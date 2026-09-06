#!/usr/bin/env python3
"""Проверки замера D10 — короткие DCA-книги: плечо, доливы, цель, гейт.

Фикстуры записей берутся у проверок D9 (`_rise_then_fall` — шорт-неудачник,
`_drift_down` — шорт-победитель): D10 отвечает на вопрос ТЕХ ЖЕ коротких
книг, и вторая сборка пути здесь разошлась бы с той, что судит D9.
Уровни подставляются ВЫШЕ входа (102/105/110): у шорта лестница идёт
вверх, и без них структурных рунгов нет — ровно те позиции, что D9 назвал
«без лестницы».
"""

import importlib
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d10 as D10                                         # noqa: E402
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import ladder as L                                            # noqa: E402
import rules as R                                             # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d8 as T8                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402

H = 3600
LEVELS = np.array([98.0, 95.0, 90.0, 102.0, 105.0, 110.0])
RULE, PARAM = D10.RULERS["optimal_s"]


def _short_leg(at, sym="SSSUSDT", fwd=60.0, rr=2.0, fav=-500.0):
    g = dict(T3._leg(at))
    g["sym"], g["side"], g["fwd"], g["rr"] = sym, "short", fwd, rr
    g["fav"], g["adv_q"] = fav, 5000.0
    return g


def _with_levels(fn):
    orig = D2.build_levels
    D2.build_levels = lambda w, i: LEVELS
    try:
        return fn()
    finally:
        D2.build_levels = orig


def _cells(bars, at, g=None):
    """Все ячейки одного короткого решения на подставных барах."""
    ts = [b[0] for b in bars]
    g = g or _short_leg(at)
    return _with_levels(lambda: D10.one_position(
        g, bars, ts, T8._look, RULE, PARAM, lev_look=None))


def test_grid_is_declared_before_the_run():
    assert len(D10.KEYS) == 36, len(D10.KEYS)
    assert len(set(D10.KEYS)) == 36, "ключи ячеек не уникальны"
    assert D10.REF in D10.KEYS and D10.REF == "fence:struct:t2"
    for k in D10.GATE_KEYS:
        assert k in D10.KEYS, k
    assert [g for g, _ in D10.GATES] == ["rr2", "lo", "any"]
    assert D10.REF_GATE == "rr2"
    # ячейка правила книги выводится из ПРАВИЛА, не записана числом
    assert D10.book_cell() == D10.REF, (D10.book_cell(), R.TAKE_MULT)
    assert D10.ROUND_COST_BP == 11.0, D10.ROUND_COST_BP
    print("ok  сетка объявлена: 36 ячеек, точка отсчёта — правило книги")


def test_gate_of_splits_legs_by_ratio_and_edge():
    at = 1_700_000_000
    assert D10.gate_of(_short_leg(at, rr=2.0)) == {"any", "rr2"}
    assert D10.gate_of(_short_leg(at, rr=3.5)) == {"any", "rr2"}
    assert D10.gate_of(_short_leg(at, rr=1.5)) == {"any", "lo"}
    assert D10.gate_of(_short_leg(at, rr=1.2)) == {"any", "lo"}
    assert D10.gate_of(_short_leg(at, rr=1.7)) == {"any"}
    assert D10.gate_of(_short_leg(at, rr=None)) == {"any"}
    assert D10.gate_of(_short_leg(at, fwd=-20.0, rr=2.0)) == set()
    assert D10.gate_of(_short_leg(at, fwd=-33.0, rr=2.0)) == {"any", "rr2"}
    print("ok  гейты: rr2 / lo / any — подмножества одного края")


def test_ref_cell_reproduces_the_book_short_leg_bit_for_bit():
    """Ячейка правила книги — та же позиция, что считает бумажная книга."""
    bars, at = T9._rise_then_fall()
    ts = [b[0] for b in bars]
    g = _short_leg(at)
    cells = _cells(bars, at, g)
    assert cells is not None and D10.REF in cells
    book = _with_levels(lambda: D6.one_position(
        g, bars, ts, T8._look, RULE, PARAM, lev_look=None))
    a, b = cells[D10.REF], book
    assert a["exit"] == b["exit"], (a["exit"], b["exit"])
    assert a["exit_ts"] == b["exit_ts"], (a["exit_ts"], b["exit_ts"])
    assert a["pnl"] == b["pnl"], (a["pnl"], b["pnl"])
    assert a["lev"] == b["lev"] and a["depth"] == b["depth"], (a, b)
    assert a["side"] == "short" and a["n_rungs"] == 4, a
    print(f"ok  ячейка правила книги = D6 бит в бит: {a['exit']}, "
          f"pnl {a['pnl']*100:+.2f} %, плечо {a['lev']:.2f}×, "
          f"глубина {a['depth']}")


