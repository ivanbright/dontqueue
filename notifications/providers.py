"""Notification delivery providers.

The queue engine never talks to a specific transport. It creates a
``Notification`` row and calls :func:`dispatch`, which selects a provider by
channel. Local development needs no credentials: the in-app and console
providers are always available, and email uses Django's console backend by
default.
"""

from django.conf import settings
from django.core.mail import send_mail

from .models import Channel, NotificationStatus


class BaseProvider:
    channel: str = ""

    def send(self, notification):
        raise NotImplementedError


class InAppProvider(BaseProvider):
    """Messages surfaced by browser polling; delivered as soon as stored."""

    channel = Channel.INAPP

    def send(self, notification):
        notification.mark(NotificationStatus.DELIVERED)
        return True


class EmailProvider(BaseProvider):
    channel = Channel.EMAIL

    def send(self, notification):
        try:
            send_mail(
                notification.subject or "Don't Queue",
                notification.body or "",
                getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@dontqueue.local"),
                [notification.recipient_address] if notification.recipient_address else [],
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            notification.mark(NotificationStatus.FAILED, error=str(exc))
            return False
        notification.mark(NotificationStatus.SENT)
        return True


class ConsoleProvider(BaseProvider):
    """Fallback/development transport that logs to stdout."""

    channel = Channel.SMS

    def send(self, notification):
        print(
            f"[notification:{notification.channel}] "
            f"{notification.recipient_address or notification.recipient_user} "
            f"{notification.subject} {notification.body}"
        )
        notification.mark(NotificationStatus.SENT)
        return True


_PROVIDERS = {
    Channel.INAPP: InAppProvider(),
    Channel.EMAIL: EmailProvider(),
    Channel.SMS: ConsoleProvider(),
}


def get_provider(channel):
    return _PROVIDERS.get(channel, ConsoleProvider())


def dispatch(notification):
    """Send one notification, recording the outcome. Returns True on success."""
    provider = get_provider(notification.channel)
    notification.attempts += 1
    notification.save(update_fields=["attempts"])
    try:
        return bool(provider.send(notification))
    except Exception as exc:  # noqa: BLE001 - never let delivery break the queue
        notification.mark(NotificationStatus.FAILED, error=str(exc))
        return False
