"""Fail-closed Telegram tenant context resolution.

This module is deliberately not wired into Supply Chain handlers yet. It provides
one tested boundary for the later handler adapter: company selection is only a
hint, and active membership plus every required permission are revalidated
server-side for each update before a company snapshot is loaded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


_COMPANY_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ACTIVE_COMPANY_KEY = "sc_active_company_id"


class TelegramTenantContextError(PermissionError):
    """A Telegram update has no valid, authorized tenant context."""


@dataclass(frozen=True)
class TelegramTenantContext:
    telegram_user_id: int
    company_id: str
    role: str
    snapshot: dict[str, Any]
    version: int


def select_active_company(user_data: dict[str, Any], company_id: str) -> None:
    """Store a company selector only; this function grants no authority."""
    if not isinstance(user_data, dict):
        raise TypeError("user_data must be a dictionary")
    if not isinstance(company_id, str) or not _COMPANY_ID.fullmatch(company_id):
        raise ValueError("Korxona identifikatori noto'g'ri.")
    user_data[_ACTIVE_COMPANY_KEY] = company_id.lower()


def clear_active_company(user_data: dict[str, Any]) -> None:
    if isinstance(user_data, dict):
        user_data.pop(_ACTIVE_COMPANY_KEY, None)


def resolve_telegram_tenant_context(
    update: Any,
    user_data: dict[str, Any],
    tenant_store: Any,
    required_permissions: Iterable[str],
) -> TelegramTenantContext:
    """Resolve a private-chat update to a live member and authorized snapshot.

    The company ID comes from user_data strictly as a selector. The user ID
    comes from Telegram's effective_user. All permissions are checked against
    current membership before reading the tenant snapshot.
    """
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if not chat or not user or str(getattr(chat, "type", "")) != "private":
        raise TelegramTenantContextError("Korxona Supply Chain faqat shaxsiy chatda ishlaydi.")

    try:
        telegram_user_id = int(user.id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise TelegramTenantContextError("Telegram foydalanuvchisi aniqlanmadi.") from exc
    if telegram_user_id <= 0:
        raise TelegramTenantContextError("Telegram foydalanuvchisi noto'g'ri.")

    company_id = user_data.get(_ACTIVE_COMPANY_KEY) if isinstance(user_data, dict) else None
    if not isinstance(company_id, str) or not _COMPANY_ID.fullmatch(company_id):
        raise TelegramTenantContextError("Avval /sc orqali korxonani tanlang.")

    permissions = tuple(required_permissions)
    if any(not isinstance(p, str) or not p.strip() for p in permissions):
        raise ValueError("required_permissions noto'g'ri.")
    if len(set(permissions)) != len(permissions):
        raise ValueError("required_permissions takrorlanmasligi kerak.")

    member = None
    try:
        # Each permission is re-authorized against the live database. This is
        # intentionally fail-closed and occurs before any tenant data read.
        for permission in permissions:
            current = tenant_store.require_permission(company_id, telegram_user_id, permission)
            if not isinstance(current, dict):
                raise TelegramTenantContextError("Korxona a'zoligi tasdiqlanmadi.")
            if member is not None and current.get("role") != member.get("role"):
                raise TelegramTenantContextError("Korxona roli tekshiruv vaqtida o'zgardi.")
            member = current
        if member is None:
            # Even a nominally read-only handler must declare its permission.
            raise TelegramTenantContextError("Amal uchun ruxsat belgilanmagan.")
        record = tenant_store.load_snapshot_record(company_id)
    except TelegramTenantContextError:
        raise
    except Exception as exc:
        raise TelegramTenantContextError(
            "Korxona a'zoligi yoki ruxsatini tekshirib bo'lmadi."
        ) from exc

    if not isinstance(record, dict) or record.get("company_id", "").lower() != company_id.lower():
        raise TelegramTenantContextError("Korxona ombori mos kelmadi.")
    snapshot = record.get("data")
    version = record.get("version")
    if (not isinstance(snapshot, dict) or isinstance(version, bool)
            or not isinstance(version, int) or version < 1):
        raise TelegramTenantContextError("Korxona ombor versiyasi noto'g'ri.")

    return TelegramTenantContext(
        telegram_user_id=telegram_user_id,
        company_id=company_id.lower(),
        role=str(member.get("role") or ""),
        snapshot=snapshot,
        version=version,
    )


async def telegram_company_list(update: Any, context: Any, tenant_store_factory: Any) -> None:
    """Show the caller's active company memberships; this does not open data."""
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (not chat or not user or str(getattr(chat, "type", "")) != "private"
            or message is None):
        return
    try:
        store = tenant_store_factory()
        companies = store.list_companies(int(user.id))
    except Exception:
        await message.reply_text("Korxonalar ro'yxatini hozir yuklab bo'lmadi. Keyinroq urinib ko'ring.")
        return

    if not companies:
        await message.reply_text(
            "Siz hali hech qaysi korxonaga faol a'zo emassiz. "
            "Korxona egasidan taklif havolasi yoki kodini oling."
        )
        return

    # Import Telegram UI types lazily so this module's authorization helpers
    # remain independently testable without Telegram objects.
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for row in companies[:20]:
        if not isinstance(row, dict):
            continue
        company = row.get("sc_companies")
        if isinstance(company, list):
            company = company[0] if company else None
        if not isinstance(company, dict):
            continue
        company_id = company.get("id") or row.get("company_id")
        name = str(company.get("name") or "Korxona").strip()[:48]
        if not isinstance(company_id, str) or not _COMPANY_ID.fullmatch(company_id):
            continue
        rows.append([InlineKeyboardButton(
            f"{name} · {str(row.get('role') or 'a’zo')[:16]}",
            callback_data="sctenant:" + company_id.lower(),
        )])
    if not rows:
        await message.reply_text("Faol korxonalar ro'yxatida yaroqli yozuv topilmadi.")
        return
    await message.reply_text(
        "Ishlamoqchi bo'lgan korxonangizni tanlang. Tanlovning o'zi ruxsat bermaydi; "
        "har bir amal oldidan a'zolik qayta tekshiriladi.",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def telegram_company_select(update: Any, context: Any, tenant_store_factory: Any) -> None:
    """Select a company only after rechecking the caller's active membership."""
    query = getattr(update, "callback_query", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if (query is None or not chat or not user
            or str(getattr(chat, "type", "")) != "private"):
        return
    raw = str(getattr(query, "data", "") or "")
    company_id = raw.partition(":")[2]
    if not _COMPANY_ID.fullmatch(company_id):
        await query.answer("Korxona identifikatori noto'g'ri.", show_alert=True)
        return
    try:
        store = tenant_store_factory()
        member = store.membership(company_id, int(user.id))
        if not isinstance(member, dict) or member.get("status") != "active":
            await query.answer("Bu korxonaga faol a'zoligingiz yo'q.", show_alert=True)
            return
        user_data = getattr(context, "user_data", None)
        if not isinstance(user_data, dict):
            await query.answer("Foydalanuvchi sessiyasi mavjud emas.", show_alert=True)
            return
        select_active_company(user_data, company_id)
        await query.answer("Korxona tanlandi.")
        await query.edit_message_text(
            "Tanlangan korxona: " + company_id[:8] +
            "\nBu faqat tanlov. Omborni /sc_ombor orqali ko'rishingiz mumkin; o'zgartirishlar hali ulanmagan."
        )
    except Exception:
        await query.answer("A'zolikni tekshirib bo'lmadi. Keyinroq urinib ko'ring.", show_alert=True)


async def telegram_inventory_overview(update: Any, context: Any, tenant_store_factory: Any) -> None:
    """Read-only company inventory overview with live membership validation."""
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (not chat or not user or str(getattr(chat, "type", "")) != "private"
            or message is None):
        return
    try:
        user_data = getattr(context, "user_data", None)
        tenant_context = resolve_telegram_tenant_context(
            update, user_data if isinstance(user_data, dict) else {},
            tenant_store_factory(), ("inventory.read",),
        )
        products = tenant_context.snapshot.get("products")
        if not isinstance(products, dict):
            raise TelegramTenantContextError("Korxona omboridagi mahsulotlar ro'yxati noto'g'ri.")
        rows = []
        for sku, raw in products.items():
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or sku).replace("\n", " ").strip()[:70]
            unit = str(raw.get("unit") or "dona").replace("\n", " ").strip()[:12]
            quantity = str(raw.get("quantity", 0)).replace("\n", " ").replace("\r", " ")[:24]
            reorder = str(raw.get("reorder_point", 0)).replace("\n", " ").replace("\r", " ")[:24]
            rows.append((name.casefold(), str(sku)[:40], name, quantity, unit, reorder))
        rows.sort(key=lambda item: (item[0], item[1]))
        if not rows:
            await message.reply_text("Tanlangan korxona omborida hozircha mahsulot yo'q.")
            return
        lines = [
            f"📦 {tenant_context.company_id[:8]} — Ombor",
            f"Mahsulotlar soni: {len(rows)}",
            "",
        ]
        for _sort, sku, name, quantity, unit, reorder in rows[:15]:
            lines.append(f"• {name} ({sku})")
            lines.append(f"  Qoldiq: {quantity} {unit} · ROP: {reorder} {unit}")
        if len(rows) > 15:
            lines.append(f"\nYana {len(rows) - 15} ta mahsulot bor. Dastlabki 15 tasi ko'rsatildi.")
        lines.append("\nBu faqat ko'rish rejimi. Ma'lumot o'zgartirilmaydi.")
        await message.reply_text("\n".join(lines))
    except TelegramTenantContextError as exc:
        await message.reply_text(str(exc))
    except Exception:
        await message.reply_text("Korxona omborini yuklab bo'lmadi. Ruxsat yoki baza holatini tekshiring.")



async def telegram_inventory_add(update: Any, context: Any, tenant_store_factory: Any) -> None:
    """Add one inventory item to the selected tenant with CAS and replay safety."""
    import hashlib
    import json
    import math

    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (not chat or not user or str(getattr(chat, "type", "")) != "private"
            or message is None):
        return
    text = str(getattr(message, "text", "") or "")
    _command, separator, raw = text.partition(" ")
    if not separator:
        await message.reply_text(
            "Format: /sc_qosh SKU | Nomi | Miqdor | Birlik | ROP\n"
            "Misol: /sc_qosh SKU-01 | Shakar | 100 | kg | 10"
        )
        return
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 5:
        await message.reply_text(
            "5 ta maydon kerak: SKU | Nomi | Miqdor | Birlik | ROP"
        )
        return
    sku, name, quantity_raw, unit, reorder_raw = parts
    if (not 1 <= len(sku) <= 64 or not 2 <= len(name) <= 120
            or not 1 <= len(unit) <= 12 or any("\n" in p or "\r" in p for p in parts)):
        await message.reply_text("SKU, nom yoki birlik uzunligi noto'g'ri.")
        return
    try:
        quantity = float(quantity_raw.replace(",", "."))
        reorder = float(reorder_raw.replace(",", "."))
        if not math.isfinite(quantity) or not math.isfinite(reorder) or quantity < 0 or reorder < 0:
            raise ValueError
    except (TypeError, ValueError):
        await message.reply_text("Miqdor va ROP manfiy bo'lmagan son bo'lishi kerak.")
        return

    payload = {
        "action": "inventory_add", "sku": sku, "name": name,
        "quantity": quantity, "unit": unit, "reorder_point": reorder,
    }
    update_id = getattr(update, "update_id", None)
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        await message.reply_text("Telegram amal identifikatori aniqlanmadi. Qayta yuboring.")
        return

    try:
        user_data = getattr(context, "user_data", None)
        store = tenant_store_factory()
        tenant_context = resolve_telegram_tenant_context(
            update, user_data if isinstance(user_data, dict) else {},
            store, ("inventory.write",),
        )
        operation_id = f"tg-{update_id}-{tenant_context.company_id[:8]}-inventory-add"
        request_hash = hashlib.sha256(json.dumps(
            {"company_id": tenant_context.company_id, "request": payload},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()

        def mutate(snapshot: dict[str, Any]) -> dict[str, Any]:
            products = snapshot.get("products")
            if not isinstance(products, dict):
                raise TelegramTenantContextError("Korxona mahsulotlar ro'yxati noto'g'ri.")
            if len(products) >= 10000:
                raise TelegramTenantContextError("Mahsulotlar limiti to'lgan.")
            if any(str(existing).casefold() == sku.casefold() for existing in products):
                raise TelegramTenantContextError("Bu SKU korxona omborida allaqachon mavjud.")
            products[sku] = {
                "sku": sku, "name": name, "quantity": quantity, "unit": unit,
                "reorder_point": reorder, "unit_cost": 0.0, "annual_demand": 0.0,
                "order_cost": 0.0, "holding_cost": 0.0,
            }
            return {"sku": sku, "name": name, "quantity": quantity, "unit": unit}

        result = store.mutate_snapshot(
            tenant_context.company_id, tenant_context.telegram_user_id,
            "inventory.write", mutate, expected_version=tenant_context.version,
            operation_id=operation_id, request_hash=request_hash,
        )
        item = result.get("result") or {}
        replay_note = " (takroriy so'rov — avvalgi natija)" if result.get("replayed") else ""
        await message.reply_text(
            f"✅ {item.get('name', name)} qo'shildi: "
            f"{item.get('quantity', quantity)} {item.get('unit', unit)} · "
            f"SKU: {item.get('sku', sku)}{replay_note}"
        )
    except TelegramTenantContextError as exc:
        await message.reply_text(str(exc))
    except Exception as exc:
        # Keep database/internal details out of Telegram messages.
        from supply_chain_tenants import SnapshotVersionConflict, PermissionDenied, MembershipRequired
        if isinstance(exc, SnapshotVersionConflict):
            await message.reply_text("Ombor ma'lumotlari yangilangan. /sc_ombor bilan tekshirib, qayta urinib ko'ring.")
        elif isinstance(exc, (PermissionDenied, MembershipRequired)):
            await message.reply_text("Bu korxonada omborga mahsulot qo'shish huquqingiz yo'q.")
        else:
            await message.reply_text("Mahsulot saqlanmadi. Ruxsat va baza holatini tekshiring, keyin qayta urinib ko'ring.")




async def telegram_purchase_order_add(update: Any, context: Any, tenant_store_factory: Any) -> None:
    """Create a draft PO inside the active tenant, with CAS and replay protection."""
    import hashlib
    import json
    import math
    import uuid
    from datetime import date, datetime, timedelta, timezone
    from supply_chain_tenants import SnapshotVersionConflict, PermissionDenied, MembershipRequired

    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if message is None or not chat or not user or str(getattr(chat, "type", "")) != "private":
        return
    _command, separator, raw = str(getattr(message, "text", "") or "").partition(" ")
    if not separator:
        await message.reply_text(
            "Format: /sc_buyurtma SKU | Yetkazib beruvchi ID | Miqdor | Birlik narxi | Sana (YYYY-MM-DD)\\n"
            "Misol: /sc_buyurtma SKU-01 | SUP-01 | 100 | 18000 | 2026-12-05"
        )
        return
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 5 or any(not part for part in parts):
        await message.reply_text("5 ta maydon kerak: SKU | Yetkazib beruvchi ID | Miqdor | Birlik narxi | Sana")
        return
    sku, supplier_id, qty_raw, price_raw, expected = parts
    try:
        qty = float(qty_raw.replace(",", "."))
        price = float(price_raw.replace(",", "."))
        date.fromisoformat(expected)
        if not math.isfinite(qty) or not math.isfinite(price) or qty <= 0 or price <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await message.reply_text("Miqdor va narx musbat son, sana esa YYYY-MM-DD formatida bo'lishi kerak.")
        return
    update_id = getattr(update, "update_id", None)
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        await message.reply_text("Telegram amal identifikatori aniqlanmadi. Qayta yuboring.")
        return
    try:
        user_data = getattr(context, "user_data", None)
        store = tenant_store_factory()
        tenant_context = resolve_telegram_tenant_context(
            update, user_data if isinstance(user_data, dict) else {}, store, ("procurement.write",)
        )
        payload = {"sku": sku, "supplier_id": supplier_id, "quantity": qty,
                   "unit_price": price, "expected_date": expected}
        request_hash = hashlib.sha256(json.dumps(
            {"company_id": tenant_context.company_id, "request": payload},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        operation_id = f"tg-{update_id}-{tenant_context.company_id[:8]}-po-add"

        def mutate(snapshot: dict[str, Any]) -> dict[str, Any]:
            products = snapshot.get("products")
            suppliers = snapshot.get("suppliers")
            orders = snapshot.setdefault("orders", [])
            if not isinstance(products, dict) or not isinstance(suppliers, dict) or not isinstance(orders, list):
                raise TelegramTenantContextError("Xarid ma'lumotlari noto'g'ri.")
            product = next((v for k, v in products.items() if str(k).casefold() == sku.casefold()), None)
            supplier = next((v for k, v in suppliers.items() if str(k).casefold() == supplier_id.casefold()), None)
            if not isinstance(product, dict):
                raise TelegramTenantContextError("Bu SKU korxona omborida topilmadi.")
            if not isinstance(supplier, dict):
                raise TelegramTenantContextError("Bu yetkazib beruvchi korxonada topilmadi.")
            oid = "PO-" + uuid.uuid4().hex[:8].upper()
            order = {
                "id": oid, "sku": str(product.get("sku") or sku),
                "supplier_id": str(supplier.get("id") or supplier_id),
                "quantity": qty, "unit_price": price, "expected_date": expected,
                "status": "draft", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            orders.append(order)
            if len(orders) > 10000:
                del orders[:-10000]
            return {"id": oid, "sku": order["sku"], "product_name": str(product.get("name") or sku),
                    "supplier_name": str(supplier.get("name") or supplier_id),
                    "quantity": qty, "unit": str(product.get("unit") or "dona"),
                    "unit_price": price, "total": qty * price, "expected_date": expected}

        result = store.mutate_snapshot(
            tenant_context.company_id, tenant_context.telegram_user_id, "procurement.write",
            mutate, expected_version=tenant_context.version, operation_id=operation_id, request_hash=request_hash,
        )
        item = result.get("result") or {}
        replay = " (takroriy so'rov — ikkinchi buyurtma yaratilmadi)" if result.get("replayed") else ""
        await message.reply_text(
            f"✅ Xarid buyurtmasi qoralamasi: {item.get('id')}\\n"
            f"{item.get('product_name')} · {item.get('quantity'):g} {item.get('unit')} × "
            f"{item.get('unit_price'):g} = {item.get('total'):g}\\n"
            f"Yetkazib beruvchi: {item.get('supplier_name')} · Sana: {item.get('expected_date')}\\n"
            f"Holat: qoralama. Berish uchun /sc_buyurtma_ber {item.get('id')}{replay}"
        )
    except TelegramTenantContextError as exc:
        await message.reply_text(str(exc))
    except (SnapshotVersionConflict, PermissionDenied, MembershipRequired):
        await message.reply_text("Xarid yozish huquqi yoki korxona versiyasi mos kelmadi. /sc orqali qayta tekshiring.")
    except Exception:
        await message.reply_text("Xarid buyurtmasi saqlanmadi. Ruxsat va baza holatini tekshiring.")


async def telegram_purchase_order_transition(update: Any, context: Any, tenant_store_factory: Any,
                                             action: str) -> None:
    """Mark a PO ordered or receive it with AVCO; receiving also needs inventory.write."""
    import hashlib
    import json
    import math
    from datetime import datetime, timezone
    from supply_chain_tenants import SnapshotVersionConflict, PermissionDenied, MembershipRequired

    permissions = {
        "ordered": ("procurement.write",),
        "received": ("procurement.write", "inventory.write"),
    }
    if action not in permissions:
        return
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if message is None or not chat or not user or str(getattr(chat, "type", "")) != "private":
        return
    _command, separator, order_id = str(getattr(message, "text", "") or "").partition(" ")
    order_id = order_id.strip()
    if not separator or not order_id or len(order_id) > 40:
        command = "sc_buyurtma_ber" if action == "ordered" else "sc_buyurtma_qabul"
        await message.reply_text(f"Format: /{command} PO-ID")
        return
    update_id = getattr(update, "update_id", None)
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        await message.reply_text("Telegram amal identifikatori aniqlanmadi. Qayta yuboring.")
        return
    try:
        user_data = getattr(context, "user_data", None)
        store = tenant_store_factory()
        tenant_context = resolve_telegram_tenant_context(
            update, user_data if isinstance(user_data, dict) else {}, store, permissions[action]
        )
        payload = {"action": action, "order_id": order_id}
        request_hash = hashlib.sha256(json.dumps(
            {"company_id": tenant_context.company_id, "request": payload},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        operation_id = f"tg-{update_id}-{tenant_context.company_id[:8]}-po-{action}"

        def mutate(snapshot: dict[str, Any]) -> dict[str, Any]:
            orders = snapshot.get("orders")
            if not isinstance(orders, list):
                raise TelegramTenantContextError("Xarid buyurtmalari ro'yxati noto'g'ri.")
            order = next((x for x in orders if isinstance(x, dict) and str(x.get("id")) == order_id), None)
            if not order:
                raise TelegramTenantContextError("Bu korxonada buyurtma topilmadi.")
            if action == "ordered":
                if order.get("status") != "draft":
                    raise TelegramTenantContextError("Faqat qoralama buyurtmani yetkazib beruvchiga berish mumkin.")
                order["status"] = "ordered"
                order["ordered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                return {"id": order_id, "status": "ordered", "message": "Buyurtma yetkazib beruvchiga berildi."}

            if order.get("status") != "ordered":
                raise TelegramTenantContextError("Faqat berilgan buyurtmani qabul qilish mumkin.")
            products = snapshot.get("products")
            if not isinstance(products, dict):
                raise TelegramTenantContextError("Ombor mahsulotlari ro'yxati noto'g'ri.")
            product = next((v for k, v in products.items()
                            if str(k).casefold() == str(order.get("sku", "")).casefold()), None)
            if not isinstance(product, dict):
                raise TelegramTenantContextError("Mahsulot topilmadi; zaxira o'zgartirilmadi.")
            try:
                qty = float(order.get("quantity", 0))
                purchase_price = float(order.get("unit_price", 0))
                old_qty = float(product.get("quantity", 0))
                old_cost = float(product.get("unit_cost", 0))
            except (TypeError, ValueError, OverflowError):
                raise TelegramTenantContextError("AVCO uchun miqdor yoki tannarx noto'g'ri.")
            if (not all(math.isfinite(x) for x in (qty, purchase_price, old_qty, old_cost))
                    or qty <= 0 or purchase_price <= 0 or old_qty < 0 or old_cost < 0):
                raise TelegramTenantContextError("AVCO uchun miqdor va narxlar musbat, zaxira esa manfiy bo'lmasligi kerak.")
            if old_qty > 0 and old_cost <= 0:
                raise TelegramTenantContextError("Mavjud zaxiraning tannarxi kiritilmagan. Avval unit_cost ni to'g'rilang.")
            new_qty = old_qty + qty
            previous_cost = old_cost
            new_cost = ((old_qty * old_cost) + (qty * purchase_price)) / new_qty
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            product["quantity"] = new_qty
            product["unit_cost"] = new_cost
            product["updated_at"] = now
            order["status"] = "received"
            order["received_at"] = now
            order["previous_unit_cost"] = previous_cost
            order["received_unit_cost"] = new_cost
            movements = snapshot.setdefault("movements", [])
            if not isinstance(movements, list):
                raise TelegramTenantContextError("Ombor harakatlari ro'yxati noto'g'ri.")
            movements.append({
                "id": hashlib.sha256(f"{tenant_context.company_id}:{update_id}:po-receipt".encode()).hexdigest()[:12],
                "sku": order.get("sku"), "type": "in", "quantity": qty, "unit_cost": purchase_price,
                "total_cost": qty * purchase_price, "note": f"Xarid buyurtmasi {order_id} qabul qilindi; AVCO yangilandi",
                "created_at": now, "order_id": order_id,
            })
            if len(movements) > 50000:
                del movements[:-50000]
            return {"id": order_id, "status": "received", "quantity": qty,
                    "unit": str(product.get("unit") or "dona"),
                    "previous_cost": previous_cost, "new_cost": new_cost, "remaining": new_qty}

        result = store.mutate_snapshot(
            tenant_context.company_id, tenant_context.telegram_user_id,
            "procurement.write" if action == "ordered" else "inventory.write",
            mutate, expected_version=tenant_context.version, operation_id=operation_id, request_hash=request_hash,
        )
        item = result.get("result") or {}
        replay = " (takroriy so'rov — qayta qo'llanmadi)" if result.get("replayed") else ""
        if action == "ordered":
            reply = f"✅ {item.get('message', 'Buyurtma berildi')} · {order_id}{replay}"
        else:
            reply = (f"✅ {order_id} qabul qilindi · Omborga +{item.get('quantity'):g} {item.get('unit')}\\n"
                     f"Qoldiq: {item.get('remaining'):g} {item.get('unit')} · "
                     f"AVCO: {item.get('previous_cost'):g} → {item.get('new_cost'):g}{replay}")
        await message.reply_text(reply)
    except TelegramTenantContextError as exc:
        await message.reply_text(str(exc))
    except (SnapshotVersionConflict, PermissionDenied, MembershipRequired):
        await message.reply_text("Xarid/ombor huquqi yoki korxona versiyasi mos kelmadi. /sc orqali qayta tekshiring.")
    except Exception:
        await message.reply_text("Buyurtma holati saqlanmadi. Baza va ruxsatlarni tekshiring.")


def register_telegram_company_selector(app: Any, tenant_store_factory: Any) -> None:
    """Register the company selector and the isolated read-only inventory command."""
    from telegram.ext import CallbackQueryHandler, CommandHandler

    app.add_handler(CommandHandler("sc", lambda update, context: telegram_company_list(
        update, context, tenant_store_factory
    )))
    app.add_handler(CommandHandler("sc_ombor", lambda update, context: telegram_inventory_overview(
        update, context, tenant_store_factory
    )))
    app.add_handler(CommandHandler("sc_qosh", lambda update, context: telegram_inventory_add(
        update, context, tenant_store_factory
    )))
    app.add_handler(CommandHandler("sc_kirim", lambda update, context: telegram_inventory_movement(
        update, context, tenant_store_factory, "in"
    )))
    app.add_handler(CommandHandler("sc_chiqim", lambda update, context: telegram_inventory_movement(
        update, context, tenant_store_factory, "out"
    )))
    app.add_handler(CommandHandler("sc_yetkazuvchi", lambda update, context: telegram_supplier_add(
        update, context, tenant_store_factory
    )))
    app.add_handler(CommandHandler("sc_buyurtma", lambda update, context: telegram_purchase_order_add(
        update, context, tenant_store_factory
    )))
    app.add_handler(CommandHandler("sc_buyurtma_ber", lambda update, context: telegram_purchase_order_transition(
        update, context, tenant_store_factory, "ordered"
    )))
    app.add_handler(CommandHandler("sc_buyurtma_qabul", lambda update, context: telegram_purchase_order_transition(
        update, context, tenant_store_factory, "received"
    )))
    app.add_handler(CallbackQueryHandler(
        lambda update, context: telegram_company_select(update, context, tenant_store_factory),
        pattern=r"^sctenant:",
    ))


async def telegram_inventory_movement(update: Any, context: Any, tenant_store_factory: Any,
                                      action: str) -> None:
    """Apply a tenant-scoped stock-in/out mutation with CAS and replay safety."""
    import hashlib
    import json
    import math
    from datetime import datetime, timezone
    from supply_chain_tenants import SnapshotVersionConflict, PermissionDenied, MembershipRequired

    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if (action not in {"in", "out"} or message is None or not chat or not user
            or str(getattr(chat, "type", "")) != "private"):
        return
    raw_text = str(getattr(message, "text", "") or "")
    _command, separator, raw = raw_text.partition(" ")
    if not separator:
        command = "sc_kirim" if action == "in" else "sc_chiqim"
        await message.reply_text(
            f"Format: /{command} SKU | Miqdor | Izoh\n"
            f"Misol: /{command} SKU-01 | 25 | Ombor hujjati"
        )
        return
    parts = [part.strip() for part in raw.split("|", 2)]
    if len(parts) != 3 or not parts[0] or not parts[2] or any("\n" in p or "\r" in p for p in parts):
        await message.reply_text("3 ta maydon kerak: SKU | Miqdor | Izoh")
        return
    sku, amount_raw, note = parts
    try:
        amount = float(amount_raw.replace(",", "."))
        if not math.isfinite(amount) or amount <= 0 or amount > 1_000_000_000:
            raise ValueError
    except (TypeError, ValueError):
        await message.reply_text("Miqdor musbat va chekli son bo'lishi kerak.")
        return
    update_id = getattr(update, "update_id", None)
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        await message.reply_text("Telegram amal identifikatori aniqlanmadi. Qayta yuboring.")
        return
    try:
        user_data = getattr(context, "user_data", None)
        store = tenant_store_factory()
        tenant_context = resolve_telegram_tenant_context(
            update, user_data if isinstance(user_data, dict) else {},
            store, ("movement.write",),
        )
        payload = {"action": action, "sku": sku, "quantity": amount, "note": note}
        request_hash = hashlib.sha256(json.dumps(
            {"company_id": tenant_context.company_id, "request": payload},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        operation_id = f"tg-{update_id}-{tenant_context.company_id[:8]}-movement-{action}"

        def mutate(snapshot: dict[str, Any]) -> dict[str, Any]:
            products = snapshot.get("products")
            movements = snapshot.setdefault("movements", [])
            if not isinstance(products, dict) or not isinstance(movements, list):
                raise TelegramTenantContextError("Korxona ombor ma'lumotlari noto'g'ri.")
            product = next((value for key, value in products.items()
                            if str(key).casefold() == sku.casefold()), None)
            if not isinstance(product, dict):
                raise TelegramTenantContextError("Bu SKU korxona omborida topilmadi.")
            try:
                current = float(product.get("quantity", 0))
            except (TypeError, ValueError):
                raise TelegramTenantContextError("Mahsulot qoldig'i noto'g'ri.")
            if not math.isfinite(current) or current < 0:
                raise TelegramTenantContextError("Mahsulot qoldig'i noto'g'ri.")
            if action == "out" and current < amount:
                raise TelegramTenantContextError(
                    f"Omborda yetarli qoldiq yo'q. Mavjud: {current:g} {product.get('unit', 'dona')}."
                )
            updated = current + amount if action == "in" else current - amount
            product["quantity"] = updated
            product["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            movement_id = hashlib.sha256(
                f"{tenant_context.company_id}:{update_id}:{action}".encode("utf-8")
            ).hexdigest()[:12]
            movements.append({
                "id": movement_id, "sku": product.get("sku") or sku,
                "type": action, "quantity": amount, "note": note[:240],
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            if len(movements) > 50000:
                del movements[:-50000]
            return {"sku": product.get("sku") or sku, "name": str(product.get("name") or sku),
                    "quantity": amount, "remaining": updated, "unit": str(product.get("unit") or "dona")}

        result = store.mutate_snapshot(
            tenant_context.company_id, tenant_context.telegram_user_id,
            "movement.write", mutate, expected_version=tenant_context.version,
            operation_id=operation_id, request_hash=request_hash,
        )
        item = result.get("result") or {}
        label = "Kirim" if action == "in" else "Chiqim"
        replay = " (takroriy so'rov — qayta qo'shilmadi)" if result.get("replayed") else ""
        await message.reply_text(
            f"✅ {label}: {item.get('name', sku)} · {item.get('quantity', amount):g} "
            f"{item.get('unit', 'dona')}\nQoldiq: {item.get('remaining', 0):g} "
            f"{item.get('unit', 'dona')}{replay}"
        )
    except TelegramTenantContextError as exc:
        await message.reply_text(str(exc))
    except (SnapshotVersionConflict, PermissionDenied, MembershipRequired):
        await message.reply_text("Ruxsat yoki ombor versiyasi mos kelmadi. /sc_ombor bilan tekshirib qayta urinib ko'ring.")
    except Exception:
        await message.reply_text("Ombor harakati saqlanmadi. Baza holatini tekshirib, keyin qayta urinib ko'ring.")


async def telegram_supplier_add(update: Any, context: Any, tenant_store_factory: Any) -> None:
    """Create a supplier in the selected company; never touches legacy owner storage."""
    import hashlib
    import json
    import math
    from datetime import datetime, timezone
    from supply_chain_tenants import SnapshotVersionConflict, PermissionDenied, MembershipRequired

    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if message is None or not chat or not user or str(getattr(chat, "type", "")) != "private":
        return
    raw_text = str(getattr(message, "text", "") or "")
    _command, separator, raw = raw_text.partition(" ")
    if not separator:
        await message.reply_text(
            "Format: /sc_yetkazuvchi ID | Nomi | Yetkazish muddati (kun)\n"
            "Misol: /sc_yetkazuvchi SUP-01 | Atlas Textile | 7"
        )
        return
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 3 or not parts[0] or not parts[1] or any("\n" in p or "\r" in p for p in parts):
        await message.reply_text("Uchta maydon kerak: ID | Nomi | Yetkazish muddati (kun)")
        return
    supplier_id, name, lead_raw = parts
    if len(supplier_id) > 40 or len(name) > 120:
        await message.reply_text("ID yoki yetkazib beruvchi nomi juda uzun.")
        return
    try:
        lead_days = float(lead_raw.replace(",", "."))
        if not math.isfinite(lead_days) or lead_days < 0 or lead_days > 3650:
            raise ValueError
    except ValueError:
        await message.reply_text("Yetkazish muddati 0–3650 kun oralig'idagi son bo'lishi kerak.")
        return
    update_id = getattr(update, "update_id", None)
    if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
        await message.reply_text("Telegram amal identifikatori aniqlanmadi. Qayta yuboring.")
        return
    try:
        user_data = getattr(context, "user_data", None)
        store = tenant_store_factory()
        tenant_context = resolve_telegram_tenant_context(
            update, user_data if isinstance(user_data, dict) else {},
            store, ("procurement.write",),
        )
        payload = {"supplier_id": supplier_id, "name": name, "lead_time_days": lead_days}
        request_hash = hashlib.sha256(json.dumps(
            {"company_id": tenant_context.company_id, "request": payload},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        operation_id = f"tg-{update_id}-{tenant_context.company_id[:8]}-supplier-add"

        def mutate(snapshot: dict[str, Any]) -> dict[str, Any]:
            suppliers = snapshot.setdefault("suppliers", {})
            if not isinstance(suppliers, dict):
                raise TelegramTenantContextError("Yetkazib beruvchi ma'lumotlari noto'g'ri.")
            if any(str(key).casefold() == supplier_id.casefold() for key in suppliers):
                raise TelegramTenantContextError("Bu yetkazib beruvchi ID avval ishlatilgan.")
            suppliers[supplier_id] = {
                "id": supplier_id, "name": name, "lead_time_days": lead_days,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            return {"id": supplier_id, "name": name, "lead_time_days": lead_days}

        result = store.mutate_snapshot(
            tenant_context.company_id, tenant_context.telegram_user_id,
            "procurement.write", mutate, expected_version=tenant_context.version,
            operation_id=operation_id, request_hash=request_hash,
        )
        item = result.get("result") or {}
        replay = " (takroriy so'rov — qayta yaratilmadi)" if result.get("replayed") else ""
        await message.reply_text(
            f"✅ Yetkazib beruvchi qo'shildi: {item.get('name', name)} · "
            f"ID: {item.get('id', supplier_id)} · Yetkazish: {item.get('lead_time_days', lead_days):g} kun{replay}"
        )
    except TelegramTenantContextError as exc:
        await message.reply_text(str(exc))
    except (SnapshotVersionConflict, PermissionDenied, MembershipRequired):
        await message.reply_text("Ruxsat yoki korxona ma'lumotlari versiyasi mos kelmadi. /sc orqali qayta tekshiring.")
    except Exception:
        await message.reply_text("Yetkazib beruvchi saqlanmadi. Ruxsat va baza holatini tekshiring.")
