"""Owner-scoped content inventory and explainable metadata recommendations."""
from django.db.models import Q

from creator_insights.privacy import eligible_analytics_users
from creator_insights.services import _joke_count_subquery, resolve_creator_jokes
from jokes.models import Joke, JokeReaction, JokeView, SavedJoke, ShareEvent

SORTS = {
    'newest': '-created_at', 'oldest': 'created_at', 'views': '-view_count',
    'reactions': '-reaction_count', 'saves': '-save_count', 'shares': '-share_count',
}


def content_queryset(creator, filters):
    jokes = resolve_creator_jokes(creator)
    for param, field in (
        ('joke_format', 'format__slug'), ('language', 'language__code'),
        ('theme', 'context_tags__slug'), ('category', 'tones__slug'),
    ):
        if filters.get(param):
            jokes = jokes.filter(**{field: filters[param]})
    if filters.get('q'):
        q = filters['q']
        jokes = jokes.filter(Q(text__icontains=q) | Q(setup__icontains=q) | Q(punchline__icontains=q))
    # Deduplicate attribution/taxonomy joins before adding metric subqueries.
    # An outer DISTINCT would evaluate every metric for the entire inventory
    # even for pagination counts and a small newest-first page.
    jokes = Joke.objects.filter(pk__in=jokes.order_by().values('pk')).select_related(
        'format', 'language',
    ).prefetch_related('context_tags', 'tones')
    eligible = Q(user__in=eligible_analytics_users().exclude(pk=creator.pk))
    annotations = {}
    for name, model, date_field in (
        ('view_count', JokeView, 'viewed_date'),
        ('reaction_count', JokeReaction, 'created_at__date'),
        ('save_count', SavedJoke, 'created_at__date'),
        ('share_count', ShareEvent, 'created_at__date'),
    ):
        window = Q(**{f'{date_field}__range': (filters['start'], filters['end'])})
        annotations[name] = _joke_count_subquery(model, since_q=window, extra_q=eligible)
    return jokes.annotate(**annotations).order_by(SORTS[filters['sort']], 'pk')


def content_row(joke):
    themes = [{'slug': item.slug, 'name': item.name} for item in joke.context_tags.all()]
    categories = [{'slug': item.slug, 'name': item.name} for item in joke.tones.all()]
    missing = []
    if not themes:
        missing.append('themes')
    if not categories:
        missing.append('categories')
    # Required database format/language fields are already populated. This score
    # measures discovery metadata completeness, never joke quality or safety.
    score = round((4 - len(missing)) / 4 * 100)
    if missing:
        recommendation = {
            'kind': 'complete_metadata',
            'detail': 'Add ' + ' and '.join(missing) + ' to make this material easier to find.',
            'sample_size': joke.view_count,
        }
    else:
        recommendation = {
            'kind': 'collect_feedback',
            'detail': 'Discovery metadata is complete. Gather feedback before drawing performance conclusions.',
            'sample_size': joke.view_count,
        }
    return {
        'id': joke.pk, 'text': joke.text, 'setup': joke.setup, 'punchline': joke.punchline,
        'format': {'slug': joke.format.slug, 'name': joke.format.name},
        'language': {'code': joke.language.code, 'name': joke.language.name},
        'themes': themes, 'categories': categories,
        'created_at': joke.created_at.isoformat(),
        'views': joke.view_count, 'reactions': joke.reaction_count,
        'saves': joke.save_count, 'share_initiations': joke.share_count,
        'metadata_missing': missing, 'metadata_completeness': score,
        'recommendation': recommendation,
    }


MEASUREMENT_NOTES = [
    'Analytics include signed-in adults who currently opt in to share analytics; anonymous visits are not measured.',
    'Views are recorded opens or reveals, not laughs or completed reads.',
    'Reactions and saves count current relationships created in the selected window, not historical totals.',
    'Shares are share initiations; downstream clicks and recipient reads are not measured.',
    'Dates use UTC. The window filters activity, not content creation. Metadata describes the current version.',
]
