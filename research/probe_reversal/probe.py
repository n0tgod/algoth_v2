#!/usr/bin/env python3
"""
Зонд: работает ли краткосрочный возврат на минутных горизонтах.

**Зонд, а не гипотеза.** Ни объявленной сетки, ни порогов-критериев, ни
вердикта. Его задача — ответить на три вопроса и решить, стоит ли
писать спеку.

Откуда он взялся
----------------

L3 закрыл гипотезу каскадов, но по дороге намерил другое: после резкого
падения цена растёт, и на пятнадцати минутах превышение над
**одновременной кросс-секцией** составляет 11.4 б.п. при цикле издержек
11.7–14.8. То есть эффект есть, он реален и он ровно на грани
окупаемости. Замечание владельца: если это тот самый краткосрочный
возврат, торговать его надо быстро — входить сразу после падения и
выходить как можно раньше.

L3 короче пяти минут не мерил вовсе: сетка набора `metrics` пятиминутна.
Здесь сетка минутная, а условие на открытый интерес снято за
ненадобностью — L3 показал, что оно вычитает.

Три вопроса
-----------

1. **Растёт ли превышение при укорочении горизонта.** Если да,
   направление живо; если оно плоское или падает, быстрая торговля
   ничего не добавляет, а издержки платятся те же.
2. **Переживает ли эффект задержку входа.** Вход откладывается на 1, 2
   и 5 минут после сигнала. Эффект, исчезающий от минуты задержки, не
   торгуется: столько занимает решение и отправка заявки.
3. **Не микроструктура ли это.** Главная ловушка минутных горизонтов.
   Цена скачет между спросом и предложением, и на трейдовых ценах это
   даёт **ложный возврат**, растущий по мере укорочения горизонта.
   Подпись у него та же, что у настоящего эффекта, и различить их можно
   только задержкой входа и сравнением с ценой круга.

Всё меряется **сверх одновременной кросс-секции**, а не сверх
безусловного сноса. Это главный урок L3: из сорока трёх базисных
пунктов сырого отскока сорок принадлежали рынку.

    .venv/bin/python research/probe_reversal/probe.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
import data as D                                          # noqa: E402
import events as E                                        # noqa: E402

STEP_MIN = 1                      # минутная сетка
STEP_SEC = 60
WINDOW_MIN = 15                   # окно, за которое меряется падение
MOVES = (0.02, 0.03, 0.05)        # параметры обзора, не критерии
DELAYS = (0, 1, 2, 5)             # задержка входа после сигнала, минуты
HORIZONS = (1, 2, 3, 5, 10, 15, 30, 60)
MIN_CROSS = 20                    # меньше — кросс-секция не считается


def grid(start, end):
    t0 = int(datetime.fromisoformat(start).replace(
        tzinfo=timezone.utc).timestamp())
    t1 = int(datetime.fromisoformat(end).replace(
        tzinfo=timezone.utc).timestamp()) + 86_400 - STEP_SEC
    return np.arange(t0, t1 + STEP_SEC, STEP_SEC, dtype=np.int64)


def month_bounds(mon):
    y, m = (int(x) for x in mon.split("-"))
    a = datetime(y, m, 1, tzinfo=timezone.utc)
    b = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
    return a.date().isoformat(), (b - timedelta(days=1)).date().isoformat()


def taker_bp(symbols):
    """Посимвольная тейкерская ставка из A1. Ставка не одно число."""
    path = os.path.join(RESEARCH, "a1_universe", "out", "fees.json")
    fees = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        src = doc.get("fees", doc) if isinstance(doc, dict) else {}
        for k, v in (src.items() if isinstance(src, dict) else []):
            if isinstance(v, dict):
                t = v.get("taker_fee_bp", v.get("takerFeeRate"))
            else:
                t = v
            try:
                t = float(t)
            except (TypeError, ValueError):
                continue
            fees[k] = t * 1e4 if t < 0.01 else t
    uni = D.universe()
    out = {}
    for s in symbols:
        out[s] = fees.get(s, 5.5)
        if s not in fees:
            # Делистнутым ставки не существует — правило R4: берётся
            # модальный тариф, а не молчаливый ноль.
            out[s] = 5.5
    return out


def run_month(mon, nxt, symbols, uni, share, min_share, interval, log):
    """События месяца и всё, что по ним меряется. Возвращает записи."""
    a0, _ = month_bounds(mon)
    _, b1 = month_bounds(nxt or mon)
    times = grid(a0, b1)
    M = D.price_matrix(symbols, times, interval, None,
                       columns=("open", "low", "high"))
    P = M["open"]
    own = len(grid(*month_bounds(mon)))          # индексы своего месяца
    rec = []
    ones = np.ones(len(times), dtype=np.float64)
    for r, sym in enumerate(symbols):
        px = P[r].astype(np.float64)
        ok = (np.isfinite(px)
              & D.delist_mask(sym, times, uni)
              & D.liquidity_mask(sym, times, share, min_share))
        if not ok.any():
            continue
        for move in MOVES:
            idx = E.detect(ones, px, ok, 0.0, move, require_oi=False,
                           step_min=STEP_MIN, window_min=WINDOW_MIN,
                           dedup_min=60)
            idx = idx[idx < own]                 # события только своего месяца
            for j in idx:
                rec.append((r, int(j), move))
    log(f"  {mon}: событий {len(rec)}")
    return rec, M, times


def excursions(M, er, ec, horizons):
    """Насколько далеко цена ушла ПРОТИВ позиции и в её пользу.

    Ход против позиции — это и есть вход для уровня ограничения
    убытка: назначать его на глаз нельзя, а по распределению
    просадки внутри сделки — можно. Считается по минимумам и
    максимумам баров, а не по закрытиям: стоп срабатывает от
    касания, а не от закрытия.
    """
    lo, hi, op = M["low"], M["high"], M["open"]
    entry = op[er, ec]
    n = op.shape[1]
    run_lo = np.full(len(ec), np.inf)
    run_hi = np.full(len(ec), -np.inf)
    out = {}
    for k in range(0, max(horizons) + 1):
        idx = np.clip(ec + k, 0, n - 1)
        fit = (ec + k) < n
        v_lo = np.where(fit, lo[er, idx], np.nan)
        v_hi = np.where(fit, hi[er, idx], np.nan)
        run_lo = np.fmin(run_lo, v_lo)
        run_hi = np.fmax(run_hi, v_hi)
        if k in horizons:
            with np.errstate(invalid="ignore", divide="ignore"):
                out[k] = (run_lo / entry - 1.0,
                          run_hi / entry - 1.0)
    return out


def measure(rec, M, times, log):
    """Превышение над одновременной кросс-секцией по эпизодам."""
    P = M["open"]
    out = {}
    for move in MOVES:
        sel = [(r, j) for r, j, m in rec if m == move]
        if not sel:
            continue
        rows = np.array([r for r, _ in sel], dtype=np.int64)
        cols = np.array([j for _, j in sel], dtype=np.int64)
        for delay in DELAYS:
            ent = cols + delay
            good = ent < P.shape[1]
            if not good.any():
                continue
            er, ec = rows[good], ent[good]
            ep = E.episodes(times[ec])
            banned = E.ban_matrix(P.shape, er, ec, 60, STEP_MIN)
            exc_path = excursions(M, er, ec, set(HORIZONS))
            for h in HORIZONS:
                k = ec + h
                fit = k < P.shape[1]
                with np.errstate(invalid="ignore", divide="ignore"):
                    f = np.where(fit,
                                 P[er, np.clip(k, 0, P.shape[1] - 1)]
                                 / P[er, ec] - 1.0, np.nan)
                cs = E.cross_section(P, ec, er, h, guard_min=60,
                                     step_min=STEP_MIN, banned=banned,
                                     min_cross=MIN_CROSS)
                exc = np.where(np.isfinite(cs) & np.isfinite(f),
                               f - cs, np.nan)
                key = (move, delay, h)
                acc = out.setdefault(key, {"exc": [], "raw": [], "ep": [],
                                           "mae": [], "mfe": []})
                acc["exc"].append(exc)
                acc["raw"].append(f)
                acc["mae"].append(exc_path[h][0])
                acc["mfe"].append(exc_path[h][1])
                acc["ep"].append(ep + (10**7) * len(acc["ep"]))
    return out


def merge(dst, src):
    for k, v in src.items():
        d = dst.setdefault(k, {"exc": [], "raw": [], "ep": [],
                               "mae": [], "mfe": []})
        for name in ("exc", "raw", "ep", "mae", "mfe"):
            d[name] += v[name]
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()

    def log(m):
        print(f"[{time.time() - t0:6.0f} с] {m}", file=sys.stderr, flush=True)

    uni = D.universe()
    have = sorted(s[:-len(".npz")] for s in os.listdir(D.OI_SERIES)
                  if s.endswith(".npz"))
    symbols = [s for s in have if s in uni]
    if a.limit:
        symbols = symbols[:a.limit]
    share, min_share = D.liquid_days(a.interval)
    fee = taker_bp(symbols)
    log(f"символов {len(symbols)}, медианный тейкер "
        f"{np.median(list(fee.values())):.2f} б.п.")

    mons = D.months(a.start, a.end)
    acc = {}
    for i, mon in enumerate(mons):
        nxt = mons[i + 1] if i + 1 < len(mons) else None
        rec, M, times = run_month(mon, nxt, symbols, uni, share,
                                  min_share, a.interval, log)
        if rec:
            acc = merge(acc, measure(rec, M, times, log))
        del M

    rows = []
    for (move, delay, h), v in sorted(acc.items()):
        exc = np.concatenate(v["exc"])
        raw = np.concatenate(v["raw"])
        ep = np.concatenate(v["ep"])
        e = E.by_episode(exc, ep)
        if len(e) < 10:
            continue
        mae = np.concatenate(v["mae"])
        mfe = np.concatenate(v["mfe"])
        mae = mae[np.isfinite(mae)]
        mfe = mfe[np.isfinite(mfe)]
        rows.append({"move": move, "delay": delay, "horizon": h,
                     "episodes": int(len(e)),
                     "events": int(np.isfinite(exc).sum()),
                     "excess_bp": float(np.median(e)) * 1e4,
                     "raw_bp": float(np.median(raw[np.isfinite(raw)])) * 1e4,
                     "share_pos": float(np.mean(e > 0)),
                     "mae_med_bp": float(np.median(mae)) * 1e4 if len(mae) else None,
                     "mae_p10_bp": float(np.percentile(mae, 10)) * 1e4 if len(mae) else None,
                     "mfe_med_bp": float(np.median(mfe)) * 1e4 if len(mfe) else None})

    with open(os.path.join(OUT, f"probe_{a.interval}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"config": {"start": a.start, "end": a.end,
                              "moves": list(MOVES), "delays": list(DELAYS),
                              "horizons": list(HORIZONS),
                              "window_min": WINDOW_MIN,
                              "symbols": len(symbols)}, "rows": rows},
                  f, ensure_ascii=False, indent=1)

    md = ["# Зонд: краткосрочный возврат на минутных горизонтах\n",
          f"Окно {a.start} … {a.end}, символов {len(symbols)}, сетка "
          f"{STEP_MIN} мин. Падение цены за {WINDOW_MIN} минут, условия на "
          "открытый интерес нет — L3 показал, что оно вычитает.\n",
          "Все величины — **превышение над одновременной кросс-секцией**, "
          "по эпизодам. Сравнивать с циклом издержек: тейкер туда-обратно "
          "около **11 б.п.** плюс проскальзывание.\n"]
    for move in MOVES:
        md.append(f"\n## Падение на {move:.0%} за {WINDOW_MIN} минут\n")
        md.append("| Задержка входа | " + " | ".join(f"{h} мин"
                                                     for h in HORIZONS)
                  + " | Эпизодов |")
        md.append("|---" * (len(HORIZONS) + 2) + "|")
        for delay in DELAYS:
            cells, eps = [], 0
            for h in HORIZONS:
                r = next((x for x in rows if x["move"] == move
                          and x["delay"] == delay and x["horizon"] == h), None)
                cells.append(f"{r['excess_bp']:+.1f}" if r else "—")
                eps = max(eps, r["episodes"] if r else 0)
            md.append(f"| +{delay} мин | " + " | ".join(cells)
                      + f" | {eps} |")
        md.append("")
    md.append("\n## Ход против позиции — вход для уровня стопа\n")
    md.append("После входа цена уходит вниз, прежде чем отскочить. "
              "Медиана и 10-й процентиль этого хода говорят, где обязан "
              "стоять ограничитель убытка, чтобы не выбивало на шуме, — "
              "и сколько он будет стоить. Считается по минимумам баров: "
              "стоп срабатывает от касания, а не от закрытия.\n")
    md.append("| Падение | Горизонт | Ход против, медиана | 10-й процентиль "
              "| Ход в пользу, медиана |")
    md.append("|---|---|---|---|---|")
    for move in MOVES:
        for h in HORIZONS:
            r = next((x for x in rows if x["move"] == move
                      and x["delay"] == 0 and x["horizon"] == h), None)
            if not r or r.get("mae_med_bp") is None:
                continue
            md.append(f"| {move:.0%} | {h} мин | {r['mae_med_bp']:+.0f} б.п. "
                      f"| {r['mae_p10_bp']:+.0f} б.п. "
                      f"| {r['mfe_med_bp']:+.0f} б.п. |")
    md.append("")
    md.append("\n## Как читать\n")
    md.append("**Растёт при укорочении горизонта** — подпись микроструктуры, "
              "а не торгуемого эффекта: цена скачет между спросом и "
              "предложением, и на трейдовых ценах это даёт ложный возврат.\n")
    md.append("**Исчезает от задержки в минуту** — не торгуется: столько "
              "занимает решение и отправка заявки.\n")
    md.append("**Держится по горизонтам и переживает задержку** — тогда "
              "есть о чём говорить, и решает сравнение с ценой круга.\n")
    text = "\n".join(md)
    dst = os.path.join(OUT, f"reversal-probe-{a.interval}.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    log(f"записано {dst}")


if __name__ == "__main__":
    main()
