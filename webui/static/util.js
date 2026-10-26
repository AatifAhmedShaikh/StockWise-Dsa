/* util.js - small helpers shared by every page. No libraries. */
'use strict';

/* ---- safe HTML templates: every interpolated value is escaped unless wrapped with raw() ---- */
function Raw(s) { this.s = s; }
Raw.prototype.toString = function () { return this.s; };
function raw(s) { return new Raw(String(s)); }
function esc(v) {
  return String(v).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function part(v) {
  if (v === null || v === undefined || v === false) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(part).join('');
  return esc(v);
}
function h(strings) {
  var out = '';
  for (var i = 0; i < strings.length; i++) {
    out += strings[i];
    if (i + 1 < strings.length) out += part(arguments[i + 1]);
  }
  return new Raw(out);
}

var $ = function (sel, root) { return (root || document).querySelector(sel); };
var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

/* ---- formatting ---- */
function num(n) { return Number(n).toLocaleString('en-US'); }
function money(n, digits) {
  var d = digits === undefined ? 2 : digits;
  return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
function fixed(n, d) { return Number(n).toFixed(d === undefined ? 1 : d); }
function shortDate(iso) {
  var p = iso.split('-');
  return ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][+p[1] - 1] + ' ' + (+p[2]);
}

/* ---- icons (paths come from icons.js) ---- */
function icon(name, size) {
  var s = size || 20, paths = window.ICON_PATHS[name] || [];
  return raw('<svg class="icon" width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    paths.map(function (d) { return '<path d="' + d + '"/>'; }).join('') + '</svg>');
}

/* ---- API ---- */
async function api(path, options) {
  var opts = options || {};
  var init = { method: opts.method || 'GET', headers: {} };
  if (init.method !== 'GET') {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body || {});
  }
  var res;
  try { res = await fetch(path, init); } catch (e) { throw new Error('Cannot reach the StockWise server. Is it still running?'); }
  var data = null;
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) throw new Error((data && data.error) || ('Request failed (' + res.status + ')'));
  return data;
}
function query(params) {
  return Object.keys(params).filter(function (k) { return params[k] !== undefined && params[k] !== null && params[k] !== ''; })
    .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
}
function debounce(fn, ms) {
  var t;
  return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms); };
}

/* ---- toasts and tooltips ---- */
function toast(message, kind) {
  var box = $('#toasts'), el = document.createElement('div');
  el.className = 'toast' + (kind === 'error' ? ' error' : '');
  el.innerHTML = String(h`${icon(kind === 'error' ? 'error' : 'check_circle', 20)}<span>${message}</span>`);
  box.appendChild(el);
  setTimeout(function () { el.remove(); }, kind === 'error' ? 6000 : 3500);
}
function initTooltip() {
  var tip = $('#tooltip');
  document.addEventListener('mousemove', function (e) {
    var t = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!t) { tip.style.display = 'none'; return; }
    tip.textContent = t.getAttribute('data-tip');
    tip.style.display = 'block';
    var x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + 'px';
    tip.style.top = Math.min(e.clientY + 16, window.innerHeight - tip.offsetHeight - 8) + 'px';
  });
}

/* ---- reusable pieces ---- */
var STATUS = {
  'Out of stock': { cls: 'red', icon: 'error' },
  'Low stock': { cls: 'orange', icon: 'warning' },
  'In stock': { cls: 'green', icon: 'check_circle' },
};
function badge(status) {
  var s = STATUS[status] || STATUS['In stock'];
  return h`<span class="badge ${s.cls}">${icon(s.icon, 15)}${status}</span>`;
}
function categoryImage(category) {
  var slug = String(category).trim().toLowerCase().replace(/\s+/g, '-');
  var known = ['electronics', 'grocery', 'stationery', 'cleaning', 'beverages', 'personal-care'];
  return '/assets/categories/' + (known.indexOf(slug) >= 0 ? slug : 'other') + '.svg';
}
function metric(label, value, o) {
  var opt = o || {};
  return h`<div class="metric"${opt.help ? raw(' title="' + esc(opt.help) + '"') : ''}>
    <div class="label">${opt.icon ? icon(opt.icon, 18) : ''}${label}</div>
    <div class="value">${value}</div>
    ${opt.delta ? h`<span class="delta">${opt.delta}</span>` : ''}
    ${opt.note ? h`<div class="note">${opt.note}</div>` : ''}
    ${opt.extra || ''}</div>`;
}
function card(title, body, o) {
  var opt = o || {};
  return h`<div class="card ${opt.cls || ''}">${title ? h`<h3>${title}</h3>` : ''}${opt.sub ? h`<div class="sub">${opt.sub}</div>` : ''}${body}</div>`;
}
function empty(message) {
  return h`<div class="empty"><img src="/assets/empty.svg" alt="">${message}</div>`;
}
function alertBox(kind, message) {
  return h`<div class="alert ${kind}">${icon(kind === 'error' ? 'error' : kind === 'warn' ? 'warning' : 'info', 20)}<div>${message}</div></div>`;
}
/* columns: [{label, get(row) -> value|Raw, cls}] */
function table(columns, rows, o) {
  var opt = o || {};
  if (!rows.length) return empty(opt.empty || 'Nothing to show.');
  return h`<div class="table-wrap" ${opt.style ? raw('style="' + esc(opt.style) + '"') : ''}><table>
    <thead><tr>${columns.map(function (c) { return h`<th class="${c.cls || ''}">${c.label}</th>`; })}</tr></thead>
    <tbody>${rows.map(function (r, i) {
      return h`<tr class="${opt.rowClass ? opt.rowClass(r, i) : ''}">${columns.map(function (c) { return h`<td class="${c.cls || ''}">${c.get(r, i)}</td>`; })}</tr>`;
    })}</tbody></table></div>`;
}
function segmented(name, options, value) {
  return h`<div class="seg" data-seg="${name}">${options.map(function (o) {
    return h`<button type="button" data-value="${o[0]}" class="${o[0] === value ? 'on' : ''}">${o[1]}</button>`;
  })}</div>`;
}
function tabsBar(options, value) {
  return h`<div class="tabs">${options.map(function (o) {
    return h`<button type="button" data-tab="${o[0]}" class="${o[0] === value ? 'on' : ''}">${o[2] ? icon(o[2], 18) : ''}${o[1]}</button>`;
  })}</div>`;
}
function options(list, selected) {
  return list.map(function (o) { return h`<option value="${o[0]}"${String(o[0]) === String(selected) ? raw(' selected') : ''}>${o[1]}</option>`; });
}
/* Wire a segmented control or tab bar inside `root`; calls fn(value). */
function onSeg(root, name, fn) {
  $$('[data-seg="' + name + '"] button', root).forEach(function (b) {
    b.addEventListener('click', function () { fn(b.getAttribute('data-value')); });
  });
}
function onTabs(root, fn) {
  $$('.tabs [data-tab]', root).forEach(function (b) {
    b.addEventListener('click', function () { fn(b.getAttribute('data-tab')); });
  });
}
function setHTML(el, node) { el.innerHTML = String(node); }
function formValue(form, name) { return form.elements[name].value; }
function intOrNull(v) { return v === '' || v === null || v === undefined ? null : parseInt(v, 10); }
