#!/usr/bin/env python3
"""
Страница просмотра событий: кластер, уровень, сделка, путь цены.

Зачем она нужна и почему это не украшение
-----------------------------------------

Числа отвечают на вопрос «зарабатывает ли», но не отвечают на вопрос
**«то ли это вообще, что имелось в виду»**. Детектор может аккуратно
измерять не тот объект, и в статистике это выглядит как честный ноль.
Единственный способ проверить — посмотреть глазами на два десятка
событий и сказать: накопление это или шум.

Отсюда и границы. Один файл, без библиотек и без настроек внешнего
вида: v1 умер отчасти на четырёх тысячах строк кастомизации графика.
Как только страница покажет ситуацию, работа по ней прекращается.

Что рисуется
------------

По каждому событию: кластер (цена × секунды, цвет — сторона агрессии,
плотность — объём), горизонтали уровня, входа, стопа и цели, путь цены
после входа и строка журнала — какие именно условия сработали и чем
кончилась сделка.

    python3 research/t3_brackets/render.py
    python3 research/t3_brackets/render.py --tag -smoke
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def sparse(rows):
    """Плотную матрицу в разреженную: нулей в кластере большинство."""
    out = []
    for b, row in enumerate(rows):
        for s, v in enumerate(row):
            if v:
                out.append([b, s, int(v)])
    return out


def prepare(ev):
    """Событие в вид, удобный для отрисовки, без лишних чисел."""
    path = [[p[0], p[1]] for p in ev["path"] if p[1] is not None]
    ys = [ev["price_lo"], ev["price_hi"], ev["stop"], ev["target"],
          ev["entry"], ev["level"]] + [p[1] for p in path]
    return {
        "sym": ev["symbol"], "time": ev["time"][:19].replace("T", " "),
        "side": ev["side"], "win": ev["window_sec"], "mult": ev["vol_mult"],
        "conc": ev["conc"], "rr": round(ev["rr"], 2),
        "outcome": ev["outcome"], "held": ev["held"],
        "net": round(ev["net_bp"], 1),
        "t0": ev["t_from"], "lo": ev["price_lo"], "hi": ev["price_hi"],
        "nb": ev["bands"], "ns": len(ev["buy"][0]),
        "level": ev["level"], "entry": ev["entry"],
        "stop": ev["stop"], "target": ev["target"],
        "ymin": min(ys), "ymax": max(ys),
        "buy": sparse(ev["buy"]), "sell": sparse(ev["sell"]),
        "path": path,
    }


HTML = """<title>Лента: события набора на уровне</title>
<style>
:root {
  color-scheme: light dark;
  --ground: #f6f7f9; --panel: #ffffff; --ink: #141a21; --muted: #5c6673;
  --rule: #dfe4ea; --buy: #1f7a56; --sell: #b8452c; --accent: #a97514;
  --grid: #eef1f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ground: #0c1015; --panel: #131922; --ink: #e4e9f0; --muted: #8b95a4;
    --rule: #212936; --buy: #35a877; --sell: #d4614a; --accent: #d7a24a;
    --grid: #1a212c;
  }
}
:root[data-theme="dark"] {
  --ground: #0c1015; --panel: #131922; --ink: #e4e9f0; --muted: #8b95a4;
  --rule: #212936; --buy: #35a877; --sell: #d4614a; --accent: #d7a24a;
  --grid: #1a212c;
}
:root[data-theme="light"] {
  --ground: #f6f7f9; --panel: #ffffff; --ink: #141a21; --muted: #5c6673;
  --rule: #dfe4ea; --buy: #1f7a56; --sell: #b8452c; --accent: #a97514;
  --grid: #eef1f5;
}
body {
  margin: 0; background: var(--ground); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 940px; margin: 0 auto; padding: 28px 16px 64px; }
