"""Wikimedia Commons image fallback for Navyblue presentations.

Only accepts public-domain, CC0, and attribution-based Creative Commons assets.
Every returned asset includes creator, license, and source-page attribution.
"""
import html
import json
import logging
import re
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)
_USER_AGENT = "NavybluePresentationBot/1.0 (presentation image retrieval)"
_MAX_BYTES = 12 * 1024 * 1024


def _metadata_value(metadata, key):
    item = metadata.get(key) or {}
    value = item.get("value", "") if isinstance(item, dict) else str(item or "")
    value = re.sub(r"<[^>]+>", " ", str(value))
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _allowed_license(name):
    value = re.sub(r"\s+", " ", str(name or "")).strip().casefold()
    if not value or any(term in value for term in ("noncommercial", "non-commercial", "no derivatives", "no-derivatives", "nc", "nd")):
        return False
    return (
        value.startswith(("cc0", "pdm", "public domain"))
        or bool(re.match(r"^cc by(?:-sa)?(?:\s|$)", value))
    )


def find_commons_photo(query, used, valid_image):
    """Search Commons and return (bytes, credit, provider), or None."""
    query = str(query or "").strip()[:160]
    if not query:
        return None
    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": "filetype:bitmap " + query,
        "gsrnamespace": 6,
        "gsrlimit": 18,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1600,
        "format": "json",
    })
    request = urllib.request.Request(
        "https://commons.wikimedia.org/w/api.php?" + params,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Wikimedia Commons qidiruv xatosi: %s", exc)
        return None

    pages = list((payload.get("query") or {}).get("pages", {}).values())
    pages.sort(key=lambda page: int(page.get("index", 999999)))
    for page in pages:
        page_id = str(page.get("pageid") or "")
        used_key = "wc:" + page_id
        if not page_id or used_key in used:
            continue
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        mime = str(info.get("mime") or "").lower()
        if mime not in {"image/jpeg", "image/png"}:
            continue
        metadata = info.get("extmetadata") or {}
        license_name = _metadata_value(metadata, "LicenseShortName")
        if not _allowed_license(license_name):
            continue
        image_url = info.get("thumburl") or info.get("url")
        if not image_url:
            continue
        try:
            image_request = urllib.request.Request(
                image_url, headers={"User-Agent": _USER_AGENT}
            )
            with urllib.request.urlopen(image_request, timeout=35) as response:
                raw = response.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES or not valid_image(raw):
                continue
        except Exception as exc:
            logger.warning("Wikimedia Commons rasmi yuklanmadi (%s): %s", page_id, exc)
            continue

        title = str(page.get("title") or "Untitled").removeprefix("File:")
        creator = _metadata_value(metadata, "Artist") or "Creator not listed"
        license_url = _metadata_value(metadata, "LicenseUrl")
        source_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            str(page.get("title") or "").replace(" ", "_"), safe="()"
        )
        credit = f'"{title}" — {creator}; {license_name}'
        if license_url:
            credit += f" ({license_url})"
        credit += f" — {source_url}"
        used.add(used_key)
        logger.info("Wikimedia Commons rasm olindi: query=%r pageid=%s license=%s", query, page_id, license_name)
        return raw, credit, "Wikimedia Commons"
    return None
