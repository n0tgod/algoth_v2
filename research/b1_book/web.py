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

import gzip
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Order Book Live</title>
<style>
/* Палитра — общая на все страницы: наследие v1 (тёмный фиолет, пурпур
   #9747ff) в современном исполнении. Тема одна, настроек внешнего вида
   нет — правило v2. */
:root{color-scheme:dark;
 --ground:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff;--grid:#1c1839}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,
  var(--ground);
 color:var(--ink);
 font:14px/1.5 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.wrap{max-width:1000px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none;white-space:nowrap}
.brand b{color:var(--accent);font-weight:800}
.tag{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);border:1px solid var(--rule);border-radius:999px;
 padding:4px 10px;background:rgba(151,71,255,.06);white-space:nowrap}
.sp{flex:1 1 auto}
.sub{color:var(--muted);font-size:12.5px;margin:0}
.strip{display:grid;gap:8px;
 grid-template-columns:repeat(auto-fit,minmax(104px,1fr));margin-bottom:12px}
.st{background:linear-gradient(180deg,rgba(151,71,255,.06),
  rgba(151,71,255,0) 55%),var(--panel);
 border:1px solid var(--rule);border-radius:12px;padding:9px 11px}
.st .k{font-size:9.5px;color:var(--muted);letter-spacing:.1em;
 text-transform:uppercase}
.st .v{font-size:14.5px;font-weight:600;margin-top:3px}
.bad{color:var(--ask)} .good{color:var(--bid)}
.k{color:var(--muted);font-size:12px}
.syms{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;align-items:center}
.pick{padding:8px 10px}
.pickwrap>summary{list-style:none}
.pickwrap>summary::-webkit-details-marker{display:none}
.pick input{width:100%;font:inherit;font-size:16px;color:var(--ink);
 background:var(--chip);border:1px solid var(--rule);border-radius:10px;
 padding:7px 10px;margin-bottom:6px}
details.grp{border-top:1px solid var(--rule-soft)}
details.grp summary::-webkit-details-marker{display:none}
details.grp summary{cursor:pointer;padding:6px 2px;font-size:12px;
 color:var(--muted);letter-spacing:.03em;list-style:none;
 display:flex;justify-content:space-between}
details.grp summary::after{content:"▸";color:var(--muted)}
details.grp[open] summary::after{content:"▾"}
details.grp .gs{display:flex;flex-wrap:wrap;gap:5px;padding:2px 0 8px;max-height:38vh;overflow-y:auto}
.modelbox{padding:8px 12px;font-size:13px}
.modelbox .mline{color:var(--muted);font-size:12px;margin-bottom:6px}
.thoughts{max-height:230px;overflow-y:auto;font-size:12.5px;
 white-space:pre-wrap;line-height:1.5}
.thoughts .tt{color:var(--muted)}
.mtr{width:100%;border-collapse:collapse;font-size:11.5px}
.mtr th{text-align:left;color:var(--muted);font-weight:500;font-size:10px;
 letter-spacing:.08em;text-transform:uppercase;
 padding:2px 6px 3px 0;border-bottom:1px solid var(--rule)}
.mtr td{padding:2px 6px 2px 0;white-space:nowrap}
.mtr tr.good td:nth-child(8){color:var(--bid)}
.mtr tr.bad td:nth-child(8){color:var(--ask)}
.mtr tr.dim td{color:var(--muted)}
@media(max-width:640px){
 .wrap{padding:10px 8px 30px}
 button{padding:8px 12px;font-size:13.5px}
 .strip{grid-template-columns:repeat(auto-fit,minmax(84px,1fr));gap:6px}
 td{padding:3px 7px}
 .tape{max-height:240px}
}
.open{font-size:12px;color:var(--ink);background:var(--chip);
 border:1px solid var(--accent);border-radius:999px;padding:3px 10px;
 text-decoration:none}
.open:hover{background:rgba(151,71,255,.14)}
button{font:inherit;font-size:12.5px;color:var(--muted);
 background:var(--chip);border:1px solid var(--rule);border-radius:999px;
 padding:4px 11px;cursor:pointer;
 transition:border-color .15s,color .15s}
button:hover{color:var(--ink);border-color:var(--accent)}
button[aria-pressed=true]{color:var(--ink);border-color:var(--accent);
 background:rgba(151,71,255,.14)}
.cols{display:grid;gap:12px;grid-template-columns:1fr}
@media(min-width:760px){.cols{grid-template-columns:1fr 1fr}}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:16px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.cap{padding:8px 12px;border-bottom:1px solid var(--rule-soft);
 font-size:10.5px;color:var(--muted);letter-spacing:.12em;
 text-transform:uppercase;display:flex;justify-content:space-between;gap:8px}
table{border-collapse:collapse;width:100%;font-size:13px}
td{padding:2px 9px;position:relative;white-space:nowrap}
td.sz{text-align:right;width:38%}
td.px{width:34%}
.bar{position:absolute;top:1px;bottom:1px;opacity:.16}
tr.a .bar{background:var(--ask);right:0}
tr.b .bar{background:var(--bid);right:0}
tr.a td.px{color:var(--ask)} tr.b td.px{color:var(--bid)}
.spread{background:var(--chip);font-size:12px;color:var(--muted)}
.tape{max-height:330px;overflow-y:auto}
.tape td{padding:1px 9px}
.buy{color:var(--bid)} .sell{color:var(--ask)}
canvas{display:block;width:100%}
.log{max-height:150px;overflow-y:auto;padding:6px 12px;font-size:12px;
 color:var(--muted);white-space:pre-wrap}
.bands{padding:8px 12px}
.band{display:flex;align-items:center;gap:6px;margin:3px 0;font-size:12px}
.band .n{width:52px;color:var(--muted);text-align:right}
.band .g{flex:1;display:flex;height:12px;background:var(--grid);
 border-radius:4px;overflow:hidden}
.band .g i{display:block;height:100%}
.band .g .l{background:var(--bid);margin-left:auto}
.band .g .r{background:var(--ask)}
.band .q{width:96px;text-align:center;color:var(--muted)}
footer{color:var(--muted);font-size:12px;margin-top:16px;line-height:1.7}
</style>
<div class="wrap">
<header class="top">
  <span class="brand">ALG<b>O</b>TH</span>
  <span class="tag">order book · live</span>
  <span class="sp"></span>
  <span class="sub" id="sub">connecting…</span>
</header>
<div class="strip" id="strip"></div>
<details class="panel pickwrap" style="margin-bottom:12px">
  <summary class="cap" style="cursor:pointer"><span>coins by sector</span>
    <span id="cap-syms" class="mono"></span></summary>
  <div class="pick">
    <input id="symq" placeholder="search coin…" autocomplete="off">
    <div id="groups"></div>
  </div>
</details>
<div class="panel" style="margin-bottom:12px">
  <div class="cap"><span>model — hypothesis 6, observation</span>
    <span id="cap-model" class="mono"></span></div>
  <div class="modelbox" id="modelbox">…</div>
</div>
<div class="panel" style="margin-bottom:12px">
  <div class="cap"><span>execution core — Rust shadow</span>
    <span id="cap-bot" class="mono"></span></div>
  <div class="note" id="botbox">…</div>
</div>
<div class="cols">
  <div class="panel">
    <div class="cap"><span>order book</span><span id="cap-book" class="mono"></span></div>
    <table id="book"></table>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>depth by bands, k$</span></div>
    <div class="bands" id="bands"></div>
  </div>
  <div class="panel">
    <div class="cap"><span>mid price, last 15 min</span>
      <span id="cap-mid" class="mono"></span></div>
    <canvas id="mid" height="140"></canvas>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>detector — conditions right now</span>
      <span id="cap-diag" class="mono"></span></div>
    <table id="diag"></table>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>paper trades — observation, not trading</span>
      <span id="cap-sig" class="mono"></span></div>
    <table id="sig"></table>
    <div class="cap" style="border-top:1px solid var(--rule)">
      <span>tape</span><span id="cap-tape" class="mono"></span></div>
    <div class="tape"><table id="tape"></table></div>
  </div>
</div>
<div class="panel" style="margin-top:12px">
  <div class="cap"><span>paper trades summary, all coins</span>
    <span id="cap-all" class="mono"></span></div>
  <div id="sum2" class="strip" style="margin:0;border:0"></div>
  <div id="rules2"></div>
  <div id="recbox"></div>
  <canvas id="eq2" height="110"></canvas>
  <div class="tape" style="max-height:260px"><table id="alltr"></table></div>
</div>
<div class="panel" style="margin-top:12px">
  <div class="cap"><span>collector log</span></div>
  <div class="log mono" id="log"></div>
</div>
<footer>Updates once a second. Book — the execution venue&#39;s
orderbook.50 topic; trade side is the aggressor&#39;s.</footer>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
let sym = null, timer = null;
// Состояния, виды уровней и правила приходят с сервера по-русски: это
// КЛЮЧИ файлов и журналов, а не текст для глаз. Перевод живёт на
// границе показа — переименовать ключ значило бы разойтись с записью.
const KEY_EN = {"открыта": "open", "закрыта": "closed", "цель": "target",
  "стоп": "stop", "время": "time", "не открыта": "not taken",
  "оборвана перезапуском": "cut by restart", "ждёт разбора": "awaiting",
  "вышла, ждёт разбора": "exited, pnl pending",
  "без исхода": "no outcome", "полка": "shelf", "кругл": "round",
  "экстремум": "extreme", "лента": "tape", "стакан": "book",
  "лонг": "long", "шорт": "short"};
const disp = v => v == null ? "—" : (KEY_EN[v] || v);
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();
const fmt = (v, d=2) => v === null || v === undefined || !isFinite(v)
  ? "—" : v.toLocaleString("en-US", {minimumFractionDigits: d,
                                     maximumFractionDigits: d});
const kk = v => v >= 1e6 ? (v/1e6).toFixed(1)+"M"
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
      `connection lost (attempts ${ST.fails}), last data below`;
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
    `${d.symbols.length} symbols · collecting for ${(s.uptime_sec/3600).toFixed(1)} h`;
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  const age = s.last_msg_age_sec;
  document.getElementById("strip").innerHTML =
    cell("messages", kk(s.messages)) +
    cell("per second", fmt(s.msg_per_sec, 0)) +
    cell("trades", kk(s.trades)) +
    cell("books ready", `${s.ready}/${d.symbols.length}`,
         s.ready === d.symbols.length ? "good" : "bad") +
    cell("resets", s.resets, s.resets ? "bad" : "") +
    cell("trades closed", `${s.closed ?? 0}/${s.signals ?? 0}`) +
    dkCells(s.disk) +
    cell("quiet, s", fmt(age, 1), age > 5 ? "bad" : "good");

  // Группы строятся отдельно (renderGroups) и не пересобираются каждым
  // тактом: пересборка DOM с 540 кнопками раз в секунду убивала бы
  // мобильный браузер и сбрасывала бы фокус поиска. Такт лишь
  // подсвечивает выбранную монету и обновляет ссылку на график.
  document.querySelectorAll("#groups [data-s]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.s === d.sym)));
  document.getElementById("cap-syms").innerHTML =
    `${(d.symbols || []).length} coins · <a class="open" target="_blank"`
    + ` href="/chart?k=${encodeURIComponent(KEY)}&sym=${d.sym}">chart ${
      d.sym.replace("USDT","")} ↗</a>`;

  const bk = d.book;
  const t = document.getElementById("book");
  if (!bk) { t.innerHTML = `<tr><td>book not ready yet</td></tr>`; }
  else {
    const mx = Math.max(...bk.a.map(r => r[1]), ...bk.b.map(r => r[1]), 1);
    const row = (r, cls) => `<tr class="${cls}">
      <td class="px mono">${r[0]}</td>
      <td class="sz mono"><span class="bar" style="width:${
        (r[1]/mx*100).toFixed(1)}%"></span>${fmt(r[1], 2)}</td>
      <td class="mono" style="color:var(--muted)">${kk(r[0]*r[1])}</td></tr>`;
    t.innerHTML =
      bk.a.slice().reverse().map(r => row(r, "a")).join("") +
      `<tr class="spread"><td colspan="3" class="mono">spread ${
        fmt((bk.ask-bk.bid)/bk.bid*1e4, 1)} bp · mid ${
        fmt((bk.ask+bk.bid)/2, 6)}</td></tr>` +
      bk.b.map(r => row(r, "b")).join("");
    document.getElementById("cap-book").textContent =
      `${bk.depth ?? "?"} levels · upd/s ${bk.upd} · reach ±${
        bk.reach_b}/${bk.reach_a} bp`;
    document.getElementById("bands").innerHTML = d.bands.map(b => {
      const tot = b.bid + b.ask || 1;
      // Полоса шире видимой книги содержит её целиком: подписка отдаёт
      // полсотни уровней, а не проценты. Помечена, чтобы одинаковые
      // числа в соседних строках не читались как измерение.
      return `<div class="band" ${b.beyond ? 'style="opacity:.5"' : ""}
        title="${b.beyond ? "wider than the visible book — this is all of it" : ""}">
        <span class="n mono">±${b.w}%${b.beyond ? "*" : ""}</span>
        <span class="g"><i class="l" style="width:${
          (b.bid/tot*100).toFixed(1)}%"></i><i class="r" style="width:${
          (b.ask/tot*100).toFixed(1)}%"></i></span>
        <span class="q mono">${kk(b.bid/1e3)} / ${kk(b.ask/1e3)}</span></div>`;
    }).join("");
  }

  const tp = d.tape || [];
  document.getElementById("cap-tape").textContent = `${tp.length} recent`;
  document.getElementById("tape").innerHTML = tp.slice().reverse().map(x =>
    `<tr><td class="mono" style="color:var(--muted)">${
      new Date(x.ts).toISOString().slice(11,23)}</td>
     <td class="mono ${x.side>0?"buy":"sell"}">${x.side>0?"buy":"sell"}</td>
     <td class="mono">${x.p}</td>
     <td class="mono sz">${fmt(x.v,3)}</td>
     <td class="mono" style="color:var(--muted)">${kk(x.p*x.v)}</td></tr>`
  ).join("");

  const sg = d.sig || {levels:[], open:[], done:[], candles:[]};
  drawMid(d.mid || [], sg);
  // Выключенный детектор обязан называться выключенным. Пустые таблицы
  // «сделок нет» неотличимы от сломанного детектора — этот симптом уже
  // стоил владельцу круга.
  const paperOff = d.status && d.status.paper === false;
  document.getElementById("cap-diag").textContent = paperOff
    ? "off — tape direction closed by probes, absorption moved into the model"
    : `history ${sg.history_min ?? 0} min · to level ${
      sg.near_x ?? "—"} noise (need ≤ ${sg.touch_x})`;
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
    `<tr><td style="color:var(--muted);font-size:11.5px">side</td>
      <td style="color:var(--muted);font-size:11.5px">volume</td>
      <td style="color:var(--muted);font-size:11.5px">imbalance</td>
      <td style="color:var(--muted);font-size:11.5px">move</td>
      <td style="color:var(--muted);font-size:11.5px">verdict</td></tr>`
    + drow("tape: sell absorption · long", dg.long)
    + drow("tape: buy absorption · short", dg.short)
    + bookRows(sg.book || {});
  const all = sg.open.concat(sg.done).slice(0, 12);
  document.getElementById("cap-sig").textContent = paperOff
    ? (all.length ? "no new ones — history of a closed direction below"
                  : "off, history cleared")
    : `open ${sg.open.length} · noise ${sg.noise_bp ?? "—"} bp · levels ${
      sg.levels.length}`;
  document.getElementById("sig").innerHTML = all.length
    ? all.map(x => `<tr>
        <td class="mono" style="color:var(--muted)">${
          new Date(x.t*1000).toISOString().slice(11,19)}</td>
        <td class="mono ${x.long?"buy":"sell"}">${x.long?"long":"short"}</td>
        <td class="mono">${x.entry}</td>
        <td class="mono" style="color:var(--muted)">${disp(x.kind)}</td>
        <td class="mono">1:${x.rr}</td>
        <td class="mono">${disp(x.state)}</td>
        <td class="mono ${x.pnl_bp>0?"buy":"sell"}">${x.pnl_bp == null ? "—"
          : pct(x.pnl_bp) + " · " + (x.r>0?"+":"") + x.r + " R"}</td>
      </tr>`).join("")
    : `<tr><td style="color:var(--muted);padding:8px 10px">no events yet</td></tr>`;
  const lg = document.getElementById("log");
  lg.textContent = (d.log || []).join("\n");
}

// Общий итог по всем монетам. Тянется отдельным запросом раз в
// пятнадцать секунд: история меняется раз в минуты, а опрос идёт раз в
// секунду, и возить её вместе с состоянием значит платить за неё
// каждую секунду.
const ALL = {trades:[], stats:null, by_rule:{}, equity:[], at:0,
             busy:false, older:0, ver:null, by_ver:[]};
async function pullAll() {
  if (ALL.busy || Date.now() - ALL.at < 15000) return;
  ALL.busy = true;
  try {
    const r = await fetch(`/trades?k=${encodeURIComponent(KEY)}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    ALL.trades = h.trades || []; ALL.stats = h.stats;
    ALL.by_rule = h.by_rule || {}; ALL.equity = h.equity || [];
    ALL.older = h.older || 0; ALL.ver = h.ver;
    ALL.by_ver = h.by_ver || [];
    ALL.at = Date.now();
  } catch (e) { /* тихо: следующий круг попробует снова */ }
  finally { ALL.busy = false; }
  renderAll();
}

// Источник сделок один: всё под нынешними правилами. Выбора между
// «как было» и «как стало» здесь больше нет — решение владельца, и оно
// снимает целый класс путаницы: застывший снимок часами подменял
// таблицу, а страница молчала об этом.
//
// Пока счёт идёт (первые минуты после запуска сборщика либо после
// правки правил), показываются настоящие исходы: это ЧЕСТНЕЕ пустоты и
// подписано строкой сверху. Полупосчитанный список — нет: он выглядит
// готовым и врал бы числами.
function shown() {
  const d = recReady();
  return d ? {trades: d.trades || [], stats: d.stats,
              by_rule: d.by_rule || {}, by_ver: [], ver: d.ver,
              equity: d.equity || [], older: 0, rec: true} : ALL;
}

function renderAll() {
  const pc = v => (v*100).toFixed(0) + " %";
  const A = shown(), s = A.stats;
  document.getElementById("cap-all").textContent =
    `${A.trades.length} trades total`
    + (A.rec ? " · replayed, not actual"
             : ALL.older
               ? ` · ${ALL.older} under older rules, excluded from stats` : "");
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  document.getElementById("sum2").innerHTML = !s
    ? cell("closed trades", "none yet")
    : cell("trades", s.trades)
      // Доля побед сравнивается с безубыточной, а не с половиной: при
      // отношении 1:3 выигрывать надо каждую четвёртую.
      + cell("wins", pc(s.win_rate),
             s.win_rate >= s.break_even ? "good" : "bad")
      + cell("break-even", pc(s.break_even))
      + cell("expectancy", pct(s.expectancy_bp),
             s.expectancy_bp > 0 ? "good" : "bad")
      + cell("in R", (s.expectancy_r>0?"+":"") + s.expectancy_r.toFixed(2)
             + " R", s.expectancy_r > 0 ? "good" : "bad")
      + cell("target/stop/time",
             `${pc(s.share_target)}/${pc(s.share_stop)}/${pc(s.share_time)}`)
      + (s.cut_by_restart ? cell("cut early", s.cut_by_restart, "bad") : "");
  const br = A.by_rule || {};
  document.getElementById("rules2").innerHTML =
    `<div style="padding:7px 10px;font-size:12.5px;color:var(--muted)">`
    + (verLine(A.by_ver, A.ver) ? verLine(A.by_ver, A.ver) + "<br>" : "")
    + (Object.keys(br).map(r => {
        const x = br[r];
        return x ? `<b>${disp(r)}</b>: ${x.trades} trades, wins ${
            pc(x.win_rate)} `
          + `vs break-even ${pc(x.break_even)}, expectancy ${
            pct(x.expectancy_bp)}`
          : `<b>${disp(r)}</b>: no trades`;
      }).join(" · ") || "&nbsp;") + `</div>`;
  document.getElementById("alltr").innerHTML = A.trades.length
    ? A.trades.slice(0, 60).map(x => `<tr ${
        (x.ver || 1) !== A.ver
          ? 'style="opacity:.5" title="older rules — excluded from stats"'
          : ""}>
        <td class="mono" style="color:var(--muted)">${
          new Date(x.t*1000).toISOString().slice(5,16).replace("T"," ")}</td>
        <td class="mono">${(x.sym||"").replace("USDT","")}</td>
        <td>${disp(x.rule || "лента")}</td>
        <td class="mono ${x.long?"buy":"sell"}">${x.long?"long":"short"}</td>
        <td class="mono">1:${x.rr}</td>
        <td class="mono">${disp(x.state)}</td>
        <td class="mono ${x.pnl_bp>0?"buy":"sell"}">${x.pnl_bp == null ? "—"
          : pct(x.pnl_bp) + " · " + (x.r>0?"+":"") + x.r
            + " R"}</td></tr>`).join("")
    : `<tr><td style="color:var(--muted);padding:8px 10px">
        no closed trades yet</td></tr>`;
  drawEqAll();
}

function drawEqAll() {
  const cv = document.getElementById("eq2"), pts = shown().equity || [];
  const dpr = Math.min(devicePixelRatio||1, 2), W = cv.clientWidth, H = 110;
  cv.width = W*dpr; cv.height = H*dpr; cv.style.height = H+"px";
  const g = cv.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);
  g.fillStyle = css("--muted"); g.font = "12px system-ui";
  g.textBaseline = "middle";
  if (pts.length < 2) {
    g.fillText("the curve appears after two closed trades", 10, H/2);
    return;
  }
  const v = pts.map(p => p[1]);
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
  g.font = "11px ui-monospace, Menlo, monospace";
  g.fillText(pct(hi), W-60, y(hi));
  g.fillText(pct(lo), W-60, y(lo));
}

// Встречный пересчёт: те же входы, нынешняя геометрия. Отвечает на
// вопрос «как изменилась бы вся статистика», а не «что было». Считается
// в фоне на сервере — сутки по двум десяткам символов это минуты.
//
// Пока он включён, ПОДМЕНЯЕТСЯ вся панель разом — сводка, кривая счёта,
// таблица сделок, — а не приписывается строчкой отчёта. Показывать
// таблицу по факту, а числа по пересчёту значило бы сложить два разных
// счёта в одну картинку. Что перед глазами именно встречный счёт,
// сказано в заголовке и подписью.
// Состояние переключателя переживает перезагрузку страницы. Держали
// только в памяти — и каждое обновление гасило встречный счёт, а
// владельцу приходилось запускать трёхминутный пересчёт заново ради тех
// же чисел. Сам результат при этом лежит на сервере в файле, поэтому
// восстановление бесплатно: просим `go=0`, то есть «отдай готовое, не
// начинай новый».
// --- группы монет: строятся один раз, фильтруются поиском -----------
const GRP = {list: null, q: ""};
const GRP_RU = {bitcoin_pow: "Bitcoin & PoW", privacy: "Privacy",
  smart_contract_l1: "L1 platforms", layer2: "L2",
  cosmos_interop: "Cosmos & bridges", polkadot: "Polkadot",
  defi_dex: "DeFi: exchanges", defi_lending: "DeFi: lending",
  defi_derivatives: "DeFi: derivatives", defi_yield: "DeFi: yield",
  liquid_staking: "Staking", oracles: "Oracles",
  storage_compute: "Storage & compute", depin: "DePIN",
  ai_infra: "AI: infrastructure", ai_agents: "AI: agents",
  memes: "Memes", gaming_metaverse: "Gaming & metaverse",
  telegram_games: "Telegram games", nft_creator: "NFT",
  exchange_tokens: "Exchange tokens", fan_tokens: "Fan tokens",
  consumer_apps: "Consumer apps", identity_access: "Identity",
  infrastructure: "Infrastructure", payments_social: "Payments",
  dao_governance: "DAO", rwa: "RWA",
  bitcoin_ecosystem: "Bitcoin ecosystem",
  excluded_special: "Special", other: "Other & new listings"};
async function pullGroups() {
  try {
    const r = await fetch(`/groups?k=${encodeURIComponent(KEY)}`);
    const d = await r.json();
    if (d && Array.isArray(d.groups)) { GRP.list = d.groups; }
  } catch (e) { /* группы — удобство, страница живёт и без них */ }
  renderGroups();
}
function renderGroups() {
  const box = document.getElementById("groups");
  if (!GRP.list) { box.textContent = "…"; return; }
  const q = GRP.q.toUpperCase();
  box.innerHTML = GRP.list.map(g => {
    const ss = q ? g.symbols.filter(s => s.includes(q)) : g.symbols;
    if (!ss.length) return "";
    // Свёрнуто ВСЕГДА, кроме поиска: авто-раскрытие группы текущей
    // монеты на «прочих» из двух сотен имён давало стену кнопок.
    const open = q ? " open" : "";
    return `<details class="grp"${open}><summary><span>${
        GRP_RU[g.id] || g.id}</span><span>${ss.length}</span></summary>
      <div class="gs">${ss.map(s =>
        `<button data-s="${s}" aria-pressed="${String(s === sym)}">${
          s.replace("USDT","")}</button>`).join("")}</div></details>`;
  }).join("") || `<div class="mline">nothing found</div>`;
  box.querySelectorAll("[data-s]").forEach(b =>
    b.onclick = () => { sym = b.dataset.s; wipe(); ST.sym = sym; tick(); });
  // Аккордеон: раскрытие одной группы сворачивает остальные.
  box.querySelectorAll("details.grp").forEach(dd =>
    dd.addEventListener("toggle", () => {
      if (dd.open && !GRP.q)
        box.querySelectorAll("details.grp[open]").forEach(o =>
          { if (o !== dd) o.open = false; });
    }));
}

// --- исполнительное ядро: статус тени и вердикты сторожа -------------
// Отсутствие ядра — не тревога (оно может быть просто не развёрнуто),
// но и не пустота: панель говорит «не запущено» словами. Тревога — это
// молчание ЗАПУЩЕННОГО: статус старше пяти минут при интервале такта в
// минуту означает повисший процесс, и это красным.
async function pullBot() {
  let d = null;
  try {
    const r = await fetch(`/bot?k=${encodeURIComponent(KEY)}`);
    d = await r.json();
  } catch (e) { /* тихо: следующий опрос через минуту */ }
  const box = document.getElementById("botbox");
  const cap = document.getElementById("cap-bot");
  if (!d || !d.present) {
    box.textContent = "core not running — the shadow is not deployed yet";
    cap.textContent = "";
    return;
  }
  const age = d.age_sec == null ? null : Math.round(d.age_sec);
  cap.textContent = age == null ? "" : `updated ${age} s ago`;
  const bad = [];
  if (age != null && age > 300)
    bad.push(`STATUS SILENT for ${Math.round(age / 60)} min — process hung`);
  if (d.error) bad.push(`ERROR: ${d.error}`);
  const ch = d.check || {};
  if (ch.ok === false)
    bad.push(`INVARIANTS: ${(ch.violations || []).join("; ")}`);
  const sv = d.sverka || {};
  if (sv.ok === false) bad.push(sv.note || "RECONCILIATION: mismatches");
  const kill = d.kill ? ` · <b style="color:var(--ask)">KILL SWITCH</b>` : "";
  const warns = (ch.warnings || []).length
    ? `<div class="k">warnings: ${(ch.warnings || []).join("; ")}</div>`
    : "";
  box.innerHTML = `<span class="mono">${d.balance_usd} $</span>
    <span class="k">shadow balance (arm ${d.arm})</span> ·
    open ${d.open}${kill} ·
    invariants ${ch.ok === true ? "intact" : "—"} ·
    reconciliation ${sv.ok === true ? "0 mismatches"
             : sv.ok == null ? (sv.note || "not run yet") : "see below"}`
    + ` · <a href="/bot-page?k=${encodeURIComponent(KEY)}">details</a>`
    + (bad.length
       ? `<div style="color:var(--ask)"><b>${bad.join("<br>")}</b></div>`
       : "")
    + warns;
}

// --- модель: состояние, живой IC и мысли трейдерскими словами --------
// `arm` — рука турнира моделей, `book` — книга турнира темпов: одни
// веса ведут несколько книг с разным сроком удержания, и сравнение
// «какой темп учится быстрее» и есть смысл переключателя.
const MDL = {data: null, arm: "all", book: "h4"};
// Ситуационная книга — ОДНА секция. Наблюдательная (та же ситуация
// без требования к отношению) отдельной вкладкой не стоит: владелец
// видит один раздел, а какие сделки в нём показаны, решает дилер по
// отношению. Две вкладки предлагали выбирать книгу — то есть плумбинг,
// — вместо вопроса, который на самом деле задают: «а если считать
// только сделки от такого-то RR».
const BOOKS = [["h4", "4 h"], ["h1", "1 h"], ["h24", "24 h"],
               ["sit", "situational"]];
// Порог обещанного отношения: настройка ВЛАДЕЛЬЦА, не правило книги.
// Он же выбирает ИСТОЧНИК: ниже собственного гейта книги торгуемых
// сделок не существует вовсе, и ответ на такой порог может дать только
// наблюдательная запись. Подмена источника обязана быть подписана —
// молча показать другую книгу под тем же именем было бы худшим из
// решений. Хранится в памяти страницы и в адресе, чтобы ссылку можно
// было переслать.
//
// `null` — «не выбирал»: тогда показывается книга как она торгует, со
// своим гейтом. Ноль от него отличается и означает «любое отношение».
const RRQ = (() => {
  const q = new URLSearchParams(location.search).get("rr");
  const raw = q != null ? q : localStorage.getItem("rr_min");
  if (raw == null || raw === "") return null;
  const v = parseFloat(raw);
  return isNaN(v) ? null : v;
})();
let RR_MIN = RRQ;

async function pullModel() {
  try {
    const r = await fetch(`/model?k=${encodeURIComponent(KEY)}`
      // Ноль отправляется тоже: для сервера это «любое отношение» и
      // выбор источника, а не отсутствие выбора.
      + (RR_MIN == null ? "" : `&rr_min=${RR_MIN}`));
    const d = await r.json();
    if (d && d.present !== undefined) { MDL.data = d; }
  } catch (e) { /* тихо: следующий опрос через минуту */ }
  renderModel();
}
// Состояние выбранной книги. Главная (4 ч) — сам ответ `/model`;
// остальные лежат в `books` и имеют ту же форму, поэтому рисуются тем
// же кодом.
function bookState() {
  const d = MDL.data;
  if (!d || MDL.book === "h4") return d;
  // Ситуационная секция ОДНА: какая запись отвечает на выбранный
  // порог — торгуемая или наблюдательная, — решил сервер, и под
  // ключом `sit` уже лежит она. Второе такое же решение здесь однажды
  // разошлось бы с ним, и страница показывала бы одно, а страница
  // сделок другое.
  return (d.books || {})[MDL.book] || null;
}
// Какой порог ДЕЙСТВУЕТ на экране: «не выбирал» означает книгу как она
// торгует, то есть её собственный гейт. Гейт приходит от сервера
// числом (`traded_gate`) и остаётся верным даже когда на экране
// наблюдательная запись, у которой своего гейта нет.
function rrEff(d) {
  // Значение берётся из ОТВЕТА, а не из памяти страницы: показать
  // выбор, которого сервер не применил, — это расхождение «что
  // просили» и «что посчитали», и увидеть его потом нельзя ничем.
  // Ноль ответа означает две разные вещи, и различает их источник:
  // при наблюдательной записи это «любое отношение» (владелец ушёл
  // ниже гейта), при торгуемой — «не выбирал», то есть книга как она
  // торгует.
  const v = +((d || {}).rr_min || 0);
  if (v) return v;
  return (d || {}).source_book === "observation"
    ? 0 : +((d || {}).traded_gate || 0);
}

// Базисные пункты -> ПРОЦЕНТ движения цены. Решение владельца: везде,
// где показывается сделка, единица — процент; он читается как движение
// цены, б.п. требуют пересчёта в голове. Внутри всё остаётся в б.п.
// (цели модели, издержки, формула счёта) — единица хранения и единица
// показа разные вещи.
//
// Два знака, а при мелких величинах три: нетто после издержек обычно
// единицы б.п., и на двух знаках оно схлопнулось бы в «0.00 %» — то
// есть исчезло бы ровно то число, ради которого таблица и нужна.
function pct(v) {
  if (v == null) return "—";
  const d = Math.abs(v) >= 10 ? 2 : 3;
  return (v > 0 ? "+" : "") + (v / 100).toFixed(d) + " %";
}

// Сводка по сделкам. Открытые в неё НЕ входят: у них нет исхода, и
// посчитать его нулём значило бы разбавить статистику выдумкой.
function shownArms() {
  return MDL.arm === "all" ? ["gbm", "nn"] : [MDL.arm];
}
function tradeStats(p) {
  const st = p.trade_stats || {};
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  // На вкладке «обе» показывается ТОЛЬКО итог по книге. Разбивка по
  // рукам никуда не делась — она за соседними кнопками, и печатать её
  // здесь же значит показывать одно и то же двумя способами: три
  // одинаковых блока подряд читаются дольше, чем один, и владелец
  // сказал об этом прямо.
  const shown = MDL.arm === "all" ? ["all"] : [MDL.arm];
  return shown.map(a => {
    const s = st[a]; if (!s) return "";
    const name = a === "gbm" ? "trees"
      : a === "nn" ? "neural" : "both arms together";
    if (!s.closed) return `<div class="mline">${name}: ${s.open || 0}
      open, none closed yet — ${isSit(p)
        ? "they close when their situation ends"
        : "first outcomes in ~" + bookH(p) + " h"}.</div>`;
    // «Обещание / факт» — самое честное число здесь: модель может
    // угадывать знак и обещать вчетверо больше, чем даёт.
    return `<div class="mline"><b>${name}</b></div><div class="stats">`
      // «Всего» первым: столбики иначе не складываются с числом
      // сделок книги, и закрытые одной руки читаются как вся книга —
      // владелец так и прочёл 32 из 76.
      + cell("trades", s.trades ?? ((s.closed||0) + (s.open||0)
             + (s.exiting||0) + (s.awaiting||0) + (s.no_outcome||0)))
      + cell("closed", s.closed)
      + cell("open", s.open)
      + (s.exiting ? cell("exited, pnl pending", s.exiting) : "")
      // «Знак угадан» считается по сделкам, дошедшим до НАШЕГО же
      // уровня — стопа или цели. Сделка, закрытая разворотом прогноза
      // или пределом возраста, до уровня не дошла, и её мелкий плюс
      // победой не является: владелец увидел 70 % при отрицательном
      // счёте. Знаменатель стоит рядом числом, а прежняя доля по всем
      // закрытым — в подсказке, чтобы разница была видна, а не
      // заменена.
      + cell(s.hit_basis === "levels" ? "sign right (at a level)"
             : "sign right",
             (s.hit_rate*100).toFixed(0) + " %"
             + `<span class="k"> of ${s.hit_n ?? s.closed}</span>`,
             s.hit_rate >= 0.5 ? "good" : "bad")
      + (s.hit_rate_all != null
         ? cell("sign right, all exits",
                (s.hit_rate_all*100).toFixed(0) + " %"
                + `<span class="k"> of ${s.closed}</span>`) : "")
      + cell("net move", pct(s.net_bp_avg),
             s.net_bp_avg > 0 ? "good" : "bad")
      + cell("paper P&L, $", s.pnl, s.pnl > 0 ? "good" : "bad")
      + cell("promise / actual", s.expected_over_got ?? "—",
             s.expected_over_got > 3 ? "bad" : "")
      + (s.awaiting ? cell("awaiting", s.awaiting) : "")
      + (s.no_outcome ? cell("no outcome", s.no_outcome, "bad") : "")
      + `</div>` + exitLine(s);
  }).join("");
}

// Кривая счёта: рисуется из истории самого счёта, а не пересчитывается
// по сделкам — иначе график и баланс однажды разойдутся.
function equityBlock(p) {
  const accs = p.accounts || {};
  const series = shownArms().map(a => (accs[a]||{}).history || [])
    .filter(h => h.length > 1);
  if (!series.length) return "";
  const all = series.flat().map(h => h.balance);
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.1 || 1;
  const W = 320, H = 60;
  const path = (h, col) => {
    const n = h.length;
    const pts = h.map((r, i) => {
      const x = n > 1 ? i / (n - 1) * W : 0;
      const y = H - (r.balance - lo + pad) / (hi - lo + 2*pad) * H;
      return `${x.toFixed(1)},${y.toFixed(1)}`; }).join(" ");
    return `<polyline points="${pts}" fill="none" stroke="${col}"
      stroke-width="1.5"/>`;
  };
  const cols = ["#268bd2", "#b58900"];
  return `<div class="mline">paper equity <span class="dim">(start
    $1000, ${series[0].length} closed hours)</span></div>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;
      height:${H}px;display:block">
      ${series.map((h,i) => path(h, cols[i])).join("")}
    </svg>`;
}

// Таблица сделок: одна строка — одна позиция. Открытая несёт прогноз и
// срок закрытия, закрытая — факт и деньги. Ровно это и просили: «если
// сделка ещё не состоялась, хочу видеть прогноз».
// Метка «месяц-день час:минута» в UTC. На этой странице все часы —
// КЛЮЧИ, то есть UTC; показать рядом местное время значило бы держать
// два пояса в одной колонке.
function utcHM(ts) {
  return ts ? new Date(ts * 1000).toISOString().slice(5, 16)
                .replace("T", " ") : "—";
}

function tradeTable(p) {
  const tr = (p.trades || []).filter(t => MDL.arm === "all"
                                          || t.arm === MDL.arm);
  if (!tr.length) return `<div class="mline">no model trades yet —
    the first cycle writes picks, outcomes arrive 4 h later.</div>`;
  const SHOW = 60;
  const rows = tr.slice(0, SHOW).map(t => {
    const cls = t.state === "закрыта"
      ? ((t.net_bp > 0) ? "good" : "bad")
      : (t.state === "открыта" ? "" : "dim");
    const when = t.state === "открыта"
      ? (t.closes_in_sec == null ? "open"
         : `in ${(t.closes_in_sec/3600).toFixed(1)} h`)
      : (t.state === "закрыта"
         ? "closed" + (t.exit_reason
             ? " · " + (EXIT_EN[t.exit_reason] || t.exit_reason) : "")
         : t.state === "вышла, ждёт разбора"
           ? "exited " + (EXIT_EN[t.exit_reason] || t.exit_reason || "")
             + " · pnl at next cycle"
         : t.state === "ждёт разбора" ? "awaiting" : "no outcome");
    // У книги без срока час — это ключ ЛИСТА сечения, а не время
    // сделки: вход сканера случается посреди следующего часа, и
    // строка «17» у сделки, открытой в 18:16, читается как старая
    // сделка по таймеру (владелец так её и прочёл). Показываем факт —
    // секунду входа, час остаётся подсказкой.
    const key = isSit(p) ? utcHM(t.opened_at) : t.hour.slice(5);
    // «Почему» — подсказкой на строке: обучение, вклад признаков,
    // место в сечении. Полное предложение живёт на странице графика;
    // здесь достаточно того, что ответ ЕСТЬ и его видно без перехода.
    const why = [t.train_seq != null ? "training #" + t.train_seq
                   : null,
                 t.rank != null && t.of
                   ? `rank #${t.rank} of ${t.of}` : null,
                 (t.why || []).map(w => `${w[0]} ${w[1] > 0 ? "+" : ""}${
                   (w[1] / 100).toFixed(2)} %`).join(", ") || null]
      .filter(Boolean).join(" · ");
    // Вид ситуации — колонкой, а не подсказкой: владелец просил видеть,
    // на чём стоит сделка (выедение стакана, ликвидации, зажим), и
    // прятать это в наведение значило бы не показать вовсе. Доли — в
    // подсказке колонки.
    const su = (t.setup || [])[0];
    const suTxt = su ? (FAM_EN[su[0]] || su[0]).split(" (")[0] : "—";
    // Значок «i» — просьба владельца: страница разбора сделки, где
    // простыми словами сказано, почему вход здесь и как расставлены
    // уровни. Ссылка несёт книгу и порог: сделка ниже гейта живёт в
    // наблюдательной записи, и страница обязана открыть именно её.
    const ip = new URLSearchParams({k: KEY, sym: t.sym,
                                    arm: t.arm || "gbm",
                                    hour: t.hour, side: t.side});
    const bhz = MDL.book === "h4" ? "" : MDL.book;
    if (bhz) ip.set("hz", bhz);
    if (RR_MIN != null) ip.set("rr", String(RR_MIN));
    const info = `<a href="/trade-info?${ip.toString()}"
      title="why this trade — plain-words breakdown"
      style="text-decoration:none">&#9432;</a>`;
    return `<tr class="${cls}"${why ? ` title="${why}"` : ""}>
      <td class="mono" title="sheet hour ${t.hour}">${key}</td>
      <td>${t.arm === "nn" ? "neu" : "tre"}</td>
      <td class="mono">${t.sym.replace("USDT","")}</td>
      <td>${t.side === "long" ? "L" : "S"}</td>
      <td class="dim" title="${setupText(t)}">${suTxt}</td>
      <td class="mono">${pct(t.expected_bp)}</td>
      <td class="mono dim">${pct(t.mae_bp)}</td>
      <td class="mono">${pct(t.got_bp)}</td>
      <td class="mono">${t.pnl == null ? "—" :
        (t.pnl > 0 ? "+" : "") + t.pnl.toFixed(2)}</td>
      <td class="dim">${when}</td><td>${info}</td></tr>`;
  }).join("");
  return `<div class="mline">model trades <span class="dim">(exp —
    expected move; mae — expected move <b>against</b> the position
    on the way; got — what actually happened. % of price, ${isSit(p)
      ? "until the situation exits"
      : "over " + bookH(p) + " h"})</span></div>
    <div style="overflow-x:auto"><table class="mtr">
    <tr><th>${isSit(p) ? "entered" : "hour"}</th>
    <th>arm</th><th>coin</th><th>side</th>
    <th title="dominant feature family of this forecast — a reading
      of the contributions, not a hand-picked strategy">setup</th>
    <th>exp</th>
    <th>mae</th><th>got</th><th>$</th><th>state</th><th>i</th></tr>
    ${rows}</table></div>`
    + (tr.length > SHOW ? `<div class="mline dim">showing ${SHOW} of ${
        p.trades_total ?? tr.length} — older ones are on disk</div>` : "");
}

