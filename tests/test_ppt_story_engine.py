import unittest

from ppt_story_engine import build_story_guidance, classify_archetype


class FantasyStoryArchitectureTests(unittest.TestCase):
    def test_harry_potter_is_classified_as_fantasy(self):
        self.assertEqual(classify_archetype("Harry Potter olamidagi sehrli mavjudotlar"), "fantasy_fiction")

    def test_uzbek_fantasy_terms_are_classified(self):
        self.assertEqual(classify_archetype("Afsonaviy ajdarholar va gippogriflar"), "fantasy_fiction")

    def test_fantasy_guidance_blocks_unrequested_scientific_drift(self):
        guidance = build_story_guidance("Harry Potter olamidagi sehrli mavjudotlar", 8)
        self.assertIn("JANRGA SODIQLIK", guidance)
        self.assertIn("real biologiya, ekologiya, iqtisod", guidance)
        self.assertIn("mavjudotlar", guidance)

    def test_regular_logistics_topic_keeps_process_archetype(self):
        self.assertEqual(classify_archetype("Ta'minot zanjiri logistikasi"), "process_system")


if __name__ == "__main__":
    unittest.main()
