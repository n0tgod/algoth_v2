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
import os
import sys
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "s8_loop"))
import books as BK                                        # noqa: E402

# Меню страниц — просьба владельца: все страницы в одном месте, чтобы
# переключаться, не возвращаясь на обзор. Список объявлен ОДИН раз и
# вставляется во все страницы: пять копий разошлись бы, и новая
# страница появлялась бы в меню через раз.
#
# Что в меню не входит и почему: график (`/chart`) существует только
# для конкретной монеты и часа, а пункт меню без них вёл бы в пустоту;
# разбор сделки (`/trade-info`) — то же самое. Оба открываются со
# своих мест, где монета известна.
PCTJS = r"""
function pct(v) {
  if (v == null) return "\u2014";
  const d = Math.abs(v) >= 10 ? 2 : 3;
  return (v > 0 ? "+" : "") + (v / 100).toFixed(d) + " %";
}
"""

# Величина БЕЗЗНАКОВАЯ: порог, издержка, граница корзины — это
# настройка, а не движение цены, и «+0.22 %» у неё читалось бы как
# прибыль. Знак решает вид величины, поэтому это ОТДЕЛЬНОЕ решение,
# а не вторая копия `pct`. Две расходящиеся копии `lvl` уже жили на
# странице живого исполнения и на листе турнира — одна из них
# печатала два знака всегда, другая три у мелких величин.
LVLJS = r"""
function lvl(v) {
  if (v == null) return "\u2014";
  const d = Math.abs(v) >= 10 ? 2 : 3;
  return (v / 100).toFixed(d) + " %";
}
"""

# Причины выхода в ячейках таблиц — коротким словом. Длинная фраза
# («price broke the promised adverse path») переносила ячейку
# состояния на вторую строку, и ряд закрытой сделки распухал —
# владелец увидел это как «таблица поехала на одной сделке». Полная
# причина остаётся в подсказке строки и на странице разбора сделки;
# карта ОДНА на все таблицы — копии уже завелись трижды и разошлись
# бы.
EXITJS = r"""
const EXIT_EN = {"прогноз развернулся": "flip",
                 "цена прошла обещанный ход против": "stop",
                 "цена дошла до обещанной цели": "target",
                 "предел возраста": "age",
                 "встречный сигнал закрыл позицию": "netted",
                 "корзина дошла до цели": "basket",
                 "корзина дошла до предела убытка": "basket floor",
                 "корзина дошла до предела возраста": "basket age"};
"""

# Книги: ключ и подпись, СОБРАНЫ ИЗ РЕЕСТРА (`s8_loop/books.py`), а не
# записаны здесь. Список жил восемью копиями, и книга в единицах σ
# доехала до пяти: страница сделок молча показывала главную книгу под
# именем выбранной, сводка собирала каталог соглашением, лига звала
# книги своими ярлыками. Подписи говорят, ЧТО за книга, а не как
# называется каталог; порядок реестра и есть порядок кнопок.
# Собирается на импорте: страница отдаёт ЯДРО, а кандидаты фабрики
# (`in_menu` у них выключено) кнопками не становятся — ряд из сотни
# кнопок показом не является.
BOOKJS = (
    "\nconst BOOK_LIST = "
    + json.dumps([list(x) for x in BK.menu()]) + ";\n"
    # Ключ книги из адреса проверяется ПО ФОРМЕ, а существование
    # решает сервер. Прежде страница держала список законных ключей
    # (`BK.addressable()`), собранный на импорте, — и с появлением
    # книг фабрики он стал вторым списком книг: кандидат объявляется
    # каждый час, страница о нём не знает до перезапуска, ключ
    # отбрасывается как чужой, и ссылка МОЛЧА открывает главную книгу.
    # Ровно этот отказ уже трижды случался с каталогом книги. Форма
    # проверяется здесь потому, что ключ уезжает и в адрес, и в путь
    # на диске; чего не существует — называет сервер словами.
    + "function hzOf(v){return (v && /^[a-z0-9_]+$/.test(v))"
    + " ? v : \"\";}\n")

# Состав меню — решение владельца (2026-08-22): пункт playbook ВЕРНУЛСЯ
# на справочник (перепутал при прошлой просьбе), живой исполнитель занял
# слот панели ядра, а сама панель из меню ушла («достаточно затестили»).
# Страница ядра не удалена: живёт по своему адресу, достижимость держит
# ссылка со страницы живого исполнения — тот же приём, что был у
# справочника, пока из меню уходил он.
NAVJS = r"""
const NAV_ITEMS = [
  ["/", "overview", "обзор"],
  ["/trades-page", "trades", "сделки"],
  ["/league-page", "league", "лига"],
  ["/vol-page", "volatility", "волатильность"],
  ["/learning-page", "learning", "обучение"],
  ["/glossary-page", "playbook", "справочник"],
  ["/tree-page", "models", "модели"],
  ["/tournament-page", "tournament", "турнир"],
  ["/paper-page", "monthly", "месячная"],
  ["/dca-page", "DCA", "DCA"],
  ["/agents-page", "agents", "агенты"],
  ["/asks-page", "needs you", "нужно от вас"],
  ["/built-page", "built", "построено"],
  ["/live-page", "bot live", "бот live"]];
function navMount(current){
  const el = document.getElementById("nav");
  if (!el) return;
  // Ключ несёт КАЖДАЯ ссылка: без него переход роняет доступ, и меню
  // выглядело бы сломанным сервером.
  const key = (typeof KEY === "string" && KEY) ? KEY : "";
  const lang = (typeof LANG === "string" && LANG === "ru") ? 1 : 0;
  el.className = "navbar";
  el.innerHTML = NAV_ITEMS.map(it => {
    const here = it[0] === current;
    const q = "?k=" + encodeURIComponent(key);
    return `<a class="navlink${here ? " on" : ""}" href="${it[0]}${q}"
      ${here ? 'aria-current="page"' : ""}>${it[lang ? 2 : 1]}</a>`;
  }).join("");
}
"""

# Стили меню — тоже один раз: пять копий CSS разъехались бы так же
# незаметно, как разъехался бы список.
NAVCSS = r"""
.navbar{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px}
.navlink{display:inline-block;padding:4px 12px;border-radius:999px;
 font-size:12px;text-decoration:none;border:1px solid #272250;
 background:#1a1636;color:#8e88ad}
.navlink:hover{color:#eceaf6}
.navlink.on{border-color:#9747ff;color:#9747ff}
"""


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
""" + NAVCSS + r"""</style>
<div class="wrap">
<header class="top">
  <span class="brand">ALG<b>O</b>TH</span>
  <span class="tag">order book · live</span>
  <span class="sp"></span>
  <span class="sub" id="sub">connecting…</span>
</header>
<div id="nav"></div>
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
""" + BOOKJS + NAVJS + r"""
navMount("/");
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
        pct((bk.ask-bk.bid)/bk.bid*1e4)} · mid ${
        fmt((bk.ask+bk.bid)/2, 6)}</td></tr>` +
      bk.b.map(r => row(r, "b")).join("");
    document.getElementById("cap-book").textContent =
      `${bk.depth ?? "?"} levels · upd/s ${bk.upd} · reach ±${
        pct(bk.reach_b)}/${pct(bk.reach_a)}`;
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
    : `open ${sg.open.length} · noise ${
      sg.noise_bp == null ? "—" : pct(sg.noise_bp)} · levels ${
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
    // Выключена решением владельца — состояние словами, не «не
    // развёрнуто»: остановленная тень не должна читаться как поломка.
    box.textContent = d && d.off
      ? "shadow stopped by the owner — enough tested, server load "
        + "trimmed; not a failure. The live executor reconciles with "
        + "the exchange itself."
      : "core not running — the shadow is not deployed yet";
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
const BOOKS = BOOK_LIST;
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
""" + PCTJS + r"""

// Сводка по сделкам. Открытые в неё НЕ входят: у них нет исхода, и
// посчитать его нулём значило бы разбавить статистику выдумкой.
function shownArms() {
  return MDL.arm === "all" ? ["gbm", "nn"] : [MDL.arm];
}
function tradeStats(p) {
  const st = p.trade_stats || {};
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  // Открытые деньги — просьба владельца: их не было видно ни у одной
  // руки и ни у одной книги, хотя сервер их считает.
  //
  // Ячейка ОТДЕЛЬНАЯ и с фактом не складывается. У закрытой сделки
  // исход известен, у открытой это лишь текущая отметка, и до выхода
  // она может стать любой; сумма «итого» выдала бы незавершённое за
  // результат — то самое правило, по которому счёт держит закрытые и
  // открытые раздельно.
  //
  // Ноля здесь не бывает по умолчанию: позиция без цены (книга по
  // инструменту молчит) в переоценку не входит, и написать ей ноль
  // значило бы объявить её ровной. Если переоценить нечего — прочерк,
  // а сколько позиций переоценено, стоит рядом числом.
  const openCell = (s) => {
    if (!s.open) return "";
    if (s.unreal_pnl == null)
      return cell("open P&L, $ (mark)", "—"
        + `<span class="k"> ${s.open} open, none priced yet</span>`);
    const part = (s.marked != null && s.marked < s.open)
      ? ` of ${s.marked}/${s.open} priced` : "";
    return cell("open P&L, $ (mark)",
      (s.unreal_pnl > 0 ? "+" : "") + s.unreal_pnl
      + `<span class="k">${s.unreal_net_avg_bp != null
          ? " " + pct(s.unreal_net_avg_bp) + " avg" : ""}${part}</span>`,
      s.unreal_pnl > 0 ? "good" : "bad");
  };
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
    // Книга без единого закрытия — ровно тот случай, где открытые
    // деньги и есть всё, что о ней известно: отметка идёт той же
    // ячейкой, а не теряется до первого исхода.
    if (!s.closed) return `<div class="mline">${name}: ${s.open || 0}
      open, none closed yet — ${isSit(p)
        ? "they close when their situation ends"
        : "first outcomes in ~" + bookH(p) + " h"}.</div>`
      + (s.open ? `<div class="stats">${openCell(s)}</div>` : "");
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
      + openCell(s)
      + cell("promise / actual", s.expected_over_got ?? "—",
             s.expected_over_got > 3 ? "bad" : "")
      + (s.awaiting ? cell("awaiting", s.awaiting) : "")
      + (s.no_outcome ? cell("no outcome", s.no_outcome, "bad") : "")
      // Решения, схлопнувшие встречный лот: позиции по ним не
      // открывалось, и в списке сделок их нет — но число стоит
      // рядом, иначе выбор модели пропадает молча.
      + (s.netted ? cell("netted (no position)", s.netted) : "")
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
      <td class="mono dim">${t.tid ? "#" + t.tid : "\u2014"}</td>
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
      <td class="dim"${t.exit_reason
        ? ` title="${t.exit_reason}"` : ""}>${when}</td>
      <td>${info}</td></tr>`;
  }).join("");
  return `<div class="mline">model trades <span class="dim">(exp —
    expected move; mae — expected move <b>against</b> the position
    on the way; got — what actually happened. % of price, ${isSit(p)
      ? "until the situation exits"
      : "over " + bookH(p) + " h"})</span></div>
    <div style="overflow-x:auto"><table class="mtr">
    <tr><th title="trade id">id</th>
    <th>${isSit(p) ? "entered" : "hour"}</th>
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
""" + EXITJS + r"""
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
       move is at least <b>${pct(m.min_edge_bp)}</b>, reward/risk at
       least <b>${m.min_rr}</b>, and the price has given back
       <b>${pct(m.min_disc_bp ?? 0)}</b> on top of what the sheet
       promised. Without that last one every name the model likes
       would enter in the first tick after the sheet — a batch on the
       cycle clock, not a moment.${m.arm_band_bp
         ? ` And the crossing has to happen <b>in front of us</b>: the
            name must first be seen at least <b>${pct(m.arm_band_bp)}</b>
            away from the trigger. A name found already parked at the
            line is skipped — its next tick is a wobble around a level
            it was standing on, not a move.` : ""}${m.max_eaten != null
         ? ` Two more gates (rules v11): the stop room must survive
            the coin's own <b>live minute noise</b>${m.noise_mult > 1
              ? ` — and this book demands <b>${m.noise_mult}×</b> that
                 noise, not just one (owner's rule after a stop one
                 wick wide)` : ""}, and the price may
            not have eaten more than <b>${Math.round(
              m.max_eaten * 100)} %</b> of the promised adverse path
            before entry — a move against the forecast used to count
            twice in favour (bigger discount, bigger reward/risk) and
            never against.` : ""}${m.min_stop_bp
         ? ` And this book refuses entries whose executable stop is
            tighter than <b>${(m.min_stop_bp / 100).toFixed(0)} %</b>:
            an equal dollar of risk must fit under the per-name cap —
            a tighter stop would silently risk less than R (owner's
            rule; the bar is derived from the cap, not chosen).`
         : ""}</div>`
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
  // Правило пола главной книги — числом, по той же причине, что гейт
  // ситуационной: с полом тихий час НЕ торгуется, и пустой час — это
  // работа правила, а не отказ сборщика.
  const floorLine = !isSit(d) && m.entry_floor_bp
    ? `<div class="mline dim">entry rule: a leg enters only if its
       forecast clears <b>${pct(m.entry_floor_bp)}</b> (≈3× the cost
       round; the extremeness probe put all the edge in that top
       quintile) — a quiet hour is not traded at all, so an hour
       without picks is the rule working, not a failure.</div>`
    : "";
  // Переключатель порога — только у книги без срока: у часовых книг
  // обещания пути не решают ни входа, ни выхода, и фильтровать их тем
  // же числом значило бы сравнивать разные вещи.
  const rrLine = isSit(d) ? rrControl(d) : "";
  // Дневной тормоз — забор поверх ВСЕХ книг, и его состояние обязано
  // стоять на странице всегда: сработавший тормоз без строки читался
  // бы как отказ сборщика (час без входов), а тормоз, чьё состояние
  // устарело, — как работающий. Три состояния — тихо / СРАБОТАЛ /
  // неизвестен — различаются словами и числом.
  const bk = full.day_brake;
  const brakeLine = bk && bk.limit
    ? (bk.error || bk.stale
       ? `<div class="mline alarm">day brake state is UNKNOWN (${
            bk.error ? "error: " + bk.error : "stale"}) — entries are
          NOT braked; a fence that silently is not there is worse
          than none, so this line shouts instead.</div>`
       : (bk.active
          ? `<div class="mline alarm">DAY BRAKE: realized today
             <b>${(+bk.realized).toFixed(2)} $</b> is past
             −<b>${(+bk.limit).toFixed(0)} $</b> (1 % of combined
             book capital) — no new entries until the UTC day ends;
             exits keep working.</div>`
          : `<div class="mline dim">day brake quiet: realized today
             <b>${(+bk.realized).toFixed(2)} $</b>, entries stop for
             the day at −<b>${(+bk.limit).toFixed(0)} $</b> (replay
             of the 08-24…27 drain: would have cut +572 $ of −2061
             at a cost of ≈0 $ in the profitable base).</div>`))
    : "";
  box.innerHTML = armBtns + rrLine + brakeLine + lagLine + gateLine
    + stopLine + floorLine
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
      &nbsp;·&nbsp; <a href="/glossary-page?k=${encodeURIComponent(KEY)
        }">playbook: every situation explained &rarr;</a>
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
        <td class="mono">expects ${pct(p.fwd)} / ${hz}h</td>
        <td class="mono">adverse ~${pct(p.mae)}</td>
        <td class="mono">${p.odd != null
          ? `unseen ${(p.odd * 100).toFixed(0)}%` : ""}</td>
        <td class="mono">${g ? `last: got ${pct(g.got)}` : ""}</td>
        </tr>`;
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
.alarm{border-left:3px solid var(--ask);padding-left:9px;
 color:var(--ask);font-size:12px;margin-bottom:10px}
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
""" + NAVCSS + r"""</style>
<div class="wrap">
  <header class="top">
    <a href="#" id="back" class="brand" title="to overview">ALG<b>O</b>TH</a>
    <span class="tag">model trades</span>
    <span id="src" class="mono note" style="margin:0"></span>
  </header>
  <div id="nav"></div>
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
      <span id="armf" style="display:contents"><span class="k">arm</span>
      <select id="arm"><option value="">both</option>
        <option value="gbm">trees (ML)</option>
        <option value="nn">neural (AI)</option></select></span>
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
      <thead><tr><th title="trade id — quote it to find the trade">id</th>
        <th id="thw">signal hour</th>
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
""" + BOOKJS + NAVJS + r"""
navMount("/trades-page");
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
const HZ = hzOf(new URLSearchParams(location.search).get("hz"));
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
  // Кнопки строятся ИЗ ОБЩЕГО списка книг, а не перечисляются здесь
  // руками: перечень жил пятым местом, и книга в единицах σ до него не
  // доехала — страница открывалась, а вкладки у неё не было.
  document.getElementById("books").innerHTML =
    `<span class="k">book (hold)</span> `
    + BOOK_LIST.map(x => mk(x[0] === "h4" ? "" : x[0], x[1])).join(" ");
}
renderBooks();
// Percent of price move — the display unit across the whole project
// (owner's decision). Two decimals, three for small values: otherwise
// net-after-costs collapses into "0.00 %".
""" + PCTJS + LVLJS + r"""
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
               "вышла, ждёт разбора": "exited, pnl pending",
               // Решение, НЕ ставшее позицией: встречный сигнал в том
               // же имени закрывает существующий лот, а второй не
               // открывает — на одном счёте в одностороннем режиме
               // площадка поступает так же.
               "схлопнула позицию": "netted a position (not opened)"};
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
""" + EXITJS + r"""
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
  // У согласной книги кривые рук совпадают: вторая линия легла бы
  // ровно на первую и читалась бы как «две руки сошлись», тогда как
  // это одна книга, нарисованная дважды.
  const arms = (d.agree && d.arms_match !== false
                ? ["gbm"] : ["gbm", "nn"])
    .filter(a => (cur[a] || []).length > 1);
  const lab = document.getElementById("eqlab");
  if (!arms.length) {
    if (lab) lab.textContent = "not enough hours yet";
    return;
  }
  EQ = {cur, arms, start: d.start ?? null};
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
  if (EQ.start != null) {
    lo = Math.min(lo, EQ.start); hi = Math.max(hi, EQ.start);
  }
  const pad = Math.max(1, (hi - lo) * 0.08);
  lo -= pad; hi += pad;
  const L = 46, R = 8, T = 8, B = 18;
  const X = t => L + (t - t0) / Math.max(1, t1 - t0) * (w - L - R);
  const Y = v => T + (hi - v) / Math.max(1e-9, hi - lo) * (h - T - B);
  const css = getComputedStyle(document.documentElement);
  const rule = css.getPropertyValue("--rule").trim() || "#333";
  const muted = css.getPropertyValue("--muted").trim() || "#888";
  g.strokeStyle = rule; g.lineWidth = 1;
  // Без старта из ответа базовая линия не рисуется вовсе — кривые
  // остаются: выдуманная база хуже её отсутствия.
  if (EQ.start != null) {
    g.beginPath(); g.moveTo(L, Y(EQ.start)); g.lineTo(w - R, Y(EQ.start));
    g.setLineDash([4, 4]); g.stroke(); g.setLineDash([]);
  }
  g.fillStyle = muted; g.font = "11px system-ui,sans-serif";
  g.fillText(hi.toFixed(0), 4, Y(hi) + 9);
  g.fillText(lo.toFixed(0), 4, Y(lo));
  if (EQ.start != null)
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
      const dp = v == null || EQ.start == null
        ? "" : ((v / EQ.start - 1) * 100).toFixed(2);
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
  // У корзинной книги без отдельных выходов срока НЕТ — «hold 4 h»
  // был бы ложью показа: у её ног нет таймера вовсе.
  const holdWord = d.no_timer
    ? "basket only (no per-leg exits)"
    : "hold " + (d.horizon_h || 4) + " h";
  document.getElementById("src").textContent = "live model · "
    + holdWord;
  // Горизонт — в заголовок вкладки: открытые рядом страницы двух книг
  // иначе неотличимы друг от друга.
  document.title = "model trades · " + (d.no_timer
    ? "basket" : (d.horizon_h || 4) + " h");
  document.getElementById("warn").innerHTML = "";
  const cell = (k, v, cls) => `<div class="st"><div class="k">${k}</div>
    <div class="v mono ${cls||""}">${v}</div></div>`;
  // Статистика делится по рукам турнира: all / ml / ai. Смотреть их
  // вместе можно, но решает сравнение — они учатся на одних данных, и
  // общий блок скрывает, какая именно из двух даёт результат.
  // Согласная книга: пересечение выборов симметрично, значит её руки
  // несут ОДНИ И ТЕ ЖЕ сделки, и сервер уже свёл ответ к одной.
  // Переключатель рук предлагал бы выбор между копиями, а вкладка
  // «all» складывала бы книгу с самой собой.
  const AG = !!d.agree && d.arms_match !== false;
  if (d.agree && d.arms_match === false)
    document.getElementById("warn").innerHTML = `<div class="alarm">agreed
      book: both arms must hold <b>identical</b> trades by construction
      &mdash; they do not. Showing both arms until that is explained;
      neither column is the book on its own.</div>`;
  const af = document.getElementById("armf");
  if (af) af.style.display = AG ? "none" : "contents";
  const which = AG ? (d.arm_forced || "gbm") : (S.arm || "all");
  const st = (d.stats||{})[which] || {};
  const acc = (d.accounts||{})[which];
  const armBtns = AG
    ? `<div class="note">One book, not two arms: both heads picked the
       same name and side in the same hour, so the arms hold
       <b>identical</b> trades by construction &mdash; shown once, on
       the trees-arm account.</div>`
    : `<div class="bar">` +
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
    + (st.no_outcome ? cell("no outcome", st.no_outcome, "bad") : "")
    // Решения, схлопнувшие встречный лот: позиции по ним не
    // открывалось, поэтому в списке сделок их нет и в счётчик они не
    // входят — но число стоит рядом, иначе выбор модели пропадает
    // молча. Владелец увидел их в таблице строками на ноль долларов.
    + (st.netted ? cell("netted (no position)", st.netted) : "");
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
      + cell("round trip, median", lvl(st.exec_med_bp),
             st.exec_med_bp > 25 ? "bad" : "")
      + cell("of it commission", lvl(st.fee_med_bp))
      + cell("of it spread", lvl(st.slip_med_bp))
      + cell("mean", lvl(st.exec_avg_bp))
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
      + cell("gift, median", pct(st.gift_med_bp),
             st.gift_med_bp > 5 ? "bad" : "")
      + cell("mean", pct(st.gift_avg_bp))
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
    ["net per trade", a => pct((d.stats[a]||{}).net_bp_avg)],
    ["round trip", a => lvl((d.stats[a]||{}).exec_med_bp)],
    ["account drawdown", a => { const v = ((d.stats[a]||{}).dd_book||{}).pct;
      return v == null ? "—" : v + " %"; }],
    ["worst open moment", a =>
      lvl(((d.stats[a]||{}).dd_open_book||{}).cap_bp)],
  ];
  html += AG
    ? `<div class="gt">the agreed book</div>`
      + `<details class="hint"><summary>how to read</summary>
         <div class="note">One column, because the two arms are the
         same book here. What a second column measures elsewhere
         &mdash; the <b>measurement error</b> between two models
         &mdash; is zero by construction once only agreed decisions
         are traded.</div></details>`
      + `<div class="scroll"><table class="cmp"><tr><th></th>`
      + `<th style="color:${ARMC.gbm}">agreed (both heads)</th></tr>`
      + CMP.map(r => `<tr><td>${r[0]}</td><td>${r[1]("gbm")}</td></tr>`)
          .join("")
      + `</table></div>`
    : `<div class="gt">arms side by side</div>`
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
  const accLine = (AG ? ["gbm"] : ["gbm","nn"]).map(a => {
    const x = (d.accounts||{})[a];
    return x ? `${AG ? "agreed" : (a === "gbm" ? "ml" : "ai")} ${
      x.balance} $` : null;
  }).filter(Boolean).join(" · ");
  if (accLine)
    html += `<div class="note" style="margin-top:8px">${
      AG ? "paper account" : "paper accounts"}: ${accLine} <span class="k">(start ${
      d.start ?? "—"} $${AG ? "" : " each"}, one capital, leverage 1&times;${
      AG ? "; the neural-arm copy carries the same trades"
         : ""})</span></div>`;
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
    return `<tr><td class="mono" style="color:var(--muted)">${
        t.tid ? "#" + t.tid : "\u2014"}</td>
      <td class="mono" title="UTC key ${t.hour}">${
        SIT ? hhmm(t.opened_at) : hourLocal(t.hour)}</td>
      <td class="mono hide-s">${
        SIT ? hourLocal(t.hour) : hhmm(t.opened_at)}</td>
      <td class="mono hide-s">${hhmm(t.closes_at)}</td>
      <td class="mono hide-s" style="color:var(--muted)">${t.lag_sec == null
        ? "—" : Math.round(t.lag_sec/60) + "m"}</td>
      <td class="hide-s">${AG ? "both"
        : (t.arm === "nn" ? "neural" : "trees")}</td>
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
  }).join("") || `<tr><td colspan="18" style="color:var(--muted);
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
    const r = await fetch("/model_marks?k=" + encodeURIComponent(KEY)
      + (HZ ? "&hz=" + encodeURIComponent(HZ) : ""));
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
""" + NAVCSS + r"""</style>
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
  <div id="nav"></div>
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
""" + BOOKJS + NAVJS + r"""
navMount("/bot-page");
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
    document.getElementById("alarm").innerHTML = d.off
      ? `<div class="card">shadow stopped by the owner — enough
         tested, server load trimmed; not a failure. The live
         executor reconciles with the exchange on every tact.
         Turn back on: <span class="mono">tools/run_bot.sh --on</span>
         ${d.off_note ? "<br>" + d.off_note : ""}</div>`
      : `<div class="card">core not running — the shadow is not deployed
       yet</div>`;
    return;
  }
  BOOK_HZ = d.book_hz || "";
  // Имя книги — из общего списка страниц: своя развилка называла
  // ситуационную книгу «situational», а остальные — голым ключом.
  const bkName = (BOOK_LIST.find(x => x[0] === BOOK_HZ) || [])[1];
  document.getElementById("src").textContent = `arm ${d.arm}`
    + (BOOK_HZ ? ` · ${bkName || BOOK_HZ}` : "");
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
  // Журнал писан ПРЕЖНИМ правилом кассы: он дописывается и хранит
  // размеры, посчитанные тем правилом, а Python пересчитывает всё
  // заново — сверка после такой правки краснеет навсегда и перестаёт
  // быть сигналом. Это не расхождение реализаций, и панель обязана
  // сказать это прямо, вместе с тем, чем оно лечится.
  if (d.cash_stale)
    bad.push(`CASH RULES CHANGED: journal written under rule v${
      d.cash_stale.was}, engine now v${d.cash_stale.now} — the
      mismatches above are the old rule, not a real disagreement.
      Restart the core (<span class="mono">tools/run_bot.sh</span>):
      it archives the journal and starts a clean one.`);
  document.getElementById("alarm").innerHTML = bad.length
    ? `<div class="card alarm">${bad.join("<br>")}</div>` : "";
  // Капитал — из статуса самого ядра; выдуманное умолчание красило
  // бы баланс против несуществующей базы (урок фолбэка «22 bp gate»).
  const cap = d.capital_usd || null;
  const share = cap == null ? null
    : ((d.balance_usd / cap - 1) * 100).toFixed(2);
  const tb = document.getElementById("topbal");
  tb.textContent = `${d.balance_usd} $`;
  tb.className = "cv mono " + (cap == null ? ""
    : d.balance_usd >= cap ? "good" : "bad");
  const cnt = d.counts || {};
  document.getElementById("acct").innerHTML =
    cell("balance", `${d.balance_usd} $`,
         cap == null ? "" : d.balance_usd >= cap ? "good" : "bad")
    + cell("vs start", share == null ? "—"
             : `${share > 0 ? "+" : ""}${share} %`,
           share == null ? "" : share >= 0 ? "good" : "bad")
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
      sideways and up/down, finger too · pinch sideways or wheel
      zooms time, pinch up-down / shift+wheel (or wheel over the
      price axis) zooms price · double click or double tap resets
      the price scale</span>
    <span id="cap2" class="mono"></span></div>
  <canvas id="px" height="420"></canvas>
  <div id="tip" class="mono"></div>
</div>
<div class="legend">
  <span><span class="sw" style="border-color:var(--accent)"></span>level</span>
  <span id="lglv"><span><span class="sw"
    style="border-color:var(--ask)"></span>stop</span>
  <span><span class="sw" style="border-color:var(--muted)"></span>where the
    model expects price to go against the trade — the stop stands
    beyond it</span>
  <span><span class="sw" style="border-color:var(--bid)"></span>target /
    profit promise</span></span>
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
    <th>id</th>
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
""" + BOOKJS + r"""
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
  "экстремум": "extreme", "лента": "tape", "стакан": "book"};
""" + EXITJS + r"""
const disp = v => v == null ? "—" : (EXIT_EN[v] || KEY_EN[v] || v);
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
             hz: hzOf(Q.get("hz")),
             // Порог обещанного отношения из ссылки: он выбирает
             // ЗАПИСЬ, из которой сервер отдаёт сделки. `null` —
             // «не задан», и тогда график берёт книгу как она
             // торгует, а если сделки там нет — переспрашивает
             // наблюдательную запись (ниже).
             rr: (Q.get("rr") == null || Q.get("rr") === ""
                  ? null : parseFloat(Q.get("rr"))),
             obs: false,
             // Книга DCA: график показывает ПОЗИЦИИ лестницы, а не
             // выборы модели. Рука у неё одна (лестница не делится на
             // деревья и сеть), уровней нет — и то и другое приходит
             // ОТВЕТОМ сервера, а не решается здесь списком ключей.
             dca: Q.get("dca") || "",
             fit: false};
// Пункты легенды про уровни — только там, где уровни действуют:
// подпись «stop» под графиком часовой книги утверждала бы правило,
// которого у книги нет. Пересчитывается и после ответа сервера — до
// него ситуационность книги неизвестна и уровни не утверждаются.
function legendLevels() {
  const lv = document.getElementById("lglv");
  if (lv) lv.style.display = actsOnLevels() ? "" : "none";
}
legendLevels();
// Сделка, ради которой страницу открыли. Ищется по руке и часу: пара
// (рука, час, монета) единственна по построению — цикл выбирает шесть
// имён на час, повторов в часе нет.
function focused() {
  if (!MDL.hour) return null;
  return MDL.trades.find(t => t.arm === MDL.arm && t.hour === MDL.hour)
    || null;
}
function modelTrades() {
  // Сливаются ТОЛЬКО позиции, у которых доливы были: их лоты
  // накладывались друг на друга и не читались (просьба владельца).
  // Остальные сделки проходят как есть — подменять ими весь список
  // значило бы спрятать те, о которых сервер ничего не склеивал
  // (ответ прежнего образца, другая рука, неполный набор).
  const heads = (MDL.merged || []).filter(t => (t.lots || 1) > 1
                                          && t.arm === MDL.arm);
  const eaten = new Set();
  for (const h of heads) {
    eaten.add(h.arm + "|" + h.sym + "|" + h.side + "|" + h.hour);
    for (const a of (h.adds || []))
      eaten.add(h.arm + "|" + h.sym + "|" + h.side + "|" + a.hour);
  }
  const rest = MDL.trades.filter(
    t => t.arm === MDL.arm
      && !eaten.has(t.arm + "|" + t.sym + "|" + t.side + "|" + t.hour));
  return heads.concat(rest);
}
async function pullModelTrades() {
  // Своя монета — свой запрос, поэтому условие на свежесть проверяется
  // ВМЕСТЕ с монетой: иначе смена монеты в течение минуты оставляла бы
  // на графике сделки прежней.
  if (MDL.busy || (MDL.sym === sym && Date.now() - MDL.at < 60000)) return;
  MDL.busy = true;
  try {
    if (MDL.dca) {
      const p = new URLSearchParams({k: KEY, sym: sym, book: MDL.dca});
      const r = await fetch("/dca_trades?" + p.toString());
      const d = await r.json();
      MDL.trades = (d.rows || []).filter(t => t.sym === sym);
      MDL.merged = (d.merged || []).filter(t => t.sym === sym);
      MDL.arm = "dca";
      MDL.obs = false;
      // Уровней у лестницы нет: обещания пути принадлежат ситуационной
      // книге. Нарисовать их значило бы утверждать правило, которого у
      // книги нет, — поэтому `situational` приходит ложью по делу.
      MDL.rules = {rules_version: d.rules_version, situational: false,
                   dca_book: d.book, dca_title: d.ruler_title,
                   dca_deposit: d.deposit, why: d.why};
      legendLevels();
      MDL.sym = sym; MDL.at = Date.now();
      armButtons();
      if (focused() && !MDL.fit) { MDL.fit = true; fitFocus(); }
      return;
    }
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
    // Слитые позиции считает СЕРВЕР (`trades.merge_adds`): долив —
    // точка на одной позиции, а не отдельная сделка. Фильтруем по
    // монете тем же условием, что строки; головная сделка несёт все
    // поля первого лота, поэтому рисовальщику ничего доучивать не
    // нужно — он просто получает одну позицию вместо четырёх.
    MDL.merged = (d.merged || []).filter(t => t.sym === sym);
    // Правила книги — из ОТВЕТА, не из констант страницы: объяснение
    // сделки обязано описывать тот прогон, который её открыл.
    MDL.rules = {stop_tau: d.stop_tau, min_edge_bp: d.min_edge_bp,
                 min_rr: d.min_rr, min_disc_bp: d.min_disc_bp,
                 rules_version: d.rules_version,
                 no_timer: !!d.no_timer,
                 basket_take_share: d.basket_take_share,
                 basket_floor_share: d.basket_floor_share,
                 basket_age_h: d.basket_age_h,
                 situational: !!d.situational};
    legendLevels();
    MDL.sym = sym; MDL.at = Date.now();
    armButtons();
    // Окно графика под сделку — только когда она нашлась.
    if (focused() && !MDL.fit) { MDL.fit = true; fitFocus(); }
  } catch (e) { /* тихо: следующий круг попробует снова */ }
  finally { MDL.busy = false; }
}

