import unittest, zipfile, io, json
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
    def test_vite_zip_contains_buildable_scaffold(self):
        html = "<!doctype html><html><head></head><body><h1>Hello</h1></body></html>"
        archive = zipfile.ZipFile(io.BytesIO(engine.create_vite_zip(html, "My Room!")))
        self.assertEqual(set(archive.namelist()), {"index.html", "package.json", "vite.config.js", "README.md", ".gitignore"})
        package = json.loads(archive.read("package.json"))
        self.assertIn("build", package["scripts"])
        self.assertIn("vite", package["devDependencies"])
        self.assertIn("dist", archive.read("README.md").decode())
    def test_rejects_incomplete_html(self):
        with self.assertRaises(ValueError):
            engine.create_vite_zip("<html>broken", "broken")

if __name__ == "__main__":
    unittest.main()
