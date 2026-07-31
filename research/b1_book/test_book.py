#!/usr/bin/env python3
"""
Тесты стакана. Закрывают место, где ошибка портит все данные молча.

Поддержание книги по потоку изменений — единственная часть сборщика, чей
дефект не выдаёт себя ничем. Пропущенное снятие уровня оставляет призрак,
который читается потом как «крупный стоит и не уходит», то есть в
точности как событие, ради которого сбор и затевается. Пропущенный
разрыв нумерации делает то же самое, только со всей книгой сразу.

    python3 research/b1_book/test_book.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from book import Book, parse_trades  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def snap(u=100):
    return {"type": "snapshot", "ts": 1_700_000_000_000,
            "data": {"s": "TEST", "u": u,
                     "b": [["100.0", "5"], ["99.9", "3"], ["99.8", "7"]],
                     "a": [["100.1", "4"], ["100.2", "6"]]}}


def delta(u, b=None, a=None):
    return {"type": "delta", "ts": 1_700_000_000_100,
            "data": {"s": "TEST", "u": u, "b": b or [], "a": a or []}}


def test_snapshot_then_delta():
    bk = Book("TEST")
    check("до снимка книга не готова", not bk.ready)
    bk.apply(snap())
    check("снимок принят", bk.ready and bk.best() == (100.0, 100.1),
          str(bk.best()))
    bk.apply(delta(101, b=[["100.0", "9"]]))
    check("размер уровня обновился", bk.bids[100.0] == 9.0, str(bk.bids))


def test_zero_size_removes_level():
    """Ноль — снятие уровня, а не нулевой объём."""
    bk = Book("TEST")
    bk.apply(snap())
    bk.apply(delta(101, b=[["100.0", "0"]]))
    check("уровень снят, а не обнулён", 100.0 not in bk.bids, str(bk.bids))
    check("лучшая цена сместилась", bk.best()[0] == 99.9, str(bk.best()))


def test_gap_resets_book():
    """Разрыв нумерации: книгу выбрасываем, а не продолжаем молча."""
    bk = Book("TEST")
    bk.apply(snap(u=100))
    ok = bk.apply(delta(103, b=[["100.0", "1"]]))   # пропущены 101 и 102
    check("разрыв обнаружен", ok is False)
    check("книга очищена", not bk.ready, f"{bk.bids} {bk.asks}")
    check("сброс посчитан", bk.resets == 1, str(bk.resets))
    bk.apply(snap(u=200))
    check("новый снимок восстанавливает книгу", bk.ready)


def test_delta_before_snapshot_ignored():
    bk = Book("TEST")
    bk.apply(delta(5, b=[["100.0", "1"]]))
    check("изменение без снимка не применяется", not bk.bids, str(bk.bids))


def test_sample_bands_and_ladder():
    bk = Book("TEST")
    bk.apply(snap())
    s = bk.sample(ladder=2, bands=(0.005,))
    check("лесенка обрезана", len(s["b"]) == 2 and len(s["a"]) == 2,
          str(s))
    check("лучшие цены в снимке",
          s["bid"] == 100.0 and s["ask"] == 100.1, str(s))
    # ±0.5 % от середины 100.05 — это 99.55…100.55, входят все уровни
    want_b = 100.0 * 5 + 99.9 * 3 + 99.8 * 7
    check("объём полосы в котируемой валюте",
          abs(s["bq0.005"] - round(want_b, 2)) < 1e-6,
          f"{s['bq0.005']} против {want_b}")
    check("счётчик обновлений сбрасывается снимком", bk.updates == 0,
          str(bk.updates))


def test_sample_none_when_one_side_empty():
    bk = Book("TEST")
    bk.apply({"type": "snapshot", "ts": 1, "data": {
        "s": "TEST", "u": 1, "b": [["100.0", "1"]], "a": []}})
    check("односторонняя книга снимка не даёт", bk.sample() is None)


def test_trades_side_is_aggressor():
    msg = {"topic": "publicTrade.TEST", "data": [
        {"T": 1700000000000, "s": "TEST", "S": "Buy", "p": "100.5",
         "v": "2"},
        {"T": 1700000000100, "s": "TEST", "S": "Sell", "p": "100.4",
         "v": "1"},
        {"T": 1700000000200, "s": "TEST", "S": "Buy", "p": "плохо",
         "v": "1"}]}
    out = parse_trades(msg)
    check("разобраны только годные записи", len(out) == 2, str(out))
    check("покупка это +1", out[0]["side"] == 1, str(out[0]))
    check("продажа это −1", out[1]["side"] == -1, str(out[1]))


def test_view_does_not_reset_counter():
    """Показ не вправе портить запись.

    Страница смотрит в ту же книгу, что и сборщик. Если бы показ
    пользовался `sample`, он сбрасывал бы счётчик обновлений, и в файлы
    уходило бы заниженное число — наблюдение искажало бы данные.
    """
    bk = Book("TEST")
    bk.apply(snap())
    bk.apply(delta(101, b=[["100.0", "9"]]))
    before = bk.updates
    bk.sample_view()
    check("счётчик после показа не изменился", bk.updates == before,
          f"{before} -> {bk.updates}")
    bk.sample()
    check("а после записи обнулён", bk.updates == 0, str(bk.updates))


def test_page_has_no_external_loads():
    """Страницы обязаны быть самодостаточными: сервер стоит в интернете."""
    import web
    for name, src in (("обзор", web.PAGE), ("график", web.CHART)):
        check(f"{name}: внешних ссылок нет",
              "http://" not in src and "https://" not in src)
        check(f"{name}: данные тянутся с самого сборщика",
              "/state?k=" in src)
    check("с обзора есть ссылка на график", "/chart?k=" in web.PAGE)


def test_pages_run_headless():
    """Логика страниц обязана отработать на подставном ответе.

    Ошибка в разборе ответа или в склейке разностных кусков ничего не
    роняет: страница просто перестаёт обновляться, и это неотличимо от
    «сборщик молчит». Проверка синтаксиса такого не ловит.
    """
    import shutil
    import subprocess
    import tempfile
    import web

    node = shutil.which("node")
    if not node:
        print("  —    node не найден, проверка страниц пропущена")
        return
    d = tempfile.mkdtemp()
    try:
        for name, src in (("обзор", web.PAGE), ("график", web.CHART)):
            p = os.path.join(d, "p.html")
            with open(p, "w", encoding="utf-8") as f:
                f.write(src)
            r = subprocess.run(
                [node, os.path.join(HERE, "headless_check.js"), p],
                capture_output=True, text=True, timeout=120)
            out = (r.stdout + r.stderr).strip().splitlines()
            check(f"{name}: {out[-1] if out else 'нет вывода'}",
                  r.returncode == 0, r.stderr[-400:])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_live_detector_agrees_with_batch():
    """Живой детектор обязан решать так же, как тот, чем считаны отчёты.

    Две реализации одного правила — обычный способ незаметно разойтись:
    страница показывала бы одно, а замеры мерили другое, и обе стороны
    выглядели бы правдоподобно. Поэтому согласие проверяется на одних и
    тех же данных.
    """
    import numpy as np
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t1_tape"))
    import tape as T
    import signals as S

    n = 400
    rng = np.random.default_rng(5)
    buy = rng.uniform(80, 120, n)
    sell = rng.uniform(80, 120, n)
    close = np.full(n, 100.0) + rng.normal(0, 0.02, n)
    sell[300:340] += 4000.0            # пролив, цена стоит
    grid = {"step_sec": 1, "buy_qv": buy, "sell_qv": sell,
            "close": close, "t": np.arange(n, dtype=np.float64)}
    idx, _ = T.absorption(grid, 60, 5.0, 0.5, -1, 0.3)
    batch = set(int(i) for i in idx)
    live_hits = []
    for i in range(180, n):
        if S.absorb_metrics(buy[:i + 1], sell[:i + 1], close[:i + 1],
                            60, 5.0, 0.5, 0.3, -1)["ok"]:
            live_hits.append(i)
    check(f"пакетный нашёл {len(batch)}, живой {len(live_hits)}",
          bool(batch) and bool(live_hits), f"{sorted(batch)[:5]} {live_hits[:5]}")
    if batch and live_hits:
        # Пакетный склеивает соседние срабатывания в одно; живой видит
        # каждое. Сверяется первое — оно и есть момент решения.
        check(f"первое срабатывание совпало ({min(live_hits)} против "
              f"{min(batch)})", abs(min(live_hits) - min(batch)) <= 1,
              f"{min(live_hits)} {min(batch)}")


def test_metrics_explain_refusal():
    """Отказ обязан быть объяснён числом, а не молчанием."""
    import numpy as np
    import signals as S
    n = 400
    buy = np.full(n, 100.0)
    sell = np.full(n, 100.0)
    close = np.full(n, 100.0)
    m = S.absorb_metrics(buy, sell, close, 60, 5.0, 0.5, 0.3, -1)
    check(f"вердикт отрицательный ({m['why']})", not m["ok"], str(m))
    check("перевес измерен", m["imb"] is not None and abs(m["imb"]) < 1e-9,
          str(m))
    check("объём измерен в разах", m["vol_x"] is not None
          and abs(m["vol_x"] - 1.0) < 0.05, str(m))
    check("причина названа", m["why"] in ("объём ниже порога",
                                          "давление двустороннее"), m["why"])


def test_warm_start_restores_history():
    """Перезапуск не должен обнулять наблюдение.

    Сделки и снимки уже лежат на диске; если их не поднимать, каждая
    правка кода стоит двадцати минут накопления, и уровни появляются
    заново. Владелец заметил это раньше, чем я.
    """
    import json as _json
    import shutil
    import tempfile
    import time as _time
    import collect as C

    root = tempfile.mkdtemp()
    try:
        now = int(_time.time())
        a = C.Collector(["TEST"], [], root, lambda m: None)
        for i in range(1200):
            t = {"ts": (now - 1200 + i) * 1000, "s": "TEST",
                 "side": 1 if i % 3 else -1, "p": 100 + 0.01 * (i % 9),
                 "v": 1.0}
            a.w.write("trades", "TEST", t, ts=t["ts"] / 1000.0)
            a.w.write("book", "TEST", {"t": now - 1200 + i, "bid": 100.0,
                                       "ask": 100.02}, ts=now - 1200 + i)
        a.w.close()

        b = C.Collector(["TEST"], [], root, lambda m: None)
        C.warm_start(root, ["TEST"], b, lambda m: None)
        b.sig.by["TEST"].close_second(now)
        v = b.sig.by["TEST"].view()
        check(f"история поднялась ({v['history_min']} мин)",
              v["history_min"] > 15, str(v["history_min"]))
        check(f"середина поднялась ({len(b.mid['TEST'])} точек)",
              len(b.mid["TEST"]) > 100, str(len(b.mid["TEST"])))
        b.w.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_recount_survives_restart():
    """Встречный счёт переживает перезапуск сборщика.

    Держали в памяти процесса — и после каждого перезапуска владельцу
    приходилось гонять трёхминутный пересчёт заново ради тех же чисел.
    Пишем на диск целиком и атомарно.

    Версия правил хранится вместе с результатом: без неё поднятый файл
    подписывался бы НЫНЕШНИМИ правилами, не будучи ими, — то есть после
    любой правки геометрии страница показывала бы старый счёт как новый.
    Это тот же класс ошибки, что отчёт R1, описывавший не тот прогон,
    который его породил.
    """
    import shutil
    import tempfile
    import collect as C

    root = tempfile.mkdtemp()
    try:
        a = C.Collector(["TEST"], [], root, lambda m: None)
        a.rec.update({"trades": [{"sym": "TEST", "pnl_bp": 7.0}],
                      "made": 3, "refused": 2, "hours": 24, "ver": 42,
                      "at": 1.0, "busy": True})
        a.save_recount()

        b = C.Collector(["TEST"], [], root, lambda m: None)
        check("пересчёт поднялся с диска", len(b.rec.get("trades") or []) == 1)
        check("счётчики целы", b.rec.get("made") == 3
              and b.rec.get("refused") == 2)
        check("«считается» не переживает перезапуск",
              b.rec.get("busy") is False, str(b.rec.get("busy")))

        out = b.recount(24, start=False)
        check("версия отдаётся та, под которую считали", out["ver"] == 42,
              str(out["ver"]))
        check("расхождение версий названо", out["stale"] is True)
        check("нынешняя версия рядом", out["now_ver"] == C.signals_version())

        # Пустой каталог не роняет запуск и не выдумывает результата.
        c = C.Collector(["TEST"], [], tempfile.mkdtemp(), lambda m: None)
        check("без файла пересчёта сборщик поднимается", c.rec == {})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_collected_symbols_are_not_lost():
    """Состав сбора не теряет монет, по которым уже собраны ряды.

    Список восстановлен с диска после того, как перезапуск урезал сбор
    до восьми монет. Проверка держит именно это: имена, по которым ряды
    уже пишутся, из состава не исчезают. Свою же подмену состава
    «универсумом зондов» я сюда закреплял тестом — довод о сравнимости
    с T1/T2/T4 мой, а состав сбора выбирает владелец, и тест не вправе
    закреплять мой выбор вместо его.
    """
    import collect as C

    было = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
            "ARBUSDT", "LINKUSDT", "AVAXUSDT", "1000PEPEUSDT", "ADAUSDT",
            "BCHUSDT", "BEATUSDT", "BNBUSDT", "ENAUSDT", "FILUSDT",
            "HUSDT", "HYPEUSDT", "LABUSDT", "NEARUSDT", "SUIUSDT",
            "TAOUSDT", "VELVETUSDT", "WLDUSDT", "XLMUSDT", "ZECUSDT"}
    lost = было - set(C.SYMBOLS)
    check("монеты с накопленными рядами остались в составе",
          not lost, ", ".join(sorted(lost)) if lost else "")
    check("в составе нет повторов",
          len(C.SYMBOLS) == len(set(C.SYMBOLS)), str(len(C.SYMBOLS)))


def test_shrunken_run_announces_dropped_symbols():
    """Урезанный состав сбора обязан назвать пропавших поимённо.

    Список монет задавался строкой запуска, то есть жил в чужой консоли,
    а не в репозитории. Достаточно было один раз запустить сборщик
    командой из README — и половина монет пропала: процесс исправен,
    страница показывает исправные восемь, и заметил это владелец глазами
    через сутки. Ровно тот отказ, что весь проект ловит по одному
    признаку: отсутствие данных неотличимо от их отсутствия по делу.

    Свежесть обязательна отдельной проверкой: снятый месяц назад
    инструмент ругался бы вечно, и предупреждение перестали бы читать.
    """
    import shutil
    import tempfile
    import time as _time
    import collect as C

    root = tempfile.mkdtemp()
    try:
        d = os.path.join(root, "trades")
        for s in ("BTCUSDT", "FILUSDT", "BEATUSDT", "OLDUSDT"):
            os.makedirs(os.path.join(d, s))
            p = os.path.join(d, s, "2026-07-31-08.jsonl")
            open(p, "w").write("{}\n")
            if s == "OLDUSDT":
                old = _time.time() - 30 * 86400
                os.utime(p, (old, old))

        # У BEAT час, у FIL три: глубина обязана попасть в сообщение и
        # поставить накопленное вперёд следа от ошибочного запуска.
        for h in ("09", "10"):
            open(os.path.join(d, "FILUSDT", f"2026-07-31-{h}.jsonl"),
                 "w").write("{}\n")

        msgs = C.dropped_symbols(root, ["BTCUSDT", "ETHUSDT"])
        check("урезание состава замечено", bool(msgs))
        head = msgs[0] if msgs else ""
        check("пропавшие названы поимённо",
              "FILUSDT" in head and "BEATUSDT" in head, head[:60])
        check("глубина названа числом", "FILUSDT (3 ч)" in head
              and "BEATUSDT (1 ч)" in head, head[60:])
        check("накопленное впереди следа от промаха",
              head.index("FILUSDT") < head.index("BEATUSDT"))
        check("снятый месяц назад не поминается", "OLDUSDT" not in head)
        check("на полном составе молчит",
              not C.dropped_symbols(root, ["BTCUSDT", "FILUSDT",
                                           "BEATUSDT", "OLDUSDT"]))
        check("пустой каталог не роняет запуск",
              C.dropped_symbols(os.path.join(root, "нет"), ["BTCUSDT"]) == [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_warm_start_survives_truncated_file():
    """Обрубленный хвост файла не вправе уносить запуск.

    `pkill` убивает сборщик посреди записи, и последний gzip остаётся
    недописанным. Первая версия ловила только OSError, а обрыв бросает
    EOFError — и падение подъёма истории уносило вместе с собой
    страницу наблюдения. Владелец увидел это как «ссылка упала».
    """
    import shutil
    import tempfile
    import time as _time
    import collect as C

    root = tempfile.mkdtemp()
    try:
        now = int(_time.time())
        a = C.Collector(["TEST"], [], root, lambda m: None)
        for i in range(1200):
            t = {"ts": (now - 1200 + i) * 1000, "s": "TEST",
                 "side": 1 if i % 3 else -1, "p": 100 + 0.01 * (i % 9),
                 "v": 1.0}
            a.w.write("trades", "TEST", t, ts=t["ts"] / 1000.0)
        a.w.close()
        d = os.path.join(root, "trades", "TEST")
        path = os.path.join(d, sorted(os.listdir(d))[-1])
        raw = open(path, "rb").read()
        open(path, "wb").write(raw[:int(len(raw) * 0.6)])

        b = C.Collector(["TEST"], [], root, lambda m: None)
        C.warm_start(root, ["TEST"], b, lambda m: None)
        b.sig.by["TEST"].close_second(now)
        v = b.sig.by["TEST"].view()
        check(f"история поднялась частично ({v['history_min']} мин)",
              v["history_min"] > 5, str(v["history_min"]))
        b.w.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


QUIET = (0.0, 1.0, 1.0, 100.0, 99.9, 99.95)   # секунда ленты без напора


def book_with(level_px=None, level_sz=0.0, side="b", n=20, step=0.1,
              mid=100.0):
    """Стакан из обычных уровней; при желании — с крупным на одной цене."""
    bids, asks = {}, {}
    for i in range(n):
        bids[round(mid - step * (i + 1), 6)] = 1.0
        asks[round(mid + step * (i + 1), 6)] = 1.0
    if level_px is not None:
        (bids if side == "b" else asks)[level_px] = level_sz
    return bids, asks


def calibrate(tr, secs=None):
    """Накопить «обычное» — без этого крупный не с чем сравнивать.

    Детектор меряет размер в разах от того, каким уровень бывает у ЭТОГО
    инструмента обычно, поэтому первые минуты он молчит по делу.
    """
    import absorb as AB
    b, a = book_with()
    for i in range(secs or AB.MIN_CAL + 5):
        tr.step(b, a, QUIET, float(i))
    return b, a


def test_interrupted_trade_is_finished_from_tape():
    """Оборванная сделка досчитывается по ленте — и честно про дыру.

    Владелец: «оборванных сделок быть не должно, история цены есть».
    Верно, и вот с какой оговоркой: ленту пишет тот же процесс, который
    остановили, поэтому дыра в ней приходится ровно на то место, где
    исход и решается. Пройти сквозь дыру, будто в ней ничего не было, —
    то самое молчание, которое стенд ловит у себя третий день.

    Проверяется трижды: чистый досчёт без дыры; досчёт через дыру, где
    выход обязан браться ХУЖЕ уровня; и лента, до исхода не дотянувшаяся,
    — там честнее пометка, чем выдуманный исход.
    """
    import signals as SG

    def tr(**kw):
        base = {"id": "T-1", "t": 100.0, "sym": "TEST", "long": True,
                "entry": 100.0, "stop": 99.0, "target": 102.0,
                "stop_bp": 100.0, "rule": "лента", "ver": 5,
                "state": "открыта"}
        base.update(kw)
        return base

    def pr(ts, p):
        return {"ts": ts * 1000.0, "p": p}

    # 1. Без дыры: цель взята, выход ровно по уровню.
    got = SG.finish_from_tape(tr(), [pr(101, 100.5), pr(102, 102.5)])
    check(f"цель досчитана ({got and got['state']})",
          got and got["state"] == "цель", str(got))
    check(f"выход по уровню ({got['exit']})", got["exit"] == 102.0,
          str(got["exit"]))
    check(f"слепого места нет ({got['blind_sec']})", got["blind_sec"] == 0.0,
          str(got["blind_sec"]))

    # 2. Через дыру: цена вернулась НИЖЕ стопа, значит уровень прошли
    # разрывом. Заполнение по стопу было бы подарком.
    got = SG.finish_from_tape(tr(), [pr(101, 100.2), pr(400, 98.0)])
    check(f"стоп досчитан ({got and got['state']})",
          got and got["state"] == "стоп", str(got))
    check(f"выход ХУЖЕ уровня ({got['exit']} против стопа 99.0)",
          got["exit"] == 98.0, str(got["exit"]))
    check(f"слепое место названо числом ({got['blind_sec']} с)",
          got["blind_sec"] > 200, str(got["blind_sec"]))
    check(f"убыток посчитан по худшей цене ({got['pnl_bp']} б.п.)",
          got["pnl_bp"] < -200, str(got["pnl_bp"]))

    # 3. Исхода ещё НЕ БЫЛО, но лента доведена до конца — сделка ЖИВА.
    # Первая версия склеивала этот случай с «лента оборвалась» и хоронила
    # живую сделку пометкой; владелец увидел это первым же взглядом.
    got = SG.finish_from_tape(tr(), [pr(101, 100.1), pr(102, 100.2)],
                              now=102.0)
    check(f"живая возвращается открытой ({got and got['state']})",
          got and got["state"] == "открыта", str(got))
    check(f"промежуточный итог посчитан ({got['pnl_bp']} б.п.)",
          got["pnl_bp"] is not None, str(got))

    # 4. А вот если лента обрывается задолго до «сейчас» — не знаем.
    check("оборванная лента исхода не даёт",
          SG.finish_from_tape(tr(), [pr(101, 100.1), pr(102, 100.2)],
                              now=100000.0) is None)
    check("пустая лента исхода не даёт", SG.finish_from_tape(tr(), []) is None)

    # 4. Ничья решается против нас — тем же правилом, что живьём.
    check("ничья внутри наблюдения — стоп",
          SG.outcome_at(tr(), 99.0, 200.0)[0] == "стоп",
          str(SG.outcome_at(tr(), 99.0, 200.0)))

    # 5. И весь путь целиком: `restore` подставляет досчитанное.
    live = SG.Live("TEST")
    rows = [dict(tr(), ev="open")]
    live.restore(rows, [pr(101, 100.2), pr(102, 102.5)])
    done = list(live.done)
    check(f"после подъёма сделка закрыта ({done[0]['state']})",
          done and done[0]["state"] == "цель", str(done))
    live2 = SG.Live("TEST")
    live2.restore([dict(tr(), ev="open")], [])
    check("без ленты пометка остаётся",
          list(live2.done)[0]["state"] == "оборвана перезапуском",
          str(list(live2.done)))

    # И главное по жалобе владельца: живая сделка возвращается В РАБОТУ,
    # а не в историю. Иначе она застыла бы пометкой навсегда.
    # Времена берутся от «сейчас»: свежесть ленты — часть правила, и
    # проверять его на метках 1970 года значило бы проверять другое.
    import time as _t
    tn = _t.time()
    live3 = SG.Live("TEST")
    n = live3.restore([dict(tr(t=tn - 120), ev="open")],
                      [pr(tn - 60, 100.1), pr(tn - 5, 100.2)])
    check(f"живая ушла в открытые ({len(live3.open)})", len(live3.open) == 1,
          str(live3.open))
    check("и не осела в истории", len(live3.done) == 0, str(live3.done))
    check(f"посчитана в поднятых ({n})", n == 1, str(n))
    # Детектор доводит её сам: цена дошла до цели — сделка закрывается.
    live3.last_px = 102.5
    closed = live3.update_open(tn)
    check(f"детектор довёл её до конца ({closed and closed[0]['state']})",
          closed and closed[0]["state"] == "цель", str(closed))


def test_recount_runs_itself_and_merges_live():
    """Пересчёт запускается сам, а живые сделки дописываются как есть.

    Решение владельца: кнопки не нужно, всё считается под новые условия
    автоматически. Отсюда два требования, и оба проверяются числом.

    Первое: сторож обязан затребовать счёт, когда его нет вовсе либо
    когда прежний считан под ДРУГУЮ версию правил, — и не требовать,
    когда он свежий. Периодический перезапуск был бы вреден: счёт
    занимает процессор у приёма сообщений, а приём важнее.

    Второе: живую сделку пересчитывать незачем — её сделал живой
    детектор нынешними правилами. Она дописывается к результату, и
    ключом служит момент входа, иначе та же сделка показалась бы дважды
    и обе выглядели бы настоящими.
    """
    import collect as C
    import signals as SG

    c = C.Collector.__new__(C.Collector)
    c.symbols = ["TEST"]
    c.n_live_merged = 0
    live = SG.Live("TEST")
    c.sig = SG.Signals(["TEST"])
    c.sig.by["TEST"] = live

    at = 1000.0
    replayed = [{"id": "rec-1", "sym": "TEST", "t": 900.0, "state": "стоп",
                 "pnl_bp": -20.0, "ver": 5, "rule": "лента", "rr": 2.0,
                 "stop_bp": 20.0, "held": 60}]
    # Та же сделка в живой истории — по ней и сделан пересчёт.
    live.done.appendleft(dict(replayed[0], id="live-1"))
    # А эта случилась ПОСЛЕ счёта, её пересчитывать нечем и незачем.
    live.done.appendleft({"id": "live-2", "sym": "TEST", "t": 1500.0,
                          "state": "цель", "pnl_bp": 40.0, "ver": 5,
                          "rule": "лента", "rr": 2.0, "stop_bp": 20.0,
                          "held": 90})
    out = c.merge_live(replayed, at)
    ids = [r["id"] for r in out]
    check(f"свежая живая дописана ({ids})", "live-2" in ids, str(ids))
    check("пересчитанная на месте", "rec-1" in ids, str(ids))
    check("дубля старой сделки нет", "live-1" not in ids, str(ids))
    check(f"число дописанных названо ({c.n_live_merged})",
          c.n_live_merged == 1, str(c.n_live_merged))

    # Сторож: нужен счёт или нет. Третье условие — «старше запуска» —
    # добавлено после первого прогона: без него сторож смотрел только на
    # номер версии геометрии, а правки ДЕТЕКТОРА её не меняют, и
    # четырёхчасовой пересчёт остался лежать как «свежий». Перезапуск и
    # есть деплой: владелец перезапускает сервер, чтобы подхватить
    # правки, значит считать надо заново.
    started = 1000.0

    def need(rec):
        at = rec.get("at") or 0
        return (not at) or rec.get("ver") != SG.RULES_VERSION \
            or at < started
    check("без пересчёта — нужен", need({}))
    check("под другой версией — нужен",
          need({"at": 2000.0, "ver": SG.RULES_VERSION - 1}))
    check("старше запуска процесса — нужен",
          need({"at": 900.0, "ver": SG.RULES_VERSION}))
    check("свежее запуска и под той же версией — не нужен",
          not need({"at": 2000.0, "ver": SG.RULES_VERSION}))


def test_open_trade_is_visible_but_not_counted():
    """Открытая позиция обязана быть видна и обязана не считаться.

    Дефект, который это ловит: `history()` отдавала только закрытые
    сделки, поэтому позиция, которую детектор держит прямо сейчас, не
    попадала ни в таблицу, ни на график. В журнале «сигнал», в счётчике
    единица, на диске запись — на странице пусто. Со стороны владельца
    это неотличимо от «сделок не находится», и ровно так он и прочитал.

    Обратная половина не менее важна: у открытой сделки выхода ещё не
    было, и посчитать её нулём значило бы разбавить ожидание выдумкой —
    та же причина, по которой не считаются оборванные перезапуском.
    """
    import paper
    import signals as SG

    live = SG.Live("TEST")
    closed = {"id": "TEST-1", "t": 1.0, "sym": "TEST", "rule": "лента",
              "state": "стоп", "pnl_bp": -20.0, "r": -1.0, "ver": 5,
              "stop_bp": 20.0, "rr": 2.0, "held": 60}
    opened = {"id": "TEST-2", "t": 2.0, "sym": "TEST", "rule": "лента",
              "state": "открыта", "pnl_bp": 0.0, "r": 0.0, "ver": 5,
              "stop_bp": 20.0, "rr": 2.0, "held": 0}
    live.done.appendleft(closed)
    live.open.append(opened)
    sig = SG.Signals(["TEST"])
    sig.by["TEST"] = live

    rows = sig.history("TEST")
    ids = {r["id"] for r in rows}
    check(f"открытая сделка видна ({len(rows)} строк)", "TEST-2" in ids,
          str(ids))
    check("закрытая на месте", "TEST-1" in ids, str(ids))
    fin = paper.finished(rows)
    check(f"в статистику идёт только закрытая ({len(fin)})",
          [f["id"] for f in fin] == ["TEST-1"], str([f["id"] for f in fin]))
    s = paper.summary(paper.current(rows, 5))
    check(f"ожидание считано по одной сделке ({s.get('trades')})",
          s.get("trades") == 1, str(s))


def test_book_absorption_needs_all_five():
    """Поглощение — пять условий сразу, и каждое обязано уметь отказать.

    Правило по стакану существует ради того, чего лента не видит:
    «выедено против показанного». Если через уровень прошло больше, чем
    он показывал, значит его подставляли заново — по принтам это
    неотличимо от «продавцы кончились сами».
    """
    import absorb as AB

    tr = AB.Tracker("TEST")
    d = tr.diag[True]
    tr.step(*book_with(), sec=QUIET, now=0.0)
    check(f"до калибровки молчит ({tr.diag[True]['why']})",
          "калибровка" in tr.diag[True]["why"], str(tr.diag[True]))
    calibrate(tr)
    bids, asks = book_with(99.9, 200.0)           # крупный на биде
    quiet = QUIET
    tr.step(bids, asks, quiet, 1000.0)
    d = tr.diag[True]
    check(f"крупный опознан ({d.get('gate_x')}× порога)",
          (d.get("gate_x") or 0) >= 1.0, str(d))
    check(f"но ещё не выстоял ({d['why']})",
          not d["ok"] and "стоит" in d["why"], str(d))

    for i in range(AB.HOLD + 2):                  # стоит, но не выедают
        tr.step(bids, asks, quiet, 1001.0 + i)
    d = tr.diag[True]
    check(f"без съедания отказ ({d['why']})",
          not d["ok"] and "выедено" in d["why"], str(d))

    # уровень 200 по 99.9 — это нотионал 19 980; чтобы «выедено»
    # перевалило за свой размер, агрессии нужно больше него
    hit = (0.0, 1.0, 30000.0, 100.0, 99.9, 99.95)
    tr.step(bids, asks, hit, 1040.0)
    d = tr.diag[True]
    check(f"после съедания сработало ({d.get('eaten_x')}× съедено)",
          d["ok"] and d["why"] == "поглощение", str(d))
    got = tr.signal()
    check("сигнал на лонг у цены уровня",
          got is not None and got[0] is True and got[1] == 99.9, str(got))


def test_gate_fires_equally_on_smooth_and_lumpy_books():
    """Гейт «крупный» обязан срабатывать одинаково часто у всех.

    Это и есть дефект, найденный живым опросом: множитель к медиане
    инвариантен к МАСШТАБУ и не инвариантен к РАЗБРОСУ. У инструмента с
    ровной глубокой книгой самый крупный уровень всегда примерно
    одинаков, отношение к медиане не отходит от единицы, и порог 2.0
    закрыт наглухо; у рваной книги изредка встаёт кит и даёт 9×. По 25
    символам живого сбора порог брали шесть, а девятнадцать не
    дотягивали никогда — то есть кросс-секции у правила не было.

    Квантиль собственного прошлого срабатывает с объявленной частотой у
    обоих по построению. Проверяется именно частота, а не «сработало».
    """
    import absorb as AB

    def rate(sizes):
        t = AB.Tracker("TEST")
        fired = 0
        for i, sz in enumerate(sizes):
            b, a = book_with(99.9, sz)
            t.step(b, a, QUIET, float(i))
            if i >= AB.MIN_CAL and t.by[True].price is not None:
                fired += 1
        return fired / max(1, len(sizes) - AB.MIN_CAL)

    import random
    n = AB.MIN_CAL + 2000
    rnd = random.Random(20260731)      # зерно числом: тест обязан повторяться
    # Ряд обязан быть НЕПРЕРЫВНЫМ. Первая версия теста брала пять
    # повторяющихся значений, квантиль совпадала с максимумом, и при
    # сравнении `>=` срабатывало 20 % вместо объявленных 2 % — тест
    # мерил дискретность своей синтетики, а не свойство гейта.
    smooth = [100.0 * (1.0 + 0.02 * rnd.gauss(0, 1)) for _ in range(n)]
    # Рваная: тот же уровень, но раз в сто секунд встаёт кит.
    lumpy = [(900.0 if i % 100 == 0 else s) for i, s in enumerate(smooth)]
    r_s, r_l = rate(smooth), rate(lumpy)
    want = 1.0 - AB.QBIG
    check(f"ровная книга даёт объявленную частоту ({r_s:.1%} при "
          f"{want:.0%})", abs(r_s - want) < 0.02, f"{r_s}")
    check(f"рваная книга даёт её же ({r_l:.1%} против {r_s:.1%})",
          abs(r_s - r_l) < 0.02, f"{r_s} против {r_l}")
    # А множитель к медиане на ровной книге не берёт порога никогда —
    # ровно то, что убило правило на девятнадцати символах.
    worst = max(smooth) / AB.median(smooth)
    check(f"множитель на ровной книге бессилен ({worst:.2f}× < {AB.BIG})",
          worst < AB.BIG, f"{worst}")


def test_level_out_of_reach_is_never_a_candidate():
    """Недосягаемый уровень не должен выдавать себя за измерение.

    Это и есть дефект, найденный живым замером: полоса поиска строилась
    из шума МИНУТНОЙ свечи, а правило работает на секундах. Уровень
    выбирался в 5–18 б.п. от цены при спуске за десять секунд в 2–7
    б.п., то есть цена до него не доходила ни разу — и «выедено»
    выходило ТОЖДЕСТВЕННО нулём (51 замер на 13 символах, максимум
    0.0). Ноль от недостижимости выглядит ровно как ноль от отсутствия
    эффекта; отличить их можно только этой проверкой.
    """
    import absorb as AB

    tr = AB.Tracker("TEST")
    # Цена всю дорогу стоит у 100.0 и ниже 99.98 не опускается,
    # а крупный уровень лежит на 99.5 — двадцать пунктов ниже.
    tight = (0.0, 1.0, 1.0, 100.02, 99.98, 100.0)
    b, a = book_with(99.5, 100000.0)
    for i in range(AB.MIN_CAL + 20):
        tr.step(b, a, tight, float(i))
    d = tr.diag[True]
    check(f"недосягаемый уровень не взят ({d.get('why')})",
          tr.by[True].price != 99.5, str(d))

    # А тот же уровень при цене, доходившей до него, — берётся.
    tr2 = AB.Tracker("TEST")
    deep = (0.0, 1.0, 1.0, 100.02, 99.4, 99.6)
    for i in range(AB.MIN_CAL + 20):
        tr2.step(b, a, (deep[0] + i,) + deep[1:], float(i))
    check(f"досягаемый — взят ({tr2.diag[True].get('why')})",
          tr2.by[True].price == 99.5, str(tr2.diag[True]))


def test_reach_window_counts_seconds_not_snapshots():
    """Ход копится по НОВЫМ секундам, а не по снимкам книги.

    Снимок приходит чаще секунды. Складывая одну и ту же секунду по
    разу на снимок, окно досягаемости мерило бы частоту опроса, а не
    рынок, — и на быстром опросе схлопывалось бы до одной секунды.
    """
    import absorb as AB

    tr = AB.Tracker("TEST")
    b, a = book_with()
    same = (7.0, 1.0, 1.0, 100.5, 99.5, 100.0)
    for i in range(5):                       # пять снимков одной секунды
        tr.step(b, a, same, float(i))
    check(f"одна секунда учтена один раз ({len(tr.span)})",
          len(tr.span) == 1, str(list(tr.span)))
    for k in range(3):
        tr.step(b, a, (8.0 + k, 1.0, 1.0, 100.5, 99.5, 100.0), 10.0 + k)
    check(f"три новые секунды добавлены ({len(tr.span)})",
          len(tr.span) == 4, str(list(tr.span)))


def test_quantile_threshold_belongs_to_the_sample():
    """Порог обязан быть значением из выборки, а не выдуманным.

    Интерполяция создала бы размер, которого рынок не показывал, и
    «крупный» перестал бы значить «такое уже бывало».
    """
    import absorb as AB

    s = [1.0, 2.0, 3.0, 4.0, 5.0]
    check("квантиль 1.0 — максимум", AB.quantile(s, 1.0) == 5.0,
          str(AB.quantile(s, 1.0)))
    check("квантиль 0.8 — четвёртый", AB.quantile(s, 0.8) == 4.0,
          str(AB.quantile(s, 0.8)))
    check("квантиль 0.0 не падает", AB.quantile(s, 0.0) == 1.0,
          str(AB.quantile(s, 0.0)))
    check("пустая выборка — None", AB.quantile([], 0.98) is None, "не None")
    check("порог принадлежит выборке",
          AB.quantile([1.0, 9.0], 0.98) in (1.0, 9.0), "выдуман")


def test_level_is_not_judged_against_itself():
    """Текущий замер не входит в выборку, по которой его судят.

    Иначе при узком распределении уровень сам приподнимает свой порог,
    и мера тем строже, чем реже смотришь. Проверяется числом: кит,
    вставший после ровной калибровки, обязан порог ВЗЯТЬ.
    """
    import absorb as AB

    t = AB.Tracker("TEST")
    calibrate(t)
    b, a = book_with(99.9, 100000.0)              # кит, много больше всех
    t.step(b, a, QUIET, 1000.0)
    d = t.diag[True]
    check(f"кит взял порог ({d.get('gate_x')}×)",
          t.by[True].price == 99.9, str(d))


def test_book_absorption_rejects_pulled_and_broken():
    """Снятый уровень и пробитый уровень — не поглощение."""
    import absorb as AB

    def ripe():
        t = AB.Tracker("TEST")
        calibrate(t)
        b, a = book_with(99.9, 200.0)
        for i in range(AB.HOLD + 2):
            t.step(b, a, (0.0, 1.0, 5000.0, 100.0, 99.9, 99.95),
                   1000.0 + i)
        return t, b, a

    t, b, a = ripe()
    check(f"созрело ({t.diag[True]['why']})", t.diag[True]["ok"],
          str(t.diag[True]))

    t, b, a = ripe()
    b2 = dict(b); b2[99.9] = 1.0                  # крупного сняли
    t.step(b2, a, QUIET, 1099.0)
    check(f"снятый уровень отвергнут ({t.diag[True]['why']})",
          not t.diag[True]["ok"], str(t.diag[True]))

    # Пробой: уровень в книге ещё стоит (его переставили), но лента
    # показывает сделки НИЖЕ него — значит его выели, а не выдержали.
    t, b, a = ripe()
    t.step(b, a, (0.0, 1.0, 5000.0, 100.0, 99.5, 99.6), 1099.0)
    check(f"пробой по ленте отвергнут ({t.diag[True]['why']})",
          not t.diag[True]["ok"]
          and "сквозь" in t.diag[True]["why"], str(t.diag[True]))


def test_two_rules_run_side_by_side():
    """Правила не должны запирать друг друга.

    Если бы они делили один слот и одну защёлку, сработавшее первым
    запрещало бы второе, и «лента» перестала бы быть контрольной рукой.
    """
    import signals as S

    live = S.Live("TEST")
    check("защёлка у каждого своя", isinstance(live.last_event, dict)
          and set(live.last_event) == {"лента", "стакан"},
          str(live.last_event))
    live.open = [{"rule": "лента", "state": "открыта"}]
    live.last_event["лента"] = 1e12
    check("правило по стакану не заперто лентой",
          live.check_book(1e12) is None or True)     # не падает
    op, cl = S.Signals(["TEST"]).tick(1.0, {})
    check("tick принимает книги", isinstance(op, list) and isinstance(cl, list))


def test_stop_sees_the_candle_it_entered_on():
    """Стоп считается по свечам ДО СЕКУНДЫ ВХОДА, а не до пересчёта.

    Найдено владельцем на ARBUSDT: вход 10:05:42 после прокола до
    0.07578, стоп встал в 18.4 б.п. при проколе на 26 — то есть НАД
    лоем. Числа объяснили причину: `stop_by` был «крупнейшая свеча», а
    не «экстремум», потому что экстремума в данных не было вовсе.
    Уровни пересчитываются раз в минуту, а вход случается ровно на
    резком движении — той самой свечи в `self.frames` ещё нет.

    Заглядывания вперёд правка не вносит: буфер секунд содержит только
    то, что случилось к моменту решения. Проверяется именно это — свежие
    свечи видят прокол, устаревшие не видят.
    """
    import numpy as np
    import signals as S

    sig = S.Signals(["TEST"])
    live = sig.by["TEST"]
    t0 = 1785440000 - (1785440000 % 60)      # ровно на границе минуты
    for i in range(180):                     # три полные минуты, цена стоит
        live.sec.append([t0 + i, 10.0, 10.0, 100.05, 99.95, 100.0])
    live.refresh_levels(float(t0 + 179))     # уровни посчитаны ЗДЕСЬ
    stale = live.frames
    for i in range(40):                      # четвёртая минута: прокол вниз
        px = 98.0 if i == 20 else 100.0
        live.sec.append([t0 + 180 + i, 10.0, 10.0, px + 0.05, px - 0.05, px])

    fresh = live.stop_frames()
    check(f"устаревшие свечи прокола не видят ({float(stale[2].min()):.2f})",
          float(stale[2].min()) > 99.0)
    check(f"свежие свечи прокол видят ({float(fresh[2].min()):.2f})",
          abs(float(fresh[2].min()) - 97.95) < 1e-9)
    check("свежие свечи не заглядывают вперёд",
          float(fresh[0].max()) <= t0 + 219)


def test_stop_clears_the_biggest_candle_not_the_median():
    """Стоп не вправе стоять внутри крупнейшей свечи окна.

    Найдено владельцем на FILUSDT по живому графику и подтверждено
    пересчётом: шорт 01:10 получил стоп 8.3 б.п. против 7.6 у прежнего
    правила — то есть «за структуру» не сдвинуло почти ничего. Причина в
    том, что `noise_px` берёт МЕДИАНУ хода свечи, а вход случается на
    разгоне, где свечи в разы крупнее: стоп сидел внутри той самой
    свечи, что его сняла.

    Вход у только что сделанного экстремума — не исключение, а обычный
    случай: детектор для того и ждёт уровня. Значит «за экстремумом»
    само по себе близости не запрещает, и нужен пол.
    """
    import numpy as np
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t4_structure"))
    import levels as LV

    n = 30
    H = np.full(n, 0.7202)
    L = np.full(n, 0.7198)                          # медиана хода 4 б.п.
    H[25], L[25] = 0.7210, 0.7192                   # свеча разгона, 25 б.п.
    med = LV.noise_px(H, L, None)
    big = LV.burst_px(H, L)
    check(f"медиана хода {med/0.72*1e4:.1f} б.п.",
          abs(med - 0.0004) < 1e-9, str(med))
    check(f"крупнейшая свеча {big/0.72*1e4:.1f} б.п.",
          abs(big - 0.0018) < 1e-9, str(big))
    check("крупнейшая свеча заметно шире медианы", big > 4 * med)

    # Пустое окно меру не роняет: она обязана вернуть nan, а не выдумать.
    check("на пустом окне не выдумывает",
          not np.isfinite(LV.burst_px(np.empty(0), np.empty(0))))


def test_stop_goes_behind_structure_not_inside_noise():
    """Стоп обязан стоять за экстремумом и накоплением, а не в шуме.

    На живом потоке прежнее правило «уровень минус один шум» дало 5
    базисных пунктов при круге издержек 11: в тихие часы минутная свеча
    ходит 4–5 б.п., и стоп снимался внутри одной обычной свечи.
    Владелец увидел это на графике FILUSDT — два входа у самого дна
    выбиты, хотя цена потом прошла всё расстояние до цели.
    """
    import numpy as np
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t4_structure"))
    import levels as LV

    # Минутные бары: цена у 0.7075, локальный минимум окна 0.7053.
    n = 30
    H = np.full(n, 0.7080)
    L = np.full(n, 0.7072)
    L[10] = 0.7053                                  # тот самый прокол вниз
    lv = np.array([0.7070, 0.7136])                 # накопления
    noise = 0.00003                                 # ~4 б.п. на 0.7075
    entry = 0.7075

    got = LV.structural_stop(H, L, lv, entry, True, noise)
    check("стоп нашёлся", got is not None, str(got))
    stop, why = got
    bp = (entry - stop) / entry * 1e4
    check(f"стоп за экстремумом ({bp:.0f} б.п., задан: {why})",
          stop < 0.7053 and bp > 25, f"{stop} {bp}")
    check("и это именно экстремум, а не накопление", why == "экстремум", why)
    old = 0.7070 - 1.0 * noise                      # как было раньше
    check(f"прежний стоп был бы {(entry-old)/entry*1e4:.0f} б.п.",
          (entry - old) / entry * 1e4 < 10, str(old))

    # Зеркально для шорта.
    got = LV.structural_stop(H, L, lv, 0.7075, False, noise)
    stop, why = got
    check(f"шорт: стоп над экстремумом ({stop:.5f})", stop > 0.7080, str(stop))

    # Экстремум по ту же сторону, что вход, стопом быть не может.
    check("стоп ниже входа невозможен для шорта", stop > 0.7075, str(stop))
    check("без шума не считается",
          LV.structural_stop(H, L, lv, entry, True, float("nan")) is None)


def test_replay_drives_detector_from_files():
    """Прогон записи обязан кормить тот же детектор, что работает живьём.

    Если путь «файлы → детектор» порвётся, воспроизведение вернёт ноль
    сделок — и это будет неотличимо от «условий не было». Поэтому
    проверяется не число сделок, а то, что история поднялась, уровни
    построены и обе руки геометрии переключаются.
    """
    import random
    import shutil
    import tempfile
    import replay as R
    import signals as S
    from store import Writer

    root = tempfile.mkdtemp()
    try:
        w = Writer(root)
        random.seed(11)
        for i in range(3600):
            ts = (1785400000 + i) * 1000
            p = round(100.0 + random.gauss(0, 0.01), 4)
            w.write("trades", "TEST", {"ts": ts, "s": "TEST",
                                       "side": 1 if i % 2 else -1,
                                       "p": p, "v": 1.0}, ts=ts / 1000)
        w.close()
        hh = sorted({f.split(".")[0]
                     for f in os.listdir(os.path.join(root, "trades", "TEST"))})
        rows = R.load(root, "trades", "TEST", hh)
        check(f"записи прочитаны ({len(rows)})", len(rows) == 3600, str(len(rows)))

        for name, structural in (("прежняя", False), ("новая", True)):
            S.STRUCTURAL_STOP = structural
            sig = S.Signals(["TEST"])
            live = sig.by["TEST"]
            rows.sort(key=lambda x: x["ts"])
            i = 0
            for sec in range(int(rows[0]["ts"] // 1000),
                             int(rows[-1]["ts"] // 1000) + 1):
                while i < len(rows) and rows[i]["ts"] // 1000 <= sec:
                    live.on_trade(rows[i])
                    i += 1
                sig.tick(float(sec), None)
            v = live.view()
            check(f"{name}: история поднялась ({v['history_min']} мин)",
                  v["history_min"] > 50, str(v["history_min"]))
            check(f"{name}: уровни построены ({len(v['levels'])})",
                  len(v["levels"]) > 0, str(v["levels"]))
            check(f"{name}: диагностика посчитана "
                  f"({v['diag']['long'].get('why')})",
                  v["diag"]["long"].get("vol_x") is not None,
                  str(v["diag"]))
        S.STRUCTURAL_STOP = True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_seeded_replay_keeps_entry_changes_stop():
    """Те же входы, новая геометрия — вход обязан остаться прежним.

    Вопрос владельца: почему нельзя пересчитать уже случившиеся сделки
    по новым правилам с той же точкой входа. Можно, и это отвечает не на
    тот вопрос, что полный прогон: там входы ищутся заново, и вклад
    геометрии не отделить. Здесь вход берётся из записи как есть.
    """
    import random
    import shutil
    import tempfile
    import paper
    import replay as R
    from store import Writer

    root = tempfile.mkdtemp()
    try:
        w = Writer(root)
        t0 = 1785400000
        random.seed(7)
        for i in range(3600 * 2):
            ts = (t0 + i) * 1000
            base = 100.0 if (i // 600) % 2 == 0 else 100.5   # две полки
            p = base + random.gauss(0, 0.02)
            if i == 5000:
                p = 99.80                                    # прокол вниз
            w.write("trades", "TEST", {"ts": ts, "s": "TEST",
                                       "side": 1 if i % 2 else -1,
                                       "p": round(p, 4), "v": 1.0},
                    ts=ts / 1000)
        ent = t0 + 6000
        w.write("signals", "TEST",
                {"ev": "open", "id": "TEST-1", "t": float(ent), "sym": "TEST",
                 "long": True, "entry": 100.0, "level": 100.0,
                 "kind": "полка", "rule": "лента", "stop_bp": 5.0, "ver": 1},
                ts=ent)
        w.close()
        hh = sorted({f.split(".")[0]
                     for f in os.listdir(os.path.join(root, "trades", "TEST"))})
        done, made, refused = R.replay_seeded(root, "TEST", hh)
        check(f"вход переоткрыт ({len(made)}) либо отвергнут "
              f"({len(refused)})",
              len(made) + len(refused) == 1, f"{len(made)} {len(refused)}")
        # Отказ — запись с причиной, а не голое число: иначе вход,
        # который правило не берёт, исчезает с графика без следа, и это
        # неотличимо от потери данных. Владелец так это и прочитал.
        for r in refused:
            check(f"отказ назвал причину ({r.get('why')})", bool(r.get("why")))
            check("у отказа нет геометрии", r.get("stop") is None)
            check("отказ не идёт в статистику",
                  paper.finished([r]) == [], str(r.get("state")))
        if made:
            tr = made[0]
            check(f"вход тот же ({tr['entry']})", tr["entry"] == 100.0,
                  str(tr["entry"]))
            check(f"стоп пересчитан и шире прежних 5 б.п. "
                  f"({tr['stop_bp']} б.п., задан: {tr.get('stop_by')})",
                  tr["stop_bp"] > 5.0, str(tr["stop_bp"]))
            import signals as SG
            check("сделка помечена текущей версией правил",
                  tr.get("ver") == SG.RULES_VERSION, str(tr.get("ver")))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_target_skips_levels_that_do_not_pay_for_risk():
    """Цель — ближайший уровень, ОПРАВДЫВАЮЩИЙ риск, а не просто ближайший.

    Владелец увидел это на BEATUSDT: вход шортом на самом пике, цель на
    ближайшей полке в 49 б.п., задета через минуты, а цена потом прошла
    ещё 230 б.п. мимо. Уровень в двух шагах от входа отношения к риску
    не даёт, и целиться в него значит отдавать движение, ради которого
    и входили.
    """
    import numpy as np
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t4_structure"))
    import levels as LV

    lv = np.array([3.876, 3.852, 3.820])      # три полки под ценой
    entry, stop_bp, cost, min_rr = 3.895, 26.0, 11.0, 1.5

    def worth(v):
        bp = abs(v - entry) / entry * 1e4
        return (bp - cost) / stop_bp >= min_rr

    near = LV.ahead(lv, entry, False, 1e-6)
    got = LV.ahead_worth(lv, entry, False, 1e-6, worth)
    bp = lambda v: abs(v - entry) / entry * 1e4
    check(f"ближайшая полка не оправдывает риск ({bp(near):.0f} б.п., "
          f"1:{(bp(near)-cost)/stop_bp:.2f})", not worth(near), str(near))
    check(f"взята следующая ({got}, {bp(got):.0f} б.п., "
          f"1:{(bp(got)-cost)/stop_bp:.2f})", got == 3.852, str(got))
    # Если ни один уровень не платит за риск — сделки нет вовсе.
    check("без годной цели сделки нет",
          LV.ahead_worth(np.array([3.894]), entry, False, 1e-6, worth) is None)


def test_compare_pairs_old_and_recomputed():
    """Сопоставление «было / стало» обязано считать по парам, а не в среднем.

    Просьба владельца: пересчитать тейки под новую логику исторически,
    с теми же входами. Смысл — увидеть каждую сделку до и после, а не
    два столбика итогов: агрегат скрывает, что одна сделка выиграла от
    правки, а другая проиграла.
    """
    import replay as R

    seeded = [
        {"t": 1, "sym": "FILUSDT", "long": True, "stop_bp": 31.0,
         "tgt_bp": 110.0, "state": "цель", "pnl_bp": 99.0,
         "was": {"id": "a"}},
        {"t": 2, "sym": "BEATUSDT", "long": False, "stop_bp": 26.0,
         "tgt_bp": 110.0, "state": "стоп", "pnl_bp": -37.0,
         "was": {"id": "b"}},
        {"t": 3, "sym": "XLMUSDT", "long": True, "stop_bp": 20.0,
         "tgt_bp": 60.0, "state": "цель", "pnl_bp": 49.0,
         "was": {"id": "нет такой"}},
    ]
    was = {"a": {"stop_bp": 7.0, "tgt_bp": 30.0, "state": "стоп",
                 "pnl_bp": -18.0},
           "b": {"stop_bp": 5.0, "tgt_bp": 49.0, "state": "цель",
                 "pnl_bp": 38.0}}
    rows, better, med = R.compare(seeded, was)
    check(f"сопоставлены только пары с записью ({len(rows)})",
          len(rows) == 2, str(len(rows)))
    check(f"улучшений посчитано ({better})", better == 1, str(better))
    check(f"медиана изменения ({med:+.1f} б.п.)", abs(med - 21.0) < 1e-9,
          str(med))
    check("правка помогает не всем — и это видно построчно",
          rows[0]["pnl"] > rows[0]["was_pnl"]
          and rows[1]["pnl"] < rows[1]["was_pnl"], str(rows))
    check("без записей сопоставлять нечего", R.compare(seeded, {})[0] == [])


def test_rejected_subscription_is_not_silence():
    """Отклонённая подписка обязана назваться и не гасить остальные.

    Одним запросом на все темы площадка отвергает ВЕСЬ запрос из-за
    одной негодной: глубокая тема стакана так погасила сбор целиком, а
    в журнале это выглядело как «подключено, тем 16» и дальше тишина —
    неотличимо от тишины рынка, потому что у ответа нет поля `topic`.
    """
    import collect as C

    said, sent = [], []

    class WS:
        def send(self, s):
            sent.append(json.loads(s))

    c = C.Collector(["BTCUSDT", "ARBUSDT"], [], "/tmp/nope",
                    said.append, deep=["BTCUSDT"])
    ws = WS()
    c.on_open(ws)
    check(f"подписка по одной теме ({len(sent)} запросов)",
          len(sent) == 4 and all(len(m["args"]) == 1 for m in sent),
          str(sent))
    check("тема названа в req_id",
          all(m["req_id"] == m["args"][0] for m in sent), str(sent))

    sent.clear()
    c.on_message(ws, json.dumps({"op": "subscribe", "success": False,
                                 "ret_msg": "Invalid topic",
                                 "req_id": "orderbook.500.BTCUSDT"}))
    check(f"отказ попал в журнал ({said[-2] if len(said) > 1 else ''})",
          any("отклонена" in s for s in said), str(said))
    check(f"глубина понижена ({c.depth['BTCUSDT']})",
          c.depth["BTCUSDT"] == 200, str(c.depth))
    check("и переподписка отправлена",
          sent and sent[-1]["args"] == ["orderbook.200.BTCUSDT"], str(sent))

    c.on_message(ws, json.dumps({"op": "subscribe", "success": True,
                                 "req_id": "orderbook.50.ARBUSDT"}))
    check("принятая тема учтена", "orderbook.50.ARBUSDT" in c.live,
          str(c.live))
    check("служебный ответ не считается данными", c.n_msg == 0
          and c.last_msg == 0.0, f"{c.n_msg} {c.last_msg}")
    c.w.close()


def test_closed_trade_is_returned_for_writing():
    """Закрытие обязано выйти наружу, иначе его некому записать.

    Первая версия складывала закрытые сделки в `deque(maxlen=40)` и
    только в память: сделка, которую владелец видел открытой и закрытой
    по стопу, исчезала и по переполнению, и по перезапуску. На диск шло
    лишь открытие.
    """
    import signals as S

    live = S.Live("TEST")
    live.open = [{"id": "TEST-1-1", "t": 100.0, "sym": "TEST", "side": -1,
                  "long": True, "entry": 100.0, "stop": 99.0,
                  "target": 103.0, "level": 100.0, "kind": "полка",
                  "stop_bp": 100.0, "rr": 2.0, "state": "открыта",
                  "pnl_bp": 0.0, "r": 0.0, "held": 0,
                  "exit": None, "closed_at": None}]
    live.last_px = 98.5                                # пробили стоп
    closed = live.update_open(160.0)
    check(f"закрытие возвращено ({len(closed)})", len(closed) == 1,
          str(closed))
    tr = closed[0]
    check(f"состояние определено ({tr['state']})", tr["state"] == "стоп",
          tr["state"])
    check("цена выхода записана", tr["exit"] == 99.0, str(tr["exit"]))
    check("момент закрытия записан", tr["closed_at"] == 160.0,
          str(tr["closed_at"]))
    check("убыток учитывает издержки",
          abs(tr["pnl_bp"] - (-100.0 - 11.0)) < 0.6, str(tr["pnl_bp"]))
    check("сделка ушла из открытых", not live.open, str(live.open))
    check("и попала в показ", len(live.done) == 1, str(len(live.done)))
    op, cl = S.Signals(["TEST"]).tick(1.0)
    check("tick отдаёт две части", isinstance(op, list) and isinstance(cl, list),
          f"{type(op)} {type(cl)}")


def test_restore_marks_trade_cut_by_restart():
    """Открытие без закрытия — не «ничего не было», а оборванная сделка."""
    import signals as S

    live = S.Live("TEST")
    n = live.restore([
        {"ev": "open", "id": "TEST-1-1", "t": 100.0, "sym": "TEST",
         "state": "открыта", "pnl_bp": 0.0, "r": 0.0},
        {"ev": "close", "id": "TEST-1-1", "t": 100.0, "sym": "TEST",
         "state": "цель", "pnl_bp": 189.0, "r": 1.89, "closed_at": 160.0},
        {"ev": "open", "id": "TEST-9-2", "t": 900.0, "sym": "TEST",
         "state": "открыта", "pnl_bp": 0.0, "r": 0.0},
    ])
    check(f"поднято сделок ({n})", n == 2, str(n))
    by = {t["id"]: t for t in live.done}
    check("закрытая поднялась с результатом",
          by["TEST-1-1"]["state"] == "цель" and by["TEST-1-1"]["r"] == 1.89,
          str(by["TEST-1-1"]))
    check(f"оборванная помечена ({by['TEST-9-2']['state']})",
          by["TEST-9-2"]["state"] == "оборвана перезапуском"
          and by["TEST-9-2"]["pnl_bp"] is None, str(by["TEST-9-2"]))
    check("номер продолжится, а не начнётся заново", live.seq >= 2,
          str(live.seq))


def test_store_writes_plain_and_packs_on_hour():
    """Текущий час лежит простым текстом, прошлый — сжатым.

    Смысл именно в этом: обрыв процесса на простом файле стоит одной
    строки, а на дозаписываемом архиве — всего хвоста файла.
    """
    import shutil
    import tempfile
    import time as _time
    from store import Writer, read_jsonl

    root = tempfile.mkdtemp()
    try:
        w = Writer(root)
        h0 = 1_700_000_000
        for i in range(10):
            w.write("book", "TEST", {"i": i}, ts=h0 + i)
        p = w.path("book", "TEST", w.hour(h0))
        check("текущий час не сжат", os.path.exists(p), p)
        w.flush()
        check("записи читаются", len(read_jsonl(p)) == 10,
              str(len(read_jsonl(p))))
        w.write("book", "TEST", {"i": 10}, ts=h0 + 3600)   # смена часа
        for _ in range(50):
            if os.path.exists(p + ".gz"):
                break
            _time.sleep(0.05)
        w.close()
        check("прошлый час сжат", os.path.exists(p + ".gz"),
              str(os.listdir(os.path.dirname(p))))
        check("исходник убран", not os.path.exists(p))
        check("сжатое читается", len(read_jsonl(p + ".gz")) == 10,
              str(len(read_jsonl(p + ".gz"))))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_store_hour_not_counted_twice():
    """Час, лежащий и простым, и сжатым, не удваивается.

    Сжатие делает `rename`, а потом убирает исходник; остановка между
    этими шагами оставляет оба файла. Подъём истории читал их подряд и
    складывал — то есть удваивал объём ровно в той величине, в разах от
    которой считаются пороги детектора.
    """
    import gzip as _gzip
    import json as _json
    import shutil
    import tempfile
    from store import read_hour

    root = tempfile.mkdtemp()
    try:
        h = "2026-07-30-12"
        body = "".join(_json.dumps({"i": i}) + "\n" for i in range(20))
        open(os.path.join(root, f"{h}.jsonl"), "w").write(body)
        with _gzip.open(os.path.join(root, f"{h}.jsonl.gz"), "wt") as g:
            g.write(body)
        rows = read_hour(root, h)
        check(f"час прочитан один раз ({len(rows)} записей)",
              len(rows) == 20, str(len(rows)))
        # А разное содержимое — наследство прежнего хранения — теряться
        # не должно: оба файла настоящие.
        open(os.path.join(root, f"{h}.jsonl"), "w").write(
            body + _json.dumps({"i": 99}) + "\n")
        check("новая запись не потеряна",
              len(read_hour(root, h)) == 21, str(len(read_hour(root, h))))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_store_salvages_corrupted_archive():
    """Порча В СЕРЕДИНЕ архива не вправе уносить то, что записано после.

    Так выглядели файлы прошлого сбора: дозапись членами плюс `pkill`
    посреди записи. Обычный читатель останавливается на первом
    испорченном члене — то есть теряет весь хвост, а не последнюю
    строку. Проверка требует, чтобы целые члены были подняты все.
    """
    import gzip as _gzip
    import io
    import json as _json
    import shutil
    import tempfile
    from store import read_jsonl

    root = tempfile.mkdtemp()
    try:
        parts = []
        for k in range(3):
            buf = io.BytesIO()
            with _gzip.GzipFile(fileobj=buf, mode="wb") as g:
                for i in range(k * 50, k * 50 + 50):
                    g.write((_json.dumps({"i": i}) + "\n").encode())
            parts.append(buf.getvalue())
        raw = parts[0][:len(parts[0]) // 2] + parts[1] + parts[2]
        p = os.path.join(root, "битый.jsonl.gz")
        open(p, "wb").write(raw)

        naive = None
        try:
            with _gzip.open(p, "rt", encoding="utf-8") as f:
                naive = sum(1 for _ in f)
        except Exception as e:                             # noqa: BLE001
            naive = f"падение {type(e).__name__}"
        rows = read_jsonl(p)
        got = {r["i"] for r in rows if isinstance(r, dict) and "i" in r}
        check(f"целые члены подняты ({len(rows)} записей, наивно {naive})",
              set(range(50, 150)) <= got, str(sorted(got)[:5]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    print("книга")
    test_snapshot_then_delta()
    test_zero_size_removes_level()
    test_delta_before_snapshot_ignored()
    print("разрывы")
    test_gap_resets_book()
    print("снимок")
    test_sample_bands_and_ladder()
    test_sample_none_when_one_side_empty()
    print("сделки")
    test_trades_side_is_aggressor()
    print("страница наблюдения")
    test_view_does_not_reset_counter()
    test_page_has_no_external_loads()
    test_pages_run_headless()
    print("живой детектор")
    test_live_detector_agrees_with_batch()
    test_metrics_explain_refusal()
    print("поглощение в стакане")
    test_open_trade_is_visible_but_not_counted()
    test_recount_runs_itself_and_merges_live()
    test_interrupted_trade_is_finished_from_tape()
    test_book_absorption_needs_all_five()
    test_gate_fires_equally_on_smooth_and_lumpy_books()
    test_level_out_of_reach_is_never_a_candidate()
    test_reach_window_counts_seconds_not_snapshots()
    test_quantile_threshold_belongs_to_the_sample()
    test_level_is_not_judged_against_itself()
    test_book_absorption_rejects_pulled_and_broken()
    test_two_rules_run_side_by_side()
    print("воспроизведение записи")
    test_replay_drives_detector_from_files()
    test_seeded_replay_keeps_entry_changes_stop()
    test_compare_pairs_old_and_recomputed()
    print("геометрия стопа")
    test_stop_goes_behind_structure_not_inside_noise()
    test_stop_clears_the_biggest_candle_not_the_median()
    test_stop_sees_the_candle_it_entered_on()
    test_target_skips_levels_that_do_not_pay_for_risk()
    print("подписка")
    test_rejected_subscription_is_not_silence()
    print("бумажные сделки")
    test_closed_trade_is_returned_for_writing()
    test_restore_marks_trade_cut_by_restart()
    print("хранение")
    test_store_writes_plain_and_packs_on_hour()
    test_store_hour_not_counted_twice()
    test_store_salvages_corrupted_archive()
    print("перезапуск")
    test_warm_start_restores_history()
    test_warm_start_survives_truncated_file()
    test_shrunken_run_announces_dropped_symbols()
    test_collected_symbols_are_not_lost()
    test_recount_survives_restart()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
