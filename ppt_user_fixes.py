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
   30-slide deck). Uzbek-looking ASCII queries are now translated to English keywords.
4. Fantasy/fiction decks: the rule table in build_photorealistic_query() also matched the *deck
   topic* ("Hogwarts" -> the same "wizard professor classroom" query for every slide), so after ~8
   photos the stock results were exhausted. Rules now see only each slide's own title/body and the
   slide title is appended, so every slide searches for something different.
"""
import asyncio
import logging
import os
import re
import sys
import threading
import time

log = logging.getLogger("ppt_user_fixes")

_FILLER = re.compile(r"\b(?:photorealistic|editorial|photograph|photography|natural|cinematic|lighting|documentary|render)\b", re.I)
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
        async def to_english(text, kind="photo"):
            raw = (text or "").strip()
            try:
                if raw and re.fullmatch(r"[A-Za-z0-9 ,.\-]+", raw) and needs(raw):
                    cleaned = re.sub(r"\s+", " ", _FILLER.sub(" ", raw)).strip()
                    if cleaned:
                        what = "video" if kind == "video" else "photo"
                        prompt = (f"Convert this stock-{what} search request (Uzbek written in Latin letters) into 2-4 concise, "
                                  "SPECIFIC ENGLISH keywords for a stock website. Keep the main subject noun first and keep every "
                                  "important detail (object, place, action). Do not add words that were not requested. "
                                  f"Return ONLY JSON: {{\"q\": \"...\"}}.\nRequest: {cleaned[:200]}")
                        async with mod.ai_gate:
                            out = await asyncio.wait_for(
                                asyncio.to_thread(mod._ai_generate_text_sync, prompt, 0.1, 200, True), timeout=45)
                        q = str((mod._json_loads_loose(out) or {}).get("q") or "").strip()
                        if q and re.search(r"[A-Za-z]", q):
                            return q[:100], True
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
