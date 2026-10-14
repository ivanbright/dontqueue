"""Forms for branches, services, staff assignments and queue rules."""

from django import forms

from core.forms import style_fields

from .models import Branch, QueueRule, Service, StaffAssignment


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "code", "address", "phone", "timezone", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            "name",
            "code",
            "description",
            "avg_service_minutes",
            "allow_remote_join",
            "is_active",
        ]

    def __init__(self, *args, organization=None, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.branch = branch
        if branch is None and organization is not None:
            self.fields["branch"] = forms.ModelChoiceField(
                queryset=organization.branches.order_by("name"),
                label="Branch",
                help_text="Where this service — and the queue it creates — belongs.",
            )
            self.order_fields(
                [
                    "branch",
                    "name",
                    "code",
                    "description",
                    "avg_service_minutes",
                    "allow_remote_join",
                    "is_active",
                ]
            )
        style_fields(self)


class StaffAssignmentForm(forms.ModelForm):
    class Meta:
        model = StaffAssignment
        fields = ["membership", "branch", "service", "is_active"]

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if organization is not None:
            self.fields["membership"].queryset = organization.memberships.select_related(
                "user"
            ).order_by("user__email")
            self.fields["branch"].queryset = organization.branches.order_by("name")
            self.fields["service"].queryset = Service.objects.filter(
                branch__organization=organization
            ).order_by("branch__name", "name")
        style_fields(self)

    def clean(self):
        cleaned = super().clean()
        service = cleaned.get("service")
        branch = cleaned.get("branch")
        if service is not None and branch is not None and service.branch_id != branch.id:
            raise forms.ValidationError("The selected service does not belong to that branch.")
        if self.organization is not None and branch is not None:
            if branch.organization_id != self.organization.id:
                raise forms.ValidationError("That branch belongs to another organization.")
        return cleaned


class QueueRuleForm(forms.ModelForm):
    class Meta:
        model = QueueRule
        fields = [
            "max_wait_minutes",
            "auto_miss_after_minutes",
            "reopen_after_missed",
            "priority_enabled",
            "notification_channels",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)
