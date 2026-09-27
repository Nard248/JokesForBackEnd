#!/usr/bin/env bash
# An isolated local demo. Does not source .env or import production settings.
set -euo pipefail

COMMUNITIES_BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMUNITIES_RUNTIME_DIR=/private/tmp/jokesfor-communities
COMMUNITIES_PYTHON="${COMMUNITIES_PYTHON:-$COMMUNITIES_BACKEND_DIR/.venv/bin/python}"
COMMUNITIES_PGDATA="$COMMUNITIES_RUNTIME_DIR/pgdata"
COMMUNITIES_SOCKET="$COMMUNITIES_RUNTIME_DIR/pgsocket"
COMMUNITIES_ACTION="${1:-serve}"

if [[ "$COMMUNITIES_ACTION" != serve && "$COMMUNITIES_ACTION" != test ]]; then
  echo 'Usage: bash scripts/community-lab.sh [serve|test]' >&2
  exit 2
fi

for executable in initdb pg_ctl psql createdb; do
  command -v "$executable" >/dev/null || { echo "Missing $executable; install PostgreSQL." >&2; exit 1; }
done
[[ -x "$COMMUNITIES_PYTHON" ]] || { echo 'Set COMMUNITIES_PYTHON to a Python environment with the project dependencies.' >&2; exit 1; }

mkdir -p "$COMMUNITIES_SOCKET"
if [[ ! -f "$COMMUNITIES_PGDATA/PG_VERSION" ]]; then
  initdb -D "$COMMUNITIES_PGDATA" -U community_demo -A trust --no-locale --encoding=UTF8
fi
if ! pg_ctl -D "$COMMUNITIES_PGDATA" status >/dev/null 2>&1; then
  pg_ctl -D "$COMMUNITIES_PGDATA" -l "$COMMUNITIES_RUNTIME_DIR/postgres.log" \
    -o "-h 127.0.0.1 -p 55437 -k $COMMUNITIES_SOCKET" start
fi
if [[ "$(psql -h "$COMMUNITIES_SOCKET" -p 55437 -U community_demo -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = 'community_lab'")" != 1 ]]; then
  createdb -h "$COMMUNITIES_SOCKET" -p 55437 -U community_demo community_lab
fi

cd "$COMMUNITIES_BACKEND_DIR"
export DATABASE_URL=''
export DJANGO_SETTINGS_MODULE=community_lab.settings
if [[ "$COMMUNITIES_ACTION" == test ]]; then
  exec "$COMMUNITIES_PYTHON" -m django test community_lab --keepdb --noinput
fi
"$COMMUNITIES_PYTHON" -m django migrate --noinput
"$COMMUNITIES_PYTHON" -m django seed_community_lab
exec "$COMMUNITIES_PYTHON" -m django runserver 127.0.0.1:8017 --noreload
