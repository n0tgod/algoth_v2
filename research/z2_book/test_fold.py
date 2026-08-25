"""Тесты минутного склада записи стакана.

Главный из них один: **склад обязан воспроизводить сырой счёт бит в
бит**. Правка скорости, меняющая числа, есть другая мера, а не
ускорение — и узнать это можно только сравнив два пути на одних и тех
же файлах, вместе с пропусками.

Остальное — правила, каждое из которых уже стоило проекту прогона:
состояние читается с диска, а не из дельты прогона (дефект `build.py`
в A2); незакончившиеся сутки не сворачиваются (свёрнутый наполовину
день неотличим по имени от полного); склад чужой версии не берётся
молча, а падает на сырьё со словами.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "z1_screen"))

import bookfeat2 as B                                     # noqa: E402
import fold as F                                          # noqa: E402
import probe as P                                         # noqa: E402
from test_probe import check, write_rec, FAILED           # noqa: E402


def _setup(days, syms, hours=(10, 11), per_min=4, seed=7):
    root = tempfile.mkdtemp()
    write_rec(root, syms, days, hours=hours, per_min=per_min, seed=seed)
    old = (F.BOOK, F.TRADES, F.STORE, P.BOOK, P.TRADES, P.STORE,
           P.MIN_SNAPS)
    F.BOOK = P.BOOK = os.path.join(root, "book")
    F.TRADES = P.TRADES = os.path.join(root, "trades")
    F.STORE = P.STORE = os.path.join(root, "store")
    P.MIN_SNAPS = 3
    return root, old


def _restore(old):
    (F.BOOK, F.TRADES, F.STORE, P.BOOK, P.TRADES, P.STORE,
     P.MIN_SNAPS) = old


def _same(a, b):
    return (a.shape == b.shape
            and np.array_equal(a, b, equal_nan=True))


def test_store_reproduces_raw_bit_for_bit():
    """Матрицы со склада и из сырья равны точно, включая пропуски."""
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    root, old = _setup(days, syms)
    try:
        raw, have_raw = P.day_matrices(syms, days[0], log=lambda m: None,
                                       use_store=False)
        F.fold_day(days[0], syms=syms, jobs=1, log=lambda m: None,
                   now=time.time() + 10 * 86400)
        got, have_st = P.day_matrices(syms, days[0], log=lambda m: None,
                                      use_store=True)
        bad = [f for f in P.FIELDS if not _same(raw[f], got[f])]
        check("склад воспроизводит сырьё бит в бит", not bad,
              f"разошлись поля: {bad}")
        # И ДО маски тонких минут тоже. Маска ставит пропуск всюду, где
        # снимков мало, и потому сама по себе стирает разницу между
        # «пропуск» и «ноль»: сравнение только после неё пропустило бы
        # подмену кодировки пропуска. Проверено отрицательным контролем.
        raw0 = P._raw_matrices(syms, days[0], log=lambda m: None)
        st0 = F.read_day(days[0], syms, fields=P.FIELDS, store=F.STORE,
                         log=lambda m: None)
        bad0 = [f for f in P.FIELDS if not _same(raw0[f], st0[f])]
        check("равенство держится и до маски тонких минут", not bad0,
              f"разошлись поля: {bad0}")
        check("число имён с записью совпало", have_raw == have_st,
              f"{have_raw} против {have_st}")
        fin = int(np.isfinite(raw["mid_open"]).sum())
        check("сравнение шло на непустых матрицах", fin > 100, f"минут {fin}")
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_unfinished_day_is_not_folded():
    """Текущие сутки не сворачиваются: половина дня выглядела бы целой."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc)
                + timedelta(days=1)).strftime("%Y-%m-%d")
    root, old = _setup([today], ["AAAUSDT"])
    try:
        rc = F.fold_day(today, syms=["AAAUSDT"], log=lambda m: None)
        check("сегодняшние сутки не свёрнуты", rc == "не кончились", rc)
        check("файла суток нет",
              not os.path.exists(os.path.join(F.STORE, today + ".npz")))
        check("завтрашние тем более не свёрнуты",
              F.fold_day(tomorrow, syms=["AAAUSDT"],
                         log=lambda m: None) == "не кончились")
        check("вчерашние — годны",
              F.day_is_closed((datetime.now(timezone.utc)
                               - timedelta(days=1)).strftime("%Y-%m-%d")))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_state_is_read_from_disk_not_from_the_run():
    """Обход склада знает о сутках, которых этот процесс не сворачивал."""
    days = ["2026-08-20", "2026-08-21"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms)
    try:
        far = time.time() + 10 * 86400
        for d in days:
            F.fold_day(d, syms=syms, jobs=1, log=lambda m: None, now=far)
        st = F.scan(F.STORE)
        check("обход нашёл обе сутки", sorted(st) == days, sorted(st))
        check("заголовок несёт версию с диска",
              all(v["version"] == F.FOLD_VERSION for v in st.values()))
        check("заголовок несёт число символо-минут",
              all(v["minutes"] > 0 for v in st.values()),
              str({k: v["minutes"] for k, v in st.items()}))
        man = F.write_manifest(F.STORE, log=lambda m: None)
        check("сводка выведена из обхода, а не из прогона",
              man["total_days"] == 2
              and man["total_minutes"] == sum(v["minutes"]
                                              for v in st.values()))
        # Повторный вызов не пересворачивает готовое.
        check("готовые сутки не пересворачиваются",
              F.fold_day(days[0], syms=syms, log=lambda m: None,
                         now=far) == "есть")
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_foreign_version_falls_back_loudly():
    """Склад чужой версии не берётся молча — падает на сырьё со словами."""
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms)
    try:
        F.fold_day(days[0], syms=syms, log=lambda m: None,
                   now=time.time() + 10 * 86400)
        said = []
        raw, _ = P.day_matrices(syms, days[0], log=lambda m: None,
                                use_store=False)
        F.FOLD_VERSION += 1
        try:
            got = F.read_day(days[0], syms, fields=P.FIELDS,
                             store=F.STORE, log=said.append)
        finally:
            F.FOLD_VERSION -= 1
        check("чужая версия не отдаётся", got is None)
        check("отказ назван словами",
              any("верси" in m for m in said), str(said))
        # А замер при этом обязан посчитаться — по сырью.
        F.FOLD_VERSION += 1
        try:
            back, _ = P.day_matrices(syms, days[0], log=lambda m: None)
        finally:
            F.FOLD_VERSION -= 1
        check("замер посчитался запасным путём",
              all(_same(raw[f], back[f]) for f in P.FIELDS))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_symbol_absent_that_day_is_a_gap_and_order_is_the_asked_one():
    """Состав записи растёт по дням: чужое имя — строка пропусков."""
    days = ["2026-08-20"]
    root, old = _setup(days, ["AAAUSDT", "BBBUSDT"])
    try:
        F.fold_day(days[0], syms=["AAAUSDT", "BBBUSDT"],
                   log=lambda m: None, now=time.time() + 10 * 86400)
        ask = ["BBBUSDT", "ZZZUSDT", "AAAUSDT"]
        got = F.read_day(days[0], ask, fields=P.FIELDS, store=F.STORE,
                         log=lambda m: None)
        check("порядок строк — запрошенный, а не складской",
              np.isfinite(got["mid_open"][0]).any()
              and np.isfinite(got["mid_open"][2]).any())
        check("имени, которого в тех сутках не было, — пропуск",
              not np.isfinite(got["mid_open"][1]).any())
        one = F.read_day(days[0], ["AAAUSDT"], fields=P.FIELDS,
                         store=F.STORE, log=lambda m: None)
        check("та же строка при другом запросе — та же",
              _same(one["mid_open"][0], got["mid_open"][2]))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_fields_of_the_screen_are_a_subset_of_the_fold():
    """Поле замера, которого нет в свёртке, дало бы матрицу пропусков."""
    miss = [f for f in P.FIELDS if f not in B.FOLD_FIELDS]
    check("поля скрина — подмножество свёртки", not miss, str(miss))
    check("порядок свёртки объявлен один раз",
          len(B.FOLD_FIELDS) == len(set(B.FOLD_FIELDS)))


