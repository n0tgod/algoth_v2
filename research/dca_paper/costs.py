#!/usr/bin/env python3
"""Издержки бумажных DCA-книг: комиссия площадки, funding, гейт по знаку ставки.

Вопрос владельца 2026-09-06: «в DCA-стратегиях у нас считаются издержки,
комиссия биржи, проскальзывание?» Ответ — НЕТ: журнал книг несёт
`pnl_frac` и `usd` брутто, а в коде книг (`run_paper`, `ration`,
`ladder.simulate_dca`) комиссии, проскальзывания и funding нет вовсе;
единственное место, где круг издержек встречается, — гейт входа
`MIN_EDGE_BP = 3 × круг`. Этот модуль считает две из трёх издержек ПО
ЗАПИСИ книги, не трогая ни журнал, ни правила:

* **комиссия** — тейкер ПО СИМВОЛУ из справочника универсума
  (`taker_fee_bp`: 5.5 у большинства, 2.75 и 11.0 у части — A1 намерила,
  что «комиссия» не одно число); символу без ставки — модальные 5.5 б.п.,
  и число таких строк печатается. Платится на КАЖДОМ рунге (доля
  нотионала × цена рунга) и на выходе (все контракты × цена выхода):
  лестница с четырьмя рунгами платит пять раз, одиночный вход — два;
* **funding** — по рядам площадки исполнения (`a1_universe/out/funding`,
  символы Bybit): на каждом начислении внутри жизни позиции ставка ×
  нотионал, ОТКРЫТЫЙ к этому моменту (рунги заполняются по ходу — до
  долива платит четверть, после — половина). Знак — соглашение
  `funding_series`: положительная ставка означает «лонги платят
  шортам», поэтому лонгу это расход, шорту — доход. Нотионал берётся по
  ценам рунгов, а не по марк-цене в момент начисления (её в записи нет);
  ряд, не покрывающий жизнь позиции целиком, даёт «не измерено», а не
  ноль — и это считается числом;
* **проскальзывание** НЕ считается: его нет ни в записи, ни в модели
  книги; исполнение обходом лесенки — отдельный замер (D1 намерил
  ~4 б.п. медианы на входе живьём).

Рядом — рука «гейт по знаку funding при входе»: та же книга, но вход
только когда последняя известная ставка БЛАГОПРИЯТНА стороне (лонгу —
ставка ≤ 0, шорту — ≥ 0). Это одна из пяти проверок к вопросу «чем
вывести шорт-книги в плюс»; сравнение парное на общих позициях, форма —
той же `run_paper._stats`.

Артефакт: `out/DCA-costs-1m.md` + `.json`, публикует сам (`--no-publish`).
"""

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import run_paper as PP                                        # noqa: E402
import trades as TR                                           # noqa: E402
from common import funding_series as FS                       # noqa: E402

OUT = os.path.join(HERE, "out")
A1 = os.path.join(ROOT, "research", "a1_universe", "out")
UNIVERSE = os.path.join(A1, "universe.json")
FUNDING_DIR = os.path.join(A1, "funding")
TAKER_FALLBACK_BP = float(TR.ROUND_COST_BP) / 2.0     # модальные 5.5 б.п.
MIN_FUNDING_COVER = 0.5      # доля позиций с покрытым рядом, ниже — не вердикт
# «Последняя известная ставка» годится гейту, только если она свежая:
# интервал начисления на площадке не длиннее 8 ч, и точка старше суток
# означает дыру или конец ряда, а не действующую ставку. Без этого срока
# первый живой прогон брал в «ставку на входе» июльскую точку для
# августовских входов — ряды кончились раньше записи книг.
RATE_MAX_AGE_S = 24 * 3600
# меньше стольких позиций в ЛЮБОЙ из рук гейта — рука не судится:
# медиана девяти отсечённых есть шум, а не мера
MIN_ARM_N = 30


def universe():
    with open(UNIVERSE, encoding="utf-8") as f:
        u = json.load(f)
    return u["assets"]


def symbol_maps(assets):
    """Символ Bybit → актив; символ → тейкер б.п. (None — ставки нет)."""
    to_asset, taker = {}, {}
    for a, v in assets.items():
        s = v.get("bybit_symbol")
        if not s:
            continue
        to_asset[s] = a
        taker[s] = v.get("taker_fee_bp")
    return to_asset, taker


