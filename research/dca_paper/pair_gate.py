#!/usr/bin/env python3
"""Два входных фильтра короткой стороны общего счёта — на одной сетке.

Просьба владельца 2026-09-07: «давай проверим [гейт по ставке funding
для шортов]. Затести ещё, если открывать только шорт-сделки по тем
именам, которые у нас в лонге, или наоборот, не открывать те, которые в
лонге».

Оси объявлены ДО прогона, и меряется вся сетка, а не лучшая ячейка.

**Ось имён** — что делать с монетой, которую длинная книга держит В ЭТОТ
МОМЕНТ (момент решения, без заглядывания вперёд: позиция открыта раньше
и ещё не закрыта):

* `all` — как сейчас: имя длинной стороны шорту не мешает (хедж);
* `only_long` — шортим ТОЛЬКО такие имена (настоящий хедж по имени);
* `not_long` — шортим только ОСТАЛЬНЫЕ;
* `random` — случайное подмножество РОВНО того же размера, что
  `only_long`. Без него «меньше сделок» и «лучше отбор» неразличимы:
  совпадений имён у нас 3–5 %, и любая узкая полоса будет выглядеть
  иначе просто потому, что она узкая.

**Ось ставки funding на входе** — брать ли шорт, когда ставка площадки
против него:

* `off` — как сейчас;
* `on` — вход только при ставке, БЛАГОПРИЯТНОЙ шорту (положительная:
  лонги платят шортам), и только если ставка свежая (не старше суток —
  тот же срок, что в замере издержек). Ставка неизвестна — входа нет, и
  число таких отказов печатается: «не измерено» не превращается в
  «разрешено».

Считается ОБЩИЙ счёт (одна касса, билеты сторон те же, что в живых
книгах), деньги — НЕТТО, издержки в каждой сделке. Журнал книг замер не
трогает: это проба, а не книга.

Запуск: `run research/dca_paper/pair_gate.py`.
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
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_pair as PR                                         # noqa: E402
import costs as CO                                            # noqa: E402

NAMES = ("all", "only_long", "not_long", "random")
# Третье состояние оси — КОНТРОЛЬ РАЗМЕРА гейта: случайное подмножество
# ровно того размера, что оставляет гейт, но выбранное без всякой
# ставки. Без него «гейт отбирает» неотличимо от «шортов стало вдвое
# меньше, а шорты в минусе» — а это разные выводы и лечатся они разным.
GATES = ("off", "on", "random")
SEED = 20260907          # объявлен здесь, а не выбран после прогона
# Контроль размера считается на МНОЖЕСТВЕ зёрен: одна случайная выборка
# сама по себе шум — на первом прогоне два контроля почти одного размера
# дали +1836 и +270 $, и по такому «нулю» судить нельзя. Двадцать зёрен
# дают медиану, полосу и долю выборок, которые бьют гейт.
SEEDS = 20


def held_intervals(rows, dep):
    """Что длинная книга ДЕРЖАЛА: имя → список (вход, выход).

    Берутся строки книги того же депозита: «у нас в лонге» — это про
    книгу, которой торгуют, а не про все решения листа.
    """
    out = {}
    for r in rows:
        if int(float(r.get("dep") or 0)) != int(dep):
            continue
        try:
            out.setdefault(r["sym"], []).append((float(r["at"]),
                                                 float(r["exit_ts"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def in_long(held, sym, at):
    """Держала ли длинная книга это имя В МОМЕНТ решения.

    Условие «открыта раньше и ещё не закрыта» известно в сам момент: то,
    что позиция закроется позже, знать не требуется.
    """
    for (a, b) in held.get(sym, ()):
        if a <= at < b:
            return True
    return False


def gate_rate(rec, ctx):
    """Ставка площадки на входе и годится ли она шорту.

    Возвращает (ставка, годится). Ставки нет — (None, None): это отказ
    по незнанию, и он считается отдельно от отказа по знаку.
    """
    to_asset = (ctx or {}).get("to_asset") or {}
    funding = (ctx or {}).get("funding") or {}
    a = to_asset.get(rec.get("sym"))
    s = funding.get(a) if a else None
    if s is None:
        return None, None
    rate = CO.rate_at_entry(s, rec.get("at"))
    if rate is None:
        return None, None
    return rate, bool(CO.favourable("short", rate))


def pick(shorts, held, ctx, names="all", gate="off", seed=SEED):
    """Короткие решения после обоих фильтров плюс счётчики отказов."""
    why = {"по имени": 0, "по ставке": 0, "ставка неизвестна": 0}
    keep = []
    for r in shorts:
        sym, at = r.get("sym"), float(r.get("at") or 0.0)
        if names in ("only_long", "not_long"):
            got = in_long(held, sym, at)
            if (names == "only_long") != bool(got):
                why["по имени"] += 1
                continue
        if gate == "on":
            rate, ok = gate_rate(r, ctx)
            if ok is None:
                why["ставка неизвестна"] += 1
                continue
            if not ok:
                why["по ставке"] += 1
                continue
        keep.append(r)
    if gate == "random":
        # столько же, сколько оставил бы гейт, но без всякой ставки
        n = len(pick(shorts, held, ctx, names if names != "random" else "all",
                     "on", seed)[0])
        rs = np.random.default_rng(seed + 1)
        idx = sorted(rs.choice(len(keep), size=min(n, len(keep)),
                               replace=False).tolist()) if keep else []
        why["контроль размера"] = len(keep) - len(idx)
        keep = [keep[i] for i in idx]
    if names == "random":
        # ровно столько же, сколько оставляет `only_long`, и на объявленном
        # зерне: контроль размера, а не удачи
        n = len(pick(shorts, held, ctx, "only_long", gate, seed)[0])
        rs = np.random.default_rng(seed)
        idx = sorted(rs.choice(len(keep), size=min(n, len(keep)),
                               replace=False).tolist()) if keep else []
        why["по имени"] = len(keep) - len(idx)
        keep = [keep[i] for i in idx]
    return keep, why


def cell(longs, shorts, pk, dep, ctx, now=None, log=lambda *a: None):
    """Общий счёт на этих решениях: деньги НЕТТО, просадка, состав."""
    packed = PR.pack({R.parts_of(pk)[0]: longs},
                     {R.parts_of(pk)[1]: shorts}, keys=[pk])
    rows, cells, one, _live = RP.build_rows(packed, now=now, keys=[pk],
                                            log=log)
    mine = [r for r in rows if int(r.get("dep", 0)) == int(dep)]
    if ctx is not None and not ctx.get("error"):
        mine, _c = CO.apply_to_rows(mine, ctx)
    st = RP._stats(mine, dep) or {}
    lk, sk = R.parts_of(pk)
    side = {k: RP._stats([r for r in mine if (r.get("book") or pk) == k], dep)
            for k in (lk, sk)}
    c = cells.get(RP._cell(pk, dep)) or {}
    # Доход НА ПРОСАДКУ — то, чем читается книга: 20 % при −5 % и 20 %
    # при −20 % это разные книги. Просадки нет — отношения не
    # существует, и это прочерк, а не бесконечность.
    fin, dd = st.get("final"), st.get("max_dd")
    ratio = (None if not fin or not dd else round(float(fin) / abs(float(dd)), 2))
    return {"n": st.get("n"), "usd": st.get("usd"), "final": st.get("final"),
            "max_dd": st.get("max_dd"), "win": st.get("win"), "ratio": ratio,
            "n_long": (side[lk] or {}).get("n"),
            "n_short": (side[sk] or {}).get("n"),
            "usd_long": (side[lk] or {}).get("usd"),
            "usd_short": (side[sk] or {}).get("usd"),
            "no_cash": c.get("no_cash"), "taken": c.get("taken")}


def run(dep=None, log=print, ctx=None, long_cache=None, short_cache=None,
        long_journal=None, keys=None, now=None):
    t0 = time.time()
    dep = float(dep or R.DEPOSITS[1])
    keys = list(keys or R.PAIR_ORDER)
    ctx = ctx if ctx is not None else CO.context()
    longs, why_l = PR.long_recs(long_cache, log=log)
    shorts, why_s = PR.short_recs(short_cache, log=log)
    if why_l or why_s or not longs or not shorts:
        why = why_l or why_s or "позиций в кэшах нет"
        log(f"замер не считается: {why}")
        return {"error": why, "dep": dep}
    jrows, _bad = R.read_journal(long_journal or R.JOURNAL)
    jrows = [r for r in jrows if R.is_current(r)]
    out = {"dep": dep, "seed": SEED, "cells": {}, "drops": {},
           "costs_error": (ctx or {}).get("error"),
           "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    for pk in keys:
        lk, sk = R.parts_of(pk)
        held = held_intervals([r for r in jrows if R.ruler_of(r) == lk], dep)
        lrec, srec = longs.get(lk) or [], shorts.get(sk) or []
        out.setdefault("held", {})[pk] = {"names": len(held),
                                          "positions": sum(len(v) for v
                                                           in held.values())}
        for nm in NAMES:
            for g in GATES:
                if g == "random" and nm in ("all", "not_long"):
                    # Контроль размера — РАСПРЕДЕЛЕНИЕМ по зёрнам, а не
                    # одной выборкой: одна ничего не говорит. У узких
                    # политик имён гейт почти не меняет состав, и там
                    # контролю нечего судить.
                    got = []
                    for k in range(SEEDS):
                        keep, why = pick(srec, held, ctx, nm, g,
                                         seed=SEED + 100 * k)
                        got.append(cell(lrec, keep, pk, dep, ctx, now=now))
                    base = out["cells"].get(f"{pk}|{nm}|on") or {}
                    usd = [x["usd"] or 0.0 for x in got]
                    sh = [x["usd_short"] or 0.0 for x in got]
                    dd = [x["max_dd"] or 0.0 for x in got]
                    beat = (None if base.get("usd") is None
                            else round(float(np.mean(np.array(usd)
                                                     >= base["usd"])), 3))
                    # То же по ОТНОШЕНИЮ доход/просадка: замечание
                    # владельца о том, что гейт «выглядит лучше», — это
                    # про него, и проверяется он тем же контролем.
                    rt = [x["ratio"] for x in got if x.get("ratio") is not None]
                    beat_r = (None if not rt or base.get("ratio") is None
                              else round(float(np.mean(np.array(rt)
                                                       >= base["ratio"])), 3))
                    out["cells"][f"{pk}|{nm}|{g}"] = {
                        "pair": pk, "names": nm, "gate": g, "seeds": SEEDS,
                        "offered": len(srec), "kept": len(keep), "drops": why,
                        "usd": round(float(np.median(usd)), 2),
                        "usd_p10": round(float(np.quantile(usd, 0.1)), 2),
                        "usd_p90": round(float(np.quantile(usd, 0.9)), 2),
                        "usd_short": round(float(np.median(sh)), 2),
                        "max_dd": round(float(np.median(dd)), 4),
                        "final": round(float(np.median(usd)) / dep, 4),
                        "n": int(np.median([x["n"] or 0 for x in got])),
                        "n_short": int(np.median([x["n_short"] or 0
                                                  for x in got])),
                        "ratio": (round(float(np.median(rt)), 2) if rt else None),
                        "ratio_p10": (round(float(np.quantile(rt, 0.1)), 2)
                                      if rt else None),
                        "ratio_p90": (round(float(np.quantile(rt, 0.9)), 2)
                                      if rt else None),
                        "beat_gate": beat, "beat_gate_ratio": beat_r}
                    log(f"{pk} {nm}/контроль ({SEEDS} зёрен): медиана "
                        f"{out['cells'][f'{pk}|{nm}|{g}']['usd']} $, "
                        f"бьют гейт по деньгам {beat}, по отношению "
                        f"{beat_r}")
                    continue
                keep, why = pick(srec, held, ctx, nm, g)
                c = cell(lrec, keep, pk, dep, ctx, now=now)
                out["cells"][f"{pk}|{nm}|{g}"] = dict(
                    c, pair=pk, names=nm, gate=g, offered=len(srec),
                    kept=len(keep), drops=why)
                log(f"{pk} {nm}/{g}: коротких решений {len(keep)} из "
                    f"{len(srec)}, счёт {c.get('usd')} $, просадка "
                    f"{c.get('max_dd')}")
    out["secs"] = round(time.time() - t0, 1)
    return out


def _u(x):
    return "—" if x is None else f"{float(x):+.2f}"


def _p(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def report(s):
    L = ["# Входные фильтры короткой стороны: имена и ставка funding", "",
         "Просьба владельца 2026-09-07: проверить гейт по ставке funding "
         "для шортов и три политики по именам — шортить только то, что "
         "держит длинная книга; не шортить то, что она держит; или как "
         "сейчас. Оси объявлены до прогона, печатается ВСЯ сетка.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    dep = int(s["dep"])
    L += [f"Общий счёт, депозит ${dep:,}, деньги НЕТТО (издержки в каждой "
          "сделке). Журнал книг замер не трогает.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки не вычтены:** {s['costs_error']}. Деньги — "
              "брутто.", ""]
    L += ["| книга | имена | ставка | коротких взято | из них длинных | "
          "сделок | Σ $ (у контроля медиана и полоса p10…p90) | "
          "к депозиту | просадка | **доход на просадку** | Σ $ шорта | "
          "доля контроля (деньги / отношение) |",
          "|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    для_имени = {"all": "все", "only_long": "только те, что в лонге",
                 "not_long": "кроме тех, что в лонге",
                 "random": "случайные (столько же, сколько «только»)"}
    for pk in (R.PAIR_ORDER):
        for nm in NAMES:
            for g in GATES:
                c = (s.get("cells") or {}).get(f"{pk}|{nm}|{g}")
                if not c:
                    continue
                L.append(
                    f"| {R.ruler_title(pk)} | {для_имени[nm]} | "
                    + {"on": "гейт", "off": "любая",
                       "random": "случайно столько же"}[g]
                    + f" | {c['kept']} из {c['offered']} | "
                    f"{c.get('n_short') or 0} | {c.get('n') or 0} | "
                    f"{_u(c.get('usd'))}"
                    + (f" ({_u(c['usd_p10'])}…{_u(c['usd_p90'])})"
                       if c.get("seeds") else "")
                    + f" | {_p(c.get('final'), 2)} | "
                    f"{_p(c.get('max_dd'))} | "
                    + ("—" if c.get("ratio") is None else f"{c['ratio']:.2f}")
                    + (f" ({c['ratio_p10']:.2f}…{c['ratio_p90']:.2f})"
                       if c.get("ratio_p10") is not None else "")
                    + f" | {_u(c.get('usd_short'))} | "
                    + (f"{100 * c['beat_gate']:.0f} % / "
                       + ("—" if c.get("beat_gate_ratio") is None
                          else f"{100 * c['beat_gate_ratio']:.0f} %")
                       if c.get("beat_gate") is not None
                       else _u(c.get('usd_long'))) + " |")
    L += ["", "Отказы по причинам (на ячейку «все имена, гейт»): ", ""]
    for pk in R.PAIR_ORDER:
        c = (s.get("cells") or {}).get(f"{pk}|all|on")
        if not c:
            continue
        d = c.get("drops") or {}
        L.append(f"- {R.ruler_title(pk)}: по ставке {d.get('по ставке', 0)}, "
                 f"ставка неизвестна {d.get('ставка неизвестна', 0)}; "
                 f"длинная книга держала {(s.get('held') or {}).get(pk, {}).get('names', 0)} имён.")
    L += ["", "## Как читать", "",
          "- Строка «случайные» — КОНТРОЛЬ размера: она берёт ровно "
          "столько же коротких решений, сколько «только те, что в лонге», "
          "на объявленном зерне. Без неё «лучше отбор» и «меньше сделок» "
          "неразличимы.",
          f"- Строка «случайно столько же» — КОНТРОЛЬ гейта на {SEEDS} "
          "зёрнах: столько же коротких решений, сколько оставляет гейт, "
          "но выбранных без всякой ставки. Печатается медиана, полоса "
          "p10…p90 и доля выборок, которые ГЕЙТ НЕ ПОБИЛ — отдельно по "
          "деньгам и отдельно по ОТНОШЕНИЮ доход/просадка. Гейт отбирает "
          "только там, где эта доля мала; по одной случайной выборке "
          "вывода нет.",
          "- Отношение доход/просадка считается на КАЖДОЙ выборке, а не "
          "как частное медиан: медиана денег и медиана просадки бывают у "
          "разных выборок, и их частное не описывает ни одну книгу.",
          "- Гейт по ставке отказывает и тогда, когда ставка неизвестна: "
          "это отказ по незнанию, он считается отдельной колонкой и НЕ "
          "смешивается с отказом по знаку.",
          "- Ячейка становится правилом, только будучи объявленной "
          "заранее и проверенной вперёд: сетка отвечает на вопрос «есть "
          "ли там что-нибудь», а не выбирает победителя.",
          "- Окно одно и режим рынка один; веса модели видели эти часы, "
          "и это оценка СВЕРХУ.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="фильтры короткой стороны")
    ap.add_argument("--dep", type=float, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run(dep=a.dep)
    art = os.path.join(R.OUT, "DCA-pair-gate.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-pair-gate.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("фильтры короткой стороны: имена и ставка funding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
