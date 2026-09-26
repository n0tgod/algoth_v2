#!/usr/bin/env python3
"""Добор цены выхода охраны: исправляется только поле показа с сохранением
прежнего, деньги не тронуты, чужой выход и строки без заполнений — как
были, повтор ничего не меняет, подмена другого поля роняет прогон."""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402

spec = importlib.util.spec_from_file_location("bx", os.path.join(HERE, "backfill_exit_px.py"))
BX = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BX)

AT = 1790352000.0
H = 3600.0


def _row(**kw):
    r = {"dep": 1000, "ruler": "optimal_h", "at": AT, "sym": "RAREUSDT", "side": "short",
         "lev": 25.0, "margin": 53.6, "entry_px": 0.016194, "exit_ts": AT + 8 * H - 1,
         "exit": R.GUARD_EXIT, "exit_px": 0.016103, "pnl_frac": 0.14048, "usd": 7.53,
         "fills": [[AT, 0.016194, 0.25]], "rules": R.RULES, "book_rules": R.family_rules("optimal_h")}
    r.update(kw)
    return r


def main():
    rows = [_row(),                                              # исправляется
            _row(sym="BBBUSDT", exit="срок"),                    # чужой выход — нет
            _row(sym="CCCUSDT", fills=None),                     # без заполнений — нет, считается
            _row(sym="DDDUSDT", rules=R.RULES - 1),              # чужая версия — нет
            _row(sym="EEEUSDT", exit_px=0.01583, exit_px_from="fills")]   # уже добрана
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "short-2026-09-26.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        n, t, m = BX.patch_file(p, write=True)
        assert (n, t, m) == (5, 1, 1), (n, t, m)
        got = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
        assert abs(got[0]["exit_px"] - 0.01583) < 2e-6 and got[0]["exit_px_was"] == 0.016103 \
            and got[0]["exit_px_from"] == "fills", got[0]
        assert got[0]["pnl_frac"] == 0.14048 and got[0]["usd"] == 7.53, got[0]
        assert got[1]["exit_px"] == 0.016103 and "exit_px_from" not in got[1]
        assert got[2]["exit_px"] == 0.016103 and "exit_px_from" not in got[2]
        assert got[3]["exit_px"] == 0.016103 and got[4]["exit_px"] == 0.01583
        n2, t2, m2 = BX.patch_file(p, write=True)
        assert (t2, m2) == (0, 1), (t2, m2)
        # контроль сверки: подмена денег под видом добора роняет прогон
        # (файл пишется ДО подмены, иначе подмена легла бы и в исходник)
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(rows[0], ensure_ascii=False) + "\n")
        assert json.loads(open(p, encoding="utf-8").readline())["usd"] == 7.53
        real = BX.json.dumps
        BX.json.dumps = lambda r, **kw: real(dict(r, usd=99.0), **kw)
        try:
            BX.patch_file(p, write=True)
            raise AssertionError("сверка пропустила подмену usd")
        except SystemExit as e:
            assert "не только полями" in str(e), e
        finally:
            BX.json.dumps = real
        # контроль: изменившийся кусок не пишется
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(rows[0], ensure_ascii=False) + "\n")
        BX._unchanged = lambda path, sig: False
        n3, t3, m3 = BX.patch_file(p, write=True)
        assert (t3, m3) == (0, 0) and json.loads(open(p).readline())["exit_px"] == 0.016103
    print("ok  добор цены выхода: исправлена 1 (0.016103 → 0.01583, прежняя сохранена), деньги "
          "не тронуты, чужой выход/версия/без заполнений/уже добранная — как были, повтор пуст, "
          "подмена денег и изменившийся кусок — отказ")


if __name__ == "__main__":
    main()
