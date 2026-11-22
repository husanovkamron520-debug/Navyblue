"""Lightweight, deterministic skill routing for October.

Skills are prompt guidance, not executable tools. Keep this module dependency-free
so the Telegram bot can start even if optional integrations are unavailable.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple


_SKILLS: Dict[str, dict] = {
    "logistics": {
        "label": "Logistika va supply chain",
        "keywords": (
            "logistika", "ta'minot zanjiri", "supply chain", "scm", "ombor",
            "zaxira", "inventory", "yetkazib ber", "transport", "procurement",
            "lead time", "forecast", "talab prognozi", "ta'minotchi",
        ),
        "guidance": (
            "- Logistika/SCM savollarida jarayonni boshidan oxirigacha ko'rsat: "
            "talab -> xarid -> ishlab chiqarish -> ombor -> transport -> mijoz.\n"
            "- KPI, formula va hisoblarda birliklarni ko'rsat; berilmagan raqamlarni "
            "fakt sifatida to'qima, kerak bo'lsa taxmin ekanini ajrat.\n"
            "- Amaliy misol, sabab-oqibat va qaror variantlarini nazariy ta'rifdan ustun qo'y.\n"
            "- Case yechimida muammo, dalil, variantlar, risk, KPI va tavsiyani alohida ber."
        ),
    },
    "presentation": {
        "label": "Taqdimot va vizual material",
        "keywords": (
            "taqdimot", "prezentatsiya", "slayd", "slayt", "powerpoint",
            "pptx", "slide deck", "slaydlar",
        ),
        "guidance": (
            "- Avval auditoriya, maqsad va asosiy xabarni aniqlab ol; yetarli bo'lsa "
            "ortiqcha savol bermasdan ishni boshlash uchun mavjud ma'lumotdan foydalan.\n"
            "- Har slaydda bitta asosiy fikr bo'lsin; bir xil maketni ketma-ket takrorlama.\n"
            "- Foydalanuvchi yuborgan rasmlarni asosiy manba sifatida ko'rib chiq; "
            "rasm mazmunini taxmin qilma va aloqasiz stock tasvir tanlama.\n"
            "- Fakt, manba va dizayn bezagini ajrat; slayd soni yoki fayl yaratilganini "
            "faqat dastur tasdiqlagandan keyin ayt."
        ),
    },
    "research": {
        "label": "Tadqiqot va manbalar",
        "keywords": (
            "tadqiqot", "research", "manba", "manbalar", "internetdan qidir",
            "webdan qidir", "github", "repo", "repository", "maqola", "ilmiy",
            "so'nggi ma'lumot", "eng yangi", "taqqosla",
        ),
        "guidance": (
            "- Tashqi yoki yangilanadigan fakt kerak bo'lsa, mavjud qidiruv vositasidan "
            "foydalan; vosita bo'lmasa, jonli tekshirganman deb da'vo qilma.\n"
            "- Muhim xulosalarni birlamchi/rasmiy manbalar bilan tekshir, sanani va "
            "manba havolasini saqla.\n"
            "- Fakt, taxmin va tavsiyani aniq ajrat; qarama-qarshi dalillarni yashirma.\n"
            "- GitHub repolarida avval README, litsenziya, faollik, arxitektura va "
            "integratsiya xarajatini tekshir; butun frameworkni ko'chirishga shoshilma."
        ),
    },
    "study": {
        "label": "Ta'lim va o'rganish",
        "keywords": (
            "ielts", "imtihon", "dars", "mavzuni tushuntir", "tushuntirib ber",
            "o'rgan", "mashq", "grammatika", "reading", "listening", "writing",
            "speaking", "test savol", "konspekt",
        ),
        "guidance": (
            "- Tushuntirishni sodda ta'rif -> mexanizm -> amaliy misol -> qisqa tekshiruv "
            "ketma-ketligida ber.\n"
            "- O'quvchining darajasiga mos murakkablikni tanla; javobni shunchaki aytib "
            "qo'ymasdan, nima uchunligini ko'rsat.\n"
            "- Til o'rganishda xatoni aniq ko'rsat, tabiiyroq variantni ber va qisqa "
            "mashq bilan mustahkamla."
        ),
    },
    "productivity": {
        "label": "Rejalashtirish va unumdorlik",
        "keywords": (
            "vazifa", "to-do", "eslatma", "eslatib", "reja tuz", "kunlik reja",
            "haftalik reja", "deadline", "muddat", "jadval tuz", "ustuvorlik",
        ),
        "guidance": (
            "- Katta ishni aniq keyingi qadamlarga bo'l; har bir qadamda natija va "
            "muddatni ko'rsat.\n"
            "- Shoshilinchlik va muhimlikni ajrat, bir vaqtda bajariladigan ishlar "
            "sonini real saqla.\n"
            "- Vazifa yoki eslatmani faqat tegishli action va saqlash natijasi "
            "tasdiqlanganda bajarildi deb ayt."
        ),
    },
}

_MAX_SKILLS = 2
_MAX_CONTEXT_CHARS = 3200


def _normalize(text: str) -> str:
    value = str(text or "").casefold().replace("’", "'").replace("ʻ", "'")
    return re.sub(r"\\s+", " ", value).strip()


def select_skills(text: str, limit: int = _MAX_SKILLS) -> List[str]:
    """Return up to limit skill IDs, ranked by explicit keyword matches."""
    normalized = _normalize(text)
    if not normalized:
        return []
    scored: List[Tuple[int, str]] = []
    for skill_id, spec in _SKILLS.items():
        score = 0
        for keyword in spec["keywords"]:
            needle = _normalize(keyword)
            if " " in needle:
                matched = needle in normalized
            else:
                matched = re.search(r"(?<![\\w])" + re.escape(needle) + r"(?![\\w])", normalized) is not None
            if matched:
                score += 2 if len(needle) > 5 else 1
        if score:
            scored.append((score, skill_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [skill_id for _score, skill_id in scored[:max(0, min(int(limit), _MAX_SKILLS))]]


def build_skill_context(text: str) -> str:
    """Build a small prompt section; empty when no specialist skill matches."""
    selected = select_skills(text)
    if not selected:
        return ""
    blocks = ["TANLANGAN ISH KO'NIKMALARI (faqat tegishli bo'lsa qo'lla):"]
    for skill_id in selected:
        spec = _SKILLS[skill_id]
        blocks.append(f"\\n[{spec['label']}]\\n{spec['guidance']}")
    result = "\\n".join(blocks)
    return result[:_MAX_CONTEXT_CHARS]


def available_skills() -> List[dict]:
    """Return public metadata only; internal keyword lists stay private."""
    return [
        {"id": skill_id, "label": spec["label"]}
        for skill_id, spec in _SKILLS.items()
    ]
