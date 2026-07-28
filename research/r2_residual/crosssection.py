#!/usr/bin/env python3
"""
R2 — возврат остатка вне выборки, кросс-секционный прогон.

Спека 03, этап R2. Отвечает на критерии §8.3 п. 1–3 и на критерий
немедленной остановки §8.2, **не доходя до бэктеста**.

Протокол одной даты ребаланса `t`
---------------------------------

    │──── окно формирования 90 дн ────│──── форвард h ────│
                        │─ сигнал k ─│
                                      ↑ t

- β оценивается на окне формирования `[t−90, t)` против равновзвешенной
  волны «все, кроме меня» (ядро R1);
- сигнал — накопленный остаток за последние `k` дней окна, со знаком
  минус: положительный сигнал означает «отстал от волны»;
- форвард — накопленный остаток за `[t, t+h)` **по той же β**. Никакого
  пересчёта коэффициента на торговом окне: прямой запрет CLAUDE.md.

Форвардное окно не пересекается с окном формирования ни одним баром,
поэтому эмбарго §6 спеки 02 здесь не нужно: оно защищало от того, что
пара отбиралась и торговалась на одних данных. Сигнал же обязан
примыкать к форварду вплотную — возврат к среднему на горизонте в дни
именно этим и является, и зазор в неделю уничтожил бы измеряемое.

Сигнал считается внутри окна формирования, то есть по той же β, что и
подогнана на нём. Это не заглядывание в будущее — будущих данных в β
нет вовсе, — но остаток сигнала слегка сжат подгонкой. Смещение
консервативное: сжимается именно то отклонение, которое мы ищем.

Почему сетка дат плотная
------------------------

A4 шла по 48 окнам с шагом 30 дней. Здесь этого мало: критерий §8.3
п. 10 требует не менее 100 **непересекающихся** сечений, а при 48 датах
их не набрать ни при каком `h`. Ребаланс идёт ежедневно, а
непересекающиеся сечения набираются прореживанием каждой `h`-й датой.
Докладываются обе величины, но решение §8.3 принимается по
непересекающимся: урок A4 стоил месяца — превосходство ×4.7 целиком
создавалось перекрытием окон.

Ступень лестницы §3.3
---------------------

Первый прогон — голая рыночная волна. Спека требует строить следующую
ступень только после того, как измерена предыдущая, поэтому сектор и
PCA-3 идут отдельными прогонами, а не все сразу. Это не сокращение
объявленной сетки §2: значения из неё никуда не делись, они считаются
позже и в отчёт войдут все.

    python3 crosssection.py --interval 1m
    python3 crosssection.py --interval 1m --report
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CHUNKS = os.path.join(OUT, "chunks")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "r1_factor"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))

import residual as RS        # noqa: E402
import factor as FA          # noqa: E402
import series as S           # noqa: E402
import pairs as P            # noqa: E402

STEP = "1h"                  # выбран замером в A4, подтверждён R1
BARS_PER_DAY = 24
FORM_DAYS = 90
MODEL = "market"             # ступень 1 лестницы §3.3

# Сетка §2 спеки 03. Объявлена до прогона и не меняется.
KS = (1, 3, 7, 14)           # окно накопления сигнала, дни
HS = (1, 3, 5, 10)           # горизонт удержания, дни
WIDTHS = {"decile": 0.10, "quintile": 0.20}

GRID_START = "2022-07-01"
GRID_END = "2026-06-01"
REBALANCE_STEP_DAYS = 1
CHUNK_DAYS = 90              # сколько дат ребаланса обрабатывается за одну загрузку

MIN_ASSETS = 30              # сечение тоньше — дециль вырождается в 3 имени
MIN_FORWARD_BARS = 1


def rebalance_dates(start, end, step_days):
    t, last = date.fromisoformat(start), date.fromisoformat(end)
    while t <= last:
        yield t.isoformat()
        t += timedelta(days=step_days)


def ms(day):
    return int(np.datetime64(day + "T00:00:00", "ms").astype("int64"))


def fit_window(R, F_loo, need):
    """β каждого актива на окне формирования. NaN там, где не оценивается."""
    n = R.shape[1]
    beta = np.full(n, np.nan)
    for j in range(n):
        r = FA.regress(R[:, j], F_loo[:, j])
        if r is not None and r[2] >= need:
            beta[j] = r[0]
    return beta


def run_date(at, grid, PX, cols, live, state, universe, rng=None):
    """Одно сечение: сигналы по всем k, форварды по всем h, IC и корзины."""
    t_ms = ms(at)
    i_t = int(np.searchsorted(grid, t_ms))
    i_form = int(np.searchsorted(grid, ms(
        (date.fromisoformat(at) - timedelta(days=FORM_DAYS)).isoformat())))
    if i_t - i_form < FORM_DAYS * BARS_PER_DAY // 2:
        return None

    # Волна строится только по активам, живым и ликвидным на эту дату.
    keep = [i for i, c in enumerate(cols) if c in live]
    if len(keep) < MIN_ASSETS:
        return None
    sub = PX[:, keep]
    names = [cols[i] for i in keep]

    R = FA.log_returns(sub)
    _, F_loo, _ = FA.market_factor(R)
    # Индексация после log_returns: R[i] — переход grid[i] -> grid[i+1].
    # Значит R[i_t − 1] есть доходность часа, ЗАКОНЧИВШЕГОСЯ в момент t,
    # то есть уже известного при ребалансе; она принадлежит сигналу.
    # Первый торгуемый бар — R[i_t]. Граница между сигналом и форвардом
    # проходит ровно по i_t:
    #
    #     формирование  R[i_form : i_t]
    #     сигнал        R[i_t − k·24 : i_t]
    #     форвард       R[i_t : i_t + h·24]
    #
    # Сдвиг на один бар здесь не косметика. Включив R[i_t − 1] в форвард,
    # мы бы зарабатывали на часе, который уже произошёл, — и любой отскок
    # после падения в окне сигнала пришёл бы в результат как эдж.
    need = int(FA.MIN_COVERAGE * (i_t - i_form))
    (f0, f1), _, _ = RS.window_bounds(i_form, i_t, len(R), 1, 1, BARS_PER_DAY)
    beta = fit_window(R[f0:f1], F_loo[f0:f1], need)

    row = {"date": at, "assets": len(names),
           "beta_median": float(np.nanmedian(beta)) if np.isfinite(beta).any()
           else None,
           "beta_fitted": int(np.isfinite(beta).sum()), "cells": {}}

    sig = {}
    for k in KS:
        _, (s0, s1), _ = RS.window_bounds(i_form, i_t, len(R), k, 1,
                                          BARS_PER_DAY)
        e, _ = RS.accumulate(R, F_loo, beta, s0, s1)
        sig[k] = np.where(np.isfinite(beta), -e, np.nan)

    if rng is not None:
        # Нуль 1 §7: «кто какой сигнал получил» перемешивается между
        # активами внутри сечения. Разрушается ровно одно — связь
        # сигнала с активом. Универсум, форвардные доходности, ширина
        # корзины, число ног, структура портфеля остаются на месте.
        #
        # Перестановка ОДНА на дату и применяется ко всем k: так
        # сохраняется взаимная структура сигналов разных горизонтов, и
        # нуль остаётся консервативным. Отдельная перестановка на каждое
        # k разрушала бы больше, чем требуется, и завышала бы разрыв.
        #
        # Переставляются и NaN вместе со значениями: иначе актив без
        # сигнала получил бы чужой, и число наблюдений в сечении
        # изменилось бы — нуль перестал бы отличаться от прогона только
        # разрывом связи.
        perm = rng.permutation(len(names))
        sig = {k: v[perm] for k, v in sig.items()}

    fwd, fwd_bars = {}, {}
    for h in HS:
        _, _, (w0, w1) = RS.window_bounds(i_form, i_t, len(R), 1, h,
                                          BARS_PER_DAY)
        e, nb = RS.accumulate(R, F_loo, beta, w0, w1)
        fwd[h] = np.where(np.isfinite(beta) & (nb >= MIN_FORWARD_BARS),
                          e, np.nan)
        fwd_bars[h] = nb

    for k in KS:
        for h in HS:
            ic, n = RS.spearman(sig[k], fwd[h])
            cell = {"ic": ic, "n": n}
            for wname, w in WIDTHS.items():
                b = RS.basket_spread(sig[k], fwd[h], w)
                if b is None:
                    continue
                cell[wname] = {"spread": b["spread"], "long": b["long"],
                               "short": b["short"], "per_leg": b["per_leg"]}
                if wname == "decile" and h == HS[1] and k == KS[2]:
                    # Диагностика ловушек §5.2 и §5.3 снимается на одной
                    # ячейке: состав дециля против универсума по обороту,
                    # свежести цены и возрасту листинга.
                    cell["composition"] = composition(
                        b, names, state, universe, at)
            row["cells"][f"k{k}_h{h}"] = cell
    return row


def composition(b, names, state, universe, at):
    """Чем дециль отличается от универсума. §5.2 и §5.3 спеки 03."""
    def stats(idx):
        turn, share, age = [], [], []
        for i in idx:
            a = names[i]
            s = state.get(a)
            if not s:
                continue
            turn.append(s["turnover"])
            share.append(s["share_traded"])
            li = universe.get(a, {}).get("listed")
            if li:
                age.append((date.fromisoformat(at)
                            - date.fromisoformat(li)).days)
        med = lambda v: float(np.median(v)) if v else None  # noqa: E731
        return {"turnover": med(turn), "share_traded": med(share),
                "age_days": med(age), "n": len(turn)}

    return {"long": stats(b["long_idx"]), "short": stats(b["short_idx"]),
            "universe": stats(range(len(names)))}


def process_chunk(con, dates, liq, universe, interval, null_seed=None):
    """Одна загрузка данных на группу дат: память под контролем.

    Читать всю историю разом — 36 тыс. баров на 700 символов, порядка
    полугигабайта только под матрицу цен, и это на машине, которая уже
    уходила в OOM при сборке A2. Загрузка идёт кусками: на группу дат
    берётся ровно то окно, которое ей нужно.
    """
    t0 = (date.fromisoformat(dates[0]) - timedelta(days=FORM_DAYS)).isoformat()
    t1 = (date.fromisoformat(dates[-1]) + timedelta(days=max(HS) + 1)).isoformat()

    live_by_date, wanted = {}, set()
    for at in dates:
        st = P.state_at(liq, universe, at)
        live = {a for a, s in st.items()
                if s["share_traded"] >= P.MIN_SHARE_TRADED}
        live_by_date[at] = (live, st)
        wanted |= live
    if not wanted:
        return []

    sym_of = {a: universe[a]["binance_symbol"] for a in wanted
              if universe[a].get("binance_symbol")}
    raw = S.load(con, sorted(sym_of.values()), t0, t1, step=STEP,
                 interval=interval)
    if not raw:
        return []
    by_asset = {a: raw[s] for a, s in sym_of.items() if s in raw}
    grid, cols, PX = FA.price_grid(by_asset, STEP, ms(t0), ms(t1))

    out = []
    for at in dates:
        live, st = live_by_date[at]
        # Зерно завязано на дату: прогон остаётся воспроизводимым и не
        # зависит от того, каким куском и в каком порядке считался.
        rng = (np.random.default_rng(
            abs(hash((null_seed, at))) % (2 ** 32)) if null_seed is not None
            else None)
        r = run_date(at, grid, PX, cols, live, st, universe, rng)
        if r:
            out.append(r)
    return out


def tag(interval, null_seed):
    return interval if null_seed is None else f"{interval}_null{null_seed}"


def chunk_path(interval, i, null_seed=None):
    return os.path.join(CHUNKS, f"{tag(interval, null_seed)}_{i:03d}.json")


def load_chunks(interval, null_seed=None):
    """Состояние с диска, а не из дельты прогона (урок A2)."""
    rows = []
    if not os.path.isdir(CHUNKS):
        return rows
    for fn in sorted(os.listdir(CHUNKS)):
        if fn.startswith(tag(interval, null_seed) + "_") \
                and fn.endswith(".json") and ("null" in fn) == (
                    null_seed is not None):
            with open(os.path.join(CHUNKS, fn), encoding="utf-8") as f:
                rows.extend(json.load(f))
    rows.sort(key=lambda r: r["date"])
    return rows


def summarize(rows):
    s = {"sections_total": len(rows), "cells": {}}
    if not rows:
        return s
    s["date_first"], s["date_last"] = rows[0]["date"], rows[-1]["date"]
    s["assets"] = {"median": float(np.median([r["assets"] for r in rows])),
                   "min": int(min(r["assets"] for r in rows)),
                   "max": int(max(r["assets"] for r in rows))}
    by_date = {r["date"]: r for r in rows}
    order = sorted(by_date)

    for k in KS:
        for h in HS:
            key = f"k{k}_h{h}"
            # Непересекающиеся сечения: каждая h-я дата. Перекрытие —
            # ровно то, что обесценило результат A4.
            indep = order[::h]
            def pull(dates, field, sub=None):
                v = []
                for d in dates:
                    c = by_date[d]["cells"].get(key)
                    if not c:
                        continue
                    x = c.get(field) if sub is None else \
                        (c.get(field) or {}).get(sub)
                    if x is not None:
                        v.append(x)
                return v

            ic_all = pull(order, "ic")
            ic_ind = pull(indep, "ic")
            m_all, t_all, n_all = RS.tstat(ic_all)
            m_ind, t_ind, n_ind = RS.tstat(ic_ind)
            cell = {
                "ic_overlapping": {"mean": m_all, "t": t_all, "sections": n_all,
                                   "positive_share": share_positive(ic_all)},
                "ic_independent": {"mean": m_ind, "t": t_ind, "sections": n_ind,
                                   "positive_share": share_positive(ic_ind),
                                   "q": RS.quantiles(ic_ind)},
            }
            for wname in WIDTHS:
                sp = pull(indep, wname, "spread")
                m, t, n = RS.tstat(sp)
                # Одного среднего мало, и это не педантизм. Распределение
                # спреда по сечениям имеет тяжёлые хвосты: отдельные
                # сечения дают ±20 % и более, поэтому среднее тащат
                # единицы наблюдений. В двух ячейках сетки среднее вышло
                # отрицательным при положительной медиане — то есть по
                # среднему ячейка читалась бы как «возврата нет», хотя
                # в большинстве сечений он есть. Медиана и усечённое
                # среднее докладываются рядом, чтобы вывод не зависел от
                # выбора меры.
                cell[wname] = {"spread_mean": m, "t": t, "sections": n,
                               "spread_median": robust(sp, "median"),
                               "spread_trimmed": robust(sp, "trimmed"),
                               "positive_share": share_positive(sp),
                               "q": RS.quantiles(sp),
                               "annualized": (m * 365.0 / h) if m is not None
                               else None,
                               "annualized_median": (
                                   robust(sp, "median") * 365.0 / h)
                               if robust(sp, "median") is not None else None}
            s["cells"][key] = cell

    # Диагностика ловушек §5.2 и §5.3 агрегируется здесь, а не в отчёте.
    # Иначе отчёту нужен массив всех сечений, артефакт раздувается до
    # мегабайтов и в git не идёт — а сводка обязана быть самодостаточной,
    # как walkforward_summary.json в A4.
    comps = [r["cells"]["k7_h3"]["composition"] for r in rows
             if r["cells"].get("k7_h3", {}).get("composition")]
    if comps:
        def med_of(leg, field):
            v = sorted(c[leg][field] for c in comps
                       if c[leg].get(field) is not None)
            return float(np.median(v)) if v else None
        s["composition"] = {
            leg: {f: med_of(leg, f)
                  for f in ("turnover", "share_traded", "age_days")}
            for leg in ("long", "short", "universe")}
        s["composition"]["sections"] = len(comps)

    ics = [c["ic_independent"]["mean"] for c in s["cells"].values()
           if c["ic_independent"]["mean"] is not None]
    s["grid"] = {"cells": len(s["cells"]),
                 "ic_median": float(np.median(ics)) if ics else None,
                 "ic_best": max(ics) if ics else None,
                 "ic_worst": min(ics) if ics else None,
                 "positive_cells": sum(1 for x in ics if x > 0)}
    return s


def robust(v, how):
    """Медиана и усечённое на 5 % с каждого хвоста среднее."""
    v = sorted(x for x in v if x is not None and x == x)
    if not v:
        return None
    if how == "median":
        return float(np.median(v))
    cut = len(v) // 20
    w = v[cut:len(v) - cut] if len(v) > 2 * cut + 1 else v
    return float(np.mean(w))


def share_positive(v):
    v = [x for x in v if x is not None and x == x]
    return (sum(1 for x in v if x > 0) / len(v)) if v else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--start", default=GRID_START)
    ap.add_argument("--end", default=GRID_END)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--null-seed", type=int, default=None,
                    help="нулевая модель §7: сигнал перемешан между активами")
    args = ap.parse_args()

    os.makedirs(CHUNKS, exist_ok=True)
    if not args.report:
        liq, universe = P.load_liquidity(args.interval)
        con = S.connect()
        dates = list(rebalance_dates(args.start, args.end,
                                     REBALANCE_STEP_DAYS))
        groups = [dates[i:i + CHUNK_DAYS]
                  for i in range(0, len(dates), CHUNK_DAYS)]
        for i, g in enumerate(groups):
            path = chunk_path(args.interval, i, args.null_seed)
            if os.path.exists(path) and not args.rerun:
                continue
            t = time.time()
            rows = process_chunk(con, g, liq, universe,
                                 args.interval, args.null_seed)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False)
            os.replace(tmp, path)
            print(f"  {i + 1}/{len(groups)} {g[0]}…{g[-1]}: сечений "
                  f"{len(rows)}, {time.time() - t:.1f} с",
                  file=sys.stderr, flush=True)

    rows = load_chunks(args.interval, args.null_seed)
    s = summarize(rows)
    config = {"step": STEP, "model": MODEL, "form_days": FORM_DAYS,
              "ks": list(KS), "hs": list(HS), "widths": WIDTHS,
              "rebalance_step_days": REBALANCE_STEP_DAYS,
              "grid_start": args.start, "grid_end": args.end,
              "min_assets": MIN_ASSETS, "interval": args.interval,
              "null_seed": args.null_seed}
    name = f"crosssection_{tag(args.interval, args.null_seed)}.json"
    # В артефакт идёт сводка, а не все сечения: подробности живут в
    # chunks/ и пересобираются за минуты, а в git должно попадать то, что
    # читается человеком и сравнивается между прогонами.
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump({"config": config, "summary": s}, f, ensure_ascii=False,
                  indent=1)
    print(json.dumps(s["grid"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
