#!/usr/bin/env bash
# Проверка проверки: safety_check обязан кусаться на каждом случае,
# ради которого написан, и молчать на обычном коммите.
#
# Гоняется в НАСТОЯЩЕМ временном репозитории — не в рабочем: тест,
# который что-то стягивает в индекс основного дерева, однажды
# закоммитит это сам.
set -u
CHECK="$(cd "$(dirname "$0")" && pwd)/safety_check.sh"
ok=0
fail=0

say() { printf '%s\n' "$*"; }
check() {                       # имя, ожидание (0 = молчит, 1 = кусается)
    local name="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
        say "  ok   $name"
        ok=$((ok + 1))
    else
        say "  ПАДЕНИЕ $name: ждали $want, получили $got"
        fail=$((fail + 1))
    fi
}

tmp=$(mktemp -d)
cd "$tmp" || exit 1
git init -q .
git config user.email t@t
git config user.name t
mkdir -p research/x/out docs
echo "отчёт" > research/x/out/report.md
echo "спека" > docs/01-spec.md
echo "код" > code.py
git add research/x/out/report.md docs/01-spec.md code.py
git -c core.hooksPath=/dev/null commit -qm "начало"

# 1. Обычный коммит — молчит.
echo "правка" >> code.py
git add code.py
"$CHECK" >/dev/null 2>&1
check "обычный коммит проходит" 0 $?
git -c core.hooksPath=/dev/null commit -qm "правка"

# 2. Удаление артефакта — отказ.
git rm -q research/x/out/report.md
"$CHECK" >/dev/null 2>&1
check "удаление артефакта прогона останавливает коммит" 1 $?
ALLOW_DELETE=1 "$CHECK" >/dev/null 2>&1
check "осознанное удаление разрешено явным намерением" 0 $?
git reset -q --hard

# 3. Маркеры конфликта — отказ.
printf 'a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> other\n' > research/x/out/r2.md
git add research/x/out/r2.md
"$CHECK" >/dev/null 2>&1
check "склейка с маркерами конфликта не публикуется" 1 $?
git reset -q --hard; rm -f research/x/out/r2.md

# 4. Секрет файлом — отказ.
echo "KEY=abc" > live.env
git add -f live.env
"$CHECK" >/dev/null 2>&1
check "файл с ключом не уходит в git" 1 $?
git reset -q --hard; rm -f live.env

# 5. Секрет содержимым — отказ.
# Строка собирается ИЗ ЧАСТЕЙ, поэтому в самом тесте присвоения
# ключа нет — иначе проверка (справедливо) заворачивала бы собственный
# тест. Настоящий ключ здесь недопустим тем более: ключ в тесте — это
# тот же ключ в git, только под видом проверки.
key="Example"; key="${key}NotAReal"; key="${key}Key0000000000"
printf 'API_%s = "%s"\n' SECRET "$key" > cfg.py
git add cfg.py
"$CHECK" >/dev/null 2>&1
check "присвоение ключа в коде не уходит в git" 1 $?
git reset -q --hard; rm -f cfg.py

# 6. Крупный файл — отказ.
head -c 6000000 /dev/zero > research/x/out/big.bin
git add -f research/x/out/big.bin
"$CHECK" >/dev/null 2>&1
check "ряд размером в мегабайты не уходит в git" 1 $?
git reset -q --hard; rm -f research/x/out/big.bin

# 7. Хук на месте и исполняем.
cd - >/dev/null || exit 1
[ -x tools/githooks/pre-commit ]
check "хук исполняем" 0 $?

rm -rf "$tmp"
say ""
if [ "$fail" != 0 ]; then
    say "ЕСТЬ ПАДЕНИЯ: $fail"
    exit 1
fi
say "все проверки прошли ($ok)"
