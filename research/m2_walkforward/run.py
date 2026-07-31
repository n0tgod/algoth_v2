#!/usr/bin/env python3
"""
M2 — пилот-гейт гипотезы 6 (спека 07 §10): walk-forward по сетке из
8 ячеек, модель против одиночного признака.

Порядок счёта закреплён спекой: **нуль 3 идёт первым** — обучение на
перемешанных внутри сечения форвардах. Модель, обученная на шуме,
обязана давать IC ≈ 0; если даёт больше 0.01, конвейер течёт (утечка
нормировки, пересечение признака с форвардом), и числа прогона читать
нельзя. Нуль гоняется тем же кодом, что прогон, — отличаются только
цели обучения; частота переобучения у нуля месячная и это решение
записано здесь: класс утечки живёт в конвейере (границы обучающего
окна, корзины, признаки), а не в частоте вызова этого конвейера.

Что смоук обязан замерить до полной сетки — цену одного обучения;
она печатается после первого же обучения нуля 3 вместе с проекцией
на весь прогон. Ось «сутки» самая дорогая, и решение о железе
принимается по этому числу, а не по ощущению.

    .venv/bin/python research/m2_walkforward/run.py            # полный
    .venv/bin/python research/m2_walkforward/run.py --tag smoke \
        --cells h1_static,h5_static --null-seeds 2 --trees 20  # смоук

Смоук пишет артефакты с суффиксом и в git не идёт (урок F2: смоук,
неотличимый от прогона, однажды подменил собой результат).
"""

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gbm                                                  # noqa: E402
import wf                                                   # noqa: E402

RESEARCH = os.path.dirname(HERE)
MATRIX = os.path.join(RESEARCH, "m1_features", "out", "features_1m.parquet")
OUT = os.path.join(HERE, "out")

META = ("day", "asset")
NOT_FEATURES = ("target_1", "target_5", "fwd_1", "fwd_5")
NULL3_STOP = 0.01            # §8: сдвиг больше этого при |t| > 3 — течь
FIXED_BASELINE = "ret_7"     # диагностика: возврат R2 в лоб, знак минус


def log(m):
    print(m, flush=True)


