# T3 — Live API Contract Tests

**Run:** 2026-08-25 · **Tier:** T3 (live API contract) · **Target:** LOCAL full stack only
(backend `http://localhost:8010`, Django runserver, local Postgres `jokesfor`, `DEBUG=True`,
console email, **blank Stripe keys**, no GCS, no Vision). Production was never contacted.

**Method.** Every assertion was written *after* reading the implementing source
(`jokes/submission_rules.py`, `jokes/serializers.py`, `jokes/views.py`, `jokes/media_processing.py`,
`jokes/media_probe.py`, `jokes/media_screening.py`, `jokes/admin.py`, `jokes/moderation.py`,
`jokes/paywall.py`, `jokes/serving.py`, `jokes/sitemap.py`, `jokes/templates/jokes/share*.html`,
`billing/views.py`, `billing/stripe_gateway.py`, `audit/models.py`, `audit/signals.py`).
Scripts live in
`/private/tmp/claude-501/.../scratchpad/t3/` (`t3_m.py`, `t3_s.py`, `t3_b.py`, `t3_o.py`,
`common.py` on top of the provided `harness.py`); raw per-area results are in `results/*.json`.
No application source file was modified. Test users `t3.*@e2e.dev` and a handful of test
jokes/media rows were created in the local DB.

## Result summary

| Verdict | Count |
| --- | --- |
| PASS | 24 |
| CONFIRMED-DEFECT | 3 |
| CONFIRMED-QUIRK | 2 |
| genuine FAIL (app behaved unexpectedly and the expectation was right) | 0 |
| **Total tests** | **29** |

Two intermediate failures during the run were **my** bad assumptions, not app bugs, and were
corrected before the final run: (a) T3-S03 asserted the wrong duplicate-appeal wording — the app's
`"An appeal is already pending for this joke."` is correct; (b) T3-S02's search assertion collided
with an identically-worded joke left by an earlier run, fixed with a per-run token.

## Test matrix

