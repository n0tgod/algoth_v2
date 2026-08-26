#!/usr/bin/env python3
"""Funding месячной книги — вторая половина зонда месячного горизонта.

Зонд намерил нетто +93 б.п. за 30 дней БЕЗ funding, и это главная из
трёх оговорок: на месячном удержании funding первого порядка (медиана
дифференциала ног 19.7 % годовых ≈ 160 б.п./мес — сопоставим со всем
спредом), и R4 намерил, что длинная нога возврата funding ПЛАТИТ. Пока
он не посчитан, про месячную книгу нельзя сказать ничего.

Устройство: те же книги, что построил зонд (пары пересобираются тем же
кодом `probe.py`), к каждому непересекающемуся сечению добавляется
funding окна удержания `[t, t+h)` по рядам ПЛОЩАДКИ ИСПОЛНЕНИЯ
(каталог A1, Bybit; подмена площадки запрещена спекой 02 §2.0). Число
начислений берётся из ряда, а не из объявленного интервала (318
символов меняли режим). Знак — конвенция `funding_series`:
положительная ставка — лонги платят шортам, издержка позиции =
вес · сумма ставок; в отчёте funding печатается ИЗДЕРЖКОЙ
(положительное = книга платит) и вычитается из нетто.

Встроенная сверка: нетто БЕЗ funding, пересчитанное здесь из тех же
векторов, обязано совпасть с артефактом зонда — расхождение прерывает
прогон (узор `nulls.py` против R2: два пути к одному числу).

Правила меры:
- нога без ряда funding — НЕ ноль: её вес идёт в «недоучтённый гросс»
  и печатается числом; сечение с недоучётом больше UNCOVERED_MAX
  выбрасывается из свода С funding (в свод без funding входит);
- ноги докладываются отдельно (§5.1 спеки 04: разложение по ногам уже
  ловило дефект, который агрегат прятал нулём).

Запуск (на VPS, после зонда):

    python3 research/probe_monthly/funding_cost.py --interval 1m --tag 30d
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta, datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
A1 = os.path.join(RESEARCH, "a1_universe", "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))
sys.path.insert(0, RESEARCH)

import probe as P                                         # noqa: E402
import residual as RS                                     # noqa: E402
import nulls as N                                         # noqa: E402
import run_d1 as R                                        # noqa: E402
from common import funding_series as FS                   # noqa: E402

UNCOVERED_MAX = 0.10   # выше — funding сечения не измерен, а придуман
NET_TOL = 0.06         # допуск сверки с артефактом зонда (округление)


def load_universe(path=None):
    p = path or os.path.join(A1, "universe.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["assets"]


def book_of(vec, t, sig, fwd):
    """Книга сечения: {актив: вес}, Σ|w| = 1 — тот же дециль, что зонд."""
    b = RS.basket_spread(sig, fwd, P.WIDTH)
    if b is None:
        return None, None
    names = vec[t]["names"]
    w = {}
    for i in b["long_idx"]:
        w[names[i]] = 0.5 / len(b["long_idx"])
    for i in b["short_idx"]:
        w[names[i]] = -0.5 / len(b["short_idx"])
    return w, b


def funding_of_book(funding, w, t, h):
    """Издержка funding книги за `[t, t+h)`, б.п. гросса, по ногам.

    Возвращает `(итог, лонги, шорты, недоучтённый_гросс)`; нога без
    ряда не превращается в ноль — её вес копится отдельно.
    """
    t0 = FS.ms(t)
    t1 = FS.ms((date.fromisoformat(t) + timedelta(days=h)).isoformat())
    tot = long_c = short_c = uncovered = 0.0
    for a, wa in w.items():
        acc = FS.accrued(funding, a, t0, t1)
        if acc is None:
            uncovered += abs(wa)
            continue
        c = wa * acc * 1e4
        tot += c
        if wa > 0:
            long_c += c
        else:
            short_c += c
    return tot, long_c, short_c, uncovered


def measure_cell_funding(vec, pairs, funding, h, counters):
    """Funding и нетто-с-funding по сечениям ячейки; рядом пересчёт
    нетто БЕЗ funding — для сверки с артефактом зонда."""
    nets0, netsf, fcosts, flong, fshort, uncov = [], [], [], [], [], []
    prev_w = None
    for t, sig, fwd in pairs:
        w, b = book_of(vec, t, sig, fwd)
        if w is None:
            counters["дециль вырождается"] += 1
            continue
        tr = P.turnover(prev_w, w) if prev_w is not None else 1.0
        prev_w = w
        net0 = b["spread"] * 1e4 / 2.0 - tr * P.TAKER_BP
        nets0.append(net0)
        fc, fl, fsh, un = funding_of_book(funding, w, t, h)
        uncov.append(un)
        if un > UNCOVERED_MAX:
            counters["funding недоучтён"] += 1
            continue
        fcosts.append(fc)
        flong.append(fl)
        fshort.append(fsh)
        netsf.append(net0 - fc)
    if not netsf:
        return None
    mean_f, t_f, _ = RS.tstat(netsf)
    return {
        "sections": len(netsf),
        "net0_median_bp": round(float(np.median(nets0)), 1),
        "net0_mean_bp": round(float(np.mean(nets0)), 1),
        "funding_median_bp": round(float(np.median(fcosts)), 1),
        "funding_mean_bp": round(float(np.mean(fcosts)), 1),
        "funding_long_mean_bp": round(float(np.mean(flong)), 1),
        "funding_short_mean_bp": round(float(np.mean(fshort)), 1),
        "netf_median_bp": round(float(np.median(netsf)), 1),
        "netf_mean_bp": round(mean_f, 1),
        "netf_t": round(t_f, 2) if t_f is not None else None,
        "netf_pos_share": round(float(np.mean(np.array(netsf) > 0)), 3),
        "netf_worst_bp": round(float(np.min(netsf)), 1),
        "uncovered_median": round(float(np.median(uncov)), 3),
    }


def crosscheck(cells_f, probe_art):
    """Нетто без funding обязано совпасть с артефактом зонда.

    Два пути к одному числу: расхождение означает, что funding считался
    ДРУГИМ книгам, и весь замер описывает не то, что подписано.
    """
    bad = []
    for key, c in cells_f.items():
        ref = probe_art["cells"].get(key)
        if ref is None:
            continue
        for a, b in (("net0_median_bp", "net_median_bp"),
                     ("net0_mean_bp", "net_mean_bp")):
            if abs(c[a] - ref[b]) > NET_TOL:
                bad.append({"cell": key, "field": a,
                            "here": c[a], "probe": ref[b]})
    return bad


def verdict_phrase(cell):
    """Фраза выводится ИЗ чисел главной ячейки (урок Z2)."""
    if cell is None:
        return "главная ячейка не измерена — фразы нет"
    f, n0, nf = (cell["funding_mean_bp"], cell["net0_mean_bp"],
                 cell["netf_mean_bp"])
    if nf > 0 and cell["netf_median_bp"] > 0:
        return (f"funding книгу не убивает: издержка в среднем "
                f"{f:+.1f} б.п. за период, нетто {n0:+.1f} → {nf:+.1f} "
                f"(медиана {cell['netf_median_bp']:+.1f}) — обе меры "
                f"остаются в плюсе")
    if nf > 0 or cell["netf_median_bp"] > 0:
        return (f"с funding книга живёт ТОЛЬКО одной мерой: среднее "
                f"{nf:+.1f}, медиана {cell['netf_median_bp']:+.1f} б.п. "
                f"— расхождение знака есть подпись хвоста, вердикта нет")
    return (f"funding съедает книгу: издержка в среднем {f:+.1f} б.п. "
            f"за период, нетто {n0:+.1f} → {nf:+.1f} (медиана "
            f"{cell['netf_median_bp']:+.1f})")


def report(art, path):
    a = art
    L = ["# Funding месячной книги\n",
         f"Прогон: {a['run_at']}, векторы R2 `{a['interval']}`, ряды "
         f"funding площадки исполнения ({a['funding_assets']} активов). "
         "Вторая половина зонда месячного горизонта: те же книги, тот "
         "же дециль, к каждому сечению добавлен funding окна удержания."
         "\n",
         f"**{a['verdict']}**\n",
         "Знак: funding печатается ИЗДЕРЖКОЙ (положительное — книга "
         "платит) и вычитается из нетто. Нога без ряда не ноль: её вес "
         "— «недоучтённый гросс», сечение с недоучётом больше "
         f"{UNCOVERED_MAX:.0%} в свод с funding не входит.\n",
         "## Ячейки h = 30 (по непересекающимся сечениям)\n",
         "| k, дн | сечений | нетто без f. (мед/ср) | funding "
         "(мед/ср) | лонги | шорты | нетто с f. (мед/ср) | t | >0 | "
         "худшее | недоучёт |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in P.KS:
        c = a["cells"].get(f"k{k}_h30")
        if c is None:
            L.append(f"| {k} | — | — | — | — | — | — | — | — | — | — |")
            continue
        mark = " **⟵**" if f"k{k}_h30" == P.MAIN_CELL else ""
        L.append(
            f"| {k} | {c['sections']} | {c['net0_median_bp']:+.1f} / "
            f"{c['net0_mean_bp']:+.1f} | {c['funding_median_bp']:+.1f} "
            f"/ {c['funding_mean_bp']:+.1f} | "
            f"{c['funding_long_mean_bp']:+.1f} | "
            f"{c['funding_short_mean_bp']:+.1f} | "
            f"{c['netf_median_bp']:+.1f} / {c['netf_mean_bp']:+.1f} | "
            f"{c['netf_t']} | {c['netf_pos_share']:.2f} | "
            f"{c['netf_worst_bp']:+.1f} | {c['uncovered_median']:.3f}"
            f"{mark} |")
    L += ["",
          "«Лонги»/«шорты» — средняя издержка ноги (шорт при "
          "положительной ставке ПОЛУЧАЕТ — у него минус). Сверка нетто "
          "без funding с артефактом зонда: "
          f"{a['crosscheck_bad']} расхождений.\n",
          "## Пропуски\n"]
    for kk, v in sorted(a["skipped"].items()):
        L.append(f"- {kk}: {v}")
    L += ["", "## Оговорки, не снимаемые замером\n",
          "- ставка начисляется на нотионал позиции по её ходу; здесь "
          "вес книги считается постоянным внутри окна — дрейф веса за "
          "30 дней в числах нет;",
          "- ряды A1 закрывались датой сбора: последние сечения могут "
          "терять хвост окна — это видно в «недоучтённом гроссе»;",
          "- комиссия модальным тейкером, как в зонде; хвост и бюджет "
          "доказательства — оговорки зонда, funding их не снимает."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--tag", default="30d")
    ap.add_argument("--funding-dir", default=os.path.join(A1, "funding"))
    ap.add_argument("--universe", default=None)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    probe_path = os.path.join(a.out, f"MONTHLY-{a.tag}.json")
    if not os.path.exists(probe_path):
        raise SystemExit(f"нет артефакта зонда {probe_path} — сначала "
                         f"probe.py")
    probe_art = json.load(open(probe_path, encoding="utf-8"))

    t0 = time.time()
    vec = N.load_vectors(a.interval)
    dates_all = sorted(vec)
    universe = load_universe(a.universe)
    funding = FS.load_funding(a.funding_dir, universe, set(universe))
    if funding is None:
        raise SystemExit(f"нет каталога {a.funding_dir}")
    if len(funding) < FS.MIN_FUNDING_SYMBOLS:
        raise SystemExit(f"рядов funding {len(funding)} — это не "
                         f"покрытие, а его отсутствие")
    print(f"векторов {len(dates_all)} дат, рядов funding {len(funding)}")

    counters = {k: 0 for k in (
        "нет прошлого для сигнала", "нет будущего для форварда",
        "дециль вырождается", "funding недоучтён")}
    cache, cells = {}, {}
    for k in P.KS:
        pairs = P.build_pairs(vec, cache, dates_all[::30], k, 30,
                              counters)
        got = measure_cell_funding(vec, pairs, funding, 30, counters)
        if got:
            cells[f"k{k}_h30"] = got
    if not cells:
        for kk, v in sorted(counters.items()):
            print(f"  пропуск — {kk}: {v}")
        raise SystemExit("ни одной измеренной ячейки — причины выше")

    bad = crosscheck(cells, probe_art)
    if bad:
        for b in bad:
            print(f"  РАСХОЖДЕНИЕ {b}")
        raise SystemExit(
            "нетто без funding не совпало с артефактом зонда — funding "
            "посчитан другим книгам, замер недействителен")

    art = {
        "run_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "interval": a.interval, "tag": a.tag,
        "funding_assets": len(funding),
        "uncovered_max": UNCOVERED_MAX,
        "cells": cells, "skipped": counters,
        "crosscheck_bad": 0,
        "verdict": verdict_phrase(cells.get(P.MAIN_CELL)),
        "took_min": round((time.time() - t0) / 60, 1),
    }
    p = os.path.join(a.out, f"MONTHLY-funding-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"MONTHLY-funding-{a.tag}.md"))
    print(f"готово: {p} ({art['took_min']} мин)")
    print(f"  {art['verdict']}")
    if not a.no_publish:
        R.publish(f"funding месячной книги ({a.tag})")


if __name__ == "__main__":
    main()
