# Wave 1D — GDPR Export + Safe Account Deletion (backend)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes. Wave 1 (launch-gating compliance); decisions CD1-CD6 locked in 2026-06-16-wave1-decisions-and-user-action-items.md.

---
## Work-Stream D: GDPR Data Export + Safe Account Deletion (CD6)

**Goal:** Replace the two stubs in jokes/views.py with real, in-request (no-worker) GDPR features: (1) DataExportView synchronously assembles ALL of the requesting user's data across every user-owned model into a downloadable zipped-JSON HttpResponse; (2) UserAccountDeleteView performs a confirmed HARD delete inside a transaction — re-auth via password (or typed "DELETE" confirm for OAuth/no-usable-password accounts), purge the avatar from the storage backend, delete EmailMessageLog + EmailVerification rows, blacklist outstanding refresh tokens, then user.delete() (cascade), returning 204. Full TDD, plain commits (no footers), YAGNI scope (text-only MVP — no rich-media/moderation handling).

**Architecture:** Both endpoints already exist and are wired in jokes/urls.py (GET /api/v1/users/me/data-export/ -> DataExportView; DELETE /api/v1/users/me/ -> UserAccountDeleteView), so NO url changes are needed — only the view bodies in jokes/views.py change.

EXPORT (CD6, synchronous, zipped-JSON):
- Build a single dict keyed by section. Sections (all filtered to request.user, excluding other users' PII): account (id/email/username/date_joined/last_login/is_active), profile (UserProfile — bio, avatar name+url, is_premium, privacy flags, theme), preferences (UserPreference incl. M2M preferred_tones/contexts as slugs, notification flags, onboarding), saved_jokes (SavedJoke: joke_id + joke text snapshot + collection name + note), collections (Collection), favorites (Favorite: joke_id+text), ratings (JokeRating), reactions (JokeReaction), daily_jokes (DailyJoke), streak (Streak OneToOne) + streak_days (StreakDay), views (JokeView — recently-viewed history is derived from this; cap/serialize id/joke_id/source/revealed/viewed_at), submissions (JokeSubmission incl. status), reports_filed (ContentReport where reporter=user — include reason/description/status but NOT other reporters), blocks (UserBlock where blocker=user — store blocked_id only, not the blocked user's email/PII), achievements (UserAchievement -> achievement slug+title+unlocked_at), vibes (UserVibe -> vibe slug), pack_progress (JokePackProgress), mystery_rolls (MysteryBoxRoll), share_events (ShareEvent where user=user), and email_logs (notifications.EmailMessageLog where user=user OR to_email==user.email). Add an export_meta block {generated_at, format_version, note}.
- Serialize datetimes/dates via DjangoJSONEncoder. Avoid leaking joke full content where unnecessary, but including the user's saved/favorited joke text is fine (it's public content the user kept). Crucially, for UserBlock and any cross-user FK, emit only the integer id, never the other user's email/username.
- Wrap json.dumps in a zipfile.ZipFile (in BytesIO) writing one entry "jokes-for-data-export.json"; return HttpResponse(buf, content_type="application/zip") with Content-Disposition: attachment; filename="jokes-for-data-export.zip". (Single .zip per CD6 "zipped-JSON".) Permission IsAuthenticated; GET only.

