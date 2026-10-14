"""Populate an existing organization with a large, realistic demo dataset.

Generates branches, services (each with a live queue), customers and mixed-status
queue activity through the real queue engine, so the data behaves exactly like
production data.

Example:
    python manage.py seed_org im-bank --branches 100 --services 100 \
        --customers 100 --tickets 100
"""

import itertools
import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Organization
from directory.models import Branch, QueueRule, Service
from queues import services as qs
from queues.models import Customer, EntryStatus, Queue, QueueEntry

CITIES = [
    "Nairobi CBD", "Westlands", "Karen", "Kilimani", "Upper Hill", "Industrial Area",
    "Mombasa", "Nyali", "Likoni", "Kisumu", "Nakuru", "Eldoret", "Thika", "Machakos",
    "Kitale", "Nyeri", "Meru", "Kericho", "Naivasha", "Malindi", "Kilifi", "Lamu",
    "Garissa", "Kakamega", "Bungoma", "Embu", "Voi", "Lodwar", "Marsabit", "Nanyuki",
    "Kerugoya", "Narok", "Bomet", "Kitui", "Wote", "Ruiru", "Kikuyu", "Athi River",
    "Ngong", "Limuru", "Kiambu", "Juja", "Karatina", "Murang'a", "Homa Bay", "Migori",
    "Kisii", "Busia", "Siaya", "Bondo", "Vihiga", "Webuye", "Malaba", "Mumias",
    "Nyahururu", "Gilgil", "Molo", "Ol Kalou", "Kajiado", "Namanga", "Taveta",
    "Wundanyi", "Chuka", "Kapsabet", "Iten", "Kabarnet", "Maralal", "Wajir",
    "Mandera", "Isiolo", "Moyale", "Hola", "Mpeketoni", "Vipingo", "Diani", "Ukunda",
]

SUFFIXES = ["", "North", "South", "East", "West", "Central", "Plaza", "Hub"]

SERVICE_TYPES = [
    "Teller Services", "Customer Service", "Account Opening", "Loans & Credit",
    "Forex Bureau", "Card Services", "KYC Verification", "Fixed Deposits",
    "Business Banking", "Diaspora Desk", "Wealth Management", "Treasury Services",
    "Trade Finance", "Mortgage Desk", "Insurance Services", "Salary Processing",
    "Mobile Banking Support", "ATM Support", "Safe Deposit", "Premier Banking",
]

FIRST_NAMES = [
    "Amina", "Brian", "Cynthia", "David", "Esther", "Felix", "Grace", "Hassan",
    "Irene", "James", "Kevin", "Lydia", "Moses", "Nancy", "Oscar", "Purity",
    "Quinter", "Ruth", "Samuel", "Tabitha", "Uhuru", "Violet", "Wilson", "Yvonne",
    "Zainab", "Alice", "Benard", "Catherine", "Dennis", "Elizabeth", "Francis",
    "Gladys", "Henry", "Isabella", "John", "Khadija", "Michael", "Njeri", "Otieno",
    "Priscilla",
]

LAST_NAMES = [
    "Otieno", "Kamau", "Wanjiru", "Mwangi", "Achieng", "Kiprop", "Njoroge", "Wafula",
    "Cheruiyot", "Mutiso", "Adhiambo", "Kilonzo", "Barasa", "Chebet", "Maina",
    "Omondi", "Wekesa", "Karanja", "Nyambura", "Kiptoo", "Muthoni", "Onyango",
    "Kibet", "Njeri", "Wambui", "Okoth", "Kimani", "Atieno", "Rotich", "Mburu",
    "Owino", "Nekesa", "Kiplagat", "Mwikali", "Oduya", "Waweru", "Nafula",
    "Korir", "Mueni", "Ouma",
]


