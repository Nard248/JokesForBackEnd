# Phase 9: Daily Joke - Research

**Researched:** 2026-01-11
**Domain:** Django scheduled tasks, recommendation algorithms, push notifications
**Confidence:** HIGH

<research_summary>
## Summary

Researched the ecosystem for implementing a personalized "Joke of the Day" feature with scheduled delivery and basic recommendations. The standard approach uses Django Celery Beat for scheduling, a hybrid content-based + popularity recommendation algorithm for MVP, and OneSignal for push notifications.

Key finding: For an MVP with a small dataset (100-200 jokes), collaborative filtering (Surprise library) is overkill and suffers from the cold start problem. A simpler content-based filtering approach using existing UserPreference data (preferred_tones, preferred_contexts, preferred_age_rating) combined with popularity signals is more practical and avoids dependency complexity.

**Primary recommendation:** Use Django Celery Beat + Redis for scheduling, implement content-based filtering using UserPreference matches, defer true collaborative filtering until user interaction data accumulates, and use OneSignal for cross-platform push notifications.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| celery | 5.6.2 | Distributed task queue | Industry standard for Django async tasks |
| django-celery-beat | 2.8.1 | Database-backed periodic tasks | Official extension, admin UI for schedules |
| redis | 7.1.0 | Message broker + result backend | Fast, reliable, commonly paired with Celery |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| django-celery-results | 2.5.1 | Store task results in Django ORM | If you need to query task history |
| flower | 2.0.1 | Celery monitoring UI | For debugging and production monitoring |
| onesignal-python-api | 2.x | OneSignal REST API client | If using OneSignal for push notifications |
| scikit-surprise | 1.1.4 | Collaborative filtering | Future: when you have enough rating data |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Celery Beat | Django-Q | Simpler setup, but less ecosystem support |
| Redis | RabbitMQ | More features, but more complex for small scale |
| Content-based | Surprise CF | CF better with more data, but cold start for MVP |
| OneSignal | Firebase FCM | FCM is free but requires more setup, less analytics |

**Installation:**
```bash
pip install celery redis django-celery-beat django-celery-results flower
# Optional for future:
pip install scikit-surprise onesignal-python-api
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
JokesForProject/
├── celery.py                 # Celery app configuration
├── jokes/
│   ├── tasks.py             # Celery tasks (generate_daily_jokes, send_notifications)
│   ├── recommendations.py    # Recommendation algorithm
│   ├── models.py            # Add DailyJoke, JokeDelivery models
│   └── services/
│       └── daily_joke.py    # Business logic for joke selection
```

### Pattern 1: Celery App Configuration
**What:** Standard celery.py setup in project root
**When to use:** Always for Django + Celery
**Example:**
```python
# JokesForProject/celery.py
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'JokesForProject.settings')

app = Celery('JokesForProject')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### Pattern 2: Content-Based Recommendation for Cold Start
**What:** Match jokes to user preferences without needing interaction history
**When to use:** MVP with small dataset, new users, before collaborative filtering is viable
**Example:**
```python
# jokes/recommendations.py
from django.db.models import Count, Q

def get_personalized_joke(user, exclude_joke_ids=None):
    """
    Content-based filtering using UserPreference.
    Returns a joke matching user's preferences, avoiding recently shown.
    """
    prefs = user.preference
    exclude_ids = exclude_joke_ids or []

    # Build preference-based filter
    filters = Q()
    if prefs.preferred_tones.exists():
        filters &= Q(tones__in=prefs.preferred_tones.all())
    if prefs.preferred_contexts.exists():
        filters &= Q(context_tags__in=prefs.preferred_contexts.all())
    if prefs.preferred_age_rating:
        filters &= Q(age_rating=prefs.preferred_age_rating)
    if prefs.preferred_language:
        filters &= Q(language=prefs.preferred_language)

    # Query with exclusions and preference matching
    jokes = Joke.objects.exclude(id__in=exclude_ids)
    if filters:
        jokes = jokes.filter(filters).distinct()

    # Fallback to popularity if no preference matches
    if not jokes.exists():
        jokes = Joke.objects.exclude(id__in=exclude_ids)

    # Order by popularity (saved count) with randomness
    return jokes.annotate(
        save_count=Count('saved_by')
    ).order_by('-save_count', '?').first()
```

### Pattern 3: Periodic Task with django-celery-beat
**What:** Database-backed scheduled task for daily joke generation
**When to use:** When you need admin-manageable schedules
**Example:**
```python
# jokes/tasks.py
from celery import shared_task
from django.utils import timezone

