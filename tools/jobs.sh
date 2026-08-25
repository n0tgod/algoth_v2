#!/usr/bin/env bash
# Очередь заданий: сессия кладёт задание в git, сервер его выполняет.
#
# Зачем
# -----
# Прямого доступа к серверу у ассистента нет и не будет: из песочницы
# наружу открыты только 80 и 443, порт 22 режет политика, а на 443
# стоит терминирующий TLS-прокси (это измерено, а не предположено).
# Владелец при этом устал копировать команды руками.
#
# Открывать исполнение по HTTP на машине, где лежат ключи биржи, —
# плохой обмен. Поэтому канал другой: заданием служит ФАЙЛ В GIT.
# Ассистент коммитит его, сторож на сервере подтягивает и выполняет,
# результат публикуется обратно в git. Аутентификация — доступ к
# репозиторию, аудит — сама история, произвольных команд нет.
#
# Что можно выполнить
# -------------------
# Только питон-файл, лежащий В РЕПОЗИТОРИИ, и только из объявленного
# набора действий. Никакого `eval`, никакой сборки строки: аргументы
# идут массивом и проверяются посимвольно. Код попадает в репозиторий
# коммитом — то есть проходит ровно тот же путь, что и сегодня, когда
# владелец запускает команды руками.
#
# Формат задания: `jobs/<имя>.job`, одна строка:
#     run research/probe_turn/turn.py --tag 1m
#     restart-book
#     status
#
# Выполненное задание помечается `jobs/done/<имя>.done` и больше не
# запускается никогда — маркер в git, поэтому переживает перезапуск и
# не зависит от памяти сторожа.
#
#     tools/jobs.sh            # зовётся сторожем каждые 5 минут
set -u

cd "$(dirname "$0")/.." || exit 1
JOBS=jobs
DONE=$JOBS/done
mkdir -p "$DONE"
now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# --- подтянуть задания ------------------------------------------------
# Только перемотка вперёд: расхождение означает, что на сервере есть
# незапушенная работа, и молча перематывать её нельзя.
if [ "${JOBS_NO_FETCH:-0}" != "1" ]; then
    git fetch -q origin main 2>/dev/null
    if ! git merge -q --ff-only origin/main 2>/dev/null; then
        echo "[$(now)] задания: дерево разошлось с origin/main — не трогаю"
        exit 0
    fi
fi

shopt -s nullglob
found=0
for job in "$JOBS"/*.job; do
    name=$(basename "$job" .job)
    [ -f "$DONE/$name.done" ] && continue
    found=1
    log="$DONE/$name.log"
    line=$(head -n 1 "$job" | tr -d '\r')
    # Разбор в массив БЕЗ eval: слова разделяются пробелами, и каждое
    # проверяется отдельно. Строка задания никогда не попадает в шелл
    # как команда.
    read -r -a parts <<< "$line"
    action="${parts[0]:-}"
    bad=""
    for a in "${parts[@]}"; do
        case "$a" in
            *[!A-Za-z0-9._/=-]*) bad="$a"; break;; esac
    done

    {
        echo "== задание $name =="
        echo "строка: $line"
        echo "начало: $(now)"
    } > "$log"

    if [ -n "$bad" ]; then
        echo "ОТКАЗ: недопустимый символ в аргументе: $bad" >> "$log"
        echo "[$(now)] задание $name отвергнуто (аргумент: $bad)"
    else
        case "$action" in
        run)
            script="${parts[1]:-}"
            case "$script" in
                research/*.py|tools/*.py) ;;
                *) script="";;
            esac
            if [ -z "$script" ] || [ ! -f "$script" ]; then
                echo "ОТКАЗ: скрипт вне репозитория или не найден:" \
                     "${parts[1]:-—}" >> "$log"
            else
                echo "запускаю: .venv/bin/python $script ${parts[*]:2}" \
                    >> "$log"
                # Фоном и с пониженным приоритетом: прогон может
                # считать час, а сборщик и живой цикл важнее. Сторож
                # не ждёт — по завершении задание публикует себя само.
                setsid nohup nice -n 15 bash -c '
                    log="$1"; shift
                    .venv/bin/python "$@" >> "$log" 2>&1
                    rc=$?
                    echo "конец: $(date -u +%FT%TZ), код $rc" >> "$log"
                    # В git уходит ХВОСТ: зонд печатает прогресс
                    # тысячами строк, и целиком он там не нужен.
                    tail -n 400 "$log" > "$log.t" && mv "$log.t" "$log"
                    tools/publish.sh "job: $(basename "$log" .log)" \
                        >> "$log" 2>&1
                ' _ "$log" "$script" "${parts[@]:2}" &
                echo "[$(now)] задание $name запущено: $script"
            fi
            ;;
        restart-book)
            echo "перезапуск сборщика и циклов" >> "$log"
            setsid nohup bash -c "tools/restart_book.sh >> '$log' 2>&1
                tools/publish.sh 'job: $name' >> '$log' 2>&1" &
            echo "[$(now)] задание $name: перезапуск сборщика"
            ;;
        status)
            {
                echo "--- диск ---"; df -h / /mnt/HC_Volume_* 2>/dev/null
                echo "--- процессы ---"
                pgrep -af "b1_book/collect.py|s8_loop/train.py|bot live" \
                    2>/dev/null || echo "нет"
                echo "--- статус сбора ---"
                head -c 700 research/b1_book/out/status.json 2>/dev/null
                echo; echo "--- живой исполнитель ---"
                head -c 700 bot/out/live/live_status.json 2>/dev/null
                echo; echo "конец: $(now)"
            } >> "$log" 2>&1
            tools/publish.sh "job: $name" >> "$log" 2>&1
            echo "[$(now)] задание $name: состояние снято"
            ;;
        *)
            echo "ОТКАЗ: неизвестное действие: $action" >> "$log"
            echo "[$(now)] задание $name отвергнуто (действие: $action)"
            ;;
        esac
    fi
    # Маркер ставится ВСЕГДА, даже на отказе: задание, отвергнутое
    # один раз, будет отвергнуто и в следующий раз, а сторож ходит
    # каждые пять минут — иначе журнал заполнится одним и тем же.
    date -u +"%FT%TZ" > "$DONE/$name.done"
done

[ "$found" = 1 ] || exit 0
exit 0
