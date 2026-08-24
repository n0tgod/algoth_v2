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
# Денежные пределы §5 (день −15 $, итог −45 $) — решение владельца о
# риске, снимаются и возвращаются БЕЗ перезапуска:
#   tools/run_live.sh --limits-off   # снять денежные пределы
#   tools/run_live.sh --limits-on    # вернуть их
# Прочие остановки (расхождение с биржей, три отказа подряд, KILL,
# молчание часового цикла) этим НЕ снимаются: они не про аппетит к
# риску, а про работу вслепую.
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
# Книга исполнителя — ключом --book (sit | sit_lo). Умолчание — sit:
# живой счёт не меняет книгу от чьей-то забывчивости. Перевод на
# другую книгу — процедура из двух шагов (решение владельца
# 2026-08-22): сперва --no-entries (входы гаснут, выходы сопровождают
# открытое), затем, когда позиций ноль, --book sit_lo — журнал
# отставляется в архив вместе с флагом паузы, и чистый начинается уже
# на новой книге.
BOOK=sit
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

# Денежные пределы §5 снимаются и возвращаются БЕЗ перезапуска:
# исполнитель читает маркер каждым тактом (5 с). Перезапуск живого
# исполнителя сам по себе рискован — длинная команда с телефона уже
# однажды стоила журнала, — поэтому решение о риске кладётся файлом,
# а не ключом старта.
if [ "${1:-}" = "--limits-off" ]; then
    mkdir -p "$JOURNAL"
    : > "$JOURNAL/LIMITS_OFF"
    echo "== ДЕНЕЖНЫЕ пределы §5 СНЯТЫ: $JOURNAL/LIMITS_OFF =="
    echo "   день −15 \$ и итог −45 \$ больше НЕ останавливают исполнитель."
    echo "   Взведёнными остаются: сверка с биржей, три отказа подряд,"
    echo "   KILL, молчание часового цикла дольше 3 ч."
    echo "   Вернуть: tools/run_live.sh --limits-on"
    exit 0
fi
if [ "${1:-}" = "--limits-on" ]; then
    rm -f "$JOURNAL/LIMITS_OFF"
    echo "== денежные пределы §5 ВЕРНУЛИСЬ: день −15 \$, итог −45 \$ =="
    echo "   Если минус дня уже глубже предела, ближайший такт остановит"
    echo "   исполнитель и закроет позиции — это и есть предел."
    exit 0
fi

MODE_FLAG="--dry"
MODE_NAME="СУХОЙ прогон (X2) — заявки НЕ отправляются"
EXTRA=""
NO_ENTRIES=""
ARCHIVE_OPEN=""
expect_book=""
for a in "$@"; do
    if [ -n "$expect_book" ]; then
        case "$a" in
            sit)    BOOK=sit;    S8=research/s8_loop/out/model_sit ;;
            sit_lo) BOOK=sit_lo; S8=research/s8_loop/out/model_sit_lo ;;
            *) echo "неизвестная книга: $a (жду sit / sit_lo)"; exit 2 ;;
        esac
        expect_book=""
        continue
    fi
    case "$a" in
        --live) MODE_FLAG=""; MODE_NAME="ЖИВЫЕ заявки (X3), капитал $CAPITAL \$" ;;
        --clear-halt) EXTRA="--clear-halt" ;;
        --book) expect_book=1 ;;
        --no-entries) NO_ENTRIES=1 ;;
        --archive-with-open) ARCHIVE_OPEN=1 ;;
        *) echo "неизвестный ключ: $a (жду --live / --stop / --clear-halt / --book / --no-entries / --archive-with-open / --limits-off / --limits-on)"; exit 2 ;;
    esac
done
[ -n "$expect_book" ] && { echo "--book требует имени книги (sit / sit_lo)"; exit 2; }

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

