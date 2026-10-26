/* pages_plan.js - Restocking, Delivery routes, Search and sorting. */
'use strict';

var RS = { budget: null };

async function pageRestock(root) {
  var d = await api('/api/restock');
  var head = pageHead('Restocking', 'Products at or below minimum stock, ranked by a C Max-Heap. The budget planner solves a 0/1 knapsack with dynamic programming.');
  if (!d.items.length) { root.innerHTML = String(h`${head}${card('', empty('Every product is above its minimum stock. Nothing to restock.'))}`); return; }
  var total = d.total_cost, step = Math.max(Math.floor(total / 100), 1);
  if (RS.budget === null || RS.budget > total) RS.budget = Math.max(Math.floor(total / 2), Math.min(total, 1));
  var ranking = table([
    { label: 'Rank', get: function (p) { return p.rank; }, cls: 'num' },
    { label: 'Product', get: function (p) { return p.name; }, cls: 'nowrap' },
    { label: 'Stock', get: function (p) { return num(p.quantity); }, cls: 'num' },
    { label: 'Min stock', get: function (p) { return num(p.min_stock); }, cls: 'num' },
    { label: 'Priority', get: function (p) { return h`<div class="bar-cell"><div class="track"><div class="fill" style="width:${p.score}%"></div></div><span>${fixed(p.score, 1)}</span></div>`; } },
    { label: 'Reason', get: function (p) { return p.reasons.join('; '); } },
    { label: 'Suggested qty', get: function (p) { return num(p.suggested_qty); }, cls: 'num' },
    { label: 'Cost', get: function (p) { return money(p.cost, 0); }, cls: 'num' },
  ], d.items, { style: 'max-height:430px' });
  var rows = d.items.slice(0, 10).map(function (p) {
    return { label: p.name, parts: [50 * p.shortage_score, 30 * p.demand_score, 20 * p.importance_score] };
  });
  root.innerHTML = String(h`${head}
    <div class="grid g4">
      ${metric('Products to restock', d.items.length, { icon: 'local_shipping' })}
      ${metric('Out of stock', d.out_of_stock, { icon: 'error' })}
      ${metric('Cost to restock all', money(total, 0), { icon: 'shopping_cart', help: num(d.total_units) + ' units in total' })}
      ${metric('Heap operations', num(d.comparisons + d.swaps), { icon: 'account_tree', help: d.comparisons + ' comparisons, ' + d.swaps + ' swaps' })}
    </div>
    <div style="margin-top:18px">${card('Priority ranking', h`${ranking}
      <details><summary>${icon('function', 18)} How the priority score is calculated</summary>
        <p style="margin:10px 0"><b>Priority = 100 × (0.5·S + 0.3·D + 0.2·I)</b></p>
        <ul>
          <li><b>S, shortage</b> = (min stock − quantity) / min stock, clamped to 0..1 (min stock 0: 1 if out of stock, else 0)</li>
          <li><b>D, demand</b> = demand / highest demand in the inventory</li>
          <li><b>I, importance</b> = (importance − 1) / 4 for importance 1..5</li>
          <li>Missing demand or importance uses a neutral <b>0.5</b>.</li>
          <li><b>Suggested quantity</b> = min stock + one month of demand − quantity (2 × min stock − quantity if demand is unknown), at least 1.</li>
        </ul></details>`)}</div>
    <div style="margin-top:18px">${card('Budget planner', h`
      <div class="sub">Not enough money to restock everything? Pick the set of restocks with the highest total priority that fits the budget. Dynamic programming finds the best set; the greedy shortcut (best priority per dollar first) is compared.</div>
      <label class="field"><span>Budget <b class="range-val" id="bval">${money(RS.budget, 0)}</b></span><input type="range" id="budget" min="0" max="${total}" step="${step}" value="${RS.budget}"></label>
      <div id="plan" style="margin-top:12px"></div>`)}</div>
    <div class="grid g-3-2" style="margin-top:18px">
      ${card('Score breakdown', h`${legend([['Shortage', BLUE], ['Demand', ORANGE], ['Importance', AQUA]])}${stackedH(rows, [{ name: 'Shortage', color: BLUE }, { name: 'Demand', color: ORANGE }, { name: 'Importance', color: AQUA }], { label: 'Priority score breakdown' })}<div class="caption" style="text-align:center">Priority points</div>`)}
      ${card('Record a delivery', h`<form id="deliver"><label class="field"><span>Product</span><select name="product_id">${options(d.items.map(function (p) { return [p.id, p.id + ' · ' + p.name + ' · suggested ' + p.suggested_qty]; }))}</select></label>
        <label class="field" style="margin-top:10px"><span>Quantity received</span><input type="number" name="quantity" min="0" step="1" value="0"></label>
        <div class="caption">Leave at 0 to use the suggested quantity.</div><div id="deliver-error"></div>
        <button class="btn primary" type="submit">${icon('local_shipping', 18)}Record delivery</button></form>`)}
    </div>`);

  var showPlan = async function () {
    var box = $('#plan', root), p;
    try { p = await api('/api/restock/plan?budget=' + RS.budget); } catch (err) { box.innerHTML = String(alertBox('error', err.message)); return; }
    if (p.error) { box.innerHTML = String(alertBox('error', p.error)); return; }
    var items = table([
      { label: 'Product', get: function (i) { return i.name; } },
      { label: 'Cost', get: function (i) { return money(i.cost, 0); }, cls: 'num' },
      { label: 'Priority', get: function (i) { return fixed(i.score, 1); }, cls: 'num' },
      { label: 'Priority per $', get: function (i) { return i.per_dollar === null ? '–' : fixed(i.per_dollar, 3); }, cls: 'num' },
      { label: 'DP plan', get: function (i) { return i.dp ? h`<span class="badge green">${icon('check_circle', 15)}Selected</span>` : ''; } },
      { label: 'Greedy plan', get: function (i) { return i.greedy ? h`<span class="badge blue">${icon('check_circle', 15)}Selected</span>` : ''; } },
    ], p.items, { style: 'max-height:340px', rowClass: function (i) { return i.dp ? 'hl' : ''; } });
    var gap = p.dp.value - p.greedy.value;
    box.innerHTML = String(h`<div class="grid g4">
      ${metric('DP priority covered', fixed(p.dp.value, 1), { icon: 'grid_on', delta: (gap >= 0 ? '+' : '') + fixed(gap, 1) + ' vs greedy' })}
      ${metric('Greedy priority covered', fixed(p.greedy.value, 1), { icon: 'bolt' })}
      ${metric('DP plan cost', money(p.dp.cost, 0), { icon: 'payments', help: money(p.budget - p.dp.cost, 0) + ' of the budget left over' })}
      ${metric('DP cells evaluated', num(p.dp.cells), { icon: 'table', help: 'n × (budget + 1) at most' })}
    </div><div style="margin:12px 0">${items}</div>
    <div id="order-error"></div>
    <button class="btn primary" id="order" ${p.items.some(function (i) { return i.dp; }) ? '' : raw('disabled')}>${icon('shopping_cart', 18)}Order the DP plan</button>`);
    $('#order', root).addEventListener('click', async function () {
      try {
        var r = await api('/api/restock/order', { method: 'POST', body: { budget: RS.budget } });
        toast('Recorded ' + r.ordered + ' deliveries costing ' + money(r.cost, 0));
        await refreshCount(); pageRestock(root);
      } catch (err) { $('#order-error', root).innerHTML = String(alertBox('error', err.message)); }
    });
  };
  var planSoon = debounce(showPlan, 120);
  $('#budget', root).addEventListener('input', function (e) {
    RS.budget = parseInt(e.target.value, 10); $('#bval', root).textContent = money(RS.budget, 0); planSoon();
  });
  showPlan();
  $('#deliver', root).addEventListener('submit', async function (e) {
    e.preventDefault();
    var f = e.target.elements, qty = parseInt(f.quantity.value, 10) || 0;
    var item = d.items.filter(function (p) { return p.id === parseInt(f.product_id.value, 10); })[0];
    try {
      var r = await api('/api/transactions', { method: 'POST', body: { product_id: item.id, type: 'IN', quantity: qty || item.suggested_qty, note: 'Restock' } });
      toast('Added ' + (qty || item.suggested_qty) + ' units to ' + item.name + ' · now ' + num(r.balance));
      await refreshCount(); pageRestock(root);
    } catch (err) { $('#deliver-error', root).innerHTML = String(alertBox('error', err.message)); }
  });
}