def test_parallel_fold_equals_single_threaded():
    """Три потока обязаны дать тот же склад, что один."""
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    root, old = _setup(days, syms)
    far = time.time() + 10 * 86400
    try:
        F.fold_day(days[0], syms=syms, jobs=1, log=lambda m: None, now=far)
        one = F.read_day(days[0], syms, store=F.STORE, log=lambda m: None)
        F.fold_day(days[0], syms=syms, jobs=3, refold=True,
                   log=lambda m: None, now=far)
        many = F.read_day(days[0], syms, store=F.STORE, log=lambda m: None)
        bad = [f for f in B.FOLD_FIELDS if not _same(one[f], many[f])]
        check("параллельная свёртка равна последовательной", not bad,
              str(bad))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_cli_runs_the_whole_road():
    """Настоящий `main()`: находит сутки в сырье, сворачивает, пишет сводку.

    У свёртки дорог несколько (разбор ключей, поиск суток по именам
    часовых файлов, сама свёртка, сводка), и «тесты зелёные» значит
    ровно те дороги, которые тесты ИСПОЛНЯЮТ. Урок S11.
    """
    days = ["2026-08-20", "2026-08-21"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms)
    try:
        found = F.days_with_records(book=F.BOOK)
        check("сутки найдены по именам часовых файлов", found == days,
              str(found))
        rc = F.main(["--symbols", ",".join(syms), "--jobs", "1"])
        check("прогон вернул ноль", rc == 0, str(rc))
        man = os.path.join(F.STORE, "manifest.json")
        check("сводка склада написана", os.path.exists(man))
        with open(man, encoding="utf-8") as f:
            got = json.load(f)
        check("в сводке обе сутки", got["total_days"] == 2,
              str(got.get("total_days")))
        check("сводка несёт состав свёртки",
              got["fields"] == list(B.FOLD_FIELDS))
        # Скрин читает то, что склад написал.
        M, have = P.day_matrices(syms, days[0], log=lambda m: None)
        check("скрин прочитал склад", have == 2 and
              np.isfinite(M["mid_open"]).sum() > 100, f"имён {have}")
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def main():
    test_store_reproduces_raw_bit_for_bit()
    test_unfinished_day_is_not_folded()
    test_state_is_read_from_disk_not_from_the_run()
    test_foreign_version_falls_back_loudly()
    test_symbol_absent_that_day_is_a_gap_and_order_is_the_asked_one()
    test_fields_of_the_screen_are_a_subset_of_the_fold()
    test_parallel_fold_equals_single_threaded()
    test_cli_runs_the_whole_road()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print("все проверки прошли (8 блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