# Журнал сухого прогона и журнал живых заявок описывают РАЗНОЕ: первый
# полон записей «сформирована, не отправлена», и смешав их, отчёт X4
# посчитал бы сухие отказы настоящими — доля отказов, проскальзывание и
# число кругов вышли бы из смеси гипотетического с реальным. Тот же
# приём, что маркер источника у тени: смена режима отставляет журнал в
# архив, а не дописывает поверх. Файл KILL переносится в свежий каталог
# — аварийный выключатель не снимается сменой режима.
WANT_MODE=$([ -n "$MODE_FLAG" ] && echo dry || echo live)
MODE_MARK="$JOURNAL/mode.txt"
CUR_MODE=$(cat "$MODE_MARK" 2>/dev/null || true)
# Маркер КНИГИ — тем же правилом: журнал описывает одну книгу, и
# записи другой поверх старых обессмыслили бы сопоставление с бумагой.
# Отсутствие маркера при непустом журнале означает model_sit — все
# журналы до появления маркера писаны с неё; трактовать отсутствие как
# «неизвестно» значило бы отставить живой журнал с ОТКРЫТЫМИ
# позициями на пустом месте, и сверка с биржей встала бы красной.
BOOK_MARK="$JOURNAL/book.txt"
CUR_BOOK=$(cat "$BOOK_MARK" 2>/dev/null || echo model_sit)
WANT_BOOK=$(basename "$S8")
# --- решение об архиве журнала ---------------------------------------
if { [ "$CUR_MODE" != "$WANT_MODE" ] || [ "$CUR_BOOK" != "$WANT_BOOK" ]; } \
        && ls "$JOURNAL"/journal-*.jsonl* >/dev/null 2>&1; then
    # Журнал с ОТКРЫТЫМИ позициями не отставляется молча: позиции на
    # бирже остались бы без управления, без тейков и без записи —
    # инцидент 2026-08-23 (команда дошла без --book: телефонная
    # вставка переносит строку, хвост уходит отдельной командой, и
    # умолчание sit отставило журнал книги sit_lo с пятью живыми
    # позициями). Штатный перевод книги и так требует нуля позиций
    # (--no-entries, дождаться нуля) — отказ ничему законному не
    # мешает. Позиции берутся из статуса только что остановленного
    # исполнителя; нет статуса — защищать нечего. Тот же род правила,
    # что «команда публикации не вправе записывать удаления».
    OPEN_POS=$(python3 - "$JOURNAL" <<'PYG'
import json, sys
try:
    st = json.load(open(sys.argv[1] + "/live_status.json"))
    print(len(st.get("positions") or []))
except Exception:
    print(0)
PYG
)
    if [ "${OPEN_POS:-0}" -gt 0 ] && [ -z "$ARCHIVE_OPEN" ]; then
        echo "ОТКАЗ: журнал (режим «${CUR_MODE:-без маркера}», книга «$CUR_BOOK») держит $OPEN_POS откр. позиций,"
        echo "  а команда просит режим $WANT_MODE, книгу $WANT_BOOK — отставить журнал значит бросить"
        echo "  позиции без управления и записи. Либо та же книга: --book прежним значением,"
        echo "  либо штатный перевод (--no-entries, дождаться нуля позиций),"
        echo "  либо явно: --archive-with-open (позиции останутся на бирже без записи)."
        exit 1
    fi
    ARCH="${JOURNAL}-${CUR_MODE:-unmarked}-$(date -u +%Y%m%d-%H%M%S)"
    echo "== журнал писан иначе (режим «${CUR_MODE:-без маркера}», книга «$CUR_BOOK») =="
    echo "   архивирую в $ARCH и начинаю чистый (режим $WANT_MODE, книга $WANT_BOOK)"
    mv "$JOURNAL" "$ARCH" || { echo "ОШИБКА: не смог отставить журнал"; exit 1; }
    mkdir -p "$JOURNAL"
    # KILL переезжает (аварийный выключатель не снимается сменой
    # журнала); NO_ENTRIES — НЕТ: пауза входов и была процедурой
    # перевода, смена книги её завершает.
    [ -f "$ARCH/KILL" ] && cp "$ARCH/KILL" "$JOURNAL/KILL"
fi
# --- конец решения об архиве -----------------------------------------
printf '%s\n' "$WANT_MODE" > "$MODE_MARK"
printf '%s\n' "$WANT_BOOK" > "$BOOK_MARK"
if [ -n "$NO_ENTRIES" ]; then
    : > "$JOURNAL/NO_ENTRIES"
    echo "== входы ВЫКЛЮЧЕНЫ файлом NO_ENTRIES — исполнитель только сопровождает открытое =="
elif [ -f "$JOURNAL/NO_ENTRIES" ]; then
    echo "ВНИМАНИЕ: лежит $JOURNAL/NO_ENTRIES — входы выключены с прошлого запуска."
    echo "  Снять: rm $JOURNAL/NO_ENTRIES (либо перевод книги --book, он начинает чистый журнал)"
fi
# Снятый предохранитель переживает перезапуск — и обязан кричать о
# себе при каждом старте, иначе через неделю никто не вспомнит, что
# денежных пределов у замера нет.
if [ -f "$JOURNAL/LIMITS_OFF" ]; then
    echo "ВНИМАНИЕ: лежит $JOURNAL/LIMITS_OFF — ДЕНЕЖНЫЕ пределы §5 сняты"
    echo "  (день −15 \$ и итог −45 \$ не останавливают). Вернуть: tools/run_live.sh --limits-on"
fi

echo "== запускаю: $MODE_NAME, книга $WANT_BOOK =="
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
