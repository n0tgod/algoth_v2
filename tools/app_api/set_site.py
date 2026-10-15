#!/usr/bin/env python3
"""Задать настройки сайта (`out/site.json`) с сервера через очередь —
то же, что панель оператора на /account, когда токен оператора не под
рукой. Ключи — только из SITE_KEYS сервера; значения проверяются тем же
правилом. Печатает итоговые настройки.

    run tools/app_api/set_site.py --apple_client_id=trade.algoth.web
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server as SV                                           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    for k in SV.SITE_KEYS:
        ap.add_argument(f"--{k}", default=None)
    a = ap.parse_args()
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    cur = SV.site_settings(out)
    for k in SV.SITE_KEYS:
        v = getattr(a, k)
        if v is None:
            continue
        if k == "apple_client_id" and not SV.SITE_ID.match(v):
            print(f"ОТКАЗ: {k}: только буквы, цифры, точки и дефисы"); return 2
        if k.endswith("_url") and v and not v.startswith("https://"):
            print(f"ОТКАЗ: {k} должен начинаться с https://"); return 2
        cur[k] = v
    path = os.path.join(out, "site.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)
    print("настройки сайта:", json.dumps(cur, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
