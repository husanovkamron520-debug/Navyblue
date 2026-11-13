import unittest
from ppt_template_library import choose_design_reference, build_template_guidance

class TemplateLibraryTests(unittest.TestCase):
    def test_selects_topic_appropriate_reference(self):
        catalog = [
            {"slug": "business", "title": "Business Strategy", "tags": ["Business", "Strategy"], "pptx_url": "https://cdn.ppttemplate.ai/a.pptx"},
            {"slug": "academic", "title": "Academic Thesis", "tags": ["Academic", "Research"], "pptx_url": "https://cdn.ppttemplate.ai/b.pptx"},
        ]
        selected = choose_design_reference("Supply chain", "process_system", catalog)
        self.assertEqual(selected["slug"], "business")
        self.assertEqual(selected["license"], "CC BY 4.0")
        self.assertEqual(selected["use"], "design_reference_only")

    def test_guidance_does_not_claim_morph_without_inspection(self):
        item = {"title": "Academic Theme"}
        guidance = build_template_guidance("Research", "research_evidence", item, {"has_morph": False})
        self.assertIn("no verified Morph", guidance)
        self.assertIn("CC BY 4.0", guidance)

if __name__ == "__main__":
    unittest.main()
