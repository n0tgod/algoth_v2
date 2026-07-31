#!/usr/bin/env python3
"""
Замер: зависит ли исход сделки от локального тренда в момент входа.

Гипотеза владельца, записанная его словами до счёта
---------------------------------------------------

«Определение локального тренда — не всегда нужно открывать сделки против
тренда, потому что потенциал их движения намного меньше и вероятность
попасть на перелом тренда намного меньше».

Проверка прямая: у каждой сделки известны символ, время и сторона.
Локальный тренд считается по минутным барам ДО входа, и сделки делятся
на «по тренду», «против» и «тренда нет». Если владелец прав, у сделок
против тренда ожидание должно быть хуже.

Почему это не то же самое, что прошлый замер
--------------------------------------------

Потолок отсева показал: три сильнейших признака (время с прошлой сделки,
длина серии, был ли стоп в ту же сторону) — все косвенные меры одного и
того же, «идёт ли движение». Тренд меряет это прямо, а не по следам
собственных сделок. Признак при этом остаётся известным в момент входа.

Устройство
----------

Сетка окон объявлена ДО прогона и не меняется: 15, 60 и 240 минут.
Порогов нет вовсе — сторона тренда определяется знаком изменения цены за
окно, а «тренда нет» это когда изменение меньше обычного хода за то же
окно (медиана |изменения| по всей неделе для этого символа). Мера
безразмерна и своя у каждой монеты: 20 б.п. за час для BTC — движение, а
для мелкого альта — стояние.

Цены берутся из архива Binance, а сделки прогонялись по ленте Bybit.
Здесь это законно: тренд — УСЛОВИЕ на состояние рынка, а не форвард
сделки. Направление движения актива от площадки не зависит; расходится
базис, а не знак часового хода. Форвард по-прежнему считается тем, что
записал сам прогон.

    python3 research/t4_structure/trend.py
"""

import argparse
import io
import json
import math
import os
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(HERE, "out", "bars")
DAILY = "https://data.binance.vision/data/futures/um/daily/klines"
WINDOWS = (15, 60, 240)          # минуты; объявлено до прогона
SEED = 20260731


def day_bars(symbol, day):
    """Минутные бары символа за сутки: `{метка: (открытие, закрытие)}`."""
    os.makedirs(os.path.join(CACHE, symbol), exist_ok=True)
    path = os.path.join(CACHE, symbol, f"{day}.zip")
    if not os.path.exists(path):
        url = f"{DAILY}/{symbol}/1m/{symbol}-1m-{day}.zip"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                blob = r.read()
        except Exception:                                 # noqa: BLE001
            return {}
        with open(path, "wb") as f:
            f.write(blob)
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read(z.namelist()[0]).decode()
    except Exception:                                     # noqa: BLE001
        return {}
    for line in raw.splitlines():
        p = line.split(",")
        if len(p) < 5 or not p[0].isdigit():
            continue
        # Метка в миллисекундах либо микросекундах — архив за разные
        # годы пишет по-разному, и молча поделить не на то значит
        # сдвинуть весь ряд на годы.
        t = int(p[0])
        t = t // 1000 if t > 1e12 else t
        out[int(t)] = (float(p[1]), float(p[4]))
    return out


def load_bars(syms, days):
    bars = {}
    for s in sorted(syms):
        b = {}
        for d in days:
            b.update(day_bars(s, d))
        bars[s] = b
        print(f"  {s:12} баров {len(b)}", file=sys.stderr)
    return bars


