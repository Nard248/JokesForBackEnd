# MVP 0.2 Slice 2 — Follow + Joke.creator + Creator Profiles (Design)

# MVP 0.2 — Slice 2 Design: Joke.creator FK + Follow Engine + Creator Profiles

## 0. Context & grounding

Today creators are resolved **only** through the chain `Joke → submission (OneToOne reverse) → JokeSubmission.user`. The whole codebase funnels that join through ONE function, `creator_insights/services.py :: resolve_creator_jokes(creator)`, which is the deliberate swap point left by Slice 1. Publishing happens in exactly one place: `jokes/admin.py :: JokeSubmissionAdmin.approve_and_publish` (creates the `Joke`, then sets `submission.published_joke` + `status='published'`). There is no public-creator surface yet, and the content-tier gate (`jokes/serving.py :: allowed_tiers`) is intentionally bypassed for owner-scoped insights — any *public* creator surface MUST re-apply it.

`creator_insights/models.py` already documents the intent: `CreatorFollow(follower, creator, created_at)`. The task asks for a **new follow app**, so this design ships a dedicated `follows` app and leaves the `creator_insights/models.py` docstring as a pointer (openDecision flags the fold-in alternative).

Single Cloud Run app, Neon Postgres, **no workers/cron** — every count is computed on-read via aggregate queries. Migration must be safe on the live `jokes` table (nullable + indexed add, backfill in a *separate* data migration). Commit messages plain (no footers). YAGNI: ship the narrowest demoable slice.

---

## 1. Joke.creator FK (real attribution)

### 1.1 Model change (`jokes/models.py`)
Add to `Joke`:
```python
creator = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='created_jokes',
    db_index=True,
    help_text='Attributed creator, stamped at publish time. Null = legacy/seed/curated.',
)
```
- **`null=True`** — non-blocking `ADD COLUMN` on the live table (Postgres adds a nullable column without a table rewrite; no default value scan).
- **`on_delete=SET_NULL`** — a deleted user does not cascade-delete published jokes (content survives; attribution drops). Matches `ShareEvent.user`/`Source` conventions already in the model.
- **`db_index=True`** — `resolve_creator_jokes` and the profile endpoint filter on `creator`; index is required for both.
- **`related_name='created_jokes'`** — distinct from submission's `joke_submissions` and from `JokePack` `created_by` (`+`).

### 1.2 Schema migration (auto, `jokes/00XX_joke_creator_fk.py`)
Single `AddField` (nullable + indexed). Safe: `ADD COLUMN ... NULL` + `CREATE INDEX` (Django emits `CREATE INDEX`, not `CONCURRENTLY`; acceptable at current table size — flagged in openDecisions for scale).

### 1.3 Data migration (separate, `jokes/00XX_backfill_joke_creator.py`)
`migrations.RunPython(forward, reverse)`:
- **forward**: iterate published submissions with an attached joke and stamp the FK — `JokeSubmission.objects.filter(status='published', published_joke__isnull=False).select_related('published_joke')` then `Joke.objects.filter(pk=..).update(creator_id=submission.user_id)`. Use `.iterator()` + batched `update()` (or `bulk_update`) so it streams rather than loading all rows. Idempotent: only stamps rows where `creator_id` is currently NULL (`...published_joke__creator__isnull=True`).
- **reverse**: `Joke.objects.update(creator=None)` (or no-op) — keeps `migrate jokes 00XX-1` runnable.
- Uses the historical model via `apps.get_model('jokes', 'Joke')` / `'JokeSubmission')` — never imports the live model.
- **Migration safety**: backfill is data-only (no schema lock); separate file means the schema add can deploy/rollback independently of the backfill. On Cloud Run the migration runs in the release step (GH Actions `migrate` job) before traffic shifts.

### 1.4 Stamp at publish (`jokes/admin.py`)
In `approve_and_publish`, pass `creator=submission.user` into `Joke.objects.create(...)`. This makes the FK authoritative for all *new* publishes; the backfill covers history. (If a future API publish path is added it stamps the same way — single new keyword.)

### 1.5 Swap `resolve_creator_jokes` (`creator_insights/services.py`)
The one-line swap the comment promised, made **safe for un-backfilled / null-creator rows** via a fallback:
```python
def resolve_creator_jokes(creator):
    return Joke.objects.filter(
        Q(creator=creator) |
        Q(creator__isnull=True, submission__user=creator, submission__status='published')
    ).distinct()
```
- Primary path: direct `creator` FK (fast, indexed).
- Fallback `OR` branch: any joke not yet stamped but attributable via the old submission join — guarantees **zero regression** in insights even before the backfill lands or for edge rows. `.distinct()` guards the M2M-free but OR-joined query.
- Once backfill + publish-stamping are fully in place the fallback becomes dead weight but is harmless; removal is a later cleanup (openDecision).
- All existing `creator_insights` tests must still pass unchanged (they build submissions, not FKs) — proving the fallback works.