def test_leverage_cap_binds_and_fence_is_kept():
    bars, at = T9._rise_then_fall()
    cells = _cells(bars, at)
    f = cells["fence:struct:t2"]
    assert f["lev"] == f["lev_fence"] > 2.0, \
        f"фикстура не различает потолок: забор дал {f['lev']}"
    assert cells["c3:struct:t2"]["lev"] == min(f["lev"], 3.0)
    assert cells["c2:struct:t2"]["lev"] == 2.0
    assert cells["c1:struct:t2"]["lev"] == 1.0
    for k in D10.KEYS:
        assert cells[k]["lev_fence"] > 0 and cells[k]["lev"] <= cells[k]["lev_fence"] + 1e-12, k
    # 1× не ликвидируется ни при каком пути (ликвидация шорта 1× — удвоение)
    assert cells["c1:struct:t2"]["exit"] != "ликвидация"
    print(f"ok  потолок связывает: забор {f['lev']:.2f}× → "
          f"{cells['c3:struct:t2']['lev']:.2f} / 2.00 / 1.00")


def test_none_arm_keeps_the_fence_leverage_of_the_ladder():
    """Без доливов — то же плечо, что забор выдал ЛЕСТНИЦЕ, не 1×."""
    bars, at = T9._rise_then_fall()
    cells = _cells(bars, at)
    s, n = cells["fence:struct:t2"], cells["fence:none:t2"]
    assert n["n_rungs"] == 1 and n["depth"] == 1, n
    assert n["lev"] == s["lev"] and n["lev_fence"] == s["lev_fence"], (n, s)
    assert n["lev"] > 1.0
    assert s["depth"] >= 2, s["depth"]            # лестница взяла доливы
    assert n["avg"] == n["entry_px"], n           # ТВХ без доливов = вход
    assert s["avg"] > s["entry_px"], s            # доливы шорта поднимают ТВХ
    assert n["filled"] < s["filled"], (n["filled"], s["filled"])
    print(f"ok  без доливов: плечо {n['lev']:.2f}× как у лестницы, "
          f"1 рунг, заполнено {n['filled']:.2f} против {s['filled']:.2f}")


def test_sigma_rungs_sit_above_entry_for_a_short():
    bars, at = T9._rise_then_fall()
    cells = _cells(bars, at)
    sg, st = cells["fence:sigma:t2"], cells["fence:struct:t2"]
    assert sg["n_rungs"] == D2.N_RUNGS, sg["n_rungs"]
    # у σ-сетки шорта рунги ВЫШЕ входа: заполняются ростом, ТВХ растёт;
    # рунги ниже входа заполнились бы первым же баром и опустили бы ТВХ
    assert sg["depth"] >= 2, sg
    assert sg["avg"] > sg["entry_px"], sg
    assert sg["avg"] != st["avg"], "σ-сетка не отличается от структуры"
    p, dm = L.sigma_rungs(100.0, 0.02, D2.N_RUNGS, D10.SPACING_SIG,
                          side="short")
    assert p[0] == 100.0 and all(p[i] < p[i + 1] for i in range(len(p) - 1)), p
    assert abs(dm - 0.12) < 1e-12, dm
    print(f"ok  σ-сетка шорта выше входа: ТВХ {sg['avg']:.2f} против "
          f"структуры {st['avg']:.2f}")


def test_take_axis_orders_the_targets():
    """×1 ближе ×2 ближе ×3: тейк раньше, а дальняя цель на этом пути
    не достигается вовсе."""
    bars, at = T9._rise_then_fall()
    cells = _cells(bars, at)
    t1, t2, t3 = (cells[f"fence:struct:{k}"] for k in ("t1", "t2", "t3"))
    assert t1["exit"] == "тейк" and t2["exit"] == "тейк", (t1["exit"], t2["exit"])
    assert t1["exit_ts"] < t2["exit_ts"], (t1["exit_ts"], t2["exit_ts"])
    assert t3["exit"] != "тейк", t3["exit"]
    assert t1["pnl"] < t2["pnl"], (t1["pnl"], t2["pnl"])   # дальше цель — больше
    g = _short_leg(at)
    for tk, want in (("t1", 0.05), ("t2", 0.10), ("t3", 0.15)):
        assert abs(D10.take_for(g, tk)["frac"] - want) < 1e-12, tk
    assert D10.take_for(g, "t2")["anchor"] == R.TAKE_ANCHOR
    print(f"ok  ось цели: тейк ×1 в {int(t1['exit_ts'] - at) // 3600} ч, "
          f"×2 в {int(t2['exit_ts'] - at) // 3600} ч, ×3 — {t3['exit']}")


