"""october_plus.py - October uchun qo'shimcha modul.

Imkoniyatlar:
1. Bilimlar bazasi (Supabase). Buyruqsiz ham ishlaydi:
     g'oya: matn            -> g'oya sifatida saqlaydi (qayd:, iqtibos: ham shunday)
     oxirgi 5 xabarim g'oya -> oxirgi 5 ta xabarni g'oya qilib saqlaydi
     haftalik hisobot       -> mavzular bo'yicha jurnal (Bento HTML + PNG rasm)
   Eski /goya, /qayd, /iqtibos, /haftalik_hisobot buyruqlari ham ishlayveradi.
2. HTML generator: "ombor 3d", "html sahifa", "infografika" kabi so'rovlarda
   Gemini neon uslubidagi tayyor .html fayl yozadi, avtomatik tuzatadi,
   sifatini tekshiradi va yuboradi. Fayl tashqi kutubxonasiz (offline) ishlaydi.
   3D so'ralsa, sinalgan tayyor 3D yadro (october_core3d.js) ishlatiladi.
   Oxirgi HTML Supabase'da ham saqlanadi: bot qayta ishga tushsa ham "koding yubor"
   ishlaydi; HTML faylga javob (reply) qilib o'zgartirish yozsangiz, uni yangilaydi.
3. October xotirasi: bu modul bajargan ishlar October'ning suhbat tarixiga yoziladi,
   shuning uchun October "hozirgina nima qildim" ni biladi.
4. Halollik qoidasi: October bajara olmagan ishini "ha" deb o'tkazib yubormaydi.
5. Task yaratish: "ombor logistikasi bo'yicha krossvord task yarat" -> october_tasks.py orqali
   krossvord + so'z qidirish yaratiladi va saqlanadi (TASK_INTEGRATION.md'ga qarang).

Ulash: pastdagi "ULASH" bo'limiga qarang (bot.py'da allaqachon ulangan).
"""
import asyncio
import datetime as dt
import html as _html
import io
import json
import os
import re
import sys
import textwrap
import time
from collections import deque

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

try:
    import october_tasks as _tasks
except Exception:  # modul yo'q yoki xato bo'lsa, qolgan funksiyalar ishlayveradi
    _tasks = None

TABLE = "kb_notes"
_HTML_TTL_H = 6  # oxirgi HTML necha soat eslab qolinadi

_owner_id = None
_gen = None  # sinxron funksiya: gen(prompt: str) -> str  (Gemini javobi matni)
_sb = None   # Supabase client (yoki .table().insert().execute() qo'llaydigan adapter)

# Egasining oxirgi xabarlari ("oxirgi 5 xabarim g'oya" uchun). Bot qayta ishga tushsa tozalanadi.
_recent = deque(maxlen=50)
# Oxirgi yasalgan HTML (kod so'ralganda yoki o'zgartirishda kerak).
_last_html = {"doc": None, "req": None, "ts": 0.0}

# bot.py dagi October promptiga qo'shiladigan qoida matni
HONESTY_RULES = (
    "- Biror ishni qila olmasang yoki uning bajarilganini dastur tasdiqlamagan bo'lsa, "
    "\"ha\" deb o'tkazib yuborma: nima qila olmasligingni va sababini aniq ayt, "
    "qilish mumkin bo'lgan eng yaqin variantni taklif qil.\n"
)

SQL_SETUP = """
create table if not exists kb_notes (
  id bigserial primary key,
  owner bigint not null,
  kind text not null default 'goya',
  text text not null,
  created_at timestamptz not null default now()
);
create index if not exists kb_notes_owner_time on kb_notes (owner, created_at);
"""

_HTML_WORDS = ("html", "3d", "sahifa", "veb", "web", "infografika", "bento",
               "simulyator", "interaktiv")
_INTERACTIVE_WORDS = ("3d", "o'yin", "oyin", "simulyator", "interaktiv", "kalkulyator")

