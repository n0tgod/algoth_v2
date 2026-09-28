#!/usr/bin/env python3
"""Проверка `tools/loggrep.py`: счёт по дням в обоих форматах меток, окно дней."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loggrep as L  # noqa: E402


def test_scan_counts_by_day_in_both_stamp_formats():
    lines = ["[09-28 17:20:28] матрица: 784 символов × 1330 часов",
             "[09-28 18:20:28] матрица: 784 символов × 1331 часов",
             "[09-27 03:00:00] матрица: 784 символов × 1300 часов",
             "[2026-09-26T03:00:01Z] цикл обучения не найден — поднимаю",
             "[09-10 03:00:00] матрица: старая, вне окна",
             "строка без метки: матрица:"]
    by_day, hits = L.scan(lines, "матрица:", 10, today=date(2026, 9, 28))
    assert by_day == {"2026-09-28": 2, "2026-09-27": 1}, by_day
    assert len(hits) == 3, hits
    by_day, hits = L.scan(lines, "поднимаю", 3, today=date(2026, 9, 28))
    assert by_day == {"2026-09-26": 1}, by_day
    by_day, _ = L.scan(lines, "поднимаю", 2, today=date(2026, 9, 28))
    assert by_day == {}, by_day


def test_preset_cycle_matches_milestones():
    lines = ["[09-28 17:33:10] матрица: 784 символов × 1330 часов, сечений 1200",
             "[09-28 17:34:10] переобучаю: весам 101.8 ч при каденции 24",
             "[09-28 16:05:31]   сводка: 663/784 символов, новых часов 0",
             "[09-24 20:13:00] цикл закончен за 1200 с, веса v5"]
    by_day, hits = L.scan(lines, L.PRESETS["cycle"], 10, today=date(2026, 9, 28))
    assert by_day == {"2026-09-28": 2, "2026-09-24": 1}, by_day


def test_main_without_file():
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = L.main(["--file", "train", "--preset", "cycle"])
    assert rc == 0 and "(файла нет)" in buf.getvalue(), buf.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
