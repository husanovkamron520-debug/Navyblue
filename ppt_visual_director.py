"""Universal, slide-level visual direction for the Navyblue presentation engine.

The director creates an auditable visual plan; it does not fabricate facts or force
every slide into a photo layout. Rendering remains the responsibility of the existing
PPTX composer and asset providers.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from ppt_story_engine import classify_archetype, infer_story_role


def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _slide_text(slide):
    parts = [slide.get("title", ""), slide.get("text", ""), slide.get("story_beat", "")]
    for key in ("cards", "items", "steps", "nodes", "levels", "takeaways", "stats", "kpis"):
        values = slide.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    parts.extend(v for v in item.values() if isinstance(v, (str, int, float)))
                elif isinstance(item, (str, int, float)):
                    parts.append(item)
    return " ".join(str(x) for x in parts if x)


def _has(text, *terms):
    return any(_fold(term) in text for term in terms)


def _visual_kind(slide, topic):
    title = _fold(slide.get("title"))
    body = _fold(_slide_text(slide))
    whole = title + " " + body
    layout = _fold(slide.get("layout"))

    # Existing explicit structured layouts are authoritative.
    if layout == "map" or _has(whole, "xarita", "geografik joylashuv", "route map", "geographic distribution"):
        return "map", "Geografik ma'lumotni xarita orqali ko'rsatish"
    if layout in {"timeline", "chronology"} or _has(whole, "timeline", "xronologiya", "tarixiy bosqich", "yilma yil", "davrlar ketma"):
        return "timeline", "Vaqt ketma-ketligini ko'rsatish"
    if layout in {"chart", "stats", "data"}:
        return "data", "Mavjud miqdoriy ma'lumotni ko'rsatish"
    if layout in {"compare", "comparison", "before_after"} or _has(whole, "taqqoslash", "solishtirish", "farqlari", "afzallik va kamchilik", "versus", "compared with"):
        return "comparison", "Ikki yoki undan ortiq obyektni mezonlar bo'yicha solishtirish"
    if layout in {"chain", "process", "funnel", "swimlane"} or _has(whole, "bosqichlari", "jarayoni", "qanday ishlaydi", "workflow", "process flow", "supply chain"):
        return "process", "Jarayon yoki oqimni ketma-ket ko'rsatish"
    if layout in {"network", "hub", "orbit", "venn"} or _has(whole, "o'zaro bog'liq", "munosabatlar", "ishtirokchilar", "aloqalar", "tarkibiy qismlar"):
        return "relationship", "Obyektlar orasidagi asosli aloqalarni ko'rsatish"
    if _has(whole, "formula", "tenglama", "hisoblash", "formulasi", "equation"):
        return "formula", "Formula va uning belgilarini tushuntirish"
    if _has(whole, "tajriba", "eksperiment", "laboratoriya", "mikroskop", "hujayra", "anatomiya", "organ", "anatomy"):
        return "scientific_illustration", "Ilmiy obyekt yoki mexanizmni aniq illustratsiya qilish"
    if _has(whole, "qahramon", "personaj", "shaxs", "biografiya", "hayoti", "portret", "character", "biography"):
        return "subject_illustration", "Markaziy shaxs yoki personajni ko'rsatish"
    if _has(whole, "me'morchilik", "obida", "saroy", "masjid", "arxitektura", "architecture", "monument"):
        return "place_illustration", "Aniq joy yoki me'moriy obyektni ko'rsatish"
    if _has(whole, "iqtibos", "fikricha", "degan edi", "quote"):
        return "typography", "Iqtibos yoki asosiy fikrni tipografik urg'u bilan berish"
    if layout in {"collage", "image_story", "hero", "image_text", "text_image", "banner_cards", "split"}:
        return "photo", "Slayd mazmuniga mos fotografik dalil"
    return "photo", "Mazmunni aniq ifodalovchi kontekstual tasvir"


_COMPOSITIONS = {
    "map": ("map_caption", "editorial_split", "image_dominant"),
    "timeline": ("timeline", "editorial_rows", "magazine_spread"),
    "data": ("data_dashboard", "data_focus", "editorial_split"),
    "comparison": ("comparison_duel", "swiss_column", "asym_grid"),
    "process": ("process_lane", "isometric_stack", "swimlane"),
    "relationship": ("orbit_system", "matrix_priority", "editorial_rows"),
    "formula": ("oversized_numeral", "swiss_column", "editorial_split"),
    "scientific_illustration": ("image_dominant", "editorial_split", "layered"),
    "subject_illustration": ("cinematic_frame", "magazine_spread", "photo_triptych"),
    "place_illustration": ("cinematic_panorama", "image_dominant", "editorial_split"),
    "typography": ("typographic_poster", "negative_space", "editorial_masthead"),
    "photo": ("editorial_split", "asym_grid", "magazine_spread", "cinematic_frame"),
}


def build_visual_direction_guidance(topic, slide_count):
    """Prompt guidance for a slide-specific visual director, not a fixed visual template."""
    domain = classify_archetype(topic)
    return "\n".join([
        "UNIVERSAL VISUAL DIRECTOR — HAR BIR SLAYD UCHUN:",
        f"Mavzu arxitekturasi: {domain}. Barcha slaydga bir xil rasm yoki diagramma qolipini qo'llama.",
        "Har slayd uchun visual_type, visual_focus, photo_query yoki map_query (kerak bo'lsa), composition va visual_rationale maydonlarini mazmun asosida belgilagin.",
        "Vizual turi: photo, map, timeline, data, comparison, process, relationship, formula, scientific_illustration, subject_illustration, place_illustration yoki typography.",
        "Fotografiya faqat aniq obyekt, joy, shaxs yoki hodisani ko'rsatish uchun; mavzuga aloqasiz chiroyli stock foto ishlatma.",
        "Diagramma va grafiklar faqat slayddagi tasdiqlangan mazmunni ifodalasın; ma'lumot yo'q bo'lsa soxta raqam, foiz yoki o'q to'qima.",
        "Jarayonni flow/process, vaqtni timeline, makonni map, farqni comparison, sababiy yoki tizimli aloqani relationship diagram bilan ko'rsat.",
        "Ilmiy mavzularda aniq organ, hujayra, mexanizm yoki tajriba illustratsiyasi; tarixda davr, joy, artefakt va tarixiy shaxs; badiiy mavzuda personaj, sahna, buyum va olamga mos vizual tanla.",
        "Bitta slaydda bitta dominant vizual vazifa bo'lsin. Vizualni bezak sifatida emas, tushunishni osonlashtirish uchun ishlat.",
        "Ketma-ket slaydlarda bir xil visual_type va kompozitsiyani takrorlashdan qoch, lekin mazmun talab qilsa izchil qol.",
        "Agar ishonchli rasm topilmasa, noto'g'ri rasm bilan to'ldirma; mos diagramma yoki aniq belgilangan original illustratsiyaga o't.",
        f"Kontent slaydlari: {int(slide_count)}. Har bir slaydning vizual qarori uning o'z matni va story_role asosida bo'lsin.",
    ])


def build_visual_manifest(topic, slides):
    """Attach a deterministic, inspectable visual plan to each slide."""
    domain = classify_archetype(topic)
    counts = Counter()
    manifest = []
    for index, slide in enumerate(slides or [], start=1):
        if not isinstance(slide, dict):
            continue
        kind, rationale = _visual_kind(slide, topic)
        variant = counts[kind]
        counts[kind] += 1
        title = str(slide.get("title") or "").strip()
        # Keep queries short and grounded in the actual slide title and deck topic.
        query = " ".join(x for x in (title, str(topic or "").strip()) if x)
        query = re.sub(r"\s+", " ", query).strip()[:180]
        plan = {
            "slide": index,
            "domain": domain,
            "story_role": slide.get("story_role") or infer_story_role(slide),
            "visual_type": kind,
            "visual_focus": title or str(topic or "").strip(),
            "asset_query": query,
            "composition": _COMPOSITIONS[kind][variant % len(_COMPOSITIONS[kind])],
            "rationale": rationale,
            "requires_external_asset": kind in {"photo", "map", "scientific_illustration", "subject_illustration", "place_illustration"},
            "data_guard": kind == "data",
        }
        slide["_visual_plan"] = plan
        design = dict(slide.get("design") or {})
        design.setdefault("visual_type", kind)
        design.setdefault("visual_focus", plan["visual_focus"])
        design.setdefault("composition", plan["composition"])
        slide["design"] = design
        if kind == "map" and not slide.get("map_query"):
            slide["map_query"] = query
        elif plan["requires_external_asset"] and not slide.get("photo_query"):
            slide["photo_query"] = query
        manifest.append(plan)
    return {
        "schema_version": 1,
        "domain": domain,
        "slide_count": len(manifest),
        "visual_type_distribution": dict(counts),
        "slides": manifest,
    }


def critique_visual_manifest(manifest):
    """Return actionable planning warnings; it never claims that rendered slides passed QA."""
    manifest = manifest if isinstance(manifest, dict) else {}
    plans = manifest.get("slides") if isinstance(manifest.get("slides"), list) else []
    warnings = []
    types = [p.get("visual_type") for p in plans if isinstance(p, dict)]
    if len(types) >= 5:
        counts = Counter(types)
        for kind, count in counts.items():
            if count / len(types) > 0.60:
                warnings.append({"severity": "warning", "code": "visual_type_overuse",
                                 "visual_type": kind, "count": count, "slides": len(types)})
    seen = {}
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        index = plan.get("slide")
        if not plan.get("visual_focus"):
            warnings.append({"severity": "error", "code": "missing_visual_focus", "slide": index})
        query = _fold(plan.get("asset_query"))
        if plan.get("requires_external_asset") and not query:
            warnings.append({"severity": "error", "code": "missing_asset_query", "slide": index})
        if query and query in seen and plan.get("requires_external_asset"):
            warnings.append({"severity": "warning", "code": "duplicate_asset_query",
                             "slides": [seen[query], index]})
        elif query:
            seen[query] = index
        if plan.get("data_guard") and not plan.get("has_source_data"):
            # A data visual can still be an authored qualitative chart; the renderer must not invent numbers.
            warnings.append({"severity": "info", "code": "verify_data_before_chart", "slide": index})
    return warnings


def apply_visual_direction(topic, slides):
    manifest = build_visual_manifest(topic, slides)
    return manifest, critique_visual_manifest(manifest)
