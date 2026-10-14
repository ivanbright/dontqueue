from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.SignupView.as_view(), name="signup"),
    path("login/", views.AppLoginView.as_view(), name="login"),
    path("logout/", views.AppLogoutView.as_view(), name="logout"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("profile/", views.profile, name="profile"),
    path("invite/<uuid:token>/", views.accept_invite, name="accept_invite"),
    path("password-reset/", views.AppPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        views.AppPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.AppPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        views.AppPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
