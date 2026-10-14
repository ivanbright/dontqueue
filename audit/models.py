"""Append-only audit trail for privileged actions."""

from django.db import models
from django.utils.timezone import now


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs"
    )
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "created_at"])]

    def __str__(self):
        return f"{self.action} by {self.actor or 'system'} at {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Audit logs are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit logs are append-only and cannot be deleted.")

    @classmethod
    def record(cls, *, action, actor=None, organization=None, target=None, metadata=None, ip_address=None):
        target_type = target_id = ""
        if target is not None:
            target_type = target.__class__.__name__
            target_id = str(getattr(target, "pk", ""))
        return cls.objects.create(
            action=action,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            organization=organization,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
            ip_address=ip_address,
        )
