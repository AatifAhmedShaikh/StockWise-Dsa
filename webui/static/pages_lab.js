/* pages_lab.js - DSA laboratory and About. */
'use strict';

var LB = { source: 'real', n: 200, seed: 42, buckets: 0, tab: 'search', id: null, key: 'price',
  min: null, max: null, prefix: 's', budget: 7,
  items: [{ name: 'Cables', cost: 1, value: 1 }, { name: 'Rice', cost: 3, value: 4 }, { name: 'Soap', cost: 4, value: 5 }, { name: 'Juice', cost: 5, value: 7 }] };

function labQuery(extra) {
  var p = { source: LB.source, n: LB.n, seed: LB.seed, buckets: LB.buckets };
  Object.keys(extra || {}).forEach(function (k) { p[k] = extra[k]; });
  return query(p);
}
function badgeResult(ok) {
  return ok ? h`<span class="badge green">${icon('check_circle', 15)}Passed</span>` : h`<span class="badge red">${icon('error', 15)}Failed</span>`;
}

var LAB_TABS = {
  async search(el) {
    var r = await api('/api/lab/search?' + labQuery({ id: LB.id }));
    el.innerHTML = String(h`<label class="field" style="max-width:420px"><span>Target product ID (try a missing one too)</span><input type="number" id="lid" min="1" step="1" value="${r.id}"></label>
      <div class="grid g-3-2" style="margin-top:14px">${table([
        { label: 'Algorithm', get: function (x) { return x.algorithm; } },
        { label: 'Result', get: function (x) { return x.found ? h`<span class="badge green">Found</span>` : h`<span class="badge orange">Not found</span>`; } },
        { label: 'Product', get: function (x) { return x.product || '–'; } },
        { label: 'Comparisons', get: function (x) { return num(x.comparisons); }, cls: 'num' },
        { label: 'Complexity', get: function (x) { return x.complexity; } }], r.rows)}
        ${columnsChart(r.rows.map(function (x) { return { label: x.algorithm, value: x.comparisons }; }), { height: 230, label: 'Comparisons per algorithm' })}</div>`);
    $('#lid', el).addEventListener('input', debounce(function (e) { LB.id = parseInt(e.target.value, 10) || null; LAB_TABS.search(el); }, 400));
  },

  async sorting(el) {
    var results = await Promise.all([api('/api/lab/sort?' + labQuery({ key: LB.key })), App.scaling || api('/api/lab/scaling')]);
    var r = results[0]; App.scaling = results[1];
    var groups = {};
    App.scaling.points.forEach(function (p) { (groups[p.algorithm] = groups[p.algorithm] || []).push({ x: p.n, y: p.comparisons }); });
    var series = Object.keys(groups).map(function (name, i) { return { name: name, color: SERIES[i % SERIES.length], points: groups[name] }; });
    el.innerHTML = String(h`<label class="field" style="max-width:280px"><span>Sort key</span><select id="lkey">${options([['price', 'Price'], ['name', 'Name'], ['quantity', 'Quantity'], ['value', 'Value']], LB.key)}</select></label>
      <div style="margin:14px 0">${table([
        { label: 'Algorithm', get: function (x) { return x.algorithm; } }, { label: 'Comparisons', get: function (x) { return num(x.comparisons); }, cls: 'num' },
        { label: 'Moves', get: function (x) { return num(x.moves); }, cls: 'num' }, { label: 'Stable', get: function (x) { return x.stable ? 'Yes' : 'No'; } },
        { label: 'Time', get: function (x) { return x.time; } }], r.rows)}</div>
      <div class="caption">${icon(r.same_order ? 'check_circle' : 'error', 16)} ${r.same_order ? 'All four algorithms produced the same key order' : 'The key orders differ'}</div>
      ${card('Scaling experiment', h`<div class="sub">Comparisons needed to sort random data by price as n grows (logarithmic axis).</div>${lineLog(series, { label: 'Sorting comparisons by n' })}`)}`);
    $('#lkey', el).addEventListener('change', function (e) { LB.key = e.target.value; LAB_TABS.sorting(el); });
  },

  async hash(el) {
    var s = await api('/api/lab/hash?' + labQuery());
    el.innerHTML = String(h`<div class="grid g5">${metric('Buckets (m)', num(s.bucket_count))}${metric('Items (n)', num(s.item_count))}${metric('Load factor', fixed(s.load_factor, 2))}${metric('Collisions', num(s.collisions))}${metric('Longest chain', num(s.longest_chain))}</div>
      <div class="caption">hash(id) = id mod m. A collision is an item stored in a bucket that already had one. Set a small bucket count to force collisions.</div>
      ${card('Chain length per bucket', columnsChart(s.chain_lengths.map(function (v, i) { return { label: String(i), value: v, tip: 'Bucket ' + i + ': ' + v + ' item(s)' }; }), { width: 900, height: 250, values: false, label: 'Chain lengths' }))}`);
  },

  async heap(el) {
    var r = await api('/api/lab/heap?' + labQuery());
    if (!r.count) { el.innerHTML = String(empty('No product is at or below its minimum stock.')); return; }
    el.innerHTML = String(h`<div class="caption">${r.count} candidates · ${r.comparisons} comparisons · ${r.swaps} swaps</div>
      ${card('Heap as a tree', h`<div class="sub">Labelled id / score. The root is the most urgent product.</div><div style="overflow:auto">${treeSvg(r.tree, { label: 'Max-heap' })}</div>`)}
      <div class="grid g2" style="margin-top:18px">${card('Heap array', h`<div class="sub">Level order, after all pushes</div>${table([
        { label: 'Index', get: function (x) { return x.index; }, cls: 'num' }, { label: 'Parent', get: function (x) { return x.parent === null ? '–' : x.parent; }, cls: 'num' },
        { label: 'ID', get: function (x) { return x.id; }, cls: 'num' }, { label: 'Score', get: function (x) { return fixed(x.score, 2); }, cls: 'num' }], r.heap, { style: 'max-height:340px' })}`)}
        ${card('Extraction order', h`<div class="sub">Repeated extract-max</div>${table([
          { label: 'Rank', get: function (x) { return x.rank; }, cls: 'num' }, { label: 'ID', get: function (x) { return x.id; }, cls: 'num' },
          { label: 'Name', get: function (x) { return x.name; } }, { label: 'Score', get: function (x) { return fixed(x.score, 2); }, cls: 'num' }], r.ranking, { style: 'max-height:340px' })}`)}</div>`);
  },

  async avl(el) {
    var r = await api('/api/lab/avl?' + labQuery({ min: LB.min, max: LB.max }));
    var s = r.stats;
    var caption = function (x) { return x.matches + ' products in range · ' + x.visited + ' of ' + x.count + ' nodes visited (linear search would check all ' + x.count + ')'; };
    el.innerHTML = String(h`<div class="grid g4">${metric('Nodes', num(s.avl_nodes))}${metric('Height', s.avl_height, { help: 'A single node has height 1' })}${metric('Best possible height', r.ideal_height, { help: '⌈log₂(n + 1)⌉' })}${metric('Rotations while building', num(s.avl_rotations))}</div>
      <div class="grid g2" style="margin-top:14px">
        <label class="field"><span>Minimum price <b class="range-val" id="avl-lo-v">${money(r.min)}</b></span><input type="range" id="avl-lo" min="0" max="${r.ceiling}" step="0.5" value="${r.min}"></label>
        <label class="field"><span>Maximum price <b class="range-val" id="avl-hi-v">${money(r.max)}</b></span><input type="range" id="avl-hi" min="0" max="${r.ceiling}" step="0.5" value="${r.max}"></label></div>
      <div class="caption" id="avl-cap">${caption(r)}</div>
      ${r.tree.length ? card('Tree, top 5 levels', h`<div class="sub">Keyed by price. Left subtree cheaper, right subtree dearer.</div><div style="overflow:auto">${treeSvg(r.tree, { label: 'AVL tree' })}</div>`) : empty('The tree is empty.')}`);
    var lo = $('#avl-lo', el), hi = $('#avl-hi', el);
    var update = debounce(async function () {
      var q = await api('/api/lab/avl?' + labQuery({ min: LB.min, max: LB.max }));
      $('#avl-cap', el).textContent = caption(q);
    }, 150);
    var sync = function (which) {
      if (+lo.value > +hi.value) { if (which === 'lo') hi.value = lo.value; else lo.value = hi.value; }
      LB.min = +lo.value; LB.max = +hi.value;
      $('#avl-lo-v', el).textContent = money(LB.min); $('#avl-hi-v', el).textContent = money(LB.max); update();
    };
    lo.addEventListener('input', function () { sync('lo'); });
    hi.addEventListener('input', function () { sync('hi'); });
  },

  async trie(el) {
    var draw = async function () {
      var r = await api('/api/lab/trie?' + labQuery({ prefix: LB.prefix }));
      var out = r.trie ? h`<div class="grid g-3-2" style="grid-template-columns:minmax(0,2fr) minmax(0,3fr);margin-top:14px"><div>${table([
        { label: 'Method', get: function (x) { return x.m; } }, { label: 'Work', get: function (x) { return num(x.work); }, cls: 'num' }, { label: 'Matches', get: function (x) { return num(x.matches); }, cls: 'num' }],
        [{ m: 'Trie prefix', work: r.trie.work, matches: r.trie.matches }, { m: 'Linear substring', work: r.linear.work, matches: r.linear.matches }])}
        <div class="caption">Trie work counts nodes visited; linear work counts names checked. Substring search also matches text inside words.</div></div>
        <div>${table([{ label: 'Suggestion', get: function (x) { return x.name; } }, { label: 'ID', get: function (x) { return x.id; }, cls: 'num' }], r.suggestions, { empty: 'No suggestions.', style: 'max-height:300px' })}</div></div>` : '';
      $('#trie-out', el).innerHTML = String(out);
      return r;
    };
    var first = await api('/api/lab/trie?' + labQuery({ prefix: LB.prefix })), s = first.stats;
    el.innerHTML = String(h`<div class="grid g3">${metric('Trie nodes', num(s.trie_nodes))}${metric('Keys inserted', num(s.trie_keys), { help: 'One key per word start of every name' })}${metric('Products', num(first.count))}</div>
      <label class="field" style="max-width:360px;margin-top:14px"><span>Prefix</span><input type="text" id="tprefix" value="${LB.prefix}"></label><div id="trie-out"></div>`);
    $('#tprefix', el).addEventListener('input', debounce(function (e) { LB.prefix = e.target.value; draw(); }, 250));
    await draw();
  },

  async knapsack(el) {
    var drawOut = async function () {
      var box = $('#ks-out', el);
      try {
        var r = await api('/api/lab/knapsack', { method: 'POST', body: { items: LB.items, budget: LB.budget } });
        var pick = function (idx) { return idx.length ? idx.map(function (i) { return r.names[i]; }).join(', ') : 'nothing'; };
        var gap = r.greedy.value - r.dp.value;
        box.innerHTML = String(h`<div class="grid g3">${metric('DP best priority', fixed(r.dp.value, 1))}${metric('Greedy priority', fixed(r.greedy.value, 1), { delta: (gap >= 0 ? '+' : '') + fixed(gap, 1) + ' vs DP' })}${metric('Cells evaluated', num(r.dp.cells))}</div>
          <p style="margin:12px 0"><b>DP picks:</b> ${pick(r.dp.chosen)} &nbsp; <b>Greedy picks:</b> ${pick(r.greedy.chosen)}</p>
          ${card('DP table', h`<div class="sub">dp[i][w] is the best priority using the first i items with budget w.</div><div style="overflow:auto">${heatmap(['(none)'].concat(r.names), r.dp.table[0].map(function (_, w) { return String(w); }), r.dp.table, { label: 'Knapsack DP table' })}</div>`)}`);
      } catch (err) { box.innerHTML = String(alertBox('error', err.message)); }
    };
    var drawItems = function () {
      $('#ks-items', el).innerHTML = String(h`<div class="table-wrap"><table class="editable"><thead><tr><th>Item</th><th>Cost</th><th>Priority</th><th></th></tr></thead><tbody>
        ${LB.items.map(function (it, i) { return h`<tr><td><input type="text" data-i="${i}" data-f="name" value="${it.name}"></td><td><input type="number" min="0" max="1000" step="1" data-i="${i}" data-f="cost" value="${it.cost}"></td>
          <td><input type="number" min="0" step="0.5" data-i="${i}" data-f="value" value="${it.value}"></td><td><button class="btn small" data-del="${i}" title="Remove">${icon('close', 16)}</button></td></tr>`; })}</tbody></table></div>
        <div style="margin-top:8px"><button class="btn small" id="ks-add">${icon('add', 16)}Add item</button></div>`);
      $$('[data-f]', el).forEach(function (inp) {
        inp.addEventListener('input', debounce(function () {
          var it = LB.items[+inp.getAttribute('data-i')], f = inp.getAttribute('data-f');
          it[f] = f === 'name' ? inp.value : (inp.value === '' ? 0 : parseFloat(inp.value)); drawOut();
        }, 250));
      });
      $$('[data-del]', el).forEach(function (b) { b.addEventListener('click', function () { LB.items.splice(+b.getAttribute('data-del'), 1); drawItems(); drawOut(); }); });
      $('#ks-add', el).addEventListener('click', function () { LB.items.push({ name: 'Item ' + (LB.items.length + 1), cost: 1, value: 1 }); drawItems(); drawOut(); });
    };
    el.innerHTML = String(h`<div class="caption">Edit the items and budget. Each cell dp[i][w] is the best priority using the first i items with budget w.</div><div id="ks-items"></div>
      <label class="field" style="max-width:420px;margin:14px 0"><span>Budget <b class="range-val" id="ks-bv">${LB.budget}</b></span><input type="range" id="ks-budget" min="0" max="20" step="1" value="${LB.budget}"></label><div id="ks-out"></div>`);
    drawItems();
    $('#ks-budget', el).addEventListener('input', function (e) { LB.budget = +e.target.value; $('#ks-bv', el).textContent = LB.budget; drawOut(); });
    await drawOut();
  },

  async edge(el) {
    var r = await api('/api/lab/edge'), passed = r.cases.filter(function (c) { return c.Result === 'Passed'; }).length;
    el.innerHTML = String(h`<div class="caption">${passed} of ${r.cases.length} checks passed. These run live against the C engine and a scratch database.</div>${table([
      { label: 'Case', get: function (c) { return c.Case; } }, { label: 'Expected', get: function (c) { return c.Expected; } },
      { label: 'Actual', get: function (c) { return c.Actual; } }, { label: 'Result', get: function (c) { return badgeResult(c.Result === 'Passed'); } }], r.cases)}`);
  },

  async code(el) {
    var boot = App.boot;
    el.innerHTML = String(h`${complexityTable()}${Object.keys(boot.pseudocode).map(function (name) { return h`<details><summary>${icon('code', 18)} ${name}</summary><pre>${boot.pseudocode[name]}</pre></details>`; })}`);
  },
};