// Горизонт книги — из её манифеста; главная 4-часовая его не пишет.
function bookH(p) {
  return ((p || {}).manifest || {}).horizon_h || 4;
}
function isSit(p) {
  return !!(((p || {}).manifest || {}).situational);
}
// Причины выхода ситуационной книги — перевод на границе показа.
// Вид ситуации — семейство признаков, на котором стоит прогноз
// сделки. Ключи объявлены в bookfeat.FAMILY_*; это ЧТЕНИЕ вкладов, а
// не выбранная стратегия — у модели дискретных стратегий нет, и
// подписывать надо честно.
const FAM_EN = {absorption: "book eaten (absorption)",
                book: "book imbalance / depth",
                tape: "tape pressure", liq: "liquidations",
                oi: "open interest", funding: "funding & basis",
                move: "price move / reversal", squeeze: "squeeze",
                tilt: "tilt", range: "range / dwell",
                vol: "volatility regime", leader: "leader & sector",
                clock: "time of day", round: "round levels",
                beta: "market beta", age: "listing age",
                other: "other"};
function setupText(t) {
  if (!t || !t.setup || !t.setup.length) return "";
  return t.setup.map(x => `${FAM_EN[x[0]] || x[0]} ${
    Math.round(x[1] * 100)} %`).join(", ");
}
const EXIT_EN = {"прогноз развернулся": "forecast flipped",
                 "цена прошла обещанный ход против":
                   "price broke the promised adverse path",
                 "цена дошла до обещанной цели": "target reached",
                 "предел возраста": "age limit"};
function exitLine(s) {
  // Раскладка выходов числом. Без неё «знак угадан у 55 % из 12» не
  // говорит, куда делись остальные сделки, а именно там и сидит
  // разница между двумя долями.
  const e = s.exits || {};
  const ks = Object.keys(e);
  if (!ks.length) return "";
  const part = ks.sort((a, b) => e[b] - e[a])
    .map(k => `${EXIT_EN[k] || k} <b>${e[k]}</b>`).join(" · ");
  return `<div class="mline dim">how they ended: ${part}</div>`;
}
function renderModel() {
  const box = document.getElementById("modelbox"), full = MDL.data;
  const cap = document.getElementById("cap-model");
  if (!full) { box.textContent = "…"; return; }
  // Переключатель книг рисуется, только когда книги есть: до первого
  // цикла нового кода ряд из одной кнопки выглядел бы как поломка.
  const bookBtns = (full.books && Object.keys(full.books).length)
    ? `<div style="margin-bottom:6px"><span class="dim"
         style="margin-right:4px">hold</span>` +
      BOOKS.map(x => `<button data-book="${x[0]}" aria-pressed="${
        String(MDL.book === x[0])}">${x[1]}</button>`).join(" ")
      + `</div>` : "";
  const d = bookState();
  const armBtns = bookBtns + `<div style="margin-bottom:6px">` +
    [["all","both"],["gbm","trees (ML)"],["nn","neural (AI)"]].map(x =>
      `<button data-arm="${x[0]}" aria-pressed="${
        String(MDL.arm === x[0])}">${x[1]}</button>`).join(" ") + `</div>`;
  const wireArms = () => {
    box.querySelectorAll("[data-arm]").forEach(b =>
      b.onclick = () => { MDL.arm = b.dataset.arm; renderModel(); });
    box.querySelectorAll("[data-book]").forEach(b =>
      b.onclick = () => { MDL.book = b.dataset.book; renderModel(); }); };
  if (!d) {
    // Выбранной книги ещё нет: цикл нового кода не прошёл ни разу.
    box.innerHTML = armBtns + `<div class="mline">this book has not
      started yet — first picks come with the next training cycle.</div>`;
    cap.textContent = "book pending";
    wireArms();
    return;
  }
  if (!d.present) {
    // Готовность — числом, а не обещанием. «Модели нет» означало и
    // «копим запись», и «копим вхолостую, ни один час не годен»;
    // второе трижды выяснялось только через сутки.
    const rd = d.readiness;
    let prog = `<div class="mline">no readiness file yet — the training
      loop has not completed a cycle.</div>`;
    if (rd) {
      const bad = (rd.by_hour || []).filter(h => h.n < rd.min_section);
      const last = (rd.by_hour || []).slice(-6).map(h =>
        `${h.h.slice(-2)}h:${h.n}`).join(" ");
      prog = `<div class="mline"><b>${rd.sections} / ${rd.need}</b>
        hourly cross-sections ready · ${rd.symbols} coins ·
        ${rd.hours} hours summarised · ${rd.features} features<br>
        need ≥${rd.min_section} eligible names in an hour to count it;
        ${bad.length} of the last ${(rd.by_hour || []).length} hours fall
        short<br>last hours (names per hour): ${last || "—"}</div>`;
    }
    cap.textContent = rd ? `${rd.sections}/${rd.need} sections`
                         : "accumulating data";
    // Вердикт последнего цикла обязан быть виден: «96/48 готово» при
    // отсутствующей модели читается как поломка, хотя цикл честно
    // ходит и ждёт своего гейта. Причины — ключи сервера, перевод на
    // границе показа.
    const lr = d.last_run || {};
    const WHY = {"нет главной цели": "main target fwd_4h not ready — it "
      + "is the residual to the wave, so it needs a per-coin beta "
      + "(96 h of eligible history) plus a closed 4 h forward; first "
      + "weights come a few hours after beta crosses the bar",
      "мало сечений": "not enough sections yet",
      "канарейка кричит": "leak canary fired — weights withheld",
      "канарейка не считалась": "canary had nothing to count",
      "обучилась": "trained"};
    const prog2 = lr.reason
      ? prog + `<div class="mline">last cycle ${lr.at
          ? String(lr.at).slice(11, 16) + " UTC" : ""}: <b>${
          WHY[lr.reason] || lr.reason}</b></div>`
      : prog;
    box.innerHTML = armBtns + `<div class="mline">two models will train
      here — trees (ML) vs neural net (AI) — once 48 closed hourly
      cross-sections accumulate (~2 days of full-list recording).</div>`
      + prog2;
    wireArms();
    return;
  }
  const m = d.manifest || {};
  const ageH = m.trained_at
    ? Math.max(0, (Date.now()/1000 - new Date(m.trained_at).getTime()/1000)
               / 3600) : null;
  const accs = d.accounts || {};
  const accLine = ["gbm","nn"].map(a => accs[a]
    ? `${a === "gbm" ? "trees" : "neural"} $${accs[a].balance.toFixed(2)}`
    : null).filter(Boolean).join(" · ");
  cap.textContent = `weights v${m.version}${
    m.train_seq != null ? " · training #" + m.train_seq : ""} · hold ${
    isSit(d) ? "by situation" : bookH(d) + " h"} · age ${
    ageH == null ? "—" : ageH.toFixed(1)} h${
    accLine ? " · " + accLine : ""}`;
  const ic = {};
  (d.ic || []).forEach(r => { ic[(r.arm || "gbm") + ":" + r.target] = r; });
  const armIc = a => ["fwd_1h","fwd_4h","fwd_24h"].map(t => {
    const r = ic[a + ":" + t];
    return r ? `${t.replace("fwd_","")} ${r.median_ic > 0 ? "+" : ""}${
      r.median_ic}` : null;
  }).filter(Boolean).join(" ");
  const icLine = ["gbm","nn"].map(a => {
    const s = armIc(a);
    return s ? `${a === "gbm" ? "trees" : "neural"}: ${s}` : null;
  }).filter(Boolean).join(" · ");
  // Книга без выборов обязана называть причину ЧИСЛОМ: цель горизонта
  // требует закрытого форварда своей длины на каждую строку обучения,
  // и медленная книга стартует позже быстрых. Пустая книга без этой
  // строки неотличима от сломанной.
  const waitLine = (m.target_rows != null && m.target_need
                    && m.target_rows < m.target_need)
    ? `<div class="mline" style="border-left:3px solid var(--accent);
         padding-left:8px">waiting for its target: <b>${m.target}</b>
       has <b>${m.target_rows}</b> of ${m.target_need} training rows.
       Each row needs a closed ${bookH(d)} h forward on top of the
       per-coin beta, so this book starts later than the faster ones —
       picks begin once the bar is crossed.</div>`
    : "";
  // Запаздывание входа — числом и С РАЗБОРОМ по шагам: «шесть минут»
  // без разложения выглядит как лень движка, тогда как лечится каждый
  // шаг по-своему, а часть из них не лечится вовсе (признаки часа не
  // существуют, пока час не закрылся).
  const st = m.steps_sec || {};
  const stNames = Object.keys(st);
  const lagLine = (m.woke_after_hour_sec != null && stNames.length)
    ? `<div class="mline dim">decision lag: woke <b>${
       Math.round(m.woke_after_hour_sec)} s</b> after the hour closed,
       then <b>${Math.round(m.cycle_sec)} s</b> of work — ${
       stNames.map(k => `${k} ${Math.round(st[k])} s`).join(", ")}.
       Features of an hour do not exist until it closes, and the hour
       has to be summarised across every coin first; the rest is
       compute.</div>`
    : "";
  // Книга без срока входит редко и по замыслу. Правило обязано стоять
  // числом рядом с ней: иначе пустая книга неотличима от сломанной, а
  // «мало сделок» читается как отказ сборщика.
  const gateLine = isSit(d) && m.min_edge_bp
    ? `<div class="mline dim">entry rule: the sheet is a map, the
       price is the trigger — a name is taken only when the remaining
       move is at least <b>${m.min_edge_bp} bp</b>, reward/risk at
       least <b>${m.min_rr}</b>, and the price has given back
       <b>${m.min_disc_bp ?? 0} bp</b> on top of what the sheet
       promised. Without that last one every name the model likes
       would enter in the first tick after the sheet — a batch on the
       cycle clock, not a moment.${m.arm_band_bp
         ? ` And the crossing has to happen <b>in front of us</b>: the
            name must first be seen at least <b>${m.arm_band_bp} bp</b>
            away from the trigger. A name found already parked at the
            line is skipped — its next tick is a wobble around a level
            it was standing on, not a move.` : ""}</div>`
    : "";
  // Правило СТОПА — тем же способом и рядом: заявка стоит не там,
  // куда модель ждёт цену, а за этой линией, и уровень предсказывает
  // отдельная модель. Без числа на странице разницу между двумя
  // правилами не увидеть в сделке никак.
  const stopLine = isSit(d) && m.stop_tau
    ? `<div class="mline dim">stop rule: not on the forecast line —
       the level the model expects price to reach would be hit by
       about half the trades (measured: 52 % touch it, 37 % of those
       come back and still reach the target). The stop sits on a
       separately learned level that price is allowed to pass in
       <b>${Math.round(m.stop_tau * 100)} %</b> of cases; reward/risk
       at the gate is counted against that level, not the forecast
       one.</div>`
    : "";
  // Переключатель порога — только у книги без срока: у часовых книг
  // обещания пути не решают ни входа, ни выхода, и фильтровать их тем
  // же числом значило бы сравнивать разные вещи.
  const rrLine = isSit(d) ? rrControl(d) : "";
  box.innerHTML = armBtns + rrLine + lagLine + gateLine + stopLine
    + `<div class="mline">trained on ${m.sections ?? "—"}
      cross-sections, ${m.symbols ?? "—"} coins · noise check ${
      m.canary_ic == null ? "—" : "clean (" + m.canary_ic + ")"}${
      icLine ? " · out-of-sample IC: " + icLine : ""}</div>
    ${waitLine}${picksTable(d)}
    ${tradeStats(d)}${equityBlock(d)}${tradeTable(d)}
    <div class="mline"><a href="/trades-page?k=${
        encodeURIComponent(KEY)}${MDL.book === "h4" ? ""
          : "&hz=" + MDL.book}">full trade history, paged &rarr;</a>
      &nbsp;·&nbsp; <a href="/league-page?k=${encodeURIComponent(KEY)
        }">league: what works best &rarr;</a>
    </div>` + (MDL.book !== "h4" ? "" : `
    <div class="thoughts">${(d.thoughts || []).slice().reverse()
      .filter(t => MDL.arm === "all"
        || (MDL.arm === "gbm" ? /^\[деревья\]/ : /^\[сеть\]/)
             .test(t.text || ""))
      .map(t =>
      `<span class="tt">[${t.at || ""}]</span> ${t.text}`).join("\n")
      || "no thoughts yet — they appear after the first training"}</div>`);
  wireArms();
  // Порог — настройка владельца, поэтому живёт и в памяти страницы, и
  // в адресе: перезагрузка его не гасит, а ссылку можно переслать.
  const rf = document.getElementById("rrf");
  if (rf) rf.onchange = () => {
    // Ноль здесь — «любое отношение», сознательный выбор владельца, а
    // не отсутствие выбора: он переключает показ на наблюдательную
    // запись. Поэтому и в памяти, и в адресе он хранится числом.
    RR_MIN = parseFloat(rf.value) || 0;
    localStorage.setItem("rr_min", String(RR_MIN));
    const u = new URLSearchParams(location.search);
    u.set("rr", String(RR_MIN));
    history.replaceState(null, "", location.pathname + "?" + u);
    pullModel();
  };
}
// Настройка ВЛАДЕЛЬЦА: показывать только сделки с обещанным
// отношением не ниже порога, шаг 0.5. Книга торгует своим гейтом, а
// это вопрос «что было бы, если считать только такие» — поэтому
// отбор живёт в показе и всегда подписан как подмножество.
//
// Выбранное значение и подпись берутся из ОТВЕТА сервера, а не из
// памяти страницы: отбор и счёт делает он, и расхождение между
// «что просили» и «что посчитали» обязано быть видно, а не спрятано.
function rrControl(d) {
  // Гейт торгуемой книги и то, чья запись на экране, приходят от
  // сервера: он и выбирает источник. Спрашивать гейт у показанного
  // манифеста нельзя — у наблюдательной записи он ноль по построению.
  const gate = +(d.traded_gate || 0);
  const cur = rrEff(d);
  const obs = d.source_book === "observation";
  const steps = [];
  for (let v = 1.0; v <= 5.0001; v += 0.5) steps.push(v.toFixed(1));
  // «1 : 3» означает ТРИ И ВЫШЕ, а не ровно три — иначе порог читался
  // бы как выбор одной полки, и сделка с отношением 5 из показа
  // выпадала бы. Слово «≥» стоит прямо в подписи, потому что вопрос
  // возник у владельца до первого использования.
  const lab = v => (Math.abs(v - gate) < 1e-9
    ? `≥ 1 : ${v} — as the book trades` : `≥ 1 : ${v}`);
  const opts = [`<option value="0"${cur ? "" : " selected"}>any
      reward/risk</option>`]
    .concat(steps.map(v => `<option value="${v}"${
      Math.abs(cur - parseFloat(v)) < 1e-9 ? " selected" : ""
    }>${lab(parseFloat(v).toFixed(1))}</option>`)).join("");
  const total = (d.trades_total || 0) + (d.rr_cut || 0);
  // Откуда числа — обязано стоять на экране. Ниже собственного гейта
  // торгуемых сделок не существует, и ответ даёт наблюдательная
  // запись: те же правила входа, снятое требование к отношению, свой
  // счёт. Молчаливая подмена книги под тем же именем была бы худшим
  // из решений — по кривой её не отличить.
  const src = obs
    ? `<span class="dim"> — below the book’s own gate
       (<b>≥ ${gate}</b>) it has no such trades at all, so these come
       from the <b>observation record</b>: same entry rules, the
       reward/risk requirement dropped, its own account. The shadowed
       bot does not trade it${cur ? `. Keeping reward/risk
       <b>${cur} or higher</b>` : ""}.</span>`
    : `<span class="dim"> — the <b>traded book</b>, the one the bot
       shadows${cur > gate
         ? `, keeping only trades whose promised reward/risk is
            <b>${cur} or higher</b>`
         : ", every trade it took"}.</span>`;
  // Оговорка принадлежит ОТБОРУ, а не источнику: она нужна везде, где
  // порог что-то убрал, — и в торгуемой книге, и в наблюдательной
  // записи. Привязав её к источнику, я бы прятал её ровно там, где
  // отфильтрованная кривая читается как деньги книги.
  const note = (d.rr_cut || 0)
    ? `<span class="dim"> <b>${d.trades_total || 0}</b> of ${total}
       trades <b>across both arms</b>, open and closed${d.rr_unknown
          ? `, ${d.rr_unknown} with no promise to judge by` : ""}.
       The account below is recomputed on this subset: it answers
       “what if only such trades were taken”, it is NOT the book’s
       money.</span>`
    : "";
  return `<div class="mline">show trades with reward/risk:
    <select id="rrf">${opts}</select>${src}${note}</div>`;
}

