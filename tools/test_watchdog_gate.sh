#!/usr/bin/env bash
# Проверка блока сторожа «судья спеки 19»: проход, когда сводка старше 14
# мин или её нет; свежая — молчит; идущий не дублируется; флаг ожидания
# обучения — не стартует; каталог лога создаётся. Блок вырезается до
# следующего заголовка «# --- ».
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdgate-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
awk -v s='# --- судья спеки 19' 'index($0, s) == 1 {on = 1; print; next} on && /^# --- / {exit} on' \
    tools/watchdog_book.sh > "$tmp/block.sh"
grep -q "ai_gate/gate_run.py" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок не вырезался"; exit 1; }
mkdir -p "$tmp/stubs" "$tmp/research/s8_loop/out"
printf '#!/bin/sh\nexit ${PGREP_RC:-1}\n' > "$tmp/stubs/pgrep"
printf '#!/bin/sh\nshift 2\necho "$@" >> ran.log\n' > "$tmp/stubs/setsid"
chmod +x "$tmp/stubs/pgrep" "$tmp/stubs/setsid"
fail=0
run() {  # $1 возраст сводки (пусто — нет), $2 занят (1/0), $3 флаг обучения (1/0)
    rm -f "$tmp/ran.log" "$tmp/research/s8_loop/out/train_wait.flag"
    rm -rf "$tmp/research/ai_gate"
    if [ -n "$1" ]; then
        mkdir -p "$tmp/research/ai_gate/out"
        touch -d "@$(( $(date -u +%s) - $1 ))" "$tmp/research/ai_gate/out/latest.json"
    fi
    [ "$3" = 1 ] && echo 1 > "$tmp/research/s8_loop/out/train_wait.flag"
    [ "$3" = old ] && echo 1 > "$tmp/research/s8_loop/out/train_wait.flag" \
        && touch -d "@$(( $(date -u +%s) - 7200 ))" "$tmp/research/s8_loop/out/train_wait.flag"
    ( cd "$tmp" && PATH="$tmp/stubs:$PATH" PGREP_RC=$([ "$2" = 1 ] && echo 0 || echo 1) \
        bash -c 'now() { echo T; }; . ./block.sh' >/dev/null 2>&1 )
    sleep 0.3
    [ -f "$tmp/ran.log" ]
}
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
check "сводки нет — проход" 'run "" 0 0'
check "проход зовёт судью" 'grep -q "ai_gate/gate_run.py" "$tmp/ran.log"'
check "каталога лога нет — блок его создаёт" 'run "" 0 0; [ -d "$tmp/research/ai_gate/out" ]'
check "сводка 16 мин — проход" 'run 960 0 0'
check "сводка 5 мин — молчит" '! run 300 0 0'
check "проход уже идёт — не второй" '! run "" 1 0'
check "обучение ждёт памяти — не стартует" '! run "" 0 1'
check "флаг висит 2 ч — застрял, проход идёт" 'run "" 0 old'
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока судьи прошли"
