# 🛍️ ShopLocal — E-Commerce Demo 

A self-contained e-commerce website with:

- **Product catalog** — 10 sample products, category filter, live search
- **Cart feature** — server-side carts (create / add / change qty / clear / checkout), stock enforced at checkout
- **Price-change tracking API** — set a new price and every change is recorded with timestamp, delta, and % change; query history, global feed, or per-product summary

**Zero dependencies** — runs on the Python 3 standard library only.

## Run

```bash
cd ~/your-project-location/
python3 app.py                # http://localhost:8000
PORT=9000 python3 app.py      # custom port
```

Open **http://localhost:8000** in a browser.

## Layout

```
ecommerce/
├── app.py                 # HTTP server + full API (stdlib only)
├── data/products.json     # 10 example products
└── static/
    ├── index.html         # storefront
    ├── style.css
    └── app.js             # catalog, cart, price tracker UI
```

## API Reference

All endpoints are JSON.

### Health
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness check |

### Catalog
| Method | Path | Description |
|---|---|---|
| GET | `/api/products` | All products (filter: `?category=audio`) |
| GET | `/api/products/<id>` | Single product |
| GET | `/api/categories` | Distinct category list |

### Cart
| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/api/cart` | – | Create cart → `cart_id` |
| GET | `/api/cart/<id>` | – | View cart (items, total) |
| POST | `/api/cart/<id>/add` | `{"product_id": 1, "quantity": 2}` | Add item |
| POST | `/api/cart/<id>/items/<pid>` | `{"quantity": 3}` | Set qty (`0` = remove) |
| DELETE | `/api/cart/<id>/items/<pid>` | – | Remove item |
| DELETE | `/api/cart/<id>` | – | Delete cart |
| POST | `/api/cart/<id>/checkout` | – | Place order (decrements stock) |

### Price-change tracking
| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/api/products/<id>/price` | `{"price": 99.99, "reason": "flash sale"}` | Set new price, records the change |
| GET | `/api/products/<id>/price-history` | – | All changes for one product |
| GET | `/api/price-changes` | – | Global change feed → `{count, changes: [...]}` (`?since=2026-11-13T00:00:00&product_id=1`) |
| GET | `/api/price-changes/summary` | – | Per-product original vs current price, delta, %, count → `{generated_at, summary: [...]}` |

## Try the price tracker

```bash
# 1) drop the headphones to a flash-sale price
curl -X POST localhost:8000/api/products/1/price \
  -H "Content-Type: application/json" \
  -d '{"price": 89.99, "reason": "flash sale"}'

# 2) watch the change feed
curl localhost:8000/api/price-changes

# 3) per-product summary (original vs current, delta, %)
curl localhost:8000/api/price-changes/summary
```

Or just click **📈 Tracker** in the site header — it shows the live summary and history and auto-refreshes every 30 seconds. Changed products also show their original price struck through on the card (this survives page reloads).

## Cart flow example

```bash
CART=$(curl -s -X POST localhost:8000/api/cart | python3 -c 'import sys,json;print(json.load(sys.stdin)["cart_id"])')
curl -s -X POST localhost:8000/api/cart/$CART/add -H 'Content-Type: application/json' -d '{"product_id": 1, "quantity": 1}'
curl -s -X POST localhost:8000/api/cart/$CART/add -H 'Content-Type: application/json' -d '{"product_id": 7, "quantity": 2}'
curl -s localhost:8000/api/cart/$CART
curl -s -X POST localhost:8000/api/cart/$CART/checkout
```

## Testing

A test suite lives in `tests/` — standard library only (`unittest`), no extra
packages needed. It boots a fresh server instance per test class on a random
port, so it's safe to run alongside a running shop.

```bash
python3 -m unittest -v                  # from the project root
python3 -m unittest tests.test_cart -v  # a single module
```

Covered: health, catalog + category filter, cart lifecycle (add / qty /
remove / delete), checkout + stock enforcement (incl. 409 paths), a
concurrency test for parallel cart adds, the full price-change tracking API
(set / history / feed / summary + validation), static file serving,
path-traversal safety, CORS, and unknown-route handling.

## Notes
- State (carts, price history, stock adjustments) is in-memory; the product catalog itself lives in `data/products.json`. Stock changes and price history reset when the server restarts.
- The cart is identified by an opaque `cart_id`; the website stores it in `localStorage` so your cart survives reloads.
- Price-change records are kept for the server's lifetime — perfect for demos and testing.
