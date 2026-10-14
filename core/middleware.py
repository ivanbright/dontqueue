"""Request helpers shared across the platform."""

from django.urls import Resolver404, resolve


class CurrentOrganizationMiddleware:
    """Attach the organization addressed by an ``org_slug`` URL kwarg.

    Authorization is still enforced per-view; this only makes the active
    tenant available to templates and context processors.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = None
        request.organization_slug = None
        path = request.path_info
        if path.startswith("/app/") or path.startswith("/o/"):
            try:
                match = resolve(request.path_info)
                slug = match.kwargs.get("org_slug")
            except Resolver404:
                slug = None
            if slug:
                from accounts.models import Organization

                request.organization_slug = slug
                request.organization = (
                    Organization.objects.filter(slug=slug, is_active=True)
                    .select_related("owner")
                    .first()
                )
        return self.get_response(request)
