#!/usr/bin/env python3
"""Разморозить публикацию: вернуть разрезанный журнал к версии git.

Зачем. Журнал DCA-книг одним файлом перерос 5 МБ, и защита от опасного
коммита стала отказывать на КАЖДОЙ публикации: с 12:10 4 сентября в git
не доехало ничего — ни логов заданий, ни ночного отчёта. После перевода
на суточную ротацию новые решения идут в куски, но сам цельный файл
остаётся изменённым относительно git, и коммит по-прежнему отвергается.

Что делает. Проверяет, что КАЖДОЕ решение из рабочей копии цельного
файла уже лежит в суточных кусках (ключ тот же, которым дедуплицирует
запись), и только тогда возвращает цельный файл к версии git. Ни одной
строки при этом не теряется: они уже в кусках, а читатель снимает
перекрытие.

Чего НЕ делает. Не трогает ничего, кроме одного этого файла, и
отказывается работать, если проверка не сошлась: молчаливое «git
checkout» по записи книги было бы ровно тем, от чего защита и стоит.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))

import rules as R  # noqa: E402
import split_journal as S  # noqa: E402

REL = "research/dca_paper/out/journal.jsonl"


def main():
    path = os.path.join(ROOT, REL)
    if not os.path.exists(path):
        print("цельного журнала нет — возвращать нечего")
        return 0
    rows, bad = S.read_one(path)
    have = set()
    for part in R.journal_parts(path):
        if part == path:
            continue
        for r in S.read_one(part)[0]:
            have.add(R.journal_key(r))
    missing = [r for r in rows if R.journal_key(r) not in have]
    size = os.path.getsize(path) / 1048576.0
    print(f"цельный журнал: {len(rows)} решений, {size:.1f} МБ"
          + (f", битых строк {bad}" if bad else ""))
    print(f"суточных кусков: {len(R.journal_parts(path)) - 1}; "
          f"решений в них {len(have)}; не покрыто {len(missing)}")
    if missing:
        print("ОТКАЗ: часть решений живёт только в цельном файле — "
              "сперва разрезка (research/dca_paper/split_journal.py)")
        return 1
    before, _ = R.read_journal(path)
    r = subprocess.run(["git", "checkout", "--", REL], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("ОТКАЗ: git checkout не прошёл: "
              + (r.stderr or r.stdout).strip()[:200])
        return 1
    after, _ = R.read_journal(path)
    print(f"после возврата: файл {os.path.getsize(path) / 1048576.0:.1f} МБ; "
          f"решений читается {len(after)} против {len(before)} до — "
          + ("сошлось" if len(after) == len(before) else "РАСХОЖДЕНИЕ"))
    return 0 if len(after) == len(before) else 1


if __name__ == "__main__":
    raise SystemExit(main())
