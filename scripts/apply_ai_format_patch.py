"""One-time patch: readable AI answers + deterministic overstock estimate.

Usage: python scripts/apply_ai_format_patch.py [path/to/supply_chain.py]

All replacements must match exactly once, otherwise nothing is written.
"""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "supply_chain.py"
updated = open(path, encoding="utf-8").read()

if "_overstock_estimate" in updated:
    print("Format patch already applied; nothing to do.")
    sys.exit(0)


def rep(old, new):
    global updated
    found = updated.count(old)
    if found != 1:
        raise SystemExit(f"Patch anchor matched {found} times (expected 1): {old[:70]!r}")
    updated = updated.replace(old, new)


helpers = '''_OVERSTOCK_TARGET_DAYS = 60
_OVERSTOCK_HOLDING_RATE = 0.20


def _overstock_estimate(data: dict[str, Any]) -> dict[str, Any]:
    """Deterministic overstock estimate: stock above N days of demand, with stated assumptions."""
    history = data.get("demand_history", [])
    rows: list[dict[str, Any]] = []
    skipped = 0
    for sku, product in data.get("products", {}).items():
        if not isinstance(product, dict) or product.get("quantity") is None:
            continue
        stock = _safe_num(product.get("quantity"))
        if stock <= 0:
            continue
        annual = _safe_num(product.get("annual_demand"))
        source = "yillik talab"
        if annual > 0:
            daily = annual / 365.0
        else:
            records = sorted((r for r in history if r.get("sku") == sku), key=lambda r: str(r.get("month", "")))[-6:]
            if len(records) < 3:
                skipped += 1
                continue
            values = [_safe_num(r.get("quantity")) for r in records]
            weights = list(range(1, len(values) + 1))
            daily = (sum(v * w for v, w in zip(values, weights)) / sum(weights)) / 30.0
            source = "oylik talab tarixi"
        if daily <= 0:
            skipped += 1
            continue
        target = daily * _OVERSTOCK_TARGET_DAYS
        excess = stock - target
        if excess <= 0:
            continue
        row: dict[str, Any] = {
            "product": str(product.get("name", sku)), "unit": str(product.get("unit", "dona")),
            "stock": round(stock, 2), "days_of_cover": round(stock / daily),
            "normal_stock": round(target, 1), "excess_quantity": round(excess, 1), "demand_source": source,
        }
        cost = product.get("unit_cost")
        if cost is not None and _safe_num(cost) >= 0:
            unit_cost = _safe_num(cost)
            holding = product.get("holding_cost")
            per_unit_year = _safe_num(holding) if holding is not None else unit_cost * _OVERSTOCK_HOLDING_RATE
            row["excess_value_uzs"] = round(excess * unit_cost)
            row["yearly_holding_cost_uzs"] = round(excess * per_unit_year)
        rows.append(row)
    rows.sort(key=lambda r: r.get("excess_value_uzs", 0), reverse=True)
    priced = [r for r in rows if "excess_value_uzs" in r]
    return {
        "assumptions": {
            "normal_stock_rule": f"normal zaxira = {_OVERSTOCK_TARGET_DAYS} kunlik talab",
            "holding_cost_rule": "saqlash xarajati: mahsulotda kiritilgan bo‘lsa shu, aks holda narxning 20% / yil",
        },
        "overstock_products": len(rows),
        "products_skipped_no_demand": skipped,
        "total_excess_value_uzs": sum(r["excess_value_uzs"] for r in priced),
        "total_yearly_holding_cost_uzs": sum(r["yearly_holding_cost_uzs"] for r in priced),
        "top_items": rows[:8],
    }


_AI_FORMAT_RULES = (
    "JAVOB SHAKLI (majburiy; oldingi shakl ko‘rsatmalaridan ustun):\\n"
    "1) Birinchi qator: 💡 va savolga to‘g‘ridan-to‘g‘ri javob, bitta qisqa gap, raqam bilan.\\n"
    "2) Bo‘sh qator, keyin ko‘pi bilan 4 ta band; har biri bitta qatorda: • Nomi — raqam — nima qilish kerak.\\n"
    "3) Bo‘sh qator, oxirida bitta qator: ➡️ Keyingi qadam: ... (bitta amaliy tavsiya).\\n"
    "4) Jami 700 belgidan oshmasin. Uzun paragraf, takror, umumiy ogohlantirish va dars berish yo‘q.\\n"
    "5) Pulni million so‘mda yoz (masalan 831 mln so‘m), miqdorni 100 701 kg ko‘rinishida yoz; uzun sonlarni to‘liq yozma.\\n"
    "6) Aniq qiymat uchun ma’lumot yetmasa, «hisoblab bo‘lmaydi» deb to‘xtama: berilgan tayyor taxminiy hisobdan foydalan, "
    "bitta qisqa gapda qaysi faraz ishlatilganini ayt (masalan, normal zaxira = 60 kunlik talab) va qaysi ma’lumot kiritilsa aniqroq bo‘lishini yoz. "
    "Berilgan hisobda bo‘lmagan raqamni to‘qima.\\n"
    "7) Mahsulotlarni qiymati yoki muhimligi bo‘yicha tartiblab, eng muhim 3–4 tasini ko‘rsat; qolganini «yana N ta» deb yoz.\\n\\n"
)


'''
rep('def _format_ai_customer_answer(answer: str) -> str:', helpers + 'def _format_ai_customer_answer(answer: str) -> str:')

