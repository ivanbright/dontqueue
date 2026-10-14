"""Operator console, receptionist registration and the public customer flow."""

import uuid

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core import exports
from core.permissions import OrganizationAccessMixin
from directory.models import Service

from . import services
from .forms import PublicJoinForm, RegisterForm
from .models import Customer, EntryStatus, Presence, Queue, QueueEntry, QueueEvent


def _queue_for(organization, queue_id):
    return get_object_or_404(
        Queue.objects.select_related("service", "service__branch"),
        pk=queue_id,
        service__branch__organization=organization,
    )


def _entry_for(organization, pk):
    return get_object_or_404(
        QueueEntry.objects.select_related("queue", "queue__service", "customer"),
        pk=pk,
        queue__service__branch__organization=organization,
    )


class ConsoleView(OrganizationAccessMixin, TemplateView):
    template_name = "queues/console.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queue = _queue_for(self.organization, self.kwargs["queue_id"])
        called = queue.entries.filter(status=EntryStatus.CALLED).select_related("customer").first()
        waiting = list(queue.waiting_entries().select_related("customer"))
        for entry in waiting:
            entry.estimate = services.estimate_wait(entry)
        context.update(
            {
                "queue": queue,
                "service": queue.service,
                "snapshot": services.queue_snapshot(queue),
                "called": called,
                "in_service": queue.entries.filter(status=EntryStatus.IN_SERVICE).select_related(
                    "customer"
                ),
                "waiting": waiting,
                "missed": queue.entries.filter(status=EntryStatus.MISSED_TURN)
                .select_related("customer")
                .order_by("-called_at"),
                "recent_served": queue.entries.filter(status=EntryStatus.SERVED)
                .select_related("customer")
                .order_by("-completed_at")[:8],
                "events": QueueEvent.objects.filter(queue=queue)
                .select_related("actor")
                .order_by("-created_at", "-id")[:20],
                "can_operate": self._can_operate,
                "is_admin": self._is_admin,
                "entry_statuses": EntryStatus,
            }
        )
        return context


class ConsoleExportView(OrganizationAccessMixin, View):
    """Export a queue's waiting list as Excel, Word or PDF via ``exportkit``."""

    operator_required = True

    def get(self, request, org_slug, queue_id, fmt):
        queue = _queue_for(self.organization, queue_id)
        report, stem = exports.waiting_report(queue)
        return exports.file_response(report, fmt, stem)


class CallNextView(OrganizationAccessMixin, View):
    operator_required = True

    def post(self, request, org_slug, queue_id):
        queue = _queue_for(request.organization, queue_id)
        try:
            entry = services.call_next(queue, actor=request.user)
        except services.QueueError as exc:
            messages.error(request, str(exc))
        else:
            if entry is None:
                messages.info(request, "No one is currently waiting.")
            else:
                messages.success(request, f"Called ticket #{entry.number}.")
        return redirect("queues:console", org_slug=org_slug, queue_id=queue_id)


class QueueActionView(OrganizationAccessMixin, View):
    operator_required = True
    actions = {
        "pause": services.pause_queue,
        "resume": services.open_queue,
        "close": services.close_queue,
        "open": services.open_queue,
    }

    def post(self, request, org_slug, queue_id, action):
        function = self.actions.get(action)
        if function is None:
            raise Http404("Unknown queue action.")
        queue = _queue_for(request.organization, queue_id)
        function(queue, actor=request.user)
        messages.success(request, f"Queue {action}d." if action != "resume" else "Queue reopened.")
        return redirect("queues:console", org_slug=org_slug, queue_id=queue_id)


class EntryActionView(OrganizationAccessMixin, View):
    operator_required = True
    simple = {
        "start": services.start_service,
        "complete": services.complete_service,
        "reopen": services.reopen_entry,
    }
    noted = {
        "cancel": services.cancel_entry,
        "miss": services.mark_missed,
    }

    def post(self, request, org_slug, pk, action):
        entry = _entry_for(request.organization, pk)
        try:
            if action in self.simple:
                self.simple[action](entry, actor=request.user)
            elif action in self.noted:
                self.noted[action](entry, actor=request.user, note=request.POST.get("note", ""))
            else:
                raise Http404("Unknown entry action.")
        except services.QueueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Ticket #{entry.number} is now '{entry.get_status_display()}'.")
        return redirect("queues:console", org_slug=org_slug, queue_id=entry.queue_id)


class EntryPresenceView(OrganizationAccessMixin, View):
    operator_required = True

    def post(self, request, org_slug, pk):
        entry = _entry_for(request.organization, pk)
        presence = request.POST.get("presence")
        try:
            services.set_presence(entry, presence, actor=request.user)
        except services.QueueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Ticket #{entry.number} marked {entry.get_presence_display()}.")
        return redirect("queues:console", org_slug=org_slug, queue_id=entry.queue_id)


