"""Branch, service, staff and queue-rule management (organization scoped)."""

from django.contrib import messages
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, TemplateView, UpdateView

from audit.models import AuditLog
from core.permissions import OrganizationAccessMixin

from .forms import BranchForm, QueueRuleForm, ServiceForm, StaffAssignmentForm
from .models import Branch, QueueRule, Service, StaffAssignment


class BranchListView(OrganizationAccessMixin, TemplateView):
    template_name = "directory/branches.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["branches"] = self.organization.branches.annotate(
            service_count=Count("services", distinct=True)
        )
        context["is_admin"] = self._is_admin
        return context


class BranchCreateView(OrganizationAccessMixin, CreateView):
    model = Branch
    form_class = BranchForm
    template_name = "directory/branch_form.html"
    admin_required = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["heading"] = "New branch"
        return context

    def form_valid(self, form):
        form.instance.organization = self.organization
        response = super().form_valid(form)
        AuditLog.record(
            action="branch.created",
            actor=self.request.user,
            organization=self.organization,
            target=self.object,
        )
        messages.success(self.request, f"Branch '{self.object.name}' created.")
        return response

    def get_success_url(self):
        return reverse("directory:branches", args=[self.organization.slug])


class BranchUpdateView(OrganizationAccessMixin, UpdateView):
    model = Branch
    form_class = BranchForm
    template_name = "directory/branch_form.html"
    admin_required = True

    def get_queryset(self):
        return Branch.objects.filter(organization=self.organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["heading"] = f"Edit {self.object.name}"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        AuditLog.record(
            action="branch.updated",
            actor=self.request.user,
            organization=self.organization,
            target=self.object,
        )
        messages.success(self.request, "Branch updated.")
        return response

    def get_success_url(self):
        return reverse("directory:branches", args=[self.organization.slug])


class ServiceListView(OrganizationAccessMixin, TemplateView):
    template_name = "directory/services.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["services"] = (
            Service.objects.filter(branch__organization=self.organization)
            .select_related("branch")
            .prefetch_related("queues")
            .order_by("branch__name", "name")
        )
        context["is_admin"] = self._is_admin
        return context


class ServiceCreateView(OrganizationAccessMixin, CreateView):
    model = Service
    form_class = ServiceForm
    template_name = "directory/service_form.html"
    admin_required = True

    def get_branch(self):
        branch_id = self.kwargs.get("branch_id")
        if not branch_id:
            return None
        return get_object_or_404(
            Branch, pk=branch_id, organization=self.organization
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organization"] = self.organization
        kwargs["branch"] = self.get_branch()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["heading"] = "New service"
        context["branch"] = self.get_branch()
        return context

    def form_valid(self, form):
        branch = self.get_branch() or form.cleaned_data.get("branch")
        if branch is None:
            form.add_error("branch", "Choose a branch for this service.")
            return self.form_invalid(form)
        form.instance.branch = branch
        response = super().form_valid(form)
        from queues.services import ensure_queue

        ensure_queue(self.object)
        AuditLog.record(
            action="service.created",
            actor=self.request.user,
            organization=self.organization,
            target=self.object,
        )
        messages.success(self.request, f"Service '{self.object.name}' created with a live queue.")
        return response

    def get_success_url(self):
        return reverse("directory:services", args=[self.organization.slug])


class ServiceUpdateView(OrganizationAccessMixin, UpdateView):
    model = Service
    form_class = ServiceForm
    template_name = "directory/service_form.html"
    admin_required = True

    def get_queryset(self):
        return Service.objects.filter(branch__organization=self.organization)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["heading"] = f"Edit {self.object.name}"
        context["branch"] = self.object.branch
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        AuditLog.record(
            action="service.updated",
            actor=self.request.user,
            organization=self.organization,
            target=self.object,
        )
        messages.success(self.request, "Service updated.")
        return response

    def get_success_url(self):
        return reverse("directory:services", args=[self.organization.slug])


class StaffView(OrganizationAccessMixin, TemplateView):
    template_name = "directory/staff.html"
    admin_required = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["assignments"] = (
            StaffAssignment.objects.filter(membership__organization=self.organization)
            .select_related("membership__user", "branch", "service")
            .order_by("membership__user__email")
        )
        context["form"] = kwargs.get("form") or StaffAssignmentForm(organization=self.organization)
        return context

    def post(self, request, *args, **kwargs):
        form = StaffAssignmentForm(request.POST, organization=self.organization)
        if form.is_valid():
            assignment = form.save()
            AuditLog.record(
                action="staff.assigned",
                actor=request.user,
                organization=self.organization,
                target=assignment,
            )
            messages.success(request, "Staff assignment saved.")
            return redirect("directory:staff", org_slug=self.organization.slug)
        return self.render_to_response(self.get_context_data(form=form), status=400)


class RuleUpdateView(OrganizationAccessMixin, UpdateView):
    model = QueueRule
    form_class = QueueRuleForm
    template_name = "directory/service_rules.html"
    admin_required = True

    def get_object(self, queryset=None):
        service = get_object_or_404(
            Service, pk=self.kwargs["service_id"], branch__organization=self.organization
        )
        rule, _ = QueueRule.objects.get_or_create(service=service)
        self.service = service
        return rule

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["service"] = self.service
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Queue rules updated.")
        return response

    def get_success_url(self):
        return reverse("directory:services", args=[self.organization.slug])
