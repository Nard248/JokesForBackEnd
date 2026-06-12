from django.test import TestCase

from notifications.templates_registry import render_template, UnknownTemplate


class RenderTemplateTests(TestCase):
    def test_renders_verification_code(self):
        subject, html, text = render_template(
            'verification_code', {'code': '123456', 'ttl_minutes': 10}
        )
        self.assertIn('123456', html)
        self.assertIn('123456', text)
        self.assertTrue(subject)
        self.assertIn('10', text)  # ttl appears in the copy

    def test_unknown_template_raises(self):
        with self.assertRaises(UnknownTemplate):
            render_template('does_not_exist', {})
