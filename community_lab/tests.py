import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest import SkipTest

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

if not settings.configured or settings.SETTINGS_MODULE != "community_lab.settings":
    raise SkipTest("Community database tests require community_lab.settings; run bash scripts/community-lab.sh test.")

from community_lab.models import Content, DemoState, Event, Membership, Participant, Subject
from community_lab.snapshot import build_snapshot

BASE = "/api/v1/community-lab/"


class CommunityApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        DemoState.objects.create(simulated_at=cls.now)
        Participant.objects.bulk_create([Participant(id="demo-you", name="You (demo)")] + [
            Participant(id=f"p{i:04}", name=f"Synthetic neighbor {i}") for i in range(20)])
        for subject_id in ("space", "tech"):
            Subject.objects.create(id=subject_id, name=subject_id.title(), description="A synthetic topic",
                                   color="#7766CC", emoji="🪐")
            Content.objects.bulk_create([Content(id=f"{subject_id}-{i}", subject_id=subject_id,
                title=f"Original setup {i}", punchline="An original punchline.", creator="Demo studio") for i in range(3)])

    def post(self, action, data, client=None):
        return (client or self.client).post(BASE + action + "/", data=json.dumps(data), content_type="application/json")

    def engage(self, person, subject="space", days=0):
        Event.objects.bulk_create([Event(actor_id=person, subject_id=subject, content_id=f"{subject}-{i}",
            kind="save", occurred_at=self.now - timedelta(days=days)) for i in range(2)])

    def snapshot(self):
        return self.client.get(BASE + "snapshot/").json()

    def subject(self, data, subject_id="space"):
        return next((s for s in data.get("subjects", []) if s["id"] == subject_id), {})

    def test_five_independently_engaged_people_activate_subject(self):
        for i in range(4):
            self.engage(f"p{i:04}")
        self.assertEqual(self.subject(self.snapshot()).get("status"), "forming")
        self.engage("p0004")
        self.assertEqual(self.subject(self.snapshot()).get("status"), "active")

    def test_manual_join_alone_does_not_activate_subject(self):
        Membership.objects.bulk_create([Membership(actor_id=f"p{i:04}", subject_id="space", state="joined", updated_at=self.now) for i in range(6)])
        topic = self.subject(self.snapshot())
        self.assertEqual(topic.get("members"), 6)
        self.assertEqual(topic.get("active_members"), 0)
        self.assertEqual(topic.get("status"), "forming")

    def test_share_is_persisted_and_idempotent_with_attributed_reactions(self):
        data = {"content_id": "space-0", "event_id": "share-unique-request"}
        first = self.post("share", data)
        self.assertEqual(first.status_code, 200)
        count = Event.objects.count()
        self.assertGreater(count, 1)
        sender = Event.objects.filter(request_key="share-unique-request").first()
        self.assertIsNotNone(sender)
        self.assertEqual(sender.actor_id, "demo-you")
        self.assertGreater(Event.objects.filter(parent=sender, kind="like").count(), 0)
        second = self.post("share", data)
        self.assertEqual(Event.objects.count(), count)
        self.assertEqual(first.json().get("meta"), second.json().get("meta"))

    def test_reused_id_for_different_content_returns_conflict(self):
        self.post("share", {"content_id": "space-0", "event_id": "same-request"})
        count = Event.objects.count()
        response = self.post("share", {"content_id": "space-1", "event_id": "same-request"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Event.objects.count(), count)

    def test_share_cascade_can_form_a_community(self):
        for i in range(3):
            self.engage(f"p{i:04}")
        response = self.post("share", {"content_id": "space-0", "event_id": "formation-demo"})
        self.assertEqual(self.subject(response.json()).get("status"), "active")
        self.assertEqual(self.subject(self.snapshot()).get("status"), "active")

    def test_leaving_removes_inferred_membership_until_rejoin(self):
        self.engage("demo-you")
        left = self.post("membership", {"subject_id": "space", "action": "leave"}).json()
        self.assertFalse(self.subject(left).get("joined", True))
        self.post("simulate", {"subject_id": "space", "steps": 2})
        self.assertFalse(self.subject(self.snapshot()).get("joined", True))
        joined = self.post("membership", {"subject_id": "space", "action": "join"}).json()
        self.assertTrue(self.subject(joined).get("joined", False))

    def test_time_advance_decays_engagement_and_persists_clock(self):
        for i in range(5):
            self.engage(f"p{i:04}")
        response = self.post("advance", {"days": 7})
        topic = self.subject(response.json())
        self.assertEqual(topic.get("active_members"), 0)
        self.assertEqual(topic.get("status"), "cooling")
        self.assertEqual(topic.get("growth"), -5)
        self.assertEqual(DemoState.objects.get().simulated_at, self.now + timedelta(days=7))

    def test_growth_compares_current_population_to_historical_cutoff(self):
        for i in range(3):
            self.engage(f"p{i:04}", days=8)
        for i in range(3, 8):
            self.engage(f"p{i:04}")
        self.assertEqual(self.subject(self.snapshot()).get("growth"), 2)

    def test_snapshot_has_bounded_anonymous_graph_and_full_aggregate_counts(self):
        Participant.objects.bulk_create([Participant(id=f"extra{i}", name="Synthetic person") for i in range(270)])
        for i in range(270):
            self.engage(f"extra{i}")
        self.engage("demo-you", "space")
        self.engage("demo-you", "tech")
        # Loading hundreds of people must not issue per-person or per-topic queries.
        with self.assertNumQueries(6):
            build_snapshot()
        data = self.snapshot()
        self.assertGreater(data.get("meta", {}).get("total_members", 0), 240)
        members = [n for n in data.get("graph", {}).get("nodes", []) if n["kind"] == "member"]
        self.assertLessEqual(len(members), 240)
        self.assertGreater(len(members), 0)
        self.assertEqual(data["stats"]["bridges"], 1)
        self.assertTrue(all(n["label"].startswith("Synthetic") or n["id"] == "demo-you" for n in members))

    def test_api_requires_csrf_and_snapshot_sets_cookie(self):
        browser = Client(enforce_csrf_checks=True)
        response = browser.get(BASE + "snapshot/")
        self.assertIn("community_lab_csrf", response.cookies)
        self.assertEqual(self.post("advance", {"days": 1}, browser).status_code, 403)
        token = response.cookies["community_lab_csrf"].value
        response = browser.post(BASE + "advance/", data='{"days":1}', content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)

    @override_settings(COMMUNITY_LAB_ENABLED=False)
    def test_mutations_are_disabled_without_explicit_demo_settings(self):
        response = self.post("simulate", {"steps": 1})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Event.objects.count(), 0)

    def test_mutation_validation_rejects_bad_input_without_writes(self):
        cases = [
            ("simulate", {"steps": 0}), ("simulate", {"steps": 101}), ("simulate", {"steps": True}),
            ("simulate", {"steps": 1.2}), ("simulate", {"steps": "4"}),
            ("simulate", {"steps": 1, "actor_id": "p0001"}),
            ("simulate", {"steps": 1, "subject_id": []}), ("simulate", {"subject_id": "missing", "steps": 1}),
            ("advance", {"days": 31}), ("advance", {"days": False}), ("advance", {}),
            ("membership", {"subject_id": "space", "action": "admin"}),
            ("share", {"content_id": "space-0", "event_id": ""}),
            ("share", {"content_id": "space-0", "event_id": "x" * 200}),
            ("share", {"content_id": "missing", "event_id": "missing-content"}),
        ]
        for action, data in cases:
            with self.subTest(action=action, data=data):
                self.assertEqual(self.post(action, data).status_code, 400)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(DemoState.objects.get().revision, 1)

    def test_malformed_json_and_non_object_payloads_are_rejected(self):
        for body in ("{", "[]", "null", '"hello"'):
            response = self.client.post(BASE + "simulate/", data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_get_cannot_mutate(self):
        for action in ("simulate", "share", "membership", "advance"):
            self.assertEqual(self.client.get(BASE + action + "/").status_code, 405)

    def test_membership_history_has_strict_order_and_leave_is_preserved_at_cutoff(self):
        self.engage("demo-you")
        self.post("membership", {"subject_id": "space", "action": "join"})
        joined_at = Event.objects.get(kind="join").occurred_at
        self.post("membership", {"subject_id": "space", "action": "leave"})
        left_at = Event.objects.get(kind="leave").occurred_at
        self.assertLess(joined_at, left_at)
        response = self.post("advance", {"days": 7})
        self.assertEqual(self.subject(response.json())["growth"], 0)

    def test_hostile_identifier_strings_are_rejected_before_database_lookup(self):
        for value in ("\x00", "\ud800", "space\n", "x" * 1000):
            for action, data in (
                ("simulate", {"subject_id": value, "steps": 1}),
                ("membership", {"subject_id": value, "action": "join"}),
                ("share", {"content_id": value, "event_id": "safe-request"}),
            ):
                with self.subTest(action=action, value=repr(value)):
                    self.assertEqual(self.post(action, data).status_code, 400)

    def test_repeated_likes_do_not_inflate_unique_audience_or_trending(self):
        Event.objects.bulk_create([Event(actor_id="p0001", subject_id="space", content_id="space-0",
            kind="like", occurred_at=self.now) for _ in range(30)])
        Event.objects.create(actor_id="p0001", subject_id="space", content_id="space-0", kind="save", occurred_at=self.now)
        row = next(item for item in self.snapshot().get("content", []) if item["id"] == "space-0")
        self.assertEqual(row["likes"], 1)
        self.assertEqual(row["trending_score"], 4)

    @override_settings(SETTINGS_MODULE="production.settings", COMMUNITY_LAB_ENABLED=True)
    def test_importing_lab_urls_under_production_settings_does_not_enable_demo(self):
        self.assertEqual(self.post("simulate", {"steps": 1}).status_code, 403)
        self.assertEqual(self.client.get(BASE + "snapshot/").status_code, 403)

    def test_invalid_utf8_and_oversized_body_are_controlled_errors(self):
        response = self.client.post(BASE + "simulate/", data=b'\xff', content_type="application/json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(BASE + "simulate/", data='{"extra":"' + 'x' * 5000 + '"}', content_type="application/json")
        self.assertEqual(response.status_code, 413)


class SeedLifecycleTests(TestCase):
    def test_seed_has_forming_topic_and_noop_preserves_state_until_explicit_reset(self):
        output = StringIO()
        call_command("seed_community_lab", stdout=output)
        data = build_snapshot()
        self.assertEqual(data["stats"]["participants"], 1600)
        self.assertEqual(len(data["content"]), 216)
        self.assertEqual(data["stats"]["active_communities"], 8)
        space = next(subject for subject in data["subjects"] if subject["id"] == "space")
        self.assertEqual(space["active_members"], 3)
        self.assertEqual(space["status"], "forming")
        count = Event.objects.count()
        DemoState.objects.filter(pk=1).update(revision=42)
        call_command("seed_community_lab", stdout=output)
        self.assertEqual(DemoState.objects.get().revision, 42)
        self.assertEqual(Event.objects.count(), count)
        call_command("seed_community_lab", reset=True, stdout=output)
        self.assertEqual(DemoState.objects.get().revision, 1)
        self.assertEqual(Event.objects.count(), count)


class ConcurrentShareTests(TransactionTestCase):
    def setUp(self):
        DemoState.objects.create()
        Subject.objects.create(id="space", name="Space", description="A synthetic topic", color="#7766CC", emoji="🪐")
        Participant.objects.bulk_create([Participant(id=person, name="Synthetic person") for person in ("demo-you", "p1", "p2", "p3")])
        Content.objects.bulk_create([Content(id=f"space-{i}", subject_id="space", title="An original setup",
            punchline="An original punchline", creator="Demo studio") for i in range(2)])

    def test_concurrent_retries_produce_exactly_one_share_and_one_cascade(self):
        barrier = Barrier(2)

        def post_share():
            try:
                barrier.wait(timeout=5)
                response = Client().post(BASE + "share/", data=json.dumps({
                    "content_id": "space-0", "event_id": "concurrent-request"}), content_type="application/json")
                return response.status_code, response.json().get("meta", {}).get("revision")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: post_share(), range(2)))
        self.assertEqual(results, [(200, 2), (200, 2)])
        self.assertEqual(Event.objects.filter(kind="share").count(), 1)
        self.assertEqual(Event.objects.filter(parent__isnull=False).count(), 9)
        self.assertEqual(DemoState.objects.get().revision, 2)
