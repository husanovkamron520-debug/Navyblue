"""Premium polish for Navyblue decks (applied at runtime, every part falls back to the original).

1. Photos: near-duplicate detection. Stock sites often return the same picture several times
   (different ids, same image / crop). A 64-bit difference hash is compared with the photos already
   used in the deck; a near-duplicate is replaced by the next candidate.
2. Animation: the entrance effects of the original _v8_timing() plus a "rise" (float-in) effect and a
   smoother cascade. Set PPT_ANIM_RISE=0 to go back to plain fades.
3. Typography: kerning on, tighter tracking and line spacing on large headlines, light tracking on
   short UPPERCASE labels (never touches body text, so nothing can overflow).
"""
import io
import logging
import os
import sys
import threading
import time
from collections import OrderedDict

log = logging.getLogger("ppt_premium")

# ------------------------------------------------------------------ 1. photo duplicates
_SEEN = OrderedDict()           # id(used set) -> (used set, [hashes])   (keeps the set alive, capped)


def dhash(raw):
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("L").resize((9, 8), Image.LANCZOS)
    px = list(im.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def wrap_photo_search(orig, threshold=8):
    def find_photo(query, anchor, used, historical=False):
        res = orig(query, anchor, used, historical)
        try:
            entry = _SEEN.get(id(used))
            if entry is None or entry[0] is not used:
                entry = (used, [])
                _SEEN[id(used)] = entry
                while len(_SEEN) > 24:
                    _SEEN.popitem(last=False)
            hashes = entry[1]
            for _attempt in range(3):
                if not res:
                    return res
                h = dhash(res[0])
                if all(hamming(h, x) > threshold for x in hashes):
                    hashes.append(h)
                    return res
                log.info("near-duplicate photo skipped (query=%r)", str(query)[:60])
                res = orig(query, anchor, used, historical)      # the rejected id is already in `used`
            if res:
                hashes.append(dhash(res[0]))
        except Exception as exc:
            log.warning("photo dedupe skipped: %s", exc)
        return res
    return find_photo


# ------------------------------------------------------------------ 3. typography
def polish_typography(slide):
    from pptx.oxml.ns import qn
    from lxml import etree
    for sh in slide.shapes:
        if not getattr(sh, "has_text_frame", False) or not sh.text_frame.text.strip():
            continue
        text = sh.text_frame.text.strip()
        for p in sh.text_frame.paragraphs:
            sizes = [r.font.size.pt for r in p.runs if r.font.size is not None]
            if not sizes:
                continue
            size = max(sizes)
            runs = [r._r.find(qn("a:rPr")) for r in p.runs]
            headline = size >= 28 and len(text) <= 90
            label = size <= 14 and len(text) <= 24 and text.upper() == text and any(ch.isalpha() for ch in text)
            if not (headline or label):
                continue
            for rpr in runs:
                if rpr is None:
                    continue
                rpr.set("kern", "1200")
                if headline and rpr.get("spc") is None:
                    rpr.set("spc", str(-int(min(size, 60))))
                elif label and rpr.get("spc") is None:
                    rpr.set("spc", "50")
            if headline:
                ppr = p._p.get_or_add_pPr()
                if ppr.find(qn("a:lnSpc")) is None:
                    ln = etree.SubElement(ppr, qn("a:lnSpc"))
                    etree.SubElement(ln, qn("a:spcPct")).set("val", "92000")
                    ppr.remove(ln)
                    ppr.insert(0, ln)                       # lnSpc must be the first child of pPr


# ------------------------------------------------------------------ 2. animation
_FILTER_FX = {
    "fade": (10, 0, "fade"), "wipe_up": (22, 1, "wipe(up)"), "wipe_right": (22, 2, "wipe(right)"),
    "wipe_down": (22, 4, "wipe(down)"), "wipe_left": (22, 8, "wipe(left)"), "dissolve": (9, 0, "dissolve"),
    "box": (4, 16, "box(in)"), "circle": (6, 16, "circle(in)"),
}


def _pick_fx(idx, k, kind, rise=True):
    if kind == "chart":
        return "wipe_left"
    if kind == "text":
        return "rise" if rise else "fade"
    if kind == "small":
        seq = ("rise", "fade", "box", "circle") if rise else ("fade", "box", "circle")
        return seq[(idx + k) % len(seq)]
    seq = ("rise", "fade", "wipe_up", "wipe_left", "dissolve", "wipe_right", "box") if rise else \
          ("fade", "wipe_up", "wipe_left", "dissolve", "wipe_right", "wipe_down", "box")
    return seq[(idx * 2 + k % 2) % len(seq)]


def _effect_xml(ids, fx, node_type, delay, sid):
    a, b, c, d = next(ids), next(ids), next(ids), next(ids)
    visible = (f'<p:set><p:cBhvr><p:cTn id="{b}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
               f'<p:tgtEl><p:spTgt spid="{sid}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
               f'<p:to><p:strVal val="visible"/></p:to></p:set>')
    if fx == "rise":
        head = (f'<p:par><p:cTn id="{a}" presetID="42" presetClass="entr" presetSubtype="0" fill="hold" nodeType="{node_type}">'
                f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>')
        body = (visible +
                f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{c}" dur="450"/>'
                f'<p:tgtEl><p:spTgt spid="{sid}"/></p:tgtEl></p:cBhvr></p:animEffect>'
                f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{d}" dur="450" fill="hold"/>'
                f'<p:tgtEl><p:spTgt spid="{sid}"/></p:tgtEl><p:attrNameLst><p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr>'
                f'<p:tavLst><p:tav tm="0"><p:val><p:strVal val="#ppt_y+.06"/></p:val></p:tav>'
                f'<p:tav tm="100000"><p:val><p:strVal val="#ppt_y"/></p:val></p:tav></p:tavLst></p:anim>')
        return head + body + '</p:childTnLst></p:cTn></p:par>'
    pid, sub, flt = _FILTER_FX[fx]
    return (f'<p:par><p:cTn id="{a}" presetID="{pid}" presetClass="entr" presetSubtype="{sub}" fill="hold" nodeType="{node_type}">'
            f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>' + visible +
            f'<p:animEffect transition="in" filter="{flt}"><p:cBhvr><p:cTn id="{c}" dur="320"/>'
            f'<p:tgtEl><p:spTgt spid="{sid}"/></p:tgtEl></p:cBhvr></p:animEffect></p:childTnLst></p:cTn></p:par>')


def build_timing(slide, idx):
    """Same structure as the bot's _v8_timing (auto-start entrance effects), richer effects."""
    from pptx.oxml import parse_xml
    from pptx.oxml.ns import qn
    rise = os.environ.get("PPT_ANIM_RISE", "1") != "0"
    prs = slide.part.package.presentation_part.presentation
    W, H = int(prs.slide_width), int(prs.slide_height)
    targets = []
    for sh in slide.shapes:
        nm = str(getattr(sh, "name", ""))
        if nm.startswith("!!") or nm.startswith("deco"):
            continue
        try:
            w, h, st = int(sh.width), int(sh.height), sh.shape_type
        except Exception:
            continue
        if (w >= W * 0.96 and h >= H * 0.96) or w < 36000 or h < 36000 or st == 9:
            continue
        has_text = bool(getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip())
        is_chart = bool(getattr(sh, "has_chart", False) or getattr(sh, "has_table", False))
        area = w * h / (914400.0 * 914400.0)
        if is_chart:
            targets.append((sh, "chart"))
        elif has_text:
            targets.append((sh, "text"))
        elif st == 13 or 0.04 < area < 2.5:
            targets.append((sh, "small"))
    targets = targets[:26]
    if not targets:
        return
    ids = iter(range(5, 800))
    inner = ""
    for k, (sh, kind) in enumerate(targets):
        node_type = "afterEffect" if k == 0 else "withEffect"
        delay = 0 if k == 0 else min(k * 70, 700)
        inner += _effect_xml(ids, _pick_fx(idx, k, kind, rise), node_type, delay, sh.shape_id)
    xml = (
        '<p:timing xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:tnLst><p:par>'
        '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        '<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
        '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>'
        '<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        + inner +
        '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
        '</p:childTnLst></p:cTn>'
        '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
        '</p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>')
    el = slide._element
    old = el.find(qn("p:timing"))
    if old is not None:
        el.remove(old)
    node = parse_xml(xml)
    ext = el.find(qn("p:extLst"))
    if ext is not None:
        ext.addprevious(node)
    else:
        el.append(node)


def wrap_timing(orig):
    def timing(slide, idx):
        try:
            polish_typography(slide)
        except Exception as exc:
            log.warning("typography polish skipped: %s", exc)
        try:
            return build_timing(slide, idx)
        except Exception as exc:
            log.warning("premium animation skipped, using original: %s", exc)
            return orig(slide, idx)
    return timing


# ------------------------------------------------------------------ wiring
def schedule(builder_class, timeout=180.0):
    mod = sys.modules.get(getattr(builder_class, "__module__", ""))
    if mod is None:
        return

    def worker():
        deadline = time.time() + timeout
        while time.time() < deadline:
            if hasattr(mod, "_ppt_find_photo_sync") and hasattr(mod, "_v8_timing") and hasattr(mod, "main"):
                time.sleep(1.5)         # let ppt_user_fixes wrap the photo search first
                done = []
                try:
                    mod._ppt_find_photo_sync = wrap_photo_search(mod._ppt_find_photo_sync)
                    done.append("photo dedupe")
                except Exception as exc:
                    log.error("photo dedupe not installed: %s", exc)
                try:
                    mod._v8_timing = wrap_timing(mod._v8_timing)
                    done.append("animation+typography")
                except Exception as exc:
                    log.error("animation/typography not installed: %s", exc)
                log.info("ppt_premium active: %s", ", ".join(done) or "nothing")
                return
            time.sleep(0.25)
        log.warning("ppt_premium: bot module never finished loading; nothing patched")

    threading.Thread(target=worker, name="ppt_premium", daemon=True).start()
