#!/usr/bin/env python3
"""Кеш кусков DCA под замком (дефект 06.11): два потока читают журналы
разом — кеш не падает «dictionary changed size during iteration», оба
получают строки; замок один на сборщика."""
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "dca_paper"))
import collect as C                                           # noqa: E402
import rules as DR                                            # noqa: E402


def main():
    td = tempfile.mkdtemp()
    t0 = (int(DR.RULES_SINCE) // 3600 + 1) * 3600
    paths = []
    for j in range(4):
        jp = os.path.join(td, f"j{j}.jsonl")
        paths.append(jp)
        for day in range(6):
            part = jp[:-6] + f"-2026-10-{day + 1:02d}.jsonl"
            with open(part, "w", encoding="utf-8") as f:
                for i in range(60):
                    at = t0 + 100000 * j + 1000 * day + i
                    f.write(json.dumps({"dep": 1000, "ruler": "safe", "at": at, "exit_ts": at + 3600, "sym": f"S{i}USDT",
                                        "usd": 1.0, "written_at": t0 + 700, "rules": DR.RULES, "book_rules": DR.FAMILY_RULES["sit"],
                                        "fills": [[t0, 2.0, 0.25]] * 4}) + "\n")

    class FakeC(C.Collector):
        def __init__(self):
            pass
    c = FakeC()
    was = C.Collector._DCA_PARTS_BUDGET
    C.Collector._DCA_PARTS_BUDGET = 1  # бюджет меньше куска: каждое чтение выбрасывает чужие — кеш меняется постоянно
    errs, got = [], []

    def worker(jp):
        try:
            for _ in range(15):
                rows, _b = c._dca_rows(DR, jp)
                got.append(len(rows))
        except Exception as e:                                # noqa: BLE001
            errs.append(repr(e))
    try:
        th = [threading.Thread(target=worker, args=(p,)) for p in paths for _ in range(2)]
        for t in th:
            t.start()
        for t in th:
            t.join()
    finally:
        C.Collector._DCA_PARTS_BUDGET = was
    assert not errs, errs[:3]
    assert len(got) == 8 * 15 and all(n == 360 for n in got), (len(got), set(got))
    assert isinstance(c.__dict__.get("_dca_parts_lock"), type(threading.Lock())), "замок один на сборщика"
    print("ok  кеш кусков DCA под замком: восемь потоков, бюджет меньше куска — без падений, строки у всех")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
