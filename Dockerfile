# syntax=docker/dockerfile:1.7
# Two-stage build: compile wheels in `builder`, copy site-packages into a
# minimal `runtime` stage so we ship build toolchains nowhere near production.

# ---------- builder ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY requirements.txt .
# --prefix lets us COPY the entire tree into the runtime image's /usr/local
# (preserving site-packages layout) without needing pip in the runtime stage.
RUN pip install --prefix=/install/deps -r requirements.txt

# ---------- runtime ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DJANGO_SETTINGS_MODULE=JokesForProject.settings

# Runtime system libs:
#   libcairo2 / libpango* — required by cairosvg (share-card rendering)
#   libpq5                — psycopg2 runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder /install/deps /usr/local

WORKDIR /app
COPY --chown=app:app . .

# Build-time collectstatic so the static layer is cached and served by WhiteNoise.
# SECRET_KEY/DEBUG values here are throwaway — nothing sensitive is read.
RUN SECRET_KEY=build-only-key DEBUG=False ALLOWED_HOSTS=* \
    python manage.py collectstatic --noinput --clear

USER app
EXPOSE 8080

# Cloud Run sends $PORT; gunicorn binds to it. Keep workers low — Cloud Run
# scales horizontally rather than vertically for serverless workloads.
CMD exec gunicorn JokesForProject.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers 2 \
    --threads 4 \
    --worker-class gthread \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
