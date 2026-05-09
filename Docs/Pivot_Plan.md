# JokesFor — Pivot Plan: Mystery Box, Streaks, Categorization Refactor

> **Source**: design package at `~/Downloads/JokesFor` (Flow Canvas + Flow + Design Book + onboarding/home/library/search PDFs).
> Read in full: 5 analysis JSX files, 2 flow definition files (1212 lines), `tokens.jsx`, `screens-1..4.jsx`.
> Cross-referenced against current backend: `jokes/models.py` (16 models, 10 migrations live on Neon).
>
> **Status**: design + plan only. No code or migrations yet. Plan is intended to be reviewed before any backend work starts.

---

## 1. Executive summary

The pivot is **not a redesign of joke storage** — it's the addition of three new behavioural primitives that wrap the existing joke model:

1. **Vibes** — a curated 12-item "humor flavor" selector that drives onboarding, recommendations, and the Mystery Box.
2. **Streaks** — a daily reading commitment with forgiveness mechanics ("freeze days").
3. **Mystery Box** — a daily-capped variable-reward shuffle pulled from the user's vibes.

Plus secondary surfaces that need backend support:
4. **Reaction emojis** (4-way: 😂 🤣 🤔 🙄) replacing the like/dislike rating
5. **Joke Packs** — editor-curated themed bundles ("Back-to-school survival kit", "14 jokes for Valentine's")
6. **Issue numbering** for the Daily Joke ("Vol. I · No. 042" newspaper-style)
7. **Reading state** — "You stopped mid-sip · 2/4 from yesterday's Office Proper set"
8. **Multi-line knock-knock** format storage
9. **Tomorrow teaser** — preview tomorrow's joke (blurred)
10. **Taste profile** — derived analytics surface ("This month: 168 read · 42 saved · Top vibe: Pun")

The categorization refactor is a **clarification, not a rebuild**: the existing `Format` / `Tone` / `ContextTag` already form a 3-axis taxonomy. We rename for clarity (in serializers, not necessarily in DB) and add the curated `Vibe` layer on top.

**No data migration risk** — all changes are additive. Existing jokes retain their current taxonomy; new fields default to nullable.

---

## 2. The vocabulary problem (and the fix)

The design uses 4 words that all describe joke metadata. They are **not interchangeable** but the relationships are subtle. Getting this right is the most important decision in the pivot.

### The 4 axes the design uses

| Design term | Question it answers | Examples | Cardinality |
|---|---|---|---|
| **Format** | *How does it land?* | one-liner, setup→punchline, knock-knock, story, anti-joke, observational | one per joke |
| **Theme** | *What is it about?* | work, family, food, tech, school, dating, animals, science, travel, money, weather | many per joke |
| **Category** | *How does it feel?* | wholesome, office-proper, dad, kid-safe, nerd, surreal, dark, edgy | many per joke |
| **Vibe** | *Which curated humor flavor?* | Office, Dad jokes, Puns, Dark humor, Nerd, Surreal, Wholesome, Observational, One-liners, Date night, Kids OK, Absurd | many per joke + many per user |

### The trap

"Vibe" is **not a 4th axis** in the data model. It's a **curated preset over the other three axes**. Treating it as a 4th tag dimension would create:
- Triple-tagging burden on submitters/curators
- Inconsistency between e.g. `vibe=oneliner` and `format=oneliner` (which wins?)
- Drift over time (someone adds vibe "office" but forgets the underlying theme=work tag)

### Mapping to existing models

The current backend already has a **3-axis taxonomy**, just under different names. Renaming-only changes are needed at the serializer layer; the underlying model names stay (low-risk).

| Design name | Existing model | Action |
|---|---|---|
| Format | `Format` | None — already named correctly |
| Theme | `ContextTag` | Add `name` alias `Theme` in admin UI; serializer field renames `context_tags` → `themes` |
| Category | `Tone` | Same: alias to `Category`, serializer renames `tones` → `categories` |
| Vibe | *new model* | Add `Vibe` table with FK/M2M back to Format/Theme/Category |

`AgeRating`, `Language`, `CultureTag`, and `content_tier` (compliance tier) stay as-is. They're orthogonal to the curatorial axes.

### The Vibe model — proposed design

A `Vibe` is a **named filter recipe** + cosmetic metadata:

```python
class Vibe(models.Model):
    slug = models.SlugField(unique=True)        # "office", "dad", "puns", ...
    label = models.CharField(max_length=40)     # "Office", "Dad jokes"
    subtitle = models.CharField(max_length=80)  # "Meetings · Slack"
    icon = models.CharField(max_length=8)       # emoji; "💼"
    swatch_bg = models.CharField(max_length=20) # hex; "#6A1CF6"
    swatch_fg = models.CharField(max_length=20) # hex; "#fff"
    order = models.PositiveSmallIntegerField(default=0)

    # Filter recipe — populated by curators, used by Mystery Box and recs
    formats   = models.ManyToManyField(Format,     blank=True, related_name='vibes')
    themes    = models.ManyToManyField(ContextTag, blank=True, related_name='vibes')  # alias: themes
    categories= models.ManyToManyField(Tone,       blank=True, related_name='vibes')  # alias: categories
```

A vibe like **"Office"** = `categories ∋ office-proper` AND `themes ∋ work`.
A vibe like **"One-liners"** = `formats ∋ oneliner` (no theme/category constraint).
A vibe like **"Dark humor"** = `categories ∋ dark, edgy`.