function armButtons() {
  const box = document.getElementById("marm");
  // У книги DCA рук нет вовсе: лестница одна, и переключатель «ml/ai»
  // предлагал бы выбор, которого не существует. Вместо него — имя
  // книги, чьи позиции на графике: молча показывать чужую книгу под
  // прежним переключателем нельзя.
  if (MDL.dca) {
    box.innerHTML = "<span class=\"mono\">DCA · " +
      String((MDL.rules && MDL.rules.dca_title) || MDL.dca) +
      ((MDL.rules && MDL.rules.dca_deposit)
        ? " · $" + Number(MDL.rules.dca_deposit).toLocaleString("en-US")
        : "") + " · " + MDL.trades.length + "</span>";
    return;
  }
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
""" + PCTJS + LVLJS + r"""
// Цена выхода у сделки модели своей колонкой не записана: разбор пишет
// ХОД цены за удержание, а это то же самое число с другой стороны.
// Считать его здесь — не вторая копия расчёта, а перевод единицы.
function mdlExit(t) {
  // У сделки, вышедшей живым сторожем, исхода в разборе ещё нет, а
  // цена выхода записана событием — она и есть факт. Считать по ней
  // не «вторая копия расчёта»: разбор считает ДЕНЬГИ, здесь цена.
  if (t.exit_px) return t.exit_px;
  // У ОТКРЫТОЙ позиции цены выхода не существует, и восстанавливать её
  // из хода нельзя. У частично разгруженной позиции ход принадлежит
  // уже закрытым лотам, и `вход × (1 + ход)` давал бы цену, по которой
  // никто не выходил: владелец увидел ровно такую — 0.008372 у живого
  // шорта по INX. Сервер эту цену и не отдаёт (`exit_px` снят), а
  // страница её выдумывала.
  if (t.state !== "\u0437\u0430\u043a\u0440\u044b\u0442\u0430")
    return null;
  return (t.entry_px && t.got_bp != null)
    ? t.entry_px * (1 + t.got_bp / 10000) : null;
}
// Уровни (стоп и тейк) — правило ТОЛЬКО ситуационной книги: их ведёт
// живой сторож. Книги со сроком (1/4/24 ч) выходят по времени, стопа
// и тейка у их сделок НЕ СУЩЕСТВУЕТ — mae/mfe там прогноз пути, и
// рисовать его линиями TP/SL значит показывать правило, которого нет:
// владелец прочёл эти линии как уровни сделки.
// Ситуационность решает МАНИФЕСТ книги через ответ сервера
// (`situational`), а не список ключей на странице: зашитый список уже
// пропустил книгу равного риска (sit_r) — её сделки рисовались голым
// спаном без стопа и цели, а объяснение писало «выход по времени» про
// книгу, которую ведёт живой сторож уровней (владелец: «очень странно
// отображаются»). До первого ответа уровни не утверждаются.
function actsOnLevels() {
  return !!(MDL.rules && MDL.rules.situational);
}
// Ноги позиции: чем набирали и чем скидывали, по времени. Первый лот
// в `adds` не лежит (там доливы), а его размер выводится из общего:
// второй список размеров разошёлся бы с кассой, которая считает по
// лотам.
function mdlLegs(t) {
  const adds = t.adds || [], exits = t.exits || [];
  if (!adds.length && exits.length < 2) return [];
  const legs = [];
  const first = (t.size_total != null && adds.length)
    ? Math.round((t.size_total
        - adds.reduce((s, a) => s + (a.size || 0), 0)) * 100) / 100
    : t.size;
  legs.push({kind: "entry", at: t.opened_at, px: t.entry_px,
             size: first, hour: t.hour});
  for (const a of adds)
    legs.push({kind: "add", at: a.at, px: a.px, size: a.size,
               hour: a.hour});
  for (const e of exits)
    legs.push({kind: "exit", at: e.at, px: e.px, size: e.size,
               net_bp: e.net_bp, pnl: e.pnl, reason: e.reason});
  legs.sort((a, b) => (a.at || 0) - (b.at || 0));
  // Лот нулевого размера — не дефект показа: касса была занята, и
  // выбор записан без денег (на живой книге так выходит у каждого
  // девятого лота). Голый «0.00 $» читается как поломка, поэтому
  // причина стоит рядом словом.
  for (const l of legs)
    l.dry = l.size != null && Math.abs(l.size) < 0.005;
  return legs;
}
// Какие позиции развёрнуты — состояние ПОКАЗА, и оно обязано пережить
// перерисовку: таблица собирается заново каждым опросом (раз в
// секунду), и разворот, живущий только в разметке, схлопывался сам
// через секунду после нажатия — владелец увидел это на телефоне.
const MDLEXP = new Set();
function mdlLegRows(key, legs) {
  const rows = legs.map(l => {
    const money = l.kind === "exit"
      ? `<td class="mono ${(l.pnl || 0) > 0 ? "buy" : "sell"}">${
          l.net_bp == null ? "—" : pct(l.net_bp)}</td>
         <td class="mono ${(l.pnl || 0) > 0 ? "buy" : "sell"}">${
          l.pnl == null ? "—"
          : (l.pnl > 0 ? "+" : "") + l.pnl.toFixed(2)}</td>`
      : `<td class="mono" style="color:var(--muted)">—</td>
         <td class="mono" style="color:var(--muted)">—</td>`;
    return `<tr>
      <td class="mono" style="color:var(--muted)">${stamp(l.at)}</td>
      <td style="color:var(--muted)">${l.kind === "exit" ? "unload"
        : l.kind === "add" ? "add" : "entry"}</td>
      <td class="mono"${l.dry ? ` title="no free cash that hour: the
        pick is recorded, but the money was already in earlier
        positions — this leg carries no exposure"` : ""}>${
        l.size == null ? "—" : (+l.size).toFixed(2)} $${l.dry
        ? `<span style="color:var(--muted)"> no cash</span>` : ""}</td>
      <td class="mono">${l.px == null ? "—" : +(+l.px).toPrecision(10)}</td>
      ${money}</tr>`;
  }).join("");
  // Цена разгрузки у книг со сроком не записывается вовсе (разбор
  // считает деньги, не цену), и прочерк здесь — не потеря: выдумывать
  // её из хода мы уже перестали.
  return `<tr class="mdet" id="mdet-${mdlKeyId(key)}"
    data-det="${key}" style="display:${
      MDLEXP.has(key) ? "table-row" : "none"}">
    <td colspan="10" style="padding:2px 0 8px 22px">
    <table style="width:100%;border-collapse:collapse" class="mleg">
    <tr><th style="text-align:left">when</th>
    <th style="text-align:left">leg</th><th style="text-align:left">size</th>
    <th style="text-align:left">price</th>
    <th style="text-align:left">net</th>
    <th style="text-align:left">$</th></tr>${rows}</table></td></tr>`;
}
// Ключ строки — в ИДЕНТИФИКАТОРЕ, а не в селекторе по атрибуту:
// разворот обязан проверяться прогоном страницы, а заглушка DOM в
// проверке умеет искать по id. Проверка, которую нельзя выполнить,
// защищает ровно ничего.
function mdlKeyId(key) {
  return String(key).replace(/[^a-z0-9]+/gi, "-");
}
function mdlToggle(key) {
  const id = mdlKeyId(key);
  const r = document.getElementById("mdet-" + id);
  const b = document.getElementById("mexp-" + id);
  // Состояние пишется в набор ДО выхода: строки может не оказаться в
  // разметке (её перерисовывают), но намерение владельца от этого не
  // исчезает — иначе нажатие терялось бы ровно на перерисовке.
  if (MDLEXP.has(key)) MDLEXP.delete(key); else MDLEXP.add(key);
  if (!r) return;
  // Открыто — только «table-row»; всё остальное (пусто, `none`,
  // унаследованное) считается закрытым. Опираться на дословное `none`
  // значит зависеть от того, что браузер вернёт для строки, которой
  // стиль ещё не назначали.
  const open = MDLEXP.has(key);
  r.style.display = open ? "table-row" : "none";
  if (b) b.innerHTML = open ? "&#9662;" : "&#9656;";
}
// Частично разгруженная позиция: часть лотов закрыта, часть жива.
// Реализованное принадлежит закрытой части, и печатать его без
// пометки — то же, что назвать открытую сделку закрытой.
function mdlPart(t) {
  return t.state !== "\u0437\u0430\u043a\u0440\u044b\u0442\u0430"
    && t.got_bp != null;
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
    // Конец ПОЗИЦИИ — последняя разгрузка, а не выход первого лота:
    // иначе спан обрывался бы на первом тейке, а позиция ещё жива.
    const lastEx = (t.exits || []).reduce(
      (m, e) => Math.max(m, e.at || 0), 0);
    const end = (live ? t1 + 60 : 0)
      || lastEx || t.closes_at || t.exit_ts || t.opened_at;
    if (end < t0 - 3600 || t.opened_at > t1 + 3600) continue;
    const xa = clamp(xt(t.opened_at));
    const xb = clamp(xt(Math.min(end, t1 + 60)));
    // Уровень входа — СРЕДНЯЯ цена позиции, когда доливы были.
    const entry = t.avg_px || t.entry_px;
    const ye = y(entry), ex = mdlExit(t);
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
    // У книги без уровней зоны не тянутся к линиям, которых нет.
    for (const v of (actsOnLevels() ? [pAdv, pFav, ex] : [ex])) {
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
    if (actsOnLevels()) {
      promise(pFav, css("--bid"), up ? "promise ↑" : "promise ↓");
      promise(pAdv, css("--ask"), "stop");
      promise(pExp, css("--muted"), "expected move against");
    }
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
    // Плавающая ТВХ: средняя цена входа ПОСЛЕ каждого рунга лестницы.
    // Линия входа стоит на ПЕРВОМ рунге и о позиции больше ничего не
    // говорит — доливы опускают среднюю, и без ступеньки по графику не
    // сказать, от какой цены считается результат. Величина приходит
    // готовой с сервера (`rules.avg_walk`), второй арифметики здесь нет.
    const wk = t.walk || [];
    if (wk.length > 1) {
      // Ступени собираются В СПИСОК, и только он решает, была ли линия
      // нарисована: подпись рядом с ненарисованной линией однажды уже
      // прошла бы проверку — она печатается из данных, а не из
      // картинки, и проверять надо ОТРИСОВАННОЕ.
      const seg = [];
      for (let i = 0; i < wk.length; i++) {
        const x0 = clamp(xt(wk[i].at));
        const x1 = clamp(i + 1 < wk.length ? xt(wk[i + 1].at) : xb);
        seg.push([x0, Math.max(x1, x0), y(wk[i].avg)]);
      }
      if (seg.length) {
        g.save();
        g.strokeStyle = css("--accent"); g.lineWidth = me ? 2 : 1.3;
        g.setLineDash([4, 3]);
        g.beginPath();
        seg.forEach(([x0, x1, yv], i) => {
          if (i === 0) g.moveTo(x0, yv); else g.lineTo(x0, yv);
          g.lineTo(x1, yv);
        });
        g.stroke(); g.setLineDash([]);
        if (me) {
          g.fillStyle = css("--accent");
          g.fillText("avg entry " + wk[wk.length - 1].avg.toFixed(dec),
                     xa + 4, seg[seg.length - 1][2] - 4);
        }
        g.restore();
        const last = seg[seg.length - 1];
        HIT.push({mdl: t, avgline: seg.length, x0: last[0], x1: last[1],
                  y0: last[2] - 4, y1: last[2] + 4});
      }
    }
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
    // Доливы — точками на линии позиции, с размером в подсказке:
    // владелец просил видеть, ЧТО долив был и какой, а не четыре
    // наложенных прямоугольника. Разгрузка — засечками на выходах:
    // это тейки одной позиции, а не отдельные сделки.
    for (const ad of (t.adds || [])) {
      if (!ad.at || !ad.px) continue;
      const xd = clamp(xt(ad.at));
      if (xd < 0 || xd > W) continue;
      g.fillStyle = col;
      g.beginPath();
      g.arc(xd, y(ad.px), me ? 4 : 3, 0, 6.284);
      g.fill();
      HIT.push({add: ad, mdl: t, x0: xd-5, x1: xd+5,
                y0: y(ad.px)-5, y1: y(ad.px)+5});
    }
    for (const e of (t.exits || [])) {
      if (!e.at || !e.px) continue;
      const xe = clamp(xt(e.at));
      if (xe < 0 || xe > W) continue;
      g.strokeStyle = (e.net_bp || 0) > 0 ? css("--bid") : css("--ask");
      g.lineWidth = me ? 2 : 1;
      g.beginPath();
      g.moveTo(xe, y(e.px) - 5);
      g.lineTo(xe, y(e.px) + 5);
      g.stroke();
      // Засечка — своя зона наведения, как у точки долива: подсказка
      // обязана говорить об ЭТОЙ разгрузке, а не о позиции целиком.
      HIT.push({ex: e, mdl: t, x0: xe-5, x1: xe+5,
                y0: y(e.px)-7, y1: y(e.px)+7});
    }
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
        t.side} · ${disp(t.state)}${t.tid
        ? ` · <b>#${t.tid}</b>` : ""}${MDL.obs
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
      move${t.floor_bp
        ? ` and cleared the <b>${pct(t.floor_bp)}</b> entry floor`
        : ""}`);
  if (t.fwd0_bp != null && t.expected_bp != null) {
    const disc = Math.abs(t.expected_bp) - Math.abs(t.fwd0_bp);
    bits.push(`strategy: situational scanner${r.rules_version
      ? " (rules v" + r.rules_version + ")" : ""} — the sheet promised
      ${pct(t.fwd0_bp)}, price gave back <b>${pct(disc)}</b> more, so
      the remaining move crossed the ${r.min_edge_bp != null
        ? lvl(r.min_edge_bp) + " " : ""}entry gate in
      front of us with reward/risk${r.min_rr != null
        ? " ≥ " + r.min_rr : " over the gate"} against the
      executable stop`);
  }
  if (t.mae_bp != null && !actsOnLevels() && r.no_timer) {
    // Книга без отдельных выходов: «exits by time» была бы ложью —
    // ногу закрывает только корзина целиком, правила из ответа.
    bits.push(`path forecast (not orders): expected extreme against
      ${pct(t.mae_bp)}${t.mfe_bp != null
      ? `, in favour ${pct(t.mfe_bp)}` : ""} — this leg has NO exit of
      its own: the whole basket closes at once (target +${
      (r.basket_take_share || 0.05) * 100} % of capital, floor −${
      (r.basket_floor_share || 0.05) * 100} %, or basket age ${
      r.basket_age_h || 24} h)`);
  } else if (t.mae_bp != null && !actsOnLevels()) {
    bits.push(`path forecast (not orders): expected extreme against
      ${pct(t.mae_bp)}${t.mfe_bp != null
      ? `, in favour ${pct(t.mfe_bp)}` : ""} — this book exits by
      time, it has no stop or take`);
  } else if (t.mae_bp != null) {
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
  // Имя книги — из общего списка, а не из ключа строковой хирургией:
  // у ключа `z` она давала «z h book», а у главной книги теряла
  // порядок сечения, которым та торгует.
  const bookName = (BOOK_LIST.find(x => x[0] === (MDL.hz || "h4"))
                    || [null, MDL.hz || "h4"])[1];
  document.getElementById("cap4").textContent =
    `${list.length} on ${sym.replace("USDT", "")} · ${
      MDL.arm === "nn" ? "ai (neural)" : "ml (trees)"} · ${bookName}`;
  document.getElementById("mrows").innerHTML = list.length
    ? list.map(t => {
        const ex = mdlExit(t);
        const cls = t.net_bp == null ? ""
          : (t.net_bp > 0 ? "buy" : "sell");
        // Частично разгруженная позиция: закрытые лоты дали факт,
        // живые — отметку. Обе величины показываются РЯДОМ и никогда
        // не складываются (правило `summary`), и обе подписаны: без
        // подписи реализованное на одном лоте из двух читается как
        // исход всей сделки — владелец увидел ровно это.
        const part = mdlPart(t);
        const ttl = part ? `${t.lots_closed || 1} of ${t.lots || 2}`
          + " lots closed — realised on that part only" : "";
        const live = t.unreal_net_bp == null ? ""
          : `<span style="color:var(--muted)">${
              pct(t.unreal_net_bp)} live</span>`;
        // Открытая сделка несёт нереализованное — иначе колонка «net»
        // у неё пуста, и живая позиция выглядит как потерянная.
        const net = t.net_bp == null ? (live || "—")
          : part ? `${pct(t.net_bp)}<span style="color:var(--muted)">
              part</span>${live ? " · " + live : ""}`
          : pct(t.net_bp);
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
        // Позиция из нескольких лотов разворачивается по кнопке:
        // каждый долив и каждая разгрузка — своей строкой, с размером
        // и с тем, сколько на ней зафиксировано. Сложенная строка
        // говорит про позицию целиком, и по ней не видно, ЧЕМ её
        // набирали и по частям ли скидывали.
        const legs = mdlLegs(t);
        const key = `${t.arm || "gbm"}|${t.hour}`;
        const exp = legs.length > 1
          ? `<button class="mexp" id="mexp-${mdlKeyId(key)}"
             data-exp="${key}"
             title="show the lots and unloads"
             onclick="event.stopPropagation();mdlToggle('${key}')"
             style="background:none;border:0;color:var(--muted);
             cursor:pointer;padding:0 4px">${
             MDLEXP.has(key) ? "&#9662;" : "&#9656;"}</button>` : "";
        return `<tr data-h="${t.hour}" style="cursor:pointer${
          here ? ";background:rgba(127,127,255,.10)" : ""}"
          title="${tip ? tip + " — " : ""}click to centre the chart">
        <td class="mono" style="color:var(--muted)">${
          t.tid ? "#" + t.tid : "\u2014"}</td>
        <td class="mono">${exp}${stamp(t.opened_at)}</td>
        <td class="${t.side === "long" ? "buy" : "sell"}">${t.side}</td>
        <td class="mono" ${(t.lots || 1) > 1
          ? `title="${t.lots} lots, average of ${t.size_total} $"` : ""}>${
          t.entry_px == null && t.avg_px == null ? "—"
          : (t.lots || 1) > 1
            ? `${t.avg_px} <span style="color:var(--muted)">avg ×${
                t.lots}</span>`
            : t.entry_px}</td>
        <td class="mono">${ex == null ? "—" : +ex.toPrecision(10)}</td>
        <td class="mono" style="color:var(--muted)">${
          pct(t.expected_bp)}</td>
        <td class="mono"${part ? ` title="${ttl}"` : ""}>${
          pct(t.got_bp)}${part
          ? `<span style="color:var(--muted)"> part</span>` : ""}</td>
        <td class="mono ${cls}"${part ? ` title="${ttl}"` : ""}>${net}</td>
        <td class="mono ${cls}"${part ? ` title="${ttl}"` : ""}>${
          t.pnl == null ? "—"
          : (t.pnl > 0 ? "+" : "") + t.pnl.toFixed(2)}</td>
        <td style="color:var(--muted)">${disp(t.state)}${
          t.exit_reason ? " · " + disp(t.exit_reason) : ""} ${
          info}</td></tr>${legs.length > 1 ? mdlLegRows(key, legs) : ""}`;
      }).join("")
    : `<tr><td colspan="10" style="color:var(--muted)">no model trades on
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
          // Палец тянет и вертикаль тоже: у холста стоит
          // touch-action:none, страница с него не листается и так,
          // значит вертикальный жест не отнимает у владельца ничего —
          // а без него телефон не мог сдвинуть цену вовсе (прежняя
          // оговорка «касание оставляет прокрутку экрану» была
          // списана с намерения, а не с кода).
          vert: true}; });
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
// Двойное касание пальцем — тот же сброс, что двойной щелчок мышью:
// dblclick при touch-action:none телефон не шлёт, и уехавшую цену
// иначе было бы не вернуть без перезагрузки страницы.
let lastTap = 0;
px.addEventListener("pointerup", e => {
  if (drag && Math.abs(e.clientX-drag.x) < 6
      && Math.abs(e.clientY-drag.y) < 6) {
    if (e.pointerType === "touch" && Date.now() - lastTap < 350) {
      // Сброс снимает и перекрестие с подсказкой: первый тап их
      // поставил (тап по сделке показывает подсказку — это фича),
      // и «автоматический масштаб» с висящим перекрестием не был бы
      // возвратом к исходному виду.
      vreset(); lastTap = 0; CROSS = null;
      tip.style.display = "none"; draw();
    } else {
      lastTap = Date.now(); hover(e);
    }
  }
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
// Щипок читается по осям, а не одним расстоянием: горизонтальный
// развод пальцев — масштаб времени вокруг центра щипка, вертикальный —
// масштаб цены, движение самого центра — панорама по обеим осям.
// Прежний щипок менял только время и всегда вокруг середины экрана —
// владелец на телефоне не мог ни растянуть цену, ни прицелиться.
px.addEventListener("touchstart", e => { if (e.touches.length===2){
  drag=null; pinch=span(e); } }, {passive:true});
px.addEventListener("touchmove", e => { if (e.touches.length===2 && pinch){
  const s=span(e);
  const r = px.getBoundingClientRect();
  // Оси независимы: диагональный щипок меняет обе. Порог в 40px —
  // чтобы почти вертикальный щипок не дёргал время шумом дрожащих
  // пальцев (и наоборот).
  if (pinch.dx > 40 && s.dx > 40)
    zoom(pinch.dx/s.dx, (s.cx - r.left)/Math.max(1, px.clientWidth));
  if (pinch.dy > 40 && s.dy > 40)
    vzoom = Math.max(0.05, Math.min(20, vzoom*pinch.dy/s.dy));
  const c = cands();
  if (c.length && view) {
    const per = Math.max(1e-9, px.clientWidth/view.n);
    view.i0 = Math.max(0, Math.min(c.length-view.n,
                                   view.i0 - (s.cx-pinch.cx)/per));
    follow = false;
    document.getElementById("live").setAttribute("aria-pressed","false");
  }
  vpan += (s.cy-pinch.cy)/Math.max(1, px.clientHeight - 30);
  pinch=s; draw(); } }, {passive:true});
px.addEventListener("touchend", () => { pinch=null; });
function span(e){
  const a=e.touches[0], b=e.touches[1];
  return {dx: Math.abs(a.clientX-b.clientX),
          dy: Math.abs(a.clientY-b.clientY),
          cx: (a.clientX+b.clientX)/2, cy: (a.clientY+b.clientY)/2}; }
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
  const put = () => {
    tip.style.display="block";
    tip.style.left = Math.max(4, Math.min(px.clientWidth-tip.offsetWidth-4,
                                          mx+14))+"px";
    tip.style.top = Math.max(4, my+18)+"px";
  };
  const hm = v => new Date(v*1000).toISOString().slice(11,16) + " UTC";
  // Точка долива и засечка разгрузки — подсказка ПРО ЭТУ ногу, а не про
  // позицию целиком: зона точки лежит внутри спана сделки, и общая
  // подсказка на ней съедала бы ровно те числа, ради которых точка и
  // нарисована (просьба владельца).
  if (h.add) {
    const a = h.add, t = h.mdl;
    const dry = a.size != null && Math.abs(a.size) < 0.005;
    tip.innerHTML = `<div style="font-weight:650;margin-bottom:3px">
        add · ${t.side} · ${t.sym.replace("USDT","")}</div>`
      + row("time", hm(a.at))
      + row("price", a.px)
      + row("size", dry ? "0 $ — no cash that hour"
            : a.size == null ? "—" : (+a.size).toFixed(2) + " $")
      + row("position from", t.hour);
    put();
    return;
  }
  if (h.ex) {
    const ev = h.ex, t = h.mdl;
    tip.innerHTML = `<div style="font-weight:650;margin-bottom:3px">
        unload · ${t.side} · ${t.sym.replace("USDT","")}</div>`
      + row("time", hm(ev.at))
      + row("price", ev.px == null ? "—" : ev.px)
      + row("size out", ev.size == null ? "—"
            : (+ev.size).toFixed(2) + " $")
      + (ev.net_bp == null ? ""
         : row("net this lot", pct(ev.net_bp),
               ev.net_bp > 0 ? "buy" : "sell"))
      + (ev.pnl == null ? ""
         : row("locked in", (ev.pnl > 0 ? "+" : "")
               + (+ev.pnl).toFixed(2) + " $",
               ev.pnl > 0 ? "buy" : "sell"))
      + (ev.reason ? row("reason", disp(ev.reason)) : "");
    put();
    return;
  }
  if (h.mdl) {
    // Сделка МОДЕЛИ. Открытая несёт прогноз и срок, закрытая — факт и
    // деньги; путать её со сделкой детектора нельзя, поэтому и
    // подсказка своя.
    // Процент движения цены, а не б.п. — решение владельца. Два знака,
    // при мелких величинах три: нетто после издержек иначе схлопнулось
    // бы в «0.00 %», а это как раз то число, ради которого смотрят.
    const t = h.mdl;
    tip.innerHTML = `<div style="font-weight:650;margin-bottom:3px">
        model · ${t.side} · ${disp(t.state)}</div>`
      + row("arm", t.arm === "nn" ? "neural (AI)" : "trees (ML)")
      + row("signal hour", t.hour)
      + row("entry", new Date(t.opened_at*1000).toISOString().slice(11,16)
            + " UTC" + (t.lag_sec == null ? ""
              : ` (+${Math.round(t.lag_sec/60)} min)`))
      + row("expects", pct(t.expected_bp))
      + row("adverse expected", pct(t.mae_bp))
      // Ход в пользу — второй конец обещания. Пустой у сделок, записанных
      // до того, как поле появилось; показывать там ноль значило бы
      // выдать отсутствие данных за «модель не ждёт движения».
      + (t.mfe_bp == null ? "" : row("favorable expected", pct(t.mfe_bp)))
      + (t.state === "закрыта"
         ? row("got", pct(t.got_bp), (t.got_bp>0)===(t.side==="long")
               ? "buy" : "sell")
           + row("net after costs", pct(t.net_bp),
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


# Перевод признаков на человеческий — ОДИН на все страницы, которые
# его показывают (разбор сделки и справочник). Копию я едва не завёл
# ради справочника: два словаря с одними ключами разошлись бы молча, и
# одна страница объясняла бы признак иначе, чем другая. Незнакомое имя
# честно остаётся как есть — выдуманное описание хуже сырого имени.
FEATJS = r"""
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
const FEAT_RU = {
  imb_best:"размер бида против аска на самой вершине книги",
  spread_rel:"спред против своей обычной ширины",
  upd_rel:"как быстро переписывают книгу против обычного",
  big_rel:"самая крупная стоящая заявка против обычной здесь",
  turn_rel:"оборот часа против обычного",
  delta:"кто бьёт сильнее в ленте — покупатели или продавцы",
  burst:"крупнейший всплеск объёма за секунду против обычного",
  traded_share:"в какой доле часа вообще были сделки",
  eat_bid:"продавцы выедают показанные биды",
  eat_ask:"покупатели выедают показанные аски",
  net_path_24h:"насколько прямым был суточный ход (чистое к пути)",
  vol_regime:"волатильность суток против недели — проснулась или спит",
  fr_bp:"текущая ставка финансирования",
  mins_fund:"минуты до следующего начисления",
  oi_rel:"открытый интерес против своего обычного уровня",
  oi_chg_4h:"изменение открытого интереса за 4 часа",
  oi_chg_24h:"изменение открытого интереса за сутки",
  basis_bp:"цена перпа против спота — премия или дисконт",
  liq_long_share:"ликвидации лонгов как доля оборота",
  liq_short_share:"ликвидации шортов как доля оборота",
  liq_imb:"какую сторону вынесло сильнее",
  squeeze_4h:"насколько зажат четырёхчасовой размах против обычного",
  squeeze_24h:"насколько зажат суточный размах против обычного",
  tilt_4h:"наклонка: чистый ход за 4 часа внутри своего размаха",
  range_pos:"где цена в суточном диапазоне (0 — низ, 1 — верх)",
  dwell_24h:"сколько цена уже стоит в этом коридоре",
  hod_sin:"время суток", hod_cos:"время суток", dow:"день недели",
  btc_ret_4h:"собственный ход BTC за 4 часа",
  sec_ret_4h:"ход сектора этой монеты за 4 часа",
  rel_sec_4h:"насколько монета отстала от своего сектора за 4 часа",
  dist_round:"расстояние до ближайшего круглого числа",
  beta:"насколько сильно монета идёт за рыночной волной",
  age_rec:"возраст монеты в записи"};
// `lang` необязателен: страница разбора сделки зовёт без него и
// получает прежний английский бит в бит. Незнакомое имя честно
// остаётся как есть на любом языке — выдуманный перевод хуже сырого
// имени, а перевод, которого нет, не должен превращаться в пустоту.
function featDesc(n, lang){
  const ru = lang === "ru";
  const D = ru ? FEAT_RU : FEAT_EN;
  if (D[n]) return D[n];
  if (ru && FEAT_EN[n]) return FEAT_EN[n];
  let m = n.match(/^ret_(\d+)h?$/);
  if (m) return ru
    ? `собственный ход монеты за ${m[1]} ч в единицах своей волатильности`
    : `the coin's own ${m[1]} h move vs its usual volatility`;
  const band = w => parseFloat((w*100).toFixed(3));
  m = n.match(/^imb_([\d.]+)$/);
  if (m) return ru
    ? `бид против аска в полосе ±${band(+m[1])} % от цены`
    : `bid vs ask depth within ±${band(+m[1])} % of price`;
  m = n.match(/^depth_b([\d.]+)$/);
  if (m) return ru
    ? `глубина бида в полосе ±${band(+m[1])} % против обычной`
    : `bid depth within ±${band(+m[1])} % vs usual`;
  m = n.match(/^depth_a([\d.]+)$/);
  if (m) return ru
    ? `глубина аска в полосе ±${band(+m[1])} % против обычной`
    : `ask depth within ±${band(+m[1])} % vs usual`;
  return n;
}
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
""" + BOOKJS + r"""
// Ключи книг — из общего списка: свой перечень уже отстал от жизни
// (нёс удалённую h1 и не знал sit_r и z), и значок «i» у сделки
// боковой книги открывал разбор ГЛАВНОЙ книги — «сделки нет» было
// ответом про другую книгу.
const Q = new URLSearchParams(location.search);
const KEY = Q.get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
const HZ = hzOf(Q.get("hz"));
const ARM = Q.get("arm") === "nn" ? "nn" : "gbm";
const HOUR = Q.get("hour") || "";
const SYM = Q.get("sym") || "";
const SIDE = Q.get("side") || "";
const RR = Q.get("rr");

""" + PCTJS + LVLJS + r"""
function px_at(entry, bp){ if (entry == null || bp == null) return null;
  return +(entry * (1 + bp/1e4)).toPrecision(6); }
function utc(ts){ if (!ts) return "—";
  const d = new Date(ts*1000);
  return d.toISOString().slice(0,16).replace("T"," ") + " utc"; }

// Состояния и причины выхода приходят по-русски: это ключи файлов.
const ST_EN = {"закрыта":"closed","открыта":"open",
  "вышла, ждёт разбора":"exited, pnl pending",
  "ждёт разбора":"awaiting review","без исхода":"no outcome",
  "схлопнула позицию":"netted a position (not opened)"};
const EXIT_EN = {"прогноз развернулся":"the forecast flipped sign",
  "цена прошла обещанный ход против":"price hit the stop",
  "цена дошла до обещанной цели":"price reached the target",
  "предел возраста":"the 24 h age limit",
  "корзина дошла до цели":"the whole basket hit its profit target",
  "корзина дошла до предела убытка":"the whole basket hit its loss floor",
  "корзина дошла до предела возраста":"the whole basket hit its age limit",
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
""" + FEATJS + r"""

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
    : d.no_timer ? "basket-only book (no per-leg exits)"
    : `${d.horizon_h || 4} h book`;
  document.getElementById("ttl").textContent =
    `${SYM.replace("USDT","")} · ${t.side} · ${bookName} · ${
      ST_EN[t.state] || t.state}${t.tid ? " · #" + t.tid : ""}`;
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
      ${d.min_edge_bp != null
        ? lvl(d.min_edge_bp) + " " : ""}entry gate.</p>
      <p>Two more checks passed before entering: the crossing happened
      <b>in front of the scanner</b> (the name was first seen away
      from the trigger — so this was a move, not a wobble around a
      line it was parked at), and the promised reward was at least
      ${d.min_rr != null ? d.min_rr + "&times;"
                         : "the gate's multiple of"}
      the distance to the actual stop.</p>${t.noise_bp != null
      ? `<p>Rules v11, both by the numbers of this entry: the stop
        room survived the coin's live minute noise of
        <b>${pct(t.noise_bp)}</b>${d.noise_mult > 1
          ? ` — cleared at this book's own bar of
             <b>${d.noise_mult}×</b> that noise (owner's rule: a
             stop one wick wide is a coin toss)` : ""}, and the
        price had consumed
        <b>${Math.round((t.eaten ?? 0) * 100)} %</b> of the promised
        adverse path${d.max_eaten != null
          ? ` — under the ${Math.round(d.max_eaten * 100)} % cap`
          : ""}. A move against the forecast used to count only in
        favour of entering; these two gates are where it counts
        against.</p>` : ""}`;
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
         rule).`) + (d.min_stop_bp
      ? ` This book only takes trades whose stop is at least
         <b>${(d.min_stop_bp / 100).toFixed(0)} %</b> wide: an equal
         dollar of risk (R) must fit under the per-name cap, and a
         tighter stop would silently risk less than R.`
      : "") + `</p>`
      + (t.mfe_bp != null
      ? `<p><b>Target</b> at ${tgtPx ?? "—"} (${pct(t.mfe_bp)}): the
         best excursion the model expects in the trade's favour —
         what it waits for, not a rare tail.</p>` : "")
      + `<p class="dim">Exits, in order: stop or target touched by the
       path of trade prints (checked every ~5 seconds). The target is
       a resting limit at a level known since entry: when prints pass
       <b>strictly through</b> it, the fill is credited at the level
       itself — by price-time priority such a sweep cannot skip our
       order. A mere touch — and every stop — fills at the price
       available when noticed: in a gap the fill can be worse than
       the level, the stop does <b>not</b> guarantee the loss bound${
       d.exit_policy === "levels_only"
       ? `. <b>Nothing else closes this book's trades</b> (owner's
          rule): no forecast flip, no age limit — every close is the
          stop or the take, −1R or +RR·R`
       : `; the forecast flipping sign at an hourly review; the 24 h
          age limit`}.</p>`;
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
    if (t.fill === "level")
      out += `<p class="dim">The take was credited <b>at the level
        itself</b>: prints traded strictly through it${
        t.thru_px != null ? ` (to ${t.thru_px})` : ""} — a resting
        limit there cannot be skipped by such a sweep. A mere touch
        would have filled at the price available when noticed.</p>`;
  } else if (t.exit_pending) {
    out = `<p>The guard saw the exit (${EXIT_EN[t.exit_reason]
      || t.exit_reason}) at ${utc(t.exit_ts)}; money is booked at the
      hourly review — the shadowed bot reads the same files, and the
      page must not run ahead of it.</p>`;
  } else if (t.state === "схлопнула позицию") {
    // Найдено владельцем: карточка писала «Still open» там, где
    // позиции не открывалось вовсе. Состояние существует потому, что
    // решение модели не должно пропадать из записи, — но сделкой оно
    // не стало: ни входа, ни размера, ни денег.
    out = `<p><b>No position was opened.</b> The book already held the
      opposite side in this coin, and on one account in one-way mode
      an opposite order does not open a second position — it closes
      the existing one. So this signal <b>closed the older lot</b>${
      t.netted_with ? ` (entered at hour ${
        String(t.netted_with).replace(/[^0-9-]/g, "")})` : ""}
      at this signal's price; that lot carries the money, with the
      exit reason «a counter signal closed the position».</p>
      <p class="dim">This record has no entry time, no size and no
      money of its own — the cash account skips it. It is kept so the
      model's decision stays visible: a signal that did not become a
      trade is not the same as a signal that never happened. If the
      book held several lots, only the oldest is closed (FIFO, as the
      exchange does), so the rest of the position stays open.</p>`;
  } else if (t.state === "без исхода") {
    out = `<p>No outcome could be computed — the forward was never
      closed for this coin (a gap in the record, or the coin left the
      universe). The principal returns to the cash account, but no
      result is invented for it.</p>`;
  } else if (t.state === "ждёт разбора") {
    out = `<p>The hold is over and the hourly review has not reached
      this trade yet — the money appears when it does.</p>`;
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


# Справочник — просьба владельца: страница со всеми «стратегиями»
# модели и подробным объяснением каждой простыми словами. Тексты
# приходят с сервера из `families.py` (единственное определение карты
# семейств), список признаков — из ЖИВОГО манифеста обучения. Страница
# ничего не выдумывает и своей таблицы семейств не держит: вторая
# таблица разошлась бы с той, по которой считается вид ситуации.
# Волатильность рынка против результата книг — просьба владельца:
# сразу понимать, насколько режим рынка влияет на модели. Страница
# намеренно НЕ является картинкой волатильности: главное на ней —
# разбивка наших же закрытых сделок по режиму часа входа, а кривая
# стоит рядом контекстом. Все агрегаты приходят с сервера готовыми.
LEARNPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>learning — is the model getting smarter, and does it pay</title>
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
.wrap{max-width:1560px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
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
.thin{color:var(--muted)}
a{color:var(--accent)}
.scroll{overflow-x:auto}
.big{font-size:19px;font-weight:700}
""" + NAVCSS + r"""
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">learning — is the model getting smarter, and does
    it pay</span>
  <span style="flex:1"></span>
  <span class="k" id="lead"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div id="box">&hellip;</div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + r"""
navMount("/learning-page");
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function num(v, dg){ return v == null ? "&mdash;"
  : (v > 0 ? "+" : "") + Number(v).toFixed(dg == null ? 3 : dg); }

// Рамка предмета — первым абзацем, как на листе турнира: без неё
// «модель умнеет» читается из любой зелёной строки.
function intro(d){
  const n = (d.days || []).length;
  return `<div class="cap">what this page can and cannot show</div>
  <div>Three rows that must not be confused. <b>Skill</b> is the live
  IC — the rank agreement between the forecast and what happened,
  over the WHOLE section, not over the six names the book picked.
  <b>Money</b> is the closed trades of the same day. <b>Knowledge</b>
  is how many sections the training had and what the canary read.</div>
  <div class="k" style="margin-top:6px">Hourly retraining cannot make
  the model measurably smarter, and that was measured before it was
  built: a fresh hour is 1/40000 of the sample, and M2 found daily
  against monthly retraining worth +0.000…+0.004 IC. So the trend of
  IC is read as «is it degrading», not as «is it learning»; growth,
  if it comes, comes from the sample getting longer and from rules
  changing — and it shows up in the link between skill and money, not
  in the training number. ${n} days of record so far: at this length
  a rank correlation is a hint, not a finding.</div>`;
}
function headline(d){
  const m = d.ic_vs_money, t = d.ic_vs_time;
  const say = (v, n, good, bad) => v == null
    ? `<span class="dim">not enough days</span>`
    : `<span class="${v > 0 ? "good" : "bad"}">${num(v)}</span>
       <span class="k">over ${n} days — ${v > 0 ? good : bad}</span>`;
  return `<div class="panel"><div class="cap">the two questions</div>
    <table><tr><td>does a smarter day earn more?</td>
      <td class="mono big">${say(m, d.ic_vs_money_n,
        "days when the forecasts ranked the outcomes better are the "
        + "days the books earned more", "the link points the wrong "
        + "way: better-ranked days earned less")}</td></tr>
    <tr><td>is skill drifting with time?</td>
      <td class="mono big">${say(t, d.ic_vs_time_n,
        "IC is drifting up over the record",
        "IC is drifting down — worth watching, not yet a verdict")}</td>
    </tr></table>
    <div class="k" style="margin-top:6px">Both are rank correlations
    over DAYS, not over trades: hours inside a day share the same
    market and the same weights, so counting them as observations
    would inflate the certainty. A day with no closed trades or no
    scored section is left out entirely — a gap is not a zero.</div>
    </div>`;
}
function table(d){
  const rows = (d.days || []);
  if (!rows.length)
    return `<div class="panel"><div class="dim">no scored sections
      yet — the model writes one per hour per target, and the first
      appear once the forward closes</div></div>`;
  return `<div class="panel"><div class="cap">day by day</div>
   <div class="scroll"><table><tr><th>day</th><th>IC 4 h</th>
   <th>sections</th><th>IC 24 h</th><th>sections</th>
   <th>trades</th><th>$</th><th>trainings</th><th>sample</th>
   <th>canary</th></tr>` + rows.map(r => `<tr>
     <td class="mono">${esc(r.day)}</td>
     <td class="mono ${r.ic_4h == null ? "dim"
        : (r.ic_4h > 0 ? "good" : "bad")}">${num(r.ic_4h)}</td>
     <td class="mono ${r.sections_4h < 5 ? "thin" : ""}">${
        r.sections_4h || "&mdash;"}</td>
     <td class="mono ${r.ic_24h == null ? "dim"
        : (r.ic_24h > 0 ? "good" : "bad")}">${num(r.ic_24h)}</td>
     <td class="mono ${r.sections_24h < 5 ? "thin" : ""}">${
        r.sections_24h || "&mdash;"}</td>
     <td class="mono">${r.trades || "&mdash;"}</td>
     <td class="mono ${r.pnl > 0 ? "good" : "bad"}">${num(r.pnl, 2)}</td>
     <td class="mono">${r.trainings || "&mdash;"}</td>
     <td class="mono">${r.sections == null ? "&mdash;" : r.sections}</td>
     <td class="mono">${num(r.canary_ic)}</td></tr>`).join("")
   + `</table></div><div class="k">A day whose section count is small
   is greyed: one section is a rank correlation over four hundred
   names in one hour, and it swings by tenths. «Sample» is how many
   sections the last training of that day had — the row that says
   whether the model knows more than it did; it is empty for days
   recorded before the training log existed, and that is a gap, not
   a zero.</div></div>`;
}
async function load(){
  try {
    const r = await fetch("/learning?k=" + encodeURIComponent(KEY));
    const d = await r.json();
    document.getElementById("intro").innerHTML = intro(d);
    document.getElementById("box").innerHTML =
      headline(d) + table(d)
      + ((d.errors || []).length
         ? `<div class="panel"><div class="cap">books that did not
            build</div><div class="dim">${(d.errors || [])
            .map(esc).join("<br>")}</div><div class="k">their trades
            are missing from the money column — the numbers here are
            NOT the whole story</div></div>` : "");
    document.getElementById("lead").textContent =
      (d.days || []).length + " days";
  } catch (e) {
    document.getElementById("box").innerHTML =
      `<div class="panel"><div class="dim">no answer from the
       collector — the page shows nothing rather than guessing</div>
       </div>`;
  }
}
load();
setInterval(load, 60000);
</script>
"""

# Дневная статистика ОДНОЙ книги — просьба владельца: «кликаем на
# 4-hour book, и открывается страница, где статистика по этой книге
# отдельно по каждому дню, примерно как на странице learning».
#
# Итог книги на дереве отвечает «сколько всего» и молчит о том, КОГДА:
# сумма за две недели может стоять на одном дне, и по ней нельзя
# отличить ровный ряд от одного разгона. Числа считает сервер той же
# кассой, что видит владелец на остальных страницах, — вторая
# реализация счёта здесь разошлась бы с обзором ровно так, как уже
# расходились две дороги одной книги.
BOOKDAYS = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>book, day by day</title>
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
.wrap{max-width:1560px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
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
.thin{color:var(--muted)}
a{color:var(--accent)}
.scroll{overflow-x:auto}
.big{font-size:19px;font-weight:700}
.stats{display:flex;gap:8px;flex-wrap:wrap}
.st{background:var(--chip);border:1px solid var(--rule);
 border-radius:12px;padding:8px 12px;min-width:120px}
.st .v{font-size:17px;font-weight:700}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.tab{padding:4px 12px;border-radius:999px;font-size:12px;
 border:1px solid var(--rule);background:var(--chip);
 color:var(--muted);cursor:pointer}
.tab[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
.nb{white-space:nowrap}
""" + NAVCSS + r"""
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k" id="strap">book, day by day</span>
  <span style="flex:1"></span>
  <span class="k" id="lead"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div id="arms"></div>
<div id="box">&hellip;</div>
</div>
<script>
const Q = new URLSearchParams(location.search);
const KEY = Q.get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + BOOKJS + EXITJS + r"""
navMount("/book-page");
// Книга берётся из ОБЩЕГО списка, а не собирается из ключа строковой
// хирургией: у графика так уже выходило «z h book», и подпись врала о
// том, что показано.
const HZ = hzOf(Q.get("hz")) || "h4";
const BOOK_NAME = (BOOK_LIST.find(x => x[0] === HZ) || [HZ, HZ])[1];
const ARMS = ["all", "gbm", "nn"];
let ARM = ARMS.includes(Q.get("arm")) ? Q.get("arm") : "all";
let DATA = null;
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function money(v){
  if (v == null) return "&mdash;";
  const c = v > 0 ? "good" : v < 0 ? "bad" : "";
  return `<span class="${c} mono nb">${v > 0 ? "+" : ""}${
    Number(v).toFixed(2)} $</span>`;
}
function share(v, cap){
  if (v == null || !cap) return "";
  return ` <span class="mono nb dim">(${pct(v / cap * 1e4)})</span>`;
}
function exits(e){
  const ks = Object.keys(e || {});
  if (!ks.length) return "&mdash;";
  return ks.map(k => `${esc(EXIT_EN[k] || k)}&nbsp;${e[k]}`)
    .sort().join(" · ");
}
function cell(row){ return (row.arms || {})[ARM] || null; }

// Рамка предмета — первым абзацем, как на листе турнира и на странице
// обучения: без неё дневная кривая читается как «книга зарабатывает»,
// а она отвечает на другой вопрос — РОВНО ли она это делает.
function intro(d){
  if (d.unknown) return `<div class="cap">no daily money for this
    book</div><div>«${esc(BOOK_NAME)}» is not one of the traded books:
    the observation record takes the same candidates as the traded one
    and holds no money of its own, so there is nothing to break down by
    day. This is a different thing from a book that traded nothing.
    </div>`;
  const n = (d.days || []).length;
  return `<div class="cap">what this page shows</div>
  <div>Closed trades of <b>${esc(BOOK_NAME)}</b>, split by calendar day
  (UTC). A day owns a trade by the moment its money became known — the
  live exit or the review — not by when it was opened: a trade opened
  yesterday and closed today belongs to today, otherwise yesterday's
  line would keep changing behind our back.</div>
  <div class="k" style="margin-top:6px">Open positions are NOT in these
  numbers and are never added to them: an open position has no outcome,
  only a mark that will be a different number tomorrow. They are shown
  once, as the state of right now.${d.echo ? " This book is an ECHO: "
  + "its decisions are copies of another book's, differing by one "
  + "declared rule — its money is real, but it is not an independent "
  + "observation." : ""} ${n} days of record: at this length a good day
  is a day, not a property of the book.</div>`;
}
function tiles(d){
  const t = (d.totals || {})[ARM];
  if (!t) return `<div class="panel"><div class="dim">no closed trades
    in this book for this arm yet</div></div>`;
  const days = (d.days || []).filter(r => cell(r));
  const best = days.reduce((a, b) =>
    !a || cell(b).pnl > cell(a).pnl ? b : a, null);
  const worst = days.reduce((a, b) =>
    !a || cell(b).pnl < cell(a).pnl ? b : a, null);
  const st = (cap, v, sub) => `<div class="st"><div class="k">${
    cap}</div><div class="v">${v}</div>${
    sub ? `<div class="k">${sub}</div>` : ""}</div>`;
  const green = days.filter(r => cell(r).pnl > 0).length;
  return `<div class="panel"><div class="cap">the book so far</div>
   <div class="stats">
    ${st("days", days.length, green + " green · "
         + (days.length - green) + " red")}
    ${st("trades", t.trades, Math.round(t.win * 100) + " % won")}
    ${st("realised", money(t.pnl) + share(t.pnl, d.cap),
         "closed trades only")}
    ${st("median trade", t.net_med == null ? "&mdash;"
         : pct(t.net_med), "mean " + (t.net_avg == null ? "&mdash;"
         : pct(t.net_avg)))}
    ${st("without the best trade", money(t.pnl_wo_top),
         "best: " + esc(t.top_sym) + " " + money(t.top_pnl))}
    ${best ? st("best day", money(cell(best).pnl), esc(best.day)) : ""}
    ${worst ? st("worst day", money(cell(worst).pnl),
                 esc(worst.day)) : ""}
    ${openTile(d)}
   </div>
   <div class="k" style="margin-top:8px">«Without the best trade» is
   here for the same reason it is in the league: a fortnight whose
   money belongs to one name looks like statistics until that column
   is put next to it.</div></div>`;
}
// Открытое стоит ОТДЕЛЬНОЙ плиткой и никогда не складывается с
// реализованным. Переоценить нечего — прочерк, а не ноль: ноль
// объявил бы позицию ровной там, где по инструменту просто нет цены.
function openTile(d){
  const o = d.open || {};
  const arms = ARM === "all" ? ["gbm", "nn"] : [ARM];
  let n = 0, m = 0, p = 0.0, priced = false;
  for (const a of arms) {
    const s = o[a];
    if (!s || !s.open) continue;
    n += s.open; m += s.marked || 0;
    if (s.unreal_pnl != null) { p += s.unreal_pnl; priced = true; }
  }
  if (!n) return "";
  const v = priced ? money(Math.round(p * 100) / 100) : "&mdash;";
  return `<div class="st"><div class="k">open now</div>
    <div class="v">${v}</div><div class="k">${n} open${
    m < n ? " · " + m + "/" + n + " priced" : ""} · a mark, not an
    outcome</div></div>`;
}
// Кривая — накопленные ДЕНЬГИ по дням, с честным нулём: база не
// подрисовывается под минимум, иначе убыточная книга выглядела бы
// растущей.
function curve(d){
  const pts = (d.days || []).filter(r => cell(r))
    .map(r => ({day: r.day, v: cell(r).cum}));
  if (pts.length < 2) return "";
  const W = 900, H = 110;
  const hi = Math.max(0, ...pts.map(p => p.v));
  const lo = Math.min(0, ...pts.map(p => p.v));
  const y = v => H - (v - lo) / ((hi - lo) || 1) * H;
  const line = pts.map((p, i) => `${(i / (pts.length - 1) * W)
    .toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  return `<div class="panel"><div class="cap">money of the book,
    day by day (cumulative)</div>
   <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px;
     display:block">
     <line x1="0" y1="${y(0).toFixed(1)}" x2="${W}"
       y2="${y(0).toFixed(1)}" stroke="#8e88ad" stroke-width="1"
       stroke-dasharray="3 3"/>
     <polyline points="${line}" fill="none" stroke="#9747ff"
       stroke-width="1.4"/></svg>
   <div class="k">${esc(pts[0].day)} &rarr; ${
     esc(pts[pts.length - 1].day)} UTC · zero is the dashed line ·
     realised money only</div></div>`;
}
function table(d){
  const rows = (d.days || []).filter(r => cell(r));
  if (!rows.length)
    return `<div class="panel"><div class="dim">no closed trades for
      this arm yet — a book with open positions and no closed ones
      says nothing about money, and that is a state, not a zero</div>
      </div>`;
  return `<div class="panel"><div class="cap">day by day</div>
   <div class="scroll"><table><tr><th>day</th><th>trades</th>
   <th>won</th><th>median</th><th>mean</th><th>$</th>
   <th>&Sigma; $</th><th>$ w/o best</th><th>best trade</th>
   <th>worst trade</th><th>exits</th></tr>` + rows.map(r => {
     const c = cell(r);
     const thin = c.trades < 5;
     return `<tr class="${thin ? "thin" : ""}"
       data-day="${esc(r.day)}">
       <td class="mono">${esc(r.day)}</td>
       <td class="mono">${c.trades}</td>
       <td class="mono">${Math.round(c.win * 100)} %</td>
       <td class="mono ${c.net_med > 0 ? "good" : "bad"}">${
         c.net_med == null ? "&mdash;" : pct(c.net_med)}</td>
       <td class="mono ${c.net_avg > 0 ? "good" : "bad"}">${
         c.net_avg == null ? "&mdash;" : pct(c.net_avg)}</td>
       <td class="mono">${money(c.pnl)}</td>
       <td class="mono">${money(c.cum)}</td>
       <td class="mono">${money(c.pnl_wo_top)}</td>
       <td class="mono">${esc(c.top_sym)} ${money(c.top_pnl)}</td>
       <td class="mono">${money(c.worst_pnl)}</td>
       <td class="k">${exits(c.exits)}</td></tr>`; }).join("")
   + `</table></div><div class="k">A day with fewer than five closed
   trades is greyed: it is an anecdote, not a measurement. «Median»
   and «mean» are the trade itself in per cent of its own notional,
   after costs; the money column is what the cash box actually
   credited, and it depends on position size as well. Exits are why
   the trades of that day ended — for the situational books the share
   of stops is the number that moves first when the geometry stops
   working.</div></div>`;
}
function armBar(){
  const lbl = {all: "both arms", gbm: "trees (gbm)", nn: "net (nn)"};
  document.getElementById("arms").innerHTML =
    `<div class="tabs">` + ARMS.map(a => `<button class="tab"
      data-arm="${a}" aria-pressed="${String(a === ARM)}">${
      lbl[a]}</button>`).join("") + `</div>`;
  document.querySelectorAll("#arms button").forEach(b =>
    b.onclick = () => setArm(b.dataset.arm));
}
function setArm(a){
  if (!ARMS.includes(a)) return;
  ARM = a;
  // Выбранная рука едет в адрес, чтобы страницу можно было переслать
  // уже на нужной. Адрес собирается из `location.search`, а не через
  // `new URL(location.href)`: показ не вправе зависеть от того, какие
  // поля навигации доступны, — таблицу переключить надо в любом
  // случае.
  const q = new URLSearchParams(location.search || "");
  q.set("arm", a);
  window.history.replaceState(null, "", "?" + q.toString());
  render(DATA);
}
function render(d){
  DATA = d;
  if (!d) return;
  document.getElementById("strap").textContent =
    BOOK_NAME + " — day by day";
  document.getElementById("intro").innerHTML = intro(d);
  armBar();
  document.getElementById("box").innerHTML = d.unknown ? "" :
    (tiles(d) + curve(d) + table(d)
     + `<div class="panel"><div class="cap">where else to look</div>
        <div><a href="/trades-page?k=${encodeURIComponent(KEY)}${
        HZ === "h4" ? "" : "&hz=" + encodeURIComponent(HZ)}">every
        trade of this book</a> &nbsp;·&nbsp; <a href="/tree-page?k=${
        encodeURIComponent(KEY)}">the model tree</a>
        &nbsp;·&nbsp; <a href="/league-page?k=${
        encodeURIComponent(KEY)}">the league</a></div></div>`
     + ((d.errors || []).length
        ? `<div class="panel"><div class="cap">books that did not
           build</div><div class="dim">${(d.errors || [])
           .map(esc).join("<br>")}</div><div class="k">the day rows
           are built from the same pass, so a book that failed to
           build is missing from them</div></div>` : ""));
  document.getElementById("lead").textContent =
    (d.days || []).length + " days · " + HZ;
}
async function load(){
  try {
    const r = await fetch("/book_days?k=" + encodeURIComponent(KEY)
      + "&hz=" + encodeURIComponent(HZ));
    render(await r.json());
  } catch (e) {
    document.getElementById("box").innerHTML =
      `<div class="panel"><div class="dim">no answer from the
       collector — the page shows nothing rather than guessing</div>
       </div>`;
  }
}
load();
setInterval(load, 60000);
</script>
"""


# Бумажная месячная книга (`research/paper_monthly`). Своего показа у
# неё не было вовсе: книга писала отчёт файлом в git, и состав траншей —
# что именно она купила и продала — не был виден нигде. Просьба
# владельца: вывести на страницу наблюдения.
#
# Страница НИЧЕГО не считает: свод берётся из артефакта прогона, числа
# исхода — из журнала как есть. Причина та же, по которой показ не
# считает деньги живых книг: вторая реализация однажды разойдётся с
# первой, и экран будет утверждать не то, что опубликовано отчётом.
DCAPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DCA paper books — three modes × three deposits</title>
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
.wrap{max-width:1560px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
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
.thin{color:var(--muted)}
a{color:var(--accent)}
.scroll{overflow-x:auto}
.alarm{border-color:var(--ask);background:rgba(255,100,115,.08)}
.stats{display:grid;gap:10px;
 grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.st{background:var(--chip);border:1px solid var(--rule);border-radius:12px;
 padding:8px 10px}
.st .v{font-size:18px;font-weight:700}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 2px}
.tab{background:var(--chip);border:1px solid var(--rule);border-radius:999px;
 padding:5px 14px;cursor:pointer;font-size:13px;color:var(--muted)}
.tab.on{border-color:var(--accent);color:var(--ink)}
.tag{display:inline-block;font-size:10px;letter-spacing:.1em;
 text-transform:uppercase;border:1px solid var(--rule);border-radius:999px;
 padding:1px 8px;color:var(--muted)}
.tag.fwd{border-color:var(--accent);color:var(--accent)}
tr.pos{cursor:pointer}
tr.pos:hover{background:rgba(151,71,255,.10)}
tr.sub td{background:rgba(255,255,255,.03);font-size:12px}
table.leg td,table.leg th{border-bottom:1px solid var(--rule-soft);
 font-size:12px;padding:3px 8px}
.btn{background:var(--chip);border:1px solid var(--rule);border-radius:999px;
 padding:4px 12px;cursor:pointer;font-size:12.5px;color:var(--muted)}
.btn:hover{border-color:var(--accent);color:var(--ink)}
.btn[disabled]{opacity:.35;cursor:default}
.mback{position:fixed;inset:0;background:rgba(5,3,18,.66);z-index:40}
.mbox{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);
 z-index:41;width:min(820px,94vw);max-height:84vh;overflow:auto;
 background:var(--panel);border:1px solid var(--accent);
 border-radius:14px;padding:16px 18px}
.mx{position:absolute;top:6px;right:10px;background:none;border:0;
 color:var(--muted);font-size:17px;cursor:pointer;padding:2px 6px}
.pg{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:8px 0}
""" + NAVCSS + r"""
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">DCA paper books &mdash; three modes &times; three deposits</span>
  <button class="btn" id="whatbtn">что это</button>
  <span style="flex:1"></span>
  <span class="k" id="lead"></span></div>
<div id="nav"></div>
<div class="panel" id="why" style="display:none"></div>
<div class="tabs" id="rtabs"></div>
<div class="tabs" id="tabs"></div>
<div class="tabs" id="gtabs"></div>
<div id="box">&hellip;</div>
<div id="modal"></div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + LVLJS + r"""
navMount("/dca-page");
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function usd(v){ return v == null ? "&mdash;"
  : (v > 0 ? "+" : "") + Number(v).toFixed(2) + " $"; }
function tsq(t){ return t == null ? "&mdash;"
  : new Date(t * 1000).toISOString().slice(5, 16).replace("T", " "); }
// Свод книги хранит ДОЛИ (0.0684 — это 6.84 %), а общий `pct` говорит
// на базисных пунктах: 0.0684 б.п. печатались как «+0.001 %», и целые
// четыре колонки читались нулями. Перевод стоит ОДНОЙ названной
// функцией — второй формат развёл бы страницу с остальными семью, а
// умножение россыпью по вызовам однажды забылось бы в одном из них.
function fpct(v){ return v == null ? "\u2014" : pct(Number(v) * 1e4); }
let DATA = null, DEP = null, RUL = null, GRP = "all";
// Состояние ПОКАЗА списка позиций. Оно живёт здесь, а не в разметке:
// страница перерисовывается раз в минуту, и выбор, живущий в DOM,
// сбрасывался бы сам (тот же урок, что разворот позиции).
// `PST` — какие позиции показывать, `PAGE`/`SIZE` — окно списка,
// `INTRO` — открыта ли модалка «что это».
let PST = "all", PAGE = 0, SIZE = 20, INTRO = false;
const SIZES = [20, 50];
function dcaState(x){ PST = x; PAGE = 0; render(); }
function dcaSize(n){ SIZE = Number(n); PAGE = 0; render(); }
function dcaPage(n){ PAGE = Math.max(0, Number(n)); render(); }
function dcaIntro(on){ INTRO = !!on; render(); }

// Рамка предмета первым абзацем. Без неё три книги читаются как три
// стратегии, а отличаются они РОВНО депозитом; и «бумажная» здесь
// значит реплей по барам записи, а не живой сканер на живой цене.
function intro(d){
  const r = d.rules || {};
  const dd = (r.DEPOSITS || []).map(
    x => "$" + x.toLocaleString("en-US")).join(" / ");
  // Билет считается ПО РЕЖИМУ: пол и пик у режимов свои. Артефакт
  // прежнего образца нёс один набор билетов на все режимы — тогда
  // печатается он, а не выдуманный по режимам.
  const tks = r.TICKETS || {};
  const perMode = tks && !Array.isArray(tks)
    && Object.values(tks).some(v => v && typeof v === "object");
  const tline = (rk) => {
    const m = perMode ? (tks[rk] || {}) : tks;
    return (r.DEPOSITS || []).map(x => {
      const v = m[String(Math.trunc(x))];
      return v == null ? "&mdash;" : "$" + v;
    }).join(" / ") || "&mdash;";
  };
  let h = "<div class=cap>что это</div>";
  h += "<p><b>Книги отличаются двумя вещами, и только ими: РЕЖИМОМ и " +
    "депозитом</b> (" + esc(dd) + "). Ограда и выходы у всех одни. " +
    "Билет при этом НЕ один &mdash; и это не третья ось: он считается " +
    "ОДНОЙ формулой <code>максимум(пол режима, депозит / (пик режима " +
    "&times; запас))</code>, просто пол и пик у каждого режима свои.</p>";
  h += "<p><b>Пол задаёт биржа, потолок — книга.</b> Минимальный ордер " +
    "$5, мельчайший рунг лестницы 25 % нотионала, значит маржа не " +
    "бывает меньше $5/0.25/плечо. Худшее плечо режима без гейта есть " +
    "1&times; (забор выдаёт от единицы) &mdash; отсюда $20 и, с " +
    "четвертью запаса на просадку, пол $25; у режима с гейтом худший " +
    "случай есть сам гейт, и пол выходит вчетверо ниже. Сверху билет " +
    "ограничен тем, чтобы хватало на ВСЕ места СВОЕГО режима: пик " +
    "измерен по журналу, запас " +
    (r.PEAK_MARGIN == null ? "&mdash;" : r.PEAK_MARGIN + "&times;") +
    " нужен потому, что пик есть максимум выборки. Отсюда главное: " +
    "<b>мелкий депозит наполнить нельзя</b> &mdash; у него связывает " +
    "пол биржи.</p>";
  const rl = d.rulers || [];
  if (rl.length){
    h += "<p><b>Режим</b> &mdash; не настройка агрессивности: плечо " +
      "выводится из неравенства безопасности, и режим задаёт, ИЗ ЧЕГО. ";
    for (const r of rl)
      h += "<b>" + esc(r.title || r.key) + "</b> &mdash; " +
        esc(r.plain || "") + " ";
    // Числа режима таблицей: билет и места видны рядом с полом и пиком,
    // иначе «билеты разные» остаётся словом
    const fl = r.FLOORS || {}, pk = r.PEAKS || {};
    h += "<table><tr><th>режим<th>пол<th>пик<th>билет<th>мест</tr>";
    for (const x of rl){
      const m = perMode ? (tks[x.key] || {}) : tks;
      const sl = (r.DEPOSITS || []).map(dpx => {
        const v = m[String(Math.trunc(dpx))];
        return v == null ? "&mdash;" : String(Math.floor(dpx / v));
      }).join(" / ");
      h += "<tr><td>" + esc(x.title || x.key) + "<td>"
        + (fl[x.key] == null ? "&mdash;" : "$" + fl[x.key]) + "<td>"
        + (pk[x.key] == null
           ? (r.PEAK_SEEN == null ? "&mdash;" : r.PEAK_SEEN) : pk[x.key])
        + "<td>" + tline(x.key) + "<td>" + sl + "</tr>";
    }
    h += "</table>";
    h += "<span class=dim>Имена &mdash; ярлыки, а не вердикт: какой " +
      "режим лучше, покажет форвард, и все ведутся параллельно ровно " +
      "затем, чтобы вопрос решали числа, а не выбор задним числом." +
      (d.rulers_legacy ? " Прогон, породивший артефакт, знал одну " +
        "линейку &mdash; остальные появятся ближайшим суточным." : "") +
      "</span></p>";
    // Режим с ГЕЙТОМ входа обязан назвать порог числом ИЗ ОТВЕТА и
    // сказать, что билет ему считается из ЕГО пола и ЕГО пика: иначе
    // «билеты разные» читается как отдельная ось, а не как одна формула
    for (const r2 of rl.filter(x => x.min_lev != null))
      h += "<p><b>У режима «" + esc(r2.title || r2.key) + "» есть гейт " +
        "входа: плечо не ниже " + r2.min_lev + "&times;.</b> Порог не " +
        "назначен, а взят из ячейки, породившей вопрос: при билете $5 " +
        "биржевой пол требовал ровно такого плеча. Ту ячейку видели ДО " +
        "того, как порог объявили, значит по прошлому режим выбран из " +
        "просмотренной поверхности — вердикт ему выносит только " +
        "запись вперёд. <span class=dim>Билет у него свой, и это не " +
        "второе правило: та же формула от его собственного пола (гейт " +
        "делает пол вчетверо ниже) и его собственного пика (позиций у " +
        "него меньше). До 2026-09-04 пик брался общий, и режим стоял " +
        "недогруженным — был честен по позиции и нечестен по книге. " +
        "Чего это не чинит: гейт срабатывает вспышками, поэтому средняя " +
        "загрузка у него останется ниже соседей — свойство правила, а " +
        "не наш недогруз.</span></p>";
  }
  h += "<p><b>У имени позиция одна</b>" +
    (r.ONE_PER_NAME === false ? " &mdash; правило СНЯТО в этом прогоне" :
     ": второй выбор по той же монете пропущен, как на бирже") + ".</p>";
  h += "<p><b>Записанное вперёд и пересчёт по прошлому не складываются " +
    "нигде.</b> Решение записано вперёд, если попало в журнал не позже " +
    (r.AHEAD_H == null ? "&mdash;" : r.AHEAD_H + " ч") +
    " после себя (предел жизни позиции " +
    (r.HOLD_H == null ? "&mdash;" : r.HOLD_H + " ч") +
    " плюс двое суток на прогон). Первый прогон восстанавливает " +
    "накопленное, и оно всё помечено пересчётом.</p>";
  h += "<p class=dim><b>Чего в числах нет:</b> живого исполнения. Сделки " +
    "считаются реплеем по барам записи, а не сканером на живой цене &mdash; " +
    "значит нет ни проскальзывания, ни очереди в стакане, ни задержки " +
    "входа. Маржа и цена ликвидации считаются по каждой позиции отдельно, " +
    "а биржа считает их по слитой. Веса модели видели эти часы, поэтому " +
    "пересчёт читается как оценка сверху.</p>";
  return h;
}

// Кривая книги рисуется ИЗ ТОГО ЖЕ ряда, из которого посчитана
// просадка: `days_rows` — суточные деньги, и `max_dd` в своде считан
// по ним же. Своей просадки страница НЕ считает намеренно: два числа
// под одним именем однажды разошлись бы, и картинка спорила бы с
// плиткой. Здесь только линия, число приходит с сервера.
function curveSvg(st, dep){
  const rs = (st && st.days_rows) || [];
  if (rs.length < 2) return "<div class=k>Кривой ещё нет: суток в этой " +
    "группе " + rs.length + ". Из одной точки линии не бывает &mdash; " +
    "это не «книга стоит на месте».</div>";
  const W = 1000, H = 210, PL = 6, PR = 6, PT = 12, PB = 20;
  const d0 = Number(dep) || 0;
  let acc = 0;
  const eq = rs.map(r => { acc += Number(r.usd || 0); return d0 + acc; });
  const lo = Math.min(d0, ...eq), hi = Math.max(d0, ...eq);
  const span = (hi - lo) || 1;
  const xw = (W - PL - PR) / (eq.length - 1);
  const yy = v => PT + (H - PT - PB) * (1 - (v - lo) / span);
  const xx = i => PL + i * xw;
  const pts = eq.map((v, i) => xx(i).toFixed(1) + "," + yy(v).toFixed(1));
  const base = yy(d0).toFixed(1);
  const up = eq[eq.length - 1] >= d0;
  const col = up ? "var(--bid)" : "var(--ask)";
  // Заливка до линии депозита: видно, когда книга ниже старта, и это
  // не второе число — та же ломаная, замкнутая на базовую линию.
  const area = "M" + pts[0].split(",")[0] + "," + base + " L" +
    pts.join(" L") + " L" + xx(eq.length - 1).toFixed(1) + "," + base + " Z";
  let h = "<svg viewBox='0 0 " + W + " " + H + "' " +
    "preserveAspectRatio='none' style='width:100%;height:210px;display:block'>";
  h += "<path d='" + area + "' fill='" + col + "' opacity='0.12'/>";
  h += "<line x1='" + PL + "' y1='" + base + "' x2='" + (W - PR) +
    "' y2='" + base + "' stroke='var(--rule)' stroke-dasharray='4 4'/>";
  h += "<polyline points='" + pts.join(" ") + "' fill='none' stroke='" +
    col + "' stroke-width='2' vector-effect='non-scaling-stroke'/>";
  h += "</svg>";
  h += "<div class=k style='display:flex;justify-content:space-between'>" +
    "<span>" + esc(rs[0].d) + " &middot; $" + d0.toLocaleString("en-US") +
    "</span><span>" + esc(rs[rs.length - 1].d) + " &middot; $" +
    eq[eq.length - 1].toFixed(2) + "</span></div>";
  return h;
}

function statBlock(st, dep, title, op, grp){
  const gname = grp === "fwd" ? "записанное вперёд" : "бэктест и записанное вперёд";
  if (!st) return "<div class=panel><div class=cap>" + esc(title) +
    "</div><p class=dim>Строк ещё нет. У книги это не пустота показа: " +
    "решение попадает в журнал только после того, как его позиция " +
    "закрылась.</p></div>";
  const cls = v => v == null ? "" : (v > 0 ? "good" : (v < 0 ? "bad" : ""));
  let h = "<div class=panel><div class=cap>" + esc(title) +
    " <span class='tag " + (grp === "fwd" ? "fwd" : "") + "'>" +
    esc(grp === "fwd" ? "наблюдение" : "общий счёт") + "</span></div>";
  h += "<div class=stats>";
  const cells = [
    // ПОЗИЦИЙ, а не сделок: позиция есть лестница, и каждый её долив —
    // свой вход. Числа стоят рядом, чтобы их нельзя было спутать.
    ["закрытых позиций", st.n, null],
    ["входов (с доливами)", st.fills == null ? "&mdash;" : st.fills, null],
    ["из них бэктест", st.n_bt == null ? "&mdash;" : st.n_bt, null],
    ["имён", st.names, null],
    ["дней", st.days, null],
    ["деньги", usd(st.usd), cls(st.usd)],
    ["к депозиту", fpct(st.final), cls(st.final)],
    // Просадка ДЕПОЗИТА по закрытым позициям: глубочайший провал
    // накопленного счёта от его же вершины. Считается по тем же суткам,
    // по которым нарисована кривая выше.
    ["просадка депозита", fpct(st.max_dd), cls(st.max_dd)],
    // Доля прибыльных ПОЗИЦИЙ — не то же, что доля зелёных ДНЕЙ:
    // знаменатели разные, и путать их значит отвечать не на тот вопрос.
    ["прибыльных сделок", st.win == null ? "&mdash;" :
      (st.win * 100).toFixed(1) + " %", null],
    ["среднее время в сделке", st.hold_h == null ? "&mdash;" :
      Number(st.hold_h).toFixed(1) + " ч", null],
    ["медиана дня", fpct(st.day_median), cls(st.day_median)],
    ["худший день", fpct(st.day_worst), cls(st.day_worst)],
    ["зелёных дней", st.day_green == null ? "&mdash;" :
      Number(st.day_green).toFixed(2), null],
    ["укус", st.bite == null ? "&mdash;" : st.bite, null],
    ["$ без лучшего имени", usd(st.usd_wo_top), cls(st.usd_wo_top)],
    ["$ без 3 лучших дней", st.usd_wo_top3d == null ? "&mdash;" :
      usd(st.usd_wo_top3d), cls(st.usd_wo_top3d)]];
  for (const [k, v, c] of cells)
    h += "<div class=st><div class=k>" + k + "</div><div class='v mono " +
      (c || "") + "'>" + (v == null ? "&mdash;" : v) + "</div></div>";
  // Открытое НИКОГДА не складывается с закрытым: у закрытой позиции
  // исход известен, у открытой это ОТМЕТКА, и до выхода она станет
  // любой. `live_known === false` значит «не считали» — прочерк с
  // названной причиной, а не ноль. Открытые стоят в блоке при ЛЮБОЙ
  // группе: это состояние СЕЙЧАС, а не часть выбранной кривой.
  if (op !== undefined){
    const kn = op && op.known !== false;
    const n = kn && op.positions ? op.positions.length : null;
    const cut = kn && op.cut ? op.cut.length : null;
    h += "<div class=st><div class=k>открытых позиций</div>" +
      "<div class='v mono'>" + (kn ? n : "&mdash;") + "</div></div>";
    h += "<div class=st><div class=k>открытый pnl</div>" +
      "<div class='v mono " + (kn ? cls(op.mark_usd) : "") + "'>" +
      (kn ? usd(op.mark_usd) : "&mdash;") + "</div></div>";
    // Худшая ОТКРЫТАЯ — просадка, которую книга несёт прямо сейчас.
    // Считает сервер (`rules.open_stats`): страница печатает её дважды,
    // и вторая арифметика разошлась бы с первой.
    h += "<div class=st><div class=k>худшая открытая</div>" +
      "<div class='v mono " + (kn ? cls(op.worst_frac) : "") + "'>" +
      (kn && op.worst_frac != null ? fpct(op.worst_frac) : "&mdash;") +
      "</div></div>";
    if (kn && cut) h += "<div class=st><div class=k>оборвано записью</div>" +
      "<div class='v mono'>" + cut + "</div></div>";
  }
  h += "</div>";
  // Кривая идёт СРАЗУ под числами и по той же группе: подпись говорит,
  // чем она набрана, иначе «одна кривая» читается как живой трек.
  h += "<div style='margin-top:10px'>" + curveSvg(st, dep) + "</div>";
  h += "<div class=k>Кривая — накопленный счёт по ЗАКРЫТЫМ позициям от " +
    "депозита; открытые в неё не входят. Группа: " + esc(gname) + ". " +
    "Просадка в плитке считана по этому же ряду, и второго её счёта на " +
    "странице нет.</div>";
  if (op !== undefined && !(op && op.known !== false))
    h += "<div class=k style='margin-top:8px'>Открытых не считали: свод " +
      "пересобран из журнала (<code>--restat</code>), а открытые позиции " +
      "в журнал не идут вовсе &mdash; их отметка меняется каждый час. " +
      "Прочерк здесь значит «не смотрели», а не «открытых нет».</div>";
  else if (op !== undefined) h += "<div class=k style='margin-top:8px'>" +
    "Открытый pnl &mdash; ОТМЕТКА по последней цене записи, а не исход: " +
    "с закрытым счётом он не складывается нигде" +
    (op.at ? " (снята " + tsq(op.at) + " UTC)" : "") +
    (op.worst_sym ? ". Глубже всех сейчас " + esc(op.worst_sym) + " (" +
      fpct(op.worst_frac) + " &middot; " + usd(op.worst_usd) + ")" : "") +
    ".</div>";
  if (st.top_sym) h += "<div class=k style='margin-top:8px'>лучшее имя " +
    esc(st.top_sym) + " &mdash; колонка рядом показывает итог без него: " +
    "деньги из одного разгона статистикой не являются. Соседняя колонка " +
    "вычитает три лучших ДНЯ: один рыночный эпизод раздаёт деньги " +
    "десяткам имён разом, и по именам он невидим" +
    (st.usd_wo_top3d == null ? " (у книги моложе четырёх дней вычитать " +
      "нечего &mdash; там прочерк, а не ноль)" : "") + "</div>";
  return h + "</div>";
}

// Какие позиции РАЗВЁРНУТЫ — состояние ПОКАЗА, и живёт оно в наборе
// страницы, а не в разметке: страница перерисовывается каждую минуту, и
// разворот, живущий в DOM, сворачивался бы сам (урок панели сделок).
const OPEN = new Set();
function rowKey(r){ return String(Math.trunc(r.at)) + ":" + r.sym; }

// Плавающая ТВХ приходит ГОТОВОЙ с сервера (`rules.avg_walk`): долив
// опускает среднюю цену входа, и по одной цене позицию из четырёх
// рунгов не прочитать. Второй реализации здесь нет намеренно — она
// разошлась бы с симуляцией, посчитавшей эту же позицию.

function keyId(k){ return String(k).replace(/[^a-z0-9]+/gi, "-"); }
// Ключ часа В ТОМ ЖЕ формате, что у книг модели: график ищет по нему
// сделку, ради которой его открыли.
function hourKey(ts){
  const d = new Date(Number(ts) * 1000);
  const p = n => String(n).padStart(2, "0");
  return d.getUTCFullYear() + "-" + p(d.getUTCMonth() + 1) + "-" +
    p(d.getUTCDate()) + "-" + p(d.getUTCHours());
}

// Разворот — состояние ПОКАЗА, и пишется оно в набор ДО работы с
// разметкой: строки может не оказаться на месте (страница
// перерисовывается раз в минуту), но намерение от этого не исчезает.
function dcaToggle(key){
  const id = keyId(key);
  if (OPEN.has(key)) OPEN.delete(key); else OPEN.add(key);
  const open = OPEN.has(key);
  const r = document.getElementById("ddet-" + id);
  const b = document.getElementById("dexp-" + id);
  if (r) r.style.display = open ? "table-row" : "none";
  if (b) b.innerHTML = open ? "&#9662;" : "&#9656;";
}

function fillRows(r, key, live){
  // Раскрытая позиция: КАЖДЫЙ вход своей строкой и ТВХ после него.
  // Свёрнутая строка описывает позицию целиком и молчит о том, чем её
  // набирали и по какой цене она в итоге стоит.
  const w = r.walk || [];
  let h = "<table class=leg style='width:100%'><tr><th>когда<th>нога" +
    "<th>цена<th>доля<th>ТВХ после<th>что это</tr>";
  w.forEach((f, i) => {
    h += "<tr><td class=mono>" + (f.at == null ? "&mdash;" : tsq(f.at)) +
      "<td>" + (i ? "долив " + i : "вход") +
      "<td class=mono>" + Number(f.px).toPrecision(6) +
      "<td class=mono>" + (f.w * 100).toFixed(0) + " %" +
      "<td class=mono>" + Number(f.avg).toPrecision(6) +
      "<td class=dim>" + (i ? "цена дошла до структурного уровня" :
        "первый рунг по сигналу модели") + "</tr>";
  });
  // У ОТКРЫТОЙ позиции выхода не существует: последняя строка — не
  // исход, а отметка по последней цене записи, и подписана она так же.
  // Выдать отметку строкой «выход» значило бы придумать сделке цену, по
  // которой никто не выходил.
  if (live) h += "<tr><td class=mono>" +
    (r.last_ts ? tsq(r.last_ts) : "&mdash;") + "<td>ещё открыта" +
    "<td class=mono>&mdash;" +
    "<td class=mono>" + (r.depth == null ? "&mdash;" :
      "рунгов " + r.depth) +
    "<td class='mono " + (r.mark_usd > 0 ? "good" : "bad") + "'>" +
    fpct(r.mark_frac) + " &middot; " + usd(r.mark_usd) +
    "<td class=dim>отметка, а не исход</tr></table>";
  else h += "<tr><td class=mono>" + tsq(r.exit_ts) + "<td>выход" +
    "<td class=mono>" + (r.exit_px == null ? "&mdash;" :
      Number(r.exit_px).toPrecision(6)) +
    "<td class=mono>" + (r.depth == null ? "&mdash;" :
      "рунгов " + r.depth) +
    "<td class='mono " + (r.usd > 0 ? "good" : "bad") + "'>" +
    fpct(r.pnl_frac) + " &middot; " + usd(r.usd) +
    "<td class=dim>" + esc(r.exit || "") + "</tr></table>";
  // Ширина детали равна ширине таблицы: список ОДИН на все состояния,
  // и колонок в нём двенадцать.
  return "<tr class=sub id='ddet-" + esc(keyId(key)) + "' style='display:" +
    (OPEN.has(key) ? "table-row" : "none") + "'><td colspan=12>" +
    h + "</td></tr>";
}

// Список позиций ОДИН на все состояния (решение владельца
// 2026-09-04): закрытые, открытые и оборванные записью стоят вместе,
// а какие показывать — выбирает переключатель. Три таблицы подряд
// отвечали на один вопрос трижды, и найти в них позицию по монете
// было нечем.
//
// Чего объединение НЕ отменяет: открытое не складывается с закрытым
// нигде. Плитки счёта считают их порознь по-прежнему, а в строке
// деньги не-закрытой позиции подписаны отметкой — до выхода она
// станет любой.
function unifiedRows(b){
  const out = [];
  for (const r of (b.trades || []))
    out.push(Object.assign({}, r, {st: "closed"}));
  const op = b.open || {};
  for (const r of (op.positions || []))
    out.push(Object.assign({}, r, {st: "open"}));
  for (const r of (op.cut || []))
    out.push(Object.assign({}, r, {st: "cut"}));
  // Свежие сверху: список отвечает на «что происходит», а не на «с
  // чего книга начиналась».
  out.sort((a, b2) => (b2.at || 0) - (a.at || 0));
  return out;
}

const STATES = [["all", "все"], ["closed", "закрытые"],
                ["open", "открытые"], ["cut", "оборванные записью"]];
function stTitle(k){
  const f = STATES.find(x => x[0] === k);
  return f ? f[1] : k;
}

function posBlock(b, grp){
  const all = unifiedRows(b);
  // Группа «без бэктеста» режет ЗАКРЫТЫЕ: пометки пересчёта у открытой
  // не бывает вовсе — она не в журнале. Прятать её вместе с бэктестом
  // значило бы объявить её пересчётом.
  const inGrp = all.filter(r => grp !== "fwd" || r.st !== "closed" || !r.bt);
  const cnt = {all: inGrp.length, closed: 0, open: 0, cut: 0};
  for (const r of inGrp) cnt[r.st] = (cnt[r.st] || 0) + 1;
  const rows = PST === "all" ? inGrp : inGrp.filter(r => r.st === PST);
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / SIZE));
  const pg = Math.min(PAGE, pages - 1);
  const from = pg * SIZE;
  const win = rows.slice(from, from + SIZE);
  let h = "<div class=panel><div class=cap>позиции книги &mdash; " +
    total + "</div>";
  // Переключатель состояния: счётчик стоит В САМОМ чипе, иначе выбрать
  // пустую вкладку можно вслепую.
  h += "<div class=tabs>" + STATES.map(([k, t]) =>
    "<div class='tab" + (k === PST ? " on" : "") + "' data-st='" + k +
    "'>" + t + " <span class=dim>" + (cnt[k] || 0) + "</span></div>")
    .join("") + "</div>";
  h += "<p class=k>Одна строка &mdash; ОДНА ПОЗИЦИЯ по паре: доливы " +
    "лестницы живут внутри неё, а не отдельными сделками. Нажмите " +
    "строку, чтобы увидеть каждый вход, ТВХ после него и выход; " +
    "ссылка справа открывает график этой позиции. " +
    (grp === "fwd"
      ? "Строк пересчёта по прошлому здесь нет вовсе: список следует за "
        + "переключателем группы."
      : "Пометка <span class=tag>бэктест</span> означает пересчёт по "
        + "прошлому: он идёт в ОБЩЕЙ кривой, а числа групп стоят рядом "
        + "отдельно.") +
    " У открытой и оборванной записью деньги &mdash; ОТМЕТКА по " +
    "последней цене записи, а не исход, и с закрытым счётом они не " +
    "складываются нигде." +
    (b.live_known === false ? " Открытых в этом прогоне не считали " +
      "(свод пересобран из журнала, а открытые в журнал не идут) " +
      "&mdash; это не «открытых нет»." : "") + "</p>";
  // Оборванная записью — НЕ открытая на бирже, и сказать это надо там,
  // где такие строки есть: у них кончился ряд цен своего символа
  // раньше, чем у остальных, и исход неизвестен. Закрытыми «по сроку»
  // они не считаются — это значило бы выдумать исход.
  if (cnt.cut) h += "<p class=k>Оборванных записью " + cnt.cut + ": это " +
    "НЕ открытые позиции на бирже &mdash; у них кончился ряд цен своего " +
    "символа раньше, чем у остальных. Закрытыми «по сроку» они не " +
    "считаются: это значило бы выдумать исход, &mdash; и в счёт книги " +
    "не входят. Число их само по себе наблюдение.</p>";
  // Окно списка: владелец просил 20–50 строк за раз. Размер и страница
  // — состояние показа, оно живёт в наборе страницы.
  h += "<div class=pg>";
  h += "<span class=k>в окне</span>";
  for (const n of SIZES)
    h += "<button class='btn" + (n === SIZE ? " on" : "") +
      "' data-size='" + n + "'" + (n === SIZE ? " disabled" : "") + ">" +
      n + "</button>";
  h += "<span style='flex:1'></span>";
  h += "<button class=btn data-page='" + (pg - 1) + "'" +
    (pg <= 0 ? " disabled" : "") + ">&#8592;</button>";
  h += "<span class='k mono'>" + (total ? (from + 1) : 0) + "&ndash;" +
    Math.min(total, from + SIZE) + " из " + total + "</span>";
  h += "<button class=btn data-page='" + (pg + 1) + "'" +
    (pg >= pages - 1 ? " disabled" : "") + ">&#8594;</button>";
  h += "</div>";
  if (!total) return h + "<p class=dim>В выбранном состоянии («" +
    esc(stTitle(PST)) + "») позиций нет. Это измерено, а не пропуск " +
    "показа: счётчик в переключателе говорит, где они есть.</p></div>";
  h += "<div class=scroll><table><tr><th>вход<th>выход<th>монета" +
    "<th>плечо<th>маржа<th>цена входа<th>ТВХ<th>цена выхода" +
    "<th>ход<th>деньги<th>исход<th>график</tr>";
  for (const r of win){
    const live = r.st !== "closed";
    // Деньги закрытой — ИСХОД, у остальных ОТМЕТКА. Поля разные, и
    // читать их одним именем значило бы выдать отметку за результат.
    const frac = live ? r.mark_frac : r.pnl_frac;
    const money = live ? r.mark_usd : r.usd;
    const c = money == null ? "" : (money > 0 ? "good" : "bad");
    const key = (live ? (r.st === "cut" ? "c" : "o") : "") + rowKey(r);
    const id = keyId(key), o = OPEN.has(key);
    const nf = (r.fills || []).length;
    h += "<tr class=pos onclick=\"dcaToggle('" + esc(key) + "')\">" +
      "<td class=mono><span id='dexp-" + esc(id) + "'>" +
      (o ? "&#9662;" : "&#9656;") + "</span> " + tsq(r.at) +
      // У открытой и оборванной выхода НЕ СУЩЕСТВУЕТ — прочерк, а не
      // последняя цена записи: выдать отметку за выход значило бы
      // придумать сделке цену, по которой никто не выходил.
      "<td class=mono>" + (live ? "&mdash;" : tsq(r.exit_ts)) +
      "<td>" + esc(r.sym) +
      (r.bt ? " <span class=tag>бэктест</span>" : "") +
      "<td class=mono>" + (r.lev == null ? "&mdash;" :
        Number(r.lev).toFixed(2) + "&times;") +
      "<td class=mono>" + (r.margin == null ? "&mdash;" :
        Number(r.margin).toFixed(2) + " $") +
      "<td class=mono>" + (r.entry_px == null ? "&mdash;" :
        Number(r.entry_px).toPrecision(6)) +
      // ТВХ — плавающая средняя цена входа: долив опускает её, и по
      // одной цене позицию из четырёх рунгов не прочитать. Приходит
      // готовой с сервера (`rules.avg_walk`).
      "<td class=mono>" + (r.avg == null ? "&mdash;" :
        Number(r.avg).toPrecision(6)) +
      "<td class=mono>" + (live || r.exit_px == null ? "&mdash;" :
        Number(r.exit_px).toPrecision(6)) +
      "<td class='mono " + c + "'>" + fpct(frac) +
      "<td class='mono " + c + "'>" + usd(money) +
      (live ? " <span class=tag>отметка</span>" : "") +
      "<td>" + (r.st === "cut" ? "<span class=dim>оборвана записью</span>"
        : (r.st === "open" ? "открыта" : esc(r.exit || ""))) +
      (nf > 1 ? " <span class=dim>&middot; рунгов " + nf + "</span>" : "") +
      // График этой позиции: свечи записи, точки доливов и ступенчатая
      // ТВХ. Ключ книги едет в ссылке — без него график молча показал
      // бы выборы модели вместо лестницы.
      "<td><a href='/chart?k=" + encodeURIComponent(KEY) + "&sym=" +
      encodeURIComponent(r.sym) + "&dca=" +
      encodeURIComponent(RUL + ":" + DEP) + "&hour=" +
      encodeURIComponent(hourKey(r.at)) + "' onclick='event.stopPropagation()'" +
      ">открыть</a>" +
      "</tr>";
    // Деталь стоит в разметке ВСЕГДА и лишь скрыта: разворот тогда не
    // требует перерисовки страницы, а проверить его можно прогоном.
    h += fillRows(r, key, live);
  }
  return h + "</table></div></div>";
}

