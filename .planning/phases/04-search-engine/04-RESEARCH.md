# Phase 4: Search Engine - Research

**Researched:** 2026-01-11
**Domain:** PostgreSQL full-text search with Django
**Confidence:** HIGH

<research_summary>
## Summary

Researched PostgreSQL full-text search implementation for Django, focusing on the Joke model with text fields and multiple filter dimensions. The standard approach uses Django's built-in `django.contrib.postgres.search` module with SearchVectorField for pre-computed search vectors, GIN indexes for performance, and optional trigram similarity for typo tolerance.

Key finding: Don't compute `to_tsvector()` on-the-fly in queries. Use a stored `SearchVectorField` with database triggers (via `django-pgtrigger`) to maintain the search index automatically. This approach is orders of magnitude faster and enables efficient GIN index usage.

PostgreSQL full-text search is the right choice for this MVP - it provides sufficient functionality without additional infrastructure. Elasticsearch would be overkill for 100-5000 jokes and adds operational complexity.

**Primary recommendation:** Add SearchVectorField to Joke model, configure GIN index, use django-pgtrigger for automatic updates, combine with TrigramSimilarity for typo tolerance.
</research_summary>

<standard_stack>
## Standard Stack

The established libraries/tools for Django PostgreSQL full-text search:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| django.contrib.postgres | Built-in | Full-text search classes | Official Django support, no dependencies |
| psycopg2-binary | 2.9.x | PostgreSQL adapter | Already in stack |
| django-pgtrigger | 4.17.0 | Automatic SearchVectorField updates | Clean trigger management, avoids manual SQL |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pg_trgm extension | Built-in PG | Trigram similarity | Typo tolerance, fuzzy matching |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| django-pgtrigger | django-tsvector-field | pgtrigger is more actively maintained, broader feature set |
| django-pgtrigger | Raw SQL triggers | pgtrigger is Django-native, manages migrations automatically |
| PostgreSQL FTS | Elasticsearch | Elasticsearch is overkill for <10k records, adds infrastructure |
| PostgreSQL FTS | pg_search (ParadeDB) | Newer, less battle-tested, not needed for MVP scale |

**Installation:**
```bash
pip install django-pgtrigger
```

**Migration for pg_trgm:**
```python
from django.contrib.postgres.operations import TrigramExtension

class Migration(migrations.Migration):
    operations = [TrigramExtension()]
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Approach

```
jokes/
├── models.py          # Add SearchVectorField + trigger
├── managers.py        # Custom manager with search method
├── search.py          # Search query builder (optional)
└── migrations/
    └── XXXX_*.py      # SearchVectorField + GIN index + trigger
```

### Pattern 1: SearchVectorField with Triggers
**What:** Pre-computed search vectors stored in database, auto-updated via triggers
**When to use:** Always for production - this is the performant approach
**Example:**
```python
# models.py
from django.db import models
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
import pgtrigger

class Joke(models.Model):
    text = models.TextField()
    setup = models.TextField(blank=True)
    punchline = models.TextField(blank=True)

    # Pre-computed search vector
    search_vector = SearchVectorField(null=True)

    class Meta:
        indexes = [
            GinIndex(fields=['search_vector'], name='joke_search_idx'),
        ]
        triggers = [
            pgtrigger.UpdateSearchVector(
                name='update_search_vector',
                vector_field='search_vector',
                document_fields=['text', 'setup', 'punchline'],
            )
        ]
```

### Pattern 2: Weighted Search Vectors
**What:** Assign different weights to fields (A=1.0, B=0.4, C=0.2, D=0.1)
**When to use:** When some fields are more important than others
**Example:**
```python
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank

# Build weighted vector
vector = (
    SearchVector('text', weight='A') +
    SearchVector('setup', weight='B') +
    SearchVector('punchline', weight='B')
)

# Search with ranking
Joke.objects.annotate(
    rank=SearchRank(vector, SearchQuery('funny'))
).filter(rank__gte=0.1).order_by('-rank')
```

### Pattern 3: Custom Search Manager
**What:** Centralized search logic in a model manager
**When to use:** Keep views/serializers clean, reusable search logic
**Example:**
```python
# managers.py
from django.db import models
from django.contrib.postgres.search import SearchQuery, SearchRank

