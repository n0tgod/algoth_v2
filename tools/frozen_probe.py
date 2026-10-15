"""Зонд: пишет ли цикл лист замороженной модели и ложится ли архив весов.

Печатает `frozen/frozen.json`, число строк и последние часы
`model_sit/sheets_frozen.jsonl` (час, номер заморозки, номер живого
обучения, рук, имён), и состав `archive/`. Ничего не меняет.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "research", "s8_loop"))
import train as T                                             # noqa: E402


def main():
    fd = T.frozen_dir()
    try:
        with open(os.path.join(fd, "frozen.json"), encoding="utf-8") as f:
            print("заморозка:", json.load(f))
    except (OSError, ValueError) as e:
        print("заморозки нет:", e)
    p = os.path.join(T.MODEL_DIR + "_sit", "sheets_frozen.jsonl")
    rows = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                rows.append((r.get("hour"), r.get("train_seq"), r.get("live_seq"),
                             {a: len(v) for a, v in (r.get("arms") or {}).items()}))
        print(f"sheets_frozen.jsonl: {len(rows)} строк, {os.path.getsize(p) / 1e6:.1f} МБ")
        for r in rows[-5:]:
            print("  ", r)
    except OSError as e:
        print("sheets_frozen.jsonl нет:", e)
    ad = os.path.join(T.MODEL_DIR, T.ARCHIVE_DIR_NAME)
    print("архив:", sorted(os.listdir(ad)) if os.path.isdir(ad) else "пуст (первое обучение после деплоя ещё не прошло)")
    # живой лист — для сверки часа
    lp = os.path.join(T.MODEL_DIR + "_sit", "sheets.jsonl")
    try:
        with open(lp, "rb") as f:
            f.seek(max(0, os.path.getsize(lp) - 2_000_000))
            last = [ln for ln in f.read().decode("utf-8", "ignore").split("\n") if ln.startswith("{")][-1]
        print("живой лист, последний час:", last[:120])
    except (OSError, IndexError) as e:
        print("живой лист:", e)


if __name__ == "__main__":
    main()