function complexityTable() {
  var c = App.boot.complexity;
  return table(c.columns.map(function (name, i) { return { label: name, get: function (r) { return r[i]; }, cls: '' }; }), c.rows, { style: 'max-height:none' });
}

async function pageLab(root) {
  var generated = LB.source === 'generated';
  var tabs = [['search', 'Search', 'search'], ['sorting', 'Sorting', 'sort'], ['hash', 'Hash table', 'tag'], ['heap', 'Max-Heap', 'account_tree'],
    ['avl', 'AVL tree', 'park'], ['trie', 'Trie', 'spellcheck'], ['knapsack', 'Knapsack DP', 'grid_on'], ['edge', 'Edge cases', 'rule'], ['code', 'Pseudocode', 'code']];
  root.innerHTML = String(h`${pageHead('DSA laboratory', 'Experiment with the C data structures on real or generated inventory data.')}
    <div class="card"><div class="grid g4">
      <div class="field"><span>Data</span>${segmented('source', [['real', 'Real inventory'], ['generated', 'Generated']], LB.source)}</div>
      <label class="field"><span>Sample size</span><input type="number" id="ln" min="0" max="5000" step="50" value="${LB.n}" ${generated ? '' : raw('disabled')}></label>
      <label class="field"><span>Random seed</span><input type="number" id="lseed" min="0" max="10000" value="${LB.seed}" ${generated ? '' : raw('disabled')}></label>
      <label class="field"><span>Hash buckets (0 = auto)</span><input type="number" id="lbuckets" min="0" max="100000" value="${LB.buckets}"></label></div></div>
    <div style="margin-top:18px">${tabsBar(tabs, LB.tab)}<div id="lab-tab"><div class="loading">Running in C…</div></div></div>`);
  var el = $('#lab-tab', root);
  var run = async function () {
    el.innerHTML = '<div class="loading">Running in C…</div>';
    try { await LAB_TABS[LB.tab](el); } catch (err) { el.innerHTML = String(alertBox('error', err.message)); }
  };
  onSeg(root, 'source', function (v) { LB.source = v; pageLab(root); });
  onTabs(root, function (t) { LB.tab = t; pageLab(root); });
  var again = debounce(function () { LB.id = null; LB.min = null; LB.max = null; run(); }, 450);
  [['#ln', 'n'], ['#lseed', 'seed'], ['#lbuckets', 'buckets']].forEach(function (pair) {
    $(pair[0], root).addEventListener('input', function (e) { LB[pair[1]] = parseInt(e.target.value, 10) || 0; again(); });
  });
  await run();
}

