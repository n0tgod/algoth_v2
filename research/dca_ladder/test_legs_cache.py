#!/usr/bin/env python3
"""Кэш ног листа (`run_d6.gated_legs`, 15.10): второй вызов читает кэш, не
лист; изменённый лист — пересчёт; гейт применяется ПОСЛЕ кэша (кэш один
на стороны); подделка подписи кусается.

    .venv/bin/python research/dca_ladder/test_legs_cache.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_d2 as D2                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402


def sheet_line(hour, sym, fwd, px=1.0):
    return json.dumps({"hour": hour, "written_at": time.time(), "arms": {"nn": [
        {"sym": sym, "fwd": fwd, "px": px, "mae": -40, "mfe": 120, "mae_m": -30, "fz": 2.0,
         "stop_bp": 60, "rr": 3.0}]}})


def main():
    d = tempfile.mkdtemp()
    sheets = os.path.join(d, "sheets.jsonl")
    with open(sheets, "w", encoding="utf-8") as f:
        f.write(sheet_line("2026-10-14-10", "AUSDT", 90.0) + "\n")
        f.write(sheet_line("2026-10-14-10", "BUSDT", -90.0) + "\n")
    cache = os.path.join(d, "legs.pkl")
    was = D2.SHEETS
    D2.SHEETS = sheets
    logs = []
    try:
        a = D6.gated_legs(side=None, log=logs.append, cache=cache)
        assert os.path.exists(cache) and not any("из кэша" in m for m in logs), logs
        n = len(a)
        assert n >= 1, "лист из двух строк дал ноль ног — фикстура не похожа на живую"
        logs.clear()
        b = D6.gated_legs(side=None, log=logs.append, cache=cache)
        assert any("из кэша" in m for m in logs), logs
        assert [(g["sym"], g["at"]) for g in a] == [(g["sym"], g["at"]) for g in b]
        # гейт стороны — после кэша: длинные из того же кэша
        logs.clear()
        longs = D6.gated_legs(side="long", log=logs.append, cache=cache)
        assert any("из кэша" in m for m in logs) and all(g["side"] == "long" for g in longs)
        assert len(longs) < n or all(g["side"] == "long" for g in a)
        # лист дописан — подпись другая, пересчёт
        time.sleep(0.01)
        with open(sheets, "a", encoding="utf-8") as f:
            f.write(sheet_line("2026-10-14-11", "CUSDT", 95.0) + "\n")
        logs.clear()
        c = D6.gated_legs(side=None, log=logs.append, cache=cache)
        assert not any("из кэша" in m for m in logs) and len(c) > n, (len(c), n, logs)
        # без кэша — как раньше
        assert len(D6.gated_legs(side=None, log=lambda m: None, cache=None)) == len(c)
        # контроль: подпись, не видящая лист, отдала бы старые ноги на новом листе
        real = D6._legs_sig
        D6._legs_sig = lambda: {"sheets": (1, 1), "code": []}
        try:
            D6.gated_legs(side=None, log=lambda m: None, cache=cache)       # записал под фальшивой подписью
            with open(sheets, "a", encoding="utf-8") as f:
                f.write(sheet_line("2026-10-14-12", "DUSDT", 99.0) + "\n")
            stale = D6.gated_legs(side=None, log=lambda m: None, cache=cache)
            assert len(stale) == len(c), "контроль не лёг: фальшивая подпись должна отдать старое"
        finally:
            D6._legs_sig = real
        fresh = D6.gated_legs(side=None, log=lambda m: None, cache=cache)
        assert len(fresh) == len(c) + 1, (len(fresh), len(c))
    finally:
        D2.SHEETS = was
    print(f"ok  кэш ног листа: второй вызов из кэша, гейт после кэша, дописанный лист — пересчёт, "
          f"фальшивая подпись отдаёт старое (контроль); ног {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
