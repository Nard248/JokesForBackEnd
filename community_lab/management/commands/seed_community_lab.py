import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from community_lab.models import Content, DemoState, Event, Membership, Participant, Subject
from community_lab.seed_data import JOKES, SUBJECTS
from community_lab.snapshot import build_snapshot


class Command(BaseCommand):
    help = "Seed only the isolated community lab with synthetic participants and original jokes."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Replace the synthetic demo dataset.")

    @transaction.atomic
    def handle(self, *args, **options):
        if (getattr(settings, "COMMUNITY_LAB_ENABLED", False) is not True
                or getattr(settings, "SETTINGS_MODULE", "") != "community_lab.settings"):
            raise CommandError("Seeding requires the isolated community_lab.settings module.")
        if DemoState.objects.exists() and not options["reset"]:
            self.stdout.write("Community demo is already seeded; preserving its activity. Use --reset to replace synthetic data.")
            return
        # Every table here belongs exclusively to community_lab, never a production app.
        Event.objects.all().delete()
        Membership.objects.all().delete()
        Content.objects.all().delete()
        Subject.objects.all().delete()
        Participant.objects.all().delete()
        DemoState.objects.all().delete()
        now = timezone.now().replace(microsecond=0)
        state = DemoState.objects.create(simulated_at=now)
        Subject.objects.bulk_create([Subject(id=sid, name=name, description=description,
            color=color, emoji=emoji, order=index) for index, (sid, name, description, color, emoji) in enumerate(SUBJECTS)])
        Participant.objects.bulk_create([Participant(id="demo-you", name="You (demo)")] + [
            Participant(id=f"p{i:04}", name=f"Synthetic neighbor {i:04}") for i in range(1, 1600)])
        contents = []
        for sid, name, *_ in SUBJECTS:
            for index, line in enumerate(JOKES[sid].strip().splitlines()):
                title, punchline = line.split("|", 1)
                contents.append(Content(id=f"{sid}-{index + 1:02}", subject_id=sid,
                    title=title.strip(), punchline=punchline.strip(), creator=f"Demo studio · {name}"))
        Content.objects.bulk_create(contents)
        rng = random.Random(2047)
        events = []
        main_subjects = [row[0] for row in SUBJECTS[:-1]]

        def signal(actor, subject, number, kind, days, parent=None):
            item = Event(actor_id=actor, subject_id=subject, content_id=f"{subject}-{number:02}", kind=kind,
                occurred_at=now - timedelta(days=days), parent=parent)
            events.append(item)
            return item

        for i in range(1, 1501):
            actor = f"p{i:04}"
            primary = main_subjects[i % len(main_subjects)]
            interests = [primary]
            if i % 3 == 0:
                interests.append(main_subjects[(i + 3) % len(main_subjects)])
            if i % 11 == 0:
                interests.append(main_subjects[(i + 5) % len(main_subjects)])
            for subject in interests:
                numbers = rng.sample(range(1, 25), 3)
                recent = rng.uniform(0.015, 1.8)
                signal(actor, subject, numbers[0], "view", recent + 0.002)
                signal(actor, subject, numbers[0], "like", recent)
                signal(actor, subject, numbers[1], "save", recent - 0.003)
                signal(actor, subject, numbers[2], "save", recent - 0.008)
                # A distinct earlier population gives seven-day growth a real baseline.
                if i % 5 != 0:
                    signal(actor, subject, numbers[0], "save", 8.5)
                    signal(actor, subject, numbers[1], "save", 8.4)
            if i % 4 == 0:
                days = rng.uniform(0.2, 5.5)
                parent = signal(actor, primary, 1, "share", days)
                friend = f"p{(i % 1500) + 1:04}"
                signal(friend, primary, 1, "view", days - 0.002, parent)
                signal(friend, primary, 1, "like", days - 0.003, parent)
                signal(friend, primary, 2, "save", days - 0.005, parent)
        for subject in ("tech", "work"):
            signal("demo-you", subject, 1, "save", 0.2)
            signal("demo-you", subject, 2, "save", 0.2)
        # This rare community starts at three engaged people; a share can activate it.
        for i in (1597, 1598, 1599):
            signal(f"p{i:04}", "space", 1, "save", 0.05)
            signal(f"p{i:04}", "space", 2, "save", 0.05)
        Event.objects.bulk_create(events, batch_size=1000)
        result = build_snapshot(state)
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {result['stats']['participants']:,} synthetic participants, {len(contents)} original jokes, "
            f"{len(events):,} persisted events and {len(SUBJECTS)} canonical subjects. "
            f"{result['stats']['active_communities']} active; Space oddities begins forming."))
