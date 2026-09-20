#!/usr/bin/env python3
"""Прогон механики bb7c3581 — буря выкупа шортов по рынку.

Всё I/O живёт здесь: часовые сводки, кэш реплея коротких книг, деньги
кассой семейства, артефакт, отчёт и публикация. Мера — в `storm.py`, и
второй её копии здесь нет.

Порядок прогона — порядок убийц заявки, и он не переставляется:

  0. сторона ленты (данными, а не именем колонки), ширина по
     календарному часу и её измеримость, покрытие журнала, число
     ИЗМЕНЁННЫХ позиций по книгам — всё ДО денег. Блок здесь означает
     отчёт с причиной, а не молчание;
  1. потолок на почасовых отметках: ось `AXIS_Q`, база — книги С
     охраной рынком, деньги нетто на $10 000, контроль — столько же
     закрытий ВСЕЙ книги в случайных часах с тем же часом суток;
  2. диагностика: буря раньше худшей отметки, слепота охраны, ряд
     ширины, сдвинутый на ±24 ч, и переставленные колонки стороны.

Прогон длиннее минуты: каталог артефактов создаётся ДО счёта, лог
строчный, состояние пишется файлом после каждого шага, предел памяти
свой (`short_grid.MEM_LIMIT_MB`), публикация — часть прогона.

    .venv/bin/python research/mech_bb7c3581/run_storm.py --seeds 200
"""
import argparse
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
           os.path.join(RESEARCH, "mech_d71203f0"),
           os.path.join(RESEARCH, "mech_357a7c60")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import costs as CO                                            # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import path_screen as P                                       # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_squeeze as RUN357                                  # noqa: E402
import short_grid as G                                        # noqa: E402
import squeeze_fuel as SQ                                     # noqa: E402
import tail_screen as T                                       # noqa: E402
import wave_guard as WG                                       # noqa: E402
import storm as STM                                           # noqa: E402

OUT = os.path.join(HERE, "out")
ART = "MECH-storm"
BOOK_KEYS = STM.BOOK_KEYS
MAIN_DEP = STM.MAIN_DEP


# ----------------------------------------------------------------------
# Чтение сводок: один проход на калибровку и на ширину
# ----------------------------------------------------------------------

def scan(root, names, width, log=print, every=100):
    """Генератор (имя, строки) для калибровки, попутно считающий ширину.

    Проход по 772 именам один: калибровка стороны кончается только после
    всех имён, а ширина считается сразу для ОБЕИХ колонок ликвидаций —
    та, что выберет калибровка, и та, что не выберет. Второй проход по
    записи стоил бы минут ни за что, а лишняя колонка стоит счётчика и
    даёт контроль стороны.
    """
    t0 = time.time()
    for i, sym in enumerate(names):
        rows = RUN357.read_name(root, sym)
        STM.fold_width(rows, width)
        yield sym, rows
        if every and i and i % every == 0:
            log(f"    сводки: {i} имён из {len(names)}, "
                f"{time.time() - t0:.0f} с")


def write_status(out, tag, status):
    """Состояние файлом: прогон, убитый ядром, не пишет ничего, и снаружи
    это неотличимо от «не запускали»."""
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, f"{ART}-status-{tag}.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


# ----------------------------------------------------------------------
# Деньги одной ячейки оси
# ----------------------------------------------------------------------

def money_cell(gcache, views, changed, base, pool, real, ctx, launch, seeds,
               now=None, log=print, dep=MAIN_DEP):
    """Деньги одной ячейки: правило, контроль случайными часами, дни.

    Ядро денег — `agree_book.stats_of` (то же, что считает книгу на
    странице), концентрация и разбор по дням — `wave_guard.wo3` /
    `day_diff`, форма — `factory.stability`. Своего здесь нет ничего, и
    это намеренно.
    """
    out = {"delta": P.deltas(gcache, views, changed), "stats": None,
           "control": None, "beat": {}, "tails": {}, "wo3": {}, "days": {},
           "shape": {}}
    if not changed:
        return out
    mod = STM.repack(STM.close_storm(gcache, changed))
    out["stats"] = AG.stats_of(mod, ctx, launch, BOOK_KEYS, deps=[dep],
                               now=now)
    ctl = STM.control_storm(gcache, views, real, pool, ctx, launch,
                            seeds=seeds, dep=dep, now=now, log=log)
    out["control"] = ctl
    for bk in BOOK_KEYS:
        st = out["stats"].get(f"{bk}:{int(dep)}") or {}
        b = base.get(f"{bk}:{int(dep)}") or {}
        out["beat"][bk] = {f: AG.beat_share(ctl["books"].get(bk), st.get(f), f)[0]
                           for f in ("final", "ratio")}
        out["tails"][bk] = {"base": WG.tails_of(b), "rule": WG.tails_of(st)}
        tb, wb, _d1 = WG.wo3(b.get("days"))
        tr, wr, _d2 = WG.wo3(st.get("days"))
        out["wo3"][bk] = {"base": wb, "rule": wr, "total_base": tb,
                          "total_rule": tr}
        out["days"][bk] = WG.day_diff(b.get("days"), st.get("days"))
        out["shape"][bk] = {"base": STM.shape_of(b), "rule": STM.shape_of(st)}
    out["beat"]["sum"] = AG.beat_share([{"sum": x} for x in ctl["sum"]],
                                       out["delta"]["sum"], "sum")[0]
    return out


