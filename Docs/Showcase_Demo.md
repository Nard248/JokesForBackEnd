# Showcase demo — Creator Studio + communities (local only)

Synthetic, local data for presenting the creator tools and self-forming
communities. Never run against Neon: the seed refuses anything but
`DEBUG=True` + loopback PostgreSQL + filesystem storage.

## Start

```sh
# 1. Backend (port 8020) — empty DATABASE_URL is load-bearing (.env points at prod)
cd ~/PycharmProjects/JokesForProject
export DATABASE_URL='' DEBUG=True DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
export DB_NAME=jokesfor_release DB_USER=postgres DB_PASSWORD=<local> DB_HOST=localhost DB_PORT=5432
export FRONTEND_URL=http://localhost:5180 CORS_ALLOWED_ORIGINS=http://localhost:5180 CSRF_TRUSTED_ORIGINS=http://localhost:5180
export EMAIL_VERIFICATION_REQUIRED=false CREATOR_CHECKOUT_ENABLED=false
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_showcase          # rebuilds showcase rows; repeatable
.venv/bin/python manage.py runserver 127.0.0.1:8020

# 2. Web (port 5180)
cd ~/WebstormProjects/jokes-for-frontend
VITE_API_URL=http://localhost:8020/api/v1 VITE_USE_MOCKS=false VITE_USE_REAL_PREFERENCES=true \
VITE_USE_REAL_CREATE=true npm run dev -- --strictPort --port 5180
```

Open http://localhost:5180. Password for every account: `Showcase-2026!`

| Account | Role | Show |
|---|---|---|
| `maya@showcase.invalid` | Maya Okafor — Creator Pro comedian | Studio: Overview, Content workbench + CSV, Insights (28 days of consenting audience), **Communities** (reach + opportunities), Library (set list, series, notes, pending metadata request) |
| `theo@showcase.invalid` | Theo Lindqvist — free creator | Which Studio tools are included vs Creator Pro (gates) |
| `sam@showcase.invalid` | Sam Rivera — reader | `/communities`: member of Puns (joined); **Space is forming and Sam is one laugh away** |

## The scripted moment

As Sam open `/communities/space`: *Forming · You've enjoyed 1 so far*. Laugh (😂)
at "Why did the star get detention?" in *Trending in Space* → Space turns
**Active** (status is live), Sam gets the YOU badge, and the button becomes *Leave
community*. The member count does not jump with it: person-counts come from a
once-a-day snapshot with day-stable noise (`Docs/API/Communities.md`, *Privacy*),
so Space keeps the morning's figure — usually "fewer than 5" — until the next UTC
day. Re-run `seed_showcase` to reset (it also drops the day's snapshot).

The flip also writes `community_formed` inbox notifications (`GET
/api/v1/notifications/`): Sam gets `role: "member"`, Maya and Priya (both have
Space jokes) get `role: "creator"`, and so do the four other counted Space
readers. They are written by the first communities request after the laugh;
reloading never sends them twice. `seed_showcase` re-baselines formation
tracking, so every reseed can replay the moment.

Every showcase account is backdated 150 days and the scripted readers enjoy 3+
distinct jokes, so they are *established* and count; a brand-new account you
sign up yourself is not counted for a week (`viewer.counted: false`).

Other states: Weather is **cooling** (its fans' signals are two weeks old);
School/Science/Dating are small but active; 15% of the audience does not share
analytics and is never counted.

## Gotcha

Re-running `seed_showcase` recreates the accounts. A browser still holding the
previous JWT cookies gets 401 on login and 500 on token refresh — sign out first
or use a private window. (The 500 is a pre-existing backend bug: a refresh token
for a deleted user raises `User.DoesNotExist` instead of returning 401.)
