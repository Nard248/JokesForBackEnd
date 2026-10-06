"""Pure, no-write validation and coverage accounting for authored joke bundles.

Country describes the setting/context of a collection, never its author's identity.
Each record counts once toward one primary category within its collection.
"""

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CATEGORIES = (
    'wholesome', 'office-proper', 'dad', 'kid-safe', 'nerd',
    'surreal', 'dark', 'edgy', 'puns',
)
THEMES = {
    'work', 'family', 'food', 'tech', 'school', 'dating', 'animals',
    'science', 'travel', 'money', 'weather', 'mondays', 'puns',
}
FORMATS = {'oneliner', 'setup', 'story', 'anti', 'observ'}
AGE_RATINGS = {'kid-safe', 'family-friendly', 'teen', 'adult', 'mature'}
SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
RECORD_FIELDS = {
    'id', 'collection', 'category', 'format', 'text', 'setup', 'punchline',
    'age_rating', 'themes', 'cultural_note', 'related_countries',
}


@dataclass(frozen=True)
class Corpus:
    manifest: dict
    records: list[dict]
    coverage: list[dict]

    @property
    def complete(self):
        return all(row['missing'] == 0 for row in self.coverage)


def fingerprint(text):
    """Catch cosmetic variants without transliterating or stripping accents."""
    normalized = unicodedata.normalize('NFKC', text).casefold()
    return ''.join(char for char in normalized if char.isalnum())


def _text(obj, field, *, limit=100, optional=False):
    value = obj.get(field, '')
    if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
        raise ValueError(f'{field} must be a nonempty string of at most {limit} characters')
    if any(unicodedata.category(c) == 'Cc' and c not in '\n\t\r' for c in value):
        raise ValueError(f'{field} contains control characters')
    return unicodedata.normalize('NFC', value).strip()


def _slug(obj, field, *, limit=100):
    value = _text(obj, field, limit=limit)
    if value != obj.get(field):
        raise ValueError(f'{field} must use canonical spelling without surrounding whitespace')
    if not SLUG.fullmatch(value):
        raise ValueError(f'Invalid {field}: {value!r}')
    return value


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'Cannot read JSON bundle file {path.name}: {exc}') from exc


