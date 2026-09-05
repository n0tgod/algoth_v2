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

`--repack` — вторая работа того же рода: суточных кусков оказалось
мало. Одно решение живёт во ВСЕХ книгах разом (девять на 2026-09-05,
восемнадцать с зеркальными короткими), и куски 20–21 августа доросли до
4.2–4.35 МБ. Пересчёт истории после смены правил перешагнул бы 5 МиБ и
заморозил бы канал снова. Перепаковка перекладывает строки СУТОК по
частям `journal-<дата>.NN`, ни одной не теряя: строки переезжают между
файлами, число решений у читателя не меняется, и это сверяется тем же
способом, что у разрезки.
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


def repack(path=None, cap=None, log=print, apply=True):
    """Переложить строки суток по частям, не переступая порог размера.

    Работает ПО СУТКАМ и только там, где нужно: день, влезающий в одну
    часть, не трогается вовсе. Число решений у читателя — инвариант, и
    он сверяется; расхождение прерывает работу, а не докладывается.
    """
    path = path or R.JOURNAL
    cap = R.SHARD_CAP if cap is None else int(cap)
    before, _b0 = R.read_journal(path)
    base, ext = os.path.splitext(path)
    days = sorted({os.path.basename(f)[len(os.path.basename(base)) + 1:]
                   .split(".")[0]
                   for f in R.journal_parts(path) if f != path})
    moved, touched = 0, 0
    for d in days:
        parts = [f for f in R.shard_parts(path, day=d) if os.path.exists(f)]
        if not parts:
            continue
        if all(os.path.getsize(f) <= cap for f in parts):
            continue                        # день влезает — не трогаем
        lines = []
        for f in parts:
            with open(f, encoding="utf-8") as fh:
                lines += [ln for ln in fh if ln.strip()]
        # Раскладка считается на ПУСТЫХ частях: файлы этого дня будут
        # переписаны целиком, и размер на диске к решению не относится.
        place, cur, sz, n = {}, f"{base}-{d}{ext}", 0, 0
        for ln in lines:
            add = len(ln.encode("utf-8"))
            if sz and sz + add > cap:
                n += 1
                cur = f"{base}-{d}.{n:02d}{ext}"
                sz = 0
            place.setdefault(cur, []).append(ln)
            sz += add
        touched += 1
        moved += len(lines)
        log(f"  {d}: {len(lines)} строк из {len(parts)} частей → "
            f"{len(place)}")
        if not apply:
            continue
        for f in parts:                     # части дня переписываются
            if f not in place:
                open(f, "w", encoding="utf-8").close()
        for f, ls in place.items():
            tmp = f + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write("".join(ls))
            os.replace(tmp, f)
    if not apply:
        log(f"сухой прогон: тронуть {touched} суток, {moved} строк")
        return {"days": touched, "moved": moved, "applied": False}
    st = {}
    after, _b2 = R.read_journal(path, stats=st)
    ok = len(after) == len(before)
    log(f"сверка: решений было {len(before)}, читается {len(after)}"
        f", кусков {st.get('parts')} — "
        f"{'сошлось' if ok else 'РАСХОЖДЕНИЕ'}")
    if not ok:
        raise SystemExit("перепаковка изменила число решений")
    big = [f for f in R.journal_parts(path)
           if os.path.getsize(f) > cap and f != path]
    log(f"частей сверх порога осталось: {len(big)}"
        + (" — " + ", ".join(os.path.basename(f) for f in big) if big else ""))
    return {"days": touched, "moved": moved, "applied": True,
            "over_cap": len(big)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--journal", default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--repack", action="store_true",
                    help="переложить части суток по размеру")
    a = ap.parse_args()
    if a.repack:
        repack(a.journal, apply=not a.dry)
    else:
        split(a.journal, apply=not a.dry)


if __name__ == "__main__":
    main()
