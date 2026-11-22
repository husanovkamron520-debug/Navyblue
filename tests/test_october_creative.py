import unittest

import october_creative as builder


class CreativeBuilderTests(unittest.TestCase):
    def test_detects_3d_and_site_requests(self):
        self.assertTrue(builder.wants_builder("3D xona yarat"))
        self.assertTrue(builder.wants_builder("Sayyora animatsiyasi"))
        self.assertTrue(builder.wants_builder("interaktiv HTML sahifa"))

    def test_does_not_capture_unrelated_text(self):
        self.assertFalse(builder.wants_builder("Bugun supply chain haqida gaplashamiz"))
        self.assertFalse(builder.wants_builder("Menga yangi reja tuzib ber"))

    def test_extracts_complete_html(self):
        raw = "<!DOCTYPE html><html><head></head><body>" + ("x" * 1100) + "</body></html>"
        self.assertIn("</html>", builder._html(raw))

    def test_3d_quality_check_requires_webgl(self):
        good = ("<!DOCTYPE html><html><head><script type='module'>"
                "import * as THREE from 'three.module.js';"
                "const renderer = new THREE.WebGLRenderer();"
                "</script></head><body></body></html>")
        self.assertIsNone(builder._check(good, "3D sayyora yarat", []))
        self.assertIn("Three.js", builder._check(
            "<!DOCTYPE html><html><body>2D canvas</body></html>", "3D xona yarat", []))

    def test_uploaded_image_token_must_be_present(self):
        doc = "<!DOCTYPE html><html><body><img src='__OCTOBER_IMAGE_0__'></body></html>"
        self.assertIsNone(builder._check(doc, "HTML rasm", [{"data": b"x"}]))
        self.assertIn("rasm", builder._check(
            "<!DOCTYPE html><html><body></body></html>", "HTML rasm", [{"data": b"x"}]))


if __name__ == "__main__":
    unittest.main()
