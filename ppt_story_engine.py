"""Adaptive narrative architecture and story QA for Navyblue presentations.

Inspired by common open presentation-design practices. This module is original
project code; it does not copy implementation or template assets from third parties.
"""
import re
import unicodedata
from collections import Counter

STORY_ROLES = {
    "opening_question", "context", "definition", "origin", "chronology",
    "taxonomy", "principle", "mechanism", "workflow", "architecture",
    "actors", "relationship", "case_study", "example", "evidence",
    "measurement", "comparison", "tradeoff", "risk", "constraint",
    "diagnosis", "cause", "effect", "interpretation", "application",
    "decision", "recommendation", "scenario", "future", "implication",
    "reflection", "conclusion", "problem", "analysis", "solution",
    "hook", "synthesis", "method", "experiment", "finding", "geography",
}

_ARCHETYPES = {
    "concept_explainer": {
        "match": ("nazariya", "tushuncha", "mohiyat", "ta'rif", "definition", "concept", "theory", "principle"),
        "flow": "savol yoki paradoks → tushuncha ta'rifi → tarkibiy qismlar → ishlash prinsipi → bog'lanishlar → real misol → qo'llanish",
    },
    "historical_chronicle": {
        "match": ("tarix", "tarixiy", "sivilizatsiya", "urush", "imperiya", "davlat tarixi", "history", "historical", "empire"),
        "flow": "davr manzarasi → kelib chiqish sharoiti → muhim shaxslar va kuchlar → burilish nuqtalari → sabab-oqibat → tarixiy talqin → meros",
    },
    "process_system": {
        "match": ("logistika", "ta'minot zanjiri", "ishlab chiqarish", "jarayon", "tizim", "transport", "supply chain", "workflow", "process", "operations"),
        "flow": "tizim xaritasi → ishtirokchilar → kirish resurslari → oqim bosqichlari → nazorat nuqtalari → uzilish/tor joy → natija va optimallashtirish",
    },
    "comparative_analysis": {
        "match": ("taqqoslash", "qiyos", "farqi", "solishtirish", "comparison", "versus", "vs ", "compare"),
        "flow": "taqqoslash savoli → mezonlar → A modeli → B modeli → kesishuvchi va farqli jihatlar → trade-off → vaziyatga mos tanlov",
    },
    "research_evidence": {
        "match": ("tadqiqot", "ilmiy", "statistika", "ko'rsatkich", "samaradorlik", "research", "study", "data", "performance"),
        "flow": "tadqiqot savoli → metod va doira → dalillar → natijalar → naqshlar va farqlar → cheklovlar → xulosa",
    },
    "case_study": {
        "match": ("case study", "keys", "korxona", "kompaniya", "amaliyot", "misol", "company", "case"),
        "flow": "kontekst → tashkilot yoki vaziyat → boshlang'ich holat → qarorlar → amalga oshirish → natijalar → olinadigan saboq",
    },
    "biography_profile": {
        "match": ("biografiya", "hayoti", "shaxs", "olim", "rahbar", "biography", "life of", "profile"),
        "flow": "davr va muhit → shakllanish → asosiy g'oyalar → qarorlar va ishlar → ta'sir → bahsli jihatlar → meros",
    },
    "strategic_decision": {
        "match": ("strategiya", "reja", "rivojlanish", "islohot", "qaror", "strategy", "roadmap", "transformation"),
        "flow": "maqsad va mezon → tashqi muhit → imkoniyatlar → variantlar → resurs va risklar → yo'l xaritasi → o'lchovlar",
    },
    "geographic_system": {
        "match": ("geografiya", "mintaqa", "mamlakatlar", "hudud", "yo'nalish", "geography", "region", "countries", "route"),
        "flow": "makon va masshtab → hududiy xususiyatlar → markazlar → oqimlar va aloqalar → tafovutlar → ta'sir omillari → istiqbol",
    },
    "how_it_works": {
        "match": ("qanday ishlaydi", "qanday ishlash", "bosqichlari", "qo'llanma", "how it works", "how to", "guide", "steps"),
        "flow": "yakuniy natija → kerakli qismlar → tayyorgarlik → ketma-ket amallar → tekshiruv → keng tarqalgan xato → natijani baholash",
    },
}

_LAYOUT_ROLE = {
    "timeline": "chronology", "chain": "workflow", "isometric": "architecture",
    "map": "geography", "compare": "comparison", "before_after": "comparison",
    "matrix": "decision", "chart": "evidence", "stats": "measurement",
    "kpi": "measurement", "table": "taxonomy", "pyramid": "taxonomy",
    "venn": "relationship", "hub": "architecture", "orbit": "relationship",
    "funnel": "mechanism", "iceberg": "interpretation", "bignumber": "measurement",
    "cards": "taxonomy", "bento": "synthesis", "editorial": "interpretation",
    "statement": "principle", "hero": "opening_question", "image_story": "case_study",
    "collage": "example", "agenda": "context", "closing": "conclusion",
}

