# Creator Tips Wave — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps.

**Goal:** Ship `Docs/superpowers/specs/2026-07-24-creator-tips-design.md` — one-off creator tips on the existing env-gated Stripe rails, dormant until live-mode.

**Architecture:** `Tip` model + a payment-mode Checkout Session mirroring `CheckoutSessionView`; webhook extension; fixed-tier amounts; dormant behind STRIPE_SECRET_KEY.

## Global Constraints
- Django runner NEVER pytest; new tests `billing/tests/test_tips.py`; mock the Stripe gateway the way existing billing tests do (read billing/tests for the pattern — likely patches billing.stripe_gateway functions).
- Commits plain no footers. Fixed tiers verbatim: 100/300/500/1000 cents. No arbitrary amounts, no self-tipping.
- Dormant: is_enabled() False → 503 billing_unavailable everywhere, same as subscriptions. Tests run against test-mode/mocked gateway.
- Payout scoping honest: v1 collects to platform, no Connect, UI says "received" not "withdraw".

---

### Task 1: Tip model + checkout endpoint
**Files:** billing/models.py (Tip per spec §Model) + migration; billing/stripe_gateway.py (`create_tip_checkout_session(sender, creator, joke, amount_cents)` — payment mode, tip metadata: {type:'tip', tip_id, creator_id, joke_id}); billing/views.py (`TipCheckoutView` POST /tips/checkout/ — IsAuthenticated, validate amount in allowlist / creator exists+is-creator / not self; create Tip(pending) + session; dormant→503); billing/urls.py; throttle.
**Tests (TDD):** amount not in tier → 400; self-tip → 400; non-creator target → 400; dormant → 503; happy → session URL + Tip(pending) row + metadata; mocked gateway.
Commit: `tips: Tip model and payment-mode checkout endpoint`.

### Task 2: webhook completion + summaries
**Files:** billing/webhooks.py (extend checkout.session.completed handler: tip-metadata marker → mark Tip succeeded, stamp payment_intent+completed_at, idempotent on session id — mirror the subscription dedup); billing/views.py (`GET /creators/{id}/tips/summary/` public count+total of succeeded; `GET /users/me/tips/` sent history); urls.
**Tests (TDD):** webhook completes a tip idempotently (double event → one success); non-tip session unaffected (regression on subscription path); summary counts only succeeded; my-tips isolation.
Commit: `tips: webhook completion, creator tip summary, sent-tips history`.

### Task 3 (frontend, branch feat/tips): tip button + tier modal
**Files (FE repo):** tips API/hooks; TipButton + tier-picker modal on creator profile (+ optional joke detail with joke_id); checkout redirect reusing the subscription redirect pattern; creator-profile tips-received summary (hidden when zero); dormant-aware (billing 503 → button hidden/"coming soon", never broken checkout); success/cancel return handling.
**Tests (vitest):** tier modal → checkout redirect; dormant → hidden; summary renders/hides; graceful-absent.
Commit: `tips: creator tip button, tier modal, received summary`.

### Task 4: regression + wrap
Backend full suite + FE suite/build green.

---

## Deployment notes
- Ships dormant (STRIPE_SECRET_KEY test/unset). Activates with subscriptions when owner completes live-mode onboarding + sets the live key — ZERO code change. No new infra.
- Webhook: the tips path rides the EXISTING Stripe webhook endpoint — no new Stripe webhook config needed (same signed endpoint, new metadata branch).
