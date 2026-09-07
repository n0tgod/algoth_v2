#!/usr/bin/env python3
"""Проверки книги одной руки.

Кусаются: рука записи определяется ЧИСЛАМИ записи, а не правилом «больший
прогноз» (перестановка чисел переставляет руку); спорное решение, чья
запись в кэше принадлежит чужой руке, попадает в досчёт; книга каждой
руки собирается той же машинерией, что настоящая, и деньги двух рук не
складываются в книгу — каждой дан весь депозит; непригодный кэш — причина
словами, а не пустые таблицы.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import arm_book as AB                                        # noqa: E402
import rules as R                                            # noqa: E402
import run_paper as RP                                       # noqa: E402

H = 3600.0
T0 = 1786320000.0


def _leg(sym, arm, at, fwd, fav, side="long"):
    return {"sym": sym, "arm": arm, "at": at, "fwd": fwd, "fav": fav,
            "side": side, "adv_q": -abs(fwd), "rr": 3.0}


def _rec(sym, at, fwd, fav, pnl, lev=3.0, side="long", hold=24 * H):
    return {"sym": sym, "at": at, "fwd": abs(fwd), "fav_bp": fav,
            "pnl": pnl, "lev": lev, "side": side, "exit": "тейк",
            "exit_ts": at + hold, "sched_end": at + hold,
            "end_ts": at + hold, "state": "closed", "depth": 1,
            "entry_px": 100.0, "exit_px": 101.0, "avg": 100.0,
            "marks": [(int(at) - int(at) % 3600, pnl)],
            "fills": [[at, 100.0, 1.0]]}


def test_arm_of_a_record_comes_from_its_numbers():
    legs = [_leg("AAAUSDT", "gbm", T0, 120.0, 300.0),
            _leg("AAAUSDT", "nn", T0, 400.0, 700.0)]
    idx = AB.legs_index(legs)
    cands = idx[AB.key_of("AAAUSDT", T0)]
    assert AB.match_arm(_rec("AAAUSDT", T0, 120.0, 300.0, 0.1), cands) == ("gbm", None)
    assert AB.match_arm(_rec("AAAUSDT", T0, 400.0, 700.0, 0.1), cands) == ("nn", None)
    # числа записи чужие — рука не выдумывается
    assert AB.match_arm(_rec("AAAUSDT", T0, 999.0, 111.0, 0.1), cands)[1] == "нога не сошлась"
    # ноги нет вовсе
    assert AB.match_arm(_rec("ZZZUSDT", T0, 120.0, 300.0, 0.1), [])[1] == "нет ноги"
    # руки с ОДИНАКОВЫМИ числами неразличимы, и это сказано
    same = AB.legs_index([_leg("BBBUSDT", "gbm", T0, 200.0, 500.0),
                          _leg("BBBUSDT", "nn", T0, 200.0, 500.0)])
    assert AB.match_arm(_rec("BBBUSDT", T0, 200.0, 500.0, 0.1),
                        same[AB.key_of("BBBUSDT", T0)])[1] == "руки неразличимы"
    # сторона входит в сравнение: короткая нога за длинную запись не отвечает
    sh = AB.legs_index([_leg("CCCUSDT", "nn", T0, 120.0, -300.0, side="short")])
    assert AB.match_arm(_rec("CCCUSDT", T0, 120.0, -300.0, 0.1),
                        sh[AB.key_of("CCCUSDT", T0)])[1] == "нет ноги"
    print("ok  рука записи — из её чисел: перестановка чисел переставляет "
          "руку, чужие числа и одинаковые числа названы причиной")


def test_disputed_record_of_the_other_arm_goes_to_the_replay():
    pairs = AB.pairs_of()
    legs = [_leg("AAAUSDT", "gbm", T0, 120.0, 300.0),
            _leg("AAAUSDT", "nn", T0, 400.0, 700.0),
            _leg("BBBUSDT", "gbm", T0 + H, 150.0, 350.0)]
    idx = AB.legs_index(legs)
    cache = {}
    for pr in pairs:
        if (pr[2] if len(pr) > 2 else "long") != "long":
            continue
        cache[(tuple(pr), "AAAUSDT", round(T0, 3))] = _rec("AAAUSDT", T0, 400.0, 700.0, 0.2)
        cache[(tuple(pr), "BBBUSDT", round(T0 + H, 3))] = _rec("BBBUSDT", T0 + H, 150.0, 350.0, 0.1)
    owned, why, disputed = AB.split_cache(cache, idx, log=lambda *a: None)
    assert disputed == {"gbm": 0, "nn": 2}, disputed      # спор достался сети
    need = AB.missing_legs(legs, owned, pairs)
    syms = sorted({(g["sym"], g["arm"]) for g in need})
    assert syms == [("AAAUSDT", "gbm")], syms            # досчитать надо деревья
    assert sum(why.values()) == 0, why
    print(f"ok  спорные решения в кэше достались сети ({disputed['nn']} записи), "
          "и нога деревьев по тому же имени и часу ушла в досчёт")


def test_each_arm_gets_its_own_book_and_the_whole_deposit():
    pairs = [pr for pr in AB.pairs_of()
             if (pr[2] if len(pr) > 2 else "long") == "long"]
    legs, cache = [], {}
    for i in range(80):
        at = T0 + i * H
        arm = "gbm" if i % 2 else "nn"
        pnl = 0.20 if arm == "nn" else 0.05
        legs.append(_leg(f"S{i}USDT", arm, at, 100.0 + i, 300.0 + i))
        for pr in pairs:
            cache[(tuple(pr), f"S{i}USDT", round(at, 3))] = _rec(
                f"S{i}USDT", at, 100.0 + i, 300.0 + i, pnl)
    s = AB.run(legs=legs, cache=cache, log=lambda *a: None)
    assert s["replayed"] == 0 and s["owned"] == len(cache)
    g = s["books"]["gbm"]["optimal"]
    n = s["books"]["nn"]["optimal"]
    assert g["stats"]["n"] == 40 and n["stats"]["n"] == 40, (g["stats"], n["stats"])
    # у каждой руки СВОЙ депозит целиком: итог сети вчетверо больше по
    # доле счёта, а не половина книги
    assert n["final"] > g["final"] > 0, (g["final"], n["final"])
    assert abs(n["final"] / g["final"] - 4.0) < 0.6, (g["final"], n["final"])
    v = AB.verdict(s)
    assert v["optimal"]["winner"] == "nn", v["optimal"]
    assert v["safe_s"]["why"].startswith("сделок меньше 30"), v["safe_s"]
    txt = AB.report(s)
    assert "Чего замер НЕ говорит" in txt and "Сложить два итога нельзя" in txt
    assert "| `optimal` (оптимальная) | сеть |" in txt
    print(f"ok  книга каждой руки собрана отдельно: деревья {g['stats']['n']} "
          f"сделок итог {100 * g['final']:+.2f} %, сеть {n['stats']['n']} "
          f"итог {100 * n['final']:+.2f} %; вердикт — сеть")


def test_memory_guard_stops_the_run_itself():
    said = []
    log = guarded_log = AB.guarded(said.append, limit=100, rss=lambda: 50.0)
    guarded_log("иду")
    assert said == ["иду"], said
    over = AB.guarded(said.append, limit=100, rss=lambda: 1500.0)
    try:
        over("иду дальше")
        raise AssertionError("сторож не сработал")
    except SystemExit as e:
        assert e.code == 3, e
    assert "СТОП: память 1500 МБ" in said[-1], said[-1]
    del log
    print("ok  сторож памяти останавливает прогон сам и говорит число")


def test_unusable_cache_says_why(monkey=None):
    was = RP.read_cache
    try:
        RP.read_cache = lambda *a, **k: ({}, "правила реплея изменились")
        s = AB.run(legs=[_leg("AAAUSDT", "gbm", T0, 120.0, 300.0)],
                   log=lambda *a: None)
        assert s.get("error") and "правила реплея" in s["error"], s
        txt = AB.report(s)
        assert "Замер не состоялся" in txt and "правила реплея" in txt
        assert "Итог книг" not in txt
    finally:
        RP.read_cache = was
    print("ok  непригодный кэш реплея — причина словами, таблиц с нулями нет")


if __name__ == "__main__":
    test_arm_of_a_record_comes_from_its_numbers()
    test_disputed_record_of_the_other_arm_goes_to_the_replay()
    test_each_arm_gets_its_own_book_and_the_whole_deposit()
    test_memory_guard_stops_the_run_itself()
    test_unusable_cache_says_why()
    print("\nвсе 5 проверок прошли")
