#!/usr/bin/env python3
"""
R4 — издержки на фактическом обороте книги.

Спека 03, этап R4 и раздел 6. Считается по векторам, сохранённым
прогоном R2: состав дециля из них восстанавливается точно, значит
оборот книги измеряется, а не предполагается.

Что именно проверяется
----------------------

До сих пор все спреды были брутто. Здесь впервые появляется цена
исполнения, и по конструкции она бьёт по коротким горизонтам: при
ежедневном ребалансе и удержании в сутки книга обновляется целиком
каждый день. Ячейки с лучшим брутто-IC — первые кандидаты на смерть от
оборота, и это надо увидеть числом.

Два прогона обязательны, а не один
----------------------------------

Ставки нет у 36.7 % крипто-активов универсума, и назначать её приходится
правилом. Правило способно перевернуть вердикт в одиночку, поэтому
считаются оба:

- **базовый** — ожидаемая ставка квинтиля оборота на окне формирования;
- **пессимистичный** — плоские 11.0 б.п. всем, у кого ставки нет.

Расхождение вердиктов означает «не определено данными», а не
«положительно». Завышенная издержка убивает настоящий эдж так же
надёжно, как заниженная создаёт несуществующий.

Funding
-------

Требует рядов площадки исполнения (`a1_universe/out/funding/`, в git не
идут). Без них прогон считает только комиссию и помечает это в
артефакте — молча выдавать неполные издержки за полные нельзя.

У книги, равной по деньгам с обеих сторон, funding есть ДИФФЕРЕНЦИАЛ
ног, а не сумма, и знак его заранее неизвестен: ноги отбираются
возвратом остатка, а не ставкой. Это замер, а не поправка.

    python3 run.py --interval 1m
    python3 run.py --interval 15m --no-funding
"""

import argparse
import csv
import gzip
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
A1 = os.path.join(RESEARCH, "a1_universe", "out")
VECTORS = os.path.join(RESEARCH, "r2_residual", "out", "vectors")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "asset_groups"))

import costs as C            # noqa: E402
import pairs as P            # noqa: E402

BP = 0.0001
CHEAP, MODAL, EXPENSIVE = 2.75 * BP, 5.5 * BP, 11.0 * BP
# Доля дорогого тарифа по квинтилям оборота, замер A1 (раздел 6 спеки).
EXPENSIVE_SHARE = [0.432, 0.326, 0.137, 0.147, 0.052]

WIDTHS = {"decile": 0.10, "quintile": 0.20}
COST_MULTIPLIER = 1.5        # критерий §8.3 п. 9
# Ниже этого числа символов с рядами funding покрытие считается
# отсутствующим: частичное покрытие даёт заниженную издержку, выдавая
# её за полную.
MIN_FUNDING_SYMBOLS = 50


def load_vectors(interval):
    out = {}
    if not os.path.isdir(VECTORS):
        raise SystemExit(f"нет {VECTORS} — сначала r2_residual/crosssection.py")
    for fn in sorted(os.listdir(VECTORS)):
        if not (fn.startswith(interval + "_") and fn.endswith(".json")):
            continue
        with open(os.path.join(VECTORS, fn), encoding="utf-8") as f:
            for d, v in json.load(f).items():
                out[d] = {"names": v["names"],
                          "sig": {int(k): np.asarray(x, dtype=np.float64)
                                  for k, x in v["sig"].items()},
                          "fwd": {int(k): np.asarray(x, dtype=np.float64)
                                  for k, x in v["fwd"].items()}}
    if not out:
        raise SystemExit(f"в {VECTORS} нет дампов для {interval}")
    return out


def load_fees(universe):
    """Ставка тейкера по базовому активу. None там, где её нет."""
    with open(os.path.join(A1, "fees.json"), encoding="utf-8") as f:
        raw = {r["symbol"]: float(r["takerFeeRate"]) for r in json.load(f)}
    out = {}
    for a, v in universe.items():
        s = v.get("bybit_symbol")
        out[a] = raw.get(s) if s else None
    return out


