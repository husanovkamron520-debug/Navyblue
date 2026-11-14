import io
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation
from pptx.oxml import parse_xml
from pptx.util import Inches
from ppt_template_library import inspect_pptx
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
        self.assertTrue(selected["license_verified_from_source_license"])

    def test_selects_medical_reference_from_category_tags(self):
        catalog = [
            {"slug": "general", "title": "Clean General Slides", "tags": ["General Purpose"], "pptx_url": "https://cdn.ppttemplate.ai/a.pptx"},
            {"slug": "clinical", "title": "Clinical Anatomy Education", "tags": ["Medical & Health", "Biology"], "pptx_url": "https://cdn.ppttemplate.ai/b.pptx"},
        ]
        selected = choose_design_reference("Cardiovascular anatomy", "medical_education", catalog)
        self.assertEqual(selected["slug"], "clinical")
        self.assertEqual(selected["use"], "design_reference_only")

    def test_template_choice_is_stable_for_same_topic(self):
        catalog = [
            {"slug": "blue", "title": "Blue Business Strategy", "tags": ["Business"], "pptx_url": "https://cdn.ppttemplate.ai/a.pptx"},
            {"slug": "green", "title": "Green Business Strategy", "tags": ["Business"], "pptx_url": "https://cdn.ppttemplate.ai/b.pptx"},
        ]
        first = choose_design_reference("Supply chain", "process_system", catalog)
        second = choose_design_reference("Supply chain", "process_system", catalog)
        self.assertEqual(first["slug"], second["slug"])

    def test_inspects_morph_transition_inside_alternate_content(self):
        xml = "<mc:AlternateContent xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\" xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"><mc:Choice xmlns:p159=\"http://schemas.microsoft.com/office/powerpoint/2015/09/main\" Requires=\"p159\"><p:transition spd=\"med\"><p159:morph option=\"byObject\"/></p:transition></mc:Choice><mc:Fallback><p:transition><p:fade/></p:transition></mc:Fallback></mc:AlternateContent>"
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text_frame.text = "Morph test"
        slide._element.append(parse_xml(xml))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "morph-reference.pptx"
            prs.save(path)
            report = inspect_pptx(path)
        self.assertTrue(report["has_morph"])
        self.assertEqual(report["morph_slide_count"], 1)

    def test_guidance_does_not_claim_morph_without_inspection(self):
        item = {"title": "Academic Theme"}
        guidance = build_template_guidance("Research", "research_evidence", item, {"has_morph": False})
        self.assertIn("no verified Morph", guidance)
        self.assertIn("CC BY 4.0", guidance)

if __name__ == "__main__":
    unittest.main()
