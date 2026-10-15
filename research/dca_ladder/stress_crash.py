#!/usr/bin/env python3
"""Стресс: что делает механика Ladder в затяжном падении — без сигнала.

Вопрос владельца 2026-10-15: «от затяжного падения мы защищены полом и
шорт-стратегиями, разве нет?» Запись стакана у проекта только с августа
2026 — один режим рынка. Минутная история Binance (хранилище A2) есть с
2020 года, и в ней лежат настоящие обвалы. Сигнала модели там нет, зато
механика (структурная лестница, забор плеча, доливы, тейк от плавающей
ТВХ, пол капитуляции, срок 72 ч) от сигнала не зависит — её и меряем.

Как: в каждом окне выбирается `--per-day` СЛУЧАЙНЫХ решений в сутки по
случайным именам из `--symbols` самых оборотных в окне (стейблы и
квартальные контракты прочь); обещание модели (`fav`) берётся из
ЭМПИРИЧЕСКОГО распределения гейтованных ног настоящего листа (кэш
реплея), иначе цель стояла бы не там, где её ставят книги. Исход каждой
позиции — ядром `run_d6.one_position` (та же геометрия и симуляция, что
у бумаги и намерений), раздача кассы — `run_d6.ration` с билетом книги
(`rules.share`), «одна на имя» — `run_d6.one_per_name`, гейт плеча
агрессивной — `rules.min_lev_of`. Ни одной второй копии правила.

Окна объявлены ДО прогона: четыре обвала, два спокойных контроля и
окно самой записи книг (калибровка: случайные входы против настоящего
листа на том же отрезке — сколько даёт сигнал сверх механики). Зёрна
`--seeds`: одна выборка — сам шум.

Что НЕ учтено (и названо): издержки (брутто, как ячейки кассы), тиры
площадки (плоская ставка поддержки 2 %, предел плеча 25×), funding,
бары Binance вместо Bybit, снятые имена в прошлом (универсум окна — то,
что торговалось ТОГДА, по самому хранилищу).

    run research/dca_ladder/stress_crash.py --seeds=3 --per-day=60
"""
import argparse
import bisect
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
sys.path.insert(0, os.path.join(ROOT, "research", "a4_cointegration"))
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import ladder as L                                            # noqa: E402
import rules as R                                             # noqa: E402
import arm_book as AB                                         # noqa: E402

OUT_MD = os.path.join(HERE, "out", "STRESS-crash.md")
OUT_JSON = os.path.join(HERE, "out", "STRESS-crash.json")
HOUR = 3600.0
LEV_CAP = 25.0                      # потолок плеча без тиров (D5 §)

# Окна (UTC): имя, начало, конец, что это. Объявлены до прогона.
WINDOWS = [
    ("обвал 05.2021", "2021-05-01", "2021-06-30", "crash"),
    ("LUNA 05.2022", "2022-05-01", "2022-06-30", "crash"),
    ("FTX 11.2022", "2022-11-01", "2022-12-31", "crash"),
    ("йена 08.2024", "2024-07-15", "2024-09-15", "crash"),
    ("рост 11.2023", "2023-10-15", "2023-12-15", "calm"),
    ("рост 02.2024", "2024-02-01", "2024-03-31", "calm"),
    ("запись книг", "2026-08-04", "2026-10-13", "calib"),
]
BOOKS = ("safe", "optimal", "aggr")
DEPS = (1000.0, 10000.0)
STABLE_PFX = ("USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "EUR", "GBP",
              "AUD", "USD1", "USDE", "USTC", "UST", "AEUR", "XUSD")


def ts_of(day):
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def is_stable(sym):
    base = sym[:-4] if sym.endswith("USDT") else sym
    return base.startswith(STABLE_PFX) or "_" in sym or base.endswith("USD")


# ------------------------------------------------------------ хранилище

