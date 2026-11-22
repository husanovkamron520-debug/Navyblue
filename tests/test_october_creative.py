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

    def test_3d_quality_check_requires_real_scene_loop_and_camera(self):
        good = """<!DOCTYPE html><html><head><script type="module">
        import * as THREE from 'three.module.js';
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
        const renderer = new THREE.WebGLRenderer();
        renderer.setSize(600, 400);
        document.body.appendChild(renderer.domElement);
        const controls = { enableDamping: true };
        window.addEventListener('resize', () => {});
        scene.add(new THREE.AmbientLight(0xffffff));
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 32), new THREE.MeshStandardMaterial());
        const mesh2 = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial());
        const mesh3 = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial());
        const mesh4 = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial());
        const mesh5 = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial());
        scene.add(mesh); scene.add(mesh2); scene.add(mesh3); scene.add(mesh4); scene.add(mesh5);
        function animate() { requestAnimationFrame(animate); renderer.render(scene, camera); }
        animate();
        </script></head><body></body></html>"""
        self.assertIsNone(builder._check(good, "3D xona yarat", []))
        fake = good.replace("requestAnimationFrame(animate);", "")
        self.assertIn("animatsiya", builder._check(fake, "3D xona yarat", []))
        self.assertIsNotNone(builder._check(
            "<!DOCTYPE html><html><body>2D canvas</body></html>", "3D xona yarat", []))

    def test_planet_request_requires_multiple_spheres(self):
        plain = """<!DOCTYPE html><html><head><script type="module">
        import * as THREE from 'three.module.js';
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera();
        const renderer = new THREE.WebGLRenderer(); renderer.setSize(10,10);
        document.body.appendChild(renderer.domElement);
        scene.add(new THREE.AmbientLight());
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial());
        scene.add(mesh);
        function animate(){ requestAnimationFrame(animate); renderer.render(scene,camera); }
        animate();
        </script></head><body></body></html>"""
        self.assertIn("ikkita alohida sfera", builder._check(plain, "3D sayyoralar yarat", []))

    def test_image_must_be_rendered_not_left_as_upload_widget(self):
        doc = "<!DOCTYPE html><html><body><input type='file'><img src='__OCTOBER_IMAGE_0__'></body></html>"
        self.assertIn("yuklash paneli", builder._check(doc, "HTML rasm", [{"data": b"x"}]))
        good = "<!DOCTYPE html><html><body><img src='__OCTOBER_IMAGE_0__'></body></html>"
        self.assertIsNone(builder._check(good, "HTML rasm", [{"data": b"x"}]))

    def test_room_and_warehouse_requests_require_threejs(self):
        plain = "<!DOCTYPE html><html><body>2D canvas</body></html>"
        self.assertIn("Three.js", builder._check(plain, "xona yarat", []))
        self.assertIn("Three.js", builder._check(plain, "ombor yarat", []))

    def test_editing_a_non_3d_page_does_not_force_threejs(self):
        plain = "<!DOCTYPE html><html><body><h1>Portfolio</h1></body></html>"
        self.assertIsNone(builder._check(plain, "rangini ko'k qil", [], existing=plain))

    def test_uploaded_image_token_must_be_present(self):
        doc = "<!DOCTYPE html><html><body><img src='__OCTOBER_IMAGE_0__'></body></html>"
        self.assertIsNone(builder._check(doc, "HTML rasm", [{"data": b"x"}]))
        self.assertIn("rasm", builder._check(
            "<!DOCTYPE html><html><body></body></html>", "HTML rasm", [{"data": b"x"}]))


if __name__ == "__main__":
    unittest.main()
