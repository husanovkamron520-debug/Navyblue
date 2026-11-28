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


INIT_DATA_MAX_AGE_SECONDS = 3600
INIT_DATA_FUTURE_SKEW_SECONDS = 30
SESSION_TTL_SECONDS = 1800
MAX_INIT_DATA_BYTES = 16_384


class AuthError(ValueError):
    """Invalid or unauthorized Telegram Web App authentication."""


def validate_init_data(init_data: str, bot_token: str, owner_id: int | None = None,
                       now: float | None = None) -> dict:
    """Validate Telegram Web App initData and return its authenticated user."""
    if not isinstance(init_data, str) or not init_data or len(init_data.encode("utf-8")) > MAX_INIT_DATA_BYTES:
        raise AuthError("initData missing or too large")
    if not isinstance(bot_token, str) or not bot_token:
        raise AuthError("server authentication is not configured")
    if owner_id is not None and (isinstance(owner_id, bool) or int(owner_id) <= 0):
        raise AuthError("server owner authentication is not configured")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=32)
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
    if not isinstance(user, dict) or isinstance(user.get("id"), bool):
        raise AuthError("invalid Telegram user")
    try:
        telegram_user_id = int(user.get("id"))
    except (TypeError, ValueError) as exc:
        raise AuthError("invalid Telegram user") from exc
    if telegram_user_id <= 0 or (owner_id is not None and telegram_user_id != int(owner_id)):
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
    """Bounded process-local sliding-window limiter for sensitive endpoints."""
    def __init__(self, max_requests: int = 8, window_seconds: int = 60,
                 max_buckets: int = 2048):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self.max_buckets = max(1, int(max_buckets))
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        bucket_key = str(key or "global")
        cutoff = current - self.window_seconds
        with self._lock:
            # Prune every bucket, not only the current caller's bucket. Otherwise
            # one-off client keys accumulate indefinitely on a public endpoint.
            for existing_key, stamps in list(self._events.items()):
                live = [stamp for stamp in stamps if stamp > cutoff]
                if live:
                    self._events[existing_key] = live
                else:
                    self._events.pop(existing_key, None)

            events = self._events.get(bucket_key)
            if events is None:
                # Fail closed instead of growing memory without a hard bound.
                if len(self._events) >= self.max_buckets:
                    return False
                events = []
                self._events[bucket_key] = events
            if len(events) >= self.max_requests:
                return False
            events.append(current)
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
            "history": [{"month": str(r.get("month") or ""), "quantity": _number(r.get("quantity"))} for r in records if _number(r.get("quantity")) is not None and _number(r.get("quantity")) >= 0],
            "forecast_status": "available" if forecast is not None else "insufficient_history",
            "forecast_next_month": monthly,
            "average_daily_demand": round(daily, 4) if daily is not None else None,
            "days_of_stock_cover": round(cover, 2) if cover is not None else None,
            "reorder_point": reorder,
            "stock_quantity": qty,
            "recommended_purchase_quantity": round(max(0.0, forecast + (reorder or 0) - (qty or 0)), 4) if forecast is not None else None,
        })
    return _envelope({"items": items, "method": "weighted_moving_average_last_6_months",
                      "minimum_history_months": 3}, _safe_version(data))


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
                     _safe_version(data))


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
                     _safe_version(data))


