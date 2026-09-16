#!/usr/bin/env python3
"""Проверки механики 1d5e7287 (гейт RR: подача или отбор).

Прогон: `.venv/bin/python research/mech_1d5e7287/test_rr_supply.py`.
Скрипт самостоятельный (не pytest): его же запускает приёмка фабрики,
применяя к копии модуля каждую объявленную подделку и требуя падения.

Правило фикстур этого проекта: подставной артефакт обязан выглядеть как
живой. Поэтому записи позиций здесь НЕ пишутся руками — они считаются
настоящим реплеем (`run_d6.collect_recs` → `ladder.simulate_dca`) по
синтетическим барам, а сами бары дрожат, живут в реальных секундах и
имеют объём. Восемь холостых проверок в этом проекте случились ровно на
фикстурах, которые живой писатель бы не написал.
"""

import json
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in ("dca_paper", "dca_ladder", "s8_loop", "s10_policy", "s9_sweep",
           "t4_structure", "factory", "a1_universe"):
    _q = os.path.join(RESEARCH, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)
sys.path.insert(0, HERE)

import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import tournament as TNT                                      # noqa: E402
import live_books as LB                                       # noqa: E402
import pool as PL                                             # noqa: E402
import stability as SB                                        # noqa: E402

import rr_supply as M                                         # noqa: E402

HOUR = 3600
MINUTE = 60
T0 = 1786000000                      # 2026-08-05 ~ живая секунда записи
FAILS = []


def noop(*_a, **_k):
    pass


def check(name, ok, detail=""):
    if ok:
        print(f"ok: {name}")
    else:
        FAILS.append(name)
        print(f"ПРОВАЛ: {name}{(' — ' + str(detail)) if detail else ''}")


# --- фикстуры ------------------------------------------------------------

def bars_for(sym, t_start, minutes, seed, shock_at=None, shock_mult=1.0):
    """Минутные бары: (время, открытие, максимум, минимум, закрытие, объём).

    Путь дрожит и имеет объём — бар без объёма у ленты не рождается, и
    фикстура, которая этого не знает, проверяет не то.
    """
    rnd = random.Random(seed)
    px = 100.0 + (hash(sym) % 37)
    out, shocked = [], False
    for i in range(minutes):
        t = t_start + i * MINUTE
        step = px * rnd.uniform(-0.0022, 0.0021)
        o = px
        px = max(1e-6, px + step)
        # Обвал ОДИН раз и строго ПОСЛЕ последнего срока: будущее ломается
        # так, чтобы прошлое обязано было остаться тем же числом.
        if shock_at is not None and not shocked and t > shock_at:
            shocked = True
            px = max(1e-6, px * shock_mult)
        hi = max(o, px) * (1.0 + abs(rnd.gauss(0, 0.0006)))
        lo = min(o, px) * (1.0 - abs(rnd.gauss(0, 0.0006)))
        out.append((t, o, hi, lo, px, 1000.0 + rnd.random() * 500.0))
    return out


class FakeSrc:
    """Источник баров, который отдаёт ВЕСЬ ряд символа, не глядя на окно.

    Так и задумано: пусть источник предлагает будущее — модуль обязан его
    не взять. Окно режет `run_d2.split_window` по сроку книги, и тест на
    заглядывание в будущее кусается ровно здесь.
    """

    def __init__(self, series):
        self.series = series
        self.last_tape = {}
        self.last_book = {}

    def bars(self, sym, _t0, _t1):
        return list(self.series.get(sym) or [])


def legs_fixture():
    """Ноги двух рук: полоса, гейт, промежуток и нога без отношения."""
    legs = []
    spec = [
        # (имя, час входа, рука, край б.п., mfe б.п., |стоп| б.п.)
        ("AAAUSDT", 26, "gbm", 60.0, 300.0, 100.0),   # rr 3.0  — гейт
        ("AAAUSDT", 50, "nn", 55.0, 260.0, 90.0),     # rr 2.9  — гейт
        ("BBBUSDT", 27, "gbm", 48.0, 120.0, 150.0),   # rr 0.8  — полоса
        ("BBBUSDT", 52, "nn", 51.0, 140.0, 140.0),    # rr 1.0  — полоса
        ("CCCUSDT", 28, "gbm", 44.0, 150.0, 110.0),   # rr 1.36 — полоса
        ("CCCUSDT", 54, "nn", 47.0, 170.0, 100.0),    # rr 1.7  — между
        ("AAAUSDT", 30, "nn", 20.0, 200.0, 60.0),     # край мал — ни туда
    ]
    for (sym, h, arm, fwd, mfe, stop) in spec:
        at = float(T0 + h * HOUR)
        legs.append({"arm": arm, "sym": sym, "hour": None, "at": at,
                     "side": "long", "fwd": fwd, "px": 100.0,
                     "fz": fwd / 10.0, "beta": 1.0,
                     "adv_q": -stop, "adv_m": -stop * 0.8, "fav": mfe,
                     "rr": mfe / stop})
    return legs


