/* app.js - navigation, routing and start-up. */
'use strict';

var App = { boot: null, token: 0, scaling: null };

var NAV = [
  ['Overview', [['dashboard', 'Dashboard', 'space_dashboard', pageDashboard]]],
  ['Inventory', [['products', 'Products', 'inventory_2', pageProducts], ['transactions', 'Transactions', 'sync_alt', pageTransactions],
    ['restocking', 'Restocking', 'local_shipping', pageRestock], ['routes', 'Delivery routes', 'route', pageRoutes]]],
  ['Algorithms', [['search-sort', 'Search and sorting', 'manage_search', pageSearchSort], ['lab', 'DSA laboratory', 'science', pageLab],
    ['about', 'About', 'info', pageAbout]]],
];

function routeName() {
  var name = (location.hash || '').replace(/^#\/?/, '') || 'dashboard';
  var known = NAV.some(function (g) { return g[1].some(function (i) { return i[0] === name; }); });
  return known ? name : 'dashboard';
}

function buildSidebar() {
  $('#sidebar').innerHTML = String(h`<img class="logo" src="/assets/logo.svg" alt="StockWise">
    ${NAV.map(function (g) {
      return h`<div class="nav-group">${g[0]}</div>${g[1].map(function (i) { return h`<a class="nav-item" href="#/${i[0]}" data-route="${i[0]}">${icon(i[2], 20)}<span>${i[1]}</span></a>`; })}`;
    })}
    <div class="side-foot">${icon('memory', 18)}<span id="count">…</span></div>`);
}

async function refreshCount() {
  try {
    var s = await api('/api/summary');
    $('#count').textContent = s.products + ' products indexed by the C engine';
  } catch (e) { /* sidebar only */ }
}

async function render() {
  var name = routeName(), token = ++App.token;
  $$('.nav-item').forEach(function (a) { a.classList.toggle('active', a.getAttribute('data-route') === name); });
  var page = null;
  NAV.forEach(function (g) { g[1].forEach(function (i) { if (i[0] === name) page = i; }); });
  var el = document.createElement('div');
  el.innerHTML = '<div class="loading">Loading…</div>';
  var main = $('#main');
  if (!main.firstChild) main.appendChild(el);
  var view = document.createElement('div');
  try { await page[3](view); }
  catch (err) {
    view.innerHTML = String(h`<h1 class="page-title">${page[1]}</h1>${alertBox('error', err.message)}<button class="btn" id="retry">Try again</button>`);
    var retry = view.querySelector('#retry');
    if (retry) retry.addEventListener('click', render);
  }
  if (token !== App.token) return;  // the user already moved on to another page
  main.replaceChildren(view);
  document.title = page[1] + ' · StockWise';
  window.scrollTo(0, 0);
}

async function start() {
  initTooltip();
  try { App.boot = await api('/api/bootstrap'); }
  catch (err) { $('#main').innerHTML = String(alertBox('error', err.message)); return; }
  buildSidebar();
  refreshCount();
  window.addEventListener('hashchange', render);
  render();
}
document.addEventListener('DOMContentLoaded', start);
