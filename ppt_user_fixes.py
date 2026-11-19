"""Runtime fixes for the Telegram presentation flow (slide count + photo coverage).

Applied once, after bot.py has finished defining its functions (see schedule()).
Every patch is wrapped so that any failure falls back to the original behaviour.

1. Slide count: phrases such as "20 ta slayd", "20ta slide", "slayd soni 20", "20 talik taqdimot"
   or "mavzu | 20" are understood by the October assistant. If no number is given at all, the bot
   asks with the count buttons instead of silently making 10 slides.
2. Photos: more editorial slides are promoted to photo layouts (default target 80%, set
   PPT_VISUAL_TARGET to change it). Slides with no photo found still fall back to clean card layouts.
3. Photo search language: Uzbek written in Latin letters is plain ASCII, so the original
   _pxb_to_english() treated it as "already English" and never translated it. Every slide then
   searched the same untranslated query and the stock providers ran out of results (1 photo on a
   30-slide deck). Uzbek-looking ASCII queries are now translated to English keywords, all of a
   deck's queries in ONE batched AI request (the Gemini free tier allows only a few per minute).
4. Fantasy/fiction decks: the rule table in build_photorealistic_query() also matched the *deck
   topic* ("Hogwarts" -> the same "wizard professor classroom" query for every slide), so after ~8
   photos the stock results were exhausted. Rules now see only each slide's own title/body and the
   slide title is appended, so every slide searches for something different.
5. Niche topics (e.g. "Remus Lupin character analysis"): stock sites know nothing about the
   character, and the slide's own scene query ("werewolf silhouette full moon ...") was only
   searched together with that name, so nothing was found. For fantasy scenes, when the normal
   search finds nothing, the scene itself is searched.
6. Texts cut with "..." in the middle of a sentence are now cut at a sentence/clause boundary.
7. New layouts (waterfall / swimlane / network / quote): the sanitizer DROPPED a slide whose
   structured data was incomplete (e.g. a network with < 3 links, a quote without a source), so the
   deck came out short and needed extra AI calls. Such slides are now demoted to plain text slides.
8. Language button: the slide-count keyboard gets a row "Uz / English / Russian". The chosen
   language is applied to the whole deck generation (AI prompts get an output-language rule).
   The handler is registered in group -2: bot.py has a catch-all TypeHandler in group -1 and
   python-telegram-bot runs only the first matching handler of a group.
"""
import asyncio
import contextvars
import logging
import os
import re
import sys
import threading
import time

log = logging.getLogger("ppt_user_fixes")

_FILLER = re.compile(r"\b(?:photorealistic|editorial|photograph|photography|natural|cinematic|lighting|documentary|render)\b", re.I)
_SCENE_HINT = re.compile(r"fantasy|wizard|witch|werewolf|gothic|castle|moonlit|spectral|parchment|film still|magic", re.I)
_SCENE_STOP = {"cinematic", "photorealistic", "film", "still", "natural", "dramatic", "lighting",
               "live", "action", "with", "and", "the", "light"}


def _finish_sentence(out):
    """Turn 'half a sentence...' into a complete clause when a clean boundary exists."""
    if not isinstance(out, str) or not out.endswith("\u2026"):
        return out
    body = out[:-1].rstrip()
    for sep in (". ", "! ", "? "):
        i = body.rfind(sep)
        if i >= len(body) * 0.4:
            return body[:i + 1]
    cut = max(body.rfind(", "), body.rfind("; "), body.rfind(": "), body.rfind(" \u2014 "))
    if cut >= len(body) * 0.55:
        return body[:cut].rstrip(" ,;:\u2014-") + "."
    return out


_NOUNS = r"(?:slayd|slayt|slide|slaid|sahifa|bet|varoq|taqdimot|prezentatsiya|presentatsiya|prezentatsiyasi|ppt|pptx)"
_COUNT_PATTERNS = (
    re.compile(r"(?<!\d)(\d{1,2})\s*(?:ta|talik|tali)?\s*" + _NOUNS, re.I),
    re.compile(_NOUNS + r"\s*(?:soni|miqdori)?\s*[:=\-]?\s*(\d{1,2})(?!\d)", re.I),
    re.compile(r"(?<![\d.,:/-])(\d{1,2})\s*(?:ta|talik|tali)(?![a-z])", re.I),
    re.compile(r"[|;]\s*(\d{1,2})\s*$"),
)


