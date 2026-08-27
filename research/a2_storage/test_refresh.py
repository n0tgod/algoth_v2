#!/usr/bin/env python3
"""
Тесты докачки хранилища A2.

Главный столп — признак готовности партиции: дозакачанные суточные
файлы состав символов НЕ меняют, и партиция молча считалась бы
готовой. Это тот же класс, что «готовность символа по существованию
файла» в L2, и проверяется он сборкой настоящего `build.py` на
подставном сырье, а не рассуждением.

    python3 research/a2_storage/test_refresh.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "a1_universe"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import refresh as RF                                      # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def test_days_stop_before_today():
    """Сегодня не качается: суточный архив появляется после конца суток."""
    edge = date(2026, 6, 30)
    today = date(2026, 7, 5)
    got = RF.days_to_fetch(edge, today=today)
    check("дни от края до вчера",
          got == [date(2026, 7, d) for d in (1, 2, 3, 4)], f"{got}")
    check("свежее хранилище — пустой список",
          RF.days_to_fetch(date(2026, 7, 4), today=today) == [], "")
    check("нет края — нечего качать",
          RF.days_to_fetch(None, today=today) == [], "")


def test_max_days_guard():
    """Предохранитель: докачка не превращается в повторный прогон A1."""
    got = RF.days_to_fetch(date(2020, 1, 1), today=date(2026, 7, 5))
    check("не больше предела", len(got) == RF.MAX_DAYS, f"{len(got)}")


def test_live_symbols_skips_the_dead():
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "u.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"assets": {
                "AAA": {"binance_symbol": "AAAUSDT",
                        "last_trading_day": "2026-12-31"},
                "DEAD": {"binance_symbol": "DEADUSDT",
                         "last_trading_day": "2025-01-01"},
                "NOSYM": {"last_trading_day": "2026-12-31"},
            }}, f)
        got = RF.live_symbols(p, on_day=date(2026, 7, 1))
        check("живой взят, мёртвый и бессимвольный — нет",
              got == ["AAAUSDT"], f"{got}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def make_zip(path, rows):
    """Суточный/месячный архив в формате Binance."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.StringIO()
    for t, c in rows:
        # open_time, open, high, low, close, volume, close_time,
        # quote_volume, trades, taker_base, taker_quote, ignore
        buf.write(f"{t},{c},{c},{c},{c},1,{t + 59999},1,5,1,1,0\n")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(os.path.basename(path).replace(".zip", ".csv"),
                   buf.getvalue())


def build_store(tmp, interval="1m", extra_day=False, gap_day=False):
    """Сырьё месяца и сборка партиции НАСТОЯЩИМ build.py."""
    raw = os.path.join(tmp, "klines", interval, "AAAUSDT")
    base = int(date(2026, 7, 1).strftime("%s")) * 1000
    make_zip(os.path.join(raw, f"AAAUSDT-{interval}-2026-07-01.zip"),
             [(base + i * 60000, 100.0) for i in range(60)])
    if extra_day:
        d2 = base + 86_400_000
        make_zip(os.path.join(raw, f"AAAUSDT-{interval}-2026-07-02.zip"),
                 [(d2 + i * 60000, 101.0) for i in range(60)])
    if gap_day:
        # 1 июля есть, 2–4 нет, 5 есть: ровно та дыра, которую сделал
        # живой пилот, взяв последние дни вместо первых.
        d5 = base + 4 * 86_400_000
        make_zip(os.path.join(raw, f"AAAUSDT-{interval}-2026-07-05.zip"),
                 [(d5 + i * 60000, 105.0) for i in range(60)])
    out = os.path.join(tmp, "out")
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ)
    # Пишем в СВОЙ каталог: первая версия теста собирала в рабочее
    # хранилище проекта и на втором прогоне подхватывала собственный
    # мусор — «партиция уже готова», проверка падала на верном коде.
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "build.py"),
         "--interval", interval, "--raw", os.path.join(tmp, "klines"),
         "--dest", os.path.join(tmp, "parquet")],
        cwd=RESEARCH, capture_output=True, text=True, env=env)
    return r


