import ast
import json
import logging
import math
import re
import unittest
from pathlib import Path


class SlideCountGateTests(unittest.TestCase):
    def test_unexpected_recovery_error_cannot_return_short_outline(self):
        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        function = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "_ppt_expand_missing_slides"
        )
        isolated = ast.Module(body=[function], type_ignores=[])
        def fail_guidance(topic, count):
            raise RuntimeError("simulated recovery setup failure")

        namespace = {
            "PPT_MAX_SLIDES": 30,
            "PPT_AI_MODELS": ["model-a"],
            "AI_MODEL_NAME": "model-a",
            "math": math,
            "json": json,
            "re": re,
            "logger": logging.getLogger("slide-count-test"),
            "_ppt_clip": lambda value, limit: str(value or "")[:limit],
            "_ppt_slide_text": lambda item: str(item.get("text") or ""),
            "build_story_guidance": fail_guidance,
        }
        exec(compile(isolated, "bot.py", "exec"), namespace)
        outline = {
            "slides": [{
                "layout": "text",
                "title": "Only generated slide",
                "text": "This is the only slide returned by the first attempt.",
            }]
        }
        with self.assertRaisesRegex(RuntimeError, "Slaydlar soni yetarli emas: 1/2"):
            namespace["_ppt_expand_missing_slides"](
                outline, "Test topic", 2, False, lambda *args: {"slides": []}
            )


if __name__ == "__main__":
    unittest.main()
