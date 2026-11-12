"""Adaptive narrative architecture and semantic QA for Navyblue PPTX generation.

This is original project code. It adapts open presentation-design principles to the
existing Python/ python-pptx renderer; it does not vendor third-party templates.
"""
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

STORY_ROLES = {
    "opening_question", "context", "definition", "origin", "chronology",
    "taxonomy", "principle", "mechanism", "workflow", "architecture",
    "actors", "relationship", "case_study", "example", "evidence",
    "measurement", "comparison", "tradeoff", "risk", "constraint",
    "diagnosis", "cause", "effect", "interpretation", "application",
    "decision", "recommendation", "scenario", "future", "implication",
    "reflection", "conclusion", "problem", "analysis", "solution",
    "hook", "synthesis", "method", "experiment", "finding", "geography",
    "debate", "policy", "model", "principle", "lesson", "implementation",
}

# Topic archetypes are deliberately broad. The model may override the first match
# after reading the actual topic; these are narrative starting points, not templates.
_ARCHETYPES = {
    "concept_explainer": {
        "match": ("nazariya", "tushuncha", "mohiyat", "ta'rif", "definition", "concept", "theory", "principle"),
        "flow": "kuchli savol yoki paradoks → ta'rif → tarkibiy qismlar → ishlash prinsipi → o'zaro bog'lanish → real misol → qo'llanish va cheklov",
        "roles": "opening_question, definition, taxonomy, mechanism, relationship, example, application",
    },
    "historical_chronicle": {
        "match": ("tarix", "tarixiy", "sivilizatsiya", "urush", "imperiya", "sulola", "history", "historical", "empire"),
        "flow": "davr manzarasi → kelib chiqish sharoiti → kuchlar va manfaatlar → burilish nuqtalari → sabab-oqibat → tarixiy talqin → meros",
        "roles": "context, origin, actors, chronology, cause, interpretation, implication",
    },
    "process_system": {
        "match": ("logistika", "ta'minot zanjiri", "ishlab chiqarish", "jarayon", "tizim", "transport", "supply chain", "workflow", "process", "operations"),
        "flow": "tizim xaritasi → ishtirokchilar → resurslar va kirishlar → oqim bosqichlari → nazorat nuqtalari → tor joylar → natija va optimallashtirish",
        "roles": "architecture, actors, workflow, mechanism, constraint, measurement, application",
    },
    "comparative_analysis": {
        "match": ("taqqoslash", "qiyos", "farqi", "solishtirish", "comparison", "versus", " vs ", "compare"),
        "flow": "taqqoslash savoli → mezonlar → A modeli → B modeli → umumiy va farqli jihatlar → trade-off → vaziyatga mos tanlov",
        "roles": "opening_question, comparison, model, evidence, tradeoff, decision, implication",
    },
    "research_evidence": {
        "match": ("tadqiqot", "ilmiy", "statistika", "ko'rsatkich", "samaradorlik", "research", "study", "data", "performance"),
        "flow": "tadqiqot savoli → metod va doira → dalillar → natijalar → naqshlar va farqlar → cheklovlar → xulosa",
        "roles": "opening_question, method, evidence, finding, interpretation, constraint, conclusion",
    },
    "case_study": {
        "match": ("case study", "keys", "korxona", "kompaniya", "amaliyot", "misol", "company", "case"),
        "flow": "kontekst → tashkilot yoki vaziyat → boshlang'ich holat → qarorlar → amalga oshirish → natijalar → olinadigan saboq",
        "roles": "context, case_study, diagnosis, decision, implementation, measurement, lesson",
    },
    "biography_profile": {
        "match": ("biografiya", "hayoti", "shaxs", "olim", "rahbar", "biography", "life of", "profile"),
        "flow": "davr va muhit → shakllanish → asosiy g'oyalar → qarorlar va ishlar → ta'sir → bahsli jihatlar → meros",
        "roles": "context, origin, chronology, principle, decision, implication, reflection",
    },
    "strategic_decision": {
        "match": ("strategiya", "reja", "rivojlanish", "islohot", "qaror", "strategy", "roadmap", "transformation"),
        "flow": "maqsad va mezon → tashqi muhit → imkoniyatlar → variantlar → resurs va risklar → yo'l xaritasi → o'lchovlar",
        "roles": "context, objective, analysis, comparison, risk, implementation, measurement",
    },
    "geographic_system": {
        "match": ("geografiya", "mintaqa", "mamlakatlar", "hudud", "yo'nalish", "geography", "region", "countries", "route"),
        "flow": "makon va masshtab → hududiy xususiyatlar → markazlar → oqimlar va aloqalar → tafovutlar → ta'sir omillari → istiqbol",
        "roles": "geography, context, taxonomy, relationship, workflow, comparison, future",
    },
    "how_it_works": {
        "match": ("qanday ishlaydi", "qanday ishlash", "bosqichlari", "qo'llanma", "how it works", "how to", "guide", "steps"),
        "flow": "yakuniy natija → kerakli qismlar → tayyorgarlik → amallar → tekshiruv → keng tarqalgan xato → natijani baholash",
        "roles": "opening_question, architecture, method, workflow, constraint, application, measurement",
    },
    "science_and_technology": {
        "match": ("fizika", "kimyo", "biologiya", "texnologiya", "sun'iy intellekt", "science", "technology", "engineering", "algorithm"),
        "flow": "hodisa yoki savol → ilmiy asos → tizim qismlari → mexanizm → tajriba/dalil → amaliy ta'sir → cheklov va istiqbol",
        "roles": "opening_question, principle, architecture, mechanism, experiment, application, future",
    },
    "policy_and_governance": {
        "match": ("davlat", "byudjet", "budjet", "siyosat", "qonunchilik", "boshqaruv", "policy", "governance", "public finance"),
        "flow": "institutsional kontekst → vakolat va ishtirokchilar → qoidalar → resurslar oqimi → nazorat → natijalar → bahs va takomillashtirish",
        "roles": "context, actors, policy, mechanism, measurement, constraint, implication",
    },
    "business_model": {
        "match": ("biznes model", "daromad", "bozor", "mijoz", "marketing", "business model", "market", "revenue", "customer"),
        "flow": "mijoz ehtiyoji → qiymat taklifi → bozor va raqobat → operatsion model → daromad/xarajat mexanizmi → risk → o'sish",
        "roles": "context, actors, principle, comparison, mechanism, risk, strategy",
    },
    "educational_method": {
        "match": ("ta'lim", "pedagogika", "o'qitish", "o'rganish", "metodika", "education", "learning", "teaching", "pedagogy"),
        "flow": "o'rganish maqsadi → nazariy asos → metod → dars/amal jarayoni → namuna → baholash → transfer va refleksiya",
        "roles": "objective, principle, method, workflow, example, measurement, reflection",
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
    "waterfall": "measurement", "swimlane": "workflow", "network": "relationship", "quote": "reflection",
}

def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def _slide_blob(slide):
    parts = [str(slide.get("title") or ""), str(slide.get("text") or ""),
             str(slide.get("story_beat") or "")]
    for key in ("cards", "items", "steps", "nodes", "levels", "takeaways", "stats", "kpis"):
        value = slide.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts.extend(str(v) for v in item.values() if isinstance(v, (str, int, float)))
                elif isinstance(item, str):
                    parts.append(item)
    return _fold(" ".join(parts))

def classify_archetype(topic):
    folded = _fold(topic)
    scored = []
    for name, spec in _ARCHETYPES.items():
        score = sum(2 if len(_fold(term).split()) > 1 else 1
                    for term in spec["match"] if _fold(term) and _fold(term) in folded)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored[0][1] if scored else "concept_explainer"

def build_story_guidance(topic, slide_count):
    """Build topic-aware narrative guidance without forcing a universal slide order."""
    selected = classify_archetype(topic)
    spec = _ARCHETYPES[selected]
    lines = [
        "NARRATIVE ARCHITECTURE ENGINE — MAJBURIY:",
        f"Mavzuga mos boshlang'ich arxitektura: {selected}. Tavsiya xolos; mavzuni o'qib, kerak bo'lsa boshqa arxitektura yoki gibrid tanla.",
        f"Taklif etilgan oqim: {spec['flow']}.",
        f"Ushbu arxitektura uchun mumkin bo'lgan story_role ketma-ketligi: {spec['roles']}. Uni mexanik ravishda ko'chirma; mazmunga moslab qayta tuz.",
        "Bitta universal 'muammo → tahlil → yechim → natija' qolipidan foydalanma. Muammo/yechim faqat mavzuning markaziy mazmuni bo'lsa ishlatiladi.",
        "Muqova metadata: muallif, guruh va tashkilot nomlari faqat muqovada. Kontent slaydlarida ism yoki guruhni takrorlama.",
        "Har bir slayd bitta yangi savolga javob bersin yoki yangi bilim, dalil, mexanizm, mezon, misol, oqibat yoxud nuqtai nazar qo'shsin.",
        "Ketma-ket slaydlarning vazifasi, sarlavhasi va asosiy vizual metaforasi farq qilsin. Bir fikrni sinonim bilan qayta aytish yangi slayd emas.",
        "Birinchi kontent slaydi agenda bo'lishi shart emas: kuchli savol, tarixiy kadr, xarita, obyekt, dalil yoki paradoks bilan ochish mumkin.",
        "Oxirgi kontent slaydi doim 'Yechim' yoki 'Xulosa' bo'lishi shart emas: topilma, prognoz, qaror, meros, amaliy saboq yoki ochiq savol bilan yakunla.",
        "Muammo → yechim → natija ketma-ketligini ketma-ket uch slaydga aylantirma, agar bu mavzuning tabiiy jarayoni bo'lmasa.",
        "Slaydlar soni 7+ bo'lsa kamida 5 xil story_role, 5 xil layout va 4 xil composition ishlat. Bir xil layout yoki composition ketma-ket kelmasin.",
        "Har bir slaydga story_role va mazmuniy story_beat yoz. story_role ro'yxati: " + ", ".join(sorted(STORY_ROLES)) + ".",
        "Sarlavhalar konkret obyekt, davr, mexanizm, mezon, topilma yoki savolni nomlasin; 'Kirish', 'Muammo', 'Yechim', 'Xulosa' kabi umumiy sarlavhalarni yolg'iz ishlatma.",
        "Chart faqat manbali yoki aniq 'namunaviy' deb belgilangan ma'lumot bilan; manbasiz statistik raqam va soxta manba to'qima.",
        "Har bir slayd uchun visual_focus, visual_type, composition, hierarchy va density maydonlarini mazmunga mos tanla.",
        "Bir xil ism/taqdimotchi, muammo-yechim sarlavhasi, 3 ta bir xil kartochka yoki bir xil vizual blokni butun taqdimot bo'ylab takrorlama.",
        f"Rejalashtirilgan kontent slaydlari: {int(slide_count)}. Kerakli slayd sonini mazmun sifatidan ustun qo'yma; yetishmasa mazmunli yangi bo'limlar bilan davom ettir.",
        "Taqdimot yakunida mavzuning eng muhim g'oyasi va auditoriya nimani eslab qolishi aniq bo'lsin.",
    ]
    return "\n".join(lines)

def infer_story_role(slide):
    """Infer a semantic role when the model omitted or supplied an invalid role."""
    layout = str((slide or {}).get("layout") or "").strip().lower()
    if layout in _LAYOUT_ROLE:
        return _LAYOUT_ROLE[layout]
    blob = _fold(" ".join(str((slide or {}).get(k) or "") for k in ("title", "text", "story_beat")))
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
        (("ishtirokchi", "tomonlar", "stakeholder", "actor"), "actors"),
        (("bosqich", "jarayon", "workflow", "process"), "workflow"),
        (("taqqos", "farq", "solishtir", "versus", "compare"), "comparison"),
        (("o'lchov", "ko'rsatkich", "kpi", "measure"), "measurement"),
        (("dalil", "natijalar", "evidence", "finding"), "evidence"),
    )
    for terms, role in rules:
        if any(_fold(term) in blob for term in terms):
            return role
    return "analysis"

