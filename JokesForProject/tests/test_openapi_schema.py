"""Every serializer in the published OpenAPI schema must have its own component name.

drf_spectacular names a serializer's component after its class. Two classes
called ``CollectionSerializer`` (reader collections in ``jokes``, creator
collections in ``creator_insights``) both became ``Collection``, so one silently
overwrote the other and the schema described the wrong shape for one family of
endpoints.
"""
from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator


class OpenApiSchemaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def test_reader_and_creator_collections_are_distinct_components(self):
        components = self.schema['components']['schemas']
        self.assertIn('joke_count', components['Collection']['properties'])
        self.assertIn('kind', components['CreatorCollection']['properties'])
        self.assertNotIn('kind', components['Collection']['properties'])
