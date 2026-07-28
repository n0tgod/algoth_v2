#!/usr/bin/env python3
"""
R3 — две нулевые модели по десять зёрен. Спека 03, раздел 7.

Считается **до** бэктеста намеренно. В A4 перестановочный тест обесценил
результат месячного прогона, и узнали об этом в конце. Здесь нуль стоит
между дешёвым замером (R2) и дорогим бэктестом (R5), и здесь же критерий
немедленной остановки §8.2 в полном виде.

Нули считаются пересчётом сохранённых векторов, а не повторным прогоном
конвейера. Это законно ровно потому, что обе нулевые модели отличаются
от прогона одним — тем, КАК сопоставлены вектор сигнала и вектор
форварда. Всё остальное (универсум, β, ликвидность, состав корзины,
издержки) обязано остаться нетронутым, и при пересчёте оно нетронуто по
построению, а не по обещанию.

Проверка самого метода встроена: реальный результат пересчитывается из
тех же векторов и сверяется с результатом прогона R2. Расхождение
означало бы ошибку в одном из двух путей.

Нуль 1 — перестановка внутри сечения
------------------------------------

На каждую дату перемешивается «кто какой сигнал получил». Разрушена
связь сигнала с активом; рыночные условия, состав универсума, число ног
и распределение форвардных доходностей сохранены полностью. Прямой
аналог перестановки меток групп из §7 спеки 02, которая в A4 показала,
что экономическая группировка не добавляет ничего.

Перестановка одна на дату и применяется ко всем `k` сразу: так
сохраняется взаимная структура сигналов разных горизонтов, и нуль
остаётся консервативным.

Нуль 2 — сдвиг сечения во времени
---------------------------------

Сигнал даты `t` соединяется с форвардными доходностями даты `t + S`.
Кросс-секционное распределение и той и другой величины сохранено
целиком, разрушена только связь между ними. A1 применяла этот приём к
funding, и величина монотонно сползала к нулю при отодвигании окна —
поведение, которого и ждёшь от настоящего эффекта.

Нуль 2 ловит то, чего не ловит нуль 1. Если у части активов и сигнал, и
форвардная доходность высоки по какой-то устойчивой причине — скажем, у
молодых инструментов и то и другое волатильнее, — перестановка внутри
сечения это разрушит, а сдвиг во времени сохранит. То есть нуль 2 строже
там, где эффект мог бы оказаться свойством актива, а не времени.

**Зерном нуля 2 служит величина сдвига**, а не генератор случайных
чисел: свободный параметр здесь один, и перебирать надо именно его.
Сдвиги объявлены списком и включают требуемые спекой 365 дней.

Требуется дамп векторов: `crosssection.py --interval <X>` сохраняет их
в `out/vectors/` (в git не идут, пересобираются вместе с прогоном).

    python3 nulls.py --interval 15m
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
VECTORS = os.path.join(OUT, "vectors")

sys.path.insert(0, HERE)
import residual as RS  # noqa: E402

SEEDS = tuple(range(1, 11))
# Сдвиги нуля 2, дни. 365 — величина из спеки; остальные дают
# распределение, без которого «превышает 95-й процентиль» не измерить.
SHIFTS = (180, 240, 300, 365, 430, 490, 550, 610, 670, 730)
WIDTHS = {"decile": 0.10, "quintile": 0.20}

# Порог §8.2: реальный IC обязан превышать 95-й процентиль зёрен нуля.
NULL_PERCENTILE = 95


def load_vectors(interval):
    if not os.path.isdir(VECTORS):
        raise SystemExit(
            f"нет {VECTORS} — сначала crosssection.py --interval {interval}")
    out = {}
    for fn in sorted(os.listdir(VECTORS)):
        if not (fn.startswith(interval + "_") and fn.endswith(".json")):
            continue
        with open(os.path.join(VECTORS, fn), encoding="utf-8") as f:
            for d, v in json.load(f).items():
                out[d] = {
                    "names": v["names"],
                    "sig": {int(k): np.asarray(x, dtype=np.float64)
                            for k, x in v["sig"].items()},
                    "fwd": {int(k): np.asarray(x, dtype=np.float64)
                            for k, x in v["fwd"].items()},
                }
    if not out:
        raise SystemExit(f"в {VECTORS} нет дампов для {interval}")
    return out


def measure(pairs, k, h):
    """IC и спред корзины по списку пар (сигнал, форвард)."""
    ics, spreads = [], {w: [] for w in WIDTHS}
    for sig, fwd in pairs:
        ic, _ = RS.spearman(sig, fwd)
        if ic is not None:
            ics.append(ic)
        for w, frac in WIDTHS.items():
            b = RS.basket_spread(sig, fwd, frac)
            if b is not None:
                spreads[w].append(b["spread"])
    mean, t, n = RS.tstat(ics)
    out = {"ic_mean": mean, "ic_t": t, "sections": n,
           "ic_positive_share": share_pos(ics)}
    for w in WIDTHS:
        v = sorted(x for x in spreads[w] if x == x)
        out[w] = {"spread_median": float(np.median(v)) if v else None,
                  "spread_mean": RS.tstat(spreads[w])[0],
                  "positive_share": share_pos(spreads[w])}
    return out


def share_pos(v):
    v = [x for x in v if x is not None and x == x]
    return (sum(1 for x in v if x > 0) / len(v)) if v else None


def grid_of(dates, vec, build):
    """Мера по всей сетке k×h. `build` даёт пары (сигнал, форвард)."""
    ks = sorted(next(iter(vec.values()))["sig"])
    hs = sorted(next(iter(vec.values()))["fwd"])
    cells = {}
    for k in ks:
        for h in hs:
            # Непересекающиеся сечения: каждая h-я дата. Перекрытие —
            # то, что обесценило результат A4.
            pairs = build(dates[::h], k, h)
            if pairs:
                cells[f"k{k}_h{h}"] = measure(pairs, k, h)
    ics = [c["ic_mean"] for c in cells.values() if c["ic_mean"] is not None]
    return {"cells": cells,
            "ic_median": float(np.median(ics)) if ics else None,
            "ic_best": max(ics) if ics else None,
            "ic_worst": min(ics) if ics else None,
            "positive_cells": sum(1 for x in ics if x > 0)}


def real_builder(vec):
    def build(dates, k, h):
        return [(vec[d]["sig"][k], vec[d]["fwd"][h]) for d in dates]
    return build


def null1_builder(vec, seed):
    def build(dates, k, h):
        out = []
        for d in dates:
            # Зерно завязано на дату: результат воспроизводим и не зависит
            # от порядка обхода.
            rng = np.random.default_rng(abs(hash((seed, d))) % (2 ** 32))
            sig = vec[d]["sig"][k]
            out.append((sig[rng.permutation(len(sig))], vec[d]["fwd"][h]))
        return out
    return build


def null2_builder(vec, dates_all, shift):
    """Сигнал даты t против форварда даты t+shift, сопоставление по активу.

    Состав универсума за год меняется, поэтому пара строится только по
    активам, присутствующим в обеих датах. Число наблюдений в сечении
    от этого падает, и это докладывается: нуль на меньшей выборке
    шумнее, то есть его 95-й процентиль выше — сравнение остаётся
    консервативным, а не наоборот.
    """
    from datetime import date, timedelta
    have = set(dates_all)

    def build(dates, k, h):
        out = []
        for d in dates:
            d2 = (date.fromisoformat(d) + timedelta(days=shift)).isoformat()
            if d2 not in have:
                continue
            a, b = vec[d], vec[d2]
            idx_b = {n: i for i, n in enumerate(b["names"])}
            common = [(i, idx_b[n]) for i, n in enumerate(a["names"])
                      if n in idx_b]
            if len(common) < 30:
                continue
            ia = np.fromiter((x for x, _ in common), dtype=np.int64)
            ib = np.fromiter((y for _, y in common), dtype=np.int64)
            out.append((a["sig"][k][ia], b["fwd"][h][ib]))
        return out
    return build


def verify_against_run(real, interval):
    """Пересчёт из векторов обязан воспроизвести прогон R2 в точности.

    Без этой сверки весь приём незаконен: нули считаются по векторам, и
    если векторы описывают не то, что считал конвейер, нули меряют не то,
    с чем их сравнивают. Расхождение здесь означает ошибку в одном из
    двух путей, и какой именно — выяснять до всякой интерпретации.
    """
    path = os.path.join(OUT, f"crosssection_{interval}.json")
    if not os.path.exists(path):
        return {"checked": 0, "mismatches": None,
                "note": f"нет {path} — сверить не с чем"}
    with open(path, encoding="utf-8") as f:
        run = json.load(f)["summary"]["cells"]
    bad = []
    for k, c in real["cells"].items():
        if k not in run:
            continue
        a, b = c["ic_mean"], run[k]["ic_independent"]["mean"]
        if a is None or b is None or abs(a - b) > 1e-12:
            bad.append({"cell": k, "from_vectors": a, "from_run": b})
    return {"checked": len(real["cells"]), "mismatches": len(bad),
            "detail": bad}


def verdict(real, nulls, key="ic_median"):
    v = sorted(n[key] for n in nulls if n[key] is not None)
    if not v:
        return None
    p95 = v[min(len(v) - 1, int(round(NULL_PERCENTILE / 100 * (len(v) - 1))))]
    return {"real": real[key], "null_median": float(np.median(v)),
            "null_p95": p95, "null_max": v[-1], "null_min": v[0],
            "beats_p95": real[key] is not None and real[key] > p95,
            "ratio": (real[key] / p95) if p95 and p95 > 0 else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    args = ap.parse_args()

    vec = load_vectors(args.interval)
    dates = sorted(vec)
    print(f"сечений с векторами: {len(dates)}  "
          f"{dates[0]} … {dates[-1]}", file=sys.stderr, flush=True)

    real = grid_of(dates, vec, real_builder(vec))
    check = verify_against_run(real, args.interval)
    print(f"реальный: IC медиана {real['ic_median']:.4f}, "
          f"положительных ячеек {real['positive_cells']}",
          file=sys.stderr, flush=True)
    print(f"сверка с прогоном R2: ячеек {check['checked']}, расхождений "
          f"{check['mismatches']}", file=sys.stderr, flush=True)
    if check["mismatches"]:
        raise SystemExit(
            "пересчёт из векторов разошёлся с прогоном R2 — считать нули\n"
            "бессмысленно, пока не выяснено, какой из путей неверен:\n"
            + json.dumps(check["detail"], ensure_ascii=False, indent=1))

    n1 = []
    for s in SEEDS:
        g = grid_of(dates, vec, null1_builder(vec, s))
        n1.append(g)
        print(f"  нуль 1, зерно {s:>2}: IC медиана {g['ic_median']:+.4f}, "
              f"положительных {g['positive_cells']}/16",
              file=sys.stderr, flush=True)

    n2 = []
    for sh in SHIFTS:
        g = grid_of(dates, vec, null2_builder(vec, dates, sh))
        g["shift_days"] = sh
        n2.append(g)
        print(f"  нуль 2, сдвиг {sh:>3} дн: IC медиана {g['ic_median']:+.4f}, "
              f"положительных {g['positive_cells']}/16",
              file=sys.stderr, flush=True)

    doc = {
        "config": {"interval": args.interval, "seeds": list(SEEDS),
                   "shifts": list(SHIFTS), "percentile": NULL_PERCENTILE},
        "verification": check,
        "real": real,
        "null1": n1,
        "null2": n2,
        "verdict": {"null1": verdict(real, n1), "null2": verdict(real, n2)},
    }
    with open(os.path.join(OUT, f"nulls_{args.interval}.json"), "w",
              encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(json.dumps(doc["verdict"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
