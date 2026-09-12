#!/usr/bin/env python3
"""
Тесты механики d71203f0 — неспровоцированный принт ликвидации.

Здесь три места, где легче всего соврать себе в свою пользу, и каждое
закрыто синтетикой с известным заранее ответом.

**Заглядывание в будущее.** Тишина шести окон решает, брать ли событие, и
если хоть одно из окон зацепит секунду после решения, разрез окажется
знанием будущего, а выглядеть будет находкой. Проверяется прямо: будущее
переписывается целиком, прошлое обязано не шелохнуться. Отдельно
проверяется, что σ берётся у ПРОШЛЫХ суток: сквозной прогон построен так,
что подмена «σ нынешних суток» меняет число неспровоцированных событий.

**Сама мера.** Сломанная загрузка и перевёрнутая метка стороны выглядят
ровно как «эффекта нет», и в этом проекте так дважды печатался нулевой
отчёт. Поэтому калибровочная пара: подсаженный откат мера обязана найти,
а на перемешанных сторонах — промолчать.

**Пустота.** Ноль наблюдений при непустом входе и метка стороны, которую
выбрать нечем, обязаны быть ОТКАЗОМ, а не отчётом с прочерками.

Цены сквозного прогона подаются матрицей, а не файлами снимков: чтение
снимков — код D1 (`run_d1.load_day`), закреплённый его собственными
тестами, и переписывать сотни тысяч строк JSON на каждую подделку
негативного контроля значило бы платить минутами за уже проверенное.
Принты ликвидаций при этом настоящие — они пишутся `store.Writer` и
читаются `probe_liqsplit.liq_of_day`, то есть ровно тем путём, которым их
читает прогон.

    python3 research/mech_d71203f0/test_unprovoked.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in (HERE, os.path.join(RESEARCH, "d1_seconds"),
           os.path.join(RESEARCH, "b1_book"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "probe_liqsplit"),
           os.path.join(RESEARCH, "dca_ladder")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import detect as D                                          # noqa: E402
import run_d1 as R                                          # noqa: E402
import stability as SB                                      # noqa: E402
import unprovoked as U                                      # noqa: E402
import run_unprovoked as RUN                                # noqa: E402
from store import Writer                                    # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def run_test(fn):
    """Прогнать проверку так, чтобы её ПАДЕНИЕ было сосчитано, а не
    оборвало сюиту.

    Тест, умерший исключением, уносит с собой все проверки, стоящие
    после него, и сводки падений не печатается вовсе — снаружи это
    неотличимо от «их не было». Цена этого не теоретическая: приёмка
    фабрики (`runlog._run_tests`) читает ПОСЛЕДНИЕ 4000 символов вывода
    и по сводке судит, какая проверка укусила. Оборванная сюита
    оставляет в хвосте трассировку вместо имён, и кусающийся негативный
    контроль объявляется холостым — на этом отчёт постройки 12.09 и был
    отвергнут дважды.

    Поэтому исключение становится ИМЕНОВАННЫМ падением: имя теста,
    класс ошибки и хвост трассировки. Сводка печатается всегда.
    """
    try:
        fn()
    except BaseException as e:                              # noqa: BLE001
        import traceback
        print(f"  ПАДЕНИЕ {fn.__name__}: {type(e).__name__}: {e}")
        print(traceback.format_exc().rstrip()[-1000:])
        FAILED.append(fn.__name__)


# ======================================================================
# 1. Склейка принтов
# ======================================================================

def test_glue():
    ts = [100.0, 130.0, 155.0, 400.0, 430.0]
    usd = [10.0, 20.0, 30.0, 40.0, 50.0]
    got = U.glue_prints(ts, usd)
    check("принты в пределах 60 с — одно событие",
          len(got) == 2 and got[0][2] == 3 and got[1][2] == 2,
          f"событий {len(got)}: {got}")
    check("принты дальше 60 с — разные события",
          len(U.glue_prints([0.0, 61.0, 122.0], [1.0, 1.0, 1.0])) == 3,
          str(U.glue_prints([0.0, 61.0, 122.0], [1.0, 1.0, 1.0])))
    check("нотионал кластера суммируется",
          abs(got[0][1] - 60.0) < 1e-9 and abs(got[1][1] - 90.0) < 1e-9,
          str(got))
    check("время события — первый принт кластера",
          got[0][0] == 100.0 and got[1][0] == 400.0, str(got[:2]))
    check("пустой вход — пустой выход", U.glue_prints([], []) == [])


# ======================================================================
# 2. Калибровка метки стороны
# ======================================================================

def test_side_calibration():
    """Assert на долю: 0.34 у LIQSPLIT означает метку `Buy` у лонга."""
    n = 1000
    n_sell = 340
    mark, why = U.long_mark(n_sell, n - n_sell)
    assert abs(n_sell / n - 0.34) < 1e-9, "доля подсадки не 0.34"
    check("доля Sell 0.34 маркирует лонга меткой Buy", mark == "Buy",
          f"{mark}: {why}")
    check("обратная доля маркирует лонга меткой Sell",
          U.long_mark(n - n_sell, n_sell)[0] == "Sell",
          str(U.long_mark(n - n_sell, n_sell)))
    check("доля у половины — отказ, а не выбор",
          U.long_mark(500, 500)[0] is None, str(U.long_mark(500, 500)))
    check("доля на краю полосы — всё ещё отказ",
          U.long_mark(480, 520)[0] is None, str(U.long_mark(480, 520)))
    check("принтов меньше пола — метка не измерена",
          U.long_mark(0, U.MIN_CALIB_PRINTS - 1)[0] is None,
          str(U.long_mark(0, U.MIN_CALIB_PRINTS - 1)))
    check("вторая сторона выводится из первой",
          U.other_side("Buy") == "Sell" and U.other_side(None) is None)


# ======================================================================
# 3. σ: два отказа вместо нуля
# ======================================================================

def test_sigma_refuses_instead_of_zero():
    rng = np.random.default_rng(3)
    live = rng.normal(0, 0.001, U.MIN_SIGMA_PTS * 2)
    check("живой ряд даёт положительную σ",
          (U.sigma_of(live) or 0) > 0, str(U.sigma_of(live)))
    check("мало секунд с ценой — σ не измерена",
          U.sigma_of(live[:U.MIN_SIGMA_PTS - 1]) is None,
          str(U.sigma_of(live[:U.MIN_SIGMA_PTS - 1])))
    frozen = np.zeros(U.MIN_SIGMA_PTS * 2)
    check("замороженный ряд — σ не измерена", U.sigma_of(frozen) is None,
          str(U.sigma_of(frozen)))
    holey = np.full(U.MIN_SIGMA_PTS * 2, np.nan)
    holey[:10] = live[:10]
    check("дыра в записи — σ не измерена", U.sigma_of(holey) is None,
          str(U.sigma_of(holey)))


# ======================================================================
# 4. Тишина шести окон
# ======================================================================

SIG = {60: 0.001, 300: 0.002, 3600: 0.004}


def _mv(v, **over):
    out = {w: v for w in U.WINDOWS_SEC}
    for w, x in over.items():
        out[int(w)] = x
    return out


def test_quiet_six_windows():
    check("тишина шести окон найдена",
          U.quiet_of(_mv(0.0), _mv(0.0), SIG, SIG) is True)
    loud_own = _mv(0.0, **{"300": 0.01})
    check("громкий ход имени — не тишина",
          U.quiet_of(loud_own, _mv(0.0), SIG, SIG) is False,
          str(U.quiet_of(loud_own, _mv(0.0), SIG, SIG)))
    loud_cross = _mv(0.0, **{"3600": 0.05})
    check("громкая кросс-секция — не тишина",
          U.quiet_of(_mv(0.0), loud_cross, SIG, SIG) is False,
          str(U.quiet_of(_mv(0.0), loud_cross, SIG, SIG)))
    check("нет σ — не измерено, а не отсутствие тишины",
          U.quiet_of(_mv(0.0), _mv(0.0), None, SIG) is None,
          str(U.quiet_of(_mv(0.0), _mv(0.0), None, SIG)))
    check("нет хода — не измерено",
          U.quiet_of(_mv(float("nan")), _mv(0.0), SIG, SIG) is None)
    check("два σ шире одного",
          U.quiet_of(_mv(0.0015), _mv(0.0), SIG, SIG) is False
          and U.quiet_of(_mv(0.0015), _mv(0.0), SIG, SIG,
                         k=U.K_SIGMA_DIAG) is True)


# ======================================================================
# 5. Заглядывание в будущее
# ======================================================================

SPAN = 8000                       # длина куска синтетики, секунды
STEP = 5                          # снимок раз в пять секунд, как у записи
NSYM = 55                         # фон обязан быть шире detect.MIN_CROSS
N_SEC = R.DAY_SEC + 2 * R.PAD_SEC
PAD = R.PAD_SEC
J_A = PAD + 5400                  # неспровоцированное событие, строка 0
J_B = PAD + 6000                  # неспровоцированное событие, строка 1
J_C0 = PAD + 600                  # начало падения строк 2..5
J_C1 = PAD + 1500                 # конец падения
J_D = J_A                         # событие строки 7: ход мал, но заметен
FALLERS = (2, 3, 4, 5)
LOUD_ROW = 7
JITTER = 0.0002                   # 2 б.п. — из этого и берётся σ суток


def _grid():
    return np.arange(0, N_SEC, STEP, dtype=np.int64)


def calm_matrix(seed=11):
    """Спокойные сутки: цена дрожит, из этого дрожания и считается σ."""
    P = np.full((NSYM, N_SEC), np.nan, dtype=np.float32)
    idx = _grid()
    rng = np.random.default_rng(seed)
    for r in range(NSYM):
        P[r, idx] = 100.0 * (1.0 + rng.normal(0, JITTER, len(idx)))
    return P


def event_matrix(tail=150.0, tail0=100.5):
    """Сутки события: две тихие строки с подсаженным откатом и шумные.

    Строки 0 и 1 — тишина шести окон и откат +50 б.п. ПОСЛЕ входа.
    Строки 2..5 — падение на 5 %: их принты спровоцированы по построению.
    Строка 7 — ход 20 б.п. перед принтом (больше вчерашней σ, меньше
    сегодняшней): по вчерашней σ она спровоцирована, по сегодняшней была
    бы тихой, и на этом ловится подмена σ.

    `tail` и `tail0` переписывают БУДУЩЕЕ — цену строк 7 и 0 дальше, чем
    достаёт любое измерение события. Ими проверяется, что прошлое не
    шелохнулось: `tail0` лежит за выходом из позиции, но внутри
    шестидесятиминутного окна, если его отсчитывать ВПЕРЁД.
    """
    P = np.full((NSYM, N_SEC), np.nan, dtype=np.float32)
    idx = _grid()
    P[:, idx] = 100.0
    P[0, idx[idx >= J_A + 10]] = 100.5
    P[0, idx[idx >= J_A + 3000]] = float(tail0)
    P[1, idx[idx >= J_B + 10]] = 100.5
    for r in FALLERS:
        mid = idx[(idx >= J_C0) & (idx <= J_C1)]
        P[r, mid] = 100.0 - 5.0 * (mid - J_C0) / float(J_C1 - J_C0)
        P[r, idx[idx > J_C1]] = 95.0
    P[LOUD_ROW, idx[(idx >= J_D - 55) & (idx < J_D + 2000)]] = 100.2
    P[LOUD_ROW, idx[idx >= J_D + 2000]] = float(tail)
    return P


def _scan(P, ev):
    return U.scan_day(P, PAD, PAD + R.DAY_SEC, ev)


def test_future_does_not_move_the_past():
    """Переписали будущее — прошлое не шелохнулось.

    Проверяются обе половины тишины: собственный ход имени в секунде
    события и медианный ход кросс-секции до этой секунды.
    """
    ev = {0: [J_A], 1: [J_B]}
    a = _scan(event_matrix(), ev)
    b = _scan(event_matrix(tail=400.0, tail0=130.0), ev)
    check("будущее не двигает ход в секунде события",
          a["moves"][0][J_A] == b["moves"][0][J_A],
          f"{a['moves'][0][J_A]} против {b['moves'][0][J_A]}")
    g = J_A // U.CROSS_STEP_SEC
    same = all(np.array_equal(
        np.nan_to_num(a["cross_med"][w][:g + 1], nan=-9.0),
        np.nan_to_num(b["cross_med"][w][:g + 1], nan=-9.0))
        for w in U.WINDOWS_SEC)
    check("будущее не двигает кросс-секцию до события", same)
    sig = {w: 0.001 for w in U.WINDOWS_SEC}
    qa = U.quiet_of(a["moves"][0][J_A], U.cross_at(a["cross_med"], J_A),
                    sig, sig)
    qb = U.quiet_of(b["moves"][0][J_A], U.cross_at(b["cross_med"], J_A),
                    sig, sig)
    check("будущее не двигает вердикт тишины", qa == qb and qa is True,
          f"{qa} против {qb}")


def test_cross_is_taken_not_later_than_the_event():
    """Кросс-секция берётся с сетки НЕ ПОЗЖЕ секунды события."""
    step = U.CROSS_STEP_SEC
    arr = np.arange(100, dtype=np.float64)
    cm = {w: arr.copy() for w in U.WINDOWS_SEC}
    j = 5 * step + step - 1            # секунда между узлами сетки
    got = U.cross_at(cm, j, step=step)
    check("кросс-секция берётся не позже секунды события",
          got[60] == 5.0, f"{got[60]} при j={j}, шаг {step}")
    check("за сеткой — прочерк, а не край",
          U.cross_at(cm, 10_000 * step, step=step)[60] is None)


def test_scan_refuses_frozen_rows():
    """Замороженная строка не попадает в тихие через нулевую σ."""
    P = np.full((NSYM, N_SEC), np.nan, dtype=np.float32)
    idx = _grid()
    P[:, idx] = 100.0
    sc = _scan(P, {0: [J_A]})
    check("замороженная строка — σ не измерена",
          sc["sigma_own"][0][60] is None, str(sc["sigma_own"][0][60]))
    check("замороженное сечение — σ не измерена",
          sc["sigma_cross"][60] is None, str(sc["sigma_cross"][60]))
    check("без σ тишина не объявляется",
          U.quiet_of(sc["moves"][0][J_A], U.cross_at(sc["cross_med"], J_A),
                     sc["sigma_own"][0], sc["sigma_cross"]) is None)


# ======================================================================
# 6. Агрегат
# ======================================================================

def _rows(vals, quiet=True, t0=1_700_000_000.0, gap=1.0, day="2026-08-10",
          side="Buy", usd=1000.0):
    return [{"sym": f"S{i}", "t": t0 + i * gap, "day": day, "side": side,
             "usd": usd + i, "quiet": quiet, "exc": v, "own": v}
            for i, v in enumerate(vals)]


def test_group_counts_episodes_not_events():
    rows = _rows([0.01] * 6, gap=10.0)
    g = U.group_stats(rows)
    check("эпизоды считаются вместо событий",
          g["episodes"] == 1 and g["events"] == 6,
          f"эпизодов {g['episodes']}, событий {g['events']}")
    far = _rows([0.01] * 3, gap=D.EPISODE_SEC * 3)
    check("разнесённые события — разные эпизоды",
          U.group_stats(far)["episodes"] == 3)
    check("пустая группа — прочерки, а не нули",
          U.group_stats([])["mean_bp"] is None)


def test_ceiling_is_the_best_horizon():
    rows = [dict(r, exc_h5=0.001, exc_h30=0.0005)
            for r in _rows([0.002] * 4, gap=D.EPISODE_SEC * 3)]
    got = U.ceiling_bp(rows, ["exc", "exc_h5", "exc_h30"])
    check("потолок — лучший горизонт, а не худший", abs(got - 20.0) < 1e-6,
          str(got))
    check("мерить нечего — прочерк, не ноль",
          U.ceiling_bp([], ["exc"]) is None)


def test_concentration_columns():
    rows = []
    for k in range(9):
        rows.append({"sym": "MANY" if k == 0 else f"S{k}",
                     "t": 1_700_000_000.0 + k * D.EPISODE_SEC * 3,
                     "day": f"2026-08-{10 + k:02d}", "side": "Buy",
                     "usd": 100.0, "quiet": True,
                     "exc": 0.05 if k == 0 else -0.001,
                     "own": 0.0})
    g, name = U.drop_best_name(rows)
    check("без лучшего имени убирается лучшее",
          name == "MANY" and g["mean_bp"] < 0,
          f"{name}, {g['mean_bp']}")
    g2, days = U.drop_best_days(rows, k=3)
    check("без трёх лучших суток убираются лучшие",
          "2026-08-10" in days and len(days) == 3 and g2["mean_bp"] < 0,
          f"{days}, {g2['mean_bp']}")
    check("нечего убирать — прочерк",
          U.drop_best_name([])[1] is None)


def test_null_takes_the_95th_percentile():
    rows = []
    for k in range(6):
        rows.append({"sym": f"S{k}",
                     "t": 1_700_000_000.0 + k * D.EPISODE_SEC * 3,
                     "day": "2026-08-10", "side": "Buy", "usd": 1.0,
                     "quiet": True, "exc": 0.002, "own": 0.002,
                     "null": [0.0001 * (s + 1) for s in
                              range(U.NULL_SEEDS)]})
    n = U.null_stats(rows)
    check("нуль берёт 95-й процентиль по зёрнам",
          abs(n["pct95_bp"] - 9.55) < 0.2,
          f"{n['pct95_bp']} при среднем {n['mean_bp']}")
    check("нуль воспроизводим", U.null_stats(rows) == n)
    check("нуля нет — прочерк", U.null_stats([])["pct95_bp"] is None)


def test_calibration_pair():
    """Подсаженный откат мера находит; перемешанные стороны — молчит.

    Без этой пары отрицательный результат ничего не значит: сломанная
    загрузка и перевёрнутая метка стороны выглядят ровно как «эффекта
    нет», и в этом проекте так уже печатался нулевой отчёт.
    """
    rows, plant = [], np.random.default_rng(5)
    for k in range(80):
        quiet = k % 2 == 0
        side = "Buy" if k % 4 < 2 else "Sell"
        base = 0.006 if (quiet and side == "Buy") else 0.0
        if quiet and side == "Sell":
            base = -0.006
        rows.append({"sym": f"S{k}", "day": f"2026-08-{10 + k // 20:02d}",
                     "t": 1_700_000_000.0 + k * D.EPISODE_SEC * 3,
                     "side": side, "usd": 100.0, "quiet": quiet,
                     "exc": base + float(plant.normal(0, 0.0005)),
                     "own": 0.0})
    sp = U.split_by_quiet([r for r in rows if r["side"] == "Buy"])
    check("подсаженный откат найден",
          sp[U.GROUPS[0]]["mean_bp"] > sp[U.GROUPS[1]]["mean_bp"] + 30,
          f"{sp[U.GROUPS[0]]['mean_bp']} против "
          f"{sp[U.GROUPS[1]]['mean_bp']}")
    rng = np.random.default_rng(17)
    sides = np.array([r["side"] for r in rows], dtype=object)
    mixed = [dict(r, side=str(s))
             for r, s in zip(rows, sides[rng.permutation(len(rows))])]
    sp2 = U.split_by_quiet([r for r in mixed if r["side"] == "Buy"])
    check("перемешанные стороны дают ноль",
          abs(sp2[U.GROUPS[0]]["mean_bp"]) < 30,
          f"{sp2[U.GROUPS[0]]['mean_bp']}")


# ======================================================================
# 7. Касса реплея и форма
# ======================================================================

def test_one_position_per_name():
    # Доход у ПЕРВОГО принта, у остальных ноль: пока прежняя позиция
    # открыта, новый принт того же имени не берётся, и средняя за сутки
    # обязана остаться единицей. Взяли бы все пять — вышло бы 0.2 %.
    rows = [{"sym": "ONE", "t": 1_700_000_000.0 + k, "day": "2026-08-10",
             "own": 0.01 if k == 0 else 0.0, "side": "Buy", "usd": 1.0,
             "quiet": True} for k in range(5)]
    d = U.daily_series(rows, 0.0)
    check("одна позиция на имя",
          len(d) == 1 and abs(d[list(d)[0]] - 1.0) < 1e-6, str(d))
    far = [dict(r, sym=f"S{k}") for k, r in enumerate(rows)]
    d2 = U.daily_series(far, 0.0)
    check("разные имена берутся все",
          len(d2) == 1 and abs(d2[list(d2)[0]] - 0.2) < 1e-6, str(d2))
    d3 = U.daily_series(rows, 100.0)
    check("издержки вычитаются из каждой позиции",
          abs(d3[list(d3)[0]] - 0.0) < 1e-6, str(d3))


def test_form_uses_the_project_measure():
    daily = {20670: 0.3, 20671: -0.1, 20672: 0.2, 20673: -2.0,
             20674: 0.25, 20675: 0.1, 20676: 0.05, 20677: -0.2,
             20678: 0.15, 20679: 0.4, 20680: 0.05}
    check("форма считается общей мерой проекта",
          U.form_stats(daily) == SB.stats(daily), str(U.form_stats(daily)))
    check("закрытых суток нет — прочерк", U.form_stats({}) is None)


def test_modules_come_from_where_they_should():
    """Чужой тёзка на пути импорта опознаётся отказом, а не работой.

    Поймано живым смоуком: `ceiling.py` есть и у фабрики, и у
    `t4_structure`, и порядок чужих импортов отдавал прогону не тот —
    падение приходило на ПОСЛЕДНЕМ шаге, после всего счёта.
    """
    check("потолок берётся у фабрики, а не у тёзки",
          U.module_origin(U.CE) == "factory", U.CE.__file__)
    check("форма берётся у фабрики", U.module_origin(U.SB) == "factory",
          U.SB.__file__)
    check("ядро берётся у d1_seconds",
          U.module_origin(U.D) == "d1_seconds", U.D.__file__)
    check("связь считает та же функция, что и потолок фабрики",
          U.CE.pair_corr is not None and hasattr(U.CE, "MAX_CORR"))
    got = None
    try:
        U.check_origin(U.D, "factory")
    except ImportError as e:
        got = str(e)
    check("чужой тёзка опознаётся отказом",
          got is not None and "чужой модуль" in got, str(got))


def test_live_corr_is_a_dash_when_nothing_to_compare():
    check("связи нет — прочерк, а не ноль",
          U.live_corr({1: 1.0}, {})[0] is None,
          str(U.live_corr({1: 1.0}, {})))
    same = {d: float(d % 7) for d in range(20700, 20740)}
    r, who, k = U.live_corr(same, {"книга": same})
    check("совпадающие ряды дают связь 1",
          r is not None and abs(r - 1.0) < 1e-6 and who == "книга",
          f"{r} / {who} / {k}")


# ======================================================================
# 8. Показ и вердикт
# ======================================================================

def _art(mean_unp, mean_prov=-10.0, med=50.0, n95=0.0, ceil=None):
    unp = {"events": 900, "episodes": 400, "mean_bp": mean_unp,
           "median_bp": mean_unp, "share_pos": 0.6, "names": 40}
    prov = {"events": 900, "episodes": 400, "mean_bp": mean_prov,
            "median_bp": mean_prov, "share_pos": 0.4, "names": 40}
    return {"split": {U.GROUPS[0]: unp, U.GROUPS[1]: prov},
            "events_per_day_median": med, "days_live": 30, "dead_days": 2,
            "null": {"pct95_bp": n95, "seeds": U.NULL_SEEDS},
            "ceiling_bp": mean_unp if ceil is None else ceil,
            "no_best_name": dict(unp), "best_name": "AAAUSDT",
            "no_best_days": dict(unp), "best_days": ["a", "b", "c"]}


def test_absent_value_is_a_dash_not_zero():
    check("величины нет — прочерк", U._num(None) == "—", U._num(None))
    check("ноль печатается нулём", U._num(0.0) == "+0.0", U._num(0.0))


def test_reading_is_derived_from_the_number():
    low_vol = U.reading(_art(60.0, med=float(U.MIN_EVENTS_PER_DAY - 1)))
    check("вердикт выведен из числа", "Закрыто объёмом" in low_vol,
          low_vol[:90])
    poor = U.reading(_art(U.NEED_MEAN_BP - 1.0))
    check("ниже круга тейкера — закрыто экономикой",
          "Закрыто" in poor, poor[:90])
    same = U.reading(_art(40.0, mean_prov=45.0, ceil=45.0))
    check("спровоцированные не хуже — закрыто механизмом",
          "Закрыто механизмом" in same, same[:90])
    null_hit = U.reading(_art(40.0, mean_prov=-10.0, n95=45.0, ceil=45.0))
    check("нуль не перебит — закрыто нулём", "Закрыто нулём" in null_hit,
          null_hit[:90])
    open_dir = U.reading(_art(25.0))
    check("выше круга, ниже планки — направление открыто",
          "книги нет" in open_dir, open_dir[:120])
    big = U.reading(_art(80.0))
    check("выше планки — убийцы пройдены",
          "Все четыре убийцы пройдены" in big, big[:90])


def test_killers_are_named_by_number():
    k = U.killers(_art(U.NEED_MEAN_BP - 1.0,
                       med=float(U.MIN_EVENTS_PER_DAY - 1)))
    check("убийцы названы числом",
          "СРАБОТАЛ" in k["1. объём"] and "СРАБОТАЛ" in k["2. экономика"],
          f"{k['1. объём']} | {k['2. экономика']}")
    k2 = U.killers(_art(60.0))
    check("убийца, который не сработал, так и сказан",
          "не сработал" in k2["2. экономика"], k2["2. экономика"])
    check("планка D1 названа отдельно от убийц",
          "не убийца" in " ".join(k2), list(k2))


# ======================================================================
# 9. Сквозной прогон
# ======================================================================

DAY1 = "2026-08-05"               # только σ
DAY2 = "2026-08-06"               # лента ликвидаций молчит
DAY3 = "2026-08-07"               # сутки события
DAYS = (DAY1, DAY2, DAY3)


def build_store(tmp, with_liq=True, sides=None):
    """Каталог записи: пустые файлы книги и НАСТОЯЩИЕ файлы ликвидаций.

    Книга подаётся матрицей (см. шапку), поэтому здесь от неё нужен
    только список имён и часов, который читает `run_d1.available`.
    """
    root = os.path.join(tmp, "store")
    book = os.path.join(root, "book")
    for r in range(NSYM):
        d = os.path.join(book, f"S{r:03d}USDT")
        os.makedirs(d, exist_ok=True)
        for day in DAYS:
            open(os.path.join(d, f"{day}-00.jsonl"), "w").close()
    if not with_liq:
        return root
    w = Writer(root)
    t1 = R.day_bounds(DAY1)
    # Принты первых суток: они обязаны пропасть — σ прошлых суток нет.
    for k, j in enumerate((PAD + 1000, PAD + 2000)):
        w.write("liq", "S000USDT",
                {"ts": int((t1 - PAD + j) * 1000), "side": "Buy",
                 "p": 100.0, "v": 5.0}, ts=t1 - PAD + j)
    t3 = R.day_bounds(DAY3) - PAD
    put = sides or (lambda i: "Buy")
    n = 0
    for row, j in ((0, J_A), (1, J_B), (LOUD_ROW, J_D)):
        w.write("liq", f"S{row:03d}USDT",
                {"ts": int((t3 + j) * 1000), "side": put(n), "p": 100.0,
                 "v": 20.0}, ts=t3 + j)
        n += 1
    for row in FALLERS:
        for j in range(PAD + 700, PAD + 1126, 25):
            w.write("liq", f"S{row:03d}USDT",
                    {"ts": int((t3 + j) * 1000), "side": put(n),
                     "p": 99.0, "v": 3.0}, ts=t3 + j)
            n += 1
    w.flush()
    w.close()
    return root


def fake_load_day(root, syms, day, jobs=1, log=print):
    """Матрица суток вместо чтения снимков. Форма — как у `load_day`."""
    t0 = R.day_bounds(day) - R.PAD_SEC
    P = event_matrix() if day == DAY3 else calm_matrix(
        seed=11 if day == DAY1 else 12)
    return P, t0, N_SEC


def run_main(root, out, days=0, extra=()):
    argv, load, pub = sys.argv, R.load_day, R.publish
    R.load_day = fake_load_day
    R.publish = lambda msg: None
    sys.argv = ["run_unprovoked.py", "--root", root, "--out", out,
                "--tag", "t", "--no-publish", "--live",
                os.path.join(out, "нет-такого.json")] + list(extra)
    if days:
        sys.argv += ["--days", str(days)]
    try:
        RUN.main()
    finally:
        sys.argv, R.load_day, R.publish = argv, load, pub
    with open(os.path.join(out, "MECH-unprov-t.json"), encoding="utf-8") as f:
        art = json.load(f)
    with open(os.path.join(out, "MECH-unprov-t.md"), encoding="utf-8") as f:
        md = f.read()
    return art, md


_E2E = {}


def e2e():
    if "art" not in _E2E:
        tmp = tempfile.mkdtemp()
        try:
            root = build_store(tmp)
            out = os.path.join(tmp, "out")
            _E2E["art"], _E2E["md"] = run_main(root, out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return _E2E["art"], _E2E["md"]


def test_end_to_end():
    art, md = e2e()
    check("сторона калибрована по падениям",
          art["long_mark"] == "Buy" and art["calib_buy"] == 72
          and art["calib_sell"] == 0,
          f"{art['long_mark']}, Buy {art['calib_buy']}, "
          f"Sell {art['calib_sell']}")
    check("первые сутки идут только на σ",
          art["days_sigma_only"] == 1 and art["events_glued"] == 27,
          f"{art['days_sigma_only']}, событий {art['events_glued']}")
    check("молчащие сутки сосчитаны",
          art["dead_days"] == 1 and art["days_live"] == 1,
          f"молчащих {art['dead_days']}, живых {art['days_live']}")
    unp = art["split"][U.GROUPS[0]]
    prov = art["split"][U.GROUPS[1]]
    check("σ берётся у прошлых суток",
          art["events_unprovoked"] == 2,
          f"неспровоцированных {art['events_unprovoked']} "
          f"(ожидалось 2: строки 0 и 1)")
    check("подсаженный откат найден прогоном",
          unp["mean_bp"] is not None and abs(unp["mean_bp"] - 50.0) < 3.0,
          str(unp))
    # Обе величины проверяются на прочерк, а не одна: сравнение
    # `None > float` роняет сюиту вместо того, чтобы назвать падение по
    # имени, и о правиле, ради которого проверка написана, такое падение
    # не говорит ничего.
    check("неспровоцированные выше спровоцированных",
          prov["mean_bp"] is not None and unp["mean_bp"] is not None
          and unp["mean_bp"] > prov["mean_bp"],
          f"{unp['mean_bp']} против {prov['mean_bp']}")
    check("спровоцированные сосчитаны тем же кодом",
          prov["events"] == 25, str(prov["events"]))
    check("убийца объёма сработал числом",
          "СРАБОТАЛ" in art["killers"]["1. объём"]
          and "2.0" in art["killers"]["1. объём"],
          art["killers"]["1. объём"])
    check("нуль измерен по зёрнам",
          (art["null"] or {}).get("seeds") == U.NULL_SEEDS,
          str(art["null"]))
    check("отчёт написан и называет шесть окон",
          "шесть окон" in md and "неспровоцированные" in md, md[:200])
    check("отчёт печатает вердикт из артефакта",
          art["reading"][:40] in md, art["reading"][:80])


def test_end_to_end_refuses_on_empty_tape():
    """Ноль принтов при живой записи — отказ, а не отчёт с прочерками."""
    tmp = tempfile.mkdtemp()
    try:
        root = build_store(tmp, with_liq=False)
        got = None
        try:
            run_main(root, os.path.join(tmp, "out"))
        except SystemExit as e:
            got = str(e)
        except BaseException as e:                          # noqa: BLE001
            got = f"НЕ ОТКАЗ: {type(e).__name__}: {e}"
        check("пустота названа отказом",
              got is not None and got.startswith("ОТКАЗ")
              and "нечего мерить" in got, str(got)[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_undetermined_side_is_refused():
    """Долю Sell у половины выбрать нечем — прогон ОТКАЗЫВАЕТСЯ.

    Молчаливый выбор перевернул бы знак каждой сделки с вероятностью в
    половину, а перевёрнутый знак неотличим от «эффекта нет».
    """
    tmp = tempfile.mkdtemp()
    try:
        root = build_store(
            tmp, sides=lambda i: "Buy" if i % 2 == 0 else "Sell")
        got = None
        try:
            run_main(root, os.path.join(tmp, "out"))
        except SystemExit as e:
            got = str(e)
        except BaseException as e:                          # noqa: BLE001
            got = f"НЕ ОТКАЗ: {type(e).__name__}: {e}"
        check("неразличимая сторона — отказ прогона",
              got is not None and got.startswith("ОТКАЗ")
              and "метку стороны" in got, str(got)[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_one_day_is_refused():
    """Одни сутки — σ прошлых суток взять неоткуда, и это отказ."""
    tmp = tempfile.mkdtemp()
    try:
        root = build_store(tmp)
        got = None
        try:
            run_main(root, os.path.join(tmp, "out"), days=1)
        except SystemExit as e:
            got = str(e)
        except BaseException as e:                          # noqa: BLE001
            got = f"НЕ ОТКАЗ: {type(e).__name__}: {e}"
        check("одни сутки — отказ",
              got is not None and got.startswith("ОТКАЗ")
              and "ПРОШЛЫХ" in got, str(got)[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    # Каждая проверка идёт через `run_test`: упавшая на исключении не
    # вправе уносить с собой соседей и сводку падений.
    for title, tests in (
            ("склейка принтов", (test_glue,)),
            ("калибровка стороны", (test_side_calibration,)),
            ("сигма", (test_sigma_refuses_instead_of_zero,)),
            ("тишина шести окон", (test_quiet_six_windows,)),
            ("заглядывание в будущее",
             (test_future_does_not_move_the_past,
              test_cross_is_taken_not_later_than_the_event,
              test_scan_refuses_frozen_rows)),
            ("агрегат",
             (test_group_counts_episodes_not_events,
              test_ceiling_is_the_best_horizon,
              test_concentration_columns,
              test_null_takes_the_95th_percentile,
              test_calibration_pair)),
            ("касса реплея",
             (test_one_position_per_name,
              test_form_uses_the_project_measure,
              test_modules_come_from_where_they_should,
              test_live_corr_is_a_dash_when_nothing_to_compare)),
            ("показ и вердикт",
             (test_absent_value_is_a_dash_not_zero,
              test_reading_is_derived_from_the_number,
              test_killers_are_named_by_number)),
            ("сквозной прогон",
             (test_end_to_end,
              test_end_to_end_refuses_on_empty_tape,
              test_undetermined_side_is_refused,
              test_one_day_is_refused))):
        print(title)
        for fn in tests:
            run_test(fn)
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
