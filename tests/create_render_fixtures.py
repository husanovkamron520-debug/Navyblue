"""Create deterministic, original six-domain PPTX fixtures for renderer CI."""
from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "render-fixtures")
OUT.mkdir(parents=True, exist_ok=True)

DOMAINS = {
    "medicine": ("Yurak-qon tomir tizimi", "Qon aylanishi: yurakdan to'qimagacha",
                 ["Yurak", "Arteriya", "Kapillyar", "Vena"],
                 ["Nasos vazifasi", "Qonni olib boradi", "Modda almashinuvi", "Qonni qaytaradi"]),
    "history": ("Usmonli imperiyasi", "Davlat taraqqiyotining muhim bosqichlari",
                ["1299", "1453", "1520", "1922"],
                ["Davlat tashkil topdi", "Konstantinopol olindi", "Klassik davr", "Sultonlik tugadi"]),
    "biology": ("Biologik klonlash", "Somatik hujayra yadrosini ko'chirish",
                ["Donor hujayra", "Yadro", "Tuxum hujayra", "Embrion"],
                ["Somatik hujayra olinadi", "Yadro ajratiladi", "Yadrosiz hujayraga o'tkaziladi", "Rivojlanish kuzatiladi"]),
    "fiction": ("Fantastik olam qurilishi", "Qahramon, muhit va sabab-oqibat",
                ["Qahramon", "Maqsad", "To'siq", "O'zgarish"],
                ["Boshlang'ich holat", "Ichki motiv", "Konflikt", "Yakuniy qaror"]),
    "economics": ("Davlat byudjeti", "Daromad va xarajatlar muvozanati",
                  ["Soliqlar", "Bojxona", "Ta'lim", "Infratuzilma"],
                  ["Asosiy tushum", "Tashqi savdo tushumi", "Ijtimoiy xarajat", "Kapital xarajat"]),
    "logistics": ("Ta'minot zanjiri", "Mahsulot oqimining boshqarilishi",
                  ["Ta'minotchi", "Ombor", "Transport", "Mijoz"],
                  ["Xomashyo", "Zaxira va saqlash", "Yetkazib berish", "Talabni qondirish"]),
}


def add_text(slide, x, y, w, h, value, size=22, color=(25, 42, 66), bold=False):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.word_wrap = True
    frame.margin_left = Inches(0.08)
    frame.margin_right = Inches(0.08)
    frame.margin_top = Inches(0.04)
    frame.margin_bottom = Inches(0.04)
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.LEFT
    run = paragraph.add_run()
    run.text = value
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(*color)
    return shape


def add_header(slide, title, subtitle):
    add_text(slide, 0.65, 0.35, 12.0, 0.55, title, 28, (22, 49, 82), True)
    add_text(slide, 0.7, 1.0, 11.8, 0.45, subtitle, 15, (95, 110, 128))


for slug, (title, subtitle, labels, descriptions) in DOMAINS.items():
    deck = Presentation()
    deck.slide_width = Inches(13.333)
    deck.slide_height = Inches(7.5)

    # 1. Cover with a distinct visual anchor.
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(239, 244, 250)
    accent_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.28), Inches(7.5))
    accent_bar.fill.solid()
    accent_bar.fill.fore_color.rgb = RGBColor(36, 90, 145)
    add_text(slide, 0.9, 2.0, 10.8, 1.1, title, 34, (22, 49, 82), True)
    add_text(slide, 0.95, 3.2, 10.5, 0.8, subtitle, 20, (95, 110, 128))
    cover_mark = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(10.9), Inches(4.8), Inches(1.15), Inches(1.15))
    cover_mark.fill.solid()
    cover_mark.fill.fore_color.rgb = RGBColor(36, 90, 145)

    # 2. Four-step process, deliberately varied across subject families.
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    add_header(slide, "Jarayon xaritasi", subtitle)
    for index, (label, description) in enumerate(zip(labels, descriptions)):
        x = 0.75 + index * 3.15
        y = 2.25 + (0.35 if index % 2 else 0)
        block = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(2.55), Inches(2.05))
        block.fill.solid()
        block.fill.fore_color.rgb = RGBColor(36 + index * 15, 90 + index * 8, 145 - index * 12)
        block.line.color.rgb = RGBColor(255, 255, 255)
        tf = block.text_frame
        tf.text = f"{index + 1:02d}\n{label}\n{description}"
        for paragraph in tf.paragraphs:
            paragraph.alignment = PP_ALIGN.CENTER
            for run in paragraph.runs:
                run.font.size = Pt(15 if index else 17)
                run.font.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
        if index < 3:
            slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, Inches(x + 2.58), Inches(y + 1.0),
                Inches(x + 3.05), Inches(y + 1.0),
            ).line.color.rgb = RGBColor(190, 150, 80)

    # 3. Evidence / comparison layout with a chart-like native shape treatment.
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    add_header(slide, "Asosiy tarkibiy qismlar", "Har bir elementning vazifasi va o'zaro bog'liqligi")
    for index, (label, description) in enumerate(zip(labels, descriptions)):
        y = 2.0 + index * 1.05
        add_text(slide, 0.9, y, 2.6, 0.45, label, 19, (36, 90, 145), True)
        add_text(slide, 3.65, y, 7.8, 0.5, description, 17, (55, 65, 78))
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(3.65), Inches(y + 0.55), Inches(1.1 + index * 0.62), Inches(0.12))
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(36, 90, 145)
        bar.line.fill.background()

    # 4. Summary with a different hierarchy and a visual marker.
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(22, 49, 82)
    add_text(slide, 0.9, 1.25, 11.3, 0.9, "Asosiy xulosa", 32, (255, 255, 255), True)
    add_text(slide, 0.95, 2.45, 9.7, 1.5, f"{title}: mavzuni tizimli tushunish uchun sabab, jarayon va natijani birgalikda ko'rish kerak.", 22, (235, 241, 248))
    summary_mark = slide.shapes.add_shape(MSO_SHAPE.DIAMOND, Inches(10.7), Inches(4.3), Inches(1.1), Inches(1.1))
    summary_mark.fill.solid()
    summary_mark.fill.fore_color.rgb = RGBColor(190, 150, 80)

    deck.save(OUT / f"{slug}.pptx")

