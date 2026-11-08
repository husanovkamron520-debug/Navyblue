"""GRAND ROYAL PALACE MUSEUM — 3D virtual muzey (Telegram Mini App + bot boshqaruvi).

bot.py bilan ulanishi:
    museum.init(load_json, save_json, TELEGRAM_BOT_TOKEN, _cw_app_base, OWNER_CHAT_ID)
    museum.install(app)
    museum.http_get(handler, parsed_url)       # /museum, /museum/data, /museum/m
    await museum.on_text(update, context, text, is_menu_button)
    await museum.on_media(update, context)
"""
import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

logger = logging.getLogger("museum")

BTN_MUSEUM = "🏛 3D Muzey"
MUSEUM_FILE = "museum_data.json"
ROOMS = max(1, min(20, int(os.environ.get("MUSEUM_ROOMS") or 20)))
MAX_ITEMS = 12
MAX_MEDIA_BYTES = 20 * 1024 * 1024          # Telegram bot getFile limiti
CACHE_DIR = os.path.join(tempfile.gettempdir(), "museum_cache")

THEMES = {
    "gold":   {"label": "👑 Qirollik oltini", "wall": "e9d9a8", "floor": "8a6d2f", "accent": "c9a227"},
    "ocean":  {"label": "🌊 Dengiz",          "wall": "bfe3f2", "floor": "2b5f7a", "accent": "1f78a8"},
    "forest": {"label": "🌲 O'rmon",          "wall": "cfe5c4", "floor": "3f6b3a", "accent": "2f8f4a"},
    "fire":   {"label": "🔥 Olov",            "wall": "f2c9b8", "floor": "7a2f22", "accent": "d9482b"},
    "violet": {"label": "🔮 Binafsha",        "wall": "d9cdf0", "floor": "4d3a7a", "accent": "7a4fd0"},
    "snow":   {"label": "❄️ Qor",             "wall": "f2f5f8", "floor": "9aa8b5", "accent": "5c7ea3"},
    "night":  {"label": "🌑 Tun",             "wall": "4b5568", "floor": "1c2230", "accent": "e0b94a"},
    "rose":   {"label": "🌸 Pushti",          "wall": "f6d5e1", "floor": "8a3f5d", "accent": "d9578a"},
}
THEME_KEYS = list(THEMES)

# 20 ta xona: (ism, jins 'm'/'f', hijob). Tartib = xona raqami.
# Egasi (siz) ismlarni, jinsni va hijobni muzeydagi «👑 Egasi» panelidan o'zgartira olasiz.
ROSTER = [
    ("Abror", "m", False), ("Sardor", "m", False), ("Sabina", "f", True), ("Mirvosid", "m", False),
    ("Shuhrat", "m", False), ("Nozima", "f", True), ("Lobar", "f", False), ("Nodira", "f", False),
    ("Gulsevar", "f", False), ("Kamola", "f", True), ("Shohjahon", "m", False), ("Hamidulla", "m", False),
    ("Olim", "m", False), ("Doniyor", "m", False), ("O'tkir", "m", False), ("Zafar", "m", False),
    ("Kamron", "m", False), ("Ozodbek", "m", False), ("Malika", "f", False), ("Surayyo", "f", True),
]
_ATT = {}      # kod urinishlari (brute-force'dan himoya)
_SESSIONS = {} # faqat kod bilan tasdiqlangan WebApp sessiyalari
_SESSION_TTL = 4 * 60 * 60
_ST_CACHE = {"t": 0, "v": None}

_D = {}
_LOCK = threading.RLock()


def init(load_json, save_json, token, base_url_fn, owner_id):
    _D.update(load=load_json, save=save_json, token=token or "", base=base_url_fn, owner=owner_id)


# ============================================================
# MA'LUMOTLAR
# ============================================================
def _norm(code):
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def _new_code(d, name):
    pre = re.sub(r"[^A-Z]", "", str(name).upper())[:3].ljust(3, "X")
    used = {_norm(p.get("code", "")) for p in d.get("people", {}).values()}
    while True:
        c = f"{pre}-{secrets.randbelow(90000) + 10000}"
        if _norm(c) not in used:
            return c


def _ensure(d):
    """20 ta xona va har biriga shaxs yozuvi (ism + kod) bo'lishini ta'minlaydi."""
    ch = False
    for i, (nm, g, hj) in enumerate(ROSTER, 1):
        if i > ROOMS:
            break
        k = str(i)
        r = d["rooms"].get(k)
        if r is None:
            r = d["rooms"][k] = {"owner": None, "name": nm, "title": "Mening xonam",
                                 "theme": THEME_KEYS[(i - 1) % len(THEME_KEYS)], "items": [], "ts": int(time.time())}
            ch = True
        if k not in d["people"]:
            d["people"][k] = {"name": nm, "g": g, "h": bool(hj and g == "f"),
                              "code": _new_code(d, nm), "uid": r.get("owner")}
            ch = True
    return ch


def _load():
    with _LOCK:
        d = _D["load"](MUSEUM_FILE, {})
        if not isinstance(d, dict):
            d = {}
        d.setdefault("rooms", {})
        d.setdefault("owners", {})
        d.setdefault("people", {})
        if _ensure(d):
            _save(d)
        return d


def _save(d):
    _D["save"](MUSEUM_FILE, d)


def _sig(text: str) -> str:
    return hmac.new(_D["token"].encode(), text.encode(), hashlib.sha256).hexdigest()[:20]


def _is_owner(uid):
    try:
        o = _D.get("owner")
        return o is not None and str(o).strip() != "" and int(uid) == int(o)
    except (TypeError, ValueError):
        return False


def _rate_ok(uid):
    now = time.time()
    a = [t for t in _ATT.get(uid, []) if now - t < 600]
    _ATT[uid] = a
    return len(a) < 8


def _rate_fail(uid):
    _ATT.setdefault(uid, []).append(time.time())


def _new_session(uid):
    """Faqat to'g'ri shaxsiy koddan keyin 4 soatlik tasodifiy WebApp sessiyasi."""
    now = time.time()
    with _LOCK:
        for token, info in list(_SESSIONS.items()):
            if info.get("exp", 0) <= now:
                _SESSIONS.pop(token, None)
        token = secrets.token_urlsafe(32)
        _SESSIONS[token] = {"uid": int(uid), "exp": now + _SESSION_TTL}
        return token


def _session_ok(token, uid=None):
    if not token:
        return False
    now = time.time()
    with _LOCK:
        info = _SESSIONS.get(str(token))
        if not info:
            return False
        if info.get("exp", 0) <= now:
            _SESSIONS.pop(str(token), None)
            return False
        return uid is None or int(info.get("uid", -1)) == int(uid)


def _login(uid, code):
    """Kod bo'yicha kirish. Qaytadi: (xona_raqami, xato) — xato: None | 'bad' | 'has'."""
    c = _norm(code)
    if len(c) < 4:
        return None, "bad"
    with _LOCK:
        d = _load()
        cur = d["owners"].get(str(uid))
        for k, p in d["people"].items():
            if _norm(p.get("code", "")) == c:
                if cur and str(cur) != k:
                    return int(cur), "has"
                old = p.get("uid")
                if old and int(old) != uid:
                    d["owners"].pop(str(old), None)
                p["uid"] = uid
                d["owners"][str(uid)] = int(k)
                d["rooms"][k]["owner"] = uid
                _save(d)
                return int(k), None
    return None, "bad"


def _my_room(uid):
    d = _load()
    n = d["owners"].get(str(uid))
    return (int(n), d["rooms"].get(str(n))) if n else (None, None)


def _target_n(d, uid, room=None):
    """Oddiy foydalanuvchi — faqat o'z xonasi. Muzey egasi — tanlangan istalgan xona."""
    if room and _is_owner(uid) and str(int(room)) in d["rooms"]:
        return int(room)
    n = d["owners"].get(str(uid))
    return int(n) if n else None


def _add_item(uid, item, room=None):
    """Oddiy foydalanuvchi uchun faqat qo'shish; muzey egasi istalgan xonani boshqara oladi."""
    with _LOCK:
        d = _load()
        n = _target_n(d, uid, room)
        if not n:
            return "noroom"
        r = d["rooms"][str(n)]
        if len(r["items"]) >= MAX_ITEMS:
            return "full"
        r["items"].append(item)
        _save(d)
        return len(r["items"])


def _del_item(uid, room, item_id):
    """Faqat muzey egasi: eksponatni o'chirish."""
    if not _is_owner(uid):
        return False
    with _LOCK:
        d = _load()
        r = d["rooms"].get(str(room))
        if not r:
            return False
        before = len(r.get("items", []))
        r["items"] = [it for it in r.get("items", []) if it.get("id") != item_id]
        if len(r["items"]) == before:
            return False
        _save(d)
        return True


def _replace_item(uid, room, item_id, data):
    """Faqat muzey egasi: eksponatni (rasm/video/matn) joyida almashtirish."""
    if not _is_owner(uid):
        return False
    with _LOCK:
        d = _load()
        r = d["rooms"].get(str(room))
        if not r:
            return False
        for it in r.get("items", []):
            if it.get("id") == item_id:
                it.update(data)
                _save(d)
                return True
    return False


def _acting(uid, context):
    """Egasi hozir qaysi xonani boshqarayotgani (None — o'z menyusi)."""
    try:
        n = context.user_data.get("_mu_as")
    except Exception:
        n = None
    return int(n) if (n and _is_owner(uid)) else None


def _room_for(uid, context):
    a = _acting(uid, context)
    if a:
        r = _load()["rooms"].get(str(a))
        return (a, r) if r else (None, None)
    return _my_room(uid)


def _edit(uid, field, value, item_id=None, room=None):
    with _LOCK:
        d = _load()
        n = _target_n(d, uid, room)
        if not n:
            return False
        r = d["rooms"][str(n)]
        if item_id:
            for it in r["items"]:
                if it["id"] == item_id:
                    it["cap"] = value
                    _save(d)
                    return True
            return False
        r[field] = value
        _save(d)
        return True


# ============================================================
# ESHIK KODI (xona egasi / muzey egasi qo'yadi; kodni bilmaganlar kira olmaydi va eksponatlarni ko'ra olmaydi)
# ============================================================
_UNLOCK = {}              # uid -> {xona: tugash vaqti}
_UNLOCK_TTL = 4 * 60 * 60
LOCK_MIN, LOCK_MAX = 3, 16


def _lock_hash(n, code):
    return _sig(f"lock:{int(n)}:{str(code or '').strip()}")


def _can_manage(uid, n, d=None):
    d = d or _load()
    if _is_owner(uid):
        return True
    mine = d["owners"].get(str(uid))
    return bool(mine) and int(mine) == int(n)


def _is_unlocked(uid, n):
    with _LOCK:
        return (_UNLOCK.get(int(uid)) or {}).get(int(n), 0) > time.time()


def _locked_for(uid, n, d, r=None):
    r = r or d["rooms"].get(str(n)) or {}
    if not r.get("lock"):
        return False
    return not (_can_manage(uid, n, d) or _is_unlocked(uid, n))


# ============================================================
# TELEGRAM initData TEKSHIRUVI
# ============================================================
def _verify(init: str):
    try:
        pairs = dict(urllib.parse.parse_qsl(init or "", keep_blank_values=True))
        got = pairs.pop("hash", None)
        if not got:
            return None
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", _D["token"].encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > 7 * 86400:
            return None
        user = json.loads(pairs.get("user") or "{}")
        return user if user.get("id") else None
    except Exception:
        return None


# ============================================================
# HTTP: /museum, /museum/data, /museum/m
# ============================================================
def _send(h, code, body, ctype, extra=None):
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(body)))
    for k, v in (extra or {}).items():
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(body)


def _json(h, code, obj):
    _send(h, code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
          {"Cache-Control": "no-store"})


def _prune_cache():
    try:
        files = []
        for fn in os.listdir(CACHE_DIR):
            p = os.path.join(CACHE_DIR, fn)
            if os.path.isfile(p) and not p.endswith(".part"):
                files.append((os.path.getatime(p), p, os.path.getsize(p)))
        total = sum(f[2] for f in files)
        if total <= 500 * 1024 * 1024:
            return
        for _t, p, s in sorted(files):
            if total <= 350 * 1024 * 1024:
                break
            try:
                os.remove(p)
                total -= s
            except OSError:
                pass
    except Exception:
        pass


_DL_LOCKS = {}
_DL_GUARD = threading.Lock()


def _cache_path(fid, suffix=""):
    return os.path.join(CACHE_DIR, hashlib.sha1(fid.encode()).hexdigest() + suffix)


def _get_file(fid):
    os.makedirs(CACHE_DIR, exist_ok=True)
    dest = _cache_path(fid)
    if os.path.exists(dest):
        return dest
    with _DL_GUARD:
        lock = _DL_LOCKS.setdefault(fid, threading.Lock())
    with lock:
        if os.path.exists(dest):
            return dest
        tok = _D["token"]
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{tok}/getFile?file_id={urllib.parse.quote(fid)}", timeout=30) as r:
            fpath = json.loads(r.read())["result"]["file_path"]
        tmp = dest + ".part"
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{tok}/{fpath}", timeout=120) as r, \
                open(tmp, "wb") as out:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, dest)
        _prune_cache()
    return dest


def _get_thumb(fid):
    dest = _cache_path(fid, "_t.jpg")
    if os.path.exists(dest):
        return dest
    src = _get_file(fid)
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im.thumbnail((1024, 1024))
    tmp = dest + ".part"
    im.save(tmp, "JPEG", quality=82)
    os.replace(tmp, dest)
    return dest


def _serve_file(h, path, ctype):
    size = os.path.getsize(path)
    start, end, code = 0, size - 1, 200
    rng = h.headers.get("Range")
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if m:
            a, b = m.groups()
            if a == "" and b:
                start = max(0, size - int(b))
            elif a:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
            code = 206
            if start > end or start >= size:
                h.send_response(416)
                h.send_header("Content-Range", f"bytes */{size}")
                h.send_header("Content-Length", "0")
                h.end_headers()
                return
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Accept-Ranges", "bytes")
    h.send_header("Cache-Control", "private, max-age=3600")
    h.send_header("Content-Length", str(end - start + 1))
    if code == 206:
        h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    h.end_headers()
    left = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while left > 0:
            chunk = fh.read(min(65536, left))
            if not chunk:
                break
            h.wfile.write(chunk)
            left -= len(chunk)


def _find_item_room(iid):
    for k, r in _load()["rooms"].items():
        for it in r.get("items", []):
            if it.get("id") == iid:
                return int(k)
    return None


def _find_item(iid):
    for r in _load()["rooms"].values():
        for it in r.get("items", []):
            if it.get("id") == iid:
                return it
    return None


def _http_data(h):
    user = _verify(h.headers.get("X-Init", ""))
    if not user:
        _json(h, 401, {"error": "auth"})
        return
    uid = int(user["id"])
    session = h.headers.get("X-Museum-Session", "")
    owner = _is_owner(uid)
    if not _session_ok(session, uid):
        if not owner:
            _json(h, 401, {"error": "code_required"})
            return
        session = _new_session(uid)   # muzey egasi (OWNER_CHAT_ID) shaxsiy kodsiz, avtomatik tanib olinadi
    d = _load()
    mine = d["owners"].get(str(uid))
    rooms = []
    for k, r in d["rooms"].items():
        n = int(k)
        if n > ROOMS:
            continue
        items = []
        locked = _locked_for(uid, n, d, r)
        for it in ([] if locked else r.get("items", [])):
            sg = _sig(it["id"])
            base = f"/museum/m?i={it['id']}&k={sg}&s={urllib.parse.quote(session)}&c={_sig(str(it.get('fid') or ''))[:6]}"
            items.append({"id": it["id"], "type": it["type"], "cap": it.get("cap", ""),
                          "u": base + "&v=t", "f": base + "&v=f"})
        rooms.append({"n": n, "name": r.get("name", ""), "title": r.get("title", ""),
                      "theme": r.get("theme", "gold"), "mine": (mine is not None and int(mine) == n), "items": items,
                      "locked": locked, "lockSet": bool(r.get("lock")) and _can_manage(uid, n, d)})
    pp = d["people"].get(str(mine)) if mine else None
    me = {"n": int(mine) if mine else None,
          "name": (pp or {}).get("name") or user.get("first_name") or "",
          "g": (pp or {}).get("g", "m"), "h": bool((pp or {}).get("h")), "owner": _is_owner(uid)}
    _json(h, 200, {"rooms": rooms, "themes": THEMES, "total": ROOMS, "max": MAX_ITEMS,
                   "mine": int(mine) if mine else None, "me": me,
                   "session": session if owner else None})


def _http_media(h, u):
    q = urllib.parse.parse_qs(u.query)
    iid = (q.get("i") or [""])[0]
    k = (q.get("k") or [""])[0]
    v = (q.get("v") or ["f"])[0]
    session = (q.get("s") or [""])[0]
    if not _session_ok(session):
        _send(h, 401, b"code required", "text/plain")
        return
    if not iid or not hmac.compare_digest(_sig(iid), k):
        _send(h, 403, b"forbidden", "text/plain")
        return
    it = _find_item(iid)
    if not it or not it.get("fid"):
        _send(h, 404, b"not found", "text/plain")
        return
    rn = _find_item_room(iid)
    sess_uid = (_SESSIONS.get(session) or {}).get("uid")
    if rn and sess_uid is not None and _locked_for(sess_uid, rn, _load()):
        _send(h, 403, b"locked", "text/plain")
        return
    try:
        if it["type"] == "image" and v == "t":
            _serve_file(h, _get_thumb(it["fid"]), "image/jpeg")
        else:
            default = "video/mp4" if it["type"] == "video" else "image/jpeg"
            _serve_file(h, _get_file(it["fid"]), it.get("mime") or default)
    except (BrokenPipeError, ConnectionResetError):
        raise
    except Exception:
        logger.warning("Muzey fayli olinmadi", exc_info=True)
        _send(h, 502, b"upstream error", "text/plain")


def _ago(sec):
    if sec < 60:
        return f"{sec} s oldin"
    if sec < 3600:
        return f"{sec // 60} daq oldin"
    return f"{sec // 3600} soat oldin"


