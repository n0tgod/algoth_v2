#!/usr/bin/env python3
"""
График бэктеста: свечи, сделки на них, кривая счёта снизу.

Что переиспользовано из v1 и что нет
------------------------------------

Из v1 переиспользована **раскладка**, а не код: главная панель со
свечами, панель бэктеста под ней, список сделок, метки сделок прямо на
графике. Сам код переиспользовать нельзя технически — фронт v1 стоял на
трёх графических библиотеках сразу (`klinecharts` двух версий,
`lightweight-charts`, `chart.js`, плюс `d3`), это npm-пакеты со
сборкой, а страница обязана быть одним файлом без внешних загрузок.

И не нужно: рисование свечей — это сотня строк на canvas. Четыре тысячи
строк в v1 ушли на настройку внешнего вида графика, и это одна из
причин, по которым он не дожил до первого платящего пользователя.
Настроек внешнего вида здесь нет вовсе.

Что показывает
--------------

Свечи минутные, из той же ленты, по которой считались сделки. На них —
вход, стоп, цель, уровень набора и выход, с затенением от входа до
выхода. Снизу кривая счёта по всей ячейке (обе стороны сразу: лонг
после набора под ценой, шорт после разгрузки над ценой) и сводка,
где доля побед стоит рядом с безубыточной для фактических отношений.

    python3 research/t3_brackets/chart.py
    python3 research/t3_brackets/chart.py --tag=-smoke
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

HTML = r"""<title>Бэктест: сделки на графике</title>
<style>
:root {
  color-scheme: light dark;
  --ground:#f6f7f9; --panel:#fff; --ink:#141a21; --muted:#5c6673;
  --rule:#dfe4ea; --up:#1f7a56; --down:#b8452c; --accent:#a97514;
  --grid:#eef1f5; --eq:#3d6fb4;
}
@media (prefers-color-scheme: dark) {
  :root { --ground:#0c1015; --panel:#131922; --ink:#e4e9f0; --muted:#8b95a4;
    --rule:#212936; --up:#35a877; --down:#d4614a; --accent:#d7a24a;
    --grid:#1a212c; --eq:#6f9fe0; }
}
:root[data-theme="dark"] {
  --ground:#0c1015; --panel:#131922; --ink:#e4e9f0; --muted:#8b95a4;
  --rule:#212936; --up:#35a877; --down:#d4614a; --accent:#d7a24a;
  --grid:#1a212c; --eq:#6f9fe0;
}
:root[data-theme="light"] {
  --ground:#f6f7f9; --panel:#fff; --ink:#141a21; --muted:#5c6673;
  --rule:#dfe4ea; --up:#1f7a56; --down:#b8452c; --accent:#a97514;
  --grid:#eef1f5; --eq:#3d6fb4;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--ground); color:var(--ink);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums; }
.wrap { max-width:1080px; margin:0 auto; padding:20px 14px 56px; }
h1 { font-size:20px; margin:0 0 4px; }
.sub { color:var(--muted); font-size:13.5px; margin:0 0 14px; }
.eyebrow { font-size:11px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--muted); margin-bottom:6px; }
.stats { display:grid; gap:1px; background:var(--rule);
  grid-template-columns:repeat(auto-fit,minmax(112px,1fr));
  border:1px solid var(--rule); margin:0 0 14px; }
.stat { background:var(--panel); padding:9px 11px; }
.stat .k { font-size:11px; color:var(--muted); letter-spacing:.04em; }
.stat .v { font-size:17px; font-weight:600; }
.good { color:var(--up); } .bad { color:var(--down); }
.bar { display:flex; flex-wrap:wrap; gap:6px; align-items:center;
  margin:0 0 8px; }
button { font:inherit; color:var(--ink); background:var(--panel);
  border:1px solid var(--rule); padding:5px 11px; cursor:pointer; }
button:hover { border-color:var(--accent); }
button[aria-pressed="true"] { border-color:var(--accent);
  box-shadow:inset 0 -2px 0 var(--accent); }
button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.spacer { flex:1 1 auto; }
.panel { background:var(--panel); border:1px solid var(--rule);
  margin:0 0 12px; }
canvas { display:block; width:100%; touch-action:none; }
.cap { display:flex; justify-content:space-between; gap:10px;
  padding:7px 11px; border-bottom:1px solid var(--rule);
  font-size:12px; color:var(--muted); }
.list { border:1px solid var(--rule); max-height:340px; overflow-y:auto;
  background:var(--panel); }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { padding:6px 9px; text-align:right; white-space:nowrap;
  border-bottom:1px solid var(--rule); }
th { position:sticky; top:0; background:var(--panel); color:var(--muted);
  font-weight:500; font-size:11.5px; letter-spacing:.05em;
  text-transform:uppercase; }
td:first-child, th:first-child { text-align:left; }
tbody tr { cursor:pointer; }
tbody tr:hover { background:var(--grid); }
tbody tr[aria-selected="true"] { background:var(--grid);
  box-shadow:inset 3px 0 0 var(--accent); }
.legend { display:flex; flex-wrap:wrap; gap:4px 16px; font-size:12px;
  color:var(--muted); margin:10px 0 18px; }
.sw { display:inline-block; width:20px; height:0; border-top:2px solid;
  vertical-align:4px; margin-right:6px; }
footer { color:var(--muted); font-size:12.5px; border-top:1px solid var(--rule);
  padding-top:12px; margin-top:18px; }
#tip { position:absolute; z-index:5; pointer-events:none; display:none;
  background:var(--panel); border:1px solid var(--rule); padding:8px 10px;
  font-size:12.5px; line-height:1.45; box-shadow:0 6px 24px rgba(0,0,0,.18);
  max-width:260px; }
