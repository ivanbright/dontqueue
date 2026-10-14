"""Forms for signup, onboarding, invitations and profile."""

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.utils import timezone

from .models import Invitation, Organization, Role, User


def _style(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxInput,)):
            continue
        existing = widget.attrs.get("class", "")
        widget.attrs["class"] = (existing + " input").strip()
    return fields


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        _style(self.fields)


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class SignupForm(UserCreationForm):
    full_name = forms.CharField(label="Full name", max_length=150, required=False)

    class Meta:
        model = User
        fields = ["email", "full_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        _style(self.fields)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class OrganizationCreateForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "description", "timezone"]
        labels = {"name": "Organization name", "description": "Short description"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class InvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["email", "role", "branch"]
        labels = {"email": "Teammate email"}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if organization is not None:
            self.fields["branch"].queryset = organization.branches.all()
        self.fields["role"].choices = [
            choice for choice in Role.choices if choice[0] != Role.OWNER
        ]
        _style(self.fields)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if self.organization and self.organization.memberships.filter(user__email=email).exists():
            raise forms.ValidationError("That person is already a member of this organization.")
        return email

    def save(self, commit=True):
        invitation = super().save(commit=False)
        invitation.organization = self.organization
        if invitation.expires_at is None:
            invitation.expires_at = timezone.now() + timezone.timedelta(days=14)
        if commit:
            invitation.save()
        return invitation
