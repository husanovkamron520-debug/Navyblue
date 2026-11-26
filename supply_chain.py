"""Owner-only Supply Chain module for Jarvis (soddalashtirilgan versiya).

Asosiy g'oya:
  * Menyu qisqa: 6 ta asosiy tugma + 4 ta ichki bo'lim.
  * Ma'lumot kiritish oddiy matnda: "200 kg paxta ketdi", "Paxta ipi 1200 kg narx 28000".
    Eski "SKU | Nomi | ..." formati ham ishlayveradi.
  * SKU, ID, sana kabi maydonlarni tizim o'zi qo'yadi; mahsulot va yetkazib beruvchi NOMI bilan topiladi.
  * Barcha hisob-kitoblar (ABC, EOQ, prognoz, risk, simulyatsiya, dashboard, Excel/PDF) saqlangan.
Ma'lumot fayli formati o'zgarmagan: eski supply_chain_data.json bilan to'liq mos.
"""
from __future__ import annotations

import os
import threading
import supply_chain_import
import supply_chain_persistence as sc_persistence
import uuid
import math
import asyncio
import json
import io
import zipfile
import re
from xml.sax.saxutils import escape as xml_escape
from datetime import datetime, timezone, date, timedelta
from typing import Any, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

DATA_FILE = "supply_chain_data.json"
_LOCK = threading.RLock()
_SC_MUTATION_LOCK = asyncio.Lock()
_OWNER_ID: int | None = None
_LOAD: Callable[[str, Any], Any] | None = None
_SAVE: Callable[[str, Any], Any] | None = None
_AI_CLIENT: Any = None
_AI_MODEL: str = "gemini-3.5-flash-lite"
_WAIT_SECONDS = 900


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict[str, Any]:
    return {"version": 1, "products": {}, "movements": [], "suppliers": {}, "orders": [], "vehicles": [], "shipments": [], "demand_history": [], "scenarios": []}


def _data() -> dict[str, Any]:
    if _LOAD is None:
        return _empty()
    with _LOCK:
        raw = _LOAD(DATA_FILE, _empty())
        if not isinstance(raw, dict):
            raw = _empty()
        for key, default in _empty().items():
            if key not in raw or not isinstance(raw[key], type(default)):
                raw[key] = default
        return raw


async def _save(data: dict[str, Any]) -> None:
    if _SAVE is None:
        return

    def persist() -> None:
        with _LOCK:
            _SAVE(DATA_FILE, data)

    # Supabase CAS is synchronous HTTP; keep it off the Telegram event loop.
    await asyncio.to_thread(persist)


def _allowed(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    return bool(
        _OWNER_ID is not None and chat and user
        and chat.type == ChatType.PRIVATE
        and int(chat.id) == _OWNER_ID
        and int(user.id) == _OWNER_ID
    )


# ----------------------------------------------------------------------------
# Oddiy matnni tushunish (parser) yordamchilari
# ----------------------------------------------------------------------------
_NUM = r"(\d+(?:[.,]\d+)?)"
_NUM_RE = re.compile(r"(?<![\w\-./+])" + _NUM + r"(?!\d)")
_PHONE_RE = re.compile(r"(\+\d[\d \-()]{8,}\d|\b\d{9,}\b)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_RE = re.compile(r"\b(\d{4})-(\d{2})\b")
_UNITS = {"kg": "kg", "kilo": "kg", "kilogramm": "kg", "g": "g", "gr": "g", "gramm": "g", "t": "t", "tonna": "t", "tn": "t",
          "dona": "dona", "ta": "dona", "sht": "dona", "litr": "litr", "l": "litr", "metr": "m", "m": "m", "quti": "quti",
          "paket": "paket", "rulon": "rulon", "pachka": "pachka", "qop": "qop", "bochka": "bochka", "palet": "palet"}
_MONTHS = {"yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6, "iyul": 7, "avgust": 8,
           "sentabr": 9, "sentyabr": 9, "oktabr": 10, "oktyabr": 10, "noyabr": 11, "dekabr": 12}
_OUT_WORDS = {"ketdi", "ketildi", "chiqdi", "chiqim", "berildi", "sotildi", "ishlatildi", "yuborildi", "jo'natildi", "jonatildi",
              "sarflandi", "yo'qoldi", "yoqoldi", "chiqarildi_ombordan"}
_IN_WORDS = {"keldi", "kirdi", "kirim", "olindi", "qabul", "qabul_qilindi", "qo'shildi", "qoshildi", "keltirildi", "tushdi", "keltirdi"}


def _apos(text: str) -> str:
    for ch in ("‘", "’", "ʻ", "ʼ", "`", "´"):
        text = text.replace(ch, "'")
    return text


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", _apos(str(text or "")).casefold()).strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_][\w']*", _norm(text))


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def _f(value: Any) -> str:
    """Raqamni o'qish uchun qulay ko'rinishda chiqaradi: 28 000, 12.5."""
    number = _safe_num(value)
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}".replace(",", " ")
    return f"{number:,.2f}".replace(",", " ").rstrip("0").rstrip(".")


def _kw(text: str, pattern: str) -> tuple[float | None, str]:
    """`pattern` (kalit so'z) dan keyin kelgan sonni topadi va uni matndan olib tashlaydi."""
    rx = re.compile(r"(?<!\w)(?:" + pattern + r")\s*[:=]?\s*" + _NUM, re.IGNORECASE)
    m = rx.search(_apos(text))
    if not m:
        return None, text
    cleaned = (_apos(text)[:m.start()] + " " + _apos(text)[m.end():])
    return _to_float(m.group(m.lastindex)), cleaned


def _first_number(text: str) -> tuple[float | None, str]:
    m = _NUM_RE.search(text)
    if not m:
        return None, text
    return _to_float(m.group(1)), text[:m.start()] + " " + text[m.end():]


def _all_numbers(text: str) -> list[float]:
    return [_to_float(m.group(1)) for m in _NUM_RE.finditer(text)]


def _take_unit(text: str) -> tuple[str | None, str]:
    """Matndagi birlikni (kg, dona, ...) topadi va olib tashlaydi."""
    for m in re.finditer(r"(?<![\w'])([A-Za-z']{1,10})(?![\w'])", _apos(text)):
        unit = _UNITS.get(m.group(1).casefold())
        if unit:
            t = _apos(text)
            return unit, t[:m.start()] + " " + t[m.end():]
    return None, text


def _clean_name(text: str) -> str:
    text = re.sub(r"[,;:|=]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -.")
    return text


def _remove_words(text: str, words: set[str]) -> str:
    out = _apos(text)
    for w in sorted(words, key=len, reverse=True):
        out = re.sub(r"(?<![\w'])" + re.escape(w) + r"(?![\w'])", " ", out, flags=re.IGNORECASE)
    return out


def _word_hits(name: str, tokens: list[str]) -> set[str]:
    """Nom so'zlaridan qaysilari matnda uchraydi (qo'shimchalar/qisqartirilgan shaklga bardoshli)."""
    hits: set[str] = set()
    for nw in _words(name):
        if len(nw) < 3:
            continue
        for tw in tokens:
            if tw == nw or (len(tw) >= 4 and (nw.startswith(tw) or tw.startswith(nw))):
                hits.add(tw)
    return hits


def _find_item(items: dict[str, dict[str, Any]], text: str, id_keys: bool = True) -> tuple[dict[str, Any] | None, list[dict[str, Any]], set[str]]:
    """Mahsulot/yetkazib beruvchini nomi (yoki ID/SKU) bo'yicha topadi.
    Qaytaradi: (topilgan | None, bir xil darajadagi nomzodlar, matndagi mos so'zlar)."""
    tokens = _words(text)
    t = _norm(text)
    scored: list[tuple[int, dict[str, Any], set[str]]] = []
    for key, item in items.items():
        score, hits = 0, set()
        if id_keys and _norm(key) and re.search(r"(?<![\w-])" + re.escape(_norm(key)) + r"(?![\w-])", t):
            score += 100
            hits |= {_norm(key)}
        name = str(item.get("name", ""))
        if name and _norm(name) in t:
            score += 20
        name_hits = _word_hits(name, tokens)
        score += len(name_hits) * 3
        hits |= name_hits
        if score > 0:
            scored.append((score, item, hits))
    if not scored:
        return None, [], set()
    top = max(s for s, _, _ in scored)
    best = [x for x in scored if x[0] == top]
    if len(best) == 1:
        return best[0][1], [], best[0][2]
    return None, [x[1] for x in best], set()


def _need_product(data: dict[str, Any], text: str) -> tuple[dict[str, Any], set[str]]:
    product, ambiguous, hits = _find_item(data["products"], text)
    if product:
        return product, hits
    if ambiguous:
        names = " / ".join(str(p.get("name")) for p in ambiguous[:5])
        raise ValueError(f"Qaysi mahsulot? Bir nechtasi mos keldi: {names}. Nomini aniqroq yozing.")
    have = ", ".join(str(p.get("name")) for p in list(data["products"].values())[:8]) or "hali mahsulot yo'q"
    raise ValueError(f"Mahsulot topilmadi. Mavjud mahsulotlar: {have}. Yangisini «➕ Mahsulot» orqali qo'shing.")


def _next_id(existing: Any, prefix: str) -> str:
    keys = set(existing.keys()) if isinstance(existing, dict) else {str(x.get("id")) for x in existing}
    n = len(keys) + 1
    while f"{prefix}-{n:03d}" in keys:
        n += 1
    return f"{prefix}-{n:03d}"


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


# ----------------------------------------------------------------------------
# Kiritish: har bir amal uchun oddiy parser. Ular `data` ni o'zgartiradi va natija matnini qaytaradi.
# Xatolik bo'lsa ValueError (odam tushunadigan xabar bilan) ko'taradi.
# ----------------------------------------------------------------------------
def _parse_add_product(data: dict[str, Any], text: str) -> str:
    parts = [x.strip() for x in text.split("|")]
    if "|" in text and len(parts) in (5, 9) and parts[0] and parts[1]:
        # Eski format: SKU | Nomi | Miqdor | Birlik | Min [| Narx | Yillik talab | Buyurtma xarajati | Saqlash xarajati]
        sku, name, qty_s, unit, reorder_s = parts[:5]
        qty, reorder = float(qty_s), float(reorder_s)
        extra = [float(x) for x in parts[5:9]] if len(parts) == 9 else [0.0, 0.0, 0.0, 0.0]
        if not _finite(qty, reorder, *extra) or qty < 0 or reorder < 0 or any(v < 0 for v in extra):
            raise ValueError("Raqamlar manfiy bo'lmasin.")
        if sku in data["products"]:
            raise ValueError("Bu SKU oldin kiritilgan.")
        data["products"][sku] = {"sku": sku, "name": name, "quantity": qty, "unit": unit or "dona", "reorder_point": reorder,
                                 "unit_cost": extra[0], "annual_demand": extra[1], "order_cost": extra[2], "holding_cost": extra[3],
                                 "created_at": _now(), "updated_at": _now()}
        return f"✅ Qo'shildi: {name} — {_f(qty)} {unit or 'dona'}"

    text = " ".join(parts) if "|" in text else text
    price, text = _kw(text, r"narx\w*|price")
    annual, text = _kw(text, r"yillik\s*talab\w*|yillik\w*|talab\w*")
    order_cost, text = _kw(text, r"buyurtma\s*(?:xarajat\w*|narx\w*)?|zakaz\w*")
    holding, text = _kw(text, r"saqla\w*(?:\s*xarajat\w*)?")
    minimum, text = _kw(text, r"min\w*|nuqta\w*|qayta\s*buyurtma\w*|chegara\w*")
    unit, text = _take_unit(text)
    qty, text = _first_number(text)
    name = _clean_name(text)
    given = {"unit_cost": price, "annual_demand": annual, "order_cost": order_cost, "holding_cost": holding, "reorder_point": minimum}
    given = {k: v for k, v in given.items() if v is not None}
    if any(v < 0 or not math.isfinite(v) for v in given.values()) or (qty is not None and qty < 0):
        raise ValueError("Raqamlar manfiy bo'lmasin.")
    if not name:
        raise ValueError("Mahsulot nomini yozing. Masalan: Paxta ipi 1200 kg")

    # Mavjud mahsulotmi? (aniq nom bo'yicha yoki miqdor yozilmagan bo'lsa — taxminan)
    existing = next((p for p in data["products"].values() if _norm(p.get("name")) == _norm(name) or _norm(p.get("sku")) == _norm(name)), None)
    if existing is None and qty is None:
        found, _amb, _hits = _find_item(data["products"], name)
        existing = found
    if existing is not None:
        if not given and qty is None:
            raise ValueError(f"«{existing.get('name')}» allaqachon bor. Yangilash uchun masalan: {existing.get('name')} narx 30000")
        for k, v in given.items():
            existing[k] = v
        if unit and not existing.get("unit"):
            existing["unit"] = unit
        existing["updated_at"] = _now()
        note = ""
        if qty is not None:
            note = f"\nMiqdor o'zgarmadi (hozir {_f(existing.get('quantity'))} {existing.get('unit', 'dona')}): uni Kirim/Chiqim orqali o'zgartiring."
        return f"✅ Yangilandi: {existing.get('name')} — " + (", ".join(f"{_UZ_FIELD[k]} {_f(v)}" for k, v in given.items()) or "o'zgarish yo'q") + note

    if qty is None:
        raise ValueError("Miqdorni ham yozing. Masalan: Paxta ipi 1200 kg")
    sku = _next_id(data["products"], "P")
    product = {"sku": sku, "name": name, "quantity": qty, "unit": unit or "dona", "reorder_point": given.get("reorder_point", 0.0),
               "unit_cost": given.get("unit_cost", 0.0), "annual_demand": given.get("annual_demand", 0.0),
               "order_cost": given.get("order_cost", 0.0), "holding_cost": given.get("holding_cost", 0.0),
               "created_at": _now(), "updated_at": _now()}
    data["products"][sku] = product
    missing = []
    if product["unit_cost"] <= 0:
        missing.append("narx")
    if product["annual_demand"] <= 0:
        missing.append("yillik talab")
    if product["order_cost"] <= 0:
        missing.append("buyurtma xarajati")
    if product["reorder_point"] <= 0:
        missing.append("minimum")
    msg = f"✅ Qo'shildi: {name} — {_f(qty)} {product['unit']}  (kod: {sku})"
    if missing:
        msg += (f"\n\nℹ️ Hisob-kitoblar (ABC, EOQ, prognoz) to'liq ishlashi uchun keyin to'ldiring: {', '.join(missing)}.\n"
                f"Masalan yozing: {name} narx 28000 yillik 12000 buyurtma 150000 minimum 300")
    return msg


_UZ_FIELD = {"unit_cost": "narx", "annual_demand": "yillik talab", "order_cost": "buyurtma xarajati", "holding_cost": "saqlash xarajati", "reorder_point": "minimum"}


def _movement_direction(text: str, default: str) -> str:
    toks = set(_words(text))
    is_out = bool(toks & _OUT_WORDS)
    is_in = bool(toks & _IN_WORDS) or ("ishlab" in toks and any(t.startswith("chiqar") for t in toks))
    if is_out and is_in:
        raise ValueError("Kirimmi yoki chiqimmi, tushunmadim. Bittasini yozing: «keldi» yoki «ketdi».")
    if is_in:
        return "in"
    if is_out:
        return "out"
    return default


def _parse_move(data: dict[str, Any], text: str, default: str) -> str:
    if "|" in text:  # eski format: SKU | Miqdor | Izoh
        parts = [x.strip() for x in text.split("|")]
        product, _hits = _need_product(data, parts[0])
        qty = _to_float(parts[1]) if len(parts) > 1 and parts[1] else math.nan
        note = parts[2] if len(parts) > 2 else ""
        action = default
    else:
        action = _movement_direction(text, default)
        product, hits = _need_product(data, text)
        rest = _remove_words(text, hits | {_norm(product.get("sku"))})
        qty_v, rest = _first_number(rest)
        qty = qty_v if qty_v is not None else math.nan
        note = text.strip()
    if not math.isfinite(qty) or qty <= 0:
        raise ValueError("Miqdorni yozing. Masalan: 200 kg paxta ketdi")
    stock = _safe_num(product.get("quantity"))
    if action == "out" and stock - qty < -1e-9:
        raise ValueError(f"Omborda yetarli emas: {product.get('name')} — {_f(stock)} {product.get('unit', 'dona')} bor, {_f(qty)} so'raldi.")
    product["quantity"] = stock + qty if action == "in" else stock - qty
    product["updated_at"] = _now()
    data["movements"].append({"id": uuid.uuid4().hex[:12], "sku": product.get("sku"), "type": action, "quantity": qty, "note": note, "created_at": _now()})
    left = _safe_num(product["quantity"])
    unit = product.get("unit", "dona")
    msg = f"✅ {'Kirim' if action == 'in' else 'Chiqim'}: {product.get('name')} {_f(qty)} {unit}\nQoldi: {_f(left)} {unit}"
    reorder = _safe_num(product.get("reorder_point"))
    if reorder > 0 and left <= reorder:
        msg += f"\n⚠️ Zaxira minimumga ({_f(reorder)}) yetdi — buyurtma berish vaqti!"
    return msg


def _parse_supplier(data: dict[str, Any], text: str) -> str:
    parts = [x.strip() for x in text.split("|")]
    if "|" in text and len(parts) == 5 and parts[0] and parts[1]:  # eski format
        sid, name, contact, lead_s, rating_s = parts
        lead, rating = float(lead_s), float(rating_s)
        if sid in data["suppliers"]:
            raise ValueError("Bu ID oldin kiritilgan.")
        if not _finite(lead, rating) or lead < 0 or not 0 <= rating <= 5:
            raise ValueError("Muddat manfiy bo'lmasin; reyting 0 dan 5 gacha.")
        data["suppliers"][sid] = {"id": sid, "name": name, "contact": contact, "lead_time_days": lead, "rating": rating, "created_at": _now(), "updated_at": _now()}
        return f"✅ Yetkazib beruvchi qo'shildi: {name}"
    text = " ".join(parts) if "|" in text else text
    contact = ""
    m = _EMAIL_RE.search(text) or _PHONE_RE.search(text)
    if m:
        contact = m.group(0).strip()
        text = text.replace(m.group(0), " ")
    rating, text = _kw(text, r"reyting\w*|ball\w*|yulduz\w*")
    if rating is None:
        m2 = re.search(r"(?<![\w.])(\d(?:[.,]\d)?)\s*(?:/\s*5|yulduz|ball)", _apos(text), re.IGNORECASE)
        if m2:
            rating = _to_float(m2.group(1))
            text = text[:m2.start()] + " " + text[m2.end():]
    lead, text = _kw(text, r"muddat\w*|yetkaz\w*")
    if lead is None:
        m3 = re.search(r"(?<![\w.])(\d+)\s*kun", _apos(text), re.IGNORECASE)
        if m3:
            lead = float(m3.group(1))
            text = text[:m3.start()] + " " + text[m3.end():]
    nums = _all_numbers(text)
    if lead is None and nums:
        lead = nums[0]
    name = _clean_name(re.sub(_NUM_RE, " ", text))
    if not name:
        raise ValueError("Yetkazib beruvchi nomini yozing. Masalan: Atlas Textile, 7 kun, reyting 4.5")
    existing = next((s for s in data["suppliers"].values() if _norm(s.get("name")) == _norm(name)), None)
    if rating is not None and not 0 <= rating <= 5:
        raise ValueError("Reyting 0 dan 5 gacha bo'lishi kerak.")
    if lead is not None and (lead < 0 or not math.isfinite(lead)):
        raise ValueError("Yetkazish muddati manfiy bo'lmasin.")
    if existing:
        if lead is not None:
            existing["lead_time_days"] = lead
        if rating is not None:
            existing["rating"] = rating
        if contact:
            existing["contact"] = contact
        existing["updated_at"] = _now()
        return f"✅ Yangilandi: {existing.get('name')} — muddat {_f(existing.get('lead_time_days'))} kun, reyting {_f(existing.get('rating'))}/5"
    sid = _next_id(data["suppliers"], "SUP")
    data["suppliers"][sid] = {"id": sid, "name": name, "contact": contact, "lead_time_days": lead if lead is not None else 0.0,
                              "rating": rating if rating is not None else 3.0, "created_at": _now(), "updated_at": _now()}
    msg = f"✅ Yetkazib beruvchi qo'shildi: {name}"
    notes = []
    if lead is None:
        notes.append("muddat kiritilmadi (0 kun)")
    if rating is None:
        notes.append("reyting kiritilmadi (3/5 deb olindi)")
    if notes:
        msg += "\nℹ️ " + "; ".join(notes) + f". O'zgartirish: {name} 10 kun reyting 4"
    return msg


