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

import calendar
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


# Отказ по лимиту аккаунта — ОЖИДАНИЕ, а не поломка, и статус у него
# свой. Разница не косметическая: попытка, упёршаяся в лимит, не
# должна тратить суточный бюджет попыток — иначе три лимита подряд
# выбивают роль из круга на сутки, хотя лимит снимается через час.
# Решение владельца (2026-09-02): роль, остановленная лимитом,
# возобновляется САМА по его истечении.
LIMIT = "limit"

# Запас, когда ответ не назвал момента снятия. Не угадываем время по
# тексту: лучше подождать объявленное и сказать, что ждём именно
# запас, чем выдумать точность, которой нет.
LIMIT_BACKOFF_SEC = 1800


def limit_retry_at(text, now=None):
    """Когда пробовать снова после отказа по лимиту: (момент, откуда).

    CLI при исчерпании квоты называет момент снятия эпохой в секундах
    (`...limit reached|1788350400`) либо не называет вовсе. Разбираются
    обе формы плюс `retry-after`; чего в ответе нет, то не выдумывается
    — берётся объявленный запас, и ОТКУДА взят момент, возвращается
    рядом: «ждём до 14:30» и «ждём полчаса, потому что нам не сказали»
    — разные утверждения, и владелец вправе их различать.
    """
    now = time.time() if now is None else now
    t = str(text or "")
    # Эпоха рядом со словом о лимите. Диапазон проверяется: число из
    # чужой строки лога, принятое за момент снятия, увело бы роль в
    # ожидание на годы.
    for m in re.finditer(r"(?:limit|quota|лимит)[^\n]{0,80}?"
                         r"(\b1[6-9]\d{8}\b)", t, re.I):
        v = float(m.group(1))
        if now < v < now + 30 * 86400:
            return v, "момент снятия назван ответом"
    # Человеческая форма: «resets 10:20pm (UTC)». Найдена живым
    # отказом 2026-09-02 — момент снятия был НАЗВАН, а мы брали
    # объявленный запас, то есть теряли знание, которое нам дали.
    #
    # Часовой пояс обязан быть назван UTC: приняв чужие часы за наши,
    # мы отправили бы роль ждать не туда — на часы вперёд или назад, —
    # и это было бы хуже честного запаса.
    m = re.search(r"resets?\s+(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?"
                  r"[^\n]{0,24}\bUTC\b|resets?\s+(\d{1,2}):(\d{2})"
                  r"[^\n]{0,24}\bUTC\b", t, re.I)
    if m:
        if m.group(1) is not None:
            hh, mm = int(m.group(1)), int(m.group(2) or 0)
            ampm = (m.group(3) or "").lower()
            if ampm == "p" and hh != 12:
                hh += 12
            elif ampm == "a" and hh == 12:
                hh = 0
        else:
            hh, mm = int(m.group(4)), int(m.group(5))
        if 0 <= hh < 24 and 0 <= mm < 60:
            day = time.gmtime(now)
            v = calendar.timegm((day.tm_year, day.tm_mon, day.tm_mday,
                                 hh, mm, 0, 0, 0, 0))
            if v <= now:
                v += 86400.0
            return v, "момент снятия назван ответом (часы UTC)"
    m = re.search(r"retry[- ]after\D{0,10}(\d{1,6})", t, re.I)
    if m:
        v = now + float(m.group(1))
        if v < now + 30 * 86400:
            return v, "срок из retry-after"
    return now + LIMIT_BACKOFF_SEC, "момент снятия не назван, запас"


def limit_wait(rows, role, now=None):
    """Сколько секунд роли ещё ждать снятия лимита (0 — не ждёт).

    Смотрится ПОСЛЕДНЯЯ строка роли: за лимитом мог последовать
    удачный прогон, и старая отметка держала бы роль в ожидании
    после того, как она уже отработала.

    Ничья решается в пользу ПОЗДНЕЙ строки — по той же причине, что в
    `last_by_role`: метка округлена до миллисекунды, а два отказа
    подряд её делят. Со строгим сравнением побеждала первая, то есть
    роль ждала бы по ПРОШЛОМУ сроку снятия и не поднималась в тот
    такт, когда лимит уже истёк, — ровно то, чего требует правило
    «возобновляется сама».
    """
    now = time.time() if now is None else now
    got = [r for r in rows if r.get("role") == role
           and r.get("status") != "start"]
    if not got:
        return 0.0
    last = got[0]
    for r in got[1:]:
        if (r.get("at") or 0) >= (last.get("at") or 0):
            last = r
    if last.get("status") != LIMIT:
        return 0.0
    return max(0.0, float(last.get("retry_at") or 0) - now)


