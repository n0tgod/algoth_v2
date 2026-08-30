#!/usr/bin/env python3
"""Проверки зонда корреляции: мера, исключение себя, причинность,
сквозная дорога до машины суда с подсаженным навыком."""
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import corr_probe as CP                                   # noqa: E402

FAILED = []


def check(name, cond, note=""):
    print(("ok  " if cond else "ПРОВАЛ") + " " + name
          + ("" if cond else f" · {note}"))
    if not cond:
        FAILED.append(name)


def synth_returns(n_names=40, n_days=260, seed=11):
    """Доходности: имя 0 — клон рынка, имя 1 — независимое, имя 2 —
    зеркало рынка. Рынок — общий фактор остальных имён."""
    rng = np.random.default_rng(seed)
    f = rng.normal(scale=0.02, size=n_days)
    r = np.empty((n_names, n_days))
    for i in range(n_names):
        r[i] = f + rng.normal(scale=0.02, size=n_days)
    r[0] = f + rng.normal(scale=0.001, size=n_days)
    r[1] = rng.normal(scale=0.02, size=n_days)
    r[2] = -f + rng.normal(scale=0.001, size=n_days)
    return r


def test_corr_math_and_self_exclusion():
    r = synth_returns()
    ws, wc = np.nansum(r, axis=0), np.isfinite(r).sum(axis=0)
    q = np.array([len(r[0]) - 1])
    c_clone = CP.corr_series(r[0], ws, wc, q)[0]
    c_indep = CP.corr_series(r[1], ws, wc, q)[0]
    c_anti = CP.corr_series(r[2], ws, wc, q)[0]
    check("клон рынка — корреляция около единицы", c_clone > 0.9,
          str(c_clone))
    check("независимое имя — около нуля", abs(c_indep) < 0.35,
          str(c_indep))
    check("зеркало рынка — около минус единицы", c_anti < -0.9,
          str(c_anti))
    # Исключение себя (замер R1: включение себя завышает связь).
    # Независимое имя с ОГРОМНОЙ σ доминирует в сумме: волна с собой —
    # почти оно само, корреляция дутая; без себя — около нуля.
    # «С собой» получается подстановкой (Σ + r₁, cnt + 1): формула
    # (Σ + r₁ − r₁)/(cnt + 1 − 1) = Σ/cnt — среднее, несущее себя.
    rng = np.random.default_rng(3)
    dom = np.array([rng.normal(scale=0.02, size=r.shape[1])
                    for _ in range(CP.MIN_WAVE + 2)])
    dom[1] = rng.normal(scale=1.0, size=r.shape[1])
    wsd, wcd = np.nansum(dom, axis=0), np.isfinite(dom).sum(axis=0)
    ours = CP.corr_series(dom[1], wsd, wcd, q)[0]
    with_self = CP.corr_series(dom[1], wsd + dom[1], wcd + 1, q)[0]
    check("без себя связь честная (около нуля у независимого)",
          abs(ours) < 0.35, str(ours))
    check("с собой связь дутая — исключение себя обязательно",
          with_self - abs(ours) > 0.4,
          f"{ours} против {with_self}")


def test_causality_and_min_window():
    r = synth_returns()
    ws, wc = np.nansum(r, axis=0), np.isfinite(r).sum(axis=0)
    d = 150
    base = CP.corr_series(r[1], ws, wc, np.array([d]))[0]
    # Будущее переписано целиком — значение в день d не шелохнулось.
    r2 = r.copy()
    r2[:, d + 1:] = np.random.default_rng(5).normal(
        scale=0.05, size=r2[:, d + 1:].shape)
    ws2, wc2 = np.nansum(r2, axis=0), np.isfinite(r2).sum(axis=0)
    after = CP.corr_series(r2[1], ws2, wc2, np.array([d]))[0]
    check("переписанное будущее не меняет состояние",
          abs(after - base) < 1e-12, f"{base} против {after}")
    # Отрицательный контроль теста: правка ВНУТРИ окна обязана менять.
    r3 = r.copy()
    r3[1, d - 10:d] = 0.5
    ws3, wc3 = np.nansum(r3, axis=0), np.isfinite(r3).sum(axis=0)
    inside = CP.corr_series(r3[1], ws3, wc3, np.array([d]))[0]
    check("правка внутри окна меняет состояние (тест кусается)",
          abs(inside - base) > 1e-6, str(inside))
    # Меньше CORR_MIN конечных пар — меры нет, а не ноль.
    r4 = r.copy()
    r4[1, :d - CP.CORR_MIN + 20] = np.nan
    r4[1, d - CP.CORR_MIN + 20:d - 30] = np.nan
    short = CP.corr_series(r4[1], np.nansum(r4, axis=0),
                           np.isfinite(r4).sum(axis=0),
                           np.array([d]))[0]
    check("короткое окно — NaN, не ноль", not np.isfinite(short),
          str(short))
    # Тонкая волна (меньше MIN_WAVE чужих) — пары не существует.
    r5 = r[:CP.MIN_WAVE].copy()          # чужих ровно MIN_WAVE−1
    thin = CP.corr_series(r5[1], np.nansum(r5, axis=0),
                          np.isfinite(r5).sum(axis=0), np.array([d]))[0]
    check("волна тоньше порога — состояния нет",
          not np.isfinite(thin), str(thin))


