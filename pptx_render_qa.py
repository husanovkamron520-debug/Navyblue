"""Headless PowerPoint-to-PNG rendering and deterministic visual preflight.

This validates that a PPTX can be rendered by LibreOffice and that each resulting
page is a real, decodable, non-empty image. It is a structural visual preflight,
not semantic image understanding or a substitute for human review.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat
from pptx import Presentation


class RenderQAError(RuntimeError):
    """Raised when a presentation cannot be rendered or its output is invalid."""


def _average_hash(image: Image.Image) -> int:
    """Return a compact 64-bit average hash for near-duplicate detection."""
    pixels = list(image.convert("L").resize((8, 8)).getdata())
    mean = sum(pixels) / max(1, len(pixels))
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= mean)
    return value


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def analyze_rendered_slides(
    image_paths, min_width: int = 960, min_height: int = 540,
    blank_stddev_threshold: float = 1.25,
) -> dict:
    """Inspect PNG decoding, resolution, near-blank pages and perceptual repeats."""
    slides = []
    issues = []
    warnings = []
    hashes = []

    for index, path in enumerate(image_paths, start=1):
        path = Path(path)
        try:
            with Image.open(path) as source:
                source.verify()
            with Image.open(path) as source:
                image = source.convert("RGB")
                width, height = image.size
                stat = ImageStat.Stat(image)
                stddev = round(sum(stat.stddev) / 3, 3)
                entropy = round(image.convert("L").entropy(), 3)
                digest = _average_hash(image)
        except Exception as exc:
            issues.append({"slide": index, "code": "invalid_png", "detail": type(exc).__name__})
            continue

        record = {
            "slide": index, "file": path.name, "width": width, "height": height,
            "mean_channel_stddev": stddev, "grayscale_entropy": entropy,
        }
        slides.append(record)
        if width < min_width or height < min_height:
            issues.append({
                "slide": index, "code": "low_resolution",
                "detail": f"{width}x{height}; minimum {min_width}x{min_height}",
            })
        if stddev < blank_stddev_threshold and entropy < 0.08:
            issues.append({"slide": index, "code": "near_blank_slide"})
        hashes.append((index, digest))

    duplicates = []
    for offset, (left_index, left_hash) in enumerate(hashes):
        for right_index, right_hash in hashes[offset + 1:]:
            distance = _hamming_distance(left_hash, right_hash)
            if distance <= 2:
                duplicates.append({
                    "slides": [left_index, right_index],
                    "hash_distance": distance,
                })
    if duplicates:
        warnings.append("Potentially repeated rendered slides detected; review the PNGs.")

    return {
        "slide_count": len(image_paths),
        "valid_png_count": len(slides),
        "slides": slides,
        "issues": issues,
        "duplicate_slide_pairs": duplicates,
        "warnings": warnings,
        "passed": not issues and len(slides) == len(image_paths),
    }


def _make_contact_sheet(image_paths, destination: Path, thumb_size=(480, 270)):
    if not image_paths:
        raise RenderQAError("No rendered slide images were produced.")
    columns = 2
    rows = (len(image_paths) + columns - 1) // columns
    gutter, label_h = 18, 28
    width = columns * thumb_size[0] + (columns + 1) * gutter
    height = rows * (thumb_size[1] + label_h) + (rows + 1) * gutter
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(image_paths):
        with Image.open(path) as source:
            thumb = source.convert("RGB")
            thumb.thumbnail(thumb_size)
        x = gutter + (index % columns) * (thumb_size[0] + gutter)
        y = gutter + (index // columns) * (thumb_size[1] + label_h + gutter)
        sheet.paste(thumb, (x, y))
        draw.text((x, y + thumb_size[1] + 5), f"Slide {index + 1}", fill="black")
    sheet.save(destination, format="PNG")


def render_pptx(pptx_path, output_dir, timeout: int = 120, dpi: int = 120) -> dict:
    """Render one PPTX to slide PNGs using LibreOffice and Poppler."""
    pptx_path = Path(pptx_path).resolve()
    output_dir = Path(output_dir).resolve()
    if not pptx_path.is_file() or pptx_path.suffix.lower() != ".pptx":
        raise RenderQAError(f"Input is not an existing .pptx file: {pptx_path}")
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    pdftoppm = shutil.which("pdftoppm")
    if not soffice or not pdftoppm:
        raise RenderQAError("Rendering requires LibreOffice (soffice) and Poppler (pdftoppm).")

    from pptx import Presentation
    expected_slides = len(Presentation(str(pptx_path)).slides)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="navyblue-render-") as temporary:
        temp = Path(temporary)
        pdf_dir = temp / "pdf"
        profile_dir = temp / "lo-profile"
        pdf_dir.mkdir()
        profile_dir.mkdir()
        command = [
            soffice, f"-env:UserInstallation={profile_dir.as_uri()}",
            "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir),
            str(pptx_path),
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False,
        )
        pdf_path = pdf_dir / f"{pptx_path.stem}.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            detail = (result.stderr or result.stdout or "LibreOffice produced no PDF")[-1500:]
            raise RenderQAError(f"LibreOffice conversion failed: {detail}")

        prefix = temp / "slide"
        raster = subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if raster.returncode != 0:
            detail = (raster.stderr or raster.stdout or "Poppler rasterization failed")[-1500:]
            raise RenderQAError(f"PNG conversion failed: {detail}")
        generated = sorted(temp.glob("slide-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        if len(generated) != expected_slides:
            raise RenderQAError(
                f"Rendered page count mismatch: expected {expected_slides}, got {len(generated)}"
            )
        image_paths = []
        for index, source in enumerate(generated, start=1):
            target = output_dir / f"slide-{index:02d}.png"
            shutil.copy2(source, target)
            image_paths.append(target)

    report = analyze_rendered_slides(image_paths)
    report.update({
        "input": pptx_path.name,
        "expected_slide_count": expected_slides,
        "renderer": "LibreOffice + Poppler",
        "dpi": dpi,
    })
    _make_contact_sheet(image_paths, output_dir / "contact-sheet.png")
    (output_dir / "render-qa.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if not report["passed"]:
        raise RenderQAError(
            f"Rendered visual preflight failed for {pptx_path.name}: {report['issues']}"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True, help="One or more PPTX files.")
    parser.add_argument("--output-dir", required=True, help="Directory for PNGs and QA reports.")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dpi", type=int, default=120)
    args = parser.parse_args()

    root = Path(args.output_dir)
    summaries = []
    for item in args.input:
        source = Path(item)
        destination = root / source.stem
        summaries.append(render_pptx(source, destination, args.timeout, args.dpi))
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps({
        "decks": len(summaries),
        "slides": sum(item["slide_count"] for item in summaries),
        "passed": all(item["passed"] for item in summaries),
        "output": str(root),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
