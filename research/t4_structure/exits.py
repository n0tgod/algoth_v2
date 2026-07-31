#!/usr/bin/env python3
"""
Потолок геометрии: сколько вообще способны дать стоп и цель.

Откуда вопрос
-------------

Владелец предложил считать стоп и цель по стакану, возможно динамически:
настроение меняется в моменте, и цель, назначенная на входе, позже уже не
та. Предложение попадает в единственное место, которого стенд не
проверял, — стакан в архивах не лежит вовсе.

Но прежде чем строить правило, считается потолок. Приём тот же, которым
S1 закрыл сразу три рычага против сквиза, а T1 — секундные горизонты:
**сначала самая дешёвая оценка, способная убить направление.** Если даже
идеальный выход с полным знанием будущего не выводит в плюс, то ни
стакан, ни динамика не выведут тем более — они могут лишь приблизиться к
потолку снизу.

Что считается
-------------

По каждой записанной сделке T4 (тот же символ, момент и сторона)
восстанавливается ход цены на всё окно удержания, и из него:

* **потолок A — идеальный динамический выход.** Сделка выходит по лучшей
  цене внутри окна. Это верхняя граница ЛЮБОГО правила выхода, какое
  вообще можно придумать, включая любую динамику по стакану;
* **потолок B — идеальный стоп при неизменной цели.** Сделка, которая
  дошла до цели, стоп не трогает вовсе; сделка, которая не дошла,
  закрывается сразу. Это ровно то, что просят от стакана: угадать, какой
  стоп переживёт шум;
* **потолок C — лучшая ПОСТОЯННАЯ пара (стоп, цель),** подобранная по
  известным исходам. Отвечает на другой вопрос: много ли теряется на том,
  что геометрия выбрана неудачно, а не на том, что её надо угадывать;
* **диагностика к наблюдению владельца на FIL:** сколько сделок,
  закрытых стопом, дошли бы до своей цели, будь стоп шире.

Оговорка, которую нельзя терять
-------------------------------

Ход цены берётся минутными барами Binance, а сделки прогонялись по ленте
Bybit посекундно. Внутри минуты порядок касаний неразличим, и ничья
решается ПРОТИВ нас — как в T3/T4. Согласие с записанным исходом
докладывается числом: если оно низкое, потолок описывает не ту сделку, и
верить ему нельзя.

    python3 research/t4_structure/exits.py
"""

import argparse
import json
import math
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "bars")
MAX_HOLD_SEC = 4 * 3600          # как в run.py
COST_BP = 11.0                   # круг тейкером, как в ячейке прогона


def day_ohlc(symbol, day):
    """Минутные бары суток: `{метка: (open, high, low, close)}`.

    Файлы качает `trend.py`; здесь только чтение уже лежащего кэша,
    чтобы замер не зависел от сети.
    """
    path = os.path.join(CACHE, symbol, f"{day}.zip")
    if not os.path.exists(path):
        return {}
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read(z.namelist()[0]).decode()
    except Exception:                                     # noqa: BLE001
        return {}
    out = {}
    for line in raw.splitlines():
        p = line.split(",")
        if len(p) < 5 or not p[0].isdigit():
            continue
        t = int(p[0])
        t = t // 1000 if t > 1e12 else t
        out[int(t)] = (float(p[1]), float(p[2]), float(p[3]), float(p[4]))
    return out


def load_bars(syms, days):
    bars = {}
    for s in sorted(syms):
        b = {}
        for d in days:
            b.update(day_ohlc(s, d))
        bars[s] = b
    return bars


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = []
    for t in d.get("trades") or []:
        ts = datetime.fromisoformat(t["t"])
        entry = float(t["entry"])
        rows.append({
            "sym": t["sym"], "t": int(ts.timestamp()),
            # Направление позиции: side — сторона поглощающего.
            "pos": -int(t["side"]), "entry": entry,
            "stop": float(t["stop"]), "target": float(t["target"]),
            "outcome": t["outcome"], "net": float(t["net"]),
            "stop_bp": abs(entry - float(t["stop"])) / entry * 1e4,
            "tgt_bp": abs(float(t["target"]) - entry) / entry * 1e4,
        })
    return d.get("cell", {}), rows


