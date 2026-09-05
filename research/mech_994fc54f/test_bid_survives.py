#!/usr/bin/env python3
"""
Тесты механики 994fc54f — поглощение после падения.

Здесь два места, где легко соврать себе в свою пользу, и оба закрыты
синтетикой с известным заранее ответом.

Первое — **метка**. Она считается по потоку за минуту, и если окно
случайно захватит хоть что-то после своего конца, разрез окажется
заглядыванием в будущее, а выглядеть будет как находка. Проверяется
прямо: будущее за окном переписывается целиком, метка обязана не
шелохнуться.

Второе — **сама мера**. Сломанная загрузка и сломанный разрез выглядят
ровно как «эффекта нет», и в этом проекте так дважды печатался нулевой
отчёт. Поэтому калибровочная пара: подсаженный разрез мера обязана
найти, а на шуме — промолчать.

    python3 research/mech_994fc54f/test_bid_survives.py
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
           os.path.join(RESEARCH, "factory")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bid_survives as A                                         # noqa: E402
import detect as D                                         # noqa: E402
import passive as PS                                       # noqa: E402
import run_d1 as R                                         # noqa: E402
import stability as SB                                     # noqa: E402
from store import Writer                                   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def tape(rows):
    """`(время, цена, объём, сторона)` массивами, как их даёт запись."""
    if not rows:
        e = np.empty(0)
        return e, e, e, e
    a = np.array(rows, dtype=np.float64)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


# --- вход и метка -----------------------------------------------------

def test_entry_never_earlier_than_the_label():
    """Вход не раньше, чем метка становится известна.

    Заявка объявила δ = 60 с, а метку — по потоку за 60 с от пятой
    секунды, то есть по данным до 65-й. Вход на шестидесятой торговал бы
    знанием, которого в тот момент нет.
    """
    check("вход не раньше конца окна метки",
          A.entry_wait() >= A.MARK_DELAY_SEC + A.T_SEC,
          f"{A.entry_wait()} против {A.MARK_DELAY_SEC + A.T_SEC}")
    check("объявленные 60 с уступают 65",
          A.entry_wait(5, 60, 60) == 65, f"{A.entry_wait(5, 60, 60)}")
    check("объявленный вход позже метки не сдвигается",
          A.entry_wait(5, 10, 120) == 120, f"{A.entry_wait(5, 10, 120)}")


def test_label_does_not_look_beyond_T():
    """Поток ПОСЛЕ окна метку не решает."""
    j = 0
    late = [[float(A.MARK_DELAY_SEC + A.T_SEC + 5), 99.0, 10000.0, -1]]
    tt, tp, tv, ts = tape(late)
    lab, _ = A.mark_event(tt, tp, tv, ts, j, limit=100.0, queue=10.0,
                          size=50.0)
    check("поток за окном не съедает бид", lab == "пережил", lab)


def test_future_beyond_the_window_does_not_move_the_mark():
    """Переписали будущее за окном — метка, поток и снятие не дрогнули.

    Тест на заглядывание. Прошлое обязано не шелохнуться; если
    шелохнулось, разрез считает то, чего в момент решения не знали.
    """
    inside = [[10.0, 99.5, 5.0, -1]]
    after = [[200.0, 99.0, 100000.0, -1], [400.0, 98.0, 100000.0, -1]]
    got = []
    for extra in ([], after):
        tt, tp, tv, ts = tape(inside + extra)
        lab, _ = A.mark_event(tt, tp, tv, ts, 0, 100.0, 10.0, 50.0)
        flow = A.flow_through(tt, tp, tv, ts, float(A.MARK_DELAY_SEC),
                              100.0)
        got.append((lab, flow))
    check("метка не смотрит дальше T", got[0] == got[1],
          f"{got[0]} против {got[1]}")


def test_shown_queue_decides_the_label():
    """Знаменатель поглощения — ПОКАЗАННЫЙ размер уровня.

    Ровно его не было ни у одного из четырёх замеров ленты: они считали
    числитель, то есть «сколько агрессии прошло».
    """
    rows = [[float(A.MARK_DELAY_SEC + 1 + k), 99.5, 20.0, -1]
            for k in range(10)]
    tt, tp, tv, ts = tape(rows)
    thin, _ = A.mark_event(tt, tp, tv, ts, 0, 100.0, queue=1.0, size=1.0)
    thick, _ = A.mark_event(tt, tp, tv, ts, 0, 100.0, queue=1000.0,
                            size=1.0)
    check("тонкая очередь выедается", thin == "выеден", thin)
    check("толстая очередь переживает", thick == "пережил", thick)


def test_flow_agrees_with_the_fill_model():
    """Диагностика и метка считают одно и то же.

    Поток — числитель, решение принимает `passive.fill_at`. Разойдись
    они, отчёт объяснял бы разрез одной величиной, а строил другой.
    """
    rng = np.random.default_rng(11)
    bad = 0
    for _ in range(60):
        n = int(rng.integers(1, 12))
        rows = [[float(A.MARK_DELAY_SEC + 1 + k),
                 100.0 + float(rng.normal(0, 1)),
                 float(rng.uniform(1, 60)),
                 float(rng.choice([-1.0, 1.0]))] for k in range(n)]
        tt, tp, tv, ts = tape(rows)
        q, size = float(rng.uniform(0, 40)), float(rng.uniform(0, 40))
        lab, _ = A.mark_event(tt, tp, tv, ts, 0, 100.0, q, size)
        flow = A.flow_through(tt, tp, tv, ts, float(A.MARK_DELAY_SEC),
                              100.0)
        if (flow >= q + size) != (lab == "выеден"):
            bad += 1
    check("поток и модель очереди согласны", bad == 0, f"расхождений {bad}")


def test_pulled_level_is_told_apart():
    """Уровень, ушедший без единого принта, считается отдельно."""
    check("снят без принта", A.level_pulled(0.0, 100.0, 99.0) is True)
    check("выдержал принты", A.level_pulled(5.0, 100.0, 99.0) is False)
    check("бид на месте", A.level_pulled(0.0, 100.0, 100.0) is False)
    check("цены после окна нет — не измерено",
          A.level_pulled(0.0, 100.0, None) is None)


# --- фон и агрегат ----------------------------------------------------

def _matrix(nrows, own_ret, bg_ret, n=400):
    """Матрица «символы × секунды»: строка 0 своя, остальные фон."""
    P = np.full((nrows, n), 100.0, dtype=np.float32)
    P[0, 200:] = 100.0 * (1.0 + own_ret)
    P[1:, 200:] = 100.0 * (1.0 + bg_ret)
    NXT = np.empty(P.shape, dtype=np.int32)
    for r in range(P.shape[0]):
        NXT[r] = D.fill_index(P[r])[1]
    return P, NXT


def test_thin_background_is_not_measured():
    """Фон тоньше пола — не ноль, а отсутствие измерения."""
    P, NXT = _matrix(D.MIN_CROSS + 1, 0.02, 0.0)
    fat = A.bg_mean(P, NXT, 0, 100, 1, 99, None)
    P2, NXT2 = _matrix(D.MIN_CROSS - 10, 0.02, 0.0)
    thin = A.bg_mean(P2, NXT2, 0, 100, 1, 99, None)
    check("широкий фон измеряется", np.isfinite(fat), f"{fat}")
    check("тонкий фон не измеряется", not np.isfinite(thin), f"{thin}")


def _rows(vals, labels, t0=1_700_000_000.0, gap=1.0, day="2026-08-10"):
    return [{"sym": f"S{i}", "t": t0 + i * gap, "day": day,
             "exc_med": v, "label": lab}
            for i, (v, lab) in enumerate(zip(vals, labels))]


def test_group_counts_episodes_not_events():
    """Шесть событий одной минуты — одно наблюдение, а не шесть."""
    rows = _rows([0.01] * 6, ["пережил"] * 6, gap=10.0)
    g = A.group_stats(rows)
    check("эпизод один", g["episodes"] == 1, f"{g['episodes']}")
    check("событий шесть", g["events"] == 6, f"{g['events']}")
    far = _rows([0.01] * 3, ["пережил"] * 3, gap=D.EPISODE_SEC * 3)
    check("разнесённые события — разные эпизоды",
          A.group_stats(far)["episodes"] == 3,
          f"{A.group_stats(far)['episodes']}")


def test_ceiling_is_the_best_subset():
    """Верхняя граница — лучшее подмножество при идеальном знании."""
    split = {"пережил": {"median_bp": 10.0}, "выеден": {"median_bp": 40.0}}
    check("берётся лучшее из двух", A.ceiling_bp(split) == 40.0,
          f"{A.ceiling_bp(split)}")
    check("нечего мерить — не ноль",
          A.ceiling_bp({"пережил": {"median_bp": None},
                        "выеден": {"median_bp": None}}) is None)


# --- нуль -------------------------------------------------------------

def _two_days(n=15):
    """Сутки с одной меткой и сутки с другой. Значения различаются."""
    rows = []
    for k in range(n):
        rows.append({"sym": f"A{k}", "t": 1_700_000_000.0 + k * 600,
                     "day": "2026-08-10", "exc_med": 0.004,
                     "label": "пережил"})
    for k in range(n):
        rows.append({"sym": f"B{k}", "t": 1_700_100_000.0 + k * 600,
                     "day": "2026-08-11", "exc_med": -0.004,
                     "label": "выеден"})
    return rows


def test_null_permutes_inside_the_day():
    """Перестановка идёт ВНУТРИ суток, а не по всей выборке.

    Проверяется свойством, которое ни с чем не спутать: если все события
    суток несут одну метку, перестановка внутри суток не меняет НИЧЕГО —
    разброс нуля обязан быть ровно нулевым. Глобальная перестановка
    смешала бы сутки, и разброс появился бы.
    """
    rows = _two_days()
    n = A.null_permutation(rows, perms=25)
    surv = A.group_stats([r for r in rows if r["label"] == "пережил"])
    check("нуль внутри суток ничего не переставил", n["sd_bp"] == 0.0,
          f"{n['sd_bp']}")
    check("нуль совпал с прогоном",
          n["pct95_bp"] == surv["median_bp"],
          f"{n['pct95_bp']} против {surv['median_bp']}")


def test_null_is_reproducible():
    """Зерно — число: нуль, который нельзя повторить, не проверяем."""
    rows = _rows([0.01, -0.01, 0.02, -0.02, 0.005, -0.005],
                 ["пережил", "выеден"] * 3, gap=D.EPISODE_SEC * 3)
    a = A.null_permutation(rows, perms=20)
    b = A.null_permutation(rows, perms=20)
    check("нуль воспроизводим", a == b, f"{a} против {b}")


def test_calibration_pair():
    """Подсаженный разрез мера обязана найти, на шуме — промолчать.

    Без этой пары отрицательный результат ничего не значит: сломанная
    загрузка выглядит ровно как «эффекта нет».
    """
    rows, rng = [], np.random.default_rng(7)
    plant = np.random.default_rng(3)
    for k in range(60):
        lab = "пережил" if k % 2 == 0 else "выеден"
        shift = 0.006 if lab == "пережил" else -0.006
        rows.append({"sym": f"S{k}", "t": 1_700_000_000.0 + k * 600,
                     "day": f"2026-08-{10 + k // 10:02d}",
                     "label": lab,
                     "exc_med": shift + float(plant.normal(0, 0.004))})
    split = A.by_label(rows)
    null = A.null_permutation(rows, perms=100)
    check("подсаженный разрез найден",
          split["пережил"]["median_bp"] > split["выеден"]["median_bp"],
          f"{split['пережил']['median_bp']} против "
          f"{split['выеден']['median_bp']}")
    check("подсаженный разрез перебивает нуль",
          split["пережил"]["median_bp"] > null["pct95_bp"],
          f"{split['пережил']['median_bp']} против {null['pct95_bp']}")

    noise = [dict(r, exc_med=float(rng.normal(0, 0.01))) for r in rows]
    nsplit = A.by_label(noise)
    nnull = A.null_permutation(noise, perms=100)
    check("на шуме мера молчит",
          nsplit["пережил"]["median_bp"] <= nnull["pct95_bp"],
          f"{nsplit['пережил']['median_bp']} против {nnull['pct95_bp']}")


# --- книга по дням ----------------------------------------------------

def _book_rows(n, t=1_700_000_000.0, own=0.01, same_name=False):
    return [{"sym": "ONE" if same_name else f"S{k}", "t": t,
             "day": "2026-08-10", "own": own} for k in range(n)]


def test_slots_are_respected():
    """Мест шесть, и седьмой сигнал в книгу не входит."""
    daily = A.replay_days(_book_rows(10))
    one = A.NAME_CAP * (0.01 - A.COST_ROUND_BP / 1e4) * 100.0
    got = sum(daily.values())
    check("взято ровно шесть ног", abs(got - A.SLOTS * one) < 1e-9,
          f"{got} против {A.SLOTS * one}")


def test_one_position_per_name():
    """Одна позиция на имя: три сигнала по одной монете — одна нога."""
    daily = A.replay_days(_book_rows(3, same_name=True))
    one = A.NAME_CAP * (0.01 - A.COST_ROUND_BP / 1e4) * 100.0
    got = sum(daily.values())
    check("нога одна", abs(got - one) < 1e-9, f"{got} против {one}")


def test_form_uses_the_project_measure():
    """Форма считается ОБЩЕЙ мерой проекта, а не своей."""
    daily = {20670: 0.3, 20671: -0.1, 20672: 0.2, 20673: -2.0,
             20674: 0.25, 20675: 0.1, 20676: 0.05, 20677: -0.2,
             20678: 0.15, 20679: 0.4, 20680: 0.05}
    check("форма совпадает с stability.stats",
          A.form_stats(daily) == SB.stats(daily),
          f"{A.form_stats(daily)}")


def test_trade_day_share_is_measurability():
    daily = {20670: 0.3, 20672: -0.1}
    check("доля суток со сделками", A.trade_day_share(daily, 10) == 0.2,
          f"{A.trade_day_share(daily, 10)}")
    check("суток нет — не ноль",
          A.trade_day_share(daily, 0) is None)


# --- показ и вердикт --------------------------------------------------

def test_absent_value_is_a_dash_not_zero():
    """Величины, которой нет, — прочерк. Ноль означает «измерено»."""
    check("нет величины — прочерк", A._num(None) == "—", A._num(None))
    check("ноль печатается нулём", A._num(0.0) == "+0.0", A._num(0.0))


def _art(ceil, surv=None, eat=None, n95=None):
    surv = {"median_bp": ceil if surv is None else surv, "episodes": 400,
            "share_pos": 0.7, "events": 900, "mean_bp": ceil, "names": 30}
    eat = {"median_bp": -10.0 if eat is None else eat, "episodes": 300,
           "share_pos": 0.4, "events": 800, "mean_bp": -10.0, "names": 30}
    return {"ceiling_bp": ceil, "cost_round_bp": 17.4,
            "split": {"пережил": surv, "выеден": eat},
            "split_mean": {"пережил": dict(surv), "выеден": dict(eat)},
            "null": {"pct95_bp": n95}}


def test_reading_is_derived_from_the_number():
    """Вердиктовая фраза выводится из числа, а не стоит рядом с ним."""
    low = A.reading(_art(A.NEED_BP - 1.0, n95=0.0))
    high = A.reading(_art(A.NEED_BP + 20.0, n95=0.0))
    check("ниже порога — закрыто", "Закрыто первым же числом" in low, low)
    check("выше порога — не закрыто",
          "Закрыто первым же числом" not in high, high)
    check("нечего мерить — сказано словами",
          "Судить нечем" in A.reading(_art(None)))


def test_killers_are_named_by_number():
    k = A.killers(dict(_art(A.NEED_BP - 1.0, n95=0.0),
                       form={"голая нога": None, "с хеджем BTC": None,
                             "суток со сделками": 0.10, "дней": 3}))
    check("верхняя граница сработала",
          "СРАБОТАЛ" in k["1. верхняя граница"], k["1. верхняя граница"])
    check("измеримость формы не пройдена",
          "НЕ ПРОЙДЕНА" in k["измеримость формы"], k["измеримость формы"])


# --- сквозной прогон --------------------------------------------------

J_EV = 3600            # событие ровно в начале суток
STEP = 5               # снимок раз в пять секунд
SPAN = 7800            # длина куска записи, секунды
NSYM = 55              # фон обязан быть шире D.MIN_CROSS


def build_day(root, with_event=True):
    """Сутки записи: два события с разным ответом книги и ровный фон."""
    w = Writer(root)
    t0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
    for r in range(NSYM):
        sym = f"S{r:03d}USDT"
        for j in range(0, SPAN, STEP):
            px = 100.0
            if with_event and r in (0, 1) and j >= J_EV:
                px = 96.0
                if j >= J_EV + 70:
                    px = 94.0 if r == 0 else 98.0
            t = t0 + j
            bid, ask = px * 0.999, px * 1.001
            w.write("book", sym, {
                "s": sym, "ts": int(t * 1000), "u": 1,
                "bid": bid, "ask": ask, "bid_sz": 10.0, "ask_sz": 10.0,
                "upd": 1, "b": [[bid, 10.0]], "a": [[ask, 10.0]],
                "t": round(float(t), 3)}, ts=t)
            if r in (0, 1):
                # Строка 0 — бид выеден: продающая агрессия сквозь него
                # много больше очереди плюс нашего размера. Строка 1 —
                # бид пережил: продажи есть, но их не хватает.
                w.write("trades", sym, {
                    "ts": int(t * 1000), "s": sym, "side": -1,
                    "p": bid * 0.999, "v": 400.0 if r == 0 else 1.0},
                    ts=t)
    w.flush()
    w.close()
    return t0


def run_main(with_event=True):
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "store")
        build_day(root, with_event=with_event)
        out = os.path.join(tmp, "out")
        argv, pub = sys.argv, R.publish
        R.publish = lambda msg: None
        sys.argv = ["bid_survives.py", "--root", root, "--out", out,
                    "--tag", "t", "--no-publish",
                    "--live", os.path.join(tmp, "нет-такого.json")]
        try:
            A.main()
        finally:
            sys.argv, R.publish = argv, pub
        return (json.load(open(os.path.join(out, "MECH-bidsurv-t.json"),
                               encoding="utf-8")),
                open(os.path.join(out, "MECH-bidsurv-t.md"),
                     encoding="utf-8").read())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_end_to_end_splits_the_two_subsets():
    art, md = run_main()
    s = art["split"]
    check("оба подмножества найдены",
          s["пережил"]["events"] == 1 and s["выеден"]["events"] == 1,
          f"{s['пережил']['events']} / {s['выеден']['events']}")
    check("выживший отскочил, выеденный упал",
          s["пережил"]["median_bp"] > 0 > s["выеден"]["median_bp"],
          f"{s['пережил']['median_bp']} / {s['выеден']['median_bp']}")
    check("вход считается на 65-й секунде", art["entry_sec"] == 65,
          f"{art['entry_sec']}")
    check("отчёт написан и говорит о входе",
          "65-й секунде" in md, md[:200])
    check("верхняя граница есть",
          art["ceiling_bp"] == s["пережил"]["median_bp"],
          f"{art['ceiling_bp']}")
    check("вердикт выведен из числа",
          isinstance(art["reading"], str) and len(art["reading"]) > 40,
          str(art["reading"])[:120])


def test_end_to_end_refuses_when_there_are_no_events():
    """Ноль наблюдений при непустом входе — отказ, а не пустой отчёт."""
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "store")
        w = Writer(root)
        t0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
        for r in range(2):
            sym = f"F{r:03d}USDT"
            for j in range(0, SPAN, STEP):
                t = t0 + j
                w.write("book", sym, {
                    "s": sym, "ts": int(t * 1000), "u": 1,
                    "bid": 99.9, "ask": 100.1, "bid_sz": 10.0,
                    "ask_sz": 10.0, "upd": 1,
                    "b": [[99.9, 10.0]], "a": [[100.1, 10.0]],
                    "t": round(float(t), 3)}, ts=t)
        w.flush()
        w.close()
        argv, pub = sys.argv, R.publish
        R.publish = lambda msg: None
        sys.argv = ["bid_survives.py", "--root", root,
                    "--out", os.path.join(tmp, "out"), "--tag", "e",
                    "--no-publish", "--live", os.path.join(tmp, "нет.json")]
        got = None
        try:
            A.main()
        except SystemExit as e:
            got = str(e)
        except BaseException as e:                        # noqa: BLE001
            got = f"НЕ ОТКАЗ: {type(e).__name__}: {e}"
        finally:
            sys.argv, R.publish = argv, pub
        check("пустота названа отказом",
              got is not None and got.startswith("ОТКАЗ"), str(got)[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("вход и метка")
    test_entry_never_earlier_than_the_label()
    test_label_does_not_look_beyond_T()
    test_future_beyond_the_window_does_not_move_the_mark()
    test_shown_queue_decides_the_label()
    test_flow_agrees_with_the_fill_model()
    test_pulled_level_is_told_apart()
    print("фон и агрегат")
    test_thin_background_is_not_measured()
    test_group_counts_episodes_not_events()
    test_ceiling_is_the_best_subset()
    print("нуль")
    test_null_permutes_inside_the_day()
    test_null_is_reproducible()
    test_calibration_pair()
    print("книга по дням")
    test_slots_are_respected()
    test_one_position_per_name()
    test_form_uses_the_project_measure()
    test_trade_day_share_is_measurability()
    print("показ и вердикт")
    test_absent_value_is_a_dash_not_zero()
    test_reading_is_derived_from_the_number()
    test_killers_are_named_by_number()
    print("сквозной прогон")
    test_end_to_end_splits_the_two_subsets()
    test_end_to_end_refuses_when_there_are_no_events()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
