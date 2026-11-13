import io
import unittest

try:
    from PIL import Image
    from ppt_semantic_visuals import fantasy_visual_kind, render_fantasy_visual
    HAS_PIL = True
except ImportError:
    Image = None
    fantasy_visual_kind = None
    render_fantasy_visual = None
    HAS_PIL = False


@unittest.skipUnless(HAS_PIL, "Pillow is installed in the dedicated semantic visual workflow")
class FantasyVisualTests(unittest.TestCase):
    def test_known_subjects_are_classified(self):
        cases = [
            ("Harry Potter olami mo'jizalari", "O'lim tuhfalari", "deathly_hallows"),
            ("Harry Potter olami", "Azkaban va dementorlar", "azkaban_dementors"),
            ("Harry Potter olami", "Sirli xona va Basilisk", "chamber_basilisk"),
            ("Harry Potter olami", "Bashoratlar zali", "prophecy_archive"),
            ("Harry Potter olami", "Xogvarts qasri", "hogwarts_castle"),
        ]
        for topic, title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(fantasy_visual_kind(topic, title), expected)

    def test_unrelated_slide_is_not_forced_into_fantasy_scene(self):
        self.assertIsNone(fantasy_visual_kind("Logistika", "Ombor boshqaruvi", "Zaxira nazorati"))

    def test_every_scene_renders_valid_wide_image(self):
        kinds = ("deathly_hallows", "hogwarts_castle", "chamber_basilisk",
                 "prophecy_archive", "azkaban_dementors")
        for kind in kinds:
            with self.subTest(kind=kind):
                raw = render_fantasy_visual(kind)
                self.assertGreater(len(raw), 10_000)
                with Image.open(io.BytesIO(raw)) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (1600, 900))
                    self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
