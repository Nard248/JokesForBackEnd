# Frontend Integration Guide — Email Verification (Registration)

**Audience:** The frontend engineer / FE agent who owns the Jokes For web app (React + Vite + TS, TanStack Query, Zustand, axios with JWT-cookie auth). You did not build the backend side of this; this document gives you everything you need to integrate the new registration email-verification flow.

**Status:** Backend built, tested, and **deployed to production** (2026-06-12). Email sending is live (Resend, domain `jokesfor.net` verified). The flow is currently **dormant in production behind a flag** — see §4. Your job is to build the UI so the flag can be turned on.

**How to read this doc:** §2–§5 are *context and product intent* — read them to understand *why*. §7 is the *exact API contract* — that part is precise and non-negotiable. Everything about FE code (components, state, hooks) is **suggestion, not prescription** — the approaches here are starting points; **you decide the implementation that fits the existing app best.**

**Companion docs in this repo:**
- `Docs/API/Frontend_Integration_Handout.md` — the broad API surface
- `Docs/API/Frontend_Content_Creation_Spec.md` — the creator-authoring feature (same house style)

---

## 1. TL;DR

We added **email verification at registration**: a new user receives a **6-digit code** by email and must enter it before they get a session. It's a security/anti-spam/compliance requirement (COPPA/GDPR posture).

The backend change is **gated behind a flag** (`EMAIL_VERIFICATION_REQUIRED`) that is currently **OFF in production**, so today's signup behaves exactly as before. You build the verification UI; once it ships, we flip the flag and the new flow goes live. **Both modes must be supported by the FE during the transition** — and, helpfully, the FE can tell which mode it's in *from the registration response itself* (§4).

Three new/changed endpoints, all under `/api/v1/auth/`:
- `POST registration/` — now *may* return "verify your email" instead of logging you in
- `POST verify-email/` — submit the code → get logged in
- `POST resend-verification/` — request a new code

Google OAuth sign-in is **unaffected** (no code step). §11.

---

## 2. Session Context — What we built on the backend

So you understand the shape of what you're integrating with, here's the arc of work this produced:

### 2.1 A reusable notification engine (not just verification)
We stood up a `notifications` Django app — a **provider-agnostic email engine**:
- An **outbox/audit table** (`EmailMessageLog`) records every email the system attempts (pending → sent / failed).
- A **template registry** maps a template name (e.g. `verification_code`) to its subject + HTML + text bodies.
- A **single `send_email()` entry point** that feature code calls; it renders, logs, and dispatches through Django's standard mail layer.
- The transport is **django-anymail → Resend** in production (swappable to SES/Postmark by config; you never see this).

The point: verification is the *first* feature on this engine. Password-reset emails, streak nudges, and marketing campaigns will reuse the same engine later. For you, that's context — it means the email infrastructure is solid and not a one-off hack.

### 2.2 Registration email verification (the feature you're integrating)
- A **6-digit numeric code** (not a magic link), 10-minute expiry, hashed at rest, max 5 wrong attempts, then dead.
- The user is created **inactive** and gets **no session** until the code is verified — a **hard gate**.
- **Resend throttle**: max 3 resend requests per 15 minutes per email.
- **Anti-enumeration**: error responses are uniform so an attacker can't probe which emails exist (this constrains some of your UX copy — see §12).
- **Google OAuth users are exempt** — Google already verified their email, so the social flow is unchanged.

### 2.3 Production status (as of 2026-06-12)
- Deployed to Cloud Run (`jokesforbackend`, `us-east1`). Migration applied to Neon.
- Resend wired; `jokesfor.net` domain verified; a real verification email was delivered through the production path in testing.
- **`EMAIL_VERIFICATION_REQUIRED` is OFF** — production signup still logs users straight in (legacy behavior). Nothing real users do has changed yet.

---

## 3. The core idea & why it matters

**Product reasoning:** an account that hasn't proven control of its email is a liability — spam signups, unusable password resets, and a compliance gap (we can't responsibly gate mature content or honor data-rights requests for unverified identities). Verifying the email at the door fixes all three.

**Why a code, not a magic link:** codes work when signup and email are on different devices, aren't auto-consumed by corporate link-scanners, and pair naturally with a clean numeric-entry UI. (We deliberately chose this; you're building a code-entry screen, not a link handler.)

**The experience we're after:** verification should feel like a *fast, reassuring* step, not a wall. The user just signed up — they're motivated. Get them a code instantly, make entry effortless (autofocus, paste-the-whole-code, auto-submit), and make "didn't get it?" obviously recoverable.