function dayTable(st, dep, title){
  // Итог книги отвечает «сколько всего» и молчит о том, КОГДА: сумма за
  // месяц может стоять на одном дне. Тонкий день приглушён, но НЕ
  // спрятан — прятать наблюдение значит подгонять картину.
  const rs = (st && st.days_rows) || [];
  if (!rs.length) return "";
  let h = "<div class=panel><div class=cap>" + esc(title) + " &mdash; " +
    rs.length + " суток</div><div class=scroll><table><tr><th>сутки UTC" +
    "<th>позиций<th>из них бэктест<th>деньги<th>к депозиту" +
    "<th>накопленным итогом</tr>";
  let acc = 0;
  for (const r of rs){
    acc += Number(r.usd || 0);
    const c = r.usd > 0 ? "good" : (r.usd < 0 ? "bad" : "");
    h += "<tr" + (r.n < 5 ? " class=thin" : "") + "><td class=mono>" +
      esc(r.d) + "<td class=mono>" + r.n +
      "<td class=mono>" + (r.bt == null ? "&mdash;" : r.bt) +
      "<td class='mono " + c + "'>" + usd(r.usd) +
      "<td class='mono " + c + "'>" + (dep ? fpct(r.usd / Number(dep)) :
        "&mdash;") +
      "<td class='mono " + (acc > 0 ? "good" : "bad") + "'>" + usd(acc) +
      "</tr>";
  }
  return h + "</table></div><div class=k>Накопленный итог идёт по ОБЩЕЙ " +
    "кривой: бэктест и записанное вперёд ведутся одним счётом, и " +
    "колонка «из них бэктест» говорит, чем именно набран день.</div></div>";
}

