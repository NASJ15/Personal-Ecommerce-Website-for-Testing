"""Health check + product catalog endpoints."""

from .base import ServerTestCase

EXPECTED_CATEGORIES = {
    "Accessories", "Audio", "Displays", "Peripherals",
    "Smart Home", "Storage", "Wearables",
}
REQUIRED_FIELDS = {
    "id", "name", "description", "category", "price",
    "currency", "stock", "image_emoji",
}


class TestHealth(ServerTestCase):

    def test_health(self):
        status, body = self.api("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertIn("time", body)

    def test_health_is_json(self):
        _status, headers, _body = self.request("GET", "/api/health")
        self.assertTrue(headers.get("Content-Type", "").startswith("application/json"))


class TestCatalog(ServerTestCase):

    def _all_products(self):
        status, body = self.api("GET", "/api/products")
        self.assertEqual(status, 200)
        return body

    def test_products_list(self):
        body = self._all_products()
        self.assertEqual(body["count"], 10)
        self.assertEqual(len(body["products"]), 10)
        for p in body["products"]:
            self.assertTrue(REQUIRED_FIELDS <= set(p), f"missing fields in {p}")
            self.assertIsInstance(p["id"], int)
            self.assertGreater(p["price"], 0)
            self.assertGreaterEqual(p["stock"], 0)

    def test_product_ids_unique(self):
        ids = [p["id"] for p in self._all_products()["products"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_category_filter_case_insensitive(self):
        _status, audio = self.api("GET", "/api/products?category=AUDIO")
        self.assertEqual(audio["count"], 2)
        self.assertTrue(all(p["category"].lower() == "audio" for p in audio["products"]))
        self.assertEqual(
            {p["id"] for p in audio["products"]}, {1, 6})

    def test_category_filter_no_match(self):
        status, body = self.api("GET", "/api/products?category=frobnicators")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["products"], [])

    def test_single_product(self):
        status, p = self.api("GET", "/api/products/1")
        self.assertEqual(status, 200)
        self.assertEqual(p["name"], "Aurora Wireless Headphones")
        self.assertEqual(p["price"], 129.99)
        self.assertEqual(p["category"], "Audio")

    def test_single_product_not_found(self):
        status, body = self.api("GET", "/api/products/999")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_single_product_invalid_id(self):
        status, _body = self.api("GET", "/api/products/not-a-number")
        self.assertEqual(status, 404)

    def test_categories_sorted(self):
        status, body = self.api("GET", "/api/categories")
        self.assertEqual(status, 200)
        self.assertEqual(body["categories"], sorted(EXPECTED_CATEGORIES))
