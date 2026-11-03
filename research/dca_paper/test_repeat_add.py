#!/usr/bin/env python3
"""Долив по повторному выбору: на синтетических барах — долив на первом повторе,
где держит условие ячейки (любая цена / не выше средней / ниже лестницы);
без подходящего повтора — запись книги на 1.25 T с лежащим резервом; плечо
книжное; случайные часы нуля считаются и выбираются зерном; события и нуль
собираются из кэшей; кэш по своей подписи."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                            # noqa: E402
import repeat_add as RA                                       # noqa: E402
import test_reserve_rung as T                                 # noqa: E402
import run_d2 as D2                                           # noqa: E402

H = 3600.0


def main():
    bars = T.bars_path(dip=0.20, recover=0.03)
    ts = [b[0] for b in bars]
    g = dict(T.LEG)
    legs = [g, dict(g, at=T.T0 + 5 * H), dict(g, at=T.T0 + 20 * H), dict(g, at=T.T0 + 80 * H)]   # повтор на 5 ч, 20 ч; 80 ч — после выхода
    was = D2.build_levels
    D2.build_levels = lambda win, now_i: T.LEVELS
    try:
        cells = RA.leg_cells(g, bars, ts, T.look, None, "sigma", 6.0, legs)
        assert cells is not None and all(c in cells for c in RA.MAIN_CELLS if c != "ticket"), set(cells)
        book, idle = cells["book"], cells["idle"]
        assert book["capital_t"] == 1.0 and idle["capital_t"] == RA.CAPITAL and abs(idle["pnl"] - book["pnl"] / RA.CAPITAL) < 1e-12
        assert idle["exit"] == book["exit"] and idle["adds"] == 0
        a, d, dp = cells["rep_any"], cells["rep_down"], cells["rep_deep"]
        # 5 ч: цена −3 %, ниже средней (две ступени заполнены), но выше глубочайшего рунга 0.94
        assert a["adds"] == 1 and a["add_t"] == T.T0 + 5 * H and a["repeat_t"] == T.T0 + 5 * H, a
        assert d["adds"] == 1 and d["add_t"] == T.T0 + 5 * H, d
        # ниже лестницы — только повтор на 20 ч (−13 %)
        assert dp["adds"] == 1 and dp["add_t"] == T.T0 + 20 * H, dp
        for r in (a, d, dp):
            assert r["capital_t"] == RA.CAPITAL and r["lev"] == book["lev"], "плечо книжное, маржа 1.25 T"
            assert len(r["fills"]) == 4 + 1 and any(abs(f[2] - RA.ADD_W / RA.CAPITAL) < 1e-12 for f in r["fills"])
        # долив ниже лестницы на возврате к −3 % даёт больше лежащего резерва; долив на −3 % при дне −20 % — хуже
        assert dp["pnl"] > idle["pnl"] and dp["exit"] == "срок", (dp["pnl"], idle["pnl"], dp["exit"])
        # случайные часы: три варианта на условие «любая цена», для «ниже лестницы» — только часы под лестницей
        rnd_any = [c for c in cells if c.startswith("rnd_any:")]
        assert len(rnd_any) == RA.RND_K, rnd_any
        for c in cells:
            if c.startswith("rnd_deep:"):
                assert cells[c]["adds"] == 1 and cells[c]["add_t"] >= T.T0 + 10 * H, (c, cells[c]["add_t"])
        # повтор только ПОСЛЕ выхода книги — долива нет, запись лежащего резерва
        late = RA.leg_cells(g, bars, ts, T.look, None, "sigma", 6.0, [g, dict(g, at=T.T0 + 80 * H)])
        assert late["rep_any"]["adds"] == 0 and late["rep_any"]["repeat_t"] is None and late["rep_any"]["pnl"] == idle["pnl"]
        # условие «не выше средней»: повтор на первом часу, пока цена выше средней (путь вверх сперва) — долива нет
        up = [b for b in bars]
        for i, b in enumerate(up):
            if T.T0 < b[0] < T.T0 + 3 * H:          # после бара входа: цена на 2 % выше средней
                k = 1.02
                up[i] = (b[0], b[1] * k, b[2] * k, b[3] * k, b[4] * k, b[5])
        cu = RA.leg_cells(g, up, [b[0] for b in up], T.look, None, "sigma", 6.0, [g, dict(g, at=T.T0 + 1 * H)])
        assert cu["rep_any"]["adds"] == 1 and cu["rep_down"]["adds"] == 0, (cu["rep_any"]["adds"], cu["rep_down"]["adds"])
    finally:
        D2.build_levels = was
    # события и нуль из кэшей
    pr = ("sigma", 6.0, "long")
    key = (pr, "SYNUSDT", float(T.T0))
    caches = {c: {} for c in RA.CELLS}
    for c, r in cells.items():
        caches[c][key] = dict(r, state="closed")
    ev = RA.events(caches, pr, "rep_deep")
    assert ev["n"] == 1 and abs(ev["mean_t_res"] - round(dp["pnl"] * RA.CAPITAL, 4)) < 1e-9 and ev["mean_t_book"] == round(book["pnl"], 4)
    with tempfile.TemporaryDirectory() as d_:
        RA.CACHE_DIR = d_
        RA.write_caches(caches)
        back = RA.read_caches(log=lambda *a: None)
        assert back["rep_deep"][key]["adds"] == 1 and back["rnd_any:0"][key]["adds"] == 1
    print("ok  долив по повтору: первый подходящий повтор, три условия, лежащий резерв без повтора, плечо книжное, случайные часы, события, кэш")
    print("\nвсе 1 проверки прошли")


if __name__ == "__main__":
    main()