#tip .t { font-weight:650; margin-bottom:3px; }
#tip .r { display:flex; justify-content:space-between; gap:14px; }
#tip .r span:first-child { color:var(--muted); }
.holder { position:relative; }
</style>

<div class="wrap">
<p class="eyebrow">__EYEBROW__</p>
<h1>Сделки на графике</h1>
<p class="sub">__SUB__</p>

<div class="stats" id="stats"></div>

<div class="bar">
  <span id="syms"></span>
  <span class="spacer"></span>
  <button id="prev" title="предыдущая сделка">‹ сделка</button>
  <button id="next" title="следующая сделка">сделка ›</button>
  <button id="fit" title="показать все сделки символа">весь период</button>
</div>

<div class="panel holder">
  <div class="cap"><span id="cap-sym" class="mono"></span>
    <span id="cap-range" class="mono"></span></div>
  <canvas id="px" height="380"></canvas>
  <div id="tip" class="mono"></div>
</div>

<div class="panel">
  <div class="cap"><span>кривая счёта ·
    <button id="unit" style="padding:1px 8px;font-size:12px">в R</button>
    </span><span id="cap-eq" class="mono"></span></div>
  <canvas id="eq" height="150"></canvas>
</div>

<div class="legend">
  <span><span class="sw" style="border-color:var(--accent)"></span>уровень набора</span>
  <span><span class="sw" style="border-color:var(--down)"></span>стоп</span>
  <span><span class="sw" style="border-color:var(--up)"></span>цель</span>
  <span><span class="sw" style="border-color:var(--ink)"></span>вход и выход</span>
  <span>тяните график, колесо или щипок — масштаб</span>
</div>

<div class="list">
<table><thead><tr>
<th>время</th><th>сторона</th><th>вход</th><th>стоп</th><th>цель</th>
<th>отн.</th><th>исход</th><th>держали</th><th>итог</th>
</tr></thead><tbody id="rows"></tbody></table>
</div>

<footer>
Свечи минутные, из той же ленты, по которой считались сделки. Вход — по
первой доступной цене после закрытия окна набора; исполнение лимитной
заявкой не предполагается, круг издержек __COST__ б.п. тейкером. Ничья
«стоп и цель в одну секунду» засчитана стопом.
</footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();
const fmt = (v, d) => v.toFixed(d);

