#!/usr/bin/env python3
"""
Z2 — скрин закономерностей по СОБСТВЕННОЙ записи стакана.

Z1 перебрал 62 условия по минутным барам и не нашёл ничего, что платит
против круга издержек. Это ответ про свечи. Здесь перебор идёт по
величинам, которых у свечей и принтов нет в принципе:

- **снятие заявок** — изменение глубины МИНУС то, что объяснено
  сделками. Четыре замера ленты (T1–T4) видели, сколько агрессии
  прошло через уровень, и не видели, подставляли ли уровень заново;
  это и есть недостающий знаменатель;
- **ход середины без единой сделки** — котировка ушла, потому что сняли
  заявки, а не потому что кто-то торговал;
- **выедено против показанного** — прошло ли через сторону больше, чем
  она показывала глубиной;
- **шторм обновлений**, растяжение лесенки, перекос глубины.

Машина суда — та же, что у Z1 (`research/z1_screen/screen.py`): те же
корзины, та же семейственная планка по Z, тот же вердикт с согласием
медианы и среднего. Второй копии ядра в проекте не заводят.

Три отличия от Z1, каждое вынужденное
-------------------------------------

1. **Контроль — СРЕДНЕЕ сечения, а не медиана.** Z1 намерил, что
   превышение над медианой несёт структурный снос (+10.7 б.п. на лонг
   за четыре часа): медиана робастна, но она не портфель, и
   хеджировать об неё нельзя. Равновзвешенная корзина такого сноса не
   имеет по построению — и это же служит встроенной проверкой: снос
   по стороне обязан выйти около нуля.
2. **Момент наблюдения — позднее из двух времён снимка.** Метку `t`
   сборщик ставит один раз на весь проход по символам, а проход
   занимает до 2.5 секунды; биржевая метка `ts` говорит, каким было
   состояние, когда его прочитали.
3. **Ширина записи печатается по датам.** Состав сборщика рос
   ступенями (25 → 518 → 559 → 725 имён), и у имени, добавленного
   вчера, нет ни собственной нормы, ни места в кросс-секции.

Запуск на VPS:
  cd ~/algoth_v2 && nice -n 19 .venv/bin/python research/z2_book/probe.py
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "z1_screen"))
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))

import bookfeat2 as B                                     # noqa: E402
import screen as Z                                        # noqa: E402
from store import read_hour                               # noqa: E402

BOOK = os.path.join(RESEARCH, "b1_book", "out", "book")
TRADES = os.path.join(RESEARCH, "b1_book", "out", "trades")
MIN_PER_DAY = 1440
HORIZONS = (1, 5, 15, 60)         # минуты
MIN_SNAPS = 30                    # снимков в минуте, иначе минута — пропуск
NORM_MIN_MIN = 600                # минут вчерашней истории для нормы


def log_(m):
    print(m, flush=True)


def symbols(root=BOOK):
    try:
        return sorted(d for d in os.listdir(root)
                      if os.path.isdir(os.path.join(root, d)))
    except OSError:
        return []


def hours_of_day(day):
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return [(d + timedelta(hours=h)).strftime("%Y-%m-%d-%H")
            for h in range(24)], int(d.timestamp())


def symbol_day(sym, day, log=log_):
    """Минутные признаки одного символа за сутки. Пропуск — это None."""
    hours, t0 = hours_of_day(day)
    snaps, trades = [], []
    for h in hours:
        try:
            snaps += read_hour(os.path.join(BOOK, sym), h,
                               parse=B.snap_line)
        except Exception:                                 # noqa: BLE001
            pass
        try:
            trades += read_hour(os.path.join(TRADES, sym), h,
                                parse=B.trade_line)
        except Exception:                                 # noqa: BLE001
            pass
    if not snaps:
        return None
    snaps.sort(key=lambda r: r[0])
    trades.sort(key=lambda r: r[0])
    return B.fold(snaps, trades, t0, MIN_PER_DAY)


FIELDS = ("mid_open", "spread", "depth_b", "depth_a", "imb", "reach",
          "upd", "path", "path_quiet", "buy", "sell", "trades",
          "snaps", "pull_bid", "pull_ask")


def day_matrices(syms, day, log=log_):
    """Матрицы «символ × минута» за сутки плюс ширина записи числом."""
    M = {f: np.full((len(syms), MIN_PER_DAY), np.nan, dtype=np.float32)
         for f in FIELDS}
    have = 0
    for r, sym in enumerate(syms):
        got = symbol_day(sym, day)
        if got is None:
            continue
        have += 1
        for f in FIELDS:
            v = got.get(f)
            if v is None:
                continue
            M[f][r] = [np.nan if x is None else x for x in v]
    # Минута с редкими снимками — не наблюдение: у неё и путь, и
    # медианы стоят на двух-трёх точках. Порог объявлен до прогона.
    thin = M["snaps"] < MIN_SNAPS
    for f in FIELDS:
        M[f][thin] = np.nan
    log(f"  {day}: имён с записью {have} из {len(syms)}, "
        f"годных символо-минут {int(np.isfinite(M['mid_open']).sum()):,}")
    return M, have


def norms(prev):
    """Собственные нормы символа по ВЧЕРАШНИМ суткам.

    Норма, посчитанная по тем же суткам, знала бы будущее внутри дня.
    Символ без вчерашней записи нормы не получает вовсе — и его минуты
    становятся пропуском, а не сырым значением (урок Z1: нормировка по
    всей выборке улучшает всё разом и потому невидима).
    """
    if prev is None:
        return None
    out = {}
    for f in ("spread", "depth_b", "depth_a", "reach", "upd", "path",
              "buy", "sell", "trades"):
        with np.errstate(invalid="ignore"):
            med = np.nanmedian(prev[f], axis=1)
        cnt = np.isfinite(prev[f]).sum(axis=1)
        med[cnt < NORM_MIN_MIN] = np.nan
        med[~np.isfinite(med) | (med <= 0)] = np.nan
        out[f] = med[:, None]
    return out


def primitives(M, N):
    """Признаки в собственных единицах символа. Нормы — вчерашние."""
    p = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        p["spread_rel"] = M["spread"] / N["spread"]
        p["depth_b_rel"] = M["depth_b"] / N["depth_b"]
        p["depth_a_rel"] = M["depth_a"] / N["depth_a"]
        p["reach_rel"] = M["reach"] / N["reach"]
        p["upd_rel"] = M["upd"] / N["upd"]
        p["path_rel"] = M["path"] / N["path"]
        p["trades_rel"] = M["trades"] / N["trades"]
        # Доля хода, сделанного БЕЗ единой сделки. Путь считается по
        # снимкам внутри минуты, поэтому величина существует только
        # там, где путь ненулевой; ноль пути — пропуск, а не «весь ход
        # сделками».
        p["quiet_share"] = np.where(M["path"] > 0,
                                    M["path_quiet"] / M["path"], np.nan)
        # Выедено против ПОКАЗАННОГО: через сторону прошло агрессии
        # больше, чем она показывала глубиной. Это тот знаменатель,
        # которого не было у четырёх замеров ленты.
        p["eat_bid_rel"] = M["sell"] / M["depth_b"]
        p["eat_ask_rel"] = M["buy"] / M["depth_a"]
        # Снятие заявок в долях показанной глубины. Плюс — ликвидность
        # ушла без сделок, минус — подставили больше, чем съели.
        p["pull_bid_rel"] = M["pull_bid"] / M["depth_b"]
        p["pull_ask_rel"] = M["pull_ask"] / M["depth_a"]
        p["imb"] = M["imb"]
    return p


def build_conditions():
    """Пространство объявляется ЦЕЛИКОМ здесь и после прогона не растёт."""
    C = []

    def add(name, side, fn, group):
        C.append({"name": name, "side": side, "fn": fn, "group": group})

    for s in (+1, -1):
        # Спред и его расширение.
        add("спред шире своей нормы втрое", s,
            lambda p: p["spread_rel"] >= 3, "спред")
        add("спред втрое шире при вялой торговле", s,
            lambda p: (p["spread_rel"] >= 3) & (p["trades_rel"] <= 0.2),
            "спред")
        # Глубина и её перекос.
        add("бид истончился вдвое", s,
            lambda p: p["depth_b_rel"] <= 0.5, "глубина")
        add("аск истончился вдвое", s,
            lambda p: p["depth_a_rel"] <= 0.5, "глубина")
        add("перекос глубины в биды", s,
            lambda p: p["imb"] >= 0.5, "глубина")
        add("перекос глубины в аски", s,
            lambda p: p["imb"] <= -0.5, "глубина")
        add("лесенка растянулась вдвое", s,
            lambda p: p["reach_rel"] >= 2, "глубина")
        # Снятие заявок — величина, которой нет ни в свечах, ни в ленте.
        add("сняли биды без сделок", s,
            lambda p: p["pull_bid_rel"] >= 1.0, "снятие")
        add("сняли аски без сделок", s,
            lambda p: p["pull_ask_rel"] >= 1.0, "снятие")
        add("биды подставляют быстрее, чем едят", s,
            lambda p: (p["pull_bid_rel"] <= -1.0)
            & (p["eat_bid_rel"] >= 0.5), "снятие")
        add("аски подставляют быстрее, чем едят", s,
            lambda p: (p["pull_ask_rel"] <= -1.0)
            & (p["eat_ask_rel"] >= 0.5), "снятие")
        # Выедено против показанного.
        add("через бид прошло больше, чем он показывал", s,
            lambda p: p["eat_bid_rel"] >= 1.0, "выедание")
        add("через аск прошло больше, чем он показывал", s,
            lambda p: p["eat_ask_rel"] >= 1.0, "выедание")
        add("бид выеден втрое сверх показанного", s,
            lambda p: p["eat_bid_rel"] >= 3.0, "выедание")
        add("аск выеден втрое сверх показанного", s,
            lambda p: p["eat_ask_rel"] >= 3.0, "выедание")
        # Ход котировкой и шторм обновлений.
        add("половина хода сделана без сделок", s,
            lambda p: (p["quiet_share"] >= 0.5) & (p["path_rel"] >= 2),
            "тихий ход")
        add("шторм обновлений впятеро", s,
            lambda p: p["upd_rel"] >= 5, "шторм")
    return C


CONDITIONS = build_conditions()
CONDS_BY_NAME = {}
for _c in CONDITIONS:
    CONDS_BY_NAME.setdefault(_c["name"], []).append(_c)


def collect_events(P, prim, times, log=log_):
    """События по всем условиям: имя триггера → (строки, колонки)."""
    ev = {}
    fin = np.isfinite(P)
    for c in CONDITIONS:
        if c["name"] in ev:
            continue                       # стороны делят один триггер
        try:
            hit = c["fn"](prim) & fin
        except KeyError:
            continue
        r, cc = Z.dedup_rows(hit, dedup_min=5)
        if len(r):
            ev[c["name"]] = (c, r, cc)
    log(f"  условий сработало {len(ev)}, событий "
        f"{sum(len(v[1]) for v in ev.values()):,}")
    return ev


def side_drift(cells):
    """Снос по стороне: при контроле СРЕДНИМ он обязан быть около нуля.

    Встроенная проверка меры, а не украшение. Z1 считал превышение над
    медианой сечения и получил снос +10.7 б.п. на любой лонг за четыре
    часа — величину, не зависящую от условия. Равновзвешенная корзина
    такого сноса не имеет по построению, и если он всё же появился,
    значит контроль считается не тем, чем задумано.
    """
    out = {}
    for h in HORIZONS:
        for side in (1, -1):
            v = [c["mean_bp"] for k, c in cells.items()
                 if k[1] == side and k[2] == h
                 and c["buckets"] >= Z.MIN_BUCKETS]
            if v:
                out[f"{h}|{side}"] = float(np.median(v))
    return out


def write_report(path, cells, null, drift, meta):
    L = []
    L.append("# Z2 — скрин по собственной записи стакана\n")
    L.append(f"Прогон {meta['when']} · {meta['days']} суток "
             f"({meta['first']}…{meta['last']}) · условий "
             f"{len(CONDITIONS)} · ячеек {len(cells)} · перестановок "
             f"{null['perms']}\n")
    L.append("\n**Что здесь меряется и почему этого нет в Z1.** Свечи "
             "показывают состоявшееся, лента — исполненное. Снятая "
             "заявка не оставляет следа ни там, ни там. Записанная "
             "книга даёт её прямо: изменение глубины МИНУС то, что "
             "объяснено сделками, и есть добавление или снятие "
             "ликвидности. Четыре замера ленты (T1–T4) видели, сколько "
             "агрессии прошло через уровень, и не видели, подставляли "
             "ли уровень заново, — это и был недостающий знаменатель.\n")
    L.append("\n**Контроль — СРЕДНЕЕ сечения, а не медиана.** Z1 "
             "намерил, что превышение над медианой несёт структурный "
             "снос (+10.7 б.п. на любой лонг за четыре часа): медиана "
             "робастна, но она статистика, а не портфель. "
             "Равновзвешенная корзина такого сноса не имеет по "
             "построению.\n")
    L.append("\n### Проверка меры: снос по стороне обязан быть около нуля\n\n")
    L.append("| горизонт | лонги | шорты |\n|---|--:|--:|\n")
    for h in HORIZONS:
        a = drift.get(f"{h}|1")
        b = drift.get(f"{h}|-1")
        L.append(f"| {h} мин | {'—' if a is None else f'{a:+.2f}'} | "
                 f"{'—' if b is None else f'{b:+.2f}'} |\n")
    L.append("\nЕсли эти числа заметно отличны от нуля, читать таблицу "
             "ниже нельзя: контроль считается не тем, чем задумано.\n")
    L.append(f"\n- планка по Z (95-й процентиль максимума среди "
             f"{null['cells_in_bar']} годных ячеек): "
             f"**{null['bar_z']:+.2f} σ**, средний максимум "
             f"{null['mean_z']:+.2f};\n")
    L.append(f"- издержка вердикта — {Z.NEUTRAL_COST_BP:.0f} б.п. "
             "(нейтральная книга: нога плюс хедж);\n")
    L.append(f"- ячейка идёт в находки при корзинах ≥ {Z.MIN_BUCKETS};\n")
    L.append(f"- минута с числом снимков меньше {MIN_SNAPS} — пропуск, "
             "а не наблюдение.\n")
    L.append("\n## Все ячейки, по Z\n")
    L.append("| условие | стор | гор | событий | покр | корзин | медиана | "
             "СРЕДНЕЕ | сырая медиана | z | β-утечка | побед | сечение | "
             "доля | вердикт |\n")
    L.append("|---|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--|\n")
    best = sorted(cells.items(),
                  key=lambda kv: -(kv[1].get("z") if
                                   np.isfinite(kv[1].get("z", np.nan))
                                   else -9e9))
    for (name, side, h), c in best:
        L.append(f"| {name} | {'L' if side > 0 else 'S'} | {h} | "
                 f"{c['events']} | {c['coverage']:.2f} | {c['buckets']} | "
                 f"{c['med_bp']:+.1f} | {c['mean_bp']:+.1f} | "
                 f"{c['raw_med_bp']:+.1f} | "
                 f"{c.get('z', float('nan')):+.1f} | "
                 f"{c['beta_leak']:+.2f} | {c['win']:.2f} | "
                 f"{c['cross']:.0f} | {c['share']:.3f} | "
                 f"{Z.verdict_of(c, null)} |\n")
    L.append("\n**«короткая волатильность»** в вердикте означает: "
             "медиана выше круга издержек, а СРЕДНЕЕ ниже. Такая ячейка "
             "выигрывает часто и по мелочи, а отдаёт разом — форма, "
             "убившая гипотезы 3 и 4.\n")
    L.append("\n## Ширина записи по суткам\n\n")
    L.append("| сутки | имён с записью | годных символо-минут |\n"
             "|---|--:|--:|\n")
    for d, n, mins in meta["width"]:
        L.append(f"| {d} | {n} | {mins:,} |\n")
    L.append("\nСостав сборщика рос ступенями (25 → 518 → 559 → 725 "
             "имён), и у имени, добавленного вчера, нет ни собственной "
             "нормы, ни места в кросс-секции. Числа выше говорят, на "
             "какой ширине на самом деле считалась каждая дата.\n")
    L.append("\n## Чего этот скрин НЕ говорит\n")
    L.append("- Он не проверяет стратегию: у ячейки нет ни стопа, ни "
             "цели, ни размера, ни конкуренции за слоты.\n")
    L.append("- Снятие считается по ПОЛОСЕ ±0.25 %, привязанной к "
             "середине, а середина движется: часть «снятия» на резком "
             "ходе есть смещение полосы, а не уход заявок. Честная "
             "версия требует разбора лесенки по ценам уровней и стоит "
             "на порядок дороже — это следующий шаг, а не оговорка.\n")
    L.append("- Запись коротка (недели), режим рынка один.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))


def days_between(start, end):
    a = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    b = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out = []
    while a <= b:
        out.append(a.strftime("%Y-%m-%d"))
        a += timedelta(days=1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="скрин по записи стакана")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    syms = [s for s in args.symbols.split(",") if s] or symbols()
    if not syms:
        log_(f"в {BOOK} нет записи — считать нечего")
        return 1
    have_days = sorted({f.split(".")[0][:10]
                        for s in syms[:50]
                        for f in os.listdir(os.path.join(BOOK, s))
                        if f[:2] == "20"})
    days = days_between(args.start or have_days[0],
                        args.end or have_days[-1])
    log_(f"символов {len(syms)}, суток {len(days)} "
         f"({days[0]}…{days[-1]})")
    acc, rng = {}, np.random.default_rng(Z.SEED)
    prev, width = None, []
    for day in days:
        M, have = day_matrices(syms, day)
        mins = int(np.isfinite(M["mid_open"]).sum())
        width.append((day, have, mins))
        N = norms(prev)
        if N is None:
            log_(f"  {day}: нет вчерашних норм — сутки идут только в "
                 "историю")
            prev = M
            continue
        prim = primitives(M, N)
        times = np.arange(len(M["mid_open"][0]), dtype=np.int64) * 60 \
            + int(datetime.strptime(day, "%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp())
        ev = collect_events(M["mid_open"], prim, times)
        Z.measure(ev, M["mid_open"], times, acc, rng,
                  conds_by_name=CONDS_BY_NAME, control="mean")
        prev = M
    if not acc:
        log_("ни одного события — считать нечего")
        return 1
    log_("считаю сводку и семейственную планку…")
    cells, null = Z.summarize(acc)
    drift = side_drift(cells)
    path = os.path.join(OUT, f"Z2-book-{args.tag}.md")
    write_report(path, cells, null, drift,
                 {"when": datetime.now(timezone.utc)
                  .strftime("%Y-%m-%d %H:%M UTC"),
                  "days": len(days), "first": days[0], "last": days[-1],
                  "width": width})
    with open(os.path.join(OUT, f"z2-{args.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": {f"{k[0]}|{k[1]}|{k[2]}": v
                             for k, v in cells.items()},
                   "null": null, "drift": drift, "width": width,
                   "conds": len(CONDITIONS)}, f, ensure_ascii=False)
    over = [k for k, c in cells.items()
            if Z.verdict_of(c, null) == "**кандидат**"]
    log_(f"отчёт: {path}")
    log_(f"ячеек измерено: {len(cells)}; планка {null['bar_z']:+.2f} σ; "
         f"кандидатов: {len(over)}")
    for k in sorted(over, key=lambda x: -cells[x]["z"])[:10]:
        c = cells[k]
        log_(f"  {k[0]} [{'L' if k[1] > 0 else 'S'}] {k[2]}м: "
             f"медиана {c['med_bp']:+.1f}, среднее {c['mean_bp']:+.1f} "
             f"б.п., z {c['z']:+.1f}, корзин {c['buckets']}")
    log_("снос по стороне (обязан быть около нуля): "
         + ", ".join(f"{k}: {v:+.2f}" for k, v in sorted(drift.items())))
    if not args.no_publish:
        Z.publish("Z2: скрин по собственной записи стакана")
    return 0


if __name__ == "__main__":
    sys.exit(main())
