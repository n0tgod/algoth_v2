"""Замер: ОБРАТНАЯ охрана рынком — выход, когда рынок пошёл в сторону позиции
(вопрос владельца 2026-10-16: «сделай замер для шортов и лонгов, если делать
инверсивную охрану»).

Прямая охрана закрывает позицию, когда рынок идёт ПРОТИВ неё (шорт — рост
волны, действующее правило 4 %; лонг — падение, `long_guard.py`: вредит).
Обратная закрывает, когда рынок идёт В ЕЁ СТОРОНУ: шорт — волна с входа упала
на ≥ порога, лонг — выросла на ≥ порога. Смысл — забрать ход, который дал
весь рынок, пока он не вернулся. Ядро то же (`wave.apply_guard`, `down`).

Объявлено ДО прогона:
* ось порогов — та же (1 / 1.5 / 2 / 3 / 4 / 6 %);
* шорты: без охраны; действующая прямая 4 %; обратная X %; прямая 4 % +
  обратная X % (книга, какой она стала бы); лонги: без охраны; обратная X %;
* окна: вся запись, половины по моменту решения, с 13.09;
* нуль: те же часы закрытия, случайная открытая позиция в каждом, `--seeds`
  зёрен, на всей записи, для обратной 2 и 4 % (без прямой);
* касса тем же ядром (`run_paper.build_rows`), $1k и $10k, сложный процент,
  БРУТТО; короткие — после фильтра возраста имени (правило книги).

Ничего не меняет: книги, журналы и кэши не пишутся.

    run research/dca_paper/inverse_guard.py --seeds=20
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_pair as RPair                                      # noqa: E402
import wave as WV                                             # noqa: E402
import arm_book as AB                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import long_guard as LG                                       # noqa: E402

OUT_MD = os.path.join(R.OUT, "DCA-inverse-guard.md")
OUT_JSON = os.path.join(R.OUT, "DCA-inverse-guard.json")
AXIS = LG.AXIS
NULL_AT = (2.0, 4.0)
DIRECT_SHORT = 4.0
SHORTS = ("safe_h", "optimal_h", "aggr_h")
WHY_INV = "рынок за нас"


def guard(recs, pct, mkt, book, down, why):
    """Записи под охраной (направление `down`) и пары «было → стало»."""
    if not pct:
        return list(recs), []
    out, _st = WV.apply_guard(recs, pct, mkt, R.hold_of(book) - 1, why=why, down=down)
    return out, [(a, b) for a, b in zip(recs, out) if b is not a and b.get("exit") == why]


def variants(side):
    """Объявленные варианты: (имя, прямая, обратная)."""
    out = [("off", None, None)]
    if side == "short":
        out.append((f"direct{DIRECT_SHORT:g}", DIRECT_SHORT, None))
    for x in AXIS:
        out.append((f"inv{x:g}", None, x))
    if side == "short":
        for x in AXIS:
            out.append((f"direct{DIRECT_SHORT:g}+inv{x:g}", DIRECT_SHORT, x))
    return out


def run(seeds, log):
    t0 = time.time()
    R.DEPOSITS[:] = list(LG.DEPS)
    R.SIZINGS = (R.SIZING_COMPOUND,)
    now = time.time()
    longs, why_l = RPair.long_recs(log=log)
    shorts_all, why_s = RPair.short_recs(log=log)
    if why_l or why_s:
        return {"error": why_l or why_s}
    launch = IR.launches()
    quiet = lambda *a: None                                    # noqa: E731
    shorts = {}
    for bk in SHORTS:
        kept, _ = RP.age_shorts(shorts_all.get(bk) or [], bk, launch=launch, log=quiet, now=now)
        shorts[bk] = kept
    sides = {"long": ({k: longs[k] for k in R.order_of("sit") if k in longs}, False),
             "short": (shorts, True)}
    mkt = WV.Market(WV.Hours())
    res = {"axis": list(AXIS), "seeds": seeds, "since": LG.SINCE, "sides": {}}
    for side, (books, short) in sides.items():
        keys = list(books)
        ats = sorted(float(r["at"]) for v in books.values() for r in v)
        mid = ats[len(ats) // 2]
        since = time.mktime(time.strptime(LG.SINCE, "%Y-%m-%d")) - time.timezone
        wins = {"all": (None, None), "half1": (None, mid), "half2": (mid, None),
                "since": (since, None)}
        # прямая охрана шорта — рост рынка (down=False); обратная — наоборот
        inv_down = short
        sres = {"keys": keys, "windows": {}, "null": {}}
        for wname, (lo, hi) in wins.items():
            part = LG.window(books, lo, hi)
            cells = {}
            for name, d_pct, i_pct in variants(side):
                by, hits = {}, {}
                for k in keys:
                    recs = part.get(k, [])
                    recs, _h = guard(recs, d_pct, mkt, k, down=False, why=R.GUARD_EXIT)
                    recs, h = guard(recs, i_pct, mkt, k, down=inv_down, why=WHY_INV)
                    by[k], hits[k] = recs, h
                c = LG.cash(by, keys, now)
                cells[name] = {"cash": c, "pos": {k: LG.pos_stats(hits[k]) for k in keys}}
                log(f"{side}, окно {wname}, {name}: посчитано ({time.time() - t0:.0f} с)")
                if wname == "all" and d_pct is None and i_pct in NULL_AT:
                    idx = {k: LG.open_index(part.get(k, []), k) for k in keys}
                    draws = []
                    for sd in range(seeds):
                        rng = random.Random(2000 + sd)
                        nb = {k: LG.null_book(part.get(k, []), hits[k], idx[k], rng)[0] for k in keys}
                        draws.append(LG.cash(nb, keys, now))
                    share = {}
                    for k in keys:
                        for d in LG.DEPS:
                            rv = (c[k][int(d)] or {}).get("final")
                            xs = [x[k][int(d)].get("final") for x in draws if x[k][int(d)].get("final") is not None]
                            share[f"{k}:{int(d)}"] = (None if rv is None or not xs
                                                      else sum(1 for x in xs if x >= rv) / len(xs))
                    sres["null"][name] = share
                    log(f"  нуль {name}: {seeds} зёрен")
            sres["windows"][wname] = cells
        res["sides"][side] = sres
    res["secs"] = round(time.time() - t0, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


def _title(name):
    if name == "off":
        return "без охраны"
    if name.startswith("direct") and "+" not in name:
        return "прямая " + name[6:] + " % (действующая)"
    if name.startswith("inv"):
        return "обратная " + name[3:] + " %"
    d, i = name.split("+")
    return "прямая " + d[6:] + " % + обратная " + i[3:] + " %"


def report(res):
    if res.get("error"):
        return "# Обратная охрана рынком\n\nНе посчитано: %s.\n" % res["error"]
    L = ["# Обратная охрана рынком: выход, когда рынок пошёл в сторону позиции", "",
         "Шорт закрывается по закрытию часа, когда средний ход крупных имён с входа УПАЛ на ≥ порога; "
         "лонг — когда ВЫРОС. Ось и варианты объявлены до прогона. Касса тем же ядром, деньги БРУТТО. "
         "«Позиций закрыто» — сколько закрыла обратная охрана; «Δ на позицию» — средняя разница исхода "
         "в долях маржи (+ — помогла); «срезано победителей» — закрытые, которые без неё кончили лучше.", ""]
    wt = {"all": "Вся запись", "half1": "Первая половина", "half2": "Вторая половина",
          "since": "С 2026-09-13"}
    for side in ("short", "long"):
        s = res["sides"].get(side) or {}
        L += ["# " + ("ШОРТЫ (короткие книги h24)" if side == "short" else "ЛОНГИ (длинные книги)"), ""]
        for wname in ("all", "half1", "half2", "since"):
            cells = s["windows"].get(wname) or {}
            L += ["## " + wt[wname], ""]
            for k in s["keys"]:
                L += ["### %s (`%s`)" % (R.title_en(k), k), "",
                      "| вариант | $1k итог | $1k просадка | $10k итог | $10k просадка | $10k без 3 дней | "
                      "позиций закрыто | Δ на позицию | срезано победителей |",
                      "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
                for name, c in cells.items():
                    a = c["cash"][k][1000]
                    b = c["cash"][k][10000]
                    p = c["pos"][k]
                    n = p.get("n", 0)
                    dm = "—" if not n else "%+.1f п.п." % (100 * p["delta_mean"])
                    wc = "—" if not n else str(p["worse"])
                    L.append("| %s | %s | %s | %s | %s | %s | %d | %s | %s |" % (
                        _title(name), LG._pp(a.get("final")), LG._pp(a.get("max_dd")),
                        LG._pp(b.get("final")), LG._pp(b.get("max_dd")),
                        LG._usd(b.get("usd_wo_top3d")), n, dm, wc))
                L.append("")
        if s.get("null"):
            L += ["## Нуль (%s): те же часы закрытия, случайные открытые позиции" % side, "",
                  "%d зёрен, вся запись. Доля зёрен, где случайные закрытия НЕ ХУЖЕ правила "
                  "(около 0 — правило лучше случайного, около 1 — хуже)." % res["seeds"], "",
                  "| вариант | " + " | ".join("%s $1k | %s $10k" % (R.title_en(k), R.title_en(k)) for k in s["keys"]) + " |",
                  "|---|" + "--:|" * (2 * len(s["keys"]))]
            for name, sh in s["null"].items():
                def _sh(x):
                    return "—" if x is None else "%.2f" % x
                L.append("| %s | " % _title(name) + " | ".join(
                    _sh(sh.get(k + ":1000")) + " | " + _sh(sh.get(k + ":10000")) for k in s["keys"]) + " |")
            L.append("")
    L.append("Прогон %s с, %s UTC." % (res.get("secs"), res.get("computed_at")))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    log = AB.guarded(print, limit=LG.MEM_LIMIT_MB)
    res = run(a.seeds, log)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "замер: обратная охрана рынком"], cwd=ROOT, check=False)


if __name__ == "__main__":
    main()
