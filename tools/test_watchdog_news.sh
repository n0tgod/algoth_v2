#!/usr/bin/env bash
# Проверка блока сторожа «новостной фон»: прогон, когда срез старше 14 мин
# или его нет; свежий — молчит; идущий не дублируется. Блок вырезается из
# самого сторожа.
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdnews-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
# до СЛЕДУЮЩЕГО заголовка «# --- », каким бы он ни был: блок, вставший
# между соседями, иначе попадал в вырезку (18.10)
awk -v s='# --- новостной фон: RSS' 'index($0, s) == 1 {on = 1; print; next} on && /^# --- / {exit} on' \
    tools/watchdog_book.sh > "$tmp/block.sh"
grep -q "research/news/collect.py" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок не вырезался"; exit 1; }
mkdir -p "$tmp/stubs" "$tmp/research/news/out"
printf '#!/bin/sh\nexit ${PGREP_RC:-1}\n' > "$tmp/stubs/pgrep"
printf '#!/bin/sh\nshift 2\necho "$@" >> ran.log\n' > "$tmp/stubs/setsid"
chmod +x "$tmp/stubs/pgrep" "$tmp/stubs/setsid"
fail=0
run() {  # $1 возраст среза в секундах (пусто — файла нет), $2 занят (1/0)
    rm -f "$tmp/ran.log" "$tmp/research/news/out/latest.json"
    [ -n "$1" ] && touch -d "@$(( $(date -u +%s) - $1 ))" "$tmp/research/news/out/latest.json"
    ( cd "$tmp" && PATH="$tmp/stubs:$PATH" PGREP_RC=$([ "$2" = 1 ] && echo 0 || echo 1) \
        bash -c 'now() { echo T; }; . ./block.sh' >/dev/null 2>&1 )
    sleep 0.3
    [ -f "$tmp/ran.log" ]
}
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
check "среза нет — прогон" 'run "" 0'
check "прогон зовёт сборщик новостей" 'grep -q "research/news/collect.py" "$tmp/ran.log"'
check "срез 16 мин — прогон" 'run 960 0'
check "срез 5 мин — молчит" '! run 300 0'
check "прогон уже идёт — не второй" '! run "" 1'
# каталог лога на свежем клоне отсутствует (git пустых не переносит): блок
# обязан создать его сам, иначе перенаправление роняет запуск молча
check "каталога лога нет — блок его создаёт" 'rm -rf "$tmp/research/news/out"; run "" 0; [ -d "$tmp/research/news/out" ]'
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока новостного фона прошли"
