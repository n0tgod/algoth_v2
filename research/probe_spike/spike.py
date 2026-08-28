#!/usr/bin/env python3
"""Зонд минутного всплеска: цена это была или котировка, и что после круга.

Откуда взялся предмет. Скрин лесенки на двадцати сутках дал ровно один
кандидат — и это его КОНТРОЛЬ без лесенки: «цена выросла на 2 % за
минуту», шорт, 60 минут, превышение над одновременной кросс-секцией
+32.9 б.п. сверх сноса при круге нейтральной книги 22, доля прибыльных
корзин 0.61, половины записи совпадают (+33.3 и +32.8). Книга в этом
условии не участвует ни одним числом, то есть измерен возврат после
резкого хода — семейство, которое проект уже мерил (Z1, зонд возврата,
D1) и где оно умирало об издержки.

Три вопроса, объявленные ДО прогона, и все три — из D1.

1. **Цена или котировка.** Середина прыгает и без единой сделки:
   достаточно снять биды. Тогда «возврат» есть возвращение котировки,
   и торговать его нечем. В минутном складе для этого есть готовые
   поля: `trades` (сделок в минуте) и `path_quiet/path` — доля хода,
   сделанного БЕЗ сделок. События делятся на три группы, и превышение
   считается по каждой отдельно.

2. **Сколько стоит круг.** Превышение над одновременной кросс-секцией
   есть книга из ДВУХ ног, поэтому и круг считается по двум: комиссия
   11 б.п. на ногу (конвенция R4, `NEUTRAL_COST_BP` = 22) плюс
   пересечение спреда каждой ногой. Пересечение стоит ПОЛОВИНУ спреда
   относительно середины, а не спред целиком — так же считал D1
   (6.8 и 6.1 б.п. спреда дали круг 17.4 при комиссии 11). Спред
   нашей ноги берётся из той же записи в минуту события и в минуту
   выхода; спред хедж-ноги — медиана спреда по сечению в те же
   минуты, а не назначается. Оценка остаётся НИЖНЕЙ границей:
   исполнение считается по краю книги, без обхода лесенки, а D1
   намерил, что обход может только удорожить.

3. **Не сидит ли всё в горстке имён.** Колонка «без лучшего имени» —
   тот же приём, что переворачивал вывод в `one_name.py` и в лиге.

Пороги объявлены здесь и после прогона не двигаются:
   всплеск ±2 % за минуту; подтверждён лентой — сделок ≥ 10 и тихая
   доля ≤ 0.5; котировочный — тихая доля ≥ 0.8; между ними «серединка»
   и считается отдельно, а не приписывается ни к одной группе.

Запуск:
    cd ~/algoth_v2 && mkdir -p research/probe_spike/out
    cd ~/algoth_v2 && .venv/bin/python research/probe_spike/spike.py --tag 1m
"""
import argparse
import json
import os
import sys
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "z2_book"), os.path.join(ROOT, "z1_screen"),
          os.path.join(ROOT, "b1_book")):
    if p not in sys.path:
        sys.path.insert(0, p)

import probe as P2                                        # noqa: E402
import screen as Z                                        # noqa: E402

OUT = os.path.join(HERE, "out")
HORIZONS = (15, 60, 240)
JUMP = 0.02                # всплеск за минуту
MIN_TRADES = 10            # сделок в минуте события
QUIET_OK = 0.5             # тихая доля не больше — событие подтверждено
QUIET_BAD = 0.8            # тихая доля не меньше — событие котировочное
FEE_BP = 11.0              # комиссия круга на ногу (тейкер 5.5 × 2)
LEGS = 2                   # книга из двух ног: наша и хедж об сечение


def log_(m):
    print(m, flush=True)


def moves(mid):
    out = np.full_like(mid, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:, 1:] = mid[:, 1:] / mid[:, :-1] - 1.0
    return out


def primitives(M):
    p = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        p["ret_1m"] = moves(M["mid_open"])
        p["trades"] = M["trades"]
        # Доля хода, сделанного без единой сделки. Ноль пути — меры
        # нет, а не «весь ход сделками»: пропуск, а не ноль.
        p["quiet"] = np.where(M["path"] > 0, M["path_quiet"] / M["path"],
                              np.nan)
    return p


