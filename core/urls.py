from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("explore/", views.explore, name="explore"),
    path("app/", views.dashboard, name="dashboard"),
    path("platform/", views.PlatformConsole.as_view(), name="platform"),
    path("healthz", views.healthz, name="healthz"),
]
