"""Independent, deterministic content critic for universal PPTX outlines.

This pass checks structure and repetition without pretending to fact-check claims
against sources. It never rewrites slide text or invents replacement facts.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ppt_visual_director import classify_visual_domain


_GENERIC_TITLES = {
    "kirish", "xulosa", "muammo", "yechim", "natija", "reja", "introduction",
    "conclusion", "problem", "solution", "results", "overview", "agenda",
}
_METRIC_RE = re.compile(r"(?<!\w)(?:\d+(?:[.,]\d+)?\s*%|\d+(?:[.,]\d+)?\s*(?:ta|foiz|million|billion|mln|mlrd))", re.I)


def _fold(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _content(slide):
    parts = []
    for key in ("text", "body", "final", "quote", "context", "notes", "story_beat"):
        value = slide.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("cards", "items", "steps", "nodes", "levels", "takeaways", "stats", "kpis", "rows"):
        values = slide.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    parts.extend(str(v) for k, v in item.items() if k not in {"icon", "color"})
                elif isinstance(item, (str, int, float)):
                    parts.append(str(item))
    return " ".join(parts).strip()


def critique_content(topic, slides):
    """Return a non-mutating report of narrative/content risks."""
    slides = [s for s in (slides or []) if isinstance(s, dict)]
    domain = classify_visual_domain(topic)
    issues = []
    title_rows = []
    content_rows = []
    roles = []
    layouts = []

    for index, slide in enumerate(slides):
        number = index + 1
        title = str(slide.get("title") or "").strip()
        body = _content(slide)
        title_key = _fold(title)
        body_key = _fold(body)
        role = str(slide.get("story_role") or "analysis").casefold()
        layout = str(slide.get("layout") or "").casefold()
        title_rows.append((number, title_key))
        content_rows.append((number, body_key))
        roles.append(role)
        layouts.append(layout)

        if not title:
            issues.append({"slide": number, "severity": "high", "code": "missing_title",
                           "message": "Slayd sarlavhasi yo'q", "action": "Mazmunni aniq nomlaydigan sarlavha yoz"})
        if len(re.findall(r"\w+", body, re.UNICODE)) < 8:
            issues.append({"slide": number, "severity": "high", "code": "thin_content",
                           "message": "Slaydda mazmuniy izoh juda kam", "action": "Mavjud faktni izohla yoki mazmunli diagramma elementlari qo'sh"})
        if title_key in _GENERIC_TITLES:
            issues.append({"slide": number, "severity": "low", "code": "generic_title",
                           "message": "Sarlavha mavzuga xos emas", "action": "Obyekt, davr, mexanizm yoki topilmani aniq nomla"})
        if _METRIC_RE.search(body) and not any(
            marker in _fold(" ".join(str(slide.get(k) or "") for k in ("source", "source_note", "citation", "manba", "notes")))
            for marker in ("source", "manba", "citation", "havola", "official", "rasmiy")
        ):
            issues.append({"slide": number, "severity": "medium", "code": "unverified_metric",
                           "message": "Raqamli da'vo uchun manba ko'rsatilmagan", "action": "Manba qo'sh yoki raqamni aniq namunaviy deb belgilash"})
        if domain == "fiction" and re.search(r"\b(?:kpi|reyting|indeks|index|score|100\s*%)\b", body, re.I):
            issues.append({"slide": number, "severity": "medium", "code": "genre_metric_drift",
                           "message": "Badiiy mavzuda sun'iy KPI yoki reyting ishlatilgan bo'lishi mumkin", "action": "Qahramon yoki voqeani aniq sahna va qarorlar bilan tushuntir"})

    for i, (num, title) in enumerate(title_rows):
        if not title:
            continue
        for other_num, other in title_rows[i + 1:]:
            if other and SequenceMatcher(None, title, other).ratio() >= 0.92:
                issues.append({"slide": other_num, "severity": "medium", "code": "repeated_title",
                               "message": f"{num}-slayd sarlavhasiga juda o'xshash", "action": "Yangi slayd vazifasini aniq farqlat"})
                break

    for i, (num, body) in enumerate(content_rows):
        if len(body) < 50:
            continue
        for other_num, other in content_rows[i + 1:]:
            if other and SequenceMatcher(None, body, other).ratio() >= 0.94:
                issues.append({"slide": other_num, "severity": "high", "code": "repeated_content",
                               "message": f"{num}-slayd mazmuni takrorlangan", "action": "Takroriy slaydni yangi bilim bilan almashtir"})
                break

    for label, sequence in (("story_role", roles), ("layout", layouts)):
        run = 0
        previous = None
        for index, value in enumerate(sequence):
            run = run + 1 if value == previous else 1
            previous = value
            if value and run >= 3:
                issues.append({"slide": index + 1, "severity": "low", "code": f"repeated_{label}_run",
                               "message": f"Ketma-ket uchta bir xil {label}", "action": "Mazmun talab qilsa, narrativ vazifa yoki maketni almashtir"})
                break

    penalties = {"high": 22, "medium": 8, "low": 2}
    score = max(0, 100 - sum(penalties[x["severity"]] for x in issues))
    return {
        "domain": domain,
        "slide_count": len(slides),
        "score": score,
        "passed": not any(x["severity"] == "high" for x in issues),
        "issue_count": len(issues),
        "issues": issues,
    }
