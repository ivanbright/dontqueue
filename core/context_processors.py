"""Template context available to every page."""

from django.conf import settings

from accounts.models import Membership


def platform(request):
    organization = getattr(request, "organization", None)
    memberships = []
    current_membership = None
    if request.user.is_authenticated:
        memberships = list(
            Membership.objects.filter(user=request.user, is_active=True)
            .select_related("organization")
            .order_by("organization__name")
        )
        if organization is not None:
            current_membership = next(
                (m for m in memberships if m.organization_id == organization.id), None
            )
    is_platform_admin = getattr(request.user, "is_platform_admin", False)
    current_is_admin = bool(
        is_platform_admin or (current_membership and current_membership.is_admin)
    )
    current_can_operate = bool(
        is_platform_admin or (current_membership and current_membership.can_operate)
    )
    return {
        "PLATFORM_NAME": "Don't Queue",
        "current_organization": organization,
        "current_membership": current_membership,
        "current_is_admin": current_is_admin,
        "current_can_operate": current_can_operate,
        "user_memberships": memberships,
        "poll_interval_seconds": settings.POLL_INTERVAL_SECONDS,
    }
