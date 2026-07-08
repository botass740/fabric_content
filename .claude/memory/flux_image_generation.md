---
name: flux-image-generation
description: FLUX image generation via OpenRouter for Dzen article covers
metadata: 
  node_type: memory
  type: reference
  originSessionId: 0c348cb3-a0a4-4ee3-9cc0-f929cf8ca8c0
---

FLUX image generation is enabled via `app/generators/images.py` → `FluxClient` (`app/generators/flux_client.py`).

Pipeline:
1. `analyze_article_for_image()` — LLM call to determine category, emotion, subject, location
2. `get_template(category)` — picks a prompt template from `app/prompts/image_templates.py`
3. `_build_flux_prompt()` — substitutes analysis data into template
4. `FluxClient.generate_image()` — POST to `https://openrouter.ai/api/v1/images` with model `black-forest-labs/flux.2-pro`
5. Falls back to `_create_placeholder(title)` if FLUX fails (uses PIL to draw text on gray background)

Settings: `FLUX_MODEL`, `FLUX_OUTPUT_FORMAT`, `OPENROUTER_API_KEY` in `.env`

**Why:** Need high-quality, relevant cover images for Dzen articles. Placeholder was used during debugging of Playwright publishing.

**How to apply:** To temporarily disable FLUX, change `if settings.openrouter_api_key:` to `if False:` in `app/generators/images.py:134`.