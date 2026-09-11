#!/usr/bin/env python3
"""Проверки общего счёта: длинная книга и короткая на ОДНОМ депозите.

Кусаются: общий счёт берёт МЕНЬШЕ сделок, чем два раздельных на тех же
решениях (касса одна — это и есть требование владельца, и подмена его
двумя вызовами кассы проверку роняет); билет остаётся билетом СВОЕЙ
стороны; совпадения имён и связь сторон считаются внутри самой книги;
без кэшей реплея — причина словами, а не пустые книги; издержки учтены в
каждой сделке, как и в отдельных книгах.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_pair as PR                                         # noqa: E402
import test_paper as TP                                       # noqa: E402

H = 3600.0
T0 = TP.T0


def _long(sym, at, pnl=0.10, hold_h=6.0, lev=4.0):
    return TP._rec(at, hold_h=hold_h, pnl=pnl, lev=lev, sym=sym)


def _short(sym, at, pnl=0.10, hold_h=6.0, lev=4.0):
    r = TP._rec(at, hold_h=hold_h, pnl=pnl, lev=lev, sym=sym)
    r["side"] = "short"
    return r


def _caches(longs, shorts, lk="safe", sk="safe_h"):
    """Кэши обеих книг в том виде, в каком их пишут сами прогоны."""
    lc = {(tuple(RP.RULERS[lk]), r["sym"], round(r["at"], 3)): r
          for r in longs}
    base = PR.S.BOOKS[sk]
    sc = {(base, r["sym"], round(r["at"], 3)): r for r in shorts}
    return lc, sc


def test_pack_marks_the_source_and_keeps_both_sides():
    longs = {"safe": [_long("AUSDT", T0)], "optimal": [_long("BUSDT", T0)]}
    shorts = {"safe_h": [_short("CUSDT", T0)]}
    got = PR.pack(longs, shorts, keys=["pair_safe"])["pair_safe"]
    assert [g["book"] for g in got] == ["safe", "safe_h"], got
    assert {g["sym"] for g in got} == {"AUSDT", "CUSDT"}, got
    # чужой режим в общую книгу не попадает
    assert "BUSDT" not in {g["sym"] for g in got}
    print("ok  общая книга собрана из СВОИХ двух книг, у каждой записи "
          "стоит источник")


def test_one_account_takes_less_than_two_separate_ones():
    """Один счёт — не сумма двух: касса одна, и часть сделок не случается.

    Проверка кусается ровно на требовании владельца: подмени общий счёт
    двумя вызовами кассы — и взятых станет столько же, сколько врозь.
    """
    n = 30
    longs = [_long(f"L{i}USDT", T0 + i, hold_h=48.0) for i in range(n)]
    shorts = [_short(f"S{i}USDT", T0 + i, hold_h=48.0) for i in range(n)]
    packed = PR.pack({"safe": longs}, {"safe_h": shorts}, keys=["pair_safe"])
    _rows, cells, _one, _live = RP.build_rows(packed, now=T0 + 200 * H,
                                              keys=["pair_safe"],
                                              log=lambda *a: None)
    apart_l, cl, _o, _l = RP.build_rows({"safe": longs}, now=T0 + 200 * H,
                                        keys=["safe"], log=lambda *a: None)
    apart_s, cs, _o2, _l2 = RP.build_rows({"safe_h": shorts},
                                          now=T0 + 200 * H, keys=["safe_h"],
                                          log=lambda *a: None)
    dep = int(R.DEPOSITS[0])
    both = cells[RP._cell("pair_safe", dep)]
    sep_l = cl[RP._cell("safe", dep)]
    sep_s = cs[RP._cell("safe_h", dep)]
    assert sep_l["taken"] + sep_s["taken"] == 2 * n, (sep_l, sep_s)
    assert both["taken"] < sep_l["taken"] + sep_s["taken"], (both, sep_l, sep_s)
    assert both["no_cash"] > 0, both
    # мест и билета у общего счёта одного не существует: у сторон он свой
    assert both.get("ticket") is None and both.get("share_by_source") is True
    print(f"ok  общий счёт взял {both['taken']} решений из {2 * n}; врозь "
          f"те же решения берутся все ({sep_l['taken']} + {sep_s['taken']}), "
          f"отказов по кассе {both['no_cash']}")


def test_ticket_stays_the_ticket_of_its_own_side():
    """Билет — свойство СТОРОНЫ: у длинной свой, у короткой свой.

    Кусается: общий билет сделал бы маржу сторон равной, а она обязана
    отличаться ровно во столько раз, во сколько отличаются билеты книг.
    """
    dep = 10000.0
    longs = [_long("AUSDT", T0)]
    shorts = [_short("BUSDT", T0)]
    packed = PR.pack({"safe": longs}, {"safe_h": shorts}, keys=["pair_safe"])
    rows, _c, _o, _l = RP.build_rows(packed, now=T0 + 100 * H,
                                     keys=["pair_safe"], log=lambda *a: None)
    mine = {r["sym"]: r for r in rows if int(r["dep"]) == int(dep)}
    assert set(mine) == {"AUSDT", "BUSDT"}, mine
    want = R.ticket(dep, "safe_h") / R.ticket(dep, "safe")
    got = mine["BUSDT"]["margin"] / mine["AUSDT"]["margin"]
    assert want > 3, want            # книги и правда с разными билетами
    assert abs(got - want) < 0.02 * want, (got, want, mine)
    assert mine["AUSDT"].get("book") == "safe"
    assert mine["BUSDT"].get("book") == "safe_h"
    print(f"ok  билет по стороне: короткая маржа больше длинной в "
          f"{got:.1f}× при объявленном отношении {want:.1f}×")


def test_short_side_enters_with_the_declared_share():
    """Билет короткой стороны в общем счёте — объявленная доля своего.

    Решение владельца 2026-09-07 по замеру `short_why`: 0.25 у общей
    оптимальной и общей агрессивной, у безопасной без изменений.
    Кусается на дороге целиком: маржа строки короткой стороны обязана
    быть вчетверо меньше её собственного билета там, где доля
    объявлена, и равна ему там, где не объявлена.
    """
    dep = 10000.0
    longs = [_long("AUSDT", T0)]
    shorts = [_short("BUSDT", T0)]
    got = {}
    for pk in ("pair_safe", "pair_optimal"):
        lk, sk = R.parts_of(pk)
        packed = PR.pack({lk: longs}, {sk: shorts}, keys=[pk])
        rows, _c, one, _l = RP.build_rows(packed, now=T0 + 100 * H,
                                          keys=[pk], log=lambda *a: None)
        mine = {r["sym"]: r for r in rows if int(r["dep"]) == int(dep)}
        got[pk] = (mine["BUSDT"]["margin"], R.ticket(dep, sk),
                   (one[pk]["parts"][sk]["ticket"][str(int(dep))]))
    m_safe, own_safe, _t = got["pair_safe"]
    m_opt, own_opt, _t2 = got["pair_optimal"]
    assert abs(m_safe - own_safe) < 0.02 * own_safe, got["pair_safe"]
    assert abs(m_opt - 0.25 * own_opt) < 0.02 * own_opt, got["pair_optimal"]
    assert R.pair_share_mult("pair_optimal", "optimal_h") == 0.25
    assert R.pair_share_mult("pair_optimal", "optimal") == 1.0, "лонг не режем"
    assert R.pair_share_mult("pair_safe", "safe_h") == 1.0
    print(f"ok  короткая сторона входит объявленной долей: у безопасной "
          f"${m_safe:.0f} из ${own_safe:.0f}, у оптимальной ${m_opt:.0f} "
          f"из ${own_opt:.0f}")


def test_the_share_never_dives_under_the_exchange_floor():
    """Доля не вправе опустить билет под биржевой минимум.

    Иначе правило не уменьшало бы риск, а вычёркивало сделки молча:
    касса отказала бы им «мельче минимума». На депозите $1k билеты и так
    стоят на полу — там доля не кусается, и это видно числом.
    """
    small = R.DEPOSITS[0]
    sk = R.parts_of("pair_optimal")[1]
    got = R.ticket_in("pair_optimal", sk, small)
    assert got == R.floor_of(sk), (got, R.floor_of(sk))
    assert got > R.ticket(small, sk) * 0.25, (got, R.ticket(small, sk))
    # на $10k пол не мешает, и доля кусается полностью
    big = R.DEPOSITS[1]
    assert abs(R.ticket_in("pair_optimal", sk, big)
               - 0.25 * R.ticket(big, sk)) < 1e-9
    print(f"ok  доля билета не ныряет под пол биржи: на ${int(small)} "
          f"билет остаётся ${got:g}, на ${int(big)} режется до "
          f"${R.ticket_in('pair_optimal', sk, big):g}")


def test_family_rules_retire_the_old_rows_without_touching_other_books():
    """Смена правил СЕМЕЙСТВА не трогает запись остальных книг.

    Кусается: строка общего счёта прежней версии (без поля) в счёт не
    идёт, но остаётся читаемой; строка длинной книги без того же поля —
    идёт, потому что у её семейства своей версии нет; ключ дедупа
    различает версии, иначе решение, пересчитанное по новому правилу, не
    записалось бы никогда.
    """
    old = {"dep": 1000, "ruler": "pair_safe", "at": T0, "exit_ts": T0 + H,
           "sym": "AUSDT", "side": "short", "usd": 1.0, "lev": 2.0,
           "margin": 25.0, "pnl_frac": 0.04, "exit": "тейк",
           "written_at": T0 + H, "rules": R.RULES}
    new = dict(old, book_rules=R.FAMILY_RULES["pair"])
    plain = dict(old, ruler="safe", side="long")
    assert not R.is_current(old), "строка прежней версии семейства учтена"
    assert R.is_current(new), "строка нынешней версии не учтена"
    assert R.is_current(plain), "у длинной книги своей версии нет"
    assert R.journal_key(old) != R.journal_key(new), "версии не различены"
    # запись не пропала: журнал читается целиком
    rows = [old, new]
    assert len([r for r in rows if R.ruler_of(r) == "pair_safe"]) == 2
    print(f"ok  версия правил семейства {R.FAMILY_RULES['pair']}: строки "
          "прежней версии остаются в журнале и в счёт не идут, книги "
          "других семейств не тронуты")


def test_rate_gate_machinery_works_and_the_rule_is_off_now():
    """Гейт по ставке — правило входа КОРОТКОЙ стороны общего счёта.

    Кусается: шорт со ставкой не в его пользу не входит, со ставкой в
    пользу входит, без ставки не входит вовсе, и оба отказа считаются
    РАЗНЫМИ числами. Длинная сторона гейта не видит. Рядов нет вовсе —
    книга не останавливается молча: она идёт без гейта и говорит это
    причиной.
    """
    import numpy as np
    t = np.asarray([int((T0 - 3600.0) * 1000)], dtype=np.int64)
    ctx = {"to_asset": {"AUSDT": "A", "BUSDT": "B", "CUSDT": "C"},
           "funding": {"A": (t, np.asarray([0.0002])),      # шорту в пользу
                       "B": (t, np.asarray([-0.0002]))}}    # против
    shorts = [_short("AUSDT", T0), _short("BUSDT", T0), _short("CUSDT", T0)]
    # Машинерия проверяется при ВКЛЮЧЁННОМ гейте: само правило снято
    # 08.09 (его результат держался на «ставке неизвестна»), но код
    # остаётся — он понадобится, если гейт вернётся другим порогом.
    was = R.PAIR_SHORT_GATE["pair_safe"]
    try:
        R.PAIR_SHORT_GATE["pair_safe"] = True
        keep, why = PR.gate_shorts(shorts, "pair_safe", ctx,
                                   log=lambda *a: None)
        assert [r["sym"] for r in keep] == ["AUSDT"], keep
        assert why["по ставке"] == 1 and why["ставка неизвестна"] == 1, why
        assert why["applied"] is True and why["max_age_h"] > 0, why
        # рядов нет вовсе — не «никто не входит», а причина словами
        none_, w3 = PR.gate_shorts(shorts, "pair_safe", {"to_asset": {}},
                                   log=lambda *a: None)
        assert len(none_) == 3 and w3.get("applied") is False and w3.get("why")
    finally:
        R.PAIR_SHORT_GATE["pair_safe"] = was
    # книга без объявленного гейта берёт всё — и сейчас объявлено именно
    # это, во всех трёх книгах
    off, w2 = PR.gate_shorts(shorts, "pair_safe", ctx, log=lambda *a: None)
    assert len(off) == 3 and w2["gate"] is False, (off, w2)
    assert not any(R.short_gate_on(k) for k in R.PAIR_ORDER), R.PAIR_SHORT_GATE
    # каждая смена правила семейства — новая версия записи
    assert R.FAMILY_RULES["pair"] >= 4, R.FAMILY_RULES
    print(f"ok  машинерия гейта: взят {len(keep)} из {len(shorts)} "
          f"(по знаку {why['по ставке']}, неизвестна "
          f"{why['ставка неизвестна']}); само правило сейчас СНЯТО во "
          f"всех книгах, версия записи {R.FAMILY_RULES['pair']}")


def test_every_family_version_carries_the_day_it_changed():
    """Смена версии семейства обнуляет «записанное вперёд».

    Кусается: у каждого семейства с версией правил обязан быть день
    смены, и он обязан доехать до страницы сводом. Без даты короткая
    запись вперёд читается как «книга перестала торговать» — владелец
    так её и прочитал 08.09.
    """
    assert set(R.FAMILY_RULES) <= set(R.FAMILY_SINCE), (R.FAMILY_RULES,
                                                        R.FAMILY_SINCE)
    for fam, day in R.FAMILY_SINCE.items():
        assert len(str(day)) == 10 and str(day)[4] == "-", (fam, day)
    assert R.family_since("safe_h") == R.FAMILY_SINCE["h24"]
    assert R.family_since("pair_safe") == R.FAMILY_SINCE["pair"]
    assert R.family_since("safe") is None, "у длинных книг версии нет"
    snap = RP.rules_snapshot(keys=list(R.PAIR_ORDER))
    assert snap["FAMILY_SINCE"] == R.FAMILY_SINCE, snap.get("FAMILY_SINCE")
    assert snap["FAMILY_RULES"] == R.FAMILY_RULES, snap.get("FAMILY_RULES")
    print("ok  у каждого семейства с версией есть день смены "
          f"({', '.join(f'{k} {v}' for k, v in R.FAMILY_SINCE.items())}), "
          "и он едет на страницу сводом")


def test_age_rule_refuses_young_names_and_counts_the_unknown_apart():
    """Возраст имени — объявленное правило входа КОРОТКОЙ стороны.

    Кусается: возраст считается на МОМЕНТ РЕШЕНИЯ (имя, молодое в день
    входа, не спасается тем, что сегодня оно старое); имя без даты
    листинга не входит и считается ОТДЕЛЬНЫМ числом; длинная сторона
    правила не видит; справочника нет вовсе — книга идёт без фильтра и
    говорит причину, а не встаёт молча.
    """
    day = 86400.0
    launch = {"OLDUSDT": T0 - 100 * day, "NEWUSDT": T0 - 2 * day,
              "EDGEUSDT": T0 - 30 * day}
    shorts = [_short("OLDUSDT", T0), _short("NEWUSDT", T0),
              _short("XXXUSDT", T0),
              # молодое НА МОМЕНТ РЕШЕНИЯ: листинг за сутки до входа
              _short("EDGEUSDT", T0 - 29 * day)]
    keep, why = RP.age_shorts(shorts, "pair_safe", launch=launch,
                              log=lambda *a: None, now=T0)
    assert [r["sym"] for r in keep] == ["OLDUSDT"], keep
    assert why["моложе порога"] == 2, why
    assert why["возраст неизвестен"] == 1, why
    assert why["applied"] is True and why["days"] == R.min_age_days("pair_safe")
    # справочника нет — не «никто не входит», а причина словами
    none_, w2 = RP.age_shorts(shorts, "pair_safe", launch={},
                              log=lambda *a: None, now=T0)
    assert len(none_) == 4 and w2.get("applied") is False and w2.get("why")
    # правило объявлено во ВСЕХ трёх книгах общего счёта и записано
    # своей версией: строки прежних правил в счёт не идут
    assert all(R.min_age_days(k) >= 7 for k in R.PAIR_ORDER), R.MIN_AGE_DAYS
    assert R.FAMILY_RULES["pair"] >= 5, R.FAMILY_RULES
    # и оно видно на самой странице книги, а не только в отчёте
    assert "моложе" in R.RULERS["pair_safe"]["plain"]
    print(f"ok  фильтр возраста ≥{why['days']:g} сут: взят "
          f"{len(keep)} из {len(shorts)}, моложе порога "
          f"{why['моложе порога']} (одно — по дате РЕШЕНИЯ), возраст "
          f"неизвестен {why['возраст неизвестен']}; версия записи "
          f"{R.FAMILY_RULES['pair']}")


def test_collisions_and_link_live_inside_the_book():
    """Совпадение имён и связь сторон считаются по строкам самой книги."""
    at = T0
    rows = []
    for (sym, side, a, h) in (("XUSDT", "long", at, 10.0),
                              ("XUSDT", "short", at + 2 * H, 4.0),
                              ("YUSDT", "long", at, 4.0),
                              ("YUSDT", "short", at + 4 * H, 4.0)):
        rows.append({"dep": 1000, "ruler": "pair_safe", "at": a,
                     "exit_ts": a + h * H, "sym": sym, "side": side,
                     "book": "safe" if side == "long" else "safe_h",
                     "lev": 2.0, "margin": 25.0, "pnl_frac": 0.02,
                     "usd": 1.0, "exit": "тейк", "written_at": a + H,
                     "rules": R.RULES})
    col = PR.collisions(rows, "pair_safe")
    # X: шорт открыт ВНУТРИ длинной — совпадение; Y: шорт открыт ровно в
    # секунду выхода длинной — касание встык, не совпадение
    assert col["n"] == 1 and col["names"] == 1, col
    one_side = PR.collisions([r for r in rows if r["side"] == "long"],
                             "pair_safe")
    assert one_side["n"] == 0 and one_side.get("why"), one_side
    lk = PR.link(rows, "pair_safe")
    assert lk["corr"] is None and lk.get("why"), lk
    print(f"ok  совпадений имён {col['n']} (касание встык не считается); "
          "связь без трёх общих суток — причина словами")


def test_books_sharing_one_geometry_both_get_their_positions():
    """Одна пара линейки кормит НЕСКОЛЬКО книг, и обе обязаны их получить.

    «Оптимальная» и «агрессивная» считаются на одной геометрии и
    различаются гейтом плеча. Словарь «пара → книга» оставлял только
    последнюю, и общая книга режима выходила БЕЗ ДЛИННОЙ СТОРОНЫ: ноль,
    выглядящий как книга (поймано первым же живым прогоном — «длинных
    0» при 7336 позициях в кэше).
    """
    share = [k for k in R.order_of("sit")
             if tuple(RP.RULERS[k]) == tuple(RP.RULERS["optimal"])]
    assert len(share) > 1, ("проверка потеряла смысл: геометрию больше "
                            "никто не делит", share)
    rec = _long("AUSDT", T0)
    cache = {(tuple(RP.RULERS["optimal"]), "AUSDT", round(T0, 3)): rec}
    got, why = PR.long_recs(cache, log=lambda *a: None)
    assert not why, why
    assert set(got) == set(share), (sorted(got), share)
    assert all(len(v) == 1 for v in got.values()), got
    print(f"ok  общую геометрию делят {len(share)} книги ({', '.join(share)}), "
          "и позиции достаются каждой")


def test_memory_guard_stops_the_run_itself():
    """Прогон останавливается САМ и с числом: OOM выбирает не его.

    На сервере тяжёлый прогон рядом с часовым циклом уже убивал ЦИКЛ, а
    не себя. Сторож памяти — тот же, что у разреза по рукам.
    """
    said = []
    try:
        PR.run(long_cache={}, short_cache={}, log=said.append,
               mem_limit=0.0)
    except SystemExit as e:
        assert e.code == 3, e
    else:
        raise AssertionError("сторож памяти не сработал: " + str(said))
    assert any("СТОП: память" in x for x in said), said
    print("ok  сторож памяти останавливает общий счёт сам и говорит число")


def test_missing_caches_are_a_reason_not_empty_books():
    s = PR.run(long_cache={}, short_cache={}, log=lambda *a: None)
    assert s.get("error") and not s.get("books"), s
    txt = PR.report(s)
    assert "Не посчитан" in txt and s["error"] in txt, txt[:400]
    print(f"ok  без кэшей общий счёт не считается: «{s['error']}» — "
          "причина словами, а не пустые книги")


def test_end_to_end_writes_its_own_journal_and_compares_with_two_accounts():
    """Прогон целиком: свой журнал, свой свод, сравнение с раздельными.

    Кусается: строки общей книги НЕ попадают в журналы отдельных книг
    (иначе их числа посчитались бы дважды), а раздел сравнения берёт
    деньги раздельных счетов из ИХ журналов.
    """
    n = 12
    longs = [_long(f"L{i}USDT", T0 + i * H, hold_h=6.0) for i in range(n)]
    shorts = [_short(f"S{i}USDT", T0 + i * H, hold_h=6.0, pnl=-0.05)
              for i in range(n)]
    lc, sc = _caches(longs, shorts)
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "pair.jsonl")
        lj = os.path.join(td, "journal.jsonl")
        sj = os.path.join(td, "short.jsonl")
        # журналы отдельных книг — тем же писателем, что у самих книг
        lrows, _c, _o, _l = RP.build_rows({"safe": longs}, now=T0 + 100 * H,
                                          keys=["safe"], log=lambda *a: None)
        srows, _c2, _o2, _l2 = RP.build_rows({"safe_h": shorts},
                                             now=T0 + 100 * H,
                                             keys=["safe_h"],
                                             log=lambda *a: None)
        RP.append_journal(lrows, path=lj, log=lambda *a: None)
        RP.append_journal(srows, path=sj, log=lambda *a: None)
        # Справочник листингов подаётся явно: правило возраста стоит на
        # входе короткой стороны, и молча брать боевой файл значило бы
        # мерить сквозной прогон чужими датами.
        launch = {f"S{i}USDT": T0 - 200 * 86400.0 for i in range(n)}
        s = PR.run(long_cache=lc, short_cache=sc, journal=jp,
                   long_journal=lj, short_journal=sj,
                   keys=["pair_safe"], now=T0 + 100 * H,
                   launch=launch, log=lambda *a: None)
        a = (s.get("ages") or {}).get("pair_safe") or {}
        assert a.get("applied") and a.get("kept") == n, a
        assert not s.get("error"), s.get("error")
        dep = int(R.DEPOSITS[1])
        b = s["books"][RP._cell("pair_safe", dep)]
        st = b["all"]
        assert st["n"] == 2 * n, st
        pr = b["parts"]
        assert set(pr) == {"safe", "safe_h"}, pr
        assert pr["safe"]["stats"]["n"] == n == pr["safe_h"]["stats"]["n"]
        assert pr["safe"]["ticket"] != pr["safe_h"]["ticket"], pr
        assert b["ticket"] is None and b["slots"] is None, b
        # издержки считаются той же дорогой, что у отдельных книг
        assert b["costs"]["n"] == st["n"], b["costs"]
        # обе стороны на месте — и это сказано полем, а не подразумевается
        assert b["one_sided"] is None, b["one_sided"]
        # контроль: книга без одной стороны обязана назвать её
        half = dict(b, parts={"safe": pr["safe"],
                              "safe_h": dict(pr["safe_h"], stats=None)})
        assert PR.one_sided(half, "safe", "safe_h") == ["safe_h"], half["parts"]
        bad_txt = PR.report(dict(s, books={RP._cell("pair_safe", dep):
                                           dict(half, one_sided=["safe_h"])}))
        assert "ВНИМАНИЕ: общий счёт не собран из двух сторон" in bad_txt
        # раздельные счета взяты из журналов самих книг и посчитаны
        # ТЕМ ЖЕ ядром издержек: колонка нетто против колонки брутто в
        # одной таблице — ошибка единиц, и она в проекте уже ловилась
        sc = s["separate_costs"]
        # строк обеих книг по ВСЕМ депозитам, и все прошли через то же
        # ядро издержек (здесь рядов funding нет — тогда «применено»
        # считает те, у кого измеримы комиссия и проскальзывание)
        assert sc["n"] == 2 * n * len(R.DEPOSITS), sc
        sep = b["separate"]
        assert sep["safe"]["n"] == n and sep["safe_h"]["n"] == n, sep
        assert abs(st["usd"] - (sep["safe"]["usd"] + sep["safe_h"]["usd"])) \
            > 1e-9, (st["usd"], sep)
        # журнал общей книги СВОЙ: в журналах отдельных книг её строк нет
        prows, _ = R.read_journal(jp)
        assert {R.ruler_of(r) for r in prows} == {"pair_safe"}, prows[:1]
        lrows2, _ = R.read_journal(lj)
        assert all(R.ruler_of(r) == "safe" for r in lrows2)
        txt = PR.report(s)
        assert "Один счёт против двух раздельных" in txt
        assert "Издержки: учтены в каждой сделке" in txt
        print(f"ok  общий счёт: {st['n']} сделок, {st['usd']:+.2f} $ против "
              f"{sep['safe']['usd'] + sep['safe_h']['usd']:+.2f} $ у двух "
              "раздельных; журнал свой")


def test_report_shows_what_the_money_is_made_of():
    """Концентрация обязана стоять и в отчёте общего счёта.

    Те же колонки, что у длинных книг: одна разогнанная монета, один
    рыночный эпизод, один день просадки. Кусается на подставной книге, у
    которой три дня несут ВСЁ: без них итог уходит в минус, и это должно
    быть видно строкой таблицы. Числа считает то же ядро
    (`run_paper._stats`), проверка смотрит на дорогу до показа.
    """
    D = 86400
    rows = []
    for i in range(10):
        rows.append({"dep": 10000, "rules": R.RULES, "sym": f"T{i}USDT",
                     "at": T0 + i * D, "exit_ts": T0 + i * D + 60,
                     "usd": -1.0, "written_at": T0 + i * D + 120,
                     "lev": 4.0, "margin": 25.0, "pnl_frac": -0.04,
                     "exit": "срок"})
    for j in range(3):
        for k in range(4):
            rows.append({"dep": 10000, "rules": R.RULES,
                         "sym": f"F{j}{k}USDT", "at": T0 + (20 + j) * D,
                         "exit_ts": T0 + (20 + j) * D + 60, "usd": 5.0,
                         "written_at": T0 + (20 + j) * D + 120, "lev": 4.0,
                         "margin": 25.0, "pnl_frac": 0.2, "exit": "тейк"})
    st = RP._stats(rows, 10000.0)
    s = {"books": {RP._cell("pair_safe", 10000): {
            "deposit": 10000.0, "ruler": "pair_safe", "all": st,
            "parts": {}, "n_forward": 0, "n_restored": len(rows)}},
         "rulers": ["pair_safe"], "ages": {},
         "rules": RP.rules_snapshot(), "computed_at": "2026-09-11 10:00"}
    txt = PR.report(s)
    assert "$ без 3 лучших дней" in txt, txt[:300]
    assert "просадка без худшего дня" in txt, txt[:300]
    line = [x for x in txt.splitlines() if "-10.00" in x]
    assert line, [x for x in txt.splitlines() if "pair" in x.lower()][:3]
    print(f"ok  отчёт общего счёта называет концентрацию: без 3 лучших дней "
          f"{st['usd_wo_top3d']:+.0f} $ при итоге {st['usd']:+.0f} $")


if __name__ == "__main__":
    for t in (test_pack_marks_the_source_and_keeps_both_sides,
              test_books_sharing_one_geometry_both_get_their_positions,
              test_short_side_enters_with_the_declared_share,
              test_rate_gate_machinery_works_and_the_rule_is_off_now,
              test_age_rule_refuses_young_names_and_counts_the_unknown_apart,
              test_every_family_version_carries_the_day_it_changed,
              test_the_share_never_dives_under_the_exchange_floor,
              test_family_rules_retire_the_old_rows_without_touching_other_books,
              test_memory_guard_stops_the_run_itself,
              test_one_account_takes_less_than_two_separate_ones,
              test_ticket_stays_the_ticket_of_its_own_side,
              test_collisions_and_link_live_inside_the_book,
              test_missing_caches_are_a_reason_not_empty_books,
              test_end_to_end_writes_its_own_journal_and_compares_with_two_accounts,
              test_report_shows_what_the_money_is_made_of):
        t()
    print("\nвсе 15 проверок прошли")