---

## 2. Follow / Subscribe engine (social follow — NOT paid subscription)

New Django app **`follows`** (added to `INSTALLED_APPS` after `creator_insights`).

### 2.1 Model (`follows/models.py`)
```python
class Follow(models.Model):
    follower = models.ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE, related_name='following')
    creator  = models.ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [['follower', 'creator']]
        indexes = [models.Index(fields=['creator', 'created_at']),  # follower lists + growth-over-time
                   models.Index(fields=['follower', 'created_at'])]  # following lists
```
- `unique_together(follower, creator)` — one edge, idempotent follow.
- `creator + created_at` index powers follower-count, follower list, and the **follower-growth-over-time** sparkline wired into insights.
- `CASCADE` on both — deleting a user removes their edges (social graph, not content). This differs from `Joke.creator` (SET_NULL) deliberately.
- Self-follow guarded at the **service/serializer layer**, not a DB constraint (clearer 400 message; a CHECK constraint is an openDecision).

### 2.2 Service layer (`follows/services.py`)
Thin pure functions (mirrors `creator_insights/services.py` style, no DRF coupling):
- `follow(follower, creator)` → raises `ValidationError` on self-follow; `get_or_create` the edge; returns `(follow, created)`.
- `unfollow(follower, creator)` → delete edge if present (idempotent).
- `follower_count(creator)` / `following_count(user)` → `.count()` aggregates.
- `is_following(follower, creator)` → `.exists()`.

### 2.3 Endpoints (`follows/views.py`, `follows/urls.py` → mounted at `/api/v1/follows/`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/follows/<creator_id>/` | IsAuthenticated | Follow creator (idempotent 201/200; 400 self-follow; 404 unknown user) |
| DELETE | `/api/v1/follows/<creator_id>/` | IsAuthenticated | Unfollow (idempotent 204) |
| GET | `/api/v1/follows/<creator_id>/status/` | IsAuthenticated | `{is_following, follower_count}` for the button |
| GET | `/api/v1/follows/<creator_id>/followers/` | IsAuthenticated | Paginated follower list + `count` |
| GET | `/api/v1/users/me/following/` | IsAuthenticated | Paginated list of creators I follow + `count` |

- Follow/unfollow/status target a **creator user id**. Lists reuse DRF `PageNumberPagination` (PAGE_SIZE=10) already configured.
- Security: all follow-graph endpoints require auth. Follower/following lists return minimal public identity only (`id`, display name, `@handle` derived from email local-part as `TopJokestersView` does) — **never email**.
- Throttle: default `user` rate (1000/hr) is fine; no dedicated scope needed (YAGNI).
- A `FollowSerializer` documents the edge; lightweight `PublicUserSerializer` (id/name/username/avatar_url) for list rows + reuse in profile.

### 2.4 Self-follow guard
`follow()` raises `serializers.ValidationError("You cannot follow yourself.")` → view returns 400. Covered by an explicit test.

---

## 3. Creator profile pages (public, tier-filtered)

### 3.1 Backend endpoint (`creator_insights` app — public surface, distinct from owner insights)
`GET /api/v1/creators/<creator_id>/profile/` — `permission_classes = [AllowAny]`.

Response shape:
```jsonc
{
  "creator": { "id", "name", "username", "avatar_url", "bio" },
  "follower_count": 128,
  "published_jokes_count": 14,
  "is_following": true,            // false when anon/self
  "is_self": false,
  "jokes": [ <JokeListSerializer rows> ]   // paginated
}
```
- **Tier filtering (critical)**: this is a *public* surface, so it MUST re-apply `allowed_tiers(request)` — the opposite of owner-scoped `resolve_creator_jokes`. Build the joke list as:
  `Joke.objects.filter(creator=creator_user).filter(content_tier__in=allowed_tiers(request)) | (null-creator fallback via submission join, same fallback as §1.5)` then tier-filter, `.distinct()`, ordered `-created_at`, paginated.
  → an anon viewer never sees tier_2; an adult opted-in viewer does. tier_3 never served.
