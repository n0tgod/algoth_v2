#!/usr/bin/env python3
"""
L1 — как каскад ликвидаций выглядит в данных, и есть ли после него отскок.

**Зонд, а не гипотеза.** Ни порогов-критериев, ни объявленной сетки, ни
вердикта. Задача — увидеть событие числами прежде, чем писать спеку, и
ответить на три вопроса:

1. **Как выглядит подпись.** Каскад — это принудительные закрытия:
   позиции не переоткрываются, они исчезают. Значит открытый интерес
   падает **одновременно** с движением цены. Обычное движение цены при
   растущем или неизменном интересе — это не каскад, а приток денег.
2. **Сколько их.** Наш стенд четыре раза упирался в то, что 133
   независимых периода не позволяют предъявить ничего слабее Sharpe 1.5.
   Событийная конструкция считается по событиям, и если их тысячи —
   доказуемый эффект становится втрое меньше.
3. **Есть ли отскок и какой.** Вынужденный продавец продаёт по любой
   цене; если после того, как он закончился, цена возвращается — это и
   есть предмет гипотезы.

Почему открытый интерес, а не лента
-----------------------------------

Прямой выкладки принудительных закрытий нет ни у Binance, ни у Bybit
(инвентаризация L0), а признака ликвидации нет и в ленте. Событие
пришлось бы выводить из подписи в тиках — но лента весит 43.6 ГБ на
один BTCUSDT, то есть по универсуму это терабайты.

Открытый интерес даёт ту же подпись напрямую и стоит **0.02 ГБ на
символ за шесть лет**: набор `metrics` архива Binance, шаг 5 минут, с
сентября 2020. Падение интереса и есть исчезновение позиций.

Пороги обнаружения здесь — **параметры обзора, а не критерии**.
Докладывается несколько значений сразу, чтобы видеть форму зависимости,
а не одно число, которое захочется подогнать.

Момент решения — не метка строки
--------------------------------

Первая версия зонда решала и входила по метке `t`. Проверка `lag.py`
показала, что так нельзя, причём дважды:

- **строка `metrics` с меткой `t` описывает интервал `[t, t+5)` и
  завершена только в `t+5`.** Отношение объёмов из строки совпадает с
  пересчётом по свечам за интервал ПОСЛЕ метки (отклонение 0.0003
  против 0.4 у интервала до), а снимок интереса стоит на конце
  интервала: связь изменения интереса с объёмом даёт острый пик на
  сдвиге +1 во всех проверенных символо-месяцах;
- **цена бралась с бара, который на метке ещё не закрылся.** Правило
  «последний бар, открытый не позже метки» при точном совпадении сеток
  даёт бар `[t, t+1)`, а его закрытие наступает в `t+1`. Расхождение с
  закрытым баром — медиана 4–7 б.п., 95-й процентиль 15–29 б.п., и в
  каскаде оно систематическое, а не случайное.

Поэтому решение принимается в `t + LAG_MIN`, а цена входа берётся с
последнего бара, **закрытого** к этому моменту. Старое поведение
достижимо ключами `--lag-min 0 --price-rule open` — не ради выбора, а
чтобы измерить, сколько эффекта создавалось заглядыванием.

    python3 probe.py
"""

import argparse
import csv
import io
import json
import os
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")

sys.path.insert(0, RESEARCH)
from common.venue import fetch_binary                      # noqa: E402

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
UA = "l1-cascade-probe/1.0"
WORKERS = 8

# Выборка: мажоры, средние и мелкие. Каскады у них разной силы, и
# средним по BTC судить обо всех нельзя.
SAMPLE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
          "AVAXUSDT", "LINKUSDT", "ARBUSDT", "APTUSDT", "SUIUSDT",
          "INJUSDT", "SEIUSDT")
START = "2024-01-01"
END = "2026-06-30"

STEP_MIN = 5                      # шаг набора metrics
LAG_MIN = 5                       # строка с меткой t завершена в t+5 (lag.py)
WINDOW_MIN = 15                   # окно, за которое меряется падение
OI_DROPS = (0.01, 0.02, 0.03)     # параметры обзора, не критерии
MOVES = (0.01, 0.02, 0.03)
FORWARD_MIN = (5, 15, 60, 240, 1440)


