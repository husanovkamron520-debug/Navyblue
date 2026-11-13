# Universal PPTX Engine — architecture and rollout

## Goal

Generate high-quality, topic-faithful, visually varied and structurally valid decks for arbitrary subjects. The system must not assume that every topic is a corporate presentation, a problem/solution story, or a photo collage.

## Architecture

1. **Content planner** — owns the narrative, audience, factual claims, evidence and slide coverage. It may select a topic-specific or hybrid story arc; no universal slide order is mandatory.
2. **Visual director** — creates a slide-level manifest: story role, visual purpose, focal subject, asset query, visual type, composition and uniqueness key.
3. **Asset engine** — retrieves properly licensed, relevant media or creates original explanatory diagrams. It records provenance and must not silently substitute unrelated stock imagery.
4. **Slide composer** — maps the approved brief to renderer-supported layouts and composition profiles while preserving the slide's content.
5. **Independent critic** — checks narrative fidelity, unsupported claims, repetition, subject relevance and whether the visual actually explains the slide.
6. **Render QA and repair** — renders every slide, inspects geometry, clipping, empty visual slots, duplicate assets, text overflow and package integrity; repairs and re-renders where possible.
7. **Preflight** — blocks delivery for critical defects and records warnings for lower-confidence heuristics.

## Design principles

- One slide, one main job, one dominant idea.
- The visual form follows the content: maps for spatial ideas, timelines for chronology, diagrams for mechanisms, charts for sourced data, portraits/scenes for people and narratives.
- Shapes may explain relationships but must not masquerade as subject imagery.
- Do not invent metrics, citations, dates, statistics or canonical facts.
- Reuse an image only when the repetition is narratively intentional.
- Preserve meaningful text and slide structure during visual repair.
- Every composition must be supported by the actual renderer; unknown profiles are rejected before serialization.
- Topic-specific visual modules are optional domain packs, not the universal engine itself.

## Current implementation

- Existing story engine remains responsible for broad narrative archetypes and story roles.
- `ppt_visual_director.py` adds deterministic domain classification, per-slide visual manifests, renderer-safe composition diversification and a visual critic report.
- `ppt_content_critic.py` adds an independent non-mutating pass for thin content, repeated slides, generic titles, unsourced numeric claims and fiction/genre KPI drift.
- `bot.py` attaches that manifest before asset retrieval and uses its query as a fallback when a slide has no explicit photo query.
- `ppt_asset_manifest.py` records per-slide original/retrieved/fallback assets, provider, available credit, query and image hash; it warns about missing provenance and duplicate media.
- Visual Director only selects composition profiles registered by the current renderer and does not force plain text slides to use stock photos.
- The asset manifest records provider/license metadata only to the extent returned by the provider; it does not claim that every provider exposes a direct source URL or item-level license record.
- Unit tests cover medical, historical, fantasy, scientific, finance and logistics topic families, content preservation, renderer-supported composition diversity, content critique and asset provenance.

## Rollout gates

### Stage 1 — planning foundation (implemented)
- Visual Director integrated into outline generation.
- Renderer-safe composition selection, per-slide visual focus and domain-aware prompts.
- Unit tests and CI compile checks.

### Stage 2 — asset intelligence (partially implemented)
- Per-slide asset provenance manifest, image hashes and duplicate-media warnings.
- Existing stock relevance filters and local fallback ladder remain in place.
- Remaining: provider-specific source URLs/license metadata normalization and stricter asset replacement when relevance is uncertain.

### Stage 3 — independent critic (partially implemented)
- Non-mutating content critic and visual-plan critic run on generated outlines.
- Unsupported metrics, thin content, repeated slides, generic titles and repeated visual focus are reported.
- Remaining: targeted model-assisted repair and a second critic pass; current warnings do not constitute external fact verification.

### Stage 4 — rendered review and repair
- Render each slide to an image.
- Check layout-specific visual coverage, crop, text overflow, hierarchy and repetition.
- Apply bounded repair attempts, then fail safely if critical issues remain.

### Stage 5 — cross-domain acceptance
- Generate representative decks in medicine, history, biology, fiction, economics, logistics, geography and technology.
- Inspect every slide; compare automated QA with actual rendered quality.
- Deploy only after the acceptance suite is green.

## Safety and deployment

The current integration commits to the connected main branch; branch protection and mandatory pull-request review are not enabled. The primary Render service is configured for automatic deployment from main, so each pushed commit can trigger a production deploy. Secrets and production environment settings are not modified by this architecture work. A green CI run or successful Render deploy is not equivalent to visual acceptance of generated decks; rendered end-to-end checks remain mandatory.