def build_replenishment(snapshot: dict) -> dict:
    """Read-only replenishment and indicative 90-day surplus analysis."""
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    history = data.get("demand_history") if isinstance(data.get("demand_history"), list) else []
    suppliers = data.get("suppliers") if isinstance(data.get("suppliers"), dict) else {}
    orders = data.get("orders") if isinstance(data.get("orders"), list) else []
    review_horizon_days = 90
    items = []
    for sku, product in products.items():
        if not isinstance(product, dict):
            continue
        qty, reorder = _number(product.get("quantity")), _number(product.get("reorder_point"))
        unit_cost = _number(product.get("unit_cost"))
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
        matching_orders = [o for o in orders if isinstance(o, dict)
                           and str(o.get("sku")) == str(sku)
                           and str(o.get("status") or "").lower() in {"draft", "ordered"}]
        draft_qty = sum((_number(o.get("quantity")) or 0) for o in matching_orders
                        if str(o.get("status") or "").lower() == "draft")
        inbound = sum((_number(o.get("quantity")) or 0) for o in matching_orders
                      if str(o.get("status") or "").lower() == "ordered")
        open_qty = draft_qty + inbound
        daily = forecast / 30 if forecast is not None else None
        cover_days = qty / daily if qty is not None and daily is not None and daily > 0 else None
        inventory_value = qty * unit_cost if qty is not None and unit_cost is not None else None
        # Confirmed inbound is included; draft orders remain a separate proposal.
        committed_supply = qty + inbound if qty is not None else None
        horizon_demand = forecast * (review_horizon_days / 30) if forecast is not None else None
        surplus_qty = (max(0.0, committed_supply - horizon_demand)
                       if committed_supply is not None and horizon_demand is not None else None)
        surplus_value = surplus_qty * unit_cost if surplus_qty is not None and unit_cost is not None else None
        status = "unknown"
        if qty is not None and reorder is not None:
            status = "low" if qty <= reorder else "healthy"
        items.append({
            "sku": str(sku), "name": str(product.get("name") or sku),
            "quantity": qty, "reorder_point": reorder, "unit_cost": unit_cost,
            "inventory_value": round(inventory_value, 2) if inventory_value is not None else None,
            "forecast_monthly": round(forecast, 2) if forecast is not None else None,
            "average_daily_demand": round(daily, 4) if daily is not None else None,
            "days_of_stock_cover": round(cover_days, 2) if cover_days is not None else None,
            "draft_order_quantity": round(draft_qty, 2), "ordered_quantity": round(inbound, 2),
            "inbound_quantity": round(inbound, 2), "open_order_quantity": round(open_qty, 2),
            "lead_time_days": max(lead_times) if lead_times else None,
            "review_horizon_days": review_horizon_days,
            "supply_including_confirmed_inbound": round(committed_supply, 2) if committed_supply is not None else None,
            "demand_over_review_horizon": round(horizon_demand, 2) if horizon_demand is not None else None,
            "indicative_surplus_quantity": round(surplus_qty, 2) if surplus_qty is not None else None,
            "indicative_surplus_value": round(surplus_value, 2) if surplus_value is not None else None,
            "surplus_review_status": ("review" if surplus_qty is not None and surplus_qty > 0
                                      else "no_signal" if surplus_qty is not None else "insufficient_data"),
            "suggested_order_quantity": round(max(0, (forecast or 0) + (reorder or 0) - (qty or 0) - open_qty), 2) if forecast is not None else None,
            "status": status
        })
    items.sort(key=lambda x: (
        0 if x["surplus_review_status"] == "review" else 1,
        {"low": 0, "unknown": 1, "healthy": 2}[x["status"]],
        x["name"].casefold()
    ))
    return _envelope({
        "items": items,
        "surplus_review_horizon_days": review_horizon_days,
        "surplus_method": "on_hand_plus_confirmed_inbound_minus_weighted_forecast_over_90_days",
        "note": "90-day surplus is an indicative review signal, not an optimal-stock decision. It requires at least 3 months of demand history; values require unit_cost. Draft orders are shown separately and excluded from committed supply."
    }, _safe_version(data))