function picksTable(d) {
  // Турнир: у каждой руки свои выборы и свой разбор. Смешение рук в
  // одной таблице выглядело бы осмысленно и не значило бы ничего.
  const arms = {};
  (d.picks || []).forEach(p => { arms[p.arm || "gbm"] = p; });
  const revs = {};
  (d.review || []).forEach(r => { revs[r.arm || "gbm"] = r; });
  const hz = bookH(d);
  const one = (armId, title) => {
    const pk = arms[armId];
    if (!pk) return "";
    const got = {};
    ((revs[armId] || {}).rows || []).forEach(r => { got[r.sym] = r; });
    const row = (p, side) => {
      const g = got[p.sym];
      return `<tr><td class="${side === "long" ? "buy" : "sell"}">${
        side}</td><td>${p.sym.replace("USDT","")}</td>
        <td class="mono">expects ${p.fwd > 0 ? "+" : ""}${p.fwd.toFixed(0)}
          bp / ${hz}h</td>
        <td class="mono">adverse ~${p.mae.toFixed(0)} bp</td>
        <td class="mono">${p.odd != null
          ? `unseen ${(p.odd * 100).toFixed(0)}%` : ""}</td>
        <td class="mono">${g ? `last: got ${g.got > 0 ? "+" : ""}${
          g.got} bp` : ""}</td></tr>`;
    };
    return `<div class="mline" style="margin-top:6px">${title} — picks
        (hour ${pk.hour || "—"}):</div>
      <table>${(pk.long || []).map(p => row(p, "long")).join("")}${
        (pk.short || []).map(p => row(p, "short")).join("")}</table>`;
  };
  if (MDL.arm === "gbm") return one("gbm", "trees (ML)");
  if (MDL.arm === "nn") return one("nn", "neural net (AI)");
  return one("gbm", "trees (ML)") + one("nn", "neural net (AI)");
}

const REC = {on:true, busy:false, data:null, timer:null};
async function pullRec(go) {
  if (REC.busy) return;
  REC.busy = true;
  try {
    // `go=0` всегда: счёт запускает сам сборщик, когда меняется версия
    // правил. Страница только забирает готовое — иначе каждое открытие
    // вкладки гоняло бы трёхминутный прогон заново.
    const r = await fetch(`/recount?k=${encodeURIComponent(KEY)}`
      + `&hours=24&go=0`);
    if (r.ok) REC.data = await r.json();
  } catch (e) { /* тихо */ }
  finally { REC.busy = false; }
  if (REC.data && REC.data.busy && !REC.timer)
    REC.timer = setInterval(() => pullRec(false), 3000);
  if (REC.data && !REC.data.busy && REC.timer) {
    clearInterval(REC.timer); REC.timer = null;
  }
  renderRec(); renderAll();
}

// Пересчёт годен к показу, только когда он досчитан: наполовину
// собранный список сделок выглядит как готовый и врал бы числами.
// Выключенный пересчёт РЕЗУЛЬТАТОМ не является: ответ `off` говорит,
// что бумажных сделок не ведут вовсе. Прежде он проходил как готовый
// пересчёт с пустым списком, и таблица подписывалась «0 сделок,
// пересчёт, не факт» — то есть выключенное наблюдение выглядело как
// посчитанная пустота.
function recReady() {
  return REC.data && !REC.data.busy && !REC.data.off
         && REC.data.stats !== undefined
    ? REC.data : null;
}

function renderRec() {
  const box = document.getElementById("recbox"), d = REC.data;
  // Направление закрыто — панель молчит целиком, а не показывает
  // пустую таблицу: пустота неотличима от поломки.
  if (d && d.off) {
    box.innerHTML = `<div class="note" style="padding:7px 10px">detector paper
      trades are off: tape direction closed by measurements, absorption
      feeds the model as features</div>`;
    return;
  }
  if (!d || d.busy) {
    box.innerHTML = `<div class="note" style="padding:7px 10px">replaying
      the same entries under current rules${
        d ? `: ${d.done} of ${d.total} coins` : ""}…</div>`;
    return;
  }
  box.innerHTML = `<div class="note" style="padding:7px 10px">`
    + (d.stale ? `<b style="color:var(--ask)">replay was computed under rules `
        + `v${d.ver}, current is v${d.now_ver}</b> — refresh to recompute.<br>` : "")
    + `<b>replay</b>: NOT actual outcomes — the same entries run under `
    + `rules v${d.ver} (window ${d.hours} h, took ${d.took_sec} s). `
    + `Same price path, different trade. `
    + `Entries taken ${d.made}, rejected by new geometry ${d.refused}.`
    + ageLine(d, ALL.trades) + coverLine(d, ALL.trades.length) + `</div>`;
}

// Когда пересчёт считан и сколько живых сделок с тех пор прошло мимо.
// Пересчёт намеренно НЕ обновляется сам — владелец просил, чтобы он не
// слетал. Но тогда обязан быть виден его возраст: снимок трёхчасовой
// давности на исправном сборщике выглядит точно как «новых сделок нет».
// Проверка `stale` этого не ловила — она сравнивает версию правил, а не
// время, и на неизменившихся правилах молчит всегда.
function ageLine(d, live) {
  if (!d.at) return "";
  // Часы берём со сборщика (`ST.since` — его `now`), а не с телефона:
  // разошедшиеся на минуты часы дали бы возраст со знаком минус.
  const now = ST.since || Date.now() / 1000;
  const mins = Math.max(0, Math.round((now - d.at) / 60));
  const fresh = (live || []).filter(t => t.t > d.at).length;
  const hhmm = new Date(d.at * 1000).toISOString().slice(11, 16);
  return `<br><span style="opacity:.8">computed at ${hhmm} UTC, `
    + `${mins} min ago — NOT recomputed since.`
    + (fresh
        ? ` <b style="color:var(--ask)">Live trades after that moment: `
          + `${fresh}, not shown here</b> — refresh the replay.`
        : ` No new live trades since.`)
    + `</span>`;
}

// Сколько входов из таблицы вообще попало в пересчёт. История
// поднимается за трое суток, а пересчёт считает своё окно — молчать об
// этом нельзя: недосчитанные сделки выглядели бы как исчезнувшие, а
// сводка по куску истории — как сводка по всей.
function coverLine(d, shownN) {
  const seen = (d.made || 0) + (d.refused || 0);
  if (!shownN || seen >= shownN) return "";
  return `<br><span style="opacity:.8">replayed ${seen} of `
    + `${shownN} entries in the table: the rest are older than the `
    + `replay window (${d.hours} h). Summary covers replayed only.</span>`;
}

// Диск: сколько занято, с какой скоростью растёт и надолго ли хватит.
// «Хватит на» — то число, по которому решается, сколько символов
// добавлять: ширина универсума покупает наблюдения быстрее, чем время,
// но упирается в диск, и упереться она должна на бумаге, а не ночью.
function dkCells(d) {
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  if (!d) return cell("disk", "measuring…");
  const days = d.days_left;
  // Пока пары точек в одной фазе часа нет, скорости НЕТ — и это
  // честнее числа, посчитанного по несжатым файлам текущего часа: оно
  // завышало расход вчетверо и кричало «на 0.8 дня» при восьмидесяти
  // свободных гигабайтах.
  const wait = d.rate_mb_h == null;
  return cell("used, GB", d.used_gb ?? "—")
    + cell("free, GB", d.free_gb ?? "—")
    + cell("growth, MB/h", wait ? "measuring…" : d.rate_mb_h)
    + cell("per symbol, MB/h", wait ? "—" : d.per_sym_mb_h)
    + cell("days left", wait ? "after 1 h" : (days ?? "—"),
           days && days < 14 ? "bad" : days ? "good" : "");
}

// Правило по стакану: крупный стоит, его выедают, он подставляет снова.
// Показываются измеренные величины, а не «да/нет»: без чисел «событий
// нет» неотличимо от «детектор сломан».
function verLine(list, cur) {
  // По версиям правил рядом: смешивать их нельзя, но и прятать прежние
  // незачем — выборка текущей всегда мала, и без соседних строк
  // непонятно, стало лучше или просто сделок мало.
  if (!list || !list.length) return "";
  const pc = v => (v*100).toFixed(0) + " %";
  return list.map(x => {
    const s = x.stats, me = x.ver === cur;
    const head = (me ? "<b>rules v" + x.ver + " (current)</b>"
                     : "rules v" + x.ver);
    return head + ": " + (s
      ? `${s.trades} trades, wins ${pc(s.win_rate)} vs break-even `
        + `${pc(s.break_even)}, expectancy ${pct(s.expectancy_bp)}, `
        + `stop ${pct(s.stop_bp_median)}`
      : `${x.n} trades, none closed`);
  }).join("<br>");
}

