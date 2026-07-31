#!/usr/bin/env python3
"""
M1: сборка матрицы признаков — этап 1 гипотезы 6 (спека 07).

Что делает, простыми словами
----------------------------

Строит одну большую таблицу: строка — «монета в конкретный день»,
колонки — всё, что было известно о ней К КОНЦУ этого дня (признаки), и
то, что случилось ПОСЛЕ (цели обучения). Модель M2 будет учиться
угадывать второе по первому. Всё заглядывающее в будущее здесь смерть,
поэтому каждый признак закрыт тестом «поменяй будущее — прошлое не
шелохнётся».

Два прохода:

1. **Дневная сводка из хранилища A2** — дорогой (читает сотни миллионов
   минутных баров), поэтому по месяцам и с возобновлением: месяц готов —
   пропускается. Закрытие дня — последний бар СО СДЕЛКАМИ (замороженные
   ряды A2: бар без сделок — пропуск, а не наблюдение).
2. **Признаки и цели** — быстрый, из дневной сводки плюс funding
   площадки исполнения плюс открытый интерес. Пересчитывается целиком.

Артефакты несут разрешение в имени (урок R1: сводка без разрешения
молча затиралась прогоном другого):

    out/daily_{interval}/{YYYY-MM}.parquet   — дневная сводка
    out/features_{interval}.parquet          — матрица
    out/m1_summary_{interval}.json           — настройки, покрытие, бюджет
    out/M1-report-{interval}.md              — отчёт

Запуск (авторитетно — на VPS, там 1m и все источники):

    tools/run.sh "M1: матрица признаков" research/m1_features/build.py
    .venv/bin/python research/m1_features/build.py --interval 15m  # песочница
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, RESEARCH)
sys.path.insert(0, HERE)

import features as F                                       # noqa: E402
from common import funding_series as FS                    # noqa: E402
from common import oi_metrics as OM                        # noqa: E402

PARQUET = os.path.join(RESEARCH, "a2_storage", "out", "parquet")
UNIVERSE = os.path.join(RESEARCH, "a1_universe", "out", "universe.json")
FUNDING_DIR = os.path.join(RESEARCH, "a1_universe", "out", "funding")
OI_DIR = os.path.join(RESEARCH, "l2_data", "out", "oi_binance")

START_DEFAULT = "2022-07-01"      # глубина всех гипотез с F1: раньше
                                  # на площадке исполнения не из чего
MIN_HISTORY_DAYS = 365            # требование универсума, как везде
BARS_PER_DAY = {"1m": 1440, "15m": 96}


def connect():
    """duckdb с теми же прагмами, что у liquidity.py, — и по той же
    причине: без явной зоны граница суток зависела бы от машины."""
    import duckdb
    con = duckdb.connect()
    tmp = os.path.join(OUT, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    con.execute(f"PRAGMA temp_directory='{tmp}'")
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    con.execute(f"PRAGMA memory_limit='{int(total / 1024**2 * 0.5)}MB'")
    con.execute("SET TimeZone='UTC'")
    return con


def aggregate_partition(con, path):
    """Дневная сводка одной месячной партиции, arrow-таблицей.

    Закрытие дня — последний бар СО СДЕЛКАМИ. Оборот — только по барам
    со сделками: на замороженном хвосте он и так нулевой, но бар без
    сделок с ненулевым объёмом — признак битой строки, и он обязан
    выпасть, а не попасть (то же правило, что в liquidity.py).
    """
    return con.execute("""
        SELECT symbol,
               CAST(open_time AS DATE)                       AS day,
               arg_max(close, open_time) FILTER (trades > 0) AS close,
               sum(quote_volume)         FILTER (trades > 0) AS turnover,
               count(*)                  FILTER (trades > 0) AS bars_traded
        FROM read_parquet(?)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, [path]).fetch_arrow_table()


