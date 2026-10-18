#!/usr/bin/env python3
"""Лёг ли ключ Anthropic и жив ли он (спека 19, этап N0). Ключ НЕ печатается.

Проверяет по порядку и печатает только вердикты:
1. файл `tools/app_api/out/anthropic_key.txt` есть, права 600 или строже,
   в нём одна строка нужной формы (печатаются длина и «форма верна», не
   знаки ключа);
2. `GET /v1/models` — ключ принят площадкой (бесплатный вызов), число
   доступных моделей;
3. один вызов `POST /v1/messages` с `max_tokens 1` самой младшей моделью
   из списка — есть ли деньги на балансе (без пополнения ключ «жив», но
   запросы отклоняются). Цена — доли цента; печатаются токены вызова.

Любой текст ответа площадки, прежде чем попасть в лог, проходит замену
ключа на звёздочки — лог уходит в git.

    run tools/anthropic_key_check.py
"""
import json
import os
import stat
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "tools", "app_api", "out", "anthropic_key.txt")
API = "https://api.anthropic.com"
VERSION = "2023-06-01"


def read_key(path=PATH):
    """→ (ключ или None, список вердиктов). Ключ наружу не выходит."""
    if not os.path.exists(path):
        return None, [f"НЕТ: файла {os.path.relpath(path, ROOT)} нет"]
    out = []
    mode = stat.S_IMODE(os.stat(path).st_mode)
    out.append(f"права файла {oct(mode)}" + ("" if mode & 0o077 == 0 else " — ШИРЕ 600, выполните chmod 600"))
    with open(path, encoding="utf-8") as f:
        lines = [x.strip() for x in f.read().splitlines() if x.strip()]
    if len(lines) != 1:
        return None, out + [f"НЕТ: в файле {len(lines)} непустых строк, нужна одна"]
    k = lines[0].strip("'\"")
    if not k.startswith("sk-ant-"):
        return None, out + [f"НЕТ: строка не начинается с sk-ant- (длина {len(k)})"]
    if any(c.isspace() for c in k):
        return None, out + ["НЕТ: в ключе пробел — скопирован с переносом"]
    return k, out + [f"форма верна, длина {len(k)}"]


def scrub(text, key):
    return text.replace(key, "***") if key else text


def call(key, method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=(json.dumps(body).encode() if body else None),
                                 headers={"x-api-key": key, "anthropic-version": VERSION,
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:200]}


def err_of(doc):
    e = (doc or {}).get("error") or {}
    return f"{e.get('type') or '?'}: {e.get('message') or doc.get('raw') or ''}"[:200]


def main():
    key, notes = read_key()
    for n in notes:
        print(n)
    if not key:
        print("ИТОГ: ключ не лёг")
        return 1
    code, doc = call(key, "GET", "/v1/models?limit=100")
    if code != 200:
        print(scrub(f"ИТОГ: площадка ключ НЕ приняла — HTTP {code}, {err_of(doc)}", key))
        return 1
    ids = [m.get("id") for m in doc.get("data") or [] if m.get("id")]
    print(f"ключ принят: моделей доступно {len(ids)}: {', '.join(ids[:12])}")
    small = [i for i in ids if "haiku" in i] or ids
    if not small:
        print("ИТОГ: ключ принят, но список моделей пуст — баланс не проверить")
        return 1
    model = small[0]
    code, doc = call(key, "POST", "/v1/messages",
                     {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]})
    if code == 200:
        u = doc.get("usage") or {}
        print(f"вызов {model}: ответ есть, токенов вход {u.get('input_tokens')}, выход {u.get('output_tokens')}")
        print("ИТОГ: ключ лёг и жив, баланс есть")
        return 0
    print(scrub(f"вызов {model}: HTTP {code}, {err_of(doc)}", key))
    print("ИТОГ: ключ лёг и принят, но вызов отклонён — смотрите причину выше (чаще всего баланс)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
