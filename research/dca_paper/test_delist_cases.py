#!/usr/bin/env python3
"""Замер делистингов: имена из заголовка и описания (перп и спот раздельно),
снятые контракты из справочника, «держали» и «вошли после» по уникальному
входу, «после объявления» — итог минус путь на часе публикации."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import delist_cases as D                                     # noqa: E402

H = 3600


def test_parse_and_closed():
    a = D.parse_ann({"title": "Delisting of ABCUSDT and 1000XYZUSDT Perpetual Contracts",
                     "description": "Also FOO/USDT spot pair. USDT margin.", "publishTime": "1790000000000"})
    assert a["perps"] == ["1000XYZUSDT", "ABCUSDT"] and a["spots"] == ["FOO"] and a["t"] == 1790000000000
    cl = D.closed_contracts({"ABCUSDT": {"status": "Closed", "delivery_time": "1790500000000"},
                             "OLDUSDT": {"status": "Closed", "delivery_time": "1700000000000"},
                             "LIVEUSDT": {"status": "Trading", "delivery_time": "0"}}, D.SINCE_MS)
    assert cl == [("ABCUSDT", 1790500000000)]
    print("ok  объявление: перпы и спот раздельно; справочник: снятые в окне")


def test_match_held_after_and_effect():
    t0 = 1_790_000_000
    ann = {"t": (t0 + 5 * H + 600) * 1000, "title": "Delisting of ABCUSDT", "perps": ["ABCUSDT"], "spots": []}
    cum = {1: 0.01, 2: 0.02, 3: 0.0, 4: -0.05, 5: -0.10, 6: -0.20, 7: -0.30}
    pos = [{"book": "b1", "sym": "ABCUSDT", "side": "long", "span": (t0, t0 + 7 * H), "final": -0.30, "cum": cum},
           {"book": "b2", "sym": "ABCUSDT", "side": "long", "span": (t0, t0 + 7 * H), "final": -0.30, "cum": cum},
           {"book": "b1", "sym": "ABCUSDT", "side": "short", "span": (t0 + 8 * H, t0 + 20 * H), "final": 0.4, "cum": {1: 0.4}},
           {"book": "b1", "sym": "ABCUSDT", "side": "long", "span": (t0 + 30 * H, t0 + 40 * H), "final": 0.1, "cum": {1: 0.1}},
           {"book": "b1", "sym": "ZZZUSDT", "side": "long", "span": (t0, t0 + 7 * H), "final": 0.0, "cum": {1: 0.0}}]
    held, after = D.match([ann], pos, {"ABCUSDT": t0 + 25 * H})
    assert len(held) == 1 and held[0]["books"] == ["b1", "b2"], "сестры одного входа — один случай"
    assert len(after) == 1 and after[0]["side"] == "short", "вход после снятия контракта не считается"
    eff = D.after_announcement(cum, t0, ann["t"] / 1000)
    assert abs(eff - (-0.30 - (-0.20))) < 1e-12, eff            # публикация в 6-м часе: итог − путь[6]
    assert D.span_of({"at": t0, "marks": [[t0, 0.01], [t0 + 3 * H, 0.02]]}) == (t0, t0 + 4 * H)
    assert D.span_of({"at": t0, "exit_ts": t0 + 5}) == (t0, t0 + 5)
    print("ok  держали/вошли после — по уникальному входу; после объявления = итог − путь на часе публикации")


def test_report_zero_says_so():
    r = {"window_from": "x", "computed_at": "y", "secs": 1, "fetch_error": None, "anns": 3, "anns_perp": 2,
         "anns_spot_only": 1, "perps_named": 4, "perps_named_ever_in_books": 0, "closed_contracts": 5,
         "closed_ever_in_books": 0, "positions": 100, "held": [], "entered_after": []}
    t = D.report(r)
    assert "Случаев ноль" in t and "| **держали в момент объявления** (уникальных входов) | **0** |" in t
    print("ok  ноль случаев печатается словами и числом")


if __name__ == "__main__":
    test_parse_and_closed()
    test_match_held_after_and_effect()
    test_report_zero_says_so()
    print("\nвсе 3 проверки прошли")
