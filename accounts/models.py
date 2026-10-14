"""Identity, tenancy and membership models."""

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils.text import slugify
from django.utils.timezone import now


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_platform_admin", True)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Platform account. Email is the login identifier."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_platform_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.full_name or self.email

    @property
    def short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email.split("@")[0]


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.CharField(max_length=280, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    owner = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="owned_organizations"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:100] or "org"
            slug = base
            index = 2
            while Organization.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{index}"
                index += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Administrator"
    BRANCH_MANAGER = "branch_manager", "Branch manager"
    RECEPTIONIST = "receptionist", "Receptionist"
    PROVIDER = "provider", "Service provider"


# Roles that may administer organization-wide settings.
ADMIN_ROLES = {Role.OWNER, Role.ADMIN}
# Roles that may operate a queue (call next, start, complete).
OPERATOR_ROLES = {Role.OWNER, Role.ADMIN, Role.BRANCH_MANAGER, Role.RECEPTIONIST, Role.PROVIDER}


class Membership(models.Model):
    """A user's role inside exactly one organization (tenant)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.PROVIDER)
    branch = models.ForeignKey(
        "directory.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships",
        help_text="Optional branch scope for managers/receptionists.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="unique_membership_per_user_org"),
            models.CheckConstraint(
                condition=~models.Q(role=""), name="membership_role_not_blank"
            ),
        ]
        ordering = ["organization__name", "user__email"]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role in ADMIN_ROLES

    @property
    def can_operate(self):
        return self.role in OPERATOR_ROLES


class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.PROVIDER)
    branch = models.ForeignKey(
        "directory.Branch", on_delete=models.SET_NULL, null=True, blank=True, related_name="invitations"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="invitations_sent"
    )
    created_at = models.DateTimeField(default=now)
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(accepted_at__isnull=True),
                name="unique_pending_invitation",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite {self.email} to {self.organization}"

    @property
    def is_expired(self):
        return self.expires_at is not None and now() >= self.expires_at

    @property
    def is_pending(self):
        return self.accepted_at is None and not self.is_expired
