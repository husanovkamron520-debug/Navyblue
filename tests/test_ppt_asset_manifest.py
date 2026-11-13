import unittest

from ppt_asset_manifest import build_asset_manifest


class AssetManifestTests(unittest.TestCase):
    def test_records_generated_asset_provenance(self):
        slides = [{
            "title": "Heart anatomy",
            "_img": b"generated-heart-illustration",
            "_asset": {"source_type": "original_generated", "generator": "Navyblue", "visual_kind": "heart"},
        }]
        report = build_asset_manifest(slides)
        self.assertEqual(report["asset_count"], 1)
        self.assertEqual(report["source_counts"]["original_generated"], 1)
        self.assertEqual(report["issues"], [])

    def test_detects_unattributed_assets(self):
        report = build_asset_manifest([{"title": "Slide", "_img": b"image-bytes"}])
        self.assertIn("missing_asset_provenance", {x["code"] for x in report["issues"]})

    def test_detects_duplicate_assets_across_slides(self):
        raw = b"same-stock-image"
        slides = [
            {"title": "First", "_img": raw, "_asset": {"source_type": "retrieved", "provider": "Pixabay"}},
            {"title": "Second", "_img": raw, "_asset": {"source_type": "retrieved", "provider": "Pixabay"}},
        ]
        report = build_asset_manifest(slides)
        self.assertIn("duplicate_asset", {x["code"] for x in report["issues"]})

    def test_records_multiple_collage_assets(self):
        slides = [{
            "title": "Collage",
            "_imgs": [b"image-one", b"image-two", b"image-three"],
            "_assets": [
                {"source_type": "retrieved", "provider": "Openverse"},
                {"source_type": "retrieved", "provider": "Pixabay"},
                {"source_type": "retrieved", "provider": "Wikimedia Commons"},
            ],
        }]
        report = build_asset_manifest(slides)
        self.assertEqual(report["asset_count"], 3)
        self.assertEqual(report["slide_count_with_assets"], 1)
        self.assertEqual(report["issues"], [])


if __name__ == "__main__":
    unittest.main()