NEON_PROMPT = """Sen tajribali front-end dasturchisan. Quyidagi so'rov bo'yicha BITTA to'liq, ishlaydigan HTML fayl yoz.
Asosiy qoidalar:
- So'rovdagi narsani AYNAN yasa. Masalan "ombor 3d" bo'lsa, 3D ombor sahnasi (javonlar, qutilar, barmoq/sichqon bilan aylantirish va yaqinlashtirish) yasa; dashboard yoki grafiklar yasama. Infografika so'ralmagan bo'lsa, infografika yasama.
- HECH QANDAY tashqi kutubxona, CDN, tashqi rasm, shrift yoki <link> ishlatma (three.js, Chart.js ham yo'q). Fayl internetsiz va cheklangan brauzerda (Telegram ichida) ham ochilishi kerak.
- Faqat toza HTML + CSS + JavaScript. 3D kerak bo'lsa, <canvas> 2D kontekstida o'zing perspektiva yoki izometrik proyeksiya hisobla. Grafik kerak bo'lsa, inline SVG yoki canvas bilan chiz. WebGL ishlatma.
- <head> ichida birinchi qator: <meta charset="utf-8"> (aynan shu ko'rinishda), keyin viewport meta.
- Neon uslub: to'q fon (#0B0F19), yorqin neon ko'k/pushti/yashil ranglar, yumshoq glow.
- Telefon ekraniga moslash: katta tugmalar, touch hodisalari (touchstart/touchmove) ishlasin.
- Interfeys matnlari o'zbekcha bo'lsin.
- Kod TO'LIQ bo'lsin: "...", "shu yerga qo'shing", TODO kabi to'ldirilmagan joy qoldirma. Sodda, lekin ishonchli yoz: murakkab, sinab bo'lmaydigan narsadan qoch.
- O'yin yoki simulyator bo'lsa: boshlash tugmasi, ball/holat ko'rsatkichi, aniq maqsad va qayta boshlash tugmasi bo'lsin.
- Yozishdan oldin kod mantiqini ichingda tekshirib chiq (o'zgaruvchi nomlari, yopilmagan teglar, mavjud element id'lari).
- Javobda FAQAT HTML kod bo'lsin: izoh yoki ``` belgilarisiz. <!DOCTYPE html> bilan boshlanib </html> bilan tugasin.
So'rov: {req}{extra}"""

_EXTRA_3D = (
    "\n\nSINALGAN 3D YADRO (o'zgartirmasdan ishlat): sahifada "
    "<canvas id=\"scene\" style=\"position:fixed;inset:0;width:100%;height:100%;touch-action:none\"></canvas> bo'lsin. "
    "Quyidagi JavaScript'ni <script> ichiga AYNAN nusxalab qo'y, so'ng sahnani addBox(x,y,z,w,h,d,rang) chaqiruvlari bilan "
    "to'ldir (pol, javonlar, qutilar, yo'laklar, mashinalar...; y - balandlik, rang - '#rrggbb'), oxirida loop() ni chaqir. "
    "Aylantirish, yaqinlashtirish (zoomBy(1.2) / zoomBy(0.8)) va touch yadroda tayyor. Tugmalar, panel, ball kabi UI'ni "
    "canvas ustiga o'zing qo'sh (position:fixed). Yadro kodi:\n"
)

_CORE3D_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "october_core3d.js")

# Sahifa ichida xato bo'lsa (yoki skript yuklanmasa), ekran bo'sh qolmasligi uchun
# pastda qizil qutida xato matnini ko'rsatadi.
_ERR_BANNER = (
    '<script>window.addEventListener("error",function(e){var d=document.createElement("div");'
    'd.style.cssText="position:fixed;left:8px;right:8px;bottom:8px;z-index:99999;background:#300;'
    'color:#fff;padding:8px;font:12px monospace;border:1px solid #f55;border-radius:8px";'
    'd.textContent="JS xato: "+(e.message||(e.target&&e.target.src)||"nomalum");'
    '(document.body||document.documentElement).appendChild(d);},true);</script>'
)


def setup(owner_id, gen_text, supabase_client):
    """bot.py ishga tushganda bir marta chaqiriladi."""
    global _owner_id, _gen, _sb
    _owner_id, _gen, _sb = int(owner_id), gen_text, supabase_client


def _is_owner(update: Update) -> bool:
    u = update.effective_user
    return bool(u and _owner_id is not None and u.id == _owner_id)


async def _ask(prompt: str) -> str:
    return await asyncio.to_thread(_gen, prompt)


def _norm(text: str) -> str:
    """Kichik harf, har xil apostroflar bitta ' ga."""
    return re.sub(r"[ʻʼ’‘`]", "'", (text or "").lower()).strip()


