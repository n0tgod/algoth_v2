#!/usr/bin/env python3
"""
Тесты L3. Закрывают места, где ошибка была бы невидимой в результате.

    python3 research/l3_events/test_l3.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import events as E  # noqa: E402

FAILED = []
W = E.steps(E.WINDOW_MIN)


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def flat(n, v=100.0):
    return np.full(n, float(v))


def test_detect_basic():
    n = 60
    oi, px = flat(n, 1000.0), flat(n)
    oi[30:] = 950.0                  # −5 % интереса
    px[30:] = 96.0                   # −4 % цены
    ok = np.ones(n, bool)
    idx = E.detect(oi, px, ok, 0.01, 0.03)
    check("настоящий каскад найден", len(idx) == 1, str(idx))
    check("момент — первый, где выполнено окно", idx[0] == 30, str(idx))


def test_detect_direction():
    """Рост цены событием не является: конструкция — лонг после падения."""
    n = 60
    oi, px = flat(n, 1000.0), flat(n)
    oi[30:] = 950.0
    px[30:] = 104.0
    idx = E.detect(oi, px, np.ones(n, bool), 0.01, 0.03)
    check("каскад вверх не считается событием", len(idx) == 0, str(idx))


def test_detect_needs_oi_drop():
    n = 60
    oi, px = flat(n, 1000.0), flat(n)
    px[30:] = 96.0                   # цена упала, интерес не изменился
    idx = E.detect(oi, px, np.ones(n, bool), 0.01, 0.03)
    check("без падения интереса события нет", len(idx) == 0, str(idx))
    idx2 = E.detect(oi, px, np.ones(n, bool), 0.01, 0.03, require_oi=False)
    check("контроль 2 то же самое находит", len(idx2) == 1, str(idx2))


def test_detect_gap_is_nan():
    """Дыра в ряде интереса не порождает события — она NaN на сетке."""
    n = 60
    oi, px = flat(n, 1000.0), flat(n)
    oi[27:30] = np.nan               # нет данных как раз на окне
    oi[30:] = 500.0
    px[30:] = 96.0
    idx = E.detect(oi, px, np.ones(n, bool), 0.01, 0.03)
    check("через пропуск событие не считается", 30 not in idx, str(idx))


def test_detect_mask():
    n = 60
    oi, px = flat(n, 1000.0), flat(n)
    oi[30:] = 950.0
    px[30:] = 96.0
    ok = np.ones(n, bool)
    ok[30:36] = False                # окно делистинга или тонкий период
    idx = E.detect(oi, px, ok, 0.01, 0.03)
    check("маска отсекает запрещённые моменты", 30 not in idx, str(idx))


def test_dedup():
    """Серия соседних баров одного обвала — одно событие."""
    n = 120
    oi, px = flat(n, 1000.0), flat(n)
    for k in range(30, 45):
        oi[k] = 1000.0 - (k - 29) * 20
        px[k] = 100.0 - (k - 29) * 0.9
    oi[45:] = oi[44]
    px[45:] = px[44]
    idx = E.detect(oi, px, np.ones(n, bool), 0.01, 0.03)
    check("обвал даёт одно событие, а не десять", len(idx) <= 2, str(idx))
    if len(idx) > 1:
        check("между событиями не меньше часа",
              int(np.min(np.diff(idx))) >= E.steps(E.DEDUP_MIN), str(idx))


def test_forward():
    px = flat(40)
    px[20:] = 110.0
    j = np.array([17])
    check("форвард считается от входа",
          abs(E.forward(px, j, 15)[0] - 0.10) < 1e-12,
          str(E.forward(px, j, 15)))
    check("форвард за краем ряда не считается",
          not np.isfinite(E.forward(px, np.array([39]), 60)[0]))


def test_episodes():
    # Разрыв считается между СОСЕДНИМИ событиями, а не от первого:
    # цепочка близких событий остаётся одним эпизодом, сколько бы
    # времени она ни занимала. Поэтому разрыв здесь заведомо больше
    # четырёх часов.
    t = np.array([0, 60, 3600, 3600 + 5 * 3600, 3600 + 5 * 3600 + 60],
                 dtype=np.int64)
    ep = E.episodes(t)
    check("события в пределах четырёх часов — один эпизод",
          ep[0] == ep[1] == ep[2], str(ep))
    check("после разрыва начинается новый", ep[3] == ep[2] + 1, str(ep))
    check("соседи после разрыва снова вместе", ep[3] == ep[4], str(ep))
    check("порядок аргумента не важен",
          list(E.episodes(t[::-1])[::-1]) == list(ep), str(ep))


def test_by_episode():
    v = np.array([0.1, 0.3, 1.0])
    ep = np.array([0, 0, 1])
    r = E.by_episode(v, ep)
    check("эпизод даёт один голос, а не столько, сколько событий",
          len(r) == 2 and abs(r[0] - 0.2) < 1e-12, str(r))


def test_ban_matrix_matches_direct_fill():
    """Разностный массив обязан дать в точности то же, что прямая запись.

    Переписано ради скорости: на секундной сетке ленты окно в полчаса —
    3601 ячейка на событие. Ускорение, меняющее результат, есть не
    ускорение, а другая мера, поэтому равенство проверяется числом на
    краях и на пересечениях окон.
    """
    rng = np.random.default_rng(7)
    shape = (5, 200)
    rows = rng.integers(0, shape[0], 40)
    cols = rng.integers(0, shape[1], 40)
    for guard in (0, 1, 7, 300):
        want = np.zeros(shape, dtype=bool)
        g = E.steps(guard, 1)
        for r, j in zip(rows, cols):
            want[r, max(0, j - g):min(shape[1], j + g + 1)] = True
        got = E.ban_matrix(shape, rows, cols, guard_min=guard, step_min=1)
        check(f"защитное окно {guard}: совпало с прямой записью",
              bool(np.array_equal(got, want)),
              f"расхождений {int((got != want).sum())}")
        # Пачечное заполнение обязано давать тот же результат при
        # любом размере пачки — граница пачки внутри ряда событий.
        for ch in (1, 2, 128):
            got_c = E.ban_matrix(shape, rows, cols, guard_min=guard,
                                 step_min=1, chunk_rows=ch)
            check(f"окно {guard}, пачка {ch}: бит в бит",
                  bool(np.array_equal(got_c, want)),
                  f"расхождений {int((got_c != want).sum())}")
    empty = E.ban_matrix(shape, np.array([], dtype=np.int64),
                         np.array([], dtype=np.int64), guard_min=5,
                         step_min=1)
    check("без событий не запрещено ничего", not empty.any(), "")


def test_cross_section_excludes_neighbours():
    """Каскадящие соседи не должны попадать в собственный фон."""
    # Кросс-секция меньше двадцати активов не считается вовсе — фон из
    # трёх имён не фон.
    n_sym, n_t = 25, 100
    P = np.full((n_sym, n_t), 100.0)
    P[:, 50:] = 100.0
    P[0, 50:] = 110.0                # каскадный актив отскочил
    P[1, 50:] = 110.0                # сосед, у которого тоже событие
    rows = np.array([0, 1])
    cols = np.array([40, 40])
    cs = E.cross_section(P, cols, rows, 60)
    check("фон считается без каскадящих активов",
          np.isfinite(cs[0]) and abs(cs[0]) < 1e-12, str(cs))


def test_null_shift():
    n = 200_000
    j = np.array([1000, n - 10])
    d = E.SHIFT_DAYS * 24 * 60 // E.STEP_MIN
    out = E.null_shift(j, n)
    check("сдвиг вперёд, если помещается", out[0] == 1000 + d, str(out))
    check("иначе назад", out[1] == n - 10 - d, str(out))


def test_null_matched_hour():
    n = 288 * 10
    hours = np.array([(k * 5 // 60) % 24 for k in range(n)], dtype=np.int8)
    valid = np.ones(n, bool)
    j = np.array([500])
    got = E.null_matched_times(valid, j, hours, 1, guard_steps=12)
    check("нуль 1 берёт тот же час суток",
          got[0] >= 0 and hours[got[0]] == hours[500], str(got))
    check("и не соседний момент", abs(got[0] - 500) > 12, str(got))
    a = E.null_matched_times(valid, j, hours, 7, 12)
    b = E.null_matched_times(valid, j, hours, 7, 12)
    check("зерно воспроизводимо", a[0] == b[0], f"{a} {b}")


def main():
    print("отбор событий")
    test_detect_basic()
    test_detect_direction()
    test_detect_needs_oi_drop()
    test_detect_gap_is_nan()
    test_detect_mask()
    test_dedup()
    print("форварды и эпизоды")
    test_forward()
    test_episodes()
    test_by_episode()
    print("контроли и нули")
    test_ban_matrix_matches_direct_fill()
    test_cross_section_excludes_neighbours()
    test_null_shift()
    test_null_matched_hour()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
