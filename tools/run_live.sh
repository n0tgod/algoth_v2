#!/usr/bin/env bash
# Запуск/перезапуск ЖИВОГО исполнителя (спека 12, этапы X2–X3).
#
# По умолчанию — СУХОЙ прогон (X2): заявки формируются и проверяются
# по живому справочнику, но НЕ отправляются. Живые заявки включаются
# только явным словом:
#
#   tools/run_live.sh          # X2: сухой прогон, ничего не отправляет
#   tools/run_live.sh --live   # X3: ЖИВЫЕ заявки на 300 $
#   tools/run_live.sh --stop   # остановить исполнитель
#
# Аварийный выключатель, работает мгновенно и без git:
#   touch ~/algoth_v2/bot/out/live/KILL
# После KILL исполнитель не совершает НИЧЕГО — ни заявок, ни отмен.
# Снять: удалить файл. Остановку по журналу (Kill после лимитов §5)
# снимает --clear-halt при следующем запуске, ПОСЛЕ разбора причины.
set -u
cd "$(dirname "$0")/.."

PAT='bot live --s8'
BIN=bot/target/release/bot
LOG=bot/out/live.log
JOURNAL=bot/out/live
S8=research/s8_loop/out/model_sit
KEYS="$HOME/.bybit/live.env"
BASE="https://api.bybit.com"
# Капитал ЗАМЕРА — 300 $ (спека 12 §2), НЕ бумажные 3000 из ядра:
# живой счёт и держит ровно столько.
CAPITAL=300

if [ "${1:-}" = "--stop" ]; then
    echo "== останавливаю исполнитель =="
    pkill -f "$PAT" 2>/dev/null && echo "остановлен" || echo "не был запущен"
    exit 0
fi

MODE_FLAG="--dry"
MODE_NAME="СУХОЙ прогон (X2) — заявки НЕ отправляются"
EXTRA=""
for a in "$@"; do
    case "$a" in
        --live) MODE_FLAG=""; MODE_NAME="ЖИВЫЕ заявки (X3), капитал $CAPITAL \$" ;;
        --clear-halt) EXTRA="--clear-halt" ;;
        *) echo "неизвестный ключ: $a (жду --live / --stop / --clear-halt)"; exit 2 ;;
    esac
done

[ -f "$KEYS" ] || { echo "ОШИБКА: нет файла ключа $KEYS"; exit 1; }

echo "== собираю =="
if ! command -v cargo >/dev/null 2>&1 && [ -f "$HOME/.cargo/env" ]; then
    . "$HOME/.cargo/env"
fi
if command -v cargo >/dev/null 2>&1; then
    cargo build --release --manifest-path bot/Cargo.toml -q \
        || { echo "ОШИБКА: сборка не прошла — старый бинарник не тронут"; exit 1; }
elif [ -x "$BIN" ]; then
    echo "ВНИМАНИЕ: cargo не найден — запускаю ПРЕЖНИЙ бинарник"
else
    echo "ОШИБКА: нет ни cargo, ни собранного бинарника"; exit 1
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

mkdir -p "$JOURNAL" bot/out
echo "== запускаю: $MODE_NAME =="
( setsid nohup "$BIN" live \
    --s8 "$S8" \
    --journal "$JOURNAL" \
    --keys "$KEYS" \
    --base "$BASE" \
    --arm gbm \
    --capital "$CAPITAL" \
    --interval-sec 5 \
    $MODE_FLAG $EXTRA \
    >> "$LOG" 2>&1 & )

# Жив ли процесс и пишет ли статус — команда, вернувшая ноль, не
# доказательство ни того ни другого (правило run_bot.sh).
sleep 8
if ! pgrep -f "$PAT" >/dev/null; then
    echo "ОШИБКА: исполнитель не поднялся. Хвост журнала:"
    tail -20 "$LOG"
    exit 1
fi
for i in $(seq 1 6); do
    [ -f "$JOURNAL/live_status.json" ] && break
    sleep 5
done
if [ -f "$JOURNAL/live_status.json" ]; then
    echo "== поднялся, статус пишется =="
    python3 - <<'PYEOF'
import json
st = json.load(open("bot/out/live/live_status.json"))
print(f"  сухой прогон: {st.get('dry')}")
print(f"  остановка: {st.get('halted') or 'нет'}")
print(f"  позиций: {len(st.get('positions') or [])}")
w = st.get("wallet") or {}
print(f"  кошелёк: equity {w.get('equity')}, balance {w.get('balance')}")
PYEOF
else
    echo "ВНИМАНИЕ: процесс жив, но live_status.json за полминуты не появился"
fi
tail -4 "$LOG"
