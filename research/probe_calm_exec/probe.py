#!/usr/bin/env python3
"""Зонд пассивного входа в СПОКОЙНОМ рынке.

Вопрос (выбор владельца из карты направлений): D1 намерил, что в
СТРЕССЕ пассивная заявка — не снижение издержек, а смена выборки со
сменой знака (неблагоприятный отбор −54.7 б.п., исполнение 0.42). Но
живые книги входят не в каскадах, а в обычные часы. Если в спокойном
рынке отбор мал, круг издержек ноги падает с 11 до ~4 б.п. — и это
меняет арифметику всех будущих гипотез. Если отбор велик и там, довод
«спасёмся мейкером» закрыт вторым замером, окончательно.

Это зонд, а не гипотеза: порогов и вердикта нет, пространство объявлено
до прогона, решение по таблице — за владельцем.

Мера. В начале каждого часа по каждому имени ставятся две пассивные
заявки (на лучшей цене своей стороны и на середине) и рядом — тейкерский
вход. Все руки оцениваются в ОДНОЙ точке `i0 + HORIZON_SEC` по середине:
не исполнившаяся за `T` секунд лимитка доисполняется тейкером в `i0 + T`
— рука «мейкер» есть стратегия «поставь лимитку, не вышло — бей рынок»,
и только так её можно честно сравнить с тейкером на одном множестве
моментов. Главная величина — `выгода = value(пассив) − value(тейкер)` в
б.п. нотионала ноги; экономия спреда и цена отбора сидят в ней ВМЕСТЕ,
потому что вопрос звучит «ставить ли лимитку», а не «красив ли спред».

Модель очереди — та же, что в D1 (`d1_seconds/passive.py`): исполнение
по факту прошедшей сквозь уровень встречной агрессии, не по касанию
(ошибка движка v1); отмены заявок не видны и не учитываются — это
работает ПРОТИВ пассивной руки.

Ось состояния — ход середины за час ДО заявки в единицах причинной σ
символа (σ часовых доходностей по прошлым СУТКАМ, расширяющееся окно,
минимум MIN_SIGMA_OBS наблюдений; моменты без σ не меряются). Полоса
«спокойно» (|z| < 0.25) и есть предмет зонда, остальные — градиент.

Ловушки, названные до прогона:
- спокойный рынок не отменяет отбора: лимитка на биде и в тишине
  исполняется тогда, когда цена идёт сквозь неё, — ровно это и меряем;
- комиссия учитывается только на входе: выход у всех рук один и тот же
  условный (по середине в общей точке) и в разности сокращается;
- своя заявка на рынок не влияет; запись — 3+ недели одного режима.

Запуск: см. RUNBOOK.md. Смоук: --days 2 --take 6 --tag smoke --no-publish
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))
sys.path.insert(0, os.path.join(RESEARCH, "b1_book"))
sys.path.insert(0, RESEARCH)

import detect as D                                        # noqa: E402
import passive as PV                                      # noqa: E402
import run_d1 as R                                        # noqa: E402
from common import universe_filter as UF                  # noqa: E402

# --- объявлено до прогона ---------------------------------------------
SIZE_USD = 300.0    # нога бумажной ситуационной книги: зонд про вход
#                     живых книг, а не про спеку 11 (там было $5000)
WAITS = (60, 300, 900)          # сколько лимитка стоит, с
HORIZON_SEC = 3600              # общая точка оценки всех рук
STATE_SEC = 3600                # окно состояния: ход за час до заявки
Z_EDGES = (-1.0, -0.25, 0.25, 1.0)
BAND_NAMES = ("падал ≥1σ", "падал", "спокойно", "рос", "рос ≥1σ")
CALM_BAND = 2                   # |z| < 0.25
MIN_SIGMA_OBS = 48              # часовых доходностей до первой меры
SNAP_TOL = 5                    # снимок-якорь: не позже 5 с от начала часа
REF_TOL = 60                    # точки состояния/оценки: допуск 60 с
ARMS = ("на лучшей", "на середине")
SIDES = (1, -1)
DEFAULT_START = "2026-08-04"    # первые полные и широкие сутки записи
DEFAULT_TAKE = 38               # имён в срезе (36 по сетке + BTC и ETH)

MAKER_BP = PV.MAKER_BP
TAKER_BP = PV.TAKER_BP


def day_hours(day):
    """27 ключей часов: последний час прошлых суток + 24 + 2 следующих.

    Час назад нужен состоянию первого момента (00:00 − STATE_SEC), два
    часа вперёд — оценке последнего (23:00 + T=900 + HORIZON_SEC).
    """
    t = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    t0g = int(t.timestamp()) - 3600
    hours = [(t + timedelta(hours=h - 1)).strftime("%Y-%m-%d-%H")
             for h in range(27)]
    return hours, t0g


def band_of(z):
    """Полоса состояния по z; границы — Z_EDGES."""
    k = 0
    for e in Z_EDGES:
        if z >= e:
            k += 1
    return k


def pick_symbols(root, take):
    """Срез имён: пересечение книги и ленты, минус не-крипто.

    Стратификация по алфавиту (каждое k-е) ≈ случайная и не смещена по
    обороту; BTC и ETH входят принудительно — у них тема в 200 уровней
    и самая плотная книга, ровный шаг по алфавиту их уже пропускал
    (урок bench_ladder).
    """
    b = os.path.join(root, "book")
    tr = os.path.join(root, "trades")
    if not (os.path.isdir(b) and os.path.isdir(tr)):
        return []
    syms = sorted(set(os.listdir(b)) & set(os.listdir(tr)))
    ref = UF.non_crypto_set()
    syms = [s for s in syms if not UF.is_non_crypto(s, ref)]
    must = [s for s in ("BTCUSDT", "ETHUSDT") if s in syms]
    rest = [s for s in syms if s not in must]
    need = max(0, take - len(must))
    if need and rest:
        k = max(1, len(rest) // need)
        rest = rest[::k][:need]
    else:
        rest = []
    return sorted(must + rest)


def eval_moment(mid, bid, ask, bsz, asz, nxt, tt, tp, tv, tside,
                i0, side, wait, arm, size_usd=SIZE_USD):
    """Выгода пассивной руки против тейкера в одном моменте.

    Возвращает `(filled, wait_sec, benefit_bp, drift_bp)` либо `None`,
    когда точка оценки или доисполнения не существует (дыра записи):
    пропуск, а не ноль — у пропуска нет величины.
    """
    iH = int(D.first_at_or_after(nxt, np.array([i0 + HORIZON_SEC]),
                                 REF_TOL)[0])
    iT = int(D.first_at_or_after(nxt, np.array([i0 + wait]), REF_TOL)[0])
    if iH < 0 or iT < 0:
        return None
    b, a = float(bid[i0]), float(ask[i0])
    m0, mH = float(mid[i0]), float(mid[iH])
    taker_px = a if side > 0 else b
    v_tk = side * (mH - taker_px) / m0 * 1e4 - TAKER_BP
    if arm == 0:
        limit = b if side > 0 else a
        queue = float(bsz[i0]) if side > 0 else float(asz[i0])
    else:
        limit, queue = m0, 0.0
    if not (limit > 0 and queue >= 0 and np.isfinite(queue)):
        return None
    w = PV.fill_at(tt, tp, tv, tside, float(i0), limit, queue,
                   size_usd / limit, wait=wait, side=side)
    if w is not None:
        v_mk = side * (mH - limit) / m0 * 1e4 - MAKER_BP
    else:
        px2 = float(ask[iT]) if side > 0 else float(bid[iT])
        if not (np.isfinite(px2) and px2 > 0):
            return None
        v_mk = side * (mH - px2) / m0 * 1e4 - TAKER_BP
    drift = side * (float(mid[iT]) - m0) / m0 * 1e4
    return (w is not None, w, v_mk - v_tk, drift)


def measure_symbol(root, sym, days, counters, min_obs=None,
                   size_usd=SIZE_USD):
    """События одного имени за все сутки. σ копится причинно.

    σ пересчитывается раз в сутки по доходностям ПРОШЛЫХ суток: момент
    не видит ни своих суток, ни соседних часов того же дня — правило
    «порог из будущего был бы заглядыванием» (own_theta в W2).

    `min_obs` разрешается в момент вызова, а не при определении: иначе
    подмена модульной константы в тестах молча не действовала бы.
    """
    if min_obs is None:
        min_obs = MIN_SIGMA_OBS
    events = []
    hist = []
    n = 27 * 3600
    for day in days:
        hours, t0g = day_hours(day)
        bid, ask, bsz, asz = PV.book_grids(root, sym, hours, t0g, n)
        mid = np.where(np.isfinite(bid) & np.isfinite(ask),
                       (bid + ask) / 2.0, np.nan)
        _, nxt = D.fill_index(mid)
        tt, tp, tv, tside = PV.trade_arrays(root, sym, hours, t0g)
        sigma = float(np.std(hist)) if len(hist) >= min_obs else None
        day_mids = []
        for k in range(25):
            j = 3600 + k * 3600
            i = int(D.first_at_or_after(nxt, np.array([j]), SNAP_TOL)[0])
            day_mids.append(float(mid[i]) if i >= 0 else None)
        for k in range(24):
            j = 3600 + k * 3600
            i0 = int(D.first_at_or_after(nxt, np.array([j]), SNAP_TOL)[0])
            if i0 < 0:
                counters["нет якорного снимка"] += 1
                continue
            im1 = int(D.first_at_or_after(
                nxt, np.array([i0 - STATE_SEC]), REF_TOL)[0])
            if im1 < 0:
                counters["нет точки состояния"] += 1
                continue
            b, a = float(bid[i0]), float(ask[i0])
            if not (b > 0 and a > 0 and a >= b):
                counters["кривые уровни"] += 1
                continue
            if sigma is None:
                counters["нет σ (мало истории)"] += 1
                continue
            m0 = float(mid[i0])
            ret = m0 / float(mid[im1]) - 1.0
            if sigma <= 0:
                counters["нет σ (замороженный ряд)"] += 1
                continue
            band = band_of(ret / sigma)
            spread_bp = (a - b) / m0 * 1e4
            he = t0g + j
            for side in SIDES:
                for wait in WAITS:
                    for arm in range(len(ARMS)):
                        got = eval_moment(mid, bid, ask, bsz, asz, nxt,
                                          tt, tp, tv, tside, i0, side,
                                          wait, arm, size_usd)
                        if got is None:
                            counters["нет точки оценки"] += 1
                            continue
                        filled, w, benefit, drift = got
                        events.append((side, band, wait, arm,
                                       1 if filled else 0,
                                       w if w is not None else float("nan"),
                                       benefit, drift, spread_bp, he))
        for p, q in zip(day_mids[:-1], day_mids[1:]):
            if p is not None and q is not None and p > 0:
                hist.append(q / p - 1.0)
        del bid, ask, bsz, asz, mid, nxt, tt, tp, tv, tside
    return events


def _ep_median(vals, hours):
    """Медиана почасовых медиан: час — один голос, не одно имя."""
    by = {}
    for v, h in zip(vals, hours):
        by.setdefault(h, []).append(v)
    per = [float(np.median(v)) for v in by.values()]
    return (round(float(np.median(per)), 2), len(per),
            round(float(np.mean(np.array(per) > 0)), 3))


def summarise(events):
    """Свод по ячейкам (сторона, полоса, T, рука)."""
    cells = {}
    for e in events:
        cells.setdefault(e[:4], []).append(e)
    out = {}
    for key, rows in sorted(cells.items()):
        side, band, wait, arm = key
        fills = [r for r in rows if r[4]]
        ben = [r[6] for r in rows]
        hrs = [r[9] for r in rows]
        drift_all = [r[7] for r in rows]
        drift_f = [r[7] for r in fills]
        ep, n_ep, share = _ep_median(ben, hrs)
        rec = {
            "n": len(rows), "filled": len(fills),
            "fill_rate": round(len(fills) / len(rows), 3),
            "wait_median": (round(float(np.median(
                [r[5] for r in fills])), 1) if fills else None),
            "benefit_ep_bp": ep, "episodes": n_ep,
            "share_pos_ep": share,
            "benefit_ev_bp": round(float(np.median(ben)), 2),
            "adverse_bp": (round(float(np.median(drift_f))
                           - float(np.median(drift_all)), 2)
                           if fills else None),
            "spread_med_bp": round(float(np.median(
                [r[8] for r in rows])), 2),
        }
        out["|".join(map(str, key))] = rec
    return out


def headline(events):
    """Главная ячейка сводки, объявлена до прогона: полоса «спокойно»,
    T = 60 с, рука «на лучшей», обе стороны вместе, счёт по эпизодам."""
    rows = [e for e in events
            if e[1] == CALM_BAND and e[2] == WAITS[0] and e[3] == 0]
    if not rows:
        return None
    ep, n_ep, share = _ep_median([r[6] for r in rows],
                                 [r[9] for r in rows])
    fills = [r for r in rows if r[4]]
    drift_all = [r[7] for r in rows]
    drift_f = [r[7] for r in fills]
    return {
        "benefit_ep_bp": ep, "episodes": n_ep, "share_pos_ep": share,
        "n": len(rows),
        "fill_rate": round(len(fills) / len(rows), 3),
        "adverse_bp": (round(float(np.median(drift_f))
                       - float(np.median(drift_all)), 2)
                       if fills else None),
        "spread_med_bp": round(float(np.median([r[8] for r in rows])), 2),
    }


def verdict_phrase(h):
    """Фраза выводится ИЗ числа, а не стоит рядом с ним (урок Z2)."""
    if h is None or h.get("benefit_ep_bp") is None:
        return "спокойная полоса не измерена — фразы нет"
    v = h["benefit_ep_bp"]
    if v > 0:
        return (f"в спокойный час лимитка на лучшей ПЛАТИТ: "
                f"{v:+.1f} б.п. выгоды против тейкерского входа "
                f"(медиана по эпизодам)")
    return (f"в спокойный час лимитка на лучшей НЕ платит: "
            f"{v:+.1f} б.п. против тейкерского входа — отбор съедает "
            f"экономию спреда и комиссии")


def report(art, path):
    a = art
    L = ["# Зонд: пассивный вход в спокойном рынке\n",
         f"Прогон: {a['run_at']}. Зонд, не гипотеза: порогов нет, "
         "решение по таблице за владельцем.\n",
         f"- суток: **{a['days']}** ({a['day_first']} … {a['day_last']}), "
         f"имён: **{a['symbols']}**, записей: **{a['events']}**",
         f"- нога ${SIZE_USD:.0f}, ожидания {list(WAITS)} с, оценка всех "
         f"рук в одной точке через {HORIZON_SEC} с; недоисполненное "
         f"доисполняется тейкером в конце ожидания",
         f"- ставки: мейкер {MAKER_BP}, тейкер {TAKER_BP} б.п.; выгода — "
         f"в б.п. нотионала ноги, экономия и цена отбора В ОДНОМ числе\n",
         f"**{a['verdict']}**\n",
         "Контекст для сравнения: в СТРЕССЕ (D1, события каскадов) "
         "исполнение было 0.42–0.44, а отбор −54.7 б.п. — переворот "
         "знака. Числа взяты из закрытого отчёта D1-passive и не "
         "пересчитываются здесь.\n"]
    h = a.get("headline")
    if h:
        L += ["## 1. Главная ячейка (объявлена до прогона)\n",
              "Полоса «спокойно», ожидание 60 с, рука «на лучшей», обе "
              "стороны, счёт по эпизодам (час — один голос).\n",
              f"- выгода: **{h['benefit_ep_bp']:+.2f} б.п.** на "
              f"{h['episodes']} эпизодах, доля часов в плюс "
              f"{h['share_pos_ep']:.3f}",
              f"- исполнение {h['fill_rate']:.3f}, отбор "
              f"{h['adverse_bp'] if h['adverse_bp'] is not None else '—'}"
              f" б.п., медиана спреда {h['spread_med_bp']:.2f} б.п.",
              f"- потолок выгоды при нулевом отборе ≈ спред + "
              f"{TAKER_BP - MAKER_BP:.1f} б.п. комиссии = "
              f"{h['spread_med_bp'] + TAKER_BP - MAKER_BP:.1f} б.п.; "
              f"разница с фактом и есть цена отбора\n"]
    for arm in range(len(ARMS)):
        L += [f"## {2 + arm}. Рука «{ARMS[arm]}»\n",
              "| сторона | полоса | T, с | n | исполн. | ждали, с | "
              "выгода (эп.) | доля>0 | эп. | отбор | спред |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for side in SIDES:
            for band in range(len(BAND_NAMES)):
                for wait in WAITS:
                    r = a["summary"].get(
                        f"{side}|{band}|{wait}|{arm}")
                    nm = "покупка" if side > 0 else "продажа"
                    if r is None:
                        L.append(f"| {nm} | {BAND_NAMES[band]} | {wait} "
                                 f"| 0 | — | — | — | — | — | — | — |")
                        continue
                    d = lambda v, f: "—" if v is None else format(v, f)
                    L.append(
                        f"| {nm} | {BAND_NAMES[band]} | {wait} | "
                        f"{r['n']} | {r['fill_rate']:.3f} | "
                        f"{d(r['wait_median'], '.0f')} | "
                        f"{r['benefit_ep_bp']:+.2f} | "
                        f"{r['share_pos_ep']:.3f} | {r['episodes']} | "
                        f"{d(r['adverse_bp'], '+.1f')} | "
                        f"{r['spread_med_bp']:.2f} |")
        L.append("")
    L += ["## Пропуски\n"]
    for k, v in sorted(a["skipped"].items()):
        L.append(f"- {k}: {v}")
    L += ["", "## Оговорки, не снимаемые замером\n",
          "- отмены заявок не видны, очередь — размер уровня в момент "
          "постановки; работает ПРОТИВ пассивной руки;",
          "- своя заявка на рынок не влияет;",
          "- комиссия только на входе: выход у всех рук один и тот же "
          "условный (середина в общей точке) и в разности сокращается — "
          "мера сравнивает ВХОДЫ;",
          "- запись — недели одного режима рынка; σ причинная по "
          "прошлым суткам, первые ~2 суток каждого имени не меряются;",
          "- срез имён, не весь универсум: стратификация по алфавиту "
          "плюс BTC и ETH принудительно."]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--days", type=int, default=0,
                    help="последние N суток вместо всех")
    ap.add_argument("--take", type=int, default=DEFAULT_TAKE)
    ap.add_argument("--symbols", action="append", default=None,
                    help="явный список имён (для смоука)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="1s")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    syms = a.symbols or pick_symbols(a.root, a.take)
    _, hours = R.available(os.path.join(a.root, "book"))
    days = sorted({h[:10] for h in hours})
    days = [d for d in days if d >= a.start]
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи после {a.start}")
    print(f"имён {len(syms)}, суток {len(days)} "
          f"({days[0]} … {days[-1]}), памяти свободно "
          f"{R.mem_available_mb():.0f} МБ")

    counters = {k: 0 for k in (
        "нет якорного снимка", "нет точки состояния", "кривые уровни",
        "нет σ (мало истории)", "нет σ (замороженный ряд)",
        "нет точки оценки")}
    events, t_start = [], time.time()
    for i, sym in enumerate(syms):
        got = measure_symbol(a.root, sym, days, counters)
        events += got
        print(f"  {i + 1}/{len(syms)} {sym}: записей {len(got)}, всего "
              f"{len(events)}, {(time.time() - t_start) / 60:.1f} мин")
    if not events:
        raise SystemExit("записей нет — см. счётчики пропусков")

    h = headline(events)
    art = {
        "run_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "days": len(days), "day_first": days[0], "day_last": days[-1],
        "symbols": len(syms), "events": len(events),
        "size_usd": SIZE_USD, "waits": list(WAITS),
        "horizon_sec": HORIZON_SEC,
        "maker_bp": MAKER_BP, "taker_bp": TAKER_BP,
        "headline": h, "verdict": verdict_phrase(h),
        "summary": summarise(events), "skipped": counters,
        "took_min": round((time.time() - t_start) / 60, 1),
    }
    p = os.path.join(a.out, f"CALM-exec-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"CALM-exec-{a.tag}.md"))
    print(f"готово: {p}")
    print(f"  {art['verdict']}")
    if not a.no_publish:
        R.publish(f"зонд пассивного входа в спокойном рынке ({a.tag})")


if __name__ == "__main__":
    main()
