#!/usr/bin/env bash
# Опубликовать артефакты прогона: отчёты и сводки — в git.
#
# Правило проекта: прогон идёт на сервере, а обсуждается в другом
# месте. Пересказывать консоль скриншотами значит терять числа и время,
# поэтому каждый этап пишет отчёт файлом, а эта команда его публикует.
#
# Что уходит и что нет, решают правила `.gitignore` этапов: отчёты и
# манифесты идут, ряды и журналы — нет. Здесь никакой отдельной логики
# отбора: два места, решающих одно и то же, однажды разойдутся.
#
#     tools/publish.sh "L2: проверка площадки исполнения"

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
msg="${1:-артефакты прогона}"
branch="$(git rev-parse --abbrev-ref HEAD)"

git add -A research/*/out docs 2>/dev/null || true

if git diff --cached --quiet; then
  echo "нечего публиковать — артефакты не изменились"
  exit 0
fi

echo "публикуется в ветку $branch:"
git diff --cached --stat

git commit -q -m "$msg"

# Повторы только на сетевых сбоях, с растущей паузой.
for attempt in 1 2 3 4; do
  if git push -u origin "$branch"; then
    echo "опубликовано"
    exit 0
  fi
  delay=$((2 ** attempt))
  echo "push не прошёл, повтор через ${delay} с (попытка $attempt из 4)"
  sleep "$delay"
done

echo "push не прошёл после четырёх попыток — коммит на месте, "
echo "повторить можно командой: git push -u origin $branch"
exit 1
