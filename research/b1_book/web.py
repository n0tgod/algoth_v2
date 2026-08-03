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
.pick{padding:8px 10px}
.pickwrap>summary{list-style:none}
.pickwrap>summary::-webkit-details-marker{display:none}
.pick input{width:100%;font:inherit;font-size:16px;color:var(--ink);
 background:var(--ground);border:1px solid var(--rule);padding:7px 10px;
 margin-bottom:6px}
details.grp{border-top:1px solid var(--rule)}
details.grp summary::-webkit-details-marker{display:none}
details.grp summary{cursor:pointer;padding:6px 2px;font-size:12px;
 color:var(--muted);letter-spacing:.03em;list-style:none;
 display:flex;justify-content:space-between}
details.grp summary::after{content:"▸";color:var(--muted)}
details.grp[open] summary::after{content:"▾"}
details.grp .gs{display:flex;flex-wrap:wrap;gap:5px;padding:2px 0 8px;max-height:38vh;overflow-y:auto}
.modelbox{padding:8px 10px;font-size:13px}
.modelbox .mline{color:var(--muted);font-size:12px;margin-bottom:6px}
.thoughts{max-height:230px;overflow-y:auto;font-size:12.5px;
 white-space:pre-wrap;line-height:1.5}
.thoughts .tt{color:var(--muted)}
.mtr{width:100%;border-collapse:collapse;font-size:11.5px}
.mtr th{text-align:left;color:var(--muted);font-weight:400;
 padding:2px 6px 3px 0;border-bottom:1px solid var(--rule)}
.mtr td{padding:2px 6px 2px 0;white-space:nowrap}
.mtr tr.good td:nth-child(8){color:var(--bid)}
.mtr tr.bad td:nth-child(8){color:var(--ask)}
.mtr tr.dim td{color:var(--muted)}
@media(max-width:640px){
 .wrap{padding:10px 8px 30px}
 button{padding:8px 12px;font-size:13.5px}
 .strip{grid-template-columns:repeat(auto-fit,minmax(76px,1fr))}
 td{padding:3px 7px}
 .tape{max-height:240px}
}
.open{font-size:13px;color:var(--ink);background:var(--panel);
 border:1px solid var(--accent);padding:4px 9px;text-decoration:none}
.open:hover{background:var(--grid)}
button{font:inherit;font-size:13px;color:var(--ink);background:var(--panel);
 border:1px solid var(--rule);padding:4px 9px;cursor:pointer}
button[aria-pressed=true]{border-color:var(--accent);
 box-shadow:inset 0 -2px 0 var(--accent)}
.cols{display:grid;gap:12px;grid-template-columns:1fr}
@media(min-width:760px){.cols{grid-template-columns:1fr 1fr}}
.panel{background:var(--panel);border:1px solid var(--rule);overflow-x:auto;-webkit-overflow-scrolling:touch}
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
<h1>Order Book Live</h1>
<p class="sub" id="sub">connecting…</p>
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
    `${d.symbols.length} symbols · collecting for ${(s.uptime_sec/3600).toFixed(1)} ч`;
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
        fmt((bk.ask-bk.bid)/bk.bid*1e4, 1)} б.п. · середина ${
        fmt((bk.ask+bk.bid)/2, 6)}</td></tr>` +
      bk.b.map(r => row(r, "b")).join("");
    document.getElementById("cap-book").textContent =
      `${bk.depth ?? "?"} levels · upd/s ${bk.upd} · reach ±${
        bk.reach_b}/${bk.reach_a} б.п.`;
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
  document.getElementById("cap-tape").textContent = `${tp.length} recent`;
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
        <td class="mono ${x.long?"buy":"sell"}">${x.long?"лонг":"шорт"}</td>
        <td class="mono">${x.entry}</td>
        <td class="mono" style="color:var(--muted)">${x.kind}</td>
        <td class="mono">1:${x.rr}</td>
        <td class="mono">${x.state}</td>
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
      + (s.cut_by_restart ? cell("оборвано", s.cut_by_restart, "bad") : "");
  const br = A.by_rule || {};
  document.getElementById("rules2").innerHTML =
    `<div style="padding:7px 10px;font-size:12.5px;color:var(--muted)">`
    + (verLine(A.by_ver, A.ver) ? verLine(A.by_ver, A.ver) + "<br>" : "")
    + (Object.keys(br).map(r => {
        const x = br[r];
        return x ? `<b>${r}</b>: ${x.trades} trades, wins ${pc(x.win_rate)} `
          + `vs break-even ${pc(x.break_even)}, expectancy ${
            pct(x.expectancy_bp)}`
          : `<b>${r}</b>: no trades`;
      }).join(" · ") || "&nbsp;") + `</div>`;
  document.getElementById("alltr").innerHTML = A.trades.length
    ? A.trades.slice(0, 60).map(x => `<tr ${
        (x.ver || 1) !== A.ver
          ? 'style="opacity:.5" title="прежние правила — в статистику не идёт"'
          : ""}>
        <td class="mono" style="color:var(--muted)">${
          new Date(x.t*1000).toISOString().slice(5,16).replace("T"," ")}</td>
        <td class="mono">${(x.sym||"").replace("USDT","")}</td>
        <td>${x.rule || "лента"}</td>
        <td class="mono ${x.long?"buy":"sell"}">${x.long?"лонг":"шорт"}</td>
        <td class="mono">1:${x.rr}</td>
        <td class="mono">${x.state}</td>
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
    g.fillText("кривая появится после двух закрытых сделок", 10, H/2);
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

