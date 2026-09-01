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
mkdir -p research/factory/agents
echo "# роль" > research/factory/agents/brief.md
printf '#!/bin/sh\necho "РОЛЬ $*"\n' > tools/agents_run.sh
chmod +x tools/agents_run.sh
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

# 8а. Отказ `fetch` НЕ молчит: с origin, которого нет, очередь обязана
# сказать об этом файлом. Молчание здесь неотличимо от «новых заданий
# нет», и ровно так очередь однажды замерла на сутки.
git remote add origin "$tmp/нет-такого.git" 2>/dev/null || true
bash tools/jobs.sh >/dev/null 2>&1
has "отказ fetch назван словами" jobs/queue-state.md "не получен"

# 8б. Расхождение чинится публикацией застрявшего, а не замиранием.
# Сервер ушёл вперёд своим коммитом (так кончается публикация, у
# которой не прошёл push), а в origin тем временем лёг новый — и
# ЗАДАНИЕ лежит именно там: если очередь просто замрёт, оно не
# выполнится никогда.
git remote remove origin
# Подсобные репозитории живут ВНЕ рабочего дерева: положив их внутрь,
# тест сам добавил бы их в свой же коммит (`git add -A`).
aux=$(mktemp -d)
bare="$aux/bare.git"; git init -q --bare -b main "$bare"
git branch -M main
git remote add origin "$bare"
git push -q -u origin main
other="$aux/other"; git clone -q "$bare" "$other"
( cd "$other" && git config user.email t@t && git config user.name t \
  && mkdir -p jobs && echo "status" > jobs/j.job \
  && git add -A >/dev/null \
  && git -c core.hooksPath=/dev/null commit -qm "задание" \
  && git push -q origin main )
echo "непушнутая работа" > jobs/local-work.txt
git add -A >/dev/null
git -c core.hooksPath=/dev/null commit -qm "непушнутое"
ahead_before=$(git rev-list --count origin/main..HEAD)
check "перед прогоном сервер и правда впереди" 1 "$ahead_before"
bash tools/jobs.sh >/dev/null 2>&1
has "застрявший коммит опубликован" jobs/queue-state.md "опубликован"
has "и задание из origin выполнено" jobs/done/j.log "диск"
git fetch -q origin main
lost=$(git rev-list --count origin/main..HEAD)
check "непушнутая работа не потеряна" 0 "$lost"

# 10. Публикация переживает ГРЯЗНОЕ дерево при разошедшейся ветке.
# Это ровно та цепочка, что заморозила очередь на живом сервере: пока
# идёт длинное задание, его лог дописывается, `git pull --rebase`
# отказывается начинаться словами «You have unstaged changes», push не
# проходит, коммит остаётся локально — и очередь после этого не
# трогает задания вообще. Гоняется НАСТОЯЩИЙ `publish.sh`.
pub=$(mktemp -d)
(
  cd "$pub" || exit 1
  git init -q -b main .; git config user.email t@t; git config user.name t
  # `publish.sh` добавляет `research/*/out docs jobs` одной командой, и
  # git отвергает ВЕСЬ add, если хоть один путь не существует — поэтому
  # фикстура обязана выглядеть как настоящее дерево, а не как минимум,
  # нужный этой проверке.
  mkdir -p tools research/x/out docs jobs/done
  cp "$SRC/publish.sh" tools/; chmod +x tools/publish.sh
  echo "журнал" > docs/journal.md
  echo "прогон" > research/x/out/run.log
  echo "отчёт" > research/x/out/X-report.md
  git add -A >/dev/null; git -c core.hooksPath=/dev/null commit -qm init
  git init -q --bare -b main "$pub/bare.git"
  git remote add origin "$pub/bare.git"; git push -q -u origin main
  o="$pub/other"; git clone -q "$pub/bare.git" "$o"
  ( cd "$o" && git config user.email t@t && git config user.name t \
    && echo "чужое" > research/x/out/Y-report.md && git add -A >/dev/null \
    && git -c core.hooksPath=/dev/null commit -qm "чужой отчёт" \
    && git push -q origin main )
  # Ветка разошлась И в дереве лежит грязный отслеживаемый лог.
  echo "новые числа" > research/x/out/X-report.md
  echo "прогресс" >> research/x/out/run.log
  bash tools/publish.sh "тест: публикация на грязном дереве" \
      > "$pub/out.txt" 2>&1
)
has "публикация прошла при грязном дереве" "$pub/out.txt" "опубликовано"
left=$( (cd "$pub" && git rev-list --count origin/main..HEAD 2>/dev/null) )
check "непубликованных коммитов не осталось" 0 "${left:-нет}"
dirty=$( (cd "$pub" && git status --porcelain research/x/out/run.log | wc -l) )
check "лог идущего задания вернулся в дерево" 1 "${dirty:-нет}"
rm -rf "$pub"

# 8b. Роль автономной системы: объявленная запускается, выдуманная
# отвергается. Имя роли — это имя файла промпта, и всё, кроме букв,
# здесь означает попытку, а не опечатку.
# Приманка ВНЕ каталога ролей: имя `../evil` собирается в
# `research/factory/agents/../evil.md`, то есть в существующий файл, и
# проверку «файл есть» проходит. Отвергнуть его может ТОЛЬКО проверка
# имени — без неё чужой файл стал бы промптом роли. Первый вариант
# теста этого не различал: `../../etc/passwd` отвергался существованием.
echo "# чужой файл" > research/factory/evil.md
printf 'agents-run brief\n' > jobs/role-ok.job
printf 'agents-run ../evil\n' > jobs/role-bad.job
printf 'agents-run nosuch\n' > jobs/role-none.job
git add -A >/dev/null; git -c core.hooksPath=/dev/null commit -qm roles
bash tools/jobs.sh > /dev/null 2>&1
sleep 1
has "роль запущена" jobs/done/role-ok.log "запускаю роль: brief"
has "подставная запускалка позвана" jobs/done/role-ok.log "РОЛЬ brief"
has "путь наружу отвергнут проверкой ИМЕНИ" jobs/done/role-bad.log "ОТКАЗ"
has "несуществующая роль отвергнута" jobs/done/role-none.log "ОТКАЗ"
if grep -q "РОЛЬ" jobs/done/role-bad.log 2>/dev/null; then
    say "  ПАДЕНИЕ отвергнутая роль всё же звалась"; fail=$((fail+1))
else say "  ok   отвергнутая роль не звалась"; ok=$((ok+1)); fi

# 9. Сторож обязан звать очередь: секция, которую легко потерять при
# правке соседней.
cd - >/dev/null || exit 1
grep -q "tools/jobs.sh" tools/watchdog_book.sh
check "сторож зовёт очередь заданий" 0 $?
cd "$tmp" || exit 1

cd - >/dev/null || exit 1
rm -rf "$tmp" "${aux:-}"
say ""
if [ "$fail" != 0 ]; then say "ЕСТЬ ПАДЕНИЯ: $fail"; exit 1; fi
say "все проверки прошли ($ok)"
