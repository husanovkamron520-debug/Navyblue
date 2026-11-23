"""October Creative Builder: image-aware HTML and Three.js projects."""
import asyncio, base64, io, logging, re, time

import creative_template_engine as _template_engine

logger = logging.getLogger(__name__)

_owner_id = _gen = _vision = None
_load_state = _save_state = None
_last = {"html": None}
_PROJECTS_KEY = "october_creative_projects.json"
_PROJECT_MAX_BYTES = 4 * 1024 * 1024
_project_cache = {}
_BUILD = re.compile(r"\b(html|3d|sayyora|sayyoralar|xona|ombor|simulyator|interaktiv|sahifa|sayt|veb|web|website|portfolio|landing|animatsiya|kosmos|galaktika|dizayn)\b", re.I)
_IMAGE = re.compile(r"(rasm|surat|photo|image)", re.I)
_EDIT = re.compile(r"(o.?zgartir|qo.?sh|olib tashla|rangini|joylashtir|devorga|devorini|foniga|fonini|ichiga|ustiga|kengaytir|toraytir|yoritishni)", re.I)
_NEW_REQUEST = re.compile(r"(yarat|yasab ber|qurib ber|yangisini|yangi loyiha|boshidan)", re.I)
_DONE = {"tayyor", "bo'ldi", "boldi", "tamom", "boshlayver"}
_CANCEL = {"bekor", "bekor qil", "to'xta", "stop"}

def setup(owner_id, generate_text, analyze_image, load_state=None, save_state=None):
    global _owner_id, _gen, _vision, _load_state, _save_state
    _owner_id, _gen, _vision = int(owner_id), generate_text, analyze_image
    _load_state, _save_state = load_state, save_state

def _project_record():
    key = str(_owner_id)
    if key in _project_cache:
        return _project_cache[key]
    state = {}
    if _load_state:
        try:
            state = _load_state(_PROJECTS_KEY, {}) or {}
        except Exception:
            state = {}
    record = state.get(key) if isinstance(state, dict) else None
    record = record if isinstance(record, dict) else {}
    _project_cache[key] = record
    return record

def _persist_project(doc, request):
    size = len(doc.encode("utf-8"))
    record = {"request": (request or "")[:5000], "updated_at": int(time.time()),
              "bytes": size, "html": doc if size <= _PROJECT_MAX_BYTES else None}
    _project_cache[str(_owner_id)] = record
    if _save_state:
        try:
            state = _load_state(_PROJECTS_KEY, {}) if _load_state else {}
            state = state if isinstance(state, dict) else {}
            state[str(_owner_id)] = record
            _save_state(_PROJECTS_KEY, state)
        except Exception:
            pass
    return record

