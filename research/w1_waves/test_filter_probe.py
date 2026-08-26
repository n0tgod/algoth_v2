#!/usr/bin/env python3
"""Проверки волнового фильтра.

Две обязательные стороны. Причинность: состояние в момент t строится
только из ПОДТВЕРЖДЁННЫХ к t разворотов и не меняется от будущего —
вершина без подтверждения не существует, и фильтр по ней был бы
заглядыванием ровно того рода, каким жива волновая разметка. И
калибровка: подсаженная неоднородность навыка обязана находиться
машиной суда, а на ровном навыке доля «шире случайного» обязана стоять
у половины — иначе «фильтр ничего не даёт» неотличимо от «мера
сломана».
"""

import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import filter_probe as FP                                  # noqa: E402
import waves as W                                          # noqa: E402
from test_grammar import build                             # noqa: E402
from test_waves import check, FAILED                       # noqa: E402

THETA = 0.03


def test_state_is_causal_and_confirmation_gated():
    """Будущее состояния не меняет; неподтверждённая вершина не видна."""
    x = build([0.10, 0.04, 0.16, 0.05, 0.08], tail=0.05)
    piv = W.zigzag(x, THETA)
    # Момент МЕЖДУ вершиной и её подтверждением: вершина уже случилась,
    # но знать о ней нельзя.
    ip, ic, _ = piv[-1]
    t = (ip + ic) // 2
    check("между вершиной и подтверждением есть зазор", ic > ip + 1,
          f"{ip}..{ic}")
    st = FP.wave_states(x, THETA, [t])
    st_conf = FP.wave_states(x, THETA, [ic])
    prev_leg_sz = 0.05                    # нога, завершённая ДО вершины
    check("до подтверждения глубина мерится от СТАРОЙ вершины",
          abs(st["wv_depth"][0] * prev_leg_sz
              - abs(x[t] - x[piv[-2][0]])) < 1e-9,
          str(st["wv_depth"][0]))
    check("после подтверждения база сменилась",
          not np.isclose(st["wv_depth"][0], st_conf["wv_depth"][0]))
    # Будущее взбесилось — состояние в t не шелохнулось.
    y = x.copy()
    y[t + 1:] = y[t + 1] + np.linspace(0, 5.0, len(y) - t - 1)
    st2 = FP.wave_states(y, THETA, [t])
    same = all(np.isclose(st[k][0], st2[k][0], equal_nan=True)
               for k, _ in FP.WAVE_REGIMES)
    check("будущее состояния не меняет", same,
          str({k: (st[k][0], st2[k][0]) for k, _ in FP.WAVE_REGIMES}))


def test_state_numbers_by_hand():
    """Числа состояния сходятся с карандашом, знак — с направлением."""
    x = build([0.10, 0.04, 0.16, 0.05, 0.08], tail=0.05)
    piv = W.zigzag(x, THETA)
    lg = W.legs(x, piv, max_gap=W.MAX_GAP)
    ip, ic, d = piv[-1]                   # последняя вершина — топ 0.25
    t = min(ic + 4, len(x) - 1)
    st = FP.wave_states(x, THETA, [t])
    leg = lg[-1]
    raw = x[t] - leg["px_to"]
    check("глубина — ход от вершины в долях её ноги",
          abs(st["wv_depth"][0] - abs(raw) / leg["size"]) < 1e-9)
    check("знак хода — по направлению ТЕКУЩЕЙ ноги (после топа — вниз)",
          st["wv_dir_move"][0] > 0 and raw < 0,
          str((st["wv_dir_move"][0], raw)))
    check("откат предыдущей ноги — ratio завершённой",
          abs(st["wv_prev_ratio"][0] - lg[-1]["ratio"]) < 1e-9)
    check("правила импульса посчитаны числом 0–3",
          st["wv_imp_rules"][0] in (0.0, 1.0, 2.0, 3.0),
          str(st["wv_imp_rules"][0]))
    check("зрелость ноги неотрицательна", st["wv_leg_age"][0] >= 0)


def test_stale_price_gives_no_state():
    """Протухшая цена — не состояние: дыра длиннее MAX_GAP даёт NaN.

    Хвост ряда взят длинным нарочно: первая версия фикстуры кончалась
    раньше, чем набиралась дыра, `min(…, len-1)` молча обрезал момент
    запроса до свежей цены — и проверка проверяла свежую цену, а не
    протухшую. Момент обязан помещаться в ряд, и это утверждается, а
    не подразумевается.
    """
    x = build([0.10, 0.04, 0.16, 0.05, 0.08], tail=0.12)
    piv = W.zigzag(x, THETA)
    ic = piv[-1][1]
    t = ic + W.MAX_GAP + 3
    check("момент запроса помещается в ряд", t < len(x),
          f"{t} при длине {len(x)}")
    y = x.copy()
    y[ic + 2:t + 1] = np.nan
    st = FP.wave_states(y, THETA, [t])
    check("все пять состояний — пропуск",
          all(not np.isfinite(st[k][0]) for k, _ in FP.WAVE_REGIMES),
          str({k: st[k][0] for k, _ in FP.WAVE_REGIMES}))


def test_day_hour_maps_to_the_last_hour_of_the_day():
    """День решения — открытие его ПОСЛЕДНЕГО часа, числом."""
    from datetime import datetime, timezone
    g0 = int(datetime(2022, 7, 1, tzinfo=timezone.utc).timestamp())
    check("первый день — час 23", FP.day_hour("2022-07-01", g0) == 23)
    check("второй день — час 47", FP.day_hour("2022-07-02", g0) == 47)


