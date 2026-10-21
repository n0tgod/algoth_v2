#!/usr/bin/env bash
# Хук SessionStart Claude Code (graphify, 21.10; правила — .claude/CLAUDE.md).
# В новой песочнице: ставит graphify (uv), если его нет, и ОТЦЕПЛЕННО
# собирает граф кода (`graphify update` — AST, без LLM, ~2 мин; затем
# кластеры без имён, ~1 мин). Граф в git не идёт (14 МБ при минутных
# пулах сервера). Хук молчит и возвращает 0 сразу: сессия не ждёт сборки и
# не начинается с ошибки без сети; ход сборки — graphify-out/build.log,
# готовность — graphify-out/GRAPH_REPORT.md. На сервере хук не запускается.
export PATH="$HOME/.local/bin:$PATH"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 0
mkdir -p graphify-out
{
    if ! command -v graphify >/dev/null 2>&1; then
        command -v uv >/dev/null 2>&1 || { echo "uv нет — graphify не поставлен"; exit 0; }
        timeout 240 uv tool install graphifyy -q || { echo "graphify не поставлен (сеть?)"; exit 0; }
    fi
    if [ -f graphify-out/graph.json ] && [ -f graphify-out/GRAPH_REPORT.md ] \
       && [ -z "$(find . -newer graphify-out/graph.json -name '*.py' -not -path './.venv/*' -print -quit)" ]; then
        echo "граф свежее кода — не пересобираю"; exit 0
    fi
    echo "сборка графа: $(date -u +%FT%TZ)"
    timeout 900 graphify update . --force --no-cluster && timeout 600 graphify cluster-only . --no-label --no-viz
    echo "конец: $(date -u +%FT%TZ), код $?"
} > graphify-out/build.log 2>&1 </dev/null &
disown 2>/dev/null || true
exit 0
