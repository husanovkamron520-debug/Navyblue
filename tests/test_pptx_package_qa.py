import io
import unittest

try:
    from pptx import Presentation
    from pptx.util import Inches
    from pptx.enum.shapes import MSO_SHAPE
    from PIL import Image
    from pptx_package_qa import PPTXPackageError, inspect_pptx_bytes
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False
    Presentation = None
    Inches = None
    MSO_SHAPE = None
    Image = None
    PPTXPackageError = ValueError
    inspect_pptx_bytes = None


def sample_deck(text="QA test title"):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    box.text_frame.text = text
    prs.slides.add_slide(prs.slide_layouts[6])
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


@unittest.skipUnless(HAS_PPTX, "python-pptx is installed in the dedicated PPTX QA workflow")
class PPTXPackageQATests(unittest.TestCase):
    def test_valid_deck(self):
        report = inspect_pptx_bytes(sample_deck(), expected_slides=2)
        self.assertTrue(report["valid"])
        self.assertEqual(report["slides"], 2)
        self.assertEqual(len(report["empty_slides"]), 1)

    def test_full_bleed_background_does_not_count_as_content_photo(self):
        prs = Presentation()
        background_slide = prs.slides.add_slide(prs.slide_layouts[6])
        content_slide = prs.slides.add_slide(prs.slide_layouts[6])
        image_bytes = io.BytesIO()
        Image.new("RGB", (320, 180), "navy").save(image_bytes, format="PNG")
        raw = image_bytes.getvalue()
        background_slide.shapes.add_picture(
            io.BytesIO(raw), 0, 0, prs.slide_width, prs.slide_height
        )
        content_slide.shapes.add_picture(
            io.BytesIO(raw), Inches(1), Inches(1), Inches(3), Inches(2)
        )
        out = io.BytesIO()
        prs.save(out)
        report = inspect_pptx_bytes(out.getvalue(), expected_slides=2)
        self.assertEqual(report["image_slides"], 1)
        self.assertEqual(report["image_coverage_ratio"], 0.5)
        self.assertEqual(len(report["slides_without_images"]), 1)

    def test_intentional_bleed_decorations_are_not_bounds_errors(self):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        prs.slides.add_slide(prs.slide_layouts[6])
        title = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        title.text_frame.text = "Bounds test"
        decoration = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(-1), Inches(1), Inches(2), Inches(2)
        )
        decoration.name = "!!orb_1"
        bad_content = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(-1), Inches(4), Inches(2), Inches(1)
        )
        bad_content.name = "content_bad"
        out = io.BytesIO()
        prs.save(out)
        report = inspect_pptx_bytes(out.getvalue(), expected_slides=2)
        self.assertEqual(
            [item["shape"] for item in report["out_of_bounds_shapes"]],
            ["content_bad"],
        )

    def test_reports_ellipsis_truncation(self):
        report = inspect_pptx_bytes(
            sample_deck("Ushbu tarixiy jarayon mamlakatning siyosiy tuzilishiga..."),
            expected_slides=2,
        )
        self.assertTrue(any(x["reason"] == "ellipsis" for x in report["truncated_text_blocks"]))
        self.assertTrue(any("tugallanmagan jumla" in x for x in report["warnings"]))

    def test_reports_dangling_uzbek_connector(self):
        report = inspect_pptx_bytes(
            sample_deck("Bu tizim iqtisodiy va siyosiy jarayonlar bilan"),
            expected_slides=2,
        )
        self.assertTrue(any(x["reason"] == "dangling_connector" for x in report["truncated_text_blocks"]))

    def test_does_not_flag_complete_sentence(self):
        report = inspect_pptx_bytes(
            sample_deck("Bu tizim mamlakat taraqqiyotiga sezilarli ta'sir ko'rsatdi."),
            expected_slides=2,
        )
        self.assertEqual(report["truncated_text_blocks"], [])

    def test_reports_likely_text_box_overflow(self):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(0.25))
        paragraph = box.text_frame.paragraphs[0]
        run = paragraph.add_run()
        run.text = "Juda uzun matn " * 18
        from pptx.util import Pt
        run.font.size = Pt(36)
        prs.slides.add_slide(prs.slide_layouts[6])
        out = io.BytesIO()
        prs.save(out)
        report = inspect_pptx_bytes(out.getvalue(), expected_slides=2)
        self.assertTrue(report["text_fit_warnings"])
        self.assertTrue(any("matn qutisida" in warning for warning in report["warnings"]))

    def test_detects_morph_inside_alternate_content(self):
        from pptx.oxml import parse_xml
        prs = Presentation(io.BytesIO(sample_deck()))
        prs.slides[1]._element.append(parse_xml("<mc:AlternateContent xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\" xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"><mc:Choice xmlns:p159=\"http://schemas.microsoft.com/office/powerpoint/2015/09/main\" Requires=\"p159\"><p:transition spd=\"med\"><p159:morph option=\"byObject\"/></p:transition></mc:Choice><mc:Fallback><p:transition><p:fade/></p:transition></mc:Fallback></mc:AlternateContent>"))
        out = io.BytesIO()
        prs.save(out)
        report = inspect_pptx_bytes(out.getvalue(), expected_slides=2)
        self.assertEqual(report["morph_slides"], 1)

    def test_rejects_invalid_bytes(self):
        with self.assertRaises(PPTXPackageError):
            inspect_pptx_bytes(b"not a pptx")

    def test_rejects_wrong_slide_count(self):
        with self.assertRaises(PPTXPackageError):
            inspect_pptx_bytes(sample_deck(), expected_slides=3)


if __name__ == "__main__":
    unittest.main()
