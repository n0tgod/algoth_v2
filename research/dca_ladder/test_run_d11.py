#!/usr/bin/env python3
"""Проверки D11: ноги из выборов h24 (короткая сторона руки, тем же `_leg`),
отсчёт по гейту «любой» и срок — на время прогона, сквозной реплей."""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d11 as D11                                         # noqa: E402
import run_d10 as D10                                         # noqa: E402
import run_d2 as D2                                           # noqa: E402
import trades as TR                                           # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600


def _picks(path, hours, arms=("nn", "gbm")):
    with open(path, "w", encoding="utf-8") as f:
        for h in hours:
            for arm in arms:
                rows_s = [
                    # лист: mae — минимум цены (< 0), mfe — максимум; шорту
                    # минимум и есть ход в пользу
                    {"sym": "SSSUSDT", "fwd": -420.0, "px": 100.0,
                     "mae": -700.0, "mfe": 120.0, "mae_q": -650.0, "mfe_q": 110.0,
                     "fwd_z": -1.4, "beta": 1.0},
                    {"sym": "TTTUSDT", "fwd": -20.0, "px": 50.0,        # край < 33
                     "mae": -300.0, "mfe": 80.0, "fwd_z": -0.2},
                    {"sym": "LLLUSDT", "fwd": 300.0, "px": 10.0,        # лонг по знаку
                     "mae": -100.0, "mfe": 500.0, "fwd_z": 1.0}]
                rows_l = [{"sym": "AAAUSDT", "fwd": 250.0, "px": 20.0,
                           "mae": -90.0, "mfe": 400.0}]
                f.write(json.dumps({"arm": arm, "hour": h, "long": rows_l,
                                    "short": rows_s}) + "\n")


def test_legs_come_from_h24_short_picks_of_the_arm():
    tmp = tempfile.mkdtemp(prefix="d11-")
    path = os.path.join(tmp, "picks.jsonl")
    hours = ["2026-09-01-00", "2026-09-01-01", "2026-09-01-02"]
    _picks(path, hours)
    try:
        legs = D11.h24_legs("nn", path=path, log=lambda *a: None)
        assert len(legs) == 3, legs            # по одной годной ноге в час
        assert all(g["side"] == "short" and g["sym"] == "SSSUSDT" and g["arm"] == "nn"
                   for g in legs), legs
        assert all(g["fav"] < 0 < g["adv_q"] for g in legs), legs[0]
        assert [g["at"] for g in legs] == [TR.hour_end(h) for h in hours]
        assert all(D10.gate_of(g) for g in legs)
        assert D11.h24_legs("gbm", path=path, limit=2, log=lambda *a: None)[0]["arm"] == "gbm"
        assert len(D11.h24_legs("gbm", path=path, limit=2, log=lambda *a: None)) == 2
        assert D11.h24_legs("nn", path=os.path.join(tmp, "none.jsonl"),
                            log=lambda *a: None) == []
        print(f"ok  ноги h24: {len(legs)} коротких выборов руки nn под краем, "
              "лонг по знаку и край < 33 отброшены, момент — закрытие часа")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reference_gate_and_hold_are_set_for_the_run_only():
    ref0, hold0, cd0 = D10.REF_GATE, D2.HOLD_H, D10.cell.__defaults__
    was = D11.configure(hold_h=24)
    try:
        assert D10.REF_GATE == "any" and D10.cell.__defaults__[0] == "any"
        assert D2.HOLD_H == 24
    finally:
        D11.restore(was)
    assert D10.REF_GATE == ref0 == "rr2" and D2.HOLD_H == hold0 == 72
    assert D10.cell.__defaults__ == cd0
    print("ok  гейт отсчёта «любой» и срок 24 ч — только на время прогона; "
          "после — прежние rr2 и 72")


def test_run_end_to_end_on_synthetic_bars():
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = T10._legs(at, "SSSUSDT") + T10._legs(at, "TTTUSDT")
    for g in legs:
        g["arm"] = "nn"
    s = T10._with_levels(lambda: D11.run(arm="nn", src=src, legs=legs,
                                          log=lambda *a: None))
    assert s["signal"]["arm"] == "nn" and s["signal"]["hold_h"] == 72
    assert s["ref_gate"] == "any" and s["positions"] == 20, (s["ref_gate"], s["positions"])
    dep = int(s["deposits"][1])
    ref = s["cells"][f"{s['ref']}|optimal_s|{dep}"]
    assert ref["gate"] == "any", ref
    # отсчёт по «любому» гейту виден в разрезе плеча: все 20 ног, а не 8 (rr2)
    ls = s["lev_split"]["optimal_s"]
    assert ls["ladder"]["n"] + ls["no_ladder"]["n"] == 20, ls
    assert s["gate_cells"][f"any|{s['ref']}|optimal_s"]["taken"] == ref["taken"]
    assert D10.REF_GATE == "rr2" and D2.HOLD_H == 72        # восстановлено
    txt = D11.report(s)
    assert "# D11 — DCA-лестница на сигнале h24" in txt and "при гейте «any»" in txt
    assert "## Книга" in txt
    print(f"ok  сквозной D11: отсчёт по гейту «any» взял {ref['taken']} позиций, "
          "отчёт с заголовком D11 поверх формы D10")


if __name__ == "__main__":
    test_legs_come_from_h24_short_picks_of_the_arm()
    test_reference_gate_and_hold_are_set_for_the_run_only()
    test_run_end_to_end_on_synthetic_bars()
    print("\nвсе 3 проверки прошли")
