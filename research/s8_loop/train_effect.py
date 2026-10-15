#!/usr/bin/env python3
"""Что даёт обучение: качество сигнала по НОМЕРУ обучения.

Вопрос владельца 2026-10-15: «ювелирность сигналов со временем должна
расти — мы постоянно обучаемся». Старые веса не хранились, прогнать
раннюю модель по новым данным нельзя. Зато каждая строка листа сечения
помечена номером обучения (`train_seq`), а цикл каждый час пишет живой
вневыборочный IC прежних весов (`ic_history.jsonl`). Этого хватает на
два ряда «качество против номера обучения»:

1. **Позиции Ladder по обучениям.** Решения реплея (кэш `run_paper`,
   линейка Depth — геометрия одна на всех) разложены по номеру обучения,
   которое написало лист того часа: средний и медианный исход позиции
   (доля маржи), доля прибыльных, доля полов. Это сигнал, прошедший
   гейты книги, ДО кассы — касса отбирает по-своему, и судить сигнал по
   ней нельзя (урок 08.10).
2. **Живой IC по обучениям** — та мера, которой цикл судит себя сам.

Тренд — ранговая корреляция (Спирмен) номера обучения с показателем;
нуль — перестановка номеров между часами, 500 раз: доля нулей с
|ρ| не меньше наблюдённого. Половины — первая и вторая половина
обучений, средние с ошибкой среднего. Ничего не меняет.

    run research/s8_loop/train_effect.py
"""
import collections
import json
import os
import random
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import train as T                                             # noqa: E402
import trades as TR                                           # noqa: E402

OUT_MD = os.path.join(HERE, "out", "TRAIN-effect.md")
OUT_JSON = os.path.join(HERE, "out", "TRAIN-effect.json")
SHEETS = os.path.join(T.MODEL_DIR + "_sit", "sheets.jsonl")
IC_HISTORY = os.path.join(T.MODEL_DIR, "ic_history.jsonl")
N_PERM = 500


def hour_to_seq(path, log):
    """Час листа → номер обучения; плюс первый час каждого обучения."""
    out, first = {}, {}
    n = 0
    try:
        fh = open(path, encoding="utf-8")
    except OSError as e:
        log(f"лист сечения не читается: {e}")
        return out, first
    with fh:
        for line in fh:
            # строка листа — мегабайт; номер и час стоят в её начале
            head = line[:400]
            i = head.find('"train_seq"')
            j = head.find('"hour"')
            if i < 0 or j < 0:
                continue
            try:
                hour = head[j:].split('"')[3]
                seq = int(head[i:].split(":")[1].split(",")[0].strip().strip("}"))
            except (IndexError, ValueError):
                continue
            ts = TR._ts(hour)
            if not ts:
                continue
            out[int(ts)] = seq
            first.setdefault(seq, hour)
            n += 1
    log(f"лист сечения: {n} часов, обучений {len(first)}")
    return out, first


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3:
        return None
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def trend(seqs, vals, groups_by_hour, rng):
    """ρ номера обучения с показателем и нуль перестановкой номеров по часам.

    `groups_by_hour`: {час: [значения]} — перестановка переназначает
    ЧАСАМ номера обучений (блоками того же размера), пересчитывает
    средние по номерам и ρ. Переставлять позиции внутри обучения нельзя:
    правило зависит от того, какой час каким обучением считан.
    """
    rho = spearman(seqs, vals)
    if rho is None:
        return None, None
    null = []
    hour_seq = groups_by_hour["__seq__"]
    hs = sorted(h for h in groups_by_hour if h != "__seq__")
    seq_list = [hour_seq[h] for h in hs]
    for _ in range(N_PERM):
        perm = list(seq_list)
        rng.shuffle(perm)
        acc = collections.defaultdict(list)
        for h, sq in zip(hs, perm):
            acc[sq].extend(groups_by_hour[h])
        ks = sorted(acc)
        r = spearman(ks, [float(np.mean(acc[k])) for k in ks])
        if r is not None:
            null.append(abs(r))
    p = (sum(1 for r in null if r >= abs(rho)) / len(null)) if null else None
    return rho, p


def positions_by_seq(h2s, log):
    import run_paper as RP
    import rules as R
    cache, why = RP.read_cache()
    if why or not cache:
        log(f"кэш реплея не читается: {why or 'пуст'}")
        return None
    pair = tuple(RP.RULERS["optimal"])
    by_hour = collections.defaultdict(list)
    recs = {}
    for (pr, sym, at), r in cache.items():
        if tuple(pr) != pair:
            continue
        recs[(sym, round(float(at), 3))] = r
    for (sym, at), r in recs.items():
        h = int(at) - int(at) % 3600
        sq = h2s.get(h)
        if sq is None:
            continue
        by_hour[h].append((sq, float(r["pnl"]), r.get("exit"), float(r["lev"])))
    log(f"позиций Depth в кэше {len(recs)}, с номером обучения "
        f"{sum(len(v) for v in by_hour.values())}")
    return by_hour


