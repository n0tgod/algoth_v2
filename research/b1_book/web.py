#!/usr/bin/env python3
"""
Страница наблюдения: стакан, лента, глубина и журнал живьём.

Почему её отдаёт сам сборщик
----------------------------

Данные должны быть текущими, а не выгруженными: смысл в том, чтобы
видеть, как объём встаёт на цену и восполняется после удара. Между
файлом и глазом не должно быть ни выгрузки, ни публикации — поэтому
сборщик поднимает крошечный сервер и отдаёт своё состояние прямо из
памяти.

Страница одним файлом, без внешних загрузок — как и остальные в
проекте. Настроек внешнего вида нет: это прибор.

Доступ
------

Сервер слушает на всех адресах, иначе с телефона к нему не подключиться.
Поэтому обязателен ключ в ссылке: данные тут биржевые и не секретные, но
открытый порт в интернет без всякой двери — плохая привычка, а не
безопасность. Ключ печатается в журнал при старте.

    .venv/bin/python research/b1_book/collect.py --http 8765
"""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Стакан живьём</title>
<style>
:root{color-scheme:light dark;
 --ground:#f6f7f9;--panel:#fff;--ink:#141a21;--muted:#5c6673;--rule:#dfe4ea;
 --bid:#1f7a56;--ask:#b8452c;--accent:#a97514;--grid:#eef1f5}
@media(prefers-color-scheme:dark){:root{
 --ground:#0c1015;--panel:#131922;--ink:#e4e9f0;--muted:#8b95a4;--rule:#212936;
 --bid:#35a877;--ask:#d4614a;--accent:#d7a24a;--grid:#1a212c}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
 font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.wrap{max-width:1000px;margin:0 auto;padding:14px 12px 40px}
h1{font-size:17px;margin:0 0 2px}
.sub{color:var(--muted);font-size:12.5px;margin:0 0 12px}
.strip{display:grid;gap:1px;background:var(--rule);border:1px solid var(--rule);
 grid-template-columns:repeat(auto-fit,minmax(92px,1fr));margin-bottom:12px}
.st{background:var(--panel);padding:7px 9px}
.st .k{font-size:10.5px;color:var(--muted);letter-spacing:.04em}
.st .v{font-size:15px;font-weight:600}
.bad{color:var(--ask)} .good{color:var(--bid)}
.syms{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;align-items:center}
.open{font-size:13px;color:var(--ink);background:var(--panel);
 border:1px solid var(--accent);padding:4px 9px;text-decoration:none}
.open:hover{background:var(--grid)}
button{font:inherit;font-size:13px;color:var(--ink);background:var(--panel);
 border:1px solid var(--rule);padding:4px 9px;cursor:pointer}
button[aria-pressed=true]{border-color:var(--accent);
 box-shadow:inset 0 -2px 0 var(--accent)}
.cols{display:grid;gap:12px;grid-template-columns:1fr}
@media(min-width:760px){.cols{grid-template-columns:1fr 1fr}}
.panel{background:var(--panel);border:1px solid var(--rule)}
.cap{padding:6px 10px;border-bottom:1px solid var(--rule);font-size:11.5px;
 color:var(--muted);letter-spacing:.05em;text-transform:uppercase;
 display:flex;justify-content:space-between;gap:8px}
table{border-collapse:collapse;width:100%;font-size:13px}
td{padding:2px 9px;position:relative;white-space:nowrap}
td.sz{text-align:right;width:38%}
td.px{width:34%}
.bar{position:absolute;top:1px;bottom:1px;opacity:.16}
tr.a .bar{background:var(--ask);right:0}
tr.b .bar{background:var(--bid);right:0}
tr.a td.px{color:var(--ask)} tr.b td.px{color:var(--bid)}
.spread{background:var(--grid);font-size:12px;color:var(--muted)}
.tape{max-height:330px;overflow-y:auto}
.tape td{padding:1px 9px}
.buy{color:var(--bid)} .sell{color:var(--ask)}
canvas{display:block;width:100%}
.log{max-height:150px;overflow-y:auto;padding:6px 10px;font-size:12px;
 color:var(--muted);white-space:pre-wrap}
.bands{padding:8px 10px}
.band{display:flex;align-items:center;gap:6px;margin:3px 0;font-size:12px}
.band .n{width:52px;color:var(--muted);text-align:right}
.band .g{flex:1;display:flex;height:12px;background:var(--grid)}
.band .g i{display:block;height:100%}
.band .g .l{background:var(--bid);margin-left:auto}
.band .g .r{background:var(--ask)}
.band .q{width:96px;text-align:center;color:var(--muted)}
footer{color:var(--muted);font-size:12px;margin-top:14px}
</style>
<div class="wrap">
<h1>Стакан живьём</h1>
<p class="sub" id="sub">подключение…</p>
<div class="strip" id="strip"></div>
<div class="syms" id="syms"></div>
<div class="cols">
  <div class="panel">
    <div class="cap"><span>стакан</span><span id="cap-book" class="mono"></span></div>
    <table id="book"></table>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>глубина по полосам, тыс. $</span></div>
    <div class="bands" id="bands"></div>
  </div>
  <div class="panel">
    <div class="cap"><span>середина, последние 15 мин</span>
      <span id="cap-mid" class="mono"></span></div>
    <canvas id="mid" height="140"></canvas>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>детектор — что выполнено прямо сейчас</span>
      <span id="cap-diag" class="mono"></span></div>
    <table id="diag"></table>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>бумажные сделки — наблюдение, не торговля</span>
      <span id="cap-sig" class="mono"></span></div>
    <table id="sig"></table>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>лента</span><span id="cap-tape" class="mono"></span></div>
    <div class="tape"><table id="tape"></table></div>
  </div>
</div>
<div class="panel" style="margin-top:12px">
  <div class="cap"><span>журнал сборщика</span></div>
  <div class="log mono" id="log"></div>
</div>
<footer>Обновление раз в секунду. Стакан — тема orderbook.50 площадки
исполнения; сторона сделки — агрессора.</footer>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
let sym = null, timer = null;
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();
const fmt = (v, d=2) => v === null || v === undefined || !isFinite(v)
  ? "—" : v.toLocaleString("ru-RU", {minimumFractionDigits: d,
                                     maximumFractionDigits: d});
const kk = v => v >= 1e6 ? (v/1e6).toFixed(1)+" млн"
  : v >= 1e3 ? (v/1e3).toFixed(0) : v.toFixed(0);

// Разностный опрос. Полная выдача весила 58 КиБ, из них 29 — девятьсот
// точек середины ради одной новой; на мобильной связи ответ не успевал
// прийти до следующего опроса, и страница писала «нет связи» на
// исправном сборщике. Здесь копится своё, а с сервера берётся новое.
const ST = {mid:[], tape:[], log:[], cand:[], logn:0, since:0, sym:"",
            busy:false, fails:0};
function wipe() { ST.mid=[]; ST.tape=[]; ST.log=[]; ST.cand=[];
                  ST.logn=0; ST.since=0; }
function mergeCandles(old, add) {
  if (!add.length) return old;
  const m = new Map(old.map(c => [c[0], c]));
  for (const c of add) m.set(c[0], c);
  return [...m.values()].sort((a,b) => a[0]-b[0]).slice(-600);
}
function merge(d) {
  ST.mid  = d.mid_full  ? (d.mid||[])  : ST.mid.concat(d.mid||[]);
  ST.tape = d.tape_full ? (d.tape||[]) : ST.tape.concat(d.tape||[]);
  if (ST.mid.length  > 900) ST.mid  = ST.mid.slice(-900);
  if (ST.tape.length > 120) ST.tape = ST.tape.slice(-120);
  if (d.log && d.log.length) ST.log = ST.log.concat(d.log).slice(-60);
  if (d.log_n != null) ST.logn = d.log_n;
  const sg = d.sig || {};
  ST.cand = sg.candles_full ? (sg.candles||[])
                            : mergeCandles(ST.cand, sg.candles||[]);
  sg.candles = ST.cand;
  ST.since = d.now || ST.since;
  d.mid = ST.mid; d.tape = ST.tape; d.log = ST.log;
  return d;
}

async function tick() {
  if (ST.busy) return;            // на медленной связи запросы не копятся
  ST.busy = true;
  let d;
  try {
    const r = await fetch(`/state?k=${encodeURIComponent(KEY)}`
      + (sym ? `&sym=${sym}` : "")
      + `&since=${ST.since}&logn=${ST.logn}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
    ST.fails = 0;
  } catch (e) {
    // Картинка не стирается: обрыв на секунду — не повод показать пустоту.
    ST.fails++;
    document.getElementById("sub").textContent =
      `связь потеряна (попыток ${ST.fails}), последние данные ниже`;
    return;
  } finally { ST.busy = false; }
  // Смена символа: чужие буферы выбрасываются. Если ответ был
  // разностным (спросили до смены), он не годится — ждём следующего,
  // который придёт полным. Склеить куски разных символов хуже, чем
  // подождать секунду.
  const fresh = d.sym !== ST.sym;
  if (fresh) { wipe(); ST.sym = d.sym; }
  sym = d.sym;
  if (fresh && !d.mid_full) return;
  render(merge(d));
}

function render(d) {
  const s = d.status;
  document.getElementById("sub").textContent =
    `${d.symbols.length} символов · сбор идёт ${(s.uptime_sec/3600).toFixed(1)} ч`;
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  const age = s.last_msg_age_sec;
  document.getElementById("strip").innerHTML =
    cell("сообщений", kk(s.messages)) +
    cell("в секунду", fmt(s.msg_per_sec, 0)) +
    cell("сделок", kk(s.trades)) +
    cell("книг готово", `${s.ready}/${d.symbols.length}`,
         s.ready === d.symbols.length ? "good" : "bad") +
    cell("сбросов", s.resets, s.resets ? "bad" : "") +
    cell("сделок закрыто", `${s.closed ?? 0}/${s.signals ?? 0}`) +
    cell("тишина, с", fmt(age, 1), age > 5 ? "bad" : "good");

  document.getElementById("syms").innerHTML = d.symbols.map(x =>
    `<button data-s="${x}" aria-pressed="${x === d.sym}">${
      x.replace("USDT","")}</button>`).join("")
    + `<a class="open" target="_blank" href="/chart?k=${
        encodeURIComponent(KEY)}&sym=${d.sym}">график ${
        d.sym.replace("USDT","")} ↗</a>`;
  document.querySelectorAll("[data-s]").forEach(b =>
    b.onclick = () => { sym = b.dataset.s; wipe(); ST.sym = sym; tick(); });

  const bk = d.book;
  const t = document.getElementById("book");
  if (!bk) { t.innerHTML = `<tr><td>книга ещё не готова</td></tr>`; }
  else {
    const mx = Math.max(...bk.a.map(r => r[1]), ...bk.b.map(r => r[1]), 1);
    const row = (r, cls) => `<tr class="${cls}">
      <td class="px mono">${r[0]}</td>
      <td class="sz mono"><span class="bar" style="width:${
        (r[1]/mx*100).toFixed(1)}%"></span>${fmt(r[1], 2)}</td>
      <td class="mono" style="color:var(--muted)">${kk(r[0]*r[1])}</td></tr>`;
    t.innerHTML =
      bk.a.slice().reverse().map(r => row(r, "a")).join("") +
      `<tr class="spread"><td colspan="3" class="mono">спред ${
        fmt((bk.ask-bk.bid)/bk.bid*1e4, 1)} б.п. · середина ${
        fmt((bk.ask+bk.bid)/2, 6)}</td></tr>` +
      bk.b.map(r => row(r, "b")).join("");
    document.getElementById("cap-book").textContent =
      `обновлений/с ${bk.upd} · видно ±${bk.reach_b}/${bk.reach_a} б.п.`;
    document.getElementById("bands").innerHTML = d.bands.map(b => {
      const tot = b.bid + b.ask || 1;
      // Полоса шире видимой книги содержит её целиком: подписка отдаёт
      // полсотни уровней, а не проценты. Помечена, чтобы одинаковые
      // числа в соседних строках не читались как измерение.
      return `<div class="band" ${b.beyond ? 'style="opacity:.5"' : ""}
        title="${b.beyond ? "шире видимой книги — это весь стакан" : ""}">
        <span class="n mono">±${b.w}%${b.beyond ? "*" : ""}</span>
        <span class="g"><i class="l" style="width:${
          (b.bid/tot*100).toFixed(1)}%"></i><i class="r" style="width:${
          (b.ask/tot*100).toFixed(1)}%"></i></span>
        <span class="q mono">${kk(b.bid/1e3)} / ${kk(b.ask/1e3)}</span></div>`;
    }).join("");
  }

  const tp = d.tape || [];
  document.getElementById("cap-tape").textContent = `${tp.length} последних`;
  document.getElementById("tape").innerHTML = tp.slice().reverse().map(x =>
    `<tr><td class="mono" style="color:var(--muted)">${
      new Date(x.ts).toISOString().slice(11,23)}</td>
     <td class="mono ${x.side>0?"buy":"sell"}">${x.side>0?"покупка":"продажа"}</td>
     <td class="mono">${x.p}</td>
     <td class="mono sz">${fmt(x.v,3)}</td>
     <td class="mono" style="color:var(--muted)">${kk(x.p*x.v)}</td></tr>`
  ).join("");

  const sg = d.sig || {levels:[], open:[], done:[], candles:[]};
  drawMid(d.mid || [], sg);
  document.getElementById("cap-diag").textContent =
    `история ${sg.history_min ?? 0} мин · до уровня ${
      sg.near_x ?? "—"} шума (нужно ≤ ${sg.touch_x})`;
  const dg = sg.diag || {};
  const drow = (name, m) => {
    m = m || {};
    const cell = (v, need, ok) => v === null || v === undefined
      ? `<td class="mono" style="color:var(--muted)">—</td>`
      : `<td class="mono ${ok?"buy":"sell"}">${v}${need}</td>`;
    return `<tr><td>${name}</td>
      ${cell(m.vol_x, "×", m.vol_x >= (sg.vol_mult||5))}
      ${cell(m.imb, "", m.imb >= (sg.imb||0.3))}
      ${cell(m.move_x, "", m.move_x !== undefined && m.move_x >= -1)}
      <td class="mono" style="color:var(--muted)">${m.why || "—"}</td></tr>`;
  };
  document.getElementById("diag").innerHTML =
    `<tr><td style="color:var(--muted);font-size:11.5px">сторона</td>
      <td style="color:var(--muted);font-size:11.5px">объём</td>
      <td style="color:var(--muted);font-size:11.5px">перевес</td>
      <td style="color:var(--muted);font-size:11.5px">ход</td>
      <td style="color:var(--muted);font-size:11.5px">итог</td></tr>`
    + drow("поглощение продаж · лонг", dg.long)
    + drow("поглощение покупок · шорт", dg.short);
  const all = sg.open.concat(sg.done).slice(0, 12);
  document.getElementById("cap-sig").textContent =
    `открыто ${sg.open.length} · шум ${sg.noise_bp ?? "—"} б.п. · уровней ${
      sg.levels.length}`;
  document.getElementById("sig").innerHTML = all.length
    ? all.map(x => `<tr>
        <td class="mono" style="color:var(--muted)">${
          new Date(x.t*1000).toISOString().slice(11,19)}</td>
        <td class="mono ${x.long?"buy":"sell"}">${x.long?"лонг":"шорт"}</td>
        <td class="mono">${x.entry}</td>
        <td class="mono" style="color:var(--muted)">${x.kind}</td>
        <td class="mono">1:${x.rr}</td>
        <td class="mono">${x.state}</td>
        <td class="mono ${x.pnl_bp>0?"buy":"sell"}">${x.pnl_bp == null ? "—"
          : (x.pnl_bp>0?"+":"") + x.pnl_bp + " б.п. · "
            + (x.r>0?"+":"") + x.r + " R"}</td>
      </tr>`).join("")
    : `<tr><td style="color:var(--muted);padding:8px 10px">событий пока нет</td></tr>`;
  const lg = document.getElementById("log");
  lg.textContent = (d.log || []).join("\n");
}

function drawMid(pts, sg) {
  const cv = document.getElementById("mid");
  const dpr = Math.min(devicePixelRatio||1, 2), W = cv.clientWidth, H = 140;
  cv.width = W*dpr; cv.height = H*dpr; cv.style.height = H+"px";
  const g = cv.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);
  if (pts.length < 2) {
    g.fillStyle = css("--muted");
    g.font = "12px system-ui"; g.textBaseline = "middle";
    g.fillText("копим историю…", 10, H/2);
    return;
  }
  // В шкалу входят и уровни со сделками: иначе метка окажется за краем,
  // и «сделки не видно» будет означать не отсутствие, а обрезку.
  const near = (sg.levels||[]).map(l=>l.p).filter(p =>
    p > Math.min(...pts.map(q=>q[1]))*0.995 &&
    p < Math.max(...pts.map(q=>q[1]))*1.005);
  const marks = (sg.open||[]).concat(sg.done||[]).slice(0,8);
  const extra = marks.flatMap(m=>[m.entry, m.stop, m.target]);
  const vals = pts.map(p=>p[1]).concat(near, extra);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi-lo)*0.08 || 1e-9;
  const y = v => 8 + (H-24)*(hi+pad-v)/((hi-lo)+2*pad);
  const x = i => 6 + (W-70)*i/(pts.length-1);
  g.strokeStyle = css("--grid");
  for (let k=0;k<=2;k++){const yy=8+(H-24)*k/2;
    g.beginPath();g.moveTo(6,yy);g.lineTo(W-64,yy);g.stroke();}
  // Уровни — горизонтали; вид подписан, чтобы было видно, откуда взялся.
  for (const l of (sg.levels||[])) {
    if (l.p < lo || l.p > hi) continue;
    g.save(); g.strokeStyle = css("--accent"); g.globalAlpha = .5;
    g.setLineDash(l.kind === "полка" ? [] : [3,3]);
    g.beginPath(); g.moveTo(6, y(l.p)); g.lineTo(W-64, y(l.p)); g.stroke();
    g.restore();
    g.fillStyle = css("--muted");
    g.font = "10px ui-monospace, Menlo, monospace"; g.textBaseline = "middle";
    g.fillText(l.kind, 9, y(l.p) - 6);
  }
  g.strokeStyle = css("--ink"); g.lineWidth = 1.5; g.globalAlpha = .85;
  g.beginPath();
  pts.forEach((p,i)=> i?g.lineTo(x(i),y(p[1])):g.moveTo(x(i),y(p[1])));
  g.stroke(); g.globalAlpha = 1;

  // Сделки: вход треугольником по направлению, стоп и цель отрезками
  // вправо от входа — там, где сделка живёт.
  const t0 = pts[0][0], t1 = pts[pts.length-1][0];
  const xt = t => 6 + (W-70)*Math.max(0, Math.min(1, (t-t0)/Math.max(t1-t0,1)));
  for (const m of marks) {
    const xa = xt(m.t), xb = W-64;
    const seg = (v, color, dash) => {
      if (v < lo || v > hi) return;
      g.save(); g.strokeStyle = color; g.setLineDash(dash); g.lineWidth = 1.2;
      g.beginPath(); g.moveTo(xa, y(v)); g.lineTo(xb, y(v)); g.stroke();
      g.restore();
    };
    seg(m.stop, css("--ask"), [2,3]);
    seg(m.target, css("--bid"), [2,3]);
    g.fillStyle = css("--ink");
    const yy = y(m.entry), d = m.long ? 1 : -1;
    g.beginPath(); g.moveTo(xa, yy);
    g.lineTo(xa-5, yy+9*d); g.lineTo(xa+5, yy+9*d);
    g.closePath(); g.fill();
  }
  g.fillStyle = css("--muted");
  g.font = "11px ui-monospace, Menlo, monospace"; g.textBaseline="middle";
  g.fillText(hi.toPrecision(7), W-60, y(hi));
  g.fillText(lo.toPrecision(7), W-60, y(lo));
  document.getElementById("cap-mid").textContent =
    ((pts[pts.length-1][1]/pts[0][1]-1)*1e4).toFixed(1) + " б.п. за окно";
}

tick(); timer = setInterval(tick, 1000);
</script>
"""


CHART = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>График живьём</title>
<style>
:root{color-scheme:light dark;
 --ground:#f6f7f9;--panel:#fff;--ink:#141a21;--muted:#5c6673;--rule:#dfe4ea;
 --bid:#1f7a56;--ask:#b8452c;--accent:#a97514;--grid:#eef1f5}
@media(prefers-color-scheme:dark){:root{
 --ground:#0c1015;--panel:#131922;--ink:#e4e9f0;--muted:#8b95a4;--rule:#212936;
 --bid:#35a877;--ask:#d4614a;--accent:#d7a24a;--grid:#1a212c}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
 font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.wrap{max-width:1180px;margin:0 auto;padding:12px 12px 40px}
.bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:10px}
h1{font-size:17px;margin:0 8px 0 0}
button,a.btn{font:inherit;font-size:13px;color:var(--ink);
 background:var(--panel);border:1px solid var(--rule);padding:4px 9px;
 cursor:pointer;text-decoration:none}
button[aria-pressed=true]{border-color:var(--accent);
 box-shadow:inset 0 -2px 0 var(--accent)}
.sp{flex:1 1 auto}
.panel{background:var(--panel);border:1px solid var(--rule);
 margin-bottom:10px;position:relative}
.cap{padding:6px 10px;border-bottom:1px solid var(--rule);font-size:11.5px;
 color:var(--muted);letter-spacing:.05em;text-transform:uppercase;
 display:flex;justify-content:space-between;gap:8px}
canvas{display:block;width:100%;touch-action:none}
#tip{position:absolute;z-index:5;pointer-events:none;display:none;
 background:var(--panel);border:1px solid var(--rule);padding:7px 9px;
 font-size:12.5px;line-height:1.4;box-shadow:0 6px 20px rgba(0,0,0,.18)}
#tip .r{display:flex;justify-content:space-between;gap:14px}
#tip .r span:first-child{color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:5px 9px;text-align:right;white-space:nowrap;
 border-bottom:1px solid var(--rule)}
th{color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.05em;
 text-transform:uppercase;position:sticky;top:0;background:var(--panel)}
td:first-child,th:first-child{text-align:left}
.buy{color:var(--bid)} .sell{color:var(--ask)}
.hist{max-height:300px;overflow-y:auto}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;
 color:var(--muted);margin:8px 0 12px}
.sw{display:inline-block;width:20px;height:0;border-top:2px solid;
 vertical-align:4px;margin-right:6px}
.stats{display:flex;flex-wrap:wrap;gap:1px;background:var(--rule)}
.st{flex:1 1 108px;background:var(--panel);padding:7px 10px}
.st .k{font-size:11px;color:var(--muted);letter-spacing:.04em}
.st .v{font-size:15px;margin-top:2px}
.note{padding:10px;color:var(--muted);font-size:13px}
</style>
<div class="wrap">
<div class="bar">
  <h1 id="ttl" class="mono">…</h1>
  <span id="syms"></span>
  <span class="sp"></span>
  <button id="fit">весь период</button>
  <button id="live" aria-pressed="true">следить за краем</button>
  <a class="btn" href="/" id="home">к обзору</a>
</div>
<div class="panel">
  <div class="cap"><span id="cap">минутные свечи · тяните, колесо или щипок — масштаб</span>
    <span id="cap2" class="mono"></span></div>
  <canvas id="px" height="420"></canvas>
  <div id="tip" class="mono"></div>
</div>
<div class="legend">
  <span><span class="sw" style="border-color:var(--accent)"></span>уровень</span>
  <span><span class="sw" style="border-color:var(--ask)"></span>стоп</span>
  <span><span class="sw" style="border-color:var(--bid)"></span>цель</span>
  <span><span class="sw" style="border-color:var(--ink)"></span>вход и выход</span>
</div>
<div class="panel">
  <div class="cap"><span>итог бумажных сделок по этой монете</span>
    <button id="unit" style="padding:1px 7px">в R</button></div>
  <div id="sum" class="stats"></div>
  <canvas id="eq"></canvas>
</div>
<div class="panel">
  <div class="cap"><span>история сделок — бумажные, наблюдение</span>
    <span id="cap3" class="mono"></span></div>
  <div class="hist"><table><thead><tr>
    <th>время</th><th>сторона</th><th>вход</th><th>стоп</th><th>цель</th>
    <th>уровень</th><th>отн.</th><th>состояние</th><th>держали</th><th>итог</th>
  </tr></thead><tbody id="rows"></tbody></table></div>
</div>
</div>
<script>
const Q = new URLSearchParams(location.search);
const KEY = Q.get("k") || "";
let sym = Q.get("sym") || "";
let data = null, view = null, follow = true, HIT = [];
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();
const stamp = t => new Date(t*1000).toISOString().slice(11,16);

// Опрос разностный — см. тот же приём на странице обзора.
const ST = {cand:[], since:0, sym:"", busy:false, fails:0};
const HIST = {trades:[], stats:null, equity:[], at:0, busy:false};
// Единица кривой счёта: базисные пункты — сколько денег при равном
// размере позиции, R — сколько при равном риске на сделку. Это разные
// вопросы, поэтому переключатель, а не выбор раз и навсегда.
let EQR = false;
function wipe() { ST.cand=[]; ST.since=0;
                  HIST.trades=[]; HIST.stats=null; HIST.equity=[]; HIST.at=0; }
function mergeCandles(old, add) {
  if (!add.length) return old;
  const m = new Map(old.map(c => [c[0], c]));
  for (const c of add) m.set(c[0], c);
  return [...m.values()].sort((a,b) => a[0]-b[0]).slice(-1440);
}

async function history() {
  // История сделок — не поток: она меняется раз в минуты, а опрос идёт
  // раз в секунду. Тянуть её вместе с состоянием значит платить за неё
  // каждую секунду.
  if (HIST.busy || Date.now() - HIST.at < 15000) return;
  HIST.busy = true;
  try {
    const r = await fetch(`/trades?k=${encodeURIComponent(KEY)}&sym=${sym}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    HIST.trades = h.trades || []; HIST.stats = h.stats;
    HIST.equity = h.equity || []; HIST.at = Date.now();
  } catch (e) { /* тихо: следующий круг попробует снова */ }
  finally { HIST.busy = false; }
}