def fills_of(row):
    """Рунги записи: (момент, цена, доля нотионала). Пусто — записи нет."""
    out = []
    for f in row.get("fills") or []:
        try:
            ts, px, share = float(f[0]), float(f[1]), float(f[2])
        except (TypeError, ValueError, IndexError):
            continue
        if px > 0 and share > 0:
            out.append((ts, px, share))
    return sorted(out)


def commission_usd(row, taker_bp):
    """Комиссия позиции в долларах: каждый рунг и выход, тейкером.

    Нотионал рунга = доля × нотионал позиции (маржа × плечо) по цене
    рунга; выход — все набранные контракты по цене выхода. Нет нотионала,
    рунгов или цены выхода — None: неизмеримое не есть ноль.
    """
    notl = R.notional_of(row)
    fills = fills_of(row)
    try:
        exit_px = float(row.get("exit_px"))
    except (TypeError, ValueError):
        return None
    if notl is None or not fills or not exit_px > 0:
        return None
    rate = float(taker_bp) / 1e4
    fee, qty = 0.0, 0.0
    for (_ts, px, share) in fills:
        fee += share * notl * rate
        qty += share * notl / px
    fee += qty * exit_px * rate
    return fee


def funding_usd(row, series, side):
    """Funding позиции как ВКЛАД в pnl (минус — платим). None — не измерено.

    `series` — `(времена_мс, ставки)` актива. На каждом начислении в
    `[первый рунг, выход)` открытый нотионал — сумма долей рунгов,
    заполненных к этому моменту, по их ценам. Ряд обязан покрывать окно
    позиции целиком: начисление позже последней точки ряда — не «нуль
    ставки», а отсутствие данных.
    """
    if series is None:
        return None
    notl = R.notional_of(row)
    fills = fills_of(row)
    try:
        exit_ts = float(row.get("exit_ts"))
    except (TypeError, ValueError):
        return None
    if notl is None or not fills or not exit_ts > fills[0][0]:
        return None
    t, r = series
    if len(t) == 0 or t[-1] < exit_ts * 1000 or t[0] > fills[0][0] * 1000:
        return None                       # ряд не покрывает жизнь позиции
    i0 = int(np.searchsorted(t, int(fills[0][0] * 1000), "left"))
    i1 = int(np.searchsorted(t, int(exit_ts * 1000), "left"))
    sign = 1.0 if side == "long" else -1.0
    pnl = 0.0
    for i in range(i0, i1):
        tm = float(t[i]) / 1000.0
        open_notl = sum(share * notl for (ts, _px, share) in fills if ts <= tm)
        pnl -= sign * float(r[i]) * open_notl
    return pnl


def rate_at_entry(series, at, max_age_s=RATE_MAX_AGE_S):
    """Последняя ИЗВЕСТНАЯ на момент входа ставка; None — ряда нет, рано
    или последняя точка старше `max_age_s` (ряд кончился/дыра)."""
    if series is None:
        return None
    t, r = series
    at_ms = int(float(at) * 1000)
    i = int(np.searchsorted(t, at_ms, "right")) - 1
    if i < 0 or at_ms - int(t[i]) > max_age_s * 1000:
        return None
    return float(r[i])


def favourable(side, rate):
    """Гейт входа по знаку ставки: лонгу ставка ≤ 0, шорту ≥ 0."""
    if rate is None:
        return None
    return rate <= 0 if side == "long" else rate >= 0


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts)))


