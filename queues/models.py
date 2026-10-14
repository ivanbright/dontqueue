"""Queue engine models: queues, customers, entries and append-only events."""

import uuid

from django.db import models
from django.utils.timezone import now


class QueueStatus(models.TextChoices):
    OPEN = "open", "Open"
    PAUSED = "paused", "Paused"
    CLOSED = "closed", "Closed"


class EntryStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    CALLED = "called", "Called"
    IN_SERVICE = "in_service", "In service"
    SERVED = "served", "Served"
    CANCELLED = "cancelled", "Cancelled"
    MISSED_TURN = "missed_turn", "Missed turn"


class Presence(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    PRESENT = "present", "Present on site"
    REMOTE = "remote", "Waiting remotely"


class ServiceExecution(models.TextChoices):
    NOT_STARTED = "not_started", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"


TERMINAL_STATUSES = {EntryStatus.SERVED, EntryStatus.CANCELLED}
ACTIVE_STATUSES = {EntryStatus.WAITING, EntryStatus.CALLED, EntryStatus.IN_SERVICE}


class Queue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    service = models.ForeignKey(
        "directory.Service", on_delete=models.CASCADE, related_name="queues"
    )
    name = models.CharField(max_length=120, default="Main")
    status = models.CharField(max_length=16, choices=QueueStatus.choices, default=QueueStatus.OPEN)
    next_number = models.PositiveIntegerField(default=1)
    opened_at = models.DateTimeField(default=now)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["service", "name"], name="unique_queue_name_per_service")
        ]
        ordering = ["service__name", "name"]

    def __str__(self):
        return f"{self.service.name} - {self.name}"

    @property
    def organization(self):
        return self.service.branch.organization

    @property
    def organization_id(self):
        return self.service.branch.organization_id

    @property
    def branch(self):
        return self.service.branch

    @property
    def is_open(self):
        return self.status == QueueStatus.OPEN

    def waiting_entries(self):
        return self.entries.filter(status=EntryStatus.WAITING).order_by("-priority", "joined_at", "id")


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="customers"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="customer_profiles"
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "phone"],
                condition=~models.Q(phone=""),
                name="unique_customer_phone_per_org",
            )
        ]
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class QueueEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    queue = models.ForeignKey("queues.Queue", on_delete=models.CASCADE, related_name="entries")
    customer = models.ForeignKey(
        "queues.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="entries"
    )
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=EntryStatus.choices, default=EntryStatus.WAITING)
    presence = models.CharField(max_length=16, choices=Presence.choices, default=Presence.UNKNOWN)
    service_execution = models.CharField(
        max_length=16, choices=ServiceExecution.choices, default=ServiceExecution.NOT_STARTED
    )
    priority = models.IntegerField(default=0)
    idempotency_key = models.CharField(max_length=120, blank=True)
    notes = models.CharField(max_length=280, blank=True)

    joined_at = models.DateTimeField(default=now)
    called_at = models.DateTimeField(null=True, blank=True)
    service_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="entries_created"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["queue", "number"], name="unique_ticket_number_per_queue"),
            models.UniqueConstraint(
                fields=["queue", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_idempotency_key_per_queue",
            ),
        ]
        ordering = ["-priority", "joined_at", "id"]

    def __str__(self):
        return f"#{self.number} {self.get_status_display()}"

    @property
    def organization_id(self):
        return self.queue.organization_id

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self):
        return self.status in TERMINAL_STATUSES


class EventType(models.TextChoices):
    JOINED = "joined", "Joined"
    CALLED = "called", "Called"
    SERVICE_STARTED = "service_started", "Service started"
    SERVED = "served", "Served"
    CANCELLED = "cancelled", "Cancelled"
    MISSED_TURN = "missed_turn", "Missed turn"
    REOPENED = "reopened", "Reopened"
    PRESENCE_CHANGED = "presence_changed", "Presence changed"
    QUEUE_PAUSED = "queue_paused", "Queue paused"
    QUEUE_RESUMED = "queue_resumed", "Queue resumed"
    QUEUE_CLOSED = "queue_closed", "Queue closed"
    QUEUE_OPENED = "queue_opened", "Queue opened"
    NOTIFIED = "notified", "Notified"
    REQUEUED = "requeued", "Requeued"


class QueueEvent(models.Model):
    """Append-only history. Rows are never updated or deleted."""

    id = models.BigAutoField(primary_key=True)
    queue = models.ForeignKey(
        "queues.Queue", on_delete=models.CASCADE, null=True, blank=True, related_name="events"
    )
    entry = models.ForeignKey(
        "queues.QueueEntry",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, blank=True)
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="queue_events"
    )
    note = models.CharField(max_length=280, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["entry", "created_at"]),
            models.Index(fields=["queue", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} at {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Queue events are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Queue events are append-only and cannot be deleted.")

    @classmethod
    def record(cls, entry=None, event_type=None, *, queue=None, actor=None, from_status="", to_status="", note="", metadata=None):
        if entry is not None and queue is None:
            queue = entry.queue
        return cls.objects.create(
            queue=queue,
            entry=entry,
            event_type=event_type,
            actor=actor,
            from_status=from_status or "",
            to_status=to_status or "",
            note=note,
            metadata=metadata or {},
        )
