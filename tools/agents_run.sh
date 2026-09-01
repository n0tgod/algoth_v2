#!/usr/bin/env bash
# Запускалка ролей автономной системы.
#
# Роль здесь — НЕ живая сессия, а рецепт запуска: промпт файлом, права,
# что прочитать, что оставить на диске. Сессия рождается на вызов и
# умирает; всё, что следующий вызов будет знать, лежит в репозитории.
# Эта команда и есть то, что заменяет владельца на кроне.
#
#     tools/agents_run.sh brief --dry     # собрать и показать, не звать
#     tools/agents_run.sh brief           # позвать модель
#
# Три правила, каждое из наших же уроков:
#
#   ОДИН ПИСАТЕЛЬ ЗА РАЗ. Роли пишут в один репозиторий, и очередь
#   заданий уже отказывала «дерево разошлось» при конкурентной
#   публикации. Замок — flock, и второй вызов не ждёт, а честно уходит.
#
#   ТИШИНА ЗАПРЕЩЕНА. Каждое пробуждение оставляет строку в журнале
#   прогонов, включая отказ. Остановившаяся запускалка иначе выглядит
#   ровно как спокойный день — самый дешёвый отказ из всех.
#
#   ОТКАЗ НАЗЫВАЕТСЯ. Нет промпта, нет ключа, нет самого `claude` —
#   всё это разные беды, и лечатся они по-разному. Общего «не
#   запустилось» не бывает.

set -uo pipefail

# Прогон роли идёт минуты, а сторож подтягивает ветку каждые пять — то
# есть ЭТОТ файл могут заменить прямо во время исполнения. Bash читает
# скрипт по мере надобности, по смещению в байтах, поэтому подмена на
# ходу уводит исполнение в середину чужой строки: отказ, который потом
# не объяснить ничем.
#
# Поэтому первым делом исполняем СВОЮ КОПИЮ. Копия живёт в /tmp и
# удаляется сама; на поведение это не влияет ничем, кроме того, что
# обновление репозитория больше не трогает идущий прогон.
if [ -z "${AGENTS_SELF_COPY:-}" ]; then
    self="$(mktemp -t agents_run.XXXXXX.sh)" || exit 2
    cat "$0" > "$self" || exit 2
    chmod +x "$self"
    AGENTS_SELF_COPY="$self" exec bash "$self" "$@"
fi
trap 'rm -f "${AGENTS_SELF_COPY:-}"' EXIT

cd "$(git rev-parse --show-toplevel)" || exit 2
ROOT="$(pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
# Каталог артефактов можно увести на время проверки: тест обязан
# гонять НАСТОЯЩИЙ скрипт, а не его пересказ, и при этом не
# писать в журнал прогонов сервера.
OUT="${AGENTS_OUT:-$ROOT/research/factory/out}"
LOCK="$OUT/agents.lock"
mkdir -p "$OUT"

ROLE="${1:-}"
DRY=0
shift || true
for a in "$@"; do
    case "$a" in
        --dry) DRY=1 ;;
        *) echo "неизвестный аргумент: $a"; exit 2 ;;
    esac
done

# Сухой прогон пишет в СВОЙ журнал и в git не идёт. По содержимому он
# неотличим от боевого — оба выглядят как строка прогона роли, — а
# смешавшись, они дали бы «роль работала» там, где модель не звали ни
# разу. Тот же приём, которым в проекте разведены смоук и настоящий
# прогон этапа.
RUNS="$OUT/agents-runs.jsonl"
[ "$DRY" = "1" ] && RUNS="$OUT/agents-runs-dry.jsonl"

STARTED="$(date +%s)"

# Строка прогона пишется ЯДРОМ журнала, а не echo в файл: формат один
# на запускалку, страницу и проверки, и второй писатель однажды
# разошёлся бы с первым.
log_run() {                              # статус, пояснение [, pid]
    "$PY" - "$RUNS" "$ROLE" "$1" "$STARTED" "${2:-}" "$DRY" "${3:-}" \
        <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "research", "factory"))
import runlog as R
path, role, status, started, note, dry, pid = sys.argv[1:8]
R.append(path, role, status, float(started), note=note or None,
         dry=(dry == "1"), pid=int(pid) if pid else None)
PYEOF
}

die() {                                       # статус, пояснение
    echo "ОТКАЗ: $2"
    log_run "$1" "$2"
    exit 1
}

