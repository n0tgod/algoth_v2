"""Зонд: какие поля справочника Bybit отличают перпы на акции от крипты.

Печатает все поля нескольких эталонных имён и распределение полей с
малым числом значений по всему справочнику — чтобы правило «не-крипто»
читалось с биржи, а не велось списком. Ничего не пишет, ключей не
трогает: публичный эндпоинт.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "research", "b1_book"))
import collect as C                                        # noqa: E402

REF = ("BTCUSDT", "DOGEUSDT", "AMZUUSDT", "METAUSDT", "SHOPUSDT",
       "KODEX200USDT", "EURUSDUSDT", "XAUUSDT", "CVXSTOCKUSDT", "PURRUSDT")


def main():
    got = C.fetch_instruments()
    by = {it.get("symbol"): it for it in got}
    print(f"инструментов: {len(got)}")
    for s in REF:
        print(s, json.dumps(by.get(s), ensure_ascii=False)[:900])
    vals = collections.defaultdict(collections.Counter)
    for it in got:
        for k, v in it.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                vals[k][str(v)] += 1
    print("--- поля с числом значений ≤ 12 ---")
    for k, c in sorted(vals.items()):
        if len(c) <= 12:
            print(k, dict(c.most_common()))
    for k, c in sorted(vals.items()):
        if 1 < len(c) <= 12 and k not in ("status", "contractType",
                                          "quoteCoin", "settleCoin"):
            for v, n in c.items():
                if n <= 400:
                    names = sorted(it["symbol"] for it in got
                                   if str(it.get(k)) == v)
                    print(f"{k}={v} ({n}): {' '.join(names)[:3000]}")


if __name__ == "__main__":
    main()
