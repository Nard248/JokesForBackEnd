# Phase 11: Frontend Foundation - Context

**Gathered:** 2026-01-11
**Status:** Ready for research

<vision>
## How This Should Work

The frontend should feel **playful and engaging** — not just functional, but fun to use. The UI itself should have personality, with quirky touches and unexpected delights. Think easter eggs, surprising micro-interactions, and a vibe that matches the humor content.

The app should feel like it has a personality of its own — not corporate, not boring, but genuinely entertaining even before you read a joke.

Mobile-first is essential — most users will browse jokes on their phones.

</vision>

<essential>
## What Must Be Nailed

- **Solid API integration** — Auth flow and data fetching work flawlessly. JWT token management, refresh flow, error handling. Everything else builds on this foundation.
- **The shell/layout feel** — Get the overall vibe right. Colors, typography, spacing that feels quirky and unexpected. This is the personality foundation.
- **Mobile-first responsive** — Works great on phones first. Desktop is an enhancement, not the default.

All three are equally important — can't ship without all working well.

</essential>

<boundaries>
## What's Out of Scope

- **Animations and polish** — Get the structure working first. Micro-interactions, transitions, and delightful touches come in Phase 12.
- **Feature pages** — Search UI, collections management, daily joke widget, etc. are Phase 12. This phase is shell + infrastructure only.
- **Dark mode** — Single theme for now. Can add theme switching later.

</boundaries>

<specifics>
## Specific Ideas

**Stack:**
- TailwindCSS for styling
- Shadcn/ui as component library base
- Open to futuristic, easy-to-use tools
- Playwright for E2E testing

**Repository:**
- Separate repo from backend (not monorepo)
- Location: `/Users/narekmeloyan/WebstormProjects/`
- GitHub remote: `https://github.com/Nard248/JokesForFrontEnd.git`
- Branch: `main`

**Tech decisions to make during research:**
- React Query vs SWR vs Zustand for state management
- JWT token storage strategy (httpOnly cookies already on backend)
- Project structure conventions

</specifics>

<notes>
## Additional Context

**Operational notes:**
- Claude operates from the backend terminal but can cd to frontend directory
- Planning tracked in backend's `.planning/` (same milestone)
- Git commits happen in the frontend repo when working on frontend code
- Vite/npm commands run from frontend directory

**User preference:**
- Wants things that are "futuristic and easy to do"
- Open to recommendations on tooling
- Testing infrastructure (Playwright) should be part of foundation

</notes>

---

*Phase: 11-frontend-foundation*
*Context gathered: 2026-01-11*