def _page_items(items: list[dict], page: int = 1, page_size: int = 10) -> dict:
    page = max(1, min(int(page), 1_000_000))
    page_size = max(1, min(int(page_size), 100))
    total = len(items)
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size],
            "pagination": {"page": page, "page_size": page_size, "total": total,
                           "pages": (total + page_size - 1) // page_size}}


def list_purchase_orders(snapshot: dict, status: str = "all", page: int = 1, page_size: int = 10) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    suppliers = data.get("suppliers") if isinstance(data.get("suppliers"), dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    orders = data.get("orders") if isinstance(data.get("orders"), list) else []
    rows = []
    for order in orders:
        if not isinstance(order, dict) or (status != "all" and order.get("status") != status):
            continue
        supplier = suppliers.get(str(order.get("supplier_id")), {})
        product = products.get(str(order.get("sku")), {})
        if not isinstance(supplier, dict):
            supplier = {}
        if not isinstance(product, dict):
            product = {}
        rows.append({"id": str(order.get("id") or ""), "sku": str(order.get("sku") or ""),
                     "product_name": str(product.get("name") or order.get("sku") or ""),
                     "supplier_name": str(supplier.get("name") or ""),
                     "quantity": _number(order.get("quantity")), "unit_price": _number(order.get("unit_price")),
                     "expected_date": order.get("expected_date"), "status": str(order.get("status") or ""),
                     "created_at": order.get("created_at")})
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return _envelope(_page_items(rows, page, page_size), _safe_version(data))


def list_suppliers(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    suppliers = data.get("suppliers") if isinstance(data.get("suppliers"), dict) else {}
    rows = []
    for sid, supplier in suppliers.items():
        if not isinstance(supplier, dict):
            continue
        rows.append({"id": str(sid), "name": str(supplier.get("name") or sid),
                     "lead_time_days": _number(supplier.get("lead_time_days")),
                     "rating": _number(supplier.get("rating"))})
    rows.sort(key=lambda r: r["name"].casefold())
    return _envelope({"items": rows}, _safe_version(data))


def list_shipments(snapshot: dict, status: str = "all", page: int = 1, page_size: int = 10) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    vehicles = data.get("vehicles") if isinstance(data.get("vehicles"), list) else []
    vehicle_map = {str(v.get("id")): v for v in vehicles if isinstance(v, dict)}
    shipments = data.get("shipments") if isinstance(data.get("shipments"), list) else []
    rows = []
    for shipment in shipments:
        if not isinstance(shipment, dict) or (status != "all" and shipment.get("status") != status):
            continue
        product = products.get(str(shipment.get("sku")), {})
        vehicle = vehicle_map.get(str(shipment.get("vehicle_id")), {})
        if not isinstance(product, dict):
            product = {}
        if not isinstance(vehicle, dict):
            vehicle = {}
        rows.append({"id": str(shipment.get("id") or ""), "sku": str(shipment.get("sku") or ""),
                     "product_name": str(product.get("name") or shipment.get("sku") or ""),
                     "quantity": _number(shipment.get("quantity")), "destination": str(shipment.get("destination") or ""),
                     "distance_km": _number(shipment.get("distance_km")),
                     "vehicle_name": str(vehicle.get("name") or ""),
                     "estimated_hours": _number(shipment.get("estimated_hours")),
                     "estimated_cost": _number(shipment.get("estimated_cost")),
                     "status": str(shipment.get("status") or ""),
                     "created_at": shipment.get("created_at")})
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return _envelope(_page_items(rows, page, page_size), _safe_version(data))


def list_vehicles(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    vehicles = data.get("vehicles") if isinstance(data.get("vehicles"), list) else []
    rows = []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        rows.append({"id": str(vehicle.get("id") or ""), "name": str(vehicle.get("name") or ""),
                     "capacity": _number(vehicle.get("capacity")),
                     "cost_per_km": _number(vehicle.get("cost_per_km")),
                     "speed_kmh": _number(vehicle.get("speed_kmh"))})
    rows.sort(key=lambda r: r["name"].casefold())
    return _envelope({"items": rows}, _safe_version(data))

def get_inventory_detail(snapshot: dict, sku: str) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    product = products.get(sku)
    if not isinstance(product, dict):
        return _envelope({"item": None}, _safe_version(data))
    movement_source = data.get("movements")
    if not isinstance(movement_source, list):
        movement_source = []
    raw_movements = [m for m in movement_source if isinstance(m, dict) and str(m.get("sku")) == str(sku)]
    raw_movements.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
    movements = [{"type": str(m.get("type") or ""), "quantity": _number(m.get("quantity")),
                  "note": str(m.get("note") or "")[:240], "created_at": m.get("created_at"),
                  "shipment_id": m.get("shipment_id"), "order_id": m.get("order_id")}
                 for m in raw_movements[:20]]
    demand_source = data.get("demand_history")
    if not isinstance(demand_source, list):
        demand_source = []
    raw_demand = [r for r in demand_source if isinstance(r, dict) and str(r.get("sku")) == str(sku)]
    raw_demand.sort(key=lambda r: str(r.get("month") or ""), reverse=True)
    demand = [{"month": str(r.get("month") or ""), "quantity": _number(r.get("quantity")),
               "created_at": r.get("created_at")} for r in raw_demand[:12]]
    return _envelope({"item": _product_row(str(sku), product),
                      "recent_movements": movements,
                      "demand_history": demand}, _safe_version(data))

def _safe_version(data: dict) -> int:
    """Keep malformed persisted metadata from turning otherwise readable views into 500s."""
    try:
        version = int(data.get("version") or 1)
        return version if version > 0 else 1
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 1


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
    history = data.get("import_history") if isinstance(data.get("import_history"), list) else []
    recent_imports = []
    for item in history[-10:]:
        if not isinstance(item, dict):
            continue
        recent_imports.append({
            "file_name": str(item.get("file_name", ""))[:180],
            "sheet": str(item.get("sheet", ""))[:120],
            "created_at": str(item.get("created_at", ""))[:40],
            "processed": _number(item.get("processed")),
            "created": _number(item.get("created")),
            "updated": _number(item.get("updated")),
            "unchanged": _number(item.get("unchanged")),
            "unchanged_quantity": _number(item.get("unchanged_quantity")),
        })
    return _envelope({
        "company": {"mode": "single_company", "label": "Supply Chain"},
        "sections": ["dashboard", "inventory", "analytics", "procurement", "logistics"],
        "data_version": _safe_version(data),
        "recent_imports": recent_imports,
        "metric_definitions": {
            "inventory_value": "sum(quantity × unit_cost) for rows with both values",
            "low_stock": "quantity <= reorder_point",
        },
    }, _safe_version(data))


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
            "product_count": sum(1 for product in products.values() if isinstance(product, dict)),
            "total_units": total_units,
            "inventory_value": inventory_value,
            "inventory_value_rows": value_rows,
            "low_stock_count": low_stock,
            "unknown_stock_count": unknown_stock,
            "open_order_count": sum(1 for x in orders if isinstance(x, dict) and x.get("status") in {"draft", "ordered"}),
            "active_shipment_count": sum(1 for x in shipments if isinstance(x, dict) and x.get("status") in {"planned", "dispatched"}),
        },
        "alerts": {"low_stock": low_stock},
    }, _safe_version(data))


def list_inventory(snapshot: dict, search: str = "", status: str = "all",
                   sort: str = "name", page: int = 1, page_size: int = 10) -> dict:
    data = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    products = data.get("products") if isinstance(data.get("products"), dict) else {}
    rows = [_product_row(str(sku), p) for sku, p in products.items() if isinstance(p, dict)]
    # A high-stock signal is a review flag, not proof of overstock: reorder point is a minimum, not a maximum.
    for row in rows:
        qty, reorder = row["quantity"], row["reorder_point"]
        row["stock_level"] = ("unknown" if qty is None or reorder is None or reorder <= 0
                              else "low" if qty <= reorder
                              else "high" if qty >= reorder * 5
                              else "healthy")
        row["reorder_multiple"] = round(qty / reorder, 2) if qty is not None and reorder is not None and reorder > 0 else None
    query = str(search or "").strip().casefold()
    if query:
        rows = [r for r in rows if query in r["sku"].casefold() or query in r["name"].casefold()]
    if status == "low":
        rows = [r for r in rows if r["quantity"] is not None and r["reorder_point"] is not None and r["quantity"] <= r["reorder_point"]]
    elif status == "healthy":
        rows = [r for r in rows if r["stock_level"] == "healthy"]
    elif status == "high":
        rows = [r for r in rows if r["stock_level"] == "high"]
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
    }, _safe_version(data))

