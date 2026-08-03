# Media Share Cards Wave — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship `Docs/superpowers/specs/2026-07-24-media-share-cards-design.md` — media jokes get a poster-composited OG share card; the ordering trap and the takedown-leak are closed.

**Architecture:** Extend the existing cairosvg pipeline — dispatch to a media-card SVG that embeds a downscaled poster/image as a base64 data-URI; regenerate after publish's media copy; blank on takedown.

**Tech Stack:** cairosvg + Pillow (both existing), Django.

## Global Constraints

- Backend tests Django runner NEVER pytest; new tests `jokes/tests_share_cards.py`; reuse tests_media/tests_appeals helpers + temp MEDIA_ROOT + note the share-image patch is now the code UNDER TEST (don't patch it away in these tests).
- Commits plain no footers. Spec values verbatim (1200x630; ~1200px raster downscale; poster is the screened raster; audio→text card + badge).
- MUST NOT regress: text jokes produce byte-identical cards (pin with a hash/dimension test); the wave-1/2 media suites; the appeals quarantine tests.
- No new dependency; base64 data-URI `<image>` in SVG, cairosvg rasterizes.

---

### Task 1: media-card generator + dispatch (text cards unchanged)
**Files:** jokes/share_cards.py (add `_downscale_raster(bytes)->jpeg bytes` via Pillow ≤1200w; `media_share_card_png(joke)` embedding the poster/image as data-URI in a NEW template jokes/templates/jokes/share_cards/media_card.svg; `generate_share_card_png` dispatches media-with-raster → media card, audio/text → existing path), new SVG template.
**Produces:** `generate_share_card_png(joke)` returns a media card for image/video/GIF jokes with a primary raster, the existing text card otherwise; text output unchanged.
**Which raster:** image joke → the display asset file bytes; video/GIF → poster bytes; audio → no raster (text card + 'Audio' badge). Read the MediaAsset/JokeMedia relations; the primary asset is position 0.
**Tests (TDD):** image joke → PNG contains an embedded raster (assert output differs from the text card + is a valid 1200x630 PNG); video joke → uses poster; audio → text card path; text joke → byte-identical to pre-change (pin). Downscale correctness (large raster → ≤1200w before embed).
Commit: `share-cards: poster-composited media share cards with text-card fallback`.

### Task 2: regeneration triggers (ordering trap + takedown leak)
**Files:** jokes/admin.py (approve_and_publish: after the JokeMedia copy loop, explicitly regenerate the joke's share card — call the model's generation with media now present; take_down_joke: blank share_image for removed jokes so the OG card stops serving the poster — and on reverse_appeals restore path, regenerate), possibly jokes/models.py (a small `regenerate_share_image()` public method wrapping _generate_share_image so admin can call it cleanly).
**Produces:** published media jokes have a media card (not text-only); removed jokes' share_image is blank; reversed jokes' card regenerated.
**Tests (TDD):** publish a media submission via approve_and_publish → the resulting joke's share_image is a media card (embedded raster present), NOT the text card generated at Joke.save() time (this is the ordering-trap regression — assert the media is in the final card); take down a media joke → share_image cleared (share_image.name falsy / file removed); reverse the appeal → share_image regenerated as a media card. **CROSS-WAVE:** also add the appeals-wave-owed test — a removed joke's share_image_url does not serve its poster (serialize + assert share_image blank).
Commit: `share-cards: regenerate after publish media-copy; blank on takedown, restore on reversal`.

### Task 3: regression + wrap
Full backend suite green. The appeals-owed share_image leak test lives here or Task 2 — ensure it exists.

---

## Deployment notes
Backend-only wave (share cards are server-generated; share_image_url already consumed by FE OG tags — no FE change needed; verify the FE meta tags read share_image_url, they do). Ships after appeals. Same two-repo deploy is unnecessary — backend push only.
