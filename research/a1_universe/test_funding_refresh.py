#!/usr/bin/env python3
"""Проверки догона рядов funding (`funding_refresh.py`).

Сеть подменяется: `fetch` — подставная пагинация с записью аргументов,
файлы — во временном каталоге вместо `out/funding`. Ряд в фикстуре
выглядит как живой: ISO-время и ставка строкой, как пишет сборщик A1.
"""

import gzip
import importlib
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bybit_api as B                                         # noqa: E402
import funding_refresh as FR                                  # noqa: E402

TODAY = date(2026, 9, 6)


def _iso(d, h=0):
    return f"{d.isoformat()}T{h:02d}:00:00+00:00"


def _write(dirp, sym, rows):
    os.makedirs(dirp, exist_ok=True)
    with gzip.open(os.path.join(dirp, f"{sym}.csv.gz"), "wt",
                   encoding="utf-8", newline="") as f:
        f.write("funding_time,funding_rate\n")
        for t, r in rows:
            f.write(f"{t},{r}\n")


class _Fetch:
    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.calls = rows, fail, []

    def __call__(self, sym, a, b):
        self.calls.append((sym, a, b))
        if self.fail:
            raise RuntimeError("сеть")
        return [r for r in self.rows]


def _in_tmp(fn):
    tmp = tempfile.mkdtemp(prefix="fund-")
    saved = B.FUNDING_DIR
    B.FUNDING_DIR = os.path.join(tmp, "funding")
    try:
        return fn(B.FUNDING_DIR)
    finally:
        B.FUNDING_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_merge_dedups_by_time_and_new_wins():
    old = [(_iso(date(2026, 7, 1)), "0.0001"), (_iso(date(2026, 7, 1), 8), "0.0002")]
    new = [(_iso(date(2026, 7, 1), 8), "0.0003"), (_iso(date(2026, 7, 2)), "0.0004")]
    m = FR.merge(old, new)
    assert len(m) == 3, m
    assert m[1] == (_iso(date(2026, 7, 1), 8), "0.0003"), m[1]     # новая победила
    assert [t for t, _ in m] == sorted(t for t, _ in m)
    print("ok  слияние по времени: повтор снят, новая точка побеждает, порядок по времени")


def test_tail_is_fetched_from_the_last_day_with_overlap():
    def body(dirp):
        ld = date(2026, 7, 20)
        old = [(_iso(ld - timedelta(days=1)), "0.0001"), (_iso(ld, 8), "0.0002")]
        _write(dirp, "AAAUSDT", old)
        f = _Fetch([(_iso(ld, 8), "0.0002"), (_iso(ld, 16), "0.0005"),
                    (_iso(TODAY), "0.0009")])
        had, added, end, err = FR.refresh_symbol("AAAUSDT", TODAY, fetch=f)
        assert err is None and had == 2 and added == 2, (had, added, err)
        assert end == TODAY.isoformat(), end
        assert f.calls == [("AAAUSDT", ld - timedelta(days=FR.OVERLAP_D), TODAY)], f.calls
        rows = FR.read_rows(os.path.join(dirp, "AAAUSDT.csv.gz"))
        assert len(rows) == 4 and rows[-1][1] == "0.0009", rows
        assert not os.path.exists(os.path.join(dirp, "AAAUSDT.csv.gz.tmp"))
        # символ без файла: тянется вся история
        f2 = _Fetch([(_iso(TODAY), "0.0001")])
        had, added, end, err = FR.refresh_symbol("NEWUSDT", TODAY, fetch=f2)
        assert had == 0 and added == 1 and end == TODAY.isoformat(), (had, added, end)
        assert f2.calls[0][1] < date(2020, 1, 1), f2.calls
    _in_tmp(body)
    print("ok  хвост тянется с последнего дня минус сутки перекрытия, повтор снят, файл атомарен")


