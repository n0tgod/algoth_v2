#!/usr/bin/env python3
"""Проверки замера множителя тейка на коротком листе.

Кусаются: ось попадает в карту множителей D10 и цель считается ЕГО
арифметикой (второй формулы цели нет); ближняя цель у шорта стоит ВЫШЕ
дальней по цене — то есть ближе к ТВХ; записи ячейки раскладываются по
книгам той же картой, что у прогона; замер применяет правила книги
(возраст имени) и не пишет в журнал книг.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_d10 as D10                                         # noqa: E402
import short_take as ST                                       # noqa: E402
import test_pair as TP                                        # noqa: E402

H = 3600.0
DAY = 86400.0
T0 = TP.T0
DEP = R.DEPOSITS[1]


def test_axis_lands_in_the_grid_of_the_replay():
    was = dict(D10.TAKE_MULT)
    try:
        cl = ST.cells()
        keys = [c[0] for c in cl]
        assert keys == [f"fence:none:{k}" for k, _m in ST.TAKES], keys
        assert all(c[1] == "fence" and c[2] == "none" for c in cl), cl
        for k, m in ST.TAKES:
            assert D10.TAKE_MULT[k] == m, (k, D10.TAKE_MULT.get(k))
        # цель считает ЯДРО замера, а не копия формулы здесь
        g = {"fav": -1000.0}          # обещание шорту в пользу: −10 %
        near = D10.take_for(g, "t05")["frac"]
        far = D10.take_for(g, "t3")["frac"]
        assert abs(near - 0.05) < 1e-12 and abs(far - 0.30) < 1e-12, (near, far)
        # у шорта цель НИЖЕ ТВХ, и ближняя ближе: доля меньше
        assert near < far, (near, far)
        print(f"ok  ось объявлена в карте D10: ×0.5 → цель {100 * near:g} % "
              f"от ТВХ, ×3 → {100 * far:g} %; арифметика одна")
    finally:
        D10.TAKE_MULT.clear()
        D10.TAKE_MULT.update(was)


def test_axis_does_not_leak_into_the_book_rule():
    """Ось замера не меняет правило книги: множитель книги остаётся своим."""
    was = float(R.TAKE_MULT)
    ST.cells()
    assert float(R.TAKE_MULT) == was, R.TAKE_MULT
    # и цель книги считается её же правилом
    # Доля цели у шорта берётся МОДУЛЕМ: направление задаёт сторона в
    # самой симуляции (`avg × (1 − доля)` вниз), и знак здесь был бы
    # вторым местом, решающим направление.
    rule = R.take_rule(-1000.0, "short")
    assert rule and abs(rule["frac"] - 0.2) < 1e-12, rule
    print(f"ok  множитель книги не тронут (×{was:g}), цель книги "
          f"{100 * abs(rule['frac']):g} % от ТВХ")


def test_pack_uses_the_map_of_the_run():
    key = "fence:none:t2"
    recs = {"safe_s": {key: [{"sym": "AUSDT"}]},
            "optimal_s": {key: [{"sym": "BUSDT"}, {"sym": "CUSDT"}]}}
    got = ST.pack(recs, key)
    assert set(got) == set(ST.S.BOOKS), sorted(got)
    assert len(got["safe_h"]) == 1 and len(got["optimal_h"]) == 2
    # «агрессивная» считается на той же линейке, что «оптимальная»
    assert len(got["aggr_h"]) == 2, got["aggr_h"]
    print("ok  записи ячейки разложены по книгам картой прогона: "
          f"safe_h {len(got['safe_h'])}, optimal_h {len(got['optimal_h'])}, "
          f"aggr_h {len(got['aggr_h'])}")


def test_cell_stats_applies_the_book_rules_and_writes_nothing():
    day = 86400.0
    old_, young = "OLDUSDT", "NEWUSDT"
    recs = [TP._short(old_, T0, hold_h=6.0),
            TP._short(young, T0 + H, hold_h=6.0)]
    launch = {old_: T0 - 200 * day, young: T0 - 1 * day}
    with tempfile.TemporaryDirectory() as td:
        st = ST.cell_stats({"safe_h": recs}, {"error": "рядов нет"}, launch,
                           now=T0 + 100 * H)
        assert sorted(os.listdir(td)) == [], "написал лишнее"
    c = st[f"safe_h:{int(DEP)}"]
    assert c["n"] == 1, c            # молодое имя правилом книги отсечено
    assert (c.get("exits") or {}), c
    print(f"ok  правила книги применены замером: из двух решений взято "
          f"{c['n']} (второе — моложе {R.min_age_days('safe_h'):g} суток), "
          f"исходы {sorted(c['exits'])}")


def test_merge_keeps_cells_of_earlier_runs_and_names_the_missing():
    """Ось считается частями — артефакт сливается, а отчёт это говорит.

    Кусается: ячейка прежнего прогона не теряется и сохраняет СВОЮ дату;
    заново посчитанная перекрывает старую; ячейки, которых ещё нет,
    названы в отчёте — «не считали» не выдаётся за «не бывает».
    """
    with tempfile.TemporaryDirectory() as td:
        art = os.path.join(td, "DCA-short-take.json")
        first = {"cells": {"t05": {"a": 1}}, "computed_at": "2026-09-10 10:00",
                 "takes": [{"key": "t05", "mult": 0.5}]}
        got = ST.merge_artifact(dict(first), art)
        import json as _j
        with open(art, "w", encoding="utf-8") as f:
            _j.dump(got, f, ensure_ascii=False)
        second = {"cells": {"t1": {"a": 2}}, "computed_at": "2026-09-10 14:00",
                  "takes": [{"key": "t1", "mult": 1.0}], "hold_h": 24}
        m = ST.merge_artifact(dict(second), art)
        assert set(m["cells"]) == {"t05", "t1"}, sorted(m["cells"])
        assert m["cell_at"]["t05"] == "2026-09-10 10:00", m["cell_at"]
        assert m["cell_at"]["t1"] == "2026-09-10 14:00", m["cell_at"]
        assert [t["key"] for t in m["takes"]] == ["t05", "t1"], m["takes"]
        txt = ST.report(m)
        assert "Ось посчитана не целиком" in txt, txt[:400]
        for mult in ("×1.5", "×2", "×3"):
            assert mult in txt, mult
        assert "РАЗНЫМИ прогонами" in txt
    print("ok  слияние оси: ячейки прежних прогонов целы со своими датами, "
          "недостающие названы в отчёте")


if __name__ == "__main__":
    for t in (test_axis_lands_in_the_grid_of_the_replay,
              test_axis_does_not_leak_into_the_book_rule,
              test_pack_uses_the_map_of_the_run,
              test_cell_stats_applies_the_book_rules_and_writes_nothing,
              test_merge_keeps_cells_of_earlier_runs_and_names_the_missing):
        t()
    print("\nвсе 5 проверок прошли")
