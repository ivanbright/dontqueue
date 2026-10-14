"""Bridge between the project's data and the ``exportkit`` package.

``exportkit`` is a general-purpose library (published on PyPI) with no knowledge
of Django; everything below is the thin, project-specific adapter that maps
querysets onto :class:`exportkit.Report` objects and streams the result back as
an HTTP response.
"""

from __future__ import annotations

from django.http import Http404, HttpResponse
from exportkit import Column, Format, Report, render
from exportkit.exceptions import UnsupportedFormatError

WALK_IN = "Walk-in customer"


def _timestamp(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _customer_name(entry):
    return entry.customer.full_name if entry.customer_id else WALK_IN


def file_response(report, fmt, stem):
    """Render ``report`` to ``fmt`` (``xlsx``/``docx``/``pdf``) as a download."""
    try:
        target = Format.coerce(fmt)
    except UnsupportedFormatError:
        raise Http404(f"Unsupported export format: {fmt!r}")
    response = HttpResponse(render(report, target), content_type=target.content_type)
    response["Content-Disposition"] = f'attachment; filename="{target.filename(stem)}"'
    return response


def tickets_report(organization):
    from queues.models import QueueEntry

    entries = (
        QueueEntry.objects.filter(queue__service__branch__organization=organization)
        .select_related("queue", "queue__service", "queue__service__branch", "customer")
        .order_by("-joined_at")
    )
    rows = [
        {
            "number": entry.number,
            "customer": _customer_name(entry),
            "service": entry.queue.service.name,
            "branch": entry.queue.service.branch.name,
            "status": entry.get_status_display(),
            "priority": entry.priority,
            "joined": entry.joined_at,
        }
        for entry in entries
    ]
    report = Report(
        title="Tickets",
        subtitle=organization.name,
        columns=[
            Column("Ticket", key="number", align="right"),
            Column("Customer", key="customer"),
            Column("Service", key="service"),
            Column("Branch", key="branch"),
            Column("Status", key="status"),
            Column("Priority", key="priority", align="right"),
            Column("Joined", key="joined", format=_timestamp),
        ],
        rows=rows,
        summary={"Tickets": len(rows)},
        footer=f"{organization.name} · Don't Queue",
        sheet_name="Tickets",
        landscape=True,
    )
    return report, f"{organization.slug}-tickets"


def services_report(organization):
    from directory.models import Service

    services = (
        Service.objects.filter(branch__organization=organization)
        .select_related("branch")
        .order_by("branch__name", "name")
    )
    rows = [
        {
            "branch": service.branch.name,
            "code": service.code,
            "service": service.name,
            "avg": service.avg_service_minutes,
            "remote": "Yes" if service.allow_remote_join else "No",
            "active": "Yes" if service.is_active else "No",
        }
        for service in services
    ]
    report = Report(
        title="Services",
        subtitle=organization.name,
        columns=[
            Column("Branch", key="branch"),
            Column("Code", key="code"),
            Column("Service", key="service"),
            Column("Avg minutes", key="avg", align="right"),
            Column("Remote join", key="remote"),
            Column("Active", key="active"),
        ],
        rows=rows,
        summary={"Services": len(rows)},
        footer=f"{organization.name} · Don't Queue",
        sheet_name="Services",
    )
    return report, f"{organization.slug}-services"


def audit_report(organization):
    from audit.models import AuditLog

    logs = (
        AuditLog.objects.filter(organization=organization)
        .select_related("actor")
        .order_by("-created_at")
    )
    rows = [
        {
            "when": log.created_at,
            "actor": log.actor.email if log.actor else "system",
            "action": log.action,
            "target": f"{log.target_type or ''} {log.target_id or ''}".strip(),
            "ip": str(log.ip_address or ""),
            "details": str(log.metadata) if log.metadata else "",
        }
        for log in logs
    ]
    report = Report(
        title="Audit log",
        subtitle=organization.name,
        columns=[
            Column("When", key="when", format=_timestamp),
            Column("Actor", key="actor"),
            Column("Action", key="action"),
            Column("Target", key="target"),
            Column("IP", key="ip"),
            Column("Details", key="details"),
        ],
        rows=rows,
        summary={"Entries": len(rows)},
        footer=f"{organization.name} · Don't Queue",
        sheet_name="Audit log",
        landscape=True,
    )
    return report, f"{organization.slug}-audit-log"


def waiting_report(queue):
    entries = list(queue.waiting_entries().select_related("customer"))
    rows = [
        {
            "number": entry.number,
            "customer": _customer_name(entry),
            "presence": entry.get_presence_display(),
            "priority": entry.priority,
            "joined": entry.joined_at,
        }
        for entry in entries
    ]
    report = Report(
        title=f"Waiting list · {queue.service.name}",
        subtitle=f"{queue.service.branch.name} · {queue.name}",
        columns=[
            Column("Ticket", key="number", align="right"),
            Column("Customer", key="customer"),
            Column("Presence", key="presence"),
            Column("Priority", key="priority", align="right"),
            Column("Joined", key="joined", format=_timestamp),
        ],
        rows=rows,
        summary={"Waiting": len(rows)},
        footer=f"{queue.service.branch.organization.name} · Don't Queue",
        sheet_name="Waiting",
    )
    return report, f"{queue.service.branch.organization.slug}-{queue.service.code}-waiting"


ORG_REPORTS = {
    "tickets": tickets_report,
    "services": services_report,
    "audit": audit_report,
}
