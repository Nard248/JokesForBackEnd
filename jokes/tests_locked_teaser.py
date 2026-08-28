"""A locked joke must still have something to show.

The F-021 fix correctly stopped shipping the payoff in ``text`` — a published
two-part joke carries a denormalized "<setup> <punchline>", so withholding
``text`` was the only way to close the leak.

But it left a hole its own docstring assumes away: *"``setup`` is always kept,
and the client composes the locked card from it"* is true only for two-part
formats. A one-liner carries its whole joke in ``text`` and has an **empty**
``setup``, so a locked one-liner arrives with `text=None, setup='', lines=None`
— nothing to display at all.

One-liners are roughly 40% of the catalogue, so a reader past the daily cap
scrolls a wall of blank cards. That is worse than a paywall: it looks broken,
and it converts nobody, because you cannot want a joke you cannot see the start
of.

These tests pin a ``teaser`` field that is always present and never the payoff.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jokes.models import AgeRating, Format, Joke, Language

User = get_user_model()


class LockedTeaserTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.age = AgeRating.objects.order_by('min_age').first()
        cls.lang = Language.objects.get(code='en')

    def _joke(self, slug, **fields):
        fmt = Format.objects.get(slug=slug)
        return Joke.objects.create(
            format=fmt, age_rating=self.age, language=self.lang,
            content_tier='tier_1', **fields,
        )

    def _exhaust_allowance(self, user):
        """Burn the daily cap so everything else is locked for this reader."""
        filler = [
            self._joke('oneliner', text=f'Filler number {i} for the cap.', setup='', punchline='')
            for i in range(10)
        ]
        self.client.force_authenticate(user)
        for joke in filler:
            self.client.get(f'/api/v1/jokes/{joke.id}/')
        return filler

    def test_a_locked_oneliner_still_has_a_teaser(self):
        user = User.objects.create_user(username='t1@x.com', email='t1@x.com', password='pw')
        self._exhaust_allowance(user)

        target = self._joke(
            'oneliner',
            text='I told my laptop a joke about paging and it never returned.',
            setup='', punchline='',
        )
        body = self.client.get(f'/api/v1/jokes/{target.id}/').json()

        self.assertTrue(body['is_locked'], 'expected the cap to be spent')
        self.assertIsNone(body['text'], 'the payoff must still be withheld')
        self.assertTrue(
            body.get('teaser'),
            'a locked one-liner has nothing to display without a teaser',
        )

    def test_the_teaser_is_not_the_punchline(self):
        """The whole point: enough to want it, not enough to have it."""
        user = User.objects.create_user(username='t2@x.com', email='t2@x.com', password='pw')
        self._exhaust_allowance(user)

        target = self._joke(
            'oneliner',
            text='I told my laptop a joke about paging and it never returned.',
            setup='', punchline='',
        )
        teaser = self.client.get(f'/api/v1/jokes/{target.id}/').json()['teaser']

        self.assertNotIn('never returned', teaser, 'the teaser gave away the payoff')
        self.assertLess(len(teaser), len(target.text))

    def test_two_part_jokes_keep_their_full_setup(self):
        """A setup is already a teaser by construction — do not truncate it."""
        user = User.objects.create_user(username='t3@x.com', email='t3@x.com', password='pw')
        self._exhaust_allowance(user)

        target = self._joke(
            'setup',
            setup='Why did the two-part joke cross the road?',
            punchline='To prove the paywall strips every field.',
            text='Why did the two-part joke cross the road? To prove the paywall strips every field.',
        )
        body = self.client.get(f'/api/v1/jokes/{target.id}/').json()

        self.assertEqual(body['teaser'], target.setup)
        self.assertNotIn('strips every field', body['teaser'])

    def test_an_unlocked_joke_also_carries_a_teaser(self):
        """One field the client can always read, locked or not — otherwise every
        caller reimplements the fallback chain and one of them gets it wrong."""
        user = User.objects.create_user(username='t4@x.com', email='t4@x.com', password='pw')
        self.client.force_authenticate(user)

        target = self._joke('oneliner', text='A perfectly ordinary joke.', setup='', punchline='')
        body = self.client.get(f'/api/v1/jokes/{target.id}/').json()

        self.assertFalse(body['is_locked'])
        self.assertTrue(body['teaser'])

    def test_a_locked_knock_knock_has_a_teaser(self):
        """Knock-knock carries everything in `lines`, which is also nulled."""
        user = User.objects.create_user(username='t5@x.com', email='t5@x.com', password='pw')
        self._exhaust_allowance(user)

        target = self._joke(
            'knock', setup='', punchline='',
            text='Knock, knock. Who is there? Regression. Regression who?',
            lines=['Knock, knock.', 'Who is there?', 'Regression.', 'Regression who?'],
        )
        body = self.client.get(f'/api/v1/jokes/{target.id}/').json()

        self.assertIsNone(body['lines'])
        self.assertTrue(body.get('teaser'), 'a locked knock-knock renders blank without this')

    def test_no_locked_joke_in_a_page_is_blank(self):
        """The state a free reader actually reaches: a whole page of locked
        jokes, every one of which must be worth looking at."""
        user = User.objects.create_user(username='t6@x.com', email='t6@x.com', password='pw')
        self._exhaust_allowance(user)
        for i in range(6):
            self._joke('oneliner', text=f'Another joke number {i} about databases.',
                       setup='', punchline='')

        results = self.client.get('/api/v1/jokes/?page=1').json()['results']
        locked = [j for j in results if j['is_locked']]
        self.assertTrue(locked, 'expected locked jokes on the page')
        for joke in locked:
            self.assertTrue(
                joke.get('teaser'),
                f"joke {joke['id']} ({joke['format']['slug']}) would render as an empty card",
            )
