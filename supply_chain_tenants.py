"""Server-side multi-company tenancy helpers for Navyblue Supply Chain.

This module is intentionally not wired into public bot/API routes yet. Callers
must authenticate Telegram identities first and keep the Supabase service-role
key exclusively on the server. Never accept a company_id or role as proof of
authorization from a client.
"""
from __future__ import annotations

import copy
import hashlib
import secrets
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Callable


class TenantError(RuntimeError):
    pass


class MembershipRequired(TenantError):
    pass


class PermissionDenied(TenantError):
    pass


class TenantStore:
    """Small server-only repository around the existing Supabase REST adapter."""

    ROLES = {"owner", "admin", "warehouse", "purchasing", "transport", "viewer"}
    WRITE_ROLES = {
        "owner": {"*"},
        "admin": {"*"},
        "warehouse": {"inventory.read", "inventory.write", "movement.write", "reports.read"},
        "purchasing": {"inventory.read", "procurement.read", "procurement.write", "reports.read"},
        "transport": {"inventory.read", "logistics.read", "logistics.write", "reports.read"},
        "viewer": {"inventory.read", "procurement.read", "logistics.read", "reports.read"},
    }

    def __init__(self, db_request: Callable[..., Any]):
        if not callable(db_request):
            raise TypeError("db_request must be callable")
        self._db_request = db_request

    def _rpc(self, name: str, payload: dict) -> Any:
        if not re.fullmatch(r"sc_[a-z_]+", name):
            raise ValueError("invalid RPC name")
        return self._db_request("POST", "rpc/" + name, payload)

    @staticmethod
    def _telegram_id(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("invalid Telegram user ID")
        try:
            user_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Telegram user ID") from exc
        if user_id <= 0:
            raise ValueError("invalid Telegram user ID")
        return user_id

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
        slug = slug[:63].strip("-")
        # Cyrillic and other non-Latin company names are valid. The slug is
        # an internal URL-safe identifier, so fall back to a random neutral base.
        if len(slug) < 2:
            slug = "company-" + secrets.token_hex(4)
        return slug

    def create_company(self, name: str, owner_telegram_id: int) -> dict:
        name = str(name or "").strip()
        if not 2 <= len(name) <= 160:
            raise ValueError("Korxona nomi 2–160 belgi bo'lishi kerak.")
        owner_id = self._telegram_id(owner_telegram_id)
        # A random suffix prevents collisions without exposing internal IDs.
        slug = self._slug(name)[:52] + "-" + secrets.token_hex(4)
        result = self._rpc("sc_create_company", {
            "p_name": name,
            "p_slug": slug,
            "p_owner_telegram_id": owner_id,
        })
        if isinstance(result, list):
            result = result[0] if result else None
        if not isinstance(result, dict) or not result.get("id"):
            raise TenantError("Korxona yaratish natijasi tasdiqlanmadi.")
        return result

    def list_companies(self, telegram_user_id: int) -> list[dict]:
        user_id = self._telegram_id(telegram_user_id)
        query = urlencode({
            "telegram_user_id": "eq." + str(user_id),
            "status": "eq.active",
            "select": "company_id,role,status,sc_companies(id,name,slug,status)",
            "order": "joined_at.asc",
        }, safe=",.*()")
        rows = self._db_request("GET", "sc_company_members?" + query)
        return rows if isinstance(rows, list) else []

    def membership(self, company_id: str, telegram_user_id: int) -> dict | None:
        if not isinstance(company_id, str) or not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            company_id,
        ):
            raise ValueError("Korxona identifikatori noto'g'ri.")
        user_id = self._telegram_id(telegram_user_id)
        query = urlencode({
            "company_id": "eq." + company_id,
            "telegram_user_id": "eq." + str(user_id),
            "status": "eq.active",
            "select": "company_id,telegram_user_id,role,status",
            "limit": "1",
        }, safe=",.*")
        rows = self._db_request("GET", "sc_company_members?" + query)
        return rows[0] if isinstance(rows, list) and rows else None

    def require_permission(self, company_id: str, telegram_user_id: int,
                           permission: str) -> dict:
        member = self.membership(company_id, telegram_user_id)
        if not member:
            raise MembershipRequired("Bu korxonaga kirish huquqi yo'q.")
        role = member.get("role")
        allowed = self.WRITE_ROLES.get(role, set())
        if "*" not in allowed and permission not in allowed:
            raise PermissionDenied("Bu amal uchun ruxsat berilmagan.")
        return member

    def create_invite(self, company_id: str, actor_telegram_id: int,
                      role: str, *, expires_in_hours: int = 72,
                      max_uses: int = 1) -> dict:
        if role not in self.ROLES - {"owner"}:
            raise ValueError("Taklif uchun rol noto'g'ri.")
        if isinstance(expires_in_hours, bool) or not 1 <= int(expires_in_hours) <= 720:
            raise ValueError("Taklif muddati 1–720 soat oralig'ida bo'lishi kerak.")
        if isinstance(max_uses, bool) or not 1 <= int(max_uses) <= 100:
            raise ValueError("Taklif soni 1–100 oralig'ida bo'lishi kerak.")
        raw_code = secrets.token_urlsafe(32)
        code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
        expires_at = (datetime.now(timezone.utc) +
                      timedelta(hours=int(expires_in_hours))).isoformat()
        invite_id = self._rpc("sc_create_company_invite", {
            "p_company_id": company_id,
            "p_actor_telegram_id": self._telegram_id(actor_telegram_id),
            "p_code_hash": code_hash,
            "p_role": role,
            "p_expires_at": expires_at,
            "p_max_uses": int(max_uses),
        })
        if isinstance(invite_id, list):
            invite_id = invite_id[0] if invite_id else None
        if isinstance(invite_id, dict):
            invite_id = next(iter(invite_id.values()), None)
        if not invite_id:
            raise TenantError("Taklif kodi yaratilmadi.")
        # The raw code is returned exactly once; only its SHA-256 is persisted.
        return {"invite_id": str(invite_id), "code": raw_code,
                "role": role, "expires_at": expires_at, "max_uses": int(max_uses)}

    def redeem_invite(self, raw_code: str, telegram_user_id: int) -> dict:
        if not isinstance(raw_code, str) or not 20 <= len(raw_code) <= 128:
            raise ValueError("Taklif kodi noto'g'ri.")
        code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
        result = self._rpc("sc_redeem_company_invite", {
            "p_code_hash": code_hash,
            "p_telegram_user_id": self._telegram_id(telegram_user_id),
        })
        if isinstance(result, list):
            result = result[0] if result else None
        if not isinstance(result, dict) or not result.get("company_id"):
            raise TenantError("Taklif kodi yaroqsiz yoki muddati tugagan.")
        return result

    def load_snapshot(self, company_id: str) -> dict:
        if not isinstance(company_id, str) or not company_id:
            raise ValueError("company_id talab qilinadi.")
        query = urlencode({
            "company_id": "eq." + company_id,
            "select": "company_id,data,version,updated_at",
            "limit": "1",
        }, safe=",.*")
        rows = self._db_request("GET", "sc_company_snapshots?" + query)
        if not isinstance(rows, list) or not rows or not isinstance(rows[0].get("data"), dict):
            raise TenantError("Korxona ombor ma'lumotlari topilmadi.")
        return rows[0]["data"]

    def migrate_legacy_snapshot(self, company_id: str, telegram_user_id: int,
                                configured_owner_id: int, legacy_snapshot: dict) -> dict:
        """Copy the legacy owner dataset once into a newly-created empty company.

        The original bot_storage row is never modified. This operation is
        restricted to the configured owner and a company whose snapshot is
        still the pristine version-1 default.
        """
        actor_id = self._telegram_id(telegram_user_id)
        owner_id = self._telegram_id(configured_owner_id)
        if actor_id != owner_id:
            raise PermissionDenied("Eski ombor ma'lumotlarini faqat tizim egasi ko'chira oladi.")
        member = self.membership(company_id, actor_id)
        if not member or member.get("role") != "owner":
            raise PermissionDenied("Ko'chirish uchun korxona egasi bo'lishingiz kerak.")
        if not isinstance(legacy_snapshot, dict):
            raise ValueError("Eski ombor ma'lumotlari noto'g'ri.")

        current = self.load_snapshot(company_id)
        if current.get("version") != 1:
            raise TenantError("Korxona snapshot versiyasi ko'chirish uchun mos emas.")
        for key, value in current.items():
            if key == "version" or value is None or value == "":
                continue
            if isinstance(value, (dict, list)) and not value:
                continue
            raise TenantError("Korxona omborida ma'lumot bor; eski ma'lumot ustidan yozilmadi.")

        migrated = copy.deepcopy(legacy_snapshot)
        migrated["version"] = 2
        self.commit_snapshot(company_id, 1, migrated)
        products = migrated.get("products") if isinstance(migrated.get("products"), dict) else {}
        return {"company_id": company_id, "version": 2, "product_count": len(products),
                "legacy_preserved": True}

    def commit_snapshot(self, company_id: str, expected_version: int,
                        snapshot: dict) -> int:
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot object bo'lishi kerak.")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected_version noto'g'ri.")
        if snapshot.get("version") != expected_version + 1:
            raise ValueError("snapshot version ketma-ketligi noto'g'ri.")
        result = self._rpc("sc_commit_company_snapshot", {
            "p_company_id": company_id,
            "p_expected_version": expected_version,
            "p_data": snapshot,
        })
        if isinstance(result, list):
            result = result[0] if result else None
        if isinstance(result, dict):
            result = next(iter(result.values()), None)
        try:
            version = int(result)
        except (TypeError, ValueError) as exc:
            raise TenantError("Korxona ma'lumotlari saqlangani tasdiqlanmadi.") from exc
        if version != expected_version + 1:
            raise TenantError("Saqlash versiyasi kutilgan natijaga mos emas.")
        return version
