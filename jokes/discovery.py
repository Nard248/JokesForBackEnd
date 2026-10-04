"""Shared, strict content selectors. Languages, countries and cultures are independent."""
from django.db.models import Count
from drf_spectacular.utils import OpenApiParameter

from .models import Country, CulturalCollection, CultureTag, Joke, Language
from .moderation import visible_jokes
from .serving import allowed_tiers

DISCOVERY_PARAMETERS = [
    OpenApiParameter('language', str, description='ISO language code; empty means every language.'),
    OpenApiParameter('country', str, description='ISO 3166-1 alpha-2 country setting; independent of language.'),
    OpenApiParameter('culture_tags', str, description='Comma-separated cultural-context slugs (union).'),
]


def discovery_selectors(params):
    """Normalize optional selectors without guessing a country from a language."""
    return {
        'language': str(params.get('language', '')).strip().lower(),
        'country': str(params.get('country', '')).strip().upper(),
        'culture_tags': [s.strip() for s in str(params.get('culture_tags', '')).split(',') if s.strip()],
    }


def filter_discovery(queryset, selectors):
    """Apply explicit constraints; an unknown or incompatible choice matches nothing."""
    selectors = selectors or {}
    if selectors.get('language'):
        queryset = queryset.filter(language__code=selectors['language'])
    if selectors.get('country'):
        queryset = queryset.filter(countries__code=selectors['country'])
    if selectors.get('culture_tags'):
        queryset = queryset.filter(culture_tags__slug__in=selectors['culture_tags'])
    return queryset.distinct()


def discovery_pool(request):
    """Only currently visible, permitted jokes can influence discovery or its counts."""
    return filter_discovery(
        visible_jokes(Joke.objects.filter(content_tier__in=allowed_tiers(request)), request),
        discovery_selectors(request.query_params),
    )


def locale_catalog(request):
    cultures = list(CultureTag.objects.prefetch_related('languages', 'countries').order_by('name'))
    languages = list(Language.objects.order_by('name'))
    countries = list(Country.objects.order_by('name'))
    visible = visible_jokes(Joke.objects.filter(content_tier__in=allowed_tiers(request)), request)
    counts = {
        (r['language__code'], r['countries__code'], r['culture_tags__slug']): r['total']
        for r in visible.values('language__code', 'countries__code', 'culture_tags__slug').annotate(
            total=Count('id', distinct=True),
        ).order_by()
    }
    country_languages = {c.code: set() for c in countries}
    # A joke can involve a neighbouring country without constituting a separate
    # authored collection. Expose its readable language without inventing a preset.
    for (language_code, country_code, _), count in counts.items():
        if language_code and country_code and count:
            country_languages[country_code].add(language_code)
    collections = []
    culture_rows = []
    for culture in cultures:
        associated_languages = list(culture.languages.all())
        associated_countries = list(culture.countries.all())
        culture_rows.append({
            'slug': culture.slug, 'name': culture.name, 'native_name': culture.native_name,
            'description': culture.description,
            'language_codes': sorted(lang.code for lang in associated_languages),
            'country_codes': sorted(c.code for c in associated_countries),
        })
    for collection in CulturalCollection.objects.select_related('language', 'country', 'culture'):
        language, country, culture = collection.language, collection.country, collection.culture
        country_languages[country.code].add(language.code)
        collections.append({
            'locale': f'{language.code}-{country.code}',
            'language': language.code, 'country': country.code, 'culture': culture.slug,
            'label': culture.native_name or culture.name,
            'joke_count': counts.get((language.code, country.code, culture.slug), 0),
        })
    return {
        'languages': [{'code': lang.code, 'name': lang.name, 'native_name': lang.native_name} for lang in languages],
        'countries': [{
            'code': c.code, 'name': c.name, 'native_name': c.native_name,
            'language_codes': sorted(country_languages[c.code]),
        } for c in countries],
        'cultures': culture_rows,
        'collections': sorted(collections, key=lambda c: (c['locale'], c['culture'])),
    }
