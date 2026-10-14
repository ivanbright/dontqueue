"""Authentication, onboarding, profile and team management."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, TemplateView

from audit.models import AuditLog
from core.permissions import OrganizationAccessMixin

from .forms import (
    InvitationForm,
    OrganizationCreateForm,
    ProfileForm,
    SignupForm,
    StyledAuthenticationForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)
from .models import Invitation, Membership, Organization, Role


class SignupView(CreateView):
    form_class = SignupForm
    template_name = "accounts/signup.html"
    success_url = reverse_lazy("accounts:onboarding")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        AuditLog.record(
            action="user.registered",
            actor=self.object,
            target=self.object,
            ip_address=self.request.META.get("REMOTE_ADDR"),
        )
        messages.success(self.request, "Welcome. Create your first organization to get started.")
        return response


class AppLoginView(LoginView):
    authentication_form = StyledAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class AppLogoutView(LogoutView):
    next_page = reverse_lazy("core:landing")


class AppPasswordResetView(PasswordResetView):
    form_class = StyledPasswordResetForm
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class AppPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class AppPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = StyledSetPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class AppPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@login_required
def onboarding(request):
    if request.method == "POST":
        form = OrganizationCreateForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                organization = form.save(commit=False)
                organization.owner = request.user
                organization.save()
                Membership.objects.create(
                    user=request.user, organization=organization, role=Role.OWNER
                )
            AuditLog.record(
                action="organization.created",
                actor=request.user,
                organization=organization,
                target=organization,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, f"{organization.name} is ready.")
            return redirect("org_dashboard", org_slug=organization.slug)
    else:
        form = OrganizationCreateForm()
    return render(request, "accounts/onboarding.html", {"form": form})


@login_required
def profile(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def accept_invite(request, token):
    invitation = get_object_or_404(Invitation, token=token)
    if invitation.accepted_at is not None:
        messages.info(request, "That invitation has already been used.")
        return redirect("core:dashboard")
    if invitation.is_expired:
        messages.error(request, "That invitation has expired.")
        return redirect("core:dashboard")
    if request.user.email.lower() != invitation.email.lower():
        messages.error(
            request,
            f"This invitation was sent to {invitation.email}. "
            "Sign in with that address to accept it.",
        )
        return redirect("core:dashboard")

    membership, created = Membership.objects.get_or_create(
        user=request.user,
        organization=invitation.organization,
        defaults={"role": invitation.role, "branch": invitation.branch},
    )
    if not created:
        membership.role = invitation.role
        membership.is_active = True
        membership.save(update_fields=["role", "is_active"])
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    AuditLog.record(
        action="membership.joined",
        actor=request.user,
        organization=invitation.organization,
        target=membership,
    )
    messages.success(request, f"You joined {invitation.organization.name}.")
    return redirect("org_dashboard", org_slug=invitation.organization.slug)


# --------------------------------------------------------------------------
# Team management (organization scoped)
# --------------------------------------------------------------------------
class TeamView(OrganizationAccessMixin, TemplateView):
    template_name = "accounts/team.html"
    admin_required = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["memberships"] = self.organization.memberships.select_related("user", "branch")
        context["invitations"] = [
            invite
            for invite in self.organization.invitations.filter(accepted_at__isnull=True)
        ]
        context["invite_form"] = kwargs.get("invite_form") or InvitationForm(
            organization=self.organization
        )
        return context

    def post(self, request, *args, **kwargs):
        form = InvitationForm(request.POST, organization=self.organization)
        if form.is_valid():
            invitation, created = Invitation.objects.update_or_create(
                organization=self.organization,
                email=form.cleaned_data["email"],
                accepted_at__isnull=True,
                defaults={
                    "role": form.cleaned_data["role"],
                    "branch": form.cleaned_data.get("branch"),
                    "invited_by": request.user,
                    "expires_at": timezone.now() + timezone.timedelta(days=14),
                },
            )
            AuditLog.record(
                action="invitation.created" if created else "invitation.updated",
                actor=request.user,
                organization=self.organization,
                target=invitation,
                metadata={"email": invitation.email, "role": invitation.role},
            )
            verb = "created" if created else "updated"
            messages.success(request, f"Invitation {verb} for {invitation.email}.")
            return redirect("team:team", org_slug=self.organization.slug)
        context = self.get_context_data(invite_form=form)
        return self.render_to_response(context, status=400)


@login_required
def update_membership(request, org_slug, membership_id):
    from core.permissions import _authorize

    _authorize(request, admin=True)
    organization = request.organization
    membership = get_object_or_404(Membership, pk=membership_id, organization=organization)
    if request.method != "POST":
        return redirect("team:team", org_slug=organization.slug)
    action = request.POST.get("action")
    if action == "deactivate" and membership.role != Role.OWNER:
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        messages.success(request, f"{membership.user} deactivated.")
    elif action == "activate":
        membership.is_active = True
        membership.save(update_fields=["is_active"])
        messages.success(request, f"{membership.user} reactivated.")
    elif action == "role":
        new_role = request.POST.get("role")
        if new_role in Role.values and membership.role != Role.OWNER:
            membership.role = new_role
            membership.save(update_fields=["role"])
            messages.success(request, f"{membership.user} is now {membership.get_role_display()}.")
    AuditLog.record(
        action=f"membership.{action or 'update'}",
        actor=request.user,
        organization=organization,
        target=membership,
    )
    return redirect("team:team", org_slug=organization.slug)
