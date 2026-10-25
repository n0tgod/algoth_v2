"""Ветви правил (спека 18): сестры в реестре, карты по наследству,
подпись кэша без сестёр, дерево и адрес, перенос записи 2 %."""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools"))
import rules as R                                             # noqa: E402
import run_short as S                                         # noqa: E402
import run_pair as PR                                         # noqa: E402
import branch_inherit as BI                                   # noqa: E402

H = 3600.0
T0 = float(R.RULES_SINCE or 0) + 3 * 86400.0
# день ветви 2 % (15.10) + час: решения ветви раньше её дня — пересчёт
T15 = R.ruler_since_ts("safe_h_g2") + H


def test_sisters_in_registry_inherit_maps_and_differ_only_by_guard():
    for base in ("safe_h", "optimal_h", "aggr_h"):
        assert R.wave_guard_of(base) == 4.0 and R.RULERS[base]["branch"]["default"]
        for v, want in ((0.0, None), (2.0, 2.0), (6.0, 6.0)):
            k = R.branch_key(base, v)
            assert k in R.H24_ORDER and R.is_branch(k) and R.base_of(k) == base, k
            assert R.wave_guard_of(k) == want, (k, R.wave_guard_of(k))
            assert R.family_of(k) == "h24" and R.side_of(k) == "short" and R.mode_of(k) == R.mode_of(base)
            for m in (R.PEAKS, R.SHORT_SHARE, R.MIN_AGE_DAYS, R.FLOOR_FRAC_BY_BOOK):
                if base in m:
                    assert m[k] == m[base], (k, m.get(k), m[base])
            assert R.hold_of(k) == R.hold_of(base) and R.min_lev_of(k) == R.min_lev_of(base)
            # текст вкладки называет ветвь: порог либо «охраны нет»
            pl = R.RULERS[k]["plain"]
            assert (f"≥ {want:g} %" in pl) if want else ("Охраны рынком у этой ветви НЕТ" in pl), (k, pl[-200:])
    for pk in ("pair_safe", "pair_optimal", "pair_aggr"):
        lk, sk = R.parts_of(pk)
        for v in (0.0, 2.0, 6.0):
            k = R.branch_key(pk, v)
            assert k in R.PAIR_ORDER and R.parts_of(k) == [lk, R.branch_key(sk, v)], (k, R.parts_of(k))
            assert R.wave_guard_of(k) == (v or None), k
            assert R.family_of(k) == "pair" and R.side_of(k) == "both" and R.mode_of(k) == R.mode_of(pk)
            assert R.SHORT_SHARE[k] == R.SHORT_SHARE[pk] and R.MIN_AGE_DAYS[k] == R.MIN_AGE_DAYS[pk]
    # книги модели (спека 19 §12) — не сестры охраны: их число живёт реестром
    guard_h24 = [k for k in R.H24_ORDER if not R.is_ai(k) and not R.is_model(k) and R.lev_cap_of(k) is None]
    assert len(guard_h24) == 15 and len([k for k in R.PAIR_ORDER if not R.is_ai(k)]) == 12
    assert [k for k in R.order_of("sit") if not R.is_ai(k)] == ["safe", "optimal", "aggr"]
    # длинные книги ветвей охраны не несут (ветвь судьи — своя, ниже)
    for lk in ("safe", "optimal", "aggr"):
        assert "branch" not in R.RULERS[lk] and R.wave_guard_of(lk) is None
    print("ok  сестры 0/2/6 % у коротких и общих книг, карты по наследству, "
          "отличие одно — охрана; длинные без ветвей")


