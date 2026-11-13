import io
import unittest

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Pillow is installed in the dedicated PPTX QA workflow")
class RemusLupinVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ppt_remus_lupin_visuals import (
            remus_lupin_topic, remus_lupin_visual_kind,
            render_remus_lupin_visual, sanitize_remus_lupin_slide,
            apply_remus_lupin_visual_coverage,
        )
        cls.remus_lupin_topic = staticmethod(remus_lupin_topic)
        cls.remus_lupin_visual_kind = staticmethod(remus_lupin_visual_kind)
        cls.render_remus_lupin_visual = staticmethod(render_remus_lupin_visual)
        cls.sanitize_remus_lupin_slide = staticmethod(sanitize_remus_lupin_slide)
        cls.apply_remus_lupin_visual_coverage = staticmethod(apply_remus_lupin_visual_coverage)
    def test_topic_detection(self):
        self.assertTrue(remus_lupin_topic("Remus Lupin: O'tmish soyasidagi jasorat"))
        self.assertTrue(remus_lupin_topic("Professor Lupin"))
        self.assertFalse(remus_lupin_topic("Usmonli imperiyasi"))

    def test_visual_kind_selection(self):
        self.assertEqual(remus_lupin_visual_kind("Remus Lupin", "Feniks ordenidagi hissasi"), "order_phoenix")
        self.assertEqual(remus_lupin_visual_kind("Remus Lupin", "To'lin oy va bo'ri odam"), "werewolf")
        self.assertEqual(remus_lupin_visual_kind("Remus Lupin", "Hogwarts professori"), "professor")

    def test_each_visual_is_valid_png(self):
        for kind in ("portrait","werewolf","professor","marauders","order_phoenix","patronus","full_moon"):
            raw = render_remus_lupin_visual(kind)
            with Image.open(io.BytesIO(raw)) as im:
                self.assertEqual(im.format, "PNG")
                self.assertEqual(im.size, (1600, 900))

    def test_fabricated_metrics_removed(self):
        slide = {"layout":"stats","title":"Feniks ordenidagi hissasi",
                 "stats":[{"label":"Fidoyilik darajasi","value":"100%"}]}
        self.assertTrue(sanitize_remus_lupin_slide(slide))
        self.assertEqual(slide["layout"], "editorial")
        self.assertNotIn("stats", slide)
        self.assertNotIn("100%", slide["text"])


    def test_visual_coverage_promotes_text_only_slides(self):
        slides = [
            {"layout":"plain_text","title":"Remusning bolaligi","text":"U yoshligidan likantropiya bilan yashagan."},
            {"layout":"stats","title":"Feniks ordenidagi hissasi",
             "stats":[{"label":"Fidoyilik","value":"100%"}]},
            {"layout":"references","title":"Manbalar","text":"Kitoblar"},
        ]
        changed = apply_remus_lupin_visual_coverage(slides)
        self.assertEqual(changed, 2)
        self.assertEqual(slides[0]["layout"], "image_text")
        self.assertEqual(slides[1]["layout"], "image_text")
        self.assertEqual(slides[2]["layout"], "references")
        self.assertNotIn("100%", slides[1]["text"])

    def test_normal_narrative_preserved(self):
        slide = {"layout":"editorial","title":"Hayoti","text":"U Hogwartsda dars bergan."}
        self.assertFalse(sanitize_remus_lupin_slide(slide))
        self.assertEqual(slide["text"], "U Hogwartsda dars bergan.")


if __name__ == "__main__":
    unittest.main()
