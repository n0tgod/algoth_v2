#!/usr/bin/env python3
"""Тревога по заполнению дисков — ДО того, как умрёт сборщик.

Повод. 24.09 том записи заполнился на 100 %, сборщик умер в 00:36 и
12 часов ничто этого не называло: сторож поднимал его каждые 5 минут,
тот умирал снова, страницы стояли. Память проекта предупреждала
6 сентября «вопрос диска вернётся» — но предупреждение в прозе не
тревога.

Что делает. Смотрит заполнение тома записи и корня; при `--pct` и выше
(умолчание 90) пишет просьбу владельцу в журнал «нужно от вас»
(`research/factory/asks.py`, страница `/asks-page`) — один раз на месяц и
порог (ключ просьбы — её текст), и печатает строку сторожу. Ниже
порога — молчит. Просьба закрывается словом владельца или сама, когда
том снова ниже порога — это проверка `check` не умеет (файла нет),
поэтому состояние — по слову.

    .venv/bin/python tools/disk_alarm.py            # из сторожа
    .venv/bin/python tools/disk_alarm.py --pct 80   # проба
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))

RECORD = os.path.join(ROOT, "research", "b1_book", "out")
ASKS_OUT = os.path.join(ROOT, "research", "factory", "out")
PCT = 90


def usage(path, statvfs=os.statvfs):
    """Заполнение диска под путём в процентах и свободные ГБ."""
    st = statvfs(path)
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    if total <= 0:
        return None, None
    return 100.0 * (1 - free / total), free / 2**30


def check(paths, pct=PCT, asks_out=ASKS_OUT, statvfs=os.statvfs, now=None,
          log=print):
    """Возвращает список путей над порогом; просьба пишется один раз."""
    import asks as A
    now = now or time.time()
    month = time.strftime("%Y-%m", time.gmtime(now))
    over = []
    for name, p in paths:
        try:
            u, free = usage(p, statvfs)
        except OSError as e:
            log(f"диск {name}: df не читается ({e})")
            continue
        if u is None:
            continue
        if u >= pct:
            over.append((name, p, u, free))
            what = (f"Диск «{name}» заполнен на {pct} % и больше ({month}) — "
                    "нужно место под запись")
            why = (f"{p}: занято {u:.0f} %, свободно {free:.1f} ГБ. Запись "
                   "стакана растёт на ≈ 4 ГБ в сутки; на полном диске сборщик "
                   "умирает и страницы встают (24.09 — 12 часов без записи). "
                   "Выгрузить закрытые сутки в хранилище (`tools/record_ship.py`), "
                   "снять местные копии или расширить том.")
            n = A.record(asks_out, [{"what": what, "why": why,
                                     "unblocks": "запись стакана и страницы"}],
                         src="сторож дисков")
            log(f"ТРЕВОГА диск «{name}» {p}: занято {u:.0f} %, свободно "
                f"{free:.1f} ГБ (порог {pct} %)"
                + (" — просьба записана" if n else " — просьба уже стоит"))
    return over


def main(argv=None, asks_out=ASKS_OUT, paths=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pct", type=float, default=PCT)
    a = ap.parse_args(argv)
    over = check(paths or [("том записи", RECORD), ("корень", ROOT)],
                 pct=a.pct, asks_out=asks_out)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