def enrich(rows, funding, to_asset, taker, log=print):
    """Строка журнала → строка с издержками. Пропуски считаются числом."""
    out, miss = [], {"taker_fallback": 0, "no_fills": 0, "no_commission": 0,
                     "no_funding_series": 0, "funding_uncovered": 0,
                     "no_rate_at_entry": 0}
    nf_written = []          # когда записаны строки без рунгов — причина датами
    for row in rows:
        if row.get("exit") is None or row.get("exit_ts") is None:
            continue
        sym = row.get("sym")
        side = R.row_side(row)
        tb = taker.get(sym)
        if tb is None:
            miss["taker_fallback"] += 1
            tb = TAKER_FALLBACK_BP
        fills = fills_of(row)
        if not fills:
            # записи рунгов нет — ни комиссия, ни funding неизмеримы; это
            # прочерк с причиной, и причина печатается датами записи
            miss["no_fills"] += 1
            nf_written.append(float(row.get("written_at") or row.get("at") or 0))
        fee = commission_usd(row, tb) if fills else None
        if fills and fee is None:
            miss["no_commission"] += 1
        asset = to_asset.get(sym)
        series = (funding or {}).get(asset) if asset else None
        fund = None
        if series is None:
            miss["no_funding_series"] += 1
        elif fills:
            fund = funding_usd(row, series, side)
            if fund is None:
                miss["funding_uncovered"] += 1
        rate = rate_at_entry(series, row.get("at"))
        if rate is None:
            miss["no_rate_at_entry"] += 1
        out.append(dict(row, side=side, taker_bp=tb, fee_usd=fee,
                        fund_usd=fund, rate_entry=rate,
                        fav_funding=favourable(side, rate)))
    miss["no_fills_written"] = ([_day(min(nf_written)), _day(max(nf_written))]
                                if nf_written else None)
    log(f"строк с исходом {len(out)}; тейкер по умолчанию у "
        f"{miss['taker_fallback']}, без записи рунгов {miss['no_fills']} "
        f"(записаны {miss['no_fills_written']}), без комиссии "
        f"{miss['no_commission']}, "
        f"без ряда funding {miss['no_funding_series']}, ряд не покрывает "
        f"{miss['funding_uncovered']}, ставка на входе неизвестна "
        f"{miss['no_rate_at_entry']}")
    return out, miss


def _sum(rows, k):
    v = [float(r[k]) for r in rows if r.get(k) is not None]
    return (round(float(np.sum(v)), 2) if v else None), len(v)


def _bp_median(rows, k):
    v = [float(r[k]) / float(r["margin"]) * 1e4 for r in rows
         if r.get(k) is not None and float(r.get("margin") or 0) > 0]
    return round(float(np.median(v)), 1) if v else None


def _stats_net(rows, dep):
    """Форма книги нетто: те же `_stats`, деньги = брутто − комиссия + funding."""
    take = []
    for r in rows:
        if r.get("fee_usd") is None or r.get("fund_usd") is None:
            continue
        take.append({"exit_ts": r["exit_ts"], "at": r["at"], "sym": r["sym"],
                     "written_at": r.get("written_at"),
                     "usd": float(r["usd"]) - float(r["fee_usd"])
                     + float(r["fund_usd"])})
    return PP._stats(take, dep) or {}, len(take)


def _stats_gross(rows, dep):
    take = [{"exit_ts": r["exit_ts"], "at": r["at"], "sym": r["sym"],
             "written_at": r.get("written_at"), "usd": float(r["usd"])}
            for r in rows]
    return PP._stats(take, dep) or {}


def book_costs(rows, dep):
    """Издержки книги: суммы, медианы на позицию (б.п. маржи), форма нетто."""
    gross, n = _sum(rows, "usd")
    fee, n_fee = _sum(rows, "fee_usd")
    fund, n_fund = _sum(rows, "fund_usd")
    both = [r for r in rows if r.get("fee_usd") is not None
            and r.get("fund_usd") is not None]
    gross_m, _ = _sum(both, "usd")
    fee_m, _ = _sum(both, "fee_usd")
    fund_m, _ = _sum(both, "fund_usd")
    net = (round(gross_m - fee_m + fund_m, 2)
           if both and gross_m is not None else None)
    st_n, n_net = _stats_net(rows, dep)
    st_g = _stats_gross(rows, dep)
    return {"n": n, "gross_usd": gross,
            "fee_usd": fee, "n_fee": n_fee,
            "fund_usd": fund, "n_fund": n_fund,
            "fund_cover": round(n_fund / n, 3) if n else None,
            # нетто — только по позициям, где измерены ОБЕ издержки
            "measured": len(both), "gross_measured_usd": gross_m,
            "net_usd": net,
            "net_pct": round(net / dep, 5) if net is not None else None,
            "gross_pct": round(gross / dep, 5) if gross is not None else None,
            "fee_bp_median": _bp_median(rows, "fee_usd"),
            "fund_bp_median": _bp_median(rows, "fund_usd"),
            "gross_bp_median": _bp_median(rows, "usd"),
            "form_gross": {k: st_g.get(k) for k in
                           ("day_median", "day_green", "bite", "max_dd", "win")},
            "form_net": {k: st_n.get(k) for k in
                         ("day_median", "day_green", "bite", "max_dd", "win")},
            "n_net_form": n_net}