def _core3d() -> str:
    try:
        with open(_CORE3D_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# ---------------------------------------------------------------- October xotirasi
def _bot_module():
    """Ishlayotgan bot.py modulini topadi (October tarixiga yozish uchun)."""
    for name in ("__main__", "bot"):
        m = sys.modules.get(name)
        if m is not None and all(hasattr(m, a) for a in ("_oct_data", "save_json", "OCT_FILE")):
            return m
    return None


def _remember(user_text: str, reply_text: str):
    """Shu modul bajargan ishni October suhbat tarixiga yozadi, October ham bilib tursin."""
    m = _bot_module()
    if m is None:
        return
    try:
        d = m._oct_data()
        d["hist"].append({"r": "u", "t": str(user_text)[:800]})
        d["hist"].append({"r": "m", "t": str(reply_text)[:800]})
        d["hist"] = d["hist"][-60:]
        m.save_json(m.OCT_FILE, d)
    except Exception:
        pass


async def _say(msg, user_text: str, reply: str):
    await msg.reply_text(reply)
    _remember(user_text, reply)


# ---------------------------------------------------------------- HTML generator
def wants_html(text: str) -> bool:
    t = _norm(text)
    return not t.startswith("/") and any(w in t for w in _HTML_WORDS)


def _clean_html(raw: str):
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:html)?\s*|\s*```$", "", raw, flags=re.I).strip()
    start = raw.lower().find("<!doctype")
    if start < 0:
        start = raw.lower().find("<html")
    end = raw.lower().rfind("</html>")
    if start < 0 or end < 0:
        return None
    doc = raw[start:end + 7]
    return doc if len(doc) > 800 else None


def _repair_html(doc: str) -> str:
    """Gemini'ning odatiy xatolarini tuzatadi va xato-qutisini qo'shadi."""
    # <charset="UTF-8"> kabi noto'g'ri tegni to'g'ri <meta charset> ga almashtirish
    doc = re.sub(r"<\s*charset\s*=\s*[\"']?[\w-]+[\"']?\s*/?>", '<meta charset="utf-8">', doc, flags=re.I)
    # xato-qutisini <head> boshiga qo'yamiz
    if 'addEventListener("error"' not in doc:
        doc = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + _ERR_BANNER, doc, count=1, flags=re.I)
    # <meta charset> eng birinchi bo'lishi kerak (brauzer dastlabki baytlarda qidiradi)
    if not re.search(r"<meta[^>]+charset", doc, re.I):
        doc = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + '<meta charset="utf-8">', doc, count=1, flags=re.I)
    else:
        m = re.search(r"<meta[^>]+charset[^>]*>", doc, re.I)
        if m:
            tag = m.group(0)
            doc = doc.replace(tag, "", 1)
            doc = re.sub(r"(<head[^>]*>)", lambda mm: mm.group(1) + tag, doc, count=1, flags=re.I)
    if not doc.rstrip().lower().endswith("</html>"):
        doc = doc.rstrip() + "\n</html>"
    return doc


def _quality_issue(doc: str, req: str):
    """Aniq kamchilik bo'lsa matn, yaxshi bo'lsa None."""
    low = doc.lower()
    body = low.replace(_ERR_BANNER.lower(), "")
    if body.count("<script") != body.count("</script>"):
        return "<script> teglari to'g'ri yopilmagan"
    if re.search(r"<script[^>]+src\s*=\s*[\"']?(https?:)?//", body):
        return "tashqi kutubxona (CDN) ishlatilgan; faqat sof JavaScript kerak"
    if re.search(r"<link[^>]+href\s*=\s*[\"']?(https?:)?//", body):
        return "tashqi CSS/shrift ishlatilgan; hammasi fayl ichida bo'lishi kerak"
    if "<script" not in body and any(w in _norm(req) for w in _INTERACTIVE_WORDS):
        return "JavaScript yo'q, sahifa interaktiv emas"
    if re.search(r"(//|/\*|<!--)\s*(\.\.\.|todo|shu yerga|bu yerga|qolgan kod)", body):
        return "kodda to'ldirilmagan joylar (placeholder) bor"
    return None


async def make_html(request: str, use_core: bool = True):
    """(doc, kamchilik) qaytaradi. 3 marta urinadi; yaroqli HTML chiqmasa (None, sabab)."""
    extra = ""
    if use_core and "3d" in _norm(request):
        core = _core3d()
        if core:
            extra = _EXTRA_3D + core
    issue = None
    best = None
    for attempt in range(3):
        prompt = NEON_PROMPT.format(req=request, extra=extra)
        if issue and attempt:
            prompt += "\n\nOldingi urinishdagi kamchilik: " + issue + ". Buni tuzat va kodni TO'LIQ qayta yoz."
        try:
            doc = _clean_html(await _ask(prompt))
        except Exception as e:
            doc, issue = None, "Gemini xato berdi: " + str(e)
            continue
        if not doc:
            issue = "HTML to'liq chiqmadi (boshi yoki oxiri yo'q)"
            continue
        doc = _repair_html(doc)
        best = doc
        issue = _quality_issue(doc, request)
        if not issue:
            return doc, None
    return best, issue


def _persist_html(doc: str):
    _sb.table(TABLE).insert({"owner": _owner_id, "kind": "html_kod", "text": doc}).execute()


def _load_html():
    since = (dt.datetime.utcnow() - dt.timedelta(hours=_HTML_TTL_H)).isoformat()
    r = (_sb.table(TABLE).select("id,text,created_at")
         .eq("owner", _owner_id).eq("kind", "html_kod")
         .gte("created_at", since).order("created_at").execute())
    rows = r.data or []
    return rows[-1].get("text") if rows else None


async def _get_last_html():
    """Oxirgi HTML: avval xotiradan, bo'lmasa (bot qayta ishga tushgan bo'lsa) bazadan."""
    if _last_html["doc"] and time.time() - _last_html["ts"] < _HTML_TTL_H * 3600:
        return _last_html["doc"]
    try:
        doc = await asyncio.to_thread(_load_html)
    except Exception:
        doc = None
    if doc:
        _last_html["doc"], _last_html["ts"] = doc, time.time()
    return doc


async def _send_html(msg, doc: str, issue, req: str, user_text: str):
    """HTML'ni yuboradi, keyingi savol/o'zgartirish uchun eslab qoladi va October tarixiga yozadi."""
    _last_html["doc"], _last_html["req"], _last_html["ts"] = doc, req, time.time()
    caption = "Tayyor. Faylni telefonda Chrome/Safari orqali oching (Telegram ichida emas)."
    if issue:
        caption = "Tayyor, lekin ogohlantirish: " + issue + ". Ishlamasa, ayting, qayta yozdiraman."
    await msg.reply_document(document=io.BytesIO(doc.encode("utf-8")),
                             filename="october.html", caption=caption)
    try:
        await asyncio.to_thread(_persist_html, doc)
    except Exception:
        pass
    kb = max(1, len(doc) // 1024)
    _remember(user_text, "\"" + user_text[:120] + "\" bo'yicha october.html yasab yubordim (HTML/CSS/JavaScript, "
              + str(kb) + " KB). Kodini so'rasa yoki o'zgartirmoqchi bo'lsa, fayl ustiga reply qilsin.")


# ---------------------------------------------------------------- Buyruqsiz tushunish
_KIND = r"(g'?oya|qayd|iqtibos)"
_RE_SAVE_COLON = re.compile(r"^\s*" + _KIND + r"\s*[:\-–—]\s*(.+)$", re.S)
_RE_SAVE_SPACE = re.compile(r"^\s*" + _KIND + r"\s+(.{3,})$", re.S)
# asl matndan (apostrof turi har xil bo'lishi mumkin) prefiksni olib tashlash uchun
_PREFIX_RE = re.compile(r"^\s*(?:g[ʻʼ'’‘`]?oya|qayd|iqtibos)\s*[:\-–—]?\s*", re.I)
_NUM_WORDS = {"bitta": 1, "ikkita": 2, "uchta": 3, "to'rtta": 4, "beshta": 5,
              "oltita": 6, "yettita": 7, "sakkizta": 8, "to'qqizta": 9, "o'nta": 10}
