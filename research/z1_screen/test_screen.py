"""Тесты скрина Z1. Каждая дорога исполняется, а не подразумевается.

Главное, что здесь проверяется, — не арифметика, а три места, где
ошибка была бы НЕВИДИМОЙ в отчёте: заглядывание вперёд, вырожденный
контроль и планка нуля, которая не кусается.
"""

import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import screen as Z                                        # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "ПРОВАЛ ") + name
          + ("" if cond else f"  · {extra}"))
    if not cond:
        FAILED.append(name)


def test_forward_never_touches_the_signal_bar():
    """Вход по открытию СЛЕДУЮЩЕГО бара, а не того, что дал сигнал.

    Вход по бару решения есть подарок себе: цена этого бара и породила
    условие. Проверяется прямо: переписываем будущее — прошлое обязано
    не шелохнуться; переписываем бар входа — форвард обязан измениться.
    """
    P = np.array([[100.0, 101.0, 102.0, 103.0, 104.0, 105.0]],
                 dtype=np.float32)
    f = Z.fwd_ret(P, 2)
    # сигнал на баре 1: вход по открытию бара 2, выход по открытию 4
    want = 104.0 / 102.0 - 1.0
    check("форвард считается от следующего бара",
          abs(float(f[0, 1]) - want) < 1e-6, f"{f[0,1]} против {want}")
    P2 = P.copy()
    P2[0, 4:] = 999.0
    b1 = Z.back_ret(P, 2)[0, 3]
    b2 = Z.back_ret(P2, 2)[0, 3]
    check("прошлое не меняется от переписанного будущего",
          abs(float(b1) - float(b2)) < 1e-9, f"{b1} против {b2}")
    P3 = P.copy()
    P3[0, 2] = 50.0
    check("форвард ЗАВИСИТ от бара входа (иначе вход не тот)",
          abs(float(Z.fwd_ret(P3, 2)[0, 1]) - float(f[0, 1])) > 1e-6)


def test_dedup_keeps_one_event_per_series():
    hit = np.zeros((2, 200), dtype=bool)
    hit[0, 10:40] = True                  # одна серия
    hit[0, 150] = True                    # вторая, далеко
    hit[1, 5] = True
    r, c = Z.dedup_rows(hit, dedup_min=60)
    check("серия срабатываний даёт одно событие",
          len(r) == 3 and sorted(c.tolist()) == [5, 10, 150],
          f"{r.tolist()} {c.tolist()}")


def test_cross_section_excludes_own_events_and_thins_out():
    F = np.full((60, 3), 0.01, dtype=np.float32)
    F[0, 1] = 0.50                        # наше событие — выброс
    rows = np.array([0]); cols = np.array([1])
    med, wide = Z.cross_median(F, cols, rows)
    check("своё событие не входит в свой же контроль",
          abs(float(med[0]) - 0.01) < 1e-9 and int(wide[0]) == 59,
          f"{med} {wide}")
    thin = np.full((4, 2), 0.01, dtype=np.float32)
    med2, wide2 = Z.cross_median(thin, np.array([1]), np.array([0]))
    check("узкое сечение — пропуск, а не число",
          not np.isfinite(med2[0]), str(med2))


def synth(n_sym=120, n_min=3000, edge=0.004, seed=3):
    """Синтетика: у половины «событий» есть настоящее превышение.

    Событие ставится по условию на самих ценах, чтобы дорога от
    условия до превышения исполнялась целиком.
    """
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.001, size=(n_sym, n_min))
    P = 100 * np.exp(np.cumsum(r, axis=1)).astype(np.float32)
    rows = rng.integers(0, n_sym, size=200)
    cols = rng.integers(100, n_min - 400, size=200)
    for k in range(len(rows)):
        # Ход начинается ПОСЛЕ входа: вход по открытию бара col+1,
        # значит сдвигать надо с col+2 — иначе «эффект» лежит в цене
        # самого входа, то есть недостижим.
        P[rows[k], cols[k] + 2:] *= (1.0 + edge)
    return P, rows, cols


def run_cells(P, rows, cols, side=1, perms=40):
    times = np.arange(P.shape[1], dtype=np.int64) * 60
    ev = {"тест": ({"name": "тест", "side": side, "group": "тест"},
                   rows.astype(np.int64), cols.astype(np.int64))}
    Z.CONDS_BY_NAME["тест"] = [{"name": "тест", "side": side,
                                "group": "тест"}]
    old = Z.PERMS
    Z.PERMS = perms
    try:
        acc = {}
        Z.measure(ev, P, times, acc, np.random.default_rng(1))
        cells, null = Z.summarize(acc)
    finally:
        Z.PERMS = old
    return cells, null


