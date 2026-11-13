"""Cart lifecycle: create, add, update, remove, checkout, stock enforcement,
concurrency.

Each test creates its own cart, so tests do not depend on each other's carts.
Stock is shared class-wide, so tests pick distinct products / leave stock
assertions relative.
"""

import threading

from .base import ServerTestCase

# Prices from data/products.json (class server starts fresh, so these hold)
P1 = 129.99   # headphones,  stock 42
P3 = 89.50    # keyboard,   stock 63
P7 = 59.99    # charger,    stock 210
P2_STOCK = 18  # smartwatch stock


class TestCartLifecycle(ServerTestCase):

    def _create_cart(self):
        status, cart = self.api("POST", "/api/cart")
        self.assertEqual(status, 201)
        return cart["cart_id"]

    def _add(self, cart_id, pid, qty):
        return self.api("POST", f"/api/cart/{cart_id}/add",
                        {"product_id": pid, "quantity": qty})

    def test_create_cart(self):
        status, cart = self.api("POST", "/api/cart")
        self.assertEqual(status, 201)
        self.assertRegex(cart["cart_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(cart["item_count"], 0)
        self.assertEqual(cart["items"], [])
        self.assertEqual(cart["total"], 0)
        self.assertEqual(cart["currency"], "USD")
        self.assertIn("created_at", cart)

    def test_get_cart_not_found(self):
        status, body = self.api("GET", "/api/cart/" + "0" * 32)
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_add_item_and_view(self):
        cid = self._create_cart()
        status, cart = self._add(cid, 1, 2)
        self.assertEqual(status, 201)
        self.assertEqual(cart["item_count"], 1)
        item = cart["items"][0]
        self.assertEqual(item["product_id"], 1)
        self.assertEqual(item["unit_price"], P1)
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(item["line_total"], round(P1 * 2, 2))
        self.assertEqual(cart["total"], round(P1 * 2, 2))

        # add a second product -> totals aggregate
        status, cart = self._add(cid, 3, 1)
        self.assertEqual(status, 201)
        self.assertEqual(cart["item_count"], 2)
        self.assertEqual(cart["total"], round(P1 * 2 + P3, 2))

    def test_add_accumulates_quantity(self):
        cid = self._create_cart()
        self._add(cid, 7, 2)
        status, cart = self._add(cid, 7, 3)
        self.assertEqual(status, 201)
        self.assertEqual(cart["item_count"], 1)
        self.assertEqual(cart["items"][0]["quantity"], 5)

    def test_add_validation(self):
        cid = self._create_cart()

        # malformed JSON
        status, body = self.api("POST", f"/api/cart/{cid}/add", "not json{")
        self.assertEqual(status, 400)

        # quantity not an integer
        status, body = self._add(cid, 1, "lots")
        self.assertEqual(status, 400)
        self.assertIn("quantity", body["error"])

        # quantity zero / negative
        self.assertEqual(self._add(cid, 1, 0)[0], 400)
        self.assertEqual(self._add(cid, 1, -3)[0], 400)

        # unknown product
        status, body = self._add(cid, 4242, 1)
        self.assertEqual(status, 404)
        self.assertIn("error", body)

        # unknown cart
        status, _body = self.api("POST", f"/api/cart/{'f' * 32}/add",
                                 {"product_id": 1, "quantity": 1})
        self.assertEqual(status, 404)

    def test_add_out_of_stock_rejected(self):
        cid = self._create_cart()
        # exhaust the smartwatch (stock 18) via a full-stock checkout
        self.assertEqual(self._add(cid, 2, P2_STOCK)[0], 201)
        status, order = self.api("POST", f"/api/cart/{cid}/checkout")
        self.assertEqual(status, 201)
        self.assertEqual(order["items"][0]["quantity"], P2_STOCK)

        # now adding it must fail with 409
        cid2 = self._create_cart()
        status, body = self._add(cid2, 2, 1)
        self.assertEqual(status, 409)
        self.assertIn("stock", body["error"].lower())

        # stock endpoint confirms zero
        _status, p2 = self.api("GET", "/api/products/2")
        self.assertEqual(p2["stock"], 0)

    def test_set_quantity(self):
        cid = self._create_cart()
        self._add(cid, 1, 1)
        status, cart = self.api("POST", f"/api/cart/{cid}/items/1", {"quantity": 4})
        self.assertEqual(status, 200)
        self.assertEqual(cart["items"][0]["quantity"], 4)
        self.assertEqual(cart["total"], round(P1 * 4, 2))

    def test_set_quantity_zero_removes(self):
        cid = self._create_cart()
        self._add(cid, 1, 1)
        self._add(cid, 3, 1)
        status, cart = self.api("POST", f"/api/cart/{cid}/items/1", {"quantity": 0})
        self.assertEqual(status, 200)
        self.assertEqual(cart["item_count"], 1)
        self.assertEqual(cart["items"][0]["product_id"], 3)

    def test_set_quantity_validation(self):
        cid = self._create_cart()
        self._add(cid, 1, 1)
        status, _body = self.api("POST", f"/api/cart/{cid}/items/1", {"quantity": "x"})
        self.assertEqual(status, 400)
        status, _body = self.api("POST", f"/api/cart/{cid}/items/1", "not json{")
        self.assertEqual(status, 400)

    def test_delete_item(self):
        cid = self._create_cart()
        self._add(cid, 1, 1)
        self._add(cid, 3, 1)
        status, cart = self.api("DELETE", f"/api/cart/{cid}/items/1")
        self.assertEqual(status, 200)
        self.assertEqual(cart["item_count"], 1)
        self.assertEqual(cart["items"][0]["product_id"], 3)
        # deleting again is a no-op, not an error
        status, cart = self.api("DELETE", f"/api/cart/{cid}/items/1")
        self.assertEqual(status, 200)
        self.assertEqual(cart["item_count"], 1)

    def test_delete_cart(self):
        cid = self._create_cart()
        status, body = self.api("DELETE", f"/api/cart/{cid}")
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])
        self.assertEqual(body["cart_id"], cid)
        # gone now
        self.assertEqual(self.api("GET", f"/api/cart/{cid}")[0], 404)
        # double delete -> 404
        self.assertEqual(self.api("DELETE", f"/api/cart/{cid}")[0], 404)

    def test_checkout_empty_cart(self):
        cid = self._create_cart()
        status, body = self.api("POST", f"/api/cart/{cid}/checkout")
        self.assertEqual(status, 400)
        self.assertIn("empty", body["error"].lower())

    def test_checkout_success(self):
        cid = self._create_cart()
        before, p1 = self.api("GET", "/api/products/1")
        self.assertEqual(before, 200)
        self._add(cid, 1, 2)
        self._add(cid, 3, 1)

        status, order = self.api("POST", f"/api/cart/{cid}/checkout")
        self.assertEqual(status, 201)
        self.assertRegex(order["order_id"], r"^ORD-[0-9A-F]{10}$")
        self.assertIn("placed_at", order)
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual(
            order["total"], round(P1 * 2 + P3, 2))

        # stock decremented
        _status, p1_after = self.api("GET", "/api/products/1")
        self.assertEqual(p1_after["stock"], p1["stock"] - 2)

        # cart emptied, still exists
        status, cart = self.api("GET", f"/api/cart/{cid}")
        self.assertEqual(status, 200)
        self.assertEqual(cart["item_count"], 0)
        self.assertEqual(cart["total"], 0)

    def test_checkout_insufficient_stock(self):
        cid = self._create_cart()
        self._add(cid, 3, 1)
        self._add(cid, 4, 999)  # stock is only 120

        status, body = self.api("POST", f"/api/cart/{cid}/checkout")
        self.assertEqual(status, 409)
        self.assertIn("stock", body["error"].lower())

        # failed checkout must NOT clear the cart or touch stock
        _status, p4 = self.api("GET", "/api/products/4")
        self.assertEqual(p4["stock"], 120)
        status, cart = self.api("GET", f"/api/cart/{cid}")
        self.assertEqual(status, 200)
        self.assertEqual(cart["item_count"], 2)

    def test_concurrent_adds_do_not_lose_updates(self):
        """ThreadingHTTPServer + LOCK: parallel adds to the same product must
        all land in the cart quantity."""
        cid = self._create_cart()
        n_threads, qty_each = 10, 2
        errors = []

        def worker():
            try:
                status, _cart = self._add(cid, 7, qty_each)
                if status != 201:
                    errors.append(status)
            except Exception as e:  # noqa: BLE001 - report any failure
                errors.append(repr(e))

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        status, cart = self.api("GET", f"/api/cart/{cid}")
        self.assertEqual(status, 200)
        self.assertEqual(cart["items"][0]["quantity"], n_threads * qty_each)
        self.assertEqual(cart["total"], round(P7 * n_threads * qty_each, 2))
