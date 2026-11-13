"""Topic-specific cardiovascular illustrations for generated PowerPoint slides.

These are original simplified educational schematics, not diagnostic anatomy.
"""
from __future__ import annotations

import io
import math
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1600, 900

def _fold(value):
    value = str(value or "").casefold().replace("ʻ", "'").replace("’", "'")
    return re.sub(r"[^a-z0-9' ]+", " ", value)

def cardiovascular_topic(topic: str) -> bool:
    t = _fold(topic)
    keys = ("yurak", "qon tomir", "qon aylanish", "cardiovascular", "heart", "blood vessel",
            "circulatory system", "arteriya", "vena", "kapillyar")
    return any(k in t for k in keys)

def cardiovascular_visual_kind(topic: str, title: str = "", body: str = "") -> str | None:
    if not cardiovascular_topic(topic):
        return None
    t = _fold(" ".join((topic, title, body)))
    rules = [
        (("ekg", "ecg", "elektrokardi", "yurak ritm", "puls", "urish chastot"), "ecg"),
        (("arteriya", "vena", "kapillyar", "tomir devor", "qon tomir", "aorta"), "vessels"),
        (("kichik qon aylanish", "katta qon aylanish", "qon aylanish doir", "o'pka qon", "tana qon"), "circulation"),
        (("bo'lmacha", "qorincha", "yurak kamer", "to'rt kamer", "yurak tuzil"), "chambers"),
        (("klapan", "qopqoq", "mitral", "trikuspid", "aortal", "pulmonal"), "valves"),
        (("qon tarkib", "eritrotsit", "leykotsit", "trombotsit", "gemoglobin", "qon hujay"), "blood"),
        (("profilaktika", "sog'lom turmush", "kasallik", "infarkt", "gipertoniya", "ateroskleroz", "xavf omil"), "health"),
    ]
    for terms, kind in rules:
        if any(term in t for term in terms):
            return kind
    return "heart"

