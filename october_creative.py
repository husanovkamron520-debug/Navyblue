"""October Creative Builder: image-aware HTML and Three.js projects."""
import asyncio, base64, io, re, time

_owner_id = _gen = _vision = None
_last = {"html": None}
_BUILD = re.compile(r"\b(html|3d|sayyora|sayyoralar|xona|ombor|simulyator|interaktiv|sahifa|sayt|veb|web|website|portfolio|landing|animatsiya|kosmos|galaktika|dizayn)\b", re.I)
_IMAGE = re.compile(r"(rasm|surat|photo|image)", re.I)
_EDIT = re.compile(r"(o.?zgartir|qo.?sh|olib tashla|rangini|joylashtir|devorga|devorini|foniga|fonini|ichiga|ustiga|kengaytir|toraytir|yoritishni)", re.I)
_NEW_REQUEST = re.compile(r"(yarat|yasab ber|qurib ber|yangisini|yangi loyiha|boshidan)", re.I)
_DONE = {"tayyor", "bo'ldi", "boldi", "tamom", "boshlayver"}
_CANCEL = {"bekor", "bekor qil", "to'xta", "stop"}

def setup(owner_id, generate_text, analyze_image):
    global _owner_id, _gen, _vision
    _owner_id, _gen, _vision = int(owner_id), generate_text, analyze_image

def _owner(update):
    u = update.effective_user
    return bool(u and _owner_id is not None and u.id == _owner_id)

def wants_builder(text):
    return bool(text and not text.lstrip().startswith("/") and _BUILD.search(text))

def is_edit_request(text, has_project=True):
    return bool(has_project and _EDIT.search(text or "") and not _NEW_REQUEST.search(text or ""))

def _compress(raw, mime):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)); im.thumbnail((1400, 1400))
        out = io.BytesIO()
        if im.mode in ("RGBA", "LA") and "png" in (mime or ""):
            im.save(out, "PNG", optimize=True); return out.getvalue(), "image/png"
        if im.mode != "RGB": im = im.convert("RGB")
        im.save(out, "JPEG", quality=82, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return raw, mime or "image/jpeg"

async def handle_image(update, context, raw, mime, filename):
    if not _owner(update) or not context.user_data.get("_ocb_pending") or not (mime or "").startswith("image/"):
        return False
    items = context.user_data.setdefault("_ocb_images", [])
    if len(items) >= 4:
        await update.effective_message.reply_text("Ko'pi bilan 4 ta rasm qabul qilaman. «Tayyor» deb yozing.")
        return True
    data, kind = await asyncio.to_thread(_compress, raw, mime)
    if sum(len(x["data"]) for x in items) + len(data) > 8 * 1024 * 1024:
        await update.effective_message.reply_text("Rasmlar siqilgandan keyin ham jami 8 MB dan oshdi. Kichikroq rasm yuboring.")
        return True
    items.append({"data": data, "mime": kind, "name": filename or "reference"})
    await update.effective_message.reply_text("🖼 Rasm qabul qilindi (" + str(len(items)) + "/4). Tugatgach «tayyor» deb yozing.")
    return True

def _data_uri(item):
    return "data:" + item["mime"] + ";base64," + base64.b64encode(item["data"]).decode("ascii")

def _extract_embedded(doc):
    saved = []
    pat = re.compile(r"data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\s]+", re.I)
    def repl(m):
        token = "__OCTOBER_OLD_IMAGE_" + str(len(saved)) + "__"
        saved.append(m.group(0).replace("\n", "").replace(" ", ""))
        return token
    return pat.sub(repl, doc or ""), saved

def _html(raw):
    raw = re.sub(r"^```(?:html)?\s*|\s*```$", "", (raw or "").strip(), flags=re.I).strip()
    a = raw.lower().find("<!doctype")
    if a < 0: a = raw.lower().find("<html")
    b = raw.lower().rfind("</html>")
    return raw[a:b+7] if a >= 0 and b > a and b+7-a > 1000 else None

def _repair(doc):
    if not re.search(r"<meta[^>]+charset", doc, re.I):
        doc = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + '<meta charset="utf-8">', doc, count=1, flags=re.I)
    if not re.search(r"<meta[^>]+name=[\"']viewport", doc, re.I):
        doc = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + '<meta name="viewport" content="width=device-width,initial-scale=1">', doc, count=1, flags=re.I)
    return doc

