#!/usr/bin/env python3
"""
Потолок трёх рычагов против сквиза — до того, как строить хоть один.

Вопрос владельца, на который S1 не ответил: были предложены три рычага,
а проверен один и в слабой форме (обратная волатильность вместо
«меньше там, где вероятен сквиз»), плюс обычный стоп — тот самый,
который сам же назван худшим инструментом.

Здесь считается **верхняя граница** пользы всех трёх, и считается она
недостижимо оптимистично: с идеальным знанием будущего. Если даже такой
потолок не выводит книгу к порогу, все три рычага закрыты разом, и
строить их незачем. Это тот же приём, что закрыл вопрос о мейкерском
исполнении за час вместо недель (§12.2 спеки 03).

Что именно считается
--------------------

- **A, идеальное избегание сквиза** — из книги убраны ноги, которые
  ПО ФАКТУ потеряли больше 100 % позиции. Знать это заранее нельзя ни
  при каком правиле; величина есть предел любой защиты от сквиза;
- **B, идеальное избегание делистинга** — убраны короткие ноги в
  активах, снимаемых с торгов Bybit в ближайшие 30 дней. Дата снятия
  известна задним числом, дата объявления не собрана — поэтому это
  тоже потолок, а не правило;
- **C, асимметрия ног** — единственный из трёх, который **не требует
  знания будущего**: короткая нога получает меньшую долю гросса.
  Значение объявлено одно и не перебирается.

Освободившийся вес НЕ перераспределяется ни в одном варианте: доливка
пошла бы в позиции, которые в этот момент, скорее всего, тоже под
давлением. Книга просто становится меньше.

    python3 ceilings.py --interval 1m
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
A1 = os.path.join(RESEARCH, "a1_universe", "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "f1_carry"))
sys.path.insert(0, os.path.join(RESEARCH, "r5_backtest"))
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))

import managed as MG         # noqa: E402
import carry as CY           # noqa: E402
import stats as ST           # noqa: E402
import pairs as P            # noqa: E402

KS = (7, 14)
HS = (5, 10)
WIDTHS = {"decile": 0.10, "quintile": 0.20}
DECLARED_STOP = {5: 0.35, 10: 0.45}

SHORT_SHARE = 0.35           # вариант C: доля гросса на короткую ногу
DELIST_HORIZON = 30
REQUIRED_SHARPE = 1.53       # §8.2 спеки 05 при восьми испытаниях
DD_LIMIT = 0.20


def load_vectors(tag):
    d = os.path.join(OUT, "vectors")
    out = {}
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.startswith(tag + "_") and fn.endswith(".json"):
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    out.update(json.load(f))
    if not out:
        raise SystemExit(f"нет векторов S1 для {tag} — сначала run.py")
    return out


def delist_days(universe):
    with open(os.path.join(A1, "instruments.json"), encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw if isinstance(raw, list) else list(raw.values())
    by_symbol = {}
    for r in rows:
        dt = r.get("delivery_time")
        if r.get("status") != "Closed" or not dt or dt in ("0", 0):
            continue
        by_symbol[r["symbol"]] = str(
            np.datetime64(int(dt), "ms").astype("datetime64[D]"))
    return {a: by_symbol[v["bybit_symbol"]] for a, v in universe.items()
            if v.get("bybit_symbol") and v["bybit_symbol"] in by_symbol}


def beta(book, mkt):
    """Наклон доходности книги на доходность равновзвешенной волны.

    Критерий 11 §8.2 спеки: |β| ≤ 0.2. Для вариантов A и B он
    формальность — веса ног остаются равными. Для варианта C он
    решающий: короткая нога урезана, книга становится чистым лонгом на
    30 % гросса, и в растущем рынке это даёт доход, не имеющий к carry
    никакого отношения.
    """
    m = np.isfinite(book) & np.isfinite(mkt)
    if m.sum() < 10:
        return None
    x, y = mkt[m], book[m]
    dx, dy = x - x.mean(), y - y.mean()
    sxx = float(dx @ dx)
    return float(dx @ dy) / sxx if sxx > 0 else None


def arr(v, key, sub):
    return np.asarray(v[key][str(sub)], dtype=np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--funding-venue", default="bybit")
    a = ap.parse_args()
    tag = f"{a.interval}_{a.funding_venue}"

    vec = load_vectors(tag)
    dates = sorted(vec)
    _, universe = P.load_liquidity(a.interval)
    dl = delist_days(universe)

    arms = ("managed", "A_no_squeeze", "B_no_delist", "C_asymmetric",
            "ABC_all")
    out = {}
    for k in KS:
        for h in HS:
            level = DECLARED_STOP[h]
            for wname, width in WIDTHS.items():
                name = f"k{k}_h{h}_{wname}"
                series = {arm: [] for arm in arms}
                dropped = {arm: [] for arm in arms}
                # Доходность равновзвешенной волны за тот же период —
                # знаменатель критерия 11. Вариант C делает книгу
                # НЕсбалансированной по деньгам, и без беты его успех
                # неотличим от простого лонга рынка.
                market = []

                for day in dates[::h]:
                    v = vec[day]
                    names = v["names"]
                    score, vol = arr(v, "score", k), arr(v, "vol", k)
                    price, fund = arr(v, "price", h), arr(v, "funding", h)
                    ok = np.isfinite(price) & np.isfinite(fund)
                    w, per_leg = MG.inverse_vol_weights(score, vol, width)
                    if per_leg < 1:
                        continue
                    pos = CY.position_return(np.sign(w), np.where(ok, price,
                                                                  0.0))
                    e = v["exit"][str(h)][str(level)]
                    er = np.where(w > 0,
                                  np.asarray(e["long"][0], dtype=np.float64),
                                  np.asarray(e["short"][0], dtype=np.float64))
                    ef = np.where(w > 0,
                                  np.asarray(e["long"][1], dtype=np.float64),
                                  np.asarray(e["short"][1], dtype=np.float64))
                    ret, _ = MG.apply_exits(w, pos, np.where(ok, er, np.nan),
                                            ef, np.where(ok, fund, 0.0))
                    ret = np.where(ok, ret, 0.0)

                    fin = np.isfinite(price)
                    market.append(float(np.expm1(price[fin]).mean())
                                  if fin.any() else np.nan)
                    blown = ret < -1.0
                    t = date.fromisoformat(day)
                    near = np.array([
                        bool(dl.get(s)
                             and 0 <= (date.fromisoformat(dl[s]) - t).days
                             <= DELIST_HORIZON)
                        for s in names])

                    masks = {
                        "managed": np.ones(len(w), dtype=bool),
                        "A_no_squeeze": ~blown,
                        "B_no_delist": ~(near & (w < 0)),
                        "ABC_all": ~blown & ~(near & (w < 0)),
                    }
                    for arm, keep in masks.items():
                        ww = np.where(keep, w, 0.0)
                        if arm == "ABC_all":
                            ww = np.where(ww < 0, ww * SHORT_SHARE / 0.5, ww)
                        series[arm].append(float((np.abs(ww) * ret).sum()))
                        dropped[arm].append(
                            float(np.abs(w[~keep]).sum()))
                    # C считается отдельно: без всякого знания будущего
                    wc = np.where(w < 0, w * SHORT_SHARE / 0.5, w)
                    series["C_asymmetric"].append(
                        float((np.abs(wc) * ret).sum()))
                    dropped["C_asymmetric"].append(0.0)

                if len(series["managed"]) < 10:
                    continue
                ppy = 365.0 / h
                row = {"periods": len(series["managed"])}
                mk = np.asarray(market, dtype=np.float64)
                for arm in arms:
                    v2 = series[arm]
                    b = beta(np.asarray(v2), mk)
                    row[arm] = {
                        "annual": float(np.mean(v2)) * ppy,
                        "sharpe": ST.sharpe(v2, ppy),
                        "drawdown": ST.max_drawdown(v2)["max_drawdown"],
                        "dropped_weight": CY.robust(dropped[arm]),
                        "beta": b,
                    }
                out[name] = row

    doc = {"config": {"interval": a.interval, "funding_venue":
                      a.funding_venue, "short_share": SHORT_SHARE,
                      "delist_horizon": DELIST_HORIZON,
                      "required_sharpe": REQUIRED_SHARPE,
                      "dd_limit": DD_LIMIT},
           "cells": out}
    with open(os.path.join(OUT, f"ceilings_{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    titles = {"managed": "S1 как есть", "A_no_squeeze": "A: без сквизов",
              "B_no_delist": "B: без делистингов",
              "C_asymmetric": f"C: шорт {SHORT_SHARE:.0%}",
              "ABC_all": "A+B+C вместе"}
    print("ПОТОЛОК ТРЁХ РЫЧАГОВ. A и B используют знание будущего.\n")
    print(f"{'вариант':<22}{'Sharpe':>9}{'лучший':>9}{'просадка':>11}"
          f"{'доходность':>12}{'|β| медиана':>13}{'ячеек ≥1.53':>13}")
    for arm in arms:
        srs = [out[n][arm]["sharpe"] for n in out
               if out[n][arm]["sharpe"] is not None]
        dds = [out[n][arm]["drawdown"] for n in out]
        ann = [out[n][arm]["annual"] for n in out]
        bs = [abs(out[n][arm]["beta"]) for n in out
              if out[n][arm]["beta"] is not None]
        good = sum(1 for s in srs if s >= REQUIRED_SHARPE)
        print(f"{titles[arm]:<22}{np.median(srs):>9.2f}{max(srs):>9.2f}"
              f"{np.median(dds):>10.1%}{np.median(ann):>11.1%}"
              f"{np.median(bs):>13.2f}{good:>13}")
    print(f"\nтребуется Sharpe ≥ {REQUIRED_SHARPE} и просадка ≤ "
          f"{DD_LIMIT:.0%} (§8.2 спеки 05)")
    print("Критерий 11: |β| ≤ 0.2. Вариант C урезает короткую ногу, то "
          "есть делает книгу чистым лонгом на 30 % гросса — его Sharpe "
          "читать только вместе с бетой.")
    print("A и B недостижимы: дата сквиза и дата снятия известны только "
          "задним числом. C — единственный вариант, не требующий знания "
          "будущего.")


if __name__ == "__main__":
    main()
