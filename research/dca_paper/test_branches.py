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
    assert len(R.H24_ORDER) == 12 and len(R.PAIR_ORDER) == 12 and len(R.order_of("sit")) == 3
    # длинные книги ветви не несут
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
    assert [m["mode"] for m in t] == ["safe", "optimal", "aggr"]
    for m in t:
        sides = {s["side"]: s for s in m["sides"]}
        assert set(sides) == {"long", "short", "both"}
        assert len(sides["long"]["branches"]) == 1 and sides["long"]["branches"][0]["branch"] == []
        for side in ("short", "both"):
            br = sides[side]["branches"]
            assert len(br) == 4 and sides[side]["default"] == br[0]["key"] and not R.is_branch(br[0]["key"])
            vals = sorted(x["branch"][0]["value"] for x in br)
            assert vals == [0.0, 2.0, 4.0, 6.0], vals
            assert sum(1 for x in br if x["branch"][0]["default"]) == 1
    a = R.address_of("pair_optimal_g6")
    assert a == {"key": "pair_optimal_g6", "mode": "optimal", "mode_en": "Depth", "side": "both",
                 "base": "pair_optimal", "branch": [{"rule": "guard", "value": 6.0, "default": False,
                                                     "title": "охрана 6 %", "title_en": "guard 6 %"}]}, a
    print("ok  дни рождения ветвей (2 % — с 15.10), версия семейная, дерево 3 × (1 + 4 + 4)")


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
    assert len(S.BOOKS) == 12 and len(S.BASE_BOOKS) == 3
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
        rows = [_row("safe_h", T0, old_ver),                            # вперёд: писана через час
                _row("safe_h", T0 + 2 * H, old_ver, sym="BUSDT", written=T0 + 40 * 86400),  # пересчёт
                _row("optimal_h", T0, old_ver, sym="CUSDT", sizing=R.SIZING_FIXED),
                _row("safe_h", T0 + 3 * H, old_ver + 1, sym="DUSDT"),  # не та версия
                _row("safe_h_g6", T0 + 4 * H, old_ver, sym="EUSDT")]   # не основная книга
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
        RP.append_journal([_row("pair_safe", T0, pold, book="safe_h"),
                           dict(_row("pair_safe", T0 + H, pold, sym="LUSDT", book="safe"), side="long")],
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


if __name__ == "__main__":
    for t in (test_sisters_in_registry_inherit_maps_and_differ_only_by_guard,
              test_birthdays_versions_and_tree,
              test_short_cache_signature_ignores_sisters_and_books_map_feeds_them,
              test_inherit_copies_old_guard_rows_into_branch_two_and_is_idempotent,
              test_inherit_runs_once_before_first_write_and_leaves_a_marker):
        t()
    print("\nвсе 5 проверок прошли")
