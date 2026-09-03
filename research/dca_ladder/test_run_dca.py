#!/usr/bin/env python3
"""Тесты чистых помощников реплея D1 — без хранилища A2.

Чтение store и сквозной прогон проверяются смоуком на 15m/1m: store
лежит только на VPS. Здесь — арифметика, где легко ошибиться молча.
Запуск из `.venv/bin/python` (нужен numpy/duckdb для импорта).
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "a4_cointegration"))
import run_dca as R  # noqa: E402


def test_daily_sigma_known():
    # Суточный ряд с известными лог-доходностями: закрытия 100,110,99,…
    # берём по одному бару в сутки (метки на границах суток).
    day = 86_400_000
    t = np.array([0, day, 2 * day, 3 * day, 4 * day], dtype="int64")
    c = np.array([100.0, 105.0, 100.0, 108.0, 100.0])
    r = np.diff(np.log(c))
    sg = R.daily_sigma(t, c)
    assert abs(sg - float(np.std(r))) < 1e-12, (sg, np.std(r))
    print(f"ok  σ суточная = {sg:.4f}")


def test_daily_sigma_takes_last_of_day():
    # Несколько баров в сутки — берётся ПОСЛЕДНЕЕ закрытие суток.
    day = 86_400_000
    t = np.array([0, day // 2, day, 3 * day // 2], dtype="int64")
    c = np.array([100.0, 101.0, 110.0, 111.0])
    # суточные закрытия: 101 (день 0), 111 (день 1) → одна доходность
    sg = R.daily_sigma(t, c)
    assert not np.isfinite(sg)     # одна доходность < 2 → нет σ
    print("ok  σ по последнему закрытию суток, мало точек → нет меры")


def test_slice_window():
    t = np.array([0, 10, 20, 30, 40], dtype="int64")
    c = np.arange(5.0) + 100
    lo = c - 1
    tt, cc, ll = R.slice_window(t, c, lo, 10, 30)
    assert list(tt) == [10, 20], list(tt)
    assert list(cc) == [101.0, 102.0], list(cc)
    print("ok  срез окна по времени [ts0, ts1)")


def test_entry_dates_stride():
    ds = R.entry_dates("2022-07-01", __import__("datetime").date(2022, 8, 10))
    # шаг STRIDE_D=20: 07-01, 07-21, 08-10
    assert [d.isoformat() for d in ds] == \
        ["2022-07-01", "2022-07-21", "2022-08-10"], ds
    print(f"ok  даты входа шагом {R.STRIDE_D}: {len(ds)}")


def test_measures_numbers():
    lad = [0.10, -1.0, 0.05, 0.20]
    hold = [0.05, -1.0, 0.02, 0.0]
    per_day = {"2022-07-01": 0.10, "2022-07-21": -0.50, "2022-08-10": 0.30}
    s = R.measures(lad, hold, liq=1, ruin=1, depth_sum=8, n=4, skipped=2,
                   per_day=per_day, interval="1m", smoke=False, secs=1.0)
    assert abs(s["liq_freq"] - 0.25) < 1e-12
    assert abs(s["ruin_freq"] - 0.25) < 1e-12
    assert abs(s["avg_depth"] - 2.0) < 1e-12
    assert abs(s["lad_median"] - 0.075) < 1e-12, s["lad_median"]
    assert abs(s["hold_median"] - 0.01) < 1e-12, s["hold_median"]
    assert abs(s["diff_median"] - 0.04) < 1e-12, s["diff_median"]
    assert abs(s["lad_beats_hold_frac"] - 0.75) < 1e-12
    assert abs(s["green_frac"] - 0.75) < 1e-12
    assert s["worst"] == -1.0
    assert abs(s["bite"] - 10.0) < 1e-9, s["bite"]      # |−1| / медиана 0.10
    assert abs(s["curve_dd"] - (-0.50)) < 1e-12, s["curve_dd"]
    print(f"ok  меры: liq {s['liq_freq']}, укус {s['bite']}, "
          f"просадка {s['curve_dd']}")


def test_measures_empty_is_none_not_zero():
    # Ноль позиций — величины ПРОЧЕРК (None), а не 0: голый ноль читался
    # бы как «ликвидаций не было».
    s = R.measures([], [], 0, 0, 0, 0, 0, {}, "1m", False, 0.1)
    assert s["liq_freq"] is None and s["ruin_freq"] is None
    assert "lad_median" not in s
    print("ok  ноль позиций → None, не 0")


def test_measures_no_winners_bite_none():
    # Все позиции в минусе — медианы прибыльной нет, укус None, не деление
    # на ноль.
    s = R.measures([-0.1, -0.2, -1.0], [-0.1, -0.2, -1.0], 1, 0, 3, 3, 0,
                   {"d": -1.3}, "1m", False, 0.1)
    assert s["bite"] is None, s["bite"]
    assert s["green_frac"] == 0.0
    print("ok  нет прибыльных — укус None")


# --- отрицательные контроли -----------------------------------------------

def _control_bite_against_all():
    """Укус, посчитанный по медиане ВСЕХ (а не прибыльных), даёт другое
    число — значит выбор знаменателя нагружен, и пиннинг его стережёт."""
    lad = np.array([0.10, -1.0, 0.05, 0.20])
    wrong = abs(float(np.min(lad))) / float(np.median(lad))   # /0.075
    return abs(wrong - 10.0) > 0.5      # ≈13.3, заметно ≠ 10 → отличимо


def _control_empty_returns_zero():
    """Если бы measures на n=0 возвращал 0 вместо None, edge-тест упал."""
    s = R.measures([], [], 0, 0, 0, 0, 0, {}, "1m", False, 0.1)
    return s["liq_freq"] is None       # держим, что именно None


TESTS = [
    test_daily_sigma_known,
    test_daily_sigma_takes_last_of_day,
    test_slice_window,
    test_entry_dates_stride,
    test_measures_numbers,
    test_measures_empty_is_none_not_zero,
    test_measures_no_winners_bite_none,
]


def main():
    for t in TESTS:
        t()
    assert _control_bite_against_all(), "укус по всем неотличим — контроль пуст"
    assert _control_empty_returns_zero(), "n=0 не даёт None"
    # отчёт собирается и несёт ключевые числа
    s = R.measures([0.1, -1.0, 0.05], [0.05, -1.0, 0.0], 1, 0, 6, 3, 0,
                   {"d": -0.85}, "1m", False, 1.0)
    rep = R.report(s)
    assert "§8.1" in rep and "0.5 %" in rep, "отчёт без порога ликвидации"
    print(f"\nвсе {len(TESTS)} проверки прошли; контроли на месте, отчёт цел")


if __name__ == "__main__":
    main()
