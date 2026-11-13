"""Curated, license-aware PowerPoint design-reference library.

The catalog decks are downloaded only as design references. They are NOT treated as
Morph sources unless inspection proves that they contain Morph transitions. The
project's own editable renderer remains responsible for generated slide content.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

CATALOG_URL = "https://raw.githubusercontent.com/ai-ppt-template/free-ppt-template/main/index.json"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
SOURCE_REPO = "https://github.com/ai-ppt-template/free-ppt-template"
ALLOWED_CDN_HOSTS = {"cdn.ppttemplate.ai"}
ALLOWED_CATALOG_HOSTS = {"raw.githubusercontent.com"}
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 180 * 1024 * 1024
MAX_ZIP_ENTRIES = 2500
CACHE_DIR = Path(os.environ.get("PPT_TEMPLATE_CACHE", "/tmp/navyblue_ppt_templates"))

_PROFILE_TERMS = {
    "fantasy_fiction": {"fantasy", "fantasy", "magical", "magic", "myth", "creative", "portfolio", "story"},
    "historical_chronicle": {"history", "historical", "heritage", "chronicle", "story"},
    "process_system": {"business", "project", "planning", "process", "strategy", "logistics", "data"},
    "research_evidence": {"academic", "thesis", "research", "data", "charts", "infographic"},
    "science_and_technology": {"technology", "science", "engineering", "ai", "product"},
    "educational_method": {"education", "classroom", "lesson", "academic", "learning"},
    "concept_explainer": {"general", "minimal", "aesthetic", "education", "infographic"},
}

def _safe_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise ValueError("Template URL host is not allowlisted")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in template URLs are not allowed")
    return url

def _read_url(url: str, allowed_hosts: set[str], limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Navyblue-PPT-Template-Library/1.0"})
    with urllib.request.urlopen(request, timeout=18) as response:
        final_url = _safe_url(response.geturl(), allowed_hosts)
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise ValueError("Remote template exceeds size limit")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Remote template exceeds size limit")
    return data

def load_catalog(cache_dir: Path | str = CACHE_DIR, force: bool = False) -> list[dict]:
    """Load the CC BY 4.0 catalog index, with a local cache and strict URL checks."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "catalog-index.json"
    if force or not path.exists():
        data = _read_url(_safe_url(CATALOG_URL, ALLOWED_CATALOG_HOSTS),
                         ALLOWED_CATALOG_HOSTS, 12 * 1024 * 1024)
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Unexpected template catalog format")
        path.write_text(json.dumps(payload), encoding="utf-8")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in payload if isinstance(item, dict) and item.get("pptx_url")]

def choose_design_reference(topic: str, archetype: str = "concept_explainer",
                            catalog: list[dict] | None = None) -> dict | None:
    """Choose a design reference by archetype/tags; deterministic and topic-aware."""
    items = catalog if catalog is not None else load_catalog()
    terms = _PROFILE_TERMS.get(archetype, _PROFILE_TERMS["concept_explainer"])
    topic_words = set(re.findall(r"[a-z0-9]+", str(topic).casefold()))
    ranked = []
    for item in items:
        tags = {str(x).casefold() for x in (item.get("tags") or [])}
        title_words = set(re.findall(r"[a-z0-9]+", str(item.get("title") or "").casefold()))
        score = 3 * len(tags & terms) + len(topic_words & title_words)
        if score:
            ranked.append((score, str(item.get("slug") or item.get("title") or ""), item))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (-row[0], row[1]))
    chosen = dict(ranked[0][2])
    chosen["license"] = "CC BY 4.0"
    chosen["license_url"] = LICENSE_URL
    chosen["attribution"] = "Template design reference by ppttemplate.ai (CC BY 4.0); adapted for Navyblue."
    chosen["use"] = "design_reference_only"
    return chosen

