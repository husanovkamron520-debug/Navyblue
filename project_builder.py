"""Staged, modular generation for complex Creative Builder projects.

The model creates a short blueprint, then independent CSS, HTML-body and
JavaScript fragments. The fragments are assembled into one portable HTML file.
"""
from __future__ import annotations

import asyncio
import re


_COMPLEX = re.compile(
    r"\b(dashboard|web[- ]?app|web[- ]?ilova|platforma|ta'lim platformasi|"
    r"boshqaruv tizimi|admin panel|crm|erp|analytics|monitoring|"
    r"login|autentifikatsiya|foydalanuvchi kabineti|ko'p sahifa|"
    r"multiple pages|interactive system|interaktiv tizim|"
    r"3d|simulyator|simulator)\b",
    re.I,
)
_MARKERS = {
    "css": "/*__PROJECT_BUILDER_END_CSS__*/",
    "html": "<!--__PROJECT_BUILDER_END_HTML__-->",
    "js": "//__PROJECT_BUILDER_END_JS__",
}


def should_use_modular(request: str, existing: str | None = None) -> bool:
    """Route complex new builds to staged generation; keep small edits on legacy path."""
    if existing:
        return False
    words = re.findall(r"\w+", request or "", flags=re.UNICODE)
    return len(words) >= 28 or bool(_COMPLEX.search(request or ""))


