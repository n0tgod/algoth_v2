#!/usr/bin/env python3
"""Правила общего счёта на ОТДЕЛЬНЫХ коротких книгах: возраст и билет.

Просьба владельца 2026-09-08: «нужно сделать такую же логику, как и в
общих, чтобы вывести в плюс отдельно шортовые стратегии».

Мерится ровно то, что у общего счёта УЖЕ объявлено, и ничего нового:

* **возраст имени на входе** — порог 7 суток. Он объявлен 08.09 по
  сетке (0, 3, 7, 14, 30, 60) на этом же листе, и здесь НЕ подбирается:
  берётся как есть, иначе это была бы вторая подгонка под тот же ответ.
* **доля билета** — 1.0 / 0.5 / 0.25, те же три значения, что стоят у
  общего счёта. Доля не меняет знак средней сделки: она уменьшает и
  доход, и просадку. Но касса от неё не линейна — мелкий билет пускает
  в книгу решения, которым раньше не хватало денег, — и именно это
  здесь и считается, а не пересчитывается умножением.

Контроль тот же и по той же причине: фильтр РЕЖЕТ число сделок, а
короткая книга в минусе — значит меньше шортов само по себе улучшает
счёт. На пороге считается случайная выборка ровно того же размера, на
200 зёрнах, и печатается доля выборок, которые фильтр НЕ побил, —
отдельно по деньгам и по отношению доход/просадка.

Деньги НЕТТО: комиссия, проскальзывание и funding учтены в каждой
сделке тем же ядром, что у самих книг. Журнал книг замер не трогает —
это проба, а не книга.

Запуск: `run research/dca_paper/short_age.py`.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_pair as PR                                         # noqa: E402
import pair_age as PA                                         # noqa: E402
import instruments_refresh as IR                              # noqa: E402

# Оси объявлены ДО прогона. Порог возраста — уже объявленный (7 суток) и
# ноль как «как сейчас»; доли билета — те же три, что у общего счёта.
DAYS = (0, 7)
SHARES = (1.0, 0.5, 0.25)
SEEDS = 200
SEED = 20260908
# Депозит, на котором считается контроль: 200 зёрен × три книги — это
# 600 пересборок книги, и делать их на всех трёх депозитах значило бы
# втрое дороже ради того же ответа.
CTRL_DEP = 10000.0


def cell(recs, bk, dep, ctx, share=1.0, now=None):
    """Книга на этих решениях при этой доле билета. Деньги НЕТТО.

    Доля билета выставляется в объявленной карте правил и возвращается
    обратно: правило живёт одним местом (`rules.SHORT_SHARE`), и проба
    считает ИМ, а не своей копией формулы билета.
    """
    was, had = R.SHORT_SHARE.get(bk), (bk in R.SHORT_SHARE)
    try:
        R.SHORT_SHARE[bk] = float(share)
        rows, cells, _one, live = RP.build_rows({bk: recs}, now=now,
                                                keys=[bk],
                                                log=lambda *a: None)
        # Билет считается ПОД той же долей, что и книга: посчитав его
        # после возврата карты правил, отчёт показал бы билет, которым
        # ячейка не торговала.
        ticket = R.ticket_in(bk, bk, dep)
    finally:
        if had:
            R.SHORT_SHARE[bk] = was
        else:
            R.SHORT_SHARE.pop(bk, None)
    mine = [r for r in rows if int(r.get("dep", 0)) == int(dep)]
    if ctx is not None and not ctx.get("error"):
        mine, _c = CO.apply_to_rows(mine, ctx)
    st = RP._stats(mine, dep) or {}
    c = cells.get(RP._cell(bk, dep)) or {}
    fin, dd = st.get("final"), st.get("max_dd")
    # Доход НА ПРОСАДКУ: +20 % при −5 % и +20 % при −20 % — разные книги.
    # Просадки нет — отношения не существует, и это прочерк.
    ratio = (None if not fin or not dd
             else round(float(fin) / abs(float(dd)), 2))
    return {"n": st.get("n"), "usd": st.get("usd"), "final": fin,
            "max_dd": dd, "win": st.get("win"), "ratio": ratio,
            "no_cash": c.get("no_cash"), "taken": c.get("taken"),
            "ticket": ticket, "rows": mine,
            # ОТКРЫТЫЕ позиции — тоже входы, просто ещё не закрытые.
            # Считать «взято» одними закрытыми значило бы показывать ноль
            # у каждых свежих суток: срок книги 24 ч, и вчерашний вход
            # закрывается только сегодня.
            "open": ((live.get(RP._cell(bk, dep)) or {}).get("positions")
                     or [])}


def supply(recs, bk, ctx, launch, days=14, dep=None, now=None):
    """Подача листа по суткам: что предложено, что срезал возраст, что взято.

    Сетка выше судит книгу целиком, а владелец смотрит на живой график и
    видит ТИШИНУ последних дней. Тишина бывает двух родов: листа не
    подают — или правило режет то, что подали. Это разные болезни, и
    отличать их надо числом по суткам, а не средним за месяц.
    """
    dep = float(dep or CTRL_DEP)
    now = float(now if now is not None else time.time())
    need = R.min_age_days(bk)
    keep, _drops = PA.pick(recs, launch, need)
    with_, without = cell(keep, bk, dep, ctx, now=now), cell(recs, bk, dep,
                                                            ctx, now=now)
    got = {}
    for r in recs:
        d = time.strftime("%Y-%m-%d", time.gmtime(float(r.get("at", 0))))
        b = got.setdefault(d, {"предложено": 0, "моложе порога": 0,
                               "возраст неизвестен": 0, "взято": 0,
                               "взято без правила": 0})
        b["предложено"] += 1
        a = IR.age_days(launch, r.get("sym"), r.get("at"))
        if a is None:
            b["возраст неизвестен"] += 1
        elif a < need:
            b["моложе порога"] += 1
    for tag, c in (("взято", with_), ("взято без правила", without)):
        for r in list(c.get("rows") or []) + list(c.get("open") or []):
            d = time.strftime("%Y-%m-%d", time.gmtime(float(r.get("at", 0))))
            if d in got:
                got[d][tag] += 1
    last = sorted(got)[-int(days):]
    return {"dep": int(dep), "days": {d: got[d] for d in last},
            "min_days": need,
            "n": with_.get("n"), "n_free": without.get("n"),
            "open": len(with_.get("open") or []),
            "open_free": len(without.get("open") or [])}


def run(log=print, ctx=None, cache=None, keys=None, now=None, seeds=None,
        days=None, shares=None, deps=None, launch=None):
    t0 = time.time()
    keys = list(keys or R.H24_ORDER)
    days = tuple(days or DAYS)
    shares = tuple(shares or SHARES)
    deps = list(deps or R.DEPOSITS)
    seeds = int(seeds or SEEDS)
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    shorts, why = PR.short_recs(cache, log=log)
    if why or not shorts:
        why = why or "позиций коротких книг нет"
        log(f"замер не считается: {why}")
        return {"error": why}
    if not launch:
        log("справочник инструментов не читается — возраст неизвестен всем")
    out = {"days": list(days), "shares": list(shares), "deps": deps,
           "seeds": seeds, "ctrl_dep": CTRL_DEP, "cells": {},
           "launch_known": len(launch),
           "costs_error": (ctx or {}).get("error"),
           "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    for bk in keys:
        recs = shorts.get(bk) or []
        for d in days:
            keep, drops = PA.pick(recs, launch, d)
            for sh in shares:
                for dep in deps:
                    c = cell(keep, bk, dep, ctx, share=sh, now=now)
                    # Строки книги в артефакт не идут: это книга целиком,
                    # а не сводка.
                    c.pop("rows", None)
                    out["cells"][f"{bk}|{d}|{sh}|{int(dep)}"] = dict(
                        c, book=bk, min_days=d, share=sh, dep=int(dep),
                        offered=len(recs), kept=len(keep), drops=drops)
                log(f"{bk} ≥{d} сут, билет {sh:g}×: решений {len(keep)} из "
                    f"{len(recs)}, ${int(CTRL_DEP)} → "
                    f"{out['cells'][f'{bk}|{d}|{sh}|{int(CTRL_DEP)}']['usd']} $")
            if not d:
                continue
            # Контроль — только на объявленной доле 1.0 и одном депозите:
            # вопрос контроля один («это отбор или просто меньше сделок»),
            # и ответ на него не зависит от размера билета.
            got = []
            for k in range(seeds):
                rk_, _w = PA.pick(recs, launch, d, seed=SEED + 100 * k,
                                  n_random=len(keep))
                x = cell(rk_, bk, CTRL_DEP, ctx, share=1.0, now=now)
                x.pop("rows", None)
                got.append(x)
            usd = [x["usd"] or 0.0 for x in got]
            rt = [x["ratio"] for x in got if x.get("ratio") is not None]
            base = out["cells"][f"{bk}|{d}|1.0|{int(CTRL_DEP)}"]
            out["cells"][f"{bk}|{d}|random"] = {
                "book": bk, "min_days": d, "seeds": seeds, "kept": len(keep),
                "dep": int(CTRL_DEP),
                "usd": round(float(np.median(usd)), 2),
                "usd_p10": round(float(np.quantile(usd, 0.1)), 2),
                "usd_p90": round(float(np.quantile(usd, 0.9)), 2),
                "ratio": (round(float(np.median(rt)), 2) if rt else None),
                "ratio_p10": (round(float(np.quantile(rt, 0.1)), 2)
                              if rt else None),
                "ratio_p90": (round(float(np.quantile(rt, 0.9)), 2)
                              if rt else None),
                "beat_usd": (None if base.get("usd") is None else
                             round(float(np.mean(np.array(usd)
                                                 >= base["usd"])), 3)),
                "beat_ratio": (None if not rt or base.get("ratio") is None
                               else round(float(np.mean(
                                   np.array(rt) >= base["ratio"])), 3))}
            r = out["cells"][f"{bk}|{d}|random"]
            log(f"   контроль ({seeds} зёрен): медиана денег {r['usd']} $, "
                f"бьют фильтр {r['beat_usd']}")
    out["secs"] = round(time.time() - t0, 1)
    return out


def run_supply(log=print, ctx=None, cache=None, keys=None, now=None,
               launch=None, days=14, dep=None):
    """Подача по суткам у всех книг семейства."""
    keys = list(keys or R.H24_ORDER)
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    shorts, why = PR.short_recs(cache, log=log)
    if why or not shorts:
        why = why or "позиций коротких книг нет"
        log(f"подача не считается: {why}")
        return {"error": why}
    out = {"books": {}, "launch_known": len(launch),
           "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    for bk in keys:
        out["books"][bk] = supply(shorts.get(bk) or [], bk, ctx, launch,
                                  days=days, dep=dep, now=now)
        b = out["books"][bk]
        log(f"{bk}: сделок под правилом {b['n']}, без правила {b['n_free']}")
    return out


def supply_report(s):
    L = ["# Подача листа коротких книг по суткам", "",
         "Вопрос владельца 2026-09-08: «шорт-сделки не открываются на "
         "графике». Тишина бывает двух родов, и это разные болезни: "
         "листа не подают — или правило режет то, что подали. Здесь "
         "считается и то, и другое, по суткам, на депозите "
         + (f"${(s.get('books') or {}).get(R.H24_ORDER[0], {}).get('dep', 0)}"
            if s.get("books") else "$10000") + ".", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    for bk in R.H24_ORDER:
        b = (s.get("books") or {}).get(bk)
        if not b:
            continue
        L += [f"## {R.ruler_title(bk)} (порог ≥{b['min_days']:g} сут)", "",
              f"Всего закрытых сделок под правилом {b['n']}, без "
              f"правила {b['n_free']}; открытых сейчас {b.get('open')} "
              f"против {b.get('open_free')}. В таблице «взято» — ВХОДЫ "
              "(и закрытые, и ещё открытые): вход книги со сроком 24 ч "
              "закрывается только на следующие сутки, и считать одни "
              "закрытые значило бы показывать ноль у каждых свежих "
              "суток.", "",
              "| сутки | решений на листе | моложе порога | возраст "
              "неизвестен | взято книгой | взято было бы без правила |",
              "|---|--:|--:|--:|--:|--:|"]
        for d, v in sorted((b.get("days") or {}).items()):
            L.append(f"| {d} | {v['предложено']} | {v['моложе порога']} | "
                     f"{v['возраст неизвестен']} | {v['взято']} | "
                     f"{v['взято без правила']} |")
        L.append("")
    L += ["## Как читать", "",
          "- «Решений на листе» — что подала модель за эти сутки. Мало "
          "здесь — молчит подача, и правило ни при чём.",
          "- «Взято книгой» против «взято было бы без правила» — цена "
          "самого правила, в сделках, а не в процентах за месяц.",
          "- Считается на кэше решений: прошлое не пересчитывается, "
          "числа те же, которыми живёт книга.", ""]
    return "\n".join(L)


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def report(s):
    L = ["# Правила общего счёта на отдельных коротких книгах", "",
         "Просьба владельца 2026-09-08: «нужно сделать такую же логику, "
         "как и в общих, чтобы вывести в плюс отдельно шортовые "
         "стратегии». Мерятся два объявленных правила общего счёта — "
         "фильтр возраста имени ≥ 7 суток и доля билета — на книгах "
         "`safe_h`/`optimal_h`/`aggr_h`. Порог возраста здесь НЕ "
         "подбирается: он объявлен 08.09 по сетке на этом же листе.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    L += [f"Деньги НЕТТО (издержки в каждой сделке). Момент листинга "
          f"известен у {s['launch_known']} символов справочника; имя без "
          "даты в фильтр не проходит и считается отдельной колонкой.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}.", ""]
    for bk in (R.H24_ORDER):
        L += [f"## {R.ruler_title(bk)}", "",
              "| порог | доля билета | депозит | билет | сделок | Σ $ | "
              "итог | просадка | доход/просадка |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for d in s.get("days", DAYS):
            for sh in s.get("shares", SHARES):
                for dep in s.get("deps", R.DEPOSITS):
                    c = (s.get("cells") or {}).get(
                        f"{bk}|{d}|{sh}|{int(dep)}")
                    if not c:
                        continue
                    L.append(
                        "| " + ("нет" if not d else f"≥{d} сут")
                        + f" | {sh:g}× | ${int(dep)} | "
                        f"${c.get('ticket', 0):g} | {c.get('n')} | "
                        f"{_u(c.get('usd'))} | {_p(c.get('final'))} | "
                        f"{_p(c.get('max_dd'))} | "
                        + ("—" if c.get("ratio") is None
                           else f"{c['ratio']:.2f}") + " |")
        r = (s.get("cells") or {}).get(f"{bk}|7|random") or {}
        if r:
            base = (s.get("cells") or {}).get(
                f"{bk}|7|1.0|{int(s.get('ctrl_dep', CTRL_DEP))}") or {}
            L += ["", f"**Контроль на ${int(r['dep'])}, доля 1.0×** "
                  f"({r['seeds']} зёрен): случайная выборка того же "
                  f"размера ({r['kept']} решений) даёт по деньгам медиану "
                  f"{_u(r['usd'])} $ ({_u(r['usd_p10'])}…{_u(r['usd_p90'])}) "
                  f"против {_u(base.get('usd'))} $ у фильтра; такое же или "
                  f"лучше выпадает у "
                  + ("—" if r.get("beat_usd") is None
                     else f"{100 * r['beat_usd']:.0f} %")
                  + " выборок по деньгам и "
                  + ("—" if r.get("beat_ratio") is None
                     else f"{100 * r['beat_ratio']:.0f} %")
                  + " по отношению доход/просадка.", ""]
        else:
            L += [""]
    L += ["## Как читать", "",
          "- Строка «нет» при доле 1.0× — книга как она есть сегодня; с "
          "ней и сравнивается всё остальное.",
          "- Доля билета не меняет знак средней сделки: она режет и "
          "доход, и просадку. Смотреть на неё стоит по столбцу "
          "доход/просадка, а не по деньгам.",
          "- На депозите $1 000 билет упирается в биржевой пол, и доля "
          "там не кусается — это видно по колонке «билет».",
          "- Контроль отвечает на один вопрос: отбор это или просто "
          "меньше сделок. Возраст что-то отбирает только там, где доля "
          "«бьют фильтр» мала.",
          "- Ячейка становится правилом только объявленной заранее и "
          "проверенной вперёд; окно одно, веса модели эти часы видели.",
          ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="правила общего счёта на "
                                             "отдельных коротких книгах")
    ap.add_argument("--seeds", type=int, default=None)
    # Отдельный вопрос владельца («шорт-сделки не открываются»): сетка на
    # него не отвечает — она судит месяц целиком. Подача считается по
    # СУТКАМ и стоит секунды, поэтому у неё свой режим.
    ap.add_argument("--only-supply", action="store_true",
                    help="только подача листа по суткам, без сетки")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    if a.only_supply:
        s = run_supply()
        art = os.path.join(R.OUT, "DCA-short-supply.json")
        with open(art + ".tmp", "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
        os.replace(art + ".tmp", art)
        txt = supply_report(s)
        with open(os.path.join(R.OUT, "DCA-short-supply.md"), "w",
                  encoding="utf-8") as f:
            f.write(txt)
        print(txt)
        publish("подача листа коротких книг по суткам")
        return 0
    s = run(seeds=a.seeds)
    art = os.path.join(R.OUT, "DCA-short-age.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-short-age.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    publish("правила общего счёта на отдельных коротких книгах")
    return 0


if __name__ == "__main__":
    sys.exit(main())