def load_corpus(manifest_path, *, require_complete=False):
    path = Path(manifest_path).resolve()
    manifest = _read_json(path)
    if (not isinstance(manifest, dict) or type(manifest.get('version')) is not int
            or manifest.get('version') != 1):
        raise ValueError('Manifest version must be 1')
    provenance = manifest.get('provenance', {})
    if (not isinstance(provenance, dict) or provenance.get('kind') != 'ai_original'
            or provenance.get('native_reviewed') is not False):
        raise ValueError('Generated corpus must declare ai_original and native_reviewed=false')
    _text(provenance, 'description', limit=2000)
    collections = manifest.get('collections')
    if not isinstance(collections, list) or not collections:
        raise ValueError('Manifest must contain collection targets')
    by_id, combinations = {}, set()
    for collection in collections:
        if not isinstance(collection, dict):
            raise ValueError('Each collection must be an object')
        key = _slug(collection, 'id')
        language = _text(collection, 'language', limit=10)
        country = _text(collection, 'country', limit=2)
        if language != collection['language'] or country != collection['country']:
            raise ValueError(f'Language and country must be canonical codes for {key}')
        culture = _slug(collection, 'culture')
        if not re.fullmatch(r'[a-z]{2,3}', language):
            raise ValueError(f'Invalid language code for {key}')
        if not re.fullmatch(r'[A-Z]{2}', country):
            raise ValueError(f'Invalid country code for {key}')
        if collection.get('locale') != f'{language}-{country}':
            raise ValueError(f'Collection locale must match language-country for {key}')
        for field in ('language_name', 'language_native_name', 'country_name',
                      'country_native_name', 'culture_name', 'culture_native_name'):
            _text(collection, field)
        _text(collection, 'description', limit=2000)
        categories = collection.get('categories')
        if (not isinstance(categories, list) or not categories
                or any(not isinstance(x, str) or x not in CATEGORIES for x in categories)
                or len(set(categories)) != len(categories)):
            raise ValueError(f'Invalid category targets for {key}')
        target = collection.get('target_per_category')
        if type(target) is not int or not 1 <= target <= 100000:
            raise ValueError(f'Invalid target_per_category for {key}')
        combo = (language, country, culture)
        if key in by_id or combo in combinations:
            raise ValueError(f'Duplicate collection: {key}')
        by_id[key] = collection
        combinations.add(combo)

    country_codes = {collection['country'] for collection in collections}
    context_countries = manifest.get('context_countries', [])
    if not isinstance(context_countries, list):
        raise ValueError('context_countries must be a list of country definitions')
    for country in context_countries:
        if not isinstance(country, dict):
            raise ValueError('Each context country must be an object')
        code = _text(country, 'code', limit=2)
        if code != country['code'] or not re.fullmatch(r'[A-Z]{2}', code):
            raise ValueError('Context country codes must be canonical uppercase ISO codes')
        if code in country_codes:
            raise ValueError(f'Duplicate country definition: {code}')
        _text(country, 'name')
        _text(country, 'native_name')
        country_codes.add(code)

    files = manifest.get('files')
    if not isinstance(files, list) or not files or any(not isinstance(x, str) for x in files):
        raise ValueError('Manifest files must be a nonempty list of relative paths')
    if len(set(files)) != len(files):
        raise ValueError('Duplicate files in manifest')
    records, keys, texts = [], set(), set()
    counts = Counter()
    for filename in files:
        record_path = (path.parent / filename).resolve()
        if not record_path.is_relative_to(path.parent) or Path(filename).is_absolute():
            raise ValueError('Corpus files must stay inside the manifest directory')
        entries = _read_json(record_path)
        if not isinstance(entries, list):
            raise ValueError(f'{filename} must contain a JSON array')
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError(f'{filename}: each record must be an object')
            if unknown := set(item) - RECORD_FIELDS:
                raise ValueError(f'Unknown record fields: {sorted(unknown)}')
            record = dict(item)
            key = _slug(record, 'id', limit=160)
            if key in keys:
                raise ValueError(f'Duplicate record id: {key}')
            collection_key = _slug(record, 'collection')
            collection = by_id.get(collection_key)
            if collection is None:
                raise ValueError(f'{key}: unknown collection {collection_key}')
            related = record.get('related_countries', [])
            if (not isinstance(related, list)
                    or any(not isinstance(code, str) or code not in country_codes
                           or code == collection['country'] for code in related)
                    or len(set(related)) != len(related)):
                raise ValueError(f'{key}: related_countries must contain distinct, known secondary country codes')
            record['related_countries'] = related
            if record.get('category') not in collection['categories']:
                raise ValueError(f'{key}: category must belong to collection targets')
            if not isinstance(record.get('format'), str) or record['format'] not in FORMATS:
                raise ValueError(f'{key}: unsupported format')
            if not isinstance(record.get('age_rating'), str) or record['age_rating'] not in AGE_RATINGS:
                raise ValueError(f'{key}: unsupported age_rating')
            for field in ('text', 'setup', 'punchline', 'cultural_note'):
                record[field] = _text(record, field, limit=10000, optional=field in ('setup', 'punchline'))
            if record['format'] == 'setup' and not (record['setup'] and record['punchline']):
                raise ValueError(f'{key}: setup format requires setup and punchline')
            if record['format'] != 'setup' and (record['setup'] or record['punchline']):
                raise ValueError(f'{key}: separate setup/punchline fields require setup format')
            if record['format'] == 'setup' and fingerprint(record['text']) != fingerprint(
                record['setup'] + ' ' + record['punchline']
            ):
                raise ValueError(f'{key}: text must contain the setup and punchline in order')
            themes = record.get('themes')
            if (not isinstance(themes, list) or not themes
                    or any(not isinstance(x, str) or x not in THEMES for x in themes)
                    or len(set(themes)) != len(themes)):
                raise ValueError(f'{key}: themes must contain known, distinct theme slugs')
            text_key = (collection['language'], fingerprint(record['text']))
            if not text_key[1]:
                raise ValueError(f'{key}: text must contain letters or numbers')
            if text_key in texts:
                raise ValueError(f'Duplicate joke text in language {text_key[0]}: {key}')
            keys.add(key)
            texts.add(text_key)
            counts[(collection_key, record['category'])] += 1
            records.append(record)

    coverage = [
        {'collection': collection['id'], 'locale': collection['locale'],
         'category': category, 'count': counts[(collection['id'], category)],
         'target': collection['target_per_category'],
         'missing': max(0, collection['target_per_category'] - counts[(collection['id'], category)])}
        for collection in collections for category in collection['categories']
    ]
    corpus = Corpus(manifest=manifest, records=records, coverage=coverage)
    if require_complete and not corpus.complete:
        missing = '; '.join(
            f"{row['collection']}/{row['category']}: missing {row['missing']}"
            for row in coverage if row['missing']
        )
        raise ValueError(f'Corpus targets incomplete: {missing}')
    return corpus


