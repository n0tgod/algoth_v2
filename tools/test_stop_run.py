#!/usr/bin/env python3
"""Проверки `stop_run.py`: границы имени и совпадение по пути."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stop_run as S                                          # noqa: E402

PS = [
    "1572752 .venv/bin/python research/b1_book/collect.py --http 8765",
    "1572909 .venv/bin/python research/s8_loop/train.py",
    "1609538 .venv/bin/python research/dca_ladder/run_d10.py",
    "1609533 bash -c log=$1; shift .venv/bin/python research/dca_ladder/run_d10.py",
    "669148 bot/target/release/bot live --s8 research/s8_loop/out/model_sit_lo",
    "7 /usr/bin/python3 tools/diag_cycle.py --tail=12",
]


def test_protected_names_are_refused():
    for bad in ("research/b1_book/collect.py", "research/s8_loop/train.py",
                "tools/jobs.sh", "tools/watchdog_book.sh", "tools/run_live.sh",
                "bot/target/release/bot", "/root/x.py", "research/../tools/x.py",
                "docs/x.py", "research/x.txt"):
        assert not S.allowed(bad), bad
    assert S.allowed("research/dca_ladder/run_d10.py")
    assert S.allowed("tools/diag_cycle.py")
    print("ok  защищённые имена и чужие пути отвергаются")


def test_match_is_by_exact_script_path_of_a_python_process():
    assert S.match(PS, "research/dca_ladder/run_d10.py") == [1609538]
    assert S.match(PS, "research/s8_loop/train.py") == [1572909]   # match ≠ allowed
    assert S.match(PS, "research/dca_ladder/run_d1.py") == []
    assert S.match(PS, "tools/diag_cycle.py") == [7]
    print("ok  совпадение — точный путь у процесса python, обёртка bash не считается")


def test_main_refuses_and_reports_absence():
    assert S.main(["research/s8_loop/train.py"]) == 3
    assert S.main([]) == 2
    assert S.main(["research/dca_ladder/no_such_run.py", "--dry-run"]) == 0
    print("ok  main: отказ кодом 3, отсутствие процесса — словами и кодом 0")


if __name__ == "__main__":
    test_protected_names_are_refused()
    test_match_is_by_exact_script_path_of_a_python_process()
    test_main_refuses_and_reports_absence()
    print("\nвсе 3 проверки прошли")