def test_birthdays_versions_and_tree():
    assert R.family_since("safe_h") == R.FAMILY_SINCE["h24"]
    assert R.family_since("safe_h_g2") == "2026-10-15", "ветвь 2 % наследует запись с 15.10"
    assert R.family_since("safe_h_g0") == "2026-10-16" and R.family_since("pair_aggr_g6") == "2026-10-16"
    assert R.family_rules("safe_h_g2") == R.FAMILY_RULES["h24"], "версия у ветви — семейная"
    row = {"rules": R.RULES, "book_rules": R.FAMILY_RULES["h24"], "ruler": "safe_h_g2"}
    assert R.is_current(row) and not R.is_current(dict(row, book_rules=5))
    t = R.tree()
    # корень книг модели (§12) — после судьи, когда реестр не пуст
    assert [m["mode"] for m in t] == ["safe", "optimal", "aggr", "ai"] + (["lab"] if R.MODEL_BOOKS else []), \
        "судья — отдельный корень последним из постоянных"
    guard_only = lambda xs: [x for x in xs if not R.is_ai(x["key"]) and R.lev_cap_of(x["key"]) is None]  # noqa: E731
    for m in [x for x in t if x["mode"] not in ("ai", "lab")]:
        sides = {s["side"]: s for s in m["sides"]}
        assert set(sides) == {"long", "short", "both"}
        lb = guard_only(sides["long"]["branches"])
        assert len(lb) == 1 and lb[0]["branch"] == []
        for side in ("short", "both"):
            br = guard_only(sides[side]["branches"])
            n = 5 if side == "short" else 4               # у шортов — ещё ветвь 4+2
            assert len(br) == n and sides[side]["default"] == br[0]["key"] and not R.is_branch(br[0]["key"])
            vals = sorted((x["branch"][0]["value"], x["branch"][0].get("inv", 0.0)) for x in br)
            want = [(0.0, 0.0), (2.0, 0.0), (4.0, 0.0), (6.0, 0.0)] + ([(4.0, 2.0)] if side == "short" else [])
            assert vals == sorted(want), vals
            assert sum(1 for x in br if x["branch"][0]["default"]) == 1
    a = R.address_of("pair_optimal_g6")
    assert a == {"key": "pair_optimal_g6", "root": "optimal", "mode": "optimal", "mode_en": "Depth", "side": "both",
                 "base": "pair_optimal", "branch": [{"rule": "guard", "value": 6.0, "default": False,
                                                     "title": "охрана 6 %", "title_en": "guard 6 %"}]}, a
    print("ok  дни рождения ветвей (2 % — с 15.10), версия семейная, дерево 3 × (1 + 5 + 4)")


def test_short_cache_signature_ignores_sisters_and_books_map_feeds_them():
    # подпись реплея ДЛИННЫХ книг — тоже без сестёр: сервер 16.10 18:10
    # ответил «правила реплея изменились» общему счёту, потому что 9
    # линеек в подписи стали 18 (сестры попали в `run_paper.RULERS`)
    import run_paper as RP
    long_sig = RP.cache_sig()["rulers"]
    assert len(long_sig) == 9 and long_sig == sorted(
        v for k, v in RP.RULERS.items() if R.family_of(k) != "pair" and not R.is_branch(k)), long_sig
    sig = S.cache_sig()
    assert sorted(sig["floor"]) == ["aggr_h", "optimal_h", "safe_h"], sig["floor"]
    assert sorted(sig["books"]) == ["optimal_s", "safe_s"]
    assert S.BOOKS["safe_h_g2"] == S.BOOKS["safe_h"] and S.BOOKS["aggr_h_g0"] == S.BOOKS["aggr_h"]
    # 15 ветвей охраны + ветвь судьи + книги модели (§12, число — реестром)
    assert len(S.BOOKS) == 16 + len(R.MODEL_BOOKS) + len(R.LEV_CAP_BRANCHES) and len(S.BASE_BOOKS) == 3
    assert S.BOOKS["optimal_h_ai"] == S.BOOKS["optimal_h"], "ветвь судьи кормится линейкой основной книги"
    assert S.BOOKS["optimal_h_g4i2"] == S.BOOKS["optimal_h"]
    S.floor_groups()                       # сестры с полом основной книги не ломают группы
    # общий счёт: сестра собирает длинную книгу и СВОЮ короткую сторону
    longs = {"safe": [{"sym": "AUSDT", "at": T0, "exit_ts": T0 + H, "pnl": 0.01, "lev": 2.0, "marks": []}]}
    shorts = {"safe_h": [{"sym": "BUSDT", "at": T0, "exit_ts": T0 + H, "pnl": 0.02, "lev": 2.0, "marks": []}],
              "safe_h_g2": [{"sym": "CUSDT", "at": T0, "exit_ts": T0 + H, "pnl": 0.03, "lev": 2.0, "marks": []}]}
    got = PR.pack(longs, shorts, keys=["pair_safe_g2"])["pair_safe_g2"]
    assert [(r["book"], r["sym"]) for r in got] == [("safe", "AUSDT"), ("safe_h_g2", "CUSDT")], got
    print("ok  подпись кэша коротких без сестёр; сестра кормится линейкой основной книги; "
          "общий счёт берёт свою короткую сторону")


