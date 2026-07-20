# Media Jokes Wave 1 — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Image jokes (setup teaser + 1–6 image punchline) end-to-end on the backend — upload pipeline, format registry, locking contract, moderation/deletion lifecycle, and the anonymous paywall — per the approved spec `Docs/superpowers/specs/2026-07-20-media-jokes-design.md`.

**Architecture:** A user-owned `MediaAsset` model (UUID pk) + ordered through-models to `JokeSubmission`/`Joke`; a synchronous in-request image pipeline (Pillow validate → re-encode/EXIF-strip → dHash → SafeSearch → GCS via existing STORAGES); `image` joins `FORMAT_RULES` so the whole draft→submit→review→publish machinery picks it up; locking strips media URLs server-side; anon paywall is a signed-cookie ledger mirroring the JokeView ledger.

**Tech Stack:** Django 5.2 + DRF, Pillow (newly pinned), google-cloud-vision (new), django-storages/GCS (existing), freezegun for time tests.

## Global Constraints

- Single Cloud Run app. Everything request-triggered. NO Celery/cron/workers/threads.
- Tests: Django test runner, NEVER pytest. Run with local Postgres: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test <target> --keepdb` (empty `DATABASE_URL` forces the `DB_*` local fallback: db `jokesfor`, user `postgres`, pw `6969`, localhost).
- Commit messages: plain, descriptive. NO `Co-Authored-By`, NO "Generated with", no emoji footers.
- Image caps (spec §5.1): JPEG/PNG/WEBP only, ≤10MB, ≤4096px source; derivative max 1600px longest edge, WebP quality 82. EXIF stripped by re-encode.
- Image format rule (spec §6.1): required `setup`+`media`, forbidden `punchline`+`lines`, 1–6 image attachments.
- Locked media jokes serve `{kind,width,height}` ONLY — no URLs (spec §6.2). `JokeListSerializer` NEVER serves media URLs.
- Anon paywall (spec §8): 10 distinct reveals/day, signed cookie `jf_anon_reads`, midnight-UTC reset, tamper→fresh ledger. Cookie-clearing evasion is accepted.
- Upload throttle scope `media-upload: 30/hour`.
- New tests live in `jokes/tests_media.py` (one file, one class per concern). Follow the `tests_storage.py` pattern: `override_settings(MEDIA_ROOT=tempfile.mkdtemp())` so files land in a temp dir with FileSystemStorage.
- Do not modify: share-card generation, telemetry ingest, `TEXT_ONLY_FORMATS` derivation, the daily-joke paywall exemption.

---

### Task 1: Dependencies + MediaAsset / through-models + deletion helper

**Files:**
- Modify: `requirements.txt`
- Modify: `jokes/models.py` (append a new section at end of file)
- Create: `jokes/migrations/00XX_media_asset.py` (via makemigrations)
- Test: `jokes/tests_media.py` (create)

**Interfaces:**
- Consumes: existing `Joke`, `JokeSubmission` models; `STORAGES['default']`.
- Produces: `MediaAsset(id: UUID, owner, kind: 'image'|'video'|'audio', file, poster, width, height, duration_ms, is_gif, safesearch: dict|None, phash: str, created_at)` with method `delete_with_files() -> None`; `JokeSubmissionMedia(submission, asset, position)` with `related_name='media'` on submission and `related_name='submission_links'` on asset; `JokeMedia(joke, asset, position)` with `related_name='media'` on joke and `related_name='joke_links'` on asset. Both through-models: `Meta.ordering = ['position']`, CASCADE both sides.

- [ ] **Step 1: Pin dependencies**

Append to `requirements.txt` (Pillow is currently only a transitive dep of cairosvg — latent breakage; the exact Pillow pin should match what's already in `.venv`, check with `.venv/bin/pip show pillow`):

```
Pillow==12.1.0
google-cloud-vision==3.10.2
```

Run: `.venv/bin/pip install -r requirements.txt`
Expected: both install cleanly. If `google-cloud-vision==3.10.2` does not exist on PyPI, install `.venv/bin/pip install 'google-cloud-vision~=3.8'` and pin the exact version it resolves (`.venv/bin/pip show google-cloud-vision`).

- [ ] **Step 2: Write the failing model tests**

Create `jokes/tests_media.py`:

```python
"""Tests for media jokes (Wave 1): assets, pipeline, formats, locking, anon paywall."""
import io
import shutil
import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from jokes.models import (
    AgeRating, Format, Joke, JokeMedia, JokeSubmission, JokeSubmissionMedia,
    Language, MediaAsset,
)

User = get_user_model()

_MEDIA_ROOT = tempfile.mkdtemp()


def make_user(email='creator@example.com'):
    return User.objects.create_user(username=email, email=email, password='x')


def make_asset(owner, kind='image', **kwargs):
    asset = MediaAsset(owner=owner, kind=kind, width=800, height=600, **kwargs)
    asset.file.save('image.webp', ContentFile(b'fake-webp-bytes'), save=False)
    asset.save()
    return asset


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaAssetModelTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def test_asset_has_uuid_pk_and_pathed_file(self):
        asset = make_asset(make_user())
        self.assertIsInstance(asset.pk, uuid.UUID)
        self.assertIn(f'media-assets/{asset.pk}/', asset.file.name)

    def test_delete_with_files_removes_storage_objects_and_row(self):
        asset = make_asset(make_user())
        name = asset.file.name
        self.assertTrue(default_storage.exists(name))
        asset.delete_with_files()
        self.assertFalse(default_storage.exists(name))
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())

    def test_asset_delete_cascades_through_links(self):
        user = make_user()
        asset = make_asset(user)
        fmt, _ = Format.objects.get_or_create(slug='image', defaults={'name': 'Image'})
        age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
        lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
        sub = JokeSubmission.objects.create(
            user=user, format=fmt, age_rating=age, language=lang, setup='caption'
        )
        JokeSubmissionMedia.objects.create(submission=sub, asset=asset, position=0)
        asset.delete_with_files()
        self.assertEqual(sub.media.count(), 0)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media --keepdb`
Expected: FAIL — `ImportError: cannot import name 'MediaAsset'`.

- [ ] **Step 4: Implement the models**

Append at the END of `jokes/models.py`:

```python
# =============================================================================
# Media Assets (Wave 1: image jokes; video/audio arrive in Wave 2)
# =============================================================================

def media_asset_path(instance, filename):
    """Unguessable, stable storage path: media-assets/<uuid>/<name>."""
    return f'media-assets/{instance.pk}/{filename}'


class MediaAsset(models.Model):
    """A user-owned uploaded media file (the display derivative, never the
    original). Owned by the USER, not a draft, so uploads may precede draft
    creation. Files live in the default storage (GCS in prod) at UUID paths;
    pre-moderation exposure at unguessable public URLs is an accepted spec
    trade-off (spec §3.3). Deletion must go through delete_with_files() so
    storage objects never orphan (no cron exists to sweep them)."""

    KIND_CHOICES = [('image', 'Image'), ('video', 'Video'), ('audio', 'Audio')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='media_assets',
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    file = models.FileField(upload_to=media_asset_path)
    poster = models.ImageField(upload_to=media_asset_path, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    is_gif = models.BooleanField(default=False)
    safesearch = models.JSONField(null=True, blank=True)
    phash = models.CharField(max_length=32, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def delete_with_files(self):
        """Delete storage objects, then the row (links CASCADE away)."""
        for field_file in (self.file, self.poster):
            if field_file:
                field_file.delete(save=False)
        self.delete()

    def __str__(self):
        return f'{self.kind} asset {self.id} ({self.owner_id})'


class JokeSubmissionMedia(models.Model):
    """Ordered media attachment on a draft/submission."""
    submission = models.ForeignKey(
        JokeSubmission, on_delete=models.CASCADE, related_name='media',
    )
    asset = models.ForeignKey(
        MediaAsset, on_delete=models.CASCADE, related_name='submission_links',
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['submission', 'position'],
                name='uniq_submission_media_position',
            ),
        ]


class JokeMedia(models.Model):
    """Ordered media attachment on a published joke (copied at publish)."""
    joke = models.ForeignKey(
        Joke, on_delete=models.CASCADE, related_name='media',
    )
    asset = models.ForeignKey(
        MediaAsset, on_delete=models.CASCADE, related_name='joke_links',
    )
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['joke', 'position'], name='uniq_joke_media_position',
            ),
        ]
