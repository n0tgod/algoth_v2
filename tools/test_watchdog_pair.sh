#!/usr/bin/env bash
# Проверка правила сторожа: общий счёт считается ПОСЛЕ книг-источников.
#
# Берётся сам код сторожа (функции `computed_ts` и `pair_due` вырезаются
# из `watchdog_book.sh`), а не его копия: копия правила однажды разошлась
# бы с правилом. Файлы подставные, во временном каталоге.
#
#     bash tools/test_watchdog_pair.sh
set -u
cd "$(dirname "$0")/.."
tmp=$(mktemp -d /tmp/wdpair-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
sed -n '/^computed_ts() {/,/^}/p; /^pair_due() {/,/^}/p' tools/watchdog_book.sh > "$tmp/fn.sh"
grep -q "pair_due" "$tmp/fn.sh" || { echo "ПАДЕНИЕ: функции сторожа не вырезались"; exit 1; }
# shellcheck disable=SC1090
. "$tmp/fn.sh"

art() { printf '{"computed_at": "%s", "books": {}}\n' "$2" > "$1"; }
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }

P=$tmp/pair.json; S=$tmp/short.json; L=$tmp/paper.json
art "$P" "2026-09-23 12:10"; art "$S" "2026-09-23 12:26"; art "$L" "2026-09-23 12:27"
check "оба источника новее — общий счёт должен" 'pair_due "$P" "$S" "$L"'
check "метка читается секундами" '[ "$(computed_ts "$P")" -eq $(date -u -d "2026-09-23 12:10 UTC" +%s) ]'

art "$S" "2026-09-23 11:21"
check "короткие старее общего — ждать (контроль: случай 23.09 12:10)" '! pair_due "$P" "$S" "$L"'

art "$S" "2026-09-23 12:26"; art "$L" "2026-09-23 11:22"
check "длинные старее общего — ждать" '! pair_due "$P" "$S" "$L"'

art "$L" "2026-09-23 12:27"; rm -f "$P"
check "общего счёта ещё нет, источники есть — должен (первый прогон)" 'pair_due "$P" "$S" "$L"'

art "$P" "2026-09-23 12:10"; rm -f "$S"
check "источника нет — ждать, а не считать по пустому" '! pair_due "$P" "$S" "$L"'

art "$S" "2026-09-23 12:26"; printf 'не json\n' > "$P"
check "битая метка общего читается нулём — должен" '[ "$(computed_ts "$P")" -eq 0 ] && pair_due "$P" "$S" "$L"'

# Контроль сверх правила: подмена «оба новее» на «хотя бы один новее»
# обязана уронить проверку «длинные старее — ждать».
art "$P" "2026-09-23 12:10"; art "$S" "2026-09-23 12:26"; art "$L" "2026-09-23 11:22"
pair_due() { local p s l; p=$(computed_ts "$1"); s=$(computed_ts "$2"); l=$(computed_ts "$3"); [ "$s" -gt "$p" ] || [ "$l" -gt "$p" ]; }
check "подставное правило «хотя бы один» кусается (контроль)" 'pair_due "$P" "$S" "$L"'

if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки сторожа прошли"
