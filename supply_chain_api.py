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



def _sku_matches(raw: str, sku: str) -> bool:
    return not raw or str(raw).casefold() == str(sku).casefold()


def _weighted_demand(records: list[dict]) -> float | None:
    ordered = sorted(
        (r for r in records if isinstance(r, dict)),
        key=lambda r: str(r.get("month", "")),
    )[-6:]
    if len(ordered) < 3:
        return None
    values = [_number(r.get("quantity")) for r in ordered]
    if any(v is None or v < 0 for v in values):
        return None
    weights = list(range(1, len(values) + 1))
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def build_demand_analytics(snapshot: dict, sku: str = "") -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    history = data.get("demand_history") if isinstance(data.get("demand_history"), list) else []
    items = []
    for key, product in sorted(products.items(), key=lambda pair: str(pair[0])):
        if not isinstance(product, dict) or not _sku_matches(sku, key):
            continue
        records = sorted(
            [r for r in history if isinstance(r, dict) and str(r.get("sku")) == str(key)],
            key=lambda r: str(r.get("month", "")),
        )[-6:]
        forecast = _weighted_demand(records)
        qty = _number(product.get("quantity"))
        reorder = _number(product.get("reorder_point"))
        monthly = round(forecast, 4) if forecast is not None else None
        daily = forecast / 30 if forecast is not None else None
        cover = qty / daily if qty is not None and daily and daily > 0 else None
        items.append({
            "sku": str(key),
            "name": str(product.get("name") or key),
            "unit": str(product.get("unit") or ""),
            "history_months": len(records),
            "months_used": [str(r.get("month") or "") for r in records],
            "forecast_status": "available" if forecast is not None else "insufficient_history",
            "forecast_next_month": monthly,
            "average_daily_demand": round(daily, 4) if daily is not None else None,
            "days_of_stock_cover": round(cover, 2) if cover is not None else None,
            "reorder_point": reorder,
            "stock_quantity": qty,
            "recommended_purchase_quantity": round(max(0.0, forecast + (reorder or 0) - (qty or 0)), 4) if forecast is not None else None,
        })
    return _envelope({"items": items, "method": "weighted_moving_average_last_6_months",
                      "minimum_history_months": 3}, int(data.get("version") or 1))


