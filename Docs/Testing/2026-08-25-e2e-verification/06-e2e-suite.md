# The end-to-end suite — closing the structural gap

**Added 2026-08-27.** Lives in the frontend repo at `jokes-for-frontend/e2e/`.

## The gap it closes

Fixing the 20 findings fixed *bugs*. It did not fix the thing that let three P0s
reach production behind 1,676 passing tests.

That cause is structural, not a lapse in care:

| Suite | What it mocks | So it cannot see |
|---|---|---|
| 799 vitest | the API (`src/lib/mock-api.ts`, jsdom) | any real response shape; any layout |
| 877 Django | Stripe, Vision, GCS, email, and the client | any real client payload |

Each side is tested against **its own idea of the contract**, so drift between
them is invisible to both. Two concrete illustrations from this pass:

- The paywall fixtures build jokes with `text=''`. Real published rows carry a
  denormalized `"<setup> <punchline>"`. The leak was therefore *impossible* for
  those tests to see, no matter how many were added.
- jsdom has no layout engine, so the consent banner covering the entire mobile
  navigation could never surface in a component test.

## What it is

A real Chromium, driving the real SPA, against the real Django API and a real
Postgres. Playwright starts both servers itself on non-default ports (`:8011` /
`:5274`) and runs `migrate` + `seed_achievements` + `seed_e2e` before serving, so
a run can never execute against a stale schema or an empty catalogue.
`DATABASE_URL` is forced to `''`, which pins the backend to local Postgres —
**a suite run cannot point at production Neon.**

```bash
npm run e2e            # everything
npm run e2e:desktop    # desktop project
npm run e2e:mobile     # the *.mobile.spec.ts specs under Pixel 5
npm run e2e:headed     # watch it
```

## Three conventions, each earned by a specific bug

**Assert on the payload, not the pixels.** The paywall leak rendered a correct
`████` redaction while shipping the punchline in the JSON. `apiGet(page, path)`
runs inside the browser's own session, so a spec inspects exactly what the app
received — not a parallel request that might be in a different state.

**Cover every variant, not a convenient one.** The leak was format-specific:
one-liners were safe, two-part jokes were not, and the format sampled by hand
happened to be a safe one. `seed_e2e` creates one joke of *every* format —
shaped the way the publish pipeline shapes them, denormalized `text` included —
and the regression spec loops over all of them.

**Set up through the API; assert through the thing under test.** Twelve clicks
to reach a capped paywall is slow and brittle; `exhaustFreeReads()` then
asserting the UI is fast and precise.

Each spec creates its own account. The paywall, streaks and achievements are all
per-user-per-day, so a shared fixture user would make specs order-dependent and
quietly flaky — and a flaky E2E suite gets muted, which would put us straight
back where we started.

## No test-only authentication bypass

The backend runs with Django's file-based email backend and `fixtures/mail.ts`
reads the verification code out of the **real rendered message**. The
alternative — a test-only "activate this user" endpoint — would mean a code path
whose entire purpose is skipping authentication, living in the production
codebase forever. This way the template, the notification service and the
code-issuing path all run exactly as they do in production; only the transport
changes.

(`EMAIL_FILE_PATH` was added to `settings.py` for this. It is read only by the
file-based backend and is unset in production, where the backend is Resend.)

## Regression guards for the P0s

| Spec | Guards |
|---|---|
| `paywall.spec.ts` | **F-021** — no locked joke ships its punchline in *any* field, in *any* format; every serving path (list/search/random/detail) applies the lock |
| `share-seo.spec.ts` | **F-000** — the punchline appears nowhere in the share page, body included |
| `telemetry.spec.ts` | **F-006** — telemetry returns 202, not 403 |
| `onboarding.spec.ts` | **F-005** — onboarding actually persists, and vibes drive personalization |
| `contract.spec.ts` | **F-004 / F-011 / F-007 / F-012** — full catalogues, union filters, earnable achievements, stable daily joke |
| `consent.mobile.spec.ts` | **F-003** — the banner cannot cover the mobile navigation |
| `auth.spec.ts` | age gate, generic unverified-login error, CSRF enforcement |

## CI

`.github/workflows/e2e.yml` runs the suite with a Postgres service, checking out
the backend repo alongside. It needs a `BACKEND_REPO_TOKEN` secret with read
access to `Nard248/JokesForBackEnd`.

Without that secret the job **skips and emits a warning** rather than failing
red — but the warning says plainly that the FE↔BE contract is unverified on that
commit, so the unconfigured state is visible rather than silent.

## Honest limits

This suite still does not cover the prod-only surfaces: Google OAuth consent,
GCS and Vision in production, Resend inbox delivery, Stripe hosted checkout, or
`SameSite=None` cross-site cookies. Those need a staging environment with real
third-party credentials. They remain the largest untested area.

---

## What building it actually took

Recorded because the failure modes here are the ones that make an E2E suite get
muted, and the fixes are not obvious from the outside.

**Three of my own assumptions were wrong**, each caught by running the specs
rather than reasoning about them:

- `/login` is guest-only, so a spec that had already established a cookie
  session got bounced away before the form rendered. Fixed by registering the
  persona through an **isolated request context** (`createVerifiedPersona`), so
  the browser starts genuinely logged out.
- Clearing cookies is not logging out. The SPA persists its auth store in
  `sessionStorage`, and the route guard reads that.
- A synthetic `pagehide` flushes telemetry, but only if something is queued.
  Impressions need sustained visibility (`IntersectionObserver` + a dwell
  timer), so the queue was empty. Driving a joke *detail view* — where
  `trackReveal` fires on load — is the reliable trigger.

**Two backend changes were required**, both defaults-preserving:

- `EMAIL_FILE_PATH` in `settings.py`, read only by the file-based mail backend
  and unset in production.
- Env-overridable throttle rates (`THROTTLE_ANON`, `THROTTLE_USER`, …), all
  defaulting to the current production values. The suite drives dozens of real
  signups and reads from one IP and was **throttling itself** to 429 — a tier
  that flakes gets muted, which is the exact failure this tier exists to
  prevent. The limits themselves stay covered by the backend's own throttle
  tests.

**Two config bugs of mine**, found by the first full run rather than the
per-spec runs:

- The desktop project had no `testIgnore`, so it also ran the `*.mobile.spec.ts`
  geometry specs at a desktop viewport, where they fail for the wrong reason.
- `reuseExistingServer` would silently reuse a backend left over from an earlier
  run — one started with *different* env (old throttle limits, a different mail
  dir). The resulting failures look exactly like product bugs. Now set to
  `false`: a few seconds slower, and it removes a whole class of phantom
  flakiness.

That last one is worth internalising. A green suite is only evidence if you can
trust what it ran against.
