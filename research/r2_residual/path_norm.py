#!/usr/bin/env python3
"""
Замер к идее владельца: нормировать сигнал длиной пути (эквивалент RSI).

Зачем это здесь
---------------

Предложение звучало как «использовать RSI внутри отрезков расхождения».
Считать RSI на цене ноги нельзя — это вернуло бы в книгу направление
рынка, ровно то, что вычитается волной. RSI на **остатке** осмыслен, и
он не является новым сигналом: при определении Уайлдера через суммы
приращений вверх и вниз

    RSI = 100 · U / (U + D),   U − D = чистое смещение, U + D = длина пути

то есть

    RSI = 50 · (1 + чистое / путь)

Сигнал §4 спеки 03 — это ровно «чистое» (сумма остатков за k дней, со
знаком минус). RSI получается делением его на длину пути. А раз сечение
ранжируется, любое строго монотонное преобразование даёт тот же
портфель: переход к RSI сводится к одному вопросу — **помогает ли делить
на путь**.

Здесь этот вопрос и меряется. Ничего не прогоняется заново: берутся
сохранённые векторы R2 (`out/vectors/`), из подённых сигналов `sig[1]`
собирается путь за k дней, и сравниваются IC трёх величин.

Почему числитель берётся из тех же подённых кусков
--------------------------------------------------

Первая версия делила сохранённый `sig[k]` на путь, собранный из
подённых `sig[1]`, и сверяла себя требованием «сумма подённых равна
k-дневному». Сверка не прошла — и была права: **β переоценивается на
каждую дату ребаланса** (`i_form = i_t − 90 дней`, окно формирования
скользит). Значит подённый сигнал даты `t−1` посчитан по другой β, чем
k-дневный сигнал даты `t`, и тождества нет и быть не может.

Поэтому числитель собирается из тех же кусков, что и знаменатель:
`чистое = Σ подённых`, `путь = Σ |подённых|`, и `RSI = 50·(1 + чистое /
путь)` выполняется точно. Расхождение «чистого» с сохранённым `sig[k]`
остаётся в отчёте как диагностика — она показывает, насколько
переоценка β меняет сам сигнал, и это самостоятельно полезное число.
"""

import argparse
import glob
import json
import os

import numpy as np

import residual as RS

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
VECTORS = os.path.join(OUT, "vectors")

DAY = "1"          # подённый сигнал, из него собираются и путь, и чистое
MIN_AGREE = 0.98   # ниже — подённые куски и k-дневный сигнал суть разные


def window_files(interval, model):
    tag = f"{interval}_" if model == "market" else f"{interval}_{model}_"
    out = []
    for p in sorted(glob.glob(os.path.join(VECTORS, tag + "*.json"))):
        rest = os.path.basename(p)[len(tag):]
        if len(rest) == len("YYYY-MM-DD.json"):
            out.append(p)
    return out


def daily_pieces(win, dates, i, k, names):
    """Подённые сигналы за k дней, выровненные по именам текущей даты.

    Имена сопоставляются по названию актива, а не по позиции: состав
    сечения меняется от даты к дате, и совпадение длин ничего не
    гарантирует. Актив, у которого хотя бы один из k дней отсутствует,
    выбывает целиком — путь короче k дней есть другая величина.
    """
    run = np.zeros(len(names))
    net = np.zeros(len(names))
    ok = np.ones(len(names), dtype=bool)
    for j in range(k):
        prev = win[dates[i - j]]
        pos = {n: p for p, n in enumerate(prev["names"])}
        v = np.full(len(names), np.nan)
        for p, n in enumerate(names):
            q = pos.get(n)
            if q is not None:
                v[p] = prev["sig"][DAY][q]
        ok &= np.isfinite(v)
        run += np.where(np.isfinite(v), np.abs(v), 0.0)
        net += np.where(np.isfinite(v), v, 0.0)
    return np.where(ok, net, np.nan), np.where(ok, run, np.nan)


def gross_sharpe(spreads, h):
    """Годовой Sharpe по непересекающимся периодам, брутто.

    Сечения идут ежедневно, а форвард длится h дней — соседние сечения
    делят данные. Поэтому берётся каждое h-е, как в R5: иначе разброс
    занижается перекрытием и Sharpe выходит завышенным.

    Брутто: издержек здесь нет, и число не сравнимо с §8.3 п. 6 напрямую.
    Сравнивать его можно только с таким же брутто соседней колонки —
    вопрос ведь в том, меняет ли нормировка пути знаменатель.
    """
    v = np.asarray(spreads, dtype=np.float64)
    v = v[np.isfinite(v)]
    if len(v) < 10:
        return None, None, None
    sd = float(v.std(ddof=1))
    if sd <= 0:
        return None, None, None
    per_year = 365.0 / h
    sr_p = float(v.mean()) / sd
    n = len(v)
    # Стандартная ошибка Sharpe (Лоу): sqrt((1 + SR²/2) / N) на период,
    # затем годовое масштабирование тем же множителем. Без неё разность
    # двух Sharpe на сотне периодов читается как результат, хотя обе
    # величины шумят сильнее, чем расходятся.
    se = np.sqrt((1.0 + sr_p ** 2 / 2.0) / n) * np.sqrt(per_year)
    return sr_p * np.sqrt(per_year), float((v > 0).mean()), float(se)


