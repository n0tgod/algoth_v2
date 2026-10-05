#!/usr/bin/env bash
# Проверка блока сторожа «память сборщика»: перезапуск по потолку RSS,
# только с `--keep-cycle`, строка называет число и возраст; ниже потолка
# — тишина; без процесса — тишина; «ps пуст» — строка, а не перезапуск;
# после обычного перезапуска блок не срабатывает второй раз. Блок
# вырезается из самого сторожа.
#
#     bash tools/test_watchdog_mem.sh
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdmem-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
sed -n '/^# --- память сборщика/,/^# --- цикл обучения/p' tools/watchdog_book.sh \
    | sed '$d' > "$tmp/block.sh"
grep -q "COLLECT_RSS_MAX_MB=" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок не вырезался"; exit 1; }
mkdir -p "$tmp/stubs" "$tmp/tools"
cat > "$tmp/stubs/pgrep" <<'S'
#!/bin/sh
[ -n "${PIDS:-}" ] && echo "$PIDS"
S
cat > "$tmp/stubs/ps" <<'S'
#!/bin/sh
case "$*" in
  *rss=*)    [ -n "${RSS_KB:-}" ] && echo "  $RSS_KB" ;;
  *etimes=*) echo "${ETIMES:-0}" ;;
esac
exit 0
S
printf '#!/bin/sh\necho "restart_book $*" >> "$TESTDIR/ran.log"\n' > "$tmp/tools/restart_book.sh"
chmod +x "$tmp/stubs/"* "$tmp/tools/restart_book.sh"
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
run() {  # $1 pids, $2 RSS КБ, $3 возраст с, $4 need_restart
    rm -f "$tmp/ran.log"
    ( cd "$tmp" && TESTDIR="$tmp" PATH="$tmp/stubs:$PATH" PIDS="$1" RSS_KB="$2" ETIMES="$3" \
        bash -c "now() { echo T; }; need_restart='$4'; . ./block.sh" > "$tmp/out.log" 2>&1 )
}

run 4242 1536000 90360 ""
check "1500 МБ ниже потолка — тишина и без перезапуска" \
      '[ ! -f "$tmp/ran.log" ] && [ ! -s "$tmp/out.log" ]'
run 4242 2560000 90360 ""
check "2500 МБ выше потолка — перезапуск" '[ -f "$tmp/ran.log" ]'
check "перезапуск по памяти идёт с --keep-cycle" 'grep -q "restart_book --keep-cycle" "$tmp/ran.log"'
check "строка называет RSS, потолок и возраст" \
      'grep -q "ПО ПАМЯТИ: RSS 2500 МБ при потолке 2200, возраст 25 ч" "$tmp/out.log"'
run "" "" "" ""
check "процесса нет — тишина (его поднимает блок сборщика)" \
      '[ ! -f "$tmp/ran.log" ] && [ ! -s "$tmp/out.log" ]'
run 4242 "" 90360 ""
check "ps пуст — строка «не измерена», без перезапуска" \
      '[ ! -f "$tmp/ran.log" ] && grep -q "не измерена" "$tmp/out.log"'
run 4242 2560000 90360 "процесс сборщика не найден"
check "после обычного перезапуска блок не срабатывает второй раз" '[ ! -f "$tmp/ran.log" ]'
run "4242,4243" 2560000 90360 ""
check "два pid — берётся наибольший RSS, перезапуск" '[ -f "$tmp/ran.log" ]'

# Отрицательный контроль: сравнение, перевёрнутое на «меньше», обязано
# перезапускать ниже потолка — сперва доказываем, что подделка легла.
cp "$tmp/block.sh" "$tmp/block.good"
sed -i 's/ -gt "\$COLLECT_RSS_MAX_MB"/ -lt "$COLLECT_RSS_MAX_MB"/' "$tmp/block.sh"
grep -q -- '-lt "$COLLECT_RSS_MAX_MB"' "$tmp/block.sh" || { echo "ПАДЕНИЕ: подделка не легла"; exit 1; }
run 4242 1536000 90360 ""
check "перевёрнутое сравнение кусается (контроль)" '[ -f "$tmp/ran.log" ]'
cp "$tmp/block.good" "$tmp/block.sh"

if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока памяти сборщика прошли"
