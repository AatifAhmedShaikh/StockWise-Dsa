/* charts.js - small SVG chart functions (no libraries). Each returns a Raw SVG string.
 * Palette: validated colour-blind-safe order blue, orange, aqua, then yellow. */
'use strict';

var BLUE = '#2a78d6', ORANGE = '#eb6834', AQUA = '#1baf7a', YELLOW = '#eda100';
var SERIES = [BLUE, ORANGE, AQUA, YELLOW];

/* maxScale caps how far a chart may be enlarged, so text never becomes oversized in a wide card */
function svgOpen(w, hgt, label, maxScale) {
  return '<svg class="chart" viewBox="0 0 ' + w + ' ' + hgt + '" style="max-width:' + Math.round(w * (maxScale || 1.3)) + 'px" role="img" aria-label="' + esc(label || 'chart') + '">';
}
function tipAttr(t) { return t ? ' data-tip="' + esc(t) + '"' : ''; }
function clip(text, n) { text = String(text); return text.length > n ? text.slice(0, n - 1) + '…' : text; }

/* "nice" axis maximum and step, about 4 intervals */
function niceScale(max) {
  if (max <= 0) return { max: 1, step: 0.25 };
  var raw = max / 4, pow = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / pow;
  var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow;
  return { max: Math.ceil(max / step) * step, step: step };
}
function axisNum(n) { return n >= 1000 ? (n / 1000) + 'k' : String(Math.round(n * 100) / 100); }

/* horizontal bars: items [{label, value, tip}] */
function hbar(items, o) {
  var opt = o || {}, W = opt.width || 560, fmt = opt.fmt || num, color = opt.color || BLUE;
  var maxLabel = Math.max.apply(null, items.map(function (i) { return Math.min(String(i.label).length, 28); }).concat([4]));
  var lw = Math.min(190, maxLabel * 6.7 + 10), rowH = 28, top = 4, right = 64;
  var max = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1e-9]));
  var H = top + items.length * rowH + 6, x0 = lw + 8, span = W - x0 - right;
  var out = svgOpen(W, H, opt.label) + '<line class="axis" x1="' + x0 + '" y1="0" x2="' + x0 + '" y2="' + (H - 4) + '"/>';
  items.forEach(function (it, i) {
    var y = top + i * rowH, bw = Math.max(it.value / max * span, it.value > 0 ? 2 : 0);
    out += '<text x="' + (lw) + '" y="' + (y + 17) + '" text-anchor="end">' + esc(clip(it.label, 28)) + '</text>' +
      '<rect x="' + x0 + '" y="' + (y + 4) + '" width="' + bw + '" height="18" rx="4" fill="' + color + '"' + tipAttr(it.tip || (it.label + ': ' + fmt(it.value))) + '/>' +
      '<text x="' + (x0 + bw + 6) + '" y="' + (y + 17) + '">' + esc(fmt(it.value)) + '</text>';
  });
  return raw(out + '</svg>');
}

/* vertical bars: items [{label, value, tip}] */
function columnsChart(items, o) {
  var opt = o || {}, W = opt.width || 560, H = opt.height || 230, color = opt.color || BLUE;
  var L = 40, B = 28, T = 18, R = 8, fmt = opt.fmt || num;
  var sc = niceScale(Math.max.apply(null, items.map(function (i) { return i.value; }).concat([0])));
  var pw = W - L - R, ph = H - T - B, bw = pw / items.length, gap = Math.min(bw * 0.3, 14);
  var out = svgOpen(W, H, opt.label);
  for (var v = 0; v <= sc.max + 1e-9; v += sc.step) {
    var y = T + ph - v / sc.max * ph;
    out += '<line class="grid" x1="' + L + '" y1="' + y + '" x2="' + (W - R) + '" y2="' + y + '"/><text x="' + (L - 6) + '" y="' + (y + 4) + '" text-anchor="end">' + axisNum(v) + '</text>';
  }
  var every = Math.ceil(items.length / 16);
  items.forEach(function (it, i) {
    var x = L + i * bw + gap / 2, w = Math.max(bw - gap, 1), bh = it.value / sc.max * ph;
    out += '<rect x="' + x + '" y="' + (T + ph - bh) + '" width="' + w + '" height="' + Math.max(bh, 0) + '" rx="' + Math.min(4, w / 2) + '" fill="' + color + '"' + tipAttr(it.tip || (it.label + ': ' + fmt(it.value))) + '/>';
    if (opt.values !== false && items.length <= 12) out += '<text x="' + (x + w / 2) + '" y="' + (T + ph - bh - 5) + '" text-anchor="middle" style="fill:#14171f">' + esc(fmt(it.value)) + '</text>';
    if (i % every === 0) out += '<text x="' + (x + w / 2) + '" y="' + (H - 8) + '" text-anchor="middle">' + esc(clip(it.label, 14)) + '</text>';
  });
  return raw(out + '<line class="axis" x1="' + L + '" y1="' + (T + ph) + '" x2="' + (W - R) + '" y2="' + (T + ph) + '"/></svg>');
}

