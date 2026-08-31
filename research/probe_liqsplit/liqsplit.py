#!/usr/bin/env python3
"""Живые принты ликвидаций как условие отскока: падения D1 С
принудительными закрытиями против падений БЕЗ них.

Гипотеза 5 умерла на ПРОКСИ: открытый интерес Binance с шагом 5 минут,
и контроль 2 показал «условие вычитает». У сборщика с 2026-08 пишется
поток `allLiquidation` площадки исполнения — секундные принты
принудительных закрытий, которых нет ни в одном архиве (L0). Вопрос
один, и он ровно контроль 2 наоборот: ДОБАВЛЯЕТ ли условие «в окне
падения были ликвидации» к голому падению по середине.

Чем это может кончиться, названо до прогона
-------------------------------------------
- Смерть 1 (ожидаемая, урок L3): группы не различаются — механизм
  принудительного закрытия украшение, гипотеза сводится к «покупай
  падение», уже закрытому экономикой D1 (нетто +8.8 б.п. при нужных
  34.8).
- Смерть 2: градиент по нотионалу ликвидаций плоский или обратный —
  довод, закрывший уровневый зонд T2.
- Единственный интересный исход — КОНЦЕНТРАЦИЯ: если превышение
  группы «с ликвидациями» существенно крупнее общего (+26 б.п.),
  меньшее число событий с большей величиной может перебить тот же
  круг издержек 17.4 × 2 ≈ 35 б.п. валовых ≈ 52 б.п.

Конструкция — дословно `tape_check`: та же ячейка вердикта спеки 11
(падение 3 % за 15 мин, задержка 5 с, горизонт 30 мин), тот же
`D.excess` с одновременной кросс-секцией, те же эпизоды. Меняется
ровно признак группы: принты `liq` того же имени в ОКНЕ ОБНАРУЖЕНИЯ
[t−15 мин, t].

Ноль ликвидаций — законное наблюдение, а не пропуск: ликвидации
редки, и час без единого принта у живого сборщика — норма. Отказ,
неотличимый от тишины, ловится на уровне СУТОК: если за сутки нет ни
одного liq-файла ни у одного имени при живой записи книги, молчит
подписка, а не рынок — такие сутки исключаются и считаются числом.

    setsid nohup .venv/bin/python research/probe_liqsplit/liqsplit.py \
        > research/probe_liqsplit/out/run.log 2>&1 &
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
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))

import detect as D                                        # noqa: E402
import run_d1 as R                                        # noqa: E402
from store import read_hour                               # noqa: E402

for _mod, _want in ((D, "d1_seconds"), (R, "d1_seconds")):
    _got = os.path.basename(os.path.dirname(os.path.abspath(_mod.__file__)))
    assert _got == _want, f"чужой модуль: {_mod.__name__} из {_got}"

# --- объявлено до прогона ---------------------------------------------
GROUPS = ("с ликвидациями", "без ликвидаций")
COST_ROUND_BP = 17.4      # круг D1: комиссия 11 + измеренный спред
NEED_GROSS_BP = 2 * COST_ROUND_BP


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def liq_line(line):
    """Принт ликвидации: (секунда, нотионал $, сторона Buy=1).

    Что означает `side`, решили ДАННЫЕ, а не документация: моё чтение
    «ликвидация лонга исполняется как Sell» опровергнуто первым же
    прогоном — в падениях на 3 % доля Sell всего 0.34, то есть на
    этом потоке ликвидацию ЛОНГА маркирует `Buy`. В меру сторона не
    входит (группируют принты любой стороны), доля печатается
    диагностикой."""
    r = json.loads(line)
    return (r["ts"] / 1000.0, float(r["p"]) * float(r["v"]),
            1 if r.get("side") == "Buy" else 0)


def liq_of_day(root, sym, hours):
    """Все принты `liq` имени за сутки, отсортированные по времени."""
    d = os.path.join(root, "liq", sym)
    ts, usd, buy = [], [], []
    for h in hours:
        for t, u, b in read_hour(d, h, parse=liq_line):
            ts.append(t)
            usd.append(u)
            buy.append(b)
    o = np.argsort(ts, kind="stable") if ts else []
    return (np.asarray(ts, dtype=np.float64)[o],
            np.asarray(usd, dtype=np.float64)[o],
            np.asarray(buy, dtype=np.int8)[o])


def liq_day_alive(root, day):
    """Есть ли за сутки хоть один liq-файл хоть у одного имени."""
    base = os.path.join(root, "liq")
    try:
        names = os.listdir(base)
    except OSError:
        return False
    for s in names:
        try:
            if any(fn.startswith(day) for fn in
                   os.listdir(os.path.join(base, s))):
                return True
        except OSError:
            continue
    return False


def check_day(root, syms, day, jobs, log=print):
    """События суток ячейки вердикта с принтами ликвидаций окна."""
    P, t0, n = R.load_day(os.path.join(root, "book"), syms, day, jobs,
                          log)
    drop = D.VERDICT_CELL["drop"]
    delay = D.VERDICT_CELL["delay_sec"]
    hor = D.VERDICT_CELL["horizon_sec"]
    NXT = R.next_index(P)
    rows, cols = R.events_of_day(P, t0, drop, {}, R.PAD_SEC,
                                 R.PAD_SEC + R.DAY_SEC)
    log(f"    событий {len(rows)}")
    if len(rows) == 0:
        return []
    ban = D.guard_matrix(P.shape, rows, cols, D.guard_sec(delay, hor))
    hours = R.hours_of(t0, n)
    out = []
    by_sym = {}
    for r, j in zip(rows, cols):
        by_sym.setdefault(int(r), []).append(int(j))
    for k, (r, js) in enumerate(sorted(by_sym.items())):
        sym = syms[r]
        lt, lu, lb = liq_of_day(root, sym, hours)
        for j in js:
            own, bg, exc, width = D.excess(P, NXT, r, j, delay, hor,
                                           ban[:, j])
            a = float(t0 + j - D.W_SEC)
            b = float(t0 + j)
            lo = int(np.searchsorted(lt, a, side="left"))
            hi = int(np.searchsorted(lt, b, side="right"))
            out.append({
                "sym": sym, "t": t0 + j, "excess": exc, "own": own,
                "bg": bg, "width": width,
                "n_liq": hi - lo,
                "liq_usd": float(lu[lo:hi].sum()),
                "liq_buy": int(lb[lo:hi].sum())})
        if (k + 1) % 25 == 0:
            log(f"    просмотрено {k + 1}/{len(by_sym)} имён")
    del P, NXT, ban
    return out


def group_of(e):
    return GROUPS[0] if e["n_liq"] >= 1 else GROUPS[1]


def _med(v):
    v = [x for x in v if x is not None and np.isfinite(x)]
    return float(np.median(v)) if v else None


def _agg(sub):
    rec = {"events": len(sub), "episodes": 0, "excess_bp": None,
           "share_pos": None, "own_bp": None, "bg_bp": None,
           "liq_usd_med": _med([e["liq_usd"] for e in sub
                                if e["n_liq"] > 0]),
           "n_liq_med": _med([e["n_liq"] for e in sub])}
    exc = np.array([e["excess"] for e in sub], dtype=np.float64)
    ok = np.isfinite(exc)
    if ok.any():
        t = np.array([e["t"] for e in sub], dtype=np.float64)[ok]
        ep = D.episodes(t)
        v = D.by_episode(exc[ok], ep)
        rec.update({
            "episodes": int(len(v)),
            "excess_bp": round(float(np.median(v)) * 1e4, 2),
            "share_pos": round(float(np.mean(v > 0)), 3),
            "own_bp": round((_med([e["own"] for e in sub]) or 0) * 1e4,
                            2),
            "bg_bp": round((_med([e["bg"] for e in sub]) or 0) * 1e4,
                           2)})
    return rec


def summarise(rows):
    out = {g: _agg([e for e in rows if group_of(e) == g])
           for g in GROUPS}
    # Градиент по нотионалу — терцили СРЕДИ событий с ликвидациями,
    # объявлены здесь: если механизм — принудительное закрытие,
    # превышение обязано расти с размером снесённого.
    liq = [e for e in rows if e["n_liq"] >= 1]
    grad = []
    if len(liq) >= 30:
        usd = np.array([e["liq_usd"] for e in liq])
        q1, q2 = np.quantile(usd, [1 / 3, 2 / 3])
        for name, sel in (("нижняя треть $", usd <= q1),
                          ("середина", (usd > q1) & (usd < q2)),
                          ("верхняя треть $", usd >= q2)):
            grad.append((name,
                         _agg([e for e, s in zip(liq, sel) if s])))
    out["_gradient"] = grad
    # Сторона — диагностика: падение ликвидирует ЛОНГОВ (Sell).
    tot = sum(e["n_liq"] for e in liq)
    out["_sell_share"] = (round(1 - sum(e["liq_buy"] for e in liq)
                                / tot, 3) if tot else None)
    return out


def reading(g):
    a, b = g[GROUPS[0]], g[GROUPS[1]]
    if not a["episodes"] or not b["episodes"]:
        return ("Одна из групп пуста — деление не измерено, вердикта "
                "нет.")
    if a["excess_bp"] is None or b["excess_bp"] is None:
        return "Превышение не измерено — вердикта нет."
    if a["excess_bp"] <= b["excess_bp"]:
        return ("Условие на ликвидации НЕ добавляет к голому падению — "
                "та же смерть, что контроль 2 в L3: механизм "
                "принудительного закрытия украшение, а «покупай "
                "падение» уже закрыто экономикой D1.")
    if a["excess_bp"] >= NEED_GROSS_BP:
        return (f"Группа с ликвидациями даёт {a['excess_bp']:+.1f} "
                f"б.п. — выше валового порога {NEED_GROSS_BP:.0f}: "
                "повод считать спеку, не вывод.")
    return (f"Группа с ликвидациями выше голого падения "
            f"({a['excess_bp']:+.1f} против {b['excess_bp']:+.1f} "
            f"б.п.), но валового порога {NEED_GROSS_BP:.0f} б.п. не "
            "достигает — экономика D1 остаётся несходящейся.")


def _row(name, r):
    if not r["events"]:
        return f"| {name} | 0 | — | — | — | — | — |"
    return (f"| {name} | {r['events']} | {r['episodes']} | "
            + ("—" if r["excess_bp"] is None
               else f"{r['excess_bp']:+.1f}")
            + " | "
            + ("—" if r["share_pos"] is None else f"{r['share_pos']:.2f}")
            + " | "
            + ("—" if r["own_bp"] is None else f"{r['own_bp']:+.1f}")
            + " | "
            + ("—" if r["liq_usd_med"] is None
               else f"{r['liq_usd_med']:,.0f}")
            + " |")


def report(art, path):
    g = art["groups"]
    L = ["# Падения D1: с принудительными закрытиями и без\n"]
    L.append(f"Прогон {art['run_at']} · суток {art['days']} (молчащих "
             f"лентой ликвидаций {art['dead_days']}) · событий "
             f"{art['events']} · ячейка вердикта спеки 11 · окно "
             "принтов = окно обнаружения (15 мин)\n")
    L.append("**Зонд, не вердикт.** Смерти объявлены до прогона: "
             "группы не различаются — условие украшение (смерть L3); "
             "градиент по нотионалу обратный — механизм не "
             "ликвидации. Валовый порог экономики D1 — "
             f"{NEED_GROSS_BP:.0f} б.п. (двойной круг 17.4 со "
             "спредом).\n")
    L.append("| группа | событий | эпизодов | сверх кросс-секции, б.п."
             " | доля эпизодов >0 | своя нога, б.п. | медиана liq $ |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for grp in GROUPS:
        L.append(_row(grp, g[grp]))
    if g["_gradient"]:
        L.append("\n## Градиент по нотионалу ликвидаций (диагностика)\n")
        L.append("| треть | событий | эпизодов | сверх кросс-секции | "
                 "доля >0 | своя нога | медиана liq $ |")
        L.append("|---|--:|--:|--:|--:|--:|--:|")
        for name, r in g["_gradient"]:
            L.append(_row(name, r))
    if g["_sell_share"] is not None:
        L.append(f"\nДоля Sell среди принтов окна: "
                 f"{g['_sell_share']:.2f}. Семантику метки решают "
                 "данные: в падениях доминирует Buy — на этом потоке "
                 "он и маркирует ликвидацию лонга (моё обратное чтение "
                 "опровергнуто первым прогоном). В меру сторона не "
                 "входит.\n")
    L.append("\n" + art["reading"] + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    if not a.tag:
        a.tag = f"1m-{a.days}d" if a.days else "1m"
    os.makedirs(a.out, exist_ok=True)

    syms, hours = R.available(os.path.join(a.root, "book"))
    days = sorted({h[:10] for h in hours})
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи")
    log_(f"символов {len(syms)}, суток {len(days)}")
    t_start = time.time()
    rows, dead = [], 0
    for day in days:
        if not liq_day_alive(a.root, day):
            dead += 1
            log_(f"  {day}: лента ликвидаций молчит ЦЕЛИКОМ — сутки "
                 "исключены (отказ, неотличимый от тишины)")
            continue
        log_(f"  {day}: читаю")
        got = check_day(a.root, syms, day, a.jobs, log=log_)
        rows += got
        log_(f"  {day}: событий {len(got)}, из них с ликвидациями "
             f"{sum(1 for e in got if e['n_liq'])}")
    art = {
        "run_at": datetime.now(timezone.utc)
        .strftime("%Y-%m-%d %H:%M UTC"),
        "days": len(days) - dead, "dead_days": dead,
        "events": len(rows),
        "groups": summarise(rows),
        "took_min": round((time.time() - t_start) / 60, 1)}
    art["reading"] = reading(art["groups"])
    p = os.path.join(a.out, f"LIQSPLIT-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"LIQSPLIT-{a.tag}.md"))
    log_(f"готово: {p}")
    log_(art["reading"])
    if not a.no_publish:
        R.publish(f"зонд ликвидаций: деление падений D1 ({a.tag})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
