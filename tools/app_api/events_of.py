#!/usr/bin/env python3
"""События исполнителя Ladder по одному имени — разбор сделки (11.10).

Печатает строки `events.jsonl` подписок по имени и строки лога процесса
`ladder.log`, где имя упомянуто. Ключей и секретов в этих файлах нет.

    run tools/app_api/events_of.py --sym STRKUSDT
"""
import argparse
import glob
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXEC = os.path.join(ROOT, "bot", "out", "dca")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", required=True)
    ap.add_argument("--log-tail", type=int, default=60)
    a = ap.parse_args(argv)
    sym = a.sym.upper()
    for d in sorted(glob.glob(os.path.join(EXEC, "sub_*"))):
        print(f"== {os.path.basename(d)}")
        try:
            with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as f:
                for ln in f:
                    try:
                        e = json.loads(ln)
                    except ValueError:
                        continue
                    if e.get("sym") == sym:
                        t = time.strftime("%m-%d %H:%M:%S", time.gmtime(float(e.get("ts") or 0)))
                        print(t, json.dumps(e, ensure_ascii=False))
        except OSError as e:
            print(f"events.jsonl: {e}")
        for lp in sorted(glob.glob(os.path.join(d, "*.log"))):
            try:
                lines = [x.rstrip() for x in open(lp, encoding="utf-8", errors="replace") if sym in x]
            except OSError:
                continue
            print(f"-- {os.path.basename(lp)}: строк с {sym} {len(lines)}")
            for x in lines[-a.log_tail:]:
                print("  " + x[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
