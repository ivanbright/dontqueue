from django.urls import path

from . import views

app_name = "public"

urlpatterns = [
    path("join/", views.PublicJoinView.as_view(), name="join"),
    path("t/<uuid:reference>/", views.StatusView.as_view(), name="status"),
    path("t/<uuid:reference>/status.json", views.status_json, name="status_json"),
]
