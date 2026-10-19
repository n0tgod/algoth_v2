#!/usr/bin/env python3
"""Живая отметка DCA-книги читается из артефакта ЕЁ семейства.

Дефект 19.10: `Collector.dca_marks` читал только артефакт длинных книг
(`rules.ARTIFACT`), и всем коротким (`*_h`) и общим (`pair_*`) ячейкам
отвечал «не считали» (`known: false`). Приложение показывало им отметку
последнего прогона вместо живой, а позицию, прожившую меньше одного
прогона, не показывало вовсе — закрытая на −560 $ позиция «нигде не
была». Здесь: у короткой и общей книги отметка берётся из их артефактов
(`rules.artifact_of`), открытые читаются из `books[ячейка].open`, кеш
артефактов — по пути, а не один на всех.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "dca_paper"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "dca_ladder"))

import collect as C          # noqa: E402
import ladder as LD          # noqa: E402
import rules as DR           # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


class B:
    def __init__(self, px):
        self.px = px

    def best(self):
        return (self.px * 0.999, self.px * 1.001)


def _art(cell, pos, with_live):
    bk = {"all": {"n": 1, "usd": 1.0}, "open": {"positions": pos, "cut": [],
                                                 "mark_usd": 0.0, "priced": 1}}
    a = {"books": {cell: bk}}
    if with_live:
        a["live"] = {cell: bk["open"]}
    return a


def reconnect_pause_resets_after_open():
    """Пауза переподключения: после открывшегося соединения — снова 1 с;
    растёт только у соединений, которые не открылись (отказ площадки).
    Прежде она доходила до 30 с и не сбрасывалась никогда."""
    import types

    c = C.Collector(["TEST"], [], tempfile.mkdtemp(), lambda m: None)
    sh = c.shards[0]
    plan = [True, True, False, False, False, True, True]   # открылось ли
    sleeps = []

    class App:
        def __init__(self, url, on_open=None, **kw):
            self.on_open = on_open

        def run_forever(self, **kw):
            ok = plan.pop(0)
            if ok:
                self.on_open(self)
            if not plan:
                c.stop.set()

    sh.send_sub = lambda ws, topics: None
    fake = types.ModuleType("websocket")
    fake.WebSocketApp = App
    keep_ws, keep_sleep = sys.modules.get("websocket"), C.time.sleep
    sys.modules["websocket"] = fake
    C.time.sleep = lambda x: sleeps.append(x)
    try:
        sh.run()
    finally:
        C.time.sleep = keep_sleep
        if keep_ws is not None:
            sys.modules["websocket"] = keep_ws
        else:
            sys.modules.pop("websocket", None)
    check("пауза переподключения: после открытого соединения 1 с, отказы удваивают",
          sleeps == [1, 1, 2, 4, 8, 1], str(sleeps))
    check("обрывы считаются", sh.n_drops == 6, str(sh.n_drops))


def main():
    keep = (DR.ARTIFACT, DR.H24_ARTIFACT, DR.PAIR_ARTIFACT)
    td = tempfile.mkdtemp()
    try:
        DR.ARTIFACT = os.path.join(td, "long.json")
        DR.H24_ARTIFACT = os.path.join(td, "short.json")
        DR.PAIR_ARTIFACT = os.path.join(td, "pair.json")
        t0 = (int(DR.RULES_SINCE) // 3600 + 1) * 3600
        dep = 10000
        pos = [{"sym": "AAAUSDT", "at": t0, "lev": 25.0, "margin": 1274.74,
                "avg": 2.0, "entry_px": 2.0, "depth": 1,
                "mark_frac": 0.0, "mark_usd": 0.0,
                "fills": [[t0, 2.0, 1.0]]}]
        # длинный артефакт несёт `live`, короткий и общий — только `books`
        with open(DR.ARTIFACT, "w", encoding="utf-8") as f:
            json.dump(_art(f"optimal:{dep}", pos, True), f)
        with open(DR.H24_ARTIFACT, "w", encoding="utf-8") as f:
            json.dump(_art(f"optimal_h:{dep}", pos, False), f)
        with open(DR.PAIR_ARTIFACT, "w", encoding="utf-8") as f:
            json.dump(_art(f"pair_optimal_g2:{dep}", pos, False), f)
        c = C.Collector(["TEST"], [], tempfile.mkdtemp(), lambda m: None)
        c.books["AAAUSDT"] = B(2.4)
        want_s = LD.open_mark(2.4, 2.0, 1274.74, 25.0, [1.0], side="short")
        want_l = LD.open_mark(2.4, 2.0, 1274.74, 25.0, [1.0], side="long")
        ds = c.dca_marks(dep=dep, ruler="optimal_h")
        check("короткая книга: отметка известна и живая",
              ds.get("known") is True and ds.get("n") == 1
              and abs((ds["rows"][0].get("mark_frac") or 0) - round(want_s, 6)) < 1e-9,
              str(ds))
        dp = c.dca_marks(dep=dep, ruler="pair_optimal_g2")
        check("общий счёт: отметка известна, знак стороны книги",
              dp.get("known") is True and dp.get("priced") == 1
              and dp["rows"][0]["mark_frac"] is not None,
              str(dp))
        dl = c.dca_marks(dep=dep, ruler="optimal")
        check("длинная книга: по-прежнему из `live`",
              dl.get("known") is True
              and abs(dl["rows"][0]["mark_frac"] - round(want_l, 6)) < 1e-9,
              str(dl))
        check("знак у шорта зеркален длинной при той же цене",
              want_s < 0 < want_l, f"{want_s} / {want_l}")
        # кеш — по пути: чтение одного семейства не подменяет другое
        ds2 = c.dca_marks(dep=dep, ruler="optimal_h")
        dl2 = c.dca_marks(dep=dep, ruler="optimal")
        check("кеш артефактов по семействам не смешивает книги",
              ds2.get("book") == f"optimal_h:{dep}" and dl2.get("book") == f"optimal:{dep}"
              and len(getattr(c, "_dca_arts", {})) == 3, str(sorted(getattr(c, "_dca_arts", {}))))
        # ячейка, которой прогон не касался, — «не считали», не ноль
        dn = c.dca_marks(dep=100, ruler="optimal_h")
        check("ячейки нет в артефакте семейства → «не считали»",
              dn.get("known") is False and not dn.get("rows"), str(dn))
        # Стакан пуст (шард переподключается): берётся последняя
        # записанная середина не старше MARK_STALE_S, возраст рядом;
        # старше — прочерк, а не ноль.
        import time as _t
        from collections import deque

        class Empty:
            def best(self):
                return (None, None)
        c.books["AAAUSDT"] = Empty()
        c.mid = {"AAAUSDT": deque([(_t.time() - 30.0, 2.4)])}
        de = c.dca_marks(dep=dep, ruler="optimal_h")
        r0 = (de.get("rows") or [{}])[0]
        check("пустой стакан: отметка по последней середине, возраст рядом",
              de.get("priced") == 1 and abs((r0.get("mark_frac") or 0) - round(want_s, 6)) < 1e-9
              and 29 <= (r0.get("stale_s") or 0) <= 40, str(de))
        c.mid = {"AAAUSDT": deque([(_t.time() - C.MARK_STALE_S - 5, 2.4)])}
        do = c.dca_marks(dep=dep, ruler="optimal_h")
        r1 = (do.get("rows") or [{}])[0]
        check("пустой стакан, середина старше предела: прочерк",
              do.get("priced") == 0 and r1.get("mark_usd") is None
              and do.get("mark_usd") is None, str(do))
        h = c.health()
        check("статус несёт обрывы и замирания числом",
              "drops" in h and "stalls_over_5s" in h and "net_minute" in h, str(sorted(h)))
        # артефакта семейства нет — названо, и это тоже «не считали»
        os.remove(DR.PAIR_ARTIFACT)
        dm = c.dca_marks(dep=dep, ruler="pair_optimal_g2")
        check("нет артефакта семейства → ошибка названа, known=false",
              dm.get("known") is False and "нет" in str(dm.get("error")), str(dm))
    finally:
        DR.ARTIFACT, DR.H24_ARTIFACT, DR.PAIR_ARTIFACT = keep
    reconnect_pause_resets_after_open()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