def _row(ruler, at, book_rules, sym="AUSDT", written=None, book=None, sizing=None):
    r = {"dep": 1000, "ruler": ruler, "at": at, "exit_ts": at + H, "sym": sym,
         "side": "short", "usd": 1.0, "lev": 2.0, "margin": 25.0, "pnl_frac": 0.04,
         "exit": "тейк", "written_at": (at + H) if written is None else written,
         "rules": R.RULES, "book_rules": book_rules}
    if book:
        r["book"] = book
    if sizing:
        r["sizing"] = sizing
    return r


def test_inherit_copies_old_guard_rows_into_branch_two_and_is_idempotent():
    said = []
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "short.jsonl")
        import run_paper as RP
        old_ver = R.FAMILY_RULES["h24"] - 2                  # версия охраны 2 % — 5
        rows = [_row("safe_h", T15, old_ver),                            # вперёд: писана через час
                _row("safe_h", T15 + 2 * H, old_ver, sym="BUSDT", written=T15 + 40 * 86400),  # пересчёт
                _row("optimal_h", T15, old_ver, sym="CUSDT", sizing=R.SIZING_FIXED),
                _row("safe_h", T15 + 3 * H, old_ver + 1, sym="DUSDT"),  # не та версия
                _row("safe_h_g6", T15 + 4 * H, old_ver, sym="EUSDT")]   # не основная книга
        # подделка легла: пишем всем журналом (дедуп полный, версии разные)
        RP.append_journal(rows, path=path, log=said.append)
        got, _ = R.read_journal(path)
        got_f, _ = R.read_journal(R.fixed_twin(path))
        assert len(got) + len(got_f) == 5, (len(got), len(got_f))
        res = BI.inherit(path, "h24", old_ver, log=said.append)
        assert res["added"] == 3, res
        new, _ = R.read_journal(path)
        new_f, _ = R.read_journal(R.fixed_twin(path))
        g2 = [r for r in new + new_f if r["ruler"] in ("safe_h_g2", "optimal_h_g2")]
        assert len(g2) == 3 and all(r["book_rules"] == R.FAMILY_RULES["h24"] and R.is_current(r) for r in g2)
        assert {r["sym"] for r in g2} == {"AUSDT", "BUSDT", "CUSDT"}
        assert any(r["ruler"] == "optimal_h_g2" and R.sizing_of(r) == R.SIZING_FIXED for r in new_f), \
            "строка фиксированного билета ушла в журнал-близнец"
        fwd, back = R.split_rows([r for r in g2 if r["sym"] in ("AUSDT", "BUSDT")])
        assert len(fwd) == 1 and len(back) == 1, "written_at сохранён: вперёд остаётся вперёд"
        # исходные строки целы
        assert sum(1 for r in new + new_f if r["book_rules"] == old_ver) == 4
        again = BI.inherit(path, "h24", old_ver, log=said.append)
        assert again["added"] == 0, again
        # общий счёт: метка стороны `book` переводится на сестру
        ppath = os.path.join(d, "pair.jsonl")
        pold = R.FAMILY_RULES["pair"] - 2
        RP.append_journal([_row("pair_safe", T15, pold, book="safe_h"),
                           dict(_row("pair_safe", T15 + H, pold, sym="LUSDT", book="safe"), side="long")],
                          path=ppath, log=said.append)
        pres = BI.inherit(ppath, "pair", pold, log=said.append)
        assert pres["added"] == 2
        prow, _ = R.read_journal(ppath)
        mine = [r for r in prow if r["ruler"] == "pair_safe_g2"]
        assert sorted(r["book"] for r in mine) == ["safe", "safe_h_g2"], [r["book"] for r in mine]
    print("ok  перенос записи 2 %: копия под ключом сестры и текущей версией, written_at цел, "
          "фиксированный билет — в близнец, повтор ничего не добавляет, метка стороны переведена")


