"""Mavzuga aniq mos, original fantasy illustrationlar."""
from __future__ import annotations
import re, io
from PIL import Image, ImageDraw

def _norm(value):
    value = str(value or "").casefold().replace("’", "'").replace("ʻ", "'").replace(chr(96), "'")
    return re.sub(r"\s+", " ", value)

def fantasy_visual_kind(topic, title, body=""):
    text = _norm(" ".join((topic, title, body)))
    rules = (
        ("deathly_hallows", ("deathly hallows", "o'lim tuhfalari", "o'lim hadyalari", "uch aka-uka ramzi")),
        ("azkaban_dementors", ("azkaban", "dementor", "dementorlar", "qorong'u qamoqxona")),
        ("chamber_basilisk", ("chamber of secrets", "sirli xona", "sirlar xonasi", "basilisk", "salazar slytherin")),
        ("prophecy_archive", ("prophecy", "bashoratlar zali", "bashorat sharlari", "bashoratlar")),
        ("hogwarts_castle", ("hogwarts", "xogvarts", "hogvarts", "hogwarts castle", "xogvarts qasri")),
    )
    for kind, phrases in rules:
        if any(p in text for p in phrases):
            return kind
    return None

def fantasy_photo_query(topic, title, body=""):
    kind = fantasy_visual_kind(topic, title, body)
    return {
        "hogwarts_castle": "gothic Scottish medieval castle silhouette misty highlands dramatic towers",
        "chamber_basilisk": "ancient underground gothic stone chamber giant serpent statue dark green torchlight",
        "prophecy_archive": "mysterious magical archive shelves glowing glass crystal spheres blue light",
        "azkaban_dementors": "dark sea fortress prison isolated rocky island storm fog black cloaked wraith silhouette",
        "deathly_hallows": None,
    }.get(kind) if kind else None

def _gradient(size, top, bottom):
    w, h = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    a = tuple(int(top[i:i+2], 16) for i in (0,2,4))
    b = tuple(int(bottom[i:i+2], 16) for i in (0,2,4))
    for y in range(h):
        t = y / max(1, h-1)
        color = tuple(round(a[i]*(1-t)+b[i]*t) for i in range(3))
        draw.line((0, y, w, y), fill=color)
    return image

def _save(im):
    out=io.BytesIO()
    im.save(out,format="PNG",optimize=True)
    return out.getvalue()

