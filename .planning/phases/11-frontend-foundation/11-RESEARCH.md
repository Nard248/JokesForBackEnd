# Phase 11: Frontend Foundation - Research

**Researched:** 2026-01-11
**Domain:** React + Vite + TypeScript with TailwindCSS v4 and shadcn/ui
**Confidence:** HIGH

<research_summary>
## Summary

Researched the modern React frontend ecosystem for building a playful, mobile-first joke discovery app. The standard 2025/2026 approach uses React 19 with Vite 6, TypeScript, TailwindCSS v4 (CSS-first config), and shadcn/ui components built on Radix primitives.

Key finding: State management has evolved to a clear separation of concerns - TanStack Query for server state (API data, caching, sync) and Zustand for client state (UI state, auth tokens). Don't use a single state solution for both. JWT authentication with httpOnly cookies (already implemented on backend) requires Axios interceptors for token refresh, with careful handling of refresh queues to avoid race conditions.

The project structure should follow feature-based organization (inspired by Bulletproof React) rather than technical-layer organization for maintainability at scale.

**Primary recommendation:** Use React 19 + Vite 6 + TailwindCSS v4 (@tailwindcss/vite) + shadcn/ui. State: TanStack Query for server data + Zustand for client state. Auth: Axios interceptors with httpOnly cookie refresh tokens. Testing: Playwright for E2E.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react | 19.x | UI framework | Latest stable, concurrent rendering by default, new hooks |
| react-dom | 19.x | DOM rendering | Paired with React 19 |
| vite | 6.x | Build tool & dev server | Fastest DX, ESM-native, official React template |
| typescript | 5.x | Type safety | Standard for production React apps |

### Styling & Components
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tailwindcss | 4.x | Utility-first CSS | CSS-first config, 3.5x faster, no JS config needed |
| @tailwindcss/vite | 4.x | Vite plugin | Native integration, no PostCSS setup required |
| shadcn/ui | canary | Component library | Copy-paste ownership, Radix primitives, Tailwind v4 compatible |
| lucide-react | latest | Icons | Modern, tree-shakeable, shadcn/ui default |
| clsx | latest | Conditional classes | Lightweight, pairs with tailwind-merge |
| tailwind-merge | latest | Class conflict resolution | Prevents Tailwind class conflicts |

### State Management
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| @tanstack/react-query | 5.x | Server state | Caching, background sync, deduplication |
| zustand | 5.x | Client state | Minimal boilerplate, no providers needed |

### Routing & Navigation
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react-router | 7.x | Client-side routing | De facto standard, nested routes, loaders |

### HTTP & Auth
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| axios | 1.x | HTTP client | Interceptors for JWT refresh, request/response transforms |

### Testing
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| @playwright/test | latest | E2E testing | Real browser testing, parallel execution, best DX |
| vitest | latest | Unit testing | Vite-native, Jest-compatible, fast |

### Dev Experience
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| @tanstack/react-query-devtools | 5.x | Query debugging | Visualize cache, queries, mutations |
| eslint | 9.x | Linting | Flat config, React plugin |
| prettier | latest | Formatting | Code consistency |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Zustand | Jotai | Jotai is atom-based, better for fine-grained state; Zustand simpler for this scale |
| Axios | Fetch + wrapper | Axios has built-in interceptors; fetch requires more boilerplate |
| React Router | TanStack Router | TanStack newer, React Router more mature ecosystem |
| Playwright | Cypress | Playwright faster parallel execution, better multi-browser |

**Installation:**
```bash
# Core
npm create vite@latest jokes-for-frontend -- --template react-ts
cd jokes-for-frontend

# Styling
npm install tailwindcss @tailwindcss/vite

# Components (shadcn/ui installed via CLI)
npx shadcn@canary init

# State & Routing
npm install @tanstack/react-query @tanstack/react-query-devtools zustand react-router

# HTTP
npm install axios

# Testing
npm install -D @playwright/test vitest
npx playwright install

# Dev tools
npm install -D eslint prettier eslint-plugin-react-hooks
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
src/
├── app/                    # Application shell
│   ├── App.tsx            # Root component with providers
│   ├── routes.tsx         # Route definitions
│   └── providers/         # Context providers (QueryClient, Auth)
├── components/            # Shared UI components
│   └── ui/                # shadcn/ui components (auto-generated)
├── features/              # Feature-based modules
│   ├── auth/              # Authentication feature
│   │   ├── components/    # Auth-specific components
│   │   ├── hooks/         # useAuth, useUser
│   │   ├── api/           # Auth API calls
│   │   └── store.ts       # Auth state (Zustand)
│   ├── search/            # Search feature
│   ├── jokes/             # Joke display feature
│   └── collections/       # Collections feature
├── hooks/                 # Shared hooks
├── lib/                   # Configured libraries
│   ├── axios.ts           # Axios instance with interceptors
│   ├── query-client.ts    # TanStack Query client config
│   └── utils.ts           # Utility functions (cn, etc.)
├── types/                 # Shared TypeScript types
└── main.tsx               # Entry point
```