def test_readiness_accounts_for_new_files():
    """Дозакачанный день ОБЯЗАН вызвать пересборку партиции.

    Состав символов при докачке не меняется, и по прежнему признаку
    («символы совпали») месяц оставался бы без свежих дней навсегда.
    Проверяется настоящей сборкой: сперва один день, потом два.
    """
    tmp = tempfile.mkdtemp()
    try:
        r1 = build_store(tmp)
        check("первая сборка прошла", r1.returncode == 0,
              (r1.stderr or "")[-300:])
        man = os.path.join(tmp, "parquet", "1m",
                           "2026-07.parquet.symbols.json")
        check("манифест партиции на месте", os.path.exists(man),
              f"{man}")
        if not os.path.exists(man):
            return
        with open(man, encoding="utf-8") as f:
            m1 = json.load(f)
        check("манифест несёт число файлов",
              m1.get("files") == 1, f"{m1}")
        r2 = build_store(tmp, extra_day=True)
        check("вторая сборка прошла", r2.returncode == 0,
              (r2.stderr or "")[-300:])
        with open(man, encoding="utf-8") as f:
            m2 = json.load(f)
        check("новый файл вызвал пересборку",
              m2.get("files") == 2 and m2["rows"] > m1["rows"],
              f"{m1} → {m2}")
        # Сводка обязана лечь рядом с ПОДСТАВНЫМИ партициями, а не в
        # рабочий каталог проекта: первая версия теста затёрла сводку
        # настоящего хранилища числами на одном символе.
        check("сводка легла в свой каталог",
              os.path.exists(os.path.join(tmp, "parquet",
                                          "build_1m.json")),
              f"{sorted(os.listdir(os.path.join(tmp, 'parquet')))}")
        real = os.path.join(HERE, "out", "build_1m.json")
        if os.path.exists(real):
            with open(real, encoding="utf-8") as f:
                got = json.load(f)
            check("рабочая сводка не тронута тестом",
                  got.get("symbols", 0) > 1, f"{got}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_storage_edge_reads_a_real_partition():
    """Край читается с НАСТОЯЩЕЙ партиции и без сторонних модулей.

    Живой пилот упал ровно здесь: duckdb не может отдать TIMESTAMPTZ в
    Python без `pytz`, которого на сервере нет. Значит дату обязан
    возвращать сам SQL — строкой. Тест воспроизводит серверный отказ:
    в песочнице `pytz` тоже отсутствует.
    """
    tmp = tempfile.mkdtemp()
    orig = RF.PARQUET
    try:
        r = build_store(tmp)
        check("партиция собрана", r.returncode == 0,
              (r.stderr or "")[-300:])
        RF.PARQUET = os.path.join(tmp, "parquet")
        got = RF.storage_edge("1m")
        check("край — дата последнего бара партиции",
              got == date(2026, 7, 1), f"{got}")
        RF.PARQUET = os.path.join(tmp, "нет-такого")
        check("нет хранилища — нет края",
              RF.storage_edge("1m") is None, "")
    finally:
        RF.PARQUET = orig
        shutil.rmtree(tmp, ignore_errors=True)


def test_edge_is_the_end_of_CONTINUOUS_coverage():
    """Край — конец НЕПРЕРЫВНОГО покрытия, а не максимальная метка.

    Живой пилот это и вскрыл: `--days 3` взял последние три дня, край
    прыгнул с 30 июня на 26 августа, а полтора месяца внутри остались
    дырой — и следующий прогон счёл бы хранилище свежим навсегда.
    Признаком результата служило неполное свойство: тот же класс, что
    «готовность партиции по составу символов».
    """
    tmp = tempfile.mkdtemp()
    orig = RF.PARQUET
    try:
        r = build_store(tmp, gap_day=True)
        check("партиция с дырой собрана", r.returncode == 0,
              (r.stderr or "")[-300:])
        RF.PARQUET = os.path.join(tmp, "parquet")
        got = RF.storage_edge("1m")
        check("край остановился ПЕРЕД дырой",
              got == date(2026, 7, 1), f"{got}")
    finally:
        RF.PARQUET = orig
        shutil.rmtree(tmp, ignore_errors=True)


def test_days_pilot_takes_the_FIRST_days():
    """Пилот берёт дни ОТ КРАЯ, а не с конца: иначе он сам делает дыру."""
    days = [date(2026, 7, d) for d in range(1, 11)]
    check("первые три", RF.limit_days(days, 3) == days[:3],
          f"{RF.limit_days(days, 3)}")
    check("ноль — все", RF.limit_days(days, 0) == days, "")


def test_verdict_says_when_edge_did_not_move():
    """Неподвижный край при непустой докачке — отказ, и он называется."""
    src = open(os.path.join(HERE, "refresh.py"), encoding="utf-8").read()
    check("ветка неподвижного края есть в коде",
          "край хранилища НЕ сдвинулся" in src, "")
    check("ветка свежего хранилища есть",
          "хранилище свежее" in src, "")


def main():
    print("выбор дней и символов")
    test_days_stop_before_today()
    test_max_days_guard()
    test_live_symbols_skips_the_dead()
    print("готовность партиции")
    test_readiness_accounts_for_new_files()
    print("край хранилища")
    test_storage_edge_reads_a_real_partition()
    test_edge_is_the_end_of_CONTINUOUS_coverage()
    test_days_pilot_takes_the_FIRST_days()
    print("вердикт")
    test_verdict_says_when_edge_did_not_move()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