def collect(interval, model, ks, hs, width=0.1):
    acc = {(k, h): {"stored": [], "net": [], "rsi": [], "rho": []}
           for k in ks for h in hs}
    # Спреды копятся по датам, а прореживаются после — по общему списку
    # дат, ровно как `dates[::h]` в R4. Прореживание внутри окна сбивало
    # бы фазу на каждой границе, и ряд перестал бы совпадать с тем, по
    # которому считан Sharpe этапа R5.
    spread = {(k, h): {} for k in ks for h in hs}
    agree = {k: [] for k in ks}
    ratio = {k: [] for k in ks}

    for path in window_files(interval, model):
        with open(path) as f:
            win = json.load(f)
        dates = sorted(win)
        for i, d in enumerate(dates):
            cur = win[d]
            names = cur["names"]
            for k in ks:
                if i + 1 < k:
                    continue
                net, run = daily_pieces(win, dates, i, k, names)
                stored = np.asarray(cur["sig"][str(k)], dtype=np.float64)

                # Диагностика переоценки β: насколько сигнал, собранный
                # из подённых кусков, отличается от посчитанного за k
                # дней одной β. В рангах — потому что портфель строится
                # по рангам.
                r, _ = RS.spearman(net, stored)
                if r is not None:
                    agree[k].append(r)
                m = np.isfinite(net) & np.isfinite(stored)
                if m.sum() >= 3:
                    s = float(np.median(np.abs(stored[m])))
                    if s > 0:
                        ratio[k].append(
                            float(np.median(np.abs(net[m] - stored[m]))) / s)

                with np.errstate(invalid="ignore", divide="ignore"):
                    rsi = np.where(run > 0, net / run, np.nan)

                for h in hs:
                    fwd = np.asarray(cur["fwd"][str(h)], dtype=np.float64)
                    cell = acc[(k, h)]
                    for key, vec in (("stored", stored), ("net", net),
                                     ("rsi", rsi)):
                        v, _ = RS.spearman(vec, fwd)
                        if v is not None:
                            cell[key].append(v)
                    v, _ = RS.spearman(net, rsi)
                    if v is not None:
                        cell["rho"].append(v)

                    row = {}
                    for key, vec in (("stored", stored), ("net", net),
                                     ("rsi", rsi)):
                        b = RS.basket_spread(vec, fwd, width)
                        row[key] = b["spread"] if b else np.nan
                    spread[(k, h)][d] = row

    return acc, agree, ratio, spread


def median(v):
    return float(np.median(v)) if len(v) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--model", default="market")
    ap.add_argument("--ks", default="3,7,14")
    ap.add_argument("--hs", default="1,3,5,10")
    a = ap.parse_args()

    ks = [int(x) for x in a.ks.split(",")]
    hs = [int(x) for x in a.hs.split(",")]
    acc, agree, ratio, spread = collect(a.interval, a.model, ks, hs)
    all_dates = sorted({d for c in spread.values() for d in c})

    print("диагностика переоценки β: сигнал из подённых кусков против "
          "сохранённого")
    for k in ks:
        g, q = median(agree[k]), median(ratio[k])
        print(f"  k={k:<3} ранговое согласие {g:.4f}   "
              f"медианное расхождение {q * 100:.1f} % от величины сигнала")
        if g is not None and g < MIN_AGREE:
            raise SystemExit(
                f"k={k}: подённые куски дают другой сигнал (согласие {g:.3f})")

    rows = []
    print(f"\n{'ячейка':<10}{'IC сигнал':>11}{'IC /путь':>10}{'Δ IC':>9}"
          f"{'SR сигнал':>11}{'SR /путь':>10}{'дол.+ сиг':>11}"
          f"{'дол.+ /пути':>12}{'ранг.корр':>11}")
    for k in ks:
        for h in hs:
            c = acc[(k, h)]
            st, ne, rs = median(c["stored"]), median(c["net"]), median(c["rsi"])
            if ne is None or rs is None:
                continue
            keep = [spread[(k, h)][d] for d in all_dates[::h]
                    if d in spread[(k, h)]]
            sr_s, pos_s, _ = gross_sharpe([r["stored"] for r in keep], h)
            sr_n, pos_n, se_n = gross_sharpe([r["net"] for r in keep], h)
            sr_r, pos_r, se_r = gross_sharpe([r["rsi"] for r in keep], h)
            f2 = lambda x: f"{x:.2f}" if x is not None else "  — "
            f3 = lambda x: f"{x:.3f}" if x is not None else "  — "
            print(f"k{k}_h{h:<7}{ne:>11.4f}{rs:>10.4f}{rs - ne:>9.4f}"
                  f"{f2(sr_n):>11}{f2(sr_r):>10}{'±' + f2(se_n):>9}"
                  f"{f3(pos_n):>11}{f3(pos_r):>12}"
                  f"{median(c['rho']):>11.3f}")
            rows.append({"k": k, "h": h, "ic_stored": st, "ic_net": ne,
                         "ic_rsi": rs, "delta": rs - ne,
                         "sharpe_stored": sr_s, "sharpe_net": sr_n,
                         "sharpe_rsi": sr_r, "sharpe_se": se_n,
                         "sharpe_se_rsi": se_r,
                         "pos_stored": pos_s, "pos_net": pos_n,
                         "pos_rsi": pos_r, "periods": len(keep),
                         "rank_corr": median(c["rho"]),
                         "sections": len(c["net"])})

    dst = os.path.join(OUT, f"path_norm_{a.interval}_{a.model}.json")
    with open(dst, "w") as f:
        json.dump({"config": {"interval": a.interval, "model": a.model,
                              "ks": ks, "hs": hs},
                   "beta_refit": {str(k): {"rank_agreement": median(agree[k]),
                                           "median_rel_gap": median(ratio[k])}
                                  for k in ks},
                   "cells": rows}, f, ensure_ascii=False, indent=2)
    print(f"\n→ {dst}")


if __name__ == "__main__":
    main()
