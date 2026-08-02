#!/usr/bin/env python3
"""
S8.1, этап 1: запись стакана → почасовая сводка (спека 08 §3, §9).

Зачем двухэтапность — та же арифметика, что в M1. Сырой час одного
символа — тысячи строк JSON с полной лесенкой; признакам из них нужно
полтора десятка чисел. Пересчитывать признаки из сырья при каждом
переобучении значило бы часами жевать одно и то же; сводка считается
по каждому (символ, час) один раз и дописывается по мере закрытия
часов. Возобновление — по содержимому дневного файла, а не по факту
его существования (урок манифеста L2).

Чтение — `b1_book/store.read_hour`: та же функция, что у сборщика,
включая спасение испорченных архивов. Вторая копия разбора здесь
однажды разошлась бы с первой (урок funding-загрузчика).

Цензура полос — из аудита `B1-feature-audit.md`: полоса шире охвата
книги в этом снимке — пропуск, а не число. У BTC различима одна полоса
из четырёх, и без цензуры три колонки несли бы одну величину,
выглядя измерением.

    .venv/bin/python research/s8_loop/summary.py            # дозакрыть всё
    .venv/bin/python research/s8_loop/summary.py --hours-back 48
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))
from book import BANDS                                     # noqa: E402
from store import read_hour                                # noqa: E402

BOOK_ROOT = os.path.join(RESEARCH, "b1_book", "out")
OUT = os.path.join(HERE, "out", "summary")

# Самая узкая полоса, в которой меряется «выедено против показанного»:
# знаменатель — показанная глубина у цены, числитель — агрессия ленты.
EAT_BAND = 0.001


def _med(v):
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def summarize_hour(book_rows, trade_rows, metrics_rows=None,
                   liq_rows=None, hour_end=None):
    """Один (символ, час) → одна строка сводки.

    Все величины — только из этого часа; нормировка на собственное
    прошлое живёт в признаках (этап 2), где прошлое явное и проверяемое
    тестом на заглядывание.

    metrics_rows — опрос тикеров раз в 5 минут (funding, интерес,
    базис), liq_rows — поток ликвидаций. Часы до начала их записи
    честно несут None: пропуск — не ноль (урок A2). Ликвидации при
    живом опросе — наоборот ноль, а не пропуск: «в этот час никого не
    ликвидировали» есть наблюдение, и стирать его в NaN значило бы
    выбросить самые спокойные часы из знаменателя.
    """
    spreads, upds, reaches = [], [], []
    bands = {f"{side}{w}": [] for side in "ba" for w in BANDS}
    best_b, best_a, bigs = [], [], []
    mids = []
    depth_eat = []
    for r in book_rows:
        bid, ask = r.get("bid"), r.get("ask")
        if not bid or not ask:
            continue
        mid = (bid + ask) / 2.0
        mids.append((r.get("t") or 0.0, mid))
        spreads.append((ask - bid) / mid * 1e4)
        upds.append(r.get("upd") or 0)
        reach = min(r.get("reach_b") or 0.0, r.get("reach_a") or 0.0)
        reaches.append(reach)
        for w in BANDS:
            # Цензура: полоса шире охвата книги — пропуск, а не число.
            if reach < w * 1e4:
                continue
            bq, aq = r.get(f"bq{w}"), r.get(f"aq{w}")
            if bq is not None:
                bands[f"b{w}"].append(bq)
            if aq is not None:
                bands[f"a{w}"].append(aq)
        bs, as_ = r.get("bid_sz"), r.get("ask_sz")
        if bs is not None:
            best_b.append(bs * bid)
        if as_ is not None:
            best_a.append(as_ * ask)
        # Крупнейший уровень в пределах ±0.5 % (или охвата, если он уже).
        big = 0.0
        for pside in ("b", "a"):
            for p, q in (r.get(pside) or []):
                if abs(p - mid) / mid <= 0.005:
                    big = max(big, p * q)
        if big > 0:
            bigs.append(big)
        if reach >= EAT_BAND * 1e4:
            bq, aq = r.get(f"bq{EAT_BAND}"), r.get(f"aq{EAT_BAND}")
            if bq is not None and aq is not None:
                depth_eat.append((bq, aq))

    if not mids:
        return None
    mids.sort()
    mvals = [m for _, m in mids]

    buy = sell = 0.0
    n_tr = 0
    per_sec = {}
    hi = lo = None
    for t in trade_rows:
        try:
            notional = float(t["p"]) * float(t["v"])
            side = int(t.get("side") or 0)
            ts = int(t["ts"] // 1000)
        except (KeyError, TypeError, ValueError):
            continue
        n_tr += 1
        if side > 0:
            buy += notional
        else:
            sell += notional
        per_sec[ts] = per_sec.get(ts, 0.0) + notional
        p = float(t["p"])
        hi = p if hi is None else max(hi, p)
        lo = p if lo is None else min(lo, p)

    out = {
        "n_snap": len(mvals),
        "mid_close": mvals[-1],
        "mid_high": max(mvals) if hi is None else max(max(mvals), hi),
        "mid_low": min(mvals) if lo is None else min(min(mvals), lo),
        "spread_bp": _med(spreads),
        "upd": _med(upds),
        "reach_bp": _med(reaches),
        "best_b": _med(best_b), "best_a": _med(best_a),
        "big_med": _med(bigs),
        "big_max": max(bigs) if bigs else None,
        "n_trades": n_tr, "buy": round(buy, 2), "sell": round(sell, 2),
        "vol_max_1s": round(max(per_sec.values()), 2) if per_sec else 0.0,
        "traded_secs": len(per_sec),
        "depth_eat_b": _med([b for b, _ in depth_eat]),
        "depth_eat_a": _med([a for _, a in depth_eat]),
    }

    # --- funding / открытый интерес / базис: последняя точка часа ---
    last = None
    for m in metrics_rows or []:
        try:
            ts = float(m["ts"]) / 1000.0
        except (KeyError, TypeError, ValueError):
            continue
        if last is None or ts >= last[0]:
            last = (ts, m)
    if last is not None:
        m = last[1]
        try:
            out["fr"] = float(m["fr"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            out["oi_usd"] = round(float(m["oiv"]), 2)
        except (KeyError, TypeError, ValueError):
            pass
        try:
            idx_p = float(m["idx"])
            out["basis_bp"] = round(
                (float(m["mark"]) - idx_p) / idx_p * 1e4, 4)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
        if hour_end is not None:
            try:
                out["mins_fund"] = round(
                    (float(m["nft"]) / 1000.0 - hour_end) / 60.0, 1)
            except (KeyError, TypeError, ValueError):
                pass
        # Ликвидации считаются только при живом опросе метрик того же
        # часа: сам по себе пустой поток неотличим от выключенного
        # сборщика, а метрики идут раз в 5 минут и служат пульсом.
        # Сторона по соглашению Bybit: `Buy` — принудительно выкупают
        # ШОРТЫ, `Sell` — принудительно продают ЛОНГИ. Закреплено
        # тестом; перепутать стороны значило бы учить модель наоборот.
        lb = ls = 0.0
        for q in liq_rows or []:
            try:
                notional = float(q["p"]) * float(q["v"])
                side = q["side"]
            except (KeyError, TypeError, ValueError):
                continue
            if side == "Buy":
                lb += notional
            elif side == "Sell":
                ls += notional
        out["liq_short"] = round(lb, 2)
        out["liq_long"] = round(ls, 2)
    for k, v in bands.items():
        out[f"bq_{k}"] = _med(v)
        # Доля снимков, где полоса вообще была измерима, — чтобы
        # отличать «нет глубины» от «нечем было измерить».
        out[f"cov_{k}"] = round(len(v) / len(mvals), 3) if mvals else 0.0
    for k in ("spread_bp", "reach_bp", "best_b", "best_a", "big_med",
              "big_max", "depth_eat_b", "depth_eat_a"):
        if out[k] is not None:
            out[k] = round(out[k], 4 if k.endswith("bp") else 2)
    for k, v in list(out.items()):
        if isinstance(v, float) and not math.isfinite(v):
            out[k] = None
    return out


def hours_closed(now=None, back=None):
    """Часы, уже закрытые записью (текущий не берётся — он пишется)."""
    now = now or time.time()
    n = back or 24 * 365
    end = datetime.fromtimestamp(now, timezone.utc).replace(
        minute=0, second=0, microsecond=0)
    return [(end - timedelta(hours=i)).strftime("%Y-%m-%d-%H")
            for i in range(1, n + 1)]


def done_hours(day_path):
    out = set()
    try:
        with open(day_path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.add(json.loads(line)["hour"])
                except (ValueError, KeyError):
                    continue
    except OSError:
        pass
    return out


def run(root, out_dir, hours_back, log, redo=0):
    """redo — пересвести последние N часов, даже если они уже готовы.

    Нужен ровно при смене состава сводки (добавили metrics/liq): часы,
    сведённые старым кодом, помечены готовыми и сами не обновятся, а
    сырьё для новых полей на диске уже лежит. Строка дописывается в
    конец дневного файла; при сборке матриц поздняя строка того же
    часа побеждает — порядок строк файла хронологичен по дозаписи.
    """
    t0 = time.time()
    book_dir = os.path.join(root, "book")
    try:
        symbols = sorted(os.listdir(book_dir))
    except OSError:
        raise SystemExit(f"нет записи стакана в {book_dir}")
    hours = hours_closed(back=hours_back)
    redo_set = set(hours_closed(back=redo)) if redo else set()
    n_new = n_sym = 0
    said = time.time()
    for si, sym in enumerate(symbols):
        if time.time() - said > 30:
            # Молчащий дольше минуты прогон неотличим от повисшего;
            # на бэклоге один символ со старой записью жуётся минуты.
            log(f"  сводка: {si}/{len(symbols)} символов, "
                f"новых часов {n_new}")
            said = time.time()
        sdir = os.path.join(book_dir, sym)
        have = {f.split(".")[0] for f in os.listdir(sdir)}
        todo = [h for h in hours if h in have]
        if not todo:
            continue
        n_sym += 1
        by_day = {}
        for h in todo:
            by_day.setdefault(h[:10], []).append(h)
        for day, hh in sorted(by_day.items()):
            day_path = os.path.join(out_dir, sym, day + ".jsonl")
            seen = done_hours(day_path)
            fresh = [h for h in hh if h not in seen or h in redo_set]
            if not fresh:
                continue
            os.makedirs(os.path.dirname(day_path), exist_ok=True)
            with open(day_path, "a", encoding="utf-8") as f:
                for h in sorted(fresh):
                    h_end = datetime.strptime(
                        h, "%Y-%m-%d-%H").replace(
                        tzinfo=timezone.utc).timestamp() + 3600
                    row = summarize_hour(
                        read_hour(sdir, h),
                        read_hour(os.path.join(root, "trades", sym), h),
                        read_hour(os.path.join(root, "metrics", sym), h),
                        read_hour(os.path.join(root, "liq", sym), h),
                        hour_end=h_end)
                    if row is None:
                        continue
                    row["hour"] = h
                    f.write(json.dumps(row, separators=(",", ":"))
                            + "\n")
                    n_new += 1
    log(f"сводка: символов с записью {n_sym}, новых часов {n_new}, "
        f"{time.time() - t0:.0f} с")
    return n_new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=BOOK_ROOT)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--hours-back", type=int, default=0,
                    help="0 — вся запись")
    ap.add_argument("--redo", type=int, default=0,
                    help="пересвести последние N часов (смена состава)")
    a = ap.parse_args()
    try:
        # Рядом живёт сборщик, приём данных важнее счёта (правило M5).
        os.nice(10)
    except OSError:
        pass
    run(a.root, a.out, a.hours_back or None,
        lambda m: print(m, flush=True), redo=a.redo)


if __name__ == "__main__":
    main()
