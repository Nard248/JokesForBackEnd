# Phase 02: Data Models - Context

**Gathered:** 2026-01-11
**Status:** Ready for planning

<vision>
## How This Should Work

A rich tagging system where every joke is deeply tagged across multiple dimensions — humor type, age rating, context/situation, and format. Users should be able to search and filter jokes by combining any of these dimensions freely.

The system serves three equally important search patterns:
- **Situation-based:** "I need a joke for a wedding toast" or "something for my work presentation"
- **Tone-based:** "Show me dad jokes" or "I want something dark/edgy"
- **Audience-based:** "Safe for my 8-year-old" or "adult humor only"

All three patterns should work well, and users should be able to combine them (e.g., "kid-safe dad jokes for a birthday party").

</vision>

<essential>
## What Must Be Nailed

- **Flexible filtering** — Users can combine any filters (age + context + tone) and get relevant results. This is the core of the search engine experience.
- Tags must be comprehensive enough to support the three main search patterns (situation, tone, audience)
- Structure should make multi-dimensional queries efficient

</essential>

<boundaries>
## What's Out of Scope

- Multi-language support — English only for MVP
- User-generated content structures — all jokes are curated/imported for now
- Otherwise open to including whatever makes sense for the model

</boundaries>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches for joke structure, attribution, and metadata fields.

</specifics>

<notes>
## Additional Context

This is a search-first platform. The data model exists to serve filtering and discovery. Every field should earn its place by enabling better search results.

</notes>

---

*Phase: 02-data-models*
*Context gathered: 2026-01-11*
