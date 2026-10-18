#!/usr/bin/env bash
# Проверка блока сторожа «состояние рынка»: раз в час в первые 15 минут,
# только когда срез сделан в прошлом часе; идущий прогон не дублируется;
# срез этого часа — молчит. Блок вырезается из самого сторожа.
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdmarket-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
# до СЛЕДУЮЩЕГО заголовка «# --- », каким бы он ни был: блок, вставший
# между соседями, иначе попадал в вырезку (18.10)
awk -v s='# --- состояние рынка: доли лонгов' 'index($0, s) == 1 {on = 1; print; next} on && /^# --- / {exit} on' \
    tools/watchdog_book.sh > "$tmp/block.sh"
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
run() {  # $1 минута часа, $2 срез: prev — прошлый час, same — этот час, пусто — файла нет; $3 занят (1/0)
    rm -f "$tmp/ran.log" "$tmp/research/market_state/out/latest.json"
    f="$tmp/research/market_state/out/latest.json"
    hstart=$(( $(date -u +%s) / 3600 * 3600 ))
    [ "$2" = prev ] && touch -d "@$(( hstart - 1 ))" "$f"
    [ "$2" = same ] && touch -d "@$hstart" "$f"
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
check "минута 07, срез прошлого часа (хоть 1 с назад) — прогон" 'run 07 prev 0'
check "минута 07, срез этого часа — молчит" '! run 07 same 0'
check "минута 40, срез прошлого часа — молчит (не окно часа)" '! run 40 prev 0'
check "прогон уже идёт — не второй" '! run 03 "" 1'
# каталог лога на свежем клоне отсутствует (git пустых не переносит): блок
# обязан создать его сам, иначе перенаправление роняет запуск молча
check "каталога лога нет — блок его создаёт" 'rm -rf "$tmp/research/market_state/out"; run 03 "" 0; [ -d "$tmp/research/market_state/out" ]'
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока состояния рынка прошли"
