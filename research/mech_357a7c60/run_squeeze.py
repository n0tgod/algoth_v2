#!/usr/bin/env python3
"""Прогон механики 357a7c60 — топливо сквиза по ходу позиции.

Всё I/O живёт здесь: кэш реплея коротких книг, часовые сводки, деньги
кассой семейства, артефакт, отчёт и публикация. Мера — в
`squeeze_fuel.py`, и второй её копии здесь нет.

Порядок прогона — порядок убийц заявки, и он не переставляется:

  0. сторона ленты (данными, не именем колонки) и покрытие журнала
     сводками — ДО всяких денег; блок здесь означает отчёт с причиной,
     а не молчание;
  1. потолок на почасовых отметках: ось `AXIS_S`, деньги нетто на
     $10 000, контроль — случайные выходы того же числа сделок в те же
     часы среди открытых;
  2. диагностика механизма (всплеск раньше худшей отметки),
     перемешанный между именами поток, пересечение с охраной рынком и
     колонка уже измеренного ценового стопа.

Прогон длиннее минуты: каталог артефактов создаётся ДО счёта, лог
строчный, состояние пишется файлом после каждого шага, предел памяти
свой (`short_grid.MEM_LIMIT_MB`), публикация — часть прогона.

    .venv/bin/python research/mech_357a7c60/run_squeeze.py --seeds 200
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
for _p in (HERE, os.path.join(RESEARCH, "dca_paper"),
           os.path.join(RESEARCH, "a1_universe"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "s8_loop"),
           os.path.join(RESEARCH, "mech_d71203f0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rules as R                                            # noqa: E402
import costs as CO                                           # noqa: E402
import run_short as S                                        # noqa: E402
import short_grid as G                                       # noqa: E402
import agree_book as AG                                      # noqa: E402
import arm_book as AB                                        # noqa: E402
import instruments_refresh as IR                             # noqa: E402
import tail_screen as T                                      # noqa: E402
import path_screen as P                                      # noqa: E402
import wave_guard as WG                                      # noqa: E402
import squeeze_fuel as SQ                                    # noqa: E402

OUT = os.path.join(HERE, "out")
ART = "MECH-squeeze"
BOOK_KEYS = P.BOOK_KEYS
MAIN_DEP = P.MAIN_DEP
_LAST = {}


# ----------------------------------------------------------------------
# Чтение сводок
# ----------------------------------------------------------------------

def summary_names(root):
    try:
        return sorted(d for d in os.listdir(root)
                      if os.path.isdir(os.path.join(root, d)))
    except OSError:
        return []


def read_name(root, sym):
    """Все часовые строки одного имени. Битая строка пропускается."""
    rows = []
    for p in sorted(glob.glob(os.path.join(root, sym, "*.jsonl"))):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("hour"):
                        rows.append(r)
        except OSError:
            continue
    return rows


def name_rows(root, names, log=print, every=100):
    """Генератор (имя, строки) — по одному имени в памяти за раз."""
    t0 = time.time()
    for i, sym in enumerate(names):
        yield sym, read_name(root, sym)
        if every and i and i % every == 0:
            log(f"    калибровка: {i} имён из {len(names)}, "
                f"{time.time() - t0:.0f} с")


# ----------------------------------------------------------------------
# Состояние прогона
# ----------------------------------------------------------------------

def write_status(out, tag, status):
    """Состояние файлом: прогон, убитый ядром, не пишет ничего, и снаружи
    это неотличимо от «не запускали»."""
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, f"{ART}-status-{tag}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


# ----------------------------------------------------------------------
# Счёт
# ----------------------------------------------------------------------

def money_cell(cache, views, changed, ctx, launch, base, seeds, idx, now=None,
               log=print, dep=MAIN_DEP):
    """Деньги одной ячейки оси: правило, контроль, концентрация, дни.

    Ядро денег — `agree_book.stats_of` (то же, что считает книгу на
    странице), контроль — `path_screen.control_exits`, концентрация и
    разбор по дням — `wave_guard.wo3` / `day_diff`. Своего здесь нет
    ничего, и это намеренно.
    """
    mod = SQ.apply_flow(cache, changed)
    d = P.deltas(cache, views, changed)
    out = {"delta": d, "stats": None, "control": None, "beat": {},
           "tails": {}, "wo3": {}, "days": {}, "shape": {}}
    if not changed:
        return out
    out["stats"] = AG.stats_of(AG.packed_short(mod), ctx, launch, BOOK_KEYS,
                               deps=[dep], now=now)
    ctl = P.control_exits(cache, views, changed, ctx, launch, seeds=seeds,
                          dep=dep, now=now, log=log, idx=idx)
    out["control"] = {"books": ctl["books"], "no_cand": ctl["no_cand"],
                      "sum_med": P._med(ctl["sum"])}
    for bk in BOOK_KEYS:
        st = out["stats"].get(f"{bk}:{int(dep)}") or {}
        b = base.get(f"{bk}:{int(dep)}") or {}
        out["beat"][bk] = {f: AG.beat_share(ctl["books"].get(bk), st.get(f), f)[0]
                           for f in ("final", "ratio")}
        out["tails"][bk] = {"base": WG.tails_of(b), "rule": WG.tails_of(st)}
        tb, wb, _d1 = WG.wo3(b.get("days"))
        tr, wr, _d2 = WG.wo3(st.get("days"))
        out["wo3"][bk] = {"base": wb, "rule": wr,
                          "total_base": tb, "total_rule": tr}
        out["days"][bk] = WG.day_diff(b.get("days"), st.get("days"))
        out["shape"][bk] = {"base": SQ.shape_of(b), "rule": SQ.shape_of(st)}
    out["beat"]["sum"] = AG.beat_share([{"sum": x} for x in ctl["sum"]],
                                       d["sum"], "sum")[0]
    return out


def run(seeds=P.SEEDS, perm_seeds=SQ.PERM_SEEDS, axis=SQ.AXIS_S,
        summary_dir=None, names_limit=0, mem_limit=None, now=None,
        launch=None, ctx=None, log=print, status=None, out=OUT, tag="1m"):
    t0 = time.time()
    log = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    st = status if status is not None else {}

    def step(name, **kw):
        st["step"] = name
        st.update(kw)
        st["secs"] = round(time.time() - t0, 1)
        write_status(out, tag, st)

    step("кэш реплея")
    cache, why = S.read_cache(log=log)
    if why:
        return {"error": f"кэш реплея непригоден: {why}"}
    views = SQ.views_of(cache)
    if not views:
        return {"error": "в кэше нет закрытых записей коротких линеек — "
                         "мерить нечего"}
    log(f"записей кэша {len(cache)}, закрытых с путём {len(views)}")

    root = summary_dir or T.SUMMARY_DIR
    names = summary_names(root)
    if names_limit:
        names = names[:int(names_limit)]
    step("калибровка стороны", names=len(names))
    side = SQ.calibrate(name_rows(root, names, log=log))
    log(f"сторона: строк {side.get('rows')}, имён {side.get('names')}, "
        f"часов роста/падения {side['hours']['up']}/{side['hours']['down']}; "
        f"{side.get('why')}")
    # Ноль строк при непустом каталоге сводок — ОТКАЗ, а не отчёт с
    # прочерками: пустота не вправе выдавать себя за результат.
    SQ.refuse_if_empty(len(names), side, root=root)

    art = {"axis": [float(x) for x in axis], "judged": float(SQ.middle(axis)),
           "min_usd": SQ.MIN_USD, "books": list(BOOK_KEYS), "dep": MAIN_DEP,
           "seeds": int(seeds), "perm_seeds": int(perm_seeds),
           "n": len(views), "side": side, "cells": [],
           "summary_names": len(names)}
    if not side.get("ok"):
        art.update({"cover": {}, "verdict": None, "computed_at": G.stamp(),
                    "secs": round(time.time() - t0, 1)})
        art["verdict"] = SQ.verdict(art)
        return art

    field = side["field_short"]
    step("поток по часам жизни")
    hours = T.Hours(root=root)
    cells = SQ.flow_cells(views, hours, field)
    cover = SQ.coverage(views, cells)
    art["cover"] = cover
    art["hours_io"] = {"есть сводка": hours.hit, "нет сводки": hours.miss}
    log(f"часов жизни {cover['hours']}, измеримых {cover['hours_measured']} "
        f"({100 * (cover['hours_share'] or 0):.1f} %); позиций с полным "
        f"покрытием {cover['full']} из {cover['n']}")
    if (cover["share"] or 0) < SQ.COVER_BLOCK:
        art.update({"verdict": None, "computed_at": G.stamp(),
                    "secs": round(time.time() - t0, 1)})
        art["verdict"] = SQ.verdict(art)
        return art

    step("деньги", cells=0)
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    base = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS,
                       deps=[MAIN_DEP], now=now)
    art["base"] = base
    art["costs_error"] = (ctx or {}).get("error")
    idx = P.open_index(views)
    mkt = P.Market(hours)
    pcts = sorted({float(R.wave_guard_of(bk) or 0.0) for bk in BOOK_KEYS})
    judged = float(art["judged"])
    for s in art["axis"]:
        changed, mst = SQ.mark_all(views, cells, s)
        cell = {"s": float(s), "by_book": SQ.by_book(views, changed, BOOK_KEYS),
                "marked_share": SQ.marked_share(views, cells, s),
                "scan": mst}
        log(f"s = {100 * s:.1f} %: помечено {len(changed)} позиций "
            f"(хвостовых {sum(1 for k in changed if views[k]['tail'])})")
        cell.update(money_cell(cache, views, changed, ctx, launch, base,
                               seeds, idx, now=now, log=log))
        cell["diag"] = SQ.before_worst(views, changed)
        cell["perm_real"] = {"n": len(changed),
                             "tails": sum(1 for k in changed
                                          if views[k]["tail"])}
        if changed and perm_seeds:
            draws = SQ.permuted_marks(views, cells, s, seeds=perm_seeds,
                                      log=log)
            cell["perm"] = SQ.perm_stats(cell["perm_real"], draws)
        else:
            cell["perm"] = {"seeds": 0, "beat_tails": None, "beat_n": None}
        gc = {}
        for pct in pcts:
            gc[f"{pct:g}"] = SQ.guard_cross(views, changed, mkt, pct,
                                            R.H24_HOLD_H - 1)
        cell["guard_cross"] = dict(gc[f"{pcts[0]:g}"],
                                   others=({k: v for k, v in gc.items()
                                            if k != f"{pcts[0]:g}"} or None))
        art["cells"].append(cell)
        step("деньги", cells=len(art["cells"]))
        if abs(float(s) - judged) < 1e-12:
            # Колонка сравнения: ценовой стоп, уже измеренный дорогой
            # сделки. Считается тем же кодом и той же кассой, контроля
            # своего не получает — он стоит колонкой, а не соперником.
            step("ценовой стоп")
            _mod, ch_loss = P.apply_axis(cache, views, "loss", SQ.LOSS_STOP)
            ls = money_cell(cache, views, ch_loss, ctx, launch, base, 0, idx,
                            now=now, log=log)
            ls["overlap"] = len(set(ch_loss) & set(changed))
            ls["val"] = SQ.LOSS_STOP
            art["loss_stop"] = ls
    art["computed_at"] = G.stamp()
    art["secs"] = round(time.time() - t0, 1)
    art["verdict"] = SQ.verdict(art)
    return art


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=P.SEEDS,
                    help="зёрен контроля случайных выходов")
    ap.add_argument("--perm-seeds", type=int, default=SQ.PERM_SEEDS,
                    help="зёрен перемешанного между именами потока")
    ap.add_argument("--names", type=int, default=0,
                    help="ограничить калибровку числом имён (смоук)")
    ap.add_argument("--summary", default=None)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--mem-limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    # Смоук не занимает имя полного прогона: подменённый артефакт в этом
    # проекте уже случался (F2).
    tag = a.tag or ("smoke" if (a.seeds < P.SEEDS or a.names) else "1m")
    os.makedirs(a.out, exist_ok=True)
    status = {"state": "идёт", "tag": tag, "seeds": a.seeds,
              "perm_seeds": a.perm_seeds, "started": G.stamp()}
    _LAST.update({"out": a.out, "tag": tag, "status": status,
                  "no_publish": a.no_publish})
    write_status(a.out, tag, status)
    try:
        art = run(seeds=a.seeds, perm_seeds=a.perm_seeds,
                  summary_dir=a.summary, names_limit=a.names,
                  mem_limit=a.mem_limit, log=print, status=status,
                  out=a.out, tag=tag)
    except SystemExit:
        status["state"] = "ОТКАЗ"
        write_status(a.out, tag, status)
        raise
    except BaseException as e:                               # noqa: BLE001
        import traceback
        status.update({"state": "УПАЛ", "error": f"{type(e).__name__}: {e}",
                       "traceback": traceback.format_exc()[-2000:]})
        write_status(a.out, tag, status)
        print(f"ПРОГОН УПАЛ: {type(e).__name__}: {e}")
        if not a.no_publish:
            publish(f"механика 357a7c60: прогон упал ({tag})")
        raise
    art["tag"] = tag
    p = os.path.join(a.out, f"{ART}-{tag}.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)
    txt = SQ.report(art)
    with open(os.path.join(a.out, f"{ART}-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    status.update({"state": "готов", "secs": art.get("secs")})
    write_status(a.out, tag, status)
    if not a.no_publish:
        publish(f"механика 357a7c60: топливо сквиза по ходу позиции ({tag})")
    return 0


if __name__ == "__main__":
    main()
