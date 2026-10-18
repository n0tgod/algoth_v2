#!/usr/bin/env python3
"""Заглянуть в запись состояния рынка на сервере (только чтение).

Печатает: число строк по источникам за сегодня, последние строки событий
с метками времени словами, и сырые поля трёх свежих объявлений Bybit —
чтобы спор «почему событий за сутки ноль» решался фактом, а не памятью о
полях ответа.

    run research/market_state/peek.py
"""
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import collect as C                                          # noqa: E402


def when(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return f"?{ms}"


def main():
    day = datetime.now(timezone.utc).date().isoformat()
    path = os.path.join(C.RECORD, f"state-{day}.jsonl")
    cnt = Counter(); events = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                cnt[r.get("src")] += 1
                if r.get("src") == "event":
                    events.append(r)
    print(f"строк за {day} по источникам: {dict(cnt)}")
    print(f"событий в записи: {len(events)}; последние 8:")
    for e in events[-8:]:
        print(f"  t={e.get('t')} ({when(e.get('t'))}) {e.get('venue')} {e.get('kind')}: {str(e.get('title'))[:90]}")
    try:
        doc = C.http_json(f"{C.BYBIT}/v5/announcements/index?locale=en-US&limit=3")
        for it in ((doc.get("result") or {}).get("list") or []):
            print("bybit raw:", {k: (str(v)[:60]) for k, v in it.items() if k != "description"})
    except Exception as e:                                   # noqa: BLE001
        print("bybit announcements не получены:", e)
    try:
        doc = C.http_json(C.BINANCE_CMS + "48")
        cats = ((doc.get("data") or {}).get("catalogs") or [])
        for c in cats[:1]:
            print("binance catalog:", c.get("catalogId"), c.get("catalogName"))
            for a in (c.get("articles") or [])[:2]:
                print("  article:", {k: str(v)[:60] for k, v in a.items()})
    except Exception as e:                                   # noqa: BLE001
        print("binance cms не получен:", e)
    print("сейчас:", int(time.time() * 1000), when(time.time() * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
