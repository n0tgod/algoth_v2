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


def legs_index(log=print):
    """Обещание модели по ключу решения — из ТОГО ЖЕ списка ног."""
    out = {}
    for g in D6.gated_legs(log=log):
        try:
            out[(g["sym"], round(float(g["at"]), 3))] = float(g["fav"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def shards():
    """Все куски журнала плюс цельный файл прежнего хранения."""
    import glob
    base, ext = os.path.splitext(R.JOURNAL)
    got = sorted(glob.glob(f"{base}-*{ext}"))
    if os.path.exists(R.JOURNAL):
        got.append(R.JOURNAL)
    return got


def patch_file(path, idx, write=False):
    """Дописать поле в один кусок. Возвращает (строк, тронуто, без ноги)."""
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
            v = idx.get((r.get("sym"), round(float(r.get("at") or 0), 3)))
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
    # Сверка: кроме двух добавленных полей не сдвинулось НИЧЕГО.
    for a, b in zip(src, out):
        if a == b:
            continue
        ra, rb = json.loads(a), json.loads(b)
        add = set(rb) - set(ra)
        if add != {"fav_bp", "fav_from"} or any(
                ra[k] != rb[k] for k in ra):
            raise SystemExit(f"{path}: строка изменилась не только полем "
                             f"обещания: {sorted(add)}")
    if write and touched:
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
    print(f"ног в индексе {len(idx)}")
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