def test_inherit_runs_once_before_first_write_and_leaves_a_marker():
    import run_paper as RP
    said = []
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "short.jsonl")
        old_ver = R.BRANCH_INHERIT["h24"]["from_version"]
        RP.append_journal([_row("safe_h", T0, old_ver)], path=path, log=said.append)
        res = RP.inherit_branches(path, "h24", log=said.append)
        assert res and res["added"] == 1, res
        mk = RP.inherit_marker(path, 2.0)
        assert os.path.exists(mk) and not any(mk.endswith(x) for x in (".jsonl",))
        assert R.journal_parts(path) and all(not p.endswith(".done") for p in R.journal_parts(path))
        assert RP.inherit_branches(path, "h24", log=said.append) is None, "с отметкой — не повторяется"
        assert RP.inherit_branches(path, "sit", log=said.append) is None, "у длинных карты нет"
        rows, _ = R.read_journal(path)
        assert sorted(r["ruler"] for r in rows) == ["safe_h", "safe_h_g2"]
    print("ok  перенос из прогона: один раз, до первой записи сестры, с отметкой рядом с журналом")


def test_branch_forward_starts_on_its_own_day_not_inside_the_120h_window():
    """Ветвь пишет в первом прогоне всю историю: решение раньше её дня —
    пересчёт, даже если строка записана в пределах окна `AHEAD_H`.
    Книга без своего дня (основная) живёт прежним правилом бит в бит."""
    d17 = R.ruler_since_ts("safe_h_g4i2")
    assert d17 == 1792195200.0, d17                      # 2026-10-17 00:00 UTC
    def row(ruler, at, written):
        return {"ruler": ruler, "at": at, "written_at": written}
    early = row("safe_h_g4i2", d17 - 6 * H, d17 - 5 * H)  # писана «вовремя», но до дня ветви
    late = row("safe_h_g4i2", d17 + H, d17 + 2 * H)
    base = row("safe_h", d17 - 6 * H, d17 - 5 * H)
    assert R.ahead(early["at"], early["written_at"]) is True, "подделка: без границы она «вперёд»"
    fwd, back = R.split_rows([early, late, base])
    assert fwd == [late, base] and back == [early], (fwd, back)
    assert R.row_ahead(base) == R.ahead(base["at"], base["written_at"])
    assert R.ruler_since_ts("safe_h") is None and R.ruler_since_ts("safe_h_g0") == d17 - 86400.0
    print("ok  запись вперёд ветви — с её дня (4+2 — с 17.10), основная книга — прежним правилом")