def build_conditions():
    C = []

    def add(name, side, fn, group):
        C.append({"name": name, "side": side, "fn": fn, "group": group})

    for s in (+1, -1):
        for lbl, sign in (("вверх", +1), ("вниз", -1)):
            jump = ((lambda p: p["ret_1m"] >= JUMP) if sign > 0
                    else (lambda p: p["ret_1m"] <= -JUMP))
            add(f"всплеск {lbl} 2 % — подтверждён лентой", s,
                (lambda p, j=jump: j(p) & (p["trades"] >= MIN_TRADES)
                 & (p["quiet"] <= QUIET_OK)), f"всплеск {lbl}")
            add(f"всплеск {lbl} 2 % — котировочный", s,
                (lambda p, j=jump: j(p) & (p["quiet"] >= QUIET_BAD)),
                f"всплеск {lbl}")
            add(f"всплеск {lbl} 2 % — все события", s,
                (lambda p, j=jump: j(p)), f"всплеск {lbl}")
    return C


CONDITIONS = build_conditions()
CONDS_BY_NAME = {}
for _c in CONDITIONS:
    CONDS_BY_NAME.setdefault(_c["name"], []).append(_c)


def collect_events(P, prim, log=log_):
    ev = {}
    fin = np.isfinite(P)
    for c in CONDITIONS:
        if c["name"] in ev:
            continue
        try:
            hit = c["fn"](prim) & fin
        except KeyError:
            continue
        r, cc = Z.dedup_rows(hit, dedup_min=5)
        if len(r):
            ev[c["name"]] = (c, r, cc)
    log(f"  условий сработало {len(ev)}, событий "
        f"{sum(len(v[1]) for v in ev.values()):,}".replace(",", " "))
    return ev


def diag(ev, M, syms, acc, h=60):
    """Спред, концентрация по именам и сырой ход — по каждому условию.

    Считается напрямую, а не судьёй: судья отдаёт сводку по ячейке, а
    здесь нужны величины, из которых складывается ЦЕНА сделки, и имя,
    на котором всё держится.

    ВСЁ хранится в базисных пунктах. `fwd_ret` отдаёт долю, судья
    домножает на 1e4 только в своей сводке, и первый прогон напечатал в
    таблице цены сделки «−0.0» при +38.5 б.п. в главной таблице: одна
    таблица отчёта противоречила другой, и меньшая читалась как «эффекта
    нет». Та же ошибка единиц, что спред «на ногу» против цикла «на пару
    ног» в R4.

    Сторона здесь НЕ применяется: копится длинная сторона, а знак
    ставит отчёт по стороне условия — иначе у имени, входящего в сетку
    обеими сторонами, пришлось бы держать две копии одних чисел.
    """
    P = M["mid_open"]
    F = Z.fwd_ret(P, h)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        # Колонка без единой конечной доходности — законный пропуск
        # (край суток, тонкая минута), и nanmean по ней шумит
        # предупреждением. Молчание здесь не прячет ошибку: результат
        # остаётся NaN и дальше отсеивается проверкой конечности.
        warnings.simplefilter("ignore", RuntimeWarning)
        colm = np.nanmean(F, axis=0)
        # Спред хедж-ноги: медиана по сечению в ту же минуту. Хедж —
        # равновзвешенная корзина сечения, и каждая её нога платит
        # своё пересечение; назначить её спред числом значило бы
        # выдумать половину издержек книги.
        hedge = np.nanmedian(M["spread"], axis=0)
    n = P.shape[1]
    for name, (_, rows, cols) in ev.items():
        a = acc.setdefault(name, {"spread_in": [], "spread_out": [],
                                  "hedge_in": [], "hedge_out": [],
                                  "raw": [], "exc": [], "by_sym": {},
                                  "n": 0})
        sp_in = M["spread"][rows, cols]
        out_c = np.minimum(cols + h, n - 1)
        sp_out = M["spread"][rows, out_c]
        hg_in, hg_out = hedge[cols], hedge[out_c]
        a["hedge_in"] += [float(x) for x in hg_in[np.isfinite(hg_in)]]
        a["hedge_out"] += [float(x) for x in hg_out[np.isfinite(hg_out)]]
        raw = F[rows, cols] * 1e4
        exc = raw - colm[cols] * 1e4
        ok = np.isfinite(exc)
        a["n"] += int(ok.sum())
        a["spread_in"] += [float(x) for x in sp_in[np.isfinite(sp_in)]]
        a["spread_out"] += [float(x) for x in sp_out[np.isfinite(sp_out)]]
        a["raw"] += [float(x) for x in raw[np.isfinite(raw)]]
        a["exc"] += [float(x) for x in exc[ok]]
        for r, e in zip(rows[ok], exc[ok]):
            s = syms[r]
            v = a["by_sym"].setdefault(s, [0.0, 0])
            v[0] += float(e)
            v[1] += 1


