"""Tests for the follows app: services, views, serializer safety."""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from follows.models import Follow
from follows import services

User = get_user_model()


def _user(n):
    return User.objects.create_user(
        username=f'follow_u{n}@test.com',
        email=f'follow_u{n}@test.com',
        password='x',
    )


class FollowServicesTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.u1 = _user(1)
        cls.u2 = _user(2)

    def test_follow_creates_row(self):
        follow_obj, created = services.follow(self.u1, self.u2)
        self.assertTrue(created)
        self.assertTrue(Follow.objects.filter(follower=self.u1, creator=self.u2).exists())

    def test_follow_idempotent(self):
        services.follow(self.u1, self.u2)
        _, created2 = services.follow(self.u1, self.u2)
        self.assertFalse(created2)
        self.assertEqual(Follow.objects.filter(follower=self.u1, creator=self.u2).count(), 1)

    def test_unfollow_removes_row(self):
        services.follow(self.u1, self.u2)
        services.unfollow(self.u1, self.u2)
        self.assertFalse(Follow.objects.filter(follower=self.u1, creator=self.u2).exists())

    def test_unfollow_idempotent(self):
        services.unfollow(self.u1, self.u2)  # should not raise

    def test_self_follow_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            services.follow(self.u1, self.u1)

    def test_follower_count(self):
        services.follow(self.u1, self.u2)
        self.assertEqual(services.follower_count(self.u2), 1)

    def test_is_following_true(self):
        services.follow(self.u1, self.u2)
        self.assertTrue(services.is_following(self.u1, self.u2))

    def test_is_following_false(self):
        self.assertFalse(services.is_following(self.u1, self.u2))

    def tearDown(self):
        Follow.objects.all().delete()


class FollowViewTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.follower = _user(10)
        cls.creator = _user(11)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.follower)
        Follow.objects.all().delete()

    def test_post_follow_returns_201(self):
        url = reverse('follow', kwargs={'creator_id': self.creator.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['is_following'])
        self.assertIn('follower_count', response.data)

    def test_post_follow_twice_returns_200(self):
        url = reverse('follow', kwargs={'creator_id': self.creator.pk})
        self.client.post(url)
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_unfollow_returns_204(self):
        services.follow(self.follower, self.creator)
        url = reverse('follow', kwargs={'creator_id': self.creator.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Follow.objects.filter(follower=self.follower, creator=self.creator).exists())

    def test_post_self_follow_returns_400(self):
        url = reverse('follow', kwargs={'creator_id': self.follower.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        url = reverse('follow', kwargs={'creator_id': self.creator.pk})
        response = client.post(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_nonexistent_creator_returns_404(self):
        url = reverse('follow', kwargs={'creator_id': 999999})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class FollowStatusViewTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.follower = _user(20)
        cls.creator = _user(21)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.follower)
        Follow.objects.all().delete()

    def test_status_not_following(self):
        url = reverse('follow-status', kwargs={'creator_id': self.creator.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_following'])
        self.assertEqual(response.data['follower_count'], 0)

    def test_status_following(self):
        services.follow(self.follower, self.creator)
        url = reverse('follow-status', kwargs={'creator_id': self.creator.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_following'])
        self.assertEqual(response.data['follower_count'], 1)

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        url = reverse('follow-status', kwargs={'creator_id': self.creator.pk})
        response = client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class FollowersListViewTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.follower1 = _user(30)
        cls.follower2 = _user(31)
        cls.creator = _user(32)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.follower1)
        Follow.objects.all().delete()

    def test_followers_list_returns_paginated(self):
        services.follow(self.follower1, self.creator)
        services.follow(self.follower2, self.creator)
        url = reverse('follow-followers', kwargs={'creator_id': self.creator.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)

    def test_followers_list_no_email_in_response(self):
        services.follow(self.follower1, self.creator)
        url = reverse('follow-followers', kwargs={'creator_id': self.creator.pk})
        response = self.client.get(url)
        for user_data in response.data['results']:
            self.assertNotIn('email', user_data)
            self.assertIn('id', user_data)
            self.assertIn('name', user_data)
            self.assertIn('username', user_data)

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        url = reverse('follow-followers', kwargs={'creator_id': self.creator.pk})
        response = client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MyFollowingViewTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.follower = _user(40)
        cls.creator1 = _user(41)
        cls.creator2 = _user(42)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.follower)
        Follow.objects.all().delete()

    def test_my_following_list(self):
        services.follow(self.follower, self.creator1)
        services.follow(self.follower, self.creator2)
        url = reverse('my-following')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)

    def test_my_following_no_email_in_response(self):
        services.follow(self.follower, self.creator1)
        url = reverse('my-following')
        response = self.client.get(url)
        for user_data in response.data['results']:
            self.assertNotIn('email', user_data)
            self.assertIn('id', user_data)
            self.assertIn('username', user_data)

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        url = reverse('my-following')
        response = client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_following_list(self):
        url = reverse('my-following')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