# ----------------------------------------------------------------------
# Прогон
# ----------------------------------------------------------------------

def run(seeds=STM.CTL_SEEDS, axis=STM.AXIS_Q, summary_dir=None, names_limit=0,
        mem_limit=None, now=None, launch=None, ctx=None, log=print,
        status=None, out=OUT, tag="1m", cache=None, edge_seeds=0):
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
    if cache is None:
        cache, why = S.read_cache(log=log)
        if why:
            return {"error": f"кэш реплея непригоден: {why}"}
    root = summary_dir or T.SUMMARY_DIR
    # Рынок охраны — из ТОГО ЖЕ каталога сводок, что и ширина: охрана есть
    # база этой механики, и читай она другую запись, база была бы книгой,
    # которой нет.
    RP.market(root=root)
    names = RUN357.summary_names(root)
    if names_limit:
        names = names[:int(names_limit)]

    step("сторона и ширина", names=len(names))
    width = STM.new_width()
    side = SQ.calibrate(scan(root, names, width, log=log))
    width["names"] = len(names)
    log(f"сторона: строк {side.get('rows')}, имён {side.get('names')}; "
        f"{side.get('why')}")
    # Ноль строк при непустом каталоге сводок — ОТКАЗ, а не отчёт с
    # прочерками: пустота не вправе выдавать себя за результат.
    SQ.refuse_if_empty(len(names), side, root=root)

    art = {"axis": [float(x) for x in axis], "judged": float(STM.middle(axis)),
           "mark_s": STM.MARK_S, "min_usd": STM.MIN_USD,
           "min_names": STM.MIN_NAMES, "books": list(BOOK_KEYS),
           "dep": MAIN_DEP, "seeds": int(seeds), "side": side, "cells": [],
           "summary_names": len(names),
           "width_raw": {k: v for k, v in width.items() if k != "hours"}}
    if not side.get("ok"):
        art.update({"width": {}, "cover": {}, "computed_at": G.stamp(),
                    "secs": round(time.time() - t0, 1)})
        art["verdict"] = STM.verdict(art)
        return art

    field = side["field_short"]
    series = STM.width_series(width, field)
    art["width"] = STM.width_stats(series)
    log(f"ширина: часов {art['width']['hours']}, измеримых "
        f"{art['width']['measurable']}, медиана "
        f"{100 * (art['width']['median'] or 0):.2f} %")
    if not int(art["width"].get("measurable") or 0):
        art.update({"cover": {}, "computed_at": G.stamp(),
                    "secs": round(time.time() - t0, 1)})
        art["verdict"] = STM.verdict(art)
        return art

    step("база: книги с охраной рынком")
    launch = IR.launches() if launch is None else launch
    gpacked, guards = STM.guarded_books(cache, launch, now=now, log=log)
    gcache = STM.keyed(gpacked)
    views = SQ.views_of(gcache, rulers=BOOK_KEYS)
    art["guards"] = {bk: v["guard"] for bk, v in guards.items()}
    art["n"] = len(views)
    art["open_skipped"] = len(gcache) - len(views)
    if not views:
        return dict(art, error="в кэше нет закрытых записей коротких книг — "
                               "мерить нечего")
    art["cover"] = STM.cover_of(views, series)
    log(f"позиций базы {len(views)} (открытых пропущено "
        f"{art['open_skipped']}); покрытие "
        f"{100 * (art['cover']['share'] or 0):.1f} %")
    if (art["cover"]["share"] or 0) < STM.COVER_BLOCK:
        art.update({"computed_at": G.stamp(),
                    "secs": round(time.time() - t0, 1)})
        art["verdict"] = STM.verdict(art)
        return art

    step("деньги", cells=0)
    ctx = ctx if ctx is not None else CO.context()
    art["costs_error"] = (ctx or {}).get("error")
    base = AG.stats_of(STM.repack(gcache), ctx, launch, BOOK_KEYS,
                       deps=[MAIN_DEP], now=now)
    raw = AG.stats_of(AG.packed_short(cache), ctx, launch, BOOK_KEYS,
                      deps=[MAIN_DEP], now=now)
    # База, посчитанная по МОИМ записям, обязана совпасть с базой, которую
    # касса считает из кэша сама: охрана и возраст идемпотентны, и если
    # это не так — я считаю не ту книгу, что стоит на странице.
    art["base_matches"] = all(
        (base.get(k) or {}).get(f) == (raw.get(k) or {}).get(f)
        for k in raw for f in ("n", "usd", "final", "max_dd"))
    art["base"] = base
    log(f"база: совпадение с кассой по кэшу — "
        f"{'да' if art['base_matches'] else 'НЕТ'}")

    # Окно журнала: час, в который книга не торговала, кандидатом
    # контроля быть не может.
    lo = min(SQ.hour_key(float(v["rec"]["at"]), 1) for v in views.values())
    hi = max(SQ.hour_key(float(v["rec"]["at"]), int(v["path"]["K"]))
             for v in views.values())
    pool = STM.hour_pool(series, lo=lo, hi=hi)
    art["pool"] = {"lo": lo, "hi": hi,
                   "hours": sum(len(v) for v in pool.values())}
    mkt = RP.market()
    judged = float(art["judged"])
    for q in art["axis"]:
        storms = STM.storm_hours(series, q)
        changed = STM.apply_storm(views, storms)
        cell = {"q": float(q), "storms": len(storms),
                "storm_days": len(STM.days_of(storms)),
                "by_book": STM.by_book(views, changed)}
        # Контроль идёт на СУДИМОЙ ячейке. Края печатаются рядом и не
        # судят — значит и контроля им не нужно: зерно стоит секунд
        # десять, и тройная цена за числа, которые вердикт не читает,
        # есть просто тройная цена. Ячейка без контроля отдаёт прочерк,
        # а не ноль: вердикт на прочерке говорит «нечем судить».
        cell_seeds = seeds if abs(float(q) - judged) < 1e-12 else int(edge_seeds)
        log(f"q = {100 * q:.0f} %: бурных часов {len(storms)} в "
            f"{cell['storm_days']} сутках, изменено позиций {len(changed)}, "
            f"зёрен контроля {cell_seeds}")
        cell.update(money_cell(gcache, views, changed, base, pool, storms,
                               ctx, launch, cell_seeds, now=now, log=log))
        cell["diag"] = SQ.before_worst(views, changed)
        cell["quiet"] = STM.quiet_share([STM.hour_wave(mkt, hk)
                                         for hk in storms])
        cell["guard_cross"] = STM.guard_cross(views, changed, storms)
        cell["shift"] = {}
        for off in (-STM.SHIFT_H, STM.SHIFT_H):
            sh_storms = STM.storm_hours(STM.shifted(series, off), q)
            sh_changed = STM.apply_storm(views, sh_storms)
            cell["shift"][f"{off:+d} ч"] = {
                "storms": len(sh_storms), "changed": len(sh_changed),
                "common": len(set(sh_changed) & set(changed))}
        art["cells"].append(cell)
        step("деньги", cells=len(art["cells"]))
        if abs(float(q) - judged) < 1e-12:
            art["hod"] = STM.hod_hist(storms)
            other = [f for f in STM.LIQ_FIELDS if f != field]
            sw_storms = STM.storm_hours(
                STM.width_series(width, other[0]), q) if other else []
            art["swap"] = {"field": (other[0] if other else None),
                           "storms": len(sw_storms), "real": len(storms),
                           "common": len(set(sw_storms) & set(storms))}
    art["computed_at"] = G.stamp()
    art["secs"] = round(time.time() - t0, 1)
    art["verdict"] = STM.verdict(art)
    return art


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=STM.CTL_SEEDS,
                    help="зёрен контроля случайными часами")
    ap.add_argument("--edge-seeds", type=int, default=0,
                    help="зёрен контроля на КРАЯХ оси (они не судят)")
    ap.add_argument("--names", type=int, default=0,
                    help="ограничить чтение сводок числом имён (смоук)")
    ap.add_argument("--summary", default=None)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--mem-limit", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                         # noqa: BLE001
        pass
    # Смоук не занимает имя полного прогона: подменённый артефакт в этом
    # проекте уже случался (F2).
    tag = a.tag or ("smoke" if (a.seeds < STM.CTL_SEEDS or a.names) else "1m")
    os.makedirs(a.out, exist_ok=True)
    status = {"state": "идёт", "tag": tag, "seeds": a.seeds,
              "started": G.stamp()}
    write_status(a.out, tag, status)
    try:
        art = run(seeds=a.seeds, summary_dir=a.summary, names_limit=a.names,
                  mem_limit=a.mem_limit, log=print, status=status,
                  out=a.out, tag=tag, edge_seeds=a.edge_seeds)
    except SystemExit:
        status["state"] = "ОТКАЗ"
        write_status(a.out, tag, status)
        raise
    except BaseException as e:                                # noqa: BLE001
        import traceback
        status.update({"state": "УПАЛ", "error": f"{type(e).__name__}: {e}",
                       "traceback": traceback.format_exc()[-2000:]})
        write_status(a.out, tag, status)
        print(f"ПРОГОН УПАЛ: {type(e).__name__}: {e}")
        if not a.no_publish:
            publish(f"механика bb7c3581: прогон упал ({tag})")
        raise
    art["tag"] = tag
    p = os.path.join(a.out, f"{ART}-{tag}.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)
    txt = STM.report(art)
    with open(os.path.join(a.out, f"{ART}-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    status.update({"state": "готов", "secs": art.get("secs")})
    write_status(a.out, tag, status)
    if not a.no_publish:
        publish(f"механика bb7c3581: буря выкупа шортов по рынку ({tag})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