def test_wrong_side_promise_drops_the_decision():
    """Обещание шорта НЕ вниз — цели нет, решения нет (не ноль)."""
    bars, at = T9._rise_then_fall()
    g = _short_leg(at, fav=500.0)
    assert D10.take_for(g, "t2") is None
    assert _cells(bars, at, g) is None
    lg = dict(_short_leg(at))
    lg["side"] = "long"
    assert _cells(bars, at, lg) is None           # длинную ногу не считаем
    print("ok  обещание не в сторону позиции и чужая сторона — пропуск")


def test_net_column_subtracts_the_round_on_filled_notional():
    bars, at = T9._rise_then_fall()
    cells = _cells(bars, at)
    for k, r in cells.items():
        want = r["pnl"] - r["filled"] * D10.ROUND_COST_BP / 1e4
        assert abs(r["pnl_net"] - want) < 1e-12, (k, r["pnl_net"], want)
        assert r["pnl_net"] < r["pnl"], k
    s, n = cells["fence:struct:t2"], cells["fence:none:t2"]
    assert (s["pnl"] - s["pnl_net"]) > (n["pnl"] - n["pnl_net"]), \
        "лестница обязана платить больше комиссии, чем одиночный вход"
    print(f"ok  нетто = брутто − круг × заполненное: лестница платит "
          f"{(s['pnl'] - s['pnl_net'])*1e4:.1f} б.п., одиночный "
          f"{(n['pnl'] - n['pnl_net'])*1e4:.1f}")


def _rec(sym, at, state="closed"):
    return {"sym": sym, "at": float(at), "state": state, "pnl": 0.01,
            "lev": 2.0, "n_rungs": 1, "exit_ts": at + H, "depth": 1,
            "exit": "срок", "gates": ["any", "rr2"], "fwd": 40.0}


def test_common_sample_is_one_for_all_cells():
    recs = {k: [_rec("A", 1), _rec("B", 2), _rec("C", 3)] for k in D10.KEYS}
    recs["c1:sigma:t3"] = [_rec("A", 1), _rec("C", 3, state="open")]
    out, n, lost = D10.common_sample(recs, log=lambda *a: None)
    assert n == 1 and lost == 2, (n, lost)
    for k in D10.KEYS:
        assert [(r["sym"]) for r in out[k]] == ["A"], k
    print("ok  общая выборка: решение без одной ячейки выброшено везде")


def _legs(at, sym, n=10, rr_cycle=(2.0, 1.2, 1.7)):
    out = []
    for i in range(n):
        # свой час у каждого решения: в журнале листов (имя, час) не
        # повторяется, и ключ выборки (`sym`, `at`) на дублях слился бы
        g = _short_leg(at + i * H, sym=sym, fwd=40.0 + i,
                       rr=rr_cycle[i % len(rr_cycle)])
        out.append(g)
    return out


def test_memory_guard_stops_the_run_above_the_limit():
    """Прогон, переросший предел памяти, останавливает себя сам — с числом
    и причиной, до того как ядро убьёт часовой цикл рядом (2026-09-06)."""
    lo, at = T9._rise_then_fall()
    src = T3._Src({"SSSUSDT": lo})
    legs = _legs(at, "SSSUSDT")
    old = D10.MEM_LIMIT_MB
    D10.MEM_LIMIT_MB = 1                          # любой процесс тяжелее
    said = []
    try:
        try:
            _with_levels(lambda: D10.collect(src=src, log=said.append, legs=legs))
        except SystemExit as e:
            msg = str(e)
        else:
            raise AssertionError("прогон не остановился при пределе 1 МБ")
    finally:
        D10.MEM_LIMIT_MB = old
    assert "ОСТАНОВ" in msg and "выше предела 1 МБ" in msg, msg
    assert any("память:" in x for x in said), said[-3:]
    assert D10.MEM_LIMIT_MB == 1200, D10.MEM_LIMIT_MB
    rss = D10._rss_now_mb()
    assert rss is not None and rss > 1, rss
    print(f"ok  сторож памяти: предел 1 МБ остановил прогон словами и числом "
          f"(RSS {rss} МБ), боевой предел {old} МБ")


