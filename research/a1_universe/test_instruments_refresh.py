#!/usr/bin/env python3
"""Проверки догона справочника инструментов.

Кусаются: старая запись не исчезает (делистнутый символ остаётся),
свежая побеждает, новые и обновлённые считаются РАЗНЫМИ числами; возраст
считается от момента листинга и на заданный момент; отказ площадки не
трогает прежний файл.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import instruments_refresh as IR                              # noqa: E402

DAY = 86400.0


def test_merge_keeps_the_old_and_counts_kinds_apart():
    old = {"A": {"symbol": "A", "status": "Trading"},
           "GONE": {"symbol": "GONE", "status": "Closed"}}
    fresh = {"A": {"symbol": "A", "status": "Closed"},
             "NEW": {"symbol": "NEW", "status": "Trading"}}
    got, new, upd = IR.merge(old, fresh)
    assert set(got) == {"A", "GONE", "NEW"}, got
    assert got["A"]["status"] == "Closed", got["A"]
    assert got["GONE"]["status"] == "Closed", "делистнутый исчез"
    assert (new, upd) == (1, 1), (new, upd)
    print(f"ok  слияние: новых {new}, обновлённых {upd}, делистнутый на месте")


def test_age_is_counted_from_the_launch_moment():
    at = 1788800000.0
    data = {"A": {"launch_time": str(int((at - 10 * DAY) * 1000))},
            "B": {"launch_time": str(int((at - 100 * DAY) * 1000))},
            "NO": {"launch_time": None}}
    ages = IR.launch_days(data, at=at)
    assert abs(ages["A"] - 10.0) < 1e-6 and abs(ages["B"] - 100.0) < 1e-6
    assert "NO" not in ages, "символ без даты листинга получил возраст"
    # на другой момент возраст другой — это возраст, а не константа
    later = IR.launch_days(data, at=at + 5 * DAY)
    assert abs(later["A"] - 15.0) < 1e-6, later
    print(f"ok  возраст от листинга: A {ages['A']:.0f} сут, B "
          f"{ages['B']:.0f}; без даты — не считается")


def test_cache_key_carries_the_day_of_the_run():
    """Догон обязан СПРОСИТЬ площадку, а не вернуть вчерашний ответ.

    Кусается: первый живой прогон отработал за 0.1 с и объявил «новых
    0» — ключ кэша ответов не нёс дня, и справочник пришёл из
    августовского снимка. Проверяется, что метка доезжает до вызова.
    """
    seen = []
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "instruments.json")
        IR.run(log=lambda *a: None, path=p,
               collect=lambda tag="": (seen.append(tag) or {"A": {"symbol": "A"}}))
    assert seen and seen[0].startswith("_20"), seen
    assert len(seen[0]) == 11, seen        # «_ГГГГ-ММ-ДД»
    print(f"ok  ключ кэша несёт день прогона: метка «{seen[0]}»")


def test_venue_silence_leaves_the_file_alone():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "instruments.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"A": {"symbol": "A"}}, f)
        def boom(tag=""):
            raise RuntimeError("нет сети")
        s = IR.run(log=lambda *a: None, collect=boom, path=p)
        assert s.get("error") and s["had"] == 1, s
        with open(p, encoding="utf-8") as f:
            assert json.load(f) == {"A": {"symbol": "A"}}, "файл тронут"
        assert "Не обновлён" in IR.report(s)
        print("ok  отказ площадки: прежний файл не тронут, причина словами")


if __name__ == "__main__":
    for t in (test_merge_keeps_the_old_and_counts_kinds_apart,
              test_cache_key_carries_the_day_of_the_run,
              test_age_is_counted_from_the_launch_moment,
              test_venue_silence_leaves_the_file_alone):
        t()
    print("\nвсе 4 проверки прошли")
