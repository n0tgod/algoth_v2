#!/usr/bin/env python3
"""Проверки прохода лесенки: свой склад, чужой не трогается."""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
Z2 = os.path.join(os.path.dirname(HERE), "z2_book")
for p in (HERE, Z2):
    if p not in sys.path:
        sys.path.insert(0, p)

import fold as F                                          # noqa: E402
import fold_ladder as FL                                  # noqa: E402
import ladder as LD                                       # noqa: E402
from test_probe import check, FAILED                      # noqa: E402

TICK = 0.01
LEVELS = 12


def write_ladder_rec(root, syms, days, hour=10, per_min=30, seed=3,
                     hours=None, spill=0.0, pull=0.0):
    """Запись с НАСТОЯЩЕЙ лесенкой: уровни на сетке шага цены.

    Общий помощник `write_rec` кладёт один уровень на сторону, и у него
    цена каждого снимка своя — пересечение видимых цен тогда пусто
    всегда, и любая мера по уровням выходит тождественным нулём. Такая
    фикстура прошла бы проверку, ничего не проверив; поэтому здесь своя,
    с уровнями, которые стоят на месте.

    `spill` двигает биржевую метку ПОСЛЕДНЕГО снимка часа за его
    границу: момент наблюдения — позднее из двух времён, значит запись
    лежит в файле своего часа, а по времени принадлежит следующему.
    Ровно этот перенос обязано пережить почасовое чтение.
    """
    import json
    import random
    from datetime import datetime, timezone
    rng = random.Random(seed)
    hh_list = tuple(hours) if hours else (hour,)
    for day in days:
        d0 = int(datetime.strptime(day, "%Y-%m-%d")
                 .replace(tzinfo=timezone.utc).timestamp())
        for si, sym in enumerate(syms):
            bd = os.path.join(root, "book", sym)
            td = os.path.join(root, "trades", sym)
            os.makedirs(bd, exist_ok=True)
            os.makedirs(td, exist_ok=True)
            base = 100.0
            for hour_i in hh_list:
                hh = (datetime.fromtimestamp(d0 + hour_i * 3600,
                                             timezone.utc)
                      .strftime("%Y-%m-%d-%H"))
                bl, tl = [], []
                for m in range(60):
                    for k in range(per_min):
                        t = d0 + hour_i * 3600 + m * 60 + k * (60 / per_min)
                        # Лучшая цена стоит на месте почти всегда: уровни
                        # обязаны переживать соседние снимки, иначе
                        # пересечения не будет вовсе.
                        if rng.random() < 0.05:
                            base = round(base + TICK * rng.choice((-1, 1)), 2)
                        # `pull` съедает показанный бид на части минут,
                        # не убирая сами цены: уровень, ИСЧЕЗНУВШИЙ из
                        # лесенки, мерой снятия не считается вовсе (он
                        # ушёл за край видимого), поэтому фикстура, где
                        # уровни просто пропадают, не породила бы ни
                        # одного события — и дорога скрина осталась бы
                        # неисполненной.
                        # Через снимок, а не один раз за минуту: меры
                        # минуты — это СУММЫ по парам, и одиночная
                        # просадка среди сорока пар даёт долю 1/40, то
                        # есть ни одно объявленное условие не сработает
                        # и дорога скрина останется неисполненной.
                        # Фаза «дикой» минуты СВОЯ у каждого имени:
                        # синхронный сигнал не оставляет фона — все
                        # символы в эти минуты запрещены как соседи, и
                        # контроль не строится ни для одного события
                        # (урок T1 и L3, воспроизведённый фикстурой).
                        thin = pull if (pull and m % 5 == si % 5
                                        and k % 2 == 1) else 1.0
                        b = [[round(base - TICK * i, 2),
                              round((2.0 + rng.random()) * thin, 3)]
                             for i in range(LEVELS)]
                        a = [[round(base + TICK * (i + 1), 2),
                              round(2.0 + rng.random(), 3)]
                             for i in range(LEVELS)]
                        last = (m == 59 and k == per_min - 1)
                        ts = t + (spill if last else 0.0)
                        bl.append(json.dumps(
                            {"s": sym, "ts": int(ts * 1000), "u": 1,
                             "bid": b[0][0], "ask": a[0][0],
                             "bid_sz": b[0][1], "ask_sz": a[0][1], "upd": 5,
                             "b": b, "a": a, "reach_b": 50.0,
                             "reach_a": 60.0,
                             "bq0.0005": 10.0, "aq0.0005": 11.0,
                             "bq0.001": 20.0, "aq0.001": 21.0,
                             "bq0.0025": 100.0, "aq0.0025": 110.0,
                             "bq0.005": 200.0, "aq0.005": 210.0,
                             "t": round(t, 3)}, separators=(",", ":")))
                        if k % 5 == 0:
                            tl.append(json.dumps(
                                {"ts": int(t * 1000), "s": sym, "side": -1,
                                 "p": b[0][0], "v": 0.5},
                                separators=(",", ":")))
                        # Принты ПОСЛЕ последнего снимка часа: они
                        # объясняют убыль в первой паре следующего часа,
                        # и почасовое чтение обязано донести их туда.
                        # Их несколько и на разных уровнях нарочно:
                        # съеденное есть min(убыль, объём сделок на этой
                        # цене), и один принт на случайной сетке размеров
                        # с половинной вероятностью попадает на выросший
                        # уровень — то есть не меняет ничего, и подделка
                        # переноса теста не роняет.
                        if last:
                            for lv in range(6):
                                tl.append(json.dumps(
                                    {"ts": int((t + 0.5) * 1000), "s": sym,
                                     "side": -1, "p": b[lv][0], "v": 0.7},
                                    separators=(",", ":")))
                with open(os.path.join(bd, hh + ".jsonl"), "w",
                          encoding="utf-8") as f:
                    f.write("\n".join(bl) + "\n")
                with open(os.path.join(td, hh + ".jsonl"), "w",
                          encoding="utf-8") as f:
                    f.write("\n".join(tl) + "\n")


