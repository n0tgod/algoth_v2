#!/usr/bin/env python3
"""Проверки разреза DCA-книг по руке модели.

Кусаются: спор двух рук за одно имя разрешает КЭШ РЕПЛЕЯ, а без него
строка остаётся без руки (догадкой не приписывается); строка без ноги не
зачисляется ни одной руке; деньги рук в сумме с «нет руки» дают книгу;
строки чужой версии правил в счёт не идут.
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


def test_dispute_is_resolved_by_the_cache_or_stays_without_an_arm():
    # одна рука
    import run_paper as RP                                    # noqa: E402
    legs = [_leg("AAAUSDT", "nn", T0, -300.0),
            _leg("BBBUSDT", "gbm", T0 + H, 120.0),
            _leg("BBBUSDT", "nn", T0 + H, 400.0)]
    rows = [_row("AAAUSDT", T0, +5.0), _row("BBBUSDT", T0 + H, -2.0)]
    # без кэша спор НЕ приписывается ни одной руке
    s0 = A.run(rows=rows, legs=legs, owners={}, log=lambda *a: None)
    c0 = s0["cells"]["optimal:10000"]
    assert c0["arms"]["nn"]["n"] == 1 and c0["arms"]["gbm"]["n"] == 0
    assert c0["arms"]["нет руки"]["usd"] == -2.0, c0["arms"]["нет руки"]
    assert s0["attribution"]["tie"] == 1 and s0["attribution"]["by_cache"] == 0
    # кэш говорит, что спорную запись держат ДЕРЕВЬЯ — и разрез слушает его
    pr = tuple(RP.RULERS["optimal"])
    own = {(pr, "BBBUSDT", round(T0 + H, 3)): "gbm"}
    s1 = A.run(rows=rows, legs=legs, owners=own, log=lambda *a: None)
    c1 = s1["cells"]["optimal:10000"]
    assert c1["arms"]["gbm"]["usd"] == -2.0 and s1["attribution"]["by_cache"] == 1
    # тот же кэш с другой рукой — деньги переезжают, значит кэш читается
    own2 = {(pr, "BBBUSDT", round(T0 + H, 3)): "nn"}
    s2 = A.run(rows=rows, legs=legs, owners=own2, log=lambda *a: None)
    assert s2["cells"]["optimal:10000"]["arms"]["nn"]["usd"] == 3.0
    # сторона входит в ключ: короткая нога не отвечает за длинную строку
    idx2 = A.legs_index([_leg("CCCUSDT", "nn", T0, -300.0, side="short")])
    assert A.key_of("CCCUSDT", "long", T0) not in idx2
    print("ok  спор разрешает кэш реплея: без кэша строка без руки, с кэшем "
          "деньги едут ровно к названной руке; сторона входит в ключ")


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
    import run_paper as RP                                    # noqa: E402
    pr = tuple(RP.RULERS["optimal"])
    own = {(pr, "BBBUSDT", round(T0 + H, 3)): "nn"}
    s = A.run(rows=rows, legs=legs, owners=own, log=lambda *a: None)
    assert s["rows"] == 4 and s["rows_all"] == 5, (s["rows"], s["rows_all"])
    a = s["attribution"]
    assert (a["one"], a["both"], a["tie"], a["no_leg"]) == (1, 1, 1, 1), a
    assert a["by_cache"] == 1, a
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
    assert "| обе руки, спор разрешён кэшем реплея | 1 |" in txt
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


def test_report_names_the_backtest_and_the_daily_activity():
    legs = [_leg("AAAUSDT", "gbm", T0, 300.0),
            _leg("BBBUSDT", "nn", T0 + 26 * H, 300.0)]
    rows = [_row("AAAUSDT", T0, +4.0), _row("BBBUSDT", T0 + 26 * H, -6.0)]
    s = A.run(rows=rows, legs=legs, log=lambda *a: None)
    # обе строки писаны через 4 ч после решения, но правила v6 моложе их
    assert s["forward"] == 0 and s["back"] == 2, (s["forward"], s["back"])
    assert len(s["days"]) == 2, s["days"]
    d = s["days"][sorted(s["days"])[0]]
    assert (d["gbm"], d["nn"], d["rows"]) == (1, 0, 1), d
    txt = A.report(s)
    assert "вперёд записано всего 0 строк" in txt and "БЭКТЕСТ" in txt
    assert "## Активность по суткам" in txt
    assert sorted(s["days"])[1] in txt
    print(f"ok  отчёт называет пересчёт ({s['back']} строк) и раскладывает "
          f"активность по {len(s['days'])} суткам")


if __name__ == "__main__":
    test_dispute_is_resolved_by_the_cache_or_stays_without_an_arm()
    test_money_of_arms_sums_to_the_book_and_orphans_are_named()
    test_without_the_sheets_journal_nothing_pretends_to_have_an_arm()
    test_halves_split_by_decision_time()
    test_report_names_the_backtest_and_the_daily_activity()
    print("\nвсе 5 проверок прошли")
