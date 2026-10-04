from datetime import UTC, datetime, timedelta
from unittest import TestCase

from communities.engine import affinities

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def event(content="j1", kind="like", days=0, person="p1", subject="space"):
    return {"actor_id": person, "content_id": content, "subject_id": subject,
            "kind": kind, "occurred_at": NOW - timedelta(days=days)}


class AffinityTests(TestCase):
    def test_two_recent_distinct_likes_infer_membership(self):
        result = affinities([event(), event("j2")], NOW)
        self.assertTrue(result.get(("p1", "space"), {}).get("inferred", False))

    def test_repeated_content_cannot_establish_membership(self):
        result = affinities([event(kind="save")] * 100, NOW)
        self.assertLessEqual(result.get(("p1", "space"), {}).get("score", 999), 4)
        self.assertFalse(result[("p1", "space")]["inferred"])

    def test_views_alone_do_not_establish_membership(self):
        result = affinities([event(f"j{i}", kind="view") for i in range(100)], NOW)
        self.assertFalse(result.get(("p1", "space"), {}).get("inferred", False))

    def test_seven_days_halves_affinity(self):
        result = affinities([event(kind="save", days=7), event("j2", kind="save", days=7)], NOW)
        self.assertAlmostEqual(result.get(("p1", "space"), {}).get("score", -1), 4)
        self.assertFalse(result[("p1", "space")]["inferred"])

    def test_leave_overrides_inference_until_explicit_rejoin(self):
        events = [event(kind="save"), event("j2", kind="save")]
        result = affinities(events, NOW, [{"actor_id": "p1", "subject_id": "space", "state": "left"}])
        self.assertFalse(result.get(("p1", "space"), {}).get("member", True))
        result = affinities(events, NOW, [{"actor_id": "p1", "subject_id": "space", "state": "joined"}])
        self.assertTrue(result.get(("p1", "space"), {}).get("member", False))

    def test_join_alone_is_not_independent_engagement(self):
        result = affinities([], NOW, [{"actor_id": "p1", "subject_id": "space", "state": "joined"}])
        self.assertTrue(result.get(("p1", "space"), {}).get("member", False))
        self.assertFalse(result[("p1", "space")]["inferred"])

    def test_people_may_have_overlapping_interests(self):
        events = [event(kind="save"), event("j2", kind="save"),
                  event("j3", kind="save", subject="pets"), event("j4", kind="save", subject="pets")]
        result = affinities(events, NOW)
        self.assertEqual(sum(value["member"] for value in result.values()), 2)

    def test_future_events_do_not_affect_historical_population(self):
        result = affinities([event(kind="save"), event("j2", kind="save")], NOW - timedelta(days=1))
        self.assertFalse(any(value["member"] for value in result.values()))
