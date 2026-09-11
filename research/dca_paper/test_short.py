#!/usr/bin/env python3
"""Проверки коротких книг на сигнале h24 и общей статистики.

Кусаются: подпись кэша меняется вместе с ячейкой и сроком (иначе книга
считала бы чужие исходы своими); ноги берутся у ОБЕИХ рук и стоят по
времени; книга «агрессивная» отличается от «оптимальной» ровно гейтом
плеча; журнал и артефакт семейства СВОИ (в журнал длинных книг не
попадает ни строки). Общий счёт двух книг проверяет `test_pair.py`: он
считается своей книгой, а не блоком этого прогона.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_short as S                                         # noqa: E402
import run_paper as RP                                        # noqa: E402
import test_paper as TP                                        # noqa: E402
import run_d10 as D10                                         # noqa: E402
import run_d2 as D2                                           # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import test_run_d9 as T9                                      # noqa: E402
import test_run_d10 as T10                                    # noqa: E402

H = 3600.0
T0 = 1786320000.0


def _picks(path, hours, arms=("gbm", "nn")):
    """Журнал выборов книги со сроком: у каждой руки своё имя в час."""
    with open(path, "w", encoding="utf-8") as f:
        for h in hours:
            for arm in arms:
                sym = "SSSUSDT" if arm == "gbm" else "TTTUSDT"
                f.write(json.dumps({
                    "arm": arm, "hour": h, "long": [],
                    "short": [{"sym": sym, "fwd": -420.0, "px": 100.0,
                               "mae": 120.0, "mfe": -700.0}]}) + "\n")


def test_cache_signature_follows_the_cell_and_the_hold():
    was_hold, was_cell = R.H24_HOLD_H, S.CELL
    a = S.cache_sig()
    try:
        R.H24_HOLD_H = 72
        b = S.cache_sig()
        assert b != a and b["hold_h"] == 72, (a, b)
        R.H24_HOLD_H = was_hold
        S.CELL = ("c3:none:t2", "c3", "none", "t2")
        c = S.cache_sig()
        assert c != a and c["cell"] == "c3:none:t2", (a, c)
    finally:
        R.H24_HOLD_H, S.CELL = was_hold, was_cell
    assert S.cache_sig() == a
    print("ok  подпись кэша меняется вместе со сроком и ячейкой — чужие "
          "исходы своими не станут")


def test_legs_come_from_both_arms_in_time_order():
    tmp = tempfile.mkdtemp(prefix="short-")
    path = os.path.join(tmp, "picks.jsonl")
    try:
        _picks(path, ["2026-09-01-00", "2026-09-01-01"])
        got = S.legs(path=path, log=lambda *a: None)
        assert len(got) == 4, got
        assert {g["arm"] for g in got} == {"gbm", "nn"}
        assert [g["at"] for g in got] == sorted(g["at"] for g in got)
        # внутри часа порядок по руке: он же порядок кассы
        assert [g["arm"] for g in got[:2]] == ["gbm", "nn"], got[:2]
        assert all(g["side"] == "short" for g in got)
        print(f"ok  ноги обеих рук: {len(got)} решений, порядок по времени "
              "и руке")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_needs_replay_asks_for_new_and_open_positions():
    legs = [{"sym": "AAAUSDT", "at": T0}, {"sym": "BBBUSDT", "at": T0 + H}]
    cache = {}
    assert len(S.needs_replay(cache, legs)) == 2
    for rk in set(S.BOOKS.values()):
        cache[(rk, "AAAUSDT", round(T0, 3))] = {"state": "closed"}
        cache[(rk, "BBBUSDT", round(T0 + H, 3))] = {"state": "open"}
    need = S.needs_replay(cache, legs)
    assert [g["sym"] for g in need] == ["BBBUSDT"], need
    print("ok  заново считаются новые решения и открытые позиции, "
          "закрытые берутся из кэша")


def _end_to_end(tmp):
    lo, at = T9._rise_then_fall()
    wn, _ = T9._drift_down()
    src = T3._Src({"SSSUSDT": lo, "TTTUSDT": wn})
    legs = T10._legs(at, "SSSUSDT") + T10._legs(at, "TTTUSDT")
    for i, g in enumerate(legs):
        g["arm"] = "nn" if i % 2 else "gbm"
    jp = os.path.join(tmp, "short.jsonl")
    cp = os.path.join(tmp, "recs.jsonl")
    # Справочник листингов подаётся ЯВНО: с 08.09 у книг есть правило
    # возраста имени, и молча взять боевой файл значило бы судить
    # выдуманные символы чужими датами (все — «возраст неизвестен»).
    t_first = min(float(g["at"]) for g in legs)
    launch = {sym: t_first - 90 * 86400.0
              for sym in ("SSSUSDT", "TTTUSDT")}
    s = T10._with_levels(lambda: S.run(legs_=legs, src=src, journal=jp,
                                       cache_path=cp, launch=launch,
                                       log=lambda *a: None))
    return s, jp, cp, legs, launch


def test_family_writes_its_own_journal_and_gates_the_aggressive_book():
    tmp = tempfile.mkdtemp(prefix="short-")
    try:
        s, jp, cp, legs, launch = _end_to_end(tmp)
        assert s["family"] == "h24" and s["hedge"] is True
        assert s["signal"]["hold_h"] == R.H24_HOLD_H == 24
        assert s["rules"]["RULER_ORDER"] == list(R.H24_ORDER)
        assert set(s["rulers"]) == set(R.H24_ORDER), s["rulers"]
        # журнал семейства свой, и он не пуст
        rows, bad = R.read_journal(jp)
        assert rows and not bad
        assert {R.ruler_of(r) for r in rows} <= set(R.H24_ORDER), \
            sorted({R.ruler_of(r) for r in rows})
        assert all(r["side"] == "short" for r in rows)
        # «агрессивная» — та же линейка, но гейт плеча: правило читается,
        # а не подразумевается. Поднимаем порог до заведомо недостижимого
        # и требуем, чтобы книга опустела: гейт, которого нет, этого не
        # сделает.
        one = s["one_name"]
        assert one["aggr_h"]["min_lev"] == R.AGGR_MIN_LEV
        assert one["optimal_h"]["min_lev"] is None
        assert one["aggr_h"]["kept"] <= one["optimal_h"]["kept"], one
        was_gate = R.RULERS["aggr_h"].get("min_lev")
        try:
            R.RULERS["aggr_h"]["min_lev"] = 999.0
            s2 = T10._with_levels(lambda: S.run(
                legs_=legs, src=T3._Src({}), journal=os.path.join(tmp, "g.jsonl"),
                cache_path=cp, launch=launch, log=lambda *a: None))
            assert s2["one_name"]["aggr_h"]["kept"] == 0, s2["one_name"]["aggr_h"]
            assert s2["one_name"]["optimal_h"]["kept"] > 0
        finally:
            R.RULERS["aggr_h"]["min_lev"] = was_gate
        # билет книги — из объявленного пика режима
        b = s["books"][f"optimal_h:{int(R.DEPOSITS[1])}"]
        # билет — С ДОЛЕЙ, объявленной для книги, а не «свой» билет режима
        assert b["ticket"] == R.ticket_in("optimal_h", "optimal_h",
                                          R.DEPOSITS[1]), b["ticket"]
        assert (b.get("dups") or {}).get("overlaps") == 0, b.get("dups")
        # кэш пригоден для следующего прогона: второй прогон не считает заново
        cache, why = S.read_cache(cp, log=lambda *a: None)
        assert not why and cache, why
        assert not S.needs_replay(cache, [g for g in legs
                                          if g["sym"] == "SSSUSDT"][:1])
        txt = S.report(s)
        assert "хедж" in txt.lower() and "## Книги" in txt
        print(f"ok  семейство пишет свой журнал ({len(rows)} строк), "
              f"«агрессивная» под гейтом {one['aggr_h']['kept']} против "
              f"{one['optimal_h']['kept']} у «оптимальной», дублей нет")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_floor_is_per_book_and_the_cache_knows_it():
    """Пол капитуляции — свой у книги, и кэш обязан это знать.

    Кусается трижды: линейки раскладываются по СВОЕМУ полу; линейка,
    кормящая книги с разным полом, — отказ словами, а не молчаливый
    выбор первой доли; подпись кэша меняется вместе с полом — иначе
    прогон подставил бы исходы ДРУГОЙ книги, ведь ключ записи от пола
    не зависит.
    """
    import run_d2 as D2

    g = S.floor_groups()
    assert g == {0.10: ["safe_s"], 0.50: ["optimal_s"]}, g
    assert R.floor_frac_of("safe_h", D2.FLOOR_FRAC) == 0.10
    assert R.floor_frac_of("aggr_h", D2.FLOOR_FRAC) == 0.50
    # длинные книги не тронуты: у них своей доли нет вовсе
    assert R.floor_frac_of("safe", D2.FLOOR_FRAC) == D2.FLOOR_FRAC
    was = dict(R.FLOOR_FRAC_BY_BOOK)
    a = S.cache_sig()
    try:
        R.FLOOR_FRAC_BY_BOOK["aggr_h"] = 0.25
        try:
            S.floor_groups()
            raise AssertionError("линейка с двумя полами прошла молча")
        except ValueError as e:
            assert "разным полом" in str(e), str(e)
        R.FLOOR_FRAC_BY_BOOK["aggr_h"] = 0.50
        R.FLOOR_FRAC_BY_BOOK["safe_h"] = 0.75
        b = S.cache_sig()
        assert a != b, (a["floor"], b["floor"])
    finally:
        R.FLOOR_FRAC_BY_BOOK.clear()
        R.FLOOR_FRAC_BY_BOOK.update(was)
    assert S.cache_sig() == a, "подпись не вернулась к объявленной"
    print(f"ok  пол по книгам: {g}; линейка с двумя полами — отказ "
          "словами; подпись кэша меняется вместе с полом")


def test_replay_gives_each_ruler_its_own_floor():
    """Симуляция линейки видит ИМЕННО её пол — проверка на самой дороге."""
    import run_d2 as D2

    tmp = tempfile.mkdtemp(prefix="short-floor-")
    try:
        lo, at = T9._rise_then_fall()
        wn, _ = T9._drift_down()

        class Spy(T3._Src):
            def __init__(self, data):
                super().__init__(data)
                self.saw = []

            def bars(self, sym, a, b):
                self.saw.append(D2.FLOOR_FRAC)
                return super().bars(sym, a, b)

        src = Spy({"SSSUSDT": lo, "TTTUSDT": wn})
        legs = T10._legs(at, "SSSUSDT")
        was = D2.FLOOR_FRAC
        out, _tail = T10._with_levels(
            lambda: S.replay(legs, src=src, log=lambda *a: None))
        assert D2.FLOOR_FRAC == was, D2.FLOOR_FRAC
        assert set(src.saw) == {0.10, 0.50}, src.saw
        rulers = {rk for (rk, _s, _a) in out}
        assert rulers <= {"safe_s", "optimal_s"}, rulers
        print(f"ok  реплей отдал каждой линейке свой пол: симуляция видела "
              f"{sorted(set(src.saw))}, линейки {sorted(rulers)}; "
              f"глобальный пол после прогона на месте ({was:g})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_age_rule_of_the_book_bites_and_counts_the_unknown_apart():
    """Правило возраста имени — правило самой книги с 2026-09-08.

    Кусается: молодое имя в книгу не входит, имя без даты листинга не
    входит тоже и считается ОТДЕЛЬНЫМ числом, справочника нет вовсе —
    книга идёт без фильтра и говорит причину, а не встаёт молча.
    """
    tmp = tempfile.mkdtemp(prefix="short-age-")
    try:
        s, jp, cp, legs, launch = _end_to_end(tmp)
        a = (s.get("ages") or {}).get("safe_h") or {}
        assert a.get("applied") and a["kept"] == a["offered"], a
        assert R.min_age_days("safe_h") >= 7, R.MIN_AGE_DAYS
        assert R.FAMILY_RULES["h24"] >= 1, R.FAMILY_RULES
        base = s["books"][f"safe_h:{int(R.DEPOSITS[1])}"]["all"]["n"]
        # те же ноги, но имена листнуты вчера — книга обязана опустеть
        young = {k: min(float(g["at"]) for g in legs) - 86400.0
                 for k in launch}
        s2 = T10._with_levels(lambda: S.run(
            legs_=legs, src=T3._Src({}),
            journal=os.path.join(tmp, "y.jsonl"), cache_path=cp,
            launch=young, log=lambda *a: None))
        a2 = s2["ages"]["safe_h"]
        assert a2["kept"] == 0 and a2["моложе порога"] == a2["offered"], a2
        # даты неизвестны — отказ ТОТ ЖЕ, но причина считается отдельно
        s3 = T10._with_levels(lambda: S.run(
            legs_=legs, src=T3._Src({}),
            journal=os.path.join(tmp, "u.jsonl"), cache_path=cp,
            launch={"ЧУЖОЙUSDT": 1.0}, log=lambda *a: None))
        a3 = s3["ages"]["safe_h"]
        assert a3["kept"] == 0 and a3["возраст неизвестен"] == a3["offered"]
        assert a3["моложе порога"] == 0, a3
        # справочника нет вовсе — книга идёт БЕЗ фильтра, с причиной
        s4 = T10._with_levels(lambda: S.run(
            legs_=legs, src=T3._Src({}),
            journal=os.path.join(tmp, "n.jsonl"), cache_path=cp,
            launch={}, log=lambda *a: None))
        a4 = s4["ages"]["safe_h"]
        assert a4.get("applied") is False and a4.get("why"), a4
        assert a4["kept"] == a4["offered"], a4
        txt = S.report(s)
        assert "возраст неизвестен" in txt and "доля билета" in txt
        print(f"ok  правило возраста книги: старые имена дают {base} "
              f"сделок, молодые — {a2['kept']} решений (причина «моложе "
              f"порога» {a2['моложе порога']}), без даты — "
              f"{a3['возраст неизвестен']} по своей причине, без "
              "справочника книга идёт без фильтра вслух")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_report_shows_what_the_money_is_made_of():
    """Отчёт книги обязан называть концентрацию, а не только итог.

    Колонки «без лучшего имени», «без 3 лучших дней» и «просадка без
    худшего дня» стояли только у длинных книг: правила короткой стороны
    объявлялись по числам, ни разу не проверенным на вопрос «не сделан
    ли плюс тремя днями». Кусается на подставной книге, у которой три
    дня несут ВСЁ: без них итог обязан уйти в минус и это обязано быть
    видно в строке таблицы, а не только в json.
    """
    D = 86400
    t0 = 1_767_225_600
    rows = []
    for i in range(10):                       # десять тощих дней
        rows.append({"dep": 10000, "rules": R.RULES, "sym": f"T{i}USDT",
                     "at": t0 + i * D, "exit_ts": t0 + i * D + 60,
                     "usd": -1.0, "written_at": t0 + i * D + 120,
                     "lev": 4.0, "margin": 25.0, "pnl_frac": -0.04,
                     "exit": "срок"})
    for j in range(3):                        # три жирных, разными именами
        for k in range(4):
            rows.append({"dep": 10000, "rules": R.RULES,
                         "sym": f"F{j}{k}USDT",
                         "at": t0 + (20 + j) * D,
                         "exit_ts": t0 + (20 + j) * D + 60,
                         "usd": 5.0, "written_at": t0 + (20 + j) * D + 120,
                         "lev": 4.0, "margin": 25.0, "pnl_frac": 0.2,
                         "exit": "тейк"})
    st = RP._stats(rows, 10000.0)
    assert abs(st["usd"] - 50.0) < 1e-6, st["usd"]
    assert abs(st["usd_wo_top3d"] + 10.0) < 1e-6, st["usd_wo_top3d"]
    s = {"books": {f"optimal_h:10000": {"deposit": 10000.0,
                                        "ruler": "optimal_h", "all": st,
                                        "n_forward": 0,
                                        "n_restored": len(rows)}},
         "computed_at": "2026-09-11 10:00", "legs": len(rows),
         "rulers": list(R.H24_ORDER), "ages": {},
         # свод, который пишет ЖИВОЙ прогон: версия правил, срок и
         # сигнал — без них отчёт не собирается вовсе
         "rules": RP.rules_snapshot(), "hold_h": R.H24_HOLD_H,
         "positions": len(rows), "secs": 1.0}
    txt = S.report(s)
    assert "$ без 3 лучших дней" in txt, txt[:400]
    assert "просадка без худшего дня" in txt, txt[:400]
    assert "-10.00" in txt, [x for x in txt.splitlines() if "optimal_h" in x]
    # колонки обязаны сойтись числом: markdown склеивает столбцы молча
    head, sep, rows_ = TP.table_shape(txt, "без 3 лучших дней")
    assert head == sep and set(rows_) == {head}, (head, sep, rows_)
    print(f"ok  отчёт коротких книг называет концентрацию: итог "
          f"{st['usd']:+.0f} $, без 3 лучших дней {st['usd_wo_top3d']:+.0f} $, "
          f"просадка {100 * st['max_dd']:.1f} % → без худшего дня "
          f"{100 * st['max_dd_wo_worst']:.1f} %")


if __name__ == "__main__":
    test_cache_signature_follows_the_cell_and_the_hold()
    test_legs_come_from_both_arms_in_time_order()
    test_needs_replay_asks_for_new_and_open_positions()
    test_family_writes_its_own_journal_and_gates_the_aggressive_book()
    test_age_rule_of_the_book_bites_and_counts_the_unknown_apart()
    test_floor_is_per_book_and_the_cache_knows_it()
    test_replay_gives_each_ruler_its_own_floor()
    test_report_shows_what_the_money_is_made_of()
    print("\nвсе 8 проверок прошли")