def append(path, role, status, started, ended=None, note=None,
           dry=False, out_bytes=None, pid=None, retry_at=None):
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
        # Пояснение приходит из чужого вывода (модель, обрезанный
        # хвост лога), и обрезка по БАЙТАМ рвёт utf-8 посередине —
        # `json.dumps` на одиноком суррогате бросает, и строка не
        # пишется ВОВСЕ. Потерянная строка журнала есть отказ,
        # неотличимый от тишины: страница вечно показывает прогон
        # оборванным. Порченый знак заменяется, строка остаётся.
        row["note"] = str(note)[:2000].encode(
            "utf-8", "replace").decode("utf-8")
    if out_bytes is not None:
        row["out_bytes"] = int(out_bytes)
    if retry_at is not None:
        row["retry_at"] = round(float(retry_at), 3)
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


def fails_since_ok(rows, role):
    """Сколько попыток роли ПОДРЯД кончились отказом и чем — с последнего
    успеха.

    Найдено 2026-09-02 на живом сервере: `scout` трижды звали, и каждый
    раз CLI отвечал «does not support this model», — а страница
    показывала это как «не отрабатывал ни разу», то есть как ТИШИНУ.
    Тишина и повторяющийся названный отказ лечатся по-разному: первая
    означает «расписание не дошло», второй — «дошло, и вот причина».
    Свести их в одно значило бы вернуть отказ, неотличимый от тишины,
    через показ.

    Считаются только НЕсухие попытки, у которых модель звали: `start`,
    `busy` и `fallback` — служебные строки одного и того же прогона, а
    не отдельные попытки.

    Лимит аккаунта (`LIMIT`) отказом здесь НЕ считается, и это то же
    решение, по которому он не поднимает тревогу тишины: у него есть
    собственное состояние и собственный момент повтора, он снимется
    сам. Мера отвечает на другой вопрос — сколько попыток подряд
    отказали ТАК, что само не пройдёт.

    Возвращает (сколько, последняя причина).
    """
    got = [r for r in rows
           if r.get("role") == role and not r.get("dry")
           and r.get("status") not in ("start", "busy", "fallback",
                                       LIMIT)]
    got.sort(key=lambda x: (x.get("at") or 0))
    n, note = 0, None
    for r in reversed(got):
        if r.get("status") == "ok":
            break
        n += 1
        if note is None:
            note = r.get("note")
    return n, note


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

    Строка `fallback` прогона НЕ закрывает: её пишет тот же процесс
    посреди работы, когда переходит на запасную модель. Найдено на
    живом прогоне разведчика — с откатом на постоянный отказ модели
    (2026-09-02) такая строка стала обычной, и идущая роль показывалась
    как «не идёт», а оборвись она — не помечалась бы и оборванной.
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
        elif r.get("status") == "fallback":
            continue
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

# Поле `shape` заведено решением владельца (2026-09-02): главный
# критерий — устойчивость, «приносит немного, но стабильно и не
# забирает за один день прибыль недели». Правило вылета судит теперь
# именно форму (`pool.shape_why`: медиана дня и укус), то есть заявка,
# не сказавшая, какой формы кривую она ждёт и чем ограничен её хвост,
# подаётся вслепую под критерий, по которому её будут судить.
#
# Проверяется, как и всё здесь, ФОРМА, а не убедительность: длина
# ответа. Верность ожидания проверить машиной нельзя — для этого есть
# адверсарий и календарь.
PROPOSAL_MIN = {"hypothesis": 80, "kills_it": 60, "ceiling": 80,
                "differs_from_live": 60, "shape": 80}
PROPOSAL_MIN_CITES = 3
BRIEF_PATH = "research/factory/out/brief.md"
# Пустой день — законный ответ, но он обязан быть ОБОСНОВАН: иначе
# «сегодня нечего предложить» станет способом не работать, и отличить
# его от отказа будет нечем.
PROPOSAL_MIN_WHY = 120