async function pull() {
  if (ST.busy) return;
  ST.busy = true;
  let d;
  try {
    const r = await fetch(`/state?k=${encodeURIComponent(KEY)}&sym=${sym}`
      + `&since=${ST.since}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
    ST.fails = 0;
  } catch (e) {
    ST.fails++;
    document.getElementById("cap2").textContent =
      `связь потеряна (попыток ${ST.fails}), картинка прежняя`;
    return;
  } finally { ST.busy = false; }
  const fresh = d.sym !== ST.sym;
  if (fresh) { wipe(); ST.sym = d.sym; }
  if (fresh && !(d.sig || {}).candles_full) { sym = d.sym; return; }
  const sg = d.sig || {};
  ST.cand = sg.candles_full ? (sg.candles||[])
                            : mergeCandles(ST.cand, sg.candles||[]);
  sg.candles = ST.cand;
  ST.since = d.now || ST.since;
  data = d;
  history();
  sym = data.sym;
  document.getElementById("ttl").textContent = sym;
  document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
  document.getElementById("syms").innerHTML = data.symbols.map(x =>
    `<button data-s="${x}" aria-pressed="${x===sym}">${
      x.replace("USDT","")}</button>`).join(" ");
  document.querySelectorAll("[data-s]").forEach(b => b.onclick = () => {
    sym = b.dataset.s; view = null; follow = true; wipe(); ST.sym = sym;
    window.history.replaceState(
      null, "", `?k=${encodeURIComponent(KEY)}&sym=${sym}`);
    pull();
  });
  draw(); rows(); summary();
}

function cands() { return (data && data.sig && data.sig.candles) || []; }
function trades() {
  // История берётся из отдельного запроса: в состоянии лежат только
  // последние двадцать закрытых, чтобы не гонять сотни каждую секунду.
  const sg = (data && data.sig) || {};
  return (sg.open||[]).concat(
    HIST.trades.length ? HIST.trades : (sg.done||[]));
}
function res(m) {
  return m.pnl_bp == null ? `<span style="color:var(--muted)">—</span>`
    : `<span class="${m.pnl_bp>0?"buy":"sell"}">${m.pnl_bp>0?"+":""}${
        m.pnl_bp} б.п. · ${m.r>0?"+":""}${m.r} R</span>`;
}

function draw() {
  const c = cands();
  const cv = document.getElementById("px");
  const dpr = Math.min(devicePixelRatio||1, 2);
  const W = cv.clientWidth, H = 420;
  cv.width = W*dpr; cv.height = H*dpr; cv.style.height = H+"px";
  const g = cv.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);
  if (c.length < 2) {
    g.fillStyle = css("--muted"); g.font = "13px system-ui";
    g.textBaseline = "middle";
    g.fillText("копим историю — свечи появятся через пару минут", 12, H/2);
    return;
  }
  if (!view) view = { i0: Math.max(0, c.length-90), n: Math.min(90, c.length) };
  // Следить за краем: если пользователь не уводил окно, оно едет за
  // последней свечой; уведёт — остаётся там, где поставил.
  if (follow) view.i0 = Math.max(0, c.length - view.n);
  view.n = Math.max(15, Math.min(view.n, c.length));
  view.i0 = Math.max(0, Math.min(c.length - view.n, view.i0));
  const i0 = Math.round(view.i0), i1 = Math.min(c.length, i0 + view.n);

  const padL=6, padR=70, padT=10, padB=20;
  const pw = W-padL-padR, ph = H-padT-padB;
  const lv = (data.sig.levels||[]);
  const tr = trades();
  let lo = Infinity, hi = -Infinity;
  for (let i=i0;i<i1;i++){ lo=Math.min(lo,c[i][3]); hi=Math.max(hi,c[i][2]); }
  const t0 = c[i0][0], t1 = c[i1-1][0];
  for (const l of lv) if (l.p>lo*0.99 && l.p<hi*1.01){
    lo=Math.min(lo,l.p); hi=Math.max(hi,l.p); }
  for (const m of tr) if (m.t>=t0-3600 && m.t<=t1+3600){
    lo=Math.min(lo,m.stop,m.target,m.entry);
    hi=Math.max(hi,m.stop,m.target,m.entry); }
  const pad=(hi-lo)*0.06||1e-9; lo-=pad; hi+=pad;
  const y = v => padT + ph*(hi-v)/(hi-lo);
  const x = i => padL + pw*(i-i0+0.5)/(i1-i0);
  const xt = t => padL + pw*((t-t0)/Math.max(t1-t0,1)*(i1-i0-1)+0.5)/(i1-i0);
  const dec = Math.max(2, Math.ceil(-Math.log10((hi-lo)/50)));

  g.strokeStyle = css("--grid"); g.lineWidth = 1;
  g.fillStyle = css("--muted"); g.font = "11px ui-monospace, Menlo, monospace";
  g.textBaseline = "middle";
  for (let k=0;k<=4;k++){
    const v = hi-(hi-lo)*k/4;
    g.beginPath(); g.moveTo(padL,y(v)); g.lineTo(W-padR,y(v)); g.stroke();
    g.fillText(v.toFixed(dec), W-padR+5, y(v));
  }
  for (const l of lv) {
    if (l.p<lo||l.p>hi) continue;
    g.save(); g.strokeStyle=css("--accent"); g.globalAlpha=.55;
    g.setLineDash(l.kind==="полка"?[]:[3,3]);
    g.beginPath(); g.moveTo(padL,y(l.p)); g.lineTo(W-padR,y(l.p)); g.stroke();
    g.restore();
    g.fillStyle=css("--muted"); g.fillText(l.kind, padL+4, y(l.p)-7);
  }
  const cw = Math.max(1, pw/(i1-i0)*0.62);
  for (let i=i0;i<i1;i++){
    const up = c[i][4] >= c[i][1];
    g.strokeStyle = g.fillStyle = up ? css("--bid") : css("--ask");
    g.beginPath(); g.moveTo(x(i),y(c[i][2])); g.lineTo(x(i),y(c[i][3]));
    g.stroke();
    const yo=y(c[i][1]), yc=y(c[i][4]);
    g.fillRect(x(i)-cw/2, Math.min(yo,yc), cw, Math.max(Math.abs(yc-yo),1));
  }
  HIT = [];
  for (const m of tr) {
    if (m.t < t0-60 || m.t > t1+60) continue;
    const xa = xt(m.t), xb = W-padR;
    const seg=(v,col,dash)=>{ if(v<lo||v>hi) return;
      g.save(); g.strokeStyle=col; g.setLineDash(dash); g.lineWidth=1.2;
      g.beginPath(); g.moveTo(xa,y(v)); g.lineTo(xb,y(v)); g.stroke(); g.restore(); };
    seg(m.stop, css("--ask"), [3,3]);
    seg(m.target, css("--bid"), [3,3]);
    g.fillStyle = css("--ink");
    const yy=y(m.entry), d = m.long?1:-1;
    g.beginPath(); g.moveTo(xa,yy); g.lineTo(xa-6,yy+11*d);
    g.lineTo(xa+6,yy+11*d); g.closePath(); g.fill();
    const ya=y(Math.max(m.stop,m.target)), yb=y(Math.min(m.stop,m.target));
    const h2=Math.max(yb-ya,20);
    HIT.push({m, x0:xa-10, x1:xb, y0:(ya+yb)/2-h2/2, y1:(ya+yb)/2+h2/2});
  }
  g.fillStyle = css("--muted"); g.textBaseline="alphabetic";
  g.fillText(stamp(t0), padL, H-6);
  g.textAlign="right"; g.fillText(stamp(t1), W-padR, H-6); g.textAlign="left";
  document.getElementById("cap2").textContent =
    `${i1-i0} из ${c.length} мин · ${stamp(t0)}—${stamp(t1)}`;
  document.getElementById("cap3").textContent = `${tr.length} сделок`;
}

function rows() {
  const tr = trades();
  document.getElementById("rows").innerHTML = tr.length ? tr.map(m => `
    <tr><td class="mono">${stamp(m.t)}</td>
    <td class="${m.long?"buy":"sell"}">${m.long?"лонг":"шорт"}</td>
    <td class="mono">${m.entry}</td><td class="mono">${m.stop}</td>
    <td class="mono">${m.target}</td>
    <td style="color:var(--muted)">${m.kind}</td>
    <td class="mono">1:${m.rr}</td><td>${m.state}</td>
    <td class="mono">${m.held} с</td>
    <td class="mono">${res(m)}</td></tr>`
  ).join("") : `<tr><td colspan="10" style="color:var(--muted)">
    событий пока нет — детектор ждёт совпадения условий</td></tr>`;
}

function summary() {
  const s = HIST.stats, box = document.getElementById("sum");
  const pc = v => (v*100).toFixed(0) + " %";
  if (!s) {
    box.innerHTML = `<div class="note">закрытых сделок пока нет</div>`;
  } else {
    const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
      <div class="v mono ${cls||""}">${v}</div></div>`;
    // Доля побед сравнивается с безубыточной, а не с половиной: при
    // отношении 1:3 выигрывать нужно каждую четвёртую, и «мало побед»
    // само по себе ничего не значит.
    box.innerHTML =
      cell("сделок", s.trades) +
      cell("побед", pc(s.win_rate),
           s.win_rate >= s.break_even ? "buy" : "sell") +
      cell("безубыточно", pc(s.break_even)) +
      cell("ожидание", (s.expectancy_bp>0?"+":"") +
           s.expectancy_bp.toFixed(1) + " б.п.",
           s.expectancy_bp > 0 ? "buy" : "sell") +
      cell("в риске", (s.expectancy_r>0?"+":"") + s.expectancy_r.toFixed(2)
           + " R", s.expectancy_r > 0 ? "buy" : "sell") +
      cell("медиана", s.median_bp.toFixed(1) + " б.п.") +
      cell("стоп", s.stop_bp_median.toFixed(0) + " б.п.") +
      cell("цель / стоп / время",
           `${pc(s.share_target)} / ${pc(s.share_stop)} / ${pc(s.share_time)}`) +
      (s.cut_by_restart
        ? cell("оборвано", s.cut_by_restart, "sell") : "");
  }
  drawEq();
}

function drawEq() {
  const cv = document.getElementById("eq"), pts = HIST.equity || [];
  const dpr = Math.min(devicePixelRatio||1, 2), W = cv.clientWidth, H = 110;
  cv.width = W*dpr; cv.height = H*dpr; cv.style.height = H+"px";
  const g = cv.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);
  if (pts.length < 2) {
    g.fillStyle = css("--muted"); g.font = "12px system-ui";
    g.textBaseline = "middle";
    g.fillText(pts.length ? "одна сделка — кривой ещё нет"
                          : "кривая появится после двух закрытых сделок",
               10, H/2);
    return;
  }
  const k = EQR ? 2 : 1;
  const v = pts.map(p => p[k]);
  const lo = Math.min(0, ...v), hi = Math.max(0, ...v);
  const y = q => 8 + (H-26)*(hi-q)/((hi-lo)||1e-9);
  const x = i => 6 + (W-70)*i/(pts.length-1);
  g.strokeStyle = css("--grid");
  g.beginPath(); g.moveTo(6, y(0)); g.lineTo(W-64, y(0)); g.stroke();
  g.strokeStyle = v[v.length-1] >= 0 ? css("--bid") : css("--ask");
  g.lineWidth = 1.6; g.beginPath();
  v.forEach((q,i) => i ? g.lineTo(x(i), y(q)) : g.moveTo(x(i), y(q)));
  g.stroke();
  g.fillStyle = css("--muted");
  g.font = "11px ui-monospace, Menlo, monospace"; g.textBaseline = "middle";
  const u = EQR ? " R" : " б.п.";
  g.fillText(hi.toFixed(EQR?1:0) + u, W-60, y(hi));
  g.fillText(lo.toFixed(EQR?1:0) + u, W-60, y(lo));
}

