"""Public XML sitemap of crawlable frontend routes -- served at /sitemap.xml.

This backend generates the sitemap, but every `<loc>` is an ABSOLUTE frontend
URL (settings.FRONTEND_URL), never this backend's own host: a Firebase
Hosting rewrite maps `/sitemap.xml` on the frontend origin straight to this
endpoint, so whatever we emit is what search engines crawl verbatim.

Visibility mirrors the real anonymous-visitor read paths, not a re-derived
guess -- a search-engine crawler is, from this app's point of view, just
another anonymous request:

  - Jokes: content_tier in serving.BASE_TIERS (tier_1) and not removed.
    BASE_TIERS is exactly what `allowed_tiers(request)` resolves to for an
    anonymous caller (jokes/serving.py) -- the same gate JokeViewSet.
    get_queryset() applies, so this is what GET /jokes/<id> actually 200s
    on for a crawler. tier_2 is deliberately excluded here even though it's
    servable to some authenticated viewers: a sitemap has no viewer.
    `Joke.objects` (the default manager) already excludes is_removed=True
    (see JokeManager.get_queryset), so `is_removed=False` below is a
    defensive repeat, not a new condition -- keeps the leakage guard
    visible at the call site instead of relying solely on the manager.

  - Creators: any creator with >= 1 directly-attributed (Joke.creator FK)
    tier_1, non-removed joke -- the same condition
    creator_insights.services.build_creator_profile / CreatorProfileView
    200s on for an anonymous viewer. The legacy null-creator ->
    JokeSubmission join fallback (resolve_creator_published_jokes_for_viewer's
    second branch, for pre-FK-stamp seed data) is intentionally out of
    scope: it exists for old-profile lookups, not new crawlable surface.

  - Packs: same is_published + publish/expiry window gate as
    JokePackViewSet.get_queryset().

Every section is capped well under the sitemap protocol's 50k-URL / 50MB
per-file limit -- current published-joke count is ~173, so none of these
caps bind today, but an unbounded query would be a landmine as the catalog
grows. A capped section logs a warning so growth past the cap is visible
instead of silently truncating the sitemap forever.
"""
import logging
from xml.etree.ElementTree import Element, SubElement, tostring

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Joke, JokePack
from .serving import BASE_TIERS

logger = logging.getLogger('jokesfor.sitemap')

_SITEMAP_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'

STATIC_ROUTES = (
    '/',
    '/daily',
    '/trending',
    '/privacy',
    '/terms',
    '/cookie-policy',
    '/childrens-privacy',
)

MAX_JOKES = 20000
MAX_CREATORS = 5000
MAX_PACKS = 2000


def _abs_url(path):
    """Build an absolute frontend URL -- never this backend's own host."""
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}"


def _add_url(urlset, path, lastmod=None):
    url_el = SubElement(urlset, 'url')
    SubElement(url_el, 'loc').text = _abs_url(path)
    if lastmod is not None:
        SubElement(url_el, 'lastmod').text = lastmod.date().isoformat()


def _public_joke_queryset():
    """Publicly-servable jokes -- exactly what an anonymous JokeViewSet
    request (GET /jokes/ or /jokes/<id>/) returns. See module docstring."""
    return Joke.objects.filter(is_removed=False, content_tier__in=BASE_TIERS)


def _public_pack_queryset():
    """Publicly-servable packs -- mirrors JokePackViewSet.get_queryset()."""
    now = timezone.now()
    return (
        JokePack.objects
        .filter(is_published=True)
        .filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    )


@require_GET
def sitemap_view(request):
    """GET /sitemap.xml

    Public, unauthenticated. Plain Django view (not DRF), so it needs no
    AllowAny declaration and drf-spectacular skips it automatically --
    same pattern as jokes.views.joke_share_page / JokesForProject.health.
    """
    urlset = Element('urlset', xmlns=_SITEMAP_NS)

    for path in STATIC_ROUTES:
        _add_url(urlset, path)

    # .values(...) rather than .only(...): Joke.__init__ unconditionally reads
    # self.text/self.is_removed for its dirty-tracking flags, so a model
    # instance missing either from a deferred `.only()` load re-triggers a
    # per-field refresh_from_db() that recurses back into __init__ (verified
    # by hand -- RecursionError). .values() returns plain dicts and never
    # constructs a Joke instance, sidestepping that entirely.
    jokes = list(
        _public_joke_queryset()
        .order_by('-updated_at', '-id')
        .values('id', 'updated_at')[:MAX_JOKES]
    )
    if len(jokes) >= MAX_JOKES:
        logger.warning(
            'sitemap: joke count hit the %d cap; some jokes are not listed', MAX_JOKES,
        )
    for joke in jokes:
        _add_url(urlset, f"/jokes/{joke['id']}", joke['updated_at'])

    creator_ids = list(
        _public_joke_queryset()
        .exclude(creator__isnull=True)
        .order_by('creator_id')
        .values_list('creator_id', flat=True)
        .distinct()[:MAX_CREATORS]
    )
    if len(creator_ids) >= MAX_CREATORS:
        logger.warning(
            'sitemap: creator count hit the %d cap; some creators are not listed', MAX_CREATORS,
        )
    for creator_id in creator_ids:
        _add_url(urlset, f'/creators/{creator_id}')

    packs = list(
        _public_pack_queryset()
        .order_by('-updated_at', '-id')
        .only('slug', 'updated_at')[:MAX_PACKS]
    )
    if len(packs) >= MAX_PACKS:
        logger.warning(
            'sitemap: pack count hit the %d cap; some packs are not listed', MAX_PACKS,
        )
    for pack in packs:
        _add_url(urlset, f'/packs/{pack.slug}', pack.updated_at)

    xml_bytes = tostring(urlset, encoding='utf-8', xml_declaration=True)
    return HttpResponse(xml_bytes, content_type='application/xml')
