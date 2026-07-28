#!/usr/bin/env python3
"""
A4 — прогон теста на коинтеграцию по сетке окон walk-forward.

Спека 02: §3.2 (Энгл–Грейнджер только на окне отбора), §3.3 (поправка на
множественность и обязательный артефакт «до и после»), §3.4 (отбраковка
по полураспаду), §6 (протокол окон).

Что здесь решается и чего здесь ещё нет
---------------------------------------

Этот прогон отвечает на два критерия раздела 8 целиком, **не доходя до
бэктеста**:

- критерий 1 — пар, переживших FDR, в среднем на окно ≥ 50;
- критерий 2 — доля пар, выживающих между соседними окнами, ≥ 30 %.

И на критерий немедленной остановки: если в большинстве окон после
поправки выживает менее 15 пар, работа прекращается здесь. Поэтому
прогон запускается до того, как написана хоть строка бэктеста, а не
после.

Чего здесь нет: издержек. §3.4 требует отбраковывать пару, у которой
издержки съедают прибыль, а посимвольные комиссии и funding — предмет
A6. Из §3.4 применяется та часть, которая от издержек не зависит:
полураспад должен укладываться в горизонт удержания 1–5 дней (спека 01
§11). Порог зафиксирован ниже **до** прогона.

Устройство окна (§6)
--------------------

    │──── отбор 90 дн ────│─ эмбарго 7 ─│──── торговля 30 ────│
                                         │──── отбор 90 дн ────│ ...

Дата окна `t` — конец окна отбора. Тест видит только `[t−90, t)`.
Эмбарго и торговое окно здесь не используются: они определяют шаг
сетки, чтобы соседние окна означали то же, что и в бэктесте.

Пересечение соседних окон отбора — 60 дней из 90, и выживание пары
между ними частично механическое. Поэтому рядом считается выживание
между окнами, отстоящими на три шага, — у них общих данных нет вовсе.
Оба числа докладываются, и сравнивать критерий 2 нужно с первым, а
понимать — по второму.

Прогон возобновляемый: результат каждого окна пишется отдельным файлом,
готовые окна пропускаются. Урок A2 — состояние берётся с диска, а не из
дельты прогона.

    python3 walkforward.py                    # вся сетка
    python3 walkforward.py --at 2025-06-15    # одно окно
    python3 walkforward.py --report           # сводка по готовым окнам
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
WINDOWS = os.path.join(OUT, "windows")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))

import coint as C          # noqa: E402
import series as S         # noqa: E402
import pairs as P          # noqa: E402

# ---- параметры, зафиксированные до прогона -------------------------------

STEP = "1h"          # выбран замером sweep.py, обоснование — коммит 339ff5e
FORM_DAYS = 90       # окно отбора
EMBARGO_DAYS = 7     # зазор §6: больше максимума удержания (5 дней)
TRADE_DAYS = 30      # торговое окно; оно же шаг сетки
ALPHA = 0.10         # уровень FDR, §3.3

# §3.4 в части, не зависящей от издержек. Горизонт удержания 1–5 дней
# (спека 01 §11). Полураспад — время, за которое отклонение спреда
# сокращается вдвое: при входе на 2σ ровно один полураспад возвращает
# спред к 1σ. Пара с полураспадом в 5 дней закрывается на границе
# максимального удержания, с полураспадом в 10 — не закрывается вовсе и
# выходит по времени, то есть по случайной цене.
MAX_HALF_LIFE_DAYS = 5.0

# Нижней границы здесь нет намеренно. «Слишком быстрый» возврат
# отбраковывается не полураспадом, а сравнением амплитуды σ спреда с
# издержками — это A6, там есть посимвольная комиссия и funding.

BARS_PER_DAY = {"1m": 1440, "15m": 96, "1h": 24, "4h": 6, "1d": 1}
GRID_START = "2022-07-01"
GRID_END = "2026-06-01"


def window_dates(start, end, step_days):
    t = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while t <= last:
        yield t.isoformat()
        t += timedelta(days=step_days)


def form_window(at):
    t1 = date.fromisoformat(at)
    return (t1 - timedelta(days=FORM_DAYS)).isoformat(), t1.isoformat()


def run_window(con, at, groups, of_group, meta, liq, universe, interval):
    """Один срез: кандидаты A3 → Энгл–Грейнджер → BH → полураспад."""
    t = time.time()
    st = P.state_at(liq, universe, at)
    cand, live = P.candidates(groups, of_group, meta, st)
    t0, t1 = form_window(at)

    row = {"date": at, "form_start": t0, "form_end": t1, "step": STEP,
           "assets": len(live), "candidates": len(cand), "alpha": ALPHA,
           "max_half_life_days": MAX_HALF_LIFE_DAYS}
    if not cand:
        row.update({"tested": 0, "no_series": 0, "too_short": 0,
                    "raw_pass": 0, "fdr_pass": 0, "selected": 0,
                    "pairs": [], "seconds": round(time.time() - t, 1)})
        return row

    sym = {}
    for a, b, _ in cand:
        for x in (a, b):
            s = universe[x].get("binance_symbol")
            if s:
                sym[x] = s
    data = S.load(con, sorted(set(sym.values())), t0, t1, step=STEP,
                  interval=interval)

    res, no_series, too_short = [], 0, 0
    for a, b, g in cand:
        sa, sb = sym.get(a), sym.get(b)
        if sa is None or sb is None or sa not in data or sb not in data:
            no_series += 1
            continue
        _, ca, cb = S.align(data[sa], data[sb])
        # Первой ногой — более оборотистая: направление регрессии не
        # должно зависеть от порядка, в котором пара пришла из A3.
        if st[a]["turnover"] < st[b]["turnover"]:
            ca, cb = cb, ca
            first, second = b, a
        else:
            first, second = a, b
        r = C.test_pair(ca, cb)
        if r is None:
            too_short += 1
            continue
        r["pair"] = f"{a}/{b}"
        r["group"] = g
        r["regress"] = f"{first}~{second}"
        r["half_life_days"] = r.pop("half_life") / BARS_PER_DAY[STEP]
        res.append(r)

    p = np.array([r["p"] for r in res])
    keep = set(C.benjamini_hochberg(p, ALPHA).tolist())
    for i, r in enumerate(res):
        r["fdr"] = i in keep
        r["selected"] = bool(r["fdr"]
                             and r["half_life_days"] <= MAX_HALF_LIFE_DAYS)

    row.update({
        "tested": len(res),
        "no_series": no_series,
        "too_short": too_short,
        "obs_median": int(np.median([r["n"] for r in res])) if res else 0,
        "raw_pass": int((p < 0.05).sum()) if len(p) else 0,
        "fdr_pass": len(keep),
        "selected": sum(1 for r in res if r["selected"]),
        # Ряды не храним, храним результат по каждой паре: A5 строит
        # спред по тем же β, и пересчитывать их второй раз нельзя —
        # это была бы вторая копия расчёта.
        "pairs": res,
        "seconds": round(time.time() - t, 1),
    })
    return row


def load_windows():
    if not os.path.isdir(WINDOWS):
        return []
    out = []
    for f in sorted(os.listdir(WINDOWS)):
        if f.endswith(".json"):
            with open(os.path.join(WINDOWS, f), encoding="utf-8") as fh:
                out.append(json.load(fh))
    return out


def overlap(a, b):
    """Доля пар окна `a`, дошедших до окна `b`.

    Знаменатель — размер более раннего набора: вопрос §8 в том, сколько
    из отобранного удержалось, а не насколько похожи два набора.
    """
    if not a:
        return float("nan")
    return len(a & b) / len(a)


def summarize(rows):
    rows = sorted(rows, key=lambda r: r["date"])
    # Выживание «между соседними окнами» имеет смысл, только если соседние
    # окна отстоят на шаг сетки. Одно окно, посчитанное вручную не по
    # сетке, сдвинуло бы и соседство, и сравнение через три шага, и
    # заметить это в числах было бы нечем.
    gaps = {(date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days
            for a, b in zip(rows, rows[1:])}
    if gaps - {TRADE_DAYS}:
        raise SystemExit(
            f"окна стоят не по сетке: шаги {sorted(gaps)} при ожидаемом "
            f"{TRADE_DAYS}. Лишние файлы в {WINDOWS} нужно убрать — сводка "
            f"по разношаговой сетке считала бы соседство неправильно.")
    sel = [{p["pair"] for p in r["pairs"] if p.get("selected")} for r in rows]
    fdr = [{p["pair"] for p in r["pairs"] if p.get("fdr")} for r in rows]

    adj = [overlap(fdr[i], fdr[i + 1]) for i in range(len(fdr) - 1)]
    far = [overlap(fdr[i], fdr[i + 3]) for i in range(len(fdr) - 3)]
    adj_s = [overlap(sel[i], sel[i + 1]) for i in range(len(sel) - 1)]

    def mean(v):
        v = [x for x in v if np.isfinite(x)]
        return float(np.mean(v)) if v else float("nan")

    n_fdr = [r["fdr_pass"] for r in rows]
    n_sel = [r["selected"] for r in rows]
    return {
        "windows": len(rows),
        "candidates_total": sum(r["candidates"] for r in rows),
        "tested_total": sum(r["tested"] for r in rows),
        "raw_pass_mean": float(np.mean([r["raw_pass"] for r in rows])),
        "fdr_pass_mean": float(np.mean(n_fdr)),
        "fdr_pass_median": float(np.median(n_fdr)),
        "selected_mean": float(np.mean(n_sel)),
        "selected_median": float(np.median(n_sel)),
        "windows_fdr_below_15": int(sum(1 for x in n_fdr if x < 15)),
        "windows_selected_below_15": int(sum(1 for x in n_sel if x < 15)),
        "survival_adjacent_fdr": mean(adj),
        "survival_adjacent_selected": mean(adj_s),
        "survival_three_steps_fdr": mean(far),
        "criterion_1_fdr_ge_50": bool(np.mean(n_fdr) >= 50),
        "criterion_2_survival_ge_30pct": bool(mean(adj) >= 0.30),
        "stop_rule_triggered": bool(sum(1 for x in n_fdr if x < 15)
                                    > len(n_fdr) / 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m", help="хранилище A2")
    ap.add_argument("--at", help="одно окно вместо сетки")
    ap.add_argument("--start", default=GRID_START)
    ap.add_argument("--end", default=GRID_END)
    ap.add_argument("--force", action="store_true",
                    help="пересчитать окна, которые уже есть на диске")
    ap.add_argument("--report", action="store_true",
                    help="только сводка по тому, что уже посчитано")
    args = ap.parse_args()

    os.makedirs(WINDOWS, exist_ok=True)

    if not args.report:
        groups, of_group, meta = P.load_groups()
        liq, universe = P.load_liquidity(args.interval)
        dates = ([args.at] if args.at
                 else list(window_dates(args.start, args.end, TRADE_DAYS)))
        con = S.connect()
        for at in dates:
            path = os.path.join(WINDOWS, f"{at}.json")
            if os.path.exists(path) and not args.force:
                print(f"{at}  — уже посчитано, пропуск", flush=True)
                continue
            row = run_window(con, at, groups, of_group, meta, liq, universe,
                             args.interval)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(row, f, ensure_ascii=False)
            os.replace(tmp, path)
            print(f"{at}  активов {row['assets']:>3}  кандидатов "
                  f"{row['candidates']:>5}  проверено {row['tested']:>5}"
                  f"  p<0.05 {row['raw_pass']:>4}"
                  f"  после FDR {row['fdr_pass']:>4}"
                  f"  с полураспадом ≤{MAX_HALF_LIFE_DAYS:.0f} дн "
                  f"{row['selected']:>4}"
                  f"  ({row['seconds']} с)", flush=True)

    rows = load_windows()
    if not rows:
        return
    s = summarize(rows)
    with open(os.path.join(OUT, "walkforward_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump({"step": STEP, "form_days": FORM_DAYS,
                   "embargo_days": EMBARGO_DAYS, "trade_days": TRADE_DAYS,
                   "alpha": ALPHA, "max_half_life_days": MAX_HALF_LIFE_DAYS,
                   "summary": s,
                   "windows": [{k: v for k, v in r.items() if k != "pairs"}
                               for r in rows]}, f, ensure_ascii=False, indent=1)

    print(f"\nокон {s['windows']}  кандидатов всего {s['candidates_total']}"
          f"  проверено {s['tested_total']}")
    print(f"после FDR на окно: среднее {s['fdr_pass_mean']:.1f}, "
          f"медиана {s['fdr_pass_median']:.0f}"
          f"   (критерий 1 — ≥ 50: "
          f"{'да' if s['criterion_1_fdr_ge_50'] else 'НЕТ'})")
    print(f"после фильтра полураспада: среднее {s['selected_mean']:.1f}, "
          f"медиана {s['selected_median']:.0f}")
    print(f"выживание между соседними окнами (после FDR): "
          f"{100*s['survival_adjacent_fdr']:.1f} %"
          f"   (критерий 2 — ≥ 30 %: "
          f"{'да' if s['criterion_2_survival_ge_30pct'] else 'НЕТ'})")
    print(f"выживание через три шага (окна отбора не пересекаются): "
          f"{100*s['survival_three_steps_fdr']:.1f} %")
    print(f"окон с менее чем 15 парами после FDR: "
          f"{s['windows_fdr_below_15']} из {s['windows']}"
          f"   (правило остановки: "
          f"{'СРАБОТАЛО' if s['stop_rule_triggered'] else 'нет'})")


if __name__ == "__main__":
    main()
