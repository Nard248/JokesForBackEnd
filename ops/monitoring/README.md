# Monitoring & performance ops

Versioned, owner-applied observability + performance config for the backend Cloud Run
service (`jokesforbackend`, project `jokesfor`, region `us-east1`). Everything here is a
**prod-config change** — review, then apply the `gcloud` command yourself (or ask me to run
it and I'll surface it for your approval first).

## 1. Real p50/p95/p99 — log-based latency metric

The app already logs `latency_ms` per request keyed by `route` (see
`JokesForProject/observability/middleware.py`). This turns those logs into a per-route
latency histogram — no code change, no new dependency.

```bash
gcloud logging metrics create access_request_latency \
  --project=jokesfor \
  --config-from-file=ops/monitoring/access_latency_metric.yaml
```

Metric type produced: `logging.googleapis.com/user/access_request_latency`.
It starts collecting from creation forward (log-based metrics are not retroactive), so create
it **before** the load test / launch to capture the numbers.

## 2. Latency dashboard

Per-route p50/p95/p99, request rate by response-code class, and instance count (cold-start
signal) in one board.

```bash
gcloud monitoring dashboards create \
  --project=jokesfor \
  --config-from-file=ops/monitoring/dashboard-latency.json
```

(Depends on metric #1 existing first for the latency tiles to populate.)

## 3. Kill cold starts — keep one instance warm

The service currently runs `min-instances=0` (scales to zero). At near-zero traffic almost
every real request is a cold start (~10–14s: container boot + Neon connect), which is what
inflates the raw p99 today. One always-warm instance turns the first-hit into ~0.5s.

```bash
gcloud run services update jokesforbackend \
  --project=jokesfor --region=us-east1 \
  --min-instances=1
```

**Cost:** one always-on instance at 1 vCPU / 1 GiB ≈ **$15–40/month** depending on the CPU
allocation mode (request-based vs always-allocated). Cheap insurance for launch; revert with
`--min-instances=0` anytime. Consider raising `--max-instances` (currently 3) before a real
traffic spike, especially given inline video encode ties up a worker for ~20s.

## 4. Getting a true p95/p99 (the honest gap)

These metrics measure real traffic. Pre-launch there's ~none (≈233 req/week = health checks),
so the dashboard won't show a meaningful tail until either (a) real users arrive, or (b) you
run a load test. A load test against the media-upload path is the way to get true encode-path
p95/p99 before opening the doors — track that as a pre-launch task.