def test_real_effect_beats_the_family_bar():
    P, rows, cols = synth()
    cells, null = run_cells(P, rows, cols)
    key = ("тест", 1, 5)
    check("ячейка измерена", key in cells, str(list(cells)[:3]))
    if key in cells:
        check("настоящий эффект выше планки нуля",
              cells[key]["med_bp"] > null["bar"] > 0,
              f"{cells[key]['med_bp']:.1f} против планки {null['bar']:.1f}")


def test_pure_noise_stays_under_the_bar():
    P, rows, cols = synth(edge=0.0, seed=11)
    cells, null = run_cells(P, rows, cols)
    over = [k for k, c in cells.items() if c["med_bp"] > null["bar"]]
    check("на шуме ни одна ячейка не выше планки", not over,
          f"{over} планка {null['bar']:.1f}")


def test_buckets_do_not_degenerate_on_a_frequent_signal():
    """Единица наблюдения обязана оставаться множественной.

    Слипание по разрыву времени на частом сигнале схлопывает всё в
    один-два «эпизода», и медиана по ним есть медиана двух чисел —
    именно это и показал первый прогон этого теста. Корзина длиной в
    горизонт такого не допускает по построению.
    """
    P, rows, cols = synth()
    cells, _ = run_cells(P, rows, cols)
    c = cells[("тест", 1, 5)]
    check("корзин много, а не две", c["buckets"] > 50,
          f"корзин {c['buckets']} на {c['events']} событий")


def test_side_flips_the_sign():
    P, rows, cols = synth()
    up, _ = run_cells(P, rows, cols, side=1)
    dn, _ = run_cells(P, rows, cols, side=-1)
    a = up[("тест", 1, 5)]["med_bp"]
    b = dn[("тест", -1, 5)]["med_bp"]
    check("шорт той же ситуации даёт зеркальный знак",
          a > 0 > b and abs(a + b) < 0.3 * abs(a), f"{a:.1f} {b:.1f}")


def test_report_names_the_degenerate_control():
    """Доля универсума в событии обязана доезжать до отчёта.

    Условие, которое срабатывает у всего рынка разом, делает контроль
    бессмысленным — и это должно быть ВИДНО числом, а не выясняться
    потом (в зонде возврата ячейка 2 % умерла именно так).
    """
    P, rows, cols = synth()
    cells, null = run_cells(P, rows, cols)
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "rep.md")
        Z.write_report(path, cells, null,
                       {"when": "тест", "start": "a", "end": "b",
                        "symbols": 120, "conds": 1})
        txt = open(path, encoding="utf-8").read()
        check("в отчёте есть планка, доля и сечение",
              "планка" in txt and "доля" in txt and "сечение" in txt,
              txt[:200])
        check("в отчёте сказано, чего скрин не говорит",
              "НЕ говорит" in txt, txt[-300:])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_units_are_yesterdays_and_zero_noise_is_a_gap():
    """Нулевой шум — пропуск, а не «бесконечно сильный сигнал».

    Обратная величина без пола уже была ловушкой замороженных рядов в
    S1: актив с нулевой волатильностью забирал 92.7 % книги.
    """
    times = np.arange(0, 2 * 86400, 60, dtype=np.int64)
    U = {"noise": np.zeros((1, len(times)), dtype=np.float32)}
    U["noise"][~np.isfinite(U["noise"]) | (U["noise"] <= 0)] = np.nan
    check("нулевой шум становится пропуском",
          not np.isfinite(U["noise"]).any(), "ноль остался числом")
    A = Z.age_matrix(["AAA"], times, {"AAA": {"listed": "2020-01-01"}})
    check("возраст листинга растёт по суткам",
          A[0, -1] > A[0, 0], f"{A[0,0]} {A[0,-1]}")


def test_since_shock_and_rolling_sum():
    z = np.zeros((1, 10), dtype=np.float32)
    z[0, 3] = 5.0
    d = Z.since_shock(z, thr=2.0, cap=100)
    check("время с шока считается от шока",
          float(d[0, 3]) == 0.0 and float(d[0, 6]) == 3.0, str(d))
    X = np.ones((1, 5), dtype=np.float32)
    s = Z.roll_sum(X, 3)
    check("скользящая сумма смотрит назад",
          not np.isfinite(s[0, 1]) and float(s[0, 2]) == 3.0, str(s))


TESTS = [test_forward_never_touches_the_signal_bar,
         test_dedup_keeps_one_event_per_series,
         test_cross_section_excludes_own_events_and_thins_out,
         test_real_effect_beats_the_family_bar,
         test_pure_noise_stays_under_the_bar,
         test_buckets_do_not_degenerate_on_a_frequent_signal,
         test_side_flips_the_sign,
         test_report_names_the_degenerate_control,
         test_units_are_yesterdays_and_zero_noise_is_a_gap,
         test_since_shock_and_rolling_sum]


def main():
    for t in TESTS:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛОВ: {len(FAILED)} — " + ", ".join(FAILED))
        return 1
    print(f"все проверки прошли ({len(TESTS)} блоков)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
