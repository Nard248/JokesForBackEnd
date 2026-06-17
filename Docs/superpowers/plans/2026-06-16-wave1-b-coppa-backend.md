# Wave 1B — COPPA: DOB Age Gate + content_tier Serving Lock (backend)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes. Wave 1 (launch-gating compliance); decisions CD1-CD6 locked in 2026-06-16-wave1-decisions-and-user-action-items.md.

---
## Work-Stream B: COPPA age gate (DOB on UserProfile, block under-13) + content_tier serving lock at all read paths

**Goal:** Add a neutral date_of_birth to UserProfile collected at registration that blocks under-13s with the exact contract error, and enforce a single fail-safe allowed_tiers(request) resolver at EVERY joke read path so anon/minors/null-DOB users only ever receive tier_1, adults only get tier_2 if they explicitly opted into mature content, and tier_3 is never served to anyone via the API. Full TDD, against local Postgres.

**Architecture:** Two independent-but-related concerns, both fail-safe to tier_1.

CONCERN 1 — AGE (CD2): date_of_birth is a nullable DateField on the EXISTING jokes.UserProfile (OneToOne on default auth.User; AUTH_USER_MODEL is NOT swapped). show_mature is a new BooleanField(default=False) on jokes.UserPreference. Age helpers (age, is_adult [18+], is_minor) live on UserProfile and compute from DOB; null DOB => treated as non-adult (is_adult False, is_minor True) so OAuth/legacy users fail safe to tier_1. Registration is the ONLY DOB collection point: EmailOnlyRegisterSerializer gains a required date_of_birth field, validates it's a real non-future date, blocks <13 with the EXACT contract error, and persists DOB onto the signal-created UserProfile after user.save(). Google OAuth (SocialLoginView) never touches this serializer, so OAuth users keep null DOB and are treated as non-adult — exactly the desired fail-safe.

