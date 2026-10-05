#!/usr/bin/env bash
# Проверка `tools/restart_book.sh --keep-cycle`: перезапуск сборщика по
# памяти НЕ трогает циклы обучения, обычный перезапуск — трогает,
# неизвестный аргумент — отказ. Гоняется сам скрипт во временном дереве
# с подставными pgrep/pkill/git/sleep; подставной «питон» отмечает
# подъём сборщика файлом.
#
#     bash tools/test_restart_book.sh
set -u
SRC="$(cd "$(dirname "$0")" && pwd)"
tmp=$(mktemp -d /tmp/rbook-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/tools" "$tmp/stubs" "$tmp/.venv/bin" "$tmp/research/b1_book/out"
cp "$SRC/restart_book.sh" "$tmp/tools/restart_book.sh"
: > "$tmp/research/b1_book/out/collect.log"
# pgrep: сборщик жив, пока есть файл up; цикл жив, пока его не убили.
cat > "$tmp/stubs/pgrep" <<'S'
#!/bin/sh
case "$*" in
  *collect.py*) [ -f "$TESTDIR/up" ] ;;
  *pretest*)    exit 1 ;;                       # предпросмотра давно нет
  *train.py*)   [ ! -f "$TESTDIR/killed_train" ] ;;
  *) exit 1 ;;
esac
S
cat > "$tmp/stubs/pkill" <<'S'
#!/bin/sh
echo "pkill $*" >> "$TESTDIR/calls.log"
case "$*" in
  *collect.py*) rm -f "$TESTDIR/up" ;;
  *train.py*)   touch "$TESTDIR/killed_train" ;;
esac
exit 0
S
printf '#!/bin/sh\necho "git $*" >> "$TESTDIR/calls.log"\nexit 0\n' > "$tmp/stubs/git"
# Подставной sleep не нулевой: подъём идёт фоном (nohup … &), и нулевое
# ожидание спрашивало бы pgrep раньше, чем «питон» отметил подъём.
printf '#!/bin/sh\n/bin/sleep 0.3\n' > "$tmp/stubs/sleep"
printf '#!/bin/sh\ntouch "$TESTDIR/up"\necho "python $*" >> "$TESTDIR/calls.log"\nexit 0\n' \
    > "$tmp/.venv/bin/python"
chmod +x "$tmp/stubs/"* "$tmp/.venv/bin/python" "$tmp/tools/restart_book.sh"

fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
run() {   # $@ — аргументы скрипта; вывод в out.log, код в rc
    rm -f "$tmp/calls.log" "$tmp/killed_train"; touch "$tmp/up"
    ( cd "$tmp" && TESTDIR="$tmp" PATH="$tmp/stubs:$PATH" \
        bash tools/restart_book.sh "$@" > "$tmp/out.log" 2>&1 ); rc=$?
}

run
check "обычный перезапуск: сборщик остановлен и поднят" \
      '[ "$rc" = 0 ] && grep -q "pkill -f b1_book/collect.py" "$tmp/calls.log" && grep -q "python research/b1_book/collect.py --http 8765" "$tmp/calls.log"'
check "обычный перезапуск останавливает цикл обучения (деплой)" \
      'grep -qF "pkill -f s8_loop/train.py\$" "$tmp/calls.log" && grep -q "перезапускаю циклы обучения" "$tmp/out.log"'

run --keep-cycle
check "--keep-cycle: сборщик остановлен и поднят" \
      '[ "$rc" = 0 ] && grep -q "pkill -f b1_book/collect.py" "$tmp/calls.log" && [ -f "$tmp/up" ]'
check "--keep-cycle: цикл обучения НЕ тронут" \
      '! grep -q "train.py" "$tmp/calls.log" && [ ! -f "$tmp/killed_train" ]'
check "--keep-cycle: причина названа в выводе" 'grep -q "не трогаю" "$tmp/out.log"'

run --deploy-all
check "неизвестный аргумент — отказ, ничего не остановлено" \
      '[ "$rc" = 2 ] && [ ! -f "$tmp/calls.log" ]'

# Отрицательный контроль: подделка без проверки флага обязана уронить
# «цикл не тронут». Сперва доказываем, что подделка легла.
cp "$tmp/tools/restart_book.sh" "$tmp/tools/restart_book.good"
sed -i '/^if \[ "\$KEEP_CYCLE" = 1 \]; then$/,/^fi$/d' "$tmp/tools/restart_book.sh"
grep -q 'KEEP_CYCLE" = 1' "$tmp/tools/restart_book.sh" && { echo "ПАДЕНИЕ: подделка не легла"; exit 1; }
run --keep-cycle
check "подделка без флага кусается (контроль): цикл убит" \
      'grep -qF "pkill -f s8_loop/train.py\$" "$tmp/calls.log"'
cp "$tmp/tools/restart_book.good" "$tmp/tools/restart_book.sh"

if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки перезапуска сборщика прошли"