def months(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    out, cur = [], date(a.year, a.month, 1)
    while cur <= b:
        out.append(f"{cur.year:04d}-{cur.month:02d}")
        cur = date(cur.year + (cur.month == 12),
                   cur.month % 12 + 1, 1)
    return out


def days(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += timedelta(days=1)
    return out


def read_zip_csv(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        with z.open(z.namelist()[0]) as f:
            return list(csv.reader(io.TextIOWrapper(f, "utf-8")))


def load_metrics(sym, start, end):
    """Открытый интерес по 5-минутной сетке. `metrics` бывает только суточным."""
    def one(day):
        key = (f"data/futures/um/daily/metrics/{sym}/"
               f"{sym}-metrics-{day}.zip")
        try:
            raw = fetch_binary(f"{S3}/{key}", CACHE,
                               cache_key=f"m_{sym}_{day}", user_agent=UA)
        except Exception:
            return []
        rows = read_zip_csv(raw)
        if not rows:
            return []
        head = [c.strip() for c in rows[0]]
        try:
            it, io_ = head.index("create_time"), head.index("sum_open_interest")
        except ValueError:
            return []
        out = []
        for r in rows[1:]:
            if len(r) <= max(it, io_):
                continue
            try:
                # Метка — UTC. Без явной зоны берётся локальная, и на
                # машине не в UTC сетка молча съезжает на часы.
                t = datetime.fromisoformat(r[it].strip()).replace(
                    tzinfo=timezone.utc).timestamp()
                out.append((t, float(r[io_])))
            except ValueError:
                continue
        return out

    got = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for part in ex.map(one, days(start, end)):
            got += part
    got.sort()
    if not got:
        return None
    t = np.array([x[0] for x in got], dtype=np.float64)
    v = np.array([x[1] for x in got], dtype=np.float64)
    return t, v


def load_price(sym, start, end):
    """Минутные закрытия из месячных архивов."""
    def one(mon):
        key = (f"data/futures/um/monthly/klines/{sym}/1m/"
               f"{sym}-1m-{mon}.zip")
        try:
            raw = fetch_binary(f"{S3}/{key}", CACHE,
                               cache_key=f"k_{sym}_{mon}", user_agent=UA)
        except Exception:
            return []
        out = []
        for r in read_zip_csv(raw):
            if not r or not r[0].strip().lstrip("-").isdigit():
                continue          # заголовок появился в файлах 2025 года
            try:
                out.append((int(r[0]) / 1000.0, float(r[4])))
            except (ValueError, IndexError):
                continue
        return out

    got = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for part in ex.map(one, months(start, end)):
            got += part
    got.sort()
    if not got:
        return None
    t = np.array([x[0] for x in got], dtype=np.float64)
    v = np.array([x[1] for x in got], dtype=np.float64)
    return t, v


def align(mt, pt, pv, lag_min=LAG_MIN, rule="closed"):
    """Цена в момент решения — по бару, ЗАКРЫТОМУ к этому моменту.

    Момент решения = метка строки + `lag_min`: раньше строки просто нет
    (см. шапку и `lag.py`). Правило `closed` берёт последний бар, чьё
    закрытие уже наступило; `open` воспроизводит первую версию зонда,
    бравшую бар, который в этот момент ещё торгуется.
    """
    at = mt + lag_min * 60
    side = "left" if rule == "closed" else "right"
    idx = np.searchsorted(pt, at, side) - 1
    clip = np.clip(idx, 0, len(pt) - 1)
    # Допуск считается от закрытия бара, а не от его открытия: у бара
    # `[at-60, at)` открытие отстоит на минуту по построению.
    close_t = pt[clip] + 60.0
    ok = (idx >= 0) & (np.abs(close_t - at) <= 120)
    return np.where(ok, pv[clip], np.nan), at


def scan(sym, oi_t, oi_v, price, oi_drop, move):
    """События: интерес упал И цена сдвинулась за одно окно."""
    w = WINDOW_MIN // STEP_MIN
    if len(oi_v) < w + 2:
        return []
    d_oi = np.full(len(oi_v), np.nan)
    d_px = np.full(len(oi_v), np.nan)
    d_oi[w:] = oi_v[w:] / np.maximum(oi_v[:-w], 1e-12) - 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        d_px[w:] = price[w:] / price[:-w] - 1.0

    hit = np.isfinite(d_oi) & np.isfinite(d_px) & \
        (d_oi <= -oi_drop) & (np.abs(d_px) >= move)
    events, last = [], -10**9
    for i in np.flatnonzero(hit):
        if oi_t[i] - last < 3600:        # одно событие, а не серия баров
            continue
        last = oi_t[i]
        fwd = {}
        for f in FORWARD_MIN:
            j = int(np.searchsorted(oi_t, oi_t[i] + f * 60))
            if j < len(price) and np.isfinite(price[j]) and \
                    np.isfinite(price[i]) and price[i] > 0:
                fwd[f] = price[j] / price[i] - 1.0
        events.append({"symbol": sym, "t": float(oi_t[i]),
                       "oi_change": float(d_oi[i]),
                       "price_change": float(d_px[i]),
                       "down": bool(d_px[i] < 0), "fwd": fwd})
    return events


def episodes(events, gap_sec=4 * 3600):
    """События, слипшиеся в эпизоды по всем символам сразу.

    Каскады не независимы: обвал накрывает весь рынок, и двенадцать
    событий на двенадцати активах в один час — это одно наблюдение, а
    не двенадцать. Фаза A четыре раза упиралась в то, что бюджетом
    доказательства служит число НЕЗАВИСИМЫХ наблюдений; считать его
    надо здесь, а не после того, как построена стратегия.
    """
    if not events:
        return []
    order = sorted(events, key=lambda e: e["t"])
    groups, cur = [], [order[0]]
    for e in order[1:]:
        if e["t"] - cur[-1]["t"] <= gap_sec:
            cur.append(e)
        else:
            groups.append(cur)
            cur = [e]
    groups.append(cur)
    return groups


def by_episode(events, f):
    """Медиана внутри эпизода, потом по эпизодам. Одно окно — один голос."""
    vals = []
    for g in episodes(events):
        inner = [e["fwd"][f] for e in g if f in e["fwd"]]
        if inner:
            vals.append(float(np.median(inner)))
    return vals


def baseline(series, rng_seed=7):
    """Безусловная доходность на тех же активах и том же периоде.

    Без неё замер бессмыслен. Если рынок за выборку рос, положительный
    форвард после события ничего не говорит о событии — он говорит о
    периоде. Подпись «обе стороны положительны» именно на это и
    указывает, и проверять её надо, а не объяснять.

    Берутся случайные моменты той же сетки, по тысяче на актив: полный
    перебор дал бы то же самое дороже.
    """
    rng = np.random.default_rng(rng_seed)
    out = {f: [] for f in FORWARD_MIN}
    for sym, (t, v, px) in series.items():
        n = len(t)
        if n < 1000:
            continue
        for i in rng.choice(n - 1, size=min(1000, n - 1), replace=False):
            if not np.isfinite(px[i]) or px[i] <= 0:
                continue
            for f in FORWARD_MIN:
                j = int(np.searchsorted(t, t[i] + f * 60))
                if j < n and np.isfinite(px[j]):
                    out[f].append(px[j] / px[i] - 1.0)
    return {f: (float(np.median(v)) if len(v) >= 100 else None)
            for f, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--symbols", default=",".join(SAMPLE))
    ap.add_argument("--lag-min", type=int, default=LAG_MIN,
                    help="задержка появления строки metrics, минуты")
    ap.add_argument("--price-rule", choices=("closed", "open"),
                    default="closed",
                    help="closed — бар закрыт к моменту решения; "
                         "open — первая версия зонда")
    ap.add_argument("--tag", default="",
                    help="суффикс имени артефакта, чтобы прогоны не затирались")
    a = ap.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    os.makedirs(OUT, exist_ok=True)

    series = {}
    for sym in syms:
        m = load_metrics(sym, a.start, a.end)
        p = load_price(sym, a.start, a.end)
        if not m or not p:
            print(f"{sym}: данных нет", file=sys.stderr, flush=True)
            continue
        price, _ = align(m[0], p[0], p[1], a.lag_min, a.price_rule)
        series[sym] = (m[0], m[1], price)
        print(f"{sym}: точек интереса {len(m[0])}, цена сошлась у "
              f"{np.isfinite(price).mean():.1%}", file=sys.stderr, flush=True)
    if not series:
        raise SystemExit("ничего не загрузилось")

    print(f"\nмомент решения = метка + {a.lag_min} мин, цена по правилу "
          f"'{a.price_rule}'", file=sys.stderr, flush=True)

    base = baseline(series)
    print("\nБЕЗУСЛОВНАЯ доходность на тех же активах и периоде "
          "(медиана по случайным моментам):")
    print("  " + "  ".join(f"{f} мин: {base[f] * 100:+.3f}%"
                           if base[f] is not None else f"{f} мин: —"
                           for f in FORWARD_MIN))
    print("  всё, что ниже, надо читать ПРОТИВ этих чисел\n")

    grid = []
    for oi_drop in OI_DROPS:
        for move in MOVES:
            ev = []
            for sym, (t, v, px) in series.items():
                ev += scan(sym, t, v, px, oi_drop, move)
            if not ev:
                continue
            down_ev = [e for e in ev if e["down"]]
            eps = episodes(down_ev)
            row = {"oi_drop": oi_drop, "move": move, "events": len(ev),
                   "down": len(down_ev), "episodes": len(eps),
                   "top_episode_share": (max(len(g) for g in eps) / len(down_ev)
                                         if eps else None)}
            for side, sel in (("down", down_ev),
                              ("up", [e for e in ev if not e["down"]])):
                for f in FORWARD_MIN:
                    vals = [e["fwd"][f] for e in sel if f in e["fwd"]]
                    if len(vals) >= 20:
                        row[f"{side}_{f}"] = float(np.median(vals))
                        row[f"{side}_{f}_n"] = len(vals)
            # То же по эпизодам: одно рыночное окно даёт один голос.
            for f in FORWARD_MIN:
                ep = by_episode(down_ev, f)
                if len(ep) >= 10:
                    row[f"ep_{f}"] = float(np.median(ep))
                    row[f"ep_{f}_n"] = len(ep)
                    row[f"ep_{f}_pos"] = float(np.mean(np.array(ep) > 0))
            grid.append(row)

    dst = os.path.join(OUT, f"l1_probe{a.tag}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"config": {"symbols": syms, "start": a.start,
                              "end": a.end, "window_min": WINDOW_MIN,
                              "lag_min": a.lag_min,
                              "price_rule": a.price_rule,
                              "oi_drops": list(OI_DROPS),
                              "moves": list(MOVES),
                              "forward_min": list(FORWARD_MIN)},
                   "baseline": {str(k): v for k, v in base.items()},
                   "grid": grid}, f, ensure_ascii=False, indent=1)

    print("\nСКОЛЬКО СОБЫТИЙ (падение интереса И движение цены за 15 мин)")
    print("эпизод — события всех активов, слипшиеся в окно 4 часа\n")
    print(f"{'падение OI':>12}{'движение':>11}{'событий':>10}{'вниз':>8}"
          f"{'эпизодов':>11}{'крупнейший':>13}")
    for r in grid:
        top = (f"{r['top_episode_share']:.0%}"
               if r.get("top_episode_share") is not None else "—")
        print(f"{r['oi_drop']:>11.0%}{r['move']:>11.0%}"
              f"{r['events']:>10}{r['down']:>8}"
              f"{r.get('episodes', 0):>11}{top:>13}")

    print("\nЧТО БЫЛО ПОСЛЕ — ПРЕВЫШЕНИЕ над безусловной доходностью")
    print("каскад ВНИЗ: положительное = отскок сверх обычного сноса\n")
    hdr = "".join(f"{str(f) + ' мин':>11}" for f in FORWARD_MIN)
    print(f"{'падение OI':>11}{'движение':>10}{hdr}")
    for r in grid:
        cells = "".join(
            f"{(r[f'down_{f}'] - (base[f] or 0)) * 100:>10.2f}%"
            if f"down_{f}" in r else f"{'—':>11}" for f in FORWARD_MIN)
        print(f"{r['oi_drop']:>10.0%}{r['move']:>10.0%}{cells}")
    print("\nкаскад ВВЕРХ: отрицательное = откат вниз сверх обычного\n")
    print(f"{'падение OI':>11}{'движение':>10}{hdr}")
    for r in grid:
        cells = "".join(
            f"{(r[f'up_{f}'] - (base[f] or 0)) * 100:>10.2f}%"
            if f"up_{f}" in r else f"{'—':>11}" for f in FORWARD_MIN)
        print(f"{r['oi_drop']:>10.0%}{r['move']:>10.0%}{cells}")

    print("\nТО ЖЕ ПО ЭПИЗОДАМ — одно рыночное окно даёт один голос")
    print("в скобках доля эпизодов, где отскок положителен\n")
    print(f"{'падение OI':>11}{'движение':>10}{'эпизодов':>10}{hdr}")
    for r in grid:
        cells = "".join(
            f"{(r[f'ep_{f}'] - (base[f] or 0)) * 100:>7.2f}%"
            f"{r[f'ep_{f}_pos']:>4.0%}" if f"ep_{f}" in r else f"{'—':>11}"
            for f in FORWARD_MIN)
        print(f"{r['oi_drop']:>10.0%}{r['move']:>10.0%}"
              f"{r.get('ep_' + str(FORWARD_MIN[0]) + '_n', 0):>10}{cells}")
    print(f"\nзаписано {dst}")


if __name__ == "__main__":
    main()