### Pattern 1: TanStack Query for Server State
**What:** All API data fetched and cached via useQuery/useMutation
**When to use:** Any data from the backend API
**Example:**
```typescript
// src/features/jokes/api/jokes.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/axios'

export const jokeKeys = {
  all: ['jokes'] as const,
  search: (params: SearchParams) => [...jokeKeys.all, 'search', params] as const,
  detail: (id: number) => [...jokeKeys.all, 'detail', id] as const,
}

export function useJokeSearch(params: SearchParams) {
  return useQuery({
    queryKey: jokeKeys.search(params),
    queryFn: () => api.get('/jokes/', { params }).then(r => r.data),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

export function useRateJoke() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ jokeId, rating }: { jokeId: number; rating: 1 | -1 }) =>
      api.post(`/jokes/${jokeId}/rate/`, { rating }),
    onSuccess: (_, { jokeId }) => {
      queryClient.invalidateQueries({ queryKey: jokeKeys.detail(jokeId) })
    },
  })
}
```

### Pattern 2: Zustand for Client State
**What:** UI state, auth tokens, user preferences stored in Zustand
**When to use:** State not from server, or derived state
**Example:**
```typescript
// src/features/auth/store.ts
import { create } from 'zustand'

interface AuthState {
  accessToken: string | null
  isAuthenticated: boolean
  setAccessToken: (token: string | null) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  isAuthenticated: false,
  setAccessToken: (token) => set({
    accessToken: token,
    isAuthenticated: !!token
  }),
  logout: () => set({ accessToken: null, isAuthenticated: false }),
}))
```

### Pattern 3: Axios Interceptors for JWT Refresh
**What:** Automatic token refresh on 401, request queue for concurrent failures
**When to use:** All authenticated API calls
**Example:**
```typescript
// src/lib/axios.ts
import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/features/auth/store'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true, // Include httpOnly cookies
})

let isRefreshing = false
let refreshSubscribers: ((token: string) => void)[] = []

function subscribeTokenRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb)
}

function onRefreshed(token: string) {
  refreshSubscribers.forEach(cb => cb(token))
  refreshSubscribers = []
}

// Request interceptor - attach access token
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor - handle 401 and refresh
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Queue this request until token is refreshed
        return new Promise((resolve) => {
          subscribeTokenRefresh((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(api(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        // Refresh token is in httpOnly cookie, sent automatically
        const { data } = await axios.post(
          `${import.meta.env.VITE_API_URL}/auth/token/refresh/`,
          {},
          { withCredentials: true }
        )

        useAuthStore.getState().setAccessToken(data.access)
        onRefreshed(data.access)
        originalRequest.headers.Authorization = `Bearer ${data.access}`
        return api(originalRequest)
      } catch (refreshError) {
        useAuthStore.getState().logout()
        window.location.href = '/login'
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

export { api }
```

### Pattern 4: Feature-Based Module Organization
**What:** Group all code for a feature together instead of by technical layer
**When to use:** Always - prevents cross-codebase imports for single features
**Example:**
```typescript
// src/features/collections/index.ts
// Each feature has its own components, hooks, API, and state

// Components
export { CollectionList } from './components/CollectionList'
export { CollectionCard } from './components/CollectionCard'

// Hooks
export { useCollections, useCreateCollection } from './api/collections'

// Types
export type { Collection, SavedJoke } from './types'
```

### Anti-Patterns to Avoid
- **Barrel files in large features:** Vite can't tree-shake properly; import directly instead
- **Mixing server and client state:** Don't put API data in Zustand; use TanStack Query
- **Deep folder nesting:** Max 2-3 levels; keeps imports manageable
- **Cross-feature imports:** Features should not import from other features; compose at app level
- **localStorage for tokens:** Use httpOnly cookies (already configured on backend)
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Data fetching & caching | Custom hooks with useEffect + useState | TanStack Query | Cache invalidation, deduplication, background sync, devtools |
| Token refresh logic | Custom fetch wrapper | Axios interceptors with queue pattern | Race conditions, retry logic, concurrent request handling |
| Component primitives | Custom accessible dialogs, dropdowns, etc. | shadcn/ui (Radix) | ARIA compliance, keyboard nav, focus traps are hard |
| Form handling | Manual state + validation | react-hook-form + zod | Validation, error states, controlled vs uncontrolled |
| Class merging | String concatenation | clsx + tailwind-merge | Tailwind class conflicts (e.g., px-2 vs px-4) |
| Routing | Custom history management | React Router | Nested routes, code splitting, loaders/actions |
| Date formatting | Manual format functions | date-fns or dayjs | Timezones, locales, relative time |
| Icons | Custom SVG management | lucide-react | Tree-shakeable, consistent sizing, TypeScript |

