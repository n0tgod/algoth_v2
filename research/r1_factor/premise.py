#!/usr/bin/env python3
"""
R1 — прогон: рыночная волна по сетке окон и проверка посылки §8.1.

Спека 03, этап R1. Отвечает на два условия, без выполнения которых
двигаться в R2 нельзя:

    П1  доля дисперсии доходностей, объяснённая волной   ≥ 40 %
    П2  оценка β не зависит от шага бара (1h / 4h / 1d)  разброс ≤ 15 %

П1 — проверка того, что волна вообще является волной. Если общая
компонента объясняет пятую часть движения, хеджировать об неё нечего, и
вся конструкция раздела 3 спеки бессмысленна. Это дешёвая проверка
посылки, и стоит она до всякой статистики намеренно.

П2 — эффект Эппса. A4 закрыла его **для β на уровнях цен**: отношение
β(1m)/β(1h) по 300 парам равно 0.999 / 1.000 / 1.001. Оговорка записана
там же дословно: Эппс бьёт по оценкам НА ДОХОДНОСТЯХ. Эта спека считает
именно по доходностям, значит проверка нужна заново и на своих числах.
Если β систематически растёт с укрупнением бара, хедж на мелком шаге
недооценивает экспозицию, и «нейтральная» книга нейтральной не является.

Устройство окна — то же, что в A4 (§6 спеки 02), и это не совпадение:
даты обязаны совпадать, чтобы числа R1 сравнивались с числами A4
напрямую, без оговорок.

    │──── формирование 90 дн ────│─ эмбарго 7 ─│──── торговля 30 ────│

Отличие от A4 в составе активов, и оно намеренное. A4 брала только
активы с надёжной меткой сектора — иначе не из чего строить пару. Волна
же есть свойство рынка, а не размеченной его части, поэтому здесь берётся
весь ликвидный универсум на момент окна. Оба числа докладываются.

Прогон возобновляемый: окно — отдельный файл, готовые пропускаются,
сводка читается с диска. Урок A2: сводка обязана описывать состояние, а
не дельту прогона — иначе перезагрузка VPS молча превращает 78 партиций
в 42.

    python3 premise.py --interval 1m           # вся сетка
    python3 premise.py --at 2025-06-15         # одно окно
    python3 premise.py --report                # сводка по готовым
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
WINDOWS = os.path.join(OUT, "windows")   # + суффикс разрешения, см. windows_dir()

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))

import factor as FA          # noqa: E402
import series as S           # noqa: E402
import pairs as P            # noqa: E402

STEP = "1h"                  # базовый шаг, как в A4 (обоснование — 339ff5e)
COARSER = ("4h", "1d")       # шаги сравнения для П2
FORM_DAYS = 90
TRADE_DAYS = 30              # он же шаг сетки
GRID_START = "2022-07-01"
GRID_END = "2026-06-01"

MIN_ASSETS = 10              # окно тоньше — волна не определена

# Пороги §8.1. Здесь они только докладываются: решение принимает сводка,
# а не отдельное окно.
P1_MIN_EXPLAINED = 0.40
P2_MAX_SPREAD = 0.15


def windows_dir(interval):
    """Окна тоже раскладываются по разрешению.

    Иначе возобновление прогона подхватило бы окна, посчитанные на
    другом разрешении, и сводка описала бы смесь двух прогонов, ничем
    себя не выдав.
    """
    return f"{WINDOWS}_{interval}"


def window_dates(start, end, step_days):
    t, last = date.fromisoformat(start), date.fromisoformat(end)
    while t <= last:
        yield t.isoformat()
        t += timedelta(days=step_days)


def form_window(at):
    t1 = date.fromisoformat(at)
    return (t1 - timedelta(days=FORM_DAYS)).isoformat(), t1.isoformat()


def fit_at_step(series, step, t0_ms, t1_ms):
    """β, R² и доля объяснённой дисперсии на одном шаге бара."""
    grid, syms, PX = FA.price_grid(series, step, t0_ms, t1_ms)
    if len(grid) < 3:
        return None
    R = FA.log_returns(PX)
    F, F_loo, n_in_bar = FA.market_factor(R)
    fitted = FA.betas(R, F_loo)
    if not fitted:
        return None

    # Смещение от включения себя в собственную волну: то же самое,
    # посчитанное на общей волне. При 300 активах разница обязана быть
    # незаметной, в окне из двадцати — нет. Докладывается числом.
    naive = {j: FA.regress(R[:, j], F)[0] for j, *_ in fitted
             if FA.regress(R[:, j], F) is not None}

    out = {
        "bars": int(len(grid)),
        "assets_fitted": len(fitted),
        "beta": {syms[j]: b for j, b, _, _ in fitted},
        "r2": {syms[j]: r2 for j, _, r2, _ in fitted},
        "beta_own_included": {syms[j]: naive[j] for j, *_ in fitted
                              if j in naive},
        "median_assets_per_bar": float(np.median(n_in_bar[n_in_bar > 0]))
        if (n_in_bar > 0).any() else 0.0,
    }
    r2v = [r2 for _, _, r2, _ in fitted]
    bv = [b for _, b, _, _ in fitted]
    out["r2_median"] = float(np.median(r2v))
    out["r2_mean"] = float(np.mean(r2v))
    out["r2_q"] = FA.quantiles(r2v)
    out["beta_median"] = float(np.median(bv))
    out["beta_q"] = FA.quantiles(bv)

    # Доля дисперсии в агрегате: сумма объяснённой по всем активам к
    # сумме полной. Отличается от среднего R² тем, что её тянут активы
    # с большой дисперсией, — поэтому докладываются обе.
    num = den = 0.0
    for j, _, r2, _ in fitted:
        v = np.nanvar(R[:, j])
        if v == v:
            num += r2 * v
            den += v
    out["r2_aggregate"] = float(num / den) if den > 0 else None
    return out


def run_window(con, at, liq, universe, of_group, interval):
    t_start = time.time()
    st = P.state_at(liq, universe, at)
    live = sorted(a for a, s in st.items()
                  if s["share_traded"] >= P.MIN_SHARE_TRADED)
    t0, t1 = form_window(at)
    row = {"date": at, "form_start": t0, "form_end": t1, "step": STEP,
           "interval": interval, "assets_liquid": len(live)}

    if len(live) < MIN_ASSETS:
        row["skipped"] = "мало активов"
        row["seconds"] = round(time.time() - t_start, 1)
        return row

    row["assets_labelled"] = sum(1 for a in live if a in of_group)

    symbols = [universe[a]["binance_symbol"] for a in live
               if universe[a].get("binance_symbol")]
    raw = S.load(con, symbols, t0, t1, step=STEP, interval=interval)
    if not raw:
        row["skipped"] = "нет рядов"
        row["seconds"] = round(time.time() - t_start, 1)
        return row

    t0_ms = int(np.datetime64(t0 + "T00:00:00", "ms").astype("int64"))
    t1_ms = int(np.datetime64(t1 + "T00:00:00", "ms").astype("int64"))

    # Шаг 1h читается из хранилища, крупные получаются пересчётом уже
    # загруженного: перечитывать те же три месяца по всему универсуму
    # ради 4h и 1d стоит минуту на шаг и ничего не добавляет.
    by_step = {STEP: raw}
    for c in COARSER:
        by_step[c] = {s: S.resample(t, px, c) for s, (t, px) in raw.items()}

    fits = {}
    for step, ser in by_step.items():
        f = fit_at_step(ser, step, t0_ms, t1_ms)
        if f is not None:
            fits[step] = f

    if STEP not in fits:
        row["skipped"] = "не удалось оценить на базовом шаге"
        row["seconds"] = round(time.time() - t_start, 1)
        return row

    base = fits[STEP]
    row["bars"] = base["bars"]
    row["assets_fitted"] = base["assets_fitted"]
    row["median_assets_per_bar"] = base["median_assets_per_bar"]
    row["r2_median"] = base["r2_median"]
    row["r2_mean"] = base["r2_mean"]
    row["r2_aggregate"] = base["r2_aggregate"]
    row["r2_q"] = base["r2_q"]
    row["beta_median"] = base["beta_median"]
    row["beta_q"] = base["beta_q"]

    # Смещение «включил себя в волну», медиана отношения по активам.
    rat = [base["beta_own_included"][s] / base["beta"][s]
           for s in base["beta"] if s in base["beta_own_included"]
           and abs(base["beta"][s]) > 1e-9]
    row["own_inclusion_beta_ratio_median"] = float(np.median(rat)) if rat else None

    # П2: отношение β на крупном шаге к β на базовом, по активам,
    # оценённым НА ВСЕХ шагах. Иначе сравнивались бы разные выборки, и
    # разница шага перепуталась бы с разницей состава.
    common = set(base["beta"])
    for c in COARSER:
        common &= set(fits.get(c, {}).get("beta", {}))
    row["assets_common_all_steps"] = len(common)
    row["beta_step_ratio"] = {}
    row["r2_by_step"] = {STEP: base["r2_median"]}
    for c in COARSER:
        if c not in fits:
            continue
        row["r2_by_step"][c] = fits[c]["r2_median"]
        rr = [fits[c]["beta"][s] / base["beta"][s] for s in common
              if abs(base["beta"][s]) > 1e-9]
        if rr:
            row["beta_step_ratio"][c] = {
                "median": float(np.median(rr)),
                "q": FA.quantiles(rr),
                "n": len(rr),
            }
    row["seconds"] = round(time.time() - t_start, 1)
    return row


def load_windows(interval):
    """Состояние с диска, а не из дельты прогона (урок A2, правка a51c133)."""
    rows = []
    where = windows_dir(interval)
    if not os.path.isdir(where):
        return rows
    for fn in sorted(os.listdir(where)):
        if fn.endswith(".json"):
            with open(os.path.join(where, fn), encoding="utf-8") as f:
                rows.append(json.load(f))
    return rows


def summarize(rows):
    good = [r for r in rows if "r2_median" in r]
    s = {"windows": len(rows), "windows_measured": len(good)}
    if not good:
        return s

    r2w = [r["r2_median"] for r in good]
    s["explained_variance"] = {
        "median_over_windows": float(np.median(r2w)),
        "min": float(np.min(r2w)), "max": float(np.max(r2w)),
        "q": FA.quantiles(r2w),
        "aggregate_median_over_windows": float(np.median(
            [r["r2_aggregate"] for r in good if r.get("r2_aggregate")])),
        "windows_below_threshold": sum(1 for x in r2w if x < P1_MIN_EXPLAINED),
    }
    s["p1_pass"] = bool(s["explained_variance"]["median_over_windows"]
                        >= P1_MIN_EXPLAINED)

    s["beta_step_ratio"] = {}
    worst = 0.0
    for c in COARSER:
        v = [r["beta_step_ratio"][c]["median"] for r in good
             if r.get("beta_step_ratio", {}).get(c)]
        if not v:
            continue
        m = float(np.median(v))
        s["beta_step_ratio"][c] = {"median_over_windows": m,
                                   "deviation": abs(m - 1.0),
                                   "windows": len(v),
                                   "q": FA.quantiles(v)}
        worst = max(worst, abs(m - 1.0))
    s["beta_step_max_deviation"] = worst
    s["p2_pass"] = bool(worst <= P2_MAX_SPREAD)

    s["assets"] = {
        "liquid_median": float(np.median([r["assets_liquid"] for r in good])),
        "fitted_median": float(np.median([r["assets_fitted"] for r in good])),
        "labelled_median": float(np.median(
            [r.get("assets_labelled", 0) for r in good])),
        "min_fitted": int(np.min([r["assets_fitted"] for r in good])),
    }
    own = [r["own_inclusion_beta_ratio_median"] for r in good
           if r.get("own_inclusion_beta_ratio_median")]
    if own:
        s["own_inclusion_beta_ratio"] = {
            "median_over_windows": float(np.median(own)),
            "max": float(np.max(own)),
        }
    s["premise_pass"] = bool(s["p1_pass"] and s["p2_pass"])
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m", help="разрешение хранилища A2")
    ap.add_argument("--at", help="одно окно")
    ap.add_argument("--rerun", action="store_true", help="пересчитать готовые")
    ap.add_argument("--report", action="store_true", help="только сводка")
    args = ap.parse_args()

    where = windows_dir(args.interval)
    os.makedirs(where, exist_ok=True)
    if not args.report:
        liq, universe = P.load_liquidity(args.interval)
        of_group = P.load_groups()[1]
        con = S.connect()
        dates = [args.at] if args.at else list(
            window_dates(GRID_START, GRID_END, TRADE_DAYS))
        for i, at in enumerate(dates, 1):
            path = os.path.join(where, f"{at}.json")
            if os.path.exists(path) and not args.rerun:
                continue
            row = run_window(con, at, liq, universe, of_group,
                             args.interval)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(row, f, ensure_ascii=False, indent=1)
            print(f"  {i}/{len(dates)} {at}: активов {row.get('assets_fitted', 0)}"
                  f", R² медиана {row.get('r2_median', float('nan')):.3f}"
                  f", {row['seconds']} с", file=sys.stderr, flush=True)

    rows = load_windows(args.interval)
    s = summarize(rows)
    # Настройки прогона идут в артефакт, а не читаются отчётом из кода.
    # Во-первых, отчёт тогда описывает тот прогон, который этот файл
    # породил, а не текущее состояние исходников. Во-вторых, сборка
    # отчёта перестаёт зависеть от numpy и duckdb: имея JSON, отчёт
    # делается где угодно.
    config = {"step": STEP, "coarser": list(COARSER), "form_days": FORM_DAYS,
              "trade_days": TRADE_DAYS, "grid_start": GRID_START,
              "grid_end": GRID_END, "min_assets": MIN_ASSETS,
              "interval": args.interval,
              "p1_min_explained": P1_MIN_EXPLAINED,
              "p2_max_spread": P2_MAX_SPREAD}
    # Имя несёт разрешение хранилища: 15m и 1m — два независимых
    # прогона, и они служат перекрёстной проверкой друг другу. Общее имя
    # означало бы, что второй молча затирает первый, а сравнивать станет
    # нечего. В A2 это сделано правильно (build_15m.json / build_1m.json),
    # здесь перенести забыли — и 1m действительно затёр 15m.
    name = f"premise_summary_{args.interval}.json"
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump({"config": config, "summary": s, "windows": rows}, f,
                  ensure_ascii=False, indent=1)
    print(json.dumps(s, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
