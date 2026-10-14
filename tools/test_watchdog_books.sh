#!/usr/bin/env bash
# Проверка гейта прогонов книг в стороже (`books_mem_ok`): один прогон
# за раз (14.10) — идёт другой прогон книг или в этом такте один уже
# запущен — отложить со строкой; цикл тяжелее порога — отложить; памяти
# мало — отложить; всё свободно — идти. Функции вырезаются из самого
# сторожа, `pgrep`/`ps` и /proc/meminfo подменяются.
#
#     bash tools/test_watchdog_books.sh
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdbooks-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
sed -n '/^MEMINFO=/,/^# --- сборщик/p' tools/watchdog_book.sh | sed '$d' > "$tmp/gate.sh"
grep -q "books_running()" "$tmp/gate.sh" || { echo "ПАДЕНИЕ: гейт не вырезался"; exit 1; }
mkdir -p "$tmp/stubs"
# pgrep: BOOKS — ответ на прогоны книг, TRAIN — pid цикла
cat > "$tmp/stubs/pgrep" <<'S'
#!/bin/sh
case "$*" in
  *dca_paper*) [ -n "${BOOKS:-}" ] && { echo "$BOOKS"; exit 0; }; exit 1 ;;
  *s8_loop*)   [ -n "${TRAIN:-}" ] && { echo "$TRAIN"; exit 0; }; exit 1 ;;
esac
exit 1
S
cat > "$tmp/stubs/ps" <<'S'
#!/bin/sh
[ -n "${TRAIN_KB:-}" ] && echo "  $TRAIN_KB"
exit 0
S
chmod +x "$tmp/stubs/"*
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
run() {  # $1 прогоны книг (pid), $2 запущено в такте, $3 pid цикла, $4 RSS цикла КБ, $5 MemAvailable КБ
    printf 'MemAvailable:   %s kB\n' "$5" > "$tmp/meminfo"
    ( cd "$tmp" && PATH="$tmp/stubs:$PATH" BOOKS="$1" TRAIN="$3" TRAIN_KB="$4" MEMINFO="$tmp/meminfo" \
        bash -c "now() { echo T; }; . ./gate.sh; BOOKS_LAUNCHED='$2'; if books_mem_ok; then echo ИДТИ; fi" \
        > "$tmp/out.log" 2>&1 )
}

run "" "" "" "" 4096000
check "всё свободно, 4000 МБ — идти" 'grep -q ИДТИ "$tmp/out.log"'
run "" "длинные книги" "" "" 4096000
check "в этом такте уже запущены длинные — отложить (03:10 14.10)" \
      '! grep -q ИДТИ "$tmp/out.log" && grep -q "в этом такте уже запущен длинные книги — по одному" "$tmp/out.log"'
run 777 "" "" "" 4096000
check "идёт другой прогон книг — отложить со строкой" \
      '! grep -q ИДТИ "$tmp/out.log" && grep -q "идёт другой прогон книг" "$tmp/out.log"'
run "" "" 555 2150400 4096000
check "цикл 2100 МБ — учится, отложить" \
      '! grep -q ИДТИ "$tmp/out.log" && grep -q "идёт обучение S8 (цикл 2100 МБ" "$tmp/out.log"'
run "" "" 555 1126400 2048000
check "памяти 2000 МБ при пороге 2500 — отложить" \
      '! grep -q ИДТИ "$tmp/out.log" && grep -q "доступно 2000 МБ" "$tmp/out.log"'

# Отрицательный контроль: без проверки «уже запущен в такте» второй
# прогон того же такта проходит — сперва доказываем, что подделка легла.
cp "$tmp/gate.sh" "$tmp/gate.good"
sed -i 's/if \[ -n "\$BOOKS_LAUNCHED" \]; then/if false; then/' "$tmp/gate.sh"
grep -q 'if false; then' "$tmp/gate.sh" || { echo "ПАДЕНИЕ: подделка не легла"; exit 1; }
run "" "длинные книги" "" "" 4096000
check "без проверки такта второй прогон проходит (контроль)" 'grep -q ИДТИ "$tmp/out.log"'
cp "$tmp/gate.good" "$tmp/gate.sh"

# Сторож ставит метку после КАЖДОГО из трёх запусков
n=$(grep -c '^        BOOKS_LAUNCHED="' tools/watchdog_book.sh)
check "метка запуска стоит у всех трёх прогонов книг ($n)" '[ "$n" -eq 3 ]'

if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки гейта прогонов книг прошли"