// Свечи лежат приращениями: закрытие — к предыдущему закрытию, прочие
// три цены — смещением от закрытия своей свечи. Разворачиваем один раз.
const SER = {};
for (const [sym, s] of Object.entries(D.series)) {
  const n = s.dc.length, t = new Array(n), c = new Array(n);
  let acc = 0, tt = s.t0;
  for (let i = 0; i < n; i++) {
    acc += s.dc[i];
    if (i) tt += s.dt[i - 1] * 60;
    t[i] = tt; c[i] = s.base + acc * s.tick;
  }
  SER[sym] = { t,
    o: s.o.map((v, i) => c[i] + v * s.tick),
    h: s.h.map((v, i) => c[i] + v * s.tick),
    l: s.l.map((v, i) => c[i] + v * s.tick), c,
    tick: s.tick };
}
const TR = D.trades.map(x => ({ ...x, ts: Date.parse(x.t) / 1000 }));
TR.sort((a, b) => a.ts - b.ts);
// Итог сделки в кратности риска: сколько взяли относительно того, чем
// рисковали. Кривая в R равносильна одинаковому риску на сделку, кривая
// в процентах — одинаковому объёму; трейдер размеряет позицию первым
// способом, поэтому переключатель, а не одна мера.
TR.forEach(x => {
  x.stopBp = Math.abs(x.entry - x.stop) / x.entry * 1e4;
  x.r = x.net / Math.max(x.stopBp, 1e-9);
});
let UNIT = "bp";
function recalc() {
  let e = 0;
  TR.forEach(x => { e += (UNIT === "bp" ? x.net : x.r); x.eq = e; });
}
recalc();

const symbols = Object.keys(SER).sort(
  (a, b) => TR.filter(x => x.sym === b).length
          - TR.filter(x => x.sym === a).length);
let sym = symbols[0];
let view = { i0: 0, n: 180 };
let sel = 0;

function stats(list) {
  const n = list.length;
  if (!n) return null;
  const wins = list.filter(x => x.net > 0);
  const pos = wins.reduce((s, x) => s + x.net, 0);
  const neg = list.filter(x => x.net <= 0).reduce((s, x) => s - x.net, 0);
  const rAvg = list.reduce((s, x) => s + x.r, 0) / n;
  let peak = 0, dd = 0, e = 0;
  for (const x of list) { e += x.net; peak = Math.max(peak, e);
    dd = Math.min(dd, e - peak); }
  // Безубыточная доля побед — по ФАКТИЧЕСКОМУ отношению каждой сделки:
  // цель ставит структура, а не наш параметр.
  const be = list.reduce((s, x) => {
    const stop = Math.abs(x.entry - x.stop) / x.entry * 1e4;
    return s + (stop + D.cell.cost_bp) / (stop * (1 + x.rr));
  }, 0) / n;
  return { n, win: wins.length / n, be, exp: (pos - neg) / n, rAvg,
    sum: pos - neg, dd, pf: neg > 0 ? pos / neg : Infinity };
}

function drawStats() {
  const s = stats(TR);
  const el = document.getElementById("stats");
  const cell = (k, v, cls) => `<div class="stat"><div class="k">${k}</div>
    <div class="v mono ${cls || ""}">${v}</div></div>`;
  el.innerHTML =
    cell("сделок", s.n) +
    cell("доля побед", (s.win * 100).toFixed(0) + " %",
         s.win > s.be ? "good" : "bad") +
    cell("безубыточная", (s.be * 100).toFixed(0) + " %") +
    cell("ожидание", (s.exp > 0 ? "+" : "") + s.exp.toFixed(1) + " б.п.",
         s.exp > 0 ? "good" : "bad") +
    cell("ожидание, R", (s.rAvg > 0 ? "+" : "") + s.rAvg.toFixed(2),
         s.rAvg > 0 ? "good" : "bad") +
    cell("итог", (s.sum > 0 ? "+" : "") + s.sum.toFixed(0) + " б.п.",
         s.sum > 0 ? "good" : "bad") +
    cell("просадка", s.dd.toFixed(0) + " б.п.", "bad") +
    cell("профит-фактор", isFinite(s.pf) ? s.pf.toFixed(2) : "—",
         s.pf >= 1 ? "good" : "bad");
}

function symTrades() { return TR.filter(x => x.sym === sym); }

function drawSyms() {
  document.getElementById("syms").innerHTML = symbols.map(s =>
    `<button data-sym="${s}" aria-pressed="${s === sym}"
      >${s.replace("USDT", "")} <span style="color:var(--muted)"
      >${TR.filter(x => x.sym === s).length}</span></button>`).join(" ");
  document.querySelectorAll("[data-sym]").forEach(b =>
    b.onclick = () => { sym = b.dataset.sym; sel = 0; focusTrade(0, true); });
}

