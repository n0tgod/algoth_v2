#!/usr/bin/env python3
"""Поиск ТВХ по состоянию (U4c): калибровочная пара — подсаженный параметр
(вход, когда доля лонгов упала ниже порога, даёт плюс, остальные часы —
минус) находится и держит на проверочной половине в обе стороны, а на
перемешанных параметрах отбор молчит; первый час по условиям и окно;
таблица исходов — подставная."""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import entry_search as ES                                    # noqa: E402


def synth(n=600, seed=3, planted=True):
    rng = np.random.default_rng(seed)
    K = ES.KMAX + 1
    names = ["crowd_bybit", "noise_a", "noise_b"]
    F = rng.uniform(0, 1, size=(n, K, len(names)))
    O = rng.normal(-0.01, 0.05, size=(n, K))
    if planted:
        good = F[:, :, 0] <= 0.25                      # толпа ушла в шорт — вход выгоден
        O = np.where(good, O + 0.12, O)
    at = np.arange(n) * 3600.0
    return names, F, O, at


def test_exit_cells_and_shortest_stop():
    """Таблица O[сигнал, k, ячейка выхода] (§11.9): подсаженный выигрыш живёт
    в паре «состояние + стоп 3 %» — отбор находит пару, мера цели печатает
    стоп 3 % как самый короткий держащийся; без подсадки — пусто; ячейка
    книги — та же, что у книги (`run_short.CELL`), без политики."""
    rng = np.random.default_rng(11)
    n, K = 600, ES.KMAX + 1
    names = ["crowd_bybit", "noise_a"]
    F = rng.uniform(0, 1, size=(n, K, len(names)))
    exits = [ES.BOOK_EXIT, "s3:t2:book", "s1:t2:book"]
    O = rng.normal(-0.01, 0.05, size=(n, K, len(exits)))
    good = F[:, :, 0] <= 0.25
    O[:, :, 1] = np.where(good, O[:, :, 1] + 0.12, O[:, :, 1])    # выигрыш — только со стопом 3 %
    at = np.arange(n) * 3600.0
    f1, f2 = ES.search(F, O, names, at, seed=1, exits=exits)
    assert f1["held"] and f2["held"] and f1["rule"]["exit"] == "s3:t2:book", (f1["rule"], f2["rule"])
    assert ES.shortest_stop(f1, f2) == "3", (f1["by_stop"].keys(), ES.shortest_stop(f1, f2))
    assert not f1["by_stop"]["1"]["held"] or not f2["by_stop"]["1"]["held"], "стоп 1 % без подсадки не держится"
    r = ES.run(log=lambda *a: None, table={"names": names, "F": F, "O": O, "at": at, "n": n, "exits": exits})
    assert r["shortest_stop"] == "3" and "Самый короткий стоп, который держится:** 3 %" in ES.report(r)
    be = {x["exit"]: x for x in r["book_exits"]}
    assert set(be) == set(exits) and be["s3:t2:book"]["all"] > be[ES.BOOK_EXIT]["all"], be
    assert "Вход книги (час сигнала) с каждым выходом" in ES.report(r)
    O2 = rng.normal(-0.01, 0.05, size=(n, K, len(exits)))
    g1, g2 = ES.search(F, O2, names, at, seed=2, exits=exits)
    assert ES.shortest_stop(g1, g2) is None, "на шуме короткого стопа нет"
    import run_short as S                                     # noqa: E402
    cell, pol = ES.exit_cell(ES.BOOK_EXIT)
    assert cell == S.CELL and pol is None, (cell, S.CELL)
    c2, p2 = ES.exit_cell("s2:t1:eq")
    assert c2[3] == "t1" and p2 == {"adds": [], "stop_frac": 0.02, "lev_risk": True} and c2[0] != S.CELL[0]
    assert len(ES.EXITS) == 33 and len({ES.exit_cell(e["name"])[0][0] for e in ES.EXITS}) == 33
    print("ok  стоп и тейк в таблице: пара «состояние + стоп 3 %» найдена и держит, мера цели — 3 %; на шуме — пусто; "
          "ячейка книги = run_short.CELL")


def main():
    test_exit_cells_and_shortest_stop()
    names, F, O, at = synth()
    rule = {"when": [{"field": "crowd_bybit", "op": "<=", "value": 0.25}], "W": 3}
    ks = ES.first_k(F, names, rule)
    i = int(np.where(ks > 0)[0][0])
    assert F[i, ks[i], 0] <= 0.25 and all(F[i, k, 0] > 0.25 for k in range(ks[i])), "первый час по условию"
    assert all(k <= 3 for k in ks), "окно W"
    f1, f2 = ES.search(F, O, names, at, seed=1)
    assert f1["held"] and f2["held"], (f1.get("rule"), f1.get("test_mean"), f1.get("p_random_hour"), f2.get("rule"))
    assert f1["rule"]["when"][0]["field"] == "crowd_bybit" and f2["rule"]["when"][0]["field"] == "crowd_bybit"
    c1, c2 = ES.search(ES.shuffled(F, 9), O, names, at, seed=2)
    assert not (c1.get("held") and c2.get("held")), "на перемешанных параметрах отбор молчит"
    n2, F2, O2, at2 = synth(planted=False, seed=5)
    g1, g2 = ES.search(F2, O2, n2, at2, seed=3)
    assert not (g1.get("held") and g2.get("held")), "на шуме отбор молчит"
    r = ES.run(log=lambda *a: None, table={"names": names, "F": F, "O": O, "at": at, "n": len(at)})
    assert r["procedure_holds"] and r["candidate"]["rule"]["when"][0]["field"] == "crowd_bybit", r.get("candidate")
    assert "держит" in ES.report(r) or "**да**" in ES.report(r)
    print("ok  поиск ТВХ: подсаженный параметр найден и держит на проверке в обе стороны; перемешанные и шум — молчат")
    # --from-table: таблица, сохранённая полным прогоном, читается тем же видом
    import tempfile
    pth = os.path.join(tempfile.mkdtemp(), "t.npz")
    np.savez_compressed(pth, F=F, O=O, at=at, names=np.array(names))
    t = ES.load_table(pth)
    assert t["names"] == names and t["n"] == len(at) and np.array_equal(t["O"], O, equal_nan=True)
    r2 = ES.run(log=lambda *a: None, table=t)
    assert r2["fold_1to2"]["rule"] == r["fold_1to2"]["rule"], "та же таблица — тот же отбор"
    assert "error" in ES.load_table(pth + ".нет"), "нет таблицы — названная ошибка, не пустой поиск"
    planted = {"when": [{"field": "crowd_bybit", "op": "<=", "value": 0.25}], "W": 3}
    ms = ES.model_scores(F, O, names, at, [planted, {"when": [{"field": "нет_поля", "op": ">=", "value": 1}], "W": 3}])
    assert all(h["gain"] > 0 for h in ms[0]["halves"]) and ms[1]["why"], ms
    assert "Правила модели" in ES.report(dict(r, model=ms))
    print("ok  поиск ТВХ по сохранённой таблице: тот же отбор; без таблицы — ошибка с причиной")
    print("\nвсе 3 проверки прошли")


if __name__ == "__main__":
    main()
