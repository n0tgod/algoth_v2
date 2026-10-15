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
        table = []
        for sq in seqs:
            v = acc[sq]
            pn = np.array([x[0] for x in v])
            table.append({"seq": sq, "first": first.get(sq), "n": len(v),
                          "mean": float(pn.mean()), "hours": len({x[3] for x in v})})
        # Таблица — по НЕДЕЛЯМ часа листа: в августе обучение шло каждый
        # час, и строка на обучение дала бы тысячи строк; тренд при этом
        # считается по номерам обучений, как объявлено.
        weeks = collections.defaultdict(list)
        for h, items in by_hour.items():
            wk = time.strftime("%Y-%m-%d", time.gmtime(h - (h - 4 * 86400) % (7 * 86400)))
            weeks[wk].extend(items)
        L += ["## 1. Позиции Ladder (Depth) по неделям листа", "",
              f"Обучений с позициями: {len(seqs)} (№{seqs[0]}…№{seqs[-1]}; в августе обучение шло "
              "каждый час, с сентября — раз в сутки). Строка — неделя часа листа.", "",
              "| неделя с | обучений | позиций | средний исход | медиана | прибыльных | пол+ликв | плечо |",
              "|---|--:|--:|--:|--:|--:|--:|--:|"]
        wtable = []
        for wk in sorted(weeks):
            v = weeks[wk]
            pn = np.array([x[1] for x in v])
            fl = sum(1 for x in v if x[2] in ("пол", "ликвидация")) / len(v)
            row = {"week": wk, "trainings": len({x[0] for x in v}), "n": len(v),
                   "mean": float(pn.mean()), "median": float(np.median(pn)),
                   "win": float((pn > 0).mean()), "floor": fl,
                   "lev": float(np.median([x[3] for x in v]))}
            wtable.append(row)
            L.append(f"| {wk} | {row['trainings']} | {len(v)} | {_p(row['mean'])} | "
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
        res["positions"] = {"weeks": wtable, "trainings": len(seqs), "rho": rho, "p": p,
                            "halves": ([float(a1.mean()), float(a2.mean()),
                                        float(se(a1)), float(se(a2)), int(len(a1)), int(len(a2))]
                                       if len(a1) and len(a2) else None)}
    else:
        L += ["## 1. Позиции по обучениям: кэш реплея или лист не читаются — раздела нет", ""]

    # --- 2. живой IC
    ics = ic_by_seq(log)
    if ics:
        res["ic"] = {}
        # (а) оценка прежних весов в момент обучения: десятки сечений
        # после `trained_upto`; на одно обучение берётся последняя
        # (у неё сечений больше всего)
        by_tr = {}
        for r in ics:
            if r.get("trained_upto") and (r.get("sections") or 0) >= 10:
                by_tr[(r.get("arm"), r["trained_upto"])] = r
        L += ["## 2а. Вневыборочный IC прежних весов на момент обучения (цель fwd_4h, ≥ 10 сечений)", "",
              "| обучено до | gbm | сечений | nn | сечений |", "|---|--:|--:|--:|--:|"]
        ups = sorted({k[1] for k in by_tr})
        for up in ups:
            g, n_ = by_tr.get(("gbm", up)), by_tr.get(("nn", up))
            L.append(f"| {up} | {g['median_ic']:+.4f} | {g.get('sections')} | " if g else f"| {up} | — | — | ")
            L[-1] += (f"{n_['median_ic']:+.4f} | {n_.get('sections')} |" if n_ else "— | — |")
        L.append("")
        for arm in ("gbm", "nn"):
            vals = [by_tr[(arm, up)]["median_ic"] for up in ups if (arm, up) in by_tr]
            if len(vals) < 3:
                continue
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
            L.append(f"- {arm}: {len(vals)} обучений, первая половина IC {np.mean(vals[:half]):+.4f}, "
                     f"вторая {np.mean(vals[half:]):+.4f}; тренд ρ = "
                     + (f"{rho:+.2f}, доля нулей не слабее {p:.2f}" if rho is not None else "—"))
            res["ic"][arm] = {"n": len(vals), "first_half": float(np.mean(vals[:half])),
                              "second_half": float(np.mean(vals[half:])), "rho": rho, "p": p}
        # (б) часовой живой IC (одно сечение на замер) — медианы по неделям
        wk_ic = collections.defaultdict(list)
        for r in ics:
            if (r.get("sections") or 0) == 1 and r.get("at"):
                try:
                    t = time.mktime(time.strptime(r["at"][:10], "%Y-%m-%d"))
                except ValueError:
                    continue
                wk = time.strftime("%Y-%m-%d", time.gmtime(t - (t - 4 * 86400) % (7 * 86400)))
                wk_ic[(wk, r.get("arm"))].append(float(r["median_ic"]))
        if wk_ic:
            L += ["", "## 2б. Часовой живой IC (одно сечение на замер) — медиана по неделям", "",
                  "| неделя с | gbm | замеров | nn | замеров |", "|---|--:|--:|--:|--:|"]
            for wk in sorted({k[0] for k in wk_ic}):
                g, n_ = wk_ic.get((wk, "gbm"), []), wk_ic.get((wk, "nn"), [])
                L.append(f"| {wk} | {(np.median(g) if g else float('nan')):+.4f} | {len(g)} | "
                         f"{(np.median(n_) if n_ else float('nan')):+.4f} | {len(n_)} |")
            res["ic_weekly"] = {f"{k[0]}/{k[1]}": [float(np.median(v)), len(v)] for k, v in wk_ic.items()}
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
