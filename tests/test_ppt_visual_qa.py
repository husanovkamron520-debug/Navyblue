import unittest

from ppt_visual_qa import package_qa_blockers, visual_integrity_issues


class VisualIntegrityTests(unittest.TestCase):
    def test_image_layout_without_image_is_reported(self):
        slides = [{"layout": "image_text", "_img": None}]
        issues = visual_integrity_issues(slides, {"image_text", "collage"}, lambda value: isinstance(value, bytes))
        self.assertEqual(issues[0]["reason"], "missing_or_invalid_image")

    def test_collage_requires_three_valid_images(self):
        slides = [{"layout": "collage", "_imgs": [b"a", None, b"b"]}]
        issues = visual_integrity_issues(slides, {"image_text", "collage"}, lambda value: isinstance(value, bytes))
        self.assertEqual(issues[0]["valid_images"], 2)

    def test_valid_image_slots_pass(self):
        slides = [{"layout": "image_text", "_img": b"png"}, {"layout": "collage", "_imgs": [b"a", b"b", b"c"]}]
        self.assertEqual(visual_integrity_issues(slides, {"image_text", "collage"}, lambda value: isinstance(value, bytes)), [])

    def test_empty_serialized_slides_block_delivery(self):
        self.assertEqual(package_qa_blockers({"empty_slides": ["ppt/slides/slide4.xml"]}), ["ppt/slides/slide4.xml"])
        self.assertEqual(package_qa_blockers({"empty_slides": [], "warnings": ["text fit"]}), [])


if __name__ == "__main__":
    unittest.main()
