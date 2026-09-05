#!/usr/bin/env python3
"""Разрезать цельный журнал книги на суточные куски.

Зачем. Журнал рос одним файлом и 4 сентября перевалил 11 МБ — защита
от опасного коммита (`tools/safety_check.sh`, порог 5 МБ) стала
отказывать на КАЖДОЙ публикации, и с 12:10 в git не доехало ничего:
ни логов заданий, ни ночного отчёта турнира, ни артефактов кандидатов.
Защита сработала верно; молчал канал. Ротация убирает класс: суточный
кусок — доли мегабайта при ~320 решениях в день.

Что делает. Читает ТОЛЬКО старый цельный файл (`out/journal.jsonl`),
раскладывает строки по дате решения (`at`, UTC) в `journal-ГГГГ-ММ-ДД`
и печатает сверку: сумма строк кусков обязана совпасть с числом
прочитанных. Уже лежащие в кусках решения не дублируются — ключ тот
же, которым дедуплицирует запись.

Чего НЕ делает. Не удаляет и не укорачивает оригинал: удаление записи
есть осознанное действие, а не побочный эффект правки. Дедуп на чтении
(`rules.read_journal`) снимает перекрытие, поэтому числа книг после
разрезки не меняются — это проверяется прогоном и тестом.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import rules as R  # noqa: E402


def read_one(path):
    """Строки ОДНОГО файла: разрезка не должна читать свои же куски."""
    rows, bad = [], 0
    if not os.path.exists(path):
        return rows, bad
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:
                bad += 1
    return rows, bad


def split(path=None, log=print, apply=True):
    path = path or R.JOURNAL
    # Сколько решений видит ЧИТАТЕЛЬ до разрезки — это и есть величина,
    # которую разрезка не вправе изменить. Сравнивать с числом строк
    # одного лишь оригинала нельзя: куски могли уже нести решения,
    # которых в оригинале нет.
    before, _bad0 = R.read_journal(path)
    rows, bad = read_one(path)
    if not rows:
        log(f"разрезать нечего: {path} пуст или отсутствует")
        return {"read": 0, "written": 0, "shards": 0, "bad": bad}
    # что уже лежит в суточных кусках — тем же ключом, что у записи
    base, ext = os.path.splitext(path)
    have = set()
    for part in R.journal_parts(path):
        if part == path:
            continue
        for r in read_one(part)[0]:
            have.add(R.journal_key(r))
    by = {}
    for r in rows:
        if R.journal_key(r) in have:
            continue
        by.setdefault(R.shard_of(path, r.get("at")), []).append(r)
    n = sum(len(v) for v in by.values())
    log(f"прочитано {len(rows)} строк"
        + (f", битых {bad}" if bad else "")
        + f"; уже в кусках {len(rows) - n}; разложить {n} "
          f"по {len(by)} суточным файлам")
    if not apply:
        log("сухой прогон: ничего не записано")
        return {"read": len(rows), "written": 0, "shards": len(by),
                "bad": bad}
    for sh in sorted(by):
        with open(sh, "a", encoding="utf-8") as f:
            for r in by[sh]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        log(f"  {os.path.basename(sh)}: +{len(by[sh])} "
            f"({os.path.getsize(sh) / 1048576:.2f} МБ)")
    # СВЕРКА: после разрезки читатель обязан вернуть то же число
    # решений, что и до неё. Разрезка, меняющая числа книг, есть не
    # экономия, а другая запись.
    st = {}
    after, _bad2 = R.read_journal(path, stats=st)
    ok = len(after) == len(before)
    log(f"сверка: решений было {len(before)}, читается {len(after)}"
        f", повторов снято {st.get('dups')}, кусков {st.get('parts')}"
        f" — {'сошлось' if ok else 'РАСХОЖДЕНИЕ'}")
    if not ok:
        raise SystemExit("разрезка изменила число решений — не применяю")
    log("оригинал НЕ тронут: удаление записи — отдельное решение "
        "владельца (ALLOW_DELETE=1)")
    return {"read": len(rows), "written": n, "shards": len(by), "bad": bad}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--journal", default=None)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    split(a.journal, apply=not a.dry)


if __name__ == "__main__":
    main()