def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def build_story_guidance(topic, slide_count):
    """Return a topic-aware, non-prescriptive story architecture brief for Gemini."""
    folded = _fold(topic)
    scored = []
    for name, spec in _ARCHETYPES.items():
        score = sum(1 for term in spec["match"] if _fold(term) and _fold(term) in folded)
        if score:
            scored.append((score, name, spec))
    scored.sort(key=lambda row: (-row[0], row[1]))
    selected = scored[0][1] if scored else "concept_explainer"
    lines = [
        "NARRATIVE ARCHITECTURE ENGINE (majburiy):",
        f"Mavzu uchun eng mos boshlang'ich arxitektura: {selected}. Bu faqat tavsiya; mavzuni tahlil qilib yaxshiroq model bo'lsa, uni tanla.",
        "Bitta universal 'muammo → tahlil → yechim → natija' qolipidan foydalanma. Muammo-yechim faqat mavzuning markaziy mazmuni bo'lsa ishlatiladi.",
        "Quyidagi hikoya modellaridan mosini tanla yoki 2 tasini mantiqan birlashtir:",
    ]
    for name, spec in _ARCHETYPES.items():
        lines.append(f"- {name}: {spec['flow']}")
    lines.extend([
        f"Kontent slaydlari soni: {int(slide_count)}. Har bir slayd yangi bilim yoki yangi nuqtai nazar olib kelsin.",
        "Har slaydga story_role va story_beat yoz. story_role takrorlanishi mumkin, lekin ketma-ket bir xil vazifali slaydlar bo'lmasin.",
        "Slayd nomlarini 'Kirish', 'Muammo', 'Yechim', 'Xulosa' kabi umumiy sarlavhalar bilan to'ldirma; konkret obyekt, mexanizm, davr, mezon yoki topilmani nomla.",
        "Muallif/taqdimotchi ismi, guruh va tashkilot ma'lumotlari faqat muqova metadata qismida bo'lsin; kontent slaydlarida qayta-qayta ism yozma.",
        "Birinchi kontent slaydi albatta agenda bo'lishi shart emas. Kuchli savol, tarixiy kadr, obyekt, xarita, dalil yoki tushuncha bilan ochish mumkin.",
        "Oxirgi kontent slaydi doim 'Yechim' yoki 'Xulosa' bo'lishi shart emas. Mavzuga mos topilma, prognoz, qaror, meros yoki ochiq savol bilan yakunla.",
        "Slaydlar ichida kamida 5 xil mazmuniy vazifa va kamida 5 xil maket ishlat (agar slaydlar soni 7 yoki undan ko'p bo'lsa).",
        "Bitta sarlavha yoki g'oyani boshqa so'z bilan takrorlash yangi slayd hisoblanmaydi. Har slayd oldingisiga yangi fakt, mexanizm, mezon, misol yoki oqibat qo'shsin.",
        "Faqat mavzuga aloqador bo'lsa chart/table/map ishlat; ishonchli raqam bo'lmasa diagrammani konseptual ko'rsat yoki boshqa vizual tanla.",
    ])
    return "\n".join(lines)

def infer_story_role(slide):
    """Infer a semantic role from the selected visual form when AI omitted one."""
    layout = str((slide or {}).get("layout") or "").strip().lower()
    if layout in _LAYOUT_ROLE:
        return _LAYOUT_ROLE[layout]
    title = _fold((slide or {}).get("title"))
    text = _fold((slide or {}).get("text"))
    blob = title + " " + text[:500]
    rules = (
        (("kelib chiq", "tarixi", "davr", "boshlangan", "origin", "history"), "origin"),
        (("ta'rif", "mohiyat", "tushuncha", "definition", "what is"), "definition"),
        (("sabab", "omil", "nega", "cause", "driver"), "cause"),
        (("oqibat", "ta'sir", "natija", "effect", "impact"), "effect"),
        (("misol", "amaliy", "case", "example"), "example"),
        (("xavf", "risk", "cheklov", "muammo", "constraint"), "risk"),
        (("usul", "metod", "method", "yondashuv"), "method"),
        (("kelajak", "istiqbol", "prognoz", "future", "outlook"), "future"),
        (("tavsiya", "recommend", "qaror", "decision"), "recommendation"),
    )
    for terms, role in rules:
        if any(term in blob for term in terms):
            return role
    return "analysis"

def story_quality_report(slides):
    """Compact diagnostics: report structural repetition without rewriting valid content."""
    items = [s for s in (slides or []) if isinstance(s, dict) and s.get("layout") != "executive"]
    titles = [_fold(s.get("title")) for s in items]
    title_counts = Counter(t for t in titles if t)
    role_counts = Counter(str(s.get("story_role") or infer_story_role(s)) for s in items)
    layout_counts = Counter(str(s.get("layout") or "") for s in items)
    repeated_titles = [t for t, n in title_counts.items() if n > 1]
    max_layout_run = run = 0
    last = None
    for s in items:
        cur = s.get("layout")
        run = run + 1 if cur == last else 1
        max_layout_run = max(max_layout_run, run)
        last = cur
    return {
        "slides": len(items),
        "unique_titles": len(set(titles)),
        "repeated_titles": repeated_titles[:5],
        "role_count": len(role_counts),
        "role_distribution": dict(role_counts),
        "layout_count": len(layout_counts),
        "max_same_layout_run": max_layout_run,
    }