class JokeManager(models.Manager):
    def search(self, query_text, filters=None):
        """
        Full-text search with optional filters.

        Args:
            query_text: User's search query
            filters: Dict of filter params (format, age_rating, tones, etc.)
        """
        if not query_text:
            qs = self.all()
        else:
            query = SearchQuery(query_text, search_type='websearch')
            qs = self.annotate(
                rank=SearchRank('search_vector', query)
            ).filter(search_vector=query).order_by('-rank')

        # Apply filters
        if filters:
            if filters.get('format'):
                qs = qs.filter(format__slug=filters['format'])
            if filters.get('age_rating'):
                qs = qs.filter(age_rating__slug=filters['age_rating'])
            if filters.get('tones'):
                qs = qs.filter(tones__slug__in=filters['tones'])
            if filters.get('context_tags'):
                qs = qs.filter(context_tags__slug__in=filters['context_tags'])

        return qs.distinct()
```

### Pattern 4: Trigram Similarity for Fuzzy Matching
**What:** Handle typos and partial matches
**When to use:** As fallback when full-text search returns no results
**Example:**
```python
from django.contrib.postgres.search import TrigramSimilarity

def search_with_fallback(query_text):
    # Try full-text search first
    results = Joke.objects.search(query_text)

    if not results.exists():
        # Fall back to trigram similarity
        results = Joke.objects.annotate(
            similarity=TrigramSimilarity('text', query_text)
        ).filter(similarity__gt=0.3).order_by('-similarity')

    return results
```

### Anti-Patterns to Avoid
- **Computing tsvector on-the-fly:** `filter(body_text__search='query')` generates tsvector per row - use SearchVectorField instead
- **Missing GIN index:** Without index, full table scan required
- **Over-engineering:** Don't add Elasticsearch for <10k records - PostgreSQL FTS is sufficient
- **Ignoring search_type:** Default 'plain' splits words; use 'websearch' for boolean operators
- **Not handling empty queries:** Always check for empty search strings
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Search indexing | Manual tsvector generation | SearchVectorField + trigger | Trigger keeps index in sync automatically |
| Trigger management | Raw SQL triggers | django-pgtrigger | Manages migrations, Django-native |
| Typo tolerance | Custom fuzzy matching | TrigramSimilarity + pg_trgm | PostgreSQL built-in, optimized |
| Result ranking | Custom scoring algorithm | SearchRank | Uses proven tf-idf/BM25-like algorithm |
| Stemming/normalization | Custom text processing | PostgreSQL text search config | Handles language-specific stemming |
| Highlight matches | Custom string manipulation | SearchHeadline | Handles edge cases, configurable |

**Key insight:** PostgreSQL has 20+ years of full-text search development. The built-in functions handle stemming, stop words, ranking, and indexing better than custom code. Django's postgres.search module provides clean Python bindings to all of it.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: On-the-Fly tsvector Computation
**What goes wrong:** Queries are slow (seconds instead of milliseconds)
**Why it happens:** Each row runs `to_tsvector()` during query, can't use GIN index efficiently
**How to avoid:** Use SearchVectorField with pre-computed vectors and GIN index
**Warning signs:** Slow searches even on small datasets, high CPU during search

### Pitfall 2: Missing GIN Index on SearchVectorField
**What goes wrong:** Search works but is slow
**Why it happens:** Without GIN index, PostgreSQL does sequential scan
**How to avoid:** Always add `GinIndex(fields=['search_vector'])` to model Meta
**Warning signs:** EXPLAIN shows Seq Scan instead of Bitmap Index Scan

### Pitfall 3: Search Vector Not Updated
**What goes wrong:** New/edited jokes don't appear in search results
**Why it happens:** SearchVectorField isn't automatically updated on save
**How to avoid:** Use django-pgtrigger's UpdateSearchVector trigger
**Warning signs:** Newly added records missing from search, stale results

### Pitfall 4: Wrong search_type for User Queries
**What goes wrong:** Boolean queries like "dog OR cat" don't work
**Why it happens:** Default search_type='plain' treats OR as literal word
**How to avoid:** Use search_type='websearch' for user-facing search (PostgreSQL 11+)
**Warning signs:** Users report search not finding expected results

### Pitfall 5: Not Handling Empty Search Queries
**What goes wrong:** Empty search crashes or returns nothing
**Why it happens:** SearchQuery('') raises error or matches nothing
**How to avoid:** Check for empty query before creating SearchQuery, return all results
**Warning signs:** 500 errors on empty search, blank search page

### Pitfall 6: Forgetting pg_trgm Extension for Trigram
**What goes wrong:** TrigramSimilarity queries fail
**Why it happens:** pg_trgm extension not installed in database
**How to avoid:** Add TrigramExtension() migration operation
**Warning signs:** DatabaseError mentioning similarity function
</common_pitfalls>

<code_examples>
## Code Examples

Verified patterns from official sources:

### Basic Full-Text Search Setup
```python
# Source: Django 5.1 docs + django-pgtrigger docs
from django.db import models
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
import pgtrigger

