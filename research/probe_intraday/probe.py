#!/usr/bin/env python3
"""
Зонд: какой знак у связи «прошлое отклонение → будущее» внутри дня?

Это **зонд, а не гипотеза**. Ни порогов, ни объявленной сетки, ни
вердикта: его задача ответить на три вопроса и решить, стоит ли писать
спеку.

1. **Какой знак.** На горизонтах 10–90 дней измерено: IC положителен
   везде, то есть работает возврат, и ставка на расхождение была бы
   неверной стороной. Внутри дня знак может быть другим — не мерялось.
2. **Какая величина против издержек.** Внутридневной ребаланс платит
   полную замену книги каждый раз: 11 б.п. гросс-нотионала при тейкере
   5.5. Спред дециля обязан это перекрывать, иначе знак безразличен.
3. **Не микроструктура ли это.** Главная ловушка горизонта. Отскок
   между ценой покупки и продажи даёт **ложный возврат**, который
   растёт по мере измельчения бара и не торгуется вовсе. A4 уже
   находила эту подпись: полураспад спреда укорачивался вместе с шагом
   бара, «монотонное сползание есть подпись микроструктурного шума».

Поэтому всё считается на **трёх шагах бара сразу**. Если величина
растёт при измельчении — это микроструктура, и направление закрыто.
Если держится — эффект в единицах времени, а не в единицах сетки
наблюдений, и тогда есть о чём говорить.

Считается по выборке окон, а не по всей истории: зонд отвечает на
вопрос о знаке, и для этого достаточно нескольких окон, разнесённых по
режимам рынка.

    python3 probe.py --interval 1m
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

sys.path.insert(0, os.path.join(RESEARCH, "r1_factor"))
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))

import factor as FA          # noqa: E402
import residual as RS        # noqa: E402
import series as S           # noqa: E402
import pairs as P            # noqa: E402

STEPS = ("1m", "5m", "15m")          # проверка на микроструктуру
STEP_MIN = {"1m": 1, "5m": 5, "15m": 15}

# Горизонты в МИНУТАХ: величина должна быть свойством времени, а не
# числа баров, иначе сравнение шагов бессмысленно.
KS_MIN = (60, 240)                   # окно накопления сигнала
HS_MIN = (60, 240, 1440)             # горизонт удержания
MIN_BARS = 4                         # меньше — величина не оценивается

FORM_DAYS = 20                       # окно оценки β
TEST_DAYS = 10                       # окно замера
WINDOWS = ("2022-09-01", "2023-03-01", "2023-09-01", "2024-03-01",
           "2024-09-01", "2025-03-01", "2025-09-01", "2026-03-01")

MIN_ASSETS = 30
WIDTH = 0.10                         # дециль, для спреда
ROUND_TRIP_BP = 11.0                 # полная замена книги при тейкере 5.5


def ms(day):
    return int(np.datetime64(day + "T00:00:00", "ms").astype("int64"))


def one_window(con, start, step, liq, universe, interval):
    """Один срез: β на окне формирования, IC на окне замера."""
    t0 = start
    t1 = (date.fromisoformat(start)
          + timedelta(days=FORM_DAYS + TEST_DAYS + 1)).isoformat()
    st = P.state_at(liq, universe, start)
    live = {a for a, s in st.items()
            if s["share_traded"] >= P.MIN_SHARE_TRADED}
    sym_of = {a: universe[a]["binance_symbol"] for a in live
              if universe[a].get("binance_symbol")}
    if len(sym_of) < MIN_ASSETS:
        return None
    raw = S.load(con, sorted(sym_of.values()), t0, t1, step=step,
                 interval=interval)
    if not raw:
        return None
    by_asset = {a: raw[s] for a, s in sym_of.items() if s in raw}
    grid, cols, PX = FA.price_grid(by_asset, step, ms(t0), ms(t1))
    R = FA.log_returns(PX)
    if len(R) < 100:
        return None

    per_day = 1440 // STEP_MIN[step]
    i_split = FORM_DAYS * per_day
    if i_split >= len(R):
        return None

    _, F_loo, _ = FA.market_factor(R)
    fitted = FA.betas(R[:i_split], F_loo[:i_split])
    if len(fitted) < MIN_ASSETS:
        return None
    E = FA.residuals(R, F_loo, fitted)

    out = {}
    for k_min in KS_MIN:
        kb = k_min // STEP_MIN[step]
        if kb < MIN_BARS:
            continue
        for h_min in HS_MIN:
            hb = h_min // STEP_MIN[step]
            if hb < MIN_BARS:
                continue
            ics, spreads = [], []
            # Сечения идут НЕПЕРЕСЕКАЮЩИМИСЯ шагами по h: соседние
            # перекрывались бы форвардом, и превосходство создавалось бы
            # перекрытием, а не эффектом. Урок A4.
            for i in range(i_split, len(R) - hb, hb):
                sig, ns = RS.accumulate_resid(E, max(i_split, i - kb), i)
                fwd, nf = RS.accumulate_resid(E, i, i + hb)
                sig = np.where(ns >= MIN_BARS, -sig, np.nan)
                fwd = np.where(nf >= MIN_BARS, fwd, np.nan)
                ic, n = RS.spearman(sig, fwd)
                if ic is not None:
                    ics.append(ic)
                b = RS.basket_spread(sig, fwd, WIDTH)
                if b:
                    spreads.append(b["spread"])
            if len(ics) >= 5:
                out[(k_min, h_min)] = {
                    "ic": float(np.median(ics)),
                    "spread_bp": float(np.median(spreads)) * 1e4,
                    "sections": len(ics),
                }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--steps", default=",".join(STEPS))
    args = ap.parse_args()
    steps = [s.strip() for s in args.steps.split(",")]

    liq, universe = P.load_liquidity(args.interval)
    con = S.connect()
    acc = {}
    for step in steps:
        for w in WINDOWS:
            t = time.time()
            r = one_window(con, w, step, liq, universe, args.interval)
            print(f"{step:>4} {w}: {'—' if not r else len(r)} ячеек, "
                  f"{time.time() - t:.1f} с", file=sys.stderr, flush=True)
            if not r:
                continue
            for key, val in r.items():
                acc.setdefault((step, *key), []).append(val)

    rows = []
    for (step, k_min, h_min), vals in sorted(acc.items()):
        rows.append({
            "step": step, "k_min": k_min, "h_min": h_min,
            "ic": float(np.median([v["ic"] for v in vals])),
            "spread_bp": float(np.median([v["spread_bp"] for v in vals])),
            "sections": int(sum(v["sections"] for v in vals)),
            "windows": len(vals),
        })
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"probe_{args.interval}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"config": {"interval": args.interval, "steps": steps,
                              "ks_min": list(KS_MIN), "hs_min": list(HS_MIN),
                              "windows": list(WINDOWS),
                              "round_trip_bp": ROUND_TRIP_BP},
                   "rows": rows}, f, ensure_ascii=False, indent=1)

    print("\nЗНАК И ВЕЛИЧИНА ВНУТРИ ДНЯ")
    print("IC > 0 — возврат; IC < 0 — расхождение\n")
    print(f"{'шаг':>5}{'k, мин':>8}{'h, мин':>8}{'IC':>10}"
          f"{'спред дециля, б.п.':>20}{'против 11 б.п.':>16}{'сечений':>10}")
    for r in rows:
        mark = "окупается" if abs(r["spread_bp"]) / 2 > ROUND_TRIP_BP else ""
        print(f"{r['step']:>5}{r['k_min']:>8}{r['h_min']:>8}{r['ic']:>10.4f}"
              f"{r['spread_bp']:>20.1f}{mark:>16}{r['sections']:>10}")

    print("\nПРОВЕРКА НА МИКРОСТРУКТУРУ: та же величина по шагам бара")
    print("рост при измельчении = отскок bid-ask, а не торгуемый эффект\n")
    for k_min in KS_MIN:
        for h_min in HS_MIN:
            line = [f"k={k_min:>4} h={h_min:>4}:"]
            for step in steps:
                v = [r for r in rows if r["step"] == step
                     and r["k_min"] == k_min and r["h_min"] == h_min]
                line.append(f"{step} {v[0]['ic']:+.4f}" if v
                            else f"{step}   —   ")
            print("  " + "   ".join(line))
    print(f"\nзаписано {dst}")


if __name__ == "__main__":
    main()
