#!/usr/bin/env bash
# Проверка проверки: сведение конфликта на генерируемой карте кода.
#
# Кусается в обе стороны. Карта обязана сводиться САМА — иначе
# публикация с сервера останавливается на ней, коммит остаётся лежать
# локально, и очередь заданий замирает целиком (так канал вставал
# трижды за сутки). Смысловой конфликт (код, спека, журнал) сводиться
# НЕ должен — его разбирают руками, и молчаливое «разрешение» такого
# конфликта потеряло бы чью-то работу.
#
# Гоняется в НАСТОЯЩЕМ временном репозитории, не в рабочем.
set -u
TOOL="$(cd "$(dirname "$0")" && pwd)/resolve_maps.sh"
ok=0
fail=0
check() {                       # имя, ожидание, факт
    if [ "$2" = "$3" ]; then
        printf '  ok   %s\n' "$1"; ok=$((ok + 1))
    else
        printf '  ПАДЕНИЕ %s: ждали «%s», получили «%s»\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}

tmp=$(mktemp -d)
cd "$tmp" || exit 1
git init -q .
git config user.email t@t
git config user.name t
git config core.hooksPath /dev/null
mkdir -p docs tools
printf 'карта А\n' > docs/MAP.md
printf 'код А\n' > code.py
git add docs/MAP.md code.py
git commit -qm "начало"

# Ветка сервера: своя пересборка карты и своя работа.
git checkout -q -b server
printf 'карта сервера\n' > docs/MAP.md
printf 'код сервера\n' >> code.py
git commit -qam "прогон на сервере"

# Ветка сессии: своя пересборка ТОЙ ЖЕ карты.
git checkout -q master 2>/dev/null || git checkout -q main
printf 'карта сессии\n' > docs/MAP.md
git commit -qam "правка из сессии"

# 1. Конфликт только на карте — сводится сам.
git checkout -q server
git rebase master >/dev/null 2>&1 || git rebase main >/dev/null 2>&1
un_before=$(git diff --name-only --diff-filter=U | tr '\n' ' ')
check "конфликт на карте случился" "docs/MAP.md " "$un_before"
"$TOOL" >/dev/null 2>&1
un_after=$(git diff --name-only --diff-filter=U | tr '\n' ' ')
check "карта сведена сама" "" "$un_after"
marks=$(grep -c '^<<<<<<<\|^=======$\|^>>>>>>>' docs/MAP.md || true)
check "маркеров конфликта в карте не осталось" "0" "$marks"
GIT_EDITOR=true git rebase --continue >/dev/null 2>&1
check "перенос доведён до конца" "0" "$?"

# 2. Смысловой конфликт — НЕ сводится: контроль, без него проверка
#    выше меряла бы «разрешает всё подряд».
git checkout -q master 2>/dev/null || git checkout -q main
printf 'код сессии\n' >> code.py
git commit -qam "правка кода из сессии"
git checkout -q -b other HEAD~1
printf 'код другой\n' >> code.py
git commit -qam "другая правка кода"
git rebase master >/dev/null 2>&1 || git rebase main >/dev/null 2>&1
"$TOOL" >/dev/null 2>&1
un_code=$(git diff --name-only --diff-filter=U | tr '\n' ' ')
check "смысловой конфликт остался на месте" "code.py " "$un_code"
git rebase --abort >/dev/null 2>&1 || true

cd / && rm -rf "$tmp"
printf '\nпрошло %d, упало %d\n' "$ok" "$fail"
[ "$fail" = 0 ] || exit 1
