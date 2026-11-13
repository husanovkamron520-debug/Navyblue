"""Original, non-photorealistic illustrations for Remus Lupin presentation slides.

The artwork is an educational fan-style interpretation, not a portrait of the film actor
or an official still. It uses distinct scene types instead of generic node-network filler.
"""
from __future__ import annotations

import io
import re
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
_BG = (10, 18, 34)
_INK = (18, 27, 43)
_GOLD = (211, 177, 112)
_PALE = (238, 233, 218)
_BLUE = (91, 133, 169)
_MOON = (226, 220, 190)
_RED = (139, 68, 73)


def _norm(value):
    value = str(value or "").casefold().replace("’", " ").replace("ʻ", " ").replace("‘", " ").replace("'", " ")
    return re.sub(r"[^a-z0-9 ]+", " ", value)


def remus_lupin_topic(value: str) -> bool:
    t = _norm(value)
    return any(term in t for term in (
        "remus lupin", "remus john lupin", "remus", "professor lupin",
        "remus lupin o tmish", "lupin werewolf",
    ))


def remus_lupin_visual_kind(topic: str, title: str = "", body: str = "") -> str:
    t = _norm(" ".join((topic, title, body)))
    rules = (
        ("werewolf", ("bo ri", "bo ri odam", "werewolf", "lycanthropy", "likantrop", "oy to lishi", "la'nat")),
        ("professor", ("professor", "hogwarts", "xogvarts", "dark arts", "qorong u san at", "dars")),
        ("marauders", ("marauders", "talonchilar", "prongs", "padfoot", "wormtail", "moony", "xarita")),
        ("order_phoenix", ("feniks", "phoenix", "order of the phoenix", "qarshilik", "urush", "jang")),
        ("patronus", ("patronus", "patronus afsuni", "expecto patronum", "kumush bo ri")),
        ("full_moon", ("to lin oy", "full moon", "oy fazasi", "transformatsiya", "o zgarish")),
        ("portrait", ("lupin portreti", "lupinning hayoti", "bolaligi")),
    )
    for kind, phrases in rules:
        if any(p in t for p in phrases):
            return kind
    return "portrait"


