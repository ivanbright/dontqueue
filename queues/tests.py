"""Tests for the queue engine service layer and entry lifecycle."""

from django.test import TestCase

from accounts.models import Organization, User
from directory.models import Branch, Service
from queues import services
from queues.models import EntryStatus, QueueEntry, QueueStatus


class QueueEngineTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="pw12345678")
        self.org = Organization.objects.create(name="Clinic", owner=self.owner)
        self.branch = Branch.objects.create(organization=self.org, name="Main", code="M")
        self.service = Service.objects.create(branch=self.branch, name="General", code="G")
        self.queue = services.ensure_queue(self.service)

    def test_join_allocates_numbers_and_positions(self):
        first, created = services.join_queue(self.queue, full_name="A", idempotency_key="k1")
        second, _ = services.join_queue(self.queue, full_name="B", idempotency_key="k2")
        self.assertTrue(created)
        self.assertEqual(first.number, 1)
        self.assertEqual(second.number, 2)
        self.assertEqual(services.position_of(first), 1)
        self.assertEqual(services.position_of(second), 2)

    def test_join_is_idempotent(self):
        first, _ = services.join_queue(self.queue, full_name="A", idempotency_key="dup")
        second, created = services.join_queue(self.queue, full_name="A", idempotency_key="dup")
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(QueueEntry.objects.filter(queue=self.queue).count(), 1)

    def test_full_lifecycle(self):
        entry, _ = services.join_queue(self.queue, full_name="A", idempotency_key="k")
        called = services.call_next(self.queue)
        self.assertEqual(called.pk, entry.pk)
        called.refresh_from_db()
        self.assertEqual(called.status, EntryStatus.CALLED)

        services.start_service(called)
        called.refresh_from_db()
        self.assertEqual(called.status, EntryStatus.IN_SERVICE)

        services.complete_service(called)
        called.refresh_from_db()
        self.assertEqual(called.status, EntryStatus.SERVED)

    def test_invalid_transition_is_rejected(self):
        entry, _ = services.join_queue(self.queue, full_name="A", idempotency_key="k")
        with self.assertRaises(services.InvalidTransition):
            services.start_service(entry)  # waiting -> in_service is not allowed

    def test_call_next_requires_open_queue(self):
        services.join_queue(self.queue, full_name="A", idempotency_key="k")
        services.close_queue(self.queue)
        with self.assertRaises(services.QueueNotOpen):
            services.call_next(self.queue)

    def test_pause_and_resume(self):
        services.pause_queue(self.queue)
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, QueueStatus.PAUSED)
        services.open_queue(self.queue)
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, QueueStatus.OPEN)

    def test_estimate_falls_back_to_configured_average(self):
        entry, _ = services.join_queue(self.queue, full_name="A", idempotency_key="k")
        estimate = services.estimate_wait(entry)
        self.assertTrue(estimate["approximate"])
        self.assertEqual(estimate["source"], "configured")
        self.assertEqual(estimate["position"], 1)