class Command(BaseCommand):
    help = "Generate demo branches, services, customers and queue activity for an organization."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Organization slug, e.g. im-bank")
        parser.add_argument("--branches", type=int, default=100)
        parser.add_argument("--services", type=int, default=100)
        parser.add_argument("--customers", type=int, default=100)
        parser.add_argument("--tickets", type=int, default=100, help="Tickets per queue.")
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete existing branches and customers first (cascades queues/entries).",
        )
        parser.add_argument("--seed", type=int, default=2026)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            org = Organization.objects.get(slug=options["slug"])
        except Organization.DoesNotExist:
            raise CommandError(f"No organization with slug '{options['slug']}'.")

        rng = random.Random(options["seed"])

        if options["reset"]:
            org.customers.all().delete()
            org.branches.all().delete()

        branches = self._make_branches(org, options["branches"], rng)
        if not branches:
            raise CommandError("The organization has no branches; create one or pass --branches.")

        self._make_services(branches, options["services"], rng)
        customers = self._make_customers(org, options["customers"], rng)

        queues = list(
            Queue.objects.filter(service__branch__organization=org).order_by("created_at")
        )
        entries = []
        for index, queue in enumerate(queues, start=1):
            entries.extend(self._fill_queue(queue, customers, rng, options["tickets"]))
            if index % 10 == 0:
                self.stdout.write(f"  filled {index}/{len(queues)} queues...")

        self._spread_timestamps(entries, rng)

        self.stdout.write(
            self.style.SUCCESS(
                f"{org.name} ({org.slug}): "
                f"branches={org.branches.count()} "
                f"services={Service.objects.filter(branch__organization=org).count()} "
                f"customers={org.customers.count()} "
                f"queues={len(queues)} tickets={len(entries)}"
            )
        )

    # ------------------------------------------------------------------ builders
    def _make_branches(self, org, count, rng):
        branches = list(org.branches.order_by("created_at"))
        start = len(branches)
        for i in range(count):
            city = CITIES[i % len(CITIES)]
            suffix = SUFFIXES[(i // len(CITIES)) % len(SUFFIXES)]
            name = " ".join(part for part in [city, suffix, "Branch"] if part)
            code = f"BR{start + i + 1:03d}"
            branch, _ = Branch.objects.get_or_create(
                organization=org,
                code=code,
                defaults={
                    "name": name,
                    "address": f"{rng.randint(1, 250)} {city} Road",
                    "phone": f"+2547{rng.randint(10000000, 99999999)}",
                },
            )
            branches.append(branch)
        return branches

    def _make_services(self, branches, count, rng):
        for i in range(count):
            branch = branches[i % len(branches)]
            service, _ = Service.objects.get_or_create(
                branch=branch,
                code=f"SVC{i + 1:03d}",
                defaults={
                    "name": SERVICE_TYPES[i % len(SERVICE_TYPES)],
                    "description": "Quick service desk.",
                    "avg_service_minutes": rng.randint(5, 25),
                    "allow_remote_join": True,
                },
            )
            QueueRule.objects.get_or_create(service=service)
            qs.ensure_queue(service)

    def _make_customers(self, org, count, rng):
        customers = []
        for i in range(count):
            first = FIRST_NAMES[i % len(FIRST_NAMES)]
            last = LAST_NAMES[(i // len(FIRST_NAMES)) % len(LAST_NAMES)]
            phone = f"+2547{i + 1:08d}"
            customer, _ = Customer.objects.get_or_create(
                organization=org,
                phone=phone,
                defaults={
                    "full_name": f"{first} {last}",
                    "email": f"customer{i + 1}@example.com",
                },
            )
            customers.append(customer)
        return customers

    def _fill_queue(self, queue, customers, rng, tickets):
        served = max(1, round(tickets * 0.20))
        in_service = max(1, round(tickets * 0.10))
        called = max(1, round(tickets * 0.10))
        missed = max(1, round(tickets * 0.03))
        cancelled = max(1, round(tickets * 0.02))
        waiting = max(0, tickets - served - in_service - called - missed - cancelled)

        counter = itertools.count()
        keys = lambda: f"seed-{queue.id}-{next(counter)}"  # noqa: E731
        entries = []

        def join():
            customer = rng.choice(customers)
            return qs.join_queue(
                queue,
                full_name=customer.full_name,
                customer=customer,
                idempotency_key=keys(),
            )

        # History first so call_next always claims the entry we just added.
        for _ in range(served):
            _, made = join()
            if made:
                entry = qs.call_next(queue)
                if entry:
                    qs.start_service(entry)
                    qs.complete_service(entry)
                    entries.append(entry)

        for _ in range(missed):
            _, made = join()
            if made:
                entry = qs.call_next(queue)
                if entry:
                    qs.mark_missed(entry)
                    entries.append(entry)

        for _ in range(cancelled):
            entry, made = join()
            if made:
                qs.cancel_entry(entry)
                entries.append(entry)

        for _ in range(in_service):
            _, made = join()
            if made:
                entry = qs.call_next(queue)
                if entry:
                    qs.start_service(entry)
                    entries.append(entry)

        for _ in range(called):
            _, made = join()
            if made:
                entry = qs.call_next(queue)
                if entry:
                    entries.append(entry)

        for _ in range(waiting):
            entry, made = join()
            if made:
                entries.append(entry)

        return entries

    def _spread_timestamps(self, entries, rng):
        now = timezone.now()
        called_states = {
            EntryStatus.CALLED,
            EntryStatus.IN_SERVICE,
            EntryStatus.SERVED,
            EntryStatus.MISSED_TURN,
        }
        for entry in entries:
            entry.joined_at = now - timedelta(seconds=rng.randint(0, 7 * 24 * 3600))
            if entry.status in called_states:
                entry.called_at = entry.joined_at + timedelta(minutes=rng.randint(1, 45))
            if entry.status in {EntryStatus.IN_SERVICE, EntryStatus.SERVED}:
                entry.service_started_at = (entry.called_at or entry.joined_at) + timedelta(
                    minutes=rng.randint(0, 4)
                )
            if entry.status == EntryStatus.SERVED:
                entry.completed_at = (entry.service_started_at or entry.joined_at) + timedelta(
                    minutes=rng.randint(3, 30)
                )
            if entry.status == EntryStatus.CANCELLED:
                entry.cancelled_at = entry.joined_at + timedelta(minutes=rng.randint(1, 30))
        QueueEntry.objects.bulk_update(
            entries,
            ["joined_at", "called_at", "service_started_at", "completed_at", "cancelled_at"],
            batch_size=500,
        )
