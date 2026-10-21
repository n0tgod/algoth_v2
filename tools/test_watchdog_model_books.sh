#!/usr/bin/env bash
# Проверка блока сторожа «книги модели» (спека 19 §12): в 08 UTC при сводке
# старше 20 ч — суточный прогон; иначе, минута ≥ 10, при книгах ТВХ в реестре
# и отметке тика старше 55 мин — тик; без книг ТВХ тик молчит; идущий не
# дублируется; свежий флаг обучения — не стартует. Блок — до следующего «# --- ».
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdmb-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
awk -v s='# --- книги модели' 'index($0, s) == 1 {on = 1; print; next} on && /^# --- / {exit} on' \
    tools/watchdog_book.sh > "$tmp/block.sh"
grep -q "ai_gate/model_books.py" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок не вырезался"; exit 1; }
mkdir -p "$tmp/stubs" "$tmp/research/s8_loop/out"
printf '#!/bin/sh\nexit ${PGREP_RC:-1}\n' > "$tmp/stubs/pgrep"
printf '#!/bin/sh\nshift 2\necho "$@" >> ran.log\n' > "$tmp/stubs/setsid"
chmod +x "$tmp/stubs/pgrep" "$tmp/stubs/setsid"
fail=0
run() {  # $1 час, $2 минута, $3 возраст сводки, $4 возраст тика, $5 книги ТВХ, $6 занят, $7 флаг
    rm -f "$tmp/ran.log" "$tmp/research/s8_loop/out/train_wait.flag"; rm -rf "$tmp/research/ai_gate"
    mkdir -p "$tmp/research/ai_gate/out/record"
    [ -n "$3" ] && touch -d "@$(( $(date -u +%s) - $3 ))" "$tmp/research/ai_gate/out/model_books_latest.json"
    [ -n "$4" ] && touch -d "@$(( $(date -u +%s) - $4 ))" "$tmp/research/ai_gate/out/record/model_tick.json"
    if [ "$5" = 1 ]; then printf '{"books": [{"id": "m01", "kind": "entry"}]}' > "$tmp/research/ai_gate/out/model_books.json"
    else printf '{"books": [{"id": "m01", "kind": "skip"}]}' > "$tmp/research/ai_gate/out/model_books.json"; fi
    [ "$7" = 1 ] && echo 1 > "$tmp/research/s8_loop/out/train_wait.flag"
    cat > "$tmp/stubs/date" <<S
#!/bin/sh
if [ "\$1" = "-u" ] && [ "\$2" = "+%H" ]; then echo $1
elif [ "\$1" = "-u" ] && [ "\$2" = "+%M" ]; then echo $2
else exec /bin/date "\$@"; fi
S
    chmod +x "$tmp/stubs/date"
    ( cd "$tmp" && PATH="$tmp/stubs:$PATH" PGREP_RC=$([ "$6" = 1 ] && echo 0 || echo 1) \
        bash -c 'now() { echo T; }; . ./block.sh' >/dev/null 2>&1 )
    sleep 0.3
    [ -f "$tmp/ran.log" ]
}
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
check "08 UTC, сводки нет — суточный прогон" 'run 08 30 "" 600 0 0 0'
check "суточный — без --tick" 'grep -q "model_books.py" "$tmp/ran.log" && ! grep -q -- "--tick" "$tmp/ran.log"'
check "08 UTC, сводка 3 ч — суточный молчит (тика нет без ТВХ)" '! run 08 30 10800 "" 0 0 0'
check "книги ТВХ, тик 1 ч, минута 30 — тик" 'run 14 30 3600 3600 1 0 0'
check "тик зовёт --tick" 'grep -q -- "--tick" "$tmp/ran.log"'
check "книги ТВХ, тик 20 мин — молчит" '! run 14 30 3600 1200 1 0 0'
check "минута 5 — тик молчит" '! run 14 5 3600 "" 1 0 0'
check "без книг ТВХ — тик молчит" '! run 14 30 3600 "" 0 0 0'
check "идёт — не второй" '! run 08 30 "" "" 1 1 0'
check "обучение ждёт — не стартует" '! run 08 30 "" "" 1 0 1'
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока книг модели прошли"
