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
    "fantasy_fiction": {"fantasy", "magical", "magic", "myth", "creative", "portfolio", "story"},
    "historical_chronicle": {"history", "historical", "heritage", "chronicle", "story"},
    "process_system": {"business", "project", "planning", "process", "strategy", "logistics", "data"},
    "research_evidence": {"academic", "thesis", "research", "data", "charts", "infographic", "philosophy", "humanities", "ethics", "logic"},
    "science_and_technology": {"technology", "science", "engineering", "ai", "product", "software"},
    "medical_education": {"medical", "health", "clinical", "biology", "anatomy", "medicine", "wellness"},
    "arts_culture": {"creative", "portfolio", "art", "culture", "design", "editorial", "photography"},
    "geography_environment": {"nature", "environment", "sustainability", "ecology", "travel", "geography"},
    "civic_policy": {"government", "policy", "public", "civic", "law", "politics", "community"},
    "finance_accounting": {"finance", "accounting", "budget", "economics", "investment", "financial"},
    "educational_method": {"education", "classroom", "lesson", "academic", "learning", "teaching"},
    "concept_explainer": {"general", "minimal", "aesthetic", "education", "infographic"},

}

_TOPIC_ARCHETYPE_KEYWORDS = {
    "research_evidence": ("falsafa", "falsafiy", "philosoph", "tadqiqot", "ilmiy", "nazariya", "bilish"),
    "historical_chronicle": ("tarix", "tarixiy", "imperiya", "sulola", "usmonli", "ottoman"),
    "process_system": ("logistika", "ta'minot", "zanjir", "transport", "supply chain"),
    "finance_accounting": ("iqtisod", "moliya", "byudjet", "budjet", "hisob", "bank", "investitsiya"),
    "medical_education": ("tibbiyot", "yurak", "qon tomir", "anatomiya", "kasallik", "sog'liq"),
    "science_and_technology": ("biologiya", "klonlash", "texnologiya", "sun'iy intellekt", "robot"),
    "fantasy_fiction": ("sehr", "fantasy", "harry potter", "remus", "lupin", "fantastika"),
    "arts_culture": ("san'at", "madaniyat", "adabiyot", "she'riyat", "musiqa"),
}

_TOPIC_TERM_ALIASES = {
    "research_evidence": {"philosophy", "humanities", "ethics", "logic", "academic", "research"},
    "historical_chronicle": {"history", "historical", "empire", "heritage", "chronicle"},
    "process_system": {"logistics", "supply", "chain", "transportation", "operations"},
    "finance_accounting": {"economics", "finance", "accounting", "budget", "investment"},
    "medical_education": {"medical", "health", "clinical", "biology", "anatomy", "medicine"},
    "science_and_technology": {"science", "biology", "genetics", "technology", "engineering", "ai"},
    "fantasy_fiction": {"fantasy", "fiction", "magical", "magic", "myth", "story"},
    "arts_culture": {"art", "culture", "literature", "poetry", "music", "creative"},
}


def _infer_template_archetype(topic: str, fallback: str) -> str:
    low = str(topic or "").casefold()
    for archetype, keywords in _TOPIC_ARCHETYPE_KEYWORDS.items():
        if any(keyword in low for keyword in keywords):
            return archetype
    return fallback


def _topic_terms(topic: str, archetype: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", str(topic or "").casefold()))
    words.update(_TOPIC_TERM_ALIASES.get(archetype, set()))
    return words

def _safe_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise ValueError("Template URL host is not allowlisted")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in template URLs are not allowed")
    return url

class _AllowlistedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def _read_url(url: str, allowed_hosts: set[str], limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Navyblue-PPT-Template-Library/1.0"})
    opener = urllib.request.build_opener(_AllowlistedRedirect(allowed_hosts))
    with opener.open(request, timeout=8) as response:
        _safe_url(response.geturl(), allowed_hosts)
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
    archetype = _infer_template_archetype(topic, archetype)
    terms = _PROFILE_TERMS.get(archetype, _PROFILE_TERMS["concept_explainer"])
    topic_words = _topic_terms(topic, archetype)
    ranked = []
    for item in items:
        tags = set()
        for tag in (item.get("tags") or []):
            tags.update(re.findall(r"[a-z0-9]+", str(tag).casefold()))
        title_words = set(re.findall(r"[a-z0-9]+", str(item.get("title") or "").casefold()))
        topic_overlap = len(topic_words & (tags | title_words))
        # A generic archetype match is not enough: require at least one topic-relevant term.
        if not topic_overlap:
            continue
        score = 3 * len(tags & terms) + 2 * topic_overlap
        if score:
            ranked.append((score, str(item.get("slug") or item.get("title") or ""), item))
    if not ranked:
        return None
    # Keep selection stable for the same topic, but rotate among equally strong
    # references instead of always choosing the alphabetically first template.
    ranked.sort(key=lambda row: (-row[0], row[1]))
    best_score = ranked[0][0]
    shortlist = [row for row in ranked if row[0] >= best_score - 1][:12]
    seed = hashlib.sha256(str(topic).casefold().encode("utf-8")).digest()
    chosen = dict(shortlist[int.from_bytes(seed[:4], "big") % len(shortlist)][2])
    # The source repository LICENSE explicitly covers every listed PPTX and preview image.
    chosen["license"] = "CC BY 4.0"
    chosen["license_verified_from_source_license"] = True
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
    if (str(item.get("license") or "").upper() not in {"CC BY 4.0", "CC-BY-4.0", "CC BY 4.0 (CREATIVE COMMONS)"}
            or item.get("license_verified_from_source_license") is not True):
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
        checked = _validate_pptx_archive(_zip_bytes(path))
        checked.close()
        names = archive.namelist()
        slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        morph_slides = []
        image_only = 0
        slide_ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
        for slide_name in slides:
            root = ET.fromstring(archive.read(slide_name))
            transition = root.find(".//p:transition", slide_ns)
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
