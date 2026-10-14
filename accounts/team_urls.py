from django.urls import path

from . import views

app_name = "team"

urlpatterns = [
    path("team/", views.TeamView.as_view(), name="team"),
    path(
        "team/<uuid:membership_id>/",
        views.update_membership,
        name="update_membership",
    ),
]
