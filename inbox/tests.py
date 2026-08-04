"""Tests for in-app notifications (inbox)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from follows import services as follow_services
from inbox.models import Notification
from inbox.services import notify

User = get_user_model()

LIST_URL = '/api/v1/notifications/'
UNREAD_URL = '/api/v1/notifications/unread-count/'
MARK_URL = '/api/v1/notifications/mark-read/'


class NotifyServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user(username='a@t.com', email='a@t.com', password='x')
        cls.b = User.objects.create_user(username='b@t.com', email='b@t.com', password='x')

    def test_notify_creates_row(self):
        n = notify(self.a, 'followed_you', actor=self.b)
        self.assertIsNotNone(n)
        self.assertEqual(Notification.objects.filter(recipient=self.a).count(), 1)

    def test_notify_self_is_noop(self):
        self.assertIsNone(notify(self.a, 'followed_you', actor=self.a))
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_none_recipient_is_noop(self):
        self.assertIsNone(notify(None, 'joke_removed'))


class NotifyPayloadTests(TestCase):
    """notify(**extra) lands in Notification.data; old-style calls stay valid."""

    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user(username='pa@t.com', email='pa@t.com', password='x')
        cls.b = User.objects.create_user(username='pb@t.com', email='pb@t.com', password='x')

    def test_notify_stores_extra_kwargs_in_data(self):
        n = notify(
            self.a, 'joke_removed',
            reason='spam', appeal_deadline='2026-08-07T00:00:00+00:00',
        )
        self.assertEqual(
            n.data,
            {'reason': 'spam', 'appeal_deadline': '2026-08-07T00:00:00+00:00'},
        )

    def test_old_style_notify_defaults_to_empty_data(self):
        n = notify(self.a, 'followed_you', actor=self.b)
        self.assertEqual(n.data, {})

    def test_serializer_exposes_data(self):
        notify(self.a, 'joke_removed', reason='harassment', appeal_deadline='2026-08-07')
        client = APIClient()
        client.force_authenticate(self.a)
        resp = client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        row = resp.data['results'][0]
        self.assertEqual(
            row['data'], {'reason': 'harassment', 'appeal_deadline': '2026-08-07'},
        )

    def test_serializer_exposes_empty_data_for_old_style_notification(self):
        notify(self.a, 'followed_you', actor=self.b)
        client = APIClient()
        client.force_authenticate(self.a)
        resp = client.get(LIST_URL)
        self.assertEqual(resp.data['results'][0]['data'], {})


class FollowCreatesNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.follower = User.objects.create_user(username='f@t.com', email='f@t.com', password='x')
        cls.creator = User.objects.create_user(username='c@t.com', email='c@t.com', password='x')

    def test_follow_notifies_creator(self):
        follow_services.follow(self.follower, self.creator)
        n = Notification.objects.get(recipient=self.creator)
        self.assertEqual(n.verb, 'followed_you')
        self.assertEqual(n.actor_id, self.follower.pk)

    def test_repeat_follow_does_not_duplicate(self):
        follow_services.follow(self.follower, self.creator)
        follow_services.follow(self.follower, self.creator)  # idempotent
        self.assertEqual(Notification.objects.filter(recipient=self.creator).count(), 1)


class NotificationEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='u@t.com', email='u@t.com', password='x')
        cls.other = User.objects.create_user(username='o@t.com', email='o@t.com', password='x')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_list_only_own_notifications(self):
        notify(self.user, 'followed_you', actor=self.other)
        notify(self.other, 'followed_you', actor=self.user)  # not mine
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['verb'], 'followed_you')
        self.assertEqual(resp.data['results'][0]['actor']['id'], self.other.pk)

    def test_actor_identity_has_no_email(self):
        notify(self.user, 'followed_you', actor=self.other)
        resp = self.client.get(LIST_URL)
        self.assertNotIn('o@t.com', resp.content.decode())

    def test_unread_count_and_mark_read(self):
        notify(self.user, 'followed_you', actor=self.other)
        notify(self.user, 'followed_you', actor=self.other)
        self.assertEqual(self.client.get(UNREAD_URL).data['count'], 2)
        marked = self.client.post(MARK_URL)
        self.assertEqual(marked.data['marked'], 2)
        self.assertEqual(self.client.get(UNREAD_URL).data['count'], 0)

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)
