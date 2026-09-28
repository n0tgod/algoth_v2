#!/usr/bin/env python3
"""Проверка `tools/memtop.py`: разбор `ps`, хвост лога, отсутствующий файл."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memtop as M  # noqa: E402


def test_ps_rows_sorts_by_rss_and_converts_units():
    lines = ["  PID  PPID   RSS ELAPSED COMMAND",
             "   10     1  1536000  90061 .venv/bin/python research/b1_book/collect.py --http 8765",
             "   20     1  4300800    57 .venv/bin/python research/s8_loop/train.py",
             "   30    29   204800 21600 .venv/bin/python research/dca_paper/run_short.py",
             "мусор без чисел",
             "   40     1  abc 5 сломанная строка"]
    rows = M.ps_rows(lines, top=2)
    assert [r[0] for r in rows] == [20, 10], rows
    assert rows[0][2] == 4200 and rows[1][2] == 1500, rows
    assert rows[0][3] == "00:00" and rows[1][3] == "25:01", rows
    assert rows[1][4].endswith("--http 8765")


def test_ps_rows_cuts_args():
    ln = "  1 0 1024 0 " + "x" * 400
    assert len(M.ps_rows([ln])[0][4]) == M.ARGS_W


def test_tail_lines_and_missing():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.log")
        with open(p, "w") as f:
            f.write("\n".join(f"строка {i}" for i in range(10)) + "\n")
        lines, note = M.tail_lines(p, 3)
        assert lines == ["строка 7", "строка 8", "строка 9"], lines
        assert note == "строк всего 10", note
        lines, note = M.tail_lines(os.path.join(d, "нет.log"), 3)
        assert lines is None and note.startswith("не читается")


def test_main_runs_without_server_logs(capsys=None):
    # На стенде логов нет: каждый источник печатает «(файла нет)», а не падает.
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = M.main(["--day", "2026-09-28", "--tail", "3"])
    out = buf.getvalue()
    assert rc == 0
    assert "== free -m" in out and "== процессы по памяти" in out
    assert out.count("(файла нет)") + out.count("строк всего") == len(M.LOGS), out


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
