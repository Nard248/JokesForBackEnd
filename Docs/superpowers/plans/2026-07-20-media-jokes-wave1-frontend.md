# Media Jokes Wave 1 — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Image jokes render, upload, and paywall correctly across the JokesFor React app — renderer + carousel, ImageEditor with upload, bespoke-surface consolidation, the anonymous sign-up wall, and the ToS amendment — per spec `Docs/superpowers/specs/2026-07-20-media-jokes-design.md` (backend contract pinned by the wave-1 backend plan).

**Architecture:** Extend the closed `FlowJokeFormat` union with `'image'` so TypeScript forces every keyed map; add an unknown-format skip-render guard (deploy-order safety); media rides `JokePayload` so ONE renderer branch serves cards, detail, previews, and daily heroes; upload is a dedicated FormData mutation whose returned asset ids ride the existing 800ms JSON autosave.

**Tech Stack:** React 19 + TS + Vite, react-router 7, @tanstack/react-query 5, axios, zustand, vitest + @testing-library/react. Inline styles + `useBreakpoint` per `Docs/RESPONSIVE.md`.

## Global Constraints

- Repo: `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend`. Tests: `npm test -- --run` (vitest); type-check/build: `npm run build`. 633 pre-existing tests must stay green.
- Commit messages: plain, descriptive. NO Co-Authored-By, NO "Generated with", no emoji footers.
- Backend contract (already implemented, wave-1 backend plan): `Joke.media?: [{kind,url?,poster_url?,width,height,duration_ms?,is_gif?}]` — locked jokes get `{kind,width,height}` ONLY (no `url` key); `POST /api/v1/media/uploads/` (multipart `file`,`kind`) → 201 MediaAsset DTO; draft PATCH accepts `media_asset_ids: string[]`; draft DTO carries `media: MediaAssetDTO[]`; `POST /api/v1/jokes/{id}/reveal/` (anon consumption) → `{limit,used,remaining,over,reset_at}`; `GET /jokes/daily-reads/` now returns numeric limits for anon.
- Renderer rules (spec §10.1): media sits in an `aspect-ratio`-reserved box (dims from backend — no masonry CLS); blur = existing `.punch-blur` mechanic; reveal fires `onReveal` exactly once; locked media = dimensioned placeholder + CTA, NEVER an `<img>` with a real URL.
- Anon CTA: "Sign up free" → `/register`. Authenticated free CTA stays "Unlock with Supporter" → `/settings/billing`.
- Image formats join the reveal-gated set (they consume a daily read on reveal).
- Mock seams must keep working: create is mocked locally (`VITE_USE_REAL_CREATE` unset) — upload gets a mock branch returning object-URL DTOs.
- Responsive: mobile <640 via `useBreakpoint`; tap targets ≥44px; test at 375/768/1280; `prefers-reduced-motion` respected.
- Wave 1 = `'image'` only. Do NOT add `'video'`/`'audio'` union members yet (wave 2).

---

### Task 1: Joke media types, `'image'` union member, unknown-format guard, adapter threading

**Files:**
- Modify: `src/lib/api.ts` (Joke type, ~L166-200)
- Modify: `src/components/JokeRenderer.tsx` (union L4, SKIN L17, FORMAT_LABEL L26, FLOW_FORMAT_TO_BACKEND_SLUG L38, formatSlugToFlow L54, tagToneFor L86)
- Modify: `src/components/FlowJokeCard.tsx` (FlowJokeData L35, jokeToFlowData L369)
- Modify: `src/pages/LibraryPage.tsx` (savedJokeToFlowData ~L413), `src/pages/CollectionDetailPage.tsx` (~L131), `src/pages/TrendingPage.tsx` (~L100)
- Modify: null-filter call sites: `src/pages/ExplorePage.tsx`, `src/pages/SearchPage.tsx`, `src/pages/LibraryPage.tsx`, `src/pages/FavoritesPage.tsx`, `src/pages/CollectionDetailPage.tsx`, `src/pages/TrendingPage.tsx`, `src/pages/HomePage.tsx`, `src/pages/FlowCanvasPage.tsx`, `src/pages/JokeDetailPage.tsx` (related-jokes grid)
- Test: `src/components/JokeRenderer.format.test.tsx` (create), extend existing adapter tests if present

**Interfaces:**
- Consumes: backend `media` array shape (Global Constraints).
- Produces: `export interface JokeMediaItem { kind: 'image'|'video'|'audio'; url?: string|null; poster_url?: string|null; width?: number|null; height?: number|null; duration_ms?: number|null; is_gif?: boolean }` on `src/lib/api.ts`; `Joke.media?: JokeMediaItem[]`; `FlowJokeFormat` includes `'image'`; `formatSlugToFlow(slug): FlowJokeFormat | null` (null = unknown → skip render); `jokeToFlowData(joke): FlowJokeData | null`; `FlowJokeData.media?: JokeMediaItem[]`.

- [ ] **Step 1: Write the failing tests**