_RE_BULK = re.compile(
    r"oxirgi\s+(\d+|" + "|".join(_NUM_WORDS) + r")\s*(?:ta\s*)?(?:xabar|yozuv|gap)\w*.*?" + _KIND)
_RE_CODE_Q = re.compile(r"\bkod\w*")
_RE_NEW_BUILD = re.compile(r"(yasab|yozib|yaratib|qilib)\s+ber|\byarat\b|\byasa\b")

_RE_TASK_WORD = re.compile(r"\btask\w*")
_RE_TASK_KIND = re.compile(r"krossvord|qidirish")
_RE_TASK_VERB = re.compile(r"yarat|yasa|tayyorla|\btuz|\bqil\b|qilib")
_RE_TASK_NOISE = re.compile(
    r"\b(task\w*|krossvord\w*|so'?z\s+qidirish\w*|qidirish\w*|yarat\w*|yasa\w*|tayyorla\w*|tuz\w*|qil\w*|"
    r"ber|va|bo'yicha|haqida|mavzusida|mavzuda|mavzu|uchun|menga|iltimos)\b")


def _is_task_request(t: str) -> bool:
    return bool(_RE_TASK_WORD.search(t) and _RE_TASK_KIND.search(t) and _RE_TASK_VERB.search(t))


async def _make_task(msg, text: str, t: str) -> bool:
    """"ombor logistikasi bo'yicha krossvord task yarat" -> Gemini task yasaydi, saqlaydi, namuna yuboradi."""
    topic = re.sub(r"[\s:,\-–—]+", " ", _RE_TASK_NOISE.sub(" ", t)).strip()
    if len(topic) < 3:
        await _say(msg, text, "Qaysi mavzu bo'yicha? Masalan: \"ombor logistikasi bo'yicha krossvord task yarat\".")
        return True
    await msg.reply_text("\"" + topic + "\" bo'yicha task tayyorlanyapti (30-60 soniya)...")
    try:
        task = await asyncio.to_thread(_tasks.create_task, topic, _gen)
    except Exception as e:
        await _say(msg, text, "Task yasab bo'lmadi: " + str(e) + ". Mavzuni aniqroq yozib, qayta urinib ko'ring.")
        return True
    saved = True
    try:
        await asyncio.to_thread(_tasks.save, _sb, _owner_id, task)
        html_doc = await asyncio.to_thread(_tasks.build_html, task)
    except Exception as e:
        saved = False
        html_doc = None
        await msg.reply_text("Task yasaldi, lekin saqlab bo'lmadi: " + str(e))
    info = ("\"" + task["title"] + "\" tayyor (ID: " + task["id"] + "): "
            + str(len(task["data"]["cw1"]["ents"])) + " ta krossvord so'zi, "
            + str(len(task["data"]["ws"]["words"])) + " ta so'z qidirish so'zi.")
    if saved and _tasks.INTEGRATED:
        info += " Talabalar uni Task tugmasida ko'radi, natija avtomatik tekshirilib ustozga ketadi."
    elif saved:
        info += " Saqlandi. Talabalarga Task tugmasida chiqishi uchun bot.py ulanishi kerak (TASK_INTEGRATION.md)."
    if html_doc:
        await msg.reply_document(document=io.BytesIO(html_doc.encode("utf-8")),
                                 filename="task_" + task["id"] + ".html",
                                 caption=info + " Fayl faqat oldindan ko'rish uchun (natija yuborilmaydi).")
        _remember(text, info)
    else:
        await _say(msg, text, info)
    return True


