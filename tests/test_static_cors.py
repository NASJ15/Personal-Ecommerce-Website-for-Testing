"""Static file serving, path-traversal safety, CORS, unknown routes."""

from .base import ServerTestCase


class TestStaticFiles(ServerTestCase):

    def test_index_served_at_root(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"ShopLocal", body)

    def test_css_served(self):
        status, headers, _body = self.request("GET", "/style.css")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/css"))

    def test_js_served(self):
        status, headers, body = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertTrue("javascript" in headers["Content-Type"])
        self.assertTrue(body)

    def test_missing_file_404(self):
        status, _headers, _body = self.request("GET", "/does-not-exist.html")
        self.assertEqual(status, 404)

    def test_path_traversal_blocked(self):
        # raw socket: path is NOT normalized client-side
        status_line, body = self.raw_request("GET /../app.py HTTP/1.0")
        self.assertIn(" 404 ", status_line)
        self.assertNotIn(b"ThreadingHTTPServer", body)  # no app source leaked

        status_line, _body = self.raw_request("GET /..%2f..%2fapp.py HTTP/1.0")
        self.assertIn(" 404 ", status_line)

    def test_traversal_to_etc_passwd(self):
        status_line, body = self.raw_request("GET /../data/products.json HTTP/1.0")
        # ../data resolves outside STATIC_DIR -> 404 (not the JSON itself)
        self.assertIn(" 404 ", status_line)
        self.assertNotIn(b"image_emoji", body)


class TestCorsAndRoutes(ServerTestCase):

    def test_options_preflight(self):
        status, headers, _body = self.request("OPTIONS", "/api/cart")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("POST", headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("Content-Type", headers.get("Access-Control-Allow-Headers", ""))

    def test_json_responses_carry_cors_header(self):
        _status, headers, _body = self.request("GET", "/api/products")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_unknown_api_get_falls_to_static_404(self):
        status, _headers, _body = self.request("GET", "/api/definitely-not-real")
        self.assertEqual(status, 404)

    def test_unknown_api_post_404(self):
        status, body = self.api("POST", "/api/nope", {"x": 1})
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_unknown_api_delete_404(self):
        status, _body = self.api("DELETE", "/api/nope")
        self.assertEqual(status, 404)