Create `src/components/JokeRenderer.format.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { formatSlugToFlow, SKIN, FORMAT_LABEL, FLOW_FORMAT_TO_BACKEND_SLUG } from './JokeRenderer'
import { jokeToFlowData } from './FlowJokeCard'
import type { Joke } from '@/lib/api'

function makeJoke(overrides: Partial<Joke> = {}): Joke {
  return {
    id: 1, text: 'caption', setup: 'caption', punchline: null,
    format: { id: 9, name: 'Image', slug: 'image' },
    age_rating: { id: 1, name: 'All Ages', slug: 'all-ages', min_age: 0 },
    tones: [], context_tags: [], culture_tags: [],
    language: { id: 1, name: 'English', code: 'en' },
    source: 'original', share_image_url: null, created_at: '2026-07-20T00:00:00Z',
    ...overrides,
  } as Joke
}

describe('image format registration', () => {
  it('maps the image slug and has card chrome entries', () => {
    expect(formatSlugToFlow('image')).toBe('image')
    expect(SKIN.image).toBeDefined()
    expect(FORMAT_LABEL.image).toBe('Image')
    expect(FLOW_FORMAT_TO_BACKEND_SLUG.image).toBe('image')
  })

  it('threads media through jokeToFlowData', () => {
    const joke = makeJoke({
      media: [{ kind: 'image', url: 'http://x/img.webp', width: 800, height: 600 }],
    })
    const flow = jokeToFlowData(joke)
    expect(flow).not.toBeNull()
    expect(flow!.fmt).toBe('image')
    expect(flow!.media?.[0].url).toBe('http://x/img.webp')
  })
})

describe('unknown-format guard', () => {
  it('formatSlugToFlow returns null for unknown slugs', () => {
    expect(formatSlugToFlow('hologram')).toBeNull()
  })

  it('jokeToFlowData returns null for unknown slugs instead of a garbled card', () => {
    const joke = makeJoke({ format: { id: 99, name: 'Hologram', slug: 'hologram' } })
    expect(jokeToFlowData(joke)).toBeNull()
  })

  it('legacy long-form slugs still resolve (regression)', () => {
    expect(formatSlugToFlow('setup_punchline')).toBe('setup')
    expect(formatSlugToFlow('one-liner')).toBe('oneliner')
  })

  it('slugless jokes still fall back by shape (regression)', () => {
    const joke = makeJoke({
      format: { id: 0, name: '', slug: '' }, setup: 's', punchline: 'p',
    })
    expect(jokeToFlowData(joke)?.fmt).toBe('setup')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/components/JokeRenderer.format.test.tsx`
Expected: FAIL — TS error `'image'` not assignable / `SKIN.image` undefined / `toBeNull` mismatch (unknown slugs return `'oneliner'` today).

- [ ] **Step 3: Extend the union + maps + guard in `JokeRenderer.tsx`**

```ts
export type FlowJokeFormat = 'setup' | 'oneliner' | 'observ' | 'anti' | 'knock' | 'story' | 'image'
```

Add to `SKIN` (image jokes sit on the warm off-white ground so the photo carries the color):

```ts
  image:    { bg: '#FFFFFF',  fg: '#1A1A1A', border: '1px solid #E9E8E7', divider: '#F1EFEC' },
```

Add to `FORMAT_LABEL`: `image: 'Image',` — and to `FLOW_FORMAT_TO_BACKEND_SLUG`: `image: 'image',`

`formatSlugToFlow` — new return type + image case + null default (KEEP every existing legacy-alias case exactly as-is):

```ts
export function formatSlugToFlow(rawSlug: string | null | undefined): FlowJokeFormat | null {
  switch ((rawSlug ?? '').toLowerCase()) {
    // ... existing cases unchanged ...
    case 'image':
      return 'image'
    case '':
      return null   // slugless: caller falls back by shape
    default:
      return null   // unknown format (future wave) → skip render, don't garble
  }
}
```

`tagToneFor`: add `case 'image':` to the `'amber'` group.

- [ ] **Step 4: Thread media + guard through the adapters**

`src/lib/api.ts` — after the `JokeTaxon` interface:

```ts
export interface JokeMediaItem {
  kind: 'image' | 'video' | 'audio'
  /** Absent/undefined when the joke is LOCKED — the backend withholds URLs server-side. */
  url?: string | null
  poster_url?: string | null
  width?: number | null
  height?: number | null
  duration_ms?: number | null
  is_gif?: boolean
}
```

and on `Joke`: `media?: JokeMediaItem[]` (next to `share_image_url`).

`FlowJokeCard.tsx` — `FlowJokeData` gains `media?: JokeMediaItem[]` (import the type). Rewrite `jokeToFlowData`'s format cascade to use the guard (keep the taxonomy/label logic untouched):

```ts
export function jokeToFlowData(joke: Joke): FlowJokeData | null {
  const slug = taxonSlug(joke.format).toLowerCase()
  let fmt = formatSlugToFlow(slug)
  if (fmt === null) {
    if (slug === '' || slug === 'short-story' || slug === 'short_story') {
      // slugless/legacy: fall back by shape as before
      fmt = joke.setup && joke.punchline ? 'setup' : joke.text ? 'oneliner' : null
      if (slug.startsWith('short')) fmt = 'story'
    }
    if (fmt === null) return null   // unknown format → hide, don't garble
  }
  // ... themeLabel/catLabel lines unchanged ...
  return {
    id: joke.id, fmt,
    setup: joke.setup ?? undefined,
    punch: joke.punchline ?? undefined,
    text: joke.text ?? undefined,
    lines: joke.lines ?? undefined,
    media: joke.media ?? undefined,
    themeLabel, catLabel,
    isLocked: joke.is_locked === true,
  }
}
```

(NOTE: `formatSlugToFlow` already resolves `short-story`/`short_story` to `'story'` via its existing case — check before duplicating; if so drop that special-case here and only keep the slugless shape fallback.)

Apply the same two changes (media passthrough + null return on unknown) to `savedJokeToFlowData` (`LibraryPage.tsx` AND its duplicate in `CollectionDetailPage.tsx`) and `trendingToFlowData` (`TrendingPage.tsx`) — each currently builds `FlowJokeData` from a saved/trending row; route their slug through `formatSlugToFlow` identically.

