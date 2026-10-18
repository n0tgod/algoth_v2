#!/usr/bin/env python3
"""Сетка выходов (`exit_grid.py`): каждое правило решает час выхода ТОЛЬКО по
пути до этого часа и не позже забора; правило отбора берёт победителя по
первой половине и судит по второй. Подделка доказывается до проверки."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exit_grid as EG                                        # noqa: E402
import wave as WV                                             # noqa: E402

H = 3600.0
AT = 1_789_002_000.0


def _rec(steps, exit="срок"):
    marks = [(AT + i * H, d) for i, d in enumerate(steps)]
    return {"sym": "AUSDT", "at": AT, "exit_ts": AT + len(steps) * H, "side": "short", "lev": 5.0,
            "pnl": sum(steps), "exit": exit, "marks": marks, "entry_px": 100.0, "state": "closed",
            "fills": [[AT, 100.0, 1.0]]}


def test_rules_decide_on_the_past_only_and_inside_the_fence():
    # путь: 0.03, 0.08, 0.14, 0.12, 0.02, -0.05, -0.04, -0.10, ...
    steps = [0.03, 0.05, 0.06, -0.02, -0.10, -0.07, 0.01, -0.06] + [0.0] * 16
    r = _rec(steps)
    p = WV.path_of(r)
    cum = [round(p["cum"][k], 6) for k in range(1, 9)]
    assert cum == [0.03, 0.08, 0.14, 0.12, 0.02, -0.05, -0.04, -0.10], cum
    last = p["K"] - 1
    assert EG.exit_hour(p, last, ("term", 6)) == 6
    assert EG.exit_hour(p, last, ("term", 99)) is None, "срок за забором — выход книги"
    assert EG.exit_hour(p, last, ("tstop", 4)) is None, "к 4 ч в плюсе — стопа нет"
    assert EG.exit_hour(p, last, ("tstop", 6)) == 6, "к 6 ч в минусе — стоп"
    # трейлинг 0.05: пик 0.14 (ч.3) ≥ 0.05; падение на 0.05 — к ч.5 (0.02 ≤ 0.09)
    assert EG.exit_hour(p, last, ("trail", 0.05)) == 5
    # трейлинг 0.10: пик 0.14 ≥ 0.10; 0.14−0.10=0.04 — ч.5 (0.02)
    assert EG.exit_hour(p, last, ("trail", 0.10)) == 5
    # трейлинг 0.20: пик 0.14 < 0.20 — не включился
    assert EG.exit_hour(p, last, ("trail", 0.20)) is None
    assert EG.exit_hour(p, last, ("lock", 0.10)) == 3
    assert EG.exit_hour(p, last, ("lock", 0.25)) is None
    # будущее не видно: подменить хвост после ч.3 не меняет решения фиксации и срока 3
    r2 = _rec(steps[:3] + [5.0] * 21)
    p2 = WV.path_of(r2)
    assert EG.exit_hour(p2, p2["K"] - 1, ("lock", 0.10)) == 3
    assert EG.exit_hour(p2, p2["K"] - 1, ("term", 3)) == 3
    out, hits = EG.grid_recs([r], "safe_h", ("lock", 0.10))
    assert out[0]["exit"] == EG.WHY and abs(float(out[0]["pnl"]) - 0.14) < 1e-9 and hits[0][2] == 3
    out2, hits2 = EG.grid_recs([r], "safe_h", ("trail", 0.20))
    assert out2[0] is r and hits2[0][1] is r
    print("ok  правила сетки решают по прошлому и внутри забора: срок, стоп по времени, трейлинг, фиксация")


def test_selection_picks_by_first_half_and_judges_on_second():
    def cash(v):
        return {k: {1000: {"final": v[k]}, 10000: {"final": v[k]}} for k in v}
    keys = ["safe_h", "optimal_h", "aggr_h"]
    pk = ["pair_safe"]
    half1 = {"T6": {"cash": cash({k: 0.50 for k in keys + pk})},
             "T12": {"cash": cash({k: 0.10 for k in keys + pk})}}
    half2 = {"T6": {"cash": cash({k: 0.30 for k in keys + pk})},
             "T12": {"cash": cash({k: 0.90 for k in keys + pk})},
             "rule": {"cash": cash({k: 0.20 for k in keys + pk})},
             "random": {"cash": {k: {1000: {"all": [0.10] * 20}, 10000: {"all": [0.10] * 19 + [0.40]}}
                                 for k in keys + pk}}}
    res = {"keys": {"short": keys, "pair": pk}, "grid": ["T6", "T12"],
           "windows": {"half1": half1, "half2": half2}}
    s = EG.select(res)
    assert s["winner"] == "T6", "победитель — по первой половине, а не лучший на второй (T12)"
    j = s["judge_half2"]["safe_h:10000"]
    assert j["cell"] == 0.30 and j["rule"] == 0.20 and abs(j["blind_not_worse"] - 0.05) < 1e-9
    assert s["beats_rule_half2"] and s["beats_blind_half2"]
    half2["rule"] = {"cash": cash({k: 0.35 for k in keys + pk})}
    assert not EG.select(res)["beats_rule_half2"], "правило книги лучше на второй — не кандидат"
    print("ok  отбор: победитель по первой половине, суд на второй против правила и слепого выхода")


if __name__ == "__main__":
    test_rules_decide_on_the_past_only_and_inside_the_fence()
    test_selection_picks_by_first_half_and_judges_on_second()
    print("\nвсе 2 проверки прошли")
