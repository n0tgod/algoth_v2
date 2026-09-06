#!/usr/bin/env python3
"""Проверки `spill_book.py` на подставном дереве записи: переносятся
только старые сжатые часы, оригинал уступает место ссылке лишь после
проверенной копии, прогон идемпотентен, предохранители держат."""
import gzip
import importlib
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spill_book as SB                                       # noqa: E402

TODAY = datetime.now(timezone.utc).date()


def _day(n):
    return (TODAY - timedelta(days=n)).isoformat()


def _tree():
    """Источник: два символа, дни −10…−1, сжатые часы; плюс несжатый
    старый час и текущий день. Приёмник — отдельный каталог."""
    base = tempfile.mkdtemp(prefix="spill-")
    src = os.path.join(base, "out")
    dest = os.path.join(base, "spill")
    for sub in ("book", "trades"):
        for sym in ("AAAUSDT", "BBBUSDT"):
            d = os.path.join(src, sub, sym)
            os.makedirs(d)
            for back in range(1, 11):
                for hh in (0, 12):
                    p = os.path.join(d, f"{_day(back)}-{hh:02d}.jsonl.gz")
                    with gzip.open(p, "wb") as f:
                        f.write((f"{sub} {sym} {back} {hh}\n" * 200).encode())
            with open(os.path.join(d, f"{_day(5)}-23.jsonl"), "w") as f:
                f.write("несжатый старый час\n")         # не трогать
            with open(os.path.join(d, f"{_day(0)}-01.jsonl"), "w") as f:
                f.write("текущий день\n")
    os.makedirs(os.path.join(src, "metrics", "AAAUSDT"))
    with gzip.open(os.path.join(src, "metrics", "AAAUSDT",
                                f"{_day(9)}-00.jsonl.gz"), "wb") as f:
        f.write("metrics: не в списке подкаталогов\n".encode())
    return base, src, dest


def _files(src):
    out = {}
    for r, _, fs in os.walk(src):
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, src)] = p
    return out


def test_moves_only_old_compressed_hours_and_links_them():
    base, src, dest = _tree()
    SB.REQUIRE_OTHER_DEV = False
    try:
        before = {k: open(v, "rb").read() for k, v in _files(src).items()}
        s = SB.run(src=src, dest=dest, upto=_day(3), max_gb=10,
                   min_root_free_gb=0, log=lambda *a: None)
        # дни −10…−3 по двум подкаталогам, двум символам и двум часам
        assert s["files"] == 8 * 2 * 2 * 2 and s["stop"] is None, s
        for rel, p in _files(src).items():
            day = os.path.basename(rel)[:10]
            is_gz = rel.endswith(".jsonl.gz")
            in_subs = rel.split(os.sep)[0] in SB.SUBS
            moved = is_gz and in_subs and day <= _day(3)
            assert os.path.islink(p) == moved, (rel, moved)
            # содержимое по прежнему пути читается тем же
            assert open(p, "rb").read() == before[rel], rel
            if moved:
                tgt = os.readlink(p)
                assert tgt == os.path.join(dest, rel) and os.path.isfile(tgt), rel
                assert os.stat(tgt).st_mtime == os.stat(p).st_mtime
        assert os.path.exists(os.path.join(dest, "spill.log"))
        # повтор ничего не переносит: ссылки пропускаются
        s2 = SB.run(src=src, dest=dest, upto=_day(3), max_gb=10,
                    min_root_free_gb=0, log=lambda *a: None)
        assert s2["files"] == 0 and s2["candidates"] == 0, s2
        print(f"ok  перенесено {s['files']} старых сжатых часов, ссылки на месте, "
              "содержимое и mtime те же; повтор — ноль")
    finally:
        SB.REQUIRE_OTHER_DEV = True
        shutil.rmtree(base, ignore_errors=True)