def render_fantasy_visual(kind, width=1600, height=900):
    palettes = {
        "deathly_hallows": ("101626","26354A"),
        "hogwarts_castle": ("071426","31435B"),
        "chamber_basilisk": ("061A1A","263B35"),
        "prophecy_archive": ("08162B","263D61"),
        "azkaban_dementors": ("080F1B","253849"),
    }
    top,bottom=palettes.get(kind,("101626","26354A"))
    im=_gradient((width,height),top,bottom).convert("RGBA")
    d=ImageDraw.Draw(im,"RGBA")
    w,h=width,height
    if kind=="deathly_hallows":
        # Exact symbol geometry: triangle, inscribed circle, vertical line; no pentagram or star.
        cx,apex,base=w//2,int(h*.19),int(h*.82)
        left,right=int(w*.29),int(w*.71)
        gold=(224,194,125,255)
        d.ellipse((cx-260,int(h*.50)-260,cx+260,int(h*.50)+260),outline=gold,width=10)
        d.line((cx,apex,cx,base+18),fill=gold,width=12)
        d.line((cx,apex,left,base),fill=gold,width=12)
        d.line((left,base,right,base),fill=gold,width=12)
        d.line((right,base,cx,apex),fill=gold,width=12)
    elif kind=="hogwarts_castle":
        d.polygon([(0,h*.68),(w*.12,h*.48),(w*.22,h*.60),(w*.38,h*.39),(w*.50,h*.58),(w*.68,h*.37),(w*.83,h*.56),(w,h*.43),(w,h),(0,h)],fill=(24,39,57,255))
        base=int(h*.78)
        d.polygon([(0,base),(w*.12,base-80),(w*.22,base-40),(w*.32,base-135),(w*.44,base-70),(w*.56,base-170),(w*.69,base-80),(w*.82,base-145),(w,base-55),(w,h),(0,h)],fill=(8,17,31,255))
        for x,top_y,ww in ((.17,.34,.075),(.29,.22,.06),(.43,.31,.075),(.56,.14,.085),(.70,.29,.07),(.83,.20,.065)):
            cx=int(w*x); bw=int(w*ww); y=int(h*top_y)
            d.rectangle((cx-bw//2,y+55,cx+bw//2,base+20),fill=(8,17,31,255))
            d.polygon([(cx-bw//2-12,y+60),(cx,y),(cx+bw//2+12,y+60)],fill=(8,17,31,255))
            d.rectangle((cx-8,y+85,cx+8,y+115),fill=(220,184,112,170))
        for i in range(6):
            y=int(h*(.53+i*.055))
            d.ellipse((-100,y-32,w+100,y+60),fill=(175,198,220,20))
    elif kind=="chamber_basilisk":
        for x in range(80,w,240):
            d.polygon([(x,120),(x+78,120),(x+120,h*.82),(x-42,h*.82)],fill=(12,30,29,185),outline=(110,142,119,90))
            d.arc((x-50,70,x+130,310),180,360,fill=(150,170,145,95),width=7)
        d.rectangle((0,h*.79,w,h),fill=(3,12,14,255))
        d.rounded_rectangle((w*.30,h*.67,w*.72,h*.88),radius=30,fill=(61,77,65,255),outline=(155,165,126,180),width=7)
        d.arc((w*.35,h*.43,w*.67,h*.82),195,520,fill=(123,145,105,255),width=42)
        d.arc((w*.39,h*.48,w*.63,h*.77),190,510,fill=(35,55,45,255),width=18)
        d.polygon([(w*.58,h*.46),(w*.70,h*.36),(w*.78,h*.43),(w*.72,h*.52),(w*.63,h*.54)],fill=(104,126,91,255),outline=(190,188,135,220))
        d.ellipse((w*.70,h*.415,w*.715,h*.43),fill=(235,190,92,255))
        d.line((w*.705,h*.425,w*.73,h*.445),fill=(15,22,18,255),width=5)
        for x in (w*.23,w*.78):
            d.ellipse((x-22,h*.23,x+22,h*.30),fill=(245,173,78,95))
            d.polygon([(x-32,h*.29),(x+32,h*.29),(x,h*.48)],fill=(245,173,78,22))
    elif kind=="prophecy_archive":
        d.rectangle((0,h*.17,w,h*.86),fill=(9,19,38,170))
        for row,y in enumerate((h*.25,h*.52,h*.78)):
            d.rectangle((w*.08,y,w*.92,y+18),fill=(107,126,153,190))
            for col,x in enumerate(range(int(w*.13),int(w*.90),145)):
                r=27+(row+col)%2*5
                glow=(115,177,232,130) if (row+col)%3 else (231,191,117,145)
                d.ellipse((x-r,y-r*2.5,x+r,y+r*.1),fill=(95,140,190,55),outline=(185,215,245,210),width=4)
                d.ellipse((x-r*.45,y-r*1.95,x+r*.45,y-r*1.05),fill=glow)
                d.arc((x-r,y-r*2.5,x+r,y+r*.1),205,330,fill=(235,245,255,210),width=3)
        cx,cy,r=int(w*.5),int(h*.48),105
        d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(91,143,205,80),outline=(216,234,255,245),width=9)
        d.ellipse((cx-r*.55,cy-r*.62,cx-r*.05,cy-r*.12),fill=(240,249,255,130))
        d.ellipse((cx-r*.35,cy-r*.35,cx+r*.35,cy+r*.35),outline=(154,202,245,145),width=4)
    elif kind=="azkaban_dementors":
        sea=int(h*.70)
        d.rectangle((0,sea,w,h),fill=(7,17,27,255))
        for y in range(sea+20,h,35):
            d.line((0,y,w,y+((y//35)%2)*3),fill=(130,158,176,28),width=2)
        d.polygon([(w*.25,sea),(w*.34,h*.57),(w*.42,h*.54),(w*.50,h*.60),(w*.60,h*.53),(w*.73,sea),(w*.84,h),(w*.15,h)],fill=(14,24,34,255))
        d.rectangle((w*.43,h*.25,w*.60,sea),fill=(5,12,21,255))
        d.polygon([(w*.40,h*.28),(w*.515,h*.12),(w*.63,h*.28)],fill=(5,12,21,255))
        for x in (w*.46,w*.50,w*.54,w*.58): d.rectangle((x,h*.37,x+13,h*.47),fill=(112,143,159,120))
        for i in range(7):
            y=int(h*(.48+i*.065))
            d.ellipse((-w*.15,y-38,w*1.1,y+80),fill=(167,187,203,24))
        for x,y,s in ((w*.20,h*.40,1.0),(w*.78,h*.36,.82),(w*.68,h*.53,.65)):
            d.ellipse((x-30*s,y-78*s,x+30*s,y-18*s),fill=(2,7,14,240))
            d.polygon([(x-28*s,y-28*s),(x+28*s,y-28*s),(x+55*s,y+105*s),(x+5*s,y+70*s),(x-50*s,y+115*s)],fill=(2,7,14,238))
        d.ellipse((w*.78,h*.12,w*.88,h*.22),fill=(185,205,219,70))
    for i in range(65):
        x=(i*197+73)%w; y=(i*113+41)%h
        d.ellipse((x,y,x+2,y+2),fill=(220,230,240,20+(i%4)*8))
    return _save(im.convert("RGB"))