---

## 4. The most important rule: dual-mode, and how to detect it

`EMAIL_VERIFICATION_REQUIRED` flips behavior. **You must handle both, because the flag turns on after your code ships** — and ideally your code is robust enough that the flip needs no FE redeploy.

The elegant part: **you don't need to know the flag's value — the registration response tells you which mode you're in.**

| Mode | `POST /registration/` returns | What it means |
|---|---|---|
| **Legacy** (flag off, today) | `201` with `{ access, refresh, user }` **+ auth cookies set** | User is logged in immediately. Proceed exactly as you do now. |
| **Gated** (flag on, future) | `201` with `{ detail, email }` and **no tokens, no `user`, no auth cookie** | User must verify. Route them to the code-entry screen. |

**Suggested detection logic** (you decide the exact shape):
> After a successful `201` from registration, branch on the body: if it contains `access`/`user` → treat as logged-in (legacy). If it contains `email` and no tokens → enter the verification flow. A simple, robust check is "did we get tokens/cookies or not."

This means: **build the verification screen and the branch now.** While the flag is off, your branch simply never triggers (registration keeps returning tokens). The day we flip it, your UI is already there. No coordinated redeploy, no breakage window.

---

## 5. User journeys

### 5.1 Happy path (gated mode)
```
Signup form (email + password)
   │  POST /registration/
   ▼
201 { detail, email }  (no session)
   │  navigate to code-entry, carry the email
   ▼
Code-entry screen  "We sent a 6-digit code to a@b.com"
   │  user types 135790
   │  POST /verify-email/ { email, code }
   ▼
200 { user }  + auth cookies set
   │  user is now authenticated (same as a fresh login)
   ▼
Continue into the app (onboarding / home), exactly as a normal logged-in user
```

### 5.2 Didn't get the code
```
Code-entry screen → "Didn't get it? Resend"
   │  POST /resend-verification/ { email }
   ▼
200 (always)  → toast "A new code is on its way"
   │  (a new code invalidates the previous one)
   │  4th resend within 15 min → 429 → "Please wait a bit before trying again"
```

### 5.3 Wrong / expired code
```
Enter wrong code → 400 { code: ["Incorrect code."] } → inline error, let them retry
5 wrong tries → 429 { detail: "Too many attempts. Request a new code." } → prompt Resend
Code older than 10 min → 400 { code: ["This code has expired. Request a new one."] } → prompt Resend
```

### 5.4 User leaves and comes back
The account exists but is inactive; the code may have expired. The cleanest re-entry: let them **return to the code-entry screen** (e.g., from a "verify your email" state) and hit **Resend** to get a fresh code. (There is no "login" path for an unverified user — login is refused until active.)

### 5.5 Google sign-in
Unchanged. No code screen. They come back from Google already logged in. §11.

---

## 6. Screens (conceptual — you design the real thing)

### 6.1 Code-entry screen (the one new screen)
The heart of this feature. A focused, single-purpose screen.

```
┌───────────────────────────────────────────────┐
│  ← back                                        │
│                                                │
│  Check your email                              │
│  We sent a 6-digit code to                     │
│  a@b.com                                        │
│                                                │
│     ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐ ┌─┐                     │
│     │1│ │3│ │5│ │7│ │9│ │0│   ← code inputs     │
│     └─┘ └─┘ └─┘ └─┘ └─┘ └─┘                     │
│                                                │
│  [ inline error slot ]                         │
│                                                │
│            [  Verify  ]                         │
│                                                │
│  Didn't get it?  Resend code   (00:42)         │
│  Wrong email?  Go back                          │
└───────────────────────────────────────────────┘
```

**UX qualities that matter (suggestions, not mandates):**
- **Autofocus** the first input on mount.
- **Whole-code paste**: pasting `135790` should distribute across the boxes. (A single `<input inputmode="numeric" maxlength=6>` is simpler and also fine — your call; six boxes is just nicer.)
- **Auto-submit** when the 6th digit is entered (with a manual Verify button as fallback / for a11y).
- **`autocomplete="one-time-code"` + `inputmode="numeric"`** so mobile keyboards show digits and iOS offers the code from the Messages/Mail. (Email OTP autofill is weaker than SMS, but the attributes still help.)
- **Resend with a cooldown timer** reflecting the 15-min/3-per window — disable Resend for, say, 30–60s after each send and show a countdown so users don't spam it into a 429.
- **Show the email** they're verifying, with a "wrong email? go back" escape.

