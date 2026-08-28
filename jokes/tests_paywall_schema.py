"""The OpenAPI schema must admit that a locked joke's payoff fields are null.

``JokeSerializer.to_representation`` sets ``text``, ``punchline`` and ``lines``
to ``None`` whenever the paywall withholds a joke's payoff. The schema, however,
inherits its types from the *model* fields, which are non-nullable — so it
advertises a contract the API demonstrably breaks on every locked joke.

For the web client that is a latent inaccuracy. For a generated or hand-written
native client it is a crash: a non-optional Swift `String` decoding `null`
throws, and because DRF returns a whole page at once, one locked joke takes the
entire feed down. That is precisely the failure mode that would hit every free
reader past their tenth read of the day.
"""
from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator


class PaywalledFieldsAreNullableInSchemaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        cls.joke = schema['components']['schemas']['Joke']['properties']

    def _assert_nullable(self, field):
        prop = self.joke[field]
        self.assertTrue(
            prop.get('nullable') or 'null' in str(prop.get('type', '')),
            f'{field!r} is not nullable in the schema, but the paywall nulls it '
            f'for every locked joke: {prop}',
        )

    def test_text_is_nullable(self):
        self._assert_nullable('text')

    def test_punchline_is_nullable(self):
        self._assert_nullable('punchline')

    def test_lines_is_nullable(self):
        self._assert_nullable('lines')