def test_dry_run_and_caps_do_not_move():
    base, src, dest = _tree()
    SB.REQUIRE_OTHER_DEV = False
    try:
        s = SB.run(src=src, dest=dest, upto=_day(3), dry_run=True,
                   log=lambda *a: None)
        assert s["files"] == 0 and s["candidates"] == 64, s
        assert not any(os.path.islink(p) for p in _files(src).values())
        # предел за прогон: крошечный — переносится меньше, остальное ждёт
        s = SB.run(src=src, dest=dest, upto=_day(3), max_gb=0,
                   min_root_free_gb=0, log=lambda *a: None)
        assert s["files"] == 0 and "предел" in s["stop"], s
        # запас приёмника: требуем больше, чем есть на диске
        s = SB.run(src=src, dest=dest, upto=_day(3), max_gb=10,
                   min_root_free_gb=1e9, log=lambda *a: None)
        assert s["files"] == 0 and "приёмнике" in s["stop"], s
        # день не позже позавчера
        try:
            SB.run(src=src, dest=dest, upto=_day(1), log=lambda *a: None)
        except SystemExit as e:
            assert "позавчера" in str(e), e
        else:
            raise AssertionError("вчерашний день принят")
        print("ok  пробный прогон, предел объёма, запас корня и день не позже "
              "позавчера — ничего не переносят")
    finally:
        SB.REQUIRE_OTHER_DEV = True
        shutil.rmtree(base, ignore_errors=True)


def test_same_device_is_refused():
    base, src, dest = _tree()
    try:
        try:
            SB.run(src=src, dest=dest, upto=_day(3), log=lambda *a: None)
        except SystemExit as e:
            assert "одном диске" in str(e), e
        else:
            raise AssertionError("один диск принят")
        print("ok  источник и приёмник на одном диске — отказ")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_truncated_copy_leaves_the_original():
    base, src, dest = _tree()
    p = os.path.join(src, "book", "AAAUSDT", f"{_day(9)}-00.jsonl.gz")
    orig = open(p, "rb").read()
    real = shutil.copyfile

    def short(a, b):
        real(a, b)
        with open(b, "r+b") as f:
            f.truncate(len(orig) // 2)

    shutil.copyfile = short
    try:
        try:
            SB.spill_one(p, os.path.join(dest, "book", "AAAUSDT",
                                         os.path.basename(p)))
        except IOError as e:
            assert "неполна" in str(e), e
        else:
            raise AssertionError("усечённая копия принята")
        assert not os.path.islink(p) and open(p, "rb").read() == orig
        assert not os.path.exists(os.path.join(dest, "book", "AAAUSDT",
                                               os.path.basename(p) + ".tmp"))
        print("ok  усечённая копия: оригинал цел, ссылки нет, временный файл снят")
    finally:
        shutil.copyfile = real
        shutil.rmtree(base, ignore_errors=True)


# --- отрицательные контроли ------------------------------------------------
def _poison(path, lit, sub, fn):
    src = open(path, encoding="utf-8").read()
    assert src.count(lit) == 1, f"подделка НЕ легла: {lit}"
    keep = os.path.join(tempfile.mkdtemp(prefix="spill-ctl-"), "spill_book.py")
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, sub, 1))
        cache = os.path.join(os.path.dirname(path), "__pycache__")
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith("spill_book."):
                    os.remove(os.path.join(cache, f))
        importlib.reload(SB)
        try:
            fn()
        except Exception:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(SB)


P = os.path.join(HERE, "spill_book.py")


def _control_copy_not_verified():
    return _poison(P, "if got != size:", "if False:",
                   test_truncated_copy_leaves_the_original)


def _control_same_device_allowed():
    return _poison(P, "if REQUIRE_OTHER_DEV and os.stat(src).st_dev == os.stat(dest).st_dev:",
                   "if False:", test_same_device_is_refused)


def _control_plain_jsonl_moved_too():
    return _poison(P, r'NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-\d{2}\.jsonl\.gz$")',
                   r'NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-\d{2}\.jsonl(\.gz)?$")',
                   test_moves_only_old_compressed_hours_and_links_them)


TESTS = [test_moves_only_old_compressed_hours_and_links_them,
         test_dry_run_and_caps_do_not_move, test_same_device_is_refused,
         test_truncated_copy_leaves_the_original]
CONTROLS = [("копия не проверяется", _control_copy_not_verified),
            ("один диск разрешён", _control_same_device_allowed),
            ("несжатый час тоже переносится", _control_plain_jsonl_moved_too)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; {len(CONTROLS)} отрицательных "
          f"контролей кусаются")


if __name__ == "__main__":
    main()
