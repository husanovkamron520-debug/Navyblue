import ast
import re
import unittest
from pathlib import Path


class ClassicSanitizerRegressionTests(unittest.TestCase):
    def test_image_text_layout_keeps_photo_query_without_undefined_names(self):
        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        function = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "_sanitize_outline_classic"
        )
        isolated = ast.Module(body=[function], type_ignores=[])
        namespace = {
            "_ppt_s": lambda value, limit: str(value or "").strip()[:limit],
            "_ppt_img_budget": lambda count: 20,
            "PPT_MAX_SLIDES": 30,
            "PPT_LAYOUTS": {"image_text", "text_image", "banner_cards", "hero", "split", "image_story"},
            "re": re,
        }
        exec(compile(isolated, "bot.py", "exec"), namespace)
        result = namespace["_sanitize_outline_classic"](
            {
                "title": "Warehouse automation",
                "slides": [{
                    "layout": "image_text",
                    "title": "Robots in the warehouse",
                    "text": "Autonomous mobile robots move inventory between storage and picking zones.",
                    "photo_query": "warehouse workers forklift",
                }],
            },
            "Warehouse automation",
            1,
            True,
        )
        self.assertEqual(len(result["slides"]), 1)
        self.assertEqual(result["slides"][0]["photo_query"], "warehouse workers forklift")
        self.assertEqual(result["slides"][0]["layout"], "image_text")

    def test_classic_sanitizer_does_not_exceed_requested_content_count(self):
        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        function = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "_sanitize_outline_classic"
        )
        isolated = ast.Module(body=[function], type_ignores=[])
        namespace = {
            "_ppt_s": lambda value, limit: str(value or "").strip()[:limit],
            "_ppt_img_budget": lambda count: 20,
            "PPT_MAX_SLIDES": 30,
            "PPT_LAYOUTS": {"text", "image_text", "text_image", "banner_cards", "hero", "split", "image_story"},
            "re": re,
        }
        exec(compile(isolated, "bot.py", "exec"), namespace)
        slides = [
            {"layout": "text", "title": f"Section {index}", "text": "This is enough explanatory content for a valid slide."}
            for index in range(1, 5)
        ]
        result = namespace["_sanitize_outline_classic"](
            {"title": "Test deck", "slides": slides},
            "Test deck",
            2,
            False,
        )
        self.assertEqual(len(result["slides"]), 2)


if __name__ == "__main__":
    unittest.main()