def load_trades(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = []
    for t in d.get("trades") or []:
        entry, stop = float(t["entry"]), float(t["stop"])
        stop_bp = abs(entry - stop) / entry * 1e4
        ts = datetime.fromisoformat(t["t"])
        rows.append({"sym": t["sym"], "t": int(ts.timestamp()),
                     "side": int(t["side"]), "net": float(t["net"]),
                     "outcome": t["outcome"], "stop_bp": stop_bp,
                     "rr": float(t.get("rr") or 0.0),
                     "r": float(t["net"]) / max(stop_bp, 1e-9)})
    return d.get("cell", {}), rows


def typical_move(bars, win):
    """Обычное |изменение| за окно у этого символа — медиана по неделе.

    Порог «тренда нет» обязан быть в единицах самого инструмента: 20
    б.п. за час у BTC это движение, у мелкого альта — стояние. Тот же
    приём, которым T1 чинил порог объёма, а S1 — пол волатильности.
    """
    ks = sorted(bars)
    vals = []
    for i in range(win, len(ks), max(1, win // 3)):
        a, b = bars[ks[i - win]][1], bars[ks[i]][1]
        if a > 0 and b > 0:
            vals.append(abs(b / a - 1.0) * 1e4)
    if not vals:
        return float("nan")
    vals.sort()
    return vals[len(vals) // 2]


def trend_at(bars, t, win, typ):
    """Знак и величина тренда ДО момента `t`. Только назад."""
    t0 = (t // 60) * 60
    a = bars.get(t0 - win * 60)
    b = bars.get(t0)
    if not a or not b or a[1] <= 0 or b[1] <= 0:
        return None
    move = (b[1] / a[1] - 1.0) * 1e4
    if not math.isfinite(typ) or typ <= 0:
        return None
    if abs(move) < typ:
        return 0, move / typ
    return (1 if move > 0 else -1), move / typ


def exp_se(rows, key):
    n = len(rows)
    if not n:
        return 0.0, 0.0
    v = [r[key] for r in rows]
    m = sum(v) / n
    var = sum((x - m) ** 2 for x in v) / max(1, n - 1)
    return m, math.sqrt(var / n)


def median(rows, key):
    v = sorted(r[key] for r in rows)
    return v[len(v) // 2] if v else float("nan")


def bucket_of(bars, r, win, typ):
    """Корзина сделки: по тренду, против, либо тренда нет."""
    got = trend_at(bars, r["t"], win, typ)
    if got is None:
        return None
    sign, _mag = got
    # Сторона сделки: в выгрузке side = сторона ПОГЛОЩАЮЩЕГО, поэтому
    # направление позиции это −side. Ошибиться здесь значит поменять
    # вывод на противоположный, поэтому пишется явно.
    pos = -r["side"]
    if sign == 0:
        return "тренда нет"
    return "по тренду" if sign == pos else "против тренда"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(OUT, "backtest.json"))
    a = ap.parse_args()

    cell, rows = load_trades(a.file)
    syms = sorted({r["sym"] for r in rows})
    lo = min(r["t"] for r in rows)
    hi = max(r["t"] for r in rows)
    d0 = datetime.fromtimestamp(lo, timezone.utc).date() - timedelta(days=1)
    d1 = datetime.fromtimestamp(hi, timezone.utc).date()
    days = [(d0 + timedelta(days=i)).isoformat()
            for i in range((d1 - d0).days + 1)]
    print(f"сделок {len(rows)}, символов {len(syms)}, суток {len(days)}")
    print("качаю минутные бары…", file=sys.stderr)
    bars = load_bars(syms, days)

    base, base_se = exp_se(rows, "net")
    print(f"ожидание как есть {base:+.2f} ± {base_se:.2f} б.п.\n")

    for win in WINDOWS:
        typ = {s: typical_move(bars[s], win) for s in syms}
        buckets = defaultdict(list)
        skipped = 0
        for r in rows:
            b = bucket_of(bars[r["sym"]], r, win, typ[r["sym"]])
            if b is None:
                skipped += 1
                continue
            r["bucket"] = b
            buckets[b].append(r)
        med_typ = sorted(v for v in typ.values() if math.isfinite(v))
        print(f"окно {win:>3} мин · обычный ход "
              f"{med_typ[len(med_typ)//2]:.0f} б.п. · без цены {skipped}")
        print(f"  {'корзина':16} {'сделок':>7} {'побед':>7} "
              f"{'ожидание':>14} {'в риске':>13} {'стоп':>7} {'цель':>7}")
        got = {}
        for name in ("по тренду", "против тренда", "тренда нет"):
            sel = buckets[name]
            if not sel:
                continue
            m, se = exp_se(sel, "net")
            rm, rse = exp_se(sel, "r")
            wins = sum(1 for x in sel if x["outcome"] == "цель") / len(sel)
            got[name] = (m, se, rm, rse)
            print(f"  {name:16} {len(sel):>7} {wins:>6.1%} "
                  f"{m:>+8.2f}±{se:<4.2f} {rm:>+7.2f}±{rse:<5.2f} "
                  f"{median(sel, 'stop_bp'):>6.1f} {median(sel, 'rr'):>6.2f}")
        if "по тренду" in got and "против тренда" in got:
            m1, s1, r1, q1 = got["по тренду"]
            m2, s2, r2, q2 = got["против тренда"]
            d, sd = m1 - m2, math.hypot(s1, s2)
            dr, sdr = r1 - r2, math.hypot(q1, q2)
            print(f"  разность «по» − «против»: {d:+.2f} ± {sd:.2f} б.п. "
                  f"({abs(d)/max(sd,1e-9):.1f} σ) · "
                  f"{dr:+.2f} ± {sdr:.2f} R ({abs(dr)/max(sdr,1e-9):.1f} σ)")
            # Устойчивость. Агрегат в две-три сигмы получен на выборке,
            # которую мы уже смотрели, и гипотеза родилась из графиков,
            # где исход был известен. Значит смотреть надо, повторяется
            # ли ЗНАК на независимых кусках, а не насколько велико одно
            # число. Ровно так замер повторного входа отделил настоящее
            # от совпадения.
            for key, title in ((lambda r: datetime.utcfromtimestamp(
                                    r["t"]).strftime("%m-%d"), "дням"),
                               (lambda r: r["sym"], "монетам")):
                same, both = 0, 0
                for k in sorted({key(r) for r in rows if "bucket" in r}):
                    sel = [r for r in rows if "bucket" in r and key(r) == k]
                    a = [r for r in sel if r["bucket"] == "по тренду"]
                    b = [r for r in sel if r["bucket"] == "против тренда"]
                    if len(a) < 10 or len(b) < 10:
                        continue
                    both += 1
                    same += exp_se(a, "net")[0] > exp_se(b, "net")[0]
                if both:
                    print(f"  по {title}: «по тренду» лучше в {same} "
                          f"из {both} кусков")
            # Что осталось бы, если против тренда просто не входить.
            # Отдельный вопрос от «есть ли разница»: отсев может быть
            # настоящим и при этом не выводить в плюс.
            keep = [r for r in rows
                    if r.get("bucket") and r["bucket"] != "против тренда"]
            m, se = exp_se(keep, "net")
            print(f"  если против тренда не входить: {len(keep)} сделок из "
                  f"{len(rows)}, ожидание {m:+.2f} ± {se:.2f} б.п.")
        for r in rows:
            r.pop("bucket", None)
        print()


if __name__ == "__main__":
    main()
