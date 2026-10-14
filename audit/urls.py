from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("audit/", views.AuditLogListView.as_view(), name="log"),
]
