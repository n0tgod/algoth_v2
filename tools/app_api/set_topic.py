#!/usr/bin/env python3
"""Сменить тему пушей APNs (Bundle ID приложения) в `out/apns.json`.

10.10: первый пробный пуш ответил `400 TopicDisallowed` — сервер слал
на `pl.mdsauto.algoth` из project.yml, а сборка подставляет Bundle ID из
секрета `IOS_BUNDLE_ID`, и он `algoth`. Тема читается при каждой
отправке — перезапуск API не нужен. Значение — буквы, цифры, точка,
дефис, подчёркивание; ключ файла не печатается.

    run tools/app_api/set_topic.py algoth
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "out", "apns.json")
OK = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def main(argv):
    if len(argv) != 1 or not OK.match(argv[0]):
        print("ОТКАЗ: ровно одно значение из букв, цифр, точки, дефиса и подчёркивания")
        return 2
    try:
        with open(PATH, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError) as e:
        print(f"ОТКАЗ: ключ APNs не задан ({e}) — сперва Set APNs key в приложении")
        return 1
    was = c.get("topic")
    c["topic"] = argv[0]
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PATH)
    print(f"тема пушей: {was!r} → {argv[0]!r}; ключ {c.get('key_id')} на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
