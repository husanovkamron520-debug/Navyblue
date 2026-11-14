import unittest

from ppt_content_critic import critique_content


class ContentCriticTests(unittest.TestCase):
    def test_detects_thin_content(self):
        result = critique_content("Biology", [{"title": "Cell structure", "text": "Cells are basic."}])
        self.assertIn("thin_content", {x["code"] for x in result["issues"]})
        self.assertFalse(result["passed"])

    def test_detects_duplicate_slides(self):
        slides = [
            {"title": "Supply chain stages", "text": "The supply chain includes sourcing, production, storage, transport and delivery to the final customer."},
            {"title": "Supply chain stages", "text": "The supply chain includes sourcing, production, storage, transport and delivery to the final customer."},
        ]
        codes = {x["code"] for x in critique_content("Logistics", slides)["issues"]}
        self.assertIn("repeated_title", codes)
        self.assertIn("repeated_content", codes)

    def test_short_agenda_is_not_misclassified_as_thin(self):
        result = critique_content("Project overview", [{
            "layout": "agenda",
            "title": "Presentation roadmap",
            "items": ["Context", "Challenges", "Options", "Conclusion"],
        }])
        self.assertNotIn("thin_content", {issue["code"] for issue in result["issues"]})

    def test_structured_matrix_content_is_not_misclassified_as_thin(self):
        result = critique_content("Decision matrix", [{
            "layout": "matrix",
            "title": "Four decision dimensions",
            "quadrants": [
                {"head": "Cost", "text": "Initial and ongoing financial burden"},
                {"head": "Risk", "text": "Operational and compliance exposure"},
                {"head": "Speed", "text": "Time required to implement"},
                {"head": "Impact", "text": "Long-term effect on service quality"},
            ],
        }])
        self.assertNotIn("thin_content", {issue["code"] for issue in result["issues"]})

    def test_chart_and_comparison_nested_fields_are_counted(self):
        result = critique_content("Operations analysis", [{
            "layout": "compare",
            "title": "Two operating models",
            "left": {"head": "Centralized", "items": ["Lower unit cost", "Consistent controls", "Longer response time"]},
            "right": {"head": "Distributed", "items": ["Local flexibility", "Faster response", "Higher coordination cost"]},
            "chart": {"data": [{"label": "Cost", "value": 42}, {"label": "Speed", "value": 68}]},
        }])
        self.assertNotIn("thin_content", {issue["code"] for issue in result["issues"]})

    def test_warns_about_unsourced_metrics(self):
        result = critique_content("State budget", [
            {"title": "Budget share", "text": "The budget share is 42% of the total amount in this example."}
        ])
        self.assertIn("unverified_metric", {x["code"] for x in result["issues"]})

    def test_recognizes_fictional_kpi_drift(self):
        result = critique_content("Harry Potter magical world", [
            {"title": "Character impact", "text": "The hero has a loyalty KPI score and a ranking index."}
        ])
        self.assertIn("genre_metric_drift", {x["code"] for x in result["issues"]})

    def test_does_not_mutate_slide_content(self):
        slide = {"title": "Mechanism", "text": "A sufficiently detailed explanation with more than eight words is preserved exactly."}
        original = dict(slide)
        critique_content("Science", [slide])
        self.assertEqual(slide, original)


if __name__ == "__main__":
    unittest.main()
