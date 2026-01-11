---
phase: 10-sharing
plan: 02
subsystem: api
tags: [svg, cairosvg, share-cards, social-media, image-generation]

# Dependency graph
requires:
  - phase: 02-data-models
    provides: Joke model structure
  - phase: 05-api-core
    provides: JokeSerializer, JokeListSerializer
provides:
  - SVG template system for themed share cards
  - Automatic share image generation on joke save
  - share_image_url in API responses
affects: [10-sharing, 12-frontend-features]

# Tech tracking
tech-stack:
  added: [cairosvg]
  patterns: [SVG templates with Django templating, auto-generation on model save]

key-files:
  created:
    - jokes/templates/jokes/share_cards/base_card.svg
    - jokes/templates/jokes/share_cards/dad_joke.svg
    - jokes/templates/jokes/share_cards/dark_humor.svg
    - jokes/templates/jokes/share_cards/pun.svg
    - jokes/templatetags/__init__.py
    - jokes/templatetags/mathfilters.py
    - jokes/share_cards.py
    - jokes/migrations/0008_joke_share_image.py
  modified:
    - requirements.txt
    - jokes/models.py
    - jokes/serializers.py

key-decisions:
  - "Tone-based template selection: dad-jokes, dark, puns get themed cards"
  - "Text change detection via _original_text tracking to avoid unnecessary regeneration"
  - "Pre-generate on save, not on request for performance"

patterns-established:
  - "SVG templates with Django template language for dynamic content"
  - "multiply templatetag for tspan y-coordinate calculations"
  - "Model save() override with .update() to avoid recursion"

issues-created: []

# Metrics
duration: 5min
completed: 2026-01-11
---

# Phase 10 Plan 02: Share Cards Summary

**SVG template system with CairoSVG PNG generation, tone-based theming, and automatic share image generation on joke save**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-11T16:26:07Z
- **Completed:** 2026-01-11T16:31:27Z
- **Tasks:** 3
- **Files modified:** 11

## Accomplishments
- Created 4 themed SVG templates (base, dad_joke, dark_humor, pun) for social media share cards
- Added share_image ImageField to Joke model with automatic PNG generation on save
- Implemented text change detection to avoid unnecessary regeneration
- Exposed share_image_url in API responses with absolute URLs

## Task Commits

Each task was committed atomically:

1. **Task 1: Install CairoSVG and create SVG templates** - `4a98383` (feat)
2. **Task 2: Add share_image field with auto-generation** - `5c27fbe` (feat)
3. **Task 3: Add share_image_url to serializers** - `1c657be` (feat)

**Plan metadata:** (pending)

## Files Created/Modified

### Created
- `jokes/templates/jokes/share_cards/base_card.svg` - Default dark theme with red accent
- `jokes/templates/jokes/share_cards/dad_joke.svg` - Warm orange theme for dad jokes
- `jokes/templates/jokes/share_cards/dark_humor.svg` - Dark purple theme for dark humor
- `jokes/templates/jokes/share_cards/pun.svg` - Teal/green theme for puns
- `jokes/templatetags/__init__.py` - Package init for templatetags
- `jokes/templatetags/mathfilters.py` - multiply filter for SVG tspan calculations
- `jokes/share_cards.py` - PNG generation logic with template selection
- `jokes/migrations/0008_joke_share_image.py` - Migration for share_image field

### Modified
- `requirements.txt` - Added cairosvg==2.8.2
- `jokes/models.py` - Added share_image field, _original_text tracking, save override, _generate_share_image method
- `jokes/serializers.py` - Added share_image_url to JokeSerializer and JokeListSerializer

## Decisions Made
- Tone-based template selection (dad-jokes → dad_joke.svg, dark → dark_humor.svg, puns → pun.svg)
- Text change detection via _original_text instance attribute to avoid unnecessary image regeneration
- Pre-generate images on model save rather than on-demand for performance
- Use Django's template system for SVG rendering (same tooling as HTML templates)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness
- Share card infrastructure complete, ready for 10-03 (Share Analytics)
- Existing jokes will need to be saved to generate share images (management command could be added later)
- Cairo library must be installed on deployment server: `brew install cairo` (macOS) or `apt-get install libcairo2-dev` (Linux)

---
*Phase: 10-sharing*
*Completed: 2026-01-11*