**Key insight:** The React ecosystem in 2025 is mature. Every common problem has a battle-tested solution. Custom implementations waste time and introduce bugs. The project's "playful and engaging" UX goal is better served by spending time on creative features, not reimplementing data fetching.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Barrel File Performance
**What goes wrong:** Slow dev server, failed tree-shaking, large bundles
**Why it happens:** Barrel files (index.ts re-exports) force Vite to load all modules
**How to avoid:** Import directly from files, not from feature index
**Warning signs:** Slow HMR, large chunks in bundle analysis

### Pitfall 2: JWT Refresh Race Conditions
**What goes wrong:** Multiple concurrent 401s trigger multiple refresh attempts, some requests fail
**Why it happens:** No queue management for requests during token refresh
**How to avoid:** Implement subscriber pattern (shown in axios.ts above)
**Warning signs:** Intermittent auth failures, multiple refresh token calls in network tab

### Pitfall 3: Mixed State Management
**What goes wrong:** Stale data, cache inconsistencies, complex debugging
**Why it happens:** Storing server data in Zustand instead of TanStack Query
**How to avoid:** Clear rule: TanStack Query for server state, Zustand for client state only
**Warning signs:** Manual refetching, data out of sync between components

### Pitfall 4: React 19 Compatibility Issues
**What goes wrong:** Libraries fail, hooks behave differently
**Why it happens:** Some libraries not yet updated for React 19
**How to avoid:** Check library React 19 compatibility before installing; shadcn/ui canary supports React 19
**Warning signs:** Console warnings about deprecated patterns, forwardRef issues

### Pitfall 5: Tailwind v4 Migration Confusion
**What goes wrong:** Config not applied, classes not working
**Why it happens:** v4 uses CSS-first config (@theme), not tailwind.config.js
**How to avoid:** Use @tailwindcss/vite plugin, configure in CSS with @theme directive
**Warning signs:** Custom colors not working, config file ignored

### Pitfall 6: CORS Cookie Issues
**What goes wrong:** Refresh token cookie not sent with requests
**Why it happens:** Missing withCredentials: true, or CORS misconfigured
**How to avoid:** Set withCredentials: true on axios instance; verify backend CORS_ALLOW_CREDENTIALS
**Warning signs:** 401 on refresh attempts, cookie present in browser but not in request
</common_pitfalls>

<code_examples>
## Code Examples

Verified patterns from official sources:

### TailwindCSS v4 Setup (vite.config.ts)
```typescript
// Source: https://tailwindcss.com/docs/installation/using-vite
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
})
```

### TailwindCSS v4 CSS-First Config
```css
/* src/index.css */
/* Source: https://tailwindcss.com/blog/tailwindcss-v4 */
@import "tailwindcss";

@theme {
  --color-primary: oklch(0.7 0.15 180);
  --color-secondary: oklch(0.6 0.12 280);
  --font-display: "Poppins", sans-serif;
}
```

### TanStack Query Provider Setup
```typescript
// src/app/providers/QueryProvider.tsx
// Source: https://tanstack.com/query/latest/docs/framework/react/overview
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      retry: 1,
    },
  },
})

export function QueryProvider({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
```

### Zustand Store with TypeScript
```typescript
// Source: https://github.com/pmndrs/zustand
import { create } from 'zustand'

interface UIState {
  isMobileMenuOpen: boolean
  toggleMobileMenu: () => void
  closeMobileMenu: () => void
}

export const useUIStore = create<UIState>((set) => ({
  isMobileMenuOpen: false,
  toggleMobileMenu: () => set((state) => ({ isMobileMenuOpen: !state.isMobileMenuOpen })),
  closeMobileMenu: () => set({ isMobileMenuOpen: false }),
}))
```

### Playwright E2E Test Example
```typescript
// e2e/auth.spec.ts
// Source: https://playwright.dev/docs/test-components
import { test, expect } from '@playwright/test'

test('user can log in', async ({ page }) => {
  await page.goto('/login')
  await page.fill('[name="email"]', 'test@example.com')
  await page.fill('[name="password"]', 'password123')
  await page.click('button[type="submit"]')

  await expect(page).toHaveURL('/dashboard')
  await expect(page.locator('text=Welcome')).toBeVisible()
})
```