This recipe is **stored** so the Mystery Box query is fast (`Joke.objects.filter(...)` based on the vibe's M2M sets).

### User ↔ Vibe relationship

```python
class UserVibe(models.Model):
    user = models.ForeignKey(User, related_name='vibes')
    vibe = models.ForeignKey(Vibe, related_name='users')
    weight = models.FloatField(default=1.0)  # for future tuning; user can pick "more of this"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'vibe']]
```

Or simpler: `User.vibes = M2M(Vibe)` if we don't need weight initially.

### Joke ↔ Vibe — should we tag jokes directly?

**Recommendation: no.** Compute joke→vibe membership on the fly via the recipe. This keeps the data normalised. If a vibe's recipe changes, the membership of every joke updates instantly without a backfill.

If query performance ever becomes a concern, materialise via a Postgres view or a periodic `joke_vibes` denormalised table.

---

## 3. Concept-by-concept catalog with backend implications

### 3.1 Streaks

**What the user sees**: 14-day streak chip in the header, a 14-cell streak grid on Today, "1 day from Top 10%" copy, "streak-saver" notifications at 8 PM if user hasn't read.

**Backend needs**:

```python
class Streak(models.Model):
    user = models.OneToOneField(User, related_name='streak')
    current_count = models.PositiveIntegerField(default=0)
    longest_count = models.PositiveIntegerField(default=0)
    last_active_date = models.DateField(null=True)
    freeze_days_available = models.PositiveSmallIntegerField(default=2)  # forgiveness mechanic
    freezes_used_total = models.PositiveIntegerField(default=0)
    started_at = models.DateField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
```

Plus a daily activity log (so the 14-cell grid can render):

```python
class StreakDay(models.Model):
    user = models.ForeignKey(User, related_name='streak_days')
    date = models.DateField()
    status = models.CharField(choices=[('read','Read'), ('frozen','Frozen'), ('missed','Missed')])

    class Meta:
        unique_together = [['user', 'date']]
        indexes = [models.Index(fields=['user', '-date'])]
```

**Logic** (all request-triggered, no scheduled jobs):
- On any joke read by the user that day → mark today as `read`, increment streak if continuous (synchronous, in `JokeView` post-save signal)
- **Lazy missed-day detection**: when user fetches `/streak/`, backend computes the gap between today and `last_active_date`. For each missed day with `freeze_days_available > 0` → auto-burn a freeze; if any gap remains uncovered → reset `current_count` to 0. This computes on read, not via cron.
- **Streak-saver "8 PM push" replacement**: response includes `streak_at_risk_today: bool` flag (true if user hasn't read today and it's past their local 8 PM). Frontend renders an in-app nudge.

**API**:
- `GET /api/v1/users/me/streak/` → `{ current, longest, freeze_days, last_14_days: [...] }`
- `POST /api/v1/users/me/streak/freeze/` → manually use a freeze day (for "I'm on vacation" UX)

### 3.2 Mystery Box

**What the user sees**: a card on Today saying "Mystery box · 3 left today" with a Roll button. Tapping returns one randomly-selected joke from the user's vibe pool.

**Backend needs**:

```python
class MysteryBoxRoll(models.Model):
    user = models.ForeignKey(User, related_name='mystery_rolls')
    joke = models.ForeignKey(Joke, related_name='mystery_pulls')
    rolled_at = models.DateTimeField(auto_now_add=True)
    # day-bucket field for fast "today's rolls" count
    rolled_date = models.DateField(db_index=True)
```

**Logic**:
- Daily cap: `MAX_DAILY_ROLLS = 3` (config)
- Pull algorithm: aggregate the joke pool from all the user's vibes' recipes; exclude jokes the user has already saved or seen via DailyJoke this week; weighted random pick
- If user has no vibes (skipped onboarding) → fall back to global trending pool

**API**:
- `GET /api/v1/mystery-box/status/` → `{ rolls_used_today, rolls_remaining_today, max_per_day }`
- `POST /api/v1/mystery-box/roll/` → `{ joke: {...}, rolls_remaining_today }` or `429` if cap hit

### 3.3 Reactions (replaces simple Like/Dislike)

**What the user sees**: 4 emoji reactions on the Joke Detail card: 😂 LOL · 🤣 Crying · 🤔 Hmm · 🙄 Eye-roll. Aggregated counts shown.

**Current backend**: `JokeRating` with `rating IN (1, -1)`.

**Two paths**:

**Path A (clean break)** — replace `JokeRating` with `JokeReaction` that has 4 reaction types. Migration needed to map existing likes → 😂, dislikes → 🙄.

**Path B (additive)** — keep `JokeRating` for existing like/dislike, add new `JokeReaction` model:
```python
class JokeReaction(models.Model):
    REACTIONS = [
        ('lol',   '😂 LOL'),
        ('crying','🤣 Crying'),
        ('hmm',   '🤔 Hmm'),
        ('eyeroll','🙄 Eye-roll'),
    ]
    user = models.ForeignKey(User)
    joke = models.ForeignKey(Joke, related_name='reactions')
    reaction = models.CharField(max_length=10, choices=REACTIONS)
    class Meta:
        unique_together = [['user', 'joke']]  # one reaction per user per joke
```

**Recommendation**: Path A (cleaner long-term). The existing `JokeRating` data is small (likely <100 rows in dev), backfill is trivial.

**API**:
- `POST /api/v1/jokes/{id}/react/` → `{ reaction: 'lol' }` (toggle off if same; switch if different)
- `GET /api/v1/jokes/{id}/reactions/` → `{ counts: { lol: 412, crying: 188, hmm: 38, eyeroll: 12 }, my_reaction: 'lol' | null }`

### 3.4 Joke Packs (curated bundles)

**What the user sees**: "Back-to-school survival kit · 45 jokes" or "14 jokes for Valentine's". Editor-curated themed sets.

**Different from Collections**: Collections are user-owned. Packs are editor-owned and shipped to all users.

```python
class JokePack(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    cover_color = models.CharField(max_length=20, default='#FFC965')
    is_published = models.BooleanField(default=False)
    publish_at = models.DateTimeField(null=True, blank=True)  # for scheduled releases
    expires_at = models.DateTimeField(null=True, blank=True)  # e.g. Valentine's pack expires Feb 15
    jokes = models.ManyToManyField(Joke, through='JokePackEntry', related_name='packs')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')

class JokePackEntry(models.Model):
    pack = models.ForeignKey(JokePack)
    joke = models.ForeignKey(Joke)
    order = models.PositiveSmallIntegerField()
    class Meta:
        unique_together = [['pack', 'joke']]
        ordering = ['order']
```

Plus user progress tracking (for "You stopped mid-sip · 2/4"):

```python
class JokePackProgress(models.Model):
    user = models.ForeignKey(User, related_name='pack_progress')
    pack = models.ForeignKey(JokePack)
    last_read_entry = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        unique_together = [['user', 'pack']]
```

**API**:
- `GET /api/v1/packs/` → published packs (paginated)
- `GET /api/v1/packs/{slug}/` → pack with jokes
- `GET /api/v1/users/me/packs/in-progress/` → packs user has started but not finished
- `POST /api/v1/packs/{slug}/progress/` → `{ entry_order: 2 }` to record progress

### 3.5 Reading state / "Continue yesterday's set"

Subset of pack progress above, plus a general read-event log:

```python
class JokeView(models.Model):
    user = models.ForeignKey(User, related_name='joke_views')
    joke = models.ForeignKey(Joke, related_name='views')
    viewed_at = models.DateTimeField(auto_now_add=True)
    revealed_punchline = models.BooleanField(default=False)  # for tap-to-reveal stat
    source = models.CharField(max_length=20, choices=[
        ('daily','Daily'), ('search','Search'), ('explore','Explore'),
        ('mystery','Mystery'), ('pack','Pack'), ('saved','Saved'), ('share','Share'),
    ])
    class Meta:
        indexes = [
            models.Index(fields=['user', '-viewed_at']),
            models.Index(fields=['joke', '-viewed_at']),
        ]
```

This single table powers:
- "168 jokes read this month" stat
- "9 AM peak read" derivation
- "What you've been laughing at" sparkline
- "Continue yesterday's set" lookup
- Streak day determination (any view on a date → that date counts)
- Mystery Box exclusion (don't pull jokes seen this week)

High write volume — index carefully, consider partitioning later.

### 3.6 Notification ritual

The design adds **day-of-week selection** + **streak-saver toggle** beyond the existing `notification_time`.

Extend `UserPreference`:

```python
# Add to existing UserPreference model:
notification_days = models.CharField(
    max_length=14, default='1234567',
    help_text='String of weekday digits 1-7; "12345" = weekdays only'
)
streak_saver_enabled = models.BooleanField(default=True)
streak_saver_time = models.TimeField(default='20:00')  # 8 PM nudge
```

Or better — use a proper bit field via `django-bitfield` or a JSON field:
```python
notification_days = models.JSONField(default=list)  # ['mon','tue','wed','thu','fri']
```

### 3.7 Issue numbering for Daily Joke

"Vol. I · No. 042" newspaper styling. **Don't store this as a column** — derive from the launch date:

```python
LAUNCH_DATE = date(2026, 1, 1)
def issue_number(d):
    days_since_launch = (d - LAUNCH_DATE).days
    return f"Vol. I · No. {days_since_launch + 1:03d}"
```

Add to `DailyJoke` serializer as a computed field. If we ever cross 365 days → "Vol. II · No. 001" automatically.

### 3.8 Knock-knock multi-line storage

Current `Joke` model has `text`, `setup`, `punchline`. Knock-knock has 5 lines (call/response). Two options:

**Option A — JSON field on Joke** (cheap, denormalised):
```python
lines = models.JSONField(null=True, blank=True)  # ['Knock, knock.', 'Who\'s there?', ...]
```

**Option B — separate JokeLine table** (normalised):
```python
class JokeLine(models.Model):
    joke = models.ForeignKey(Joke, related_name='lines')
    order = models.PositiveSmallIntegerField()
    speaker = models.CharField(max_length=10, choices=[('A','A'), ('B','B')])
    text = models.TextField()
```

**Recommendation: A.** Multi-line jokes are a small fraction of the corpus, and we never need to query *into* the lines (only display them). JSON is fine.

When `format == 'knock'`, the API response returns `lines: [...]`. For other formats, `lines: null` and `text` / `setup`+`punchline` are used.

### 3.9 Tomorrow teaser

Today screen shows tomorrow's joke partially blurred. Backend just needs to expose tomorrow's `DailyJoke` for the user with **only setup or first 12 words** (the frontend renders the blur):

```
GET /api/v1/daily-jokes/tomorrow/
→ { format: 'story', preview: 'A man walks into a library and asks for a book on…', read_time: '2 min' }
```

Or the existing `DailyJoke` model + a "preview" computed serializer field that truncates at 12 words.

This requires `DailyJoke` rows for tomorrow to exist at the time of the request. **No Celery, so generation is lazy**: when the endpoint is hit, if today's or tomorrow's `DailyJoke` row for this user doesn't exist yet, the view generates one inline (using the same selection logic the old beat task used) and returns it. First-request latency is ~50ms; subsequent requests hit the existing row.

### 3.10 Top Jokesters leaderboard

Already exists at `GET /api/v1/users/top-jokesters/`. Confirm the response shape matches the design:

| Design field | Backend field |
|---|---|
| Name | `display_name` from UserProfile |
| Handle | `handle` from UserProfile |
| Punchlines count | derived: count of approved JokeSubmissions in window |
| Vibe tags | top 2 vibes by submission count (NEW — derive from submissions) |

May need: `?window=week|month|all` query param + vibe tag derivation in the view.

### 3.11 Taste profile (derived analytics)

The "How you've been laughing this month" panel + "Themes you laugh at most" pill cloud. **Pure derivations** from `JokeView`, `SavedJoke`, `JokeReaction` — no new model.

```
GET /api/v1/users/me/taste-profile/
→ {
    period: 'month',
    jokes_read: 168,
    jokes_saved: 42,
    peak_read_hour: 9,        // 9 AM
    top_vibe: { slug: 'puns', label: 'Puns' },
    top_themes:    [{ label: 'Office life', count: 42 }, ...],
    top_categories:[{ label: 'Wholesome',  count: 24 }, ...],
    top_formats:   [{ label: 'One-liners', count: 21 }, ...],
    daily_reads_28d: [12, 18, 8, ...]   // sparkline data
  }
```

### 3.12 Generated session names (Spotify Daylist style)

"Chaotic Tuesday energy" — generated descriptive labels for the user's current taste. **Lower priority** for MVP; defer to a later phase that uses the Claude API to generate.

---

## 4. Phased rollout — vertical business slices

**Sequencing principle.** Each phase ships a **complete user-facing behaviour loop** that QA / product can validate end-to-end while the next phase is being built. A phase is "done" when a user can perform an action, see persistence, refresh the page, and watch the loop close — not when a table exists. This is closer to how the team validates work in practice.

**Decisions baked in** (per your calls on 2026-05-09):
- Categorization renames are **alias-only** at the serializer/admin layer — no DB rename, no migration window.
- `JokeReaction` is **additive** alongside `JokeRating`, no destructive migration of existing rating rows.
- Phase boundaries are **vertical slices** (one complete loop per phase).
- **Single Cloud Run app** — no Celery, no workers, no cron/beat. Everything is request-triggered. Anything that was a scheduled task becomes either on-demand computation or a flag the frontend reads.

### Dependency graph (read top-down; lateral = parallel-buildable)

```
                      ┌─────────────────┐
                      │ P1 · Foundation │  serializer aliases
                      └────────┬────────┘
              ┌────────────────┼────────────────┬────────────────┐
              ▼                ▼                ▼                ▼
       ┌─────────────┐  ┌─────────────┐  ┌────────────┐  ┌─────────────┐
       │ P2 · Vibes  │  │ P4 · React  │  │ P5 · Views │  │ P7 · Packs  │
       └──────┬──────┘  └─────────────┘  └─────┬──────┘  └─────────────┘
              ▼                                ▼
       ┌──────────────┐                  ┌─────────────┐
       │ P3 · Mystery │                  │ P6 · Streak │
       │      Box     │                  └──────┬──────┘
       └──────────────┘                         ▼
                                         ┌──────────────┐
                                         │ P8 · Ritual  │
                                         │   nudges     │
                                         └──────────────┘

       ┌──────────────────────────────────────────────────┐
       │ P9 · Insights (taste profile + tomorrow + issue) │  depends on P5+
       └──────────────────────────────────────────────────┘
       ┌──────────────────────────────────────────────────┐
       │ P10 · Polish (top jokesters, knock-knock lines)  │  parallel anytime
       └──────────────────────────────────────────────────┘
```

**Critical path** (for the demo-critical loop): **P1 → P2 → P3** (Vibes + Mystery Box) and **P1 → P5 → P6** (Streak). These two chains can run in parallel from end of P1.

---

### Phase 1 · Foundation — categorization aliases (½ day)
*Unblocks every other phase. No model changes.*

**Scope**
- Update `JokeSerializer`: rename outputs `tones → categories`, `context_tags → themes`. Accept both names on input during a deprecation window (1 month).
- Update `UserPreferenceSerializer`: same.
- Admin UI: add `verbose_name` overrides ("Category" for `Tone`, "Theme" for `ContextTag`) so curators see the design vocabulary.
- Update `Frontend_Integration_Handout.md` + regenerate OpenAPI schema.

**Business loop validated**
> A frontend developer hits `/api/v1/jokes/{id}/` and sees `categories: [...]` and `themes: [...]` in the response. The endpoint catalogue and the design now share one vocabulary.

**Validation checklist**
- [ ] `GET /jokes/1/` returns both `themes` and `categories` keys
- [ ] `POST /jokes/submit/` accepts payload with new key names
- [ ] OpenAPI schema reflects new names; Swagger UI shows them
- [ ] Existing frontend (using old names) keeps working via input aliases
- [ ] Admin: editing a Joke shows "Themes" and "Categories" labels

**Dependencies** — none.
**Parallel** — n/a (gate phase).

---

### Phase 2 · The humor fingerprint — Vibes (3 days)
*Closes the onboarding loop. User picks 3+ vibes, vibes persist across sessions, vibes drive recommendations.*

**Scope**
- Models: `Vibe`, `UserVibe`
- Data migration: seed the 12 canonical vibes (slug, label, subtitle, icon, swatches, recipe pre-populated) from `parts/flow.jsx` lines 26-39
- Admin UI: editor can adjust each vibe's filter recipe (`formats`, `themes`, `categories` M2M)
- Endpoints:
  - `GET    /api/v1/vibes/` — catalog (12 entries with display metadata)
  - `GET    /api/v1/users/me/vibes/` — current user's selected vibes
  - `PUT    /api/v1/users/me/vibes/` — replace user's selection (body: `{ slugs: ['office', 'puns', ...] }`)
  - `GET    /api/v1/jokes/?vibe=office` — filter jokes by vibe (resolves to recipe-derived filter)

**Business loop validated**
> User logs in → onboarding screen 1 displays 12 vibes → user picks "Office", "Puns", "Observational" → submits → reloads page → vibes still selected → calls `/jokes/?vibe=office` → returns jokes matching the Office recipe.

**Validation checklist**
- [ ] All 12 vibes seeded with correct icons + swatches matching design
- [ ] Picking < 3 vibes returns 400 (matches design's "Pick at least 3")
- [ ] User's vibes survive logout/login
- [ ] `?vibe=office` filter returns jokes whose `themes ∋ work` AND `categories ∋ office-proper` (the recipe)
- [ ] Two users with disjoint vibe selections see different recommendations

**Dependencies** — P1.
**Parallel** — P4 (Reactions), P5 (Views), P7 (Packs) can be built in parallel by other engineers; none of them touch Vibe.

---

### Phase 3 · The variable reward — Mystery Box (2 days)
*Closes the dopamine loop. User taps Roll, gets a joke from their vibe pool, daily cap enforced.*

**Scope**
- Model: `MysteryBoxRoll` (user, joke, rolled_date, source_vibe)
- Pull algorithm:
  1. Aggregate joke pool from user's `UserVibe` recipes
  2. Exclude jokes user has saved this month or seen via `DailyJoke` this week
  3. If pool < 5 jokes after filtering → fallback to global trending
  4. Weighted random pick (weight by vibe weight if `UserVibe.weight` exists)
- Cap enforcement: `MAX_DAILY_ROLLS = 3` (settings, env-overridable)
- Endpoints:
  - `GET  /api/v1/mystery-box/status/` — `{ rolls_used_today, rolls_remaining_today, max_per_day }`
  - `POST /api/v1/mystery-box/roll/` — `{ joke: {...}, rolls_remaining_today }` or 429 if cap

**Business loop validated**
> User on Today screen sees "Mystery box · 3 left today" → taps Roll → modal opens with a joke from their Office vibe → counter ticks to 2 → rolls 3 times → 4th attempt returns 429 → midnight UTC passes → counter resets to 3.

**Validation checklist**
- [ ] User with 0 vibes selected → fallback to trending pool (no 500)
- [ ] User with 6 vibes → pool unions correctly across all
- [ ] 3rd roll succeeds, 4th returns 429 with clear error message
- [ ] Counter resets at midnight in user's local timezone (or UTC — see open Q5.4)
- [ ] Joke seen via Daily this week is not pulled
- [ ] Joke saved this month is not pulled

**Dependencies** — P1, P2.
**Parallel** — none with Vibes (must wait), but P4/P5/P7 can still run alongside.

---

### Phase 4 · The reaction loop — 4-emoji reactions (2 days)
*Closes the engagement loop. User reacts, count updates, user sees their reaction persist.*

**Scope**
- Model: `JokeReaction` (additive — `JokeRating` stays untouched). Unique on `(user, joke)` so a user can swap-but-not-stack reactions.
- Endpoints:
  - `POST   /api/v1/jokes/{id}/react/` — body: `{ reaction: 'lol' | 'crying' | 'hmm' | 'eyeroll' }`. Toggle off if same; switch if different. Returns `{ my_reaction, counts }`.
  - `GET    /api/v1/jokes/{id}/reactions/` — public counts
  - Embed reaction summary in `JokeSerializer` (so detail page doesn't need 2 calls)

**Business loop validated**
> User opens joke detail → 4 emoji buttons render counts (412/188/38/12) → user clicks 😂 → counter goes to 413 → button highlights → user clicks 🤔 → 😂 drops back to 412, 🤔 goes 38→39 → user clicks 🤔 again → 🤔 drops to 38, no reaction selected.

**Validation checklist**
- [ ] First reaction increments target count by 1
- [ ] Switching reaction decrements old, increments new
- [ ] Same-reaction click un-reacts (decrements, returns `my_reaction: null`)
- [ ] Unauthenticated POST returns 401
- [ ] `JokeRating` rows untouched (no destructive change)
- [ ] OpenAPI schema includes the 4 reaction enum values

**Dependencies** — P1.
**Parallel** — fully independent of P2/P3/P5/P7. Can ship anytime after P1.

---

### Phase 5 · The activity log — JokeView (1 day)
*Foundational layer for streak (P6), insights (P9), and "continue mid-sip" (P7). Standalone but unlocks four downstream features.*

**Scope**
- Model: `JokeView` (user, joke, viewed_at, source, revealed_punchline)
- Signal/middleware: log a view whenever an authenticated user fetches `/jokes/{id}/`
- Optional batching: collect views in Redis, flush to DB every 30s (defer until volume justifies)
- Endpoint: `GET /api/v1/users/me/recently-viewed/?limit=20` — for "continue mid-sip"

**Business loop validated**
> User opens Joke A, then B, then C → calls `/users/me/recently-viewed/` → returns C, B, A in that order with timestamps and source field.

**Validation checklist**
- [ ] View logged with correct `source` (daily / search / explore / mystery / pack)
- [ ] `revealed_punchline=true` recorded on tap-to-reveal
- [ ] Anonymous fetches don't create a view row
- [ ] No double-log on same joke within 1 minute (debouncing)
- [ ] Index `(user, -viewed_at)` works for fast recent-views query

**Dependencies** — P1.
**Parallel** — fully independent. Recommended to ship in parallel with P2/P3/P4 since downstream phases need it.

---

### Phase 6 · The commitment loop — Streak (3 days)
*Closes the daily-return loop. User reads → streak ticks → must read tomorrow or freeze → 14-day grid renders.*

**Scope**
- Models: `Streak` (one-to-one with user), `StreakDay` (per-day status)
- Logic (all request-triggered — no scheduled jobs):
  - On `JokeView` post-save → upsert today's `StreakDay(status='read')`, recompute `Streak.current_count` based on continuous read/frozen days back from today
  - **Lazy gap reconciliation**: when `/streak/` is fetched, backend computes the gap between today and `last_active_date`; auto-burns freezes for each missed day up to `freeze_days_available`; resets count if any gap remains uncovered
  - Forgiveness: 2 freezes per month, refreshed monthly (computed lazily on access — `if last_freeze_refresh_month != current_month: reset to 2`)
- Endpoints:
  - `GET   /api/v1/users/me/streak/` — `{ current, longest, freeze_days, streak_at_risk_today, last_14_days: [...] }`
  - `POST  /api/v1/users/me/streak/freeze/` — manually use a freeze ("vacation mode")
  - `POST  /api/v1/users/me/streak/freeze/remove/` — undo today's freeze if used by accident

**Business loop validated**
> Day 1: user reads → streak = 1 → 14-cell grid shows 1 filled cell → next day, user reads at 9 AM → streak = 2 → user takes Saturday off → midnight task auto-burns freeze (`freeze_days_available: 2 → 1`) → Sunday, user reads → streak = 4 (3 read + 1 frozen) → user misses 2 days with 0 freezes → streak resets to 0.

**Validation checklist**
- [ ] First view of the day creates `StreakDay(status='read')`
- [ ] Subsequent views same day don't double-count
- [ ] Continuous reading increments streak; gap with no freeze resets it
- [ ] Manual freeze decrements `freeze_days_available`
- [ ] 14-cell grid returns last 14 days in chronological order with status per day
- [ ] Timezone respected (user-local, not UTC) — see open Q5.4

**Dependencies** — P1, P5.
**Parallel** — independent of P2/P3/P4/P7.

---

### Phase 7 · The editorial loop — Joke Packs (3 days)
*Closes the curation loop. Editor publishes pack → user starts → progress tracked → user resumes next day → completion.*

**Scope**
- Models: `JokePack`, `JokePackEntry`, `JokePackProgress`
- Admin UI: editors create packs, drag-order jokes, set publish date, cover color
- Endpoints:
  - `GET    /api/v1/packs/` — published packs (paginated, filterable by `?featured=true`)
  - `GET    /api/v1/packs/{slug}/` — pack detail with full joke list
  - `GET    /api/v1/users/me/packs/in-progress/` — packs user has started but not finished
  - `POST   /api/v1/packs/{slug}/progress/` — body: `{ entry_order: 2 }` to record where user is
  - `GET    /api/v1/packs/featured-this-week/` — single pack for the "Weekly Special" surface

**Business loop validated**
> Editor publishes "Back-to-school survival kit" with 45 jokes → user opens Today screen → sees Weekly Special tile → taps → reads jokes 1-2 → leaves → next day, taps "Continue mid-sip" → resumes at joke 3 → reads through 45 → completed_at set → pack disappears from in-progress.

**Validation checklist**
- [ ] Pack with publish_at in future is hidden until that date
- [ ] Pack with expires_at in past is hidden after that date
- [ ] User can have multiple packs in progress simultaneously
- [ ] `progress.last_read_entry` updates correctly on each `POST /progress/`
- [ ] Completion sets `completed_at` and removes from `in-progress` list
- [ ] Featured-this-week endpoint returns most recent featured pack with `is_published=True`

**Dependencies** — P1.
**Parallel** — independent of P2/P3/P4/P5/P6. Can be assigned to a different engineer while critical path runs.

---

### Phase 8 · Ritual preferences — settings persistence only (1 day)
*Closes the preference loop, NOT the push-delivery loop. Backend stores when/how the user wants their reminder; **the push itself is a frontend concern** (web push, FCM client SDK, or simply an in-app banner).*

**Scope** (revised given no-Celery constraint)
- Extend `UserPreference`: add `notification_days` (JSON list of weekday names), `streak_saver_enabled`
- Update `UserPreferenceSerializer` to expose these
- Backend exposes a `streak_at_risk_today: bool` computed flag in `/users/me/streak/` (true if user hasn't read AND it's past their local 8 PM AND `streak_saver_enabled`); frontend renders the in-app nudge
- Backend exposes `daily_joke_due: bool` flag in `/users/me/today/` (true if it's after `notification_time` on a configured day and user hasn't read); frontend renders the "Today's joke is ready" surface
- Push delivery itself (FCM/APNs/web-push) is **out of scope for this phase** — backend is reactive only

**Business loop validated**
> User picks 9:00 AM + Mon-Fri + streak saver on → settings persist → at 9 AM Tue, frontend polls `/users/me/today/` → sees `daily_joke_due: true` → renders "Today's joke is ready" hero → user reads → flag clears. At 8 PM, frontend checks `/users/me/streak/` → sees `streak_at_risk_today: true` → renders an in-app banner.

**Validation checklist**
- [ ] Notification settings persist across login
- [ ] `daily_joke_due` flag respects user's chosen days (Sat/Sun off → flag stays false those days)
- [ ] `streak_at_risk_today` only true if `streak_saver_enabled=True`, user hasn't read today, and local time > 20:00
- [ ] Email digest setting honored (existing field)
- [ ] No scheduled tasks added to Cloud Run service

**Dependencies** — P1, P6 (streak risk flag needs streak), P5 (read detection needs JokeView).
**Parallel** — independent of P2/P3/P4/P7.

---

### Phase 9 · The insight loop — Taste profile + Tomorrow teaser + Issue label (1 day)
*Closes the self-knowledge loop. User reads regularly → sees their stats grow → sees tomorrow teased → sees today's issue number.*

**Scope**
- Endpoint: `GET /api/v1/users/me/taste-profile/` — derives from `JokeView`, `SavedJoke`, `JokeReaction`:
  ```
  { period, jokes_read, jokes_saved, peak_read_hour, top_vibe, top_themes,
    top_categories, top_formats, daily_reads_28d }
  ```
- Endpoint: `GET /api/v1/daily-jokes/tomorrow/` — preview (first 12 words of tomorrow's joke for the blurred teaser); **lazy-generates** tomorrow's `DailyJoke` row inline if it doesn't exist yet
- Endpoint: `GET /api/v1/daily-jokes/today/` — same lazy-generation pattern (eliminates need for any cron task)
- Add `issue_label` computed field to `DailyJokeSerializer`: derived from launch date + days offset
- Cache taste profile in Redis with 1h TTL (it's read-heavy, write-light)

**Business loop validated**
> User reads jokes for a week → opens Today screen → sees "168 jokes read this month · 42 saved · 9 AM peak read · Top vibe: Pun" → sees tomorrow's joke partially blurred → sees "Vol. I · No. 042" eyebrow.

**Validation checklist**
- [ ] Taste profile reflects actual read history accurately
- [ ] `daily_reads_28d` is 28 integers, oldest first
- [ ] Peak read hour is most common hour from `JokeView.viewed_at`
- [ ] Tomorrow endpoint returns truncated text (12 words max)
- [ ] Issue label increments by 1 each calendar day from launch
- [ ] User with no view history → returns zeros, no errors

**Dependencies** — P1, P5 (views), P2 (top vibe).
**Parallel** — independent of P3/P4/P6/P7.

---

### Phase 10 · Polish — Top Jokesters refresh + Knock-knock lines (1 day)
*Two small surfaces, neither a full loop. Group together as "polish".*

**Scope**
- Extend `Top Jokesters` view: include each user's top 2 vibes (derived from their accepted submissions)
- Add `?window=week|month|all` query param
- Add `lines` `JSONField(null=True)` to `Joke`
- Update `JokeSerializer`: when `format=knock`, return `lines` array; else `null`
- Migration: backfill existing knock-knock jokes (parse `text` into lines if pattern matches)

**Business loop validated**
> Today screen shows leaderboard with vibe pills next to each user. Joke detail for a knock-knock joke renders 5 dialogue bubbles (call/response).

**Validation checklist**
- [ ] Top Jokesters returns 5 users with vibe tags
- [ ] `?window=week` only counts submissions from last 7 days
- [ ] Knock-knock joke serializer returns `lines: [...]`, other formats return `lines: null`
- [ ] Existing knock-knock jokes either backfilled or render with lines: null gracefully

**Dependencies** — P1.
**Parallel** — fully independent. Cheapest phase, often done by the engineer between bigger pieces.

---

### Total estimate and parallelism strategy

| Phase | Days | Critical path? | Parallel-buildable with |
|---|---|---|---|
| P1 Foundation | 0.5 | Yes (gate) | — |
| P2 Vibes | 3 | Yes | P4, P5, P7, P10 |
| P3 Mystery Box | 2 | Yes (after P2) | P4, P5, P7, P10 |
| P4 Reactions | 2 | No | P2, P3, P5, P6, P7, P10 |
| P5 JokeView | 1 | No (but unlocks P6/P9) | P2, P3, P4, P7, P10 |
| P6 Streak | 3 | No | P2, P3, P4, P7, P10 |
| P7 Joke Packs | 3 | No | P2, P3, P4, P5, P6, P10 |
| P8 Ritual | 2 | No | P2, P3, P4, P7 |
| P9 Insights | 1 | No | P3, P4, P6, P7 |
| P10 Polish | 1 | No | anytime after P1 |

**Total backend work**: 18.5 person-days.

**Single-engineer sequencing**: P1 → P5 → P2 → P3 → P6 → P4 → P7 → P8 → P9 → P10 (~3.5 weeks).

**Two-engineer fan-out**: After P1 (½ day), engineer A runs P5 → P2 → P3 → P6 → P8 (~10 days). Engineer B runs P4 → P7 → P9 → P10 (~7 days). **Total elapsed: ~2 weeks.**

**Three-engineer fan-out**: After P1, three parallel chains:
- Chain A (critical): P2 → P3 (5 days)
- Chain B (streak loop): P5 → P6 → P8 (6 days)
- Chain C (independent surfaces): P4 → P7 → P10 (6 days)
- Then P9 sweeps up after B ships P5+ and C ships P7. **Total elapsed: ~7 days.**

Each phase's "Validation checklist" is the QA acceptance gate — frontend can integrate against the deployed phase while the next chain is being built.

---

## 5. Risks and open questions

### 5.1 Vibe ↔ joke membership performance
If a user picks 6 vibes and the Mystery Box does `Joke.objects.filter(formats__in=..., themes__in=..., categories__in=...)` it'll work fine for tens of thousands of jokes but could become slow at hundreds of thousands. **Mitigation**: materialize membership in a `vibe_jokes` table refreshed on vibe-recipe changes (rare event).

### 5.2 Reaction migration data loss
Path A (replace JokeRating with JokeReaction) loses the like/dislike binary signal. Acceptable trade because production data volume is tiny. Confirm before pulling the trigger.

### 5.3 JokeView write volume
Logging every joke view → potentially 10k+ inserts/day at modest scale. For MVP this is fine on Neon's free tier; at scale, consider:
- Async insert via Celery
- Batch flush every N seconds
- Sample (log 1 in 5)

Not a blocker today, just budget for it.

### 5.4 Streak edge cases
Timezones. If a user reads at 11:55 PM in Tokyo and 12:05 AM in NYC the same day boundary, do they get one streak day or two? **Decision needed**: use the user's timezone (stored on UserProfile?) or always UTC. Recommend: store user timezone (already a settings hook), bucket streak days in user-local time.

### 5.5 Vibe/Theme/Category naming in DB
Should we **rename** the underlying DB tables (`Tone` → `Category`, `ContextTag` → `Theme`) or only **alias** at serializer/admin layer? Aliasing is faster (no migration); renaming is cleaner long-term. Recommend: alias-only for now, schedule a rename for a quiet window.

### 5.6 Mystery Box — what if user has no vibes?
User skipped onboarding, has 0 vibes. Roll falls back to global trending? Random? Forced to onboard first? **Decision needed**.

### 5.7 Anti-joke and observational format storage
- Anti-joke: design renders setup+punchline but with "* That's it. That's the joke." footer. Currently storable as `format=anti` + setup + punchline. ✓
- Observational: rendered as italic quote with serif. Storable as `format=observ` + `text`. ✓
- Story: long text, has reading time. Add `read_time_seconds` field to `Joke` for stories? Or compute from word count?

### 5.8 The "Test on a friend · Did it land?" feature
Today screen has a card to share + report whether the friend laughed/lied. New model `ShareOutcome`? Or piggyback on existing `ShareEvent` with a follow-up reaction? **Defer** — interesting product feature, not core to the pivot.

---

## 6. Decisions made (2026-05-09)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Categorization renames are alias-only** at serializer + admin layer; underlying DB tables (`Tone`, `ContextTag`) keep their names | Fastest path to unblock frontend; no migration window needed; can revisit a true rename later in a quiet release |
| 2 | **Reactions are additive** — `JokeReaction` ships alongside `JokeRating`; no destructive migration | Preserves all historical rating data; both tables can coexist indefinitely; frontend will use `JokeReaction` going forward |
| 3 | **Phases are vertical slices** — each phase ships a complete user-facing loop QA can validate end-to-end | Allows parallel construction of next phase while current phase is being validated; closer to how product ships |

These decisions are baked into §4 above — the dependency graph and the per-phase scope reflect them.

**Next concrete step**: Phase 1 (½ day, serializer aliases + admin labels + OpenAPI refresh). Unblocks frontend's onboarding work and every other phase.

---

## Appendix: Source mapping

For audit, here are the design files where each concept came from:

| Concept | File | Lines |
|---|---|---|
| 12 Vibes (data) | `parts/flow.jsx` | 26-39 |
| 6 Formats (data) | `parts/flow.jsx` | 41-48 |
| 12 Themes (data) | `parts/flow.jsx` | 51-56 |
| 8 Categories (data) | `parts/flow.jsx` | 58-62 |
| Streak grid + chip | `parts/flow-screens.jsx` | 411-425 (Today) |
| Mystery Box card | `parts/flow-screens.jsx` | 427-433 (Today) |
| Notification ritual | `parts/flow-screens.jsx` | 264-321 (OnbRitual) |
| Hooked framework | `parts/analysis-4.jsx` | 62-110 |
| Streak forgiveness | `parts/analysis-4.jsx` | 100-106 ("freeze days") |
| 4-emoji reactions | `parts/screens-4.jsx` | 36-43 (Joke Detail) |
| "Why you got this one" | `parts/screens-4.jsx` | 47-51 |
| Issue numbering | `parts/flow-screens.jsx` | 361 ("Vol. I · No. 042") |
| 7-day archive | `parts/flow-screens.jsx` | 469-497 |
| Top Jokesters leaderboard | `parts/flow-screens.jsx` | 510-543 |
| Weekly Special pack | `parts/flow-screens.jsx` | 545-568 |
| Taste profile (numbers) | `parts/flow-screens.jsx` | 572-588 |
| Top themes pill cloud | `parts/flow-screens.jsx` | 590-612 |
| Search sentence builder | `parts/flow-screens.jsx` | 855-895 |
| Tomorrow teaser | `parts/flow-screens.jsx` | 435-440 |
| Three-axis filter rails | `parts/flow-screens.jsx` | 695-727 (Explore) |
| Continue mid-sip | `parts/flow-screens.jsx` | 444-455 |
| Knock-knock dialogue | `parts/flow.jsx` | 74 (`lines` array) |