### 6.2 Signup screen
Mostly unchanged. The only difference: after `POST /registration/`, your **success handler branches** (§4). In legacy mode it logs in as today; in gated mode it navigates to the code-entry screen carrying the `email`.

### 6.3 Where verification sits in routing
Two reasonable options (you decide):
- A **dedicated route** (e.g. `/verify-email?email=…` or carry the email in nav state). Clean, linkable, survives refresh if you keep the email in the URL/query.
- A **step within the signup flow** (a wizard step / modal). Smoother, but loses the state on hard refresh unless you persist the pending email.

A pragmatic middle ground: dedicated route + the pending email in a query param or short-lived store, so a refresh on the code screen still knows whose code to verify.

---

## 7. API contract (precise — this is the integration surface)

Base path: `/api/v1/auth/`. Production host is the existing configured API base (`https://jokesforbackend-q6w4ck2t2q-ue.a.run.app`). All three endpoints are **public** (no auth header needed) and participate in the **same cookie/CORS setup** you already use for login (credentialed requests, `withCredentials`).

### 7.1 `POST /api/v1/auth/registration/`
Your existing signup call. Body unchanged: `{ email, password1, password2 }`.

**Legacy mode (flag off — today):**
```http
201 Created
Set-Cookie: jokes-access-token=…; HttpOnly
Set-Cookie: jokes-refresh-token=…; HttpOnly
{ "access": "…", "refresh": "…", "user": { … } }
```
→ Logged in. Behave exactly as you do now.

**Gated mode (flag on — future):**
```http
201 Created           (no auth cookies)
{ "detail": "Verification code sent to your email.", "email": "a@b.com" }
```
→ Navigate to code-entry with `email`.

**Errors (both modes):** existing registration validation still applies — e.g. `400 { "email": ["A user is already registered with this e-mail address."] }`, password mismatch, etc. Handle as you do today.

### 7.2 `POST /api/v1/auth/verify-email/`
**Request:**
```json
{ "email": "a@b.com", "code": "135790" }
```
- `code` must match `^\d{6}$` (exactly 6 digits). If it doesn't, you get a **serializer 400** like `{ "code": ["This value does not match the required pattern."] }` *before* any business logic. **Validate format client-side** to avoid that.

**Success:**
```http
200 OK
Set-Cookie: jokes-access-token=…; HttpOnly
Set-Cookie: jokes-refresh-token=…; HttpOnly
{ "user": { "id": 12, "email": "a@b.com" } }
```
→ The user is now authenticated, identically to a fresh login. **Reuse your post-login flow** (hydrate auth state, redirect to onboarding/home). The cookies are set by the server; your existing credentialed-axios setup will carry them onward.

**Error responses:**

| HTTP | Body | Meaning | Suggested UX |
|---|---|---|---|
| 400 | `{ "code": ["Incorrect code."] }` | wrong code **or unknown email** (uniform on purpose) | inline error under the code field; let them retry |
| 400 | `{ "code": ["This code has expired. Request a new one."] }` | code older than 10 min | inline error + nudge to Resend |
| 400 | `{ "code": ["No active code. Request a new one."] }` | no live code (e.g. already consumed) | nudge to Resend |
| 400 | `{ "detail": "This email is already verified. Please log in." }` | user already active | route them to login |
| 429 | `{ "detail": "Too many attempts. Request a new code." }` | 5 wrong attempts used up | disable entry, prompt Resend |
| 400 | `{ "code": ["…pattern…"] }` | code wasn't 6 digits | shouldn't happen if you validate client-side |

**Note the two error shapes:** field errors arrive as `{ "code": [ "…" ] }`; flow errors arrive as `{ "detail": "…" }`. Your handler should check both. The 429 specifically signals "stop retrying, resend."

### 7.3 `POST /api/v1/auth/resend-verification/`
**Request:**
```json
{ "email": "a@b.com" }
```

**Response (always, by design):**
```http
200 OK
{ "detail": "If that email needs verification, a new code has been sent." }
```
This is **uniform regardless of whether the email exists / is already verified** — anti-enumeration (§12). Treat any 200 as "ok, a code may be coming." A new code invalidates any previous one.

**Throttle:**
```http
429 Too Many Requests          (4th request within 15 minutes, per email)
```
→ "You've requested several codes. Please wait a few minutes." A **client-side cooldown** on the Resend button keeps users from hitting this.

### 7.4 Cookies / auth — nothing new to learn
Verification's success path sets the **same HttpOnly cookies** as login (`jokes-access-token`, `jokes-refresh-token`). Your existing axios instance (credentialed, with the refresh interceptor) handles everything from there. There is **no token in a header to capture** — it's cookie-based, same as today. Just make sure the verify/resend calls go through the same credentialed client so cookies are set/sent.

