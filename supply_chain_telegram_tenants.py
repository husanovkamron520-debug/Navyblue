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