def _setup(days, syms, per_min=4):
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES, F.STORE, FL.STORE)
    F.BOOK = os.path.join(root, "book")
    F.TRADES = os.path.join(root, "trades")
    F.STORE = os.path.join(root, "store")
    FL.STORE = os.path.join(root, "store3")
    write_ladder_rec(root, syms, days, hour=10, per_min=per_min)
    return root, old


def _restore(old):
    (F.BOOK, F.TRADES, F.STORE, FL.STORE) = old


def test_ladder_folds_into_its_own_store_and_leaves_the_book_alone():
    """У лесенки свой склад, и книжный она не трогает.

    Два склада делят одну машинерию, и если каталог разрешается на
    ИМПОРТЕ, а не в момент вызова, свёртка молча пишет мимо. Первая
    версия правки `fold.py` делала ровно это.
    """
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms, per_min=30)
    far = time.time() + 10 * 86400
    try:
        F.fold_day(days[0], syms=syms, log=lambda m: None, now=far)
        # Каталог НЕ передаётся: его обязан дать реестр, и разрешить
        # он его обязан в момент вызова. Первая версия правки `fold.py`
        # замораживала путь на импорте и молча писала мимо.
        F.fold_day(days[0], syms=syms, log=lambda m: None, now=far,
                   kind="ladder")
        b = F.scan(F.STORE)
        l3 = F.scan(FL.STORE)
        check("книжный склад на месте", days[0] in b, str(sorted(b)))
        check("ладдерный склад появился", days[0] in l3, str(sorted(l3)))
        check("склады — разные каталоги", F.STORE != FL.STORE)
        got = F.read_day(days[0], syms, fields=LD.FIELDS, store=FL.STORE,
                         log=lambda m: None)
        check("поля лесенки читаются со своего склада",
              got is not None and set(got) == set(LD.FIELDS),
              str(None if got is None else sorted(got)))
        bk = F.read_day(days[0], syms, store=F.STORE, log=lambda m: None)
        check("книжные поля читаются со своего",
              bk is not None and "mid_open" in bk,
              str(None if bk is None else sorted(bk)[:3]))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_flows_reach_the_minute_grid_with_real_numbers():
    """Числа обязаны доехать от пары снимков до минутной сетки.

    Проверять надо не только величину, но и её ДОРОГУ до склада — тот
    же урок, что колонка просадки прочерками в турнире.
    """
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms, per_min=30)
    far = time.time() + 10 * 86400
    try:
        F.fold_day(days[0], syms=syms, log=lambda m: None, now=far,
                   kind="ladder", store=FL.STORE)
        got = F.read_day(days[0], syms, fields=LD.FIELDS, store=FL.STORE,
                         log=lambda m: None)
        import numpy as np
        vis = got["vis_b"]
        pairs = got["pairs"]
        live = np.isfinite(vis)
        check("минуты с записью заполнены", int(live.sum()) >= 100,
              str(int(live.sum())))
        check("видимый нотионал положителен",
              float(np.nanmin(vis[live])) > 0, str(np.nanmin(vis[live])))
        # Пар в минуте на одну БОЛЬШЕ числа снимков внутри неё: первый
        # снимок минуты пары́тся с последним снимком предыдущей, и эта
        # пара принадлежит текущей минуте — по времени ВТОРОГО снимка.
        check("пар в минуте на одну больше числа снимков",
              float(np.nanmax(pairs)) == 30.0, str(np.nanmax(pairs)))
        # Размеры уровней в фикстуре дрожат, значит и снятое, и
        # добавленное обязаны быть положительными: ноль здесь означал бы,
        # что мера не досчиталась до склада.
        check("снятое доехало до склада числом",
              float(np.nansum(got["cancel_b"])) > 0,
              str(np.nansum(got["cancel_b"])))
        check("добавленное доехало до склада числом",
              float(np.nansum(got["add_b"])) > 0,
              str(np.nansum(got["add_b"])))
        check("съеденное сделками посчитано",
              float(np.nansum(got["eat_b"])) > 0,
              str(np.nansum(got["eat_b"])))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_trades_are_matched_to_their_own_interval():
    """Сделка объясняет убыль ТОГО интервала, в котором случилась.

    Иначе принт из начала минуты оправдывал бы снятие в её конце — то
    же самое, чем плоха полосовая мера Z2.
    """
    t0 = 1786000000.0
    snaps = [{"t": t0 + i, "bid": 99.0, "ask": 101.0,
              "b": [[99.0, 10.0 - i]], "a": [[101.0, 10.0]]}
             for i in range(3)]
    # Один принт лежит в первом интервале, другой — ДО первого снимка
    # вовсе. Второй не вправе объяснить ничего: убыль, объяснённая
    # сделкой из чужого времени, есть переодетая агрессия.
    trs = [(t0 - 10.0, -1, 99.0, 5.0), (t0 + 0.5, -1, 99.0, 1.0)]
    keep, LD.MIN_PAIRS = LD.MIN_PAIRS, 1
    try:
        got = FL.fold_symbol(snaps, trs, t0, n_min=2)
    finally:
        LD.MIN_PAIRS = keep
    check("первый интервал объяснён своей сделкой",
          got["eat_b"][0] == 99.0, f"eat={got['eat_b'][0]}")
    check("сделка до первого снимка ничего не объясняет",
          got["cancel_b"][0] == 99.0, f"cancel={got['cancel_b'][0]}")