DELETE (CD6, re-auth + purge + transaction):
- Re-auth gate BEFORE any mutation: if user.has_usable_password() -> require body {"password": ...}; reject missing/blank with 400 {"password": ["This field is required."]} and wrong with 400 {"password": ["Incorrect password."]} using user.check_password(...). If NOT has_usable_password() (Google OAuth / unusable) -> require body {"confirm": "DELETE"} exactly; missing/mismatch -> 400 {"confirm": ["Type DELETE to confirm account deletion."]}.
- On success, inside transaction.atomic(): (a) if profile.avatar present, capture its .name then profile.avatar.delete(save=False) (calls the configured STORAGES['default'] backend — FileSystemStorage in tests, GCS in prod) wrapped in try/except so a missing/already-gone file can't break deletion (idempotent/safe); (b) EmailMessageLog.objects.filter(Q(user=user)|Q(to_email__iexact=user.email)).delete() and EmailVerification.objects.filter(user=user).delete() — EmailVerification would cascade anyway but delete explicitly for clarity/idempotency; (c) if 'rest_framework_simplejwt.token_blacklist' in settings.INSTALLED_APPS: for ot in OutstandingToken.objects.filter(user=user): BlacklistedToken.objects.get_or_create(token=ot) (guard import inside the branch so a disabled blacklist app degrades gracefully); (d) user.delete() — FK cascades remove SavedJoke/Collection/Favorite/JokeRating/JokeReaction/DailyJoke/JokeView/Streak/StreakDay/Submission/ContentReport(reporter)/UserBlock(blocker+blocked)/UserProfile/UserPreference/UserVibe/JokePackProgress/MysteryBoxRoll/ShareEvent(SET_NULL)/UserAchievement. Return 204.
- Note: OutstandingToken.user is on_delete=SET_NULL, so blacklisting must happen BEFORE user.delete() (after delete the rows still exist but user_id is null — order matters). BlacklistedToken rows persist post-delete (token FK to OutstandingToken, not user) which is the desired audit/no-reuse behavior.

No new models, no migrations, no Celery, no new URLs. Everything request-triggered in the single Cloud Run app.

**Tech Stack:** Django 5.2 + DRF, rest_framework_simplejwt (+ token_blacklist app already in INSTALLED_APPS), dj-rest-auth/allauth (default auth.User, email-as-username), django-storages GCS in prod / FileSystemStorage in tests. Python stdlib json/zipfile/io. Tests via Django runner (NO pytest) against LOCAL Postgres with --keepdb.

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/views.py` | Replace the DataExportView body (~L1629) with a synchronous zipped-JSON export across all user-owned models; replace UserAccountDeleteView body (~L1618) with re-auth (password or typed DELETE for no-usable-password accounts) + transactional purge (avatar file, EmailMessageLog/EmailVerification, refresh-token blacklist) + cascade user.delete(). Add imports: io, json, zipfile; django.http.HttpResponse; django.core.serializers.json.DjangoJSONEncoder; django.db.models.Q (already imported); notifications.models EmailMessageLog/EmailVerification; ShareEvent/UserAchievement/StreakDay already importable from .models. |
| edit | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests.py` | Add two APITestCase classes: DataExportTests and AccountDeleteTests, seeding a user with rows across the listed models plus a SECOND user with their own rows to assert no cross-user leakage. Reuse the existing Format/AgeRating/Language seed-data lookup pattern from SubmissionApiTests.setUpTestData. |
| none | `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/urls.py` | Already wires both endpoints (L70-71). No change. |

### Task 1: Task 1 — Write failing tests for DataExportView

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests.py`

- [ ] **Step 1 (note): Read the existing SubmissionApiTests.setUpTestData (jokes/tests.py L130-145) to copy how it fetches seeded Format('oneliner'/'setup'), AgeRating.first(), Language('en'). The test DB has lookup seed data from migrations.**

- [ ] **Step 2 (test): Add class DataExportTests(APITestCase). In setUpTestData create user_a (creator@... already taken by another class but each class gets its own DB rows within its transaction; use a distinct email like exporter@example.com) and user_b (other@example.com). Create one published Joke (Joke.objects.create with format/age_rating/language FKs + set required M2M after). Seed for user_a across models so every export section is non-empty.**

```
from jokes.models import (Joke, Collection, SavedJoke, Favorite, JokeRating, JokeReaction, DailyJoke, JokeView, Streak, StreakDay, JokeSubmission, ContentReport, UserBlock, UserPreference, UserProfile, UserVibe, Vibe, MysteryBoxRoll, ShareEvent, Achievement, UserAchievement, JokePack, JokePackProgress)
from notifications.models import EmailMessageLog, EmailVerification
import io, zipfile, json
from datetime import date, timedelta
from django.utils import timezone

class DataExportTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='exporter@example.com', email='exporter@example.com', password='pw12345!')
        cls.other = User.objects.create_user(username='other@example.com', email='other@example.com', password='pw12345!')
        fmt = Format.objects.get(slug='oneliner'); age = AgeRating.objects.first(); lang = Language.objects.get(code='en')
        cls.joke = Joke.objects.create(text='My export joke', format=fmt, age_rating=age, language=lang)
        col = Collection.objects.create(user=cls.user, name='Mine')
        SavedJoke.objects.create(user=cls.user, joke=cls.joke, collection=col, note='keep')
        Favorite.objects.create(user=cls.user, joke=cls.joke)
        JokeRating.objects.create(user=cls.user, joke=cls.joke, rating=JokeRating.LIKE)
        JokeReaction.objects.create(user=cls.user, joke=cls.joke, reaction=JokeReaction.REACTION_LOL)
        DailyJoke.objects.create(user=cls.user, joke=cls.joke, date=date.today())
        JokeView.objects.create(user=cls.user, joke=cls.joke, source=JokeView.SOURCE_DAILY)
        EmailMessageLog.objects.create(user=cls.user, to_email=cls.user.email, template_name='welcome', subject='Hi', status='sent')
        ContentReport.objects.create(reporter=cls.user, joke=cls.joke, reason='spam')
        UserBlock.objects.create(blocker=cls.user, blocked=cls.other)
        # other user's data that must NOT leak
        Favorite.objects.create(user=cls.other, joke=cls.joke)
        EmailMessageLog.objects.create(user=cls.other, to_email=cls.other.email, template_name='welcome', subject='Hi', status='sent')
    def setUp(self):
        self.client.force_authenticate(user=self.user)
    def _export(self):
        resp = self.client.get('/api/v1/users/me/data-export/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        self.assertIn('attachment', resp['Content-Disposition'])
        zf = zipfile.ZipFile(io.BytesIO(b''.join(resp.streaming_content) if resp.streaming else resp.content))
        return json.loads(zf.read(zf.namelist()[0]))
```

  - Expected: Tests fail now (current stub returns 202 JSON, not a 200 zip).

- [ ] **Step 3 (test): Add assertions: test_export_headers_and_zip (200 + application/zip + attachment filename .zip); test_export_contains_all_sections (data has keys account/profile/preferences/saved_jokes/collections/favorites/ratings/reactions/daily_jokes/streak/views/submissions/reports_filed/blocks/email_logs and each user_a-owned one is non-empty); test_export_excludes_other_users_data (favorites has exactly 1 row for cls.joke and no row attributable to other; email_logs length == count of user_a logs only; blocks rows contain blocked_id == other.id but NOT other.email anywhere in the JSON via assertNotIn('other@example.com', json.dumps(data))); test_export_requires_auth (force_authenticate(None) -> 401/403).**

  - Expected: All fail (stub).

### Task 2: Task 2 — Implement DataExportView

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/views.py`

- [ ] **Step 1 (impl): Add module imports near the top of jokes/views.py: import io, json, zipfile; from django.http import HttpResponse; from django.core.serializers.json import DjangoJSONEncoder; from notifications.models import EmailMessageLog, EmailVerification. Ensure ShareEvent, UserAchievement, StreakDay are in the existing `from .models import (...)` block (StreakDay & ShareEvent & UserAchievement are defined; add any missing names).**

- [ ] **Step 2 (impl): Replace DataExportView.get to build a dict per the architecture, dumping with DjangoJSONEncoder, zipping into BytesIO, returning HttpResponse(content_type='application/zip') with Content-Disposition attachment. Filter EVERY queryset by request.user; for UserBlock emit blocked_id only; for ContentReport include own reason/description/status only; for email_logs filter Q(user=user)|Q(to_email__iexact=user.email).**

```
def get(self, request):
    u = request.user
    def dt(x):
        return x  # DjangoJSONEncoder handles datetime/date
    data = {
        'export_meta': {'generated_at': timezone.now(), 'format_version': 1,
            'note': 'Full export of your Jokes For data. Other users\' personal data is excluded.'},
        'account': {'id': u.id, 'email': u.email, 'username': u.username,
            'date_joined': u.date_joined, 'last_login': u.last_login, 'is_active': u.is_active},
        'profile': [{ 'bio': p.bio, 'avatar': p.avatar.name or '', 'is_premium': p.is_premium,
            'public_profile': p.public_profile, 'show_activity': p.show_activity,
            'share_analytics': p.share_analytics, 'theme': p.theme, 'created_at': p.created_at}
            for p in UserProfile.objects.filter(user=u)],
        'preferences': [{ 'notification_enabled': pr.notification_enabled,
            'notification_days': pr.notification_days, 'onboarding_completed': pr.onboarding_completed,
            'preferred_tones': list(pr.preferred_tones.values_list('slug', flat=True)),
            'preferred_contexts': list(pr.preferred_contexts.values_list('slug', flat=True))}
            for pr in UserPreference.objects.filter(user=u)],
        'collections': list(Collection.objects.filter(user=u).values('id','name','description','is_public','created_at')),
        'saved_jokes': [{ 'joke_id': s.joke_id, 'joke_text': s.joke.text, 'collection': s.collection.name if s.collection else None, 'note': s.note, 'created_at': s.created_at} for s in SavedJoke.objects.filter(user=u).select_related('joke','collection')],
        'favorites': [{ 'joke_id': f.joke_id, 'joke_text': f.joke.text, 'created_at': f.created_at} for f in Favorite.objects.filter(user=u).select_related('joke')],
        'ratings': list(JokeRating.objects.filter(user=u).values('joke_id','rating','created_at')),
        'reactions': list(JokeReaction.objects.filter(user=u).values('joke_id','reaction','created_at')),
        'daily_jokes': list(DailyJoke.objects.filter(user=u).values('joke_id','date','delivered_at')),
        'views': list(JokeView.objects.filter(user=u).values('joke_id','source','revealed_punchline','viewed_at')[:5000]),
        'streak': list(Streak.objects.filter(user=u).values('current_count','longest_count','last_active_date','freeze_days_available','freezes_used_total')),
        'streak_days': list(StreakDay.objects.filter(user=u).values('date','status')),
        'submissions': list(JokeSubmission.objects.filter(user=u).values('id','text','setup','punchline','status','created_at')),
        'reports_filed': list(ContentReport.objects.filter(reporter=u).values('joke_id','reason','description','status','created_at')),
        'blocks': list(UserBlock.objects.filter(blocker=u).values('blocked_id','created_at')),
        'achievements': list(UserAchievement.objects.filter(user=u).values('achievement__slug','achievement__title','unlocked_at')),
        'vibes': list(UserVibe.objects.filter(user=u).values('vibe__slug','weight','created_at')),
        'pack_progress': list(JokePackProgress.objects.filter(user=u).values('pack__slug','last_read_entry','completed_at')),
        'mystery_rolls': list(MysteryBoxRoll.objects.filter(user=u).values('joke_id','source_vibe__slug','rolled_date')),
        'share_events': list(ShareEvent.objects.filter(user=u).values('joke_id','platform','created_at')),
        'email_logs': list(EmailMessageLog.objects.filter(Q(user=u)|Q(to_email__iexact=u.email)).values('to_email','template_name','subject','status','created_at','sent_at')),
    }
    payload = json.dumps(data, cls=DjangoJSONEncoder, indent=2)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('jokes-for-data-export.json', payload)
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = 'attachment; filename="jokes-for-data-export.zip"'
    return resp
```

  - Expected: Adjust section key names to exactly match what Task 1 asserts.

- [ ] **Step 3 (run): Run only the export tests.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes.tests.DataExportTests --keepdb
```

  - Expected: DataExportTests pass (200 zip, all sections present, no other@example.com leak).

- [ ] **Step 4 (commit): Commit export feature.**

```
git checkout -b wave1-gdpr-export-delete && git add jokes/views.py jokes/tests.py && git commit -m "Add synchronous GDPR data export (zipped JSON)"
```

  - Expected: Plain commit message, no Co-Authored-By/Generated-with footer.

### Task 3: Task 3 — Write failing tests for UserAccountDeleteView

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/tests.py`

- [ ] **Step 1 (test): Add class AccountDeleteTests(APITestCase). Create pw_user (usable password 'pw12345!') and an oauth_user via User.objects.create_user(...) then oauth_user.set_unusable_password(); oauth_user.save(). Seed each with a SavedJoke + EmailMessageLog + EmailVerification so cascade/purge can be asserted.**

```
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from notifications.models import EmailMessageLog, EmailVerification

class AccountDeleteTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pw_user = User.objects.create_user(username='del@example.com', email='del@example.com', password='pw12345!')
        cls.oauth_user = User.objects.create_user(username='g@example.com', email='g@example.com')
        cls.oauth_user.set_unusable_password(); cls.oauth_user.save()
        for usr in (cls.pw_user, cls.oauth_user):
            EmailMessageLog.objects.create(user=usr, to_email=usr.email, template_name='welcome', subject='Hi', status='sent')
            EmailVerification.objects.create(user=usr, code_hash='x', expires_at=timezone.now()+timedelta(minutes=10))
```

  - Expected: Fails to assert behaviors against the current bare user.delete() stub.

- [ ] **Step 2 (test): Tests: (a) test_delete_wrong_password -> force_authenticate(pw_user); DELETE body {'password':'nope'} -> 400 and 'password' in body and User still exists. (b) test_delete_missing_password -> DELETE no body -> 400. (c) test_delete_correct_password -> body {'password':'pw12345!'} -> 204 and User.objects.filter(pk=pw_user.pk).exists() is False and EmailMessageLog/EmailVerification for that user gone. (d) test_oauth_requires_confirm -> force_authenticate(oauth_user); DELETE {} -> 400 with 'confirm'; DELETE {'confirm':'nope'} -> 400; DELETE {'confirm':'DELETE'} -> 204 and user gone. (e) test_delete_blacklists_refresh_token -> mint RefreshToken.for_user(pw_user) BEFORE delete (creates OutstandingToken), then DELETE with correct password, assert BlacklistedToken count for that token >=1 (query via OutstandingToken jti or that BlacklistedToken.objects.exists()). Use APIClient credentials with the access token OR force_authenticate; note force_authenticate bypasses real token creation, so explicitly create RefreshToken.for_user(pw_user) in the test to populate OutstandingToken.**

  - Expected: All fail against the stub.

### Task 4: Task 4 — Implement UserAccountDeleteView

**Files:** `/Users/narekmeloyan/PycharmProjects/JokesForProject/jokes/views.py`

- [ ] **Step 1 (impl): Replace UserAccountDeleteView.delete with: re-auth gate first (password vs typed DELETE based on user.has_usable_password()), returning 400 with the contract error dicts; then transaction.atomic() purge in order — blacklist tokens (BEFORE delete, guarded by INSTALLED_APPS check + inner import), avatar file delete (try/except), EmailMessageLog + EmailVerification delete, user.delete(); return 204.**

```
def delete(self, request):
    user = request.user
    if user.has_usable_password():
        password = (request.data or {}).get('password')
        if not password:
            return Response({'password': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        if not user.check_password(password):
            return Response({'password': ['Incorrect password.']}, status=status.HTTP_400_BAD_REQUEST)
    else:
        if (request.data or {}).get('confirm') != 'DELETE':
            return Response({'confirm': ['Type DELETE to confirm account deletion.']}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        if 'rest_framework_simplejwt.token_blacklist' in settings.INSTALLED_APPS:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
            for ot in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=ot)
        profile = UserProfile.objects.filter(user=user).first()
        if profile and profile.avatar:
            try:
                profile.avatar.delete(save=False)
            except Exception:
                pass
        EmailMessageLog.objects.filter(Q(user=user) | Q(to_email__iexact=user.email)).delete()
        EmailVerification.objects.filter(user=user).delete()
        user.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
```

  - Expected: Matches the error-body contract the tests assert; blacklisting happens before user.delete() because OutstandingToken.user is SET_NULL.

- [ ] **Step 2 (run): Run the delete tests, then the full export+delete suite.**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes.tests.AccountDeleteTests jokes.tests.DataExportTests --keepdb
```

  - Expected: All pass.

- [ ] **Step 3 (run): Run the full jokes + notifications suites to confirm no regressions (the Google-exemption / verification tests touch the same auth/notifications surface).**

```
DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 DB_HOST=localhost DB_PORT=5432 .venv/bin/python manage.py test jokes notifications --keepdb
```

  - Expected: Green.

- [ ] **Step 4 (commit): Commit delete feature.**

```
git add jokes/views.py jokes/tests.py && git commit -m "Harden account deletion: re-auth, avatar/email-log purge, token blacklist"
```

  - Expected: Plain commit message.

**Decisions in this plan:**

- *Single .json or zipped .json for the export?* → Zipped JSON (.zip containing jokes-for-data-export.json), Content-Type application/zip — this is exactly what CD6 specifies ('downloadable zipped-JSON') and keeps room to add files (e.g. avatar) later without changing the contract.
- *How to handle re-auth for Google OAuth accounts that have no usable password?* → Branch on user.has_usable_password(). Usable -> require+verify {"password"}. Unusable -> require body {"confirm": "DELETE"} exactly. This matches CD6 and the existing Google-exemption pattern (set_unusable_password).
- *Must the refresh-token blacklist run before or after user.delete()?* → Before. OutstandingToken.user is on_delete=SET_NULL, so after user.delete() the rows survive with user_id=NULL and the per-user filter would miss them. Blacklist first, inside the same atomic block.
- *Should the blacklist step be unconditional?* → Guard it with `'rest_framework_simplejwt.token_blacklist' in settings.INSTALLED_APPS` and import inside that branch, so the view degrades gracefully if the app is ever disabled (it is currently enabled per settings.py L59).
- *Does the export need a date_of_birth field?* → No. date_of_birth is Work-Stream B (CD2) and does NOT exist on UserProfile yet. Do not reference it in Stream D to avoid a cross-stream import error; if it lands first, it'll naturally appear under the profile/account section in a follow-up.
- *Do urls.py need changes?* → No. Both routes already exist (jokes/urls.py L70-71). Only the two view bodies change.
- *How to make avatar deletion safe/idempotent?* → Wrap profile.avatar.delete(save=False) in try/except so a missing file (GCS object already gone, or filesystem race) cannot abort the transaction; account deletion must still succeed.

**Risks:**

- force_authenticate() bypasses real JWT issuance, so no OutstandingToken row is created automatically — the blacklist test MUST explicitly call RefreshToken.for_user(pw_user) before deleting, or the assertion will trivially pass/fail for the wrong reason. Mint the token in-test.
- Tests run with --keepdb against a shared local Postgres; reusing the email 'creator@example.com' across classes is fine (each TestCase wraps in a transaction), but pick distinct emails to avoid confusion. ACCOUNT_UNIQUE_EMAIL is on.
- Joke.save() auto-generates a share-card PNG via PIL on create; seeding many jokes in tests is slow and writes to MEDIA_ROOT. Seed ONE joke and reuse it across the user's rows to keep tests fast and avoid filesystem churn.
- EmailMessageLog.user is on_delete=SET_NULL (not CASCADE), so it is NOT auto-removed by user.delete() — the explicit filter-delete is REQUIRED for GDPR purge, and the test must assert those rows are gone (a bare user.delete() would orphan them with user=NULL).
- UserProfile/UserPreference are auto-created by a post_save signal on user creation; the export must tolerate their presence and the delete cascade removes them — don't double-create in tests or you'll hit the OneToOne unique constraint.
- Including full joke text for saved/favorited jokes is acceptable (public content), but be careful NOT to serialize any FK that exposes another user's email/username (UserBlock.blocked, ContentReport across reporters); emit integer ids only and assert assertNotIn(other_user_email, dumped_json).
- DjangoJSONEncoder is required for datetime/date/time fields; plain json.dumps will raise TypeError on the timezone-aware datetimes pulled via .values().
