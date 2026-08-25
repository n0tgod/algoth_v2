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
        said = []
        orig_pub, F.publish = F.publish, said.append
        try:
            rc = F.main(["--symbols", ",".join(syms), "--jobs", "1"])
        finally:
            F.publish = orig_pub
        check("прогон вернул ноль", rc == 0, str(rc))
        check("прогон опубликовал состояние сам", len(said) == 1, str(said))
        man = os.path.join(F.STORE, "manifest.json")
        check("сводка склада написана", os.path.exists(man))
        with open(man, encoding="utf-8") as f:
            got = json.load(f)
        check("в сводке обе сутки", got["total_days"] == 2,
              str(got.get("total_days")))
        check("сводка несёт состав свёртки",
              got["fields"] == list(B.FOLD_FIELDS))
        rep = os.path.join(F.STORE, "Z2-store.md")
        check("отчёт склада написан", os.path.exists(rep))
        txt = open(rep, encoding="utf-8").read() if os.path.exists(rep) else ""
        check("отчёт называет обе свёрнутые сутки",
              all(d in txt for d in days), txt[:200])
        check("отчёт говорит, сколько НЕ свёрнуто",
              "не свёрнуто 0" in txt, txt[-300:])
        # Скрин читает то, что склад написал.
        M, have = P.day_matrices(syms, days[0], log=lambda m: None)
        check("скрин прочитал склад", have == 2 and
              np.isfinite(M["mid_open"]).sum() > 100, f"имён {have}")
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_report_names_the_days_the_store_is_missing():
    """Главное число отчёта — сутки записи, которых на складе нет."""
    days = ["2026-08-20", "2026-08-21"]
    root, old = _setup(days, ["AAAUSDT"])
    try:
        F.fold_day(days[0], syms=["AAAUSDT"], log=lambda m: None,
                   now=time.time() + 10 * 86400)
        rep = F.write_report(syms=["AAAUSDT"], log=lambda m: None)
        check("отставшие сутки названы", rep["missing"] == [days[1]],
              str(rep["missing"]))
        txt = open(rep["path"], encoding="utf-8").read()
        check("отставшие сутки стоят в отчёте числом и именем",
              "не свёрнуто 1" in txt and days[1] in txt, txt[-300:])
        check("и сказано, что делать", "fold.py --jobs" in txt)
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_report_separates_full_days_from_stumps_and_names_recording_gaps():
    """Покрытие и дыры записи — числами, а не арифметикой в уме.

    Без покрытия 491 тыс. символо-минут выглядят как много, а это две
    трети дня; замер по огрызку вперемешку с полными сутками описывает
    не то, что подписано.
    """
    st = {
        "2026-08-03": {"rows": 543, "minutes": 491_459, "bytes": 20 << 20,
                       "symbols": 728, "version": F.FOLD_VERSION},
        "2026-08-04": {"rows": 546, "minutes": 782_256, "bytes": 30 << 20,
                       "symbols": 728, "version": F.FOLD_VERSION},
        "2026-07-30": {"rows": 25, "minutes": 4_285, "bytes": 1 << 18,
                       "symbols": 728, "version": F.FOLD_VERSION},
        # Сутки ПОЛНЫЕ по времени и УЗКИЕ по составу: без отдельного
        # условия на ширину они прошли бы как годные, а кросс-секции на
        # тридцати именах нет (урок T1).
        "2026-07-31": {"rows": 30, "minutes": 30 * 1440, "bytes": 1 << 20,
                       "symbols": 728, "version": F.FOLD_VERSION},
    }
    check("покрытие полных суток около единицы",
          abs(F.coverage(st["2026-08-04"]) - 0.995) < 0.01,
          str(F.coverage(st["2026-08-04"])))
    check("покрытие огрызка ловится",
          abs(F.coverage(st["2026-08-03"]) - 0.629) < 0.01,
          str(F.coverage(st["2026-08-03"])))
    check("суток без строк с записью — не ноль, а пропуск",
          F.coverage({"rows": 0, "minutes": 0}) is None)
    check("дыра записи найдена",
          F.calendar_gaps(["2026-08-01", "2026-08-03"]) == ["2026-08-02"],
          str(F.calendar_gaps(["2026-08-01", "2026-08-03"])))
    check("сплошной ряд дыр не имеет",
          F.calendar_gaps(["2026-08-01", "2026-08-02"]) == [])
    check("годны только полные И широкие сутки",
          F.full_days(st) == ["2026-08-04"], str(F.full_days(st)))
    check("полные, но узкие сутки годными не считаются",
          abs(F.coverage(st["2026-07-31"]) - 1.0) < 1e-9
          and "2026-07-31" not in F.full_days(st))

    root, old = _setup(["2026-08-20", "2026-08-22"], ["AAAUSDT"])
    try:
        F.fold_day("2026-08-20", syms=["AAAUSDT"], log=lambda m: None,
                   now=time.time() + 10 * 86400)
        rep = F.write_report(syms=["AAAUSDT"], log=lambda m: None)
        txt = open(rep["path"], encoding="utf-8").read()
        check("дыра записи названа в отчёте",
              rep["gaps"] == ["2026-08-21"] and "2026-08-21" in txt
              and "Дыры САМОЙ записи" in txt, str(rep["gaps"]))
        check("отчёт говорит, что докачать их неоткуда",
              "неоткуда" in txt)
        check("колонка покрытия есть", "покрытие" in txt, txt[:400])
        # Наши сутки узки по составу (одно имя) — отчёт обязан это сказать,
        # а не считать их годными.
        check("узкие сутки не объявлены годными", not rep["full"],
              str(rep["full"]))
        check("узость названа словами", "Узкие по составу" in txt)
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_density_catches_thinning_that_coverage_cannot():
    """Прорежение видно плотностью и НЕ видно покрытием.

    Проверяется и сама величина, и её ДОРОГА до строки отчёта: урок
    `curve_dd` — формула считалась верно, а попадает ли она в таблицу,
    не покрывал ни один тест, и владелец увидел колонку прочерков.
    """
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE, P.BOOK, P.TRADES, P.STORE)
    F.BOOK = P.BOOK = os.path.join(root, "book")
    F.TRADES = P.TRADES = os.path.join(root, "trades")
    F.STORE = P.STORE = os.path.join(root, "store")
    syms = ["AAAUSDT", "BBBUSDT"]
    far = time.time() + 10 * 86400
    try:
        # Густые сутки и вдвое реже записанные — часы и имена те же.
        write_rec(root, syms, ["2026-08-20"], per_min=6, seed=11)
        write_rec(root, syms, ["2026-08-21"], per_min=3, seed=12)
        for d in ("2026-08-20", "2026-08-21"):
            F.fold_day(d, syms=syms, log=lambda m: None, now=far)
        thick = F.density(os.path.join(F.STORE, "2026-08-20.npz"))
        thin = F.density(os.path.join(F.STORE, "2026-08-21.npz"))
        check("плотность густых суток", thick and abs(thick["med"] - 6) < 1e-6,
              str(thick))
        check("плотность редких суток", thin and abs(thin["med"] - 3) < 1e-6,
              str(thin))
        st = F.scan(F.STORE)
        c1 = F.coverage(st["2026-08-20"])
        c2 = F.coverage(st["2026-08-21"])
        check("покрытие прорежения НЕ видит", abs(c1 - c2) < 1e-9,
              f"{c1} против {c2}")
        rep = F.write_report(syms=syms, log=lambda m: None)
        txt = open(rep["path"], encoding="utf-8").read()
        check("плотность доехала до строки отчёта",
              "| 6.0 |" in txt and "| 3.0 |" in txt, txt[:900])
        check("колонка названа", "снимков/мин" in txt)
    finally:
        (F.BOOK, F.TRADES, F.STORE, P.BOOK, P.TRADES, P.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def test_hour_grid_is_the_control_that_same_day_hours_are_not():
    """Просевший ЧАС последних суток ловится сравнением с теми же часами.

    Именно этого контроля не было, когда я сравнил загруженные часы с
    утренними и объявил цену свёртки: у сборщика проход зависит от
    потока обновлений книги, а тот растёт с активностью рынка.
    """
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE)
    F.BOOK = os.path.join(root, "book")
    F.TRADES = os.path.join(root, "trades")
    F.STORE = os.path.join(root, "store")
    syms = ["AAAUSDT", "BBBUSDT"]
    far = time.time() + 10 * 86400
    days = ["2026-08-20", "2026-08-21", "2026-08-22"]
    try:
        # Час 10 РЕДОК у ВСЕХ суток, час 11 густ у всех — это суточный
        # ритм рынка, а не прорежение. Сверх того у последних суток
        # проседает час 11 — вот это уже нагрузка.
        #
        # Фикстура нарочно устроена так, чтобы два контроля РАЗОШЛИСЬ:
        # сравнение с соседними часами ТОГО ЖЕ дня объявило бы дефектом
        # тихий час 10 у всех суток. Первая версия этой проверки такого
        # различения не давала, и контроль не кусался.
        for d in days:
            write_rec(root, syms, [d], hours=(10,), per_min=2, seed=21)
        for d in days[:2]:
            write_rec(root, syms, [d], hours=(11,), per_min=6, seed=22)
        write_rec(root, syms, [days[2]], hours=(11,), per_min=3, seed=23)
        for d in days:
            F.fold_day(d, syms=syms, log=lambda m: None, now=far)
        rows, off = F.hour_table(F.STORE, days, log=lambda m: None)
        check("сетка собрана по всем суткам", sorted(rows) == days,
              str(sorted(rows)))
        hs = [o["h"] for o in off]
        check("просевший против ТЕХ ЖЕ часов час назван", hs == [11],
              str(off))
        check("тихий у всех суток час дефектом НЕ назван", 10 not in hs,
              str(off))
        rep = F.write_report(syms=syms, log=lambda m: None)
        txt = open(rep["path"], encoding="utf-8").read()
        check("сетка доехала до отчёта", "Плотность по часам" in txt
              and "| 2026-08-22 |" in txt, txt[:300])
        check("отклонение названо словами и числом",
              "реже медианы тех же" in txt and "11 (3 против 6" in txt,
              txt[txt.find("Плотность по часам"):][:800])
    finally:
        (F.BOOK, F.TRADES, F.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def test_even_base_uses_a_true_median_not_the_upper_middle():
    """`sorted(x)[n // 2]` на чётной длине берёт ВЕРХНЕЕ из двух средних.

    Тот же дефект уже ловился однажды на живой странице
    (`Collector._median`) и повторился здесь: на живой сетке из шести
    суток он поднял базу и объявил прорежением ПЯТЬ часов вместо двух.
    Фикстура строится так, чтобы два счёта разошлись в ВЕРДИКТЕ, а не
    в третьем знаке: соседние сутки дают 4, 4, 10, 10 — верхнее среднее
    равно 10, честная медиана 7, и час с шестью снимками флагуется
    только по первой.
    """
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE)
    F.BOOK = os.path.join(root, "book")
    F.TRADES = os.path.join(root, "trades")
    F.STORE = os.path.join(root, "store")
    syms = ["AAAUSDT", "BBBUSDT"]
    far = time.time() + 10 * 86400
    days = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
            "2026-08-21"]
    try:
        for d, n in zip(days, (4, 4, 10, 10, 6)):
            write_rec(root, syms, [d], hours=(12,), per_min=n, seed=31)
            F.fold_day(d, syms=syms, log=lambda m: None, now=far)
        med = F._med([4, 4, 10, 10])
        check("медиана чётной длины — среднее двух средних", med == 7.0,
              str(med))
        rows, off = F.hour_table(F.STORE, days, log=lambda m: None)
        check("час внутри честной базы прорежением НЕ назван",
              [o["h"] for o in off] == [], str(off))
        sp = F.hour_spread(rows)
        check("размах часа по суткам измерен числом",
              sp is not None and sp > 0, str(sp))
        rep = F.write_report(syms=syms, log=lambda m: None)
        txt = open(rep["path"], encoding="utf-8").read()
        check("калибровка порога напечатана",
              "Размах ОДНОГО И ТОГО ЖЕ часа" in txt
              and "диагностика, а не тревога" in txt,
              txt[txt.find("Плотность по часам"):][:900])
    finally:
        (F.BOOK, F.TRADES, F.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def test_flow_tells_market_from_our_load_one_way():
    """Выросшая лента при упавших снимках означает рынок.

    Довод работает в одну сторону, и отчёт обязан это говорить: под
    нашей нагрузкой замедляется и запись ленты, поэтому обычная лента
    при упавших снимках нашей нагрузки не исключает.

    Фикстура нарочно ловит второй дефект — АГРЕГАТОР. Поток взлетает у
    ОДНОГО имени из трёх, то есть медиана по символам не шевелится
    вовсе, а средний поток на имя растёт втрое. Так живой отчёт и
    напечатал «лента 2 против 2»: медианное имя универсума торгует
    один-два принта в минуту, и мера выглядела мерой, ею не будучи.
    """
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE)
    F.BOOK = os.path.join(root, "book")
    F.TRADES = os.path.join(root, "trades")
    F.STORE = os.path.join(root, "store")
    syms = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    far = time.time() + 10 * 86400
    days = ["2026-08-19", "2026-08-20", "2026-08-21"]
    try:
        for d, n, heavy in zip(days, (6, 6, 3), (1, 1, 30)):
            write_rec(root, [syms[0]], [d], hours=(12,), per_min=n, seed=41,
                      trades_per_min=heavy)
            for k, sym in enumerate(syms[1:]):
                write_rec(root, [sym], [d], hours=(12,), per_min=n,
                          seed=42 + k, trades_per_min=1)
            F.fold_day(d, syms=syms, log=lambda m: None, now=far)
        p = os.path.join(F.STORE, days[-1] + ".npz")
        by_med = F.hour_series(p, "trades", log=lambda m: None)[12]
        by_mean = F.hour_series(p, "trades", agg="mean_sym",
                                log=lambda m: None)[12]
        check("медиана по символам взлёт ОДНОГО имени не видит",
              abs(by_med - 1.0) < 1e-9, str(by_med))
        check("средний поток на имя взлёт видит",
              by_mean > 3 * by_med, f"{by_mean} против {by_med}")
        rows, off = F.hour_table(F.STORE, days, log=lambda m: None)
        check("просевший час назван", [o["h"] for o in off] == [12],
              str(off))
        o = off[0]
        check("поток ленты приехал к отклонению",
              o["flow"] is not None and o["flow_med"] is not None
              and o["flow"] > o["flow_med"], str(o))
        rep = F.write_report(syms=syms, log=lambda m: None)
        txt = open(rep["path"], encoding="utf-8").read()
        check("лента стоит в строке отклонения числом с дробью",
              "лента 10.7 против 1.0" in txt,
              txt[txt.find("реже медианы"):][:400])
        check("единица ленты названа",
              "средний поток принтов на имя" in txt,
              txt[txt.find("реже медианы"):][:900])
        check("односторонность довода названа",
              "Обратное доводом НЕ является" in txt,
              txt[txt.find("реже медианы"):][:1200])
    finally:
        (F.BOOK, F.TRADES, F.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def test_screen_starts_at_the_first_full_and_wide_day():
    """Замер начинается с полных и ШИРОКИХ суток, а не с первых суток.

    Состав сборщика рос ступенями (25 → 30 → 540 → 725 имён), и на
    ранних сутках кросс-секции, которой меряется превышение, нет вовсе.
    Взять их в замер значило бы считать ячейки против фона, которого не
    построено, — урок T1.
    """
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE, P.BOOK, P.TRADES, P.STORE)
    F.BOOK = P.BOOK = os.path.join(root, "book")
    F.TRADES = P.TRADES = os.path.join(root, "trades")
    F.STORE = P.STORE = os.path.join(root, "store")
    far = time.time() + 10 * 86400
    narrow = ["AAAUSDT"]
    wide = [f"S{i:03d}USDT" for i in range(120)]
    try:
        # 08-19 — узкие сутки (одно имя), 08-20 и 08-21 — широкие.
        write_rec(root, narrow, ["2026-08-19"], hours=(10,), per_min=2,
                  seed=51)
        for d in ("2026-08-20", "2026-08-21"):
            write_rec(root, wide, [d], hours=tuple(range(24)), per_min=2,
                      seed=52)
        for d in ("2026-08-19", "2026-08-20", "2026-08-21"):
            F.fold_day(d, syms=narrow + wide, log=lambda m: None, now=far)
        st = F.scan(F.STORE)
        full = F.full_days(st)
        check("узкие сутки полными не считаются",
              "2026-08-19" not in full, str(full))
        got = P.start_day("", ["2026-08-19", "2026-08-20", "2026-08-21"],
                          log=lambda m: None)
        check("замер начат с первых широких суток", got == full[0],
              f"{got} против {full[0]}")
        asked = P.start_day("2026-08-19",
                            ["2026-08-19", "2026-08-20", "2026-08-21"],
                            log=lambda m: None)
        check("явно названное начало не трогается", asked == "2026-08-19",
              asked)
    finally:
        (F.BOOK, F.TRADES, F.STORE, P.BOOK, P.TRADES, P.STORE) = old
        shutil.rmtree(root, ignore_errors=True)


