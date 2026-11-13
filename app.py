#!/usr/bin/env python3
"""
ShopLocal — a minimal e-commerce demo server.

Features
  * Product catalog API (JSON)
  * Cart API (in-memory carts, create / add / remove / get)
  * Checkout API (decrements stock, returns order receipt)
  * Price-change tracking API:
      - POST  /api/products/<id>/price          -> set a new price (records the change)
      - GET   /api/products/<id>/price-history  -> full price history for one product
      - GET   /api/price-changes                -> all recorded changes (optional ?since=<iso8601>&product_id=<id>)
      - GET   /api/price-changes/summary        -> per-product current vs original price + delta

Runs with the Python standard library only. No third-party packages.

Usage:
    python3 app.py            # serves on http://localhost:8000
    PORT=9000 python3 app.py  # custom port
"""

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_FILE = os.path.join(BASE_DIR, "data", "products.json")

# ---------------------------------------------------------------------------
# In-memory state (loaded from disk so restarts keep the catalog)
# ---------------------------------------------------------------------------
with open(DATA_FILE, "r", encoding="utf-8") as f:
    DATA = json.load(f)

PRODUCTS = {p["id"]: p for p in DATA["products"]}
CARTS = {}            # cart_id -> {"items": {product_id: qty}, "created_at": ...}
PRICE_CHANGES = []    # list of change records (newest appended last)
LOCK = __import__("threading").Lock()


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_price_change(product_id, old_price, new_price, reason=None):
    entry = {
        "product_id": product_id,
        "product_name": PRODUCTS[product_id]["name"],
        "old_price": old_price,
        "new_price": new_price,
        "delta": round(new_price - old_price, 2),
        "pct_change": round((new_price - old_price) / old_price * 100, 2) if old_price else None,
        "changed_at": utcnow_iso(),
        "reason": reason or "manual update",
    }
    PRICE_CHANGES.append(entry)
    return entry