def _font(size, bold=False):
    paths = (("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
             "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _heart_points(cx, cy, scale):
    pts = []
    for i in range(181):
        t = math.pi * 2 * i / 180
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
        pts.append((cx + x * scale / 32, cy - y * scale / 32))
    return pts

def _arrow(draw, start, end, color, width=18):
    draw.line((start, end), fill=color, width=width)
    ang = math.atan2(end[1]-start[1], end[0]-start[0])
    size = width * 1.8
    p1 = (end[0]-size*math.cos(ang-0.55), end[1]-size*math.sin(ang-0.55))
    p2 = (end[0]-size*math.cos(ang+0.55), end[1]-size*math.sin(ang+0.55))
    draw.polygon((end, p1, p2), fill=color)

def render_cardiovascular_visual(kind: str = "heart", variant: int = 0) -> bytes:
    """Return a 1600x900 original educational cardiovascular illustration."""
    kind = kind if kind in {"heart", "circulation", "vessels", "chambers", "valves", "ecg", "blood", "health"} else "heart"
    im = Image.new("RGB", (W, H), "#071B31")
    px = im.load()
    top, bottom = (7, 27, 49), (13, 49, 69)
    for y in range(H):
        q = y / (H - 1)
        c = tuple(int(top[i]*(1-q) + bottom[i]*q) for i in range(3))
        for x in range(W):
            px[x, y] = c
    d = ImageDraw.Draw(im, "RGBA")
    # Fine technical grid and soft glows keep the illustration polished without obscuring it.
    for x in range(0, W, 80):
        d.line((x, 0, x, H), fill=(110, 166, 194, 17), width=1)
    for y in range(0, H, 80):
        d.line((0, y, W, y), fill=(110, 166, 194, 17), width=1)
    d.rounded_rectangle((45, 42, 1555, 858), radius=38, outline=(111, 177, 204, 100), width=3)
    d.ellipse((460, 100, 1140, 780), fill=(32, 108, 133, 26))
    d.ellipse((560, 200, 1040, 700), fill=(35, 119, 145, 22))
    red, blue, pale, gold = (242, 91, 94, 255), (73, 164, 224, 255), (225, 241, 246, 245), (239, 190, 102, 255)

    if kind in ("heart", "chambers", "valves"):
        # Main cardiac silhouette and major vessels.
        d.rounded_rectangle((700, 105, 825, 330), radius=55, fill=red)
        d.rounded_rectangle((850, 120, 965, 315), radius=48, fill=blue)
        d.line((755, 255, 755, 145, 700, 95), fill=red, width=62)
        d.line((900, 255, 930, 150, 1010, 100), fill=blue, width=56)
        d.line((690, 300, 610, 205, 560, 160), fill=blue, width=38)
        d.line((965, 300, 1030, 215, 1080, 175), fill=red, width=38)
        d.polygon(_heart_points(800, 520, 430), fill=(181, 53, 70, 255), outline=(255, 174, 165, 255))
        d.line((800, 355, 800, 710), fill=(255, 210, 190, 235), width=12)
        if kind == "chambers":
            d.line((610, 515, 990, 515), fill=(255, 226, 215, 245), width=12)
            d.ellipse((625, 410, 785, 535), fill=(83, 161, 218, 235), outline=pale, width=6)
            d.ellipse((815, 410, 975, 535), fill=(222, 83, 88, 235), outline=pale, width=6)
            d.ellipse((635, 555, 785, 690), fill=(64, 137, 202, 235), outline=pale, width=6)
            d.ellipse((815, 555, 965, 690), fill=(190, 61, 70, 235), outline=pale, width=6)
            for x, y, label in [(705, 470, "O'NG"), (895, 470, "CHAP"), (710, 615, "O'NG"), (890, 615, "CHAP")]:
                d.text((x-32, y-12), label, font=_font(20, True), fill=(255,255,255,255))
        elif kind == "valves":
            for x, y in [(720, 500), (880, 500), (720, 620), (880, 620)]:
                d.ellipse((x-46, y-35, x+46, y+35), outline=gold, width=13)
                d.line((x-28, y+20, x, y-22, x+28, y+20), fill=pale, width=9)
            d.text((610, 745), "YURAK QOPQOQLARI — SODDALASHTIRILGAN SXEMA",
                   font=_font(24, True), fill=pale)
    elif kind == "circulation":
        # Pulmonary and systemic circulation loops around the heart.
        d.ellipse((650, 270, 950, 630), fill=(181, 53, 70, 245), outline=(255, 180, 170, 255), width=8)
        d.polygon(_heart_points(800, 465, 245), fill=(235, 102, 104, 255))
        d.ellipse((185, 270, 485, 585), fill=(63, 142, 190, 220), outline=blue, width=8)
        d.ellipse((1115, 270, 1415, 585), fill=(62, 139, 185, 220), outline=blue, width=8)
        d.text((265, 405), "O'PKA", font=_font(34, True), fill=pale)
        d.text((1195, 405), "TANA", font=_font(34, True), fill=pale)
        _arrow(d, (650, 355), (475, 355), blue, 20)
        _arrow(d, (485, 515), (650, 515), red, 20)
        _arrow(d, (950, 355), (1120, 355), red, 20)
        _arrow(d, (1115, 515), (950, 515), blue, 20)
        d.text((675, 700), "KICHIK VA KATTA QON AYLANISH DOIRASI", font=_font(25, True), fill=pale)
    elif kind == "vessels":
        # Artery and vein cross sections.
        for cx, col, inner, label in [(520, red, (255, 185, 174, 255), "ARTERIYA"),
                                      (1080, blue, (150, 210, 239, 255), "VENA")]:
            d.ellipse((cx-245, 190, cx+245, 680), fill=col, outline=pale, width=10)
            d.ellipse((cx-170, 265, cx+170, 605), fill=(18, 43, 66, 255), outline=inner, width=20)
            for a in range(0, 360, 45):
                rad = math.radians(a)
                x1, y1 = cx+185*math.cos(rad), 435+185*math.sin(rad)
                x2, y2 = cx+215*math.cos(rad), 435+215*math.sin(rad)
                d.line((x1, y1, x2, y2), fill=pale, width=8)
            d.text((cx-120, 735), label, font=_font(34, True), fill=pale)
        d.text((620, 95), "TOMIR DEVORINING KO'NDALANG KESIMI", font=_font(26, True), fill=gold)
    elif kind == "ecg":
        d.rounded_rectangle((115, 165, 1485, 725), radius=28, fill=(5, 24, 42, 170), outline=(100, 177, 205, 150), width=4)
        for x in range(145, 1485, 42):
            d.line((x, 185, x, 705), fill=(90, 155, 185, 35), width=1)
        for y in range(205, 705, 42):
            d.line((135, y, 1465, y), fill=(90, 155, 185, 35), width=1)
        pts = []
        for base in (250, 650, 1050):
            pts.extend([(base, 465), (base+45, 465), (base+72, 430), (base+100, 465),
                        (base+130, 465), (base+160, 565), (base+188, 255), (base+220, 520),
                        (base+250, 465), (base+320, 465)])
        d.line(pts, fill=(84, 231, 192, 255), width=12, joint="curve")
        d.text((155, 90), "ELEKTROKARDIOGRAMMA — RITM SXEMASI", font=_font(27, True), fill=pale)
    elif kind == "blood":
        # Vessel lumen populated by red cells and platelets.
        d.rounded_rectangle((130, 250, 1470, 650), radius=190, fill=(106, 36, 55, 255), outline=(245, 125, 125, 255), width=18)
        d.rounded_rectangle((165, 285, 1435, 615), radius=160, fill=(35, 30, 54, 255), outline=(255, 184, 160, 180), width=8)
        for i in range(15):
            x = 245 + (i % 5) * 245 + (i // 5) * 18
            y = 360 + (i // 5) * 95 + (i % 2) * 20
            d.ellipse((x-62, y-32, x+62, y+32), fill=(221, 64, 78, 255), outline=(255, 180, 170, 255), width=6)
            d.ellipse((x-25, y-13, x+25, y+13), fill=(145, 35, 58, 255))
        for x, y in [(450, 520), (990, 345), (1250, 520)]:
            d.ellipse((x-12, y-12, x+12, y+12), fill=gold)
        d.text((460, 735), "QON HUJAYRALARI — SODDALASHTIRILGAN TASVIR", font=_font(25, True), fill=pale)
    elif kind == "health":
        d.ellipse((500, 140, 1100, 740), fill=(25, 99, 119, 160), outline=(114, 207, 190, 230), width=8)
        d.polygon(_heart_points(800, 445, 360), fill=(202, 62, 78, 255), outline=(255, 188, 177, 255))
        d.polygon([(800, 595), (685, 520), (715, 690), (800, 760), (885, 690), (915, 520)],
                  fill=(66, 164, 134, 245), outline=pale)
        d.line((800, 620, 800, 710), fill=pale, width=14)
        d.line((755, 665, 845, 665), fill=pale, width=14)
        for cx, cy, label in [(300, 260, "HARAKAT"), (1300, 260, "OVQATLANISH"), (300, 650, "NAZORAT"), (1300, 650, "CHEKISHNI TASHLASH")]:
            d.ellipse((cx-115, cy-95, cx+115, cy+95), fill=(14, 55, 78, 225), outline=gold, width=5)
            d.text((cx-95, cy-12), label, font=_font(19, True), fill=pale)
    # Small, consistent source note makes the schematic nature explicit.
    d.text((90, 805), "O'QUV ILUSTRATSIYASI  •  SODDALASHTIRILGAN SXEMA", font=_font(18, True),
           fill=(190, 218, 230, 190))
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()