class TenantSessionStore:
    """Short-lived bearer sessions bound to one verified company membership.

    The caller must verify membership against Supabase before issue(). A session
    never accepts a company or role supplied by a later API request.
    """
    TTL_SECONDS = 1800
    ROLE_PERMISSIONS = {
        "owner": {"*"},
        "admin": {"*"},
        "warehouse": {"inventory.read", "inventory.write", "movement.write", "reports.read"},
        "purchasing": {"inventory.read", "procurement.read", "procurement.write", "reports.read"},
        "transport": {"inventory.read", "logistics.read", "logistics.write", "reports.read"},
        "viewer": {"inventory.read", "procurement.read", "logistics.read", "reports.read"},
    }

    def __init__(self, ttl_seconds: int = TTL_SECONDS, max_sessions: int = 10000):
        self.ttl_seconds = max(60, min(int(ttl_seconds), 3600))
        self.max_sessions = max(100, int(max_sessions))
        self._sessions: dict[str, tuple[dict, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _valid_company_id(company_id: str) -> bool:
        import re
        return isinstance(company_id, str) and bool(re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            company_id,
        ))

    def issue(self, user_id: int, company_id: str, role: str,
              now: float | None = None) -> tuple[str, int]:
        if isinstance(user_id, bool) or int(user_id) <= 0:
            raise AuthError("invalid user")
        if not self._valid_company_id(company_id):
            raise AuthError("invalid company")
        if role not in self.ROLE_PERMISSIONS:
            raise AuthError("invalid membership role")
        current = time.time() if now is None else float(now)
        token = secrets.token_urlsafe(32)
        context = {"user_id": int(user_id), "company_id": company_id, "role": role}
        with self._lock:
            self._purge(current)
            if len(self._sessions) >= self.max_sessions:
                raise AuthError("session capacity reached")
            self._sessions[token] = (context, current + self.ttl_seconds)
        return token, self.ttl_seconds

    def authenticate(self, token: str, now: float | None = None) -> dict | None:
        current = time.time() if now is None else float(now)
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None
            context, expires_at = session
            if expires_at <= current:
                self._sessions.pop(token, None)
                return None
            return dict(context)

    def allows(self, context: dict | None, permission: str) -> bool:
        if not isinstance(context, dict) or not isinstance(permission, str):
            return False
        allowed = self.ROLE_PERMISSIONS.get(context.get("role"), set())
        return "*" in allowed or permission in allowed

    def revoke_user(self, user_id: int, company_id: str | None = None) -> int:
        removed = 0
        with self._lock:
            for token, (context, _) in list(self._sessions.items()):
                if context.get("user_id") == int(user_id) and (
                    company_id is None or context.get("company_id") == company_id
                ):
                    self._sessions.pop(token, None)
                    removed += 1
        return removed

    def _purge(self, now: float) -> None:
        for token, (_, expires_at) in list(self._sessions.items()):
            if expires_at <= now:
                self._sessions.pop(token, None)

