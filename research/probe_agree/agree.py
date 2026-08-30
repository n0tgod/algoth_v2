#!/usr/bin/env python3
"""Зонд согласия рук: решение, взятое ОБЕИМИ руками, против взятого одной.

Идея (2026-08-30): деревья и сеть ранжируют одно сечение одними
признаками, и согласие ансамбля — единственный фильтр-кандидат без
отрицательного приора: девять зондов «обстановки» судили внешние
состояния, внутреннее согласие не судил ни один.

Это ЗОНД: порогов вердикта нет, все ячейки печатаются, выбор лучшей —
ошибка R5. Правило чтения объявлено до прогона: фильтр жив, только
если знак согласия держится в большинстве измеренных ячеек И в обеих
половинах истории; иначе — «торговать реже, а не лучше».

Три решения конструкции, каждое из наших уроков:

1. СОГЛАСИЕ БЕРЁТСЯ ИЗ ВЫБОРОВ, не из закрытых сделок. Фильтр обязан
   быть известен В МОМЕНТ ВХОДА; закрытые строки — подмножество,
   обусловленное выживанием (схлопывание, «без исхода»), и флаг по
   ним был бы знанием из будущего в мягкой форме.
2. НУЛЬ — перестановка флага ВНУТРИ ДНЯ (UTC) той же руки и книги,
   счёт флагов дня сохранён. Слив 08-24…27 лёг на конкретные дни, и
   глобальная перестановка смешала бы эффект согласия с эффектом дня.
   Зерно числом (урок R3).
3. Единица — `net_bp` сделки (после издержек), не деньги: деньги
   зависят от правил кассы книги и книги между собой не сравнивают
   (правило зонда сетапов). «Без лучшего имени» — в каждой ячейке.

Книги — торгуемые не-эхо (те же, что у зонда сетапов); наблюдательная
запись — отдельным блоком (самая широкая выборка, проверка знака, в
свод не входит). Ячейка (книга × рука) измерена при 30+ сделках в
КАЖДОЙ группе; тоньше — не измерена, а не ноль.

    .venv/bin/python research/probe_agree/agree.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, os.path.join(RESEARCH, "probe_setups"))
sys.path.insert(0, os.path.join(RESEARCH, "probe_turn"))
sys.path.insert(0, os.path.join(RESEARCH, "s8_loop"))

import setups as SP                                       # noqa: E402
import turn as PT                                         # noqa: E402

MIN_CELL = 30                 # сделок в каждой группе ячейки
PERMS = 1000
SEED = 20260831


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def pick_keys(mdir):
    """Множество (час, имя, сторона) по КАЖДОЙ руке — из выборов.

    Выбор с нулевым размером (кассе не хватило денег) — всё равно
    решение руки: согласие меряет модель, а не кассу.
    """
    keys = {"gbm": set(), "nn": set()}
    for p in SP.read_jsonl(os.path.join(mdir, "picks.jsonl")):
        arm = p.get("arm") or "gbm"
        if arm not in keys:
            continue
        for side in ("long", "short"):
            for leg in p.get(side) or []:
                if leg.get("sym"):
                    keys[arm].add((p.get("hour"), leg["sym"], side))
    return keys


def flag_rows(rows, keys):
    """Флаг согласия на закрытой строке: ДРУГАЯ рука тоже выбирала."""
    other = {"gbm": "nn", "nn": "gbm"}
    for r in rows:
        k = (r["hour"], r["sym"], r["side"])
        r["agree"] = k in keys[other[r["arm"]]]
    return rows


def day_of(ts):
    return int(ts) // 86400


def _delta(nets_a, nets_s):
    ma = sum(nets_a) / len(nets_a)
    ms = sum(nets_s) / len(nets_s)
    return ma - ms


def perm_p(trades, delta_obs, perms=PERMS, seed=SEED):
    """Односторонний перестановочный p: согласие лучше случайного
    разбиения тех же дней. Флаги тасуются ВНУТРИ дня, счёт по дням
    сохранён; зерно числом."""
    import numpy as np
    by_day = {}
    for t in trades:
        by_day.setdefault(day_of(t["ts"]), []).append(t)
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(perms):
        na, ns = [], []
        for day, ts_ in by_day.items():
            nets = [t["net"] for t in ts_]
            n_agr = sum(1 for t in ts_ if t["agree"])
            idx = rng.permutation(len(nets))
            for j, i in enumerate(idx):
                (na if j < n_agr else ns).append(nets[i])
        if na and ns and _delta(na, ns) >= delta_obs:
            hits += 1
    return hits / perms


def cell_stats(trades):
    """Числа одной ячейки (книга × рука). Меньше MIN_CELL в любой
    группе — ячейка не измерена, а не нулевая."""
    agr = [t for t in trades if t["agree"]]
    solo = [t for t in trades if not t["agree"]]
    out = {"n_agree": len(agr), "n_solo": len(solo),
           "share_agree": (len(agr) / len(trades)) if trades else None,
           "measured": len(agr) >= MIN_CELL and len(solo) >= MIN_CELL}
    if not out["measured"]:
        return out
    na, ns = [t["net"] for t in agr], [t["net"] for t in solo]
    out.update({
        "med_agree": round(SP.median(na), 1),
        "med_solo": round(SP.median(ns), 1),
        "mean_agree": round(sum(na) / len(na), 1),
        "mean_solo": round(sum(ns) / len(ns), 1),
        "win_agree": round(sum(1 for v in na if v > 0) / len(na), 3),
        "win_solo": round(sum(1 for v in ns if v > 0) / len(ns), 3),
        "delta_mean": round(_delta(na, ns), 1),
        "delta_med": round(SP.median(na) - SP.median(ns), 1)})
    out["p_perm"] = round(perm_p(trades, _delta(na, ns)), 3)
    # Без лучшего имени: имя с крупнейшим |Σ net| в группе согласия.
    tot = {}
    for t in agr:
        tot[t["sym"]] = tot.get(t["sym"], 0.0) + t["net"]
    if tot:
        top = max(tot, key=lambda s: abs(tot[s]))
        na2 = [t["net"] for t in agr if t["sym"] != top]
        if len(na2) >= 10:
            out["top_sym"] = top
            out["delta_wo_top"] = round(
                sum(na2) / len(na2) - out["mean_solo"], 1)
    # Половины истории: знак дельты в каждой (урок сетапов — эффект,
    # живущий в одной половине, предъявлен быть не может).
    ts_sorted = sorted(t["ts"] for t in trades)
    mid = ts_sorted[len(ts_sorted) // 2]
    halves = []
    for early in (True, False):
        sub = [t for t in trades if (t["ts"] < mid) == early]
        a = [t["net"] for t in sub if t["agree"]]
        s = [t["net"] for t in sub if not t["agree"]]
        halves.append(round(_delta(a, s), 1) if len(a) >= 10
                      and len(s) >= 10 else None)
    out["halves"] = halves
    return out


def reading(cells_out):
    meas = [(k, c) for k, c in cells_out.items() if c.get("measured")]
    if not meas:
        return ("ни одна ячейка не измерена — согласию не из чего "
                "строиться.")
    pos = [1 for _, c in meas if c["delta_mean"] > 0]
    both_halves = [1 for _, c in meas
                   if c.get("halves") and None not in c["halves"]
                   and c["halves"][0] > 0 and c["halves"][1] > 0]
    if len(pos) * 3 >= len(meas) * 2 and both_halves:
        return (f"согласие рук в плюсе в {len(pos)} из {len(meas)} "
                f"ячеек, и в {len(both_halves)} ячейках знак держится "
                "в обеих половинах — повод считать спеку фильтра, не "
                "вывод.")
    return (f"согласие рук не разводит исходы: дельта положительна в "
            f"{len(pos)} из {len(meas)} измеренных ячеек, в обеих "
            f"половинах держится у {len(both_halves)} — фильтр значил "
            "бы торговать реже, а не лучше.")


def write_report(path, cells_out, obs_out, meta):
    L = ["# Зонд согласия рук — «обе выбрали» против «одна»\n"]
    L.append(f"Прогон {meta['when']} · согласие из ВЫБОРОВ (известно "
             "в момент входа) · нуль — перестановка флага внутри дня "
             f"({PERMS} повторов, зерно числом) · единица — net б.п. "
             "после издержек\n")
    L.append("**Это зонд: порогов вердикта нет, все ячейки "
             "напечатаны, выбрать лучшую — ошибка R5.** Ячейка "
             f"измерена при {MIN_CELL}+ сделках в каждой группе.\n")

    def table(cd):
        rows = ["| книга · рука | сделок (обе/одна) | доля согласия | "
                "медиана обе/одна | Δ среднего | p | Δ без лучшего | "
                "половины |",
                "|---|--:|--:|--:|--:|--:|--:|--:|"]
        for k in sorted(cd):
            c = cd[k]
            if not c.get("measured"):
                rows.append(f"| {k} | {c['n_agree']}/{c['n_solo']} | "
                            "— | не измерена | — | — | — | — |")
                continue
            h = c.get("halves") or [None, None]
            hs = " / ".join("—" if v is None else f"{v:+.0f}"
                            for v in h)
            rows.append(
                f"| {k} | {c['n_agree']}/{c['n_solo']} | "
                f"{c['share_agree']:.2f} | {c['med_agree']:+.0f} / "
                f"{c['med_solo']:+.0f} | {c['delta_mean']:+.1f} | "
                f"{c['p_perm']:.3f} | "
                + (f"{c['delta_wo_top']:+.1f}"
                   if c.get("delta_wo_top") is not None else "—")
                + f" | {hs} |")
        return rows
    L.append("\n## Торгуемые книги\n")
    L += table(cells_out)
    L.append(f"\n**Читается так:** {reading(cells_out)}\n")
    L.append("\n## Наблюдательная запись (проверка знака, в свод "
             "не входит)\n")
    L += table(obs_out)
    L.append("\nΔ среднего — среднее нетто согласных минус одиночных, "
             "б.п. на сделку; p — односторонний перестановочный "
             "(согласие лучше случайного разбиения тех же дней). "
             "Половины — Δ в ранней и поздней половинах истории "
             "ячейки.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="согласие рук как фильтр")
    ap.add_argument("--s8", default=os.path.join(
        RESEARCH, "s8_loop", "out"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)

    cells_out, obs_out = {}, {}
    for hz, name in SP.BOOKS + (SP.OBS,):
        mdir = os.path.join(a.s8, name)
        got = SP.book_rows(mdir, hz)
        rows = got[0] if got else []
        if not rows:
            log_(f"{hz}: закрытых сделок нет — пропуск")
            continue
        keys = pick_keys(mdir)
        flag_rows(rows, keys)
        dst = obs_out if hz == SP.OBS[0] else cells_out
        for arm in SP.ARMS:
            sub = [r for r in rows if r["arm"] == arm]
            if not sub:
                continue
            c = cell_stats(sub)
            dst[f"{hz} · {arm}"] = c
            log_(f"{hz} · {arm}: обе {c['n_agree']}, одна "
                 f"{c['n_solo']}"
                 + (f", Δ {c['delta_mean']:+.1f} б.п. (p {c['p_perm']})"
                    if c.get("measured") else " — не измерена"))
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC")}
    path = write_report(os.path.join(OUT, f"AGREE-{a.tag}.md"),
                        cells_out, obs_out, meta)
    with open(os.path.join(OUT, f"agree-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": cells_out, "obs": obs_out, "meta": meta},
                  f, ensure_ascii=False, indent=1)
    log_(f"отчёт: {path}")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
