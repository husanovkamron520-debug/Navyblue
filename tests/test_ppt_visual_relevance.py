import unittest

from ppt_visual_relevance import contextually_irrelevant, metadata_relevant


class VisualRelevanceTests(unittest.TestCase):
    def test_exact_tokens_prevent_substring_false_positives(self):
        self.assertFalse(metadata_relevant("art", "artificial intelligence image", minimum=1))
        self.assertFalse(metadata_relevant("organ", "ornamental beetle", minimum=1))

    def test_requires_multiple_meaningful_terms_when_available(self):
        self.assertTrue(metadata_relevant("somatic cell nuclear transfer", "somatic cell process", minimum=2))
        self.assertFalse(metadata_relevant("somatic cell nuclear transfer", "somatic illustration", minimum=2))

    def test_known_biology_stock_false_positives_are_rejected(self):
        self.assertTrue(contextually_irrelevant("biological cloning", "Lego Star Wars Stormtrooper toys"))
        self.assertTrue(contextually_irrelevant("artificial organ tissue model", "shiny beetle macro"))
        self.assertFalse(contextually_irrelevant("insect biology beetle", "beetle macro photography"))
        self.assertFalse(contextually_irrelevant("Ottoman architecture history", "toy soldier"))

    def test_non_biology_context_does_not_apply_biology_blacklist(self):
        self.assertFalse(contextually_irrelevant("Lego toy history", "Lego toy brick"))


if __name__ == "__main__":
    unittest.main()
