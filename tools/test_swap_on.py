#!/usr/bin/env python3
"""Проверка `tools/swap_on.py`: план по состоянию, отказы, без `--apply` ничего не меняется."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swap_on as S  # noqa: E402


def test_plan_branches():
    base = {"active": "", "file": False, "size_gb": 0, "fstab": False, "root_free_gb": 72.0}
    steps, why = S.plan(base, 4, True)
    assert why == "ok" and [s[0] for s in steps] == ["fallocate", "chmod", "mkswap", "swapon", "fstab-append"], steps
    steps, why = S.plan(dict(base, fstab=True), 4, True)
    assert [s[0] for s in steps] == ["fallocate", "chmod", "mkswap", "swapon"], steps
    steps, why = S.plan(dict(base, active="/swapfile 4294967296 0 -2"), 4, True)
    assert steps == [] and why == "своп уже активен", why
    steps, why = S.plan(dict(base, file=True, size_gb=2.0), 4, False)
    assert steps == [] and "решать руками" in why, why
    steps, why = S.plan(dict(base, file=True, size_gb=4.0), 4, False)
    assert [s[0] for s in steps] == ["swapon"], steps
    steps, why = S.plan(dict(base, root_free_gb=23.0), 4, False)
    assert steps == [] and "меньше" in why, why


def test_dry_run_changes_nothing(tmp=None):
    import io
    from contextlib import redirect_stdout
    calls = []
    orig = S.sh
    S.sh = lambda cmd: (calls.append(cmd) or (0, "", ""))
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = S.main(["--size-gb", "4"])
        assert rc == 0 and "ничего не менял" in buf.getvalue(), buf.getvalue()
        # без --apply единственный вызов — чтение состояния (swapon --show)
        assert all(c[:2] == ["swapon", "--show"] for c in calls), calls
    finally:
        S.sh = orig


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
