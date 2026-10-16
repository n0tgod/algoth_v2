"""Зонд: строки часовых сводок прокси-имён за данный час — какие поля,
когда записаны, и какая волна выходит по подмножествам. Для разбора
ложного срабатывания охраны рынком. Ничего не меняет.

    run tools/wave_rows_probe.py --hour=2026-10-16-11 --from=2026-10-15-18
"""
import argparse
import itertools
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "research", "dca_paper"))
import wave as WV                                             # noqa: E402


def ts(h):
    return datetime.strptime(h, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc).timestamp()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hour", default="2026-10-16-11")
    ap.add_argument("--from", dest="frm", default="2026-10-15-18")
    a = ap.parse_args()
    hrs = WV.Hours()
    mkt = WV.Market(hrs)
    t1 = ts(a.hour) + 1
    t0 = ts(a.frm) + 3599
    moves = {}
    for s in WV.PROXY:
        r = hrs.row(s, t1)
        p = os.path.join(WV.SUMMARY_DIR, s, a.hour[:10] + ".jsonl")
        mt = time.strftime("%H:%M:%S", time.gmtime(os.path.getmtime(p))) if os.path.exists(p) else "—"
        keys = sorted(r.keys()) if r else None
        m = mkt.move(s, t0, t1)
        moves[s] = m
        extra = {k: r.get(k) for k in ("mid_close", "written_at", "at", "ts", "n", "bars", "last_ts", "closed") if r and k in r}
        print(f"{s[:-4]:6s} ход {('—' if m is None else f'{m * 100:+.2f} %'):>8}  файл mtime {mt}  {extra}")
        if s == WV.PROXY[0] and keys:
            print("   поля строки:", keys)
    ms = sorted((v, k) for k, v in moves.items() if v is not None)
    print(f"волна по всем {len(ms)} именам: {sum(v for v, _ in ms) / len(ms) * 100:+.2f} %")
    # какое подмножество из ≥ MIN_PROXY имён даёт ≥ 2 %: достаточно взять сильнейшие
    top = ms[::-1]
    for n in range(WV.MIN_PROXY, len(top) + 1):
        w = sum(v for v, _ in top[:n]) / n
        if w >= 0.02:
            print(f"  {n} сильнейших имён дают {w * 100:+.2f} %: {', '.join(k[:-4] for _, k in top[:n])}")
        else:
            print(f"  {n} сильнейших — {w * 100:+.2f} % (ниже порога), дальше только ниже")
            break


if __name__ == "__main__":
    main()
