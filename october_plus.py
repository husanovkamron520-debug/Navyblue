"""october_plus.py - October uchun qo'shimcha modul.

Imkoniyatlar:
1. Bilimlar bazasi (Supabase). Buyruqsiz ham ishlaydi:
     g'oya: matn            -> g'oya sifatida saqlaydi (qayd:, iqtibos: ham shunday)
     oxirgi 5 xabarim g'oya -> oxirgi 5 ta xabarni g'oya qilib saqlaydi
     haftalik hisobot       -> mavzular bo'yicha jurnal (Bento HTML + PNG rasm)
   Eski /goya, /qayd, /iqtibos, /haftalik_hisobot buyruqlari ham ishlayveradi.
2. HTML generator: "ombor 3d", "html sahifa", "infografika" kabi so'rovlarda
   Gemini neon uslubidagi tayyor .html fayl yozadi, sifatini tekshiradi va yuboradi.
3. Halollik qoidasi: October bajara olmagan ishini "ha" deb o'tkazib yubormaydi.

Ulash: pastdagi "ULASH" bo'limiga qarang.
"""
import asyncio
import datetime as dt
import html as _html
import io
import json
import re
import textwrap
from collections import deque

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

TABLE = "kb_notes"

_owner_id = None
_gen = None  # sinxron funksiya: gen(prompt: str) -> str  (Gemini javobi matni)
_sb = None   # Supabase client (yoki .table().insert().execute() qo'llaydigan adapter)

