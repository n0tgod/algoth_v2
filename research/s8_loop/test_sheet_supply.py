#!/usr/bin/env python3
"""Проверки подачи листа: гейты считаются той же геометрией, что у ног;
строка с переставленным знаком пути в счёт подачи не идёт; разделение
причин берёт края окна, а не лучший день; короткого окна не хватает — и
это сказано причиной, а не нулём."""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sheet_supply as SS                                    # noqa: E402

DAY = 86400.0
T0 = 1786320000.0                     # 2026-08-09 12:00 UTC


def _row(sym, fwd, mae, mfe, px=100.0):
    return {"sym": sym, "fwd": fwd, "px": px, "mae": mae, "mfe": mfe,
            "fwd_z": fwd / 30.0, "beta": 1.1, "adverse_of": "mae_4h"}


def _sheet(path, recs):
    with open(path, "w", encoding="utf-8") as f:
        for at, arms in recs:
            f.write(json.dumps({
                "hour": "2026-08-09-12", "written_at": round(at, 1),
                "train_seq": 7, "min_edge_bp": 33.0, "min_rr": 2.0,
                "arms": arms}, ensure_ascii=False) + "\n")


def test_gates_are_counted_by_the_same_geometry_as_the_legs():
    tmp = tempfile.mkdtemp(prefix="supply-")
    p = os.path.join(tmp, "sheets.jsonl")
    rows = [_row("AAAUSDT", 50.0, -20.0, 60.0),      # край и RR 3 → оба
            _row("BBBUSDT", 20.0, -20.0, 60.0),      # RR есть, края нет
            _row("CCCUSDT", 50.0, -50.0, 60.0),      # край, RR 1.2 → низкий
            _row("DDDUSDT", 50.0, 20.0, 60.0),       # знак пути переставлен
            {"sym": "EEEUSDT", "fwd": 50.0, "px": 5.0}]      # пути нет вовсе
    try:
        _sheet(p, [(T0, {"gbm": rows, "nn": rows[:1]})])
        s = SS.run(path=p, log=lambda *a: None)
        day = sorted(s["days"])[0]
        g = s["days"][day]["gbm"]
        assert g["rows"] == 5 and g["with_path"] == 3, g
        assert (g["edge"], g["rr"], g["both"], g["lo"]) == (2, 2, 1, 1), g
        assert g["fwd_median"] == 50.0 and g["rr_median"] == 3.0, g
        assert s["days"][day]["nn"]["both"] == 1
        print(f"ok  подача: строк {g['rows']}, с путём {g['with_path']} "
              "(переставленный знак и строка без пути в счёт не идут), "
              f"под гейтом книг {g['both']}, низкий RR {g['lo']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_diagnosis_compares_the_edges_of_the_window_not_the_best_day():
    tmp = tempfile.mkdtemp(prefix="supply-")
    p = os.path.join(tmp, "sheets.jsonl")
    recs = []
    for i in range(16):
        # деревья: строк столько же, прогноз сдулся во второй половине;
        # сеть: без изменений. В СЕРЕДИНЕ окна — «лучший день» вдесятеро
        # по числу строк: он не должен попасть ни в одну из границ.
        big = 60.0 if i < 8 else 12.0
        gbm = [_row(f"G{j}USDT", big, -20.0, big + 10.0) for j in range(4)]
        nn = [_row(f"N{j}USDT", 60.0, -20.0, 70.0) for j in range(4)]
        if i == 8:
            gbm = gbm * 10
        recs.append((T0 + i * DAY, {"gbm": gbm, "nn": nn}))
    try:
        _sheet(p, recs)
        s = SS.run(path=p, log=lambda *a: None)
        d = s["diagnose"]
        assert d["head"][0] == "2026-08-10" and d["tail"][1] == "2026-08-25", d
        g, n = d["arms"]["gbm"], d["arms"]["nn"]
        assert g["rows_head"] == g["rows_tail"] == 28, g   # день ×10 вне краёв
        assert g["fwd_med_head"] == 60.0 and g["fwd_med_tail"] == 12.0, g
        assert g["both_head"] == 28 and g["both_tail"] == 0, g
        assert n["fwd_med_head"] == n["fwd_med_tail"] == 60.0, n
        txt = SS.report(s)
        assert "| деревья | 28 → 28 | 28 → 0 | 60 → 12 |" in txt, txt[-900:]
        assert "Чего замер НЕ говорит" in txt and "2026-08-10 | деревья" in txt
        print("ok  причины разделяются: у деревьев строк столько же, а "
              "прогноз 60 → 12 и под гейтом 28 → 0; у сети без изменений; "
              "всплеск в середине окна в края не попал")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_short_window_says_why_instead_of_zeros():
    tmp = tempfile.mkdtemp(prefix="supply-")
    p = os.path.join(tmp, "sheets.jsonl")
    try:
        _sheet(p, [(T0 + i * DAY, {"gbm": [_row("AAAUSDT", 50.0, -20.0, 60.0)]})
                   for i in range(3)])
        s = SS.run(path=p, log=lambda *a: None)
        assert "суток 3" in s["diagnose"]["why"], s["diagnose"]
        assert "arms" not in s["diagnose"]
        txt = SS.report(s)
        assert "Разделить причины нечем: суток 3" in txt
        # журнала нет вовсе — тоже причина, а не пустая таблица
        s2 = SS.run(path=os.path.join(tmp, "none.jsonl"), log=lambda *a: None)
        assert s2["days"] == {} and s2["hours"] == 0
        assert "Разделить причины нечем" in SS.report(s2)
        print("ok  короткое окно и отсутствие журнала листов названы "
              "причиной, а не показаны нулями")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_gates_are_counted_by_the_same_geometry_as_the_legs()
    test_diagnosis_compares_the_edges_of_the_window_not_the_best_day()
    test_short_window_says_why_instead_of_zeros()
    print("\nвсе 3 проверки прошли")
