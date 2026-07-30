#!/usr/bin/env python3
"""
Тесты выгрузки и страниц. Ловят молчаливую пустоту.

Страница, которая ничего не нарисовала, выглядит как «эффекта нет», а не
как ошибка — тот же род дефекта, что зашитый шаг в загрузчике цен и
горизонт короче шага хранилища. Поэтому здесь проверяется, что в
готовом файле есть данные, что подстановки заменены, и главное — что
**сжатие свечей не меняет чисел**: приращения обязаны разворачиваться в
те же цены, иначе это другой график, а не тот же поменьше.

    python3 research/t3_brackets/test_render.py
"""

import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t1_tape"))
sys.path.insert(0, HERE)

import brackets as B  # noqa: E402

FAILED = []
OUT = os.path.join(HERE, "out")


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def test_minute_bars():
    """Минутные свечи из секундной сетки: края берутся по сделкам."""
    n = 180
    t0 = 1_700_000_000
    g = {"t": t0 + np.arange(86_400, dtype=np.float64), "step_sec": 1,
         "open": np.full(86_400, np.nan), "high": np.full(86_400, np.nan),
         "low": np.full(86_400, np.nan), "close": np.full(86_400, np.nan)}
    # Первая минута: три сделки на 10, 12, 11 секундах.
    for s, (o, h, l, c) in {10: (100.0, 101.0, 100.0, 101.0),
                            12: (101.0, 103.0, 99.0, 99.5),
                            40: (99.5, 99.9, 99.4, 99.8)}.items():
        g["open"][s], g["high"][s] = o, h
        g["low"][s], g["close"][s] = l, c
    # Вторая минута пустая, третья — одна сделка.
    g["open"][130] = g["high"][130] = g["low"][130] = g["close"][130] = 105.0
    bars = B.minute_bars(g, t0)
    check("минута со сделками есть", t0 in bars, str(sorted(bars)[:3]))
    o, h, l, c = bars[t0]
    check("открытие — первая сделка минуты", abs(o - 100.0) < 1e-9, str(o))
    check("максимум и минимум по всей минуте",
          abs(h - 103.0) < 1e-9 and abs(l - 99.0) < 1e-9, f"{h} {l}")
    check("закрытие — последняя сделка минуты", abs(c - 99.8) < 1e-9, str(c))
    check("пустая минута отсутствует, а не равна нулю",
          (t0 + 60) not in bars, str(sorted(bars)))
    check("третья минута на месте", (t0 + 120) in bars, str(sorted(bars)))


def test_tick_is_measured():
    check("шаг цены — наименьшее различие",
          abs(B.tick_of([1.0, 1.25, 1.5, 2.0]) - 0.25) < 1e-12,
          str(B.tick_of([1.0, 1.25, 1.5, 2.0])))
    check("на одной цене шаг не рушит счёт", B.tick_of([5.0, 5.0]) > 0,
          str(B.tick_of([5.0, 5.0])))


def encode_decode(bars):
    """То же преобразование, что в выгрузке, и обратно."""
    ts = sorted(bars)
    vals = [v for t in ts for v in bars[t]]
    step = B.tick_of(vals)
    base = min(vals)
    c = [int(round((bars[t][3] - base) / step)) for t in ts]
    dc, prev = [], 0
    for v in c:
        dc.append(v - prev)
        prev = v
    o = [int(round((bars[t][0] - bars[t][3]) / step)) for t in ts]
    h = [int(round((bars[t][1] - bars[t][3]) / step)) for t in ts]
    lo = [int(round((bars[t][2] - bars[t][3]) / step)) for t in ts]
    dt = [(ts[i] - ts[i - 1]) // 60 for i in range(1, len(ts))]
    # Разворот — ровно как на странице.
    out, acc, tt = {}, 0, ts[0]
    for i in range(len(dc)):
        acc += dc[i]
        if i:
            tt += dt[i - 1] * 60
        cc = base + acc * step
        out[tt] = (cc + o[i] * step, cc + h[i] * step,
                   cc + lo[i] * step, cc)
    return out


def test_encoding_round_trip():
    """Сжатие, меняющее числа, есть другой график, а не тот же поменьше."""
    rng = np.random.default_rng(4)
    t0, tick = 1_700_000_000, 0.0001
    bars, p = {}, 0.3400
    for k in range(500):
        if k % 37 == 5:
            continue                      # дыра в ряде — минуты нет
        p = round(p + rng.integers(-15, 16) * tick, 8)
        o = p
        c = round(p + rng.integers(-8, 9) * tick, 8)
        h = round(max(o, c) + rng.integers(0, 6) * tick, 8)
        lo = round(min(o, c) - rng.integers(0, 6) * tick, 8)
        bars[t0 + k * 60] = (o, h, lo, c)
        p = c
    back = encode_decode(bars)
    check("число свечей сохранилось", len(back) == len(bars),
          f"{len(back)} против {len(bars)}")
    worst = 0.0
    for t, (o, h, lo, c) in bars.items():
        b = back.get(t)
        if b is None:
            check("метка времени сохранилась", False, str(t))
            return
        worst = max(worst, max(abs(b[0] - o), abs(b[1] - h),
                               abs(b[2] - lo), abs(b[3] - c)))
    check(f"цены совпали до {worst:.2e}", worst < 1e-9, f"{worst}")


def render_if_possible(script, tag):
    src = os.path.join(OUT, ("backtest" if "chart" in script else "events")
                       + tag + ".json")
    if not os.path.exists(src):
        print(f"  — {script} пропущен: нет {os.path.basename(src)}")
        return None
    r = subprocess.run([sys.executable, os.path.join(HERE, script),
                        f"--tag={tag}"], capture_output=True, text=True)
    if r.returncode != 0:
        check(f"{script} отработал", False, r.stderr.strip()[-300:])
        return None
    name = ("T3-chart" if "chart" in script else "T3-events") + tag + ".html"
    return os.path.join(OUT, name)


def test_pages_have_data():
    for script, tag in (("chart.py", "-smoke"), ("render.py", "-smoke")):
        path = render_if_possible(script, tag)
        if path is None:
            continue
        html = open(path, encoding="utf-8").read()
        check(f"{script}: подстановки заменены", "__" + "DATA__" not in html
              and "__" + "SUB__" not in html and "__" + "LEDE__" not in html)
        a = html.find('<script id="data"')
        b = html.find("</script>", a)
        blob = html[html.find(">", a) + 1:b]
        try:
            data = json.loads(blob)
        except Exception as e:                            # noqa: BLE001
            check(f"{script}: данные разбираются", False, str(e))
            continue
        n = len(data["trades"]) if isinstance(data, dict) else len(data)
        check(f"{script}: данные на месте ({n} записей)", n > 0)
        check(f"{script}: страница без внешних загрузок",
              "http://" not in html and "https://" not in html,
              "нашлась внешняя ссылка")


def main():
    print("минутные свечи")
    test_minute_bars()
    test_tick_is_measured()
    print("сжатие свечей")
    test_encoding_round_trip()
    print("страницы")
    test_pages_have_data()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
