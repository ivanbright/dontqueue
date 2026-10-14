"""Public landing, role-aware dashboards and platform administration."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from accounts.models import Organization
from directory.models import Service
from queues.models import EntryStatus, Queue
from queues.services import queue_snapshot

from . import exports
from .permissions import OrganizationAccessMixin


def landing(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    organizations = Organization.objects.filter(is_active=True).order_by("name")[:12]
    return render(request, "core/landing.html", {"organizations": organizations})


def explore(request):
    """Public directory so customers can find a queue to join."""
    query = request.GET.get("q", "").strip()
    organizations = Organization.objects.filter(is_active=True)
    if query:
        organizations = organizations.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(branches__name__icontains=query)
            | Q(branches__services__name__icontains=query)
        ).distinct()
    organizations = organizations.annotate(
        branch_count=Count("branches", distinct=True),
        service_count=Count("branches__services", distinct=True),
    ).order_by("name")
    return render(
        request, "core/explore.html", {"organizations": organizations, "query": query}
    )


@login_required
def dashboard(request):
    if request.user.is_platform_admin:
        return redirect("core:platform")
    membership = (
        request.user.memberships.filter(is_active=True)
        .select_related("organization")
        .order_by("organization__name")
        .first()
    )
    if membership is not None:
        return redirect("org_dashboard", org_slug=membership.organization.slug)
    return redirect("accounts:onboarding")


class PlatformConsole(LoginRequiredMixin, TemplateView):
    template_name = "core/platform.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_platform_admin:
            raise PermissionDenied("Platform administrator access is required.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organizations"] = Organization.objects.annotate(
            branch_count=Count("branches", distinct=True),
            member_count=Count("memberships", distinct=True),
        ).order_by("name")
        return context


class OrgDashboard(OrganizationAccessMixin, TemplateView):
    template_name = "core/org_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = self.organization
        queues = (
            Queue.objects.filter(service__branch__organization=organization)
            .select_related("service", "service__branch")
            .order_by("service__branch__name", "service__name")
        )
        cards = [
            {
                "queue": queue,
                "snapshot": queue_snapshot(queue),
            }
            for queue in queues
        ]
        context.update(
            {
                "branches": organization.branches.filter(is_active=True),
                "services": Service.objects.filter(branch__organization=organization, is_active=True),
                "service_count": Service.objects.filter(branch__organization=organization).count(),
                "queue_cards": cards,
                "recent_entries": organizations_recent_entries(organization),
                "membership": self.membership,
                "is_admin": self._is_admin,
                "can_operate": self._can_operate,
            }
        )
        return context


class OrgExportView(OrganizationAccessMixin, View):
    """Download an organization dataset (tickets / services / audit) as a file.

    Rendered by the published ``exportkit`` package in Excel, Word or PDF.
    """

    def dispatch(self, request, *args, **kwargs):
        if kwargs["kind"] not in exports.ORG_REPORTS:
            raise Http404("Unknown export.")
        self.operator_required = True
        self.admin_required = kwargs["kind"] == "audit"
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, org_slug, kind, fmt):
        report, stem = exports.ORG_REPORTS[kind](self.organization)
        return exports.file_response(report, fmt, stem)


def organizations_recent_entries(organization):
    return (
        organization_entries(organization)
        .select_related("queue", "queue__service")
        .order_by("-joined_at")[:10]
    )


def organization_entries(organization):
    from queues.models import QueueEntry

    return QueueEntry.objects.filter(queue__service__branch__organization=organization).exclude(
        status__in=[EntryStatus.SERVED, EntryStatus.CANCELLED]
    )


def healthz(request):
    return HttpResponse("ok")
