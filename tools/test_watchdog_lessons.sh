#!/usr/bin/env bash
# Проверка блока сторожа «уроки судьи»: раз в неделю в час 07 UTC, когда
# сводка старше 6.5 суток; другой час — молчит; свежая сводка — молчит;
# идущий не дублируется; свежий флаг обучения — не стартует. Блок — до «# --- ».
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdls-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
awk -v s='# --- уроки судьи' 'index($0, s) == 1 {on = 1; print; next} on && /^# --- / {exit} on' \
    tools/watchdog_book.sh > "$tmp/block.sh"
grep -q "ai_gate/lessons.py" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок не вырезался"; exit 1; }
mkdir -p "$tmp/stubs" "$tmp/research/s8_loop/out"
printf '#!/bin/sh\nexit ${PGREP_RC:-1}\n' > "$tmp/stubs/pgrep"
printf '#!/bin/sh\nshift 2\necho "$@" >> ran.log\n' > "$tmp/stubs/setsid"
chmod +x "$tmp/stubs/pgrep" "$tmp/stubs/setsid"
fail=0
run() {  # $1 час UTC, $2 возраст сводки (пусто — нет), $3 занят, $4 флаг обучения
    rm -f "$tmp/ran.log" "$tmp/research/s8_loop/out/train_wait.flag"; rm -rf "$tmp/research/ai_gate"
    if [ -n "$2" ]; then mkdir -p "$tmp/research/ai_gate/out"
        touch -d "@$(( $(date -u +%s) - $2 ))" "$tmp/research/ai_gate/out/lessons.json"; fi
    [ "$4" = 1 ] && echo 1 > "$tmp/research/s8_loop/out/train_wait.flag"
    cat > "$tmp/stubs/date" <<S
#!/bin/sh
if [ "\$1" = "-u" ] && [ "\$2" = "+%H" ]; then echo $1; else exec /bin/date "\$@"; fi
S
    chmod +x "$tmp/stubs/date"
    ( cd "$tmp" && PATH="$tmp/stubs:$PATH" PGREP_RC=$([ "$3" = 1 ] && echo 0 || echo 1) \
        bash -c 'now() { echo T; }; . ./block.sh' >/dev/null 2>&1 )
    sleep 0.3
    [ -f "$tmp/ran.log" ]
}
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
check "07 UTC, сводки нет — прогон" 'run 07 "" 0 0'
check "прогон зовёт уроки" 'grep -q "ai_gate/lessons.py" "$tmp/ran.log"'
check "07 UTC, сводка 7 суток — прогон" 'run 07 604800 0 0'
check "07 UTC, сводка 2 суток — молчит" '! run 07 172800 0 0'
check "08 UTC — молчит" '! run 08 "" 0 0'
check "идёт — не второй" '! run 07 "" 1 0'
check "обучение ждёт — не стартует" '! run 07 "" 0 1'
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока уроков судьи прошли"
