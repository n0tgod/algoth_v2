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
    """Пути, названные в тексте.

    ГОЛОЕ ИМЯ ФАЙЛА указателем не считается, и это не придирка: в
    проекте десяток файлов `probe.py`, и «candidate.py:186» не говорит,
    какой именно. Проверять существование такого имени в корне
    репозитория тем более бессмысленно — первый же прогон
    предлагающего был отвергнут за три упоминания в прозе, каждое из
    которых было верным.

    Указатель — путь от корня, то есть с косой чертой.
    """
    seen, out = set(), []
    for m in CITE_RE.finditer(text or ""):
        p = m.group(0)
        if "/" not in p or p in seen:
            continue
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

    # СТРОГО проверяется список `cites` — это объявленное свидетельство
    # заявки. В прозе путь может быть назван и для того, чтобы сказать
    # «его ещё нет»: первый прогон предлагающего был отвергнут в том
    # числе за честное «research/factory/ceiling.py отсутствует».
    # Такое отмечается, но заявку не валит; ловить выдумку в прозе —
    # работа адверсария, а не формы.
    declared = [c for c in (d.get("cites") or []) if isinstance(c, str)]
    got = cites(" ".join(declared))
    missing = [c for c in got if not os.path.exists(os.path.join(root, c))]
    if len(got) < PROPOSAL_MIN_CITES:
        bad.append(f"указателей {len(got)}, а нужно не меньше "
                   f"{PROPOSAL_MIN_CITES}: заявка без ссылок на замеры "
                   "неотличима от догадки")
    if missing:
        bad.append("в cites названы несуществующие файлы: "
                   + ", ".join(sorted(missing)[:5]))
    # Проза НЕ сканируется намеренно: путь в ней бывает назван именно
    # затем, чтобы сказать «его ещё нет», и такое утверждение полезно.
    # Ловить выдумку в прозе — работа адверсария, а не формы.
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
    elif role == "adversary":
        ok, why = check_adversary(
            texts.get("research/factory/out/adversary.json", ""), root)
        if not ok:
            bad.append("adversary.json: " + "; ".join(why))
    elif role == "build":
        ok, why = check_build(
            texts.get("research/factory/out/build.json", ""), root)
        if not ok:
            bad.append("build.json: " + "; ".join(why))
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


# --- контракт строителя ----------------------------------------------

BUILD_MIN_WHY = 120
# Предел числа подделок и общий бюджет времени на их проверку.
#
# Первая версия ставила предел 8 и ОТВЕРГЛА починку с десятью
# контролями — при том что задание требовало закрепить шесть находок
# адверсария. Предел, наказывающий за тщательность, есть неверный
# предел: настоящее ограничение здесь — время, а не счёт. Счёт
# оставлен грубой страховкой от бессмысленной сотни, а связывает
# бюджет: не проверенные целиком контроли — отказ с названной
# причиной, а не молчаливое «первые восемь сошлись».
BUILD_MAX_CONTROLS = 24
BUILD_CONTROLS_BUDGET = 1800
# Сколько ждать прогон тестов кандидата.
BUILD_TEST_TIMEOUT = 900


def _run_tests(root, tests):
    """Прогнать тесты кандидата. Возвращает (прошли, вывод)."""
    import subprocess
    import sys
    py = os.path.join(root, ".venv", "bin", "python")
    if not os.path.exists(py):
        py = sys.executable
    try:
        r = subprocess.run([py, tests], cwd=root, capture_output=True,
                           text=True, timeout=BUILD_TEST_TIMEOUT)
    except Exception as e:                                # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:]


