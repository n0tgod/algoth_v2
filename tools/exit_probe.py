"""Зонд: почему исполнитель Ladder закрыл позиции — записи намерений
`exit` и событий исполнителя по именам за последние сутки, плюс строки
журнала API о выходах. Печатает только поля причины (без ключей и
балансов). Ничего не меняет.

    run tools/exit_probe.py --sym=NXPCUSDT --sym=SIRENUSDT --sym=AKEUSDT
"""
import argparse
import glob
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEEP = ("kind", "sym", "book", "side", "reason", "wave_k", "wave_pct", "decided_at",
        "pos_at", "computed_at", "at", "at_ms", "ts", "event", "type", "exit_px", "px",
        "pnl", "why", "mode", "seq")


def fmt_ts(v):
    try:
        v = float(v)
        if v > 1e12:
            v /= 1000.0
        return time.strftime("%d %H:%M:%S", time.gmtime(v))
    except (TypeError, ValueError):
        return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", action="append", default=[])
    ap.add_argument("--hours", type=float, default=30)
    a = ap.parse_args()
    syms = set(a.sym)
    since = time.time() - a.hours * 3600
    for path in sorted(glob.glob(os.path.join(ROOT, "bot", "out", "dca", "sub_*", "*.jsonl"))):
        hits = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not any(s in line for s in syms):
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    t = r.get("computed_at") or r.get("at") or r.get("ts") or r.get("at_ms") or 0
                    try:
                        t = float(t)
                        if t > 1e12:
                            t /= 1000.0
                    except (TypeError, ValueError):
                        t = 0
                    if t and t < since:
                        continue
                    row = {k: (fmt_ts(v) if k in ("decided_at", "pos_at", "computed_at", "at", "at_ms", "ts") else v)
                           for k, v in r.items() if k in KEEP}
                    hits.append(json.dumps(row, ensure_ascii=False)[:300])
        except OSError:
            continue
        if hits:
            print(f"== {os.path.relpath(path, ROOT)}: {len(hits)}")
            for h in hits[-40:]:
                print("  ", h)
    for path in glob.glob(os.path.join(ROOT, "tools", "app_api", "out", "*.log")):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = [ln.rstrip() for ln in f if ("wave" in ln or "рынк" in ln or "market" in ln)
                         and any(s in ln for s in syms)]
        except OSError:
            continue
        if lines:
            print(f"== {os.path.relpath(path, ROOT)}: {len(lines)}")
            for ln in lines[-20:]:
                print("  ", ln[:300])


if __name__ == "__main__":
    main()