def _check(doc, req, images, existing=None):
    low = doc.lower()
    if "</html>" not in low or "<body" not in low or "</body>" not in low:
        return "HTML hujjati to'liq emas"
    if low.count("<script") != low.count("</script>"):
        return "JavaScript teglari yopilmagan"
    needs_three = bool(
        re.search(r"\b3d\b|sayyora|kosmos|xona|ombor", req, re.I)
        or (existing and ("three.module.js" in existing.lower() or "webglrenderer" in existing.lower()))
    )
    if needs_three:
        required = {
            "Three.js moduli": r"three\.module\.js|from\s*['\"]three['\"]",
            "WebGL renderer": r"new\s+THREE\.WebGLRenderer",
            "3D sahna": r"new\s+THREE\.Scene",
            "kamera": r"new\s+THREE\.(PerspectiveCamera|OrthographicCamera)",
            "kamera renderga ulanishi": r"renderer\.render\s*\(\s*scene\s*,\s*camera",
            "animatsiya sikli": r"requestAnimationFrame",
            "renderer DOMga ulanishi": r"appendChild\s*\(\s*renderer\.domElement",
            "3D geometriya": r"THREE\.(SphereGeometry|BoxGeometry|CylinderGeometry|TorusGeometry|PlaneGeometry)",
            "yoritish": r"THREE\.(AmbientLight|HemisphereLight|DirectionalLight|PointLight)",
        }
        for label, pattern in required.items():
            if not re.search(pattern, doc, re.I):
                return label + " yo'q — sahna haqiqiy ishlaydigan 3D emas"
        if not re.search(r"new\s+THREE\.Mesh", doc):
            return "3D obyekt mesh ko'rinishida yaratilmagan"
        if not re.search(r"renderer\.setSize|renderer\.setPixelRatio", doc):
            return "Renderer o'lchami sozlanmagan"
        if re.search(r"sayyor|planet|kosmos", req, re.I):
            if len(re.findall(r"new\s+THREE\.SphereGeometry", doc)) < 2:
                return "Sayyoralar uchun kamida ikkita alohida sfera geometriyasi yaratilmagan"
    for i in range(len(images)):
        token = "__OCTOBER_IMAGE_" + str(i) + "__"
        if token not in doc:
            return "Yuborilgan " + str(i+1) + "-rasm HTMLga kiritilmagan"
        escaped = re.escape(token)
        placed = (
            re.search(r"(?:src|map)\s*[:=]\s*['\"]?" + escaped, doc, re.I)
            or re.search(r"\.load\s*\(\s*['\"]" + escaped, doc, re.I)
            or re.search(r"setAttribute\s*\(\s*['\"]src['\"]\s*,\s*['\"]" + escaped, doc, re.I)
        )
        if not placed:
            return "Yuborilgan rasm haqiqiy img yoki 3D texture sifatida joylashtirilmagan"
    if images and re.search(r"<input[^>]+type\s*=\s*['\"]file|rasm tanlash|choose file|upload image", doc, re.I):
        return "Rasmni yuklash paneli emas, yuborilgan suratning o'zi ko'rsatilishi kerak"
    return None

async def _vision_text(images, request):
    out = []
    for i, item in enumerate(images):
        if not _vision: raise RuntimeError("Rasm tahlili sozlanmagan")
        desc = await asyncio.to_thread(_vision, item["data"], item["mime"], request)
        out.append("RASM " + str(i) + " token=__OCTOBER_IMAGE_" + str(i) + "__: " + str(desc or "")[:1500])
    return out

def _prompt(req, descriptions, existing):
    img = ""
    if descriptions:
        img = "\nRASMLAR:\n" + "\n".join(descriptions) + (
            "\nHar bir rasmni aynan ko'rsatilgan joyga joylashtir. Tokenni img src yoki Three.js TextureLoader ichida ishlat. "
            "3D sahnada poster, ramka yoki texture plane bo'lishi mumkin. Oddiy suratni haqiqiy 3D geometriyaga aylantirdim deb da'vo qilma."
        )
    old = ""
    if existing:
        compact, _ = _extract_embedded(existing)
        old = "\nMAVJUD LOYIHA KODI (uni saqla va faqat so'ralgan o'zgarishni kirit):\n" + compact[:50000]
    three = bool(re.search(r"\b3d\b|sayyora|kosmos|xona|ombor", req, re.I) or (existing and ("three.module.js" in existing.lower() or "webglrenderer" in existing.lower())))
    rules = (
        "Haqiqiy Three.js WebGL sahnasi qur. Three.js r160 va OrbitControls ni jsDelivr import map orqali yukla; "
        "responsive renderer, kamera, yoritish, materiallar va mouse/touch orbit-zoom bo'lsin. Internet kerakligini hisobga ol.\n"
        if three else "3D so'ralmagan bo'lsa, ortiqcha 3D qo'shma.\n"
    )
    return (
        "Sen senior creative developer. Foydalanuvchi aytgan loyihani yarat yoki mavjudini tahrirla. Faqat to'liq HTML qaytar.\n"
        "Talablar: aytilgan obyekt, matn, rang va joylashuvlarni aynan bajar; zamonaviy, mobil/desktop responsive UI; "
        "barcha tugmalar ishlasin; o'zbekcha matn; TODO yoki soxta funksiya yo'q; bitta HTML fayl; "
        "remote rasm/font/script ishlatma, faqat Three.js CDN mumkin; rasm tokenlarini aynan saqla. "
        "Foydalanuvchi yuborgan rasmni sahnada darhol ko'rsat; file input, rasm tanlash paneli yoki bo'sh placeholder yasama. "
        "Hech qachon faqat sarlavha va qora fon bilan tugatma.\\n" + rules + img + old +
        "\nTOPSHIRIQ:\n" + req + "\n<!DOCTYPE html> dan </html> gacha kod qaytar."
    )