def _restore_project(context):
    doc = context.user_data.get("_ocb_last_html")
    if doc:
        return doc
    doc = _project_record().get("html")
    if doc:
        context.user_data["_ocb_last_html"] = doc
        return doc
    return None

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
    # Repair common LLM typos in the Three.js CDN host before saving/sending HTML.
    doc = doc.replace("cdn.jsdelivr.5net", "cdn.jsdelivr.net")
    doc = doc.replace("jsdelivr.5net", "jsdelivr.net")
    doc = doc.replace("cdn.jsdelivr,net", "cdn.jsdelivr.net")
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
        mesh_count = len(re.findall(r"new\s+THREE\.Mesh\s*\(", doc))
        add_count = len(re.findall(r"scene\.add\s*\(", doc))
        if re.search(r"sayyor|planet|kosmos", req, re.I):
            if len(re.findall(r"new\s+THREE\.SphereGeometry\s*\(", doc)) < 2 or mesh_count < 2 or add_count < 2:
                return "Sayyora sahnasida kamida ikkita alohida sfera, mesh va scene.add bo'lishi shart"
        if re.search(r"\bxona\b|room|interyer", req, re.I) and (mesh_count < 5 or add_count < 5):
            return "3D xona yetarlicha qurilmagan: pol, devor va mebellar alohida 3D obyekt bo'lishi kerak"
        if re.search(r"ombor|warehouse|zavod|factory", req, re.I) and (mesh_count < 5 or add_count < 5):
            return "3D ombor/zavod sahnasida stellaj, pol va obyektlar yetarli emas"
        if not re.search(r"OrbitControls|enableDamping", doc, re.I):
            return "3D sahnada kamerani aylantirish/zoom boshqaruvi yo'q"
        if not re.search(r"addEventListener\s*\(\s*['\"]resize", doc, re.I):
            return "3D sahna ekran o'lchamiga moslashmaydi"
        template_id, _ = _template_engine.select_template(req)
        if template_id == "cosmos_3d":
            cinematic_checks = {
                "procedural texture": r"CanvasTexture|getContext",
                "surface relief": r"bumpMap|normalMap|displacementMap",
                "bloom": r"EffectComposer|UnrealBloomPass",
                "atmosphere/nebula": r"ShaderMaterial|Fresnel|fresnel",
                "asteroids": r"InstancedMesh|asteroid",
                "camera fly-to": r"lerpVectors|lerp|flyTo|fly-to",
                "mobile pixel-ratio cap": r"setPixelRatio|MAX_PIXEL_RATIO|pixelRatio",
                "error fallback": r"catch|onerror|xato|yuklanmadi",
            }
            for label, pattern in cinematic_checks.items():
                if not re.search(pattern, doc, re.I):
                    return "Cinematic 3D talabi bajarilmagan: " + label
            if not re.search(r"castShadow", doc) or not re.search(r"receiveShadow", doc):
                return "Quyosh tizimida castShadow/receiveShadow sozlamalari yo'q"
            if not re.search(r"MeshPhysicalMaterial|MeshStandardMaterial", doc):
                return "Fizik yoritiladigan sayyora materiali yo'q"
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
        "Haqiqiy Three.js WebGL sahnasi qur. Three.js r160 va OrbitControls ni quyidagi importmap bilan yukla; URL'larni aynan, biror belgi o'zgartirmasdan yoz: " +
        "three: https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js; " +
        "three/addons/: https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/. " +
        "Domen faqat cdn.jsdelivr.net bo'lsin; cdn.jsdelivr.5net yoki boshqa variant mutlaqo taqiqlanadi. "
        "responsive renderer, kamera, yoritish, materiallar, OrbitControls bilan mouse/touch orbit-zoom va resize handler bo'lsin. "
        "Sayyora so'ralganda kamida 2 ta alohida SphereGeometry, 2 ta Mesh va 2 ta scene.add yarat. "
        "Xona so'ralganda pol, devorlar va mebellarni ifodalovchi kamida 5 ta Mesh yarat; ombor/zavodda kamida 5 ta Mesh (stellaj, pallet, quti va boshqalar) bo'lsin. "
        "Faqat sarlavha, qora fon yoki bitta dekorativ shar bilan cheklanma. Internet kerakligini hisobga ol.\n"
        if three else "3D so'ralmagan bo'lsa, ortiqcha 3D qo'shma.\n"
    )
    starter = _template_engine.template_prompt(req)
    template_id, _ = _template_engine.select_template(req)
    cinematic = ""
    if template_id == "cosmos_3d":
        cinematic = (
            "\\nCINEMATIC 3D ENGINE — COSMOS UCHUN: NASA/Interstellar ruhidagi vizualizatsiya. "
            "Sayyoralar procedural CanvasTexture, qatlamli rang/noise va bumpMap yoki normalMap relyefi bilan; Quyosh emissive animatsiyalanuvchi plasma. "
            "EffectComposer + RenderPass + UnrealBloomPass bloom; addon ishlamasa base renderer fallback. "
            "Fresnel/ShaderMaterial atmosfera; oq nuqtalar o'rniga rangli yarim shaffof qatlamli nebula. "
            "Quyosh PointLight, MeshPhysicalMaterial yoki MeshStandardMaterial, day/night terminator, castShadow/receiveShadow va Saturn ring geometry. "
            "Mars-Yupiter oralig'ida asteroid belt uchun InstancedMesh, minglab alohida Mesh emas. "
            "Planet click/raycasting bilan tanlansin; kamera position/target silliq lerp bilan yaqinlashsin, OrbitControls saqlansin. "
            "Mobil DPR 1.5-2 bilan cheklansin, asteroid va bloom sifati moslashtirilsin. Loading indicator va tushunarli xato paneli; WebGL/import xatosida qora ekran yoki cheksiz loading bo'lmasin. "
            "Har bir effekt comment emas, ishlaydigan kod bo'lsin.\\n"
        )
    return (
        "Sen senior creative developer. Foydalanuvchi aytgan loyihani yarat yoki mavjudini tahrirla. Faqat to'liq HTML qaytar.\n"
        "Talablar: aytilgan obyekt, matn, rang va joylashuvlarni aynan bajar; zamonaviy, mobil/desktop responsive UI; "
        "barcha tugmalar ishlasin; o'zbekcha matn; TODO yoki soxta funksiya yo'q; bitta HTML fayl; "
        "remote rasm/font/script ishlatma, faqat Three.js CDN mumkin; rasm tokenlarini aynan saqla. "
        "Foydalanuvchi yuborgan rasmni sahnada darhol ko'rsat; file input, rasm tanlash paneli yoki bo'sh placeholder yasama. "
        "Hech qachon faqat sarlavha va qora fon bilan tugatma.\\n" + starter + "\\n" + rules + cinematic + img + old +
        "\nTOPSHIRIQ:\n" + req + "\n<!DOCTYPE html> dan </html> gacha kod qaytar."
    )

