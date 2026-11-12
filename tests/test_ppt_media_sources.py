import unittest

from ppt_media_sources import _allowed_license, _metadata_value


class WikimediaLicenseTests(unittest.TestCase):
    def test_allows_public_domain_and_cc0(self):
        for license_name in ("Public domain", "Public Domain Mark", "CC0", "CC0 1.0"):
            with self.subTest(license_name=license_name):
                self.assertTrue(_allowed_license(license_name))

    def test_allows_attribution_licenses(self):
        for license_name in ("CC BY 4.0", "CC BY-SA 4.0", "CC BY 2.0"):
            with self.subTest(license_name=license_name):
                self.assertTrue(_allowed_license(license_name))

    def test_rejects_restrictive_or_missing_licenses(self):
        for license_name in ("CC BY-NC 4.0", "CC BY-ND 4.0", "All rights reserved", ""):
            with self.subTest(license_name=license_name):
                self.assertFalse(_allowed_license(license_name))

    def test_metadata_html_is_cleaned(self):
        value = _metadata_value({"Artist": {"value": "<a href='https://example.com'>Jane &amp; Co</a>" }}, "Artist")
        self.assertEqual(value, "Jane & Co")


if __name__ == "__main__":
    unittest.main()
