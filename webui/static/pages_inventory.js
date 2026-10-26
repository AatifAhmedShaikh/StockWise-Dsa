/* pages_inventory.js - Dashboard, Products, Transactions. */
'use strict';

function pageHead(title, sub) {
  return h`<h1 class="page-title">${title}</h1><p class="page-sub">${sub}</p>`;
}

function productTable(products, compact) {
  return table([
    { label: 'ID', get: function (p) { return p.id; }, cls: 'num' },
    { label: 'Name', get: function (p) { return p.name; } },
    { label: 'Category', get: function (p) { return p.category; } },
    { label: 'Price', get: function (p) { return money(p.price); }, cls: 'num' },
    { label: 'Qty', get: function (p) { return num(p.quantity); }, cls: 'num' },
    { label: 'Min stock', get: function (p) { return num(p.min_stock); }, cls: 'num', hide: compact },
    { label: 'Demand', get: function (p) { return p.demand === null ? '–' : num(p.demand); }, cls: 'num', hide: compact },
    { label: 'Importance', get: function (p) { return p.importance === null ? '–' : p.importance + ' / 5'; }, cls: 'num', hide: compact },
    { label: 'Value', get: function (p) { return money(p.value); }, cls: 'num' },
    { label: 'Status', get: function (p) { return badge(p.status); } },
  ].filter(function (c) { return !c.hide; }), products, { empty: 'No products match.' });
}

function productCard(p) {
  var pct = Math.min(p.quantity / Math.max(2 * p.min_stock, 1), 1) * 100;
  return h`<div class="pcard">
    <div class="top"><img src="${categoryImage(p.category)}" alt=""><div><div class="name">${p.name}</div>
      <div class="meta">${p.category} · #${p.id}</div></div></div>
    <div class="gauge"><div style="width:${pct}%"></div></div>
    <div class="stock">${num(p.quantity)} in stock · minimum ${num(p.min_stock)}</div>
    <div class="bottom">${badge(p.status)}<span class="price">${money(p.price)}</span></div></div>`;
}

function txTable(rows) {
  return table([
    { label: 'Time', get: function (t) { return t.created_at; }, cls: 'nowrap' },
    { label: 'Product', get: function (t) { return t.product_name; } },
    { label: 'Type', get: function (t) { return t.type === 'IN' ? 'Stock in' : 'Stock out'; }, cls: 'nowrap' },
    { label: 'Qty', get: function (t) { return num(t.quantity); }, cls: 'num' },
    { label: 'Balance', get: function (t) { return num(t.balance_after); }, cls: 'num' },
    { label: 'Note', get: function (t) { return t.note || ''; } },
  ], rows, { empty: 'No transactions recorded yet.', style: 'max-height:420px' });
}