function idxOfTime(s, ts) {
  let a = 0, b = s.t.length - 1;
  while (a < b) { const m = (a + b) >> 1;
    if (s.t[m] < ts) a = m + 1; else b = m; }
  return a;
}

function focusTrade(k, redrawList) {
  const list = symTrades();
  if (!list.length) { view = { i0: 0, n: 180 }; draw(); return; }
  sel = Math.max(0, Math.min(list.length - 1, k));
  const tr = list[sel];
  const s = SER[sym];
  const i = idxOfTime(s, tr.ts);
  view.n = Math.max(40, Math.min(view.n, s.t.length));
  view.i0 = Math.max(0, Math.min(s.t.length - view.n,
                                 i - Math.round(view.n * 0.35)));
  if (redrawList !== false) drawList();
  draw();
}

function drawList() {
  const list = symTrades();
  document.getElementById("rows").innerHTML = list.map((x, i) => `
    <tr data-i="${i}" aria-selected="${i === sel}">
      <td class="mono">${x.t.slice(5, 16).replace("T", " ")}</td>
      <td>${x.side < 0 ? "лонг" : "шорт"}</td>
      <td class="mono">${x.entry}</td>
      <td class="mono">${x.stop}</td>
      <td class="mono">${x.target}</td>
      <td class="mono">1:${x.rr}</td>
      <td>${x.outcome}</td>
      <td class="mono">${x.held} с</td>
      <td class="mono ${x.net > 0 ? "good" : "bad"}">${x.net > 0 ? "+" : ""}${x.net}</td>
    </tr>`).join("");
  document.querySelectorAll("#rows tr").forEach(r =>
    r.onclick = () => focusTrade(+r.dataset.i));
  const cur = document.querySelector('#rows tr[aria-selected="true"]');
  if (cur) cur.scrollIntoView({ block: "nearest" });
}

function setup(cv, h) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = cv.clientWidth;
  cv.width = W * dpr; cv.height = h * dpr; cv.style.height = h + "px";
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, h);
  return [g, W, h];
}

