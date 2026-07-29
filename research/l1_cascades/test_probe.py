#!/usr/bin/env python3
"""
Тесты отбора событий. Покрывают дефект, найденный на широком универсуме.

У двенадцати мажоров зонда пропусков в ряде интереса почти нет (0.05 %),
а на универсуме есть и крупные: BSWUSDT — 248 суточных файлов из 640
(39 %), BRETTUSDT — 116 из 796. Окно в 15 минут бралось смещением на
три точки сетки, и через дыру это смещение означает не пятнадцать
минут, а месяц. Проверка «точка есть» при этом проходит, а величина
считается не та — тот же род ошибки, что замороженные ряды A2.

    python3 research/l1_cascades/test_probe.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import probe as PR  # noqa: E402

FAILED = []
STEP = PR.STEP_MIN * 60


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def grid(n, start=1_700_000_000):
    return np.arange(n, dtype=np.float64) * STEP + start


def test_at_time_exact():
    t = grid(20)
    got = PR.at_time(t, t - PR.WINDOW_MIN * 60)
    check("на сплошной сетке окно — ровно три точки назад",
          list(got[3:]) == list(range(len(t) - 3)), str(got))
    check("у первых трёх точек назад ничего нет",
          list(got[:3]) == [-1, -1, -1], str(got[:3]))


def test_at_time_gap():
    """Дыра: точки есть, но не те. Обязан вернуть −1, а не соседа."""
    t = np.concatenate([grid(6), grid(6)[-1] + 30 * 86400 + grid(6)])
    got = PR.at_time(t, t - PR.WINDOW_MIN * 60)
    check("после дыры окно не находится", got[6] == -1 and got[7] == -1
          and got[8] == -1, str(got))
    check("внутри второго куска окно снова находится",
          got[9] == 6 and got[11] == 8, str(got))


def test_at_time_tolerance():
    t = grid(10)
    want = t - PR.WINDOW_MIN * 60 + 30       # метка сдвинута на полминуты
    check("сдвиг в пределах допуска попадает",
          PR.at_time(t, want)[5] == 2, str(PR.at_time(t, want)[5]))
    want = t - PR.WINDOW_MIN * 60 + 150      # сдвиг больше допуска
    check("сдвиг больше допуска не попадает",
          PR.at_time(t, want)[5] == -1, str(PR.at_time(t, want)[5]))


def test_scan_ignores_gap():
    """Обвал «через дыру» событием не является.

    Ряд из двух кусков, между ними месяц. Интерес во втором куске вдвое
    ниже, цена вдвое ниже. По номеру точки это выглядит как каскад
    −50 %/−50 %; по времени события нет вовсе.
    """
    a, b = grid(6), grid(6) + 30 * 86400
    t = np.concatenate([a, b])
    oi = np.concatenate([np.full(6, 1000.0), np.full(6, 500.0)])
    px = np.concatenate([np.full(6, 100.0), np.full(6, 50.0)])
    ev = PR.scan("X", t, oi, px, 0.01, 0.01)
    check("разрыв не порождает события", ev == [], f"{len(ev)} событий")


def test_scan_finds_real_event():
    """Настоящий каскад внутри сплошного куска обязан находиться."""
    t = grid(40)
    oi = np.full(40, 1000.0)
    px = np.full(40, 100.0)
    oi[20:] = 950.0            # −5 % интереса за окно
    px[20:] = 96.0             # −4 % цены
    px[23:] = 98.0             # отскок через 15 минут
    ev = PR.scan("X", t, oi, px, 0.03, 0.03)
    check("настоящий каскад найден", len(ev) == 1, f"{len(ev)} событий")
    if ev:
        e = ev[0]
        check("сторона определена как «вниз»", e["down"], str(e["down"]))
        check("падение интереса посчитано",
              abs(e["oi_change"] + 0.05) < 1e-9, str(e["oi_change"]))
        check("форвард на 15 мин посчитан по времени",
              abs(e["fwd"][15] - (98.0 / 96.0 - 1.0)) < 1e-9,
              str(e["fwd"].get(15)))


def test_forward_across_gap_dropped():
    """Форвард, попадающий в дыру, не берётся ближайшим соседом."""
    t = np.concatenate([grid(24), grid(24)[-1] + 5 * 86400 + grid(6)])
    oi = np.full(len(t), 1000.0)
    px = np.full(len(t), 100.0)
    oi[20:] = 900.0
    px[20:] = 95.0
    ev = PR.scan("X", t, oi, px, 0.03, 0.03)
    check("событие у края найдено", len(ev) == 1, f"{len(ev)} событий")
    if ev:
        far = [f for f in (60, 240, 1440) if f in ev[0]["fwd"]]
        check("дальние горизонты за дырой отброшены", far == [], str(far))


def main():
    print("поиск точки по времени")
    test_at_time_exact()
    test_at_time_gap()
    test_at_time_tolerance()
    print("отбор событий")
    test_scan_ignores_gap()
    test_scan_finds_real_event()
    test_forward_across_gap_dropped()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
