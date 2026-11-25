"""Read-only Supply Chain Mini App primitives.

This module deliberately contains no HTTP server wiring and no write operations.
It validates Telegram Web App initData, issues short-lived in-memory sessions,
and builds read-only responses from a caller-provided data snapshot.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl


INIT_DATA_MAX_AGE_SECONDS = 600
INIT_DATA_FUTURE_SKEW_SECONDS = 30
SESSION_TTL_SECONDS = 1800
MAX_INIT_DATA_BYTES = 16_384


class AuthError(ValueError):
    """Invalid or unauthorized Telegram Web App authentication."""


def validate_init_data(init_data: str, bot_token: str, owner_id: int,
                       now: float | None = None) -> dict:
    """Validate Telegram Web App initData and return its authenticated user."""
    if not isinstance(init_data, str) or not init_data or len(init_data.encode("utf-8")) > MAX_INIT_DATA_BYTES:
        raise AuthError("initData missing or too large")
    if not isinstance(bot_token, str) or not bot_token or not owner_id:
        raise AuthError("server authentication is not configured")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        values = {}
        for key, value in pairs:
            if key in values:
                raise AuthError("duplicate initData field")
            values[key] = value
        supplied_hash = values.pop("hash")
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
    except AuthError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthError("malformed initData") from exc
    if len(supplied_hash) != 64:
        raise AuthError("invalid initData signature")
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise AuthError("invalid initData signature")
    current = time.time() if now is None else float(now)
    age = current - auth_date
    if age < -INIT_DATA_FUTURE_SKEW_SECONDS or age > INIT_DATA_MAX_AGE_SECONDS:
        raise AuthError("initData expired")
    if not isinstance(user, dict) or str(user.get("id", "")) != str(owner_id):
        raise AuthError("not authorized")
    return user


class SessionStore:
    """Process-local bearer sessions; tokens are never embedded in URLs."""
    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS):
        self.ttl_seconds = int(ttl_seconds)
        self._sessions: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: int, now: float | None = None) -> tuple[str, int]:
        current = time.time() if now is None else float(now)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge(current)
            self._sessions[token] = (int(user_id), current + self.ttl_seconds)
        return token, self.ttl_seconds

    def authenticate(self, token: str, owner_id: int, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        if not isinstance(token, str) or not token:
            return False
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return False
            user_id, expires_at = session
            if expires_at <= current:
                self._sessions.pop(token, None)
                return False
            return user_id == int(owner_id)

    def revoke_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _purge(self, now: float) -> None:
        for token, (_, expires_at) in list(self._sessions.items()):
            if expires_at <= now:
                self._sessions.pop(token, None)



class RateLimiter:
    """Small process-local sliding-window limiter for sensitive endpoints."""
    def __init__(self, max_requests: int = 8, window_seconds: int = 60):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        bucket_key = str(key or "global")
        cutoff = current - self.window_seconds
        with self._lock:
            events = [stamp for stamp in self._events.get(bucket_key, [])
                      if stamp > cutoff]
            if len(events) >= self.max_requests:
                self._events[bucket_key] = events
                return False
            events.append(current)
            self._events[bucket_key] = events
            return True


def _number(value):
    try:
        result = float(value)
        if result == result and abs(result) != float("inf"):
            return result
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _product_row(sku: str, product: dict) -> dict:
    """Allow-list public Mini App fields; never serialize arbitrary stored JSON."""
    return {
        "sku": str(product.get("sku") or sku),
        "name": str(product.get("name") or sku),
        "quantity": _number(product.get("quantity")),
        "unit": str(product.get("unit") or ""),
        "reorder_point": _number(product.get("reorder_point")),
        "unit_cost": _number(product.get("unit_cost")),
        "annual_demand": _number(product.get("annual_demand")),
        "order_cost": _number(product.get("order_cost")),
        "holding_cost": _number(product.get("holding_cost")),
        "updated_at": product.get("updated_at"),
    }


def _envelope(data: dict, version=1) -> dict:
    return {
        "data": data,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_version": version,
            "source": "supply_chain_data",
        },
        "error": None,
    }


def build_bootstrap(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    return _envelope({
        "company": {"mode": "single_company", "label": "Supply Chain"},
        "sections": ["dashboard", "inventory", "analytics", "procurement", "logistics"],
        "data_version": int(data.get("version") or 1),
        "metric_definitions": {
            "inventory_value": "sum(quantity × unit_cost) for rows with both values",
            "low_stock": "quantity <= reorder_point",
        },
    }, int(data.get("version") or 1))


def build_dashboard(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    total_units, inventory_value, value_rows = 0.0, 0.0, 0
    low_stock, unknown_stock = 0, 0
    for sku, raw in products.items():
        if not isinstance(raw, dict):
            continue
        row = _product_row(str(sku), raw)
        qty, reorder, cost = row["quantity"], row["reorder_point"], row["unit_cost"]
        if qty is None:
            unknown_stock += 1
        else:
            total_units += qty
        if qty is not None and reorder is not None and qty <= reorder:
            low_stock += 1
        if qty is not None and cost is not None and qty >= 0 and cost >= 0:
            inventory_value += qty * cost
            value_rows += 1
    orders = data.get("orders") if isinstance(data.get("orders"), list) else []
    shipments = data.get("shipments") if isinstance(data.get("shipments"), list) else []
    return _envelope({
        "kpis": {
            "product_count": len(products),
            "total_units": total_units,
            "inventory_value": inventory_value,
            "inventory_value_rows": value_rows,
            "low_stock_count": low_stock,
            "unknown_stock_count": unknown_stock,
            "open_order_count": sum(1 for x in orders if isinstance(x, dict) and x.get("status") in {"draft", "ordered"}),
            "active_shipment_count": sum(1 for x in shipments if isinstance(x, dict) and x.get("status") in {"planned", "dispatched"}),
        },
        "alerts": {"low_stock": low_stock},
    }, int(data.get("version") or 1))


def list_inventory(snapshot: dict, search: str = "", status: str = "all",
                   sort: str = "name", page: int = 1, page_size: int = 10) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    rows = [_product_row(str(sku), p) for sku, p in products.items() if isinstance(p, dict)]
    query = str(search or "").strip().casefold()
    if query:
        rows = [r for r in rows if query in r["sku"].casefold() or query in r["name"].casefold()]
    if status == "low":
        rows = [r for r in rows if r["quantity"] is not None and r["reorder_point"] is not None and r["quantity"] <= r["reorder_point"]]
    elif status == "healthy":
        rows = [r for r in rows if r["quantity"] is not None and r["reorder_point"] is not None and r["quantity"] > r["reorder_point"]]
    sort_keys = {
        "name": lambda r: r["name"].casefold(),
        "quantity": lambda r: (r["quantity"] is None, r["quantity"] or 0),
        "value": lambda r: (r["quantity"] is None or r["unit_cost"] is None,
                            (r["quantity"] or 0) * (r["unit_cost"] or 0)),
    }
    rows.sort(key=sort_keys.get(sort, sort_keys["name"]))
    total = len(rows)
    page = max(1, min(int(page), 1_000_000))
    page_size = max(1, min(int(page_size), 100))
    start = (page - 1) * page_size
    return _envelope({
        "items": rows[start:start + page_size],
        "pagination": {"page": page, "page_size": page_size, "total": total,
                       "pages": (total + page_size - 1) // page_size},
    }, int(data.get("version") or 1))