def test_current_symbol_is_not_fetched_and_failure_leaves_the_file():
    def body(dirp):
        _write(dirp, "CURUSDT", [(_iso(TODAY, 8), "0.0001")])
        f = _Fetch([])
        had, added, end, err = FR.refresh_symbol("CURUSDT", TODAY, fetch=f)
        assert f.calls == [] and added == 0 and err is None, (f.calls, added, err)
        old = [(_iso(date(2026, 7, 1)), "0.0001")]
        _write(dirp, "BADUSDT", old)
        before = open(os.path.join(dirp, "BADUSDT.csv.gz"), "rb").read()
        had, added, end, err = FR.refresh_symbol("BADUSDT", TODAY, fetch=_Fetch([], fail=True))
        assert err and added == 0 and end == "2026-07-01", (err, added, end)
        assert open(os.path.join(dirp, "BADUSDT.csv.gz"), "rb").read() == before
        # пустой ответ — тоже без записи
        had, added, end, err = FR.refresh_symbol("BADUSDT", TODAY, fetch=_Fetch([]))
        assert added == 0 and err is None and end == "2026-07-01"
    _in_tmp(body)
    print("ok  свежий символ не тянется; отказ сети и пустой ответ файл не трогают")


def test_run_aggregates_and_report_names_failures():
    def body(dirp):
        _write(dirp, "AAAUSDT", [(_iso(date(2026, 7, 1)), "0.0001")])
        _write(dirp, "BBBUSDT", [(_iso(date(2026, 8, 1)), "0.0001")])
        good = [(_iso(TODAY), "0.0002")]
        calls = []

        def fetch(sym, a, b):
            calls.append(sym)
            if sym == "BBBUSDT":
                raise RuntimeError("сеть")
            return good
        s = FR.run(["AAAUSDT", "BBBUSDT", "CCCUSDT"], TODAY, workers=1,
                   log=lambda *a: None, fetch=fetch)
        assert s["symbols"] == 3 and s["errors"] == 1 and s["added"] == 2, s
        assert s["end_min"] == "2026-08-01" and s["end_max"] == TODAY.isoformat(), s
        assert s["per_symbol"]["BBBUSDT"]["error"], s["per_symbol"]["BBBUSDT"]
        txt = FR.report(s)
        assert "BBBUSDT" in txt and "отказов сети 1" in txt, txt
        assert "медиана" in txt
    _in_tmp(body)
    print("ok  сводка догона: края рядов, отказы поимённо")


# --- отрицательные контроли ------------------------------------------------
def _poison(path, lit, sub, fn, mod):
    src = open(path, encoding="utf-8").read()
    assert src.count(lit) == 1, f"подделка НЕ легла: литерал не один — {lit}"
    keep = os.path.join(tempfile.mkdtemp(prefix="fr-"), os.path.basename(path))
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, sub, 1))
        cache = os.path.join(os.path.dirname(path), "__pycache__")
        base = os.path.basename(path).split(".")[0]
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith(base + "."):
                    os.remove(os.path.join(cache, f))
        importlib.reload(mod)
        try:
            fn()
        except Exception:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(mod)


P = os.path.join(HERE, "funding_refresh.py")


def _control_no_overlap():
    return _poison(P, "start = (ld - timedelta(days=OVERLAP_D)) if ld else",
                   "start = ld if ld else",
                   test_tail_is_fetched_from_the_last_day_with_overlap, FR)


def _control_old_point_wins():
    return _poison(P, "        by[t] = r\n    return sorted(by.items())",
                   "        by.setdefault(t, r)\n    return sorted(by.items())",
                   test_merge_dedups_by_time_and_new_wins, FR)


def _control_current_symbol_refetched():
    return _poison(P, "if ld is not None and ld >= today:", "if False:",
                   test_current_symbol_is_not_fetched_and_failure_leaves_the_file, FR)


TESTS = [
    test_merge_dedups_by_time_and_new_wins,
    test_tail_is_fetched_from_the_last_day_with_overlap,
    test_current_symbol_is_not_fetched_and_failure_leaves_the_file,
    test_run_aggregates_and_report_names_failures,
]

CONTROLS = [
    ("хвост без перекрытия", _control_no_overlap),
    ("старая точка побеждает новую", _control_old_point_wins),
    ("свежий символ тянется заново", _control_current_symbol_refetched),
]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; {len(CONTROLS)} отрицательных "
          f"контролей кусаются")


if __name__ == "__main__":
    main()