function bookRows(b) {
  const cell = (v, need, ok) => v === null || v === undefined
    ? `<td class="mono" style="color:var(--muted)">—</td>`
    : `<td class="mono ${ok ? "buy" : "sell"}">${v}${need}</td>`;
  const rows = ["лонг", "шорт"].map(k => {
    const m = b[k] || {};
    return `<tr><td>book: ${disp(k)} at a large one</td>
      ${cell(m.gate_x, "× gate", m.gate_x >= 1)}
      ${cell(m.held, " s", m.held >= (b.hold || 10))}
      ${cell(m.eaten_x, "× eaten", m.eaten_x >= (b.eat || 1))}
      <td class="mono" style="color:var(--muted)">${m.why || "—"}</td></tr>`;
  }).join("");
  // Докуда цепочка дошла за жизнь процесса. Без этой строки «правило
  // молчит» неотличимо от «правило молчит вот на этом условии», а
  // чинится только второе.
  const c = b.chain || {};
  const named = ["never large", "was large",
                 "held long enough", "was eaten"][c.stage || 0];
  return rows + `<tr><td>book: furthest step reached</td>
    <td class="mono" colspan="3">${named}${c.eat_n
      ? `, eating over ${c.eat_n} samples: median ${c.eat_med}×, `
        + `max ${c.eat_max}× vs required ${b.eat || 1}`
      : ""}</td>
    <td class="mono" style="color:var(--muted)">gate ${
      ((1 - (b.qbig || 0.98)) * 100).toFixed(0)}% of time</td></tr>`;
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
    g.fillText("accumulating history…", 10, H/2);
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
    g.fillText(disp(l.kind), 9, y(l.p) - 6);
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
    // Отрезок кончается вместе со сделкой — иначе линии соседних сделок
    // наезжают друг на друга и читать нечего.
    const end = m.closed_at || (m.held ? m.t + m.held : null);
    const xa = xt(m.t), xb = end ? Math.min(xt(end), W-64) : W-64;
    const seg = (v, color, dash) => {
      if (v < lo || v > hi) return;
      g.save(); g.strokeStyle = color; g.setLineDash(dash); g.lineWidth = 1.2;
      g.beginPath(); g.moveTo(xa, y(v)); g.lineTo(Math.max(xb, xa+2), y(v));
      g.stroke();
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
    pct((pts[pts.length-1][1]/pts[0][1]-1)*1e4) + " over the window";
}

tick(); timer = setInterval(tick, 1000);
// Общий итог тянется своим тактом, а не из `tick`: у того есть ранние
// выходы (обрыв связи, смена символа), и привязка к нему означала бы,
// что панель молчит ровно тогда, когда что-то пошло не так.
pullAll(); setInterval(pullAll, 15000);
// Тумблера нет: вид один. Опрос повторяется, потому что сборщик может
// пересчитывать прямо сейчас — при первом запуске и после каждой правки
// правил, — и результат обязан появиться сам, без нажатий.
localStorage.removeItem("rec");
pullRec(false); setInterval(() => pullRec(false), 30000);
pullGroups();
pullModel(); setInterval(pullModel, 60000);
pullBot(); setInterval(pullBot, 60000);
document.getElementById("symq").oninput = e => {
  GRP.q = e.target.value.trim(); renderGroups();
};
</script>
"""


# Отдельная страница истории сделок модели. Заведена по просьбе
# владельца: на обзоре таблица режется до шестидесяти строк, а история
# растёт на двенадцать сделок в час — за неделю это две тысячи, и
# смотреть их в панели обзора нельзя.
#
# Два решения, оба существенны.
#
# Сводка считается по ВСЕЙ выборке, а не по видимой странице.
# Статистика, зависящая от того, какую страницу открыли, статистикой не
# является. Фильтры при этом сводку не двигают — она всегда про всё, и
# это сказано на самой странице.
#
# Страницами режется только показ; файлы читаются целиком. История
# сделок — это то, ради чего всё писалось, и урезать её на чтении
# значит однажды не увидеть худшую сделку месяца.
TRADES = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>model trades</title>
<style>
/* Палитра — общая на все страницы: наследие v1 (тёмный фиолет, пурпур
   #9747ff) в современном исполнении. Тема одна, настроек нет. */
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,
  var(--bg);
 color:var(--ink);
 font:14px/1.5 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:1200px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none;white-space:nowrap}
.brand b{color:var(--accent);font-weight:800}
.tag{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);border:1px solid var(--rule);border-radius:999px;
 padding:4px 10px;background:rgba(151,71,255,.06);white-space:nowrap}
a{color:var(--accent)}
.card{background:var(--panel);border:1px solid var(--rule);
 border-radius:16px;padding:12px 14px;margin-bottom:14px}
.note{color:var(--muted);font-size:12px;margin-bottom:8px}
.warn{border-left:3px solid var(--accent);padding-left:9px;
 color:var(--muted);font-size:12px;margin-bottom:10px}
/* Плотная таблица «подпись — значение», а не крупные плитки. Плитки
   занимали втрое больше высоты, чем сами числа, и страница
   пролистывалась ради семи величин. */
.stats{display:grid;gap:0;border:1px solid var(--rule);
 border-radius:12px;overflow:hidden;background:var(--chip);
 grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
/* Значение НИКОГДА не обрезается. Первая версия ставила
   `text-overflow:ellipsis`, и составные величины («−2.09 % / −15.07 $»)
   выходили как «−2.09 …»: число на странице есть, а прочитать его
   нельзя. Это то же самое, что его не показать, только незаметно —
   тот самый класс дефекта, от которого проект защищается везде.
   Не влезло в строку — переносится целиком на следующую. */
.st{display:flex;flex-wrap:wrap;align-items:baseline;gap:1px 10px;
 padding:4px 10px;
 border-bottom:1px solid var(--rule-soft);
 border-right:1px solid var(--rule-soft)}
.k{color:var(--muted);font-size:11.5px;white-space:nowrap}
.v{font-size:13px;font-variant-numeric:tabular-nums;text-align:right;
 white-space:nowrap;margin-left:auto}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.good{color:var(--bid)} .bad{color:var(--ask)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:10px;
 letter-spacing:.08em;text-transform:uppercase;
 padding:4px 8px 5px 0;border-bottom:1px solid var(--rule);
 position:sticky;top:0;background:var(--panel)}
td{padding:4px 8px 4px 0;white-space:nowrap;
 border-bottom:1px solid var(--rule-soft)}
tbody tr:hover td{background:rgba(151,71,255,.04)}
button,select{background:var(--chip);color:var(--muted);
 border:1px solid var(--rule);border-radius:999px;padding:4px 11px;
 font:inherit;font-size:12px;cursor:pointer;
 transition:border-color .15s,color .15s}
button:hover,select:hover{color:var(--ink);border-color:var(--accent)}
button[aria-pressed=true]{color:var(--ink);border-color:var(--accent);
 background:rgba(151,71,255,.14)}
button:disabled{opacity:.4}
/* Кнопка «открыть на графике» — ссылка, а не скрипт: она обязана
   работать средним щелчком и держаться в закладке. Строка сделки в
   таблице не отвечает на вопрос «а что там было с ценой». */
a.open{color:var(--muted);text-decoration:none;border:1px solid var(--rule);
 border-radius:999px;padding:1px 8px;font-size:11px;background:var(--chip)}
a.open:hover{color:var(--ink);border-color:var(--accent)}
.bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;
 margin-bottom:8px}
.scroll{overflow-x:auto}
/* Заголовок группы величин. Блоки статистики налипали друг на друга
   без всякой структуры — «просадка», «издержки», «результат» шли
   подряд одинаковыми плитками, и глазу не за что было зацепиться. */
.gt{font-size:10.5px;color:var(--muted);letter-spacing:.09em;
 text-transform:uppercase;margin:10px 0 4px}
.gt:first-child{margin-top:0}
/* Пояснения — под раскрытие. Они не лишние: в них записано, почему
   величина считается именно так, и владелец нашёл ими не один дефект.
   Но развёрнутые они занимают больше места, чем числа, ради которых
   страницу открывают. Свёрнутые — остаются в разметке и в проверке. */
.hint{margin:0 0 5px}
.hint summary{cursor:pointer;color:var(--muted);font-size:11px;
 list-style:none;display:inline-block}
.hint summary::-webkit-details-marker{display:none}
.hint summary::before{content:"? "}
.hint summary:hover{color:var(--ink)}
.hint .note{margin:4px 0 0}
/* Сравнение рук: они учатся на одних данных, и вопрос почти всегда
   сравнительный. Переключаться между вкладками ради этого — терять
   ответ по дороге. */
.cmp{width:100%;border-collapse:collapse;font-size:13px}
.cmp{font-size:12.5px}
.cmp th{position:static;padding:3px 8px 3px 0}
.cmp td{padding:2px 8px 2px 0;font-variant-numeric:tabular-nums;
 font-family:ui-monospace,Menlo,Consolas,monospace}
.cmp td:first-child,.cmp th:first-child{font-family:inherit;
 color:var(--muted);white-space:normal}
canvas{width:100%;display:block;touch-action:pan-y}
/* Узкий экран. Смотрят с телефона, а колонок в таблице тринадцать:
   без этого строка уезжает вбок и читать её невозможно. Прячутся
   ВТОРИЧНЫЕ колонки, а не случайные: час входа и выхода выводимы из
   часа сигнала, ожидание и ход против — диагностика модели, задержка
   и новизна — тоже. Остаются час, монета, сторона, факт, нетто,
   просадка. */
@media(max-width:720px){
  .wrap{padding:10px 8px 30px}
  table{font-size:12px}
  .hide-s{display:none}
  .st{flex:1 1 46%}
}
</style>
<div class="wrap">
  <header class="top">
    <a href="#" id="back" class="brand" title="to overview">ALG<b>O</b>TH</a>
    <span class="tag">model trades</span>
    <span id="src" class="mono note" style="margin:0"></span>
  </header>
  <div id="warn"></div>

  <div class="card">
    <div class="bar" id="books"></div>
    <div class="note">All clock times are <b>Europe/Vienna</b>; the
      underlying keys are UTC and show on hover.</div>
    <details class="hint"><summary>how to read a row</summary>
    <div class="note"><b>signal hour</b> — the hour
      whose <b>close</b> the decision is based on: features cover the
      whole hour, so nothing can be entered before it ends.
      <b>entry</b> is that close, <b>exit</b> is the book&#39;s holding
      horizon later (named in the header) — exactly how the target is
      defined. <b>lag</b> is how late the training loop
      actually woke up after the hour closed: real entry delay, not
      zero. <b>state</b> is a state, not a time: open / closed / no
      outcome (deadline passed but the hour is not summarised yet — a
      trade with no outcome is never counted as zero).
      <b>unreal</b> — live mark-to-market of an open position against
      its entry price (the close of the signal hour, taken from the same
      hourly summary the model itself trains on), already net of the
      taker round trip; it refreshes every 10 s while the rest of the
      table refreshes once a minute.
      <b>exp</b> is the expected move, <b>mae</b> the expected move
      <b>against</b> the position on the way, <b>got</b> what actually
      happened, <b>net</b> the same minus the taker round trip.
      <b>dd</b> is the <b>realised</b> drawdown — how much of the
      <b>deposit</b> this trade was down at its worst while it was held.
      Not of the position: one position is roughly 1/24 of the account,
      so a 47 % move against it is about 2 % of the deposit. Hover shows
      the price move and the dollars. So <b>mae</b> is the promise and
      <b>dd</b> is what the promise cost. A trade that closed in profit
      can still have been deep down on the way, and <b>net</b> alone
      never shows that.
      <b>unseen</b> — share of this coin&#39;s features that fell
      outside the range the model saw while training: 0 % means fully
      familiar, high means the coin is in a state the model has never
      seen, so its forecast is worth less. It is a <b>measurement, not
      a filter</b> — any &laquo;don&#39;t trade the unfamiliar&raquo;
      rule mechanically flatters drawdown, and may only be introduced
      after comparing it with a random gate of the same frequency.</div>
    </details>
    <div class="note">stats below cover the <b>whole</b> history;
      filters do not move them</div>
    <div id="stats"></div>
  </div>

  <div class="card">
    <div class="gt">paper account over time</div>
    <details class="hint"><summary>how to read</summary>
    <div class="note">Balance of the paper book, hour by hour, with
      <b>open positions marked to market</b> — not just closed trades.
      The shaded band is the range inside each drawn point, so a dip
      that happened between samples still shows: an equity curve
      thinned by taking every k-th point hides exactly the drawdown it
      is looked at for. Dashed line is the 1000 $ start.</div></details>
    <canvas id="eq" height="170"></canvas>
    <div id="eqlab" class="note" style="margin-top:6px"></div>
  </div>

  <div class="card">
    <div class="bar">
      <span class="k">arm</span>
      <select id="arm"><option value="">both</option>
        <option value="gbm">trees (ML)</option>
        <option value="nn">neural (AI)</option></select>
      <span class="k">state</span>
      <select id="state"><option value="">any</option>
        <option value="закрыта">closed</option>
        <option value="открыта">open</option>
        <option value="вышла, ждёт разбора">exited, pnl pending</option>
        <option value="ждёт разбора">awaiting review</option>
        <option value="без исхода">no outcome</option></select>
      <span class="k">coin</span>
      <select id="sym"><option value="">any</option></select>
      <span class="k">per page</span>
      <select id="per"><option>50</option><option selected>100</option>
        <option>250</option><option>500</option></select>
    </div>
    <div class="bar">
      <button id="prev">&larr;</button>
      <span id="pg" class="mono k"></span>
      <button id="next">&rarr;</button>
      <span id="cnt" class="k"></span>
      <span id="mkat" class="k"></span>
      <span id="rrlab"></span>
    </div>
    <div class="scroll"><table>
      <thead><tr><th id="thw">signal hour</th>
        <th class="hide-s" id="thw2">entry</th><th class="hide-s">exit</th>
        <th class="hide-s">lag</th><th class="hide-s">arm</th>
        <th>coin</th><th>side</th><th class="hide-s">exp</th>
        <th class="hide-s">mae</th><th>got</th><th>net</th>
        <th>unreal</th><th>dd</th>
        <th>$</th><th class="hide-s">state</th>
        <th class="hide-s">unseen</th><th>chart</th>
      </tr></thead><tbody id="tb"></tbody>
    </table></div>
  </div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("back").href = "/?k=" + encodeURIComponent(KEY);
// Книга турнира темпов из ссылки («h1», «h24»); пусто — главная 4 ч.
// Едет в каждый запрос и в ссылки на график: страница обязана
// показывать ту книгу, из которой пришли, а не молча главную.
// Порог владельца: `null` — «не выбирал» (книга как торгует), ноль —
// «любое отношение». Разные значения: второе переключает показ на
// наблюдательную запись, и свести их к нулю значило бы открывать
// страницу на другой книге.
const RRQ = (() => {
  const q = new URLSearchParams(location.search).get("rr");
  const raw = q != null ? q : localStorage.getItem("rr_min");
  if (raw == null || raw === "") return null;
  const v = parseFloat(raw);
  return isNaN(v) ? null : v;
})();
let RR_MIN = RRQ;
const HZ = ["h1", "h24", "sit", "sit_obs"].includes(
  new URLSearchParams(location.search).get("hz"))
  ? new URLSearchParams(location.search).get("hz") : "";
const S = {page: 0};
// У каждой книги турнира темпов своя страница статистики; здесь —
// переход между ними. Смена книги — НАВИГАЦИЯ, а не подмена данных на
// месте: ссылку на страницу конкретной книги можно послать и открыть,
// и фильтры не переживают переход намеренно — это другая книга.
function renderBooks() {
  const mk = (hz, label) => {
    const p = new URLSearchParams({k: KEY});
    if (hz) p.set("hz", hz);
    return `<a href="/trades-page?${p.toString()}"><button
      data-hz="${hz || "h4"}" aria-pressed="${
      String((HZ || "h4") === (hz || "h4"))}">${label}</button></a>`;
  };
  document.getElementById("books").innerHTML =
    `<span class="k">book (hold)</span> `
    + mk("", "4 h") + " " + mk("h1", "1 h") + " " + mk("h24", "24 h")
    + " " + mk("sit", "situational");
}
renderBooks();
// Percent of price move — the display unit across the whole project
// (owner's decision). Two decimals, three for small values: otherwise
// net-after-costs collapses into "0.00 %".
function pct(v) {
  if (v == null) return "—";
  return (v > 0 ? "+" : "") + (v / 100).toFixed(Math.abs(v) >= 10 ? 2 : 3)
    + " %";
}
// Время показывается в часовом поясе владельца (Вена), а хранится и
// ключуется в UTC. Смешивать нельзя: `signal hour` — это КЛЮЧ часа в
// файлах и в журналах, и сдвинутый ключ ничему не соответствует.
// Поэтому пояс назван в заголовках колонок, а исходный UTC доступен
// наведением (title).
const TZ = "Europe/Vienna";
const FMT = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false});
const FMT_D = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ, day: "2-digit", month: "2-digit",
  hour: "2-digit", minute: "2-digit", hour12: false});
function hhmm(ts) { return ts ? FMT.format(new Date(ts * 1000)) : "—"; }
function dmhm(ts) { return ts ? FMT_D.format(new Date(ts * 1000)) : "—"; }
// Ключ часа `2026-08-03-20` — это UTC. Для глаз показываем его в
// местном поясе, а сам ключ оставляем в подсказке.
function hourLocal(h) {
  const m = /^(\d{4})-(\d{2})-(\d{2})-(\d{2})$/.exec(h || "");
  if (!m) return h || "—";
  const ts = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4]) / 1000;
  return dmhm(ts);
}
// Состояния приходят с сервера по-русски: это ключи, а не текст для
// глаз. Перевод живёт здесь, на границе показа — переименовать ключ
// значило бы разойтись с уже записанными файлами.
const ST_EN = {"закрыта": "closed", "открыта": "open",
               "без исхода": "no outcome", "ждёт разбора": "awaiting",
               "вышла, ждёт разбора": "exited, pnl pending"};
// Причины выхода ситуационной книги — перевод на границе показа.
// Вид ситуации — семейство признаков, на котором стоит прогноз
// сделки. Ключи объявлены в bookfeat.FAMILY_*; это ЧТЕНИЕ вкладов, а
// не выбранная стратегия — у модели дискретных стратегий нет, и
// подписывать надо честно.
const FAM_EN = {absorption: "book eaten (absorption)",
                book: "book imbalance / depth",
                tape: "tape pressure", liq: "liquidations",
                oi: "open interest", funding: "funding & basis",
                move: "price move / reversal", squeeze: "squeeze",
                tilt: "tilt", range: "range / dwell",
                vol: "volatility regime", leader: "leader & sector",
                clock: "time of day", round: "round levels",
                beta: "market beta", age: "listing age",
                other: "other"};
function setupText(t) {
  if (!t || !t.setup || !t.setup.length) return "";
  return t.setup.map(x => `${FAM_EN[x[0]] || x[0]} ${
    Math.round(x[1] * 100)} %`).join(", ");
}
const EXIT_EN = {"прогноз развернулся": "forecast flipped",
                 "цена прошла обещанный ход против":
                   "price broke the promised adverse path",
                 "цена дошла до обещанной цели": "target reached",
                 "предел возраста": "age limit"};
// Кривая счёта. Рисуются ОБЕ руки всегда, даже когда выбрана одна:
// они учатся на одних данных, и почти любой вопрос к ним
// сравнительный — «чем разошлись». Выбранная ведётся ярко, вторая
// приглушена, чтобы вкладка всё же что-то значила.
const ARMC = {gbm: "#2f7fd1", nn: "#c06a1f"};
const ARMN = {gbm: "ml", nn: "ai"};
let EQ = null;
function drawEq(d) {
  const cv = document.getElementById("eq");
  if (!cv) return;
  const cur = d.curves || {};
  const arms = ["gbm", "nn"].filter(a => (cur[a] || []).length > 1);
  const lab = document.getElementById("eqlab");
  if (!arms.length) {
    if (lab) lab.textContent = "not enough hours yet";
    return;
  }
  EQ = {cur, arms, start: d.start || 1000};
  const w = Math.max(320, cv.clientWidth || 900), h = 170;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  cv.style.height = h + "px";
  const g = cv.getContext("2d");
  if (!g || !g.setTransform) return;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const pts = arms.flatMap(a => cur[a]);
  let t0 = Infinity, t1 = -Infinity, lo = Infinity, hi = -Infinity;
  for (const p of pts) {
    if (p[0] < t0) t0 = p[0];
    if (p[0] > t1) t1 = p[0];
    if (p[2] < lo) lo = p[2];
    if (p[3] > hi) hi = p[3];
  }
  // Стартовый уровень обязан быть в кадре: без него рост и падение
  // выглядят одинаково — просто линия куда-то идёт.
  lo = Math.min(lo, EQ.start); hi = Math.max(hi, EQ.start);
  const pad = Math.max(1, (hi - lo) * 0.08);
  lo -= pad; hi += pad;
  const L = 46, R = 8, T = 8, B = 18;
  const X = t => L + (t - t0) / Math.max(1, t1 - t0) * (w - L - R);
  const Y = v => T + (hi - v) / Math.max(1e-9, hi - lo) * (h - T - B);
  const css = getComputedStyle(document.documentElement);
  const rule = css.getPropertyValue("--rule").trim() || "#333";
  const muted = css.getPropertyValue("--muted").trim() || "#888";
  g.strokeStyle = rule; g.lineWidth = 1;
  g.beginPath(); g.moveTo(L, Y(EQ.start)); g.lineTo(w - R, Y(EQ.start));
  g.setLineDash([4, 4]); g.stroke(); g.setLineDash([]);
  g.fillStyle = muted; g.font = "11px system-ui,sans-serif";
  g.fillText(hi.toFixed(0), 4, Y(hi) + 9);
  g.fillText(lo.toFixed(0), 4, Y(lo));
  g.fillText(EQ.start + " $", 4, Y(EQ.start) + 3);
  const sel = S.arm || "all";
  for (const a of arms) {
    const c = cur[a], on = sel === "all" || sel === a;
    g.globalAlpha = on ? 1 : 0.28;
    // Полоса «между точками» рисуется только у ведомой руки: у
    // прореженной кривой провал живёт внутри корзины, и без полосы он
    // исчезает — а смотрят как раз на него.
    if (on && c.some(p => p[3] - p[2] > 1e-9)) {
      g.fillStyle = ARMC[a]; g.globalAlpha = 0.13;
      g.beginPath();
      c.forEach((p, i) => i ? g.lineTo(X(p[0]), Y(p[3]))
                            : g.moveTo(X(p[0]), Y(p[3])));
      for (let i = c.length - 1; i >= 0; i--)
        g.lineTo(X(c[i][0]), Y(c[i][2]));
      g.closePath(); g.fill();
      g.globalAlpha = 1;
    }
    g.strokeStyle = ARMC[a]; g.lineWidth = on ? 1.8 : 1.2;
    g.beginPath();
    c.forEach((p, i) => i ? g.lineTo(X(p[0]), Y(p[1]))
                          : g.moveTo(X(p[0]), Y(p[1])));
    g.stroke();
  }
  g.globalAlpha = 1;
  const last = a => (cur[a] || []).slice(-1)[0];
  if (lab)
    lab.innerHTML = arms.map(a => {
      const p = last(a), v = p ? p[1] : null;
      const dp = v == null ? "" : ((v / EQ.start - 1) * 100).toFixed(2);
      return `<span class="mono" style="color:${ARMC[a]}">&#9632;</span> ${
        ARMN[a]} ${v == null ? "—" : v.toFixed(2) + " $ (" +
        (dp >= 0 ? "+" : "") + dp + " %)"}`;
    }).join(" &nbsp; ") +
      ` <span class="k">&middot; ${(cur[arms[0]] || []).length} hours</span>`;
}

// Итог одной ноги: деньги и доля СТАРТОВОГО депозита. Доля считается
// на сервере — там же, где счёт, — чтобы у процента не завелось второго
// определения. Число сделок рядом: +20 $ на двух сделках и на двухстах
// — разные утверждения.
function sideCell(name, st, side) {
  const p = st["pnl_" + side], q = st["pnl_" + side + "_pct"];
  if (p == null) return "";
  return `<div class="st"><div class="k">${name}
    <span class="k">· ${st["n_" + side] || 0}</span></div>
    <div class="v mono ${p > 0 ? "good" : "bad"}">${
      (p > 0 ? "+" : "") + p} $${
      q == null ? "" : ` <span class="k">(${
        (q > 0 ? "+" : "") + q} %)</span>`}</div></div>`;
}

const val = id => document.getElementById(id).value;
async function load() {
  const p = new URLSearchParams({k: KEY, page: S.page, per: val("per"),
                                 arm: val("arm"), state: val("state"),
                                 sym: val("sym")});
  if (HZ) p.set("hz", HZ);
  // Порог обещанного отношения — настройка владельца; сервер отбирает,
  // ПЕРЕСЧИТЫВАЕТ счёт тем же ядром и он же выбирает запись-источник.
  if (RR_MIN != null) p.set("rr_min", String(RR_MIN));
  let d;
  try {
    const r = await fetch("/model_trades?" + p.toString());
    d = await r.json();
  } catch (e) {
    document.getElementById("cnt").textContent = "no link to collector";
    return;
  }
  document.getElementById("src").textContent = "live model · hold "
    + (d.horizon_h || 4) + " h";
  // Горизонт — в заголовок вкладки: открытые рядом страницы двух книг
  // иначе неотличимы друг от друга.
  document.title = "model trades · " + (d.horizon_h || 4) + " h";
  document.getElementById("warn").innerHTML = "";
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  // Статистика делится по рукам турнира: all / ml / ai. Смотреть их
  // вместе можно, но решает сравнение — они учатся на одних данных, и
  // общий блок скрывает, какая именно из двух даёт результат.
  const which = S.arm || "all";
  const st = (d.stats||{})[which] || {};
  const acc = (d.accounts||{})[which];
  const armBtns = `<div class="bar">` +
    [["all","all"],["gbm","ml (trees)"],["nn","ai (neural)"]].map(x =>
      `<button data-sa="${x[0]}" aria-pressed="${
        String(which === x[0])}">${x[1]}</button>`).join(" ")
    + `</div>`;
  let html = armBtns + `<div class="gt">result</div>`
    + `<div class="stats">`
    + cell("trades", which === "all" ? d.grand_total
           : st.trades ?? ((st.closed||0) + (st.open||0)
             + (st.exiting||0) + (st.awaiting||0) + (st.no_outcome||0)))
    + cell("closed", st.closed || 0)
    + cell("open", st.open || 0)
    + (st.exiting ? cell("exited, pnl pending", st.exiting) : "")
    + (st.awaiting ? cell("awaiting review", st.awaiting) : "")
    // Красным — только окончательная потеря: разбор до неё дошёл и
    // цель посчитать не смог. Ожидание разбора красным быть не должно,
    // иначе тревога станет фоном и её перестанут читать.
    + (st.no_outcome ? cell("no outcome", st.no_outcome, "bad") : "");
  if (st.closed) {
    html += cell(st.hit_basis === "levels" ? "sign right (at a level)"
                 : "sign right",
                 (st.hit_rate*100).toFixed(0) + " %"
                 + `<span class="k"> of ${st.hit_n ?? st.closed}</span>`,
                 st.hit_rate >= 0.5 ? "good" : "bad")
      + (st.hit_rate_all != null
         ? cell("sign right, all exits",
                (st.hit_rate_all*100).toFixed(0) + " %"
                + `<span class="k"> of ${st.closed}</span>`) : "")
      + cell("net move, avg", pct(st.net_bp_avg),
             st.net_bp_avg > 0 ? "good" : "bad")
      + cell("realised P&L", (st.pnl > 0 ? "+" : "") + st.pnl + " $",
             st.pnl > 0 ? "good" : "bad")
      // Раздельно по ногам. Книга нейтральна по ЧИСЛУ позиций и не
      // нейтральна по бете: если весь доход приносит одна сторона —
      // это ставка на направление рынка, а не кросс-секция, и сумма
      // об этом молчит.
      + sideCell("longs", st, "long") + sideCell("shorts", st, "short")
      // How many times the promise exceeds the outcome — the most
      // honest number here: a model can get the sign right and still
      // promise four times what it delivers.
      + cell("promise / actual", st.expected_over_got ?? "—",
             st.expected_over_got > 3 ? "bad" : "");
  }
  html += `</div>`;
  // Нереализованное — ОТДЕЛЬНЫМ рядом, а не в одной строке с фактом.
  // У закрытой сделки исход известен, у открытой это лишь текущая
  // отметка, и до срока она может стать любой; сложить их значило бы
  // выдать незавершённое за результат.
  if (st.marked) {
    html += `<div class="gt">live exposure</div>`
    + `<details class="hint"><summary>how to read</summary><div class="note">open positions,
      marked to market <span class="k">(not a result yet)</span></div></details>
      <div class="stats">`
      + cell("marked", st.marked)
      + cell("unreal, avg", pct(st.unreal_net_avg_bp),
             st.unreal_net_avg_bp > 0 ? "good" : "bad")
      + cell("in the money", (st.unreal_win*100).toFixed(0) + " %",
             st.unreal_win >= 0.5 ? "good" : "bad")
      + (st.unreal_pnl == null ? "" :
         cell("unreal P&L", (st.unreal_pnl > 0 ? "+" : "")
              + st.unreal_pnl + " $", st.unreal_pnl > 0 ? "good" : "bad"))
      // Экспозиция сама по себе читается неверно, когда капиталов
      // несколько: 1504 $ на вкладке «обе» — это 0.75 плеча при двух
      // тысячах капитала, а не полтора. Показываем плечо.
      + (st.exposure == null ? "" :
         cell("exposure", st.exposure + " $"
              + (st.capital ? ` / ${st.capital}` : "")))
      // Плечо ниже единицы у свежей книги — норма, а не пропажа денег:
      // книга набирается 4 часа, и через час стоит четверть. Пишем это
      // рядом с числом, иначе «0.25×» выглядит поломкой.
      + (st.leverage == null ? "" :
         cell("leverage", st.leverage + "×"
              + (st.fill_hours && st.fill_hours < st.fill_of
                 ? ` · filling ${st.fill_hours}/${st.fill_of} h` : ""),
              st.leverage > 1.05 ? "bad" : ""))
      + `</div>`;
  }
  // Просадка — отдельным рядом, потому что она отвечает на вопрос, на
  // который итог сделки не отвечает вовсе: сколько позиция была в
  // минусе ПО ДОРОГЕ. Сделка, закрывшаяся в плюс, могла по пути стоить
  // −40 %, и по колонке `net` этого не видно.
  if (st.dd_measured || st.dd_book) {
    const b = st.dd_book || {}, o = st.dd_open_book || {};
    html += `<div class="gt">risk</div>`
    + `<details class="hint"><summary>how to read</summary><div class="note">drawdown
      <span class="k">— <b>as a share of the deposit</b>, not of the
      position. The headline is the <b>whole open book at one moment</b>:
      all positions alive in that hour, summed with sign, at their worst
      hour. That is what the account actually had to sit through — a
      single bad trade is only a part of it. Per-trade numbers are below
      it; the price move behind each one is on hover in the table.
      Measured from hourly high/low of the book mid, so it is a
      <b>lower</b> bound — moves inside a second are not in the
      snapshots.</span></div></details>
      <div class="stats">`
      // Главное число: вся живая книга в один момент. Худшая сделка —
      // это одна сделка; одновременная просадка по всем открытым есть
      // состояние счёта, и переживать приходится именно его.
      + (o.cap_bp == null ? "" :
         cell("open book, worst moment", pct(o.cap_bp)
              + (o.usd == null ? "" : ` / ${o.usd} $`),
              o.cap_bp < -300 ? "bad" : ""))
      + (o.hour ? cell("at", hourLocal(o.hour)
                       + (o.open ? ` · ${o.open} pos` : "")) : "")
      // Просадка счёта считается по кривой с переоценкой открытых. По
      // одним закрытиям она была бы систематически мельче пережитой.
      + (b.pct == null ? "" :
         cell("account, peak to trough", b.pct + " %",
              b.pct < -10 ? "bad" : ""))
      + (st.dd_worst_cap_bp == null ? "" :
         cell("worst single trade", pct(st.dd_worst_cap_bp)
              + (st.dd_worst_usd == null ? "" : ` / ${st.dd_worst_usd} $`),
              st.dd_worst_cap_bp < -100 ? "bad" : ""))
      + (st.dd_med_cap_bp == null ? "" :
         cell("median trade", pct(st.dd_med_cap_bp)))
      + (st.dd_measured == null ? "" :
         cell("trades measured", st.dd_measured))
      // Час, где живую ногу переоценить было нечем, делает просадку
      // счёта заниженной. Молчать об этом нельзя — это ровно тот класс
      // дефекта, где пустота выдаёт себя за результат.
      + (b.gaps ? cell("hours with a gap", b.gaps, "bad") : "")
      + `</div>`;
  }
  // Подарок входа. Признаки кончаются на закрытии часа, решение
  // приходит на минуты позже, а сделка записана по цене закрытия —
  // значит книга входит по цене, которой в момент решения уже нет.
  // Число говорит, сколько эта условность стоит; пока оно только
  // измеряется и в счёт не входит.
  // Издержки — разложением. Комиссию задаёт тариф символа,
  // проскальзывание — толщина книги; лечатся они разным, и одна цифра
  // круга это скрывала бы. Покрытие ставок стоит рядом числом: без
  // него умолчание неотличимо от измерения.
  if (st.exec_n) {
    html += `<div class="gt">execution</div>`
    + `<details class="hint"><summary>how to read</summary><div class="note">costs
      <span class="k">— walked through the <b>recorded order book</b>
      at entry and at exit, not a flat number: a long buys the ask and
      sells the bid, a short the reverse. Commission is the venue's
      per-symbol taker rate. Maker execution is not assumed — a limit
      order is not filled just because the price touched it.</span>
      </div></details>
      <div class="stats">`
      + cell("round trip, median", st.exec_med_bp + " bp",
             st.exec_med_bp > 25 ? "bad" : "")
      + cell("of it commission", st.fee_med_bp + " bp")
      + cell("of it spread", st.slip_med_bp + " bp")
      + cell("mean", st.exec_avg_bp + " bp")
      + cell("real fee rate for", st.fee_known + "/" + st.exec_n,
             st.fee_known < st.exec_n ? "bad" : "")
      + (st.exec_partial ? cell("book too thin", st.exec_partial, "bad") : "")
      + (st.cost_flat ? cell("old flat-11 trades", st.cost_flat) : "")
      + `</div>`;
  }
  if (st.gift_n) {
    html += `<div class="gt">entry timing</div>`
    + `<details class="hint"><summary>how to read</summary><div class="note">entry timing
      <span class="k">— features end at the hour close, the cycle
      decides minutes later, and the trade is booked at that close.
      Positive means the recorded book entered <b>better</b> than it
      could have live. Measured only — not yet applied to the
      accounts, because the outcome is measured from the same close and
      moving one end alone would be worse than the flaw itself.</span>
      </div></details>
      <div class="stats">`
      + cell("gift, median", st.gift_med_bp + " bp",
             st.gift_med_bp > 5 ? "bad" : "")
      + cell("mean", st.gift_avg_bp + " bp")
      + (st.gift_lag_med == null ? "" :
         cell("decision lag", st.gift_lag_med + " s"))
      + cell("trades", st.gift_n)
      + `</div>`;
  }
  // Две руки рядом. Они учатся на одних данных и одном универсуме, и
  // почти любой вопрос к ним сравнительный: где разошлись и на чём.
  // Переключение вкладок этого не отвечает — ответ теряется по дороге.
  const CMP = [
    ["balance", a => { const x = (d.accounts||{})[a];
      return x ? x.balance + " $" : "—"; }],
    ["closed", a => (d.stats[a]||{}).closed ?? "—"],
    ["sign right", a => { const v = (d.stats[a]||{}).hit_rate;
      return v == null ? "—" : (v*100).toFixed(0) + " %"; }],
    ["net per trade", a => { const v = (d.stats[a]||{}).net_bp_avg;
      return v == null ? "—" : (v>0?"+":"") + v + " bp"; }],
    ["round trip", a => { const v = (d.stats[a]||{}).exec_med_bp;
      return v == null ? "—" : v + " bp"; }],
    ["account drawdown", a => { const v = ((d.stats[a]||{}).dd_book||{}).pct;
      return v == null ? "—" : v + " %"; }],
    ["worst open moment", a => { const v =
      ((d.stats[a]||{}).dd_open_book||{}).cap_bp;
      return v == null ? "—" : (v/100).toFixed(2) + " %"; }],
  ];
  html += `<div class="gt">arms side by side</div>`
    + `<details class="hint"><summary>how to read</summary>
       <div class="note">Same data, same universe, same hour, same
       slots &mdash; only the model differs. The gap between the two
       columns is the <b>measurement error</b> made visible: neither
       column is a result on its own.</div></details>`
    + `<div class="scroll"><table class="cmp"><tr><th></th>`
    + `<th style="color:${ARMC.gbm}">ml (trees)</th>`
    + `<th style="color:${ARMC.nn}">ai (neural)</th></tr>`
    + CMP.map(r => `<tr><td>${r[0]}</td><td>${r[1]("gbm")}</td>`
                 + `<td>${r[1]("nn")}</td></tr>`).join("")
    + `</table></div>`;
  const accLine = ["gbm","nn"].map(a => {
    const x = (d.accounts||{})[a];
    return x ? `${a === "gbm" ? "ml" : "ai"} ${x.balance} $` : null;
  }).filter(Boolean).join(" · ");
  if (accLine)
    html += `<div class="note" style="margin-top:8px">paper accounts: ${
      accLine} <span class="k">(start 1000 $ each, one capital,
      leverage 1&times;)</span></div>`;
  document.getElementById("stats").innerHTML = html;
  drawEq(d);
  document.getElementById("stats").querySelectorAll("[data-sa]")
    .forEach(b => b.onclick = () => { S.arm = b.dataset.sa; load(); });

  const sel = document.getElementById("sym");
  if (sel.options.length <= 1 && (d.symbols||[]).length) {
    for (const x of d.symbols) {
      const o = document.createElement("option");
      o.value = x; o.textContent = x.replace("USDT","");
      sel.appendChild(o);
    }
  }
  const SIT = !!d.situational;
  document.getElementById("thw").textContent = SIT ? "entered" : "signal hour";
  document.getElementById("thw2").textContent = SIT ? "sheet hour" : "entry";
  document.getElementById("tb").innerHTML = (d.rows||[]).map(t => {
    const cls = t.state === "закрыта"
      ? (t.net_bp > 0 ? "good" : "bad") : "";
    // У книги без срока первым идёт МОМЕНТ ВХОДА: час — это ключ
    // листа сечения, и сделка, открытая сканером в 18:16, стояла бы
    // под «17:00» — на телефоне, где колонка входа скрыта, она
    // читается как старая сделка по таймеру.
    return `<tr><td class="mono" title="UTC key ${t.hour}">${
        SIT ? hhmm(t.opened_at) : hourLocal(t.hour)}</td>
      <td class="mono hide-s">${
        SIT ? hourLocal(t.hour) : hhmm(t.opened_at)}</td>
      <td class="mono hide-s">${hhmm(t.closes_at)}</td>
      <td class="mono hide-s" style="color:var(--muted)">${t.lag_sec == null
        ? "—" : Math.round(t.lag_sec/60) + "m"}</td>
      <td class="hide-s">${t.arm === "nn" ? "neural" : "trees"}</td>
      <td class="mono">${t.sym.replace("USDT","")}</td>
      <td>${t.side === "long" ? "L" : "S"}</td>
      <td class="mono hide-s">${pct(t.expected_bp)}</td>
      <td class="mono hide-s" style="color:var(--muted)">${pct(t.mae_bp)}</td>
      <td class="mono">${pct(t.got_bp)}</td>
      <td class="mono ${cls}">${pct(t.net_bp)}</td>
      <td class="mono ${t.unreal_net_bp == null ? "" :
          (t.unreal_net_bp > 0 ? "good" : "bad")}"
          data-mk="${t.arm}|${t.hour}|${t.sym}|${t.side}">${
          pct(t.unreal_net_bp)}</td>
      <td class="mono ${t.dd_cap_bp < -100 ? "bad" : ""}"
          title="${t.dd_bp == null ? "" : pct(t.dd_bp)
            + " of the position, " + (t.dd_usd ?? "?") + " $, "
            + (t.dd_hours ?? "?") + " h of the hold covered"}">${
          t.dd_cap_bp == null
            ? (t.dd_bp == null ? "—" : "· " + pct(t.dd_bp))
            : pct(t.dd_cap_bp)}</td>
      <td class="mono ${cls}">${t.pnl == null ? "—"
        : (t.pnl > 0 ? "+" : "") + t.pnl.toFixed(2)}</td>
      <td class="hide-s" style="color:var(--muted)"
          title="${t.exit_reason || ""}">${ST_EN[t.state] || t.state}${
        t.exit_reason
        ? ` <span class="k">· ${EXIT_EN[t.exit_reason]
            || t.exit_reason}</span>` : ""}${
        t.state === "открыта" && t.closes_in_sec != null
        ? ` <span class="k">(${(t.closes_in_sec/3600).toFixed(1)} h
            left)</span>` : ""}</td>
      <td class="mono hide-s" style="color:var(--muted)">${t.odd == null ? "—"
        : (t.odd*100).toFixed(0) + " %"}</td>
      <td><a class="open" title="plain-words breakdown of this trade"
        href="/trade-info?k=${encodeURIComponent(KEY)}&sym=${
        encodeURIComponent(t.sym)}&arm=${t.arm}&hour=${t.hour}&side=${
        t.side}${HZ ? "&hz=" + HZ : ""}${
        RR_MIN == null ? "" : "&rr=" + RR_MIN
        }" style="text-decoration:none">&#9432;</a>
        <a class="open" href="/chart?k=${encodeURIComponent(KEY)}&sym=${
        encodeURIComponent(t.sym)}&arm=${t.arm}&hour=${t.hour}${
        HZ ? "&hz=" + HZ : ""}${
        // Порог едет в ссылку: он выбирает не только подмножество, но
        // и ЗАПИСЬ. Без него график просил у сервера торгуемую книгу,
        // не находил там сделку с отношением ниже гейта и говорил
        // «у этой руки в этом часе сделки нет» — ответ верный для
        // другой книги и потому неверный по существу.
        RR_MIN == null ? "" : "&rr=" + RR_MIN}">open</a></td></tr>`;
  }).join("") || `<tr><td colspan="17" style="color:var(--muted);
    padding:10px 0">no trades yet</td></tr>`;
  document.getElementById("pg").textContent =
    `page ${d.page + 1} of ${d.pages}`;
  // Порог владельца обязан быть подписан ТАМ ЖЕ, где счёт: иначе
  // отфильтрованная кривая читается как деньги книги.
  const rl = document.getElementById("rrlab");
  // Подписей две, и путать их нельзя: одна про ОТБОР (счёт пересчитан
  // на подмножестве), другая про ИСТОЧНИК (на экране наблюдательная
  // запись, а не торгуемая книга). Порог ниже гейта делает второе, не
  // первое: отбирать там нечего, книга таких сделок не открывала.
  const obs = d.source_book === "observation"
    ? `<span class="k">observation record — same entry rules, the
       reward/risk requirement dropped, its own account; the shadowed
       bot does not trade it</span> ` : "";
  if (rl) rl.innerHTML = obs + (!d.rr_min ? ""
    : `<span class="k">reward/risk ≥ ${d.rr_min}: ${d.grand_total}
       of ${(d.grand_total || 0) + (d.rr_cut || 0)} trades, account
       recomputed on this subset — a “what if”, not the book’s
       money</span>`);
  document.getElementById("cnt").textContent = d.filtered
    ? `${d.total} match of ${d.grand_total}` : `${d.total} trades`;
  document.getElementById("prev").disabled = d.page <= 0;
  document.getElementById("next").disabled = d.page + 1 >= d.pages;
}
document.getElementById("prev").onclick = () => { S.page--; load(); };
document.getElementById("next").onclick = () => { S.page++; load(); };
for (const id of ["arm","state","sym","per"])
  document.getElementById(id).onchange = () => { S.page = 0; load(); };
// Полная выдача — раз в минуту, переоценка открытых — раз в десять
// секунд. Тянуть весь список каждые десять секунд значит повторить
// ошибку, из-за которой страница писала «нет связи со сборщиком» на
// исправном сборщике: тяжёлый ответ не успевал прийти до следующего
// опроса.
async function marks() {
  let d;
  try {
    const r = await fetch("/model_marks?k=" + encodeURIComponent(KEY));
    d = await r.json();
  } catch (e) { return; }
  const by = {};
  for (const m of d.rows || [])
    by[[m.arm, m.hour, m.sym, m.side].join("|")] = m;
  document.querySelectorAll("[data-mk]").forEach(td => {
    const m = by[td.dataset.mk];
    if (!m) return;
    td.textContent = pct(m.unreal_net_bp);
    td.className = "mono " + (m.unreal_net_bp == null ? ""
      : (m.unreal_net_bp > 0 ? "good" : "bad"));
  });
  const t = document.getElementById("mkat");
  if (t) t.textContent = "marks " + hhmm(d.at);
}
load(); setInterval(load, 60000);
marks(); setInterval(marks, 10000);
</script>
"""


BOTPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Execution core — shadow</title>
<style>
/* Дизайн — наследник algoth_v1: тот же тёмный сине-фиолетовый фон и
   пурпурный акцент, но без тяжёлых градиентов первой версии — тонкие
   рамки, воздух, крупные числа. Тема одна: фирменный цвет v1 и есть
   тёмная тема, переключателей внешнего вида не бывает (правило v2). */
:root{color-scheme:dark;
 --ground:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --accent:#9747ff;--accent2:#694ef0;
 --good:#3ddc7f;--bad:#ff6473;
 --good-soft:rgba(61,220,127,.1);--bad-soft:rgba(255,100,115,.1)}
*{box-sizing:border-box;margin:0}
body{background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,
  var(--ground);
 color:var(--ink);
 font:14px/1.5 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.wrap{max-width:1160px;margin:0 auto;padding:0 16px 72px}
.top{position:sticky;top:0;z-index:5;display:flex;align-items:center;
 gap:10px;flex-wrap:wrap;padding:14px 0 12px;margin-bottom:12px;
 background:rgba(11,8,32,.82);backdrop-filter:blur(10px);
 border-bottom:1px solid var(--rule-soft)}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none;white-space:nowrap}
.brand b{color:var(--accent);font-weight:800}
.tag{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);border:1px solid var(--rule);border-radius:999px;
 padding:4px 10px;background:rgba(151,71,255,.06);white-space:nowrap}
.sp{flex:1 1 auto}
.pill{display:inline-flex;align-items:center;gap:7px;font-size:12px;
 color:var(--muted);border:1px solid var(--rule);border-radius:999px;
 padding:4px 11px;background:var(--chip);white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--good);
 box-shadow:0 0 6px var(--good);flex:none}
.hb-stale .dot{background:var(--bad);box-shadow:0 0 6px var(--bad)}
.chip{display:inline-flex;align-items:baseline;gap:8px;
 border:1px solid var(--rule);border-radius:10px;padding:5px 12px;
 background:var(--chip)}
.ck{font-size:9px;letter-spacing:.12em;text-transform:uppercase;
 color:var(--muted)}
.cv{font-size:14px;font-weight:650}
.k{color:var(--muted);font-size:12px}
.good{color:var(--good)} .bad{color:var(--bad)}
.stats{display:grid;grid-template-columns:repeat(auto-fill,
 minmax(155px,1fr));gap:10px;margin:0 0 14px}
.st{background:linear-gradient(180deg,rgba(151,71,255,.06),
  rgba(151,71,255,0) 55%),var(--panel);
 border:1px solid var(--rule);border-radius:14px;padding:11px 13px}
.st .k{font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.st .v{font-size:17px;font-weight:600;margin-top:5px}
.card{background:var(--panel);border:1px solid var(--rule);
 border-radius:16px;padding:14px 16px;margin-bottom:14px}
.cap{display:flex;justify-content:space-between;align-items:baseline;
 gap:10px;flex-wrap:wrap;font-size:10.5px;letter-spacing:.12em;
 text-transform:uppercase;color:var(--muted);margin-bottom:10px}
.meta{letter-spacing:0;text-transform:none;font-size:11.5px;
 color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:10px;
 letter-spacing:.1em;text-transform:uppercase;
 padding:6px 10px 7px 0;border-bottom:1px solid var(--rule)}
td{padding:7px 10px 7px 0;white-space:nowrap;
 border-bottom:1px solid var(--rule-soft)}
tbody tr:hover td{background:rgba(151,71,255,.04)}
tr[data-pos]{cursor:pointer}
#tchart{width:100%;height:520px;border:0;border-radius:12px;
 background:var(--ground);display:block}
.scroll{overflow-x:auto}
.side{display:inline-block;min-width:22px;text-align:center;
 border-radius:6px;font-size:11px;font-weight:700;padding:1px 6px}
.side.l{color:var(--good);background:var(--good-soft)}
.side.s{color:var(--bad);background:var(--bad-soft)}
canvas{width:100%;display:block}
pre{white-space:pre-wrap;font-size:12px;color:var(--muted);
 margin:10px 0 0}
.alarm{border-color:rgba(255,100,115,.5);background:var(--bad-soft);
 color:var(--bad);font-weight:600}
details summary{cursor:pointer}
.foot{color:var(--muted);font-size:12px;margin-top:20px;line-height:1.7}
@media(max-width:640px){
 .wrap{padding:0 10px 60px}
 .stats{grid-template-columns:repeat(auto-fill,minmax(138px,1fr));gap:8px}
 .card{padding:12px;border-radius:14px}}
</style>
<div id="botlike-page" class="wrap">
<header class="top">
  <a id="back" href="#" class="brand" title="to overview">ALG<b>O</b>TH</a>
  <span class="tag">execution core · shadow</span>
  <span class="sp"></span>
  <span id="hb" class="pill"><span class="dot"></span><span
    id="topage" class="mono">…</span></span>
  <span id="src" class="pill mono"></span>
  <span class="chip"><span class="ck">balance</span><span
    id="topbal" class="cv mono">…</span></span>
</header>
  <div id="alarm"></div>
  <div class="stats" id="acct">…</div>
  <section class="card" id="tcard" style="display:none">
    <div class="cap"><span>trade on chart</span>
      <span id="tlab" class="mono meta"></span></div>
    <iframe id="tchart" title="trade chart"></iframe></section>
  <section class="card"><div class="cap"><span>equity ·
      realised closes</span>
      <span id="eqlab" class="mono meta"></span></div>
    <canvas id="eq" height="200"></canvas></section>
  <section class="card"><div class="cap"><span>open positions</span>
      <span class="meta">marked to the collector&#39;s own book mids,
        costs not deducted · click a row to see it on the chart</span></div>
    <div class="scroll"><table>
      <thead><tr><th>coin</th><th>side</th><th>size $</th><th>entry</th>
        <th>mid now</th><th>unreal</th><th>unreal $</th><th>age</th>
        <th>closes in</th></tr></thead>
      <tbody id="pos"></tbody></table></div></section>
  <section class="card"><div class="cap"><span>closed trades</span>
      <span id="cnt" class="mono meta"></span></div>
    <div class="scroll"><table>
      <thead><tr><th>hour</th><th>coin</th><th>side</th><th>size $</th>
        <th>entry</th><th>exit</th><th>pnl $</th><th>cost basis</th>
      </tr></thead><tbody id="cl"></tbody></table></div></section>
  <section class="card"><details><summary class="cap">reconciliation
      vs the Python books — report</summary>
    <pre id="sv">…</pre></details></section>
  <footer class="foot">this page only reads: the emergency stop is the
    KILL file on the server — the page shows it, never presses it
    · refreshes every 30 s</footer>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("back").href = "/?k=" + encodeURIComponent(KEY);
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();
const FMT = new Intl.DateTimeFormat("en-GB", {timeZone: "Europe/Vienna",
  hour: "2-digit", minute: "2-digit"});
