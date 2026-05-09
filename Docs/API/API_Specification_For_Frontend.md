# Jokes For — Backend API Specification (Frontend Requirements)

> **Purpose:** This document describes every endpoint the frontend currently needs to function. Each endpoint is mapped to the specific page(s) and UI operations that depend on it.
>
> **Base URL:** `/api/v1`
>
> **Auth:** All endpoints except `POST /auth/login/`, `POST /auth/registration/`, and public `GET /jokes/` require a valid `Authorization: Bearer <access_token>` header.
>
> **Pagination Convention:** All list endpoints return `{ count, next, previous, results[] }`. Default page size: 10.

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Jokes — Search & Browse](#2-jokes--search--browse)
3. [Daily Jokes](#3-daily-jokes)
4. [Collections](#4-collections)
5. [Saved Jokes (Library)](#5-saved-jokes-library)
6. [Favorites](#6-favorites)
7. [Trending & Discovery](#7-trending--discovery)
8. [Joke Submission & Drafts](#8-joke-submission--drafts)
9. [User Profile & Activity](#9-user-profile--activity)
10. [User Settings & Preferences](#10-user-settings--preferences)
11. [Type Reference](#11-type-reference)

---

## 1. Authentication

### `POST /auth/login/`

| | |
|---|---|
| **Page** | Login Page (`/login`) |
| **Purpose** | Authenticate user with email/password and return JWT tokens |

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "secret123"
}
```

**Success Response (200):**
```json
{
  "access": "eyJ...",
  "refresh": "eyJ...",
  "user": {
    "pk": 1,
    "email": "user@example.com",
    "first_name": "Laugh",
    "last_name": "Master"
  }
}
```

**Error Response (400):**
```json
{
  "non_field_errors": ["Unable to log in with provided credentials."],
  "email": ["This field may not be blank."],
  "password": ["This field may not be blank."]
}
```

**Notes:**
- The `refresh` token may be returned as an httpOnly cookie instead of in the body.
- The `user` object in the response is optional — if absent, the frontend calls `GET /auth/user/` separately.

---

### `POST /auth/registration/`

| | |
|---|---|
| **Page** | Register Page (`/register`) |
| **Purpose** | Create a new user account |

**Request Body:**
```json
{
  "email": "user@example.com",
  "password1": "securepass123",
  "password2": "securepass123"
}
```

**Success Response (201):**
```json
{
  "access": "eyJ...",
  "refresh": "eyJ...",
  "user": {
    "pk": 1,
    "email": "user@example.com",
    "first_name": "",
    "last_name": ""
  }
}
```

**Error Response (400):**
```json
{
  "email": ["A user is already registered with this e-mail address."],
  "password1": ["This password is too common."],
  "password2": ["The two password fields didn't match."]
}
```

---

### `POST /auth/logout/`

| | |
|---|---|
| **Page** | Settings Page (`/settings`) — Danger Zone section |
| **Purpose** | Invalidate current session/tokens |

**Request:** Empty body. Authorization header required.

**Success Response (200):**
```json
{ "detail": "Successfully logged out." }
```

---

### `GET /auth/user/`

| | |
|---|---|
| **Page** | App-wide (called on app initialization, used by Header, Sidebar) |
| **Purpose** | Get the currently authenticated user's basic info |

**Success Response (200):**
```json
{
  "pk": 1,
  "email": "user@example.com",
  "first_name": "Laugh",
  "last_name": "Master"
}
```

---

### `POST /auth/token/refresh/`

| | |
|---|---|
| **Page** | App-wide (Axios interceptor, automatic) |
| **Purpose** | Refresh an expired access token using the refresh token |

**Request Body:**
```json
{ "refresh": "eyJ..." }
```
Or empty body if refresh token is in httpOnly cookie.

**Success Response (200):**
```json
{ "access": "eyJ..." }
```

---

## 2. Jokes — Search & Browse

### `GET /jokes/`

| | |
|---|---|
| **Pages** | Search Page (`/search`), Home Page (`/` — for "Fresh Arrivals" and "Load More") |
| **Purpose** | Search and filter jokes. This is the core discovery endpoint powering the search experience. |

**Query Parameters:**

| Param | Type | Description | Example |
|-------|------|-------------|---------|
| `q` | string | Free-text search query. Should match joke text, setup, punchline, AND tag/tone names. | `?q=office` |
| `tones` | string | Filter by humor tone slug (comma-separated for multiple) | `?tones=dad_joke,punny` |
| `age_rating` | string | Filter by age rating slug | `?age_rating=kid_safe` |
| `joke_format` | string | Filter by format slug | `?joke_format=one_liner` |
| `context_tags` | string | Filter by context/situation slug | `?context_tags=office` |
| `culture_tags` | string | Filter by culture tag slug | `?culture_tags=american` |
| `language` | string | Filter by language code | `?language=en` |
| `ordering` | string | Sort order | `?ordering=-created_at` or `?ordering=-popularity` |
| `page` | int | Pagination page number (default: 1) | `?page=2` |

**Success Response (200):**
```json
{
  "count": 42,
  "next": "/api/v1/jokes/?q=office&page=2",
  "previous": null,
  "results": [
    {
      "id": 5,
      "text": "I told my boss that three companies were after me...",
      "setup": "I told my boss that three companies were after me and I needed a raise.",
      "punchline": "He asked which ones. I said: \"The electric company, the gas company, and the water company.\"",
      "format": { "id": 2, "name": "Short Story", "slug": "short_story" },
      "age_rating": { "id": 2, "name": "Family Friendly", "slug": "family_friendly", "min_age": 0 },
      "tones": [
        { "id": 3, "name": "Sarcastic", "slug": "sarcastic" }
      ],
      "context_tags": [
        { "id": 7, "name": "Work", "slug": "work" },
        { "id": 8, "name": "Office", "slug": "office" }
      ],
      "culture_tags": [],
      "language": { "id": 1, "name": "English", "code": "en" },
      "source": "community",
      "share_image_url": null,
      "created_at": "2025-10-01T12:00:00Z"
    }
  ]
}
```

**Important:**
- The `q` parameter should perform full-text search across `text`, `setup`, `punchline`, and also match against `tones[].name` and `context_tags[].name`. A user searching "office" expects results tagged with the "Office" context even if the word doesn't appear in the joke text.
- The `ordering` parameter should support at minimum: `-created_at` (newest), `popularity` (by likes/saves), `relevance` (default, when `q` is present).

---

### `GET /jokes/{id}/`

| | |
|---|---|
| **Page** | Potential future joke detail page, also needed for sharing/deep-linking |
| **Purpose** | Get a single joke by ID |

**Success Response (200):** Single `Joke` object (same shape as in search results).

---

### `GET /jokes/random/`

| | |
|---|---|
| **Page** | 404 Page (shows random consolation joke), potential future widget use |
| **Purpose** | Get a random joke |

**Success Response (200):** Single `Joke` object.

---

### `POST /jokes/{id}/rate/`

| | |
|---|---|
| **Page** | Any page with JokeCard (Search, Trending, Favorites, Library, Daily) |
| **Purpose** | Rate a joke up or down (like/dislike). Affects popularity ranking. |

**Request Body:**
```json
{ "rating": 1 }
```
Values: `1` (upvote) or `-1` (downvote).

**Success Response (200):**
```json
{ "rating": 1, "joke_score": 4.5 }
```

---

### `GET /jokes/{id}/my-rating/`

| | |
|---|---|
| **Page** | Any page with JokeCard |
| **Purpose** | Check if the current user already rated a specific joke |

**Success Response (200):**
```json
{ "rating": 1, "joke_score": 4.5 }
```
`rating` is `null` if user hasn't rated.

---

## 3. Daily Jokes

### `GET /daily-jokes/today/`

| | |
|---|---|
| **Pages** | Home Page (`/` — Joke of the Day card), Daily Joke Page (`/daily`) |
| **Purpose** | Get today's daily joke. For authenticated users, this should be personalized based on humor preferences. For anonymous users, return a curated/editorial pick. |

**Success Response (200):**
```json
{
  "joke": { /* full Joke object */ },
  "date": "2025-10-14"
}
```

**Notes:**
- The joke should change once per day.
- The frontend caches this with a 1-hour stale time.
- Personalization should use the user's selected humor types from onboarding preferences.

---

### `GET /daily-jokes/history/`

| | |
|---|---|
| **Page** | Daily Joke Page (`/daily` — "Previous Daily Jokes" grid) |
| **Purpose** | Get the history of past daily jokes for this user |

**Success Response (200):**
```json
{
  "count": 7,
  "next": null,
  "previous": null,
  "results": [
    {
      "joke": { /* full Joke object */ },
      "date": "2025-10-13"
    },
    {
      "joke": { /* full Joke object */ },
      "date": "2025-10-12"
    }
  ]
}
```

**Notes:** Results ordered by date descending (most recent first).

---

## 4. Collections

### `GET /collections/`

| | |
|---|---|
| **Page** | Library Page (`/library` — collections grid and mobile collection list) |
| **Purpose** | List all collections belonging to the authenticated user |

**Success Response (200):**
```json
{
  "count": 7,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Work Icebreakers",
      "is_default": false,
      "joke_count": 42,
      "created_at": "2025-09-01T00:00:00Z"
    }
  ]
}
```

**Notes:**
- Every user should have one collection with `is_default: true` (e.g. "All-Time Classics" or "Saved Jokes").
- `joke_count` is a computed field — number of saved jokes in this collection.

---

### `POST /collections/`

| | |
|---|---|
| **Page** | Library Page (`/library` — "New Collection" button) |
| **Purpose** | Create a new collection |

**Request Body:**
```json
{ "name": "Wedding Toast Gems" }
```

**Success Response (201):**
```json
{
  "id": 8,
  "name": "Wedding Toast Gems",
  "is_default": false,
  "joke_count": 0,
  "created_at": "2025-10-14T12:00:00Z"
}
```

---

### `PATCH /collections/{id}/`

| | |
|---|---|
| **Page** | Library Page (future inline rename) |
| **Purpose** | Rename a collection |

**Request Body:**
```json
{ "name": "New Name" }
```

**Success Response (200):** Updated `Collection` object.

---

### `DELETE /collections/{id}/`

| | |
|---|---|
| **Page** | Library Page (future delete action) |
| **Purpose** | Delete a collection. Saved jokes in it should be moved to the default collection or orphaned. |

**Success Response (204):** No content.

---

### `GET /collections/{id}/jokes/`

| | |
|---|---|
| **Page** | Library Page (future collection detail view — clicking on a collection card) |
| **Purpose** | List all saved jokes within a specific collection |

**Success Response (200):**
```json
{
  "count": 42,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 1,
      "joke": { /* full Joke object */ },
      "collection": 1,
      "note": "Great for Monday standups",
      "saved_at": "2025-10-12T00:00:00Z"
    }
  ]
}
```

---

## 5. Saved Jokes (Library)

### `GET /saved-jokes/`

| | |
|---|---|
| **Page** | Library Page (`/library` — "All Saved Jokes" list) |
| **Purpose** | List all jokes saved by the user across all collections |

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `ordering` | string | `-saved_at` (default, newest first) or `saved_at` |
| `page` | int | Page number |

**Success Response (200):**
```json
{
  "count": 24,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 1,
      "joke": { /* full Joke object */ },
      "collection": 1,
      "note": null,
      "saved_at": "2025-10-12T00:00:00Z"
    }
  ]
}
```

---

### `POST /saved-jokes/`

| | |
|---|---|
| **Page** | Any page with JokeCard — bookmark/save icon action |
| **Purpose** | Save a joke to a collection |

**Request Body:**
```json
{
  "joke": 5,
  "collection": 1,
  "note": "Use this for Monday standup"
}
```
`note` is optional.

**Success Response (201):** Created `SavedJoke` object.

---

### `DELETE /saved-jokes/{id}/`

| | |
|---|---|
| **Page** | Library Page (`/library` — saved joke row delete action) |
| **Purpose** | Remove a saved joke |

**Success Response (204):** No content.

---

### `GET /saved-jokes/search/`

| | |
|---|---|
| **Page** | Library Page (`/library` — "Search my library..." input) |
| **Purpose** | Search within the user's saved jokes |

**Query Parameters:** Same as `GET /jokes/` but scoped to user's saved jokes.

**Success Response (200):** Paginated `SavedJoke` list.

---

## 6. Favorites

> **Architecture Note:** Favorites could be implemented as a special system collection (`is_favorite: true` flag on saved jokes), a separate model, or simply as positive ratings. The frontend needs the following regardless of implementation.

### `GET /favorites/`  *(NEW)*

| | |
|---|---|
| **Page** | Favorites Page (`/favorites`) |
| **Purpose** | List all jokes the user has favorited/hearted, with metadata |

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `tones` | string | Filter by humor tone slug |
| `ordering` | string | `-favorited_at` (default), `favorited_at`, `-popularity` |
| `page` | int | Page number |

**Success Response (200):**
```json
{
  "count": 24,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "joke": { /* full Joke object */ },
      "favorited_at": "2025-10-14T10:30:00Z"
    }
  ]
}
```

---

### `POST /favorites/`  *(NEW)*

| | |
|---|---|
| **Page** | Any page with JokeCard — heart icon action |
| **Purpose** | Add a joke to favorites |

**Request Body:**
```json
{ "joke": 5 }
```

**Success Response (201):**
```json
{ "id": 1, "joke": 5, "favorited_at": "2025-10-14T12:00:00Z" }
```

---

### `DELETE /favorites/{id}/`  *(NEW)*

| | |
|---|---|
| **Page** | Favorites Page — unfavorite action |
| **Purpose** | Remove a joke from favorites |

**Success Response (204):** No content.

---

### `GET /favorites/stats/`  *(NEW)*

| | |
|---|---|
| **Page** | Favorites Page (`/favorites` — stat cards at top) |
| **Purpose** | Summary statistics for the user's favorites |

**Success Response (200):**
```json
{
  "total_count": 24,
  "top_tone": "Dad Jokes",
  "this_week_count": 5
}
```

---

## 7. Trending & Discovery

### `GET /jokes/trending/`  *(NEW)*

| | |
|---|---|
| **Page** | Trending Page (`/trending` — main content), Home Page (`/` — potential "Hot Now" section) |
| **Purpose** | Get jokes ranked by recent popularity (likes, shares, saves in a time window) |

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `period` | string | Time window: `today`, `week` (default), `month` |
| `page` | int | Page number |

**Success Response (200):**
```json
{
  "count": 50,
  "next": "...",
  "previous": null,
  "results": [
    {
      "rank": 1,
      "joke": { /* full Joke object */ },
      "likes": 4200,
      "shares": 1800,
      "comments": 342,
      "trending_since": "2025-10-14T08:00:00Z"
    }
  ]
}
```

---

### `GET /tags/trending/`  *(NEW)*

| | |
|---|---|
| **Page** | Trending Page (`/trending` — trending tags row), Home Page (`/` — "Hot Now" chips) |
| **Purpose** | Get tags/topics ranked by recent engagement growth |

**Success Response (200):**
```json
{
  "results": [
    { "name": "Dad Jokes", "slug": "dad_jokes", "count": 2400, "growth_percent": 42 },
    { "name": "Office Humor", "slug": "office_humor", "count": 1800, "growth_percent": 28 }
  ]
}
```

---

### `GET /tags/rising/`  *(NEW)*

| | |
|---|---|
| **Page** | Trending Page (`/trending` — "Rising Topics" sidebar card) |
| **Purpose** | Get topics with the highest growth rate (emerging trends) |

**Success Response (200):**
```json
{
  "results": [
    { "name": "AI Humor", "slug": "ai_humor", "growth_percent": 120 },
    { "name": "Remote Work", "slug": "remote_work", "growth_percent": 85 }
  ]
}
```

---

### `GET /users/top-jokesters/`  *(NEW)*

| | |
|---|---|
| **Pages** | Trending Page (`/trending` — "Jokesters on Fire"), Home Page (`/` — "Top Jokesters" sidebar) |
| **Purpose** | Get users ranked by contribution metrics (published jokes, total likes received) |

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `period` | string | `week`, `month`, `all_time` (default) |
| `limit` | int | Number of results (default: 5) |

**Success Response (200):**
```json
{
  "results": [
    {
      "id": 1,
      "name": "Uncle Jerry",
      "username": "@uncle_jerry",
      "avatar_url": null,
      "punchline_count": 1240,
      "rank": 1
    }
  ]
}
```

---

### `GET /collections/trending/`  *(NEW)*

| | |
|---|---|
| **Page** | Trending Page (`/trending` — "Hot Collections" sidebar card) |
| **Purpose** | Get public collections gaining traction |

**Success Response (200):**
```json
{
  "results": [
    {
      "id": 10,
      "name": "Monday Meeting Survival",
      "joke_count": 38,
      "saves_this_week": 120,
      "creator_name": "Uncle Jerry"
    }
  ]
}
```

---

### `GET /themes/popular/`  *(NEW)*

| | |
|---|---|
| **Page** | Home Page (`/` — "Popular Themes" sidebar card) |
| **Purpose** | Get popular theme/topic labels for discovery |

**Success Response (200):**
```json
{
  "results": [
    "Coding Humor",
    "School Bus Jokes",
    "Space Puns",
    "Coffee Junkies",
    "Fitness Fails",
    "Pet Parents"
  ]
}
```

---

## 8. Joke Submission & Drafts

### `POST /jokes/submit/`  *(NEW)*

| | |
|---|---|
| **Page** | Submit Joke Page (`/submit`) |
| **Purpose** | Submit a new joke for moderation review |

**Request Body:**
```json
{
  "format": "setup_punchline",
  "setup": "Why don't eggs tell jokes?",
  "punchline": "They'd crack each other up!",
  "text": null,
  "tones": ["dad_joke", "punny"],
  "age_rating": "family_friendly",
  "context_tags": ["school", "icebreaker"],
  "source": "original",
  "language": "en"
}
```

**Field Rules:**
- If `format` is `one_liner`: `text` is required, `setup` and `punchline` are null.
- If `format` is `setup_punchline` or `short_story`: `setup` and `punchline` are required, `text` is auto-generated as concatenation.
- `tones`, `context_tags`: arrays of slugs.
- `age_rating`: slug string.
- `source`: `"original"` or free-text attribution.

**Success Response (201):**
```json
{
  "id": 101,
  "status": "pending",
  "created_at": "2025-10-14T12:00:00Z"
}
```

---

### `GET /jokes/my-drafts/`  *(NEW)*

| | |
|---|---|
| **Page** | Drafts Page (`/drafts`) |
| **Purpose** | List all jokes submitted/drafted by the current user |

**Success Response (200):**
```json
{
  "count": 4,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 101,
      "setup": "Why don't eggs tell jokes?",
      "punchline": "They'd crack each other up!",
      "text": "Why don't eggs tell jokes? They'd crack each other up!",
      "format": "setup_punchline",
      "status": "draft",
      "tones": ["Dad Joke", "Punny"],
      "age_rating": "family_friendly",
      "context_tags": [],
      "last_edited_at": "2025-10-14T16:00:00Z",
      "created_at": "2025-10-14T12:00:00Z",
      "likes": null,
      "rejection_reason": null
    }
  ]
}
```

**Status values:** `draft`, `pending`, `published`, `rejected`

---

### `PATCH /jokes/my-drafts/{id}/`  *(NEW)*

| | |
|---|---|
| **Page** | Drafts Page (`/drafts` — Edit action button) |
| **Purpose** | Update a draft joke (only allowed when status is `draft` or `rejected`) |

**Request Body:** Partial — any subset of the submit fields.

**Success Response (200):** Updated draft object.

---

### `POST /jokes/my-drafts/{id}/submit/`  *(NEW)*

| | |
|---|---|
| **Page** | Drafts Page (`/drafts` — "Submit for Review" / "Resubmit" buttons) |
| **Purpose** | Change a draft's status from `draft`/`rejected` to `pending` (sends it to moderation) |

**Request:** Empty body.

**Success Response (200):**
```json
{ "id": 101, "status": "pending" }
```

---

### `DELETE /jokes/my-drafts/{id}/`  *(NEW)*

| | |
|---|---|
| **Page** | Drafts Page (`/drafts` — trash icon) |
| **Purpose** | Delete a draft permanently |

**Success Response (204):** No content.

---

## 9. User Profile & Activity

### `GET /users/me/profile/`  *(NEW)*

| | |
|---|---|
| **Page** | Profile Page (`/profile`), Header/Sidebar (avatar, name) |
| **Purpose** | Get the current user's full profile including stats, humor DNA, and bio |

**Success Response (200):**
```json
{
  "name": "Laugh Master",
  "username": "@laugh_master",
  "email": "laughmaster@jokesfor.com",
  "bio": "Professional pun enthusiast. Dad joke certified.",
  "avatar_url": null,
  "member_since": "2025-08-15",
  "is_premium": true,
  "stats": {
    "jokes_saved": 24,
    "jokes_shared": 12,
    "collections": 7,
    "days_active": 42
  },
  "humor_dna": [
    { "type": "Dad Jokes", "percentage": 40 },
    { "type": "Puns", "percentage": 30 },
    { "type": "Sarcasm", "percentage": 20 },
    { "type": "Geeky", "percentage": 10 }
  ]
}
```

**Notes:**
- `humor_dna` is computed from the user's onboarding preferences and/or interaction history (likes, saves by tone).
- `stats` are computed aggregates.

---

### `PATCH /users/me/profile/`  *(NEW)*

| | |
|---|---|
| **Page** | Settings Page (`/settings` — Account section), Profile Page (Edit Profile) |
| **Purpose** | Update user profile fields |

**Request Body (partial):**
```json
{
  "first_name": "Laugh",
  "last_name": "Master",
  "bio": "Updated bio text"
}
```

**Success Response (200):** Updated profile object.

---

### `GET /users/me/activity/`  *(NEW)*

| | |
|---|---|
| **Page** | Profile Page (`/profile` — "Recent Activity" feed) |
| **Purpose** | Get the user's recent activity feed |

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `limit` | int | Number of items (default: 10) |

**Success Response (200):**
```json
{
  "results": [
    {
      "id": 1,
      "type": "save",
      "description": "Saved 'Why don't scientists trust atoms'",
      "created_at": "2025-10-14T10:30:00Z"
    },
    {
      "id": 2,
      "type": "like",
      "description": "Liked a Dad Joke about flamingos",
      "created_at": "2025-10-14T05:00:00Z"
    }
  ]
}
```

**Activity `type` values:** `save`, `like`, `share`, `collection`, `draft`, `achievement`

---

### `GET /users/me/achievements/`  *(NEW)*

| | |
|---|---|
| **Page** | Profile Page (`/profile` — "Achievements" grid) |
| **Purpose** | Get user's achievement badges with unlock status |

**Success Response (200):**
```json
{
  "results": [
    {
      "id": "first_save",
      "title": "First Save",
      "description": "Saved your first joke",
      "icon": "bookmark",
      "unlocked": true,
      "unlocked_at": "2025-08-16T00:00:00Z"
    },
    {
      "id": "streak_30",
      "title": "30-Day Streak",
      "description": "Visited 30 days in a row",
      "icon": "diamond",
      "unlocked": false,
      "unlocked_at": null
    }
  ]
}
```

---

## 10. User Settings & Preferences

### `GET /users/me/preferences/`  *(NEW)*

| | |
|---|---|
| **Pages** | Settings Page (`/settings` — Humor Preferences, Notifications, Privacy), Onboarding Page (`/onboarding`) |
| **Purpose** | Get the user's saved preferences |

**Success Response (200):**
```json
{
  "humor_types": ["dad_jokes", "puns", "sarcasm"],
  "notifications": {
    "daily_joke": true,
    "trending_alerts": false,
    "collection_updates": true,
    "email_digest": false
  },
  "privacy": {
    "public_profile": true,
    "show_activity": true,
    "share_analytics": false
  },
  "theme": "light"
}
```

---

### `PUT /users/me/preferences/`  *(NEW)*

| | |
|---|---|
| **Pages** | Settings Page (`/settings` — all toggle switches), Onboarding Page (`/onboarding` — humor type selection) |
| **Purpose** | Save/update user preferences |

**Request Body:**
```json
{
  "humor_types": ["dad_jokes", "puns", "geeky"],
  "notifications": {
    "daily_joke": true,
    "trending_alerts": true,
    "collection_updates": true,
    "email_digest": false
  },
  "privacy": {
    "public_profile": true,
    "show_activity": false,
    "share_analytics": false
  },
  "theme": "light"
}
```

**Success Response (200):** Updated preferences object.

**Notes:**
- The Onboarding Page only updates `humor_types`. It should be possible to PATCH just that field.
- The Settings Page updates individual toggle groups independently.

---

### `POST /auth/password/change/`  *(NEW)*

| | |
|---|---|
| **Page** | Settings Page (`/settings` — "Change Password" button) |
| **Purpose** | Change the user's password |

**Request Body:**
```json
{
  "old_password": "currentpass",
  "new_password1": "newpass123",
  "new_password2": "newpass123"
}
```

**Success Response (200):**
```json
{ "detail": "New password has been saved." }
```

---

### `DELETE /users/me/`  *(NEW)*

| | |
|---|---|
| **Page** | Settings Page (`/settings` — Danger Zone "Delete Account") |
| **Purpose** | Permanently delete the user's account and all associated data |

**Success Response (204):** No content.

---

## 11. Type Reference

### Core Types

```
Joke {
  id: int
  text: string
  setup: string | null
  punchline: string | null
  format: { id: int, name: string, slug: string }
  age_rating: { id: int, name: string, slug: string, min_age: int }
  tones: [{ id: int, name: string, slug: string }]
  context_tags: [{ id: int, name: string, slug: string }]
  culture_tags: [{ id: int, name: string, slug: string }]
  language: { id: int, name: string, code: string }
  source: string
  share_image_url: string | null
  created_at: datetime
}