/* grouped columns over time: xs [labels], series [{name,color,values}] */
function groupedColumns(xs, series, o) {
  var opt = o || {}, W = opt.width || 620, H = opt.height || 250, L = 40, B = 28, T = 10, R = 6;
  var max = 0; series.forEach(function (s) { s.values.forEach(function (v) { max = Math.max(max, v); }); });
  var sc = niceScale(max), pw = W - L - R, ph = H - T - B, slot = pw / xs.length;
  var bw = Math.max((slot * 0.78) / series.length, 1.5);
  var out = svgOpen(W, H, opt.label);
  for (var v = 0; v <= sc.max + 1e-9; v += sc.step) {
    var y = T + ph - v / sc.max * ph;
    out += '<line class="grid" x1="' + L + '" y1="' + y + '" x2="' + (W - R) + '" y2="' + y + '"/><text x="' + (L - 6) + '" y="' + (y + 4) + '" text-anchor="end">' + axisNum(v) + '</text>';
  }
  xs.forEach(function (label, i) {
    series.forEach(function (s, k) {
      var bh = s.values[i] / sc.max * ph, x = L + i * slot + slot * 0.11 + k * bw;
      out += '<rect x="' + x + '" y="' + (T + ph - bh) + '" width="' + (bw - 0.6) + '" height="' + Math.max(bh, 0) + '" rx="1.5" fill="' + s.color + '"' + tipAttr(label + ' · ' + s.name + ': ' + num(s.values[i]) + ' units') + '/>';
    });
    if (i % 7 === 0 || (i === xs.length - 1 && i % 7 >= 4)) out += '<text x="' + (L + i * slot + slot / 2) + '" y="' + (H - 8) + '" text-anchor="middle">' + esc(label) + '</text>';
  });
  return raw(out + '<line class="axis" x1="' + L + '" y1="' + (T + ph) + '" x2="' + (W - R) + '" y2="' + (T + ph) + '"/></svg>');
}

/* stacked horizontal bars on a 0..100 scale: rows [{label, parts:[...]}], keys [{name,color}] */
function stackedH(rows, keys, o) {
  var opt = o || {}, W = opt.width || 560, rowH = 30;
  var lw = Math.min(180, Math.max.apply(null, rows.map(function (r) { return Math.min(r.label.length, 26); }).concat([4])) * 6.7 + 10);
  var x0 = lw + 8, span = W - x0 - 10, H = rows.length * rowH + 30;
  var out = svgOpen(W, H, opt.label);
  [0, 25, 50, 75, 100].forEach(function (v) {
    var x = x0 + v / 100 * span;
    out += '<line class="grid" x1="' + x + '" y1="0" x2="' + x + '" y2="' + (rows.length * rowH) + '"/><text x="' + x + '" y="' + (rows.length * rowH + 16) + '" text-anchor="middle">' + v + '</text>';
  });
  rows.forEach(function (r, i) {
    var y = i * rowH, x = x0;
    out += '<text x="' + lw + '" y="' + (y + 19) + '" text-anchor="end">' + esc(clip(r.label, 26)) + '</text>';
    r.parts.forEach(function (v, k) {
      var w = v / 100 * span;
      if (w > 0) out += '<rect x="' + x + '" y="' + (y + 5) + '" width="' + Math.max(w - 1.5, 0.5) + '" height="20" rx="2" fill="' + keys[k].color + '"' + tipAttr(r.label + ' · ' + keys[k].name + ': ' + fixed(v, 1) + ' points') + '/>';
      x += w;
    });
  });
  return raw(out + '</svg>');
}