```

Add `import uuid` to the imports at the top of `jokes/models.py` (keep alphabetical placement with the other stdlib imports).

- [ ] **Step 5: Make the migration**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py makemigrations jokes`
Expected: one new migration creating `MediaAsset`, `JokeSubmissionMedia`, `JokeMedia`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media --keepdb`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt jokes/models.py jokes/migrations jokes/tests_media.py
git commit -m "media: MediaAsset + ordered joke/submission attachments with storage-safe deletion"
```

---

### Task 2: Image processing service (validate / re-encode / EXIF-strip / dHash)

**Files:**
- Create: `jokes/media_processing.py`
- Test: `jokes/tests_media.py` (append)

**Interfaces:**
- Consumes: nothing project-specific (pure Pillow).
- Produces: `process_image(uploaded_file) -> ProcessedImage(data: bytes, width: int, height: int, phash: str)`; raises `MediaValidationError(errors: dict[str, str])`. Constants `MAX_IMAGE_BYTES`, `MAX_SOURCE_DIM`, `OUT_MAX_DIM`. Helper `dhash_hex(img, hash_size=8) -> str` (16-hex-char difference hash).

- [ ] **Step 1: Write the failing tests**

Append to `jokes/tests_media.py`:

```python
from PIL import Image

from jokes.media_processing import (
    MAX_IMAGE_BYTES, MediaValidationError, process_image,
)


def make_image_bytes(width=1200, height=900, fmt='JPEG', exif=None):
    img = Image.new('RGB', (width, height), color=(120, 40, 200))
    buf = io.BytesIO()
    kwargs = {'format': fmt}
    if exif is not None:
        kwargs['exif'] = exif
    img.save(buf, **kwargs)
    buf.seek(0)
    buf.name = f'test.{fmt.lower()}'
    return buf


class ImageProcessingTests(TestCase):
    def test_valid_jpeg_is_reencoded_to_webp_with_dims_and_phash(self):
        result = process_image(make_image_bytes(1200, 900))
        self.assertEqual((result.width, result.height), (1200, 900))
        self.assertEqual(len(result.phash), 16)
        out = Image.open(io.BytesIO(result.data))
        self.assertEqual(out.format, 'WEBP')

    def test_oversize_dimensions_rejected(self):
        with self.assertRaises(MediaValidationError) as ctx:
            process_image(make_image_bytes(5000, 100))
        self.assertIn('file', ctx.exception.errors)

    def test_downscales_to_1600_longest_edge(self):
        result = process_image(make_image_bytes(3200, 1600))
        self.assertEqual((result.width, result.height), (1600, 800))

    def test_non_image_rejected(self):
        buf = io.BytesIO(b'this is not an image at all')
        buf.name = 'evil.jpg'
        with self.assertRaises(MediaValidationError):
            process_image(buf)

    def test_gif_rejected_in_wave_1(self):
        with self.assertRaises(MediaValidationError):
            process_image(make_image_bytes(fmt='GIF'))

    def test_exif_is_stripped(self):
        exif = Image.Exif()
        exif[0x010F] = 'TestCam Make'          # Make tag
        src = make_image_bytes(exif=exif.tobytes())
        result = process_image(src)
        out = Image.open(io.BytesIO(result.data))
        self.assertEqual(dict(out.getexif()), {})

    def test_phash_is_deterministic(self):
        a = process_image(make_image_bytes())
        b = process_image(make_image_bytes())
        self.assertEqual(a.phash, b.phash)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.ImageProcessingTests --keepdb`
Expected: FAIL — `ModuleNotFoundError: No module named 'jokes.media_processing'`.

- [ ] **Step 3: Implement**

Create `jokes/media_processing.py`:

```python
"""In-request image processing for media-joke uploads (spec §5.1).

Everything is synchronous and cheap by construction (Pillow on a ≤4096px
source): validate → bake orientation → downscale → re-encode to WebP. The
re-encode is ALSO the EXIF strip — no metadata survives a fresh encode. The
original upload is never stored.
"""
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_SOURCE_FORMATS = {'JPEG', 'PNG', 'WEBP'}   # GIF is Wave 2 (video-shaped)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_DIM = 4096
OUT_MAX_DIM = 1600
OUT_QUALITY = 82


class MediaValidationError(Exception):
    """Upload rejected. `errors` is a DRF-style {field: message} dict."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(str(errors))


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes            # WebP-encoded display derivative
    width: int
    height: int
    phash: str             # 64-bit difference hash, 16 hex chars


def dhash_hex(img, hash_size=8):
    """64-bit difference hash — adjacent-pixel gradient signs on an 8x9
    grayscale thumbnail. Pure Pillow (no numpy). This is a dedup/audit
    fingerprint; a CSAM vendor SDK computes its own hashes at activation
    (spec §7.3) — this is NOT PhotoDNA."""
    gray = img.convert('L').resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(gray.getdata())
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f'{bits:016x}'


def process_image(uploaded):
    """Validate + normalize one uploaded image; returns ProcessedImage.

    Raises MediaValidationError with a field-keyed message dict on any
    rejection (size, type, dimensions, corrupt data).
    """
    size = getattr(uploaded, 'size', None)
    if size is not None and size > MAX_IMAGE_BYTES:
        raise MediaValidationError(
            {'file': f'Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit.'}
        )

    try:
        probe = Image.open(uploaded)
        probe.verify()                       # cheap integrity check
    except (UnidentifiedImageError, OSError, ValueError):
        raise MediaValidationError({'file': 'Not a valid image.'})

    uploaded.seek(0)
    img = Image.open(uploaded)               # verify() invalidates; reopen
    if img.format not in ALLOWED_SOURCE_FORMATS:
        raise MediaValidationError(
            {'file': 'Only JPEG, PNG, or WebP images are supported.'}
        )
    if img.width > MAX_SOURCE_DIM or img.height > MAX_SOURCE_DIM:
        raise MediaValidationError(
            {'file': f'Image dimensions exceed {MAX_SOURCE_DIM}px.'}
        )

    img = ImageOps.exif_transpose(img)       # bake orientation BEFORE strip
    if max(img.size) > OUT_MAX_DIM:
        img.thumbnail((OUT_MAX_DIM, OUT_MAX_DIM), Image.LANCZOS)

    has_alpha = img.mode in ('RGBA', 'LA', 'PA') or 'transparency' in img.info
    img = img.convert('RGBA' if has_alpha else 'RGB')

    phash = dhash_hex(img)
    out = io.BytesIO()
    img.save(out, format='WEBP', quality=OUT_QUALITY)   # fresh encode = no EXIF
    return ProcessedImage(
        data=out.getvalue(), width=img.width, height=img.height, phash=phash,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.ImageProcessingTests --keepdb`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add jokes/media_processing.py jokes/tests_media.py
git commit -m "media: in-request image pipeline (validate, EXIF-strip re-encode to WebP, dHash)"
```

---

### Task 3: Content screening — SafeSearch wrapper + dormant hash matcher

**Files:**
- Create: `jokes/media_screening.py`
- Modify: `JokesForProject/settings.py` (one new setting near the STORAGES block)
- Test: `jokes/tests_media.py` (append)

**Interfaces:**
- Consumes: `settings.SAFESEARCH_ENABLED` (new, env-driven, default False — Stripe-gateway dormant pattern).
- Produces: `screen_image(image_bytes: bytes) -> dict` — `{'status': 'skipped'}` when disabled; else `{'status': 'ok'|'blocked', 'adult': <LIKELIHOOD-NAME>, 'violence': ..., 'racy': ..., 'medical': ..., 'spoof': ...}`. `get_matcher() -> HashMatcher` with `HashMatcher.match(phash: str) -> dict | None` (None = no hit); default `NullMatcher`.

- [ ] **Step 1: Add the setting**

In `JokesForProject/settings.py`, directly after the `STORAGES = {...}` block:

```python
# Media upload pre-screening (spec §7). Dormant unless enabled — mirrors the
# Stripe-gateway pattern: local dev/tests run with it off; prod sets
# SAFESEARCH_ENABLED=true (Cloud Run env) and uses ADC for the Vision API.
SAFESEARCH_ENABLED = os.getenv('SAFESEARCH_ENABLED', '').strip().lower() in ('1', 'true', 'yes')
```

- [ ] **Step 2: Write the failing tests**

Append to `jokes/tests_media.py`:

```python
from unittest.mock import MagicMock, patch