function render(){
  const d = DATA, box = document.getElementById("box");
  // Рамка «что это» уехала в МОДАЛКУ (решение владельца 2026-09-04):
  // она длинная, а страница нужна ради чисел. Утверждения из неё не
  // выброшены — они по кнопке, и это разные вещи.
  const mod = document.getElementById("modal");
  mod.innerHTML = (INTRO && d && d.present)
    ? "<div class=mback onclick='dcaIntro(false)'></div>" +
      "<div class=mbox><button class=mx onclick='dcaIntro(false)'>" +
      "&times;</button>" + intro(d) + "</div>"
    : "";
  const wb = document.getElementById("whatbtn");
  if (wb) wb.onclick = () => dcaIntro(true);
  // Отказ сборщика в модалку НЕ прячется: причину надо видеть сразу,
  // а не по нажатию — иначе пустая страница выглядит просто пустой.
  const why = document.getElementById("why");
  why.style.display = (d && d.present) ? "none" : "block";
  if (!(d && d.present))
    why.innerHTML = "<div class=cap>что это</div><p class=dim>" +
      esc((d && d.why) || "нет ответа сборщика") + "</p>";
  const tabs = document.getElementById("tabs");
  if (!d || !d.present){
    tabs.innerHTML = ""; box.innerHTML = "";
    document.getElementById("rtabs").innerHTML = "";
    document.getElementById("gtabs").innerHTML = "";
    return; }
  const deps = d.deposits || [];
  const ruls = d.rulers || [];
  if (DEP == null && deps.length) DEP = String(Math.trunc(deps[0]));
  // умолчание — ПЕРВАЯ линейка порядка (безопасная): книга, которую
  // показывают по умолчанию, не должна быть той, что рискует больше
  if (RUL == null && ruls.length) RUL = ruls[0].key;
  const rtabs = document.getElementById("rtabs");
  rtabs.innerHTML = ruls.map(r =>
    "<div class='tab" + (r.key === RUL ? " on" : "") + "' data-rul='" +
    esc(r.key) + "'>" + esc(r.title || r.key) + "</div>").join("");
  for (const el of rtabs.querySelectorAll(".tab"))
    el.onclick = () => { RUL = el.dataset.rul; render(); };
  tabs.innerHTML = deps.map(x => {
    const k = String(Math.trunc(x));
    return "<div class='tab" + (k === DEP ? " on" : "") +
      "' data-dep='" + k + "'>$" + Number(x).toLocaleString("en-US") +
      "</div>";
  }).join("");
  for (const el of tabs.querySelectorAll(".tab"))
    el.onclick = () => { DEP = el.dataset.dep; render(); };
  // Умолчание — «с бэктестом»: это общий счёт книги, и он же кривая,
  // которую владелец просил не делить. «Без бэктеста» стоит рядом
  // ровно затем, чтобы вклад пересчёта по прошлому можно было снять
  // одним нажатием, а не читать его в третьем блоке.
  const gtabs = document.getElementById("gtabs");
  const gl = [["all", "с бэктестом"], ["fwd", "без бэктеста"]];
  gtabs.innerHTML = gl.map(([k, t]) =>
    "<div class='tab" + (k === GRP ? " on" : "") + "' data-grp='" + k +
    "'>" + t + "</div>").join("");
  for (const el of gtabs.querySelectorAll(".tab"))
    el.onclick = () => { GRP = el.dataset.grp; render(); };
  // ключ книги несёт ОБЕ оси: склеив их по депозиту, страница показала
  // бы одну книгу под именем другой
  const b = (d.books || {})[RUL + ":" + DEP] || {};
  let h = "";
  if (d.stale) h += "<div class='panel alarm'><b>Суточный прогон не " +
    "пришёл</b>, артефакту " + (d.age_h == null ? "&mdash;" : d.age_h) +
    " ч. Числа ниже описывают ТОТ прогон, а не сегодняшний день.</div>";
  const rmeta = (ruls.find(r => r.key === RUL) || {});
  h += "<div class=panel><div class=cap>книга</div><div class=stats>" +
    "<div class=st><div class=k>режим</div><div class='v'>" +
    esc(rmeta.title || RUL || "&mdash;") + "</div></div>" +
    "<div class=st><div class=k>депозит</div><div class='v mono'>$" +
    Number(b.deposit || DEP).toLocaleString("en-US") + "</div></div>" +
    "<div class=st><div class=k>мест</div><div class='v mono'>" +
    (b.slots == null ? "&mdash;" : b.slots) + "</div></div>" +
    "<div class=st><div class=k>билет</div><div class='v mono'>" +
    (b.ticket == null ? "&mdash;" : "$" + b.ticket) + "</div></div>" +
    "<div class=st><div class=k>строк в журнале</div><div class='v mono'>" +
    (b.n_journal == null ? "&mdash;" : b.n_journal) + "</div></div>" +
    "</div></div>";
  // Групп ДВЕ, и они переключателем, а не тремя блоками подряд
  // (решение владельца 2026-09-04): «с бэктестом» — общий счёт одной
  // кривой, «без бэктеста» — только записанное вперёд. Третьей группы
  // («пересчёт по прошлому») больше нет: она есть первая минус вторая,
  // и держать её отдельным блоком значило приглашать сложить их.
  const st = GRP === "fwd" ? b.forward : b.all;
  const op = (b.live_known === false) ? {known: false}
    : (b.open ? Object.assign({}, b.open, {known: true}) : undefined);
  h += statBlock(st, b.deposit || DEP,
                 GRP === "fwd" ? "счёт без бэктеста: записанное вперёд"
                               : "счёт с бэктестом: одна кривая",
                 op, GRP);
  h += dayTable(st, b.deposit || DEP, "по суткам");
  if (!d.journal_present) h += "<div class=panel><p class=dim>Журнала на " +
    "этой машине нет вовсе &mdash; он живёт там, где книги считаются. " +
    "Это не то же самое, что «сделок нет».</p></div>";
  // ОДИН список на все состояния, окном по 20–50 строк. Он следует за
  // переключателем группы: показывать строки бэктеста под числами
  // группы «без бэктеста» значило бы, что таблица описывает не тот
  // счёт, что стоит над ней.
  h += posBlock(Object.assign({}, b, {open: op && op.known === false
                                        ? null : op}), GRP);
  box.innerHTML = h;
  // Обработчики нового блока вешаются ПОСЛЕ вставки разметки: чипы
  // состояния и кнопки окна — состояние показа, и живёт оно в наборе
  // страницы, а не в разметке.
  for (const el of box.querySelectorAll("[data-st]"))
    el.onclick = () => dcaState(el.dataset.st);
  for (const el of box.querySelectorAll("[data-size]"))
    el.onclick = () => dcaSize(el.dataset.size);
  for (const el of box.querySelectorAll("[data-page]"))
    el.onclick = () => dcaPage(el.dataset.page);
  document.getElementById("lead").textContent = d.window
    ? ("окно решений " + d.window.from + " … " + d.window.to + " UTC")
    : "";
}

function load(){
  fetch("/dca?k=" + encodeURIComponent(KEY))
    .then(r => r.json()).then(j => { DATA = j; render(); })
    .catch(() => { DATA = {present: false, why:
      "сборщик не отвечает &mdash; это не «книг нет»"}; render(); });
}
load();
setInterval(load, 60000);
</script>
"""

PAPERPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>monthly book — one construction, recorded forward</title>
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
.wrap{max-width:1560px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
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
.thin{color:var(--muted)}
a{color:var(--accent)}
.scroll{overflow-x:auto}
.big{font-size:19px;font-weight:700}
.alarm{border-color:var(--ask);background:rgba(255,100,115,.08)}
.two{display:grid;gap:12px;
 grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
tr.pick{cursor:pointer}
tr.pick:hover td{background:var(--chip)}
tr.on td{background:var(--chip)}
.tag{display:inline-block;font-size:10px;letter-spacing:.1em;
 text-transform:uppercase;border:1px solid var(--rule);border-radius:999px;
 padding:1px 8px;color:var(--muted)}
.tag.fwd{border-color:var(--accent);color:var(--accent)}
""" + NAVCSS + r"""
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">monthly book — one construction, recorded forward</span>
  <span style="flex:1"></span>
  <span class="k" id="lead"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div id="box">&hellip;</div>
<div id="legs"></div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + LVLJS + r"""
navMount("/paper-page");
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function num(v, dg){ return v == null ? "&mdash;"
  : (v > 0 ? "+" : "") + Number(v).toFixed(dg == null ? 2 : dg); }
let DATA = null, OPEN = null;

// Рамка предмета — первым абзацем. Без неё страница читается как ещё
// одна книга живого цикла, а это другая конструкция и другой смысл:
// здесь нет ни модели, ни слотов, ни кассы — одна объявленная
// кросс-секция, транш в день, удержание месяц, бумага.
function intro(d){
  const r = d.rules || {};
  return `<div class="cap">what this page is</div>
  <div>A <b>paper</b> book, not one of the live model books: no model,
  no slots, no cash account. One construction declared before the first
  run — formation ${r.k} d, hold ${r.h} d, decile, market wave,
  β over 90 d, ${lvl(r.cost_bp)} cost per tranche — and a new tranche
  opened every day. There is no grid here: the book tests ONE
  construction rather than picking the best of many.</div>
  <div class="k" style="margin-top:6px"><b>Recorded forward</b> means
  the decision was in the journal before its forward window began; it
  is a real observation. <b>Backfilled</b> means it was computed after
  the fact — a backtest, no better and no worse than the probe that
  preceded this book. The two are never added together and never share
  a curve: half a curve of hindsight would still look like a track
  record. The probe measured this signal at roughly +0.33 % a month
  after the survivorship fix, with t = 1.06 by Newey–West — which is
  why no spec was written and why the only lever left is the calendar.
  This book exists to spend it.</div>`;
}

function fresh(d){
  if (!d.stale) return "";
  const h = Math.round((d.run_age_sec || 0) / 3600);
  const lim = Math.round((d.stale_after_sec || 0) / 3600);
  return `<div class="panel alarm"><b>the nightly run did not come
    through</b> — this table is ${h} h old, and anything past ${lim} h
    means the daily chain (storage refresh, then the book) did not
    finish. The numbers below describe the run that produced the file,
    not today.</div>`;
}

// Свод — ДВЕ панели рядом, и они не складываются никогда. Это то же
// правило, по которому открытые деньги не суммируются с закрытыми:
// величины разного вида под одной чертой читаются как одна.
function summary(d){
  const s = d.summary || {};
  const card = (key, name, note) => {
    const g = s[key] || {};
    if (!g.tranches)
      return `<div class="panel"><div class="cap">${name}</div>
        <div class="dim">no tranches in this group yet</div>
        <div class="k" style="margin-top:6px">${note}</div></div>`;
    return `<div class="panel"><div class="cap">${name}</div>
      <div class="mono big ${g.net_mean_bp > 0 ? "good" : "bad"}">${
        pct(g.net_mean_bp)}</div>
      <div class="k">net per tranche, mean over ${g.tranches}
        tranches (${esc(g.from)} … ${esc(g.to)})</div>
      <table style="margin-top:8px">
        <tr><td>gross</td><td class="mono">${pct(g.gross_mean_bp)}</td>
            <td>net median</td>
            <td class="mono">${pct(g.net_median_bp)}</td></tr>
        <tr><td>share &gt; 0</td>
            <td class="mono">${g.net_pos_share == null ? "&mdash;"
              : (100 * g.net_pos_share).toFixed(0) + " %"}</td>
            <td>funding</td>
            <td class="mono">${pct(g.funding_mean_bp)}</td></tr>
        <tr><td>t naive</td><td class="mono">${num(g.t_naive)}</td>
            <td>t Newey–West</td>
            <td class="mono">${num(g.t_nw)}</td></tr>
        <tr><td>independent</td>
            <td class="mono">${g.independent == null ? "&mdash;"
              : g.independent}</td>
            <td>t independent</td>
            <td class="mono">${num(g.t_independent)}</td></tr>
      </table><div class="k" style="margin-top:6px">${note}</div></div>`;
  };
  return `<div class="two">` + card("ahead", "recorded forward",
      "the honest group: these decisions were written before their "
      + "forward window opened. The threshold declared for it is t ≥ 3 "
      + "over independent sections — twelve of those a year, so this "
      + "is a matter of years.")
    + card("backfilled", "backfilled",
      "computed after the fact. Not a track record, and it is kept "
      + "apart from the honest group rather than merged into it: the "
      + "two numbers are never summed.")
    + `</div>`;
}

function tranches(d){
  const rows = d.tranches || [];
  if (!rows.length)
    return `<div class="panel"><div class="dim">${d.journal_present
      ? "the journal holds no decisions yet"
      : "no journal on this machine — the book writes it where it "
        + "runs, and only the reports travel in git. This is not "
        + "«no tranches», it is «not the machine that keeps them»"
      }</div></div>`;
  return `<div class="panel"><div class="cap">tranches — one per day,
    click a row for its legs</div>
   <div class="scroll"><table><tr><th>date</th><th>group</th>
   <th>legs</th><th>state</th><th>gross</th><th>funding</th>
   <th>net</th><th>cut legs</th><th>coverage</th></tr>`
   + rows.slice().reverse().map(r => {
     const open = r.state === "open";
     return `<tr class="pick${OPEN === r.at ? " on" : ""}"
       data-at="${esc(r.at)}">
     <td class="mono">${esc(r.at)}</td>
     <td><span class="tag ${r.ahead ? "fwd" : ""}">${
        r.ahead ? "forward" : "backfilled"}</span></td>
     <td class="mono">${r.legs_n} <span class="k">${r.long_n}L/${
        r.short_n}S</span></td>
     <td class="${open ? "dim" : ""}">${open
        ? `matures ${esc(r.matures_at)} <span class="k">(${
            r.days_left} d)</span>` : "closed"}</td>
     <td class="mono">${open ? "&mdash;" : pct(r.gross_bp)}</td>
     <td class="mono">${open ? "&mdash;" : pct(r.funding_bp)}</td>
     <td class="mono ${open ? "dim"
        : (r.net_bp > 0 ? "good" : "bad")}">${
        open ? "&mdash;" : pct(r.net_bp)}</td>
     <td class="mono ${open ? "dim" : ""}">${open ? "&mdash;"
        : (r.truncated_legs == null ? "&mdash;" : r.truncated_legs)}</td>
     <td class="mono ${open ? "dim" : ""}">${open ? "&mdash;"
        : (r.coverage_median == null ? "&mdash;"
           : r.coverage_median.toFixed(2))}</td></tr>`; }).join("")
   + `</table></div>` + legend(d) + `</div>`;
}

// Расшифровка ВСЕХ пометок, а не тех, о которых уже спросили: на листе
// турнира владелец спрашивал по очереди про четыре из них, и это было
// признаком, что объяснять надо все сразу.
function legend(d){
  const r = d.rules || {};
  const tol = Math.round((r.ahead_tol_sec || 0) / 3600);
  return `<details class="k" style="margin-top:8px">
   <summary style="cursor:pointer">what the columns mean</summary>
   <div style="margin-top:6px">
   <b>group</b> — «forward» if the decision reached the journal within
   ${tol} h of its date, «backfilled» otherwise. The delay is
   structural, not sloppiness: Binance publishes a day's archive after
   that day ends, and a decision dated D needs a bar stamped D, so
   D + 1 is the earliest any schedule can produce it.<br>
   <b>state</b> — a tranche is judged ${r.h} days after its date. An
   open one shows dashes, never zeros: it has no outcome yet, and a
   zero would read as «it made nothing».<br>
   <b>gross / net</b> — the tranche's residual return; net is gross
   minus ${lvl(r.cost_bp)} of cost and minus funding. Both come from the
   book's own resolution record, not from anything this page computes.<br>
   <b>funding</b> — what the book PAID over the hold (positive means it
   cost); rates come from the venue of execution.<br>
   <b>cut legs</b> — legs whose series ended more than a day before the
   window closed, i.e. delistings. They are held to their last bar
   rather than dropped: dropping them flattered the probe by 0.44 % a
   month.<br>
   <b>coverage</b> — median share of hours with an observation. Gaps
   are normal (a bar with no trade is not an observation), which is why
   «fewer bars than a full month» is not the definition of a cut leg —
   it would flag 82 % of them.</div></details>`;
}

// Ноги транша: состав решения и, у закрытого, исход каждой ноги. У
// открытого исхода нет — прочерк, не ноль.
function legs(d){
  if (d.legs_reason)
    return `<div class="panel"><div class="dim">${esc(d.legs_reason)}
      </div></div>`;
  const rows = d.legs || [];
  if (!rows.length) return "";
  const any = rows.some(r => r.resid_bp != null);
  return `<div class="panel"><div class="cap">legs of ${esc(d.legs_at)}
    — ${rows.length} names, long first</div>
   <div class="scroll"><table><tr><th>name</th><th>side</th>
   <th>weight</th><th>signal</th><th>β</th><th>outcome</th>
   <th>coverage</th></tr>` + rows.map(r => `<tr>
     <td class="mono">${esc(r.sym)}</td>
     <td class="${r.side === "long" ? "good" : "bad"}">${r.side}</td>
     <td class="mono">${r.w == null ? "&mdash;"
        : (100 * r.w).toFixed(2) + " %"}</td>
     <td class="mono">${num(r.sig, 4)}</td>
     <td class="mono">${num(r.beta, 3)}</td>
     <td class="mono ${r.resid_bp == null ? "dim"
        : (r.resid_bp > 0 ? "good" : "bad")}">${
        r.resid_bp == null ? "&mdash;" : pct(r.resid_bp)}</td>
     <td class="mono ${r.truncated ? "bad" : ""}">${r.coverage == null
        ? "&mdash;" : r.coverage.toFixed(2)
          + (r.truncated ? " cut" : "")}</td></tr>`).join("")
   + `</table></div><div class="k">${any
     ? "«outcome» is the leg's residual over the hold — what it did "
       + "beyond the market wave, which is what the book actually "
       + "trades. Weights sum to 1 in absolute value, so the two sides "
       + "are half the book each."
     : "this tranche is still open: the legs are the position, and "
       + "none of them has an outcome yet — dashes, not zeros"}</div>
   </div>`;
}

function bind(){
  const tb = document.getElementById("box");
  if (!tb || !tb.querySelectorAll) return;
  (tb.querySelectorAll("tr.pick") || []).forEach(tr => {
    tr.addEventListener("click", () => openLegs(tr.dataset.at));
  });
}
async function openLegs(at){
  if (!at) return;
  OPEN = (OPEN === at) ? null : at;
  if (!OPEN) { document.getElementById("legs").innerHTML = ""; render(); return; }
  try {
    const r = await fetch("/paper?k=" + encodeURIComponent(KEY)
      + "&at=" + encodeURIComponent(at));
    const d = await r.json();
    document.getElementById("legs").innerHTML = legs(d);
  } catch (e) {
    document.getElementById("legs").innerHTML =
      `<div class="panel"><div class="dim">no answer from the
       collector</div></div>`;
  }
  render();
}
function render(){
  const d = DATA;
  if (!d) return;
  document.getElementById("intro").innerHTML = intro(d);
  document.getElementById("box").innerHTML =
    fresh(d) + `<div class="panel"><div class="cap">verdict of the run
      that produced the file</div><div>${esc(d.verdict)}</div>
      <div class="k" style="margin-top:6px">run ${esc(d.run_at)};
      the summary was computed over ${d.art_decisions} decisions.
      ${d.journal_present
        ? `The journal here holds ${d.decisions}${
            d.art_decisions !== d.decisions
            ? " — it has moved ahead of the summary, which describes "
              + "the run that produced the file"
            : ""}.`
        : `No journal on this machine: the book keeps it where it
           runs, and only the reports travel in git — so the table
           below is empty for that reason, not for lack of tranches.`}
      </div></div>`
    + summary(d) + tranches(d);
  bind();
  document.getElementById("lead").textContent =
    d.decisions + " tranches";
}
async function load(){
  try {
    const r = await fetch("/paper?k=" + encodeURIComponent(KEY));
    const d = await r.json();
    if (!d.present) {
      document.getElementById("box").innerHTML =
        `<div class="panel"><div class="dim">${esc(d.reason
          || "the book has not run here")}</div></div>`;
      return;
    }
    DATA = d;
    render();
  } catch (e) {
    document.getElementById("box").innerHTML =
      `<div class="panel"><div class="dim">no answer from the
       collector — the page shows nothing rather than guessing</div>
       </div>`;
  }
}
load();
setInterval(load, 120000);
</script>
"""

LIVEPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>playbook — live execution vs the paper signal</title>
<style>
/* Дизайн — тот же, что у панели ядра (наследник algoth_v1): тёмный
   сине-фиолетовый фон, пурпурный акцент, тонкие рамки, воздух,
   крупные числа (просьба владельца: страница bot live в дизайне
   прежней core). Тема одна, переключателей внешнего вида нет (v2). */
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
.dim{color:var(--muted)} .thin{color:var(--muted)}
a{color:var(--accent)}
.stats{display:grid;grid-template-columns:repeat(auto-fill,
 minmax(155px,1fr));gap:10px;margin:0 0 14px}
.st{background:linear-gradient(180deg,rgba(151,71,255,.06),
  rgba(151,71,255,0) 55%),var(--panel);
 border:1px solid var(--rule);border-radius:14px;padding:11px 13px}
.st .k{font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.st .v{font-size:17px;font-weight:600;margin-top:5px}
.st .s{font-size:10.5px;color:var(--muted);margin-top:4px;
 line-height:1.45}
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
.alarm{border:1px solid rgba(255,100,115,.5);background:var(--bad-soft);
 color:var(--bad);font-weight:600;border-radius:12px;
 padding:9px 12px;margin-top:10px}
.mode{display:inline-block;padding:2px 10px;border-radius:8px;
 font-weight:700;letter-spacing:.08em}
.mode.live{background:rgba(255,100,115,.16);color:var(--bad);
 border:1px solid var(--bad)}
.mode.dry{background:rgba(142,136,173,.14);color:var(--muted);
 border:1px solid var(--rule)}
.foot{color:var(--muted);font-size:12px;margin-top:20px;line-height:1.7}
@media(max-width:640px){
 .wrap{padding:0 10px 60px}
 .stats{grid-template-columns:repeat(auto-fill,minmax(138px,1fr));gap:8px}
 .card{padding:12px;border-radius:14px}}
""" + NAVCSS + r"""</style>
<div class="wrap">
<header class="top">
  <a id="home" href="#" class="brand" title="to overview">ALG<b>O</b>TH</a>
  <span class="tag">playbook · live execution</span>
  <span class="sp"></span>
  <span id="hb" class="pill"><span class="dot"></span><span
    id="topage" class="mono">&hellip;</span></span>
  <span id="lead" class="pill mono">&hellip;</span>
  <span class="chip"><span class="ck">wallet</span><span
    id="topbal" class="cv mono">&hellip;</span></span>
</header>
<div id="nav"></div>
<div class="card" id="intro"></div>
<section class="card" id="tcard" style="display:none">
  <div class="cap"><span>trade on chart</span>
    <span id="tlab" class="mono meta"></span></div>
  <iframe id="tchart" title="trade chart"></iframe></section>
<div id="box">&hellip;</div>
<footer class="foot">this page only reads: the executor trades by the
  scanner&rsquo;s own decisions, the emergency stop is the KILL file
  on the server · refreshes every 15 s</footer>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + LVLJS + r"""
navMount("/live-page");
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function usd(v){ return v == null ? "&mdash;"
  : (v > 0 ? "+" : "") + Number(v).toFixed(2) + " $"; }
function ts(t){ return t ? new Date(t * 1000).toISOString()
  .slice(5, 16).replace("T", " ") : "&mdash;"; }
// Ключ книги журнала — из ОТВЕТА сервера (book_hz по маркеру
// book.txt): зашитое hz=sit после перевода исполнителя на другую
// книгу вело бы ссылки графика и разбора в чужую запись.
let HZ = "sit";