def test_inverse_branch_four_plus_two_registry_text_and_end_to_end():
    """Ветвь «4+2» (владелец 16.10): у трёх коротких книг, прямая 4 %,
    обратная 2 %, запись вперёд с 17.10; основная книга обратной не
    несёт; сквозной проход через сводки: падение рынка на 3 % закрывает
    шорт ветви словом обратной охраны, основную книгу — нет; рост на 5 %
    закрывает обе прямой охраной."""
    import run_paper as RP
    import wave as WV
    import test_guard as TG
    import test_tail_screen as TT
    for base in ("safe_h", "optimal_h", "aggr_h"):
        k = R.branch_key(base, 4.0, 2.0)
        assert k == base + "_g4i2" and k in R.H24_ORDER and R.is_branch(k) and R.base_of(k) == base
        assert R.wave_guard_of(k) == 4.0 and R.inv_guard_of(k) == 2.0 and R.inv_guard_of(base) is None
        assert R.mode_of(k) == R.mode_of(base) and R.side_of(k) == "short" and R.family_of(k) == "h24"
        assert R.family_since(k) == "2026-10-17"
        for m in (R.PEAKS, R.SHORT_SHARE, R.MIN_AGE_DAYS, R.FLOOR_FRAC_BY_BOOK):
            if base in m:
                assert m[k] == m[base], k
        assert "УПАЛ на ≥ 2 %" in R.RULERS[k]["plain"] and "FALLEN by ≥ 2 %" in R.RULERS[k]["plain_en"]
        assert "УПАЛ" not in R.RULERS[base]["plain"]
        b = R.address_of(k)["branch"][0]
        assert b["title_en"] == "guard 4 % + inverse 2 %" and b["inv"] == 2.0 and not b["default"]
    for pk in R.PAIR_ORDER:
        assert R.inv_guard_of(pk) is None, "у общих книг ветви 4+2 нет"
    proxies = list(WV.PROXY[:6])
    start = TG.AT - H
    marks = [(TG.AT + i * H, 0.02) for i in range(5)]
    def run(bump, book):
        td = tempfile.mkdtemp()
        for p in proxies:
            TT._write_hours(td, p, start, 6, lambda i: {"mid_close": 100.0 if i < 2 else 100.0 * (1 + bump)})
        RP.reset_market()
        try:
            return RP.guard_shorts([TG._rec(marks)], book, log=lambda *a: None, mkt=RP.market(root=td))
        finally:
            RP.reset_market()
    out, st = run(-0.03, "safe_h_g4i2")
    assert out[0]["exit"] == R.INV_GUARD_EXIT and len(out[0]["marks"]) == 2, out[0]
    assert st["closed_by_inv"] == 1 and st["closed_by_market"] == 0 and st["inv_pct"] == 2.0, st
    out, st = run(-0.03, "safe_h")
    assert out[0]["exit"] == "срок" and "closed_by_inv" not in st, st
    for book in ("safe_h", "safe_h_g4i2"):
        out, st = run(0.05, book)
        assert out[0]["exit"] == R.GUARD_EXIT and st["closed_by_market"] == 1, (book, st)
        assert st.get("closed_by_inv", 0) == 0
    print("ok  ветвь 4+2 у трёх коротких книг: прямая 4 %, обратная 2 %, вперёд с 17.10; "
          "падение −3 % закрывает только ветвь, рост +5 % — обе")