h1 { font-size: 22px; line-height: 1.25; margin: 0 0 6px; text-wrap: balance; }
.lede { color: var(--muted); max-width: 62ch; margin: 0 0 4px; }
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
}
.eyebrow {
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted);
}
.ask {
  margin: 20px 0 26px; padding: 14px 16px; background: var(--panel);
  border: 1px solid var(--rule); border-left: 3px solid var(--accent);
}
.ask p { margin: 0 0 8px; }
.ask p:last-child { margin-bottom: 0; }
.card {
  background: var(--panel); border: 1px solid var(--rule);
  margin: 0 0 22px; padding: 14px 14px 10px;
}
.head { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: baseline; }
.head .sym { font-size: 17px; font-weight: 650; }
.head .side { color: var(--muted); }
.chartbox { overflow-x: auto; margin: 10px 0 6px; }
canvas { display: block; width: 100%; height: auto; }
.log {
  font-size: 12.5px; color: var(--muted); display: flex; flex-wrap: wrap;
  gap: 4px 16px; padding-top: 6px; border-top: 1px solid var(--rule);
}
.log b { color: var(--ink); font-weight: 600; }
.tag { padding: 1px 7px; border: 1px solid var(--rule); font-size: 12px; }
.win { color: var(--buy); border-color: currentColor; }
.loss { color: var(--sell); border-color: currentColor; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 12px;
          color: var(--muted); margin: 14px 0 22px; }
.sw { display: inline-block; width: 22px; height: 9px; vertical-align: 0px;
      margin-right: 6px; }
footer { color: var(--muted); font-size: 13px; border-top: 1px solid var(--rule);
         padding-top: 14px; margin-top: 10px; }
</style>

<div class="wrap">
<p class="eyebrow">Замер сделки T3 · направление потока заявок</p>
<h1>Набор на уровне: как это выглядит в ленте</h1>
<p class="lede">__LEDE__</p>

<div class="ask">
<p><b>Вопрос ровно один:</b> это накопление — или детектор поймал шум?
Числа на него не отвечают. Он может аккуратно измерять не тот объект, и
в статистике это выглядит как честный ноль.</p>
<p>Смотреть стоит на две вещи. <b>Собран ли объём на одной цене</b> —
столбцы кластера должны утыкаться в одну горизонталь, а не быть
размазаны по всему ходу. И <b>держится ли цена</b> у этой горизонтали,
пока в неё льют.</p>
</div>

<div class="legend">
<span><span class="sw" style="background:var(--buy)"></span>агрессивные покупки</span>
<span><span class="sw" style="background:var(--sell)"></span>агрессивные продажи</span>
<span><span class="sw" style="background:var(--accent)"></span>уровень набора</span>
<span><span class="sw" style="background:var(--ink);opacity:.55"></span>вход · стоп · цель</span>
<span>плотность цвета — объём в ячейке</span>
</div>

<div id="list"></div>

<footer>
Данные — лента Bybit, секундная сетка. Вход по первой доступной цене
после закрытия окна; исполнение лимитной заявкой не предполагается.
Ничья «стоп и цель в одну секунду» засчитана стопом.
</footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const EV = JSON.parse(document.getElementById("data").textContent);
const css = k => getComputedStyle(document.documentElement)
  .getPropertyValue(k).trim();

