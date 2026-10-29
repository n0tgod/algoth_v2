#!/usr/bin/env python3
"""Книги модели (спека 19 §12): мягкий порог, пределы, подпись, рождение с
нуля в следующий час, отставка по окну и простою, час входа книги ТВХ (не
раньше сводки часа, решение заморожено), фильтр в проходе судьи (правило,
held, нет поля — «открыть» словами), регистрация книги в правилах (корень
«AI lab», старт с нуля, только бумага). Подделки — литералы."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "dca_paper"))
import model_books as MB                                     # noqa: E402

H, DAY = 3600, 86400
NOW = 1792600000.0


def lesson(i, matched, mm, mr, p, fld="price_moves_to_decision.4h_pct", v=10.0):
    return {"id": f"L{i}", "text": f"t{i}", "do": "skip", "why": f"w{i}",
            "when": [{"field": fld, "op": ">=", "value": v + i}],
            "test": {"all": {"n": 145, "matched": matched, "mean_matched": mm, "mean_rest": mr, "p_random": p}}}


def test_soft_gate_quota_and_signature():
    st = {"proposed": [lesson(1, 17, -0.17, 0.04, 0.003), lesson(2, 9, -0.3, 0.04, 0.0),
                       lesson(3, 14, -0.35, 0.05, 0.005), lesson(4, 20, 0.05, 0.04, 0.0),
                       lesson(5, 12, -0.10, 0.03, 0.25), lesson(6, 15, -0.2, 0.04, 0.05)]}
    cs = MB.skip_candidates(st)
    fails = {c["source"]: c["fail"] for c in cs}
    assert fails["lessons:L1"] is None and fails["lessons:L3"] is None and fails["lessons:L6"] is None
    assert "< 10" in fails["lessons:L2"] and "не хуже остальных" in fails["lessons:L4"] and "0.25" in fails["lessons:L5"]
    reg = {"books": []}
    born, wait = MB.births(reg, cs, NOW)
    assert [b["source"] for b in born] == ["lessons:L1", "lessons:L3"], "по доле случайных, предел 2 за неделю"
    assert wait and "7 суток" in wait[0]["why"]
    assert born[0]["id"] == "m01" and born[1]["id"] == "m02" and born[0]["key"] == "optimal_h_m01"
    assert born[0]["born_at"] == (int(NOW // H) + 1) * H and born[0]["born_at"] > NOW, "старт со следующего часа"
    b2, _ = MB.births(reg, cs, NOW + 8 * DAY)
    assert [b["source"] for b in b2] == ["lessons:L6"], "подпись не рождается дважды; неделя прошла — место есть"
    # живых ≤ 10, книг ТВХ ≤ 3
    reg = {"books": [{"id": f"m{i:02d}", "kind": "skip", "status": "live", "decided_at": NOW - 30 * DAY, "sig": str(i)}
                     for i in range(1, 11)]}
    born, wait = MB.births(reg, cs, NOW)
    assert not born and "живых уже 10" in wait[0]["why"]
    ent = [{"kind": "entry", "rule": {"when": [{"field": "oi_1h", "op": "<=", "value": -0.02 - i / 100}], "W": 5},
            "why": "w", "text": None, "source": "p", "fail": None, "gate": {}, "p": 0.01, "n": 50} for i in range(3)]
    reg = {"books": [{"id": f"m{i:02d}", "kind": "entry", "status": "live", "decided_at": NOW - 30 * DAY, "sig": str(i)}
                     for i in range(1, 4)]}
    born, wait = MB.births(reg, ent, NOW)
    assert not born and "ТВХ уже 3" in wait[0]["why"]
    a = {"trig": 40, "rule_mean": 0.05, "book_mean": 0.03, "p_random_hour": 0.1}
    assert MB.soft_entry(a) is None and "не лучше" in MB.soft_entry(dict(a, rule_mean=0.02))
    assert "0.3" in MB.soft_entry(dict(a, p_random_hour=0.3)) and "< 10" in MB.soft_entry(dict(a, trig=9))
    print("ok  книги модели: мягкий порог словами, предел 2 в неделю, 10 живых, 3 ТВХ, подпись не повторяется, старт со следующего часа")


def test_retire_window_and_idle():
    born = NOW - 15 * DAY
    b = {"born_at": born}
    days = lambda f: {MB.day_str(NOW - i * DAY): (f(i), 3) for i in range(1, 15)}   # noqa: E731
    assert MB.retire_why(b, days(lambda i: 5.0), days(lambda i: 10.0), NOW).startswith("за 10 суток"), "ниже основной"
    assert MB.retire_why(b, days(lambda i: 12.0), days(lambda i: 10.0), NOW) is None
    assert MB.retire_why({"born_at": NOW - 5 * DAY}, days(lambda i: -50.0), days(lambda i: 10.0), NOW) is None, "моложе 10 суток"
    assert MB.retire_why({"born_at": NOW - 10.2 * DAY}, days(lambda i: -50.0), days(lambda i: 10.0), NOW) is None, \
        "окно — полные сутки ПОСЛЕ дня рождения"
    old = {MB.day_str(NOW - 40 * DAY): (1.0, 1)}
    assert "простой" in MB.retire_why({"born_at": NOW - 45 * DAY}, old, {}, NOW)
    assert "простой" in MB.retire_why({"born_at": NOW - 31 * DAY}, {}, {}, NOW), "ни одной позиции с рождения"
    reg = {"books": [{"id": "m01", "key": "optimal_h_m01", "status": "live", "born_at": born}]}
    gone = MB.retire(reg, lambda k: days(lambda i: 1.0) if k == "optimal_h_m01" else days(lambda i: 9.0), NOW)
    assert gone and reg["books"][0]["status"] == "retired" and reg["books"][0]["retired_at"] == NOW
    print("ok  отставка: ниже основной за 10 полных суток после рождения, простой 30 суток; моложе — не судится")


def test_entry_hour_first_match_frozen_and_dedup():
    born = NOW - 10 * H
    b = {"id": "m03", "kind": "entry", "born_at": born, "status": "live",
         "rule": {"when": [{"field": "oi_1h", "op": "<=", "value": -0.02}], "W": 3}}
    legs = [{"sym": "AUSDT", "at": born + H}, {"sym": "BUSDT", "at": born + H}, {"sym": "CUSDT", "at": NOW - H},
            {"sym": "DUSDT", "at": born - H}, {"sym": "AUSDT", "at": born + 2 * H}]
    oi = {("AUSDT", born + H): [0.0, -0.01, -0.03, -0.05], ("BUSDT", born + H): [0.0, 0.0, 0.0, 0.0],
          ("CUSDT", NOW - H): [0.0, -0.05, 0, 0], ("AUSDT", born + 2 * H): [0.0, -0.04, 0, 0]}
    calls = []

    def feat(g, k):
        calls.append((g["sym"], k))
        return {"oi_1h": oi[(g["sym"], g["at"])][k]}
    state = {}
    n = MB.entry_decide(b, legs, feat, state, NOW)
    m = state["m03"]
    assert m[f"AUSDT|{int(born + H)}"]["k"] == 2 and m[f"BUSDT|{int(born + H)}"]["k"] == -1, "первый час по условию; не наступило"
    assert f"CUSDT|{int(NOW - H)}" not in m, "час 1 ещё не лёг (сводка — 5 мин) — решение ждёт"
    assert f"DUSDT|{int(born - H)}" not in m and n == 3, "сигнал до рождения не берётся"
    calls.clear()
    oi[("AUSDT", born + H)] = [-0.9] * 4                          # данные «поменялись» — решение не пересматривается
    MB.entry_decide(b, legs, feat, state, NOW + 60)
    assert m[f"AUSDT|{int(born + H)}"]["k"] == 2 and not any(c[0] == "AUSDT" and c[1] == 0 for c in calls)
    sh = MB.shifted_legs(b, legs, state)
    ats = sorted((g["sym"], g["at"]) for g in sh)
    assert ats == [("AUSDT", born + 3 * H)], ats                  # второй сигнал A (k=1) — тот же час: один вход
    assert sh[0]["at_signal"] == born + H
    print("ok  книга ТВХ: первый час по условию, ждёт сводку часа, решение заморожено, один вход на имя и час")


def test_skip_pass_in_judge_and_rules_registration():
    import gate_run as G                                       # noqa: E402
    import rules as R                                          # noqa: E402
    import model_branch as MBR                                 # noqa: E402
    born = NOW - 3 * H
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "model_books.json")
        rule = {"when": [{"field": "price_moves_to_decision.4h_pct", "op": ">=", "value": 10.0}]}
        json.dump({"books": [{"id": "m91", "key": "optimal_h_m91", "kind": "skip", "rule": rule, "status": "live",
                              "born_at": born, "why": "pump still running", "sig": "s"}]}, open(path, "w"))
        recs = [{"sym": "PUMPUSDT", "at": born + H, "lev": 5, "exit_ts": born + 20 * H, "fwd": 50},
                {"sym": "CALMUSDT", "at": born + H, "lev": 5, "exit_ts": born + 20 * H, "fwd": 40},
                {"sym": "CALMUSDT", "at": born + 2 * H, "lev": 5, "exit_ts": born + 21 * H, "fwd": 40},
                {"sym": "NOFLDUSDT", "at": born + H, "lev": 5, "exit_ts": born + 20 * H, "fwd": 30},
                {"sym": "EARLYUSDT", "at": born - H, "lev": 5, "exit_ts": born + 20 * H, "fwd": 30}]
        dos = {G.key_of("optimal_h", recs[0]): {"price_moves_to_decision": {"4h_pct": 14.0}},
               G.key_of("optimal_h", recs[1]): {"price_moves_to_decision": {"4h_pct": 2.0}},
               G.key_of("optimal_h", recs[3]): {"price_moves_to_decision": {}}}
        out, full, dec_by = [], [], {}
        n = G.model_pass(recs, dec_by, dict(dos), NOW, out, full, lambda r: (_ for _ in ()).throw(AssertionError("build")),
                         log=lambda *a: None, registry=path)
        by = {(r["sym"], r["at"]): r for r in out}
        assert by[("PUMPUSDT", born + H)]["decision"] == "skip" and by[("CALMUSDT", born + H)]["decision"] == "open"
        assert by[("CALMUSDT", born + 2 * H)]["decision"] == "held", "повтор по держимому имени — held"
        nf = by[("NOFLDUSDT", born + H)]
        assert nf["decision"] == "open" and "нет поля" in nf["no_verdict"], "нет поля — открыть со словами"
        assert ("EARLYUSDT", born - H) not in by and n == 4 and all(r["branch"] == "m91" and r["cost_usd"] == 0 for r in out)
        n2 = G.model_pass(recs, dec_by, dos, NOW + 60, out, full, None, log=lambda *a: None, registry=path)
        assert n2 == 0, "второй проход не решает тех же"
        # регистрация книги: корень AI lab, старт с нуля, суффикс снимается
        R._register_model_books(path)
        k = "optimal_h_m91"                                    # номер вне живого реестра
        assert R.is_model(k) and k in R.H24_ORDER and R.root_of(k) == "lab" and R.side_of(k) == "short"
        assert R.mode_of(k) == "optimal" and R.title_en(k) == "AI lab" and R.base_of(k) == "optimal_h"
        assert any(t["mode"] == "lab" and t["mode_en"] == "AI lab" and any(
            k in [x["key"] for x in sd["branches"]] for sd in t["sides"]) for t in R.tree())
        row = {"rules": R.RULES, "book_rules": R.FAMILY_RULES.get("h24"), "ruler": k, "at": born - 1}
        assert not R.is_current(row) and R.is_current(dict(row, at=born + 1)), "старт с нуля в час рождения"
        assert "pump still running" in R.RULERS[k]["plain"]
        # книга-фильтр над записями: правило убирает свой skip, до рождения — пусто
        rows = [dict(r, kind="entry") for r in out]
        kept, st = MBR.apply_skip([dict(r) for r in recs], k, log=lambda *a: None, rows=rows)
        assert sorted(r["sym"] for r in kept) == ["CALMUSDT", "CALMUSDT", "NOFLDUSDT"] and st["cut"] == 1
    print("ok  фильтр модели: решает правило в проходе судьи (skip/open/held, нет поля — словами), книга в корне AI lab с нуля")


def test_exit_cell_in_signature_candidates_and_words():
    """Выход книги модели (§11.9): подпись без выхода — прежняя (m01/m02 не
    меняются), с выходом — другая; кандидат несёт выход; слова — стоп и тейк."""
    import rules as R                                          # noqa: E402
    rule = {"when": [{"field": "oi_1h", "op": "<=", "value": -0.02}], "W": 5}
    old = json.dumps({"kind": "entry", "W": 5, "when": [["oi_1h", "<=", -0.02]]}, sort_keys=True, ensure_ascii=False)
    assert MB.sig("entry", rule) == old and MB.sig("entry", dict(rule, exit="s0:t2:book")) == old
    assert MB.sig("entry", dict(rule, exit="s2:t1:eq")) != old
    search = {"model": [{"rule": dict(rule, exit="s2:t1:eq"), "halves": [],
                         "all": {"trig": 50, "rule_mean": 0.04, "book_mean": 0.01, "p_random_hour": 0.05}}]}
    rf = {"rules": [dict(rule, exit="s2:t1:eq", why="unwind then short with a tight stop", proposed_at="x")]}
    c = MB.entry_candidates(search, rf)[0]
    assert c["rule"]["exit"] == "s2:t1:eq" and c["fail"] is None and c["why"].startswith("unwind"), c
    assert "стоп 2 %" in MB.rule_text("entry", c["rule"]) and "равный риск" in MB.rule_text("entry", c["rule"])
    assert "стоп 2 %" in R.model_rule_text({"kind": "entry", "rule": c["rule"]})
    assert "стоп" not in R.model_rule_text({"kind": "entry", "rule": rule})
    print("ok  выход книги модели: подпись прежних книг не меняется, с выходом — своя; слова стопа и тейка")


def test_entry_book_carries_exit_rules_judged_at_entry_hour():
    """Свой выход у книги ТВХ (§11.10, владелец 29.10): кандидаты правил выхода
    с мягким порогом; книга ТВХ рождается с прошедшими правилами (≤ 3), отдельной
    книги выхода нет; в час входа первое выполненное правило даёт ячейку,
    иначе выход книги; решение заморожено с числами полей; сдвинутый вход несёт
    ячейку; `--attach-exits` подключает правила живым книгам с часа подключения."""
    import rules as R                                          # noqa: E402
    rule = {"when": [{"field": "crowd_bybit", "op": "<=", "value": 0.4}], "exit": "s3:t2:book"}
    search = {"computed_at": "x", "exit_model": [
        {"rule": rule, "matched": 40, "mean_cell": 0.05, "mean_book": 0.01, "gain": 0.004, "p_random": 0.0, "halves": []},
        {"rule": dict(rule, exit="s1:t2:book"), "matched": 5, "mean_cell": 0.05, "mean_book": 0.01, "gain": 0.0, "p_random": 0.0},
        {"rule": dict(rule, exit="s2:t1:eq"), "matched": 40, "mean_cell": 0.00, "mean_book": 0.01, "gain": -0.001, "p_random": 0.9},
        {"rule": {"when": [{"field": "spread_bp", "op": ">=", "value": 9}], "exit": "s8:t3:book"}, "matched": 900,
         "mean_cell": 0.02, "mean_book": 0.018, "gain": 0.001, "p_random": 0.0, "halves": []}]}
    rf = {"exit_rules": [dict(rule, why="adverse excursion is small when the crowd is short", proposed_at="p")]}
    cs = MB.exit_candidates(search, rf)
    assert [c["fail"] for c in cs] == [None, "подходящих 5 < 10", "в ячейке не лучше, чем с выходом книги", None]
    xr = MB.exit_rules_for_birth(cs)
    assert [r["exit"] for r in xr] == ["s3:t2:book", "s8:t3:book"] and xr[0]["why"].startswith("adverse"), xr   # p равны → по приросту
    assert MB.rule_text("exit", xr[0]) == "crowd_bybit <= 0.4 → стоп 3 %, тейк обещание ×2, плечо книги"
    # рождение: книга ТВХ несёт правила выхода, отдельная книга выхода не рождается
    ent = {"kind": "entry", "rule": {"when": [{"field": "oi_1h", "op": "<=", "value": -0.02}], "W": 4}, "why": "w",
           "text": None, "source": "s", "fail": None, "gate": {}, "p": 0.0, "n": 50}
    reg = {"books": []}
    born, wait = MB.births(reg, [ent] + cs, NOW)
    assert len(born) == 1 and born[0]["kind"] == "entry" and born[0]["exit_rules"] == xr and born[0]["exit_since"] == born[0]["born_at"]
    assert not wait and all(b["kind"] != "exit" for b in reg["books"])
    # выход в час входа: первое выполненное правило; до exit_since — выход книги
    b = dict(born[0], id="m05", born_at=NOW - 10 * H, exit_since=NOW - 5 * H)
    assert MB.exit_for(b, {"crowd_bybit": 0.3, "spread_bp": 12}, NOW - H)[0] == "s3:t2:book", "первое правило по порядку"
    ex, i, vals = MB.exit_for(b, {"crowd_bybit": 0.9, "spread_bp": 12}, NOW - H)
    assert ex == "s8:t3:book" and i == 1 and vals == {"crowd_bybit": 0.9, "spread_bp": 12}
    assert MB.exit_for(b, {"crowd_bybit": 0.9, "spread_bp": 2}, NOW - H) == (MB.BOOK_EXIT, None, {"crowd_bybit": 0.9, "spread_bp": 2})
    assert MB.exit_for(b, {"crowd_bybit": 0.3, "spread_bp": 12}, NOW - 8 * H)[0] == MB.BOOK_EXIT, "до часа подключения — выход книги"
    assert MB.exit_for(dict(b, exit_rules=[], rule=dict(b["rule"], exit="s2:t1:eq")), {}, NOW)[0] == "s2:t1:eq"
    # решение книги: час входа и ячейка выхода вместе, заморожены
    legs = [{"sym": "AUSDT", "at": NOW - 4 * H}, {"sym": "BUSDT", "at": NOW - 4 * H}]
    feats = {("AUSDT", 0): {"oi_1h": 0.0, "crowd_bybit": 0.9, "spread_bp": 2}, ("AUSDT", 1): {"oi_1h": -0.03, "crowd_bybit": 0.3, "spread_bp": 2},
             ("BUSDT", 0): {"oi_1h": -0.05, "crowd_bybit": 0.9, "spread_bp": 2}, ("BUSDT", 1): {"oi_1h": -0.05, "crowd_bybit": 0.3, "spread_bp": 2}}
    state = {}
    MB.entry_decide(b, legs, lambda g, k: feats[(g["sym"], k)], state, NOW)
    m = state["m05"]
    a_, b_ = m[f"AUSDT|{int(NOW - 4 * H)}"], m[f"BUSDT|{int(NOW - 4 * H)}"]
    assert a_["k"] == 1 and a_["exit"] == "s3:t2:book" and a_["exit_rule"] == 0 and a_["exit_vals"]["crowd_bybit"] == 0.3
    assert b_["k"] == 0 and b_["exit"] == MB.BOOK_EXIT and b_["exit_rule"] is None, "в час входа ни одно правило выхода не держит"
    sh = {g["sym"]: g for g in MB.shifted_legs(b, legs, state)}
    assert sh["AUSDT"]["exit"] == "s3:t2:book" and sh["AUSDT"]["at"] == NOW - 3 * H and sh["BUSDT"]["exit"] == MB.BOOK_EXIT
    # подключение живым книгам: только ТВХ без правил, с ближайшего часа; прежние решения не трогаются
    import entry_search as ES                                  # noqa: E402
    with tempfile.TemporaryDirectory() as d:
        reg_p = os.path.join(d, "model_books.json")
        old = dict(b, exit_rules=None, exit_since=None, sig="z", key="optimal_h_m05")
        skip = {"id": "m06", "key": "optimal_h_m06", "kind": "skip", "status": "live", "rule": {"when": []}, "born_at": NOW, "sig": "q"}
        json.dump({"books": [old, skip]}, open(reg_p, "w"))
        json.dump(search, open(os.path.join(d, "s.json"), "w")); json.dump(rf, open(os.path.join(d, "r.json"), "w"))
        was = (MB.REGISTRY, ES.LATEST, ES.RULES_FILE)
        try:
            MB.REGISTRY, ES.LATEST, ES.RULES_FILE = reg_p, os.path.join(d, "s.json"), os.path.join(d, "r.json")
            r = MB.attach_exits(log=lambda *a: None, now=NOW)
            got = json.load(open(reg_p))["books"]
        finally:
            MB.REGISTRY, ES.LATEST, ES.RULES_FILE = was
        assert r["attached"] == ["m05"] and got[0]["exit_rules"] == xr and got[0]["exit_since"] == float((int(NOW // H) + 1) * H)
        assert "exit_rules" not in got[1] and got[0]["born_at"] == b["born_at"]
        r2 = MB.attach_exits(log=lambda *a: None, now=NOW + H)
        assert r2["attached"] == [], "повторно без --force не трогает"
        MB.REGISTRY, ES.LATEST, ES.RULES_FILE = reg_p, os.path.join(d, "s.json"), os.path.join(d, "r.json")
        try:
            r3 = MB.attach_exits(log=lambda *a: None, now=NOW + H, force=True)
            got = json.load(open(reg_p))["books"]
        finally:
            MB.REGISTRY, ES.LATEST, ES.RULES_FILE = was
        assert r3["attached"] == ["m05"] and got[0]["exit_history"][0]["rules"] == xr and got[0]["exit_since"] == float((int((NOW + H) // H) + 1) * H)
        R._register_model_books(reg_p)
        k = "optimal_h_m05"
        assert R.RULERS[k]["branch"]["title_en"] == "m05 · own entry rule + exit"
        t = R.model_rule_text(R.MODEL_BOOKS[k])
        assert t.startswith("oi_1h <= -0.02, окно 4 ч; выход по состоянию часа входа: crowd_bybit <= 0.4 → стоп 3 %, тейк ×2; "
                            "spread_bp >= 9 → стоп 8 %, тейк ×3; иначе выход книги"), t
    print("ok  свой выход у книги ТВХ: правила выхода при рождении (≤ 3, по порогу), в час входа первое выполненное, "
          "решение заморожено, вход несёт ячейку; подключение живым — с часа подключения")


def test_entry_book_closes_early_on_state_change():
    """Ранний выход (§11.11): кандидаты правил закрытия с мягким порогом; книга ТВХ
    рождается с ними (≤ 3); в прожитом часе первое выполненное правило решает
    «закрыть», решение заморожено с числами; позиция режется на отметке часа после
    решения словом «смена» тем же ядром, что сторож; уже вышедшая не трогается;
    подключение живым — с ближайшего часа."""
    import rules as R                                          # noqa: E402
    rule = {"when": [{"field": "crowd_bybit", "op": ">=", "value": 0.6}], "H": 12}
    cs_ = {"computed_at": "x", "close_model": [
        {"rule": rule, "matched": 40, "mean_close": 0.02, "mean_hold": -0.03, "gain": 0.004, "p_random_hour": 0.0, "halves": []},
        {"rule": dict(rule, H=3), "matched": 4, "mean_close": 0.02, "mean_hold": -0.03, "gain": 0.0, "p_random_hour": 0.0},
        {"rule": {"when": [{"field": "btc_1h", "op": ">=", "value": 0.01}], "H": 23}, "matched": 60, "mean_close": -0.01,
         "mean_hold": 0.0, "gain": -0.001, "p_random_hour": 0.5}]}
    rf = {"close_rules": [dict(rule, why="the crowd flipped long: the squeeze is on", proposed_at="p")]}
    cc = MB.close_candidates(cs_, rf)
    assert [c["fail"] for c in cc] == [None, "подходящих 4 < 10", "закрыть не лучше, чем держать"], [c["fail"] for c in cc]
    cr = MB.close_rules_for_birth(cc)
    assert len(cr) == 1 and cr[0]["H"] == 12 and cr[0]["why"].startswith("the crowd") and MB.close_rule_text(cr[0]) == "crowd_bybit >= 0.6, до 12 ч"
    ent = {"kind": "entry", "rule": {"when": [{"field": "oi_1h", "op": "<=", "value": -0.02}], "W": 4}, "why": "w",
           "text": None, "source": "s", "fail": None, "gate": {}, "p": 0.0, "n": 50}
    reg = {"books": []}
    born, _w = MB.births(reg, [ent] + cc, NOW)
    assert born[0]["close_rules"] == cr and born[0]["close_since"] == born[0]["born_at"] and all(b["kind"] == "entry" for b in reg["books"])
    # решения по прожитым часам: вход в NOW−5ч, толпа развернулась на 3-м часе; сводка 5-го часа ещё не легла
    b = dict(born[0], id="m07", born_at=NOW - 10 * H, close_since=NOW - 10 * H)
    at = NOW - 5 * H + 60                                        # пятый час ещё не прожит целиком (EDGE_S)
    legs = [{"sym": "AUSDT", "at": at, "at_signal": at, "exit": MB.BOOK_EXIT},
            {"sym": "OLDUSDT", "at": NOW - 8 * H, "at_signal": NOW - 8 * H, "exit": MB.BOOK_EXIT}]
    crowd = {("AUSDT", 1): 0.4, ("AUSDT", 2): 0.5, ("AUSDT", 3): 0.7, ("AUSDT", 4): 0.9}
    calls = []

    def feat(g, h):
        calls.append((g["sym"], h))
        return {"crowd_bybit": crowd.get((g["sym"], h), 0.1)}
    state = {}
    b["close_since"] = NOW - 10 * H
    n = MB.close_decide(b, [legs[0]], feat, state, NOW)
    d = state["closes"]["m07"][f"AUSDT|{int(at)}"]
    assert n == 1 and d["close"]["h"] == 3 and d["close"]["rule"] == 0 and d["close"]["vals"] == {"crowd_bybit": 0.7} and d["h_done"] == 3
    assert [h for s_, h in calls] == [1, 2, 3], calls                 # после решения часы не судятся
    crowd[("AUSDT", 3)] = 0.1
    assert MB.close_decide(b, [legs[0]], feat, state, NOW + H) == 0 and d["close"]["h"] == 3, "решение заморожено"
    # вход до close_since не судится; у входа без срабатывания растёт h_done
    b2 = dict(b, close_since=NOW - 4 * H)
    assert MB.close_decide(b2, [legs[0]], feat, {}, NOW) == 0
    st2 = {}
    assert MB.close_decide(b, [legs[1]], feat, st2, NOW) == 0 and st2["closes"]["m07"][f"OLDUSDT|{int(NOW - 8 * H)}"]["h_done"] == 7
    # применение: закрыть на отметке часа после решения словом «смена»; вышедшая раньше — как есть
    rec = {"sym": "AUSDT", "at": at, "marks": [[at + (k - 1) * H, 0.01] for k in range(1, 13)], "state": "open", "pnl": 0.12,
           "pnl_net": 0.11, "exit": "срок", "exit_ts": at + 24 * H, "side": "short", "lev": 2.0, "fills": []}
    early = dict(rec, sym="AUSDT", at=at, marks=rec["marks"][:2], state="closed", exit="пол", exit_ts=at + 2 * H - 1)
    st_apply = {"closes": {"m07": {f"AUSDT|{int(at)}": d}}}
    out, n_cl = MB.apply_closes([rec], b, st_apply, R.RULE_EXIT)
    assert n_cl == 1 and out[0]["exit"] == "смена" and out[0]["state"] == "closed" and len(out[0]["marks"]) == 4, out[0]
    assert abs(out[0]["pnl"] - 0.04) < 1e-9 and abs(out[0]["pnl_net"] - 0.03) < 1e-9
    out2, n2 = MB.apply_closes([early], b, st_apply, R.RULE_EXIT)
    assert n2 == 0 and out2[0]["exit"] == "пол", "вышедшая раньше решения не трогается"
    import costs as CO                                         # noqa: E402
    assert R.RULE_EXIT in CO.MARKET_EXITS, "рыночный выход — издержки как у охраны"
    # подключение живым
    import close_search as CS                                  # noqa: E402
    import entry_search as ES                                  # noqa: E402
    with tempfile.TemporaryDirectory() as dd:
        reg_p = os.path.join(dd, "model_books.json")
        json.dump({"books": [dict(b, close_rules=None, close_since=None, sig="z", key="optimal_h_m07")]}, open(reg_p, "w"))
        json.dump(cs_, open(os.path.join(dd, "c.json"), "w")); json.dump(rf, open(os.path.join(dd, "r.json"), "w"))
        was = (MB.REGISTRY, CS.LATEST, ES.RULES_FILE)
        try:
            MB.REGISTRY, CS.LATEST, ES.RULES_FILE = reg_p, os.path.join(dd, "c.json"), os.path.join(dd, "r.json")
            r = MB.attach_closes(log=lambda *a: None, now=NOW)
            got = json.load(open(reg_p))["books"]
        finally:
            MB.REGISTRY, CS.LATEST, ES.RULES_FILE = was
        assert r["attached"] == ["m07"] and got[0]["close_rules"] == cr and got[0]["close_since"] == float((int(NOW // H) + 1) * H)
        R._register_model_books(reg_p)
        k = "optimal_h_m07"
        assert R.RULERS[k]["branch"]["title_en"].endswith("+ early close") and "ранний выход по смене состояния: crowd_bybit >= 0.6 (до 12 ч)" in R.model_rule_text(R.MODEL_BOOKS[k])
    print("ok  ранний выход книги ТВХ: кандидаты и порог, при рождении, решение по прожитому часу заморожено, "
          "закрытие словом «смена» на отметке часа после решения, подключение живым")


def main():
    n = 0
    for f in (test_entry_book_closes_early_on_state_change, test_entry_book_carries_exit_rules_judged_at_entry_hour, test_exit_cell_in_signature_candidates_and_words, test_soft_gate_quota_and_signature, test_retire_window_and_idle,
              test_entry_hour_first_match_frozen_and_dedup, test_skip_pass_in_judge_and_rules_registration):
        f()
        n += 1
    print(f"\nвсе {n} проверки прошли")


if __name__ == "__main__":
    main()
