#!/usr/bin/env python3
"""Чтение баров записи B1 не зависит от порядка пути: процесс, где первым
на пути стоит `research/news` (у сборщика новостей свой `collect.py`), всё
равно получает `minute_bars` сборщика стакана (книги ТВХ модели, 21.10:
тик падал на `ImportError`). Отдельным процессом — путь не делится с
другими проверками."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CODE = """
import sys
sys.path.insert(0, "research/s9_sweep")
import sweep as SW
sys.path.insert(0, "research/news")
import collect as news_collect
assert "news" in news_collect.__file__ and not hasattr(news_collect, "minute_bars"), "подделка легла"
m = SW._b1("collect")
assert hasattr(m, "minute_bars") and "b1_book" in m.__file__, m.__file__
assert hasattr(SW._b1("store"), "read_hour")
"""


def main():
    r = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    print("ok  бары B1 при чужом `collect` на пути: сборщик стакана грузится по пути")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
