#!/usr/bin/env python3
"""
Тесты ядра решения D1. Каждая проверка закрывает место, где ошибка была
бы невидимой в результате: числа печатались бы, отчёт выглядел бы
исправным, а мерилось бы другое.

    python3 research/d1_seconds/test_detect.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import detect as D  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def ramp(n, start=100.0):
    """Ровный ряд без движения: событий в нём быть не должно."""
    return np.full(n, float(start))


# --- сетка и время ----------------------------------------------------

def test_place_takes_the_last_price_of_the_second():
    """Решение принимается концом секунды, значит и цена — последняя.

    Взяв первую, мы считали бы по цене, которая внутри той же секунды
    уже устарела, — и на секундной сетке это ровно тот масштаб, ради
    которого гипотеза и заведена.
    """
    row = D.place([10.0, 10.4, 10.9, 11.2], [1.0, 2.0, 3.0, 4.0],
                  t0=10, n=3)
    check("последняя цена секунды", row[0] == 3.0, f"{row[0]}")
    check("следующая секунда своя", row[1] == 4.0, f"{row[1]}")
    check("секунды без наблюдений — nan", np.isnan(row[2]), f"{row[2]}")


def test_place_ignores_order_of_input():
    """Порядок строк в записи не обязан быть отсортированным."""
    a = D.place([10.9, 10.0, 10.4], [3.0, 1.0, 2.0], t0=10, n=1)
    check("порядок входа не решает", a[0] == 3.0, f"{a[0]}")


def test_gap_is_a_gap_not_a_carried_price():
    """Дыра остаётся дырой: перенесённая цена дала бы нулевую доходность.

    Урок A2: замороженный ряд опаснее пропуска, потому что проверка
    «есть ли значение» на нём проходит.
    """
    row = D.place([0.0, 30.0], [100.0, 99.0], t0=0, n=31)
    check("дыра не заполняется", int(np.isfinite(row).sum()) == 2,
          f"{int(np.isfinite(row).sum())}")


# --- окно измеряется во времени, а не в точках ------------------------

def test_window_is_time_not_cells():
    """Главная проверка модуля.

    Ряд, в котором наблюдений мало: если считать «пятнадцать точек
    назад», опорой станет цена часовой давности и падение найдётся; если
    считать пятнадцать минут — опоры нет вовсе, и события нет.
    """
    n = 4000
    row = np.full(n, np.nan)
    # Наблюдения раз в 400 с: соседняя ТОЧКА отстоит на семь минут, и
    # опоры ровно за 900 с не существует ни у одной из них.
    for k, j in enumerate(range(0, n, 400)):
        row[j] = 100.0 - k          # ровное сползание по точкам
    prev, nxt = D.fill_index(row)
    f = D.falls(row, prev, nxt)
    j = 3600                        # наблюдение есть, опоры за 900 с нет
    check("цена на месте есть", np.isfinite(row[j]), "нет цены")
    check("опоры нет — падение не считается", np.isnan(f[j]), f"{f[j]}")
    # а там, где опора реально есть, величина считается
    row2 = D.place(np.arange(0, n, 1.0), np.linspace(100.0, 90.0, n),
                   t0=0, n=n)
    f2 = D.falls(row2)
    check("на сплошном ряде падение есть", np.isfinite(f2[j]), f"{f2[j]}")


def test_reference_is_the_nearest_not_the_older_one():
    """Ближайшая опора, а не «последняя до».

    Односторонний поиск назад делает окно длиннее объявленного — то есть
    систематически находит падения чаще. Смещение в пользу гипотезы, и в
    результате оно невидимо.
    """
    n = 1000
    row = np.full(n, np.nan)
    row[99] = 100.0                 # на 3 с РАНЬШЕ опорного момента
    row[104] = 90.0                 # на 2 с ПОЗЖЕ — ближе
    prev, nxt = D.fill_index(row)
    got = int(D.nearest(prev, nxt, np.array([102]), tol=5)[0])
    check("берётся ближайшая опора", got == 104, f"{got}")

    tied = np.full(n, np.nan)
    tied[99] = 100.0
    tied[105] = 90.0                # равное расстояние в обе стороны
    p2, n2 = D.fill_index(tied)
    tie = int(D.nearest(p2, n2, np.array([102]), tol=5)[0])
    check("ничья решается ранней", tie == 99, f"{tie}")


def test_missing_reference_is_not_zero():
    """Нет опоры — `nan`, а не «падения не было».

    Ноль на месте пропуска сделал бы дыру спокойным рынком, а таких дыр
    у записи по 518 именам будет много.
    """
    n = 2000
    row = np.full(n, np.nan)
    row[1500] = 100.0
    f = D.falls(row)
    check("пропуск не превращается в ноль", np.isnan(f[1500]), f"{f[1500]}")
    idx = D.detect(row, 0.03)
    check("события без опоры нет", len(idx) == 0, f"{len(idx)}")


# --- событие ----------------------------------------------------------

def test_detect_finds_the_declared_fall():
    n = 3000
    px = np.full(n, 100.0)
    px[1800:] = 96.5                # −3.5 % ступенькой
    row = D.place(np.arange(n, dtype=float), px, t0=0, n=n)
    idx = D.detect(row, 0.03)
    check("событие найдено", len(idx) == 1, f"{len(idx)}")
    check("момент — первая секунда выполнения",
          len(idx) == 1 and idx[0] == 1800, f"{idx}")
    weak = D.detect(row, 0.05)
    check("порог 5 % это падение не берёт", len(weak) == 0, f"{len(weak)}")


def test_dedup_counts_one_event_per_window():
    """Падение остаётся верным сотни секунд подряд.

    Без пропуска ступенька дала бы 900 «событий», и число наблюдений в
    отчёте выросло бы на порядок из ничего — ровно та подделка бюджета
    доказательства, от которой спека считает эпизоды.
    """
    n = 4000
    px = np.full(n, 100.0)
    px[1800:] = 96.0
    row = D.place(np.arange(n, dtype=float), px, t0=0, n=n)
    idx = D.detect(row, 0.03)
    check("одно событие, а не девятьсот", len(idx) == 1, f"{len(idx)}")
    raw = D.detect(row, 0.03, dedup_sec=1)
    check("без пропуска их сотни", len(raw) > 800, f"{len(raw)}")


# --- вход и выход -----------------------------------------------------

def test_entry_at_the_decision_second_is_refused():
    """Вход по цене, определившей сигнал, — подарок, которого нет.

    Отвергается исключением, а не молча приравнивается к секунде: тихая
    поправка выглядела бы как исполнимая сделка.
    """
    n = 100
    row = D.place(np.arange(n, dtype=float), np.full(n, 100.0), 0, n)
    _, nxt = D.fill_index(row)
    try:
        D.trade(row, nxt, 10, 0, 30)
        check("δ = 0 отвергается", False, "исключения не было")
    except ValueError:
        check("δ = 0 отвергается", True)


def test_entry_is_the_first_price_strictly_after_the_delay():
    n = 200
    px = np.arange(n, dtype=float) + 100.0     # цена растёт на 1 в секунду
    row = D.place(np.arange(n, dtype=float), px, 0, n)
    _, nxt = D.fill_index(row)
    r, i_in, i_out = D.trade(row, nxt, 50, 1, 10)
    check("вход в T+1", i_in == 51, f"{i_in}")
    check("выход через горизонт от входа", i_out == 61, f"{i_out}")
    check("доходность считается по этим двум",
          abs(r - (px[61] / px[51] - 1.0)) < 1e-12, f"{r}")


def test_entry_refuses_a_stale_price():
    """Цена, найденная сильно позже намеченного момента, — другая сделка.

    Без ограничения ожидания вход «через 5 с» на дырявом участке молча
    исполнялся бы через минуту, и колонка задержки перестала бы мерить
    задержку.
    """
    n = 300
    row = np.full(n, np.nan)
    row[np.arange(0, 100)] = 100.0
    row[200] = 105.0                # следующая цена только через 100 с
    _, nxt = D.fill_index(row)
    r, i_in, _ = D.trade(row, nxt, 99, 5, 30)
    check("несвежий вход не исполняется", i_in == -1 and np.isnan(r),
          f"{i_in}, {r}")


def test_horizon_runs_from_the_actual_entry():
    """Задержка заполнения не должна укорачивать удержание."""
    n = 400
    row = np.full(n, np.nan)
    row[np.arange(0, 401, 1)[:n]] = np.nan
    for j in range(0, n):
        row[j] = 100.0 + j * 0.01
    row[101:104] = np.nan           # вход заполнится не сразу
    _, nxt = D.fill_index(row)
    _, i_in, i_out = D.trade(row, nxt, 100, 1, 60)
    check("вход сдвинулся заполнением", i_in == 104, f"{i_in}")
    check("горизонт от входа, а не от решения", i_out == 164, f"{i_out}")


# --- одновременная кросс-секция --------------------------------------

def build_matrix(rows, n, mover=None, drop=0.04, j_ev=1800):
    """Матрица ровных рядов; строке `mover` рисуется падение и отскок."""
    P = np.full((rows, n), 100.0)
    if mover is not None:
        P[mover, j_ev:] = 100.0 * (1.0 - drop)
        P[mover, j_ev + 60:] = 100.0 * (1.0 - drop) * 1.02   # отскок 2 %
    return P


def matrix_index(P):
    NXT = np.empty(P.shape, dtype=np.int64)
    for r in range(P.shape[0]):
        NXT[r] = D.fill_index(P[r])[1]
    return NXT


def test_cross_section_floor_is_not_zero():
    """Фон тоньше пола — «не измеряется», а не «превышение равно нулю».

    Ширина возвращается всегда: только по ней видно, отчего ячейка
    молчит. В зонде возврата такая ячейка выглядела отсутствием эффекта.
    """
    n = 2200
    for rows, want in ((40, False), (60, True)):
        P = build_matrix(rows, n, mover=0)
        NXT = matrix_index(P)
        own, bg, exc, width = D.excess(P, NXT, 0, 1800, 5, 300, None)
        check(f"фон {rows - 1} имён: измерение {'есть' if want else 'нет'}",
              np.isfinite(exc) == want, f"exc={exc}, width={width}")
        check(f"ширина фона названа числом ({rows})", width == rows - 1,
              f"{width}")


def test_cross_section_excludes_neighbours_with_own_event():
    """Сосед со своим падением не годится в фон — и не только сосед в ту
    же секунду.

    Загрязняет фон тот, чей ОТСКОК накрывает наш замер, а его падение
    случилось раньше. Поэтому здесь событие соседей отстоит от нашего на
    двести секунд: проверяется ширина защитного окна, а не сам факт
    запрета. Узкое окно оставляло бы такого соседа в фоне, и превышение
    занижалось бы ровно там, где падают многие — то есть в самых
    интересных моментах (урок T1).
    """
    n = 2600
    rows, nb, j = 120, 60, 1800
    P = np.full((rows, n), 100.0)
    P[0, j:] = 96.0                              # наше падение
    P[0, j + 60:] = 96.0 * 1.02                  # наш отскок
    for r in range(1, nb + 1):
        P[r, j - 200:] = 96.0                    # упали раньше нас
        P[r, j + 100:] = 96.0 * 1.02             # а отскок внутри нашего окна
    NXT = matrix_index(P)
    ev_rows = [0] + list(range(1, nb + 1))
    ev_cols = [j] + [j - 200] * nb
    g = D.guard_sec(5, 300)
    check("защитное окно шире расстояния до соседа", g >= 200, f"{g}")
    banned = D.guard_matrix(P.shape, ev_rows, ev_cols, g)
    _, _, exc_all, w_all = D.excess(P, NXT, 0, j, 5, 300, None)
    _, _, exc_g, w_g = D.excess(P, NXT, 0, j, 5, 300, banned[:, j])
    check("без защиты фон широкий", w_all == rows - 1, f"{w_all}")
    check("с защитой соседи выброшены", w_g == rows - 1 - nb, f"{w_g}")
    check("грязный фон прячет эффект", abs(exc_all) < 1e-9, f"{exc_all}")
    check("превышение с защитой больше", exc_g > exc_all + 0.005,
          f"{exc_g} против {exc_all}")


def test_background_uses_the_same_execution_rule():
    """Фон считается той же функцией, что событие.

    Если бы у фона был свой вход (например, без задержки), в разность
    вошло бы правило исполнения, а не рынок. Проверка прямая: сдвиг
    задержки обязан двигать и фон тоже.
    """
    n = 2200
    rows = 60
    P = np.full((rows, n), 100.0)
    # Рынок растёт ПОСЛЕ входа: движение до входа сделке не достаётся, и
    # фон обязан мерить ровно тот кусок, что и событие.
    P[:, 1900:] = 101.0
    P[0, 1800:] = 96.0
    P[0, 1900:] = 97.0
    NXT = matrix_index(P)
    _, bg1, _, _ = D.excess(P, NXT, 0, 1800, 1, 300, None)
    check("фон несёт движение рынка", bg1 > 0.005, f"{bg1}")


def test_single_row_and_matrix_paths_agree():
    """Внутри самого ядра путей исполнения два, и они обязаны совпасть.

    `trade` считает одну ногу (её зовёт живая половина), `returns_matrix`
    — всю матрицу разом (её зовёт кросс-секция). Разойдись они, событие
    и фон считались бы разными правилами, а разность выглядела бы эджем.
    """
    rng = np.random.default_rng(20260812)
    rows, n = 12, 3000
    P = np.full((rows, n), np.nan)
    for r in range(rows):
        px = 100.0
        for j in range(n):
            px *= 1.0 + rng.normal(0.0, 0.0005)
            if rng.random() > 0.12:              # дыры записи
                P[r, j] = px
    NXT = matrix_index(P)
    bad = 0
    for j in (1000, 1500, 2000):
        for d in D.DELAYS:
            for h in (300, 900):
                m = D.returns_matrix(P, NXT, j, d, h)
                for r in range(rows):
                    one, _, _ = D.trade(P[r], NXT[r], j, d, h)
                    if np.isnan(one) and np.isnan(m[r]):
                        continue
                    if not (abs(one - m[r]) < 1e-15):
                        bad += 1
    check("одиночный и матричный пути совпадают", bad == 0,
          f"{bad} расхождений")


def test_delay_axis_decays_as_the_rebound_is_given_away():
    """Сквозная проверка: чем позже вход, тем меньше остаётся.

    Убывание — не только свойство рынка, но и признак того, что ось
    задержки вообще подключена. Спека требует его как условие
    немедленной остановки: не убывает — мера сломана.
    """
    n = 3000
    rows = 60
    j = 1800
    P = np.full((rows, n), 100.0)
    P[0, j:] = 96.0
    # отскок раздаётся ровно по секунде: вход позже ловит меньше
    for k in range(0, 120):
        P[0, j + k:] = 96.0 * (1.0 + 0.0002 * k)
    NXT = matrix_index(P)
    got = []
    for d in (1, 5, 15, 30, 60):
        _, _, exc, _ = D.excess(P, NXT, 0, j, d, 300, None)
        got.append(exc)
    check("превышение убывает с задержкой",
          all(got[i] > got[i + 1] for i in range(len(got) - 1)),
          f"{[round(x * 1e4, 1) for x in got]}")


# --- живая половина ---------------------------------------------------

def test_live_and_replay_agree_bit_for_bit():
    """То, ради чего ядро одно.

    Сканер зовёт `live_fall` по своей очереди середин, реплей — `falls`
    по матрице. Разойдись они, живая калибровка исполнения описывала бы
    другую сделку, и обе половины выглядели бы исправными.
    """
    rng = np.random.default_rng(20260812)
    t0 = 1_800_000_000
    times, mids = [], []
    px = 100.0
    for k in range(2000):
        if rng.random() < 0.1:                 # дыры, как у живого прохода
            continue
        px *= 1.0 + rng.normal(0.0, 0.0004)
        times.append(t0 + k + rng.random())
        mids.append(px)
    row = D.place(times, mids, t0, 2000)
    f = D.falls(row)
    bad = 0
    for j in (1000, 1200, 1500, 1900):
        live = D.live_fall(times, mids, t0 + j + 0.99)
        book = f[j]
        if not (np.isnan(live) and np.isnan(book)) \
                and not (abs(live - book) < 1e-15):
            bad += 1
    check("живой счёт совпадает с реплеем", bad == 0, f"{bad} расхождений")


# --- объявленное спекой ------------------------------------------------

def test_declared_grid_matches_the_spec():
    """Сетка объявлена спекой и после результата не меняется.

    Молчаливый сдвиг константы — самая дешёвая форма подгонки: числа
    остаются правдоподобными, а ячейка вердикта становится другой.
    """
    check("окно 15 минут", D.W_SEC == 900, f"{D.W_SEC}")
    check("пороги падения", D.DROPS == (0.03, 0.05), f"{D.DROPS}")
    check("ось задержки", D.DELAYS == (1, 5, 15, 30, 60), f"{D.DELAYS}")
    check("горизонты", D.HORIZONS_SEC == (300, 900, 1800),
          f"{D.HORIZONS_SEC}")
    check("ячейка вердикта одна",
          D.VERDICT_CELL == {"drop": 0.03, "delay_sec": 5,
                             "horizon_sec": 1800}, f"{D.VERDICT_CELL}")
    check("пол фона 50 имён", D.MIN_CROSS == 50, f"{D.MIN_CROSS}")
    check("эпизод 5 минут", D.EPISODE_SEC == 300, f"{D.EPISODE_SEC}")


def test_episodes_glue_the_market_wide_drop():
    """Сотня событий в одну минуту — одно наблюдение, а не сто."""
    t = np.array([0.0, 10.0, 20.0, 1000.0, 1010.0])
    ep = D.episodes(t)
    check("два эпизода", len(np.unique(ep)) == 2, f"{np.unique(ep)}")


def main():
    print("сетка и время")
    test_place_takes_the_last_price_of_the_second()
    test_place_ignores_order_of_input()
    test_gap_is_a_gap_not_a_carried_price()
    print("окно во времени")
    test_window_is_time_not_cells()
    test_reference_is_the_nearest_not_the_older_one()
    test_missing_reference_is_not_zero()
    print("событие")
    test_detect_finds_the_declared_fall()
    test_dedup_counts_one_event_per_window()
    print("вход и выход")
    test_entry_at_the_decision_second_is_refused()
    test_entry_is_the_first_price_strictly_after_the_delay()
    test_entry_refuses_a_stale_price()
    test_horizon_runs_from_the_actual_entry()
    print("кросс-секция")
    test_cross_section_floor_is_not_zero()
    test_cross_section_excludes_neighbours_with_own_event()
    test_background_uses_the_same_execution_rule()
    test_single_row_and_matrix_paths_agree()
    test_delay_axis_decays_as_the_rebound_is_given_away()
    print("живая половина")
    test_live_and_replay_agree_bit_for_bit()
    print("объявленное спекой")
    test_declared_grid_matches_the_spec()
    test_episodes_glue_the_market_wide_drop()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
