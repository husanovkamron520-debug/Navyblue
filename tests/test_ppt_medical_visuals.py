import io
import unittest

from PIL import Image

from ppt_medical_visuals import (
    cardiovascular_topic,
    cardiovascular_visual_kind,
    render_cardiovascular_visual,
)


class CardiovascularVisualTests(unittest.TestCase):
    def test_topic_detection_is_specific(self):
        self.assertTrue(cardiovascular_topic("Yurak qon tomir tizimi"))
        self.assertTrue(cardiovascular_topic("Cardiovascular system"))
        self.assertFalse(cardiovascular_topic("Harry Potter olami"))
        self.assertFalse(cardiovascular_topic("Logistika boshqaruvi"))

    def test_scene_selection(self):
        cases = [
            ("Yurak qon tomir tizimi", "Yurak kameralarining tuzilishi", "bo'lmacha va qorincha", "chambers"),
            ("Yurak qon tomir tizimi", "Arteriya va vena", "tomir devori", "vessels"),
            ("Yurak qon tomir tizimi", "Katta qon aylanish doirasi", "", "circulation"),
            ("Yurak qon tomir tizimi", "Elektrokardiogramma", "EKG ritmi", "ecg"),
            ("Yurak qon tomir tizimi", "Qon tarkibi", "eritrotsit va trombotsit", "blood"),
            ("Yurak qon tomir tizimi", "Profilaktika", "sog'lom turmush", "health"),
        ]
        for topic, title, body, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(cardiovascular_visual_kind(topic, title, body), expected)

    def test_all_visuals_are_valid_16_9_pngs(self):
        for kind in ("heart", "circulation", "vessels", "chambers", "valves", "ecg", "blood", "health"):
            with self.subTest(kind=kind):
                raw = render_cardiovascular_visual(kind)
                with Image.open(io.BytesIO(raw)) as im:
                    self.assertEqual(im.size, (1600, 900))
                    self.assertEqual(im.format, "PNG")
                    self.assertEqual(im.mode, "RGB")
                    self.assertGreater(len(raw), 10000)


if __name__ == "__main__":
    unittest.main()
