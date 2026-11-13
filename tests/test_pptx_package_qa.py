import io
import unittest

from pptx import Presentation
from pptx.util import Inches

from pptx_package_qa import PPTXPackageError, inspect_pptx_bytes


def sample_deck():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    box.text_frame.text = "QA test title"
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


class PPTXPackageQATests(unittest.TestCase):
    def test_valid_deck(self):
        report = inspect_pptx_bytes(sample_deck(), expected_slides=1)
        self.assertTrue(report["valid"])
        self.assertEqual(report["slides"], 1)

    def test_rejects_invalid_bytes(self):
        with self.assertRaises(PPTXPackageError):
            inspect_pptx_bytes(b"not a pptx")

    def test_rejects_wrong_slide_count(self):
        with self.assertRaises(PPTXPackageError):
            inspect_pptx_bytes(sample_deck(), expected_slides=2)


if __name__ == "__main__":
    unittest.main()