/* ---------------------------------------------------------------- Dashboard */
async function pageDashboard(root) {
  var d = await api('/api/dashboard'), k = d.kpis;
  var units = metric('Units in stock', num(k.units), {
    icon: 'package', delta: (d.level_change >= 0 ? '+' : '') + num(d.level_change) + ' in 30 days',
    extra: d.level.length ? sparkArea(d.level.map(function (x) { return x.units; })) : '' });
  var body = h`
    <img class="hero" src="/assets/hero.svg" alt="StockWise: know what to restock before it runs out">
    <div class="grid g5">
      ${metric('Products', num(k.products), { icon: 'inventory_2' })}
      ${units}
      ${metric('Inventory value', money(k.value, 0), { icon: 'payments', help: money(k.value) + ' exactly' })}
      ${metric('Low stock', num(k.low), { icon: 'warning', help: 'Above zero but at or below minimum stock' })}
      ${metric('Out of stock', num(k.out), { icon: 'error' })}
    </div>`;
  if (!k.products) {
    root.innerHTML = String(h`${body}<div class="card" style="margin-top:18px">${empty('No products yet. Add your first one on the Products page.')}</div>`);
    return;
  }
  var days = d.movement.map(function (m) { return shortDate(m.date); });
  var movement = d.movement.length ? h`${legend([['Stock in', BLUE], ['Stock out', ORANGE]])}${groupedColumns(days, [
    { name: 'Stock in', color: BLUE, values: d.movement.map(function (m) { return m.in; }) },
    { name: 'Stock out', color: ORANGE, values: d.movement.map(function (m) { return m.out; }) }], { label: 'Stock movement' })}` : empty('No transactions yet.');
  var attention = d.attention.length ? d.attention.map(function (p) {
    return h`<div class="attn"><img src="${categoryImage(p.category)}" alt=""><div class="t"><b>${p.name}</b>
      <small>${p.quantity} of ${p.min_stock} min · priority ${Math.round(p.score)}</small></div>${badge(p.status)}</div>`;
  }) : h`<div class="caption">Every product is above its minimum stock.</div>`;
  var money0 = function (v) { return money(v, 0); };
  root.innerHTML = String(h`${body}
    <div class="grid g-3-2" style="margin-top:18px">
      ${card('Stock movement, last 30 days', movement)}
      ${card('Needs attention', attention)}
    </div>
    <div class="grid g2" style="margin-top:18px">
      ${card('Inventory value by category', hbar(d.by_category.map(function (c) { return { label: c.category, value: c.value }; }), { fmt: money0, label: 'Inventory value by category' }))}
      ${card('Highest-value products', h`${hbar(d.top_value.items.map(function (p) { return { label: p.name, value: p.value }; }), { fmt: money0, label: 'Highest-value products' })}<div class="caption">Ranked by C Merge Sort · ${d.top_value.comparisons} comparisons</div>`)}
    </div>
    <div style="margin-top:18px">${card('Recent transactions', txTable(d.recent))}</div>`);
}

/* ---------------------------------------------------------------- Products */
var PS = { tab: 'catalog', q: '', cats: {}, view: 'grid', min: null, max: null, editId: null, deleteId: null };

function productForm(p, mode) {
  var add = mode === 'add', dem = p.demand === null || p.demand === undefined;
  return h`<form id="pform" class="card" autocomplete="off">
    <div class="form-section">Details</div>
    <div class="form-grid">
      <label class="field"><span>Product ID</span><input type="number" name="id" min="1" step="1" required value="${p.id}" ${add ? '' : raw('disabled')}></label>
      <label class="field"><span>Name</span><input type="text" name="name" maxlength="63" required value="${p.name}" placeholder="e.g. USB-C Charging Cable"></label>
      <label class="field"><span>Category</span><input type="text" name="category" maxlength="31" list="catlist" required value="${p.category}" placeholder="e.g. Electronics"></label>
    </div>
    <div class="form-section">Stock and pricing</div>
    <div class="form-grid">
      <label class="field"><span>Price ($)</span><input type="number" name="price" min="0" step="0.01" required value="${p.price}"></label>
      <label class="field"><span>Quantity</span><input type="number" name="quantity" min="0" step="1" required value="${p.quantity}" ${add ? '' : raw('disabled title="Change stock on the Transactions page"')}></label>
      <label class="field"><span>Minimum stock</span><input type="number" name="min_stock" min="0" step="1" required value="${p.min_stock}"></label>
    </div>
    <div class="form-section">Planning inputs</div>
    <div class="form-grid">
      <label class="field"><span>Estimated demand (units/month)</span><input type="number" name="demand" min="0" step="1" value="${dem ? 0 : p.demand}" ${dem ? raw('disabled') : ''}></label>
      <label class="field"><span>&nbsp;</span><span class="check"><input type="checkbox" name="demand_unknown" ${dem ? raw('checked') : ''}> Demand unknown</span></label>
      <label class="field"><span>Importance</span><select name="importance">${options([['', 'Unknown'], [1, '1 (lowest)'], [2, '2'], [3, '3'], [4, '4'], [5, '5 (highest)']], p.importance === null ? '' : p.importance)}</select></label>
    </div>
    <div id="pform-error"></div>
    <div style="margin-top:14px"><button class="btn primary" type="submit">${icon('save', 18)}Save product</button></div>
  </form>`;
}

