"""Creator-Tips-Wave Task 1: Tip model + payment-mode checkout endpoint.

Security-critical (payments): fixed-tier amount allowlist, self-tip
prevention, creator existence/creator-ness — none of the rejection paths may
create a Tip row. Mirrors billing/tests/test_checkout_portal.py's mocking
pattern (patches billing.stripe_gateway.stripe).
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from billing.models import Tip
from jokes.models import AgeRating, Format, Joke, Language

User = get_user_model()

CHECKOUT_URL = '/api/v1/tips/checkout/'


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(slug='one-liner', defaults={'name': 'One-Liner'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


def make_user(email):
    return User.objects.create_user(username=email, email=email, password='pw')


def make_joke(creator, text='Why did the chicken cross the road?'):
    fmt, age, lang = _taxonomy()
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(text=text, format=fmt, age_rating=age, language=lang, creator=creator)


def make_creator(email):
    """A user with a published joke — passes the is-a-creator check."""
    user = make_user(email)
    make_joke(user)
    return user


class TipCheckoutValidationTests(APITestCase):
    """Amount-tier allowlist, self-tip, creator existence/creator-ness.

    None of these rejections may create a Tip row.
    """

    def setUp(self):
        self.sender = make_user('sender@example.com')
        self.creator = make_creator('creator1@example.com')
        self.client.force_authenticate(self.sender)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_amount_not_in_tier_rejected(self):
        for bad_amount in (250, 0, -100, 99999):
            resp = self.client.post(
                CHECKOUT_URL, {'creator_id': self.creator.pk, 'amount_cents': bad_amount},
            )
            self.assertEqual(resp.status_code, 400, f'amount={bad_amount} should be rejected')
        self.assertEqual(Tip.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_self_tip_rejected(self):
        # Sender must itself be a creator to reach the self-tip guard (creator
        # existence + is-a-creator checks run first).
        make_joke(self.sender, text='self joke')
        resp = self.client.post(
            CHECKOUT_URL, {'creator_id': self.sender.pk, 'amount_cents': 100},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Tip.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_target_not_a_creator_rejected(self):
        non_creator = make_user('noncreator@example.com')
        resp = self.client.post(
            CHECKOUT_URL, {'creator_id': non_creator.pk, 'amount_cents': 100},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data.get('code'), 'not_a_creator')
        self.assertEqual(Tip.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_nonexistent_creator_404(self):
        resp = self.client.post(
            CHECKOUT_URL, {'creator_id': 999999, 'amount_cents': 100},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Tip.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_joke_belonging_to_different_creator_rejected(self):
        other_creator = make_creator('other@example.com')
        other_joke = Joke.objects.filter(creator=other_creator).first()
        resp = self.client.post(CHECKOUT_URL, {
            'creator_id': self.creator.pk,
            'amount_cents': 100,
            'joke_id': other_joke.pk,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Tip.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_missing_creator_id_400(self):
        resp = self.client.post(CHECKOUT_URL, {'amount_cents': 100})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Tip.objects.count(), 0)

    def test_unauthenticated_401(self):
        self.client.force_authenticate(None)
        resp = self.client.post(
            CHECKOUT_URL, {'creator_id': self.creator.pk, 'amount_cents': 100},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(Tip.objects.count(), 0)


class TipCheckoutDormantTests(APITestCase):
    """With no STRIPE_SECRET_KEY, tip checkout returns 503 (mirrors subscription checkout)."""

    @override_settings(STRIPE_SECRET_KEY='')
    def test_dormant_returns_503(self):
        sender = make_user('dormant-sender@example.com')
        creator = make_creator('dormant-creator@example.com')
        self.client.force_authenticate(sender)
        resp = self.client.post(CHECKOUT_URL, {'creator_id': creator.pk, 'amount_cents': 100})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'billing_unavailable')
        self.assertEqual(Tip.objects.count(), 0)


class TipCheckoutHappyPathTests(APITestCase):
    """Mocked Stripe gateway — session URL + Tip(pending) row stamped with metadata."""

    def setUp(self):
        self.sender = make_user('happy-sender@example.com')
        self.creator = make_creator('happy-creator@example.com')
        self.client.force_authenticate(self.sender)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('billing.stripe_gateway.stripe')
    def test_happy_path_with_joke_creates_pending_tip(self, mstripe):
        mstripe.api_key = ''
        mstripe.api_version = ''
        mock_customer = MagicMock()
        mock_customer.id = 'cus_tip_test'
        mstripe.Customer.create.return_value = mock_customer
        mock_session = MagicMock()
        mock_session.id = 'cs_test_tip_123'
        mock_session.url = 'https://stripe.test/cs_test_tip_123'
        mstripe.checkout.Session.create.return_value = mock_session

        joke = Joke.objects.filter(creator=self.creator).first()
        resp = self.client.post(CHECKOUT_URL, {
            'creator_id': self.creator.pk,
            'amount_cents': 500,
            'joke_id': joke.pk,
        })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['checkout_url'], 'https://stripe.test/cs_test_tip_123')
        self.assertIn('tip_id', resp.data)

        tip = Tip.objects.get(pk=resp.data['tip_id'])
        self.assertEqual(tip.sender_id, self.sender.pk)
        self.assertEqual(tip.creator_id, self.creator.pk)
        self.assertEqual(tip.joke_id, joke.pk)
        self.assertEqual(tip.amount_cents, 500)
        self.assertEqual(tip.status, 'pending')
        self.assertEqual(tip.stripe_checkout_session_id, 'cs_test_tip_123')
        self.assertEqual(Tip.objects.count(), 1)

        # Stripe was called in payment mode with server-constructed metadata.
        _, kwargs = mstripe.checkout.Session.create.call_args
        self.assertEqual(kwargs['mode'], 'payment')
        self.assertEqual(kwargs['metadata'], {
            'type': 'tip',
            'tip_id': str(tip.id),
            'creator_id': str(self.creator.id),
            'joke_id': str(joke.id),
        })

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('billing.stripe_gateway.stripe')
    def test_happy_path_without_joke_id(self, mstripe):
        mstripe.api_key = ''
        mstripe.api_version = ''
        mock_customer = MagicMock()
        mock_customer.id = 'cus_tip_test2'
        mstripe.Customer.create.return_value = mock_customer
        mock_session = MagicMock()
        mock_session.id = 'cs_test_tip_456'
        mock_session.url = 'https://stripe.test/cs_test_tip_456'
        mstripe.checkout.Session.create.return_value = mock_session

        resp = self.client.post(CHECKOUT_URL, {'creator_id': self.creator.pk, 'amount_cents': 300})

        self.assertEqual(resp.status_code, 200)
        tip = Tip.objects.get(pk=resp.data['tip_id'])
        self.assertIsNone(tip.joke_id)

        _, kwargs = mstripe.checkout.Session.create.call_args
        self.assertEqual(kwargs['metadata']['joke_id'], '')


class TipCheckoutRemovedOnlyJokeNotCreatorTests(APITestCase):
    """A user whose ONLY joke is is_removed=True is NOT a creator.

    Joke.objects (the default manager) excludes is_removed=True globally —
    takedown enforcement, see jokes/managers.py:JokeManager. The checkout
    view's is-a-creator check already queries through that manager, so a
    moderated-away joke must not count.
    """

    def setUp(self):
        self.sender = make_user('removedcheck-sender@example.com')
        self.target = make_user('removedcheck-target@example.com')
        joke = make_joke(self.target, text='will be removed')
        joke.is_removed = True
        joke.save()
        self.client.force_authenticate(self.sender)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    def test_removed_only_joke_target_rejected_not_a_creator(self):
        resp = self.client.post(CHECKOUT_URL, {
            'creator_id': self.target.pk, 'amount_cents': 100,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data.get('code'), 'not_a_creator')
        self.assertEqual(Tip.objects.count(), 0)


class TipCheckoutThrottleTests(APITestCase):
    """Payments endpoint gets its own scoped throttle, off the 1000/hr global."""

    def test_throttle_scope_registered_in_settings(self):
        from django.conf import settings
        rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        self.assertIn('tips-checkout', rates)

    def test_view_uses_scoped_throttle(self):
        from rest_framework.throttling import ScopedRateThrottle
        from billing.views import TipCheckoutView
        self.assertEqual(TipCheckoutView.throttle_scope, 'tips-checkout')
        self.assertIn(ScopedRateThrottle, TipCheckoutView.throttle_classes)


class TipAmountTiersTypeTests(APITestCase):
    def test_tip_amount_tiers_is_frozenset(self):
        from billing.views import TIP_AMOUNT_TIERS_CENTS
        self.assertIsInstance(TIP_AMOUNT_TIERS_CENTS, frozenset)


class CreatorTipsSummaryTests(APITestCase):
    """GET /api/v1/creators/{id}/tips/summary/ — public, only succeeded tips counted."""

    def setUp(self):
        self.creator = make_creator('summary-creator@example.com')
        self.sender = make_user('summary-sender@example.com')

    def _url(self, creator_id):
        return f'/api/v1/creators/{creator_id}/tips/summary/'

    def test_only_succeeded_tips_counted(self):
        Tip.objects.create(sender=self.sender, creator=self.creator, amount_cents=100, status='pending')
        Tip.objects.create(sender=self.sender, creator=self.creator, amount_cents=300, status='failed')
        Tip.objects.create(sender=self.sender, creator=self.creator, amount_cents=500, status='succeeded')
        Tip.objects.create(sender=self.sender, creator=self.creator, amount_cents=1000, status='succeeded')

        resp = self.client.get(self._url(self.creator.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 2)
        self.assertEqual(resp.data['total_cents'], 1500)

    def test_no_tips_returns_zero(self):
        other = make_creator('summary-empty@example.com')
        resp = self.client.get(self._url(other.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 0)
        self.assertEqual(resp.data['total_cents'], 0)

    def test_is_public_no_auth_required(self):
        self.client.force_authenticate(None)
        Tip.objects.create(sender=self.sender, creator=self.creator, amount_cents=500, status='succeeded')
        resp = self.client.get(self._url(self.creator.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)


class MyTipsHistoryTests(APITestCase):
    """GET /api/v1/users/me/tips/ — caller's sent tips only, most recent first."""

    MY_TIPS_URL = '/api/v1/users/me/tips/'

    def setUp(self):
        self.sender = make_user('mytips-sender@example.com')
        self.other_sender = make_user('mytips-other@example.com')
        self.creator = make_creator('mytips-creator@example.com')

    def test_requires_auth(self):
        resp = self.client.get(self.MY_TIPS_URL)
        self.assertEqual(resp.status_code, 401)

    def test_returns_only_my_sent_tips_most_recent_first(self):
        other_tip = Tip.objects.create(
            sender=self.other_sender, creator=self.creator, amount_cents=100, status='succeeded',
        )
        tip1 = Tip.objects.create(sender=self.sender, creator=self.creator, amount_cents=300, status='succeeded')
        tip2 = Tip.objects.create(sender=self.sender, creator=self.creator, amount_cents=500, status='pending')

        self.client.force_authenticate(self.sender)
        resp = self.client.get(self.MY_TIPS_URL)

        self.assertEqual(resp.status_code, 200)
        results = resp.data['results']
        self.assertEqual(len(results), 2, 'Only the caller\'s own tips')
        self.assertEqual(results[0]['id'], tip2.id, 'Most recent first')
        self.assertEqual(results[1]['id'], tip1.id)
        returned_ids = {r['id'] for r in results}
        self.assertNotIn(other_tip.id, returned_ids, 'Isolation: another user\'s tip must not appear')