def stage1(interval, log):
    """Дневная сводка по всем партициям, с возобновлением по месяцам.

    Готовность месяца — файл на диске с числом строк из манифеста; при
    потерянном манифесте число строк читается из самого файла (признак
    результата — содержимое, а не утверждение: дефект `build.py` A2 и
    манифеста L2 оба были ровно об этом).
    """
    import pyarrow.parquet as pq

    src = os.path.join(PARQUET, interval)
    if not os.path.isdir(src):
        raise SystemExit(f"нет хранилища {src} — авторитетный прогон "
                         f"на VPS; в песочнице доступен только 15m, "
                         f"и только если A2 собран")
    dst = os.path.join(OUT, f"daily_{interval}")
    os.makedirs(dst, exist_ok=True)
    man_path = os.path.join(OUT, f"daily_{interval}_manifest.json")
    man = {}
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)

    con, t0 = None, time.time()
    parts = sorted(f for f in os.listdir(src) if f.endswith(".parquet"))
    done = 0
    for i, fn in enumerate(parts, 1):
        month = fn[:-len(".parquet")]
        out_fn = os.path.join(dst, fn)
        if os.path.exists(out_fn):
            rows = man.get(month)
            if rows is None:
                rows = pq.read_metadata(out_fn).num_rows
                man[month] = rows
            done += 1
            continue
        if con is None:
            con = connect()
        t1 = time.time()
        tbl = aggregate_partition(con, os.path.join(src, fn))
        pq.write_table(tbl, out_fn + ".tmp")
        os.replace(out_fn + ".tmp", out_fn)
        man[month] = tbl.num_rows
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(man, f)
        log(f"  {month}: строк {tbl.num_rows:,}, {time.time() - t1:.1f} с "
            f"({i}/{len(parts)})")
    if con is not None:
        con.close()
    log(f"дневная сводка: месяцев {len(parts)} (готово было {done}), "
        f"{time.time() - t0:.0f} с")
    return dst, {"months": len(parts), "resumed": done,
                 "sec": round(time.time() - t0, 1)}


def load_daily(dst, day0, n_days, symbols):
    """Дневная сводка -> матрицы (символ × день)."""
    import pyarrow.parquet as pq

    idx = {s: i for i, s in enumerate(symbols)}
    close = np.full((len(symbols), n_days), np.nan)
    turn = np.full((len(symbols), n_days), np.nan)
    traded = np.zeros((len(symbols), n_days))
    for fn in sorted(os.listdir(dst)):
        if not fn.endswith(".parquet"):
            continue
        t = pq.read_table(os.path.join(dst, fn))
        sym = t.column("symbol").to_pylist()
        day = t.column("day").to_pylist()
        cl = t.column("close").to_pylist()
        tv = t.column("turnover").to_pylist()
        bt = t.column("bars_traded").to_pylist()
        for s, d, c, v, b in zip(sym, day, cl, tv, bt):
            si = idx.get(s)
            if si is None:
                continue
            di = (d - day0).days
            if 0 <= di < n_days:
                if c is not None:
                    close[si, di] = c
                if v is not None:
                    turn[si, di] = v
                traded[si, di] = b or 0
    return close, turn, traded


