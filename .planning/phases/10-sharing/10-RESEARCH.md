# Phase 10: Sharing - Research

**Researched:** 2026-01-11
**Domain:** Django dynamic OG image generation + rating system
**Confidence:** HIGH

<research_summary>
## Summary

Researched how to implement social share cards and rating systems in Django. The standard approach for dynamic Open Graph images uses **SVG templates + CairoSVG** for PNG conversion - this is the Lincoln Loop pattern used in production Django sites.

For rating systems, the choice between thumbs up/down vs 5-star depends on use case. For joke ratings where binary "funny/not funny" is the goal, thumbs up/down with `django-updown-ratings` or a simple custom model is appropriate.

Key finding: **Don't generate images on every request**. Store generated PNGs in a FileField and regenerate only when content changes. All major platforms (Twitter, Facebook, LinkedIn) accept **1200 x 630 pixels** as the universal safe size.

**Primary recommendation:** Use SVG templates with CairoSVG for context-themed share cards. Store generated images on model save. Use simple JokeRating model with thumbs up/down for ratings.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| cairosvg | 2.7.1+ | SVG to PNG conversion | Lightweight, Django-compatible, production-proven |
| Pillow | 10.0+ | Image manipulation | Already in stack, handles resizing/optimization |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| django-updown-ratings | 0.2+ | Thumbs up/down voting | Simple binary rating out of box |
| playwright | 1.40+ | Headless browser screenshots | Only if CSS-heavy designs needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| CairoSVG | Playwright | Playwright supports full CSS but takes ~15s per image, resource heavy |
| CairoSVG | Pillow-only | Pillow requires manual coordinate math, fragile for complex layouts |
| django-updown-ratings | Custom model | Custom gives full control, but updown is battle-tested |

**Installation:**
```bash
pip install cairosvg Pillow
```

Note: CairoSVG requires Cairo library on system. On macOS: `brew install cairo`. On Linux: `apt-get install libcairo2-dev`.
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
jokes/
├── templates/
│   └── jokes/
│       └── share_cards/          # SVG templates per joke type
│           ├── base_card.svg     # Base layout
│           ├── dad_joke.svg      # Dad joke theme
│           ├── dark_humor.svg    # Dark humor theme
│           └── pun.svg           # Pun theme
├── models.py                     # Add JokeRating, share_image field to Joke
├── share_cards.py                # OG image generation logic
└── views.py                      # Share endpoints
```

### Pattern 1: SVG Template + CairoSVG Conversion
**What:** Use Django templates to render SVG with dynamic content, convert to PNG with CairoSVG
**When to use:** Any dynamic OG image generation
**Example:**
```python
# Source: Lincoln Loop blog (verified August 2025)
import io
import cairosvg
from django.template.loader import render_to_string

class Joke(models.Model):
    # ... existing fields ...
    share_image = models.ImageField(upload_to="share-cards/", blank=True)

    def generate_share_card_svg(self) -> str:
        """Render SVG template with joke data"""
        # Select template based on joke tone
        template = self._get_card_template()
        return render_to_string(template, {"joke": self})

    def _get_card_template(self) -> str:
        """Get themed template based on primary tone"""
        tone = self.tones.first()
        if tone:
            tone_templates = {
                'dad-jokes': 'jokes/share_cards/dad_joke.svg',
                'dark': 'jokes/share_cards/dark_humor.svg',
                'puns': 'jokes/share_cards/pun.svg',
            }
            return tone_templates.get(tone.slug, 'jokes/share_cards/base_card.svg')
        return 'jokes/share_cards/base_card.svg'

    def write_share_image(self) -> None:
        """Convert SVG to PNG and save"""
        png_buffer = io.BytesIO()
        cairosvg.svg2png(
            bytestring=self.generate_share_card_svg().encode(),
            write_to=png_buffer,
            output_width=1200,
            output_height=630
        )
        png_buffer.seek(0)
        self.share_image.save(f"joke-{self.id}.png", png_buffer, save=False)
```

### Pattern 2: SVG Text Wrapping with tspan
**What:** SVG lacks auto text-wrap - use Django's wordwrap filter with tspan elements
**When to use:** Any multi-line text in SVG
**Example:**
```xml
<!-- Source: Lincoln Loop blog -->
{% with y_start=120 joke_lines=joke.text|wordwrap:30 %}
<text class="joke-text">
  {% for line in joke_lines.splitlines %}
    {% with offset=forloop.counter0|multiply:50 %}
    <tspan x="60" y="{{ y_start|add:offset }}">{{ line }}</tspan>
    {% endwith %}
  {% endfor %}