function readProductForm(form) {
  var f = form.elements;
  return { id: parseInt(f.id.value, 10), name: f.name.value, category: f.category.value,
    price: parseFloat(f.price.value), quantity: parseInt(f.quantity.value, 10),
    min_stock: parseInt(f.min_stock.value, 10),
    demand: f.demand_unknown.checked ? null : intOrNull(f.demand.value), importance: intOrNull(f.importance.value) };
}

function wireProductForm(root, submit) {
  var form = $('#pform', root);
  form.elements.demand_unknown.addEventListener('change', function () {
    form.elements.demand.disabled = form.elements.demand_unknown.checked;
  });
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var box = $('#pform-error', root);
    box.innerHTML = '';
    try { await submit(readProductForm(form)); }
    catch (err) { box.innerHTML = String(alertBox('error', err.message)); }
  });
}

async function pageProducts(root) {
  var all = await api('/api/products');
  var ceiling = all.price_ceiling, nextId = Math.max.apply(null, all.products.map(function (p) { return p.id; }).concat([1000])) + 1;
  var tabs = [['catalog', 'Catalog', 'grid_view'], ['add', 'Add product', 'add_circle'], ['edit', 'Edit', 'edit'], ['delete', 'Delete', 'delete']];
  root.innerHTML = String(h`${pageHead('Products', 'Search uses the C hash table (ID) and trie (name prefix). The price filter is a range query on a C AVL tree.')}
    ${tabsBar(tabs, PS.tab)}<div id="tab"></div>
    <datalist id="catlist">${all.categories.map(function (c) { return h`<option value="${c}">`; })}</datalist>`);
  onTabs(root, function (t) { PS.tab = t; pageProducts(root); });
  var tab = $('#tab', root);
  var changed = async function (message) { toast(message); await refreshCount(); pageProducts(root); };

  if (PS.tab === 'catalog') {
    var lo = PS.min === null ? 0 : Math.min(PS.min, ceiling), hi = PS.max === null ? ceiling : Math.min(PS.max, ceiling);
    tab.innerHTML = String(h`
      <div class="row gap-sm" style="align-items:center">
        <div class="search-wrap" style="flex:3">${icon('search', 20)}<input type="search" id="q" value="${PS.q}" placeholder="Search by product ID or name, e.g. 1042 or cab"></div>
        <div style="flex:none">${segmented('view', [['grid', h`${icon('grid_view', 17)} Grid`], ['table', h`${icon('table_rows', 17)} Table`]], PS.view)}</div>
      </div>
      <div class="chips" id="cats" style="margin:12px 0">${all.categories.map(function (c) { return h`<span class="chip ${PS.cats[c] ? 'on' : ''}" data-cat="${c}">${c}</span>`; })}</div>
      <div class="grid g2" style="margin-bottom:6px">
        <label class="field"><span>Minimum price <b class="range-val" id="lo-val">${money(lo)}</b></span><input type="range" id="pmin" min="0" max="${ceiling}" step="0.5" value="${lo}"></label>
        <label class="field"><span>Maximum price <b class="range-val" id="hi-val">${money(hi)}</b></span><input type="range" id="pmax" min="0" max="${ceiling}" step="0.5" value="${hi}"></label>
      </div>
      <div id="notes"></div><div id="results"></div>`);
    var load = async function () {
      var cats = Object.keys(PS.cats).filter(function (c) { return PS.cats[c]; });
      var r;
      try { r = await api('/api/products?' + query({ q: PS.q, categories: cats.join(','), min: lo, max: hi })); }
      catch (err) { $('#results', root).innerHTML = String(alertBox('error', err.message)); return; }
      $('#notes', root).innerHTML = String(h`<div class="caption">${r.notes.map(function (n) { return h`<div>${icon('account_tree', 15)} ${n}</div>`; })}${r.products.length} of ${r.total} products</div>`);
      $('#results', root).innerHTML = String(PS.view === 'table' ? productTable(r.products)
        : r.products.length ? h`<div class="pgrid">${r.products.map(productCard)}</div>` : empty('No products match.'));
    };
    var loadSoon = debounce(load, 200);
    $('#q', root).addEventListener('input', function (e) { PS.q = e.target.value; loadSoon(); });
    onSeg(root, 'view', function (v) { PS.view = v; pageProducts(root); });
    $$('#cats .chip', root).forEach(function (chip) {
      chip.addEventListener('click', function () { var c = chip.getAttribute('data-cat'); PS.cats[c] = !PS.cats[c]; chip.classList.toggle('on', PS.cats[c]); load(); });
    });
    var sync = function (which) {
      var a = $('#pmin', root), b = $('#pmax', root);
      if (+a.value > +b.value) { if (which === 'min') b.value = a.value; else a.value = b.value; }
      lo = +a.value; hi = +b.value;
      PS.min = lo === 0 ? null : lo; PS.max = hi >= ceiling ? null : hi;
      $('#lo-val', root).textContent = money(lo); $('#hi-val', root).textContent = money(hi);
      loadSoon();
    };
    $('#pmin', root).addEventListener('input', function () { sync('min'); });
    $('#pmax', root).addEventListener('input', function () { sync('max'); });
    load();
  } else if (PS.tab === 'add') {
    tab.innerHTML = String(productForm({ id: nextId, name: '', category: '', price: 0, quantity: 0, min_stock: 10, demand: null, importance: 3 }, 'add'));
    wireProductForm(root, async function (body) {
      var r = await api('/api/products', { method: 'POST', body: body });
      await changed('Added product ' + r.product.id + ' · ' + r.product.name);
    });
  } else if (!all.products.length) {
    tab.innerHTML = String(card('', empty('No products to ' + PS.tab + '.')));
  } else {
    var key = PS.tab === 'edit' ? 'editId' : 'deleteId';
    if (!all.products.some(function (p) { return p.id === PS[key]; })) PS[key] = all.products[0].id;
    var chosen = all.products.filter(function (p) { return p.id === PS[key]; })[0];
    var picker = h`<label class="field" style="margin-bottom:14px"><span>Product to ${PS.tab}</span><select id="pick">${options(all.products.map(function (p) { return [p.id, p.id + ' · ' + p.name]; }), PS[key])}</select></label>`;
    if (PS.tab === 'edit') {
      tab.innerHTML = String(h`${picker}<div class="caption">${icon('info', 15)} Quantity changes go through Transactions so every change has a history record.</div>${productForm(chosen, 'edit')}`);
      wireProductForm(root, async function (body) {
        await api('/api/products/' + chosen.id, { method: 'PUT', body: body });
        await changed('Updated product ' + chosen.id);
      });
    } else {
      tab.innerHTML = String(h`${picker}<div class="card"><h3>Delete ${chosen.name}?</h3>
        <div class="caption">This also removes the product's transaction history. It cannot be undone.</div>
        <label class="check" style="margin:10px 0"><input type="checkbox" id="sure"> I understand, delete this product</label>
        <div id="del-error"></div>
        <button class="btn danger" id="del" disabled>${icon('delete', 18)}Delete product</button></div>`);
      $('#sure', root).addEventListener('change', function (e) { $('#del', root).disabled = !e.target.checked; });
      $('#del', root).addEventListener('click', async function () {
        try { await api('/api/products/' + chosen.id, { method: 'DELETE' }); await changed('Deleted product ' + chosen.id + ' · ' + chosen.name); }
        catch (err) { $('#del-error', root).innerHTML = String(alertBox('error', err.message)); }
      });
    }
    $('#pick', root).addEventListener('change', function (e) { PS[key] = parseInt(e.target.value, 10); pageProducts(root); });
  }
}

