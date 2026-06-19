"""Tests for lazy quota reset and check_and_consume_quota."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from billing import entitlements
from billing.entitlements import check_and_consume_quota, check_quota_by_count
from billing.models import Plan, UsageCounter

User = get_user_model()

FAKE_DATE_A = '2026-06-01'
FAKE_DATE_B = '2026-07-01'


class QuotaConsumeTests(TestCase):
    """check_and_consume_quota: basic consume + block at limit."""

    def setUp(self):
        self.user = User.objects.create_user(username='quota@example.com', email='quota@example.com', password='pw')

    def test_first_consume_allowed(self):
        result = check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        self.assertTrue(result.allowed)
        self.assertEqual(result.used, 1)

    def test_consume_up_to_limit(self):
        free_plan = Plan.objects.get(is_default=True)
        free_plan.limits['submissions_per_day'] = 2
        free_plan.save()

        r1 = check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        r2 = check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        r3 = check_and_consume_quota(self.user, 'submissions_per_day', period='day')

        self.assertTrue(r1.allowed)
        self.assertTrue(r2.allowed)
        self.assertFalse(r3.allowed)
        self.assertEqual(r3.remaining, 0)

        # Restore
        free_plan.limits['submissions_per_day'] = 5
        free_plan.save()

    def test_idempotent_period_key(self):
        """Two calls in the same period accumulate correctly."""
        check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        counter = UsageCounter.objects.get(
            user=self.user, key='submissions_per_day',
        )
        self.assertEqual(counter.count, 2)


class QuotaLazyResetTests(TestCase):
    """Lazy period reset: new period_key = fresh counter, no cron."""

    def setUp(self):
        self.user = User.objects.create_user(username='reset@example.com', email='reset@example.com', password='pw')
        free_plan = Plan.objects.get(is_default=True)
        free_plan.limits['submissions_per_day'] = 2
        free_plan.save()

    def tearDown(self):
        free_plan = Plan.objects.get(is_default=True)
        free_plan.limits['submissions_per_day'] = 5
        free_plan.save()

    @patch('billing.entitlements.date')
    def test_quota_resets_lazily_on_period_rollover(self, mock_date):
        import datetime

        # Consume to limit in 'day' period 2026-06-15
        mock_date.today.return_value = datetime.date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)

        r1 = check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        r2 = check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        r3 = check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        self.assertFalse(r3.allowed)

        # Roll to next day — new period_key -> fresh counter, no cron needed
        mock_date.today.return_value = datetime.date(2026, 6, 16)
        r4 = check_and_consume_quota(self.user, 'submissions_per_day', period='day')
        self.assertTrue(r4.allowed, 'New period should reset quota lazily')
        self.assertEqual(r4.used, 1)

    @patch('billing.entitlements.date')
    def test_monthly_period_reset(self, mock_date):
        import datetime

        mock_date.today.return_value = datetime.date(2026, 6, 1)
        mock_date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)

        free_plan = Plan.objects.get(is_default=True)
        free_plan.limits['submissions_per_day'] = 1
        free_plan.save()

        r1 = check_and_consume_quota(self.user, 'submissions_per_day', period='month')
        r2 = check_and_consume_quota(self.user, 'submissions_per_day', period='month')
        self.assertFalse(r2.allowed)

        # Next month
        mock_date.today.return_value = datetime.date(2026, 7, 1)
        r3 = check_and_consume_quota(self.user, 'submissions_per_day', period='month')
        self.assertTrue(r3.allowed)

        free_plan.limits['submissions_per_day'] = 5
        free_plan.save()


class CheckQuotaByCountTests(TestCase):
    """check_quota_by_count: uses a callable for live row count, no UsageCounter write."""

    def setUp(self):
        self.user = User.objects.create_user(username='bycount@example.com', email='bycount@example.com', password='pw')

    def test_under_limit_allowed(self):
        result = check_quota_by_count(
            self.user, 'mystery_box_rolls_per_day',
            count_callable=lambda: 2,
            period='day',
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.remaining, 1)

    def test_at_limit_blocked(self):
        result = check_quota_by_count(
            self.user, 'mystery_box_rolls_per_day',
            count_callable=lambda: 3,
            period='day',
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.remaining, 0)

    def test_no_usage_counter_written(self):
        check_quota_by_count(
            self.user, 'mystery_box_rolls_per_day',
            count_callable=lambda: 1,
            period='day',
        )
        self.assertEqual(UsageCounter.objects.count(), 0)
