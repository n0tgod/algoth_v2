"""Перенос записи ветви 2 % (спека 18 §3, решение владельца 2026-10-16).

Ветвь `_g2` есть возврат правила, которое стояло до 16.10: охрана рынком
2 %. Строки версии h24 5 / pair 11 (с 15.10 до снятия охраны) писались
ровно её правилами, поэтому они переносятся в её запись КОПИЕЙ под
ключом сестры и текущей версией семейства; `written_at` сохраняется —
«вперёд» остаётся «вперёд», пересчёт пересчётом. Исходные строки не
трогаются (журнал write-ahead), повтор запуска ничего не добавляет
(дедуп по ключу решения). У общего счёта метка `book` короткой стороны
тоже переводится на ключ сестры: по ней читатели делят стороны.

    run tools/branch_inherit.py            # перенос
    run tools/branch_inherit.py --dry      # только посчитать
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "research", "dca_paper"))
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402

def inherit(path, family, old_ver, log=print, dry=False, value=2.0):
    """Обёртка над ядром `run_paper.inherit_branch` — одно место переноса."""
    return RP.inherit_branch(path, family, old_ver, value, log=log, dry=dry)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    res = {}
    for fam, path in (("h24", R.H24_JOURNAL), ("pair", R.PAIR_JOURNAL)):
        spec = R.BRANCH_INHERIT[fam]
        res[fam] = inherit(path, fam, spec["from_version"], dry=a.dry, value=spec["to"])
    print("итог:", {k: {"added": v.get("added"), "would": v.get("would")} for k, v in res.items()})


if __name__ == "__main__":
    main()