def enforce_story_quality(slides):
    """Remove only near-identical content duplicates and normalize story roles."""
    kept = []
    removed = 0
    for slide in slides or []:
        if not isinstance(slide, dict):
            continue
        role = str(slide.get("story_role") or "").strip().lower()
        if role not in STORY_ROLES:
            slide["story_role"] = infer_story_role(slide)
        title = _fold(slide.get("title"))
        blob = _slide_blob(slide)
        duplicate = False
        for prior in kept:
            prior_title = _fold(prior.get("title"))
            prior_blob = _slide_blob(prior)
            title_ratio = SequenceMatcher(None, title, prior_title).ratio() if title and prior_title else 0
            body_ratio = SequenceMatcher(None, blob, prior_blob).ratio() if blob and prior_blob else 0
            # Both title and content must be almost identical; related slides remain.
            if title_ratio >= 0.96 and body_ratio >= 0.94:
                duplicate = True
                break
        if duplicate:
            removed += 1
            continue
        kept.append(slide)
    return kept, {"near_duplicates_removed": removed}

def story_quality_report(slides):
    """Report narrative and visual repetition for logging and QA."""
    items = [s for s in (slides or []) if isinstance(s, dict) and s.get("layout") != "executive"]
    titles = [_fold(s.get("title")) for s in items]
    title_counts = Counter(t for t in titles if t)
    role_counts = Counter(str(s.get("story_role") or infer_story_role(s)) for s in items)
    layout_counts = Counter(str(s.get("layout") or "") for s in items)
    composition_counts = Counter(str((s.get("design") or {}).get("composition") or "") for s in items)
    repeated_titles = [t for t, n in title_counts.items() if n > 1]
    near_title_pairs = []
    for i, title in enumerate(titles):
        if not title:
            continue
        for j in range(i + 1, len(titles)):
            other = titles[j]
            if other and SequenceMatcher(None, title, other).ratio() >= 0.88:
                near_title_pairs.append([i + 1, j + 1])
                if len(near_title_pairs) >= 8:
                    break
        if len(near_title_pairs) >= 8:
            break
    max_layout_run = run = 0
    last = None
    for slide in items:
        cur = slide.get("layout")
        run = run + 1 if cur == last else 1
        max_layout_run = max(max_layout_run, run)
        last = cur
    max_composition_run = run = 0
    last = None
    for slide in items:
        cur = (slide.get("design") or {}).get("composition")
        run = run + 1 if cur == last else 1
        max_composition_run = max(max_composition_run, run)
        last = cur
    return {
        "slides": len(items),
        "unique_titles": len(set(t for t in titles if t)),
        "repeated_titles": repeated_titles[:8],
        "near_title_pairs": near_title_pairs,
        "role_count": len(role_counts),
        "role_distribution": dict(role_counts),
        "layout_count": len(layout_counts),
        "composition_count": len(composition_counts),
        "max_same_layout_run": max_layout_run,
        "max_same_composition_run": max_composition_run,
    }