def walk(bars, r):
    """Пройти окно удержания и снять всё, что нужно всем потолкам.

    Возвращает по сделке: лучший и худший ход в б.п. (в единицах
    направления позиции), исход при записанной геометрии, и — для
    диагностики — дошла ли цена до цели ХОТЬ КОГДА-ТО внутри окна.
    """
    t0 = (r["t"] // 60 + 1) * 60          # первый бар, начавшийся ПОСЛЕ входа
    e, p = r["entry"], r["pos"]
    up = (r["target"] - e) / e * 1e4 * p    # цель всегда > 0 в этих единицах
    dn = (r["stop"] - e) / e * 1e4 * p      # стоп всегда < 0
    # Путь хранится целиком, а не двумя крайностями. Иначе потолок C
    # (другие множители стопа и цели) не может сказать, что задето
    # ПЕРВЫМ, и приходится решать всё против себя — то есть занижать
    # потолок систематически. Ускорение, меняющее числа, есть другая
    # мера; здесь путь стоит 240 пар на сделку и ничего не стоит.
    path = []
    last = 0.0
    for k in range(t0, t0 + MAX_HOLD_SEC, 60):
        b = bars.get(k)
        if not b:
            continue
        _o, h, lo, c = b
        # Ход в нашу пользу и против — в единицах направления позиции.
        hi_bp = (h - e) / e * 1e4 * p
        lo_bp = (lo - e) / e * 1e4 * p
        if p < 0:                          # в шорте максимум цены — худший ход
            hi_bp, lo_bp = lo_bp, hi_bp
        path.append((hi_bp, lo_bp))
        last = (c - e) / e * 1e4 * p
    if not path:
        return None
    best = max(h for h, _l in path)
    worst = min(l for _h, l in path)
    # Просадка ДО цели, а не по всему окну. Сделка, взявшая цель на
    # пятой минуте, из окна уже вышла, и провал через час к ней
    # отношения не имеет. Считать по всему окну значило бы объявлять
    # выигравшие сделки непережившими — первая версия замера так и
    # делала, и потолок с ограничением выходил ниже фактического.
    worst_pre, run = None, 0.0
    for hi_bp, lo_bp in path:
        run = min(run, lo_bp)
        if hi_bp >= up:
            worst_pre = run
            break
    hit = bracket(path, dn, up, last)
    return {"best": max(0.0, best), "worst": worst, "hit": hit[0],
            "gross": hit[1], "target_ever": best >= up, "bars": len(path),
            "worst_pre": worst_pre, "up": up, "dn": dn,
            "path": path, "last": last}


def bracket(path, dn, up, last):
    """Что задето первым при данной геометрии: стоп, цель или время.

    Ничья внутри бара решается ПРОТИВ нас — минутный бар не разрешает
    порядок касаний, и то же правило стоит в T3/T4.
    """
    for hi_bp, lo_bp in path:
        if lo_bp <= dn:
            return "стоп", dn
        if hi_bp >= up:
            return "цель", up
    return "время", last


def stat(vals):
    n = len(vals)
    if not n:
        return 0.0, 0.0
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / max(1, n - 1)
    return m, math.sqrt(var / n)


def grid_cell(walks, s_mult, t_mult):
    """Исход при стопе и цели, умноженных на заданные множители."""
    out = []
    for w in walks:
        _why, g = bracket(w["path"], w["dn"] * s_mult, w["up"] * t_mult,
                          w["last"])
        out.append(g - COST_BP)
    return stat(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(OUT, "backtest.json"))
    a = ap.parse_args()

    cell, rows = load(a.file)
    syms = sorted({r["sym"] for r in rows})
    lo = min(r["t"] for r in rows)
    hi = max(r["t"] for r in rows) + MAX_HOLD_SEC
    d0 = datetime.fromtimestamp(lo, timezone.utc).date()
    d1 = datetime.fromtimestamp(hi, timezone.utc).date()
    days = [(d0 + timedelta(days=i)).isoformat()
            for i in range((d1 - d0).days + 1)]
    bars = load_bars(syms, days)
    missing = [s for s in syms if not bars[s]]
    if missing:
        print(f"нет баров: {', '.join(missing)} — сначала trend.py",
              file=sys.stderr)

    walks, skipped = [], 0
    for r in rows:
        w = walk(bars.get(r["sym"], {}), r)
        if w is None:
            skipped += 1
            continue
        w["row"] = r
        walks.append(w)

    print(f"выгрузка: {a.file}")
    print(f"ячейка: {cell.get('start')}…{cell.get('end')}, издержки "
          f"{COST_BP} б.п., удержание {MAX_HOLD_SEC // 3600} ч")
    print(f"сделок {len(rows)}, восстановлено {len(walks)}, "
          f"без баров {skipped}\n")

    # СВЕРКА. Потолок считается по минутным барам Binance, а прогон шёл
    # по ленте Bybit посекундно. Если исходы расходятся сильно, замер
    # описывает не ту сделку, и всё остальное читать нельзя.
    same = sum(1 for w in walks if w["hit"] == w["row"]["outcome"])
    rec, _ = stat([w["row"]["net"] for w in walks])
    rep, _ = stat([w["gross"] - COST_BP for w in walks])
    print(f"СВЕРКА с прогоном: исход совпал у {same}/{len(walks)} "
          f"({same / max(1, len(walks)):.0%})")
    print(f"  ожидание записанное {rec:+.2f} б.п., "
          f"воспроизведённое {rep:+.2f} б.п.\n")

    # Потолок A — идеальный выход. Верхняя граница любого правила.
    a_vals = [max(0.0, w["best"]) - COST_BP for w in walks]
    ma, sa = stat(a_vals)
    # Потолок B — идеальный стоп при неизменной цели: дошедшие до цели
    # берут цель, недошедшие закрываются сразу (в ноль минус издержки).
    b_vals = [(w["up"] if w["target_ever"] else 0.0) - COST_BP for w in walks]
    mb, sb = stat(b_vals)

    print(f"{'потолок':44} {'ожидание':>16}")
    print(f"{'как есть (записано прогоном)':44} {rec:>+11.2f} б.п.")
    print(f"{'B — идеальный стоп, цель прежняя':44} "
          f"{mb:>+11.2f} б.п. ±{sb:.2f}")
    print(f"{'A — идеальный выход (предел всего)':44} "
          f"{ma:>+11.2f} б.п. ±{sa:.2f}")

    reach = sum(1 for w in walks if w["target_ever"])
    stopped = [w for w in walks if w["row"]["outcome"] == "стоп"]
    saved = sum(1 for w in stopped if w["target_ever"])
    print(f"\nдошли бы до цели хоть когда-то в окне: {reach}/{len(walks)} "
          f"({reach / max(1, len(walks)):.0%})")
    print(f"из закрытых стопом дошли бы до цели позже: {saved}/"
          f"{len(stopped)} ({saved / max(1, len(stopped)):.0%}) "
          f"— это наблюдение владельца на FIL, числом")

    med = sorted(w["worst_pre"] for w in walks if w["target_ever"])
    if med:
        print(f"просадка ДО цели у дошедших: медиана {med[len(med)//2]:.0f}"
              f", 10-й процентиль {med[len(med)//10]:.0f} б.п. "
              f"при стопе {sorted(r['stop_bp'] for r in rows)[len(rows)//2]:.0f}")

    # Мост между B и C. Потолок B даёт +48, но разрешает сделке сидеть
    # в просадке 400 б.п. при стопе 20 — это не «лучший стоп», это
    # совсем другой размер риска. Честный вопрос: сколько остаётся от
    # потолка, если оракулу ЗАПРЕТИТЬ уходить дальше заданной границы.
    # Ниже границы оракул всеведущ, выше — обычный стоп.
    print("\nB с ограничением: оракул знает исход, но не вправе терпеть "
          "больше предела")
    print(f"    {'предел':>10} {'ожидание':>14} {'выжило целей':>15}")
    for cap_mult in (1, 2, 4, 8, 16, 32, 1000):
        vals, kept = [], 0
        for w in walks:
            cap = w["dn"] * cap_mult          # dn отрицателен
            if w["target_ever"] and w["worst_pre"] > cap:
                vals.append(w["up"] - COST_BP)     # пережила, взяла цель
                kept += 1
            elif w["worst"] <= cap:
                vals.append(cap - COST_BP)         # выбило пределом
            else:
                vals.append(0.0 - COST_BP)         # оракул закрыл сразу
        m, se = stat(vals)
        lab = "без предела" if cap_mult == 1000 else f"×{cap_mult} стопа"
        print(f"    {lab:>10} {m:>+9.2f} ±{se:<4.2f} "
              f"{kept:>8}/{reach}")

    # Потолок C — лучшая ПОСТОЯННАЯ пара множителей, подобранная задним
    # числом. Отвечает не «можно ли угадать», а «много ли теряется на
    # неудачно выбранной геометрии вообще».
    print("\nC — лучшая постоянная пара (множители к записанной геометрии),"
          "\n    порог подобран ПО ИЗВЕСТНЫМ ИСХОДАМ:")
    print(f"    {'стоп ×':>8} {'цель ×':>8} {'ожидание':>14}")
    best = None
    for sm in (0.5, 1.0, 2.0, 4.0, 8.0):
        line = []
        for tm in (0.25, 0.5, 1.0, 2.0):
            m, _se = grid_cell(walks, sm, tm)
            line.append(m)
            if best is None or m > best[0]:
                best = (m, sm, tm)
        print(f"    {sm:>8.1f} " + " ".join(f"{v:>+8.2f}" for v in line)
              + "   (цель ×0.25/0.5/1/2)")
    if best:
        print(f"    лучшая: стоп ×{best[1]}, цель ×{best[2]} → "
              f"{best[0]:+.2f} б.п.")

    print("\nВсе три потолка подобраны ПО ИЗВЕСТНЫМ ИСХОДАМ. Это верхние\n"
          "границы, а не результаты: правило по стакану может к ним\n"
          "приблизиться снизу и не может их превысить.")


if __name__ == "__main__":
    main()
