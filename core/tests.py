"""Public pages, password reset, tenant isolation and the demo seed command."""

from django.core.management import call_command
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import Membership, Organization, Role, User
from directory.models import Branch, Service
from queues import services as queue_services


class PublicPageTests(TestCase):
    def test_landing_and_explore_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/explore/").status_code, 200)

    def test_healthz(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)


class PasswordResetTests(TestCase):
    def test_reset_and_confirm_inputs_are_styled(self):
        response = self.client.get("/auth/password-reset/")
        self.assertContains(response, 'class="input"')

    def test_full_reset_flow(self):
        User.objects.create_user(email="user@example.com", password="OldPass!2026")

        response = self.client.post("/auth/password-reset/", {"email": "user@example.com"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/auth/password-reset/done/").status_code, 200)

        user = User.objects.get(email="user@example.com")
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        response = self.client.get(f"/auth/reset/{uid}/{token}/")
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            response.url,
            {"new_password1": "NewPass!2026", "new_password2": "NewPass!2026"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.login(username="user@example.com", password="NewPass!2026"))


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(email="a@example.com", password="pw12345678")
        self.owner_b = User.objects.create_user(email="b@example.com", password="pw12345678")
        self.org_a = Organization.objects.create(name="Alpha", owner=self.owner_a)
        self.org_b = Organization.objects.create(name="Beta", owner=self.owner_b)
        Membership.objects.create(user=self.owner_a, organization=self.org_a, role=Role.OWNER)
        Membership.objects.create(user=self.owner_b, organization=self.org_b, role=Role.OWNER)
        Branch.objects.create(organization=self.org_b, name="B", code="B")

    def test_member_of_a_cannot_open_b(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(f"/app/o/{self.org_b.slug}/services/")
        self.assertEqual(response.status_code, 403)

    def test_owner_can_open_own_org(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(f"/app/o/{self.org_a.slug}/services/")
        self.assertEqual(response.status_code, 200)


class SeedDemoTests(TestCase):
    def test_seed_demo_is_idempotent(self):
        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)
        self.assertTrue(Organization.objects.filter(slug="demo-clinic").exists())
        self.assertEqual(Organization.objects.filter(slug="demo-clinic").count(), 1)


class ExportTests(TestCase):
    """File exports rendered by the external, PyPI-published ``exportkit`` package."""

    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw12345678")
        self.org = Organization.objects.create(name="Alpha", owner=self.owner)
        Membership.objects.create(user=self.owner, organization=self.org, role=Role.OWNER)
        self.branch = Branch.objects.create(organization=self.org, name="Main", code="MAIN")
        self.service = Service.objects.create(branch=self.branch, name="Teller", code="TEL")
        self.queue = queue_services.ensure_queue(self.service)
        queue_services.join_queue(self.queue, full_name="Amina", idempotency_key="k1")
        self.client.force_login(self.owner)

    def test_tickets_xlsx_export(self):
        response = self.client.get(f"/app/o/{self.org.slug}/export/tickets/xlsx/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(response.content.startswith(b"PK"))
        self.assertIn("attachment", response["Content-Disposition"])

    def test_tickets_pdf_export(self):
        response = self.client.get(f"/app/o/{self.org.slug}/export/tickets/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_audit_docx_export(self):
        response = self.client.get(f"/app/o/{self.org.slug}/export/audit/docx/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"PK"))

    def test_services_export(self):
        response = self.client.get(f"/app/o/{self.org.slug}/export/services/xlsx/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_shows_export_links(self):
        response = self.client.get(f"/app/o/{self.org.slug}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"/app/o/{self.org.slug}/export/tickets/xlsx/")
        self.assertContains(response, f"/app/o/{self.org.slug}/export/tickets/pdf/")

    def test_console_shows_export_links(self):
        response = self.client.get(f"/app/o/{self.org.slug}/console/{self.queue.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"/console/{self.queue.id}/export/xlsx/")
        self.assertContains(response, f"/console/{self.queue.id}/export/docx/")

    def test_audit_shows_export_links(self):
        response = self.client.get(f"/app/o/{self.org.slug}/audit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"/app/o/{self.org.slug}/export/audit/xlsx/")

    def test_unknown_format_is_404(self):
        response = self.client.get(f"/app/o/{self.org.slug}/export/tickets/csv/")
        self.assertEqual(response.status_code, 404)

    def test_non_member_cannot_export(self):
        outsider = User.objects.create_user(email="out@example.com", password="pw12345678")
        self.client.force_login(outsider)
        response = self.client.get(f"/app/o/{self.org.slug}/export/tickets/pdf/")
        self.assertEqual(response.status_code, 403)
