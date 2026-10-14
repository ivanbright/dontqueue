"""Organizational structure: branches, services, staff assignments, queue rules."""

import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.timezone import now


class Branch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="branches"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40, help_text="Short internal code, unique per organization.")
    address = models.CharField(max_length=280, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    timezone = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="unique_branch_code_per_org")
        ]
        ordering = ["organization__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.organization.name})"


class Service(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    branch = models.ForeignKey("directory.Branch", on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40)
    description = models.CharField(max_length=280, blank=True)
    avg_service_minutes = models.PositiveIntegerField(
        default=10, validators=[MinValueValidator(1)], help_text="Fallback estimate per customer."
    )
    allow_remote_join = models.BooleanField(
        default=True, help_text="Allow customers to join and wait remotely via the public page."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "code"], name="unique_service_code_per_branch")
        ]
        ordering = ["branch__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.branch.name})"

    @property
    def organization(self):
        return self.branch.organization

    @property
    def organization_id(self):
        return self.branch.organization_id

    @property
    def default_queue(self):
        """The service's primary queue, using the prefetch cache when warm."""
        return next(iter(self.queues.all()), None)


class StaffAssignment(models.Model):
    """Links a membership to a branch and (optionally) a specific service."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    membership = models.ForeignKey(
        "accounts.Membership", on_delete=models.CASCADE, related_name="assignments"
    )
    branch = models.ForeignKey("directory.Branch", on_delete=models.CASCADE, related_name="assignments")
    service = models.ForeignKey(
        "directory.Service",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assignments",
        help_text="Leave empty to cover every service in the branch.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "branch", "service"], name="unique_staff_assignment"
            )
        ]
        ordering = ["branch__name"]

    def __str__(self):
        scope = self.service.name if self.service else "all services"
        return f"{self.membership.user} -> {self.branch.name} / {scope}"


class QueueRule(models.Model):
    """Per-service operational policy for the queue engine."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.OneToOneField(
        "directory.Service", on_delete=models.CASCADE, related_name="rule"
    )
    max_wait_minutes = models.PositiveIntegerField(default=60)
    auto_miss_after_minutes = models.PositiveIntegerField(
        default=10, help_text="Grace period after being called before a turn is marked missed."
    )
    reopen_after_missed = models.BooleanField(
        default=True, help_text="Return a missed customer to the waiting list."
    )
    priority_enabled = models.BooleanField(default=False)
    notification_channels = models.CharField(
        max_length=120, default="inapp", help_text="Comma separated list, e.g. 'inapp,email'."
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Rules for {self.service}"

    @property
    def channel_list(self):
        return [c.strip() for c in self.notification_channels.split(",") if c.strip()]