def _db_status():
    """Supabase holati (tarmoq so'rovi bilan). Natija keshga ham yoziladi."""
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    out = {"mode": "supabase" if (url and key) else "local", "ok": False, "ms": None,
           "saved_ago": None, "err": "", "rooms": 0, "bound": 0, "items": 0}
    try:
        d = _load()
        out["rooms"] = len(d["rooms"])
        out["bound"] = sum(1 for p in d["people"].values() if p.get("uid"))
        out["items"] = sum(len(r.get("items", [])) for r in d["rooms"].values())
    except Exception as e:
        out["err"] = ("o'qib bo'lmadi: " + str(e))[:120]
    if out["mode"] == "local":
        out["ok"] = True
    else:
        headers = {"apikey": key, "User-Agent": "museum-status/1.0"}
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        t0 = time.time()
        try:
            req = urllib.request.Request(
                f"{url}/rest/v1/bot_storage?storage_key=eq.museum_data&select=updated_at", headers=headers)
            with urllib.request.urlopen(req, timeout=6) as r:
                rows = json.loads(r.read() or b"[]")
            out["ms"] = int((time.time() - t0) * 1000)
            out["ok"] = True
            if rows and rows[0].get("updated_at"):
                try:
                    dt = datetime.fromisoformat(str(rows[0]["updated_at"]).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    out["saved_ago"] = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
                except Exception:
                    pass
        except Exception as e:
            out["err"] = str(e)[:120]
    _ST_CACHE.update(t=time.time(), v=out)
    return out


def _status_line(st):
    if st["mode"] == "supabase":
        t = "🟢 Supabase" if st["ok"] else "🔴 Supabase"
        if st["ok"]:
            t += f" · {st['ms']} ms · oxirgi saqlash " + (_ago(st["saved_ago"]) if st["saved_ago"] is not None
                                                          else "hali yozilmagan")
        else:
            t += " · xato: " + (st["err"] or "?")
    else:
        t = "🟡 Lokal fayl (Render qayta ishga tushsa o'chadi) — Supabase kalitlari yo'q"
    return t + f" · muzey: {st['rooms']} xona, {st['bound']} kirgan, {st['items']} eksponat"


def db_status_line(short=False):
    """bot.py dagi /holat uchun bir qatorli Supabase holati. short=True — tarmoqsiz (keshdan)."""
    st = _ST_CACHE["v"]
    if short:
        if not st or time.time() - _ST_CACHE["t"] > 300:
            return "💾 Supabase: aniq holat uchun /holat yuboring"
    else:
        st = _db_status()
    return "💾 " + _status_line(st)


def _codes_text(d=None):
    d = d or _load()
    lines = ["🔑 Muzey kodlari — har kimga faqat o'zinikini yuboring:", ""]
    for i in range(1, ROOMS + 1):
        p = d["people"].get(str(i))
        if p:
            lines.append(f"№{i} {p['name']}{' 🧕' if p.get('h') else ''} — {p['code']} {'🟢' if p.get('uid') else '⚪'}")
    lines.append("")
    lines.append("🟢 kirgan · ⚪ hali kirmagan")
    return "\n".join(lines)


def _tg_send(chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{_D['token']}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


def _pub_person(d, k):
    p = d["people"][k]
    return {"n": int(k), "name": p.get("name", ""), "g": p.get("g", "m"), "h": bool(p.get("h")),
            "code": p.get("code", ""), "uid": p.get("uid")}


def _http_login(h, u):
    user = _verify(h.headers.get("X-Init", ""))
    if not user:
        _json(h, 401, {"error": "auth"})
        return
    uid = int(user["id"])
    if not _rate_ok(uid):
        _json(h, 200, {"ok": False, "error": "Juda ko'p urinish. 10 daqiqadan keyin qayta urinib ko'ring."})
        return
    code = (urllib.parse.parse_qs(u.query).get("c") or [""])[0]
    n, err = _login(uid, code)
    if err == "bad":
        _rate_fail(uid)
        _json(h, 200, {"ok": False, "error": "Kod noto'g'ri. Tekshirib, qayta kiriting."})
    elif err == "has":
        _json(h, 200, {"ok": False, "error": f"Siz allaqachon №{n} xonaga bog'langansiz."})
    else:
        session = _new_session(uid)
        _json(h, 200, {"ok": True, "n": n, "session": session})


def _http_adm(h, u):
    """Faqat egasi (OWNER_CHAT_ID) uchun: ro'yxat, tahrirlash, kodni yangilash, holat."""
    user = _verify(h.headers.get("X-Init", ""))
    if not user:
        _json(h, 401, {"error": "auth"})
        return
    uid = int(user["id"])
    if not _is_owner(uid) and not _session_ok(h.headers.get("X-Museum-Session", ""), uid):
        _json(h, 401, {"error": "code_required"})
        return
    if not _is_owner(uid):
        _json(h, 403, {"ok": False, "error": "Faqat egasi uchun"})
        return
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    op = q.get("op", "")
    if op == "status":
        _json(h, 200, _db_status())
        return
    with _LOCK:
        d = _load()
        if op == "list":
            _json(h, 200, {"ok": True, "people": [_pub_person(d, str(i)) for i in range(1, ROOMS + 1)
                                                  if str(i) in d["people"]]})
            return
        if op == "send":
            try:
                _tg_send(_D["owner"], _codes_text(d))
                _json(h, 200, {"ok": True})
            except Exception as e:
                _json(h, 200, {"ok": False, "error": str(e)[:100]})
            return
        k = q.get("n", "")
        if not k.isdigit() or k not in d["people"]:
            _json(h, 200, {"ok": False, "error": "Xona topilmadi"})
            return
        p, r = d["people"][k], d["rooms"][k]
        if op == "set":
            f, v = q.get("f", ""), q.get("v", "")
            if f == "name":
                v = v.strip()[:30]
                if not v:
                    _json(h, 200, {"ok": False, "error": "Ism bo'sh bo'lmasin"})
                    return
                p["name"] = v
                r["name"] = v
            elif f == "g" and v in ("m", "f"):
                p["g"] = v
                if v == "m":
                    p["h"] = False
            elif f == "h":
                p["h"] = (v == "1") and p.get("g") == "f"
            else:
                _json(h, 200, {"ok": False, "error": "Noto'g'ri maydon"})
                return
        elif op == "regen":
            p["code"] = _new_code(d, p.get("name", "X"))
        elif op == "unbind":
            old = p.get("uid")
            if old:
                d["owners"].pop(str(old), None)
            p["uid"] = None
            r["owner"] = None
        else:
            _json(h, 200, {"ok": False, "error": "Noma'lum amal"})
            return
        _save(d)
        _json(h, 200, {"ok": True, "p": _pub_person(d, k)})


_PUT_LOG = {}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _put_rate_ok(uid):
    now = time.time()
    lst = [t for t in _PUT_LOG.get(uid, []) if now - t < 600]
    _PUT_LOG[uid] = lst
    if len(lst) >= 12:
        return False
    lst.append(now)
    return True


def _tg_send_photo(chat_id, jpeg, caption=""):
    """Rasmni Telegramga yuboradi va doimiy file_id qaytaradi (baza faqat file_id saqlaydi)."""
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"
    body = b""
    for k, v in (("chat_id", str(chat_id)), ("caption", caption), ("disable_notification", "true")):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"museum.jpg\"\r\n"
             "Content-Type: image/jpeg\r\n\r\n").encode("utf-8") + jpeg + crlf + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{_D['token']}/sendPhoto", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=45) as r:
        res = json.loads(r.read())
    return res["result"]["photo"][-1]["file_id"]


def _item_broken(it):
    """Rasm fayli Telegramdan olinmasa — 'buzilgan' deb hisoblanadi."""
    if it.get("type") != "image" or not it.get("fid"):
        return True
    try:
        _get_file(it["fid"])
        return False
    except Exception:
        return True


def _put_replace(room, item_id, data):
    with _LOCK:
        d = _load()
        r = d["rooms"].get(str(room))
        if not r:
            return False
        for it in r.get("items", []):
            if it.get("id") == item_id:
                it.update(data)
                _save(d)
                return True
    return False


def _http_put(h, u):
    user = _verify(h.headers.get("X-Init", ""))
    if not user:
        _json(h, 401, {"ok": False, "msg": "Kirish tasdiqlanmadi"})
        return
    uid = int(user["id"])
    owner = _is_owner(uid)
    if not owner and not _session_ok(h.headers.get("X-Museum-Session", ""), uid):
        _json(h, 401, {"ok": False, "msg": "Avval kod bilan kiring"})
        return
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    try:
        n = int(q.get("n", "0"))
    except ValueError:
        n = 0
    iid = q.get("i", "")
    d = _load()
    mine = d["owners"].get(str(uid))
    if n < 1 or n > ROOMS or str(n) not in d["rooms"]:
        _json(h, 400, {"ok": False, "msg": "Xona topilmadi"})
        return
    if not owner and (not mine or int(mine) != n):
        _json(h, 403, {"ok": False, "msg": "Faqat o'z xonangizga rasm qo'ya olasiz"})
        return
    target = None
    if iid:
        target = next((it for it in d["rooms"][str(n)].get("items", []) if it.get("id") == iid), None)
        if not target:
            _json(h, 404, {"ok": False, "msg": "Eksponat topilmadi"})
            return
        if not owner and not _item_broken(target):
            _json(h, 403, {"ok": False, "msg": "Bu rasm normal ochilyapti. Faqat buzilgan rasmni almashtirish mumkin"})
            return
    elif len(d["rooms"][str(n)].get("items", [])) >= MAX_ITEMS:
        _json(h, 409, {"ok": False, "msg": f"Xona to'ldi ({MAX_ITEMS}/{MAX_ITEMS})"})
        return
    try:
        ln = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        ln = 0
    if ln <= 0 or ln > MAX_UPLOAD_BYTES:
        _json(h, 413, {"ok": False, "msg": "Rasm hajmi noto'g'ri yoki 8 MB dan katta"})
        return
    if not _put_rate_ok(uid):
        _json(h, 429, {"ok": False, "msg": "Juda ko'p urinish. Bir necha daqiqadan keyin qayta urining"})
        return
    raw = h.rfile.read(ln)
    try:
        from PIL import Image, ImageOps
        import io
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        im.thumbnail((2000, 2000))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        jpeg = buf.getvalue()
    except Exception:
        _json(h, 400, {"ok": False, "msg": "Bu rasm emas yoki fayl buzilgan"})
        return
    try:
        fid = _tg_send_photo(uid, jpeg, f"🖼 LOG-324 muzey · №{n} xona: rasm qo'yildi")
    except Exception:
        logger.warning("Muzey: rasmni Telegramga yuborib bo'lmadi", exc_info=True)
        _json(h, 502, {"ok": False, "msg": "Telegramga yuklab bo'lmadi. Birozdan keyin qayta urining"})
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(fid), "wb") as f:
            f.write(jpeg)
    except Exception:
        pass
    data = {"type": "image", "fid": fid, "mime": "image/jpeg"}
    if target:
        ok = _put_replace(n, iid, data)
        res = "replaced" if ok else None
    else:
        data.update({"id": uuid.uuid4().hex[:10], "cap": "", "ts": int(time.time())})
        res = _add_item(uid, data, room=n)
        ok = isinstance(res, int)
    if not ok:
        _json(h, 500, {"ok": False, "msg": "Saqlab bo'lmadi"})
        return
    _json(h, 200, {"ok": True})


def _lock_auth(h):
    user = _verify(h.headers.get("X-Init", ""))
    if not user:
        _json(h, 401, {"error": "auth"})
        return None
    uid = int(user["id"])
    if not _is_owner(uid) and not _session_ok(h.headers.get("X-Museum-Session", ""), uid):
        _json(h, 401, {"error": "code_required"})
        return None
    return uid


def _http_lock(h, u):
    """Eshikka kod qo'yish/o'chirish: faqat xona egasi yoki muzey egasi."""
    uid = _lock_auth(h)
    if uid is None:
        return
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    try:
        n = int(q.get("n", "0"))
    except ValueError:
        n = 0
    code = (q.get("c") or "").strip()
    with _LOCK:
        d = _load()
        if n < 1 or n > ROOMS or str(n) not in d["rooms"]:
            _json(h, 200, {"ok": False, "msg": "Xona topilmadi"})
            return
        if not _can_manage(uid, n, d):
            _json(h, 200, {"ok": False, "msg": "Faqat o'z xonangizga kod qo'ya olasiz"})
            return
        r = d["rooms"][str(n)]
        if not code:
            r.pop("lock", None)
            msg = "Eshik kodi o'chirildi"
        else:
            if not (LOCK_MIN <= len(code) <= LOCK_MAX):
                _json(h, 200, {"ok": False, "msg": f"Kod {LOCK_MIN}–{LOCK_MAX} belgidan iborat bo'lsin"})
                return
            r["lock"] = _lock_hash(n, code)
            for m in _UNLOCK.values():      # eski ochilgan sessiyalar yopiladi
                m.pop(n, None)
            msg = "Eshik kodi saqlandi"
        _save(d)
    _json(h, 200, {"ok": True, "msg": msg})


def _http_unlock(h, u):
    uid = _lock_auth(h)
    if uid is None:
        return
    key = f"lk{uid}"
    if not _rate_ok(key):
        _json(h, 200, {"ok": False, "msg": "Juda ko'p urinish. 10 daqiqadan keyin qayta urinib ko'ring."})
        return
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    try:
        n = int(q.get("n", "0"))
    except ValueError:
        n = 0
    code = (q.get("c") or "").strip()
    d = _load()
    r = d["rooms"].get(str(n))
    if not r or n < 1 or n > ROOMS:
        _json(h, 200, {"ok": False, "msg": "Xona topilmadi"})
        return
    lk = r.get("lock")
    if not lk or hmac.compare_digest(lk, _lock_hash(n, code)):
        if lk:
            with _LOCK:
                _UNLOCK.setdefault(uid, {})[n] = time.time() + _UNLOCK_TTL
        _json(h, 200, {"ok": True})
    else:
        _rate_fail(key)
        _json(h, 200, {"ok": False, "msg": "Kod noto'g'ri"})


def http_post(h, u):
    try:
        p = u.path.rstrip("/") or "/"
        if p == "/museum/put":
            _http_put(h, u)
        else:
            _send(h, 404, b"not found", "text/plain")
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception:
        logger.exception("Muzey POST xatosi")
        try:
            _send(h, 500, b"error", "text/plain")
        except Exception:
            pass