@shared_task
def generate_daily_jokes():
    """
    Run daily (e.g., 00:01 UTC) to pre-generate daily jokes for all users.
    """
    from jokes.models import DailyJoke
    from jokes.recommendations import get_personalized_joke
    from django.contrib.auth import get_user_model

    User = get_user_model()
    today = timezone.now().date()

    for user in User.objects.filter(preference__onboarding_completed=True):
        # Get jokes already shown to this user
        shown_ids = DailyJoke.objects.filter(
            user=user
        ).values_list('joke_id', flat=True)

        joke = get_personalized_joke(user, exclude_joke_ids=list(shown_ids))
        if joke:
            DailyJoke.objects.update_or_create(
                user=user,
                date=today,
                defaults={'joke': joke}
            )
```

### Anti-Patterns to Avoid
- **Computing daily jokes on-demand:** Pre-generate at night to avoid latency spikes
- **Running beat and worker in same process:** Always separate processes
- **Hardcoding schedules in code:** Use django-celery-beat for admin-manageable schedules
- **Not excluding shown jokes:** Users will see repeats quickly with small dataset
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Task scheduling | Custom cron/threading | Celery Beat | Reliability, retries, monitoring, distributed |
| Collaborative filtering | Custom matrix factorization | Surprise (later) | Edge cases, performance, tested algorithms |
| Push notifications | Direct APNS/FCM calls | OneSignal | Token management, cross-platform, analytics |
| Job queue | Database polling | Redis + Celery | Performance, reliability, backpressure |
| Recommendation ranking | Simple random | Preference scoring + popularity | Better UX even with basic algorithm |

**Key insight:** Scheduling and notifications are infrastructure problems with battle-tested solutions. Focus implementation effort on the recommendation logic (the business differentiator), not on reinventing job queues or notification delivery.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Cold Start Problem
**What goes wrong:** New users or new jokes get poor recommendations
**Why it happens:** Collaborative filtering needs interaction history
**How to avoid:** Start with content-based filtering (user preferences); hybrid approach adds CF signals later
**Warning signs:** New user gets random/unpopular jokes, new jokes never recommended

### Pitfall 2: Running Multiple Beat Schedulers
**What goes wrong:** Tasks run multiple times (duplicate daily jokes, duplicate notifications)
**Why it happens:** Multiple Celery Beat processes in deployment
**How to avoid:** Use systemd or supervisor to ensure exactly ONE beat process
**Warning signs:** Users report getting multiple daily jokes, task logs show duplicates

### Pitfall 3: Timezone Confusion
**What goes wrong:** Daily jokes delivered at wrong time, users in different timezones get jokes at midnight UTC
**Why it happens:** Not handling user timezones in notification scheduling
**How to avoid:** Store notification_time with user's timezone, group users by timezone for batch sends
**Warning signs:** Users complain about 3am notifications

### Pitfall 4: Joke Exhaustion
**What goes wrong:** Users see repeats quickly, "no more jokes" error
**Why it happens:** Small dataset (100-200 jokes) exhausted by exclusion logic
**How to avoid:** Track recency window (e.g., exclude last 30 days), not all-time shown
**Warning signs:** DailyJoke.joke is None, users report seeing same jokes

### Pitfall 5: Push Notification Token Management
**What goes wrong:** Notifications fail silently, unsubscribed users still in queue
**Why it happens:** Not handling token invalidation, device changes
**How to avoid:** Use OneSignal (handles token lifecycle), or implement webhook for failed deliveries
**Warning signs:** Low delivery rates, growing invalid token list
</common_pitfalls>

<code_examples>
## Code Examples

Verified patterns from official sources:

### DailyJoke Model
```python
# jokes/models.py
class DailyJoke(models.Model):
    """Track daily joke delivered to each user"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='daily_jokes'
    )
    joke = models.ForeignKey(
        Joke,
        on_delete=models.CASCADE,
        related_name='daily_deliveries'
    )
    date = models.DateField()
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [['user', 'date']]
        ordering = ['-date']
        indexes = [
            models.Index(fields=['user', 'date']),
        ]
```

### Settings Configuration for Celery
```python
# settings.py
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

INSTALLED_APPS += [
    'django_celery_beat',
    'django_celery_results',
]
```

### API Endpoint for Daily Joke
```python
# jokes/views.py
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

class DailyJokeViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def today(self, request):
        """Get today's personalized joke"""
        today = timezone.now().date()
        daily = DailyJoke.objects.filter(
            user=request.user,
            date=today
        ).select_related('joke').first()

        if not daily:
            # Fallback: generate on-demand if scheduled task missed
            from jokes.recommendations import get_personalized_joke
            shown_ids = DailyJoke.objects.filter(
                user=request.user
            ).values_list('joke_id', flat=True)
            joke = get_personalized_joke(request.user, list(shown_ids))
            if joke:
                daily = DailyJoke.objects.create(
                    user=request.user,
                    joke=joke,
                    date=today
                )

        if daily:
            return Response(JokeSerializer(daily.joke).data)
        return Response({'detail': 'No joke available'}, status=404)
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| crontab | Celery Beat | 2015+ | Reliable distributed scheduling with retries |
| Celery 4.x | Celery 5.6 | 2024 | Python 3.9+ required, better async support |
| Redis 6.x | Redis 7.x | 2024 | Streams, functions, improved performance |
| GCM | FCM v1 API | 2023+ | Old GCM deprecated, new auth model |
| Manual CF | LightFM, Surprise | 2020+ | Production-ready collaborative filtering |