[ -n "$ROLE" ] && [[ "$ROLE" =~ ^[a-z_]+$ ]] || {
    echo "нужна роль: tools/agents_run.sh <роль> [--dry]"; exit 2; }

PROMPT="$ROOT/research/factory/agents/$ROLE.md"
[ -f "$PROMPT" ] || die "no-prompt" "промпта роли нет: research/factory/agents/$ROLE.md"

# Выключатель уважается ЗДЕСЬ, а не только в расписании: остановить
# систему должно быть проще, чем запустить, и ручное задание не
# должно обходить остановку. Строка в журнал пишется — иначе
# остановленная система выглядит спокойным днём.
STOPFILE="$OUT/STOP"
[ -f "$STOPFILE" ] && die "stopped" "выключатель: $STOPFILE"

# --- один писатель за раз -------------------------------------------
exec 9>"$LOCK"
if ! flock -n 9; then
    die "busy" "другая роль уже работает (замок $LOCK)"
fi

# Строка НАЧАЛА с номером процесса. Без неё «работает сейчас»
# неотличимо от «не запускалась»: роль оставляла бы след только по
# завершении, а спрашивают состояние именно во время работы.
# Мёртвый номер читается как «прогон оборван», а не как идущий.
log_run "start" "" "$$"

if [ "$DRY" = "1" ]; then
    echo "=== сухой прогон роли $ROLE: модель НЕ вызывается ==="
    echo "промпт: $PROMPT ($(wc -c < "$PROMPT") байт)"
    echo
    cat "$PROMPT"
    log_run "ok" "сухой прогон: промпт собран, модель не звалась"
    exit 0
fi

# --- боевой прогон --------------------------------------------------
command -v claude >/dev/null 2>&1 || die "no-cli" \
    "команды claude нет в PATH — роль позвать нечем"

# Путей авторизации ДВА, и требовать только первый было ошибкой: CLI
# умеет работать и от подписки (claude auth login / setup-token), и
# тогда никакого ключа в окружении нет вовсе, а роль звать можно.
#
# Ключ, если он есть, живёт файлом с правами 600 рядом с ключами биржи
# и НИКОГДА не печатается.
KEYFILE="${ANTHROPIC_KEY_FILE:-$HOME/.anthropic/key}"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$KEYFILE" ]; then
    ANTHROPIC_API_KEY="$(tr -d '[:space:]' < "$KEYFILE")"
    export ANTHROPIC_API_KEY
fi
AUTH=""
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    AUTH="ключ API"
elif claude auth status 2>/dev/null | grep -q '"loggedIn": *true'; then
    # Спрашиваем САМ CLI, а не гадаем по файлам: где он держит
    # состояние входа, знает только он, и наш пересказ однажды
    # разошёлся бы с ним.
    AUTH="вход CLI (подписка)"
fi
[ -n "$AUTH" ] || die "no-auth" \
    "авторизации нет ни одним путём: либо claude auth login (подписка), либо ключ в $KEYFILE (права 600)"
echo "авторизация: $AUTH"

# Права роли — из РЕЕСТРА, а не из этой команды: реестр и так
# описывает, что роль читает и куда пишет, и второй перечень разошёлся
# бы с ним. Пусто — зовём без ограничения списком (модель тогда
# попросит разрешение и в неинтерактивном прогоне получит отказ; это
# видно в журнале, а не молча).
ALLOW="$("$PY" - "$ROLE" <<'PYTOOLS'
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "research", "factory"))
import agents as AG
print(" ".join(AG.tools(sys.argv[1])))
PYTOOLS
)"

# Модель и усилие берутся из реестра и передаются ЯВНО. Прежде не
# передавалось ни того, ни другого — роли шли на умолчании CLI, то
# есть на внешнем состоянии, которое может смениться под нами, и в
# журнале прогонов не осталось бы ни следа.
MODEL="$("$PY" -c "import sys,os;sys.path.insert(0,os.path.join(os.getcwd(),'research','factory'));import agents as AG;print(AG.model_of(sys.argv[1]))" "$ROLE")"
EFFORT="$("$PY" -c "import sys,os;sys.path.insert(0,os.path.join(os.getcwd(),'research','factory'));import agents as AG;print(AG.effort_of(sys.argv[1]))" "$ROLE")"
FALLBACK="$("$PY" -c "import sys,os;sys.path.insert(0,os.path.join(os.getcwd(),'research','factory'));import agents as AG;print(AG.fallback_of(sys.argv[1]))" "$ROLE")"
echo "модель: $MODEL · усилие: $EFFORT${FALLBACK:+ · запасная: $FALLBACK}"