class RegisterView(OrganizationAccessMixin, TemplateView):
    template_name = "queues/register.html"
    operator_required = True

    def get_service(self):
        return get_object_or_404(
            Service.objects.select_related("branch"),
            pk=self.kwargs["service_id"],
            branch__organization=self.organization,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = self.get_service()
        context["service"] = service
        context["queue"] = services.ensure_queue(service)
        context["form"] = kwargs.get("form") or RegisterForm()
        return context

    def post(self, request, *args, **kwargs):
        service = self.get_service()
        form = RegisterForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form), status=400)

        data = form.cleaned_data
        customer = None
        if data.get("phone"):
            customer, _ = Customer.objects.get_or_create(
                organization=self.organization,
                phone=data["phone"],
                defaults={"full_name": data["full_name"], "email": data.get("email", "")},
            )
        elif data.get("email"):
            customer, _ = Customer.objects.get_or_create(
                organization=self.organization,
                email=data["email"],
                defaults={"full_name": data["full_name"]},
            )

        queue = services.ensure_queue(service)
        try:
            entry, created = services.join_queue(
                queue,
                full_name=data["full_name"],
                phone=data.get("phone", ""),
                email=data.get("email", ""),
                customer=customer,
                remote=False,
                priority=data.get("priority") or 0,
                actor=request.user,
                note=data.get("note", ""),
            )
        except services.QueueError as exc:
            messages.error(request, str(exc))
            return redirect("queues:console", org_slug=self.organization.slug, queue_id=queue.id)

        messages.success(request, f"Registered ticket #{entry.number} for {data['full_name']}.")
        return redirect("queues:console", org_slug=self.organization.slug, queue_id=queue.id)


# --------------------------------------------------------------------------
# Public (unauthenticated) customer flow
# --------------------------------------------------------------------------
class PublicJoinView(TemplateView):
    template_name = "queues/public_join.html"

    def get_organization(self):
        organization = getattr(self.request, "organization", None)
        if organization is None:
            raise Http404("Organization not found.")
        return organization

    def get_services(self, organization):
        return Service.objects.filter(
            branch__organization=organization, is_active=True, allow_remote_join=True
        ).select_related("branch")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.get_organization()
        context["organization"] = organization
        context["services"] = self.get_services(organization)
        context["form"] = kwargs.get("form") or PublicJoinForm()
        context["submission_id"] = kwargs.get("submission_id") or uuid.uuid4().hex
        return context

    def post(self, request, *args, **kwargs):
        organization = self.get_organization()
        form = PublicJoinForm(request.POST)
        service_id = request.POST.get("service_id")
        services_qs = self.get_services(organization)
        if not services_qs.filter(pk=service_id).exists():
            raise Http404("Service not available for remote joining.")
        if not form.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, submission_id=request.POST.get("submission_id"))
            )
        service = services_qs.get(pk=service_id)
        queue = services.ensure_queue(service)
        data = form.cleaned_data
        customer = None
        if data.get("phone"):
            customer, _ = Customer.objects.get_or_create(
                organization=organization,
                phone=data["phone"],
                defaults={"full_name": data["full_name"], "email": data.get("email", "")},
            )
        entry, created = services.join_queue(
            queue,
            full_name=data["full_name"],
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            customer=customer,
            remote=True,
            idempotency_key=request.POST.get("submission_id", ""),
        )
        return redirect("public:status", org_slug=organization.slug, reference=entry.reference)


class StatusView(TemplateView):
    template_name = "queues/status.html"

    def get_entry(self):
        return get_object_or_404(
            QueueEntry.objects.select_related(
                "queue", "queue__service", "queue__service__branch", "queue__service__branch__organization"
            ),
            reference=self.kwargs["reference"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entry = self.get_entry()
        context["entry"] = entry
        context["organization"] = entry.queue.organization
        context["service"] = entry.queue.service
        context["position"] = services.position_of(entry)
        context["estimate"] = services.estimate_wait(entry)
        context["events"] = entry.events.all()
        return context


def status_json(request, org_slug, reference):
    entry = get_object_or_404(
        QueueEntry.objects.select_related("queue", "queue__service"), reference=reference
    )
    estimate = services.estimate_wait(entry)
    return JsonResponse(
        {
            "number": entry.number,
            "status": entry.status,
            "status_label": entry.get_status_display(),
            "position": services.position_of(entry),
            "presence": entry.presence,
            "approx_wait_seconds": estimate["approx_wait_seconds"],
            "estimate_source": estimate["source"],
            "computed_at": estimate["computed_at"].isoformat(),
            "service": entry.queue.service.name,
            "organization": entry.queue.organization.name,
        }
    )