async def _generate(req, images, existing=None):
    desc = await _vision_text(images, req)
    prompt = _prompt(req, desc, existing)
    issue = None
    best = None
    for _ in range(3):
        raw = await asyncio.to_thread(_gen, prompt + (("\nTekshiruv xatosi: " + issue + ". Tuzatib to'liq HTML qaytar.") if issue else ""))
        doc = _html(raw)
        if not doc:
            issue = "HTML kodi to'liq qaytmadi"; continue
        doc = _repair(doc)
        issue = _check(doc, req, images, existing); best = doc
        if not issue and existing:
            compact_old, old_images_check = _extract_embedded(existing)
            for old_i in range(len(old_images_check)):
                if "__OCTOBER_OLD_IMAGE_" + str(old_i) + "__" not in doc:
                    issue = "Mavjud loyihadagi rasm saqlanmagan"
                    break
        if not issue:
            for i, item in enumerate(images):
                doc = doc.replace("__OCTOBER_IMAGE_" + str(i) + "__", _data_uri(item))
            if existing:
                _, old_images = _extract_embedded(existing)
                for i, uri in enumerate(old_images):
                    doc = doc.replace("__OCTOBER_OLD_IMAGE_" + str(i) + "__", uri)
            return doc, None
    if best:
        for i, item in enumerate(images):
            best = best.replace("__OCTOBER_IMAGE_" + str(i) + "__", _data_uri(item))
    return best, issue

async def _send(msg, context, doc, req, issue):
    global _last
    _last = {"html": doc}
    context.user_data["_ocb_last_html"] = doc
    context.user_data.pop("_ocb_pending", None); context.user_data.pop("_ocb_images", None)
    caption = "✅ Loyiha tayyor. HTML faylni yuklab olib Chrome'da oching."
    if issue: caption += "\n⚠️ Statik tekshiruv ogohlantirishi: " + issue + ". Brauzerda ham tekshiring."
    await msg.reply_document(document=io.BytesIO(doc.encode("utf-8")), filename="creative_project.html", caption=caption)

async def _run(msg, context, req, edit=False):
    imgs = context.user_data.get("_ocb_images") or []
    existing = (context.user_data.get("_ocb_last_html") or _last.get("html")) if edit else None
    status = await msg.reply_text("🧠 Talablarni tahlil qilib, loyihani yaratyapman...")
    try:
        doc, issue = await asyncio.wait_for(_generate(req, imgs, existing), timeout=240)
        if not doc:
            await status.edit_text("HTML yaratilmadi: to'liq kod olinmadi. Vazifani qismlarga ajrating."); return
        await _send(msg, context, doc, req, issue)
        try: await status.delete()
        except Exception: pass
    except Exception as exc:
        try: await status.edit_text("Loyiha yaratishda xato: " + str(exc)[:220])
        except Exception: pass

async def try_handle(update, context, text):
    if not _owner(update): return False
    msg = update.effective_message
    t = (text or "").strip(); low = t.lower()
    pending = context.user_data.get("_ocb_pending")
    imgs = context.user_data.get("_ocb_images") or []
    if pending and low in _DONE:
        if not imgs:
            await msg.reply_text("Hali rasm kelmadi. Avval rasm yuboring yoki «bekor» deb yozing."); return True
        await _run(msg, context, pending["request"], pending.get("edit", False)); return True
    if pending and low in _CANCEL:
        context.user_data.pop("_ocb_pending", None); context.user_data.pop("_ocb_images", None)
        await msg.reply_text("Loyiha yaratish bekor qilindi."); return True
    if pending and not low.startswith("/"):
        pending["request"] += "\nQo'shimcha ko'rsatma: " + t
        await msg.reply_text("Ko'rsatma qo'shildi. Rasm yuboring yoki «tayyor» deb yozing."); return True
    last = context.user_data.get("_ocb_last_html") or _last.get("html")
    if last and _IMAGE.search(t) and is_edit_request(t, True):
        context.user_data["_ocb_pending"] = {"request": "Mavjud loyihaga o'zgarish kirit: " + t, "edit": True}
        context.user_data["_ocb_images"] = []
        await msg.reply_text("Rasmni yuboring; mavjud loyihaga joylashtiraman. Tugatgach «tayyor» deb yozing."); return True
    if is_edit_request(t, bool(last)) and len(t) < 700:
        await _run(msg, context, "Mavjud loyihani o'zgartir: " + t, True); return True
    if not wants_builder(t): return False
    if _IMAGE.search(t):
        context.user_data["_ocb_pending"] = {"request": t, "edit": False}
        context.user_data["_ocb_images"] = []
        await msg.reply_text("Rasmni yuboring. Bir nechta rasm yuborishingiz mumkin; tugatgach «tayyor» deb yozing."); return True
    await _run(msg, context, t, False)
    return True