/* ---------------------------------------------------------------- Transactions */
var TS = { product: null };

async function pageTransactions(root) {
  var d = await api('/api/transactions' + (TS.product ? '?product_id=' + TS.product : ''));
  if (!d.products.length) { root.innerHTML = String(h`${pageHead('Transactions', 'Stock in and stock out are saved with their history.')}${card('', empty('Add a product first.'))}`); return; }
  var opts = d.products.map(function (p) { return [p.id, p.id + ' · ' + p.name + ' · stock ' + num(p.quantity)]; });
  var side;
  if (TS.product === null) {
    side = card('Oldest stock', h`<div class="sub">Age of the oldest units still on the shelf, per product, from FIFO lots.</div>${table([
      { label: 'Product', get: function (a) { return a.name; } },
      { label: 'Oldest lot (days)', get: function (a) { return a.oldest_days; }, cls: 'num' },
      { label: 'Lots', get: function (a) { return a.lots; }, cls: 'num' }], d.aging, { empty: 'No stock on hand.' })}`);
  } else {
    var lots = d.lots.lots;
    side = card('Stock lots (FIFO queue)', lots.length ? h`<div class="grid g2 gap-sm">${metric('Lots on hand', lots.length, { icon: 'layers' })}${metric('Oldest stock', lots[0].age_days + ' days', { icon: 'schedule' })}</div>
      <div style="margin:12px 0">${columnsChart(lots.map(function (l) { return { label: shortDate(l.date), value: l.quantity, tip: shortDate(l.date) + ': ' + l.quantity + ' units' }; }), { height: 190, label: 'Units per lot' })}</div>
      ${table([{ label: 'Received', get: function (l) { return l.date; } }, { label: 'Units', get: function (l) { return num(l.quantity); }, cls: 'num' }, { label: 'Age (days)', get: function (l) { return l.age_days; }, cls: 'num' }], lots)}
      <div class="caption">${d.lots.queue_operations} enqueue/dequeue operations. Sales take units from the oldest lot first.</div>`
      : empty('No units on hand, so the queue is empty.'));
  }
  root.innerHTML = String(h`${pageHead('Transactions', 'Stock in and stock out are saved atomically with their history. Stock lots are tracked first-in, first-out with a C circular queue.')}
    <form id="txform" class="card" autocomplete="off"><h3>New transaction</h3>
      <div class="grid g3" style="margin-top:8px">
        <label class="field"><span>Product</span><select name="product_id">${options(opts, TS.product || d.products[0].id)}</select></label>
        <div class="field"><span>Type</span><div class="radio-list"><label><input type="radio" name="type" value="IN" checked> Add stock (IN)</label><label><input type="radio" name="type" value="OUT"> Reduce stock (OUT)</label></div></div>
        <label class="field"><span>Quantity</span><input type="number" name="quantity" min="1" step="1" value="1" required></label>
      </div>
      <label class="field" style="margin-top:10px"><span>Note (optional)</span><input type="text" name="note" maxlength="200" placeholder="e.g. Supplier delivery, customer order"></label>
      <div id="tx-error"></div>
      <div style="margin-top:12px"><button class="btn primary" type="submit">${icon('sync_alt', 18)}Record transaction</button></div>
    </form>
    <label class="field" style="margin:18px 0 12px"><span>Show history for</span><select id="hist"><option value="">All products</option>${options(opts, TS.product)}</select></label>
    <div class="grid g-3-2">${card('History', txTable(d.rows))}${side}</div>`);
  $('#hist', root).addEventListener('change', function (e) { TS.product = e.target.value ? parseInt(e.target.value, 10) : null; pageTransactions(root); });
  $('#txform', root).addEventListener('submit', async function (e) {
    e.preventDefault();
    var f = e.target.elements;
    try {
      var r = await api('/api/transactions', { method: 'POST', body: { product_id: parseInt(f.product_id.value, 10),
        type: f.type.value, quantity: parseInt(f.quantity.value, 10), note: f.note.value } });
      toast((f.type.value === 'IN' ? 'Added ' : 'Removed ') + f.quantity.value + ' × ' + r.product.name + ' · balance ' + num(r.balance));
      TS.product = TS.product === null ? null : parseInt(f.product_id.value, 10);
      await refreshCount();
      pageTransactions(root);
    } catch (err) { $('#tx-error', root).innerHTML = String(alertBox('error', 'Transaction rejected: ' + err.message)); }
  });
}