def _validate_pptx_archive(data: bytes) -> zipfile.ZipFile:
    import io
    archive = zipfile.ZipFile(io.BytesIO(data))
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ValueError("PPTX archive contains too many entries")
    total = sum(info.file_size for info in infos)
    if total > MAX_UNPACKED_BYTES:
        raise ValueError("PPTX archive expands beyond the safety limit")
    names = set(archive.namelist())
    if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
        raise ValueError("Downloaded file is not a valid PPTX package")
    return archive

def download_design_reference(item: dict, cache_dir: Path | str = CACHE_DIR) -> Path:
    """Download a catalog PPTX after checking its source, license and archive bounds."""
    if str(item.get("license") or "").upper() not in {"CC BY 4.0", "CC-BY-4.0", "CC BY 4.0 (CREATIVE COMMONS)"}:
        raise ValueError("A verified CC BY 4.0 license is required")
    url = _safe_url(item.get("pptx_url", ""), ALLOWED_CDN_HOSTS)
    data = _read_url(url, ALLOWED_CDN_HOSTS, MAX_DOWNLOAD_BYTES)
    archive = _validate_pptx_archive(data)
    archive.close()
    digest = hashlib.sha256(data).hexdigest()
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(item.get("slug") or item.get("title") or "template").casefold()).strip("-")[:70]
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{slug}-{digest[:12]}.pptx"
    if not target.exists():
        fd, temp_name = tempfile.mkstemp(prefix="ppt-template-", suffix=".pptx", dir=str(cache))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    return target

def inspect_pptx(path: str | Path) -> dict:
    """Inspect package integrity, Morph transitions and image-heavy slide ratio."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        _validate_pptx_archive(archive.read_bytes() if hasattr(archive, "read_bytes") else _zip_bytes(path))
        names = archive.namelist()
        slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\\d+\\.xml", n)),
                        key=lambda n: int(re.search(r"(\\d+)", n).group(1)))
        morph_slides = []
        image_only = 0
        slide_ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
        for slide_name in slides:
            root = ET.fromstring(archive.read(slide_name))
            transition = root.find("p:transition", slide_ns)
            transition_xml = ET.tostring(transition, encoding="unicode") if transition is not None else ""
            if "morph" in transition_xml.casefold():
                morph_slides.append(slide_name)
            shapes = root.findall(".//p:sp", slide_ns)
            pictures = root.findall(".//p:pic", slide_ns)
            if pictures and not shapes:
                image_only += 1
        return {
            "slide_count": len(slides),
            "morph_slide_count": len(morph_slides),
            "has_morph": bool(morph_slides),
            "morph_slides": morph_slides,
            "image_only_slide_count": image_only,
            "image_only_ratio": round(image_only / max(1, len(slides)), 3),
            "is_morph_source": bool(morph_slides),
            "path": str(path),
        }

def _zip_bytes(path: Path) -> bytes:
    return path.read_bytes()

def build_template_guidance(topic: str, archetype: str, item: dict | None = None,
                            inspection: dict | None = None) -> str:
    """Prompt-safe guidance: use inspiration, never copy irrelevant slide content."""
    if not item:
        return "TEMPLATE REFERENCE: use the original Navyblue design system; vary composition by slide."
    lines = [
        "LICENSED DESIGN REFERENCE (CC BY 4.0):",
        f"Reference: {item.get('title', 'Untitled')}.",
        "Use only its visual hierarchy, palette, spacing and composition as inspiration.",
        "Do not copy its wording, topic-specific claims, logos, people, photos or unrelated illustrations.",
        "Rebuild the design with editable native PowerPoint shapes and topic-relevant/licensed visuals.",
        "Credit: Template design reference by ppttemplate.ai (CC BY 4.0); adapted for Navyblue.",
    ]
    if inspection:
        if inspection.get("has_morph"):
            lines.append("Verified: this PPTX contains Morph transitions; preserve them only if slide continuity is rebuilt safely.")
        else:
            lines.append("Important: this PPTX has no verified Morph transition; keep Navyblue's own Morph engine for motion.")
        if inspection.get("image_only_ratio", 0) > 0.5:
            lines.append("The reference is image-heavy; do not reuse full-slide raster images as editable layouts.")
    return "\n".join(lines)