def check_build(text, root):
    """Постройка годна? Возвращает (годно, список бед).

    Главное здесь — не «тесты зелёные», а **кусаются ли негативные
    контроли**. Проверка, которая не кусается, не проверяет ничего, и
    таких в этом проекте находили десятками. Поэтому каждая подделка
    применяется к КОПИИ файла, тесты прогоняются заново и обязаны
    упасть; контроль, который не укусил, валит весь прогон.

    Отсюда же следует, что отчёт «построено» без кусающихся контролей
    получить нельзя: их проверяет машина, а не автор.
    """
    bad = []
    try:
        d = json.loads(text or "")
    except ValueError as e:
        return False, [f"отчёт постройки не разбирается как JSON: {e}"]
    if not isinstance(d, dict) or not isinstance(d.get("built"), bool):
        return False, ["нет поля built (да/нет)"]
    if not d["built"]:
        why = (d.get("why") or "").strip()
        if len(why) < BUILD_MIN_WHY:
            bad.append(f"неудача не объяснена: {len(why)} символов при "
                       f"минимуме {BUILD_MIN_WHY}")
        return (not bad), bad

    mod = (d.get("module") or "").strip()
    tests = (d.get("tests") or "").strip()
    for name, rel in (("модуль", mod), ("тесты", tests)):
        if not rel:
            bad.append(f"{name}: путь не назван")
        elif not os.path.exists(os.path.join(root, rel)):
            bad.append(f"{name}: файла нет — {rel}")
    if bad:
        return False, bad

    ok, out = _run_tests(root, tests)
    if not ok:
        return False, ["тесты кандидата не проходят: "
                       + out.strip().splitlines()[-1][:300]
                       if out.strip() else "тесты кандидата не проходят"]

    controls = d.get("controls") or []
    if not isinstance(controls, list) or not controls:
        return False, ["негативных контролей нет: проверка, которая не "
                       "кусается, не проверяет ничего"]
    if len(controls) > BUILD_MAX_CONTROLS:
        return False, [f"контролей {len(controls)}, а предел "
                       f"{BUILD_MAX_CONTROLS}"]

    started = time.time()
    for i, c in enumerate(controls, 1):
        if time.time() - started > BUILD_CONTROLS_BUDGET:
            bad.append(f"бюджет проверки контролей исчерпан на {i}-м из "
                       f"{len(controls)}: непроверенный контроль не "
                       "считается кусающимся")
            break
        rel = (c.get("file") or "").strip()
        old = c.get("old") or ""
        new = c.get("new") or ""
        want = (c.get("expect") or "").strip()
        p = os.path.join(root, rel)
        # Портить можно только СВОИ файлы: подделка чужого модуля
        # проверяла бы чужую проверку, а заодно роняла бы соседей.
        if not rel.startswith("research/factory/") or ".." in rel:
            bad.append(f"контроль {i}: файл вне своего каталога — {rel}")
            continue
        if not os.path.exists(p):
            bad.append(f"контроль {i}: файла нет — {rel}")
            continue
        with open(p, encoding="utf-8") as f:
            src = f.read()
        if not old or src.count(old) != 1:
            bad.append(f"контроль {i}: строка встречается "
                       f"{src.count(old) if old else 0} раз, а нужна "
                       "ровно одна — подделка обязана быть точной")
            continue
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src.replace(old, new, 1))
            fell, out = _run_tests(root, tests)
        finally:
            with open(p, "w", encoding="utf-8") as f:
                f.write(src)
        if fell:
            bad.append(f"контроль {i} НЕ КУСАЕТСЯ: подделка прошла "
                       "мимо тестов")
        elif want and want not in out:
            bad.append(f"контроль {i}: упало не то, что обещано "
                       f"({want!r} в выводе нет)")
    return (not bad), bad


# --- контракт адверсария ---------------------------------------------

ADV_MIN_TRIES = 3
ADV_MIN_HOW = 40
ADV_MIN_WHY = 100
ADV_VERDICTS = ("veto", "pass", "undetermined")


def check_adversary(text, root):
    """Разбор адверсария годен? Возвращает (годно, список бед).

    Проверяется ровно одно, зато главное: отличимо ли «не смог
    сломать» от «не пробовал». Отличает их только список попыток, и
    попытка настоящая, если названо КОНКРЕТНОЕ действие — какой файл
    подделан, какая команда запущена, какое число пересчитано.

    Содержательную силу атак это не проверяет и не притворяется, что
    проверяет: сильнее адверсария в системе никого нет.
    """
    bad = []
    try:
        d = json.loads(text or "")
    except ValueError as e:
        return False, [f"разбор не читается как JSON: {e}"]
    if not isinstance(d, dict):
        return False, ["разбор не объект"]
    v = d.get("verdict")
    if v not in ADV_VERDICTS:
        bad.append("вердикт обязан быть одним из "
                   + ", ".join(ADV_VERDICTS)
                   + ": «не смог сломать» и «не могу подтвердить» — "
                     "разные ответы, и склеивать их нельзя")
    tried = d.get("tried")
    if not isinstance(tried, list) or len(tried) < ADV_MIN_TRIES:
        bad.append(f"попыток {len(tried) if isinstance(tried, list) else 0}"
                   f", а нужно не меньше {ADV_MIN_TRIES}: пустой список "
                   "означает «не пробовал», а не «не сломалось»")
        tried = []
    for i, t in enumerate(tried, 1):
        if not isinstance(t, dict):
            bad.append(f"попытка {i}: не объект")
            continue
        for f, n in (("attack", 10), ("how", ADV_MIN_HOW), ("result", 10)):
            got = (t.get(f) or "").strip()
            if len(got) < n:
                bad.append(f"попытка {i}: поле {f} короче {n} символов — "
                           "«просмотрел код» попыткой не является")
    if v == "veto" and len((d.get("why") or "").strip()) < ADV_MIN_WHY:
        bad.append(f"вето без объяснения: нужно не меньше {ADV_MIN_WHY} "
                   "символов о том, что именно сломано")
    got = cites(" ".join(c for c in (d.get("cites") or [])
                         if isinstance(c, str)))
    missing = [c for c in got if not os.path.exists(os.path.join(root, c))]
    if missing:
        bad.append("в cites названы несуществующие файлы: "
                   + ", ".join(sorted(missing)[:5]))
    return (not bad), bad