def sheets_fixture(path):
    """Журнал листов живого образца: часы, руки, оба квантиля пути."""
    rows = {
        26: [("AAAUSDT", 60.0, -80.0, 300.0, -100.0, 340.0),
             ("BBBUSDT", 48.0, -120.0, 120.0, -150.0, 130.0),
             ("DDDUSDT", -55.0, -90.0, 210.0, -120.0, 230.0)],
        27: [("CCCUSDT", 44.0, -95.0, 150.0, -110.0, 160.0),
             ("AAAUSDT", 20.0, -50.0, 200.0, -60.0, 210.0)],
        28: [("BBBUSDT", 51.0, -130.0, 140.0, -140.0, 150.0),
             ("EEEUSDT", 39.0, -70.0, 90.0, -75.0, 95.0)],
    }
    with open(path, "w", encoding="utf-8") as f:
        for h, lst in sorted(rows.items()):
            at = float(T0 + h * HOUR)
            rec = {"hour": time.strftime("%Y-%m-%d-%H", time.gmtime(at - HOUR)),
                   "written_at": at, "min_edge_bp": 22.0, "min_rr": 2.0,
                   "arms": {}}
            for arm in ("gbm", "nn"):
                out = []
                for i, (sym, fwd, mae, mfe, mae_q, mfe_q) in enumerate(lst):
                    sign = 1.0 if arm == "gbm" else 0.93
                    out.append({"sym": sym, "fwd": round(fwd * sign, 2),
                                "mae": mae, "mfe": mfe, "mae_q": mae_q,
                                "mfe_q": mfe_q, "px": 100.0 + i,
                                "fwd_z": round(fwd * sign / 12.0, 3),
                                "beta": 1.0 + 0.1 * i, "odd": 0.0})
                rec["arms"][arm] = out
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def replay_fixture(shock_mult=1.0, tmp=None):
    """Настоящие записи позиций по синтетическим барам.

    Ряд каждого имени тянется далеко ЗА срок книги — источник предлагает
    будущее намеренно.
    """
    legs = [g for g in legs_fixture() if abs(g["fwd"]) >= D2.MIN_EDGE_BP]
    syms = sorted({g["sym"] for g in legs})
    start = T0
    # Граница «прошлого» берётся у ПРАВИЛ КНИГИ (`rules.HOLD_H`), а не у
    # константы модуля. Возьми её у модуля — и подделка, удлиняющая срок,
    # подвинула бы вместе с окном и сам обвал, то есть проверка на
    # заглядывание в будущее перестала бы кусаться, оставшись зелёной.
    minutes = int((80 + 8 * R.HOLD_H) * 60)
    last_at = max(g["at"] for g in legs)
    series = {s: bars_for(s, start, minutes, seed=hash(s) % 10007,
                          shock_at=last_at + R.HOLD_H * HOUR,
                          shock_mult=shock_mult) for s in syms}
    src = FakeSrc(series)
    was = D2.instruments_tiers
    D2.instruments_tiers = lambda: {}
    try:
        path = os.path.join(tmp or tempfile.mkdtemp(prefix="rrsup-"),
                            "recs.jsonl")
        recs, info = M.replay(legs, src=src, log=noop, path=path, mem=False)
    finally:
        D2.instruments_tiers = was
    return legs, recs, info


