#!/usr/bin/env python3
"""Проверки фильтров короткой стороны.

Кусаются: «в лонге» решается по МОМЕНТУ решения (позиция, закрытая до
него, не считается, а открытая позже — тем более); политики `only_long`
и `not_long` делят решения ровно надвое, ничего не теряя; контроль
`random` берёт ровно столько же, сколько `only_long`; гейт по ставке
отказывает и по знаку, и по незнанию, и эти отказы считаются РАЗНЫМИ
числами; сам замер не пишет ни строки в журнал книг.
"""
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import pair_gate as PG                                        # noqa: E402
import test_pair as TP                                        # noqa: E402

H = 3600.0
T0 = TP.T0


def _long_row(sym, at, hold_h, dep=10000):
    return {"dep": dep, "ruler": "safe", "at": float(at),
            "exit_ts": float(at) + hold_h * H, "sym": sym, "side": "long",
            "lev": 2.0, "margin": 25.0, "pnl_frac": 0.01, "usd": 0.25,
            "exit": "тейк", "written_at": at + H, "rules": R.RULES}


def _ctx(rate_by_sym):
    t = np.asarray([int((T0 - 3600.0) * 1000)], dtype=np.int64)
    return {"to_asset": {s: s for s in rate_by_sym},
            "funding": {s: (t, np.asarray([r], dtype=float))
                        for s, r in rate_by_sym.items() if r is not None}}


def test_in_long_is_decided_at_the_moment_of_the_decision():
    held = PG.held_intervals([_long_row("AAAUSDT", T0, 10.0),
                              _long_row("BBBUSDT", T0 - 50 * H, 10.0),
                              _long_row("CCCUSDT", T0 + 5 * H, 10.0)], 10000)
    assert PG.in_long(held, "AAAUSDT", T0 + 3 * H) is True
    assert PG.in_long(held, "BBBUSDT", T0 + 3 * H) is False, "закрытая раньше"
    assert PG.in_long(held, "CCCUSDT", T0 + 3 * H) is False, "открытая позже"
    assert PG.in_long(held, "AAAUSDT", T0 + 10 * H) is False, "выход встык"
    # чужой депозит в «что держим» не попадает
    other = PG.held_intervals([_long_row("AAAUSDT", T0, 10.0, dep=1000)], 10000)
    assert not other, other
    print("ok  «в лонге» решается моментом решения: закрытая раньше и "
          "открытая позже не считаются, чужой депозит не считается")


def test_name_policies_split_the_decisions_without_loss():
    held = PG.held_intervals([_long_row("AAAUSDT", T0, 10.0)], 10000)
    shorts = [TP._short("AAAUSDT", T0 + H), TP._short("BBBUSDT", T0 + H),
              TP._short("CCCUSDT", T0 + 2 * H)]
    ctx = _ctx({"AAAUSDT": 0.0001, "BBBUSDT": 0.0001, "CCCUSDT": 0.0001})
    only, w1 = PG.pick(shorts, held, ctx, "only_long", "off")
    nots, w2 = PG.pick(shorts, held, ctx, "not_long", "off")
    alls, w3 = PG.pick(shorts, held, ctx, "all", "off")
    assert [r["sym"] for r in only] == ["AAAUSDT"], only
    assert {r["sym"] for r in nots} == {"BBBUSDT", "CCCUSDT"}, nots
    assert len(only) + len(nots) == len(alls) == 3
    assert w1["по имени"] == 2 and w2["по имени"] == 1
    rnd, _w = PG.pick(shorts, held, ctx, "random", "off")
    assert len(rnd) == len(only), (len(rnd), len(only))
    print(f"ok  политики делят решения без потерь: только {len(only)}, "
          f"кроме {len(nots)}, все {len(alls)}; контроль берёт "
          f"{len(rnd)} — столько же, сколько «только»")


def test_gate_refuses_by_sign_and_by_ignorance_separately():
    held = {}
    shorts = [TP._short("AAAUSDT", T0), TP._short("BBBUSDT", T0),
              TP._short("CCCUSDT", T0)]
    # плюс шорту благоприятен (лонги платят шортам), минус — нет,
    # у третьего ставки нет вовсе
    ctx = _ctx({"AAAUSDT": 0.0002, "BBBUSDT": -0.0002, "CCCUSDT": None})
    keep, why = PG.pick(shorts, held, ctx, "all", "on")
    assert [r["sym"] for r in keep] == ["AAAUSDT"], keep
    assert why["по ставке"] == 1 and why["ставка неизвестна"] == 1, why
    off, _w = PG.pick(shorts, held, ctx, "all", "off")
    assert len(off) == 3, off
    print(f"ok  гейт по ставке: взят {len(keep)} из {len(off)}; отказ по "
          f"знаку {why['по ставке']} и по незнанию "
          f"{why['ставка неизвестна']} — разные числа")


def test_probe_writes_nothing_into_the_book_journal():
    """Замер — проба: журнал книг он не трогает ни строкой."""
    longs = [TP._long(f"L{i}USDT", T0 + i * H) for i in range(6)]
    shorts = [TP._short(f"S{i}USDT", T0 + i * H) for i in range(6)]
    lc, sc = TP._caches(longs, shorts)
    with tempfile.TemporaryDirectory() as td:
        lj = os.path.join(td, "journal.jsonl")
        with open(lj, "w", encoding="utf-8") as f:
            f.write(json.dumps(_long_row("S1USDT", T0, 50.0)) + "\n")
        before = sorted(os.listdir(td))
        s = PG.run(dep=R.DEPOSITS[1], long_cache=lc, short_cache=sc,
                   long_journal=lj, keys=["pair_safe"],
                   ctx={"error": "рядов нет"}, now=T0 + 200 * H,
                   log=lambda *a: None)
        assert sorted(os.listdir(td)) == before, "замер написал в журнал"
        cells = s["cells"]
        assert f"pair_safe|all|off" in cells and f"pair_safe|random|off" in cells
        a, o = cells["pair_safe|all|off"], cells["pair_safe|only_long|off"]
        assert a["kept"] == 6 and o["kept"] == 1, (a["kept"], o["kept"])
        assert cells["pair_safe|random|off"]["kept"] == o["kept"]
        # гейт без рядов funding отказывает ВСЕМ по незнанию, а не пускает
        g = cells["pair_safe|all|on"]
        assert g["kept"] == 0 and g["drops"]["ставка неизвестна"] == 6, g
        txt = PG.report(s)
        assert "только те, что в лонге" in txt and "КОНТРОЛЬ размера" in txt
        print(f"ok  проба не пишет в журнал; «все» {a['kept']}, «только в "
              f"лонге» {o['kept']}, гейт без рядов отказывает всем по "
              "незнанию")


if __name__ == "__main__":
    for t in (test_in_long_is_decided_at_the_moment_of_the_decision,
              test_name_policies_split_the_decisions_without_loss,
              test_gate_refuses_by_sign_and_by_ignorance_separately,
              test_probe_writes_nothing_into_the_book_journal):
        t()
    print("\nвсе 4 проверки прошли")