User {
  pk: int
  email: string
  first_name: string
  last_name: string
}

Collection {
  id: int
  name: string
  is_default: boolean
  joke_count: int (computed)
  created_at: datetime
}

SavedJoke {
  id: int
  joke: Joke
  collection: int (collection ID)
  note: string | null
  saved_at: datetime
}

PaginatedResponse<T> {
  count: int
  next: string | null
  previous: string | null
  results: T[]
}
```

### Enum Values (Slugs)

**Joke Formats:** `one_liner`, `setup_punchline`, `short_story`, `knock_knock`, `question_answer`

**Age Ratings:** `kid_safe`, `teen`, `adult`, `family_friendly`

**Tones (Humor Types):** `clean`, `dark`, `absurdist`, `dad_joke`, `punny`, `sarcastic`, `wordplay`, `observational`, `dry`, `surreal`, `geeky`, `classic`

**Context Tags (Situations):** `wedding`, `work`, `school`, `presentation`, `social_media`, `icebreaker`, `birthday`, `holiday`, `office`, `marriage`, `relationships`, `kids`, `animal_humor`, `tech`, `educational`, `fun`

**Draft Statuses:** `draft`, `pending`, `published`, `rejected`

**Activity Types:** `save`, `like`, `share`, `collection`, `draft`, `achievement`

---

## Endpoint Summary Table

| # | Method | Endpoint | Status | Used By |
|---|--------|----------|--------|---------|
| 1 | POST | `/auth/login/` | Existing | Login |
| 2 | POST | `/auth/registration/` | Existing | Register |
| 3 | POST | `/auth/logout/` | Existing | Settings |
| 4 | GET | `/auth/user/` | Existing | App-wide |
| 5 | POST | `/auth/token/refresh/` | Existing | App-wide |
| 6 | GET | `/jokes/` | Existing | Search, Home |
| 7 | GET | `/jokes/{id}/` | Existing | Sharing/deep-links |
| 8 | GET | `/jokes/random/` | Existing | 404 Page |
| 9 | POST | `/jokes/{id}/rate/` | Existing | JokeCard actions |
| 10 | GET | `/jokes/{id}/my-rating/` | Existing | JokeCard state |
| 11 | GET | `/daily-jokes/today/` | Existing | Home, Daily |
| 12 | GET | `/daily-jokes/history/` | Existing | Daily |
| 13 | GET | `/collections/` | Existing | Library |
| 14 | POST | `/collections/` | Existing | Library |
| 15 | PATCH | `/collections/{id}/` | Existing | Library |
| 16 | DELETE | `/collections/{id}/` | Existing | Library |
| 17 | GET | `/collections/{id}/jokes/` | Existing | Library |
| 18 | GET | `/saved-jokes/` | Existing | Library |
| 19 | POST | `/saved-jokes/` | Existing | JokeCard save |
| 20 | DELETE | `/saved-jokes/{id}/` | Existing | Library |
| 21 | GET | `/saved-jokes/search/` | Existing | Library search |
| 22 | GET | `/favorites/` | **NEW** | Favorites |
| 23 | POST | `/favorites/` | **NEW** | JokeCard heart |
| 24 | DELETE | `/favorites/{id}/` | **NEW** | Favorites |
| 25 | GET | `/favorites/stats/` | **NEW** | Favorites |
| 26 | GET | `/jokes/trending/` | **NEW** | Trending, Home |
| 27 | GET | `/tags/trending/` | **NEW** | Trending, Home |
| 28 | GET | `/tags/rising/` | **NEW** | Trending |
| 29 | GET | `/users/top-jokesters/` | **NEW** | Trending, Home |
| 30 | GET | `/collections/trending/` | **NEW** | Trending |
| 31 | GET | `/themes/popular/` | **NEW** | Home |
| 32 | POST | `/jokes/submit/` | **NEW** | Submit |
| 33 | GET | `/jokes/my-drafts/` | **NEW** | Drafts |
| 34 | PATCH | `/jokes/my-drafts/{id}/` | **NEW** | Drafts |
| 35 | POST | `/jokes/my-drafts/{id}/submit/` | **NEW** | Drafts |
| 36 | DELETE | `/jokes/my-drafts/{id}/` | **NEW** | Drafts |
| 37 | GET | `/users/me/profile/` | **NEW** | Profile, Header |
| 38 | PATCH | `/users/me/profile/` | **NEW** | Settings |
| 39 | GET | `/users/me/activity/` | **NEW** | Profile |
| 40 | GET | `/users/me/achievements/` | **NEW** | Profile |
| 41 | GET | `/users/me/preferences/` | **NEW** | Settings, Onboarding |
| 42 | PUT | `/users/me/preferences/` | **NEW** | Settings, Onboarding |
| 43 | POST | `/auth/password/change/` | **NEW** | Settings |
| 44 | DELETE | `/users/me/` | **NEW** | Settings |

**Total: 44 endpoints (21 existing + 23 new)**
