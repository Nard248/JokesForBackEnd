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
**Active · 5 members**, Sam gets the YOU badge, and the button becomes *Leave
community*. Re-run `seed_showcase` to reset.

Other states: Weather is **cooling** (its fans' signals are two weeks old);
School/Science/Dating are small but active; 15% of the audience does not share
analytics and is never counted.
