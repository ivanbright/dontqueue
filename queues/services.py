"""Queue engine service layer.

All state changes to queues and entries flow through these functions so that
transitions, event history, notifications and audit logging stay consistent.
The module is deliberately free of any industry-specific logic.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from audit.models import AuditLog
from directory.models import QueueRule, StaffAssignment
from notifications.models import Notification
from notifications.providers import dispatch

from .models import (
    ACTIVE_STATUSES,
    EntryStatus,
    EventType,
    Presence,
    Queue,
    QueueEntry,
    QueueEvent,
    QueueStatus,
    ServiceExecution,
    TERMINAL_STATUSES,
)


class QueueError(Exception):
    """Base class for expected, user-facing queue errors."""


class QueueNotOpen(QueueError):
    pass


class InvalidTransition(QueueError):
    pass


class DuplicateSubmission(QueueError):
    pass


ALLOWED_TRANSITIONS = {
    EntryStatus.WAITING: {EntryStatus.CALLED, EntryStatus.CANCELLED},
    EntryStatus.CALLED: {EntryStatus.IN_SERVICE, EntryStatus.MISSED_TURN, EntryStatus.CANCELLED},
    EntryStatus.IN_SERVICE: {EntryStatus.SERVED, EntryStatus.CANCELLED},
    EntryStatus.MISSED_TURN: {EntryStatus.WAITING},
    EntryStatus.SERVED: set(),
    EntryStatus.CANCELLED: set(),
}

_CLAIM_RETRIES = 64


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def rule_for(service) -> QueueRule:
    rule, _ = QueueRule.objects.get_or_create(service=service)
    return rule


def ensure_queue(service, name: str = "Main") -> Queue:
    """Return the service's default queue, creating it if needed."""
    queue, _ = Queue.objects.get_or_create(service=service, name=name)
    return queue


def _audit(entry, action, actor):
    AuditLog.record(
        action=action,
        actor=actor,
        organization=entry.queue.organization,
        target=entry,
        metadata={"number": entry.number, "reference": str(entry.reference), "status": entry.status},
    )


def _assert_transition(entry, to_status):
    if to_status not in ALLOWED_TRANSITIONS.get(entry.status, set()):
        raise InvalidTransition(
            f"A customer that is currently '{entry.get_status_display()}' "
            f"cannot become '{EntryStatus(to_status).label}'."
        )


