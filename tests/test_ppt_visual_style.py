import unittest

from ppt_visual_style import build_photorealistic_query, is_nonphotographic_metadata
from ppt_visual_director import classify_visual_domain


class PhotographicStyleTests(unittest.TestCase):
    def test_medical_queries_are_scene_specific_and_realistic(self):
        query = build_photorealistic_query("medical", "Yurak va qon tomir", "Qon tarkibi", "Eritrotsitlar kislorod tashiydi")
        self.assertIn("3D medical render", query)
        self.assertIn("red blood cells", query)

    def test_remus_patronus_uses_cinematic_photo_language(self):
        query = build_photorealistic_query("fiction", "Remus Lupin", "Patronus: Umid timsoli")
        self.assertIn("cinematic photorealistic", query)
        self.assertIn("silver spectral wolf", query)

    def test_non_photographic_results_are_rejected(self):
        self.assertTrue(is_nonphotographic_metadata("cartoon vector illustration"))
        self.assertTrue(is_nonphotographic_metadata("anime character portrait"))
        self.assertTrue(is_nonphotographic_metadata("Ottoman historical miniature painting"))
        self.assertFalse(is_nonphotographic_metadata("photorealistic 3D medical render"))

    def test_generic_query_has_photographic_style(self):
        query = build_photorealistic_query("logistics", "Warehouse automation", "Robotic picking")
        self.assertIn("photorealistic editorial photograph", query)

    def test_generic_queries_keep_topic_when_slide_title_is_generic(self):
        query = build_photorealistic_query("history", "Ottoman Empire", "Conclusion")
        self.assertIn("Ottoman Empire", query)
        self.assertIn("Conclusion", query)
        self.assertIn("photorealistic editorial photograph", query)

    def test_biology_does_not_fall_back_to_heart_visuals(self):
        query = build_photorealistic_query("science", "Biology", "Cell structure")
        self.assertIn("biological cell", query)
        self.assertNotIn("human heart", query)

    def test_medical_and_fiction_fallbacks_keep_the_topic(self):
        medical = build_photorealistic_query("medical", "Diabetes", "Insulin regulation")
        fiction = build_photorealistic_query("fiction", "The Lord of the Rings", "The Shire")
        self.assertIn("Diabetes", medical)
        self.assertIn("Insulin regulation", medical)
        self.assertIn("The Lord of the Rings", fiction)
        self.assertIn("The Shire", fiction)

    def test_non_special_subjects_all_get_photo_first_queries(self):
        topics = [
            ("history", "Ottoman Empire", "Architecture of Istanbul"),
            ("finance", "State budget", "Public expenditure"),
            ("logistics", "Supply chain", "Warehouse operations"),
        ]
        for domain, topic, title in topics:
            with self.subTest(domain=domain):
                query = build_photorealistic_query(domain, topic, title)
                self.assertIn("photorealistic editorial photograph", query)
                self.assertIn(topic, query)
                self.assertIn(title, query)

    def test_general_health_topics_use_medical_visual_domain(self):
        for topic in ("Diabetes", "Cancer treatment", "Hospital surgery", "Qon kasalliklari"):
            with self.subTest(topic=topic):
                self.assertEqual(classify_visual_domain(topic), "medical")


if __name__ == "__main__":
    unittest.main()
