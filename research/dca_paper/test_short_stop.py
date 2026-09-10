#!/usr/bin/env python3
"""Проверки замера «пол капитуляции как стоп».

Кусаются: пол ставится на время прогона и ВОЗВРАЩАЕТСЯ обратно (иначе
соседний замер молча стал бы другим замером); ось читается в съеденной
марже той же арифметикой, что печатает отчёт; ранний пол действительно
режет позицию раньше — на тех же барах ядра лестницы; незаявленная
ячейка оси — отказ словами, а не молчаливый пустой прогон.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import short_stop as SS                                       # noqa: E402


def test_axis_reads_as_eaten_margin():
    assert [k for k, _v in SS.FLOORS] == ["f10", "f25", "f50", "f75"]
    assert dict(SS.FLOORS)["f10"] == D2.FLOOR_FRAC, (SS.FLOORS, D2.FLOOR_FRAC)
    assert abs(SS.eaten(0.25) - 0.75) < 1e-12
    assert abs(SS.eaten(0.75) - 0.25) < 1e-12
    print("ok  ось: ячейка f10 равна ДЕЙСТВУЮЩЕМУ полу книги "
          f"({D2.FLOOR_FRAC:g}); 0.75 читается как «съедено 25 % маржи»")


def test_floor_is_put_back_after_the_run():
    was = D2.FLOOR_FRAC
    s = SS.run("f75", legs_=[], log=lambda *a: None,
               ctx={"error": "рядов нет"}, launch={})
    assert s.get("error"), s
    assert D2.FLOOR_FRAC == was, D2.FLOOR_FRAC
    bad = SS.run("нетакой", legs_=[{"sym": "AUSDT"}], log=lambda *a: None,
                 ctx={"error": "рядов нет"}, launch={})
    assert "не объявлена" in (bad.get("error") or ""), bad
    assert D2.FLOOR_FRAC == was, D2.FLOOR_FRAC
    print(f"ok  пол книги после замера на месте ({was:g}); незаявленная "
          "ячейка — отказ словами")


def test_earlier_floor_cuts_the_position_earlier():
    """На тех же барах ранний пол режет раньше и дешевле — ядром лестницы."""
    # шорт 10×: цена идёт ВВЕРХ против позиции, минута за минутой
    entry = 100.0
    bars = [[i * 60.0, entry, entry + i * 1.2, entry - 0.2,
             entry + i * 1.0, 1000.0] for i in range(1, 30)]
    bars = [[0.0, entry, entry, entry, entry, 1000.0]] + bars
    out = {}
    for key, frac in SS.FLOORS:
        r = L.simulate_dca(bars, [entry], [1.0], 1.0, 10.0, 0.02,
                           take_px=None, floor_frac=frac, side="short")
        out[key] = (r.get("exit"), r.get("exit_ts"), r.get("pnl_frac"))
    late, early = out["f10"], out["f75"]
    assert early[0] in ("пол", "ликвидация") and late[0] in ("пол",
                                                             "ликвидация")
    assert early[1] < late[1], out            # ранний стоп срабатывает раньше
    assert early[2] > late[2], out            # и теряет меньше маржи
    print(f"ok  ранний пол режет раньше: 0.75 → {early[0]} на "
          f"{early[1]:.0f} с при {100 * early[2]:.0f} % маржи, "
          f"0.10 → {late[0]} на {late[1]:.0f} с при {100 * late[2]:.0f} %")


def test_report_names_the_missing_cells():
    s = {"cells": {"f10": {}}, "computed_at": "2026-09-10 15:00",
         "axis": [{"key": "f10", "value": 0.10}],
         "axis_all": [{"key": k, "value": v} for k, v in SS.FLOORS],
         "cell_at": {"f10": "2026-09-10 15:00"}, "hold_h": 24}
    txt = SS.report(s)
    assert "Ось посчитана не целиком" in txt, txt[:300]
    for v in ("0.25", "0.5", "0.75"):
        assert v in txt, v
    print("ok  отчёт называет ячейки, которых ещё нет")


def test_parallel_cells_do_not_lose_each_other():
    """Ячейки оси считаются параллельно — артефакт обязан пережить это.

    Кусается на самой гонке: два процесса сливают СВОЮ ячейку в один
    артефакт одновременно. Без замка второй читает файл до записи
    первого и затирает его ячейку — молча, потому что по отдельности
    каждый отработал верно.
    """
    import json
    import multiprocessing as mp
    import tempfile
    import short_grid as G

    def one(outdir, key, val, ready, go):
        G.R.OUT = outdir
        ready.put(key)
        go.wait()
        s = {"cells": {key: {"v": val}}, "computed_at": f"дата-{key}"}
        G.merge_and_write(s, "ось", [(k, v) for k, v in SS.FLOORS],
                          lambda x: "отчёт", log=lambda *a: None)

    with tempfile.TemporaryDirectory() as td:
        ctx = mp.get_context("fork")
        ready, go = ctx.Queue(), ctx.Event()
        ps = [ctx.Process(target=one, args=(td, k, v, ready, go))
              for k, v in (("f50", 0.5), ("f75", 0.75))]
        for p_ in ps:
            p_.start()
        for _ in ps:
            ready.get(timeout=30)
        go.set()
        for p_ in ps:
            p_.join(timeout=60)
        with open(os.path.join(td, "ось.json"), encoding="utf-8") as f:
            got = json.load(f)
    assert set(got.get("cells") or {}) == {"f50", "f75"}, got.get("cells")
    assert set(got.get("cell_at") or {}) == {"f50", "f75"}, got.get("cell_at")
    print(f"ok  параллельные ячейки не теряют друг друга: в артефакте "
          f"{sorted(got['cells'])}")


if __name__ == "__main__":
    for t in (test_axis_reads_as_eaten_margin,
              test_floor_is_put_back_after_the_run,
              test_earlier_floor_cuts_the_position_earlier,
              test_report_names_the_missing_cells,
              test_parallel_cells_do_not_lose_each_other):
        t()
    print("\nвсе 5 проверок прошли")
