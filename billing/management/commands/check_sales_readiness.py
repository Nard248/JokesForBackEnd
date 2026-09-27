"""Read-only merchant/catalog checks. Never creates Stripe resources or prints IDs."""
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from billing.models import Plan
from billing.stripe_gateway import _client


class Command(BaseCommand):
    help = 'Read-only Stripe merchant, catalog and configuration checks; no sales activation.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true', help='Require a live key/catalog (default: test mode).')
        parser.add_argument('--expected-country', default='US')

    def handle(self, *args, **options):
        failures = []

        def check(label, passed):
            self.stdout.write(f'{label}: {"PASS" if passed else "FAIL"}')
            if not passed:
                failures.append(label)

        live = options['live']
        secret = settings.STRIPE_SECRET_KEY
        prefix = ('sk_live_', 'rk_live_') if live else ('sk_test_', 'rk_test_')
        check('key matches requested mode', bool(secret) and secret.startswith(prefix))
        check('webhook signing secret configured', settings.STRIPE_WEBHOOK_SECRET.startswith('whsec_'))
        self.stdout.write(f'creator sales gate: {"ON" if settings.CREATOR_CHECKOUT_ENABLED else "OFF"}')
        check('tips remain disabled', not settings.TIPS_ENABLED)
        for label, url in (
            ('success redirect', settings.BILLING_SUCCESS_URL),
            ('cancel redirect', settings.BILLING_CANCEL_URL),
            ('portal redirect', settings.BILLING_PORTAL_RETURN_URL),
        ):
            parsed = urlsplit(url)
            check(label, bool(parsed.hostname) and parsed.scheme in ({'https'} if live else {'http', 'https'}))
        if not secret or not secret.startswith(prefix):
            raise CommandError('Readiness failed; Stripe reads skipped because the key mode is wrong.')
        try:
            client = _client()
            account = client.Account.retrieve()
            check('merchant country matches', account.get('country') == options['expected_country'].upper())
            check('merchant details submitted', bool(account.get('details_submitted')))
            check('merchant charges enabled', bool(account.get('charges_enabled')))
            check('merchant payouts enabled', bool(account.get('payouts_enabled')))
            plans = list(Plan.objects.filter(is_active=True, is_public=True, amount_cents__gt=0)[:11])
            check('bounded paid creator catalog exists', 0 < len(plans) <= 10)
            for index, plan in enumerate(plans[:10], start=1):
                label = f'catalog item {index}'
                if not plan.stripe_price_id or not plan.stripe_product_id:
                    check(label, False)
                    continue
                price = client.Price.retrieve(plan.stripe_price_id)
                product = client.Product.retrieve(plan.stripe_product_id)
                recurring = price.get('recurring') or {}
                check(label, (
                    price.get('active') is True and product.get('active') is True
                    and price.get('livemode') is live
                    and price.get('product') == plan.stripe_product_id
                    and price.get('unit_amount') == plan.amount_cents
                    and price.get('currency') == plan.currency.lower()
                    and recurring.get('interval') == plan.interval
                    and recurring.get('interval_count') == 1
                ))
        except Exception as exc:
            # Stripe exceptions can include request/customer details. The operator
            # receives the exception class only; secrets and account IDs stay out.
            raise CommandError(f'Stripe readiness read failed ({type(exc).__name__}).') from None
        if failures:
            raise CommandError(f'{len(failures)} readiness check(s) failed. Keep creator sales disabled.')
        self.stdout.write(self.style.SUCCESS('Read-only checks passed. No configuration was changed.'))
        self.stdout.write('Still required: signed webhook end-to-end exercise, portal review and merchant approval.')