def _font(size: int, bold: bool = False):
    paths = (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _base(kind):
    im = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(im, "RGBA")
    for y in range(H):
        shade = int(12 + 16 * y / H)
        d.line((0, y, W, y), fill=(shade, shade + 8, shade + 20, 255))
    # moonlit vignette and restrained parchment framing
    d.ellipse((1080, -260, 1740, 400), fill=(103, 126, 151, 24))
    d.rounded_rectangle((42, 42, W-42, H-42), radius=30, outline=(*_GOLD, 115), width=3)
    d.rounded_rectangle((78, 755, W-78, 820), radius=14, fill=(5, 12, 24, 225), outline=(*_GOLD, 95), width=2)
    d.text((110, 773), "REMUS LUPIN  •  ORIGINAL ILLUSTRATIVE ART", font=_font(20, True), fill=_PALE)
    return im, d


def _person(d, cx=690, cy=425, scale=1.0, cloak=True):
    # Fictional, original interpretation: no resemblance to any actor.
    def box(v):
        return tuple(int(z) for z in v)
    def pts(values):
        return [(int(x), int(y)) for x, y in values]
    coat = (39, 55, 75, 255)
    d.polygon(pts([(cx-210*scale,cy+390*scale),(cx-150*scale,cy+55*scale),
                   (cx-80*scale,cy-10*scale),(cx+75*scale,cy-10*scale),
                   (cx+165*scale,cy+65*scale),(cx+230*scale,cy+390*scale)]),
              fill=coat if cloak else (65,78,90,255))
    d.ellipse(box((cx-118*scale,cy-250*scale,cx+118*scale,cy+25*scale)), fill=(190,151,119,255))
    # slightly untidy, greying hair
    d.pieslice(box((cx-130*scale,cy-285*scale,cx+130*scale,cy-15*scale)),180,360,fill=(133,127,119,255))
    for dx,dy in [(-95,-225),(-55,-270),(-5,-280),(48,-260),(92,-220)]:
        d.line(box((cx+dx*scale,cy+dy*scale,cx+(dx-18)*scale,cy+(dy+65)*scale)),
               fill=(179,174,158,255),width=max(2,int(12*scale)))
    # tired but kind eyes, subtle facial details
    for ex in (-48,48):
        d.ellipse(box((cx+(ex-13)*scale,cy-120*scale,cx+(ex+13)*scale,cy-103*scale)),fill=(35,42,47,255))
        d.arc(box((cx+(ex-23)*scale,cy-139*scale,cx+(ex+23)*scale,cy-105*scale)),190,345,fill=(95,70,64,255),width=max(2,int(4*scale)))
    d.line(box((cx,cy-105*scale,cx-10*scale,cy-52*scale)),fill=(128,93,76,255),width=max(2,int(4*scale)))
    d.arc(box((cx-30*scale,cy-55*scale,cx+35*scale,cy-15*scale)),5,165,fill=(92,54,51,255),width=max(2,int(4*scale)))
    # patched robe seams
    d.line(box((cx-145*scale,cy+115*scale,cx+145*scale,cy+115*scale)),fill=(*_GOLD,100),width=max(2,int(3*scale)))
    d.polygon(pts([(cx-30*scale,cy+30*scale),(cx+30*scale,cy+30*scale),
                   (cx+85*scale,cy+210*scale),(cx,cy+260*scale),(cx-85*scale,cy+210*scale)]),
              fill=(20,35,52,255))


def render_remus_lupin_visual(kind: str = "portrait", variant: int = 0) -> bytes:
    allowed = {"portrait","werewolf","professor","marauders","order_phoenix","patronus","full_moon"}
    kind = kind if kind in allowed else "portrait"
    im, d = _base(kind)
    if kind == "portrait":
        d.ellipse((980,120,1460,600),fill=(*_MOON,35),outline=(*_GOLD,190),width=5)
        _person(d, 690, 420, 1.12)
        d.text((1030, 620), "REMUS", font=_font(49,True), fill=_PALE)
        d.text((1030, 680), "LUPIN", font=_font(49,True), fill=_GOLD)
        d.text((130,120), "THE QUIET COURAGE", font=_font(25,True), fill=_GOLD)
    elif kind == "werewolf":
        d.ellipse((1060,95,1470,505),fill=(*_MOON,38),outline=(*_MOON,180),width=5)
        # restrained wolf silhouette
        d.ellipse((420,330,980,620),fill=(5,10,18,255))
        d.polygon(pts([(790,390),(930,220),(950,420),(1090,360),(1030,520),(900,570)]),fill=(5,10,18,255))
        d.polygon(pts([(480,400),(370,270),(540,330),(640,300),(700,430)]),fill=(5,10,18,255))
        d.ellipse((900,420,930,448),fill=(*_GOLD,255))
        d.text((145,130),"THE CURSE OF THE FULL MOON",font=_font(30,True),fill=_PALE)
        d.text((145,680),"A burden he bears — not the whole of who he is",font=_font(25),fill=_GOLD)
    elif kind == "professor":
        _person(d, 700, 390, 1.05)
        d.rectangle((1110,210,1370,650),fill=(26,35,48,210),outline=(*_GOLD,160),width=4)
        d.text((1150,270),"DEFENCE",font=_font(30,True),fill=_PALE)
        d.text((1150,315),"AGAINST",font=_font(25),fill=_GOLD)
        d.text((1150,355),"THE DARK",font=_font(27,True),fill=_PALE)
        d.text((1150,395),"ARTS",font=_font(30,True),fill=_PALE)
        d.text((145,120),"A TEACHER WHO UNDERSTOOD FEAR",font=_font(27,True),fill=_GOLD)
    elif kind == "marauders":
        # parchment map, trails and four discreet footprints
        d.rounded_rectangle((170,145,1430,700),radius=28,fill=(202,181,139,245),outline=(*_GOLD,255),width=7)
        for y in range(220,650,85):
            d.line((230,y,1360,y-25),fill=(100,79,57,90),width=3)
        for x,y,label in [(400,330,"MOONY"),(710,480,"PADFOOT"),(1010,300,"PRONGS"),(1190,540,"WORMTAIL")]:
            d.ellipse((x-13,y-13,x+13,y+13),fill=(65,52,42,255))
            d.text((x+24,y-15),label,font=_font(21,True),fill=(65,52,42,255))
        d.text((235,175),"THE MARAUDERS' MAP",font=_font(30,True),fill=(60,48,40,255))
    elif kind == "order_phoenix":
        d.ellipse((480,150,1120,790),outline=(*_GOLD,210),width=8)
        # phoenix-like rising wings and flame
        d.arc((330,230,800,700),190,330,fill=(190,102,73,245),width=28)
        d.arc((800,230,1270,700),210,350,fill=(190,102,73,245),width=28)
        d.polygon([(800,260),(740,440),(800,390),(860,440)],fill=(*_GOLD,240))
        d.polygon([(800,430),(680,650),(800,590),(920,650)],fill=(174,80,67,240))
        d.text((555,690),"THE ORDER OF THE PHOENIX",font=_font(25,True),fill=_PALE)
    elif kind == "patronus":
        d.ellipse((1080,95,1470,485),fill=(*_MOON,35),outline=(*_MOON,190),width=5)
        # silver wolf-like Patronus made from luminous linework
        for off in range(0,5):
            d.arc((430+off*5,240+off*5,1120-off*4,690-off*4),195,345,fill=(169,205,224,210-off*20),width=8)
        d.polygon([(690,430),(820,270),(855,440),(1020,380),(930,535),(770,570)],fill=(153,192,213,105))
        d.ellipse((870,425,895,450),fill=(235,244,248,255))
        d.text((140,135),"EXPECTO PATRONUM",font=_font(30,True),fill=_PALE)
    elif kind == "full_moon":
        for i in range(4):
            x=340+i*300
            d.ellipse((x,290,x+175,465),outline=(*_MOON,210),width=5)
            d.ellipse((x+18,308,x+157,447),fill=(*_MOON,35+i*12))
        d.text((330,535),"THE CYCLE OF THE FULL MOON",font=_font(31,True),fill=_PALE)
        d.text((350,600),"A recurring struggle — never his only identity",font=_font(24),fill=_GOLD)
    out=io.BytesIO()
    im.save(out,format="PNG",optimize=True)
    return out.getvalue()


def sanitize_remus_lupin_slide(slide: dict) -> bool:
    """Replace fabricated character KPIs/percentages with a factual qualitative explanation."""
    if not isinstance(slide, dict):
        return False
    layout = str(slide.get("layout") or "").casefold()
    has_metrics = layout in {"stats","kpi"} or bool(slide.get("stats") or slide.get("kpis"))
    if not has_metrics:
        # Character decks should not invent a percentage score as a decorative stat.
        serialized = " ".join(str(v) for v in slide.values() if isinstance(v, (str,int,float)))
        if re.search(r"\b100\s*%", serialized):
            slide["text"] = re.sub(r"\b100\s*%", "sadoqat va fidoyilik", str(slide.get("text") or ""))
            slide.pop("stats", None); slide.pop("kpis", None)
            return True
        return False
    slide.pop("stats", None)
    slide.pop("kpis", None)
    slide.pop("value", None)
    slide.pop("number", None)
    slide["layout"] = "image_text"
    existing = str(slide.get("text") or slide.get("body") or "").strip()
    if not existing or re.search(r"\b100\s*%", existing):
        slide["text"] = (
            "Remus Lupin Feniks ordeni a'zosi sifatida Voldemortga qarshi qarshilikda qatnashadi. "
            "Uning hissasi sun'iy foiz yoki reyting bilan emas, sadoqati, jasorati va boshqalarga "
            "ko'rsatgan yordami orqali ochib beriladi."
        )
    return True
