# MVP 0.2 — Creator Audience Intelligence (Design)

> Auto-generated design (2026-06-17). Demo-slice plan: plans/2026-06-17-mvp02-slice-1.md.

# MVP 0.2 — Creator Audience Intelligence

> Status: design for owner checkpoint. Scope: a demoable creator-facing analytics + growth toolkit built into the existing single Cloud Run Django app as a NEW modular `creator_insights` app, honoring the hard no-worker constraint (on-read aggregation + write-path counters only; no cron/Celery/batch) and the live content-tier compliance serving lock.

---

## 1. Vision & strategy

Give content creators a reason to keep creating: let them **see their audience**, **see which jokes win**, **watch their reach grow**, and get **concrete, data-backed suggestions to grow**. This is the headline deliverable of 0.2 and the seed of a future standalone "Creator Audience Intelligence" product. We build it as a **modular monolith**: a new self-contained app that READS the existing rich engagement event log, adds nothing to the live `jokes` tables for the demo, and mirrors the proven `notifications` app boundary (own `models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, `throttles.py`, `permissions.py`, own migrations, FKs only to `AUTH_USER_MODEL`).

The strategic bet from the research (TikTok/Buffer/Sprout 2025-26): **saves, off-platform shares, and completion/payoff predict growth far better than raw likes**. The joke platform already logs all three high-signal events — `SavedJoke`, `ShareEvent.platform`, and `JokeView.revealed_punchline` (a joke-native completion proxy). So the dashboard's headline quality metric is **payoff rate** (reveal rate), the joke equivalent of TikTok completion rate — not a vanity like count.

We mirror the universal **five-layer analytics IA** every platform converges on: **Overview KPIs → Reach → Engagement → Top content → Audience + Growth-over-time**.

**What we explicitly de-scope for 0.2** (YAGNI, no overshoot): geo/gender/age demographics (no PII, would expand consent), A/B testing (no thumbnails, the title *is* the joke, needs experiment infra), comment/reply engage-back loops (no comments exist). We substitute taste-based audience composition for demographics, and milestone/consistency nudges for the engage-back loop.

---

## 2. Audience model — the reality, and the follow/subscribe decision

### 2.1 The author-FK reality (verified in code)

There is **no `author`/`creator` FK on `Joke`** (`jokes/models.py:97`). The only author-style FK on any content object is `JokePack.created_by` (precedent). Creator attribution exists ONLY indirectly:

```
User → JokeSubmission.user (related_name='joke_submissions', status='published')
     → JokeSubmission.published_joke (OneToOne → Joke, on_delete=SET_NULL, reverse Joke.submission)
```

This is already production's source of truth for authorship: `TopJokestersView` (`jokes/views.py:1556`) ranks creators by `Count('joke_submissions', filter=published)` and never touches `Joke` for authorship.

**Caveats this join carries:**
- `published_joke` is `on_delete=SET_NULL` → deleting a submission silently orphans the joke's authorship.
- Seeded/imported catalog jokes were NOT born from a submission → they have **no creator**. For the demo, "my content" = submission-born published jokes only. That is correct and sufficient; the creator only cares about jokes they authored.
- No index supports the creator→jokes fan-out directly; the join goes through the `(user, status)` index on `JokeSubmission`, which is adequate at current volume.

**The creator's joke set** (the keystone query every metric keys off):
```python
Joke.objects.filter(submission__user=creator, submission__status='published')
```

**The author-FK fix (recommended, but staged AFTER the demo):** add a nullable, indexed `Joke.creator = ForeignKey(User, null=True, on_delete=SET_NULL, related_name='authored_jokes')`, stamped at publish time in `jokes/admin.py:186` (`creator=submission.user`), backfilled for existing submission-born jokes via a data migration (`joke.creator = joke.submission.user`). This turns the 2-hop join into a single indexed reverse query and makes the SET_NULL-orphan problem moot. **It is NOT required for the demo** — the join works today — so we defer it to the second slice to keep the demo a zero-migration-on-`jokes` change. The `creator_insights` service layer is written so that switching from the join to the FK is a one-line change in one resolver function.

### 2.2 "Audience" today = derived engagers

With no follow model, the audience of a creator is the **set of distinct users who engaged** the creator's jokes:

```
audience(creator) = distinct user_id across
  JokeView ∪ JokeReaction ∪ JokeRating ∪ Favorite ∪ SavedJoke ∪ ShareEvent
  WHERE joke ∈ creator's published jokes
```

For the demo we use **distinct `JokeView.user`** as the primary "reach" number (every engagement implies a view; it's the highest-volume signal and the cleanest single audience proxy), and expose the richer union as a future enhancement. `ShareEvent.user` is nullable (anonymous shares) so anon virality counts toward share totals but not toward audience identity.

### 2.3 Follow/subscribe — decision: **design it now, ship it in the SECOND slice**

The research is consistent (FanCircles/1000-true-fans): durable creator value is the casual→follower→superfan ladder, and a persistent creator↔audience edge is the single highest-leverage net-new primitive. It unlocks: a real growing audience number (not an approximation), **new-vs-returning** splits, **follower-growth-over-time**, the IG-style "which joke earned you the most new followers", and **notification targeting** ("new joke from a creator you follow" — reuses the existing notifications engine, request-triggered, no worker).

**Recommendation:** yes, add it — but NOT in the demo slice. The demo proves value on existing data with zero new tables on `jokes`. The follow model is a clean second slice:

```python
# creator_insights/models.py (owned by the new app; FKs only to AUTH_USER_MODEL)
class CreatorFollow(models.Model):
    follower = ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE, related_name='following')
    creator  = ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE, related_name='followers')
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    class Meta:
        unique_together = [['follower', 'creator']]
        indexes = [Index(fields=['creator', 'created_at'])]  # follower-growth-over-time
