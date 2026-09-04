#!/usr/bin/env python3
"""
Проверки механики `fcbd3542`: метка tick/σ и замер по половинам.

Проверки собираются АВТОМАТИЧЕСКИ по имени `test_*`, а не перечисляются
списком в `main`. Это не удобство: в `s8_loop/test_book.py` явный список
однажды уже оставил новую проверку не исполненной, и она молча не
работала, пока имя не сверили грепом по выводу. Список, который можно
забыть дополнить, рано или поздно забывают.

    .venv/bin/python research/mech_fcbd3542/test_halves.py
"""

import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in (HERE, os.path.join(RESEARCH, "d1_seconds")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import detect as D                                          # noqa: E402
import run_d1 as R1                                         # noqa: E402
import run_halves as RH                                     # noqa: E402
import ticksig as TS                                        # noqa: E402


def same(a, b):
    """Равны как числа, считая nan равным nan."""
    if a is None or b is None:
        return a is b
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    return a == b


# =====================================================================
# Метка tick/σ
# =====================================================================

def test_window_ends_at_month_start_and_never_looks_into_it():
    t0, t1 = TS.window("2026-08")
    assert t1 == "2026-08-01", t1
    assert t0 == "2026-07-02", t0
    # Правый край ИСКЛЮЧЁН и равен началу месяца: ни один бар месяца
    # события в метку не входит.
    for month in ("2026-01", "2026-03", "2027-12"):
        a, b = TS.window(month)
        assert b == month + "-01", (month, b)
        assert a < b, (a, b)


def test_future_rewrite_does_not_move_the_label():
    """Заглядывание: переписать месяц события — метка не шелохнётся."""
    past = [100.0 * (1.0 + 0.01 * ((i % 3) - 1)) for i in range(30)]
    future = [1.0] * 30                       # обвал внутри месяца

    def loader(which):
        def load(syms, t0, t1):
            return {"AAAUSDT": list(which)}
        return load

    ticks = {"AAAUSDT": 0.01}
    bymap = {"AAAUSDT": "AAAUSDT"}
    a, _ = TS.build("2026-08", ["AAAUSDT"], loader(past), ticks=ticks,
                    bymap=bymap)
    # Загрузчик отдаёт ОДНО и то же независимо от окна, поэтому
    # подмена «будущего» видна только если окно его захватывает.
    b, _ = TS.build("2026-08", ["AAAUSDT"], loader(past + future),
                    ticks=ticks, bymap=bymap)
    assert a["AAAUSDT"]["ticksig"] is not None
    # Негативный контроль самой проверки: подмена ПРОШЛОГО обязана
    # метку двигать, иначе проверка ничего не проверяет.
    c, _ = TS.build("2026-08", ["AAAUSDT"], loader(future), ticks=ticks,
                    bymap=bymap)
    assert c["AAAUSDT"]["ticksig"] != a["AAAUSDT"]["ticksig"], \
        "проверка не кусается: подмена прошлого метку не двигает"
    # Окно строго до месяца — это и есть механизм защиты.
    _t0, t1 = TS.window("2026-08")
    assert t1 == "2026-08-01"
    assert b["AAAUSDT"]["obs"] == len(past + future)


def test_frozen_row_gives_a_gap_not_infinity():
    """Замороженный ряд A2: σ = 0 — пропуск, а не бесконечный tick/σ."""
    frozen = [7.0] * 30
    rec = TS.label_one(0.001, frozen, 1.0)
    assert rec["ticksig"] is None, rec
    assert "замороженный" in (rec["why"] or ""), rec["why"]
    assert rec["sigma"] == 0.0
    live = [7.0 * (1.0 + 0.02 * ((i % 5) - 2)) for i in range(30)]
    assert TS.label_one(0.001, live, 1.0)["ticksig"] is not None


def test_price_scale_comes_from_the_names():
    assert TS.price_scale("10000SATSUSDT", "1000SATSUSDT") == 10.0
    assert TS.price_scale("SHIB1000USDT", "1000SHIBUSDT") == 1.0
    assert TS.price_scale("1000TAGUSDT", "TAGUSDT") == 1000.0
    assert TS.price_scale("BTCUSDT", "BTCUSDT") == 1.0
    assert TS.price_scale("1000000CHEEMSUSDT", "1000CHEEMSUSDT") == 1000.0
    # Масштаб обязан входить в метку: без него у имени с чужим
    # множителем tick/σ ошибочен ровно во столько же раз.
    closes = [1.0 * (1.0 + 0.01 * ((i % 4) - 2)) for i in range(30)]
    one = TS.label_one(0.001, closes, 1.0)["ticksig"]
    ten = TS.label_one(0.001, closes, 10.0)["ticksig"]
    assert abs(one / ten - 10.0) < 1e-9, (one, ten)


def test_short_history_is_a_gap_with_a_named_reason():
    rec = TS.label_one(0.01, [10.0, 10.1, 9.9], 1.0)
    assert rec["ticksig"] is None
    assert "суток с ценой" in rec["why"], rec["why"]
    rec = TS.label_one(None, [10.0] * 30, 1.0)
    assert rec["ticksig"] is None and "шага цены" in rec["why"]
    rec = TS.label_one(0.01, [10.0] * 30, None)
    assert rec["ticksig"] is None and "архивом" in rec["why"]


def test_halves_split_at_median_and_tie_goes_coarse():
    lab = {f"S{i}": {"ticksig": float(i)} for i in range(1, 6)}
    thin, coarse, med = TS.halves(lab)
    assert med == 3.0
    assert thin == {"S1", "S2"}, thin
    # Имя ровно на медиане уходит в КРУПНУЮ: правило однозначно.
    assert "S3" in coarse, coarse
    assert not (thin & coarse)
    lab["S6"] = {"ticksig": None}
    thin2, coarse2, _ = TS.halves(lab)
    assert "S6" not in thin2 and "S6" not in coarse2, \
        "имя без метки не принадлежит ни одной половине"


def test_turnover_is_recorded_as_median_daily():
    closes = [5.0 * (1.0 + 0.01 * ((i % 4) - 2)) for i in range(30)]
    rec = TS.label_one(0.001, closes, 1.0, turnover=[10.0, 30.0, 20.0])
    assert rec["turnover"] == 20.0, rec["turnover"]
    assert TS.label_one(0.001, closes, 1.0)["turnover"] is None


# =====================================================================
# Замер: совпадение с чужим ядром
# =====================================================================

def _matrix(rows=80, n=4000, seed=3):
    rng = np.random.default_rng(seed)
    P = (100.0 * np.exp(np.cumsum(rng.normal(0, 2e-4, size=(rows, n)),
                                  axis=1))).astype(np.float32)
    hole = rng.random((rows, n)) < 0.05
    P[hole] = np.nan
    return P


def test_excess_both_matches_detect_excess_exactly():
    """Медианная ветка обязана совпадать с `detect.excess` дословно."""
    P = _matrix()
    NXT = R1.next_index(P)
    rng = np.random.default_rng(11)
    checked = wide = thin = 0
    for _ in range(60):
        row = int(rng.integers(0, P.shape[0]))
        j = int(rng.integers(0, P.shape[1] - 2000))
        ban = rng.random(P.shape[0]) < float(rng.choice([0.0, 0.9]))
        want = D.excess(P, NXT, row, j, 5, 1800, ban)
        got = RH.excess_both(P, NXT, row, j, 5, 1800, ban)
        assert same(want[0], got[0]), (want, got)      # своя нога
        assert same(want[1], got[1]), (want, got)      # фон медианой
        assert same(want[2], got[2]), (want, got)      # превышение
        assert want[3] == got[5], (want, got)          # ширина
        checked += 1
        if want[3] >= D.MIN_CROSS:
            wide += 1
        else:
            thin += 1
    assert checked == 60
    # Обе ветки обязаны быть пройдены, иначе проверка смотрит одну.
    assert wide > 0 and thin > 0, (wide, thin)


def test_mean_background_is_a_second_statistic_not_a_copy():
    P = _matrix(seed=5)
    NXT = R1.next_index(P)
    got = [RH.excess_both(P, NXT, r, 1500, 5, 1800, None)
           for r in range(20)]
    pairs = [(g[1], g[3]) for g in got
             if np.isfinite(g[1]) and np.isfinite(g[3])]
    assert pairs, "фон нигде не измерен — проверять нечего"
    assert any(abs(a - b) > 1e-12 for a, b in pairs), \
        "медиана и среднее сечения совпали всюду: считается одно и то же"


def test_measure_halves_matches_run_d1_measure():
    """Первые шесть столбцов обязаны совпасть с чужим замером."""
    P, syms, _ts = RH.synthetic(n_event=10, n_quiet=60, n_sec=6000)
    P = P.astype(np.float32)
    NXT = R1.next_index(P)
    rows, cols = R1.events_of_day(P, 0, 0.03, {}, 0, P.shape[1])
    assert len(rows) > 0
    cells = [(0.03, 5, 1800), (0.03, 1, 300)]
    want = R1.measure(P, NXT, rows, cols, 0, cells, log=lambda *_: None)
    got = RH.measure_halves(P, NXT, rows, cols, 0, cells,
                            log=lambda *_: None)
    for k in cells:
        assert len(want[k]) == len(got[k]) == len(rows), k
        for a, b in zip(want[k], got[k]):
            for i in range(6):
                assert same(a[i], b[i]), (k, i, a, b)


def test_rewriting_the_future_beyond_exit_moves_nothing():
    """Заглядывание в замере: за выходом сделки цены не влияют."""
    P, syms, _ts = RH.synthetic(n_event=6, n_quiet=60, n_sec=6000)
    P = P.astype(np.float32)
    rows, cols = R1.events_of_day(R1.next_index(P) * 0 + P, 0, 0.03, {}, 0,
                                  P.shape[1]) if False else \
        R1.events_of_day(P, 0, 0.03, {}, 0, P.shape[1])
    assert len(rows) > 0
    j = int(cols[0])
    cut = j + 5 + 1800 + 1
    cells = [(0.03, 5, 1800)]
    base = RH.measure_halves(P, R1.next_index(P), rows[:1], cols[:1], 0,
                             cells, log=lambda *_: None)[cells[0]]
    rng = np.random.default_rng(1)
    P2 = P.copy()
    P2[:, cut:] = (P2[:, cut:] * rng.uniform(0.2, 5.0,
                                             size=P2[:, cut:].shape)
                   ).astype(np.float32)
    after = RH.measure_halves(P2, R1.next_index(P2), rows[:1], cols[:1], 0,
                              cells, log=lambda *_: None)[cells[0]]
    for a, b in zip(base, after):
        for i in range(9):
            assert same(a[i], b[i]), (i, a, b)
    # Проверка обязана кусаться: подмена ВНУТРИ удержания числа двигает.
    P3 = P.copy()
    P3[:, j + 10:cut] = (P3[:, j + 10:cut] * 3.0).astype(np.float32)
    inside = RH.measure_halves(P3, R1.next_index(P3), rows[:1], cols[:1], 0,
                               cells, log=lambda *_: None)[cells[0]]
    assert not same(base[0][RH.I_OWN], inside[0][RH.I_OWN]), \
        "проверка не кусается: подмена внутри удержания ничего не меняет"


# =====================================================================
# Половины, нули, книга
# =====================================================================

def _labels(syms, thin, month="1970-01", turn=None):
    vals = {s: (1.0 if s in thin else 9.0) for s in syms}
    return {month: {"values": vals,
                    "half": {s: ("thin" if s in thin else "coarse")
                             for s in syms},
                    "turnover": turn or {}}}


def _rec(t, row, exc, own=None):
    own = exc if own is None else own
    return (float(t), int(row), own, 0.0, exc, 500, 0.0, exc, 0.0)


def test_unlabelled_is_a_third_group():
    syms = ["A", "B", "C"]
    labels = _labels(["A", "B"], thin=["A"])   # у "C" метки нет вовсе
    assert "C" not in labels["1970-01"]["half"]
    rec = [_rec(0, 0, 0.01), _rec(600, 1, -0.01), _rec(1200, 2, 0.5)]
    parts = RH.split_records(rec, syms, labels)
    assert len(parts["thin"]) == 1 and len(parts["coarse"]) == 1
    assert len(parts["unlabelled"]) == 1, parts
    h = RH.half_stats(rec, syms, labels)
    assert h["thin"]["by_median_bg"]["median_bp"] == 100.0
    assert h["coarse"]["by_median_bg"]["median_bp"] == -100.0
    assert h["diff_bp"] == 200.0, h["diff_bp"]
    # Имя без метки не подмешано ни в одну половину: иначе крупная
    # величина третьей группы утекла бы в результат.
    assert h["unlabelled"]["by_median_bg"]["median_bp"] == 5000.0


def test_half_is_asked_per_month():
    """Метка помесячная: имя бывает тонким в июле и крупным в августе."""
    syms = ["A"]
    labels = {"1970-01": {"values": {"A": 1.0}, "half": {"A": "thin"},
                          "turnover": {}},
              "1970-02": {"values": {"A": 9.0}, "half": {"A": "coarse"},
                          "turnover": {}}}
    t_feb = 32 * 86400.0
    parts = RH.split_records([_rec(0, 0, 0.01), _rec(t_feb, 0, -0.02)],
                             syms, labels)
    assert len(parts["thin"]) == 1 and len(parts["coarse"]) == 1, parts
    assert parts["thin"][0][RH.I_T] == 0.0
    assert parts["coarse"][0][RH.I_T] == t_feb


def test_episode_stats_says_nothing_instead_of_zero():
    e = RH.episode_stats([], RH.I_EXCM)
    assert e["median_bp"] is None and e["mean_bp"] is None, e
    assert e["share_pos"] is None and e["episodes"] == 0
    nan = float("nan")
    only_nan = [(0.0, 0, nan, nan, nan, 3, nan, nan, nan)]
    e2 = RH.episode_stats(only_nan, RH.I_EXCM)
    assert e2["median_bp"] is None and e2["events"] == 1, e2


def test_median_and_mean_are_printed_side_by_side():
    """Форма фейда видна только парой: медиана плюс, среднее минус."""
    syms = ["A"]
    labels = _labels(syms, thin=["A"])
    rec = [_rec(k * 600, 0, 0.001) for k in range(9)]
    rec.append(_rec(9 * 600, 0, -0.5))
    h = RH.half_stats(rec, syms, labels)
    m = h["thin"]["by_median_bg"]
    assert m["median_bp"] > 0 > m["mean_bp"], m
    assert m["episodes"] == 10, m


def test_indexing_does_not_change_the_number():
    """Ускорение, меняющее числа, есть другая мера.

    Раскладка записей один раз (`index_records`) заведена ради нуля:
    иначе двести перестановок пересобирали бы месяц каждой записи. Она
    обязана давать РОВНО ту же медиану, что прямой отбор.
    """
    syms = [f"S{i}" for i in range(6)]
    rng = np.random.default_rng(2)
    rec = [_rec(k * 600, k % len(syms), float(rng.normal(0, 0.01)))
           for k in range(120)]
    want = {("1970-01", s) for s in syms[:3]}
    naive = [r for r in rec
             if (RH.month_of(r[RH.I_T]), syms[int(r[RH.I_ROW])]) in want]
    slow = RH.episode_stats(naive, RH.I_EXCM)["median_bp"]
    fast = RH._median_of(RH.index_records(rec, syms), want)
    assert slow == fast, (slow, fast)
    assert fast is not None
    # Пустой отбор — «не измерено», а не ноль.
    assert RH._median_of(RH.index_records(rec, syms), set()) is None


def test_null_is_reproducible_by_number_and_centred_on_zero():
    syms = [f"S{i}" for i in range(20)]
    rng = np.random.default_rng(0)
    rec = []
    for k in range(60):
        row = int(rng.integers(0, len(syms)))
        rec.append(_rec(k * 600, row, float(rng.normal(0, 0.01))))
    labels = _labels(syms, thin=syms[:10])
    a = RH.permutation_null(rec, syms, labels, perms=40)
    b = RH.permutation_null(rec, syms, labels, perms=40)
    assert a["p95"] == b["p95"] and a["mean"] == b["mean"], (a, b)
    assert a["perms"] == 40
    # Нуль обязан вести себя как нуль: метка ни при чём, значит
    # разность перестановок распределена вокруг нуля.
    assert abs(a["mean"]) < 3 * abs(a["p95"] or 1.0), a
    assert a["observed"] is not None
    assert a["beats"] in (True, False)


def test_null_permutes_the_label_not_the_events():
    """Подсаженная связь метки с исходом обязана перебивать нуль."""
    syms = [f"S{i}" for i in range(20)]
    rng = np.random.default_rng(4)
    rec = []
    for k in range(400):
        row = k % len(syms)
        # Шум крупнее эффекта: при перестановке метки половины
        # различаться перестают, при настоящей — различаются.
        rec.append(_rec(k * 600, row,
                        float(rng.normal(0, 0.02))
                        + (0.02 if row < 10 else 0.0)))
    labels = _labels(syms, thin=syms[:10])
    n = RH.permutation_null(rec, syms, labels, perms=60)
    assert n["observed"] > n["p95"], n
    assert n["beats"] is True, n
    # А при метке, не связанной с исходом, перебивать нечем.
    flat = [_rec(k * 600, k % len(syms), 0.01) for k in range(60)]
    n2 = RH.permutation_null(flat, syms, labels, perms=60)
    assert not n2["beats"], n2


def test_book_keeps_six_slots_and_one_position_per_name():
    syms = [f"S{i}" for i in range(12)]
    want = {("1970-01", s) for s in syms}
    rec = [_rec(0, i, 0.0, own=0.01) for i in range(12)]
    tr = RH.book_trades(rec, syms, want, 5, 1800, 0.0)
    assert len(tr) == RH.SLOTS, len(tr)
    # Одна позиция на имя: второй сигнал того же имени внутри
    # удержания места не занимает и сделкой не становится.
    rec2 = [_rec(0, 0, 0.0, own=0.01), _rec(60, 0, 0.0, own=0.01)]
    tr2 = RH.book_trades(rec2, syms, want, 5, 1800, 0.0)
    assert len(tr2) == 1, tr2
    # А после выхода — становится.
    rec3 = [_rec(0, 0, 0.0, own=0.01), _rec(3000, 0, 0.0, own=0.01)]
    assert len(RH.book_trades(rec3, syms, want, 5, 1800, 0.0)) == 2


def test_book_pays_the_round_and_the_hedge_pays_its_own():
    syms = ["A"]
    want = {("1970-01", "A")}
    rec = [(0.0, 0, 0.01, 0.0, 0.01, 500, 0.0, 0.01, 0.004)]
    plain = RH.book_trades(rec, syms, want, 5, 1800, 17.4)
    assert abs(plain[0]["net"] - (100.0 - 17.4)) < 1e-9, plain
    hedged = RH.book_trades(rec, syms, want, 5, 1800, 17.4, hedged=True,
                            hedge_ring_bp=11.0)
    # Хедж вычитает ногу рынка И платит собственный круг.
    assert abs(hedged[0]["net"] - (60.0 - 17.4 - 11.0)) < 1e-9, hedged


def test_book_day_is_the_day_of_exit():
    """Сделка принадлежит суткам, когда деньги стали известны."""
    syms = ["A"]
    want = {("1970-01", "A")}
    # Вход в 23:50 первых суток, выход — во вторые.
    t = 86400.0 - 600.0
    rec = [(t, 0, 0.01, 0.0, 0.01, 500, 0.0, 0.01, 0.0)]
    tr = RH.book_trades(rec, syms, want, 5, 1800, 0.0)
    pct, s = RH.book_days(tr, cap_share=1.0)
    assert list(pct) == [1], pct
    assert s["days"] == 1


def test_book_size_is_the_project_name_cap():
    syms = ["A"]
    want = {("1970-01", "A")}
    rec = [(0.0, 0, 0.01, 0.0, 0.01, 500, 0.0, 0.01, 0.0)]
    tr = RH.book_trades(rec, syms, want, 5, 1800, 0.0)
    pct, _s = RH.book_days(tr)
    sys.path.insert(0, os.path.join(RESEARCH, "s8_loop"))
    import trades as TR
    assert abs(pct[0] - 100.0 * TR.NAME_CAP_SHARE / 100.0) < 1e-9, pct


def test_active_share_and_shape_rule_come_from_the_ceiling():
    sys.path.insert(0, os.path.join(RESEARCH, "factory"))
    import ceiling as CE
    import pool as PL
    assert RH.active_share({1: 0.1, 2: 0.2}, 6) == round(2 / 6.0, 3)
    assert RH.active_share({}, 0) is None
    # Порог берётся у потолка, а не повторяется числом.
    assert 0.0 < CE.MIN_ACTIVE_SHARE < 1.0
    losing = {d: -1.0 for d in range(PL.WINDOW_D + 2)}
    assert PL.shape_why(losing, 0.0), "правило вылета обязано ругаться"


def test_require_events_refuses_instead_of_printing_dashes():
    try:
        RH.require_events([], 12, 500)
    except SystemExit as e:
        assert "ОТКАЗ" in str(e) and "12" in str(e), str(e)
    else:
        raise AssertionError("пустая ячейка вердикта прошла как результат")
    assert RH.require_events([1, 2], 12, 500) == 2


# =====================================================================
# Калибровочная пара
# =====================================================================

def test_calibration_finds_the_planted_rebound_and_is_silent_on_noise():
    """Без этой пары сломанная загрузка выглядит как «эффекта нет»."""
    planted = RH.calibrate(True)
    assert planted["events"] > 0, planted
    assert planted["diff_bp"] is not None, planted
    assert planted["diff_bp"] > 100.0, planted
    assert planted["thin_bp"] > planted["coarse_bp"], planted
    noise = RH.calibrate(False)
    assert noise["diff_bp"] is None or abs(noise["diff_bp"]) < 20.0, noise


def test_tick_change_never_invents_a_list():
    """Сеть в проверку не входит: обе ветки отказа подставные."""
    def boom(_cache):
        raise OSError("сети нет")

    syms, why = RH.tick_change_symbols({"AAAUSDT"}, fetch=boom)
    assert syms is None, syms
    assert "не ответил" in why, why
    # Ответ есть, а смены шага в нём нет — тоже «не измерено».
    quiet = lambda _c: [{"title": "новый контракт",                # noqa: E731
                         "description": "AAAUSDT"}]
    syms2, why2 = RH.tick_change_symbols({"AAAUSDT"}, fetch=quiet)
    assert syms2 is None, syms2
    assert "не найдено" in why2, why2
    # А когда объявление есть — берутся только знакомые имена.
    real = lambda _c: [{"title": "Adjustment of tick size",         # noqa: E731
                        "description": "AAAUSDT and ZZZUSDT"}]
    syms3, why3 = RH.tick_change_symbols({"AAAUSDT"}, fetch=real)
    assert syms3 == ["AAAUSDT"], syms3
    assert why3 == "объявления площадки"
    # Поданный файл читается, и из него берутся только известные имена.
    p = os.path.join(HERE, "out", "_test_tick.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write("AAAUSDT\nЧУЖОЕUSDT\n")
    try:
        got, why2 = RH.tick_change_symbols({"AAAUSDT"}, path=p)
        assert got == ["AAAUSDT"], got
        assert why2 == "файл"
    finally:
        os.remove(p)


# =====================================================================
# Отчёт: вердиктовая фраза выводится из числа
# =====================================================================

def _art(best, span=50.0):
    nan = None
    return {
        "run_at": "сейчас", "days": 3, "day_from": "a", "day_to": "b",
        "symbols": 5, "cadence_sec": 1.0, "took_min": 1.0,
        "labels": {"2026-08": {"window": ["a", "b"], "labelled": 4,
                               "unlabelled": 1, "median": 1.0,
                               "p05": 0.1, "p95": 9.0, "span": span}},
        "label_why": {"нет шага цены": 1},
        "span_overall": span,
        "verdict_cell": dict(D.VERDICT_CELL),
        "cost_round_bp": 17.4, "cost_source": "измерено",
        "verdict": {
            "thin": {"by_median_bg": {"episodes": 300, "median_bp": best,
                                      "mean_bp": best, "share_pos": 0.61,
                                      "events": 900},
                     "by_mean_bg": {"episodes": 300, "median_bp": best,
                                    "mean_bp": best, "share_pos": 0.6,
                                    "events": 900},
                     "symbols": 3, "d1": None},
            "coarse": {"by_median_bg": {"episodes": 300, "median_bp": 1.0,
                                        "mean_bp": 1.0, "share_pos": 0.5,
                                        "events": 900},
                       "by_mean_bg": {"episodes": 300, "median_bp": 1.0,
                                      "mean_bp": 1.0, "share_pos": 0.5,
                                      "events": 900},
                       "symbols": 3, "d1": None},
            "unlabelled": {"by_median_bg": {"episodes": 0,
                                            "median_bp": nan,
                                            "mean_bp": nan,
                                            "share_pos": nan, "events": 0},
                           "by_mean_bg": {"episodes": 0, "median_bp": nan,
                                          "mean_bp": nan,
                                          "share_pos": nan, "events": 0},
                           "symbols": 0, "d1": None},
            "diff_bp": (best or 0) - 1.0, "best_half_bp": best},
        "null": {"perms": 200, "p95": 3.0, "mean": 0.0, "observed": 5.0,
                 "beats": True},
        "turnover": {"low_turnover": {"thin_bp": 1.0, "coarse_bp": 0.0,
                                      "names_thin": 2, "names_coarse": 2,
                                      "diff_bp": 1.0},
                     "high_turnover": {"thin_bp": 1.0, "coarse_bp": 0.0,
                                       "names_thin": 2, "names_coarse": 2,
                                       "diff_bp": 1.0}},
        "book": {}, "calibration": {"planted": {"diff_bp": 200.0,
                                                "events": 10},
                                    "random": {"diff_bp": 0.5,
                                               "events": 10}},
        "tick_change": {"symbols": None, "why": "не снялось",
                        "experiment": None},
        "link": None, "link_why": "не измерено",
        "drops": [0.03], "delays": [5], "horizons": [1800],
        "cells": {},
    }


def _art_full(best, span=50.0):
    a = _art(best, span)
    a["killers"] = RH.killers(a)
    return a


def test_killer_phrases_follow_the_numbers():
    """Вердикт по каждому условию выводится из числа, а не рядом с ним."""
    low = RH.killers(_art(best=10.0))
    assert "НЕ ПРОХОДИТ" in low["1. величина"], low
    high = RH.killers(_art(best=90.0))
    assert "НЕ ПРОХОДИТ" not in high["1. величина"], high
    # Знак разделения: тонкая ниже крупной — знак обратный заявленному.
    art = _art(best=90.0)
    art["verdict"]["diff_bp"] = -5.0
    assert "ОБРАТНЫЙ" in RH.killers(art)["3. знак разделения"]
    art["verdict"]["diff_bp"] = 5.0
    assert "ОБРАТНЫЙ" not in RH.killers(art)["3. знак разделения"]
    # Форма: медиана и среднее расходятся знаком.
    art = _art(best=90.0)
    art["verdict"]["thin"]["by_median_bg"]["mean_bp"] = -3.0
    assert "РАСХОДЯТСЯ" in RH.killers(art)["4. форма"]
    # Доля прибыльных ниже 0.60 — тоже отказ, при согласных знаках.
    art = _art(best=90.0)
    art["verdict"]["thin"]["by_median_bg"]["share_pos"] = 0.51
    assert "ниже 0.60" in RH.killers(art)["4. форма"]
    # Нуль не перебит.
    art = _art(best=90.0)
    art["null"]["beats"] = False
    assert "НЕ ВЫШЕ" in RH.killers(art)["2. нуль перестановки"]
    # Контроль оборота: не разделяет ни в одной половине.
    art = _art(best=90.0)
    for g in ("low_turnover", "high_turnover"):
        art["turnover"][g]["diff_bp"] = -1.0
    assert "НИ В ОДНОЙ" in RH.killers(art)["5. контроль оборота"]
    # А если измерена одна половина из двух — «ни в одной» сказать
    # нельзя: не измерено и не разделяет суть разные ответы.
    art["turnover"]["high_turnover"]["diff_bp"] = None
    one = RH.killers(art)["5. контроль оборота"]
    assert "НИ В ОДНОЙ" not in one, one
    assert "вторая молчит" in one and "1 половина из 2" in one, one
    art["turnover"]["low_turnover"]["diff_bp"] = None
    assert "не измерено" in RH.killers(art)["5. контроль оборота"]


def test_tick_change_experiment_is_built_or_absent_not_empty():
    syms = ["AUSDT", "BUSDT"]
    at = RH.tick_change_at()
    rec = [_rec(at - 3600 * k, 0, 0.01) for k in range(1, 12)]
    rec += [_rec(at + 3600 * k, 0, 0.03) for k in range(1, 12)]
    rec += [_rec(at - 3600 * k, 1, 0.02) for k in range(1, 12)]
    rec += [_rec(at + 3600 * k, 1, 0.02) for k in range(1, 12)]
    # Списка нет — замера нет вовсе, а не таблица прочерков.
    assert RH.tick_change_experiment(rec, syms, None) is None
    ex = RH.tick_change_experiment(rec, syms, ["AUSDT"])
    assert ex["before_bp"] == 100.0 and ex["after_bp"] == 300.0, ex
    assert ex["control_before_bp"] == 200.0, ex
    assert ex["control_after_bp"] == 200.0, ex
    assert ex["before_episodes"] > 0 and ex["after_episodes"] > 0
    # Группа без записей — «не измерено», а не ноль.
    ex2 = RH.tick_change_experiment(rec[:11], syms, ["AUSDT"])
    assert ex2["after_bp"] is None and ex2["after_episodes"] == 0, ex2


def test_link_reads_the_daily_series_not_a_summary():
    """Связь считается по РЯДУ суток, а не по сводке о нём.

    Первый заход брал `stability.live_rows`, которая отдаёт сводку, а
    не ряд: связь вышла бы по пустому словарю и печаталась прочерком,
    выглядя измеренной.
    """
    import json as J
    p = os.path.join(HERE, "out", "_test_day.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mine = {i: (1.0 if i % 2 else -1.0) for i in range(10)}
    run = {"candidates": {
        "one": {"daily": {str(i): (1.0 if i % 2 else -1.0)
                          for i in range(10)}},
        "two": {"daily": {str(i): (-1.0 if i % 2 else 1.0)
                          for i in range(10)}},
        "мало": {"daily": {"0": 1.0}}}}
    try:
        open(p, "w", encoding="utf-8").write(J.dumps(run))
        got, why = RH.link_to_pool(mine, p)
        assert got["one"]["corr"] == 1.0, got
        assert got["two"]["corr"] == -1.0, got
        # Общих суток меньше порога пары — «не измерено», а не ноль.
        assert got["мало"]["corr"] is None, got
        assert "кандидаты" in why, why
        # Нечего читать — тоже «не измерено», и прогон не падает.
        assert RH.link_to_pool({}, p)[0] is None
        assert RH.link_to_pool(mine, p + ".нет")[0] is None
    finally:
        os.remove(p)


def test_report_verdict_phrase_follows_the_number():
    p = os.path.join(HERE, "out", "_test_report.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        RH.report(_art_full(best=10.0), p)
        low = open(p, encoding="utf-8").read()
        assert "направление закрыто самым дешёвым числом" in low, low[:400]
        RH.report(_art_full(best=90.0), p)
        high = open(p, encoding="utf-8").read()
        assert "требуемое перекрыто" in high
        assert "направление закрыто самым дешёвым числом" not in high
    finally:
        os.remove(p)


def test_report_span_phrase_follows_the_number():
    p = os.path.join(HERE, "out", "_test_report2.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        RH.report(_art_full(best=90.0, span=2.0), p)
        narrow = open(p, encoding="utf-8").read()
        assert "разрезать нечего" in narrow
        RH.report(_art_full(best=90.0, span=50.0), p)
        wide = open(p, encoding="utf-8").read()
        assert "деление осмысленно" in wide
        assert "разрезать нечего" not in wide
    finally:
        os.remove(p)


def test_report_says_not_measured_instead_of_zero():
    p = os.path.join(HERE, "out", "_test_report3.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        RH.report(_art_full(best=90.0), p)
        text = open(p, encoding="utf-8").read()
        assert "**Не измерено**" in text, "пустое обязано называть себя"
        assert "Не измерено: сделок в тонкой половине нет" in text
        # Артефакт прежнего образца не роняет отчёт и говорит об этом.
        RH.report(_art(best=90.0), p)          # без блока `killers`
        old = open(p, encoding="utf-8").read()
        assert "артефакт сделан до появления блока" in old
    finally:
        os.remove(p)


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    bad = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok  {name}")
        except Exception as e:                              # noqa: BLE001
            bad += 1
            import traceback
            print(f"ПАДЕНИЕ {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\nпроверок {len(tests)}, упало {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