def _kind_of(word: str) -> str:
    return "goya" if word.startswith("g") else word


_LABEL = {"goya": "G'oya", "qayd": "Qayd", "iqtibos": "Iqtibos"}


def _save_note(kind: str, text: str):
    r = _sb.table(TABLE).insert({"owner": _owner_id, "kind": kind, "text": text}).execute()
    rows = r.data or []
    return rows[0].get("id") if rows else None


async def _save_many(msg, kind: str, texts, user_text: str):
    saved, failed = 0, 0
    for t in texts:
        try:
            await asyncio.to_thread(_save_note, kind, t[:4000])
            saved += 1
        except Exception:
            failed += 1
    name = _LABEL[kind].lower()
    if failed:
        reply = str(saved) + " ta " + name + " saqlandi, " + str(failed) + " tasi saqlanmadi (baza xatosi)."
    else:
        reply = str(saved) + " ta " + name + " saqlandi."
    await _say(msg, user_text, reply)


async def try_handle(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """october_chat() boshida chaqiriladi: True qaytsa, so'rov shu yerda hal bo'lgan."""
    if not _is_owner(update):
        return False
    msg = update.effective_message
    t = _norm(text)
    if not t:
        return False
    previous = list(_recent)  # joriy xabardan oldingilari
    if not t.startswith("/"):
        _recent.append((text or "").strip())

    # 1) "oxirgi 5 xabarim g'oya"
    m = _RE_BULK.search(t)
    if m and len(t) < 120:
        raw_n = m.group(1)
        n = int(raw_n) if raw_n.isdigit() else _NUM_WORDS[raw_n]
        n = max(1, min(n, 20))
        texts = previous[-n:]
        if not texts:
            await _say(msg, text, "Oldingi xabarlaringiz esimda yo'q (bot qayta ishga tushgan bo'lishi mumkin). "
                                  "Ularni \"g'oya: matn\" ko'rinishida yuboring.")
            return True
        if len(texts) < n:
            await msg.reply_text("Faqat " + str(len(texts)) + " ta xabar esimda, shularni saqlayman.")
        await _save_many(msg, _kind_of(m.group(2)), texts, text)
        return True

    # 2) "g'oya: matn" / "g'oya matn"
    m = _RE_SAVE_COLON.match(t) or _RE_SAVE_SPACE.match(t)
    if m:
        body = _PREFIX_RE.sub("", text or "", count=1).strip()
        if body:
            kind = _kind_of(m.group(1))
            try:
                nid = await asyncio.to_thread(_save_note, kind, body[:4000])
            except Exception as e:
                await _say(msg, text, "Saqlab bo'lmadi: " + str(e))
                return True
            await _say(msg, text, _LABEL[kind] + " saqlandi" + (" (#" + str(nid) + ")." if nid else "."))
            return True

    # 3) "haftalik hisobot"
    if len(t) < 40 and re.search(r"haftalik\s+(hisobot|jurnal)", t):
        await haftalik_hisobot(update, context)
        return True

    # 3b) "... bo'yicha krossvord task yarat"
    if _tasks is not None and _is_task_request(t):
        return await _make_task(msg, text, t)

    rm = msg.reply_to_message
    replied_file = bool(
        rm and ((rm.document and (rm.document.file_name or "").lower().endswith(".html"))
                or (rm.caption or "").startswith("Tayyor"))
    )
    wants_code = len(t) < 80 and bool(_RE_CODE_Q.search(t)) and not _RE_NEW_BUILD.search(t)
    wants_edit = replied_file and len(t) < 300 and not t.startswith("/")
    last = await _get_last_html() if (wants_code or wants_edit) else None

    # 4) oxirgi HTML haqida savol: "koding yubor", "qanday kodda yozding"
    if last and wants_code:
        await msg.reply_text("Bu sahifani HTML, CSS va JavaScript'da yozdim (Python bu botning o'zi, sahifa emas). "
                             "To'liq kodi pastdagi faylda.")
        await msg.reply_document(document=io.BytesIO(last.encode("utf-8")), filename="october_kodi.txt")
        _remember(text, "Sahifa HTML/CSS/JavaScript'da yozilgan; kodini october_kodi.txt fayl qilib yubordim.")
        return True

    # 5) HTML faylga javob (reply) bilan o'zgartirish: "rangini ko'k qil", "tezroq qil"
    if last and wants_edit:
        await msg.reply_text("Sahifani o'zgartiryapman, bir oz kuting...")
        req = ("Mavjud HTML sahifani quyidagi o'zgartirish bo'yicha yangila va TO'LIQ yangi faylni qaytar. "
               "O'zgartirish: " + (text or "") + "\n\nMavjud kod:\n" + last[:40000])
        doc, issue = await make_html(req, use_core=False)
        if not doc:
            await _say(msg, text, "O'zgartirib bo'lmadi: " + str(issue) + ". Avvalgi fayl o'zgarishsiz qoldi.")
            return True
        await _send_html(msg, doc, issue, req, text)
        return True

    # 6) yangi HTML
    if wants_html(text):
        await msg.reply_text("HTML yozyapman, bir oz kuting...")
        doc, issue = await make_html(text)
        if not doc:
            await _say(msg, text, "HTML yasab bo'lmadi: " + str(issue) + ". So'rovni biroz aniqroq qilib qayta yuboring.")
            return True
        await _send_html(msg, doc, issue, text, text)
        return True
    return False


# ---------------------------------------------------------------- Buyruqlar (eski usul)
def _make_save_handler(kind: str, label: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_owner(update):
            return
        msg = update.effective_message
        text = " ".join(context.args or []).strip()
        if not text and msg.reply_to_message:
            text = (msg.reply_to_message.text or msg.reply_to_message.caption or "").strip()
        if not text:
            await msg.reply_text("Foydalanish: /" + kind + " matn... (yoki biror xabarga javob qilib yozing)")
            return
        try:
            nid = await asyncio.to_thread(_save_note, kind, text[:4000])
        except Exception as e:
            await msg.reply_text("Saqlab bo'lmadi: " + str(e))
            return
        await _say(msg, "/" + kind + " " + text, label + " saqlandi" + (" (#" + str(nid) + ")." if nid else "."))
    return handler


# ---------------------------------------------------------------- Haftalik jurnal
def _fetch_week():
    since = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
    rows = []
    for kind in ("goya", "qayd", "iqtibos"):  # html_kod yozuvlari jurnalga kirmasin
        r = (_sb.table(TABLE).select("id,kind,text,created_at")
             .eq("owner", _owner_id).eq("kind", kind)
             .gte("created_at", since).order("created_at").execute())
        rows.extend(r.data or [])
    rows.sort(key=lambda x: str(x.get("created_at")))
    return rows


def _loose_json(t: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (t or "").strip(), flags=re.I)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        return json.loads(m.group(0)) if m else None


async def _group_topics(rows):
    """Yozuvlarni mavzularga ajratadi. Gemini ishlamasa, turi bo'yicha guruhlaydi."""
    listing = "\n".join("#" + str(r["id"]) + " [" + str(r["kind"]) + "] " + str(r["text"]) for r in rows)[:12000]
    prompt = (
        "Quyidagi shaxsiy yozuvlarni 2-6 ta mavzuga ajrat. Faqat JSON qaytar:\n"
        '{"topics":[{"title":"qisqa nom","summary":"1-2 gap","ids":[1,2]}],'
        '"insight":"hafta boyicha 1-2 gapli xulosa"}\n'
        "Har bir yozuv bitta mavzuga tushsin. O'zbekcha yoz.\n\n" + listing
    )
    by_id = {r["id"]: r for r in rows}
    try:
        data = _loose_json(await _ask(prompt))
        topics = []
        for t in data.get("topics", []):
            items = [by_id[i] for i in t.get("ids", []) if i in by_id]
            if items:
                topics.append({"title": str(t.get("title", "Mavzu")),
                               "summary": str(t.get("summary", "")), "items": items})
        if topics:
            return topics, str(data.get("insight", ""))
    except Exception:
        pass
    names = {"goya": "G'oyalar", "qayd": "Dars qaydlari", "iqtibos": "Iqtiboslar"}
    topics = []
    for kind, title in names.items():
        items = [r for r in rows if r["kind"] == kind]
        if items:
            topics.append({"title": title, "summary": "", "items": items})
    return topics, ""


def _render_html(topics, insight, start, end):
    cards = []
    for i, t in enumerate(topics):
        big = " big" if i == 0 else ""
        lis = "".join("<li>" + _html.escape(r["text"]) + "</li>" for r in t["items"])
        cards.append(
            '<section class="card' + big + '"><h2>' + _html.escape(t["title"]) + '</h2>'
            '<p class="sum">' + _html.escape(t["summary"]) + '</p><ul>' + lis + '</ul></section>')
    ins = ""
    if insight:
        ins = '<section class="card ins"><h2>Xulosa</h2><p>' + _html.escape(insight) + '</p></section>'
    css = (
        "body{margin:0;padding:16px;background:#0B0F19;color:#fff;font-family:system-ui,sans-serif}"
        "h1{font-size:22px;margin:4px 0 2px}.d{color:#8fa3c0;font-size:13px;margin-bottom:14px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}"
        ".card{background:#141b2d;border:1px solid #1f6feb55;border-radius:16px;padding:14px}"
        ".card.big{grid-column:1/-1;border-color:#00e5ff}.card.ins{border-color:#ffd54a}"
        "h2{font-size:16px;margin:0 0 6px;color:#00e5ff}.ins h2{color:#ffd54a}"
        ".sum{color:#8fa3c0;font-size:13px;margin:0 0 8px}"
        "ul{margin:0;padding-left:18px;font-size:14px;line-height:1.5}"
    )
    return (
        '<!DOCTYPE html><html lang="uz"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Haftalik jurnal</title><style>' + css + '</style></head><body>'
        '<h1>Haftalik jurnal</h1><div class="d">' + start + ' - ' + end + '</div>'
        '<div class="grid">' + "".join(cards) + ins + '</div></body></html>'
    )


def _render_png(topics, insight, start, end) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        for name in ("DejaVuSans.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    W, pad = 1080, 40
    f_t, f_h, f_b = font(44), font(32), font(26)
    blocks = [("Haftalik jurnal", [start + " - " + end], True)]
    for t in topics:
        lines = [textwrap.fill(t["summary"], 52)] if t["summary"] else []
        lines += [textwrap.fill("- " + r["text"], 52) for r in t["items"]]
        blocks.append((t["title"], lines, False))
    if insight:
        blocks.append(("Xulosa", [textwrap.fill(insight, 52)], False))
    H = pad
    for title, lines, _ in blocks:
        H += 60 + sum(34 * (ln.count("\n") + 1) for ln in lines) + 40
    img = Image.new("RGB", (W, max(H, 400)), "#0B0F19")
    d = ImageDraw.Draw(img)
    y = pad
    for title, lines, head in blocks:
        d.text((pad, y), title, font=f_t if head else f_h, fill="#FFFFFF" if head else "#00E5FF")
        y += 60
        for ln in lines:
            for sub in ln.split("\n"):
                d.text((pad, y), sub, font=f_b, fill="#C9D4E5")
                y += 34
        y += 40
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def haftalik_hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    msg = update.effective_message
    try:
        rows = await asyncio.to_thread(_fetch_week)
    except Exception as e:
        await msg.reply_text("Bazadan o'qib bo'lmadi: " + str(e))
        return
    if not rows:
        await _say(msg, "haftalik hisobot",
                   "Oxirgi 7 kunda yozuv yo'q. \"g'oya: ...\", \"qayd: ...\" yoki \"iqtibos: ...\" deb yozing.")
        return
    await msg.reply_text(str(len(rows)) + " ta yozuv topildi, jurnal tayyorlanyapti...")
    topics, insight = await _group_topics(rows)
    end = dt.date.today()
    start = end - dt.timedelta(days=6)
    s, e = start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y")
    html_doc = _render_html(topics, insight, s, e)
    await msg.reply_document(document=io.BytesIO(html_doc.encode("utf-8")),
                             filename="haftalik_jurnal.html", caption="Interaktiv Bento jurnal")
    try:
        png = await asyncio.to_thread(_render_png, topics, insight, s, e)
        await msg.reply_photo(photo=io.BytesIO(png), caption="Haftalik jurnal (rasm)")
    except Exception as ex:
        await msg.reply_text("Rasm yasab bo'lmadi (" + str(ex) + "), lekin HTML jurnal yuqorida.")
    _remember("haftalik hisobot", "Haftalik jurnalni (" + str(len(rows)) + " ta yozuv, " + s + " - " + e
              + ") HTML va rasm qilib yubordim.")


def register(app):
    """Application'ga buyruqlarni qo'shadi."""
    app.add_handler(CommandHandler("goya", _make_save_handler("goya", "G'oya")))
    app.add_handler(CommandHandler("qayd", _make_save_handler("qayd", "Qayd")))
    app.add_handler(CommandHandler("iqtibos", _make_save_handler("iqtibos", "Iqtibos")))
    app.add_handler(CommandHandler("haftalik_hisobot", haftalik_hisobot))


# ---------------------------------------------------------------- ULASH (bot.py ga)
# bot.py'da allaqachon ulangan: setup(), register() va october_chat() boshida try_handle().
# Faqat bir marta: Supabase SQL muharririda SQL_SETUP ni ishga tushirish (bajarilgan).
# Fayllar: october_plus.py, october_core3d.js, october_tasks.py va krossvord_ombor.html bir papkada turishi kerak.
