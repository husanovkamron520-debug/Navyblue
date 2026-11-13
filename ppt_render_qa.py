"""Optional rendered-slide QA using LibreOffice + Poppler (or PyMuPDF).

The package-level validator remains authoritative when no local renderer exists.
This module never silently treats a skipped render as a visual pass.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def inspect_rendered_images(image_paths):
    """Inspect rendered slide PNGs for blank output, low visual signal and duplicates."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {"status": "unavailable", "slides_rendered": 0, "blockers": [],
                "warnings": [{"code": "pillow_missing"}]}

    paths = [Path(x) for x in image_paths if Path(x).is_file()]
    if not paths:
        return {"status": "error", "slides_rendered": 0, "blockers": [],
                "warnings": [{"code": "no_rendered_slides"}]}

    blockers, warnings = [], []
    fingerprints = {}
    for index, path in enumerate(paths, start=1):
        try:
            with Image.open(path) as source:
                image = source.convert("RGB")
                width, height = image.size
                if width < 640 or height < 360:
                    warnings.append({"slide": index, "code": "low_render_resolution",
                                     "width": width, "height": height})
                gray = image.convert("L")
                stats = ImageStat.Stat(gray)
                stddev = float(stats.stddev[0])
                if stddev < 1.0:
                    blockers.append({"slide": index, "code": "visually_blank_slide",
                                     "message": "Rendered slide has almost no visible pixel variation"})
                elif stddev < 4.0:
                    warnings.append({"slide": index, "code": "very_low_visual_signal",
                                     "stddev": round(stddev, 2)})
                thumb = gray.resize((64, 36))
                fingerprint = hashlib.sha256(thumb.tobytes()).hexdigest()
                if fingerprint in fingerprints:
                    warnings.append({"slide": index, "code": "duplicate_rendered_slide",
                                     "matches_slide": fingerprints[fingerprint]})
                else:
                    fingerprints[fingerprint] = index
        except Exception as exc:
            warnings.append({"slide": index, "code": "rendered_image_unreadable",
                             "detail": f"{type(exc).__name__}: {str(exc)[:160]}"})

    return {
        "status": "rendered",
        "slides_rendered": len(paths),
        "blockers": blockers,
        "warnings": warnings,
        "passed": not blockers,
    }


def build_contact_sheets(image_paths, slides_per_sheet: int = 16, columns: int = 4):
    """Build labeled slide thumbnails for a separate multimodal visual critic."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return []
    paths = [Path(x) for x in image_paths if Path(x).is_file()]
    if not paths:
        return []
    thumb_w, thumb_h, label_h = 480, 270, 34
    sheets = []
    for start in range(0, len(paths), max(1, slides_per_sheet)):
        chunk = paths[start:start + max(1, slides_per_sheet)]
        rows = (len(chunk) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), (18, 24, 34))
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 18)
        except Exception:
            font = ImageFont.load_default()
        for offset, path in enumerate(chunk):
            with Image.open(path) as source:
                thumb = source.convert("RGB")
                thumb.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            x = (offset % columns) * thumb_w
            y = (offset // columns) * (thumb_h + label_h)
            draw.rectangle((x, y, x + thumb_w, y + label_h), fill=(35, 48, 66))
            draw.text((x + 12, y + 7), f"SLIDE {start + offset + 1}", font=font, fill=(245, 245, 245))
            sheet.paste(thumb, (x, y + label_h))
        import io
        buffer = io.BytesIO()
        sheet.save(buffer, format="PNG", optimize=True)
        sheets.append({"start_slide": start + 1, "end_slide": start + len(chunk), "png": buffer.getvalue()})
    return sheets


def render_and_inspect_pptx(data: bytes, timeout: int = 60, dpi: int = 96, include_contact_sheets: bool = False):
    """Render PPTX pages to PNG and inspect them; return skipped if renderer is absent."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        return {"status": "error", "slides_rendered": 0, "blockers": [],
                "warnings": [{"code": "empty_pptx_input"}]}

    office = shutil.which("libreoffice") or shutil.which("soffice")
    if not office:
        return {"status": "skipped", "reason": "LibreOffice/soffice is not installed",
                "slides_rendered": 0, "blockers": [], "warnings": []}

    pdftoppm = shutil.which("pdftoppm")
    try:
        import fitz  # PyMuPDF, optional fallback
    except ImportError:
        fitz = None
    if not pdftoppm and fitz is None:
        return {"status": "skipped", "reason": "Neither pdftoppm nor PyMuPDF is installed",
                "slides_rendered": 0, "blockers": [], "warnings": []}

    with tempfile.TemporaryDirectory(prefix="navyblue-ppt-render-") as temp:
        root = Path(temp)
        pptx_path = root / "deck.pptx"
        pptx_path.write_bytes(bytes(data))
        try:
            result = subprocess.run(
                [office, "--headless", "--convert-to", "pdf", "--outdir", str(root), str(pptx_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "error", "slides_rendered": 0, "blockers": [],
                    "warnings": [{"code": "office_render_timeout", "timeout_seconds": timeout}]}
        pdf_path = root / "deck.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            detail = (result.stderr or result.stdout).decode("utf-8", "replace")[:500]
            return {"status": "error", "slides_rendered": 0, "blockers": [],
                    "warnings": [{"code": "office_pdf_conversion_failed", "detail": detail}]}

        image_paths = []
        if pdftoppm:
            prefix = root / "slide"
            try:
                converted = subprocess.run(
                    [pdftoppm, "-png", "-r", str(int(dpi)), str(pdf_path), str(prefix)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
                )
            except subprocess.TimeoutExpired:
                return {"status": "error", "slides_rendered": 0, "blockers": [],
                        "warnings": [{"code": "pdf_raster_timeout", "timeout_seconds": timeout}]}
            if converted.returncode != 0:
                detail = (converted.stderr or converted.stdout).decode("utf-8", "replace")[:500]
                return {"status": "error", "slides_rendered": 0, "blockers": [],
                        "warnings": [{"code": "pdf_raster_failed", "detail": detail}]}
            image_paths = sorted(root.glob("slide-*.png"))
        else:
            image_paths = []
            document = fitz.open(pdf_path)
            try:
                for index, page in enumerate(document, start=1):
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                    image_path = root / f"slide-{index:04d}.png"
                    pixmap.save(str(image_path))
                    image_paths.append(image_path)
            finally:
                document.close()

        report = inspect_rendered_images(image_paths)
        report["renderer"] = Path(office).name
        report["rasterizer"] = "pdftoppm" if pdftoppm else "pymupdf"
        if include_contact_sheets:
            report["contact_sheets"] = build_contact_sheets(image_paths)
        return report