---

## 8. State & data flow (suggested approach — your call)

You already use TanStack Query + Zustand + a credentialed axios client. Natural fits:

- **Mutations** for the three actions: `useRegister` (you have this), `useVerifyEmail`, `useResendVerification`. Each is a `useMutation` wrapping the respective POST.
- **The pending email** (whose code we're verifying) is short-lived UI state. Options: a query param on the verify route, nav state, or a tiny Zustand slice (`pendingVerificationEmail`). A query param is the most refresh-resilient.
- **On verify success**, reuse your existing "user just authenticated" path — the same thing your login mutation does on success (invalidate/refetch the session query, set auth state, redirect). Don't build a parallel auth path; the cookies are already set, so it's just "we're logged in now."
- **The resend cooldown** is local component state (a countdown). Persist the "last sent at" if you want the cooldown to survive a remount.

You do **not** need a new store or any global verification state machine. It's one screen + three mutations + a pending-email value.

---

## 9. Validation & error handling

- **Client-side, validate the code is exactly 6 digits** before calling verify — it keeps the UX snappy and avoids the serializer pattern-mismatch 400.
- **Two server error shapes** (`{ code: [...] }` field errors and `{ detail: "..." }` flow errors) — your error parser should read whichever is present and surface a friendly message. Don't show raw JSON.
- **429 means "stop and resend"**, not "retry harder." On verify-429, disable the inputs and steer to Resend. On resend-429, start/extend the cooldown.
- **Network / 5xx**: a generic "something went wrong, try again" with a retry affordance. The verify call is idempotent enough to retry safely (a correct code still verifies; a consumed one returns a clear error).
- **Registration 502** (rare): if registration returns `502` with `{ detail, email }`, the account was created but the *email send* failed (provider hiccup). Treat it like gated mode but lead with "we couldn't send your code — tap Resend": route to code-entry and surface Resend prominently. The account is recoverable via resend.

---

## 10. The resend UX (worth getting right)

This is where users get frustrated, so design it deliberately:
- **Cooldown timer** after each send (e.g. 45–60s) with a visible countdown; the button is disabled during it. This both improves UX and keeps users under the 3-per-15-min server limit.
- **Make the limit legible**: if they do hit 429, say *why* ("a few codes already sent — give it a couple of minutes") rather than a generic error.
- **Confirm sends** with a brief toast, but remember the response is intentionally vague ("if that email needs verification…") — don't claim "sent to a@b.com!" with certainty in copy that could leak existence. In the verification flow you *do* know the email (they just registered it), so a confident "new code sent" is fine here; just keep the *resend endpoint's* generic contract in mind if you reuse it elsewhere.

---

## 11. Google OAuth — explicitly unchanged

Social sign-in is **exempt** from verification (Google already verified the email). The `GoogleLogin` flow is untouched: the user returns from Google **already authenticated**, no code screen, no interruption. **Do not add a verification step to the Google path.** If you have any shared "post-auth" routing, just make sure the Google branch skips the code screen.

(Reminder from earlier this session: the Google callback exchange should fire **once** per code — keep the existing StrictMode-safe ref guard on the callback handler.)

---

## 12. Security constraints the FE must respect

The backend is deliberately **anti-enumeration**, and your copy/UX must not undo that:
- `verify-email` returns the **same** `400 { code: ["Incorrect code."] }` for a wrong code *and* an unknown email. **Don't write UI that distinguishes them** ("no such account" vs "wrong code") — that would leak which emails exist.
- `resend-verification` **always** returns 200 with a generic message. Don't render "we sent it to a@b.com" based on a presumed account existence in any context where the email wasn't just self-entered by the same user.
- Within the *registration → verify* flow this is mostly moot (the user typed their own email), but keep it in mind if you reuse the resend endpoint from, e.g., a standalone "resend code" entry point.
- **Never log codes** or full emails to analytics/telemetry. Treat the code like a password.

---

## 13. Accessibility

- The code input must be **keyboard-operable** and screen-reader-labeled. If you use six separate boxes, manage focus on type/paste/backspace and expose a single logical label (e.g. an `aria-label="Verification code"` group), or offer a single `<input>` as the accessible primary.
- **`autocomplete="one-time-code"`, `inputmode="numeric"`** on the field(s).
- Announce errors via `aria-live` so a screen reader hears "Incorrect code" without losing focus.
- The Resend cooldown state should be conveyed as text, not color alone.
- Respect `prefers-reduced-motion` for any auto-submit / transition animations.

---

## 14. Analytics (suggested events)

Enough to see the funnel and the friction (never include the code or full email):
- `verify_screen_viewed`
- `verify_submitted` / `verify_succeeded` / `verify_failed { reason: incorrect|expired|too_many|already_verified }`
- `resend_clicked` / `resend_throttled`
- `verify_abandoned` (left the screen without verifying)

These answer: how many who register actually verify, where they drop, and whether resend/throttle friction is hurting conversion.

---

## 15. Acceptance criteria

Done when:
- [ ] In **legacy mode** (flag off), signup behaves exactly as before — your branch never shows the code screen. (Verify against production today.)
- [ ] In **gated mode** (flag on), signup routes to the code screen carrying the email, and entering the correct code logs the user in (cookies set, normal authenticated state).
- [ ] Mode is detected from the **registration response**, not a hardcoded assumption — no FE redeploy needed when the flag flips.
- [ ] All `verify-email` error states (incorrect / expired / no-active / already-verified / too-many) render friendly, distinct-where-allowed messages.
- [ ] Resend works, with a cooldown that keeps users under the throttle; 429s are handled gracefully.
- [ ] Google sign-in shows **no** code screen.
- [ ] Code entry is mobile-friendly (numeric keyboard, paste-whole-code, one-time-code autocomplete) and accessible.
- [ ] No code or full email is sent to logs/analytics.
- [ ] Anti-enumeration copy respected (no "account doesn't exist" leaks).

---

## 16. Rollout coordination (how this actually goes live)

The flag is the contract between our two sides. Sequence:
1. **You build & ship** the code-entry screen + the registration-response branch (works in legacy mode — invisible to users).
2. **We flip `EMAIL_VERIFICATION_REQUIRED=true`** on the backend (one Cloud Run env change, no redeploy of code).
3. From that moment, new signups go through verification. Because your FE detects mode from the response, the transition is seamless and reversible (we can flip it back instantly if anything's off).

**Important:** do **not** assume the flag is on when building/testing. Today it's **off in production** — so a real signup against prod right now returns tokens (legacy). To exercise the gated path before we flip it, coordinate with us: we can flip it briefly in a non-peak window, or point you at a staging configuration with the flag on. Don't flip it yourself for a wide audience — it changes real signups.

---

## 17. Decisions left to you (the FE agent)

These are genuinely yours to make — pick what fits the app:
1. **Single input vs six boxes** for the code. (Six is nicer; one is simpler and very accessible. Either is acceptable.)
2. **Dedicated route vs wizard step** for verification. (Recommend a route + email in query for refresh-resilience.)
3. **Auto-submit on 6th digit** or require a Verify tap. (Auto-submit + a manual fallback is a good default.)
4. **Cooldown length** for Resend (30–60s) and whether it persists across remounts.
5. **Where "pending email" lives** (query param / nav state / Zustand slice).
6. **Copy/tone** for each error state, within the anti-enumeration constraints of §12.

When in doubt, optimize for: *fast to verify, obvious how to recover, never leaks account existence.*

---

## 18. Quick reference card

**Endpoints** (all public, credentialed, under `/api/v1/auth/`):
- `POST registration/` `{email,password1,password2}` → legacy: `201 {access,refresh,user}`+cookies · gated: `201 {detail,email}` no session
- `POST verify-email/` `{email,code}` → `200 {user}`+cookies · errors below
- `POST resend-verification/` `{email}` → always `200 {detail}` · `429` if >3/15min

**verify-email errors:**
- `400 {code:["Incorrect code."]}` — wrong code or unknown email (uniform)
- `400 {code:["This code has expired. Request a new one."]}`
- `400 {code:["No active code. Request a new one."]}`
- `400 {detail:"This email is already verified. Please log in."}`
- `429 {detail:"Too many attempts. Request a new code."}`

**Code:** exactly 6 digits (`^\d{6}$`), 10-min expiry, 5 attempts, then dead.
**Resend:** 3 per 15 min per email → else 429. New code invalidates old.
**Auth:** success sets HttpOnly cookies (`jokes-access-token` / `jokes-refresh-token`) — same as login; reuse your post-login path.
**Mode detection:** registration response has tokens → logged in; has `email` + no tokens → verify.
**Google OAuth:** no code step, unchanged.
**Today in prod:** flag OFF (legacy). Build the screen now; we flip later.

---

*End. Backend built & deployed this session (2026-06-12). Questions about the contract → check `notifications/views.py` / `notifications/serializers.py`, or ask the backend side.*