Null-filter every render site that maps jokes through an adapter, e.g. in ExplorePage:

```tsx
{jokes.map((j) => { const flow = jokeToFlowData(j); return flow && (
  <Link key={j.id} ...><FlowJokeCard joke={flow} source="explore" /></Link>
)})}
```

Adapt the exact surrounding JSX per page (Explore, Search, Library, Favorites, CollectionDetail, Trending, Home, FlowCanvas For-You grid, JokeDetail related grid). TypeScript will surface every call site as an error once the return type is `| null` — fix each, don't cast.

- [ ] **Step 5: Run tests + full suite + typecheck**

Run: `npm test -- --run src/components/JokeRenderer.format.test.tsx` → PASS.
Run: `npm test -- --run` → all suites green (adapters' existing tests may need the null-tolerant call pattern — fix tests only where they assert the OLD garbling fallback, and say so in the report).
Run: `npm run build` → tsc clean.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "media: image format registration, media threading, unknown-format skip-render guard"
```

---

### Task 2: JokeRenderer image branch — blurred media punchline, carousel, locked variant

**Files:**
- Modify: `src/components/JokeRenderer.tsx`
- Test: `src/components/JokeRenderer.media.test.tsx` (create)

**Interfaces:**
- Consumes: Task 1 types (`JokeMediaItem`, union member).
- Produces: `JokePayload.media: JokeMediaItem[] | null`; the image branch (reveal → `onReveal` once); `LockedBody` media placeholder; `UnlockCta` gains optional `label?: string` (default `'Unlock with Supporter'`). FlowJokeCard/PreviewPane/detail all inherit via the shared renderer.

- [ ] **Step 1: Write the failing tests**

Create `src/components/JokeRenderer.media.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { JokeRenderer, type JokePayload } from './JokeRenderer'

function imagePayload(overrides: Partial<JokePayload> = {}): JokePayload {
  return {
    format: 'image', text: 'the caption', setup: 'the caption', punchline: '', lines: null,
    media: [{ kind: 'image', url: 'http://x/a.webp', width: 800, height: 600 }],
    ...overrides,
  }
}

describe('image joke rendering', () => {
  it('shows setup and a blurred media box; tap reveals and fires onReveal once', () => {
    const onReveal = vi.fn()
    render(<JokeRenderer payload={imagePayload()} onReveal={onReveal} />)
    expect(screen.getByText('the caption')).toBeInTheDocument()
    const box = screen.getByTestId('media-punchline')
    expect(box.className).toContain('punch-blur')
    expect(box.className).not.toContain('is-revealed')
    fireEvent.click(box)
    expect(screen.getByTestId('media-punchline').className).toContain('is-revealed')
    expect(onReveal).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByTestId('media-punchline'))
    expect(onReveal).toHaveBeenCalledTimes(1)
  })

  it('reserves aspect ratio from backend dimensions', () => {
    render(<JokeRenderer payload={imagePayload()} revealed />)
    const box = screen.getByTestId('media-punchline')
    expect(box.style.aspectRatio).toBe('800 / 600')
  })

  it('renders a scroll-snap carousel for multi-image jokes', () => {
    const payload = imagePayload({
      media: [
        { kind: 'image', url: 'http://x/a.webp', width: 800, height: 600 },
        { kind: 'image', url: 'http://x/b.webp', width: 800, height: 600 },
      ],
    })
    render(<JokeRenderer payload={payload} revealed />)
    expect(screen.getAllByRole('img')).toHaveLength(2)
    expect(screen.getByText('1/2')).toBeInTheDocument()
  })

  it('locked image joke renders NO img elements and shows the CTA', () => {
    const payload = imagePayload({ media: [{ kind: 'image', width: 800, height: 600 }] })
    render(<JokeRenderer payload={payload} locked />)
    expect(screen.queryAllByRole('img')).toHaveLength(0)
    expect(screen.getByTestId('unlock-supporter-cta')).toBeInTheDocument()
    expect(screen.getByText('the caption')).toBeInTheDocument()
  })

  it('locked CTA label is overridable (anon sign-up wall)', () => {
    render(<JokeRenderer payload={imagePayload()} locked ctaLabel="Sign up free" />)
    expect(screen.getByTestId('unlock-supporter-cta')).toHaveTextContent('Sign up free')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- --run src/components/JokeRenderer.media.test.tsx`
Expected: FAIL — `media` not on `JokePayload`; no `media-punchline` testid; no `ctaLabel` prop.

- [ ] **Step 3: Implement**

`JokePayload` gains `media: JokeMediaItem[] | null` (import the type from `@/lib/api`). `JokeRendererProps` gains `ctaLabel?: string` (threaded to `LockedBody` → `UnlockCta`).

Image branch — insert BEFORE the final `return null`, after the story branch:

```tsx
  if (fmt === 'image') {
    const media = payload.media ?? []
    const first = media[0]
    const ratio = first?.width && first?.height ? `${first.width} / ${first.height}` : '4 / 3'
    const canReveal = interactive && !revealed
    const titleSize = big ? 24 : 16
    return (
      <div className={className} onClick={() => canReveal && revealSetup()} style={{ cursor: canReveal ? 'pointer' : 'default' }}>
        <div style={{ fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: titleSize, color: skin.fg, lineHeight: 1.3, marginTop: 14 }}>
          {payload.setup}
        </div>
        <div
          data-testid="media-punchline"
          className={`punch-blur ${revealed ? 'is-revealed' : ''}`}
          style={{
            marginTop: 12,
            aspectRatio: ratio,
            maxHeight: big ? 520 : 420,
            borderRadius: 12,
            overflow: 'hidden',
            background: '#F1EFEC',
            display: 'flex',
            scrollSnapType: media.length > 1 ? 'x mandatory' : undefined,
            overflowX: media.length > 1 ? 'auto' : 'hidden',
          }}
        >
          {media.map((m, i) => (
            <img
              key={i}
              src={m.url ?? undefined}
              alt={payload.setup ? `${payload.setup} — panel ${i + 1}` : `joke image ${i + 1}`}
              loading="lazy"
              draggable={false}
              style={{
                width: '100%', height: '100%', objectFit: 'cover',
                flex: '0 0 100%', scrollSnapAlign: 'start',
              }}
            />
          ))}
        </div>
        {media.length > 1 && revealed && (
          <div className="eyebrow-mono" style={{ marginTop: 8, color: '#52525B' }}>1/{media.length} · swipe</div>
        )}
        {canReveal && <div className="eyebrow-mono" style={{ marginTop: 14, color: '#6A1CF6' }}>Tap to reveal →</div>}
      </div>
    )
  }
```

`LockedBody` — accept `ctaLabel` and add the media placeholder variant. When `payload.media?.length`, REPLACE the `LOCKED_FILL` text div with:

```tsx
        <div
          className="punch-blur"
          aria-hidden
          data-testid="locked-media-placeholder"
          style={{
            marginTop: hasTeaser ? 12 : 0,
            aspectRatio: first?.width && first?.height ? `${first.width} / ${first.height}` : '4 / 3',
            maxHeight: big ? 520 : 420,
            borderRadius: 12,
            background: 'repeating-linear-gradient(45deg, #E9E8E7, #E9E8E7 12px, #F1EFEC 12px, #F1EFEC 24px)',
          }}
        />
```

(`const first = payload.media?.[0]` at the top of `LockedBody`.) `UnlockCta` renders `{label ?? 'Unlock with Supporter'}` after the `<Lock>` icon, prop `label?: string`.

- [ ] **Step 4: Run tests + full suite**

Run: `npm test -- --run src/components/JokeRenderer.media.test.tsx` → PASS, then `npm test -- --run` → all green.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "media: image joke renderer branch with blur-reveal, carousel, and locked placeholder"
```

---

### Task 3: Create pipeline — upload mutation, ImageEditor, draft threading, mock branch

**Files:**
- Modify: `src/features/create/types.ts` (FORMAT_SLUGS L9, FormatRule.constraints L37, ContentDraft/DTO/PatchDraftBody)
- Modify: `src/features/create/api.ts` (contentApi + fromDTO + toPatchBody)
- Modify: `src/features/create/adapter.ts`, `src/features/create/mock.ts`
- Modify: `src/features/create/editor-state.ts` (EditorDraft, actions, groupOf, emptyEditorDraft, toJokePayload)
- Modify: `src/features/create/autosave.ts` (isMeaningful, runPatch payload)
- Modify: `src/features/create/mutations.ts` (add useUploadMedia)
- Modify: `src/features/create/validation.ts` (media branch)
- Create: `src/features/create/editors/ImageEditor.tsx`
- Modify: `src/features/create/editors/index.ts` (registry), `src/features/create/editors/formatIcon.ts` (FORMAT_ICON + FORMAT_EXAMPLE), `src/features/create/FormatPickerPage.tsx` (FALLBACK_FORMATS), `src/features/create/ChangeFormatModal.tsx` (FORMAT_OPTIONS) — match each file's existing entry shape exactly (read the file, copy an existing entry's structure for `image`)
- Test: `src/features/create/editors/ImageEditor.test.tsx` (create), `src/features/create/media-draft.test.ts` (create)

**Interfaces:**
- Consumes: backend `POST /media/uploads/` + `media_asset_ids` PATCH contract; Task 2 `JokePayload.media`.
- Produces: `MediaAssetDTO {id: string; kind: string; url: string|null; poster_url: string|null; width: number|null; height: number|null; duration_ms: number|null; is_gif: boolean}`; `EditorDraft.media: MediaAssetDTO[]`; action `{type:'setMedia'; media: MediaAssetDTO[]}`; `contentAdapter.uploadMedia(file: File, onProgress?: (pct:number)=>void): Promise<MediaAssetDTO>`; `useUploadMedia()` mutation. Task 4/5 rely on nothing here.

- [ ] **Step 1: Write the failing draft-threading tests**

Create `src/features/create/media-draft.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { editorReducer, emptyEditorDraft, toJokePayload } from './editor-state'
import { toPatchBody, fromDTO } from './api'
import { validate } from './validation'
import type { ContentDraftDTO, FormatRule } from './types'
import type { MediaAssetDTO } from './types'

const asset: MediaAssetDTO = {
  id: 'aaaa-bbbb', kind: 'image', url: 'http://x/a.webp', poster_url: null,
  width: 800, height: 600, duration_ms: null, is_gif: false,
}

const imageRule: FormatRule = {
  id: 9, slug: 'image', name: 'Image', description: '',
  required_fields: ['setup', 'media'], forbidden_fields: ['punchline', 'lines'],
  constraints: { min_media: 1, max_media: 6 },
}

describe('media in editor state', () => {
  it('setMedia stores assets and changeFormat across groups clears them', () => {
    let draft = emptyEditorDraft('image')
    draft = editorReducer(draft, { type: 'setMedia', media: [asset] })
    expect(draft.media).toHaveLength(1)
    draft = editorReducer(draft, { type: 'changeFormat', format: 'oneliner' })
    expect(draft.media).toHaveLength(0)
  })

  it('toJokePayload carries media for the preview/validator', () => {
    let draft = emptyEditorDraft('image')
    draft = editorReducer(draft, { type: 'setMedia', media: [asset] })
    expect(toJokePayload(draft).media).toHaveLength(1)
  })
})

describe('media in API mapping', () => {
  it('toPatchBody maps media to media_asset_ids', () => {
    expect(toPatchBody({ media: [asset] }).media_asset_ids).toEqual(['aaaa-bbbb'])
  })

  it('fromDTO hydrates media from the draft DTO', () => {
    const dto = {
      id: 5, text: 'c', setup: 'c', punchline: '', lines: null, format: 'image',
      status: 'draft', tones: [], context_tags: [], culture_tags: [],
      age_rating: null, last_edited_at: 'now', created_at: 'now', likes: null,
      media: [asset],
    } as unknown as ContentDraftDTO
    expect(fromDTO(dto).media).toHaveLength(1)
  })
})

describe('media validation', () => {
  it('image format requires at least one attachment', () => {
    const payload = toJokePayload(emptyEditorDraft('image'))
    payload.setup = 'caption'
    expect(validate(payload, imageRule)).toHaveProperty('media')
  })

  it('image format caps at max_media', () => {
    let draft = emptyEditorDraft('image')
    draft = editorReducer(draft, { type: 'setMedia', media: Array(7).fill(asset) })
    const payload = toJokePayload(draft)
    payload.setup = 'caption'
    expect(validate(payload, imageRule)).toHaveProperty('media')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/features/create/media-draft.test.ts`
Expected: FAIL — `setMedia` unknown action, `media` missing everywhere.

- [ ] **Step 3: Implement the data threading**

`types.ts`:
- `FORMAT_SLUGS` gains `'image'`.
- `FormatRule.constraints` gains `min_media?: number; max_media?: number; media_kind?: string`.
- New `export interface MediaAssetDTO { id: string; kind: string; url: string | null; poster_url: string | null; width: number | null; height: number | null; duration_ms: number | null; is_gif: boolean }`.
- `ContentDraft` gains `media: MediaAssetDTO[]`; `ContentDraftDTO` gains `media?: MediaAssetDTO[]`; `PatchDraftBody` gains `media_asset_ids?: string[]`.

`editor-state.ts`:
- `EditorDraft` gains `media: MediaAssetDTO[]`; `emptyEditorDraft` initializes `media: []`.
- `EditorAction` gains `| { type: 'setMedia'; media: MediaAssetDTO[] }`; reducer case: `return { ...state, media: action.media }`.
- `groupOf`: `if (fmt === 'image') return 'media'` (extend the `FormatGroup` union with `'media'`); crossing INTO or OUT OF the media group clears `media: []` in the reset block (and entering `media` group clears text/setup keeps nothing? Keep `setup` — the caption maps to setup which sp-group also uses: on `media` ↔ `sp` crossings KEEP `setup`, clear the rest; on other crossings clear `media`). Concretely, in the cross-group reset add `media: []` to the cleared fields, then `if (newGroup === 'media' && (oldGroup === 'sp')) newState.setup = state.setup` and vice versa.
- `toJokePayload` gains `media: d.media.length ? d.media : null` (JokePayload.media from Task 2 — map `MediaAssetDTO` to `JokeMediaItem` shape inline: `{ kind: 'image', url: m.url, width: m.width, height: m.height }`).

`api.ts`:
- `contentApi.uploadMedia`:

```ts
  uploadMedia: (file: File, onProgress?: (pct: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    form.append('kind', 'image')
    return api.post<MediaAssetDTO>('/media/uploads/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
      },
    })
  },
```

- `fromDTO` gains `media: d.media ?? []`; `toPatchBody` gains `if (p.media !== undefined) body.media_asset_ids = p.media.map((m) => m.id)`.

`autosave.ts`:
- `isMeaningful` gains `if (draft.media.length > 0) return true` (read `draft.media`, not the payload).
- `runPatch`'s `patchDraft` call gains `media: current.media,`.

`adapter.ts` + `mock.ts`:
- `contentAdapter.uploadMedia(file, onProgress)`: real path `contentApi.uploadMedia(...).then(r => r.data)`; mock path `mockContentApi.uploadMedia(file)` returning

```ts
  uploadMedia: async (file: File): Promise<MediaAssetDTO> => {
    await delay(300)
    return {
      id: `mock-${Date.now()}-${file.name}`, kind: 'image',
      url: URL.createObjectURL(file), poster_url: null,
      width: 800, height: 600, duration_ms: null, is_gif: false,
    }
  },
```

- `mock.ts`: `FORMAT_CATALOG` gains the image rule `{ id: 9, slug: 'image', name: 'Image', description: 'A caption with an image punchline.', required_fields: ['setup', 'media'], forbidden_fields: ['punchline', 'lines'], constraints: { min_media: 1, max_media: 6 } }`; `makeEmptyDTO`/`patchDraft` thread `media`/`media_asset_ids` (mock keeps a per-draft `media` array; a PATCH with `media_asset_ids` keeps only matching previously-uploaded mock assets — store uploaded mock DTOs in a module map by id).

`validation.ts` — in the required-fields loop add a `media` branch (payload.media is an array):

```ts
    if (field === 'media') {
      if (!payload.media || payload.media.length === 0) {
        errors[field] = 'add at least one image'
      }
      continue
    }
```

and after the constraints section:

```ts
  if (rule.constraints.max_media != null && payload.media && payload.media.length > rule.constraints.max_media) {
    errors.media = `at most ${rule.constraints.max_media} images`
  }
```

`mutations.ts`:

```ts
export function useUploadMedia() {
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: File; onProgress?: (pct: number) => void }) =>
      contentAdapter.uploadMedia(file, onProgress),
  })
}
```

- [ ] **Step 4: Run the threading tests**

Run: `npm test -- --run src/features/create/media-draft.test.ts` → PASS.

- [ ] **Step 5: Write the failing ImageEditor test**

Create `src/features/create/editors/ImageEditor.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ImageEditor } from './ImageEditor'
import { emptyEditorDraft, editorReducer, type EditorAction } from '../editor-state'

vi.mock('../adapter', () => ({
  contentAdapter: {
    uploadMedia: vi.fn(async () => ({
      id: 'up-1', kind: 'image', url: 'blob:mock', poster_url: null,
      width: 800, height: 600, duration_ms: null, is_gif: false,
    })),
  },
}))

function renderEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let draft = emptyEditorDraft('image')
  const dispatch = vi.fn((a: EditorAction) => { draft = editorReducer(draft, a) })
  const utils = render(
    <QueryClientProvider client={qc}>
      <ImageEditor draft={draft} dispatch={dispatch} />
    </QueryClientProvider>,
  )
  return { dispatch, get draft() { return draft }, ...utils }
}

describe('ImageEditor', () => {
  it('has a caption field wired to setField setup', () => {
    const { dispatch } = renderEditor()
    fireEvent.change(screen.getByLabelText(/caption/i), { target: { value: 'my caption' } })
    expect(dispatch).toHaveBeenCalledWith({ type: 'setField', field: 'setup', value: 'my caption' })
  })

  it('uploads a picked file and dispatches setMedia with the returned asset', async () => {
    const { dispatch } = renderEditor()
    const file = new File(['x'], 'joke.png', { type: 'image/png' })
    fireEvent.change(screen.getByTestId('image-file-input'), { target: { files: [file] } })
    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'setMedia' }),
      ),
    )
  })
})
```

- [ ] **Step 6: Run to verify failure, then implement ImageEditor**

Run: `npm test -- --run src/features/create/editors/ImageEditor.test.tsx` → FAIL (no module).

Create `src/features/create/editors/ImageEditor.tsx` (match sibling editors' label/spacing conventions — open `SetupPunchlineEditor.tsx` and reuse its field-label styling verbatim):

```tsx
import { useRef, useState } from 'react'
import { ImagePlus, X, ArrowUp, ArrowDown } from 'lucide-react'
import { useUploadMedia } from '../mutations'
import type { EditorProps } from './types'

const MAX_IMAGES = 6

export function ImageEditor({ draft, dispatch, errors }: EditorProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const upload = useUploadMedia()
  const [progress, setProgress] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const onPick = async (files: FileList | null) => {
    const file = files?.[0]
    if (!file || draft.media.length >= MAX_IMAGES) return
    setUploadError(null)
    setProgress(0)
    try {
      const asset = await upload.mutateAsync({ file, onProgress: setProgress })
      dispatch({ type: 'setMedia', media: [...draft.media, asset] })
    } catch {
      setUploadError('Upload failed — check the file (JPEG/PNG/WebP, max 10MB) and try again.')
    } finally {
      setProgress(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const removeAt = (i: number) =>
    dispatch({ type: 'setMedia', media: draft.media.filter((_, idx) => idx !== i) })

  const move = (i: number, dir: -1 | 1) => {
    const next = [...draft.media]
    const j = i + dir
    if (j < 0 || j >= next.length) return
    ;[next[i], next[j]] = [next[j], next[i]]
    dispatch({ type: 'setMedia', media: next })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <label style={{ display: 'block' }}>
        <span className="eyebrow-mono">Caption (the setup)</span>
        <textarea
          aria-label="Caption"
          value={draft.setup}
          onChange={(e) => dispatch({ type: 'setField', field: 'setup', value: e.target.value })}
          rows={2}
          placeholder="When the intern says 'quick question'…"
          style={{ width: '100%', marginTop: 8, padding: 12, borderRadius: 10, border: '1px solid #E9E8E7', fontFamily: 'var(--font-display)', fontSize: 16 }}
        />
        {errors?.setup && <span style={{ color: '#D33', fontSize: 12 }}>{errors.setup}</span>}
      </label>

      <div>
        <span className="eyebrow-mono">Image punchline ({draft.media.length}/{MAX_IMAGES})</span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
          {draft.media.map((m, i) => (
            <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 10, border: '1px solid #E9E8E7', borderRadius: 10, padding: 8 }}>
              <img src={m.url ?? undefined} alt={`panel ${i + 1}`} style={{ width: 72, height: 54, objectFit: 'cover', borderRadius: 6 }} />
              <span style={{ flex: 1, fontSize: 12, color: '#52525B' }}>Panel {i + 1}</span>
              <button type="button" aria-label={`move panel ${i + 1} up`} onClick={() => move(i, -1)} disabled={i === 0} style={{ height: 44, width: 44, background: 'transparent', border: 0, cursor: 'pointer' }}><ArrowUp size={16} /></button>
              <button type="button" aria-label={`move panel ${i + 1} down`} onClick={() => move(i, 1)} disabled={i === draft.media.length - 1} style={{ height: 44, width: 44, background: 'transparent', border: 0, cursor: 'pointer' }}><ArrowDown size={16} /></button>
              <button type="button" aria-label={`remove panel ${i + 1}`} onClick={() => removeAt(i)} style={{ height: 44, width: 44, background: 'transparent', border: 0, cursor: 'pointer' }}><X size={16} /></button>
            </div>
          ))}
          {draft.media.length < MAX_IMAGES && (
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={progress !== null}
              style={{ height: 64, borderRadius: 10, border: '2px dashed #E9E8E7', background: '#FBFAF7', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: '#52525B', fontWeight: 600 }}
            >
              <ImagePlus size={18} />
              {progress !== null ? `Uploading… ${progress}%` : 'Add image (JPEG/PNG/WebP, max 10MB)'}
            </button>
          )}
          <input
            ref={fileRef}
            data-testid="image-file-input"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            style={{ display: 'none' }}
            onChange={(e) => onPick(e.target.files)}
          />
          {uploadError && <span style={{ color: '#D33', fontSize: 12 }}>{uploadError}</span>}
          {errors?.media && <span style={{ color: '#D33', fontSize: 12 }}>{errors.media}</span>}
        </div>
      </div>
    </div>
  )
}
```

Register: `editors/index.ts` gains `image: React.lazy(() => import('./ImageEditor').then((m) => ({ default: m.ImageEditor }))),`. Add `image` entries to `FORMAT_ICON`/`FORMAT_EXAMPLE` (formatIcon.ts), `FALLBACK_FORMATS` (FormatPickerPage), `FORMAT_OPTIONS` (ChangeFormatModal) — copy each file's existing entry shape.

- [ ] **Step 7: Run all create-feature tests + full suite + build**

Run: `npm test -- --run src/features/create` → green; `npm test -- --run` → green; `npm run build` → clean.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "media: ImageEditor with upload/reorder, draft media threading, mock upload branch"
```

---

### Task 4: Bespoke-surface consolidation — detail, JOTD, daily, archive

**Files:**
- Modify: `src/pages/JokeDetailPage.tsx` (body branch ~L227-330)
- Modify: `src/pages/FlowCanvasPage.tsx` (`JotdBody` ~L304, `SevenDayArchive` strip ~L745)
- Modify: `src/pages/DailyJokePage.tsx` (hero ~L203-260)
- Test: `src/pages/JokeDetailPage.media.test.tsx` (create; follow the page's existing test file's render/mocking pattern)

**Interfaces:**
- Consumes: Tasks 1-2 (`jokeToFlowData` null-guard, renderer image branch).
- Produces: media jokes render on all four surfaces; no other task depends on this.

- [ ] **Step 1: JokeDetailPage** — media jokes route through the big card exactly like knock already does. In the unlocked body chain, add a media branch BEFORE the setup/punchline branch:

```tsx
        ) : (joke.media?.length ?? 0) > 0 ? (
          (() => { const flow = jokeToFlowData(joke); return flow ? <FlowJokeCard joke={flow} big source="detail" /> : null })()
        ) : joke.setup && joke.punchline ? (
```

AND in the `locked` branch: when `joke.media?.length`, render the same `<FlowJokeCard big>` path instead of the bespoke text-locked block (the card's LockedBody shows the dimensioned placeholder + CTA; `jokeToFlowData` carries `isLocked`). Keep the existing bespoke text-locked block for text formats.

- [ ] **Step 2: JotdBody (FlowCanvasPage)** — add a media branch after the setup/punchline branch (daily joke is paywall-exempt, so no locked state here):

```tsx
  const hasMedia = (joke.media?.length ?? 0) > 0
  if (hasMedia && joke.setup) {
    return (
      <div style={{ marginTop: 32, position: 'relative' }}>
        <span className="eyebrow-mono" style={{ color: '#6A1CF6' }}>Setup</span>
        <div style={{ fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 'clamp(1.25rem, 2.5vw, 1.875rem)', color: '#1A1A1A', lineHeight: 1.25, marginTop: 8, maxWidth: 640 }}>
          {joke.setup}
        </div>
        <span className="eyebrow-mono" style={{ color: '#6A1CF6', marginTop: 32, display: 'block' }}>Punchline</span>
        <div
          onClick={onReveal}
          className={`punch-blur ${revealed ? 'is-revealed' : ''}`}
          style={{ cursor: revealed ? 'default' : 'pointer', marginTop: 8, maxWidth: 640, aspectRatio: joke.media![0].width && joke.media![0].height ? `${joke.media![0].width} / ${joke.media![0].height}` : '4 / 3', borderRadius: 14, overflow: 'hidden', background: '#F1EFEC' }}
        >
          <img src={joke.media![0].url ?? undefined} alt={joke.setup} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </div>
      </div>
    )
  }
```

- [ ] **Step 3: DailyJokePage hero** — same branch shape as Step 2, inserted before the `isSetupPunch` ternary, using that page's local `revealed`/`handleReveal`/`joke` variables (read the surrounding component for exact names). Update the header eyebrow (`L200`) to show `'Image'` when media is present.

- [ ] **Step 4: SevenDayArchive strip** — the cell currently renders `(h.joke?.text ?? '').slice(0, 60)`. Change to: when `h.joke?.media?.length`, render a 40px-tall thumbnail `<img src={h.joke.media[0].url ?? undefined} …, objectFit: 'cover', borderRadius: 6 />` followed by the text slice (which is the caption via backfill).

- [ ] **Step 5: Test** — `JokeDetailPage.media.test.tsx`: render the page (using the file's existing test harness pattern for router/query mocks) with a media joke fixture → assert an `img` with the media URL appears; with a LOCKED media joke fixture (`is_locked: true`, media without `url`) → assert `queryAllByRole('img')` length 0 and the unlock CTA testid exists.

- [ ] **Step 6: Run full suite + build; commit**

```bash
npm test -- --run && npm run build
git add -A && git commit -m "media: image jokes on detail, JOTD, daily hero, and archive strip"
```

---

### Task 5: Anonymous paywall UI — reveal consumption + sign-up CTA

**Files:**
- Modify: `src/lib/api.ts` (add `revealApi`)
- Modify: `src/components/FlowJokeCard.tsx` (anon reveal call + CTA label/destination + image joins reveal-gated)
- Modify: `src/pages/JokeDetailPage.tsx` (locked CTA label/destination for anon)
- Test: `src/components/FlowJokeCard.anon.test.tsx` (create)

**Interfaces:**
- Consumes: backend `POST /jokes/{id}/reveal/`; `useAuth()` from `@/features/auth` (`{user, isAuthenticated}`); Task 2 `ctaLabel`.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing tests**

Create `src/components/FlowJokeCard.anon.test.tsx` (follow the mocking pattern of the existing FlowJokeCard test file for reactions/saved-jokes/telemetry/daily-reads; add `vi.mock('@/features/auth', ...)` returning `isAuthenticated: false` and `vi.mock('@/lib/api', ...)` with a spy `revealApi.post`):

```tsx
// Assertions (exact harness copied from the existing FlowJokeCard test file):
// 1. anon + unlocked setup joke: tapping the punchline calls revealApi.post(jokeId)
//    and does NOT call trackReveal (telemetry is authed-only).
// 2. anon + locked joke (isLocked: true): CTA reads 'Sign up free' and clicking
//    it navigates to /register (assert via the router mock the file already uses).
// 3. authed + locked joke: CTA reads 'Unlock with Supporter' and navigates to
//    /settings/billing (regression).
// 4. image-format joke is reveal-gated: with canReveal() -> false and a fresh
//    image joke, the card renders the locked CTA (softLocked applies to fmt 'image').
```

Write these as four real test cases with the harness — the comment block above is the required behavior list, not the test code; the file must contain executable tests for all four.

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/components/FlowJokeCard.anon.test.tsx` → FAIL.

- [ ] **Step 3: Implement**

`src/lib/api.ts`:

```ts
export const revealApi = {
  post: (jokeId: number) =>
    apiClient.post<{ limit: number; used: number; remaining: number; over: boolean; reset_at: string }>(
      `/jokes/${jokeId}/reveal/`,
    ),
}
```

(use the file's existing axios instance export name — it is the same client `dailyReadsApi` uses; match it.)

`FlowJokeCard.tsx`:
- `const { isAuthenticated } = useAuth()` (import from `@/features/auth`).
- Reveal-gated set gains image: `const revealGated = joke.fmt === 'setup' || joke.fmt === 'knock' || joke.fmt === 'image'`.
- `handleReveal` — after `registerReveal(numericId)`: authed path unchanged (`if (source) trackReveal(...)`); anon path:

```ts
    if (!isAuthenticated) {
      revealApi.post(numericId)
        .then(() => queryClient.invalidateQueries({ queryKey: dailyReadsKeys.all }))
        .catch(() => { /* soft wall — best-effort */ })
    }
```

(`useQueryClient` from @tanstack/react-query; `dailyReadsKeys` from `@/features/daily-reads` — export it from the feature's index if not already.)
- CTA: `<JokeRenderer ... ctaLabel={isAuthenticated ? undefined : 'Sign up free'} onUnlock={() => navigate(isAuthenticated ? '/settings/billing' : '/register')} />`.

`JokeDetailPage.tsx` — the bespoke text-locked block's CTA button: same auth-conditional label + destination (`useAuth` may already be imported on the page; check).

- [ ] **Step 4: Run tests + full suite; commit**

```bash
npm test -- --run src/components/FlowJokeCard.anon.test.tsx && npm test -- --run
git add -A && git commit -m "paywall: anon reveal consumption + sign-up CTA on locked jokes"
```

---

### Task 6: ToS amendment + final suite + deploy notes

**Files:**
- Modify: `src/content/legal/terms.ts` (Acceptable Use section, ~L39)
- Test: existing legal-page tests (adjust only if they assert the text-only wording)

- [ ] **Step 1: Amend the Acceptable Use section**

Replace the text-only clause (which currently declares the platform text-only and forbids uploading images/videos/audio) with:

```
You may submit text jokes and, where the feature is available, image-based
jokes you own or have the right to publish. All uploads are screened
automatically and reviewed by our moderation team before publication, and
metadata (such as EXIF location data) is removed from images at upload. Do
not upload content that is unlawful, infringing, sexually explicit, violent,
or that depicts identifiable private individuals without their consent. We
may remove any upload at our discretion and suspend accounts that repeatedly
violate these rules. Audio and video submissions are not yet supported.
```

Keep the rest of the section (unlawful/infringing bans) intact. Bump the terms `lastUpdated` date constant if the file has one.

**OWNER GATE: the exact wording ships only after the owner signs off — the task lands the draft; the controller surfaces the diff to the owner before the frontend deploy.**

- [ ] **Step 2: Full suite + build**

Run: `npm test -- --run` → ALL green (633 + new). Run: `npm run build` → clean.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "legal: permit moderated image uploads in Acceptable Use; note screening and EXIF removal"
```

---

## Deployment notes (owner-visible, not tasks)

- **Frontend deploys FIRST** (spec §11): the unknown-format guard + image rendering must be live before the backend branch (with the `image` Format row migration) reaches prod main.
- ToS wording is owner-gated (Task 6).
- After both deploys: seed one real image joke end-to-end (upload → submit → admin approve) as the smoke test; verify the anon wall by browsing logged-out past 10 reveals.
