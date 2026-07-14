"""Freezegun variant of the quota lazy-reset tests (behavior 6).

The existing test_quota_lazy_reset.py mocks ``billing.entitlements.date``.
This variant freezes the real wall clock instead — ``_period_key`` /
``_reset_at`` call ``datetime.date.today()``, which freezegun patches — so the
actual production code path runs unchanged as the clock advances across a day
and a month boundary.

Run:
  DATABASE_URL= DB_NAME=jokesfor DB_USER=postgres DB_PASSWORD=6969 \
    DB_HOST=localhost DB_PORT=5432 \
    .venv/bin/python manage.py test billing.tests.test_quota_time_progression --keepdb
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from freezegun import freeze_time

from billing.entitlements import check_and_consume_quota
from billing.models import Plan, UsageCounter

User = get_user_model()


class QuotaDayRolloverTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='fzquota@example.com', email='fzquota@example.com', password='pw',
        )
        self.plan = Plan.objects.get(is_default=True)
        self.plan.limits['submissions_per_day'] = 2
        self.plan.save()

    def tearDown(self):
        self.plan.limits['submissions_per_day'] = 5
        self.plan.save()

    def test_day_period_resets_lazily(self):
        with freeze_time('2026-07-14T08:00:00Z'):
            self.assertTrue(check_and_consume_quota(self.user, 'submissions_per_day').allowed)
            self.assertTrue(check_and_consume_quota(self.user, 'submissions_per_day').allowed)
            self.assertFalse(check_and_consume_quota(self.user, 'submissions_per_day').allowed)

        with freeze_time('2026-07-15T08:00:00Z'):
            r = check_and_consume_quota(self.user, 'submissions_per_day')
            self.assertTrue(r.allowed, 'new day -> fresh counter, no cron')
            self.assertEqual(r.used, 1)
            self.assertEqual(r.reset_at, '2026-07-16')

        # Two distinct period rows exist; neither was mutated by the other.
        self.assertEqual(
            set(UsageCounter.objects.filter(
                user=self.user, key='submissions_per_day').values_list('period_key', flat=True)),
            {'2026-07-14', '2026-07-15'},
        )

    def test_month_period_resets_across_month_boundary(self):
        self.plan.limits['submissions_per_day'] = 1
        self.plan.save()
        with freeze_time('2026-07-31T23:00:00Z'):
            self.assertTrue(check_and_consume_quota(self.user, 'submissions_per_day', period='month').allowed)
            self.assertFalse(check_and_consume_quota(self.user, 'submissions_per_day', period='month').allowed)

        with freeze_time('2026-08-01T00:30:00Z'):
            r = check_and_consume_quota(self.user, 'submissions_per_day', period='month')
            self.assertTrue(r.allowed, 'new month -> fresh monthly counter')
            self.assertEqual(r.reset_at, '2026-09-01')

        self.assertEqual(
            set(UsageCounter.objects.filter(
                user=self.user, key='submissions_per_day').values_list('period_key', flat=True)),
            {'2026-07', '2026-08'},
        )
