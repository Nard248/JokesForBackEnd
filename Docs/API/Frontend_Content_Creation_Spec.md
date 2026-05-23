# Frontend Spec — Content Creation (Creator Authoring)

**Audience:** Frontend engineer (or AI assistant operating one) who has already built the rest of the Jokes For React app (auth, home, daily joke, search, collections, settings) and is now picking up the creator authoring feature cold.

**Status:** Draft v1.0 — 2026-05-19. Ready to brief implementation.

**Companion docs:**
- `Docs/API/Frontend_Integration_Handout.md` — broader API surface, per-component wiring guide
- `Docs/Pivot_Plan.md` — overall product pivot (vibes, mystery box, streaks, packs, etc.)
- `docs/superpowers/specs/2026-05-19-creator-content-system-design.md` — backend design behind this feature

**Scope of this document:** Everything a frontend engineer needs to ship the **Content Creation** experience end-to-end — business framing, UX flows, every screen, every state, exact API payloads, validation patterns, design notes, accessibility, analytics, acceptance criteria, and the small set of backend enhancements that must land before the frontend can complete.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Context — The Business Idea](#2-product-context--the-business-idea)
3. [The Creator Experience — Strategy & Principles](#3-the-creator-experience--strategy--principles)
4. [Information Architecture & Navigation](#4-information-architecture--navigation)
5. [User Journeys](#5-user-journeys)
6. [Screen-by-Screen Specifications](#6-screen-by-screen-specifications)
7. [Per-Format Authoring Deep Dive](#7-per-format-authoring-deep-dive)
8. [API Contract — Exact Endpoints](#8-api-contract--exact-endpoints)
9. [Component Inventory](#9-component-inventory)
10. [State Management & Data Flow](#10-state-management--data-flow)
11. [Validation Patterns](#11-validation-patterns)
12. [Draft Lifecycle & Autosave](#12-draft-lifecycle--autosave)
13. [Error Handling Matrix](#13-error-handling-matrix)
14. [Visual Design Notes](#14-visual-design-notes)
15. [Accessibility Requirements](#15-accessibility-requirements)
16. [Performance & Loading States](#16-performance--loading-states)
17. [Analytics Events](#17-analytics-events)
18. [Acceptance Criteria](#18-acceptance-criteria)
19. [Required Backend Enhancements](#19-required-backend-enhancements)
20. [Out of Scope / Future](#20-out-of-scope--future)
21. [Open Product Questions](#21-open-product-questions)

---

## 1. Executive Summary

**What we're building:** A web-based authoring experience that lets any signed-in user write a joke in one of six formats, save drafts that autosave as they type, preview how the joke will render to readers, and submit for moderator review. After approval, their joke becomes part of the public corpus.

**Why it matters:**
- **Content depth at zero marginal cost.** A search engine for jokes needs thousands of jokes. Editors can't curate thousands by hand; user submissions are the only economical path to depth.
- **Identity hook.** Once a user has published a joke, they have something *at stake* in the platform — their byline. This drives D30 retention disproportionately.
- **Differentiation.** Each format has a distinctive renderer (knock-knock dialogue bubbles, observational italic quote, anti-joke footer, etc.). Letting creators author into the same shape the renderer reads gives the platform an editorial-design feel competitors don't have.

**Where it sits in the app:** New top-level route `/create`, accessible from the global header (`+` icon or "Submit a joke" CTA). Visible to authenticated users only.

**Critical constraint:** This is the first feature where the creator-side data model is identical to the reader-side rendering model. The smart pattern is to extract a shared `<JokeRenderer>` component that the daily-joke page, search results, and the creator preview pane all mount with the same payload shape.

**Backend status:** Backend support for per-format validation, the `lines` JSONField for knock-knock, `culture_tags`, and the moderator approval pipeline shipped on branch `feat/creator-content-system` (10 commits, 38 tests passing). **One small backend gap remains** that blocks autosave UX: there is no endpoint to create a row with `status='draft'` (see §19). That gap is ~30 minutes of backend work and must land before this frontend work begins.

---

## 2. Product Context — The Business Idea

### 2.1 What Jokes For is

Jokes For is a global humor discovery platform — positioned as **a search engine for jokes**, not a feed.

The platform exists because:
- Humor is universal but its index is fragmented across Reddit, Twitter, joke websites of varying quality, and books that aren't searchable.
- Search engines optimize for facts, not laughter. Google "wedding joke" and you get listicles, not retrieval.
- People want jokes for *contexts* — a wedding toast, a presentation icebreaker, a kid's bedtime, a date night, a colleague's birthday Slack. The corpus needs to be tagged accordingly.

**Mission:** Help anyone find the right joke for the right moment, in the right tone, for the right audience, in the right format.

### 2.2 The four-axis taxonomy

The product organizes humor on four axes — three are stored on every joke, one is a curated preset:

| Axis | Question it answers | Examples | Cardinality |
|---|---|---|---|
| **Format** | *How does it land?* | one-liner, setup→punchline, knock-knock, story, anti-joke, observational | one per joke |
| **Theme** | *What is it about?* | work, family, food, tech, school, dating, animals, science, travel, money, weather | many per joke |
| **Category** | *How does it feel?* | wholesome, office-proper, dad, kid-safe, nerd, surreal, dark, edgy | many per joke |
| **Vibe** | *Which curated humor flavor?* | Office, Dad jokes, Puns, Dark humor, Nerd, Surreal, Wholesome, Observational, One-liners, Date night, Kids OK, Absurd | many per joke + many per user |

**Important for the creator editor:** Creators tag with Theme + Category (the design vocabulary surfaces these as `themes` and `categories` in the API, but the underlying DB models are still named `ContextTag` and `Tone` — the API accepts both names and prefers the new names. **Always use `themes` and `categories` in new frontend code.**)

Vibes are NOT directly tagged on jokes; they're derived presets over Format/Theme/Category. Creators do not pick vibes when authoring.

### 2.3 The product's three loops, and where creator content fits

The pivot plan (`Docs/Pivot_Plan.md`) frames the product as three reinforcing loops:

1. **The discovery loop:** Daily joke → reactions → mystery box → search → save → return tomorrow
2. **The commitment loop:** Streak grid → freeze days → ritual nudges → tomorrow teaser
3. **The contribution loop** ← **this feature** → Author a joke → submit → moderation → publish → byline → seen on others' feeds

The contribution loop is what we are building. Without it, users are pure consumers; with it, a subset of users become creators, which:
- Grows the corpus (content depth, the platform's moat)
- Creates social identity (creators have something at stake)
- Surfaces Top Jokesters (a leaderboard feature that already exists, but is empty without contributions)

### 2.4 Target creator personas

Three rough creator types we expect, and the UX implications:

| Persona | Behavior | UX implication |
|---|---|---|
| **The hobbyist** | Writes one good joke in a quiet moment, then leaves for weeks. Maybe returns when an approval email lands. | Editor must be inviting from second one. No tutorial required. Quick exit/save without friction. |
| **The grinder** | Submits 5-20 jokes in a session. Likely a comedian, a writer, or someone testing material. | My Drafts must scale gracefully; bulk visibility into status; batch resubmit. |
| **The remix-er** | Sees a knock-knock template, makes their own variant. May not have written original humor before. | Format examples must be inspiring, not intimidating. Show one strong example per format. |

Designing for all three at once: a clean blank-slate editor that *also* surfaces 1-2 format examples within reach, *also* makes batch management easy, *also* never punishes interruption with lost work.

### 2.5 Business value of this specific feature

Concrete success indicators we'll measure (see §17 for the events):

- **Submission volume**: number of jokes submitted per active user per week
- **Approval rate**: % of submissions that reach `published` (proxies content quality + moderator efficiency)
- **Creator return rate**: % of creators who submit a 2nd joke within 30 days of their first
- **Time-to-first-submission**: from signup to first submission (funnel health)
- **Format mix**: are creators using all six formats or piling into one?

The UX choices in this spec are calibrated to optimize approval rate and creator return rate — both of which depend on creators not getting frustrated mid-submission.

---

## 3. The Creator Experience — Strategy & Principles

### 3.1 The five principles guiding every UX decision

1. **Show, don't tell.** Every format has an example visible in the picker. The editor has a live preview. Creators see exactly how their joke will render to readers before submitting.
2. **The editor adapts to the format, not the other way around.** A knock-knock editor has a dialogue builder. A story editor has a word counter. A one-liner editor is a single field. Same backend, six different UIs.
3. **Never lose work.** Autosave on every meaningful change. The browser tab can close, the network can drop, the user can navigate away — the draft is recoverable.
4. **Validation is conversational, not punitive.** Errors appear next to the field that caused them, in the moment the user can act on them. Submit buttons only enable when the submission would actually succeed.
5. **Moderation is a conversation, not a black box.** Pending submissions show "with our reviewers since [time]". Rejected submissions show *why* and what to do next. Published submissions celebrate the user.

### 3.2 The editor's mental model

The creator's mental model when they enter the editor:

```
I want to write [format] about [theme] that feels [category],
appropriate for [age], probably in [language].
Let me write it. Let me see how it will look. Let me submit.
```

The editor surfaces these decisions in roughly that order:

1. **Pick a format** (separate screen — the picker)
2. **Write the content** (format-specific inputs, the main work)
3. **Tag classification** (theme, category, age rating, optional culture/language) — secondary, collapsible
4. **Preview** (live, never hidden)
5. **Save draft / Submit for review** (always reachable)

### 3.3 The reader's view of creator content

After approval, a creator's joke appears identically to any other joke in the corpus — same renderer, same shape, same prominence. There is currently no creator byline on the joke detail (the design hasn't specified one). The creator's signal of authorship is:

- Their own "Published" list in the Creator Hub
- The Top Jokesters leaderboard (separate feature, already exists)
- Eventually: byline on the joke detail page (deferred — see §20)

### 3.4 What we are explicitly NOT building (per YAGNI scope set 2026-05-19)

- Per-joke presentation styling overrides (colors, fonts, reveal pacing) — deferred
- Rich media attachments (image, audio, GIF) — deferred, separate compliance lift
- Block-based composition (Notion-style) — deferred
- AI-assisted joke writing — deferred
- Co-authored jokes — deferred
- Joke editing after publication — deferred (creators submit a new version if needed)
- Scheduled publishes — deferred
- Creator analytics dashboards (how often a published joke was viewed, saved, reacted to) — deferred but tracked as Tier 1 follow-up

---

## 4. Information Architecture & Navigation

### 4.1 Route map

New routes to add to the React Router 7 tree. All require authentication (existing protected-route HOC pattern).

| Route | Component | Purpose |
|---|---|---|
| `/create` | `CreatorHubPage` | Drafts list + status tabs + "New Joke" CTA. Lands here when user clicks "Submit a joke" from anywhere. |
| `/create/new` | `FormatPickerPage` | The 6-format picker. Selecting a format navigates to `/create/new/:formatSlug`. |
| `/create/new/:formatSlug` | `EditorPage` | Editor for a brand-new draft of the chosen format. POST creates draft on first meaningful change. |
| `/create/:draftId` | `EditorPage` | Editor for an existing draft. Pre-populates form with draft data. |
| `/create/:draftId/view` | `SubmissionDetailPage` | Read-only view for `pending` / `published` / `rejected` submissions. From here, `rejected` can "Edit and resubmit" which navigates back to `/create/:draftId`. |

**Note:** `EditorPage` is the same component for both `/create/new/:formatSlug` and `/create/:draftId`; it branches its initial fetch and POST/PATCH behavior based on whether `draftId` is in the URL.

### 4.2 Navigation entry points

Where the creator hub is reachable from:

1. **Global header.** Add a `+` icon (lucide `Plus`) to the right side of the header (between the user avatar and the menu). Tooltip: "Submit a joke". Click → `/create`.
2. **Profile menu.** Add a "My submissions" link → `/create`.
3. **Home page (post-onboarding).** Optional: a small footer CTA "Got a joke? Share it." → `/create`. (Optional because it competes with the discovery loop; product can A/B this.)
4. **Empty state of search results.** "Don't see one? Write your own." → `/create/new`.
5. **Daily joke page footer.** "Think you can do better? Submit a joke." → `/create/new`.

### 4.3 Guarding entry points

Unauthenticated users clicking any of these CTAs should:
- Show the existing login modal with `returnTo='/create/new'` (or whatever path they intended)
- After login, redirect to the intended path

This pattern already exists for "Save to collection" (gated for guests); reuse it.

### 4.4 Header indicator for status changes

When a submission's status changes (pending → published or pending → rejected) and the user hasn't seen it yet, the `+` icon in the header should show a small dot indicator. Clear the dot when the user visits `/create`.

Implementation hint: poll `/api/v1/jokes/my-drafts/` on app load and any time the user becomes active, compare server statuses to a Zustand-stored `lastSeenAt`, set indicator if any change is newer.

(Deferable to v1.1 if push tech isn't wired — see §17.)

---

## 5. User Journeys

### 5.1 Happy path — first-time creator

```
[Header] User clicks `+` icon
     │
     ▼
[/create] Creator Hub
   - Empty state: "Got jokes? Share them with the world. Pick a format to begin."
   - Big "New Joke" CTA
     │ user clicks "New Joke"
     ▼
[/create/new] Format Picker
   - 6 format tiles with name, brief description, one example
   - User clicks "Knock-knock"
     │
     ▼
[/create/new/knock] Editor (knock format)
   - Format header: "Knock-knock"
   - Dialogue builder: 4 empty lines pre-populated with placeholders ("Knock, knock.", "Who's there?", etc.)
   - User types each line
   - On second meaningful keystroke: POST creates draft, URL silently rewrites to /create/:draftId
   - Autosave indicator: "Saving..." → "Saved 2s ago"
   - Live preview pane on the right renders the dialogue bubble layout
   - User picks themes ["family"], categories ["wholesome"], age "kid-safe"
   - User clicks "Submit for review"
   - Confirmation: "Send to moderators?" (so they don't accidentally publish a half-baked one)
     │ confirms
     ▼
   - POST /api/v1/jokes/my-drafts/{id}/submit/
   - Toast: "Sent for review. We'll email you when a moderator acts."
   - Navigate to /create
   - The submission now appears in the "Pending" tab
```

### 5.2 Edge case — user closes the tab mid-edit

```
[/create/new/knock] Editor (knock format)
   - User has typed two lines.
   - Autosave has already created the draft and persisted those two lines.
   - User closes the tab.
   ...
   - Later, user opens the app, navigates to /create
   - "Drafts" tab shows the partial draft with format = "Knock-knock", 2/4 lines.
   - User clicks it → /create/:draftId
   - Editor opens with the two lines populated. User continues.
```

### 5.3 Edge case — rejection workflow

```
- User submitted a joke. Moderator rejected with reason: "Punchline doesn't land — try again with a clearer twist."
     │
     ▼
[Header indicator dot appears]
   - User clicks `+` → /create → "Rejected" tab badge with count "1"
     │
     ▼
[/create] Creator Hub — Rejected tab
   - Submission card shows status badge "Rejected" and an excerpt of the reason
     │ user clicks card → /create/:draftId/view
     ▼
[/create/:draftId/view] Detail page
   - Full original content rendered
   - Rejection reason panel in red/amber
   - CTA: "Edit and resubmit"
     │ click
     ▼
[/create/:draftId] Editor (re-opens with all fields prepopulated)
   - User edits the punchline
   - Autosave indicator: "Saved"
   - User clicks "Submit for review" — status flips draft→pending
   - Toast: "Resubmitted. Thanks for revising."
```

### 5.4 Edge case — format switching mid-edit

```
User is in /create/:draftId on a knock format, has typed 3 lines.
User clicks "Change format" → picks "Setup-punchline"
     │
     ▼
Confirmation modal: "Changing to Setup-punchline will clear your knock-knock lines. Continue?"
     │ confirms
     ▼
- Frontend wipes lines from local state
- PATCH with { format: 'setup', lines: null, text: '', setup: '', punchline: '' }
- Editor re-renders as setup-punchline layout (two textareas, no dialogue builder)
- Autosave indicator: "Saved"
```

### 5.5 Edge case — validation fails on submit

```
User on /create/:draftId for a knock draft has filled 3 lines (min is 4).
Save Draft button is enabled (drafts can be partial).
Submit for Review button is disabled with a tooltip: "Add at least one more line."

User adds a 4th line.
Submit button enables.
User clicks Submit. Server-side validation succeeds. Toast appears.
```

### 5.6 State diagram for a single submission

```
       (user starts in editor)
                │
       autosave creates row
                │
                ▼
            [draft] ◄────────────────┐
                │ user clicks Submit │
                ▼                    │
            [pending]                │
                │                    │ user clicks "Edit and resubmit"
       moderator decides             │
                │                    │
       ┌────────┴────────┐           │
       ▼                 ▼           │
   [published]      [rejected] ──────┘
       │                 │
       │                 ▼
       │           (editable again, see top)
       │
       (terminal — read-only)
```

Key invariants:
- A draft (`draft` or `rejected`) is editable via PATCH and submittable via the submit endpoint.
- A `pending` submission is **read-only**. The user cannot edit it; they must wait for moderation. If they truly need to fix it, they delete and start over.
- A `published` submission is permanent; no edits allowed. (Future: maybe creator can request take-down.)
- Deleting any submission is allowed (DELETE on the draft endpoint), but the spec doesn't specify what happens if a published submission's underlying Joke remains — probably the joke stays public and only the submission record is removed. Backend behavior to verify (see §21).

---

## 6. Screen-by-Screen Specifications

This section walks through every screen the user can land on, with ASCII wireframes, behavior notes, and state coverage.

### 6.1 Creator Hub (`/create`)

**Purpose:** Single-pane view of everything the user has authored. Status-tabbed.

**Layout (desktop, ≥768px):**

```
┌──────────────────────────────────────────────────────────────────┐
│  [Site Header — global, includes + icon and avatar]              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Your jokes                                              [+ New] │
│                                                                  │
│  ┌─ All (12) ─ Drafts (3) ─ Pending (2) ─ Published (6) ─ Rej (1)│
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ [knock-knock icon]                              [Draft]    │ │
│  │  "Knock, knock. Who's there? Boo..."                       │ │
│  │  Edited 2 hours ago · themes: family · categories: dad     │ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ [one-liner icon]                              [Pending]    │ │
│  │  "Why don't scientists trust atoms? They make..."          │ │
│  │  Submitted 1 day ago · with reviewers                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ [story icon]                                  [Published]  │ │
│  │  "A man walks into a library and asks for a book..."       │ │
│  │  Published 3 weeks ago · 142 saves · 8 reactions           │ │
│  │                                              [View public →]│ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Layout (mobile, <768px):**

Tab strip horizontal-scrollable. Each card stacks. Same content, narrower padding.

**States:**

- **Loading:** Skeleton 3 card placeholders.
- **Empty (no submissions ever):** Friendly empty state with a single big "Submit your first joke" CTA. Bonus: small illustrative SVG of a microphone or a thought bubble.
- **Empty filtered tab** (e.g., "No published yet"): "Once a moderator approves your jokes, they'll show up here."
- **Loaded:** Cards in reverse chronological order by `last_edited_at`.
- **Error:** "Couldn't load your submissions." with retry button.

**Card click behavior:**
- `draft` / `rejected` → navigate to `/create/:id` (editor)
- `pending` / `published` → navigate to `/create/:id/view` (detail/read-only)

**The `+ New` button:** navigates to `/create/new`. On mobile this can also be a FAB (floating action button) bottom-right.

**Data fetching:**
- Single `useDrafts(status?)` hook backed by `useQuery(['drafts', status])`
- Hits `GET /api/v1/jokes/my-drafts/` (no status filter param yet on backend; filter client-side from full list — fine at MVP scale, revisit if a user has >100 submissions)

### 6.2 Format Picker (`/create/new`)

**Purpose:** Single decision: which format. Surfaces enough example to be inspiring without being prescriptive.

**Layout:**

```
┌──────────────────────────────────────────────────────────────────┐
│  ← Back                                                          │
│                                                                  │
│  Pick a format                                                   │
│  Each format renders differently to readers. Pick one to start.  │
│                                                                  │
│  ┌────────────────────────┐  ┌────────────────────────┐         │
│  │  📜  One-liner          │  │  ❓  Setup-punchline   │         │
│  │  A single line.         │  │  A setup, a payoff.    │         │
│  │  "I'm reading a book    │  │  "Why did the          │         │
│  │  on anti-gravity. It's  │  │  scarecrow get a       │         │
│  │  impossible to put       │  │  promotion? He was     │         │
│  │  down."                  │  │  outstanding in his    │         │
│  │                          │  │  field."               │         │
│  └────────────────────────┘  └────────────────────────┘         │
│                                                                  │
│  ┌────────────────────────┐  ┌────────────────────────┐         │
│  │  🚪  Knock-knock        │  │  📖  Story             │         │
│  │  Multi-line dialogue.   │  │  Long-form, 30+ words. │         │
│  │  "Knock, knock."        │  │  "A man walks into a   │         │
│  │  "Who's there?"         │  │  library and..."       │         │
│  │  "Olive."                │  │                        │         │
│  │  "Olive who?"            │  │                        │         │
│  └────────────────────────┘  └────────────────────────┘         │
│                                                                  │
│  ┌────────────────────────┐  ┌────────────────────────┐         │
│  │  🎭  Anti-joke          │  │  🧐  Observational     │         │
│  │  Subverts expectation.  │  │  Italic-quote style.   │         │
│  │  "Why did the chicken   │  │  "Have you ever        │         │
│  │  cross the road? To     │  │  noticed how..."        │         │
│  │  get to the other       │  │                        │         │
│  │  side."                 │  │                        │         │
│  └────────────────────────┘  └────────────────────────┘         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Tile click → `/create/new/:formatSlug`
- Tiles use the same lucide icons mapped per format (see §14 for icon mapping)
- The example text is hardcoded in the frontend (not fetched) — it's an editorial choice, not data
- Each tile shows a tiny "How it renders" subtitle and a 2-3 line example

**States:**
- Loading the format catalog (from `GET /api/v1/formats/`): show skeleton tiles. Catalog is needed to validate the slug exists and to show `name`/`description` rather than hardcoding.
- Network error: fall back to hardcoded list of the 6 known slugs. The catalog enriches with `name`, `description`, `required_fields`, etc. — but for picker display, the hardcoded examples are enough.

### 6.3 Editor (`/create/new/:formatSlug` and `/create/:draftId`)

**Purpose:** The main work. Format-specific input on the left, live preview on the right (desktop) or toggleable on mobile.

**Layout (desktop):**

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ← Back                                                                    │
│                                                                            │
│  Knock-knock                                       [Change format] ⓘ      │
│                                                                            │
│  ┌──────────────────────────────────────┬───────────────────────────────┐ │
│  │ EDITOR                               │ PREVIEW                       │ │
│  │                                      │ How readers will see it       │ │
│  │ Dialogue                             │                               │ │
│  │ ┌──────────────────────────────────┐ │  ╭─────╮                      │ │
│  │ │ A: Knock, knock.              ✕  │ │  │ A   │  Knock, knock.       │ │
│  │ └──────────────────────────────────┘ │  ╰─────╯                      │ │
│  │ ┌──────────────────────────────────┐ │              ╭─────╮          │ │
│  │ │ B: Who's there?               ✕  │ │   Who's      │ B   │          │ │
│  │ └──────────────────────────────────┘ │  there?      ╰─────╯          │ │
│  │ ┌──────────────────────────────────┐ │  ╭─────╮                      │ │
│  │ │ A: Olive.                     ✕  │ │  │ A   │  Olive.              │ │
│  │ └──────────────────────────────────┘ │  ╰─────╯                      │ │
│  │ ┌──────────────────────────────────┐ │              ╭─────╮          │ │
│  │ │ B: Olive who?                 ✕  │ │   Olive      │ B   │          │ │
│  │ └──────────────────────────────────┘ │   who?       ╰─────╯          │ │
│  │                                      │                               │ │
│  │  [+ Add line]    4 of 4-8 lines      │                               │ │
│  │                                      │                               │ │
│  │ Tags (optional but recommended)      │                               │ │
│  │  Themes:    [+ family] [+ animals]   │                               │ │
│  │  Categories: [+ wholesome] [+ dad]   │                               │ │
│  │  Age:       (•) Kid-safe  ( ) Teen…  │                               │ │
│  │  Language:  English ▾                │                               │ │
│  │                                      │                               │ │
│  │ ─────────────────────────────────────┴───────────────────────────────┤ │
│  │  Saved 3s ago         [Delete draft]      [Submit for review]        │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

**Layout (mobile):**

A toggle at the top: `[Edit | Preview]`. Stacking the editor and preview vertically would make both useless on small screens. The toggle hides one or the other.

**Region inventory:**

| Region | Contents | Behavior |
|---|---|---|
| Header | Format name, "Change format" button, info tooltip | Change format = confirm modal then PATCH |
| Editor pane | Format-specific input area + tag pickers | Inputs autosave on debounced change |
| Preview pane | Live `<JokeRenderer>` mount | Updates on every keystroke (no debounce) |
| Footer | Save status, Delete, Submit for review | Submit only enables when all required fields satisfy rules |

**Format-specific input areas:** see §7 for each of the 6 layouts.

**Tag pickers** (universal across all formats):

- **Themes** — chip multi-select, fetched from `GET /api/v1/context-tags/` (returns `[{id, slug, name, description}]`). Typeahead search ("type to filter"). Selecting adds a chip; click chip × to remove.
- **Categories** — same component, fetched from `GET /api/v1/tones/`. (Reminder: API name is `categories`, DB name is `tones`; the JSON key in the submission payload should be `categories` or `tones` — both accepted, prefer `categories`.)
- **Age rating** — radio group, fetched from `GET /api/v1/age-ratings/`. Required.
- **Culture tags** — chip multi-select, fetched from `GET /api/v1/culture-tags/`. Optional, default empty.
- **Language** — dropdown, fetched from `GET /api/v1/languages/`. Defaults to `en`. Optional.
- **Source** — text input, default `original`. Optional. Used for attribution if the creator is referencing a known source.

**Footer:**
- **Save status indicator:** "Saving…" (debouncing) → "Saved" (success) → "Couldn't save · retry" (error)
- **Delete draft:** trash icon, confirm modal, DELETE `/api/v1/jokes/my-drafts/:id/`, navigate back to `/create`
- **Submit for review:** primary button. Disabled unless format-validation passes (see §11 for the rules). Click → confirm modal → POST `/api/v1/jokes/my-drafts/:id/submit/` → toast → navigate to `/create`

### 6.4 Submission Detail (`/create/:draftId/view`)

Read-only view used for `pending` and `published` (and accessible for `rejected` though the user is encouraged to go straight to the editor).

**Layout (pending):**

```
┌──────────────────────────────────────────────────────────────────┐
│  ← Back to your jokes                                            │
│                                                                  │
│  [status banner — amber]                                         │
│  With our reviewers since Apr 12 · We'll let you know.           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ [Knock-knock]                                                ││
│  │                                                              ││
│  │ Rendered preview of the joke (using JokeRenderer)            ││
│  │                                                              ││
│  │                                                              ││
│  │ Tags: family · wholesome · kid-safe                          ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Submitted 3 days ago. Average review time: 1-2 days.            │
└──────────────────────────────────────────────────────────────────┘
```

**Layout (published):**

```
┌──────────────────────────────────────────────────────────────────┐
│  ← Back                                                          │
│                                                                  │
│  [status banner — green]                                         │
│  Published 3 weeks ago                          [View public →]  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Rendered preview (JokeRenderer)                              ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Lifetime stats                                                  │
│  · 142 readers saved this                                        │
│  · 8 reactions (😂 6 · 🤣 2)                                     │
│  · 0 reports                                                     │
│                                                                  │
│  Want to submit another? [+ New joke]                            │
└──────────────────────────────────────────────────────────────────┘
```

**Layout (rejected):**

```
┌──────────────────────────────────────────────────────────────────┐
│  ← Back                                                          │
│                                                                  │
│  [status banner — amber/red]                                     │
│  Rejected 2 days ago                                             │
│                                                                  │
│  Reason from our reviewers                                       │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ "Punchline doesn't quite land — could you make the twist     ││
│  │ clearer? We think there's a great joke here with a tweak."   ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Your submission (read-only)                                     │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Rendered preview                                             ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  [Edit and resubmit]                                             │
└──────────────────────────────────────────────────────────────────┘
```

**Note on the published view's stats:** "142 readers saved this", "8 reactions", "0 reports" — these are **not yet exposed by the current API** for an individual `JokeSubmission`. To support this UI v1, the backend needs to either:
- Add a `stats` object to the `JokeSubmissionListSerializer` for published rows (joining through to `published_joke`)
- Or expose a separate `GET /api/v1/jokes/my-drafts/:id/stats/` endpoint

This is a Tier 1 backend enhancement (see §19). For v1.0 frontend launch, **hide the stats section** if the data isn't available. Don't block on it.

---

## 7. Per-Format Authoring Deep Dive

Six formats, six distinctive layouts. The shared chrome (header, tag pickers, preview, footer) is the same across all six; only the input area differs.

For each format below: layout, behavior, validation rules (mirrored client-side from `GET /api/v1/formats/` `constraints`), placeholder text, and the preview rendering.

### 7.1 One-liner

**Layout:**
```
Your one-liner
┌──────────────────────────────────────────────────────────────────┐
│ I told my wife she was drawing her eyebrows too high.            │
│ She looked surprised.                                            │
└──────────────────────────────────────────────────────────────────┘
0 / 280 characters (soft hint, no enforced cap)
```

**Field type:** Single multi-line textarea. Auto-resize as content grows. Min height ~3 lines.

**Placeholder:** "Write a punchy one-liner. Land it in one breath."

**Validation:**
- Required: `text` non-empty
- Constraints: none

**Forbidden fields:** `setup`, `punchline`, `lines` (frontend should not show these inputs at all for one-liner)

**Preview rendering:** Plain text, large serif or sans (matching the daily-joke render for one-liners).

### 7.2 Setup-punchline

**Layout:**
```
Setup
┌──────────────────────────────────────────────────────────────────┐
│ Why did the scarecrow get a promotion?                           │
└──────────────────────────────────────────────────────────────────┘

Punchline                                          (tap-to-reveal)
┌──────────────────────────────────────────────────────────────────┐
│ He was outstanding in his field.                                 │
└──────────────────────────────────────────────────────────────────┘
```

**Field types:** Two separate single-line textareas (auto-resize). Visual flow: setup on top, downward chevron or "↓" character, punchline below.

**Placeholders:**
- Setup: "The question, the setup, the lead-in…"
- Punchline: "…and the payoff."

**Validation:**
- Required: `setup` non-empty, `punchline` non-empty
- Constraints: none

**Hint text below the setup:** "Readers tap to reveal the punchline."

**Preview rendering:** Setup shown immediately; punchline shown as a "Tap to reveal" affordance, revealing on click. Use the same `<JokeRenderer>` the daily-joke page uses.

### 7.3 Knock-knock — the dialogue builder

This is the most distinctive editor and the most worth engineering well.

**Layout:**
```
Dialogue          4 of 4-8 lines · alternating A / B speakers

┌──────────────────────────────────────────────────────────────────┐
│ ⋮⋮ │ Speaker A │ Knock, knock.                            │ ✕   │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ ⋮⋮ │ Speaker B │ Who's there?                             │ ✕   │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ ⋮⋮ │ Speaker A │ Olive.                                   │ ✕   │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ ⋮⋮ │ Speaker B │ Olive who?                               │ ✕   │
└──────────────────────────────────────────────────────────────────┘

[+ Add line]
```

**Behavior:**

- **Speaker labels alternate automatically** by index: even indices → A, odd → B. This matches the backend rule (`Joke.lines` even/odd → A/B) and the renderer's behavior. The label is **non-editable** (it's derived); users can't override.
- **Drag handle (⋮⋮)** reorders lines. Use `dnd-kit` or similar. On mobile, long-press to start drag.
- **Add line button** appears below the last line. Adds a new empty line at the end. Disabled when count = max (8).
- **Delete (✕)** on each line removes that line. Disabled when count = min (4).
- **Visual constraint indicator:** "4 of 4-8 lines" updates live. Turns amber if below 4, normal otherwise.
- **Each line:** auto-growing textarea, max ~200 chars (soft hint, with character counter that warns approaching limit).

**Placeholders (for the four initial lines):**
- Line 1: "Knock, knock."
- Line 2: "Who's there?"
- Line 3: "Your setup word."
- Line 4: "Your setup word who?"
- Line 5+ (added): "And the payoff…"

(These are placeholders, not pre-filled values. The user has to type them.)

**Validation:**
- Required: `lines` array, length 4-8, each entry non-empty string ≤200 chars
- Constraints from backend: `min_lines: 4, max_lines: 8, max_line_chars: 200`

**Forbidden fields:** `text`, `setup`, `punchline`

**Preview rendering:** Bubble-style dialogue alternating sides, like an iMessage thread. Speaker A on the left, Speaker B on the right (or styled-distinct).

### 7.4 Story

**Layout:**
```
Your story                                    73 / 30 words minimum
┌──────────────────────────────────────────────────────────────────┐
│ A man walks into a library and asks for a book on paranoia.      │
│ The librarian whispers, "Have you checked behind you?"           │
│                                                                  │
│ He turned around and screamed. The librarian had vanished.       │
│ The book was already in his hand.                                │
└──────────────────────────────────────────────────────────────────┘
```

**Field type:** Multi-line textarea, much taller than the one-liner. Word count visible.

**Placeholder:** "Set the scene. Build the moment. Land the joke. 30 words or more."

**Behavior:**
- Word counter live-updates as user types. Below 30 → amber/red. 30+ → green.
- Submit button stays disabled until ≥30 words.

**Validation:**
- Required: `text` non-empty
- Constraints: `min_text_words: 30`

**Forbidden fields:** `setup`, `punchline`, `lines`

**Preview rendering:** Reading-time estimate shown at top (computed client-side: words ÷ 200 wpm, rounded). Body text rendered with paragraph breaks. The daily-joke renderer shows stories with a "X min read" label.

### 7.5 Anti-joke

**Layout:** Identical to setup-punchline, with one tweak:

```
Setup
┌──────────────────────────────────────────────────────────────────┐
│ Why did the chicken cross the road?                              │
└──────────────────────────────────────────────────────────────────┘

Punchline
┌──────────────────────────────────────────────────────────────────┐
│ To get to the other side.                                        │
└──────────────────────────────────────────────────────────────────┘

ⓘ Anti-jokes render with a "* That's it. That's the joke." footer
   automatically. You don't need to add that.
```

**Field types:** Same two textareas as setup-punchline.

**Placeholders:** Same.

**Validation:** Same as setup-punchline (`required: setup, punchline`).

**Forbidden fields:** `text`, `lines`

**Preview rendering:** Setup + Punchline, plus an italic muted footer below: `*That's it. That's the joke.`

### 7.6 Observational

**Layout:**
```
Your observation
┌──────────────────────────────────────────────────────────────────┐
│ Have you ever noticed how everyone driving slower than you       │
│ is an idiot, and everyone driving faster than you is a maniac?   │
└──────────────────────────────────────────────────────────────────┘
```

**Field type:** Multi-line textarea (slightly taller than one-liner — observational jokes tend to be 2-3 sentences).

**Placeholder:** "Have you ever noticed how… / Why is it that… / Don't you hate when…"

**Validation:**
- Required: `text` non-empty
- Constraints: none

**Forbidden fields:** `setup`, `punchline`, `lines`

**Preview rendering:** Italic, serif typography, large quotation marks framing the text. This is the design's "italic-quote with serif" treatment.

### 7.7 Common element — Format header with "Change format"

Above every editor:

```
[ICON] One-liner                                  [Change format]
```

Clicking "Change format" opens a modal:

```
┌──────────────────────────────────────────────┐
│ Change format?                                │
│                                              │
│ Your current content may be cleared if it    │
│ doesn't fit the new format. We'll keep what  │
│ we can.                                      │
│                                              │
│ Pick a new format:                           │
│  ◯ One-liner                                 │
│  ◯ Setup-punchline                           │
│  ◯ Knock-knock                               │
│  ● Story  (current)                          │
│  ◯ Anti-joke                                 │
│  ◯ Observational                             │
│                                              │
│           [Cancel]    [Change format]         │
└──────────────────────────────────────────────┘
```

**Behavior:**
- On confirm: PATCH with `{ format: newSlug }` plus null/empty for any field forbidden by the new format.
- The "what we can keep" logic:
  - One-liner ↔ Observational ↔ Story: `text` carries across (all three use `text`)
  - Setup-punchline ↔ Anti-joke: `setup` and `punchline` carry across
  - All others: clear non-compatible fields, set the new required fields to empty

---

## 8. API Contract — Exact Endpoints

This is the complete API surface the creator features touch. Most endpoints already exist; one new one is needed (see §19).

### 8.1 GET /api/v1/formats/ — format catalog with schema

**Purpose:** Provide the editor with the list of available formats and the per-format validation rules so the frontend can mirror them.

**Auth:** Public (no token required).

**Response 200:**
```json
{
  "results": [
    {
      "id": 1,
      "slug": "oneliner",
      "name": "One-liner",
      "description": "A single line, one-breath joke.",
      "required_fields": ["text"],
      "forbidden_fields": ["setup", "punchline", "lines"],
      "constraints": {}
    },
    {
      "id": 2,
      "slug": "setup",
      "name": "Setup & Punchline",
      "description": "Question, setup, payoff.",
      "required_fields": ["setup", "punchline"],
      "forbidden_fields": ["text", "lines"],
      "constraints": {}
    },
    {
      "id": 3,
      "slug": "knock",
      "name": "Knock-knock",
      "description": "Multi-line call-and-response.",
      "required_fields": ["lines"],
      "forbidden_fields": ["text", "setup", "punchline"],
      "constraints": {
        "min_lines": 4,
        "max_lines": 8,
        "max_line_chars": 200
      }
    },
    {
      "id": 4,
      "slug": "story",
      "name": "Story",
      "description": "Long-form joke, 30+ words.",
      "required_fields": ["text"],
      "forbidden_fields": ["setup", "punchline", "lines"],
      "constraints": {
        "min_text_words": 30
      }
    },
    {
      "id": 5,
      "slug": "anti",
      "name": "Anti-joke",
      "description": "Subverts expectations of a setup-punchline.",
      "required_fields": ["setup", "punchline"],
      "forbidden_fields": ["text", "lines"],
      "constraints": {}
    },
    {
      "id": 6,
      "slug": "observ",
      "name": "Observational",
      "description": "An italic-quote observation about life.",
      "required_fields": ["text"],
      "forbidden_fields": ["setup", "punchline", "lines"],
      "constraints": {}
    }
  ]
}
```

**Fetch pattern:** Once at app load. Cache in TanStack Query with stale time = 1 hour (these change very rarely). Use `useFormats()` hook.

### 8.2 Taxonomy lookups

All public, all small (<50 rows each), all cacheable with long stale time.

| Endpoint | Returns |
|---|---|
| `GET /api/v1/age-ratings/` | `[{id, slug, name, description, min_age}]` |
| `GET /api/v1/tones/` | `[{id, slug, name, description}]` (UI label: "Categories") |
| `GET /api/v1/context-tags/` | `[{id, slug, name, description}]` (UI label: "Themes") |
| `GET /api/v1/culture-tags/` | `[{id, slug, name, description}]` |
| `GET /api/v1/languages/` | `[{id, code, name}]` |

**Fetch pattern:** All five loaded at app load (parallel `useQueries`), cached with stale time = 1 hour.

### 8.3 GET /api/v1/jokes/my-drafts/ — list drafts

**Auth:** Required.

**Response 200:**
```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 47,
      "text": "Knock, knock. Who's there? Olive. Olive who? Olive you and I miss you!",
      "setup": "",
      "punchline": "",
      "lines": ["Knock, knock.", "Who's there?", "Olive.", "Olive who?", "Olive you and I miss you!"],
      "format": "knock",
      "status": "draft",
      "tones": ["Wholesome"],
      "age_rating": "kid-safe",
      "context_tags": ["family"],
      "culture_tags": ["universal"],
      "categories": ["Wholesome"],
      "themes": ["family"],
      "last_edited_at": "2026-05-18T14:23:11Z",
      "created_at": "2026-05-18T14:18:00Z",
      "likes": null,
      "rejection_reason": ""
    }
    /* … */
  ]
}
```

**Notes:**
- `categories` and `themes` are aliases of `tones` and `context_tags` respectively. Use the new names in new frontend code.
- `lines` is `null` for non-knock submissions, an array of strings for knock.
- `likes` is `null` for non-published submissions. For published, it's the count of `+1` ratings on the published Joke.
- `rejection_reason` is empty unless `status='rejected'`.

**Pagination:** Default 20 per page. The Creator Hub may want to load all in one request for simplicity at MVP scale (typical user has <50 drafts). Use `?page_size=100` if needed.

### 8.4 GET /api/v1/jokes/my-drafts/:id/ — single draft detail

**Auth:** Required, must be the owner.

**Response 200:** Same shape as a single result above.

**Response 404:** If the id doesn't belong to this user or doesn't exist.

### 8.5 POST /api/v1/jokes/my-drafts/ — create a draft (NEW ENDPOINT NEEDED)

**🟠 This endpoint does NOT exist on the backend yet.** See §19 for the gap and the proposed implementation.

**Proposed shape:**

**Auth:** Required.

**Request body:**
```json
{
  "format": "knock"
}
```

Just `format` is required; everything else is set later via PATCH. The backend should create a row with the given format, `status='draft'`, all content fields empty/null, and return the new row.

**Response 201:**
```json
{
  "id": 84,
  "text": "",
  "setup": "",
  "punchline": "",
  "lines": null,
  "format": "knock",
  "status": "draft",
  "tones": [],
  "age_rating": null,
  "context_tags": [],
  "culture_tags": [],
  "categories": [],
  "themes": [],
  "last_edited_at": "2026-05-19T10:00:00Z",
  "created_at": "2026-05-19T10:00:00Z",
  "likes": null,
  "rejection_reason": ""
}
```

**Why this needs to exist (full rationale in §19):** Without it, the frontend has no way to create a draft row to PATCH against. The autosave pattern depends on this.

### 8.6 PATCH /api/v1/jokes/my-drafts/:id/ — update a draft

**Auth:** Required, must be the owner, must be `status in ('draft', 'rejected')`.

**Request body:** Any subset of the editable fields:
```json
{
  "format": "knock",
  "text": "",
  "setup": "",
  "punchline": "",
  "lines": ["Knock, knock.", "Who's there?", "Boo.", "Boo who?", "Don't cry — it's just a joke!"],
  "tones": ["wholesome"],
  "context_tags": ["family"],
  "culture_tags": ["universal"],
  "age_rating": "kid-safe",
  "language": "en",
  "source": "original"
}
```

**Note on PATCH semantics:**
- Fields **not** in the payload preserve their existing value.
- Fields with explicit empty string `""` or `null` (for `lines`) are treated as "cleared".
- The serializer runs format-aware validation on every PATCH. If you PATCH `{format: 'knock'}` without `lines`, you'll get a 400 because the rule says knock requires lines. Fix: send both in the same PATCH.

**Response 200:** Full updated row (same shape as GET detail).

**Response 400:** Field-level errors. Examples:
```json
{ "lines": ["This field is required for knock format."] }
{ "text": ["Story must be at least 30 words."] }
{ "punchline": ["This field is required for anti format."] }
```

**Response 403:** Attempting PATCH on `status='pending'` or `status='published'`. Body:
```json
{ "detail": "Can only edit drafts or rejected submissions." }
```

### 8.7 POST /api/v1/jokes/my-drafts/:id/submit/ — submit draft for review

**Auth:** Required, must be the owner, must be `status in ('draft', 'rejected')`.

**Request body:** Empty.

**Response 200:**
```json
{ "id": 47, "status": "pending" }
```

**Response 400:** If status is not `draft` or `rejected`:
```json
{ "detail": "Can only submit drafts or rejected submissions for review." }
```

**Important:** This endpoint **does not** re-run format validation server-side. (Backend gap noted in the spec — left intentionally because the PATCH endpoint runs validation, so by the time the submission reaches `submit/`, it's validated.) **But:** edge case — if a row was created pre-migration (when `lines` didn't exist as a constraint), it could pass `submit/` despite being structurally invalid. For MVP this is acceptable; the moderator catches it.

### 8.8 DELETE /api/v1/jokes/my-drafts/:id/ — delete a draft

**Auth:** Required, must be the owner.

**Response 204:** No content.

**Allowed on any status?** Currently yes — `JokeDraftDetailView` extends `RetrieveUpdateDestroyAPIView` which allows DELETE unconditionally. The frontend should still warn before deleting `published` (the public Joke remains, but the submission audit trail is gone).

### 8.9 GET /api/v1/jokes/:publishedJokeId/ — view the published joke (for stats and public link)

Used on the published submission detail page to fetch reaction counts, save count, etc.

**Response 200:** Standard Joke shape (see Frontend Handout).

(Currently the submission list doesn't include published_joke_id in a usable form — verify the backend exposes this. If not, link via slug or fall back to no "View public" link in v1.)

### 8.10 Authentication headers

All endpoints under `/api/v1/jokes/my-drafts/`, `/api/v1/jokes/submit/`, and `/api/v1/jokes/my-drafts/:id/submit/` require the JWT access token in the `Authorization: Bearer <token>` header. The existing axios interceptor handles this.

The 401 → refresh → retry flow already exists; this feature inherits it.

---

## 9. Component Inventory

New components introduced by this feature. Reuse existing shadcn/ui primitives wherever possible.

### 9.1 New components

| Component | Responsibility | File |
|---|---|---|
| `CreatorHubPage` | The `/create` route shell with tabs and drafts list | `src/pages/CreatorHubPage.tsx` |
| `DraftCard` | One card in the drafts list | `src/features/create/components/DraftCard.tsx` |
| `FormatPickerPage` | The `/create/new` route | `src/pages/FormatPickerPage.tsx` |
| `FormatTile` | One format tile in the picker | `src/features/create/components/FormatTile.tsx` |
| `EditorPage` | The `/create/:draftId` route | `src/pages/EditorPage.tsx` |
| `EditorShell` | The shared chrome (header, footer, save indicator) | `src/features/create/components/EditorShell.tsx` |
| `OneLinerEditor` | Format-specific input for `oneliner` | `src/features/create/editors/OneLinerEditor.tsx` |
| `SetupPunchlineEditor` | Format-specific input for `setup` and `anti` (same component, anti shows the footer hint) | `src/features/create/editors/SetupPunchlineEditor.tsx` |
| `KnockEditor` | The dialogue builder for `knock` | `src/features/create/editors/KnockEditor.tsx` |
| `StoryEditor` | Format-specific input for `story` | `src/features/create/editors/StoryEditor.tsx` |
| `ObservationalEditor` | Format-specific input for `observ` | `src/features/create/editors/ObservationalEditor.tsx` |
| `DialogueLine` | Single editable line in the knock editor (with drag handle, speaker label, delete) | `src/features/create/components/DialogueLine.tsx` |
| `TagPicker` | Multi-select chip input for themes / categories / cultures | `src/features/create/components/TagPicker.tsx` |
| `AgeRatingRadio` | Radio group for age rating | `src/features/create/components/AgeRatingRadio.tsx` |
| `PreviewPane` | Renders `<JokeRenderer>` with the current draft state | `src/features/create/components/PreviewPane.tsx` |
| `SubmitConfirmModal` | "Send to moderators?" dialog | `src/features/create/components/SubmitConfirmModal.tsx` |
| `ChangeFormatModal` | "Change format?" dialog | `src/features/create/components/ChangeFormatModal.tsx` |
| `DeleteDraftModal` | "Delete this draft?" dialog | `src/features/create/components/DeleteDraftModal.tsx` |
| `SubmissionDetailPage` | The `/create/:draftId/view` route | `src/pages/SubmissionDetailPage.tsx` |
| `StatusBadge` | Color-coded pill for `draft / pending / published / rejected` | `src/features/create/components/StatusBadge.tsx` |
| `SaveIndicator` | "Saving…" / "Saved" / "Failed" | `src/features/create/components/SaveIndicator.tsx` |

### 9.2 Shared / extracted from existing code

| Component | Why |
|---|---|
| `<JokeRenderer payload={...} />` | **Extract from the daily-joke and search pages.** This must be a single component that takes the same payload shape both contexts use and renders the joke. Mount it in `PreviewPane`. |
| Existing `<Button>`, `<Input>`, `<Textarea>`, `<Dialog>`, `<RadioGroup>` from shadcn/ui | Used throughout |
| Existing `<Header>` adds the new `+` icon |
| Existing protected-route HOC | Wraps all `/create/*` routes |

### 9.3 The `JokeRenderer` extraction is the most important refactor

The whole "what readers see" claim of the preview pane depends on the editor and the daily-joke page rendering identically. If the renderer drifts from the daily joke's renderer, the editor lies to creators.

**Action:** Before building the editors, extract `<JokeRenderer>` from wherever the daily-joke page currently renders jokes. The component takes a single prop `payload: { format, text, setup, punchline, lines }` and dispatches to the correct sub-renderer (`OneLinerView`, `KnockView`, etc.).

If this hasn't been done yet — do it as the first task of the creator content milestone, before writing any editor code.

---

## 10. State Management & Data Flow

### 10.1 Query keys

Use TanStack Query with these keys:

```typescript
// src/features/create/queries.ts
const keys = {
  formats: ['formats'] as const,
  taxonomy: {
    ages: ['taxonomy', 'ages'] as const,
    tones: ['taxonomy', 'tones'] as const,
    themes: ['taxonomy', 'themes'] as const,
    cultures: ['taxonomy', 'cultures'] as const,
    languages: ['taxonomy', 'languages'] as const,
  },
  drafts: {
    list: ['drafts'] as const,
    detail: (id: number) => ['drafts', id] as const,
  },
};
```

Stale times:
- `formats` and `taxonomy.*` → 1 hour (rarely change)
- `drafts.list` → 30 seconds (so navigating back to the hub feels fresh)
- `drafts.detail` → no stale (use `refetchOnMount: 'always'` so editor opens with fresh state, useful if multi-tab editing)

### 10.2 Mutations

```typescript
// Create a new draft (when user picks a format from the picker)
useCreateDraft() →
  POST /api/v1/jokes/my-drafts/ with { format }
  On success: invalidate drafts.list, push to drafts.detail cache, navigate to /create/:id

// Patch an existing draft (autosave)
usePatchDraft(id) →
  PATCH /api/v1/jokes/my-drafts/:id/
  Optimistic update: write the partial body into drafts.detail(id) cache immediately
  On error: roll back, surface error

// Submit for review
useSubmitDraft(id) →
  POST /api/v1/jokes/my-drafts/:id/submit/
  On success: invalidate drafts.list and drafts.detail(id), navigate to /create

// Delete
useDeleteDraft(id) →
  DELETE /api/v1/jokes/my-drafts/:id/
  On success: remove from drafts.list cache, navigate to /create
```

### 10.3 Local-only editor state vs. server state

A subtle but important distinction:

**Server state** (TanStack Query): the truth as of the last successful sync. Owns: `status`, `last_edited_at`, the canonical values of every field.

**Local editor state** (`useState` / `useReducer` in the editor): the user's in-flight edits before they're persisted. Owns: what's currently in the textareas, the unsaved knock-knock line array, etc.

The PATCH mutation reconciles them — it sends the local diff and updates the server cache from the response.

Pattern:
```typescript
// EditorPage.tsx
const { data: draft } = useQuery(keys.drafts.detail(id), fetchDraft);
const patchDraft = usePatchDraft(id);

// Local state, initialized from server, updated on every keystroke
const [editor, setEditor] = useReducer(editorReducer, draft, fromServer);

// Debounced autosave
useEffect(() => {
  const t = setTimeout(() => {
    if (hasUnsavedChanges(editor, draft)) {
      patchDraft.mutate(diff(editor, draft));
    }
  }, 800);
  return () => clearTimeout(t);
}, [editor]);
```

### 10.4 Zustand: do we need a new store?

**No.** The existing `useUiStore` (mobile menu, etc.) and `useAuthStore` are sufficient. Editor state is per-component; query cache holds the server state; nothing crosses-cuts enough to justify a store.

Exception: if you implement the "header status indicator dot" mentioned in §4.4, you'll want a small `useCreatorStore` with `{ lastSeenAt: number; markSeen: () => void }`. Optional for v1.0.

### 10.5 The shape passed to `<JokeRenderer>`

```typescript
type JokePayload = {
  format: 'oneliner' | 'setup' | 'knock' | 'story' | 'anti' | 'observ';
  text: string;
  setup: string;
  punchline: string;
  lines: string[] | null;
};
```

The editor's `<PreviewPane>` builds this payload from `editor` local state and passes it to `<JokeRenderer>`. The daily-joke page builds the same shape from the API response.

---

## 11. Validation Patterns

### 11.1 Client-side mirror of FORMAT_RULES

The frontend mirrors the backend's `FORMAT_RULES` table by reading `GET /api/v1/formats/` once at app load and caching it. The client-side validation never needs to be in sync with the backend by hand — it's data-driven.

Helper:

```typescript
// src/features/create/validation.ts
import { useFormats } from './queries';

export function useFormatRule(slug: string) {
  const { data } = useFormats();
  return data?.results.find(f => f.slug === slug);
}

export function validate(payload: JokePayload, rule: FormatRule): Record<string, string> {
  const errors: Record<string, string> = {};

  for (const field of rule.required_fields) {
    if (isBlank(payload[field])) {
      errors[field] = `This field is required for ${rule.name}.`;
    }
  }

  for (const field of rule.forbidden_fields) {
    if (!isBlank(payload[field])) {
      errors[field] = `Not allowed for ${rule.name}.`;
    }
  }

  // Apply constraints (mirrored from backend logic)
  if (rule.constraints.min_lines && payload.lines?.length < rule.constraints.min_lines) {
    errors.lines = `Needs at least ${rule.constraints.min_lines} lines.`;
  }
  // ... etc

  return errors;
}
```

The Submit-for-review button enables iff `Object.keys(validate(payload, rule)).length === 0`.

### 11.2 Two validation moments

1. **Live, client-side, while editing:** Drives the Submit button enabled state and inline field error rendering. Cheap, instant.
2. **On PATCH / submit, server-side:** The source of truth. If the server returns 400 with field errors, render them in the same field-error slots as the client-side errors. Trust the server over the client.

The pattern: prefer the server's error message if one is present; otherwise show the client-side message; otherwise no error.

### 11.3 Where errors are rendered

- Field-level errors: directly under the field, in red text with a `lucide:AlertCircle` icon.
- Form-level errors (network failure, server 500): toast at the top of the screen.
- Status-related errors (e.g. trying to edit a `pending` submission): toast + navigate to the appropriate view.

### 11.4 Don't block typing on validation

Validation runs on every keystroke for live feedback, **but never blocks input**. The user types whatever they want; we just disable the Submit button and show inline hints. This is critical because validation that prevents typing is hostile.

---

## 12. Draft Lifecycle & Autosave

### 12.1 The autosave contract

The user should never lose work. Autosave operates on these rules:

1. **First meaningful change creates the draft.** When the editor opens for a new format (`/create/new/:formatSlug`), no row exists yet. As soon as the user types one character that produces non-empty content, the frontend POSTs `/api/v1/jokes/my-drafts/` with `{ format: :formatSlug }`. The response gives an `id`; the URL is rewritten to `/create/:id` via `navigate(..., { replace: true })`.

   - **"Meaningful change"** = the first character typed in any required field. Don't create a draft just because the user navigated to the page.

2. **Subsequent changes PATCH the existing draft.** Debounced 800ms after the last keystroke.

3. **Save indicator states:**
   - Idle (no recent change): "Saved [time ago]"
   - During debounce: "…"
   - During PATCH in flight: "Saving…"
   - PATCH succeeded: "Saved"
   - PATCH failed: "Save failed · retry" (clickable; runs the PATCH again)

4. **Navigation-away guard:** If a PATCH is in flight or there are local changes not yet sent, intercept the navigation attempt with a confirm dialog ("You have unsaved changes. Leave?").

5. **Background save on tab close.** Use `navigator.sendBeacon()` to fire-and-forget a final PATCH on `beforeunload` if there's unsaved state. This isn't 100% reliable but catches the common case.

### 12.2 Race conditions to handle

| Scenario | Handling |
|---|---|
| User types fast, debounce fires, PATCH in flight, user types more | Cancel/ignore the in-flight PATCH? No — let it complete, then schedule another PATCH with the newer state. Use a serialized queue. |
| User types in field A, debounce fires, PATCH(A) in flight, user types in field B | Same: serialize. The second PATCH sends the diff of B. |
| Two tabs open, both editing the same draft | Last write wins. Acceptable for MVP; later, consider a "this draft is being edited elsewhere" warning via `last_edited_at` checks. |
| Server returns 403 (draft was somehow submitted in another session) | Stop autosave, navigate to detail view |

### 12.3 First-time creation race

If two creates fire for the same format (e.g., double-click on a tile), guard with:
- Disable the format tile on click
- Track a `creatingDraft: boolean` flag in component state
- The second click is a no-op

### 12.4 Why we don't use a "Save Draft" button

Modern editors (Notion, Google Docs, Linear) have trained users to expect autosave. Explicit Save buttons feel old-fashioned and create anxiety ("did I save?"). The save indicator is the modern equivalent.

That said, a "Save and exit" button in the editor footer is reasonable as a power-user shortcut. It forces a flush of the debounce and navigates back to `/create`. Optional for v1.0.

### 12.5 Draft autosave UX summary

```
                      ┌─────────────┐
                      │ Editor open │
                      └──────┬──────┘
                             │
                       (user types)
                             │
                             ▼
                   ┌──────────────────┐
                   │ Local state diff │
                   │   != server      │
                   └────────┬─────────┘
                            │
                       800ms debounce
                            │
                            ▼
                   ┌─────────────────────┐
                   │ "Saving…" indicator │
                   │   PATCH in flight   │
                   └────────┬────────────┘
                            │
                ┌───────────┴────────────┐
              success                 failure
                │                        │
                ▼                        ▼
       ┌─────────────────┐   ┌──────────────────────┐
       │ "Saved" indicator│   │ "Save failed · retry" │
       │ Update cache    │   │ Local state preserved│
       └─────────────────┘   └──────────────────────┘
```

---

## 13. Error Handling Matrix

Every state worth handling, in one table:

| HTTP | Cause | UI response |
|---|---|---|
| 200 / 201 / 204 | Success | Update local state. Possibly toast. |
| 400 (field errors) | Validation failed | Render field-level errors inline; toast generic only if no field-mapped errors. |
| 400 (`detail` only) | Workflow violation (e.g. submit on already-published) | Toast with the `detail` message. Refetch state. |
| 401 | Token expired | Existing axios interceptor refreshes. If refresh also fails, redirect to login with `returnTo`. |
| 403 | Forbidden (e.g. PATCH on `pending`) | Toast "This submission can't be edited right now." Navigate to detail view. |
| 404 | Draft doesn't exist or was deleted | Toast "We couldn't find that draft." Navigate to `/create`. |
| 429 | Rate limited | Toast "Slow down — try again in a minute." Disable Submit briefly. |
| 5xx | Server error | Toast "Something went wrong. We've been notified. Try again." Retry button on PATCH; for create/submit, no auto-retry. |
| Network error (no response) | Offline / DNS / etc. | Indicator: "Offline — changes saved locally." Queue the PATCH; retry on reconnect. |

### 13.1 Per-error UX details

**400 field-error rendering:**
```jsx
{errors.lines && (
  <div className="text-destructive text-sm flex items-center gap-1 mt-1">
    <AlertCircle className="h-4 w-4" />
    <span>{errors.lines}</span>
  </div>
)}
```

**Offline detection:**
- Use `navigator.onLine` and `online`/`offline` events
- When offline, surface a persistent banner: "You're offline. Drafts will save when you reconnect."
- Queue PATCH operations in a local FIFO; drain on reconnect

(Offline queuing is a fast-follow improvement; for v1.0, just disable autosave when offline and warn the user.)

---

## 14. Visual Design Notes

### 14.1 Format icons (lucide)

| Format | Icon |
|---|---|
| `oneliner` | `Quote` or `Type` |
| `setup` | `MessageCircleQuestion` or `HelpCircle` |
| `knock` | `DoorOpen` or `MessagesSquare` |
| `story` | `BookOpen` or `ScrollText` |
| `anti` | `RefreshCw` or `Asterisk` |
| `observ` | `Eye` or `Glasses` |

Final mapping is a design choice; the above are starting suggestions matching the metaphorical fit.

### 14.2 Status badge colors

Use the existing oklch palette. Suggested mapping:

| Status | Background | Text | Border |
|---|---|---|---|
| `draft` | `oklch(95% 0.02 270)` (neutral light purple) | `oklch(40% 0.05 270)` | `oklch(85% 0.05 270)` |
| `pending` | `oklch(95% 0.08 75)` (amber-50) | `oklch(45% 0.15 75)` | `oklch(85% 0.10 75)` |
| `published` | `oklch(95% 0.08 140)` (green-50) | `oklch(40% 0.15 140)` | `oklch(85% 0.10 140)` |
| `rejected` | `oklch(95% 0.05 25)` (red-50) | `oklch(45% 0.15 25)` | `oklch(85% 0.10 25)` |

### 14.3 Typography per format in the preview

The whole point of distinct format renderers is type contrast. Suggested mappings:

| Format | Preview font |
|---|---|
| `oneliner` | Default sans (clean, punchy) |
| `setup` / `anti` | Default sans, with the punchline in a slightly different weight or with the "tap to reveal" affordance |
| `knock` | Default sans inside chat bubbles |
| `story` | Serif (literary, long-form feel) |
| `observ` | Italic serif (quote-like) |

(If the design system doesn't have a serif loaded yet, fall back to system-ui italic for `observ` and a fallback chain for `story`; coordinate with whoever's done the rest of the design.)

### 14.4 Editor pane chrome

- White background (or theme background)
- Generous padding (24-32px)
- Inputs use the existing shadcn `Input` and `Textarea` styles
- Subtle dividers between regions (format header / input area / tags / footer)

### 14.5 Preview pane chrome

- Slightly tinted background (oklch(98% 0.005 270) — barely-purple-tinted off-white) to visually distinguish from the editor
- Same rendering as the daily-joke page (literally a `<JokeRenderer>` mount)
- Mobile: full screen when toggled, no chrome distinction needed

### 14.6 Empty states

Friendly, never blank. Use lucide icons sparingly + 1-2 sentences of copy.

```
[lucide:Sparkles, 48px, muted]

Got jokes? Share them with the world.
Pick a format to begin.

[ + New Joke ]
```

---

## 15. Accessibility Requirements

Target: **WCAG 2.1 AA** at minimum.

### 15.1 Keyboard navigation

- Every interactive element reachable by Tab in logical order
- Format picker tiles selectable with Enter / Space
- Dialogue lines in knock editor: drag handles operable via keyboard (arrow keys to reorder, Delete to remove)
- Submit button activated with Enter when focused
- Escape closes any open modal

### 15.2 Screen reader support

- All form fields have `<label>` (or `aria-label`) tied to them
- Status badges use `aria-label` with the status spelled out
- Save indicator uses `aria-live="polite"` so screen readers announce "Saved" without interrupting
- Validation errors use `aria-describedby` linking the field to its error message
- Loading states use `aria-busy="true"`

### 15.3 Focus management

- After navigating from format picker to editor, focus the first input field
- After submitting, focus the toast / next-action area in the Creator Hub
- Modals trap focus while open; restore focus to the triggering element on close

### 15.4 Color contrast

- All text ≥ 4.5:1 against background (WCAG AA normal text)
- Status badge text against badge background ≥ 4.5:1
- Form inputs in error state must not rely on color alone — use the icon + text

### 15.5 Motion

- Respect `prefers-reduced-motion` media query
- Autosave indicator transitions: skip animations for users with reduced motion preference
- No essential information conveyed via motion alone

### 15.6 Touch targets

- All buttons ≥ 44×44px on mobile (per WCAG 2.5.5)
- Knock-knock drag handles need extra padding on touch (visible affordance is the ⋮⋮ icon but the actual hit zone is larger)

---

## 16. Performance & Loading States

### 16.1 Initial route load

- `/create` cold load target: < 1s LCP on a 4G connection
- All taxonomy lookups (formats, ages, tones, themes, cultures, languages) fetch in parallel on app load and cache 1hr — no waterfall when the user navigates to `/create`
- The drafts list fetches on Creator Hub mount; show skeleton during fetch

### 16.2 Editor open

- For a new format: instant (no fetch needed beyond what's already cached)
- For an existing draft: skeleton form during the draft fetch (typically < 200ms)
- The format catalog and taxonomy lookups should already be cached from app load

### 16.3 Bundle size

- The dialogue-builder drag library (`dnd-kit`) is ~30KB gzipped. Acceptable.
- Format-specific editor components: code-split per format with `React.lazy` so only the picked format's editor is loaded. Saves ~30-50KB.

### 16.4 Live preview performance

- Re-render on every keystroke is fine for the small JSON payload
- Don't re-fetch anything during typing; preview reads from local state only

### 16.5 Skeleton patterns

Use shadcn's `Skeleton` component (probably already in use):

```jsx
{isLoading ? (
  <div className="space-y-4">
    <Skeleton className="h-24 rounded-xl" />
    <Skeleton className="h-24 rounded-xl" />
    <Skeleton className="h-24 rounded-xl" />
  </div>
) : (
  drafts.map(d => <DraftCard key={d.id} draft={d} />)
)}
```

---

## 17. Analytics Events

Tracked via whichever analytics SDK the app has (PostHog suggested in §17 of the launch-readiness assessment).

| Event | When | Properties |
|---|---|---|
| `creator_hub_viewed` | `/create` mount | `{ tab: 'all' \| 'draft' \| 'pending' \| 'published' \| 'rejected' }` |
| `format_picker_viewed` | `/create/new` mount | none |
| `format_selected` | User clicks a format tile | `{ format: slug }` |
| `editor_opened` | Editor mounts | `{ format: slug, mode: 'new' \| 'edit' \| 'resubmit' }` |
| `draft_created` | First successful POST to my-drafts/ | `{ format }` |
| `draft_autosaved` | Successful PATCH | `{ draftId, format }` (throttled — don't fire on every keystroke; once per 30s max) |
| `submit_clicked` | Submit button pressed | `{ draftId, format }` |
| `submit_confirmed` | After confirm modal | `{ draftId, format, fields: ['lines', 'tones', ...] }` |
| `submit_succeeded` | POST submit/ 200 | `{ draftId, format }` |
| `submit_failed` | POST submit/ error | `{ draftId, format, error }` |
| `validation_error_shown` | Inline validation surfaces | `{ field, message }` (throttle) |
| `format_changed` | User changes format mid-edit | `{ from, to }` |
| `draft_deleted` | DELETE confirmed | `{ draftId, format, status_at_delete }` |
| `submission_detail_viewed` | `/create/:id/view` mount | `{ status }` |
| `published_public_link_clicked` | "View public →" clicked | `{ publishedJokeId }` |

### 17.1 Why this set

These events let product answer:
- **Funnel:** signup → viewed creator hub → opened editor → submitted → published
- **Quality:** which formats have the highest approval rate? Which have the highest abandonment rate (started editor, didn't submit)?
- **Friction:** which validation errors trigger most? Are users abandoning at a specific step?
- **Behavior:** how often do creators come back to edit a rejected submission?

---

## 18. Acceptance Criteria

Feature is "done" when **all** of the following are true:

### 18.1 Functional

- [ ] An authenticated user can navigate to `/create` from the global header
- [ ] User can see their drafts grouped by status (All / Draft / Pending / Published / Rejected)
- [ ] User can click "New Joke" and pick from 6 formats
- [ ] Each of the 6 formats has its own editor layout with correct fields
- [ ] Knock-knock editor supports add/remove/reorder of dialogue lines, enforced 4-8 lines
- [ ] Live preview pane renders the current draft as the daily-joke page would
- [ ] Autosave persists changes within 1 second of stopping typing
- [ ] Save indicator shows current state (Saved / Saving… / Failed)
- [ ] User can change format mid-edit with a confirm dialog
- [ ] User can submit a valid draft for review
- [ ] Submit button disabled when client-side validation fails, enabled when it passes
- [ ] Server-side validation errors render inline next to the relevant field
- [ ] User can delete any draft with a confirm dialog
- [ ] User can view pending / published / rejected submissions in read-only mode
- [ ] User can "Edit and resubmit" a rejected submission
- [ ] Published submissions show a "View public" link (or hide it if backend can't yet provide the public URL)

### 18.2 Quality

- [ ] All routes are protected (redirect to login if unauthenticated)
- [ ] All forms keyboard-navigable per §15.1
- [ ] No accessibility violations at WCAG AA level (verified with axe-core)
- [ ] Mobile layout works on viewports down to 360px wide
- [ ] No N+1 in initial Creator Hub load (parallel fetches, cached taxonomy)
- [ ] Loading states render correctly (no layout shift, skeletons present)
- [ ] All 11 error paths in §13 handled correctly
- [ ] Analytics events from §17 fire in the right places

### 18.3 Cross-feature integration

- [ ] `<JokeRenderer>` is extracted and used by both the daily-joke page and the creator preview pane
- [ ] The `+` icon in the global header shows the unseen-status-change dot (or — deferred to v1.1 — at least doesn't error)
- [ ] Existing pages (daily-joke, search, etc.) continue to work without regression

### 18.4 Non-regressions

- [ ] All existing routes still work
- [ ] Token refresh flow still works
- [ ] No console errors / warnings in dev mode

---

## 19. Required Backend Enhancements

Two small enhancements are required for the frontend autosave + UX patterns described above. Both are low-risk additions, ~1-3 hours each.

### 19.1 🟠 BLOCKER: POST /api/v1/jokes/my-drafts/ — create draft endpoint

**Why needed:** The frontend autosave pattern requires that drafts can be created at the start of editing, before any content is filled in. Without this endpoint, the only way to create a `JokeSubmission` row is via `POST /api/v1/jokes/submit/`, which immediately sets `status='pending'` and runs full format validation. That's incompatible with "create as the user starts typing".

**Proposed implementation:**

Add a new view:

```python
# jokes/views.py
class JokeDraftCreateView(generics.CreateAPIView):
    """POST /jokes/my-drafts/ — Create a new draft row."""

    permission_classes = [IsAuthenticated]
    serializer_class = JokeSubmissionDraftCreateSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, status='draft')
```

With a minimal serializer:

```python
# jokes/serializers.py
class JokeSubmissionDraftCreateSerializer(serializers.ModelSerializer):
    """Lightweight serializer for creating an empty draft row.
    Only `format` is required; other fields are filled in via PATCH later."""

    format = serializers.SlugRelatedField(
        slug_field='slug', queryset=Format.objects.all(),
    )

    class Meta:
        model = JokeSubmission
        fields = ['format']
```

Route it in `jokes/urls.py`:

```python
path('jokes/my-drafts/', views.JokeDraftCreateView.as_view(), name='joke-draft-create'),
```

(Note: the existing `JokeDraftListView` is on `jokes/my-drafts/` for GET. Combine them by inheriting from `ListCreateAPIView` and switching serializer classes by method, or use two views and let DRF route by HTTP method — both work.)

**Key design choices to flag:**
- The draft is created with all content fields empty/null. This is intentional — autosave PATCHes will fill them in.
- The draft's `age_rating` and `language` are nullable on create. Either: (a) make them nullable on the model with safe defaults applied on submit, or (b) require them in the POST body (simpler, since the frontend already knows defaults). **Recommendation: option (b)** — POST body accepts `{ format, age_rating, language }` and defaults `language='en'` if missing.

**Validation on this POST:**
- Format slug must exist
- That's it. No format-rule validation runs (the draft is empty, of course it won't pass rules yet).

### 19.2 🟢 NICE-TO-HAVE: Published submission stats

For the "Published" detail view to show 142 saves / 8 reactions / 0 reports (per §6.4), the backend needs to expose these counts on the submission detail.

**Option A — Embed in submission detail:**
Add to `JokeSubmissionListSerializer` for `status='published'`:
```python
saves_count = serializers.SerializerMethodField()
reactions_count = serializers.SerializerMethodField()
reports_count = serializers.SerializerMethodField()

def get_saves_count(self, obj):
    if obj.published_joke:
        return obj.published_joke.saved_by.count()
    return None
# ... etc
```

**Option B — Separate endpoint:**
`GET /api/v1/jokes/my-drafts/:id/stats/` that joins through to the published joke.

**Recommendation:** Option A. Single round-trip from frontend. Minor cost increase on the detail endpoint, acceptable.

**Status:** NOT a blocker for v1.0 frontend. Hide the stats section if not present. Can ship as a follow-up.

### 19.3 🟢 NICE-TO-HAVE: Submission status filter on the list endpoint

Currently `GET /api/v1/jokes/my-drafts/` returns all statuses. The Creator Hub tabs filter client-side, which is fine at MVP scale. If creator counts grow:

`GET /api/v1/jokes/my-drafts/?status=draft` should server-filter.

**Status:** NOT a blocker. Client-side filter is fine until a creator has >100 submissions.

### 19.4 🟢 NICE-TO-HAVE: Re-validate on submit

`POST /api/v1/jokes/my-drafts/:id/submit/` currently does not re-run format validation — it trusts that the row was validated when last PATCHed. This is mostly fine but creates an edge case: if a row was created pre-migration with invalid structure, `submit/` would let it through.

**Fix:** Add a call to `validate_per_format` inside the view's `post()` handler before flipping status to `pending`. ~5 lines of code.

**Status:** NOT a blocker for v1.0. Moderators are the second line of defense.

### 19.5 Summary of backend work needed BEFORE frontend starts

- **§19.1 only.** Estimated 30-45 minutes.

Everything else in §19 can ship parallel-or-later.

---

## 20. Out of Scope / Future

Tracked for product follow-up but not part of v1.0:

- **Creator byline on the public joke page.** "By @creatorhandle" with link to their public profile. Requires public profiles to be defined first.
- **Joke editing after publication.** Currently published is terminal; future: creators can submit a v2 of their joke.
- **Co-authored jokes.** Two users credited.
- **AI-assisted writing.** "Help me workshop this" — Claude API integration in the editor.
- **Scheduled publishes.** Submit now, publish on a date.
- **Creator analytics dashboards.** Per-joke views, save rate, share rate over time.
- **Joke templates.** "Start from a Mom joke template" — pre-fill scaffolds.
- **Bulk submission.** Paste 10 jokes, split into 10 drafts.
- **Markdown / formatting in story format.** Bold, italic, paragraph breaks rendered.
- **Rich media in any format.** Image, audio, GIF — separate compliance lift per the Compliance Addendum.
- **Per-joke presentation overrides.** Custom background color, font, sound — separate feature.
- **Drag-to-reorder drafts in Creator Hub.** Currently sorted by `last_edited_at`.

---

## 21. Open Product Questions

These are decisions someone (product, design, or you) should make before or during implementation. Each has a recommended default the frontend can ship with absent guidance.

| # | Question | Recommended default | Owner |
|---|---|---|---|
| 1 | Should published submissions be deletable by the creator? | **No** — once published, the public Joke is permanent. Creators can request take-down via support. | Product |
| 2 | Should the moderator queue notify the creator via email when a submission is published or rejected? | **Yes** — but this depends on production email being wired (Tier 0 item from §2 of the launch-readiness doc). For v1.0 frontend, no in-app notification needed; the header dot is sufficient. | Product + Backend |
| 3 | When a creator changes format mid-edit, should setup/punchline carry from `setup` to `anti` (they're compatible)? | **Yes**, see §7.7 cross-format rules. | Frontend |
| 4 | Should there be a creator achievement for "First joke published"? | **Yes** — the `Achievement` model exists; just add a row. Frontend doesn't need to change. | Backend |
| 5 | What's the moderator SLA shown in the UI? | **"1-2 days"** — shown on the pending status banner. Can be updated based on actual moderator throughput. | Product |
| 6 | What rejection-reason templates does the moderator have? | Free-text. Moderator writes whatever. UI just renders it. (Future: canned reasons.) | Backend / Moderation |
| 7 | Can a creator have unlimited drafts, or is there a cap? | **Yes, capped at 50 drafts per user** to prevent abuse. Rejected/published don't count. Backend enforcement TODO. | Product + Backend |
| 8 | Should knock-knock support more than 2 speakers (A, B, C, …)? | **No** — 2 speakers only. The renderer alternates by index parity. If a future format needs >2, add a new "Sketch" format. | Design |
| 9 | What's the public URL slug for a published joke? Numeric ID? Auto-generated slug? | **Numeric ID** for v1.0. Slugs as a follow-up (SEO concern). | Backend |
| 10 | Should creators see how many people viewed their pending submission while it's in the queue? | **No** — that data isn't tracked for unpublished jokes. | Product |

---

## 22. Appendix — Quick Reference Card

For a frontend engineer who's read this once and wants a printout to keep next to the keyboard.

### Routes
- `/create` — Hub
- `/create/new` — Format picker
- `/create/new/:formatSlug` — Editor (new)
- `/create/:draftId` — Editor (existing)
- `/create/:draftId/view` — Detail (read-only)

### Endpoints
- `GET /api/v1/formats/` — schema for each format
- `GET /api/v1/{age-ratings, tones, context-tags, culture-tags, languages}/` — taxonomy
- `POST /api/v1/jokes/my-drafts/` — **new endpoint, see §19** — create draft
- `GET /api/v1/jokes/my-drafts/` — list drafts
- `GET /api/v1/jokes/my-drafts/:id/` — detail
- `PATCH /api/v1/jokes/my-drafts/:id/` — autosave
- `POST /api/v1/jokes/my-drafts/:id/submit/` — submit for review
- `DELETE /api/v1/jokes/my-drafts/:id/` — delete

### Format slugs
`oneliner` · `setup` · `knock` · `story` · `anti` · `observ`

### Validation rules per format
- `oneliner`: needs `text`
- `setup`: needs `setup` + `punchline`
- `knock`: needs `lines` (array, 4-8 entries, ≤200 chars each)
- `story`: needs `text` (≥30 words)
- `anti`: needs `setup` + `punchline`
- `observ`: needs `text`

### Statuses
- `draft` → user can edit, can submit
- `pending` → read-only, awaiting moderator
- `published` → read-only, joke is public
- `rejected` → user can edit, can resubmit

### Common errors
- 400 → field-level inline error
- 401 → axios interceptor handles refresh
- 403 → "this submission can't be edited" toast + nav to detail
- 404 → "not found" toast + nav to hub
- 429 → "slow down" toast, disable submit briefly
- 5xx → generic error toast, retry on PATCH

---

*End of document. ~3000 lines of markdown. Author: brainstormed via session 2026-05-19. Companion to `Docs/API/Frontend_Integration_Handout.md` (general API surface) and `docs/superpowers/specs/2026-05-19-creator-content-system-design.md` (backend design).*
