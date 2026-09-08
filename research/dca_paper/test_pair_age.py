#!/usr/bin/env python3
"""Проверки фильтра по возрасту имени.

Кусаются: возраст считается на МОМЕНТ РЕШЕНИЯ, а не на сегодня; имя без
даты листинга не проходит фильтр и считается ОТДЕЛЬНОЙ причиной (молчаливое
превращение «неизвестно» в отказ и создало ложный результат гейта по
ставке); порог 0 не отсекает ничего; контроль берёт ровно столько же
решений, сколько оставляет порог; замер не пишет в журнал книг.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import pair_age as PA                                         # noqa: E402
import test_pair as TP                                        # noqa: E402

H = 3600.0
DAY = 86400.0
T0 = TP.T0


def _launch(**kw):
    return {k: T0 - v * DAY for k, v in kw.items()}


def test_age_is_measured_at_the_moment_of_the_decision():
    launch = _launch(OLDUSDT=100.0, NEWUSDT=2.0)
    assert abs(PA.age_days(launch, "OLDUSDT", T0) - 100.0) < 1e-6
    assert abs(PA.age_days(launch, "NEWUSDT", T0) - 2.0) < 1e-6
    # решение позже — имя старше; на сегодня возраст был бы другим
    assert abs(PA.age_days(launch, "NEWUSDT", T0 + 5 * DAY) - 7.0) < 1e-6
    assert PA.age_days(launch, "НЕТУUSDT", T0) is None
    print("ok  возраст берётся на момент решения, а не на сегодня; без "
          "даты листинга — не число, а None")


def test_unknown_age_is_its_own_refusal():
    launch = _launch(OLDUSDT=100.0, NEWUSDT=2.0)
    shorts = [TP._short("OLDUSDT", T0), TP._short("NEWUSDT", T0),
              TP._short("XXXUSDT", T0)]
    keep, why = PA.pick(shorts, launch, 7)
    assert [r["sym"] for r in keep] == ["OLDUSDT"], keep
    assert why["моложе порога"] == 1 and why["возраст неизвестен"] == 1, why
    # порог 0 — фильтра нет вовсе, даже у имени без даты
    keep0, why0 = PA.pick(shorts, launch, 0)
    assert len(keep0) == 3 and why0["возраст неизвестен"] == 0, (keep0, why0)
    print(f"ok  отказ «моложе порога» ({why['моложе порога']}) и «возраст "
          f"неизвестен» ({why['возраст неизвестен']}) — разные числа; "
          "порог 0 не отсекает никого")


def test_control_takes_the_same_count():
    launch = _launch(**{f"S{i}USDT": (1.0 if i % 2 else 90.0)
                        for i in range(10)})
    shorts = [TP._short(f"S{i}USDT", T0) for i in range(10)]
    keep, _w = PA.pick(shorts, launch, 30)
    rnd, why = PA.pick(shorts, launch, 30, n_random=len(keep))
    assert len(keep) == 5 and len(rnd) == 5, (len(keep), len(rnd))
    assert why["контроль размера"] == 5, why
    assert {r["sym"] for r in rnd} != {r["sym"] for r in keep}, (rnd, keep)
    print(f"ok  контроль берёт столько же ({len(rnd)}), но другой состав")


def test_end_to_end_reads_launches_and_writes_no_journal():
    longs = [TP._long(f"L{i}USDT", T0 + i * H) for i in range(6)]
    shorts = [TP._short(f"S{i}USDT", T0 + i * H) for i in range(6)]
    lc, sc = TP._caches(longs, shorts)
    launch = {f"S{i}USDT": T0 - (1.0 if i < 3 else 90.0) * DAY
              for i in range(6)}
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "instruments.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({k: {"launch_time": str(int(v * 1000))}
                       for k, v in launch.items()}, f)
        got = PA.launches(p)
        assert set(got) == set(launch), got
        s = PA.run(dep=R.DEPOSITS[1], long_cache=lc, short_cache=sc,
                   keys=["pair_safe"], days=(0, 30), seeds=3,
                   launch=got, ctx={"error": "рядов нет"},
                   now=T0 + 200 * H, log=lambda *a: None)
        assert sorted(os.listdir(td)) == ["instruments.json"], "написал лишнее"
        base = s["cells"]["pair_safe|0"]
        cut = s["cells"]["pair_safe|30"]
        assert base["kept"] == 6 and cut["kept"] == 3, (base, cut)
        ctl = s["cells"]["pair_safe|30|random"]
        assert ctl["seeds"] == 3 and ctl["kept"] == 3, ctl
        assert ctl["beat_usd"] is not None
        txt = PA.report(s)
        assert "возраст неизвестен" in txt and "бьют фильтр" in txt
        print(f"ok  прогон целиком: без фильтра {base['kept']} решений, "
              f"порог 30 сут оставляет {cut['kept']}, контроль на "
              f"{ctl['seeds']} зёрнах; журнал книг не тронут")


if __name__ == "__main__":
    for t in (test_age_is_measured_at_the_moment_of_the_decision,
              test_unknown_age_is_its_own_refusal,
              test_control_takes_the_same_count,
              test_end_to_end_reads_launches_and_writes_no_journal):
        t()
    print("\nвсе 4 проверки прошли")