def test_ai_branch_registry_inherits_base_and_is_paper_only_by_rule():
    assert R.AI_BRANCHES == {"optimal_ai": "optimal", "optimal_h_ai": "optimal_h", "pair_optimal_ai": "pair_optimal"}
    assert "optimal_ai" in R.order_of("sit") and "optimal_h_ai" in R.order_of("h24") and "pair_optimal_ai" in R.order_of("pair")
    assert R.parts_of("pair_optimal_ai") == ["optimal", "optimal_h"], "стороны — основные книги Depth"
    assert R.side_of("pair_optimal_ai") == "both" and R.SHORT_SHARE["pair_optimal_ai"] == R.SHORT_SHARE["pair_optimal"]
    assert R.PAIR_SHORT_GATE["pair_optimal_ai"] == R.PAIR_SHORT_GATE["pair_optimal"]
    for k, base in R.AI_BRANCHES.items():
        assert R.is_branch(k) and R.base_of(k) == base and R.mode_of(k) == "optimal"
        assert R.side_of(k) == R.side_of(base) and R.family_of(k) == R.family_of(base)
        assert R.family_since(k) == R.AI_SINCE == "2026-10-19"
        assert R.wave_guard_of(k) == R.wave_guard_of(base), "охрана основной книги — по наследству"
        assert R.hold_of(k) == R.hold_of(base) and R.FLOOR_FRAC_BY_BOOK.get(k) == R.FLOOR_FRAC_BY_BOOK.get(base)
        a = R.address_of(k)
        assert a["branch"][0]["rule"] == "ai" and a["branch"][0]["title_en"] == "entry + watcher"
        assert a["root"] == "ai" and a["mode"] == "optimal" and R.title_en(k) == "AI judge"
        assert R.RULERS[k]["title_en"] == "AI judge", "имя в своде — имя корня, не «Depth»"
        assert "AI judge branch" in R.RULERS[k]["plain_en"] and "Paper only" in R.RULERS[k]["plain_en"]
    t = {m["mode"]: {s["side"]: [b["key"] for b in s["branches"]] for s in m["sides"]} for m in R.tree()}
    assert t["ai"] == {"long": ["optimal_ai"], "short": ["optimal_h_ai"], "both": ["pair_optimal_ai"]}
    assert not any("_ai" in k for m in ("safe", "optimal", "aggr") for sd in t[m].values() for k in sd), "в корнях режимов судьи нет"
    print("ok  ветвь судьи: свой корень (Long, Short, Both), правила Depth по наследству, адрес и текст, день 19.10")