```

It lives in the new app, so it adds zero migrations to the live `jokes` tables and respects the no-worker rule (follower-count-over-time is computed on-read by `GROUP BY created_at::date` over the `(creator, created_at)` index; if it ever gets heavy, a per-creator `follower_count` counter is bumped on the write path). Self-follow blocked; respects `UserBlock`.

---

## 3. Creator metrics catalog

Every metric below honors the no-worker constraint: **prefer on-read aggregation over the existing indexes; add incremental counters only if a query is measured slow.** Owner-scoped reads (a creator viewing their OWN jokes) call the joke resolver with the tier gate **bypassed** (`allowed_tiers=None`) so a creator always sees all of their own content regardless of `content_tier`; any future *public/aggregate* creator surface must respect `serving.allowed_tiers(request)`.

Notation: `MY = Joke.objects.filter(submission__user=creator, submission__status='published')`. `since` = period window (week=6d, month=29d, all=None), matching `TasteProfileView`.

| Metric | Definition | Computation (on-read) | On-read vs counter | Indexes used / needed |
|---|---|---|---|---|
| **Total reach** | distinct users who viewed my jokes in period | `JokeView.objects.filter(joke__in=MY, viewed_date__gte=since).values('user').distinct().count()` | on-read for demo; counter not feasible (distinct can't be incrementally counted without a HLL — keep on-read) | `JokeView(joke, -viewed_at)` exists; ADD `JokeView(joke, viewed_date)` for date-windowed per-joke rollups |
| **Total views** | view rows on my jokes in period | `JokeView.objects.filter(joke__in=MY, viewed_date__gte=since).count()` | on-read now; **counter candidate** (`Joke.view_count` bumped in JokeView post_save) | `JokeView(joke, viewed_date)` (new) |
| **Payoff rate** (headline) | % of views that revealed the punchline | `views.filter(revealed_punchline=True).count() / total_views` | on-read | same as views |
| **Reactions** + emoji split | total `JokeReaction` on my jokes, grouped by `reaction` | `JokeReaction.objects.filter(joke__in=MY).values('reaction').annotate(c=Count('id'))` | on-read; counter candidate later | `JokeReaction(joke, reaction)` exists — covers this perfectly |
| **Favorites** | hearts on my jokes | `Favorite.objects.filter(joke__in=MY, created_at__date__gte=since).count()` | on-read | `Favorite(user, -created_at)`; per-joke scans (acceptable at scale) |
| **Saves** | bookmarks on my jokes | `SavedJoke.objects.filter(joke__in=MY).count()` | on-read | none on `joke` — small-scale scan; counter candidate |
| **Shares** + platform split | `ShareEvent` on my jokes grouped by `platform` | `ShareEvent.objects.filter(joke__in=MY).values('platform').annotate(c=Count('id'))` | on-read | `ShareEvent(joke, created_at)` exists |
| **Growth sparkline (28d)** | daily distinct viewers (or views) per day | `JokeView.filter(joke__in=MY, viewed_date__gte=today-27).values('viewed_date').annotate(c=Count('id'))` then map onto 28-day range (identical to `TasteProfileView.daily_reads_28d`) | on-read | `JokeView(joke, viewed_date)` (new) |
| **Peak audience hour** | hour-of-day histogram of when my audience reads | `views.annotate(h=ExtractHour('viewed_at')).values('h').annotate(n=Count('id')).order_by('-n').first()` (reuse `TasteProfileView` code) | on-read | scans windowed view set |
| **Discovery-source mix** | where readers found my jokes | `views.values('source').annotate(c=Count('id'))` | on-read | `JokeView.source` is `db_index`'d |
| **Top jokes leaderboard** | my published jokes ranked by views (+ reactions/saves/shares/payoff per joke) | annotate MY with `Count('views')`, `Count('reactions_v2')`, `Count('saved_by')`, `Count('share_events')`, payoff via filtered Count; order by `-view_count`, slice top 10 | on-read | reverse counts per joke; benefits from new `(joke, viewed_date)` |
| **Audience taste composition** | top Themes/Categories/Formats of engagers (via the jokes they engaged) | `views.values('joke__context_tags__name')...annotate(Count)` etc. (mirror `TasteProfileView` top_themes/categories/formats but scoped to MY jokes) | on-read | M2M joins |
| **Content-health (reports)** | report rate on my jokes | `ContentReport.objects.filter(joke__in=MY).count()` | on-read, shown only as a quiet health signal | join exists |

**Counter strategy (deferred, not in demo):** the only write-path hook needed is the SAME `post_save` on `JokeView` that already updates `Streak` (`jokes/signals.py:68`). If on-read becomes slow, add `view_count` / `reaction_count` / `save_count` / `share_count` to `Joke` (or to a `creator_insights`-owned `JokeStat` model to avoid touching `jokes`) and bump them in the existing signals. **Never a batch job.** Distinct-reach stays on-read (incremental distinct counting needs HLL — out of scope).

---

## 4. Growth tools / suggestions (the YouTube "Inspiration" pattern)

All computed on-read from the same data, surfaced as **suggestion cards** (not dashboards). Each card = a heuristic over the creator's own attributed jokes and/or platform-wide aggregates.

| Card | What it suggests | Heuristic / data behind it |
|---|---|---|
| **When your audience reads** | "Your readers are most active around 9 PM — that's your best window to publish." | `ExtractHour` histogram over engagers' `JokeView.viewed_at` (reuse `TasteProfileView` peak-hour). Framed as *when-your-audience-reads*, not strict publish scheduling (this app is pull/feed-driven, no scheduled publish). Show top 1-2 peak hours. |
| **What resonates** | "Your *dark* jokes get 3× the reactions per view of your *wholesome* ones — lean in." | For each of the creator's `tones`/`context_tags`/`format`, compute **reactions-per-view** and **save-rate** across MY jokes; rank; surface the top performer vs the creator's average. Pure aggregation over M2M tag data + view/reaction counts. |
| **Content gap** (optional, slice-2) | "*Workplace* humor is trending platform-wide and you haven't posted one in 30 days." | Cross platform-wide high-demand Themes (most-viewed/saved across all users, reusing `ThemesPopularView`-style aggregation) against Themes the creator has NOT written recently. |
| **Consistency nudge** | "You haven't published in 12 days. Creators who post 3-5×/week grow fastest." | Days since the creator's most recent `published` submission (`JokeSubmission.updated_at`). Pure date math. |
| **Milestone celebration** | "🎉 Your joke just crossed 1,000 reads!" | On dashboard load, check whether any MY joke's `view_count` crossed a milestone threshold since last seen. Reuses the notifications engine for the email/in-app version (request-triggered). |

For the **demo slice** we ship the first two ("When your audience reads", "What resonates") plus the **consistency nudge** — all three are pure on-read computations over data we already aggregate for the dashboard, so they cost almost nothing extra.

---

## 5. Modular-monolith structure — the new `creator_insights` app

Mirror the `notifications` app exactly (proven additive boundary, FKs only to `AUTH_USER_MODEL`, own migrations, single service entry point).

```
creator_insights/
  __init__.py
  apps.py                 # CreatorInsightsConfig
  models.py               # EMPTY for the demo slice (no new tables).
                          #   Slice 2: CreatorFollow; optional JokeStat counters.
  permissions.py          # IsCreator — user has >=1 published JokeSubmission
  services.py             # SINGLE entry point: build_creator_insights(creator, period)
                          #   - resolve_creator_jokes(creator)  ← the join (or future FK)
                          #   - overview(), top_jokes(), audience(), suggestions()
                          #   pure functions returning plain dicts; no DRF coupling
  serializers.py          # CreatorInsightsSerializer (response shape doc for schema)
  views.py                # CreatorInsightsView(APIView) GET /creators/me/insights/
  urls.py                 # mounted at /api/v1/creators/
  throttles.py            # CreatorInsightsThrottle (scope 'creator_insights')
  tests/
    __init__.py
    test_services.py      # aggregation correctness (the bulk of TDD)
    test_views.py         # endpoint contract, auth, IsCreator, period
    test_compliance.py    # owner-scoped tier bypass + no cross-user PII leak
    test_permissions.py   # IsCreator gate
