import unittest

import project_builder as builder


class ProjectBuilderTests(unittest.TestCase):
    def test_routes_complex_projects_to_staged_generation(self):
        self.assertTrue(builder.should_use_modular("Menga logistika uchun interaktiv dashboard yarat"))
        self.assertTrue(builder.should_use_modular("3D sayyoralar va galaktika yarat"))
        self.assertTrue(builder.should_use_modular("Ta'lim platformasi yarat"))
        self.assertFalse(builder.should_use_modular("Oddiy salom sahifasi"))

    def test_existing_project_edits_stay_on_legacy_path(self):
        self.assertFalse(builder.should_use_modular("Dashboardga yangi filter qo'sh", existing="<!doctype html>"))

    def test_assembles_one_portable_html_document(self):
        doc = builder.assemble_document(".app{display:grid}", "<main id='app'>Hello</main>", "console.log('ok')", three=False)
        self.assertTrue(doc.startswith("<!DOCTYPE html>"))
        self.assertIn("<style>", doc)
        self.assertIn("<main id='app'>", doc)
        self.assertIn("<script>", doc)
        self.assertTrue(doc.endswith("</html>"))

    def test_three_mode_adds_importmap_and_module_script(self):
        doc = builder.assemble_document("", "<main></main>", "import * as THREE from 'three';", three=True)
        self.assertIn('type="importmap"', doc)
        self.assertIn('type="module"', doc)
        self.assertIn("cdn.jsdelivr.net/npm/three@0.160.0", doc)

    def test_room_template_contains_archviz_acceptance_requirements(self):
        import creative_template_engine as templates
        prompt = templates.template_prompt("3D xona interyer penthouse divan")
        for requirement in ("L-shaped", "RoundedBoxGeometry", "RoomEnvironment",
                            "PMREMGenerator", "2048x2048", "Daylight",
                            "Night Neon / Evening Cozy", "Sofa view",
                            "TV / desk", "Top-down plan", "vertical wood slats",
                            "woven", "glass coffee table"):
            self.assertIn(requirement.casefold(), prompt.casefold())

    def test_cosmos_template_contains_deep_space_acceptance_requirements(self):
        import creative_template_engine as templates
        prompt = templates.template_prompt("Cinematic 3D kosmos yarat")
        for requirement in ("400–600", "dampingFactor 0.04", "UnrealBloomPass",
                            "Fresnel", "panorama", "no visible HUD"):
            self.assertIn(requirement.casefold(), prompt.casefold())
        self.assertNotIn("scientific HUD values", prompt.casefold())
        self.assertNotIn("temperature", prompt.casefold())
        self.assertNotIn("gravity", prompt.casefold())
        self.assertIn("no visible hud", prompt.casefold())
        self.assertIn("no visible hud, labels, text, tooltips, legends, object descriptions", prompt.casefold())


class ModularGenerationAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_generates_plan_css_body_and_javascript(self):
        def fake_generate(prompt):
            if "BOSQICH 1/4" in prompt:
                return "Reja: KPI, jadval, filter, qidiruv, mobil menyu va interaktiv grafik."
            if "BOSQICH 2/4" in prompt:
                return ".app{display:grid;gap:1rem}" + builder._MARKERS["css"]
            if "BOSQICH 3/4" in prompt:
                return "<main class='app'><button id='refresh'>Yangilash</button></main>" + builder._MARKERS["html"]
            if "BOSQICH 4/4" in prompt:
                return "document.getElementById('refresh').addEventListener('click',()=>{});" + builder._MARKERS["js"]
            raise AssertionError("Unexpected generation stage")

        doc = await builder.generate_modular(fake_generate, "Logistika dashboard yarat", "Kontekst")
        self.assertIsNotNone(doc)
        self.assertIn(".app{display:grid;gap:1rem}", doc)
        self.assertIn("id='refresh'", doc)
        self.assertIn("addEventListener", doc)

    async def test_room_generation_uses_archviz_specific_js_prompt(self):
        prompts = []
        def fake_generate(prompt):
            prompts.append(prompt)
            if "BOSQICH 1/4" in prompt:
                return "Reja: L-shaped xona, divan, yoritish rejimlari va kamera presetlari."
            if "BOSQICH 2/4" in prompt:
                return ".room{display:block}" + builder._MARKERS["css"]
            if "BOSQICH 3/4" in prompt:
                return "<main id='room'><canvas id='scene'></canvas></main>" + builder._MARKERS["html"]
            if "BOSQICH 4/4" in prompt:
                return "const scene = new THREE.Scene();" + builder._MARKERS["js"]
            raise AssertionError("Unexpected generation stage")

        doc = await builder.generate_modular(
            fake_generate,
            "3D xona interyer penthouse yarat: modulli divan, gilam, shisha stol, LED, Daylight va Night Neon",
            "ArchViz konteksti"
        )
        self.assertIsNotNone(doc)
        js_prompt = prompts[-1]
        for requirement in ("RoundedBoxGeometry", "RoomEnvironment", "PMREMGenerator",
                            "PCFSoftShadowMap", "2048x2048", "Daylight",
                            "Night Neon / Evening Cozy", "Sofa view", "TV / desk",
                            "Top-down plan"):
            self.assertIn(requirement.casefold(), js_prompt.casefold())
        self.assertNotIn("glassmorphism HUD", js_prompt.casefold())

    async def test_continues_a_truncated_fragment(self):
        calls = {"count": 0}
        marker = builder._MARKERS["css"]

        def fake_generate(prompt):
            calls["count"] += 1
            if calls["count"] == 1:
                return ".card{color:"
            anchor = ".card{color:"
            return anchor + "white}" + marker

        result = await builder._complete_fragment(fake_generate, "CSS", "css")
        self.assertEqual(result, ".card{color:white}")
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
