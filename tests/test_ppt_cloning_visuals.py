import io
import unittest

from PIL import Image
from ppt_cloning_visuals import cloning_topic, cloning_visual_kind, render_cloning_visual


class CloningVisualTests(unittest.TestCase):
    def test_cloning_topic_detection(self):
        self.assertTrue(cloning_topic("Klonlash: Biologik chegaralar va etika"))
        self.assertTrue(cloning_topic("Biological cloning"))
        self.assertFalse(cloning_topic("Supply chain management"))

    def test_slide_subjects_get_specific_visuals(self):
        topic = "Klonlash: Biologik chegaralar va etika"
        cases = [
            ("Dolly qo'yi va biologik burilish", "Dolly qo'y tajribasi", "dolly"),
            ("Somatik hujayra yadrosini ko'chirish", "Yadro donor hujayradan olinadi", "nuclear_transfer"),
            ("Sun'iy organlar va transplantatsiya", "Organoid va to'qima modellari", "organoid"),
            ("Fenotipik o'xshashlik", "Genotip va tashqi belgilar", "phenotype"),
            ("Klonlash etikasi", "Huquq, xavf va mas'uliyat", "ethics"),
        ]
        for title, body, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(cloning_visual_kind(topic, title, body), expected)

    def test_every_cloning_visual_is_valid_wide_png(self):
        for kind in ("dna", "dolly", "nuclear_transfer", "organoid", "phenotype", "ethics"):
            with self.subTest(kind=kind):
                raw = render_cloning_visual(kind)
                self.assertGreater(len(raw), 5000)
                with Image.open(io.BytesIO(raw)) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (1600, 900))
                    self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
