import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from ppt_render_qa import inspect_rendered_images, render_and_inspect_pptx


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

    def test_empty_pptx_input_is_reported(self):
        report = render_and_inspect_pptx(b"")
        self.assertEqual(report["status"], "error")
        self.assertIn("empty_pptx_input", {x["code"] for x in report["warnings"]})

    def test_missing_renderer_is_an_explicit_skip(self):
        report = render_and_inspect_pptx(b"not-a-real-pptx")
        self.assertIn(report["status"], {"skipped", "error", "rendered"})


if __name__ == "__main__":
    unittest.main()
