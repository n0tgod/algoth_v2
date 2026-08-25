"""Сквозные тесты скрина по записи стакана.

Каждая дорога исполняется настоящими файлами записи: чтение часа,
свёртка в минуты, вчерашние нормы, события, замер ядром Z1, отчёт.
Урок S11: «тесты зелёные» значит ровно те дороги, которые тесты
ИСПОЛНЯЮТ.
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "z1_screen"))

import bookfeat2 as B                                     # noqa: E402
import probe as P                                         # noqa: E402
import screen as Z                                        # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "ПРОВАЛ ") + name
          + ("" if cond else f"  · {extra}"))
    if not cond:
        FAILED.append(name)


def write_rec(root, syms, days, hours=(10, 11), per_min=4, seed=1,
              event_rows=(), event_edge=0.004):
    """Записать поддельную запись ровно в том виде, что пишет сборщик."""
    rng = np.random.default_rng(seed)
    for day in days:
        d0 = int(datetime.strptime(day, "%Y-%m-%d")
                 .replace(tzinfo=timezone.utc).timestamp())
        for r, sym in enumerate(syms):
            for h in hours:
                bd = os.path.join(root, "book", sym)
                td = os.path.join(root, "trades", sym)
                os.makedirs(bd, exist_ok=True)
                os.makedirs(td, exist_ok=True)
                hour = (datetime.fromtimestamp(d0 + h * 3600, timezone.utc)
                        .strftime("%Y-%m-%d-%H"))
                px = 100.0 * float(np.exp(rng.normal(0, 0.01)))
                bl, tl = [], []
                for m in range(60):
                    for k in range(per_min):
                        t = d0 + h * 3600 + m * 60 + k * (60 // per_min)
                        px *= float(np.exp(rng.normal(0, 0.0004)))
                        # Событие: у отмеченных строк резко тонкий бид,
                        # а цена ПОСЛЕ входа идёт вверх.
                        ev = (r, day, h, m) in event_rows
                        bq = 200.0 if ev else 1000.0
                        # Ход идёт ЧЕРЕЗ минуту после события: вход —
                        # открытие СЛЕДУЮЩЕЙ минуты, поэтому скачок ни
                        # в самой минуте события, ни в минуте входа
                        # быть не должен — иначе он уже в цене входа и
                        # недостижим. Первые два прогона этого теста
                        # показали ровно это.
                        if (r, day, h, m - 2) in event_rows and k == 0:
                            px *= (1.0 + event_edge)
                        bid, ask = px * 0.9995, px * 1.0005
                        bl.append(json.dumps(
                            {"s": sym, "ts": int(t * 1000), "u": 1,
                             "bid": round(bid, 6), "ask": round(ask, 6),
                             "bid_sz": 3.0, "ask_sz": 4.0, "upd": 5,
                             "b": [[bid, 3.0]], "a": [[ask, 4.0]],
                             "reach_b": 50.0, "reach_a": 60.0,
                             "bq0.0005": 10.0, "aq0.0005": 11.0,
                             "bq0.001": 20.0, "aq0.001": 21.0,
                             "bq0.0025": bq, "aq0.0025": 1000.0,
                             "bq0.005": 2000.0, "aq0.005": 2100.0,
                             "t": round(t, 3)},
                            separators=(",", ":")))
                        tl.append(json.dumps(
                            {"ts": int(t * 1000), "s": sym,
                             "side": 1 if k % 2 else -1,
                             "p": round(px, 6), "v": 1.0},
                            separators=(",", ":")))
                with open(os.path.join(bd, hour + ".jsonl"), "w",
                          encoding="utf-8") as f:
                    f.write("\n".join(bl) + "\n")
                with open(os.path.join(td, hour + ".jsonl"), "w",
                          encoding="utf-8") as f:
                    f.write("\n".join(tl) + "\n")


def run(root, syms, days, tag="test"):
    old = (P.BOOK, P.TRADES, P.MIN_SNAPS, P.NORM_MIN_MIN, Z.PERMS,
           Z.MIN_EVENTS, Z.MIN_BUCKETS)
    P.BOOK = os.path.join(root, "book")
    P.TRADES = os.path.join(root, "trades")
    P.MIN_SNAPS, P.NORM_MIN_MIN = 3, 50
    Z.PERMS, Z.MIN_EVENTS, Z.MIN_BUCKETS = 20, 20, 5
    try:
        rc = P.main(["--start", days[0], "--end", days[-1],
                     "--symbols", ",".join(syms), "--tag", tag,
                     "--no-publish"])
    finally:
        (P.BOOK, P.TRADES, P.MIN_SNAPS, P.NORM_MIN_MIN, Z.PERMS,
         Z.MIN_EVENTS, Z.MIN_BUCKETS) = old
    return rc


def test_end_to_end_over_real_files():
    root = tempfile.mkdtemp()
    syms = [f"S{i:03d}USDT" for i in range(70)]
    days = ["2026-08-10", "2026-08-11"]
    try:
        # События сеются во ВТОРЫЕ сутки (у первых нет вчерашних норм):
        # у части имён бид истончается вчетверо, и цена после этого
        # идёт вверх. Без такого посева условия не срабатывают вовсе —
        # ровно так первый прогон этого теста и показал, что фикстура
        # ничего не проверяет.
        # События РАЗНЕСЕНЫ по именам во времени: если все имена
        # срабатывают в одну минуту, контроль исключает их всех и
        # сечение падает ниже порога — измерять становится нечем.
        # Первый прогон этого теста показал ровно это.
        ev = {(r, days[1], h, (r * 7 + k * 23) % 60)
              for r in range(0, 70, 2) for h in (10, 11)
              for k in range(2)}
        write_rec(root, syms, days, event_rows=ev)
        rc = run(root, syms, days)
        rep = os.path.join(P.OUT, "Z2-book-test.md")
        txt = open(rep, encoding="utf-8").read() if os.path.exists(rep) \
            else ""
        js = json.load(open(os.path.join(P.OUT, "z2-test.json"),
                            encoding="utf-8"))
        check("сквозной прогон дошёл до конца", rc == 0, str(rc))
        check("отчёт написан", len(txt) > 800, str(len(txt)))
        check("в отчёте есть проверка сноса и ширина записи",
              "снос по стороне" in txt and "Ширина записи" in txt,
              txt[:200])
        check("ячейки посчитаны", len(js["cells"]) > 0,
              str(len(js["cells"])))
        thin = [k for k in js["cells"] if k.startswith("бид истончился")]
        check("посеянное условие сработало", thin, str(list(js['cells'])[:3]))
        if thin:
            L = [js["cells"][k] for k in thin if k.split('|')[1] == '1']
            check("у лонгов посеянный ход виден превышением",
                  any(c["med_bp"] > 5 for c in L),
                  str([round(c["med_bp"], 1) for c in L]))
        # Первые сутки идут только в историю: норм у них нет.
        check("первые сутки не дали событий",
              all(int(k.split("|")[2]) > 0 for k in js["cells"]), "")

    finally:
        shutil.rmtree(root, ignore_errors=True)
        for t in ("Z2-book-test.md", "z2-test.json"):
            p = os.path.join(P.OUT, t)
            if os.path.exists(p):
                os.remove(p)


def test_drift_is_zero_with_the_mean_control():
    """Снос по стороне обязан быть около нуля — встроенная проверка меры.

    Z1 считал превышение над МЕДИАНОЙ сечения и получил снос +10.7 б.п.
    на любой лонг за четыре часа: медиана робастна, но она статистика,
    а не портфель. Равновзвешенная корзина сноса не имеет по
    построению — и это проверяется на записи БЕЗ посеянных событий,
    иначе посев сам двигает сечение.
    """
    root = tempfile.mkdtemp()
    syms = [f"N{i:03d}USDT" for i in range(70)]
    days = ["2026-08-10", "2026-08-11"]
    try:
        # События сеются (иначе ни одно условие не сработает и мерить
        # нечего), но БЕЗ хода цены: форварды остаются чистым шумом,
        # и снос обязан выйти нулевым.
        ev = {(r, days[1], h, (r * 5 + k * 19) % 60)
              for r in range(0, 70, 2) for h in (10, 11)
              for k in range(2)}
        write_rec(root, syms, days, seed=7, event_rows=ev,
                  event_edge=0.0)
        rc = run(root, syms, days, tag="drift")
        js = json.load(open(os.path.join(P.OUT, "z2-drift.json"),
                            encoding="utf-8"))
        d = js["drift"]
        check("прогон на шуме дошёл до конца", rc == 0, str(rc))
        check("снос по стороне около нуля при контроле средним",
              d and all(abs(v) < 3.0 for v in d.values()), str(d))
        check("снос сторон зеркален",
              all(abs(d.get(f"{h}|1", 0) + d.get(f"{h}|-1", 0)) < 1e-6
                  for h in P.HORIZONS if f"{h}|1" in d), str(d))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        for t in ("Z2-book-drift.md", "z2-drift.json"):
            p = os.path.join(P.OUT, t)
            if os.path.exists(p):
                os.remove(p)


def test_declared_horizons_are_the_measured_ones():
    """Горизонты замера обязаны совпасть с объявленными в Z2.

    Пилот объявил 1/5/15/60 минут, а измерены оказались 5/15/60/240:
    ядро брало горизонты из СВОЕЙ константы. Дефект не роняет прогон и
    ничем себя не выдаёт — таблица выглядит исправной, просто описывает
    другие горизонты. Тот же класс, что лаг интереса в шагах вместо
    времени: переиспользованный слой несёт свои константы.
    """
    root = tempfile.mkdtemp()
    syms = [f"H{i:03d}USDT" for i in range(70)]
    days = ["2026-08-10", "2026-08-11"]
    try:
        ev = {(r, days[1], h, (r * 5 + k * 19) % 60)
              for r in range(0, 70, 2) for h in (10, 11)
              for k in range(2)}
        write_rec(root, syms, days, seed=11, event_rows=ev,
                  event_edge=0.002)
        run(root, syms, days, tag="hz")
        js = json.load(open(os.path.join(P.OUT, "z2-hz.json"),
                            encoding="utf-8"))
        got = sorted({int(k.split("|")[2]) for k in js["cells"]})
        check("измерены ровно объявленные горизонты",
              got == sorted(P.HORIZONS), f"{got} против {sorted(P.HORIZONS)}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        for t in ("Z2-book-hz.md", "z2-hz.json"):
            p = os.path.join(P.OUT, t)
            if os.path.exists(p):
                os.remove(p)


def test_norms_wiring_uses_the_previous_day():
    """Нормы обязаны ДОЕХАТЬ до замера от вчерашних суток.

    Проверка самой функции норм этого не ловит: подмена `norms(prev)`
    на `norms(M)` в цикле не роняла ни одного теста, то есть дорога до
    замера не была покрыта. Тот же класс дыры, что «ярлык остался в
    словаре» в зонде сетапов.
    """
    root = tempfile.mkdtemp()
    syms = [f"W{i:03d}USDT" for i in range(70)]
    days = ["2026-08-10", "2026-08-11"]
    seen = []
    try:
        ev = {(r, days[1], h, (r * 5 + k * 19) % 60)
              for r in range(0, 70, 2) for h in (10, 11)
              for k in range(2)}
        write_rec(root, syms, days, seed=3, event_rows=ev,
                  event_edge=0.0)
        orig_dm, orig_norms = P.day_matrices, P.norms

        def dm(sy, day, log=P.log_):
            M, have = orig_dm(sy, day, log)
            M["_day"] = day            # метка для проверки дороги
            return M, have

        def spy(prev):
            seen.append(None if prev is None else prev.get("_day"))
            return orig_norms(prev)

        P.day_matrices, P.norms = dm, spy
        try:
            run(root, syms, days, tag="wire")
        finally:
            P.day_matrices, P.norms = orig_dm, orig_norms
        check("нормы взяты от ВЧЕРАШНИХ суток",
              seen == [None, days[0]], str(seen))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        for t in ("Z2-book-wire.md", "z2-wire.json"):
            p = os.path.join(P.OUT, t)
            if os.path.exists(p):
                os.remove(p)


def test_thin_minute_and_missing_norms_are_gaps():
    root = tempfile.mkdtemp()
    syms = ["AAAUSDT", "BBBUSDT"]
    try:
        write_rec(root, syms, ["2026-08-10"], per_min=2)
        old = (P.BOOK, P.TRADES, P.MIN_SNAPS)
        P.BOOK = os.path.join(root, "book")
        P.TRADES = os.path.join(root, "trades")
        P.MIN_SNAPS = 3               # две записи в минуте — мало
        try:
            M, have = P.day_matrices(syms, "2026-08-10", log=lambda m: None)
        finally:
            P.BOOK, P.TRADES, P.MIN_SNAPS = old
        check("редкая минута стала пропуском",
              not np.isfinite(M["mid_open"]).any(),
              str(int(np.isfinite(M['mid_open']).sum())))
        check("имена с записью посчитаны", have == 2, str(have))
        check("норм без вчерашних суток не существует",
              P.norms(None) is None, "")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_norms_come_from_yesterday_only():
    """Норма, посчитанная по тем же суткам, знала бы будущее внутри дня."""
    prev = {f: np.full((2, 1440), np.nan, dtype=np.float32)
            for f in P.FIELDS}
    for f in ("spread", "depth_b", "depth_a", "reach", "upd", "path",
              "buy", "sell", "trades"):
        prev[f][0, :700] = 2.0        # хватает истории
        prev[f][1, :10] = 5.0         # почти нет истории
    N = P.norms(prev)
    check("норма считается по вчерашним суткам",
          abs(float(N["spread"][0, 0]) - 2.0) < 1e-9, str(N["spread"][0]))
    check("символ без истории нормы не получает",
          not np.isfinite(N["spread"][1, 0]), str(N["spread"][1]))


TESTS = [test_end_to_end_over_real_files,
         test_drift_is_zero_with_the_mean_control,
         test_declared_horizons_are_the_measured_ones,
         test_norms_wiring_uses_the_previous_day,
         test_thin_minute_and_missing_norms_are_gaps,
         test_norms_come_from_yesterday_only]


def main():
    for t in TESTS:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛОВ: {len(FAILED)} — " + ", ".join(FAILED))
        return 1
    print(f"все проверки прошли ({len(TESTS)} блоков)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
