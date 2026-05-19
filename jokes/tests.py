from django.test import SimpleTestCase

from jokes.submission_rules import FORMAT_RULES, validate_per_format


class FormatRulesTests(SimpleTestCase):
    def test_all_six_format_slugs_present(self):
        self.assertEqual(
            set(FORMAT_RULES.keys()),
            {'oneliner', 'setup', 'knock', 'story', 'anti', 'observ'},
        )

    # oneliner
    def test_oneliner_valid(self):
        self.assertEqual(validate_per_format('oneliner', {'text': 'A short joke.'}), {})

    def test_oneliner_missing_text(self):
        errs = validate_per_format('oneliner', {'text': ''})
        self.assertIn('text', errs)

    def test_oneliner_rejects_setup(self):
        errs = validate_per_format('oneliner', {'text': 'A.', 'setup': 'B.'})
        self.assertIn('setup', errs)

    # setup-punchline
    def test_setup_valid(self):
        self.assertEqual(
            validate_per_format('setup', {'setup': 'Why?', 'punchline': 'Because.'}),
            {},
        )

    def test_setup_missing_punchline(self):
        errs = validate_per_format('setup', {'setup': 'Why?', 'punchline': ''})
        self.assertIn('punchline', errs)

    def test_setup_rejects_lines(self):
        errs = validate_per_format(
            'setup', {'setup': 'A.', 'punchline': 'B.', 'lines': ['x', 'y']}
        )
        self.assertIn('lines', errs)

    # knock
    def test_knock_valid(self):
        self.assertEqual(
            validate_per_format(
                'knock',
                {'lines': ['Knock, knock.', "Who's there?", 'Olive.', 'Olive who?']},
            ),
            {},
        )

    def test_knock_too_few_lines(self):
        errs = validate_per_format('knock', {'lines': ['A.', 'B.']})
        self.assertIn('lines', errs)

    def test_knock_too_many_lines(self):
        errs = validate_per_format('knock', {'lines': ['x'] * 9})
        self.assertIn('lines', errs)

    def test_knock_line_too_long(self):
        errs = validate_per_format(
            'knock', {'lines': ['A.', 'B.', 'C.', 'x' * 201]}
        )
        self.assertIn('lines', errs)

    def test_knock_lines_not_a_list(self):
        errs = validate_per_format('knock', {'lines': 'not a list'})
        self.assertIn('lines', errs)

    def test_knock_empty_line_rejected(self):
        errs = validate_per_format(
            'knock', {'lines': ['A.', '', 'C.', 'D.']}
        )
        self.assertIn('lines', errs)

    def test_knock_rejects_text(self):
        errs = validate_per_format(
            'knock',
            {'lines': ['A.', 'B.', 'C.', 'D.'], 'text': 'oops'},
        )
        self.assertIn('text', errs)

    # story
    def test_story_valid(self):
        long_text = ' '.join(['word'] * 35)
        self.assertEqual(validate_per_format('story', {'text': long_text}), {})

    def test_story_too_short(self):
        errs = validate_per_format('story', {'text': 'Too short.'})
        self.assertIn('text', errs)

    # anti
    def test_anti_valid(self):
        self.assertEqual(
            validate_per_format('anti', {'setup': 'A.', 'punchline': 'B.'}),
            {},
        )

    def test_anti_missing_setup(self):
        errs = validate_per_format('anti', {'setup': '', 'punchline': 'B.'})
        self.assertIn('setup', errs)

    # observational
    def test_observ_valid(self):
        self.assertEqual(
            validate_per_format('observ', {'text': 'Have you ever noticed...'}),
            {},
        )

    def test_observ_missing_text(self):
        errs = validate_per_format('observ', {'text': ''})
        self.assertIn('text', errs)

    # unknown
    def test_unknown_format_slug(self):
        errs = validate_per_format('bogus', {'text': 'x'})
        self.assertIn('format', errs)
