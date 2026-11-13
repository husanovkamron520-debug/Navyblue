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
MAX_UNPACKED_BYTES = 220 * 1024 * 1024
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
                (n for n in names if re.fullmatch(r"ppt/slides/slide\\d+\\.xml", n)),
                key=lambda n: int(re.search(r"(\\d+)", n).group(1)),
            )
            if not slide_names:
                raise PPTXPackageError("PPTX ichida slayd topilmadi")
            morph_slides = []
            xml_errors = []
            empty_slides = []
            out_of_bounds = []
            image_slides = 0
            for slide_name in slide_names:
                try:
                    root = ET.fromstring(archive.read(slide_name))
                except ET.ParseError as exc:
                    raise PPTXPackageError(f"Slayd XML buzilgan: {slide_name}") from exc
                transition = root.find("p:transition", NS)
                transition_xml = ET.tostring(transition, encoding="unicode") if transition is not None else ""
                if "morph" in transition_xml.casefold() or "p159/morph" in transition_xml.casefold():
                    morph_slides.append(slide_name)
                shapes = root.findall(".//p:sp", NS)
                pictures = root.findall(".//p:pic", NS)
                graphic_frames = root.findall(".//p:graphicFrame", NS)
                text_values = []
                for shape in shapes:
                    name_node = shape.find(".//p:cNvPr", NS)
                    shape_name = (name_node.get("name", "") if name_node is not None else "")
                    if shape_name.casefold().startswith("deco"):
                        continue
                    text_values.extend((node.text or "").strip() for node in shape.findall(".//a:t", NS))
                    xfrm = shape.find(".//a:xfrm", NS)
                    if xfrm is not None:
                        off = xfrm.find("a:off", NS)
                        ext = xfrm.find("a:ext", NS)
                        if off is not None and ext is not None:
                            try:
                                x, y = int(off.get("x", "0")), int(off.get("y", "0"))
                                w, h = int(ext.get("cx", "0")), int(ext.get("cy", "0"))
                                # Allow a small bleed for intentional decorative geometry.
                                if x < -180000 or y < -180000 or x + w > 12240000 or y + h > 7030000:
                                    out_of_bounds.append({"slide": slide_name, "shape": shape_name[:80]})
                            except (TypeError, ValueError):
                                pass
                if not any(text_values) and not pictures and not graphic_frames:
                    empty_slides.append(slide_name)
                if pictures:
                    image_slides += 1

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
        "empty_slides": empty_slides,
        "out_of_bounds_shapes": out_of_bounds[:30],
        "warnings": [],
    }
    if empty_slides:
        report["warnings"].append(f"{len(empty_slides)} ta bo'sh slayd")
    if out_of_bounds:
        report["warnings"].append(f"{len(out_of_bounds)} ta obyekt slayd chegarasidan chiqishi mumkin")
    return report
