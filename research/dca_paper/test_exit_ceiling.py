#!/usr/bin/env python3
"""Потолок выхода (`exit_ceiling.py`): идеальный выход — лучший час СТРОГО
внутри забора (не позже выхода правила), запись без прироста не трогается,
открытая не трогается; слепой выход остаётся внутри забора; статистика
позиций считает долю «правило уже лучшее» и разбор по типу выхода.
Подделка в каждом случае доказывается до проверки."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exit_ceiling as EC                                     # noqa: E402
import wave as WV                                             # noqa: E402

H = 3600.0
AT = 1_789_002_000.0


def _rec(steps, exit="срок", state="closed", sym="AAAUSDT"):
    marks = [(AT + i * H, d) for i, d in enumerate(steps)]
    final = sum(steps)
    return {"sym": sym, "at": AT, "exit_ts": AT + len(steps) * H, "side": "short", "lev": 5.0,
            "pnl": final, "exit": exit, "marks": marks, "entry_px": 100.0, "state": state,
            "fills": [[AT, 100.0, 1.0]]}


def test_ceiling_picks_best_hour_inside_fence_only():
    up_then_down = _rec([0.02, 0.05, 0.03, -0.04, -0.06])      # пик в час 3 (0.10), итог 0.0
    p = WV.path_of(up_then_down)
    assert p["K"] == 5 and abs(p["cum"][3] - 0.10) < 1e-12 and abs(p["final"]) < 1e-12, p
    out, hits = EC.ceiling_recs([up_then_down], "safe_h")
    r = out[0]
    assert r["exit"] == EC.WHY_CEIL and abs(float(r["pnl"]) - 0.10) < 1e-12, r["pnl"]
    assert len(r["marks"]) == 3 and abs(r["exit_ts"] - (AT + 3 * H - 1)) < 1e-6
    (a, b, k, K), = hits
    assert k == 3 and K == 5 and a is up_then_down
    # итог и есть лучший час — запись не трогается, прирост 0
    rising = _rec([0.01, 0.02, 0.03], exit="тейк")
    out2, hits2 = EC.ceiling_recs([rising], "safe_h")
    assert out2[0] is rising and hits2[0][1] is rising and hits2[0][2] == 3
    # час выхода правила — НЕ кандидат: пик в последнем часе не даёт «выхода раньше»
    late_peak = _rec([-0.01, -0.02, 0.10])
    out3, _ = EC.ceiling_recs([late_peak], "safe_h")
    assert out3[0] is late_peak
    # открытая и без отметок — как есть
    opn = _rec([0.05, 0.01], state="open")
    bare = dict(_rec([0.05]), marks=[])
    out4, hits4 = EC.ceiling_recs([opn, bare], "safe_h")
    assert out4 == [opn, bare] and hits4 == []
    # забор срока: у длинной книги потолок не заглядывает дальше hold−1,
    # даже если путь (отметки) тянется дальше и пик там
    import rules as R
    hold = R.hold_of("safe")
    steps = [0.001] * (hold + 8)
    steps[9] = 0.5                                              # пик внутри забора (час 10)
    steps[hold + 2] = 1.0                                       # больший пик ЗА забором
    steps[hold + 5] = -3.0                                      # итог провальный
    long_rec = dict(_rec(steps), side="long")
    p5 = WV.path_of(long_rec)
    inside = max(p5["cum"][k] for k in range(1, hold))
    beyond = max(p5["cum"].values())
    assert beyond > inside > p5["final"], "подделка легла: за забором выше, чем внутри, итог ниже"
    out5, hits5 = EC.ceiling_recs([long_rec], "safe")
    assert hits5[0][2] <= hold - 1 and abs(float(out5[0]["pnl"]) - inside) < 1e-9, (hits5[0][2], out5[0]["pnl"])
    print("ok  потолок: лучший час строго до выхода правила и не дальше срока; без прироста, "
          "открытая, без отметок — как есть")


def test_random_exit_stays_inside_fence_and_stats_count_rule_best():
    rec = _rec([0.02, 0.05, 0.03, -0.04, -0.06])
    rng = random.Random(7)
    seen = set()
    for _ in range(200):
        out, hits = EC.random_recs([rec], "safe_h", rng)
        r = out[0]
        assert len(hits) == 1 and hits[0][0] is rec and hits[0][3] == 5 and 1 <= hits[0][2] <= 5
        if r is rec:
            seen.add("rule")
        else:
            assert r["exit"] == EC.WHY_RAND
            k = len(r["marks"])
            assert 1 <= k <= 4, k
            seen.add(k)
    assert seen == {"rule", 1, 2, 3, 4}, seen
    recs = [_rec([0.02, 0.05, 0.03, -0.04, -0.06], exit="пол"),
            _rec([0.01, 0.02, 0.03], exit="тейк", sym="BBBUSDT"),
            _rec([0.30, 0.10, 0.05], exit="срок", sym="CCCUSDT")]
    _out, hits = EC.ceiling_recs(recs, "safe_h")
    st = EC.pos_stats(hits)
    assert st["n"] == 3
    # первая: пик 0.10 против итога 0.0 → +0.10; вторая и третья: итог и есть пик → 0
    assert abs(st["delta_sum"] - 0.10) < 1e-9, st["delta_sum"]
    assert st["rule_best"] == 2 / 3
    assert st["gt5"] == 1 / 3 and st["gt20"] == 0
    assert st["by_exit"]["пол"]["n"] == 1 and abs(st["by_exit"]["пол"]["delta_sum"] - 0.10) < 1e-9
    assert st["by_exit"]["тейк"]["delta_sum"] == 0.0 and st["by_exit"]["срок"]["delta_sum"] == 0.0
    assert st["k_share_median"] == 1.0, st["k_share_median"]
    print("ok  слепой выход внутри забора; статистика: правило лучшее у 2 из 3, прирост по типу выхода")


if __name__ == "__main__":
    test_ceiling_picks_best_hour_inside_fence_only()
    test_random_exit_stays_inside_fence_and_stats_count_rule_best()
    print("\nвсе 2 проверки прошли")