def http_get(h, u):
    try:
        p = u.path.rstrip("/") or "/"
        if p == "/museum/login":
            _http_login(h, u)
        elif p == "/museum/adm":
            _http_adm(h, u)
        elif p == "/museum":
            _send(h, 200, MUSEUM_HTML.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": "no-store"})
        elif p == "/museum/data":
            _http_data(h)
        elif p == "/museum/lock":
            _http_lock(h, u)
        elif p == "/museum/unlock":
            _http_unlock(h, u)
        elif p == "/museum/m":
            _http_media(h, u)
        else:
            _send(h, 404, b"not found", "text/plain")
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception:
        logger.exception("Muzey HTTP xatosi")
        try:
            _send(h, 500, b"error", "text/plain")
        except Exception:
            pass


# ============================================================
# BOT: menyu, xona olish, qo'shish, tahrirlash (o'chirish yo'q)
# ============================================================
def _clear(context):
    context.user_data.pop("_mu_wait", None)


def _db_badge():
    if (os.environ.get("SUPABASE_URL") or "").strip() and (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip():
        return "🟢 Supabase ulangan"
    return "🟡 Lokal fayl (qayta ishga tushganda o'chadi)"


def _menu_view(uid, name, acting=None):
    d = _load()
    n = acting or d["owners"].get(str(uid))
    base = _D["base"]()
    rows = []
    if base:
        rows.append([InlineKeyboardButton("🏛 Muzeyga kirish (3D)", web_app=WebAppInfo(url=base + "/museum"))])
    bound = sum(1 for p in d["people"].values() if p.get("uid"))
    head = f"🏛 LOG-324 3D MUZEY\n👥 Kirganlar: {bound}/{ROOMS}\n💾 Baza: {_db_badge()}\n\n"
    if n and d["rooms"].get(str(n)):
        r = d["rooms"][str(n)]
        if acting:
            head += (f"👑 EGASI REJIMI — boshqarilayotgan xona: №{n} · {r.get('name', '')}\n"
                     f"🏷 Nomi: «{r.get('title', '')}»\n"
                     f"🎨 Mavzu: {THEMES.get(r.get('theme'), THEMES['gold'])['label']}\n"
                     f"🖼 Eksponatlar: {len(r['items'])}/{MAX_ITEMS}\n\n"
                     "Siz bu xonaga rasm/video/matn qo'sha, almashtira va o'chira olasiz.")
        else:
            head += (f"🚪 Sizning xonangiz: №{n} · «{r.get('title', '')}»\n"
                     f"🎨 Mavzu: {THEMES.get(r.get('theme'), THEMES['gold'])['label']}\n"
                     f"🖼 Eksponatlar: {len(r['items'])}/{MAX_ITEMS}\n\n"
                     "Rasm, video yoki matn qo'shishingiz, izoh va mavzuni o'zgartirishingiz mumkin.\n"
                     "⚠️ Qo'shilgan eksponatni o'chirib bo'lmaydi.")
        rows.append([InlineKeyboardButton("➕ Rasm / video / matn qo'shish", callback_data="mu:add")])
        rows.append([InlineKeyboardButton("📝 Izohlarni tahrirlash", callback_data="mu:caps"),
                     InlineKeyboardButton("🏷 Xona nomi", callback_data="mu:title")])
        rows.append([InlineKeyboardButton("🎨 Mavzu (rang)", callback_data="mu:theme"),
                     InlineKeyboardButton("👤 Ismim", callback_data="mu:name")])
        if acting:
            rows.append([InlineKeyboardButton("🔁 Almashtirish", callback_data="mu:orep"),
                         InlineKeyboardButton("🗑 O'chirish", callback_data="mu:odel")])
            rows.append([InlineKeyboardButton("🛠 Boshqa xona", callback_data="mu:oroom"),
                         InlineKeyboardButton("↩️ O'z menyuim", callback_data="mu:oself")])
    else:
        if _is_owner(uid):
            head += "👑 Siz muzey egasisiz — muzeyga kod so'ralmasdan, to'g'ridan-to'g'ri kirasiz."
        else:
            head += "Sizda hali xona yo'q. Sizga berilgan kodni «🔑 Kod bilan kirish» orqali kiriting — xonangiz ochiladi."
        rows.append([InlineKeyboardButton("🔑 Kod bilan kirish", callback_data="mu:code")])
    if _is_owner(uid):
        if not acting:
            head += "\n\n👑 Siz — muzey egasisiz. Ismlar/kodlar: muzeydagi «👑 Egasi» tugmasi."
            rows.append([InlineKeyboardButton("🛠 Xonalarni boshqarish (rasm almashtirish/o'chirish)", callback_data="mu:oroom")])
        rows.append([InlineKeyboardButton("👑 Kodlar ro'yxati", callback_data="mu:codes"),
                     InlineKeyboardButton("📡 Holat", callback_data="mu:status")])
    if not base:
        head += "\n\n⚠️ RENDER_EXTERNAL_URL sozlanmagan — 3D muzey ochilmaydi."
    return head, InlineKeyboardMarkup(rows)


async def _menu(msg, uid, name, acting=None):
    text, kb = _menu_view(uid, name, acting)
    await msg.reply_text(text, reply_markup=kb)


async def _show(msg, text, kb):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except Exception:
        await msg.reply_text(text, reply_markup=kb)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg and update.effective_user:
        _clear(context)
        await _menu(msg, update.effective_user.id, update.effective_user.full_name, _acting(update.effective_user.id, context))


async def on_text(update, context, text, is_menu_button=False):
    msg = update.effective_message
    if not msg or not update.effective_chat or update.effective_chat.type != "private" or not update.effective_user:
        return False
    uid = update.effective_user.id
    if text == BTN_MUSEUM:
        _clear(context)
        await _menu(msg, uid, update.effective_user.full_name, _acting(uid, context))
        return True
    w = context.user_data.get("_mu_wait")
    if not w:
        return False
    if is_menu_button or text.startswith("/") or time.time() - w[1] > 1800:
        _clear(context)
        return False
    kind = w[0]
    if kind == "rep":
        a = _acting(uid, context)
        ok = bool(a) and len(text) >= 2 and _replace_item(uid, a, w[2], {"type": "text", "fid": "", "mime": "", "cap": text[:400]})
        _clear(context)
        await msg.reply_text("✅ Almashtirildi. Muzeyda 30 soniya ichida yangilanadi." if ok else "⚠️ Almashtirib bo'lmadi (matn juda qisqa yoki eksponat topilmadi).")
        await _menu(msg, uid, update.effective_user.full_name, a)
        return True
    if kind == "add":
        if len(text) < 2:
            await msg.reply_text("Matn juda qisqa.")
            return True
        res = _add_item(uid, {"id": uuid.uuid4().hex[:10], "type": "text", "fid": "", "mime": "",
                              "cap": text[:400], "ts": int(time.time())}, room=_acting(uid, context))
        await _after_add(msg, context, res)
        return True
    if kind == "code":
        _clear(context)
        if not _rate_ok(uid):
            await msg.reply_text("Juda ko'p urinish. 10 daqiqadan keyin qayta urinib ko'ring.")
            return True
        n, err = _login(uid, text)
        if err == "bad":
            _rate_fail(uid)
            await msg.reply_text("❌ Kod noto'g'ri. «🏛 3D Muzey» → «🔑 Kod bilan kirish» orqali qayta urinib ko'ring.")
        elif err == "has":
            await msg.reply_text(f"Siz allaqachon №{n} xonaga bog'langansiz.")
        else:
            nm = _load()["people"][str(n)]["name"]
            await msg.reply_text(f"✅ Xush kelibsiz, {nm}! Xona №{n} sizniki.")
        await _menu(msg, uid, update.effective_user.full_name, _acting(uid, context))
        return True
    if kind == "title":
        _edit(uid, "title", text[:40], room=_acting(uid, context))
        _clear(context)
        await msg.reply_text("✅ Xona nomi yangilandi. Muzeyda «🔄» tugmasini bosing.")
        await _menu(msg, uid, update.effective_user.full_name, _acting(uid, context))
        return True
    if kind == "name":
        _edit(uid, "name", text[:40], room=_acting(uid, context))
        _clear(context)
        await msg.reply_text("✅ Ismingiz yangilandi.")
        await _menu(msg, uid, update.effective_user.full_name, _acting(uid, context))
        return True
    if kind == "cap":
        _edit(uid, "cap", text[:400], w[2], room=_acting(uid, context))
        _clear(context)
        await msg.reply_text("✅ Izoh yangilandi.")
        await _menu(msg, uid, update.effective_user.full_name, _acting(uid, context))
        return True
    return False


async def _after_add(msg, context, res):
    if res == "noroom":
        _clear(context)
        await msg.reply_text("Avval xona oling: «🏛 3D Muzey» → «Xona olish».")
        return
    if res == "full":
        _clear(context)
        await msg.reply_text(f"⚠️ Xonangiz to'ldi ({MAX_ITEMS}/{MAX_ITEMS}).")
        return
    context.user_data["_mu_wait"] = ("add", time.time())
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tayyor", callback_data="mu:done")]])
    await msg.reply_text(f"✅ Qo'shildi ({res}/{MAX_ITEMS}). Yana rasm, video yoki matn yuborishingiz mumkin.", reply_markup=kb)


async def on_media(update, context):
    msg = update.effective_message
    if not msg or not update.effective_chat or update.effective_chat.type != "private" or not update.effective_user:
        return False
    w = context.user_data.get("_mu_wait")
    if not w or w[0] not in ("add", "rep") or time.time() - w[1] > 1800:
        return False
    uid = update.effective_user.id
    cap = (msg.caption or "").strip()[:200]
    fid, mime, kind, size = None, "", None, 0
    if msg.photo:
        p = msg.photo[-1]
        fid, mime, kind, size = p.file_id, "image/jpeg", "image", p.file_size or 0
    elif msg.video:
        v = msg.video
        fid, mime, kind, size = v.file_id, v.mime_type or "video/mp4", "video", v.file_size or 0
    elif msg.document:
        dc = msg.document
        m = (dc.mime_type or "").lower()
        if m.startswith("image/"):
            fid, mime, kind, size = dc.file_id, m, "image", dc.file_size or 0
        elif m.startswith("video/"):
            fid, mime, kind, size = dc.file_id, m, "video", dc.file_size or 0
    if not fid:
        await msg.reply_text("Faqat rasm yoki video qabul qilinadi (yoki oddiy matn).")
        return True
    if size and size > MAX_MEDIA_BYTES:
        await msg.reply_text("⚠️ Fayl 20 MB dan katta. Telegram boti 20 MB gacha fayl ola oladi — kichikroq yuboring.")
        return True
    if w[0] == "rep":
        a = _acting(uid, context)
        data = {"type": kind, "fid": fid, "mime": mime}
        if cap:
            data["cap"] = cap
        ok = bool(a) and _replace_item(uid, a, w[2], data)
        _clear(context)
        await msg.reply_text("✅ Almashtirildi. Muzeyda 30 soniya ichida yangilanadi." if ok else "⚠️ Almashtirib bo'lmadi.")
        await _menu(msg, uid, update.effective_user.full_name, a)
        return True
    res = _add_item(uid, {"id": uuid.uuid4().hex[:10], "type": kind, "fid": fid, "mime": mime,
                          "cap": cap, "ts": int(time.time())}, room=_acting(uid, context))
    await _after_add(msg, context, res)
    return True


async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.message or q.message.chat.type != "private":
        return
    uid = q.from_user.id
    name = q.from_user.full_name
    parts = (q.data or "").split(":")
    act = parts[1] if len(parts) > 1 else ""
    msg = q.message
    if act in ("code", "claim"):
        context.user_data["_mu_wait"] = ("code", time.time())
        await q.answer()
        await msg.reply_text("🔑 Sizga berilgan kodni yuboring (masalan: SAB-48271):")
        return
    if act in ("codes", "status"):
        if not _is_owner(uid):
            await q.answer("Bu faqat egasi uchun.", show_alert=True)
            return
        await q.answer()
        if act == "codes":
            await msg.reply_text(_codes_text())
        else:
            st = await asyncio.to_thread(_db_status)
            await msg.reply_text("📡 Muzey holati\n" + _status_line(st))
        return
    if act in ("oroom", "os", "oself", "odel", "od", "orep", "or"):
        if not _is_owner(uid):
            await q.answer("Bu faqat egasi uchun.", show_alert=True)
            return
        d = _load()
        if act == "oroom":
            rows, row = [], []
            for i in range(1, ROOMS + 1):
                nm = (d["rooms"].get(str(i)) or {}).get("name", "")
                row.append(InlineKeyboardButton(f"№{i} {nm}"[:20], callback_data=f"mu:os:{i}"))
                if len(row) == 2:
                    rows.append(row)
                    row = []
            if row:
                rows.append(row)
            rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="mu:menu")])
            await q.answer()
            await _show(msg, "🛠 Qaysi xonani boshqarasiz?", InlineKeyboardMarkup(rows))
            return
        if act == "os":
            if len(parts) > 2 and parts[2].isdigit() and 1 <= int(parts[2]) <= ROOMS:
                context.user_data["_mu_as"] = int(parts[2])
                _clear(context)
                await q.answer("Xona tanlandi")
                text, kb = _menu_view(uid, name, int(parts[2]))
                await _show(msg, text, kb)
            else:
                await q.answer()
            return
        if act == "oself":
            context.user_data.pop("_mu_as", None)
            _clear(context)
            await q.answer()
            text, kb = _menu_view(uid, name, None)
            await _show(msg, text, kb)
            return
        a = _acting(uid, context)
        if not a:
            await q.answer("Avval xonani tanlang.", show_alert=True)
            return
        rm = d["rooms"].get(str(a)) or {}
        icon = {"image": "🖼", "video": "🎬", "text": "📝"}
        if act in ("odel", "orep"):
            rows = []
            for i, it in enumerate(rm.get("items", []), 1):
                label = f"{i}. {icon.get(it.get('type'), '•')} {(it.get('cap') or '(izohsiz)')[:26]}"
                rows.append([InlineKeyboardButton(label, callback_data=f"mu:{'od' if act == 'odel' else 'or'}:{it['id']}")])
            rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="mu:menu")])
            await q.answer()
            if not rm.get("items"):
                await msg.reply_text("Bu xonada hali eksponat yo'q.")
                return
            await _show(msg, ("🗑 Qaysi eksponatni o'chirasiz?" if act == "odel" else "🔁 Qaysi eksponatni almashtirasiz?"),
                        InlineKeyboardMarkup(rows))
            return
        if act == "od" and len(parts) > 2:
            ok = _del_item(uid, a, parts[2])
            await q.answer("🗑 O'chirildi" if ok else "Topilmadi")
            text, kb = _menu_view(uid, name, a)
            await _show(msg, text, kb)
            return
        if act == "or" and len(parts) > 2:
            context.user_data["_mu_wait"] = ("rep", time.time(), parts[2])
            await q.answer()
            await msg.reply_text("🔁 Yangi rasm, video (20 MB gacha) yoki matn yuboring — tanlangan eksponat shu bilan almashtiriladi:")
            return
        await q.answer()
        return
    n, room = _room_for(uid, context)
    if act in ("add", "caps", "title", "name", "theme", "ce", "th") and not room:
        await q.answer("Avval xona oling.", show_alert=True)
        return
    if act == "add":
        context.user_data["_mu_wait"] = ("add", time.time())
        await q.answer()
        await msg.reply_text(
            f"➕ Rasm, video (20 MB gacha) yoki matn yuboring. Rasm/video uchun izohni sarlavha (caption) qilib yozing.\n"
            f"Joy: {len(room['items'])}/{MAX_ITEMS}. Tugagach «Tayyor» ni bosing.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tayyor", callback_data="mu:done")]]))
    elif act == "done":
        _clear(context)
        await q.answer("Tayyor")
        text, kb = _menu_view(uid, name, _acting(uid, context))
        await _show(msg, text, kb)
    elif act == "menu":
        _clear(context)
        await q.answer()
        text, kb = _menu_view(uid, name, _acting(uid, context))
        await _show(msg, text, kb)
    elif act == "caps":
        await q.answer()
        if not room["items"]:
            await msg.reply_text("Hali eksponat yo'q.")
            return
        icon = {"image": "🖼", "video": "🎬", "text": "📝"}
        rows = []
        for i, it in enumerate(room["items"], 1):
            label = f"{i}. {icon.get(it['type'], '•')} {(it.get('cap') or '(izohsiz)')[:30]}"
            rows.append([InlineKeyboardButton(label, callback_data=f"mu:ce:{it['id']}")])
        rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="mu:menu")])
        await _show(msg, "Qaysi eksponat izohini o'zgartirmoqchisiz?", InlineKeyboardMarkup(rows))
    elif act == "ce" and len(parts) > 2:
        context.user_data["_mu_wait"] = ("cap", time.time(), parts[2])
        await q.answer()
        await msg.reply_text("Yangi izoh matnini yuboring:")
    elif act == "title":
        context.user_data["_mu_wait"] = ("title", time.time())
        await q.answer()
        await msg.reply_text("Xona uchun yangi nom yozing (masalan: «Mening sayohatlarim»):")
    elif act == "name":
        context.user_data["_mu_wait"] = ("name", time.time())
        await q.answer()
        await msg.reply_text("Eshik tabletkasida ko'rinadigan ismingizni yozing:")
    elif act == "theme":
        await q.answer()
        rows, row = [], []
        for k in THEME_KEYS:
            row.append(InlineKeyboardButton(THEMES[k]["label"], callback_data=f"mu:th:{k}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="mu:menu")])
        await _show(msg, "🎨 Xonangiz uchun mavzuni tanlang:", InlineKeyboardMarkup(rows))
    elif act == "th" and len(parts) > 2 and parts[2] in THEMES:
        _edit(uid, "theme", parts[2], room=_acting(uid, context))
        await q.answer("Mavzu o'zgardi")
        text, kb = _menu_view(uid, name, _acting(uid, context))
        await _show(msg, text, kb)
    else:
        await q.answer()


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not update.effective_user or not _is_owner(update.effective_user.id):
        return
    st = await asyncio.to_thread(_db_status)
    await msg.reply_text("📡 Muzey holati\n" + _status_line(st))


def install(app):
    app.add_handler(CommandHandler(["muzey", "museum"], cmd_menu, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler(["muzey_holat"], cmd_status, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(on_cb, pattern=r"^mu:"))


# ============================================================
# 3D MIJOZ (Three.js)
# ============================================================
MUSEUM_HTML = r'''<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>LOG-324 3D Museum</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;overflow:hidden;background:#0b1020;color:#fff;font:14px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;touch-action:none;user-select:none;-webkit-user-select:none}
#c{position:fixed;inset:0;width:100vw;height:100vh;display:block;touch-action:none}
.hide{display:none!important}
#load{position:fixed;inset:0;z-index:50;background:#0b1020;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;text-align:center;padding:24px}
#load h1{font-size:20px;margin:0;color:#e8c85a;letter-spacing:.5px}
#ltxt{opacity:.85}
.spin{width:38px;height:38px;border:4px solid #334;border-top-color:#e8c85a;border-radius:50%;animation:sp 1s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
#hud{position:fixed;left:0;right:0;top:0;z-index:10;display:flex;justify-content:space-between;align-items:flex-start;padding:calc(env(safe-area-inset-top) + 8px) 10px 0;pointer-events:none}
#hud>*{pointer-events:auto}
.pill{background:rgba(12,16,32,.62);border:1px solid rgba(255,255,255,.18);backdrop-filter:blur(6px);border-radius:14px;padding:7px 11px;font-size:13px}
.btns{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;max-width:62vw}
.b{background:rgba(12,16,32,.7);border:1px solid rgba(255,255,255,.22);color:#fff;border-radius:12px;padding:8px 11px;font:600 13px system-ui;cursor:pointer}
.b:active{background:rgba(60,70,120,.8)}
#stick{position:fixed;left:calc(env(safe-area-inset-left) + 20px);bottom:calc(env(safe-area-inset-bottom) + 26px);width:150px;height:150px;border-radius:50%;background:rgba(255,255,255,.16);border:3px solid rgba(255,255,255,.42);z-index:10;touch-action:none}
#knob{position:absolute;left:50%;top:50%;width:64px;height:64px;margin:-32px 0 0 -32px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#ff9a45,#ee6c10);border:4px solid #fff;box-shadow:0 3px 8px rgba(0,0,0,.35);pointer-events:none}
#hint{position:fixed;left:50%;bottom:calc(env(safe-area-inset-bottom) + 214px);transform:translateX(-50%);z-index:10;background:rgba(12,16,32,.75);border:1px solid rgba(255,255,255,.2);border-radius:14px;padding:8px 14px;font-size:13px;text-align:center;max-width:86vw;pointer-events:none;transition:opacity .6s}
#vw{position:fixed;inset:0;z-index:40;background:rgba(5,8,18,.94);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:14px;gap:10px}
#vwb{max-width:100%;max-height:72vh;display:flex;align-items:center;justify-content:center}
#vwb img,#vwb video{max-width:100%;max-height:72vh;border-radius:10px;background:#000}
#vwb .txt{max-width:560px;max-height:70vh;overflow:auto;background:#f6efdc;color:#221b0e;border-radius:12px;padding:18px;font-size:17px;line-height:1.5;white-space:pre-wrap}
#vwc{max-width:560px;text-align:center;font-size:15px;opacity:.92}
#vwx{position:absolute;right:calc(env(safe-area-inset-right) + 12px);top:calc(env(safe-area-inset-top) + 12px)}
#rm{position:fixed;inset:0;z-index:30;background:rgba(5,8,18,.88);display:flex;align-items:center;justify-content:center;padding:14px}
#rmb{background:#141a30;border:1px solid rgba(255,255,255,.2);border-radius:16px;width:min(520px,100%);max-height:86vh;overflow:auto;padding:12px;touch-action:pan-y}
.rr{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px;border-radius:10px;cursor:pointer}
.rr:active{background:#26305a}.rr.mine{border:1px solid #e8c85a}.rr.empty{opacity:.5}
.rr b{color:#e8c85a}
#act{position:fixed;right:calc(env(safe-area-inset-right) + 22px);bottom:calc(env(safe-area-inset-bottom) + 34px);width:124px;height:124px;border-radius:50%;background:rgba(170,180,195,.8);border:3px solid rgba(255,255,255,.6);color:#fff;font:800 20px system-ui;letter-spacing:1px;z-index:10;box-shadow:0 8px 0 rgba(90,100,120,.75);touch-action:none;cursor:pointer}
#act.ready{background:#ee6c10;box-shadow:0 8px 0 #a84608}
#act:active{transform:translateY(5px);box-shadow:0 3px 0 rgba(90,100,120,.75)}
#spd{position:fixed;right:calc(env(safe-area-inset-right) + 16px);bottom:calc(env(safe-area-inset-bottom) + 178px);display:flex;gap:6px;z-index:10;background:rgba(255,255,255,.88);border-radius:12px;padding:6px}
#spd button{border:0;border-radius:9px;background:#e9edf2;color:#222;font:800 14px system-ui;padding:8px 11px;cursor:pointer}
#spd button.on{background:#ffc928}
#navp{position:fixed;left:10px;top:calc(env(safe-area-inset-top) + 50px);z-index:10;background:rgba(238,108,16,.92);border-radius:14px;padding:6px 11px;font:700 13px system-ui;pointer-events:auto;cursor:pointer}
#ctx{position:fixed;right:calc(env(safe-area-inset-right) + 16px);bottom:calc(env(safe-area-inset-bottom) + 236px);z-index:11;background:#2f8f4a;border:2px solid #fff;border-radius:16px;padding:13px 16px;color:#fff;font:800 15px system-ui;box-shadow:0 6px 0 #1f6234;cursor:pointer}
#ctx:active{transform:translateY(4px);box-shadow:0 2px 0 #1f6234}
#toast{position:fixed;left:50%;top:calc(env(safe-area-inset-top) + 92px);transform:translateX(-50%);z-index:60;background:rgba(12,16,32,.94);border:1px solid #e8c85a;border-radius:14px;padding:9px 14px;max-width:88vw;text-align:center;pointer-events:none}
.ov{position:fixed;inset:0;z-index:45;background:rgba(5,8,18,.86);display:flex;align-items:center;justify-content:center;padding:14px;touch-action:pan-y}
.card{background:#141a30;border:1px solid rgba(255,255,255,.2);border-radius:16px;width:min(460px,100%);max-height:92vh;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.card.wide{width:min(580px,100%)}
.card h2{margin:0;color:#e8c85a;font-size:19px}
.card p{margin:0;opacity:.88}
.card input:not([type=checkbox]),.card select{background:#0d1226;border:1px solid rgba(255,255,255,.28);color:#fff;border-radius:10px;padding:10px;font:16px system-ui;user-select:text;-webkit-user-select:text;touch-action:auto;width:100%}
.row{display:flex;gap:8px;flex-wrap:wrap}
.err{color:#ff9a9a;min-height:18px}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:8px}
.st{font-size:12.5px;opacity:.92;background:#0d1226;border-radius:10px;padding:8px}
.ar{border:1px solid rgba(255,255,255,.15);border-radius:12px;padding:8px;display:flex;flex-direction:column;gap:6px}
.ah{display:flex;gap:6px;align-items:center}.ah b{color:#e8c85a;min-width:34px}
.ab{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.ab select{width:auto}
.hj{display:flex;gap:4px;align-items:center;font-size:13px}
.ac{background:#0d1226;border:1px dashed #e8c85a;border-radius:8px;padding:6px 8px;color:#ffe58a;font:700 15px ui-monospace,Menlo,monospace;letter-spacing:1px}
.sm{padding:6px 9px;font-size:12px}
.as{font-size:12px;opacity:.9;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#maplist{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;max-height:65vh;overflow:auto}#maplist button{padding:13px;border:1px solid #b99a4a;border-radius:12px;background:#17243e;color:#fff;text-align:left;font-weight:700}#vw #vwb img{max-width:96vw;max-height:82vh;object-fit:contain}#vw #vwb video{max-width:96vw;max-height:82vh}
</style></head><body>
<canvas id="c"></canvas>
<div id="load"><h1>🏛 LOG-324 3D MUZEY</h1><div class="spin"></div><div id="ltxt">Yuklanmoqda...</div></div>
<div id="hud" class="hide">
  <div class="pill" id="fl">Qavat 1</div>
  <div class="btns"><button class="b" id="bMap">🗺 Xarita</button><button class="b hide" id="bOwner">👑 Egasi</button><button class="b hide" id="bRooms">🚪</button><button class="b hide" id="bMine">⭐</button><button class="b hide" id="bHall">🏠</button><button class="b hide" id="bLift">🛗</button><button class="b hide" id="bPhoto">📸</button><button class="b hide" id="bMusic">🎵 Musiqa</button><button class="b hide" id="bLogin">🔑</button><button class="b hide" id="bNav">🧭</button><button class="b hide" id="bRef">🔄</button></div>
</div>
<div id="stick" class="hide"><div id="knob"></div></div>
<button id="act" class="hide">AMAL</button>
<button id="ctx" class="hide"></button>
<div id="spd" class="hide"><button data-s="1" class="on">1×</button><button data-s="1.6">2×</button><button data-s="2.3">3×</button></div>
<div id="navp" class="pill hide"></div>
<div id="toast" class="hide"></div>
<div id="lk" class="ov hide" style="z-index:47"><div class="card">
 <h2 id="lkt">🔒 Eshik kodi</h2><p id="lkp"></p>
 <input id="lki" maxlength="16" placeholder="Kod" autocomplete="off" autocorrect="off" spellcheck="false" autocapitalize="off">
 <div id="lke" class="err"></div>
 <div class="row"><button class="b" id="lkok">OK</button><button class="b hide" id="lkdel">🗑 Kodni o'chirish</button><button class="b" id="lkx">Bekor</button></div>
</div></div>
<div id="lg" class="ov hide"><div class="card">
 <h2>🔑 Kirish</h2>
 <p>🔒 Muzey maxfiy. Kirish uchun sizga berilgan shaxsiy kodni kiriting. To'g'ri kodsiz zal, xonalar va eksponatlar ochilmaydi.</p>
 <input id="lgi" maxlength="24" placeholder="Masalan: SAB-48271" autocapitalize="characters" autocomplete="off" autocorrect="off" spellcheck="false">
 <div id="lge" class="err"></div>
 <div class="row"><button class="b" id="lgok">🔑 Kodni tekshirish va kirish</button></div>
</div></div>
<div id="nq" class="ov hide" style="z-index:46"><div class="card">
 <h2>👋 Xush kelibsiz!</h2><p id="nqt"></p>
 <div class="row"><button class="b" id="nqy">🧭 Ha, ko'rsatilsin</button><button class="b" id="nqn">Yo'q, o'zim topaman</button></div>
</div></div>
<div id="ad" class="ov hide"><div class="card wide">
 <div class="hdr"><b style="font-size:17px;color:#e8c85a">👑 Egasi paneli</b><button class="b" id="adx">✕ Yopish</button></div>
 <div id="adst" class="st">💾 Baza tekshirilmoqda...</div>
 <div class="row"><button class="b" id="adsend">📤 Kodlarni botga yuborish</button><button class="b" id="adref">🔄 Yangilash</button></div>
 <div id="adl"></div>
</div></div>
<div id="hint" class="hide">Chap tomonda — yurish · ekranni suring — qarash · «AMAL» — yaqindagi rasmni ochish · «🗺 Xarita» — xonani tanlang, strelka yo\'l ko\'rsatadi</div>
<div id="rm" class="hide"><div id="rmb"></div></div>
<div id="mapov" class="ov hide"><div class="card wide"><div class="hdr"><b>🗺 Qayerga borasiz? Tanlang — strelka yo'l ko'rsatadi</b><button class="b" id="mapx">✕</button></div><div id="maplist"></div></div></div>
<div id="vw" class="hide"><button class="b" id="vwx">✕ Yopish</button><div id="vwb"></div><div id="vwc"></div><button class="b" id="vwput" style="display:none;padding:13px 20px;font-size:16px;background:#2f8f4a;border-color:#fff">🖼 Rasm qo'yish</button><input type="file" id="putf" accept="image/*" style="position:fixed;left:-200px;top:0;opacity:0;width:1px;height:1px"></div>
<script type="module">
import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
const $=id=>document.getElementById(id);
const tg=window.Telegram&&window.Telegram.WebApp;
try{tg.ready();tg.expand();if(tg.disableVerticalSwipes)tg.disableVerticalSwipes();}catch(e){}
const say=t=>{$('ltxt').textContent=t};
const FH=6,HT=5.6,WT=0.4;

const renderer=new THREE.WebGLRenderer({canvas:$('c'),antialias:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
renderer.setSize(innerWidth,innerHeight,false);
const scene=new THREE.Scene();
scene.background=new THREE.Color(0xbfe0ff);
scene.fog=new THREE.Fog(0xbfe0ff,80,200);
const camera=new THREE.PerspectiveCamera(62,innerWidth/innerHeight,0.1,320);
scene.add(new THREE.HemisphereLight(0xffffff,0x8a8070,1.0));
scene.add(new THREE.AmbientLight(0xffffff,0.55));
const sun=new THREE.DirectionalLight(0xfff2d8,0.9);sun.position.set(30,60,20);scene.add(sun);
addEventListener('resize',()=>{renderer.setSize(innerWidth,innerHeight,false);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();});

// ---------- yordamchilar ----------
function wrap(ctx,text,maxW){const words=String(text).split(/\s+/);const lines=[];let cur='';for(const w of words){const t=cur?cur+' '+w:w;if(ctx.measureText(t).width>maxW&&cur){lines.push(cur);cur=w;}else cur=t;}if(cur)lines.push(cur);return lines;}
function canvasTex(w,h,draw){const c=document.createElement('canvas');c.width=w;c.height=h;draw(c.getContext('2d'),w,h);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=4;return t;}
function planeMesh(tex,w,h){return new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:tex}));}
function lerpAngle(a,b,t){const d=((b-a+Math.PI)%(Math.PI*2)+Math.PI*2)%(Math.PI*2)-Math.PI;return a+d*t;}
function disposeObj(o){o.traverse(n=>{if(n.geometry)n.geometry.dispose();if(n.material){const ms=Array.isArray(n.material)?n.material:[n.material];ms.forEach(m=>{if(m.map)m.map.dispose();m.dispose();});}});}
const marble=canvasTex(256,256,(c,w,h)=>{for(let i=0;i<8;i++)for(let j=0;j<8;j++){c.fillStyle=(i+j)%2?'#d9d2c2':'#efe9da';c.fillRect(i*32,j*32,32,32);}c.strokeStyle='rgba(120,110,90,.25)';c.lineWidth=1;for(let k=0;k<=8;k++){c.beginPath();c.moveTo(k*32,0);c.lineTo(k*32,256);c.stroke();c.beginPath();c.moveTo(0,k*32);c.lineTo(256,k*32);c.stroke();}});
marble.wrapS=marble.wrapT=THREE.RepeatWrapping;marble.repeat.set(7.5,7.5);

// ---------- avatar ----------
const avatar=new THREE.Group();
const lm=c=>new THREE.MeshLambertMaterial({color:c});
function buildAvatar(pr){
 const fem=!!pr&&pr.g==='f',hj=fem&&!!pr.h;
 while(avatar.children.length){const o=avatar.children[0];avatar.remove(o);disposeObj(o);}
 const skin=0xf1c9a0,dark=0x2a1a10;
 const top=fem?(hj?0x7a5fc0:0xd9578a):0x2e6fd6;
 const M=(g,c,x,y,z)=>{const m=new THREE.Mesh(g,lm(c));m.position.set(x,y,z);avatar.add(m);return m;};
 M(new THREE.CylinderGeometry(0.19,0.22,0.62,12),top,0,1.08,0);
 M(new THREE.SphereGeometry(0.17,14,12),skin,0,1.55,0);
 for(const sx of [-1,1])M(new THREE.SphereGeometry(0.022,6,6),0x1a1a1a,sx*0.06,1.57,0.155);
 if(hj){
  // Hijob: bosh va sochni yopadi, old tomoni ochiq — yuz niqob bilan berkitilmaydi.
  const hood=M(new THREE.SphereGeometry(0.205,20,16),top,0,1.585,-0.055);
  hood.scale.set(1.12,1.13,1.02);
  // Mato faqat boshning orqa-yoni bo'ylab yelkaga tushadi.
  const drape=new THREE.Mesh(
   new THREE.CylinderGeometry(0.19,0.34,0.82,20,1,false,Math.PI/2,Math.PI),lm(top)
  );
  drape.position.set(0,1.25,-0.085);avatar.add(drape);
  const shoulder=M(new THREE.SphereGeometry(0.25,16,12),top,0,1.08,-0.09);
  shoulder.scale.set(1.15,0.78,0.72);
 }else{
  M(new THREE.SphereGeometry(0.178,14,12,0,Math.PI*2,0,Math.PI/2),dark,0,1.57,0);
  if(fem){M(new THREE.BoxGeometry(0.3,0.5,0.09),dark,0,1.38,-0.13);M(new THREE.SphereGeometry(0.06,8,8),0xff6fa5,0.14,1.62,-0.1);}
 }
 avatar.userData.skirt=null;
 if(fem)avatar.userData.skirt=M(new THREE.CylinderGeometry(0.2,hj?0.36:0.4,hj?1.0:0.62,18),hj?0x5a43a0:0xb03a6a,0,hj?0.62:0.8,0);
 avatar.userData.legs=[];avatar.userData.arms=[];
 for(const sx of [-1,1]){
  const leg=new THREE.Group();leg.position.set(sx*0.11,0.68,0);
  const lg=new THREE.Mesh(new THREE.BoxGeometry(0.15,0.68,0.17),lm(fem?(hj?0x5a43a0:0xe0b48c):0x23304a));lg.position.y=-0.34;leg.add(lg);avatar.add(leg);avatar.userData.legs.push(leg);
  const arm=new THREE.Group();arm.position.set(sx*0.29,1.3,0);
  const am=new THREE.Mesh(new THREE.BoxGeometry(0.11,0.5,0.12),lm(top));am.position.y=-0.24;arm.add(am);
  const hd=new THREE.Mesh(new THREE.SphereGeometry(0.06,8,8),lm(skin));hd.position.y=-0.52;arm.add(hd);
  avatar.add(arm);avatar.userData.arms.push(arm);
 }
}
buildAvatar({g:'m'});
scene.add(avatar);

// ---------- holat ----------
const P={x:0,y:-1.2,z:30,rot:Math.PI,yaw:0,pitch:0.24,dist:7.2,walk:0,vx:0,vz:0,dy:-1.2,spin:0,snap:true};
let world=null,colliders=[],clickables=[],lazy=[],roomPos={},DATA=null,lintels=[],doors=[],navPos={},liftCab=null,colGrid=new Map(),monitors=[];
function col(x0,z0,x1,z1,tag=-1){colliders.push([x0,z0,x1,z1,tag]);}
const CG=8;
function indexColliders(){
 colGrid=new Map();
 for(const c of colliders){
  const x0=Math.floor((c[0]-1)/CG),x1=Math.floor((c[2]+1)/CG),z0=Math.floor((c[1]-1)/CG),z1=Math.floor((c[3]+1)/CG);
  for(let i=x0;i<=x1;i++)for(let j=z0;j<=z1;j++){const k=(i+64)*256+(j+64);let a=colGrid.get(k);if(!a){a=[];colGrid.set(k,a);}a.push(c);}
 }
}
function hit(x,z,fl,R){
 const a=colGrid.get((Math.floor(x/CG)+64)*256+(Math.floor(z/CG)+64));if(!a)return false;
 for(const c of a){if(c[4]>=0&&c[4]!==fl)continue;if(x>c[0]-R&&x<c[2]+R&&z>c[1]-R&&z<c[3]+R)return true;}
 return false;
}
// shift balandligi (kamera shiftdan tepaga chiqib ketmasligi uchun) va lintellar
function ceilAt(x,z,lv){
 const ax=Math.abs(x),az=Math.abs(z);
 if(ax<11&&az<11)return 11.3;
 if(ax<15&&az<15)return lv+5.3;
 if(ax<=39.4&&az<=19.4)return lv+5.3;
 if(x>=39&&x<=109.2&&z>=-8.2&&z<=14.2)return lv+5.3;
 if(lv<1&&ax<=8.3&&z>=15&&z<=19.3)return 5.3;
 return 1e9;
}
function camHit(x,y,z,fl){
 if(hit(x,z,fl,0.3))return true;
 for(const l of lintels){if(x>l[0]-0.3&&x<l[2]+0.3&&z>l[1]-0.3&&z<l[3]+0.3&&y>l[4]-0.25&&y<l[4]+2.65)return true;}
 return false;
}
const ST=24,TW=12.8/ST,RS=0.25;   // markaziy zinapoya: 24 pog'ona, har biri 0.25 m
function heights(x,z){
 const o=[],ax=Math.abs(x),az=Math.abs(z);
 const inFront=x>-6&&x<6&&z>17&&z<23;   // kirish zinapoyasi (pastga tushadi)
 let skipGround=false;
 // markaziy zinapoya: A marsh (shimol) x bo'ylab ko'tariladi, B marsh (janub) teskari
 if(x>-6.4&&x<6.4){
  if(z>-10.95&&z<-7.8){const i=Math.min(ST-1,Math.max(0,Math.floor((x+6.4)/TW)));const h=(i+1)*RS;o.push(h);if(h>0.6)skipGround=true;}
  if(z>7.8&&z<10.95){const i=Math.min(ST-1,Math.max(0,Math.floor((6.4-x)/TW)));const h=(i+1)*RS;o.push(h);if(h>0.6)skipGround=true;}
 }
 if(inFront)o.push(-1.2*(z-17)/6);
 else if(ax<110&&az<75)o.push(-1.2);
 // 1-qavat: faqat haqiqiy pol bor joylarda (podium: zal + qanotlar)
 if(!inFront&&!skipGround&&((ax<=41&&az<=17)||(ax>=15&&ax<=39.4&&az<=19.4)))o.push(0);
 // maxsus qanot: bog'lovchi zal + yo'lak + katta xonalar (ikkala qavat)
 if(x>=39&&x<=109&&z>=-8&&z<=14){o.push(0);o.push(6);}
 // 2-qavat: zal halqasi, qanotlar, zinapoya maydonchalari
 if(ax<15&&az<15&&!(ax<11&&az<11))o.push(6);
 if(ax>=15&&ax<=39.4&&az<=19.4)o.push(6);
 if(x>=6&&x<11&&z>=-11&&z<-7.8)o.push(6);
 if(x>-11&&x<=-6&&z>7.8&&z<=11)o.push(6);
 // foto zona platformasi
 const pd=Math.hypot(x+55,z-35);
 if(pd<4.8)o.push(-0.9);else if(pd<5.2)o.push(-1.02);
 return o;
}
function surfaceY(x,z,y){let best=null;for(const h of heights(x,z)){if(h>y+0.55||h<y-0.55)continue;if(best===null||h>best)best=h;}return best;}
function tryMove(nx,nz){const fl=P.y>2.8?1:0;if(hit(nx,nz,fl,0.32))return false;const h=surfaceY(nx,nz,P.y);if(h===null)return false;P.x=nx;P.z=nz;P.y=h;return true;}

// ---------- DUNYONI QURISH ----------
function buildWorld(data){
 if(world){disposeObj(world);scene.remove(world);}
 world=new THREE.Group();scene.add(world);
 colliders=[];clickables=[];lazy=[];roomPos={};lintels=[];doors=[];navPos={};liftCab=null;monitors=[];
 const G=[],LG=[];
 const THEMES=data.themes||{};
 const byN={};(data.rooms||[]).forEach(r=>byN[r.n]=r);
 const GAL=buildGallery(data);
 const hx=h=>typeof h==='string'?parseInt(h,16):h;
 function pushGeo(g,hex,list){g=g.index?g.toNonIndexed():g;const c=new THREE.Color(hx(hex));const n=g.attributes.position.count;const a=new Float32Array(n*3);for(let i=0;i<n;i++){a[i*3]=c.r;a[i*3+1]=c.g;a[i*3+2]=c.b;}g.setAttribute('color',new THREE.BufferAttribute(a,3));(list||G).push(g);}
 function box(x0,y0,z0,x1,y1,z1,hex,list){const w=x1-x0,h=y1-y0,d=z1-z0;if(w<=0||h<=0||d<=0)return;const g=new THREE.BoxGeometry(w,h,d);g.translate(x0+w/2,y0+h/2,z0+d/2);pushGeo(g,hex,list);}
 function cyl(x,y0,z,rt,rb,h,hex,seg){const g=new THREE.CylinderGeometry(rt,rb,h,seg||16);g.translate(x,y0+h/2,z);pushGeo(g,hex);}
 const S=0xe9dfc8;
 function addDoor(g,cx,cz,y,r1,R,rn){g.rotation.y=0;const d={g,cx,cz,y,r1,R,a:0,rn:rn||0,lk:false};doors.push(d);return d;}

 function wallZ(f,z,xa,xb,gaps,hex){
  const y0=f*FH,lo=Math.min(xa,xb),hi=Math.max(xa,xb);let cur=lo-WT/2;
  const gs=(gaps||[]).slice().sort((p,q)=>p[0]-q[0]);
  const seg=(a,b)=>{if(b-a<=0.001)return;box(a,y0,z-WT/2,b,y0+HT,z+WT/2,hex);if(f===0)col(a,z-WT/2,b,z+WT/2);};
  for(const g of gs){seg(cur,g[0]);cur=g[1];box(g[0],y0+3.2,z-WT/2,g[1],y0+HT,z+WT/2,hex);lintels.push([g[0],z-WT/2,g[1],z+WT/2,y0+3.2]);}
  seg(cur,hi+WT/2);
 }
 function wallX(f,x,za,zb,gaps,hex){
  const y0=f*FH,lo=Math.min(za,zb),hi=Math.max(za,zb);let cur=lo;
  const gs=(gaps||[]).slice().sort((p,q)=>p[0]-q[0]);
  const seg=(a,b)=>{if(b-a<=0.001)return;box(x-WT/2,y0,a,x+WT/2,y0+HT,b,hex);if(f===0)col(x-WT/2,a,x+WT/2,b);};
  for(const g of gs){seg(cur,g[0]);cur=g[1];box(x-WT/2,y0+3.2,g[0],x+WT/2,y0+HT,g[1],hex);lintels.push([x-WT/2,g[0],x+WT/2,g[1],y0+3.2]);}
  seg(cur,hi);
 }

 // --- zamin, podium, zinapoya ---
 const gnd=new THREE.Mesh(new THREE.PlaneGeometry(400,400),new THREE.MeshLambertMaterial({color:0x4f8f3c}));gnd.rotation.x=-Math.PI/2;gnd.position.y=-1.25;world.add(gnd);
 box(-41,-1.2,-17,41,0,17,0xd8cfba);box(15,-1.2,17,41,0,19.6,0xd8cfba);box(-41,-1.2,17,-15,0,19.6,0xd8cfba);box(15,-1.2,-19.6,41,0,-17,0xd8cfba);box(-41,-1.2,-19.6,-15,0,-17,0xd8cfba);box(39,-1.2,-8.2,109.2,0,14.2,0xd8cfba);
 box(-8,-1.25,23,8,-1.2,90,0xb9b2a0);
 for(let i=0;i<6;i++)box(-6,-1.2,17+i,6,-0.2*(i+0.5),18+i,0xcdbf9f);
 // portiko
 box(-8.3,5.6,15,8.3,6.0,19.3,0xd6c9a8);
 for(const px of [-7.5,-4.8,4.8,7.5]){cyl(px,-1.2,18,0.42,0.46,6.8,0xf1e9d6,18);col(px-0.46,17.54,px+0.46,18.46);}

 // --- zal (markaziy) ---
 for(let f=0;f<2;f++){
  wallX(f,-15,-15,15,[[-3,3]],S);wallX(f,15,-15,15,[[-3,3]],S);
  wallZ(f,-15,-15,15,[],S);wallZ(f,15,-15,15,[[-3,3]],S);
 }
 // 2-qavat halqasi va zinapoya
 box(-15,5.6,-15,15,6,-11,0xcdbf9f);box(-15,5.6,11,15,6,15,0xcdbf9f);box(-15,5.6,-11,-11,6,11,0xcdbf9f);box(11,5.6,-11,15,6,11,0xcdbf9f);
 box(6,5.6,-11,11,6,-7.8,0xcdbf9f);box(-11,5.6,7.8,-6,6,11,0xcdbf9f);
 box(-15,6,-15,15,6.03,-11,0xe9e1cd);box(-15,6,11,15,6.03,15,0xe9e1cd);box(-15,6,-11,-11,6.03,11,0xe9e1cd);box(11,6,-11,15,6.03,11,0xe9e1cd);
 box(6,6,-11,11,6.03,-7.8,0xe9e1cd);box(-11,6,7.8,-6,6.03,11,0xe9e1cd);
 // zinapoya: ko'rinadigan pog'onalar yurish balandligi bilan 1:1 mos
 for(let i=0;i<ST;i++){
  const top=(i+1)*RS,c=i%2?0xd8c9a6:0xcdbf9f;
  box(-6.4+i*TW,0,-11,-6.4+(i+1)*TW,top,-7.8,c);
  box(6.4-(i+1)*TW,0,7.8,6.4-i*TW,top,11,c);
 }
 // panjara
 function rail(xa,za,xb,zb){
  const lo=(a,b)=>Math.min(a,b),hi=(a,b)=>Math.max(a,b);
  const t=0.05;
  box(lo(xa,xb)-t,6.85,lo(za,zb)-t,hi(xa,xb)+t,6.95,hi(za,zb)+t,0xb99a4a);
  box(lo(xa,xb)-t,6.4,lo(za,zb)-t,hi(xa,xb)+t,6.46,hi(za,zb)+t,0xb99a4a);
  const len=Math.hypot(xb-xa,zb-za),n=Math.max(1,Math.round(len/1.6));
  for(let i=0;i<=n;i++){const px=xa+(xb-xa)*i/n,pz=za+(zb-za)*i/n;box(px-0.05,6.03,pz-0.05,px+0.05,6.95,pz+0.05,0xb99a4a);}
 }
 rail(-11,-11,6,-11);rail(11,-7.8,11,11);rail(-6,11,11,11);rail(-11,-11,-11,7.8);rail(6,-7.8,11,-7.8);rail(-11,7.8,-6,7.8);
 // ustunlar
 for(const [px,pz] of [[13,13],[-13,13],[13,-13],[-13,-13],[13,7],[13,-7],[-13,7],[-13,-7],[7,13],[-7,13],[7,-13],[-7,-13]]){cyl(px,0,pz,0.4,0.45,11.6,0xf3ead6,18);col(px-0.45,pz-0.45,px+0.45,pz+0.45);}
 // favvora
 cyl(0,0,0,2.7,2.7,0.6,0xcfc5ad,32);cyl(0,0.45,0,2.4,2.4,0.2,0x4aa3d8,32);cyl(0,0,0,0.35,0.45,2.4,0xe9e1cd,16);cyl(0,2.0,0,1.1,0.5,0.3,0xcfc5ad,24);cyl(0,2.28,0,0.9,0.9,0.05,0x4aa3d8,24);
 col(-2.7,-2.7,2.7,2.7);
 // gilam
 box(-2.8,0.01,2.5,2.8,0.05,15,0x8a1c2b);box(-2.8,0.01,-15,2.8,0.05,-2.5,0x8a1c2b);
 // tom
 box(15,11.6,-11.2,39.2,12,11.2,0x5b6070);box(-39.2,11.6,-11.2,-15,12,11.2,0x5b6070);
 box(15,11.6,-19.2,39.2,12,-11,0x5b6070);box(15,11.6,11,39.2,12,19.2,0x5b6070);box(-39.2,11.6,-19.2,-15,12,-11,0x5b6070);box(-39.2,11.6,11,-15,12,19.2,0x5b6070);
 {
  const sh=new THREE.Shape();sh.moveTo(-15.2,-15.2);sh.lineTo(15.2,-15.2);sh.lineTo(15.2,15.2);sh.lineTo(-15.2,15.2);sh.lineTo(-15.2,-15.2);
  const hole=new THREE.Path();hole.absarc(0,0,14.2,0,Math.PI*2,true);sh.holes.push(hole);
  const rg=new THREE.ExtrudeGeometry(sh,{depth:0.4,bevelEnabled:false,curveSegments:32});rg.rotateX(-Math.PI/2);rg.translate(0,11.6,0);pushGeo(rg,0x5b6070);
 }
 // marmar pol
 const hall=new THREE.Mesh(new THREE.PlaneGeometry(30,30),new THREE.MeshLambertMaterial({map:marble}));hall.rotation.x=-Math.PI/2;hall.position.y=0.015;world.add(hall);
 // gumbaz
 {
  const dg=new THREE.SphereGeometry(14.2,40,20,0,Math.PI*2,0,Math.PI/2);
  const dm=new THREE.Mesh(dg,new THREE.MeshPhongMaterial({color:0x9fd8ff,transparent:true,opacity:0.3,side:THREE.DoubleSide,depthWrite:false,shininess:90}));dm.scale.y=0.62;dm.position.y=12;world.add(dm);
  const rib=new THREE.Mesh(new THREE.SphereGeometry(14.25,16,8,0,Math.PI*2,0,Math.PI/2),new THREE.MeshBasicMaterial({color:0xd4b85a,wireframe:true,transparent:true,opacity:0.7}));rib.scale.y=0.62;rib.position.y=12;world.add(rib);
  const chand=new THREE.Group();chand.position.y=9.2;
  chand.add(new THREE.Mesh(new THREE.TorusGeometry(2.4,0.08,8,40),new THREE.MeshBasicMaterial({color:0xe8c85a})).rotateX(Math.PI/2));
  for(let i=0;i<10;i++){const a=i/10*Math.PI*2;const b=new THREE.Mesh(new THREE.SphereGeometry(0.16,10,8),new THREE.MeshBasicMaterial({color:0xfff2c0}));b.position.set(Math.cos(a)*2.4,-0.12,Math.sin(a)*2.4);chand.add(b);}
  const chain=new THREE.Mesh(new THREE.CylinderGeometry(0.03,0.03,2.8,6),new THREE.MeshBasicMaterial({color:0xb99a4a}));chain.position.y=1.4;chand.add(chain);
  world.add(chand);
 }
 // lavhalar
 function sign(txt,sub,w,h,x,y,z,rot,bg,fg){
  const t=canvasTex(1024,Math.round(1024*h/w),(c,cw,ch)=>{c.fillStyle=bg;c.fillRect(0,0,cw,ch);c.strokeStyle=fg;c.lineWidth=8;c.strokeRect(10,10,cw-20,ch-20);c.fillStyle=fg;c.textAlign='center';c.textBaseline='middle';c.font='bold '+Math.round(ch*0.38)+'px Georgia,serif';c.fillText(txt,cw/2,sub?ch*0.40:ch/2);if(sub){c.font=Math.round(ch*0.18)+'px Georgia,serif';c.fillText(sub,cw/2,ch*0.74);}});
  const m=planeMesh(t,w,h);m.position.set(x,y,z);m.rotation.y=rot;world.add(m);
 }
 sign('LOG-324','3D VIRTUAL MUZEY',13,2.0,0,4.35,15.23,0,'#111827','#f5d36a');
 // ZALDAGI KATTA MONITOR (shimol devor): butun muzeydan tanlangan rasmlar slayd-shou
 {const m=makeMonitor({x:0,y:3.45,z:-14.62,rot:0,w:11,h:4.0,cw:1408,ch:512,title:"LOG-324 · XUSH KELIBSIZ!",sub:"3D virtual muzey",hq:true,range:75,far:70,wp:[0,2,-12]});m.items=GAL;}
 // TASHQARIDAGI KATTA MONITOR (old fasad, kirish ustida)
 {box(-12.6,6.1,15.2,12.6,11.7,15.34,0x1b2335);const m=makeMonitor({x:0,y:8.9,z:15.45,rot:0,w:24,h:5.0,cw:1536,ch:320,fit:"cover",title:"LOG-324 · 3D VIRTUAL MUZEY",sub:"Xush kelibsiz!",hq:true,range:120,far:140,wp:[0,1,22]});m.items=GAL;}
 // zalning asosiy kirish eshiklari: yaqinlashganda ochiladi
 for(const sd of [-1,1]){
  const dg=new THREE.Group();dg.position.set(sd*3,0,15);world.add(dg);
  const lf=new THREE.BoxGeometry(2.9,3.15,0.1);lf.translate(-sd*1.45,1.575,0);dg.add(new THREE.Mesh(lf,lm(0x76522e)));
  const pf=new THREE.BoxGeometry(2.5,2.75,0.06);pf.translate(-sd*1.45,1.575,0.07);dg.add(new THREE.Mesh(pf,lm(0xc9a227)));
  addDoor(dg,0,15,0,-sd*1.4,6.5);
 }

 // --- qanotlar ---
 for(const s of [1,-1]){
  for(let f=0;f<2;f++){
   const y0=f*FH;
   const gaps=[0,1,2].map(k=>{const cx=s*(19+8*k);return [cx-1.5,cx+1.5];});
   wallZ(f,-3,s*15,s*39,gaps,S);wallZ(f,3,s*15,s*39,gaps,S);
   wallZ(f,-19,s*15,s*39,[],S);wallZ(f,19,s*15,s*39,[],S);
   wallX(f,s*39,-19,19,[[-3,3]],S);wallX(f,s*15,-19,-15,[],S);wallX(f,s*15,15,19,[],S);
   for(const k of [1,2]){wallX(f,s*(15+8*k),-19,-3,[],S);wallX(f,s*(15+8*k),3,19,[],S);}
   if(f===1)box(Math.min(s*15,s*39)-0.2,5.6,-19.2,Math.max(s*15,s*39)+0.2,6.0,19.2,0xcdbf9f);
   const lo=Math.min(s*15,s*39),hi=Math.max(s*15,s*39);
   box(lo,y0,-19,hi,y0+0.03,19,0xc4b89c);
   box(lo,y0+0.03,-1,hi,y0+0.05,1,0x8a1c2b);
   for(let k=0;k<4;k++){box(s*(18+k*7)-0.5,y0+HT-0.06,-0.5,s*(18+k*7)+0.5,y0+HT,0.5,0xfff6d0,LG);}
  }
 }

 // --- xonalar ---
 const neutral={wall:'e8dfc9',floor:'8d8574',accent:'8a8a8a'};
 const lounge={wall:'e6dcef',floor:'6e5a86',accent:'7a4fd0'};
 const BW=2.15,BH=1.62;
 function plaque(n,rd,isLounge,x,y,z,rot){
  const mine=rd&&rd.mine;
  const th=isLounge?lounge:(rd?(THEMES[rd.theme]||neutral):neutral);
  const t=canvasTex(512,150,(c,w,h)=>{
   c.fillStyle=rd||isLounge?'#'+th.accent:'#7a7a7a';c.fillRect(0,0,w,h);
   c.strokeStyle=mine?'#ffe58a':'rgba(255,255,255,.7)';c.lineWidth=mine?10:5;c.strokeRect(6,6,w-12,h-12);
   c.fillStyle='#fff';c.textAlign='center';c.textBaseline='middle';
   let l1,l2;
   if(isLounge){l1='☕ Dam olish zonasi';l2='Skameykalar va o\'simliklar';}
   else if(rd){l1='№'+n+' · '+rd.name;l2=(mine?'★ Sizning xonangiz · ':'')+rd.title;}
   else{l1='№'+n+' · Bo\'sh xona';l2='Hali egasi yo\'q';}
   let fs=46;c.font='bold '+fs+'px system-ui,sans-serif';while(c.measureText(l1).width>w-40&&fs>20){fs-=2;c.font='bold '+fs+'px system-ui,sans-serif';}
   c.fillText(l1,w/2,h*0.38);
   fs=26;c.font=fs+'px system-ui,sans-serif';while(c.measureText(l2).width>w-40&&fs>14){fs-=2;c.font=fs+'px system-ui,sans-serif';}
   c.fillText(l2,w/2,h*0.74);
  });
  const m=planeMesh(t,3.15,0.92);m.position.set(x,y,z);m.rotation.y=rot;world.add(m);
 }
 function addFrame(item,th,px,py,pz,rotY){
  const g=new THREE.Group();g.position.set(px,py,pz);g.rotation.y=rotY;world.add(g);
  const border=new THREE.Mesh(new THREE.BoxGeometry(BW+0.16,BH+0.16,0.05),new THREE.MeshLambertMaterial({color:hx(th.accent)}));g.add(border);
  let mat,tex=null;
  if(item.type==='empty'){
   tex=canvasTex(512,384,(c,w,h)=>{c.fillStyle='#ece3cf';c.fillRect(0,0,w,h);c.setLineDash([18,12]);c.strokeStyle='#8a7a55';c.lineWidth=6;c.strokeRect(22,22,w-44,h-44);c.setLineDash([]);c.fillStyle='#8a7a55';c.font='bold 150px system-ui';c.textAlign='center';c.textBaseline='middle';c.fillText('+',w/2,h*0.46);c.font='bold 32px system-ui';c.fillText('Rasm qo\'yish',w/2,h*0.80);});
   mat=new THREE.MeshBasicMaterial({map:tex});
  }
  else if(item.type==='image'){mat=new THREE.MeshBasicMaterial({color:0x777777});}
  else if(item.type==='video'){
   tex=canvasTex(512,384,(c,w,h)=>{const gr=c.createLinearGradient(0,0,w,h);gr.addColorStop(0,'#1a2038');gr.addColorStop(1,'#3a2a58');c.fillStyle=gr;c.fillRect(0,0,w,h);c.fillStyle='rgba(255,255,255,.9)';c.beginPath();c.arc(w/2,h/2,70,0,Math.PI*2);c.fill();c.fillStyle='#1a2038';c.beginPath();c.moveTo(w/2-22,h/2-38);c.lineTo(w/2-22,h/2+38);c.lineTo(w/2+40,h/2);c.closePath();c.fill();c.fillStyle='#fff';c.font='bold 30px system-ui';c.textAlign='center';c.fillText('VIDEO',w/2,h-36);});
   mat=new THREE.MeshBasicMaterial({map:tex});
  }else{
   tex=canvasTex(512,384,(c,w,h)=>{c.fillStyle='#f6efdc';c.fillRect(0,0,w,h);c.fillStyle='#221b0e';c.font='26px Georgia,serif';c.textAlign='left';c.textBaseline='top';const ls=wrap(c,item.cap||'',w-56);ls.slice(0,10).forEach((l,i)=>c.fillText(l+(i===9&&ls.length>10?'…':''),28,28+i*33));});
   mat=new THREE.MeshBasicMaterial({map:tex});
  }
  const img=new THREE.Mesh(new THREE.PlaneGeometry(BW,BH),mat);img.position.z=0.03;img.userData.item=item;img.userData.wp=new THREE.Vector3(px,py,pz);g.add(img);clickables.push(img);
  if(item.cap&&item.type!=='text'){
   const lt=canvasTex(512,84,(c,w,h)=>{c.fillStyle='rgba(20,24,40,.9)';c.fillRect(0,0,w,h);c.fillStyle='#fff';c.font='28px system-ui,sans-serif';c.textAlign='center';c.textBaseline='middle';const ls=wrap(c,item.cap,w-24);c.fillText(ls[0]+(ls.length>1?'…':''),w/2,h/2);});
   const lb=planeMesh(lt,BW+0.16,0.3);lb.position.set(0,-(BH/2+0.27),0.03);g.add(lb);
  }
  if(item.type==='image')lazy.push({item,mat,img,border,pos:new THREE.Vector3(px,py,pz),loaded:false});
 }
 for(let f=0;f<2;f++)for(const s of [1,-1])for(const ns of [-1,1])for(let j=0;j<3;j++){
  const isLounge=(ns>0&&j===2);
  const n=isLounge?0:f*10+(s>0?0:5)+(ns<0?j:3+j)+1;
  const rd=isLounge?null:byN[n];
  const th=isLounge?lounge:(rd?(THEMES[rd.theme]||neutral):neutral);
  const y0=f*FH;
  const lo=Math.min(s*(15+8*j),s*(23+8*j)),hi=Math.max(s*(15+8*j),s*(23+8*j)),cx=(lo+hi)/2;
  const zNear=ns<0?-3:3,zBack=ns<0?-19:19;
  const iz0=ns<0?-19+0.24:3+0.24,iz1=ns<0?-3-0.24:19-0.24;
  const ix0=lo+0.24,ix1=hi-0.24;
  const wc=th.wall;
  // pol va devor qoplamasi
  const zA=ns<0?-19+0.2:3+0.2,zB=ns<0?-3-0.2:19-0.2;
  box(lo+0.2,y0+0.03,zA,hi-0.2,y0+0.045,zB,th.floor);
  if(ns<0)box(lo+0.2,y0,-19+0.2,hi-0.2,y0+HT,-19+0.24,wc);else box(lo+0.2,y0,19-0.24,hi-0.2,y0+HT,19-0.2,wc);
  box(lo+0.2,y0,zA,lo+0.24,y0+HT,zB,wc);box(hi-0.24,y0,zA,hi-0.2,y0+HT,zB,wc);
  const fz0=ns<0?-3-0.24:3+0.2,fz1=ns<0?-3-0.2:3+0.24;
  box(lo+0.2,y0,fz0,cx-1.5,y0+HT,fz1,wc);box(cx+1.5,y0,fz0,hi-0.2,y0+HT,fz1,wc);box(cx-1.5,y0+3.2,fz0,cx+1.5,y0+HT,fz1,wc);
  box(cx-0.8,y0+HT-0.06,(iz0+iz1)/2-0.8,cx+0.8,y0+HT,(iz0+iz1)/2+0.8,0xfff6d0,LG);
  // eshik tabletkasi
  const pz=ns<0?-3+0.2+0.03:3-0.2-0.03,prot=ns<0?0:Math.PI;
  plaque(n,rd,isLounge,cx,y0+4.4,pz,prot);
  // manzil
  if(!isLounge){roomPos[n]={x:cx,z:ns*0.7,f,yaw:ns<0?0:Math.PI};navPos[n]={x:cx,z:ns*7.5,f};}
  const open=isLounge||(rd&&n<=data.total);
  if(!open){box(cx-1.5,y0,zNear-0.12,cx+1.5,y0+3.2,zNear+0.12,0x5a4630);col(cx-1.5,zNear-0.12,cx+1.5,zNear+0.12,f);box(cx+1.0,y0+1.0,zNear+(ns<0?0.14:-0.14)-0.02,cx+1.2,y0+1.2,zNear+(ns<0?0.14:-0.14)+0.02,0xe8c85a);continue;}
  // Har bir xonada BITTA ishlaydigan ekran: xona eksponatlarini slayd-shou qiladi, bossangiz ochiladi
  if(!isLounge){
   const m=makeMonitor({x:cx,y:y0+4.15,z:(ns<0?iz0:iz1)+(ns<0?0.2:-0.2),rot:ns<0?0:Math.PI,w:4.0,h:2.25,cw:640,ch:360,title:"№"+n+" · "+rd.name,sub:rd.locked?"🔒 Kod bilan yopilgan":rd.title,range:42,far:22,
    emptyItem:{type:"empty",id:"m"+n,rn:n,cap:""}});
   (rd.items||[]).forEach(it=>{it.rn=n;});m.items=rd.items||[];
  }
  // Eshik: yaqinlashganda ochiladi, uzoqlashganda yopiladi
  {
   const dg=new THREE.Group();dg.position.set(cx-1.5,y0,zNear);world.add(dg);
   const zs=ns<0?1:-1;
   const lf=new THREE.BoxGeometry(2.9,3.08,0.1);lf.translate(1.45,1.54,0);dg.add(new THREE.Mesh(lf,lm(0x76522e)));
   const pf=new THREE.BoxGeometry(2.55,2.75,0.06);pf.translate(1.45,1.54,0.07*zs);dg.add(new THREE.Mesh(pf,lm(hx(th.accent))));
   const knob=new THREE.Mesh(new THREE.SphereGeometry(0.09,10,8),lm(0xe8c85a));knob.position.set(2.65,1.45,0.14*zs);dg.add(knob);
   const dr=addDoor(dg,cx,zNear,y0,ns<0?1.25:-1.25,4,isLounge?0:n);
   if(!isLounge&&rd&&rd.locked){
    dr.lk=true;col(cx-1.5,zNear-0.14,cx+1.5,zNear+0.14,f);
    const lp=planeMesh(canvasTex(256,128,(c,w,h)=>{c.fillStyle="rgba(20,24,40,.92)";c.fillRect(0,0,w,h);c.strokeStyle="#e8c85a";c.lineWidth=6;c.strokeRect(5,5,w-10,h-10);c.fillStyle="#ffe58a";c.textAlign="center";c.textBaseline="middle";c.font="bold 54px system-ui";c.fillText("🔒",w/2,h*0.40);c.font="bold 26px system-ui";c.fillText("KOD KERAK",w/2,h*0.78);}),1.3,0.65);
    lp.position.set(cx,y0+1.75,zNear+(ns<0?0.16:-0.16));lp.rotation.y=ns<0?0:Math.PI;world.add(lp);
   }
  }
  if(isLounge){
   for(const dz of [-1.65,1.65]){const bz=(iz0+iz1)/2+dz;box(cx-2.25,y0,bz-0.42,cx+2.25,y0+0.58,bz+0.42,0x594477);box(cx-2.25,y0+0.58,bz+(ns<0?-0.40:0.40)-0.14,cx+2.25,y0+1.55,bz+(ns<0?-0.40:0.40)+0.14,0x705b96);col(cx-2.25,bz-0.42,cx+2.25,bz+0.42,f);}
   const loungeCenter=(iz0+iz1)/2;
   box(cx-1.35,y0+0.02,loungeCenter-1.1,cx+1.35,y0+0.24,loungeCenter+1.1,0xc5a96c);
   box(cx-0.9,y0+0.25,loungeCenter-0.65,cx+0.9,y0+0.72,loungeCenter+0.65,0x8b623f);
   for(const [qx,qz] of [[ix0+0.5,iz0+0.5],[ix1-0.5,iz0+0.5],[ix0+0.5,iz1-0.5],[ix1-0.5,iz1-0.5]]){cyl(qx,y0,qz,0.22,0.18,0.5,0x8a5a3a,10);const g=new THREE.SphereGeometry(0.45,10,8);g.translate(qx,y0+0.95,qz);pushGeo(g,0x3f8f4a);}
   continue;
  }
  // skameyka (markazda)
  const bz=(iz0+iz1)/2;box(cx-1.0,y0,bz-0.3,cx+1.0,y0+0.45,bz+0.3,hx(th.accent));col(cx-1.0,bz-0.3,cx+1.0,bz+0.3,f);
  for(const [qx,qz] of [[ix0+0.45,ns<0?iz0+0.45:iz1-0.45],[ix1-0.45,ns<0?iz0+0.45:iz1-0.45]]){cyl(qx,y0,qz,0.2,0.16,0.45,0x8a5a3a,10);const g=new THREE.SphereGeometry(0.3,10,8);g.translate(qx,y0+0.7,qz);pushGeo(g,0x3f8f4a);}
  // eksponatlar
  const backZ=ns<0?iz0:iz1,bn=ns<0?1:-1,rotBack=ns<0?0:Math.PI,frontZ=ns<0?iz1:iz0,fn=ns<0?-1:1,rotF=ns<0?Math.PI:0;
  const slots=[];
  [0,-2.4,2.4].forEach(u=>slots.push([cx+u,backZ,rotBack,0,bn]));
  [2.0,5.4,8.8,12.2].forEach(d=>slots.push([ix0,ns<0?iz0+d:iz1-d,Math.PI/2,1,0]));
  [3.7,7.1,10.5].forEach(d=>slots.push([ix1,ns<0?iz0+d:iz1-d,-Math.PI/2,-1,0]));
  [-2.6,2.6].forEach(u=>slots.push([cx+u,frontZ,rotF,0,fn]));
  (rd.items||[]).forEach(it=>{it.rn=n;});
  (rd.items||[]).slice(0,slots.length).forEach((it,i)=>{const sl=slots[i];addFrame(it,th,sl[0]+sl[3]*0.03,y0+1.95,sl[1]+sl[4]*0.03,sl[2]);});
  if(canEditRoom(n)){for(let i=(rd.items||[]).length;i<slots.length;i++){const sl=slots[i];addFrame({type:'empty',id:'e'+n+'_'+i,rn:n,cap:''},th,sl[0]+sl[3]*0.03,y0+1.95,sl[1]+sl[4]*0.03,sl[2]);}}
 }


 // --- LOG-324 maxsus ko'rgazma qanoti: 8 ta yangi katta xona ---
 const specialRooms=[
  ['San’at galereyasi','gold','Rasmlar va haykallar'],
  ['Fan va texnologiya','ocean','Robotlar va innovatsiyalar'],
  ['Tarix xonasi','fire','Tarixiy eksponatlar'],
  ['Katta kutubxona','forest','Kitoblar va bilimlar'],
  ['Mini kinoteatr','night','Katta ekran va tomosha'],
  ['Qishki bog‘','forest','Favvora va yashil hudud'],
  ['O‘yin xonasi','violet','Interaktiv o‘yinlar'],
  ['LOG-324 sovg‘alar do‘koni','rose','Suvenirlar va sovg‘alar']
 ];
 const artColors=[0xc99a45,0x4c9fc5,0xb85c48,0x54845a,0x6c6e9c,0x579b78,0x8a62c2,0xb56d91];
 for(let ff=0;ff<2;ff++){
  const yy=ff*FH,WC=0xe8dfc9;
  // bog'lovchi zal (x 39.2..45) + keng yo'lak (z 8..14): pol, shift, devorlar
  box(39.2,yy,-8,45,yy+0.02,14,0xd4c8ad);box(45,yy,8,109,yy+0.02,14,0xd4c8ad);
  box(39.2,yy+0.02,10.7,109,yy+0.03,11.3,0xb99a4a);
  box(39.2,yy+5.6,-8,45,yy+6.0,14,0xcdbf9f);box(45,yy+5.6,8,109,yy+6.0,14,0xcdbf9f);
  box(39.2,yy,-8,45,yy+5.6,-7.75,WC);col(39.2,-8,45,-7.75,ff);
  box(39.2,yy,13.75,109,yy+5.6,14,WC);col(39.2,13.75,109,14,ff);
  box(108.75,yy,8,109,yy+5.6,14,WC);col(108.75,8,109,14,ff);
  for(let ri=0;ri<4;ri++){
   const id=21+ff*4+ri,x0=45+ri*16,x1=x0+16,z0=-8,z1=8,cx2=(x0+x1)/2;
   const spec=specialRooms[ff*4+ri],accent=artColors[ff*4+ri];
   roomPos[id]={x:cx2,z:5,f:ff,yaw:0};
   box(x0,yy,z0,x1,yy+0.02,z1,ff?0xddd6c8:0xe7dfcf);
   box(x0,yy+5.55,z0,x1,yy+6.0,z1,0xc7b99b);
   // devorlar (yo'lak tomonda keng eshik ochiq, tepasida lintel)
   box(x0,yy,z0,x0+0.25,yy+5.6,z1,WC);box(x1-0.25,yy,z0,x1,yy+5.6,z1,WC);
   box(x0,yy,z0,x1,yy+5.6,z0+0.25,WC);
   box(x0,yy,z1-0.25,cx2-1.8,yy+5.6,z1,WC);box(cx2+1.8,yy,z1-0.25,x1,yy+5.6,z1,WC);
   box(cx2-1.8,yy+3.4,z1-0.25,cx2+1.8,yy+5.6,z1,WC);
   box(cx2-1.9,yy,z1-0.18,cx2+1.9,yy+0.05,z1+0.12,0xb99a4a);
   // ikki tavaqali eshik: yaqinlashganda yo'lakka ochiladi
   for(const sd of [-1,1]){
    const dg=new THREE.Group();dg.position.set(cx2+sd*1.8,yy,z1);world.add(dg);
    const lf=new THREE.BoxGeometry(1.7,3.3,0.08);lf.translate(-sd*0.85,1.65,0);dg.add(new THREE.Mesh(lf,lm(0x76522e)));
    const pf=new THREE.BoxGeometry(1.45,3.0,0.05);pf.translate(-sd*0.85,1.65,0.06);dg.add(new THREE.Mesh(pf,lm(accent)));
    addDoor(dg,cx2,z1,yy,sd*1.3,4.5);
   }
   lintels.push([cx2-1.8,z1-0.25,cx2+1.8,z1,yy+3.4]);
   // xona nomi lavhasi: yo'lak tomonga qaragan
   sign('LOG-324',spec[0],6.0,1.0,cx2,yy+4.5,z1+0.06,0,'#111827','#f5d36a');
   // shimol devorda BITTA yirik ishlaydigan ekran (galereya slayd-shousi)
   {const m=makeMonitor({x:x0+8,y:yy+3.1,z:z0+0.36,rot:0,w:6.4,h:3.4,cw:768,ch:408,title:spec[0],sub:"LOG-324 ko'rgazma xonasi",range:45,far:26});m.items=GAL;}
   // san'at ramkalari: xona ichiga qaragan (janub devorda eshikning ikki yonida + yon devorlarda)
   const art=(px,pz,ry)=>{
    const fr=new THREE.Group();fr.position.set(px,yy+2.2,pz);fr.rotation.y=ry;world.add(fr);
    fr.add(new THREE.Mesh(new THREE.BoxGeometry(3.6,2.6,0.12),lm(accent)));
    const tx=canvasTex(512,384,(c,w,h)=>{
     c.fillStyle='#f1e6ce';c.fillRect(0,0,w,h);
     const gr=c.createLinearGradient(0,0,w,h);gr.addColorStop(0,'#'+accent.toString(16).padStart(6,'0'));gr.addColorStop(1,'#24334d');c.fillStyle=gr;c.fillRect(18,18,w-36,h-36);
     c.fillStyle='#fff0c4';c.textAlign='center';c.textBaseline='middle';c.font='bold 34px Georgia';c.fillText(spec[0],w/2,h/2);
    });
    const pm=new THREE.Mesh(new THREE.PlaneGeometry(3.35,2.35),new THREE.MeshBasicMaterial({map:tx}));
    pm.position.z=0.075;fr.add(pm);
   };
   art(x0+3.2,z1-0.31,Math.PI);art(x1-3.2,z1-0.31,Math.PI);art(x0+0.31,0,Math.PI/2);art(x1-0.31,0,-Math.PI/2);
   // markaziy ko'rgazma platformasi (to'siq bilan)
   box(x0+4,yy,z0+5,x1-4,yy+0.65,z1-5,accent);col(x0+4,z0+5,x1-4,z1-5,ff);
   cyl(cx2,yy+0.65,0,0.75,0.75,1.5,0xb99a4a,24);
   // devor to'siqlari
   col(x0,z0,x0+0.25,z1,ff);col(x1-0.25,z0,x1,z1,ff);col(x0,z0,x1,z0+0.25,ff);
   col(x0,z1-0.25,cx2-1.8,z1,ff);col(cx2+1.8,z1-0.25,x1,z1,ff);
  }
 }
 // Lift: ikki qavatga xizmat qiladi. Yoniga kelinganda "Lift" tugmasi chiqadi; kabina o'yinchi bilan birga ko'tariladi.
 {
  const lx=12.8,lz=0.0;
  for(const xx of [lx-1.5,lx+1.5])for(const zz of [lz-1.5,lz+1.5]){
   const p=new THREE.Mesh(new THREE.CylinderGeometry(0.08,0.08,6,10),new THREE.MeshLambertMaterial({color:0x9bd8e8,transparent:true,opacity:0.55}));
   p.position.set(xx,3,zz);world.add(p);
  }
  box(lx-1.5,0,lz-1.5,lx+1.5,0.03,lz+1.5,0xb99a4a);
  box(lx-1.5,6,lz-1.5,lx+1.5,6.04,lz+1.5,0xb99a4a);
  liftCab=new THREE.Group();liftCab.position.set(lx,0,lz);world.add(liftCab);
  const glass=new THREE.MeshBasicMaterial({color:0x9bd8e8,transparent:true,opacity:0.28,side:THREE.DoubleSide,depthWrite:false});
  for(const sz of [-1,1]){
   const pn=new THREE.Mesh(new THREE.PlaneGeometry(2.9,2.6),glass);pn.position.set(0,1.3,sz*1.45);liftCab.add(pn);
   const bar=new THREE.Mesh(new THREE.BoxGeometry(2.9,0.08,0.08),lm(0xb99a4a));bar.position.set(0,2.6,sz*1.45);liftCab.add(bar);
  }
 }
 // Foto zona: tashqi bog'dagi maxsus LOG-324 suratga tushish maydoni.
 {
  cyl(-55,-1.2,35,5.2,5.2,0.18,0xb99a4a,40);
  cyl(-55,-1.02,35,4.8,4.8,0.12,0x332b45,40);
  box(-61,-1.25,40,-49,4.2,40.5,0x18243c);col(-61,40,-49,40.5);
  sign('LOG-324','PHOTO ZONE',8,1.5,-55,2.8,39.97,Math.PI,'#111827','#f5d36a');
  roomPos[29]={x:-55,z:35,y:-1.2,f:0,yaw:Math.PI};roomPos[30]={x:0,z:12,f:0,yaw:0};
 }
 // daraxtlar
 let seed=7;const rnd=()=>{seed=(seed*16807)%2147483647;return seed/2147483647;};
 for(let i=0;i<28;i++){const sx=rnd()<0.5?-1:1;const x=sx*(13+rnd()*34),z=27+rnd()*50;cyl(x,-1.2,z,0.22,0.28,1.6,0x6b4a2b,8);cyl(x,0.2,z,0,1.5,3.4,0x2f7d3a,9);col(x-0.5,z-0.5,x+0.5,z+0.5);}

 const sm=new THREE.Mesh(mergeGeometries(G),new THREE.MeshLambertMaterial({vertexColors:true}));world.add(sm);
 if(LG.length)world.add(new THREE.Mesh(mergeGeometries(LG),new THREE.MeshBasicMaterial({vertexColors:true})));
 indexColliders();
 updateLazy(true);
}

// ---------- rasmlarni dangasa yuklash ----------
const loader=new THREE.TextureLoader();
function updateLazy(all){
 for(const fr of lazy){
  if(fr.loaded)continue;
  const d=Math.hypot(fr.pos.x-P.x,fr.pos.y-P.y-1.6,fr.pos.z-P.z);
  if(!all&&d>26)continue;if(all&&d>34)continue;
  fr.loaded=true;
  loader.load(fr.item.u,tex=>{
   tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=4;
   fr.mat.map=tex;fr.mat.color.set(0xffffff);fr.mat.needsUpdate=true;
   const iw=tex.image.width||4,ih=tex.image.height||3,s=Math.min(BW/iw,BH/ih);
   const w=iw*s,h=ih*s;fr.img.scale.set(w/BW,h/BH,1);fr.border.scale.set((w+0.16)/(BW+0.16),(h+0.16)/(BH+0.16),1);
  },undefined,()=>{
   fr.item.broken=true;
   const bt=canvasTex(512,384,(c,w,h)=>{c.fillStyle='#4a4f5e';c.fillRect(0,0,w,h);c.fillStyle='#ffd27a';c.font='bold 120px system-ui';c.textAlign='center';c.textBaseline='middle';c.fillText('⚠',w/2,h*0.42);c.fillStyle='#fff';c.font='bold 30px system-ui';c.fillText('Rasm yuklanmadi',w/2,h*0.72);});
   fr.mat.map=bt;fr.mat.color.set(0xffffff);fr.mat.needsUpdate=true;
  });
 }
}
const BW=2.15,BH=1.62;
setInterval(()=>updateLazy(false),500);

// ---------- ko'rish oynasi ----------
function canEditRoom(rn){const r=DATA&&(DATA.rooms||[]).find(x=>x.n===rn);return !!(r&&(r.mine||(DATA.me&&DATA.me.owner)));}
let putCtx=null;
function openItem(it){
 const b=$('vwb');b.innerHTML='';putCtx=null;const pb=$('vwput');pb.style.display='none';
 const can=canEditRoom(it.rn),isOwner=!!(DATA&&DATA.me&&DATA.me.owner);
 const showPut=label=>{if(!can)return;putCtx={rn:it.rn,id:it.type==='empty'?'':it.id};pb.textContent=label;pb.style.display='';};
 const note=(txt)=>{b.innerHTML='';const d=document.createElement('div');d.className='txt';d.textContent=txt;b.appendChild(d);};
 if(it.type==='empty'){note(can?'Bu joy bo\'sh. Pastdagi tugma orqali telefoningizdan rasm tanlang — u shu yerga qo\'yiladi.':'Bu joy hozircha bo\'sh.');showPut('🖼 Rasm qo\'yish');}
 else if(it.type==='image'){
  const im=document.createElement('img');
  im.onerror=()=>{note('Rasm yuklanmadi (fayl topilmadi yoki internet uzildi).'+(can?' Pastdagi tugma bilan o\'sha joyga yangi rasm qo\'ying.':''));showPut('🖼 Rasm qo\'yish');};
  im.src=it.f;b.appendChild(im);
  if(isOwner)showPut('🔁 Rasmni almashtirish');
 }
 else if(it.type==='video'){const v=document.createElement('video');v.src=it.f;v.controls=true;v.autoplay=true;v.playsInline=true;b.appendChild(v);}
 else{const d=document.createElement('div');d.className='txt';d.textContent=it.cap||'';b.appendChild(d);}
 $('vwc').textContent=(it.type==='text'||it.type==='empty')?'':(it.cap||'');
 $('vw').classList.remove('hide');
}
function toJpeg(file){return new Promise((res,rej)=>{
 const url=URL.createObjectURL(file),im=new Image();
 im.onload=()=>{const s=Math.min(1,1600/Math.max(im.naturalWidth,im.naturalHeight)),c=document.createElement('canvas');
  c.width=Math.max(1,Math.round(im.naturalWidth*s));c.height=Math.max(1,Math.round(im.naturalHeight*s));
  c.getContext('2d').drawImage(im,0,0,c.width,c.height);URL.revokeObjectURL(url);
  c.toBlob(bl=>bl?res(bl):rej(new Error('blob')),'image/jpeg',0.86);};
 im.onerror=()=>{URL.revokeObjectURL(url);rej(new Error('img'));};im.src=url;});}
$('vwput').onclick=()=>{if(putCtx)$('putf').click();};
$('putf').onchange=async e=>{
 const f=e.target.files&&e.target.files[0];e.target.value='';
 if(!f||!putCtx)return;const ctx=putCtx;
 toast('⏳ Rasm yuklanmoqda...',60000);
 try{
  const blob=await toJpeg(f);
  const r=await fetch('/museum/put?n='+ctx.rn+(ctx.id?'&i='+encodeURIComponent(ctx.id):''),{method:'POST',headers:{'X-Init':(tg&&tg.initData)||'','X-Museum-Session':SESSION_KEY,'Content-Type':'image/jpeg'},body:blob});
  let j={};try{j=await r.json();}catch(_){}
  if(!r.ok||!j.ok){toast('⚠️ '+(j.msg||'Yuklab bo\'lmadi'),4500);return;}
  closeItem();toast('✅ Rasm qo\'yildi',2600);refresh(false);
 }catch(err){toast('⚠️ Rasmni o\'qib bo\'lmadi. Boshqa rasm tanlang',4000);}
};
function closeItem(){const v=$('vwb').querySelector('video');if(v){v.pause();v.removeAttribute('src');v.load();}$('vwb').innerHTML='';$('vwput').style.display='none';$('vw').classList.add('hide');}
$('vwx').onclick=closeItem;

// ---------- boshqaruv ----------
const cv=$('c'),ptrs=new Map();
const ray=new THREE.Raycaster(),ndc=new THREE.Vector2();
function tap(x,y){
 ndc.set(x/innerWidth*2-1,-(y/innerHeight)*2+1);ray.setFromCamera(ndc,camera);
 const hs=ray.intersectObjects(clickables,false);
 if(hs.length){const o=hs[0].object.userData;if(o.item&&hs[0].distance<(o.far||16))openItem(o.item);}
}
cv.addEventListener('pointerdown',e=>{try{cv.setPointerCapture(e.pointerId);}catch(_){}ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY,sx:e.clientX,sy:e.clientY,t:performance.now(),moved:false});});
cv.addEventListener('pointermove',e=>{const p=ptrs.get(e.pointerId);if(!p)return;const dx=e.clientX-p.x,dy=e.clientY-p.y;p.x=e.clientX;p.y=e.clientY;if(Math.hypot(e.clientX-p.sx,e.clientY-p.sy)>8)p.moved=true;if(p.moved&&ptrs.size===1){P.yaw-=dx*0.006;P.pitch=Math.min(0.92,Math.max(-0.08,P.pitch+dy*0.0035));}});
const pend=e=>{const p=ptrs.get(e.pointerId);ptrs.delete(e.pointerId);return p;};
cv.addEventListener('pointerup',e=>{const p=pend(e);if(p&&!p.moved&&performance.now()-p.t<500)tap(e.clientX,e.clientY);});
cv.addEventListener('pointercancel',pend);
const st=$('stick'),kn=$('knob');let sid=null;const JV={x:0,y:0};
function mvStick(e){const r=st.getBoundingClientRect();let dx=e.clientX-(r.left+r.width/2),dy=e.clientY-(r.top+r.height/2);const R=r.width/2-8;const l=Math.hypot(dx,dy);if(l>R){dx*=R/l;dy*=R/l;}kn.style.transform='translate('+dx+'px,'+dy+'px)';JV.x=dx/R;JV.y=-dy/R;}
st.addEventListener('pointerdown',e=>{sid=e.pointerId;try{st.setPointerCapture(e.pointerId);}catch(_){}mvStick(e);});
st.addEventListener('pointermove',e=>{if(e.pointerId===sid)mvStick(e);});
const endStick=e=>{if(e.pointerId===sid){sid=null;JV.x=JV.y=0;kn.style.transform='translate(0,0)';}};
st.addEventListener('pointerup',endStick);st.addEventListener('pointercancel',endStick);
const keys={};addEventListener('keydown',e=>{if(e.target&&(e.target.tagName==='INPUT'||e.target.tagName==='SELECT'))return;keys[e.key.toLowerCase()]=true;});addEventListener('keyup',e=>{keys[e.key.toLowerCase()]=false;});

function teleport(x,z,y,yaw){P.x=x;P.z=z;P.y=y;P.dy=y;P.vx=P.vz=0;P.snap=true;P.yaw=yaw;P.rot=yaw+Math.PI;P.pitch=0.24;P.dist=7.2;updateLazy(true);}
function goRoom(n){const r=roomPos[n];if(!r)return;teleport(r.x,r.z,r.y!==undefined?r.y:r.f*FH,r.yaw);}
function listRooms(){
 const box=$('rmb');box.innerHTML='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><b style="font-size:16px">🚪 Xonalar</b><button class="b" id="rmx">✕</button></div>';
 const rooms={};(DATA.rooms||[]).forEach(r=>rooms[r.n]=r);
 for(let n=1;n<=DATA.total;n++){
  const r=rooms[n];const d=document.createElement('div');d.className='rr'+(r&&r.mine?' mine':'')+(r?'':' empty');
  d.innerHTML='<span><b>№'+n+'</b> '+(r?esc(r.name)+' · <i>'+esc(r.title)+'</i>':'bo\'sh')+'</span><span>'+(r?r.items.length+' 🖼':'')+' · '+(n>10?'2':'1')+'-qavat</span>';
  if(r)d.onclick=()=>{$('rm').classList.add('hide');goRoom(n);};
  box.appendChild(d);
 }
 const specialNames=['San’at galereyasi','Fan va texnologiya','Tarix xonasi','Katta kutubxona','Mini kinoteatr','Qishki bog‘','O‘yin xonasi','LOG-324 sovg‘alar do‘koni'];
 specialNames.forEach((nm,i)=>{const n=21+i,d=document.createElement('div');d.className='rr';d.innerHTML='<span><b>★</b> '+nm+'</span><span>'+(i<4?'1':'2')+'-qavat · Maxsus xona</span>';d.onclick=()=>{$('rm').classList.add('hide');goRoom(n);};box.appendChild(d);});
 const ph=document.createElement('div');ph.className='rr';ph.innerHTML='<span><b>📸</b> LOG-324 Foto zona</span><span>Bog‘</span>';ph.onclick=()=>{$('rm').classList.add('hide');teleport(-55,35,-1.2,Math.PI);};box.appendChild(ph);

 $('rm').classList.remove('hide');$('rmx').onclick=()=>$('rm').classList.add('hide');
}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('bRooms').onclick=listRooms;
$('bMine').onclick=()=>{if(DATA&&DATA.mine)goRoom(DATA.mine);else if(DATA&&DATA.me&&DATA.me.owner)toast('👑 Siz muzey egasisiz. Xonalar va kodlarni «👑 Egasi» tugmasi orqali boshqaring',4200);else openLogin();};
$('bHall').onclick=()=>teleport(0,12,0,0);
$('bRef').onclick=()=>refresh();
$('bMap').onclick=()=>{
 const ml=$('maplist');ml.innerHTML='';
 const add=(ic,text,n)=>{const b=document.createElement('button');b.textContent=ic+' '+text;b.onclick=()=>{$('mapov').classList.add('hide');startNav(n,text);};ml.appendChild(b);};
 add('🏛','Markaziy katta zal',30);
 for(let n=1;n<=DATA.total;n++){const r=(DATA.rooms||[]).find(x=>x.n===n);if(r)add(r.mine?'⭐':'🚪','№'+n+' · '+r.name,n);}
 for(let i=0;i<8;i++)add('★',(i<4?'1-qavat · ':'2-qavat · ')+specialNamesMap[i],21+i);
 add('📸','Foto zona',29);
 $('mapov').classList.remove('hide');
};
const specialNamesMap=['San’at galereyasi','Fan va texnologiya','Tarix xonasi','Katta kutubxona','Mini kinoteatr','Qishki bog‘','O‘yin xonasi','LOG-324 sovg‘alar do‘koni'];
$('mapx').onclick=()=>$('mapov').classList.add('hide');
$('bLift').onclick=()=>{
 const upper=P.y>2.8;
 teleport(12.8,0,upper?0:6,Math.PI);
 toast(upper?'Lift: 1-qavat':'Lift: 2-qavat');
};
$('bPhoto').onclick=()=>teleport(-55,35,-1.2,Math.PI);
let musicCtx=null,musicTimer=null,musicOn=false,musicStep=0;
function toggleMuseumMusic(){
 if(musicOn){if(musicTimer)clearInterval(musicTimer);musicTimer=null;if(musicCtx){musicCtx.close();musicCtx=null;}musicOn=false;$('bMusic').textContent='🎵 Musiqa';return;}
 const AC=window.AudioContext||window.webkitAudioContext;if(!AC){toast('Qurilmada audio qo‘llab-quvvatlanmaydi');return;}
 musicCtx=new AC();musicOn=true;$('bMusic').textContent='🔇 Musiqani o‘chirish';
 const notes=[261.63,329.63,392.00,329.63,293.66,349.23,440.00,349.23,261.63,329.63,392.00,523.25];
 const play=()=>{if(!musicCtx)return;const o=musicCtx.createOscillator(),g=musicCtx.createGain();o.type='sine';o.frequency.value=notes[musicStep++%notes.length];g.gain.setValueAtTime(0.0001,musicCtx.currentTime);g.gain.exponentialRampToValueAtTime(0.035,musicCtx.currentTime+0.08);g.gain.exponentialRampToValueAtTime(0.0001,musicCtx.currentTime+0.72);o.connect(g);g.connect(musicCtx.destination);o.start();o.stop(musicCtx.currentTime+0.75);};
 play();musicTimer=setInterval(play,800);
}
$('bMusic').onclick=toggleMuseumMusic;


// ---------- tezlik, xabarlar, API ----------
let SPDM=1;
document.querySelectorAll('#spd button').forEach(b=>b.onclick=()=>{SPDM=+b.dataset.s;document.querySelectorAll('#spd button').forEach(x=>x.classList.toggle('on',x===b));});
const toastEl=$('toast');let toastT=0;
function toast(t,ms){toastEl.textContent=t;toastEl.classList.remove('hide');clearTimeout(toastT);toastT=setTimeout(()=>toastEl.classList.add('hide'),ms||3200);}
let SESSION_KEY='';
async function api(path,params){
 const qs=new URLSearchParams(params||{}).toString();
 const r=await fetch(path+(qs?'?'+qs:''),{headers:{'X-Init':(tg&&tg.initData)||'','X-Museum-Session':SESSION_KEY},cache:'no-store'});
 if(r.status===401){let e={};try{e=await r.json();}catch(_){};if(e.error==='code_required'){SESSION_KEY='';throw new Error('code_required');}throw new Error('auth');}
 return r.json();
}

// ---------- profil (avatar, tugmalar) ----------
let meSig='';
function applyMe(){
 const me=(DATA&&DATA.me)||{};
 const sig=[me.g,me.h,me.n].join('|');
 if(sig!==meSig){meSig=sig;buildAvatar({g:me.g,h:me.h});}
 $('bOwner').classList.toggle('hide',!me.owner);
}
function twirl(){const me=(DATA&&DATA.me)||{};if(me.g==='f')P.spin=Math.PI*4;}

// ---------- kod bilan kirish ----------
function openLogin(){$('lge').textContent='';$('lgi').value='';$('lg').classList.remove('hide');setTimeout(()=>{try{$('lgi').focus();}catch(_){}},60);}
$('bLogin').onclick=openLogin;
async function doLogin(){
 const c=$('lgi').value.trim();if(!c)return;
 $('lgok').disabled=true;$('lge').textContent='';
 try{
  const r=await api('/museum/login',{c});
  if(!r.ok||!r.session){$('lge').textContent=r.error||'Tasdiqlash amalga oshmadi. Kodni tekshiring.';return;}
  SESSION_KEY=r.session;
  $('lge').textContent='✅ Kod tasdiqlandi. Muzey yuklanmoqda...';
  DATA=await fetchData();buildWorld(DATA);applyMe();
  $('lg').classList.add('hide');$('load').classList.add('hide');
  $('hud').classList.remove('hide');$('stick').classList.remove('hide');$('act').classList.remove('hide');$('spd').classList.remove('hide');
  const h=$('hint');h.classList.remove('hide');setTimeout(()=>{h.style.opacity=0;},7000);setTimeout(()=>h.classList.add('hide'),8000);
  twirl();askNav(true);
  requestAnimationFrame(tick);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 }catch(e){$('lge').textContent='Ulanib bo\'lmadi. Qayta urinib ko\'ring.';}
 finally{$('lgok').disabled=false;}
}
$('lgok').onclick=doLogin;
$('lgi').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});

// ---------- YO'L KO'RSATISH: strelka + sariq nuqtalar (haqiqiy yurish xaritasi bo'yicha: zinapoya, eshik, qanotlar) ----------
const NAV={on:false,n:0,label:'',tx:0,tz:0,ty:0,field:null,t:0,wx:0,wz:0,has:false,lastBuild:0};
const NS=0.5,NRAD=0.4;
const DX=[1,-1,0,0,1,1,-1,-1],DZ=[0,0,1,-1,1,-1,1,-1];
const arrow=new THREE.Group();
(function(){
 const mt=new THREE.MeshBasicMaterial({color:0xffc928,depthTest:false});
 const cone=new THREE.Mesh(new THREE.ConeGeometry(0.26,0.55,14).rotateX(Math.PI/2),mt);cone.position.z=0.38;
 const sh=new THREE.Mesh(new THREE.BoxGeometry(0.14,0.14,0.55),mt);sh.position.z=-0.05;
 cone.renderOrder=20;sh.renderOrder=20;arrow.add(cone,sh);arrow.scale.set(1.5,1.5,1.5);
})();
arrow.visible=false;scene.add(arrow);
const trail=[];
for(let i=0;i<16;i++){const m=new THREE.Mesh(new THREE.SphereGeometry(0.12,8,6),new THREE.MeshBasicMaterial({color:0xffc928,depthTest:false}));m.renderOrder=19;m.visible=false;scene.add(m);trail.push(m);}
const navpEl=$('navp');let navTxt='';
const nvk=(ix,iz,y)=>ix+','+iz+','+Math.round(y*2);
function nvCan(x,z,y,dx,dz){if(hit(x,z,y>2.8?1:0,NRAD))return null;const h=surfaceY(x,z,y);if(h===null)return null;if(Math.abs(h-y)>0.3&&(dx===0||dz!==0))return null;return h;}
function navPoint(n){const r=navPos[n]||roomPos[n];if(!r)return null;return{x:r.x,z:r.z,y:r.y!==undefined?r.y:r.f*FH};}
function buildField(){
 NAV.lastBuild=performance.now();NAV.field=null;
 const tp=navPoint(NAV.n);if(!tp)return;
 let ty=surfaceY(tp.x,tp.z,tp.y);if(ty===null)ty=tp.y;
 NAV.tx=tp.x;NAV.tz=tp.z;NAV.ty=ty;
 const par=new Map(),Y=new Map(),D=new Map();
 const gx=Math.round(tp.x/NS),gz=Math.round(tp.z/NS),k0=nvk(gx,gz,ty);
 par.set(k0,null);Y.set(k0,ty);D.set(k0,0);
 const qx=[gx],qz=[gz],qy=[ty],pcx=Math.round(P.x/NS),pcz=Math.round(P.z/NS);
 let qi=0,stop=1e9;
 while(qi<qx.length&&qi<stop){
  const cx=qx[qi],cz=qz[qi],cy=qy[qi],ck=nvk(cx,cz,cy),cd=D.get(ck);qi++;
  if(stop===1e9&&Math.abs(cx-pcx)<=1&&Math.abs(cz-pcz)<=1&&Math.abs(cy-P.y)<0.8)stop=qi+5000;
  for(let d=0;d<8;d++){
   const nx=cx+DX[d],nz=cz+DZ[d],h=nvCan(nx*NS,nz*NS,cy,DX[d],DZ[d]);if(h===null)continue;
   const nk=nvk(nx,nz,h);if(par.has(nk))continue;
   par.set(nk,ck);Y.set(nk,h);D.set(nk,cd+(DX[d]&&DZ[d]?1.41:1));qx.push(nx);qz.push(nz);qy.push(h);
  }
 }
 NAV.field={par,Y,D};
}
function findState(){
 const f=NAV.field;if(!f)return null;
 const pcx=Math.round(P.x/NS),pcz=Math.round(P.z/NS),pyb=Math.round(P.y*2);let best=null,bd=1e9;
 for(let dx=-1;dx<=1;dx++)for(let dz=-1;dz<=1;dz++)for(let dy=-1;dy<=1;dy++){
  const k=(pcx+dx)+','+(pcz+dz)+','+(pyb+dy);
  if(f.par.has(k)&&Math.abs(f.Y.get(k)-P.y)<0.4){const d=f.D.get(k);if(d<bd){bd=d;best=k;}}
 }
 return best;
}
function losClear(x0,z0,x1,z1,fl,y0){
 const d=Math.hypot(x1-x0,z1-z0),n=Math.max(1,Math.ceil(d/0.25));let y=y0;
 for(let i=1;i<=n;i++){
  const t=i/n,x=x0+(x1-x0)*t,z=z0+(z1-z0)*t;
  if(hit(x,z,y>2.8?1:0,0.42))return false;
  const h=surfaceY(x,z,y);if(h===null)return false;y=h;
 }
 return true;
}
function stopNav(){NAV.on=false;NAV.field=null;NAV.has=false;arrow.visible=false;trail.forEach(m=>{m.visible=false;});navpEl.classList.add('hide');navTxt='';}
function startNav(n,label){
 if(!navPoint(n)){toast('Bu joyga yo\'l topilmadi');return;}
 NAV.on=true;NAV.n=n;NAV.label=label||'';NAV.t=0;NAV.has=false;navTxt='';buildField();
 if(!findState())toast('⚠️ Aniq yo\'l topilmadi — to\'g\'ri yo\'nalish ko\'rsatiladi',3500);
 else toast('🧭 Yo\'l ko\'rsatiladi: '+NAV.label+'. To\'xtatish: yuqoridagi yozuvni bosing',3800);
}
navpEl.onclick=()=>{stopNav();toast('Yo\'l ko\'rsatish o\'chirildi',1800);};
function navUpdate(now,dt){
 if(!NAV.on)return;
 if(NAV.field&&Math.hypot(P.x-NAV.tx,P.z-NAV.tz)<2.0&&Math.abs(P.y-NAV.ty)<1.2){const lb=NAV.label;stopNav();toast('🎉 '+lb+' — yetib keldingiz!',3000);return;}
 NAV.t-=dt;
 if(NAV.t<=0){
  NAV.t=0.15;let sk=findState();
  if(!sk&&now-NAV.lastBuild>1500){buildField();sk=findState();}
  NAV.has=false;trail.forEach(m=>{m.visible=false;});
  let txt;
  if(sk){
   const f=NAV.field;let cur=sk,wp=null,ti=0,first=null;
   const fl=P.y>2.8?1:0;
   for(let i=0;i<40;i++){
    const p=f.par.get(cur);if(!p)break;cur=p;
    if(i===0)first=cur;
    if(i<14){const q=cur.split(',');if(losClear(P.x,P.z,q[0]*NS,q[1]*NS,fl,P.y))wp=cur;}
    if(i%2===1&&ti<trail.length){const q=cur.split(',');const m=trail[ti++];m.position.set(q[0]*NS,f.Y.get(cur)+0.12,q[1]*NS);m.visible=true;}
   }
   if(!wp)wp=first||cur;
   const q=wp.split(',');NAV.wx=q[0]*NS;NAV.wz=q[1]*NS;NAV.has=true;
   txt=NAV.label+' · '+Math.max(1,Math.round(f.D.get(sk)*NS*1.1))+' m';
  }else{
   NAV.wx=NAV.tx;NAV.wz=NAV.tz;NAV.has=true;
   txt=NAV.label+' · '+Math.round(Math.hypot(NAV.tx-P.x,NAV.tz-P.z))+' m';
  }
  if(txt!==navTxt){navTxt=txt;navpEl.textContent='🧭 '+txt+'   ✕';navpEl.classList.remove('hide');}
 }
 if(NAV.has){arrow.visible=true;arrow.position.set(P.x,P.dy+2.35+Math.sin(now/260)*0.08,P.z);arrow.rotation.y=Math.atan2(NAV.wx-P.x,NAV.wz-P.z);}
}
function askNav(fresh){
 const me=DATA.me||{};if(!DATA.mine)return;
 $('nqt').textContent=(fresh?'✅ Kod qabul qilindi. ':'')+(me.name||'')+', xonangiz №'+DATA.mine+'. Strelka bilan yo\'l ko\'rsatilsinmi?';
 $('nq').classList.remove('hide');
}
$('nqy').onclick=()=>{$('nq').classList.add('hide');startNav(DATA.mine,'№'+DATA.mine+' xonangiz');};
$('nqn').onclick=()=>{$('nq').classList.add('hide');};

// ---------- LIFT va eshiklar ----------
const LIFT={x:12.8,z:0,riding:false,t:0,y0:0,y1:0};
const ctxBtn=$('ctx');let ctxT=0;
let ctxMode=null;
function ctxUpdate(dt){
 ctxT-=dt;if(ctxT>0)return;ctxT=0.15;
 if(LIFT.riding){ctxBtn.classList.add('hide');return;}
 const up=P.y>2.8,lvl=up?FH:0;
 if(Math.hypot(P.x-LIFT.x,P.z-LIFT.z)<3.4&&Math.abs(P.y-lvl)<0.7){ctxMode=null;ctxBtn.textContent=up?'🛗 Lift: 1-qavatga tushish':'🛗 Lift: 2-qavatga chiqish';ctxBtn.classList.remove('hide');return;}
 let best=null,bd=3.8;
 for(const d of doors){if(!d.rn||Math.abs(P.y-d.y)>1.8)continue;const dd=Math.hypot(P.x-d.cx,P.z-d.cz);if(dd<bd){bd=dd;best=d;}}
 if(best&&DATA){
  const r=(DATA.rooms||[]).find(x=>x.n===best.rn);
  if(r){
   if(canEditRoom(best.rn)){ctxMode={kind:'lock',rn:best.rn,mode:'manage'};ctxBtn.textContent=r.lockSet?'🔑 Eshik kodi (qo\'yilgan)':'🔑 Eshikka kod qo\'yish';ctxBtn.classList.remove('hide');return;}
   if(r.locked){ctxMode={kind:'lock',rn:best.rn,mode:'enter'};ctxBtn.textContent='🔒 Kod kiritish';ctxBtn.classList.remove('hide');return;}
  }
 }
 ctxMode=null;ctxBtn.classList.add('hide');
}
ctxBtn.onclick=()=>{
 if(LIFT.riding)return;
 if(ctxMode&&ctxMode.kind==='lock'){openLock(ctxMode.rn,ctxMode.mode);return;}
 const up=P.y>2.8;
 LIFT.riding=true;LIFT.t=0;LIFT.y0=P.y;LIFT.y1=up?0:FH;
 P.x=LIFT.x;P.z=LIFT.z;P.vx=P.vz=0;ctxBtn.classList.add('hide');
};
function liftStep(dt){
 LIFT.t+=dt/2.6;const k=Math.min(1,LIFT.t),e=k<0.5?2*k*k:1-Math.pow(-2*k+2,2)/2;
 P.y=LIFT.y0+(LIFT.y1-LIFT.y0)*e;P.dy=P.y;
 if(k>=1){LIFT.riding=false;P.y=LIFT.y1;P.dy=P.y;toast(LIFT.y1>0?'🛗 2-qavat':'🛗 1-qavat',1800);}
}
function doorsUpdate(dt){
 const kk=1-Math.exp(-7*dt);
 for(const d of doors){
  const near=!d.lk&&Math.abs(P.y-d.y)<1.8&&Math.hypot(P.x-d.cx,P.z-d.cz)<d.R;
  d.a+=((near?1:0)-d.a)*kk;d.g.rotation.y=d.r1*d.a;
 }
 if(liftCab)liftCab.position.y=LIFT.riding?P.dy:(P.y>2.8?FH:0);
}

// ---------- AMAL tugmasi: yaqindagi eksponatni ochish ----------
const actBtn=$('act');let readyT=0;
function nearestItem(){
 let best=null,bd=1e9;
 for(const m of clickables){const w=m.userData.wp;if(!w||Math.abs(w.y-(P.y+2))>3.2)continue;const d=Math.hypot(w.x-P.x,w.z-P.z);if(d<bd){bd=d;best=m;}}
 return bd<=6.5?best:null;
}
const doAct=()=>{const m=nearestItem();if(m)openItem(m.userData.item);else toast('Yaqin atrofda eksponat yo\'q — devordagi rasmga yaqinlashing');};
actBtn.onclick=doAct;

// ---------- egasi paneli ----------
const agoTxt=t=>t<60?t+' s oldin':t<3600?Math.round(t/60)+' daq oldin':Math.round(t/3600)+' soat oldin';
function fmtStatus(t){
 const ic=t.mode==='supabase'?(t.ok?'🟢':'🔴'):'🟡';
 let x=ic+' '+(t.mode==='supabase'?'Supabase':'Lokal fayl (Render qayta ishga tushsa o\'chadi!)');
 if(t.mode==='supabase')x+=t.ok?' · '+t.ms+' ms'+(t.saved_ago!=null?' · oxirgi saqlash '+agoTxt(t.saved_ago):' · hali yozilmagan'):' · xato: '+(t.err||'?');
 return x+' · kirgan '+t.bound+'/'+DATA.total+' · eksponat '+t.items;
}
async function admStatus(){
 const el=$('adst');el.textContent='💾 Baza tekshirilmoqda...';
 try{el.textContent=fmtStatus(await api('/museum/adm',{op:'status'}));}catch(e){el.textContent='💾 Holatni olib bo\'lmadi';}
}
let admData=[];
async function admLoad(){
 const box=$('adl');box.textContent='Yuklanmoqda...';
 try{
  const r=await api('/museum/adm',{op:'list'});if(!r.ok)throw 0;
  admData=r.people;box.innerHTML='';r.people.forEach(p=>box.appendChild(admRow(p)));
 }catch(e){box.textContent='Yuklab bo\'lmadi (faqat egasi uchun).';}
}
function copyText(t){
 try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(()=>toast('📋 Nusxalandi: '+t),()=>toast(t));return;}}catch(_){}
 try{const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('📋 Nusxalandi: '+t);}catch(_){toast(t,6000);}
}
function admRow(p){
 const d=document.createElement('div');d.className='ar';
 d.innerHTML='<div class="ah"><b>№'+p.n+'</b><input class="an" maxlength="30"><button class="b sm" data-a="go">🚪</button></div>'
  +'<div class="ab"><select class="ag"><option value="m">👦 O\'g\'il</option><option value="f">👧 Qiz</option></select><label class="hj"><input type="checkbox" class="ahj"> 🧕 Hijob</label><code class="ac"></code><button class="b sm" data-a="cp">📋</button><button class="b sm" data-a="rg">🔄 Yangi kod</button></div>'
  +'<div class="as"><span class="au"></span><button class="b sm" data-a="ub">⛔ Bog\'lanishni uzish</button></div>';
 const q=s=>d.querySelector(s);
 const fill=()=>{q('.an').value=p.name;q('.ag').value=p.g;q('.ahj').checked=!!p.h;q('.ahj').disabled=p.g!=='f';q('.hj').style.opacity=p.g==='f'?1:.4;q('.ac').textContent=p.code;q('.au').textContent=p.uid?'🟢 kirgan (ID '+p.uid+')':'⚪ hali kirmagan';q('[data-a=ub]').style.display=p.uid?'':'none';};
 fill();
 const call=async(op,extra)=>{try{const r=await api('/museum/adm',Object.assign({op,n:p.n},extra||{}));if(r.ok){p=r.p;fill();toast('✅ Saqlandi');}else{toast('⚠️ '+(r.error||'Xato'));fill();}}catch(e){toast('⚠️ Xato');}};
 q('.an').onchange=e=>call('set',{f:'name',v:e.target.value});
 q('.ag').onchange=e=>call('set',{f:'g',v:e.target.value});
 q('.ahj').onchange=e=>call('set',{f:'h',v:e.target.checked?'1':'0'});
 q('[data-a=go]').onclick=()=>{$('ad').classList.add('hide');goRoom(p.n);};
 q('[data-a=cp]').onclick=()=>copyText(p.name+' — '+p.code);
 q('[data-a=rg]').onclick=()=>call('regen');
 q('[data-a=ub]').onclick=()=>call('unbind');
 return d;
}
$('bOwner').onclick=()=>{$('ad').classList.remove('hide');admLoad();admStatus();};
$('adx').onclick=()=>{$('ad').classList.add('hide');refresh();};
$('adref').onclick=()=>{admLoad();admStatus();};
$('adsend').onclick=async()=>{try{const r=await api('/museum/adm',{op:'send'});toast(r.ok?'📤 Kodlar botga yuborildi':'⚠️ '+(r.error||'Xato'));}catch(e){toast('⚠️ Xato');}};

function postLoad(){
 applyMe();
 const me=DATA.me||{};
 if(DATA.mine){toast('Xush kelibsiz, '+(me.name||'')+'!');twirl();askNav(false);}
 else if(me.owner)toast('👑 Egasi rejimi: «👑 Egasi» tugmasi orqali ismlar va kodlarni boshqaring',4500);
 else openLogin();
}

// ---------- sikl ----------
const _cv=new THREE.Vector3();
function camPos(){
 const ty=P.dy+1.5,hd=P.dist*Math.cos(P.pitch),vt=P.dist*Math.sin(P.pitch),fl=P.y>2.8?1:0,lv=fl?FH:0;
 const sy=Math.sin(P.yaw),cy=Math.cos(P.yaw);
 let t=1;
 for(let k=1;k<=24;k++){
  const tt=k/24,px=P.x+sy*hd*tt,pz=P.z+cy*hd*tt,py=Math.min(Math.max(ty+vt*tt,P.dy+0.5),ceilAt(px,pz,lv)-0.25);
  if(camHit(px,py,pz,fl)){t=Math.max(0,(k-1)/24);break;}
 }
 const qx=P.x+sy*hd*t,qz=P.z+cy*hd*t;
 return [qx,Math.min(Math.max(ty+vt*t,P.dy+0.5),ceilAt(qx,qz,lv)-0.25),qz,fl,t];
}
let last=performance.now();
function update(dt){
 let ix=JV.x,iy=JV.y;
 if(keys['a']||keys['arrowleft'])ix-=1;if(keys['d']||keys['arrowright'])ix+=1;if(keys['w']||keys['arrowup'])iy+=1;if(keys['s']||keys['arrowdown'])iy-=1;
 if(keys['q'])P.yaw+=dt*1.8;if(keys['e'])P.yaw-=dt*1.8;
 const l=Math.hypot(ix,iy);let tx=0,tz=0;
 if(l>0.08){
  const n=Math.min(1,l);ix/=l;iy/=l;
  const s=Math.sin(P.yaw),c=Math.cos(P.yaw);
  const sp=4.3*SPDM*(0.3+0.7*n)*(n>0.93?1.2:1);
  tx=(-s*iy+c*ix)*sp;tz=(-c*iy-s*ix)*sp;
 }
 if(LIFT.riding){tx=0;tz=0;}
 const k=1-Math.exp(-(l>0.08?12:18)*dt);
 P.vx+=(tx-P.vx)*k;P.vz+=(tz-P.vz)*k;
 const spd=Math.hypot(P.vx,P.vz);
 if(spd>0.05&&!LIFT.riding){
  const steps=Math.max(1,Math.ceil(spd*dt/0.18)),sx=P.vx*dt/steps,sz=P.vz*dt/steps;
  for(let i=0;i<steps;i++){const a=tryMove(P.x+sx,P.z),b=tryMove(P.x,P.z+sz);if(!a)P.vx*=0.5;if(!b)P.vz*=0.5;if(!a&&!b)break;}
 }
 const spin=P.spin>0;
 if(spin){const d=Math.min(P.spin,dt*10);P.rot+=d;P.spin-=d;}
 else if(spd>0.5)P.rot=lerpAngle(P.rot,Math.atan2(P.vx,P.vz),1-Math.exp(-16*dt));
 P.walk+=dt*(2+spd*1.6);
 const amp=Math.min(1,spd/3.2)*0.75,sw=Math.sin(P.walk)*amp,U=avatar.userData;
 U.legs[0].rotation.x=sw;U.legs[1].rotation.x=-sw;
 U.arms[0].rotation.x=-sw*0.7;U.arms[1].rotation.x=sw*0.7;
 U.arms[0].rotation.z=spin?-0.9:0;U.arms[1].rotation.z=spin?0.9:0;
 if(U.skirt){const f=spin?1.25:1+Math.min(spd,5)*0.012;U.skirt.scale.set(f,1,f);}
 if(LIFT.riding)liftStep(dt);
 P.dy+=(P.y-P.dy)*(P.snap?1:1-Math.exp(-22*dt));
 const hop=spin?Math.abs(Math.sin(P.spin*1.1))*0.12:0;
 avatar.position.set(P.x,P.dy+hop,P.z);avatar.rotation.y=P.rot;
 // kamera (silliq)
 const ty=P.dy+1.5,cp=camPos(),fl=cp[3];
 _cv.set(cp[0],cp[1],cp[2]);
 if(P.snap)camera.position.copy(_cv);else{camera.position.lerp(_cv,1-Math.exp(-18*dt));if(camHit(camera.position.x,camera.position.y,camera.position.z,fl))camera.position.copy(_cv);}
 if(cp[4]<0.2)camera.lookAt(P.x-Math.sin(P.yaw)*4,ty-Math.sin(P.pitch)*2.2,P.z-Math.cos(P.yaw)*4);else camera.lookAt(P.x,ty,P.z);
 avatar.visible=cp[4]>=0.14;
 P.snap=false;
 navUpdate(performance.now(),dt);ctxUpdate(dt);doorsUpdate(dt);monitorsUpdate(dt);
 readyT-=dt;if(readyT<=0){readyT=0.25;actBtn.classList.toggle('ready',!!nearestItem());}
 $('fl').textContent=P.y<-0.5?'Tashqarida':('Qavat '+(P.y>2.8?2:1));
}
function tick(now){requestAnimationFrame(tick);const dt=Math.min(0.05,(now-last)/1000);last=now;update(dt);renderer.render(scene,camera);}

// ---------- ISHLAYDIGAN MONITORLAR ----------
function buildGallery(data){
 // har bir xonadan avval bittadan rasm, keyin qolganlari (eng ko'pi 14 ta)
 const first=[],rest=[];
 for(const r of (data.rooms||[])){
  const imgs=(r.items||[]).filter(it=>it.type==='image');
  imgs.forEach((it,i)=>{it.rn=r.n;it._room=r.name;(i===0?first:rest).push(it);});
 }
 return first.concat(rest).slice(0,14);
}
function makeMonitor(o){
 const g=new THREE.Group();g.position.set(o.x,o.y,o.z);g.rotation.y=o.rot||0;world.add(g);
 g.add(new THREE.Mesh(new THREE.BoxGeometry(o.w+0.3,o.h+0.3,0.18),new THREE.MeshLambertMaterial({color:0xb99a4a})));
 const cv=document.createElement('canvas');cv.width=o.cw;cv.height=o.ch;
 const tex=new THREE.CanvasTexture(cv);tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=4;
 const pm=new THREE.Mesh(new THREE.PlaneGeometry(o.w,o.h),new THREE.MeshBasicMaterial({map:tex}));pm.position.z=0.1;g.add(pm);
 const m={o,cv,cx:cv.getContext('2d'),tex,pm,items:[],idx:0,t:Math.random()*4,dirty:true,tok:0,pos:new THREE.Vector3(o.x,o.y,o.z)};
 pm.userData.far=o.far||24;
 pm.userData.wp=o.wp?new THREE.Vector3(o.wp[0],o.wp[1],o.wp[2]):new THREE.Vector3(o.x,o.y,o.z);
 monCard(m);clickables.push(pm);monitors.push(m);return m;
}
function monCard(m,l2){
 const {cx,cv,o}=m,w=cv.width,h=cv.height;
 const gr=cx.createLinearGradient(0,0,w,h);gr.addColorStop(0,'#14213d');gr.addColorStop(1,'#315b82');cx.fillStyle=gr;cx.fillRect(0,0,w,h);
 cx.strokeStyle='#e8c85a';cx.lineWidth=Math.max(4,h/45);cx.strokeRect(h*0.05,h*0.05,w-h*0.1,h-h*0.1);
 cx.textAlign='center';cx.textBaseline='middle';cx.fillStyle='#f6d978';
 cx.font='bold '+Math.round(h*0.24)+'px Georgia,serif';cx.fillText('LOG-324',w/2,h*0.38);
 cx.fillStyle='#fff';cx.font='bold '+Math.round(h*0.09)+'px system-ui,sans-serif';cx.fillText(o.title||'',w/2,h*0.65);
 const sub=l2||o.sub||'';if(sub){cx.globalAlpha=0.85;cx.font=Math.round(h*0.065)+'px system-ui,sans-serif';cx.fillText(sub,w/2,h*0.80);cx.globalAlpha=1;}
 m.pm.userData.item=o.emptyItem||{type:'text',cap:'LOG-324 · '+(o.title||'3D Virtual Muzey')+(o.sub?'\n'+o.sub:'')};
 m.tex.needsUpdate=true;
}
function monDraw(m){
 const it=m.items.length?m.items[m.idx%m.items.length]:null;
 if(!it){monCard(m);return;}
 m.pm.userData.item=it;
 const {cx,cv,o}=m,w=cv.width,h=cv.height;
 const bar=(txt)=>{if(!txt)return;const bh=Math.round(h*0.12);cx.fillStyle='rgba(10,14,28,.72)';cx.fillRect(0,h-bh,w,bh);cx.fillStyle='#fff';cx.textAlign='center';cx.textBaseline='middle';cx.font='bold '+Math.round(bh*0.5)+'px system-ui,sans-serif';
  let t=txt;while(cx.measureText(t).width>w-30&&t.length>6)t=t.slice(0,-2);if(t!==txt)t+='…';cx.fillText(t,w/2,h-bh/2);};
 const label=((it._room?it._room+' · ':'')+(it.cap||'')).trim();
 if(it.type==='image'){
  const tok=++m.tok,im=new Image();
  im.onload=()=>{
   if(tok!==m.tok)return;
   cx.fillStyle='#0b1020';cx.fillRect(0,0,w,h);
   const iw=im.naturalWidth||4,ih=im.naturalHeight||3;
   const k=(o.fit==='cover')?Math.max(w/iw,h/ih):Math.min(w/iw,h/ih);
   const dw=iw*k,dh=ih*k;cx.drawImage(im,(w-dw)/2,(h-dh)/2,dw,dh);bar(label);m.tex.needsUpdate=true;
  };
  im.onerror=()=>{};
  im.src=o.hq?it.f:it.u;
 }else if(it.type==='video'){
  monCard(m,'▶ VIDEO'+(it.cap?' · '+it.cap:''));m.pm.userData.item=it;
 }else{
  cx.fillStyle='#f6efdc';cx.fillRect(0,0,w,h);cx.fillStyle='#221b0e';cx.textAlign='left';cx.textBaseline='top';
  const fs=Math.round(h*0.075);cx.font=fs+'px Georgia,serif';
  wrap(cx,it.cap||'',w-60).slice(0,Math.floor((h-40)/(fs*1.25))).forEach((l,i)=>cx.fillText(l,30,24+i*fs*1.25));
  m.tex.needsUpdate=true;
 }
}
function monitorsUpdate(dt){
 for(const m of monitors){
  const d=Math.hypot(P.x-m.pos.x,P.z-m.pos.z)+Math.abs(P.y-m.pos.y)*0.4;
  if(d>(m.o.range||50))continue;
  if(m.items.length>1){m.t-=dt;if(m.t<=0){m.t=6;m.idx++;m.dirty=true;}}
  if(m.dirty){m.dirty=false;monDraw(m);}
 }
}

// ---------- ESHIK KODI oynasi ----------
let lkCtx=null;
function openLock(rn,mode){
 lkCtx={rn,mode};
 const r=(DATA.rooms||[]).find(x=>x.n===rn)||{};
 $('lkt').textContent=mode==='manage'?'🔑 №'+rn+' xona eshik kodi':'🔒 №'+rn+' xona yopiq';
 $('lkp').textContent=mode==='manage'
  ?(r.lockSet?"Kod qo'yilgan. Yangi kod yozsangiz almashadi. Siz va muzey egasi kodsiz kira olasiz.":"Xohlasangiz eshikka kod qo'ying (3–16 belgi). Kodni bilmaganlar xonaga kira olmaydi va eksponatlarni ko'ra olmaydi.")
  :"Bu xona kod bilan yopilgan. Kodni xona egasidan so'rang.";
 $('lkok').textContent=mode==='manage'?'💾 Saqlash':'🔓 Ochish';
 $('lkdel').classList.toggle('hide',!(mode==='manage'&&r.lockSet));
 $('lki').value='';$('lke').textContent='';$('lk').classList.remove('hide');
 setTimeout(()=>{try{$('lki').focus();}catch(_){}},60);
}
async function lkSend(code,remove){
 if(!lkCtx)return;
 const enter=lkCtx.mode==='enter';
 if(!remove&&!code.trim()){$('lke').textContent='Kodni yozing';return;}
 $('lkok').disabled=true;$('lkdel').disabled=true;$('lke').textContent='';
 try{
  const r=await api(enter?'/museum/unlock':'/museum/lock',{n:lkCtx.rn,c:remove?'':code.trim()});
  if(!r.ok){$('lke').textContent=r.msg||'Xato';return;}
  $('lk').classList.add('hide');
  toast(enter?'🔓 Eshik ochildi':('✅ '+(r.msg||'Saqlandi')),2200);
  refresh(false);
 }catch(e){$('lke').textContent='Ulanib bo\'lmadi. Qayta urinib ko\'ring.';}
 finally{$('lkok').disabled=false;$('lkdel').disabled=false;}
}
$('lkok').onclick=()=>lkSend($('lki').value,false);
$('lkdel').onclick=()=>lkSend('',true);
$('lkx').onclick=()=>$('lk').classList.add('hide');
$('lki').addEventListener('keydown',e=>{if(e.key==='Enter')lkSend($('lki').value,false);});

// ---------- ma'lumot ----------
async function fetchData(){
 const r=await fetch('/museum/data',{headers:{'X-Init':(tg&&tg.initData)||'','X-Museum-Session':SESSION_KEY},cache:'no-store'});
 if(r.status===401){let e={};try{e=await r.json();}catch(_){};if(e.error==='code_required'){SESSION_KEY='';throw new Error('code_required');}throw new Error('auth');}
 if(!r.ok)throw new Error('http '+r.status);
 const j=await r.json();if(j&&j.session)SESSION_KEY=j.session;
 return j;
}
let dataSig='';
async function refresh(quiet){
 try{
  const nd=await fetchData();const sg=JSON.stringify([nd.rooms,nd.mine,nd.me]);
  if(quiet===true&&sg===dataSig){DATA=nd;return;}
  dataSig=sg;DATA=nd;buildWorld(DATA);NAV.field=null;applyMe();
 }catch(e){
  if(String(e.message)==='code_required'){
   $('hud').classList.add('hide');$('stick').classList.add('hide');$('act').classList.add('hide');$('spd').classList.add('hide');
   openLogin();$('lge').textContent='🔒 Sessiya tugadi. Davom etish uchun kodingizni qayta kiriting.';
  }else if(quiet!==true)toast('Yangilab bo\'lmadi');
 }
}
setInterval(()=>{if(!document.hidden&&!LIFT.riding&&DATA)refresh(true);},30000);
(async function(){
 try{
  say('Ma\'lumotlar olinmoqda...');DATA=await fetchData();
  say('Muzey qurilmoqda...');await new Promise(r=>setTimeout(r,30));
  buildWorld(DATA);
  postLoad();
  $('load').classList.add('hide');$('hud').classList.remove('hide');$('stick').classList.remove('hide');$('act').classList.remove('hide');$('spd').classList.remove('hide');
  const h=$('hint');h.classList.remove('hide');setTimeout(()=>{h.style.opacity=0;},7000);setTimeout(()=>h.classList.add('hide'),8000);
  requestAnimationFrame(tick);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 }catch(e){
  $('load').classList.add('hide');
  if(String(e.message)==='code_required'){
   openLogin();
   $('lge').textContent='🔒 Kirish uchun shaxsiy kod majburiy. Mehmon rejimi mavjud emas.';
  }else{
   $('load').querySelector('.spin').classList.add('hide');
   $('load').classList.remove('hide');
   say(String(e.message)==='auth'?'Muzeyni Telegram bot ichidagi «🏛 3D Muzey» tugmasi orqali oching.':'Yuklab bo\'lmadi: '+e.message+'. Qayta urinib ko\'ring.');
  }
 }
})();
</script></body></html>
'''
