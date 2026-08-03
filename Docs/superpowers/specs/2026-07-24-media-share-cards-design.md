# Media Share Cards — Design — 2026-07-24

Feature 2 of the MVP slate (after appeals). Owner-approved feature; this doc
is the design to be reviewed before its plan.

## Goal

Shared image/video/audio jokes get an Open Graph card that shows the actual
media (a poster/thumbnail), not today's text-only card of the setup — so
every share of a media joke is a visual ad. Text jokes are unchanged.

## Current state (verified)

`jokes/share_cards.py::generate_share_card_png` renders an SVG (cairosvg →
1200x630 PNG) from `joke.text` + primary-tone template. `Joke.save()`
regenerates it when `text` changes (`_generate_share_image`), stored on
`Joke.share_image`, exposed as `share_image_url` (NOT stripped by the
paywall — public OG by design). The image joke's setup IS its text (backfill).

## Two load-bearing facts

1. **Ordering trap.** `approve_and_publish` creates the `Joke` (fires
   `save()` → card generated) and copies `JokeMedia` rows AFTER. So at card
   time the media doesn't exist; text never changes later, so the card is
   never refreshed. → Publish must explicitly regenerate the card AFTER the
   media copy.
2. **Poster is the safe raster.** Image → the display derivative
   (`media-assets/.../image.webp`); video/GIF → the extracted `poster.jpg`
   (SafeSearch-screened, teaser-safe — same frame the reader sees before
   reveal); audio → NO visual, falls back to the text card (an audio badge
   variant). Never embed a video frame that wasn't screened.

## Design

- New `media_share_card_png(joke)` path: when the joke's format is media and
  it has a primary media asset with a poster-or-image raster, render a
  media-card SVG that embeds that raster as a base64 `data:` URI in an
  `<image>` element (cairosvg rasterizes it — no new dependency), composited
  with: the setup text as an overlaid caption band, the JokesFor brand
  stripe, and a format badge (▶ Video / GIF / Photo). Audio → the existing
  text card + an "Audio" badge (no media embed).
- `generate_share_card_png` dispatches: media-with-raster → media card;
  else → existing text card. Text jokes: byte-identical output (regression).
- The embedded raster is downscaled server-side (Pillow, already a dep) to
  ~1200px-wide JPEG before base64 to keep the SVG/PNG small and fast — the
  poster is ≤720p already, image derivative ≤1600px, so one cheap resize.
- **Locked/paywall:** the share card is intentionally public OG (unchanged
  policy) — it shows the POSTER (the teaser frame), never a
  paywalled-reveal frame. For image jokes the whole image IS the payoff, so
  the card shows it: acceptable because (a) it's the creator's own
  promotional surface, (b) OG crawlers need it, (c) it matches today's
  text-card behavior of showing the joke's public face. Documented decision.

## Regeneration triggers

- `approve_and_publish`: after `JokeMedia` copy, call the joke's card
  (re)generation explicitly (new small method or direct call) — the fix for
  the ordering trap.
- Takedown/quarantine: the share card is a SEPARATE generated PNG (not the
  media asset) embedding a downscaled copy — on takedown it must ALSO be
  removed/regenerated-blank, else the OG card leaks the poster of a removed
  joke. → `take_down_joke` clears/blanks `share_image` for removed jokes
  (add to the action). On reversal, regenerate.
- Media replacement in an existing published joke: out of scope (media jokes
  aren't edited post-publish in the current product).

## Out of scope

Animated cards; per-tone media templates (one media template); Twitter
player cards / video OG; share-card A/B; audio waveform rendering.

## Risks

- Card generation now does a Pillow resize + base64 in `save()`/publish —
  still synchronous, still cheap (one ≤720p decode + encode), within the
  established in-request budget. Bounded.
- Takedown must blank the OG card or removed media leaks via the crawler
  cache — explicitly handled above; a test must assert share_image is
  cleared on takedown.
