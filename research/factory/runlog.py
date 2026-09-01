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
#
# ПОРЯДОК ВЕТОК ЗНАЧИМ, и это дефект, найденный первым же боевым
# прогоном роли: в питоне альтернация берёт ПЕРВОЕ совпадение, а не
# самое длинное, поэтому при порядке «json | jsonl» путь `ledger.jsonl`
# обрезался до `ledger.json`, файла с таким именем нет — и бриф
# объявлялся выдумкой целиком. Практически это запрещало ролям
# ссылаться ровно на два файла, которые описывают состояние фабрики:
# журнал объявлений и журнал прогонов.
#
# Длинные ветки идут первыми, и хвост закрыт проверкой: после
# расширения не должно стоять ни буквы, ни цифры.
CITE_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_./-]*"
    r"\.(?:jsonl|json|py|md|sh|js|csv|txt)(?![A-Za-z0-9_])")


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


# --- контракты ролей -------------------------------------------------
#
# Модель производит, машина проверяет. Содержательную верность это не
# проверяет и не притворяется, что проверяет: для неё есть адверсарий.
# Здесь ловится ровно то, что ловится без читателя — форма, размер,
# существование названных файлов и согласие с уже объявленным.

PROPOSAL_MIN = {"hypothesis": 80, "kills_it": 60, "ceiling": 80,
                "differs_from_live": 60}
PROPOSAL_MIN_CITES = 3
BRIEF_PATH = "research/factory/out/brief.md"
# Пустой день — законный ответ, но он обязан быть ОБОСНОВАН: иначе
# «сегодня нечего предложить» станет способом не работать, и отличить
# его от отказа будет нечем.
PROPOSAL_MIN_WHY = 120


def check_proposal(text, root, ledger_ids=(), space=None):
    """Предложение проверяемо? Возвращает (годно, список бед).

    Предложение — это заявка на ИСПЫТАНИЕ, и каждое испытание тратит
    бюджет доказательства. Поэтому форма жёсткая: что утверждается,
    чем убивается, каким дешёвым расчётом закрывается и чем отличается
    от уже живых. Красноречие здесь ничего не стоит, а проверяемость —
    всё.
    """
    bad = []
    try:
        d = json.loads(text or "")
    except ValueError as e:
        return False, [f"предложение не разбирается как JSON: {e}"]
    if not isinstance(d, dict):
        return False, ["предложение не объект"]

    if "proposed" not in d or not isinstance(d["proposed"], bool):
        return False, ["нет поля proposed (да/нет) — а пустой день "
                       "обязан быть назван, а не подразумеваться"]
    if not d["proposed"]:
        why = (d.get("why") or "").strip()
        if len(why) < PROPOSAL_MIN_WHY:
            bad.append(f"пустой день не обоснован: {len(why)} символов "
                       f"при минимуме {PROPOSAL_MIN_WHY}")
        return (not bad), bad

    kind = d.get("kind")
    if kind not in ("row", "mechanism"):
        bad.append("kind обязан быть row или mechanism: строку из "
                   "объявленного пространства судья умеет прогнать "
                   "сегодня, механизм ждёт строителя")
    if not (d.get("title") or "").strip():
        bad.append("нет названия")
    for f, n in PROPOSAL_MIN.items():
        v = (d.get(f) or "").strip()
        if len(v) < n:
            bad.append(f"поле {f}: {len(v)} символов при минимуме {n}")

    got = cites(json.dumps(d, ensure_ascii=False))
    missing = [c for c in got if not os.path.exists(os.path.join(root, c))]
    if len(got) < PROPOSAL_MIN_CITES:
        bad.append(f"указателей {len(got)}, а нужно не меньше "
                   f"{PROPOSAL_MIN_CITES}: заявка без ссылок на замеры "
                   "неотличима от догадки")
    if missing:
        bad.append("названы несуществующие файлы: "
                   + ", ".join(sorted(missing)[:5]))
    # Предложение обязано опираться на БРИФ. Что роль читала только
    # его, машине не проверить; что она на него сослалась — проверить
    # можно, и это отделяет заявку из состояния проекта от заявки из
    # общих соображений.
    if BRIEF_PATH not in got:
        bad.append(f"предложение не ссылается на {BRIEF_PATH}: заявка "
                   "не из состояния проекта, а из общих соображений")

    if kind == "row":
        rule = d.get("rule")
        if space is None:
            bad.append("строку проверить нечем: пространство не подано")
        else:
            why = space.validate(rule if isinstance(rule, dict) else {})
            if why:
                bad.append(f"правило вне объявленного пространства: {why}")
            else:
                un = space.unavailable(rule)
                if un:
                    bad.append(f"строка сегодня неисполнима: {un}")
                k = space.key(rule)
                if k in set(ledger_ids):
                    bad.append(f"кандидат {k} уже объявлен — повтор "
                               "тратит бюджет доказательства впустую")
    elif kind == "mechanism":
        if not (d.get("needs") or "").strip():
            bad.append("механизм не назвал, какого шага конвейера ждёт")
    return (not bad), bad


def check_role(role, root):
    """Контракт роли: выполнен ли. Возвращает (годно, список бед).

    Одно место на все роли — иначе перечень того, что роль обязана
    оставить, разошёлся бы с реестром и с промптом.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import agents as AG
    st = AG.by_key(role) or {}
    files = list(st.get("produces") or [])
    bad = []
    texts = {}
    for rel in files:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            bad.append(f"{rel}: не создан")
            continue
        with open(p, encoding="utf-8") as f:
            texts[rel] = f.read()
    if bad:
        return False, bad

    if role == "brief":
        for rel, budget, mn in (
                ("research/factory/out/brief.md", BRIEF_BUDGET_CHARS,
                 BRIEF_MIN_CITES),
                ("research/factory/out/summary.md", 6000, 1)):
            ok, why, _ = check_brief(texts.get(rel, ""), root, budget, mn)
            if not ok:
                bad.append(rel + ": " + "; ".join(why))
    elif role == "propose":
        import ledger as LG
        import space as SP
        rows, _ = LG.read(os.path.join(root, "research", "factory",
                                       "out", "ledger.jsonl"))
        ids = list(LG.state(rows).keys())
        ok, why = check_proposal(
            texts.get("research/factory/out/proposal.json", ""),
            root, ledger_ids=ids, space=SP)
        if not ok:
            bad.append("proposal.json: " + "; ".join(why))
    return (not bad), bad
