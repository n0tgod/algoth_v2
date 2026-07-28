#!/usr/bin/env python3
"""
F2 — ловушки раздела 5 спеки 04. Прогон.

Считается **пересчётом векторов, сохранённых прогоном F1**, а не вторым
проходом по хранилищу. Законно потому, что все четыре ловушки суть
функции того, что F1 уже сохранил: состава книги, форвардных
доходностей активов и рядов funding. Второй проход по 760 млн баров
ради этого стоил бы ещё часа на сервере и ничего бы не уточнил.

Побочная выгода важнее экономии, и она та же, что была в R3: ценовой
борт книги, пересчитанный из тех же векторов, **обязан совпасть** с
тем, что F1 записал в свой артефакт. Сверка встроена и прерывает
прогон при расхождении.

Что меряется
------------

- **§5.2, бета книги** — решающий замер после F1. Регрессия ценового
  борта книги на доходность равновзвешенной волны за те же периоды.
  Критерий 10 §8.3: медиана |β| ≤ 0.2;
- **§5.3, делистинги** — доля гросса в активах, снимаемых с торгов в
  ближайшие 30 дней, и результат книги без них;
- **§5.5, ликвидность и ёмкость** — оборот дециля против универсума,
  доля баров со сделками, предельный капитал;
- **§5.6, смена режима начисления** — доля веса, у которой частота
  начислений в сутки изменилась между окном оценки и окном удержания.

    python3 run.py --interval 1m
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
A1 = os.path.join(RESEARCH, "a1_universe", "out")
F1 = os.path.join(RESEARCH, "f1_carry", "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "f1_carry"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))
sys.path.insert(0, os.path.dirname(RESEARCH))

import traps as T            # noqa: E402
import carry as CY           # noqa: E402
import pairs as P            # noqa: E402
from research.common import funding_series as FS   # noqa: E402

KS = (7, 14)
HS = (5, 10)
WIDTHS = {"decile": 0.10, "quintile": 0.20}

BETA_WINDOW = 26             # скользящее окно β, периодов
DELIST_HORIZON = 30          # дней, ловушка §5.3
CAPITAL = 20_000             # верх диапазона фазы D, §5.5
MAX_TURNOVER_SHARE = 0.05
TOLERANCE = 1e-9             # сверка с артефактом F1


def load_vectors(tag):
    d = os.path.join(F1, "vectors")
    if not os.path.isdir(d):
        raise SystemExit(f"нет {d} — сначала f1_carry/run.py")
    out = {}
    for fn in sorted(os.listdir(d)):
        if not (fn.startswith(tag + "_") and fn.endswith(".json")):
            continue
        with open(os.path.join(d, fn), encoding="utf-8") as f:
            for day, v in json.load(f).items():
                out[day] = v
    if not out:
        raise SystemExit(f"в {d} нет векторов для {tag}")
    return out


def bybit_delist_days(universe):
    """Дата снятия с торгов **на площадке исполнения**, по активу.

    Берётся `delivery_time` справочника Bybit, а не `last_trading_day`
    универсума: последнее есть дата последней сделки в архиве Binance, а
    ловушка §5.3 — про инструмент, который снимает с торгов та площадка,
    где мы стоим в позиции. A2 намерила, что расходятся они годами: у
    ORBS архив Binance кончается 2024-12-09, а на Bybit инструмент
    торговался до 2026-06-11.

    Дата Binance измеряла бы совсем другое событие и вдобавок в другую
    сторону: она пометила бы «идущим к делистингу» актив, который на
    площадке исполнения жив ещё два года, и пропустила бы настоящие
    снятия.
    """
    path = os.path.join(A1, "instruments.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — справочник Bybit нужен ловушке §5.3")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw if isinstance(raw, list) else list(raw.values())
    by_symbol = {}
    for r in rows:
        dt = r.get("delivery_time")
        if r.get("status") != "Closed" or not dt or dt in ("0", 0):
            continue
        by_symbol[r["symbol"]] = np.datetime64(int(dt), "ms").astype(
            "datetime64[D]").astype(str)
    out = {}
    for a, v in universe.items():
        s = v.get("bybit_symbol")
        if s and s in by_symbol:
            out[a] = by_symbol[s]
    return out


def as_array(d, key):
    return np.asarray(d[str(key)] if str(key) in d else d[key],
                      dtype=np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--funding-venue", default="bybit")
    a = ap.parse_args()
    tag = f"{a.interval}_{a.funding_venue}"

    vec = load_vectors(tag)
    dates = sorted(vec)
    liq, universe = P.load_liquidity(a.interval)
    last_day = bybit_delist_days(universe)
    bybit = a.funding_venue == "bybit"
    funding = FS.load_funding(
        os.path.join(A1, "funding" if bybit else "funding_binance"),
        universe, set(universe),
        symbol_field="bybit_symbol" if bybit else "binance_symbol")
    if not funding:
        raise SystemExit("ряды funding не загрузились")

    with open(os.path.join(F1, f"f1_{tag}.json"), encoding="utf-8") as f:
        f1 = json.load(f)

    states = {}
    out, mismatches = {}, 0
    for k in KS:
        for h in HS:
            for wname, width in WIDTHS.items():
                name = f"k{k}_h{h}_{wname}"
                book, mkt, rows = [], [], []
                for day in dates[::h]:
                    v = vec[day]
                    names = v["names"]
                    score = as_array(v["score"], k)
                    price = as_array(v["price"], h)
                    fund = as_array(v["funding"], h)
                    w, per_leg = CY.weights(score, width)
                    if per_leg < 1:
                        continue
                    d = CY.decompose(w, price, fund)
                    book.append(d["price"])
                    mkt.append(T.market_return(price))

                    if day not in states:
                        states[day] = P.state_at(liq, universe, day)
                    st = states[day]
                    turn = {s: x["turnover"] for s, x in st.items()}
                    share = {s: x["share_traded"] for s, x in st.items()}

                    dl_share, _ = T.near_delisting(names, w, last_day, day,
                                                   DELIST_HORIZON)
                    t0 = FS.ms(day)
                    t_form = FS.ms((date.fromisoformat(day)
                                    - timedelta(days=k)).isoformat())
                    t1 = FS.ms((date.fromisoformat(day)
                                + timedelta(days=h)).isoformat())
                    cf = [FS.accrual_count(funding, s, t_form, t0)
                          for s in names]
                    ch = [FS.accrual_count(funding, s, t0, t1) for s in names]
                    flags = T.regime_change(cf, ch, k, h)

                    # Книга без активов, идущих к делистингу: та же
                    # конструкция на суженном сечении. Сравнивать с
                    # полной книгой честно — вес просто перераспределён
                    # между оставшимися, а не выброшен.
                    clean = score.copy()
                    for i, s in enumerate(names):
                        ld = last_day.get(s)
                        if ld and 0 <= (date.fromisoformat(ld)
                                        - date.fromisoformat(day)).days \
                                <= DELIST_HORIZON:
                            clean[i] = np.nan
                    wc, pl = CY.weights(clean, width)
                    dc = CY.decompose(wc, price, fund) if pl >= 1 else None

                    rows.append({
                        "gross": d["gross"],
                        "gross_no_delist": dc["gross"] if dc else None,
                        "delist_share": dl_share,
                        "regime_share": T.weighted_share(w, flags),
                        "turn_long": T.leg_stat(names, w, turn, +1),
                        "turn_short": T.leg_stat(names, w, turn, -1),
                        "turn_universe": float(np.median(
                            [x for x in turn.values() if x])) if turn else None,
                        "share_traded_book": T.leg_stat(names, np.abs(w),
                                                        share, +1),
                        "capacity": T.capacity(w, turn, names, CAPITAL,
                                               MAX_TURNOVER_SHARE),
                    })

                if len(rows) < 10:
                    continue

                # Сверка с артефактом F1: тот же ценовой борт обязан
                # получиться из тех же векторов. Расхождение означает,
                # что F2 считает другую книгу, и все меры ниже
                # относились бы не к ней.
                want = f1["cells"].get(name, {}).get("price")
                got = CY.robust(book)
                if want is not None and got is not None \
                        and abs(want - got) > TOLERANCE:
                    mismatches += 1
                    print(f"РАСХОЖДЕНИЕ {name}: F1 {want:.9f} против "
                          f"{got:.9f}", file=sys.stderr)

                b = T.beta(book, mkt)
                roll = T.rolling_beta(book, mkt, min(BETA_WINDOW, len(book)))
                caps = [r["capacity"] for r in rows if r["capacity"]]
                out[name] = {
                    "periods": len(rows),
                    "beta": b[0] if b else None,
                    "beta_r2": b[1] if b else None,
                    "beta_rolling_median": (float(np.median(roll))
                                            if roll else None),
                    "beta_rolling_min": float(np.min(roll)) if roll else None,
                    "beta_rolling_max": float(np.max(roll)) if roll else None,
                    "price_check": got,
                    "delist_share": CY.robust([r["delist_share"] for r in rows]),
                    "delist_share_max": max(r["delist_share"] for r in rows),
                    "gross": CY.robust([r["gross"] for r in rows]),
                    "gross_no_delist": CY.robust(
                        [r["gross_no_delist"] for r in rows]),
                    "regime_share": CY.robust(
                        [r["regime_share"] for r in rows]),
                    "turn_long": CY.robust([r["turn_long"] for r in rows]),
                    "turn_short": CY.robust([r["turn_short"] for r in rows]),
                    "turn_universe": CY.robust(
                        [r["turn_universe"] for r in rows]),
                    "share_traded_book": CY.robust(
                        [r["share_traded_book"] for r in rows]),
                    "capacity_worst_share": CY.robust(
                        [c["worst_share"] for c in caps]),
                    "capital_limit": CY.robust(
                        [c["capital_limit"] for c in caps if
                         c["capital_limit"] is not None]),
                }

    if mismatches:
        raise SystemExit(f"сверка с F1 не сошлась в {mismatches} ячейках — "
                         f"F2 считает другую книгу, меры недействительны")

    betas = [abs(c["beta"]) for c in out.values() if c["beta"] is not None]
    doc = {"config": {"interval": a.interval, "funding_venue": a.funding_venue,
                      "beta_window": BETA_WINDOW,
                      "delist_horizon_days": DELIST_HORIZON,
                      "capital": CAPITAL,
                      "max_turnover_share": MAX_TURNOVER_SHARE,
                      "sections": len(dates)},
           "cells": out,
           "grid": {"abs_beta_median": (float(np.median(betas))
                                        if betas else None),
                    "abs_beta_max": max(betas) if betas else None,
                    "criterion_10_pass": (bool(betas)
                                          and float(np.median(betas)) <= 0.2)}}
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"f2_{tag}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    g = doc["grid"]
    print(f"сверка ценового борта с F1: расхождений 0 из {len(out)} ячеек")
    print(f"медиана |β| по сетке {g['abs_beta_median']:.3f}, "
          f"максимум {g['abs_beta_max']:.3f} — критерий 10 "
          f"{'✓' if g['criterion_10_pass'] else '✗'}")
    print(f"записано {dst}")


if __name__ == "__main__":
    main()