def test_interval_boundary_is_strict_on_the_left():
    """Принт ровно в момент предыдущего снимка принадлежит ПРОШЛОМУ
    интервалу.

    Внутри цикла это правило было мёртвым: указатель по ленте
    монотонный, и до сравнения дело не доходило — защита существовала
    только на вид, и подделка её не роняла. Вынесенная функция делает
    границу живой и проверяемой.
    """
    trs = [(10.0, -1, 99.0, 1.0), (10.5, -1, 99.0, 2.0),
           (11.0, -1, 99.0, 3.0), (12.0, -1, 99.0, 4.0)]
    win, j = FL.trades_between(trs, 0, 10.0, 11.0)
    check("принт ровно на левой границе не взят",
          [w[2] for w in win] == [2.0, 3.0], str(win))
    check("указатель встал за взятыми", j == 3, str(j))
    nxt, j = FL.trades_between(trs, j, 11.0, 12.0)
    check("следующий интервал берёт свой принт",
          [w[2] for w in nxt] == [4.0], str(nxt))
    check("цена и сторона доехали в правильном порядке",
          nxt[0][0] == 99.0 and nxt[0][1] == -1, str(nxt))


def test_symbols_can_be_given_by_a_repeated_key():
    """Имена можно давать повторным ключом, а не только через запятую.

    Очередь заданий пропускает аргументы только из [A-Za-z0-9._/=-], и
    список через запятую она отвергает — страж прав, править надо здесь.
    Первое задание на смоук отказом и кончилось.
    """
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT"]
    root, old = _setup(days, syms, per_min=30)
    seen = {}
    orig = F.fold_day

    def spy(day, syms=None, **kw):
        seen["syms"] = list(syms or [])
        return "ok"

    try:
        F.fold_day = spy
        FL.main(["--start", days[0], "--end", days[0],
                 "--symbols", "AAAUSDT", "--symbols", "BBBUSDT",
                 "--no-publish"])
        check("повторный ключ собрал оба имени",
              seen.get("syms") == syms, str(seen))
        FL.main(["--start", days[0], "--end", days[0],
                 "--symbols", "AAAUSDT,BBBUSDT", "--no-publish"])
        check("запятая по-прежнему работает",
              seen.get("syms") == syms, str(seen))
    finally:
        F.fold_day = orig
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_observation_moment_is_the_later_of_two_times():
    """Момент наблюдения — позднее из метки сборщика и метки биржи.

    Метку `t` сборщик ставит ОДИН раз на весь проход по символам, а
    проход занимает до 2.5 с: у символов, до которых очередь дошла
    позже, содержимое снимка новее собственной метки. Правило то же,
    что у лёгкого разбора Z2, и разойтись они не вправе.
    """
    import json
    line = json.dumps({"s": "AAAUSDT", "ts": 1786000002000, "u": 1,
                       "bid": 99.0, "ask": 101.0, "bid_sz": 1.0,
                       "ask_sz": 1.0, "upd": 3,
                       "b": [[99.0, 1.0]], "a": [[101.0, 1.0]],
                       "reach_b": 5.0, "reach_a": 5.0,
                       "bq0.0025": 1.0, "aq0.0025": 1.0,
                       "t": 1786000000.0}, separators=(",", ":"))
    got = FL.snap_full(line)
    check("взято позднее из двух времён", got["t"] == 1786000002.0,
          str(got["t"]))
    import bookfeat2 as B2
    check("совпало с правилом лёгкого разбора Z2",
          abs(B2.snap_line(line)[0] - got["t"]) < 1e-9,
          f"{B2.snap_line(line)[0]} против {got['t']}")