CONCERN 2 — SERVING LOCK (CD3): a single new module jokes/serving.py exposes allowed_tiers(request) -> frozenset. Rule: start from {tier_1}; if request.user is authenticated AND user.profile.is_adult AND user.preference.show_mature is True, add tier_2. tier_3 is NEVER added. Any error/missing profile/preference falls through to {tier_1} (fail safe). This frozenset is then applied as .filter(content_tier__in=allowed) at EVERY joke read path. JokeManager.search() gets an optional allowed_tiers kwarg threaded from each caller (it's reused by both JokeViewSet.list and SavedJokeViewSet.search). View-layer paths (random, trending, daily anon pick, daily personalized via get_personalized_joke, daily lazy via _select_daily_joke_for, Mystery Box via _mystery_pool_for_user) each filter by the resolved set. Because content_tier defaults to tier_1 and existing seed data is tier_1, the lock is backward-compatible for the common path while closing tier_2/tier_3 leakage.

Why a frozenset + single resolver: one auditable choke-point; every read path calls the same function; default-deny (only tier_1 unless explicitly proven adult+opted-in). content_tier is already an indexed CharField on Joke, so .filter(content_tier__in=...) is cheap.

**Tech Stack:** Django 5.2 + DRF, allauth/dj-rest-auth registration, Postgres (local test DB jokesfor via postgres/6969@localhost). Django test runner (NO pytest) with --keepdb. Reference/lookup data (Format, AgeRating, Language, Tone, ContextTag) is seeded by existing migrations and available in tests.

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/models.py` | Add date_of_birth nullable DateField to UserProfile (~after L451 share_analytics / before theme) plus age/is_adult/is_minor helper methods on UserProfile (~L464). Add show_mature BooleanField(default=False) to UserPreference (~after L257 onboarding_completed). |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/migrations/0023_userprofile_dob_userpreference_show_mature.py` | AddField migrations: UserProfile.date_of_birth (DateField null=True blank=True) and UserPreference.show_mature (BooleanField default=False). Generated via makemigrations; both nullable/defaulted so safe on existing rows. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/serializers.py` | Extend EmailOnlyRegisterSerializer: add required date_of_birth = serializers.DateField(); add validate_date_of_birth (reject future/today-or-later as not a real past DOB, compute age, raise EXACT under-13 error keyed on 'date_of_birth'); persist DOB onto user.profile in save() after user.save() (profile exists via post_save signal); include date_of_birth in get_cleaned_data. |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/serving.py` | New single source of truth: allowed_tiers(request) -> frozenset({'tier_1'[,'tier_2']}). Default-deny to {tier_1}; add tier_2 only for authenticated adult (profile.is_adult) with preference.show_mature True. Never tier_3. Wrap profile/preference access defensively (fail safe to {tier_1}). |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/managers.py` | Add optional allowed_tiers param to JokeManager.search(); when provided, qs = qs.filter(content_tier__in=allowed_tiers) applied early (before/with other filters). |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/views.py` | Apply tier lock at all view-layer read paths: JokeViewSet.get_queryset filters by allowed_tiers(request) (covers list non-search, retrieve, rate/react base get_object); JokeViewSet.list passes allowed_tiers into Joke.objects.search(); JokeViewSet.random filters before order_by('?'); JokeViewSet.trending filters; DailyJokeViewSet.today anon editorial pick filters; SavedJokeViewSet.search passes allowed_tiers into Joke.objects.search() and also re-filters saved set by joke content_tier; _mystery_pool_for_user and _select_daily_joke_for accept/apply allowed tiers (thread request or tier set). |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/recommendations.py` | get_personalized_joke gains allowed_tiers param (default frozenset({'tier_1'}) for fail-safe); base_queryset = Joke.objects.exclude(...).filter(content_tier__in=allowed_tiers). Callers in views (DailyJokeViewSet.today/tomorrow) pass allowed_tiers(request). |
| create | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_compliance.py` | New test module (TDD): registration age gate (under-13 exact error, 13+ accepted+DOB stored, future/invalid DOB rejected, missing DOB rejected); allowed_tiers resolver matrix (anon, minor, null-DOB, adult-no-optin, adult-optin -> never tier_3); per-endpoint serving exclusion (list, search, random, trending, daily today anon+auth, recommendations, mystery box) excludes tier_2/tier_3 for anon+minor, includes tier_2 only for opted-in adult, tier_3 never returned to anyone. |

### Task 1: Task 1 — Models + migration: DOB on UserProfile, show_mature on UserPreference, age helpers

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/models.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/migrations/0023_userprofile_dob_userpreference_show_mature.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_compliance.py`

- [ ] **Step 1 (test): Create jokes/tests_compliance.py with UserProfileAgeHelperTests(TestCase). Create a user (User.objects.create_user) — signal auto-creates profile. Set profile.date_of_birth using date math (date(today.year-N, today.month, today.day)) and assert: DOB age 12 -> is_adult False, is_minor True, age 12; DOB age 13 -> is_minor True (13<18), is_adult False; DOB age 18 -> is_adult True, is_minor False; date_of_birth None -> is_adult False, is_minor True, age None. Also assert UserPreference.show_mature defaults to False on the auto-created preference.**

- [ ] **Step 2 (impl): In jokes/models.py UserProfile, add field after share_analytics (L451): date_of_birth = models.DateField(null=True, blank=True, help_text='Neutral DOB for age gating (COPPA). Null = treated as non-adult.'). Add properties on UserProfile: age (None if no DOB else floor years between DOB and timezone.now().date(), accounting for month/day), is_adult (age is not None and age >= 18), is_minor (not is_adult). Import django.utils.timezone if not already imported.**

- [ ] **Step 3 (impl): In jokes/models.py UserPreference, add after onboarding_completed (L257): show_mature = models.BooleanField(default=False, help_text='Adult opt-in to mature (tier_2) content. Default off. Only honored for 18+ users.').**

- [ ] **Step 4 (run): Generate migration via makemigrations jokes; rename to 0023_userprofile_dob_userpreference_show_mature.py if needed and verify dependency points at 0022.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py makemigrations jokes
```

  - Expected: Creates 0023_* with two AddField operations (UserProfile.date_of_birth, UserPreference.show_mature).

- [ ] **Step 5 (run): Run the helper tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes.tests_compliance.UserProfileAgeHelperTests --keepdb
```

  - Expected: All age-helper + show_mature-default tests pass.

- [ ] **Step 6 (commit): Commit: 'Add date_of_birth to UserProfile and show_mature to UserPreference with age helpers'. Plain message, NO Co-Authored-By / generated-with footer.**

### Task 2: Task 2 — Registration age gate (block under-13, store DOB)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/JokesForProject/serializers.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_compliance.py`

- [ ] **Step 1 (test): Add RegistrationAgeGateTests(APITestCase). POST to the register endpoint (resolve via reverse('rest_register') after inspecting JokesForProject/urls.py for the dj-rest-auth register path). Use @override_settings(EMAIL_VERIFICATION_REQUIRED=False) so a user row is created synchronously and assertable. Cases: (a) DOB age 12 -> HTTP 400 and response.json()['date_of_birth'] == ['You must be at least 13 years old to use Jokes For.']; (b) DOB age 20 -> created, User exists and user.profile.date_of_birth equals submitted date; (c) future DOB -> 400 with a date_of_birth error; (d) missing date_of_birth -> 400 with required error on date_of_birth; (e) DOB exactly age 13 today -> succeeds (boundary).**

- [ ] **Step 2 (impl): In JokesForProject/serializers.py EmailOnlyRegisterSerializer: add date_of_birth = serializers.DateField(required=True, write_only=True). Add validate_date_of_birth(self, value): if value >= timezone.now().date(): raise ValidationError('Enter a valid date of birth.'); compute age = years between value and today; if age < 13: raise ValidationError('You must be at least 13 years old to use Jokes For.') (DRF wraps the string into a list under the 'date_of_birth' key). Return value.**

- [ ] **Step 3 (impl): In EmailOnlyRegisterSerializer.get_cleaned_data add 'date_of_birth': self.validated_data.get('date_of_birth'). In save(request) after user.save(): profile = user.profile; profile.date_of_birth = self.cleaned_data['date_of_birth']; profile.save(update_fields=['date_of_birth','updated_at']). (post_save signal already created the profile.)**

- [ ] **Step 4 (run): Run the registration age-gate tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes.tests_compliance.RegistrationAgeGateTests --keepdb
```

  - Expected: All pass; under-13 returns exactly {'date_of_birth': ['You must be at least 13 years old to use Jokes For.']}.

- [ ] **Step 5 (run): Regression on registration-related suites; update payloads to include a valid adult date_of_birth where missing.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test notifications.tests.test_registration_flow notifications.tests.test_google_exemption notifications.tests.test_verify_resend --keepdb
```

  - Expected: Green after adding date_of_birth to any register POST payloads. Google exemption stays green untouched (no serializer involvement).

- [ ] **Step 6 (note): Requiring date_of_birth is an intentional contract change: existing register POSTs without it now 400. Update notifications registration test payloads (e.g. add '2000-01-01') and note the change in the commit body.**

- [ ] **Step 7 (commit): Commit: 'Gate registration on age: require date_of_birth, block under-13, store DOB on profile'. Plain message.**

### Task 3: Task 3 — allowed_tiers resolver (single choke-point, fail-safe)

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/serving.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_compliance.py`

- [ ] **Step 1 (test): Add AllowedTiersResolverTests(TestCase) using RequestFactory to build requests with request.user set. Assert allowed_tiers returns: anonymous (AnonymousUser) -> frozenset({'tier_1'}); minor (profile age 15) -> {'tier_1'}; null-DOB user -> {'tier_1'}; adult with show_mature=False -> {'tier_1'}; adult with show_mature=True -> {'tier_1','tier_2'}; tier_3 never present in any case. Also assert no raise when profile/preference are missing (delete them, expect {'tier_1'}).**

- [ ] **Step 2 (impl): Create jokes/serving.py: TIER_1='tier_1', TIER_2='tier_2', BASE_TIERS=frozenset({TIER_1}). def allowed_tiers(request): user=getattr(request,'user',None); if not (user and user.is_authenticated): return BASE_TIERS; try: profile=user.profile; pref=user.preference except (AttributeError, ObjectDoesNotExist): return BASE_TIERS; if profile.is_adult and getattr(pref,'show_mature',False): return frozenset({TIER_1, TIER_2}); return BASE_TIERS. Import ObjectDoesNotExist from django.core.exceptions. tier_3 intentionally never referenced.**

- [ ] **Step 3 (run): Run the resolver matrix tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes.tests_compliance.AllowedTiersResolverTests --keepdb
```

  - Expected: All resolver matrix tests pass.

- [ ] **Step 4 (commit): Commit: 'Add allowed_tiers serving resolver (fail-safe to tier_1)'. Plain message.**

### Task 4: Task 4 — Apply tier lock at every joke read path

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/managers.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/views.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/recommendations.py`, `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_compliance.py`

- [ ] **Step 1 (test): Add ServingLockTests(APITestCase). setUpTestData: get seeded Format.objects.first(), AgeRating.objects.first(), Language.objects.get(code='en'); patch Joke._generate_share_image (mock) to skip PNG gen; create joke_t1 (content_tier='tier_1'), joke_t2 ('tier_2'), joke_t3 ('tier_3'), each with a shared searchable word in text. Create users: minor (profile age 15), adult_noopt (age 25, show_mature False), adult_opt (age 25, show_mature True). Add a helper to collect returned joke ids from list/paginated responses.**

- [ ] **Step 2 (test): Per-endpoint assertions. For anon + minor + adult_noopt: GET /api/v1/jokes/ (list), GET /api/v1/jokes/?q=<shared word> (search), GET /api/v1/jokes/random/ (assert returned tier in allowed), GET /api/v1/jokes/trending/, GET /api/v1/daily-jokes/today/ -> returned ids/tiers subset of {tier_1}; tier_2/tier_3 ids never appear. For adult_opt: list/search include tier_2 id, exclude tier_3. For ALL: tier_3 NEVER returned. Authenticated daily personalized: force-login each user, hit /daily-jokes/today/, assert only allowed tiers. Mystery Box (/mystery-box/roll/) for minor: never returns tier_2/tier_3. Use force_authenticate/force_login.**

- [ ] **Step 3 (impl): managers.py: search(self, query_text=None, filters=None, ordering=None, allowed_tiers=None); after qs=self.get_queryset(): if allowed_tiers is not None: qs = qs.filter(content_tier__in=allowed_tiers). Keep trailing .distinct().**

- [ ] **Step 4 (impl): views.py: from .serving import allowed_tiers. JokeViewSet.get_queryset -> ...filter(content_tier__in=allowed_tiers(self.request)). JokeViewSet.list -> pass allowed_tiers=allowed_tiers(request) into Joke.objects.search(...). JokeViewSet.random -> Joke.objects.filter(content_tier__in=allowed_tiers(request)).order_by('?').first(). JokeViewSet.trending -> add .filter(content_tier__in=allowed_tiers(request)). DailyJokeViewSet.today anon branch -> add .filter(content_tier__in=allowed_tiers(request)) before order_by('?').**

- [ ] **Step 5 (impl): views.py authenticated/mystery paths: DailyJokeViewSet.today/tomorrow personalized fallback -> get_personalized_joke(request.user, exclude_joke_ids=..., allowed_tiers=allowed_tiers(request)). _mystery_pool_for_user(user, allowed) -> add allowed param, pool=pool.filter(content_tier__in=allowed) before return; also filter the GLOBAL fallback Joke.objects.all(). MysteryBoxRollView.post -> pass allowed_tiers(request). _select_daily_joke_for(user, target_date, allowed=frozenset({'tier_1'})) -> filter both vibe pool and the global Joke.objects.order_by('?') fallback by allowed; thread allowed_tiers(request) from callers. SavedJokeViewSet.search -> pass allowed_tiers=allowed_tiers(request) into search() and add .filter(joke__content_tier__in=allowed_tiers(request)) on saved set.**

- [ ] **Step 6 (impl): recommendations.py: get_personalized_joke(user, exclude_joke_ids=None, allowed_tiers=frozenset({'tier_1'})): base_queryset = Joke.objects.exclude(id__in=exclude_ids).filter(content_tier__in=allowed_tiers). Default frozenset({'tier_1'}) keeps it fail-safe if a caller omits tiers.**

- [ ] **Step 7 (run): Run the serving lock tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes.tests_compliance.ServingLockTests --keepdb
```

  - Expected: All per-endpoint exclusion tests pass; tier_2 only for opted-in adult; tier_3 never returned anywhere.

- [ ] **Step 8 (commit): Commit: 'Lock joke serving to content tiers at all read paths (anon/minors get tier_1 only; tier_3 never served)'. Plain message.**

### Task 5: Task 5 — Full regression + final verification

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests_compliance.py`

- [ ] **Step 1 (run): Run the full jokes + notifications + project suites to confirm no regression.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes notifications JokesForProject --keepdb
```

  - Expected: Green. Local-DB env vars force local Postgres per project convention; any Neon failure would be environmental, not from this change.

- [ ] **Step 2 (note): Manual audit: grep for remaining Joke.objects.order_by('?') / Joke.objects.all() / .none() pool builders that feed a serializer response and confirm each is tier-filtered (random, trending, daily-anon, daily-personalized, mystery-box, _select_daily_joke_for global fallback, saved-search). Confirm JokeSerializer still does NOT expose content_tier. Confirm tier_3 appears in zero served responses across the new tests.**

- [ ] **Step 3 (commit): If audit fixups were needed, commit them: 'Tighten remaining joke serving paths for tier lock'. Otherwise no-op.**

**Decisions in this plan:**

- *Where to compute/store age and the adult flag?* → Store date_of_birth on jokes.UserProfile (per CD2; do NOT swap AUTH_USER_MODEL) and compute age/is_adult(>=18)/is_minor as Python properties from DOB. Null DOB (OAuth/legacy) => is_adult False / is_minor True, so those users fail safe to tier_1. Mature opt-in is show_mature on UserPreference (default False).
- *How to apply the tier rule consistently without scattering logic?* → One module jokes/serving.py with allowed_tiers(request)->frozenset, default-deny to {tier_1}, adds tier_2 only for authenticated adult+show_mature, never tier_3. Every read path calls it and applies .filter(content_tier__in=allowed). JokeManager.search() takes an optional allowed_tiers kwarg threaded from each view so the same code serves list and saved-search.
- *Should JokeManager.search() default to filtering tier_1 when no tiers are passed?* → No hard default in the manager (allowed_tiers=None => no tier filter) to avoid silently hiding tier_2 from internal/admin/non-request callers; but EVERY request-driven caller MUST pass allowed_tiers(request). For get_personalized_joke, default the param to frozenset({'tier_1'}) since it is only ever called in a serving context — belt-and-suspenders fail-safe.
- *Under-13 boundary and invalid dates — exact behavior?* → Block age < 13 with the EXACT contract error {'date_of_birth': ['You must be at least 13 years old to use Jokes For.']}. age == 13 succeeds. Future/today-or-later DOB is rejected as invalid ('Enter a valid date of birth.'). Missing field => DRF required error on date_of_birth. 13+ proceeds through the UNCHANGED gated email-verification flow.
- *Does requiring DOB break Google OAuth or existing registration tests?* → Google OAuth uses SocialLoginView and never invokes EmailOnlyRegisterSerializer, so OAuth users keep null DOB (treated non-adult, tier_1) — confirmed by the existing exemption test which stays untouched. Existing notifications registration tests that POST without date_of_birth WILL now 400; those payloads must be updated to include a valid adult DOB. This is an intentional, documented API contract change.

**Risks:**

- Adding required date_of_birth to registration is a breaking contract change: any existing test or frontend caller that registers without it now gets 400. Mitigation: Task 2 updates the notifications registration tests; the cross-agent contract already specifies the field so the frontend agent is aligned.
- Missed read path = compliance leak. The audit step (Task 5) must confirm every Joke.objects.order_by('?')/all()/none() pool that reaches a serializer is tier-filtered (random, trending, daily-anon, daily-personalized, mystery-box, _select_daily_joke_for global fallback, saved-search). Fail-safe defaults reduce blast radius but do not replace the audit.
- _mystery_pool_for_user and _select_daily_joke_for have GLOBAL fallbacks (Joke.objects.all() / order_by('?')) that must ALSO be tier-filtered, not just the vibe pool — easy to miss and would leak tier_2/tier_3 to minors via daily/mystery.
- Null-DOB-as-minor means legacy/OAuth users only ever see tier_1 until they set a DOB. There is currently no endpoint to set DOB post-registration; acceptable for a text-only MVP and the fail-safe direction, but note it as a known limitation (out of scope per YAGNI).
- JokeSerializer must continue to NOT expose content_tier; if any future serializer adds it, clients could infer hidden tiers. Verified currently absent; keep it absent.
- Age computed with naive today=timezone.now().date(); timezone-edge (user born today in another TZ) is negligible for a 13/18 gate. Acceptable.
