#!/usr/bin/env bash
# Сторож сбора: поднимает умершее и перезапускает зависшее.
#
# Ставится в cron и на перезагрузку сервера:
#
#     crontab -e
#     */5 * * * * /root/algoth_v2/tools/watchdog_book.sh >> /root/algoth_v2/research/b1_book/out/watchdog.log 2>&1
#     @reboot sleep 30 && /root/algoth_v2/tools/watchdog_book.sh >> /root/algoth_v2/research/b1_book/out/watchdog.log 2>&1
#
# Три случая, и каждый проверяется отдельно, потому что выглядят они
# по-разному:
#
# 1. Процесс сборщика УМЕР (OOM, kill, перезагрузка сервера) —
#    ловится pgrep.
# 2. Процесс ЖИВ, но ЗАВИС или потерял все соединения — pgrep его не
#    отличает от здорового. Ловится свежестью status.json: сборщик
#    пишет его каждые 5 секунд, и файл старше трёх минут означает, что
#    внутри всё стоит, как бы бодро процесс ни выглядел снаружи.
#    Урок проекта: тишина неотличима от поломки, поэтому мерим данные,
#    а не признаки жизни.
# 3. Цикл обучения умер — он спит сутками, поэтому для него довод
#    только pgrep: свежесть его артефактов сутками старая ПО ДЕЛУ.
#
# Обрывы, которые сторожа НЕ требуют (уже самовосстанавливаются):
# падение API биржи — шарды переподключаются с отступом 1→30 с вечно;
# отказ REST-опроса — счётчик и повтор через 5 минут; битый час на
# диске — дожимается и спасается при следующем старте.

set -u
cd "$(dirname "$0")/.."

STATUS=research/b1_book/out/status.json
STALE_SEC=180
now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# --- сборщик ---------------------------------------------------------
need_restart=""
if ! pgrep -f "b1_book/collect.py" >/dev/null; then
    need_restart="процесс сборщика не найден"
elif [ -f "$STATUS" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$STATUS") ))
    if [ "$age" -gt "$STALE_SEC" ]; then
        need_restart="status.json не обновлялся ${age} с — сборщик завис"
    fi
else
    need_restart="status.json отсутствует при живом процессе"
fi

if [ -n "$need_restart" ]; then
    echo "[$(now)] ПЕРЕЗАПУСК СБОРЩИКА: $need_restart"
    tools/restart_book.sh
else
    : # здоров — молчим, лог не засоряем
fi

# --- цикл обучения ---------------------------------------------------
if ! pgrep -f "s8_loop/train.py" >/dev/null; then
    echo "[$(now)] цикл обучения не найден — поднимаю"
    setsid nohup .venv/bin/python research/s8_loop/train.py \
        >> research/s8_loop/out/train.log 2>&1 &
fi
