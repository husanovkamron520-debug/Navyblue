"""Per-slide error recovery for Navyblue's PPTX builder.

If building one slide raises, the half-built slide is removed and replaced with a plain,
safe text slide, so a single broken layout never kills the whole presentation.
Everything here is defensive: if anything unexpected happens, behaviour falls back to the
original (the original exception is re-raised).
"""
import logging

log = logging.getLogger("ppt_recovery")

_TEXT_KEYS = ("text", "quote", "attribution", "context", "subtitle", "body")
_LIST_KEYS = ("cards", "steps", "nodes", "lanes", "bullets", "points", "items", "data")
_ITEM_KEYS = ("head", "label", "title", "text", "detail", "name")


def collect_lines(sl, limit_lines=8, limit_chars=700):
    """Pull readable text out of any slide dict, whatever its layout."""
    lines = []

    def add(value):
        if isinstance(value, str) and value.strip():
            lines.append(value.strip())

    for key in _TEXT_KEYS:
        add(sl.get(key))
    for key in _LIST_KEYS:
        seq = sl.get(key)
        if not isinstance(seq, (list, tuple)):
            continue
        for item in seq:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                parts = [str(item[k]).strip() for k in _ITEM_KEYS
                         if isinstance(item.get(k), (str, int, float)) and str(item.get(k)).strip()]
                if parts:
                    lines.append(": ".join(parts[:2]))
    out, total = [], 0
    for line in lines:
        if len(out) >= limit_lines or total + len(line) > limit_chars:
            break
        out.append(line)
        total += len(line)
    return out


def drop_slide(slide):
    """Remove a slide (and its relationship) from its presentation."""
    prs = slide.part.package.presentation_part.presentation
    id_list = prs.slides._sldIdLst
    for sld_id in list(id_list):
        if prs.part.related_part(sld_id.rId) is slide.part:
            prs.part.drop_rel(sld_id.rId)
            id_list.remove(sld_id)
            return True
    return False


def harden(builder_class, title_fn):
    """Wrap new_slide/_build_one so a failing slide degrades to a plain text slide."""
    old_new_slide = builder_class.new_slide
    old_build_one = builder_class._build_one

    def new_slide(self, *args, **kwargs):
        slide = old_new_slide(self, *args, **kwargs)
        try:
            self.__dict__.setdefault("_recovery_slides", []).append(slide)
        except Exception:
            pass
        return slide

    def build_one(self, sl):
        made = self.__dict__.setdefault("_recovery_slides", [])
        mark = len(made)
        try:
            return old_build_one(self, sl)
        except Exception as exc:
            log.warning("slide %r failed (%s: %s); using safe fallback",
                        sl.get("title") if isinstance(sl, dict) else "?", type(exc).__name__, exc)
            try:
                for partial in made[mark:]:
                    drop_slide(partial)
                del made[mark:]
                return _safe_slide(self, sl, title_fn)
            except Exception as fallback_exc:
                log.error("fallback slide failed too: %s", fallback_exc)
                raise exc

    builder_class.new_slide = new_slide
    builder_class._build_one = build_one
    try:
        from ppt_user_fixes import schedule
        schedule(builder_class)
    except Exception as exc:
        log.warning("ppt_user_fixes not scheduled: %s", exc)
    try:
        from ppt_multi_theme import install as install_multi_theme
        install_multi_theme(builder_class)
    except Exception as exc:
        log.warning("ppt_multi_theme not installed: %s", exc)
    try:
        from ppt_premium import schedule as schedule_premium
        schedule_premium(builder_class)
    except Exception as exc:
        log.warning("ppt_premium not scheduled: %s", exc)


def _safe_slide(self, sl, title_fn):
    s = self.new_slide()
    title_fn(self, s, sl.get("title") or "")
    lines = collect_lines(sl)
    if lines:
        body = "\n".join(lines)
        self.text(s, 1.0, 2.0, 11.3, 4.5, body, self.fit(body, 11.2, 4.4, 20, 11),
                  "text", False, "l", "t")
    self.notes(s, sl.get("notes"))
    return None
