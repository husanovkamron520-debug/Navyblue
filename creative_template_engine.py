"""Curated starter selection and optional Vite project packaging for Creative Builder."""
from __future__ import annotations
import io, json, re, zipfile

TEMPLATES = {
    "cosmos_3d": {"title": "3D kosmos va sayyoralar", "keywords": ("sayyora", "sayyoralar", "planet", "kosmos", "galaktika", "space"), "layout": "immersive full-screen WebGL canvas, restrained HUD labels, orbiting bodies and star field", "must_have": ("multiple distinct sphere meshes", "orbit controls", "lighting", "responsive renderer"), "vite": True},
    "room_3d": {"title": "3D xona/interyer", "keywords": ("xona", "interyer", "mebel", "stol", "divan", "yotoqxona", "room", "interior"), "layout": "architectural room shell, visible floor and walls, furniture grouped by function", "must_have": ("floor and walls as separate meshes", "at least three furniture objects", "orbit and zoom controls", "soft lighting"), "vite": True},
    "warehouse_3d": {"title": "3D ombor va zavod", "keywords": ("ombor", "warehouse", "zavod", "factory", "pallet", "stellaj", "logistika"), "layout": "readable warehouse floor plan in 3D, racks and pallets, clear aisle spacing", "must_have": ("racks and pallets as distinct meshes", "visible aisles", "orbit controls", "responsive renderer"), "vite": True},
    "birthday_gallery": {"title": "Tug‘ilgan kun va foto-galereya", "keywords": ("tug'ilgan", "tugilgan", "birthday", "tabrik", "surat", "rasm", "photo", "gallery"), "layout": "warm celebratory hero, elegant typography, photo-led composition and restrained motion", "must_have": ("uploaded photos displayed directly", "mobile-friendly layout", "working interactions", "reduced-motion support"), "vite": False},
    "portfolio": {"title": "Portfolio va biznes sayti", "keywords": ("portfolio", "biznes", "business", "landing", "sayt", "website", "agency", "company"), "layout": "strong hero, clear navigation, proof/services section and concise CTA", "must_have": ("responsive navigation", "working CTA links", "semantic sections", "accessible contrast"), "vite": False},
    "dashboard": {"title": "Dashboard va interaktiv panel", "keywords": ("dashboard", "panel", "statistika", "grafik", "chart", "monitoring", "analytics", "admin"), "layout": "calm dashboard, KPI cards, chart area, filters and responsive navigation", "must_have": ("meaningful sample data", "working filters", "readable chart labels", "mobile layout"), "vite": True},
    "general": {"title": "Universal responsive HTML", "keywords": (), "layout": "clear hierarchy, balanced whitespace, consistent component styling and mobile-first layout", "must_have": ("semantic HTML", "responsive layout", "working controls", "accessible text contrast"), "vite": False},
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
    return ("TANLANGAN STARTER: " + item["title"] + " (ID: " + key + ").\n"
            "Vizual tuzilma: " + item["layout"] + ".\n"
            "Majburiy sifat mezonlari: " + "; ".join(item["must_have"]) + ".\n"
            "Bu tayyor dizayn yo'nalishi, foydalanuvchi so'rovining o'rnini bosmaydi. "
            "So'rovdagi rang, obyekt, matn, rasm va joylashuv ko'rsatmalarini birinchi o'ringa qo'y. "
            "Shablonni mazmun va kompozitsiya bo'yicha vazifaga moslashtir.")

def _safe_project_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value or "creative-project").strip("-_").lower()
    return (value or "creative-project")[:48]

def create_vite_zip(html: str, project_name: str = "creative-project") -> bytes:
    """Package a complete HTML page as Vite source; does not run npm on Render."""
    if not isinstance(html, str) or "<html" not in html.lower() or "</html>" not in html.lower():
        raise ValueError("A complete HTML document is required")
    name = _safe_project_name(project_name)
    package = {"name": name, "private": True, "version": "1.0.0", "type": "module",
               "scripts": {"dev": "vite --host 0.0.0.0", "build": "vite build", "preview": "vite preview --host 0.0.0.0"},
               "devDependencies": {"vite": "^6.4.1"}}
    vite_config = """import { defineConfig } from 'vite';
export default defineConfig({ base: './', build: { outDir: 'dist', emptyOutDir: true, assetsInlineLimit: 4096 } });
"""
    readme = ("# " + name + "\n\nNavyblue Creative Builder Vite project.\n\n"
              "## Run locally\n1. Install Node.js LTS from https://nodejs.org/\n"
              "2. Open a terminal in this folder.\n3. Run npm install\n4. Run npm run dev\n\n"
              "## Production\nRun npm run build. The production website is written to dist/. "
              "Run npm run preview to inspect the production build locally.\n\n"
              "Note: Three.js CDN/import-map projects may require an internet connection.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("index.html", html)
        zf.writestr("package.json", json.dumps(package, ensure_ascii=False, indent=2) + "\n")
        zf.writestr("vite.config.js", vite_config)
        zf.writestr("README.md", readme)
        zf.writestr(".gitignore", "node_modules/\ndist/\n.DS_Store\n")
    return buf.getvalue()