def extract_slide_count(text, lo=4, hi=30):
    """Return a slide count found in free text, clamped to [lo, hi], or None."""
    raw = (text or "").replace("\u2019", "'")
    for pattern in _COUNT_PATTERNS:
        match = pattern.search(raw)
        if match:
            value = int(match.group(1))
            if value >= 2:
                return max(lo, min(hi, value))
    return None


def _strip_count(topic, n):
    cleaned = re.sub(r"(?<!\d)%d\s*(?:ta|talik|tali)?(?![\d\w])" % n, " ", topic or "", count=1, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip(" |,;:-")


_LANGS = {"uz": ("\U0001F1FA\U0001F1FF O'zbekcha", "O'zbek (Uzbek, Latin script)"),
          "en": ("\U0001F1EC\U0001F1E7 English", "English"),
          "ru": ("\U0001F1F7\U0001F1FA \u0420\u0443\u0441\u0441\u043a\u0438\u0439", "Russian (\u0420\u0443\u0441\u0441\u043a\u0438\u0439)")}
_lang_var = contextvars.ContextVar("ppt_lang", default="uz")
_LANG_MARK = "OUTPUT LANGUAGE RULE"
_LANG_HINTS = (
    ("en", re.compile(r"\b(?:inglizcha|ingliz\s+tilida|english|in\s+english)\b", re.I)),
    ("ru", re.compile(r"\b(?:ruscha|rus\s+tilida|russian|in\s+russian)\b|\u043d\u0430\s+\u0440\u0443\u0441\u0441\u043a\u043e\u043c|\u043f\u043e-\u0440\u0443\u0441\u0441\u043a\u0438", re.I)),
)


def _with_lang(prompt, lang):
    """Append the output-language rule to outline-generation prompts (the ones that define layouts)."""
    if lang == "uz" or not isinstance(prompt, str) or _LANG_MARK in prompt or '"layout"' not in prompt:
        return prompt
    name = _LANGS[lang][1]
    return (prompt + f"\n\n{_LANG_MARK}: write EVERY user-visible text value (titles, subtitles, text, notes, card heads, labels, "
            f"steps, captions, quotes, takeaways) in {name}. Keep JSON keys, layout names, enum values and "
            "photo_query / topic_en / cover_query exactly as specified (photo and image queries stay in English).")


def _caller_user_data():
    """user_data of the Telegram handler that is building the keyboard (looks for a `context` local)."""
    try:
        frame = sys._getframe(2)
        for _ in range(6):
            if frame is None:
                break
            ctx = frame.f_locals.get("context")
            ud = getattr(ctx, "user_data", None)
            if ud is not None:
                return ud
            frame = frame.f_back
    except Exception:
        pass
    return None


def _lang_row(lang):
    from telegram import InlineKeyboardButton
    return [InlineKeyboardButton(("\u2705 " if code == lang else "") + label, callback_data="pptlang:" + code)
            for code, (label, _name) in _LANGS.items()]


def _valid_advanced(s):
    """Same structural rules as the premium sanitizer, so we can demote instead of dropping."""
    lay = str(s.get("layout") or "").strip()
    try:
        if lay == "waterfall":
            ok = 0
            for d in (s.get("steps") or [])[:7]:
                if isinstance(d, dict) and str(d.get("label") or "").strip():
                    v = float(d.get("value"))
                    if v == v and abs(v) != float("inf"):
                        ok += 1
            return ok >= 4
        if lay == "swimlane":
            lanes = 0
            for lane in (s.get("lanes") or [])[:4]:
                if isinstance(lane, dict) and str(lane.get("label") or "").strip():
                    steps = [x for x in (lane.get("steps") or [])[:4] if isinstance(x, dict) and str(x.get("label") or "").strip()]
                    if len(steps) >= 2:
                        lanes += 1
            return lanes >= 2
        if lay == "network":
            nodes = [x for x in (s.get("nodes") or [])[:7] if isinstance(x, dict) and str(x.get("label") or "").strip()]
            links = 0
            for e in (s.get("links") or [])[:12]:
                if isinstance(e, dict):
                    a, b = int(e.get("from")), int(e.get("to"))
                    if 0 <= a < len(nodes) and 0 <= b < len(nodes) and a != b:
                        links += 1
            return len(nodes) >= 4 and links >= 3
        if lay == "quote":
            return all(str(s.get(k) or "").strip() for k in ("quote", "attribution", "source"))
    except (TypeError, ValueError):
        return False
    return True


def _demote_text(s):
    parts = []
    for key in ("text", "quote", "context"):
        if str(s.get(key) or "").strip():
            parts.append(str(s[key]).strip())
    if s.get("attribution"):
        parts.append("\u2014 " + str(s["attribution"]).strip())
    for seq_key in ("steps", "nodes", "lanes"):
        for d in (s.get(seq_key) or [])[:6]:
            if isinstance(d, dict) and str(d.get("label") or "").strip():
                parts.append(str(d["label"]).strip() + (": " + str(d["detail"]).strip() if d.get("detail") else ""))
    return " ".join(parts)[:400] or str(s.get("title") or "")


def demote_invalid_advanced(data):
    """Turn structurally incomplete advanced-layout slides into text slides instead of losing them."""
    slides = data.get("slides") if isinstance(data, dict) else data
    if not isinstance(slides, list):
        return data
    for s in slides:
        if isinstance(s, dict) and s.get("layout") in ("waterfall", "swimlane", "network", "quote") and not _valid_advanced(s):
            s["layout"] = "text"
            s["text"] = _demote_text(s)
    return data


def _patch_application():
    """Register the language button handler on the PTB Application before polling starts."""
    try:
        from telegram.ext import Application, CallbackQueryHandler
        from telegram import InlineKeyboardMarkup
    except Exception as exc:
        log.warning("language button: telegram not importable: %s", exc)
        return
    if getattr(Application, "_ppt_lang_patched", False):
        return

    async def on_lang(update, context):
        q = update.callback_query
        lang = (q.data or "").split(":")[-1] if q else ""
        if lang not in _LANGS:
            return
        context.user_data["_ppt_lang"] = lang
        try:
            await q.answer("\u2705 " + _LANGS[lang][0])
        except Exception:
            pass
        try:
            rows = [list(r) for r in q.message.reply_markup.inline_keyboard]
            for i, row in enumerate(rows):
                if row and str(getattr(row[0], "callback_data", "")).startswith("pptlang:"):
                    rows[i] = _lang_row(lang)
            await q.message.edit_reply_markup(InlineKeyboardMarkup(rows))
        except Exception as exc:
            log.info("language keyboard not re-rendered: %s", exc)

    orig_run = Application.run_polling

    def run_polling(self, *args, **kwargs):
        try:
            if not getattr(self, "_ppt_lang_added", False):
                self.add_handler(CallbackQueryHandler(on_lang, pattern=r"^pptlang:"), group=-2)
                self._ppt_lang_added = True
                log.info("ppt language button handler registered")
        except Exception as exc:
            log.error("language handler registration failed: %s", exc)
        return orig_run(self, *args, **kwargs)

    Application.run_polling = run_polling
    Application._ppt_lang_patched = True


def apply(mod):
    """Patch the bot module in place. Returns the list of patched names."""
    if getattr(mod, "_ppt_user_fixes_applied", False):
        return []
    done = []
    lo = int(getattr(mod, "PPT_MIN_SLIDES", 4))
    hi = int(getattr(mod, "PPT_MAX_SLIDES", 30))

    orig_quick = getattr(mod, "_oct_quick_intent", None)
    if callable(orig_quick):
        def quick(text):
            res = orig_quick(text)
            try:
                if res and res.get("kind") == "slide" and not res.get("n"):
                    n = extract_slide_count(text, lo, hi)
                    if n:
                        res["n"] = n
                        res["topic"] = _strip_count(res.get("topic", ""), n)
            except Exception as exc:
                log.warning("quick intent patch skipped: %s", exc)
            return res
        mod._oct_quick_intent = quick
        done.append("_oct_quick_intent")

    orig_do = getattr(mod, "_oct_do", None)
    ask_count = getattr(mod, "_ppt_ask_count", None)
    if callable(orig_do) and callable(ask_count):
        async def do(update, context, kind, topic, n=None, mode=None, again=False):
            if kind == "slide":
                try:
                    for code, pattern in _LANG_HINTS:
                        if pattern.search(topic or ""):
                            context.user_data["_ppt_lang"] = code
                            topic = re.sub(r"\s+", " ", pattern.sub(" ", topic)).strip(" ,;:-") or topic
                            break
                except Exception as exc:
                    log.warning("language hint skipped: %s", exc)
            if kind == "slide" and not n and (topic or "").strip():
                try:
                    if mode in ("common", "premium"):
                        context.user_data["_ppt_mode"] = mode
                    await ask_count(update.effective_message, context, topic.strip())
                    return None
                except Exception as exc:
                    log.warning("count prompt failed, using original flow: %s", exc)
            return await orig_do(update, context, kind, topic, n, mode, again)
        mod._oct_do = do
        done.append("_oct_do")

    orig_cov = getattr(mod, "_ppt_apply_general_visual_coverage", None)
    if callable(orig_cov):
        def coverage(outline, target_ratio=None):
            if target_ratio is None:
                try:
                    target_ratio = float(os.environ.get("PPT_VISUAL_TARGET", "0.8"))
                except ValueError:
                    target_ratio = 0.8
            return orig_cov(outline, target_ratio)
        mod._ppt_apply_general_visual_coverage = coverage
        done.append("_ppt_apply_general_visual_coverage")

    orig_pxb = getattr(mod, "_pxb_to_english", None)
    needs = getattr(mod, "needs_english_stock_translation", None)
    if callable(orig_pxb) and callable(needs):
        cache, pending, state = {}, [], {"scheduled": False}

        async def flush():
            await asyncio.sleep(0.8)          # let all slides of the deck queue up first
            batch = list(pending)
            pending.clear()
            state["scheduled"] = False
            keys = []
            for key, _kind, _fut in batch:
                if key not in keys and key not in cache:
                    keys.append(key)
            if keys:
                try:
                    keys = keys[:40]
                    lines = "\n".join(f"{i + 1}. {k[:200]}" for i, k in enumerate(keys))
                    prompt = ("Each numbered line is a stock-photo search request (Uzbek written in Latin letters). "
                              "Convert EACH one into 2-4 concise, SPECIFIC ENGLISH keywords for a stock website. "
                              "Keep the main subject noun first and keep important details (object, place, action). "
                              "Do not add words that were not requested. "
                              "Return ONLY JSON mapping the line number to the keywords, e.g. {\"1\": \"...\", \"2\": \"...\"}.\n"
                              + lines)
                    async with mod.ai_gate:
                        out = await asyncio.wait_for(
                            asyncio.to_thread(mod._ai_generate_text_sync, prompt, 0.1, 40 * 40 + 200, True), timeout=60)
                    data = mod._json_loads_loose(out) or {}
                    for i, k in enumerate(keys):
                        q = str(data.get(str(i + 1)) or "").strip()
                        if q and re.search(r"[A-Za-z]", q):
                            cache[k] = q[:100]
                except Exception as exc:
                    log.warning("uzbek->english batch translation failed, using original flow: %s", exc)
            for key, _kind, fut in batch:
                if not fut.done():
                    fut.set_result(cache.get(key))

        async def to_english(text, kind="photo"):
            raw = (text or "").strip()
            try:
                if raw and re.fullmatch(r"[A-Za-z0-9 ,.\-]+", raw) and needs(raw):
                    cleaned = re.sub(r"\s+", " ", _FILLER.sub(" ", raw)).strip()
                    if cleaned:
                        if cleaned in cache:
                            return cache[cleaned], True
                        fut = asyncio.get_running_loop().create_future()
                        pending.append((cleaned, kind, fut))
                        if not state["scheduled"]:
                            state["scheduled"] = True
                            asyncio.ensure_future(flush())
                        q = await fut
                        if q:
                            return q, True
            except Exception as exc:
                log.warning("uzbek->english translation failed, using original flow: %s", exc)
            return await orig_pxb(text, kind)
        mod._pxb_to_english = to_english
        done.append("_pxb_to_english")

    orig_bpq = getattr(mod, "build_photorealistic_query", None)
    if callable(orig_bpq):
        def build_query(domain, topic, title, body=""):
            try:
                key = re.sub(r"[^a-z0-9]+", " ", str(domain or "").lower()).strip()
                if key in ("fiction", "fantasy", "remus", "remus lupin"):
                    base = orig_bpq(domain, "", title, body)
                    if not base.startswith("cinematic photorealistic live action film still"):
                        slide_part = re.sub(r"[^A-Za-z0-9 ]+", " ", str(title or "")).strip()
                        if slide_part:
                            base = f"{base} {slide_part}"
                    return base
            except Exception as exc:
                log.warning("fiction query patch skipped: %s", exc)
            return orig_bpq(domain, topic, title, body)
        mod.build_photorealistic_query = build_query
        done.append("build_photorealistic_query")

    orig_find = getattr(mod, "_ppt_find_photo_sync", None)
    if callable(orig_find):
        def find_photo(query, anchor, used, historical=False):
            res = orig_find(query, anchor, used, historical)
            if res is not None or historical:
                return res
            try:
                if _SCENE_HINT.search(str(query or "")):
                    words = [w for w in re.findall(r"[A-Za-z]{4,}", str(query)) if w.lower() not in _SCENE_STOP]
                    alt = " ".join(words[:3])
                    if alt:
                        return orig_find(query, alt, used, historical)
            except Exception as exc:
                log.warning("scene photo retry skipped: %s", exc)
            return res
        mod._ppt_find_photo_sync = find_photo
        done.append("_ppt_find_photo_sync")

    for clip_name in ("_ppt_s", "_ppt_clip"):
        orig_clip = getattr(mod, clip_name, None)
        if callable(orig_clip):
            def make(orig):
                def clip(*args, **kwargs):
                    return _finish_sentence(orig(*args, **kwargs))
                return clip
            setattr(mod, clip_name, make(orig_clip))
            done.append(clip_name)

    orig_san = getattr(mod, "_sanitize_outline", None)
    if callable(orig_san):
        def sanitize(data, topic, n, with_images):
            try:
                demote_invalid_advanced(data)
            except Exception as exc:
                log.warning("advanced-layout demotion skipped: %s", exc)
            return orig_san(data, topic, n, with_images)
        mod._sanitize_outline = sanitize
        done.append("_sanitize_outline")

    orig_kb = getattr(mod, "_ppt_count_keyboard", None)
    if callable(orig_kb):
        def count_keyboard(*args, **kwargs):
            markup = orig_kb(*args, **kwargs)
            try:
                ud = _caller_user_data()
                lang = (ud or {}).get("_ppt_lang", "uz")
                rows = [list(r) for r in markup.inline_keyboard]
                if not any(r and str(getattr(r[0], "callback_data", "")).startswith("pptlang:") for r in rows):
                    rows.insert(0, _lang_row(lang if lang in _LANGS else "uz"))
                    return type(markup)(rows)
            except Exception as exc:
                log.warning("language row skipped: %s", exc)
            return markup
        mod._ppt_count_keyboard = count_keyboard
        done.append("_ppt_count_keyboard")

    orig_gen = getattr(mod, "_ppt_generate_and_send", None)
    if callable(orig_gen):
        async def generate(msg, context, topic, n, with_images, author, mode=None):
            lang = "uz"
            try:
                lang = context.user_data.get("_ppt_lang", "uz")
            except Exception:
                pass
            token = _lang_var.set(lang if lang in _LANGS else "uz")
            try:
                return await orig_gen(msg, context, topic, n, with_images, author, mode)
            finally:
                _lang_var.reset(token)
        mod._ppt_generate_and_send = generate
        done.append("_ppt_generate_and_send")

    orig_ai = getattr(mod, "_ai_generate_text_sync", None)
    if callable(orig_ai):
        def ai_generate(prompt, *args, **kwargs):
            try:
                prompt = _with_lang(prompt, _lang_var.get())
            except Exception as exc:
                log.warning("language rule skipped: %s", exc)
            return orig_ai(prompt, *args, **kwargs)
        mod._ai_generate_text_sync = ai_generate
        done.append("_ai_generate_text_sync")

    mod._ppt_user_fixes_applied = True
    log.info("ppt_user_fixes applied: %s", ", ".join(done) or "nothing")
    return done


_REQUIRED = ("_oct_quick_intent", "_oct_do", "_ppt_ask_count",
             "_ppt_apply_general_visual_coverage", "main")


def schedule(builder_class, timeout=180.0):
    """Apply the patches as soon as bot.py has defined everything (runs in a daemon thread)."""
    mod = sys.modules.get(getattr(builder_class, "__module__", ""))
    if mod is None:
        return
    try:
        _patch_application()
    except Exception as exc:
        log.error("language button patch failed: %s", exc)

    def worker():
        deadline = time.time() + timeout
        while time.time() < deadline:
            if all(hasattr(mod, name) for name in _REQUIRED):
                try:
                    apply(mod)
                except Exception as exc:
                    log.error("ppt_user_fixes failed: %s", exc)
                return
            time.sleep(0.25)
        log.warning("ppt_user_fixes: bot module never finished loading; nothing patched")

    threading.Thread(target=worker, name="ppt_user_fixes", daemon=True).start()