def test_publish_is_part_of_the_run():
    """С ключом публикации нет, без ключа она ОБЯЗАНА случиться.

    «Публикует по умолчанию» однажды окажется выключенным молча, если
    проверять только одну сторону.
    """
    days = ["2026-08-20"]
    root, old = _setup(days, ["AAAUSDT"])
    said = []
    orig, F.publish = F.publish, said.append
    try:
        F.main(["--symbols", "AAAUSDT", "--jobs", "1", "--no-publish"])
        check("с ключом публикации нет", not said, str(said))
        F.main(["--symbols", "AAAUSDT", "--jobs", "1", "--restat"])
        check("без ключа публикация случилась", len(said) == 1, str(said))
    finally:
        F.publish = orig
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_partial_day_is_not_taken_for_folded():
    """Сутки, свёрнутые по одному имени из трёх, свёрнутыми не считаются.

    Смоук оставляет файл, неотличимый ПО ИМЕНИ от полного, и следующий
    проход прошёл бы мимо: тот же класс отказа, что готовность символа
    по существованию файла в L2 и дельта прогона вместо состояния в A2.
    Обратная сторона тут же: имя, у которого за эти сутки сырья НЕТ,
    пересвёртки не требует — иначе свежий листинг заставлял бы
    пересворачивать всю запись ради пропуска.
    """
    day = "2026-08-20"
    syms = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    root, old = _setup([day], syms)
    later = time.time() + 10 * 86400
    path = None
    try:
        path = os.path.join(F.STORE, day + ".npz")
        F.fold_day(day, syms=syms[:1], jobs=1, log=lambda m: None,
                   now=later)
        head = F._head(path, names=True)
        check("смоук оставил сутки на складе",
              bool(head) and head["symbols"] == 1, str(head))

        part = F.partial_days(F.scan(F.STORE), syms=syms, store=F.STORE)
        check("отчёт называет такие сутки частичными числом",
              part.get(day) == 2, str(part))

        said = []
        got = F.fold_day(day, syms=syms, jobs=1, log=said.append,
                         now=later)
        check("полный проход не принимает смоук за свёрнутые сутки",
              got == "ok", got)
        # Число берётся из САМОЙ фразы, а не «двойка где-то в строке»:
        # «2» есть и в дате 2026-08-20, то есть слабая проверка прошла
        # бы на молчащем правиле.
        check("и говорит, скольких имён не хватало",
              any("у 2 из запрошенных" in m and "нет свёртки" in m
                  for m in said), str(said))
        head = F._head(path, names=True)
        check("после пересвёртки на складе все имена",
              head["symbols"] == 3, str(head))

        os.makedirs(os.path.join(F.BOOK, "DDDUSDT"), exist_ok=True)
        wide = syms + ["DDDUSDT"]
        got = F.fold_day(day, syms=wide, jobs=1, log=lambda m: None,
                         now=later)
        check("имя без сырья за эти сутки пересвёртки не требует",
              got == "есть", got)
        part = F.partial_days(F.scan(F.STORE), syms=wide, store=F.STORE)
        check("и частичными такие сутки не называются", not part, str(part))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (
        test_store_reproduces_raw_bit_for_bit,
        test_unfinished_day_is_not_folded,
        test_state_is_read_from_disk_not_from_the_run,
        test_partial_day_is_not_taken_for_folded,
        test_foreign_version_falls_back_loudly,
        test_symbol_absent_that_day_is_a_gap_and_order_is_the_asked_one,
        test_fields_of_the_screen_are_a_subset_of_the_fold,
        test_parallel_fold_equals_single_threaded,
        test_cli_runs_the_whole_road,
        test_report_names_the_days_the_store_is_missing,
        test_report_separates_full_days_from_stumps_and_names_recording_gaps,
        test_density_catches_thinning_that_coverage_cannot,
        test_hour_grid_is_the_control_that_same_day_hours_are_not,
        test_even_base_uses_a_true_median_not_the_upper_middle,
        test_flow_tells_market_from_our_load_one_way,
        test_screen_starts_at_the_first_full_and_wide_day,
        test_publish_is_part_of_the_run,
    )
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    # Число блоков СЧИТАЕТСЯ, а не пишется литералом: прежняя строка
    # печатала «13» и до добавления двух проверок, и после — то есть
    # прогон выглядел прежним при изменившемся составе.
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
