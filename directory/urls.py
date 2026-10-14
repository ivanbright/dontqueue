from django.urls import path

from . import views

app_name = "directory"

urlpatterns = [
    path("branches/", views.BranchListView.as_view(), name="branches"),
    path("branches/new/", views.BranchCreateView.as_view(), name="branch_create"),
    path("branches/<uuid:pk>/edit/", views.BranchUpdateView.as_view(), name="branch_edit"),
    path("services/", views.ServiceListView.as_view(), name="services"),
    path("services/new/", views.ServiceCreateView.as_view(), name="service_create"),
    path(
        "branches/<uuid:branch_id>/services/new/",
        views.ServiceCreateView.as_view(),
        name="service_create_for_branch",
    ),
    path("services/<uuid:pk>/edit/", views.ServiceUpdateView.as_view(), name="service_edit"),
    path(
        "services/<uuid:service_id>/rules/",
        views.RuleUpdateView.as_view(),
        name="service_rules",
    ),
    path("staff/", views.StaffView.as_view(), name="staff"),
]
