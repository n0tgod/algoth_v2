#!/usr/bin/env python3
"""Проверки разреза DCA-книг по руке модели.

Кусаются: автор решения выводится из ПРАВИЛА книги (больший модуль
прогноза), а не из порядка рук; равенство прогнозов не приписывается
молча; строка без ноги не зачисляется ни одной руке; деньги рук в сумме
с «нет руки» дают книгу; строки чужой версии правил в счёт не идут.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import arm_split as A                                        # noqa: E402
import rules as R                                            # noqa: E402

T0 = 1786320000.0
H = 3600.0


def _leg(sym, arm, at, fwd, side="long"):
    return {"sym": sym, "arm": arm, "at": at, "fwd": fwd, "side": side}


def _row(sym, at, usd, ruler="optimal", dep=10000, side="long",
         rules=None, pnl=None):
    return {"sym": sym, "at": at, "usd": usd, "ruler": ruler, "dep": dep,
            "side": side, "rules": R.RULES if rules is None else rules,
            "pnl_frac": (usd / 25.0) if pnl is None else pnl,
            "written_at": at + 4 * H, "exit_ts": at + 72 * H,
            "margin": 25.0, "lev": 3.0, "exit": "тейк"}


def test_author_follows_the_book_rule_not_the_arm_order():
    # одна рука
    idx = A.legs_index([_leg("AAAUSDT", "nn", T0, -300.0)])
    assert A.author(idx[A.key_of("AAAUSDT", "long", T0)]) == ("nn", None)
    # обе руки: автор — БОЛЬШИЙ модуль прогноза; переставляем числа —
    # переставляется и автор (иначе правило не читается вовсе)
    both = [_leg("BBBUSDT", "gbm", T0, 120.0), _leg("BBBUSDT", "nn", T0, 400.0)]
    k = A.key_of("BBBUSDT", "long", T0)
    assert A.author(A.legs_index(both)[k])[0] == "nn"
    both[0]["fwd"], both[1]["fwd"] = 400.0, 120.0
    assert A.author(A.legs_index(both)[k])[0] == "gbm"
    # равенство — неразрешимо, а не «первая попавшаяся»
    both[0]["fwd"] = both[1]["fwd"] = 250.0
    assert A.author(A.legs_index(both)[k]) == (None, "неразрешимо")
    # ноги нет
    assert A.author([]) == (None, "нет решения")
    # сторона входит в ключ: короткая нога не отвечает за длинную строку
    idx2 = A.legs_index([_leg("CCCUSDT", "nn", T0, -300.0, side="short")])
    assert A.key_of("CCCUSDT", "long", T0) not in idx2
    print("ok  автор — из правила книги (больший |прогноз|); перестановка "
          "чисел переставляет автора, равенство — «неразрешимо», сторона в ключе")


def test_money_of_arms_sums_to_the_book_and_orphans_are_named():
    legs = [_leg("AAAUSDT", "gbm", T0, 300.0),
            _leg("BBBUSDT", "nn", T0 + H, -400.0),
            _leg("BBBUSDT", "gbm", T0 + H, -100.0),         # спор: берёт nn
            _leg("DDDUSDT", "gbm", T0 + 2 * H, 200.0),
            _leg("DDDUSDT", "nn", T0 + 2 * H, 200.0)]       # равенство
    rows = [_row("AAAUSDT", T0, +5.0),
            _row("BBBUSDT", T0 + H, -2.0),
            _row("DDDUSDT", T0 + 2 * H, +1.0),              # неразрешимо
            _row("ZZZUSDT", T0 + 3 * H, +7.0),              # ноги нет
            _row("AAAUSDT", T0, +99.0, rules=R.RULES - 1)]  # чужая версия
    s = A.run(rows=rows, legs=legs, log=lambda *a: None)
    assert s["rows"] == 4 and s["rows_all"] == 5, (s["rows"], s["rows_all"])
    a = s["attribution"]
    assert (a["one"], a["both"], a["tie"], a["no_leg"]) == (1, 1, 1, 1), a
    c = s["cells"]["optimal:10000"]
    got = {k: v["usd"] for k, v in c["arms"].items() if v.get("n")}
    assert got == {"gbm": 5.0, "nn": -2.0, "нет руки": 8.0}, got
    assert abs(sum(got.values()) - c["all"]["usd"]) < 1e-9
    assert c["all"]["n"] == 4 and c["arms"]["нет руки"]["n"] == 2
    # 99 $ чужой версии не попали никуда: 5 − 2 + 1 + 7 = 11
    assert c["all"]["usd"] == 11.0, c["all"]
    assert s["agree"]["both_arms"] == 2 and s["agree"]["decisions"] == 3
    assert s["composition"]["long"] == {"gbm": 3, "nn": 2}
    txt = A.report(s)
    assert "нет руки" in txt and "Чего замер НЕ говорит" in txt
    assert "| одна рука на решении | 1 |" in txt
    assert f"сделок меньше {A.N_MIN}" in txt          # вердикта на 4 строках нет
    print(f"ok  деньги рук {got} в сумме дают книгу {c['all']['usd']:+.2f} $; "
          "чужая версия правил и строка без ноги в руки не зачислены")


def test_without_the_sheets_journal_nothing_pretends_to_have_an_arm():
    rows = [_row("AAAUSDT", T0, +5.0), _row("BBBUSDT", T0 + H, -2.0)]
    s = A.run(rows=rows, legs=[], log=lambda *a: None)
    c = s["cells"]["optimal:10000"]
    assert s["attribution"]["no_leg"] == 2
    assert c["arms"]["gbm"]["n"] == 0 and c["arms"]["nn"]["n"] == 0
    assert c["arms"]["нет руки"]["usd"] == 3.0
    assert s["agree"]["share"] is None
    txt = A.report(s)
    assert "| ноги нет (лист старше журнала книги) | 2 |" in txt
    assert "| `optimal` (оптимальная) | деревья |" not in txt
    print("ok  без журнала листов руки не выдумываются: обе по нулю строк, "
          "деньги стоят под «нет руки», доля согласия — прочерк")


def test_halves_split_by_decision_time():
    legs = [_leg("AAAUSDT", "gbm", T0, 300.0),
            _leg("BBBUSDT", "gbm", T0 + 100 * H, 300.0)]
    rows = [_row("AAAUSDT", T0, +4.0), _row("BBBUSDT", T0 + 100 * H, -6.0)]
    s = A.run(rows=rows, legs=legs, log=lambda *a: None)
    g = s["cells"]["optimal:10000"]["arms"]["gbm"]
    assert (g["half_a"], g["half_b"]) == (4.0, -6.0), g
    assert g["n_a"] == 1 and g["n_b"] == 1
    print(f"ok  половины окна режутся по моменту решения: A {g['half_a']:+.2f} $, "
          f"B {g['half_b']:+.2f} $")


if __name__ == "__main__":
    test_author_follows_the_book_rule_not_the_arm_order()
    test_money_of_arms_sums_to_the_book_and_orphans_are_named()
    test_without_the_sheets_journal_nothing_pretends_to_have_an_arm()
    test_halves_split_by_decision_time()
    print("\nвсе 4 проверки прошли")
