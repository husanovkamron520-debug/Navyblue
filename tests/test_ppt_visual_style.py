import unittest

from ppt_visual_style import build_photorealistic_query, is_nonphotographic_metadata


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
        self.assertFalse(is_nonphotographic_metadata("photorealistic 3D medical render"))

    def test_generic_query_has_photographic_style(self):
        query = build_photorealistic_query("logistics", "Warehouse automation", "Robotic picking")
        self.assertIn("photorealistic editorial photograph", query)

    def test_non_special_subjects_all_get_photo_first_queries(self):
        topics = [
            ("history", "Ottoman Empire", "Architecture of Istanbul"),
            ("finance", "State budget", "Public expenditure"),
            ("logistics", "Supply chain", "Warehouse operations"),
            ("science", "Biology", "Cell structure"),
        ]
        for domain, topic, title in topics:
            with self.subTest(domain=domain):
                query = build_photorealistic_query(domain, topic, title)
                self.assertIn("photorealistic editorial photograph", query)
                self.assertIn(title, query)


if __name__ == "__main__":
    unittest.main()
