#!/usr/bin/env python3
"""Проверки пробы «правила общего счёта на отдельных коротких книгах».

Кусаются: доля билета берётся из ОБЪЯВЛЕННОЙ карты правил и возвращается
на место (проба не оставляет книгам чужой билет); меньшая доля даёт
меньший билет и пускает в книгу больше решений; фильтр возраста режет
состав, а контроль берёт столько же решений; замер не пишет в журнал
книг и не трогает карту правил после себя.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import short_age as SA                                        # noqa: E402
import test_pair as TP                                        # noqa: E402

H = 3600.0
DAY = 86400.0
T0 = TP.T0
DEP = R.DEPOSITS[1]


def _shorts(n=8, at=None):
    return [TP._short(f"S{i}USDT", (at or T0) + i * H) for i in range(n)]


def test_share_comes_from_the_declared_map_and_is_put_back():
    recs = _shorts()
    before = dict(R.SHORT_SHARE)
    full = SA.cell(recs, "safe_h", DEP, {"error": "рядов нет"},
                   share=1.0, now=T0 + 200 * H)
    quarter = SA.cell(recs, "safe_h", DEP, {"error": "рядов нет"},
                      share=0.25, now=T0 + 200 * H)
    assert dict(R.SHORT_SHARE) == before, R.SHORT_SHARE
    assert quarter["ticket"] < full["ticket"], (quarter, full)
    # билет вчетверо меньше — но не ниже биржевого пола
    assert quarter["ticket"] >= R.floor_of("safe_h"), quarter
    print(f"ok  доля билета из карты правил: 1.0× → ${full['ticket']:g}, "
          f"0.25× → ${quarter['ticket']:g}; карта после пробы не тронута")


def test_smaller_ticket_lets_more_decisions_in():
    # Решения стоят ОДНОВРЕМЕННО и их больше, чем мест: полному билету
    # касса откажет части, четвертному — нет. Это и есть причина мерить
    # долю прогоном, а не умножать деньги на 0.25.
    recs = [TP._short(f"S{i}USDT", T0, hold_h=24.0) for i in range(120)]
    full = SA.cell(recs, "safe_h", DEP, {"error": "рядов нет"},
                   share=1.0, now=T0 + 400 * H)
    quarter = SA.cell(recs, "safe_h", DEP, {"error": "рядов нет"},
                      share=0.25, now=T0 + 400 * H)
    assert full["n"] and quarter["n"], (full, quarter)
    assert full["no_cash"] > 0, full
    assert quarter["n"] > full["n"], (quarter["n"], full["n"])
    print(f"ok  мелкий билет пускает больше решений: {full['n']} → "
          f"{quarter['n']} сделок при отказах кассы {full['no_cash']} → "
          f"{quarter['no_cash']} (касса, а не умножение)")


def test_age_filter_cuts_the_book_and_control_takes_the_same_count():
    launch = {f"S{i}USDT": T0 - (1.0 if i < 4 else 90.0) * DAY
              for i in range(8)}
    with tempfile.TemporaryDirectory() as td:
        s = SA.run(cache=None, keys=["safe_h"], days=(0, 7), shares=(1.0,),
                   deps=[DEP], seeds=3, launch=launch,
                   ctx={"error": "рядов нет"}, now=T0 + 200 * H,
                   log=lambda *a: None,
                   **{})
        assert s.get("error"), "без кэша проба обязана отказаться словами"
        assert sorted(os.listdir(td)) == [], "написал лишнее"
    cache = TP._caches(_shorts(), _shorts())[1]
    s = SA.run(cache=cache, keys=["safe_h"], days=(0, 7), shares=(1.0,),
               deps=[DEP], seeds=3, launch=launch,
               ctx={"error": "рядов нет"}, now=T0 + 200 * H,
               log=lambda *a: None)
    base = s["cells"][f"safe_h|0|1.0|{int(DEP)}"]
    cut = s["cells"][f"safe_h|7|1.0|{int(DEP)}"]
    assert base["kept"] == 8 and cut["kept"] == 4, (base, cut)
    assert cut["drops"]["моложе порога"] == 4, cut["drops"]
    ctl = s["cells"]["safe_h|7|random"]
    assert ctl["seeds"] == 3 and ctl["kept"] == 4, ctl
    assert ctl["beat_usd"] is not None
    txt = SA.report(s)
    assert "контроль" in txt.lower() and "доля билета" in txt
    print(f"ok  фильтр возраста: {base['kept']} решений → {cut['kept']}; "
          f"контроль берёт столько же на {ctl['seeds']} зёрнах; журнал "
          "книг не тронут")


if __name__ == "__main__":
    for t in (test_share_comes_from_the_declared_map_and_is_put_back,
              test_smaller_ticket_lets_more_decisions_in,
              test_age_filter_cuts_the_book_and_control_takes_the_same_count):
        t()
    print("\nвсе 3 проверки прошли")