def _q(v, q=50):
    return float(np.percentile(v, q)) if len(v) else float("nan")


def round_trip(a):
    """Круг книги из двух ног: комиссия обеих плюс по половине спреда.

    Пересечение спреда стоит ПОЛОВИНУ его ширины относительно
    середины — цены и превышение меряются по середине. Формула одна на
    отчёт и на журнал прогона: два места, считающие одно и то же,
    однажды разойдутся.
    """
    si, so = _q(a["spread_in"]), _q(a["spread_out"])
    hi, ho = _q(a["hedge_in"]), _q(a["hedge_out"])
    return LEGS * FEE_BP + (si + so) / 2 + (hi + ho) / 2, si, so, hi, ho


def write_report(path, cells, null, dg, meta):
    L = ["# Зонд минутного всплеска: цена или котировка, и что после круга\n"]
    L.append(f"\nПрогон {meta['when']} · суток {meta['days']} "
             f"({meta['first']}…{meta['last']}) · условий "
             f"{len(CONDITIONS)} · ячеек {len(cells)}\n")
    L.append("\n**Откуда предмет.** Скрин лесенки на двадцати сутках дал "
             "ровно один кандидат — и это его контроль БЕЗ лесенки: "
             "«цена выросла на 2 % за минуту», шорт, 60 минут. Значит "
             "измерен возврат после резкого хода, а не сведение из "
             "книги. Здесь проверяется, цена ли это была и переживает "
             "ли она круг издержек.\n")
    L.append("\n**Как отделена котировка от цены.** Середина прыгает и "
             "без единой сделки — достаточно снять биды. Событие "
             "подтверждено, если сделок в минуте не меньше "
             f"{MIN_TRADES} и доля хода без сделок не больше "
             f"{QUIET_OK}; котировочное — если эта доля не меньше "
             f"{QUIET_BAD}. Между ними «серединка», и она НЕ "
             "приписывается ни к одной группе.\n")
    L.append("\n**Издержки считаются по ДВУМ ногам.** Превышение над "
             "одновременной кросс-секцией есть PnL книги «наша нога "
             "против сечения», поэтому круг равен комиссии обеих ног "
             f"({LEGS} × {FEE_BP:.0f} = {LEGS * FEE_BP:.0f} б.п.) плюс "
             "по половине спреда на каждую: пересечение стоит половину "
             "ширины относительно середины, а цены и превышение "
             "меряются по середине (так же считал D1). Спред нашей ноги "
             "взят из записи в минуту события и в минуту выхода, спред "
             "хедж-ноги — медиана спреда по сечению в те же минуты. Это "
             "по-прежнему НИЖНЯЯ граница: исполнение считается по краю "
             "книги, без обхода лесенки.\n")
    L.append("\n| условие | стор. | гор. | событий | корзин | медиана | "
             "среднее | доля+ | z | вердикт |\n")
    L.append("|---|:--:|--:|--:|--:|--:|--:|--:|--:|---|\n")
    for (name, side, h), c in sorted(cells.items(),
                                     key=lambda kv: -(kv[1].get("z") or -9e9)):
        L.append(f"| {name} | {'L' if side > 0 else 'S'} | {h}м | "
                 f"{c['events']:,} | {c['buckets']:,} | "
                 f"{c['med_bp']:+.1f} | {c['mean_bp']:+.1f} | "
                 f"{c.get('win', float('nan')):.2f} | "
                 f"{c.get('z', float('nan')):+.1f} | "
                 f"{Z.verdict_of(c, null)} |\n".replace(",", " "))
    L.append("\n### Цена сделки и на чём она держится (горизонт 60 минут)\n\n")
    L.append("| условие | стор. | событий | спред наш | спред хеджа | "
             "круг двух ног | превышение | нетто | без лучшего имени |\n")
    L.append("|---|:--:|--:|--:|--:|--:|--:|--:|--:|\n")
    rows_ = []
    for name, a in sorted(dg.items()):
        if not a["exc"]:
            continue
        rnd, si, so, hi, ho = round_trip(a)
        base = float(np.mean(a["exc"]))
        best, bexc = None, 0.0
        tot, cnt = sum(v[0] for v in a["by_sym"].values()), a["n"]
        for sym, v in a["by_sym"].items():
            if abs(v[0]) > abs(bexc):
                best, bexc = sym, v[0]
        wo0 = ((tot - bexc) / max(cnt - a["by_sym"].get(best, [0, 0])[1], 1)
               if best else float("nan"))
        for c in CONDS_BY_NAME.get(name, []):
            sd = c["side"]
            rows_.append((-(sd * base), name, sd, a, rnd, si, so, hi, ho,
                          sd * base, sd * wo0, best))
    for _, name, sd, a, rnd, si, so, hi, ho, exc, wo, best in sorted(rows_):
        L.append(f"| {name} | {'L' if sd > 0 else 'S'} | {a['n']:,} | "
                 f"{si:.1f}/{so:.1f} | {hi:.1f}/{ho:.1f} | {rnd:.1f} | "
                 f"{exc:+.1f} | {exc - rnd:+.1f} | "
                 f"{wo:+.1f} ({best}) |\n".replace(",", " "))
    L.append("\nВсё в базисных пунктах. Превышение здесь считается прямым "
             "проходом (среднее по событиям против среднего сечения в ту "
             "же минуту), а главная таблица — судьёй по корзинам с "
             "запретом соседей: числа обязаны совпадать по знаку и "
             "порядку, а не дословно. "
             "Спреды (вход/выход) взяты из той же "
             "записи. «Круг двух ног» = "
             f"{LEGS} × {FEE_BP:.0f} + (наш вход + наш выход)/2 + "
             "(хедж вход + хедж выход)/2. «Нетто» — превышение минус "
             "круг.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="зонд минутного всплеска")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    syms = [s for s in a.symbols.split(",") if s] or P2.symbols()
    if not syms:
        log_(f"в {P2.BOOK} нет записи — считать нечего")
        return 1
    days = sorted(P2.F.scan(P2.STORE))
    if days:
        # Начало — первые ПОЛНЫЕ и ШИРОКИЕ сутки склада, а не первые
        # сутки записи: состав сборщика рос ступенями 25 → 30 → 540 →
        # 725, и на ранних сутках кросс-секции, которой меряется
        # превышение, нет вовсе (тот же страж, что у скрина Z2).
        start = P2.start_day(a.start, days, use_store=True, log=log_)
        days = [d for d in days if d >= start]
    if a.end:
        days = [d for d in days if d <= a.end]
    if not days:
        log_("минутного склада Z2 нет — считать нечего")
        return 1
    log_(f"зонд всплеска: суток {len(days)} ({days[0]}…{days[-1]}), "
         f"символов {len(syms)}")
    acc, dg, rng = {}, {}, np.random.default_rng(Z.SEED)
    for day in days:
        M, _ = P2.day_matrices(syms, day, log=log_, use_store=True)
        prim = primitives(M)
        times = np.arange(M["mid_open"].shape[1], dtype=np.int64) * 60 \
            + int(datetime.strptime(day, "%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp())
        ev = collect_events(M["mid_open"], prim)
        if not ev:
            continue
        Z.measure(ev, M["mid_open"], times, acc, rng,
                  conds_by_name=CONDS_BY_NAME, control="mean",
                  horizons=HORIZONS)
        diag(ev, M, syms, dg)
    if not acc:
        log_("ни одного события — считать нечего")
        return 1
    cells, null = Z.summarize(acc)
    path = os.path.join(OUT, f"SPIKE-report-{a.tag}.md")
    write_report(path, cells, null, dg,
                 {"when": datetime.now(timezone.utc)
                  .strftime("%Y-%m-%d %H:%M UTC"),
                  "days": len(days), "first": days[0], "last": days[-1]})
    with open(os.path.join(OUT, f"spike-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": {f"{k[0]}|{k[1]}|{k[2]}": v
                             for k, v in cells.items()}, "null": null},
                  f, ensure_ascii=False)
    log_(f"отчёт: {path}")
    for name, aa in sorted(dg.items()):
        if not aa["exc"]:
            continue
        rnd, si, so, hi, ho = round_trip(aa)
        exc = float(np.mean(aa["exc"]))
        log_(f"  {name}: событий {aa['n']:,}, "
             f"спред {si:.1f}/{so:.1f}, хедж {hi:.1f}/{ho:.1f}, "
             f"круг {rnd:.1f}, превышение лонга {exc:+.1f}, "
             f"нетто лонга {exc - rnd:+.1f} б.п.".replace(",", " "))
    if not a.no_publish:
        Z.publish("зонд минутного всплеска: цена или котировка")
    return 0


if __name__ == "__main__":
    sys.exit(main())
