"""Multi-template decks for Navyblue's PPTX builder.

The bot already ships ~27 themes (PPT_THEMES), but a deck used exactly one of them from the cover to
the last slide. Here the content slides are split into sections of SECTION slides: section 1 keeps the
deck's own theme, the following sections switch to two companion themes (same light/dark mode, so the
text/card contrast logic stays valid), then the cycle repeats. Closing/references/executive slides go
back to the deck's own theme.

* not used when the user picked a specific design (anything but "auto"/"random") or when the deck's
  theme is deliberately flat (swiss / editorial / brutal / retro)
* PPT_MULTI_THEME=0 switches it off, PPT_MULTI_SECTION=<n> changes the section length (default 3)
* any failure falls back to the normal single-theme build
"""
import contextvars
import copy
import logging
import os
import random
import sys
import threading
import time

log = logging.getLogger("ppt_multi_theme")

_choice = contextvars.ContextVar("ppt_theme_choice", default="auto")
_FLAT = {"swiss", "editorial", "brutal", "retro"}
_KEEP_BASE = {"closing", "references", "executive"}
_SWAP = ("theme", "pal", "tf", "bf", "left", "bg_main", "bg_title", "bg_cycle")


def _section_len():
    try:
        return max(2, int(os.environ.get("PPT_MULTI_SECTION", "3")))
    except ValueError:
        return 3


def _signature(t):
    return (bool(t.get("round")), t.get("tfont"), bool(t.get("card_alpha")), bool(t.get("hard")))


def pick_companions(themes, base, count=2, rng=random):
    """Pick `count` themes of the same light/dark mode with different looks."""
    pool = [t for t in themes
            if isinstance(t, dict) and t.get("key") != base.get("key") and t.get("key") not in _FLAT
            and bool(t.get("dark_mode")) == bool(base.get("dark_mode")) and t.get("bg") and t.get("card")]
    rng.shuffle(pool)
    picked = []
    for t in pool:
        if not picked:
            picked.append(t)
        elif _signature(t) != _signature(picked[0]) or len(pool) <= count:
            picked.append(t)
        if len(picked) >= count:
            break
    for t in pool:                      # not enough distinct looks: fill up with anything left
        if len(picked) >= count:
            break
        if t not in picked:
            picked.append(t)
    return picked


def _make_cycle(mod, base):
    cycle = []
    for t in pick_companions(getattr(mod, "PPT_THEMES", []), base):
        theme = copy.deepcopy(t)
        main, title, _credit = mod._ppt_make_backgrounds_sync(theme)
        cycle.append({"theme": theme, "bg_main": main, "bg_title": title or main})
    log.info("multi-theme deck: base=%s companions=%s", base.get("key"), [c["theme"].get("key") for c in cycle])
    return cycle


def _plan(builder, sl, mod):
    n = builder.__dict__.get("_mt_i", 0)
    builder.__dict__["_mt_i"] = n + 1
    if os.environ.get("PPT_MULTI_THEME", "1") == "0" or _choice.get() not in ("auto", "random", None, ""):
        return None
    base = builder.__dict__.setdefault("_mt_base", builder.theme)
    if base.get("key") in _FLAT or (isinstance(sl, dict) and sl.get("layout") in _KEEP_BASE):
        return None
    section = n // _section_len()
    if section % 3 == 0:
        return None
    cycle = builder.__dict__.get("_mt_cycle")
    if cycle is None:
        try:
            cycle = _make_cycle(mod, base)
        except Exception as exc:
            log.warning("multi-theme disabled for this deck: %s", exc)
            cycle = []
        builder.__dict__["_mt_cycle"] = cycle
    idx = section % 3 - 1
    return cycle[idx] if idx < len(cycle) else None


def _swap_in(builder, entry, mod):
    t = entry["theme"]
    pair = getattr(mod, "PPT_FONT_PAIRS", {}).get(t.get("key"), (getattr(mod, "PPT_TITLE_FONT", "Calibri"),
                                                                  getattr(mod, "PPT_BODY_FONT", "Calibri")))
    builder.theme = builder.pal = t
    builder.tf = t.get("tfont") or pair[0]
    builder.bf = t.get("bfont") or pair[1]
    builder.left = t.get("align") == "l"
    builder.bg_main, builder.bg_title, builder.bg_cycle = entry["bg_main"], entry["bg_title"], []


def install(builder_class):
    """Wrap builder_class._build_one (call after the other wrappers so this one is outermost)."""
    old = builder_class._build_one

    def build_one(self, sl):
        mod = sys.modules.get(builder_class.__module__)
        try:
            entry = _plan(self, sl, mod)
        except Exception as exc:
            log.warning("multi-theme plan skipped: %s", exc)
            entry = None
        if not entry:
            return old(self, sl)
        saved = {k: getattr(self, k, None) for k in _SWAP}
        try:
            _swap_in(self, entry, mod)
            return old(self, sl)
        finally:
            for k, v in saved.items():
                setattr(self, k, v)

    builder_class._build_one = build_one
    threading.Thread(target=_patch_generate, args=(builder_class,), name="ppt_multi_theme", daemon=True).start()


def _patch_generate(builder_class, timeout=180.0):
    """Remember the user's design choice for the whole generation (auto/random -> multi-template)."""
    mod = sys.modules.get(builder_class.__module__)
    deadline = time.time() + timeout
    while mod is not None and time.time() < deadline:
        if hasattr(mod, "_ppt_generate_and_send") and hasattr(mod, "main"):
            time.sleep(1.5)             # let ppt_user_fixes finish its own wrapping first
            orig = mod._ppt_generate_and_send

            async def generate(msg, context, topic, n, with_images, author, mode=None):
                choice = "auto"
                try:
                    choice = str(context.user_data.get("_ppt_theme", "auto") or "auto")
                except Exception:
                    pass
                token = _choice.set(choice)
                try:
                    return await orig(msg, context, topic, n, with_images, author, mode)
                finally:
                    _choice.reset(token)

            mod._ppt_generate_and_send = generate
            log.info("ppt_multi_theme active")
            return
        time.sleep(0.25)
    log.warning("ppt_multi_theme: bot module never finished loading; design choice not tracked")
