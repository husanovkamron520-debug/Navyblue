"""Curated starter selection for October Creative Builder."""
from __future__ import annotations

TEMPLATES = {
    "cosmos_3d": {"title": "3D kosmos va sayyoralar", "keywords": ("sayyora", "sayyoralar", "planet", "kosmos", "galaktika", "space"), "layout": "immersive full-screen WebGL canvas, restrained HUD labels, orbiting bodies and star field", "must_have": ("multiple distinct sphere meshes", "orbit controls", "lighting", "responsive renderer")},
    "room_3d": {"title": "3D xona/interyer", "keywords": ("xona", "interyer", "mebel", "stol", "divan", "yotoqxona", "room", "interior"), "layout": "architectural room shell, visible floor and walls, furniture grouped by function", "must_have": ("floor and walls as separate meshes", "at least three furniture objects", "orbit and zoom controls", "soft lighting")},
    "warehouse_3d": {"title": "3D ombor va zavod", "keywords": ("ombor", "warehouse", "zavod", "factory", "pallet", "stellaj", "logistika"), "layout": "readable warehouse floor plan in 3D, racks and pallets, clear aisle spacing", "must_have": ("racks and pallets as distinct meshes", "visible aisles", "orbit controls", "responsive renderer")},
    "birthday_gallery": {"title": "Tug‘ilgan kun va foto-galereya", "keywords": ("tug'ilgan", "tugilgan", "birthday", "tabrik", "surat", "rasm", "photo", "gallery"), "layout": "warm celebratory hero, elegant typography, photo-led composition and restrained motion", "must_have": ("uploaded photos displayed directly", "mobile-friendly layout", "working interactions", "reduced-motion support")},
    "portfolio": {"title": "Portfolio va biznes sayti", "keywords": ("portfolio", "biznes", "business", "landing", "sayt", "website", "agency", "company"), "layout": "strong hero, clear navigation, proof/services section and concise CTA", "must_have": ("responsive navigation", "working CTA links", "semantic sections", "accessible contrast")},
    "dashboard": {"title": "Dashboard va interaktiv panel", "keywords": ("dashboard", "panel", "statistika", "grafik", "chart", "monitoring", "analytics", "admin"), "layout": "calm dashboard, KPI cards, chart area, filters and responsive navigation", "must_have": ("meaningful sample data", "working filters", "readable chart labels", "mobile layout")},
    "general": {"title": "Universal responsive HTML", "keywords": (), "layout": "clear hierarchy, balanced whitespace, consistent component styling and mobile-first layout", "must_have": ("semantic HTML", "responsive layout", "working controls", "accessible text contrast")},
}

def select_template(request: str):
    text = (request or "").casefold()
    scored = [(sum(1 for word in item["keywords"] if word.casefold() in text), key) for key, item in TEMPLATES.items()]
    scored = [entry for entry in scored if entry[0]]
    if not scored:
        return "general", TEMPLATES["general"]
    _, key = max(scored, key=lambda pair: (pair[0], pair[1]))
    return key, TEMPLATES[key]

def template_prompt(request: str) -> str:
    key, item = select_template(request)
    return ("TANLANGAN STARTER: " + item["title"] + " (ID: " + key + ").\\n"
            "Vizual tuzilma: " + item["layout"] + ".\\n"
            "Majburiy sifat mezonlari: " + "; ".join(item["must_have"]) + ".\\n"
            "Bu tayyor dizayn yo'nalishi, foydalanuvchi so'rovining o'rnini bosmaydi. "
            "So'rovdagi rang, obyekt, matn, rasm va joylashuv ko'rsatmalarini birinchi o'ringa qo'y. "
            "Shablonni mazmun va kompozitsiya bo'yicha vazifaga moslashtir.")
