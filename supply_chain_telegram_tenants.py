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
            name = str(raw.get("name") or sku).replace("\\n", " ").strip()[:70]
            unit = str(raw.get("unit") or "dona").replace("\\n", " ").strip()[:12]
            quantity = raw.get("quantity", 0)
            reorder = raw.get("reorder_point", 0)
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
        await message.reply_text("\\n".join(lines))
    except TelegramTenantContextError as exc:
        await message.reply_text(str(exc))
    except Exception:
        await message.reply_text("Korxona omborini yuklab bo'lmadi. Ruxsat yoki baza holatini tekshiring.")



def register_telegram_company_selector(app: Any, tenant_store_factory: Any) -> None:
    """Register the safe /sc company selector; no business handlers are enabled."""
    from telegram.ext import CallbackQueryHandler, CommandHandler

    app.add_handler(CommandHandler("sc", lambda update, context: telegram_company_list(
        update, context, tenant_store_factory
    )))
    app.add_handler(CommandHandler("sc_ombor", lambda update, context: telegram_inventory_overview(
        update, context, tenant_store_factory
    )))
    app.add_handler(CallbackQueryHandler(
        lambda update, context: telegram_company_select(update, context, tenant_store_factory),
        pattern=r"^sctenant:",
    ))