// Рамка предмета — первым абзацем: без неё зелёная строка читается
// как заработок, а страница меряет МЕХАНИКУ (спека 12).
function intro(d){
  return `<div class="cap"><span>what this page compares</span></div>
  <div>Every live trade of the executor is THE SAME trade the paper
  situational book recorded — one decision, two ledgers. The page
  shows what differs: the fill against the <b>signal price</b> the
  scanner saw at the decision second (entry slippage), whether the
  take-profit <b>filled as a resting limit at the level</b> (the
  live test of rule v13), and the live net in PERCENT of its own
  notional against the paper net of the same record.</div>
  <div class="k" style="margin-top:6px">Money is compared in
  PERCENT OF NOTIONAL, never in dollars: the paper position is 300&nbsp;$,
  the live one 30&nbsp;$. This is a measurement of execution
  mechanics, not of profit — a week of it cannot say anything about
  returns. The core panel (the shadow ledger and its parity checks)
  left the menu and lives at
  <a href="/bot-page?k=${encodeURIComponent(KEY)
  }">the core page</a>.</div>`;
}
function strip(d){
  const st = d.status || {};
  const mode = d.mode === "live"
    ? `<span class="mode live">LIVE</span>`
    : d.mode === "dry" ? `<span class="mode dry">DRY — orders are
       formed, not sent</span>`
    : `<span class="dim">executor not deployed</span>`;
  return `<section class="card"><div class="cap"><span>executor</span>
    <span class="meta mono">${d.book ? "book " + esc(d.book) : ""
    }</span></div>
  <div>${mode}
   <span class="k" style="margin-left:10px">open ${
     ((d.summary || {}).open) ?? "&mdash;"}
   &nbsp;·&nbsp; rejects in a row ${st.rejects_row ?? "&mdash;"}
   &nbsp;·&nbsp; stale entries skipped ${
     st.stale_entries_skipped ?? "&mdash;"}</span></div>
  ${st.halted ? `<div class="alarm">HALTED: ${esc(st.halted)}</div>`
    : ""}
  ${st.lev_errors ? `<div class="alarm">leverage 1&times; was NOT set
    (the venue refused; entries proceed — size is the fence, not
    margin): ${Object.keys(st.lev_errors).map(esc).join(", ")}
    &mdash; ${esc(String(Object.values(st.lev_errors)[0] || ""))
    }</div>` : ""}
  ${st.tp_errors ? `<div class="alarm">take-profit limits are NOT
    resting — the executor retries every tact and the venue refuses:
    ${Object.keys(st.tp_errors).map(esc).join(", ")}
    &mdash; ${esc(String(Object.values(st.tp_errors)[0] || ""))
    }</div>` : ""}
  ${d.journal_error ? `<div class="alarm">journal:
     ${esc(d.journal_error)}</div>` : ""}</section>`;
}
function stats(d){
  const s = d.summary || {}, c = d.counts || {};
  const t = (name, val, sub) => `<div class="st">
    <div class="k">${name}</div><div class="v mono">${val}</div>
    <div class="s">${sub || ""}</div></div>`;
  const v13 = (s.level_fills || s.level_misses)
    ? `${s.level_fills} / ${s.level_fills + s.level_misses}`
    : "&mdash;";
  return `<div class="stats">
    ${t("entry slippage, median", pct(s.entry_slip_med_bp),
        (s.entry_slip_n || 0) + " fills vs signal price")}
    ${t("fees paid, median", lvl(s.fee_med_bp),
        s.model_round_bp == null ? "model round unknown"
        : "model round " + lvl(s.model_round_bp))}
    ${t("take filled at level (v13)", v13,
        s.level_misses ? s.level_misses + " missed" :
        "of target exits")}
    ${t("live pnl, closed", usd(s.pnl_live),
        (s.closed || 0) + " closed of " + (c.opened || 0) + " opened")}
    ${t("open, marked", s.open_priced ? usd(s.open_marked_usd)
        : "&mdash;",
        (s.open_priced || 0) + "/" + (s.open || 0)
        + " priced &middot; a mark, not an outcome")}
    ${t("live vs paper, median", pct(s.net_delta_med_bp),
        (s.net_delta_n || 0) + " matched closes")}
    ${t("decisions", (c.decisions ?? "&mdash;"),
        (c.rejects_exec || 0) + " exec rejects · "
        + (c.rejects_dry || 0) + " dry-formed")}
  </div>
  <div class="k" style="margin:0 2px 14px">Slippage is signed so that
  positive is ALWAYS worse for us, on both sides. A row the paper
  book has no record for is counted, not hidden: matched
  ${s.matched ?? 0} / unmatched ${s.unmatched ?? 0}.</div>`;
}
// Кривая реализованных закрытий — та же подача, что equity на панели
// ядра, только базой служит ноль: стартовый капитал страница не
// выдумывает (урок фолбэка «1000»), а Σ pnl закрытых сделок — числа
// самого журнала.
function eqCard(rows){
  const cl = (rows || []).filter(r => r.pnl != null && r.closed_at)
    .sort((a, b) => a.closed_at - b.closed_at);
  if (cl.length < 2) return null;
  let s = 0;
  const curve = cl.map(r => [r.closed_at, +(s += r.pnl).toFixed(4)]);
  return {curve,
    html: `<section class="card"><div class="cap"><span>realised
      closes &middot; &Sigma; pnl</span><span class="mono meta">${
      cl.length} closes &middot; ${usd(curve[curve.length - 1][1])
      }</span></div><canvas id="eq" height="200"></canvas></section>`};
}
function drawEq(curve){
  const cv = document.getElementById("eq");
  if (!cv || !cv.getContext) return;
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const W = cv.clientWidth || 700, H = 200;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!curve || curve.length < 2) return;
  let lo = 0, hi = 0;
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
  g.beginPath(); g.moveTo(8, y(0)); g.lineTo(W - 58, y(0));
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
  g.fillText(hi.toFixed(2), W - 52, 16);
  g.fillText(lo.toFixed(2), W - 52, H - 10);
}
// Клик по строке открывает сделку на графике НАД таблицей — тот же
// встроенный чарт (embed), что на панели ядра: вторая реализация
// графика однажды разошлась бы с первой. Клик по ссылке в строке —
// не клик по строке.
function showTrade(pos){
  const m = String(pos || "").split(":");
  if (m.length < 4) return;
  const p = new URLSearchParams({k: KEY, sym: m[2], arm: m[0],
                                 hour: m[1], embed: 1, hz: HZ});
  const card = document.getElementById("tcard");
  card.style.display = "";
  const f = document.getElementById("tchart");
  const src = "/chart?" + p.toString();
  if (f.src !== src) f.src = src;
  document.getElementById("tlab").textContent =
    `${m[2].replace("USDT", "")} · ${m[3]} · signal hour ${m[1]}`;
  if (card.scrollIntoView) card.scrollIntoView({behavior: "smooth"});
}
document.getElementById("box").addEventListener("click", e => {
  if (e.target && e.target.closest && e.target.closest("a")) return;
  const tr = e.target && e.target.closest
    ? e.target.closest("[data-pos]") : null;
  if (tr) showTrade(tr.dataset.pos);
});
function table(d){
  const rows = d.rows || [];
  if (!rows.length)
    return `<section class="card"><span class="dim">no live trades yet
      — the first appears with the first fresh scanner entry</span>
      </section>`;
  const info = r => (r.tid && r.hour ? `<a class="open"
    title="the paper record of this decision"
    href="/trade-info?k=${encodeURIComponent(KEY)}&sym=${
    encodeURIComponent(r.sym)}&arm=${r.arm}&hour=${r.hour}&side=${
    r.side}&hz=${HZ}" style="text-decoration:none">&#9432;</a> ` : "")
    + (r.sym && r.hour ? `<a class="open"
    title="open this trade on the live chart"
    href="/chart?k=${encodeURIComponent(KEY)}&sym=${
    encodeURIComponent(r.sym)}&arm=${r.arm}&hour=${
    r.hour}&hz=${HZ}">chart</a>` : "");
  return `<section class="card"><div class="cap"><span>live trades
   </span><span class="meta">newest first &middot; click a row to see
   it on the chart</span></div><div class="scroll"><table>
   <thead><tr><th>opened</th><th>coin</th><th>side</th><th>size $</th>
   <th>signal px</th><th>fill px</th><th>slip</th>
   <th>exit px</th><th>mark</th><th>live net</th>
   <th>paper net</th>
   <th>&Delta;</th><th>pnl $</th><th>fees</th>
   <th>exit</th><th>v13</th><th>i</th></tr></thead><tbody>`
   + rows.map(r => `<tr${r.pos ? ` data-pos="${esc(r.pos)}"` : ""}>
     <td class="mono">${ts(r.opened_at)}</td>
     <td class="mono">${esc(String(r.sym || "")
        .replace("USDT", ""))}</td>
     <td><span class="side ${r.side === "long" ? "l" : "s"}">${
        r.side === "long" ? "L" : "S"}</span></td>
     <td class="mono">${r.size == null ? "&mdash;"
        : Number(r.size).toFixed(2)}</td>
     <td class="mono">${r.sig_px ?? "&mdash;"}</td>
     <td class="mono">${r.entry_px ?? "&mdash;"}</td>
     <td class="mono ${r.slip_bp > 0 ? "bad" : "good"}">${
        pct(r.slip_bp)}</td>
     <td class="mono">${r.exit_px ?? (r.state === "открыта"
        ? '<span class="dim">open</span>' : "&mdash;")}</td>
     <td class="mono thin" title="mark at the current mid — not an
      outcome; it will be anything until the exit">${
        r.state === "открыта" ? pct(r.unreal_bp) : "&mdash;"}</td>
     <td class="mono">${pct(r.live_net_bp)}</td>
     <td class="mono">${pct(r.paper_net_bp)}</td>
     <td class="mono ${r.delta_bp == null ? "dim"
        : (r.delta_bp >= 0 ? "good" : "bad")}">${pct(r.delta_bp)}</td>
     <td class="mono ${r.pnl > 0 ? "good" : r.pnl < 0 ? "bad" : ""}"${
        r.pnl_exch ? ' title="money taken from the exchange record'
        + ' (closed-pnl) — the journal did not see this close itself"'
        : ""}>${
        r.pnl == null ? "&mdash;" : Number(r.pnl).toFixed(2)}${
        r.pnl_exch ? ' <span class="dim">exch</span>' : ""}</td>
     <td class="mono">${lvl(r.fee_bp)}</td>
     <td class="k" title="${esc(r.reason)}">${
        esc((r.reason || "").slice(0, 26))}${
        (r.reason || "").length > 26 ? "&hellip;" : ""}</td>
     <td>${r.level_fill === true ? '<span class="good">level</span>'
        : r.level_fill === false
        ? '<span class="bad">missed</span>' : ""}</td>
     <td>${info(r)}</td></tr>`).join("")
   + `</tbody></table></div>
   <div class="k" style="margin-top:8px">&Delta; is live net minus
   paper net of the SAME
   record, in percent of each ledger&rsquo;s own notional. Positive
   means
   the live fill did better than the paper model assumed — expect it
   negative by roughly the extra costs the model does not see.</div>
   </section>`;
}
function rejectsPanel(d){
  const rj = d.rejects || [];
  if (!rj.length) return "";
  return `<section class="card"><div class="cap"><span>decisions that
   did not become trades</span></div><div class="scroll"><table>
   <thead><tr><th>when</th><th>sym</th><th>side</th><th>reason</th>
   </tr></thead><tbody>`
   + rj.map(r => `<tr><td class="mono">${ts(r.at)}</td>
     <td class="mono">${esc(String(r.sym || "")
        .replace("USDT", ""))}</td>
     <td><span class="side ${r.side === "long" ? "l" : "s"}">${
        r.side === "long" ? "L" : "S"}</span></td>
     <td class="k" style="white-space:normal">${esc(r.reason)}</td>
     </tr>`).join("")
   + `</tbody></table></div><div class="k" style="margin-top:8px">In
   DRY mode every formed order
   lands here by design — that is the X2 record. In LIVE mode a row
   here is an execution fact: an IOC that did not fill inside its
   price cap, a leg below the exchange minimum, a netted signal.
   </div></section>`;
}
async function load(){
  try {
    const r = await fetch("/live_exec?k=" + encodeURIComponent(KEY));
    const d = await r.json();
    HZ = d.book_hz || "sit";
    document.getElementById("intro").innerHTML = intro(d);
    const st = d.status || {};
    const hb = document.getElementById("hb");
    hb.className = "pill"
      + (st.age_sec == null || st.age_sec > 120 ? " hb-stale" : "");
    document.getElementById("topage").textContent =
      st.age_sec == null ? "no status"
      : `${Math.round(st.age_sec)} s`;
    const w = st.wallet || {};
    document.getElementById("topbal").textContent =
      w.equity == null ? "—" : Number(w.equity).toFixed(2) + " $";
    if (!d.present) {
      document.getElementById("lead").textContent = "not deployed";
      document.getElementById("box").innerHTML =
        `<section class="card"><span class="dim">the live executor has
         not been deployed on the server yet — no journal, no status.
         This is a named state, not an error.</span></section>`;
      return;
    }
    const eq = eqCard(d.rows);
    document.getElementById("box").innerHTML =
      strip(d) + stats(d) + (eq ? eq.html : "")
      + table(d) + rejectsPanel(d);
    if (eq) drawEq(eq.curve);
    document.getElementById("lead").textContent =
      (d.mode || "") + " · " + ((d.rows || []).length) + " trades";
  } catch (e) {
    document.getElementById("box").innerHTML =
      `<section class="card"><span class="dim">no answer from the
       collector — the page shows nothing rather than guessing</span>
       </section>`;
  }
}
load();
setInterval(load, 15000);
</script>
"""

VOLPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>volatility — does the market regime move our results</title>
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
.wrap{max-width:1560px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
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
.thin{color:var(--muted)}
a{color:var(--accent)}
.scroll{overflow-x:auto}
.warn{border-left:2px solid var(--ask);padding-left:10px;
 font-size:12.5px;color:var(--muted);margin:10px 0 0}
.warn b{color:var(--ask);font-weight:600}
""" + NAVCSS + r"""
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">volatility — does the market regime move our
    results</span>
  <span style="flex:1"></span>
  <span class="k" id="lead"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div id="curve"></div>
<div id="box">&hellip;</div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + BOOKJS + NAVJS + r"""
navMount("/vol-page");
// Имена книг — из общего списка (третья копия этой таблицы уже
// разошлась с ним после перевода на per σ).
const BOOK_EN = Object.fromEntries(BOOK_LIST);
const ARM_EN = {all:"both arms", gbm:"trees (ML)", nn:"neural (AI)"};
const BUCKETS = ["quiet", "normal", "loud"];

""" + PCTJS + LVLJS + r"""
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