from jokes.media_screening import NullMatcher, get_matcher, screen_image


def _mock_annotation(adult='VERY_UNLIKELY', violence='VERY_UNLIKELY',
                     racy='VERY_UNLIKELY'):
    ann = MagicMock()
    for cat, value in (('adult', adult), ('violence', violence), ('racy', racy),
                       ('medical', 'VERY_UNLIKELY'), ('spoof', 'VERY_UNLIKELY')):
        getattr(ann, cat).name = value
    resp = MagicMock()
    resp.safe_search_annotation = ann
    resp.error.message = ''
    return resp


class ScreeningTests(TestCase):
    def test_disabled_returns_skipped(self):
        with override_settings(SAFESEARCH_ENABLED=False):
            self.assertEqual(screen_image(b'bytes'), {'status': 'skipped'})

    @override_settings(SAFESEARCH_ENABLED=True)
    def test_clean_image_ok(self):
        client = MagicMock()
        client.safe_search_detection.return_value = _mock_annotation()
        with patch('jokes.media_screening._client', return_value=client):
            verdict = screen_image(b'bytes')
        self.assertEqual(verdict['status'], 'ok')
        self.assertEqual(verdict['adult'], 'VERY_UNLIKELY')

    @override_settings(SAFESEARCH_ENABLED=True)
    def test_likely_adult_blocked(self):
        client = MagicMock()
        client.safe_search_detection.return_value = _mock_annotation(adult='LIKELY')
        with patch('jokes.media_screening._client', return_value=client):
            self.assertEqual(screen_image(b'bytes')['status'], 'blocked')

    @override_settings(SAFESEARCH_ENABLED=True)
    def test_racy_alone_does_not_block(self):
        client = MagicMock()
        client.safe_search_detection.return_value = _mock_annotation(racy='VERY_LIKELY')
        with patch('jokes.media_screening._client', return_value=client):
            self.assertEqual(screen_image(b'bytes')['status'], 'ok')

    def test_null_matcher_never_matches(self):
        matcher = get_matcher()
        self.assertIsInstance(matcher, NullMatcher)
        self.assertIsNone(matcher.match('0000000000000000'))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.ScreeningTests --keepdb`
Expected: FAIL — `ModuleNotFoundError: No module named 'jokes.media_screening'`.

- [ ] **Step 4: Implement**

Create `jokes/media_screening.py`:

```python
"""Automated media pre-screening (spec §7): Vision SafeSearch + a dormant
CSAM hash-matcher seam.

SafeSearch runs in-request at upload. Blocking policy: adult or violence at
LIKELY or above hard-blocks; everything else is stored on the asset and
surfaced to the human reviewer (racy/medical/spoof inform, never block).

The HashMatcher interface ships with a NullMatcher: every vendor (PhotoDNA,
NCMEC, Thorn Safer) needs owner-side onboarding paperwork before activation.
When credentials exist, implement HashMatcher and swap it in get_matcher() —
the upload view, audit actions, and schema are already wired (spec §7.3).
"""
from django.conf import settings

_LIKELIHOOD_ORDER = [
    'UNKNOWN', 'VERY_UNLIKELY', 'UNLIKELY', 'POSSIBLE', 'LIKELY', 'VERY_LIKELY',
]
_BLOCK_AT = _LIKELIHOOD_ORDER.index('LIKELY')
_BLOCK_CATEGORIES = ('adult', 'violence')
_REPORT_CATEGORIES = ('adult', 'violence', 'racy', 'medical', 'spoof')


def _client():
    from google.cloud import vision
    return vision.ImageAnnotatorClient()


def screen_image(image_bytes):
    """Return a verdict dict for one image. {'status': 'skipped'} when the
    screen is disabled (local dev / flag off) — the human review queue is
    still the publish gate either way."""
    if not getattr(settings, 'SAFESEARCH_ENABLED', False):
        return {'status': 'skipped'}

    from google.cloud import vision
    response = _client().safe_search_detection(
        image=vision.Image(content=image_bytes)
    )
    if getattr(response.error, 'message', ''):
        # Vision API failure: don't hard-fail the upload on infrastructure —
        # record the failure; the human reviewer remains the gate.
        return {'status': 'error', 'detail': response.error.message}

    ann = response.safe_search_annotation
    verdict = {cat: getattr(ann, cat).name for cat in _REPORT_CATEGORIES}
    blocked = any(
        _LIKELIHOOD_ORDER.index(verdict[cat]) >= _BLOCK_AT
        for cat in _BLOCK_CATEGORIES
        if verdict[cat] in _LIKELIHOOD_ORDER
    )
    verdict['status'] = 'blocked' if blocked else 'ok'
    return verdict


class HashMatcher:
    """CSAM hash-match seam. match() returns None for no-hit, or a dict
    describing the hit (vendor payload) — a truthy return blocks the upload
    and records a hash_match_hit audit."""

    def match(self, phash):
        raise NotImplementedError


class NullMatcher(HashMatcher):
    """Dormant default until a vendor is onboarded (owner action)."""

    def match(self, phash):
        return None


def get_matcher():
    return NullMatcher()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.ScreeningTests --keepdb`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add jokes/media_screening.py JokesForProject/settings.py jokes/tests_media.py
git commit -m "media: SafeSearch pre-screen (env-gated) + dormant CSAM hash-matcher seam"
```

---

### Task 4: Upload endpoint + throttle + orphan sweep

**Files:**
- Modify: `jokes/serializers.py` (add `MediaAssetSerializer` after `SourceSerializer`, before the Joke serializers)
- Modify: `jokes/views.py` (add `MediaUploadView` — put it in a new section before "Phase 2: Joke Submission & Drafts")
- Modify: `jokes/urls.py`
- Modify: `JokesForProject/settings.py` (throttle rate)
- Test: `jokes/tests_media.py` (append)

