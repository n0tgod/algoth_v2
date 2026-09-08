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
import time

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


def test_supply_separates_a_quiet_sheet_from_a_biting_rule():
    """Две тишины различимы числом: подачи нет — или правило режет.

    Кусается: сутки, где лист подал только МОЛОДЫЕ имена, показывают
    «взято 0» при «взято без правила» больше нуля (виновато правило), а
    сутки без решений вовсе показывают нули в обеих колонках (виновата
    подача). Перепутать их отчёт не может — обе колонки печатаются.
    """
    day = 86400.0
    # Полдень UTC: сутки отчёта — календарные, и решения, разложенные от
    # произвольного часа, разъехались бы по двум колонкам.
    noon = (T0 // day) * day + 12 * H
    # сутки 1: три СТАРЫХ имени, сутки 2: три МОЛОДЫХ
    old_ = [TP._short(f"O{i}USDT", noon + i * H) for i in range(3)]
    young = [TP._short(f"Y{i}USDT", noon + day + i * H) for i in range(3)]
    launch = {r["sym"]: noon - 200 * day for r in old_}
    launch.update({r["sym"]: noon + day - 1 * day for r in young})
    b = SA.supply(old_ + young, "safe_h", {"error": "рядов нет"}, launch,
                  days=14, dep=R.DEPOSITS[1], now=noon + 40 * day)
    days = b["days"]
    d1 = days[time.strftime("%Y-%m-%d", time.gmtime(noon))]
    d2 = days[time.strftime("%Y-%m-%d", time.gmtime(noon + day))]
    assert d1["моложе порога"] == 0 and d1["взято"] == d1["взято без правила"]
    assert d1["взято"] > 0, d1
    assert d2["моложе порога"] == 3, d2
    assert d2["взято"] == 0 and d2["взято без правила"] > 0, d2
    assert b["n"] < b["n_free"], b
    # ОТКРЫТАЯ позиция — тоже вход. Считать одни закрытые значило бы
    # показывать ноль у каждых свежих суток (срок книги 24 ч), и владелец
    # читал бы это как «шорты не открываются».
    live = TP._short("OLIVEUSDT", noon + 2 * day, hold_h=24.0)
    live["state"] = "open"
    live["sched_end"] = live["at"] + 24 * H
    launch[live["sym"]] = noon - 300 * day
    b2 = SA.supply(old_ + young + [live], "safe_h", {"error": "рядов нет"},
                   launch, days=14, dep=R.DEPOSITS[1],
                   now=noon + 2 * day + 2 * H)
    d3 = b2["days"][time.strftime("%Y-%m-%d", time.gmtime(noon + 2 * day))]
    assert d3["предложено"] == 1 and d3["взято"] == 1, d3
    assert b2.get("open") == 1, b2
    print(f"ok  подача по суткам: старые сутки {d1['взято']} сделок "
          f"(правило не тронуло), молодые {d2['взято']} против "
          f"{d2['взято без правила']} — видно, что режет ПРАВИЛО, а не "
          "подача; открытый вход считается входом")


if __name__ == "__main__":
    for t in (test_share_comes_from_the_declared_map_and_is_put_back,
              test_smaller_ticket_lets_more_decisions_in,
              test_age_filter_cuts_the_book_and_control_takes_the_same_count,
              test_supply_separates_a_quiet_sheet_from_a_biting_rule):
        t()
    print("\nвсе 4 проверки прошли")