**New tools/patterns to consider:**
- **Django-RQ:** Simpler alternative to Celery for smaller projects (not recommended for this project due to existing complexity)
- **Celery Flower 2.0:** Modern monitoring UI with async support
- **OneSignal Journeys:** Automated notification sequences (potential for onboarding)

**Deprecated/outdated:**
- **Celery 4.x:** End of life, upgrade to 5.6+
- **GCM (Google Cloud Messaging):** Replaced by FCM
- **django-celery (old package):** Merged into Celery, use django-celery-beat/results instead
</sota_updates>

<open_questions>
## Open Questions

Things that couldn't be fully resolved:

1. **Notification Time Grouping**
   - What we know: Users have notification_time preference, but timezones not stored
   - What's unclear: How to efficiently batch notifications across timezones
   - Recommendation: For MVP, assume single timezone (or ask during onboarding); add timezone field to UserPreference later

2. **Joke Exhaustion Strategy**
   - What we know: 100-200 jokes, users who engage daily will see repeats
   - What's unclear: Optimal recency window before allowing repeat
   - Recommendation: Start with 30-day recency window; if user exhausts pool, reset and notify

3. **Push Notification Infrastructure Scope**
   - What we know: Roadmap says "optional for MVP"
   - What's unclear: Whether to implement full push or just the model/scheduler infrastructure
   - Recommendation: Implement models and Celery tasks; defer actual push integration (OneSignal) to post-MVP
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [django-celery-beat documentation](https://django-celery-beat.readthedocs.io/) - periodic tasks setup
- [Celery 5.6 documentation](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html) - beat scheduler
- [TestDriven.io Django Celery Guide](https://testdriven.io/blog/django-celery-periodic-tasks/) - production patterns
- [Real Python Collaborative Filtering](https://realpython.com/build-recommendation-engine-collaborative-filtering/) - Surprise library usage
- [Surprise Library Documentation](https://surprise.readthedocs.io/) - algorithm details

### Secondary (MEDIUM confidence)
- [OneSignal Django Integration](https://medium.com/django-unleashed/sending-push-notifications-in-django-rest-framework-with-onesignal-a27c1a970eb2) - OneSignal setup patterns
- [Cold Start Problem Solutions](https://www.expressanalytics.com/blog/cold-start-problem) - hybrid approach strategies
- [Celery Redis Setup](https://saadali18.medium.com/setup-your-django-project-with-celery-celery-beat-and-redis-644dc8a2ac4b) - configuration patterns

### Tertiary (LOW confidence - needs validation)
- onesignal-python-api package version needs verification on PyPI
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Django Celery Beat, Redis
- Ecosystem: Celery, django-celery-beat, django-celery-results, flower
- Patterns: Content-based filtering, periodic tasks, hybrid recommendations
- Pitfalls: Cold start, duplicate scheduling, timezone handling, joke exhaustion

**Confidence breakdown:**
- Standard stack: HIGH - all packages actively maintained, Django 5.x compatible
- Architecture: HIGH - patterns from official Celery docs and production guides
- Pitfalls: HIGH - documented in multiple sources, verified against roadmap scope
- Code examples: MEDIUM - patterns verified, specific implementation will vary

**Research date:** 2026-01-11
**Valid until:** 2026-02-11 (30 days - Celery ecosystem stable)
</metadata>

---

*Phase: 09-daily-joke*
*Research completed: 2026-01-11*
*Ready for planning: yes*