/* line chart with a log10 y axis. series [{name,color,points:[{x,y}]}] */
function lineLog(series, o) {
  var opt = o || {}, W = opt.width || 760, H = opt.height || 320, L = 52, B = 34, T = 12, R = 120;
  var xs = [], ymin = Infinity, ymax = 0;
  series.forEach(function (s) { s.points.forEach(function (p) { xs.push(p.x); ymin = Math.min(ymin, p.y); ymax = Math.max(ymax, p.y); }); });
  var xmax = Math.max.apply(null, xs), xmin = Math.min.apply(null, xs), lo = Math.floor(Math.log10(Math.max(ymin, 1))), hi = Math.ceil(Math.log10(ymax));
  if (hi === lo) hi = lo + 1;
  var pw = W - L - R, ph = H - T - B;
  var X = function (x) { return L + (Math.log(x) - Math.log(xmin)) / (Math.log(xmax) - Math.log(xmin)) * pw; };
  var Y = function (y) { return T + ph - (Math.log10(Math.max(y, 1)) - lo) / (hi - lo) * ph; };
  var out = svgOpen(W, H, opt.label);
  for (var e = lo; e <= hi; e++) {
    out += '<line class="grid" x1="' + L + '" y1="' + Y(Math.pow(10, e)) + '" x2="' + (L + pw) + '" y2="' + Y(Math.pow(10, e)) + '"/><text x="' + (L - 6) + '" y="' + (Y(Math.pow(10, e)) + 4) + '" text-anchor="end">' + axisNum(Math.pow(10, e)) + '</text>';
  }
  var ticks = []; series[0].points.forEach(function (p) { ticks.push(p.x); });
  ticks.forEach(function (x) { out += '<text x="' + X(x) + '" y="' + (H - 12) + '" text-anchor="middle">' + x + '</text>'; });
  out += '<text x="' + (L + pw / 2) + '" y="' + (H) + '" text-anchor="middle">Number of products (n), log scale</text>';
  var ends = [];
  series.forEach(function (s) {
    var d = s.points.map(function (p, i) { return (i ? 'L' : 'M') + X(p.x) + ' ' + Y(p.y); }).join(' ');
    out += '<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="2.2"/>';
    s.points.forEach(function (p) {
      out += '<circle cx="' + X(p.x) + '" cy="' + Y(p.y) + '" r="4.5" fill="' + s.color + '" stroke="#fff" stroke-width="1.5"' + tipAttr(s.name + ' · n = ' + p.x + ': ' + num(p.y) + ' comparisons') + '/>';
    });
    var last = s.points[s.points.length - 1];
    ends.push({ name: s.name, y: Y(last.y), x: X(last.x) });
  });
  ends.sort(function (a, b) { return a.y - b.y; });
  for (var i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 15) ends[i].y = ends[i - 1].y + 15;
  ends.forEach(function (e2) { out += '<text x="' + (e2.x + 10) + '" y="' + (e2.y + 4) + '" style="fill:#14171f">' + esc(e2.name) + '</text>'; });
  return raw(out + '</svg>');
}

/* tiny area sparkline */
function sparkArea(values, color) {
  var W = 200, H = 34, c = color || '#8a93a3';
  var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values), span = hi - lo || 1;
  var pts = values.map(function (v, i) { return [i / Math.max(values.length - 1, 1) * W, H - 3 - (v - lo) / span * (H - 8)]; });
  var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
  return raw('<svg class="spark" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true"><path d="' + line + ' L' + W + ' ' + H + ' L0 ' + H + ' Z" fill="' + c + '" opacity=".16"/><path d="' + line + '" fill="none" stroke="' + c + '" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>');
}

