#!/usr/bin/env python3
"""Заморозить текущие веса S8: копия в `out/model/frozen/`.

Решение владельца 2026-10-15: проверить, что даёт ежедневное
переобучение. Старые веса не хранились (каждое обучение перезаписывало
файл), поэтому эксперимент идёт ВПЕРЁД: с этого дня цикл пишет лист
сечения ещё и замороженными весами (`train.frozen_sheets`), а через
недели реплей Ladder по двум журналам сравнит модели.

Ничего не обучает и живые веса не трогает. Заморозка уже есть — отказ
(иначе эксперимент сдвинулся бы молча); `--replace` заменяет сознательно.

    run tools/freeze_weights.py
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import train as T                                             # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    dst = T.frozen_dir()
    if os.path.isdir(dst) and not a.replace:
        try:
            with open(os.path.join(dst, "frozen.json"), encoding="utf-8") as f:
                was = json.load(f)
        except (OSError, ValueError):
            was = {}
        print(f"заморозка уже есть: обучение №{was.get('train_seq')} от "
              f"{was.get('frozen_at')} — не трогаю (--replace заменит)")
        return 2
    try:
        with open(os.path.join(T.MODEL_DIR, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f) or {}
    except (OSError, ValueError) as e:
        print(f"манифест модели не читается: {e}")
        return 1
    os.makedirs(dst, exist_ok=True)
    n, size = 0, 0
    for arm, _ in T.ARMS:
        for tgt in T.TARGETS:
            p = os.path.join(T.MODEL_DIR, f"weights_{arm}_{tgt}.pkl")
            if not os.path.exists(p):
                print(f"нет весов {os.path.basename(p)} — заморозка неполная, отказ")
                shutil.rmtree(dst, ignore_errors=True)
                return 1
            shutil.copy2(p, os.path.join(dst, os.path.basename(p)))
            n += 1
            size += os.path.getsize(p)
    shutil.copy2(os.path.join(T.MODEL_DIR, "manifest.json"),
                 os.path.join(dst, "manifest.json"))
    info = {"train_seq": man.get("train_seq"), "trained_upto": man.get("trained_upto"),
            "frozen_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "files": n, "bytes": size}
    with open(os.path.join(dst, "frozen.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    models, seq, why = T.load_frozen_models(None)
    if models is None:
        print(f"заморозка легла, но не читается: {why}")
        return 1
    print(f"заморожено обучение №{info['train_seq']} (до {info['trained_upto']}): "
          f"{n} файлов, {size / 1e6:.1f} МБ; цикл с этого часа пишет sheets_frozen.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
