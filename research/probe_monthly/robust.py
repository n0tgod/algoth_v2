#!/usr/bin/env python3
"""Три оговорки месячного зонда, закрытые замерами.

Зонд намерил: брутто ~102 б.п./мес, издержки ~10, funding ~15, нетто
+77.6 ср. / +129.3 мед. — единственная конструкция за проект с запасом
после ВСЕХ издержек. И три оговорки, каждая из которых может это
отменить. Прежде чем решать «спека или бумажная книга», их надо
закрыть — все три считаются пересчётом сохранённых векторов R2.

Замер 1 — смещение выживших
---------------------------
Форвард R2 частичный по построению (`MIN_FORWARD_BARS = 1`): имя,
умершее внутри 10-дневного кирпича, даёт конечный кирпич, а следующие
NaN. В зонде такое имя ВЫПАДАЕТ из меры целиком. Живая книга держала
бы его до последнего бара и зафиксировала результат.

Рука `alive` — та же книга, где имя с оборванным хвостом кирпичей
входит суммой ИМЕЮЩИХСЯ (остальные кирпичи — ноль: позиции больше
нет). Отличать делистинг от дыры обязательно: считается ПРЕФИКС
кирпичей до первого разрыва, и если после разрыва ряд продолжается —
это дыра, имя выбрасывается, как раньше. Разница рук и есть цена
смещения; печатается и по ногам — умирают обычно упавшие, и выпадение
из короткой ноги режет прибыль, из длинной — убыток.

Замер 2 — бюджет доказательства (Newey-West)
--------------------------------------------
t нетто 1.12 посчитан на 44 непересекающихся сечениях, а дат ребаланса
1330. Перекрывающиеся окна дают больше наблюдений и коррелированные
ошибки — наивный t на них раздут (урок A4: ×4.7 из ничего). Стандартное
лекарство — поправка Ньюи–Уэста на автокорреляцию перекрытия; в проекте
она не применялась ни разу.

Верить ей можно только с калибровкой, поэтому она здесь встроена и
считается ВСЕГДА: на нуле (перестановка сигнала внутри сечения) t по
NW обязан быть около нуля, а наивный t на тех же перекрытых данных —
раздутым. Не выполнится — замер недействителен, и это печатается.

Замер 3 — устойчивость по половинам истории
-------------------------------------------
S11 показал, как монотонный градиент рассыпается на другом разрезе.
Здесь: те же ячейки на первой и второй половине дат. Переворот знака
означает, что эффект принадлежит окну, а не рынку.

Как читаются результаты (объявлено ДО прогона):
- рука `alive` заметно хуже базовой → часть эджа была артефактом
  выпадения умерших, и число зонда завышено;
- NW t ≥ 2.5 при чистой калибровке → деньги предъявимы честной
  поправкой; NW t < 2.0 → бюджета доказательства нет и на перекрытых;
- знак нетто переворачивается между половинами → направление закрыто.

    python3 research/probe_monthly/robust.py --interval 1m --tag 30d
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "r2_residual"))
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import probe as P                                         # noqa: E402
import residual as RS                                     # noqa: E402
import nulls as N                                         # noqa: E402
import run_d1 as R                                        # noqa: E402

# --- объявлено до прогона ---------------------------------------------
NW_MIN_T = 2.5          # чтение: деньги предъявимы
NW_DEAD_T = 2.0         # чтение: бюджета нет
NULL_T_MAX = 1.5        # калибровка: |t| нуля по NW выше — не верить
SEEDS = (1, 2, 3, 4, 5)


def chain_alive(vec, cache, base_names, days):
    """Сумма кирпичей ПРЕФИКСОМ до первого разрыва.

    Возвращает `(сумма, число_кирпичей, статус)` на каждое имя.
    Статус: 2 — все кирпичи на месте; 1 — хвост оборван (делистинг),
    сумма частичная; 0 — разрыв в середине с продолжением (дыра) либо
    нет и первого кирпича.

    Дыра и делистинг РАЗЛИЧАЮТСЯ намеренно: у первой пропущенные
    кирпичи содержат неизвестное движение, у второго — ничего, потому
    что позиции уже нет.
    """
    n = len(base_names)
    parts = []
    for d in days:
        if d not in vec:
            return None
        parts.append(P.aligned(vec, cache, base_names, d, "fwd", P.BRICK))
    A = np.vstack(parts)                       # [кирпич × имя]
    fin = np.isfinite(A)
    total = np.zeros(n)
    cnt = np.zeros(n, dtype=int)
    status = np.zeros(n, dtype=int)
    for j in range(n):
        col = fin[:, j]
        if not col[0]:
            continue
        k = int(np.argmin(col)) if not col.all() else len(col)
        total[j] = A[:k, j].sum()
        cnt[j] = k
        status[j] = 2 if col.all() else (1 if not col[k:].any() else 0)
    total = np.where(status > 0, total, np.nan)
    return total, cnt, status


def build_forward_alive(vec, cache, t, h):
    """Месячный форвард руки `alive`: частичный при делистинге."""
    if h in vec[t]["fwd"]:
        arr = np.asarray(vec[t]["fwd"][h], dtype=np.float64)
        st = np.where(np.isfinite(arr), 2, 0)
        return arr, np.where(np.isfinite(arr), 1, 0), st
    days = [P.shift(t, P.BRICK * i) for i in range(h // P.BRICK)]
    return chain_alive(vec, cache, vec[t]["names"], days)


def book_stats(vec, t, sig, fwd, prev_w, status=None):
    """Одно сечение: нетто книги и состав ног. `None` — дециль вырожден."""
    b = RS.basket_spread(sig, fwd, P.WIDTH)
    if b is None:
        return None
    names = vec[t]["names"]
    w = {}
    for i in b["long_idx"]:
        w[names[i]] = 0.5 / len(b["long_idx"])
    for i in b["short_idx"]:
        w[names[i]] = -0.5 / len(b["short_idx"])
    tr = P.turnover(prev_w, w) if prev_w is not None else 1.0
    net = b["spread"] * 1e4 / 2.0 - tr * P.TAKER_BP
    out = {"net": net, "w": w, "spread": b["spread"] * 1e4,
           "long": b["long"] * 1e4, "short": b["short"] * 1e4}
    if status is not None:
        out["partial_long"] = int(sum(status[i] == 1
                                      for i in b["long_idx"]))
        out["partial_short"] = int(sum(status[i] == 1
                                       for i in b["short_idx"]))
        out["per_leg"] = b["per_leg"]
    return out


def survivorship(vec, cache, dates, k, h, counters):
    """Замер 1: базовая рука против руки `alive` на ОДНИХ датах."""
    base_nets, alive_nets = [], []
    p_long, p_short, legs = 0, 0, 0
    pw_b = pw_a = None
    dropped_only_base = 0
    for t in dates:
        sig = P.build_signal(vec, cache, t, k)
        if sig is None:
            counters["нет прошлого для сигнала"] += 1
            continue
        f_base = P.build_forward(vec, cache, t, h)
        got = build_forward_alive(vec, cache, t, h)
        if f_base is None or got is None:
            counters["нет будущего для форварда"] += 1
            continue
        f_alive, _cnt, status = got
        bb = book_stats(vec, t, sig, f_base, pw_b)
        ba = book_stats(vec, t, sig, f_alive, pw_a, status)
        if bb is None or ba is None:
            counters["дециль вырождается"] += 1
            continue
        pw_b, pw_a = bb["w"], ba["w"]
        base_nets.append(bb["net"])
        alive_nets.append(ba["net"])
        p_long += ba["partial_long"]
        p_short += ba["partial_short"]
        legs += ba["per_leg"]
        dropped_only_base += int(np.sum(
            (status == 1) & ~np.isfinite(f_base)))
    if not base_nets:
        return None
    mb, tb, nb = RS.tstat(base_nets)
    ma, ta, _ = RS.tstat(alive_nets)
    diff = [a - b for a, b in zip(alive_nets, base_nets)]
    md, td, _ = RS.tstat(diff)
    return {
        "sections": nb,
        "base_mean_bp": round(mb, 1),
        "base_median_bp": round(float(np.median(base_nets)), 1),
        "alive_mean_bp": round(ma, 1),
        "alive_median_bp": round(float(np.median(alive_nets)), 1),
        "diff_mean_bp": round(md, 1),
        "diff_t": round(td, 2) if td is not None else None,
        "base_t": round(tb, 2) if tb is not None else None,
        "alive_t": round(ta, 2) if ta is not None else None,
        "partial_long_per_section": round(p_long / nb, 2),
        "partial_short_per_section": round(p_short / nb, 2),
        "legs_per_section": round(legs / nb, 1),
        "dropped_by_base_total": int(dropped_only_base),
    }


def newey_west_t(vals, lag):
    """t-статистика среднего с поправкой Ньюи–Уэста на автокорреляцию.

    Перекрывающиеся месячные окна коррелированы по построению: соседние
    сечения делят 29 из 30 дней форварда. Наивная ошибка среднего это
    игнорирует и завышает t; NW добавляет автоковариации с весами
    Бартлетта. Возвращает `(среднее, t_naive, t_nw, n)`.
    """
    v = np.asarray([x for x in vals if x is not None and x == x],
                   dtype=np.float64)
    n = len(v)
    if n < 3:
        return (float(v.mean()) if n else None), None, None, n
    mean = float(v.mean())
    e = v - mean
    g0 = float(e @ e) / n
    s = g0
    for j in range(1, min(lag, n - 1) + 1):
        gj = float(e[j:] @ e[:-j]) / n
        s += 2.0 * (1.0 - j / (lag + 1.0)) * gj
    sd_naive = float(v.std(ddof=1))
    t_naive = mean / (sd_naive / np.sqrt(n)) if sd_naive > 0 else None
    if s <= 0:
        return mean, t_naive, None, n
    return mean, t_naive, mean / np.sqrt(s / n), n


def overlapping(vec, cache, dates, k, h, counters, seed=None):
    """Нетто по ВСЕМ датам (перекрывающиеся окна) + t наивный и NW.

    Оборот на перекрытых датах считается против книги ПРЕДЫДУЩЕЙ даты
    ребаланса — то есть описывает ежедневно ребалансируемую книгу; для
    сравнения рук этого достаточно, а для вердикта служит
    непересекающийся счёт зонда.
    """
    nets, gross = [], []
    prev_w = None
    for t in dates:
        sig = P.build_signal(vec, cache, t, k)
        if sig is None:
            counters["нет прошлого для сигнала"] += 1
            continue
        fwd = P.build_forward(vec, cache, t, h)
        if fwd is None:
            counters["нет будущего для форварда"] += 1
            continue
        if seed is not None:
            rng = np.random.default_rng(RS.seed_for(seed, t))
            sig = rng.permutation(sig)
        b = book_stats(vec, t, sig, fwd, prev_w)
        if b is None:
            counters["дециль вырождается"] += 1
            continue
        prev_w = b["w"]
        nets.append(b["net"])
        gross.append(b["spread"] / 2.0)
    if len(nets) < 3:
        return None
    mean, tn, tw, n = newey_west_t(nets, lag=h - 1)
    # Брутто идёт рядом ради КАЛИБРОВКИ: у перемешанного нуля книга
    # каждый день набирается заново, платит полный круг издержек, и его
    # НЕТТО систематически отрицательно (≈ −11 б.п.) по построению — на
    # таком ряде поправка проверялась бы на величине с встроенным
    # сдвигом, а это бессмысленно. Ноль ожидания есть только у брутто.
    gm, gtn, gtw, _ = newey_west_t(gross, lag=h - 1)
    return {"sections": n, "mean_bp": round(mean, 1),
            "median_bp": round(float(np.median(nets)), 1),
            "t_naive": round(tn, 2) if tn is not None else None,
            "t_nw": round(tw, 2) if tw is not None else None,
            "pos_share": round(float(np.mean(np.array(nets) > 0)), 3),
            "gross_mean_bp": round(gm, 1),
            "gross_t_naive": round(gtn, 2) if gtn is not None else None,
            "gross_t_nw": round(gtw, 2) if gtw is not None else None}


def halves(vec, cache, dates, k, h, counters):
    """Замер 3: те же ячейки на первой и второй половине дат."""
    mid = len(dates) // 2
    out = {}
    for name, sub in (("первая", dates[:mid]), ("вторая", dates[mid:])):
        nets, prev_w = [], None
        for t in sub[::h]:
            sig = P.build_signal(vec, cache, t, k)
            fwd = P.build_forward(vec, cache, t, h)
            if sig is None or fwd is None:
                continue
            b = book_stats(vec, t, sig, fwd, prev_w)
            if b is None:
                continue
            prev_w = b["w"]
            nets.append(b["net"])
        if len(nets) < 3:
            continue
        m, t_, n = RS.tstat(nets)
        out[name] = {"sections": n, "mean_bp": round(m, 1),
                     "median_bp": round(float(np.median(nets)), 1),
                     "t": round(t_, 2) if t_ is not None else None,
                     "pos_share": round(
                         float(np.mean(np.array(nets) > 0)), 3),
                     "from": sub[0], "to": sub[-1]}
    return out


def verdict_phrase(art):
    """Фраза выводится ИЗ чисел трёх замеров (урок Z2)."""
    s = art.get("survivorship", {}).get(P.MAIN_CELL)
    o = art.get("overlap", {}).get(P.MAIN_CELL)
    hv = art.get("halves", {}).get(P.MAIN_CELL, {})
    if not (s and o):
        return "замеры не сошлись — фразы нет"
    bits = []
    d = s["diff_mean_bp"]
    bits.append(
        f"смещение выживших {'съедает' if d < 0 else 'добавляет'} "
        f"{abs(d):.0f} б.п./мес (базовая {s['base_mean_bp']:+.0f} → "
        f"живая {s['alive_mean_bp']:+.0f})")
    if not art.get("nw_calibrated", True):
        bits.append("поправка Ньюи–Уэста НЕ прошла калибровку на нуле "
                    "— t на перекрытых данных читать нельзя")
    elif o["t_nw"] is None:
        bits.append("t по Ньюи–Уэсту не посчитан")
    elif o["t_nw"] >= NW_MIN_T:
        bits.append(f"на перекрытых данных t по Ньюи–Уэсту "
                    f"{o['t_nw']:.2f} — деньги предъявимы честной "
                    f"поправкой (наивный {o['t_naive']:.2f})")
    elif o["t_nw"] < NW_DEAD_T:
        bits.append(f"t по Ньюи–Уэсту {o['t_nw']:.2f} — бюджета "
                    f"доказательства нет и на перекрытых данных")
    else:
        bits.append(f"t по Ньюи–Уэсту {o['t_nw']:.2f} — между порогами "
                    f"чтения, вердикта нет")
    a, b = hv.get("первая"), hv.get("вторая")
    if a and b:
        if a["mean_bp"] * b["mean_bp"] > 0:
            bits.append(f"знак держится в обеих половинах истории "
                        f"({a['mean_bp']:+.0f} и {b['mean_bp']:+.0f})")
        else:
            bits.append(f"ЗНАК ПЕРЕВОРАЧИВАЕТСЯ между половинами "
                        f"({a['mean_bp']:+.0f} против {b['mean_bp']:+.0f})"
                        f" — эффект принадлежит окну")
    return "; ".join(bits)


def report(art, path):
    a = art
    L = ["# Месячный горизонт: три оговорки, закрытые замерами\n",
         f"Прогон: {a['run_at']}, векторы R2 `{a['interval']}` "
         f"({a['dates']} дат). Пересчёт тех же книг; вердикта нет, "
         "решение за владельцем.\n",
         f"**{a['verdict']}**\n",
         "## 1. Смещение выживших\n",
         "Базовая рука выбрасывает имя, чей хвост кирпичей оборван "
         "(делистинг внутри месяца). Рука «живая» держит его до "
         "последнего бара и фиксирует частичный результат — так "
         "поступила бы книга на бирже. Дыра в середине ряда (после неё "
         "ряд продолжается) выбрасывается в обеих руках.\n",
         "| k | сечений | базовая (ср/мед) | живая (ср/мед) | разность "
         "| t разн. | оборв. ног: лонг / шорт из | ног в ноге |",
         "|---|---|---|---|---|---|---|---|"]
    for k in P.KS:
        s = a["survivorship"].get(f"k{k}_h30")
        if not s:
            L.append(f"| {k} | — | — | — | — | — | — | — |")
            continue
        mark = " **⟵**" if f"k{k}_h30" == P.MAIN_CELL else ""
        L.append(
            f"| {k} | {s['sections']} | {s['base_mean_bp']:+.0f} / "
            f"{s['base_median_bp']:+.0f} | {s['alive_mean_bp']:+.0f} / "
            f"{s['alive_median_bp']:+.0f} | {s['diff_mean_bp']:+.0f} | "
            f"{s['diff_t']} | {s['partial_long_per_section']:.2f} / "
            f"{s['partial_short_per_section']:.2f} | "
            f"{s['legs_per_section']:.0f}{mark} |")
    L += ["", "## 2. Бюджет доказательства на перекрытых окнах\n",
          "Непересекающихся месячных сечений 44 — отсюда t = 1.12 у "
          "зонда. Перекрывающиеся окна дают на порядок больше "
          "наблюдений и коррелированные ошибки; поправка Ньюи–Уэста "
          "(лаг = h−1, веса Бартлетта) это учитывает.\n",
          f"**Калибровка**: на нуле (перестановка сигнала внутри "
          f"сечения, {len(SEEDS)} зёрен) t по NW обязан быть около "
          f"нуля. Калибруется БРУТТО, а не нетто: перемешанная книга "
          f"набирается заново каждый день и платит полный круг "
          f"издержек, поэтому её нетто отрицательно по построению "
          f"(получено {a.get('null_net_mean_bp')} б.п.) — проверять "
          f"поправку на ряде со встроенным сдвигом бессмысленно. "
          f"Брутто нуля: наивный {a['null_t_naive']}, NW "
          f"{a['null_t_nw']} — калибровка "
          f"{'ПРОЙДЕНА' if a['nw_calibrated'] else 'ПРОВАЛЕНА'}.\n",
          "| k | сечений | нетто ср. | нетто мед. | t наивный | t "
          "Ньюи–Уэста | доля > 0 |", "|---|---|---|---|---|---|---|"]
    for k in P.KS:
        o = a["overlap"].get(f"k{k}_h30")
        if not o:
            L.append(f"| {k} | — | — | — | — | — | — |")
            continue
        mark = " **⟵**" if f"k{k}_h30" == P.MAIN_CELL else ""
        L.append(f"| {k} | {o['sections']} | {o['mean_bp']:+.1f} | "
                 f"{o['median_bp']:+.1f} | {o['t_naive']} | "
                 f"**{o['t_nw']}** | {o['pos_share']:.2f}{mark} |")
    L += ["", "Наивный t на перекрытых данных завышен по построению "
          "(соседние окна делят 29 из 30 дней) — он приведён рядом "
          "именно как мера того, насколько поправка кусается.\n",
          "## 3. Устойчивость по половинам истории\n",
          "| k | половина | период | сечений | ср. | мед. | t | >0 |",
          "|---|---|---|---|---|---|---|---|"]
    for k in P.KS:
        hv = a["halves"].get(f"k{k}_h30", {})
        for nm in ("первая", "вторая"):
            v = hv.get(nm)
            if not v:
                continue
            L.append(f"| {k} | {nm} | {v['from']} … {v['to']} | "
                     f"{v['sections']} | {v['mean_bp']:+.0f} | "
                     f"{v['median_bp']:+.0f} | {v['t']} | "
                     f"{v['pos_share']:.2f} |")
    L += ["", "## Пропуски\n"]
    for kk, v in sorted(a["skipped"].items()):
        L.append(f"- {kk}: {v}")
    L += ["", "## Чего замеры НЕ снимают\n",
          "- β кирпичей: каждый посчитан по своей β, на формациях "
          "длиннее 14 дней цена этого не измерена;",
          "- funding здесь не вычтен (он в отдельном отчёте: −15.3 "
          "б.п./мес у главной ячейки) — числа этой страницы БЕЗ него;",
          "- поправка Ньюи–Уэста лечит автокорреляцию, но не "
          "малое число НЕЗАВИСИМЫХ эпизодов рынка: 3.7 года истории "
          "остаются 3.7 годами."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--tag", default="30d")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    t0 = time.time()
    vec = N.load_vectors(a.interval)
    dates_all = sorted(vec)
    print(f"векторов {len(dates_all)} дат "
          f"({dates_all[0]} … {dates_all[-1]})")

    counters = {k: 0 for k in (
        "нет прошлого для сигнала", "нет будущего для форварда",
        "дециль вырождается")}
    cache = {}
    surv, over, halv = {}, {}, {}
    for k in P.KS:
        key = f"k{k}_h30"
        print(f"  {key}: смещение выживших")
        got = survivorship(vec, cache, dates_all[::30], k, 30, counters)
        if got:
            surv[key] = got
        print(f"  {key}: перекрытые окна")
        got = overlapping(vec, cache, dates_all, k, 30, counters)
        if got:
            over[key] = got
        halv[key] = halves(vec, cache, dates_all, k, 30, counters)

    # Калибровка NW: нуль обязан дать t около нуля на тех же данных.
    print("  калибровка нуля на перекрытых окнах")
    nt_naive, nt_nw, nt_net = [], [], []
    for s in SEEDS:
        nc = {kk: 0 for kk in counters}
        k = int(P.MAIN_CELL.split("_")[0][1:])
        got = overlapping(vec, cache, dates_all, k, 30, nc, seed=s)
        if got and got["gross_t_nw"] is not None:
            # калибруем БРУТТО: у нетто перемешанного нуля ожидание
            # отрицательно на величину издержек полного оборота
            nt_naive.append(got["gross_t_naive"])
            nt_nw.append(got["gross_t_nw"])
            nt_net.append(got["mean_bp"])
    null_naive = round(float(np.mean(nt_naive)), 2) if nt_naive else None
    null_nw = round(float(np.mean(nt_nw)), 2) if nt_nw else None
    calibrated = (null_nw is not None and abs(null_nw) <= NULL_T_MAX)

    if not surv or not over:
        for kk, v in sorted(counters.items()):
            print(f"  пропуск — {kk}: {v}")
        raise SystemExit("замеры не собрались — причины выше")

    art = {
        "run_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "interval": a.interval, "dates": len(dates_all),
        "main_cell": P.MAIN_CELL, "seeds": list(SEEDS),
        "survivorship": surv, "overlap": over, "halves": halv,
        "null_t_naive": null_naive, "null_t_nw": null_nw,
        "null_net_mean_bp": (round(float(np.mean(nt_net)), 1)
                             if nt_net else None),
        "nw_calibrated": calibrated,
        "skipped": counters,
        "took_min": round((time.time() - t0) / 60, 1),
    }
    art["verdict"] = verdict_phrase(art)
    p = os.path.join(a.out, f"MONTHLY-robust-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"MONTHLY-robust-{a.tag}.md"))
    print(f"готово: {p} ({art['took_min']} мин)")
    print(f"  {art['verdict']}")
    if not a.no_publish:
        R.publish(f"месячный горизонт: три оговорки замерами ({a.tag})")


if __name__ == "__main__":
    main()
