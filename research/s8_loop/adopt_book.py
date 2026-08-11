#!/usr/bin/env python3
"""Перенести историю одной книги в другую — когда это ТА ЖЕ книга.

Зачем это нужно
---------------

Решением владельца главная книга (4 ч) перешла на порядок сечения в
единицах σ. Смена порядка отставляет прежнюю книгу в архив — она
торговала другим правилом, и дописывать к ней новые сделки значит
получить кривую, описывающую то одну книгу, то другую.

Но книга, которой главная СТАЛА, уже существовала: `model_z` — та же
сечение, тот же горизонт 4 ч, та же геометрия сделки, порядок в σ.
Она заводилась ровно затем, чтобы этот порядок измерить, и её сделки
и есть накопленная история той книги, которую главная ведёт теперь.
Начинать с нуля значило бы выбросить запись, к которой ничего не
предъявлено, — а непрерывность трека и есть то немногое, что у стенда
уже накоплено.

Чего этот инструмент НЕ делает
------------------------------

Он не считает деньги. Счета — чистая функция от выборов и разборов,
их пересобирает сам цикл (`rebuild_accounts`) по всей истории разом,
и после переноса вся кривая посчитается ОДНИМ действующим правилом
кассы. Второй копии расчётного ядра здесь нет и быть не должно.

Он ничего не удаляет: источник остаётся на диске, в нём появляется
пометка `adopted_into.txt`.

Условие законности переноса — одно: у обеих книг один и тот же
порядок сечения. Записи выбора несут его полем `rank_want`; записи,
сделанные до появления поля, помечаются значением `--rank`, и это не
догадка — источник ничем другим не упорядочивался никогда, о чём
говорит его собственный манифест. Запись, ЯВНО несущая другой
порядок, останавливает перенос: смесь двух правил в одной книге — то,
от чего архив и защищает.

    python3 research/s8_loop/adopt_book.py \\
        --from research/s8_loop/out/model_z \\
        --into research/s8_loop/out/model \\
        --rank fwd_4h_z --seq-from research/s8_loop/out/model.rank-raw
"""
import argparse
import json
import os
import sys


def read_jsonl(path):
    """Строки jsonl; битая строка пропускается, нет файла — пусто."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def key_of(rec):
    """Ключ записи книги — (рука, час), как у `write_pick`."""
    return ((rec.get("arm") or "gbm"), rec.get("hour"))


def stamp(rec, rank):
    """Проставить порядок сечения записи, сделанной до появления поля.

    Значение НЕ перебивается: запись, уже несущая порядок, говорит
    сама за себя, и переписать её значило бы стереть свидетельство.
    """
    out = dict(rec)
    if "rank_want" not in out:
        out["rank_want"] = rank
    if "rank_by" not in out:
        out["rank_by"] = rank
    return out


def conflicting(recs, rank):
    """Записи, ЯВНО упорядоченные иначе, — перенос на них останавливается."""
    return [r for r in recs
            if "rank_want" in r and r["rank_want"] != rank]


def merge(src, dst, rank):
    """Слить записи источника в цель: дубли цели побеждают, порядок — по часу.

    Час — сортируемая строка (`2026-08-11-19`), и хронология
    восстанавливается ей же. Порядок внутри часа существен: касса
    раздаёт деньги в порядке входного списка при равной секунде,
    поэтому записи одного часа сохраняют свой порядок (сортировка
    устойчива).
    """
    have = {key_of(r) for r in dst}
    add = [stamp(r, rank) for r in src if key_of(r) not in have]
    rows = add + list(dst)
    rows.sort(key=lambda r: (r.get("hour") or ""))
    return rows, len(add), len(src) - len(add)


def write_rows(path, rows):
    """Записать книгу целиком, оставив прежнюю версию рядом."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            was = f.read()
        with open(path + ".before-adopt", "w", encoding="utf-8") as f:
            f.write(was)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(path + ".tmp", path)


def carry_seq(seq_from, into, log=print):
    """Продолжить нумерацию обучений, а не начать её заново.

    Счётчик живёт в манифесте модели и растёт на единицу за цикл.
    Каталог модели уехал в архив вместе с книгой, и цикл начал считать
    с нуля — а записи сделок ссылаются на прежние номера. Два обучения
    под одним номером есть молчаливая ложь в объяснении сделки.
    """
    try:
        with open(os.path.join(seq_from, "manifest.json"),
                  encoding="utf-8") as f:
            was = int((json.load(f) or {}).get("train_seq") or 0)
    except (OSError, ValueError):
        log("  счётчик обучений в архиве не найден — оставляю как есть")
        return None
    mp = os.path.join(into, "manifest.json")
    try:
        with open(mp, encoding="utf-8") as f:
            man = json.load(f) or {}
    except (OSError, ValueError):
        log("  манифеста модели нет — счётчик перенести некуда")
        return None
    now = int(man.get("train_seq") or 0)
    if was <= now:
        log(f"  счётчик обучений уже не меньше архивного ({now} ≥ {was})")
        return None
    man["train_seq"] = was
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    os.replace(mp + ".tmp", mp)
    log(f"  нумерация обучений продолжена: {now} → {was}")
    return was


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--into", dest="dst", required=True)
    ap.add_argument("--rank", required=True,
                    help="порядок сечения, которым обе книги упорядочены")
    ap.add_argument("--seq-from", dest="seq",
                    help="каталог с манифестом, откуда продолжить "
                         "нумерацию обучений")
    a = ap.parse_args(argv)

    if not os.path.isdir(a.src):
        print(f"ОШИБКА: нет каталога источника {a.src}")
        return 1
    os.makedirs(a.dst, exist_ok=True)

    took = {}
    for name in ("picks.jsonl", "review.jsonl"):
        src = read_jsonl(os.path.join(a.src, name))
        dst = read_jsonl(os.path.join(a.dst, name))
        bad = conflicting(src, a.rank) if name == "picks.jsonl" else []
        if bad:
            print(f"ОСТАНОВЛЕНО: в источнике {len(bad)} записей другого "
                  f"порядка (например {bad[0].get('rank_want')!r} при "
                  f"ожидаемом {a.rank!r}) — это другая книга")
            return 2
        rows, added, dup = merge(src, dst, a.rank)
        if added:
            write_rows(os.path.join(a.dst, name), rows)
        took[name] = (added, dup, len(rows))
        print(f"  {name}: перенесено {added}, дублей пропущено {dup}, "
              f"итого в книге {len(rows)}")

    if a.seq:
        carry_seq(a.seq, a.dst)

    # Пометка в источнике: он остаётся на диске, и без неё через месяц
    # нельзя будет сказать, была ли его история уже перенесена.
    try:
        with open(os.path.join(a.src, "adopted_into.txt"), "a",
                  encoding="utf-8") as f:
            f.write(os.path.abspath(a.dst) + "\n")
    except OSError:
        pass

    print("== перенос закончен ==")
    print("Счета пересоберутся сами ближайшим циклом: они чистая "
          "функция от выборов и разборов.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