/* heatmap table: matrix[row][col] */
function heatmap(rowLabels, colLabels, matrix, o) {
  var opt = o || {}, W = opt.width || 640, lw = Math.min(110, Math.max.apply(null, rowLabels.map(function (l) { return l.length; }).concat([5])) * 7 + 12);
  var cw = Math.min(54, (W - lw) / colLabels.length), ch = 30, top = 26, H = top + rowLabels.length * ch + 4;
  var max = 0; matrix.forEach(function (r) { r.forEach(function (v) { max = Math.max(max, v); }); });
  var lerp = function (a, b, t) { return Math.round(a + (b - a) * t); };
  var color = function (t) { return 'rgb(' + lerp(242, 16, t) + ',' + lerp(244, 66, t) + ',' + lerp(247, 129, t) + ')'; };
  var out = svgOpen(lw + cw * colLabels.length + 4, H, opt.label, 1.25);
  colLabels.forEach(function (c, j) { out += '<text x="' + (lw + j * cw + cw / 2) + '" y="16" text-anchor="middle">' + esc(c) + '</text>'; });
  rowLabels.forEach(function (rl, i) {
    out += '<text x="' + (lw - 8) + '" y="' + (top + i * ch + 19) + '" text-anchor="end">' + esc(clip(rl, 14)) + '</text>';
    matrix[i].forEach(function (v, j) {
      var t = max ? v / max : 0;
      out += '<rect x="' + (lw + j * cw) + '" y="' + (top + i * ch) + '" width="' + (cw - 1.5) + '" height="' + (ch - 1.5) + '" rx="3" fill="' + color(t) + '"' + tipAttr('first ' + i + ' item(s), budget ' + colLabels[j] + ': best ' + fixed(v, 1)) + '/>' +
        '<text x="' + (lw + j * cw + cw / 2) + '" y="' + (top + i * ch + 19) + '" text-anchor="middle" style="fill:' + (t > 0.5 ? '#fff' : '#14171f') + '">' + Math.round(v) + '</text>';
    });
  });
  return raw(out + '</svg>');
}

/* binary tree: nodes [{label, left, right}], root = nodes[0]; labels may contain \n.
 * Each level is split evenly, so the shape reads like the textbook drawing. */
function treeSvg(nodes, o) {
  var opt = o || {};
  if (!nodes.length) return empty('The tree is empty.');
  var UX = 70, UY = 62, nodeW = 62, nodeH = 36, maxDepth = 0, pos = [];
  (function depthOf(i, d) {
    maxDepth = Math.max(maxDepth, d);
    if (nodes[i].left >= 0) depthOf(nodes[i].left, d + 1);
    if (nodes[i].right >= 0) depthOf(nodes[i].right, d + 1);
  })(0, 0);
  var slots = Math.pow(2, maxDepth);
  (function place(i, depth, lo, hi) {
    pos[i] = { x: (lo + hi) / 2, y: depth };
    if (nodes[i].left >= 0) place(nodes[i].left, depth + 1, lo, (lo + hi) / 2);
    if (nodes[i].right >= 0) place(nodes[i].right, depth + 1, (lo + hi) / 2, hi);
  })(0, 0, 0, slots);
  var W = slots * UX + 8, H = (maxDepth + 1) * UY + 4;
  var cx = function (i) { return 4 + pos[i].x * UX; }, cy = function (i) { return 4 + pos[i].y * UY + nodeH / 2; };
  var out = svgOpen(W, H, opt.label, 1), edges = '', boxes = '';
  nodes.forEach(function (n, i) {
    [n.left, n.right].forEach(function (c) {
      if (c >= 0) edges += '<line x1="' + cx(i) + '" y1="' + (cy(i) + nodeH / 2) + '" x2="' + cx(c) + '" y2="' + (cy(c) - nodeH / 2) + '" stroke="#c3c2b7" stroke-width="1.4"/>';
    });
    var lines = String(n.label).split('\n'), root = i === 0;
    boxes += '<rect x="' + (cx(i) - nodeW / 2) + '" y="' + (cy(i) - nodeH / 2) + '" width="' + nodeW + '" height="' + nodeH + '" rx="9" fill="' + (root ? BLUE : '#eef4fc') + '" stroke="' + (root ? BLUE : '#86b6ef') + '" stroke-width="1.3"/>';
    lines.forEach(function (ln, k) {
      var y = cy(i) + (lines.length === 1 ? 4 : k === 0 ? -3 : 11);
      boxes += '<text x="' + cx(i) + '" y="' + y + '" text-anchor="middle" style="fill:' + (root ? '#fff' : '#14171f') + '">' + esc(ln) + '</text>';
    });
  });
  return raw(out + edges + boxes + '</svg>');
}

