"""Tests for signup, onboarding and team invitations."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import Invitation, Membership, Organization, Role, User


class SignupOnboardingTests(TestCase):
    def test_signup_then_create_organization(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "email": "new@example.com",
                "full_name": "New Owner",
                "password1": "SuperSecret!2026",
                "password2": "SuperSecret!2026",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(email="new@example.com").exists())

        response = self.client.post(
            reverse("accounts:onboarding"),
            {"name": "Acme Clinic", "description": "", "timezone": "UTC"},
        )
        self.assertEqual(response.status_code, 302)
        org = Organization.objects.get(name="Acme Clinic")
        self.assertTrue(org.slug)
        self.assertTrue(
            Membership.objects.filter(organization=org, role=Role.OWNER).exists()
        )


class InvitationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw12345678")
        self.org = Organization.objects.create(name="Clinic", owner=self.owner)
        Membership.objects.create(user=self.owner, organization=self.org, role=Role.OWNER)
        self.client.force_login(self.owner)

    def test_inviting_same_email_twice_updates_pending_invite(self):
        url = reverse("team:team", args=[self.org.slug])
        first = self.client.post(url, {"email": "friend@example.com", "role": "receptionist", "branch": ""})
        self.assertEqual(first.status_code, 302)

        second = self.client.post(url, {"email": "friend@example.com", "role": "provider", "branch": ""})
        self.assertEqual(second.status_code, 302)

        pending = Invitation.objects.filter(
            organization=self.org, email="friend@example.com", accepted_at__isnull=True
        )
        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending.first().role, Role.PROVIDER)

    def test_inviting_an_existing_member_is_rejected(self):
        url = reverse("team:team", args=[self.org.slug])
        response = self.client.post(
            url, {"email": "owner@example.com", "role": "provider", "branch": ""}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            Invitation.objects.filter(organization=self.org, email="owner@example.com").exists()
        )