def gate_arm(rows, dep):
    """Рука «вход только при благоприятной ставке» против всех — парно.

    Обе руки считаются на позициях, у которых ставка на входе ИЗВЕСТНА:
    иначе рука сравнивала бы себя с книгой другого состава.
    """
    known = [r for r in rows if r.get("fav_funding") is not None]
    fav = [r for r in known if r["fav_funding"]]
    if not known:
        return None
    rest = [r for r in known if not r["fav_funding"]]
    a_all, a_fav = book_costs(known, dep), book_costs(fav, dep)
    return {"n_known": len(known), "n_fav": len(fav), "n_rest": len(rest),
            "share_fav": round(len(fav) / len(known), 3),
            "all": a_all, "fav": a_fav,
            "usd_fav": round(float(sum(float(r["usd"]) for r in fav)), 2),
            "usd_rest": round(float(sum(float(r["usd"]) for r in rest)), 2),
            # медианы — в б.п. МАРЖИ позиции (`usd / margin`), чтобы книги
            # разных депозитов читались одной шкалой; доллары здесь
            # печатались бы как проценты — ошибка единиц первого прогона
            "median_fav": _bp_median(fav, "usd"),
            "median_rest": _bp_median(rest, "usd"),
            "median_all": _bp_median(known, "usd")}