</text>
{% endwith %}
```

### Pattern 3: JokeRating Model
**What:** Simple binary rating (like/dislike) per user per joke
**When to use:** Thumbs up/down voting
**Example:**
```python
class JokeRating(models.Model):
    LIKE = 1
    DISLIKE = -1
    RATING_CHOICES = [(LIKE, 'Like'), (DISLIKE, 'Dislike')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    joke = models.ForeignKey('Joke', on_delete=models.CASCADE, related_name='ratings')
    rating = models.SmallIntegerField(choices=RATING_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['user', 'joke']]  # One rating per user per joke
```

### Anti-Patterns to Avoid
- **Generating images on every request:** Always store generated images, regenerate only on content change
- **Embedding fonts in SVG:** CairoSVG doesn't support embedded fonts - use system fonts
- **Using Playwright for simple cards:** Overkill, takes 15s per image, use CairoSVG instead
- **Complex SVG layouts:** Keep SVG simple - CairoSVG has limitations with advanced features
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SVG text wrapping | Manual character counting | Django `wordwrap` filter + `<tspan>` | Edge cases with special chars, multi-byte unicode |
| Image coordinates | Pixel-perfect manual placement | SVG viewBox with relative positioning | Fragile, breaks on design changes |
| OG meta tags | String concatenation | Django template with og: meta tags | Missing tags cause blank previews |
| Rating aggregation | Python loop counting | Django `aggregate()` with `Count`/`Sum` | Database does it faster |
| Image caching | Request-time generation | Pre-generate on save, FileField storage | Request latency, server load |

**Key insight:** OG image generation has deceptively complex edge cases - font rendering, text wrapping, image encoding. CairoSVG handles these reliably. Don't try to build a custom renderer.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Font Rendering Failures
**What goes wrong:** Text renders in wrong font or as boxes
**Why it happens:** CairoSVG only uses system fonts, not embedded SVG fonts
**How to avoid:** Install required TTF fonts on server at `/usr/share/fonts/` or `~/.local/share/fonts/`
**Warning signs:** Text looks different in browser vs generated PNG

### Pitfall 2: Images Not Showing on Social Platforms
**What goes wrong:** Sharing a link shows blank preview or wrong image
**Why it happens:** Missing og:image meta tag, wrong image URL, or image too small
**How to avoid:**
- Use absolute URLs for og:image
- Minimum 600x315px (recommend 1200x630)
- Test with Facebook Sharing Debugger and Twitter Card Validator
**Warning signs:** First share shows old/wrong image (platforms cache aggressively)

### Pitfall 3: Slow Share Card Generation
**What goes wrong:** Model saves become slow (seconds)
**Why it happens:** Generating image synchronously on every save
**How to avoid:**
- Only regenerate when text/theme changes (check if fields changed)
- Use Celery task for background generation if needed
**Warning signs:** Admin becomes sluggish when editing jokes

### Pitfall 4: Memory Issues with Large Images
**What goes wrong:** Server OOM when generating many images
**Why it happens:** Pillow/Cairo hold images in memory
**How to avoid:**
- Use BytesIO and explicitly close/seek
- Don't batch-generate without throttling
- Keep output under 1200x630 (no need for larger)
**Warning signs:** Celery workers dying during bulk operations
</common_pitfalls>

<code_examples>
## Code Examples

### Basic SVG Share Card Template
```xml
<!-- jokes/templates/jokes/share_cards/base_card.svg -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
  <!-- Background -->
  <rect width="1200" height="630" fill="#1a1a2e"/>

  <!-- Brand stripe -->
  <rect y="580" width="1200" height="50" fill="#e94560"/>

  <!-- Logo/brand text -->
  <text x="60" y="615" fill="white" font-family="Inter, sans-serif" font-size="24">
    JokesFor.com
  </text>

  <!-- Joke text (wrapped via Django template) -->
  {% with joke_lines=joke.text|wordwrap:40 %}
  <text fill="white" font-family="Inter, sans-serif" font-size="36">
    {% for line in joke_lines.splitlines %}
    <tspan x="60" y="{{ 200|add:forloop.counter0|multiply:50 }}">{{ line|escape }}</tspan>
    {% endfor %}
  </text>
  {% endwith %}

  <!-- Joke type badge -->
  <rect x="60" y="500" width="120" height="40" rx="20" fill="#e94560"/>
  <text x="120" y="528" fill="white" font-family="Inter, sans-serif" font-size="18" text-anchor="middle">
    {{ joke.tones.first.name|default:"Joke" }}
  </text>
</svg>
```

### Share Card Generation on Model Save
```python
# jokes/models.py
import io
import cairosvg
from django.db import models
from django.template.loader import render_to_string
from django.conf import settings

class Joke(models.Model):
    # ... existing fields ...
    share_image = models.ImageField(upload_to="share-cards/", blank=True)
    _original_text = None  # Track for change detection

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_text = self.text

    def save(self, *args, **kwargs):
        # Only regenerate if text changed or no image exists
        text_changed = self._original_text != self.text
        if text_changed or not self.share_image:
            self._generate_share_image()
        super().save(*args, **kwargs)
        self._original_text = self.text

    def _generate_share_image(self):
        """Generate themed share card PNG"""
        svg_content = render_to_string(
            self._get_template_name(),
            {"joke": self}
        )
        png_buffer = io.BytesIO()
        cairosvg.svg2png(
            bytestring=svg_content.encode('utf-8'),
            write_to=png_buffer,
            output_width=1200,
            output_height=630
        )
        png_buffer.seek(0)
        filename = f"joke-{self.id or 'new'}.png"
        self.share_image.save(filename, png_buffer, save=False)
```

### OG Meta Tags in Template
```html
<!-- base.html or joke_detail.html -->
<meta property="og:title" content="{{ joke.text|truncatechars:60 }}" />
<meta property="og:description" content="Find more jokes at JokesFor.com" />
<meta property="og:image" content="{{ request.scheme }}://{{ request.get_host }}{{ joke.share_image.url }}" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:type" content="article" />
<meta property="og:url" content="{{ request.build_absolute_uri }}" />

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:image" content="{{ request.scheme }}://{{ request.get_host }}{{ joke.share_image.url }}" />
```

### Rating API Endpoint
```python
# jokes/views.py
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

class JokeViewSet(viewsets.ModelViewSet):
    # ... existing code ...

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def rate(self, request, pk=None):
        """Rate a joke: POST /api/v1/jokes/{id}/rate/ with {"rating": 1} or {"rating": -1}"""
        joke = self.get_object()
        rating_value = request.data.get('rating')

        if rating_value not in [1, -1]:
            return Response(
                {"error": "Rating must be 1 (like) or -1 (dislike)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        rating, created = JokeRating.objects.update_or_create(
            user=request.user,
            joke=joke,
            defaults={'rating': rating_value}
        )

        return Response({
            "rating": rating.rating,
            "created": created,
            "joke_score": joke.ratings.aggregate(
                score=Sum('rating')
            )['score'] or 0
        })
```
</code_examples>

<image_requirements>
## Social Platform Image Requirements

### Universal Safe Size
**1200 x 630 pixels (1.91:1 ratio)** works across all major platforms.

| Platform | Recommended | Minimum | Max File Size |
|----------|-------------|---------|---------------|
| Facebook | 1200 x 630 | 600 x 315 | 8 MB |
| Twitter | 1200 x 628 | 300 x 157 | 5 MB |
| LinkedIn | 1200 x 627 | 400 x 400 | 5 MB |
| WhatsApp | 1200 x 630 | 300 x 200 | 5 MB |

**Best practices:**
- Keep file size under 1 MB for fast loading
- Use PNG for graphics/text, JPEG for photos
- Keep important content centered (platforms crop edges)
- Test with platform debuggers before launch
</image_requirements>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pillow direct drawing | SVG + CairoSVG | 2023-2024 | More maintainable, designer-friendly |
| Selenium/PhantomJS | Playwright | 2022+ | Playwright faster, but still heavy |
| Generate on request | Pre-generate on save | Always best | Critical for performance |

**New tools/patterns to consider:**
- **ogimage.gallery**: Collection of OG image design patterns for inspiration
- **og-img (TypeScript)**: Declarative OG generation if you have Node in stack

**Deprecated/outdated:**
- **PhantomJS**: Abandoned, use Playwright if headless browser needed
- **Wkhtmltoimage**: Outdated WebKit, rendering issues on modern designs
</sota_updates>

<open_questions>
## Open Questions

1. **Theme-specific font choices**
   - What we know: Different fonts can reinforce joke types (playful for dad jokes, edgy for dark)
   - What's unclear: Which specific fonts work well for each category
   - Recommendation: Start with Inter (clean, readable), iterate on theming post-MVP

2. **Share analytics granularity**
   - What we know: Can track share button clicks client-side
   - What's unclear: How to track actual shares (platform APIs vary)
   - Recommendation: Track clicks as proxy, don't over-engineer analytics for MVP
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [Lincoln Loop - Dynamic OG images with Django and SVG](https://lincolnloop.com/blog/dynamic-open-graph-images-with-django-and-svg/) - August 2025, production implementation
- [CairoSVG Documentation](https://cairosvg.org/documentation/) - Official library docs
- [Twitter Card Documentation](https://developer.x.com/en/docs/x-for-websites/cards/overview/summary-card-with-large-image) - Official requirements

### Secondary (MEDIUM confidence)
- [DjangoTricks - Creating OG Images](https://www.djangotricks.com/blog/2025/01/creating-open-graph-images-in-django-for-improved-social-media-sharing/) - January 2025, Playwright approach
- [Krumzi - OG Image Sizes Guide](https://www.krumzi.com/blog/open-graph-image-sizes-for-social-media-the-complete-2025-guide) - Platform size requirements
- [GitHub - django-updown](https://github.com/weluse/django-updown) - Rating system implementation

### Tertiary (LOW confidence - needs validation)
- None - all findings verified against official sources
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: CairoSVG for image generation
- Ecosystem: Pillow, django-updown-ratings
- Patterns: SVG templating, change-detect regeneration
- Pitfalls: Fonts, caching, memory, platform requirements

**Confidence breakdown:**
- Standard stack: HIGH - verified with official docs and production examples
- Architecture: HIGH - from Lincoln Loop production implementation
- Pitfalls: HIGH - documented issues with known solutions
- Code examples: HIGH - adapted from verified sources

**Research date:** 2026-01-11
**Valid until:** 2026-02-11 (30 days - stable technology)
</metadata>

---

*Phase: 10-sharing*
*Research completed: 2026-01-11*
*Ready for planning: yes*
