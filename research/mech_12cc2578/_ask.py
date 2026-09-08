"""Дописать в отчёт постройки просьбу к владельцу — ДОСЛОВНЫМ повтором
уже открытой просьбы `4c923cf1`.

Ключ просьбы есть хеш её текста (`asks.key_of`), поэтому дословный
повтор означает: новой строки на странице владельца не появится
(`asks.record` дубль по ключу не пишет), а механика встанет в очереди
как «ждёт владельца», а не «построена» — что и есть правда, пока шага
`fix` нет. Своими словами тот же вопрос завёл бы вторую просьбу об
одном и том же, а страница, которая шумит, не читается.

Файл разовый и лежит в каталоге механики; публиковать его не нужно.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))

import asks as AK                                            # noqa: E402

ASKS = os.path.join(ROOT, "research", "factory", "out", "asks.jsonl")
BUILD = os.path.join(ROOT, "research", "factory", "out", "build.json")

WHY = (
    "Шаг (2) задания построен и проверен (research/factory/horizon.py, "
    "21 блок проверок, 20 кусающихся контролей), но шаг (1) — правка "
    "research/s8_loop/train.py — строителю недоступен: каталог не его, "
    "роль fix назначает владелец. Пока полей 24 ч в листе нет, реплей "
    "строки h24_z_f30_w5_gt_rr0_se_b0_a1 даёт ноль ног, и это сказано "
    "вслух («лист сечения не несёт fwd_24h: в нём fwd_4h»), а не молча "
    "нулём. После правки исполнимых сочетаний станет 1584 из 5184 "
    "вместо 1296, и строку можно объявлять тем же кругом."
)


def main():
    rows = []
    with open(ASKS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    ask = [r for r in rows
           if r.get("id") == "4c923cf1" and r.get("ev") == "ask"][0]
    if AK.key_of(ask["what"]) != "4c923cf1":
        raise SystemExit("ключ не воспроизводится — дубль был бы неизбежен")
    with open(BUILD, encoding="utf-8") as f:
        d = json.load(f)
    d["needs_owner"] = [{"what": ask["what"], "why": WHY,
                         "unblocks": ask.get("unblocks") or ""}]
    with open(BUILD, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("просьба записана, её ключ:",
          AK.key_of(d["needs_owner"][0]["what"]),
          "— новой строки на странице не появится")


if __name__ == "__main__":
    main()