// Кривая волатильности — контекст, а не вывод: она показывает, что за
// период вообще был, и была ли «шумная» корзина одним обвалом.
function curveBlock(d){
  const s = d.series || [];
  if (s.length < 2) return "";
  const W = 900, H = 90;
  const hi = Math.max(...s.map(p => p.bp)), lo = 0;
  const pts = s.map((p, i) => {
    const x = i / (s.length - 1) * W;
    const y = H - (p.bp - lo) / (hi - lo || 1) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`; }).join(" ");
  const line = (v, col) => {
    const y = H - (v - lo) / (hi - lo || 1) * H;
    return `<line x1="0" y1="${y.toFixed(1)}" x2="${W}"
      y2="${y.toFixed(1)}" stroke="${col}" stroke-width="1"
      stroke-dasharray="3 3"/>`; };
  return `<div class="panel"><div class="cap">market range per hour —
    median across every coin we record</div>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px;
      display:block">
      ${(d.cuts_bp || []).map(c => line(c, "#8e88ad")).join("")}
      <polyline points="${pts}" fill="none" stroke="#9747ff"
        stroke-width="1.2"/></svg>
    <div class="k">${s.length} hours shown${
      d.hours_measured > s.length
        ? ` of ${d.hours_measured} recorded` : ""} · dashed lines are
      the bucket edges (${(d.cuts_bp||[]).map(c => lvl(c))
        .join(" and ")}) · from ${esc((s[0]||{}).hour)} to ${
      esc((s[s.length-1]||{}).hour)} UTC</div></div>`;
}

// Одна книга — одна таблица: строка на руку × корзину. Числа сделок и
// РАЗНЫХ ДАТ стоят в той же строке нарочно: на десятке сделок с двух
// дней любая разница между корзинами есть шум, и увидеть это надо
// раньше, чем разницу.
function bookTable(hz, b){
  const row = (arm, key) => {
    const g = ((b[arm] || {})[key]) || null;
    const thin = g && (g.n < 20 || g.days < 5);
    if (!g) return `<tr><td>${ARM_EN[arm]}</td><td>${key}</td>
      <td colspan="5" class="dim">no closed trades</td></tr>`;
    return `<tr class="${thin ? "thin" : ""}">
      <td>${ARM_EN[arm]}</td>
      <td>${key === "all" ? "<b>every hour</b>" : key}</td>
      <td class="mono">${g.n}</td>
      <td class="mono">${g.days}</td>
      <td class="mono">${g.vol_med_bp}</td>
      <td class="mono">${Math.round(g.win*100)} %</td>
      <td class="mono">${pct(g.net_bp_avg)}</td>
      <td class="mono ${g.pnl > 0 ? "good" : "bad"}">${
        g.pnl > 0 ? "+" : ""}${g.pnl}</td></tr>`;
  };
  const arms = ["all", "gbm", "nn"].filter(a => b[a]);
  return `<div class="panel"><div class="cap">${
    BOOK_EN[hz] || hz}</div><div class="scroll"><table>
    <tr><th>arm</th><th>market</th><th>trades</th><th>days</th>
    <th>median range</th><th>wins</th><th>avg net</th><th>$</th></tr>
    ${arms.map(a => ["all", ...BUCKETS].map(k => row(a, k)).join(""))
      .join("")}</table></div>
    <div class="k">rows in grey stand on fewer than 20 trades or fewer
      than 5 distinct days — read them as anecdotes, not as a
      result</div></div>`;
}

// Отбирает ли модель волатильные имена. Вопрос владельца («не учесть
// ли волатильность в обучении») упирается в то, не учтена ли она уже
// молча: признаки нормированы собственной σ монеты, а цели — сырые
// базисные пункты, и ранжирование по предсказанному ходу тогда
// частично есть ранжирование по волатильности.
function pickBlock(d){
  const p = d.pick_vol;
  if (!p) return "";
  const hot = p.rel_med >= 1.15;
  return `<div class="panel"><div class="cap">does the model pick the
    movers?</div>
    <div class="scroll"><table>
    <tr><th>trades measured</th><th>coin's own range vs the market
      median that hour</th><th>share above the median</th>
      <th>median range of the picked coin</th></tr>
    <tr><td class="mono">${p.n}</td>
      <td class="mono ${hot ? "bad" : ""}">${p.rel_med}&times;</td>
      <td class="mono ${p.above > 0.6 ? "bad" : ""}">${
        Math.round(p.above*100)} %</td>
      <td class="mono">${pct(p.own_med_bp)}</td></tr>
    ${Object.entries(p.books || {}).map(([hz, b]) =>
      `<tr><td class="dim">${BOOK_EN[hz] || hz} <span class="mono">${
         b.n}</span></td>
       <td class="mono ${b.rel_med >= 1.15 ? "bad" : ""}">${
         b.rel_med}&times;</td>
       <td class="mono ${b.above > 0.6 ? "bad" : ""}">${
         Math.round(b.above*100)} %</td>
       <td class="mono">${pct(b.own_med_bp)}</td></tr>`).join("")}
    </table></div>
    <div class="k">The measured cause was the units: features are
      normalised by each coin's own volatility, targets were raw basis
      points, so ranking by predicted move ranked partly by volatility
      itself. Books 4 h, 1 h and situational now rank <b>per σ</b>; the
      24 h book is deliberately left on the raw order as the control
      half of its pair — so the rows above are the two sides of that
      measurement, not a blend. ${hot
      ? `The overall line is still ${p.rel_med}&times; the market
         median: read it per book, not as one number.`
      : `Around one means the selection is not a volatility ranking in
         disguise.`} A fingerprint, not a proof of cause — it says what
      the book holds, not why the model chose it.</div>
    </div>`;
}

function render(d){
  const box = document.getElementById("box");
  const intro = document.getElementById("intro");
  document.getElementById("curve").innerHTML = d && d.present
    ? curveBlock(d) : "";
  // «Не ответил» и «ответил, что пусто» — РАЗНОЕ, и мешать их нельзя.
  // Первый обход суток читает файл на имя в сутки по пятистам именам и
  // занимает около минуты; запрос при этом отваливается, и страница
  // писала «делить нечего» — то есть выдавала медленный счёт за
  // отсутствие данных. Ровно тот отказ, неотличимый от тишины, против
  // которого весь проект.
  if (!d) {
    intro.innerHTML = `<b>No answer from the collector.</b> The first
      build walks every recorded day across ~500 coins and takes about
      a minute; after that it is cached and answers instantly. Retrying
      &hellip;`;
    box.innerHTML = "";
    setTimeout(pull, 5000);
    return;
  }
  if (!d.present) {
    intro.innerHTML = `<b>Nothing to split yet.</b> This page needs
      closed trades and the hourly summaries they were opened in${
      d.no_hour ? ` — ${d.no_hour} closed trades have no summary
      for their entry hour` : ""}.`;
    box.innerHTML = "";
    return;
  }
  document.getElementById("lead").textContent =
    `${d.n} closed trades · ${d.hours_measured} hours · ${d.days} days`;
  // Что именно меряется и чего это не значит — до чисел, а не после.
  intro.innerHTML = `
    <p><b>Volatility here is the median hourly range across every coin
     we record</b> — high minus low of the mid, in basis points. It is
     the range and not the hourly return on purpose: an hour where the
     market fell and came back is calm by return and was anything but
     for the positions holding through it.</p>
    <p>Each closed trade is filed under the volatility of the hour it
     was <b>opened</b> in. That is the number known at decision time,
     so a rule could be built from it ("do not trade quiet hours").
     Volatility during the hold explains outcomes better and can never
     become a rule — it is not known when the trade is placed.</p>
    <p class="k">Bucket edges are the terciles of the volatility
     distribution itself (${(d.cuts_bp||[]).map(c => lvl(c))
       .join(" / ")}), fixed before any outcome is looked at:
     thresholds picked after seeing results would be a search without a
     correction.${d.no_hour ? ` ${d.no_hour} closed trades had no
     summary for their entry hour and are left out rather than filed
     under "normal".` : ""}</p>
    ${(d.errors && d.errors.length)
      ? `<p class="warn"><b>Partial.</b> ${d.errors.map(esc).join("; ")}
         — these books are missing from every number below</p>` : ""}`;
  const hz = Object.keys(d.books || {});
  box.innerHTML = pickBlock(d) + (hz.map(k => bookTable(k, d.books[k]))
    .join("") || `<div class="panel">no book has closed trades in a
        measured hour yet</div>`);
}
async function pull(){
  let d = null;
  try {
    const r = await fetch("/volatility?k=" + encodeURIComponent(KEY));
    d = await r.json();
  } catch (e) { d = null; }
  render(d);
}
pull();
setInterval(pull, 120000);
</script>
"""


GLOSSARY_PAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>playbook — what the model can read</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.6 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:14px 16px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
h2{font-size:15px;margin:0 0 6px}
.plain{margin:0 0 10px}
.sub{font-size:12.5px;color:var(--muted);margin:0 0 8px}
.sub b{color:var(--ink);font-weight:600}
.warn{border-left:2px solid var(--ask);padding-left:10px;
 font-size:12.5px;color:var(--muted);margin:10px 0 0}
.warn b{color:var(--ask);font-weight:600}
.feats{margin:8px 0 0;border-top:1px solid var(--rule-soft)}
.feat{display:flex;gap:10px;padding:4px 0;font-size:12.5px;
 border-bottom:1px solid var(--rule-soft);flex-wrap:wrap}
.feat .n{font-family:ui-monospace,Menlo,Consolas,monospace;
 color:var(--ink);min-width:150px}
.feat .d{color:var(--muted);flex:1;min-width:200px}
.feat .w{color:var(--accent);font-family:ui-monospace,Menlo,
 Consolas,monospace}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 8px}
.tag{background:var(--chip);border:1px solid var(--rule);
 border-radius:999px;padding:2px 10px;font-size:11.5px;
 color:var(--muted)}
.good{color:var(--bid)}.bad{color:var(--ask)}
a{color:var(--accent)}
button{background:var(--chip);border:1px solid var(--rule);
 color:var(--ink);border-radius:999px;padding:4px 12px;font-size:12px;
 cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
""" + NAVCSS + r"""</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k" id="strap"></span>
  <span style="flex:1"></span>
  <span id="lang"></span>
  <span class="k" id="lead"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div id="box">&hellip;</div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + r"""
// Язык страницы. Выбор держится в браузере: владелец читает
// по-русски, и переспрашивать его каждый раз незачем. Ссылка с
// параметром `lang` перебивает сохранённое — так страницу можно
// переслать сразу на нужном языке.
let LANG = new URLSearchParams(location.search).get("lang")
  || (function(){ try { return localStorage.getItem("algoth_lang"); }
                  catch (e) { return null; } })() || "en";
// Последний ответ держим у себя: переключение языка обязано работать
// БЕЗ похода на сервер — оба языка уже пришли, и запрашивать их
// заново значило бы гасить страницу на потерянной связи.
let DATA = null;
function setLang(v){
  LANG = v;
  try { localStorage.setItem("algoth_lang", v); } catch (e) {}
  render(DATA);
}
""" + FEATJS + r"""

function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
// Подписи самой страницы. Тексты семейств приходят с сервера на обоих
// языках, а это — её собственные слова, и они обязаны переключаться
// вместе с ними: половина страницы по-русски и половина по-английски
// выглядела бы исправной и читалась бы как недоделка.
const UI = {
  strap: {en: "playbook — every situation the model can read",
          ru: "справочник — все ситуации, которые читает модель"},
  lead: {en: t => `training #${t.seq} · ${t.n} features`,
         ru: t => `обучение №${t.seq} · признаков ${t.n}`},
  feats: {en: n => `${n} feature${n === 1 ? "" : "s"}`,
          ru: n => `признаков: ${n}`},
  weight: {en: w => `weight in the 4 h forecast: ${w} %`,
           ru: w => `вес в четырёхчасовом прогнозе: ${w} %`},
  named: {en: n => `named in ${n} closed trade${n === 1 ? "" : "s"}`,
          ru: n => `названо в закрытых сделках: ${n}`},
  reads: {en: "What the model actually measures:",
          ru: "Что именно мерится:"},
  caveat: {en: "What this does not mean.",
           ru: "Чего это не значит."},
  untrained: {en: "<b>The model has not trained yet</b> — this page "
                  + "lists what the live weights read, and there are "
                  + "none.",
              ru: "<b>Модель ещё не училась</b> — страница описывает "
                  + "то, что читают живые веса, а весов нет."},
  empty: {en: "no families — the map is empty",
          ru: "семейств нет — карта пуста"},
  partial: {en: "Partial.", ru: "Неполно."},
  orphan: {en: "defect: features without a family",
           ru: "дефект: признаки без семейства"},
  orphan_tail: {
    en: "— every situation name on every page is diluted until these "
        + "are mapped",
    ru: "— пока они не расписаны, имя ситуации размыто на каждой "
        + "странице"},
};
const T = k => { const v = UI[k]; return v[LANG] || v.en; };

function famCard(f){
  const ru = LANG === "ru";
  const pick = (k) => (ru && f[k + "_ru"]) ? f[k + "_ru"] : f[k];
  // Признаки — с весом там, где он известен. Вес есть только у тех,
  // кто попал в топ-10 манифеста; остальным ставится прочерк, а НЕ
  // ноль: ноль читался бы как «модель им не пользуется», тогда как
  // на деле мы просто не видим его важности.
  const feats = (f.features || []).map(x => `<div class="feat">
      <span class="n">${esc(x.name)}</span>
      <span class="d">${esc(featDesc(x.name, LANG))}</span>
      <span class="w">${x.weight ? (x.weight*100).toFixed(1) + " %"
                                 : "&middot;"}</span></div>`).join("");
  const tr = f.traded;
  const tags = [
    `<span class="tag">${T("feats")(f.n_features)}</span>`,
    f.weight ? `<span class="tag">${
       T("weight")((f.weight*100).toFixed(1))}</span>` : "",
    tr ? `<span class="tag">${T("named")(tr.n)} &middot; <span class="${
       tr.pnl > 0 ? "good" : "bad"}">${tr.pnl > 0 ? "+" : ""}${
       tr.pnl}</span></span>` : ""].join("");
  const cav = pick("caveat");
  return `<div class="panel">
    <h2>${esc(pick("title"))}</h2>
    <div class="tags">${tags}</div>
    <p class="plain">${esc(pick("plain"))}</p>
    <p class="sub"><b>${T("reads")}</b> ${esc(pick("reads"))}.</p>
    ${cav ? `<p class="warn"><b>${T("caveat")}</b> ${esc(cav)}</p>`
          : ""}
    <div class="feats">${feats}</div></div>`;
}

// Главная честность страницы, и она стоит ПЕРВОЙ на обоих языках:
// дискретных стратегий у модели нет. Без этого абзаца список семейств
// читался бы как набор правил, которые модель выбирает, — и потерять
// его в переводе значило бы соврать одному из двух читателей.
function introHTML(d){
  const cov = ((d.weight_covers||0)*100).toFixed(0);
  if (LANG === "ru") return `
    <p class="plain"><b>Отдельных стратегий у модели нет.</b> Это одна
     модель на все монеты и все ситуации, и ей никогда не говорили
     «это зажим — делай так». Что у неё есть — словарь ниже:
     ${d.n_features} чисел о том, что происходит прямо сейчас, и
     каждое нормировано собственным прошлым монеты, иначе BTC и мелкий
     альт не сравнить вовсе.</p>
    <p class="plain">Когда открывается сделка, вклад каждого признака
     в ЭТОТ прогноз раскладывается, и семейство, двинувшее его
     сильнее прочих, становится именем ситуации, которое видно на
     сделке — «ликвидации», «выедение стакана». Это чтение прогноза,
     а не правило, которому следовали.</p>
    <p class="sub">Вес — собственная важность признака у модели для
     четырёхчасового прогноза (рука ${esc(d.weight_arm)}). Манифест
     хранит топ-10 на цель, поэтому веса накрывают ${cov} % общей
     важности: семейство без веса не «не используется», а не видно на
     этой глубине. «Названо в закрытых сделках» считает последний
     год.</p>
    ${d.error ? `<p class="warn"><b>${T("partial")}</b> ${
      esc(d.error)}</p>` : ""}`;
  return `
    <p class="plain"><b>The model has no separate strategies.</b> It is
     one model over every coin and every situation, and it was never
     told "this is a squeeze, do that". What it has is the vocabulary
     below: ${d.n_features} numbers describing what is happening right
     now, each of them normalised against that coin's own past so that
     BTC and a small alt can be compared at all.</p>
    <p class="plain">When a trade is opened, the contributions of every
     feature to that one forecast are decomposed, and the family that
     moved it most becomes the name of the situation you see on the
     trade — "liquidations", "book eaten". That is a reading of the
     forecast, not a rule that was followed.</p>
    <p class="sub">Weights are the model's own feature importance for
     the 4 h forecast (${esc(d.weight_arm)} arm). The manifest keeps
     the top ten per target, so they cover ${cov} % of the total — a
     family without a weight is not unused, it is unseen at this
     depth. "Named in N closed trades" counts the last 365 days.</p>
    ${d.error ? `<p class="warn"><b>${T("partial")}</b> ${
      esc(d.error)}</p>` : ""}`;
}

function render(d){
  DATA = d;
  const box = document.getElementById("box");
  const intro = document.getElementById("intro");
  navMount("/glossary-page");
  document.getElementById("strap").textContent = T("strap");
  document.getElementById("lang").innerHTML =
    ["en","ru"].map(v => `<button data-l="${v}"
      aria-pressed="${String(LANG === v)}">${v.toUpperCase()}</button>`)
      .join(" ");
  document.querySelectorAll("#lang button").forEach(b =>
    b.onclick = () => setLang(b.dataset.l));
  if (!d || !d.present) {
    intro.innerHTML = T("untrained") + (d && d.error
      ? ` <span class="mono dim">${esc(d.error)}</span>` : "");
    box.innerHTML = "";
    return;
  }
  document.getElementById("lead").textContent =
    T("lead")({seq: d.train_seq, n: d.n_features});
  intro.innerHTML = introHTML(d);
  const fams = d.families || [];
  box.innerHTML = fams.map(famCard).join("")
    || `<div class="panel">${T("empty")}</div>`;
  const orphan = fams.find(f => f.key === "other");
  if (orphan)
    box.insertAdjacentHTML("afterbegin", `<div class="panel"
      style="border-color:var(--ask)"><div class="cap"
      style="color:var(--ask)">${T("orphan")}</div>
      ${orphan.features.map(x => esc(x.name)).join(", ")}
      ${T("orphan_tail")}</div>`);
}
async function pull(){
  let d = null;
  try {
    const r = await fetch("/glossary?k=" + encodeURIComponent(KEY));
    d = await r.json();
  } catch (e) { d = null; }
  render(d);
}
pull();
</script>
"""


# Страница дерева моделей — просьба владельца: разветвление от
# основных ML и AI, и по каждой ветке простыми словами, какую логику
# она проверяет. Состав веток и тексты приходят с сервера готовыми
# (`/model_tree` из `BOOK_DIRS`/`BOOK_TREE`): вторая копия списка книг
# на странице однажды разошлась бы — этим уже кончалось «список книг в
# пяти местах».
TREEPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>model tree — which logic each branch tests</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.6 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:14px 16px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
/* Родовое дерево на чистом CSS: линии — рамки псевдоэлементов, без
   единой библиотеки и картинки (правило v2). Широкое дерево скроллится
   в своём контейнере, а не ломает страницу. */
.treewrap{overflow-x:auto;padding:4px 0 8px}
.tree,.tree ul{display:flex;justify-content:center;padding:0;margin:0;
 list-style:none}
/* Ширина дерева — по содержимому, и это несущее правило, а не отделка.
   Без него `.tree` шириной в контейнер, ряд веток шире её, а
   `justify-content:center` разливает переполнение В ОБЕ стороны —
   правая половина прокручивается, левая недостижима: первая карточка
   стоит на 86 px ЛЕВЕЕ края при scrollLeft 0 и уезжает до −177 при
   прокрутке вправо (измерено в браузере). При ширине по содержимому
   переполнения внутри дерева нет вовсе, прокрутке достаётся вся
   ширина, а `margin` центрирует дерево, пока оно помещается: у
   переполняющего блока автоматические поля обращаются в ноль, и он
   встаёт по левому краю — то есть с нулевой прокрутки виден его
   настоящий левый край. */
.tree{width:max-content;margin-left:auto;margin-right:auto}
.tree ul{padding-top:18px;position:relative}
.tree li{display:flex;flex-direction:column;align-items:center;
 position:relative;padding:18px 5px 0}
.tree li::before,.tree li::after{content:"";position:absolute;top:0;
 right:50%;border-top:1px solid var(--rule);width:50%;height:18px}
.tree li::after{right:auto;left:50%;border-left:1px solid var(--rule)}
.tree li:first-child::before,.tree li:last-child::after{border:0 none}
.tree li:last-child::before{border-right:1px solid var(--rule);
 border-radius:0 8px 0 0}
.tree li:first-child::after{border-radius:8px 0 0 0}
.tree li:only-child::before{display:none}
.tree li:only-child::after{border:0 none;
 border-left:1px solid var(--rule);right:auto;left:50%}
.tree>li{padding:0}
.tree>li::before,.tree>li::after{display:none}
.tree ul::before{content:"";position:absolute;top:0;left:50%;
 border-left:1px solid var(--rule);width:0;height:18px}
.node{position:relative;background:var(--chip);
 border:1px solid var(--rule);border-radius:10px;
 padding:8px 26px 8px 10px;min-width:118px;max-width:172px;
 text-align:center}
.node.root{border-color:var(--accent);max-width:240px}
.node.off{opacity:.55}
.nt{font-weight:600;font-size:12.5px;line-height:1.35}
/* Имя ветки-ссылки выглядит как имя, а не как ссылка: цвет
   узла сохраняется, подчёркивание приходит на наведение —
   иначе шесть пурпурных заголовков читались бы как меню. */
a.nt{display:block;color:inherit;text-decoration:none}
a.nt:hover{text-decoration:underline;color:var(--accent)}
.ns{font-size:11px;color:var(--muted);margin-top:3px;
 font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
/* Число — неразрывный атом. Прежнее правило переноса (жадное,
   по любому месту) рвало строку где придётся, и на узком узле
   «+349.38 $ (+11.65 %)» выходило «+11.» и «65 %» — разорванное
   пополам число читается как другое число. Перенос допускается
   только между величинами, по разделителю; длинный ключ варианта
   турнира рвётся по-прежнему — для него оставлен `overflow-wrap`,
   который делает это последним средством, а не первым. */
.nb{white-space:nowrap}
.ibtn{position:absolute;top:4px;right:4px;width:18px;height:18px;
 line-height:15px;padding:0;border-radius:50%;font-size:11px;
 font-style:italic;font-family:Georgia,serif;background:var(--chip);
 border:1px solid var(--rule);color:var(--accent);cursor:pointer}
.ibtn:hover{border-color:var(--accent)}
.good{color:var(--bid)}.bad{color:var(--ask)}
a{color:var(--accent)}
button{background:var(--chip);border:1px solid var(--rule);
 color:var(--ink);border-radius:999px;padding:4px 12px;font-size:12px;
 cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
.mback{position:fixed;inset:0;background:rgba(5,3,18,.66);z-index:40}
.mbox{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);
 z-index:41;width:min(540px,92vw);max-height:80vh;overflow:auto;
 background:var(--panel);border:1px solid var(--accent);
 border-radius:14px;padding:16px 18px}
.mx{position:absolute;top:6px;right:10px;background:none;border:0;
 color:var(--muted);font-size:17px;cursor:pointer;padding:2px 6px}
.mt{font-weight:700;font-size:14.5px;margin:0 18px 6px 0}
.facts{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-size:11.5px;color:var(--muted);margin:0 0 8px}
.plain{margin:0 0 10px;font-size:13.5px}
.stat{font-size:12.5px;color:var(--muted)}
.stat b{color:var(--ink);font-weight:600}
/* Телефон: дерево разворачивается ВЕРТИКАЛЬНО. Шесть веток в ширину
   не помещаются ни на один экран, и горизонтальная прокрутка прятала
   бы половину семьи за краем — владелец смотрит с телефона. Корень
   сверху, ветки лесенкой вниз по левой линии, лист турнира ступенькой
   глубже. Сбросы перечисляют и :first/:last/:only-child — иначе
   десктопные линии углов побеждают по специфичности и рисуются
   поверх вертикальных. */
@media (max-width:720px){
  .treewrap{overflow:visible;padding:0}
  .tree,.tree ul{display:block}
  .tree{width:auto;margin:0}
  .tree ul{margin:0;padding:0 0 0 16px;position:relative}
  .tree ul::before{content:"";position:absolute;left:0;top:0;
    bottom:0;height:auto;width:0;border-left:1px solid var(--rule)}
  .tree li,.tree>li{display:block;padding:10px 0 0;position:relative}
  .tree li::before,.tree li::after,
  .tree li:first-child::before,.tree li:first-child::after,
  .tree li:last-child::before,.tree li:last-child::after,
  .tree li:only-child::before,.tree li:only-child::after{
    display:none;content:none;border:0 none;border-radius:0;
    background:none}
  .tree ul li{padding-left:14px}
  .tree ul li::before,
  .tree ul li:first-child::before,
  .tree ul li:last-child::before,
  .tree ul li:only-child::before{content:"";display:block;
    position:absolute;left:-16px;top:28px;width:28px;height:0;
    right:auto;border:0 none;border-top:1px solid var(--rule)}
  /* Ниже последней ветки рельса нет: хвост закрашивается цветом
     панели, иначе линия висела бы в пустоту. */
  .tree ul li:last-child::after,
  .tree ul li:only-child::after{content:"";display:block;
    position:absolute;left:-17px;top:29px;bottom:0;width:3px;
    right:auto;border:0 none;background:var(--panel)}
  .node,.node.root{max-width:none;width:100%;text-align:left}
  /* Палец — не курсор: кнопке «i» нужна площадь. */
  .ibtn{width:24px;height:24px;line-height:21px;font-size:13px}
  .mx{font-size:20px}
}
""" + NAVCSS + r"""</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k" id="strap"></span>
  <span style="flex:1"></span>
  <span id="lang"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div id="box"></div>
<div id="modal"></div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + r"""
// Язык — та же механика, что у справочника: оба языка уже в ответе,
// переключение не ходит на сервер, ссылка с `lang` перебивает память.
let LANG = new URLSearchParams(location.search).get("lang")
  || (function(){ try { return localStorage.getItem("algoth_lang"); }
                  catch (e) { return null; } })() || "en";
let DATA = null;
// Какая карточка раскрыта. Проза живёт ТОЛЬКО в карточке по кнопке
// «i» (просьба владельца): по умолчанию узел несёт имя и главную
// статистику, и дерево читается одним взглядом.
let INFO = null;
function setLang(v){
  LANG = v;
  try { localStorage.setItem("algoth_lang", v); } catch (e) {}
  render(DATA);
}
function showInfo(k){ INFO = k; render(DATA); }
function closeInfo(){ INFO = null; render(DATA); }
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
const UI = {
  strap: {en: "model tree — which logic each branch tests",
          ru: "дерево моделей — какую логику проверяет каждая ветка"},
  intro: {en: "Two heads learn on the same data and run the SAME set "
              + "of books side by side — that is the first "
              + "tournament: which head reads the market better. A "
              + "sub-model here is not a separately trained model: it "
              + "is a book on the same weights that differs by "
              + "exactly one declared rule, so a difference in "
              + "results can be attributed to the rule and not to "
              + "another model. Press the \u201ci\u201d on a branch "
              + "to read what it tests.",
          ru: "Две головы учатся на одних данных и ведут ОДИНАКОВЫЙ "
              + "набор книг параллельно — это первый турнир: чья "
              + "голова лучше читает рынок. Под-модель здесь — не "
              + "отдельно обученная модель, а книга на тех же весах, "
              + "отличающаяся ровно одним объявленным правилом: "
              + "только так разницу результатов можно приписать "
              + "правилу, а не другой модели. Нажмите «i» на ветке, "
              + "чтобы прочитать, что она проверяет."},
  closedL: {en: s => `closed <b>${s.closed}</b> · win ${
              Math.round(s.win * 100)} % · `,
            ru: s => `закрыто <b>${s.closed}</b> · побед ${
              Math.round(s.win * 100)} % · `},
  none: {en: "no closed yet", ru: "закрытых нет"},
  nomoney: {en: "records only", ru: "только запись"},
  openw: {en: "open", ru: "откр."},
  openL: {en: (s, mv) => `open <b>${s.open}</b> · ${mv} (${
            s.marked}/${s.open} priced)`,
          ru: (s, mv) => `открыто <b>${s.open}</b> · ${mv} (переоценено ${
            s.marked} из ${s.open})`},
  nomoneyL: {en: "not traded and not in the league money",
             ru: "не торгуется и в деньги лиги не входит"},
  history: {en: "history →", ru: "история →"},
  bydays: {en: "day by day →", ru: "по дням →"},
  offbook: {en: "not started", ru: "не заведена"},
  offbookL: {en: "book not started on the server",
             ru: "книга на сервере ещё не заведена"},
  tnode: {en: t => t.present
            ? (t.stale ? "\u26a0 run is stale · " : "")
              + `picks ${t.points}`
              + (t.pick ? ` · now ${esc(t.pick)}` : "")
            : esc(t.status),
          ru: t => t.present
            ? (t.stale ? "\u26a0 прогон устарел · " : "")
              + `точек ${t.points}`
              + (t.pick ? ` · сейчас ${esc(t.pick)}` : "")
            : esc(t.status)},
  allvars: {en: "all 72 branches \u2192",
            ru: "все 72 ветки \u2192"},
  tstat: {en: t => `status: ${esc(t.status)}` + (t.present
            ? ` · legs ${t.legs} · measured cells ${t.cells_measured}`
              + (t.pick ? ` · now ${esc(t.pick)}` : "") : ""),
          ru: t => `статус: ${esc(t.status)}` + (t.present
            ? ` · ног ${t.legs} · измеренных ячеек ${t.cells_measured}`
              + (t.pick ? ` · сейчас ${esc(t.pick)}` : "") : "")},
};
function T(k){ const v = UI[k]; return v[LANG] || v.en; }
function tx(o, f){ return LANG === "ru" ? o[f + "_ru"] || o[f]
                                        : o[f]; }
function money(v){
  if (v == null) return "";
  const c = v > 0 ? "good" : v < 0 ? "bad" : "";
  return `<span class="${c} mono nb">${v > 0 ? "+" : ""}${
    v.toFixed(2)} $</span>`;
}
// Неразрывная величина: пробел внутри числа («52 %», «open 138»,
// «Σ 1848») — такой же разрыв, как внутри дроби, и переносить по
// нему нельзя.
function nb(s){ return `<span class="nb">${s}</span>`; }
// Доля к депозиту — рядом с каждой денежной цифрой (просьба
// владельца): «+59.95 $» без знаменателя не говорит, много это или
// пыль. Знаменатель едет из ответа сервера; без него доля не
// печатается вовсе — выдуманное число хуже пропуска.
function share(v, cap){
  if (v == null || !cap) return "";
  return ` <span class="mono nb" style="color:var(--muted)">(${
    pct(v / cap * 1e4)})</span>`;
}
// Депозит руки — сумма депозитов её ТОРГУЕМЫХ книг: наблюдательная
// запись денег не держит, незаведённая книга — тоже. Делить сумму
// двух счетов на один депозит нельзя — то же правило, что у вкладки
// «обе» в сводке.
// Книги корня: под ML и AI идут все, КРОМЕ согласных; согласные —
// только под третьим корнем. Руки согласной книги тождественны по
// построению (пересечение симметрично), и под руками каждая стояла
// бы дважды с одинаковыми числами — дубль показа, не два результата.
function rootBooks(r){
  return (DATA && DATA.books || []).filter(
    b => r.arm === "agree" ? b.agreed : !b.agreed);
}
// Рука ПОКАЗА для корня: у согласного корня руки кассы тождественны,
// канонической идёт gbm — это конвенция показа, не выбор лучшей.
function armOf(r){ return r.arm === "agree" ? "gbm" : r.arm; }
// Эхо в сумму корня не входит — но у согласного корня его книги и
// ЕСТЬ семья (эхо они по отношению к ИСТОЧНИКАМ под другими корнями,
// и туда их Σ не попадает по построению rootBooks).
function inSum(r, b){ return r.arm === "agree" || !b.echo; }
function rootCap(r){
  if (!DATA || !DATA.cap) return null;
  // «Держит ли книга деньги» решает поле сервера, а не ключ в этой
  // строке: перечень книг уже жил в восьми местах, и зашитое имя
  // однажды разойдётся с картой книг на сервере.
  const n = rootBooks(r).filter(
    b => b.present && b.traded && inSum(r, b)).length;
  return n ? DATA.cap * n : null;
}
// Короткое имя узла: часть заголовка до тире. Полный заголовок и
// проза — в карточке по «i».
function label(o){
  return String(tx(o, "title")).split(" — ")[0];
}
function openLine(s){
  // Открытые деньги — ОТДЕЛЬНОЙ строкой и никогда в одной цифре с
  // закрытыми (правило `summary`). Переоценить нечего — прочерк, а не
  // ноль: ноль объявил бы позицию ровной там, где цены просто нет.
  // Частичная переоценка названа числом — «10/12».
  if (!s || !s.open) return "";
  const m = s.open_pnl == null ? "\u2014"
    : money(s.open_pnl) + share(s.open_pnl, DATA && DATA.cap);
  const part = s.marked < s.open
    ? ` · ${nb(s.marked + "/" + s.open)}` : "";
  return `<div class="ns">${nb(T("openw") + " " + s.open)} · ${
    m}${part}</div>`;
}
function bookStat(b, arm){
  // «Держит ли книга деньги» решает ПОЛЕ сервера, а не имя книги:
  // зашитый ключ означал бы, что новая неторгуемая книга печатает
  // денежные подписи, а страница выглядит исправной.
  if (!b.traded) return T("nomoney");
  if (!b.present) return T("offbook");
  const s = (b.stats || {})[arm];
  // Книга с открытыми позициями и БЕЗ закрытых несёт только поля
  // открытых — так задумано (сервер не выдумывает нулей). Спрашивать у
  // неё число закрытых значило бы напечатать `undefined · NaN %`, и
  // ровно это владелец увидел у книги в σ. Нет закрытых — так и
  // сказано, а деньги открытых идут своей строкой ниже.
  if (!s || !s.closed) return T("none");
  return `${nb(s.closed + " · " + Math.round(s.win * 100) + " %")} · ${
    money(s.pnl)}${share(s.pnl, DATA && DATA.cap)}`;
}
function rootSum(r){
  let n = 0, p = 0.0, any = false;
  for (const b of rootBooks(r)) {
    // Книга-эхо (равный риск, корзины) — те же решения, что у
    // торгуемой: в сумме корня они считались бы дважды. Флаг шлёт
    // сервер; у согласного корня его книги и есть семья (`inSum`).
    if (!inSum(r, b)) continue;
    const s = (b.stats || {})[armOf(r)];
    // Ветка без закрытых сделок в сумму не входит вовсе: сложить с ней
    // значит получить NaN, то есть потерять и те ветки, что посчитаны.
    if (!s || !s.closed) continue;
    any = true; n += s.closed; p += s.pnl;
  }
  return any ? `${nb("\u03a3 " + n)} · ${
      money(Math.round(p * 100) / 100)}${share(p, rootCap(r))}`
             : T("none");
}
function rootOpen(r){
  let n = 0, m = 0, p = 0.0, priced = false;
  for (const b of rootBooks(r)) {
    if (!inSum(r, b)) continue;
    const s = (b.stats || {})[armOf(r)];
    if (!s || !s.open) continue;
    n += s.open; m += s.marked;
    if (s.open_pnl != null) { p += s.open_pnl; priced = true; }
  }
  if (!n) return "";
  const mv = priced
    ? money(Math.round(p * 100) / 100) + share(p, rootCap(r))
    : "\u2014";
  const part = m < n ? ` · ${nb(m + "/" + n)}` : "";
  return `<div class="ns">${nb(T("openw") + " " + n)} · ${
    mv}${part}</div>`;
}
// Имя ветки — ССЫЛКА на дневную статистику этой книги (просьба
// владельца: «кликаем на 4-hour book — открывается страница со
// статистикой по каждому дню»). Ссылку получают только книги, у
// которых деньги есть: наблюдательная запись их не держит вовсе, и
// ссылка на неё вела бы в пустую страницу, неотличимую от сломанной.
// Кнопка «i» остаётся тем же, чем была, — прозой ветки.
function nodeCard(key, cls, title, stat, extra, href){
  const nm = href
    ? `<a class="nt" href="${esc(href)}">${esc(title)}</a>`
    : `<div class="nt">${esc(title)}</div>`;
  return `<div class="node ${cls}" data-key="${esc(key)}">
    <button class="ibtn" onclick="showInfo('${key}')"
      title="what this branch tests">i</button>
    ${nm}
    <div class="ns">${stat}</div>${extra || ""}</div>`;
}
// Адрес дневной статистики книги: ключ доступа, книга и рука. Рука
// едет в адрес, потому что узел дерева и есть «книга × рука» — открыв
// его без руки, владелец увидел бы сумму двух и не понял бы, почему
// числа не совпали с узлом, по которому нажал.
function daysHref(b, arm){
  if (!b.traded || !b.present) return "";
  return "/book-page?k=" + encodeURIComponent(KEY)
    + "&hz=" + encodeURIComponent(b.key)
    + "&arm=" + encodeURIComponent(arm);
}
function rootCard(r){
  // Рука узлов корня: у согласного корня руки тождественны по
  // построению, узлы идут ОДИН раз канонической рукой gbm — под ML и
  // AI согласные книги не рисуются вовсе (rootBooks), иначе каждая
  // стояла бы на дереве дважды с одинаковыми числами.
  const arm = armOf(r);
  const kids = rootBooks(r).map(b => {
    // Турнир политик — лист ситуационной ветки: правила этой книги и
    // есть то, что он перебирает.
    const kid = b.key === "sit" && DATA.tournament
      ? `<ul><li>${nodeCard("tourney:" + arm, "leaf",
          label(DATA.tournament), T("tnode")(DATA.tournament))}
         </li></ul>` : "";
    return `<li>${nodeCard(b.key + ":" + arm,
      b.present ? "" : "off", label(b), bookStat(b, arm),
      openLine((b.stats || {})[arm]), daysHref(b, arm))}${
      kid}</li>`;
  }).join("");
  return `<div class="panel" data-root="${esc(r.arm)}">
    <div class="cap">${esc(r.arm)}</div>
    <div class="treewrap"><ul class="tree"><li>
      ${nodeCard("root:" + r.arm, "root", tx(r, "title"),
                 rootSum(r), rootOpen(r))}
      <ul>${kids}</ul></li></ul></div></div>`;
}
function infoHTML(){
  const i = String(INFO).indexOf(":");
  const kind = String(INFO).slice(0, i < 0 ? undefined : i);
  const arm = i < 0 ? "" : String(INFO).slice(i + 1);
  if (kind === "root") {
    const r = (DATA.roots || []).find(x => x.arm === arm);
    if (!r) return "";
    return `<div class="mt">${esc(tx(r, "title"))}</div>
      <div class="plain">${esc(tx(r, "plain"))}</div>
      <div class="stat mono">${rootSum(r)}</div>${rootOpen(r)}`;
  }
  if (kind === "tourney") {
    const t = DATA.tournament || {};
    return `<div class="mt">${esc(tx(t, "title"))}</div>
      <div class="plain">${esc(tx(t, "plain"))}</div>
      <div class="stat mono">${T("tstat")(t)}</div>
      <div class="stat"><a href="/tournament-page?k=${
        encodeURIComponent(KEY)}">${T("allvars")}</a></div>`;
  }
  const b = (DATA.books || []).find(x => x.key === kind);
  if (!b) return "";
  const s = (b.stats || {})[arm];
  const st = !b.traded ? T("nomoneyL")
    : !b.present ? T("offbookL")
    : s && s.closed ? T("closedL")(s) + money(s.pnl) : T("none");
  const hz = b.key === "h4" ? "" : "&hz=" + encodeURIComponent(b.key);
  const dh = daysHref(b, arm);
  const so = (b.stats || {})[arm];
  const openRow = so && so.open
    ? `<div class="stat">${T("openL")(so, so.open_pnl == null
        ? "\u2014" : money(so.open_pnl))}</div>` : "";
  return `<div class="mt">${esc(tx(b, "title"))} <span class="dim"
      style="font-weight:400">· ${esc(arm)}</span></div>
    ${b.facts ? `<div class="facts">${esc(b.facts)}</div>` : ""}
    <div class="plain">${esc(tx(b, "plain"))}</div>
    <div class="stat">${st} &nbsp;
      <a href="/trades-page?k=${encodeURIComponent(KEY)}${hz}">${
        T("history")}</a>${dh ? ` &nbsp; <a href="${esc(dh)}">${
        T("bydays")}</a>` : ""}</div>${openRow}`;
}
function render(d){
  DATA = d;
  navMount("/tree-page");
  document.getElementById("strap").textContent = T("strap");
  document.getElementById("lang").innerHTML =
    ["en","ru"].map(v => `<button data-l="${v}"
      aria-pressed="${String(LANG === v)}">${v.toUpperCase()}</button>`)
      .join(" ");
  document.querySelectorAll("#lang button").forEach(b =>
    b.onclick = () => setLang(b.dataset.l));
  const intro = document.getElementById("intro");
  const box = document.getElementById("box");
  const modal = document.getElementById("modal");
  if (!d) {
    intro.textContent = "no answer from the collector — retrying";
    setTimeout(pull, 5000);
    return;
  }
  intro.innerHTML = T("intro") + ((d.errors || []).length
    ? `<div class="k" style="margin-top:6px">${
        d.errors.map(esc).join("<br>")}</div>` : "");
  box.innerHTML = (d.roots || []).map(rootCard).join("");
  // Карточка «i»: подложка и крестик закрывают, содержимое — из тех
  // же данных и того же языка, что дерево.
  modal.innerHTML = INFO
    ? `<div class="mback" onclick="closeInfo()"></div>
       <div class="mbox"><button class="mx"
         onclick="closeInfo()">\u00d7</button>${infoHTML()}</div>`
    : "";
}
async function pull(){
  let d = null;
  try {
    const r = await fetch("/model_tree?k=" + encodeURIComponent(KEY));
    d = await r.json();
  } catch (e) { d = null; }
  render(d);
}
pull();
</script>
"""


# Страница турнира политик — просьба владельца: весь лист веток и
# подветок отдельной страницей. Данные — артефакт последнего прогона
# через `/tournament`: страница обязана описывать тот прогон, который
# породил файл, а не текущие исходники (урок R1).
TOURPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>tournament — all 72 branches</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.6 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:14px 16px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
.warn{border-left:2px solid var(--ask);padding-left:10px;
 font-size:12.5px;color:var(--muted);margin:10px 0 0}
.warn b{color:var(--ask);font-weight:600}
.frame{border-left:2px solid var(--accent);padding-left:10px;
 font-size:13px;margin:0 0 10px}
.frame b{color:var(--accent);font-weight:600}
.legend{font-size:12.5px;color:var(--muted);margin:0 0 10px}
.legend b{color:var(--ink);font-weight:600}
.gloss{margin:8px 0 0}
.gloss summary{cursor:pointer;color:var(--accent);font-size:12.5px}
.grow{font-size:12.5px;color:var(--muted);margin:6px 0 0;
 padding-left:10px;border-left:1px solid var(--rule-soft)}
.grow b{color:var(--ink);font-weight:600}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:5px 8px;text-align:right;white-space:nowrap;
 border-bottom:1px solid var(--rule-soft)}
th{color:var(--muted);font-weight:600;cursor:pointer;
 position:sticky;top:0;background:var(--panel)}
th:first-child,td:first-child{text-align:left}
tr.hl td{background:rgba(151,71,255,.10)}
tr.thin td{opacity:.55}
.good{color:var(--bid)}.bad{color:var(--ask)}
a{color:var(--accent)}
button{background:var(--chip);border:1px solid var(--rule);
 color:var(--ink);border-radius:999px;padding:4px 12px;font-size:12px;
 cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
""" + NAVCSS + r"""</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k" id="strap"></span>
  <span style="flex:1"></span>
  <span id="lang"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div class="panel" id="selbox"></div>
<div class="panel"><div class="cap" id="tcap"></div>
  <div class="legend" id="tlegend"></div>
  <div class="scroll" id="box">&hellip;</div></div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + r"""
let LANG = new URLSearchParams(location.search).get("lang")
  || (function(){ try { return localStorage.getItem("algoth_lang"); }
                  catch (e) { return null; } })() || "en";
let DATA = null;
// Порядок по умолчанию — ЛУЧШИЕ СВЕРХУ по ожиданию на сделку
// (просьба владельца). `null` означает именно его, а не объявленный
// порядок сетки: семьдесят две строки подряд глазами не читаются.
// Ожидание, а не итог: у ячеек разное число сделок, и итог сравнивал
// бы «сколько наторговала», а не «как ведёт себя правило».
let SORT = null;
const DEFAULT_SORT = "exp_bp";
// Колонки РЕЗУЛЬТАТА. При сортировке по любой из них неизмеренные
// ячейки уходят вниз ВСЕГДА: ветка с +2.47 % на восьми сделках иначе
// встала бы первой строкой и читалась бы как победитель — ровно та
// ловушка, о которой предупреждает шапка страницы. По колонкам
// НАСТРОЕК (край, RR, стоп, тейк, возраст, сделки) порядок не
// трогается: там тонкие ячейки и есть предмет просмотра.
const RESULT_COLS = ["win", "exp_bp", "med_bp", "total_bp",
                     "worst_bp", "dd_bp"];
function setLang(v){
  LANG = v;
  try { localStorage.setItem("algoth_lang", v); } catch (e) {}
  render(DATA);
}
function sortBy(col){
  SORT = (SORT && SORT.col === col)
    ? (SORT.asc ? null : {col: col, asc: true})
    : {col: col, asc: false};
  render(DATA);
}
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
""" + PCTJS + LVLJS + r"""
const UI = {
  strap: {en: "policy tournament — all 72 branches",
          ru: "турнир политик — все 72 ветки"},
  frame: {en: "These are <b>not 72 models</b>. There is one set of "
              + "weights per head (ML trees and AI net), and the 72 "
              + "rows are 72 sets of <b>behaviour rules</b> on those "
              + "same weights \u2014 where to put the stop, whether "
              + "to take profit, how long to hold, how selective to "
              + "be at entry. Same forecast, different handling. "
              + "That is why a difference in results can be "
              + "attributed to the rule and not to another model.",
          ru: "Это <b>не 72 модели</b>. Веса одни на голову (ML — "
              + "деревья, AI — сеть), а 72 строки — это 72 набора "
              + "<b>правил поведения</b> на тех же весах: куда "
              + "ставить стоп, брать ли прибыль по цели, сколько "
              + "держать, насколько придирчиво входить. Прогноз тот "
              + "же, обращение с ним разное. Именно поэтому разницу "
              + "результатов можно приписать правилу, а не другой "
              + "модели."},
  guard: {en: "This table is diagnostics, not a verdict. The replay "
              + "is optimistic — the weights saw these hours, the "
              + "scanner\u2019s discount and arming are not replayed "
              + "— and picking the best cell of 72 by the past is "
              + "exactly the mistake the selector exists to test. "
              + "The reading is the MEDIAN of measured cells; rows "
              + "thinner than the floor are unmeasured, not zero.",
          ru: "Таблица — диагностика, а не вердикт. Реплей "
              + "оптимистичен: веса видели эти часы, скидка и "
              + "взведение сканера не реплеятся, — а выбрать лучшую "
              + "из 72 ячеек по прошлому есть ровно та ошибка, для "
              + "проверки которой существует селектор. Чтение — "
              + "МЕДИАНА измеренных ячеек; строки тоньше пола не "
              + "измерены, а не нулевые."},
  head: {en: d => `legs in the journal <b>${d.legs}</b> · `
              + `measured cells <b>${d.measured}</b> of `
              + `${d.cells.length} · median expectancy of measured `
              + `<b>${pct(d.med_exp_bp)}</b> · run `
              + `${Math.round(d.run_age_sec/3600)} h ago`,
         ru: d => `ног в журнале <b>${d.legs}</b> · измеренных ячеек `
              + `<b>${d.measured}</b> из ${d.cells.length} · медиана `
              + `ожидания по измеренным <b>${pct(d.med_exp_bp)}</b> `
              + `· прогон ${Math.round(d.run_age_sec/3600)} ч назад`},
  selcap: {en: "selector (the verdict is judged here)",
           ru: "селектор (вердикт выносится здесь)"},
  tcap: {en: "all branches, best first by expectancy · click a "
             + "column header to sort, again to flip, third click "
             + "returns to best-first",
         ru: "все ветки, лучшие сверху по ожиданию · клик по "
             + "заголовку сортирует, второй переворачивает, третий "
             + "возвращает порядок «лучшие сверху»"},
  legend: {en: d => `<b>current rules</b> \u2014 the branch the live `
             + `situational book trades right now; it is the `
             + `reference, not the winner: the selector has to beat `
             + `it to justify changing the rules at all. `
             + `<b>thin</b> \u2014 fewer than ${d.min_cell} trades: `
             + `the cell is <b>unmeasured, not zero</b>, its numbers `
             + `are noise. Thin cells stay out of the median, are `
             + `not eligible for the selector, and <b>always sink to `
             + `the bottom</b> when the table is ranked by a result `
             + `column \u2014 an unmeasured cell cannot be the best `
             + `one. <b>worst trade</b> is the final result of the `
             + `single worst trade, not a drawdown \u2014 that trade `
             + `may have gone deeper against us and come back. `
             + `<b>curve drawdown</b> is the deepest dip of the `
             + `variant\u2019s cumulative curve, measured in the `
             + `same unit as the rest of the table: a SUM of per-leg `
             + `percentages, not percent of the deposit \u2014 the `
             + `replay models slots, not position size.`,
           ru: d => `<b>текущие правила</b> \u2014 ветка, которой `
             + `ситуационная книга торгует прямо сейчас; это точка `
             + `отсчёта, а не победитель: селектор обязан переиграть `
             + `её, чтобы оправдать само право менять правила. `
             + `<b>мало</b> \u2014 сделок меньше ${d.min_cell}: `
             + `ячейка <b>не измерена, а не нулевая</b>, её числа `
             + `суть шум. В медиану такие не входят, селектору для `
             + `выбора не годятся и <b>всегда уходят вниз</b> при `
             + `сортировке по колонке результата \u2014 неизмеренная `
             + `ячейка не может быть лучшей. <b>худшая сделка</b> — `
             + `итог самой убыточной сделки, а НЕ просадка: по дороге `
             + `она могла провалиться глубже и вернуться. `
             + `<b>просадка кривой</b> — глубочайший провал `
             + `накопленной кривой ветки, в той же единице, что вся `
             + `таблица: это СУММА процентов на ногу, а не процент `
             + `депозита — реплей моделирует слоты, а не размер `
             + `позиции.`},
  nodd: {en: "<b>curve drawdown is empty on purpose</b> \u2014 this "
             + "run was made before the column existed. It fills at "
             + "the next nightly run; nothing is broken.",
         ru: "<b>просадка кривой пуста по делу</b> \u2014 прогон "
             + "сделан до появления колонки. Заполнится ближайшим "
             + "ночным прогоном; ничего не сломано."},
  gtitle: {en: "what each column means",
           ru: "что означает каждая колонка"},
  gloss: {en: [
      ["variant", "the branch key: all of its settings in one name."],
      ["edge %", "entry gate \u2014 the smallest move the model has "
       + "to promise for this branch to take the trade at all. "
       + "0.22 % is twice the cost round of a leg; 0.33 % is a "
       + "pickier branch that trades less."],
      ["RR \u2265", "required ratio of the promised favourable move "
       + "to the risk, measured on the stop the branch actually "
       + "places."],
      ["stop", "where the stop level comes from: the learned "
       + "quantile, the forecast line, or no stop at all."],
      ["target", "whether the branch closes at the promised "
       + "favourable move, or only by stop and time."],
      ["age h", "how long a position may live before it is closed "
       + "by time."],
      ["trades / win", "how many trades the branch took and the "
       + "share that ended in profit."],
      ["expect %", "average result of a trade \u2014 the default "
       + "ranking of this table."],
      ["median %", "result of the middle trade. A big gap from "
       + "expectancy means the branch lives on a tail, not on its "
       + "typical trade."],
      ["total %", "sum of all its trades."]],
          ru: [
      ["вариант", "ключ ветки: все её настройки одним именем."],
      ["край %", "порог входа \u2014 насколько крупный ход модель "
       + "должна обещать, чтобы ветка вообще взяла сделку. 0.22 % "
       + "это двойной круг издержек на ногу; 0.33 % \u2014 ветка "
       + "придирчивее и торгует реже."],
      ["RR \u2265", "требуемое отношение обещанного хода в пользу к "
       + "риску, считанное по тому стопу, который ветка реально "
       + "ставит."],
      ["стоп", "откуда берётся уровень стопа: выученный квантиль, "
       + "линия прогноза или стопа нет вовсе."],
      ["тейк", "закрывает ли ветка по обещанной цели или только по "
       + "стопу и времени."],
      ["возраст ч", "сколько позиция может жить до закрытия по "
       + "времени."],
      ["сделок / побед", "сколько сделок ветка взяла и какая доля "
       + "кончилась прибылью."],
      ["ожид. %", "средний результат сделки \u2014 по нему таблица "
       + "и упорядочена по умолчанию."],
      ["медиана %", "результат средней сделки. Крупное расхождение с "
       + "ожиданием означает, что ветка живёт хвостом, а не обычной "
       + "своей сделкой."],
      ["итог %", "сумма всех её сделок."]]},
  wait: {en: "no answer from the collector — retrying",
         ru: "сборщик не ответил — повторяю"},
  cols: {en: ["variant", "edge %", "RR \u2265", "stop", "target",
              "age h", "trades", "win", "expect %", "median %",
              "total %", "worst trade %", "curve drawdown %"],
         ru: ["вариант", "край %", "RR \u2265", "стоп", "тейк",
              "возраст ч", "сделок", "побед", "ожид. %",
              "медиана %", "итог %", "худшая сделка %",
              "просадка кривой %"]},
  stop: {en: {q: "quantile", m: "forecast line", none: "no stop"},
         ru: {q: "квантиль", m: "линия прогноза", none: "без стопа"}},
  yes: {en: "yes", ru: "да"}, no: {en: "no", ru: "нет"},
  cur: {en: "current rules", ru: "текущие правила"},
  thin: {en: "thin", ru: "мало"},
  tree: {en: "model tree \u2192", ru: "дерево моделей \u2192"},
  stale: {en: h => `<b>the nightly run has not come</b> \u2014 this `
            + `table is ${h} h old. The numbers below describe the `
            + `journal as it was then, not now; check the watchdog `
            + `and the run log on the server.`,
          ru: h => `<b>ночной прогон не пришёл</b> \u2014 таблице `
            + `${h} ч. Числа ниже описывают журнал на тот момент, а `
            + `не сейчас; проверить сторож и лог прогона на сервере.`},
};
function T(k){ const v = UI[k]; return v[LANG] || v.en; }
function cls(v){ return v == null ? "" : v > 0 ? "good"
  : v < 0 ? "bad" : ""; }
const COLS = ["key", "edge", "rr", "stop", "take", "age",
              "n", "win", "exp_bp", "med_bp", "total_bp", "worst_bp",
              "dd_bp"];
function sortRows(d){
  const rows = (d.cells || []).map((c, i) => Object.assign({_i: i}, c));
  const col = SORT ? SORT.col : DEFAULT_SORT;
  const asc = SORT ? SORT.asc : false;
  const sink = RESULT_COLS.indexOf(col) >= 0;
  // Ранг годности: измеренная → тонкая → пустая. Он старше самой
  // величины, поэтому сравнивается первым.
  const rank = c => !c.n ? 2 : (c.n < d.min_cell ? 1 : 0);
  rows.sort((a, b) => {
    if (sink && rank(a) !== rank(b)) return rank(a) - rank(b);
    const va = a[col], vb = b[col];
    if (va == null && vb == null) return a._i - b._i;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (va === vb) return a._i - b._i;
    return asc ? (va < vb ? -1 : 1) : (va > vb ? -1 : 1);
  });
  return rows;
}
function render(d){
  DATA = d;
  navMount("/tournament-page");
  document.getElementById("strap").textContent = T("strap");
  document.getElementById("lang").innerHTML =
    ["en","ru"].map(v => `<button data-l="${v}"
      aria-pressed="${String(LANG === v)}">${v.toUpperCase()}</button>`)
      .join(" ");
  document.querySelectorAll("#lang button").forEach(b =>
    b.onclick = () => setLang(b.dataset.l));
  const intro = document.getElementById("intro");
  const selbox = document.getElementById("selbox");
  const box = document.getElementById("box");
  if (!d) {
    intro.textContent = T("wait");
    setTimeout(pull, 5000);
    return;
  }
  if (!d.present) {
    intro.innerHTML = `${esc(d.status || "")} ·
      <a href="/tree-page?k=${encodeURIComponent(KEY)}">${T("tree")}</a>`;
    selbox.innerHTML = ""; box.innerHTML = "";
    return;
  }
  intro.innerHTML = `<div class="frame">${T("frame")}</div>
    ${T("head")(d)} ·
    <a href="/tree-page?k=${encodeURIComponent(KEY)}">${T("tree")}</a>
    ${d.stale ? `<div class="warn">${T("stale")(
        Math.round(d.run_age_sec / 3600))}</div>` : ""}
    <div class="warn"><b>!</b> ${T("guard")}</div>`;
  // Селектор: пока точек нет — его честный статус из артефакта;
  // появятся — числа рядом с нулями (случайный, оракул, референс).
  const wf = d.wf, v = d.verdict || {};
  let sl = `<div class="cap">${T("selcap")}</div>`;
  if (!wf) {
    sl += esc(v.status || "");
  } else {
    sl += `${esc(v.status || "")}<div class="mono" style="margin-top:6px">
      selector ${pct(wf.sel && wf.sel.total_bp)} ·
      random median ${pct(v.rnd_median_bp)} / max ${pct(v.rnd_p95_bp)} ·
      oracle ${pct(wf.ora && wf.ora.total_bp)} ·
      current ${pct(wf.ref && wf.ref.total_bp)} ·
      kill-10 ${pct(wf.kill && wf.kill.total_bp)}
      (${(wf.kill_events || []).length} kills)</div>`;
  }
  selbox.innerHTML = sl;
  document.getElementById("tcap").textContent = T("tcap");
  // Расшифровка колонок — под раскрытие: на экране их тринадцать, и
  // абзацем подряд они вытеснили бы саму таблицу. Владелец спрашивал
  // про «мало», «current rules», «worst» и «edge» по очереди —
  // значит объяснять надо ВСЕ, а не те, о которых уже спросили.
  document.getElementById("tlegend").innerHTML = T("legend")(d)
    + (d.has_dd === false ? `<div class="warn">${T("nodd")}</div>`
                          : "")
    + `<details class="gloss"><summary>${T("gtitle")}</summary>${
        T("gloss").map(r => `<div class="grow"><b>${esc(r[0])}</b> — ${
          esc(r[1])}</div>`).join("")}</details>`;
  const rows = sortRows(d);
  const H = T("cols");
  box.innerHTML = `<table><thead><tr>${H.map((h, i) =>
    `<th onclick="sortBy('${COLS[i]}')">${h}${
      (SORT ? SORT.col : DEFAULT_SORT) === COLS[i]
        ? ((SORT && SORT.asc) ? " \u2191" : " \u2193") : ""}</th>`
    ).join("")}</tr></thead><tbody>${
    rows.map(c => {
      const cur = c.key === d.current;
      const thin = (c.n || 0) > 0 && c.n < d.min_cell;
      const name = `<span class="mono">${esc(c.key)}</span>${
        cur ? ` <span style="color:var(--accent)">· ${T("cur")}</span>`
            : ""}`;
      if (!c.n)
        return `<tr${cur ? ' class="hl"' : ""}><td>${name}</td>
          <td>${lvl(c.edge)}</td><td>${c.rr}</td>
          <td>${T("stop")[c.stop]}</td>
          <td>${c.take ? T("yes") : T("no")}</td><td>${c.age}</td>
          <td>0</td><td>\u2014</td><td>\u2014</td><td>\u2014</td>
          <td>\u2014</td><td>\u2014</td><td>\u2014</td></tr>`;
      return `<tr class="${cur ? "hl" : ""}${thin ? " thin" : ""}">
        <td>${name}${thin ? ` <span class="dim">·${T("thin")}</span>`
                          : ""}</td>
        <td>${lvl(c.edge)}</td><td>${c.rr}</td>
        <td>${T("stop")[c.stop]}</td>
        <td>${c.take ? T("yes") : T("no")}</td><td>${c.age}</td>
        <td class="mono">${c.n}</td>
        <td class="mono">${Math.round((c.win || 0) * 100)} %</td>
        <td class="mono ${cls(c.exp_bp)}">${pct(c.exp_bp)}</td>
        <td class="mono ${cls(c.med_bp)}">${pct(c.med_bp)}</td>
        <td class="mono ${cls(c.total_bp)}">${pct(c.total_bp)}</td>
        <td class="mono ${cls(c.worst_bp)}">${pct(c.worst_bp)}</td>
        <td class="mono ${cls(c.dd_bp)}">${pct(c.dd_bp)}</td>
      </tr>`;
    }).join("")}</tbody></table>`;
}
async function pull(){
  let d = null;
  try {
    const r = await fetch("/tournament?k=" + encodeURIComponent(KEY));
    d = await r.json();
  } catch (e) { d = null; }
  render(d);
}
pull();
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
""" + NAVCSS + r"""</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">league — what works best</span>
  <span style="flex:1"></span>
  <span id="per"></span></div>
<div id="nav"></div>
<div class="k" style="margin-bottom:8px"><a id="pb"
  href="#">what each situation means &rarr;</a></div>
<div id="note" class="k"></div>
<div id="box">&hellip;</div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + BOOKJS + NAVJS + r"""
navMount("/league-page");
// Названия ситуаций в таблицах — короткие ярлыки; что каждая значит,
// объясняет справочник, и ссылка на него стоит рядом с ними.
document.getElementById("pb").href =
  "/glossary-page?k=" + encodeURIComponent(KEY);
let PERIOD = "30d", DATA = null;

""" + PCTJS + r"""
function utc(ts){ if (!ts) return "—";
  return new Date(ts*1000).toISOString().slice(5,16).replace("T"," "); }
const ARM_EN = {gbm:"trees (ML)", nn:"neural (AI)"};
// Имена книг — из ОДНОГО списка на все страницы. Своя таблица здесь
// уже разошлась с ним: после перевода на per σ она называла главную
// книгу «4 h book», а книгу в σ — «ranked per σ», то есть говорила,
// что в σ упорядочена одна из пяти, тогда как их четыре. Молчаливая
// подмена смысла при неизменном виде — тот же класс, что молчаливый
// ноль в числах.
const BOOK_EN = Object.fromEntries(BOOK_LIST);
const FAM_EN = {absorption:"book eaten (absorption)",
  book:"book imbalance / depth", tape:"tape pressure",
  liq:"liquidations", oi:"open interest", funding:"funding & basis",
  move:"price move / reversal", squeeze:"squeeze", tilt:"tilt",
  range:"range / dwell", vol:"volatility regime",
  leader:"leader & sector", clock:"time of day",
  round:"round levels", beta:"market beta", age:"listing age"};
const PER_EN = {today:"today (utc)", "30d":"last 30 days",
                "365d":"last 365 days"};

function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
  .replace(/"/g,"&quot;"); }
// Парное сравнение книг: одно сечение, один горизонт, различается
// ровно порядок. Итоги рядом в таблице книг считаны на разном числе
// часов и на разных именах, и разница в них читается как
// превосходство — а она может не отличаться от нуля. Разность мерится
// парно и с интервалом, как `compare_arms` в R5.
function pairPanel(){
  const ps = (DATA && DATA.pairs) || [];
  if (!ps.length) return "";
  return ps.map(p => {
    const nm = a => BOOK_EN[a] || a;
    if (p.thin) {
      // «0 общих часов» выглядит поломкой, поэтому пустая сторона
      // называется прямо. Пара переехала на 24 ч в день, когда главная
      // книга сама перешла на порядок в σ: сравнивать её с собственной
      // копией было бы нечем, а новая половина копит первые сделки.
      const why = !p.a_hours || !p.b_hours
        ? `${!p.a_hours ? nm(p.a) : nm(p.b)} has no closed trades yet —
           the pair fills as it closes its first ones`
        : `only ${p.hours} shared hours — too few to compare`;
      return `<div class="panel"><div class="cap">${nm(p.a)} vs ${
        nm(p.b)}</div><div class="dim">${why}</div>
        <div class="k" style="margin-top:6px">this pair is the only
        place left to answer «does per σ help»: 4 h, 1 h and the
        situational book all moved to that ordering, so 24 h runs both
        orderings side by side — same section, same geometry, one
        thing different.</div></div>`;
    }
    const win = p.covers_zero
      ? `the interval covers zero: on this history the difference
         <b>cannot be claimed</b>, whatever its size`
      : `the interval does not cover zero`;
    return `<div class="panel"><div class="cap">${nm(p.a)} vs ${
      nm(p.b)} — paired on shared hours</div>
      <div>${nm(p.a)} beats ${nm(p.b)} in <b>${
        Math.round(p.a_wins*100)} %</b> of ${p.hours} shared hours ·
        mean difference <b class="${p.mean_bp > 0 ? "good" : "bad"}">${
        pct(p.mean_bp)}</b> per hour ·
        95 % interval [${pct(p.lo_bp)}, ${pct(p.hi_bp)}]</div>
      <div class="k" style="margin-top:6px">${win}. Both books rank the
        same section over the same horizon and differ only in the
        ordering, so they are compared hour by hour — totals side by
        side are counted over different hours and different names.</div>
      </div>`;
  }).join("");
}
// Две разбивки по ситуациям различаются ЕДИНИЦЕЙ СЧЁТА, и без
// объяснения они выглядели бы как две противоречивые таблицы. Вопрос
// владельца, из которого раздел и вырос: входят ли в статистику
// одинаковые сделки разных книг.
function ONCE_NOTE(p){
  const n = p.n || 0, d = p.decisions || 0;
  return `A decision is one name, one hour, one side. Four traded
    books rank the SAME section with the same weights — they differ in
    horizon and rules — and both arms take it too, so one decision
    enters the table up to seven times. Here it votes once:
    <b>${d}</b> decisions behind <b>${n}</b> trades. Its money is the
    MEAN of its copies — the sum is the table below, and picking the
    best copy would be choosing the outcome afterwards. The label is
    what most copies read; copies disagree about half the time,
    because each book predicts its own horizon.`;
}
function EVERY_NOTE(p){
  const n = p.n || 0, d = p.decisions || 0;
  return `The same breakdown counted as the books traded it: every
    position is its own row, because every book has its own capital
    and its own position on the exchange. The money here is real —
    what is not real is the count of observations: <b>${n}</b> rows
    stand on <b>${d}</b> decisions, and a name that several books
    picked at the same hour speaks here with several voices.`;
}
function groupTable(cap, rows, names, note){
  if (!rows || !rows.length)
    return `<div class="panel"><div class="cap">${cap}</div>
      <div class="dim">nothing closed in this period</div>${
        note ? `<div class="k">${note}</div>` : ""}</div>`;
  // Лидер — просто верхняя строка сортировки по деньгам. При малом
  // числе сделок это шум, и число стоит в той же строке нарочно.
  // Таблица завёрнута в прокрутку, как таблицы топа: панель узкая, и
  // без неё правые колонки СРЕЗАЛИСЬ — владелец видел «avg net» без
  // процента и деньги не видел вовсе.
  // Колонка «без лучшего имени» стоит РЯДОМ с деньгами, а не в
  // подсказке: группа из тысячи сделок выглядит статистикой, и
  // владелец прочёл «book imbalance / depth» как лучшую стратегию —
  // тогда как её +331 $ это TUT, XAN и THE, а без них −84 $. Пока
  // разница не стоит в строке, её не видно.
  return `<div class="panel"><div class="cap">${cap}</div>
    <div class="scroll"><table><tr><th></th><th>trades</th><th>wins</th>
    <th>avg net</th><th>$</th><th>$ w/o best name</th></tr>`
    + rows.map((g, i) =>
    `<tr><td>${i === 0 ? "&#9733; " : ""}${
       (names && names[g.key]) || g.key}</td>
     <td class="mono">${g.n}</td>
     <td class="mono">${Math.round(g.win*100)} %</td>
     <td class="mono">${pct(g.net_bp_avg)}</td>
     <td class="mono ${g.pnl > 0 ? "good" : "bad"}">${
       g.pnl > 0 ? "+" : ""}${g.pnl}</td>
     <td class="mono ${g.pnl_wo_top > 0 ? "good" : "bad"}"
       title="${esc(g.top_sym || "")} alone gives ${
         g.top_pnl > 0 ? "+" : ""}${g.top_pnl} $ of it; ${
         g.syms} names in the group">${
       g.pnl_wo_top == null ? "&mdash;"
       : (g.pnl_wo_top > 0 ? "+" : "") + g.pnl_wo_top}</td></tr>`)
      .join("")
    + `</table></div><div class="k">The last column drops the single
       best-earning name of each group. A group whose money survives
       only with that one name is a pump, not a behaviour: a thousand
       trades look like statistics, and one name can still be all of
       it.</div>${note ? `<div class="k">${note}</div>` : ""}</div>`;
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
    ${groupTable("books (horizon \u00b7 ordering)", g.book, BOOK_EN)}
    ${pairPanel()}
    ${groupTable("situations \u00b7 one decision, one vote",
                 g.setup_once, FAM_EN, ONCE_NOTE(p))}
    ${groupTable("situations \u00b7 every trade counted",
                 g.setup, FAM_EN, EVERY_NOTE(p))}
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



# Страница автономной системы: конвейер ролей и механических шагов,
# границы и то, что уже построено.
#
# Тексты — из реестра `research/factory/agents.py`, того самого, из
# которого запускалка позже соберёт промпты. Прозы в самой странице
# нет намеренно: описание, живущее только в HTML, разошлось бы с
# системой при первой же правке — и страница осталась бы выглядеть
# исправной.
#
# Рамка предмета стоит ПЕРВЫМ абзацем и объясняет, что агент — не
# живая сессия, а рецепт запуска. Урок листа турнира: объяснение,
# живущее только на соседней странице, эту не защищает, а сюда
# приходят прямо из меню.
# --- страница построенного автономной системой -----------------------
#
# Просьба владельца: всё, что система объявила и что прошло проверки, —
# механика в корне, ветки под ней, описание простыми словами и сделки
# бумажной книги.
#
# Три правила показа, каждое из уроков проекта:
#
# * ФОРВАРД и РЕПЛЕЙ ПО ПРОШЛОМУ никогда не складываются. Кандидат
#   реплеится по всему журналу листов, а вперёд торгует со дня
#   объявления; сумма читалась бы треком, будучи наполовину бэктестом.
# * Чисел ещё нет — прочерк с НАЗВАННОЙ причиной, а не ноль.
# * Вылетевшие показываются вместе с живыми: «лучшая из семи» и
#   «лучшая из семи, где четыре выбыли» — разные утверждения.
BUILTPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>built by the system — mechanics and their books</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.6 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:14px 16px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
.frame{border-left:2px solid var(--accent);padding-left:10px;
 font-size:13px;margin:0 0 10px}
.frame b{color:var(--accent);font-weight:600}
.warn{border-left:2px solid var(--ask);padding-left:10px;
 font-size:12.5px;color:var(--muted);margin:10px 0 0}
.warn b{color:var(--ask);font-weight:600}
.strip{display:grid;gap:8px;
 grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 margin:10px 0 0}
.st{background:linear-gradient(180deg,rgba(151,71,255,.06),
 rgba(151,71,255,0));border:1px solid var(--rule);border-radius:12px;
 padding:9px 11px}
.st .lab{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
 color:var(--muted)}
.st .val{font-size:17px;font-weight:700;margin-top:2px}
.st .val small{font-size:11.5px;font-weight:500;color:var(--muted)}
.root{border:1px solid var(--rule);border-radius:14px;padding:12px 14px;
 margin:11px 0;background:rgba(255,255,255,.012);
 border-left:3px solid var(--accent)}
.rhead{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.rname{font-weight:700;font-size:15px}
.chip{font-size:10px;letter-spacing:.1em;text-transform:uppercase;
 border:1px solid var(--rule);border-radius:999px;padding:2px 8px;
 color:var(--muted);white-space:nowrap}
.chip.sel{border-color:var(--accent);color:var(--accent)}
.chip.ctl{border-color:var(--rule);color:var(--muted)}
.chip.out{border-color:var(--ask);color:var(--ask)}
.chip.on{border-color:var(--bid);color:var(--bid)}
/* Стратегии идут ТАБЛИЦЕЙ, а не карточками (просьба владельца:
   «стратегии просто списком в виде таблицы, описание стратегий на
   странице стратегии, тут так много текста не нужно»). Список
   отвечает на один вопрос — какие испытания идут и как они стоят по
   числам; всё, что требует абзаца (правило словами, довод
   объявления, причина отсутствия книги), живёт на странице
   стратегии. Соединительных линий дерева нет намеренно: книги под
   одной механикой не потомки друг друга, а параллельные испытания. */
tr.row{cursor:pointer}
tr.row:hover td{background:rgba(151,71,255,.07)}
tr.row.out{opacity:.62}
td.key{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-weight:600}
td.key a{color:var(--ink);text-decoration:none}
tr.row:hover td.key a{color:var(--accent)}
.bhead{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.tolink{font-size:12px;color:#2f6feb;text-decoration:none;white-space:nowrap}
.bkey{font-weight:700;font-size:12.5px;font-family:ui-monospace,
 Menlo,Consolas,monospace}
.plain{font-size:13px;margin:6px 0 0}
.nums{display:grid;gap:6px 14px;margin:8px 0 0;
 grid-template-columns:repeat(auto-fit,minmax(132px,1fr))}
.f{font-size:12.5px}
.f .lab{color:var(--muted);font-size:10.5px;letter-spacing:.09em;
 text-transform:uppercase;display:block}
.up{color:var(--bid)}
.dn{color:var(--ask)}
.note{font-size:12px;color:var(--muted);margin:7px 0 0}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:5px 8px;text-align:left;white-space:nowrap;
 border-bottom:1px solid var(--rule-soft)}
th{color:var(--muted);font-weight:600}
td.num,th.num{text-align:right}
.scroll{overflow-x:auto;margin:8px 0 0}
a{color:var(--accent)}
button{background:var(--chip);border:1px solid var(--rule);
 color:var(--ink);border-radius:999px;padding:3px 11px;font-size:11.5px;
 cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
</style>
""" + NAVCSS + r"""</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k" id="strap"></span>
  <span style="flex:1"></span>
  <span id="lang"></span></div>
<div id="nav"></div>
<div class="panel"><div id="frame"></div><div id="strip"></div>
  <div id="alarm"></div></div>
<div class="panel"><div class="cap" id="tcap"></div>
  <div id="tree">&hellip;</div></div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + r"""
let LANG = new URLSearchParams(location.search).get("lang")
  || (function(){ try { return localStorage.getItem("algoth_lang"); }
                  catch (e) { return null; } })() || "en";
let DATA = null;

const UI = {
  strap: {en: "built by the autonomous system",
          ru: "построено автономной системой"},
  tcap: {en: "mechanics and the strategies under them",
         ru: "механики и стратегии под ними"},
  declared: {en: "declared", ru: "объявлено"},
  alive: {en: "alive", ru: "живо"},
  retired: {en: "retired", ru: "вылетело"},
  effn: {en: "effective N", ru: "эффективное N"},
  space: {en: "space declared", ru: "пространство"},
  hkey: {en: "strategy", ru: "стратегия"},
  hlane: {en: "lane", ru: "полоса"},
  live: {en: "live, $", ru: "живая, $"},
  lclosed: {en: "closed", ru: "закрыто"},
  nobook: {en: "no live book", ru: "живой книги нет"},
  fwd: {en: "forward, % of gross", ru: "форвард, % гросса"},
  pre: {en: "backtest, % of gross", ru: "бэктест, % гросса"},
  trades: {en: "trades", ru: "сделок"},
  days: {en: "days", ru: "суток"},
  sel: {en: "selected", ru: "отобран"},
  ctl: {en: "control", ru: "случайный"},
  out: {en: "retired", ru: "вылетел"},
  none: {en: "nothing declared yet — the system has not passed a "
             + "candidate through the ceiling",
         ru: "не объявлено ничего — система ещё не провела ни одного "
             + "кандидата через потолок"}};

function T(k){ const v = UI[k]; return v ? (v[LANG] || v.en) : k; }
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function sgn(v){ return v == null ? "dim" : (v > 0 ? "up"
  : (v < 0 ? "dn" : "dim")); }
// Базисный пункт гросса — единица ФАБРИКИ: в ней считает и отчёт
// суточного прогона, и потолок. Общий `pct` здесь не зовётся не по
// забывчивости: он форматирует ПРОЦЕНТ движения цены, а это другая
// величина, и печатать её тем же знаком значило бы обещать
// сопоставимость, которой нет.
function ts(t){ if (!t) return "&mdash;";
  const d = new Date(t * 1000);
  return d.toISOString().slice(5, 16).replace("T", " "); }

function langBox(){
  const el = document.getElementById("lang");
  if (!el) return;
  el.innerHTML = ["en", "ru"].map(l =>
    `<button data-l="${l}" aria-pressed="${LANG === l}">${l}</button>`
    ).join(" ");
  el.querySelectorAll("button").forEach(b =>
    b.onclick = () => setLang(b.dataset.l));
}
function setLang(l){
  LANG = l;
  try { localStorage.setItem("algoth_lang", l); } catch (e) {}
  render();
}

// РАМКА — первое, что читается, и она обязана сказать, чем эти деньги
// НЕ являются. Без неё страница из книг с плюсами читается как список
// работающих стратегий, а это ровно ошибка R5 в виде страницы.
function frameHtml(d){
  const cap = d.cap, win = d.window_d;
  if (LANG === "ru") return `<p class="frame"><b>Это не список
    работающих стратегий.</b> Здесь книги, которые автономная система
    объявила испытаниями: каждая — строка параметров того, что движок
    уже умеет, а не отдельно обученная модель. Веса у всех одни и те
    же; различаются правила обращения с прогнозом, поэтому разницу
    результатов и можно приписать правилу.</p>
    <p class="frame"><b>У каждого объявленного кандидата — ЖИВАЯ
    бумажная книга</b>, и у отобранного ассистентом, и у случайного
    из контрольной руки. Живая значит настоящая машинерия: тот же
    пятисекундный сканер, та же касса со слотами и потолком на имя,
    те же издержки и те же выходы по уровням, что у книг ядра.
    Различается ровно правило, объявленное реестром испытаний.
    Случайная рука ведётся так же не из щедрости: заведи живую книгу
    одной полосе и пересчёт другой — сравнивались бы две системы
    измерения, а не две полосы.</p>
    <p class="frame"><b>Рядом с живой книгой стоит её РЕПЛЕЙ</b> — то
    же правило, прогнанное по журналу листов. Он отвечает на другой
    вопрос («что бы вышло»), и держат его затем, что живая книга и
    реплей обязаны сходиться на общих днях: расхождение при одном
    правиле и одних данных есть дефект в одном из двух.</p>
    <p class="frame"><b>Форвард и реплей прошлого не складываются
    никогда.</b> Кандидат реплеится по всему журналу листов, а вперёд
    торгует только со дня объявления. Дни до объявления — пересчёт по
    прошлому, которое ассистент видел, когда предлагал; предъявлять их
    как результат нельзя. Правило вылета этим не задето: книгу оно не
    судит, пока ей меньше ${win} суток, то есть судит уже по
    форварду.</p>`;
  return `<p class="frame"><b>This is not a list of working
    strategies.</b> These are books the autonomous system declared as
    trials: each is a row of parameters over what the engine already
    does, not a separately trained model. The weights are the same for
    all of them; what differs is the rule for handling the forecast,
    which is why a difference in results can be attributed to the
    rule.</p>
    <p class="frame"><b>Every declared candidate gets a LIVE paper
    book</b> — both the assistant-selected ones and the random
    control arm. Live means the real machinery: the same five-second
    scanner, the same cash with slots and the per-name cap, the same
    costs and the same level exits as the core books. What differs is
    exactly the rule the trials ledger declared. The control arm is run
    the same way not out of generosity: give one lane a live book and
    the other a recomputation, and you would be comparing two systems
    of measurement rather than two lanes.</p>
    <p class="frame"><b>Beside the live book stands its REPLAY</b>
    — the same rule run over the sheet journal. It answers a
    different question ("what would have come out"), and it is kept
    because the live book and the replay must agree on the days they
    share: a divergence under one rule and one data set is a defect in
    one of the two.</p>
    <p class="frame"><b>Forward and replay-of-the-past are never
    summed.</b> A candidate is replayed over the whole sheet journal but
    trades forward only from the day it was declared. Days before that
    are a recomputation over a past the assistant had already seen when
    proposing. The retirement rule is untouched by this: it does not
    judge a book younger than ${win} days, so it judges the forward
    part.</p>`;
}

// Строка списка: только числа и пометки. Прозу — правило словами,
// довод объявления, причину отсутствия живой книги — печатает
// страница стратегии; здесь она стояла бы стеной текста и прятала то,
// ради чего список и открывают: как испытания стоят друг против
// друга. Причина при этом не теряется: она едет подсказкой на самом
// прочерке, а полностью читается на странице стратегии.
function rowHtml(b){
  const lane = b.lane === "selected" ? "sel" : "ctl";
  const money = b.live == null || b.live.pnl == null
    ? `<span class="dim" title="${esc(b.live_why || T("nobook"))}"
        >&mdash;</span>`
    : `<span class="${sgn(b.live.pnl)}">${b.live.pnl > 0 ? "+" : ""}${
        Number(b.live.pnl).toFixed(2)}</span>` + (
        // Доля к ДЕПОЗИТУ книги: у стратегии он свой (1000 $ на руку,
        // решение владельца), и делить её деньги на чужое число
        // значило бы показать неверный процент исправной таблицей.
        b.live.start ? `<span class="dim"> ${
          pct((b.live.pnl / b.live.start) * 1e4)}</span>` : "");
  const num = (v, cls) => v == null
    ? `<span class="dim" title="${esc(b.no_numbers || "")}">&mdash;</span>`
    : `<span class="${cls || ""}">${v}</span>`;
  return `<tr class="row${b.alive ? "" : " out"}"
      data-open="${esc(b.key)}">
    <td class="key"><a href="${stratHref(b.key)}">${esc(b.key)}</a></td>
    <td><span class="chip ${lane}">${T(lane)}</span>${b.alive ? ""
      : ` <span class="chip out">${T("out")}</span>`}</td>
    <td class="num mono">${money}</td>
    <td class="num mono">${b.live == null
      ? `<span class="dim">&mdash;</span>` : b.live.closed}</td>
    <td class="num mono">${num(b.fwd == null ? null : pct(b.fwd),
      sgn(b.fwd))}</td>
    <td class="num mono">${num(b.fwd_days)}</td>
    <td class="num mono">${num(b.trades)}</td>
    <td class="num mono dim">${num(b.pre == null ? null : pct(b.pre))}</td>
    </tr>`;
}

// Адрес страницы стратегии живёт ОДНОЙ функцией: карточка кликается
// целиком, а внутри стоит настоящая ссылка (её видно в строке
// состояния и можно открыть в новой вкладке), и два места, строящие
// один адрес, однажды разошлись бы.
function stratHref(key){
  return "/strategy-page?k=" + encodeURIComponent(KEY)
    + "&id=" + encodeURIComponent(key);
}

// Карточка кликается целиком — но клик по ССЫЛКЕ внутри неё браузер
// обрабатывает сам, и перехватывать его значило бы ломать открытие в
// новой вкладке (тот же случай, что клик по ссылке в строке таблицы
// на панели ядра).
function cardClick(ev, key){
  if (ev.target && ev.target.closest && ev.target.closest("a")) return;
  location.href = stratHref(key);
}

function render(){
  const d = DATA;
  document.getElementById("strap").textContent = T("strap");
  navMount("/built-page");
  langBox();
  if (!d) return;
  document.getElementById("frame").innerHTML = frameHtml(d);
  document.getElementById("tcap").textContent = T("tcap");
  const t = d.totals || {};
  document.getElementById("strip").innerHTML =
    [[T("declared"), t.declared],
     [T("alive"), t.alive],
     [T("retired"), t.retired],
     [T("effn"), d.eff_n == null ? "&mdash;" : d.eff_n],
     [T("space"), `${t.declared}<small> / ${d.space_available}</small>`]]
    .map(c => `<div class="st"><div class="lab">${c[0]}</div>
      <div class="val">${c[1] == null ? "&mdash;" : c[1]}</div></div>`)
    .join("");
  // Вердикт печатается ДОСЛОВНО из артефакта прогона: он и говорит,
  // что числа ниже суть диагностика, а не результат.
  let al = "";
  if (d.verdict)
    al += `<div class="warn"><b>&#9888;</b> ${esc(d.verdict)}</div>`;
  if (d.art_error)
    al += `<div class="warn"><b>&#9888;</b> ${esc(d.art_error)}</div>`;
  else if (d.run_stale)
    al += `<div class="warn"><b>&#9888;</b> ` + (LANG === "ru"
      ? `суточный прогон не приходил ${Math.round(
          d.run_age_sec / 3600)} ч — числа устарели`
      : `no daily run for ${Math.round(d.run_age_sec / 3600)} h — `
        + `the numbers are stale`) + `</div>`;
  document.getElementById("alarm").innerHTML = al;
  const roots = d.roots || [];
  const th = `<tr><th>${T("hkey")}</th><th>${T("hlane")}</th>
    <th class="num">${T("live")}</th><th class="num">${T("lclosed")}</th>
    <th class="num">${T("fwd")}</th><th class="num">${T("days")}</th>
    <th class="num">${T("trades")}</th>
    <th class="num">${T("pre")}</th></tr>`;
  document.getElementById("tree").innerHTML = roots.length
    ? roots.map(r => `<div class="root">
        <div class="rhead"><span class="rname">${esc(r.title)}</span>
          <span class="chip">${r.alive}/${r.n}</span></div>
        <div class="scroll"><table>${th}
          ${r.branches.map(rowHtml).join("")}</table></div>
        </div>`).join("")
    : `<div class="note">${T("none")}</div>`;
  document.getElementById("tree").querySelectorAll("[data-open]")
    .forEach(el => el.onclick = ev => cardClick(ev, el.dataset.open));
}

async function tick(){
  try {
    const r = await fetch("/factory_built?k=" + encodeURIComponent(KEY));
    if (r.ok) DATA = await r.json();
  } catch (e) {}
  render();
}
render();
tick();
setInterval(tick, 60000);
</script>
"""


STRATPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>strategy of the autonomous system</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.6 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:14px 16px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
.frame{border-left:2px solid var(--accent);padding-left:10px;
 font-size:13px;margin:0 0 10px}
.frame b{color:var(--accent);font-weight:600}
.warn{border-left:2px solid var(--ask);padding-left:10px;
 font-size:12.5px;color:var(--muted);margin:10px 0 0}
.warn b{color:var(--ask);font-weight:600}
.strip{display:grid;gap:8px;
 grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:10px 0 0}
.st{background:linear-gradient(180deg,rgba(151,71,255,.06),
 rgba(151,71,255,0));border:1px solid var(--rule);border-radius:12px;
 padding:9px 11px}
.st .lab{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
 color:var(--muted)}
.st .val{font-size:17px;font-weight:700;margin-top:2px}
.st .val small{font-size:11.5px;font-weight:500;color:var(--muted)}
.chip{font-size:10px;letter-spacing:.1em;text-transform:uppercase;
 border:1px solid var(--rule);border-radius:999px;padding:2px 8px;
 color:var(--muted);white-space:nowrap}
.chip.sel{border-color:var(--accent);color:var(--accent)}
.chip.out{border-color:var(--ask);color:var(--ask)}
.chip.on{border-color:var(--bid);color:var(--bid)}
.title{font-weight:800;font-size:16px;font-family:ui-monospace,
 Menlo,Consolas,monospace}
.note{font-size:12px;color:var(--muted);margin:7px 0 0}
.up{color:var(--bid)}
.dn{color:var(--ask)}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:5px 8px;text-align:left;white-space:nowrap;
 border-bottom:1px solid var(--rule-soft)}
th{color:var(--muted);font-weight:600}
td.num,th.num{text-align:right}
tr.thin td{color:var(--muted)}
.scroll{overflow-x:auto;margin:8px 0 0}
.gapv{color:var(--ask)}
a{color:var(--accent)}
button{background:var(--chip);border:1px solid var(--rule);
 color:var(--ink);border-radius:999px;padding:3px 11px;font-size:11.5px;
 cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
</style>
""" + NAVCSS + r"""</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k" id="strap"></span>
  <span style="flex:1"></span>
  <span id="lang"></span></div>
<div id="nav"></div>
<div class="panel"><div id="head">&hellip;</div><div id="strip"></div>
  <div id="alarm"></div></div>
<div class="panel"><div class="cap" id="infocap"></div>
  <div id="info"></div></div>
<div class="panel"><div class="cap" id="daycap"></div>
  <div id="days"></div></div>
<div class="panel"><div class="cap" id="btcap"></div>
  <div id="bt"></div></div>
<div class="panel"><div class="cap" id="twincap"></div>
  <div id="twins"></div></div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
const SID = new URLSearchParams(location.search).get("id") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + PCTJS + r"""
let LANG = new URLSearchParams(location.search).get("lang")
  || (function(){ try { return localStorage.getItem("algoth_lang"); }
                  catch (e) { return null; } })() || "en";
let DATA = null, DAYS = null;

const UI = {
  strap: {en: "strategy of the autonomous system",
          ru: "стратегия автономной системы"},
  dep: {en: "deposit", ru: "депозит"},
  infocap: {en: "what this strategy is", ru: "что это за стратегия"},
  daycap: {en: "live paper book, day by day",
           ru: "живая бумажная книга по дням"},
  btcap: {en: "replay over history", ru: "бэктест на истории"},
  twincap: {en: "how much of it is a separate trial",
            ru: "насколько это отдельное испытание"},
  sel: {en: "selected", ru: "отобрана"},
  ctl: {en: "control (random draw)", ru: "случайный жребий"},
  out: {en: "retired", ru: "вылетела"},
  on: {en: "alive", ru: "жива"},
  live: {en: "live book, $", ru: "живая книга, $"},
  lclosed: {en: "closed live", ru: "закрыто вживую"},
  fwd: {en: "forward, % of gross", ru: "форвард, % гросса"},
  pre: {en: "backtest, % of gross", ru: "бэктест, % гросса"},
  days: {en: "days forward", ru: "суток вперёд"},
  axis: {en: "axis", ru: "ось"},
  want: {en: "declared", ru: "объявлено"},
  got: {en: "applied", ru: "применено"},
  field: {en: "field of the manifest", ru: "поле манифеста"},
  dcol: {en: "day", ru: "день"},
  trades: {en: "trades", ru: "сделок"},
  win: {en: "won", ru: "побед"},
  // В строке реплея вид периода стоит БЕЗ единицы: она уехала в
  // заголовок колонки, а повторять её в каждой строке значит
  // вытеснить сами числа (владелец увидел эту таблицу такой).
  fwds: {en: "forward", ru: "форвард"},
  pres: {en: "backtest", ru: "бэктест"},
  pnl: {en: "% of gross ($)", ru: "% гросса ($)"},
  cum: {en: "cumulative, % ($)", ru: "накоплено, % ($)"},
  wotop: {en: "$ without the best", ru: "$ без лучшей"},
  arm: {en: "arm", ru: "рука"},
  nodays: {en: "no closed trades yet — the book is younger than its "
               + "first exit",
           ru: "закрытых сделок ещё нет — книга моложе первого выхода"},
  nobook: {en: "no live book", ru: "живой книги нет"},
  nobt: {en: "the daily run has not produced numbers for this "
             + "strategy yet",
         ru: "суточный прогон ещё не дал чисел этой стратегии"},
  notwins: {en: "nothing to compare with: no other candidate has a "
                + "live book",
            ru: "сравнивать не с чем: живой книги нет больше ни у "
                + "одного кандидата"},
  tid: {en: "strategy", ru: "стратегия"},
  tinter: {en: "same decisions", ru: "одних решений"},
  tshare: {en: "share", ru: "доля"},
  declared: {en: "declared at", ru: "объявлена"},
  retired: {en: "retired at", ru: "вылетела"},
  open: {en: "open now", ru: "открыто сейчас"},
  totrades: {en: "live trades \u2192", ru: "сделки живой книги \u2192"},
  back: {en: "← all strategies", ru: "← все стратегии"}};

function T(k){ const v = UI[k]; return v ? (v[LANG] || v.en) : k; }
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function sgn(v){ return v == null ? "dim" : (v > 0 ? "up"
  : (v < 0 ? "dn" : "dim")); }
function usd(v){ return v == null ? "—"
  : (v > 0 ? "+" : "") + Number(v).toFixed(2); }
function ts(t){ if (!t) return "—";
  const d = new Date(t * 1000);
  return d.toISOString().slice(0, 16).replace("T", " "); }

function langBox(){
  const el = document.getElementById("lang");
  if (!el) return;
  el.innerHTML = ["en", "ru"].map(l =>
    `<button data-l="${l}" aria-pressed="${LANG === l}">${l}</button>`
    ).join(" ");
  el.querySelectorAll("button").forEach(b =>
    b.onclick = () => setLang(b.dataset.l));
}
function setLang(l){
  LANG = l;
  try { localStorage.setItem("algoth_lang", l); } catch (e) {}
  render();
}

// РАМКА страницы стратегии говорит ровно то, чем эти числа НЕ
// являются, и повторяет её не из вежливости: на страницу стратегии
// приходят по прямой ссылке, минуя список, а объяснение, живущее
// только на соседней странице, соседнюю и защищает.
function frameHtml(){
  if (LANG === "ru") return `<p class="frame"><b>Это испытание
    правила, а не отдельно обученная модель.</b> Веса те же, что у
    книг ядра; различается правило обращения с прогнозом — потому
    разницу результатов и можно приписать правилу.</p>
    <p class="frame"><b>Бэктест и форвард не складываются.</b>
    Бэктест прогнан по журналу листов за прошлое, которое ассистент
    уже видел, когда предлагал стратегию; форвард идёт со дня
    объявления и только он является предъявляемым.</p>`;
  return `<p class="frame"><b>This is a trial of a rule, not a
    separately trained model.</b> The weights are the same as the core
    books'; what differs is the rule for handling the forecast, which
    is why a difference in results can be attributed to the rule.</p>
    <p class="frame"><b>Backtest and forward are never summed.</b> The
    backtest is a replay over a past the assistant had already seen
    when proposing the strategy; the forward runs from the day of
    declaration and only it can be presented.</p>`;
}

function infoHtml(d){
  // Пробел в записи и ось, которую держит гейт заведения, — разные
  // вещи, и красным помечается только первая: покрась обе, и та
  // единственная, где правило может не доехать до сканера, утонет
  // среди законных.
  // Третье состояние — правило ЗАПИСАНО, но СУЖЕНО общим гейтом: книга
  // торгует строже объявленного, а реплей судит по объявленному.
  // Молчать об этом нельзя — строка «применено» читалась бы как
  // исполненное правило.
  const rows = (d.applied || []).map(a => `<tr${
    a.gap || a.by_gate ? ' class="thin"' : ''}>
    <td class="mono">${esc(a.axis)}</td>
    <td class="mono">${esc(a.want)}</td>
    <td class="mono">${a.gap ? '<span class="gapv">&mdash;</span>'
      : (a.by_gate ? "&mdash;" : esc(a.got == null ? "—" : a.got))}</td>
    <td class="dim">${a.gap ? esc(a.gap)
      : (a.narrowed ? '<span class="gapv">' + esc(a.narrowed) + '</span>'
         : esc(a.by_gate || a.field || ""))}</td>
    </tr>`).join("");
  return `<p>${esc(d.plain || "")}</p>
    ${d.note ? `<div class="note">&laquo;${esc(d.note)}&raquo;</div>` : ""}
    ${d.why ? `<div class="note">${esc(d.why)}</div>` : ""}
    ${d.live_why ? `<div class="note">${esc(d.live_why)}</div>` : ""}
    <div class="note">${T("declared")}: ${ts(d.declared_at)}${
      d.retired_at ? " · " + T("retired") + ": " + ts(d.retired_at)
                   : ""}</div>
    <div class="scroll"><table>
      <tr><th>${T("axis")}</th><th>${T("want")}</th>
        <th>${T("got")}</th><th>${T("field")}</th></tr>
      ${rows}</table></div>`;
}

function daysHtml(b){
  if (!b) return `<div class="note">&hellip;</div>`;
  if (b.unknown || !b.present)
    return `<div class="note">&mdash; ${T("nodays")}</div>`;
  const rows = (b.days || []).map(x => {
    const c = (x.arms || {}).all;
    if (!c) return "";
    return `<tr><td class="mono">${esc(x.day)}</td>
      <td class="num">${c.trades}</td>
      <td class="num">${Math.round(c.win * 100)}%</td>
      <td class="num mono ${sgn(c.pnl)}">${usd(c.pnl)}</td>
      <td class="num mono ${sgn(c.cum)}">${usd(c.cum)}</td>
      <td class="num mono ${sgn(c.pnl_wo_top)}">${usd(c.pnl_wo_top)}</td>
      </tr>`;
  }).join("");
  const op = Object.keys(b.open || {}).map(a =>
    `${esc(a)} ${b.open[a].open}`).join(" · ");
  return `<div class="scroll"><table>
      <tr><th>${T("dcol")}</th><th class="num">${T("trades")}</th>
        <th class="num">${T("win")}</th><th class="num">${T("pnl")}</th>
        <th class="num">${T("cum")}</th>
        <th class="num">${T("wotop")}</th></tr>
      ${rows}</table></div>
    ${op ? `<div class="note">${T("open")}: ${op}</div>` : ""}`;
}

function btHtml(d){
  const daily = d.daily || [];
  // База денег приходит с СЕРВЕРА (депозит стратегии), а не считается
  // страницей: два места, решающих капитал, разошлись бы.
  const cap = d.replay_cap == null ? null : Number(d.replay_cap);
  const money = (v) => cap == null ? ""
    : ` <span class="dim">(${(v / 1e4 * cap > 0 ? "+" : "")}${
        (v / 1e4 * cap).toFixed(2)} $)</span>`;
  if (!daily.length)
    return `<div class="note">&mdash; ${esc(d.no_numbers || T("nobt"))}</div>`;
  const cut = d.declared_at
    ? Math.floor(d.declared_at / 86400) : null;
  // Накопленное считается ВНУТРИ периода и обнуляется на границе
  // объявления. Одна сквозная кривая складывала бы бэктест с
  // форвардом — ровно то, что запрещено: до объявления это пересчёт
  // по прошлому, которое ассистент уже видел, когда предлагал.
  // Поймано собственной проверкой: колонка доходила до суммы обеих
  // половин, и та стояла на странице как итог.
  let cum = 0, was = null;
  const rows = daily.map(p => {
    const day = p[0], v = p[1];
    const fwd = cut != null && day >= cut;
    if (was !== null && fwd !== was) cum = 0;
    was = fwd;
    cum = Math.round((cum + v) * 10) / 10;
    const dt = new Date(day * 86400 * 1000).toISOString().slice(0, 10);
    return `<tr${fwd ? "" : ' class="thin"'}>
      <td class="mono">${dt}</td>
      <td>${fwd ? T("fwds") : T("pres")}</td>
      <td class="num mono ${sgn(v)}">${pct(v)}${money(v)}</td>
      <td class="num mono ${sgn(cum)}">${pct(cum)}${money(cum)}</td>
      </tr>`;
  }).join("");
  // Доллары у реплея ВЫВЕДЕНЫ, а не посчитаны кассой: своей кассы у
  // него нет вовсе — он меряет доли гросса. База пересчёта названа
  // числом прямо здесь, иначе доллары читались бы как деньги счёта.
  const base = cap == null ? "" :
    `<div class="note">${LANG === "ru"
      ? "Доллары в скобках — процент от депозита стратегии ("
        + cap.toFixed(0) + " $): у реплея своей кассы нет, он считает "
        + "доли гросса, а деньги книги живут выше, в дневной "
        + "разбивке её сделок."
      : "Dollars in brackets are the percent applied to the "
        + "strategy&rsquo;s deposit (" + cap.toFixed(0) + " $): the "
        + "replay has no cash account of its own — it measures shares "
        + "of gross. The book&rsquo;s real money is above, in the "
        + "day-by-day breakdown of its trades."}</div>`;
  return `<div class="scroll"><table>
    <tr><th>${T("dcol")}</th><th></th><th class="num">${T("pnl")}</th>
      <th class="num">${T("cum")}</th></tr>${rows}</table></div>${base}`;
}

function twinsHtml(d){
  const tw = d.twins || [];
  if (!tw.length)
    return `<div class="note">&mdash; ${T("notwins")}</div>`;
  const rows = tw.map(t => `<tr>
    <td class="mono"><a href="/strategy-page?k=${
      encodeURIComponent(KEY)}&id=${encodeURIComponent(t.id)}"
      >${esc(t.id)}</a></td>
    <td class="num">${t.inter} / ${t.union}</td>
    <td class="num mono ${t.share >= 0.9 ? "dn" : ""}"
      >${t.share == null ? "—" : t.share.toFixed(2)}</td></tr>`)
    .join("");
  const say = LANG === "ru"
    ? "Доля — сколько решений (рука, час, имя, сторона) совпало с "
      + "другой живой книгой. Единица означает, что это ОДНО испытание "
      + "под двумя именами, и знаменатель, считающий их за два, врёт."
    : "The share is how many decisions (arm, hour, name, side) "
      + "coincide with another live book. One means these are ONE "
      + "trial under two names, and a denominator counting them as "
      + "two is lying.";
  return `<div class="scroll"><table>
      <tr><th>${T("tid")}</th><th class="num">${T("tinter")}</th>
        <th class="num">${T("tshare")}</th></tr>${rows}</table></div>
    <div class="note">${say}</div>`;
}

function render(){
  document.getElementById("strap").textContent = T("strap");
  navMount("/built-page");
  langBox();
  const d = DATA;
  if (!d) return;
  const back = `<a href="/built-page?k=${encodeURIComponent(KEY)}"
    >${T("back")}</a>`;
  if (d.error){
    document.getElementById("head").innerHTML =
      `<div class="warn"><b>&#9888;</b> ${esc(d.error)}</div>
       <div class="note">${back}</div>`;
    ["strip", "info", "days", "bt", "twins"].forEach(
      i => document.getElementById(i).innerHTML = "");
    ["infocap", "daycap", "btcap", "twincap"].forEach(
      i => document.getElementById(i).textContent = "");
    return;
  }
  const lane = d.lane === "selected" ? "sel" : "ctl";
  document.getElementById("head").innerHTML =
    `<div class="top"><span class="title">${esc(d.id)}</span>
      <span class="chip ${lane}">${T(lane)}</span>
      <span class="chip ${d.alive ? "on" : "out"}"
        >${d.alive ? T("on") : T("out")}</span>
      <span style="flex:1"></span>${d.live == null ? "" :
        `<a href="/trades-page?k=${encodeURIComponent(KEY)}&hz=${
          encodeURIComponent(d.id)}">${T("totrades")}</a> · `}${back}</div>
     <div class="note">${esc((d.root || {}).title || "")}</div>
     ${frameHtml()}`;
  document.getElementById("strip").innerHTML =
    [[T("live"), d.live == null || d.live.pnl == null ? null
        : usd(d.live.pnl) + (d.live.start
            ? " · " + pct((d.live.pnl / d.live.start) * 1e4) : "")],
     // Депозит — число, от которого считаются и проценты, и доллары.
     // Без него доля на экране висит без знаменателя.
     [T("dep"), d.live == null || !d.live.start ? null
        : Number(d.live.start).toFixed(0) + " $"],
     [T("lclosed"), d.live == null ? null : d.live.closed],
     [T("fwd"), d.fwd == null ? null : pct(d.fwd)],
     [T("days"), d.fwd_days],
     [T("pre"), d.pre == null ? null : pct(d.pre)]]
    .map(c => `<div class="st"><div class="lab">${c[0]}</div>
      <div class="val">${c[1] == null ? "&mdash;" : c[1]}</div></div>`)
    .join("");
  let al = "";
  if (d.art_error)
    al += `<div class="warn"><b>&#9888;</b> ${esc(d.art_error)}</div>`;
  else if (d.run_stale)
    al += `<div class="warn"><b>&#9888;</b> ` + (LANG === "ru"
      ? "суточный прогон не приходил давно — числа бэктеста устарели"
      : "no daily run for a long time — the backtest numbers are stale")
      + `</div>`;
  document.getElementById("alarm").innerHTML = al;
  document.getElementById("infocap").textContent = T("infocap");
  document.getElementById("info").innerHTML = infoHtml(d);
  document.getElementById("daycap").textContent = T("daycap");
  document.getElementById("days").innerHTML =
    d.live == null ? `<div class="note">&mdash; ${esc(
      d.live_why || T("nobook"))}</div>` : daysHtml(DAYS);
  document.getElementById("btcap").textContent = T("btcap");
  document.getElementById("bt").innerHTML = btHtml(d);
  document.getElementById("twincap").textContent = T("twincap");
  document.getElementById("twins").innerHTML = twinsHtml(d);
}

