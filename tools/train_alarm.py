#!/usr/bin/env python3
"""Тревога «обучение S8 стоит» — сторожу, `status` и журналу «нужно от вас».

Повод. Обучение не шло с 30.09 05:27 по 04.10 21:46 — 109 часов при
каденции 24. Цикл был жив (pgrep), каждый час честно писал «обучение
отложено по памяти» в `train.log`, книги считались на старых весах,
страницы были исправны — отказ, неотличимый от исправности. Правило
одно, в `research/s8_loop/stall.py`: веса старше порога — тревога.

Что делает. Читает манифест весов и исход последнего цикла; при
тревоге печатает строку сторожу (каждый такт, пока стоит) и пишет
просьбу владельцу в журнал «нужно от вас» — один раз на эпизод (ключ
просьбы несёт время последнего обучения). Ниже порога молчит; с
`--print` печатает строку состояния всегда — так её видит `status`.

    .venv/bin/python tools/train_alarm.py          # из сторожа
    .venv/bin/python tools/train_alarm.py --print  # из задания status
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import stall as ST  # noqa: E402

MODEL_DIR = os.path.join(ROOT, "research", "s8_loop", "out", "model")
ASKS_OUT = os.path.join(ROOT, "research", "factory", "out")


def check(mdir=MODEL_DIR, asks_out=ASKS_OUT, now=None, log=print, always=False):
    """Состояние обучения; при тревоге — строка и просьба (один раз)."""
    import asks as A
    now = now or time.time()
    man, lr = ST.read_state(mdir)
    st = ST.stall_of(man, lr, now)
    ln = ST.line(st)
    if st["stalled"]:
        at = (st["trained_at"] or "")[:16].replace("T", " ")
        what = (f"Обучение S8 стоит: веса от {at} UTC, порог тревоги "
                f"{st['threshold_h']} ч")
        why = (f"Весам {st['age_h']} ч при каденции {st['cadence_h']} ч; "
               f"последний цикл {(st['last_at'] or '')[11:16]} UTC: "
               f"{st['last_why'] or 'причина не записана'}. Книги S8 "
               "считаются на старых весах. Смотреть память: `run "
               "tools/memtop.py`; сторож перезапускает сборщик по потолку "
               "RSS сам. Решения владельца, которые ждут: своп на корне "
               "(`run tools/swap_on.py --size-gb 4 --apply --persist`) или "
               "замок обучения, на время которого сторож не поднимает "
               "прогоны книг.")
        n = A.record(asks_out, [{"what": what, "why": why,
                                 "unblocks": "обучение S8 и свежесть весов книг"}],
                     src="сторож обучения")
        log(ln + (" — просьба записана" if n else " — просьба уже стоит"))
    elif always or not st["measured"]:
        log(ln)
    return st


def main(argv=None, mdir=MODEL_DIR, asks_out=ASKS_OUT):
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="always", action="store_true",
                    help="печатать строку состояния и без тревоги")
    a = ap.parse_args(argv)
    st = check(mdir=mdir, asks_out=asks_out, always=a.always)
    return 1 if st["stalled"] else 0


if __name__ == "__main__":
    sys.exit(main())
