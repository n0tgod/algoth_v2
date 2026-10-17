#!/usr/bin/env python3
"""Потолок выхода: сколько денег вообще лежит в ВЫБОРЕ МОМЕНТА ВЫХОДА.

Вопрос владельца (2026-10-17): «после открытия ИИ следит за сделкой и
сам решает, где тейк и когда закрыть». Прежде чем платить за решения в
моменте, считается потолок — урок проекта «потолок с идеальным знанием
будущего считается ПЕРВЫМ»: он закрывает направление за вечер. Входы и
размер — как у книги; меняется только выход.

Объявлено ДО прогона:
* забор — тот же, что у любого управления позицией в проекте: выход
  РАНЬШЕ правила можно, продлить срок, расширить стоп или пройти пол —
  нельзя. Поэтому окно выбора — часы с первого до часа выхода правила;
* шаг решения — ЧАС (отметки ядра `marks`): потолок при решении раз в
  час; внутричасовая точность не измерена и в отчёте названа отдельно;
* варианты: правило книги (как живёт, у коротких — с охраной рынком);
  ПОТОЛОК — лучший час внутри забора при известном будущем; СЛЕПОЙ
  выход — случайный час внутри того же забора, `--seeds` зёрен (что даёт
  «закрыть раньше» без умения). Настоящий судья в моменте попадает
  между слепым и потолком;
* деньги — касса тем же ядром (`run_paper.build_rows`), депозиты $1k и
  $10k, сложный процент, БРУТТО (ранний выход — рыночный, проскальзывание
  выхода вместо лимитного тейка; funding короче — сказано в отчёте);
* окна — вся запись, половины по моменту решения, с 13.09; книги —
  длинные, короткие и общий счёт (базовые, без ветвей);
* по позициям — прирост потолка над правилом в долях маржи: среднее,
  медиана, доля позиций, где правило уже было лучшим, доля с приростом
  > 5 и > 20 п.п., разбор по типу выхода правила, как рано стоит
  идеальный час (медиана k*/K).

Ничего не меняет: книги, журналы и кэши не пишутся.

    run research/dca_paper/exit_ceiling.py --seeds=20
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

OUT_MD = os.path.join(R.OUT, "DCA-exit-ceiling.md")
OUT_JSON = os.path.join(R.OUT, "DCA-exit-ceiling.json")
DEPS = LG.DEPS
SINCE = LG.SINCE
WHY_CEIL = "потолок"
WHY_RAND = "случайный выход"
MEM_LIMIT_MB = 3000
EXIT_KINDS = ("тейк", "пол", "срок", "рынок", "рынок за нас", "ликвидация")


def fence(rec, book):
    """Часы, в которые позиция могла быть закрыта раньше правила:
    (путь, последний допустимый час). Открытая или без отметок — None."""
    p = WV.path_of(rec)
    if not p or (rec.get("state") or "closed") != "closed":
        return None, 0
    last = min(R.hold_of(book) - 1, p["K"] - 1)
    return p, last


def ceiling_recs(recs, book):
    """Записи с идеальным выходом внутри забора и пары (было, стало, k*, K)."""
    out, hits = [], []
    for r in recs:
        p, last = fence(r, book)
        if p is None or last < 1:
            out.append(r)
            continue
        final = p["final"]
        k_star = max(range(1, last + 1), key=lambda k: p["cum"][k])
        if p["cum"][k_star] > final + 1e-12:
            new = WV.guard_record(r, k_star, why=WHY_CEIL)
            out.append(new)
            hits.append((r, new, k_star, p["K"]))
        else:
            out.append(r)
            hits.append((r, r, p["K"], p["K"]))
    return out, hits


def random_recs(recs, book, rng):
    """Слепой выход: случайный час внутри того же забора (или свой выход).
    Возвращает записи и пары (было, стало, k, K) по всем позициям с забором
    — чтобы касса сравнивалась с исходом ПОЗИЦИЙ (урок: касса растёт
    оборотом, когда позиция проигрывает)."""
    out, hits = [], []
    for r in recs:
        p, last = fence(r, book)
        if p is None or last < 1:
            out.append(r)
            continue
        k = rng.randint(1, last + 1)                 # last+1 — выход правила
        new = r if k > last else WV.guard_record(r, k, why=WHY_RAND)
        out.append(new)
        hits.append((r, new, min(k, p["K"]), p["K"]))
    return out, hits


def pos_stats(hits):
    """Что потолок делает с ПОЗИЦИЯМИ (в долях маржи, без кассы)."""
    if not hits:
        return {"n": 0}
    d = sorted(float(b["pnl"]) - float(a["pnl"]) for a, b, _k, _K in hits)
    n = len(d)
    by_exit = {}
    for a, b, _k, _K in hits:
        e = a.get("exit") or "?"
        s = by_exit.setdefault(e, {"n": 0, "sum": 0.0, "sum_pnl": 0.0})
        s["n"] += 1
        s["sum"] += float(b["pnl"]) - float(a["pnl"])
        s["sum_pnl"] += float(a["pnl"])
    early = sorted(k / K for _a, _b, k, K in hits if K)
    return {"n": n, "delta_mean": sum(d) / n, "delta_median": d[n // 2],
            "delta_sum": sum(d), "pnl_sum": sum(float(a["pnl"]) for a, _b, _k, _K in hits),
            "rule_best": sum(1 for x in d if x <= 1e-12) / n,
            "gt5": sum(1 for x in d if x > 0.05) / n,
            "gt20": sum(1 for x in d if x > 0.20) / n,
            "k_share_median": early[len(early) // 2] if early else None,
            "by_exit": {e: {"n": s["n"], "delta_mean": s["sum"] / s["n"],
                            "delta_sum": s["sum"], "pnl_sum": s["sum_pnl"]}
                        for e, s in by_exit.items()}}


def load(log):
    """Записи книг как они ЖИВУТ: длинные; короткие с возрастом и охраной;
    общий счёт — своей короткой стороной (возраст и охрана общего счёта)."""
    now = time.time()
    longs, why_l = RPair.long_recs(log=log)
    shorts_all, why_s = RPair.short_recs(log=log)
    if why_l or why_s:
        return None, why_l or why_s
    launch = IR.launches()
    quiet = lambda *a: None                                    # noqa: E731
    books = {}
    for k in R.order_of("sit"):
        if not R.is_branch(k) and k in longs:
            books[k] = longs[k]
    for k in R.order_of("h24"):
        if R.is_branch(k) or k not in shorts_all:
            continue
        kept, _ = RP.age_shorts(shorts_all[k], k, launch=launch, log=quiet, now=now)
        kept, _ = RP.guard_shorts(kept, k, log=quiet, now=now)
        books[k] = kept
    pairs = {}
    for pk in R.order_of("pair"):
        if R.is_branch(pk):
            continue
        lk, sk = R.parts_of(pk)
        if lk not in longs or sk not in shorts_all:
            continue
        kept, _ = RP.age_shorts(shorts_all[sk], pk, launch=launch, log=quiet, now=now)
        kept, _ = RP.guard_shorts(kept, pk, log=quiet, now=now)
        pairs[pk] = (lk, sk, kept)
    return {"books": books, "pairs": pairs, "longs": longs, "now": now}, None


def pack_pairs(pairs, longs_by, shorts_by):
    """Общий счёт из уже обработанных сторон (метка `book` — у записи)."""
    out = {}
    for pk, (lk, sk, _kept) in pairs.items():
        out[pk] = ([dict(r, book=lk) for r in longs_by.get(lk, [])]
                   + [dict(r, book=sk) for r in shorts_by.get(pk, [])])
    return out


def run(seeds, log):
    t0 = time.time()
    R.DEPOSITS[:] = list(DEPS)
    R.SIZINGS = (R.SIZING_COMPOUND,)
    data, why = load(log)
    if why:
        return {"error": why}
    now = data["now"]
    books, pairs = data["books"], data["pairs"]
    long_keys = [k for k in books if R.side_of(k) == "long"]
    short_keys = [k for k in books if R.side_of(k) == "short"]
    pair_keys = list(pairs)
    ats = sorted(float(r["at"]) for v in books.values() for r in v)
    mid = ats[len(ats) // 2]
    since = time.mktime(time.strptime(SINCE, "%Y-%m-%d")) - time.timezone
    wins = {"all": (None, None), "half1": (None, mid), "half2": (mid, None), "since": (since, None)}
    res = {"seeds": seeds, "since": SINCE, "mid": mid, "deps": [int(d) for d in DEPS],
           "keys": {"long": long_keys, "short": short_keys, "pair": pair_keys}, "windows": {}}
    for wname, (lo, hi) in wins.items():
        part = LG.window(books, lo, hi)
        pshort = LG.window({pk: v[2] for pk, v in pairs.items()}, lo, hi)
        cells = {}
        # правило
        by_rule = dict(part)
        pair_rule = pack_pairs(pairs, part, pshort)
        c_rule = LG.cash(by_rule, long_keys + short_keys, now)
        c_rule.update(LG.cash(pair_rule, pair_keys, now))
        cells["rule"] = {"cash": c_rule}
        log(f"окно {wname}: правило посчитано ({time.time() - t0:.0f} с)")
        # потолок
        by_ceil, pos = {}, {}
        for k, recs in part.items():
            by_ceil[k], hits = ceiling_recs(recs, k)
            pos[k] = pos_stats(hits)
        pshort_ceil, ppos = {}, {}
        for pk, recs in pshort.items():
            pshort_ceil[pk], hits = ceiling_recs(recs, pk)
            ppos[pk] = pos_stats(hits)
        c_ceil = LG.cash(by_ceil, long_keys + short_keys, now)
        c_ceil.update(LG.cash(pack_pairs(pairs, by_ceil, pshort_ceil), pair_keys, now))
        cells["ceiling"] = {"cash": c_ceil, "pos": pos, "pos_pair_short": ppos}
        log(f"окно {wname}: потолок посчитан ({time.time() - t0:.0f} с)")
        # слепой выход — зёрна
        draws, pdelta = [], {}
        for sd in range(seeds):
            rng = random.Random(3000 + sd)
            by_r, ps_r = {}, {}
            for k, recs in part.items():
                by_r[k], hits = random_recs(recs, k, rng)
                st = pos_stats(hits)
                pdelta.setdefault(k, []).append(st.get("delta_mean"))
            for pk, recs in pshort.items():
                ps_r[pk], hits = random_recs(recs, pk, rng)
                st = pos_stats(hits)
                pdelta.setdefault(pk, []).append(st.get("delta_mean"))
            c = LG.cash(by_r, long_keys + short_keys, now)
            c.update(LG.cash(pack_pairs(pairs, by_r, ps_r), pair_keys, now))
            draws.append(c)
            if wname == "all":
                log(f"  слепой выход: зерно {sd + 1}/{seeds}")
        rnd = {}
        for k in long_keys + short_keys + pair_keys:
            xs_d = [x for x in pdelta.get(k, []) if x is not None]
            rnd.setdefault(k, {})["pos_delta_mean"] = (sum(xs_d) / len(xs_d)) if xs_d else None
            for d in DEPS:
                xs = [(x[k][int(d)] or {}).get("final") for x in draws]
                xs = [x for x in xs if x is not None]
                dd = [(x[k][int(d)] or {}).get("max_dd") for x in draws]
                dd = [x for x in dd if x is not None]
                rv = (c_rule[k][int(d)] or {}).get("final")
                rnd.setdefault(k, {})[int(d)] = {
                    "final": (sum(xs) / len(xs)) if xs else None,
                    "max_dd": (sum(dd) / len(dd)) if dd else None,
                    "share_not_worse": (None if rv is None or not xs
                                        else sum(1 for x in xs if x >= rv) / len(xs))}
        cells["random"] = {"cash": rnd}
        res["windows"][wname] = cells
    res["secs"] = round(time.time() - t0, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


WIN_TITLE = {"all": "Вся запись", "half1": "Первая половина (по моменту решения)",
             "half2": "Вторая половина", "since": f"С {SINCE}"}
SIDE_TITLE = {"long": "ДЛИННЫЕ книги", "short": "КОРОТКИЕ книги h24 (с охраной рынком, как живут)",
              "pair": "ОБЩИЙ СЧЁТ (обе стороны на одном депозите)"}


def _pp(x):
    return LG._pp(x)


def _pts(x):
    return "—" if x is None else "%+.1f п.п." % (100.0 * float(x))


def report(res):
    if res.get("error"):
        return f"# Потолок выхода\n\nНе посчитано: {res['error']}.\n"
    L = ["# Потолок выхода: сколько лежит в выборе момента выхода", "",
         "Входы и размер — как у книги; меняется только выход. **Забор:** раньше правила можно, "
         "продлить срок, расширить стоп или пройти пол — нельзя. **Потолок** — лучший час внутри "
         "забора при известном будущем, шаг решения ЧАС (отметки ядра; внутричасовая точность не "
         "измерена). **Слепой выход** — случайный час внутри того же забора, среднее по зёрнам: что "
         "даёт «закрыть раньше» без умения. Настоящий судья в моменте попадает между слепым и "
         "потолком. Касса тем же ядром, деньги БРУТТО: ранний выход рыночный (проскальзывание "
         "выхода вместо лимитного тейка не вычтено), funding короче.", ""]
    for wname in ("all", "half1", "half2", "since"):
        cells = res["windows"].get(wname)
        if not cells:
            continue
        L += [f"## {WIN_TITLE[wname]}", ""]
        for side in ("long", "short", "pair"):
            keys = res["keys"].get(side) or []
            if not keys:
                continue
            L += [f"### {SIDE_TITLE[side]}", "",
                  "| книга | вариант | $1k итог | $1k просадка | $10k итог | $10k просадка | "
                  "$10k без 3 дней |", "|---|---|--:|--:|--:|--:|--:|"]
            for k in keys:
                for name, title in (("rule", "правило книги"), ("ceiling", "**потолок**"),
                                    ("random", "слепой выход (среднее)")):
                    c = cells[name]["cash"].get(k) or {}
                    a, b = c.get(1000) or {}, c.get(10000) or {}
                    extra = ""
                    if name == "random":
                        extra = (" · не хуже правила в %d %% зёрен" % round(100 * b["share_not_worse"])
                                 if b.get("share_not_worse") is not None else "")
                        pdm = c.get("pos_delta_mean")
                        extra += (" · Δ на позицию %s" % _pts(pdm)) if pdm is not None else ""
                    elif name == "ceiling":
                        pp_ = (cells["ceiling"]["pos"].get(k) or cells["ceiling"]["pos_pair_short"].get(k) or {})
                        extra = (" · Δ на позицию %s" % _pts(pp_["delta_mean"])) if pp_.get("n") else ""
                    L.append("| %s (`%s`) | %s%s | %s | %s | %s | %s | %s |" % (
                        R.title_en(k), k, title, extra, _pp(a.get("final")), _pp(a.get("max_dd")),
                        _pp(b.get("final")), _pp(b.get("max_dd")),
                        LG._usd(b.get("usd_wo_top3d")) if name != "random" else "—"))
            L.append("")
        # позиции — только на всей записи и половинах, по сторонам long/short
        pos_all = dict(cells["ceiling"]["pos"])
        pos_all.update({pk + " (короткая сторона)": v for pk, v in cells["ceiling"]["pos_pair_short"].items()})
        L += ["#### Позиции: прирост потолка над правилом, доли маржи", "",
              "| книга | закрытых | Σ pnl правила | Σ прирост | прирост в среднем | медиана | "
              "правило уже лучшее | прирост > 5 п.п. | > 20 п.п. | идеальный час, доля жизни |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for k, p in pos_all.items():
            if not p.get("n"):
                continue
            L.append("| %s | %d | %+.1f | %+.1f (%s) | %s | %s | %d %% | %d %% | %d %% | %s |" % (
                k, p["n"], p["pnl_sum"], p["delta_sum"],
                ("×%.2f" % (p["delta_sum"] / p["pnl_sum"]) if p["pnl_sum"] > 0 else "—"),
                _pts(p["delta_mean"]), _pts(p["delta_median"]), round(100 * p["rule_best"]),
                round(100 * p["gt5"]), round(100 * p["gt20"]),
                ("%.2f" % p["k_share_median"]) if p.get("k_share_median") is not None else "—"))
        L.append("")
        if wname == "all":
            L += ["#### Откуда прирост: по типу выхода правила (вся запись)", "",
                  "| книга | выход | позиций | Σ pnl правила | Σ прирост | прирост в среднем |",
                  "|---|---|--:|--:|--:|--:|"]
            for k, p in pos_all.items():
                for e in EXIT_KINDS:
                    s = (p.get("by_exit") or {}).get(e)
                    if not s:
                        continue
                    L.append("| %s | %s | %d | %+.1f | %+.1f | %s |" % (
                        k, e, s["n"], s["pnl_sum"], s["delta_sum"], _pts(s["delta_mean"])))
            L.append("")
    L += ["## Чего замер НЕ говорит", "",
          "- Потолок — верхняя граница при решении раз в ЧАС; решение раз в 5 минут даст потолок выше, "
          "но добавка эта — выбор лучшей минуты внутри часа, то есть шум, которого ни один судья не "
          "предскажет. Внутричасовая точность не измерена.",
          "- Потолок знает будущее. Любой реальный судья (правило, модель, человек) попадёт между "
          "слепым выходом и потолком; расстояние между ними — всё, за что можно бороться.",
          "- Деньги брутто: ранний рыночный выход платит проскальзывание (`costs.SLIP_BP`) там, где "
          "лимитный тейк не платил; на издержках потолок ещё ниже.",
          "- Входы не трогались: судится ТОЛЬКО выход. Доход книг пока рыночный (15.10), и выход может "
          "лишь перераспределить тот же рыночный ход.", "",
          f"Прогон {res.get('secs')} с, {res.get('computed_at')} UTC."]
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
    log = AB.guarded(print, limit=MEM_LIMIT_MB)
    res = run(a.seeds, log)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    print(txt[-3000:])
    if not a.no_publish and not res.get("error"):
        subprocess.run(["tools/publish.sh", "замер: потолок выхода"], cwd=ROOT, check=False)
    return 0 if not res.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
