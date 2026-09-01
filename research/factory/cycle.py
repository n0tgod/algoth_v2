#!/usr/bin/env python3
"""
Суточный круг фабрики: один шаг за вызов.

Сторож ходит раз в пять минут, а шаг круга идёт минуты (роль) или часы
(судья). Поэтому круг НЕ исполняется целиком в одном такте: каждый
вызов делает ровно один недостающий шаг и уходит. Это же делает его
безопасным к обрыву — состояние читается с диска, а не держится в
голове процесса.

Порядок объявлен и не меняется по ходу: бриф даёт состояние,
предлагающий читает его и подаёт заявку, потолок решает, стоит ли её
объявлять, судья прогоняет объявленное. Переставить их значит
предлагать по вчерашнему состоянию или объявлять непроверенное.

ПРЕДОХРАНИТЕЛИ, без которых расписание включать нельзя:

  STOP  — файл `research/factory/out/STOP`. Пока он есть, не делается
          ничего. Остановить систему должно быть проще, чем запустить.
  предел суток — больше объявленного числа прогонов ролей за сутки не
          делается. Сбой не должен превращаться в сотню вызовов.
  час начала — круг не начинается раньше объявленного часа UTC: до
          него сутки ещё не сложились.

    .venv/bin/python research/factory/cycle.py --dry
    .venv/bin/python research/factory/cycle.py
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
import runlog as RL                                       # noqa: E402

STOP = os.path.join(OUT, "STOP")
# Предел прогонов РОЛЕЙ за сутки. Круг делает четыре шага, из них две
# роли; запас оставлен на повтор после отказа, но не на бесконечность.
MAX_ROLE_RUNS_PER_DAY = 8
# Предел попыток МЕХАНИЧЕСКОГО шага за сутки. Модель он не зовёт, но
# судья читает бары часами: падающий шаг без предела перезапускался бы
# каждые пять минут круглые сутки и съел бы машину, на которой идёт
# запись стакана — а её неоткуда докачать. Три попытки: одна на сбой,
# две на то, чтобы сбой оказался не разовым.
MAX_MECH_RUNS_PER_DAY = 3
# Час UTC, раньше которого круг не начинается.
START_HOUR = 2

# Круг в порядке исполнения: ключ, вид, чем запускается, чем доказано.
#
# ПОРЯДОК ВЫВЕДЕН ИЗ ДАННЫХ, а не из красоты конвейера. Потолок судит
# заявку ЧИСЛАМИ, а числа рождает суточный прогон: он реплеит заявку
# отдельной рукой, потому что ноги и исходы у него уже загружены.
# Пока потолок стоял ПЕРЕД судьёй, он читал вчерашний артефакт, в
# котором сегодняшней заявки нет по построению, и честно отвечал
# «заявки в прогоне нет» — круг ходил и не объявлял ничего.
#
# Суточный прогон идёт с `--no-declare`: объявляет ОДИН шаг, и только
# после вердикта потолка. Второй канал объявления (ручной список
# `proposals.jsonl`) остаётся для владельца и в круг не входит — иначе
# заявка попадала бы в реестр мимо ворот.
# У механического шага мало «артефакт сегодняшний»: потолок судит
# ЧИСЛА судьи, а объявление — вердикт потолка, и артефакт, сделанный
# раньше своего входа, описывает вчерашнее. Сегодня это и остановило
# круг: потолок отработал в 18:40 по вчерашним числам, судья принёс
# новые в 21:10, и шаг считался сделанным. Поэтому у шага объявляется
# ВХОД, и сделанным он считается, только если его артефакт новее.
CIRCLE = [
    # Разведчик идёт ПЕРВЫМ: его меню попадает к предлагающему
    # разделом брифа, а бриф собирается следующим шагом. Пойди он
    # после брифа — принесённое сегодня дошло бы до предлагающего
    # только завтра, и разведка отставала бы на сутки навсегда.
    ("scout", "role", None, None),
    ("brief", "role", None, None),
    ("propose", "role", None, None),
    ("judge", "mech", ["research/factory/run_day.py", "--tag", "1m",
                       "--no-declare"], "FACTORY-day-1m.md"),
    ("ceiling", "mech", ["research/factory/ceiling.py"],
     "ceiling.json"),
    ("declare", "mech", ["research/factory/declare.py"],
     "declare.json"),
]

# Шаг → артефакт, который он читает. Пусто — входа нет (шаг читает
# журналы и хранилище, а не продукт соседа).
AFTER = {
    "ceiling": "factory-day-1m.json",
    "declare": "ceiling.json",
}


def day_of(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def done_today(key, kind, proof, rows, now):
    """Шаг сделан сегодня? Роль судится журналом, механика — артефактом.

    У роли доказательство — успешный НЕсухой прогон: файл она могла
    оставить и вчера. У механического шага доказательство — свежесть
    его артефакта.
    """
    today = day_of(now)
    if kind == "role":
        return any(r.get("role") == key and r.get("status") == "ok"
                   and not r.get("dry")
                   and day_of(r.get("at") or 0) == today for r in rows)
    p = os.path.join(OUT, proof)
    if not os.path.exists(p):
        return False
    if day_of(os.path.getmtime(p)) != today:
        return False
    src = AFTER.get(key)
    if src:
        sp = os.path.join(OUT, src)
        # Входа нет вовсе — шагу нечего читать, и «сделан» он не
        # станет от этого: пусть идёт и скажет об отсутствии сам.
        if not os.path.exists(sp):
            return True
        if os.path.getmtime(sp) > os.path.getmtime(p):
            return False
    return True


def launch(key, kind, argv, log=print):
    """Запустить шаг ОТЦЕПЛЕННО и вернуть номер процесса.

    Отцепленно, потому что сторож не вправе ждать: судья считает
    часами, и такт сторожа, повисший на нём, перестал бы делать всё
    остальное.
    """
    started = time.time()
    if kind == "role":
        cmd = [os.path.join(ROOT, "tools", "agents_run.sh"), key]
    else:
        py = os.path.join(ROOT, ".venv", "bin", "python")
        py = py if os.path.exists(py) else sys.executable
        # Механический шаг идёт ПОД ОБЁРТКОЙ, и это не украшение:
        # обёртка живёт ровно столько же, сколько шаг, и пишет строку
        # конца с кодом возврата. Без неё законно кончившийся шаг
        # оставался в журнале начатым навсегда.
        cmd = [py, os.path.join(HERE, "mech_run.py"), key,
               "%.3f" % started, "--", py] + argv
    log(f"запускаю шаг {key}: {' '.join(cmd)}")
    lf = open(os.path.join(OUT, f"cycle-{key}.log"), "a",
              encoding="utf-8")
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=lf,
                         start_new_session=True,
                         env=dict(os.environ, AGENTS_OUT=OUT))
    # Роль пишет своё начало сама (`agents_run.sh`), и вторая строка
    # была бы вторым прогоном в журнале. У механического шага начало
    # пишем здесь — номер процесса известен только тут, — а конец
    # напишет обёртка.
    if kind != "role":
        RL.append(os.path.join(OUT, RL.RUNS), key, "start", started,
                  pid=p.pid)
    return p.pid


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true",
                    help="сказать, что сделал бы, и не делать")
    ap.add_argument("--force", action="store_true",
                    help="не ждать часа начала (предохранители в силе)")
    a = ap.parse_args(argv)
    now = time.time()

    if os.path.exists(STOP):
        print(f"СТОП: {STOP} — не делаю ничего")
        return 0

    rows, broken = RL.read(os.path.join(OUT, RL.RUNS))
    st = RL.state_of(rows)
    running = [k for k, v in st.items() if v.get("running")]
    circle_keys = {k for k, _kind, _argv, _proof in CIRCLE}
    # Ждём ТОЛЬКО шаги самого круга. Прежде круг стоял, пока идёт
    # любой прогон роли, а роли зовут и руками — заход адверсария или
    # строителя длится час, и суточный круг молча стоял всё это время.
    # Со стороны это выглядело спокойным днём, то есть было тем самым
    # отказом, неотличимым от тишины.
    busy = [k for k in running if k in circle_keys]
    if busy:
        print(f"идёт шаг круга: {', '.join(busy)} — жду")
        return 0
    # Роль при этом не запускается, пока идёт ЛЮБАЯ роль: писатель в
    # репозиторий один за раз, и замок запускалки всё равно откажет —
    # лучше не будить её вовсе, чем получать отказ строкой в журнале.
    import agents as AG0
    role_busy = [k for k in running
                 if k in {x["key"] for x in AG0.roles()}]

    hour = int(time.strftime("%H", time.gmtime(now)))
    if hour < START_HOUR and not a.force:
        print(f"час {hour} UTC, круг начинается с {START_HOUR}")
        return 0

    today = day_of(now)
    # Считаются прогоны РОЛЕЙ: механические шаги модель не зовут и
    # денег не стоят, а предел заведён против бесконечного вызова
    # модели, а не против работы вообще.
    import agents as AG
    role_keys = {x["key"] for x in AG.roles()}
    used = sum(1 for r in rows
               if r.get("status") == "start" and not r.get("dry")
               and r.get("role") in role_keys
               and day_of(r.get("at") or 0) == today)
    for key, kind, argvv, proof in CIRCLE:
        if done_today(key, kind, proof, rows, now):
            continue
        if kind == "role" and role_busy:
            print(f"идёт роль: {', '.join(role_busy)} — шаг {key} "
                  "не запускаю, писатель один за раз")
            return 0
        if kind == "role" and used >= MAX_ROLE_RUNS_PER_DAY:
            print(f"предел суток: прогонов ролей {used} при "
                  f"{MAX_ROLE_RUNS_PER_DAY} — шаг {key} не запускаю")
            return 0
        if kind != "role":
            tries = sum(1 for r in rows
                        if r.get("status") == "start" and not r.get("dry")
                        and r.get("role") == key
                        and day_of(r.get("at") or 0) == today)
            if tries >= MAX_MECH_RUNS_PER_DAY:
                # Молчать нельзя: круг остановится, и без этой строки
                # остановка будет неотличима от пройденного круга.
                print(f"предел суток: шаг {key} запускался {tries} раз "
                      f"при {MAX_MECH_RUNS_PER_DAY} — не запускаю")
                return 0
        if a.dry:
            print(f"сделал бы шаг: {key} ({kind})")
            return 0
        launch(key, kind, argvv)
        return 0
    print(f"круг за {today} пройден целиком")
    return 0


if __name__ == "__main__":
    sys.exit(main())
