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
.syms{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px}
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
    <div class="cap"><span>середина, уровни и сделки</span>
      <span id="cap-mid" class="mono"></span></div>
    <canvas id="mid" height="190"></canvas>
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

async function tick() {
  let d;
  try {
    const r = await fetch(`/state?k=${encodeURIComponent(KEY)}`
      + (sym ? `&sym=${sym}` : ""));
    if (!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
  } catch (e) {
    document.getElementById("sub").textContent = "нет связи со сборщиком: " + e;
    return;
  }
  sym = d.sym;
  render(d);
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
    cell("тишина, с", fmt(age, 1), age > 5 ? "bad" : "good");

  document.getElementById("syms").innerHTML = d.symbols.map(x =>
    `<button data-s="${x}" aria-pressed="${x === d.sym}">${
      x.replace("USDT","")}</button>`).join("");
  document.querySelectorAll("[data-s]").forEach(b =>
    b.onclick = () => { sym = b.dataset.s; tick(); });

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
      `обновлений/с ${bk.upd}`;
    document.getElementById("bands").innerHTML = d.bands.map(b => {
      const tot = b.bid + b.ask || 1;
      return `<div class="band"><span class="n mono">±${b.w}%</span>
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

  const sg = d.sig || {levels:[], open:[], done:[]};
  drawMid(d.mid || [], sg);
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
        <td class="mono ${x.pnl_bp>0?"buy":"sell"}">${
          x.pnl_bp>0?"+":""}${x.pnl_bp} б.п. · ${x.r>0?"+":""}${x.r} R</td>
      </tr>`).join("")
    : `<tr><td style="color:var(--muted);padding:8px 10px">событий пока нет</td></tr>`;
  const lg = document.getElementById("log");
  lg.textContent = (d.log || []).join("\n");
}

function drawMid(pts, sg) {
  const cv = document.getElementById("mid");
  const dpr = Math.min(devicePixelRatio||1, 2), W = cv.clientWidth, H = 190;
  cv.width = W*dpr; cv.height = H*dpr; cv.style.height = H+"px";
  const g = cv.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,W,H);
  if (pts.length < 2) return;
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
  g.beginPath(); pts.forEach((p,i)=> i?g.lineTo(x(i),y(p[1])):g.moveTo(x(i),y(p[1])));
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
            if token and q.get("k", [""])[0] != token:
                return self._deny()
            if u.path == "/state":
                body = json.dumps(collector.snapshot(q.get("sym", [None])[0]),
                                  ensure_ascii=False).encode("utf-8")
                return self._ok(body, "application/json; charset=utf-8")
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
