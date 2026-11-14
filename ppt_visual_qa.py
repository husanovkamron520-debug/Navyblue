"""Pre-delivery checks for required slide visuals and serialized PPTX structure."""
from __future__ import annotations


class VisualIntegrityError(RuntimeError):
    """Raised when a required visual slot or serialized slide is structurally empty."""


HARD_SLIDE_ISSUES = frozenset({
    "xato",
    "chegaradan chiqdi",
    "matn sig'madi",
    "mazmun bo'sh",
    "mazmun kam",
    "matnlar ustma-ust tushdi",
    "matn va rasm ustma-ust tushdi",
})


def is_decorative_shape_name(name):
    """Recognize intentionally bleeding decorative geometry by normalized OOXML name."""
    normalized = str(name or "").casefold().lstrip("!").strip()
    return normalized.startswith(("deco", "orb", "orbit"))


def content_slide_target(total_slides, has_references=False, has_executive=False):
    """The selected count is the final deck total; reserve cover and optional final/summary slides."""
    reserved = 1 + int(bool(has_references)) + int(bool(has_executive))
    return max(1, int(total_slides) - reserved)


def hard_slide_issues(issues):
    """Return high-confidence layout issues that require repair or block delivery."""
    return sorted({str(issue) for issue in (issues or [])} & HARD_SLIDE_ISSUES)


def visual_integrity_issues(slides, image_layouts, valid_image):
    """Return required visual slots that remain empty or contain invalid image bytes."""
    issues = []
    for index, slide in enumerate(slides or [], start=1):
        if not isinstance(slide, dict):
            continue
        layout = slide.get("layout")
        if layout not in image_layouts:
            continue
        if layout == "collage":
            images = slide.get("_imgs") or []
            valid = [image for image in images if valid_image(image)]
            if len(valid) < 3:
                issues.append({
                    "slide": index,
                    "layout": layout,
                    "reason": "collage_requires_three_valid_images",
                    "valid_images": len(valid),
                })
        elif not valid_image(slide.get("_img")):
            issues.append({
                "slide": index,
                "layout": layout,
                "reason": "missing_or_invalid_image",
            })
    return issues


def package_qa_blockers(report):
    """Block only high-confidence structural/content failures; leave fuzzy fit warnings diagnostic."""
    report = report if isinstance(report, dict) else {}
    blockers = ["empty slide: " + str(item) for item in (report.get("empty_slides") or [])]
    blockers.extend("numeric truncation: " + str(item.get("slide", "unknown"))
                    for item in (report.get("numeric_truncations") or []) if isinstance(item, dict))
    blockers.extend("unfinished sentence: " + str(item.get("slide", "unknown"))
                    for item in (report.get("truncated_text_blocks") or [])
                    if isinstance(item, dict) and item.get("reason") == "dangling_connector")
    blockers.extend("out-of-bounds shape: " + str(item.get("slide", "unknown"))
                    for item in (report.get("out_of_bounds_shapes") or []) if isinstance(item, dict))
    # Geometry-based estimates vary across PowerPoint renderers; block only extreme overflow.
    for item in (report.get("text_fit_warnings") or []):
        if not isinstance(item, dict):
            continue
        try:
            estimated = float(item.get("estimated_height_pt", 0))
            available = float(item.get("available_height_pt", 0))
        except (TypeError, ValueError):
            continue
        if available > 0 and estimated > available * 1.5:
            blockers.append("severe text overflow: " + str(item.get("slide", "unknown")))
    return blockers