def load_matrix(path):
    import pyarrow.parquet as pq
    t = pq.read_table(path)
    cols = {c: t[c].to_numpy(zero_copy_only=False) for c in t.column_names}
    order = np.lexsort((cols["asset"], cols["day"]))
    cols = {c: v[order] for c, v in cols.items()}
    feats = sorted(c for c in cols if c not in META + NOT_FEATURES)
    # Цели не смеют оказаться в признаках — это защёлка, а не проверка
    # на дурака: одна переименованная колонка сделала бы IC ≈ 1 и
    # выглядела бы триумфом обучения.
    for c in feats:
        assert not c.startswith(("target", "fwd")), c
    x = np.column_stack([cols[c].astype(np.float64) for c in feats])
    day_ord = np.array([wf.parse_day(d) for d in cols["day"]])
    return cols, feats, x, day_ord


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default=MATRIX)
    ap.add_argument("--tag", default="")
    ap.add_argument("--cells", default="")
    ap.add_argument("--null-seeds", type=int, default=10)
    ap.add_argument("--trees", type=int, default=gbm.N_TREES)
    a = ap.parse_args()
    try:
        # На VPS рядом живёт сборщик стакана B1, и приём данных важнее
        # счёта (правило M5 спеки 07). Прогон многочасовой — уступаем.
        os.nice(10)
    except OSError:
        pass
    tag = f"-{a.tag}" if a.tag else ""
    if not a.tag and (a.trees != gbm.N_TREES or a.null_seeds != 10
                      or a.cells):
        raise SystemExit("урезанный протокол — только со своим --tag: "
                         "прогон и смоук не смеют быть неотличимы")
    os.makedirs(OUT, exist_ok=True)
    t_all = time.time()

    log(f"матрица: {a.matrix}")
    cols, feats, x, day_ord = load_matrix(a.matrix)
    slices = wf.day_slices(day_ord)
    day_ords = [s[0] for s in slices]
    log(f"строк {len(day_ord):,}, сечений {len(slices)}, "
        f"признаков {len(feats)}: {', '.join(feats)}")
    if not a.tag and "age" not in feats:
        raise SystemExit(
            "в матрице нет признака age — она собрана до правки M1 "
            "(возраст листинга, §4 п. 7 спеки). Сначала перепрогнать "
            "M1: tools/run.sh \"M1: матрица признаков\" "
            "research/m1_features/build.py")

    eval0 = wf.parse_day(wf.EVAL_START)
    eval_idx = [i for i, (o, _, _) in enumerate(slices) if o >= eval0]
    if not eval_idx:
        raise SystemExit("нет сечений в окне оценки")
    log(f"окно оценки: с {wf.EVAL_START}, сечений {len(eval_idx)}")

    targets = {h: cols[f"target_{h}"] for h in (1, 5)}
    log("предрасчёт IC признаков по сечениям (для руки одиночного "
        "признака)…")
    t0 = time.time()
    ic_mat = {h: wf.ic_by_day(x, targets[h], slices) for h in (1, 5)}
    log(f"  готово: {time.time() - t0:.0f} с")

    fit_times = []

    def make_fit(cell_idx):
        def fit_fn(xt, yt, fit_idx):
            t1 = time.time()
            m = gbm.fit(xt, yt, wf.fit_seed(cell_idx, fit_idx),
                        n_trees=a.trees)
            fit_times.append(time.time() - t1)
            n = len(fit_times)
            if n == 1:
                per = fit_times[0]
                total = est_total_fits(len(eval_idx), a.null_seeds)
                log(f"  ЦЕНА ОДНОГО ОБУЧЕНИЯ: {per:.1f} с; всего обучений "
                    f"~{total}, проекция ~{per * total / 3600:.1f} ч")
            elif n % 25 == 0:
                # Прогон, который молчит дольше минуты, неотличим от
                # повисшего — правило проекта со времён L2.
                log(f"  …обучений {n}, среднее {np.mean(fit_times):.1f} с")
            return m
        return fit_fn

    summary = {"interval": "1m", "tag": a.tag, "eval_start": wf.EVAL_START,
               "features": feats, "trees": a.trees,
               "gbm": {"depth": gbm.DEPTH, "lr": gbm.LEARNING_RATE,
                       "subsample": gbm.SUBSAMPLE, "bins": gbm.N_BINS,
                       "min_leaf": gbm.MIN_LEAF},
               "null3": {}, "cells": {}, "verdict": {}}

    # ---- Нуль 3 — ПЕРВЫМ (спека §7): обучение на перемешанных целях.
    #
    # Два решения закрыты ДО прогона, оба — по замерам смоука.
    #
    # 1. Спека задала порог остановки (|IC| > 0.01), но не агрегат.
    #    Вердикт — по медиане зёрен: модель, обученная на чистом шуме, —
    #    это одна случайная функция признаков, и её случайная проекция
    #    на настоящий сигнал сечения даёт ±0.01 НА ЗЕРНО (проверено
    #    двумя видами перестановки — внутрисечной и глобальной; обе
    #    болтаются вокруг нуля одинаково). Остановка по одному зерну
    #    была бы остановкой по шуму.
    #
    # 2. Подпись настоящей утечки — не большое зерно, а СОГЛАСОВАННЫЙ
    #    сдвиг всех зёрен в одну сторону: утечка не зависит от того, как
    #    перемешали цели. Детектор — t-статистика среднего по зёрнам.
    log(f"нуль 3: обучение на перемешанных форвардах ({a.null_seeds} "
        f"зёрен × 2 h, месячное переобучение)")
    for h in (1, 5):
        no = wf.nonoverlap(eval_idx, h)
        meds = []
        for s_idx in range(a.null_seeds):
            y_sh = wf.shuffle_within_sections(
                targets[h], slices, wf.null3_seed(h, s_idx))
            pred, _ = wf.run_cell(x, y_sh, day_ord, slices, eval_idx, h,
                                  wf.FREQ_DAYS["month"],
                                  make_fit(1000 + h * 100 + s_idx))
            ics = [wf.spearman(pred[sa:sb], targets[h][sa:sb])
                   for _, sa, sb in (slices[i] for i in no)]
            m = wf.stats(ics).get("median", float("nan"))
            meds.append(m)
            log(f"  h={h} зерно {s_idx}: медианный IC {m:+.4f}")
        v = np.asarray(meds)
        mean = float(v.mean())
        se = float(v.std(ddof=1) / np.sqrt(len(v))) if len(v) > 1 else 0.0
        t_shift = mean / se if se > 0 else 0.0
        summary["null3"][str(h)] = {
            "medians": meds, "median": float(np.median(v)),
            "worst_abs": float(np.max(np.abs(v))),
            "mean": mean, "se": se, "t_shift": round(t_shift, 2)}
        log(f"нуль 3, h={h}: медиана по зёрнам {np.median(v):+.4f}, "
            f"среднее {mean:+.4f} ± {se:.4f}, t сдвига {t_shift:+.1f}")

    n3 = summary["null3"].values()
    sec_worst = max(abs(s["median"]) for s in n3)
    t_worst = max(abs(s["t_shift"]) for s in n3)
    # Критерий 7 в правленой редакции §7/§8 спеки: без согласованного
    # сдвига зёрен. Остановка — сдвиг и величина разом.
    summary["verdict"]["null3_pass"] = t_worst <= 3.0
    summary["verdict"]["null3_leak"] = (t_worst > 3.0
                                        and sec_worst > NULL3_STOP)
    if summary["verdict"]["null3_leak"]:
        log(f"КОНВЕЙЕР ТЕЧЁТ: зёрна нуля 3 согласованно сдвинуты "
            f"(|t| {t_worst:.1f}, |медиана| {sec_worst:.4f}) — сетка "
            f"не считается")
        finish(summary, tag, t_all, fit_times)
        return
    if sec_worst > NULL3_STOP:
        log(f"нуль 3 поднят (|медиана| {sec_worst:.4f} > {NULL3_STOP}) "
            f"без согласованного сдвига (t {t_worst:.1f}) — шум проекции, "
            f"не течь; сетка считается")
    if fit_times:
        rest = est_total_fits(len(eval_idx), 0) * float(np.mean(fit_times))
        log(f"сетка 8 ячеек — проекция ~{rest / 3600:.1f} ч "
            f"при среднем обучении {np.mean(fit_times):.1f} с")

    # ---- Сетка 8 ячеек, от дешёвой оси к дорогой.
    wanted = set(a.cells.split(",")) if a.cells else None
    order = [(h, f) for f in ("static", "month", "week", "day")
             for h in (1, 5)]
    for ci, (h, freq) in enumerate(order):
        name = wf.cell_name(h, freq)
        if wanted and name not in wanted:
            continue
        log(f"ячейка {name}: переобучение "
            f"{'нет (статическая)' if freq == 'static' else freq}")
        t1 = time.time()
        y = targets[h]
        pred, n_fits = wf.run_cell(x, y, day_ord, slices, eval_idx, h,
                                   wf.FREQ_DAYS[freq], make_fit(ci))
        no = wf.nonoverlap(eval_idx, h)
        model_ics = [wf.spearman(pred[sa:sb], y[sa:sb])
                     for _, sa, sb in (slices[i] for i in no)]
        single_all, chosen = wf.single_feature_arm(
            ic_mat[h], day_ords, eval_idx, h, wf.FREQ_DAYS[freq])
        pos_in_eval = {si: k for k, si in enumerate(eval_idx)}
        single_ics = [single_all[pos_in_eval[i]] for i in no]
        base_j = feats.index(FIXED_BASELINE)
        fixed_ics = [-ic_mat[h][i, base_j] for i in no]

        ms, ss, fs = wf.stats(model_ics), wf.stats(single_ics), \
            wf.stats(fixed_ics)
        picked = {}
        for c in chosen:
            fn = feats[abs(int(c)) - 1]
            sign = "-" if c < 0 else "+"
            picked[sign + fn] = picked.get(sign + fn, 0) + 1
        cell = {"model": ms, "single": ss, "fixed_ret7": fs,
                "delta_median": ms["median"] - ss["median"],
                "n_fits": n_fits, "sec": round(time.time() - t1, 1),
                "picked": picked}
        summary["cells"][name] = cell
        log(f"  модель: медианный IC {ms['median']:+.4f} (t {ms['t']:.1f}, "
            f"доля+ {ms['share_pos']:.2f}, сечений {ms['n']}); "
            f"признак: {ss['median']:+.4f}; разность "
            f"{cell['delta_median']:+.4f}; {n_fits} обучений, "
            f"{cell['sec']:.0f} с")
        np.savez_compressed(
            os.path.join(OUT, f"vectors_{name}{tag}.npz"),
            pred=pred.astype(np.float32),
            eval_days=np.array([slices[i][0] for i in eval_idx]),
            single_ic=single_all, chosen=chosen)

    # Важность признаков: отдельное обучение на всём окне ДО оценки —
    # одно, честное (только прошлое), публикуемое в отчёте (§9 спеки:
    # модель, чей результат нельзя разложить, нельзя и оспорить).
    for h in (1, 5):
        rows = wf.train_rows(day_ord, eval0, h)
        m = gbm.fit(x[rows], targets[h][rows], wf.fit_seed(90 + h, 0),
                    n_trees=a.trees)
        tot = m.importance.sum() or 1.0
        summary.setdefault("importance", {})[str(h)] = {
            feats[j]: round(float(m.importance[j] / tot), 4)
            for j in np.argsort(m.importance)[::-1]}

    verdict(summary)
    finish(summary, tag, t_all, fit_times)