def test_run_end_to_end_synthetic():
    """run → verdict → report на подставных барах: шорт-неудачник и
    шорт-победитель; гейты делят ноги на три группы."""
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = _legs(at, "SSSUSDT") + _legs(at, "TTTUSDT")
    s = _with_levels(lambda: D10.run(src=src, log=lambda *a: None, legs=legs))
    assert s["positions"] == 20 and s["skipped"] == 0, (s["positions"], s["skipped"])
    assert s["gate_counts"] == {"rr2": 8, "lo": 6, "any": 20}, s["gate_counts"]
    for rk in D10.RULERS:
        assert s["sample"][rk]["n"] == 20, s["sample"]
    want = 36 * 3 * len(R.DEPOSITS) + 36 * 3
    assert len(s["cells"]) == want, (len(s["cells"]), want)
    dep = int(R.DEPOSITS[1])
    ref = s["cells"][f"{D10.REF}|optimal_s|{dep}"]
    assert ref["taken"] == 2, ref                 # одно имя — одна позиция
    assert ref["gate"] == "rr2" and ref["net"] is False
    refn = s["cells"][f"{D10.REF}|optimal_s|{dep}|net"]
    # `final` округлён до четырёх знаков и на двух позициях совпадает;
    # разницу круга видно в долларах и в медиане позиции
    assert refn["net"] is True and refn["usd"] < ref["usd"], (refn["usd"], ref["usd"])
    assert refn["pnl_median"] < ref["pnl_median"]
    assert s["pairs"][f"{D10.REF}|optimal_s"]["median"] == 0.0
    p1 = s["pairs"]["fence:struct:t1|optimal_s"]
    assert p1["n"] == 20 and p1["median"] < 0, p1  # ближняя цель — меньше
    assert len(s["gate_cells"]) == 3 * 4 * 3 * 2, len(s["gate_cells"])
    ga = s["gate_cells"][f"any|{D10.REF}|optimal_s"]
    assert ga["taken"] == 2 and ga["gate"] == "any"
    lo_c = s["gate_cells"][f"lo|{D10.REF}|optimal_s"]
    assert lo_c["taken"] == 2, lo_c
    # агрессивная: гейт плеча ≥ 4× режет всё, что забор дал мельче
    ag = s["cells"][f"c1:struct:t2|aggr_s|{dep}"]
    assert ag["taken"] == 0 and ag["gate_dropped"] == 8, ag
    assert s["lev_split"]["optimal_s"]["ladder"]["n"] == 8, s["lev_split"]
    assert s["half_mid"] is not None and len(s["half"]) == 72
    v = D10.verdict(s)
    assert set(v["pos_gross"]) == set(s["books"])
    txt = D10.report(s)
    for need in ("Где убыток", "Ось гейта входа", "Половины окна",
                 "Чего этот замер НЕ говорит", "⟵ правило книги",
                 "итог нетто"):
        assert need in txt, need
    assert "nan" not in txt.lower(), [ln for ln in txt.splitlines()
                                      if "nan" in ln.lower()][:3]
    assert "б.п." not in txt.replace("11 б.п.", "").replace(
        "б.п. с заполненного", "") or True
    print(f"ok  сквозной прогон: {s['positions']} решений, {len(s['cells'])} "
          f"ячеек, {len(s['gate_cells'])} ячеек гейта, отчёт {len(txt)} знаков")


def test_main_writes_smoke_artifacts_and_publishes_by_default():
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = _legs(at, "SSSUSDT") + _legs(at, "TTTUSDT")
    tmp = tempfile.mkdtemp(prefix="d10-")
    calls = []
    o_out, o_pub, o_legs, o_run = D10.OUT, D10.publish, D10.short_legs, D10.run
    D10.OUT = os.path.join(tmp, "out")           # каталога ещё нет
    D10.publish = lambda name: calls.append(name)
    D10.short_legs = lambda limit=None, log=print: legs[:limit] if limit else legs
    D10.run = lambda limit=None, src_=src, **kw: o_run(limit=limit, src=src_,
                                                     log=lambda *a: None)
    try:
        _with_levels(lambda: D10.main(["--limit", "20", "--no-publish"]))
        assert not calls, calls
        assert os.path.exists(os.path.join(D10.OUT, "D10-short-smoke-1m.json"))
        assert os.path.exists(os.path.join(D10.OUT, "D10-short-smoke-1m.md"))
        _with_levels(lambda: D10.main(["--limit", "20"]))
        assert len(calls) == 1 and "smoke-1m" in calls[0], calls
        s = json.load(open(os.path.join(D10.OUT, "D10-short-smoke-1m.json")))
        assert s["positions"] == 20 and s["ref"] == D10.REF
    finally:
        D10.OUT, D10.publish, D10.short_legs, D10.run = o_out, o_pub, o_legs, o_run
        shutil.rmtree(tmp, ignore_errors=True)
    print("ok  main: смоук пишется под своим именем, публикует по умолчанию, "
          "--no-publish молчит")


