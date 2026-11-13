import unittest

from ppt_visual_director import (
    apply_visual_plan,
    build_visual_plan,
    classify_visual_domain,
    critique_visual_plan,
    prepare_deck_visuals,
)


class UniversalVisualDirectorTests(unittest.TestCase):
    def test_domains_cover_distinct_subject_families(self):
        self.assertEqual(classify_visual_domain("Yurak-qon tomir tizimi"), "medical")
        self.assertEqual(classify_visual_domain("Usmonli imperiyasi tarixi"), "history")
        self.assertEqual(classify_visual_domain("Harry Potter va sehrli olam"), "fiction")
        self.assertEqual(classify_visual_domain("Klonlash va hujayra"), "science")
        self.assertEqual(classify_visual_domain("Davlat byudjeti"), "finance")
        self.assertEqual(classify_visual_domain("Ta'minot zanjiri logistikasi"), "logistics")

    def test_manifest_has_slide_specific_visual_briefs(self):
        slides = [
            {"layout": "timeline", "title": "Imperiyaning shakllanishi", "story_role": "chronology"},
            {"layout": "map", "title": "Hududiy kengayish", "story_role": "geography"},
            {"layout": "compare", "title": "Harbiy tizimlar taqqoslanishi", "story_role": "comparison"},
        ]
        plan = build_visual_plan("Usmonli imperiyasi", slides)
        self.assertEqual(plan["domain"], "history")
        self.assertEqual(plan["slide_count"], 3)
        self.assertEqual(plan["slides"][0]["visual_type"], "chronology")
        self.assertEqual(plan["slides"][1]["visual_type"], "geographic_map")
        self.assertEqual(plan["slides"][2]["visual_type"], "comparison")
        self.assertTrue(all(x["visual_focus"] and x["search_query"] for x in plan["slides"]))

    def test_apply_adds_metadata_without_changing_content_or_layout(self):
        slides = [{"layout": "text", "title": "Qon aylanish mexanizmi", "text": "Asosiy izoh"}]
        plan = build_visual_plan("Yurak-qon tomir tizimi", slides)
        self.assertEqual(apply_visual_plan(slides, plan), 1)
        self.assertEqual(slides[0]["text"], "Asosiy izoh")
        self.assertEqual(slides[0]["layout"], "text")
        self.assertIn("_visual_plan", slides[0])
        self.assertIn("visual_type", slides[0]["design"])

    def test_consecutive_compositions_are_diversified(self):
        slides = [
            {"layout": "image_text", "title": f"Unique topic {i}", "design": {"composition": "editorial_split"}}
            for i in range(5)
        ]
        plan = build_visual_plan("Science", slides)
        comps = [x["composition"] for x in plan["slides"]]
        self.assertNotEqual(comps[0], comps[1])
        self.assertNotEqual(comps[1], comps[2])

    def test_critic_detects_repeated_visual_focus(self):
        slides = [
            {"layout": "image_text", "title": "Heart anatomy", "visual_focus": "Heart anatomy", "photo_query": "human heart anatomy"},
            {"layout": "image_text", "title": "Heart anatomy", "visual_focus": "Heart anatomy", "photo_query": "human heart anatomy"},
        ]
        result = prepare_deck_visuals("Cardiovascular system", slides)
        codes = {x["code"] for x in result["qa"]["issues"]}
        self.assertIn("repeated_visual_focus", codes)
        self.assertIn("repeated_search_query", codes)


if __name__ == "__main__":
    unittest.main()