function draw(cv, e) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = cv.clientWidth, H = Math.round(W * 0.52);
  cv.width = W * dpr; cv.height = H * dpr;
  cv.style.height = H + "px";
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);

  const padL = 8, padR = 62, padT = 8, padB = 16;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  // Кластер занимает левые две трети, путь после входа — правую треть.
  const clW = Math.round(plotW * 0.66);
  const y = v => padT + plotH * (e.ymax - v) / Math.max(e.ymax - e.ymin, 1e-12);
  const band = (e.hi - e.lo) / e.nb;
  const cw = clW / e.ns, ch = Math.max(plotH * band /
      Math.max(e.ymax - e.ymin, 1e-12), 1);

  g.strokeStyle = css("--grid"); g.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const yy = padT + plotH * i / 4;
    g.beginPath(); g.moveTo(padL, yy); g.lineTo(W - padR, yy); g.stroke();
  }

  let max = 1;
  for (const [, , v] of e.buy) if (v > max) max = v;
  for (const [, , v] of e.sell) if (v > max) max = v;
  const cell = (arr, color) => {
    for (const [b, s, v] of arr) {
      const px = e.lo + (b + 0.5) * band;
      g.globalAlpha = 0.18 + 0.82 * Math.min(1, Math.sqrt(v / max));
      g.fillStyle = color;
      g.fillRect(padL + s * cw, y(px) - ch / 2, Math.max(cw, 1), ch);
    }
    g.globalAlpha = 1;
  };
  cell(e.sell, css("--sell"));
  cell(e.buy, css("--buy"));

  // Путь цены после входа — правая треть, та же ось цены.
  if (e.path.length > 1) {
    const t0 = e.path[0][0], t1 = e.path[e.path.length - 1][0];
    const px = t => padL + clW + (plotW - clW) *
      (t - t0) / Math.max(t1 - t0, 1);
    g.strokeStyle = css("--ink"); g.globalAlpha = .75; g.lineWidth = 1.5;
    g.beginPath();
    e.path.forEach(([t, p], i) => i ? g.lineTo(px(t), y(p))
                                    : g.moveTo(px(t), y(p)));
    g.stroke(); g.globalAlpha = 1;
  }
  g.strokeStyle = css("--rule");
  g.beginPath(); g.moveTo(padL + clW, padT);
  g.lineTo(padL + clW, padT + plotH); g.stroke();

  const line = (v, color, label, dash) => {
    if (!isFinite(v)) return;
    g.save();
    g.strokeStyle = color; g.setLineDash(dash); g.lineWidth = 1.25;
    g.beginPath(); g.moveTo(padL, y(v)); g.lineTo(W - padR, y(v)); g.stroke();
    g.restore();
    g.fillStyle = color;
    g.font = "11px ui-monospace, Menlo, monospace";
    g.textBaseline = "middle";
    g.fillText(label, W - padR + 5, y(v));
  };
  const ink = css("--ink");
  line(e.level, css("--accent"), "уровень", []);
  line(e.entry, ink, "вход", [4, 3]);
  line(e.stop, css("--sell"), "стоп", [2, 3]);
  line(e.target, css("--buy"), "цель", [2, 3]);
}

const list = document.getElementById("list");
EV.forEach((e, i) => {
  const el = document.createElement("div");
  el.className = "card";
  const dir = e.side < 0 ? "набор под ценой · лонг"
                         : "разгрузка над ценой · шорт";
  const good = e.net > 0;
  el.innerHTML = `
    <div class="head">
      <span class="sym mono">${e.sym}</span>
      <span class="mono" style="color:var(--muted)">${e.time} UTC</span>
      <span class="side">${dir}</span>
      <span class="tag mono ${good ? "win" : "loss"}">${e.outcome} ·
        ${e.net > 0 ? "+" : ""}${e.net} б.п.</span>
    </div>
    <div class="chartbox"><canvas></canvas></div>
    <div class="log mono">
      <span>окно <b>${e.win} с</b></span>
      <span>объём <b>×${e.mult}</b></span>
      <span>сосредоточенность <b>${e.conc}</b></span>
      <span>уровень <b>${e.level}</b></span>
      <span>вход <b>${e.entry}</b></span>
      <span>стоп <b>${e.stop}</b></span>
      <span>цель <b>${e.target}</b></span>
      <span>отношение <b>1 : ${e.rr}</b></span>
      <span>держали <b>${e.held} с</b></span>
    </div>`;
  list.appendChild(el);
  const cv = el.querySelector("canvas");
  requestAnimationFrame(() => draw(cv, e));
  window.addEventListener("resize", () => draw(cv, e));
});

const mo = new MutationObserver(() => EV.forEach((e, i) =>
  draw(document.querySelectorAll("canvas")[i], e)));
mo.observe(document.documentElement, { attributes: true,
  attributeFilter: ["data-theme"] });
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    src = os.path.join(OUT, f"events{a.tag}.json")
    with open(src, encoding="utf-8") as f:
        raw = json.load(f)
    events = [prepare(e) for e in raw["events"] if e]
    cfg = raw["config"]
    lede = (f"{len(events)} событий из ленты Bybit, "
            f"{cfg['start']} … {cfg['end']}. Отобраны детектором: "
            f"агрессия выше обычной в {min(cfg['vol_mults']):g}–"
            f"{max(cfg['vol_mults']):g} раз, перевес стороны "
            f"≥ {cfg['imb']:g}, цена стоит, и не меньше "
            f"{min(cfg['concs']):g} объёма — в одной ценовой полосе.")
    html = HTML.replace("__DATA__", json.dumps(events, ensure_ascii=False))
    html = html.replace("__LEDE__", lede)
    dst = os.path.join(OUT, f"T3-events{a.tag}.html")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{dst}: {len(events)} событий, {os.path.getsize(dst) // 1024} КиБ")


if __name__ == "__main__":
    main()
