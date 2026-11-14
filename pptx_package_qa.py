"""Post-serialization QA for generated PowerPoint packages.

This is a read-only validation layer after python-pptx has serialized the deck.
It complements the renderer's per-slide repair logic; it never mutates OOXML.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from pptx import Presentation

MAX_PPTX_BYTES = 45 * 1024 * 1024
MAX_ZIP_ENTRIES = 4000
MAX_UNPACKED_BYTES = 120 * 1024 * 1024
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"p": P_NS, "a": A_NS}


class PPTXPackageError(ValueError):
    """The generated file is not safe or structurally valid as a PPTX."""


def inspect_pptx_bytes(data: bytes, expected_slides: int | None = None) -> dict:
    """Validate ZIP/XML/python-pptx readability and report slide-level defects."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise PPTXPackageError("PPTX fayli bo'sh")
    if len(data) > MAX_PPTX_BYTES:
        raise PPTXPackageError("PPTX fayli xavfsiz hajm chegarasidan katta")

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise PPTXPackageError(f"ZIP ichida buzilgan fayl: {bad_member[:100]}")
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise PPTXPackageError("PPTX ichida fayllar soni haddan tashqari ko'p")
            if sum(x.file_size for x in infos) > MAX_UNPACKED_BYTES:
                raise PPTXPackageError("PPTX ochilganda hajm chegarasidan oshadi")
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "ppt/presentation.xml"}
            if not required.issubset(names):
                raise PPTXPackageError("PPTX paketining majburiy qismlari topilmadi")
            slide_names = sorted(
                (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.search(r"(\d+)", n).group(1)),
            )
            if not slide_names:
                raise PPTXPackageError("PPTX ichida slayd topilmadi")
            morph_slides = []
            empty_slides = []
            out_of_bounds = []
            image_slides = 0
            slides_without_images = []
            duplicate_text_blocks = []
            numeric_truncations = []
            truncated_text_blocks = []
            text_fit_warnings = []
            presentation_root = ET.fromstring(archive.read("ppt/presentation.xml"))
            slide_size = presentation_root.find("p:sldSz", NS)
            slide_w = int(slide_size.get("cx", "12192000")) if slide_size is not None else 12192000
            slide_h = int(slide_size.get("cy", "6858000")) if slide_size is not None else 6858000
            for slide_name in slide_names:
                try:
                    root = ET.fromstring(archive.read(slide_name))
                except ET.ParseError as exc:
                    raise PPTXPackageError(f"Slayd XML buzilgan: {slide_name}") from exc
                transition = root.find(".//p:transition", NS)
                transition_xml = ET.tostring(transition, encoding="unicode") if transition is not None else ""
                if "morph" in transition_xml.casefold() or "p159/morph" in transition_xml.casefold():
                    morph_slides.append(slide_name)
                shapes = root.findall(".//p:sp", NS)
                pictures = root.findall(".//p:pic", NS)
                graphic_frames = root.findall(".//p:graphicFrame", NS)
                content_pictures = 0
                for picture in pictures:
                    xfrm = picture.find(".//a:xfrm", NS)
                    off = xfrm.find("a:off", NS) if xfrm is not None else None
                    ext = xfrm.find("a:ext", NS) if xfrm is not None else None
                    if ext is None:
                        content_pictures += 1
                        continue
                    try:
                        pw, ph = int(ext.get("cx", "0")), int(ext.get("cy", "0"))
                        if pw < slide_w * 0.96 or ph < slide_h * 0.96:
                            content_pictures += 1
                    except (TypeError, ValueError):
                        content_pictures += 1
                text_values = []
                paragraph_seen = set()
                content_shapes = 0
                for shape in shapes:
                    name_node = shape.find(".//p:cNvPr", NS)
                    shape_name = (name_node.get("name", "") if name_node is not None else "")
                    if shape_name.casefold().startswith("deco"):
                        continue
                    content_shapes += 1
                    text_values.extend((node.text or "").strip() for node in shape.findall(".//a:t", NS))
                    for paragraph in shape.findall(".//a:p", NS):
                        paragraph_text = " ".join(
                            (node.text or "").strip() for node in paragraph.findall(".//a:t", NS)
                        ).strip()
                        # Estimate text-box fit from OOXML geometry and font sizes.
                        # Warning-only: font metrics vary by Office renderer.
                        if paragraph_text:
                            try:
                                xfrm_fit = shape.find(".//a:xfrm", NS)
                                ext_fit = xfrm_fit.find("a:ext", NS) if xfrm_fit is not None else None
                                body_fit = shape.find(".//p:txBody/a:bodyPr", NS)
                                if ext_fit is not None:
                                    box_w_pt = int(ext_fit.get("cx", "0")) / 12700
                                    box_h_pt = int(ext_fit.get("cy", "0")) / 12700
                                    left_pt = int(body_fit.get("lIns", "91440")) / 12700 if body_fit is not None else 7.2
                                    right_pt = int(body_fit.get("rIns", "91440")) / 12700 if body_fit is not None else 7.2
                                    top_pt = int(body_fit.get("tIns", "45720")) / 12700 if body_fit is not None else 3.6
                                    bottom_pt = int(body_fit.get("bIns", "45720")) / 12700 if body_fit is not None else 3.6
                                    avail_w = max(1.0, box_w_pt - left_pt - right_pt)
                                    avail_h = max(1.0, box_h_pt - top_pt - bottom_pt)
                                    sizes = []
                                    for run in paragraph.findall(".//a:r", NS):
                                        props = run.find("a:rPr", NS)
                                        if props is not None and props.get("sz"):
                                            sizes.append(int(props.get("sz")) / 100)
                                    if not sizes:
                                        for props in (paragraph.find("a:pPr/a:defRPr", NS), paragraph.find("a:endParaRPr", NS)):
                                            if props is not None and props.get("sz"):
                                                sizes.append(int(props.get("sz")) / 100)
                                    if sizes:
                                        font_pt = max(sizes)
                                        chars_per_line = max(1, int(avail_w / max(1.0, font_pt * 0.52)))
                                        estimated_lines = max(1, (len(paragraph_text) + chars_per_line - 1) // chars_per_line)
                                        estimated_h = estimated_lines * font_pt * 1.25
                                        if estimated_h > avail_h * 1.18:
                                            text_fit_warnings.append({
                                                "slide": slide_name,
                                                "shape": shape_name[:80],
                                                "estimated_lines": estimated_lines,
                                                "font_pt": round(font_pt, 1),
                                                "estimated_height_pt": round(estimated_h, 1),
                                                "available_height_pt": round(avail_h, 1),
                                                "text": paragraph_text[:120],
                                            })
                            except (TypeError, ValueError, ZeroDivisionError):
                                pass
                        # Catch sentence fragments left at the end of a text block.
                        # This is a warning-only heuristic: it must never reject a deck.
                        if len(paragraph_text) >= 28:
                            trimmed = paragraph_text.rstrip()
                            if re.search(r"(?:…|\.{3,})\s*$", trimmed):
                                truncated_text_blocks.append({
                                    "slide": slide_name, "reason": "ellipsis", "text": trimmed[:160]
                                })
                            elif re.search(
                                r"\b(?:va|hamda|yoki|ammo|lekin|bilan|uchun|orqali|"
                                r"and|or|but|with|for|of|to)\s*[,:;]?\s*$",
                                trimmed, re.IGNORECASE
                            ):
                                truncated_text_blocks.append({
                                    "slide": slide_name, "reason": "dangling_connector", "text": trimmed[:160]
                                })
                        normalized = re.sub(r"\W+", " ", paragraph_text.casefold()).strip()
                        if len(normalized) >= 32:
                            if normalized in paragraph_seen:
                                duplicate_text_blocks.append({
                                    "slide": slide_name, "text": paragraph_text[:140]
                                })
                            else:
                                paragraph_seen.add(normalized)
                    xfrm = shape.find(".//a:xfrm", NS)
                    if xfrm is not None:
                        off = xfrm.find("a:off", NS)
                        ext = xfrm.find("a:ext", NS)
                        if off is not None and ext is not None:
                            try:
                                x, y = int(off.get("x", "0")), int(off.get("y", "0"))
                                w, h = int(ext.get("cx", "0")), int(ext.get("cy", "0"))
                                # Allow a small bleed for intentional decorative geometry.
                                if x < -180000 or y < -180000 or x + w > slide_w + 180000 or y + h > slide_h + 180000:
                                    out_of_bounds.append({"slide": slide_name, "shape": shape_name[:80]})
                            except (TypeError, ValueError):
                                pass
                if not content_shapes and not content_pictures and not graphic_frames:
                    empty_slides.append(slide_name)
                # Ignore full-bleed background pictures: only content-sized images
                # count as meaningful slide visuals in the coverage metric.
                if content_pictures:
                    image_slides += 1
                else:
                    slides_without_images.append(slide_name)
                for value in text_values:
                    if re.search(r"\d[\d,. ]*\s*(?:…|\.{3,})\s*$", value):
                        numeric_truncations.append({"slide": slide_name, "text": value[:120]})

    except zipfile.BadZipFile as exc:
        raise PPTXPackageError("Fayl ZIP/PPTX formatida emas yoki buzilgan") from exc

    try:
        presentation = Presentation(io.BytesIO(data))
        parsed_count = len(presentation.slides)
    except Exception as exc:
        raise PPTXPackageError(f"PowerPoint parser faylni o'qiy olmadi: {type(exc).__name__}") from exc

    if parsed_count != len(slide_names):
        raise PPTXPackageError("PPTX slaydlar ro'yxati va XML soni mos emas")
    if expected_slides is not None and parsed_count != int(expected_slides):
        raise PPTXPackageError(
            f"Slaydlar soni mos emas: kutilgan {expected_slides}, topilgan {parsed_count}"
        )
    if parsed_count < 2:
        raise PPTXPackageError("Taqdimotda muqova va kontent uchun kamida 2 slayd bo'lishi kerak")

    report = {
        "valid": True,
        "bytes": len(data),
        "slides": parsed_count,
        "morph_slides": len(morph_slides),
        "morph_slide_names": morph_slides[:20],
        "image_slides": image_slides,
        "image_coverage_ratio": round(image_slides / max(1, parsed_count), 3),
        "slides_without_images": slides_without_images[:40],
        "duplicate_text_blocks": duplicate_text_blocks[:40],
        "numeric_truncations": numeric_truncations[:20],
        "truncated_text_blocks": truncated_text_blocks[:40],
        "text_fit_warnings": text_fit_warnings[:40],
        "empty_slides": empty_slides,
        "out_of_bounds_shapes": out_of_bounds[:30],
        "warnings": [],
    }
    if empty_slides:
        report["warnings"].append(f"{len(empty_slides)} ta bo'sh slayd")
    if report["image_coverage_ratio"] < 0.35:
        report["warnings"].append(
            "Rasmli slaydlar ulushi past: {}/{} ({}%)".format(
                image_slides, parsed_count, round(report["image_coverage_ratio"] * 100)
            )
        )
    if duplicate_text_blocks:
        report["warnings"].append(f"{len(duplicate_text_blocks)} ta slaydda takrorlangan matn bloki")
    if numeric_truncations:
        report["warnings"].append(f"{len(numeric_truncations)} ta raqamli matn uch nuqta bilan kesilgan")
    if truncated_text_blocks:
        report["warnings"].append(
            f"{len(truncated_text_blocks)} ta matn bloki tugallanmagan jumla yoki ellipsis bilan tugaydi"
        )
    if text_fit_warnings:
        report["warnings"].append(f"{len(text_fit_warnings)} ta matn qutisida matn sig'masligi mumkin")
    if out_of_bounds:
        report["warnings"].append(f"{len(out_of_bounds)} ta obyekt slayd chegarasidan chiqishi mumkin")
    return report
