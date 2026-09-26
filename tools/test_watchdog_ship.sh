#!/usr/bin/env bash
# Проверка блока сторожа «выгрузка записи»: раз в сутки в 03 UTC, только
# когда позавчерашний день не отмечен, без ключей — молчит, идущий
# прогон не дублируется. Блок вырезается из самого сторожа.
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdship-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
sed -n '/^# --- выгрузка записи в хранилище/,/^# --- диски: тревога/p' tools/watchdog_book.sh \
    | sed '$d' > "$tmp/block.sh"
grep -q "record_ship.py" "$tmp/block.sh" || { echo "ПАДЕНИЕ: блок не вырезался"; exit 1; }
mkdir -p "$tmp/stubs" "$tmp/home/.hetzner" "$tmp/research/b1_book/out/ship"
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
run() {  # $1 час, $2 ключи есть (1/0), $3 отметка дня есть (1/0), $4 занят (1/0)
    rm -f "$tmp/ran.log" "$tmp/home/.hetzner/s3.env"
    [ "$2" = 1 ] && echo "S3_BUCKET=x" > "$tmp/home/.hetzner/s3.env"
    day=$(date -u -d "2 days ago" +%Y-%m-%d)
    rm -f "$tmp/research/b1_book/out/ship/$day.ok"
    [ "$3" = 1 ] && echo '{}' > "$tmp/research/b1_book/out/ship/$day.ok"
    cat > "$tmp/stubs/date" <<S
#!/bin/sh
if [ "\$1" = "-u" ] && [ "\$2" = "+%H" ]; then echo $1; else exec /bin/date "\$@"; fi
S
    chmod +x "$tmp/stubs/date"
    ( cd "$tmp" && HOME="$tmp/home" PATH="$tmp/stubs:$PATH" PGREP_RC=$([ "$4" = 1 ] && echo 0 || echo 1) \
        bash -c 'now() { echo T; }; . ./block.sh' >/dev/null 2>&1 )
    sleep 0.3                      # подставной setsid пишет в фоне
    [ -f "$tmp/ran.log" ]
}
cp "$tmp/block.sh" "$tmp/block.sh.bak"
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
check "03 UTC, ключи есть, день не отмечен — прогон" 'run 03 1 0 0'
check "прогон зовёт record_ship со снятием копий" 'grep -q "record_ship.py --prune-days 21" "$tmp/ran.log"'
check "день уже отмечен — молчит" '! run 03 1 1 0'
check "не тот час — молчит" '! run 14 1 0 0'
check "без ключей — молчит" '! run 03 0 0 0'
check "прогон уже идёт — не второй" '! run 03 1 0 1'
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки блока выгрузки прошли"
