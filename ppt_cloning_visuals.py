"""Original, clearly labelled educational visuals for biological cloning slides.

These are explanatory schematics, not documentary photographs or clinical images.
"""
from __future__ import annotations
import io
import re
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
_BG = (7, 23, 39)
_PALE = (232, 241, 244)
_BLUE = (74, 165, 211)
_TEAL = (70, 190, 167)
_GOLD = (231, 185, 104)
_RED = (225, 104, 111)

def _norm(value):
    value = str(value or "").casefold().replace("ʻ", "'").replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9' ]+", " ", value)

def cloning_topic(topic: str) -> bool:
    t = _norm(topic)
    keys = ("klonlash", "klon", "cloning", "clone", "somatic cell nuclear transfer",
            "dolly sheep", "dolly qo'y", "dolly qoy", "biologik klon")
    return any(k in t for k in keys)

def cloning_visual_kind(topic: str, title: str = "", body: str = "") -> str:
    t = _norm(" ".join((title, body)))
    rules = (
        ("dolly", ("dolly", "qo'y", "qoy", "sheep", "sut emizuvchi")),
        ("nuclear_transfer", ("yadro", "nucleus", "somatic", "transfer", "ko'chirish", "kochir"),
         ),
        ("organoid", ("organ", "organoid", "transplant", "transplantatsiya", "to'qima", "to'qima", "tissue", "sun'iy organ")),
        ("phenotype", ("fenotip", "phenotype", "o'xshash", "oxshash", "belgi", "genetik va tashqi")),
        ("ethics", ("etika", "axloq", "huquq", "xavf", "mas'uliyat", "masuliyat", "ethic", "risk", "regulation")),
    )
    for item in rules:
        kind, phrases = item[0], item[1]
        if any(p in t for p in phrases):
            return kind
    return "dna"

def _font(size, bold=False):
    candidates = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _base(kind):
    im = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(im, "RGBA")
    for x in range(0, W, 80):
        d.line((x, 0, x, H), fill=(100, 155, 185, 18), width=1)
    for y in range(0, H, 80):
        d.line((0, y, W, y), fill=(100, 155, 185, 18), width=1)
    d.rounded_rectangle((42, 42, W-42, H-42), radius=34, outline=(130, 185, 205, 100), width=3)
    d.rounded_rectangle((76, 735, W-76, 820), radius=18, fill=(5, 15, 28, 225), outline=(120, 165, 185, 110), width=2)
    d.text((105, 760), "BIOLOGIK KLONLASH  •  O'QUV SXEMASI, FOTOGRAFIK DALIL EMAS",
           font=_font(22, True), fill=_PALE)
    return im, d

def _sheep(d, cx, cy, scale=1.0, color=(225, 232, 232, 255)):
    # Stylised sheep silhouette; deliberately an illustration, not a claimed photo of Dolly.
    def box(v): return tuple(int(z) for z in v)
    d.ellipse(box((cx-205*scale, cy-105*scale, cx+155*scale, cy+125*scale)), fill=color)
    for dx,dy,r in [(-165,-70,58),(-95,-118,64),(-10,-130,66),(78,-105,62),(145,-55,58),(-175,20,58),(-90,65,62),(5,72,65),(105,48,58)]:
        d.ellipse(box((cx+dx*scale-r*scale,cy+dy*scale-r*scale,cx+dx*scale+r*scale,cy+dy*scale+r*scale)),fill=color)
    d.ellipse(box((cx+115*scale,cy-100*scale,cx+265*scale,cy+45*scale)),fill=color)
    d.ellipse(box((cx+218*scale,cy-65*scale,cx+244*scale,cy-39*scale)),fill=(20,35,48,255))
    d.polygon(box((cx+220*scale,cy-88*scale,cx+300*scale,cy-130*scale,cx+278*scale,cy-58*scale)),fill=(190,205,210,255))
    for x in (-125,75):
        d.rounded_rectangle(box((cx+x*scale,cy+70*scale,cx+(x+25)*scale,cy+235*scale)),radius=9,fill=(205,215,216,255))
    d.arc(box((cx+210*scale,cy-4*scale,cx+290*scale,cy+80*scale)),0,180,fill=(225,232,232,255),width=max(3,int(7*scale)))

