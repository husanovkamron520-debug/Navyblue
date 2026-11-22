import unittest
import october_creative as builder

class CreativeTemplateTests(unittest.TestCase):
    def test_selects_relevant_starters(self):
        self.assertEqual(builder._template_engine.select_template("3D sayyoralar va galaktika")[0], "cosmos_3d")
        self.assertEqual(builder._template_engine.select_template("3D xona, divan va stol")[0], "room_3d")
        self.assertEqual(builder._template_engine.select_template("3D ombor va stellaj")[0], "warehouse_3d")
        self.assertEqual(builder._template_engine.select_template("birthday photo gallery")[0], "birthday_gallery")
        self.assertEqual(builder._template_engine.select_template("logistics dashboard chart")[0], "dashboard")
    def test_general_fallback(self):
        self.assertEqual(builder._template_engine.select_template("Oddiy sahifa")[0], "general")
    def test_template_prompt_has_quality_direction(self):
        self.assertIn("Majburiy sifat mezonlari", builder._template_engine.template_prompt("3D xona yarat"))
    def test_no_vite_packaging_or_flags(self):
        self.assertFalse(any("vite" in str(item).lower() for item in builder._template_engine.TEMPLATES.values()))
        self.assertFalse(hasattr(builder._template_engine, "create_vite_zip"))
    def test_cdn_typo_is_repaired(self):
        html = '<html><head><script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.5net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.5net/npm/three@0.160.0/examples/jsm/"}}</script></head><body></body></html>'
        fixed = builder._repair(html)
        self.assertIn("https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js", fixed)
        self.assertIn("https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/", fixed)
        self.assertNotIn("jsdelivr.5net", fixed)

if __name__ == "__main__":
    unittest.main()