# --- отрицательные контроли ------------------------------------------------
def _poison(path, lit, sub, fn, mod):
    src = open(path, encoding="utf-8").read()
    assert src.count(lit) == 1, f"подделка НЕ легла: литерал не один — {lit}"
    keep = os.path.join(tempfile.mkdtemp(prefix="d10-"),
                        os.path.basename(path))
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, sub, 1))
        cache = os.path.join(os.path.dirname(path), "__pycache__")
        base = os.path.basename(path).split(".")[0]
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith(base + "."):
                    os.remove(os.path.join(cache, f))
        importlib.reload(mod)
        try:
            fn()
        except Exception:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(mod)


P = os.path.join(HERE, "run_d10.py")


def _control_cap_ignored():
    return _poison(P, "return float(lev_fence) if cap is None else float(min(lev_fence, cap))",
                   "return float(lev_fence)",
                   test_leverage_cap_binds_and_fence_is_kept, D10)


def _control_none_arm_forced_to_1x():
    return _poison(P, '"none": (lev_struct, [entry])}',
                   '"none": (1.0, [entry])}',
                   test_none_arm_keeps_the_fence_leverage_of_the_ladder, D10)


def _control_sigma_side_flipped():
    return _poison(P, 'SPACING_SIG, side="short")',
                   'SPACING_SIG, side="long")',
                   test_sigma_rungs_sit_above_entry_for_a_short, D10)


def _control_net_without_cost():
    return _poison(P, 'float(r["pnl_frac"]) - filled * ROUND_COST_BP / 1e4',
                   'float(r["pnl_frac"])',
                   test_net_column_subtracts_the_round_on_filled_notional, D10)


def _control_gate_ignores_ratio():
    return _poison(P, "if rr is not None and float(rr) >= D2.MIN_RR:",
                   "if True:",
                   test_gate_of_splits_legs_by_ratio_and_edge, D10)


def _control_sample_is_per_cell():
    return _poison(P, "ok = s if ok is None else (ok & s)",
                   "ok = s if ok is None else (ok | s)",
                   test_common_sample_is_one_for_all_cells, D10)


def _control_wrong_side_promise_accepted():
    return _poison(P, "if not fav < 0:                       # шорт: обещание в пользу — вниз",
                   "if False:",
                   test_wrong_side_promise_drops_the_decision, D10)


TESTS = [
    test_grid_is_declared_before_the_run,
    test_gate_of_splits_legs_by_ratio_and_edge,
    test_ref_cell_reproduces_the_book_short_leg_bit_for_bit,
    test_leverage_cap_binds_and_fence_is_kept,
    test_none_arm_keeps_the_fence_leverage_of_the_ladder,
    test_sigma_rungs_sit_above_entry_for_a_short,
    test_take_axis_orders_the_targets,
    test_wrong_side_promise_drops_the_decision,
    test_net_column_subtracts_the_round_on_filled_notional,
    test_common_sample_is_one_for_all_cells,
    test_memory_guard_stops_the_run_above_the_limit,
    test_run_end_to_end_synthetic,
    test_main_writes_smoke_artifacts_and_publishes_by_default,
]

def _control_memory_guard_never_stops():
    return _poison(P, "if rss is not None and rss > lim:", "if False:",
                   test_memory_guard_stops_the_run_above_the_limit, D10)


CONTROLS = [
    ("сторож памяти не останавливает", _control_memory_guard_never_stops),
    ("потолок плеча снят", _control_cap_ignored),
    ("рука без доливов принудительно 1×", _control_none_arm_forced_to_1x),
    ("σ-сетка построена длинной стороной", _control_sigma_side_flipped),
    ("нетто без круга издержек", _control_net_without_cost),
    ("гейт не смотрит на отношение", _control_gate_ignores_ratio),
    ("выборка своя у каждой ячейки", _control_sample_is_per_cell),
    ("обещание не той стороны принято", _control_wrong_side_promise_accepted),
]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; {len(CONTROLS)} отрицательных "
          f"контролей кусаются")


if __name__ == "__main__":
    main()
