#!/usr/bin/env bash
# Хук PreToolUse Claude Code (graphify, 21.10): перед Bash/Grep/Read/Glob
# подсказывает модели спросить граф (`graphify query`) вместо чтения файлов.
# Только подсказка (exit 0): graphify не установлен или графа нет — молчит,
# чтобы хук не шумел ошибкой на каждом вызове инструмента в чистой песочнице.
export PATH="$HOME/.local/bin:$PATH"
command -v graphify >/dev/null 2>&1 || exit 0
[ -f graphify-out/graph.json ] || exit 0
exec graphify hook-guard "${1:-search}"