def _unwrap(raw: str, kind: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^\s*```(?:css|html|javascript|js)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```\s*$", "", text)
    if kind == "css":
        match = re.search(r"<style\b[^>]*>(.*?)</style\s*>", text, re.I | re.S)
        if match:
            text = match.group(1)
    elif kind == "html":
        match = re.search(r"<body\b[^>]*>(.*?)</body\s*>", text, re.I | re.S)
        if match:
            text = match.group(1)
    elif kind == "js":
        match = re.search(r"<script\b[^>]*>(.*?)</script\s*>", text, re.I | re.S)
        if match:
            text = match.group(1)
    return text.strip()


async def _complete_fragment(generate_text, prompt: str, kind: str, rounds: int = 2) -> str | None:
    marker = _MARKERS[kind]
    raw = await asyncio.to_thread(generate_text, prompt)
    combined = (raw or "").strip()
    remaining = rounds
    while marker not in combined and remaining:
        if not combined:
            return None
        anchor = combined[-220:]
        continuation = (
            "Oldingi kod bo'lagi uzildi. Boshidan yozma. Aynan shu joydan davom et. "
            "Javobni quyidagi oxirgi qismni aynan bir marta takrorlashdan boshla, "
            "so'ng darhol davom ettir va oxirida markerning o'zini yoz. "
            "Hech qanday izoh yoki markdown fence qo'shma.\nOXIRGI QISM:\n"
            + anchor + "\nYAKUNIY MARKER: " + marker
        )
        remaining -= 1
        part = (await asyncio.to_thread(generate_text, continuation) or "").strip()
        if not part:
            return None
        pos = part.find(anchor)
        if pos >= 0:
            part = part[pos + len(anchor):]
        elif re.search(r"<!doctype\s+html|<html\b", part, re.I):
            return None
        combined += part
    if marker not in combined:
        return None
    combined = combined.split(marker, 1)[0]
    return _unwrap(combined, kind)


def assemble_document(css: str, body: str, javascript: str, three: bool = False) -> str:
    """Assemble independent source fragments into a single standalone HTML document."""
    import_map = ""
    script_type = ""
    if three:
        import_map = (
            '<script type="importmap">{"imports":{'
            '"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",'
            '"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"'
            "}}</script>"
        )
        script_type = ' type="module"'
    return (
        '<!DOCTYPE html>\n<html lang="uz">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<meta name="theme-color" content="#101827">\n'
        '<title>Creative Project</title>\n'
        + import_map + "\n<style>\n" + css + "\n</style>\n</head>\n<body>\n"
        + body + "\n<script" + script_type + ">\n" + javascript
        + "\n</script>\n</body>\n</html>"
    )


async def generate_modular(generate_text, request: str, context_prompt: str) -> str | None:
    """Generate a complex project in bounded stages and assemble one HTML artifact."""
    plan_prompt = (
        context_prompt
        + "\n\nBOSQICH 1/4 — LOYIHA REJASI. Faqat qisqa texnik reja qaytar: "
        "sahifa bo'limlari, asosiy komponentlar, ma'lumotlar modeli, ishlaydigan "
        "interaksiyalar va mobil moslashuv. Kod yozma. Foydalanuvchi talablarini "
        "to'liq qamrab ol, ortiqcha funksiya o'ylab topma.\nSO'ROV: " + request
    )
    plan = (await asyncio.to_thread(generate_text, plan_prompt) or "").strip()
    if len(plan) < 20:
        return None
    plan = plan[:6000]
    three = bool(re.search(r"\b3d\b|sayyora|kosmos|xona|ombor|warehouse", request, re.I))
    common = (
        "\n\nASOSIY REJA:\n" + plan
        + "\n\nFoydalanuvchi so'rovi: " + request
        + "\nBarcha matn o'zbek tilida bo'lsin. Mobil va desktop ekranlarga mos bo'lsin. "
        "Barcha ko'rsatilgan tugma va boshqaruvlar haqiqiy ishlasin. "
        "Tashqi kutubxona yoki CDN qo'shma, faqat 3D uchun Three.js importmap ruxsat. "
        "TODO, placeholder, soxta tugma yoki ishlamaydigan demo qo'shma. "
    )
    css_prompt = (
        common + "\nBOSQICH 2/4 — FAQAT CSS. To'liq vizual dizaynni yoz: ranglar, "
        "tipografiya, grid/flex layout, responsive breakpointlar, hover/focus, "
        "mobil navigatsiya va empty/loading/error holatlari. HTML yoki JS yozma. "
        "Taxminan 3–6 ming belgi atrofida ixcham yoz. Oxirida aynan "
        + _MARKERS["css"]
    )
    css = await _complete_fragment(generate_text, css_prompt, "css")
    if not css or len(css) > 40000:
        return None

    body_prompt = (
        common + "\nBOSQICH 3/4 — FAQAT HTML BODY ICHIDAGI MARKUP. "
        "To'liq semantik sahifa tuzilmasini, barcha bo'limlar, kartalar, "
        "jadval/grafik konteynerlari, formalar, tugmalar va aniq ID/data-attribute'larni "
        "yarat. <html>, <head>, <body>, <style> va <script> teglarini yozma. "
        "JS yozma. Barcha kontentni to'ldir; bo'sh placeholder qoldirma. "
        "Rasm tokenlarini aynan saqla.\nCSS KONTEKSTI:\n" + css[:5000]
        + "\nOxirida aynan " + _MARKERS["html"]
    )
    body = await _complete_fragment(generate_text, body_prompt, "html")
    if not body or len(body) > 60000:
        return None

    js_prompt = (
        common + "\nBOSQICH 4/4 — FAQAT ISHLAYDIGAN JAVASCRIPT. "
        "HTML/CSS qaytarma. Yuqoridagi HTML elementlarining ID'lariga mos kod yoz. "
        "Barcha tugmalar, qidiruv, filter, sort, forma validatsiyasi, modal, tab, "
        "grafik va interaksiyalar ishlasin. Ma'lumotlar uchun izchil namunaviy dataset "
        "ishlat; KPI va grafik qiymatlari o'zaro mos bo'lsin. Xatolarni try/catch bilan "
        "ushla, element topilmasa sahifani yiqitma.\nHTML KONTEKSTI:\n" + body[:9000]
        + "\nCSS KONTEKSTI:\n" + css[:4000]
        + ("\nThree.js r160 va OrbitControls importmap orqali import qil. "
           "Haqiqiy WebGLRenderer, Scene, Camera, Mesh, Light, render loop, resize va "
           "touch/mouse OrbitControls bo'lsin. Mobil DPR cheklansin. "
           "Agar so'rov kosmos yoki sayyoralar haqida bo'lsa: CanvasTexture procedural "
           "surface, bumpMap yoki normalMap, EffectComposer va UnrealBloomPass (fallback bilan), "
           "ShaderMaterial/Fresnel atmosfera, InstancedMesh asteroidlar, smooth camera lerp/fly-to, "
           "castShadow/receiveShadow, MeshStandardMaterial yoki MeshPhysicalMaterial va xato fallback "
           "hammasi ishlaydigan kodda bo'lsin. " if three else "")
        + "\nFaqat JavaScript. Oxirida aynan " + _MARKERS["js"]
    )
    javascript = await _complete_fragment(generate_text, js_prompt, "js")
    if not javascript or len(javascript) > 100000:
        return None
    return assemble_document(css, body, javascript, three=three)