TMP="$(mktemp)"
# Ловушка ОДНА на выход: вторая заменила бы первую, и копия скрипта
# осталась бы в /tmp после каждого прогона.
trap 'rm -f "$TMP" "${AGENTS_SELF_COPY:-}"' EXIT
# Роль работает В КАТАЛОГЕ репозитория и читает файлы сама: список
# чтения объявлен её промптом, а не собран здесь. Второй список,
# решающий то же самое, однажды разошёлся бы с промптом.
# Промпт идёт СТДИНОМ, а не позиционным аргументом. `--allowedTools`
# берёт список переменной длины и, стоя перед промптом, проглатывает
# его целиком: слова промпта становятся «правилами доступа», а модель
# остаётся без задания. Первый прогон предлагающего умер ровно так.
call_model() {                                # модель → код возврата
    if [ -n "$ALLOW" ]; then
        # shellcheck disable=SC2086
        claude -p --model "$1" --effort "$EFFORT" \
            --allowedTools $ALLOW < "$PROMPT" >"$TMP" 2>&1
    else
        claude -p --model "$1" --effort "$EFFORT" < "$PROMPT" >"$TMP" 2>&1
    fi
}

# Откат на запасную модель — ТОЛЬКО на отказ по лимиту и ровно один
# раз. Молчаливый перебор моделей превратил бы «роль отработала» в
# «отработала неизвестно чем»; поэтому откат громкий, а `USED`
# штампуется в строку прогона.
#
# Нераспознанный отказ отката НЕ вызывает: это безопасное направление
# ошибки — прогон падает громко, и его причина лежит в логе, а не
# тратит вторую модель на беду, которая повторится.
limit_hit() {
    grep -Eiq 'usage limit|rate.?limit|limit reached|out of (usage|credit)|quota|лимит|429|overloaded|capacity' "$TMP"
}

USED="$MODEL"
call_model "$MODEL"
RC=$?
if [ "$RC" != "0" ] && [ -n "$FALLBACK" ] && limit_hit; then
    echo "ЛИМИТ модели $MODEL — перехожу на запасную $FALLBACK"
    log_run "fallback" "лимит $MODEL, перехожу на $FALLBACK" "$$"
    USED="$FALLBACK"
    call_model "$FALLBACK"
    RC=$?
fi
BYTES="$(wc -c < "$TMP")"
tail -c 4000 "$TMP"

if [ "$RC" != "0" ]; then
    log_run "fail" "модель $USED, код $RC: $(tail -c 400 "$TMP" | tr '\n' ' ')"
    exit 1
fi

# --- проверка того, что роль произвела ------------------------------
# Модель производит, машина проверяет контракт. Что именно проверяется
# по каждой роли — в `runlog.check_role`: одно место, иначе перечень
# разошёлся бы с реестром и с промптом.
"$PY" - "$ROLE" "$ROOT" <<'PYCHECK'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[2], "research", "factory"))
import runlog as R
ok, bad = R.check_role(sys.argv[1], sys.argv[2])
print("КОНТРАКТ: " + ("выполнен" if ok else "; ".join(bad)))
sys.exit(0 if ok else 1)
PYCHECK
CRC=$?
if [ "$CRC" != "0" ]; then
    log_run "contract" "роль отработала, но контракт не выполнен"
    exit 1
fi

log_run "ok" "модель $USED, усилие $EFFORT" \
    && echo "прогон роли $ROLE завершён"
# Публикацию можно выключить на время проверки: тест обязан гонять
# НАСТОЯЩИЙ скрипт, но не коммитить и не пушить репозиторий.
if [ -z "${AGENTS_NO_PUBLISH:-}" ]; then
    # У строителя продукт — КОД, а `publish.sh` публикует отчёты
    # (`research/*/out`, `docs`, `jobs`). Первая же постройка осталась
    # на сервере: прогон был, контракт выполнен, а в ветке пусто.
    # Публикуется ровно то, что роль объявила своим отчётом, — общий
    # белый список публикации не расширяется.
    if [ "$ROLE" = "build" ]; then
        "$PY" "$ROOT/research/factory/publish_build.py" || true
    else
        "$ROOT/tools/publish.sh" "агенты: прогон роли $ROLE" || true
    fi
fi
