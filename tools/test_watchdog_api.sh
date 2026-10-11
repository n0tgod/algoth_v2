#!/usr/bin/env bash
# Проверка правила сторожа для API приложения (11.10): живой, но не
# отвечающий процесс перезапускается на ВТОРОМ такте без ответа.
#
# Берётся сам блок сторожа (от «API приложения» до «живые исполнители»),
# а не копия; pgrep, curl, pkill, setsid подменены функциями.
#
#     bash tools/test_watchdog_api.sh
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdapi-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
sed -n '/^# --- API приложения/,/^# --- живые исполнители/p' tools/watchdog_book.sh > "$tmp/block.sh"
grep -q "api/v1/health" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок сторожа не вырезался"; exit 1; }
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }

tick() {   # $1 — жив ли процесс (1/0), $2 — отвечает ли (1/0)
    (
        cd "$tmp/root"
        now() { echo "2026-10-11T04:00:00Z"; }
        pgrep() { [ "$ALIVE" = 1 ]; }
        curl() { [ "$ANSWERS" = 1 ]; }
        pkill() { echo "pkill $*" >> "$tmp/calls"; }
        setsid() { echo "setsid $*" >> "$tmp/calls"; }
        sleep() { :; }
        ALIVE=$1 ANSWERS=$2
        # shellcheck disable=SC1090
        . "$tmp/block.sh"
    ) >> "$tmp/out" 2>&1
}
mkdir -p "$tmp/root/tools/app_api/out/tls"
touch "$tmp/root/tools/app_api/out/master.pub" "$tmp/root/tools/app_api/out/tls/cert.pem"
DEAF=$tmp/root/tools/app_api/out/deaf.since

: > "$tmp/calls"; tick 1 1
check "живой и отвечает — ничего не трогается" '[ ! -s "$tmp/calls" ] && [ ! -f "$DEAF" ]'
tick 1 0
check "первый такт без ответа — только отметка, без перезапуска" '[ ! -s "$tmp/calls" ] && [ -f "$DEAF" ]'
tick 1 0
check "второй такт без ответа — перезапуск (контроль ночи 11.10)" 'grep -q "pkill -f app_api/server.py" "$tmp/calls" && grep -q "setsid .*app_api/server.py" "$tmp/calls" && [ ! -f "$DEAF" ]'
check "причина перезапуска названа" 'grep -q "не отвечает на health" "$tmp/out"'
: > "$tmp/calls"; tick 1 0; tick 1 1
check "ответил после одного пропуска — отметка снята, перезапуска нет" '[ ! -s "$tmp/calls" ] && [ ! -f "$DEAF" ]'
: > "$tmp/calls"; tick 0 0
check "процесса нет — запуск сразу" 'grep -q "setsid .*app_api/server.py" "$tmp/calls"'
[ "$fail" = 0 ] && echo "все проверки прошли" || { echo "ЕСТЬ ПАДЕНИЯ"; exit 1; }
