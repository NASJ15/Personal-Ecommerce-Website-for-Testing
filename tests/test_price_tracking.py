"""Price-change tracking API.

Every test picks its own product and reads the *before* price first, so the
suite is order-independent even though price history is shared class state.
"""

from .base import ServerTestCase


class TestSetPrice(ServerTestCase):

    def test_set_price_records_change(self):
        _s, before = self.api("GET", "/api/products/1")
        new = round(before["price"] - 30.0, 2)
        status, body = self.api("POST", "/api/products/1/price",
                                {"price": new, "reason": "flash sale"})
        self.assertEqual(status, 200)
        self.assertTrue(body["updated"])
        ch = body["change"]
        self.assertEqual(ch["product_id"], 1)
        self.assertEqual(ch["product_name"], "Aurora Wireless Headphones")
        self.assertEqual(ch["old_price"], before["price"])
        self.assertEqual(ch["new_price"], new)
        self.assertEqual(ch["delta"], round(new - before["price"], 2))
        self.assertEqual(ch["pct_change"],
                         round((new - before["price"]) / before["price"] * 100, 2))
        self.assertEqual(ch["reason"], "flash sale")
        self.assertIn("changed_at", ch)

        # product price actually updated
        _s, p = self.api("GET", "/api/products/1")
        self.assertEqual(p["price"], new)

        # history ends with this change
        _s, hist = self.api("GET", "/api/products/1/price-history")
        self.assertEqual(hist["changes"][-1]["new_price"], new)

    def test_set_price_default_reason(self):
        _s, before = self.api("GET", "/api/products/2")
        new = round(before["price"] - 1, 2)
        status, body = self.api("POST", "/api/products/2/price", {"price": new})
        self.assertEqual(status, 200)
        self.assertEqual(body["change"]["reason"], "manual update")

    def test_set_price_validation(self):
        _s, before = self.api("GET", "/api/products/6")
        for bad in ["cheap", 0, -5, None]:
            status, body = self.api("POST", "/api/products/6/price", {"price": bad})
            self.assertEqual(status, 400, f"price={bad!r} should be rejected")
            self.assertIn("error", body)
        status, body = self.api("POST", "/api/products/6/price", {})
        self.assertEqual(status, 400)
        # malformed JSON
        status, _body = self.api("POST", "/api/products/6/price", "not json{")
        self.assertEqual(status, 400)
        # price untouched
        _s, p = self.api("GET", "/api/products/6")
        self.assertEqual(p["price"], before["price"])

    def test_set_price_unknown_product(self):
        status, body = self.api("POST", "/api/products/4242/price", {"price": 10})
        self.assertEqual(status, 404)
        self.assertIn("error", body)


class TestPriceHistory(ServerTestCase):

    def test_history_single_change(self):
        _s, before = self.api("GET", "/api/products/3")
        new = 80.0
        self.api("POST", "/api/products/3/price", {"price": new})
        status, hist = self.api("GET", "/api/products/3/price-history")
        self.assertEqual(status, 200)
        self.assertEqual(hist["product_id"], 3)
        self.assertEqual(hist["product_name"], "Nimbus Mechanical Keyboard")
        self.assertEqual(hist["current_price"], new)
        last = hist["changes"][-1]
        self.assertEqual(last["old_price"], before["price"])
        self.assertEqual(last["new_price"], new)
        self.assertEqual(last["delta"], round(new - before["price"], 2))

    def test_history_multiple_changes_chain(self):
        _s, before = self.api("GET", "/api/products/5")
        p1, p2 = 250.0, 300.0
        self.api("POST", "/api/products/5/price", {"price": p1})
        body = self.api("POST", "/api/products/5/price", {"price": p2})[1]

        # second change is relative to the *first* new price
        ch = body["change"]
        self.assertEqual(ch["old_price"], p1)
        self.assertEqual(ch["new_price"], p2)
        self.assertEqual(ch["delta"], round(p2 - p1, 2))
        self.assertEqual(ch["pct_change"], round((p2 - p1) / p1 * 100, 2))

        _s, hist = self.api("GET", "/api/products/5/price-history")
        mine = [c for c in hist["changes"] if c["product_id"] == 5]
        self.assertGreaterEqual(len(mine), 2)
        self.assertEqual(mine[-2]["new_price"], p1)
        self.assertEqual(mine[-1]["new_price"], p2)
        self.assertEqual(hist["current_price"], p2)

    def test_history_unknown_product(self):
        status, body = self.api("GET", "/api/products/4242/price-history")
        self.assertEqual(status, 404)
        self.assertIn("error", body)