def _daily_dir(root, syms, days, close):
    """Дневная сводка на диске — той же формы, что пишет M1."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = os.path.join(root, "daily")
    os.makedirs(d)
    rows = {"symbol": [], "day": [], "close": []}
    for i, s in enumerate(syms):
        for j, dy in enumerate(days):
            if np.isfinite(close[i, j]):
                rows["symbol"].append(s)
                rows["day"].append(dy)
                rows["close"].append(float(close[i, j]))
    pq.write_table(pa.table(rows), os.path.join(d, "2025-01.parquet"))
    return d


def test_judge_road_finds_planted_and_stays_silent():
    """Сквозная дорога: файлы → колонка → машина суда.

    Навык подсажен ТОЛЬКО в верхнюю треть по корреляции — зонд обязан
    найти и указать треть 2; на ровном навыке обязан молчать. Дорога
    настоящая: карта актив→символ, чтение сводки с диска, выравнивание
    по строкам — сквозной тест W3 однажды подменил её целиком и дыру
    не исполнял.
    """
    rng = np.random.default_rng(23)
    n, t = 60, 260
    f = rng.normal(scale=0.02, size=t)
    load = np.linspace(0.0, 1.5, n)      # разная связь с рынком
    r = np.array([load[i] * f + rng.normal(scale=0.02, size=t)
                  for i in range(n)])
    close = 100.0 * np.exp(np.cumsum(r, axis=1))
    days = [f"2025-01-{d1:02d}" if d1 <= 31 else f"2025-{2 + (d1 - 32) // 28:02d}-{(d1 - 32) % 28 + 1:02d}"
            for d1 in range(1, t + 1)]
    # календарь честный не нужен: сетка дней — упорядоченные строки
    days = [f"2025-{1 + i // 28:02d}-{i % 28 + 1:02d}" for i in range(t)]
    syms = [f"A{i:02d}USDT" for i in range(n)]
    assets = [f"A{i:02d}" for i in range(n)]
    uni = {s: {"asset": a} for s, a in zip(syms, assets)}
    root = tempfile.mkdtemp()
    try:
        dd = _daily_dir(root, syms, days, close)
        q_days = days[CP.CORR_W + 10:t - 6]
        col_asset, col_day, fwd, pred = [], [], [], []
        rng2 = np.random.default_rng(29)
        for dy in q_days:
            j = days.index(dy)
            fut = rng2.normal(size=n)
            p = rng2.normal(size=n)
            top = load > 1.0              # верхняя треть по связи
            p[top] = fut[top] + rng2.normal(scale=0.1,
                                            size=int(top.sum()))
            col_asset += assets
            col_day += [dy] * n
            fwd += list(fut)
            pred += list(p)
        cols = {"asset": np.array(col_asset), "day": np.array(col_day),
                "fwd_5": np.array(fwd)}
        corr = CP.build_corr_column(cols, dd, log=lambda m: None,
                                    uni=uni)
        check("колонка заполнена по большинству строк",
              np.isfinite(corr).mean() > 0.8,
              f"{np.isfinite(corr).mean():.2f}")
        # выравнивание: у клона рынка корреляция выше, чем у нулевого
        hi = corr[np.array(col_asset) == assets[-1]]
        lo = corr[np.array(col_asset) == assets[0]]
        check("выравнивание: связь растёт с заложенной нагрузкой",
              np.nanmedian(hi) > np.nanmedian(lo) + 0.3,
              f"{np.nanmedian(lo):.2f} против {np.nanmedian(hi):.2f}")
        cols["mkt_corr"] = corr
        rows, n_days = CP.judge(cols, np.array(pred), "fwd_5",
                                log=lambda m: None)
        r1 = rows[0]
        check("подсаженный навык найден и указана верхняя треть",
              r1["wider"] > 0.8 and r1["top_bin"] == 2,
              str((r1["wider"], r1["top_bin"], r1["bins"])))
        # ровный навык: те же данные, честный прогноз всем
        flat_pred = np.array(fwd) + rng2.normal(scale=0.9,
                                                size=len(fwd))
        rows2, _ = CP.judge(cols, flat_pred, "fwd_5",
                            log=lambda m: None)
        r2 = rows2[0]
        check("на ровном навыке зонд молчит",
              0.3 < r2["wider"] < 0.7 and r2["top_share"] < 0.5,
              str((r2["wider"], r2["top_share"])))
        # отчёт: обе ветки владельца названы, вывод из чисел
        rep = CP.write_report(
            os.path.join(root, "r.md"),
            [("vectors_h5_day.npz", rows, n_days)],
            {"when": "тест"})
        txt = open(rep, encoding="utf-8").read()
        check("обе ветки владельца названы в таблице",
              "своей жизнью" in txt and "скоррелированные" in txt)
        check("вывод выведен из чисел (верхняя треть)",
              "верхняя треть" in txt, txt[-400:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (test_corr_math_and_self_exclusion,
             test_causality_and_min_window,
             test_judge_road_finds_planted_and_stays_silent)
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