/* ---------------------------------------------------------------- Delivery routes */
var RT = { from: 0, to: 7 };

async function pageRoutes(root) {
  var boot = App.boot, names = boot.locations.map(function (l) { return l[0]; });
  var pickList = names.map(function (n, i) { return [i, n]; });
  root.innerHTML = String(h`${pageHead('Delivery routes', "Shortest delivery routes between the warehouse and branches, found with Dijkstra's algorithm in C.")}
    <div class="grid g2"><label class="field"><span>From</span><select id="from">${options(pickList, RT.from)}</select></label>
    <label class="field"><span>To</span><select id="to">${options(pickList, RT.to)}</select></label></div>
    <div id="route" style="margin-top:16px"></div>`);
  var show = async function () {
    var r = await api('/api/routes?' + query({ from: RT.from, to: RT.to }));
    var reachable = r.path.length > 0;
    var dist = names.map(function (n, i) { return { name: n, km: r.distances[i], i: i }; }).filter(function (x) { return x.i !== RT.from; })
      .sort(function (a, b) { return (a.km === null ? 1e9 : a.km) - (b.km === null ? 1e9 : b.km); });
    $('#route', root).innerHTML = String(h`<div class="grid g4">
      ${metric('Distance', reachable ? r.distances[RT.to] + ' km' : 'Unreachable', { icon: 'route' })}
      ${metric('Stops on the way', Math.max(r.path.length - 2, 0), { icon: 'location_on' })}
      ${metric('Edges relaxed', r.relaxations, { icon: 'call_split' })}
      ${metric('Heap comparisons', r.comparisons, { icon: 'account_tree' })}
    </div>
    ${reachable ? h`<div class="flow-badges">${r.path.map(function (n, i) { return h`${i ? icon('arrow_forward', 18) : ''}<span class="badge blue">${names[n]}</span>`; })}</div>` : ''}
    <div class="grid g-3-2" style="margin-top:12px">
      ${card('Network', h`<div class="sub">Road distances in km. Each node shows its shortest distance from the start.</div>${networkSvg(boot.locations, boot.routes, r.path, r.distances)}`)}
      ${card('Distances from ' + names[RT.from], h`${table([{ label: 'Location', get: function (x) { return x.name; } }, { label: 'Distance (km)', get: function (x) { return x.km === null ? '–' : x.km; }, cls: 'num' }], dist)}<div class="caption">Dijkstra settles the closest unsettled location each round, so one run gives the shortest distance to every location.</div>`)}
    </div>`);
  };
  $('#from', root).addEventListener('change', function (e) { RT.from = +e.target.value; show(); });
  $('#to', root).addEventListener('change', function (e) { RT.to = +e.target.value; show(); });
  await show();
}

