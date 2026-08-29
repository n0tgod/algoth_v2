"""Дневная разбивка книг — числами, прямо с диска сервера.

Зачем отдельный прогон, а не «страница открылась». Страницу видит
владелец, а сессия видит только то, что доехало в git; «задеплоил» —
это утверждение, а не результат. Здесь считается ровно то, что
показывает `/book-page`: та же `Collector.book_days`, то же ядро
кассы. Разойдись они — расходились бы страница и проверка, а не
страница и правда.

Только ЧТЕНИЕ: файлы книг не трогаются вовсе.

    .venv/bin/python research/ops/book_days_probe.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "research", "b1_book"))


def main():
    import collect as C

    col = C.Collector.__new__(C.Collector)
    col.log = lambda m: None
    col._px_cache = {}
    col._jsonl_cache = {}
    print("книга          суток  сделок  побед        деньги  "
          "первый день   последний")
    for hz, name in C.Collector.BOOKS:
        try:
            d = col.book_days(hz)
        except Exception as e:                        # noqa: BLE001
            # Отказ обязан быть ВИДЕН: молчание здесь неотличимо от
            # «книга пуста», а это разные состояния.
            print(f"{hz:<14} ОТКАЗ: {type(e).__name__}: {e}")
            continue
        days = d.get("days") or []
        t = (d.get("totals") or {}).get("all") or {}
        if not days:
            print(f"{hz:<14} — закрытых сделок нет "
                  f"({'книга есть' if d.get('present') else 'пусто'})")
            continue
        print(f"{hz:<14} {len(days):>5}  {t.get('trades', 0):>6}  "
              f"{t.get('win', 0) * 100:>5.1f} %  "
              f"{t.get('pnl', 0.0):>+11.2f} $  "
              f"{days[0]['day']}   {days[-1]['day']}")
    # Книга не из торгуемых обязана СКАЗАТЬ это, а не выглядеть
    # пустой: наблюдательная запись денег не держит вовсе.
    o = col.book_days("sit_obs")
    print(f"\nsit_obs: unknown={o.get('unknown')} "
          f"суток={len(o.get('days') or [])} "
          f"(ожидание: unknown=True, суток 0)")
    for e in (o.get("errors") or [])[:5]:
        print("  ошибка сборки:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
