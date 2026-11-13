"""Universal slide-level visual planning and critic for Navyblue.

Inspired by public agentic presentation workflows (planner -> art director ->
critic -> render QA), implemented as a small deterministic layer that can be
unit-tested without API keys. It never invents facts or rewrites slide content.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter


_STOP = {
    "and", "or", "the", "for", "with", "from", "into", "about", "this", "that",
    "what", "how", "why", "the", "of", "in", "on", "at", "to", "a", "an",
    "va", "yoki", "ham", "uchun", "bilan", "haqida", "bo'yicha", "boyicha",
    "tizimi", "tizim", "asoslari", "mohiyati", "ahamiyati", "kirish",
}
_DOMAIN_TERMS = {
    "medical": ("heart", "cardio", "medical", "medicine", "anatomy", "health", "yurak", "qon tomir", "anatomiya", "tibbiyot", "salomatlik"),
    "history": ("history", "historical", "empire", "war", "dynasty", "tarix", "imperiya", "urush", "sulola", "sivilizatsiya"),
    "fiction": ("fiction", "fantasy", "wizard", "magic", "harry potter", "hogwarts", "sehr", "fantastika", "afsona", "qahramon"),
    "science": ("science", "biology", "chemistry", "physics", "cloning", "cell", "biologiya", "klonlash", "hujayra", "fizika", "kimyo"),
    "finance": ("budget", "finance", "accounting", "economy", "byudjet", "budjet", "moliya", "buxgalteriya", "iqtisod"),
    "logistics": ("logistics", "supply chain", "warehouse", "transport", "freight", "logistika", "ta'minot zanjiri", "ombor", "transport"),
    "geography": ("geography", "map", "region", "country", "geografiya", "xarita", "mintaqa", "mamlakat"),
    "biography": ("biography", "life of", "person", "biografiya", "hayoti", "shaxs"),
}
SUPPORTED_COMPOSITIONS = {
    "editorial_split", "asym_grid", "full_bleed", "modular", "timeline", "radial",
    "data_focus", "comparison", "typographic", "layered", "swiss_column", "swiss_modular",
    "editorial_masthead", "editorial_pullquote", "magazine_spread", "split_caption",
    "asymmetric_caption", "image_dominant", "photo_triptych", "photo_diptych",
    "cinematic_panorama", "cinematic_frame", "brutalist_type", "oversized_numeral",
    "metric_wall", "data_dashboard", "data_waterfall", "data_lollipop", "map_route",
    "typographic_poster", "data_slopegraph", "process_lane", "swimlane", "isometric_stack",
    "isometric_exploded", "radial_network", "orbit_system", "matrix_priority", "funnel_steps",
    "comparison_duel", "card_stack", "card_mosaic", "grid_manifesto", "negative_space",
    "editorial_rows", "asym_cards",
}

_LAYOUT_TYPES = {
    "chart": "data_visualization", "stats": "data_visualization", "kpi": "data_visualization",
    "waterfall": "data_visualization", "table": "structured_comparison",
    "timeline": "chronology", "map": "geographic_map", "network": "relationship_map",
    "hub": "relationship_map", "orbit": "relationship_map", "venn": "relationship_map",
    "chain": "process_diagram", "isometric": "process_diagram", "swimlane": "process_diagram",
    "funnel": "process_diagram", "pyramid": "hierarchy_diagram",
    "compare": "comparison", "before_after": "comparison", "matrix": "decision_matrix",
    "quote": "editorial_quote", "statement": "editorial_statement",
    "collage": "image_collection", "image_story": "narrative_image",
    "hero": "hero_image", "image_text": "topic_image", "text_image": "topic_image",
    "cards": "structured_cards", "bento": "structured_cards",
}
_COMPOSITIONS = {
    "data_visualization": ("data_dashboard", "data_focus", "editorial_split", "metric_wall"),
    "structured_comparison": ("swiss_modular", "comparison_duel", "editorial_rows", "data_dashboard"),
    "chronology": ("timeline", "cinematic_frame", "editorial_rows", "magazine_spread"),
    "geographic_map": ("map_route", "editorial_split", "magazine_spread"),
    "relationship_map": ("orbit_system", "radial_network", "editorial_split", "card_mosaic"),
    "process_diagram": ("process_lane", "isometric_exploded", "funnel_steps", "editorial_split"),
    "hierarchy_diagram": ("isometric_stack", "isometric_exploded", "editorial_rows"),
    "comparison": ("comparison_duel", "swiss_modular", "magazine_spread", "asym_grid"),
    "decision_matrix": ("matrix_priority", "swiss_modular", "data_dashboard"),
    "editorial_quote": ("editorial_pullquote", "typographic", "negative_space"),
    "editorial_statement": ("typographic_poster", "negative_space", "editorial_masthead"),
    "image_collection": ("photo_triptych", "card_mosaic", "magazine_spread"),
    "narrative_image": ("cinematic_frame", "photo_diptych", "magazine_spread"),
    "hero_image": ("full_bleed", "cinematic_panorama", "image_dominant"),
    "topic_image": ("editorial_split", "asym_grid", "layered", "magazine_spread"),
    "structured_cards": ("asym_cards", "card_mosaic", "magazine_spread", "editorial_rows"),
    "text_editorial": ("swiss_column", "typographic_poster", "editorial_split", "negative_space"),
}


def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _words(value):
    return [w for w in _fold(value).split() if len(w) > 2 and w not in _STOP]


def _slide_text(slide):
    parts = [slide.get(k) for k in ("title", "text", "story_beat", "visual_focus", "photo_query", "map_query")]
    for key in ("cards", "items", "steps", "nodes", "levels", "takeaways"):
        value = slide.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts.extend(item.values())
                else:
                    parts.append(item)
    return " ".join(str(x) for x in parts if isinstance(x, (str, int, float)))


def classify_visual_domain(topic):
    folded = _fold(topic)
    scored = []
    for domain, terms in _DOMAIN_TERMS.items():
        score = sum(2 if len(_fold(term).split()) > 1 else 1
                    for term in terms if _fold(term) and _fold(term) in folded)
        if score:
            scored.append((score, domain))
    return sorted(scored, key=lambda x: (-x[0], x[1]))[0][1] if scored else "general"


def _visual_type(slide):
    layout = str(slide.get("layout") or "").casefold().strip()
    if layout in _LAYOUT_TYPES:
        return _LAYOUT_TYPES[layout]
    role = str(slide.get("story_role") or "").casefold()
    if role in {"chronology", "origin"}:
        return "chronology"
    if role in {"workflow", "mechanism", "implementation"}:
        return "process_diagram"
    if role in {"comparison", "tradeoff"}:
        return "comparison"
    if role in {"relationship", "actors"}:
        return "relationship_map"
    if role in {"evidence", "measurement", "finding"}:
        return "data_visualization"
    if role in {"geography"}:
        return "geographic_map"
    if role in {"quote", "reflection"}:
        return "editorial_quote"
    if slide.get("photo_query") or slide.get("visual_focus"):
        return "topic_image"
    return "text_editorial"


def _focus(slide, topic):
    for value in (slide.get("visual_focus"), slide.get("title"), slide.get("story_beat")):
        value = re.sub(r"\s+", " ", str(value or "")).strip(" -:—")
        if len(value) >= 4:
            return value[:120]
    return str(topic or "Mavzu")[:120]


def _search_query(slide, topic, domain):
    raw = slide.get("map_query") if str(slide.get("layout") or "").casefold() == "map" else slide.get("photo_query")
    raw = re.sub(r"\s+", " ", str(raw or "")).strip(" ,;")
    # Preserve a useful model-provided query, but reject generic one-word prompts.
    if len(_words(raw)) >= 2:
        return raw[:180]
    focus = _focus(slide, topic)
    terms = _words(focus)
    topic_terms = _words(topic)
    merged = []
    for word in terms + topic_terms:
        if word not in merged:
            merged.append(word)
    return " ".join(merged[:7]) or domain


def _choose_composition(kind, topic, slide, index, previous):
    options = _COMPOSITIONS.get(kind, _COMPOSITIONS["text_editorial"])
    seed = hashlib.sha256((str(topic) + "|" + str(index) + "|" + _focus(slide, topic)).encode("utf-8")).digest()
    start = int.from_bytes(seed[:4], "big") % len(options)
    ordered = list(options[start:]) + list(options[:start])
    return next((item for item in ordered if item in SUPPORTED_COMPOSITIONS and item not in previous[-2:]), "editorial_split")


def build_visual_plan(topic, slides):
    """Return a slide-by-slide manifest; input slides are never mutated."""
    domain = classify_visual_domain(topic)
    manifest = []
    previous_compositions = []
    for index, slide in enumerate(slides or []):
        if not isinstance(slide, dict):
            continue
        kind = _visual_type(slide)
        focus = _focus(slide, topic)
        query = _search_query(slide, topic, domain)
        current_design = slide.get("design") if isinstance(slide.get("design"), dict) else {}
        supplied = str(current_design.get("composition") or "").strip()
        composition = supplied if supplied in SUPPORTED_COMPOSITIONS else _choose_composition(kind, topic, slide, index, previous_compositions)
        if composition in previous_compositions[-2:]:
            composition = _choose_composition(kind, topic, slide, index + 101, previous_compositions)
        previous_compositions.append(composition)
        manifest.append({
            "slide_index": index,
            "title": str(slide.get("title") or "")[:140],
            "story_role": str(slide.get("story_role") or "analysis"),
            "visual_type": kind,
            "visual_focus": focus,
            "search_query": query,
            "composition": composition,
            "domain": domain,
            "asset_policy": "retrieval_or_original_diagram",
            "uniqueness_key": _fold(focus),
        })
    return {"domain": domain, "slide_count": len(manifest), "slides": manifest}


def apply_visual_plan(slides, plan):
    """Attach the plan to each slide and fill missing design metadata only."""
    items = plan.get("slides") if isinstance(plan, dict) else []
    applied = 0
    for item in items or []:
        index = item.get("slide_index")
        if not isinstance(index, int) or index < 0 or index >= len(slides):
            continue
        slide = slides[index]
        if not isinstance(slide, dict):
            continue
        slide["_visual_plan"] = dict(item)
        design = dict(slide.get("design") or {})
        design.setdefault("visual_type", item.get("visual_type"))
        design.setdefault("visual_focus", item.get("visual_focus"))
        design["composition"] = item.get("composition")
        slide["design"] = design
        if not slide.get("visual_focus"):
            slide["visual_focus"] = item.get("visual_focus")
        applied += 1
    return applied


def critique_visual_plan(plan):
    """Deterministic critic for missing anchors, repeated scenes and layout rhythm."""
    items = (plan or {}).get("slides") or []
    issues = []
    focus_counts = Counter(x.get("uniqueness_key") for x in items if x.get("uniqueness_key"))
    query_counts = Counter(_fold(x.get("search_query")) for x in items if x.get("search_query"))
    composition_counts = Counter(x.get("composition") for x in items if x.get("composition"))
    for item in items:
        index = item.get("slide_index", -1) + 1
        if not item.get("title"):
            issues.append({"slide": index, "severity": "high", "code": "missing_title", "message": "Slayd sarlavhasi yo'q"})
        if not item.get("visual_focus"):
            issues.append({"slide": index, "severity": "high", "code": "missing_visual_focus", "message": "Vizualning asosiy obyekti aniqlanmagan"})
        if len(_words(item.get("search_query"))) < 2 and item.get("visual_type") not in {"data_visualization", "text_editorial", "editorial_quote", "editorial_statement"}:
            issues.append({"slide": index, "severity": "medium", "code": "weak_search_query", "message": "Rasm qidiruvi uchun aniq obyekt yetarli emas"})
        if focus_counts.get(item.get("uniqueness_key"), 0) > 1:
            issues.append({"slide": index, "severity": "medium", "code": "repeated_visual_focus", "message": "Bir xil vizual fokus takrorlangan"})
        if query_counts.get(_fold(item.get("search_query")), 0) > 1 and item.get("visual_type") not in {"data_visualization", "text_editorial"}:
            issues.append({"slide": index, "severity": "medium", "code": "repeated_search_query", "message": "Bir xil rasm qidiruvi takrorlangan"})
    if len(items) >= 4:
        for composition, count in composition_counts.items():
            if count / len(items) > 0.5:
                issues.append({"slide": 0, "severity": "low", "code": "composition_overuse", "message": f"{composition} kompozitsiyasi juda ko'p ishlatilgan"})
    return {"passed": not any(x["severity"] == "high" for x in issues), "issue_count": len(issues), "issues": issues}


def prepare_deck_visuals(topic, slides):
    """Single entry point: plan -> apply -> critic; returns manifest and QA."""
    plan = build_visual_plan(topic, slides)
    applied = apply_visual_plan(slides, plan)
    report = critique_visual_plan(plan)
    return {"manifest": plan, "qa": report, "applied": applied}