const hhmm = ts => ts ? FMT.format(new Date(ts * 1000)) : "—";
// Цены журнала — двоичные числа, и напрямую они печатаются с хвостом
// вида 0.032045000000000004; десяти значащих цифр хватает любому шагу
// цены площадки, а повторное «+» срезает нули хвоста.
const px = v => v == null ? "—" : String(+(+v).toPrecision(10));
// Книга, которую ведёт тень, — из /bot-full (маркер источника
// журнала). Нужна графику: сделка часовой книги и ситуационной живут
// в разных каталогах, и без адреса график молча показал бы не ту.
let BOOK_HZ = "";
// Клик по строке сделки открывает её на графике НАД equity: тот же
// чарт, что живёт своей страницей, во встроенном режиме (embed) —
// вторая реализация графика однажды разошлась бы с первой.
function showTrade(pos) {
  const m = String(pos || "").split(":");
  if (m.length < 4) return;
  const p = new URLSearchParams({k: KEY, sym: m[2], arm: m[0],
                                 hour: m[1], embed: 1});
  if (BOOK_HZ) p.set("hz", BOOK_HZ);
  // Порог владельца выбирает запись, а не только подмножество: без
  // него график ищет сделку в торгуемой книге, где её нет. На
  // странице ядра дилера нет вовсе — там порог не задан, и график
  // сам переспросит наблюдательную запись, если не найдёт сделку.
  if (typeof RR_MIN !== "undefined" && RR_MIN != null)
    p.set("rr", String(RR_MIN));
  const card = document.getElementById("tcard");
  card.style.display = "";
  const f = document.getElementById("tchart");
  const src = "/chart?" + p.toString();
  if (f.src !== src) f.src = src;
  document.getElementById("tlab").textContent =
    `${m[2].replace("USDT", "")} · ${m[3]} · signal hour ${m[1]}`;
  if (card.scrollIntoView) card.scrollIntoView({behavior: "smooth"});
}
for (const id of ["pos", "cl"]) {
  document.getElementById(id).onclick = e => {
    const tr = e.target && e.target.closest
      ? e.target.closest("[data-pos]") : null;
    if (tr) showTrade(tr.dataset.pos);
  };
}
function cell(k, v, cls) {
  return `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls || ""}">${v}</div></div>`;
}
function drawEq(curve, capital) {
  const cv = document.getElementById("eq");
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const W = cv.clientWidth || 700, H = 200;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!curve || curve.length < 2) return;
  let lo = capital, hi = capital;
  for (const [, v] of curve) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const x = i => 8 + (W - 66) * i / (curve.length - 1);
  const y = v => 10 + (H - 34) * (hi - v) / (hi - lo);
  // Заливка под кривой — фирменный пурпур v1; в headless-прогоне
  // createLinearGradient заглушен и возвращает пустоту, поэтому охрана.
  const fill = g.createLinearGradient
    ? g.createLinearGradient(0, 0, 0, H) : null;
  if (fill && fill.addColorStop) {
    fill.addColorStop(0, "rgba(151,71,255,.26)");
    fill.addColorStop(1, "rgba(151,71,255,0)");
    g.beginPath();
    curve.forEach(([, v], i) =>
      i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)));
    g.lineTo(x(curve.length - 1), H - 6); g.lineTo(x(0), H - 6);
    g.closePath(); g.fillStyle = fill; g.fill();
  }
  g.setLineDash([4, 4]); g.strokeStyle = css("--rule");
  g.beginPath(); g.moveTo(8, y(capital)); g.lineTo(W - 58, y(capital));
  g.stroke(); g.setLineDash([]);
  g.strokeStyle = css("--accent"); g.lineWidth = 2;
  g.lineJoin = "round"; g.lineCap = "round";
  g.beginPath();
  curve.forEach(([, v], i) => i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)));
  g.stroke();
  const lastV = curve[curve.length - 1][1];
  g.fillStyle = css("--accent");
  g.beginPath(); g.arc(x(curve.length - 1), y(lastV), 3, 0, 7); g.fill();
  g.fillStyle = css("--muted"); g.font = "11px ui-monospace,Menlo,monospace";
  g.fillText(hi.toFixed(0), W - 52, 16);
  g.fillText(lo.toFixed(0), W - 52, H - 10);
}
async function load() {
  let d;
  try {
    const r = await fetch(`/bot-full?k=${encodeURIComponent(KEY)}`);
    d = await r.json();
  } catch (e) {
    document.getElementById("alarm").innerHTML =
      `<div class="card alarm">no connection to the collector</div>`;
    return;
  }
  if (!d.present) {
    document.getElementById("alarm").innerHTML =
      `<div class="card">core not running — the shadow is not deployed
       yet</div>`;
    return;
  }
  BOOK_HZ = d.book_hz || "";
  document.getElementById("src").textContent = `arm ${d.arm}`
    + (BOOK_HZ ? ` · ${BOOK_HZ === "sit" ? "situational" : BOOK_HZ}` : "");
  const hb = document.getElementById("hb");
  hb.className = "pill" + (d.age_sec > 300 ? " hb-stale" : "");
  document.getElementById("topage").textContent =
    d.age_sec == null ? "—" : `${Math.round(d.age_sec)} s`;
  const bad = [];
  if (d.age_sec != null && d.age_sec > 300)
    bad.push(`STATUS SILENT for ${Math.round(d.age_sec / 60)} min — process hung`);
  if (d.error) bad.push(`ERROR: ${d.error}`);
  if (d.journal_error) bad.push(`JOURNAL: ${d.journal_error}`);
  const ch = d.check || {};
  if (ch.ok === false)
    bad.push(`INVARIANTS: ${(ch.violations || []).join("; ")}`);
  const sv = d.sverka || {};
  // Возраст вердикта — рядом с самим вердиктом. Сверка идёт раз в час,
  // и красное от прошлого часа читается как красное сейчас: владелец
  // так и прочёл вердикт, посчитанный за полторы минуты ДО того, как
  // книга и журнал переначались, — оба уже были пусты.
  const svAge = (sv.at_ms && d.server_now)
    ? Math.max(0, d.server_now - sv.at_ms / 1000) : null;
  const svAgeTxt = svAge == null ? ""
    : svAge < 90 ? `${Math.round(svAge)} s ago`
    : `${Math.round(svAge / 60)} min ago`;
  if (sv.ok === false)
    bad.push((sv.note || "RECONCILIATION: mismatches")
             + (svAgeTxt ? ` <span class="k">(checked ${svAgeTxt})</span>`
                         : ""));
  if (d.kill) bad.push("KILL SWITCH ON — no new entries");
  document.getElementById("alarm").innerHTML = bad.length
    ? `<div class="card alarm">${bad.join("<br>")}</div>` : "";
  const cap = d.capital_usd || 1000;
  const share = ((d.balance_usd / cap - 1) * 100).toFixed(2);
  const tb = document.getElementById("topbal");
  tb.textContent = `${d.balance_usd} $`;
  tb.className = "cv mono " + (d.balance_usd >= cap ? "good" : "bad");
  const cnt = d.counts || {};
  document.getElementById("acct").innerHTML =
    cell("balance", `${d.balance_usd} $`,
         d.balance_usd >= cap ? "good" : "bad")
    + cell("vs start", `${share > 0 ? "+" : ""}${share} %`,
           share >= 0 ? "good" : "bad")
    + cell("in positions", `${(d.busy_usd || 0).toFixed(2)} $`)
    + cell("free cash", `${(d.cash_usd || 0).toFixed(2)} $`)
    + cell("open / closed", `${cnt.open ?? "—"} / ${cnt.closed ?? "—"}`)
    + cell("decisions / rejects",
           `${cnt.decisions ?? "—"} / ${cnt.rejects ?? "—"}`)
    + cell("invariants", ch.ok === true ? "intact" : "CHECK",
           ch.ok === true ? "good" : "bad")
    + cell("reconciliation", (sv.ok === true ? "0 mismatches"
           : sv.ok == null ? "not run yet" : "MISMATCH")
           + (svAgeTxt && sv.ok != null ? ` · ${svAgeTxt}` : ""),
           sv.ok === true ? "good" : sv.ok === false ? "bad" : "")
    + cell("status age", d.age_sec == null ? "—"
           : `${Math.round(d.age_sec)} s`,
           d.age_sec > 300 ? "bad" : "");
  drawEq(d.curve, cap);
  document.getElementById("eqlab").textContent =
    (d.curve || []).length + " closes";
  const now = d.server_now || 0;
  document.getElementById("pos").innerHTML = (d.positions || []).map(p => `
    <tr data-pos="${p.pos || ""}"><td class="mono">${
      (p.sym || "").replace("USDT", "")}</td>
    <td><span class="side ${p.side === "long" ? "l" : "s"}">${
      p.side === "long" ? "L" : "S"}</span></td>
    <td class="mono">${p.size}</td>
    <td class="mono">${px(p.entry_px)}</td>
    <td class="mono">${px(p.cur_mid)}</td>
    <td class="mono ${p.unreal_bp > 0 ? "good" : p.unreal_bp < 0 ? "bad" : ""}">
      ${p.unreal_bp == null ? "—" : (p.unreal_bp > 0 ? "+" : "")
        + (p.unreal_bp / 100).toFixed(2) + " %"}</td>
    <td class="mono">${p.unreal_usd == null ? "—"
      : (p.unreal_usd > 0 ? "+" : "") + p.unreal_usd}</td>
    <td class="mono">${p.opened_at ? ((now - p.opened_at) / 3600).toFixed(1) + " h" : "—"}</td>
    <td class="mono">${p.closes_at ? ((p.closes_at - now) / 3600).toFixed(1) + " h" : "—"}</td>
    </tr>`).join("")
    || `<tr><td colspan="9" class="k">no open positions</td></tr>`;
  document.getElementById("cnt").textContent =
    `showing ${(d.closed || []).length} of ${d.closed_total || 0}`;
  document.getElementById("cl").innerHTML = (d.closed || []).map(t => `
    <tr data-pos="${t.pos || ""}"><td class="mono" title="${t.pos}">${
      t.hour.slice(5)} ${hhmm(t.closed_at)}</td>
    <td class="mono">${(t.sym || "").replace("USDT", "")}</td>
    <td><span class="side ${t.side === "long" ? "l" : "s"}">${
      t.side === "long" ? "L" : "S"}</span></td>
    <td class="mono">${t.size}</td>
    <td class="mono">${px(t.entry_px)}</td>
    <td class="mono">${px(t.exit_px)}</td>
    <td class="mono ${t.pnl > 0 ? "good" : t.pnl < 0 ? "bad" : ""}">${
      t.pnl > 0 ? "+" : ""}${t.pnl}</td>
    <td class="k">${t.basis}</td></tr>`).join("")
    || `<tr><td colspan="8" class="k">no closed trades yet</td></tr>`;
  document.getElementById("sv").textContent =
    d.sverka_report || "no reconciliation report yet";
}
load(); setInterval(load, 30000);
</script>
"""

CHART = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chart — live</title>
<style>
/* Палитра — та же, что у страницы ядра: наследие v1 (тёмный фиолет,
   пурпур #9747ff) в современном исполнении. Тема одна, настроек
   внешнего вида нет — правило v2. */
:root{color-scheme:dark;
 --ground:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff;--grid:#1c1839;
 --bid-soft:rgba(61,220,127,.1);--ask-soft:rgba(255,100,115,.1)}
*{box-sizing:border-box;margin:0}
body{background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,
  var(--ground);
 color:var(--ink);
 font:14px/1.5 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.wrap{max-width:1180px;margin:0 auto;padding:12px 14px 56px}
.bar{display:flex;flex-wrap:wrap;gap:7px;align-items:center;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:14px;
 color:var(--ink);text-decoration:none;white-space:nowrap;
 margin-right:2px}
.brand b{color:var(--accent);font-weight:800}
h1{font-size:16px;margin:0 4px 0 0;font-weight:650}
button,a.btn{font:inherit;font-size:12.5px;color:var(--muted);
 background:var(--chip);border:1px solid var(--rule);padding:4px 11px;
 border-radius:999px;cursor:pointer;text-decoration:none;
 transition:border-color .15s,color .15s}
button:hover,a.btn:hover{color:var(--ink);border-color:var(--accent)}
button[aria-pressed=true]{color:var(--ink);border-color:var(--accent);
 background:rgba(151,71,255,.14)}
.sp{flex:1 1 auto}
/* Выбор монеты: выпадающий список с поиском и секторами. Плоская
   стена из пяти сотен кнопок нечитаема и пересобиралась каждым тактом
   — тот же урок, что группы на обзоре. */
.pickwrap{position:relative}
.pickwrap>summary{list-style:none;cursor:pointer;font:inherit;
 font-size:12.5px;color:var(--muted);background:var(--chip);
 border:1px solid var(--rule);border-radius:999px;padding:4px 11px;
 white-space:nowrap;transition:border-color .15s,color .15s}
.pickwrap>summary::-webkit-details-marker{display:none}
.pickwrap>summary:hover{color:var(--ink);border-color:var(--accent)}
.pickwrap[open]>summary{color:var(--ink);border-color:var(--accent);
 background:rgba(151,71,255,.14)}
.pick{position:absolute;left:0;top:calc(100% + 6px);z-index:30;
 width:min(88vw,560px);max-height:62vh;overflow-y:auto;
 background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:10px;
 box-shadow:0 14px 40px rgba(0,0,0,.5)}
.pick input{width:100%;font:inherit;font-size:16px;color:var(--ink);
 background:var(--chip);border:1px solid var(--rule);border-radius:10px;
 padding:7px 10px;margin-bottom:6px}
details.grp{border-top:1px solid var(--rule-soft)}
details.grp summary::-webkit-details-marker{display:none}
details.grp summary{cursor:pointer;padding:6px 2px;font-size:12px;
 color:var(--muted);letter-spacing:.03em;list-style:none;
 display:flex;justify-content:space-between}
details.grp summary::after{content:"▸";color:var(--muted)}
details.grp[open] summary::after{content:"▾"}
details.grp .gs{display:flex;flex-wrap:wrap;gap:5px;padding:2px 0 8px}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:16px;margin-bottom:14px;position:relative;
 overflow:hidden}
.cap{padding:9px 14px;border-bottom:1px solid var(--rule-soft);
 font-size:10.5px;color:var(--muted);letter-spacing:.12em;
 text-transform:uppercase;display:flex;justify-content:space-between;
 gap:8px;flex-wrap:wrap}
canvas{display:block;width:100%;touch-action:none}
#tip{position:absolute;z-index:5;pointer-events:none;display:none;
 background:var(--chip);border:1px solid var(--rule);padding:8px 10px;
 font-size:12.5px;line-height:1.45;border-radius:10px;
 box-shadow:0 8px 28px rgba(0,0,0,.45)}
#tip .r{display:flex;justify-content:space-between;gap:14px}
#tip .r span:first-child{color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 10px;text-align:right;white-space:nowrap;
 border-bottom:1px solid var(--rule-soft)}
th{color:var(--muted);font-weight:500;font-size:10px;letter-spacing:.1em;
 text-transform:uppercase;position:sticky;top:0;background:var(--panel);
 border-bottom:1px solid var(--rule)}
td:first-child,th:first-child{text-align:left}
tbody tr:hover td{background:rgba(151,71,255,.04)}
.buy{color:var(--bid)} .sell{color:var(--ask)}
.hist{max-height:300px;overflow-y:auto}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;
 color:var(--muted);margin:10px 2px 14px}
.sw{display:inline-block;width:20px;height:0;border-top:2px solid;
 vertical-align:4px;margin-right:6px}
.stats{display:grid;grid-template-columns:repeat(auto-fill,
 minmax(128px,1fr));gap:8px;padding:10px 12px}
.st{background:linear-gradient(180deg,rgba(151,71,255,.06),
  rgba(151,71,255,0) 55%),var(--chip);
 border:1px solid var(--rule);border-radius:12px;padding:9px 11px}
.st .k{font-size:9.5px;color:var(--muted);letter-spacing:.1em;
 text-transform:uppercase}
.st .v{font-size:15px;font-weight:600;margin-top:4px}
.note{padding:10px 14px;color:var(--muted);font-size:13px}
</style>
<div class="wrap">
<div class="bar" id="topnav">
  <a class="brand" href="/" id="home" title="to overview">ALG<b>O</b>TH</a>
  <h1 id="ttl" class="mono">…</h1>
  <details class="pickwrap" id="pick">
    <summary id="npick">coins</summary>
    <div class="pick">
      <input id="symq" placeholder="search coin…" autocomplete="off">
      <div id="groups">…</div>
    </div>
  </details>
  <span class="sp"></span>
  <span id="marm"></span>
  <button id="fit">fit all</button>
  <button id="live" aria-pressed="true">follow live</button>
</div>
<div id="recnote"></div>
<div class="panel">
  <div class="cap"><span id="cap">1m candles · drag to pan —
      sideways and up/down · wheel or pinch zooms time, shift+wheel
      (or wheel over the price axis) zooms price · double click
      resets the price scale</span>
    <span id="cap2" class="mono"></span></div>
  <canvas id="px" height="420"></canvas>
  <div id="tip" class="mono"></div>
</div>
<div class="legend">
  <span><span class="sw" style="border-color:var(--accent)"></span>level</span>
  <span><span class="sw" style="border-color:var(--ask)"></span>stop</span>
  <span><span class="sw" style="border-color:var(--muted)"></span>where the
    model expects price to go against the trade — the stop stands
    beyond it</span>
  <span><span class="sw" style="border-color:var(--bid)"></span>target /
    profit promise</span>
  <span><span class="sw" style="border-color:var(--ink)"></span>entry &amp;
    exit dots</span>
  <span><span class="sw" style="background:rgba(61,220,127,.25);
    border-color:transparent"></span>profit side</span>
  <span><span class="sw" style="background:rgba(255,100,115,.25);
    border-color:transparent"></span>loss side</span>
  <span id="mleg"></span>
</div>
<div class="panel" id="paperpanel">
  <div class="cap"><span>paper trades summary — this coin</span>
    <button id="unit" style="padding:1px 9px">in R</button></div>
  <div id="sum" class="stats"></div>
  <div id="rules"></div>
  <canvas id="eq"></canvas>
</div>
<div class="panel" id="mpanel">
  <div class="cap"><span>trades on this pair &mdash; model</span>
    <span id="cap4" class="mono"></span></div>
  <div class="hist"><table><thead><tr>
    <th>entered utc</th><th>side</th><th>entry</th><th>exit</th>
    <th>exp</th><th>got</th><th>net</th><th>$</th><th>state</th>
  </tr></thead><tbody id="mrows"></tbody></table></div>
  <div id="mnote" class="note"></div>
</div>
<div class="panel" id="ppanel">
  <div class="cap"><span>trade history — paper, observation</span>
    <span id="cap3" class="mono"></span></div>
  <div class="hist"><table><thead><tr>
    <th>time</th><th>side</th><th>entry</th><th>stop</th><th>target</th>
    <th>rule</th><th>level</th><th>rr</th><th>state</th>
    <th>held</th><th>result</th>
  </tr></thead><tbody id="rows"></tbody></table></div>
</div>
</div>
<script>
const Q = new URLSearchParams(location.search);
const KEY = Q.get("k") || "";
// Встроенный режим: график живёт внутри страницы ядра. Прячется
// только обрамление — шапка с выбором монет и сводка бумажных сделок;
// свечи, слой сделок модели и подсказка работают как есть. Вторая
// реализация графика на странице ядра однажды разошлась бы с этой.
const EMBED = Q.get("embed") === "1";
if (EMBED) {
  // Прячется обрамление И баннер встречного счёта: на странице ядра
  // график показывает одну сделку тени, реплей бумажных правил там
  // ни при чём.
  for (const id of ["topnav", "paperpanel", "recnote"]) {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  }
}
let sym = Q.get("sym") || "";
let data = null, view = null, follow = true, HIT = [];
// Перекрестие: позиция курсора над графиком, null — курсора нет.
let CROSS = null;
// Состояния и виды уровней приходят с сервера по-русски: это КЛЮЧИ
// файлов и журналов. Перевод живёт на границе показа.
const KEY_EN = {"открыта": "open", "закрыта": "closed", "цель": "target",
  "стоп": "stop", "время": "time", "не открыта": "not taken",
  "оборвана перезапуском": "cut by restart", "ждёт разбора": "awaiting",
  "вышла, ждёт разбора": "exited, pnl pending",
  "без исхода": "no outcome", "полка": "shelf", "кругл": "round",
  "экстремум": "extreme", "лента": "tape", "стакан": "book",
  // Причины выхода ситуационной книги: таблица сделок модели на этой
  // же странице печатает их через `disp`, и без перевода строка
  // осталась бы русской посреди английской страницы.
  "прогноз развернулся": "forecast flipped",
  "цена прошла обещанный ход против": "adverse promise hit",
  "цена дошла до обещанной цели": "target reached",
  "предел возраста": "age limit"};
const disp = v => v == null ? "—" : (KEY_EN[v] || v);
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();
const stamp = t => new Date(t*1000).toISOString().slice(11,16);

// Опрос разностный — см. тот же приём на странице обзора.
const ST = {cand:[], since:0, sym:"", busy:false, fails:0};
const HIST = {trades:[], stats:null, by_rule:{}, by_ver:[], equity:[],
              at:0, busy:false, off:false};
// История свечей с диска: в памяти сборщика живут считанные часы, а
// trades поднимаются за трое суток — график обрывался там, где кончался
// буфер, и прошлые trades смотреть было не на чем. Тянется один раз на
// символ, живые candles ложатся поверх.
const HC = {sym:"", cand:[], busy:false, hours:24, end:0};
// Единица кривой счёта: базисные пункты — сколько денег при равном
// размере позиции, R — сколько при равном риске на сделку. Это разные
// вопросы, поэтому переключатель, а не выбор раз и навсегда.
let EQR = false;
// Встречный счёт: те же входы, нынешняя геометрия. Пока включён,
// подменяются ВСЕ панели разом — график, таблица, сводка, кривая, —
// потому что владельцу нужно видеть не отчёт о пересчёте, а сами
// trades: где стоял бы стоп, куда уехала бы цель, чем кончилось бы.
// Смешивать с настоящими исходами нельзя, поэтому это переключатель, а
// не добавка, и включённое состояние подписано над графиком.
// Переключатель переживает перезагрузку — см. тот же приём на обзоре.
const REC = {on:true, busy:false, data:null, timer:null, sym:"", err:0};
function wipe() { ST.cand=[]; ST.since=0; HIST.trades=[]; HIST.stats=null;
                  HIST.by_rule={}; HIST.equity=[]; HIST.at=0;
                  HC.sym=""; HC.cand=[]; HC.end=0;
                  MDL.trades=[]; MDL.sym=""; MDL.at=0;
                  REC.data=null; REC.sym=""; }

async function pullRec(go) {
  if (REC.busy || !sym) return;
  REC.busy = true;
  try {
    // `go=0` всегда: счёт запускает сборщик сам при смене версии
    // правил, страница только забирает готовое.
    const r = await fetch(`/recount?k=${encodeURIComponent(KEY)}`
      + `&sym=${encodeURIComponent(sym)}&hours=24&go=0`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    REC.data = await r.json(); REC.sym = sym; REC.err = 0;
  } catch (e) {
    // Молча проглоченный отказ выглядит как «считаю…» без конца, а
    // график при этом не меняется — ровно тот симптом, который
    // владелец и увидел. Отказ обязан называть себя.
    REC.err = (REC.err || 0) + 1;
  }
  finally { REC.busy = false; }
  if (REC.data && REC.data.busy && !REC.timer)
    REC.timer = setInterval(() => pullRec(false), 3000);
  if (REC.data && !REC.data.busy && REC.timer) {
    clearInterval(REC.timer); REC.timer = null;
  }
  renderRec(); draw(); rows(); mrows(); summary();
}

// Пересчёт годен к показу, только когда он досчитан и посчитан по ЭТОЙ
// монете: чужой список сделок на чужом графике выглядел бы как trades,
// которых не было.
// Выключенный пересчёт РЕЗУЛЬТАТОМ не является: ответ `off` говорит,
// что бумажных сделок не ведут вовсе. Прежде он проходил как готовый
// пересчёт с пустым списком, и таблица подписывалась «0 сделок,
// пересчёт, не факт» — то есть выключенное наблюдение выглядело как
// посчитанная пустота.
function recReady() {
  return REC.data && !REC.data.busy && !REC.data.off && REC.sym === sym
    ? REC.data : null;
}

function renderRec() {
  const box = document.getElementById("recnote"), d = REC.data;
  if (d && d.off) {
    box.innerHTML = `<div class="panel"><div class="note">detector paper trades
      are off: tape direction closed by measurements, absorption feeds
      the model as features</div></div>`;
    return;
  }
  if (REC.err) {
    box.innerHTML = `<div class="panel"><div class="note">replay is not
      responding (${REC.err} failed attempts). Showing actual history.
      Try again when connection recovers.</div></div>`;
    return;
  }
  if (!d || d.busy) {
    box.innerHTML = `<div class="panel"><div class="note">replaying the same
      entries under current rules${d ? `: ${d.done} of ${d.total} coins` : ""}…
      </div></div>`;
    return;
  }
  box.innerHTML = `<div class="panel"><div class="note">`
    + (d.stale ? `<b style="color:var(--ask)">replay computed under rules
        v${d.ver}, current is v${d.now_ver}</b> — refresh to recompute.<br>` : "") + `
    <b>replay</b> — the page shows NOT actual outcomes but the same
    entries run under rules v${d.ver} (window ${d.hours} h, took
    ${d.took_sec} s). Same price path, different trade: stop and target
    are recomputed, so the exit differs too. Entries taken for this coin:
    ${d.made}, rejected by the new geometry: ${d.refused}.
    <br>Chart, table and summary show ONLY the replay.`
    + ageLine(d, HIST.trades) + coverLine(d, HIST.trades.length)
    + `</div></div>`;
}

// Возраст пересчёта. Он намеренно не обновляется сам, поэтому обязан
// говорить, когда посчитан: снимок трёхчасовой давности на исправном
// сборщике неотличим от «новых сделок нет». Флаг `stale` этого не ловит
// — он сравнивает версию правил, а не время.
function ageLine(d, live) {
  if (!d.at) return "";
  const now = ST.since || Date.now() / 1000;
  const mins = Math.max(0, Math.round((now - d.at) / 60));
  const fresh = (live || []).filter(t => t.t > d.at).length;
  const hhmm = new Date(d.at * 1000).toISOString().slice(11, 16);
  return `<br><span style="opacity:.8">computed at ${hhmm} UTC, `
    + `${mins} min ago — NOT recomputed since.`
    + (fresh
        ? ` <b style="color:var(--ask)">Live trades after that moment: `
          + `${fresh}, not shown here</b> — refresh the replay.`
        : ` No new live trades since.`)
    + `</span>`;
}

// Сколько входов из таблицы вообще попало в пересчёт — см. тот же приём
// на странице обзора. Недосчитанное обязано называться числом.
function coverLine(d, shownN) {
  const seen = (d.made || 0) + (d.refused || 0);
  if (!shownN || seen >= shownN) return "";
  return `<br><span style="opacity:.8">replayed ${seen} of `
    + `${shownN} entries in the table: the rest are older than the `
    + `replay window (${d.hours} h). Summary covers replayed only.</span>`;
}

// Источник сделок и сводки для всех панелей сразу.
function shown() {
  const d = recReady();
  return d ? {trades: d.trades || [], stats: d.stats,
              by_rule: d.by_rule || {}, by_ver: [], ver: d.ver,
              equity: d.equity || [], rec: true} : HIST;
}

async function pullHistory(s, end) {
  const want = Math.round(end || 0);
  if (HC.busy || (HC.sym === s && HC.end === want)) return;
  HC.busy = true;
  try {
    const r = await fetch(`/candles?k=${encodeURIComponent(KEY)}&sym=${s}`
      + `&hours=${HC.hours}` + (want ? `&end=${want}` : ""));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    if (h.sym === s) {
      HC.cand = h.candles || []; HC.sym = s; HC.end = want;
      // Окно под сделку ставится ПОСЛЕ того, как пришли её свечи:
      // раньше ставить не на чем — номера баров считаются по ряду.
      if (want) fitFocus();
      draw();
    }
  } catch (e) { /* тихо: живые candles всё равно рисуются */ }
  finally { HC.busy = false; }
}
function mergeCandles(old, add) {
  if (!add.length) return old;
  const m = new Map(old.map(c => [c[0], c]));
  for (const c of add) m.set(c[0], c);
  return [...m.values()].sort((a,b) => a[0]-b[0]).slice(-1440);
}

// Имя `history` занято браузером, и объявление функции с таким именем
// ПЕРЕЗАПИСЫВАЕТ window.history (свойство заменяемое по спецификации):
// replaceState переставал быть функцией, обработчик переключения руки
// падал на полпути, и подсветка кнопки застывала на прежней руке.
async function pullHist() {
  // История сделок — не поток: она меняется раз в минуты, а опрос идёт
  // раз в секунду. Тянуть её вместе с состоянием значит платить за неё
  // каждую секунду.
  if (HIST.busy || Date.now() - HIST.at < 15000) return;
  HIST.busy = true;
  try {
    const r = await fetch(`/trades?k=${encodeURIComponent(KEY)}&sym=${sym}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    // Выключенный детектор — это ОТВЕТ, а не пустота. Сервер говорит
    // об этом полем `off`, а страница его теряла и печатала «ждёт
    // условий»: владелец прочёл выключенное наблюдение как поломку
    // записи. Отказ, неотличимый от тишины, — сквозная болезнь этого
    // проекта, и здесь она была в показе.
    HIST.off = !!h.off;
    HIST.trades = h.trades || []; HIST.stats = h.stats;
    HIST.by_rule = h.by_rule || {}; HIST.older = h.older || 0;
    HIST.by_ver = h.by_ver || [];
    HIST.ver = h.ver;
    HIST.equity = h.equity || []; HIST.at = Date.now();
  } catch (e) { /* тихо: следующий круг попробует снова */ }
  finally { HIST.busy = false; }
}

// Сделки МОДЕЛИ — отдельным запросом и отдельным слоем. Мешать их с
// бумажными сделками детектора нельзя: это два разных механизма, и
// одна таблица на двоих однажды сложила бы их статистику.
//
// Рука выбирается, а не показывается вся: у двух моделей турнира сделки
// идут в одни и те же часы по одним и тем же монетам, и нарисованные
// вместе они ложатся друг на друга — вход одной закрывает вход другой,
// и по картинке не сказать, чья она. Переключатель, а не «обе», именно
// поэтому.
const ARMS = [["gbm", "ml"], ["nn", "ai"]];
const MDL = {trades: [], at: 0, busy: false, sym: "",
             arm: (Q.get("arm") === "nn" ? "nn" : "gbm"),
             // Просьба показать одну конкретную сделку: рука и час
             // сигнала из ссылки в таблице. `hz` — книга турнира
             // темпов: сделка часовой книги живёт в своём каталоге, и
             // без метки график молча показал бы книгу 4 ч.
             hour: Q.get("hour") || "",
             hz: (["h1", "h24", "sit", "sit_obs"].includes(Q.get("hz"))
                  ? Q.get("hz") : ""),
             // Порог обещанного отношения из ссылки: он выбирает
             // ЗАПИСЬ, из которой сервер отдаёт сделки. `null` —
             // «не задан», и тогда график берёт книгу как она
             // торгует, а если сделки там нет — переспрашивает
             // наблюдательную запись (ниже).
             rr: (Q.get("rr") == null || Q.get("rr") === ""
                  ? null : parseFloat(Q.get("rr"))),
             obs: false,
             fit: false};
// Сделка, ради которой страницу открыли. Ищется по руке и часу: пара
// (рука, час, монета) единственна по построению — цикл выбирает шесть
// имён на час, повторов в часе нет.
function focused() {
  if (!MDL.hour) return null;
  return MDL.trades.find(t => t.arm === MDL.arm && t.hour === MDL.hour)
    || null;
}
function modelTrades() {
  return MDL.trades.filter(t => t.arm === MDL.arm);
}
async function pullModelTrades() {
  // Своя монета — свой запрос, поэтому условие на свежесть проверяется
  // ВМЕСТЕ с монетой: иначе смена монеты в течение минуты оставляла бы
  // на графике сделки прежней.
  if (MDL.busy || (MDL.sym === sym && Date.now() - MDL.at < 60000)) return;
  MDL.busy = true;
  try {
    // Полная история по монете, а не последние двадцать из состояния:
    // страницу открывают ради сделки, которой может быть неделя.
    // `lite` — без сводок и кривых: графику нужны строки сделок, а
    // полный расчёт занимал секунды на каждую смену монеты.
    const ask = async rr => {
      const p = new URLSearchParams({k: KEY, sym: sym, per: 500,
                                     lite: 1});
      if (MDL.hz) p.set("hz", MDL.hz);
      if (rr != null) p.set("rr_min", String(rr));
      const r = await fetch("/model_trades?" + p.toString());
      return await r.json();
    };
    let d = await ask(MDL.rr);
    let rows = (d.rows || []).filter(t => t.sym === sym);
    // Сделки в торгуемой книге нет, а нас звали смотреть именно её:
    // переспрашиваем наблюдательную запись. Так открывается сделка с
    // отношением ниже гейта — её в торгуемой книге не существует
    // вовсе, и «у руки нет сделки в этом часе» было бы ответом про
    // другую книгу. Один повтор, и только когда сделку искали по часу.
    MDL.obs = d.source_book === "observation";
    if (MDL.hour && d.source_book === "traded"
        && !rows.some(t => t.arm === MDL.arm && t.hour === MDL.hour)) {
      const d2 = await ask(0);
      const r2 = (d2.rows || []).filter(t => t.sym === sym);
      if (r2.some(t => t.arm === MDL.arm && t.hour === MDL.hour)) {
        d = d2; rows = r2; MDL.obs = true;
      }
    }
    MDL.trades = rows;
    // Правила книги — из ОТВЕТА, не из констант страницы: объяснение
    // сделки обязано описывать тот прогон, который её открыл.
    MDL.rules = {stop_tau: d.stop_tau, min_edge_bp: d.min_edge_bp,
                 min_rr: d.min_rr, min_disc_bp: d.min_disc_bp,
                 rules_version: d.rules_version};
    MDL.sym = sym; MDL.at = Date.now();
    armButtons();
    // Окно графика под сделку — только когда она нашлась.
    if (focused() && !MDL.fit) { MDL.fit = true; fitFocus(); }
  } catch (e) { /* тихо: следующий круг попробует снова */ }
  finally { MDL.busy = false; }
}

function armButtons() {
  const box = document.getElementById("marm");
  const n = {};
  for (const [a] of ARMS) n[a] = MDL.trades.filter(t => t.arm === a).length;
  // Кнопки создаются ОДИН раз, дальше обновляются на месте. Пересборка
  // innerHTML при каждом приходе данных съедала касание, попавшее на
  // момент замены узла, — владелец видел это как «иногда не
  // переключается». Обработчик висит на контейнере и переживает всё.
  if (!box.dataset.wired) {
    box.innerHTML = ARMS.map(([a, name]) =>
      `<button data-arm="${a}" title="model trades: one arm shown">${
        name} <span class="mono"></span></button>`).join(" ");
    box.dataset.wired = "1";
    box.onclick = e => {
      const b = e.target && e.target.closest
        ? e.target.closest("[data-arm]") : null;
      if (!b) return;
      MDL.arm = b.dataset.arm;
      // Рука остаётся в адресе: страницу перезагружают и кладут в
      // закладки, и молча вернуться к другой руке значит показать не
      // те сделки под тем же адресом.
      const q = new URLSearchParams(location.search);
      q.set("arm", MDL.arm);
      window.history.replaceState(null, "", "?" + q.toString());
      // Час остаётся в ссылке, но у другой руки в этом часе сделка
      // своя (или её нет вовсе) — окно не двигаем, чтобы переключение
      // не уводило взгляд.
      armButtons(); draw();
    };
  }
  box.querySelectorAll("[data-arm]").forEach(b => {
    b.setAttribute("aria-pressed", String(b.dataset.arm === MDL.arm));
    const s = b.querySelector("span");
    if (s) s.textContent = n[b.dataset.arm] ?? 0;
  });
}

// Окно графика по сделке: удержание плюс час с каждого края. Свечи для
// него приходят отдельным запросом — живое окно кончается «сейчас», а
// сделка может быть недельной давности.
function focusEnd() {
  const t = focused();
  return t && t.closes_at ? t.closes_at + 3600 : 0;
}
function fitFocus() {
  const t = focused(), c = cands();
  if (!t || !c.length) return;
  const a = barAt(c, t.opened_at - 1800);
  const b = barAt(c, (t.closes_at || t.opened_at) + 1800);
  if (b <= a) return;
  view = {i0: a, n: Math.max(15, b - a + 1)};
  // Подгонка под сделку возвращает и вертикаль: её задача — показать
  // сделку целиком, а ручной сдвиг цены увёл бы её за край.
  vreset();
  follow = false;
  document.getElementById("live").setAttribute("aria-pressed", "false");
  draw();
}

async function pull() {
  pullModelTrades();
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
      `connection lost (attempts ${ST.fails}), showing last data`;
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
  pullHist();
  pullHistory(d.sym, focusEnd());
  // Смена монеты и перезагрузка страницы стирают пересчёт из памяти —
  // но не с сервера. Просим готовое (`go=0`): запускать трёхминутный
  // прогон при каждом открытии графика было бы издевательством.
  // Счёт мог пойти заново (правка правил) — переспрашиваем,
  // пока не придёт досчитанный, иначе вид застынет молча.
  if (!REC.busy && (!REC.data || REC.data.busy
                    || REC.sym !== sym)) pullRec(false);
  sym = data.sym;
  document.getElementById("ttl").textContent = sym;
  document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
  // Группы строятся не каждым тактом: пересборка DOM с пятью сотнями
  // кнопок раз в секунду — тот самый урок обзора. Такт лишь
  // подсвечивает выбранную монету; полная пересборка — только когда
  // групп ещё нет, а список символов впервые стал известен.
  if (!GRP.list && GRP.shown !== String((data.symbols || []).length)) {
    GRP.shown = String((data.symbols || []).length);
    renderGroups();
  }
  markPick();
  draw(); rows(); mrows(); summary();
}

// --- выбор монеты: сектора и поиск, как на обзоре ---------------------
const GRP = {list: null, q: "", shown: ""};
const GRP_EN = {bitcoin_pow: "Bitcoin & PoW", privacy: "Privacy",
  smart_contract_l1: "L1 platforms", layer2: "L2",
  cosmos_interop: "Cosmos & bridges", polkadot: "Polkadot",
  defi_dex: "DeFi: exchanges", defi_lending: "DeFi: lending",
  defi_derivatives: "DeFi: derivatives", defi_yield: "DeFi: yield",
  liquid_staking: "Staking", oracles: "Oracles",
  storage_compute: "Storage & compute", depin: "DePIN",
  ai_infra: "AI: infrastructure", ai_agents: "AI: agents",
  memes: "Memes", gaming_metaverse: "Gaming & metaverse",
  telegram_games: "Telegram games", nft_creator: "NFT",
  exchange_tokens: "Exchange tokens", fan_tokens: "Fan tokens",
  consumer_apps: "Consumer apps", identity_access: "Identity",
  infrastructure: "Infrastructure", payments_social: "Payments",
  dao_governance: "DAO", rwa: "RWA",
  bitcoin_ecosystem: "Bitcoin ecosystem",
  excluded_special: "Special", other: "Other & new listings"};
async function pullGroups() {
  try {
    const r = await fetch(`/groups?k=${encodeURIComponent(KEY)}`);
    const d = await r.json();
    if (d && Array.isArray(d.groups)) GRP.list = d.groups;
  } catch (e) { /* группы — удобство; без них остаётся список сборщика */ }
  renderGroups();
}
function renderGroups() {
  const box = document.getElementById("groups");
  // Пока групп нет, годится плоский список сборщика: поиск работает и
  // по нему, а пустой выпадающий список выглядит поломкой.
  const list = GRP.list
    || (data ? [{id: "other", symbols: data.symbols || []}] : null);
  if (!list) { box.textContent = "…"; return; }
  const q = GRP.q.toUpperCase();
  box.innerHTML = list.map(g => {
    const ss = q ? g.symbols.filter(s => s.includes(q)) : g.symbols;
    if (!ss.length) return "";
    // Свёрнуто всегда, кроме поиска — стена кнопок и была причиной.
    const open = q ? " open" : "";
    return `<details class="grp"${open}><summary><span>${
        GRP_EN[g.id] || g.id}</span><span>${ss.length}</span></summary>
      <div class="gs">${ss.map(s =>
        `<button data-s="${s}" aria-pressed="${String(s === sym)}">${
          s.replace("USDT","")}</button>`).join("")}</div></details>`;
  }).join("") || `<div class="note">nothing found</div>`;
  box.querySelectorAll("[data-s]").forEach(b =>
    b.onclick = () => pickSym(b.dataset.s));
  // Аккордеон: раскрытие одной группы сворачивает остальные.
  box.querySelectorAll("details.grp").forEach(dd =>
    dd.addEventListener("toggle", () => {
      if (dd.open && !GRP.q)
        box.querySelectorAll("details.grp[open]").forEach(o =>
          { if (o !== dd) o.open = false; });
    }));
}
function pickSym(s) {
  sym = s; view = null; follow = true; wipe(); ST.sym = sym;
  // Просьба показать конкретную сделку относилась к прежней монете.
  // Оставить её значило бы держать окно графика в прошлом на монете,
  // где этой сделки не было вовсе.
  MDL.hour = ""; MDL.fit = false;
  document.getElementById("live").setAttribute("aria-pressed", "true");
  window.history.replaceState(
    null, "", `?k=${encodeURIComponent(KEY)}&sym=${sym}`);
  document.getElementById("pick").open = false;
  pull();
}
function markPick() {
  document.querySelectorAll("#groups [data-s]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.s === sym)));
  const n = (data && data.symbols) ? data.symbols.length : 0;
  document.getElementById("npick").textContent =
    "coins" + (n ? " · " + n : "");
}

// Номер candles, внутри которой лежит момент. Двоичным поиском, потому
// что ряд свечей ДЫРЯВ: минута без сделок отсутствует, а не выходит
// нулевой (урок A2). Прежде метки сделок ставились линейной пропорцией
// «время между краями окна», и при каждой дыре они разъезжались со
// свечами — тем сильнее, чем уже окно. Владелец увидел это как «при
// масштабировании метка входа съезжает».
function barAt(c, t) {
  if (!c.length) return 0;
  if (t <= c[0][0]) return 0;
  if (t >= c[c.length-1][0]) return c.length - 1;
  let lo = 0, hi = c.length - 1;
  while (lo < hi) {
    const m = (lo + hi + 1) >> 1;
    if (c[m][0] <= t) lo = m; else hi = m - 1;
  }
  return lo;
}

function cands() {
  // История с диска снизу, живые candles поверх: у текущей минуты живая
  // версия свежее файловой, и она обязана победить.
  const live = (data && data.sig && data.sig.candles) || [];
  if (!HC.cand.length) return live;
  // Окно под старую сделку кончается в прошлом, и живые свечи в него не
  // входят вовсе. Подмешать их значило бы склеить два далёких куска в
  // один ряд: график молча показал бы «сделку и сегодняшний день»
  // соседними барами, а разрыв в неделю не увидеть никак.
  const use = HC.end ? live.filter(c => c[0] <= HC.end) : live;
  return mergeCandles(HC.cand, use);
}
function trades() {
  // ФАКТ: что действительно случилось.
  // История берётся из отдельного запроса: в состоянии лежат только
  // последние двадцать закрытых, чтобы не гонять сотни каждую секунду.
  const sg = (data && data.sig) || {};
  return (sg.open||[]).concat(
    HIST.trades.length ? HIST.trades : (sg.done||[]));
}
function shownTrades() {
  // Один источник на график, таблицу и сводку. Пробовал рисовать обе
  // геометрии сразу — владелец сказал, что старая на графике не нужна:
  // при включённом пересчёте она только загромождает картинку, а
  // сравнивать «было / стало» удобнее по числам в таблице.
  const d = recReady();
  return d ? (d.trades || []) : trades();
}
// Процент движения цены вместо б.п. — решение владельца. Два знака, при
// мелких величинах три: иначе мелкое нетто схлопывается в «0.00 %».
function pct(v) {
  if (v == null) return "—";
  const d = Math.abs(v) >= 10 ? 2 : 3;
  return (v > 0 ? "+" : "") + (v / 100).toFixed(d) + " %";
}
// Цена выхода у сделки модели своей колонкой не записана: разбор пишет
// ХОД цены за удержание, а это то же самое число с другой стороны.
// Считать его здесь — не вторая копия расчёта, а перевод единицы.
function mdlExit(t) {
  // У сделки, вышедшей живым сторожем, исхода в разборе ещё нет, а
  // цена выхода записана событием — она и есть факт. Считать по ней
  // не «вторая копия расчёта»: разбор считает ДЕНЬГИ, здесь цена.
  if (t.exit_px) return t.exit_px;
  return (t.entry_px && t.got_bp != null)
    ? t.entry_px * (1 + t.got_bp / 10000) : null;
}
function res(m) {
  return m.pnl_bp == null ? `<span style="color:var(--muted)">—</span>`
    : `<span class="${m.pnl_bp>0?"buy":"sell"}">${pct(m.pnl_bp)} · ${
        m.r>0?"+":""}${m.r} R</span>`;
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
    g.fillText("accumulating history — candles appear in a couple of minutes", 12, H/2);
    // Пустой график при открытой сделке обязан объясниться: иначе
    // «записи за это время нет» неотличимо от «страница не работает».
    modelNote([], 0, 0);
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
  const tr = shownTrades();
  let lo = Infinity, hi = -Infinity;
  for (let i=i0;i<i1;i++){ lo=Math.min(lo,c[i][3]); hi=Math.max(hi,c[i][2]); }
  const t0 = c[i0][0], t1 = c[i1-1][0];
  for (const l of lv) if (l.p>lo*0.99 && l.p<hi*1.01){
    lo=Math.min(lo,l.p); hi=Math.max(hi,l.p); }
  for (const m of tr) if (m.t>=t0-3600 && m.t<=t1+3600){
    // У отвергнутого входа стопа и цели нет вовсе — их и не построили.
    const vs = [m.entry, m.stop, m.target].filter(v => v != null);
    lo=Math.min(lo, ...vs); hi=Math.max(hi, ...vs); }
  // Цены сделок модели входят в масштаб наравне со свечами: иначе
  // сделка, чей вход ушёл за край окна, молча не рисуется — и это
  // неотличимо от «сделки не было».
  const MT = modelTrades();
  for (const t of MT) {
    if (!t.entry_px || t.opened_at > t1+3600
        || (t.closes_at || t.opened_at) < t0-3600) continue;
    const vs = [t.entry_px, mdlExit(t)].filter(v => v != null);
    lo=Math.min(lo, ...vs); hi=Math.max(hi, ...vs);
  }
  const pad=(hi-lo)*0.06||1e-9; lo-=pad; hi+=pad;
  // Ручная вертикаль поверх автоматической: сдвиг и растяжение
  // считаются от середины автоматического диапазона, поэтому окно не
  // прыгает, когда сам диапазон меняется от прокрутки во времени.
  if (vpan || vzoom !== 1) {
    const mid=(lo+hi)/2, half=(hi-lo)/2*vzoom, off=(hi-lo)*vpan;
    lo = mid - half + off; hi = mid + half + off;
  }
  const y = v => padT + ph*(hi-v)/(hi-lo);
  const x = i => padL + pw*(i-i0+0.5)/(i1-i0);
  // Момент кладётся на СВОЮ свечу, а не на долю окна: доля врёт на
  // каждой дыре в ряду. Внутри candles ещё доля минуты — чтобы метка
  // стояла там, где случилась, а не прыгала на границу бара.
  const xt = t => {
    const i = barAt(c, t);
    const frac = Math.max(0, Math.min(1, (t - c[i][0]) / 60));
    return x(i) + (frac - 0.5) * pw / (i1 - i0);
  };
  const dec = Math.max(2, Math.ceil(-Math.log10((hi-lo)/50)));

  g.strokeStyle = css("--grid"); g.lineWidth = 1;
  g.fillStyle = css("--muted"); g.font = "11px ui-monospace, Menlo, monospace";
  g.textBaseline = "middle";
  for (let k=0;k<=4;k++){
    const v = hi-(hi-lo)*k/4;
    g.beginPath(); g.moveTo(padL,y(v)); g.lineTo(W-padR,y(v)); g.stroke();
    g.fillText(v.toFixed(dec), W-padR+5, y(v));
  }
  // Ось времени: линии по круглым меткам, шаг подобран по ширине окна.
  // Метки ищутся по времени свечи, а не по номеру — ряд дыряв (урок
  // A2), и каждый десятый бар не значит каждые десять минут.
  const stepM = [5,15,30,60,120,240,480,1440].find(s =>
    pw / Math.max(1, (i1 - i0) / s) >= 76) || 1440;
  let tdrawn = 0;
  g.textAlign = "center";
  for (let i = i0; i < i1; i++) {
    if (c[i][0] % (stepM * 60)) continue;
    g.strokeStyle = css("--grid");
    g.beginPath(); g.moveTo(x(i), padT); g.lineTo(x(i), padT + ph);
    g.stroke();
    g.fillStyle = css("--muted");
    g.fillText(stamp(c[i][0]), x(i), H - 10);
    tdrawn++;
  }
  g.textAlign = "left";
  if (!tdrawn) {
    g.fillStyle = css("--muted");
    g.fillText(stamp(t0), padL, H - 10);
    g.textAlign = "right"; g.fillText(stamp(t1), W - padR, H - 10);
    g.textAlign = "left";
  }
  for (const l of lv) {
    if (l.p<lo||l.p>hi) continue;
    g.save(); g.strokeStyle=css("--accent"); g.globalAlpha=.55;
    g.setLineDash(l.kind==="полка"?[]:[3,3]);
    g.beginPath(); g.moveTo(padL,y(l.p)); g.lineTo(W-padR,y(l.p)); g.stroke();
    g.restore();
    g.fillStyle=css("--muted"); g.fillText(disp(l.kind), padL+4, y(l.p)-7);
  }
  const cw = Math.max(1, pw/(i1-i0)*0.62);
  // Объём — гистограммой у нижнего края, полупрозрачно: отдельная
  // панель отняла бы высоту у цены, а тень объёма читается так же.
  let vmax = 0;
  for (let i = i0; i < i1; i++) vmax = Math.max(vmax, c[i][5] || 0);
  if (vmax > 0) {
    const vh = ph * 0.16, vy = padT + ph;
    for (let i = i0; i < i1; i++) {
      g.fillStyle = c[i][4] >= c[i][1]
        ? "rgba(61,220,127,.26)" : "rgba(255,100,115,.26)";
      const hv = vh * (c[i][5] || 0) / vmax;
      g.fillRect(x(i) - cw / 2, vy - hv, cw, hv);
    }
  }
  for (let i=i0;i<i1;i++){
    const up = c[i][4] >= c[i][1];
    g.strokeStyle = g.fillStyle = up ? css("--bid") : css("--ask");
    g.beginPath(); g.moveTo(x(i),y(c[i][2])); g.lineTo(x(i),y(c[i][3]));
    g.stroke();
    const yo=y(c[i][1]), yc=y(c[i][4]);
    g.fillRect(x(i)-cw/2, Math.min(yo,yc), cw, Math.max(Math.abs(yc-yo),1));
  }
  HIT = [];
  const clamp = v => Math.max(padL, Math.min(W-padR, v));
  for (const m of tr) {
    if (m.t < t0-60 || m.t > t1+60) continue;
    // Отрезки стопа и цели обрываются там, где сделка закончилась.
    // Иначе они тянутся до правого края и у нескольких сделок подряд
    // накладываются друг на друга — на графике каша, и непонятно,
    // какая линия чьей сделке принадлежит. У открытой trades конца
    // ещё нет, и она честно тянется до края.
    const end = m.closed_at || (m.held ? m.t + m.held : null);
    const xa = clamp(xt(m.t));
    const xb = end ? clamp(xt(end)) : W-padR;
    const seg=(v,col,dash)=>{ if(v==null||v<lo||v>hi) return;
      g.save(); g.strokeStyle=col; g.setLineDash(dash); g.lineWidth=1.2;
      g.beginPath(); g.moveTo(xa,y(v)); g.lineTo(Math.max(xb, xa+2),y(v));
      g.stroke(); g.restore(); };
    seg(m.stop, css("--ask"), [3,3]);
    seg(m.target, css("--bid"), [3,3]);
    const yy=y(m.entry), d = m.long?1:-1;
    g.beginPath(); g.moveTo(xa,yy); g.lineTo(xa-6,yy+11*d);
    g.lineTo(xa+6,yy+11*d); g.closePath();
    if (m.state === "не открыта") {
      // Полый треугольник: вход был, trades нет. Молча пропустив
      // такой вход, страница выдаёт отказ правила за пропажу данных.
      g.save(); g.strokeStyle = css("--muted"); g.lineWidth = 1.4;
      g.setLineDash([2,2]); g.stroke(); g.restore();
    } else {
      g.fillStyle = css("--ink"); g.fill();
    }
    // Выход — квадратом на цене выхода: без него видно, где вошли, и
    // не видно, чем кончилось.
    if (end && m.exit != null && m.exit >= lo && m.exit <= hi) {
      g.fillStyle = m.state === "цель" ? css("--bid")
                  : m.state === "стоп" ? css("--ask") : css("--muted");
      g.fillRect(xb-3, y(m.exit)-3, 6, 6);
      g.save(); g.strokeStyle = css("--muted"); g.globalAlpha = .5;
      g.setLineDash([2,3]); g.beginPath();
      g.moveTo(xb, y(m.entry)); g.lineTo(xb, y(m.exit)); g.stroke();
      g.restore();
    }
    const ya=y(Math.max(m.stop,m.target)), yb=y(Math.min(m.stop,m.target));
    const h2=Math.max(yb-ya,20);
    HIT.push({m, x0:xa-10, x1:xb, y0:(ya+yb)/2-h2/2, y1:(ya+yb)/2+h2/2});
  }
  // Слой сделок модели: вход — треугольник НА ЦЕНЕ входа, удержание —
  // линия до срока закрытия, выход — квадрат на цене выхода. Прежде
  // вход рисовался значком у нижнего края: видно было, что сделка
  // была, и не видно, по какой цене и чем кончилась, — то есть на
  // главный вопрос «а что там было с ценой» график не отвечал.
  //
  // Показывается ОДНА рука (переключатель ml/ai): у двух моделей сделки
  // идут в те же часы по тем же монетам и ложатся друг на друга.
  const foc = focused();
  for (const t of MT) {
    if (!t.opened_at || !t.entry_px) continue;
    // У ОТКРЫТОЙ сделки конца ещё нет: у ситуационной книги срока не
    // существует вовсе, у часовых он в будущем. Спан обязан тянуться
    // до правого края — иначе `xb` совпадает с `xa`, зоны и обещания
    // отсекаются проверкой ширины, и от живой позиции остаётся одна
    // точка входа (владелец увидел ровно это). Так же ведёт себя слой
    // бумажных сделок: у открытой конца нет, и она идёт до края.
    const live = t.state !== "закрыта";
    // Живой выход, ещё не разобранный циклом, — уже конец сделки:
    // спан обязан кончиться на нём, иначе зона тянется до края у
    // позиции, которой нет.
    const end = t.closes_at || t.exit_ts
      || (live ? t1 + 60 : t.opened_at);
    if (end < t0 - 3600 || t.opened_at > t1 + 3600) continue;
    const xa = clamp(xt(t.opened_at));
    const xb = clamp(xt(Math.min(end, t1 + 60)));
    const ye = y(t.entry_px), ex = mdlExit(t);
    const up = t.side === "long";
    const col = t.state === "закрыта"
      ? ((t.net_bp || 0) > 0 ? css("--bid") : css("--ask"))
      : css("--accent");
    const me = foc && foc.hour === t.hour;
    // Обещания пути — уровни СВОЕЙ сделки, как TP/SL у v1: `mae` —
    // ход против позиции, `mfe` — в пользу, оба от цены входа.
    const pAdv = t.mae_bp == null ? null
      : t.entry_px * (1 + t.mae_bp / 1e4);
    const pFav = t.mfe_bp == null ? null
      : t.entry_px * (1 + t.mfe_bp / 1e4);
    // Линия, куда модель ЖДЁТ цену. Раньше на ней стоял стоп; теперь
    // стоп за ней, и обе линии обязаны быть видны — иначе по графику
    // не сказать, какое из двух правил вело сделку.
    const pExp = t.mae_m_bp == null ? null
      : t.entry_px * (1 + t.mae_m_bp / 1e4);
    // Границы зон — диапазон свечей за время удержания плюс уровни
    // сделки: v1 заливал прибыльную и убыточную сторону входа на весь
    // спан, и по цвету над/под линией видно, где сделка проводила
    // время.
    let rl = t.entry_px, rh = t.entry_px;
    for (const b of c) {
      if (b[0] < t.opened_at - 60 || b[0] > end + 60) continue;
      if (b[3] < rl) rl = b[3];
      if (b[2] > rh) rh = b[2];
    }
    for (const v of [pAdv, pFav, ex]) {
      if (v != null) { rl = Math.min(rl, v); rh = Math.max(rh, v); }
    }
    rl = Math.max(rl, lo); rh = Math.min(rh, hi);
    const yTop = y(rh), yBot = y(rl);
    const base = (foc && !me) ? 0.35 : 1;
    g.save();
    // Зоны v1: у лонга прибыль НАД входом (зелёная), убыток под
    // (красная); у шорта зеркально.
    if (xb > xa + 1 && yBot > yTop) {
      const zone = (y0, y1, colr) => {
        if (y1 - y0 < 1) return;
        g.fillStyle = colr; g.globalAlpha = base * (me ? 0.16 : 0.09);
        g.fillRect(xa, y0, xb - xa, y1 - y0);
      };
      if (up) {
        zone(yTop, ye, css("--bid"));
        zone(ye, yBot, css("--ask"));
      } else {
        zone(yTop, ye, css("--ask"));
        zone(ye, yBot, css("--bid"));
      }
    }
    g.globalAlpha = base;
    // Линии обещаний через весь спан — пунктиром, подписи только у
    // сделки в фокусе: на графике с десятком сделок подписи каждой
    // слились бы в шум.
    const promise = (pv, colr, lab) => {
      if (pv == null || xb <= xa + 1) return;
      if (pv < lo || pv > hi) {
        // Уровень за краем окна цены: нарисовать нельзя, промолчать —
        // значит показать сделку без цели. У сделки в фокусе ставится
        // метка у края со стрелкой и ценой; та же честность, что у
        // «сделка вне окна свечей».
        if (!me) return;
        g.fillStyle = colr;
        g.fillText(`${lab} ${pv.toFixed(dec)} ${
          pv > hi ? "↑" : "↓"} off scale`,
          // Нижняя метка ставится НАД полосой объёма (она занимает
          // 16 % высоты), иначе тонет в гистограмме.
          xa + 4, pv > hi ? padT + 8 : padT + ph * 0.8);
        return;
      }
      g.strokeStyle = colr; g.lineWidth = me ? 1.6 : 1.1;
      g.setLineDash([5, 4]);
      g.beginPath(); g.moveTo(xa, y(pv)); g.lineTo(xb, y(pv));
      g.stroke(); g.setLineDash([]);
      if (me) {
        g.fillStyle = colr;
        g.fillText(`${lab} ${pv.toFixed(dec)}`, xa + 4, y(pv) - 4);
      }
    };
    promise(pFav, css("--bid"), up ? "promise ↑" : "promise ↓");
    promise(pAdv, css("--ask"), "stop");
    promise(pExp, css("--muted"), "expected move against");
    // Линия входа через спан удержания — сплошная, как у v1.
    g.strokeStyle = col; g.fillStyle = col;
    g.lineWidth = me ? 2 : 1.2;
    g.beginPath(); g.moveTo(xa, ye); g.lineTo(Math.max(xb, xa+2), ye);
    g.stroke();
    // Кружки событий v1: белая точка с цветным кольцом. Вход —
    // пурпурное кольцо (акцент), выход — по знаку результата.
    const dot = (x0, y0, ring) => {
      g.beginPath(); g.arc(x0, y0, me ? 4 : 3.2, 0, 7);
      g.fillStyle = "#ffffff"; g.fill();
      g.lineWidth = me ? 2.6 : 2; g.strokeStyle = ring; g.stroke();
    };
    dot(xa, ye, css("--accent"));
    let drew = null;
    if (ex != null && ex >= lo && ex <= hi) {
      g.save(); g.globalAlpha = base * .6; g.strokeStyle = col;
      g.setLineDash([2,3]);
      g.beginPath(); g.moveTo(xb, ye); g.lineTo(xb, y(ex)); g.stroke();
      g.restore();
      dot(xb, y(ex), col);
      drew = ex;
    }
    g.restore();
    const yl = Math.min(ye, ex == null ? ye : y(ex));
    const yh = Math.max(ye, ex == null ? ye : y(ex));
    // `exit` проставляется ТОЛЬКО ветвью, которая его нарисовала:
    // иначе проверка «выход виден» смотрела бы на исходные данные, а не
    // на картинку, и прошла бы на графике без единого выхода.
    HIT.push({mdl: t, exit: drew, x0: xa-7, x1: Math.max(xb, xa+7),
              y0: yl-12, y1: yh+12});
  }
  // Линия последней цены с биркой у правой оси: без неё край живого
  // ряда приходится искать глазами.
  const lastC = c[c.length - 1], lastP = lastC[4];
  if (lastP >= lo && lastP <= hi) {
    const lcol = lastC[4] >= lastC[1] ? css("--bid") : css("--ask");
    g.save(); g.strokeStyle = lcol; g.globalAlpha = .75;
    g.setLineDash([2, 3]); g.beginPath();
    g.moveTo(padL, y(lastP)); g.lineTo(W - padR, y(lastP)); g.stroke();
    g.restore();
    g.fillStyle = lcol;
    g.fillRect(W - padR + 2, y(lastP) - 8, padR - 4, 16);
    g.fillStyle = "#0b0820";
    g.fillText(lastP.toFixed(dec), W - padR + 5, y(lastP));
  }
  // Легенда OHLC: по свече под перекрестием, без него — по последней
  // видимой. Подпись живёт на самом графике, как у любого kline-вида.
  const li = CROSS ? Math.max(i0, Math.min(i1 - 1,
    i0 + Math.floor((CROSS.mx - padL) / pw * (i1 - i0)))) : i1 - 1;
  const lb = c[li], chg = lb[1] ? (lb[4] / lb[1] - 1) * 100 : 0;
  const bcol = lb[4] >= lb[1] ? css("--bid") : css("--ask");
  let lx = padL + 4;
  const put = (k2, v2, col2) => {
    // На узком экране легенда обрывается, а не наезжает на ось цены.
    if (lx > W - padR - 64) return;
    g.fillStyle = css("--muted"); g.fillText(k2, lx, padT + 6);
    lx += (g.measureText(k2) || {width: 12}).width + 4;
    g.fillStyle = col2 || css("--ink"); g.fillText(v2, lx, padT + 6);
    lx += (g.measureText(v2) || {width: 40}).width + 10;
  };
  put("O", lb[1].toFixed(dec)); put("H", lb[2].toFixed(dec));
  put("L", lb[3].toFixed(dec)); put("C", lb[4].toFixed(dec), bcol);
  put("Δ", (chg > 0 ? "+" : "") + chg.toFixed(2) + " %", bcol);
  // Перекрестие: бар под курсором, цена справа, время внизу. Рисуется
  // поверх всего и только при наведении — на телефоне его нет.
  if (CROSS && !drag) {
    const ci = Math.max(i0, Math.min(i1 - 1,
      i0 + Math.floor((CROSS.mx - padL) / pw * (i1 - i0))));
    const cx = x(ci);
    g.save(); g.strokeStyle = css("--muted"); g.globalAlpha = .5;
    g.setLineDash([3, 3]);
    g.beginPath(); g.moveTo(cx, padT); g.lineTo(cx, padT + ph); g.stroke();
    if (CROSS.my >= padT && CROSS.my <= padT + ph) {
      g.beginPath(); g.moveTo(padL, CROSS.my);
      g.lineTo(W - padR, CROSS.my); g.stroke();
    }
    g.restore();
    if (CROSS.my >= padT && CROSS.my <= padT + ph) {
      const pv = hi - (hi - lo) * (CROSS.my - padT) / ph;
      g.fillStyle = css("--chip");
      g.fillRect(W - padR + 2, CROSS.my - 8, padR - 4, 16);
      g.strokeStyle = css("--rule");
      g.strokeRect(W - padR + 2, CROSS.my - 8, padR - 4, 16);
      g.fillStyle = css("--ink");
      g.fillText(pv.toFixed(dec), W - padR + 5, CROSS.my);
    }
    const tt = stamp(c[ci][0]);
    const tw = (g.measureText(tt) || {width: 40}).width + 10;
    g.fillStyle = css("--chip");
    g.fillRect(cx - tw / 2, padT + ph + 2, tw, 16);
    g.strokeStyle = css("--rule");
    g.strokeRect(cx - tw / 2, padT + ph + 2, tw, 16);
    g.fillStyle = css("--ink"); g.textAlign = "center";
    g.fillText(tt, cx, padT + ph + 10); g.textAlign = "left";
  }
  document.getElementById("cap2").textContent =
    `${i1-i0} of ${c.length} min · ${stamp(t0)}—${stamp(t1)}`;
  // Сколько сделок вообще попадает на график. Свечи живут в
  // посекундном буфере (несколько часов), а история сделок поднимается
  // с диска за трое суток — значит часть сделок старше самой старой
  // candles и нарисована быть не может. Молчать об этом нельзя: в
  // таблице их видно, на графике нет, и это читается как пропажа.
  const first = c[0][0], last = c[c.length-1][0];
  const S = shown();
  const off = tr.filter(m => m.t < first || m.t > last).length;
  const old = tr.filter(m => (m.ver || 1) !== S.ver).length;
  document.getElementById("cap3").textContent =
    (HIST.off ? "detector off" : `${tr.length} trades`)
    + (!HIST.off && S.rec ? " · replayed, not actual" : "")
    + (S.rec && recReady() && recReady().no_outcome
       ? ` · ${tr.filter(m => m.state === "не открыта").length} entries `
         + `refused by the rule (hollow triangle)` : "")
    + (off ? ` · ${off} outside the chart window` : "")
    + (old ? ` · ${old} under older rules` : "")
    + (MT.length
       ? ` · ${MT.length} model trades`
         + ` (${MDL.arm === "nn" ? "ai" : "ml"}${
             MDL.hz ? ", " + MDL.hz.slice(1) + " h book" : ""})` : "");
  modelNote(MT, first, last);
}

// Что со сделкой, ради которой открыли страницу. Молчание здесь —
// худший из отказов: график показывает какое-то окно, сделки на нём
// нет, и по виду это неотличимо от «сделка была неудачной и незаметной».
function modelNote(MT, first, last) {
  const box = document.getElementById("mleg");
  if (!MDL.hour) {
    box.innerHTML = MT.length
      ? `<span><span class="sw" style="border-color:var(--accent)"></span>
         model trade: entry &#9650;, hold — line, exit
         &#9632;</span>` : "";
    return;
  }
  if (!MDL.sym) { box.innerHTML = "<span>fetching model trades…</span>"; return; }
  const t = focused();
  if (!t) {
    // Час есть, сделки нет: у другой руки в этом часе своей сделки не
    // было. Это ответ, а не пустота, и сказать его надо словами —
    // вместе с тем, где уже искали: без этого совет «переключите
    // руку» звучит как единственная причина, а их две.
    box.innerHTML = `<span style="color:var(--ask)">arm ${
      MDL.arm === "nn" ? "ai" : "ml"} has no trade in hour ${MDL.hour}
      — switch the arm${MDL.hz === "sit"
        ? " (the observation record was checked too)" : ""}</span>`;
    return;
  }
  // Пока свечи за это окно не пришли, говорить «записи нет» нельзя:
  // ожидание и отсутствие выглядели бы одинаково.
  if (HC.busy || HC.end !== Math.round(focusEnd())) {
    box.innerHTML = "<span>fetching candles for this window…</span>"; return;
  }
  const seen = t.opened_at >= first && t.opened_at <= last;
  box.innerHTML = seen
    // Откуда сделка — обязано стоять рядом с ней: наблюдательная
    // запись ведётся теми же правилами входа, но без требования к
    // отношению и своим счётом, и молча выдать её за сделку книги
    // значило бы показать деньги, которых книга не делала.
    ? `<span>showing trade ${MDL.hour} · ${
        t.side} · ${disp(t.state)}${MDL.obs
        ? ` · <span style="color:var(--muted)">from the observation
            record (reward/risk requirement dropped; the bot does not
            trade it)</span>` : ""}</span>`
    : `<span style="color:var(--ask)">no price record for ${MDL.hour} —
       recording of this coin started later</span>`;
}

function rows() {
  const tr = shownTrades(), c = cands();
  const first = c.length ? c[0][0] : 0, last = c.length ? c[c.length-1][0] : 0;
  const off = m => c.length && (m.t < first || m.t > last);
  document.getElementById("rows").innerHTML = tr.length ? tr.map(m => `
    <tr ${off(m) ? 'style="opacity:.55" title="outside the chart window — '
                 + 'candles for that time are no longer stored"' : ""}>
    <td class="mono">${stamp(m.t)}${off(m) ? " ·" : ""}</td>
    <td class="${m.long?"buy":"sell"}">${m.long?"long":"short"}</td>
    <td class="mono">${m.entry}</td><td class="mono">${m.stop ?? "—"}</td>
    <td class="mono">${m.target ?? "—"}</td>
    <td>${disp(m.rule || "лента")}</td>
    <td style="color:var(--muted)">${disp(m.kind)}</td>
    <td class="mono">${m.rr == null ? "—" : "1:" + m.rr}</td>
    <td title="${m.why || ""}">${disp(m.state)}</td>
    <td class="mono">${m.held == null ? "—" : m.held + " s"}</td>
    <td class="mono">${res(m)}</td></tr>`
  ).join("") : `<tr><td colspan="11" style="color:var(--muted)">
    no events yet — detector waits for conditions</td></tr>`;
  // Выключённый детектор не показывает пустую таблицу: страницу
  // открывают ради сделки МОДЕЛИ, а пустая таблица чужого механизма
  // рядом читается как «сделки не записываются» — владелец так её и
  // прочёл. Панель прячется, причина уезжает строкой под сделки
  // модели, где её видно и где она никого не сбивает.
  const pp = document.getElementById("ppanel");
  if (pp && pp.style) pp.style.display = HIST.off ? "none" : "";
}

// Объяснение сделки СЛОВАМИ ИЗ ЧИСЕЛ записи — просьба владельца:
// каким обучением открыта, почему модель выбрала имя, по какой
// стратегии вошла и как расставила уровни. Прозы в записи нет
// намеренно: числа — источник истины, предложение из них собирает
// страница, и врать оно может только вместе с числами.
const FAM_EN = {absorption: "book eaten (absorption)",
                book: "book imbalance / depth",
                tape: "tape pressure", liq: "liquidations",
                oi: "open interest", funding: "funding & basis",
                move: "price move / reversal", squeeze: "squeeze",
                tilt: "tilt", range: "range / dwell",
                vol: "volatility regime", leader: "leader & sector",
                clock: "time of day", round: "round levels",
                beta: "market beta", age: "listing age",
                other: "other"};
function setupText(t) {
  if (!t || !t.setup || !t.setup.length) return "";
  return t.setup.map(x => `${FAM_EN[x[0]] || x[0]} ${
    Math.round(x[1] * 100)} %`).join(", ");
}
function whyDrivers(t) {
  if (!t || !t.why || !t.why.length) return "";
  return t.why.map(w => `${w[0]} ${w[1] > 0 ? "+" : ""}${
    (w[1] / 100).toFixed(2)} %`).join(", ");
}
function explainTrade(t) {
  if (!t) return "";
  const r = MDL.rules || {};
  const bits = [];
  bits.push(t.train_seq != null
    ? `opened by <b>training #${t.train_seq}</b> of the ${
        MDL.arm === "nn" ? "neural" : "tree"} arm`
    : "training number not recorded (trade predates the field)");
  if (t.expected_bp != null)
    bits.push(`the model expected <b>${pct(t.expected_bp)}</b>`);
  const st = setupText(t);
  if (st)
    bits.push(`situation read from the features: <b>${st}</b>
      <span class="dim">(the dominant feature families of this
      forecast — a reading of the contributions, not a hand-picked
      strategy)</span>`);
  const drv = whyDrivers(t);
  bits.push(drv ? `main drivers of the forecast: <b>${drv}</b>`
                : "per-feature breakdown not recorded for this trade");
  if (t.rank != null && t.of)
    bits.push(`strategy: hourly rebalance — this name ranked
      <b>#${t.rank} of ${t.of}</b> in the cross-section by expected
      move`);
  if (t.fwd0_bp != null && t.expected_bp != null) {
    const disc = Math.abs(t.expected_bp) - Math.abs(t.fwd0_bp);
    bits.push(`strategy: situational scanner${r.rules_version
      ? " (rules v" + r.rules_version + ")" : ""} — the sheet promised
      ${pct(t.fwd0_bp)}, price gave back <b>${pct(disc)}</b> more, so
      the remaining move crossed the ${r.min_edge_bp ?? 22} bp gate in
      front of us with reward/risk ≥ ${r.min_rr ?? 2} against the
      executable stop`);
  }
  if (t.mae_bp != null) {
    const q = String(t.stop_of || "").indexOf("q_") > 0;
    bits.push(`levels: stop at ${pct(t.mae_bp)}${q
      ? ` — the learned level price passes in ${
          Math.round((r.stop_tau ?? 0.2) * 100)} % of cases` +
        (t.mae_m_bp != null
          ? `, the forecast line itself was ${pct(t.mae_m_bp)}` : "")
      : " (the forecast line: older stop rule)"}${t.mfe_bp != null
      ? `; target at the expected favourable extreme ${pct(t.mfe_bp)}`
      : ""}`);
  }
  return bits.join(" · ");
}

// Сделки МОДЕЛИ по этой паре — то, ради чего график и открывают.
// Отдельной таблицей, а не вместе с бумажными: два механизма в одной
// таблице однажды сложили бы свою статистику (правило проекта).
function mrows() {
  const list = modelTrades().slice()
    .sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0));
  const bookName = MDL.hz === "sit" ? "situational"
    : MDL.hz ? MDL.hz.replace("h", "") + " h book" : "4 h book";
  document.getElementById("cap4").textContent =
    `${list.length} on ${sym.replace("USDT", "")} · ${
      MDL.arm === "nn" ? "ai (neural)" : "ml (trees)"} · ${bookName}`;
  document.getElementById("mrows").innerHTML = list.length
    ? list.map(t => {
        const ex = mdlExit(t);
        const cls = t.net_bp == null ? ""
          : (t.net_bp > 0 ? "buy" : "sell");
        // Открытая сделка несёт нереализованное — иначе колонка «net»
        // у неё пуста, и живая позиция выглядит как потерянная.
        const net = t.net_bp != null ? pct(t.net_bp)
          : t.unreal_net_bp != null
            ? `<span style="color:var(--muted)">${
                pct(t.unreal_net_bp)} live</span>` : "—";
        const here = t.hour === MDL.hour;
        const tip = [t.train_seq != null ? "training #"
                       + t.train_seq : null,
                     setupText(t) || null,
                     whyDrivers(t) || null].filter(Boolean).join(" · ");
        const ip = new URLSearchParams({k: KEY, sym: t.sym,
                                        arm: t.arm || "gbm",
                                        hour: t.hour, side: t.side});
        if (MDL.hz) ip.set("hz", MDL.hz);
        if (MDL.rr != null) ip.set("rr", String(MDL.rr));
        const info = `<a href="/trade-info?${ip.toString()}"
          title="plain-words breakdown"
          style="text-decoration:none"
          onclick="event.stopPropagation()">&#9432;</a>`;
        return `<tr data-h="${t.hour}" style="cursor:pointer${
          here ? ";background:rgba(127,127,255,.10)" : ""}"
          title="${tip ? tip + " — " : ""}click to centre the chart">
        <td class="mono">${stamp(t.opened_at)}</td>
        <td class="${t.side === "long" ? "buy" : "sell"}">${t.side}</td>
        <td class="mono">${t.entry_px == null ? "—" : t.entry_px}</td>
        <td class="mono">${ex == null ? "—" : +ex.toPrecision(10)}</td>
        <td class="mono" style="color:var(--muted)">${
          pct(t.expected_bp)}</td>
        <td class="mono">${pct(t.got_bp)}</td>
        <td class="mono ${cls}">${net}</td>
        <td class="mono ${cls}">${t.pnl == null ? "—"
          : (t.pnl > 0 ? "+" : "") + t.pnl.toFixed(2)}</td>
        <td style="color:var(--muted)">${disp(t.state)}${
          t.exit_reason ? " · " + disp(t.exit_reason) : ""} ${
          info}</td></tr>`;
      }).join("")
    : `<tr><td colspan="9" style="color:var(--muted)">no model trades on
       this pair in the shown book — try the other arm or another
       book</td></tr>`;
  const note = document.getElementById("mnote");
  if (note) {
    const f = focused();
    note.innerHTML = (f
      ? `<div class="mline">why this trade: ${explainTrade(f)}</div>`
      : "") + (HIST.off
      ? `The hand-rolled tape detector is off, so its own paper-trade
         table is hidden: its direction was closed by measurements
         T1&ndash;T4 and absorption now enters the model as features
         (eat_bid/eat_ask, big_rel, imbalances). Book and tape are
         still recorded; run the collector with
         <span class="mono">--paper</span> to watch it again.`
      : "");
  }
}

function verLine(list, cur) {
  // По версиям правил рядом: смешивать их нельзя, но и прятать прежние
  // незачем — выборка текущей всегда мала, и без соседних строк
  // непонятно, стало лучше или просто сделок мало.
  if (!list || !list.length) return "";
  const pc = v => (v*100).toFixed(0) + " %";
  return list.map(x => {
    const s = x.stats, me = x.ver === cur;
    const head = (me ? "<b>rules v" + x.ver + " (current)</b>"
                     : "rules v" + x.ver);
    return head + ": " + (s
      ? `${s.trades} trades, wins ${pc(s.win_rate)} vs break-even `
        + `${pc(s.break_even)}, expectancy ${pct(s.expectancy_bp)}, `
        + `stop ${pct(s.stop_bp_median)}`
      : `${x.n} trades, none closed`);
  }).join("<br>");
}


function summary() {
  const S = shown(), s = S.stats, box = document.getElementById("sum");
  const pc = v => (v*100).toFixed(0) + " %";
  if (!s) {
    box.innerHTML = `<div class="note">no closed trades yet</div>`;
  } else {
    const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
      <div class="v mono ${cls||""}">${v}</div></div>`;
    // Доля побед сравнивается с безубыточной, а не с половиной: при
    // отношении 1:3 выигрывать нужно каждую четвёртую, и «мало побед»
    // само по себе ничего не значит.
    box.innerHTML =
      cell("trades", s.trades) +
      cell("wins", pc(s.win_rate),
           s.win_rate >= s.break_even ? "buy" : "sell") +
      cell("break-even", pc(s.break_even)) +
      cell("expectancy", pct(s.expectancy_bp),
           s.expectancy_bp > 0 ? "buy" : "sell") +
      cell("in R", (s.expectancy_r>0?"+":"") + s.expectancy_r.toFixed(2)
           + " R", s.expectancy_r > 0 ? "buy" : "sell") +
      cell("median", pct(s.median_bp)) +
      cell("stop", pct(s.stop_bp_median)) +
      cell("target / stop / time",
           `${pc(s.share_target)} / ${pc(s.share_stop)} / ${pc(s.share_time)}`) +
      (s.cut_by_restart
        ? cell("cut early", s.cut_by_restart, "sell") : "");
  }
  // По правилам отдельно: «лента» — то же, что мерили T3 и T4, и она
  // здесь контрольная рука. Сравнивать новое правило надо с ней на
  // одном периоде, а не с числами старого отчёта.
  const br = S.by_rule || {};
  const line = Object.keys(br).map(r => {
    const x = br[r];
    return x ? `<b>${disp(r)}</b>: ${x.trades} trades, wins ${
      (x.win_rate*100).toFixed(0)} % vs break-even ${
      (x.break_even*100).toFixed(0)} %, expectancy ${
      pct(x.expectancy_bp)} (${
      x.expectancy_r > 0 ? "+" : ""}${x.expectancy_r.toFixed(2)} R)`
      : `<b>${disp(r)}</b>: no trades`;
  }).join(" · ");
  const vl = verLine(S.by_ver, S.ver);
  document.getElementById("rules").innerHTML =
    `<div class="note">${vl ? vl + "<br>" : ""}${line || "&nbsp;"}</div>`;
  drawEq();
}

function drawEq() {
  const cv = document.getElementById("eq"), pts = shown().equity || [];
  const dpr = Math.min(devicePixelRatio||1, 2), W = cv.clientWidth, H = 110;
  cv.width = W*dpr; cv.height = H*dpr; cv.style.height = H+"px";
  const g = cv.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);
  if (pts.length < 2) {
    g.fillStyle = css("--muted"); g.font = "12px system-ui";
    g.textBaseline = "middle";
    g.fillText(pts.length ? "one trade — no curve yet"
                          : "the curve appears after two closed trades",
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
  const pos = v[v.length-1] >= 0;
  // Заливка под кривой; в headless createLinearGradient заглушен.
  const fill = g.createLinearGradient
    ? g.createLinearGradient(0, 0, 0, H) : null;
  if (fill && fill.addColorStop) {
    fill.addColorStop(0, pos ? "rgba(61,220,127,.18)"
                             : "rgba(255,100,115,.18)");
    fill.addColorStop(1, "rgba(0,0,0,0)");
    g.beginPath();
    v.forEach((q,i) => i ? g.lineTo(x(i), y(q)) : g.moveTo(x(i), y(q)));
    g.lineTo(x(v.length-1), y(0)); g.lineTo(x(0), y(0));
    g.closePath(); g.fillStyle = fill; g.fill();
  }
  g.strokeStyle = pos ? css("--bid") : css("--ask");
  g.lineWidth = 1.6; g.beginPath();
  v.forEach((q,i) => i ? g.lineTo(x(i), y(q)) : g.moveTo(x(i), y(q)));
  g.stroke();
  g.fillStyle = css("--muted");
  g.font = "11px ui-monospace, Menlo, monospace"; g.textBaseline = "middle";
  // Кривая счёта: в R либо в процентах движения цены.
  // В R — как есть; в процентах — величина хранится в б.п., поэтому
  // делится сотней тем же правилом, что и везде.
  g.fillText(EQR ? hi.toFixed(1) + " R" : pct(hi), W-60, y(hi));
  g.fillText(EQR ? lo.toFixed(1) + " R" : pct(lo), W-60, y(lo));
}

const px = document.getElementById("px"), tip = document.getElementById("tip");
let drag=null, pinch=null;
// Вертикаль цены. Держится В ДОЛЯХ автоматического диапазона, а не в
// самой цене: диапазон пересчитывается на каждый кадр по видимым
// свечам, и абсолютный сдвиг уезжал бы вместе с ним. Ноль и единица —
// «как считает сам график», то есть прежнее поведение бит в бит.
let vpan = 0, vzoom = 1;
function vreset() { vpan = 0; vzoom = 1; }
px.addEventListener("pointerdown", e => {
  px.setPointerCapture(e.pointerId);
  drag = {x:e.clientX, y:e.clientY, i0:view?view.i0:0, v:vpan,
          // Палец на телефоне листает страницу, и отнимать это у
          // владельца нельзя: вертикаль тянется мышью и пером, а
          // касание оставляет прокрутку экрану.
          vert: e.pointerType !== "touch"}; });
px.addEventListener("pointermove", e => {
  if (!drag) { hover(e); return; }
  const c = cands(); if (!c.length || !view) return;
  follow = false; document.getElementById("live").setAttribute("aria-pressed","false");
  CROSS = null;
  const per = px.clientWidth/view.n;
  view.i0 = Math.max(0, Math.min(c.length-view.n,
                                 drag.i0 - (e.clientX-drag.x)/per));
  if (drag.vert) {
    // Тянем вниз — содержимое едет вниз, то есть окно цены вверх.
    const ph = Math.max(1, px.clientHeight - 30);
    vpan = drag.v + (e.clientY - drag.y) / ph;
  }
  draw();
});
px.addEventListener("pointerup", e => {
  if (drag && Math.abs(e.clientX-drag.x) < 6
      && Math.abs(e.clientY-drag.y) < 6) hover(e);
  drag = null; });
// Двойной щелчок возвращает автоматический масштаб: уехав по цене,
// вернуться иначе было бы нечем, кроме перезагрузки страницы.
px.addEventListener("dblclick", () => { vreset(); draw(); });
px.addEventListener("pointerleave", () => {
  tip.style.display="none"; CROSS = null; draw(); });
px.addEventListener("wheel", e => {
  e.preventDefault();
  const k = e.deltaY>0 ? 1.15 : 1/1.15;
  // Колесо над ШКАЛОЙ цены (правое поле) и Shift+колесо где угодно —
  // масштаб цены; всё остальное как было, масштаб времени.
  if (e.shiftKey || e.offsetX > px.clientWidth - 70) {
    vzoom = Math.max(0.05, Math.min(20, vzoom*k));
    draw();
    return;
  }
  zoom(k, e.offsetX/px.clientWidth);
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
  // Перекрестие живёт всегда, подсказка — только над сделкой.
  CROSS = {mx, my};
  draw();
  const h = HIT.find(z => mx>=z.x0 && mx<=z.x1 && my>=z.y0 && my<=z.y1);
  if (!h) { tip.style.display="none"; return; }
  const row=(k,v,cls)=>`<div class="r"><span>${k}</span>
    <span class="${cls||""}">${v}</span></div>`;
  if (h.mdl) {
    // Сделка МОДЕЛИ. Открытая несёт прогноз и срок, закрытая — факт и
    // деньги; путать её со сделкой детектора нельзя, поэтому и
    // подсказка своя.
    // Процент движения цены, а не б.п. — решение владельца. Два знака,
    // при мелких величинах три: нетто после издержек иначе схлопнулось
    // бы в «0.00 %», а это как раз то число, ради которого смотрят.
    const t = h.mdl, bp = v => v == null ? "—"
      : (v > 0 ? "+" : "") + (v / 100).toFixed(Math.abs(v) >= 10 ? 2 : 3)
        + " %";
    tip.innerHTML = `<div style="font-weight:650;margin-bottom:3px">
        model · ${t.side} · ${disp(t.state)}</div>`
      + row("arm", t.arm === "nn" ? "neural (AI)" : "trees (ML)")
      + row("signal hour", t.hour)
      + row("entry", new Date(t.opened_at*1000).toISOString().slice(11,16)
            + " UTC" + (t.lag_sec == null ? ""
              : ` (+${Math.round(t.lag_sec/60)} min)`))
      + row("expects", bp(t.expected_bp))
      + row("adverse expected", bp(t.mae_bp))
      // Ход в пользу — второй конец обещания. Пустой у сделок, записанных
      // до того, как поле появилось; показывать там ноль значило бы
      // выдать отсутствие данных за «модель не ждёт движения».
      + (t.mfe_bp == null ? "" : row("favorable expected", bp(t.mfe_bp)))
      + (t.state === "закрыта"
         ? row("got", bp(t.got_bp), (t.got_bp>0)===(t.side==="long")
               ? "buy" : "sell")
           + row("net after costs", bp(t.net_bp),
                 t.net_bp>0?"buy":"sell")
           + row("P&L", (t.pnl>0?"+":"") + t.pnl + " $",
                 t.pnl>0?"buy":"sell")
         : t.state === "открыта"
           ? row("closes in",
                 (t.closes_in_sec/3600).toFixed(1) + " h")
           : row("no outcome", "hour not summarised yet"));
    tip.style.display="block";
    tip.style.left = Math.max(4, Math.min(px.clientWidth-tip.offsetWidth-4,
                                          mx+14))+"px";
    tip.style.top = Math.max(4, my+18)+"px";
    return;
  }
  const m = h.m;
  tip.innerHTML = `<div style="font-weight:650;margin-bottom:3px">${
      m.long?"long":"short"} · ${disp(m.state)}</div>`
    + row("time", stamp(m.t)) + row("entry", m.entry)
    + (m.state === "не открыта" ? row("why", m.why || "rule refuses")
       : row("stop", m.stop) + row("target", m.target))
    + row("level", `${m.level} (${disp(m.kind)})`)
    + row("rr", "1:"+m.rr) + row("held", m.held+" s")
    + row("result", `${pct(m.pnl_bp)} · ${
        m.r>0?"+":""}${m.r} R`, m.pnl_bp>0?"buy":"sell");
  tip.style.display="block";
  tip.style.left = Math.max(4, Math.min(px.clientWidth-tip.offsetWidth-4,
                                        mx+14))+"px";
  tip.style.top = Math.max(4, my+18)+"px";
}
document.getElementById("fit").onclick = () => {
  const c = cands(); if (!c.length) return;
  // «Весь период» возвращает и вертикаль: кнопка обещает показать всё,
  // а с уехавшей ценой она показала бы весь период мимо свечей.
  view = {i0:0, n:c.length}; follow=false; vreset();
  document.getElementById("live").setAttribute("aria-pressed","false"); draw();
};
// Клик по строке сделки модели — центрировать график на ней. То же
// самое, что ссылка с часом в адресе, только без перезагрузки; час
// уезжает в адрес, чтобы страницу можно было переслать.
document.getElementById("mrows").onclick = e => {
  const tr = e.target && e.target.closest
    ? e.target.closest("[data-h]") : null;
  if (!tr) return;
  MDL.hour = tr.dataset.h || "";
  const p = new URLSearchParams(location.search);
  p.set("hour", MDL.hour);
  p.set("arm", MDL.arm);
  history.replaceState(null, "", location.pathname + "?" + p.toString());
  MDL.fit = true;
  fitFocus();
  mrows();
};

document.getElementById("live").onclick = e => {
  follow = !follow; e.target.setAttribute("aria-pressed", String(follow));
  draw();
};
document.getElementById("unit").onclick = e => {
  EQR = !EQR; e.target.textContent = EQR ? "in %" : "in R"; drawEq();
};
// Тумблера нет: вид один — всё под нынешними правилами.
localStorage.removeItem("rec");
window.addEventListener("resize", () => { draw(); drawEq(); });
// Переключатель рук рисуется сразу, до первого ответа: кнопка, которая
// появляется только при удачном запросе, при неудачном неотличима от
// «такой возможности нет».
armButtons();
pullGroups();
document.getElementById("symq").oninput = e => {
  GRP.q = e.target.value.trim(); renderGroups();
};
// Клик мимо выпадающего списка закрывает его — иначе он висит поверх
// графика, пока не попадёшь точно в заголовок.
document.addEventListener("click", e => {
  const p = document.getElementById("pick");
  if (p && p.open && p.contains && !p.contains(e.target)) p.open = false;
});
pull(); setInterval(pull, 1000);
</script>
"""