function draw() {
  const s = SER[sym];
  const cv = document.getElementById("px");
  const [g, W, H] = setup(cv, 380);
  const padL = 6, padR = 64, padT = 8, padB = 20;
  const pw = W - padL - padR, ph = H - padT - padB;
  const i0 = Math.max(0, Math.round(view.i0));
  const i1 = Math.min(s.t.length, i0 + Math.round(view.n));
  const list = symTrades();
  const tr = list[sel];

  let lo = Infinity, hi = -Infinity;
  for (let i = i0; i < i1; i++) { lo = Math.min(lo, s.l[i]);
    hi = Math.max(hi, s.h[i]); }
  if (tr && tr.ts >= s.t[i0] && tr.ts <= s.t[i1 - 1]) {
    lo = Math.min(lo, tr.stop, tr.target, tr.entry);
    hi = Math.max(hi, tr.stop, tr.target, tr.entry);
  }
  if (!isFinite(lo)) { lo = 0; hi = 1; }
  const pad = (hi - lo) * 0.06 || 1e-9;
  lo -= pad; hi += pad;
  const y = v => padT + ph * (hi - v) / (hi - lo);
  const x = i => padL + pw * (i - i0 + 0.5) / (i1 - i0);
  const xt = ts => padL + pw * (idxOfTime(s, ts) - i0 + 0.5) / (i1 - i0);
  const dec = Math.max(0, Math.ceil(-Math.log10(s.tick)));

  g.strokeStyle = css("--grid"); g.lineWidth = 1;
  g.fillStyle = css("--muted");
  g.font = "11px ui-monospace, Menlo, monospace";
  g.textBaseline = "middle";
  for (let k = 0; k <= 4; k++) {
    const v = hi - (hi - lo) * k / 4;
    g.beginPath(); g.moveTo(padL, y(v)); g.lineTo(W - padR, y(v)); g.stroke();
    g.fillText(fmt(v, dec), W - padR + 5, y(v));
  }

  // Сделки этого символа, попавшие в окно: сначала затенение, потом свечи.
  for (const t of list) {
    if (t.ts < s.t[i0] - 3600 || t.ts > s.t[i1 - 1] + 3600) continue;
    const xa = xt(t.ts), xb = xt(t.ts + t.held);
    g.fillStyle = t.net > 0 ? css("--up") : css("--down");
    g.globalAlpha = .10;
    g.fillRect(xa, y(Math.max(t.stop, t.target)),
               Math.max(xb - xa, 2),
               Math.abs(y(t.stop) - y(t.target)));
    g.globalAlpha = 1;
  }

  HIT.length = 0;
  const cw = Math.max(1, pw / (i1 - i0) * 0.66);
  for (let i = i0; i < i1; i++) {
    const up = s.c[i] >= s.o[i];
    g.strokeStyle = g.fillStyle = up ? css("--up") : css("--down");
    g.beginPath(); g.moveTo(x(i), y(s.h[i])); g.lineTo(x(i), y(s.l[i]));
    g.stroke();
    const yo = y(s.o[i]), yc = y(s.c[i]);
    g.fillRect(x(i) - cw / 2, Math.min(yo, yc), cw,
               Math.max(Math.abs(yc - yo), 1));
  }

  for (const t of list) {
    if (t.ts < s.t[i0] || t.ts > s.t[i1 - 1]) continue;
    const xa = xt(t.ts), xb = Math.max(xt(t.ts + t.held), xa + 3);
    const seg = (v, color, dash) => {
      g.save(); g.strokeStyle = color; g.setLineDash(dash); g.lineWidth = 1.25;
      g.beginPath(); g.moveTo(xa, y(v)); g.lineTo(xb, y(v)); g.stroke();
      g.restore();
    };
    seg(t.level, css("--accent"), []);
    seg(t.stop, css("--down"), [3, 3]);
    seg(t.target, css("--up"), [3, 3]);
    // Вход — треугольник по направлению, выход — квадрат.
    g.fillStyle = css("--ink");
    const yy = y(t.entry), d = t.side < 0 ? -1 : 1;
    g.beginPath();
    g.moveTo(xa, yy + 7 * d); g.lineTo(xa - 5, yy + 14 * d);
    g.lineTo(xa + 5, yy + 14 * d); g.closePath(); g.fill();
    g.fillRect(xb - 2.5, y(t.exit) - 2.5, 5, 5);
    // Область сделки для подсказки: от входа до выхода, между стопом и
    // целью, но не тоньше пальца — иначе попасть в неё невозможно.
    const ya = y(Math.max(t.stop, t.target)), yb = y(Math.min(t.stop, t.target));
    const h2 = Math.max(yb - ya, 18);
    HIT.push({ t, x0: xa - 8, x1: Math.max(xb, xa + 8) + 8,
               y0: (ya + yb) / 2 - h2 / 2, y1: (ya + yb) / 2 + h2 / 2 });

    if (t === tr) label(g, t, xa, xb, y, W - padR);
  }

  g.fillStyle = css("--muted");
  g.textBaseline = "alphabetic";
  const stamp = ts => new Date(ts * 1000).toISOString().slice(5, 16)
    .replace("T", " ");
  g.fillText(stamp(s.t[i0]), padL, H - 6);
  g.textAlign = "right";
  g.fillText(stamp(s.t[i1 - 1]), W - padR, H - 6);
  g.textAlign = "left";

  document.getElementById("cap-sym").textContent =
    sym + " · 1 мин · сделок " + list.length;
  document.getElementById("cap-range").textContent =
    stamp(s.t[i0]) + " — " + stamp(s.t[i1 - 1]);
  drawEquity();
}

function label(g, t, xa, xb, y, right) {
  // Подписи выбранной сделки: где вход, где выход и с чем вышли. Только
  // у выбранной — иначе при десятке сделок в окне читать нечего.
  const chip = (x, yy, text, color, align) => {
    g.font = "11px ui-monospace, Menlo, monospace";
    const w = g.measureText(text).width + 10;
    let x0 = align === "right" ? x - w : x;
    x0 = Math.max(2, Math.min(right - w, x0));
    g.fillStyle = css("--panel");
    g.fillRect(x0, yy - 8, w, 16);
    g.strokeStyle = color; g.lineWidth = 1;
    g.strokeRect(x0 + .5, yy - 7.5, w - 1, 15);
    g.fillStyle = color; g.textBaseline = "middle";
    g.fillText(text, x0 + 5, yy);
  };
  const d = t.side < 0 ? 1 : -1;
  chip(xa, y(t.entry) + 22 * d,
       (t.side < 0 ? "вход · лонг " : "вход · шорт ") + t.entry,
       css("--ink"), "left");
  chip(xb + 4, y(t.exit),
       "выход " + t.exit + " · " + t.outcome + " · "
       + (t.net > 0 ? "+" : "") + t.net + " б.п.",
       t.net > 0 ? css("--up") : css("--down"), "left");
}