def eligibility(universe, assets, day0, n_days):
    """Маска «актив в универсуме в этот день»: класс, возраст, интервал.

    Возраст — от листинга, не меньше года (как во всех гипотезах);
    конец — последний день торговли из универсума. Ликвидность (доля
    минут со сделками за 90 дней) накладывается позже, из самих данных.
    """
    elig = np.zeros((len(assets), n_days), dtype=bool)
    for i, a in enumerate(assets):
        v = universe[a]
        lo = (date.fromisoformat(v["listed"])
              + timedelta(days=MIN_HISTORY_DAYS) - day0).days
        hi = (date.fromisoformat(v["last_trading_day"]) - day0).days
        elig[i, max(0, lo):max(0, min(n_days, hi + 1))] = True
    return elig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m", choices=("1m", "15m"))
    ap.add_argument("--start", default=START_DEFAULT)
    ap.add_argument("--end", default=None)
    ap.add_argument("--tag", default="",
                    help="суффикс артефактов; смоук в git не идёт")
    ap.add_argument("--skip", default="",
                    help="источники, которых нет в этой среде: funding,oi. "
                         "Пропуск ЯВНЫЙ и пишется в сводку — молча собрать "
                         "матрицу без funding значило бы выдать её за полную")
    a = ap.parse_args()
    tag = f"-{a.tag}" if a.tag else ""
    skip = {s for s in a.skip.split(",") if s}
    os.makedirs(OUT, exist_ok=True)
    log = lambda m: print(m, flush=True)                   # noqa: E731
    t_all = time.time()

    with open(UNIVERSE, encoding="utf-8") as f:
        universe = json.load(f)["assets"]

    # Этап 1 — дневная сводка.
    dst, s1 = stage1(a.interval, log)

    # Сетка дней и состав.
    day0 = date.fromisoformat(a.start)
    day1 = (date.fromisoformat(a.end) if a.end
            else datetime.now(timezone.utc).date())
    n_days = (day1 - day0).days + 1
    crypto = {k: v for k, v in universe.items()
              if v.get("asset_class") == "crypto" and v.get("binance_symbol")}
    assets = sorted(crypto)
    symbols = [crypto[k]["binance_symbol"] for k in assets]
    log(f"универсум: {len(assets)} крипто-активов, "
        f"{n_days} дней {day0}…{day1}")

    t2 = time.time()
    close, turn, traded_cnt = load_daily(dst, day0, n_days, symbols)
    traded_share = traded_cnt / float(BARS_PER_DAY[a.interval])
    log(f"матрицы загружены: {time.time() - t2:.0f} с")

    # Универсум на момент времени + ликвидность из самих данных.
    elig = eligibility(crypto, assets, day0, n_days)
    liq = F.trailing_mean(np.where(traded_share > 0, traded_share, np.nan),
                          F.LIQ_WIN, F.LIQ_MIN_DAYS)
    elig &= np.where(np.isfinite(liq), liq, 0.0) >= F.LIQ_SHARE
    elig &= np.isfinite(close)

    # Funding площадки исполнения. Подменять нельзя, молчать нельзя.
    fund_bp = fund_cnt = None
    if "funding" not in skip:
        fund = FS.load_funding(FUNDING_DIR, universe, set(assets))
        if fund is None:
            raise SystemExit(f"нет каталога funding {FUNDING_DIR} — либо "
                             f"прогон на VPS, либо явный --skip funding")
        if len(fund) < FS.MIN_FUNDING_SYMBOLS:
            raise SystemExit(f"funding покрывает {len(fund)} активов — "
                             f"это не покрытие, а обрывок")
        day0_ms = int(datetime(day0.year, day0.month, day0.day,
                               tzinfo=timezone.utc).timestamp() * 1000)
        fund_bp = np.full((len(assets), n_days), np.nan)
        fund_cnt = np.zeros((len(assets), n_days))
        for i, aname in enumerate(assets):
            got = fund.get(aname)
            if got is not None:
                fund_bp[i], fund_cnt[i] = F.funding_daily(
                    got[0], got[1], day0_ms, n_days)
        log(f"funding: рядов {len(fund)}")

    # Открытый интерес (Binance, задержка публикации из замера).
    oi_usd = None
    if "oi" not in skip:
        if not os.path.isdir(OI_DIR):
            raise SystemExit(f"нет каталога интереса {OI_DIR} — либо "
                             f"прогон на VPS, либо явный --skip oi")
        day0_sec = int(datetime(day0.year, day0.month, day0.day,
                                tzinfo=timezone.utc).timestamp())
        oi_usd = np.full((len(assets), n_days), np.nan)
        n_oi = 0
        for i, sym in enumerate(symbols):
            p = os.path.join(OI_DIR, f"{sym}.npz")
            if not os.path.exists(p):
                continue
            with np.load(p) as z:
                oi_usd[i] = F.oi_daily(z["t"], z["oi_usd"], day0_sec, n_days,
                                       lag_sec=OM.PUBLISH_LAG_MIN * 60)
            n_oi += 1
        log(f"открытый интерес: рядов {n_oi}")

    # Возраст листинга — из справочника универсума, а не из матрицы цен:
    # матрица начинается с a.start, и «первый бар в матрице» занизил бы
    # возраст всем, кто листингован раньше окна, причём всем одинаково.
    age_days = np.empty((len(assets), n_days))
    drng = np.arange(n_days, dtype=float)
    for i, aname in enumerate(assets):
        listed = (day0 - date.fromisoformat(crypto[aname]["listed"])).days
        age_days[i] = drng + listed

    # Этап 2 — признаки и цели.
    t3 = time.time()
    feats = F.feature_pack(close, turn, traded_share, elig,
                           fund_bp, fund_cnt, oi_usd, age_days=age_days)
    r = F.daily_returns(close)
    targets, fwd_raw = {}, {}
    for h in F.HORIZONS:
        targets[h], fwd_raw[h] = F.forward_residual(
            close, r, elig, feats["beta"], h)
    log(f"признаки посчитаны: {time.time() - t3:.0f} с")

    # Длинная таблица только по строкам универсума.
    si, di = np.nonzero(elig)
    cols = {"day": np.array([(day0 + timedelta(days=int(d))).isoformat()
                             for d in di]),
            "asset": np.array([assets[i] for i in si])}
    for name in sorted(feats):
        cols[name] = feats[name][si, di]
    for h in F.HORIZONS:
        cols[f"target_{h}"] = targets[h][si, di]
        cols[f"fwd_{h}"] = fwd_raw[h][si, di]

    import pyarrow as pa
    import pyarrow.parquet as pq
    feat_path = os.path.join(OUT, f"features_{a.interval}{tag}.parquet")
    pq.write_table(pa.table(cols), feat_path + ".tmp")
    os.replace(feat_path + ".tmp", feat_path)

    # Покрытие: доля заполненных значений у каждого признака среди строк
    # универсума. Признак с дырой в половину строк должен быть виден
    # числом ДО обучения, а не удивлять после.
    n_rows = len(si)
    coverage = {k: round(float(np.mean(np.isfinite(cols[k]))), 4)
                for k in cols if k not in ("day", "asset")}
    sections = int(np.sum(elig.sum(axis=0) >= F.MIN_SECTION))
    per_year = {}
    years = np.array([d[:4] for d in cols["day"]])
    for y in sorted(set(years)):
        per_year[y] = int(np.sum(years == y))

    # Бюджет M2, нижняя граница: гребневая регрессия на всей матрице.
    # Наш бустинг будет дороже; его цену M2 меряет своим смоуком ДО
    # полной сетки. Здесь — масштаб задачи числом.
    fnames = sorted(feats)
    X = np.column_stack([cols[k] for k in fnames])
    y = cols[f"target_{F.HORIZONS[0]}"]
    ok = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
    t4 = time.time()
    if ok.sum() > 1000:
        Xs = (X[ok] - X[ok].mean(0)) / (X[ok].std(0) + 1e-12)
        A_ = Xs.T @ Xs + np.eye(Xs.shape[1]) * 10.0
        np.linalg.solve(A_, Xs.T @ y[ok])
    ridge_sec = round(time.time() - t4, 2)

    summary = {
        "interval": a.interval, "tag": a.tag,
        "start": a.start, "end": day1.isoformat(),
        "skip": sorted(skip),
        "settings": {"ret_windows": list(F.RET_WINDOWS),
                     "path_windows": list(F.PATH_WINDOWS),
                     "beta": [F.BETA_WIN, F.BETA_MIN],
                     "liq": [F.LIQ_WIN, F.LIQ_MIN_DAYS, F.LIQ_SHARE],
                     "min_history_days": MIN_HISTORY_DAYS,
                     "min_section": F.MIN_SECTION,
                     "horizons": list(F.HORIZONS),
                     "oi_lag_min": OM.PUBLISH_LAG_MIN},
        "rows": n_rows, "assets": int(len(set(cols["asset"]))),
        "days": n_days, "sections": sections,
        "rows_per_year": per_year,
        "features": fnames, "coverage": coverage,
        "complete_rows": int(ok.sum()),
        "budget": {"stage1_sec": s1["sec"], "stage1_resumed": s1["resumed"],
                   "stage2_sec": round(time.time() - t3, 1),
                   "ridge_fit_sec": ridge_sec,
                   "total_sec": round(time.time() - t_all, 1)},
    }
    sum_path = os.path.join(OUT, f"m1_summary_{a.interval}{tag}.json")
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    import report as R
    rep_path = os.path.join(OUT, f"M1-report-{a.interval}{tag}.md")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(R.render(summary))
    log(f"строк {n_rows:,} · активов {summary['assets']} · сечений "
        f"{sections} · полных строк {ok.sum():,}")
    log(f"артефакты: {feat_path}")
    log(f"          {sum_path}")
    log(f"          {rep_path}")


if __name__ == "__main__":
    main()
