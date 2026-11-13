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
    """Only structural failures block delivery; heuristic warnings remain visible diagnostics."""
    report = report if isinstance(report, dict) else {}
    return list(report.get("empty_slides") or [])