def est_total_fits(n_eval, null_seeds):
    per_month = max(1, n_eval // 30)
    return (2 * null_seeds * per_month                  # нуль 3
            + 2 * (1 + per_month + n_eval // 7 + n_eval) + 2)


def verdict(s):
    cells = s["cells"]
    if not cells:
        return
    med_ics = sorted(c["model"]["median"] for c in cells.values())
    deltas = [c["delta_median"] for c in cells.values()]
    # «Медианная ячейка» критериев 3–4 — нижняя средняя по IC (позиция
    # len//2 - 1 при чётном числе): консервативный выбор, записан до
    # прогона.
    names = sorted(cells, key=lambda k: cells[k]["model"]["median"])
    mid = names[max(0, (len(names) - 1) // 2)]
    v = s["verdict"]
    v["c1_median_ic"] = float(np.median(med_ics))
    v["c1_pass"] = bool(v["c1_median_ic"] >= 0.02)
    v["c2_median_delta"] = float(np.median(deltas))
    v["c2_pass"] = bool(v["c2_median_delta"] >= 0.005)
    v["c3_cell"] = mid
    v["c3_t"] = float(cells[mid]["model"]["t"])
    v["c3_pass"] = bool(v["c3_t"] >= 3.0)
    v["c4_share_pos"] = float(cells[mid]["model"]["share_pos"])
    v["c4_pass"] = bool(v["c4_share_pos"] >= 0.60)
    v["c5_min_sections"] = int(min(c["model"]["n"] for c in cells.values()))
    v["c5_pass"] = bool(v["c5_min_sections"] >= 100)
    v["stop_no_cell_beats_single"] = bool(all(d <= 0 for d in deltas))


def finish(summary, tag, t_all, fit_times):
    summary["budget"] = {
        "total_sec": round(time.time() - t_all, 1),
        "fits": len(fit_times),
        "fit_sec_mean": round(float(np.mean(fit_times)), 2) if fit_times
        else None,
        "fit_sec_max": round(float(np.max(fit_times)), 2) if fit_times
        else None}
    path = os.path.join(OUT, f"m2_summary_1m{tag}.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)
    log(f"сводка: {path}")
    import report
    md = report.render(summary)
    rp = os.path.join(OUT, f"M2-report-1m{tag}.md")
    with open(rp, "w", encoding="utf-8") as f:
        f.write(md)
    log(f"отчёт: {rp}")


if __name__ == "__main__":
    main()
