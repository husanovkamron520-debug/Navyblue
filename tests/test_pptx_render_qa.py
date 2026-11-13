import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from pptx_render_qa import analyze_rendered_slides, _average_hash, _hamming_distance


class RenderedSlideQATests(unittest.TestCase):
    def test_valid_nonblank_png_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slide.png"
            image = Image.new("RGB", (1280, 720), "white")
            ImageDraw.Draw(image).rectangle((100, 100, 700, 600), fill="#245A91")
            image.save(path)
            report = analyze_rendered_slides([path])
            self.assertTrue(report["passed"])
            self.assertEqual(report["valid_png_count"], 1)
            self.assertEqual(report["issues"], [])

    def test_near_blank_slide_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.png"
            Image.new("RGB", (1280, 720), "white").save(path)
            report = analyze_rendered_slides([path])
            self.assertFalse(report["passed"])
            self.assertEqual(report["issues"][0]["code"], "near_blank_slide")

    def test_low_resolution_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "small.png"
            image = Image.new("RGB", (320, 180), "white")
            ImageDraw.Draw(image).rectangle((20, 20, 180, 150), fill="navy")
            image.save(path)
            report = analyze_rendered_slides([path])
            self.assertFalse(report["passed"])
            self.assertIn("low_resolution", [item["code"] for item in report["issues"]])

    def test_average_hash_distance(self):
        image = Image.new("RGB", (64, 64), "white")
        self.assertEqual(_hamming_distance(_average_hash(image), _average_hash(image)), 0)

    def test_repeated_pages_are_reported_as_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index in range(2):
                path = Path(directory) / f"slide-{index}.png"
                image = Image.new("RGB", (1280, 720), "white")
                ImageDraw.Draw(image).rectangle((100, 100, 700, 600), fill="#245A91")
                image.save(path)
                paths.append(path)
            report = analyze_rendered_slides(paths)
            self.assertTrue(report["passed"])
            self.assertEqual(len(report["duplicate_slide_pairs"]), 1)
            self.assertTrue(report["warnings"])


if __name__ == "__main__":
    unittest.main()
