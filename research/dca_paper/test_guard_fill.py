#!/usr/bin/env python3
"""Проверки замера цены выхода охраны: кандидаты на границе, знак пользы
шорта, деньги через плечо и маржу, «нет принта» — прочерк, контроль
правила, отчёт."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402
import guard_fill as GF                                       # noqa: E402

H = 3600.0
T0 = 1790000000.0 - 1790000000.0 % H          # ровный час


def _row(rk, dep, sym, at, exit_ts, px, lev, margin, usd, w=1.0):
    return {"ruler": rk, "dep": dep, "sym": sym, "at": at, "exit_ts": exit_ts,
            "exit": R.GUARD_EXIT, "exit_px": px, "lev": lev, "margin": margin,
            "usd": usd, "side": "short", "rules": R.RULES,
            "book_rules": R.family_rules(rk), "fills": [[at, 100.0, w]]}


def bar(t, o, h, l, c, v=1000.0):
    return [t, o, h, l, c, v]


def test_candidates_and_money():
    b = T0 + 8 * H                                  # граница часа
    bars = {
        # AAA: до границы закрытие 100, на границе открытие 99 (шорту лучше на 100 б.п.)
        "AAAUSDT": [bar(b - 120, 100.5, 100.6, 100.4, 100.5), bar(b - 60, 100.4, 100.5, 99.9, 100.0),
                    bar(b, 99.0, 99.2, 98.0, 98.5), bar(b + 60, 98.5, 98.6, 98.0, 98.2)],
        # BBB: после границы принтов нет 15 минут — прочерк
        "BBBUSDT": [bar(b - 60, 50.0, 50.1, 49.9, 50.0), bar(b + 16 * 60, 51.0, 51.0, 51.0, 51.0)],
        # CCC: после границы цена выше — шорту хуже на 200 б.п.
        "CCCUSDT": [bar(b - 60, 10.0, 10.0, 10.0, 10.0), bar(b + 120, 10.2, 10.3, 10.1, 10.2)],
    }
    rows = [_row("optimal_h", 1000, "AAAUSDT", T0, b - 1, 100.0, 25.0, 40.0, 5.0),
            # четверть билета в одной ступени — деньги вчетверо меньше
            _row("optimal_h", 10000, "AAAUSDT", T0, b - 1, 100.0, 25.0, 400.0, 50.0, w=0.25),
            _row("optimal_h", 1000, "BBBUSDT", T0 + H, b - 1, 50.0, 25.0, 40.0, -1.0),
            _row("safe_h", 1000, "CCCUSDT", T0, b - 1, 10.0, 3.0, 100.0, 2.0),
            # чужая версия правил — не считается
            dict(_row("safe_h", 1000, "AAAUSDT", T0, b - 1, 100.0, 3.0, 100.0, 2.0), rules=R.RULES - 1)]
    res = GF.measure(rows, bars_of=lambda s, a, c: [x for x in bars.get(s, []) if a <= x[0] <= c],
                     log=lambda m: None)
    assert res["unique_exits"] == 3 and res["rows"] == 4, res
    o1 = res["books"]["optimal_h:1000"]
    assert o1["n"] == 2 and o1["with_after"] == 1 and o1["no_print"] == 1, o1
    assert abs(o1["median_bp"] - 100.0) < 1e-9, o1              # 100 → 99, шорту плюс
    assert abs(o1["usd"] - 0.01 * 25.0 * 40.0) < 1e-9, o1       # 1 % × плечо 25 × маржа 40 = 10 $
    o2 = res["books"]["optimal_h:10000"]
    assert abs(o2["usd"] - 25.0) < 1e-9 and o2["usd_trades"] == 50.0, o2
    s1 = res["books"]["safe_h:1000"]
    assert abs(s1["median_bp"] + 200.0) < 1e-9 and abs(s1["usd"] + 0.02 * 3.0 * 100.0) < 1e-9, s1
    assert s1["big_share"] == 1.0 and o1["big_share"] == 1.0
    # контроль правила: записанная цена = закрытие до границы → 0 б.п.
    assert res["check"]["n"] == 3 and res["check"]["median_abs_bp"] == 0.0, res["check"]
    txt = GF.report(res)
    assert "| optimal_h | $1,000 | 2 | 1 | 1 | +100.0 |" in txt, txt
    assert "плюс = живьём вышли бы лучше" in txt
    # контроль: записанная цена НЕ закрытие часа — контроль это видит
    # числом, а разница считается от закрытия часа, не от записанной
    rows2 = [_row("optimal_h", 1000, "AAAUSDT", T0, b - 1, 101.0, 25.0, 40.0, 5.0)]
    res2 = GF.measure(rows2, bars_of=lambda s, a, c: bars["AAAUSDT"], log=lambda m: None)
    assert abs(res2["check"]["median_abs_bp"] - 99.0) < 0.1, res2["check"]
    assert abs(res2["books"]["optimal_h:1000"]["median_bp"] - 100.0) < 1e-9, res2["books"]
    print("ok  замер цены выхода охраны: кандидаты на границе, знак и деньги шорта, "
          "«нет принта» — прочерк, контроль правила видит расхождение")


if __name__ == "__main__":
    test_candidates_and_money()
    print("\nвсе проверки прошли")
