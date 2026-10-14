"""Root URL configuration for Don't Queue."""

from django.contrib import admin
from django.urls import include, path

from core.views import OrgDashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("auth/", include("accounts.urls")),
    # Public, unauthenticated customer flow (organization addressed by slug).
    path("o/<slug:org_slug>/", include("queues.public_urls")),
    # Authenticated application, scoped to one organization.
    path("app/o/<slug:org_slug>/", OrgDashboard.as_view(), name="org_dashboard"),
    path("app/o/<slug:org_slug>/", include("directory.urls")),
    path("app/o/<slug:org_slug>/", include("queues.urls")),
    path("app/o/<slug:org_slug>/", include("audit.urls")),
    path("app/o/<slug:org_slug>/", include("accounts.team_urls")),
    path("app/o/<slug:org_slug>/", include("core.app_urls")),
]