def build_abc_analysis(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    rows = []
    for sku, product in products.items():
        if not isinstance(product, dict):
            continue
        demand, cost = _number(product.get("annual_demand")), _number(product.get("unit_cost"))
        if demand is None or cost is None or demand <= 0 or cost <= 0:
            continue
        rows.append({"sku": str(sku), "name": str(product.get("name") or sku),
                     "annual_consumption_value": demand * cost})
    rows.sort(key=lambda r: (-r["annual_consumption_value"], r["sku"]))
    total = sum(r["annual_consumption_value"] for r in rows)
    cumulative = 0.0
    groups = {"A": [], "B": [], "C": []}
    for row in rows:
        share = row["annual_consumption_value"] / total if total else 0.0
        midpoint = (cumulative + share / 2) * 100
        category = "A" if midpoint <= 80 else ("B" if midpoint <= 95 else "C")
        row.update(share_percent=round(share * 100, 2), cumulative_percent=round((cumulative + share) * 100, 2), category=category)
        groups[category].append(row)
        cumulative += share
    summary = {
        key: {"product_count": len(values),
              "value": round(sum(x["annual_consumption_value"] for x in values), 2),
              "share_percent": round(sum(x["annual_consumption_value"] for x in values) / total * 100, 2) if total else 0.0}
        for key, values in groups.items()
    }
    return _envelope({"total_annual_consumption_value": round(total, 2),
                      "classified_product_count": len(rows), "groups": summary, "items": rows,
                      "method": "annual_demand_times_unit_cost_midpoint_80_15_5"},
                     int(data.get("version") or 1))


def build_eoq_analysis(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    items = []
    for sku, product in sorted(products.items(), key=lambda pair: str(pair[0])):
        if not isinstance(product, dict):
            continue
        demand = _number(product.get("annual_demand"))
        order_cost = _number(product.get("order_cost"))
        holding = _number(product.get("holding_cost"))
        unit_cost = _number(product.get("unit_cost"))
        assumed = holding is None or holding <= 0
        if assumed and unit_cost is not None:
            holding = unit_cost * 0.2
        valid = demand is not None and order_cost is not None and holding is not None and demand > 0 and order_cost > 0 and holding > 0
        eoq = (2 * demand * order_cost / holding) ** 0.5 if valid else None
        items.append({"sku": str(sku), "name": str(product.get("name") or sku),
                      "annual_demand": demand, "order_cost": order_cost,
                      "holding_cost_used": holding, "holding_cost_assumed": assumed if valid else False,
                      "eoq": round(eoq, 4) if eoq is not None else None,
                      "orders_per_year": round(demand / eoq, 4) if eoq else None,
                      "status": "available" if eoq is not None else "missing_inputs"})
    return _envelope({"items": items, "formula": "sqrt(2*D*S/H)",
                      "assumed_holding_cost": "20% of unit_cost when holding_cost is missing or non-positive"},
                     int(data.get("version") or 1))


def build_replenishment(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    history = data.get("demand_history") if isinstance(data.get("demand_history"), list) else []
    suppliers = data.get("suppliers") if isinstance(data.get("suppliers"), dict) else {}
    orders = data.get("orders") if isinstance(data.get("orders"), list) else []
    items = []
    for sku, product in products.items():
        if not isinstance(product, dict):
            continue
        qty, reorder = _number(product.get("quantity")), _number(product.get("reorder_point"))
        records = [r for r in history if isinstance(r, dict) and str(r.get("sku")) == str(sku)]
        forecast = _weighted_demand(records)
        linked_ids = {str(o.get("supplier_id")) for o in orders
                      if isinstance(o, dict) and str(o.get("sku")) == str(sku) and o.get("supplier_id")
                      and o.get("status") in {"draft", "ordered"}}
        if product.get("supplier_id"):
            linked_ids.add(str(product["supplier_id"]))
        lead_times = [_number(suppliers.get(sid, {}).get("lead_time_days"))
                      for sid in linked_ids if isinstance(suppliers.get(sid), dict)]
        lead_times = [v for v in lead_times if v is not None and v >= 0]
        inbound = sum((_number(o.get("quantity")) or 0) for o in orders
                      if isinstance(o, dict) and str(o.get("sku")) == str(sku) and o.get("status") == "ordered")
        status = "unknown"
        if qty is not None and reorder is not None:
            status = "low" if qty <= reorder else "healthy"
        items.append({"sku": str(sku), "name": str(product.get("name") or sku),
                      "quantity": qty, "reorder_point": reorder, "forecast_monthly": round(forecast, 2) if forecast is not None else None,
                      "open_order_quantity": round(inbound, 2), "lead_time_days": max(lead_times) if lead_times else None,
                      "suggested_order_quantity": round(max(0, (forecast or 0) + (reorder or 0) - (qty or 0) - inbound), 2) if forecast is not None else None,
                      "status": status})
    items.sort(key=lambda x: ({"low": 0, "unknown": 1, "healthy": 2}[x["status"]], x["name"].casefold()))
    return _envelope({"items": items, "note": "Recommendations are read-only and require review before ordering."},
                     int(data.get("version") or 1))


def get_inventory_detail(snapshot: dict, sku: str) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    product = products.get(sku)
    if not isinstance(product, dict):
        return _envelope({"item": None}, int(data.get("version") or 1))
    movements = [m for m in data.get("movements", []) if isinstance(m, dict) and str(m.get("sku")) == str(sku)]
    movements.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
    demand = [r for r in data.get("demand_history", []) if isinstance(r, dict) and str(r.get("sku")) == str(sku)]
    demand.sort(key=lambda r: str(r.get("month") or ""), reverse=True)
    return _envelope({"item": _product_row(str(sku), product),
                      "recent_movements": movements[:20],
                      "demand_history": demand[:12]}, int(data.get("version") or 1))

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