def synth_judge(hetero, n_days=120, n_names=90, seed=5):
    """Матрица-фикстура для машины суда: навык либо ровный, либо
    сосредоточен в верхней трети волнового состояния."""
    rng = np.random.default_rng(seed)
    day, sym, wv, pred, fwd = [], [], [], [], []
    for d in range(n_days):
        sig = rng.normal(size=n_names)
        v = rng.normal(size=n_names)
        noise = rng.normal(size=n_names)
        top = v > np.quantile(v, 2 / 3)
        if hetero:
            f = np.where(top, sig * 1.0 + noise * 0.4,
                         noise)
        else:
            f = sig * 0.4 + noise
        day += [f"2025-{d // 28 + 1:02d}-{d % 28 + 1:02d}"] * n_names
        sym += [f"S{i}" for i in range(n_names)]
        wv += list(v)
        pred += list(sig)
        fwd += list(f)
    cols = {"day": np.array(day), "symbol": np.array(sym),
            "fwd_5": np.array(fwd), "wv_depth": np.array(wv)}
    for k, _ in FP.WAVE_REGIMES:
        cols.setdefault(k, np.full(len(day), np.nan))
    return cols, np.array(pred)


def test_planted_heterogeneity_is_found_and_flat_skill_is_flat():
    """Суд находит подсаженную неоднородность и молчит на ровной."""
    cols, pred = synth_judge(hetero=True)
    rows, n_days = FP.judge(cols, pred, "fwd_5", log=lambda m: None)
    r = {v["feat"]: v for v in rows}
    check("сечения посчитаны", n_days >= 100, str(n_days))
    check("состояние с неоднородностью найдено",
          "wv_depth" in r, str(list(r)))
    if "wv_depth" in r:
        check("разброс шире случайного почти всегда",
              r["wv_depth"]["wider"] > 0.8, str(r["wv_depth"]["wider"]))
        check("лучшая треть — верхняя, и держится",
              r["wv_depth"]["top_bin"] == 2
              and r["wv_depth"]["top_share"] > 0.6,
              str((r["wv_depth"]["top_bin"], r["wv_depth"]["top_share"])))
    cols0, pred0 = synth_judge(hetero=False)
    rows0, _ = FP.judge(cols0, pred0, "fwd_5", log=lambda m: None)
    r0 = {v["feat"]: v for v in rows0}
    check("на ровном навыке доля у половины",
          "wv_depth" in r0 and 0.3 < r0["wv_depth"]["wider"] < 0.7,
          str(r0.get("wv_depth", {}).get("wider")))


def test_reading_comes_from_the_numbers():
    """Фраза вывода — из чисел: три ветки, и каждая по своему числу."""
    flat = [{"feat": "wv_depth", "name": "x", "wider": 0.46,
             "top_share": 0.35, "top_bin": 0}]
    hot = [{"feat": "wv_depth", "name": "x", "wider": 0.72,
            "top_share": 0.55, "top_bin": 2}]
    check("ровный навык — «торговать реже, а не лучше»",
          "торговать реже" in FP.reading(flat))
    check("неоднородность — «повод для спеки», не вывод",
          "повод для спеки" in FP.reading(hot))
    check("пусто — «не из чего строиться»",
          "не из чего" in FP.reading([]))


def test_main_road_and_publish_gating():
    """Сквозная дорога main: отчёт написан, публикация обеих сторон."""
    said = []
    cols, pred = synth_judge(hetero=False, n_days=60)
    old = (FP.R.load, FP.build_wave_columns, FP.Z.publish, FP.OUT,
           FP.VECTORS)
    d = tempfile.mkdtemp()
    try:
        FP.R.load = lambda m, v, log=None: (cols, pred, "fwd_5")
        FP.build_wave_columns = lambda c, log=FP.log_: {
            k: cols[k] for k, _ in FP.WAVE_REGIMES}
        FP.Z.publish = lambda m: said.append(m)
        FP.OUT = os.path.join(d, "out")
        FP.VECTORS = ("vectors_h5_day.npz",)
        os.makedirs(os.path.join(d, "vec"), exist_ok=True)
        open(os.path.join(d, "vec", "vectors_h5_day.npz"), "wb").close()
        args = ["--vectors-dir", os.path.join(d, "vec"),
                "--matrix", "x", "--tag", "t"]
        FP.main(args + ["--no-publish"])
        p = os.path.join(FP.OUT, "W3-wavefilter-t.md")
        check("отчёт написан", os.path.exists(p))
        check("с ключом публикации нет", not said, str(said))
        FP.main(args)
        check("без ключа публикация случилась", len(said) == 1)
        t = open(p, encoding="utf-8").read()
        check("приор назван в отчёте", "Приор честно отрицательный" in t)
        check("нули названы числом", "0.50" in t and "0.33" in t)
        check("фраза вывода присутствует", "Читается так" in t)
    finally:
        (FP.R.load, FP.build_wave_columns, FP.Z.publish, FP.OUT,
         FP.VECTORS) = old
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = (
        test_state_is_causal_and_confirmation_gated,
        test_state_numbers_by_hand,
        test_stale_price_gives_no_state,
        test_day_hour_maps_to_the_last_hour_of_the_day,
        test_planted_heterogeneity_is_found_and_flat_skill_is_flat,
        test_reading_comes_from_the_numbers,
        test_main_road_and_publish_gating,
    )
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
