import unittest

from ppt_asset_manifest import build_asset_manifest


class AssetManifestTests(unittest.TestCase):
    def test_records_original_and_retrieved_assets(self):
        slides = [
            {"title": "Original diagram", "_img": b"diagram",
             "_asset": {"source_type": "original", "provider": "Navyblue", "visual_kind": "diagram"}},
            {"title": "Retrieved image", "_img": b"photo",
             "_asset": {"source_type": "retrieved", "provider": "Wikimedia Commons",
                        "credit": "Creator; CC BY 4.0; source page", "license_status": "verified"}},
        ]
        report = build_asset_manifest(slides)
        self.assertEqual(report["asset_count"], 2)
        self.assertEqual(report["source_counts"]["original"], 1)
        self.assertEqual(report["source_counts"]["retrieved"], 1)
        self.assertEqual(report["issue_count"], 0)

    def test_detects_unattributed_assets(self):
        report = build_asset_manifest([{"title": "Unknown", "_img": b"image"}])
        self.assertIn("missing_asset_provenance", {x["code"] for x in report["issues"]})

    def test_detects_reused_image_across_slides(self):
        shared = b"same image bytes"
        slides = [
            {"title": "First", "_img": shared, "_asset": {"source_type": "original", "provider": "Navyblue"}},
            {"title": "Second", "_img": shared, "_asset": {"source_type": "original", "provider": "Navyblue"}},
        ]
        report = build_asset_manifest(slides)
        self.assertIn("duplicate_asset", {x["code"] for x in report["issues"]})

    def test_duplicate_asset_inside_same_collage_is_high_severity(self):
        repeated = b"same collage image"
        report = build_asset_manifest([{
            "title": "Repeated collage",
            "_imgs": [repeated, repeated],
            "_assets": [
                {"source_type": "retrieved", "provider": "Openverse", "credit": "Creator one"},
                {"source_type": "retrieved", "provider": "Openverse", "credit": "Creator one"},
            ],
        }])
        duplicates = [issue for issue in report["issues"] if issue["code"] == "duplicate_asset"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["severity"], "high")
        self.assertFalse(report["passed"])

    def test_tracks_collage_asset_metadata(self):
        slides = [{
            "title": "Collage",
            "_imgs": [b"one", b"two"],
            "_assets": [
                {"source_type": "retrieved", "provider": "Openverse", "credit": "Author one"},
                {"source_type": "retrieved", "provider": "Wikimedia Commons", "credit": "Author two"},
            ],
        }]
        report = build_asset_manifest(slides)
        self.assertEqual(report["asset_count"], 2)
        self.assertEqual(report["slide_count_with_assets"], 1)


if __name__ == "__main__":
    unittest.main()
