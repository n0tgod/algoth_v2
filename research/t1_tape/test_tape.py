#!/usr/bin/env python3
"""
Тесты модуля ленты. Синтетика плюс одна проверка на живом файле.

Живая проверка здесь не роскошь: **чья сторона в колонке `side`** — это
вопрос, ответ на который нельзя брать из документации. Если бы там был
мейкер, а не агрессор, все производные величины поменяли бы знак
согласованно, и результат выглядел бы осмысленным. Проверка выводит
ответ из самих данных: агрессивная покупка обязана двигать цену вверх.

    python3 research/t1_tape/test_tape.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tape as T  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def synth():
    """Пять принтов в двух секундах, знаки и цены известны."""
    ts = np.array([100.0, 100.4, 100.9, 101.2, 101.8])
    sg = np.array([1, 1, -1, -1, 1], dtype=np.int8)
    sz = np.array([2.0, 3.0, 1.0, 4.0, 5.0])
    px = np.array([10.0, 11.0, 9.0, 12.0, 10.0])
    return ts, sg, sz, px


def test_grid_volumes():
    g = T.to_grid(synth(), 1.0, t0=100.0, t1=102.0)
    check("две ячейки сетки", len(g["t"]) == 2, str(g["t"]))
    # ячейка 100–101: buy 2*10 + 3*11 = 53, sell 1*9 = 9
    check("агрессивные покупки суммируются",
          abs(g["buy_qv"][0] - 53.0) < 1e-9, str(g["buy_qv"]))
    check("агрессивные продажи суммируются",
          abs(g["sell_qv"][0] - 9.0) < 1e-9, str(g["sell_qv"]))
    check("дельта есть разность сторон",
          abs(g["delta"][0] - 44.0) < 1e-9, str(g["delta"]))
    check("число принтов", list(g["prints"]) == [3, 2], str(g["prints"]))


def test_grid_prices():
    g = T.to_grid(synth(), 1.0, t0=100.0, t1=102.0)
    check("открытие — первый принт ячейки",
          abs(g["open"][0] - 10.0) < 1e-9, str(g["open"]))
    check("закрытие — последний принт ячейки",
          abs(g["close"][0] - 9.0) < 1e-9, str(g["close"]))
    check("максимум и минимум по ячейке",
          abs(g["high"][0] - 11.0) < 1e-9 and abs(g["low"][0] - 9.0) < 1e-9,
          f"{g['high']} {g['low']}")
    # VWAP ячейки: (10*20 + 11*33 + 9*9) / 62
    want = (10 * 20 + 11 * 33 + 9 * 9) / 62.0
    check("средняя по объёму", abs(g["vwap"][0] - want) < 1e-9,
          f"{g['vwap'][0]} против {want}")


def test_grid_empty_cell_is_nan():
    """Пустая ячейка — пропуск, а не наблюдение с нулевой доходностью."""
    ts = np.array([100.0, 103.5])
    tape = (ts, np.array([1, 1], dtype=np.int8),
            np.array([1.0, 1.0]), np.array([10.0, 10.0]))
    g = T.to_grid(tape, 1.0, t0=100.0, t1=104.0)
    check("в пустой ячейке цены нет",
          not np.isfinite(g["close"][1]) and not np.isfinite(g["close"][2]),
          str(g["close"]))
    check("в пустой ячейке объём ноль",
          g["buy_qv"][1] == 0.0 and g["prints"][1] == 0, str(g["prints"]))


def test_footprint():
    lvl, buy, sell = T.footprint(synth(), 100.0, 102.0, tick=1.0)
    check("уровни по возрастанию цены", list(lvl) == [9.0, 10.0, 11.0, 12.0],
          str(lvl))
    d = dict(zip(lvl, buy))
    check("покупки на уровне 10 — два принта",
          abs(d[10.0] - (2 * 10 + 5 * 10)) < 1e-9, str(buy))
    d2 = dict(zip(lvl, sell))
    check("продажи на уровне 12", abs(d2[12.0] - 4 * 12) < 1e-9, str(sell))
    check("на уровне 12 покупок нет", abs(d[12.0]) < 1e-9, str(buy))


def test_rolling_sum():
    v = np.array([1.0, 2.0, 3.0, 4.0])
    r = T.rolling_sum(v, 2)
    check("окно выровнено по правому краю",
          not np.isfinite(r[0]) and abs(r[1] - 3.0) < 1e-9
          and abs(r[3] - 7.0) < 1e-9, str(r))


def test_absorption_finds_held_price():
    """Льют объём, цена стоит — это поглощение."""
    step, n = 1.0, 300
    t0 = 1_000_000.0
    ts, sg, sz, px = [], [], [], []
    for k in range(n):
        # обычный фон: по одному принту в секунду
        ts.append(t0 + k + 0.1)
        sg.append(-1 if k % 2 else 1)
        sz.append(1.0)
        px.append(100.0)
    # окно 200–210: продажи в двадцать раз больше обычного, цена стоит
    for k in range(200, 210):
        for _ in range(20):
            ts.append(t0 + k + 0.5)
            sg.append(-1)
            sz.append(1.0)
            px.append(100.0)
    order = np.argsort(ts)
    tape = (np.array(ts)[order], np.array(sg, dtype=np.int8)[order],
            np.array(sz)[order], np.array(px)[order])
    g = T.to_grid(tape, step, t0=t0, t1=t0 + n)
    idx, info = T.absorption(g, window_sec=10, vol_mult=5.0,
                             move_mult=0.5, side=-1)
    check("поглощение найдено", len(idx) >= 1, f"{idx} {info}")
    if len(idx):
        # Окно суммы выровнено по правому краю и захватывает всплеск уже
        # с первой его ячейки: срабатывание на 200 законно, ждать 209
        # было ошибкой ожидания, а не кода.
        check("найдено в окне всплеска", 200 <= idx[0] <= 215, str(idx))


def test_absorption_ignores_move():
    """Тот же объём, но цена провалилась — это не поглощение."""
    step, n = 1.0, 300
    t0 = 1_000_000.0
    ts, sg, sz, px = [], [], [], []
    for k in range(n):
        ts.append(t0 + k + 0.1)
        sg.append(-1 if k % 2 else 1)
        sz.append(1.0)
        px.append(100.0 if k < 200 else 90.0)
    for k in range(200, 210):
        for _ in range(20):
            ts.append(t0 + k + 0.5)
            sg.append(-1)
            sz.append(1.0)
            px.append(100.0 - (k - 199))
    order = np.argsort(ts)
    tape = (np.array(ts)[order], np.array(sg, dtype=np.int8)[order],
            np.array(sz)[order], np.array(px)[order])
    g = T.to_grid(tape, step, t0=t0, t1=t0 + n)
    idx, _ = T.absorption(g, window_sec=10, vol_mult=5.0,
                          move_mult=0.5, side=-1)
    check("пролив с падением цены поглощением не считается",
          not any(200 <= i <= 215 for i in idx), str(idx))


def test_side_is_aggressor_on_real_file():
    """Живая проверка: агрессивная покупка обязана двигать цену вверх.

    Если `side` — сторона мейкера, доля будет заметно НИЖЕ половины, и
    знак дельты во всём модуле надо переворачивать.
    """
    day = T.load_day("ARBUSDT", "2025-03-10")
    if day is None:
        print("  — живая проверка пропущена: файла нет в кэше и сеть закрыта")
        return
    ts, sg, sz, px = day
    moved = np.diff(px) != 0
    up = np.diff(px)[moved] > 0
    buy = sg[1:][moved] > 0
    share_up_for_buy = float(np.mean(up[buy])) if buy.any() else float("nan")
    share_up_for_sell = (float(np.mean(up[~buy])) if (~buy).any()
                         else float("nan"))
    check(f"покупка двигает цену вверх ({share_up_for_buy:.1%})",
          share_up_for_buy > 0.8, f"{share_up_for_buy:.3f}")
    check(f"продажа двигает цену вниз ({1 - share_up_for_sell:.1%})",
          share_up_for_sell < 0.2, f"{share_up_for_sell:.3f}")


def test_cross_width_counts_only_clean():
    """Ширина фона: сам актив в него не входит, запрещённые тоже."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "l3_events"))
    import probe as P  # noqa: E402

    C = np.full((4, 10), 100.0)
    C[3, :] = np.nan                       # у четвёртого цены нет вовсе
    banned = np.zeros((4, 10), dtype=bool)
    banned[0, 5] = True                    # событие первого — он же и запрещён
    banned[1, 5] = True                    # сосед в это время тоже поглощал
    w = P.cross_width(C, banned, np.array([5]), 2)
    check("в фоне остался один сосед", int(w[0]) == 1, str(w))
    w2 = P.cross_width(C, np.zeros((4, 10), dtype=bool), np.array([5]), 2)
    check("без запретов — все с ценой", int(w2[0]) == 3, str(w2))


def main():
    print("сетка")
    test_grid_volumes()
    test_grid_prices()
    test_grid_empty_cell_is_nan()
    print("кластеры")
    test_footprint()
    print("поглощение")
    test_rolling_sum()
    test_absorption_finds_held_price()
    test_absorption_ignores_move()
    print("контроль кросс-секцией")
    test_cross_width_counts_only_clean()
    print("живая проверка стороны")
    test_side_is_aggressor_on_real_file()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