def test_lev_cap_sister_registry_and_records_come_from_capped_core():
    """Ветвь потолка плеча (владелец 25.10): `aggr_h_c10` в реестре как сестра
    Gated с правилом `lev_cap` 10, картами и охраной по наследству, своим днём
    26.10, только бумага; её записи — записи основной линейки, где плечо выше
    10× заменено пересчётом ядра из кэша потолка; досчёт идёт только по
    недостающим и открытым, кэш переживает прогон."""
    import json
    import lev_cap_branch as LC
    k = "aggr_h_c10"
    assert R.lev_cap_key("aggr_h", 10.0) == k and k in R.H24_ORDER and R.is_branch(k) and R.base_of(k) == "aggr_h"
    assert R.lev_cap_of(k) == 10.0 and R.lev_cap_of("aggr_h") is None and R.lev_cap_of("aggr_h_g2") is None
    assert R.mode_of(k) == "aggr" and R.side_of(k) == "short" and R.family_of(k) == "h24" and R.title_en(k) == "Gated"
    assert R.family_since(k) == "2026-10-26" and R.wave_guard_of(k) == 4.0 and R.inv_guard_of(k) is None
    assert R.min_lev_of(k) == R.min_lev_of("aggr_h") == 4.0 and R.hold_of(k) == 24
    for m in (R.PEAKS, R.SHORT_SHARE, R.MIN_AGE_DAYS, R.FLOOR_FRAC_BY_BOOK):
        assert m[k] == m["aggr_h"], k
    b = R.address_of(k)["branch"][0]
    assert b["rule"] == "lev_cap" and b["value"] == 10.0 and b["title_en"] == "leverage ≤ 10×" and not b["default"]
    assert "Только бумага" in R.RULERS[k]["plain"] and "Paper only" in R.RULERS[k]["plain_en"]
    t = {m["mode"]: {s["side"]: [x["key"] for x in s["branches"]] for s in m["sides"]} for m in R.tree()}
    assert k in t["aggr"]["short"] and k not in t["aggr"]["both"]
    assert S.BOOKS[k] == S.BOOKS["aggr_h"] == "optimal_s", "сестра кормится линейкой основной книги"
    assert k not in S.BASE_BOOKS and "lev_cap" not in json.dumps(S.cache_sig()), "подпись кэша коротких сестры не знает"
    assert LC.caps_in_use() == [10.0]
    # записи: 20× заменяется пересчётом, 5× остаётся, без пересчёта — как есть и считается
    rec = lambda sym, lev, at=T0, **kw: dict({"sym": sym, "at": at, "lev": lev, "state": "closed", "pnl": 0.1}, **kw)  # noqa: E731
    base = [rec("AAAUSDT", 20.0), rec("BBBUSDT", 5.0), rec("CCCUSDT", 15.0)]
    capped = {("optimal_s", "AAAUSDT", round(T0, 3)): rec("AAAUSDT", 10.0, pnl=-0.2)}
    out, st = LC.apply(base, capped, 10.0, "optimal_s")
    assert [r["lev"] for r in out] == [10.0, 5.0, 15.0] and out[0]["pnl"] == -0.2 and st == {"capped": 1, "missing": 1, "cap": 10.0}
    # досчёт: кэш пуст → считаются оба решения с плечом выше; второй вызов — ничего; открытое — снова
    td = tempfile.mkdtemp()
    path = os.path.join(td, "recs-cap10.jsonl")
    cache = {("optimal_s", "AAAUSDT", round(T0, 3)): rec("AAAUSDT", 20.0),
             ("optimal_s", "BBBUSDT", round(T0, 3)): rec("BBBUSDT", 5.0),
             ("optimal_s", "CCCUSDT", round(T0 + H, 3)): rec("CCCUSDT", 15.0, at=T0 + H, state="open")}
    legs_ = [{"sym": "AAAUSDT", "at": T0}, {"sym": "BBBUSDT", "at": T0}, {"sym": "CCCUSDT", "at": T0 + H}]
    calls = []

    def fake_replay(groups, cells, src=None, log=print, rulers=None, adds_of=None):
        calls.append(sorted(g["sym"] for g in groups))
        assert adds_of(groups[0], cells[0][0]) == {"adds": [], "lev_cap": 10.0} and rulers == ["optimal_s"]
        got = {}
        for g in groups:
            r = cache[("optimal_s", g["sym"], round(float(g["at"]), 3))]
            got[("optimal_s", g["sym"], round(float(g["at"]), 3))] = dict(r, lev=10.0, pnl=-0.3)
        return {cells[0][0]: got}, {}
    done = LC.ensure(cache, legs_, 10.0, log=lambda *a: None, path=path, replay=fake_replay)
    assert calls == [["AAAUSDT", "CCCUSDT"]] and len(done) == 2 and all(r["lev"] == 10.0 for r in done.values())
    assert os.path.exists(path) and LC.read(10.0, path=path, log=lambda *a: None).keys() == done.keys()
    done2 = LC.ensure(cache, legs_, 10.0, log=lambda *a: None, path=path, replay=fake_replay)
    assert calls[1:] == [["CCCUSDT"]], "закрытое не пересчитывается, открытое — да"
    assert len(done2) == 2
    # смена подписи (другой потолок) — чужой кэш не читается
    assert LC.read(12.0, path=path, log=lambda *a: None) == {}
    print("ok  ветвь потолка плеча: aggr_h_c10 в реестре (Gated, 10×, с 26.10, бумага), записи из кэша ядра, "
          "досчёт только нового и открытого")


if __name__ == "__main__":
    test_ai_branch_registry_inherits_base_and_is_paper_only_by_rule()
    for t in (test_sisters_in_registry_inherit_maps_and_differ_only_by_guard,
              test_birthdays_versions_and_tree,
              test_short_cache_signature_ignores_sisters_and_books_map_feeds_them,
              test_inherit_copies_old_guard_rows_into_branch_two_and_is_idempotent,
              test_inherit_runs_once_before_first_write_and_leaves_a_marker,
              test_branch_forward_starts_on_its_own_day_not_inside_the_120h_window,
              test_inverse_branch_four_plus_two_registry_text_and_end_to_end,
              test_lev_cap_sister_registry_and_records_come_from_capped_core):
        t()
    print("\nвсе 8 проверок прошли")