class Joke(models.Model):
    text = models.TextField()
    setup = models.TextField(blank=True)
    punchline = models.TextField(blank=True)

    # Search vector field
    search_vector = SearchVectorField(null=True)

    class Meta:
        indexes = [
            GinIndex(fields=['search_vector'], name='joke_search_vector_idx'),
        ]
        triggers = [
            pgtrigger.UpdateSearchVector(
                name='joke_search_vector_trigger',
                vector_field='search_vector',
                document_fields=['text', 'setup', 'punchline'],
            )
        ]
```

### Search Query with Ranking
```python
# Source: Django docs - Full text search
from django.contrib.postgres.search import SearchQuery, SearchRank

def search_jokes(query_text):
    query = SearchQuery(query_text, search_type='websearch')

    return Joke.objects.annotate(
        rank=SearchRank('search_vector', query)
    ).filter(
        search_vector=query
    ).order_by('-rank')
```

### Combined Full-Text + Filters
```python
# Source: Community pattern, verified against Django docs
def search_jokes_with_filters(
    query_text=None,
    format_slug=None,
    age_rating_slug=None,
    tone_slugs=None,
    context_slugs=None,
):
    qs = Joke.objects.all()

    # Full-text search
    if query_text:
        query = SearchQuery(query_text, search_type='websearch')
        qs = qs.annotate(
            rank=SearchRank('search_vector', query)
        ).filter(search_vector=query)

    # Apply filters
    if format_slug:
        qs = qs.filter(format__slug=format_slug)
    if age_rating_slug:
        qs = qs.filter(age_rating__slug=age_rating_slug)
    if tone_slugs:
        qs = qs.filter(tones__slug__in=tone_slugs)
    if context_slugs:
        qs = qs.filter(context_tags__slug__in=context_slugs)

    # Order by rank if searching, else by date
    if query_text:
        qs = qs.order_by('-rank')
    else:
        qs = qs.order_by('-created_at')

    return qs.distinct()
```

### Trigram Similarity Fallback
```python
# Source: Django docs - Trigram similarity
from django.contrib.postgres.search import TrigramSimilarity

def search_with_typo_tolerance(query_text, threshold=0.3):
    # First try full-text search
    query = SearchQuery(query_text, search_type='websearch')
    results = Joke.objects.filter(search_vector=query)

    if results.exists():
        return results.annotate(
            rank=SearchRank('search_vector', query)
        ).order_by('-rank')

    # Fall back to trigram similarity
    return Joke.objects.annotate(
        similarity=TrigramSimilarity('text', query_text)
    ).filter(
        similarity__gt=threshold
    ).order_by('-similarity')
```

### Search Headline for Previews
```python
# Source: Django docs - SearchHeadline
from django.contrib.postgres.search import SearchHeadline, SearchQuery