async function tick(){
  try {
    const r = await fetch("/factory_strategy?k=" + encodeURIComponent(KEY)
      + "&id=" + encodeURIComponent(SID));
    if (r.ok) DATA = await r.json();
  } catch (e) {}
  // Разбивку по дням считает ТОТ ЖЕ `book_days`, что и страницу книги
  // ядра: второй расчёт дневных денег разошёлся бы с первым, и две
  // страницы показывали бы разное об одной книге.
  if (DATA && !DATA.error && DATA.live != null){
    try {
      const r2 = await fetch("/book_days?k=" + encodeURIComponent(KEY)
        + "&hz=" + encodeURIComponent(SID));
      if (r2.ok) DAYS = await r2.json();
    } catch (e) {}
  }
  render();
}
render();
tick();
setInterval(tick, 60000);
</script>
"""


ASKSPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>what the system needs from you</title>
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
.wrap{max-width:1100px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:12px 14px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
table{border-collapse:collapse;width:100%}
td,th{padding:6px 8px;text-align:left;border-bottom:1px solid
 var(--rule-soft);font-size:13px;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
.good{color:var(--bid)}.bad{color:var(--ask)}
a{color:var(--accent)}
.big{font-size:19px;font-weight:700}
.alarm{border-color:var(--ask);background:rgba(255,100,115,.08)}
.tag{display:inline-block;font-size:10px;letter-spacing:.1em;
 text-transform:uppercase;border:1px solid var(--rule);
 border-radius:999px;padding:1px 8px;color:var(--muted)}
.tag.wait{border-color:var(--ask);color:var(--ask)}
.tag.done{border-color:var(--bid);color:var(--bid)}
""" + NAVCSS + r"""
</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k">what the system needs from you</span>
  <span style="flex:1"></span>
  <span class="k" id="lead"></span></div>
<div id="nav"></div>
<div class="panel" id="intro"></div>
<div id="box">&hellip;</div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + r"""
navMount("/asks-page");
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function when(ts){ if (!ts) return "&mdash;";
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 16).replace("T", " ") + " UTC"; }

