#!/usr/bin/env python3
"""Добор обещания модели (`fav_bp`) в уже записанные строки журнала.

Зачем. Уровень цели у книги ступенчат и выводится ПРАВИЛОМ из обещания
модели; поле `fav_bp` появилось позже самих строк, и у записей нынешней
версии правил его нет. Без него график не рисует цель вовсе — и это
правильно (рисовать уровень, которого мы не знаем, значит утверждать
чужое число), но означает, что почти вся запись осталась бы без линии,
пока книга не обернётся.

Почему это не нарушает write-ahead. Правило запрещает ПЕРЕПИСЫВАТЬ
запись: иначе момент записи можно было бы подвинуть, и «записано
вперёд» перестало бы что-то значить. Здесь не меняется ни `written_at`,
ни деньги, ни исход, ни состав — дописывается ОДНО производное поле, и
источник у него тот же, которым считает реплей (журнал листов сечения),
а не восстановление по исходу. Каждая тронутая строка помечается
`fav_from: "legs"`, чтобы добор было видно в самой записи.

Проверка встроена и прогон падает, если она не сошлась: число строк
обязано совпасть до и после, а каждая строка — совпасть со своей
прежней ВО ВСЕХ полях, кроме двух добавленных. Иначе это была бы
перезапись под видом добора.

Журналы — все три (длинных книг, коротких `h24`, общего счёта `pair`):
2026-09-22 все короткие строки общего счёта стояли с `fav_bp: null` —
кэш коротких записей писался ДО добора обещания. Ключ индекса несёт
СТОРОНУ: одно имя в один час может стоять и в длинном листе, и в
коротком, с разным обещанием, и брать обещание чужой стороны значило бы
рисовать чужую цель.

Прогон: `run research/dca_paper/backfill_fav.py` (по умолчанию сухой,
`--write` пишет).
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_d6 as D6                                           # noqa: E402
import run_short as S                                         # noqa: E402

JOURNALS = (R.JOURNAL, R.H24_JOURNAL, R.PAIR_JOURNAL)


def legs_index(log=print):
    """Обещание модели по ключу решения (сторона, имя, момент) — из ТЕХ ЖЕ
    списков ног, что кормят реплей: длинные — листы ситуационной книги
    (`run_d6`), короткие — выборы `h24` обеих рук (`run_short`)."""
    out = {}
    for g in D6.gated_legs(log=log):
        if (g.get("side") or "long") != "long":
            continue
        try:
            out[("long", g["sym"], round(float(g["at"]), 3))] = float(g["fav"])
        except (KeyError, TypeError, ValueError):
            continue
    for g in S.legs(log=log):
        try:
            out[("short", g["sym"], round(float(g["at"]), 3))] = float(g["fav"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def shards(journals=JOURNALS):
    """Все куски каждого журнала — тем же читателем, что их читает книга."""
    got = []
    for j in journals:
        got.extend(R.journal_parts(j))
    return got


def _sig(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def _unchanged(path, sig):
    """Кусок не менялся с момента чтения — иначе писать его нельзя."""
    return _sig(path) == sig


def patch_file(path, idx, write=False):
    """Дописать поле в один кусок. Возвращает (строк, тронуто, без ноги).

    Кусок сегодняшнего дня в тот же час ДОПИСЫВАЕТ прогон книги; переписать
    его поверх свежей строки значило бы потерять запись write-ahead. Поэтому
    перед записью кусок сверяется с тем, каким был прочитан: изменился —
    не пишется вовсе, и это сказано вслух (повтор идемпотентен).
    """
    sig = _sig(path)
    src = open(path, encoding="utf-8").read().splitlines()
    out, touched, miss = [], 0, 0
    for ln in src:
        if not ln.strip():
            out.append(ln)
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            out.append(ln)                 # битую строку не трогаем вовсе
            continue
        if (R.is_current(r)
                and r.get("fav_bp") is None):
            # сторона — одним правилом на всех читателей записи
            v = idx.get((R.row_side(r), r.get("sym"),
                         round(float(r.get("at") or 0), 3)))
            if v is None:
                miss += 1
            else:
                r["fav_bp"] = v
                r["fav_from"] = "legs"
                touched += 1
                out.append(json.dumps(r, ensure_ascii=False))
                continue
        out.append(ln)
    if len(out) != len(src):
        raise SystemExit(f"{path}: строк стало {len(out)} против {len(src)}")
    # Сверка: кроме двух полей обещания не сдвинулось НИЧЕГО, и оба они
    # до добора были пусты (поля не было или стояло `null` — так пишет
    # строку общий счёт).
    for a, b in zip(src, out):
        if a == b:
            continue
        ra, rb = json.loads(a), json.loads(b)
        changed = {k for k in set(ra) | set(rb) if ra.get(k) != rb.get(k)}
        if (changed != {"fav_bp", "fav_from"} or ra.get("fav_bp") is not None
                or "fav_from" in ra):
            raise SystemExit(f"{path}: строка изменилась не только полем "
                             f"обещания: {sorted(changed)}")
    if write and touched:
        if not _unchanged(path, sig):
            print(f"  {os.path.basename(path)}: изменился во время добора — "
                  "НЕ записан, повторить прогон")
            return len(src), 0, miss
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        os.replace(tmp, path)
    return len(src), touched, miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    idx = legs_index()
    print(f"ног в индексе {len(idx)}: длинных "
          f"{sum(1 for k in idx if k[0] == 'long')}, коротких "
          f"{sum(1 for k in idx if k[0] == 'short')}")
    tot = tou = mis = 0
    for p in shards():
        n, t, m = patch_file(p, idx, write=a.write)
        tot += n
        tou += t
        mis += m
        if t or m:
            print(f"  {os.path.basename(p)}: строк {n}, дописано {t}, "
                  f"ноги нет {m}")
    print(f"итого строк {tot}, дописано {tou}, обещание не найдено {mis}"
          + ("" if a.write else "  (СУХОЙ прогон, ничего не записано)"))


if __name__ == "__main__":
    main()
