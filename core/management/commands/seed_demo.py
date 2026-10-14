"""Populate a demo organization so the app can be explored immediately."""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Membership, Organization, Role, User
from directory.models import Branch, QueueRule, Service
from queues import services as qs
from queues.models import Customer

DEMO_EMAIL = "demo@dontqueue.local"
DEMO_PASSWORD = "demo12345!"
ORG_SLUG = "demo-clinic"


class Command(BaseCommand):
    help = "Create a demo organization with branches, services and sample queue activity."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the existing demo organization and user before seeding.",
        )

    def _customer(self, org, name, phone):
        customer, _ = Customer.objects.get_or_create(
            organization=org, phone=phone, defaults={"full_name": name}
        )
        return customer

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            Organization.objects.filter(slug=ORG_SLUG).delete()
            User.objects.filter(email=DEMO_EMAIL).delete()

        owner, _ = User.objects.get_or_create(
            email=DEMO_EMAIL,
            defaults={"full_name": "Demo Owner"},
        )
        owner.is_platform_admin = True
        owner.is_staff = True
        owner.set_password(DEMO_PASSWORD)
        owner.save()

        org, _ = Organization.objects.get_or_create(
            slug=ORG_SLUG,
            defaults={
                "name": "Demo Clinic",
                "owner": owner,
                "description": "A demonstration organization for exploring Don't Queue.",
                "timezone": "UTC",
            },
        )
        Membership.objects.get_or_create(
            user=owner, organization=org, defaults={"role": Role.OWNER}
        )

        branch, _ = Branch.objects.get_or_create(
            organization=org,
            code="MAIN",
            defaults={"name": "Main Branch", "address": "1 Demo Street", "phone": "555-0100"},
        )

        specs = [
            ("General Consultation", "GEN", 12),
            ("Pharmacy", "PHAR", 6),
            ("Laboratory", "LAB", 15),
        ]

        created = 0
        for index, (name, code, minutes) in enumerate(specs):
            service, _ = Service.objects.get_or_create(
                branch=branch,
                code=code,
                defaults={"name": name, "avg_service_minutes": minutes, "allow_remote_join": True},
            )
            QueueRule.objects.get_or_create(service=service)
            queue = qs.ensure_queue(service)

            served_customer = self._customer(org, f"{name} guest", phone=f"555-1{index:03d}")
            served, made = qs.join_queue(
                queue,
                full_name=served_customer.full_name,
                customer=served_customer,
                actor=owner,
                idempotency_key=f"seed-served-{code}",
            )
            if made:
                called = qs.call_next(queue, actor=owner)
                if called is not None:
                    qs.start_service(called, actor=owner)
                    qs.complete_service(called, actor=owner)
                created += 1

            for index in range(2):
                wait_customer = self._customer(
                    org, f"Visitor {index + 1} ({name})", phone=f"555-2{code}-{index}"
                )
                _, made = qs.join_queue(
                    queue,
                    full_name=wait_customer.full_name,
                    customer=wait_customer,
                    actor=owner,
                    idempotency_key=f"seed-wait-{code}-{index}",
                )
                if made:
                    created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready. Public join: /o/{org.slug}/join/  |  "
                f"login: {DEMO_EMAIL} / {DEMO_PASSWORD}"
            )
        )
        self.stdout.write(
            f"organization={org.slug} services={len(specs)} entries_created={created}"
        )
