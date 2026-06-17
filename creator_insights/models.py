"""
creator_insights models.

Empty for demo slice 1 — no new tables.
Deferred to future slices:
  - Slice 2: CreatorFollow(follower, creator, created_at) — persistent audience edge,
    enables new-vs-returning splits and follower-growth-over-time.
  - Slice 3 (optional): JokeStat — per-joke denormalised counters (view_count,
    reaction_count, save_count, share_count) bumped on the existing JokeView
    post_save hook if on-read aggregation becomes measurably slow.
"""