def render_cloning_visual(kind: str = "dna", variant: int = 0) -> bytes:
    kind = kind if kind in {"dna","dolly","nuclear_transfer","organoid","phenotype","ethics"} else "dna"
    im,d = _base(kind)
    if kind == "dolly":
        _sheep(d, 610, 390, 1.15)
        d.rounded_rectangle((1010,190,1410,610),radius=28,fill=(18,48,67,230),outline=_GOLD,width=4)
        d.text((1060,245),"DOLLY",font=_font(48,True),fill=_GOLD)
        d.text((1060,325),"1996–2003",font=_font(31,True),fill=_PALE)
        d.text((1060,400),"Somatik hujayra",font=_font(24),fill=_PALE)
        d.text((1060,440),"yadrosini ko'chirish",font=_font(24),fill=_PALE)
        d.text((1060,480),"orqali yaratilgan",font=_font(24),fill=_PALE)
        d.text((1060,520),"birinchi sutemizuvchi",font=_font(24),fill=_PALE)
        d.text((125,120),"DOLLY QO'YI — TARIXIY ILMIY NATIJA",font=_font(30,True),fill=_PALE)
    elif kind == "nuclear_transfer":
        d.text((120,105),"SOMATIK HUJAYRA YADROSINI KO'CHIRISH",font=_font(32,True),fill=_PALE)
        xs=(300,800,1300)
        labels=("1. TUXUM HUJAYRA","2. YADRO KO'CHIRISH","3. EMBRION RIVOJI")
        for x,label in zip(xs,labels):
            d.ellipse((x-115,250,x+115,480),fill=(30,77,101,210),outline=_BLUE,width=8)
            d.ellipse((x-40,330,x+40,410),fill=_GOLD,outline=_PALE,width=4)
            d.text((x-150,535),label,font=_font(22,True),fill=_PALE)
        d.line((430,365,660,365),fill=_TEAL,width=12); d.polygon([(660,345),(700,365),(660,385)],fill=_TEAL)
        d.line((930,365,1160,365),fill=_TEAL,width=12); d.polygon([(1160,345),(1200,365),(1160,385)],fill=_TEAL)
        d.text((550,650),"Yadro donor somatik hujayradan olinadi",font=_font(24),fill=_GOLD)
    elif kind == "organoid":
        d.text((120,105),"HUJAYRADAN TO'QIMA MODELLARIGACHA",font=_font(32,True),fill=_PALE)
        d.ellipse((190,260,470,540),fill=(26,87,113,230),outline=_BLUE,width=8)
        d.ellipse((275,345,385,455),fill=_GOLD)
        d.text((245,575),"STEM HUJAYRA",font=_font(24,True),fill=_PALE)
        d.line((500,400,690,400),fill=_TEAL,width=12); d.polygon([(690,380),(730,400),(690,420)],fill=_TEAL)
        for x,y,r in [(930,330,90),(1080,400,105),(950,500,72),(1190,540,68),(1250,300,65)]:
            d.ellipse((x-r,y-r,x+r,y+r),fill=(57,139,133,130),outline=_TEAL,width=7)
            for a,b in [(-25,-15),(22,20),(0,38)]:
                d.ellipse((x+a-15,y+b-15,x+a+15,y+b+15),fill=_GOLD)
        d.text((910,650),"ORGANOID / TO'QIMA MODELI",font=_font(24,True),fill=_PALE)
        d.text((120,680),"Bu laboratoriya modeli; to'liq inson organi bilan teng emas",font=_font(20),fill=_GOLD)
    elif kind == "phenotype":
        d.text((120,105),"GENOTIP VA FENOTIP: O'XSHASHLIK HAR DOIM BIR XIL EMAS",font=_font(29,True),fill=_PALE)
        for cx in (480,1120):
            _sheep(d,cx,390,.78)
        d.text((365,650),"BIR XIL YADRO DNKSI",font=_font(23,True),fill=_BLUE)
        d.text((1000,650),"MUHIT + RIVOJLANISH",font=_font(23,True),fill=_GOLD)
        d.line((800,220,800,690),fill=(180,200,210,100),width=3)
    elif kind == "ethics":
        d.text((120,105),"BIOETIKA: ILMIY IMKONIYAT VA MAS'ULIYAT",font=_font(32,True),fill=_PALE)
        d.line((800,245,800,600),fill=_GOLD,width=20)
        d.line((570,330,1030,330),fill=_GOLD,width=16)
        d.line((650,330,560,510),fill=_BLUE,width=7); d.line((950,330,1040,510),fill=_BLUE,width=7)
        d.arc((440,460,680,620),0,180,fill=_TEAL,width=12)
        d.arc((920,460,1160,620),0,180,fill=_RED,width=12)
        d.text((365,640),"DAVOLASH • TADQIQOT",font=_font(22,True),fill=_TEAL)
        d.text((925,640),"XAVF • HUQUQ • ROZILIK",font=_font(22,True),fill=_RED)
    else:
        d.text((120,105),"DNK — IROSIY AXBOROT TASHUVCHISI",font=_font(32,True),fill=_PALE)
        for x in range(300,1320,28):
            import math
            y1=420+145*math.sin((x-300)/105)
            y2=420-145*math.sin((x-300)/105)
            d.line((x,y1,x,y2),fill=_BLUE,width=5)
            if (x-300)%112==0:
                d.line((x,y1,x,y2),fill=_GOLD,width=9)
        d.line((260,420,1340,420),fill=(130,180,200,80),width=2)
    out=io.BytesIO()
    im.save(out,"PNG",optimize=True)
    return out.getvalue()
