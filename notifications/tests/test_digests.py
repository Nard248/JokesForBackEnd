"""Email-Digest-Wave Task 2: daily digest + creator milestone engine.

Idempotency is load-bearing here: EmailMessageLog doubles as the per-day
send ledger (see notifications.digests.run_daily_digests), so a same-day
re-run must send zero new emails. Email backend is locmem — assert on
django.core.mail.outbox + EmailMessageLog rows, never a real transport.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from freezegun import freeze_time

from jokes.models import (
    AgeRating, DailyJoke, Format, Joke, JokeReaction, Language,
)
from jokes.recommendations import get_daily_editorial_joke
from notifications.digests import run_daily_digests
from notifications.models import DigestRun, EmailMessageLog
from notifications.unsubscribe import load_unsubscribe_token

User = get_user_model()

TODAY = '2026-08-04T15:00:00Z'
TOMORROW = '2026-08-05T15:00:00Z'


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(slug='setup', defaults={'name': 'Setup/Punchline'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


def _make_joke(fmt, age, lang, *, creator=None, setup='Why did the chicken cross the road?',
               punchline='To get to the other side.', is_removed=False, content_tier='tier_1'):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text='', setup=setup, punchline=punchline, format=fmt, age_rating=age,
            language=lang, content_tier=content_tier, creator=creator, is_removed=is_removed,
        )


def _make_user(email, *, is_active=True, digest_opt_in=True, milestone_opt_in=True):
    user = User.objects.create_user(username=email, email=email, password='pw', is_active=is_active)
    profile = user.profile
    profile.email_digest_opt_in = digest_opt_in
    profile.creator_milestone_opt_in = milestone_opt_in
    profile.save(update_fields=['email_digest_opt_in', 'creator_milestone_opt_in'])
    return user


def _react(user, joke):
    JokeReaction.objects.create(user=user, joke=joke, reaction=JokeReaction.REACTION_LOL)


class DailyEditorialJokeTierGateTests(TestCase):
    """Compliance gate (review fold): the digest is a BROADCAST to every
    opted-in user with no per-recipient age/tier check, unlike every other
    serving path. get_daily_editorial_joke must never surface a tier_2
    (Mature, 18+ opt-in) joke, even if it was the day's most-delivered pick."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()

    def test_tier_1_joke_featured_over_more_delivered_tier_2_joke(self):
        tier1_joke = _make_joke(self.fmt, self.age, self.lang, setup='Universal setup', content_tier='tier_1')
        tier2_joke = _make_joke(self.fmt, self.age, self.lang, setup='Mature setup', content_tier='tier_2')

        with freeze_time(TODAY):
            today = timezone.now().date()
            # tier_2 delivered to 2 users (would win the "most-delivered" mode
            # with no tier filter); tier_1 delivered to only 1.
            DailyJoke.objects.create(user=_make_user('t2-a@example.com'), joke=tier2_joke, date=today)
            DailyJoke.objects.create(user=_make_user('t2-b@example.com'), joke=tier2_joke, date=today)
            DailyJoke.objects.create(user=_make_user('t1-a@example.com'), joke=tier1_joke, date=today)

            featured = get_daily_editorial_joke(today)

        self.assertEqual(featured.pk, tier1_joke.pk)

    def test_returns_none_when_only_tier_2_delivered_today(self):
        tier2_joke = _make_joke(self.fmt, self.age, self.lang, content_tier='tier_2')

        with freeze_time(TODAY):
            today = timezone.now().date()
            DailyJoke.objects.create(user=_make_user('t2-only@example.com'), joke=tier2_joke, date=today)

            featured = get_daily_editorial_joke(today)

        self.assertIsNone(featured)

    def test_digest_skips_when_only_tier_2_delivered_today(self):
        # End-to-end: run_daily_digests must skip (not broadcast mature
        # content) when tier_2 is the only thing delivered today.
        tier2_joke = _make_joke(self.fmt, self.age, self.lang, content_tier='tier_2')

        with freeze_time(TODAY), override_settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        ):
            today = timezone.now().date()
            DailyJoke.objects.create(user=_make_user('t2-only-e2e@example.com'), joke=tier2_joke, date=today)
            _make_user('would-be-reader@example.com')

            result = run_daily_digests()

        self.assertTrue(result['skipped'])
        self.assertEqual(result['digests_sent'], 0)
        self.assertFalse(any(m.to == ['would-be-reader@example.com'] for m in mail.outbox))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DailyDigestEligibilityTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.joke = _make_joke(self.fmt, self.age, self.lang)

    def _seed_todays_daily_joke(self):
        recipient = _make_user('recipient-seed@example.com')
        DailyJoke.objects.create(user=recipient, joke=self.joke, date=timezone.now().date())

    def test_sends_only_to_eligible_users(self):
        with freeze_time(TODAY):
            self._seed_todays_daily_joke()
            eligible = _make_user('eligible@example.com')
            opted_out = _make_user('optedout@example.com', digest_opt_in=False)
            unverified = _make_user('unverified@example.com', is_active=False)

            result = run_daily_digests()

            recipients = {m.to[0] for m in mail.outbox}
            self.assertIn('eligible@example.com', recipients)
            self.assertNotIn('optedout@example.com', recipients)
            self.assertNotIn('unverified@example.com', recipients)
            # +1 for the seed recipient used to plant today's DailyJoke.
            self.assertEqual(result['digests_sent'], 2)
            self.assertFalse(result['skipped'])

    def test_idempotent_same_day_second_run_sends_nothing_new(self):
        with freeze_time(TODAY):
            self._seed_todays_daily_joke()
            _make_user('reader@example.com')

            first = run_daily_digests()
            mail.outbox.clear()
            second = run_daily_digests()

            self.assertEqual(first['digests_sent'], 2)
            self.assertEqual(second['digests_sent'], 0)
            self.assertEqual(len(mail.outbox), 0)
            # Ledger: exactly one daily_digest log per user for the date.
            self.assertEqual(
                EmailMessageLog.objects.filter(template_name='daily_digest').count(), 2
            )

    def test_idempotent_resets_next_day(self):
        seed_recipient = _make_user('recipient-seed-reset@example.com')

        with freeze_time(TODAY):
            DailyJoke.objects.create(user=seed_recipient, joke=self.joke, date=timezone.now().date())
            _make_user('reader2@example.com')
            run_daily_digests()

        with freeze_time(TOMORROW):
            # A new day needs a new daily joke too, or the digest legitimately skips.
            DailyJoke.objects.create(user=seed_recipient, joke=self.joke, date=timezone.now().date())
            second_day = run_daily_digests()

        self.assertEqual(second_day['digests_sent'], 2)

    def test_cap_respected_and_remaining_reported(self):
        with freeze_time(TODAY):
            self._seed_todays_daily_joke()
            _make_user('cap-a@example.com')
            _make_user('cap-b@example.com')
            _make_user('cap-c@example.com')

            result = run_daily_digests(cap=1)

            self.assertEqual(result['digests_sent'], 1)
            self.assertEqual(len(mail.outbox), 1)
            # 4 eligible total (3 + the seed user) minus the 1 sent = 3 remaining.
            self.assertEqual(result['remaining'], 3)

    def test_no_daily_joke_today_skips_digests_but_processes_milestones(self):
        with freeze_time(TODAY):
            _make_user('reader3@example.com')  # eligible, but no DailyJoke exists today

            creator = _make_user('creator-nodaily@example.com')
            other_joke = _make_joke(self.fmt, self.age, self.lang, creator=creator)
            for i in range(15):
                _react(_make_user(f'nodaily-reactor{i}@example.com'), other_joke)

            result = run_daily_digests()

            self.assertTrue(result['skipped'])
            self.assertEqual(result['digests_sent'], 0)
            self.assertEqual(result['milestones_sent'], 1)
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(mail.outbox[0].to, ['creator-nodaily@example.com'])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CreatorMilestoneTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()

    def test_creator_crossing_threshold_gets_one_summary_email(self):
        with freeze_time(TODAY):
            creator = _make_user('milestone-creator@example.com')
            joke = _make_joke(self.fmt, self.age, self.lang, creator=creator)
            for i in range(10):
                _react(_make_user(f'reactor{i}@example.com'), joke)

            result = run_daily_digests()

            self.assertEqual(result['milestones_sent'], 1)
            milestone_mails = [m for m in mail.outbox if m.to == ['milestone-creator@example.com']]
            self.assertEqual(len(milestone_mails), 1)
            self.assertIn('10', milestone_mails[0].body)

    def test_below_threshold_gets_no_email(self):
        with freeze_time(TODAY):
            creator = _make_user('below-threshold@example.com')
            joke = _make_joke(self.fmt, self.age, self.lang, creator=creator)
            for i in range(9):
                _react(_make_user(f'below-reactor{i}@example.com'), joke)

            result = run_daily_digests()

            self.assertEqual(result['milestones_sent'], 0)
            self.assertFalse(any(m.to == ['below-threshold@example.com'] for m in mail.outbox))

    def test_milestone_opt_out_is_respected(self):
        with freeze_time(TODAY):
            creator = _make_user('optout-creator@example.com', milestone_opt_in=False)
            joke = _make_joke(self.fmt, self.age, self.lang, creator=creator)
            for i in range(10):
                _react(_make_user(f'optout-reactor{i}@example.com'), joke)

            run_daily_digests()

            self.assertFalse(any(m.to == ['optout-creator@example.com'] for m in mail.outbox))

    def test_milestone_idempotent_same_day(self):
        with freeze_time(TODAY):
            creator = _make_user('idem-creator@example.com')
            joke = _make_joke(self.fmt, self.age, self.lang, creator=creator)
            for i in range(10):
                _react(_make_user(f'idem-reactor{i}@example.com'), joke)

            first = run_daily_digests()
            mail.outbox.clear()
            second = run_daily_digests()

            self.assertEqual(first['milestones_sent'], 1)
            self.assertEqual(second['milestones_sent'], 0)
            self.assertEqual(len(mail.outbox), 0)

    def test_milestone_counts_only_new_reactions_since_last_email(self):
        with freeze_time(TODAY):
            creator = _make_user('since-last@example.com')
            joke = _make_joke(self.fmt, self.age, self.lang, creator=creator)
            for i in range(10):
                _react(_make_user(f'since-last-reactor{i}@example.com'), joke)
            first = run_daily_digests()
            self.assertEqual(first['milestones_sent'], 1)

        with freeze_time(TOMORROW):
            # Only 5 more new reactions the next day -- below threshold, no email.
            for i in range(5):
                _react(_make_user(f'since-last-reactor2-{i}@example.com'), joke)
            second = run_daily_digests()
            self.assertEqual(second['milestones_sent'], 0)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class UnsubscribeLinkInDigestTests(TestCase):
    def test_daily_digest_contains_valid_unsubscribe_link(self):
        fmt, age, lang = _taxonomy()
        joke = _make_joke(fmt, age, lang)
        with freeze_time(TODAY):
            reader = _make_user('unsub-reader@example.com')
            DailyJoke.objects.create(user=reader, joke=joke, date=timezone.now().date())

            run_daily_digests()

        msg = next(m for m in mail.outbox if m.to == ['unsub-reader@example.com'])
        self.assertIn('/api/v1/email/unsubscribe/?token=', msg.body)
        token = msg.body.split('token=')[1].split()[0].strip()
        data = load_unsubscribe_token(token)
        self.assertEqual(data['uid'], reader.pk)
        self.assertEqual(data['type'], 'digest')

    def test_creator_milestone_contains_valid_unsubscribe_link(self):
        fmt, age, lang = _taxonomy()
        with freeze_time(TODAY):
            creator = _make_user('unsub-creator@example.com')
            joke = _make_joke(fmt, age, lang, creator=creator)
            for i in range(10):
                _react(_make_user(f'unsub-reactor{i}@example.com'), joke)

            run_daily_digests()

        msg = next(m for m in mail.outbox if m.to == ['unsub-creator@example.com'])
        self.assertIn('/api/v1/email/unsubscribe/?token=', msg.body)
        token = msg.body.split('token=')[1].split()[0].strip()
        data = load_unsubscribe_token(token)
        self.assertEqual(data['uid'], creator.pk)
        self.assertEqual(data['type'], 'milestone')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DigestRunModelTests(TestCase):
    def test_run_writes_a_digest_run_row_with_counts(self):
        fmt, age, lang = _taxonomy()
        joke = _make_joke(fmt, age, lang)
        with freeze_time(TODAY):
            reader = _make_user('digestrun-reader@example.com')
            DailyJoke.objects.create(user=reader, joke=joke, date=timezone.now().date())

            run_daily_digests()

            run = DigestRun.objects.get(date=timezone.now().date())
            self.assertEqual(run.digests_sent, 1)
            self.assertIsNotNone(run.finished_at)