// Рамка предмета первым абзацем: страница отвечает на ОДИН вопрос —
// что не могут сделать агенты сами. Пустая страница здесь означает
// «система ничего не ждёт», а не «страница сломалась», и это надо
// сказать словами: пустота, не объяснившая себя, читается как отказ.
function intro(d){
  return `<div class="cap">what this page is</div>
  <div>Everything here is an action <b>an agent cannot take</b>: an
  account, a paid access, an API key, a decision about money. Agents
  write code and run measurements; they do not sign up, do not pay and
  never put a key anywhere. A request recorded here is what the system
  is waiting on — anywhere else it would live in the prose of one
  report and be read once.</div>
  <div class="k" style="margin-top:6px">State is computed <b>now</b>,
  not stored: where a request names a check (a path that exists once
  the thing is done), the machine looks and says so. Where it does not,
  the state is your word — and the page says that plainly instead of
  dressing a guess as a measurement. An empty page means the system is
  waiting on nothing.</div>`;
}

function askRow(a){
  const wait = a.open;
  const tag = wait ? `<span class="tag wait">waiting</span>`
                   : `<span class="tag done">done</span>`;
  const un = a.unblocks ? `<div class="k">unblocks: ${
    esc(a.unblocks)}</div>` : "";
  const note = a.said_done && a.check_ok !== true
    ? `<div class="k">you said it is done${
        a.done_note ? ": " + esc(a.done_note) : ""}</div>` : "";
  return `<tr><td class="mono">${esc(a.id)}</td>
    <td><b>${esc(a.what)}</b><div class="k">${esc(a.why)}</div>${un}
      ${note}</td>
    <td>${tag}<div class="k">${esc(a.check_how)}</div></td>
    <td class="k">${esc(a.from)}<br>${when(a.at)}</td></tr>`;
}

function render(d){
  const rows = d.asks || [];
  const open = rows.filter(a => a.open);
  const done = rows.filter(a => !a.open);
  let h = "";
  if (open.length)
    h += `<div class="panel alarm"><div class="big">${open.length}
      ${open.length === 1 ? "request is" : "requests are"} waiting on
      you</div><div class="k">Until they are answered the steps below
      cannot move — the machinery is built, the resource is not
      ours to get.</div></div>`;
  else
    h += `<div class="panel"><div class="big good">nothing is waiting
      on you</div><div class="k">No agent has reported anything it
      cannot do itself. This is a real state, not an empty page:
      requests appear here the moment a role reports one.</div></div>`;

  if (rows.length)
    h += `<div class="panel"><div class="cap">requests</div>
      <table><tr><th>id</th><th>what and why</th><th>state</th>
      <th>asked by</th></tr>
      ${open.map(askRow).join("")}${done.map(askRow).join("")}
      </table>
      <div class="k" style="margin-top:8px">A request with no machine
      check is closed by your word, not by the page:
      <span class="mono">jobs/&lt;name&gt;.job</span> with
      <span class="mono">run research/factory/asks.py --done ID</span>.
      A check beats a word: a file that does not exist does not start
      existing because someone said so.</div></div>`;

  const bl = d.blocked || [];
  if (bl.length)
    h += `<div class="panel">
      <div class="cap">mechanics stopped by a request</div><table><tr><th>id</th><th>mechanic</th>
      <th>why it stopped</th></tr>${bl.map(m =>
        `<tr><td class="mono">${esc(m.id)}</td><td>${esc(m.title)}</td>
         <td class="k">${esc(m.note)}</td></tr>`).join("")}</table>
      <div class="k" style="margin-top:8px">The builder built what
      could be built without the missing piece and stopped there; it
      never invents data.</div></div>`;

  const q = (d.queue || []).filter(m => m.state !== "ждёт владельца");
  if (q.length)
    h += `<div class="panel"><div class="cap">mechanics queue (for
      context — nothing here needs you)</div>
      <table><tr><th>id</th><th>mechanic</th><th>state</th></tr>
      ${q.map(m => `<tr><td class="mono">${esc(m.id)}</td>
        <td>${esc(m.title)}</td><td class="k">${esc(m.state)}</td>
        </tr>`).join("")}</table></div>`;

  if (d.broken)
    h += `<div class="panel alarm">broken lines in the journal:
      ${d.broken} — counted, not swallowed.</div>`;
  document.getElementById("box").innerHTML = h;
  document.getElementById("lead").textContent =
    open.length ? open.length + " waiting" : "all clear";
}

fetch("/asks?k=" + encodeURIComponent(KEY))
  .then(r => r.json())
  .then(d => { document.getElementById("intro").innerHTML = intro(d);
               render(d); })
  .catch(e => { document.getElementById("box").innerHTML =
    `<div class="panel alarm">no answer from the collector:
     ${esc(e)} — the page cannot tell "nothing is waiting" from
     "cannot ask", so it says neither.</div>`; });
</script>
"""

AGENTSPAGE = r"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>autonomous system — agents and the conveyor</title>
<style>
:root{color-scheme:dark;
 --bg:#0b0820;--panel:#131029;--chip:#1a1636;--ink:#eceaf6;
 --muted:#8e88ad;--rule:#272250;--rule-soft:#1e1a40;
 --bid:#3ddc7f;--ask:#ff6473;--accent:#9747ff}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1100px 480px at 50% -120px,rgba(105,78,240,.22),
    transparent 65%) fixed,var(--bg);color:var(--ink);
 font:14px/1.6 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,
   sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:14px 14px 56px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:12px}
.brand{font-weight:800;letter-spacing:.24em;font-size:15px;
 color:var(--ink);text-decoration:none}
.brand b{color:var(--accent)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
 font-variant-numeric:tabular-nums}
.k{color:var(--muted);font-size:12px}
.dim{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:14px 16px;margin:12px 0}
.cap{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
 color:var(--muted);margin-bottom:8px}
.frame{border-left:2px solid var(--accent);padding-left:10px;
 font-size:13px;margin:0 0 10px}
.frame b{color:var(--accent);font-weight:600}
.warn{border-left:2px solid var(--ask);padding-left:10px;
 font-size:12.5px;color:var(--muted);margin:10px 0 0}
.warn b{color:var(--ask);font-weight:600}
.strip{display:grid;gap:8px;
 grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 margin:10px 0 0}
.st{background:linear-gradient(180deg,rgba(151,71,255,.06),
 rgba(151,71,255,0));border:1px solid var(--rule);border-radius:12px;
 padding:9px 11px}
.st .lab{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
 color:var(--muted)}
.st .val{font-size:17px;font-weight:700;margin-top:2px}
.st .val small{font-size:11.5px;font-weight:500;color:var(--muted)}
.step{border:1px solid var(--rule);border-radius:12px;padding:11px 13px;
 margin:9px 0;background:rgba(255,255,255,.012)}
.step.role{border-left:3px solid var(--accent)}
.step.mech{border-left:3px solid var(--rule)}
.step.next{box-shadow:0 0 0 1px rgba(151,71,255,.35) inset}
.shead{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.num{font-size:11px;color:var(--muted)}
.sname{font-weight:700}
.chip{font-size:10px;letter-spacing:.1em;text-transform:uppercase;
 border:1px solid var(--rule);border-radius:999px;padding:2px 8px;
 color:var(--muted);white-space:nowrap}
.chip.role{border-color:var(--accent);color:var(--accent)}
.chip.on{border-color:var(--bid);color:var(--bid)}
.chip.off{border-color:var(--ask);color:var(--ask)}
.sbody{margin:7px 0 0;font-size:13px}
.grid{display:grid;gap:6px 14px;margin:8px 0 0;
 grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
.f{font-size:12.5px}
.f .lab{color:var(--muted);font-size:10.5px;letter-spacing:.09em;
 text-transform:uppercase;display:block}
.run{font-size:11.5px;color:var(--muted);margin:6px 0 0}
.step{cursor:pointer}
.chip.live{border-color:var(--bid);color:var(--bid)}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;
 background:var(--bid);margin-right:5px;vertical-align:middle;
 animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
.veil{position:fixed;inset:0;background:rgba(6,4,18,.72);z-index:40;
 display:flex;align-items:flex-start;justify-content:center;
 padding:24px 12px;overflow:auto}
.sheet{background:var(--panel);border:1px solid var(--rule);
 border-radius:14px;padding:16px 18px;max-width:820px;width:100%}
.sheet h3{margin:0 0 2px;font-size:15px}
.sheet .x{float:right;cursor:pointer;color:var(--muted);
 border:1px solid var(--rule);border-radius:999px;padding:2px 10px;
 font-size:12px;background:var(--chip)}
.pre{white-space:pre-wrap;font-family:ui-monospace,Menlo,Consolas,monospace;
 font-size:11.5px;color:var(--muted);background:var(--chip);
 border:1px solid var(--rule-soft);border-radius:10px;padding:9px 11px;
 max-height:280px;overflow:auto;margin:6px 0 0}
.why{font-size:12.5px;color:var(--muted);margin:8px 0 0;
 padding-left:10px;border-left:1px solid var(--rule-soft)}
.why b{color:var(--ink);font-weight:600}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:6px 8px;text-align:left;vertical-align:top;
 border-bottom:1px solid var(--rule-soft)}
th{color:var(--muted);font-weight:600}
td.name{white-space:normal;color:var(--ink);font-weight:600;width:31%}
.scroll{overflow-x:auto}
a{color:var(--accent)}
button{background:var(--chip);border:1px solid var(--rule);
 color:var(--ink);border-radius:999px;padding:4px 12px;font-size:12px;
 cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);
 color:var(--accent)}
@media (max-width:720px){ td.name{width:auto} }
""" + NAVCSS + r"""</style>
<div class="wrap">
<div class="top"><a class="brand" href="#" id="home">ALG<b>O</b>TH</a>
  <span class="k" id="strap"></span>
  <span style="flex:1"></span>
  <span id="lang"></span></div>
<div id="nav"></div>
<div class="panel"><div id="frame"></div><div id="strip"></div>
  <div id="alarm"></div></div>
<div class="panel"><div class="cap" id="scap"></div>
  <div id="sumry"></div></div>
<div class="panel"><div class="cap" id="pcap"></div>
  <div id="pipe">&hellip;</div></div>
<div class="panel"><div class="cap" id="bcap"></div>
  <div class="frame" id="bnote"></div>
  <div class="scroll"><table id="bounds"></table></div></div>
<div class="panel"><div class="cap" id="rcap"></div>
  <div class="frame" id="rnote"></div>
  <div class="scroll"><table id="risks"></table></div></div>
</div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
document.getElementById("home").href = "/?k=" + encodeURIComponent(KEY);
""" + NAVJS + r"""
let LANG = new URLSearchParams(location.search).get("lang")
  || (function(){ try { return localStorage.getItem("algoth_lang"); }
                  catch (e) { return null; } })() || "en";
let DATA = null;

// Подписи страницы переключаются вместе с текстами реестра: половина
// страницы по-русски и половина по-английски выглядела бы исправной
// и читалась бы как недоделка.
const UI = {
  strap: {en: "autonomous system", ru: "автономная система"},
  pcap: {en: "the conveyor, in order",
         ru: "конвейер в порядке исполнения"},
  bcap: {en: "what no agent touches", ru: "чего не касается ни один агент"},
  rcap: {en: "failures this design creates by itself",
         ru: "отказы, которые схема создаёт сама"},
  bnote: {en: "An autonomous session cannot be stopped mid-run, so it "
              + "is limited by RIGHTS, not by supervision.",
          ru: "Автономную сессию нельзя остановить посреди прогона, "
              + "поэтому ограничивают её ПРАВА, а не надзор."},
  rnote: {en: "Named before building: what is named in advance is "
              + "caught cheaper.",
          ru: "Названы до постройки: то, что названо заранее, ловится "
              + "дешевле."},
  built: {en: "built", ru: "построено"},
  roles: {en: "run by a model", ru: "ведёт модель"},
  next: {en: "next to build", ru: "следующий шаг"},
  pool: {en: "candidates alive", ru: "кандидатов живо"},
  effn: {en: "effective N", ru: "эффективное N"},
  days: {en: "calendar, days", ru: "календарь, суток"},
  reads: {en: "reads", ru: "читает"},
  writes: {en: "writes", ru: "пишет"},
  forbid: {en: "may not", ru: "нельзя"},
  doubt: {en: "at doubt", ru: "при сомнении"},
  waitlim: {en: "waiting out the account limit",
            ru: "ждёт снятия лимита аккаунта"},
  why: {en: "why this step exists", ru: "зачем этот шаг"},
  role: {en: "role", ru: "роль"},
  mech: {en: "mechanical", ru: "механика"},
  yes: {en: "built", ru: "построен"},
  no: {en: "not built", ru: "не построен"},
  what: {en: "what", ru: "что"},
  reason: {en: "why", ru: "почему"},
  fail: {en: "failure", ru: "отказ"},
  guard: {en: "guard", ru: "защита"},
  none: {en: "no daily run yet", ru: "суточного прогона ещё не было"},
  runs: {en: "role runs", ru: "прогонов ролей"},
  lastrun: {en: "last run", ru: "последний прогон"},
  never: {en: "never run", ru: "не запускалась ни разу"},
  hasprompt: {en: "prompt only", ru: "только промпт"},
  live: {en: "running now", ru: "работает сейчас"},
  broke: {en: "run was cut off", ru: "прогон оборван"},
  jrn: {en: "run log", ru: "журнал прогонов"},
  made: {en: "what it produced", ru: "что произвела"},
  nojrn: {en: "no runs recorded yet", ru: "прогонов ещё не было"},
  nomade: {en: "the file is not there", ru: "файла нет"},
  when: {en: "when", ru: "когда"},
  took: {en: "took", ru: "длилось"},
  tap: {en: "tap a step for its log",
        ru: "нажмите на шаг — увидите его журнал"},
  nosched: {en: "There is no schedule yet, so a silent role is not an "
                + "alarm here. It becomes one the moment the runner is "
                + "wired into the watchdog.",
            ru: "Расписания ещё нет, поэтому молчащая роль здесь не "
                + "тревога. Она станет тревогой в тот момент, когда "
                + "запускалку впишут в сторожа."},
  // Расписание есть — значит молчание круга больше не состояние.
  // Тревога называет ШАГИ поимённо: «круг стоит» без имён лечить
  // нечем, а имена и есть первый шаг разбора.
  stale: {en: "the circle is silent", ru: "круг молчит"},
  staleq: {en: "ran, but not since", ru: "отработал, но не позже чем"},
  stalen: {en: "never ran", ru: "не отрабатывал ни разу"},
  // Тишина и повторяющийся ОТКАЗ лечатся по-разному: первая означает
  // «расписание не дошло», второй — «дошло, и вот причина». Пока
  // страница звала это молчанием, живой отказ («CLI не знает такую
  // модель», трое суток подряд у scout и propose) был неотличим от
  // тишины уже на показе.
  stalef: {en: "was called", ru: "звали"},
  stalefn: {en: "times, every one refused", ru: "раза, и каждый — отказ"},
  quiet: {en: "the circle is on schedule and every step of it has run",
          ru: "круг на расписании, и каждый его шаг отработал"},
  scap: {en: "the daily summary for the owner",
         ru: "суточная сводка владельцу"},
  nosum: {en: "no summary yet: the briefer has not produced one",
          ru: "сводки ещё нет: сторож-брифер её не произвёл"},
  sumold: {en: "the summary is", ru: "сводке"},
  sumcut: {en: "shown in part, the rest is in the file",
           ru: "показана не целиком, остальное в файле"}
};
function T(k){ const v = UI[k]; return v[LANG] || v.en; }
function tx(o, f){ return LANG === "ru" ? (o[f + "_ru"] || o[f] || "")
                                        : (o[f] || ""); }
function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
// Прочерк, а не ноль: величины, которой нет, ноль приписывает
// смысл «измерено и равно нулю».
function num(v, d){ return (v === null || v === undefined) ? "&mdash;"
  : (d ? Number(v).toFixed(d) : String(v)); }

// Рамка предмета. Стоит первой и объясняет ИМЕННО то, чем страница
// может быть неверно прочитана: список из десяти шагов с ролями
// читается как «десять работающих программ», а работает сегодня
// меньше половины, и ни одна из них не «живёт» непрерывно.
function frameHtml(d){
  const ru = LANG === "ru";
  const built = d.built_n, total = d.total_n;
  if (ru) return `<p class="frame"><b>Агент здесь — не живая сессия.</b>
    Это рецепт запуска: промпт роли, права, что прочитать, что оставить
    на диске. Сессию будит запускалка, она работает минуты и умирает;
    памяти между вызовами нет вовсе, и роли разговаривают только через
    файлы в репозитории. Поэтому состояние живёт на диске, шаги
    повторяемы без вреда, а упавший прогон обязан кричать.</p>
    <p class="frame"><b>Половина конвейера — не агенты.</b> Шесть шагов
    из десяти механические, и это сделано нарочно: механический шаг
    нельзя уговорить. Отбор публикации, объявление в журнал, вылет и
    счёт знаменателя механические именно потому, что там живёт соблазн,
    который в этом проекте уже стоил месяца работы.</p>`;
  return `<p class="frame"><b>An agent here is not a live session.</b>
    It is a recipe for starting one: the role prompt, its rights, what
    to read, what to leave on disk. A scheduler wakes it, it works for
    minutes and dies; there is no memory between calls, and the roles
    speak to each other only through files in the repository. Hence:
    state lives on disk, every step is repeatable without harm, and a
    run that dies must scream.</p>
    <p class="frame"><b>Half of the conveyor is not agents.</b> Six of
    the ten steps are mechanical on purpose: a mechanical step cannot
    be talked into anything. Publication, declaration, retirement and
    the count of trials are mechanical precisely because that is where
    the temptation lives &mdash; the one that already cost this project
    a month of work.</p>`;
}

function render(){
  const d = DATA;
  document.getElementById("strap").textContent = T("strap");
  navMount("/agents-page");
  langBox();
  if (!d) return;
  document.getElementById("frame").innerHTML = frameHtml(d);

  // Плитки. «Построено N из M» — величина, а не заявление: порядок
  // постройки и следующий шаг выводятся из состояния файлов, поэтому
  // страница не может утверждать прогресс, которого нет.
  const p = d.pool || {};
  const nx = d.steps.filter(s => s.key === d.next_key)[0];
  const cells = [
    [T("built"), `${d.built_n}<small> / ${d.total_n}</small>`],
    [T("roles"), `${d.roles_n}<small> / ${d.total_n}</small>`],
    [T("next"), nx ? esc(tx(nx, "title")) : "&mdash;"],
    [T("runs"), num(d.runs_n)],
    [T("pool"), num(p.alive)],
    [T("effn"), num(p.eff_n, 1)],
    [T("days"), num(p.days)]];
  document.getElementById("strip").innerHTML = cells.map(c =>
    `<div class="st"><div class="lab">${c[0]}</div>
      <div class="val">${c[1]}</div></div>`).join("");

  // Тревоги. Пустая величина обязана объяснять себя: прочерк без
  // причины неотличим от сломанного счёта.
  let al = "";
  if (d.pool_status)
    al += `<p class="warn"><b>&#9888;</b> ${esc(d.pool_status)}</p>`;
  if (p.stale)
    al += `<p class="warn"><b>&#9888;</b> ` + (LANG === "ru"
      ? `суточный прогон не пришёл, артефакту ${
          Math.round(p.run_age_sec / 3600)} ч`
      : `the daily run did not arrive, the artifact is ${
          Math.round(p.run_age_sec / 3600)} h old`) + `</p>`;
  if (p.verdict)
    al += `<p class="warn"><b>&#8226;</b> ${esc(p.verdict)}</p>`;
  // Тревога, кричащая всегда, перестаёт быть сигналом: пока
  // расписания нет, молчание ролей есть состояние, а не отказ.
  if (d.scheduled === false)
    al += `<p class="frame" data-nosched="1">${T("nosched")}</p>`;
  else if ((d.stale_keys || []).length) {
    // Молчание шага круга при работающем расписании — отказ, и он
    // обязан кричать. Возраст последнего УСПЕХА печатается числом:
    // «молчит» без числа неотличимо от «только что запустили».
    const names = (d.stale_keys || []).map(k => {
      const s = (d.steps || []).find(x => x.key === k) || {};
      const a = s.last_ok_age_sec;
      const head = `${esc(tx(s, "title") || k)} — `
        + (a == null ? T("stalen")
           : `${T("staleq")} ${Math.round(a / 3600)} ч`);
      // Отказ называется ПРИЧИНОЙ и числом попыток: «молчит» лечат
      // расписанием, а «CLI не знает модель» — обновлением машины, и
      // без причины владелец начинает не с того.
      return s.fails_row
        ? `${head}; ${T("stalef")} ${s.fails_row} ${T("stalefn")}: ${
            esc(String(s.fail_why || "").slice(0, 160))}`
        : head;
    }).join("; ");
    al += `<p class="alarm" data-stale="1"><b>&#9888;</b> ${
      T("stale")}: ${names}</p>`;
  } else if ((d.circle || []).length)
    al += `<p class="frame" data-quiet="1">${T("quiet")}</p>`;
  document.getElementById("alarm").innerHTML = al;

  document.getElementById("scap").textContent = T("scap");
  // Сводка — это то, ради чего система и заводилась, поэтому она
  // стоит на странице, а не внутри карточки шага: ежедневный отчёт,
  // который надо искать, читают один раз. Отсутствие сводки —
  // НАЗВАННОЕ состояние, а не пустая панель.
  const sm = d.summary;
  document.getElementById("sumry").innerHTML =
    (!sm || sm.error || !(sm.text || "").trim())
      ? `<p class="frame" data-nosum="1">${T("nosum")}</p>`
      : `<p class="k" data-sumage="1">${T("sumold")} ${
          Math.round((sm.age_sec || 0) / 3600)} ч${
          sm.cut ? " \u00b7 " + T("sumcut") : ""}</p>`
        + `<pre class="frame" data-sum="1">${esc(sm.text)}</pre>`;
  document.getElementById("pcap").textContent =
    T("pcap") + " \u00b7 " + T("tap");
  document.getElementById("pipe").innerHTML = d.steps.map((s, i) => {
    const isNext = s.key === d.next_key;
    return `<div class="step ${s.kind === "role" ? "role" : "mech"}${
        isNext ? " next" : ""}" data-step="${esc(s.key)}">
      <div class="shead">
        <span class="num mono">${String(i + 1).padStart(2, "0")}</span>
        <span class="sname">${esc(tx(s, "title"))}</span>
        <span class="chip ${s.kind === "role" ? "role" : ""}">${
          s.kind === "role" ? T("role") : T("mech")}</span>
        <span class="chip">${esc(tx(s, "cadence"))}</span>
        ${s.kind === "role"
          ? `<span class="chip">${esc(s.model)}</span>` : ""}
        <span style="flex:1"></span>
        <span class="chip ${s.built ? "on" : "off"}"
          data-built="${s.built ? 1 : 0}">${
            s.built ? T("yes") : T("no")}</span>
        ${(!s.built && s.prompt) ? `<span class="chip"
          data-prompt="1">${T("hasprompt")}</span>` : ""}
        ${s.running ? `<span class="chip live" data-live="1"><span
          class="dot"></span>${T("live")}</span>` : ""}
        ${s.broken_run ? `<span class="chip off"
          data-broken="1">${T("broke")}</span>` : ""}
        ${s.limit_wait_sec ? `<span class="chip"
          data-limitwait="1" title="${T("waitlim")}">&#9203; ${
            Math.ceil(s.limit_wait_sec / 60)} ${
            LANG === "ru" ? "мин" : "min"}</span>` : ""}
      </div>
      <div class="sbody">${esc(tx(s, "plain"))}</div>
      ${s.kind === "role" ? `<div class="run mono">${T("lastrun")}:
        ${s.last_run
          ? esc(s.last_run.status) + " &middot; "
            + Math.round(s.last_run.age_sec / 60) + " min"
          : T("never")}</div>` : ""}
      <div class="grid">
        <div class="f"><span class="lab">${T("reads")}</span>${
          esc(tx(s, "reads"))}</div>
        <div class="f"><span class="lab">${T("writes")}</span>${
          esc(tx(s, "writes"))}</div>
        <div class="f"><span class="lab">${T("forbid")}</span>${
          esc(tx(s, "forbid"))}</div>
        <div class="f"><span class="lab">${T("doubt")}</span>${
          esc(tx(s, "doubt"))}</div>
      </div>
      <div class="why"><b>${T("why")}:</b> ${esc(tx(s, "why"))}
        <span class="mono dim"> &middot; ${esc(s.proof)}</span></div>
    </div>`;
  }).join("");

  document.querySelectorAll("#pipe .step").forEach(el => {
    el.onclick = () => openStep(el.getAttribute("data-step")); });

  document.getElementById("bcap").textContent = T("bcap");
  document.getElementById("bnote").textContent = T("bnote");
  document.getElementById("bounds").innerHTML =
    `<tr><th>${T("what")}</th><th>${T("reason")}</th></tr>` +
    (d.boundaries || []).map(b =>
      `<tr><td class="name">${esc(tx(b, "what"))}</td>
        <td>${esc(tx(b, "why"))}</td></tr>`).join("");

  document.getElementById("rcap").textContent = T("rcap");
  document.getElementById("rnote").textContent = T("rnote");
  document.getElementById("risks").innerHTML =
    `<tr><th>${T("fail")}</th><th>${T("guard")}</th></tr>` +
    (d.risks || []).map(r =>
      `<tr><td class="name">${esc(tx(r, "title"))}</td>
        <td>${esc(tx(r, "guard"))}</td></tr>`).join("");
}

// Карточка шага: состояние, журнал прогонов и произведённое.
// Просьба владельца: нажав на агента, видеть, когда он отработал в
// последний раз, работает ли сейчас, что сделал и чего не смог.
//
// Состояние и «последний прогон» стоят ПОРОЗНЬ намеренно: склеив их,
// страница показывала бы старый отказ во время исправного прогона.
let OPEN = null;
function fmtAge(sec){
  if (sec == null) return "&mdash;";
  const m = Math.round(sec / 60);
  if (m < 60) return m + " min";
  const h = Math.round(sec / 3600);
  return h < 48 ? h + " h" : Math.round(sec / 86400) + " d";
}
function stepHtml(s){
  let h = `<button class="x" id="sheetx">&times;</button>
    <h3>${esc(tx(s, "title"))}</h3>
    <div class="k">${s.kind === "role" ? T("role") : T("mech")} &middot;
      ${esc(tx(s, "cadence"))}${s.kind === "role"
        ? " &middot; " + esc(s.model) : ""}</div>
    <div class="sbody">${esc(tx(s, "plain"))}</div>`;
  let state;
  if (s.running)
    state = `<b class="good"><span class="dot"></span>${T("live")}</b>
      &middot; ${fmtAge(s.running.age_sec)}`;
  else if (s.broken_run)
    state = `<b class="bad">${T("broke")}</b> &middot;
      ${fmtAge(s.broken_run.age_sec)}`;
  else if (s.last_run)
    state = `${T("lastrun")}: <b>${esc(s.last_run.status)}</b> &middot;
      ${fmtAge(s.last_run.age_sec)}${s.last_run.note
        ? " &middot; " + esc(s.last_run.note) : ""}`;
  else
    state = `<span class="dim">${T("never")}</span>`;
  h += `<div class="run" data-state="1" style="font-size:13px">${state}</div>`;

  // Журнал показывается ЦЕЛИКОМ, включая отказы: тишина запрещена, и
  // показывать только удачное значило бы вернуть её через показ.
  h += `<div class="cap" style="margin-top:12px">${T("jrn")}</div>`;
  if (!s.runs || !s.runs.length) {
    h += `<div class="dim" data-nojrn="1">${T("nojrn")}</div>`;
  } else {
    h += `<div class="scroll"><table data-jrn="1"><tr>
      <th>${T("when")}</th><th>status</th><th>${T("took")}</th>
      <th>${T("reason")}</th></tr>` + s.runs.map(r => `<tr>
      <td class="mono">${fmtAge(r.age_sec)}</td>
      <td class="mono ${r.status === "ok" ? "good"
        : (r.status === "start" ? "" : "bad")}">${esc(r.status)}${
        r.dry ? ' <span class="dim">dry</span>' : ""}</td>
      <td class="mono">${r.took_sec ? r.took_sec + " s" : "&mdash;"}</td>
      <td>${esc(r.note || "")}${r.note_cut ? "&hellip;" : ""}</td>
      </tr>`).join("") + `</table></div>`;
  }

  // Произведённое. Отсутствие файла — состояние, а не пустота:
  // «роль отработала» без её продукта нечем проверить.
  if (s.produced && s.produced.length) {
    h += `<div class="cap" style="margin-top:12px">${T("made")}</div>`;
    h += s.produced.map(f => `<div data-made="1">
      <span class="mono">${esc(f.path)}</span> &middot;
      ${f.exists ? (f.bytes + " B &middot; " + fmtAge(f.age_sec))
                 : `<span class="bad">${T("nomade")}</span>`}
      ${f.head ? `<div class="pre">${esc(f.head)}${
        f.head_cut ? "\n…" : ""}</div>` : ""}</div>`).join("");
  }
  h += `<div class="why" style="margin-top:12px"><b>${T("why")}:</b>
    ${esc(tx(s, "why"))}
    <span class="mono dim"> &middot; ${esc(s.proof)}</span></div>`;
  return h;
}
function openStep(key){
  const s = (DATA && DATA.steps || []).filter(x => x.key === key)[0];
  if (!s) return;
  OPEN = key;
  let v = document.getElementById("veil");
  if (!v) {
    v = document.createElement("div");
    v.id = "veil"; v.className = "veil";
    document.body.appendChild(v);
    v.onclick = (e) => { if (e.target === v) closeStep(); };
  }
  v.innerHTML = `<div class="sheet" id="sheet">${stepHtml(s)}</div>`;
  const x = document.getElementById("sheetx");
  if (x) x.onclick = closeStep;
}
function closeStep(){
  OPEN = null;
  const v = document.getElementById("veil");
  if (!v) return;
  // Гасим содержимое И убираем узел: полагаться на parentNode нельзя —
  // проверка страницы работает на заглушке DOM, где его нет, и
  // «карточка закрылась» проверялась бы там вхолостую.
  v.innerHTML = "";
  if (typeof v.remove === "function") v.remove();
}
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeStep(); });

function setLang(v){
  LANG = v;
  try { localStorage.setItem("algoth_lang", v); } catch (e) {}
  render();
  // Открытая карточка перерисовывается вместе со страницей: половина
  // по-русски и половина по-английски выглядела бы исправной.
  if (OPEN) openStep(OPEN);
}
function langBox(){
  document.getElementById("lang").innerHTML =
    ["en", "ru"].map(v => `<button data-lang="${v}"
      aria-pressed="${String(LANG === v)}">${v.toUpperCase()}</button>`)
      .join(" ");
  document.querySelectorAll("#lang button").forEach(b => {
    b.onclick = () => setLang(b.getAttribute("data-lang")); });
}
// Оба языка приходят ОДНИМ ответом: переключение не ходит на сервер,
// иначе смена языка на потерянной связи гасила бы страницу.
fetch("/agents?k=" + encodeURIComponent(KEY))
  .then(r => r.json()).then(j => { DATA = j; render(); })
  .catch(() => { DATA = null; render();
    document.getElementById("pipe").textContent =
      LANG === "ru" ? "сборщик не ответил" : "no answer from the collector";
  });
render();
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
            if u.path == "/jobs-poke":
                # Звонок в дверь, а не пульт: сигнал НЕ несёт ни
                # команды, ни аргумента — сервер лишь смотрит очередь
                # заданий в git раньше, чем до неё дойдёт сторож.
                # Что выполнять, решает `tools/jobs.sh` белым списком,
                # а задания попадают в очередь коммитом. Поэтому даже
                # утечка ключа страницы не даёт исполнения: она даёт
                # право попросить сервер перечитать наш же git.
                return self._ok(json.dumps(
                    collector.jobs_poke(),
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
                    collector.model_marks(
                        hz=q.get("hz", [None])[0] or None),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/trade_by_id":
                return self._ok(json.dumps(
                    collector.trade_by_id(
                        q.get("tid", [""])[0]),
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
            if u.path == "/glossary":
                return self._ok(json.dumps(
                    collector.model_glossary(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/glossary-page":
                return self._ok(GLOSSARY_PAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/volatility":
                return self._ok(json.dumps(
                    collector.vol_vs_models(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/vol-page":
                return self._ok(VOLPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/learning":
                return self._ok(json.dumps(
                    collector.learning(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/learning-page":
                return self._ok(LEARNPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/paper":
                return self._ok(json.dumps(
                    collector.paper_book(q.get("at", [None])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/dca":
                return self._ok(json.dumps(
                    collector.dca_paper(q.get("dep", [None])[0],
                                        q.get("ruler", [None])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/dca_trades":
                return self._ok(json.dumps(
                    collector.dca_trades(q.get("sym", [""])[0],
                                         q.get("book", [""])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/dca-page":
                return self._ok(DCAPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/paper-page":
                return self._ok(PAPERPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/live_exec":
                return self._ok(json.dumps(
                    collector.live_exec(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/live-page":
                return self._ok(LIVEPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/book_days":
                return self._ok(json.dumps(
                    collector.book_days(q.get("hz", ["h4"])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/book-page":
                return self._ok(BOOKDAYS.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/model_tree":
                return self._ok(json.dumps(
                    collector.model_tree(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/tree-page":
                return self._ok(TREEPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/tournament":
                return self._ok(json.dumps(
                    collector.model_tournament(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/tournament-page":
                return self._ok(TOURPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/asks":
                return self._ok(json.dumps(
                    collector.owner_asks(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/asks-page":
                return self._ok(ASKSPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/agents":
                return self._ok(json.dumps(
                    collector.agents_state(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/agents-page":
                return self._ok(AGENTSPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/factory_built":
                return self._ok(json.dumps(
                    collector.factory_built(),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/built-page":
                return self._ok(BUILTPAGE.encode("utf-8"),
                                "text/html; charset=utf-8")
            if u.path == "/factory_strategy":
                return self._ok(json.dumps(
                    collector.factory_strategy(q.get("id", [""])[0]),
                    ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if u.path == "/strategy-page":
                return self._ok(STRATPAGE.encode("utf-8"),
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