# Egasining oxirgi xabarlari ("oxirgi 5 xabarim g'oya" uchun). Bot qayta ishga tushsa tozalanadi.
_recent = deque(maxlen=50)

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
Talablar:
- Faqat bitta fayl: CSS va JS shu fayl ichida. Tashqi kutubxona kerak bo'lsa faqat cdnjs.cloudflare.com dan (masalan three.js r128).
- Neon uslub: to'q fon (#0B0F19), yorqin neon ko'k/pushti/yashil ranglar, yumshoq glow.
- Telefon ekraniga moslash: viewport meta, katta tugmalar, touch bilan ishlasin.
- Interfeys matnlari o'zbekcha bo'lsin.
- Kod TO'LIQ bo'lsin: "...", "shu yerga qo'shing", TODO kabi to'ldirilmagan joy qoldirma.
- O'yin yoki simulyator bo'lsa: boshlash tugmasi, ball/holat ko'rsatkichi, aniq maqsad va qayta boshlash tugmasi bo'lsin.
- Yozishdan oldin kod mantiqini ichingda tekshirib chiq (o'zgaruvchi nomlari, yopilmagan teglar).
- Javobda FAQAT HTML kod bo'lsin: izoh yoki ``` belgilarisiz. <!DOCTYPE html> bilan boshlanib </html> bilan tugasin.
So'rov: {req}"""


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


def _quality_issue(doc: str, req: str):
    """Aniq kamchilik bo'lsa matn, yaxshi bo'lsa None."""
    low = doc.lower()
    if low.count("<script") != low.count("</script>"):
        return "<script> teglari to'g'ri yopilmagan"
    if "<script" not in low and any(w in _norm(req) for w in _INTERACTIVE_WORDS):
        return "JavaScript yo'q, sahifa interaktiv emas"
    if re.search(r"(//|/\*|<!--)\s*(\.\.\.|todo|shu yerga|bu yerga|qolgan kod)", low):
        return "kodda to'ldirilmagan joylar (placeholder) bor"
    return None


async def make_html(request: str):
    """(doc, kamchilik) qaytaradi. 3 marta urinadi; yaroqli HTML chiqmasa (None, sabab)."""
    issue = None
    best = None
    for attempt in range(3):
        prompt = NEON_PROMPT.format(req=request)
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
        best = doc
        issue = _quality_issue(doc, request)
        if not issue:
            return doc, None
    return best, issue


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


def _kind_of(word: str) -> str:
    return "goya" if word.startswith("g") else word


_LABEL = {"goya": "G'oya", "qayd": "Qayd", "iqtibos": "Iqtibos"}


def _save_note(kind: str, text: str):
    r = _sb.table(TABLE).insert({"owner": _owner_id, "kind": kind, "text": text}).execute()
    rows = r.data or []
    return rows[0].get("id") if rows else None


async def _save_many(msg, kind: str, texts):
    saved, failed = 0, 0
    for t in texts:
        try:
            await asyncio.to_thread(_save_note, kind, t[:4000])
            saved += 1
        except Exception:
            failed += 1
    name = _LABEL[kind].lower()
    if failed:
        await msg.reply_text(str(saved) + " ta " + name + " saqlandi, " + str(failed) + " tasi saqlanmadi (baza xatosi).")
    else:
        await msg.reply_text(str(saved) + " ta " + name + " saqlandi.")


async def try_handle(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """october_chat() boshida chaqiring: True qaytsa, so'rov shu yerda hal bo'lgan."""
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
            await msg.reply_text("Oldingi xabarlaringiz esimda yo'q (bot qayta ishga tushgan bo'lishi mumkin). "
                                 "Ularni \"g'oya: matn\" ko'rinishida yuboring.")
            return True
        if len(texts) < n:
            await msg.reply_text("Faqat " + str(len(texts)) + " ta xabar esimda, shularni saqlayman.")
        await _save_many(msg, _kind_of(m.group(2)), texts)
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
                await msg.reply_text("Saqlab bo'lmadi: " + str(e))
                return True
            await msg.reply_text(_LABEL[kind] + " saqlandi" + (" (#" + str(nid) + ")." if nid else "."))
            return True

    # 3) "haftalik hisobot"
    if len(t) < 40 and re.search(r"haftalik\s+(hisobot|jurnal)", t):
        await haftalik_hisobot(update, context)
        return True

    # 4) HTML
    if wants_html(text):
        await msg.reply_text("HTML yozyapman, bir oz kuting...")
        doc, issue = await make_html(text)
        if not doc:
            await msg.reply_text("HTML yasab bo'lmadi: " + str(issue) + ". So'rovni biroz aniqroq qilib qayta yuboring.")
            return True
        caption = "Tayyor. Faylni brauzerda oching."
        if issue:
            caption = "Tayyor, lekin ogohlantirish: " + issue + ". Ishlamasa, ayting, qayta yozdiraman."
        await msg.reply_document(document=io.BytesIO(doc.encode("utf-8")),
                                 filename="october.html", caption=caption)
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
        await msg.reply_text(label + " saqlandi" + (" (#" + str(nid) + ")." if nid else "."))
    return handler


# ---------------------------------------------------------------- Haftalik jurnal
def _fetch_week():
    since = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
    r = (_sb.table(TABLE).select("id,kind,text,created_at")
         .eq("owner", _owner_id).gte("created_at", since)
         .order("created_at").execute())
    return r.data or []


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
        await msg.reply_text("Oxirgi 7 kunda yozuv yo'q. \"g'oya: ...\", \"qayd: ...\" yoki \"iqtibos: ...\" deb yozing.")
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


def register(app):
    """Application'ga buyruqlarni qo'shadi."""
    app.add_handler(CommandHandler("goya", _make_save_handler("goya", "G'oya")))
    app.add_handler(CommandHandler("qayd", _make_save_handler("qayd", "Qayd")))
    app.add_handler(CommandHandler("iqtibos", _make_save_handler("iqtibos", "Iqtibos")))
    app.add_handler(CommandHandler("haftalik_hisobot", haftalik_hisobot))


# ---------------------------------------------------------------- ULASH (bot.py ga)
# 1) Supabase SQL muharririda SQL_SETUP ni bir marta ishga tushiring.
# 2) bot.py boshida:   import october_plus
# 3) october_plus.setup(OWNER_ID, gemini_matn_funksiyasi, supabase_client)
#    october_plus.register(app)
# 4) october_chat() funksiyasi boshiga:
#        if await october_plus.try_handle(update, context, text):
#            return
# 5) _oct_parse_sync ichidagi "Qoidalar:" ro'yxatiga october_plus.HONESTY_RULES qo'shing.
