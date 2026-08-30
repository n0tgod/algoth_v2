#!/usr/bin/env python3
"""Проверки зонда продолжения сквиза.

Три места, где ошибка была бы невидимой в отчёте: знак направления
(перепутанный знак дал бы таблицу «лонгов после роста», посчитанную по
падениям — числа выглядели бы осмысленно), умолчание `direction=-1`
(сдвиг умолчания молча изменил бы опубликованный L3), и дорога
`measure → rows_for → write_report` (фикстура обязана выглядеть как
живой результат `measure`, поэтому зовётся НАСТОЯЩИЙ `L3.measure`).

    cd /home/user/algoth_v2 && .venv/bin/python \
        research/probe_upcascade/test_up.py
"""

import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import up as U                                            # noqa: E402

E = U.E
L3 = U.L3

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def two_sided_series(n=200):
    """Ряд с ОБОИМИ событиями: падение на 30-м шаге, рост на 120-м;
    интерес падает в обоих случаях (каскад — исчезновение позиций)."""
    oi = np.full(n, 1000.0)
    px = np.full(n, 100.0)
    oi[30:] = 950.0                  # −5 % интереса
    px[30:] = 96.0                   # −4 % цены — каскад ВНИЗ
    oi[120:] = 900.0                 # ещё −5 %
    px[120:] = 100.0                 # +4.2 % от 96 — каскад ВВЕРХ
    return oi, px, np.ones(n, bool)


def test_default_is_down_bit_for_bit():
    """Умолчание — прежний L3: находит падение, игнорирует рост, и
    равно явному direction=-1 поэлементно."""
    oi, px, ok = two_sided_series()
    d_def = E.detect(oi, px, ok, 0.01, 0.03)
    d_m1 = E.detect(oi, px, ok, 0.01, 0.03, direction=-1)
    check("умолчание = direction=-1 бит в бит",
          np.array_equal(d_def, d_m1), f"{d_def} vs {d_m1}")
    check("падение найдено умолчанием", 30 in d_def, str(d_def))
    check("рост умолчанием НЕ найден",
          not any(j >= 120 for j in d_def), str(d_def))


def test_direction_up_mirrors():
    oi, px, ok = two_sided_series()
    d_up = E.detect(oi, px, ok, 0.01, 0.03, direction=+1)
    check("рост найден при direction=+1",
          any(120 <= j < 135 for j in d_up), str(d_up))
    check("падение при direction=+1 НЕ событие",
          30 not in d_up, str(d_up))
    # Рост при РАСТУЩЕМ интересе — не каскад: закрытий позиций нет.
    n = 200
    oi2 = np.full(n, 1000.0)
    px2 = np.full(n, 100.0)
    oi2[120:] = 1100.0
    px2[120:] = 104.0
    d2 = E.detect(oi2, px2, np.ones(n, bool), 0.01, 0.03, direction=+1)
    check("рост при растущем интересе не событие", len(d2) == 0, str(d2))
    d3 = E.detect(oi2, px2, np.ones(n, bool), 0.01, 0.03,
                  require_oi=False, direction=+1)
    check("контроль 2 тот же рост находит",
          any(120 <= j < 135 for j in d3), str(d3))


def test_reference_formula_random():
    """Независимая переформулировка условия на случайных данных:
    d_px ≥ move при direction=+1, d_oi ≤ −drop, тот же дедуп."""
    rng = np.random.default_rng(20260830)
    n = 3000
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    oi = 1e7 * np.exp(np.cumsum(rng.normal(0, 0.008, n)))
    ok = rng.random(n) > 0.05
    got = E.detect(oi, px, ok, 0.01, 0.02, direction=+1)

    w = E.steps(E.WINDOW_MIN)
    d_px = np.full(n, np.nan)
    d_oi = np.full(n, np.nan)
    d_px[w:] = px[w:] / px[:-w] - 1.0
    d_oi[w:] = oi[w:] / oi[:-w] - 1.0
    hit = (np.isfinite(d_px) & np.isfinite(d_oi) & ok
           & (d_px >= 0.02) & (d_oi <= -0.01))
    idx = np.flatnonzero(hit)
    gap = E.steps(E.DEDUP_MIN)
    keep, last = [], -10**9
    for i in idx:
        if i - last >= gap:
            keep.append(i)
            last = i
    want = np.array(keep, dtype=np.int64)
    check("направление +1 совпало с независимой формулой",
          np.array_equal(got, want),
          f"{len(got)} vs {len(want)}")
    check("на случайных данных события есть (тест не пуст)",
          len(want) > 0, str(len(want)))


