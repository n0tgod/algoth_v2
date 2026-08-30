#!/usr/bin/env python3
"""Диагностика шага книг: каталоги model_h24*, хвост журнала цикла.

Одноразовый инструмент наблюдения за деплоем h24c: печатает, какие
корзинные каталоги существуют и с какими манифестами, и хвост
`out/train.log` — по нему видно, до какого шага дошёл идущий цикл.
Ничего не пишет и не меняет.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def main():
    for name in ("model", "model_h24", "model_h24b", "model_h24bf",
                 "model_h24c"):
        d = os.path.join(OUT, name)
        if not os.path.isdir(d):
            print(f"{name}: каталога нет")
            continue
        mp = os.path.join(d, "manifest.json")
        man = {}
        if os.path.exists(mp):
            try:
                with open(mp, encoding="utf-8") as f:
                    man = json.load(f) or {}
            except ValueError:
                man = {"_": "манифест не читается"}
        pk = os.path.join(d, "picks.jsonl")
        n_pk = sum(1 for _ in open(pk, encoding="utf-8")) \
            if os.path.exists(pk) else 0
        print(f"{name}: выборов {n_pk}, манифест: "
              f"no_timer={man.get('no_timer')} "
              f"age={man.get('basket_age_h')} "
              f"take={man.get('basket_take_share')} "
              f"seq={man.get('train_seq')} "
              f"trained_at={man.get('trained_at')}")
    lp = os.path.join(OUT, "train.log")
    if os.path.exists(lp):
        with open(lp, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-40:]
        print("--- хвост train.log ---")
        for ln in tail:
            print(ln.rstrip())
    else:
        print("train.log не найден")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
