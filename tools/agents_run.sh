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

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
# Роль работает В КАТАЛОГЕ репозитория и читает файлы сама: список
# чтения объявлен её промптом, а не собран здесь. Второй список,
# решающий то же самое, однажды разошёлся бы с промптом.
claude -p "$(cat "$PROMPT")" >"$TMP" 2>&1
RC=$?
BYTES="$(wc -c < "$TMP")"
tail -c 4000 "$TMP"

if [ "$RC" != "0" ]; then
    log_run "fail" "claude вышел с кодом $RC: $(tail -c 500 "$TMP" | tr '\n' ' ')"
    exit 1
fi

# --- проверка того, что роль произвела ------------------------------
# Модель производит, машина проверяет контракт. Просить модель
# проверить себя бесполезно; посчитать размер и убедиться, что
# названные файлы существуют, машина умеет.
"$PY" - "$ROLE" "$ROOT" <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[2], "research", "factory"))
import runlog as R
role, root = sys.argv[1], sys.argv[2]
if role != "brief":
    sys.exit(0)
files = [("research/factory/out/brief.md", R.BRIEF_BUDGET_CHARS, R.BRIEF_MIN_CITES),
         ("research/factory/out/summary.md", 6000, 1)]
bad = []
for rel, budget, mn in files:
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        bad.append(f"{rel}: не создан")
        continue
    with open(p, encoding="utf-8") as f:
        ok, why, _ = R.check_brief(f.read(), root, budget, mn)
    if not ok:
        bad.append(rel + ": " + "; ".join(why))
print("КОНТРАКТ: " + ("; ".join(bad) if bad else "выполнен"))
sys.exit(1 if bad else 0)
PYEOF
CRC=$?
if [ "$CRC" != "0" ]; then
    log_run "contract" "роль отработала, но контракт не выполнен"
    exit 1
fi

log_run "ok" "" && echo "прогон роли $ROLE завершён"
"$ROOT/tools/publish.sh" "агенты: прогон роли $ROLE" || true
