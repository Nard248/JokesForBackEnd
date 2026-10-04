"""Pure, explainable community scoring. No database or presentation dependencies.

Ported unchanged in behaviour from the Community Lab prototype; the only change
is the signal vocabulary, which now names the real engagement tables:
``like`` = a positive JokeReaction (lol/crying), ``favorite`` = Favorite,
``save`` = SavedJoke, ``share`` = a signed-in ShareEvent. Views carry no weight:
watching alone never establishes membership.
"""
from collections import defaultdict

HALF_LIFE_DAYS = 7
MEMBERSHIP_THRESHOLD = 6
MINIMUM_CONTENT = 2
MINIMUM_MEMBERS = 5
CONTENT_CAP = 4
WEIGHTS = {"view": 0, "like": 3, "favorite": 4, "save": 4, "share": 2}


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
    totals = {}
    for key, values in contributions.items():
        totals[key] = (sum(values.values()), sum(value > 0 for value in values.values()))
    return affinities_from_totals(totals, overrides)


def affinities_from_totals(totals, overrides=()):
    """The same membership rules applied to precomputed per-(actor, subject) totals.

    ``totals`` maps ``(actor_id, subject_id)`` to ``(score, content_count)``: the
    sum of the per-content strongest decayed signals and how many contents had
    one — exactly what ``affinities`` derives from raw events. The database
    computes these for the community aggregate.
    """
    states = {(item["actor_id"], item["subject_id"]): item["state"] for item in overrides}
    results = {}
    for key in totals.keys() | states.keys():
        score, distinct = totals.get(key, (0, 0))
        engaged = distinct >= MINIMUM_CONTENT and score >= MEMBERSHIP_THRESHOLD
        left = states.get(key) == "left"
        results[key] = {
            "score": score, "content_count": distinct, "inferred": engaged and not left,
            "member": not left and (engaged or states.get(key) == "joined"),
            "explicit": states.get(key),
        }
    return results
