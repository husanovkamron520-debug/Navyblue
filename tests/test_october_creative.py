import unittest
import creative_template_engine as engine

class CreativeTemplateEngineTests(unittest.TestCase):
    def test_selects_relevant_starters(self):
        self.assertEqual(engine.select_template("3D sayyoralar va galaktika")[0], "cosmos_3d")
        self.assertEqual(engine.select_template("3D xona, divan va stol")[0], "room_3d")
        self.assertEqual(engine.select_template("3D ombor va stellaj")[0], "warehouse_3d")
        self.assertEqual(engine.select_template("birthday photo gallery")[0], "birthday_gallery")
        self.assertEqual(engine.select_template("logistics dashboard chart")[0], "dashboard")
    def test_general_fallback(self):
        self.assertEqual(engine.select_template("Oddiy sahifa")[0], "general")
    def test_prompt_includes_quality_direction(self):
        self.assertIn("Majburiy sifat mezonlari", engine.template_prompt("3D xona yarat"))

if __name__ == "__main__":
    unittest.main()