/* delivery network: locations [[name,x,y]], routes [[a,b,km]], highlighted path [node...] */
function networkSvg(locations, routes, path, distances) {
  var W = 720, H = 470, M = 70;
  var xs = locations.map(function (l) { return l[1]; }), ys = locations.map(function (l) { return l[2]; });
  var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
  var X = function (x) { return M + (x - x0) / (x1 - x0) * (W - 2 * M); };
  var Y = function (y) { return M / 1.5 + (y1 - y) / (y1 - y0) * (H - 1.6 * M); };
  var hot = {}; for (var i = 0; i + 1 < path.length; i++) { hot[path[i] + '-' + path[i + 1]] = 1; hot[path[i + 1] + '-' + path[i]] = 1; }
  var out = svgOpen(W, H, 'Delivery network', 1.1), edges = '', labels = '', nodes = '';
  routes.forEach(function (r) {
    var on = hot[r[0] + '-' + r[1]], ax = X(locations[r[0]][1]), ay = Y(locations[r[0]][2]), bx = X(locations[r[1]][1]), by = Y(locations[r[1]][2]);
    edges += '<line x1="' + ax + '" y1="' + ay + '" x2="' + bx + '" y2="' + by + '" stroke="' + (on ? BLUE : '#c3c2b7') + '" stroke-width="' + (on ? 4 : 1.5) + '"' + tipAttr(locations[r[0]][0] + ' to ' + locations[r[1]][0] + ': ' + r[2] + ' km') + '/>';
    var mx = (ax + bx) / 2, my = (ay + by) / 2;
    labels += '<rect x="' + (mx - 12) + '" y="' + (my - 9) + '" width="24" height="17" rx="4" fill="#fff" opacity=".92"/><text x="' + mx + '" y="' + (my + 4) + '" text-anchor="middle" style="fill:' + (on ? '#1c5cab' : '#52525b') + ';font-weight:' + (on ? 700 : 400) + '">' + r[2] + '</text>';
  });
  locations.forEach(function (l, i) {
    var end = path.length && (i === path[0] || i === path[path.length - 1]), onPath = path.indexOf(i) >= 0;
    var w = Math.max(l[0].length * 6.6 + 18, 70), x = X(l[1]), y = Y(l[2]);
    nodes += '<rect x="' + (x - w / 2) + '" y="' + (y - 19) + '" width="' + w + '" height="38" rx="9" fill="' + (end ? BLUE : onPath ? '#e6f0fc' : '#fff') + '" stroke="' + (end || onPath ? BLUE : '#c3c2b7') + '" stroke-width="1.4"/>' +
      '<text x="' + x + '" y="' + (y - 3) + '" text-anchor="middle" style="fill:' + (end ? '#fff' : '#14171f') + ';font-weight:600">' + esc(l[0]) + '</text>' +
      '<text x="' + x + '" y="' + (y + 12) + '" text-anchor="middle" style="fill:' + (end ? '#cde2fb' : '#52525b') + '">' + (distances[i] === null ? 'unreachable' : distances[i] + ' km') + '</text>';
  });
  return raw(out + edges + labels + nodes + '</svg>');
}

function legend(items) {
  return h`<div class="legend">${items.map(function (i) { return h`<span><i style="background:${i[1]}"></i>${i[0]}</span>`; })}</div>`;
}