def rows_fixture(recs, n_gate=None):
    """Строки «решение к решению» с проставленными издержками.

    Издержки здесь не считаются ядром (для этого нужен справочник
    площадки, которого у теста нет) — они ПРОСТАВЛЯЮТСЯ полем, как их
    проставляет `costs.apply_to_rows`: тест мерит арифметику набора, а не
    таблицу комиссий.
    """
    ticket = R.ticket(M.DEPOSIT, M.RULER)
    rows = M.rows_from([(r, ticket) for r in recs], M.DEPOSIT, M.RULER)
    for r in rows:
        r["usd_gross"] = r["usd"]
        r["costs_why"] = None
    return rows


def fake_rows(n, base, seed, exits=None, unmeasured=0):
    """Набор строк с объявленным исходом: для мер и зёрен."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        frac = base + rnd.gauss(0, 0.02)
        out.append({"sym": f"S{i % 17}USDT", "at": float(T0 + i * 60),
                    "exit_ts": float(T0 + i * 60 + 3600),
                    "margin": 25.0, "usd": round(25.0 * frac, 6),
                    "lev": 1.0 + (i % 5), "depth": 1 + (i % 3),
                    "exit": (exits[i % len(exits)] if exits else "тейк"),
                    "costs_why": None})
    for i in range(min(unmeasured, len(out))):
        out[i]["costs_why"] = "рунгов или цены выхода нет"
    return out


# --- проверки ------------------------------------------------------------

def t_band_source():
    """Полоса читается у оси `rr_band`, а не своим числом."""
    ok = (M.band_bounds("lo") == LB.RR_BAND["lo"]
          and M.band_bounds("hi") == LB.RR_BAND["hi"])
    check("полоса-из-оси", ok, f"{M.band_bounds('lo')} против "
                               f"{LB.RR_BAND['lo']}")
    hi = LB.RR_BAND["lo"][1]
    ok2 = (M.in_band(hi, "lo") and not M.in_band(hi + 1e-9, "lo")
           and M.in_band(LB.RR_BAND["hi"][0], "hi")
           and not M.in_band(LB.RR_BAND["hi"][0] - 1e-9, "hi"))
    check("границы-полосы-включительно", ok2)


def t_rr_unknown():
    """Нога без отношения не проходит НИ полосу, ни гейт."""
    ok = (not M.in_band(None, "lo")) and (not M.in_band(None, "hi")) \
        and (not M.in_band(None, "none"))
    legs = legs_fixture() + [dict(legs_fixture()[0], rr=None, sym="ZZZUSDT")]
    got_lo = M.pick_legs(legs, "lo")
    got_hi = M.pick_legs(legs, "hi")
    ok = ok and all(g["sym"] != "ZZZUSDT" for g in got_lo + got_hi)
    tbl = M.supply_table(legs)
    unk = sum(c["rr_unknown"] for d in tbl.values() for c in d.values())
    check("не-измерено-не-фильтр", ok and unk == 1, f"rr_unknown={unk}")


def t_edge_gate():
    """Край книги режет обе полосы одинаково."""
    legs = legs_fixture()
    small = [g for g in legs if abs(g["fwd"]) < D2.MIN_EDGE_BP]
    got = M.pick_legs(legs, "lo") + M.pick_legs(legs, "hi") \
        + M.pick_legs(legs, "none")
    ok = bool(small) and all(g not in got for g in small)
    check("край-режет-обе-полосы", ok, f"мелких {len(small)}")


def t_hi_is_live_gate():
    """Полоса `hi` тождественна ЖИВОМУ гейту книг (`run_d6.gated_legs`)."""
    tmp = tempfile.mkdtemp(prefix="rrsup-")
    try:
        path = sheets_fixture(os.path.join(tmp, "sheets.jsonl"))
        was = D2.SHEETS
        D2.SHEETS = path
        try:
            live = D6.gated_legs(log=noop)
        finally:
            D2.SHEETS = was
        legs, _rd = M.stream_legs([path], log=noop)
        mine = M.pick_legs(legs, "hi")
        key = lambda g: (g["sym"], g["at"], g["arm"],   # noqa: E731
                         round(float(g["rr"] or 0), 9))
        ok = sorted(map(key, live)) == sorted(map(key, mine)) and bool(live)
        check("полоса-hi-это-живой-гейт", ok,
              f"живых {len(live)}, своих {len(mine)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_stream_reader():
    """Потоковый читатель тождествен `tournament.legs_from_sheets`."""
    tmp = tempfile.mkdtemp(prefix="rrsup-")
    try:
        path = sheets_fixture(os.path.join(tmp, "sheets.jsonl"))
        want = TNT.legs_from_sheets([path], log=noop)
        got, rd = M.stream_legs([path], log=noop)
        strip = lambda L: [{k: v for k, v in g.items() if k != "id"}  # noqa
                           for g in L]
        ok = bool(want) and strip(want) == strip(got) \
            and rd["kept"] == len(got)
        check("читатель-тот-же", ok, f"{len(want)} против {len(got)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_sample():
    """Объявленная выборка: размер, зерно номером, воспроизводимость."""
    legs = [{"sym": f"S{i}", "at": float(T0 + i)} for i in range(100)]
    a, ia = M.declared_sample(legs, 10)
    b, _ = M.declared_sample(legs, 10)
    c, _ = M.declared_sample(legs, 10, seed=M.SEED + 1)
    # Литерал: зерно 20260916 на этой фикстуре даёт ИМЕННО эти имена.
    # Без него сдвиг зерна на единицу прошёл бы мимо — сравнение «то же
    # зерно даёт то же» верно у любого зерна.
    ok = (len(a) == 30 == ia["taken"] and ia["want"] == 30
          and [x["sym"] for x in a][:8] == ["S5", "S13", "S20", "S22",
                                            "S30", "S31", "S34", "S47"]
          and [x["sym"] for x in a] == [x["sym"] for x in b]
          and [x["sym"] for x in a] != [x["sym"] for x in c])
    # Полоса меньше выборки — берётся целиком, и это ЧИСЛО, а не молчание
    d, idd = M.declared_sample(legs[:5], 10)
    ok = ok and len(d) == 5 and idd["whole"] is True
    check("выборка-объявлена", ok, f"{len(a)}/{ia}")


def t_rows_match_build_rows():
    """Своя сборка строк совпадает с кассой живых книг ДО ЦЕНТА."""
    _legs, recs, _i = replay_fixture()
    if not recs:
        return check("сборка-как-у-книг", False, "реплей не дал записей")
    want, _cells, _one, _live = RP.build_rows({M.RULER: list(recs)},
                                              log=noop, keys=[M.RULER])
    want = [r for r in want if int(r["dep"]) == int(M.DEPOSIT)]
    got, _cell = M.cap_rows(recs, M.RULER, M.DEPOSIT, M.DEPOSIT)
    key = lambda r: (r["sym"], round(float(r["at"]), 3))    # noqa: E731
    a = {key(r): (round(float(r["usd"]), 6), round(float(r["margin"]), 6),
                  round(float(r["pnl_frac"]), 6)) for r in want}
    b = {key(r): (round(float(r["usd"]), 6), round(float(r["margin"]), 6),
                  round(float(r["pnl_frac"]), 6)) for r in got}
    check("сборка-как-у-книг", bool(a) and a == b,
          f"{len(a)} против {len(b)}")


def t_lookahead():
    """Переписать будущее — прошлое не должно шелохнуться."""
    tmp_a = tempfile.mkdtemp(prefix="rrsup-a-")
    tmp_b = tempfile.mkdtemp(prefix="rrsup-b-")
    try:
        _l1, r1, _i1 = replay_fixture(shock_mult=1.0, tmp=tmp_a)
        _l2, r2, _i2 = replay_fixture(shock_mult=6.0, tmp=tmp_b)
        if not r1 or not r2:
            return check("будущее-не-влияет", False, "реплей пуст")
        f = lambda L: sorted((r["sym"], round(float(r["at"]), 3),  # noqa: E731
                              r["exit"], round(float(r["pnl"]), 10),
                              round(float(r["exit_ts"]), 3),
                              round(float(r["lev"]), 10)) for r in L)
        check("будущее-не-влияет", f(r1) == f(r2),
              f"{len(r1)}/{len(r2)} записей")
    finally:
        shutil.rmtree(tmp_a, ignore_errors=True)
        shutil.rmtree(tmp_b, ignore_errors=True)


def t_calibration_literals():
    """Литералы калибровочной пары объявлены ЗДЕСЬ и до чисел."""
    ok = ((M.CAL_FLAT_LO, M.CAL_FLAT_HI) == (0.30, 0.70)
          and M.CAL_SHIFT == -0.05 and M.CAL_SHIFT_MIN == 0.95
          and M.SEED == 20260916 and M.SEEDS == 200
          and M.SAMPLE_MULT == 3 and M.WIN_SHARE == 0.95)
    check("литералы-объявлены", ok,
          f"{M.CAL_FLAT_LO}/{M.CAL_FLAT_HI}/{M.CAL_SHIFT}/{M.CAL_SHIFT_MIN}")


def t_calibration_bites():
    """Калибровочная пара молчит на копии и ловит подсаженный сдвиг."""
    gate = fake_rows(240, 0.01, seed=7)
    cal = M.calibration(gate, seeds=60)
    ok_flat = cal["flat"]["ok"] and M.CAL_FLAT_LO <= cal["flat"]["median_win"] \
        <= M.CAL_FLAT_HI
    ok_shift = cal["shift"]["ok"] and cal["shift"]["median_win"] >= 0.95
    check("калибровка-молчит-на-копии", ok_flat,
          f"доля {cal['flat']['median_win']}")
    check("калибровка-ловит-сдвиг", ok_shift,
          f"доля {cal['shift']['median_win']}")
    check("калибровка-вердикт", cal["ok"] is True, cal.get("why"))


def t_seed_same_size():
    """Случайная выборка берётся ТОГО ЖЕ размера, что гейтованный набор."""
    gate = fake_rows(120, 0.01, seed=11)
    band = fake_rows(360, 0.01, seed=12)
    st = M.seed_test(gate, band, seeds=40)
    ok = (st["k"] == len(gate) and st["union"] == len(gate) + len(band)
          and st["seeds"] == 40 and abs(st["resolution"] - 1 / 40) < 1e-9)
    check("выборка-того-же-размера", ok, str(st))


def t_verdict_from_number():
    """Вердикт выведен из числа, а не стоит рядом с ним."""
    hi = M.gate_verdict({"seeds": 200, "median_win": 0.99, "tail_win": 0.60})
    mid = M.gate_verdict({"seeds": 200, "median_win": 0.50, "tail_win": 0.50})
    lo = M.gate_verdict({"seeds": 200, "median_win": 0.01, "tail_win": 0.40})
    ok = ("ФИЛЬТР КАЧЕСТВА" in hi and "ОТБОРА НЕТ" in mid
          and "АНТИСЕЛЕКТИВЕН" in lo)
    check("вердикт-из-числа", ok, f"{hi[:20]} / {mid[:20]} / {lo[:20]}")


def t_refuse_on_empty():
    """Ноль наблюдений при непустом входе — ОТКАЗ, а не прочерк."""
    rows = fake_rows(20, 0.01, seed=3, unmeasured=20)
    try:
        M.outcome_stats(rows, "пусто")
        ok = False
    except SystemExit as e:
        ok = "ОТКАЗ" in str(e)
    check("отказ-вместо-пустоты", ok)
    check("пустой-вход-это-прочерк", M.outcome_stats([], "нет") is None)


def t_net_not_mixed():
    """Нетто-мера не смешивает брутто с нетто."""
    rows = fake_rows(20, 0.05, seed=5, unmeasured=8)
    vals, skip = M.net_frac(rows)
    ok = len(vals) == 12 and skip == 8
    st = M.outcome_stats(rows, "смесь")
    ok = ok and st["measured"] == 12 and st["unmeasured"] == 8
    check("брутто-не-в-нетто", ok, f"{len(vals)}/{skip}")


def t_tail_exits():
    """Хвостовой исход — пол и ликвидация, тейк и срок хвостом не бывают."""
    rows = fake_rows(40, 0.01, seed=9,
                     exits=["тейк", "срок", "пол", "ликвидация"])
    st = M.outcome_stats(rows, "хвост")
    ok = abs(st["tail_share"] - 0.5) < 1e-9 and st["tail_n"] == 20
    check("хвост-это-пол-и-ликвидация", ok, str(st["tail_share"]))


def t_dash_not_zero():
    """Величина, которой нет, — прочерк, а не ноль."""
    ok = M.ratio({"final": 0.1, "max_dd": 0.0}) is None
    ok = ok and M.ratio(None) is None
    ok = ok and abs(M.ratio({"final": 0.1, "max_dd": -0.05}) - 2.0) < 1e-9
    check("прочерк-а-не-ноль", ok)


def t_measurable_from_number():
    """Измеримость выведена из числа суток, а не объявлена словом."""
    tbl = {f"2026-08-{d:02d}": {"gbm": {"band": (1 if d <= 3 else 0)}}
           for d in range(1, 31)}
    m = M.measurable(tbl, 30)
    ok = (m["days_with_band"] == 3 and m["need"] == 10
          and m["measurable"] is False and "НЕЧЕМ" in m["verdict"])
    tbl2 = {k: {"gbm": {"band": 5}} for k in tbl}
    m2 = M.measurable(tbl2, 30)
    ok = ok and m2["measurable"] is True and "есть чем" in m2["verdict"]
    check("измеримость-из-числа", ok, str(m))


def t_mech_direction():
    """Механизм назван верно только когда доливов У ПОЛОСЫ больше."""
    more = M.mech_check({"add_share": 0.10, "depth_median": 1.0},
                        {"add_share": 0.30, "depth_median": 2.0})
    less = M.mech_check({"add_share": 0.30, "depth_median": 2.0},
                        {"add_share": 0.10, "depth_median": 1.0})
    ok = ("назван верно" in more["verdict"]
          and "НАЗВАН НЕВЕРНО" in less["verdict"])
    check("механизм-по-доливам", ok, less["verdict"][:40])


def t_shape_uses_pool_rule():
    """Форма судится ПРАВИЛОМ ПУЛА, а не своими порогами."""
    rows = [{"sym": "A", "at": float(T0), "usd": -5.0,
             "exit_ts": float(T0 + i * 86400)} for i in range(14)]
    sh = M.shape(rows)
    ok = (sh["min_days"] == SB.MIN_DAYS and sh["max_bite"] == PL.MAX_BITE
          and sh["min_med"] == PL.MIN_MED_DAY and sh["why"]
          and "вылет по форме" in sh["verdict"])
    thin = M.shape(rows[:3])
    ok = ok and thin["why"] is None and "вердикта нет" in thin["verdict"]
    check("форма-правилом-пула", ok, str(sh["verdict"])[:60])


def t_own_cache():
    """Кэш сестры — свой файл со своей подписью; живое не трогается."""
    ok = (M.cache_path() != RP.cache_path()
          and M.cache_sig() != RP.cache_sig()
          and M.cache_sig()["band"] == M.BAND
          and M.cache_sig()["band_bounds"] == list(LB.RR_BAND[M.BAND]))
    live, jrn = RP.cache_path(), R.JOURNAL
    было = [(p, os.path.getmtime(p)) for p in (live, jrn)
            if os.path.exists(p)]
    tmp = tempfile.mkdtemp(prefix="rrsup-c-")
    try:
        replay_fixture(tmp=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = ok and all(os.path.getmtime(p) == mt for (p, mt) in было)
    check("свой-кэш-живое-не-трогаем", ok,
          f"{M.cache_path()} против {RP.cache_path()}")


def t_cache_check_bites():
    """Сверка с живым кэшем ловит расхождение ядра."""
    mine = [{"sym": "A", "at": 1.0, "pnl": 0.1, "exit_ts": 5.0, "lev": 2.0,
             "exit": "тейк", "state": "closed"}]
    same = M.cache_check(mine, list(mine))
    other = M.cache_check(mine, [dict(mine[0], pnl=0.2)])
    none = M.cache_check(mine, [{"sym": "B", "at": 2.0, "pnl": 0.1,
                                 "exit_ts": 5.0, "lev": 2.0, "exit": "тейк",
                                 "state": "closed"}])
    # Помеченная хвостом позиция сверке не подлежит — и это ЧИСЛО, а не
    # молчаливый пропуск: окно прохода задаёт, докуда лента продолжена.
    tail = M.cache_check([dict(mine[0], tail=1)], [dict(mine[0], pnl=0.9)])
    ok = ("ядро одно" in same["verdict"] and "ЯДРО НЕ ОДНО" in other["verdict"]
          and "не измерено" in none["verdict"]
          and tail["tail_skipped"] == 1 and tail["diff"] == 0)
    check("сверка-ядра-кусается", ok, other["verdict"][:40])


def t_lev_bands_disjoint():
    """Полосы плеча дизъюнктны: решение не считается дважды."""
    rows = [{"sym": "A", "at": 1.0, "exit_ts": 2.0, "margin": 25.0,
             "usd": 1.0, "lev": lv, "exit": "тейк", "depth": 1,
             "costs_why": None}
            for lv in (1.0, 1.5, 3.0, 3.5, 9.0)]
    seen = []
    for (_nm, lo, hi, strict) in M.LEV_BANDS:
        for r in rows:
            lv = float(r["lev"])
            if lo is not None and (lv <= lo + 1e-9 if strict
                                   else lv < lo - 1e-9):
                continue
            if hi is not None and lv > hi + 1e-9:
                continue
            seen.append(lv)
    ok = sorted(seen) == sorted(r["lev"] for r in rows)
    split = M.lev_split(rows, rows, seeds=5)
    ok = ok and sum(x["gate_n"] for x in split) == len(rows)
    check("полосы-плеча-дизъюнктны", ok, f"{sorted(seen)}")


def t_one_per_name():
    """Биржевое правило «одна позиция на имя» книга соблюдает."""
    _legs, recs, _i = replay_fixture()
    if not recs:
        return check("одна-на-имя", False, "реплей пуст")
    doubled = list(recs) + [dict(r, at=float(r["at"]) + 60.0) for r in recs]
    rows, _c = M.cap_rows(doubled, M.RULER, M.DEPOSIT, M.DEPOSIT)
    bad = 0
    per = {}
    for r in rows:
        per.setdefault(r["sym"], []).append((float(r["at"]),
                                             float(r["exit_ts"])))
    for lst in per.values():
        lst.sort()
        for i in range(1, len(lst)):
            if lst[i][0] < lst[i - 1][1]:
                bad += 1
    check("одна-на-имя", bad == 0 and bool(rows), f"пересечений {bad}")


def t_report_has_no_stale_prose():
    """Отчёт собирается и несёт ВЫВЕДЕННЫЕ вердикты, а не литералы."""
    s = {"at": time.time(), "band": "lo", "gate": "hi", "bounds": [0.0, 1.5],
         "edge_bp": 33.0, "ruler": "safe", "deposit": 10000.0, "seed": 1,
         "seeds": 2, "sample_mult": 3, "hold_h": 72, "ticket": 25.0,
         "rules": R.RULES, "steps": [0], "secs": 1.0,
         "read": {"hours": 3, "rows": 18, "bad": 0, "kept": 6},
         "counts": {"legs": 6, "band": 3, "gate": 2, "band_syms": 2,
                    "gate_syms": 1, "band_pairs": 3, "band_days": 1,
                    "gate_days": 1},
         "supply": {"2026-08-05": {"gbm": {"n": 3, "rr_unknown": 1,
                                           "sub": {k[0]: 1 for k in
                                                   M.SUB_BANDS},
                                           "band": 1, "gate": 1,
                                           "rr_median": 1.2,
                                           "band_pairs": 1}}},
         "measurable": {"verdict": "судить есть чем: полоса непуста в 1"}}
    txt = M.report(s)
    ok = ("судить есть чем" in txt and "Шаг 0" in txt
          and "RR нет" in txt and len(txt) > 800)
    check("отчёт-собирается", ok, f"{len(txt)} символов")


def main():
    t0 = time.time()
    for fn in (t_band_source, t_rr_unknown, t_edge_gate, t_hi_is_live_gate,
               t_stream_reader, t_sample, t_rows_match_build_rows,
               t_lookahead, t_calibration_literals, t_calibration_bites,
               t_seed_same_size, t_verdict_from_number, t_refuse_on_empty,
               t_net_not_mixed, t_tail_exits, t_dash_not_zero,
               t_measurable_from_number, t_mech_direction,
               t_shape_uses_pool_rule, t_own_cache, t_cache_check_bites,
               t_lev_bands_disjoint, t_one_per_name,
               t_report_has_no_stale_prose):
        try:
            fn()
        except Exception as e:                            # noqa: BLE001
            FAILS.append(fn.__name__)
            print(f"ПРОВАЛ: {fn.__name__} — {type(e).__name__}: {e}")
    print(f"\nвремя {round(time.time() - t0, 1)} с")
    if FAILS:
        print(f"провалов {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