# Страница разбора ОДНОЙ сделки — просьба владельца: у каждой сделки
# значок «i», по нему страница, где простыми словами объяснено, почему
# модель открыла здесь и как расставила уровни. Слова собираются ИЗ
# ЧИСЕЛ записи (why/setup/train_seq/обещания) и правил книги из ответа
# сервера — прозы в записи нет, и врать страница может только вместе с
# числами. Признаки переводятся на человеческий словарём FEAT_EN.
TRADEINFO = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>trade breakdown</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.55 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
h1{font-size:17px;margin:8px 0 2px}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:12px 14px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
table{border-collapse:collapse;width:100%}
td,th{padding:4px 8px;text-align:left;border-bottom:1px solid
 var(--rule-soft);font-size:13px;vertical-align:top}
th{color:var(--muted);font-weight:600}
.good{color:var(--bid)}.bad{color:var(--ask)}
a{color:var(--accent)}
.btn{display:inline-block;border:1px solid var(--rule);
 border-radius:999px;padding:4px 12px;color:var(--ink);
 text-decoration:none;font-size:12px;background:var(--chip)}
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">trade breakdown</span>
  <span style="flex:1"></span>
  <a class="btn" id="chartlink" href="#">open on the chart</a></div>
<h1 id="ttl">&hellip;</h1>
<div class="k mono" id="sub"></div>
<div id="whybox"></div>
</div>
<script>
const Q = new URLSearchParams(location.search);
const KEY = Q.get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
const HZ = ["h1","h24","sit","sit_obs"].includes(Q.get("hz"))
  ? Q.get("hz") : "";