async def _continue_html(raw, remaining=2):
    """Continue a truncated HTML response without regenerating its completed prefix."""
    combined = (raw or "").strip()
    remaining = max(0, int(remaining))
    while remaining and not _html(combined):
        if not re.search(r"<!doctype\s+html|<html\b", combined, re.I):
            break
        anchor = combined[-240:]
        continuation_prompt = (
            "Oldingi HTML javobi token chegarasida uzildi. Boshidan yaratma, aynan uzilgan joyidan davom ettir. "
            "Javobni quyidagi oxirgi qismni aynan bir marta takrorlashdan boshla, keyin darhol davom etib </html> bilan tugat. "
            "Izoh yoki yangi doctype qo'shma.\nOXIRGI QISM:\n" + anchor
        )
        remaining -= 1
        try:
            part = await asyncio.to_thread(_gen, continuation_prompt)
        except Exception as exc:
            logger.warning("HTML continuation failed: %s", exc)
            break
        fence = chr(96) * 3
        part = (part or "").replace(fence + "html", "").replace(fence, "").strip()
        if not part:
            break
        complete_part = _html(part)
        if complete_part:
            combined = complete_part
            break
        marker_at = part.find(anchor)
        if marker_at >= 0:
            part = part[marker_at + len(anchor):]
        elif re.search(r"<!doctype\s+html|<html\b", part, re.I):
            logger.warning("Gemini repeated the HTML prefix; duplicate part skipped.")
            continue
        combined += part
    return _html(combined), remaining

async def _generate(req, images, existing=None):
    desc = await _vision_text(images, req)
    prompt = _prompt(req, desc, existing)
    issue = None
    best = None
    continuation_budget = 2
    for _ in range(3):
        raw = await asyncio.to_thread(_gen, prompt + (("\\nTekshiruv xatosi: " + issue + ". Tuzatib to'liq HTML qaytar.") if issue else ""))
        doc = _html(raw)
        if not doc and raw:
            doc, continuation_budget = await _continue_html(raw, continuation_budget)
        if not doc:
            issue = "HTML kodi to'liq qaytmadi (davom ettirishga qaramay)"; continue
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
    saved = _persist_project(doc, req)
    context.user_data.pop("_ocb_pending", None); context.user_data.pop("_ocb_images", None)
    caption = "✅ Loyiha tayyor. HTML faylni yuklab olib Chrome'da oching."
    if issue: caption += "\n⚠️ Statik tekshiruv ogohlantirishi: " + issue + ". Brauzerda ham tekshiring."
    if saved.get("html") is None:
        caption += "\n⚠️ Fayl hajmi 4 MB dan katta: loyiha qayta ishga tushgandan keyin tahrirlash uchun saqlanmadi."
    await msg.reply_document(document=io.BytesIO(doc.encode("utf-8")), filename="creative_project.html", caption=caption)

async def _run(msg, context, req, edit=False):
    imgs = context.user_data.get("_ocb_images") or []
    existing = (_restore_project(context) or _last.get("html") or _project_record().get("html")) if edit else None
    status = await msg.reply_text("🧠 Talablarni tahlil qilib, loyihani yaratyapman...")
    try:
        doc, issue = await asyncio.wait_for(_generate(req, imgs, existing), timeout=480)
        if not doc:
            await status.edit_text("HTML yaratilmadi: to'liq kod olinmadi. Vazifani qismlarga ajrating."); return
        if issue:
            await status.edit_text("Loyiha sifat tekshiruvidan o'tmadi: " + issue + ". Noto'g'ri fayl yubormadim. So'rovni qismlarga ajratib qayta urinib ko'ring.")
            return
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
    last = _restore_project(context) or _last.get("html")
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
