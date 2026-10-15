#!/usr/bin/env python3
"""Сколько стоит контекст издержек и их наложение на строки книги — по
частям (спека 17 §0: «свод» 11.7 с на сервере против 1.1 с без каталога
funding). Ничего не меняет.

    run tools/costs_timing.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "research", "dca_paper"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402


def main():
    t = time.time()
    ctx = CO.context()
    t1 = time.time()
    print(f"context: {t1 - t:.2f} с; ключи {sorted(ctx)[:12]}; n_funding {ctx.get('n_funding')}; "
          f"ошибка {ctx.get('error')}")
    for k, v in ctx.items():
        try:
            n = len(v)
        except TypeError:
            n = "-"
        print(f"  {k}: {type(v).__name__} len {n}")
    t = time.time()
    rows, bad = R.read_journal(R.JOURNAL, keep=R.is_current, disk=R.JOURNAL_CACHE, keep_sig=R.current_sig())
    t2 = time.time()
    print(f"журнал (текущие, с диска): {len(rows)} строк за {t2 - t:.2f} с")
    t = time.time()
    rows2, summ = CO.apply_to_rows(rows, ctx)
    t3 = time.time()
    print(f"apply_to_rows: {t3 - t:.2f} с; applied {summ.get('applied')} из {summ.get('n')}; "
          f"no_funding {summ.get('no_funding')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
