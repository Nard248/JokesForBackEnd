# Landing Page Design — 2026-07-16

## Goal
Replace the weak, in-app-shell `HomePage` with a dedicated, conversion-optimized
marketing landing at `/` for anonymous visitors: introduce the concept, sell it,
and drive registration via honest psychological triggers. Authenticated users at
`/` redirect into the app (they never see the pitch).

## Positioning
**Reader-first** (broadest top-of-funnel) with a **secondary creator hook**.
Voice: confident, witty, editorial — "a bit of sale," never hypey.

## Brand (reuse, don't reinvent)
Warm off-white ground (`#FBFAF7`/`#F8F6F6`), purple `#6A1CF6` + lime `#CAFD00`
accents, **Fraunces** for display headlines, Epilogue / Plus Jakarta Sans for UI.
Reuse the format-aware card skins (`JokeRenderer`/`FlowJokeCard`).

## Hero — the "try-it" card
An interactive joke card: setup visible, **punchline blurred**; one tap reveals it
(a free taste of the signature mechanic), then a soft "Loved it? Sign up to keep
reading →". Alongside: display headline + subhead + primary CTA ("Start reading
free →") + trust line ("Free · no card · 10 fresh jokes a day"). The **curiosity
gap is the hero.**

## Sections (top → bottom) + the trigger each plants
1. **Hero (try-it card)** — curiosity gap + instant gratification + free hook.
2. **What it is, in 3 beats** (Discover → Reveal → Keep) — the daily ritual / habit.
3. **Six formats showcase** (real card skins) — variety + product-as-hero.
4. **Why it's different** (3–4 lines: "curated, not scraped"; "every format,
   crafted"; "a habit, not a doomscroll") — contrast vs. the meme-feed alternative.
5. **Creator hook band** ("Funny? Turn it into a following." — publish, grow,
   analytics, monetize) — aspiration/status. Secondary CTA "Become a creator →".
6. **Get in early** (founding-reader / early-access) — honest exclusivity/FOMO.
7. **Final CTA** ("Your first joke is waiting. → Start reading free") + footer
   (privacy/terms/cookie links, small "Sign in") — loss aversion + friction removal.

## Trigger philosophy (IMPORTANT)
Every trigger is honest. **No fabricated social proof / invented user counts** —
we just removed fake numbers; the landing must not reintroduce any. Founding-reader
framing is the truthful substitute until real numbers exist. Hero/showcase jokes
are curated **real** example jokes (legitimate marketing content, not fake stats
or fake identities).

Triggers used: curiosity gap (hero reveal), instant gratification / low friction,
daily ritual / habit, loss aversion ("waiting for you"), early-access / founding
member, positioning contrast, aspiration (creator).

## Scope & technical
- New `LandingPage` component with its **own** marketing header/footer (logo,
  "Sign in", "Start free") — **not** wrapped in `FlowAppShell`.
- Routing: `/` → `LandingPage` for anon; **authenticated users at `/` redirect**
  to the app home (`/daily` or `/flow-canvas`). All CTAs → `/register`;
  "Sign in" → `/login`.
- **Mobile-first responsive** (most traffic is mobile; the app currently isn't
  responsive — the landing must be).
- Hero/showcase render from a small **curated set of real jokes** (reliable, no
  API dependency to paint the pitch).

## Out of scope (v1)
Anonymous landing telemetry/A-B testing; any hard paywall on the landing itself.
