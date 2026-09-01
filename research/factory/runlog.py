#!/usr/bin/env python3
"""
Журнал прогонов ролей и механическая проверка того, что роль
произвела.

Зачем отдельно от журнала объявлений: тот отвечает на вопрос «сколько
испытаний потрачено», этот — на вопрос «работает ли система вообще».
Смешав их, мы получили бы знаменатель доказательства, растущий от
служебных пробуждений.

Журнал лежит в `out`, потому что `publish.sh` публикует
`research/*/out`: прогон, чья строка осталась на сервере, неотличим от
прогона, которого не было. Дозапись, а не таблица — по той же
причине, что у объявлений: упавший посередине прогон дочитывается
следующим.

**Проверка брифа механическая намеренно.** Главный отказ этой схемы —
агенты пишут друг другу правдоподобный текст, и он становится фактом
без сверки с данными. Модель просить себя проверить бесполезно;
машина же способна на две вещи: посчитать размер и убедиться, что
названные файлы существуют. Бриф, ссылающийся на несуществующий файл,
есть выдумка, пойманная без читателя.
"""

import json
import os
import re
import time

RUNS = "agents-runs.jsonl"

# Потолок брифа. Роль предлагающего читает ТОЛЬКО бриф, и весь смысл
# сторожа — не платить 216 тысячами токенов памяти за каждый вызов.
# Русский текст идёт примерно по 2.2 символа на токен, поэтому 15 тыс.
# токенов — это около 33 тыс. символов. Число объявлено здесь, а не в
# промпте: промпт просит, а обязывает проверка.
BRIEF_BUDGET_CHARS = 33000

# Бриф без указателей брифом не является: утверждение без ссылки на
# файл и число нечем оспорить. Три — не «достаточно», а «хоть
# сколько-то»: ниже этого текст просто не о наших данных.
BRIEF_MIN_CITES = 3

# Что считается указателем. Расширения — те, в которых у нас живут
# данные и код; голое слово путём не является.
CITE_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|md|json|jsonl|sh|js|csv|txt)")


def append(path, role, status, started, ended=None, note=None,
           dry=False, out_bytes=None, pid=None):
    """Дозаписать строку прогона. Возвращает записанную строку.

    Статус `start` пишется В НАЧАЛЕ прогона и несёт номер процесса.
    Без него «работает сейчас» неотличимо от «не запускалась»: роль
    оставляла бы след только по завершении, а владелец спрашивает
    состояние именно во время работы.
    """
    row = {"at": round(time.time(), 3), "role": role, "status": status,
           "started": round(started, 3),
           "ended": round(ended if ended is not None else time.time(), 3),
           "dry": bool(dry)}
    if pid is not None:
        row["pid"] = int(pid)
    if note:
        row["note"] = str(note)[:2000]
    if out_bytes is not None:
        row["out_bytes"] = int(out_bytes)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def read(path):
    """Прочитать журнал. Возвращает (строки, число битых).

    Битая строка СЧИТАЕТСЯ, а не проглатывается: обрыв записи посреди
    строки — законное состояние дозаписи, но молчаливый пропуск
    превратил бы его в «прогонов было меньше».
    """
    rows, broken = [], 0
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    broken += 1
    except OSError:
        return [], 0
    return rows, broken


def last_by_role(rows):
    """Последний прогон каждой роли — по времени, а не по порядку строк.

    Порядок строк совпадает с временем почти всегда, и «почти» здесь
    достаточно, чтобы однажды показать позавчерашний прогон свежим.

    Ничья решается в пользу ПОЗДНЕЙ строки: метка округлена до
    миллисекунды, и два пробуждения подряд (отказ сразу за отказом)
    получают одну и ту же. Со строгим сравнением побеждала первая, и
    страница показывала бы предыдущий отказ как текущее состояние —
    найдено собственным тестом до первого живого прогона.
    """
    out = {}
    for r in rows:
        k = r.get("role")
        if not k:
            continue
        if k not in out or (r.get("at") or 0) >= (out[k].get("at") or 0):
            out[k] = r
    return out


def ok_runs(rows):
    """Роли, у которых был хотя бы один НЕсухой успешный прогон.

    Сухой прогон модель не зовёт вовсе, поэтому засчитывать его как
    работу роли значило бы объявить построенным то, что ни разу не
    работало.
    """
    return {r.get("role") for r in rows
            if r.get("status") == "ok" and not r.get("dry")}


def cites(text):
    """Пути, названные в тексте."""
    seen, out = set(), []
    for m in CITE_RE.finditer(text or ""):
        p = m.group(0)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def check_brief(text, root, budget=BRIEF_BUDGET_CHARS,
                min_cites=BRIEF_MIN_CITES):
    """Механическая проверка брифа. Возвращает (годен, список бед, пути).

    Проверяется ровно то, что машина способна проверить без читателя:
    бриф не пуст, укладывается в потолок, называет файлы и НЕ называет
    несуществующих. Содержательную верность утверждений это не
    проверяет и не притворяется, что проверяет, — для неё есть
    адверсарий.
    """
    bad = []
    text = text or ""
    if not text.strip():
        bad.append("бриф пуст")
    if len(text) > budget:
        bad.append(f"бриф длиннее потолка: {len(text)} против {budget}")
    got = cites(text)
    if len(got) < min_cites:
        bad.append(f"указателей {len(got)}, а нужно не меньше "
                   f"{min_cites}: утверждение без ссылки нечем оспорить")
    missing = [p for p in got
               if not os.path.exists(os.path.join(root, p))]
    if missing:
        bad.append("названы несуществующие файлы: "
                   + ", ".join(sorted(missing)[:5]))
    return (not bad), bad, got


def alive(pid):
    """Жив ли процесс. Мёртвый номер значит «прогон оборван»."""
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def state_of(rows):
    """По каждой роли: идёт ли прогон сейчас и чем кончился прошлый.

    Различать обязательно. «Работает» и «последний прогон» — разные
    вопросы, и склеив их, страница показывала бы старый отказ во время
    исправного прогона.

    Оборванный прогон (строка `start`, чей процесс мёртв) НЕ считается
    идущим: иначе убитая роль вечно выглядела бы работающей — тревога,
    которой нет, хуже её отсутствия.
    """
    out = {}
    for r in sorted(rows, key=lambda x: (x.get("at") or 0)):
        k = r.get("role")
        if not k:
            continue
        st = out.setdefault(k, {"running": None, "last": None,
                                "broken": None})
        if r.get("status") == "start":
            st["running"] = r
        else:
            # Любая незапускающая строка закрывает начатый прогон.
            st["running"] = None
            st["last"] = r
    for k, st in out.items():
        r = st["running"]
        if r is not None and not alive(r.get("pid")):
            st["running"] = None
            st["broken"] = r
    return out


def history(rows, role, limit=20):
    """Последние строки роли, новые сверху."""
    got = [r for r in rows if r.get("role") == role]
    got.sort(key=lambda x: (x.get("at") or 0), reverse=True)
    return got[:limit]
