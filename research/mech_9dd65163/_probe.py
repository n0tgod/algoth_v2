#!/usr/bin/env python3
"""Черновик постройки: есть ли на машине то, без чего потолок не считается.

Печатает три числа — записей в кэше реплея коротких книг, рядов funding и
активов справочника, — и больше ничего. Нужен перед заданием очереди:
«кэша нет» и «кэш пуст» снаружи неотличимы, а лечатся разным.

Сам замер живёт в `funding_margin.py`; формул здесь нет и быть не должно.

    .venv/bin/python research/mech_9dd65163/_probe.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import funding_margin as FM                                   # noqa: E402


def main():
    cache, why = FM.S.read_cache(log=print)
    closed = sum(1 for r in cache.values()
                 if (r.get("state") or "closed") == "closed")
    ctx = FM.CO.context()
    print(f"кэш реплея: записей {len(cache)}, закрытых {closed}"
          + (f"; НЕПРИГОДЕН: {why}" if why else ""))
    print(f"ряды funding: {len(ctx.get('funding') or {})}"
          + (f"; ошибка контекста: {ctx['error']}" if ctx.get("error") else ""))
    return 0 if (closed and (ctx.get("funding") or {})) else 2


if __name__ == "__main__":
    sys.exit(main())