def test_scan_symbols_passes_direction():
    """Дорога зонда — L3.scan_symbols(direction=+1), а не прямой
    вызов detect: зашитый в run.py −1 не поймал бы ни один тест на
    самом detect."""
    n = 200
    t0 = 1_756_500_000
    times = t0 + np.arange(n) * E.STEP_MIN * 60
    oi, px, _ = two_sided_series(n)
    P = px[None, :].copy()

    D = U.D
    saved = (D.oi_series, D.delist_mask, D.liquidity_mask)
    try:
        D.oi_series = lambda sym, t: (oi, np.full(n, 1e7))
        D.delist_mask = lambda sym, t, uni: np.ones(n, bool)
        D.liquidity_mask = lambda sym, t, share, mn: np.ones(n, bool)
        rec_up, _, _ = L3.scan_symbols(
            ["AAAUSDT"], times, P, {}, None, None, lambda m: None,
            direction=+1)
        rec_dn, _, _ = L3.scan_symbols(
            ["AAAUSDT"], times, P, {}, None, None, lambda m: None)
    finally:
        D.oi_series, D.delist_mask, D.liquidity_mask = saved

    up_ev = [int(c) for c, a in zip(rec_up["col"], rec_up["arm"])
             if a == "event"]
    dn_ev = [int(c) for c, a in zip(rec_dn["col"], rec_dn["arm"])
             if a == "event"]
    check("scan_symbols(+1) находит рост",
          any(120 <= j < 135 for j in up_ev), str(up_ev))
    check("scan_symbols(+1) не находит падение",
          30 not in up_ev, str(up_ev))
    check("scan_symbols по умолчанию — прежний L3 (падение)",
          30 in dn_ev and not any(j >= 120 for j in dn_ev), str(dn_ev))


def synth_measure(direction=+1):
    """НАСТОЯЩИЙ L3.measure на синтетике: 30 символов (кросс-секции
    нужен фон не тоньше min_cross=20 — урок T1), 600 шагов
    пятиминутной сетки, у одного — каскад вверх."""
    n = 600
    t0 = 1_756_500_000
    times = t0 + np.arange(n) * E.STEP_MIN * 60
    rng = np.random.default_rng(7)
    P = 100.0 * np.exp(np.cumsum(
        rng.normal(0, 0.0005, (30, n)), axis=1))
    # Символ 0: рост 4 % за окно на шаге 300, дальше продолжение +1 %.
    P[0, 300:] = P[0, 299] * 1.04
    P[0, 306:] = P[0, 305] * 1.01
    rec = {"row": np.array([0, 0]), "col": np.array([300, 320]),
           "sym": np.array(["AAAUSDT", "AAAUSDT"]),
           "oi_change": np.array([-0.05, -0.02]),
           "price_change": np.array([0.04, 0.031]) * direction,
           "oi_usd": np.array([6e6, 6e6]),
           "arm": np.array(["event", "event"])}
    valid_by_row = {0: np.ones(n, bool)}
    hours = np.array([(t // 3600) % 24 for t in times], dtype=np.int8)
    res = L3.measure(rec, "event", times, P, valid_by_row, hours,
                     lambda m: None)
    return res


def test_rows_and_report():
    res = synth_measure()
    rows = U.rows_for(res)
    check("строки по всем горизонтам",
          len(rows) == len(L3.HORIZONS + L3.DIAGNOSTIC),
          str([r["h"] for r in rows]))
    r15 = next(r for r in rows if r["h"] == 15)
    check("сырой ход измерен", np.isfinite(r15["raw_med"]),
          str(r15))
    check("кросс-секция построена (фон 29 имён)",
          r15["exc_med"] is not None and np.isfinite(r15["exc_med"]),
          str(r15))
    check("эпизоды посчитаны", r15["n_ep"] >= 1, str(r15))
    # Нуль 2 на 600 шагах честно NaN (сдвиг на год за краем ряда):
    # печать обязана давать прочерк, а не выдуманный ноль.
    check("немеряемый нуль 2 печатается прочерком",
          U.fmt_bp(r15["null2"]) == "—", str(r15["null2"]))

    tmp = tempfile.mkdtemp()
    try:
        blocks = [("Подтверждающая",
                   [("событие (рост + падение интереса)", res),
                    ("контроль 2 (рост без условия на интерес)", None)])]
        meta = {"when": "тест", "symbols": 4,
                "start": "2026-08-01", "end": "2026-08-02"}
        p = U.write_report(os.path.join(tmp, "r.md"), blocks, meta)
        txt = open(p, encoding="utf-8").read()
        check("рамка: вторая клетка порога не считается",
              "вторая клетка порога НЕ считается" in txt, txt[:300])
        check("рамка: контроль 2 назван по правилу",
              "рост БЕЗ условия на интерес" in txt, "")
        check("рамка: валовые числа — верхняя граница",
              "верхняя граница" in txt, "")
        check("пустая рука названа, а не нулевая",
              "событий нет" in txt, "")
        body = txt.split("### событие")[1]
        n_rows = sum(1 for ln in body.splitlines()
                     if ln.startswith("| ") and "горизонт" not in ln
                     and "--:" not in ln)
        check("таблица несёт строки числом",
              n_rows == len(L3.HORIZONS + L3.DIAGNOSTIC), str(n_rows))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = (test_default_is_down_bit_for_bit,
             test_direction_up_mirrors,
             test_reference_formula_random,
             test_scan_symbols_passes_direction,
             test_rows_and_report)
    for t in tests:
        print(t.__name__)
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