// --- модель: состояние, живой IC и мысли трейдерскими словами --------
const MDL = {data: null, arm: "all", mode: "live"};   // переключатель рук турнира
async function pullModel() {
  try {
    const r = await fetch(`/model?k=${encodeURIComponent(KEY)}`);
    const d = await r.json();
    if (d && d.present !== undefined) { MDL.data = d; }
  } catch (e) { /* тихо: следующий опрос через минуту */ }
  renderModel();
}
function wireModes() {
  const box = document.getElementById("modelbox");
  box.querySelectorAll("[data-mode]").forEach(b =>
    b.onclick = () => { MDL.mode = b.dataset.mode; renderModel(); });
}

// Предпросмотр: та же модель на том, что уже накоплено. Каждая строка
// здесь обязана нести оговорку о том, чем он отличается от боевого, —
// иначе счёт в долларах прочитается как результат стратегии.
function renderPretest(p, modeBtns) {
  const box = document.getElementById("modelbox");
  const cap = document.getElementById("cap-model");
  const m = p.manifest || {}, rd = p.readiness || {}, lr = p.last_run || {};
  cap.textContent = "PRE-TESTING · not a result";
  const warn = `<div class="mline" style="border-left:3px solid #b58900;
      padding-left:8px"><b>Pre-testing.</b> Same pipeline, but trained on
    the few days recorded so far and with the market hedge OFF — beta
    needs ${rd.beta_min_hours ?? 96} h of history and there are
    ${rd.hours_per_symbol ?? "—"}. So this book is <b>directional</b>: it
    rides the market, not just the signal. Numbers here show that
    training runs, not that anything works. The real model trains
    separately and is untouched.${
      m.canary_spread > 0.05 ? ` Leak check is weak at this sample size
      (spread ±${m.canary_spread} across ${m.canary_seeds} seeds vs a
      0.05 threshold) — it would catch a gross leak, not a subtle one.`
      : ""}</div>`;
  if (!p.present) {
    box.innerHTML = modeBtns + warn + `<div class="mline">no cycle has
      completed yet${lr.reason ? " — last run: " + lr.reason : ""}.</div>`;
    wireModes();
    return;
  }
  const ageH = m.trained_at
    ? Math.max(0, (Date.now()/1000 - new Date(m.trained_at).getTime()/1000)
               / 3600) : null;
  const accs = p.accounts || {};
  const accLine = ["gbm","nn"].map(a => accs[a]
    ? `${a === "gbm" ? "trees" : "neural"} $${accs[a].balance.toFixed(2)}`
    : null).filter(Boolean).join(" · ");
  const ic = {};
  (p.ic || []).forEach(r => { ic[(r.arm || "gbm") + ":" + r.target] = r; });
  const icLine = ["gbm","nn"].map(a => {
    const s = ["fwd_1h","fwd_4h","fwd_24h"].map(t => {
      const r = ic[a + ":" + t];
      return r ? `${t.replace("fwd_","")} ${r.median_ic > 0 ? "+" : ""}${
        r.median_ic}` : null; }).filter(Boolean).join(" ");
    return s ? `${a === "gbm" ? "trees" : "neural"}: ${s}` : null;
  }).filter(Boolean).join(" · ");
  box.innerHTML = modeBtns + warn
    + `<div class="mline">weights v${m.version} · age ${
        ageH == null ? "—" : ageH.toFixed(1)} h · trained on ${
        m.sections ?? "—"} sections, ${m.symbols ?? "—"} coins · hedge ${
        m.hedge || "?"}${accLine ? " · paper " + accLine : ""}</div>`
    + (icLine ? `<div class="mline">out-of-sample IC — ${icLine}</div>` : "")
    + tradeStats(p) + equityBlock(p) + tradeTable(p)
    + `<div class="mline"><a href="/trades-page?k=${
        encodeURIComponent(KEY)}">full trade history, paged &rarr;</a>
       </div>`
    + (p.thoughts || []).slice(-6).map(t =>
        `<div class="mline dim">${t.text}</div>`).join("");
  wireModes();
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
function tradeStats(p) {
  const st = p.trade_stats || {};
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  return ["gbm","nn"].map(a => {
    const s = st[a]; if (!s) return "";
    const name = a === "gbm" ? "trees" : "neural";
    if (!s.closed) return `<div class="mline">${name}: ${s.open || 0}
      open, none closed yet — first outcomes in ~4 h.</div>`;
    // «Обещание / факт» — самое честное число здесь: модель может
    // угадывать знак и обещать вчетверо больше, чем даёт.
    return `<div class="mline"><b>${name}</b></div><div class="stats">`
      + cell("closed", s.closed)
      + cell("open", s.open)
      + cell("sign right", (s.hit_rate*100).toFixed(0) + " %",
             s.hit_rate >= 0.5 ? "good" : "bad")
      + cell("net move", pct(s.net_bp_avg),
             s.net_bp_avg > 0 ? "good" : "bad")
      + cell("paper P&L, $", s.pnl, s.pnl > 0 ? "good" : "bad")
      + cell("promise / actual", s.expected_over_got ?? "—",
             s.expected_over_got > 3 ? "bad" : "")
      + (s.awaiting ? cell("awaiting", s.awaiting) : "")
      + (s.no_outcome ? cell("no outcome", s.no_outcome, "bad") : "")
      + `</div>`;
  }).join("");
}

// Кривая счёта: рисуется из истории самого счёта, а не пересчитывается
// по сделкам — иначе график и баланс однажды разойдутся.
function equityBlock(p) {
  const accs = p.accounts || {};
  const series = ["gbm","nn"].map(a => (accs[a]||{}).history || [])
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
function tradeTable(p) {
  const tr = p.trades || [];
  if (!tr.length) return `<div class="mline">no model trades yet —
    the first cycle writes picks, outcomes arrive 4 h later.</div>`;
  const SHOW = 60;
  const rows = tr.slice(0, SHOW).map(t => {
    const cls = t.state === "закрыта"
      ? ((t.net_bp > 0) ? "good" : "bad")
      : (t.state === "открыта" ? "" : "dim");
    const when = t.state === "открыта"
      ? `in ${(t.closes_in_sec/3600).toFixed(1)} h`
      : (t.state === "закрыта" ? "closed"
         : t.state === "ждёт разбора" ? "awaiting" : "no outcome");
    return `<tr class="${cls}">
      <td class="mono">${t.hour.slice(5)}</td>
      <td>${t.arm === "nn" ? "neu" : "tre"}</td>
      <td class="mono">${t.sym.replace("USDT","")}</td>
      <td>${t.side === "long" ? "L" : "S"}</td>
      <td class="mono">${pct(t.expected_bp)}</td>
      <td class="mono dim">${pct(t.mae_bp)}</td>
      <td class="mono">${pct(t.got_bp)}</td>
      <td class="mono">${t.pnl == null ? "—" :
        (t.pnl > 0 ? "+" : "") + t.pnl.toFixed(2)}</td>
      <td class="dim">${when}</td></tr>`;
  }).join("");
  return `<div class="mline">model trades <span class="dim">(exp —
    expected move; mae — expected move <b>against</b> the position
    on the way; got — what actually happened. % of price, over 4 h)
    </span></div>
    <div style="overflow-x:auto"><table class="mtr">
    <tr><th>hour</th><th>arm</th><th>coin</th><th>side</th><th>exp</th>
    <th>mae</th><th>got</th><th>$</th><th>state</th></tr>
    ${rows}</table></div>`
    + (tr.length > SHOW ? `<div class="mline dim">showing ${SHOW} of ${
        p.trades_total ?? tr.length} — older ones are on disk</div>` : "");
}

function renderModel() {
  const box = document.getElementById("modelbox"), d = MDL.data;
  const cap = document.getElementById("cap-model");
  if (!d) { box.textContent = "…"; return; }
  // Предпросмотр — ОТДЕЛЬНАЯ вкладка, а не подмешанные строки. Это
  // другая модель на другой посылке: хедж выключен, история — дни.
  // Слить их в одну картинку значило бы однажды прочитать её счёт как
  // счёт боевой.
  const hasPre = !!(d.pretest &&
                    (d.pretest.present || d.pretest.readiness));
  const modeBtns = hasPre ? `<div style="margin-bottom:6px">` +
    [["live","model"],["pretest","pre-testing"]].map(x =>
      `<button data-mode="${x[0]}" aria-pressed="${
        String((MDL.mode||"live") === x[0])}">${x[1]}</button>`).join(" ")
    + `</div>` : "";
  if ((MDL.mode || "live") === "pretest" && hasPre) {
    return renderPretest(d.pretest, modeBtns);
  }
  const armBtns = modeBtns + `<div style="margin-bottom:6px">` +
    [["all","both"],["gbm","trees (ML)"],["nn","neural (AI)"]].map(x =>
      `<button data-arm="${x[0]}" aria-pressed="${
        String(MDL.arm === x[0])}">${x[1]}</button>`).join(" ") + `</div>`;
  const wireArms = () => { wireModes();
    box.querySelectorAll("[data-arm]").forEach(b =>
      b.onclick = () => { MDL.arm = b.dataset.arm; renderModel(); }); };
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
    box.innerHTML = armBtns + `<div class="mline">two models will train
      here — trees (ML) vs neural net (AI) — once 48 closed hourly
      cross-sections accumulate (~2 days of full-list recording).</div>`
      + prog;
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
  cap.textContent = `weights v${m.version} · age ${
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
  box.innerHTML = armBtns + `<div class="mline">trained on ${m.sections ?? "—"}
      cross-sections, ${m.symbols ?? "—"} coins · noise check ${
      m.canary_ic == null ? "—" : "clean (" + m.canary_ic + ")"}${
      icLine ? " · out-of-sample IC: " + icLine
             : ""}</div>
    ${picksTable(d)}
    <div class="thoughts">${(d.thoughts || []).slice().reverse()
      .filter(t => MDL.arm === "all"
        || (MDL.arm === "gbm" ? /^\[деревья\]/ : /^\[сеть\]/)
             .test(t.text || ""))
      .map(t =>
      `<span class="tt">[${t.at || ""}]</span> ${t.text}`).join("\n")
      || "no thoughts yet — they appear after the first training"}</div>`;
  wireArms();
}
function picksTable(d) {
  // Турнир: у каждой руки свои выборы и свой разбор. Смешение рук в
  // одной таблице выглядело бы осмысленно и не значило бы ничего.
  const arms = {};
  (d.picks || []).forEach(p => { arms[p.arm || "gbm"] = p; });
  const revs = {};
  (d.review || []).forEach(r => { revs[r.arm || "gbm"] = r; });
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
          bp / 4h</td>
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
function recReady() {
  return REC.data && !REC.data.busy && REC.data.stats !== undefined
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
    const head = (me ? "<b>правила v" + x.ver + " (сейчас)</b>"
                     : "правила v" + x.ver);
    return head + ": " + (s
      ? `${s.trades} сд., побед ${pc(s.win_rate)} при безубыточных `
        + `${pc(s.break_even)}, ожидание ${pct(s.expectancy_bp)}, `
        + `стоп ${pct(s.stop_bp_median)}`
      : `${x.n} сд., закрытых нет`);
  }).join("<br>");
}

function bookRows(b) {
  const cell = (v, need, ok) => v === null || v === undefined
    ? `<td class="mono" style="color:var(--muted)">—</td>`
    : `<td class="mono ${ok ? "buy" : "sell"}">${v}${need}</td>`;
  const rows = ["лонг", "шорт"].map(k => {
    const m = b[k] || {};
    return `<tr><td>стакан: ${k} у крупного</td>
      ${cell(m.gate_x, "× порога", m.gate_x >= 1)}
      ${cell(m.held, " с", m.held >= (b.hold || 10))}
      ${cell(m.eaten_x, "× съедено", m.eaten_x >= (b.eat || 1))}
      <td class="mono" style="color:var(--muted)">${m.why || "—"}</td></tr>`;
  }).join("");
  // Докуда цепочка дошла за жизнь процесса. Без этой строки «правило
  // молчит» неотличимо от «правило молчит вот на этом условии», а
  // чинится только второе.
  const c = b.chain || {};
  const named = ["ни разу не крупный", "крупный был",
                 "выстаивал", "выедали"][c.stage || 0];
  return rows + `<tr><td>стакан: докуда доходило</td>
    <td class="mono" colspan="3">${named}${c.eat_n
      ? `, выедание по ${c.eat_n} замерам: медиана ${c.eat_med}×, `
        + `максимум ${c.eat_max}× при нужных ${b.eat || 1}`
      : ""}</td>
    <td class="mono" style="color:var(--muted)">гейт ${
      ((1 - (b.qbig || 0.98)) * 100).toFixed(0)}% времени</td></tr>`;
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
    pct((pts[pts.length-1][1]/pts[0][1]-1)*1e4) + " за окно";
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
:root{color-scheme:light dark;
 --bg:#fbfcfd;--panel:#fff;--ink:#12161c;--muted:#6b7785;--rule:#e3e8ee;
 --bid:#1f7a56;--ask:#b8452c;--accent:#a97514}
@media(prefers-color-scheme:dark){:root{
 --bg:#0e1116;--panel:#151a21;--ink:#e7edf5;--muted:#8b97a6;--rule:#232b36;
 --bid:#35a877;--ask:#d4614a;--accent:#d7a24a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:14px 12px 40px}
h1{font-size:16px;margin:0 0 4px}
a{color:var(--accent)}
.card{background:var(--panel);border:1px solid var(--rule);
 border-radius:10px;padding:10px 12px;margin-bottom:12px}
.note{color:var(--muted);font-size:12px;margin-bottom:8px}
.warn{border-left:3px solid var(--accent);padding-left:9px;
 color:var(--muted);font-size:12px;margin-bottom:10px}
.stats{display:flex;flex-wrap:wrap;gap:1px;background:var(--rule);
 border-radius:8px;overflow:hidden}
.st{flex:1 1 120px;background:var(--panel);padding:8px 10px}
.k{color:var(--muted);font-size:11px}
.v{font-size:15px;font-variant-numeric:tabular-nums}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.good{color:var(--bid)} .bad{color:var(--ask)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--muted);font-weight:400;
 padding:4px 8px 5px 0;border-bottom:1px solid var(--rule);
 position:sticky;top:0;background:var(--panel)}
td{padding:3px 8px 3px 0;white-space:nowrap;
 border-bottom:1px solid var(--rule)}
button,select{background:var(--panel);color:var(--ink);
 border:1px solid var(--rule);border-radius:7px;padding:4px 10px;
 font:inherit;font-size:12px}
button[aria-pressed=true]{border-color:var(--accent)}
button:disabled{opacity:.4}
.bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;
 margin-bottom:8px}
.scroll{overflow-x:auto}
</style>
<div class="wrap">
  <h1>model trades · <span id="src" class="mono"></span></h1>
  <div class="note"><a href="#" id="back">&larr; overview</a></div>
  <div id="warn"></div>

  <div class="card">
    <div class="note">All clock times are <b>Europe/Vienna</b>; the
      underlying keys are UTC and show on hover.</div>
    <div class="note">How to read a row. <b>signal hour</b> — the hour
      whose <b>close</b> the decision is based on: features cover the
      whole hour, so nothing can be entered before it ends.
      <b>entry</b> is that close, <b>exit</b> is 4 h later — exactly how
      the target is defined. <b>lag</b> is how late the training loop
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
      <b>dd</b> is the <b>realised</b> drawdown: the worst the position
      was actually down while it was held, taken from the hourly
      high/low of the book mid — so <b>mae</b> is the promise and
      <b>dd</b> is what the promise cost. A trade that closed in profit
      can still have been 40 % down on the way, and <b>net</b> alone
      never shows that.
      <b>unseen</b> — share of this coin&#39;s features that fell
      outside the range the model saw while training: 0 % means fully
      familiar, high means the coin is in a state the model has never
      seen, so its forecast is worth less. It is a <b>measurement, not
      a filter</b> — any &laquo;don&#39;t trade the unfamiliar&raquo;
      rule mechanically flatters drawdown, and may only be introduced
      after comparing it with a random gate of the same frequency.</div>
    <div class="note">overall stats below are computed over the
      <b>whole</b> history; filters do not move them</div>
    <div id="stats"></div>
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
    </div>
    <div class="scroll"><table>
      <thead><tr><th>signal hour</th><th>entry</th><th>exit</th>
        <th>lag</th><th>arm</th><th>coin</th><th>side</th><th>exp</th>
        <th>mae</th><th>got</th><th>net</th><th>unreal</th><th>dd</th>
        <th>$</th><th>state</th><th>unseen</th>
      </tr></thead><tbody id="tb"></tbody>
    </table></div>
  </div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("back").href = "/?k=" + encodeURIComponent(KEY);
const S = {page: 0};
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
               "без исхода": "no outcome", "ждёт разбора": "awaiting"};
const val = id => document.getElementById(id).value;
async function load() {
  const p = new URLSearchParams({k: KEY, page: S.page, per: val("per"),
                                 arm: val("arm"), state: val("state"),
                                 sym: val("sym")});
  let d;
  try {
    const r = await fetch("/model_trades?" + p.toString());
    d = await r.json();
  } catch (e) {
    document.getElementById("cnt").textContent = "no link to collector";
    return;
  }
  document.getElementById("src").textContent = d.pretest
    ? "pre-testing" : "live model";
  document.getElementById("warn").innerHTML = d.pretest
    ? `<div class="warn"><b>Pre-testing.</b> Trained on the first days
       of recording and with the market hedge <b>OFF</b>, so this book is
       <b>directional</b> — it rides the market, not just the signal.
       These numbers show that training runs, not that it earns.</div>`
    : "";
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
  let html = armBtns + `<div class="stats">`
    + cell("trades", which === "all" ? d.grand_total
           : (st.closed||0) + (st.open||0) + (st.awaiting||0)
             + (st.no_outcome||0))
    + cell("closed", st.closed || 0)
    + cell("open", st.open || 0)
    + (st.awaiting ? cell("awaiting review", st.awaiting) : "")
    // Красным — только окончательная потеря: разбор до неё дошёл и
    // цель посчитать не смог. Ожидание разбора красным быть не должно,
    // иначе тревога станет фоном и её перестанут читать.
    + (st.no_outcome ? cell("no outcome", st.no_outcome, "bad") : "");
  if (st.closed) {
    html += cell("sign right", (st.hit_rate*100).toFixed(0) + " %",
                 st.hit_rate >= 0.5 ? "good" : "bad")
      + cell("net move, avg", pct(st.net_bp_avg),
             st.net_bp_avg > 0 ? "good" : "bad")
      + cell("realised P&L", (st.pnl > 0 ? "+" : "") + st.pnl + " $",
             st.pnl > 0 ? "good" : "bad")
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
    html += `<div class="note" style="margin-top:8px">open positions,
      marked to market <span class="k">(not a result yet)</span></div>
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
      + (st.leverage == null ? "" :
         cell("leverage", st.leverage + "×",
              st.leverage > 1.05 ? "bad" : ""))
      + `</div>`;
  }
  // Просадка — отдельным рядом, потому что она отвечает на вопрос, на
  // который итог сделки не отвечает вовсе: сколько позиция была в
  // минусе ПО ДОРОГЕ. Сделка, закрывшаяся в плюс, могла по пути стоить
  // −40 %, и по колонке `net` этого не видно.
  if (st.dd_measured || st.dd_book) {
    const b = st.dd_book || {};
    html += `<div class="note" style="margin-top:8px">drawdown
      <span class="k">(worst move against the position while it was
      held; measured from hourly high/low of the book mid, so it is a
      <b>lower</b> bound — moves inside a second are not in the
      snapshots)</span></div>
      <div class="stats">`
      + (st.dd_worst_bp == null ? "" :
         cell("worst trade", pct(st.dd_worst_bp),
              st.dd_worst_bp < -200 ? "bad" : ""))
      + (st.dd_med_bp == null ? "" :
         cell("median trade", pct(st.dd_med_bp)))
      + (st.dd_open_worst_bp == null ? "" :
         cell("worst open now", pct(st.dd_open_worst_bp),
              st.dd_open_worst_bp < -200 ? "bad" : ""))
      // Просадка счёта считается по кривой с переоценкой открытых. По
      // одним закрытиям она была бы систематически мельче пережитой.
      + (b.pct == null ? "" :
         cell("account, peak to trough", b.pct + " %",
              b.pct < -10 ? "bad" : ""))
      + (b.at ? cell("deepest at", hourLocal(b.at)) : "")
      + (st.dd_measured == null ? "" :
         cell("trades measured", st.dd_measured))
      // Час, где живую ногу переоценить было нечем, делает просадку
      // счёта заниженной. Молчать об этом нельзя — это ровно тот класс
      // дефекта, где пустота выдаёт себя за результат.
      + (b.gaps ? cell("hours with a gap", b.gaps, "bad") : "")
      + `</div>`;
  }
  const accLine = ["gbm","nn"].map(a => {
    const x = (d.accounts||{})[a];
    return x ? `${a === "gbm" ? "ml" : "ai"} ${x.balance} $` : null;
  }).filter(Boolean).join(" · ");
  if (accLine)
    html += `<div class="note" style="margin-top:8px">paper accounts: ${
      accLine} <span class="k">(start 1000 $ each, one capital,
      leverage 1&times;)</span></div>`;
  document.getElementById("stats").innerHTML = html;
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
  document.getElementById("tb").innerHTML = (d.rows||[]).map(t => {
    const cls = t.state === "закрыта"
      ? (t.net_bp > 0 ? "good" : "bad") : "";
    return `<tr><td class="mono" title="UTC key ${t.hour}">${
        hourLocal(t.hour)}</td>
      <td class="mono">${hhmm(t.opened_at)}</td>
      <td class="mono">${hhmm(t.closes_at)}</td>
      <td class="mono" style="color:var(--muted)">${t.lag_sec == null
        ? "—" : Math.round(t.lag_sec/60) + "m"}</td>
      <td>${t.arm === "nn" ? "neural" : "trees"}</td>
      <td class="mono">${t.sym.replace("USDT","")}</td>
      <td>${t.side === "long" ? "L" : "S"}</td>
      <td class="mono">${pct(t.expected_bp)}</td>
      <td class="mono" style="color:var(--muted)">${pct(t.mae_bp)}</td>
      <td class="mono">${pct(t.got_bp)}</td>
      <td class="mono ${cls}">${pct(t.net_bp)}</td>
      <td class="mono ${t.unreal_net_bp == null ? "" :
          (t.unreal_net_bp > 0 ? "good" : "bad")}"
          data-mk="${t.arm}|${t.hour}|${t.sym}|${t.side}">${
          pct(t.unreal_net_bp)}</td>
      <td class="mono ${t.dd_bp < -200 ? "bad" : ""}"
          title="${t.dd_hours == null ? ""
            : t.dd_hours + " h of the hold covered by summaries"}">${
          t.dd_bp == null ? "—" : pct(t.dd_bp)}</td>
      <td class="mono ${cls}">${t.pnl == null ? "—"
        : (t.pnl > 0 ? "+" : "") + t.pnl.toFixed(2)}</td>
      <td style="color:var(--muted)">${ST_EN[t.state] || t.state}${
        t.state === "открыта"
        ? ` <span class="k">(${(t.closes_in_sec/3600).toFixed(1)} h
            left)</span>` : ""}</td>
      <td class="mono" style="color:var(--muted)">${t.odd == null ? "—"
        : (t.odd*100).toFixed(0) + " %"}</td></tr>`;
  }).join("") || `<tr><td colspan="15" style="color:var(--muted);
    padding:10px 0">no trades yet</td></tr>`;
  document.getElementById("pg").textContent =
    `page ${d.page + 1} of ${d.pages}`;
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


CHART = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chart живьём</title>
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
  <a class="btn" href="/" id="home">overview</a>
</div>
<div id="recnote"></div>
<div class="panel">
  <div class="cap"><span id="cap">минутные candles · тяните, колесо или щипок — масштаб</span>
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
  <div id="rules"></div>
  <canvas id="eq"></canvas>
</div>
<div class="panel">
  <div class="cap"><span>история сделок — бумажные, наблюдение</span>
    <span id="cap3" class="mono"></span></div>
  <div class="hist"><table><thead><tr>
    <th>время</th><th>сторона</th><th>вход</th><th>стоп</th><th>цель</th>
    <th>правило</th><th>уровень</th><th>отн.</th><th>состояние</th>
    <th>держали</th><th>итог</th>
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
const HIST = {trades:[], stats:null, by_rule:{}, by_ver:[], equity:[],
              at:0, busy:false};
// История свечей с диска: в памяти сборщика живут считанные часы, а
// trades поднимаются за трое суток — график обрывался там, где кончался
// буфер, и прошлые trades смотреть было не на чем. Тянется один раз на
// символ, живые candles ложатся поверх.
const HC = {sym:"", cand:[], busy:false, hours:24};
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
                  HC.sym=""; HC.cand=[]; REC.data=null; REC.sym=""; }

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
  renderRec(); draw(); rows(); summary();
}

