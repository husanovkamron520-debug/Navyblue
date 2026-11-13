import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from ppt_render_qa import build_contact_sheets, inspect_rendered_images, render_and_inspect_pptx


class RenderedSlideQATests(unittest.TestCase):
    def test_detects_visually_blank_slide(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "blank.png"
            Image.new("RGB", (1280, 720), "white").save(path)
            report = inspect_rendered_images([path])
            self.assertEqual(report["status"], "rendered")
            self.assertIn("visually_blank_slide", {x["code"] for x in report["blockers"]})

    def test_detects_duplicate_rendered_slides(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for name in ("one.png", "two.png"):
                image = Image.new("RGB", (1280, 720), "white")
                draw = ImageDraw.Draw(image)
                draw.rectangle((100, 100, 900, 600), fill="navy")
                draw.text((140, 150), "Same slide", fill="white")
                path = Path(temp) / name
                image.save(path)
                paths.append(path)
            report = inspect_rendered_images(paths)
            self.assertIn("duplicate_rendered_slide", {x["code"] for x in report["warnings"]})

    def test_nonblank_slide_passes_blankness_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "content.png"
            image = Image.new("RGB", (1280, 720), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((50, 50, 800, 670), fill="navy")
            draw.text((100, 100), "Visible content", fill="white")
            image.save(path)
            report = inspect_rendered_images([path])
            self.assertEqual(report["blockers"], [])
            self.assertTrue(report["passed"])

    def test_contact_sheet_has_slide_labels_and_chunk_ranges(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for index in range(3):
                path = Path(temp) / f"slide-{index + 1}.png"
                image = Image.new("RGB", (640, 360), "white")
                draw = ImageDraw.Draw(image)
                draw.rectangle((20, 20, 400, 300), fill=(index * 50, 40, 100))
                image.save(path)
                paths.append(path)
            sheets = build_contact_sheets(paths, slides_per_sheet=2, columns=2)
            self.assertEqual(len(sheets), 2)
            self.assertEqual((sheets[0]["start_slide"], sheets[0]["end_slide"]), (1, 2))
            self.assertEqual((sheets[1]["start_slide"], sheets[1]["end_slide"]), (3, 3))
            self.assertTrue(sheets[0]["png"].startswith(b"\\x89PNG"))

    def test_empty_pptx_input_is_reported(self):
        report = render_and_inspect_pptx(b"")
        self.assertEqual(report["status"], "error")
        self.assertIn("empty_pptx_input", {x["code"] for x in report["warnings"]})

    def test_missing_renderer_is_an_explicit_skip(self):
        report = render_and_inspect_pptx(b"not-a-real-pptx")
        self.assertIn(report["status"], {"skipped", "error", "rendered"})


if __name__ == "__main__":
    unittest.main()