def load_funding(universe, symbols):
    """Ряды funding площадки исполнения: `{актив: (времена_мс, ставки)}`.

    Формат — тот, что пишет сборщик A1 (`bybit_api.py`): gzip-CSV с
    заголовком `funding_time,funding_rate`, время в миллисекундах, файл
    на символ Bybit. Первая редакция искала `.json` и не находила
    ничего; каталог при этом существовал, поэтому прогон отрапортовал
    «funding включён» и посчитал нули.

    Возвращает `None`, если каталога нет вовсе.
    """
    d = os.path.join(A1, "funding")
    if not os.path.isdir(d):
        return None
    by_symbol = {v["bybit_symbol"]: a for a, v in universe.items()
                 if v.get("bybit_symbol")}
    out = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".csv.gz"):
            continue
        sym = fn[:-len(".csv.gz")]
        a = by_symbol.get(sym)
        if a is None or a not in symbols:
            continue
        t, r = [], []
        with gzip.open(os.path.join(d, fn), "rt", encoding="utf-8") as f:
            rd = csv.reader(f)
            next(rd, None)                      # заголовок
            for row in rd:
                if len(row) < 2:
                    continue
                t.append(int(row[0]))
                r.append(float(row[1]))
        if t:
            o = np.argsort(t)
            out[a] = (np.asarray(t, dtype=np.int64)[o],
                      np.asarray(r, dtype=np.float64)[o])
    return out


def accrued(funding, asset, t0_ms, t1_ms):
    """Сумма ставок, начисленных в `[t0, t1)`.

    Число начислений берётся из ряда, а не из объявленного интервала:
    318 символов из 722 меняли режим по ходу истории, и константа даёт
    у 128 активов ошибку больше 15 %, местами двукратную.
    """
    v = funding.get(asset)
    if v is None:
        return None
    t, r = v
    i0 = int(np.searchsorted(t, t0_ms, "left"))
    i1 = int(np.searchsorted(t, t1_ms, "left"))
    if i1 <= i0:
        return 0.0
    return float(r[i0:i1].sum())


def ms(day):
    return int(np.datetime64(day + "T00:00:00", "ms").astype("int64"))


def rate_table(names, fees, state, rule):
    """Ставка каждого имени по выбранному правилу назначения."""
    known = {s: fees.get(s) for s in names}
    if rule == "pessimistic":
        return {s: (known[s] if known[s] is not None else EXPENSIVE)
                for s in names}
    missing = [s for s in names if known[s] is None]
    turns = [(state.get(s) or {}).get("turnover") for s in missing]
    imputed = C.quintile_expected_rate(turns, EXPENSIVE_SHARE, MODAL,
                                       EXPENSIVE, EXPENSIVE)
    out = dict(known)
    for s, r in zip(missing, imputed):
        out[s] = r
    return out


