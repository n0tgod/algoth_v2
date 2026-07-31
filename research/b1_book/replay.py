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


def stub(rec, sec, why):
    """Запись об отвергнутом входе — «сделки нет и вот почему».

    Полей сделки у неё нет вовсе (ни стопа, ни цели: их и не построили),
    поэтому в статистику она не попадает по тем же правилам, что и
    оборванная перезапуском, — `paper.finished` пропускает всё, кроме
    наступивших исходов.
    """
    return {"id": f"{rec.get('sym', '')}-{int(sec)}-нет",
            "ver": S.RULES_VERSION, "t": float(sec), "sym": rec.get("sym"),
            "long": bool(rec.get("long")), "side": -1 if rec.get("long") else 1,
            "entry": float(rec["entry"]), "stop": None, "target": None,
            "level": rec.get("level"), "kind": rec.get("kind"),
            "rule": rec.get("rule") or "лента", "state": "не открыта",
            "why": why, "stop_bp": None, "tgt_bp": None, "rr": None,
            "held": None, "pnl_bp": None, "r": None, "exit": None,
            "closed_at": None}


def replay_seeded(root, sym, hours):
    """Те же входы, что были, но геометрия новая.

    Вопрос владельца: почему нельзя пересчитать уже случившиеся сделки
    по новым правилам с той же точкой входа. Можно, и это отвечает на
    другой вопрос, чем полный прогон. Полный прогон ищет входы заново —
    там меняются и они, и стоп, и разделить вклад нельзя. Здесь входы
    берутся из записи **как есть**, а стоп и цель считаются по новой
    геометрии на состоянии рынка того момента. Разница тогда целиком
    приходится на геометрию.

    Пересчитываются ОБА конца сделки — и стоп, и цель. Цель по новым
    правилам берётся не ближайшая, а ближайшая из оправдывающих риск,
    поэтому у той же точки входа она обычно дальше прежней.

    Сделка, которая по новым правилам не открылась бы вовсе (стоп
    расширился, и ни один уровень впереди не оправдывает риск),
    возвращается **записью с причиной отказа**, а не просто считается.
    Владелец смотрел на конкретную сделку ARBUSDT, новая геометрия её не
    взяла — и на графике она просто исчезла, что неотличимо от «данные
    потерялись». Отказ есть результат правила и обязан быть виден.

    К каждой пересчитанной сделке прикладывается то, чем она была в
    записи, — иначе сравнивать пришлось бы глазами по двум таблицам.
    """
    S.STRUCTURAL_STOP = True
    opens = [r for r in load(root, "signals", sym, hours)
             if r.get("ev") == "open" and r.get("entry")]
    if not opens:
        return [], [], 0
    trades = load(root, "trades", sym, hours)
    if not trades:
        return [], [], 0
    trades.sort(key=lambda t: t.get("ts", 0))
    seed = {}
    for r in opens:
        seed.setdefault(int(r.get("t") or 0), r)

    sig = S.Signals([sym])
    live = sig.by[sym]
    t0 = int(trades[0]["ts"] // 1000)
    t1 = int(trades[-1]["ts"] // 1000)
    i, done, created, refused = 0, [], [], []
    for sec in range(t0, t1 + 1):
        while i < len(trades) and trades[i]["ts"] // 1000 <= sec:
            live.on_trade(trades[i])
            i += 1
        live.close_second(sec)
        done += live.update_open(float(sec))
        live.refresh_levels(float(sec))
        r = seed.pop(sec, None)
        if r is None or live.open:
            continue
        px, kinds, noise, _ = live.levels
        if len(px) == 0 or not (noise == noise) or noise <= 0:
            refused.append(stub(r, sec, "уровней или шума ещё нет"))
            continue
        tr = live.make_trade(float(sec), bool(r.get("long")),
                             float(r.get("level") or r["entry"]),
                             r.get("kind") or "полка", float(r["entry"]),
                             noise, px, r.get("rule") or "лента")
        if tr is None:
            refused.append(stub(r, sec, live.last_refusal or "правило не берёт"))
        else:
            tr["was"] = {"stop_bp": r.get("stop_bp"), "rr": r.get("rr"),
                         "tgt_bp": r.get("tgt_bp"), "ver": r.get("ver"),
                         "id": r.get("id")}
            created.append(tr)
    # Не закрывшиеся до конца окна — тоже результат: геометрия у них
    # построена, исхода ещё нет. Помечаются отдельно и в статистику не
    # идут, но на графике видны — иначе свежий вход выглядит пропажей.
    ids = {t.get("id") for t in done}
    for t in created:
        if t.get("id") not in ids:
            t["state"] = "не закрылась в окне"
    return done, created, refused


def compare(seeded, was_close):
    """Сопоставить пересчитанные сделки с их записанными исходами.

    Вынесено из `main` не для красоты: логика внутри печати ничем не
    проверяется, а сравнение «было / стало» — это то самое, ради чего
    прогон и делается.
    """
    from statistics import median
    rows, d = [], []
    for t in sorted(seeded, key=lambda x: x.get("t") or 0):
        o = was_close.get((t.get("was") or {}).get("id"))
        if o is None or o.get("pnl_bp") is None or t.get("pnl_bp") is None:
            continue
        rows.append({
            "sym": t.get("sym", ""), "side": "лонг" if t["long"] else "шорт",
            "was_stop": o.get("stop_bp"), "was_tgt": o.get("tgt_bp") or "—",
            "was_state": o.get("state"), "was_pnl": float(o["pnl_bp"]),
            "stop": t["stop_bp"], "tgt": t.get("tgt_bp", "—"),
            "state": t["state"], "pnl": float(t["pnl_bp"])})
        d.append(rows[-1]["pnl"] - rows[-1]["was_pnl"])
    if not rows:
        return [], 0, 0.0
    return rows, sum(1 for x in d if x > 0), float(median(d))


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
    # Третья рука: те же входы, новая геометрия.
    seeded, made, refused = [], [], []
    for s in syms:
        try:
            d, cr, rf = replay_seeded(root, s, hh)
        except Exception as e:                            # noqa: BLE001
            print(f"  {s}: те же входы пропущены ({type(e).__name__}: {e})")
            continue
        seeded += d
        made += cr
        refused += rf
    st = paper.summary(seeded)
    if st:
        print(f"{'те же входы, новая геометрия':24} {st['trades']:>7} "
              f"{st['win_rate']*100:>6.0f}% {st['break_even']*100:>6.0f}% "
              f"{st['expectancy_bp']:>+9.1f} б.п. {st['expectancy_r']:>+8.2f} "
              f"{st['stop_bp_median']:>7.1f}")
        st_now = sorted(t["stop_bp"] for t in made)
        print(f"{'':24} открыто {len(made)}, отвергнуто новой геометрией "
              f"{len(refused)}; медианный стоп "
              f"{st_now[len(st_now)//2] if st_now else '—'} б.п.")
    else:
        print(f"{'те же входы, новая геометрия':24} открыто {len(made)}, "
              f"отвергнуто {len(refused)}, закрытых в окне нет")
    res["те же входы, новая геометрия"] = {
        "trades": seeded, "stats": st, "by_rule": paper.by_rule(seeded),
        "seconds": 0, "book_seconds": 0, "made": len(made),
        "refused": len(refused),
        # Причины отказов — по ним видно, ЧТО именно правило не берёт,
        # а не только сколько. Первые двадцать: список бывает длинным.
        "refused_why": [r.get("why") for r in refused[:20]]}

    # Посделочное сопоставление: что было в записи и что вышло бы.
    was_close = {}
    for s_ in syms:
        for r in load(root, "signals", s_, hh):
            if r.get("ev") == "close" and r.get("id"):
                was_close[r["id"]] = r
    rows, better, med = compare(seeded, was_close)
    if rows:
        print(f"\nте же входы, посделочно (первые 15 из {len(rows)}):")
        print(f"  {'монета':10} {'сторона':6} | "
              f"{'было: стоп':>10} {'цель':>6} {'итог':>7} {'б.п.':>8} | "
              f"{'стало: стоп':>11} {'цель':>6} {'итог':>7} {'б.п.':>8}")
        for r in rows[:15]:
            print(f"  {r['sym']:10} {r['side']:6} | "
                  f"{r['was_stop']:>10} {r['was_tgt']:>6} {r['was_state']:>7} "
                  f"{r['was_pnl']:>+8.1f} | "
                  f"{r['stop']:>11} {r['tgt']:>6} {r['state']:>7} "
                  f"{r['pnl']:>+8.1f}")
        print(f"  сопоставлено {len(rows)}, стало лучше у {better}, "
              f"медиана изменения {med:+.1f} б.п.")
    else:
        print("\nпосделочно сопоставить нечего: в окне нет сделок, у которых "
              "есть и запись прежнего исхода, и пересчитанный")

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
