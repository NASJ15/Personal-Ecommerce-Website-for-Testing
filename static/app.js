/* ShopLocal frontend — catalog, cart, and price-change tracker */
const API = "/api";
const state = {
  products: [],
  categories: [],
  activeCategory: "all",
  search: "",
  cartId: localStorage.getItem("shoplocal_cart_id") || null,
  originals: {}, // product_id -> first-seen price, to show "was" price
};

const $ = (id) => document.getElementById(id);
const money = (n) => `$${n.toFixed(2)}`;

// ---------------------------------------------------------------- API helper
async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.status + " " + res.statusText;
    try { msg = (await res.json()).error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// ---------------------------------------------------------------- catalog
async function loadCatalog() {
  const [data, summaryData] = await Promise.all([
    api("/products"),
    api("/price-changes/summary").catch(() => null),
  ]);
  state.products = data.products;
  // seed "original" prices so the grid can show strikethroughs even after a reload
  (summaryData && summaryData.summary ? summaryData.summary : []).forEach((s) => {
    state.originals[s.product_id] = s.original_price;
  });
  state.products.forEach((p) => {
    if (!(p.id in state.originals)) state.originals[p.id] = p.price;
  });
  const cats = await api("/categories");
  state.categories = cats.categories;
  renderCategories();
  renderGrid();
}

function renderCategories() {
  const wrap = $("categories");
  const chips = ["all", ...state.categories];
  wrap.innerHTML = "";
  chips.forEach((c) => {
    const b = document.createElement("button");
    b.className = "chip" + (c === state.activeCategory ? " active" : "");
    b.textContent = c === "all" ? "All" : c;
    b.onclick = () => { state.activeCategory = c; renderCategories(); renderGrid(); };
    wrap.appendChild(b);
  });
}

function visibleProducts() {
  const q = state.search.toLowerCase();
  return state.products.filter((p) => {
    const okCat = state.activeCategory === "all" || p.category === state.activeCategory;
    const okQ = !q || p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q);
    return okCat && okQ;
  });
}

