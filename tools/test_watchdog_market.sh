#!/usr/bin/env bash
# Проверка блока сторожа «состояние рынка»: раз в час в первые 15 минут,
# только когда срез старше 50 мин; идущий прогон не дублируется; свежий
# срез — молчит. Блок вырезается из самого сторожа.
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdmarket-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
sed -n '/^# --- состояние рынка: доли лонгов/,/^# --- очередь заданий/p' tools/watchdog_book.sh \
    | sed '$d' > "$tmp/block.sh"
grep -q "market_state/collect.py" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок не вырезался"; exit 1; }
mkdir -p "$tmp/stubs" "$tmp/research/market_state/out"
cat > "$tmp/stubs/pgrep" <<'S'
#!/bin/sh
exit ${PGREP_RC:-1}
S
cat > "$tmp/stubs/setsid" <<'S'
#!/bin/sh
shift 2
echo "$@" >> ran.log
S
chmod +x "$tmp/stubs/pgrep" "$tmp/stubs/setsid"
fail=0
run() {  # $1 минута часа, $2 возраст среза в секундах (пусто — файла нет), $3 занят (1/0)
    rm -f "$tmp/ran.log" "$tmp/research/market_state/out/latest.json"
    if [ -n "$2" ]; then
        touch -d "@$(( $(date -u +%s) - $2 ))" "$tmp/research/market_state/out/latest.json"
    fi
    cat > "$tmp/stubs/date" <<S
#!/bin/sh
if [ "\$1" = "-u" ] && [ "\$2" = "+%M" ]; then echo $1; else exec /bin/date "\$@"; fi
S
    chmod +x "$tmp/stubs/date"
    ( cd "$tmp" && PATH="$tmp/stubs:$PATH" PGREP_RC=$([ "$3" = 1 ] && echo 0 || echo 1) \
        bash -c 'now() { echo T; }; . ./block.sh' >/dev/null 2>&1 )
    sleep 0.3
    [ -f "$tmp/ran.log" ]
}
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
check "минута 03, среза нет — прогон" 'run 03 "" 0'
check "прогон зовёт сборщик состояния" 'grep -q "market_state/collect.py" "$tmp/ran.log"'
check "минута 07, срез 55 мин — прогон" 'run 07 3300 0'
check "минута 07, срез 20 мин — молчит" '! run 07 1200 0'
check "минута 40, срез 3 ч — молчит (не окно часа)" '! run 40 10800 0'
check "прогон уже идёт — не второй" '! run 03 "" 1'
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока состояния рынка прошли"
