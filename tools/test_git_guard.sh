#!/usr/bin/env bash
# Охрана git (20.10): мёртвый замок индекса (старше предела, живого git нет)
# снимается, свежий — нет; живой большой файл, который сведение вернуло к
# старой git-копии, возвращается из копии; маленький не трогается.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
tmp=$(mktemp -d /tmp/gg-XXXXXX)
trap 'rm -rf "$tmp"' EXIT
fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  ПАДЕНИЕ $1"; fail=1; fi; }
cd "$tmp" && git init -q . && git config user.email t@t && git config user.name t
mkdir -p research/x/out
head -c 2000 /dev/zero > research/x/out/big.json; echo small > research/x/out/small.json
git add -A >/dev/null && git commit -qm init
. "$here/git_guard.sh"
GIT_BIG_BYTES=1000
# живая версия большого файла отличается от git
head -c 3000 /dev/urandom > research/x/out/big.json; cp research/x/out/big.json live.bin
echo changed > research/x/out/small.json
big_save
check "сохранён только большой файл" '[ -f "$GIT_BIG_KEEP/research/x/out/big.json" ] && [ ! -f "$GIT_BIG_KEEP/research/x/out/small.json" ]'
git checkout -q -- research/x/out/big.json         # «сведение» откатило к git-копии
check "подделка легла: на диске git-копия" '! cmp -s live.bin research/x/out/big.json'
out="$(big_restore)"
check "живой возвращён" 'cmp -s live.bin research/x/out/big.json'
check "возврат назван словами" 'echo "$out" | grep -q "возвращён после сведения"'
# замок индекса
touch .git/index.lock
stale_lock_clear >/dev/null
check "свежий замок не снят" '[ -f .git/index.lock ]'
touch -d "@$(( $(date +%s) - 3600 ))" .git/index.lock
msg="$(stale_lock_clear)"
check "мёртвый замок снят" '[ ! -f .git/index.lock ]'
check "снятие названо словами" 'echo "$msg" | grep -q "снят мёртвый замок"'
# битый след сведения: без head-name и на ветке — снимается; с head-name — нет
mkdir -p .git/rebase-merge
msg2="$(broken_rebase_clear)"
check "битый след сведения снят" '[ ! -d .git/rebase-merge ]'
check "снятие следа названо словами" 'echo "$msg2" | grep -q "битый след"'
mkdir -p .git/rebase-merge && echo refs/heads/main > .git/rebase-merge/head-name
broken_rebase_clear >/dev/null
check "след с head-name не трогается" '[ -f .git/rebase-merge/head-name ]'
rm -rf .git/rebase-merge
if [ "$fail" -ne 0 ]; then echo "есть падения"; exit 1; fi
echo "все проверки охраны git прошли"