```

**What it reads (read-only joins into `jokes`):** `Joke`, `JokeSubmission`, `JokeView`, `JokeReaction`, `JokeRating`, `Favorite`, `SavedJoke`, `ShareEvent`, `ContextTag`/`Tone`/`Format` (via M2M), and for slice-2 suggestions `ContentReport`. It imports these models read-only and NEVER writes to them. It owns only its own future models. The 5 existing ad-hoc analytics endpoints (`TasteProfileView`, `TopJokestersView`, `ThemesPopularView`, `TagsTrendingView`, `TagsRisingView`) can later be migrated into `creator_insights/services.py` with the legacy URLs delegating (out of scope for the demo, noted as a cleanup).

**Compliance policy (must be tested):** `resolve_creator_jokes` and all owner-scoped reads run with the tier gate OFF (creator sees their own tier_2). Document this explicitly. There is no public creator-analytics surface in 0.2, so no `allowed_tiers(request)` filtering is needed yet; the test suite locks both the "creator sees own tier_2" behavior and the "no other user's email/identity is ever in the response" invariant.

`INSTALLED_APPS += ['creator_insights']`; `urls.py`: `path('api/v1/creators/', include('creator_insights.urls'))`.

---

## 6. API surface

Demo slice (one endpoint):

```
GET /api/v1/creators/me/insights/?period=month|week|all
  Auth: IsAuthenticated + IsCreator (>=1 published submission)
  200 → {
    "period": "month",
    "is_creator": true,
    "overview": {
      "published_jokes": 7,
      "reach": 412,                 # distinct viewers
      "views": 1830,
      "payoff_rate": 0.61,          # revealed_punchline / views
      "reactions": 240,
      "favorites": 88,
      "saves": 53,
      "shares": 31,
      "peak_read_hour": 21,
      "daily_reach_28d": [ ... 28 ints ... ]
    },
    "reactions_breakdown": [ {"reaction":"lol","count":120}, ... ],
    "shares_breakdown":    [ {"platform":"whatsapp","count":14}, ... ],
    "source_mix":          [ {"source":"daily","count":700}, ... ],
    "top_jokes": [
      {"id":42,"text":"...","views":540,"reactions":80,"saves":22,
       "shares":9,"payoff_rate":0.7}
    ],
    "audience": {
      "top_themes":     [ {"label":"Work","count":210}, ... ],
      "top_categories": [ {"label":"Dark","count":180}, ... ],
      "top_formats":    [ {"label":"One-liner","count":300}, ... ]
    },
    "suggestions": [
      {"kind":"peak_hour","title":"...","detail":"...","data":{"hour":21}},
      {"kind":"what_resonates","title":"...","detail":"...","data":{...}},
      {"kind":"consistency","title":"...","detail":"...","data":{"days_since":12}}
    ]
  }
  403 → if authenticated but no published submission (not a creator yet)