**Interfaces:**
- Consumes: Task 1 `MediaAsset`; Task 2 `process_image`/`MediaValidationError`; Task 3 `screen_image`/`get_matcher`; `audit.services.record_audit(request, action, outcome=..., actor=..., target_type=..., target_id=...)`.
- Produces: `POST /api/v1/media/uploads/` (multipart: `file`, optional `kind` default `'image'`) → 201 `{id, kind, url, poster_url, width, height, duration_ms, is_gif, created_at}`; 400 validation, 422 screening block, 401 anon. `MediaAssetSerializer` (used again by Task 5's list serializer). Module function `_sweep_orphan_assets(user)`.

- [ ] **Step 1: Write the failing tests**

Append to `jokes/tests_media.py`:

```python
from datetime import timedelta

from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaUploadEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user('uploader@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _upload(self, buf=None, kind='image'):
        buf = buf or make_image_bytes()
        return self.client.post(
            '/api/v1/media/uploads/', {'file': buf, 'kind': kind},
            format='multipart',
        )

    def test_upload_creates_asset_with_metadata(self):
        response = self._upload()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['kind'], 'image')
        self.assertEqual(body['width'], 1200)
        self.assertEqual(body['height'], 900)
        self.assertTrue(body['url'].startswith('http'))
        asset = MediaAsset.objects.get(pk=body['id'])
        self.assertEqual(asset.owner, self.user)
        self.assertEqual(len(asset.phash), 16)

    def test_anon_rejected(self):
        self.client.force_authenticate(None)
        self.assertEqual(self._upload().status_code, 401)

    def test_invalid_file_rejected_400(self):
        buf = io.BytesIO(b'not an image')
        buf.name = 'x.jpg'
        self.assertEqual(self._upload(buf).status_code, 400)

    def test_video_kind_rejected_wave_1(self):
        self.assertEqual(self._upload(kind='video').status_code, 400)

    def test_screening_block_returns_422_and_no_asset(self):
        with patch(
            'jokes.views.screen_image',
            return_value={'status': 'blocked', 'adult': 'LIKELY'},
        ):
            response = self._upload()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(MediaAsset.objects.count(), 0)

    def test_orphan_sweep_deletes_stale_unattached_assets(self):
        with freeze_time('2026-07-18 12:00:00'):
            stale = make_asset(self.user)
            stale_name = stale.file.name
        with freeze_time('2026-07-20 12:00:00'):
            response = self._upload()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(MediaAsset.objects.filter(pk=stale.pk).exists())
        self.assertFalse(default_storage.exists(stale_name))
```

Note: `make_asset` sets `created_at` via `auto_now_add` — `freeze_time` controls it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.MediaUploadEndpointTests --keepdb`
Expected: FAIL — 404s (route does not exist).

- [ ] **Step 3: Add the serializer**

In `jokes/serializers.py`, after `SourceSerializer`:

```python
class MediaAssetSerializer(serializers.ModelSerializer):
    """Read shape for an uploaded media asset (upload response + attachments)."""

    url = serializers.SerializerMethodField()
    poster_url = serializers.SerializerMethodField()

    class Meta:
        model = MediaAsset
        fields = [
            'id', 'kind', 'url', 'poster_url',
            'width', 'height', 'duration_ms', 'is_gif', 'created_at',
        ]

    def _absolute(self, field_file):
        if not field_file:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(field_file.url) if request else field_file.url

    def get_url(self, obj) -> str | None:
        return self._absolute(obj.file)

    def get_poster_url(self, obj) -> str | None:
        return self._absolute(obj.poster)
```

Add `MediaAsset` to the models import at the top of `jokes/serializers.py`.

- [ ] **Step 4: Add the view, route, and throttle rate**

In `JokesForProject/settings.py` `DEFAULT_THROTTLE_RATES`, add:

```python
        'media-upload': '30/hour',
```

In `jokes/views.py` (new section before "Phase 2: Joke Submission & Drafts"; add imports `from rest_framework.parsers import FormParser, MultiPartParser`, `from rest_framework.throttling import ScopedRateThrottle`, `from django.core.files.base import ContentFile`, plus `from .media_processing import MediaValidationError, process_image` and `from .media_screening import get_matcher, screen_image`; add `MediaAsset` to the models import):

```python
# =============================================================================
# Media Uploads (Wave 1: images; video/audio arrive in Wave 2)
# =============================================================================

def _sweep_orphan_assets(user):
    """Request-triggered orphan cleanup (no cron exists): on each upload,
    delete this user's own unattached assets older than 24h."""
    cutoff = timezone.now() - timedelta(hours=24)
    orphans = MediaAsset.objects.filter(
        owner=user, created_at__lt=cutoff,
        submission_links__isnull=True, joke_links__isnull=True,
    )
    for asset in orphans:
        asset.delete_with_files()


class MediaUploadView(APIView):
    """POST /media/uploads/ — validate, screen, and store one media file.

    The returned asset id is what the editor attaches to a draft via
    `media_asset_ids`. The whole pipeline is synchronous and in-request
    (single-app constraint): Pillow validate/re-encode → SafeSearch →
    hash-matcher → GCS write.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'media-upload'

    def post(self, request):
        from audit.services import record_audit

        kind = (request.data.get('kind') or 'image').strip()
        if kind != 'image':
            return Response(
                {'kind': ["Only 'image' uploads are supported. Video and audio arrive in Wave 2."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        uploaded = request.FILES.get('file')
        if uploaded is None:
            return Response(
                {'file': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            processed = process_image(uploaded)
        except MediaValidationError as exc:
            return Response(exc.errors, status=status.HTTP_400_BAD_REQUEST)

        verdict = screen_image(processed.data)
        if verdict.get('status') == 'blocked':
            record_audit(
                request, 'safesearch_block', outcome='blocked',
                actor=request.user, target_type='media_upload', target_id='',
            )
            return Response(
                {'file': ['This image was rejected by automated content screening.']},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        hit = get_matcher().match(processed.phash)
        if hit:
            record_audit(
                request, 'hash_match_hit', outcome='blocked',
                actor=request.user, target_type='media_upload', target_id='',
            )
            return Response(
                {'file': ['This image cannot be uploaded.']},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        asset = MediaAsset(
            owner=request.user, kind='image',
            width=processed.width, height=processed.height,
            phash=processed.phash, safesearch=verdict,
        )
        asset.file.save('image.webp', ContentFile(processed.data), save=False)
        asset.save()

        _sweep_orphan_assets(request.user)
        record_audit(
            request, 'media_upload', outcome='success', actor=request.user,
            target_type='media_asset', target_id=str(asset.pk),
        )
        serializer = MediaAssetSerializer(asset, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

(`timezone`/`timedelta` are already imported in `jokes/views.py`; verify and reuse the existing imports. Add `MediaAssetSerializer` to the serializers import block.)

In `jokes/urls.py` `urlpatterns` (with the other explicit paths, before `+ router.urls`):

```python
    # Media uploads (Wave 1)
    path('media/uploads/', views.MediaUploadView.as_view(), name='media-upload'),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.MediaUploadEndpointTests --keepdb`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add jokes/serializers.py jokes/views.py jokes/urls.py JokesForProject/settings.py jokes/tests_media.py
git commit -m "media: authenticated image upload endpoint with screening, throttle, and orphan sweep"
```

---

### Task 5: `image` format — rules, seed, draft/submit wiring

**Files:**
- Modify: `jokes/submission_rules.py`
- Create: `jokes/migrations/00XX_seed_image_format.py`
- Modify: `jokes/serializers.py` (`JokeSubmissionCreateSerializer`, `JokeSubmissionListSerializer`)
- Modify: `jokes/views.py` (`JokeDraftSubmitView.post`, `JokeDraftListView.get_queryset` prefetch)
- Test: `jokes/tests_media.py` (append)

**Interfaces:**
- Consumes: Task 1 models, Task 4 `MediaAssetSerializer`.
- Produces: `FORMAT_RULES['image']`; `validate_per_format` understands `attrs['media']` (a list of kind strings) + constraints `media_kind`/`min_media`/`max_media`; write API accepts `media_asset_ids: [uuid]` on draft PATCH / create / one-shot submit; `JokeSubmissionListSerializer` gains `media: [MediaAssetSerializer shape]`; text backfill covers setup-only formats.

- [ ] **Step 1: Write the failing tests**

Append to `jokes/tests_media.py`:

```python
from jokes.submission_rules import validate_per_format


def _taxonomy():
    fmt, _ = Format.objects.get_or_create(slug='image', defaults={'name': 'Image'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return fmt, age, lang


class ImageFormatRuleTests(TestCase):
    def test_image_requires_setup_and_media(self):
        errors = validate_per_format('image', {'setup': '', 'media': []})
        self.assertIn('setup', errors)
        self.assertIn('media', errors)

    def test_image_happy_path(self):
        errors = validate_per_format(
            'image', {'setup': 'caption', 'media': ['image']}
        )
        self.assertEqual(errors, {})

    def test_image_rejects_punchline(self):
        errors = validate_per_format(
            'image',
            {'setup': 'caption', 'punchline': 'nope', 'media': ['image']},
        )
        self.assertIn('punchline', errors)

    def test_image_max_six_attachments(self):
        errors = validate_per_format(
            'image', {'setup': 'caption', 'media': ['image'] * 7}
        )
        self.assertIn('media', errors)

    def test_image_rejects_wrong_kind(self):
        errors = validate_per_format(
            'image', {'setup': 'caption', 'media': ['video']}
        )
        self.assertIn('media', errors)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class ImageDraftFlowTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('imagecreator@example.com')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make_draft(self):
        response = self.client.post('/api/v1/jokes/my-drafts/', {'format': 'image'})
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def test_draft_patch_attaches_media_in_order(self):
        draft_id = self._make_draft()
        a1 = make_asset(self.user)
        a2 = make_asset(self.user)
        response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'caption here', 'media_asset_ids': [str(a2.pk), str(a1.pk)]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        draft = JokeSubmission.objects.get(pk=draft_id)
        self.assertEqual(
            [m.asset_id for m in draft.media.all()], [a2.pk, a1.pk]
        )

    def test_cannot_attach_someone_elses_asset(self):
        draft_id = self._make_draft()
        other = make_asset(make_user('other@example.com'))
        response = self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'media_asset_ids': [str(other.pk)]}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_submit_without_media_400(self):
        draft_id = self._make_draft()
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'caption'}, format='json',
        )
        response = self.client.post(f'/api/v1/jokes/my-drafts/{draft_id}/submit/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('media', response.json())

    def test_submit_happy_path_backfills_text_from_setup(self):
        draft_id = self._make_draft()
        asset = make_asset(self.user)
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'setup': 'the caption', 'media_asset_ids': [str(asset.pk)]},
            format='json',
        )
        response = self.client.post(f'/api/v1/jokes/my-drafts/{draft_id}/submit/')
        self.assertEqual(response.status_code, 200)
        draft = JokeSubmission.objects.get(pk=draft_id)
        self.assertEqual(draft.status, 'pending')
        self.assertEqual(draft.text, 'the caption')

    def test_draft_list_includes_media(self):
        draft_id = self._make_draft()
        asset = make_asset(self.user)
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'media_asset_ids': [str(asset.pk)]}, format='json',
        )
        response = self.client.get('/api/v1/jokes/my-drafts/')
        rows = response.json()['results'] if 'results' in response.json() else response.json()
        row = next(r for r in rows if r['id'] == draft_id)
        self.assertEqual(len(row['media']), 1)
        self.assertEqual(row['media'][0]['kind'], 'image')

    def test_draft_delete_removes_solely_referenced_assets(self):
        draft_id = self._make_draft()
        asset = make_asset(self.user)
        self.client.patch(
            f'/api/v1/jokes/my-drafts/{draft_id}/',
            {'media_asset_ids': [str(asset.pk)]}, format='json',
        )
        name = asset.file.name
        response = self.client.delete(f'/api/v1/jokes/my-drafts/{draft_id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(default_storage.exists(name))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.ImageFormatRuleTests jokes.tests_media.ImageDraftFlowTests --keepdb`
Expected: FAIL — unknown-format errors and missing `media` key.

- [ ] **Step 3: Extend FORMAT_RULES + validator**

In `jokes/submission_rules.py`, append to `FORMAT_RULES`:

```python
    'image': {
        'required':  ['setup', 'media'],
        'forbidden': ['punchline', 'lines'],
        'constraints': {
            'media_kind': 'image',
            'min_media': 1,
            'max_media': 6,
        },
    },
```

In `validate_per_format`, after the `min_text_words` block, add:

```python
    if {'media_kind', 'min_media', 'max_media'} & constraints.keys():
        media = attrs.get('media') or []
        if 'media' not in errors:
            min_media = constraints.get('min_media')
            max_media = constraints.get('max_media')
            media_kind = constraints.get('media_kind')
            if min_media is not None and len(media) < min_media:
                errors['media'] = (
                    f"{format_slug.capitalize()} format requires at least "
                    f"{min_media} media attachment(s)."
                )
            elif max_media is not None and len(media) > max_media:
                errors['media'] = (
                    f"{format_slug.capitalize()} format allows at most "
                    f"{max_media} media attachment(s)."
                )
            elif media_kind is not None and any(k != media_kind for k in media):
                errors['media'] = (
                    f"All attachments must be {media_kind} for "
                    f"{format_slug} format."
                )
```

(The existing required-field loop already covers empty `media` via `_is_blank([]) == True`; note both errors may appear — the test asserts membership, not exclusivity.)

- [ ] **Step 4: Seed the Format row**

Create `jokes/migrations/00XX_seed_image_format.py` (number after Task 1's migration; `dependencies` points at it):

```python
from django.db import migrations


def seed_image_format(apps, schema_editor):
    Format = apps.get_model('jokes', 'Format')
    Format.objects.update_or_create(
        slug='image',
        defaults={
            'name': 'Image',
            'description': 'A setup caption with an image (or up to six) as the punchline.',
        },
    )


def unseed_image_format(apps, schema_editor):
    Format = apps.get_model('jokes', 'Format')
    Format.objects.filter(slug='image', jokes__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('jokes', '00XX_media_asset'),
    ]
    operations = [
        migrations.RunPython(seed_image_format, unseed_image_format),
    ]
```

- [ ] **Step 5: Wire the write serializer**

In `jokes/serializers.py` `JokeSubmissionCreateSerializer`:

Add the field (with the other declared fields):

```python
    media_asset_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True,
    )
```

Add `'media_asset_ids'` to `Meta.fields`.

In `validate(self, data)`, after building `attrs` and BEFORE the `skip_format_validation` check, insert:

```python
        # Resolve media attachments for per-format validation. When the key is
        # absent on a PATCH, the instance's existing attachments stand.
        self._media_provided = 'media_asset_ids' in data
        if self._media_provided:
            media_ids = data.get('media_asset_ids') or []
            if len(set(media_ids)) != len(media_ids):
                raise serializers.ValidationError(
                    {'media_asset_ids': 'Duplicate media attachments.'}
                )
            request = self.context.get('request')
            owner = getattr(request, 'user', None)
            assets = {
                a.id: a for a in MediaAsset.objects.filter(
                    id__in=media_ids, owner=owner,
                )
            }
            missing = [str(i) for i in media_ids if i not in assets]
            if missing:
                raise serializers.ValidationError(
                    {'media_asset_ids': 'One or more media assets were not found.'}
                )
            self._media_assets = [assets[i] for i in media_ids]
            attrs['media'] = [a.kind for a in self._media_assets]
        elif self.instance is not None:
            attrs['media'] = [m.asset.kind for m in self.instance.media.all()]
        else:
            attrs['media'] = []
```

Extend the text backfill at the end of `validate` — change:

```python
        if not attrs['text']:
            if attrs['setup'] and attrs['punchline']:
                data['text'] = f"{attrs['setup']} {attrs['punchline']}"
            elif attrs['lines']:
                data['text'] = ' '.join(attrs['lines'])
```

to:

```python
        if not attrs['text']:
            if attrs['setup'] and attrs['punchline']:
                data['text'] = f"{attrs['setup']} {attrs['punchline']}"
            elif attrs['lines']:
                data['text'] = ' '.join(attrs['lines'])
            elif attrs['setup']:
                # Media formats: the setup teaser IS the searchable/share text.
                data['text'] = attrs['setup']
```

Add `create`/`update` overrides + sync helper to the same serializer:

```python
    def create(self, validated_data):
        validated_data.pop('media_asset_ids', None)
        instance = super().create(validated_data)
        self._sync_media(instance)
        return instance

    def update(self, instance, validated_data):
        validated_data.pop('media_asset_ids', None)
        instance = super().update(instance, validated_data)
        self._sync_media(instance)
        return instance

    def _sync_media(self, submission):
        if not getattr(self, '_media_provided', False):
            return
        submission.media.all().delete()
        for position, asset in enumerate(getattr(self, '_media_assets', [])):
            JokeSubmissionMedia.objects.create(
                submission=submission, asset=asset, position=position,
            )
```

Add `JokeSubmissionMedia, MediaAsset` to the models import in `jokes/serializers.py`.

- [ ] **Step 6: Read side + submit gate + draft delete cleanup**

`JokeSubmissionListSerializer`: add

```python
    media = serializers.SerializerMethodField()
```

with `'media'` appended to `Meta.fields` and:

```python
    def get_media(self, obj) -> list[dict]:
        return [
            MediaAssetSerializer(link.asset, context=self.context).data
            for link in obj.media.all()
        ]
```

`jokes/views.py` `JokeDraftSubmitView.post` — extend the `validate_per_format` attrs dict with:

```python
                'media': [m.asset.kind for m in submission.media.all()],
```

`JokeDraftListView.get_queryset` — add `'media__asset'` to `prefetch_related`.

`JokeDraftDetailView` — add a `perform_destroy` override so deleting a draft cleans up assets referenced ONLY by that draft:

```python
    def perform_destroy(self, instance):
        assets = [link.asset for link in instance.media.select_related('asset')]
        super().perform_destroy(instance)
        for asset in assets:
            still_used = (
                asset.submission_links.exists() or asset.joke_links.exists()
            )
            if not still_used:
                asset.delete_with_files()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.ImageFormatRuleTests jokes.tests_media.ImageDraftFlowTests --keepdb`
Expected: PASS (12 tests). Also run the neighboring suites that touch the same code: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests --keepdb` — expect no regressions.

- [ ] **Step 8: Commit**

```bash
git add jokes/submission_rules.py jokes/migrations jokes/serializers.py jokes/views.py jokes/tests_media.py
git commit -m "media: image format rules, Format seed, draft attach/submit wiring with text backfill"
```

---

### Task 6: Locking contract — media in Joke serializers

**Files:**
- Modify: `jokes/serializers.py` (`JokeSerializer`, `JokeListSerializer`)
- Modify: `jokes/views.py` (`JokeViewSet.get_queryset` prefetch)
- Test: `jokes/tests_media.py` (append)

**Interfaces:**
- Consumes: Task 1 `JokeMedia` (`joke.media`), existing `paywall_state` context + `_is_locked`.
- Produces: `JokeSerializer` emits `media: [{kind,url,poster_url,width,height,duration_ms,is_gif}]` unlocked / `[{kind,width,height}]` locked. `JokeListSerializer` emits dims-only ALWAYS. The frontend (FE plan) consumes exactly these shapes.

- [ ] **Step 1: Write the failing tests**

Append to `jokes/tests_media.py`:

```python
from rest_framework.test import APIRequestFactory

from jokes.paywall import PaywallState
from jokes.serializers import JokeListSerializer, JokeSerializer


def make_image_joke(user, setup='the caption'):
    fmt, age, lang = _taxonomy()
    joke = Joke.objects.create(
        text=setup, setup=setup, format=fmt, age_rating=age, language=lang,
        creator=user,
    )
    asset = make_asset(user)
    JokeMedia.objects.create(joke=joke, asset=asset, position=0)
    return joke


def locked_state(consumed=frozenset()):
    return PaywallState(
        over=True, used=10, limit=10, remaining=0,
        consumed_ids=consumed, reset_at='2026-07-21T00:00:00+00:00',
    )


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaLockingContractTests(TestCase):
    def setUp(self):
        self.user = make_user('lockme@example.com')
        self.joke = make_image_joke(self.user)
        self.request = APIRequestFactory().get('/api/v1/jokes/')

    def test_unlocked_serves_full_media(self):
        data = JokeSerializer(
            self.joke, context={'request': self.request}
        ).data
        self.assertEqual(len(data['media']), 1)
        item = data['media'][0]
        self.assertIn('url', item)
        self.assertTrue(item['url'])
        self.assertFalse(data['is_locked'])

    def test_locked_serves_dimensions_only(self):
        data = JokeSerializer(
            self.joke,
            context={'request': self.request, 'paywall_state': locked_state()},
        ).data
        self.assertTrue(data['is_locked'])
        item = data['media'][0]
        self.assertEqual(
            set(item.keys()), {'kind', 'width', 'height'}
        )
        self.assertEqual(data['setup'], 'the caption')  # teaser survives

    def test_consumed_joke_keeps_media(self):
        state = locked_state(consumed=frozenset({self.joke.id}))
        data = JokeSerializer(
            self.joke,
            context={'request': self.request, 'paywall_state': state},
        ).data
        self.assertFalse(data['is_locked'])
        self.assertIn('url', data['media'][0])

    def test_list_serializer_never_serves_urls(self):
        data = JokeListSerializer(
            self.joke, context={'request': self.request}
        ).data
        self.assertEqual(
            set(data['media'][0].keys()), {'kind', 'width', 'height'}
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.MediaLockingContractTests --keepdb`
Expected: FAIL — `KeyError: 'media'`.

- [ ] **Step 3: Implement**

`JokeSerializer` — add the declared field + `'media'` to `Meta.fields` (after `'lines'`), and the method:

```python
    media = serializers.SerializerMethodField()
```

```python
    def get_media(self, obj) -> list[dict]:
        """Media attachments in position order. LOCKED jokes get dimensions
        only — URLs are withheld SERVER-SIDE (spec §6.2): a client-side blur
        over a real URL would still download the payoff."""
        links = list(obj.media.all())
        if not links:
            return []
        if self._is_locked(obj):
            return [
                {'kind': l.asset.kind, 'width': l.asset.width, 'height': l.asset.height}
                for l in links
            ]
        serializer = MediaAssetSerializer(context=self.context)
        return [
            {
                'kind': l.asset.kind,
                'url': serializer._absolute(l.asset.file),
                'poster_url': serializer._absolute(l.asset.poster),
                'width': l.asset.width,
                'height': l.asset.height,
                'duration_ms': l.asset.duration_ms,
                'is_gif': l.asset.is_gif,
            }
            for l in links
        ]
```

`JokeListSerializer` — add the same declared field, `'media'` in `Meta.fields`, and:

```python
    def get_media(self, obj) -> list[dict]:
        """Dims-only ALWAYS: this serializer has no paywall context (it serves
        the public creator profile) — emitting URLs here would bypass the
        paywall entirely."""
        return [
            {'kind': l.asset.kind, 'width': l.asset.width, 'height': l.asset.height}
            for l in obj.media.all()
        ]
```

`jokes/views.py` `JokeViewSet.get_queryset` — extend `prefetch_related` with `'media__asset'`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.MediaLockingContractTests jokes.test_paywall --keepdb`
Expected: PASS — new tests AND the whole existing paywall suite (regression guard).

- [ ] **Step 5: Commit**

```bash
git add jokes/serializers.py jokes/views.py jokes/tests_media.py
git commit -m "media: locking contract — URLs withheld server-side when locked, dims-only in list serializer"
```

---

### Task 7: Publish copy, admin review, takedown/account-delete/export lifecycle

**Files:**
- Modify: `jokes/admin.py` (`JokeSubmissionAdmin`, `ContentReportAdmin.take_down_joke`)
- Modify: `jokes/views.py` (`UserAccountDeleteView`, `DataExportView` — locate the avatar-deletion block around L2011 and the export payload builder)
- Test: `jokes/tests_media.py` (append)

**Interfaces:**
- Consumes: Tasks 1/5/6 models + `MediaAsset.delete_with_files()`; `record_audit`.
- Produces: published image jokes carry `JokeMedia` rows; takedown and account deletion remove storage objects; data export lists the user's assets under `media_assets`.

- [ ] **Step 1: Write the failing tests**

Append to `jokes/tests_media.py`:

```python
from django.contrib.admin.sites import AdminSite

from jokes.admin import ContentReportAdmin, JokeSubmissionAdmin
from jokes.models import ContentReport


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class MediaPublishAndLifecycleTests(TestCase):
    def setUp(self):
        self.fmt, self.age, self.lang = _taxonomy()
        self.user = make_user('publisher@example.com')
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com', email='admin@example.com', password='x',
        )
        self.factory = APIRequestFactory()

    def _pending_submission(self):
        sub = JokeSubmission.objects.create(
            user=self.user, format=self.fmt, age_rating=self.age,
            language=self.lang, setup='caption', text='caption', status='pending',
        )
        a1, a2 = make_asset(self.user), make_asset(self.user)
        JokeSubmissionMedia.objects.create(submission=sub, asset=a1, position=0)
        JokeSubmissionMedia.objects.create(submission=sub, asset=a2, position=1)
        return sub

    def _admin_request(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware
        request = self.factory.post('/admin/')
        request.user = self.admin_user
        SessionMiddleware(lambda r: None).process_request(request)
        request._messages = FallbackStorage(request)   # message_user() needs this
        return request

    def test_approve_and_publish_copies_media_in_order(self):
        sub = self._pending_submission()
        admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        admin_obj.approve_and_publish(
            self._admin_request(), JokeSubmission.objects.filter(pk=sub.pk),
        )
        sub.refresh_from_db()
        joke = sub.published_joke
        self.assertIsNotNone(joke)
        self.assertEqual(
            [m.position for m in joke.media.all()], [0, 1]
        )
        self.assertEqual(
            [m.asset_id for m in joke.media.all()],
            [m.asset_id for m in sub.media.all()],
        )

    def test_takedown_deletes_storage_files(self):
        sub = self._pending_submission()
        admin_obj = JokeSubmissionAdmin(JokeSubmission, AdminSite())
        admin_obj.approve_and_publish(
            self._admin_request(), JokeSubmission.objects.filter(pk=sub.pk),
        )
        sub.refresh_from_db()
        joke = sub.published_joke
        names = [m.asset.file.name for m in joke.media.all()]
        report = ContentReport.objects.create(
            reporter=self.admin_user, joke=joke, reason='inappropriate',
        )
        report_admin = ContentReportAdmin(ContentReport, AdminSite())
        report_admin.take_down_joke(
            self._admin_request(), ContentReport.objects.filter(pk=report.pk),
        )
        joke.refresh_from_db()
        self.assertTrue(joke.is_removed)
        for name in names:
            self.assertFalse(default_storage.exists(name))
        self.assertEqual(MediaAsset.objects.filter(owner=self.user).count(), 0)

    def test_account_delete_removes_assets(self):
        asset = make_asset(self.user)
        name = asset.file.name
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.delete(
            '/api/v1/users/me/', {'password': 'x'}, format='json',
        )
        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(MediaAsset.objects.filter(pk=asset.pk).exists())
        self.assertFalse(default_storage.exists(name))

    def test_data_export_lists_media_assets(self):
        make_asset(self.user)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get('/api/v1/users/me/data-export/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['media_assets']), 1)
```

NOTE for the implementer: `test_account_delete_removes_assets` must match the
ACTUAL re-auth contract of `UserAccountDeleteView` (read it first — it may
require the password in a different field or a POST). Adjust the request in
the test to the real contract; the assertion (assets + files gone) is the
requirement. Same for the export shape: `media_assets` is the new key; nest
it wherever the existing payload groups user content.

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.MediaPublishAndLifecycleTests --keepdb`
Expected: FAIL — media not copied / files still present / `KeyError: 'media_assets'`.

- [ ] **Step 3: Implement publish copy + admin columns**

`jokes/admin.py` `approve_and_publish` — after `joke.culture_tags.set(...)`, add:

```python
                    for link in submission.media.all():
                        JokeMedia.objects.create(
                            joke=joke, asset=link.asset, position=link.position,
                        )
```

(Import `JokeMedia`, `MediaAsset` with the other model imports.)

`JokeSubmissionAdmin` — add review-queue visibility:

```python
    list_display = ['user', 'text_preview', 'media_preview', 'safesearch_flags',
                    'format', 'status', 'updated_at']

    def media_preview(self, obj):
        link = obj.media.select_related('asset').first()
        if not link or not link.asset.file:
            return '—'
        return format_html(
            '<img src="{}" style="max-height:60px;max-width:100px;'
            'border-radius:4px;" />',
            link.asset.file.url,
        )
    media_preview.short_description = 'Media'

    def safesearch_flags(self, obj):
        flags = []
        for link in obj.media.select_related('asset'):
            verdict = link.asset.safesearch or {}
            flags.extend(
                f'{category}:{level}'
                for category, level in verdict.items()
                if category != 'status'
                and level in ('POSSIBLE', 'LIKELY', 'VERY_LIKELY')
            )
        return ', '.join(flags) or '—'
    safesearch_flags.short_description = 'Screen flags'
```

(`from django.utils.html import format_html` — check it isn't already imported.)

- [ ] **Step 4: Implement takedown + account-delete + export**

`ContentReportAdmin.take_down_joke` — after the reports-resolve `.update(...)` call, add:

```python
        # Media lifecycle: takedown deletes the storage objects too — the DB
        # flag alone leaves files world-readable on the public bucket.
        media_assets = MediaAsset.objects.filter(
            joke_links__joke_id__in=joke_ids,
        ).distinct()
        media_deleted = 0
        for asset in media_assets:
            asset.delete_with_files()
            media_deleted += 1
        if media_deleted:
            record_audit(
                request, 'media_takedown', outcome='success',
                actor=request.user, target_type='joke',
                target_id=','.join(str(j) for j in sorted(joke_ids)),
            )
```

`UserAccountDeleteView` (`jokes/views.py`) — in the deletion flow, immediately BEFORE the existing avatar-deletion block, add:

```python
        # Media lifecycle: remove the user's uploaded assets from storage
        # explicitly — the DB CASCADE alone would orphan the files.
        for asset in MediaAsset.objects.filter(owner=user):
            asset.delete_with_files()
```

(Use the same local variable name the view already uses for the account being deleted — read the surrounding code.)

`DataExportView` — add to the export payload dict:

```python
            'media_assets': [
                {
                    'id': str(asset.pk),
                    'kind': asset.kind,
                    'url': request.build_absolute_uri(asset.file.url) if asset.file else None,
                    'created_at': asset.created_at.isoformat(),
                }
                for asset in MediaAsset.objects.filter(owner=user)
            ],
```

(Again: match the local user variable and payload nesting used by the existing code.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.MediaPublishAndLifecycleTests --keepdb`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add jokes/admin.py jokes/views.py jokes/tests_media.py
git commit -m "media: publish copies attachments; takedown, account delete, and export cover media files"
```

---

### Task 8: Anonymous paywall — signed-cookie ledger + reveal endpoint

**Files:**
- Modify: `jokes/paywall.py`
- Modify: `jokes/views.py` (`JokeViewSet.retrieve`, new `JokeRevealView`)
- Modify: `jokes/urls.py`
- Test: `jokes/tests_media.py` (append)

**Interfaces:**
- Consumes: existing `PaywallState`, `paywall_state(request)`, `allowed_tiers`, `visible_jokes`.
- Produces: anon `paywall_state` reads cookie `jf_anon_reads` (10/day, midnight UTC); `record_anon_read(response, request, joke_id)` appends + re-signs the cookie; `POST /api/v1/jokes/{id}/reveal/` → `{limit, used, remaining, over, reset_at}` (204 for authenticated callers — their ledger is JokeView). `GET /api/v1/jokes/daily-reads/` now returns real numbers for anon (it already calls `paywall_state`; verify, don't rewrite). The FE plan consumes the reveal endpoint + anon `is_locked`.

- [ ] **Step 1: Write the failing tests**

Append to `jokes/tests_media.py`:

```python
from django.core import signing as django_signing

from jokes.paywall import (
    ANON_COOKIE_NAME, ANON_COOKIE_SALT, FREE_READS_DEFAULT, paywall_state,
)


def _seed_text_jokes(n):
    fmt, _ = Format.objects.get_or_create(slug='oneliner', defaults={'name': 'One-liner'})
    age, _ = AgeRating.objects.get_or_create(slug='all-ages', defaults={'name': 'All Ages'})
    lang, _ = Language.objects.get_or_create(code='en', defaults={'name': 'English'})
    return [
        Joke.objects.create(
            text=f'joke {i}', format=fmt, age_rating=age, language=lang,
        )
        for i in range(n)
    ]


class AnonPaywallTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.jokes = _seed_text_jokes(12)

    def _reveal(self, joke):
        return self.client.post(f'/api/v1/jokes/{joke.pk}/reveal/')

    def test_reveal_consumes_and_reports_state(self):
        response = self._reveal(self.jokes[0])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['used'], 1)
        self.assertEqual(body['limit'], FREE_READS_DEFAULT)
        self.assertFalse(body['over'])
        self.assertIn(ANON_COOKIE_NAME, response.cookies)

    def test_over_cap_locks_new_jokes_but_not_consumed_ones(self):
        for joke in self.jokes[:10]:
            self._reveal(joke)
        listing = self.client.get('/api/v1/jokes/')
        rows = listing.json()['results']
        by_id = {row['id']: row for row in rows}
        consumed_id = self.jokes[0].pk
        fresh_id = self.jokes[11].pk
        if consumed_id in by_id:
            self.assertFalse(by_id[consumed_id]['is_locked'])
        if fresh_id in by_id:
            self.assertTrue(by_id[fresh_id]['is_locked'])

    def test_reveal_when_over_does_not_extend(self):
        for joke in self.jokes[:10]:
            self._reveal(joke)
        response = self._reveal(self.jokes[11])
        body = response.json()
        self.assertTrue(body['over'])
        self.assertEqual(body['used'], 10)

    def test_tampered_cookie_resets_ledger(self):
        self._reveal(self.jokes[0])
        self.client.cookies[ANON_COOKIE_NAME] = 'tampered-garbage'
        response = self._reveal(self.jokes[1])
        self.assertEqual(response.json()['used'], 1)

    def test_midnight_utc_reset(self):
        with freeze_time('2026-07-20 23:30:00'):
            for joke in self.jokes[:10]:
                self._reveal(joke)
            self.assertTrue(self._reveal(self.jokes[10]).json()['over'])
        with freeze_time('2026-07-21 00:30:00'):
            response = self._reveal(self.jokes[10])
            self.assertEqual(response.json()['used'], 1)
            self.assertFalse(response.json()['over'])

    def test_authenticated_caller_gets_204_noop(self):
        user = make_user('authed@example.com')
        self.client.force_authenticate(user)
        response = self._reveal(self.jokes[0])
        self.assertEqual(response.status_code, 204)

    def test_anon_detail_get_consumes(self):
        response = self.client.get(f'/api/v1/jokes/{self.jokes[0].pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(ANON_COOKIE_NAME, response.cookies)

    def test_daily_reads_reports_anon_state(self):
        self._reveal(self.jokes[0])
        response = self.client.get('/api/v1/jokes/daily-reads/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['used'], 1)
        self.assertEqual(response.json()['limit'], FREE_READS_DEFAULT)
```

(freezegun note: `APIClient` cookies persist across requests within a test, which is exactly the browser behavior being modeled.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.AnonPaywallTests --keepdb`
Expected: FAIL — `ImportError: cannot import name 'ANON_COOKIE_NAME'`.

- [ ] **Step 3: Implement the cookie ledger in `jokes/paywall.py`**

Add imports: `from django.conf import settings` and `from django.core import signing`.

Add after the `FREE_READS_DEFAULT` constant:

```python
# Anonymous ledger (spec §8): a signed cookie stands in for the JokeView
# table. Deliberately a SOFT wall — clearing cookies evades it; the goal is
# conversion (drive registration), not enforcement.
ANON_COOKIE_NAME = 'jf_anon_reads'
ANON_COOKIE_SALT = 'jokes.paywall.anon'
ANON_COOKIE_MAX_AGE = 60 * 60 * 48   # 2 days; the date check does the real reset


def _read_anon_ledger(request) -> frozenset:
    """Today's consumed joke_ids from the signed anon cookie. Tampered,
    expired, or stale-dated cookies yield a fresh (empty) ledger."""
    raw = request.COOKIES.get(ANON_COOKIE_NAME)
    if not raw:
        return frozenset()
    try:
        payload = signing.loads(
            raw, salt=ANON_COOKIE_SALT, max_age=ANON_COOKIE_MAX_AGE,
        )
    except signing.BadSignature:
        return frozenset()
    if payload.get('date') != timezone.now().date().isoformat():
        return frozenset()
    ids = payload.get('ids') or []
    return frozenset(
        i for i in ids[:FREE_READS_DEFAULT] if isinstance(i, int)
    )


def record_anon_read(response, request, joke_id) -> None:
    """Append joke_id to the anon ledger and set the re-signed cookie on the
    response. No-op when already consumed or over the cap."""
    consumed = set(_read_anon_ledger(request))
    if joke_id in consumed or len(consumed) >= FREE_READS_DEFAULT:
        return
    consumed.add(joke_id)
    payload = {
        'date': timezone.now().date().isoformat(),
        'ids': sorted(consumed),
    }
    response.set_cookie(
        ANON_COOKIE_NAME,
        signing.dumps(payload, salt=ANON_COOKIE_SALT),
        max_age=ANON_COOKIE_MAX_AGE,
        secure=not settings.DEBUG,
        httponly=True,
        samesite=getattr(settings, 'CSRF_COOKIE_SAMESITE', None) or 'Lax',
    )
```

Replace the anon early-return in `paywall_state` (the `TODO(paywall)` block):

```python
    if user is None or not getattr(user, 'is_authenticated', False):
        # Anonymous ledger: signed cookie, same 10/day semantics as free
        # accounts (spec §8). Soft wall by design.
        consumed_ids = _read_anon_ledger(request)
        used = len(consumed_ids)
        return PaywallState(
            over=used >= FREE_READS_DEFAULT,
            used=used,
            limit=FREE_READS_DEFAULT,
            remaining=max(0, FREE_READS_DEFAULT - used),
            consumed_ids=consumed_ids,
            reset_at=_next_midnight_utc_iso(),
        )
```

Update the module docstring's "Anonymous users are OUT OF SCOPE" paragraph to describe the cookie ledger.

- [ ] **Step 4: Implement the reveal endpoint + anon retrieve consumption**

`jokes/views.py` — new view (same section as `JokeViewSet`; import `record_anon_read` from `.paywall`, and ensure `AllowAny` is in the `rest_framework.permissions` import — the file currently imports `IsAuthenticated`):

```python
class JokeRevealView(APIView):
    """POST /jokes/{id}/reveal/ — anonymous consumption ledger write.

    Anonymous in-feed reveals can't ride telemetry (consent-gated), so the
    frontend calls this when an unauthenticated reader taps reveal.
    Authenticated readers 204 no-op: their ledger is JokeView (retrieve +
    telemetry). Soft wall: response carries the updated counters.
    """

    permission_classes = [AllowAny]

    def post(self, request, pk):
        if request.user.is_authenticated:
            return Response(status=status.HTTP_204_NO_CONTENT)

        joke = get_object_or_404(
            visible_jokes(
                Joke.objects.filter(content_tier__in=allowed_tiers(request)),
                request,
            ),
            pk=pk,
        )
        state = paywall_state(request)
        consumed = set(state.consumed_ids)
        will_consume = joke.pk not in consumed and not state.over
        if will_consume:
            consumed.add(joke.pk)
        used = len(consumed)
        response = Response({
            'limit': state.limit,
            'used': used,
            'remaining': max(0, (state.limit or 0) - used),
            'over': used >= (state.limit or 0),
            'reset_at': state.reset_at,
        })
        if will_consume:
            record_anon_read(response, request, joke.pk)
        return response
```

`JokeViewSet.retrieve` — after the existing authenticated block, extend the flow so anon unlocked deliveries consume too. The final shape of the method's logging section:

```python
        if request.user.is_authenticated and response.status_code == 200:
            # ... existing authed JokeView logging stays EXACTLY as-is ...
        elif response.status_code == 200 and not response.data.get('is_locked'):
            joke_id = response.data.get('id')
            if joke_id:
                record_anon_read(response, request, joke_id)
        return response
```

`jokes/urls.py` — add with the other explicit paths:

```python
    path('jokes/<int:pk>/reveal/', views.JokeRevealView.as_view(), name='joke-reveal'),
```

Then READ the existing `daily-reads` action on `JokeViewSet`: it already calls `paywall_state(request)`. Verify it has no `IsAuthenticated` permission override blocking anon; if it does, relax it to `AllowAny`. Do not otherwise rewrite it — the anon branch of `paywall_state` lights it up automatically.

- [ ] **Step 5: Run tests to verify they pass**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test jokes.tests_media.AnonPaywallTests jokes.test_paywall --keepdb`
Expected: PASS — all new tests AND the existing authed-paywall suite unchanged.

- [ ] **Step 6: Commit**

```bash
git add jokes/paywall.py jokes/views.py jokes/urls.py jokes/tests_media.py
git commit -m "paywall: anonymous 10/day ledger via signed cookie + reveal endpoint"
```

---

### Task 9: Full-suite regression + wrap-up

**Files:**
- Modify: none expected (fix regressions only, if any)

- [ ] **Step 1: Run the ENTIRE backend suite**

Run: `DATABASE_URL= DB_PASSWORD=6969 .venv/bin/python manage.py test --keepdb`
Expected: ALL tests pass (633 pre-existing + ~40 new). Pay special attention to `jokes.tests_compliance` (anon serving paths — the anon paywall branch changed `paywall_state` for anonymous requests; cookie-less anons have `used=0 → over=False`, so behavior must be unchanged) and `jokes.tests_telemetry`.

- [ ] **Step 2: Fix any regressions**

If a pre-existing test fails, the fix goes in the PRODUCTION code path that broke it, not in the old test — unless the old test literally asserts the retired behavior ("anon is never locked"), in which case update that assertion to the new spec §8 contract and say so in the commit message.

- [ ] **Step 3: Commit (only if fixes were needed)**

```bash
git add -A
git commit -m "media: regression fixes after wave-1 backend integration"
```

---

## Deployment notes (owner-visible, not tasks)

- Deploy is push-to-main (Cloud Build: migrate → build → deploy). The two new migrations run automatically.
- New Cloud Run env var to enable screening in prod: `SAFESEARCH_ENABLED=true` + Vision API enabled on the `jokesfor` GCP project (owner console action; ADC covers auth).
- Frontend deploys FIRST (unknown-format guard) per spec §11 — coordinate with the wave-1 frontend plan before pushing this branch to main.
