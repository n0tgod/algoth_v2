#!/usr/bin/env python3
"""
S1 — книга carry с управлением риском. Прогон.

Спека 05, этап S1. **Единственный дорогой проход по хранилищу во всей
гипотезе**: он сохраняет всё, что нужно этапам S2–S4, и те считаются
пересчётом за секунды. Урок F1–F3, где такой порядок дал полтора
десятка замеров ценой секунд и ловил расхождения встроенной сверкой.

Что сохраняется сверх векторов F1
---------------------------------

**Волатильность актива на окне оценки** — вход правила 1. Считается по
тем же часовым барам, на которых живёт всё остальное, и по тому же
окну `k`, что и оценка ставки: обе величины обязаны быть наблюдаемы в
момент решения и ни одна не смеет заглядывать за `t`.

**Доходность в момент первого пробоя уровня** — вход правила 2. Чтобы
смоделировать выход, пути целиком не нужны: достаточно одного числа на
ногу и уровень — где именно позиция оказалась, когда уровень пробит.
Рядом сохраняется доля периода, пройденная к этому моменту, — без неё
начисления выбитой ноги пришлось бы либо выбросить, либо подарить
целиком.

Сторон две, и обе нужны: сторона ноги зависит от `k`, а один и тот же
актив на одной дате может стоять в лонге при `k = 7` и в шорте при
`k = 14`.

**Исполнение выхода моделируется по закрытию пробившего бара, а не по
уровню.** Разрыв тем самым частично учтён — именно он и делает стоп
ненадёжным против сквиза, ради защиты от которого он и ставится.

    python3 run.py --interval 1m
    python3 run.py --interval 1m --restat      # пересбор из векторов
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
A1 = os.path.join(RESEARCH, "a1_universe", "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "f1_carry"))
sys.path.insert(0, os.path.join(RESEARCH, "r1_factor"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))
sys.path.insert(0, os.path.dirname(RESEARCH))

import managed as MG         # noqa: E402
import carry as CY           # noqa: E402
import factor as FA          # noqa: E402
import series as S           # noqa: E402
import pairs as P            # noqa: E402
from research.common import funding_series as FS   # noqa: E402

STEP = "1h"
BARS_PER_DAY = 24

# Сетка §4 спеки 05 — та же, что в 04, и НЕ расширяется.
KS = (7, 14)
HS = (5, 10)
WIDTHS = {"decile": 0.10, "quintile": 0.20}

# §3.3: уровень выхода объявлен ДО прогона и выведен из распределения
# доходности ноги (1-й процентиль, округлённый до 5 %), а не из
# результата. Второй уровень сохраняется проверкой устойчивости и в
# вердикт не входит.
DECLARED_STOP = {5: 0.35, 10: 0.45}
ROBUSTNESS_STOP = 0.25
LEVELS = sorted({*DECLARED_STOP.values(), ROBUSTNESS_STOP})

GRID_START = "2022-07-01"
GRID_END = "2026-06-01"
CHUNK_DAYS = 90
MIN_ASSETS = 30
MIN_FORWARD_BARS = 1
MIN_VOL = 1e-6


def rebalance_dates(start, end):
    t, last = date.fromisoformat(start), date.fromisoformat(end)
    while t <= last:
        yield t.isoformat()
        t += timedelta(days=1)


def volatility(R, i0, i1):
    """Разброс часовых доходностей на окне оценки. NaN, если баров мало."""
    win = R[i0:i1]
    n = np.isfinite(win).sum(axis=0)
    with np.errstate(invalid="ignore"):
        v = np.nanstd(win, axis=0)
    return np.where(n >= 24, v, np.nan)


def exits(R, i_t, i_end, levels):
    """Точки выхода по каждому уровню и каждой стороне.

    Возвращает `{уровень: {"long": (доходность, доля), "short": (…)}}`.
    Доходность — та, что была в момент **закрытия пробившего бара**;
    NaN, если уровень не пробит за период.
    """
    win = R[i_t:i_end]
    if len(win) == 0:
        empty = np.full(R.shape[1], np.nan)
        return {L: {"long": (empty, empty), "short": (empty, empty)}
                for L in levels}
    cum = np.nancumsum(np.where(np.isfinite(win), win, 0.0), axis=0)
    seen = np.cumsum(np.isfinite(win), axis=0) > 0
    cum = np.where(seen, cum, np.nan)
    move = np.expm1(cum)                     # изменение цены, доли
    T = len(win)

    out = {}
    for L in levels:
        row = {}
        for side, pos in (("long", move), ("short", -move)):
            breach = np.isfinite(pos) & (pos <= -L)
            any_hit = breach.any(axis=0)
            first = np.argmax(breach, axis=0)
            idx = np.where(any_hit, first, 0)
            val = pos[idx, np.arange(pos.shape[1])]
            frac = (idx + 1) / T
            row[side] = (np.where(any_hit, val, np.nan),
                         np.where(any_hit, frac, np.nan))
        out[L] = row
    return out


def run_date(at, grid, PX, cols, live, funding):
    t_ms = FS.ms(at)
    i_t = int(np.searchsorted(grid, t_ms))
    keep = [i for i, c in enumerate(cols) if c in live]
    if len(keep) < MIN_ASSETS:
        return None
    names = [cols[i] for i in keep]
    R = FA.log_returns(PX[:, keep])
    if i_t < 1 or i_t - 1 >= len(R):
        return None

    scores, vols = {}, {}
    for k in KS:
        scores[k] = FS.funding_score(funding, names, at, k)[0]
        i0 = max(0, i_t - k * BARS_PER_DAY)
        vols[k] = volatility(R, i0, i_t)

    price, fund, ex = {}, {}, {}
    for h in HS:
        end = (date.fromisoformat(at) + timedelta(days=h)).isoformat()
        i_end = min(len(R), int(np.searchsorted(grid, FS.ms(end))))
        win = R[i_t:i_end]
        m = np.isfinite(win)
        nb = m.sum(axis=0)
        s = np.where(m, win, 0.0).sum(axis=0)
        price[h] = np.where(nb >= MIN_FORWARD_BARS, s, np.nan)
        fund[h] = np.array([FS.accrued(funding, a, t_ms, FS.ms(end))
                            for a in names], dtype=np.float64)
        ex[h] = exits(R, i_t, i_end, LEVELS)

    return {
        "date": at, "assets": len(names),
        "names": names,
        "score": {k: v.tolist() for k, v in scores.items()},
        "vol": {k: v.tolist() for k, v in vols.items()},
        "price": {h: v.tolist() for h, v in price.items()},
        "funding": {h: v.tolist() for h, v in fund.items()},
        "exit": {h: {str(L): {side: [ex[h][L][side][0].tolist(),
                                     ex[h][L][side][1].tolist()]
                              for side in ("long", "short")}
                     for L in LEVELS} for h in HS},
    }


def process_chunk(con, dates, liq, universe, funding, interval):
    t0 = (date.fromisoformat(dates[0]) - timedelta(days=max(KS))).isoformat()
    t1 = (date.fromisoformat(dates[-1])
          + timedelta(days=max(HS) + 1)).isoformat()
    live_by_date, wanted = {}, set()
    for at in dates:
        st = P.state_at(liq, universe, at)
        live = {a for a, s in st.items()
                if s["share_traded"] >= P.MIN_SHARE_TRADED}
        live_by_date[at] = live
        wanted |= live
    if not wanted:
        return []
    sym_of = {a: universe[a]["binance_symbol"] for a in wanted
              if universe[a].get("binance_symbol")}
    raw = S.load(con, sorted(sym_of.values()), t0, t1, step=STEP,
                 interval=interval)
    if not raw:
        return []
    by_asset = {a: raw[s] for a, s in sym_of.items() if s in raw}
    grid, cols, PX = FA.price_grid(by_asset, STEP, FS.ms(t0), FS.ms(t1))
    out = []
    for at in dates:
        r = run_date(at, grid, PX, cols, live_by_date[at], funding)
        if r:
            out.append(r)
    return out


def arr(d, key):
    return np.asarray(d[str(key)] if str(key) in d else d[key],
                      dtype=np.float64)


def build(vec, dates):
    """Три руки на каждую ячейку, §3.3 и контроль.

    - `base` — равные веса, без выходов: та же книга, что в F1;
    - `sized` — правило 1 в одиночку;
    - `managed` — правила 1 и 2 вместе. Вердикт выносится по ней.

    Разложение по правилам — диагностика. Выбрать по нему лучшую руку
    значило бы превратить одно объявленное семейство испытаний в три.
    """
    cells = {}
    for k in KS:
        for h in HS:
            level = DECLARED_STOP[h]
            for wname, width in WIDTHS.items():
                name = f"k{k}_h{h}_{wname}"
                rows = {"base": [], "sized": [], "managed": []}
                extra = []
                for day in dates[::h]:
                    v = vec[day]
                    score, vol = arr(v["score"], k), arr(v["vol"], k)
                    price, fund = arr(v["price"], h), arr(v["funding"], h)
                    ok = np.isfinite(price) & np.isfinite(fund)
                    price = np.where(ok, price, np.nan)

                    w_eq, n_eq = MG.equal_weights(score, vol, width, MIN_VOL)
                    w_iv, n_iv = MG.inverse_vol_weights(score, vol, width,
                                                        MIN_VOL)
                    if n_eq < 1 or n_iv < 1:
                        continue
                    pos = CY.position_return(np.sign(w_iv), price)

                    def plain(w):
                        r = pos - np.sign(w) * np.where(ok, fund, 0.0)
                        return MG.book_pnl(w, np.where(ok, r, 0.0))

                    rows["base"].append(plain(w_eq))
                    rows["sized"].append(plain(w_iv))

                    # Точка выхода берётся по СТОРОНЕ ноги: у лонга
                    # уровень пробивается падением, у шорта ростом, и
                    # это два разных числа для одного актива.
                    e = v["exit"][str(h)][str(level)]
                    lo_r = np.asarray(e["long"][0], dtype=np.float64)
                    lo_f = np.asarray(e["long"][1], dtype=np.float64)
                    sh_r = np.asarray(e["short"][0], dtype=np.float64)
                    sh_f = np.asarray(e["short"][1], dtype=np.float64)
                    er = np.where(w_iv > 0, lo_r, sh_r)
                    ef = np.where(w_iv > 0, lo_f, sh_f)
                    er = np.where(ok, er, np.nan)
                    ret, hit = MG.apply_exits(w_iv, pos, er, ef,
                                              np.where(ok, fund, 0.0))
                    b = MG.book_pnl(w_iv, np.where(ok, ret, 0.0))
                    b["exit_share"] = float(np.abs(w_iv[hit]).sum())
                    b["unpaired"] = MG.unpaired_share(w_iv, hit)
                    b["exit_turnover"] = MG.turnover_from_exits(w_iv, hit)
                    rows["managed"].append(b)
                    extra.append(b)

                if len(rows["base"]) < 10:
                    continue
                cell = {"periods": len(rows["base"]), "stop_level": level}
                for arm, rs in rows.items():
                    g = [x["gross"] for x in rs]
                    cell[arm] = {
                        "gross": CY.robust(g),
                        "gross_mean": CY.robust(g, "mean"),
                        "positive_share": CY.share_positive(g),
                        "tail_ratio": CY.tail_ratio(g),
                        "long": CY.robust([x["long"] for x in rs]),
                        "short": CY.robust([x["short"] for x in rs]),
                        "worst_leg": min(x["worst_leg"] for x in rs
                                         if x["worst_leg"] is not None),
                        "series": [round(float(x), 12) for x in g],
                    }
                cell["exit_share"] = CY.robust([x["exit_share"]
                                                for x in extra])
                cell["unpaired"] = CY.robust([x["unpaired"] for x in extra])
                cell["exit_turnover"] = CY.robust([x["exit_turnover"]
                                                   for x in extra])
                cells[name] = cell
    return cells


def summarize(cells):
    import sys as _s
    _s.path.insert(0, os.path.join(RESEARCH, "r5_backtest"))
    import stats as ST
    grid = {}
    for arm in ("base", "sized", "managed"):
        dd, gr = [], []
        for n, c in cells.items():
            h = int(n.split("_h")[1].split("_")[0])
            dd.append(ST.max_drawdown(c[arm]["series"])["max_drawdown"])
            gr.append(c[arm]["gross"])
            c[arm]["drawdown"] = dd[-1]
            c[arm]["sharpe"] = ST.sharpe(c[arm]["series"], 365.0 / h)
        grid[arm] = {"gross_median": CY.robust(gr),
                     "drawdown_median": CY.robust(dd),
                     "drawdown_worst": min(dd)}
    better_dd = sum(1 for c in cells.values()
                    if c["managed"]["drawdown"] > c["base"]["drawdown"])
    worse_gross = sum(1 for c in cells.values()
                      if c["managed"]["gross"] < c["base"]["gross"])
    blown = sum(1 for c in cells.values() if c["managed"]["worst_leg"] < -1.0)
    grid["cells"] = len(cells)
    grid["drawdown_improved"] = better_dd
    grid["gross_worse"] = worse_gross
    grid["cells_with_blown_leg"] = blown
    return grid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--start", default=GRID_START)
    ap.add_argument("--end", default=GRID_END)
    ap.add_argument("--funding-venue", default="bybit",
                    choices=("bybit", "binance"))
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--restat", action="store_true",
                    help="пересобрать сводку из векторов, без хранилища")
    args = ap.parse_args()

    chunks = os.path.join(OUT, "chunks")
    vectors = os.path.join(OUT, "vectors")
    os.makedirs(chunks, exist_ok=True)
    os.makedirs(vectors, exist_ok=True)
    tag = f"{args.interval}_{args.funding_venue}"

    if not args.restat:
        liq, universe = P.load_liquidity(args.interval)
        bybit = args.funding_venue == "bybit"
        directory = os.path.join(A1, "funding" if bybit
                                 else "funding_binance")
        funding = FS.load_funding(
            directory, universe, set(universe),
            symbol_field="bybit_symbol" if bybit else "binance_symbol")
        if not funding or len(funding) < FS.MIN_FUNDING_SYMBOLS:
            raise SystemExit(f"ряды funding не загрузились из {directory}")
        if not bybit:
            print("ВНИМАНИЕ: ставки НЕ с площадки исполнения — только "
                  "проверка конвейера", file=sys.stderr, flush=True)
        print(f"funding: ряды у {len(funding)} активов", file=sys.stderr,
              flush=True)

        con = S.connect()
        days = list(rebalance_dates(args.start, args.end))
        groups = [days[i:i + CHUNK_DAYS] for i in range(0, len(days),
                                                        CHUNK_DAYS)]
        for g in groups:
            path = os.path.join(vectors, f"{tag}_{g[0]}.json")
            if os.path.exists(path) and not args.rerun:
                continue
            t = time.time()
            rows = process_chunk(con, g, liq, universe, funding,
                                 args.interval)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({r["date"]: r for r in rows}, f)
            print(f"{g[0]}…{g[-1]}: сечений {len(rows)}, "
                  f"{time.time() - t:.1f} с", file=sys.stderr, flush=True)

    vec = {}
    for fn in sorted(os.listdir(vectors)):
        if fn.startswith(tag + "_") and fn.endswith(".json"):
            with open(os.path.join(vectors, fn), encoding="utf-8") as f:
                vec.update(json.load(f))
    if not vec:
        raise SystemExit(f"в {vectors} нет векторов для {tag}")

    dates = sorted(vec)
    cells = build(vec, dates)
    grid = summarize(cells)
    doc = {"config": {"interval": args.interval, "ks": list(KS),
                      "hs": list(HS), "widths": WIDTHS,
                      "funding_venue": args.funding_venue,
                      "declared_stop": {str(k): v
                                        for k, v in DECLARED_STOP.items()},
                      "robustness_stop": ROBUSTNESS_STOP,
                      "sections": len(dates),
                      "declared_trials": len(KS) * len(HS) * len(WIDTHS)},
           "grid": grid, "cells": cells}
    dst = os.path.join(OUT, f"s1_{tag}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f"\nсечений {len(dates)}, ячеек {grid['cells']}")
    for arm in ("base", "sized", "managed"):
        g = grid[arm]
        print(f"  {arm:<9} брутто {g['gross_median'] * 1e4:+7.1f} б.п.  "
              f"просадка медиана {g['drawdown_median']:>7.1%}  "
              f"худшая {g['drawdown_worst']:>7.1%}")
    print(f"просадка улучшилась в {grid['drawdown_improved']} ячейках из "
          f"{grid['cells']}, брутто упало в {grid['gross_worse']}")
    print(f"ячеек, где нога теряет больше 100 % позиции: "
          f"{grid['cells_with_blown_leg']} (критерий 13)")
    print(f"записано {dst}")


if __name__ == "__main__":
    main()