function drawEquity() {
  const cv = document.getElementById("eq");
  const [g, W, H] = setup(cv, 150);
  const padL = 6, padR = 64, padT = 10, padB = 16;
  const pw = W - padL - padR, ph = H - padT - padB;
  const lo = Math.min(0, ...TR.map(t => t.eq));
  const hi = Math.max(0, ...TR.map(t => t.eq));
  const y = v => padT + ph * (hi - v) / Math.max(hi - lo, 1e-9);
  const x = i => padL + pw * i / Math.max(TR.length - 1, 1);

  g.strokeStyle = css("--grid");
  for (let k = 0; k <= 2; k++) {
    const v = hi - (hi - lo) * k / 2;
    g.beginPath(); g.moveTo(padL, y(v)); g.lineTo(W - padR, y(v)); g.stroke();
    g.fillStyle = css("--muted");
    g.font = "11px ui-monospace, Menlo, monospace";
    g.textBaseline = "middle";
    g.fillText(v.toFixed(0), W - padR + 5, y(v));
  }
  g.strokeStyle = css("--rule"); g.setLineDash([2, 3]);
  g.beginPath(); g.moveTo(padL, y(0)); g.lineTo(W - padR, y(0)); g.stroke();
  g.setLineDash([]);

  g.strokeStyle = css("--eq"); g.lineWidth = 1.6;
  g.beginPath();
  TR.forEach((t, i) => i ? g.lineTo(x(i), y(t.eq)) : g.moveTo(x(i), y(t.eq)));
  g.stroke();

  const list = symTrades();
  if (list[sel]) {
    const k = TR.indexOf(list[sel]);
    if (k >= 0) {
      g.strokeStyle = css("--accent"); g.lineWidth = 1;
      g.beginPath(); g.moveTo(x(k), padT); g.lineTo(x(k), padT + ph);
      g.stroke();
    }
  }
  document.getElementById("cap-eq").textContent =
    TR.length + " сделок · итог "
    + TR[TR.length - 1].eq.toFixed(UNIT === "bp" ? 0 : 1)
    + (UNIT === "bp" ? " б.п." : " R");
}

// Тяга и масштаб: мышь и палец одинаково, через указатели.
const px = document.getElementById("px");
let drag = null, pinch = null;
const HIT = [];
const tip = document.getElementById("tip");

function showTip(e) {
  const r = px.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const hit = HIT.find(h => mx >= h.x0 && mx <= h.x1
                         && my >= h.y0 && my <= h.y1);
  if (!hit) { tip.style.display = "none"; return; }
  const t = hit.t;
  const row = (k, v, cls) => `<div class="r"><span>${k}</span>
    <span class="${cls || ""}">${v}</span></div>`;
  tip.innerHTML =
    `<div class="t">${t.sym} · ${t.side < 0 ? "лонг" : "шорт"}</div>` +
    row("время", t.t.slice(5, 19).replace("T", " ")) +
    row("вход", t.entry) +
    row("выход", t.exit) +
    row("стоп", t.stop) +
    row("цель", t.target) +
    row("уровень", t.level) +
    row("отношение", "1:" + t.rr) +
    row("держали", t.held + " с") +
    row("исход", t.outcome) +
    row("итог", (t.net > 0 ? "+" : "") + t.net + " б.п. · "
        + (t.r > 0 ? "+" : "") + t.r.toFixed(2) + " R",
        t.net > 0 ? "good" : "bad");
  tip.style.display = "block";
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = Math.max(4, Math.min(px.clientWidth - tw - 4,
                                        mx + 14)) + "px";
  tip.style.top = Math.max(4, Math.min(px.clientHeight - th + 30,
                                       my + 30)) + "px";
}
px.addEventListener("pointerdown", e => {
  px.setPointerCapture(e.pointerId);
  drag = { x: e.clientX, i0: view.i0 };
});
px.addEventListener("pointermove", e => {
  if (!drag) { showTip(e); return; }
  const s = SER[sym];
  const per = px.clientWidth / view.n;
  view.i0 = Math.max(0, Math.min(s.t.length - view.n,
                                 drag.i0 - (e.clientX - drag.x) / per));
  draw();
});
px.addEventListener("pointerup", e => {
  // На телефоне «наведения» нет: короткое касание без протяжки
  // показывает ту же подсказку.
  if (drag && Math.abs(e.clientX - drag.x) < 6) showTip(e);
  drag = null;
});
px.addEventListener("pointerleave", () => { tip.style.display = "none"; });
px.addEventListener("pointercancel", () => { drag = null; });
px.addEventListener("wheel", e => {
  e.preventDefault();
  zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, e.offsetX / px.clientWidth);
}, { passive: false });
px.addEventListener("touchstart", e => {
  if (e.touches.length === 2) {
    drag = null;
    pinch = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
                       e.touches[0].clientY - e.touches[1].clientY);
  }
}, { passive: true });
px.addEventListener("touchmove", e => {
  if (e.touches.length === 2 && pinch) {
    const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
                         e.touches[0].clientY - e.touches[1].clientY);
    zoom(pinch / d, .5); pinch = d;
  }
}, { passive: true });
px.addEventListener("touchend", () => { pinch = null; });

