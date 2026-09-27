"""Bounded browser projection, derived exclusively from persisted demo events."""
from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations

from community_lab.engine import (
    CONTENT_CAP,
    HALF_LIFE_DAYS,
    MEMBERSHIP_THRESHOLD,
    MINIMUM_CONTENT,
    MINIMUM_MEMBERS,
    WEIGHTS,
    affinities,
    decay,
)
from community_lab.models import Content, DemoState, Event, Membership, Participant, Subject

VIEWER_ID = "demo-you"
GRAPH_MEMBER_LIMIT = 240


def read_events():
    return list(Event.objects.order_by("occurred_at", "id").values(
        "id", "actor_id", "actor__name", "subject_id", "subject__name",
        "content_id", "content__title", "kind", "occurred_at", "parent_id"))


def historical_overrides(events, memberships, cutoff):
    # Membership rows hold current state; the event ledger preserves older overrides.
    states = {(row["actor_id"], row["subject_id"]): row for row in memberships if row["updated_at"] <= cutoff}
    for event in events:
        if event["occurred_at"] <= cutoff and event["kind"] in ("join", "leave"):
            key = (event["actor_id"], event["subject_id"])
            states[key] = {"actor_id": key[0], "subject_id": key[1],
                           "state": "joined" if event["kind"] == "join" else "left"}
    return list(states.values())


