import unittest

from ppt_visual_director import (
    apply_visual_direction,
    build_visual_direction_guidance,
    build_visual_manifest,
    critique_visual_manifest,
)


class UniversalVisualDirectorTests(unittest.TestCase):
    def test_visual_guidance_is_domain_aware_without_forcing_one_layout(self):
        guidance = build_visual_direction_guidance("Usmonli imperiyasi tarixi", 10)
        self.assertIn("historical_chronicle", guidance)
        self.assertIn("bir xil rasm yoki diagramma qolipini qo'llama", guidance)
        self.assertIn("soxta raqam", guidance)

    def test_manifest_assigns_different_visual_types_from_slide_meaning(self):
        slides = [
            {"title": "Imperiya hududining kengayishi", "text": "Hududlar va chegaralar xaritasi", "layout": "map"},
            {"title": "Sulolalar xronologiyasi", "text": "XVI asrdan XIX asrgacha davrlar", "layout": "timeline"},
            {"title": "Harbiy tuzilma", "text": "Qo'shinning bosqichma-bosqich tashkil etilishi", "layout": "chain"},
            {"title": "Me'moriy meros", "text": "Masjid va saroylar", "layout": "image_text"},
        ]
        manifest = build_visual_manifest("Usmonli imperiyasi", slides)
        self.assertEqual(
            [x["visual_type"] for x in manifest["slides"]],
            ["map", "timeline", "process", "place_illustration"],
        )
        self.assertTrue(slides[0]["map_query"])
        self.assertIn("visual_focus", slides[3]["design"])

    def test_visual_plan_does_not_overwrite_existing_photo_query_or_layout(self):
        slides = [{"title": "Yurak anatomiyasi", "text": "Yurak tuzilishi",
                   "layout": "image_text", "photo_query": "human heart anatomy"}]
        manifest = build_visual_manifest("Yurak-qon tomir tizimi", slides)
        self.assertEqual(slides[0]["layout"], "image_text")
        self.assertEqual(slides[0]["photo_query"], "human heart anatomy")
        self.assertEqual(manifest["slides"][0]["visual_type"], "scientific_illustration")

    def test_manifest_critic_flags_repetitive_visual_strategy(self):
        slides = [{"title": f"Topic {i}", "text": "A general explanation", "layout": "image_text"}
                  for i in range(6)]
        manifest = build_visual_manifest("Umumiy mavzu", slides)
        warnings = critique_visual_manifest(manifest)
        self.assertTrue(any(x["code"] == "visual_type_overuse" for x in warnings))

    def test_apply_returns_manifest_and_warnings_without_losing_slides(self):
        slides = [{"title": "Supply chain", "text": "Process flow", "layout": "chain"}]
        manifest, warnings = apply_visual_direction("Logistika", slides)
        self.assertEqual(manifest["slide_count"], 1)
        self.assertEqual(len(slides), 1)
        self.assertIsInstance(warnings, list)


if __name__ == "__main__":
    unittest.main()