- `is_following` resolved via `follows.services.is_following` only when authenticated and not self.
- `bio` from `UserProfile.bio`; respect `UserProfile.public_profile` — if a creator has `public_profile=False`, return identity + counts but **404 or empty** the joke list? → recommend: still show published jokes (they're public content) but flag in openDecisions.
- Profile identity helper (`name`, `username`) shared with the follow lists via `PublicUserSerializer`.
- 404 if the user id does not exist OR has zero published jokes (not a "creator").

### 3.2 Modular placement
- Public **profile** endpoint lives in `creator_insights` (it's the read/aggregate surface, reuses `resolve_creator_jokes` semantics + `allowed_tiers`). URL: `creator_insights/urls.py` gets `path('<int:creator_id>/profile/', CreatorProfileView.as_view(), name='creator-profile')` — mounted under existing `/api/v1/creators/`.
- Follow **graph** endpoints live in the new `follows` app. Clean separation: `follows` owns the edge + mutations; `creator_insights` owns read/aggregate surfaces and *imports* `follows.services` for counts.

### 3.3 Frontend (`/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`)
- **Route**: `{ path: '/creators/:creatorId', element: <CreatorProfilePage /> }` in `src/app/routes.tsx` — public (no `ProtectedRoute`; Follow button gates on auth at click time).
- **Page**: `src/pages/CreatorProfilePage.tsx` (+ `.test.tsx`) using `FlowAppShell` (mirrors `CreatorInsightsPage`). Renders identity header, follower count, published-jokes count, the jokes grid (reuse existing `JokeCard`/list components), and the `FollowButton`.
- **Feature module**: `src/features/follows/` with `api.ts` (react-query hooks `useCreatorProfile(id)`, `useFollowStatus(id)`, `useFollow()`/`useUnfollow()` mutations with optimistic count update + invalidation), `index.ts`.
- **FollowButton** (`src/features/follows/FollowButton.tsx`): toggles via mutations; optimistic `is_following`/`follower_count`; if unauthenticated, routes to `/login`.
- **Adapter** (`src/lib/api-adapter.ts`): add `followsAdapter` + `creatorProfileAdapter` honoring `USE_MOCKS` (the existing pattern — real path hits `creatorProfileApi`/`followsApi`, mock path hits `mockFollowsApi`).
- **API client** (`src/lib/api.ts`): types `CreatorProfile`, `FollowStatus`, `PublicUser`; `creatorProfileApi.get(id)`, `followsApi.{follow,unfollow,status,following}`.
- **Mocks** (`src/lib/mock-data.ts` + `src/lib/mock-api.ts`): `mockCreatorProfile` fixture + in-memory `mockFollowsApi` (toggles a module-level `Set` of followed ids so the button demos statefully under `USE_MOCKS`).

---

## 4. Wire follower growth into creator_insights

Now that a persistent audience edge exists, extend `build_creator_insights`:
- `creator_insights/services.py` imports `follows.services` (lazy import to avoid app-load ordering issues) and adds to the `overview` block:
  - `followers`: `follower_count(creator)`.
  - `follower_growth_28d`: 28-element daily list of **new follows per day** over the trailing 28 days — `Follow.objects.filter(creator=creator, created_at__date__gte=start).values('created_at__date').annotate(c=Count('id'))` mapped into the same sparkline shape as `daily_reach_28d` (reuses the existing mapping idiom in `_overview`).
- Serializer: add `followers: IntegerField()` and `follower_growth_28d: ListField(IntegerField)` to `OverviewSerializer` in `creator_insights/serializers.py`.
- Frontend `CreatorInsights.overview` type (`src/lib/api.ts`) + `mockCreatorInsights` fixture gain `followers` + `follower_growth_28d`; CreatorInsightsPage renders a follower KPI/sparkline (small additive UI).

---

## 5. API endpoints summary

| App | Method · Path | Auth | Notes |
|---|---|---|---|
| jokes | (publish stamps `Joke.creator`) | admin | no new endpoint |
| follows | POST `/api/v1/follows/<creator_id>/` | user | follow (idempotent) |
| follows | DELETE `/api/v1/follows/<creator_id>/` | user | unfollow (idempotent) |
| follows | GET `/api/v1/follows/<creator_id>/status/` | user | `{is_following, follower_count}` |
| follows | GET `/api/v1/follows/<creator_id>/followers/` | user | paginated + count |
| follows | GET `/api/v1/users/me/following/` | user | paginated + count |
| creator_insights | GET `/api/v1/creators/<creator_id>/profile/` | public | tier-filtered jokes + counts + is_following |
| creator_insights | GET `/api/v1/creators/me/insights/` | creator | extended with followers + growth |

## 6. Security recap
- Follow graph mutations + lists: **auth required**; lists expose only public identity (id/name/@handle/avatar), never email.
- Self-follow blocked (400) at service layer.
- Public profile: **AllowAny** but joke list **MUST** pass through `allowed_tiers(request)` — anon/minor see tier_1 only; tier_3 never served. This is the explicit inverse of the owner-scoped insights bypass.
- Idempotent follow/unfollow prevents duplicate-edge / double-count abuse (DB unique constraint backstops it).