function zoom(k, anchor) {
  const s = SER[sym];
  const n0 = view.n;
  view.n = Math.max(40, Math.min(s.t.length, Math.round(view.n * k)));
  view.i0 = Math.max(0, Math.min(s.t.length - view.n,
                                 view.i0 + (n0 - view.n) * anchor));
  draw();
}

document.getElementById("unit").onclick = e => {
  UNIT = UNIT === "bp" ? "r" : "bp";
  e.target.textContent = UNIT === "bp" ? "в R" : "в б.п.";
  recalc(); drawEquity();
};
document.getElementById("prev").onclick = () => focusTrade(sel - 1);
document.getElementById("next").onclick = () => focusTrade(sel + 1);
document.getElementById("fit").onclick = () => {
  const s = SER[sym];
  view = { i0: 0, n: s.t.length };
  draw();
};
document.addEventListener("keydown", e => {
  if (e.key === "ArrowLeft") focusTrade(sel - 1);
  if (e.key === "ArrowRight") focusTrade(sel + 1);
});
window.addEventListener("resize", draw);
new MutationObserver(draw).observe(document.documentElement,
  { attributes: true, attributeFilter: ["data-theme"] });

drawStats(); drawSyms(); focusTrade(0);
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="")
    # График рисует любой этап, чья выгрузка сделана тем же форматом:
    # ядро сделки общее, значит и просмотр должен быть один, а не по
    # копии на этап.
    ap.add_argument("--dir", default=OUT,
                    help="каталог с backtest.json (по умолчанию t3_brackets)")
    a = ap.parse_args()
    src = os.path.join(a.dir, f"backtest{a.tag}.json")
    with open(src, encoding="utf-8") as f:
        raw = json.load(f)
    c = raw["cell"]
    eyebrow = (f"замер сделки T3 · окно {c['window_sec']} с · объём "
               f"×{c['vol_mult']:g} · сосредоточенность {c['conc']:g} · "
               f"минимальное отношение {c['min_rr']:g}")
    sub = (f"{len(raw['trades'])} сделок, {c['start']} … {c['end']}. "
           f"Лонг после набора под ценой, шорт после разгрузки над ценой — "
           f"направление задаёт событие. Стоп за краем полосы набора, цель "
           f"на ближайшей полке объёма; отношение считается, а не "
           f"назначается.")
    html = (HTML.replace("__DATA__", json.dumps(raw, ensure_ascii=False))
            .replace("__EYEBROW__", eyebrow)
            .replace("__SUB__", sub)
            .replace("__COST__", f"{c['cost_bp']:.0f}"))
    dst = os.path.join(a.dir, f"chart{a.tag}.html")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{dst}: {len(raw['trades'])} сделок, "
          f"{len(raw['series'])} символов, "
          f"{os.path.getsize(dst) // 1024} КиБ")


if __name__ == "__main__":
    main()