const px = document.getElementById("px"), tip = document.getElementById("tip");
let drag=null, pinch=null;
px.addEventListener("pointerdown", e => {
  px.setPointerCapture(e.pointerId); drag={x:e.clientX, i0:view?view.i0:0}; });
px.addEventListener("pointermove", e => {
  if (!drag) { hover(e); return; }
  const c = cands(); if (!c.length || !view) return;
  follow = false; document.getElementById("live").setAttribute("aria-pressed","false");
  const per = px.clientWidth/view.n;
  view.i0 = Math.max(0, Math.min(c.length-view.n,
                                 drag.i0 - (e.clientX-drag.x)/per));
  draw();
});
px.addEventListener("pointerup", e => {
  if (drag && Math.abs(e.clientX-drag.x) < 6) hover(e);
  drag = null; });
px.addEventListener("pointerleave", () => { tip.style.display="none"; });
px.addEventListener("wheel", e => {
  e.preventDefault(); zoom(e.deltaY>0?1.15:1/1.15, e.offsetX/px.clientWidth);
}, {passive:false});
px.addEventListener("touchstart", e => { if (e.touches.length===2){
  drag=null; pinch=dist(e); } }, {passive:true});
px.addEventListener("touchmove", e => { if (e.touches.length===2 && pinch){
  const d=dist(e); zoom(pinch/d, .5); pinch=d; } }, {passive:true});
