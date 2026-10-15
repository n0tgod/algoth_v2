#!/usr/bin/env python3
"""Кэш контекста издержек (`costs.context(cache=…)`, 15.10): второй вызов
не читает ряды funding; изменённый каталог рядов — пересборка; частичный
контекст (`need`) мимо кэша; контекст с ошибкой не кэшируется; подложенный
pickle с верной подписью читается (контроль).

    .venv/bin/python research/dca_paper/test_costs_cache.py
"""
import gzip
import os
import pickle
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import costs as CO                                            # noqa: E402


def main():
    d = tempfile.mkdtemp()
    fdir = os.path.join(d, "funding")
    os.makedirs(fdir)
    with gzip.open(os.path.join(fdir, "AUSDT.csv.gz"), "wt") as f:
        f.write("ts,rate\n1,0.0001\n")
    cache = os.path.join(d, "ctx.pkl")
    calls = []
    was = (CO.FUNDING_DIR, CO.universe, CO.symbol_maps, CO.extra_assets, CO.FS.load_funding)
    CO.FUNDING_DIR = fdir
    CO.universe = lambda: {"A": {"bybit_symbol": "AUSDT"}}
    CO.symbol_maps = lambda assets: ({"AUSDT": "A"}, {"AUSDT": 5.5})

    CO.extra_assets = lambda to_asset, funding_dir=None: []

    def load(directory, universe, symbols, symbol_field="bybit_symbol"):
        calls.append(sorted(symbols))
        return {"A": ([1], [0.0001])}
    CO.FS.load_funding = load
    try:
        c1 = CO.context(cache=cache)
        assert c1.get("n_funding") == 1 and len(calls) == 1 and os.path.exists(cache), (c1, calls)
        logs = []
        c2 = CO.context(cache=cache, log=logs.append)
        assert c2 == c1 and len(calls) == 1 and any("из кэша" in m for m in logs), (calls, logs)
        # частичный контекст — мимо кэша (считается заново, в кэш не пишется)
        c3 = CO.context(need={"A"}, cache=cache)
        assert len(calls) == 2 and c3.get("n_funding") == 1
        c4 = CO.context(cache=cache)
        assert len(calls) == 2 and c4 == c1, "полный контекст после частичного должен идти из кэша"
        # без кэша — всегда заново
        CO.context(cache=None)
        assert len(calls) == 3
        # контроль: подделка с верной подписью читается
        with open(cache, "rb") as f:
            dd = pickle.load(f)
        dd["ctx"] = dict(dd["ctx"], n_funding=777)
        with open(cache, "wb") as f:
            pickle.dump(dd, f)
        assert CO.context(cache=cache).get("n_funding") == 777 and len(calls) == 3, "контроль не лёг"
        # каталог рядов изменился — пересборка, подделка вытеснена
        time.sleep(0.01)
        with gzip.open(os.path.join(fdir, "BUSDT.csv.gz"), "wt") as f:
            f.write("ts,rate\n1,0.0002\n")
        c5 = CO.context(cache=cache)
        assert c5.get("n_funding") == 1 and len(calls) == 4, (c5, calls)
        # контекст с ошибкой не кэшируется
        def boom(*a, **k):
            raise RuntimeError("нет рядов")
        CO.FS.load_funding = boom
        os.unlink(cache)
        e = CO.context(cache=cache)
        assert e.get("error") and not os.path.exists(cache), e
    finally:
        CO.FUNDING_DIR, CO.universe, CO.symbol_maps, CO.extra_assets, CO.FS.load_funding = was
    print("ok  кэш контекста издержек: второй вызов без чтения рядов, need мимо кэша, без кэша заново, "
          "подделка читается (контроль), новый файл рядов — пересборка, ошибка не кэшируется")
    return 0


if __name__ == "__main__":
    sys.exit(main())
