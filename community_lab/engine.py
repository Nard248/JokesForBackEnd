"""Pure, explainable scoring. No graph layout or database dependencies."""
from collections import defaultdict

HALF_LIFE_DAYS = 7
MEMBERSHIP_THRESHOLD = 6
MINIMUM_CONTENT = 2
MINIMUM_MEMBERS = 5
CONTENT_CAP = 4
WEIGHTS = {"view": 0, "like": 3, "save": 4, "share": 2}


def decay(occurred_at, now):
    return 2 ** (-max(0, (now - occurred_at).total_seconds()) / (86400 * HALF_LIFE_DAYS))


def affinities(events, now, overrides=()):
    """One strongest decayed signal per joke prevents repeated-action inflation.

    Explicit membership is separate from independently inferred engagement.
    Historical callers supply only overrides that existed at their cutoff.
    """
    contributions = defaultdict(dict)
    for event in events:
        if event["occurred_at"] > now or event["kind"] not in WEIGHTS:
            continue
        key = (event["actor_id"], event["subject_id"])
        score = min(CONTENT_CAP, WEIGHTS[event["kind"]]) * decay(event["occurred_at"], now)
        content = event["content_id"]
        contributions[key][content] = max(score, contributions[key].get(content, 0))
    states = {(item["actor_id"], item["subject_id"]): item["state"] for item in overrides}
    results = {}
    for key in contributions.keys() | states.keys():
        values = contributions.get(key, {}).values()
        score = sum(values)
        distinct = sum(value > 0 for value in values)
        engaged = distinct >= MINIMUM_CONTENT and score >= MEMBERSHIP_THRESHOLD
        left = states.get(key) == "left"
        results[key] = {
            "score": score, "content_count": distinct, "inferred": engaged and not left,
            "member": not left and (engaged or states.get(key) == "joined"),
            "explicit": states.get(key),
        }
    return results