px.addEventListener("touchend", () => { pinch=null; });
function dist(e){ return Math.hypot(
  e.touches[0].clientX-e.touches[1].clientX,
  e.touches[0].clientY-e.touches[1].clientY); }
function zoom(k, anchor) {
  const c = cands(); if (!c.length || !view) return;
  const n0 = view.n;
  view.n = Math.max(15, Math.min(c.length, Math.round(view.n*k)));
  view.i0 = Math.max(0, Math.min(c.length-view.n, view.i0+(n0-view.n)*anchor));
  if (view.i0 + view.n < c.length - 1) {
    follow = false;
    document.getElementById("live").setAttribute("aria-pressed","false");
  }
  draw();
}
function hover(e) {
  const r = px.getBoundingClientRect();
  const mx = e.clientX-r.left, my = e.clientY-r.top;
  const h = HIT.find(z => mx>=z.x0 && mx<=z.x1 && my>=z.y0 && my<=z.y1);
  if (!h) { tip.style.display="none"; return; }
  const m = h.m;
  const row=(k,v,cls)=>`<div class="r"><span>${k}</span>
    <span class="${cls||""}">${v}</span></div>`;
  tip.innerHTML = `<div style="font-weight:650;margin-bottom:3px">${
      m.long?"лонг":"шорт"} · ${m.state}</div>`
    + row("время", stamp(m.t)) + row("вход", m.entry)
    + row("стоп", m.stop) + row("цель", m.target)
    + row("уровень", `${m.level} (${m.kind})`)
    + row("отношение", "1:"+m.rr) + row("держали", m.held+" с")
    + row("итог", `${m.pnl_bp>0?"+":""}${m.pnl_bp} б.п. · ${
        m.r>0?"+":""}${m.r} R`, m.pnl_bp>0?"buy":"sell");
  tip.style.display="block";
  tip.style.left = Math.max(4, Math.min(px.clientWidth-tip.offsetWidth-4,
                                        mx+14))+"px";
  tip.style.top = Math.max(4, my+18)+"px";
}
document.getElementById("fit").onclick = () => {
  const c = cands(); if (!c.length) return;
  view = {i0:0, n:c.length}; follow=false;
  document.getElementById("live").setAttribute("aria-pressed","false"); draw();
};
document.getElementById("live").onclick = e => {
  follow = !follow; e.target.setAttribute("aria-pressed", String(follow));
  draw();
};
document.getElementById("unit").onclick = e => {
  EQR = !EQR; e.target.textContent = EQR ? "в б.п." : "в R"; drawEq();
};
window.addEventListener("resize", () => { draw(); drawEq(); });
pull(); setInterval(pull, 1000);
</script>
"""


def serve(collector, port, token, log):
    """Поднять сервер наблюдения в отдельном потоке."""

    class H(BaseHTTPRequestHandler):
        def _ok(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _deny(self):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"nope")

        def do_GET(self):                                 # noqa: N802
            u = urlparse(self.path)
            q = parse_qs(u.query)
            # Сравнение за постоянное время: страница стоит открытым
            # портом, и обычное `!=` отвечает тем быстрее, чем раньше
            # разошлись строки, то есть подсказывает ключ по знаку.
            if token and not secrets.compare_digest(
                    q.get("k", [""])[0], token):
                return self._deny()
            if u.path == "/state":
                def num(name, default=0.0):
                    try:
                        return float(q.get(name, [""])[0])
                    except ValueError:
                        return default
                body = json.dumps(
                    collector.snapshot(q.get("sym", [None])[0],
                                       since=num("since"),
                                       logn=num("logn", None)),
                    ensure_ascii=False).encode("utf-8")
                return self._ok(body, "application/json; charset=utf-8")
            if u.path == "/trades":
                return self._ok(json.dumps(
                    collector.trades(q.get("sym", [None])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/chart":
                return self._ok(CHART.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path in ("/", "/index.html"):
                return self._ok(PAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):                        # тишина в консоли
            return

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"страница наблюдения: http://<адрес сервера>:{port}/"
        + (f"?k={token}" if token else ""))
    return srv