// Пересчёт годен к показу, только когда он досчитан и посчитан по ЭТОЙ
// монете: чужой список сделок на чужом графике выглядел бы как trades,
// которых не было.
function recReady() {
  return REC.data && !REC.data.busy && REC.sym === sym
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
    box.innerHTML = `<div class="panel"><div class="note">пересчитываю те же
      входы под текущие правила${d ? `: ${d.done} of ${d.total} coins` : ""}…
      </div></div>`;
    return;
  }
  box.innerHTML = `<div class="panel"><div class="note">`
    + (d.stale ? `<b style="color:var(--ask)">replay computed under rules
        v${d.ver}, current is v${d.now_ver}</b> — refresh to recompute.<br>` : "") + `
    <b>replay</b> — the page shows NOT actual outcomes but the same
    entries run under rules v${d.ver} (window ${d.hours} h, took
    ${d.took_sec} s). Same price path, different trade: stop and target
    пересчитаны, значит и выход другой. Входов по этой монете взято
    ${d.made}, отвергнуто новой геометрией ${d.refused}.
    <br>График, таблица и сводка показывают ТОЛЬКО пересчёт: что было
    на самом деле, видно при выключенном переключателе.`
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

async function pullHistory(s) {
  if (HC.busy || HC.sym === s) return;
  HC.busy = true;
  try {
    const r = await fetch(`/candles?k=${encodeURIComponent(KEY)}&sym=${s}`
      + `&hours=${HC.hours}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    if (h.sym === s) { HC.cand = h.candles || []; HC.sym = s; draw(); }
  } catch (e) { /* тихо: живые candles всё равно рисуются */ }
  finally { HC.busy = false; }
}
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
const MDL = {trades: [], at: 0, busy: false, pretest: false};
async function pullModelTrades() {
  if (MDL.busy || Date.now() - MDL.at < 60000) return;
  MDL.busy = true;
  try {
    const r = await fetch(`/model?k=${encodeURIComponent(KEY)}`);
    const d = await r.json();
    // Предпросмотр показываем, если он есть: боевая модель молчит до
    // накопления истории, и пустой слой читался бы как поломка.
    const src = (d.pretest && (d.pretest.trades||[]).length) ? d.pretest : d;
    MDL.pretest = src === d.pretest;
    MDL.trades = (src.trades || []).filter(t => t.sym === sym);
    MDL.at = Date.now();
  } catch (e) { /* тихо: следующий круг попробует снова */ }
  finally { MDL.busy = false; }
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
  pullHistory(d.sym);
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
  return mergeCandles(HC.cand, live);
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
    g.fillText("копим историю — candles появятся через пару минут", 12, H/2);
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
  const pad=(hi-lo)*0.06||1e-9; lo-=pad; hi+=pad;
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
  // Слой сделок модели: вход — треугольник на своём часе, срок
  // закрытия — пунктир. Форма и цвет иные, чем у детектора, чтобы два
  // механизма нельзя было спутать глазами.
  for (const t of MDL.trades) {
    if (!t.opened_at || t.opened_at < t0 - 3600 || t.opened_at > t1 + 3600)
      continue;
    const xa = xt(t.opened_at);
    const up = t.side === "long";
    const col = t.state === "закрыта"
      ? ((t.net_bp || 0) > 0 ? css("--bid") : css("--ask"))
      : css("--accent");
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1.5;
    const yb = up ? H - padB - 8 : padT + 8;
    g.beginPath();
    g.moveTo(xa, yb + (up ? -9 : 9));
    g.lineTo(xa - 5, yb); g.lineTo(xa + 5, yb); g.closePath();
    if (t.state === "закрыта") g.fill(); else g.stroke();
    if (t.closes_at && t.closes_at <= t1 + 3600) {
      g.setLineDash([3,3]);
      g.beginPath(); g.moveTo(xa, yb); g.lineTo(xt(t.closes_at), yb);
      g.stroke(); g.setLineDash([]);
    }
    HIT.push({mdl: t, x0: xa-7, x1: xa+7, y0: yb-11, y1: yb+11});
  }
  g.fillStyle = css("--muted"); g.textBaseline="alphabetic";
  g.fillText(stamp(t0), padL, H-6);
  g.textAlign="right"; g.fillText(stamp(t1), W-padR, H-6); g.textAlign="left";
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
    `${tr.length} сделок` + (S.rec ? " · replayed, not actual" : "")
    + (S.rec && recReady() && recReady().no_outcome
       ? ` · ${tr.filter(m => m.state === "не открыта").length} входов `
         + `правило не взяло (полый треугольник)` : "")
    + (off ? ` · ${off} вне окна графика` : "")
    + (old ? ` · ${old} по прежним правилам` : "")
    + (MDL.trades.length
       ? ` · ${MDL.trades.length} сделок модели`
         + (MDL.pretest ? " (pre-testing)" : "") : "");
}

function rows() {
  const tr = shownTrades(), c = cands();
  const first = c.length ? c[0][0] : 0, last = c.length ? c[c.length-1][0] : 0;
  const off = m => c.length && (m.t < first || m.t > last);
  document.getElementById("rows").innerHTML = tr.length ? tr.map(m => `
    <tr ${off(m) ? 'style="opacity:.55" title="вне окна графика — '
                 + 'свеча за это время уже не хранится"' : ""}>
    <td class="mono">${stamp(m.t)}${off(m) ? " ·" : ""}</td>
    <td class="${m.long?"buy":"sell"}">${m.long?"лонг":"шорт"}</td>
    <td class="mono">${m.entry}</td><td class="mono">${m.stop ?? "—"}</td>
    <td class="mono">${m.target ?? "—"}</td>
    <td>${m.rule || "лента"}</td>
    <td style="color:var(--muted)">${m.kind}</td>
    <td class="mono">${m.rr == null ? "—" : "1:" + m.rr}</td>
    <td title="${m.why || ""}">${m.state}</td>
    <td class="mono">${m.held == null ? "—" : m.held + " с"}</td>
    <td class="mono">${res(m)}</td></tr>`
  ).join("") : `<tr><td colspan="11" style="color:var(--muted)">
    no events yet — detector waits for conditions</td></tr>`;
}

function verLine(list, cur) {
  // По версиям правил рядом: смешивать их нельзя, но и прятать прежние
  // незачем — выборка текущей всегда мала, и без соседних строк
  // непонятно, стало лучше или просто сделок мало.
  if (!list || !list.length) return "";
  const pc = v => (v*100).toFixed(0) + " %";
  return list.map(x => {
    const s = x.stats, me = x.ver === cur;
    const head = (me ? "<b>правила v" + x.ver + " (сейчас)</b>"
                     : "правила v" + x.ver);
    return head + ": " + (s
      ? `${s.trades} сд., побед ${pc(s.win_rate)} при безубыточных `
        + `${pc(s.break_even)}, ожидание ${pct(s.expectancy_bp)}, `
        + `стоп ${pct(s.stop_bp_median)}`
      : `${x.n} сд., закрытых нет`);
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
      cell("медиана", pct(s.median_bp)) +
      cell("стоп", pct(s.stop_bp_median)) +
      cell("target / stop / time",
           `${pc(s.share_target)} / ${pc(s.share_stop)} / ${pc(s.share_time)}`) +
      (s.cut_by_restart
        ? cell("оборвано", s.cut_by_restart, "sell") : "");
  }
  // По правилам отдельно: «лента» — то же, что мерили T3 и T4, и она
  // здесь контрольная рука. Сравнивать новое правило надо с ней на
  // одном периоде, а не с числами старого отчёта.
  const br = S.by_rule || {};
  const line = Object.keys(br).map(r => {
    const x = br[r];
    return x ? `<b>${r}</b>: ${x.trades} сд., побед ${
      (x.win_rate*100).toFixed(0)} % при безубыточных ${
      (x.break_even*100).toFixed(0)} %, ожидание ${
      pct(x.expectancy_bp)} (${
      x.expectancy_r > 0 ? "+" : ""}${x.expectancy_r.toFixed(2)} R)`
      : `<b>${r}</b>: no trades`;
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
  // Кривая счёта: в R либо в процентах движения цены.
  // В R — как есть; в процентах — величина хранится в б.п., поэтому
  // делится сотней тем же правилом, что и везде.
  g.fillText(EQR ? hi.toFixed(1) + " R" : pct(hi), W-60, y(hi));
  g.fillText(EQR ? lo.toFixed(1) + " R" : pct(lo), W-60, y(lo));
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
        модель${MDL.pretest ? " (pre-testing)" : ""} · ${
        t.side === "long" ? "лонг" : "шорт"} · ${t.state}</div>`
      + row("рука", t.arm === "nn" ? "сеть (AI)" : "деревья (ML)")
      + row("час сигнала", t.hour)
      + row("вход", new Date(t.opened_at*1000).toISOString().slice(11,16)
            + " UTC" + (t.lag_sec == null ? ""
              : ` (+${Math.round(t.lag_sec/60)} мин)`))
      + row("ждёт", bp(t.expected_bp))
      + row("ход против", bp(t.mae_bp))
      + (t.state === "закрыта"
         ? row("вышло", bp(t.got_bp), (t.got_bp>0)===(t.side==="long")
               ? "buy" : "sell")
           + row("нетто с издержками", bp(t.net_bp),
                 t.net_bp>0?"buy":"sell")
           + row("деньги", (t.pnl>0?"+":"") + t.pnl + " $",
                 t.pnl>0?"buy":"sell")
         : t.state === "открыта"
           ? row("закроется через",
                 (t.closes_in_sec/3600).toFixed(1) + " ч")
           : row("исхода нет", "час ещё не сведён"));
    tip.style.display="block";
    tip.style.left = Math.max(4, Math.min(px.clientWidth-tip.offsetWidth-4,
                                          mx+14))+"px";
    tip.style.top = Math.max(4, my+18)+"px";
    return;
  }
  const m = h.m;
  tip.innerHTML = `<div style="font-weight:650;margin-bottom:3px">${
      m.long?"лонг":"шорт"} · ${m.state}</div>`
    + row("время", stamp(m.t)) + row("вход", m.entry)
    + (m.state === "не открыта" ? row("почему", m.why || "правило не берёт")
       : row("стоп", m.stop) + row("цель", m.target))
    + row("уровень", `${m.level} (${m.kind})`)
    + row("отношение", "1:"+m.rr) + row("держали", m.held+" с")
    + row("итог", `${pct(m.pnl_bp)} · ${
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
  EQR = !EQR; e.target.textContent = EQR ? "в %" : "в R"; drawEq();
};
// Тумблера нет: вид один — всё под нынешними правилами.
localStorage.removeItem("rec");
window.addEventListener("resize", () => { draw(); drawEq(); });
pull(); setInterval(pull, 1000);
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
                return self._ok(json.dumps(
                    collector.candles_files(q.get("sym", [None])[0], n),
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
            if u.path == "/model":
                return self._ok(json.dumps(
                    collector.model_state(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/model_trades":
                def ival(name, default):
                    try:
                        return int(float(q.get(name, [""])[0]))
                    except ValueError:
                        return default
                pre = q.get("pretest", [None])[0]
                return self._ok(json.dumps(
                    collector.model_trades(
                        page=ival("page", 0), per=ival("per", 100),
                        arm=q.get("arm", [None])[0] or None,
                        state=q.get("state", [None])[0] or None,
                        sym=q.get("sym", [None])[0] or None,
                        pretest=(None if pre is None
                                 else pre not in ("0", "false", ""))),
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