def search_with_highlights(query_text):
    query = SearchQuery(query_text)

    return Joke.objects.annotate(
        rank=SearchRank('search_vector', query),
        headline=SearchHeadline(
            'text',
            query,
            start_sel='<mark>',
            stop_sel='</mark>',
            max_words=50,
            min_words=20,
        )
    ).filter(search_vector=query).order_by('-rank')
```

### Migration for pg_trgm Extension
```python
# Source: Django docs
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('jokes', 'XXXX_previous'),
    ]

    operations = [
        TrigramExtension(),
    ]
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

What's changed recently:

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual SQL triggers | django-pgtrigger | 2021+ | Much cleaner trigger management |
| search_type='plain' | search_type='websearch' | PostgreSQL 11 (2018) | Better user query parsing |
| Separate search service | PostgreSQL FTS | Ongoing | FTS now handles most use cases without Elasticsearch |
| django-tsvector-field | django-pgtrigger | 2023+ | pgtrigger more actively maintained, broader features |

**New tools/patterns to consider:**
- **pg_search (ParadeDB):** BM25 ranking in PostgreSQL, Elasticsearch-like features without separate service. Worth watching but not needed for MVP.
- **Generated columns (PostgreSQL 12+):** Alternative to triggers for simple cases, but django-pgtrigger handles complex scenarios better.

**Deprecated/outdated:**
- **Computing tsvector in WHERE clause:** Always use pre-computed SearchVectorField
- **Elasticsearch for small datasets:** PostgreSQL FTS is sufficient for <100k records
- **Manual trigger SQL:** Use django-pgtrigger for Django-managed triggers
</sota_updates>

<open_questions>
## Open Questions

Things that couldn't be fully resolved:

1. **Language configuration for jokes**
   - What we know: PostgreSQL supports language-specific stemming (english, simple, etc.)
   - What's unclear: Should jokes use 'english' config (stemming) or 'simple' (no stemming)?
   - Recommendation: Start with 'english' for MVP (default). Jokes are primarily English text where stemming helps (e.g., "running" matches "run"). Can adjust based on user feedback.

2. **Trigram index performance at scale**
   - What we know: GIN/GiST indexes on trigrams can be large
   - What's unclear: Performance impact with 5k+ jokes
   - Recommendation: Don't add trigram index initially. Add TrigramSimilarity as query-time fallback. Add index only if needed based on performance testing.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [Django 5.1 Full-text Search Documentation](https://docs.djangoproject.com/en/5.1/ref/contrib/postgres/search/) - All SearchVector, SearchQuery, SearchRank examples
- [django-pgtrigger Documentation](https://django-pgtrigger.readthedocs.io/en/4.17.0/) - UpdateSearchVector trigger pattern
- [PostgreSQL 18 Full-Text Search Documentation](https://www.postgresql.org/docs/current/textsearch.html) - Index types, configuration

### Secondary (MEDIUM confidence)
- [pganalyze - Efficient Postgres Full Text Search in Django](https://pganalyze.com/blog/full-text-search-django-postgres) - Performance patterns, verified against official docs
- [pganalyze - Understanding GIN Indexes](https://pganalyze.com/blog/gin-index) - GIN index characteristics
- [Neon - PostgreSQL Full-Text Search vs Elasticsearch](https://neon.com/blog/postgres-full-text-search-vs-elasticsearch) - When to use each

### Tertiary (LOW confidence - needs validation)
- None - all critical findings verified against primary sources
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: PostgreSQL full-text search via Django
- Ecosystem: django-pgtrigger, pg_trgm extension
- Patterns: SearchVectorField + triggers, weighted vectors, trigram fallback
- Pitfalls: On-the-fly computation, missing indexes, stale vectors

**Confidence breakdown:**
- Standard stack: HIGH - Django official docs, well-documented
- Architecture: HIGH - Patterns from official docs and maintained packages
- Pitfalls: HIGH - Common issues documented in multiple sources
- Code examples: HIGH - From Django docs and django-pgtrigger docs

**Research date:** 2026-01-11
**Valid until:** 2026-02-11 (30 days - Django/PostgreSQL ecosystem stable)
</metadata>

---

*Phase: 04-search-engine*
*Research completed: 2026-01-11*
*Ready for planning: yes*
