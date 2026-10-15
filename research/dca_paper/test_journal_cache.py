#!/usr/bin/env python3
"""Кеш разобранных кусков журнала на диске (`rules.read_journal(disk=…)`,
15.10): второй вызов берёт куски с диска и отдаёт то же; дописанный кусок
разбирается заново; отбор `keep` живёт в подписи (одна подпись на журнал), а без подписи — ошибка;
подложенный pickle с верной подписью читается (контроль: кеш правда
читается), дописка его вытесняет; pickle исчезнувшего куска сметается.

    .venv/bin/python research/dca_paper/test_journal_cache.py
"""
import json
import os
import pickle
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402


def row(sym, at, rules=R.RULES, dep=1000, ruler="optimal", book=None):
    r = {"sym": sym, "at": at, "written_at": at + 5, "rules": rules, "dep": dep,
         "ruler": ruler, "usd": 1.5, "exit": "take", "exit_ts": at + 3600}
    if book:
        r["book"] = book
    return r


def write(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    d = tempfile.mkdtemp()
    j = os.path.join(d, "journal.jsonl")
    p1 = os.path.join(d, "journal-2026-10-01.jsonl")
    p2 = os.path.join(d, "journal-2026-10-02.jsonl")
    disk = os.path.join(d, "cache")
    t0 = 1_790_000_000.0
    cur = [row("AUSDT", t0 + 10 * i) for i in range(5)]
    old = [row("BUSDT", t0 + 10 * i, rules=R.RULES - 1) for i in range(3)]
    write(j, cur[:2] + old)
    write(p1, cur[1:4])                       # перекрытие с j по cur[1] — дедуп
    write(p2, cur[4:])
    with open(p2, "a", encoding="utf-8") as f:
        f.write("{битая строка\n")
    # эталон — без диска
    st0 = {}
    r0, b0 = R.read_journal(j, stats=st0)
    assert len(r0) == 8 and b0 == 1 and st0["dups"] == 1, (len(r0), b0, st0)
    # с диском: первый раз разбор и запись, второй — с диска, то же самое
    st1, st2 = {}, {}
    r1, b1 = R.read_journal(j, stats=st1, disk=disk)
    r2, b2 = R.read_journal(j, stats=st2, disk=disk)
    assert (r1, b1) == (r0, b0) and (r2, b2) == (r0, b0)
    assert st1["disk"] == 0 and st1["parsed"] == 10, st1
    assert st2["disk"] == 3 and st2["parsed"] == 0, st2
    assert len(os.listdir(disk)) == 3
    # отбор без подписи с диском — ошибка, не тишина
    try:
        R.read_journal(j, keep=R.is_current, disk=disk)
        raise AssertionError("keep без keep_sig прошёл молча")
    except ValueError:
        pass
    # дописанный кусок — разбор заново только его
    time.sleep(0.01)
    with open(p2, "a", encoding="utf-8") as f:
        f.write(json.dumps(row("CUSDT", t0 + 999)) + "\n")
    st3 = {}
    r3, b3 = R.read_journal(j, stats=st3, disk=disk)
    assert len(r3) == 9 and b3 == 1 and st3["disk"] == 2 and st3["parsed"] == 3, (len(r3), st3)
    # контроль: подложенный pickle с ВЕРНОЙ подписью читается — значит кеш
    # в самом деле источник; дописка меняет подпись и вытесняет подделку
    stx = os.stat(p1)
    cp = R._disk_path(disk, p1, "all")
    fake = [row("ZZZUSDT", t0 + 5000)]
    with open(cp, "wb") as f:
        pickle.dump({"sig": (stx.st_mtime_ns, stx.st_size), "rows": fake,
                     "keys": [R.journal_key(fake[0])], "bad": 0}, f)
    rx, _ = R.read_journal(j, disk=disk)
    assert any(r["sym"] == "ZZZUSDT" for r in rx), "контроль не лёг: подделка не прочитана"
    time.sleep(0.01)
    with open(p1, "a", encoding="utf-8") as f:
        f.write(json.dumps(row("DUSDT", t0 + 7777)) + "\n")
    ry, _ = R.read_journal(j, disk=disk)
    assert not any(r["sym"] == "ZZZUSDT" for r in ry) and any(r["sym"] == "DUSDT" for r in ry)
    # исчезнувший кусок — его pickle сметается; чужой журнал не трогается
    os.rename(p2, os.path.join(d, "other-2026-10-02.jsonl"))
    foreign = os.path.join(disk, "fixed_journal-2026-10-02.jsonl.all.pkl")
    with open(foreign, "wb") as f:
        f.write(b"x")
    R.read_journal(j, disk=disk)
    names = os.listdir(disk)
    assert not any(n.startswith("journal-2026-10-02.jsonl.") for n in names), names
    assert os.path.basename(foreign) in names
    # без диска после всего — тот же ответ, что с диском
    assert R.read_journal(j)[0] == R.read_journal(j, disk=disk)[0]
    # отбор текущих правил со своей подписью: архивных строк нет, с диска
    # то же; у журнала в каталоге живёт ОДНА подпись отбора — pickle
    # подписи «all» сметены, а чужой журнал нетронут
    ks = R.current_sig()
    rk, _ = R.read_journal(j, keep=R.is_current, disk=disk, keep_sig=ks)
    stk = {}
    rk2, _ = R.read_journal(j, keep=R.is_current, disk=disk, keep_sig=ks, stats=stk)
    want = [r["sym"] for r in R.read_journal(j)[0] if R.is_current(r)]
    assert [r["sym"] for r in rk] == want and rk2 == rk and stk["disk"] == 2, (len(rk), stk)
    names = os.listdir(disk)
    assert all(f".{ks}.pkl" in n for n in names if n.startswith("journal")), names
    assert os.path.basename(foreign) in names
    print("ok  кеш кусков журнала: с диска то же, что разбором; дописка — разбор одного куска; "
          "keep без подписи — ошибка; подделка с верной подписью читается (контроль) и "
          "вытесняется допиской; pickle исчезнувшего куска сметён")
    return 0


if __name__ == "__main__":
    sys.exit(main())