const ARM = Q.get("arm") === "nn" ? "nn" : "gbm";
const HOUR = Q.get("hour") || "";
const SYM = Q.get("sym") || "";
const SIDE = Q.get("side") || "";
const RR = Q.get("rr");

function pct(v){ if (v == null) return "—";
  return (v>0?"+":"") + (v/100).toFixed(Math.abs(v)>=10?2:3) + " %"; }
function px_at(entry, bp){ if (entry == null || bp == null) return null;
  return +(entry * (1 + bp/1e4)).toPrecision(6); }
function utc(ts){ if (!ts) return "—";
  const d = new Date(ts*1000);
  return d.toISOString().slice(0,16).replace("T"," ") + " utc"; }

// Состояния и причины выхода приходят по-русски: это ключи файлов.
const ST_EN = {"закрыта":"closed","открыта":"open",
  "вышла, ждёт разбора":"exited, pnl pending",
  "ждёт разбора":"awaiting review","без исхода":"no outcome"};
const EXIT_EN = {"прогноз развернулся":"the forecast flipped sign",
  "цена прошла обещанный ход против":"price hit the stop",
  "цена дошла до обещанной цели":"price reached the target",
  "предел возраста":"the 24 h age limit",
  "вход по ситуации":"situational entry"};
const FAM_EN = {absorption:"the order book being eaten through",
  book:"order-book imbalance and depth",
  tape:"pressure in the tape (aggressive flow)",
  liq:"liquidations", oi:"open interest",
  funding:"funding and basis",
  move:"the coin's own price move",
  squeeze:"a squeeze (range compression)",
  tilt:"a tilted, one-sided drift", range:"range trading / dwell",
  vol:"the volatility regime", leader:"the leader and the sector",
  clock:"time of day", round:"round price levels",
  beta:"how the coin follows the market", age:"listing age",
  other:"other"};