```

Future (slice 2):
```
POST   /api/v1/creators/{user_id}/follow/      → CreatorFollow create
DELETE /api/v1/creators/{user_id}/follow/      → unfollow
GET    /api/v1/creators/me/insights/audience/  → new-vs-returning, follower-growth-28d
GET    /api/v1/creators/me/insights/jokes/{id}/ → per-joke drill-down
```

---

## 7. Frontend creator-dashboard surface

New feature module `src/features/creator-insights/` (mirrors `features/insights/`):

```
src/features/creator-insights/
  api.ts        # useCreatorInsights(period) — react-query, staleTime 5m
  index.ts      # re-exports
src/lib/api.ts  # add creatorInsightsApi.get(period) + CreatorInsights types
src/pages/CreatorInsightsPage.tsx        # the dashboard
src/pages/CreatorInsightsPage.test.tsx   # vitest
```

Wire into existing `CreatorHub`: add an **"Insights" tab/link** at `/create/insights` (the CreatorHub already lives at `/create`). Route added to `src/app/routes.tsx` under `ProtectedRoute`, page exported from `src/pages/index.ts`.

**Page layout** (uses the existing FlowAppShell + design tokens already in `CreatorHubPage.tsx`):
- **Header**: "Your audience" + period selector (Week / Month / All), matching the pill-tab style already in CreatorHub.
- **Overview KPI cards row**: Reach, Views, Payoff rate (highlighted as the hero card), Reactions, Saves, Shares.
- **Growth sparkline**: 28-day daily-reach line/bar (reuse whatever sparkline component the taste-profile insights feature already renders).
- **Top Jokes list**: card per joke with text snippet + views/reactions/saves/shares/payoff.
- **Audience composition**: top Themes / Categories / Formats chips + a discovery-source mix bar (daily/explore/mystery/...).
- **Growth suggestions**: 2-3 suggestion cards (peak hour, what resonates, consistency nudge).
- **States**: loading skeletons, error+retry (clone CreatorHub patterns), and an **empty/not-a-creator state** ("Publish your first joke to unlock insights" → CTA to `/create/new`) when the API returns 403 or zero published jokes.

Components: `KpiCard`, `GrowthSparkline`, `TopJokeRow`, `TasteChips`, `SourceMixBar`, `SuggestionCard` — all presentational, in `features/creator-insights/components/`.

---

## 8. Sequencing

1. **Slice 1 (the demo, this plan):** `creator_insights` app + `GET /creators/me/insights/` (on-read, join-based attribution, owner-scoped tier bypass) + the dashboard page. Zero migrations on `jokes`.
2. **Slice 2 (post-checkpoint):** `Joke.creator` FK + backfill (flip the resolver to the FK); `CreatorFollow` model + follow/unfollow endpoints + audience new-vs-returning + follower-growth chart + per-joke drill-down; notification seeding for new-joke-from-followed-creator.
3. **Slice 3 (scale, only if measured):** incremental counters on the existing `JokeView` post_save hook; migrate the 5 legacy analytics endpoints into the service layer.
