"""Organization-scoped file exports (powered by the ``exportkit`` package)."""

from django.urls import path

from . import views

app_name = "exports"

urlpatterns = [
    path(
        "export/<str:kind>/<str:fmt>/",
        views.OrgExportView.as_view(),
        name="org_export",
    ),
]
