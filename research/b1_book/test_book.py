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
    """Страница обязана быть самодостаточной: сервер стоит в интернете."""
    import web
    check("внешних ссылок на странице нет",
          "http://" not in web.PAGE and "https://" not in web.PAGE)
    check("данные тянутся с самого сборщика", "/state?k=" in web.PAGE)


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
        if S.absorption_live(buy[:i + 1], sell[:i + 1], close[:i + 1],
                             60, 5.0, 0.5, 0.3, -1):
            live_hits.append(i)
    check(f"пакетный нашёл {len(batch)}, живой {len(live_hits)}",
          bool(batch) and bool(live_hits), f"{sorted(batch)[:5]} {live_hits[:5]}")
    if batch and live_hits:
        # Пакетный склеивает соседние срабатывания в одно; живой видит
        # каждое. Сверяется первое — оно и есть момент решения.
        check(f"первое срабатывание совпало ({min(live_hits)} против "
              f"{min(batch)})", abs(min(live_hits) - min(batch)) <= 1,
              f"{min(live_hits)} {min(batch)}")


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
    print("живой детектор")
    test_live_detector_agrees_with_batch()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
