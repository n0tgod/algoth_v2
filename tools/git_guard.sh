#!/usr/bin/env bash
# Охрана git на сервере (20.10): подключается `publish.sh` и `jobs.sh`.
#
# 1. Зависший замок индекса. git, убитый посреди работы (OOM, kill),
#    оставляет `.git/index.lock`, и с этой секунды падает КАЖДАЯ операция
#    с индексом: публикация, очередь заданий, сведение веток. 20.10 после
#    23:30 по Вене так встало всё, и снаружи это неотличимо от тишины.
#    Замок старше `GIT_LOCK_STALE_S` при отсутствии живого процесса git —
#    мёртвый: убирается, и это говорится словами.
# 2. Файлы больше 5 МБ в git не публикуются (`publish.sh`), их git-копия
#    стареет. `git pull --rebase --autostash` прячет живую версию в
#    stash, и если вернуть её не удалось, на диске остаётся СТАРАЯ копия
#    из git. 20.10 так общий счёт откатился к версии 16.10 с ошибкой
#    «правила реплея изменились», и все Both исчезли из приложения.
#    Живые большие файлы копируются в сторону ДО сведения и
#    возвращаются ПОСЛЕ — чем бы оно ни кончилось.
GIT_LOCK_STALE_S=${GIT_LOCK_STALE_S:-600}
GIT_BIG_BYTES=${GIT_BIG_BYTES:-5242880}

stale_lock_clear() {
    local lk=.git/index.lock
    [ -f "$lk" ] || return 0
    local age=$(( $(date +%s) - $(stat -c %Y "$lk" 2>/dev/null || date +%s) ))
    if [ "$age" -gt "$GIT_LOCK_STALE_S" ] && ! pgrep -x git >/dev/null 2>&1; then
        rm -f "$lk"
        echo "$(date -u +%FT%TZ) · git: снят мёртвый замок индекса (${age} с, живого git нет)"
        return 0
    fi
    return 0
}

big_save() {
    # → каталог с копиями в GIT_BIG_KEEP (пусто — копировать нечего)
    GIT_BIG_KEEP=""
    local f sz
    while IFS= read -r f; do
        [ -n "$f" ] && [ -f "$f" ] || continue
        sz="$(stat -c %s "$f" 2>/dev/null || echo 0)"
        [ "$sz" -gt "$GIT_BIG_BYTES" ] || continue
        [ -n "$GIT_BIG_KEEP" ] || GIT_BIG_KEEP="$(mktemp -d "${TMPDIR:-/tmp}/git-big-XXXXXX")"
        mkdir -p "$GIT_BIG_KEEP/$(dirname "$f")"
        cp -p "$f" "$GIT_BIG_KEEP/$f"
    done < <(git diff --name-only -- 'research/*/out/*' 2>/dev/null; \
             git diff --cached --name-only -- 'research/*/out/*' 2>/dev/null)
    return 0
}

big_restore() {
    [ -n "${GIT_BIG_KEEP:-}" ] && [ -d "$GIT_BIG_KEEP" ] || return 0
    local f
    while IFS= read -r f; do
        f="${f#"$GIT_BIG_KEEP"/}"
        if ! cmp -s "$GIT_BIG_KEEP/$f" "$f" 2>/dev/null; then
            mkdir -p "$(dirname "$f")"
            cp -p "$GIT_BIG_KEEP/$f" "$f"
            echo "$(date -u +%FT%TZ) · git: живой большой файл возвращён после сведения: $f"
        fi
    done < <(find "$GIT_BIG_KEEP" -type f)
    rm -rf "$GIT_BIG_KEEP"
    GIT_BIG_KEEP=""
    return 0
}