def run_cell(dates, vec, k, h, width, fees, states, funding, rule):
    """Проход по непересекающимся датам с переносом книги между ними."""
    prev_names, prev_w = [], np.array([])
    gross, comm, fund, turn, nets = [], [], [], [], []
    for d in dates[::h]:
        v = vec[d]
        w, per_leg = C.weights(v["sig"][k], v["fwd"][h], width)
        if per_leg < 1:
            continue
        names = v["names"]
        rates = rate_table(names, fees, states.get(d, {}), rule)

        order, delta, tot = C.turnover(prev_names, prev_w, names, w)
        c = C.commission(order, delta, lambda s: rates.get(s, EXPENSIVE))

        g = float(np.dot(w, np.nan_to_num(v["fwd"][h])))
        f = 0.0
        if funding is not None:
            t0 = ms(d)
            t1 = ms((date.fromisoformat(d) + timedelta(days=h)).isoformat())
            f = C.funding_cost(names, w,
                               lambda s: accrued(funding, s, t0, t1))
        gross.append(g)
        comm.append(c)
        fund.append(f)
        turn.append(tot)
        nets.append(g - c - f)
        prev_names, prev_w = names, w

    if not nets:
        return None

    def stat(v):
        v = np.asarray(v)
        return {"mean": float(v.mean()), "median": float(np.median(v))}

    n = np.asarray(nets)
    sd = float(n.std(ddof=1)) if len(n) > 1 else 0.0
    return {
        # Ряд доходностей по периодам, а не только его среднее. R5 считает
        # по нему просадку, худший подпериод и Deflated Sharpe — из
        # агрегата их не восстановить, а второй прогон ради этого стоил бы
        # ещё одного круга на сервер.
        "series": [round(float(x), 12) for x in nets],
        "sections": len(nets),
        "gross": stat(gross), "commission": stat(comm),
        "funding": stat(fund), "turnover": stat(turn),
        "net": stat(nets),
        "net_positive_share": float((n > 0).mean()),
        "net_t": (float(n.mean() / (sd / np.sqrt(len(n)))) if sd > 0 else None),
        # Критерий §8.3 п. 9: издержки в полтора раза выше модельных.
        "net_stressed": float((np.asarray(gross)
                               - COST_MULTIPLIER * (np.asarray(comm)
                                                    + np.asarray(fund))).mean()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--no-funding", action="store_true")
    args = ap.parse_args()

    vec = load_vectors(args.interval)
    dates = sorted(vec)
    liq, universe = P.load_liquidity(args.interval)
    fees = load_fees(universe)

    used = sorted({s for d in dates for s in vec[d]["names"]})
    funding = None if args.no_funding else load_funding(universe, set(used))
    # Пустой словарь — НЕ то же самое, что посчитанный ноль. Каталог может
    # существовать и быть пустым, имена символов могут не сойтись — и
    # тогда funding_cost вернёт 0.0 по каждой ноге, а сводка отрапортует
    # «funding включён». Ровно так и вышло на первом прогоне: +0.00 б.п.
    # во всех 32 ячейках. Точный ноль везде есть признак отсутствия
    # данных, а не свойство рынка, и различать это обязан код.
    covered = len(funding) if funding else 0
    if funding is not None and covered < MIN_FUNDING_SYMBOLS:
        print(f"рядов funding нашлось {covered} из {len(used)} активов — "
              f"это не покрытие, а его отсутствие; считается только "
              f"комиссия", file=sys.stderr, flush=True)
        funding = None
    if funding is None and not args.no_funding:
        print("funding НЕ включён", file=sys.stderr, flush=True)
    elif funding is not None:
        print(f"funding: ряды у {covered} активов из {len(used)}",
              file=sys.stderr, flush=True)

    # Оборот на окне формирования нужен только для правила назначения
    # ставки делистнутой ноге, поэтому считается один раз на дату.
    states = {}
    for d in dates:
        states[d] = P.state_at(liq, universe, d)

    ks = sorted(vec[dates[0]]["sig"])
    hs = sorted(vec[dates[0]]["fwd"])
    out = {}
    for rule in ("expected", "pessimistic"):
        cells = {}
        for k in ks:
            for h in hs:
                for wname, w in WIDTHS.items():
                    r = run_cell(dates, vec, k, h, w, fees, states, funding,
                                 rule)
                    if r:
                        cells[f"k{k}_h{h}_{wname}"] = r
        out[rule] = cells
        med = np.median([c["net"]["median"] for c in cells.values()])
        print(f"{rule}: ячеек {len(cells)}, медиана нетто по сетке "
              f"{med * 10000:+.1f} б.п.", file=sys.stderr, flush=True)

    # Даты ребаланса хранятся один раз на горизонт, а не в каждой ячейке:
    # они одинаковы у всех ячеек с общим h.
    dates_by_h = {str(h): dates[::h] for h in hs}
    doc = {"dates_by_h": dates_by_h,
           "config": {"interval": args.interval, "ks": ks, "hs": hs,
                      "widths": WIDTHS, "cost_multiplier": COST_MULTIPLIER,
                      "expensive_share": EXPENSIVE_SHARE,
                      "cheap_bp": CHEAP / BP, "modal_bp": MODAL / BP,
                      "expensive_bp": EXPENSIVE / BP,
                      "funding_included": funding is not None,
                      "funding_symbols": covered,
                      "universe_symbols": len(used),
                      "sections_total": len(dates)},
           "rules": out}
    os.makedirs(OUT, exist_ok=True)
    name = f"costs_{args.interval}.json"
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"записано {os.path.join(OUT, name)}")


if __name__ == "__main__":
    main()