# Categories whose records are mature by policy, whatever their age rating:
# they import as tier_2 (adult + explicit opt-in) and are never published by an
# AI-only screen. This is an importer rule layered on top of the age-rating
# derivation in jokes.serving.content_tier_for_age_rating, not a replacement.
MATURE_CATEGORIES = frozenset({'dark', 'edgy'})
LAUNCH_SET_METHOD_LIMIT = 200


def load_launch_set(path, corpus):
    """Validate a launch-set file against ``corpus`` (no database access).

    Shape: ``{"version": 1, "method": str, "screened_at": "YYYY-MM-DD",
    "publish": [record key, ...], "blocked": {record key: reason}}``. Every key
    must exist in the corpus; a key cannot be both published and blocked; and a
    mature-category (dark/edgy) record can never be published by this file.
    """
    data = _read_json(Path(path).resolve())
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('Launch set version must be 1')
    if unknown := set(data) - {'version', 'method', 'screened_at', 'publish', 'blocked'}:
        raise ValueError(f'Unknown launch set fields: {sorted(unknown)}')
    _text(data, 'method', limit=LAUNCH_SET_METHOD_LIMIT)
    screened_at = data.get('screened_at')
    if not isinstance(screened_at, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', screened_at):
        raise ValueError('Launch set screened_at must be a YYYY-MM-DD date')
    publish = data.get('publish')
    if not isinstance(publish, list) or any(not isinstance(key, str) for key in publish):
        raise ValueError('Launch set publish must be a list of record keys')
    if len(set(publish)) != len(publish):
        raise ValueError('Launch set publish contains duplicate keys')
    blocked = data.get('blocked')
    if not isinstance(blocked, dict) or any(
        not isinstance(reason, str) or not reason.strip() for reason in blocked.values()
    ):
        raise ValueError('Launch set blocked must map record keys to nonempty reasons')
    categories = {record['id']: record['category'] for record in corpus.records}
    if unknown := sorted((set(publish) | set(blocked)) - categories.keys()):
        raise ValueError(f'Launch set names unknown record keys: {unknown[:20]}')
    if both := sorted(set(publish) & set(blocked)):
        raise ValueError(f'Launch set keys cannot be both published and blocked: {both[:20]}')
    if mature := sorted(key for key in publish if categories[key] in MATURE_CATEGORIES):
        raise ValueError(
            f'Launch set cannot publish {len(mature)} dark/edgy record(s); they need native '
            f'review: {mature[:20]}'
        )
    return {**data, 'publish': list(publish), 'blocked': dict(blocked)}
