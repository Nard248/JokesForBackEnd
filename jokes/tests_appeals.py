"""Appeals-wave Task 1 tests: Appeal model constraints, rejection-transition
notice, and reasoned takedown notice payload."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.contrib.messages.storage.fallback import FallbackStorage

from inbox.models import Notification
from jokes.admin import ContentReportAdmin
from jokes.models import Appeal, ContentReport, Joke, JokeSubmission
from jokes.tests_media import make_user, _taxonomy


def _admin_request(user):
    req = RequestFactory().post('/')
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def _make_joke(fmt, age, lang, creator, is_removed=False):
    with patch('jokes.models.Joke._generate_share_image'):
        return Joke.objects.create(
            text='Test', format=fmt, age_rating=age, language=lang,
            content_tier='tier_1', creator=creator, is_removed=is_removed,
        )


def _make_submission(user, fmt, age, lang, status='draft'):
    return JokeSubmission.objects.create(
        user=user, format=fmt, age_rating=age, language=lang,
        text='Test submission', status=status,
    )


class AppealTargetConstraintTests(TestCase):
    """Exactly one of joke/submission must be set (DB check constraint)."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('appellant@example.com')
        self.joke = _make_joke(self.fmt, self.age, self.lang, creator=self.user, is_removed=True)
        self.submission = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')

    def test_both_targets_set_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, joke=self.joke, submission=self.submission,
                    action_type='takedown', reason_text='please review',
                )

    def test_neither_target_set_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, action_type='takedown', reason_text='please review',
                )

    def test_joke_only_is_valid(self):
        appeal = Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='please review',
        )
        self.assertIsNone(appeal.submission)

    def test_submission_only_is_valid(self):
        appeal = Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection',
            reason_text='please review',
        )
        self.assertIsNone(appeal.joke)


class AppealSingleOpenPerTargetTests(TestCase):
    """At most one PENDING appeal per (user, joke) or (user, submission)."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('appellant2@example.com')
        self.joke = _make_joke(self.fmt, self.age, self.lang, creator=self.user, is_removed=True)
        self.submission = _make_submission(self.user, self.fmt, self.age, self.lang, status='rejected')

    def test_second_pending_appeal_on_same_joke_raises(self):
        Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='first',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, joke=self.joke, action_type='takedown', reason_text='second',
                )

    def test_second_pending_appeal_on_same_submission_raises(self):
        Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection', reason_text='first',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appeal.objects.create(
                    user=self.user, submission=self.submission, action_type='rejection', reason_text='second',
                )

    def test_resolved_appeal_allows_new_pending_on_joke(self):
        first = Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='first',
        )
        first.status = 'upheld'
        first.save(update_fields=['status'])
        second = Appeal.objects.create(
            user=self.user, joke=self.joke, action_type='takedown', reason_text='second',
        )
        self.assertEqual(second.status, 'pending')

    def test_resolved_appeal_allows_new_pending_on_submission(self):
        first = Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection', reason_text='first',
        )
        first.status = 'reversed'
        first.save(update_fields=['status'])
        second = Appeal.objects.create(
            user=self.user, submission=self.submission, action_type='rejection', reason_text='second',
        )
        self.assertEqual(second.status, 'pending')


class RejectionNoticeTests(TestCase):
    """A submission transitioning to 'rejected' notifies the author exactly
    once, with the rejection_reason in the notification payload."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('rejectee@example.com')

    def _rejected_notices(self):
        return Notification.objects.filter(recipient=self.user, verb='joke_rejected')

    def test_draft_to_rejected_fires_notice_once_with_reason(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='draft')
        sub.status = 'rejected'
        sub.rejection_reason = 'Duplicate of an existing joke'
        sub.save()
        notices = self._rejected_notices()
        self.assertEqual(notices.count(), 1)
        self.assertEqual(
            notices.get().data.get('rejection_reason'), 'Duplicate of an existing joke',
        )

    def test_saving_again_while_rejected_does_not_duplicate(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='draft')
        sub.status = 'rejected'
        sub.rejection_reason = 'Too long'
        sub.save()
        sub.text = 'Edited while rejected'
        sub.save()
        self.assertEqual(self._rejected_notices().count(), 1)

    def test_pending_to_published_fires_no_rejection_notice(self):
        sub = _make_submission(self.user, self.fmt, self.age, self.lang, status='pending')
        sub.status = 'published'
        sub.save()
        self.assertEqual(self._rejected_notices().count(), 0)


class TakedownNoticeTests(TestCase):
    """take_down_joke's joke_removed notice carries the most common triggering
    report reason and the 14-day appeal deadline (ISO)."""

    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.creator = make_user('takendown@example.com')
        self.admin_user = make_user('mod@example.com')
        self.admin_obj = ContentReportAdmin(ContentReport, AdminSite())

    def _report(self, joke, reason, n):
        reporter = make_user(f'reporter{n}@example.com')
        return ContentReport.objects.create(
            reporter=reporter, joke=joke, reason=reason, status='pending',
        )

    def test_notice_carries_most_common_reason_and_deadline(self):
        joke = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        self._report(joke, 'spam', 1)
        self._report(joke, 'spam', 2)
        self._report(joke, 'harassment', 3)
        self.admin_obj.take_down_joke(
            _admin_request(self.admin_user), ContentReport.objects.filter(joke=joke),
        )
        notice = Notification.objects.get(recipient=self.creator, verb='joke_removed')
        self.assertEqual(notice.joke_id, joke.pk)
        self.assertEqual(notice.data['reason'], 'spam')
        removed_at = Joke.all_objects.get(pk=joke.pk).removed_at
        self.assertEqual(
            notice.data['appeal_deadline'], (removed_at + timedelta(days=14)).isoformat(),
        )

    def test_reason_is_grouped_per_joke(self):
        joke_a = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        joke_b = _make_joke(self.fmt, self.age, self.lang, creator=self.creator)
        self._report(joke_a, 'spam', 4)
        self._report(joke_b, 'copyright', 5)
        self.admin_obj.take_down_joke(
            _admin_request(self.admin_user),
            ContentReport.objects.filter(joke__in=[joke_a, joke_b]),
        )
        notice_a = Notification.objects.get(
            recipient=self.creator, verb='joke_removed', joke=joke_a,
        )
        notice_b = Notification.objects.get(
            recipient=self.creator, verb='joke_removed', joke=joke_b,
        )
        self.assertEqual(notice_a.data['reason'], 'spam')
        self.assertEqual(notice_b.data['reason'], 'copyright')
