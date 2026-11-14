import unittest

from ppt_visual_qa import (package_qa_blockers, visual_integrity_issues,
                           is_decorative_shape_name, hard_slide_issues)


class VisualIntegrityTests(unittest.TestCase):
    def test_image_layout_without_image_is_reported(self):
        slides = [{"layout": "image_text", "_img": None}]
        issues = visual_integrity_issues(slides, {"image_text", "collage"}, lambda value: isinstance(value, bytes))
        self.assertEqual(issues[0]["reason"], "missing_or_invalid_image")

    def test_decorative_bleed_names_are_normalized(self):
        self.assertTrue(is_decorative_shape_name("!!deco_1"))
        self.assertTrue(is_decorative_shape_name("!!orb_2"))
        self.assertTrue(is_decorative_shape_name("!!orbit_ring"))
        self.assertFalse(is_decorative_shape_name("content_bad"))

    def test_text_overlap_is_a_hard_slide_issue(self):
        self.assertEqual(
            hard_slide_issues(["matnlar ustma-ust tushdi", "matn va rasm ustma-ust tushdi", "warning"]),
            ["matn va rasm ustma-ust tushdi", "matnlar ustma-ust tushdi"],
        )

    def test_collage_requires_three_valid_images(self):
        slides = [{"layout": "collage", "_imgs": [b"a", None, b"b"]}]
        issues = visual_integrity_issues(slides, {"image_text", "collage"}, lambda value: isinstance(value, bytes))
        self.assertEqual(issues[0]["valid_images"], 2)

    def test_valid_image_slots_pass(self):
        slides = [{"layout": "image_text", "_img": b"png"}, {"layout": "collage", "_imgs": [b"a", b"b", b"c"]}]
        self.assertEqual(visual_integrity_issues(slides, {"image_text", "collage"}, lambda value: isinstance(value, bytes)), [])

    def test_out_of_bounds_shapes_block_delivery(self):
        blockers = package_qa_blockers({
            "out_of_bounds_shapes": [{"slide": "slide7.xml", "shape": "chart"}]
        })
        self.assertEqual(blockers, ["out-of-bounds shape: slide7.xml"])

    def test_empty_serialized_slides_block_delivery(self):
        self.assertEqual(package_qa_blockers({"empty_slides": ["ppt/slides/slide4.xml"]}), ["empty slide: ppt/slides/slide4.xml"])
        self.assertEqual(package_qa_blockers({"empty_slides": [], "warnings": ["text fit"]}), [])
        self.assertEqual(package_qa_blockers({"numeric_truncations": [{"slide": "slide2"}]}), ["numeric truncation: slide2"])
        self.assertEqual(package_qa_blockers({"truncated_text_blocks": [{"slide": "slide3", "reason": "dangling_connector"}]}), ["unfinished sentence: slide3"])
        self.assertEqual(package_qa_blockers({"text_fit_warnings": [{"slide": "slide1", "estimated_height_pt": 100, "available_height_pt": 50}]}), ["severe text overflow: slide1"])
        self.assertEqual(package_qa_blockers({"text_fit_warnings": [{"slide": "slide1", "estimated_height_pt": 60, "available_height_pt": 50}]}), [])


if __name__ == "__main__":
    unittest.main()
