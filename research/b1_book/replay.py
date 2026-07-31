#!/usr/bin/env python3
"""
Прогон записанного потока через тот же детектор.

Зачем
-----

Вопрос владельца: «можно ли прошлые сделки переделать под новую логику,
чтобы понять, как бы они отработали». Можно — и это же превращает
правку правила из «поменяли и ждём неделю» в «поменяли и через минуту
знаем, что было бы».

Главное здесь — **не заводить второй расчёт**. Детектор, уровни,
геометрия сделки и сводка берутся ровно те же, что работают живьём;
меняется только источник — файлы вместо вебсокета. Вторая реализация
однажды разошлась бы с первой, и тогда воспроизведение показывало бы
одно, а сборщик делал другое, причём обе стороны выглядели бы
правдоподобно.

Две руки на одних данных
------------------------

Прогон делается дважды по одному и тому же куску записи: прежней
геометрией стопа (доля шума) и новой (за экстремум и накопление).
Разницу тогда можно отнести к геометрии, а не к другому куску рынка.

Чего воспроизвести НЕЛЬЗЯ и почему
----------------------------------

Правило по стакану считает «крупный» относительно **всех** видимых
уровней. До сих пор в файл писалась лесенка в десять уровней — по
такому обрезку правило дало бы правдоподобные, но неверные числа,
поэтому на старых записях оно отключается явно, а не считается молча.
С записей, сделанных после исправления (в файл идёт вся книга),
воспроизводится и оно.

    .venv/bin/python research/b1_book/replay.py --hours 12
    .venv/bin/python research/b1_book/replay.py --hours 12 --symbols FILUSDT
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)

import paper                                              # noqa: E402
import signals as S                                       # noqa: E402
from book import Book                                     # noqa: E402
from store import read_hour                               # noqa: E402

MIN_LEVELS_FOR_BOOK = 20      # меньше — лесенка обрезана, правило врало бы


def hours_back(n):
    now = datetime.now(timezone.utc).replace(minute=0, second=0,
                                             microsecond=0)
    return [(now - timedelta(hours=i)).strftime("%Y-%m-%d-%H")
            for i in range(n, -1, -1)]


def load(root, kind, sym, hours):
    rows = []
    d = os.path.join(root, kind, sym)
    for h in hours:
        rows += read_hour(d, h)
    return rows


def book_at(rows):
    """Снимки книги по секундам: `{секунда: (биды, аски, уровней)}`."""
    out = {}
    for r in rows:
        t = r.get("t")
        b, a = r.get("b") or [], r.get("a") or []
        if t is None or not b or not a:
            continue
        out[int(t)] = ({float(p): float(q) for p, q in b},
                       {float(p): float(q) for p, q in a},
                       min(len(b), len(a)))
    return out


def replay_symbol(root, sym, hours, structural, use_book):
    """Прогнать один символ. Возвращает `(сделки, сколько секунд)`."""
    S.STRUCTURAL_STOP = structural
    trades = load(root, "trades", sym, hours)
    if not trades:
        return [], 0, 0
    trades.sort(key=lambda t: t.get("ts", 0))
    books = book_at(load(root, "book", sym, hours)) if use_book else {}
    thin = sum(1 for v in books.values() if v[2] < MIN_LEVELS_FOR_BOOK)
    if books and thin > len(books) * 0.5:
        books = {}                     # лесенка обрезана — молча не считаем

    sig = S.Signals([sym])
    live = sig.by[sym]
    t0 = int(trades[0]["ts"] // 1000)
    t1 = int(trades[-1]["ts"] // 1000)
    i, done = 0, []
    for sec in range(t0, t1 + 1):
        while i < len(trades) and trades[i]["ts"] // 1000 <= sec:
            live.on_trade(trades[i])
            i += 1
        bk = None
        if sec in books:
            b = Book(sym)
            b.bids, b.asks = books[sec][0], books[sec][1]
            bk = {sym: b}
        _, closed = sig.tick(float(sec), bk)
        done += closed
    # Незакрытые в конец окна не идут в статистику: выхода у них не было.
    return done, t1 - t0, len(books)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--hours", type=int, default=12)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    hh = hours_back(a.hours)
    root = a.out
    syms = ([s.strip() for s in a.symbols.split(",") if s.strip()]
            or sorted(os.listdir(os.path.join(root, "trades"))))
    print(f"окно: {hh[0]} … {hh[-1]} ({a.hours} ч), символов {len(syms)}")

    res = {}
    for name, structural in (("прежняя (доля шума)", False),
                             ("новая (за структуру)", True)):
        allt, secs, nb = [], 0, 0
        for s in syms:
            try:
                d, sec, b = replay_symbol(root, s, hh, structural, True)
            except Exception as e:                        # noqa: BLE001
                print(f"  {s}: пропущен ({type(e).__name__}: {e})")
                continue
            allt += d
            secs += sec
            nb += b
            if d:
                print(f"  {name:22} {s:14} сделок {len(d)}")
        res[name] = {"trades": allt, "stats": paper.summary(allt),
                     "by_rule": paper.by_rule(allt), "seconds": secs,
                     "book_seconds": nb}

    print()
    hdr = f"{'геометрия':24} {'сделок':>7} {'побед':>7} {'безуб.':>7} " \
          f"{'ожидание':>10} {'в риске':>9} {'стоп':>8}"
    print(hdr)
    for name, r in res.items():
        st = r["stats"]
        if not st:
            print(f"{name:24} {'—':>7}  сделок не было")
            continue
        print(f"{name:24} {st['trades']:>7} {st['win_rate']*100:>6.0f}% "
              f"{st['break_even']*100:>6.0f}% "
              f"{st['expectancy_bp']:>+9.1f} б.п. {st['expectancy_r']:>+8.2f} "
              f"{st['stop_bp_median']:>7.1f}")
    bs = res["новая (за структуру)"]["book_seconds"]
    print(f"\nсекунд книги с полной лесенкой: {bs}"
          + ("" if bs else "  — правило по стакану не воспроизводилось: "
                           "в старых записях лесенка обрезана до десяти "
                           "уровней"))
    tag = f"-{a.tag}" if a.tag else ""
    p = os.path.join(root, f"replay{tag}.json")
    os.makedirs(root, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != "trades"}
                   | {"trades": v["trades"][:500]}
                   for k, v in res.items()}, f, ensure_ascii=False, indent=1)
    print(f"записано: {p}")


if __name__ == "__main__":
    main()
