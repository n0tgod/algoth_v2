#!/usr/bin/env bash
# Проверка очереди заданий: она выполняет объявленное и отвергает всё
# остальное. Гоняется в НАСТОЯЩЕМ временном репозитории — тест, который
# запускает задания в рабочем дереве, однажды запустит их на сервере.
set -u
SRC="$(cd "$(dirname "$0")" && pwd)"
ok=0; fail=0
say() { printf '%s\n' "$*"; }
check() {
    if [ "$2" = "$3" ]; then say "  ok   $1"; ok=$((ok+1))
    else say "  ПАДЕНИЕ $1: ждали $2, получили $3"; fail=$((fail+1)); fi
}
has() {   # имя, файл, образец → образец обязан найтись
    if grep -q "$3" "$2" 2>/dev/null; then say "  ok   $1"; ok=$((ok+1))
    else say "  ПАДЕНИЕ $1: нет «$3» в $(basename "$2")"; fail=$((fail+1)); fi
}

tmp=$(mktemp -d); cd "$tmp" || exit 1
git init -q .; git config user.email t@t; git config user.name t
mkdir -p tools research/probe_x jobs .venv/bin
cp "$SRC/jobs.sh" tools/
# Подставные: питон печатает метку, публикация только отмечается.
printf '#!/bin/sh\nshift 0\necho "ПРОГОН $*"\n' > .venv/bin/python
printf '#!/bin/sh\necho "ОПУБЛИКОВАНО $1" >> jobs/publish.log\n' \
    > tools/publish.sh
printf '#!/bin/sh\necho "СБОРЩИК ПЕРЕЗАПУЩЕН"\n' > tools/restart_book.sh
chmod +x .venv/bin/python tools/publish.sh tools/restart_book.sh tools/jobs.sh
echo "print(1)" > research/probe_x/probe.py
git add -A >/dev/null; git -c core.hooksPath=/dev/null commit -qm init

run() { JOBS_NO_FETCH=1 bash tools/jobs.sh >/dev/null 2>&1; }

# 1. Обычное задание выполняется.
echo "run research/probe_x/probe.py --tag smoke" > jobs/a.job
run; sleep 1
has "объявленный прогон выполняется" jobs/done/a.log "ПРОГОН"
has "аргументы дошли до прогона" jobs/done/a.log "smoke"
has "результат публикуется сам" jobs/publish.log "job: a"

# 2. Повторный проход не запускает то же задание снова.
before=$(grep -c "ПРОГОН" jobs/done/a.log)
run; sleep 1
after=$(grep -c "ПРОГОН" jobs/done/a.log)
check "выполненное задание не повторяется" "$before" "$after"

# 3. Скрипт вне репозитория — отказ.
echo "run /etc/passwd" > jobs/b.job
run; sleep 1
has "скрипт вне репозитория отвергнут" jobs/done/b.log "ОТКАЗ"

# 4. Несуществующий скрипт — отказ.
echo "run research/probe_x/нет.py" > jobs/c.job
run; sleep 1
has "несуществующий скрипт отвергнут" jobs/done/c.log "ОТКАЗ"

# 5. Инъекция в аргументах — отказ (главная проверка файла).
printf 'run research/probe_x/probe.py; rm -rf /\n' > jobs/d.job
run; sleep 1
has "точка с запятой в задании отвергнута" jobs/done/d.log "ОТКАЗ"
[ -f research/probe_x/probe.py ]
check "файлы репозитория целы после попытки инъекции" 0 $?

printf 'run research/probe_x/probe.py $(touch /tmp/pwned_jobs_test)\n' \
    > jobs/e.job
run; sleep 1
has "подстановка команды отвергнута" jobs/done/e.log "ОТКАЗ"
[ ! -f /tmp/pwned_jobs_test ]
check "подстановка не выполнилась" 0 $?

# 6. Неизвестное действие — отказ.
echo "reboot" > jobs/f.job
run; sleep 1
has "неизвестное действие отвергнуто" jobs/done/f.log "неизвестное действие"

# 7. Объявленные служебные действия работают.
echo "restart-book" > jobs/g.job
run; sleep 1
has "перезапуск сборщика выполняется" jobs/done/g.log "СБОРЩИК ПЕРЕЗАПУЩЕН"
echo "status" > jobs/h.job
run; sleep 1
has "снятие состояния выполняется" jobs/done/h.log "диск"

# 8. Расхождение с origin не даёт трогать задания.
echo "run research/probe_x/probe.py" > jobs/i.job
out=$(bash tools/jobs.sh 2>&1)   # без JOBS_NO_FETCH, origin нет вовсе
[ ! -f jobs/done/i.log ]
check "без связи с origin задания не выполняются" 0 $?

# 9. Сторож обязан звать очередь: секция, которую легко потерять при
# правке соседней.
cd - >/dev/null || exit 1
grep -q "tools/jobs.sh" tools/watchdog_book.sh
check "сторож зовёт очередь заданий" 0 $?
cd "$tmp" || exit 1

cd - >/dev/null || exit 1
rm -rf "$tmp"
say ""
if [ "$fail" != 0 ]; then say "ЕСТЬ ПАДЕНИЯ: $fail"; exit 1; fi
say "все проверки прошли ($ok)"