function renderGrid() {
  const grid = $("product-grid");
  const items = visibleProducts();
  if (!items.length) {
    grid.innerHTML = '<p class="empty">No products match your search.</p>';
    return;
  }
  grid.innerHTML = "";
  items.forEach((p) => {
    const orig = state.originals[p.id];
    const changed = p.price !== orig;
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="thumb">${p.image_emoji}</div>
      <h3>${p.name}</h3>
      <div class="cat-tag">${p.category}</div>
      <p class="desc">${p.description}</p>
      <div class="price-row">
        <span class="price">${money(p.price)}</span>
        ${changed ? `<span class="price-old" title="Original price">${money(orig)}</span>` : ""}
      </div>
      <div class="stock ${p.stock < 30 ? "low" : ""}">${p.stock} in stock</div>
      <button class="btn primary" data-add="${p.id}" style="margin-top:10px" ${p.stock === 0 ? "disabled" : ""}>
        ${p.stock === 0 ? "Out of stock" : "Add to cart"}
      </button>`;
    grid.appendChild(card);
  });
  grid.querySelectorAll("[data-add]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await addToCart(Number(btn.dataset.add), 1);
      } catch (e) { alert(e.message); }
    };
  });
}

// ---------------------------------------------------------------- cart
async function ensureCart() {
  if (state.cartId) {
    try { await api(`/cart/${state.cartId}`); return; } catch { state.cartId = null; }
  }
  const cart = await api("/cart", { method: "POST" });
  state.cartId = cart.cart_id;
  localStorage.setItem("shoplocal_cart_id", state.cartId);
}

async function getCart() {
  await ensureCart();
  return api(`/cart/${state.cartId}`);
}

async function addToCart(productId, qty) {
  const cart = await api(`/cart/${state.cartId}/add`, {
    method: "POST",
    body: JSON.stringify({ product_id: productId, quantity: qty }),
  });
  afterCartChange(cart);
}

async function setQty(productId, qty) {
  const cart = await api(`/cart/${state.cartId}/items/${productId}`, {
    method: "POST",
    body: JSON.stringify({ quantity: qty }),
  });
  afterCartChange(cart);
}

async function clearCart() {
  for (const item of (await getCart()).items) {
    await api(`/cart/${state.cartId}/items/${item.product_id}`, { method: "DELETE" });
  }
  afterCartChange(await getCart());
}

function afterCartChange(cart) {
  // sync stock/price from server response
  cart.items.forEach((it) => {
    const p = state.products.find((x) => x.id === it.product_id);
    if (p) { p.price = it.unit_price; p.stock = it.stock; }
  });
  renderCart(cart);
  renderGrid();
  updateBadge(cart);
}

function updateBadge(cart) {
  const badge = $("cart-badge");
  const n = cart.item_count;
  badge.textContent = n;
  badge.classList.toggle("hidden", n === 0);
}

function renderCart(cart) {
  const wrap = $("cart-items");
  wrap.innerHTML = "";
  if (!cart.items.length) {
    wrap.innerHTML = '<p class="empty" style="grid-column:auto">Your cart is empty. 🛒</p>';
  }
  cart.items.forEach((it) => {
    const p = state.products.find((x) => x.id === it.product_id) || {};
    const row = document.createElement("div");
    row.className = "cart-item";
    row.innerHTML = `
      <div class="ci-emoji">${p.image_emoji || "📦"}</div>
      <div class="ci-body">
        <div class="ci-name">${it.name}</div>
        <div class="ci-price">${money(it.unit_price)} each</div>
      </div>
      <div class="qty-ctrl">
        <button data-dec="${it.product_id}" aria-label="Decrease">−</button>
        <span>${it.quantity}</span>
        <button data-inc="${it.product_id}" aria-label="Increase">+</button>
      </div>`;
    row.querySelector("[data-dec]").onclick = () => setQty(it.product_id, it.quantity - 1);
    row.querySelector("[data-inc]").onclick = () => addToCart(it.product_id, 1);
    wrap.appendChild(row);
  });
  $("cart-total").textContent = money(cart.total);
  $("checkout-btn").disabled = cart.item_count === 0;
}

// ---------------------------------------------------------------- checkout
async function checkout() {
  const btn = $("checkout-btn");
  btn.disabled = true;
  try {
    const order = await api(`/cart/${state.cartId}/checkout`, { method: "POST" });
    const box = $("checkout-receipt");
    box.classList.remove("hidden");
    box.innerHTML = `
      <strong>✅ Order placed!</strong><br>
      Order ${order.order_id}<br>
      ${order.items.map((i) => `${i.quantity} × ${i.name} — ${money(i.line_total)}`).join("<br>")}
      <br>Total: <strong>${money(order.total)}</strong>`;
    // refresh stock in catalog
    await loadCatalog();
    afterCartChange(await getCart());
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- tracker
async function refreshTracker() {
  try {
    const [summaryData, changes] = await Promise.all([
      api("/price-changes/summary"),
      api("/price-changes"),
    ]);
    const summary = summaryData.summary || [];
    // mark changed prices against originals
    summary.forEach((s) => { if (!(s.product_id in state.originals)) state.originals[s.product_id] = s.original_price; });

    const sWrap = $("tracker-summary");
    const changed = summary.filter((s) => s.num_changes > 0);
    sWrap.innerHTML = changed.length
      ? changed.map((s) => {
          const cls = s.delta < 0 ? "delta-down" : s.delta > 0 ? "delta-up" : "";
          const arrow = s.delta < 0 ? "▼" : s.delta > 0 ? "▲" : "•";
          return `<div class="ts-row">
            <span>${s.name}</span>
            <span>${money(s.current_price)}
              <span class="${cls}">${arrow} ${s.pct_change >= 0 ? "+" : ""}${s.pct_change}%</span>
            </span></div>`;
        }).join("")
      : '<p class="no-changes">No price changes recorded yet.</p>';

    const hWrap = $("tracker-history");
    const list = changes.changes.slice().reverse();
    hWrap.innerHTML = list.length
      ? list.map((c) => {
          const cls = c.delta < 0 ? "down" : c.delta > 0 ? "up" : "";
          return `<div class="tr-ch">
            <strong>${c.product_name}</strong>: ${money(c.old_price)} → ${money(c.new_price)}
            <span class="${cls}">(${c.pct_change >= 0 ? "+" : ""}${c.pct_change}%)</span><br>
            <span class="when">${c.changed_at} · ${c.reason}</span>
          </div>`;
        }).join("")
      : '<p class="no-changes">No changes yet. Try it:</p>' +
        '<p class="hint"><code>curl -X POST localhost:8000/api/products/1/price -H "Content-Type: application/json" -d \'{"price": 99.99, "reason": "flash sale"}\'</code></p>';
  } catch (e) {
    console.error(e);
    const box = $("tracker-history");
    if (box) box.innerHTML = `<p class="empty">Tracker failed to load: ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------- drawers
function openDrawer(id) {
  $(id).classList.remove("hidden");
  $("overlay").classList.remove("hidden");
}
function closeDrawers() {
  document.querySelectorAll(".drawer").forEach((d) => d.classList.add("hidden"));
  $("overlay").classList.add("hidden");
}

// ---------------------------------------------------------------- init
$("search").addEventListener("input", (e) => { state.search = e.target.value; renderGrid(); });
$("cart-toggle").onclick = async () => {
  try { openDrawer("cart-drawer"); afterCartChange(await getCart()); }
  catch (e) { alert("Could not load cart: " + e.message); }
};
$("cart-close").onclick = closeDrawers;
$("overlay").onclick = closeDrawers;
$("checkout-btn").onclick = checkout;
$("clear-cart-btn").onclick = clearCart;
$("tracker-toggle").onclick = () => { openDrawer("tracker-panel"); refreshTracker(); };
$("tracker-close").onclick = closeDrawers;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawers(); });

loadCatalog()
  .then(async () => { afterCartChange(await getCart()); })
  .catch((e) => { $("product-grid").innerHTML = `<p class="empty">Failed to load catalog: ${e.message}</p>`; });
refreshTracker();
setInterval(refreshTracker, 30000); // keep tracker fresh while open
