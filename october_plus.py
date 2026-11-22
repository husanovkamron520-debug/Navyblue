"""october_plus.py - October uchun qo'shimcha modul (bot.py'ga tegmaydi).

Imkoniyatlar:
1. Bilimlar bazasi (Supabase): /goya, /qayd, /iqtibos va /haftalik_hisobot
   (mavzular bo'yicha saralangan haftalik jurnal: Bento HTML + PNG rasm).
2. HTML generator: "ombor 3d", "html sahifa", "infografika" kabi so'rovlarda
   Gemini neon uslubidagi tayyor .html fayl yozadi va bot uni yuboradi.
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

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

TABLE = "kb_notes"

_owner_id = None
_gen = None  # sinxron funksiya: gen(prompt: str) -> str  (Gemini javobi matni)
_sb = None   # Supabase client

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

NEON_PROMPT = """Sen tajribali front-end dasturchisan. Quyidagi so'rov bo'yicha BITTA to'liq, ishlaydigan HTML fayl yoz.
Talablar:
- Faqat bitta fayl: CSS va JS shu fayl ichida. Tashqi kutubxona kerak bo'lsa faqat cdnjs.cloudflare.com dan (masalan three.js r128).
- Neon uslub: to'q fon (#0B0F19), yorqin neon ko'k/pushti/yashil ranglar, yumshoq glow.
- Telefon ekraniga moslash: viewport meta, katta tugmalar, touch bilan ishlasin.
- Interfeys matnlari o'zbekcha bo'lsin.
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


# ---------------------------------------------------------------- HTML generator
def wants_html(text: str) -> bool:
    t = (text or "").lower()
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


async def make_html(request: str):
    """Tayyor HTML matnini qaytaradi; 2 marta urinadi; bo'lmasa None."""
    for _ in range(2):
        try:
            doc = _clean_html(await _ask(NEON_PROMPT.format(req=request)))
        except Exception:
            doc = None
        if doc:
            return doc
    return None


async def try_handle(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """october_chat() boshida chaqiring: True qaytsa, so'rov shu yerda hal bo'lgan."""
    if not _is_owner(update) or not wants_html(text):
        return False
    msg = update.effective_message
    await msg.reply_text("HTML yozyapman, bir oz kuting...")
    doc = await make_html(text)
    if not doc:
        await msg.reply_text("HTML yasab bo'lmadi: Gemini yaroqli fayl qaytarmadi. "
                             "Iltimos, so'rovni biroz aniqroq qilib qayta yuboring.")
        return True
    data = io.BytesIO(doc.encode("utf-8"))
    await msg.reply_document(document=data, filename="october.html",
                             caption="Tayyor. Faylni brauzerda oching.")
    return True


# ---------------------------------------------------------------- Bilimlar bazasi
def _save_note(kind: str, text: str):
    r = _sb.table(TABLE).insert({"owner": _owner_id, "kind": kind, "text": text}).execute()
    rows = r.data or []
    return rows[0].get("id") if rows else None


def _make_save_handler(kind: str, label: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_owner(update):
            return
        msg = update.effective_message
        text = " ".join(context.args or []).strip()
        if not text and msg.reply_to_message:
            text = (msg.reply_to_message.text or msg.reply_to_message.caption or "").strip()
        if not text:
            await msg.reply_text(f"Foydalanish: /{kind} matn... (yoki biror xabarga javob qilib yozing)")
            return
        try:
            nid = await asyncio.to_thread(_save_note, kind, text[:4000])
        except Exception as e:
            await msg.reply_text(f"Saqlab bo'lmadi: {e}")
            return
        await msg.reply_text(f"{label} saqlandi" + (f" (#{nid})." if nid else "."))
    return handler


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
    listing = "\n".join(f"#{r['id']} [{r['kind']}] {r['text']}" for r in rows)[:12000]
    prompt = (
        "Quyidagi shaxsiy yozuvlarni 2-6 ta mavzuga ajrat. Faqat JSON qaytar:\n"
        '{"topics":[{"title":"qisqa nom","summary":"1-2 gap","ids":[1,2]}],'
        '"insight":"hafta bo\'yicha 1-2 gapli xulosa"}\n'
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
        lis = "".join(f"<li>{_html.escape(r['text'])}</li>" for r in t["items"])
        cards.append(
            f'<section class="card{big}"><h2>{_html.escape(t["title"])}</h2>'
            f'<p class="sum">{_html.escape(t["summary"])}</p><ul>{lis}</ul></section>')
    ins = f'<section class="card ins"><h2>Xulosa</h2><p>{_html.escape(insight)}</p></section>' if insight else ""
    return f"""<!DOCTYPE html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Haftalik jurnal</title><style>
body{{margin:0;padding:16px;background:#0B0F19;color:#fff;font-family:system-ui,sans-serif}}
h1{{font-size:22px;margin:4px 0 2px}}.d{{color:#8fa3c0;font-size:13px;margin-bottom:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.card{{background:#141b2d;border:1px solid #1f6feb55;border-radius:16px;padding:14px}}
.card.big{{grid-column:1/-1;border-color:#00e5ff}}.card.ins{{border-color:#ffd54a}}
h2{{font-size:16px;margin:0 0 6px;color:#00e5ff}}.ins h2{{color:#ffd54a}}
.sum{{color:#8fa3c0;font-size:13px;margin:0 0 8px}}ul{{margin:0;padding-left:18px;font-size:14px;line-height:1.5}}
</style></head><body><h1>Haftalik jurnal</h1><div class="d">{start} - {end}</div>
<div class="grid">{''.join(cards)}{ins}</div></body></html>"""


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
    blocks = [("Haftalik jurnal", [f"{start} - {end}"], True)]
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
        d.text((pad, y), title, font=f_t if head else f_h, fill="#00E5FF" if not head else "#FFFFFF")
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
        await msg.reply_text(f"Bazadan o'qib bo'lmadi: {e}")
        return
    if not rows:
        await msg.reply_text("Oxirgi 7 kunda yozuv yo'q. /goya, /qayd yoki /iqtibos bilan qo'shing.")
        return
    await msg.reply_text(f"{len(rows)} ta yozuv topildi, jurnal tayyorlanyapti...")
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
        await msg.reply_text(f"Rasm yasab bo'lmadi ({ex}), lekin HTML jurnal yuqorida.")


def register(app):
    """Application'ga buyruqlarni qo'shadi."""
    app.add_handler(CommandHandler("goya", _make_save_handler("goya", "G'oya")))
    app.add_handler(CommandHandler("qayd", _make_save_handler("qayd", "Qayd")))
    app.add_handler(CommandHandler("iqtibos", _make_save_handler("iqtibos", "Iqtibos")))
    app.add_handler(CommandHandler("haftalik_hisobot", haftalik_hisobot))


# ---------------------------------------------------------------- ULASH (bot.py ga)
# 1) Supabase SQL muharririda SQL_SETUP ni bir marta ishga tushiring.
# 2) bot.py boshida:   import october_plus
# 3) Application yaratilgandan keyin (Gemini'ga matn yuboradigan sinxron
#    funksiyangiz va Supabase client nomini o'zingiznikiga almashtiring):
#        october_plus.setup(OWNER_ID, gemini_matn_funksiyasi, supabase_client)
#        october_plus.register(app)
# 4) october_chat() funksiyasi boshiga:
#        if await october_plus.try_handle(update, context, text):
#            return
# 5) _oct_parse_sync ichidagi "Qoidalar:" ro'yxatiga october_plus.HONESTY_RULES qo'shing.