def _record(entry, event_type, *, actor, from_status, to_status, note="", metadata=None):
    return QueueEvent.record(
        entry,
        event_type,
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        note=note,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# joining
# ---------------------------------------------------------------------------
def _claim_number(queue: Queue) -> int:
    """Reserve the next ticket number with a compare-and-set loop.

    Portable across SQLite and PostgreSQL without relying on row locks.
    """
    for _ in range(_CLAIM_RETRIES):
        current = Queue.objects.filter(pk=queue.pk).values_list("next_number", flat=True).first()
        if current is None:
            raise QueueError("Queue no longer exists.")
        updated = Queue.objects.filter(pk=queue.pk, next_number=current).update(next_number=current + 1)
        if updated:
            return current
    raise QueueError("Could not allocate a ticket number, please retry.")


def join_queue(
    queue: Queue,
    *,
    full_name: str,
    phone: str = "",
    email: str = "",
    customer=None,
    remote: bool = False,
    priority: int = 0,
    idempotency_key: str = "",
    actor=None,
    note: str = "",
) -> tuple[QueueEntry, bool]:
    """Add a customer to the queue.

    Returns ``(entry, created)``. Passing the same ``idempotency_key`` twice
    yields the original entry (created=False) instead of a duplicate.
    """
    if queue.status == QueueStatus.CLOSED:
        raise QueueNotOpen("This queue is closed.")

    if idempotency_key:
        existing = QueueEntry.objects.filter(queue=queue, idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing, False

    rule = rule_for(queue.service)
    effective_priority = priority if rule.priority_enabled else 0

    with transaction.atomic():
        number = _claim_number(queue)
        try:
            entry = QueueEntry.objects.create(
                queue=queue,
                number=number,
                customer=customer,
                priority=effective_priority,
                presence=Presence.REMOTE if remote else Presence.PRESENT,
                idempotency_key=idempotency_key,
                created_by=actor if getattr(actor, "is_authenticated", False) else None,
                notes=note,
            )
        except Exception:
            if idempotency_key:
                existing = QueueEntry.objects.filter(
                    queue=queue, idempotency_key=idempotency_key
                ).first()
                if existing is not None:
                    return existing, False
            raise

    _record(
        entry,
        EventType.JOINED,
        actor=actor,
        from_status="",
        to_status=EntryStatus.WAITING,
        note=note,
        metadata={"remote": remote, "priority": effective_priority, "name": full_name},
    )
    _audit(entry, "queue.joined", actor)
    _notify(entry, "joined", actor=actor)
    return entry, True


# ---------------------------------------------------------------------------
# serving lifecycle
# ---------------------------------------------------------------------------
def call_next(queue: Queue, actor=None) -> QueueEntry | None:
    if queue.status != QueueStatus.OPEN:
        raise QueueNotOpen("The queue must be open before calling the next customer.")

    candidate = None
    for _ in range(_CLAIM_RETRIES):
        candidate = (
            QueueEntry.objects.filter(queue=queue, status=EntryStatus.WAITING)
            .order_by("-priority", "joined_at", "id")
            .first()
        )
        if candidate is None:
            return None
        updated = QueueEntry.objects.filter(pk=candidate.pk, status=EntryStatus.WAITING).update(
            status=EntryStatus.CALLED, called_at=timezone.now()
        )
        if updated:
            break
        candidate = None
    if candidate is None:
        return None

    candidate.refresh_from_db()
    _record(
        candidate,
        EventType.CALLED,
        actor=actor,
        from_status=EntryStatus.WAITING,
        to_status=EntryStatus.CALLED,
    )
    _audit(candidate, "queue.called", actor)
    _notify(candidate, "called", actor=actor)
    return candidate


def start_service(entry: QueueEntry, actor=None) -> QueueEntry:
    _assert_transition(entry, EntryStatus.IN_SERVICE)
    from_status = entry.status
    entry.status = EntryStatus.IN_SERVICE
    entry.service_execution = ServiceExecution.IN_PROGRESS
    entry.service_started_at = timezone.now()
    entry.save(update_fields=["status", "service_execution", "service_started_at"])
    _record(entry, EventType.SERVICE_STARTED, actor=actor, from_status=from_status, to_status=entry.status)
    _audit(entry, "queue.service_started", actor)
    return entry


def complete_service(entry: QueueEntry, actor=None) -> QueueEntry:
    _assert_transition(entry, EntryStatus.SERVED)
    from_status = entry.status
    entry.status = EntryStatus.SERVED
    entry.service_execution = ServiceExecution.COMPLETED
    entry.completed_at = timezone.now()
    entry.save(update_fields=["status", "service_execution", "completed_at"])
    _record(entry, EventType.SERVED, actor=actor, from_status=from_status, to_status=entry.status)
    _audit(entry, "queue.served", actor)
    _notify(entry, "served", actor=actor)
    return entry


def cancel_entry(entry: QueueEntry, actor=None, note="") -> QueueEntry:
    if entry.status not in ACTIVE_STATUSES:
        raise InvalidTransition("Only active entries can be cancelled.")
    from_status = entry.status
    entry.status = EntryStatus.CANCELLED
    entry.cancelled_at = timezone.now()
    entry.save(update_fields=["status", "cancelled_at"])
    _record(entry, EventType.CANCELLED, actor=actor, from_status=from_status, to_status=entry.status, note=note)
    _audit(entry, "queue.cancelled", actor)
    return entry


def mark_missed(entry: QueueEntry, actor=None, note="") -> QueueEntry:
    _assert_transition(entry, EntryStatus.MISSED_TURN)
    from_status = entry.status
    entry.status = EntryStatus.MISSED_TURN
    entry.save(update_fields=["status"])
    _record(entry, EventType.MISSED_TURN, actor=actor, from_status=from_status, to_status=entry.status, note=note)
    _audit(entry, "queue.missed_turn", actor)
    return entry


def reopen_entry(entry: QueueEntry, actor=None) -> QueueEntry:
    rule = rule_for(entry.queue.service)
    if not rule.reopen_after_missed:
        raise InvalidTransition("Reopening missed turns is disabled for this service.")
    _assert_transition(entry, EntryStatus.WAITING)
    from_status = entry.status
    entry.status = EntryStatus.WAITING
    entry.called_at = None
    entry.save(update_fields=["status", "called_at"])
    _record(entry, EventType.REOPENED, actor=actor, from_status=from_status, to_status=entry.status)
    _audit(entry, "queue.reopened", actor)
    return entry


def set_presence(entry: QueueEntry, presence: str, actor=None) -> QueueEntry:
    if presence not in Presence.values:
        raise QueueError("Unknown presence state.")
    previous = entry.presence
    entry.presence = presence
    entry.save(update_fields=["presence"])
    _record(
        entry,
        EventType.PRESENCE_CHANGED,
        actor=actor,
        from_status=entry.status,
        to_status=entry.status,
        metadata={"from": previous, "to": presence},
    )
    return entry


# ---------------------------------------------------------------------------
# queue-level lifecycle
# ---------------------------------------------------------------------------
def _queue_event(queue, event_type, *, actor, note=""):
    QueueEvent.record(
        None, event_type, queue=queue, actor=actor, to_status=queue.status, note=note
    )


def pause_queue(queue: Queue, actor=None, note="") -> Queue:
    queue.status = QueueStatus.PAUSED
    queue.save(update_fields=["status"])
    _queue_event(queue, EventType.QUEUE_PAUSED, actor=actor, note=note)
    AuditLog.record(action="queue.paused", actor=actor, organization=queue.organization, target=queue)
    return queue


def open_queue(queue: Queue, actor=None) -> Queue:
    queue.status = QueueStatus.OPEN
    queue.opened_at = queue.opened_at or timezone.now()
    queue.closed_at = None
    queue.save(update_fields=["status", "opened_at", "closed_at"])
    _queue_event(queue, EventType.QUEUE_OPENED, actor=actor)
    AuditLog.record(action="queue.opened", actor=actor, organization=queue.organization, target=queue)
    return queue


def close_queue(queue: Queue, actor=None, note="") -> Queue:
    queue.status = QueueStatus.CLOSED
    queue.closed_at = timezone.now()
    queue.save(update_fields=["status", "closed_at"])
    _queue_event(queue, EventType.QUEUE_CLOSED, actor=actor, note=note)
    AuditLog.record(action="queue.closed", actor=actor, organization=queue.organization, target=queue)
    return queue


# ---------------------------------------------------------------------------
# estimates
# ---------------------------------------------------------------------------
def active_provider_count(service) -> int:
    direct = (
        StaffAssignment.objects.filter(service=service, is_active=True)
        .values("membership_id")
        .distinct()
        .count()
    )
    if direct:
        return direct
    branch_wide = (
        StaffAssignment.objects.filter(branch=service.branch, service__isnull=True, is_active=True)
        .values("membership_id")
        .distinct()
        .count()
    )
    return max(1, branch_wide)


def observed_avg_service_seconds(service, sample: int = 20) -> float | None:
    entries = QueueEntry.objects.filter(
        queue__service=service,
        status=EntryStatus.SERVED,
        service_started_at__isnull=False,
        completed_at__isnull=False,
    ).order_by("-completed_at")[:sample]
    durations = [
        (entry.completed_at - entry.service_started_at).total_seconds()
        for entry in entries
        if entry.completed_at and entry.service_started_at
    ]
    if not durations:
        return None
    return sum(durations) / len(durations)


def position_of(entry: QueueEntry) -> int:
    """1-based position among waiting entries, or 0 if not waiting."""
    if entry.status != EntryStatus.WAITING:
        return 0
    ahead = (
        QueueEntry.objects.filter(queue=entry.queue, status=EntryStatus.WAITING)
        .filter(
            Q(priority__gt=entry.priority)
            | Q(priority=entry.priority, joined_at__lt=entry.joined_at)
            | Q(priority=entry.priority, joined_at=entry.joined_at, id__lt=entry.id)
        )
        .count()
    )
    return ahead + 1


def estimate_wait(entry: QueueEntry) -> dict:
    """Deterministic, clearly-approximate wait estimate."""
    now = timezone.now()
    service = entry.queue.service
    position = position_of(entry)
    avg = observed_avg_service_seconds(service)
    source = "observed"
    if avg is None:
        avg = service.avg_service_minutes * 60
        source = "configured"
    capacity = active_provider_count(service)
    ahead = max(0, position - 1)
    seconds = int(ahead * avg / capacity)
    limit = rule_for(service).max_wait_minutes * 60
    return {
        "position": position,
        "approx_wait_seconds": seconds,
        "approximate": True,
        "source": source,
        "capacity": capacity,
        "computed_at": now,
        "exceeds_max_wait": seconds > limit,
        "available": entry.status == EntryStatus.WAITING,
    }


def queue_snapshot(queue: Queue) -> dict:
    waiting = queue.entries.filter(status=EntryStatus.WAITING)
    return {
        "status": queue.get_status_display(),
        "waiting": waiting.count(),
        "called": queue.entries.filter(status=EntryStatus.CALLED).count(),
        "in_service": queue.entries.filter(status=EntryStatus.IN_SERVICE).count(),
        "served": queue.entries.filter(status=EntryStatus.SERVED).count(),
        "missed": queue.entries.filter(status=EntryStatus.MISSED_TURN).count(),
        "cancelled": queue.entries.filter(status=EntryStatus.CANCELLED).count(),
        "longest_wait_seconds": _longest_wait_seconds(queue),
        "computed_at": timezone.now(),
    }


def _longest_wait_seconds(queue: Queue) -> int:
    oldest = (
        queue.entries.filter(status=EntryStatus.WAITING).order_by("joined_at").values_list("joined_at", flat=True).first()
    )
    if oldest is None:
        return 0
    return int((timezone.now() - oldest).total_seconds())


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------
_TEMPLATES = {
    "joined": ("You joined the queue", "You are number {number} in line."),
    "called": ("It's your turn", "Number {number}, please proceed to the desk."),
    "served": ("Service complete", "Thank you, your visit is complete."),
}


def _notify(entry: QueueEntry, template: str, actor=None):
    rule = rule_for(entry.queue.service)
    subject, body_tmpl = _TEMPLATES.get(template, ("Queue update", "Queue update."))
    body = body_tmpl.format(number=entry.number)
    for channel in rule.channel_list or ["inapp"]:
        notification = Notification.objects.create(
            organization_id=entry.organization_id,
            entry=entry,
            recipient_address=(entry.customer.email if entry.customer else ""),
            channel=channel,
            template=template,
            subject=subject,
            body=body,
            payload={"number": entry.number, "reference": str(entry.reference)},
        )
        dispatch(notification)
        _record(
            entry,
            EventType.NOTIFIED,
            actor=actor,
            from_status=entry.status,
            to_status=entry.status,
            metadata={"channel": channel, "template": template},
        )
