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
- `ppt_asset_manifest.py` records per-slide media hashes, providers/generators, credits, search queries and license-status metadata; it flags unattributed and duplicated assets.
- `bot.py` attaches that manifest before asset retrieval and uses its query as a fallback when a slide has no explicit photo query.
- Visual Director only selects composition profiles registered by the current renderer.
- Unit tests cover medical, historical, fantasy, scientific, finance and logistics topic families, per-slide plans, content preservation, composition diversity and duplicate-focus detection.

## Rollout gates

### Stage 1 — planning foundation
- Visual Director integrated into outline generation.
- Unit tests and CI compile checks pass.
- No production deploy until full regression checks are green.

### Stage 2 — asset intelligence
- Build a source-aware asset manifest with licensing/provenance.
- Add per-slide relevance scoring, duplicate detection and a deliberate fallback ladder.
- Prefer specific subject assets over generic decorative imagery.

### Stage 3 — independent critic
- Add separate content and visual critique passes.
- Reject unsupported claims and topic drift; request targeted revisions rather than regenerating the whole deck.

### Stage 4 — rendered review and repair
- Render each slide to an image.
- Check layout-specific visual coverage, crop, text overflow, hierarchy and repetition.
- Apply bounded repair attempts, then fail safely if critical issues remain.

### Stage 5 — cross-domain acceptance
- Generate representative decks in medicine, history, biology, fiction, economics, logistics, geography and technology.
- Inspect every slide; compare automated QA with actual rendered quality.
- Deploy only after the acceptance suite is green.

## Safety and deployment

Changes are developed on a feature branch and reviewed through a pull request. Secrets and production service settings are not modified by this architecture work. A passing Python test suite is not equivalent to visual acceptance of generated decks; rendered end-to-end checks remain mandatory.