/* ---------------------------------------------------------------- About */
async function pageAbout(root) {
  root.innerHTML = String(h`${pageHead('About', 'How StockWise is built and what each algorithm costs.')}
    ${card('Architecture', h`<img src="/assets/architecture.svg" alt="Architecture diagram: browser, Python web server, ctypes bridge, C engine and SQLite" style="width:100%;border-radius:10px">
      <p style="margin-top:12px">SQLite is the single source of truth. For every request, <code>Engine(products)</code> copies the records into C, which builds a hash index, an id-sorted index, an AVL tree by price and a trie of name prefixes. The planning algorithms (knapsack, Dijkstra, FIFO queue) are stateless C functions that work on arrays Python passes in. The page you are looking at is served by Python's built-in web server and draws its charts as plain SVG, so nothing needs installing.</p>`)}
    <div style="margin-top:18px">${card('Complexity', complexityTable())}</div>
    <div style="margin-top:18px">${card('Where each concept is used', h`<ul style="margin:0;padding-left:20px;line-height:1.9;columns:2">
        <li><b>Hash table</b>: product lookup by ID</li><li><b>Binary / linear search</b>: ID search comparison</li>
        <li><b>Trie</b>: name autocomplete</li><li><b>AVL tree</b>: price range filter</li>
        <li><b>Merge, Insertion, Quick, Heap Sort</b>: sorted views</li><li><b>Max-Heap</b>: restock priority queue</li>
        <li><b>0/1 Knapsack (DP)</b>: budget restock plan</li><li><b>Graph + Dijkstra</b>: delivery routes</li>
        <li><b>Circular queue</b>: FIFO stock lots and stock age</li></ul>
        <p style="margin-top:12px"><b>Priority = 100 × (0.5·S + 0.3·D + 0.2·I)</b></p>`)}</div>`);
}