/* ---------------------------------------------------------------- Search and sorting */
var SS = { method: 'hash', id: 1042, q: 'ca', min: 2, max: 8, key: 'name', algo: 'merge', desc: false };

async function pageSearchSort(root) {
  var algos = App.boot.algorithms;
  var methods = [['hash', 'Hash table', 'O(1) average, by ID'], ['binary', 'Binary search', 'O(log n), id-sorted index'],
    ['linear', 'Linear search', 'O(n), by ID'], ['trie', 'Trie prefix', 'O(P + k), by name prefix'],
    ['substring', 'Linear substring', 'O(n), name contains text'], ['range', 'AVL price range', 'O(log n + k), by price']];
  var input = function () {
    if (SS.method === 'trie' || SS.method === 'substring') return h`<label class="field"><span>${SS.method === 'trie' ? 'Name prefix' : 'Name contains'}</span><input type="text" id="sq" value="${SS.q}" placeholder="e.g. cable"></label>`;
    if (SS.method === 'range') return h`<div class="grid g2 gap-sm"><label class="field"><span>Minimum price ($)</span><input type="number" id="smin" step="0.5" min="0" value="${SS.min}"></label><label class="field"><span>Maximum price ($)</span><input type="number" id="smax" step="0.5" min="0" value="${SS.max}"></label></div>`;
    return h`<label class="field"><span>Product ID</span><input type="number" id="sid" min="1" step="1" value="${SS.id}"></label>`;
  };
  root.innerHTML = String(h`${pageHead('Search and sorting', 'Run the C search and sort algorithms on the live catalog and compare the work each one does.')}
    <div class="card"><h3>Search</h3><div class="grid g-3-2" style="grid-template-columns:minmax(0,1fr) minmax(0,2fr);gap:28px;margin-top:8px">
      <div class="radio-list">${methods.map(function (m) { return h`<label><input type="radio" name="method" value="${m[0]}" ${SS.method === m[0] ? raw('checked') : ''}> ${m[1]}<small>${m[2]}</small></label>`; })}</div>
      <div>${input()}<div id="sresult" style="margin-top:12px"></div></div></div></div>
    <div class="card" style="margin-top:18px"><h3>Sort</h3>
      <div class="grid g3" style="margin:8px 0 14px">
        <label class="field"><span>Sort by</span><select id="skey">${options([['name', 'Name'], ['price', 'Price'], ['quantity', 'Quantity'], ['value', 'Value']], SS.key)}</select></label>
        <label class="field"><span>Algorithm</span><select id="salgo">${options(algos.map(function (a) { return [a.key, a.name]; }), SS.algo)}</select></label>
        <div class="field"><span>Order</span>${segmented('order', [['asc', 'Ascending'], ['desc', 'Descending']], SS.desc ? 'desc' : 'asc')}</div></div>
      <div id="sorted"></div></div>`);
  var runSearch = async function () {
    var box = $('#sresult', root);
    try {
      var r = await api('/api/search?' + query({ method: SS.method, id: SS.id, q: SS.q, min: SS.min, max: SS.max }));
      if (r.empty) { box.innerHTML = ''; return; }
      box.innerHTML = String(h`<div style="max-width:300px">${metric(r.label, r.work, { icon: 'compare_arrows' })}</div><div style="margin-top:12px">
        ${r.products.length ? productTable(r.products, true) : alertBox('warn', SS.method === 'hash' || SS.method === 'binary' || SS.method === 'linear' ? 'Product ' + r.searched + ' was not found.' : 'No products match.')}</div>`);
    } catch (err) { box.innerHTML = String(alertBox('error', err.message)); }
  };
  var runSort = async function () {
    var box = $('#sorted', root);
    try {
      var r = await api('/api/sort?' + query({ key: SS.key, algo: SS.algo, desc: SS.desc ? 1 : '' }));
      box.innerHTML = String(h`<div class="grid g4">
        ${metric('Comparisons', num(r.comparisons), { icon: 'compare_arrows' })}${metric('Element moves', num(r.moves), { icon: 'swap_vert' })}
        ${metric('Time complexity', r.complexity, { icon: 'timer' })}${metric('Stable', r.stable ? 'Yes' : 'No', { icon: 'balance', help: 'A stable sort keeps equal keys in their original order.' })}</div>
        <div style="margin-top:12px">${productTable(r.products)}</div>`);
    } catch (err) { box.innerHTML = String(alertBox('error', err.message)); }
  };
  var searchSoon = debounce(runSearch, 200);
  $$('input[name=method]', root).forEach(function (r) { r.addEventListener('change', function () { SS.method = r.value; pageSearchSort(root); }); });
  var bind = function (id, key, parse) { var el = $(id, root); if (el) el.addEventListener('input', function (e) { SS[key] = parse(e.target.value); searchSoon(); }); };
  bind('#sid', 'id', function (v) { return parseInt(v, 10) || 1; });
  bind('#sq', 'q', function (v) { return v; });
  bind('#smin', 'min', function (v) { return parseFloat(v) || 0; });
  bind('#smax', 'max', function (v) { return parseFloat(v) || 0; });
  $('#skey', root).addEventListener('change', function (e) { SS.key = e.target.value; runSort(); });
  $('#salgo', root).addEventListener('change', function (e) { SS.algo = e.target.value; runSort(); });
  onSeg(root, 'order', function (v) { SS.desc = v === 'desc'; $$('[data-seg=order] button', root).forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-value') === v); }); runSort(); });
  await Promise.all([runSearch(), runSort()]);
}