def ic_by_seq(log):
    rows = []
    try:
        with open(IC_HISTORY, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("target") == f"fwd_{T.SIT_SIGNAL_H}h" and r.get("median_ic") is not None:
                    rows.append(r)
    except OSError as e:
        log(f"история IC не читается: {e}")
    log(f"история живого IC: {len(rows)} строк")
    return rows


def _p(v, d=2):
    return "—" if v is None else f"{v * 100:+.{d}f} %"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    log = print
    t0 = time.time()
    rng = random.Random(20261015)
    h2s, first = hour_to_seq(SHEETS, log)
    res = {"computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
    L = ["# Что даёт обучение: качество сигнала по номеру обучения", "",
         "Каждый час лист сечения помечен номером обучения, которым посчитан. Ниже — исходы "
         "позиций Ladder (линейка Depth, кэш реплея, ДО кассы и издержек) по этим номерам и "
         "живой вневыборочный IC прежних весов из `ic_history.jsonl`. Тренд — ранговая "
         f"корреляция номера с показателем; нуль — {N_PERM} перестановок номеров между часами.", ""]

    # --- 1. позиции по обучениям
    by_hour = positions_by_seq(h2s, log)
    if by_hour:
        acc = collections.defaultdict(list)
        for h, items in by_hour.items():
            for sq, pnl, ex, lev in items:
                acc[sq].append((pnl, ex, lev, h))
        seqs = sorted(acc)
        L += ["## 1. Позиции Ladder (Depth) по номеру обучения", "",
              "| обучение | первый час | часов | позиций | средний исход | медиана | прибыльных | пол+ликв | плечо |",
              "|---|---|--:|--:|--:|--:|--:|--:|--:|"]
        table = []
        for sq in seqs:
            v = acc[sq]
            pn = np.array([x[0] for x in v])
            hours = len({x[3] for x in v})
            fl = sum(1 for x in v if x[1] in ("пол", "ликвидация")) / len(v)
            row = {"seq": sq, "first": first.get(sq), "hours": hours, "n": len(v),
                   "mean": float(pn.mean()), "median": float(np.median(pn)),
                   "win": float((pn > 0).mean()), "floor": fl,
                   "lev": float(np.median([x[2] for x in v]))}
            table.append(row)
            L.append(f"| {sq} | {row['first']} | {hours} | {len(v)} | {_p(row['mean'])} | "
                     f"{_p(row['median'])} | {row['win'] * 100:.0f} % | {fl * 100:.1f} % | "
                     f"{row['lev']:.2f}× |")
        groups = {h: [x[1] for x in items] for h, items in by_hour.items()}
        groups["__seq__"] = {h: items[0][0] for h, items in by_hour.items()}
        means = [r["mean"] for r in table]
        rho, p = trend([r["seq"] for r in table], means, groups, rng)
        half = len(table) // 2
        a1 = np.concatenate([[x[0] for x in acc[r["seq"]]] for r in table[:half]]) if half else np.array([])
        a2 = np.concatenate([[x[0] for x in acc[r["seq"]]] for r in table[half:]]) if half else np.array([])
        se = lambda x: (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else float("nan")  # noqa: E731
        L += ["", f"Тренд среднего исхода по номеру обучения: ρ = {rho:+.2f}, доля нулей не слабее: "
              f"{p:.2f}" if rho is not None else "Тренд: обучений меньше трёх — не считается.",
              (f"Половины обучений: первая {len(a1)} позиций {_p(float(a1.mean()))} ± {_p(se(a1))}, "
               f"вторая {len(a2)} позиций {_p(float(a2.mean()))} ± {_p(se(a2))}."
               if len(a1) and len(a2) else ""), ""]
        res["positions"] = {"table": table, "rho": rho, "p": p,
                            "halves": ([float(a1.mean()), float(a2.mean()),
                                        float(se(a1)), float(se(a2)), int(len(a1)), int(len(a2))]
                                       if len(a1) and len(a2) else None)}
    else:
        L += ["## 1. Позиции по обучениям: кэш реплея или лист не читаются — раздела нет", ""]

    # --- 2. живой IC
    ics = ic_by_seq(log)
    if ics:
        L += ["## 2. Живой вневыборочный IC прежних весов (цель fwd_4h)", "",
              "| когда | рука | обучено до | IC (медиана) | сечений |", "|---|---|---|--:|--:|"]
        by_arm = collections.defaultdict(list)
        for r in sorted(ics, key=lambda r: (r.get("at") or "")):
            L.append(f"| {r.get('at')} | {r.get('arm')} | {r.get('trained_upto')} | "
                     f"{r['median_ic']:+.4f} | {r.get('sections')} |")
            by_arm[r.get("arm")].append(float(r["median_ic"]))
        L.append("")
        res["ic"] = {}
        for arm, vals in by_arm.items():
            rho = spearman(list(range(len(vals))), vals)
            null = []
            for _ in range(N_PERM):
                v2 = list(vals)
                rng.shuffle(v2)
                r2 = spearman(list(range(len(v2))), v2)
                if r2 is not None:
                    null.append(abs(r2))
            p = (sum(1 for x in null if x >= abs(rho)) / len(null)) if (rho is not None and null) else None
            half = len(vals) // 2
            L.append(f"- {arm}: {len(vals)} замеров, первая половина IC {np.mean(vals[:half]):+.4f}, "
                     f"вторая {np.mean(vals[half:]):+.4f}; тренд ρ = "
                     + (f"{rho:+.2f}, доля нулей не слабее {p:.2f}" if rho is not None else "—"))
            res["ic"][arm] = {"n": len(vals), "first_half": float(np.mean(vals[:half])) if half else None,
                              "second_half": float(np.mean(vals[half:])), "rho": rho, "p": p}
        L.append("")
    else:
        L += ["## 2. Живой IC: истории нет — раздела нет", ""]
    L.append(f"Прогон {time.time() - t0:.0f} с, {res['computed_at']} UTC.")
    txt = "\n".join(L)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(txt)
    if not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "замер: качество сигнала по номеру обучения"], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