def build_snapshot(state=None):
    state = state or DemoState.objects.get(pk=1)
    now = state.simulated_at
    events = [event for event in read_events() if event["occurred_at"] <= now]
    subjects = list(Subject.objects.all())
    content = list(Content.objects.all())
    participants = dict(Participant.objects.values_list("id", "name"))
    memberships = list(Membership.objects.values("actor_id", "subject_id", "state", "updated_at"))
    current = affinities(events, now, memberships)
    previous_time = now - timedelta(days=7)
    previous = affinities(events, previous_time, historical_overrides(events, memberships, previous_time))
    member_sets = defaultdict(set)
    inferred_sets = defaultdict(set)
    previous_sets = defaultdict(set)
    scores = Counter()
    member_topics = defaultdict(list)
    for (person, subject), result in current.items():
        scores[subject] += result["score"]
        if result["member"]:
            member_sets[subject].add(person)
            member_topics[person].append(subject)
        if result["inferred"]:
            inferred_sets[subject].add(person)
    for (person, subject), result in previous.items():
        if result["inferred"]:
            previous_sets[subject].add(person)

    buckets = defaultdict(lambda: [0] * 7)
    like_actors, strongest = defaultdict(set), {}
    shares, trends = Counter(), Counter()
    for event in events:
        days_ago = (now.date() - event["occurred_at"].date()).days
        if 0 <= days_ago <= 6:
            buckets[event["subject_id"]][6 - days_ago] += 1
        item = event["content_id"]
        if event["kind"] == "like":
            like_actors[item].add(event["actor_id"])
        shares[item] += event["kind"] == "share"
        key = (event["actor_id"], item)
        contribution = min(CONTENT_CAP, WEIGHTS.get(event["kind"], 0)) * decay(event["occurred_at"], now)
        strongest[key] = max(strongest.get(key, 0), contribution)
    for (_, item), value in strongest.items():
        trends[item] += value

    subject_rows = []
    for subject in subjects:
        engaged = len(inferred_sets[subject.id])
        past = len(previous_sets[subject.id])
        viewer = current.get((VIEWER_ID, subject.id), {})
        status = "active" if engaged >= MINIMUM_MEMBERS else "cooling" if past >= MINIMUM_MEMBERS else "forming"
        if status == "active":
            explanation = f"{engaged} independently engaged people crossed the threshold across at least two different jokes."
        elif status == "cooling":
            explanation = "Earlier engagement has cooled. Fresh, varied positive reactions can bring this community back."
        else:
            explanation = f"{engaged} of {MINIMUM_MEMBERS} independently engaged people. Shares invite discovery; each friend must react for themselves."
        if viewer.get("explicit") == "left":
            explanation += " You left this community; automatic membership stays off until you join again."
        subject_rows.append({
            "id": subject.id, "name": subject.name, "description": subject.description,
            "color": subject.color, "emoji": subject.emoji, "members": len(member_sets[subject.id]),
            "active_members": engaged, "growth": engaged - past, "score": round(scores[subject.id], 2),
            "status": status, "joined": viewer.get("member", False),
            "affinity": round(viewer.get("score", 0), 2), "explanation": explanation,
            "activity": buckets[subject.id],
        })

    # Round-robin includes small communities; the cap applies to distinct people.
    ordered_groups = [sorted(member_sets[subject.id]) for subject in subjects]
    sampled = {VIEWER_ID} if VIEWER_ID in member_topics else set()
    index = 0
    while len(sampled) < GRAPH_MEMBER_LIMIT and any(index < len(group) for group in ordered_groups):
        for group in ordered_groups:
            if index < len(group) and len(sampled) < GRAPH_MEMBER_LIMIT:
                sampled.add(group[index])
        index += 1
    subject_lookup = {subject.id: subject for subject in subjects}
    nodes = [{"id": s.id, "kind": "subject", "subject_id": s.id, "label": s.name, "color": s.color} for s in subjects]
    edges = []
    for person in sorted(sampled):
        topics = sorted(member_topics[person], key=lambda sid: (-current[(person, sid)]["score"], sid))
        primary = subject_lookup[topics[0]]
        nodes.append({"id": person, "kind": "member", "subject_id": primary.id,
                      "label": participants[person], "color": primary.color})
        for sid in topics:
            edges.append({"source": person, "target": sid, "weight": round(current[(person, sid)]["score"], 2), "kind": "affinity"})
    bridges = Counter()
    for topics in member_topics.values():
        bridges.update(combinations(sorted(topics), 2))
    edges.extend({"source": a, "target": b, "weight": count, "kind": "bridge"} for (a, b), count in sorted(bridges.items()))

    verbs = {"view": "discovered", "like": "liked", "save": "saved", "share": "shared", "join": "joined", "leave": "left"}
    activity = []
    for event in reversed(events[-40:]):
        description = f"{event['actor__name']} {verbs.get(event['kind'], event['kind'])} "
        description += f"“{event['content__title']}”" if event["content_id"] else event["subject__name"]
        if event["parent_id"]:
            description += " after a synthetic friend’s share"
        activity.append({"id": str(event["id"]), "actor": event["actor__name"], "kind": event["kind"],
            "subject_id": event["subject_id"], "subject_name": event["subject__name"],
            "content_title": event["content__title"] or "", "created_at": event["occurred_at"].isoformat(),
            "description": description})
    content_rows = [{"id": item.id, "subject_id": item.subject_id, "title": item.title, "punchline": item.punchline,
        "format": item.format, "creator": item.creator, "likes": len(like_actors[item.id]), "shares": shares[item.id],
        "trending_score": round(trends[item.id], 2)} for item in content]
    content_rows.sort(key=lambda row: (-row["trending_score"], row["id"]))
    return {
        "meta": {"is_demo": True, "simulated_at": now.isoformat(), "revision": state.revision,
            "sampled_nodes": len(sampled), "total_members": len(member_topics),
            "caption": f"Synthetic demo · {len(sampled)} people shown from {len(member_topics):,} distinct community members. Counts cover the full demo."},
        "stats": {"participants": len(participants), "active_communities": sum(s["status"] == "active" for s in subject_rows),
            "emerging_communities": sum(s["status"] == "forming" for s in subject_rows), "interactions": len(events),
            "shares": sum(e["kind"] == "share" for e in events), "bridges": sum(len(topics) > 1 for topics in member_topics.values())},
        "viewer": {"id": VIEWER_ID, "name": participants.get(VIEWER_ID, "You (demo)")},
        "subjects": subject_rows, "graph": {"nodes": nodes, "edges": edges}, "activity": activity, "content": content_rows,
        "methodology": {"half_life_days": HALF_LIFE_DAYS, "membership_threshold": MEMBERSHIP_THRESHOLD,
            "minimum_members": MINIMUM_MEMBERS, "minimum_content": MINIMUM_CONTENT, "weights": WEIGHTS,
            "description": "A person's strongest positive signal per joke contributes at most 4 points, decaying with a seven-day half-life. At least 6 points across 2 jokes infer membership; 5 independently engaged people activate a subject. Explicit joining alone does not count toward activation. Leaving overrides inference. Growth compares engaged people now with seven days ago. Shares and recipient reactions are separate synthetic events; no real social relationships are exposed."},
    }
