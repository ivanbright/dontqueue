from django.urls import path

from . import views

app_name = "queues"

urlpatterns = [
    path("console/<uuid:queue_id>/", views.ConsoleView.as_view(), name="console"),
    path("console/<uuid:queue_id>/call-next/", views.CallNextView.as_view(), name="call_next"),
    path(
        "console/<uuid:queue_id>/export/<str:fmt>/",
        views.ConsoleExportView.as_view(),
        name="console_export",
    ),
    path(
        "console/<uuid:queue_id>/<str:action>/",
        views.QueueActionView.as_view(),
        name="queue_action",
    ),
    path("entries/<uuid:pk>/presence/", views.EntryPresenceView.as_view(), name="entry_presence"),
    path("entries/<uuid:pk>/<str:action>/", views.EntryActionView.as_view(), name="entry_action"),
    path("register/<uuid:service_id>/", views.RegisterView.as_view(), name="register"),
]