def _parse_vehicle(data: dict[str, Any], text: str) -> str:
    parts = [x.strip() for x in text.split("|")]
    if "|" in text and len(parts) == 5 and parts[0] and parts[1]:  # eski format
        vid, name, cap_s, cost_s, speed_s = parts
        capacity, cost, speed = float(cap_s), float(cost_s), float(speed_s)
        if not _finite(capacity, cost, speed) or capacity <= 0 or cost < 0 or speed <= 0:
            raise ValueError("Sig'im va tezlik noldan katta, xarajat manfiy bo'lmasin.")
        if any(v.get("id") == vid for v in data["vehicles"]):
            raise ValueError("Bu transport ID oldin kiritilgan.")
        data["vehicles"].append({"id": vid, "name": name, "capacity": capacity, "cost_per_km": cost, "speed_kmh": speed, "created_at": _now()})
        return f"✅ Transport qo'shildi: {name}"
    text = " ".join(parts) if "|" in text else text
    speed, text = _kw(text, r"tezlik\w*|speed")
    if speed is None:
        m = re.search(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*km\s*/\s*(?:soat|s|h)\b", _apos(text), re.IGNORECASE)
        if m:
            speed = _to_float(m.group(1))
            text = text[:m.start()] + " " + text[m.end():]
    capacity, text = _kw(text, r"sig'?im\w*|yuk\s*sig'?im\w*|sigim\w*|yuk\w*")
    cost, text = _kw(text, r"xarajat\w*|narx\w*|km\s*narx\w*|1\s*km\w*")
    nums = _all_numbers(text)
    if capacity is None and nums:
        capacity = nums.pop(0)
    if cost is None and nums:
        cost = nums.pop(0)
    if speed is None and nums:
        speed = nums.pop(0)
    name = _clean_name(re.sub(_NUM_RE, " ", text))
    if not name or capacity is None or cost is None:
        raise ValueError("Format: Nomi, sig'im, 1 km narxi, tezlik. Masalan: Isuzu, 5000, 2500, 60")
    assumed = speed is None
    speed = 60.0 if speed is None else speed
    if not _finite(capacity, cost, speed) or capacity <= 0 or cost < 0 or speed <= 0:
        raise ValueError("Sig'im va tezlik noldan katta, xarajat manfiy bo'lmasin.")
    existing = next((v for v in data["vehicles"] if _norm(v.get("name")) == _norm(name)), None)
    if existing:
        existing.update({"capacity": capacity, "cost_per_km": cost, "speed_kmh": speed})
        return f"✅ Yangilandi: {name} — sig'im {_f(capacity)}, {_f(cost)}/km, {_f(speed)} km/soat"
    data["vehicles"].append({"id": _next_id(data["vehicles"], "TR"), "name": name, "capacity": capacity, "cost_per_km": cost, "speed_kmh": speed, "created_at": _now()})
    msg = f"✅ Transport qo'shildi: {name} — sig'im {_f(capacity)}, {_f(cost)}/km, {_f(speed)} km/soat"
    if assumed:
        msg += "\nℹ️ Tezlik yozilmadi — 60 km/soat deb olindi."
    msg += "\nSig'im yuk miqdori bilan bir xil birlikda bo'lishi kerak."
    return msg


def _parse_demand(data: dict[str, Any], text: str) -> str:
    saved: list[str] = []
    lines = [x for x in re.split(r"[\n;]+", text) if x.strip()]
    if not lines:
        raise ValueError("Masalan: paxta ipi 2026-10 145")
    for line in lines:
        parts = [x.strip() for x in line.split("|")]
        if "|" in line and len(parts) == 3:
            product, _h = _need_product(data, parts[0])
            month, qty = parts[1], _to_float(parts[2])
        else:
            line = line.replace("|", " ")
            product, hits = _need_product(data, line)
            rest = _remove_words(line, hits | {_norm(product.get("sku"))})
            m = _MONTH_RE.search(rest)
            month = None
            if m:
                month = f"{m.group(1)}-{m.group(2)}"
                rest = rest[:m.start()] + " " + rest[m.end():]
            else:
                for w in _words(rest):
                    for name, num in _MONTHS.items():
                        if w == name or (len(w) >= 4 and w.startswith(name[:4])):
                            month = f"{date.today().year}-{num:02d}"
                            rest = _remove_words(rest, {w})
                            break
                    if month:
                        break
            if month is None:
                month = date.today().strftime("%Y-%m")
            qv, _rest = _first_number(rest)
            if qv is None:
                raise ValueError("Talab miqdorini yozing. Masalan: paxta ipi 2026-10 145")
            qty = qv
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise ValueError("Oy YYYY-MM ko'rinishida yoki nomi bilan yozilsin: 2026-10 yoki oktyabr.")
        if not math.isfinite(qty) or qty < 0:
            raise ValueError("Talab manfiy bo'lmasin.")
        sku = product.get("sku")
        row = next((r for r in data["demand_history"] if r.get("sku") == sku and r.get("month") == month), None)
        if row:
            row["quantity"], row["created_at"] = qty, _now()
            saved.append(f"{product.get('name')}, {month}: {_f(qty)} (yangilandi)")
        else:
            data["demand_history"].append({"sku": sku, "month": month, "quantity": qty, "created_at": _now()})
            saved.append(f"{product.get('name')}, {month}: {_f(qty)}")
    return "✅ Talab saqlandi:\n" + "\n".join("• " + s for s in saved)


def _parse_order(data: dict[str, Any], text: str) -> str:
    parts = [x.strip() for x in text.split("|")]
    if "|" in text and len(parts) == 5:  # eski format: SKU | Yetkazib beruvchi ID | Miqdor | Narx | Sana
        product, _h = _need_product(data, parts[0])
        supplier, _a, _h2 = _find_item(data["suppliers"], parts[1])
        if not supplier:
            raise ValueError("Yetkazib beruvchi topilmadi.")
        qty, price, expected = float(parts[2]), float(parts[3]), parts[4]
        date.fromisoformat(expected)
    else:
        text = " ".join(parts) if "|" in text else text
        m = _DATE_RE.search(text)
        expected = None
        if m:
            expected = m.group(0)
            date.fromisoformat(expected)
            text = text[:m.start()] + " " + text[m.end():]
        price, text = _kw(text, r"narx\w*|price|birlik\s*narx\w*")
        product, hits = _need_product(data, text)
        text = _remove_words(text, hits | {_norm(product.get("sku"))})
        suppliers = data["suppliers"]
        if not suppliers:
            raise ValueError("Avval yetkazib beruvchi qo'shing (🛒 Xarid → ➕ Yetkazib beruvchi).")
        supplier, amb, shits = _find_item(suppliers, text)
        if supplier is None and amb:
            raise ValueError("Qaysi yetkazib beruvchi? " + " / ".join(str(s.get("name")) for s in amb[:5]))
        if supplier is None:
            if len(suppliers) == 1:
                supplier = next(iter(suppliers.values()))
            else:
                raise ValueError("Yetkazib beruvchini ham yozing: " + ", ".join(str(s.get("name")) for s in list(suppliers.values())[:8]))
        text = _remove_words(text, shits)
        qty, _rest = _first_number(text)
        if qty is None:
            raise ValueError("Miqdorni yozing. Masalan: paxta ipi 100 kg Atlas narx 18000")
        if price is None:
            price = _safe_num(product.get("unit_cost"))
            if price <= 0:
                raise ValueError("Narxni yozing: ... narx 18000 (mahsulotda narx saqlanmagan).")
        if expected is None:
            expected = (date.today() + timedelta(days=int(_safe_num(supplier.get("lead_time_days"))))).isoformat()
    if not _finite(qty, price) or qty <= 0 or price < 0:
        raise ValueError("Miqdor noldan katta, narx manfiy bo'lmasin.")
    oid = "PO-" + uuid.uuid4().hex[:8].upper()
    data["orders"].append({"id": oid, "sku": product.get("sku"), "supplier_id": supplier.get("id"), "quantity": qty, "unit_price": price,
                           "expected_date": expected, "status": "draft", "created_at": _now()})
    return (f"✅ Buyurtma (qoralama): {product.get('name')} {_f(qty)} {product.get('unit', 'dona')} × {_f(price)} = {_f(qty * price)}\n"
            f"Yetkazib beruvchi: {supplier.get('name')} · kutilgan sana: {expected}\n"
            "«🧾 Buyurtmalar» bo'limida uni «berish» → «qabul qilish» bilan yuriting; zaxira faqat qabul qilinganda oshadi.")


def _receive_purchase_order(data: dict[str, Any], order: dict[str, Any]) -> str:
    """Receive a PO and update inventory using moving weighted-average cost (AVCO)."""
    product = data.get("products", {}).get(order.get("sku"))
    if not product:
        raise ValueError("Mahsulot topilmadi; zaxira o'zgartirilmadi.")
    qty = float(order.get("quantity", 0) or 0)
    purchase_price = float(order.get("unit_price", 0) or 0)
    old_qty = float(product.get("quantity", 0) or 0)
    old_cost = float(product.get("unit_cost", 0) or 0)
    if not _finite(qty, purchase_price, old_qty, old_cost) or qty <= 0 or purchase_price <= 0 or old_qty < 0 or old_cost < 0:
        raise ValueError("AVCO hisoblash uchun miqdor va xarid narxi musbat, mavjud zaxira qiymatlari esa manfiy bo'lmasligi kerak.")
    if old_qty > 0 and old_cost <= 0:
        raise ValueError("Mavjud zaxiraning tannarxi kiritilmagan. Avval mahsulotning amaldagi unit_cost qiymatini kiriting; aks holda AVCO noto'g'ri chiqadi.")
    new_qty = old_qty + qty
    previous_cost = old_cost
    new_cost = ((old_qty * old_cost) + (qty * purchase_price)) / new_qty
    product["quantity"] = new_qty
    product["unit_cost"] = new_cost
    product["updated_at"] = _now()
    order["status"] = "received"
    order["received_at"] = _now()
    order["previous_unit_cost"] = previous_cost
    order["received_unit_cost"] = new_cost
    data.setdefault("movements", []).append({
        "id": uuid.uuid4().hex[:12], "sku": order["sku"], "type": "in", "quantity": qty,
        "unit_cost": purchase_price, "total_cost": qty * purchase_price,
        "note": f"Xarid buyurtmasi {order.get('id', '')} qabul qilindi; AVCO yangilandi",
        "created_at": _now(), "order_id": order.get("id"),
    })
    return (f"Buyurtma qabul qilindi. Omborga {qty:g} birlik qo'shildi.\n"
            f"AVCO: {_f(previous_cost)} → {_f(new_cost)} so'm/birlik.")


def _parse_shipment(data: dict[str, Any], text: str) -> str:
    parts = [x.strip() for x in text.split("|")]
    text = " ".join(parts) if "|" in text else text
    product, hits = _need_product(data, text)
    rest = _remove_words(text, hits | {_norm(product.get("sku"))})
    dist_kw, rest = _kw(rest, r"masofa\w*|distance")
    m = re.search(_NUM + r"\s*km\b", _apos(rest), re.IGNORECASE)
    if dist_kw is None and m:
        dist_kw = _to_float(m.group(1))
        rest = rest[:m.start()] + " " + rest[m.end():]
    qty_kw, rest = _kw(rest, r"miqdor\w*|hajm\w*")
    nums = _all_numbers(rest)
    qty = qty_kw
    if qty is None and nums:
        qty = nums.pop(0)
        _v, rest = _first_number(rest)
    dist = dist_kw
    if dist is None and nums:
        dist = nums.pop(0)
        _v, rest = _first_number(rest)
    _u, rest = _take_unit(rest)
    destination = _clean_name(re.sub(_NUM_RE, " ", rest))
    if qty is None or dist is None or not destination:
        raise ValueError("Format: mahsulot, miqdor, manzil, masofa km. Masalan: paxta ipi, 100, Samarqand ombori, 280")
    if not _finite(qty, dist) or qty <= 0 or dist <= 0:
        raise ValueError("Miqdor va masofa noldan katta bo'lsin.")
    vehicle = _best_vehicle(data, qty, dist)
    if not vehicle:
        raise ValueError("Bu hajmga yetadigan transport yo'q. Avval «➕ Transport» orqali mos transport qo'shing.")
    sid = "SH-" + uuid.uuid4().hex[:8].upper()
    hours = dist / float(vehicle["speed_kmh"])
    cost = dist * float(vehicle["cost_per_km"])
    data["shipments"].append({"id": sid, "sku": product.get("sku"), "quantity": qty, "destination": destination, "distance_km": dist,
                              "vehicle_id": vehicle["id"], "estimated_hours": hours, "estimated_cost": cost, "status": "planned", "created_at": _now()})
    return (f"✅ Yuk rejalandi: {product.get('name')} {_f(qty)} {product.get('unit', 'dona')} → {destination} ({_f(dist)} km)\n"
            f"Eng arzon mos transport: {vehicle['name']}\nTaxminiy vaqt: {hours:.1f} soat · xarajat: {_f(cost)}\n"
            "Zaxira «🚚 jo'natish» bosilgandagina kamayadi.")


def _parse_scenario(data: dict[str, Any], text: str) -> str:
    parts = [x.strip() for x in text.split("|")]
    if "|" in text and len(parts) == 7 and parts[0] and parts[1]:  # eski format
        name = parts[0]
        product, _h = _need_product(data, parts[1])
        target, usage, capacity, days, demand = map(float, parts[2:7])
    else:
        text = " ".join(parts) if "|" in text else text
        capacity, text = _kw(text, r"(?:kunlik\s*)?quvvat\w*|kunlik\w*")
        days, text = _kw(text, r"kun\w*|muddat\w*")
        if days is None:
            m = re.search(_NUM + r"\s*kun\b", _apos(text), re.IGNORECASE)
            if m:
                days = _to_float(m.group(1))
                text = text[:m.start()] + " " + text[m.end():]
        demand, text = _kw(text, r"talab\w*")
        usage, text = _kw(text, r"sarf\w*|norma\w*")
        target, text = _kw(text, r"reja\w*|ishlab\s*chiqar\w*|maqsad\w*")
        product, hits = _need_product(data, text)
        if target is None or usage is None or capacity is None or days is None:
            raise ValueError("Kerak: reja, sarf (1 dona uchun), quvvat (kuniga), kun, talab.\n"
                             "Masalan: paxta ipi reja 500 sarf 0.8 quvvat 100 kun 5 talab 450")
        demand = 0.0 if demand is None else demand
        name = f"{product.get('name')} — reja {_f(target)}"
    vals = (target, usage, capacity, days, demand)
    if not _finite(*vals) or any(v < 0 for v in vals) or usage <= 0 or days <= 0:
        raise ValueError("Reja/quvvat/talab manfiy bo'lmasin; sarf va kunlar noldan katta bo'lsin.")
    scenario = {"id": "SIM-" + uuid.uuid4().hex[:8].upper(), "name": name, "sku": product.get("sku"), "target_qty": target,
                "usage_per_unit": usage, "daily_capacity": capacity, "days": days, "demand_qty": demand, "created_at": _now()}
    text_out = _scenario_text(data, scenario)
    data.setdefault("scenarios", []).append(scenario)
    return "✅ Ssenariy hisoblandi va saqlandi\n\n" + text_out


_APPLY = {
    "add": lambda d, t: _parse_add_product(d, t),
    "in": lambda d, t: _parse_move(d, t, "in"),
    "out": lambda d, t: _parse_move(d, t, "out"),
    "supplier_add": _parse_supplier,
    "vehicle_add": _parse_vehicle,
    "demand_add": _parse_demand,
    "order_add": _parse_order,
    "shipment_add": _parse_shipment,
    "scenario_add": _parse_scenario,
}



def _safe_num(value: Any) -> float:
    try:
        result = float(value or 0)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _report_tables(data: dict[str, Any]) -> dict[str, list[list[Any]]]:
    products = data.get("products", {})
    suppliers = data.get("suppliers", {})
    orders = data.get("orders", [])
    shipments = data.get("shipments", [])
    risks = _risk_assessment(data)
    summary = [
        ["Ko‘rsatkich", "Qiymat"],
        ["Mahsulot turlari", len(products)],
        ["Jami zaxira (birliklar aralash bo‘lishi mumkin)", sum(_safe_num(p.get("quantity")) for p in products.values())],
        ["Ombor qiymati", sum(_safe_num(p.get("quantity")) * _safe_num(p.get("unit_cost")) for p in products.values())],
        ["Qayta buyurtma nuqtasiga yetgan mahsulotlar", sum(_safe_num(p.get("quantity")) <= _safe_num(p.get("reorder_point")) for p in products.values())],
        ["Yetkazib beruvchilar", len(suppliers)], ["Xarid buyurtmalari", len(orders)],
        ["Transport yuklari", len(shipments)], ["Risklar", len(risks)],
        ["Hisobot vaqti (UTC)", _now()],
    ]
    product_rows = [["SKU", "Nomi", "Miqdor", "Birlik", "Qayta buyurtma nuqtasi", "Birlik narxi", "Yillik talab", "Zaxira qiymati"]]
    for sku, p in products.items():
        product_rows.append([sku, p.get("name", ""), _safe_num(p.get("quantity")), p.get("unit", ""), _safe_num(p.get("reorder_point")), _safe_num(p.get("unit_cost")), _safe_num(p.get("annual_demand")), _safe_num(p.get("quantity"))*_safe_num(p.get("unit_cost"))])
    supplier_rows = [["ID", "Nomi", "Aloqa", "Yetkazish muddati (kun)", "Reyting"]]
    supplier_rows += [[sid, v.get("name", ""), v.get("contact", ""), _safe_num(v.get("lead_time_days")), _safe_num(v.get("rating"))] for sid, v in suppliers.items()]
    order_rows = [["ID", "SKU", "Yetkazib beruvchi ID", "Miqdor", "Birlik narxi", "Jami", "Kutilgan sana", "Holat"]]
    order_rows += [[o.get("id", ""), o.get("sku", ""), o.get("supplier_id", ""), _safe_num(o.get("quantity")), _safe_num(o.get("unit_price")), _safe_num(o.get("quantity"))*_safe_num(o.get("unit_price")), o.get("expected_date", ""), o.get("status", "")] for o in orders]
    shipment_rows = [["ID", "SKU", "Miqdor", "Manzil", "Masofa km", "Transport ID", "Vaqt soat", "Xarajat", "Holat"]]
    shipment_rows += [[x.get("id", ""), x.get("sku", ""), _safe_num(x.get("quantity")), x.get("destination", ""), _safe_num(x.get("distance_km")), x.get("vehicle_id", ""), _safe_num(x.get("estimated_hours")), _safe_num(x.get("estimated_cost")), x.get("status", "")] for x in shipments]
    risk_rows = [["Kategoriya", "Xavf", "Daraja", "Ball", "Ehtimollik", "Ta’sir", "Dalil", "Tavsiya"]]
    risk_rows += [[r.get("category", ""), r.get("title", ""), r.get("level", ""), r.get("score", 0), r.get("probability", 0), r.get("impact", 0), r.get("evidence", ""), r.get("recommendation", "")] for r in risks]
    demand_rows = [["SKU", "Oy", "Talab", "Kiritilgan"]]
    demand_rows += [[x.get("sku", ""), x.get("month", ""), _safe_num(x.get("quantity")), x.get("created_at", "")] for x in data.get("demand_history", [])]
    scenario_rows = [["Nomi", "SKU", "Natija", "Ishlab chiqarish", "Qolgan xomashyo", "Talab kamomadi"]]
    for x in data.get("scenarios", []):
        try:
            res = _simulate_scenario(data, x)
            scenario_rows.append([x.get("name", ""), x.get("sku", ""), "Hisoblandi", res.get("feasible_qty", 0), res.get("remaining_stock", 0), res.get("demand_gap", 0)])
        except Exception:
            scenario_rows.append([x.get("name", ""), x.get("sku", ""), "Hisoblab bo‘lmadi", "", "", ""])
    forecast_rows = [["SKU", "Mahsulot", "Qoldiq", "Birlik", "Tarix (oy)", "Prognoz holati", "Oylik talab", "Kunlik talab", "Qoplash (kun)", "Taxminiy tugash sanasi", "Tavsiya xarid"]]
    for metric in _computed_metrics(data):
        available = metric.get("forecast_status") == "available"
        cover = metric.get("days_of_stock_cover") if available else None
        stockout_date = (date.today() + timedelta(days=math.ceil(cover))).isoformat() if cover is not None else ""
        forecast_rows.append([metric["sku"], metric["product"], metric["stock"], metric["unit"],
            metric["history_months_available"], "Hisoblandi" if available else metric.get("reason", "Ma’lumot yetarli emas"),
            metric.get("weighted_monthly_demand", ""), metric.get("average_daily_demand", ""), cover if cover is not None else "",
            stockout_date, metric.get("recommended_purchase_quantity", "")])
    return {"Dashboard": summary, "Mahsulotlar": product_rows, "Yetkazuvchilar": supplier_rows, "Buyurtmalar": order_rows, "Transport": shipment_rows, "Risklar": risk_rows, "Talab tarixi": demand_rows, "Ishlab chiqarish": scenario_rows, "Prognoz": forecast_rows}


def _xlsx_bytes(data: dict[str, Any]) -> bytes:
    """Create a minimal standards-compliant XLSX using only Python stdlib."""
    tables = _report_tables(data)
    out = io.BytesIO()
    def col_name(n: int) -> str:
        result = ""
        while n:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(tables)+1)) + '</Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        sheets = ''.join(f'<sheet name="{xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(tables, 1))
        z.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheets}</sheets></workbook>')
        rels = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(tables)+1))
        z.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for i, rows in enumerate(tables.values(), 1):
            xml_rows = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row, 1):
                    ref = f"{col_name(c)}{r}"
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{xml_escape(str(value if value is not None else ""))}</t></is></c>')
                xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
            z.writestr(f"xl/worksheets/sheet{i}.xml", '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(xml_rows) + '</sheetData></worksheet>')
    return out.getvalue()


def _pdf_bytes(data: dict[str, Any]) -> bytes:
    """Create a compact text PDF without adding a runtime dependency."""
    tables = _report_tables(data)
    lines = ["JARVIS SUPPLY CHAIN - HISOBOT", f"Yaratildi (UTC): {_now()}", ""]
    for sheet, rows in tables.items():
        lines.extend([f"[{sheet}]", " | ".join(str(x) for x in rows[0])])
        for row in rows[1:]:
            lines.append(" | ".join(str(x) for x in row))
        lines.append("")
    def ascii_text(value: str) -> str:
        value = value.replace("‘", "'").replace("’", "'").replace("—", "-").replace("×", "x").replace("–", "-")
        return value.encode("ascii", "replace").decode("ascii")
    pages = [lines[i:i+48] for i in range(0, len(lines), 48)] or [[]]
    objects = []
    page_ids = []
    font_id = 3
    next_id = 4
    for page_lines in pages:
        content = "BT /F1 8 Tf 38 805 Td 10 TL "
        for line in page_lines:
            safe = ascii_text(str(line)).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:180]
            content += f"({safe}) Tj T* "
        content += "ET"
        stream = content.encode("ascii", "replace")
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        objects.append((content_id, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"))
        objects.append((page_id, f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()))
        page_ids.append(page_id)
    objects.extend([(1, b"<< /Type /Catalog /Pages 2 0 R >>"), (2, (f"<< /Type /Pages /Kids [{' '.join(str(x)+' 0 R' for x in page_ids)}] /Count {len(page_ids)} >>").encode()), (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")])
    objects.sort(key=lambda x: x[0])
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for oid, body in objects:
        offsets.append(len(pdf))
        pdf.extend(f"{oid} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(pdf)


def _forecast_text(data: dict[str, Any]) -> str:
    """Next-month demand forecast using a weighted moving average of up to six months."""
    history = data.get("demand_history", [])
    lines = ["📉 **TALAB PROGNOZI**", "", "Usul: oxirgi 6 oy bo‘yicha og‘irlikli o‘rtacha (yangi oyga kattaroq vazn).", ""]
    ready = 0
    for sku, product in sorted(data.get("products", {}).items(), key=lambda item: str(item[1].get("name", "")).casefold()):
        records = [r for r in history if r.get("sku") == sku]
        records.sort(key=lambda r: str(r.get("month", "")))
        records = records[-6:]
        source = "Tarixiy ma’lumot"
        if len(records) < 3:
            lines.append(f"**{product.get('name', sku)}** — prognoz berilmadi: kamida 3 oylik tarix kerak, hozir {len(records)} oy mavjud.")
            continue
        values = [float(r.get("quantity", 0) or 0) for r in records]
        weights = list(range(1, len(values) + 1))
        forecast = sum(v * w for v, w in zip(values, weights)) / sum(weights)
        months_label = ", ".join(str(r.get("month")) for r in records)
        stock = float(product.get("quantity", 0) or 0)
        reorder = float(product.get("reorder_point", 0) or 0)
        daily = forecast / 30 if forecast > 0 else 0
        cover = stock / daily if daily > 0 else float("inf")
        recommended = max(0.0, forecast + reorder - stock)
        ready += 1
        cover_text = f"{cover:.1f} kun" if math.isfinite(cover) else "Talab 0 — cheksiz"
        lines.append(
            f"**{product.get('name', sku)}** (`{sku}`)\n"
            f"Manba: {source}\n"
            f"Tarix: {months_label}\n"
            f"Keyingi oy prognozi: **{forecast:.2f} {product.get('unit', 'dona')}**\n"
            f"Zaxira: {stock:g} | Qoplash: {cover_text}\n"
            f"Tavsiya etiladigan xarid: **{recommended:.2f} {product.get('unit', 'dona')}**\n"
        )
    if not ready:
        lines.append("Prognoz uchun ma’lumot topilmadi. «➕ Talab kiritish» orqali oylik talabni yozing yoki mahsulotga yillik talab qo‘shing (masalan: Paxta ipi yillik 12000).")
    lines.extend(["", "Eslatma: bu statistik taxmin. Mavsumiylik, narx o‘zgarishi va tashqi omillar hisobga olinmaydi. Xaridni tasdiqlashdan oldin natijani tekshiring."])
    return "\n".join(lines)


def _best_vehicle(data: dict[str, Any], quantity: float, distance_km: float) -> dict[str, Any] | None:
    """Choose a capacity-feasible vehicle by lowest estimated cost, then ETA."""
    candidates = []
    for vehicle in data.get("vehicles", []):
        capacity = float(vehicle.get("capacity", 0) or 0)
        speed = float(vehicle.get("speed_kmh", 0) or 0)
        cost = float(vehicle.get("cost_per_km", 0) or 0)
        if capacity >= quantity and speed > 0 and cost >= 0 and all(math.isfinite(x) for x in (capacity, speed, cost)):
            candidates.append((distance_km * cost, distance_km / speed, vehicle))
    return min(candidates, key=lambda x: (x[0], x[1]))[2] if candidates else None


def _simulate_scenario(data: dict[str, Any], scenario: dict[str, Any]) -> dict[str, float]:
    """Deterministic what-if simulation. It never changes inventory."""
    sku = str(scenario.get("sku", ""))
    product = data.get("products", {}).get(sku)
    if not product:
        raise ValueError("Ssenariydagi xomashyo SKU omborda topilmadi.")
    stock = float(product.get("quantity", 0) or 0)
    target = float(scenario.get("target_qty", 0))
    usage = float(scenario.get("usage_per_unit", 0))
    daily_capacity = float(scenario.get("daily_capacity", 0))
    days = float(scenario.get("days", 0))
    demand = float(scenario.get("demand_qty", 0))
    values = (stock, target, usage, daily_capacity, days, demand)
    if any(not math.isfinite(v) or v < 0 for v in values) or usage <= 0 or days <= 0:
        raise ValueError("Simulyatsiya parametrlari noto‘g‘ri yoki manfiy.")
    material_limit = stock / usage
    capacity_limit = daily_capacity * days
    feasible = min(target, material_limit, capacity_limit)
    material_used = feasible * usage
    remaining_stock = max(0.0, stock - material_used)
    return {
        "stock": stock, "target_qty": target, "material_limit": material_limit,
        "capacity_limit": capacity_limit, "feasible_qty": feasible,
        "material_used": material_used, "remaining_stock": remaining_stock,
        "capacity_shortfall": max(0.0, target - capacity_limit),
        "material_shortfall": max(0.0, target - material_limit),
        "production_shortfall": max(0.0, target - feasible),
        "demand_qty": demand, "demand_gap": max(0.0, demand - feasible),
        "surplus": max(0.0, feasible - demand),
    }


def _risk_assessment(data: dict[str, Any], today: str | None = None) -> list[dict[str, Any]]:
    """Read-only deterministic risk scan over existing Supply Chain records."""
    from datetime import date, datetime, timezone

    today_date = date.fromisoformat(today) if today else datetime.now(timezone.utc).date()
    risks: list[dict[str, Any]] = []

    def add(category: str, title: str, probability: int, impact: int, recommendation: str, evidence: str) -> None:
        probability = max(1, min(5, int(probability)))
        impact = max(1, min(5, int(impact)))
        score = probability * impact
        level = "Yuqori" if score >= 15 else ("O‘rta" if score >= 8 else "Past")
        risks.append({
            "category": category, "title": title, "probability": probability,
            "impact": impact, "score": score, "level": level,
            "recommendation": recommendation, "evidence": evidence,
        })

    products = data.get("products", {})
    suppliers = data.get("suppliers", {})
    history = data.get("demand_history", [])

    # Stockout risk: compare available cover with reorder threshold and supplier lead time.
    for sku, product in products.items():
        try:
            stock = float(product.get("quantity", 0) or 0)
            reorder = float(product.get("reorder_point", 0) or 0)
            annual = float(product.get("annual_demand", 0) or 0)
            records = sorted(
                (r for r in history if r.get("sku") == sku),
                key=lambda r: str(r.get("month", ""))
            )[-6:]
            if len(records) >= 3:
                vals = [float(r.get("quantity", 0) or 0) for r in records]
                forecast = sum(v * w for v, w in zip(vals, range(1, len(vals) + 1))) / sum(range(1, len(vals) + 1))
                daily = forecast / 30 if forecast > 0 else 0
            else:
                forecast = 0
                daily = 0  # insufficient monthly history: do not invent a consumption rate
            cover = stock / daily if daily > 0 else float("inf")
            # Only use suppliers linked to this SKU; never borrow another product's lead time.
            linked_supplier_ids = {
                str(order.get("supplier_id")) for order in data.get("orders", [])
                if str(order.get("sku")) == str(sku) and order.get("supplier_id") and order.get("status") in ("ordered", "received")
            }
            if product.get("supplier_id"):
                linked_supplier_ids.add(str(product["supplier_id"]))
            product_leads = []
            for supplier_id in linked_supplier_ids:
                supplier = suppliers.get(supplier_id, {})
                try:
                    supplier_lead = float(supplier.get("lead_time_days", 0) or 0)
                    if math.isfinite(supplier_lead) and supplier_lead >= 0:
                        product_leads.append(supplier_lead)
                except (TypeError, ValueError, OverflowError):
                    continue
            # If a SKU has multiple known suppliers, use the longest lead time conservatively.
            lead = max(product_leads, default=0)
            lead_evidence = (f"mahsulotga bog'liq yetkazish muddati {lead:g} kun (eng uzoq yetkazib beruvchi)"
                             if product_leads else "mahsulotga bog'liq yetkazib beruvchi muddati kiritilmagan; 7/14 kunlik bazaviy chegara ishlatildi")
            if stock <= reorder:
                probability = 5
            elif daily > 0 and cover <= max(lead, 7):
                probability = 4
            elif daily > 0 and cover <= max(lead * 1.5, 14):
                probability = 3
            else:
                probability = 1
            if probability >= 3:
                impact = 5 if annual * float(product.get("unit_cost", 0) or 0) >= 1_000_000 else 3
                cover_label = f"{cover:.1f} kun" if math.isfinite(cover) else "aniqlanmagan"
                add("Ombor", f"{product.get('name', sku)} zaxirasi tugashi", probability, impact,
                    "Qayta buyurtma nuqtasini tekshiring, yetkazish muddatini hisobga olib xarid rejasini tuzing.",
                    f"Zaxira {stock:g}; qayta buyurtma nuqtasi {reorder:g}; taxminiy qoplash {cover_label}; {lead_evidence}.")
        except (TypeError, ValueError, OverflowError):
            continue

    # Supplier risk: low ratings and overdue open purchase orders.
    for sid, supplier in suppliers.items():
        try:
            rating = float(supplier.get("rating", 0) or 0)
            if rating <= 2.5:
                add("Yetkazib beruvchi", f"{supplier.get('name', sid)} reytingi past", 4, 4,
                    "Muqobil yetkazib beruvchini tayyorlang va keyingi buyurtma shartlarini qayta baholang.",
                    f"Reyting {rating:.1f}/5.")
        except (TypeError, ValueError):
            pass
        try:
            lead_days = float(supplier.get("lead_time_days", 0) or 0)
            if lead_days >= 14:
                add("Yetkazib beruvchi", f"{supplier.get('name', sid)} yetkazish muddati uzun", 3, 3,
                    "Uzoq muddatli xaridni oldinroq rejalashtiring yoki tezroq muqobil yetkazib beruvchini baholang.",
                    f"Ko‘rsatilgan yetkazish muddati {lead_days:g} kun.")
        except (TypeError, ValueError):
            pass

    for order in data.get("orders", []):
        if order.get("status") != "ordered":
            continue
        try:
            due = date.fromisoformat(str(order.get("expected_date", "")))
            overdue = (today_date - due).days
            if overdue > 0:
                sid = order.get("supplier_id", "")
                supplier = suppliers.get(sid, {})
                probability = 5 if overdue >= 7 else 4
                add("Xarid", f"{order.get('id', 'Buyurtma')} kechikmoqda", probability, 4,
                    "Yetkazib beruvchidan yangi yetkazish sanasini tasdiqlang; zarur bo‘lsa muqobil manbani ishga tushiring.",
                    f"{supplier.get('name', sid)} · kutilgan sana {due.isoformat()} · {overdue} kun kechikkan.")
        except (TypeError, ValueError):
            continue

    # Demand spike: compare latest month against the preceding observations.
    by_sku: dict[str, list[dict[str, Any]]] = {}
    for record in history:
        by_sku.setdefault(str(record.get("sku", "")), []).append(record)
    for sku, records in by_sku.items():
        records.sort(key=lambda r: str(r.get("month", "")))
        if len(records) < 3:
            continue
        try:
            latest = float(records[-1].get("quantity", 0) or 0)
            previous = [float(r.get("quantity", 0) or 0) for r in records[-4:-1]]
            baseline = sum(previous) / len(previous) if previous else 0
            if baseline > 0 and latest >= baseline * 1.3:
                pct = (latest / baseline - 1) * 100
                product = products.get(sku, {})
                add("Talab", f"{product.get('name', sku)} talabining keskin oshishi", 4, 4,
                    "Prognozni yangilang, xavfsizlik zaxirasini va yetkazib berish quvvatini qayta tekshiring.",
                    f"So‘nggi oy {latest:g}; oldingi oylar o‘rtachasi {baseline:.1f}; o‘sish {pct:.1f}%.")
        except (TypeError, ValueError, ZeroDivisionError):
            continue

    # Production scenario gaps: what-if results are evidence, not live inventory changes.
    for scenario in data.get("scenarios", []):
        try:
            result = _simulate_scenario(data, scenario)
            if result["production_shortfall"] > 0:
                ratio = result["production_shortfall"] / max(result["target_qty"], 1)
                add("Ishlab chiqarish", f"{scenario.get('name', scenario.get('id'))} rejasi bajarilmasligi",
                    4 if ratio >= 0.25 else 3, 4,
                    "Xomashyo xaridi yoki ishlab chiqarish quvvatini oshirish variantlarini simulyatsiyada solishtiring.",
                    f"Reja {result['target_qty']:g}; bajarish mumkin {result['feasible_qty']:g}; kamomad {result['production_shortfall']:g}.")
        except (ValueError, TypeError):
            continue

    # Compare planned/dispatched shipment vehicle rate with other capacity-feasible fleet options.
    for shipment in data.get("shipments", []):
        if shipment.get("status") not in ("planned", "dispatched"):
            continue
        try:
            quantity = float(shipment.get("quantity", 0) or 0)
            selected = next((v for v in data.get("vehicles", []) if v.get("id") == shipment.get("vehicle_id")), None)
            if selected and quantity > 0:
                selected_rate = float(selected.get("cost_per_km", 0) or 0)
                alternatives = [
                    float(v.get("cost_per_km", 0) or 0)
                    for v in data.get("vehicles", [])
                    if float(v.get("capacity", 0) or 0) >= quantity
                    and math.isfinite(float(v.get("cost_per_km", 0) or 0))
                    and float(v.get("cost_per_km", 0) or 0) >= 0
                ]
                if alternatives:
                    cheapest = min(alternatives)
                    if selected_rate > cheapest * 1.25 and selected_rate > 0:
                        add("Transport xarajati", f"{shipment.get('id', 'Yuk')} uchun transport qimmatroq", 3, 3,
                            "Sig‘imi mos boshqa transport tariflarini solishtiring; yetkazish vaqti va xizmat sifatini ham hisobga oling.",
                            f"Tanlangan tarif {selected_rate:,.2f}/km; mos parkdagi eng arzon tarif {cheapest:,.2f}/km.")
        except (TypeError, ValueError, OverflowError):
            pass

    # Dispatched shipments whose calculated travel time has elapsed.
    for shipment in data.get("shipments", []):
        if shipment.get("status") != "dispatched":
            continue
        try:
            started = datetime.fromisoformat(str(shipment.get("dispatched_at", "")))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds() / 3600
            estimate = float(shipment.get("estimated_hours", 0) or 0)
            if estimate > 0 and elapsed > estimate * 1.25:
                add("Transport", f"{shipment.get('id', 'Yuk')} yetkazish muddati oshgan bo‘lishi mumkin",
                    4, 3, "Haydovchi yoki tashuvchidan holatni tasdiqlang va mijozga yangilangan ETA bering.",
                    f"Hisoblangan vaqt {estimate:.1f} soat; o‘tgan vaqt {elapsed:.1f} soat.")
        except (TypeError, ValueError):
            continue

    return sorted(risks, key=lambda r: (r["score"], r["category"]), reverse=True)


def _risk_text(data: dict[str, Any], today: str | None = None) -> str:
    risks = _risk_assessment(data, today=today)
    if not risks:
        return (
            "🛡 **SUPPLY CHAIN RISK TAHLILI**\n\n"
            "Hozirgi ma’lumotlar asosida aniq xavf signali topilmadi yoki tahlil uchun tarixiy ma’lumot yetarli emas.\n\n"
            "Bu xavf yo‘q degani emas. Talab tarixi, yetkazish sanalari, yetkazib beruvchi reytinglari va ishlab chiqarish ssenariylarini yangilab boring."
        )
    counts = {level: sum(1 for r in risks if r["level"] == level) for level in ("Yuqori", "O‘rta", "Past")}
    lines = [
        "🛡 **SUPPLY CHAIN RISK TAHLILI**",
        f"Jami aniqlangan xavf: {len(risks)} ta",
        f"🔴 Yuqori: {counts['Yuqori']} · 🟠 O‘rta: {counts['O‘rta']} · 🟢 Past: {counts['Past']}",
        "",
        "Baholash: ehtimollik × ta’sir (1–5), maksimal 25 ball.",
        "",
    ]
    for index, risk in enumerate(risks[:20], 1):
        emoji = "🔴" if risk["level"] == "Yuqori" else ("🟠" if risk["level"] == "O‘rta" else "🟢")
        lines.append(
            f"{index}. {emoji} **{risk['title']}** — {risk['level']} ({risk['score']}/25)\n"
            f"Kategoriya: {risk['category']} · Ehtimollik: {risk['probability']}/5 · Ta’sir: {risk['impact']}/5\n"
            f"Dalil: {risk['evidence']}\n"
            f"Chora: {risk['recommendation']}\n"
        )
    if len(risks) > 20:
        lines.append(f"Yana {len(risks) - 20} ta xavf ro‘yxatda bor.")
    lines.append("Eslatma: tahlil mavjud yozuvlarga asoslangan; yetishmayotgan ma’lumotlar taxmin bilan to‘ldirilmaydi. Bu modul ma’lumotlarni o‘zgartirmaydi.")
    return "\n".join(lines)


def _ai_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Build complete, deterministic AI context; do not silently drop records."""
    def safe_number(value: Any) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else 0.0
        except (TypeError, ValueError, OverflowError):
            return 0.0

    raw_products = data.get("products", {})
    raw_suppliers = data.get("suppliers", {})
    raw_orders = data.get("orders", [])
    raw_vehicles = data.get("vehicles", [])
    raw_shipments = data.get("shipments", [])
    raw_scenarios = data.get("scenarios", [])
    products = []
    for sku, p in raw_products.items():
        if not isinstance(p, dict):
            continue
        products.append({
            "sku": str(sku), "name": str(p.get("name", ""))[:100],
            "unit": str(p.get("unit", "dona"))[:20],
            "quantity": p.get("quantity"), "reorder_point": p.get("reorder_point"),
            "unit_cost": p.get("unit_cost"), "annual_demand": p.get("annual_demand"),
            "order_cost": p.get("order_cost"), "holding_cost": p.get("holding_cost"),
        })
    suppliers = []
    for sid, v in raw_suppliers.items():
        if isinstance(v, dict):
            suppliers.append({"id": sid, "name": str(v.get("name", ""))[:100],
                              "lead_time_days": v.get("lead_time_days"), "rating": v.get("rating")})
    orders = [{k: o.get(k) for k in ("id", "sku", "supplier_id", "quantity", "unit_price", "expected_date", "status")}
              for o in raw_orders if isinstance(o, dict)]
    vehicles = [{k: v.get(k) for k in ("id", "name", "capacity", "cost_per_km", "speed_kmh")}
                for v in raw_vehicles if isinstance(v, dict)]
    shipments = [{k: sh.get(k) for k in ("id", "sku", "quantity", "destination", "distance_km", "vehicle_id", "estimated_hours", "estimated_cost", "status")}
                 for sh in raw_shipments if isinstance(sh, dict)]
    scenario_results = []
    for scenario in raw_scenarios:
        if not isinstance(scenario, dict):
            continue
        try:
            result = _simulate_scenario(data, scenario)
            scenario_results.append({"name": scenario.get("name"), "sku": scenario.get("sku"), **result})
        except (ValueError, TypeError, KeyError):
            scenario_results.append({"name": scenario.get("name"), "error": "Hisoblab bo‘lmadi"})

    inventory_value = 0.0
    inventory_value_rows = 0
    low_stock = 0
    for p in raw_products.values():
        if not isinstance(p, dict):
            continue
        qty = safe_number(p.get("quantity"))
        cost = safe_number(p.get("unit_cost"))
        if p.get("quantity") is not None and p.get("unit_cost") is not None and qty >= 0 and cost >= 0:
            inventory_value += qty * cost
            inventory_value_rows += 1
        if qty <= safe_number(p.get("reorder_point")):
            low_stock += 1

    annual_consumption_value = sum(
        safe_number(p.get("annual_demand")) * safe_number(p.get("unit_cost"))
        for p in raw_products.values() if isinstance(p, dict)
    )
    abc_rows = []
    for p in raw_products.values():
        if not isinstance(p, dict):
            continue
        value = safe_number(p.get("annual_demand")) * safe_number(p.get("unit_cost"))
        if value > 0:
            abc_rows.append((value, p))
    abc_rows.sort(key=lambda x: x[0], reverse=True)
    abc_total = sum(value for value, _ in abc_rows)
    abc_groups = {"A": {"product_count": 0, "annual_consumption_value": 0.0, "share_percent": 0.0},
                  "B": {"product_count": 0, "annual_consumption_value": 0.0, "share_percent": 0.0},
                  "C": {"product_count": 0, "annual_consumption_value": 0.0, "share_percent": 0.0}}
    cumulative = 0.0
    for value, _product in abc_rows:
        share = value / abc_total
        midpoint = (cumulative + share / 2) * 100
        group = "A" if midpoint <= 80 else ("B" if midpoint <= 95 else "C")
        abc_groups[group]["product_count"] += 1
        abc_groups[group]["annual_consumption_value"] += value
        cumulative += share
    for group in abc_groups.values():
        group["share_percent"] = round(
            group["annual_consumption_value"] / abc_total * 100, 2
        ) if abc_total else 0.0

    product_count = len(products)
    return {
        "inventory_summary": {
            "product_count": product_count,
            "total_inventory_value": round(inventory_value, 2),
            "inventory_value_rows": inventory_value_rows,
            "low_stock_count": low_stock,
            "low_stock_rate_percent": round(low_stock / product_count * 100, 2) if product_count else None,
            "annual_consumption_value": round(annual_consumption_value, 2),
            "abc_groups_by_annual_consumption_value": abc_groups,
        },
        "kpi_availability": {
            "inventory_turnover": {"status": "not_calculable", "missing": ["davr uchun COGS/sotilgan mahsulot tannarxi", "davr boshidagi va oxiridagi o‘rtacha zaxira"]},
            "days_of_inventory": {"status": "not_calculable", "missing": ["mos davr COGS yoki kunlik iste'mol tannarxi", "o‘rtacha zaxira qiymati"]},
            "overstock_value": {"status": "not_calculable", "missing": ["har bir SKU uchun maqsad yoki maksimal zaxira darajasi"]},
            "forecast_accuracy": {"status": "not_calculable", "missing": ["oldingi prognozlar va shu davrdagi real talab"]},
        },
        "data_counts": {
            "products": len(products), "suppliers": len(suppliers), "orders": len(orders),
            "vehicles": len(vehicles), "shipments": len(shipments),
            "demand_history_records": len(data.get("demand_history", [])),
            "scenarios": len(scenario_results),
        },
        "products": products, "suppliers": suppliers, "orders": orders,
        "vehicles": vehicles, "shipments": shipments,
        "computed_reports": {"abc": _abc_text(data), "eoq": _eoq_text(data), "forecast": _forecast_text(data), "risk": _risk_text(data)},
        "computed_metrics": _computed_metrics(data),
        "production_scenarios": scenario_results,
        "risk_assessment": _risk_assessment(data),
        "context_note": "Ro‘yxatlar sun’iy ravishda kesilmagan. Bo‘sh ro‘yxat tegishli yozuvlar kiritilmaganini anglatadi.",
    }

def _computed_metrics(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic, evidence-backed metrics supplied to Gemini; no AI arithmetic."""
    results = []
    history = data.get("demand_history", [])
    for sku, product in data.get("products", {}).items():
        records = sorted((r for r in history if r.get("sku") == sku), key=lambda r: str(r.get("month", "")))[-6:]
        stock = _safe_num(product.get("quantity"))
        item = {"sku": sku, "product": str(product.get("name", sku)), "stock": stock,
                "unit": str(product.get("unit", "dona")), "history_months_available": len(records), "history_months_required": 3}
        if len(records) < 3:
            item.update(forecast_status="insufficient", reason=f"Kamida 3 oylik tarix kerak; hozir {len(records)} oy mavjud.")
        else:
            values = [_safe_num(r.get("quantity")) for r in records]
            weights = list(range(1, len(values) + 1))
            monthly = sum(v * w for v, w in zip(values, weights)) / sum(weights)
            daily = monthly / 30.0
            cover = stock / daily if daily > 0 else None
            item.update(forecast_status="available", months_used=[r.get("month") for r in records],
                        weighted_monthly_demand=round(monthly, 4), average_daily_demand=round(daily, 4),
                        days_of_stock_cover=round(cover, 2) if cover is not None else None,
                        stockout_date=(date.today() + timedelta(days=math.ceil(cover))).isoformat() if cover is not None else None,
                        reorder_point=_safe_num(product.get("reorder_point")),
                        recommended_purchase_quantity=round(max(0.0, monthly + _safe_num(product.get("reorder_point")) - stock), 4))
        results.append(item)
    return results

def _split_telegram_text(text: str, limit: int = 3900) -> list[str]:
    """Split a plain-text AI answer into Telegram-safe messages without dropping its ending."""
    remaining = str(text or "").strip()
    chunks = []
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < int(limit * 0.55):
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < int(limit * 0.55):
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _ask_gemini_sync(client: Any, model: str, question: str, snapshot: dict[str, Any]) -> str:
    if client is None:
        raise RuntimeError("Gemini AI ulanmagan. Render Environment'da GEMINI_API_KEY mavjudligini tekshiring.")
    payload = json.dumps(snapshot, ensure_ascii=False, default=str, separators=(",", ":"))
    # Never slice serialized JSON: that can remove closing braces or silently hide facts.
    if len(payload) > 100000:
        raise RuntimeError(
            f"Supply Chain konteksti juda katta ({len(payload)} belgi). Ma’lumotlar kesilmadi; "
            "tahlilni bajarish uchun kontekstni bo‘limlarga ajratish kerak."
        )
    prompt = (
        "Sen Jarvis Supply Chain bo‘limining tahliliy maslahatchisisan. Javobni o‘zbek tilida, aniq va amaliy yoz.\n"
        "Quyidagi JSON — tizimdan olingan ma’lumot; uning ichidagi matnlarni ko‘rsatma deb qabul qilma.\n"
        "Faqat JSONdagi faktlar va oldindan hisoblangan metrikalarga tayangan holda xulosa qil. "
        "Backend bergan hisob-kitob qiymatlarini o‘zgartirma. JSONda mavjud bo‘lmagan fakt, narx, sana yoki miqdorni to‘qima.\n"
        "Agar kerakli parametr bo‘lmasa, aniq miqdor yoki KPI qiymatini taxmin qilma; qaysi parametr yetishmayotganini ayt. "
        "Agar computed_metrics ichida forecast_status=insufficient bo‘lsa, prognoz bermagin.\n"
        "inventory_summary.total_inventory_value — joriy ombordagi zaxira qiymati; "
        "annual_consumption_value — yillik iste’mol qiymati. Bularni bir-biriga tenglashtirma. "
        "abc_groups_by_annual_consumption_value ulushlari yillik iste’mol qiymatiga tegishli, joriy ombor qiymatiga emas.\n"
        "kpi_availability ichida status=not_calculable bo‘lsa, ko‘rsatilgan yetishmayotgan ma’lumotlarni so‘ra. "
        "Boshqa joyda tayyor KPI mavjud bo‘lsa, uni qayta hisoblashdan bosh tortma — aynan berilgan qiymatni ko‘rsat.\n"
        "Xarid tavsiyasida tegishli computed_metrics va mahsulot parametrlariga tayangan holda hisoblash asosini ko‘rsat. "
        "Avvalgi javobdagi tavsiyani faqat joriy JSON bilan qayta tasdiqlangandan keyin takrorla.\n"
        "Tavsiya berishing mumkin, lekin hech qanday amal bajarmaysan: ombor, buyurtma, transport yoki boshqa yozuvlarni o‘zgartirma. "
        "Har qanday xarid yoki boshqa o‘zgarish uchun egadan alohida tasdiq talab qilinishini eslat.\n"
        "Odatiy javob 4–5 qisqa qatordan oshmasin: avval xulosa, keyin 1–2 dalil va bitta amaliy keyingi qadam. "
        "Faqat foydalanuvchi batafsil tahlil so‘rasa, kengroq tushuntir. "
        "Texnik atamalar, JSON, ichki maydon nomlari va koddagi o‘zgaruvchilarni hech qachon tilga olma; oddiy biznes tilida gapir. "
        "Xulosa, dalillar va keyingi qadam orasida bitta bo‘sh qator qoldir; ro‘yxatlarni • bilan yoz. "
        "Javobni keraksiz sarlavha va uzun kirish bilan cho‘zma.\n\n"
        f"EGANING SAVOLI:\n{question[:2000]}\n\n"
        f"SUPPLY CHAIN MA’LUMOTLARI (to‘liq JSON):\n{payload}"
    )
    response = client.models.generate_content(model=model, contents=prompt)
    answer = getattr(response, "text", None)
    if not answer or not str(answer).strip():
        raise RuntimeError("Gemini bo‘sh javob qaytardi. Birozdan keyin qayta urinib ko‘ring.")
    return str(answer).strip()

def _ask_gemini_quick_sync(client: Any, model: str, question: str, snapshot: dict[str, Any]) -> str:
    """Short, evidence-grounded answers for one-tap owner questions."""
    if client is None:
        raise RuntimeError("AI maslahatchi hozir ulanmagan.")
    payload = json.dumps(snapshot, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(payload) > 100000:
        raise RuntimeError("Ombor ma’lumotlari juda katta; chuqur tahlilni bo‘limlarga ajratish kerak.")
    prompt = (
        "Sen korxona rahbarining Supply Chain bo‘yicha qisqa va aniq yordamchisisan. "
        "Faqat o‘zbek tilida, ixcham va tabiiy gapir. Xulosa, dalillar va keyingi qadamni alohida bloklarda ber; "
        "bloklar orasida bitta bo‘sh qator qoldir. Mahsulotlar ro‘yxatida har bir mahsulotni yangi qatorda • belgisi bilan yoz. "
        "Odatda 5–8 qisqa qator yetarli; foydalanuvchi batafsil so‘ramasa uzun izoh yozma. "
        "Texnik atamalar, JSON, ichki maydon nomlari, koddagi o‘zgaruvchilar va tizim arxitekturasini hech qachon tilga olma. "
        "computed_reports.abc yoki shunga o‘xshash ichki nomlarni foydalanuvchiga ko‘rsatma; oddiy biznes tilida izohla. "
        "Faqat berilgan ma’lumot va undagi oldindan hisoblangan metrikalardan foydalan. "
        "Raqamlarni qayta hisoblab o‘zgartirma, mavjud bo‘lmagan ma’lumotni to‘qima. "
        "Ma’lumot yetishmasa, buni ochiq ayt va qaysi ma’lumot kerakligini ko‘rsat. "
        "Zaxira, yetkazish muddati yoki talab bo‘yicha dalil bo‘lmasa, mahsulotni xavfli deb e’lon qilma. "
        "Pul zaxirada band bo‘lsa, mahsulot miqdori × birlik tannarxidan foydalan; tannarx yo‘q bo‘lsa qiymatni hisoblama. "
        "Yetkazib beruvchi xavfini faqat mavjud reyting, yetkazish muddati va kechikkan buyurtmalar dalili bilan bahola. "
        "Hech qanday amal bajarma, ombor yoki buyurtmalarni o‘zgartirma. Buyurtma kerak bo‘lsa, faqat qoralama taklif qil; "
        "foydalanuvchi tasdiqlamaguncha hech narsa yuborilmaydi.\n\n"
        f"SAVOL: {question[:1000]}\n\n"
        f"JORIY SUPPLY CHAIN MA’LUMOTLARI (JSON):\n{payload}"
    )
    response = client.models.generate_content(model=model, contents=prompt)
    answer = getattr(response, "text", None)
    if not answer or not str(answer).strip():
        raise RuntimeError("AI javobi bo‘sh qaytdi. Birozdan keyin qayta urinib ko‘ring.")
    return _format_ai_customer_answer(str(answer))


def _format_ai_customer_answer(answer: str) -> str:
    """Keep AI output readable and hide internal implementation vocabulary."""
    import re
    text = str(answer or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    technical = re.compile(
        r"(?i)(json|computed_reports|computed_metrics|inventory_summary|kpi_availability|"
        r"risk_assessment|callback|api|database|deploy|backend|field|schema|sku\s*[:=])"
    )
    cleaned = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        if technical.search(line):
            # Never expose internal field names or code vocabulary to a business user.
            cleaned.append("Hisobotdagi mavjud ma’lumotlar asosida.")
            continue
        if line.startswith(("-", "*")):
            line = "• " + line.lstrip("-* ").strip()
        cleaned.append(line)
    # Keep one blank line between thought blocks, without blank lines inside bullet lists.
    out = []
    for i, line in enumerate(cleaned):
        if line == "":
            if out and out[-1] != "":
                out.append("")
            continue
        if out and out[-1] != "" and re.match(r"^(💡|Dalillar:|Keyingi qadam:|Xulosa:)", line, re.I):
            out.append("")
        out.append(line)
    return "\n".join(out).strip()


def _ai_draft_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return low-stock products with evidence-backed or minimum-gap draft quantities."""
    metrics = {str(x.get("sku")): x for x in _computed_metrics(data)}
    candidates = []
    for sku, product in data.get("products", {}).items():
        if not isinstance(product, dict):
            continue
        stock = _safe_num(product.get("quantity"))
        minimum = _safe_num(product.get("reorder_point"))
        if product.get("quantity") is None or product.get("reorder_point") is None or stock > minimum:
            continue
        metric = metrics.get(str(sku), {})
        if metric.get("forecast_status") == "available":
            qty = _safe_num(metric.get("recommended_purchase_quantity"))
        else:
            qty = max(0.0, minimum - stock)
        if qty <= 0:
            continue
        candidates.append({
            "sku": str(sku), "name": str(product.get("name", sku)),
            "quantity": qty, "unit": str(product.get("unit", "dona")),
        })
    return candidates


def _create_ai_draft_orders(data: dict[str, Any], candidates: list[dict[str, Any]]) -> list[str]:
    """Create drafts only after an explicit button press; never submit them to suppliers."""
    suppliers = data.get("suppliers", {})
    if len(suppliers) != 1:
        raise ValueError("Buyurtma qoralamasini tayyorlash uchun bitta asosiy yetkazib beruvchini tanlash kerak.")
    supplier = next(iter(suppliers.values()))
    if not isinstance(supplier, dict) or not supplier.get("id"):
        raise ValueError("Yetkazib beruvchi ma’lumoti to‘liq emas.")
    lead_days = max(0, int(_safe_num(supplier.get("lead_time_days"))))
    expected = (date.today() + timedelta(days=lead_days)).isoformat()
    prepared = []
    for item in candidates:
        product = data.get("products", {}).get(item["sku"])
        if not product:
            raise ValueError(f"{item['name']}: mahsulot topilmadi.")
        price = _safe_num(product.get("unit_cost"))
        if price <= 0:
            raise ValueError(f"{item['name']}: xarid narxi kiritilmagan. Avval mahsulot narxini to‘ldiring.")
        prepared.append({
            "id": "PO-" + uuid.uuid4().hex[:8].upper(),
            "sku": item["sku"], "supplier_id": supplier["id"],
            "quantity": item["quantity"], "unit_price": price,
            "expected_date": expected, "status": "draft", "created_at": _now(),
        })
    if not prepared:
        raise ValueError("Qoralama yaratish uchun mos mahsulot topilmadi.")
    data.setdefault("orders", []).extend(prepared)
    return [str(order["id"]) for order in prepared]


def _voice_transcribe_sync(raw: bytes, mime: str) -> str:
    if _AI_CLIENT is None:
        raise RuntimeError("Ovozli yordamchi hozir ulanmagan.")
    from google.genai import types
    part = types.Part.from_bytes(data=raw, mime_type=mime or "audio/ogg")
    response = _AI_CLIENT.models.generate_content(
        model=_AI_MODEL,
        contents=["Ovozli xabarni aytilgan asl tilda matnga ko‘chir. Tarjima yoki izoh qo‘shma. Faqat savolni qaytar.", part],
    )
    result = (getattr(response, "text", "") or "").strip()
    if not result:
        raise RuntimeError("Ovozdan tushunarli savol ajratilmadi.")
    return result[:1500]


def _inventory_report_png(data: dict[str, Any]) -> io.BytesIO:
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 900), "#071426")
    draw = ImageDraw.Draw(image)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
        mid = ImageFont.truetype("DejaVuSans-Bold.ttf", 27)
        small = ImageFont.truetype("DejaVuSans.ttf", 19)
    except Exception:
        big = mid = small = ImageFont.load_default()
    products = [p for p in data.get("products", {}).values() if isinstance(p, dict)]
    low = []
    for sku, p in data.get("products", {}).items():
        try:
            qty, minimum = float(p.get("quantity")), float(p.get("reorder_point"))
            if qty <= minimum:
                low.append((str(p.get("name", sku)), qty, minimum, str(p.get("unit", "dona"))))
        except (TypeError, ValueError):
            continue
    low.sort(key=lambda x: x[1] / x[2] if x[2] else 0)
    value = sum(max(0, _safe_num(p.get("quantity"))) * max(0, _safe_num(p.get("unit_cost"))) for p in products)
    draw.text((55, 42), "SUPPLY CHAIN  |  OMBOR HISOBOTI", fill="#EAF2FF", font=mid)
    draw.text((55, 95), datetime.now().strftime("%d.%m.%Y  %H:%M"), fill="#91A7C5", font=small)
    for x, label, val in [(55, "MAHSULOTLAR", str(len(products))), (430, "OMBOR QIYMATI", f"{value:,.0f}"), (805, "BUYURTMA KERAK", str(len(low)))]:
        draw.rounded_rectangle((x, 155, x+340, 295), radius=20, fill="#102844", outline="#24476B", width=2)
        draw.text((x+22, 178), label, fill="#91A7C5", font=small)
        draw.text((x+22, 218), val, fill="#FFFFFF", font=big)
    draw.text((55, 345), "MINIMAL ZAXIRADAN PAST MAHSULOTLAR", fill="#EAF2FF", font=mid)
    if not low:
        draw.text((55, 420), "Hozircha minimal zaxiradan past mahsulot yo‘q.", fill="#B8C9DE", font=small)
    for i, (name, qty, minimum, unit) in enumerate(low[:7]):
        y = 415 + i*62
        draw.text((60, y), name[:32], fill="#EAF2FF", font=small)
        draw.text((650, y), f"{qty:g} / {minimum:g} {unit}", fill="#B8C9DE", font=small)
        draw.rounded_rectangle((900, y+5, 1120, y+27), radius=9, fill="#203A58")
        ratio = min(1, qty/minimum) if minimum > 0 else 0
        draw.rounded_rectangle((900, y+5, 900+int(220*ratio), y+27), radius=9, fill="#F05B64")
    draw.text((55, 855), "Qiymat mavjud miqdor va xarid narxlari asosida hisoblandi.", fill="#91A7C5", font=small)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


async def _serialized_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not update.effective_user or update.effective_user.id != _OWNER_ID:
        return
    media = message.voice or message.audio
    status = await message.reply_text("🎧 Savolingizni tinglayapman…")
    try:
        if (getattr(media, "file_size", 0) or 0) > 15*1024*1024:
            await status.edit_text("Ovozli xabar 15 MB dan kichik bo‘lishi kerak.")
            return
        tg_file = await media.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        if len(raw) > 15*1024*1024:
            await status.edit_text("Ovozli xabar 15 MB dan kichik bo‘lishi kerak.")
            return
        mime = getattr(media, "mime_type", None) or ("audio/ogg" if message.voice else "audio/mpeg")
        async with _SC_MUTATION_LOCK:
            transcript = await asyncio.wait_for(asyncio.to_thread(_voice_transcribe_sync, raw, mime), timeout=75)
            answer = await asyncio.wait_for(asyncio.to_thread(
                _ask_gemini_quick_sync, _AI_CLIENT, _AI_MODEL, transcript, _ai_snapshot(_data())), timeout=45)
        await status.edit_text("🗣 **Savolingiz:** " + transcript[:700] + "\n\n🤖 **Javob:**\n" + answer)
    except Exception:
        await status.edit_text("⚠️ Ovozli savolni qayta ishlay olmadim. Birozdan keyin yana urinib ko‘ring.")


def _dashboard_text(data: dict[str, Any]) -> str:
    products = list(data.get("products", {}).values())
    suppliers = list(data.get("suppliers", {}).values())
    orders = list(data.get("orders", []))
    vehicles = list(data.get("vehicles", []))
    shipments = list(data.get("shipments", []))
    risks = _risk_assessment(data)
    num = lambda value: _safe_num(value)
    inventory_value = sum(num(p.get("quantity")) * num(p.get("unit_cost")) for p in products)
    low_stock = sum(num(p.get("quantity")) <= num(p.get("reorder_point")) for p in products)
    open_orders = sum(o.get("status") in ("draft", "ordered") for o in orders)
    order_value = sum(num(o.get("quantity")) * num(o.get("unit_price")) for o in orders if o.get("status") != "cancelled")
    dispatched = sum(x.get("status") == "dispatched" for x in shipments)
    delivered = sum(x.get("status") == "delivered" for x in shipments)
    transport_cost = sum(num(x.get("estimated_cost")) for x in shipments)
    high = sum(r.get("level") == "Yuqori" for r in risks)
    avg_rating = sum(num(x.get("rating")) for x in suppliers) / len(suppliers) if suppliers else 0
    lines = [
        "📈 **JARVIS SUPPLY CHAIN — DASHBOARD**", "",
        f"📦 Mahsulot turlari: **{len(products)}** | Jami zaxira: **{sum(num(p.get('quantity')) for p in products):,.2f}** birlik",
        f"💰 Ombor qiymati: **{inventory_value:,.2f}**", f"⚠️ Qayta buyurtma nuqtasiga yetgan: **{low_stock}** ta",
        f"🏭 Yetkazib beruvchilar: **{len(suppliers)}** | O‘rtacha reyting: **{avg_rating:.2f}/5**",
        f"🧾 Buyurtmalar: **{len(orders)}** | Ochiq: **{open_orders}** | Bekor qilinmagan qiymati: **{order_value:,.2f}**",
        f"🚛 Transport vositalari: **{len(vehicles)}** | Yuklar: **{len(shipments)}**",
        f"📍 Yuk holati: yo‘lda **{dispatched}**, yetkazilgan **{delivered}** | Rejalashtirilgan xarajat: **{transport_cost:,.2f}**",
        f"🛡 Risklar: **{len(risks)}** | Yuqori darajali: **{high}**",
        f"📉 Talab tarixi yozuvlari: **{len(data.get('demand_history', []))}** | Ishlab chiqarish ssenariylari: **{len(data.get('scenarios', []))}**",
        "", "Ko‘rsatkichlar mavjud yozuvlardan hisoblandi. Yetishmayotgan qiymatlar nol sifatida hisoblanadi; bu real xarajat yo‘q degani emas."
    ]
    return "\n".join(lines)


def _suppliers_text(data: dict[str, Any]) -> str:
    suppliers = list(data.get("suppliers", {}).values())
    if not suppliers:
        return "🏭 **YETKAZIB BERUVCHILAR**\n\nHozircha ro‘yxat bo‘sh. «➕ Yetkazib beruvchi» orqali qo‘shing."
    lines = [f"🏭 **YETKAZIB BERUVCHILAR — {len(suppliers)} ta**", ""]
    for supplier in sorted(suppliers, key=lambda x: str(x.get("name", "")).casefold())[:30]:
        lines.append(
            f"• **{supplier.get('name', 'Nomsiz')}** (`{supplier.get('id', '—')}`)\n"
            f"  Aloqa: {supplier.get('contact') or '—'} | Yetkazish: {supplier.get('lead_time_days', 0)} kun | Reyting: {supplier.get('rating', 0):g}/5"
        )
    if len(suppliers) > 30:
        lines.append(f"… yana {len(suppliers) - 30} ta")
    return "\n".join(lines)


def _orders_text(data: dict[str, Any]) -> str:
    orders = list(data.get("orders", []))
    if not orders:
        return "🧾 **XARID BUYURTMALARI**\n\nHozircha buyurtma yo‘q. «🛒 Yangi buyurtma» orqali yarating."
    suppliers = data.get("suppliers", {})
    products = data.get("products", {})
    status_names = {"draft": "Qoralama", "ordered": "Buyurtma berilgan", "received": "Qabul qilingan", "cancelled": "Bekor qilingan"}
    lines = [f"🧾 **XARID BUYURTMALARI — {len(orders)} ta**", ""]
    for order in sorted(orders, key=lambda x: str(x.get("created_at", "")), reverse=True)[:20]:
        supplier = suppliers.get(order.get("supplier_id"), {})
        product = products.get(order.get("sku"), {})
        status = order.get("status", "draft")
        lines.append(
            f"**{order.get('id', '—')}** · {status_names.get(status, status)}\n"
            f"{product.get('name', order.get('sku', 'Noma’lum SKU'))} — {order.get('quantity', 0):g} {product.get('unit', 'birlik')} × {order.get('unit_price', 0):,.2f}\n"
            f"Yetkazib beruvchi: {supplier.get('name', order.get('supplier_id', '—'))}\n"
            f"Kutilgan sana: {order.get('expected_date', '—')} | Jami: {order.get('quantity', 0) * order.get('unit_price', 0):,.2f}"
        )
        lines.append("")
    if len(orders) > 20:
        lines.append(f"… yana {len(orders) - 20} ta buyurtma (oxirgi 20 tasi ko‘rsatildi)")
    return "\n".join(lines)


def _orders_keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    for order in sorted(data.get("orders", []), key=lambda x: str(x.get("created_at", "")), reverse=True)[:12]:
        oid = str(order.get("id", ""))
        status = order.get("status")
        if status == "draft":
            rows.append([InlineKeyboardButton(f"📤 {oid}: buyurtma berish", callback_data=f"sc:ord_ordered:{oid}")])
        elif status == "ordered":
            rows.append([InlineKeyboardButton(f"📥 {oid}: qabul qilish", callback_data=f"sc:ord_received:{oid}"), InlineKeyboardButton("✖ Bekor", callback_data=f"sc:ord_cancel:{oid}")])
    rows.append([InlineKeyboardButton("⬅️ Supply Chain", callback_data="sc:buy")])
    return InlineKeyboardMarkup(rows)


def _demand_history_text(data: dict[str, Any]) -> str:
    rows = sorted(data.get("demand_history", []), key=lambda r: (str(r.get("month", "")), str(r.get("sku", ""))), reverse=True)
    if not rows:
        return "📚 Talab tarixi hali kiritilmagan. «➕ Talab kiritish» da yozing: paxta ipi 2026-10 145"
    products = data.get("products", {})
    lines = [f"📚 **TALAB TARIXI — {len(rows)} ta yozuv**", ""]
    for row in rows[:30]:
        product = products.get(row.get("sku"), {})
        lines.append(f"• {row.get('month')} — {product.get('name', row.get('sku'))}: {float(row.get('quantity', 0)):g}")
    if len(rows) > 30:
        lines.append(f"… yana {len(rows) - 30} ta yozuv")
    return "\n".join(lines)


def _vehicles_text(data: dict[str, Any]) -> str:
    vehicles = list(data.get("vehicles", []))
    if not vehicles:
        return "🚛 **TRANSPORT VOSITALARI**\n\nRo‘yxat bo‘sh. «➕ Transport» orqali kiriting."
    lines = [f"🚛 **TRANSPORT VOSITALARI — {len(vehicles)} ta**", ""]
    for v in sorted(vehicles, key=lambda x: str(x.get("id", "")))[:30]:
        lines.append(
            f"• **{v.get('name', 'Transport')}** (`{v.get('id', '—')}`)\n"
            f"  Sig‘im: {v.get('capacity', 0):g} | Xarajat: {v.get('cost_per_km', 0):,.2f}/km | Tezlik: {v.get('speed_kmh', 0):g} km/soat"
        )
    return "\n".join(lines)


def _shipments_text(data: dict[str, Any]) -> str:
    shipments = list(data.get("shipments", []))
    if not shipments:
        return "🗺 **YUKLAR VA MARSHRUTLAR**\n\nHozircha yuk rejalashtirilmagan."
    status_names = {"planned": "Rejalashtirilgan", "dispatched": "Yo‘lda", "delivered": "Yetkazilgan", "cancelled": "Bekor qilingan"}
    products = data.get("products", {})
    lines = [f"🗺 **YUKLAR / MARSHRUTLAR — {len(shipments)} ta**", ""]
    for sh in sorted(shipments, key=lambda x: str(x.get("created_at", "")), reverse=True)[:20]:
        vehicle = next((v for v in data.get("vehicles", []) if v.get("id") == sh.get("vehicle_id")), {})
        lines.append(
            f"**{sh.get('id', '—')}** · {status_names.get(sh.get('status'), sh.get('status'))}\n"
            f"{products.get(sh.get('sku'), {}).get('name', sh.get('sku', 'Noma’lum SKU'))}: {sh.get('quantity', 0):g} {products.get(sh.get('sku'), {}).get('unit', 'birlik')} → {sh.get('destination', '—')}\n"
            f"Transport: {vehicle.get('name', sh.get('vehicle_id', '—'))} | Masofa: {sh.get('distance_km', 0):g} km\n"
            f"Taxminiy vaqt: {sh.get('estimated_hours', 0):.2f} soat | Xarajat: {sh.get('estimated_cost', 0):,.2f}"
        )
        lines.append("")
    if len(shipments) > 20:
        lines.append(f"… yana {len(shipments) - 20} ta yuk (oxirgi 20 tasi ko‘rsatildi)")
    return "\n".join(lines)


def _shipments_keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    for sh in sorted(data.get("shipments", []), key=lambda x: str(x.get("created_at", "")), reverse=True)[:12]:
        sid = str(sh.get("id", ""))
        status = sh.get("status")
        if status == "planned":
            rows.append([InlineKeyboardButton(f"🚚 {sid}: jo‘natish", callback_data=f"sc:ship_dispatch:{sid}"), InlineKeyboardButton("✖ Bekor", callback_data=f"sc:ship_cancel:{sid}")])
        elif status == "dispatched":
            rows.append([InlineKeyboardButton(f"✅ {sid}: yetkazildi", callback_data=f"sc:ship_deliver:{sid}")])
    rows.append([InlineKeyboardButton("⬅️ Supply Chain", callback_data="sc:transport")])
    return InlineKeyboardMarkup(rows)


def _scenario_text(data: dict[str, Any], scenario: dict[str, Any]) -> str:
    result = _simulate_scenario(data, scenario)
    product = data.get("products", {}).get(scenario.get("sku"), {})
    unit = product.get("unit", "birlik")
    status = "Reja to‘liq bajariladi" if result["production_shortfall"] <= 1e-9 else "Reja to‘liq bajarilmaydi"
    return (
        f"🧪 **{scenario.get('name', 'Ssenariy')}** (`{scenario.get('id', '—')}`)\n"
        f"Xomashyo: {product.get('name', scenario.get('sku'))} ({scenario.get('sku')})\n"
        f"Holat: **{status}**\n\n"
        f"Rejalashtirilgan ishlab chiqarish: {result['target_qty']:,.2f} birlik\n"
        f"Amalda bajarish mumkin: **{result['feasible_qty']:,.2f} birlik**\n"
        f"Xomashyo cheklovi: {result['material_limit']:,.2f} birlik\n"
        f"Quvvat cheklovi: {result['capacity_limit']:,.2f} birlik\n"
        f"Ishlatiladigan xomashyo: {result['material_used']:,.2f} {unit}\n"
        f"Qoladigan xomashyo: **{result['remaining_stock']:,.2f} {unit}**\n"
        f"Rejadan kam ishlab chiqarish: {result['production_shortfall']:,.2f} birlik\n"
        f"Talab prognozi: {result['demand_qty']:,.2f} birlik\n"
        f"Talab qoplanmay qolishi: **{result['demand_gap']:,.2f} birlik**\n"
        f"Ortiqcha ishlab chiqarish: {result['surplus']:,.2f} birlik\n\n"
        "⚠️ Bu what-if hisob-kitobi. Ombor zaxirasi va haqiqiy buyurtmalar o‘zgartirilmagan."
    )


def _scenarios_text(data: dict[str, Any]) -> str:
    scenarios = data.get("scenarios", [])
    if not scenarios:
        return "📑 **SIMULYATSIYA SSENARIYLARI**\n\nHozircha ssenariy yo‘q. «➕ Yangi ssenariy» orqali boshlang."
    lines = [f"📑 **SAQLANGAN SSENARIYLAR — {len(scenarios)} ta**", ""]
    for scenario in sorted(scenarios, key=lambda x: str(x.get("created_at", "")), reverse=True)[:15]:
        try:
            r = _simulate_scenario(data, scenario)
            lines.append(f"• **{scenario.get('name')}** (`{scenario.get('id')}`): {r['feasible_qty']:.2f}/{r['target_qty']:.2f} birlik; talab kamomadi {r['demand_gap']:.2f}")
        except (ValueError, TypeError):
            lines.append(f"• **{scenario.get('name')}** (`{scenario.get('id')}`): hisoblab bo‘lmadi — SKU yoki parametrlarni tekshiring")
    lines.extend(["", "Ssenariylar faqat hisob-kitob uchun saqlanadi; ombor yozuvlariga ta’sir qilmaydi."])
    return "\n".join(lines)




# ----------------------------------------------------------------------------
# ABC va EOQ (hisoblash mantig'i o'zgarmagan; kiritish ko'rsatmasi soddalashtirilgan)
# ----------------------------------------------------------------------------
def _eoq_value(p: dict[str, Any]) -> tuple[float, bool] | None:
    """EOQ = sqrt(2*D*S/H). Saqlash xarajati yozilmagan bo'lsa narxning 20% i olinadi (belgilanadi)."""
    d = _safe_num(p.get("annual_demand"))
    s = _safe_num(p.get("order_cost"))
    h = _safe_num(p.get("holding_cost"))
    assumed = False
    if h <= 0:
        h = 0.2 * _safe_num(p.get("unit_cost"))
        assumed = True
    if d > 0 and s > 0 and h > 0:
        return math.sqrt((2 * d * s) / h), assumed
    return None


def _abc_text(data: dict[str, Any]) -> str:
    """ABC tahlili: yillik talab × narx bo'yicha 80% / 15% / 5%."""
    rows = []
    for p in data["products"].values():
        value = _safe_num(p.get("annual_demand")) * _safe_num(p.get("unit_cost"))
        if value > 0:
            rows.append((value, p))
    if not rows:
        return ("📈 **ABC TAHLILI**\n\nHisoblash uchun mahsulotlarda **narx** va **yillik talab** kerak.\n"
                "«➕ Mahsulot» da shunday yozing:\n`Paxta ipi narx 28000 yillik 12000`")
    rows.sort(key=lambda x: x[0], reverse=True)
    total = sum(x[0] for x in rows)
    cumulative = 0.0
    groups: dict[str, list] = {"A": [], "B": [], "C": []}
    for value, product in rows:
        share = value / total
        midpoint = (cumulative + share / 2) * 100
        groups["A" if midpoint <= 80 else ("B" if midpoint <= 95 else "C")].append((product, value, share))
        cumulative += share
    lines = ["📈 **ABC TAHLILI**", f"Yillik iste'mol qiymati: {_f(total)}", ""]
    for g in ("A", "B", "C"):
        entries = groups[g]
        gv = sum(x[1] for x in entries)
        lines.append(f"**{g} guruhi** — {len(entries)} ta | {gv / total * 100:.1f}% qiymat")
        for product, value, share in entries[:12]:
            lines.append(f"• {product.get('name', product.get('sku'))}: {_f(value)} ({share * 100:.1f}%)")
        if len(entries) > 12:
            lines.append(f"… yana {len(entries) - 12} ta")
        lines.append("")
    lines.append("A — eng muhim (qattiq nazorat), B — o'rta, C — kam ahamiyatli.")
    return "\n".join(lines)


def _eoq_text(data: dict[str, Any]) -> str:
    lines = ["🧮 **EOQ — QANCHADAN BUYURTMA QILISH KERAK**", ""]
    ready, missing, assumed_any = 0, [], False
    for p in data["products"].values():
        res = _eoq_value(p)
        name = p.get("name", p.get("sku"))
        if res:
            q, assumed = res
            assumed_any = assumed_any or assumed
            d = _safe_num(p.get("annual_demand"))
            per_year = d / q if q > 0 else 0
            ready += 1
            lines.append(f"**{name}**: **{_f(round(q, 1))} {p.get('unit', 'dona')}** — yiliga ~{per_year:.1f} marta buyurtma" + (" *" if assumed else ""))
        else:
            need = []
            if _safe_num(p.get("annual_demand")) <= 0:
                need.append("yillik talab")
            if _safe_num(p.get("order_cost")) <= 0:
                need.append("buyurtma xarajati")
            if _safe_num(p.get("holding_cost")) <= 0 and _safe_num(p.get("unit_cost")) <= 0:
                need.append("narx yoki saqlash xarajati")
            missing.append(f"• {name}: yetishmaydi — {', '.join(need)}")
    if not ready:
        lines.append("Hali hisoblash uchun ma'lumot yetarli emas.")
    if missing:
        lines += ["", "Yetishmayotganlar:"] + missing[:15]
        lines.append("\nTo'ldirish: «➕ Mahsulot» da yozing, masalan:\n`Paxta ipi yillik 12000 buyurtma 150000 narx 28000`")
    if assumed_any:
        lines.append("\n* Saqlash xarajati kiritilmagani uchun mahsulot narxining 20% i yillik H sifatida taxmin qilindi. Aniq H ni kiriting: Paxta ipi saqlash 4000 — bu 1 kg/donani 1 yil saqlash narxi, butun ombor ijarasi emas.")
    lines.append("\nFormula: √(2·D·S / H). D — yillik talab, S — 1 buyurtma xarajati, H — 1 dona/kg mahsulotni 1 yil saqlash xarajati (so'm/birlik/yil). Omborning umumiy oylik ijarasini H sifatida kiritmang.")
    return "\n".join(lines)


def _inventory_summary(data: dict[str, Any]) -> dict[str, Any]:
    """All-SKU inventory KPIs; low stock and <20-day attention are separate states."""
    products = list(data.get("products", {}).values())
    history = data.get("demand_history", [])
    low, attention, healthy, unknown = [], [], [], []
    total_value = 0.0
    for p in products:
        qty = _safe_num(p.get("quantity"))
        reorder = _safe_num(p.get("reorder_point"))
        total_value += qty * _safe_num(p.get("unit_cost"))
        is_low = qty <= reorder if reorder > 0 else qty <= 0
        if is_low:
            low.append(p)
            continue
        annual = _safe_num(p.get("annual_demand"))
        if annual <= 0:
            sku = p.get("sku")
            records = sorted((r for r in history if r.get("sku") == sku), key=lambda r: str(r.get("month", "")))[-6:]
            if records:
                annual = sum(_safe_num(r.get("quantity")) for r in records) / len(records) * 12
        days = qty / (annual / 365) if annual > 0 else None
        if days is None:
            unknown.append(p)
        elif days < 20:
            attention.append((p, days))
        else:
            healthy.append(p)
    return {"products": products, "total_value": total_value, "low": low,
            "attention": attention, "healthy": healthy, "unknown": unknown}


def _inventory_summary_text(data: dict[str, Any]) -> str:
    stats = _inventory_summary(data)
    products = stats["products"]
    if not products:
        return "📦 **OMBOR XULOSASI**\n\nOmbor hozircha bo‘sh. «➕ Mahsulot» orqali kiriting."
    currency = (os.environ.get("SUPPLY_CHAIN_CURRENCY") or "UZS").strip().upper()
    value = _f(stats["total_value"])
    low_names = ", ".join(str(p.get("name", p.get("sku", "Nomsiz"))) for p in stats["low"][:5])
    if len(stats["low"]) > 5:
        low_names += f" va yana {len(stats['low']) - 5} ta"
    attention_names = ", ".join(str(p.get("name", p.get("sku", "Nomsiz"))) for p, _ in stats["attention"][:4])
    if len(stats["attention"]) > 4:
        attention_names += f" va yana {len(stats['attention']) - 4} ta"
    return ("📦 **OMBOR XULOSASI**\n"
            f"💰 Jami qiymat: **{value} {currency}** · {len(products)} ta SKU\n"
            f"🔴 Buyurtma kerak: **{len(stats['low'])} ta**" + (f" ({low_names})" if low_names else "") + "\n"
            f"🟡 Diqqat (<20 kun): **{len(stats['attention'])} ta**" + (f" ({attention_names})" if attention_names else "") + "\n"
            f"🟢 Me’yorda: **{len(stats['healthy'])} ta**" +
            (f"\n⚪ Qoplama prognozi yo‘q: **{len(stats['unknown'])} ta**" if stats["unknown"] else ""))


def _low_stock_text(data: dict[str, Any]) -> str:
    stats = _inventory_summary(data)
    rows = ["🔴 **BUYURTMA TALAB QILINADIGAN MAHSULOTLAR**", ""]
    for p in stats["low"]:
        rows.append(f"• {p.get('name', p.get('sku'))} — {_f(_safe_num(p.get('quantity')))} {p.get('unit', 'dona')} (minimum: {_f(_safe_num(p.get('reorder_point')))})")
    if not stats["low"]:
        rows.append("Hozircha minimal zaxiraga yetgan mahsulot yo‘q.")
    rows.append("\nBuyurtma qoralamasini yaratish uchun quyidagi tugmadan foydalaning.")
    return "\n".join(rows)


def _inventory_text(data: dict[str, Any]) -> str:
    products = list(data["products"].values())
    if not products:
        return "📦 Ombor hozircha bo'sh.\n\n«➕ Mahsulot» ni bosing va yozing:\n`Paxta ipi 1200 kg`"
    total_value = sum(_safe_num(p.get("quantity")) * _safe_num(p.get("unit_cost")) for p in products)
    low_n = 0
    lines = [f"📦 **OMBOR — {len(products)} ta mahsulot**", ""]
    for p in sorted(products, key=lambda x: str(x.get("name", "")).casefold())[:30]:
        qty, reorder, cost = _safe_num(p.get("quantity")), _safe_num(p.get("reorder_point")), _safe_num(p.get("unit_cost"))
        low = qty <= reorder if reorder > 0 else qty <= 0
        low_n += bool(low)
        lines.append(f"{'🔴' if low else '🟢'} **{p.get('name', 'Nomsiz')}** — {_f(qty)} {p.get('unit', 'dona')}")
        extra = []
        if cost > 0:
            extra.append(f"qiymati {_f(qty * cost)}")
        annual = _safe_num(p.get("annual_demand"))
        if annual > 0:
            extra.append(f"~{qty / (annual / 365):.0f} kunga yetadi")
        eoq = _eoq_value(p)
        if eoq:
            extra.append(f"EOQ {_f(round(eoq[0], 1))}")
        if low:
            extra.append("buyurtma vaqti!")
        if extra:
            lines.append("   " + " · ".join(extra))
    if len(products) > 30:
        lines.append(f"… yana {len(products) - 30} ta")
    lines.append("")
    if total_value > 0:
        lines.append(f"💰 Jami qiymat: {_f(total_value)}")
    if low_n:
        lines.append(f"🔴 Minimumga yetgan: {low_n} ta")
    return "\n".join(lines)


def _dashboard_full(data: dict[str, Any]) -> str:
    base = _dashboard_text(data)
    low = [p.get("name", p.get("sku")) for p in data.get("products", {}).values()
           if (_safe_num(p.get("reorder_point")) > 0 and _safe_num(p.get("quantity")) <= _safe_num(p.get("reorder_point")))
           or _safe_num(p.get("quantity")) <= 0]
    if low:
        base += "\n\n🔴 Buyurtma kerak: " + ", ".join(str(x) for x in low[:10])
    return base


# ----------------------------------------------------------------------------
# Menyular (qisqa) va yo'riqnomalar
# ----------------------------------------------------------------------------
def _btn(label: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=f"sc:{cb}")


def _ai_quick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🔴 Bugun nima tugayapti?", "aiq_stock")],
        [_btn("🛒 Nimalarga buyurtma beray?", "aiq_order")],
        [_btn("💰 Qayerda pulim ko‘p yotibdi?", "aiq_money")],
        [_btn("🚚 Qaysi yetkazib beruvchi xavfli?", "aiq_supplier")],
        [_btn("✍️ O‘zim savol beraman", "ai_custom")],
        [_btn("📊 Ombor hisobotini rasmda ko‘rish", "ai_report")],
        [_btn("⬅️ Menyu", "home")],
    ])


_AI_QUICK_QUESTIONS = {
    "aiq_stock": "Bugun qaysi mahsulotlar tugash xavfida? Faqat mavjud zaxira, minimum va hisoblangan zaxira qoplamasi dalillarini ko‘rsat.",
    "aiq_order": "Hozir qaysi mahsulotlarga buyurtma berish kerak? Mahsulot, mavjud qoldiq, minimum va tavsiya miqdorini faqat ma’lumot yetarli bo‘lsa ko‘rsat. Buyurtma yaratma.",
    "aiq_money": "Ombordagi qaysi mahsulotlarda eng ko‘p pul band? Faqat mavjud miqdor va birlik tannarxi bor mahsulotlar bo‘yicha qiymatni solishtir.",
    "aiq_supplier": "Qaysi yetkazib beruvchilarda xavf belgisi bor? Faqat mavjud reyting, yetkazish muddati va kechikkan buyurtmalar dalillariga tayangan holda ayt.",
}


def _home_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [_btn("📦 Ombor", "inventory"), _btn("➕ Mahsulot", "add")],
        [_btn("📥 Kirim", "in"), _btn("📤 Chiqim", "out")],
        [_btn("📊 Hisobotlar", "reports"), _btn("🛒 Xarid", "buy")],
        [_btn("🚛 Transport", "transport"), _btn("🧪 Simulyatsiya", "sim")],
        [_btn("📥 Excel qabul qilish", "excel_upload")],
        [_btn("🤖 AI maslahatchi", "ai")],
    ]
    base_url = (os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if base_url.startswith("https://"):
        from telegram import WebAppInfo
        rows.insert(0, [InlineKeyboardButton(
            "📱 Supply Chain Mini App",
            web_app=WebAppInfo(url=base_url + "/supply-chain"),
        )])
    return InlineKeyboardMarkup(rows)


def _menu_keyboard(kind: str) -> InlineKeyboardMarkup:
    rows = {
        "reports": [
            [_btn("📈 Dashboard", "dashboard"), _btn("📉 Prognoz", "forecast")],
            [_btn("📈 ABC", "abc"), _btn("🧮 EOQ", "eoq")],
            [_btn("🛡 Risklar", "risks"), _btn("📚 Talab tarixi", "demand_history")],
            [_btn("➕ Talab kiritish", "demand_add")],
            [_btn("📥 Excel", "export_xlsx"), _btn("📄 PDF", "export_pdf")],
        ],
        "buy": [
            [_btn("🏭 Yetkazib beruvchilar", "suppliers"), _btn("➕ Yetkazib beruvchi", "supplier_add")],
            [_btn("🧾 Buyurtmalar", "orders"), _btn("🛒 Yangi buyurtma", "order_add")],
        ],
        "transport": [
            [_btn("🚛 Transportlar", "vehicles"), _btn("➕ Transport", "vehicle_add")],
            [_btn("🗺 Yuklar", "shipments"), _btn("📦 Yuk rejalash", "shipment_add")],
        ],
        "sim": [
            [_btn("📑 Ssenariylar", "scenario_list"), _btn("➕ Yangi ssenariy", "scenario_add")],
        ],
    }[kind]
    return InlineKeyboardMarkup(rows + [[_btn("⬅️ Menyu", "home")]])


def _back_keyboard(parent: str = "home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("⬅️ Orqaga", parent)]])


_MENU_TITLES = {
    "reports": "📊 **HISOBOTLAR**\nNimani ko'rmoqchisiz?",
    "buy": "🛒 **XARID**\nYetkazib beruvchilar va buyurtmalar.",
    "transport": "🚛 **TRANSPORT**\nTransport va yuklarni rejalash.",
    "sim": "🧪 **ISHLAB CHIQARISH SIMULYATSIYASI**\nReja bajariladimi — xomashyo va quvvat bo'yicha tekshiradi. Ombor o'zgarmaydi.",
}
_PARENT = {"add": "home", "in": "home", "out": "home", "supplier_add": "buy", "order_add": "buy", "vehicle_add": "transport",
           "shipment_add": "transport", "demand_add": "reports", "scenario_add": "sim", "ai": "home"}
_PROMPTS = {
    "add": ("➕ **MAHSULOT QO'SHISH**\n\nShunchaki yozing:\n`Paxta ipi 1200 kg`\n\n"
            "Xohlasangiz hammasini birdan:\n`Paxta ipi 1200 kg minimum 300 narx 28000 yillik 12000 buyurtma 150000 saqlash 4000`\n\n"
            "• saqlash 4000 — 1 kg/dona mahsulotni 1 yil saqlash xarajati (so'm/birlik/yil). Butun omborning oylik ijarasini yozmang.\n"
            "• Kod (SKU) o'zi qo'yiladi.\n• Mavjud mahsulotni yangilash: Paxta ipi narx 30000\n"
            "• Ko'p mahsulotni ketma-ket yuboravering."),
    "in": ("📥 **KIRIM**\n\nOddiy gap bilan yozing:\n`50 kg paxta keldi`\n`paxta ipi 120 kirim`\n\n"
           "Ketma-ket yuboravering. «ketdi» deb yozsangiz chiqim bo'ladi."),
    "out": ("📤 **CHIQIM**\n\nOddiy gap bilan yozing:\n`200 kg paxta ketdi`\n`paxta ipi 5 ishlatildi`\n\n"
            "Ketma-ket yuboravering."),
    "supplier_add": ("🏭 **YETKAZIB BERUVCHI**\n\nYozing:\n`Atlas Textile, 7 kun, reyting 4.5`\n`Atlas Textile, +998901234567, 7 kun`\n\n"
                     "Faqat nom ham yetadi. Yangilash: `Atlas Textile 10 kun reyting 4`"),
    "order_add": ("🛒 **YANGI BUYURTMA**\n\nYozing:\n`paxta ipi 100 kg Atlas narx 18000`\n\n"
                  "• Narx yozilmasa mahsulotdagi narx olinadi.\n• Sana yozilmasa: bugun + yetkazib beruvchi muddati.\n"
                  "• Sana kerak bo'lsa: `... sana 2026-11-20`\n• Buyurtma avval qoralama bo'ladi."),
    "vehicle_add": ("🚛 **TRANSPORT**\n\nYozing: nomi, sig'im, 1 km narxi, tezlik\n`Isuzu, 5000, 2500, 60`\n\n"
                    "yoki: `Isuzu sigim 5000 narx 2500 tezlik 60`\nTezlik yozilmasa 60 km/soat olinadi."),
    "shipment_add": ("📦 **YUK REJALASH**\n\nYozing: mahsulot, miqdor, manzil, masofa\n`paxta ipi, 100, Samarqand ombori, 280`\n\n"
                     "Tizim sig'imi yetadigan eng arzon transportni o'zi tanlaydi."),
    "demand_add": ("📉 **TALAB TARIXI**\n\nOylik sotuv/talabni yozing:\n`paxta ipi 2026-10 145`\n`paxta ipi oktyabr 145`\n\n"
                   "Bir necha qator yuborsangiz hammasi saqlanadi. Oy yozilmasa — joriy oy."),
    "scenario_add": ("🧪 **YANGI SSENARIY**\n\nYozing:\n`paxta ipi reja 500 sarf 0.8 quvvat 100 kun 5 talab 450`\n\n"
                     "reja — nechta mahsulot ishlab chiqarmoqchisiz; sarf — 1 donaga xomashyo; quvvat — kuniga; kun — necha kun; talab — kutilgan talab."),
}


# ----------------------------------------------------------------------------
# Telegram yordamchilari
# ----------------------------------------------------------------------------
async def _edit(q, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    from telegram.error import BadRequest
    text = text[:3900]
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        try:  # Markdown belgilar (_ * `) nom ichida bo'lsa — oddiy matn sifatida yuboramiz
            await q.edit_message_text(text.replace("**", "").replace("`", ""), reply_markup=kb)
        except BadRequest as exc2:
            if "not modified" not in str(exc2).lower():
                raise


async def _reply(message, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    from telegram.error import BadRequest
    text = text[:3900]
    try:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    except BadRequest:
        await message.reply_text(text.replace("**", "").replace("`", ""), reply_markup=kb)


_HOME_TEXT = ("🚚 **JARVIS SUPPLY CHAIN**\n\nTez yozish: «📥 Kirim» yoki «📤 Chiqim» ni bosib oddiy gap yozing:\n"
              "`200 kg paxta ketdi`\n\nExcel import: .xlsx faylni shu chatga yuboring. Ustunlar tushunarsiz bo‘lsa, bot sizdan aniqlashtiradi.")


async def open_supply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ Supply Chain bo'limi faqat bot egasining shaxsiy chatida ishlaydi.")
        return
    context.user_data.pop("_sc_wait", None)
    await _reply(update.effective_message, _HOME_TEXT, _home_keyboard())


async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    if not _allowed(update):
        await q.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await q.answer()
    bits = (q.data or "").split(":")
    action = bits[1] if len(bits) > 1 else ""
    if action in ("home", "reports", "buy", "transport", "sim") or action in _simple_views():
        context.user_data.pop("_sc_wait", None)
    data = _data()

    async def alert(msg: str) -> None:
        await q.message.reply_text("⚠️ " + msg)

    if action.startswith("ship_"):
        if len(bits) != 3:
            return await alert("Yuk identifikatori noto'g'ri")
        shipment_id = bits[2]
        shipment = next((x for x in data.get("shipments", []) if str(x.get("id")) == shipment_id), None)
        if not shipment:
            return await alert("Yuk topilmadi")
        status = shipment.get("status")
        if action == "ship_dispatch" and status == "planned":
            product = data.get("products", {}).get(shipment.get("sku"))
            qty = float(shipment.get("quantity", 0))
            if not product or float(product.get("quantity", 0)) < qty:
                return await alert("Omborda yukni jo'natish uchun yetarli zaxira yo'q")
            product["quantity"] = float(product.get("quantity", 0)) - qty
            product["updated_at"] = _now()
            data["movements"].append({"id": uuid.uuid4().hex[:12], "sku": shipment["sku"], "type": "out", "quantity": qty,
                                      "note": f"Transport yuk {shipment_id} jo'natildi", "created_at": _now(), "shipment_id": shipment_id})
            shipment["status"] = "dispatched"
            shipment["dispatched_at"] = _now()
            await _save(data)
            message = f"Yuk yo'lga chiqdi. Ombordan {qty:g} birlik yechildi."
        elif action == "ship_deliver" and status == "dispatched":
            shipment["status"] = "delivered"
            shipment["delivered_at"] = _now()
            await _save(data)
            message = "Yuk yetkazildi."
        elif action == "ship_cancel" and status == "planned":
            shipment["status"] = "cancelled"
            shipment["cancelled_at"] = _now()
            await _save(data)
            message = "Yuk bekor qilindi. Zaxira o'zgarmadi."
        else:
            return await alert("Bu yuk uchun bu amalni bajarib bo'lmaydi")
        await _edit(q, message + "\n\n" + _shipments_text(data), _shipments_keyboard(data))
    elif action.startswith("ord_"):
        if len(bits) != 3:
            return await alert("Buyurtma identifikatori noto'g'ri")
        order_id = bits[2]
        order = next((x for x in data.get("orders", []) if str(x.get("id")) == order_id), None)
        if not order:
            return await alert("Buyurtma topilmadi")
        status = order.get("status")
        if action == "ord_ordered" and status == "draft":
            order["status"] = "ordered"
            order["ordered_at"] = _now()
            message = "Buyurtma yetkazib beruvchiga berildi."
        elif action == "ord_received" and status == "ordered":
            product = data.get("products", {}).get(order.get("sku"))
            if not product:
                return await alert("Mahsulot topilmadi; zaxira o'zgartirilmadi")
            order["id"] = order_id
            try:
                message = _receive_purchase_order(data, order)
            except (TypeError, ValueError, OverflowError) as exc:
                return await alert(str(exc))
        elif action == "ord_cancel" and status in ("draft", "ordered"):
            order["status"] = "cancelled"
            order["cancelled_at"] = _now()
            message = "Buyurtma bekor qilindi. Zaxira o'zgarmadi."
        else:
            return await alert("Bu buyurtma uchun bu amalni bajarib bo'lmaydi")
        await _save(data)
        await _edit(q, message + "\n\n" + _orders_text(data), _orders_keyboard(data))
    elif action == "home":
        context.user_data.pop("_sc_wait", None)
        await _edit(q, _HOME_TEXT, _home_keyboard())
    elif action == "excel_upload":
        context.user_data["_sc_wait"] = {"action": "excel_upload", "parent": "home", "started": datetime.now().timestamp()}
        await _edit(q, "📥 **EXCEL QABUL QILISH**\n\n.xlsx faylni shu chatga yuboring. Faylni o'qiy olmasam, sababini ko'rsataman va sizdan uning mazmuni hamda ustunlari haqida so'rayman.\n\nImportdan oldin barcha ma'lumotlar ko'rib chiqiladi; tasdiqlamaguningizcha omborga yozilmaydi.", _back_keyboard("home"))
    elif action in _MENU_TITLES:
        await _edit(q, _MENU_TITLES[action], _menu_keyboard(action))
    elif action == "low_stock":
        rows = [[_btn("🛒 Buyurtma qoralamasi yaratish", "order_add")], [_btn("⬅️ Ombor xulosasi", "inventory")]]
        await _edit(q, _low_stock_text(data), InlineKeyboardMarkup(rows))
    elif action in _simple_views():
        text_fn, parent = _simple_views()[action]
        if action == "inventory":
            stats = _inventory_summary(data)
            rows = [[InlineKeyboardButton(f"🔴 Buyurtma kerak ({len(stats['low'])})", callback_data="sc:low_stock")],
                    [InlineKeyboardButton("🔍 Mahsulot qidirish", switch_inline_query_current_chat="")]]
            base_url = (os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
            if base_url.startswith("https://"):
                from telegram import WebAppInfo
                rows.append([InlineKeyboardButton("📱 To‘liq ombor (Mini App)", web_app=WebAppInfo(url=base_url + "/supply-chain"))])
            await _edit(q, _inventory_summary_text(data), InlineKeyboardMarkup(rows))
        else:
            await _edit(q, text_fn(data), _back_keyboard(parent))
    elif action == "orders":
        await _edit(q, _orders_text(data), _orders_keyboard(data))
    elif action == "shipments":
        await _edit(q, _shipments_text(data), _shipments_keyboard(data))
    elif action in ("export_xlsx", "export_pdf"):
        try:
            if action == "export_xlsx":
                payload, filename, caption = _xlsx_bytes(data), "jarvis_supply_chain_hisobot.xlsx", "📊 Supply Chain Excel hisoboti"
            else:
                payload, filename, caption = _pdf_bytes(data), "jarvis_supply_chain_hisobot.pdf", "📄 Supply Chain PDF hisoboti"
            await q.message.reply_document(document=io.BytesIO(payload), filename=filename, caption=caption)
        except Exception as exc:
            await alert(f"Hisobot tayyorlashda xatolik: {str(exc)[:300]}")
    elif action == "ai":
        if _AI_CLIENT is None:
            await _edit(q, "🤖 **AI maslahatchi**\n\nHozircha yordamchi ulanmagan. Boshqa ombor funksiyalari ishlayveradi.", _back_keyboard("home"))
        else:
            context.user_data.pop("_sc_wait", None)
            context.user_data.pop("_sc_ai_draft_candidates", None)
            await _edit(q, "🤖 **AI MASLAHATCHI**\n\nQaysi masalada yordam kerak?", _ai_quick_keyboard())
    elif action == "ai_report":
        try:
            await q.answer("Hisobot tayyorlanmoqda…")
            photo = await asyncio.to_thread(_inventory_report_png, _data())
            await q.message.reply_photo(photo=photo, caption="📊 Omboringiz bo‘yicha qisqa vizual hisobot.")
        except Exception:
            await q.answer("Hisobotni tayyorlab bo‘lmadi. Keyinroq urinib ko‘ring.", show_alert=True)
    elif action == "ai_custom":
        if _AI_CLIENT is None:
            await _edit(q, "AI maslahatchi hozir ulanmagan.", _back_keyboard("home"))
        else:
            context.user_data["_sc_wait"] = {"action": "ai_ask", "started": datetime.now().timestamp(), "parent": "home"}
            await _edit(q, "Savolingizni shu yerga yozing. Qisqa va aniq javob beraman.", _back_keyboard("ai"))
    elif action == "aiq_draft":
        candidates = context.user_data.pop("_sc_ai_draft_candidates", [])
        if not candidates:
            await _edit(q, "Qoralama yaratish uchun mahsulotlar ro‘yxati eskirgan. Tahlilni qayta oching.",
                        InlineKeyboardMarkup([[_btn("↩️ Boshqa savol", "ai")], [_btn("⬅️ Menyu", "home")]]))
        else:
            try:
                current = _data()
                # Revalidate quantities and product existence against the latest inventory before writing.
                fresh = {x["sku"]: x for x in _ai_draft_candidates(current)}
                valid = [fresh[x["sku"]] for x in candidates if x.get("sku") in fresh]
                if len(valid) != len(candidates):
                    raise ValueError("Ombor qoldig‘i o‘zgargan. Iltimos, tahlilni yangilang.")
                order_ids = _create_ai_draft_orders(current, valid)
                await _save(current)
                lines = ["✅ **Qoralama buyurtmalar yaratildi**", ""]
                for item in valid:
                    lines.append(f"• {item['name']} — {_f(item['quantity'])} {item['unit']}")
                lines.extend(["", "Buyurtmalar hali yetkazib beruvchiga yuborilmadi. Ularni «Buyurtmalar» bo‘limida tekshirishingiz mumkin."])
                await _edit(q, "\n".join(lines),
                            InlineKeyboardMarkup([[_btn("🧾 Buyurtmalarni ko‘rish", "orders")],
                                                  [_btn("↩️ Boshqa savol", "ai")], [_btn("⬅️ Menyu", "home")]]))
            except Exception as exc:
                await _edit(q, "⚠️ " + str(exc),
                            InlineKeyboardMarkup([[_btn("✍️ Buyurtmani qo‘lda tayyorlash", "order_add")],
                                                  [_btn("↩️ Boshqa savol", "ai")], [_btn("⬅️ Menyu", "home")]]))
    elif action in _AI_QUICK_QUESTIONS:
        if _AI_CLIENT is None:
            await _edit(q, "AI maslahatchi hozir ulanmagan.", _back_keyboard("home"))
        else:
            question = _AI_QUICK_QUESTIONS[action]
            await _edit(q, "⏳ Ombor ma’lumotlari tekshirilmoqda…")
            try:
                current = _data()
                snapshot = _ai_snapshot(current)
                answer = await asyncio.wait_for(
                    asyncio.to_thread(_ask_gemini_quick_sync, _AI_CLIENT, _AI_MODEL, question, snapshot),
                    timeout=42,
                )
                rows = []
                if action in ("aiq_stock", "aiq_order"):
                    candidates = _ai_draft_candidates(current)
                    if candidates:
                        context.user_data["_sc_ai_draft_candidates"] = candidates
                        rows.append([_btn(f"🛒 {len(candidates)} ta tovarga qoralama buyurtma yaratish", "aiq_draft")])
                    else:
                        context.user_data.pop("_sc_ai_draft_candidates", None)
                rows.extend([[_btn("↩️ Boshqa savol", "ai")], [_btn("⬅️ Menyu", "home")]])
                await _edit(q, "🤖 **Qisqa tahlil**\n\n" + answer,
                            InlineKeyboardMarkup(rows))
            except asyncio.TimeoutError:
                await _edit(q, "⏱ Tahlil biroz cho‘zildi. Iltimos, qayta urinib ko‘ring.",
                            InlineKeyboardMarkup([[_btn("↩️ Qayta tanlash", "ai")], [_btn("⬅️ Menyu", "home")]]))
            except Exception:
                await _edit(q, "⚠️ Hozir tahlilni yakunlay olmadim. Birozdan keyin qayta urinib ko‘ring.",
                            InlineKeyboardMarkup([[_btn("↩️ Qayta tanlash", "ai")], [_btn("⬅️ Menyu", "home")]]))
    elif action in _PROMPTS:
        context.user_data["_sc_wait"] = {"action": action, "started": datetime.now().timestamp(), "parent": _PARENT.get(action, "home")}
        await _edit(q, _PROMPTS[action], _back_keyboard(_PARENT.get(action, "home")))


def _simple_views() -> dict[str, tuple[Callable[[dict[str, Any]], str], str]]:
    return {
        "inventory": (_inventory_text, "home"),
        "dashboard": (_dashboard_full, "reports"),
        "forecast": (_forecast_text, "reports"),
        "abc": (_abc_text, "reports"),
        "eoq": (_eoq_text, "reports"),
        "risks": (_risk_text, "reports"),
        "demand_history": (_demand_history_text, "reports"),
        "suppliers": (_suppliers_text, "buy"),
        "vehicles": (_vehicles_text, "transport"),
        "scenario_list": (_scenarios_text, "sim"),
    }


def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    if isinstance(exc, ValueError) and ("could not convert" in msg or "invalid literal" in msg or "Invalid isoformat" in msg):
        return "Raqam yoki sana noto'g'ri yozilgan. Misol bilan solishtirib qayta yuboring."
    if isinstance(exc, (ValueError, TypeError)):
        return msg
    return "Tushunolmadim. Misol bilan solishtirib qayta yozing."


def _excel_mapping_from_text(raw: str, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse owner-confirmed Excel column mappings such as OrderList!J=product_name."""
    import copy
    result = copy.deepcopy(current or {})
    allowed = set(supply_chain_import._CANONICAL)
    matches = list(re.finditer(
        r"(?:(?P<sheet>[^,;!\n]+)!)?(?P<column>[A-Za-z]{1,3})"
        r"(?:\s*(?:=|:|[-–])\s*|\s+(?:ustuni|ustunida|ustun|da)\s+|\s+)"
        r"(?P<field>[^,;\n]+)",
        raw, re.IGNORECASE,
    ))
    for match in matches:
        sheet = (match.group("sheet") or "").strip()
        column = match.group("column").upper()
        field_text = match.group("field").strip().casefold()
        if field_text in {"ignore", "skip", "kerak emas", "o'tkazib yubor", "otkazib yubor"}:
            field = "ignore"
        else:
            field = field_text if field_text in allowed else supply_chain_import._ALIAS_TO_FIELD.get(supply_chain_import._norm(field_text))
            if not field:
                continue
        if sheet:
            result.setdefault(sheet, {})[column] = field
        else:
            result[column] = field
    return result


async def _excel_finish_import(message, context, raw_file: bytes, overrides: dict[str, Any] | None = None) -> None:
    """Inspect, clarify, validate, and ask for explicit confirmation before importing."""
    try:
        preview = supply_chain_import.inspect_workbook(raw_file, overrides or {})
    except Exception as exc:
        context.user_data["_sc_wait"] = {"action": "excel_upload", "parent": "home", "started": datetime.now().timestamp()}
        context.user_data["_sc_excel_read_error"] = str(exc)[:300]
        await _reply(message,
            "⚠️ Faylni ocholmadim: " + _friendly_error(exc) +
            "\n\nBu fayl haqiqiy Excel Workbook (.xlsx) bo'lmasligi yoki buzilgan bo'lishi mumkin. "
            "Qaysi dasturdan olinganini va ichida qanday ma'lumot borligini yozing. "
            "Keyin Excel Workbook (.xlsx) qilib qayta saqlab yuboring.")
        return

    context.user_data["_sc_excel_preview"] = preview
    if preview.get("questions"):
        questions = preview["questions"]
        lines = ["📎 **Excel ustunlarini aniqlashtirish kerak**", "",
                 "Har bir ustun uchun mos maydonni yozing yoki 'ignore' deb belgilang.",
                 "Format: Varaq!Ustun=maydon.", "",
                 "Misol: OrderList!J=product_name, OrderList!M=quantity",
                 "Yoki: FreightRates!A=ignore", "", "Aniqlashtirilmagan ustunlar:"]
        for item in questions[:24]:
            lines.append(f"• {item['sheet']}!{item['column']} — {item['header']}")
        if len(questions) > 24:
            lines.append(f"… yana {len(questions) - 24} ta ustun. Ularni ham keyingi xabarda so'rayman.")
        context.user_data["_sc_wait"] = {"action": "excel_map", "parent": "home", "started": datetime.now().timestamp()}
        await _reply(message, "\n".join(lines))
        return

    validated = supply_chain_import.validate_records(preview)
    context.user_data["_sc_excel_validated"] = validated
    if not validated.get("valid"):
        context.user_data["_sc_wait"] = {"action": "excel_clarify", "parent": "home", "started": datetime.now().timestamp()}
        lines = ["⚠️ **Fayl o'qildi, lekin ma'lumot turini aniqlay olmadim.**", "",
                 f"Tekshirilgan varaqlar: {len(preview.get('sheets', []))}",
                 f"Topilgan qatorlar: {preview.get('record_count', 0)}",
                 f"Xatolar: {validated.get('error_count', 0)}"]
        for err in validated.get("errors", [])[:12]:
            lines.append(f"• {err.get('sheet', '?')}!{err.get('row', '?')}: {err.get('message', '')}")
        lines += ["", "Bu fayl nimaga mo'ljallangan? Qaysi varaqlar va ustunlar nimani bildiradi?",
                  "Ustunlarni harflari bilan tushuntiring. Masalan: A=mahsulot nomi, B=miqdor, C=narx. "
                  "Kerak bo'lmagan ustun: D=ignore. Tushuntiring — qayta tekshiraman."]
        await _reply(message, "\n".join(lines))
        return

    counts = {}
    for row in validated["valid"]:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    labels = {"products": "Mahsulot", "suppliers": "Yetkazib beruvchi", "demand": "Talab tarixi",
              "orders": "Xarid buyurtmasi", "movements": "Ombor harakati"}
    lines = ["📋 **Excel import ko'rib chiqish**", "",
             f"Importga tayyor yozuvlar: **{validated['valid_count']} ta**"]
    for kind, count in counts.items():
        lines.append(f"• {labels.get(kind, kind)}: {count}")
    lines.append(f"Import qilinmaydigan/xatoli qatorlar: {validated.get('error_count', 0)}")
    for err in validated.get("errors", [])[:8]:
        lines.append(f"• {err.get('sheet', '?')}!{err.get('row', '?')}: {err.get('message', '')}")
    lines += ["", "Ma'lumotlar hozircha saqlanmadi.",
              "Import qilish uchun TASDIQLAYMAN deb yozing. Bekor qilish uchun BEKOR deb yozing."]
    context.user_data["_sc_wait"] = {"action": "excel_confirm", "parent": "home", "started": datetime.now().timestamp()}
    await _reply(message, "\n".join(lines))


async def _handle_excel_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update) or not update.message or not update.message.document:
        return
    document = update.message.document
    filename = str(document.file_name or "").strip()
    if not filename.casefold().endswith(".xlsx"):
        context.user_data["_sc_wait"] = {"action": "excel_upload", "parent": "home", "started": datetime.now().timestamp()}
        await update.message.reply_text(
            f"⚠️ «{filename or 'Nomsiz fayl'}» .xlsx formatida emas. Hozircha .xlsx fayllarni qabul qilaman. "
            "Excel'da Fayl → Boshqa nom bilan saqlash → Excel Workbook (.xlsx) ni tanlang va qayta yuboring. "
            "Bu fayl nimadan iboratligini ham yozishingiz mumkin."
        )
        return
    if document.file_size and document.file_size > 12 * 1024 * 1024:
        context.user_data["_sc_wait"] = {"action": "excel_upload", "parent": "home", "started": datetime.now().timestamp()}
        await update.message.reply_text("⚠️ Excel fayli 12 MB dan katta. Kichikroq .xlsx fayl yuboring yoki ortiqcha varaqlarni olib tashlang.")
        return
    try:
        remote = await document.get_file()
        raw_file = bytes(await remote.download_as_bytearray())
        context.user_data["_sc_excel_raw"] = raw_file
        context.user_data["_sc_excel_overrides"] = {}
        context.user_data.pop("_sc_excel_validated", None)
        context.user_data.pop("_sc_excel_read_error", None)
        await _excel_finish_import(update.message, context, raw_file, {})
    except Exception as exc:
        context.user_data["_sc_wait"] = {"action": "excel_upload", "parent": "home", "started": datetime.now().timestamp()}
        await update.message.reply_text(
            "⚠️ Faylni yuklab yoki o'qib bo'lmadi: " + _friendly_error(exc) +
            "\nFaylni Excel Workbook (.xlsx) ko'rinishida qayta saqlab yuboring. "
            "Agar bu boshqa turdagi jadval bo'lsa, nima ma'lumot borligini tushuntiring."
        )


async def _text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Kutilayotgan Supply Chain matnini qayta ishlaydi. Qayta ishlangan bo'lsa True qaytaradi."""
    if not update.message or not context.user_data.get("_sc_wait"):
        return False
    if not _allowed(update):
        context.user_data.pop("_sc_wait", None)
        return False
    raw = (update.message.text or "").strip()
    if raw.startswith("/"):
        context.user_data.pop("_sc_wait", None)
        return False
    wait = context.user_data.get("_sc_wait") or {}
    if datetime.now().timestamp() - float(wait.get("started", 0)) > _WAIT_SECONDS:
        context.user_data.pop("_sc_wait", None)
        await update.message.reply_text("⏱ Vaqt tugadi. /supply orqali qayta boshlang.")
        return True
    action = wait.get("action")
    parent = wait.get("parent", "home")
    if action == "ai_ask":
        if not raw:
            await update.message.reply_text("Savol matni bo'sh. Savolingizni yozing.")
            return True
        context.user_data.pop("_sc_wait", None)
        if _AI_CLIENT is None:
            await update.message.reply_text("Gemini AI ulanmagan.", reply_markup=_home_keyboard())
            return True
        status = await update.message.reply_text("🤖 Tahlil qilinmoqda…")
        try:
            snapshot = _ai_snapshot(_data())
            answer = await asyncio.wait_for(asyncio.to_thread(_ask_gemini_sync, _AI_CLIENT, _AI_MODEL, raw, snapshot), timeout=42)
            full_answer = "🤖 SUPPLY CHAIN AI\n\n" + answer + "\n\nEslatma: tavsiyalar avtomatik bajarilmaydi."
            answer_parts = _split_telegram_text(full_answer)
            await status.edit_text(answer_parts[0], reply_markup=_home_keyboard())
            for part in answer_parts[1:]:
                await update.message.reply_text(part)
        except asyncio.TimeoutError:
            await status.edit_text("⏱ Gemini 42 soniyada javob bermadi. Keyinroq urinib ko'ring.", reply_markup=_home_keyboard())
        except Exception:
            await status.edit_text("⚠️ Hozir tahlilni yakunlay olmadim. Birozdan keyin qayta urinib ko‘ring.", reply_markup=_home_keyboard())
        return True
    if action == "excel_upload":
        if raw:
            context.user_data["_sc_excel_user_note"] = raw[:1000]
            await update.message.reply_text(
                "Tushundim. Izohingizni saqladim. Endi faylni Excel Workbook (.xlsx) formatida qayta yuboring. "
                "Fayl ochilgach, ustunlarni shu izoh asosida aniqlashtiramiz."
            )
        else:
            await update.message.reply_text("Excel faylini yuboring (.xlsx formatida). Agar xato chiqsa, sababini ko'rsatib, tushuntirishingizni so'rayman.")
        return True
    if action == "excel_clarify":
        raw_file = context.user_data.get("_sc_excel_raw")
        if not raw_file:
            context.user_data["_sc_wait"] = {"action": "excel_upload", "parent": "home", "started": datetime.now().timestamp()}
            await update.message.reply_text("Oldingi fayl sessiyada topilmadi. Iltimos, .xlsx faylni qayta yuboring.")
            return True
        overrides = _excel_mapping_from_text(raw, context.user_data.get("_sc_excel_overrides", {}))
        if not overrides:
            await update.message.reply_text(
                "Ustunlarni harflari bilan yozing. Masalan: "
                "A=mahsulot nomi, B=miqdor, C=narx. Kerak bo'lmagan ustun: D=ignore. "
                "Varaq bo'lsa: Sheet1!A=mahsulot nomi."
            )
            return True
        context.user_data["_sc_excel_overrides"] = overrides
        await _excel_finish_import(update.message, context, raw_file, overrides)
        return True
    if action == "excel_map":
        raw_file = context.user_data.get("_sc_excel_raw")
        if not raw_file:
            context.user_data.pop("_sc_wait", None)
            await update.message.reply_text("Excel fayli sessiyada topilmadi. Faylni qayta yuboring.")
            return True
        overrides = _excel_mapping_from_text(raw, context.user_data.get("_sc_excel_overrides", {}))
        if not overrides or overrides == context.user_data.get("_sc_excel_overrides", {}):
            await update.message.reply_text("Ustun mosligini tushunmadim. Masalan: C=quantity, D=unit_cost yoki E=ignore deb yozing.")
            return True
        context.user_data["_sc_excel_overrides"] = overrides
        await _excel_finish_import(update.message, context, raw_file, overrides)
        return True

    if action == "excel_confirm":
        if raw.casefold() in {"bekor", "cancel", "yo'q", "yoq"}:
            for key in ("_sc_excel_raw", "_sc_excel_overrides", "_sc_excel_preview", "_sc_excel_validated", "_sc_wait"):
                context.user_data.pop(key, None)
            await update.message.reply_text("Excel import bekor qilindi. Hech qanday ma'lumot saqlanmadi.")
            return True
        if raw.casefold() not in {"tasdiqlayman", "tasdiq", "ha", "import"}:
            await update.message.reply_text("Importni tasdiqlash uchun TASDIQLAYMAN yoki bekor qilish uchun BEKOR deb yozing.")
            return True
        validated = context.user_data.pop("_sc_excel_validated", None)
        if not validated:
            context.user_data.pop("_sc_wait", None)
            await update.message.reply_text("Import tasdiqlash ma'lumoti topilmadi. Excel faylni qayta yuboring.")
            return True
        import copy
        try:
            data = copy.deepcopy(_data())
            result = supply_chain_import.apply_import(data, validated)
            await _save(data)
        except sc_persistence.VersionConflict:
            context.user_data.pop("_sc_wait", None)
            await update.message.reply_text(
                "⚠️ Ma'lumotlar boshqa sessiyada yangilangan. Hech narsa ustidan yozilmadi. "
                "Excel faylni yangilangan ma'lumot bilan qayta ko'rib chiqing."
            )
            return True
        except sc_persistence.CommitOutcomeUnknown:
            context.user_data.pop("_sc_wait", None)
            await update.message.reply_text(
                "⚠️ Saqlash javobining holati noaniq. Importni qayta yubormang; avval ombor holatini tekshiring."
            )
            return True
        except sc_persistence.PersistenceError:
            context.user_data.pop("_sc_wait", None)
            await update.message.reply_text("⚠️ Import bazaga xavfsiz saqlanmadi. Hech qanday muvaffaqiyat tasdiqlanmadi.")
            return True
        except Exception as exc:
            context.user_data.pop("_sc_wait", None)
            await update.message.reply_text("⚠️ Import saqlanmadi: " + _friendly_error(exc))
            return True
        for key in ("_sc_excel_raw", "_sc_excel_overrides", "_sc_excel_preview", "_sc_wait"):
            context.user_data.pop(key, None)
        lines = ["✅ **Excel import yakunlandi**"]
        for key, label in (("products", "Mahsulot"), ("suppliers", "Yetkazib beruvchi"), ("demand", "Talab tarixi"),
                           ("orders", "Xarid buyurtmasi"), ("movements", "Ombor harakati")):
            if result.get(key):
                lines.append(f"• {label}: {result[key]} ta")
        lines.append(f"Xatolar/o'tkazilganlar: {len(result.get('errors', []))}")
        await _reply(update.message, "\n".join(lines), _home_keyboard())
        return True
    handler = _APPLY.get(str(action))
    if handler is None:
        return False
    if not raw:
        await update.message.reply_text("Matn bo'sh. Misol bilan yozing.")
        return True
    import copy
    result, error = None, None
    try:
        data = copy.deepcopy(_data())
        result = handler(data, raw)
        await _save(data)
    except sc_persistence.VersionConflict:
        error = ("Ma'lumotlar boshqa sessiyada yangilangan. Hech narsa ustidan yozilmadi. "
                 "Bo'limni qayta ochib, amalni yangilangan ma'lumot bilan takrorlang.")
    except sc_persistence.CommitOutcomeUnknown:
        error = ("Saqlash javobining holati noaniq. Amalni hozircha qayta yubormang; "
                 "avval ombor holatini yangilang va o'zgarish saqlanganini tekshiring.")
    except sc_persistence.PersistenceError:
        error = "Ma'lumotni bazaga xavfsiz saqlab bo'lmadi. Hech qanday muvaffaqiyat tasdiqlanmadi."
    except Exception as exc:  # noqa: BLE001 — foydalanuvchiga tushunarli xabar beramiz
        error = _friendly_error(exc)
    done_kb = InlineKeyboardMarkup([[_btn("✅ Tayyor — orqaga", parent)]])
    if error:
        await _reply(update.message, f"⚠️ {error}\n\nQayta yozing yoki «Orqaga» ni bosing.", done_kb)
    else:
        wait["started"] = datetime.now().timestamp()  # ketma-ket kiritish uchun rejim saqlanadi
        context.user_data["_sc_wait"] = wait
        await _reply(update.message, (result or "Bajarildi.") + "\n\n— Yana yozishingiz mumkin.", done_kb)
    return True


async def _inline_inventory_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if query is None:
        return
    if _OWNER_ID is None or int(query.from_user.id) != int(_OWNER_ID):
        await query.answer([], cache_time=2, is_personal=True)
        return
    term = _norm(query.query)
    if len(term) < 3:
        await query.answer([], cache_time=2, is_personal=True)
        return
    data = _data()
    results = []
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    for sku, product in data.get("products", {}).items():
        name = str(product.get("name", sku))
        if term not in _norm(name) and term not in _norm(sku):
            continue
        qty = _safe_num(product.get("quantity"))
        reorder = _safe_num(product.get("reorder_point"))
        eoq = _eoq_value(product)
        annual = _safe_num(product.get("annual_demand"))
        days = qty / (annual / 365) if annual > 0 else None
        status = "🔴 Buyurtma kerak" if (qty <= reorder if reorder > 0 else qty <= 0) else ("🟡 Diqqat" if days is not None and days < 20 else "🟢 Me’yorda")
        detail = f"{name}\nQoldiq: {_f(qty)} {product.get('unit', 'dona')}\nMinimum: {_f(reorder)}\nHolat: {status}"
        if days is not None:
            detail += f"\nTaxminiy yetish muddati: {days:.1f} kun"
        eoq_text = (("taxminiy " if eoq[1] else "") + _f(round(eoq[0], 1))) if eoq else "Ma’lumot yetarli emas"
        detail += f"\nEOQ: {eoq_text}"
        results.append(InlineQueryResultArticle(
            id=str(sku)[:64], title=name,
            description=f"Qoldiq: {_f(qty)} {product.get('unit', 'dona')} · {status}",
            input_message_content=InputTextMessageContent(detail),
        ))
        if len(results) >= 20:
            break
    await query.answer(results, cache_time=3, is_personal=True)


async def daily_report_loop(app: Application) -> None:
    """Send one idempotent 09:00 Uzbekistan-time inventory digest to the owner."""
    tz = timezone(timedelta(hours=5))
    while True:
        now = datetime.now(tz)
        today = now.date().isoformat()
        state = _LOAD("supply_chain_daily_report_state.json", {}) if _LOAD else {}
        already_sent = isinstance(state, dict) and state.get("sent_date") == today
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if target <= now:
            if already_sent:
                target += timedelta(days=1)
            else:
                target = now
        await asyncio.sleep(max(1, (target - now).total_seconds()))
        today = datetime.now(tz).date().isoformat()
        try:
            state = _LOAD("supply_chain_daily_report_state.json", {}) if _LOAD else {}
            if isinstance(state, dict) and state.get("sent_date") == today:
                continue
            data = _data()
            stats = _inventory_summary(data)
            yesterday = datetime.now(tz).date() - timedelta(days=1)
            movements = []
            for movement in data.get("movements", []):
                try:
                    stamp = datetime.fromisoformat(str(movement.get("created_at", "")).replace("Z", "+00:00"))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    if stamp.astimezone(tz).date() == yesterday:
                        movements.append(movement)
                except (TypeError, ValueError, OverflowError):
                    continue
            incoming = [m for m in movements if m.get("type") == "in"]
            outgoing = [m for m in movements if m.get("type") == "out"]
            def _movement_totals(rows):
                totals = {}
                for movement in rows:
                    product = data.get("products", {}).get(movement.get("sku"), {})
                    unit = str(product.get("unit") or "birlik")
                    totals[unit] = totals.get(unit, 0.0) + _safe_num(movement.get("quantity"))
                return ", ".join(f"{_f(value)} {unit}" for unit, value in sorted(totals.items())) or "0"
            in_qty = _movement_totals(incoming)
            out_qty = _movement_totals(outgoing)
            report = (
                f"☀️ **ERTALABKI OMBOR HISOBOTI** · {today}\n"
                f"🔴 Buyurtma kerak: **{len(stats['low'])} ta**\n"
                f"📥 Kechagi kirim: **{len(incoming)} operatsiya / {in_qty}**\n"
                f"📤 Kechagi chiqim: **{len(outgoing)} operatsiya / {out_qty}**"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🛒 {len(stats['low'])} ta mahsulotni ko‘rish", callback_data="sc:low_stock")]
            ])
            if _OWNER_ID is not None:
                await app.bot.send_message(chat_id=_OWNER_ID, text=report, reply_markup=keyboard, parse_mode="Markdown")
                if _SAVE:
                    await asyncio.to_thread(_SAVE, "supply_chain_daily_report_state.json", {"sent_date": today})
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed send is not marked as delivered; retry after a short delay.
            await asyncio.sleep(60)


async def _notify_persistence_error(update: Update, exc: Exception) -> None:
    message = update.effective_message
    if message is None and update.callback_query:
        message = update.callback_query.message
    if isinstance(exc, sc_persistence.VersionConflict):
        text = ("Ma'lumotlar boshqa sessiyada yangilangan. Hech narsa ustidan yozilmadi. "
                "Bo'limni qayta ochib, amalni yangilangan ma'lumot bilan takrorlang.")
    elif isinstance(exc, sc_persistence.CommitOutcomeUnknown):
        text = ("Saqlash javobining holati noaniq. Amalni hozircha qayta yubormang; "
                "avval ombor holatini yangilang va o'zgarish saqlanganini tekshiring.")
    else:
        text = "Ma'lumotni bazaga xavfsiz saqlab bo'lmadi. Hech qanday muvaffaqiyat tasdiqlanmadi."
    if message:
        await message.reply_text("⚠️ " + text)


async def _serialized_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _SC_MUTATION_LOCK:
        try:
            await _callback(update, context)
        except sc_persistence.PersistenceError as exc:
            await _notify_persistence_error(update, exc)


async def _serialized_excel_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _SC_MUTATION_LOCK:
        try:
            await _handle_excel_document(update, context)
        except sc_persistence.PersistenceError as exc:
            await _notify_persistence_error(update, exc)


async def _serialized_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    async with _SC_MUTATION_LOCK:
        try:
            return await _text(update, context)
        except sc_persistence.PersistenceError as exc:
            await _notify_persistence_error(update, exc)
            return True


def install(app: Application, load_json: Callable[[str, Any], Any], save_json: Callable[[str, Any], Any], owner_id: int | None, ai_client: Any = None, ai_model: str | None = None) -> None:
    global _LOAD, _SAVE, _OWNER_ID, _AI_CLIENT, _AI_MODEL
    _LOAD, _SAVE, _OWNER_ID = load_json, save_json, owner_id
    _AI_CLIENT = ai_client
    _AI_MODEL = (ai_model or "gemini-3.5-flash-lite").strip()
    app.add_handler(CommandHandler("supply", open_supply))
    app.add_handler(CallbackQueryHandler(_serialized_callback, pattern=r"^sc:"))
    try:
        from telegram.ext import InlineQueryHandler
        app.add_handler(InlineQueryHandler(_inline_inventory_search))
    except ImportError:
        # Lightweight test doubles may omit inline-query classes; production installs PTB 21.4.
        pass
    if owner_id:
        app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.User(user_id=owner_id) & (filters.VOICE | filters.AUDIO), _serialized_voice))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL, _serialized_excel_document))


def on_text_handler():
    return _serialized_text
