"""Server-side authorization helpers.

Permissions are always evaluated here (or in the view/service layer), never
via template conditionals, so a hidden button can never grant access.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404


def get_membership(user, organization):
    if not getattr(user, "is_authenticated", False) or organization is None:
        return None
    from accounts.models import Membership

    return (
        Membership.objects.filter(organization=organization, user=user, is_active=True)
        .select_related("organization", "branch")
        .first()
    )


def _authorize(request, *, admin=False, operator=False):
    organization = getattr(request, "organization", None)
    if organization is None:
        raise Http404("Organization not found.")
    membership = get_membership(request.user, organization)
    is_platform = getattr(request.user, "is_platform_admin", False)
    if membership is None and not is_platform:
        raise PermissionDenied("You are not a member of this organization.")
    if admin and not (is_platform or (membership and membership.is_admin)):
        raise PermissionDenied("Administrator access is required.")
    if operator and not (is_platform or (membership and membership.can_operate)):
        raise PermissionDenied("Queue operator access is required.")
    request.membership = membership
    request.organization = organization
    return membership


def organization_required(*, admin=False, operator=False):
    """Decorator for function views scoped to an organization."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            _authorize(request, admin=admin, operator=operator)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class OrganizationAccessMixin(LoginRequiredMixin, AccessMixin):
    """Resolve the current organization and enforce membership/roles."""

    admin_required = False
    operator_required = False

    def dispatch(self, request, *args, **kwargs):
        self.organization = getattr(request, "organization", None)
        if self.organization is None:
            raise Http404("Organization not found.")
        self.membership = get_membership(request.user, self.organization)
        self.is_platform_admin = getattr(request.user, "is_platform_admin", False)
        if self.membership is None and not self.is_platform_admin:
            raise PermissionDenied("You are not a member of this organization.")
        if self.admin_required and not self._is_admin:
            raise PermissionDenied("Administrator access is required.")
        if self.operator_required and not self._can_operate:
            raise PermissionDenied("Queue operator access is required.")
        return super().dispatch(request, *args, **kwargs)

    @property
    def _is_admin(self):
        return bool(self.is_platform_admin or (self.membership and self.membership.is_admin))

    @property
    def _can_operate(self):
        return bool(self.is_platform_admin or (self.membership and self.membership.can_operate))