def test_report_counts_a_smoke_day_as_not_folded():
    """Сутки, свёрнутые смоуком, отчёт называет частичными, а не готовыми.

    Проверяется не сама классификация (её держит `test_fold`), а её
    ДОРОГА до отчёта: величина может считаться верно и не попадать в
    показ — ровно так колонка просадки турнира встала прочерками.
    """
    days = ["2026-08-20"]
    syms = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    root, old = _setup(days, syms, per_min=6)
    later = time.time() + 10 * 86400
    try:
        F.fold_day(days[0], syms=syms[:1], jobs=1, log=lambda m: None,
                   now=later, kind="ladder")
        path = os.path.join(FL.STORE, "Z3-store.md")
        got = FL.write_report(path=path, store=FL.STORE,
                              log=lambda m: None)
        txt = open(path, encoding="utf-8").read()
        check("частичные сутки посчитаны числом", got["partial"] == 1,
              str(got))
        check("и в свёрнутые полностью не попали",
              "свёрнуто полностью 0" in txt, txt[-400:])
        check("сутки помечены в самой таблице", "⚠ узкие" in txt,
              txt[-600:])
        check("названо, скольких имён не хватает",
              "не хватает 2" in txt, txt[-600:])
        check("и они считаются несвёрнутыми",
              got["missing"] == 1, str(got))

        F.fold_day(days[0], syms=syms, jobs=1, log=lambda m: None,
                   now=later, kind="ladder")
        got = FL.write_report(path=path, store=FL.STORE,
                              log=lambda m: None)
        txt = open(path, encoding="utf-8").read()
        check("после полной свёртки пометки нет",
              got["partial"] == 0 and "⚠ узкие" not in txt, str(got))
    finally:
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_hourly_reading_equals_the_whole_day_bit_for_bit():
    """Почасовое чтение обязано совпасть с посуточным ТОЧНО.

    Правка сделана не ради скорости: первый полный проход убило ядро
    (код 137) на сто первом имени — сутки снимков BTC с лесенкой в 200
    уровней это около 3.9 ГБ питоновских объектов. Но правка памяти,
    меняющая числа, была бы другой мерой, поэтому здесь сравнение с
    образцом — посуточным счётом на тех же файлах.

    Фикстура несёт ровно те два случая, ради которых нужен перенос:
    последний снимок часа заезжает за его границу (момент наблюдения —
    позднее из двух времён), и принт стоит ПОСЛЕ него, то есть
    объясняет убыль уже в первой паре следующего часа.
    """
    day = "2026-08-20"
    sym = "AAAUSDT"
    root = tempfile.mkdtemp()
    old = (F.BOOK, F.TRADES)
    try:
        F.BOOK = os.path.join(root, "book")
        F.TRADES = os.path.join(root, "trades")
        # per_min=30, а не меньше: минута закрывается только при
        # `MIN_PAIRS` парах, и на редкой сетке обе стороны сравнения
        # вышли бы пустыми — равенство выполнилось бы, ничего не
        # проверив (первый прогон этой проверки так и сделал).
        # Снос БОЛЬШЕ шага сетки (3 с против 2): при сносе ровно в шаг
        # заехавший снимок встаёт на границу и в общем порядке
        # оказывается ПЕРЕД первой записью следующего часа — то есть
        # там же, где и без переноса, и подделка переноса теста не
        # роняет. Проверка, которую нельзя провалить, не защищает.
        # per_min=60 (шаг 1 с), а не реже: пара с разрывом больше
        # `MAX_DT = 3 с` наблюдением не является вовсе, и на шаге 2 с
        # пара через границу часа выпадала — вместе с ней выпадали и
        # перенесённые принты, то есть подделка переноса ленты теста не
        # роняла.
        write_ladder_rec(root, [sym], [day], hours=(10, 11, 12),
                         per_min=60, spill=3.0)
        hours, t0 = F.hours_of_day(day)
        snaps, trs = [], []
        for h in hours:
            snaps += FL._read(os.path.join(F.BOOK, sym), h, FL.snap_full)
            trs += FL._read(os.path.join(F.TRADES, sym), h,
                            __import__("bookfeat2").trade_line_px)
        snaps.sort(key=lambda r: r["t"])
        trs.sort(key=lambda r: r[0])
        check("фикстура несёт перенос через границу часа",
              any(r["t"] >= t0 + 11 * 3600 for r in snaps[:len(snaps) // 3]),
              "ни один снимок не заехал за свой час")
        want = FL.fold_symbol(snaps, trs, t0)
        got = FL.symbol_day(sym, day)

        def same(a, b):
            # NaN — это «меры нет» (ход середины нулевой, делить не на
            # что), и таких минут здесь 36. Голое сравнение списков
            # объявило бы их расхождением, потому что NaN не равен сам
            # себе, — и любая будущая правка памяти выглядела бы
            # изменившей числа.
            if len(a) != len(b):
                return False
            for x, y in zip(a, b):
                if x is None or y is None:
                    if x is not y:
                        return False
                elif x != y and not (x != x and y != y):
                    return False
            return True

        bad = [f for f in LD.FIELDS if not same(want[f], got[f])]
        check("почасовой счёт равен посуточному бит в бит", not bad,
              f"разошлись поля: {bad[:4]}")
        live = [m for m in range(len(want["pairs"]))
                if want["pairs"][m] is not None]
        check("и это не пустое равенство", len(live) > 100, str(len(live)))
    finally:
        (F.BOOK, F.TRADES) = old
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (
        test_ladder_folds_into_its_own_store_and_leaves_the_book_alone,
        test_flows_reach_the_minute_grid_with_real_numbers,
        test_trades_are_matched_to_their_own_interval,
        test_interval_boundary_is_strict_on_the_left,
        test_symbols_can_be_given_by_a_repeated_key,
        test_report_counts_a_smoke_day_as_not_folded,
        test_observation_moment_is_the_later_of_two_times,
        test_hourly_reading_equals_the_whole_day_bit_for_bit,
    )
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