### React Router Setup
```typescript
// src/app/routes.tsx
import { createBrowserRouter, RouterProvider } from 'react-router'
import { Layout } from '@/components/Layout'

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'jokes/:id', element: <JokeDetailPage /> },
      { path: 'collections', element: <CollectionsPage /> },
    ],
  },
  {
    path: '/login',
    element: <LoginPage />,
  },
])

export function AppRoutes() {
  return <RouterProvider router={router} />
}
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

What's changed recently:

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| create-react-app | Vite | Feb 2025 | CRA officially deprecated, Vite is default |
| tailwind.config.js | CSS-first @theme | Jan 2025 | No more JS config, 3.5x faster builds |
| forwardRef pattern | React.ComponentProps | React 19 | shadcn/ui components simplified |
| useMemo/useCallback | React Compiler (auto) | React 19 | Manual memoization often unnecessary |
| useState for server data | TanStack Query | 2024+ | Don't mix server/client state |
| Redux for everything | Query + Zustand | 2024+ | Purpose-built tools for each state type |

**New tools/patterns to consider:**
- **React 19 Actions API:** Built-in form handling with pending states, optimistic updates
- **useOptimistic hook:** Native optimistic UI updates without libraries
- **Activity component (19.2):** Pre-render hidden UI without performance impact
- **Motion Primitives:** Animation library designed specifically for shadcn/ui

**Deprecated/outdated:**
- **create-react-app:** Officially deprecated Feb 2025, do not use
- **Tailwind JS config:** Still works but CSS-first is now recommended
- **forwardRef:** React 19 passes ref as prop, forwardRef being phased out
- **localStorage for JWT:** Security risk, use httpOnly cookies
</sota_updates>

<open_questions>
## Open Questions

Things that couldn't be fully resolved:

1. **React Router v7 vs TanStack Router**
   - What we know: Both are production-ready, React Router more mature
   - What's unclear: TanStack Router has better TypeScript, but smaller ecosystem
   - Recommendation: Use React Router for stability; reconsider if type-safety issues arise

2. **Optimal staleTime for joke data**
   - What we know: Jokes don't change often, but ratings/scores do
   - What's unclear: Best cache strategy for mixed update frequencies
   - Recommendation: Start with 5-minute staleTime, tune based on usage patterns

3. **Animation library choice**
   - What we know: Context mentions "playful, quirky" UI with animations
   - What's unclear: Whether to use Framer Motion, Motion Primitives, or CSS transitions
   - Recommendation: Defer to Phase 12 (Frontend Features); foundation should work without animations
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [Vite Official Guide](https://vite.dev/guide/) - Project setup, configuration
- [TailwindCSS v4 Blog](https://tailwindcss.com/blog/tailwindcss-v4) - v4 features, CSS-first config
- [TailwindCSS Vite Installation](https://tailwindcss.com/docs/installation/using-vite) - Official setup steps
- [shadcn/ui Tailwind v4](https://ui.shadcn.com/docs/tailwind-v4) - Component library setup
- [TanStack Query Overview](https://tanstack.com/query/latest/docs/framework/react/overview) - Server state management
- [Zustand GitHub](https://github.com/pmndrs/zustand) - Client state patterns
- [React 19 Release](https://react.dev/blog/2024/12/05/react-19) - New features, hooks
- [React 19.2](https://react.dev/blog/2025/10/01/react-19-2) - Latest updates

### Secondary (MEDIUM confidence)
- [Bulletproof React](https://github.com/alan2207/bulletproof-react/blob/master/docs/project-structure.md) - Project structure patterns
- [Robin Wieruch React Folder Structure](https://www.robinwieruch.de/react-folder-structure/) - Feature-based organization
- [BezKoder JWT Cookie Auth](https://www.bezkoder.com/react-login-example-jwt-hooks/) - Auth flow patterns
- [Redux vs TanStack Query & Zustand](https://www.bugragulculer.com/blog/good-bye-redux-how-react-query-and-zustand-re-wired-state-management-in-25) - State management comparison

### Tertiary (LOW confidence - needs validation)
- None - all findings verified against official sources
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: React 19 + Vite 6 + TypeScript
- Ecosystem: TailwindCSS v4, shadcn/ui, TanStack Query, Zustand, React Router, Axios, Playwright
- Patterns: Feature-based structure, JWT refresh interceptors, server/client state separation
- Pitfalls: Barrel files, token race conditions, state mixing, v4 config confusion

**Confidence breakdown:**
- Standard stack: HIGH - verified with official docs and 2025/2026 sources
- Architecture: HIGH - Bulletproof React pattern widely adopted, verified
- Pitfalls: HIGH - documented in multiple sources, common issues
- Code examples: HIGH - from official documentation

**Research date:** 2026-01-11
**Valid until:** 2026-02-11 (30 days - React/Vite ecosystem relatively stable)
</metadata>

---

*Phase: 11-frontend-foundation*
*Research completed: 2026-01-11*
*Ready for planning: yes*
