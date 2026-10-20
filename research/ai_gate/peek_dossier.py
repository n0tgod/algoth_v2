#!/usr/bin/env python3
"""Одно досье ветки ai_news из записи (только чтение, 20.10): какие поля
и в каком виде видит судья — для каталога полей уроков (§11.4). Печатает
досье без новостей (их текст — данные третьих лиц) и сводку числовых
листьев по всем досье записи: путь поля, сколько досье его несут, мин/макс."""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def leaves(d, pre=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from leaves(v, f"{pre}.{k}" if pre else k)
    elif isinstance(d, (int, float)) and not isinstance(d, bool):
        yield pre, float(d)


def main():
    files = sorted(glob.glob(os.path.join(HERE, "out", "record", "dossiers-*.jsonl")))
    print("файлов", len(files))
    stat, n, shown = {}, 0, False
    for p in files:
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("branch") != "ai_news" or not r.get("dossier"):
                continue
            d = r["dossier"]
            n += 1
            if not shown and d.get("crowd_positioning") and d.get("name_history_in_book"):
                show = {k: v for k, v in d.items() if k not in ("news_on_this_coin_72h", "market_headlines_24h")}
                print(json.dumps(show, ensure_ascii=False, indent=1)[:5000])
                shown = True
            for k, v in leaves({k: v for k, v in d.items() if k not in ("news_on_this_coin_72h", "market_headlines_24h")}):
                s = stat.setdefault(k, [0, v, v])
                s[0] += 1; s[1] = min(s[1], v); s[2] = max(s[2], v)
    print("досье ai_news:", n)
    for k in sorted(stat):
        print(f"  {k}: {stat[k][0]} [{stat[k][1]:.4g} … {stat[k][2]:.4g}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
