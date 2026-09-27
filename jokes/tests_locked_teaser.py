"""Free joke responses keep their teaser previews alongside full content."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jokes.models import AgeRating, Format, Joke, Language

User = get_user_model()


class FreeTeaserTests(APITestCase):
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
        """Read enough content to exceed the retired daily allowance."""
        filler = [
            self._joke('oneliner', text=f'Filler number {i} for the cap.', setup='', punchline='')
            for i in range(10)
        ]
        self.client.force_authenticate(user)
        for joke in filler:
            self.client.get(f'/api/v1/jokes/{joke.id}/')
        return filler

    def test_oneliner_keeps_full_content_and_teaser_after_legacy_cap(self):
        user = User.objects.create_user(username='t1@x.com', email='t1@x.com', password='pw')
        self._exhaust_allowance(user)

        target = self._joke(
            'oneliner',
            text='I told my laptop a joke about paging and it never returned.',
            setup='', punchline='',
        )
        body = self.client.get(f'/api/v1/jokes/{target.id}/').json()

        self.assertFalse(body['is_locked'])
        self.assertEqual(body['text'], target.text)
        self.assertTrue(
            body.get('teaser'),
            'one-liner preview remains useful alongside full content',
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

    def test_knock_knock_keeps_dialogue_and_teaser_after_legacy_cap(self):
        """Knock-knock dialogue stays readable after many prior reads."""
        user = User.objects.create_user(username='t5@x.com', email='t5@x.com', password='pw')
        self._exhaust_allowance(user)

        target = self._joke(
            'knock', setup='', punchline='',
            text='Knock, knock. Who is there? Regression. Regression who?',
            lines=['Knock, knock.', 'Who is there?', 'Regression.', 'Regression who?'],
        )
        body = self.client.get(f'/api/v1/jokes/{target.id}/').json()

        self.assertEqual(body['lines'], target.lines)
        self.assertTrue(body.get('teaser'), 'knock-knock preview is present')

    def test_list_after_legacy_cap_keeps_content_visible(self):
        """No list entry becomes a purchase-locked blank card."""
        user = User.objects.create_user(username='t6@x.com', email='t6@x.com', password='pw')
        self._exhaust_allowance(user)
        for i in range(6):
            self._joke('oneliner', text=f'Another joke number {i} about databases.',
                       setup='', punchline='')

        results = self.client.get('/api/v1/jokes/?page=1').json()['results']
        self.assertTrue(results)
        for joke in results:
            self.assertFalse(joke['is_locked'])
            self.assertIsNotNone(joke['text'])
            self.assertTrue(
                joke.get('teaser'),
                f"joke {joke['id']} ({joke['format']['slug']}) would render as an empty card",
            )
