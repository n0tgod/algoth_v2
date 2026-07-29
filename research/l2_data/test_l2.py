#!/usr/bin/env python3
"""
Тесты сбора L2. Покрываются места, где ошибка уже случалась в проекте.

1. **Колонка по имени, а не по номеру.** Загрузчик funding брал ставку
   по `row[1]`, что верно для Bybit и неверно для Binance; агрегат по
   книге выходил ровно нулём и читался как «funding нейтрален».
2. **Часовой пояс метки.** `fromisoformat` без зоны берёт локальную, и
   на машине не в UTC сетка съезжает на часы — при этом проверка «цена
   сошлась» продолжает проходить, потому что съезжают обе стороны.
3. **Отсутствующая колонка обязана падать, а не возвращать пусто.**
   Молчаливое «данных нет» неотличимо от «файла нет»; именно так
   однажды был отрапортован прогон funding с нулями.
4. **Дни берутся из интервалов жизни инструмента**, а не подряд:
   иначе половина обхода уходит в 404.

    python3 research/l2_data/test_l2.py
"""

import io
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, RESEARCH)

from common.oi_metrics import (  # noqa: E402
    OI_COL, OI_USD_COL, TAKER_RATIO_COL, days_between, metrics_url,
    parse_metrics,
)
from oi_binance import days_of  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def zipped(header, rows):
    body = ",".join(header) + "\n" + "\n".join(",".join(r) for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x-metrics-2025-01-01.csv", body)
    return buf.getvalue()


HEAD_A = ["create_time", "symbol", "sum_open_interest",
          "sum_open_interest_value", "count_toptrader_long_short_ratio",
          "sum_toptrader_long_short_ratio", "count_long_short_ratio",
          "sum_taker_long_short_vol_ratio"]
ROW_A = ["2025-03-10 00:05:00", "BTCUSDT", "69845.397", "5670733877.5",
         "3.26", "1.94", "2.79", "1.129"]

# Тот же день теми же числами, но колонки переставлены: если разбор
# идёт по номеру, значения разъедутся молча.
ORDER_B = [0, 2, 7, 3, 1, 4, 5, 6]
HEAD_B = [HEAD_A[i] for i in ORDER_B]
ROW_B = [ROW_A[i] for i in ORDER_B]


def test_columns_by_name():
    a = parse_metrics(zipped(HEAD_A, [ROW_A]),
                      (OI_COL, OI_USD_COL, TAKER_RATIO_COL))
    b = parse_metrics(zipped(HEAD_B, [ROW_B]),
                      (OI_COL, OI_USD_COL, TAKER_RATIO_COL))
    check("порядок колонок не влияет на разбор", a == b, f"{a} != {b}")
    check("интерес прочитан", abs(a[0][1] - 69845.397) < 1e-6, str(a))
    check("нотионал прочитан", abs(a[0][2] - 5670733877.5) < 1.0, str(a))
    check("отношение объёмов прочитано", abs(a[0][3] - 1.129) < 1e-9, str(a))


def test_missing_column_raises():
    head = [c for c in HEAD_A if c != OI_COL]
    row = [v for c, v in zip(HEAD_A, ROW_A) if c != OI_COL]
    try:
        parse_metrics(zipped(head, [row]), (OI_COL,))
        check("нет колонки — падение", False, "вернулось молча")
    except ValueError:
        check("нет колонки — падение", True)


def test_utc_regardless_of_local_zone():
    """Метка обязана дать одно и то же время в любом часовом поясе."""
    got = {}
    old = os.environ.get("TZ")
    for tz in ("UTC", "Asia/Tokyo", "America/New_York"):
        os.environ["TZ"] = tz
        time.tzset()
        got[tz] = parse_metrics(zipped(HEAD_A, [ROW_A]))[0][0]
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()
    check("метка не зависит от часового пояса машины",
          len(set(got.values())) == 1, str(got))
    # 2025-03-10 00:05:00 UTC
    check("метка равна ожидаемой эпохе", got["UTC"] == 1741565100.0,
          str(got["UTC"]))


def test_bad_rows_skipped_not_fatal():
    rows = [ROW_A, ["мусор"], ROW_A[:-1] + ["не число"]]
    out = parse_metrics(zipped(HEAD_A, rows), (OI_COL, TAKER_RATIO_COL))
    check("битые строки пропущены, файл прочитан", len(out) == 1, str(out))


def test_days_of_intervals():
    iv = [["2024-06-01", "2024-06-03"], ["2026-01-01", "2026-01-02"]]
    d = days_of(iv, "2024-01-01", "2026-06-30")
    check("дни только внутри интервалов", d == [
        "2024-06-01", "2024-06-02", "2024-06-03",
        "2026-01-01", "2026-01-02"], str(d))

    d = days_of([["2023-12-30", "2024-01-02"]], "2024-01-01", "2026-06-30")
    check("окно обрезает интервал слева",
          d == ["2024-01-01", "2024-01-02"], str(d))

    d = days_of([["2026-06-29", "2026-08-01"]], "2024-01-01", "2026-06-30")
    check("окно обрезает интервал справа",
          d == ["2026-06-29", "2026-06-30"], str(d))

    d = days_of([["2024-01-01", "2024-01-03"], ["2024-01-02", "2024-01-04"]],
                "2024-01-01", "2026-06-30")
    check("пересекающиеся интервалы не дают дублей", len(d) == len(set(d))
          and len(d) == 4, str(d))

    d = days_of([["2027-01-01", "2027-02-01"]], "2024-01-01", "2026-06-30")
    check("интервал вне окна даёт пусто", d == [], str(d))


def test_url_and_days():
    u = metrics_url("BTCUSDT", "2025-03-10")
    check("адрес суточного файла", u.endswith(
        "daily/metrics/BTCUSDT/BTCUSDT-metrics-2025-03-10.zip"), u)
    check("перечень дней включает границы",
          days_between("2024-02-28", "2024-03-01")
          == ["2024-02-28", "2024-02-29", "2024-03-01"], "високосный год")


def main():
    print("разбор metrics")
    test_columns_by_name()
    test_missing_column_raises()
    test_utc_regardless_of_local_zone()
    test_bad_rows_skipped_not_fatal()
    print("план обхода")
    test_days_of_intervals()
    test_url_and_days()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
