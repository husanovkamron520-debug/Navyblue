"""Pre-delivery checks for required slide visuals and serialized PPTX structure."""
from __future__ import annotations


class VisualIntegrityError(RuntimeError):
    """Raised when a required visual slot or serialized slide is structurally empty."""


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
