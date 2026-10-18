#!/usr/bin/env python3
"""Фильтр входа на признаках, без модели (владелец 2026-10-18: «ИИ фильтрует
сделки — решает, какие из потока открывать» → «давай» первый шаг: дешёвый
замер на признаках). Если простой фильтр на видимых при входе числах ничего
не даёт, ИИ с теми же числами тоже не даст; если даёт — он честный соперник,
которого ИИ обязан бить.

ОБЪЯВЛЕНО ДО ПРОГОНА (признаки, направления, доли, нуль и критерий не
меняются после просмотра; право на итерацию одно):

Книги — длинные `safe`/`optimal`/`aggr` и короткие `safe_h`/`optimal_h`/
`aggr_h` как живут (у коротких — возраст имени и охрана рынком); общий
счёт не берётся — он собран из тех же сторон.

Признаки при входе, направление «больше — подозрительнее»:
* `lev` — плечо позиции;
* `weak` — слабость обещания модели: −fav_bp;
* `against24` — ход имени за 24 ч до входа ПРОТИВ позиции (шорту — рост,
  лонгу — падение);
* `wave_against24` — ход рынка за 24 ч до входа против позиции;
* `beta` — β имени к рынку по 72 ч до входа.
Не берутся: funding (ряд площадки покрывает журнал книг не целиком —
урок A1: «не измерено» внутри фильтра само становится фильтром), время
суток (у него нет направления).

Фильтр — убрать из потока книги долю q ∈ {10, 20, 30 %} решений с
наибольшим признаком. ПОРОГ — квантиль по ПЕРВОЙ половине записи (по
моменту решения), применяется к ВТОРОЙ как есть: на второй половине порог
не видел её данных.

Деньги — касса тем же ядром (`run_paper.build_rows`): убранное решение
освобождает слот, и касса берёт следующее (урок 03.10: оценка по журналу
без кассы врёт). $1k и $10k, сложный процент, брутто (фильтр сделок не
добавляет — издержки на круг те же или меньше).

Нуль — случайное отсечение ТОГО ЖЕ числа решений в том же окне, `--seeds`
зёрен (урок: фильтр, режущий сделки, сравнивается со случайной выборкой
того же размера).

КРИТЕРИЙ кандидата (на ВТОРОЙ половине, порог от первой): касса $10k выше,
чем без фильтра, у ВСЕХ трёх книг стороны, И случайное отсечение того же
размера не хуже фильтра не более чем в 10 % зёрен у каждой книги; и на
первой половине (там порог подогнан — это верхняя оценка) знак тот же.

Ничего не меняет: книги, журналы и кэши не пишутся.

    run research/dca_paper/entry_filter.py --seeds=20
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
import wave as WV                                             # noqa: E402
import arm_book as AB                                         # noqa: E402
import long_guard as LG                                       # noqa: E402
import exit_ceiling as EC                                     # noqa: E402

OUT_MD = os.path.join(R.OUT, "DCA-entry-filter.md")
OUT_JSON = os.path.join(R.OUT, "DCA-entry-filter.json")
DEPS = LG.DEPS
HOUR = 3600.0
FEATS = ("lev", "weak", "against24", "wave_against24", "beta")
FEAT_TITLE = {"lev": "плечо выше", "weak": "обещание модели слабее",
              "against24": "имя за 24 ч до входа шло против позиции",
              "wave_against24": "рынок за 24 ч до входа шёл против позиции",
              "beta": "β к рынку выше"}
CUTS = (0.10, 0.20, 0.30)
MEM_LIMIT_MB = 3000


def feats_of(r, side, mkt, cache):
    """Признаки решения при входе (только прошлое). Нет данных — None."""
    at = float(r["at"])
    sym = r.get("sym")
    key = (sym, int(round(at)))
    if key not in cache:
        t_in = at - 1.0
        b, _rho, _n = mkt.beta_pre(sym, at)
        cache[key] = {"beta": b, "pre": mkt.move(sym, t_in - 24 * HOUR, t_in),
                      "wpre": mkt.wave(t_in - 24 * HOUR, t_in)}
    c = cache[key]
    sgn = 1.0 if side == "short" else -1.0              # «против позиции»
    fav = r.get("fav_bp")
    lev = r.get("lev")
    return {"lev": float(lev) if lev else None,
            "weak": (-float(fav) if fav is not None else None),
            "against24": (sgn * c["pre"]) if c["pre"] is not None else None,
            "wave_against24": (sgn * c["wpre"]) if c["wpre"] is not None else None,
            "beta": c["beta"]}


def threshold(values, q):
    """Порог «верхние q»: решения со значением > порога убираются."""
    xs = sorted(v for v in values if v is not None)
    if len(xs) < 20:
        return None
    return xs[min(len(xs) - 1, int((1.0 - q) * len(xs)))]


def apply_filter(recs, fts, feat, thr):
    """Убрать решения с признаком > порога. Признак не измерен — решение
    ОСТАЁТСЯ (неизмеренное не отсекается — иначе «не измерено» само стало бы
    фильтром) и считается числом."""
    keep, cut, unmeasured = [], 0, 0
    for r, f in zip(recs, fts):
        v = f.get(feat)
        if v is None:
            unmeasured += 1
            keep.append(r)
        elif thr is not None and v > thr:
            cut += 1
        else:
            keep.append(r)
    return keep, cut, unmeasured


def random_cut(recs, n, rng):
    if n <= 0 or n >= len(recs):
        return list(recs)
    drop = set(rng.sample(range(len(recs)), n))
    return [r for i, r in enumerate(recs) if i not in drop]


def judge_side(books, side, keys, now, seeds, log, t0):
    """Пороги — по первой половине; касса — в обеих половинах; нуль — случайное
    отсечение того же числа решений в каждом окне."""
    mkt = WV.Market(WV.Hours())
    cache = {}
    fts = {}
    for k in keys:
        fts[k] = [feats_of(r, side, mkt, cache) for r in books[k]]
        log(f"{side}: признаки {k} — {len(fts[k])} решений ({time.time() - t0:.0f} с)")
    ats = sorted(float(r["at"]) for k in keys for r in books[k])
    mid = ats[len(ats) // 2]
    halves = {"half1": lambda r: float(r["at"]) < mid, "half2": lambda r: float(r["at"]) >= mid}
    part, pf = {}, {}
    for w, inside in halves.items():
        part[w] = {k: [r for r in books[k] if inside(r)] for k in keys}
        pf[w] = {k: [f for r, f in zip(books[k], fts[k]) if inside(r)] for k in keys}
    out = {"mid": mid, "keys": keys, "cells": {}, "base": {}, "null": {}}
    for w in halves:
        out["base"][w] = LG.cash(part[w], keys, now)
    log(f"{side}: касса без фильтра ({time.time() - t0:.0f} с)")
    for feat in FEATS:
        for q in CUTS:
            thr = {k: threshold([f.get(feat) for f in pf["half1"][k]], q) for k in keys}
            cell = {"thr": thr, "windows": {}}
            for w in halves:
                by, cuts, unm = {}, {}, {}
                for k in keys:
                    by[k], cuts[k], unm[k] = apply_filter(part[w][k], pf[w][k], feat, thr[k])
                cell["windows"][w] = {"cash": LG.cash(by, keys, now), "cut": cuts, "unmeasured": unm,
                                      "n": {k: len(part[w][k]) for k in keys}}
            out["cells"][f"{feat}:{int(q * 100)}"] = cell
        log(f"{side}: признак {feat} — 3 доли посчитаны ({time.time() - t0:.0f} с)")
    # нуль: случайное отсечение того же числа решений, что убрал КАЖДЫЙ фильтр,
    # дорого (по ячейке); число убранных у фильтров близко к q·n — нуль считается
    # на доле q от решений книги в окне и сверяется с фактическим числом в отчёте
    for q in CUTS:
        for w in halves:
            draws = []
            for sd in range(seeds):
                rng = random.Random(7000 + sd + int(q * 1000))
                by = {k: random_cut(part[w][k], int(round(q * len(part[w][k]))), rng) for k in keys}
                draws.append(LG.cash(by, keys, now))
            out["null"][f"{int(q * 100)}:{w}"] = {
                k: {int(d): [((x[k][int(d)] or {}).get("final")) for x in draws] for d in DEPS}
                for k in keys}
        log(f"{side}: нуль {int(q * 100)} % — {seeds} зёрен ×2 окна ({time.time() - t0:.0f} с)")
    out["verdict"] = verdict(out)
    return out


def verdict(out):
    """Критерий, объявленный до прогона."""
    keys = out["keys"]
    res = {}
    for name, cell in out["cells"].items():
        q = name.split(":")[1]
        ok2, ok1, nulls = True, True, {}
        for k in keys:
            f2 = ((cell["windows"]["half2"]["cash"].get(k) or {}).get(10000) or {}).get("final")
            b2 = ((out["base"]["half2"].get(k) or {}).get(10000) or {}).get("final")
            f1 = ((cell["windows"]["half1"]["cash"].get(k) or {}).get(10000) or {}).get("final")
            b1 = ((out["base"]["half1"].get(k) or {}).get(10000) or {}).get("final")
            xs = [x for x in (out["null"].get(f"{q}:half2", {}).get(k, {}).get(10000) or []) if x is not None]
            share = (sum(1 for x in xs if f2 is not None and x >= f2) / len(xs)) if xs else None
            nulls[k] = share
            if f2 is None or b2 is None or f2 <= b2 or share is None or share > 0.10:
                ok2 = False
            if f1 is None or b1 is None or f1 <= b1:
                ok1 = False
        res[name] = {"candidate": ok2 and ok1, "half2_ok": ok2, "half1_same_sign": ok1,
                     "null_not_worse": nulls}
    return res


def run(seeds, log):
    t0 = time.time()
    R.DEPOSITS[:] = list(DEPS)
    R.SIZINGS = (R.SIZING_COMPOUND,)
    data, why = EC.load(log)
    if why:
        return {"error": why}
    now = data["now"]
    books = data["books"]
    sides = {"short": [k for k in books if R.side_of(k) == "short"],
             "long": [k for k in books if R.side_of(k) == "long"]}
    res = {"seeds": seeds, "cuts": list(CUTS), "feats": list(FEATS), "sides": {}}
    for side, keys in sides.items():
        if keys:
            res["sides"][side] = judge_side(books, side, keys, now, seeds, log, t0)
    res["secs"] = round(time.time() - t0, 1)
    res["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return res


def _pp(x):
    return LG._pp(x)


def report(res):
    if res.get("error"):
        return f"# Фильтр входа на признаках\n\nНе посчитано: {res['error']}.\n"
    L = ["# Фильтр входа на признаках: убрать подозрительные решения из потока", "",
         "Признаки, направления, доли, нуль и критерий объявлены ДО прогона (`entry_filter.py`). Порог — "
         "квантиль по ПЕРВОЙ половине записи, на вторую переносится как есть. Касса тем же ядром: убранное "
         f"решение освобождает слот. Нуль — случайное отсечение той же доли решений, {res['seeds']} зёрен. "
         "Деньги брутто. Признак не измерен — решение остаётся (число таких названо).", "",
         "**Критерий кандидата:** на второй половине касса $10k выше, чем без фильтра, у всех трёх книг стороны, "
         "и случайное отсечение того же размера не хуже фильтра не более чем в 10 % зёрен у каждой; на первой "
         "половине знак тот же.", ""]
    for side, s in res["sides"].items():
        keys = s["keys"]
        L += [f"## {'КОРОТКИЕ' if side == 'short' else 'ДЛИННЫЕ'} книги", ""]
        cand = [n for n, v in s["verdict"].items() if v["candidate"]]
        L += ["**Кандидаты:** " + (", ".join(f"`{n}`" for n in cand) if cand else "нет") + ".", ""]
        for w, wt in (("half2", "Вторая половина — СУД (порог от первой)"),
                      ("half1", "Первая половина — порог подогнан здесь (верхняя оценка)")):
            L += [f"### {wt}", "",
                  "| фильтр | " + " | ".join(f"{R.title_en(k)} $1k | {R.title_en(k)} $10k" for k in keys) +
                  " | убрано решений | случайное не хуже, $10k |",
                  "|---|" + "--:|" * (2 * len(keys)) + "---|---|"]
            base = s["base"][w]
            L.append("| без фильтра | " + " | ".join(
                f"{_pp(((base.get(k) or {}).get(1000) or {}).get('final'))} | "
                f"{_pp(((base.get(k) or {}).get(10000) or {}).get('final'))}" for k in keys) + " | — | — |")
            for q in CUTS:
                nq = s["null"].get(f"{int(q * 100)}:{w}", {})
                L.append(f"| случайно −{int(q * 100)} % (среднее) | " + " | ".join(
                    " | ".join(_pp((lambda xs: sum(xs) / len(xs) if xs else None)(
                        [x for x in (nq.get(k, {}).get(int(d)) or []) if x is not None])) for d in DEPS)
                    for k in keys) + " | — | — |")
            for name, cell in s["cells"].items():
                feat, q = name.split(":")
                c = cell["windows"][w]
                share = []
                for k in keys:
                    f = ((c["cash"].get(k) or {}).get(10000) or {}).get("final")
                    xs = [x for x in (s["null"].get(f"{q}:{w}", {}).get(k, {}).get(10000) or []) if x is not None]
                    share.append("—" if f is None or not xs else
                                 "%d %%" % round(100 * sum(1 for x in xs if x >= f) / len(xs)))
                cut = ", ".join(f"{c['cut'][k]}/{c['n'][k]}" + (f" (не измерено {c['unmeasured'][k]})"
                                                               if c['unmeasured'][k] else "") for k in keys)
                L.append(f"| −{q} % · {FEAT_TITLE[feat]} | " + " | ".join(
                    f"{_pp(((c['cash'].get(k) or {}).get(1000) or {}).get('final'))} | "
                    f"{_pp(((c['cash'].get(k) or {}).get(10000) or {}).get('final'))}" for k in keys) +
                    f" | {cut} | {', '.join(share)} |")
            L.append("")
    L += ["## Чего замер НЕ говорит", "",
          "- Список признаков короткий и объявлен заранее; «кандидата нет» значит «нет среди этих». ИИ с ТЕМИ ЖЕ "
          "числами не знает больше; его возможная добавка — внешнее (новости, листинги, анлоки), а это меряется "
          "только записью вперёд.",
          "- Нуль считается на доле q от решений книги в окне; фактическое число убранных фильтром названо рядом "
          "(отличается, когда признак у части решений не измерен).",
          "- Деньги брутто; доход книг пока рыночный (15.10) — фильтр перераспределяет тот же ход.", "",
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
    print(txt[:5000])
    if not a.no_publish and not res.get("error"):
        subprocess.run(["tools/publish.sh", "замер: фильтр входа на признаках"], cwd=ROOT, check=False)
    return 0 if not res.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