def load_window(t0, t1, n_syms, log):
    """Бары окна из A2: `{sym: (ts, o, h, l, c, qv)}` numpy; имена — самые
    оборотные в окне. Край окна расширен на BACK_H назад и срок вперёд."""
    import series as SER
    con = SER.connect()
    a = datetime.fromtimestamp(t0 - (D2.BACK_H + 24) * HOUR, timezone.utc)
    b = datetime.fromtimestamp(t1 + (R.HOLD_H + 2) * HOUR, timezone.utc)
    files = SER.partition_files("1m", a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d"))
    if not files:
        return {}, []
    flist = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
    lo, hi = a.strftime("%Y-%m-%d %H:%M:%S"), b.strftime("%Y-%m-%d %H:%M:%S")
    top = con.execute(f"""
        SELECT symbol, sum(quote_volume) AS qv FROM read_parquet([{flist}])
        WHERE open_time >= TIMESTAMPTZ '{lo}' AND open_time < TIMESTAMPTZ '{hi}'
          AND symbol LIKE '%USDT' AND trades > 0
        GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    syms = [s for s, _ in top if not is_stable(s)][:n_syms]
    out, n_bars = {}, 0
    # по кускам имён: таблица Arrow всего окна разом — гигабайт поверх numpy
    for k in range(0, len(syms), 20):
        slist = ", ".join("'" + s + "'" for s in syms[k:k + 20])
        tbl = con.execute(f"""
            SELECT symbol, open_time, open, high, low, close, quote_volume
            FROM read_parquet([{flist}])
            WHERE symbol IN ({slist}) AND trades > 0
              AND open_time >= TIMESTAMPTZ '{lo}' AND open_time < TIMESTAMPTZ '{hi}'
            ORDER BY 1, 2""").fetch_arrow_table()
        s = tbl.column("symbol").to_numpy(zero_copy_only=False)
        t = tbl.column("open_time").to_numpy(zero_copy_only=False)
        t = t.astype("datetime64[ms]").astype("int64") // 1000
        cols = [tbl.column(c).to_numpy(zero_copy_only=False).astype(np.float64)
                for c in ("open", "high", "low", "close", "quote_volume")]
        del tbl
        if len(s):
            edges = np.flatnonzero(s[1:] != s[:-1]) + 1
            starts = np.concatenate(([0], edges))
            ends = np.concatenate((edges, [len(s)]))
            for i, j in zip(starts, ends):
                out[s[i]] = ((t[i:j].astype(np.float64),)
                             + tuple(np.ascontiguousarray(c[i:j]) for c in cols))
        n_bars += len(s)
    log(f"  хранилище: {len(files)} партиций, имён {len(out)} из {len(top)} "
        f"(стейблы и квартальные прочь), баров {n_bars}")
    return out, [s for s in syms if s in out]


def bars_slice(series, t_a, t_b):
    """Срез ряда символа в [t_a, t_b] списком баров ядра `[t,o,h,l,c,qv]`."""
    ts = series[0]
    i0 = bisect.bisect_left(ts, t_a)
    i1 = bisect.bisect_right(ts, t_b)
    if i1 - i0 < 2:
        return None
    cols = [c[i0:i1].tolist() for c in series]
    return [list(x) for x in zip(*cols)]


def move_of(series, t0, t1):
    """Ход цены за окно долей: закрытие у конца к закрытию у начала."""
    ts = series[0]
    i0 = min(bisect.bisect_left(ts, t0), len(ts) - 1)
    i1 = min(bisect.bisect_right(ts, t1) - 1, len(ts) - 1)
    c = series[4]
    return float(c[i1] / c[i0] - 1.0) if c[i0] > 0 else None


# -------------------------------------------------------------- обещания

def fav_pool(log):
    """Эмпирические (fwd, fav) гейтованных ног настоящего листа."""
    try:
        import run_paper as RP
        cache, why = RP.read_cache()
    except Exception as e:                                    # noqa: BLE001
        cache, why = {}, str(e)
    pool = sorted({(abs(float(r["fwd"])), abs(float(r["fav_bp"])))
                   for r in (cache or {}).values()
                   if r.get("fav_bp") and r.get("fwd")})
    if not pool:
        log(f"  обещаний из кэша нет ({why or 'пусто'}) — одно обещание 50 б.п.")
        pool = [(50.0, 50.0)]
    else:
        f = sorted(x[1] for x in pool)
        log(f"  обещания из кэша реплея: {len(pool)}, медиана {f[len(f) // 2]:.1f} б.п.")
    return pool


def random_legs(syms, t0, t1, per_day, pool, rng):
    days = (t1 - t0) / 86400.0
    n = int(round(per_day * days))
    legs = []
    for _ in range(n):
        at = float(int(rng.uniform(t0, t1 - R.HOLD_H * HOUR) // 60) * 60)
        fwd, fav = rng.choice(pool)
        legs.append({"sym": rng.choice(syms), "at": at, "side": "long",
                     "fwd": fwd, "fav": fav, "adv_q": -fav / D2.MIN_RR,
                     "rr": D2.MIN_RR, "hour": at})
    return legs


# ---------------------------------------------------------------- прогон

def positions(legs, data, book, log):
    cfg = R.RULERS[book]
    look = lambda _n: D2.FLAT_MMR                               # noqa: E731
    lev_look = lambda _n: LEV_CAP                               # noqa: E731
    hold_h = R.hold_of(book)
    out, miss = [], 0
    for i, g in enumerate(legs):
        ser = data.get(g["sym"])
        bars = (bars_slice(ser, g["at"] - D2.BACK_H * HOUR, g["at"] + hold_h * HOUR)
                if ser is not None else None)
        if not bars:
            miss += 1
            continue
        ts = [b[0] for b in bars]
        r = D6.one_position(g, bars, ts, look, cfg["rule"], cfg["param"],
                            hold_h=hold_h, lev_look=lev_look)
        if r is None:
            miss += 1
            continue
        out.append(r)
        if (i + 1) % 1000 == 0:
            log(f"    {book}: {i + 1}/{len(legs)} позиций")
    return out, miss


def book_cells(recs, book):
    ml = R.min_lev_of(book)
    if ml is not None:
        recs = [r for r in recs if float(r["lev"]) >= ml]
    keep, _skip = D6.one_per_name(recs)
    cells = {}
    for dep in DEPS:
        c = D6.ration(keep, R.share(dep, book), deposit=dep,
                      min_notional=R.MIN_NOTIONAL)
        ex = {}
        for r in keep:
            ex[r["exit"]] = ex.get(r["exit"], 0) + 1
        levs = sorted(float(r["lev"]) for r in keep)
        cells[int(dep)] = {"final": c["final"], "max_dd": c["max_dd"],
                           "taken": c["taken"], "no_cash": c["no_cash"],
                           "too_small": c["too_small"],
                           "day_median": c["day_median"], "exits": ex,
                           "lev_median": (levs[len(levs) // 2] if levs else None),
                           "pos_pnl_median": (float(np.median([r["pnl"] for r in keep]))
                                              if keep else None),
                           "floor_share": (sum(1 for r in keep
                                               if r["exit"] in ("пол", "ликвидация"))
                                           / len(keep) if keep else None)}
    return cells


def real_sheet_cells(t0, t1, log):
    """Настоящий лист на том же окне — калибровка (сколько даёт сигнал)."""
    try:
        import run_paper as RP
        import noncrypto_cut as NC
        cache, why = RP.read_cache()
    except Exception as e:                                    # noqa: BLE001
        log(f"  лист книг не прочитан: {e}")
        return None
    if why or not cache:
        log(f"  лист книг не прочитан: {why or 'пуст'}")
        return None
    keys = list(BOOKS)
    by = NC.by_ruler_of(cache, keys, keep=lambda r: t0 <= float(r["at"]) < t1)
    out = {}
    for bk in keys:
        out[bk] = book_cells(by.get(bk) or [], bk)
    return out


def run(a, log):
    t_start = time.time()
    pool = fav_pool(log)
    res = {"per_day": a.per_day, "seeds": a.seeds, "symbols": a.symbols,
           "windows": []}
    for name, d0, d1, kind in WINDOWS:
        if a.only and a.only not in name:
            continue
        t0, t1 = ts_of(d0), ts_of(d1)
        log(f"окно «{name}» {d0}…{d1} ({kind})")
        data, syms = load_window(t0, t1, a.symbols, log)
        if not syms:
            log("  хранилища за окно нет — пропуск")
            res["windows"].append({"name": name, "from": d0, "to": d1, "kind": kind,
                                   "error": "нет хранилища"})
            continue
        btc = move_of(data["BTCUSDT"], t0, t1) if "BTCUSDT" in data else None
        moves = [m for m in (move_of(data[s], t0, t1) for s in syms) if m is not None]
        med_move = float(np.median(moves)) if moves else None
        w = {"name": name, "from": d0, "to": d1, "kind": kind, "btc": btc,
             "median_move": med_move, "symbols": len(syms), "seeds": []}
        for seed in range(a.seeds):
            rng = random.Random(20261015 + seed)
            legs = random_legs(syms, t0, t1, a.per_day, pool, rng)
            cells = {}
            for bk in BOOKS:
                recs, miss = positions(legs, data, bk, log)
                cells[bk] = book_cells(recs, bk)
                cells[bk]["positions"] = len(recs)
                cells[bk]["missing"] = miss
            w["seeds"].append(cells)
            log(f"  зерно {seed}: решений {len(legs)}; "
                + "; ".join(f"{bk} $1k {cells[bk][1000]['final'] * 100:+.1f} % "
                            f"(dd {cells[bk][1000]['max_dd'] * 100:+.1f} %)"
                            for bk in BOOKS)
                + f" ({time.time() - t_start:.0f} с)")
        if kind == "calib":
            w["real"] = real_sheet_cells(t0, t1, log)
        res["windows"].append(w)
        del data
    res["secs"] = round(time.time() - t_start, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


# --------------------------------------------------------------- отчёт

def _p(v):
    return "—" if v is None else f"{v * 100:+.1f} %"


def _rng(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    vals.sort()
    m = vals[len(vals) // 2]
    return f"{_p(m)} ({_p(vals[0])}…{_p(vals[-1])})" if len(vals) > 1 else _p(m)


def report(res):
    L = ["# Ladder в обвале: механика без сигнала — стресс по истории Binance", "",
         f"Случайные входы: {res['per_day']} решений в сутки по {res['symbols']} самым "
         f"оборотным именам окна, {res['seeds']} зёрен; обещание модели — из эмпирического "
         "распределения гейтованных ног настоящего листа. Исход позиции — ядро "
         "`run_d6.one_position` (лестница, забор, доливы, тейк, пол, срок 72 ч), касса — "
         "`run_d6.ration` с билетом книги, «одна на имя», гейт плеча у Gated. "
         "Деньги БРУТТО (без комиссий и funding); тиров нет — ставка поддержки 2 %, "
         "предел плеча 25×; бары Binance. В скобках у медианы — разброс по зёрнам.", ""]
    for w in res["windows"]:
        if w.get("error"):
            L += [f"## {w['name']} ({w['from']}…{w['to']}): {w['error']}", ""]
            continue
        L += [f"## {w['name']} · {w['from']}…{w['to']} · BTC {_p(w['btc'])}, "
              f"медиана имён {_p(w['median_move'])}", "",
              "| книга · депозит | итог | просадка | медиана дня | позиций взято | "
              "доля пол+ликв | плечо (медиана) | выходы |",
              "|---|--:|--:|--:|--:|--:|--:|---|"]
        for bk in BOOKS:
            for dep in DEPS:
                cs = [s[bk][int(dep)] for s in w["seeds"]]
                ex = {}
                for c in cs:
                    for k, v in c["exits"].items():
                        ex[k] = ex.get(k, 0) + v
                n = max(1, len(cs))
                ex_s = ", ".join(f"{k} {v // n}" for k, v in sorted(ex.items(), key=lambda kv: -kv[1]))
                lev = [c["lev_median"] for c in cs if c["lev_median"] is not None]
                L.append(f"| {R.MODE_EN.get(bk, bk) if hasattr(R, 'MODE_EN') else bk} · ${int(dep):,} | "
                         f"{_rng([c['final'] for c in cs])} | {_rng([c['max_dd'] for c in cs])} | "
                         f"{_rng([c['day_median'] for c in cs])} | "
                         f"{int(np.median([c['taken'] for c in cs]))} | "
                         f"{_rng([c['floor_share'] for c in cs])} | "
                         f"{(np.median(lev) if lev else float('nan')):.2f}× | {ex_s} |")
        if w.get("real"):
            L += ["", "Настоящий лист книг на том же окне (тот же счёт, та же касса):", "",
                  "| книга · депозит | итог | просадка | позиций | доля пол+ликв |",
                  "|---|--:|--:|--:|--:|"]
            for bk in BOOKS:
                for dep in DEPS:
                    c = w["real"][bk][int(dep)]
                    L.append(f"| {bk} · ${int(dep):,} | {_p(c['final'])} | {_p(c['max_dd'])} | "
                             f"{c['taken']} | {_p(c['floor_share'])} |")
        L.append("")
    L.append(f"Прогон {res['secs']} с, {res['computed_at']} UTC.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--per-day", type=int, default=60)
    ap.add_argument("--symbols", type=int, default=120)
    ap.add_argument("--only", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    log = AB.guarded(print, limit=2400)
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    res = run(a, log)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "стресс: Ladder в обвале без сигнала"], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