// Перевод признаков на человеческий. Незнакомое имя честно остаётся
// как есть: выдуманное описание хуже сырого имени.
const FEAT_EN = {
  imb_best:"bid vs ask size at the very top of the book",
  spread_rel:"the bid-ask spread vs its usual width",
  upd_rel:"how fast the book is changing vs usual",
  big_rel:"the largest resting order vs what is usual here",
  turn_rel:"turnover this hour vs usual",
  delta:"who is hitting harder in the tape — buyers or sellers",
  burst:"the biggest one-second volume spike vs usual",
  traded_share:"how much of the hour had any trades at all",
  eat_bid:"sellers eating through the shown bids",
  eat_ask:"buyers eating through the shown asks",
  net_path_24h:"how straight the 24 h move was (net vs path)",
  vol_regime:"volatility today vs its week — awake or asleep",
  fr_bp:"the current funding rate",
  mins_fund:"minutes left to the next funding payment",
  oi_rel:"open interest vs its usual level",
  oi_chg_4h:"open interest change over 4 h",
  oi_chg_24h:"open interest change over 24 h",
  basis_bp:"perp price vs spot (premium or discount)",
  liq_long_share:"long liquidations as a share of turnover",
  liq_short_share:"short liquidations as a share of turnover",
  liq_imb:"which side got liquidated more",
  squeeze_4h:"how squeezed the 4 h range is vs usual",
  squeeze_24h:"how squeezed the 24 h range is vs usual",
  tilt_4h:"a tilted move: the net 4 h push inside its range",
  range_pos:"where price sits in the daily range (0 low, 1 high)",
  dwell_24h:"how long price has been sitting in this corridor",
  hod_sin:"time of day", hod_cos:"time of day", dow:"day of week",
  btc_ret_4h:"BTC's own 4 h move",
  sec_ret_4h:"the coin's sector move over 4 h",
  rel_sec_4h:"how far the coin lags its own sector over 4 h",
  dist_round:"distance to the nearest round price",
  beta:"how strongly the coin follows the market wave",
  age_rec:"the coin's age in the record"};
function featDesc(n){
  if (FEAT_EN[n]) return FEAT_EN[n];
  let m = n.match(/^ret_(\d+)h?$/);
  if (m) return `the coin's own ${m[1]} h move vs its usual volatility`;
  const band = w => parseFloat((w*100).toFixed(3));
  m = n.match(/^imb_([\d.]+)$/);
  if (m) return `bid vs ask depth within ±${band(+m[1])} % of price`;
  m = n.match(/^depth_b([\d.]+)$/);
  if (m) return `bid depth within ±${band(+m[1])} % vs usual`;
  m = n.match(/^depth_a([\d.]+)$/);
  if (m) return `ask depth within ±${band(+m[1])} % vs usual`;
  return n;
}

async function ask(rr){
  const p = new URLSearchParams({k:KEY, per:500, lite:1, sym:SYM});
  if (HZ) p.set("hz", HZ);
  if (rr != null) p.set("rr_min", String(rr));
  const r = await fetch("/model_trades?" + p.toString());
  return await r.json();
}
function findT(rows){
  return (rows||[]).find(t => t.sym === SYM && t.hour === HOUR
    && (t.arm||"gbm") === ARM && (!SIDE || t.side === SIDE)) || null;
}
async function load(){
  let d, t;
  try {
    d = await ask(RR != null && RR !== "" ? parseFloat(RR) : null);
    t = findT(d.rows);
    // Сделки с отношением ниже гейта живут в наблюдательной записи —
    // та же логика, что у графика: прямая ссылка обязана открываться.
    if (!t && HZ === "sit" && d.source_book === "traded") {
      const d2 = await ask(0);
      const t2 = findT(d2.rows);
      if (t2) { d = d2; t = t2; }
    }
  } catch (e) {
    document.getElementById("ttl").textContent =
      "no link to the collector — try again";
    return;
  }
  render(d, t);
}
function sec(cap, body){
  return `<div class="panel"><div class="cap">${cap}</div>${body}</div>`;
}
function render(d, t){
  const cl = document.getElementById("chartlink");
  const cp = new URLSearchParams({k:KEY, sym:SYM, arm:ARM, hour:HOUR});
  if (HZ) cp.set("hz", HZ);
  if (RR != null && RR !== "") cp.set("rr", RR);
  cl.href = "/chart?" + cp.toString();
  if (!t) {
    document.getElementById("ttl").textContent = "trade not found";
    document.getElementById("whybox").innerHTML = sec("what happened",
      `<p>No trade of arm <b>${ARM}</b> on <b>${SYM}</b> for hour
       <b>${HOUR}</b> in this book. If the book was archived by a
       rules change, the trade lives in the archive on disk, not in
       the live record.</p>`);
    return;
  }
  const bookName = d.situational ? "situational book"
    : `${d.horizon_h || 4} h book`;
  document.getElementById("ttl").textContent =
    `${SYM.replace("USDT","")} · ${t.side} · ${bookName} · ${
      ST_EN[t.state] || t.state}`;
  document.getElementById("sub").textContent =
    `entered ${utc(t.opened_at)} · ${ARM === "nn"
      ? "neural arm" : "tree arm"}${t.train_seq != null
      ? " · training #" + t.train_seq : ""}${
      d.source_book === "observation"
      ? " · observation record (the bot does not trade it)" : ""}`;

  let html = "";

  // --- что модель увидела -------------------------------------------
  let saw = "";
  if (t.setup && t.setup.length) {
    saw += `<p>Most of this forecast came from <b>${t.setup.map(x =>
      `${FAM_EN[x[0]] || x[0]} (${Math.round(x[1]*100)} %)`)
      .join("</b> and <b>")}</b>.
      <span class="dim">The share says how much of the forecast size
      these feature groups produced. It is a reading of the model's
      arithmetic, not a strategy it picked — the model has no named
      strategies.</span></p>`;
  }
  if (t.why && t.why.length) {
    saw += `<table><tr><th>signal</th><th>in plain words</th>
      <th>pushed the forecast by</th></tr>` + t.why.map(w =>
      `<tr><td class="mono">${w[0]}</td><td>${featDesc(w[0])}</td>
       <td class="mono ${w[1] > 0 ? "good" : "bad"}">${
         pct(w[1])}</td></tr>`).join("") + "</table>";
  }
  if (!saw) saw = `<p class="dim">Not recorded for this trade — it was
    opened before explanations were introduced, or the weights predate
    the field. New trades carry it.</p>`;
  html += sec("what the model saw", saw);

  // --- почему вход именно здесь -------------------------------------
  let why = "";
  const exp = t.expected_bp;
  if (t.rank != null && t.of) {
    why = `<p>This book re-balances on the hour: it takes the names
      with the most extreme expected move. <b>${SYM.replace("USDT","")}
      </b> ranked <b>#${t.rank} of ${t.of}</b> coins by expected move
      (${pct(exp)} over ${d.horizon_h || 4} h) — that is the whole
      entry rule here.</p>`;
  } else if (t.fwd0_bp != null && exp != null) {
    const disc = Math.abs(exp) - Math.abs(t.fwd0_bp);
    why = `<p>At the top of the hour the model expected
      <b>${pct(t.fwd0_bp)}</b> from this coin. The scanner then watched
      the live price. By ${utc(t.opened_at)} the price had walked
      <b>${pct(disc)}</b> against that promise — the entry got cheaper
      than the model planned by more than the round cost — while the
      remaining expected move, <b>${pct(exp)}</b>, was still above the
      ${((d.min_edge_bp ?? 22)/100).toFixed(2)} % entry gate.</p>
      <p>Two more checks passed before entering: the crossing happened
      <b>in front of the scanner</b> (the name was first seen away
      from the trigger — so this was a move, not a wobble around a
      line it was parked at), and the promised reward was at least
      ${d.min_rr ?? 2}&times; the distance to the actual stop.</p>`;
  } else if (exp != null) {
    why = `<p>The model expected <b>${pct(exp)}</b>. The entry
      mechanics for this trade predate the recorded fields.</p>`;
  } else {
    why = `<p class="dim">Not recorded for this trade.</p>`;
  }
  html += sec("why it entered here", why);

  // --- как расставлены уровни ---------------------------------------
  let lv = "";
  if (t.mae_bp != null) {
    const stopPx = px_at(t.entry_px, t.mae_bp);
    const tgtPx = px_at(t.entry_px, t.mfe_bp);
    const learned = String(t.stop_of || "").indexOf("q_") > 0;
    lv = `<p><b>Stop</b> at ${stopPx ?? "—"} (${pct(t.mae_bp)} from
      entry). ` + (learned
      ? `This is <b>not</b> where the model expects price to go — that
         line is at ${pct(t.mae_m_bp)}. It is a separately learned
         level that price historically passes in only
         <b>${Math.round((d.stop_tau ?? 0.2)*100)} %</b> of cases:
         far enough that ordinary noise does not knock the trade out,
         close enough that a real break ends it.`
      : `Set on the model's expected adverse line (the older stop
         rule).`) + `</p>`
      + (t.mfe_bp != null
      ? `<p><b>Target</b> at ${tgtPx ?? "—"} (${pct(t.mfe_bp)}): the
         best excursion the model expects in the trade's favour —
         what it waits for, not a rare tail.</p>` : "")
      + `<p class="dim">Exits, in order: stop or target touched by the
       path of prices (checked every ~5 seconds, fill at the price
       available when noticed — in a gap the fill can be worse than
       the level, the stop does <b>not</b> guarantee the loss bound);
       the forecast flipping sign at an hourly review; the 24 h age
       limit.</p>`;
  } else {
    lv = `<p class="dim">No levels recorded for this trade.</p>`;
  }
  html += sec("how the levels are set", lv);

  // --- чем кончилось -------------------------------------------------
  let out = "";
  if (t.state === "закрыта") {
    out = `<p>Closed: <b>${EXIT_EN[t.exit_reason] || t.exit_reason
      || "period ended"}</b>. Price moved ${pct(t.got_bp)}; after the
      round cost the trade made <b class="${(t.net_bp||0) > 0
      ? "good" : "bad"}">${pct(t.net_bp)}</b>${t.pnl != null
      ? ` (${t.pnl > 0 ? "+" : ""}${t.pnl.toFixed(2)} $)` : ""}.</p>`;
  } else if (t.exit_pending) {
    out = `<p>The guard saw the exit (${EXIT_EN[t.exit_reason]
      || t.exit_reason}) at ${utc(t.exit_ts)}; money is booked at the
      hourly review — the shadowed bot reads the same files, and the
      page must not run ahead of it.</p>`;
  } else {
    out = `<p>Still open${t.unreal_net_bp != null
      ? `; running at ${pct(t.unreal_net_bp)} after costs` : ""}.</p>`;
  }
  if (t.odd != null)
    out += `<p class="dim">Novelty: ${(t.odd*100).toFixed(0)} % of this
      coin's features were outside anything the training saw — on high
      novelty the forecast is less reliable (measured, not a
      rule).</p>`;
  html += sec("how it went", out);

  document.getElementById("whybox").innerHTML = html;
}
load();
</script>
"""


# Страница лиги — просьба владельца: наблюдение за каждой стратегией
# и моделью отдельно (что ведёт себя лучше) и ТОП сделок по
# прибыльности за сегодня / месяц / год. Все агрегаты приходят с
# сервера готовыми (`/league`) — страница только рисует: вторая
# реализация сумм однажды разошлась бы с первой.
LEAGUE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>league — what works best</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.5 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
/* Ширина страницы — по вопросу владельца «почему бы не сделать шире»:
   1100px делили экран на панели по ~256px, и полная таблица группы
   (имя + четыре колонки чисел, ~360px) не влезала ни в одну — контент
   жил за прокруткой. Теперь панель по минимуму вмещает таблицу
   целиком, а страница даёт четырём панелям встать в ряд. */
.wrap{max-width:1560px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
h1{font-size:17px;margin:8px 0}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:12px 14px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
table{border-collapse:collapse;width:100%}
td,th{padding:4px 8px;text-align:left;border-bottom:1px solid
 var(--rule-soft);font-size:13px;white-space:nowrap}
th{color:var(--muted);font-weight:600}
.good{color:var(--bid)}.bad{color:var(--ask)}
a{color:var(--accent)}
button{background:var(--chip);border:1px solid var(--rule);
 color:var(--ink);border-radius:999px;padding:4px 12px;font-size:12px;
 cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,
 minmax(340px,1fr));gap:12px}
.scroll{overflow-x:auto}
/* В панелях групп самое широкое — имя («book eaten (absorption)»),
   и ему МОЖНО переноситься: числа при этом остаются в одну строку.
   Без переноса таблица шире панели, и колонки денег срезались, а
   срез читался как «денег нет». */
.grid td:first-child{white-space:normal;min-width:96px}
.grid td,.grid th{padding:4px 6px}
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">league — what works best</span>
  <span style="flex:1"></span>
  <span id="per"></span></div>
<div id="note" class="k"></div>
<div id="box">&hellip;</div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
let PERIOD = "30d", DATA = null;

function pct(v){ if (v == null) return "—";
  return (v>0?"+":"") + (v/100).toFixed(Math.abs(v)>=10?2:3) + " %"; }
function utc(ts){ if (!ts) return "—";
  return new Date(ts*1000).toISOString().slice(5,16).replace("T"," "); }
const ARM_EN = {gbm:"trees (ML)", nn:"neural (AI)"};
const BOOK_EN = {h4:"4 h book", h1:"1 h book", h24:"24 h book",
                 sit:"situational"};
const FAM_EN = {absorption:"book eaten (absorption)",
  book:"book imbalance / depth", tape:"tape pressure",
  liq:"liquidations", oi:"open interest", funding:"funding & basis",
  move:"price move / reversal", squeeze:"squeeze", tilt:"tilt",
  range:"range / dwell", vol:"volatility regime",
  leader:"leader & sector", clock:"time of day",
  round:"round levels", beta:"market beta", age:"listing age"};
const PER_EN = {today:"today (utc)", "30d":"last 30 days",
                "365d":"last 365 days"};

function groupTable(cap, rows, names){
  if (!rows || !rows.length)
    return `<div class="panel"><div class="cap">${cap}</div>
      <div class="dim">nothing closed in this period</div></div>`;
  // Лидер — просто верхняя строка сортировки по деньгам. При малом
  // числе сделок это шум, и число стоит в той же строке нарочно.
  // Таблица завёрнута в прокрутку, как таблицы топа: панель узкая, и
  // без неё правые колонки СРЕЗАЛИСЬ — владелец видел «avg net» без
  // процента и деньги не видел вовсе.
  return `<div class="panel"><div class="cap">${cap}</div>
    <div class="scroll"><table><tr><th></th><th>trades</th><th>wins</th>
    <th>avg net</th><th>$</th></tr>` + rows.map((g, i) =>
    `<tr><td>${i === 0 ? "&#9733; " : ""}${
       (names && names[g.key]) || g.key}</td>
     <td class="mono">${g.n}</td>
     <td class="mono">${Math.round(g.win*100)} %</td>
     <td class="mono">${pct(g.net_bp_avg)}</td>
     <td class="mono ${g.pnl > 0 ? "good" : "bad"}">${
       g.pnl > 0 ? "+" : ""}${g.pnl}</td></tr>`).join("")
    + "</table></div></div>";
}
function tradeRows(list){
  return list.map(t => {
    const ip = new URLSearchParams({k: KEY, sym: t.sym,
      arm: t.arm || "gbm", hour: t.hour, side: t.side});
    if (t.hz && t.hz !== "h4") ip.set("hz", t.hz);
    return `<tr>
      <td class="mono">${utc(t.at)}</td>
      <td class="mono">${(t.sym||"").replace("USDT","")}</td>
      <td>${t.side === "long" ? "L" : "S"}</td>
      <td class="dim">${BOOK_EN[t.hz] || t.hz}</td>
      <td>${t.arm === "nn" ? "neu" : "tre"}</td>
      <td class="dim">${t.setup
        ? (FAM_EN[t.setup] || t.setup).split(" (")[0] : "—"}</td>
      <td class="mono">${pct(t.net_bp)}</td>
      <td class="mono ${t.pnl > 0 ? "good" : "bad"}">${
        t.pnl > 0 ? "+" : ""}${(t.pnl ?? 0).toFixed(2)}</td>
      <td><a href="/trade-info?${ip.toString()}"
        style="text-decoration:none">&#9432;</a></td></tr>`;
  }).join("");
}
function render(){
  const d = DATA;
  const box = document.getElementById("box");
  document.getElementById("per").innerHTML =
    ["today","30d","365d"].map(k => `<button data-p="${k}"
      aria-pressed="${String(PERIOD === k)}">${PER_EN[k]}</button>`)
      .join(" ");
  document.querySelectorAll("#per button").forEach(b =>
    b.onclick = () => { PERIOD = b.dataset.p; render(); });
  const errs = (d && d.errors && d.errors.length)
    ? `<div class="panel" style="border-color:var(--ask)">
       <div class="cap" style="color:var(--ask)">books that failed to
       load</div>${d.errors.map(e => `<div class="mono">${e}</div>`)
         .join("")}
       <div class="k">these books are missing from every number on
       this page — the totals below are NOT the whole story</div>
       </div>` : "";
  if (!d || !d.present) {
    box.innerHTML = errs + `<div class="panel">no closed trades yet —
      the league starts with the first outcome${(d && d.books)
        ? ` <span class="dim">(books scanned: ${
            d.books.map(b => `${b.book} ${b.trades} trades / ${
              b.closed_kept} kept`).join(", ") || "none"})</span>`
        : ""}</div>`;
    return;
  }
  const p = (d.periods || {})[PERIOD] || {};
  document.getElementById("note").innerHTML =
    `${p.n || 0} closed trades in this period · situations known for
     ${p.setup_known || 0} of them (older trades predate the field) ·
     realised money only, open positions are not here · the
     observation record is excluded — its entries repeat the traded
     book's · with a handful of trades every leader is noise: read
     the counts first`;
  const g = p.groups || {};
  box.innerHTML = errs + `<div class="grid">
    ${groupTable("models (arms)", g.arm, ARM_EN)}
    ${groupTable("books (hold)", g.book, BOOK_EN)}
    ${groupTable("situations (dominant family)", g.setup, FAM_EN)}
    ${groupTable("sides", g.side, {long:"long", short:"short"})}
    </div>
    <div class="panel"><div class="cap">top trades — ${
      PER_EN[PERIOD]}</div><div class="scroll"><table>
      <tr><th>closed</th><th>coin</th><th>side</th><th>book</th>
      <th>arm</th><th>situation</th><th>net</th><th>$</th><th>i</th>
      </tr>${tradeRows(p.best || [])
        || `<tr><td colspan="9" class="dim">none</td></tr>`}
    </table></div></div>
    <div class="panel"><div class="cap">worst trades — ${
      PER_EN[PERIOD]}</div><div class="scroll"><table>
      <tr><th>closed</th><th>coin</th><th>side</th><th>book</th>
      <th>arm</th><th>situation</th><th>net</th><th>$</th><th>i</th>
      </tr>${tradeRows(p.worst || [])
        || `<tr><td colspan="9" class="dim">none</td></tr>`}
    </table></div></div>`;
}
async function pull(){
  try {
    const r = await fetch("/league?k=" + encodeURIComponent(KEY));
    DATA = await r.json();
  } catch (e) { DATA = null; }
  render();
}
pull();
setInterval(pull, 60000);
</script>
"""


def serve(collector, port, token, log):
    """Поднять сервер наблюдения в отдельном потоке."""

    class H(BaseHTTPRequestHandler):
        # Постоянное соединение. По умолчанию сервер отвечает по
        # HTTP/1.0 и закрывает соединение после каждого ответа, то есть
        # на каждый опрос идёт новое TCP-рукопожатие. На мобильной сети
        # потерянный SYN повторяется с нарастающей задержкой — секунда,
        # три, семь, — и страница открывается через пять-десять секунд
        # при исправном сервере, отвечающем за полсекунды.
        protocol_version = "HTTP/1.1"
        timeout = 65                      # праздное соединение не держим

        def _ok(self, body, ctype):
            # Сжатие: первый ответ весит под полсотни килобайт, и на
            # мобильной связи это разница между «открылось» и «висит».
            enc = (self.headers.get("Accept-Encoding") or "")
            gz = "gzip" in enc and len(body) > 1024
            if gz:
                body = gzip.compress(body, 6)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _empty(self, code, body=b""):
            """Ответ без содержимого обязан нести длину.

            Иначе при постоянном соединении клиент ждёт тело, которого
            не будет, — и это выглядит как зависший сервер.
            """
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _deny(self):
            self._empty(403, b"nope")

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
            if u.path == "/recount":
                try:
                    n = int(float(q.get("hours", ["24"])[0]))
                except ValueError:
                    n = 24
                go = q.get("go", ["1"])[0] not in ("0", "false", "")
                return self._ok(json.dumps(
                    collector.recount(max(1, min(n, 72)), start=go,
                                      sym=q.get("sym", [None])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/candles":
                try:
                    n = int(float(q.get("hours", ["12"])[0]))
                except ValueError:
                    n = 12
                try:
                    end = float(q.get("end", [""])[0])
                except ValueError:
                    end = None
                return self._ok(json.dumps(
                    collector.candles_files(q.get("sym", [None])[0], n,
                                            end=end),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/trades":
                return self._ok(json.dumps(
                    collector.trades(q.get("sym", [None])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/groups":
                return self._ok(json.dumps(
                    {"groups": collector.groups},
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/bot-full":
                return self._ok(json.dumps(
                    collector.bot_full(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/bot-page":
                return self._ok(BOTPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/bot":
                return self._ok(json.dumps(
                    collector.bot_status(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/model":
                def fval(name):
                    """Порог числом; ОТСУТСТВИЕ — не ноль.

                    Ноль означает «любое отношение» и переключает
                    показ на наблюдательную запись; отсутствие — «не
                    выбирал», то есть книга как она торгует. Свести их
                    к одному числу значило бы отдать владельцу другую
                    книгу при первом же открытии страницы."""
                    if name not in q:
                        return None
                    try:
                        return float(q[name][0])
                    except (ValueError, IndexError):
                        return None
                return self._ok(json.dumps(
                    collector.model_state(rr_min=fval("rr_min")),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/model_trades":
                def fnum(name):
                    """Порог RR числом; мусор — как отсутствие порога.

                    Падать на кривом параметре нельзя: страница —
                    единственный способ смотреть на сбор, и ошибка в
                    адресе не должна её гасить."""
                    if name not in q:
                        return None
                    try:
                        v = float(q[name][0])
                    except (ValueError, IndexError):
                        return None
                    # Ноль здесь осмыслен: «любое отношение». Отбор он
                    # не делает, но выбирает ИСТОЧНИК — наблюдательную
                    # запись вместо торгуемой книги.
                    return v if v >= 0 else None

                def ival(name, default):
                    try:
                        return int(float(q.get(name, [""])[0]))
                    except ValueError:
                        return default
                return self._ok(json.dumps(
                    collector.model_trades(
                        page=ival("page", 0), per=ival("per", 100),
                        arm=q.get("arm", [None])[0] or None,
                        state=q.get("state", [None])[0] or None,
                        sym=q.get("sym", [None])[0] or None,
                        hz=q.get("hz", [None])[0] or None,
                        rr_min=fnum("rr_min"),
                        lite=q.get("lite", [""])[0] in ("1", "true")),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/model_marks":
                return self._ok(json.dumps(
                    collector.model_marks(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/trades-page":
                return self._ok(TRADES.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/trade-info":
                return self._ok(TRADEINFO.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/league":
                return self._ok(json.dumps(
                    collector.model_league(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/league-page":
                return self._ok(LEAGUE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/chart":
                return self._ok(CHART.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path in ("/", "/index.html"):
                return self._ok(PAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            self._empty(404)

        def log_message(self, *a):                        # тишина в консоли
            return

    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    except OSError as e:
        # Занятый порт означает ровно одно: прежний сборщик ещё жив.
        # Голая трасса `[Errno 98] Address already in use` этого не
        # говорит, и владелец, увидев её, считал перезапуск удавшимся —
        # а на сервере продолжал работать СТАРЫЙ код, отдавая исправную
        # с виду страницу. Тишина вместо отказа, третий раз подряд.
        if getattr(e, "errno", None) in (48, 98):          # EADDRINUSE
            raise SystemExit(
                f"\nПОРТ {port} ЗАНЯТ — прежний сборщик ещё не закрылся.\n"
                f"Новый НЕ запущен, на сервере работает старый код.\n\n"
                f"Дождитесь его выхода и запустите снова:\n"
                f"  pkill -f 'b1_book/collect.py'\n"
                f"  while pgrep -f 'b1_book/collect.py' >/dev/null; "
                f"do sleep 1; done\n"
                f"или разом: tools/restart_book.sh\n") from None
        raise
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"страница наблюдения: http://<адрес сервера>:{port}/"
        + (f"?k={token}" if token else ""))
    return srv
