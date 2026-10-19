#!/usr/bin/env python3
"""Слежение за счётом: первый срез молчит; позиция, прожившая меньше такта,
названа честно; закрытая без открытых — «из ниоткуда»; приращение итога
без новых сделок — «пересчёт»; исчезнувшая открытая и открытая задним
числом названы; состояние и лог пишутся; подделка — литералы."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import account_watch as AW                                   # noqa: E402

T0 = 1_792_396_800.0  # 2026-10-19 08:00 UTC


def summary(usd, n, trades, open_):
    # закрытые — служебным полем `_closed` свода, как его пишет `summarize`
    return {"books": {"pair_optimal_g2:100": {"all": {"usd": usd, "n": n},
                                               "open": {"positions": open_}}},
            "_closed": {"pair_optimal_g2:100": {AW.pos_key(t): t["usd"] for t in trades}}}


def test_watch_names_every_jump():
    with tempfile.TemporaryDirectory() as d:
        log = []
        s1 = summary(3741.19, 324, [{"sym": "SANDUSDT", "at": T0 - 90000, "usd": 18.94}],
                     [{"sym": "ARIAUSDT", "at": T0 - 8 * 3600, "mark_usd": 300.0, "margin": 1271.7},
                      {"sym": "SIRENUSDT", "at": T0 - 3600, "mark_usd": 30.0, "margin": 1274.7}])
        b1 = AW.check(s1, "pair", now=T0 + 1800, watch_dir=d, log=log.append)
        assert "_closed" not in s1, "служебное поле закрытых в артефакт идти не должно"
        assert b1["n"] == 0 and b1["prev_at"] is None and b1["cells"] == 1, "первый срез — находок нет"
        assert os.path.exists(os.path.join(d, "pair.json")) and not os.path.exists(os.path.join(d, "log.jsonl"))
        # второй прогон: CT (вход 08:00, до прошлого прогона 08:30) закрылась, в открытых её не было;
        # итог упал ровно на неё; SIREN пропала из открытых без закрытия; LATE открыта задним числом
        s2 = summary(3741.19 - 560.19, 325,
                     [{"sym": "SANDUSDT", "at": T0 - 90000, "usd": 18.94}, {"sym": "CTUSDT", "at": T0, "usd": -560.19}],
                     [{"sym": "ARIAUSDT", "at": T0 - 8 * 3600, "mark_usd": 306.0, "margin": 1271.7},
                      {"sym": "LATEUSDT", "at": T0 - 5 * 3600, "mark_usd": 1.0, "margin": 10.0}])
        b2 = AW.check(s2, "pair", now=T0 + 2940, watch_dir=d, log=log.append)
        kinds = sorted(x["kind"] for x in b2["findings"])
        assert kinds == ["closed_unseen", "open_late", "open_vanished"], kinds
        cu = next(x for x in b2["findings"] if x["kind"] == "closed_unseen")
        assert cu["pos"] == f"CTUSDT:{int(T0)}" and "не взяла касса" in cu["why"], cu
        assert all(x["cell"] == "pair_optimal_g2:100" for x in b2["findings"])
        assert len(log) == 3 and os.path.exists(os.path.join(d, "log.jsonl"))
        # третий прогон: позиция вошла ПОСЛЕ прошлого прогона и уже закрыта — честная короткая жизнь;
        # плюс итог вырос на 100 $ без новых сделок — пересчёт
        s3 = summary(3741.19 - 560.19 - 20.0 + 100.0, 326,
                     [{"sym": "CTUSDT", "at": T0, "usd": -560.19}, {"sym": "FASTUSDT", "at": T0 + 3600, "usd": -20.0}],
                     [{"sym": "ARIAUSDT", "at": T0 - 8 * 3600, "mark_usd": 306.0, "margin": 1271.7},
                      {"sym": "LATEUSDT", "at": T0 - 5 * 3600, "mark_usd": 1.0, "margin": 10.0}])
        b3 = AW.check(s3, "pair", now=T0 + 4500, watch_dir=d, log=log.append)
        kinds = sorted(x["kind"] for x in b3["findings"])
        assert kinds == ["closed_unseen", "recount"], kinds
        fast = next(x for x in b3["findings"] if x["kind"] == "closed_unseen")
        assert "меньше одного такта" in fast["why"]
        rc = next(x for x in b3["findings"] if x["kind"] == "recount")
        assert abs(rc["gap_usd"] - 100.0) < 0.01 and rc["new_closed"] == 1, rc
        assert b3["day"]["n"] == 5 and b3["day"]["by_kind"]["closed_unseen"] == 2
        lat = json.load(open(os.path.join(d, "latest.json"), encoding="utf-8"))
        assert lat["n"] == 2 and lat["day"]["n"] == 5
        # четвёртый: ничего не изменилось — тишина
        b4 = AW.check(s3, "pair", now=T0 + 5400, watch_dir=d, log=log.append)
        assert b4["n"] == 0 and b4["prev_at"] == T0 + 4500
    print("ok  слежение: короткая жизнь и «из ниоткуда» различены, пересчёт истории назван суммой, исчезнувшая и поздняя открытые названы")


if __name__ == "__main__":
    test_watch_names_every_jump()
    print("\nвсе 1 проверки прошли")
