#!/usr/bin/env python3
"""
Механика 994fc54f — поглощение после падения со ЗНАМЕНАТЕЛЕМ.

Что проверяется
---------------

Событие, удержание и мера — дословно ячейка вердикта спеки 11: падение
середины на 3 % за 15 минут, удержание 30 минут, превышение над
ОДНОВРЕМЕННОЙ кросс-секцией, медиана и среднее по эпизодам. Меняется
одно: вход обусловлен ответом книги.

В момент `MARK_DELAY_SEC` после решения фиксируется лучший бид и его
показанный размер — это ОЧЕРЕДЬ. Дальше `T_SEC` секунд по ленте с
агрессором считается, прошло ли сквозь этот уровень продающей агрессии
больше, чем очередь плюс наш размер. Прошло — «бид выеден», входа нет.
Не прошло — «бид пережил минуту», вход тейкером.

Чем это отличается от четырёх замеров ленты (T1–T4). Те брали
поглощение безусловным триггером по всему универсуму и считали
ЧИСЛИТЕЛЬ — сколько агрессии прошло. Знаменателя (сколько было
показано) у них не было вовсе, и все четыре дали ноль. Здесь
знаменатель — показанная очередь, а условие применяется только после
падения на 3 %, то есть в состоянии, где ответ книги что-то значит.

Откуда взялось утверждение
--------------------------

Из нашего же замера `research/d1_seconds/out/D1-passive-1m.md`: при доле
исполнения 0.419 исполненные дали −28.8 б.п. против +25.9 по всей
выборке. Разложение среднего даёт центр НЕисполненных около +65 б.п.
Исполнение пассивной покупки и есть «сквозь бид прошло больше, чем
стояло», то есть переменная уже измерена — но читалась она как цена
неблагоприятного отбора, а не как признак состояния.

Почему вход НЕ на шестидесятой секунде
--------------------------------------

Заявка объявила вход в `δ = 60 с`, а метку — по потоку за 60 секунд от
пятой, то есть по данным до 65-й. Это заглядывание на пять секунд, и
молча выбрать «как объявлено» нельзя: ровно этот класс дефекта в
проекте ловился десяток раз. Поэтому вход считается не раньше, чем
метка становится известна (`entry_wait`), и это отступление названо в
отчёте числом. Направление отступления против гипотезы: вход позже —
отскока меньше, — значит порог 52.2 б.п. остаётся годным убийцей.

Что здесь НЕ живёт
------------------

Второй копии ядра нет. События, вход, форвард, фон, эпизоды —
`research/d1_seconds/detect.py`; загрузка суток и матрица —
`run_d1.py`; модель очереди — `passive.fill_at` в измеренной
конфигурации; форма по дням — `research/factory/stability.py`; связь
дневных денег — `ceiling.pair_corr`. Здесь добавлен ровно агрегат по
двум подмножествам.

    .venv/bin/python research/mech_994fc54f/bid_survives.py --days 3
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
for _p in (os.path.join(RESEARCH, "d1_seconds"),
           os.path.join(RESEARCH, "b1_book"),
           os.path.join(RESEARCH, "factory")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import detect as D                                         # noqa: E402
import passive as PS                                       # noqa: E402
import run_d1 as R                                         # noqa: E402
import stability as SB                                     # noqa: E402
import ceiling as CE                                       # noqa: E402

# --- объявлено ДО прогона, после результата не меняется ----------------
DROP = 0.03                    # событие: падение середины за 15 минут
HORIZON_SEC = 30 * 60          # удержание объявленной ячейки
MARK_DELAY_SEC = 5             # когда фиксируется бид и его очередь
T_SEC = 60                     # сколько ждём поток сквозь уровень
DECLARED_ENTRY_SEC = 60        # вход, как его объявила заявка
NEED_BP = 52.2                 # валовое превышение, ниже — закрыто
SHARE_POS_MIN = 0.60           # доля прибыльных эпизодов, критерий 2
MIN_EPISODES = 300             # бюджет доказательства, §7 п.5 спеки 11
NULL_PERMS = 200               # перестановок метки внутри суток
NULL_SEED = 20260905           # зерно ЧИСЛОМ: hash строки солится
MAX_BITE = SB.PL.MAX_BITE      # укус: порог берётся у правила вылета
MIN_TRADE_DAY_SHARE = 0.33     # измеримость формы, третья величина потолка
MAX_LIVE_CORR = CE.MAX_CORR    # предел связи, каким его держит пул
EXPECTED_LIVE_CORR = 0.30      # ожидание заявки, объявлено до прогона
SLOTS = 6                      # мест в книге
NAME_CAP = 0.10                # потолок на имя, доля капитала
DIAG_T_SEC = (15, 30)          # диагностика: другие окна потока
DIAG_HORIZONS = (5 * 60, 15 * 60)   # диагностика: другие удержания
DIAG_DROP = 0.05               # диагностика: более резкое падение
BTC = "BTCUSDT"                # нога диагностического хеджа

LABELS = ("пережил", "выеден")
DAY_SEC = 86400


def entry_wait(mark_delay=MARK_DELAY_SEC, t_sec=T_SEC,
               declared=DECLARED_ENTRY_SEC):
    """Через сколько секунд после решения возможен вход.

    Метка «выеден/пережил» завершена в `mark_delay + t_sec`, и раньше
    этого момента её не существует. Объявленные заявкой 60 секунд
    меньше 65 — вход по ним торговал бы знанием, которого в тот момент
    нет. Берётся ПОЗДНЕЕ из двух: правило, разрешающее вход раньше
    метки, есть заглядывание в будущее.
    """
    return int(max(int(declared), int(mark_delay) + int(t_sec)))


ENTRY_SEC = entry_wait()


def flow_through(tt, tp, tv, tside, t_place, limit, t_sec=T_SEC):
    """Продающая агрессия сквозь уровень `limit` за `t_sec` секунд.

    Числитель поглощения. Знаменатель — показанная очередь; решение о
    метке принимает НЕ эта функция, а `PS.fill_at`, чтобы правило
    исполнения осталось в одном месте. Совпадение двух путей
    («поток ≥ очередь + размер» тогда и только тогда, когда заявка
    исполнилась) закреплено тестом: разойдясь, они дали бы метку по
    одному правилу и диагностику по другому.
    """
    if len(tt) == 0:
        return 0.0
    lo = int(np.searchsorted(tt, float(t_place), side="right"))
    hi = int(np.searchsorted(tt, float(t_place) + int(t_sec), side="right"))
    if hi <= lo:
        return 0.0
    m = (tside[lo:hi] < 0) & (tp[lo:hi] <= float(limit))
    return float(np.sum(tv[lo:hi][m])) if m.any() else 0.0


def mark_event(tt, tp, tv, tside, j, limit, queue, size, t_sec=T_SEC,
               mark_delay=MARK_DELAY_SEC):
    """Метка события: `пережил` либо `выеден`, и когда именно выеден.

    Считает `PS.fill_at` в измеренной конфигурации (`SIZE_USD` на ногу,
    ожидание `t_sec`): та же модель очереди, которой уже измерены −28.8
    против +25.9, а не её пересказ.
    """
    w = PS.fill_at(tt, tp, tv, tside, float(int(j) + int(mark_delay)),
                   float(limit), float(queue), float(size),
                   wait=int(t_sec))
    return ("выеден" if w is not None else "пережил"), w


def level_pulled(flow, limit, bid_after):
    """Уровень ушёл, не приняв ни одного принта.

    Модель очереди считает такое событие «пережившим» — заявка ведь не
    исполнилась, — а на деле бида на этом уровне уже нет: его сняли или
    цена ушла. Это загрязняет подмножество выживших, и отделять его
    надо явно (мера `dead` скрина лесенки — то же различие: уровень,
    умерший без единой сделки).

    `None` там, где после окна цены нет: неизмеренное не есть «не
    сняли».
    """
    if bid_after is None or not np.isfinite(bid_after):
        return None
    return bool(flow <= 0.0 and float(bid_after) < float(limit))


def bg_mean(P, NXT, row, j, delay, hor, banned, min_cross=D.MIN_CROSS):
    """Фон РАВНОВЗВЕШЕННЫМ средним, рядом с медианой D1.

    Медиана сечения — статистика, а не портфель: захеджировать об неё
    нельзя, и у скошенного вправо распределения доходностей случайная
    длинная нога даёт превышение над медианой по построению (замер
    `research/z1_screen/out/Z1-screen-1m.md`). Поэтому обе величины
    печатаются рядом, а решает согласие знаков.

    Фон тоньше пола — **не измеряется, а не ноль**: тот же порог, что у
    ядра, и берётся он у ядра.
    """
    rr = D.returns_matrix(P, NXT, int(j), int(delay), int(hor))
    bg = np.array(rr, copy=True)
    bg[int(row)] = np.nan
    if banned is not None:
        bg[np.asarray(banned, dtype=bool)] = np.nan
    v = bg[np.isfinite(bg)]
    if len(v) < int(min_cross):
        return float("nan")
    return float(np.mean(v))


def _episode_values(rows, key):
    """Значения ключа по эпизодам: одно рыночное окно — один голос."""
    x = np.array([r[key] for r in rows], dtype=np.float64)
    t = np.array([r["t"] for r in rows], dtype=np.float64)
    ok = np.isfinite(x)
    if not ok.any():
        return np.empty(0)
    ep = D.episodes(t[ok])
    return D.by_episode(x[ok], ep)


def group_stats(rows, key="exc_med"):
    """Сводка подмножества: медиана и среднее ПО ЭПИЗОДАМ.

    Обвал накрывает рынок целиком, и сотня событий одной минуты — одно
    наблюдение, а не сто. Считать событиями значило бы подделать бюджет
    доказательства.
    """
    if not rows:
        return {"events": 0, "episodes": 0, "median_bp": None,
                "mean_bp": None, "share_pos": None, "names": 0}
    vals = _episode_values(rows, key)
    if len(vals) == 0:
        return {"events": len(rows), "episodes": 0, "median_bp": None,
                "mean_bp": None, "share_pos": None,
                "names": len({r["sym"] for r in rows})}
    return {
        "events": len(rows),
        "episodes": int(len(vals)),
        "median_bp": round(float(np.median(vals)) * 1e4, 2),
        "mean_bp": round(float(np.mean(vals)) * 1e4, 2),
        "share_pos": round(float(np.mean(vals > 0)), 3),
        "names": len({r["sym"] for r in rows}),
    }


def by_label(rows, field="label", key="exc_med"):
    """Сводка по обеим меткам разом."""
    return {lab: group_stats([r for r in rows if r.get(field) == lab], key)
            for lab in LABELS}


def ceiling_bp(split):
    """Верхняя граница: лучшее подмножество ПРИ ИДЕАЛЬНОМ ЗНАНИИ.

    Считается первой и закрывает направление одна: если даже
    всеведущий выбор между «пережил» и «выеден» не достаёт до порога,
    остальные шаги считать незачем. Приём S1 — потолок рычагов, — он
    там закрыл три направления за вечер.
    """
    vals = [g["median_bp"] for g in split.values()
            if g.get("median_bp") is not None]
    if not vals:
        return None
    return max(vals)


def null_permutation(rows, key="exc_med", perms=NULL_PERMS, seed=NULL_SEED):
    """Нуль: метка переставляется между событиями ТЕХ ЖЕ суток.

    Внутри суток, а не по всей выборке: рынок ходит эпизодами, и
    глобальная перестановка смешала бы спокойные сутки с обвальными —
    тогда нуль отвечал бы на «различаются ли сутки», а спрашивают его о
    метке.

    Зерно — ЧИСЛО, не `hash` строки: хеш солится на каждый процесс, и
    нуль, который нельзя повторить, проверяемым не является (дефект R3).
    """
    if not rows:
        return {"perms": 0, "pct95_bp": None, "mean_bp": None, "sd_bp": None}
    groups = _by_day(rows)              # перестановка идёт ВНУТРИ суток
    labs = np.array([r["label"] for r in rows], dtype=object)
    got = []
    for p in range(int(perms)):
        rng = np.random.default_rng(int(seed) + p)
        shuffled = labs.copy()
        for _day, idx in sorted(groups.items()):
            take = np.array(idx, dtype=np.int64)
            shuffled[take] = labs[rng.permutation(take)]
        sub = [dict(r, _null=str(shuffled[i]))
               for i, r in enumerate(rows)]
        g = group_stats([r for r in sub if r["_null"] == "пережил"], key)
        if g["median_bp"] is not None:
            got.append(g["median_bp"])
    if not got:
        return {"perms": int(perms), "pct95_bp": None, "mean_bp": None,
                "sd_bp": None}
    a = np.array(got, dtype=np.float64)
    return {"perms": int(len(a)),
            "pct95_bp": round(float(np.percentile(a, 95)), 2),
            "mean_bp": round(float(np.mean(a)), 2),
            "sd_bp": round(float(np.std(a)), 2)}


def _by_day(rows):
    out = {}
    for i, r in enumerate(rows):
        out.setdefault(r.get("day"), []).append(i)
    return out


def replay_days(rows, key="own", cost_bp=None, slots=SLOTS,
                name_cap=NAME_CAP, hold=HORIZON_SEC):
    """Книга по дням: `{номер суток: нетто в % капитала}`.

    Шесть мест, одна позиция на имя, равный доллар, потолок на имя
    `name_cap` — гросс не выше `slots × name_cap`. Ключ суток — номер
    суток от эпохи по МОМЕНТУ ВЫХОДА, ровно как его кладёт
    `candidate.daily_net`: иначе ряд нельзя ни сравнить с живыми
    книгами, ни отдать правилу вылета.
    """
    if cost_bp is None:
        cost_bp = COST_ROUND_BP
    daily, open_pos = {}, []
    for r in sorted(rows, key=lambda e: e["t"]):
        if not np.isfinite(r.get(key, np.nan)):
            continue
        t_in = float(r["t"]) + ENTRY_SEC
        open_pos = [p for p in open_pos if p[0] > t_in]
        if len(open_pos) >= int(slots):
            continue
        if r["sym"] in {p[1] for p in open_pos}:
            continue
        t_out = t_in + float(hold)
        open_pos.append((t_out, r["sym"]))
        net = float(name_cap) * (float(r[key]) - float(cost_bp) / 1e4) * 100.0
        daily[int(t_out // DAY_SEC)] = daily.get(
            int(t_out // DAY_SEC), 0.0) + net
    return daily


def form_stats(daily):
    """Форма книги по суткам — ОБЩЕЙ мерой проекта.

    `stability.stats` считает медиану дня, худший день, укус и просадку
    для живых книг пула и для реплеев. Второй реализации здесь нет
    намеренно: разойдясь, отчёт говорил бы одно, а правило вылета
    судило бы другое.
    """
    s = SB.stats(daily)
    if not s:
        return None
    return dict(s)


def trade_day_share(daily, days_total):
    """Доля суток записи, в которые книга хоть раз закрывала сделку.

    Третья величина потолка: правило вылета судит по СУТКАМ, и
    кандидат, закрывающий сделки залпом в редкие дни, по форме
    неизмерим при любой скорости сделок, а слот занимает.
    """
    if not days_total:
        return None
    return round(len([d for d in daily if abs(daily[d]) > 0]) / days_total, 3)


def live_corr(daily, path):
    """Связь дневных денег реплея с живыми книгами пула.

    Считается `ceiling.pair_corr` — тем же кодом, которым потолок судит
    независимость заявки. Возвращает (худшая связь, ключ, суток) или
    (None, None, 0), если сравнивать не с чем: `None` печатается
    прочерком, ноль читался бы как «измерено и книги независимы».
    """
    if not os.path.exists(path):
        return None, None, 0
    try:
        art = json.load(open(path, encoding="utf-8"))
    except (ValueError, OSError):
        return None, None, 0
    mine = {int(d): v for d, v in daily.items()}
    best, who, n = None, None, 0
    for cid, rec in (art.get("candidates") or {}).items():
        other = {int(d): float(v)
                 for d, v in (rec.get("daily") or {}).items()}
        r, k = CE.pair_corr(mine, other)
        if r is None:
            continue
        if best is None or abs(r) > abs(best):
            best, who, n = r, cid, k
    return best, who, n


# Круг издержек берётся ИЗМЕРЕННЫЙ по нашей же записи, а не назначенный:
# комиссия плюс половина спреда на входе и половина на выходе. Число
# читает `run_d1.cost_round` из артефакта проверки по ленте; своего
# числа здесь нет.
COST_ROUND_BP, COST_SRC = R.cost_round(
    os.path.join(RESEARCH, "d1_seconds", "out"), "1m")


def measure_day(root, syms, day, jobs, last_seen, log=print):
    """События суток с меткой поглощения и превышением по ячейкам."""
    P, t0, n = R.load_day(os.path.join(root, "book"), syms, day, jobs, log)
    NXT = R.next_index(P)
    btc_row = syms.index(BTC) if BTC in syms else None
    ev = {}
    for drop in (DROP, DIAG_DROP):
        rows, cols = R.events_of_day(P, t0, drop, last_seen.setdefault(
            drop, {}), R.PAD_SEC, R.PAD_SEC + R.DAY_SEC)
        ev[drop] = list(zip([int(x) for x in rows], [int(x) for x in cols]))
        log(f"    падение {int(drop * 100)} %: событий {len(rows)}")
    if not any(ev.values()):
        del P, NXT
        return []

    hours = R.hours_of(t0, n)
    by_sym = {}
    for drop, pairs in ev.items():
        for r, j in pairs:
            by_sym.setdefault(r, []).append((drop, j))
    recs = {}
    for k, (r, items) in enumerate(sorted(by_sym.items())):
        sym = syms[r]
        bid, ask, bsz, _asz = PS.book_grids(root, sym, hours, t0, n)
        _bprev, bnxt = D.fill_index(bid)
        tt, tp, tv, tside = PS.trade_arrays(root, sym, hours, t0)
        for drop, j in items:
            i_mark = int(D.first_at_or_after(
                bnxt, np.array([j + MARK_DELAY_SEC]), D.FILL_WAIT_SEC)[0])
            if i_mark < 0:
                continue
            limit, q = float(bid[i_mark]), float(bsz[i_mark])
            if not (limit > 0 and q > 0):
                continue
            size = PS.SIZE_USD / limit
            lab, when = mark_event(tt, tp, tv, tside, j, limit, q, size)
            flow = flow_through(tt, tp, tv, tside,
                                float(j + MARK_DELAY_SEC), limit)
            # Та же метка с очередью БЕЗ нашего размера: если разрез не
            # меняется, показанный размер ноги в нём ничего не решает.
            lab0, _ = mark_event(tt, tp, tv, tside, j, limit, q, 0.0)
            i_after = int(D.first_at_or_after(
                bnxt, np.array([j + MARK_DELAY_SEC + T_SEC]),
                D.FILL_WAIT_SEC)[0])
            pulled = level_pulled(
                flow, limit, float(bid[i_after]) if i_after >= 0 else None)
            i_in = int(D.first_at_or_after(
                bnxt, np.array([j + ENTRY_SEC]), D.FILL_WAIT_SEC)[0])
            # Голый путь цены: та же развилка без всякой книги — упала
            # ли середина ещё и между меткой и входом.
            path_hold = (bool(P[r, i_in] >= P[r, i_mark])
                         if i_in >= 0 and np.isfinite(P[r, i_in])
                         and np.isfinite(P[r, i_mark]) else None)
            rec = {"sym": sym, "row": r, "t": t0 + j, "day": day,
                   "drop": drop, "label": lab, "label_size0": lab0,
                   "eaten_at": when, "flow": flow, "queue": q,
                   "limit": limit, "pulled": pulled,
                   "path_hold": path_hold,
                   "spread_bp": ((float(ask[i_mark]) - limit)
                                 / ((float(ask[i_mark]) + limit) / 2) * 1e4
                                 if float(ask[i_mark]) > 0 else None)}
            for t_alt in DIAG_T_SEC:
                rec[f"label_T{t_alt}"] = mark_event(
                    tt, tp, tv, tside, j, limit, q, size, t_sec=t_alt)[0]
            recs.setdefault(drop, []).append(rec)
        if (k + 1) % 25 == 0:
            log(f"    размечено {k + 1}/{len(by_sym)} имён")

    out = []
    horizons = sorted({HORIZON_SEC, *DIAG_HORIZONS},
                      key=lambda h: D.guard_sec(ENTRY_SEC, h))
    for drop, rr in sorted(recs.items()):
        rows = np.array([e["row"] for e in rr], dtype=np.int64)
        cols = np.array([int(e["t"] - t0) for e in rr], dtype=np.int64)
        for hor in horizons:
            g = D.guard_sec(ENTRY_SEC, hor)
            ban = D.guard_matrix(P.shape, rows, cols, g)
            log(f"    падение {int(drop * 100)} %, удержание {hor // 60} "
                f"мин: защитное окно {g} с")
            for e in rr:
                j = int(e["t"] - t0)
                own, _bg, exc, width = D.excess(
                    P, NXT, e["row"], j, ENTRY_SEC, hor, ban[:, j])
                mean_bg = bg_mean(P, NXT, e["row"], j, ENTRY_SEC, hor,
                                  ban[:, j])
                suf = "" if hor == HORIZON_SEC else f"_h{hor // 60}"
                e["own" + suf] = own
                e["exc_med" + suf] = exc
                e["exc_mean" + suf] = (own - mean_bg
                                       if np.isfinite(mean_bg)
                                       and np.isfinite(own)
                                       else float("nan"))
                e["width" + suf] = width
                if hor == HORIZON_SEC and btc_row is not None:
                    rrow = D.returns_matrix(P, NXT, j, ENTRY_SEC, hor)
                    b = float(rrow[btc_row])
                    e["own_hedged"] = (own - b if np.isfinite(b)
                                       and np.isfinite(own)
                                       else float("nan"))
            del ban
        out += rr
    del P, NXT
    return out


def summarise(rows, days_total, live_path):
    """Все числа отчёта. Порядок — от самого дешёвого убийцы к прочим."""
    main = [e for e in rows if e["drop"] == DROP]
    split = by_label(main)
    split_mean = by_label(main, key="exc_mean")
    surv = [e for e in main if e["label"] == "пережил"]
    daily = replay_days(surv)
    daily_h = replay_days(surv, key="own_hedged",
                          cost_bp=COST_ROUND_BP + R.COMMISSION_BP)
    corr, who, corr_days = live_corr(daily, live_path)
    art = {
        "events": len(main),
        "events_all": len(rows),
        "entry_sec": ENTRY_SEC,
        "declared_entry_sec": DECLARED_ENTRY_SEC,
        "cost_round_bp": round(COST_ROUND_BP, 2),
        "cost_src": COST_SRC,
        "split": split,
        "split_mean": split_mean,
        "ceiling_bp": ceiling_bp(split),
        "null": null_permutation(main),
        "attribution": {
            "путь цены": by_label(
                [dict(e, _p=("пережил" if e["path_hold"] else "выеден"))
                 for e in main if e["path_hold"] is not None], field="_p"),
            "очередь без нашего размера": by_label(
                [dict(e, _p=e["label_size0"]) for e in main], field="_p"),
        },
        "pulled": {
            "среди выживших": len([e for e in surv if e["pulled"]]),
            "выживших": len(surv),
            "без снятых": group_stats(
                [e for e in surv if e["pulled"] is False]),
            "снятые без принта": group_stats(
                [e for e in surv if e["pulled"]]),
        },
        "form": {
            "голая нога": form_stats(daily),
            "с хеджем BTC": form_stats(daily_h),
            "суток со сделками": trade_day_share(daily, days_total),
            "дней": len(daily),
        },
        "daily": {str(k): round(v, 4) for k, v in sorted(daily.items())},
        "live_corr": None if corr is None else round(corr, 3),
        "live_corr_with": who,
        "live_corr_days": corr_days,
        "diagnostics": diagnostics(rows),
    }
    art["killers"] = killers(art)
    art["reading"] = reading(art)
    return art


def diagnostics(rows):
    """Ячейки, которые считаются рядом и предъявлять которые запрещено."""
    main = [e for e in rows if e["drop"] == DROP]
    out = {}
    for t_alt in DIAG_T_SEC:
        out[f"поток за {t_alt} с"] = by_label(
            [dict(e, _p=e[f"label_T{t_alt}"]) for e in main], field="_p")
    for hor in DIAG_HORIZONS:
        out[f"удержание {hor // 60} мин"] = by_label(
            main, key=f"exc_med_h{hor // 60}")
    out[f"падение {int(DIAG_DROP * 100)} %"] = by_label(
        [e for e in rows if e["drop"] == DIAG_DROP])
    if main:
        half = sorted({e["day"] for e in main})
        cut = half[len(half) // 2] if half else None
        out["первая половина записи"] = by_label(
            [e for e in main if cut is None or e["day"] < cut])
        out["вторая половина записи"] = by_label(
            [e for e in main if cut is not None and e["day"] >= cut])
    return out


def killers(art):
    """Пять убийц заявки. Каждый выводится из числа, а не из надежды."""
    out = {}
    surv, eat = art["split"]["пережил"], art["split"]["выеден"]
    sm = art["split_mean"]["пережил"]
    c = art["ceiling_bp"]
    out["1. верхняя граница"] = (
        "не измерена" if c is None else
        f"лучшее подмножество при идеальном знании {c:+.1f} б.п. при "
        f"пороге {NEED_BP:.1f} — "
        + ("СРАБОТАЛ: закрыто без второго шага" if c < NEED_BP
           else "не сработал"))
    n95 = art["null"]["pct95_bp"]
    out["2. нуль перестановки"] = (
        "не измерен" if n95 is None or surv["median_bp"] is None else
        f"выжившие {surv['median_bp']:+.1f} против 95-го процентиля нуля "
        f"{n95:+.1f} б.п. — "
        + ("СРАБОТАЛ: метка не отделяет ничего"
           if surv["median_bp"] <= n95 else "не сработал"))
    out["3. знак обратный"] = (
        "не измерен" if surv["median_bp"] is None
        or eat["median_bp"] is None else
        f"выжившие {surv['median_bp']:+.1f}, выеденные "
        f"{eat['median_bp']:+.1f} б.п. — "
        + ("СРАБОТАЛ: выеденные лучше выживших"
           if eat["median_bp"] > surv["median_bp"] else "не сработал"))
    bad_sign = (surv["median_bp"] is not None and sm["mean_bp"] is not None
                and surv["median_bp"] * sm["mean_bp"] < 0)
    low_share = (surv["share_pos"] is not None
                 and surv["share_pos"] < SHARE_POS_MIN)
    out["4. форма фейда"] = (
        "не измерена" if surv["median_bp"] is None else
        f"медиана {surv['median_bp']:+.1f}, среднее "
        f"{'—' if sm['mean_bp'] is None else format(sm['mean_bp'], '+.1f')}"
        f" б.п., доля прибыльных эпизодов "
        f"{'—' if surv['share_pos'] is None else surv['share_pos']} при "
        f"пороге {SHARE_POS_MIN} — "
        + ("СРАБОТАЛ" if bad_sign or low_share else "не сработал"))
    out["5. бюджет доказательства"] = (
        f"эпизодов у выживших {surv['episodes']} при требуемых "
        f"{MIN_EPISODES} — "
        + ("СРАБОТАЛ" if surv["episodes"] < MIN_EPISODES else "не сработал"))
    sh = art["form"]["суток со сделками"]
    out["измеримость формы"] = (
        "не измерена" if sh is None else
        f"доля суток записи со сделками {sh:.2f} при пороге "
        f"{MIN_TRADE_DAY_SHARE:.2f} — "
        + ("НЕ ПРОЙДЕНА" if sh < MIN_TRADE_DAY_SHARE else "пройдена"))
    f = art["form"]["голая нога"]
    out["форма книги"] = (
        "не измерена: суток мало" if not f or f["thin"] else
        f"медиана дня {f['med']:+.3f} %, худший день {f['worst']:+.3f} %, "
        f"укус {'—' if f['bite'] is None else f['bite']} при пределе "
        f"{MAX_BITE:.0f} — "
        + ("объявлять НЕЛЬЗЯ"
           if f["med"] < 0 or (f["bite"] is not None and f["bite"] > MAX_BITE)
           else "правило вылета проходит"))
    return out


def reading(art):
    """Вывод одной фразой. Выводится из числа, а не стоит рядом с ним."""
    c = art["ceiling_bp"]
    if c is None:
        return ("Судить нечем: превышение не измерено ни у одного "
                "подмножества — проверять надо ширину фона и запись, а "
                "не гипотезу.")
    surv = art["split"]["пережил"]
    eat = art["split"]["выеден"]
    if c < NEED_BP:
        return (f"**Закрыто первым же числом.** Лучшее подмножество при "
                f"идеальном знании даёт {c:+.1f} б.п. валовых при "
                f"требуемых {NEED_BP:.1f} (тройной круг "
                f"{art['cost_round_bp']:.1f}). Разрез книги величину "
                f"поднять не может: он только делит выборку, а верхняя "
                f"граница уже посчитана по лучшей половине.")
    n95 = art["null"]["pct95_bp"]
    if (surv["median_bp"] is not None and n95 is not None
            and surv["median_bp"] <= n95):
        return (f"Порог перебит ({c:+.1f} б.п.), но нуль перестановки не "
                f"перебит: выжившие {surv['median_bp']:+.1f} против "
                f"{n95:+.1f} б.п. у метки, переставленной внутри суток. "
                f"Переменная не отделяет ничего сверх распада по "
                f"задержке.")
    if (eat["median_bp"] is not None and surv["median_bp"] is not None
            and eat["median_bp"] > surv["median_bp"]):
        return (f"Знак обратный заявленному: выеденные "
                f"{eat['median_bp']:+.1f} против {surv['median_bp']:+.1f} "
                f"б.п. у выживших. Значит −28.8 б.п. замера D1-passive "
                f"были ценой первых секунд, а не состоянием книги.")
    return (f"Все пять убийц пройдены: выжившие "
            f"{_num(surv['median_bp'])} б.п. против "
            f"{_num(eat['median_bp'])} у выеденных, нуль "
            f"{_num(n95)}, эпизодов {surv['episodes']}. Дальше — форма "
            f"книги и решение пула, а не этого прогона.")


def _num(v, fmt="+.1f"):
    """Величины, которой нет, — прочерк. Ноль означает «измерено»."""
    return "—" if v is None else format(v, fmt)


def _split_table(L, split, title):
    L.append(f"\n### {title}\n")
    L.append("| метка | событий | эпизодов | медиана | среднее | "
             "доля > 0 | имён |")
    L.append("|---|---|---|---|---|---|---|")
    for lab in LABELS:
        g = split.get(lab) or {}
        L.append(f"| {lab} | {g.get('events', 0)} | "
                 f"{g.get('episodes', 0)} | "
                 f"{_num(g.get('median_bp'))} б.п. | "
                 f"{_num(g.get('mean_bp'))} б.п. | "
                 f"{_num(g.get('share_pos'), '.3f')} | "
                 f"{g.get('names', 0)} |")


def report(art, path):
    a = art
    L = ["# Механика 994fc54f — поглощение после падения\n",
         f"Прогон: {a['run_at']}. Заявка предлагающего, потолок.\n",
         "Событие и мера — ячейка вердикта спеки 11 (падение 3 % за 15 "
         "минут, удержание 30 минут, превышение над одновременной "
         "кросс-секцией). Меняется одно: вход только там, где "
         "показанный бид пережил минуту продаж.\n",
         "**Это потолок, а не вердикт.** Числа валовые там, где так "
         "написано; круг издержек назван рядом.\n",
         "## 1. Что прочитано\n",
         f"- суток записи: **{a['days']}** ({a['day_from']} … "
         f"{a['day_to']}), символов **{a['symbols']}**",
         f"- событий падения 3 %: **{a['events']}**, всего с "
         f"диагностикой {a['events_all']}",
         f"- круг издержек **{a['cost_round_bp']:.1f} б.п.** "
         f"({a['cost_src']})",
         f"- прогон занял {a['took_min']} мин\n",
         f"**Вход считается на {a['entry_sec']}-й секунде, а не на "
         f"{a['declared_entry_sec']}-й, как объявляла заявка.** Метка "
         f"по потоку за {T_SEC} с от {MARK_DELAY_SEC}-й секунды "
         f"завершена только к {MARK_DELAY_SEC + T_SEC}-й; вход раньше "
         f"торговал бы знанием, которого в тот момент нет. Отступление "
         f"работает ПРОТИВ гипотезы: вход позже — отскока меньше.\n",
         "## 2. Разрез по ответу книги\n",
         "Медиана и среднее — по эпизодам (склейка 5 минут), фон — "
         "медиана одновременной кросс-секции, как в D1.\n"]
    _split_table(L, a["split"], "Фон медианой сечения")
    _split_table(L, a["split_mean"],
                 "Фон равновзвешенным средним (медиана — статистика, "
                 "а не портфель)")
    L.append("\n## 3. Пять убийц\n")
    for k, s in a["killers"].items():
        L.append(f"- **{k}**: {s}")
    L.append("\n## 4. Нуль перестановки\n")
    n = a["null"]
    L.append(f"Метка переставлена между событиями ТЕХ ЖЕ суток, "
             f"{n['perms']} перестановок, зерно {NULL_SEED} числом. "
             f"Среднее {_num(n['mean_bp'])} б.п., разброс "
             f"{_num(n['sd_bp'], '.2f')}, 95-й процентиль "
             f"{_num(n['pct95_bp'])} б.п.\n")
    L.append("## 5. Атрибуция: а книга ли это\n")
    L.append("Если тот же разрез даёт голый путь цены, показанный "
             "размер не добавляет ничего, и механика есть "
             "«подтверждение разворота», а не поглощение.\n")
    for name, sp in a["attribution"].items():
        _split_table(L, sp, name)
    p = a["pulled"]
    L.append("\n## 6. Пережил или снят без единого принта\n")
    L.append(f"Модель очереди считает снятый уровень пережившим — "
             f"заявка ведь не исполнилась. Таких среди выживших "
             f"**{p['среди выживших']}** из {p['выживших']}.\n")
    _split_table(L, {"пережил": p["без снятых"],
                     "выеден": p["снятые без принта"]},
                 "Слева — выжившие без снятых, справа — снятые "
                 "без принта")
    L.append("\n## 7. Форма книги по суткам\n")
    L.append(f"Реплей: {SLOTS} мест, одна позиция на имя, лонг, "
             f"удержание {HORIZON_SEC // 60} минут, потолок на имя "
             f"{NAME_CAP:.0%} капитала. Единица — проценты капитала за "
             f"сутки. Хеджированная строка — диагностика формы: "
             f"вердикт по голой ноге, как в спеке 11.\n")
    L.append("| книга | суток | медиана дня | худший день | укус | "
             "просадка | прибыльных суток |")
    L.append("|---|---|---|---|---|---|---|")
    for name in ("голая нога", "с хеджем BTC"):
        f = a["form"].get(name)
        if not f:
            L.append(f"| {name} | — | — | — | — | — | — |")
            continue
        L.append(f"| {name} | {f['days']} | {_num(f['med'], '+.3f')} % | "
                 f"{_num(f['worst'], '+.3f')} % | {_num(f['bite'], '.1f')} | "
                 f"{_num(f['dd'], '+.3f')} % | "
                 f"{_num(f['green'], '.2f')} |")
    L.append(f"\nСвязь дневных денег с живыми книгами пула: "
             f"**{_num(a['live_corr'], '+.3f')}** "
             f"({a['live_corr_with'] or 'сравнивать не с чем'}, "
             f"{a['live_corr_days']} общих суток). Заявка объявила "
             f"ожидание ниже {EXPECTED_LIVE_CORR:.2f}; предел, по "
             f"которому судит пул, — {MAX_LIVE_CORR:.2f}.\n")
    L.append("## 8. Диагностика — предъявлять запрещено\n")
    L.append("Ячейки ниже просмотрены ПОСЛЕ данных. Выбрать лучшую и "
             "объявить её и есть ошибка R5.\n")
    for name, sp in a["diagnostics"].items():
        _split_table(L, sp, name)
    L.append("\n## 9. Как читать\n")
    L.append(a["reading"])
    L.append("")
    L.append("## 10. Оговорки, этим прогоном не снимаемые\n")
    L.append("- отмены заявок в записи не видны: очередь берётся "
             "размером уровня в момент метки. Это работает ПРОТИВ "
             "выживших — отменённая очередь была бы «выедена» раньше;")
    L.append("- своя заявка на рынок не влияет;")
    L.append("- превышение над кросс-секцией есть мера ЗАХЕДЖИРОВАННОЙ "
             "ноги, а живая книга голая и в каскадный день несёт рынок;")
    L.append("- проскальзывания обходом лесенки в числах нет, оно может "
             "только ухудшить.")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def write_status(out, tag, status):
    """Состояние прогона отдельным файлом, атомарно, после каждых суток."""
    p = os.path.join(out, f"MECH-bidsurv-status-{tag}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


_LAST = {}


def main():
    """Точка входа. Падение обязано САМО СЕБЯ доложить."""
    try:
        return _run()
    except SystemExit:
        raise
    except BaseException as e:                             # noqa: BLE001
        import traceback
        out, tag = _LAST.get("out"), _LAST.get("tag")
        if out and tag:
            st = _LAST.get("status") or {}
            st["state"] = "УПАЛ"
            st["error"] = f"{type(e).__name__}: {e}"
            st["traceback"] = traceback.format_exc()[-2000:]
            write_status(out, tag, st)
            print(f"ПРОГОН УПАЛ: {type(e).__name__}: {e}")
            if not _LAST.get("no_publish"):
                R.publish(f"механика 994fc54f: прогон упал ({tag})")
        raise


def _run():
    R.unbuffer_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        RESEARCH, "b1_book", "out"))
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--mem-share", type=float, default=0.6)
    ap.add_argument("--live", default=os.path.join(
        RESEARCH, "factory", "out", "factory-day-1m.json"))
    a = ap.parse_args()
    # Частичный прогон не занимает имя полного: смоук под именем
    # настоящего прогона в этом проекте уже подменял артефакт.
    if not a.tag:
        a.tag = f"1m-{a.days}d" if a.days else "1m"
    # Каталог создаётся ДО счёта: прогон турнира однажды досчитал всё и
    # упал на записи в несуществующий каталог.
    os.makedirs(a.out, exist_ok=True)
    _LAST.update({"out": a.out, "tag": a.tag, "no_publish": a.no_publish})

    syms, hours = R.available(os.path.join(a.root, "book"))
    if a.symbols:
        want = set(a.symbols.split(","))
        syms = [s for s in syms if s in want]
    days = sorted({h[:10] for h in hours})
    if a.days:
        days = days[-a.days:]
    if not syms or not days:
        raise SystemExit(f"в {a.root} нет записи")
    print(f"символов {len(syms)}, суток {len(days)}: {days[0]} … {days[-1]}")

    # Память проверяется ДО счёта: рядом работает сбор, и прибитая по
    # памяти запись стакана — единственное необратимое в проекте.
    need = R.mem_need_mb(len(syms), R.DAY_SEC + 2 * R.PAD_SEC)
    have = R.mem_available_mb()
    print(f"память: нужно ~{need:.0f} МБ на сутки, доступно "
          f"{'неизвестно' if have is None else f'{have:.0f} МБ'}")
    if have is not None and need > have * a.mem_share:
        fits = int(len(syms) * have * a.mem_share / max(need, 1e-9))
        raise SystemExit(
            f"ОТКАЗ: на сутки нужно ~{need:.0f} МБ, а свободно "
            f"{have:.0f} МБ (порог {a.mem_share:.0%}). Влезет около "
            f"{fits} символов: сузьте --symbols либо освободите память.")

    rows, last_seen = [], {}
    t_start = time.time()
    status = {"state": "идёт", "tag": a.tag, "symbols": len(syms),
              "days_planned": len(days), "day_from": days[0],
              "day_to": days[-1], "entry_sec": ENTRY_SEC,
              "mem_need_mb": need, "days_done": [],
              "started_at": datetime.now(timezone.utc).strftime(
                  "%Y-%m-%d %H:%M UTC")}
    _LAST["status"] = status
    write_status(a.out, a.tag, status)
    for day in days:
        t_day = time.time()
        print(f"  {day}: читаю")
        got = measure_day(a.root, syms, day, a.jobs, last_seen)
        rows += got
        took = round((time.time() - t_day) / 60, 1)
        print(f"  {day}: событий {len(got)}, всего {len(rows)}, "
              f"{took} мин, память {R.rss_mb()} МБ")
        # Состояние — после КАЖДЫХ суток: прогон, убитый по памяти, не
        # пишет ничего, и снаружи это неотличимо от «забыли запустить».
        status["days_done"].append(
            {"day": day, "took_min": took, "rss_mb": R.rss_mb(),
             "events": len(rows)})
        write_status(a.out, a.tag, status)

    # Ноль наблюдений при непустом входе — ОТКАЗ, а не отчёт с
    # прочерками: пустота не вправе выдавать себя за результат.
    if not [e for e in rows if e["drop"] == DROP]:
        raise SystemExit(
            f"ОТКАЗ: за {len(days)} суток по {len(syms)} символам не "
            f"нашлось ни одного события падения "
            f"{int(DROP * 100)} % с размеченной книгой. Это не «эффекта "
            f"нет», это нечего мерить: проверять надо запись, а не "
            f"гипотезу.")

    art = summarise(rows, len(days), a.live)
    art.update({
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "days": len(days), "day_from": days[0], "day_to": days[-1],
        "symbols": len(syms),
        "took_min": round((time.time() - t_start) / 60, 1),
        "thresholds": {"need_bp": NEED_BP, "share_pos_min": SHARE_POS_MIN,
                       "min_episodes": MIN_EPISODES, "t_sec": T_SEC,
                       "mark_delay_sec": MARK_DELAY_SEC,
                       "null_seed": NULL_SEED, "null_perms": NULL_PERMS},
    })
    status["state"] = "готов"
    write_status(a.out, a.tag, status)
    p = os.path.join(a.out, f"MECH-bidsurv-{a.tag}.json")
    json.dump(art, open(p, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    report(art, os.path.join(a.out, f"MECH-bidsurv-{a.tag}.md"))
    print(f"готово: {p}")
    print(art["reading"])
    if not a.no_publish:
        R.publish(f"механика 994fc54f: поглощение после падения ({a.tag})")


if __name__ == "__main__":
    main()
