#!/usr/bin/env python3
"""Проверки D12: пик одновременно открытых, билет от своего пика не ниже
пола, ячейки «пул → свой» на подставных барах, вердикт по половинам."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d12 as D12                                         # noqa: E402
import run_d10 as D10                                         # noqa: E402
import rules as R                                             # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600


def test_peak_and_own_share():
    rows = [{"at": 0, "exit_ts": 10}, {"at": 5, "exit_ts": 15},
            {"at": 10, "exit_ts": 20}, {"at": 30, "exit_ts": 40}]
    assert D12.peak_open(rows) == 2          # выход в 10 раньше входа в 10
    assert D12.peak_open([]) is None
    # $10k, пик 20 → билет 10000 / 30 = $333 ≫ пол; $1k, пик 20 → $33 ≥ пол $25
    sh = D12.own_share(10000, 20, "optimal_s")
    assert abs(sh * 10000 - 10000 / 30) < 1e-6, sh
    sh1 = D12.own_share(1000, 20, "optimal_s")
    assert abs(sh1 * 1000 - max(R.floor_of("optimal_s"), 1000 / 30)) < 1e-6
    # $1k, пик 200 → 1000/300 = $3.3 < пол → пол
    sh2 = D12.own_share(1000, 200, "optimal_s")
    assert abs(sh2 * 1000 - R.floor_of("optimal_s")) < 1e-6
    assert D12.own_share(1000, None, "optimal_s") is None
    print(f"ok  пик по заметающей прямой 2; свой билет $10k/пик 20 = ${sh * 10000:.0f}, "
          f"пол держит мелкие ($1k/пик 200 = ${sh2 * 1000:.0f})")


def test_run_end_to_end_pool_vs_own():
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = T10._legs(at, "SSSUSDT") + T10._legs(at, "TTTUSDT")
    for g in legs:
        g["arm"] = "nn"
    s = T10._with_levels(lambda: D12.run(arm="nn", src=src, legs=legs,
                                          log=lambda *a: None))
    dep = int(s["deposits"][1])
    assert s["signal"]["ref_gate"] == "any" and s["positions"] == 20
    key = "c1:none:t2"
    c = s["cells"][f"{key}|optimal_s|{dep}|net"]
    assert c["pool"]["taken"] >= 1 and c["own"]["taken"] >= 1, c
    # своего пика 1–2 позиции → билет крупнее пула, деньги те же по знаку,
    # итог в долях депозита больше по модулю
    assert s["peaks"][f"{key}|optimal_s"] in (1, 2), s["peaks"]
    assert c["own_ticket"] > c["pool_ticket"], c
    assert abs(c["own"]["final"]) > abs(c["pool"]["final"]), (c["own"]["final"], c["pool"]["final"])
    h = s["cells"][f"{key}|optimal_s|{dep}|halves"]
    assert "A" in h and "B" in h and h["mid"] > 0
    v = D12.verdict(s)
    assert set(v) == {"optimal_s", "safe_s"} and isinstance(v["optimal_s"]["held_both_halves"], list)
    assert D10.REF_GATE == "rr2" and D10.cell.__defaults__ == ("rr2", False, None)
    txt = D12.report(s)
    assert "# D12" in txt and "билет пула → свой" in txt and "`c1:none:t2`" in txt
    assert "Чего замер НЕ говорит" in txt
    print(f"ok  сквозной D12: пик {s['peaks'][f'{key}|optimal_s']}, билет "
          f"${c['pool_ticket']} → ${c['own_ticket']}, итог нетто {c['pool']['final']:+.4f} → "
          f"{c['own']['final']:+.4f}; умолчания D10 восстановлены")


if __name__ == "__main__":
    test_peak_and_own_share()
    test_run_end_to_end_pool_vs_own()
    print("\nвсе 2 проверки прошли")
