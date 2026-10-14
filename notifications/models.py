"""Provider-independent notification records."""

import uuid

from django.db import models
from django.utils.timezone import now


class Channel(models.TextChoices):
    INAPP = "inapp", "In-app"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"


class NotificationStatus(models.TextChoices):
    CREATED = "created", "Created"
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    FAILED = "failed", "Failed"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="notifications"
    )
    entry = models.ForeignKey(
        "queues.QueueEntry", on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )
    recipient_user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    recipient_address = models.CharField(max_length=254, blank=True)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.INAPP)
    template = models.CharField(max_length=64, default="generic")
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=NotificationStatus.choices, default=NotificationStatus.CREATED
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(default=now)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["entry", "created_at"])]

    def __str__(self):
        return f"{self.get_channel_display()} -> {self.recipient_address or self.recipient_user} ({self.status})"

    def mark(self, status, *, error=""):
        self.status = status
        timestamp = now()
        if status in {NotificationStatus.SENT, NotificationStatus.DELIVERED, NotificationStatus.ACKNOWLEDGED}:
            self.sent_at = self.sent_at or timestamp
        if status in {NotificationStatus.DELIVERED, NotificationStatus.ACKNOWLEDGED}:
            self.delivered_at = self.delivered_at or timestamp
        if status == NotificationStatus.ACKNOWLEDGED:
            self.acknowledged_at = timestamp
        if error:
            self.last_error = error[:280]
        self.save(
            update_fields=[
                "status",
                "sent_at",
                "delivered_at",
                "acknowledged_at",
                "last_error",
            ]
        )