def check_proposal(text, root, ledger_ids=(), space=None,
                   closed_ids=()):
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
                # Закрытое ПОТОЛКОМ повторять тоже нельзя, и это
                # отдельная проверка: такая заявка испытанием не
                # становилась, в реестре её нет, и без своего журнала
                # она вернулась бы на следующий же круг.
                elif k in set(closed_ids):
                    bad.append(f"кандидат {k} уже закрыт потолком — "
                               "если изменилось что-то, из-за чего "
                               "закрытие больше не верно, скажи об "
                               "этом словами, а не подавай заново")
    elif kind == "mechanism":
        if not (d.get("needs") or "").strip():
            bad.append("механизм не назвал, какого шага конвейера ждёт")
    bad += check_needs_owner(d)
    return (not bad), bad


# --- контракт разведчика ---------------------------------------------

SCOUT_MIN = {"title": 8, "claim": 40, "mechanism": 80,
             "kills_it": 40, "novelty": 40}
SCOUT_MAX_IDEAS = 5
SCOUT_MIN_WHY = 120
SCOUT_SEEN = "scout.jsonl"


def scout_seen(base, before=None):
    """Заголовки уже принесённых идей. Журнал ведёт машина.

    `before` — момент НАЧАЛА прогона, который судим. Запись, сделанная
    ПОСЛЕ него, принадлежит этому же прогону и повтором быть не может:
    иначе роль отвергается собственными идеями. Ровно это и случилось
    на живом сервере 2026-09-02 — три идеи легли в журнал за 23 с до
    отказа «уже приносилась», и разведчик не мог отработать вовсе.

    Строка без числовой метки машиной не писана, значит свидетельством
    «идею уже приносили» не является; блокировать по ней означало бы
    держать роль запертой, пока файл не почистит человек, — тот самый
    отказ, который эта правка и закрывает. При `before=None` (осмотр
    журнала, а не суд над прогоном) возвращается всё.
    """
    seen = []
    try:
        with open(os.path.join(base, SCOUT_SEEN), encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                t = (r.get("title") or "").strip().lower()
                if not t:
                    continue
                if before is not None:
                    at = r.get("at")
                    if not isinstance(at, (int, float)) or at >= before:
                        continue
                seen.append(t)
    except OSError:
        return []
    return seen


def scout_record(text, base):
    """Дописать принесённое в журнал. Возвращает число записанных.

    Журнал ведёт машина, а не роль: список, который роль пишет сама,
    она сама и перепишет, и защита от повтора станет украшением.
    """
    try:
        d = json.loads(text or "")
        ideas = d.get("ideas") or []
    except ValueError:
        return 0
    if not isinstance(ideas, list):
        return 0
    n = 0
    os.makedirs(base, exist_ok=True)
    # Дважды записанная идея так же вредна, как незаписанная: журнал
    # и есть защита от повтора, и раздвоенная строка делает её шумом.
    was = set(scout_seen(base))
    with open(os.path.join(base, SCOUT_SEEN), "a", encoding="utf-8") as f:
        for it in ideas:
            if not isinstance(it, dict):
                continue
            t = (it.get("title") or "").strip()
            if not t or t.lower() in was:
                continue
            was.add(t.lower())
            # Пишется ИДЕЯ ЦЕЛИКОМ, а не только заголовок. Меню
            # живёт в `scout.json`, а его каждый прогон перезаписывает
            # свежим: журнал, хранящий один заголовок, объявлял бы идею
            # принесённой, когда её текста уже нет нигде, кроме истории
            # git. Тогда запись запрещает повтор и не отдаёт взамен
            # ничего — то есть идея молча теряется.
            rec = {"at": round(time.time(), 3), "title": t,
                   "sources": [c for c in (it.get("sources") or [])
                               if isinstance(c, str)][:5]}
            for k in ("claim", "mechanism", "kills_it", "novelty",
                      "needs"):
                v = (it.get(k) or "").strip()
                if v:
                    rec[k] = v
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def check_scout(text, seen=()):
    """Меню разведчика проверяемо? Возвращает (годно, список бед).

    Проверяется ФОРМА, и только она: убедительность идеи проверит
    потолок, когда предлагающий превратит её в заявку. Но идея без
    механизма и без того, чем её убить, до предлагающего доезжать не
    должна — иначе разведка приносит настроение, а не работу.
    """
    bad = []
    try:
        d = json.loads(text or "")
    except ValueError as e:
        return False, [f"меню не разбирается как JSON: {e}"]
    if not isinstance(d, dict):
        return False, ["меню не объект"]
    if "found" not in d or not isinstance(d["found"], bool):
        return False, ["нет поля found (да/нет): пустой день обязан "
                       "быть назван, а не подразумеваться"]
    if not d["found"]:
        why = (d.get("why") or "").strip()
        if len(why) < SCOUT_MIN_WHY:
            bad.append(f"пустой день не обоснован: {len(why)} символов "
                       f"при минимуме {SCOUT_MIN_WHY}")
        return (not bad), bad

    ideas = d.get("ideas")
    if not isinstance(ideas, list) or not ideas:
        return False, ["found=true, а идей нет"]
    if len(ideas) > SCOUT_MAX_IDEAS:
        bad.append(f"идей {len(ideas)} при пределе {SCOUT_MAX_IDEAS}: "
                   "меню, которое не прочитать, не меню")
    was = {str(t).strip().lower() for t in seen}
    titles = set()
    for i, it in enumerate(ideas, 1):
        if not isinstance(it, dict):
            bad.append(f"идея {i} не объект")
            continue
        for f, n in SCOUT_MIN.items():
            v = (it.get(f) or "").strip()
            if len(v) < n:
                bad.append(f"идея {i}, поле {f}: {len(v)} символов "
                           f"при минимуме {n}")
        src = [c for c in (it.get("sources") or [])
               if isinstance(c, str) and c.strip().startswith("http")]
        if not src:
            bad.append(f"идея {i} без источника ссылкой: механику без "
                       "источника нечем оспорить")
        t = (it.get("title") or "").strip().lower()
        if t and t in was:
            bad.append(f"идея {i} уже приносилась: «{it.get('title')}» "
                       "— повтор тратит день предлагающего")
        if t and t in titles:
            bad.append(f"идея {i} повторяет соседнюю в этом же меню")
        titles.add(t)
    return (not bad), bad


# --- просьбы к владельцу ----------------------------------------------

def check_needs_owner(d):
    """Форма просьб к владельцу в отчёте роли. Возвращает список бед.

    Агент не заводит аккаунтов, не платит и не кладёт ключи. Просьба,
    сказанная только прозой отчёта, теряется в тот же день; поэтому у
    неё объявлена форма, и негодная форма — беда, а не пропуск: молча
    выброшенная просьба означает, что система стоит, а снаружи это
    спокойный день.
    """
    items = d.get("needs_owner")
    if items is None:
        return []
    bad = []
    if not isinstance(items, list):
        return ["needs_owner обязан быть списком просьб"]
    import asks as AK
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            bad.append(f"просьба {i} не объект")
            continue
        w = (it.get("what") or "").strip()
        y = (it.get("why") or "").strip()
        if len(w) < AK.MIN_WHAT:
            bad.append(f"просьба {i}: что именно нужно — {len(w)} "
                       f"символов при минимуме {AK.MIN_WHAT}")
        if len(y) < AK.MIN_WHY:
            bad.append(f"просьба {i}: зачем — {len(y)} символов при "
                       f"минимуме {AK.MIN_WHY}")
    return bad


def _owner_asks(out, d, src):
    """Записать просьбы к владельцу. Молча не теряем ни одной."""
    try:
        import asks as AK
        return AK.record(out, d.get("needs_owner"), src)
    except Exception:                                     # noqa: BLE001
        return 0


def _close_mechanism(out, d):
    """Отметить механику построенной либо упершейся в владельца.

    Чью — говорит метка в задании, а не отчёт: отчёт пишет модель, и
    ключ в нём был бы её словом о самой себе.
    """
    try:
        import mech_queue as MQ
    except Exception:                                     # noqa: BLE001
        return
    mid = MQ.task_id(os.path.join(out, MQ.TASK))
    if not mid:
        return
    if d.get("needs_owner"):
        MQ.mark(out, "blocked", mid,
                "строитель уперся в то, что может дать только владелец")
    elif d.get("built"):
        MQ.mark(out, "built", mid, (d.get("module") or "").strip())


def check_role(role, root, since=None):
    """Контракт роли: выполнен ли. Возвращает (годно, список бед).

    Одно место на все роли — иначе перечень того, что роль обязана
    оставить, разошёлся бы с реестром и с промптом.

    `since` — момент начала прогона. Он нужен ровно одному правилу:
    повтор разведчика судится по тому, что принесли РАНЬШЕ, а не по
    записям этого же прогона (см. `scout_seen`).
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
    elif role == "scout":
        out = os.path.join(root, "research", "factory", "out")
        ok, why = check_scout(
            texts.get("research/factory/out/scout.json", ""),
            seen=scout_seen(out, before=since))
        if not ok:
            bad.append("scout.json: " + "; ".join(why))
        else:
            # Журнал принесённого ведёт МАШИНА и только на годном
            # меню: записав негодное, мы запретили бы роли принести
            # ту же идею в исправленном виде.
            scout_record(texts.get("research/factory/out/scout.json",
                                   ""), out)
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
        else:
            # Просьбы к владельцу и судьба механики записываются
            # МАШИНОЙ и только на годном отчёте: журнал, который роль
            # ведёт сама, она сама и перепишет.
            out = os.path.join(root, "research", "factory", "out")
            d = json.loads(texts.get(
                "research/factory/out/build.json", "") or "{}")
            _owner_asks(out, d, "строитель")
            _close_mechanism(out, d)
    elif role == "propose":
        import ledger as LG
        import space as SP
        # Реестру подаётся КАТАЛОГ, а не файл: `ledger.read` дописывает
        # имя журнала сам. Первая версия передавала сюда путь к файлу,
        # реестр читал `…/ledger.jsonl/ledger.jsonl`, всегда получал
        # пусто — и повтор уже объявленного через эту дорогу не ловился
        # ни разу. Прямая проверка правила при этом проходила: ей
        # список ключей подавали руками.
        out_dir = os.path.join(root, "research", "factory", "out")
        rows, _ = LG.read(out_dir)
        ids = list(LG.state(rows).keys())
        # Что уже закрыто потолком — из его собственного журнала.
        closed = []
        try:
            import ceiling as CL
            closed = [r.get("id") for r in CL.read_journal(out_dir)[0]
                      if r.get("verdict") == CL.CLOSED and r.get("id")]
        except Exception:                                 # noqa: BLE001
            closed = []
        ok, why = check_proposal(
            texts.get("research/factory/out/proposal.json", ""),
            root, ledger_ids=ids, space=SP, closed_ids=closed)
        if not ok:
            bad.append("proposal.json: " + "; ".join(why))
        else:
            # Механика живёт в очереди, а не в `proposal.json`: тот
            # перезаписывается следующим прогоном, и заявка, которой
            # движок ещё не умеет, теряется через сутки.
            d = json.loads(texts.get(
                "research/factory/out/proposal.json", "") or "{}")
            _owner_asks(out_dir, d, "предлагающий")
            try:
                import mech_queue as MQ
                MQ.queue(out_dir, d)
            except Exception as e:                        # noqa: BLE001
                bad.append("механика не поставлена в очередь: %s" % e)
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
    """Прогнать тесты кандидата. Возвращает (прошли, вывод).

    Байткод складывается в СВОЙ каталог на каждый прогон, и это не
    гигиена, а исправление дефекта самой машины. Питон считает `.pyc`
    свежим по паре (mtime в целых секундах, размер исходника), а
    подделки пишутся в один файл подряд: замена одной строки часто
    даёт файл ТОГО ЖЕ размера в ту же секунду — и прогон исполняет
    байткод предыдущей подделки. Врёт это в обе стороны: кусающийся
    контроль объявляется прошедшим и наоборот. Найдено ролью
    строителя на своей копии этой машины (`out/_controls_check.py`);
    здесь тот же дефект был у всех контролей фабрики.
    """
    import subprocess
    import sys
    import tempfile
    py = os.path.join(root, ".venv", "bin", "python")
    if not os.path.exists(py):
        py = sys.executable
    cache = tempfile.mkdtemp(prefix="pyc-")
    env = dict(os.environ, PYTHONPYCACHEPREFIX=cache)
    try:
        r = subprocess.run([py, tests], cwd=root, capture_output=True,
                           text=True, timeout=BUILD_TEST_TIMEOUT,
                           env=env)
    except Exception as e:                                # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    finally:
        import shutil
        shutil.rmtree(cache, ignore_errors=True)
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
    bad += check_needs_owner(d)
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
