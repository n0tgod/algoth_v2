#!/usr/bin/env bash
# Проверка перед коммитом: то, что нельзя записать в историю случайно.
#
# Правило, записанное в документе, само по себе не защищает — за
# историю проекта данные терялись пять раз, и каждый раз правило уже
# было где-то записано. Здесь оно исполняется.
#
# Ставится хуком (разово в каждом клоне):
#     git config core.hooksPath tools/githooks
#
# Можно звать и руками:  tools/safety_check.sh
#
# Осознанный обход — переменной окружения, с явным намерением:
#     ALLOW_DELETE=1 git commit …     # удаление отслеживаемых данных
# Обход не «отключает проверку», а называет, ЧТО именно разрешено.
set -u

cd "$(git rev-parse --show-toplevel)" || exit 0
fail=0
say() { printf '%s\n' "$*" >&2; }

staged() { git diff --cached --name-only --diff-filter="$1" 2>/dev/null; }

# --- 1. Удаления в защищённых путях ----------------------------------
# Артефакты прогонов, спеки и журналы ядра удаляются только намеренно.
# Машина, где их нет на диске, иначе стирает их у всех остальных.
PROTECTED='^(research/[^/]+/out/|docs/|bot/out/|CLAUDE\.md|IDEAS\.md)'
dels=$(staged D | grep -E "$PROTECTED" || true)
if [ -n "$dels" ] && [ "${ALLOW_DELETE:-0}" != "1" ]; then
    say "ОТКАЗ: коммит удаляет данные в защищённых путях:"
    say "$dels" | sed 's/^/    /'
    say ""
    say "Если удаление намеренное — повторите с ALLOW_DELETE=1."
    say "Если нет — верните файлы: git restore --staged <путь>"
    fail=1
fi

# --- 2. Маркеры конфликта --------------------------------------------
# Склейка git с маркерами однажды уехала в git как отчёт прогона.
for f in $(staged ACM); do
    [ -f "$f" ] || continue
    case "$f" in *.png|*.jpg|*.gz|*.parquet|*.zip) continue;; esac
    if grep -qE '^(<<<<<<< |=======$|>>>>>>> )' "$f" 2>/dev/null; then
        say "ОТКАЗ: маркеры конфликта в $f"
        fail=1
    fi
done

# --- 3. Ключи и секреты ----------------------------------------------
# Ключ биржи живёт ТОЛЬКО в ~/.bybit/live.env на сервере (режим 600).
for f in $(staged ACM); do
    case "$f" in
        *.env|*/token.txt|*.pem|*.key|*id_rsa*)
            say "ОТКАЗ: секрет в коммите: $f"
            fail=1
            ;;
    esac
done
# Содержимое: ключ Bybit — 18+ знаков латиницы и цифр рядом со словом
# key/secret. Ищем присвоение, а не любое длинное слово.
for f in $(staged ACM); do
    [ -f "$f" ] || continue
    case "$f" in *.md) continue;; esac       # в документах — примеры
    if grep -qiE '(api[_-]?key|api[_-]?secret|secret)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9]{18,}' "$f" 2>/dev/null; then
        say "ОТКАЗ: похоже на ключ в $f (присвоение секрета)"
        fail=1
    fi
done

# --- 4. Крупные файлы -------------------------------------------------
# Ряды в git не идут: они восстанавливаются с площадки, а репозиторий
# с ними становится неклонируемым.
for f in $(staged ACM); do
    [ -f "$f" ] || continue
    sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
    if [ "$sz" -gt 5242880 ]; then
        say "ОТКАЗ: файл больше 5 МБ: $f ($((sz / 1048576)) МБ)"
        say "  Ряды и записи в git не идут — правила .gitignore этапа."
        fail=1
    fi
done

if [ "$fail" = 0 ]; then
    exit 0
fi
say ""
say "Проверка сохранности данных: docs/DATA-SAFETY.md"
exit 1