def run(rows=None, funding=None, assets=None, log=print):
    t0 = time.time()
    assets = assets if assets is not None else universe()
    to_asset, taker = symbol_maps(assets)
    if rows is None:
        st = {}
        rows, bad = R.read_journal(stats=st)
        log(f"журнал: {len(rows)} строк, битых {bad}, кусков {st.get('parts')}")
    # книга — строки ТЕКУЩЕЙ версии правил, как на странице книг; прежние
    # версии писаны другим правилом, и складывать их значит считать
    # книгу, которой не было (первый прогон складывал все 67 тыс. строк)
    n_all = len(rows)
    rows = [r for r in rows if R.is_current(r)]
    log(f"текущей версии правил ({R.RULES}): {len(rows)} строк из {n_all}")
    syms = {r.get("sym") for r in rows}
    need = {to_asset[s] for s in syms if s in to_asset}
    if funding is None:
        funding = FS.load_funding(FUNDING_DIR, assets, need,
                                  symbol_field="bybit_symbol")
        if funding is None:
            log(f"каталога funding нет: {FUNDING_DIR} — funding не измерен")
        else:
            log(f"funding: рядов {len(funding)} из {len(need)} нужных активов")
    rich, miss = enrich(rows, funding, to_asset, taker, log=log)
    books = {}
    for r in rich:
        books.setdefault((R.ruler_of(r), float(r.get("dep") or 0)), []).append(r)
    cells, arms, sides = {}, {}, {}
    for (rk, dep), rs in sorted(books.items()):
        key = f"{rk}:{int(dep)}"
        cells[key] = dict(book_costs(rs, dep), ruler=rk, dep=dep,
                          side=R.side_of(rk))
        arms[key] = gate_arm(rs, dep)
    for side in ("long", "short"):
        rs = [r for r in rich if r["side"] == side
              and float(r.get("dep") or 0) == R.DEPOSITS[1]]
        sides[side] = book_costs(rs, R.DEPOSITS[1]) if rs else None
    n_rows = len(rich)
    # покрытие — от строк, у которых издержки измеримы в принципе (есть
    # запись рунгов); доля строк без рунгов печатается рядом с причиной
    n_fills = n_rows - miss["no_fills"]
    covered = sum(1 for r in rich if r.get("fund_usd") is not None)
    cover = covered / n_fills if n_fills else 0.0
    cover_all = covered / n_rows if n_rows else 0.0
    fr = sorted(set(float(r["taker_bp"]) for r in rich))
    return {"cells": cells, "arms": arms, "sides": sides, "miss": miss,
            "rows": n_rows, "rows_all": n_all, "rows_with_fills": n_fills,
            "funding_cover": round(cover, 3),
            "funding_cover_all": round(cover_all, 3),
            "funding_present": funding is not None and len(funding) > 0,
            "funding_assets": len(funding or {}),
            "taker_rates_bp": fr, "taker_fallback_bp": TAKER_FALLBACK_BP,
            "min_cover": MIN_FUNDING_COVER,
            "deposits": R.DEPOSITS, "rules_version": R.RULES,
            "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


def verdict(s):
    """Из чисел: у каких книг знак держится после комиссии и funding, и
    помогает ли гейт по ставке (парно, по медиане позиции)."""
    out = {"measurable": s["funding_present"] and s["funding_cover"] >= s["min_cover"],
           "sign_kept": [], "sign_lost": [], "gate_helps": [], "gate_hurts": []}
    for k, c in s["cells"].items():
        if c.get("net_usd") is None:
            continue
        g = c.get("gross_measured_usd") or 0.0
        if g > 0 and c["net_usd"] > 0:
            out["sign_kept"].append(k)
        elif g > 0 and c["net_usd"] <= 0:
            out["sign_lost"].append(k)
    for k, a in s["arms"].items():
        if (not a or a["n_fav"] < MIN_ARM_N or a.get("n_rest", 0) < MIN_ARM_N
                or a["median_fav"] is None):
            continue
        if a["median_rest"] is None:
            continue
        (out["gate_helps"] if a["median_fav"] > a["median_rest"]
         else out["gate_hurts"]).append(k)
    return out


def _u(x):
    return "—" if x is None else f"{x:+,.2f}"


def _p(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def _b(x):
    return "—" if x is None else f"{x:+.1f}"


def report(s):
    v = verdict(s)
    m = s["miss"]
    P = ["# Издержки бумажных DCA-книг: комиссия, funding, гейт по ставке", "",
         "Вопрос владельца 2026-09-06: «считаются ли в DCA-стратегиях "
         "издержки — комиссия биржи, проскальзывание?» **Нет:** журнал книг "
         "несёт брутто, в коде книг ни комиссии, ни проскальзывания, ни "
         "funding нет (круг издержек встречается только в гейте входа "
         "`3 × круг`). Здесь издержки посчитаны ПО ЗАПИСИ, журнал и правила "
         "не тронуты.", "",
         "**Комиссия** — тейкер по символу из справочника универсума (ставки "
         + ", ".join(f"{x:g}" for x in s["taker_rates_bp"]) + " б.п.; символу "
         f"без ставки — {s['taker_fallback_bp']:g}, таких строк "
         f"{s['miss']['taker_fallback']}), на каждом рунге и на выходе. "
         "**Funding** — ряды площадки исполнения, на каждом начислении ставка "
         "× нотионал, открытый к этому моменту (по ценам рунгов, марк-цены "
         "в записи нет); лонгу положительная ставка — расход, шорту — доход. "
         "Ряд, не покрывающий жизнь позиции, даёт «не измерено», а не ноль. "
         "**Проскальзывание не считается** — его нет ни в записи, ни в "
         "модели; живой замер D1 дал медиану ~4 б.п. на входе.", "",
         f"Строк с исходом {s['rows']} — версия правил книг "
         f"{s['rules_version']}, как на странице книг (в журнале всего "
         f"{s.get('rows_all', s['rows'])}; прежние версии писаны другим "
         "правилом и в счёт не входят)"
         + (f"; без записи рунгов {m['no_fills']} (записаны "
            f"{m['no_fills_written'][0]} … {m['no_fills_written'][1]}) — у них "
            "ни комиссия, ни funding неизмеримы: прочерк, не ноль"
            if m.get("no_fills") else "")
         + f". Рядов funding {s['funding_assets']}; покрытие позиций с "
         f"рунгами {s['funding_cover'] * 100:.1f} % (от всех строк "
         f"{s.get('funding_cover_all', s['funding_cover']) * 100:.1f} %) при "
         f"пороге вердикта {s['min_cover'] * 100:.0f} %"
         + ("" if v["measurable"] else " — **funding НЕ измерен, колонки нетто "
            "читать нельзя**") + ".",
         ""]
    P += ["## По книгам (суммы в $, медианы на позицию в б.п. МАРЖИ)", "",
          "| книга | сторона | n | брутто $ | комиссия $ | funding $ | "
          "измерено | нетто $ (измеренные) | брутто измеренных $ | "
          "комиссия б.п. | funding б.п. | брутто б.п. | медиана дня брутто → "
          "нетто | зелёных | укус |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
          "---:|---:|"]
    for k, c in s["cells"].items():
        fg, fn = c["form_gross"], c["form_net"]
        P.append(
            f"| `{k}` | {c['side']} | {c['n']} | {_u(c['gross_usd'])} | "
            f"{_u(-(c['fee_usd'] or 0) if c['fee_usd'] is not None else None)} | "
            f"{_u(c['fund_usd'])} | {c['measured']} | {_u(c['net_usd'])} | "
            f"{_u(c['gross_measured_usd'])} | {_b(c['fee_bp_median'])} | "
            f"{_b(c['fund_bp_median'])} | {_b(c['gross_bp_median'])} | "
            f"{_p(fg.get('day_median'), 3)} → {_p(fn.get('day_median'), 3)} | "
            f"{_p(fg.get('day_green'), 0)} → {_p(fn.get('day_green'), 0)} | "
            f"{fg.get('bite') if fg.get('bite') is not None else '—'} → "
            f"{fn.get('bite') if fn.get('bite') is not None else '—'} |")
    P += ["", "Нетто = брутто − комиссия + funding по позициям, у которых "
          "измерены ОБЕ издержки; «брутто измеренных» — брутто того же "
          "подмножества, чтобы сравнивать одно с одним. Знак после издержек "
          f"держат {len(v['sign_kept'])} книг из "
          f"{len(v['sign_kept']) + len(v['sign_lost'])} с положительным "
          "брутто"
          + (" — теряют: " + ", ".join(f"`{k}`" for k in v["sign_lost"])
             if v["sign_lost"] else "") + ".", ""]
    P += ["## По сторонам (депозит $10 000)", "",
          "| сторона | n | брутто $ | комиссия $ | funding $ | измерено | "
          "брутто измеренных $ | нетто $ (измеренные) | "
          "funding б.п. на позицию |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for side, c in s["sides"].items():
        if not c:
            P.append(f"| {side} | 0 | — | — | — | — | — | — | — |")
            continue
        P.append(f"| {side} | {c['n']} | {_u(c['gross_usd'])} | "
                 f"{_u(-(c['fee_usd'] or 0) if c['fee_usd'] is not None else None)} | "
                 f"{_u(c['fund_usd'])} | {c['measured']} | "
                 f"{_u(c['gross_measured_usd'])} | {_u(c['net_usd'])} | "
                 f"{_b(c['fund_bp_median'])} |")
    P += ["", "## Гейт по знаку ставки на входе (лонг при ставке ≤ 0, "
          "шорт при ≥ 0)", "",
          "Обе руки — на позициях с ИЗВЕСТНОЙ ставкой на входе (последняя "
          f"точка ряда не старше {RATE_MAX_AGE_S // 3600} ч до входа); "
          "«отсечённые» — те, кого гейт не пустил. Читать по медиане "
          "позиции в б.п. маржи: гейт меняет состав, и суммы рук "
          "несравнимы по построению.", "",
          "| книга | известна | прошли гейт | отсечено | доля | "
          "медиана всех, б.п. маржи | медиана прошедших | "
          "медиана отсечённых | $ прошедших | $ отсечённых | "
          "нетто прошедших $ |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, a in s["arms"].items():
        if not a:
            P.append(f"| `{k}` | 0 | — | — | — | — | — | — | — | — | — |")
            continue
        P.append(f"| `{k}` | {a['n_known']} | {a['n_fav']} | "
                 f"{a.get('n_rest', a['n_known'] - a['n_fav'])} | "
                 f"{a['share_fav'] * 100:.0f} % | {_b(a['median_all'])} | "
                 f"{_b(a['median_fav'])} | {_b(a['median_rest'])} | "
                 f"{_u(a['usd_fav'])} | {_u(a['usd_rest'])} | "
                 f"{_u(a['fav']['net_usd'])} |")
    P += ["", f"Гейт помогает по медиане позиции у {len(v['gate_helps'])} книг"
          + (" (" + ", ".join(f"`{k}`" for k in v["gate_helps"]) + ")"
             if v["gate_helps"] else "")
          + f", вредит у {len(v['gate_hurts'])}"
          + (" (" + ", ".join(f"`{k}`" for k in v["gate_hurts"]) + ")"
             if v["gate_hurts"] else "")
          + f"; книги с меньше чем {MIN_ARM_N} позиций в любой из рук "
          "не судятся.", "",
          "## Чего замер НЕ говорит", "",
          "Проскальзывания в числах нет. Funding посчитан по нотионалу рунгов, "
          "а не по марк-цене начисления (расхождение — ход цены от рунга до "
          "начисления, единицы процентов от самого funding). Комиссия — "
          "по сегодняшнему тарифу счёта, прошлых сеток площадка не отдаёт "
          "(A1). Гейт по ставке просмотрен ПОСЛЕ прогона книг — правилом он "
          "стать может только объявленным заранее и проверенным вперёд.", ""]
    return "\n".join(P)


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    s = run()
    with open(os.path.join(OUT, f"DCA-costs-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"DCA-costs-{a.tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"DCA: издержки книг — комиссия, funding, гейт по ставке ({a.tag})")


if __name__ == "__main__":
    main()