# One 20-slide stress deck checks that the renderer handles a full-length presentation.
stress = Presentation()
stress.slide_width = Inches(13.333)
stress.slide_height = Inches(7.5)
for index in range(20):
    slide = stress.slides.add_slide(stress.slide_layouts[6])
    family = index % 5
    title = f"20-slide stress test — {index + 1:02d}"
    subtitle = f"Unique content block {index + 1}; layout family {family + 1}"
    add_header(slide, title, subtitle)
    if family == 0:
        add_text(slide, 0.9, 2.2, 4.0, 1.6, f"{(index + 1) * 7}%", 46, (36, 90, 145), True)
        add_text(slide, 5.1, 2.25, 6.8, 1.3,
                 f"Stress-test metric {index + 1} has a distinct explanation and supporting context.",
                 22, (55, 65, 78))
    elif family == 1:
        for card_index in range(3):
            x = 0.9 + card_index * 4.05
            card = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(2.25), Inches(3.35), Inches(2.35)
            )
            card.fill.solid()
            card.fill.fore_color.rgb = RGBColor(36 + card_index * 35, 90 + index * 3, 145 - card_index * 20)
            card.text_frame.text = f"Card {card_index + 1}\nSlide {index + 1}\nUnique detail {index * 3 + card_index + 1}"
            for paragraph in card.text_frame.paragraphs:
                paragraph.alignment = PP_ALIGN.CENTER
                for run in paragraph.runs:
                    run.font.size = Pt(18)
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(255, 255, 255)
    elif family == 2:
        for row in range(4):
            y = 2.0 + row * 0.95
            add_text(slide, 0.9, y, 2.4, 0.42, f"Factor {index + row + 1}", 17, (36, 90, 145), True)
            bar = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(3.5), Inches(y + 0.05),
                Inches(1.4 + ((index + row) % 5) * 0.72), Inches(0.22)
            )
            bar.fill.solid()
            bar.fill.fore_color.rgb = RGBColor(36, 90, 145)
            bar.line.fill.background()
    elif family == 3:
        connector_y = 3.35
        slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Inches(1.25), Inches(connector_y),
            Inches(11.9), Inches(connector_y)
        ).line.color.rgb = RGBColor(190, 150, 80)
        for step in range(4):
            x = 1.1 + step * 3.45
            marker_shape = slide.shapes.add_shape(
                MSO_SHAPE.OVAL, Inches(x), Inches(2.95), Inches(0.8), Inches(0.8)
            )
            marker_shape.fill.solid()
            marker_shape.fill.fore_color.rgb = RGBColor(36, 90, 145)
            add_text(slide, x - 0.2, 4.0, 1.8, 0.65, f"Stage {step + 1}\nItem {index + step + 1}",
                     14, (55, 65, 78), True)
    else:
        add_text(slide, 1.0, 2.1, 4.8, 0.55, f"Option A — {index + 1}", 22, (36, 90, 145), True)
        add_text(slide, 7.0, 2.1, 4.8, 0.55, f"Option B — {index + 1}", 22, (190, 120, 40), True)
        add_text(slide, 1.0, 3.0, 4.8, 1.2, f"Distinct comparison evidence for item {index + 1}.", 19)
        add_text(slide, 7.0, 3.0, 4.8, 1.2, f"Alternative evidence and implication for item {index + 1}.", 19)
stress.save(OUT / "stress20.pptx")

print(f"Created {len(DOMAINS)} domain fixtures in {OUT}")
