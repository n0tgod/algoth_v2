#!/usr/bin/env bash
# Запуск/перезапуск исполнительного ядра (Rust-тень, спека 09).
#
# Тот же принцип, что restart_book.sh: каждый шаг проверяется, а не
# предполагается — три перезапуска сборщика подряд научили, что отказ,
# неотличимый от успеха, стоит владельцу лишнего круга на сервер.
#
#   tools/run_bot.sh              # собрать и (пере)запустить
#   tools/run_bot.sh --no-build   # только перезапустить (зовёт сторож)
set -u
cd "$(dirname "$0")/.."

PAT='bot run --s8'
BIN=bot/target/release/bot
LOG=bot/out/bot.log
JOURNAL=bot/out/shadow
# Тень ведёт БОЕВУЮ книгу (предпросмотр снят решением владельца
# 2026-08-07). Источник записывается в журнал маркером: журнал — это
# запись одной книги, и смена источника поверх старого журнала дала бы
# сверке смесь двух книг — расхождения, которых не совершал никто.
S8=research/s8_loop/out/model

if [ "${1:-}" != "--no-build" ]; then
    echo "== собираю =="
    if ! command -v cargo >/dev/null 2>&1 \
            && [ -f "$HOME/.cargo/env" ]; then
        # rustup ставит cargo в ~/.cargo, но PATH крона про это не знает.
        . "$HOME/.cargo/env"
    fi
    if command -v cargo >/dev/null 2>&1; then
        cargo build --release --manifest-path bot/Cargo.toml -q \
            || { echo "ОШИБКА: сборка не прошла — старый бинарник не тронут"; exit 1; }
    elif [ -x "$BIN" ]; then
        echo "ВНИМАНИЕ: cargo не найден — запускаю ПРЕЖНИЙ бинарник"
    else
        echo "ОШИБКА: нет ни cargo, ни собранного бинарника."
        echo "Однократно на сервере:"
        echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"
        echo "  . \"\$HOME/.cargo/env\""
        exit 1
    fi
fi
[ -x "$BIN" ] || { echo "ОШИБКА: бинарник $BIN не найден"; exit 1; }

echo "== останавливаю прежний =="
pkill -f "$PAT" 2>/dev/null
for i in $(seq 1 20); do
    pgrep -f "$PAT" >/dev/null || break
    sleep 1
done
if pgrep -f "$PAT" >/dev/null; then
    echo "не закрылся — добиваю"
    pkill -9 -f "$PAT" 2>/dev/null; sleep 2
fi

echo "== запускаю =="
mkdir -p "$JOURNAL"
# Журнал от другого источника архивируется, а не дописывается. У
# журналов до введения маркера источником был предпросмотр — их
# застаёт та же проверка: отсутствие маркера при непустом журнале
# означает «писано до маркера», то есть предпросмотром.
MARK="$JOURNAL/source.txt"
CUR=$(cat "$MARK" 2>/dev/null || true)
if [ "$CUR" != "$S8" ] \
        && ls "$JOURNAL"/journal-*.jsonl* >/dev/null 2>&1; then
    ARCH="${JOURNAL}-$(date -u +%Y%m%d-%H%M%S)"
    echo "== журнал писан другим источником (${CUR:-до маркера}) =="
    echo "   архивирую в $ARCH и начинаю чистый"
    mv "$JOURNAL" "$ARCH"
    mkdir -p "$JOURNAL"
fi
printf '%s\n' "$S8" > "$MARK"
( setsid nohup "$BIN" run \
    --s8 "$S8" \
    --journal "$JOURNAL" \
    --arm gbm \
    --fees research/a1_universe/out/fees.json \
    --sverka bot/sverka.py --python python3 \
    >> "$LOG" 2>&1 & )

# Жив ли ПРОЦЕСС — и пишет ли СТАТУС: команда, вернувшая ноль, не
# доказательство ни того ни другого.
sleep 8
if ! pgrep -f "$PAT" >/dev/null; then
    echo "ОШИБКА: ядро не поднялось. Хвост журнала:"
    tail -20 "$LOG"
    exit 1
fi
for i in $(seq 1 12); do
    [ -f "$JOURNAL/status.json" ] && break
    sleep 5
done
if [ -f "$JOURNAL/status.json" ]; then
    echo "== поднялось, статус пишется =="
else
    echo "ВНИМАНИЕ: процесс жив, но status.json за минуту не появился"
fi
tail -4 "$LOG"