class Handler(BaseHTTPRequestHandler):
    server_version = "ShopLocal/1.0"

    # ------------------------------------------------------------------ util
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message, status=400):
        self._send_json({"error": message}, status=status)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return None

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self._send_error_json("Not found", status=404)
            return
        ext = os.path.splitext(full)[1].lower()
        mime = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter logs
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)

        # --- API: catalog ---
        if path == "/api/products":
            items = list(PRODUCTS.values())
            if "category" in qs:
                cat = qs["category"][0].lower()
                items = [p for p in items if p["category"].lower() == cat]
            return self._send_json({"count": len(items), "products": items})

        m = re.fullmatch(r"/api/products/(\d+)", path)
        if m:
            pid = int(m.group(1))
            if pid not in PRODUCTS:
                return self._send_error_json("Product not found", status=404)
            return self._send_json(PRODUCTS[pid])

        if path == "/api/categories":
            cats = sorted({p["category"] for p in PRODUCTS.values()})
            return self._send_json({"categories": cats})

        # --- API: price history / tracking ---
        m = re.fullmatch(r"/api/products/(\d+)/price-history", path)
        if m:
            pid = int(m.group(1))
            if pid not in PRODUCTS:
                return self._send_error_json("Product not found", status=404)
            history = [c for c in PRICE_CHANGES if c["product_id"] == pid]
            return self._send_json({
                "product_id": pid,
                "product_name": PRODUCTS[pid]["name"],
                "current_price": PRODUCTS[pid]["price"],
                "changes": history,
            })

        if path == "/api/price-changes":
            changes = list(PRICE_CHANGES)
            if "product_id" in qs:
                changes = [c for c in changes if c["product_id"] == int(qs["product_id"][0])]
            if "since" in qs:
                since = qs["since"][0]
                changes = [c for c in changes if c["changed_at"] >= since]
            return self._send_json({"count": len(changes), "changes": changes})

        if path == "/api/price-changes/summary":
            summary = []
            for pid, p in PRODUCTS.items():
                hist = [c for c in PRICE_CHANGES if c["product_id"] == pid]
                original = hist[0]["old_price"] if hist else p["price"]
                current = p["price"]
                summary.append({
                    "product_id": pid,
                    "name": p["name"],
                    "original_price": original,
                    "current_price": current,
                    "delta": round(current - original, 2),
                    "pct_change": round((current - original) / original * 100, 2) if original else 0,
                    "num_changes": len(hist),
                })
            return self._send_json({"generated_at": utcnow_iso(), "summary": summary})

        # --- API: cart ---
        m = re.fullmatch(r"/api/cart/([0-9a-f-]+)", path)
        if m:
            cart = CARTS.get(m.group(1))
            if not cart:
                return self._send_error_json("Cart not found", status=404)
            return self._send_json(self._cart_view(m.group(1), cart))

        # --- health check ---
        if path == "/api/health":
            return self._send_json({"status": "ok", "time": utcnow_iso()})

        # --- everything else: static site ---
        self._serve_static(path)

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # --- create cart ---
        if path == "/api/cart":
            cart_id = uuid.uuid4().hex
            CARTS[cart_id] = {"items": {}, "created_at": utcnow_iso()}
            return self._send_json(self._cart_view(cart_id, CARTS[cart_id]), status=201)

        # --- add to cart ---
        m = re.fullmatch(r"/api/cart/([0-9a-f-]+)/add", path)
        if m:
            cart = CARTS.get(m.group(1))
            if not cart:
                return self._send_error_json("Cart not found", status=404)
            body = self._read_json_body()
            if body is None:
                return self._send_error_json("Invalid JSON body", status=400)
            pid, qty = body.get("product_id"), body.get("quantity", 1)
            if pid not in PRODUCTS:
                return self._send_error_json("Product not found", status=404)
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                return self._send_error_json("quantity must be an integer", status=400)
            if qty <= 0:
                return self._send_error_json("quantity must be > 0", status=400)
            with LOCK:
                if pid not in cart["items"] and PRODUCTS[pid]["stock"] == 0:
                    return self._send_error_json("Product out of stock", status=409)
                cart["items"][pid] = cart["items"].get(pid, 0) + qty
            return self._send_json(self._cart_view(m.group(1), cart), status=201)

        # --- update cart quantity ---
        m = re.fullmatch(r"/api/cart/([0-9a-f-]+)/items/(\d+)", path)
        if m:
            cart = CARTS.get(m.group(1))
            if not cart:
                return self._send_error_json("Cart not found", status=404)
            pid = int(m.group(2))
            body = self._read_json_body()
            if body is None:
                return self._send_error_json("Invalid JSON body", status=400)
            qty = body.get("quantity", 0)
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                return self._send_error_json("quantity must be an integer", status=400)
            with LOCK:
                if qty <= 0:
                    cart["items"].pop(pid, None)
                else:
                    if pid not in PRODUCTS:
                        return self._send_error_json("Product not found", status=404)
                    cart["items"][pid] = qty
            return self._send_json(self._cart_view(m.group(1), cart))

        # --- checkout ---
        m = re.fullmatch(r"/api/cart/([0-9a-f-]+)/checkout", path)
        if m:
            cart = CARTS.get(m.group(1))
            if not cart:
                return self._send_error_json("Cart not found", status=404)
            if not cart["items"]:
                return self._send_error_json("Cart is empty", status=400)
            order = {
                "order_id": "ORD-" + uuid.uuid4().hex[:10].upper(),
                "placed_at": utcnow_iso(),
                "items": [],
            }
            total = 0.0
            with LOCK:
                for pid, qty in list(cart["items"].items()):
                    p = PRODUCTS[pid]
                    if p["stock"] < qty:
                        return self._send_error_json(
                            f"Insufficient stock for {p['name']} (available: {p['stock']})",
                            status=409)
                    p["stock"] -= qty
                    line_total = round(p["price"] * qty, 2)
                    total += line_total
                    order["items"].append({
                        "product_id": pid, "name": p["name"],
                        "quantity": qty, "unit_price": p["price"],
                        "line_total": line_total,
                    })
                cart["items"] = {}
            order["total"] = round(total, 2)
            return self._send_json(order, status=201)

        # --- set product price (price-change tracking) ---
        m = re.fullmatch(r"/api/products/(\d+)/price", path)
        if m:
            pid = int(m.group(1))
            if pid not in PRODUCTS:
                return self._send_error_json("Product not found", status=404)
            body = self._read_json_body()
            if body is None:
                return self._send_error_json("Invalid JSON body", status=400)
            new_price = body.get("price")
            if not isinstance(new_price, (int, float)) or new_price <= 0:
                return self._send_error_json("price must be a positive number", status=400)
            new_price = round(float(new_price), 2)
            with LOCK:
                old_price = PRODUCTS[pid]["price"]
                PRODUCTS[pid]["price"] = new_price
                entry = record_price_change(pid, old_price, new_price, body.get("reason"))
            return self._send_json({"updated": True, "change": entry}, status=200)

        self._send_error_json("Not found", status=404)

    # ---------------------------------------------------------------- DELETE
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # --- remove item from cart ---
        m = re.fullmatch(r"/api/cart/([0-9a-f-]+)/items/(\d+)", path)
        if m:
            cart = CARTS.get(m.group(1))
            if not cart:
                return self._send_error_json("Cart not found", status=404)
            with LOCK:
                cart["items"].pop(int(m.group(2)), None)
            return self._send_json(self._cart_view(m.group(1), cart))

        # --- delete whole cart ---
        m = re.fullmatch(r"/api/cart/([0-9a-f-]+)", path)
        if m:
            if m.group(1) not in CARTS:
                return self._send_error_json("Cart not found", status=404)
            del CARTS[m.group(1)]
            return self._send_json({"deleted": True, "cart_id": m.group(1)})

        self._send_error_json("Not found", status=404)

    # ------------------------------------------------------------------ CORS
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # -------------------------------------------------------------- helpers
    def _cart_view(self, cart_id, cart):
        items = []
        total = 0.0
        for pid, qty in cart["items"].items():
            p = PRODUCTS[pid]
            line_total = round(p["price"] * qty, 2)
            total += line_total
            items.append({
                "product_id": pid,
                "name": p["name"],
                "category": p["category"],
                "unit_price": p["price"],
                "quantity": qty,
                "line_total": line_total,
                "stock": p["stock"],
            })
        return {
            "cart_id": cart_id,
            "created_at": cart["created_at"],
            "item_count": len(items),
            "items": items,
            "total": round(total, 2),
            "currency": "USD",
        }


def main():
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"🛍️  ShopLocal running at http://localhost:{port}")
    print(f"   Catalog:  http://localhost:{port}/")
    print(f"   API docs: http://localhost:{port}/api (see README for endpoints)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