class TestPriceChangeFeed(ServerTestCase):

    def test_feed_filter_by_product(self):
        _s, before = self.api("GET", "/api/products/7")
        new = 55.0
        self.api("POST", "/api/products/7/price", {"price": new})

        status, feed = self.api("GET", "/api/price-changes?product_id=7")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(feed["count"], 1)
        self.assertTrue(all(c["product_id"] == 7 for c in feed["changes"]))
        self.assertEqual(feed["changes"][-1]["new_price"], new)
        self.assertEqual(feed["changes"][-1]["old_price"], before["price"])

        # other product's changes are excluded
        _s, other = self.api("GET", "/api/price-changes?product_id=8")
        self.assertTrue(all(c["product_id"] == 8 for c in other["changes"]))

    def test_feed_since_filter(self):
        _s, before = self.api("GET", "/api/products/8")
        self.api("POST", "/api/products/8/price", {"price": 100.0})

        _s, future = self.api("GET", "/api/price-changes?since=2099-01-01T00:00:00")
        self.assertEqual(future["count"], 0)

        _s, past = self.api("GET", "/api/price-changes?since=1970-01-01T00:00:00")
        self.assertGreaterEqual(past["count"], 1)
        self.assertTrue(all(c["changed_at"] >= "1970-01-01T00:00:00"
                            for c in past["changes"]))

    def test_feed_entry_shape(self):
        _s, before = self.api("GET", "/api/products/9")
        new = 40.0
        self.api("POST", "/api/products/9/price", {"price": new})
        _s, feed = self.api("GET", "/api/price-changes")
        entry = [c for c in feed["changes"]
                 if c["product_id"] == 9 and c["new_price"] == new][-1]
        for field in ("product_id", "product_name", "old_price", "new_price",
                      "delta", "pct_change", "changed_at", "reason"):
            self.assertIn(field, entry)
        self.assertEqual(entry["old_price"], before["price"])


class TestPriceSummary(ServerTestCase):

    def test_summary(self):
        _s, p8 = self.api("GET", "/api/products/8")
        original = p8["price"]
        new = 100.0
        self.api("POST", "/api/products/8/price", {"price": new})

        status, body = self.api("GET", "/api/price-changes/summary")
        self.assertEqual(status, 200)
        self.assertIn("generated_at", body)
        rows = {r["product_id"]: r for r in body["summary"]}
        self.assertEqual(len(body["summary"]), 10)

        # untouched product: no changes, zero delta
        r2 = rows[2]
        self.assertEqual(r2["num_changes"], 0)
        self.assertEqual(r2["original_price"], r2["current_price"])
        self.assertEqual(r2["delta"], 0)
        self.assertEqual(r2["pct_change"], 0)

        # changed product: original vs current + delta + %
        r8 = rows[8]
        self.assertEqual(r8["name"], "Drift 1TB NVMe SSD")
        self.assertGreaterEqual(r8["num_changes"], 1)
        self.assertEqual(r8["original_price"], original)
        self.assertEqual(r8["current_price"], new)
        self.assertEqual(r8["delta"], round(new - original, 2))
        self.assertEqual(r8["pct_change"],
                         round((new - original) / original * 100, 2))

    def test_summary_pct_is_stable_under_repeated_changes(self):
        # original price must stay the *first* recorded old price
        _s, p10 = self.api("GET", "/api/products/10")
        self.api("POST", "/api/products/10/price", {"price": 20.0})
        self.api("POST", "/api/products/10/price", {"price": 25.0})
        _s, body = self.api("GET", "/api/price-changes/summary")
        r10 = next(r for r in body["summary"] if r["product_id"] == 10)
        self.assertEqual(r10["original_price"], p10["price"])
        self.assertEqual(r10["num_changes"], 2)
        self.assertEqual(r10["current_price"], 25.0)