# snapshot: provide the estimate instead of "not calculable"
rep('''            "overstock_value": {"status": "not_calculable", "missing": ["har bir SKU uchun maqsad yoki maksimal zaxira darajasi"]},''',
    '''            "overstock_value": {"status": "estimated_with_assumptions", "see": "overstock_estimate"},''')
rep('''        "computed_metrics": _computed_metrics(data),''',
    '''        "computed_metrics": _computed_metrics(data),
        "overstock_estimate": _overstock_estimate(data),''')

# prompts: strict short format (appended last so it wins)
rep('''        "Javobni keraksiz sarlavha va uzun kirish bilan cho‘zma.\\n\\n"
        + _ai_history_prompt_part(history_text)''',
    '''        "Javobni keraksiz sarlavha va uzun kirish bilan cho‘zma.\\n\\n"
        + _AI_FORMAT_RULES
        + _ai_history_prompt_part(history_text)''')
rep('''        "foydalanuvchi tasdiqlamaguncha hech narsa yuborilmaydi.\\n\\n"
        + _ai_history_prompt_part(history_text)''',
    '''        "foydalanuvchi tasdiqlamaguncha hech narsa yuborilmaydi.\\n\\n"
        + _AI_FORMAT_RULES
        + _ai_history_prompt_part(history_text)''')

# custom answers go through the same cleaner as quick answers
rep('''        raise RuntimeError("Gemini bo‘sh javob qaytardi. Birozdan keyin qayta urinib ko‘ring.")
    return str(answer).strip()''',
    '''        raise RuntimeError("Gemini bo‘sh javob qaytardi. Birozdan keyin qayta urinib ko‘ring.")
    return _format_ai_customer_answer(str(answer))''')

# cleaner: whole-word match so words like "kapital" are not wiped; keep the new ➡️ line spacing
rep('''        r"(?i)(json|computed_reports|computed_metrics|inventory_summary|kpi_availability|"
        r"risk_assessment|callback|api|database|deploy|backend|field|schema|sku\\s*[:=])"''',
    '''        r"(?i)(\\b(?:json|computed_reports|computed_metrics|overstock_estimate|inventory_summary|kpi_availability|"
        r"risk_assessment|callback|api|database|deploy|backend|field|schema)\\b|sku\\s*[:=])"''')
rep('''re.match(r"^(💡|Dalillar:|Keyingi qadam:|Xulosa:)", line, re.I)''',
    '''re.match(r"^(💡|➡️|Dalillar:|Keyingi qadam:|Xulosa:)", line, re.I)''')

# shorter footer
rep('''                           "\\n\\nEslatma: tavsiyalar avtomatik bajarilmaydi.\\nSavolni davom ettirishingiz mumkin: shunchaki yozing.")''',
    '''                           "\\n\\nℹ️ Tavsiya, avtomatik bajarilmaydi. Davom ettirish uchun yozing.")''')

open(path, "w", encoding="utf-8").write(updated)
print("Format patch applied.")
