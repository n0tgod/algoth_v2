"""Что происходило у живого исполнителя: журнал сделок с временем.

Хвост `live.log` обманчив — в нём нет отметок времени, и строки
трёхдневной давности читаются как свежие (так и вышло при разборе
2026-08-25). Журнал исполнителя время несёт, поэтому вопросы «когда
это было» и «на чём потеряны деньги» решаются по нему.

Только чтение.

    .venv/bin/python research/ops/live_report.py [--last 20]
"""

import argparse
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
JOURNAL = os.path.join(ROOT, "bot", "out", "live")


def rows():
    """Записи журнала по всем суточным файлам, по возрастанию времени."""
    out = []
    try:
        names = sorted(os.listdir(JOURNAL))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(JOURNAL, name), encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def when(ms):
    if not ms:
        return "—"
    return time.strftime("%m-%d %H:%M:%S", time.gmtime(ms / 1000))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=20)
    args = ap.parse_args()

    print("=== возраст журналов (часов назад) ===")
    for p in ("bot/out/live.log", "bot/out/live/live_status.json"):
        full = os.path.join(ROOT, p)
        try:
            print(f"{p}: {round((time.time() - os.path.getmtime(full)) / 3600, 2)}")
        except OSError:
            print(f"{p}: нет файла")

    rs = rows()
    print(f"\n=== журнал: {len(rs)} записей ===")
    kinds = {}
    for r in rs:
        k = str(r.get("kind") or r.get("ev") or "?").lower()
        kinds[k] = 1 + kinds.get(k, 0)
    print("состав:", kinds)

    # Вид записи сравнивается БЕЗ регистра: журнал пишет «close», а
    # первая версия искала «Close» и честно печатала ноль закрытий —
    # отказ, неотличимый от «сделок не было».
    def kind(r):
        return str(r.get("kind") or r.get("ev") or "").lower()

    closes = [r for r in rs if kind(r) == "close"]
    if closes:
        print("\nполя записи закрытия:", sorted(closes[-1].keys()))
    print(f"\n=== последние {args.last} закрытий ===")
    tot = 0.0
    for r in closes[-args.last:]:
        pnl = (r.get("pnl_usd") if r.get("pnl_usd") is not None
               else r.get("pnl"))
        tot += float(pnl or 0)
        print(f"{when(r.get('at_ms'))}  {r.get('sym', '?'):14s} "
              f"{r.get('side', '?'):5s}  pnl {pnl}  "
              f"причина: {r.get('reason') or r.get('why') or '—'}")
    print(f"\nсумма показанных закрытий: {round(tot, 2)} $")
    print(f"всего закрытий в журнале: {len(closes)}")

    # Деньги по суткам: где именно потеряно.
    by_day = {}
    for r in closes:
        d = time.strftime("%m-%d", time.gmtime((r.get("at_ms") or 0) / 1000))
        v = r.get("pnl_usd") if r.get("pnl_usd") is not None else r.get("pnl")
        by_day[d] = round(by_day.get(d, 0.0) + float(v or 0), 2)
    print("\n=== по суткам ===")
    for d in sorted(by_day):
        print(f"{d}: {by_day[d]:+.2f} $")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
