#!/usr/bin/env python3
"""
Потолок механики «смена интервала начисления funding».

Самый дешёвый расчёт, объявленный заявкой до всякого строительства:
чистый пересчёт уже собранного — ряды funding площадки исполнения
(`research/a1_universe/out/funding`) плюс минутные бары хранилища A2.
Нового сбора нет, нового прохода по универсуму нет.

Ячейка вердикта объявлена в `shift.py` и здесь не выбирается: событие —
первое начисление по укороченному интервалу при ставке < 0 (платят
шорты), позиция ЛОНГ, удержание до возврата интервала либо 24 ч, что
раньше. Всё остальное в отчёте — диагностика, и предъявлять лучшую
клетку запрещено (ошибка R5).

Четыре числа потолка, каждое закрывает механику само
----------------------------------------------------

(а) **Плотность событий** — доля суток хотя бы с одним событием ячейки
    вердикта. Ниже `ceiling.MIN_ACTIVE_SHARE` — форма по правилу вылета
    неизмерима, и остальное считать незачем. Порог не повторяется
    числом, а берётся у самого потолка фабрики.
(б) **Превышение с ИДЕАЛЬНЫМ входом** — по цене самой метки начисления,
    задержка ноль. Верхняя граница: настоящий вход только хуже, и он
    считается рядом. Ниже `screen.NEUTRAL_COST_BP` — закрыто.
(в) **Контроль 2** — имена того же дециля |ставки| в то же окно без
    смены интервала, и отношение к ним. Ниже 1.5 — смена интервала не
    добавляет ничего к уровню ставки, и это carry в новом костюме.
(г) **Крайность ставки** — совпадает ли смена интервала с |ставкой| у
    предела собственного ряда. Не совпадает — посылка механики ложна.

Почему матрицы цен здесь нет
----------------------------

События редки во времени, а нужны от цены ровно три момента на событие
(идеальный вход, настоящий вход, выход). Полная матрица «символы ×
минуты» за четыре года стоила бы гигабайты рядом с живой записью
стакана — единственным необратимым в проекте, — поэтому грузятся только
нужные минуты: `PriceBook` держит вектор сечения на каждый якорь.
Память считается СОСТАВОМ и печатается до счёта (урок D1).

Запуск на сервере:
    cd ~/algoth_v2 && mkdir -p research/probe_fshift/out
    cd ~/algoth_v2 && nice -n 19 .venv/bin/python \\
        research/probe_fshift/run_ceiling.py --tag 1m
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in (os.path.join(RESEARCH, "common"),
           os.path.join(RESEARCH, "l3_events"),
           os.path.join(RESEARCH, "z1_screen"),
           os.path.join(RESEARCH, "a4_cointegration"),
           os.path.join(RESEARCH, "factory"),
           HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import funding_series as FS                                 # noqa: E402
import data as D                                            # noqa: E402
import screen as Z                                          # noqa: E402
import run as L3                                            # noqa: E402
import ceiling as FCE                                       # noqa: E402
import shift as SH                                          # noqa: E402

OUT = os.path.join(HERE, "out")
A1_OUT = os.path.join(RESEARCH, "a1_universe", "out")
FUND_DIR = os.path.join(A1_OUT, "funding")

# Границы применимости — из объявления площадки, чужое утверждение, а не
# наш замер. Обе обязаны стоять в отчёте числом.
AUTO_FROM = "2025-11-03"        # автоматический режим смены интервала
NOT_COVERED = ("BTCUSDT", "ETHUSDT")   # правилом площадки не охвачены

TOL_MIN = 5          # минут допуска на поиск первой доступной цены
MIN_CROSS = Z.MIN_CROSS          # уже сечения — контроля нет вовсе
NEUTRAL_COST_BP = Z.NEUTRAL_COST_BP      # круг нейтральной книги, две ноги
SOLO_COST_BP = Z.ROUND_COST_BP           # круг голой ноги, комиссия
# Круг голой ноги СО СПРЕДОМ в стрессе — перенесённое число собственной
# записи стакана (`research/d1_seconds/out/D1-tape-check-1m.md`: 6.8 б.п.
# на входе и 6.1 на выходе поверх комиссии). В архиве спреда нет вовсе,
# поэтому величина перенесена, а не измерена здесь, и отчёт это говорит.
SOLO_COST_SPREAD_BP = 17.4
SEED = 20260903      # зерно ЧИСЛОМ, а не от часов запуска (урок R3)
NULL_DRAWS = 20      # перестановок метки на событие
MIN_MEASURED = 30    # событий меньше — ячейка НЕ измерена, а не нулевая
DECILES = 10


def log_(m):
    print(m, flush=True)


def mem_available_mb():
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return float("nan")


# --- универсум и ряды -------------------------------------------------

def universe_assets():
    """Крипто-активы с обоими символами: площадка исполнения и архив.

    Ряды funding названы символом Bybit, бары — символом Binance, и
    совпадают они не у всех: сопоставление «по умолчанию Bybit» тихо
    теряло бы часть архива (правило `funding_series.load_funding`).
    """
    with open(os.path.join(A1_OUT, "universe.json"), encoding="utf-8") as f:
        raw = json.load(f)["assets"]
    return {a: v for a, v in raw.items()
            if v.get("asset_class") == "crypto"
            and v.get("binance_symbol") and v.get("bybit_symbol")}


def collect_events(fund, sym_of, uni, share, min_share, start_ms, end_ms,
                   log=log_):
    """События смены интервала по всему универсуму, с охранами.

    Охраны — те же, что у L3, и тем же кодом: окно делистинга (при
    снятии инструмента интерес и ставки ведут себя как наше условие,
    доведённое до предела) и ликвидность по 90 суткам, кончившимся ДО
    дня события.
    """
    kept, dropped = [], {"вне окна": 0, "делистинг": 0, "ликвидность": 0,
                         "нет стороны": 0, "площадка не охватывает": 0,
                         "дубль по имени": 0}
    all_ts = {}
    for asset, (t, r) in sorted(fund.items()):
        sym = sym_of.get(asset)
        if sym is None:
            continue
        evs = SH.shift_events(t, r)
        all_ts[sym] = np.array([e["ts"] for e in evs], dtype=np.int64)
        if sym in NOT_COVERED:
            dropped["площадка не охватывает"] += len(evs)
            continue
        good = []
        for e in evs:
            if not (start_ms <= e["ts"] < end_ms):
                dropped["вне окна"] += 1
                continue
            if e["side"] is None:
                dropped["нет стороны"] += 1
                continue
            sec = np.array([e["ts"] // 1000], dtype=np.int64)
            if not bool(D.delist_mask(sym, sec, uni)[0]):
                dropped["делистинг"] += 1
                continue
            if not bool(D.liquidity_mask(sym, sec, share, min_share)[0]):
                dropped["ликвидность"] += 1
                continue
            rank, top = SH.rate_extremity(t, r, e["i"])
            entry, exit_, why = SH.holding(t, e)
            good.append({**e, "symbol": sym, "asset": asset,
                         "entry_ms": entry, "exit_ms": exit_, "exit_why": why,
                         "rank": rank, "top": top})
        before = len(good)
        good = SH.dedup_by_name(good)
        dropped["дубль по имени"] += before - len(good)
        kept.extend(good)
    kept.sort(key=lambda e: e["entry_ms"])
    log(f"событий после охран: {len(kept)}; отсеяно {dropped}")
    return kept, all_ts, dropped


# --- цены: только нужные минуты --------------------------------------

def minute(ts_ms):
    return (int(ts_ms) // 60000) * 60


def anchors_of(e):
    """Четыре момента цены на событие. Одно место на весь замер.

    `pre` — зеркальное окно ТОЙ ЖЕ длины ПЕРЕД меткой. Оно отвечает на
    четвёртое объявленное условие смерти: если превышение живёт до
    метки и исчезает после, переход есть метка уже случившегося хода, и
    торговать нечем. Без этого окна условие осталось бы объявленным и
    непроверенным.
    """
    m = minute(e["entry_ms"])
    out = minute(e["exit_ms"])
    return {"pre": m - (out - m), "mark": m, "real": m + 60, "out": out}


class PriceBook:
    """Сечение цен на каждом якоре. Якорь — момент, цена — первая
    доступная в `[якорь, якорь + допуск)`.

    Отсутствующая цена остаётся `NaN`: бар без сделок в хранилище не
    лежит вовсе, и подставлять вместо него соседнюю цену значило бы
    возвращать замороженный ряд, который A2 уже ловила.
    """

    def __init__(self, symbols, anchors):
        self.syms = list(symbols)
        self.idx = {s: i for i, s in enumerate(self.syms)}
        self.anchors = np.array(sorted(set(int(a) for a in anchors)),
                                dtype=np.int64)
        self.pos = {int(a): i for i, a in enumerate(self.anchors)}
        self.A = np.full((len(self.anchors), len(self.syms)), np.nan,
                         dtype=np.float32)

    def nbytes(self):
        return self.A.nbytes

    def vec(self, anchor):
        i = self.pos.get(int(anchor))
        return None if i is None else self.A[i]

    def price(self, anchor, symbol):
        v = self.vec(anchor)
        j = self.idx.get(symbol)
        if v is None or j is None:
            return np.nan
        return float(v[j])


def needed_minutes(anchors, tol_min=TOL_MIN):
    """Минуты, которые надо прочитать: якорь плюс окно допуска."""
    a = np.asarray(sorted(set(int(x) for x in anchors)), dtype=np.int64)
    off = np.arange(max(tol_min, 1), dtype=np.int64) * 60
    return np.unique((a[:, None] + off[None, :]).ravel())


def fill_book(book, by_minute, tol_min=TOL_MIN):
    """Раскладывает прочитанные минуты по якорям.

    Смещения перебираются ПО ВОЗРАСТАНИЮ, и уже занятая ячейка не
    переписывается: у якоря побеждает ПЕРВАЯ доступная цена, а не
    произвольная из окна допуска. Порядок строк, в котором их вернуло
    хранилище, на результат не влияет — иначе одна и та же запись
    давала бы разные числа от прогона к прогону.
    """
    filled = 0
    for ai, anchor in enumerate(book.anchors):
        # Уже заполненное не переписывается и между вызовами: якорь у
        # границы месяца обслуживают две партиции подряд, и без этого
        # более далёкая минута следующего месяца затирала бы ближайшую.
        taken = np.isfinite(book.A[ai])
        for off in range(max(tol_min, 1)):
            got = by_minute.get(int(anchor) + off * 60)
            if got is None:
                continue
            rows, px = got
            sel = ~taken[rows]
            if not sel.any():
                continue
            book.A[ai, rows[sel]] = px[sel]
            taken[rows[sel]] = True
            filled += int(sel.sum())
    return filled


def load_prices(book, tol_min=TOL_MIN, log=log_, con_factory=None):
    """Заполняет `book` из хранилища A2, месяц за месяцем.

    Читаются ТОЛЬКО нужные минуты: полусоединение с зарегистрированной
    таблицей меток вместо полной матрицы «символы × минуты» за четыре
    года. Бар без сделок отбрасывается (`trades > 0`) — требование A2.
    """
    import pyarrow as pa
    import series as S

    need = needed_minutes(book.anchors, tol_min)
    con = (con_factory or S.connect)()
    row_of = {s: i for i, s in enumerate(book.syms)}
    want = "', '".join(book.syms)
    months = D.months(
        datetime.fromtimestamp(int(need.min()), timezone.utc).date().isoformat(),
        datetime.fromtimestamp(int(need.max()), timezone.utc).date().isoformat())
    filled = 0
    for mon in months:
        path = os.path.join(S.PARQUET, "1m", f"{mon}.parquet")
        if not os.path.exists(path):
            continue
        y, m = int(mon[:4]), int(mon[5:7])
        lo = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())
        hi = int(datetime(y + (m == 12), m % 12 + 1, 1,
                          tzinfo=timezone.utc).timestamp())
        want_ts = need[(need >= lo) & (need < hi)]
        if not len(want_ts):
            continue
        con.register("need_ts", pa.table({"ts": pa.array(want_ts)}))
        q = f"""
            SELECT symbol, epoch(open_time)::BIGINT AS ts, open
            FROM read_parquet('{path}')
            WHERE trades > 0 AND open > 0
              AND symbol IN ('{want}')
              AND epoch(open_time)::BIGINT IN (SELECT ts FROM need_ts)
        """
        tab = con.execute(q).fetch_arrow_table()
        con.unregister("need_ts")
        if tab.num_rows == 0:
            continue
        d = tab.column("symbol").combine_chunks().dictionary_encode()
        vocab = d.dictionary.to_pylist()
        rmap = np.array([row_of.get(s, -1) for s in vocab], dtype=np.int64)
        rows = rmap[np.asarray(d.indices)]
        ts = np.asarray(tab.column("ts"))
        px = np.asarray(tab.column("open"), dtype=np.float32)
        keep = rows >= 0
        rows, ts, px = rows[keep], ts[keep], px[keep]
        o = np.argsort(ts, kind="stable")
        rows, ts, px = rows[o], ts[o], px[o]
        edge = np.flatnonzero(np.concatenate(([True], ts[1:] != ts[:-1])))
        edge = np.append(edge, len(ts))
        by_minute = {int(ts[edge[k]]): (rows[edge[k]:edge[k + 1]],
                                        px[edge[k]:edge[k + 1]])
                     for k in range(len(edge) - 1)}
        filled += fill_book(book, by_minute, tol_min)
        log(f"  цены {mon}: строк {tab.num_rows:,}".replace(",", " "))
    con.close()
    if not filled:
        raise SystemExit("ни одной цены не прочитано — пустая загрузка, "
                         "а не «событий нет»")
    log(f"  заполнено {filled:,} значений, сечений {len(book.anchors):,}, "
        f"{book.nbytes() / 2**20:.0f} МиБ".replace(",", " "))
    return book


# --- замер -----------------------------------------------------------

def cross_mean(book, a_in, a_out, banned_rows):
    """Равновзвешенная корзина сечения за окно `(a_in, a_out)`.

    Контроль 1. Именно СРЕДНЕЕ, а не медиана: превышение над медианой
    несёт структурный снос (замер Z1: до +10.7 б.п. у любого лонга на
    240 минутах), потому что распределение доходностей скошено вправо.
    Медиана годится для обнаружения сигнала, но хеджировать об
    статистику нельзя — корзина торгуема, медиана нет.
    """
    vi, vo = book.vec(a_in), book.vec(a_out)
    if vi is None or vo is None:
        return np.nan, 0
    with np.errstate(invalid="ignore", divide="ignore"):
        r = vo.astype(np.float64) / vi.astype(np.float64) - 1.0
    ok = np.isfinite(r)
    if banned_rows is not None and len(banned_rows):
        ok[banned_rows] = False
    k = int(ok.sum())
    if k < MIN_CROSS:
        return np.nan, k
    return float(r[ok].mean()), k


def banned(all_ts, book, t0_ms, t1_ms):
    """Строки, у которых в окне своё событие смены интервала.

    Сосед, которого в это же окно выталкивает площадка, не годится в
    равновзвешенный фон: его исход и есть то, что мы меряем. Окно
    расширено назад на предел удержания — событие соседа, начавшееся
    раньше, всё ещё живо в нашем окне.
    """
    out = []
    lo = int(t0_ms) - SH.MAX_HOLD_MS
    for s, ts in all_ts.items():
        j = book.idx.get(s)
        if j is None or not len(ts):
            continue
        i0 = int(np.searchsorted(ts, lo, "left"))
        i1 = int(np.searchsorted(ts, int(t1_ms), "right"))
        if i1 > i0:
            out.append(j)
    return np.array(sorted(set(out)), dtype=np.int64)


def own_ret(book, a_in, a_out, symbol):
    p0 = book.price(a_in, symbol)
    p1 = book.price(a_out, symbol)
    if not (np.isfinite(p0) and np.isfinite(p1)) or p0 <= 0:
        return np.nan
    return p1 / p0 - 1.0


def current_rates(fund, sym_of, at_ms, max_age_ms=24 * SH.MS_H):
    """Действующая ставка каждого имени в момент `at_ms`.

    Берётся последнее начисление СТРОГО ДО момента и не старше суток:
    ряд, у которого последнее начисление неделю назад, действующей
    ставки не имеет, и подставлять её значило бы придумать наблюдение.
    """
    out = {}
    for asset, (t, r) in fund.items():
        s = sym_of.get(asset)
        if s is None:
            continue
        i = int(np.searchsorted(t, int(at_ms), "left"))
        if i <= 0:
            continue
        if int(at_ms) - int(t[i - 1]) > max_age_ms:
            continue
        out[s] = float(r[i - 1])
    return out


def decile_peers(rates, symbol, same_sign=True, deciles=DECILES):
    """Имена того же дециля |ставки|, что и `symbol`.

    `same_sign=True` — главная прочитка: контроль обязан быть той же
    СТОРОНЫ, иначе мы сравнивали бы «лонг имени, которое нам платит» с
    «лонгом имени, которому платим мы», то есть другую сделку. Заявка
    говорила «того же дециля |ставки|» и знака не называла, поэтому
    вторая прочитка (`same_sign=False`) считается рядом диагностикой, а
    не подменяется молча.
    """
    r0 = rates.get(symbol)
    if r0 is None or not np.isfinite(r0) or r0 == 0:
        return []
    pool = {s: v for s, v in rates.items()
            if np.isfinite(v) and v != 0
            and (not same_sign or (v < 0) == (r0 < 0))}
    if len(pool) < deciles:
        return []
    names = list(pool)
    a = np.abs(np.array([pool[s] for s in names]))
    edges = np.quantile(a, np.linspace(0, 1, deciles + 1))
    b0 = int(np.clip(np.searchsorted(edges, abs(r0), "right") - 1,
                     0, deciles - 1))
    lo, hi = edges[b0], edges[b0 + 1]
    return [s for s, v in zip(names, a)
            if lo <= v <= hi and s != symbol]


def measure(events, book, all_ts, fund, sym_of, rng, log=log_,
            asset_of=None):
    """Числа (б) и (в) по каждому событию. Чистая функция от цен.

    Никакого чтения с диска здесь нет: тест подаёт свой `PriceBook` и
    свои ряды, и калибровочная пара гоняется на настоящей этой функции,
    а не на её пересказе.
    """
    # Обратная карта строится ЗДЕСЬ, а не приходит вторым списком: два
    # места, решающих «какому активу принадлежит символ», однажды
    # разойдутся, и начисления соседа посчитались бы чужому ряду.
    asset_of = asset_of or {v: k for k, v in sym_of.items()}
    rows, skipped = [], 0
    for e in events:
        sym = e["symbol"]
        side = e["side"]
        A = anchors_of(e)
        a_mark, a_real, a_out = A["mark"], A["real"], A["out"]
        if a_out <= a_real:
            skipped += 1
            continue
        ban = banned(all_ts, book, e["entry_ms"], e["exit_ms"])
        rec = {"symbol": sym, "ts": e["entry_ms"], "exit_ts": e["exit_ms"],
               "side": side, "rate": e["rate"], "step_h": e["step_h"],
               "before_h": e["before_h"], "rank": e["rank"], "top": e["top"],
               "exit_why": e["exit_why"],
               "hold_h": round((e["exit_ms"] - e["entry_ms"]) / SH.MS_H, 3)}
        for arm, a_in in (("ideal", a_mark), ("real", a_real)):
            o = own_ret(book, a_in, a_out, sym)
            c, wide = cross_mean(book, a_in, a_out, ban)
            rec[f"{arm}_own_bp"] = (float(side) * o * 1e4
                                    if np.isfinite(o) else np.nan)
            rec[f"{arm}_exc_bp"] = SH.excess_bp(o, c, side)
            rec[f"{arm}_cross"] = wide
        # Зеркальное окно ПЕРЕД меткой: свой фон и свои запреты, иначе
        # «до» и «после» сравнивались бы против разных корзин.
        ban_pre = banned(all_ts, book, A["pre"] * 1000, e["entry_ms"])
        cp, _ = cross_mean(book, A["pre"], a_mark, ban_pre)
        op = own_ret(book, A["pre"], a_mark, sym)
        rec["pre_own_bp"] = (float(side) * op * 1e4 if np.isfinite(op)
                             else np.nan)
        rec["pre_exc_bp"] = SH.excess_bp(op, cp, side)
        # Начисления считаются СТРОГО ВНУТРИ удержания: начисление в
        # самый момент метки достаётся тем, кто держал позицию ДО него,
        # а мы в эту секунду только входим. Записать его себе значило бы
        # получить деньги за риск, которого не несли, — и на часовом
        # интервале со ставкой в полпроцента это десятки базисных
        # пунктов на событие. Начисление ровно в момент выхода тоже не
        # наше: выход и есть та минута.
        got = FS.accrued(fund, e["asset"], e["entry_ms"] + 1, e["exit_ms"])
        rec["fund_bp"] = SH.funding_bp(got, side)
        # Контроль 2 и нуль считаются ТОЛЬКО там, где событие измерено:
        # иначе они описывали бы другое подмножество, и отношение (в)
        # сравнивало бы числитель одной выборки со знаменателем другой.
        if np.isfinite(rec["ideal_exc_bp"]):
            rates = current_rates(fund, sym_of, e["entry_ms"])
            # Корзина сечения у контроля 2 — ТА ЖЕ, что у события: иначе
            # числитель и знаменатель отношения (в) считались бы против
            # разных фонов, и отношение сравнивало бы две разные сделки.
            base, _ = cross_mean(book, a_mark, a_out, ban)
            ban_set = set(ban.tolist())
            for tag, same in (("c2", True), ("c2any", False)):
                vals, fnd = [], []
                for p in decile_peers(rates, sym, same_sign=same):
                    j = book.idx.get(p)
                    if j is None or j in ban_set:
                        continue
                    v = SH.excess_bp(own_ret(book, a_mark, a_out, p),
                                     base, side)
                    if not np.isfinite(v):
                        continue
                    vals.append(v)
                    # Начисления соседа считаются ТЕМ ЖЕ окном и той же
                    # функцией, что у события. Без них отношение (в)
                    # сравнивало бы ценовую ногу события с ценовой ногой
                    # контроля и молчало бы о том, что обе стороны
                    # получают одну и ту же ставку: «carry в новом
                    # костюме» стало бы догадкой вместо числа.
                    g = FS.accrued(fund, asset_of.get(p), e["entry_ms"] + 1,
                                   e["exit_ms"])
                    f_bp = SH.funding_bp(g, side)
                    if np.isfinite(f_bp):
                        fnd.append(f_bp)
                rec[f"{tag}_n"] = len(vals)
                rec[f"{tag}_bp"] = float(np.mean(vals)) if vals else np.nan
                rec[f"{tag}_med_bp"] = (float(np.median(vals)) if vals
                                        else np.nan)
                rec[f"{tag}_fund_bp"] = (float(np.mean(fnd)) if fnd
                                         else np.nan)
            rec["null_bp"] = null_excess(book, a_mark, a_out, ban, side, rng)
        rows.append(rec)
    if skipped:
        log(f"  пропущено событий с удержанием короче минуты: {skipped}")
    log(f"измерено строк: {len(rows)}")
    return rows


def null_excess(book, a_in, a_out, ban, side, rng, draws=NULL_DRAWS):
    """Нуль: та же минута, ДРУГОЕ имя.

    Перемешивается ровно связь «это имя ↔ этот исход»; календарь
    событий и состояние рынка в эти минуты остаются на месте. Если
    загрузка сломана, наблюдаемое превышение и нуль обвалятся вместе —
    в этом и смысл пары (урок зонда дней недели: сломанная загрузка
    выглядит ровно как «эффекта нет»).
    """
    vi, vo = book.vec(a_in), book.vec(a_out)
    if vi is None or vo is None:
        return np.nan
    with np.errstate(invalid="ignore", divide="ignore"):
        r = vo.astype(np.float64) / vi.astype(np.float64) - 1.0
    ok = np.isfinite(r)
    if len(ban):
        ok[ban] = False
    idx = np.flatnonzero(ok)
    if len(idx) < MIN_CROSS:
        return np.nan
    c, _ = cross_mean(book, a_in, a_out, ban)
    if not np.isfinite(c):
        return np.nan
    pick = rng.choice(idx, size=min(draws, len(idx)), replace=False)
    return float(np.mean([SH.excess_bp(r[p], c, side) for p in pick]))


# --- сводка и вердикт -------------------------------------------------

def agg(vals):
    v = np.asarray([x for x in vals if np.isfinite(x)], dtype=np.float64)
    if not len(v):
        return {"n": 0, "mean": None, "med": None}
    return {"n": int(len(v)), "mean": float(v.mean()),
            "med": float(np.median(v))}


def daily_net(rows, key="ideal_exc_bp"):
    """Ряд «сутки → сумма нетто за эти сутки», в б.п. гросса.

    Тот же вид, который читает правило вылета (`pool.shape_why` →
    `stability.stats`): кандидат объявляется только после потолка, и
    ряд обязан быть готов в той форме, в какой его судят.
    """
    out = {}
    for r in rows:
        v = r.get(key)
        if v is None or not np.isfinite(v):
            continue
        d = datetime.fromtimestamp(r["ts"] / 1000, timezone.utc).date()
        out[d.isoformat()] = out.get(d.isoformat(), 0.0) + float(v) \
            + (float(r["fund_bp"]) if np.isfinite(r.get("fund_bp", np.nan))
               else 0.0) - NEUTRAL_COST_BP
    return out


def verdict(dens, ex, c2, rank_share, null, pre=None, measured=None):
    """Вердикт ЧИСЛОМ, а не литералом рядом с числом.

    Каждая строка — одно из объявленных заявкой условий смерти, и текст
    её выводится из измеренной величины. Фраза, стоящая рядом с числом
    литералом, однажды противоречит своему же числу; так уже случалось
    в замере цены разбора лесенки.

    Возвращает `(строки, сработавшие_условия, сомнения)`. Сомнения — НЕ
    условия смерти: нуль калибрует меру, а не судит механику, и своего
    порога заявка ему не объявляла. Смешать их значило бы завести
    пятое условие смерти задним числом.

    `measured` меньше `MIN_MEASURED` означает «не измерено»: на горстке
    событий вердикт не выносится вовсе, и ни одно условие не считается
    сработавшим. Смоук иначе читался бы как закрытие механики.
    """
    lines, dead, doubt = [], [], []
    thin = measured is not None and measured < MIN_MEASURED
    thr = FCE.MIN_ACTIVE_SHARE
    d = dens.get("share")
    if d is None:
        lines.append(("плотность", "—", "не измерена"))
    else:
        ok = d >= thr
        lines.append(("плотность", f"{d:.2f} при пороге {thr:.2f}",
                      "" if ok else "форма неизмерима"))
        if not ok:
            dead.append("плотность ниже порога измеримости формы")
    m = ex.get("mean")
    if m is None:
        lines.append(("превышение, среднее", "—", "не измерено"))
    else:
        ok = m >= NEUTRAL_COST_BP
        lines.append(("превышение, среднее",
                      f"{m:+.1f} при круге {NEUTRAL_COST_BP:.0f} б.п.",
                      "" if ok else "не окупает круг нейтральной книги"))
        if not ok:
            dead.append("среднее превышение ниже круга нейтральной книги")
    md = ex.get("med")
    if m is not None and md is not None:
        same = (m > 0) == (md > 0)
        lines.append(("медиана против среднего",
                      f"{md:+.1f} против {m:+.1f}",
                      "" if same else "форма короткой волатильности"))
        if not same:
            dead.append("медиана и среднее расходятся знаком")
    txt, ok2 = L3.ratio_cell(ex.get("mean") if ex.get("mean") is not None
                             else np.nan,
                             c2.get("mean") if c2.get("mean") is not None
                             else np.nan)
    # `None` у `ratio_cell` означает «не измерено», а не «сработало»:
    # величина, которой нет, не есть провал условия.
    lines.append(("отношение к контролю 2", txt,
                  "не измерено" if ok2 is None
                  else ("" if ok2 else "смена интервала не добавляет "
                        "к ставке")))
    if ok2 is False:
        dead.append("отношение к контролю 2 ниже 1.5")
    if rank_share is None:
        lines.append(("ставка у предела", "—", "не измерена"))
    else:
        lines.append(("ставка у предела",
                      f"{rank_share:.2f} событий выше 90-го процентиля "
                      "собственного ряда",
                      "" if rank_share >= 0.5 else "посылка механики слаба"))
        if rank_share < 0.5:
            dead.append("ставка события далека от предела своего ряда")
    p = (pre or {}).get("mean")
    if p is None or m is None:
        lines.append(("превышение ДО метки", "—", "не измерено"))
    else:
        ok = m > p
        lines.append(("превышение ДО метки",
                      f"{p:+.1f} против {m:+.1f} после",
                      "" if ok else "переход есть метка уже случившегося"))
        if not ok:
            dead.append("превышение живёт до метки, а не после неё")
    n = null.get("mean")
    if n is not None:
        # Нуль — калибровка меры, а не условие смерти: своего порога
        # заявка ему не объявляла, и добавлять его в «сработало»
        # значило бы назначить пятое условие после результата.
        bad = abs(n) > 2.0
        lines.append(("нуль (перемешанные метки), калибровка",
                      f"{n:+.1f} б.п.",
                      "" if not bad else "нуль не около нуля"))
        if bad:
            doubt.append("нуль смещён — замер под вопросом")
    if thin:
        lines.append(("объём выборки",
                      f"{measured} событий при {MIN_MEASURED}",
                      "ячейка НЕ измерена"))
        doubt.append(f"измерено {measured} событий — меньше "
                     f"{MIN_MEASURED}: вердикт не выносится")
        dead = []
    return lines, dead, doubt


def write_report(path, meta, dens, ex_i, ex_r, own_i, fund_a, c2, c2any,
                 null, rank_share, rows, dens_split, diag, ex_pre,
                 c2_fund, c2any_fund, pre_own):
    L = ["# Потолок механики «смена интервала начисления funding»\n"]
    L.append(f"\nПрогон {meta['when']} · окно {meta['start']}…{meta['end']} · "
             f"символов {meta['symbols']} · событий найдено "
             f"{meta['found']} · измерено {meta['measured']}\n")
    L.append("\n**Что меряется.** Событие — первое начисление по "
             "УКОРОЧЕННОМУ интервалу при ставке < 0 (платят шорты). "
             "Позиция ЛОНГ против выталкиваемых шортов, одна на имя; "
             "удержание до первого начисления по возвращённому длинному "
             "интервалу либо 24 ч, что раньше. Мера — превышение над "
             "ОДНОВРЕМЕННОЙ равновзвешенной кросс-секцией, среднее и "
             "медиана рядом.\n")
    L.append("\n**Детектор смотрит только назад.** Режим считается по "
             "окну шагов, кончающемуся на предыдущем начислении, и "
             "сравнивается с шагом, приведшим к событию: обе величины "
             "известны в момент метки. Определение «режим до длинный, "
             "режим после короткий» было бы заглядыванием в будущее и "
             "закрыто тестом с негативным контролем.\n")
    L.append(f"\n**Границы применимости, из объявления площадки.** "
             f"Автоматический режим смены интервала действует с "
             f"**{AUTO_FROM}**, и история до него считается отдельно "
             f"(таблица плотности ниже). Правилом площадки НЕ охвачены "
             f"{', '.join(NOT_COVERED)} — в события они не входят вовсе "
             f"({meta['not_covered']} событий отсеяно).\n")

    L.append("\n## (а) Плотность событий\n\n")
    L.append("| срез | суток | суток с событием | доля | окна по 30 суток: "
             "медиана / мин / макс |\n")
    L.append("|---|--:|--:|--:|---|\n")
    for name, dd in dens_split:
        if dd["share"] is None:
            L.append(f"| {name} | — | — | — | — |\n")
            continue
        w = ("—" if dd["med"] is None
             else f"{dd['med']:.2f} / {dd['lo']:.2f} / {dd['hi']:.2f}")
        L.append(f"| {name} | {dd['days']} | {dd['active_days']} | "
                 f"{dd['share']:.2f} | {w} |\n")
    L.append(f"\nПорог измеримости формы — **{FCE.MIN_ACTIVE_SHARE:.2f}**, и "
             "он не назначен здесь, а взят у потолка фабрики "
             "(`research/factory/ceiling.py`): за `pool.IDLE_D` суток "
             "простоя кандидат обязан набрать `stability.MIN_DAYS` суток "
             "со сделками, иначе правило вылета его форму не судит "
             "вовсе.\n")

    L.append("\n## (б) Превышение над кросс-секцией\n\n")
    L.append("| вход | событий | среднее | медиана | сырой ход | "
             "начисления | нетто книги |\n")
    L.append("|---|--:|--:|--:|--:|--:|--:|\n")
    for name, a, o in (("идеальный (по метке)", ex_i, own_i),
                       ("настоящий (следующий бар)", ex_r, None)):
        if not a["n"]:
            L.append(f"| {name} | 0 | — | — | — | — | — |\n")
            continue
        raw = "—" if o is None or not o["n"] else f"{o['mean']:+.1f}"
        fu = "—" if not fund_a["n"] else f"{fund_a['mean']:+.1f}"
        net = a["mean"] - NEUTRAL_COST_BP + (fund_a["mean"] or 0.0)
        L.append(f"| {name} | {a['n']} | {a['mean']:+.1f} | {a['med']:+.1f} | "
                 f"{raw} | {fu} | {net:+.1f} |\n")
    if ex_i["n"] and ex_r["n"]:
        d = ex_r["mean"] - ex_i["mean"]
        L.append(f"\nОдна минута задержки стоит **{d:+.1f}** б.п.: "
                 f"настоящий вход дал {ex_r['mean']:+.1f} против "
                 f"{ex_i['mean']:+.1f} у идеального. "
                 + ("Знак не в нашу пользу — идеальный вход и правда "
                    "недостижимо хорош." if d < 0 else
                    "Знак ПОЛОЖИТЕЛЕН, то есть на этой выборке минута "
                    "задержки не стоила ничего; «идеальный вход» есть "
                    "недостижимая цена, а не арифметическая верхняя "
                    "граница превышения, и читать его как границу "
                    "нельзя.") + "\n")
    L.append(f"\nИдеальный вход — по цене САМОЙ метки начисления, задержка "
             "ноль: цена, по которой купить нельзя (приём S1). "
             "Круг нейтральной книги — "
             f"**{NEUTRAL_COST_BP:.0f} б.п.**, две ноги: превышение над "
             "кросс-секцией есть PnL книги «наша нога плюс хедж об "
             "сечение». Голая нога сравнивается с "
             f"**{SOLO_COST_BP:.0f}** б.п. комиссии и с "
             f"**{SOLO_COST_SPREAD_BP:.1f}** б.п. со спредом в стрессе — "
             "второе число ПЕРЕНЕСЕНО из нашей записи стакана "
             "(`D1-tape-check-1m.md`), в архиве спреда нет вовсе.\n")

    L.append("\n## (в) Контроль 2 — тот же дециль |ставки| без события\n\n")
    L.append("| выборка | пар | цена, среднее | цена, медиана | начисления "
             "| нетто книги | отношение события к ней |\n")
    L.append("|---|--:|--:|--:|--:|--:|---|\n")
    ev_net = (ex_i["mean"] - NEUTRAL_COST_BP + (fund_a["mean"] or 0.0)
              if ex_i["n"] else None)
    L.append(f"| **событие** | {ex_i['n']} | "
             + (f"{ex_i['mean']:+.1f} | {ex_i['med']:+.1f} | "
                f"{(fund_a['mean'] or 0.0):+.1f} | {ev_net:+.1f} | — |\n"
                if ex_i["n"] else "— | — | — | — | — |\n"))
    for name, c, cf in (("дециль того же знака (главная прочитка)", c2,
                         c2_fund),
                        ("дециль без учёта знака (диагностика)", c2any,
                         c2any_fund)):
        if not c["n"]:
            L.append(f"| {name} | 0 | — | — | — | — | — |\n")
            continue
        txt, _ = L3.ratio_cell(ex_i["mean"] if ex_i["n"] else np.nan,
                               c["mean"])
        cn = (c["mean"] - NEUTRAL_COST_BP + (cf["mean"] or 0.0)
              if cf["n"] else None)
        L.append(f"| {name} | {c['n']} | {c['mean']:+.1f} | {c['med']:+.1f} "
                 f"| " + (f"{(cf['mean'] or 0.0):+.1f} | {cn:+.1f} | "
                          if cf["n"] else "— | — | ") + f"{txt} |\n")
    if ev_net is not None and c2_fund["n"] and c2["n"]:
        c2n = c2["mean"] - NEUTRAL_COST_BP + (c2_fund["mean"] or 0.0)
        px_better = ex_i["mean"] > c2["mean"]
        net_better = ev_net > c2n
        L.append(f"\n**Колонка «нетто книги» и есть ответ на вопрос "
                 f"«событие или carry».** У события {ev_net:+.1f} б.п., у "
                 f"соседей той же ставки БЕЗ смены интервала {c2n:+.1f}; "
                 f"ценовые ноги — {ex_i['mean']:+.1f} против "
                 f"{c2['mean']:+.1f}. ")
        if net_better and px_better:
            L.append("Событие лучше соседей И по нетто, И по цене — "
                     "значит прибавку даёт сама смена интервала, а не "
                     "уровень ставки. Это единственная конфигурация, в "
                     "которой механику стоит строить дальше.\n")
        elif net_better:
            L.append("Нетто у события выше, а ценовая нога ХУЖЕ, чем у "
                     "соседей той же ставки. Значит прибавку даёт не "
                     "событие, а начисления: укороченный интервал есть "
                     "усилитель carry — та же ставка, начисленная в "
                     "несколько раз чаще. Carry как направление — это "
                     "гипотеза 3, закрытая не сигналом, а хвостом "
                     "(просадка −47.8 % при живом сигнале 3.6 σ, "
                     "`research/f3_nulls/out/F3-report-1m.md`), и здесь "
                     "хвост не измерен вовсе: ни забора на имя, ни "
                     "размера, ни книги в этом потолке нет.\n")
        else:
            L.append("Событие не лучше соседей и по нетто: смена "
                     "интервала не добавляет к уровню ставки ничего.\n")
        L.append("\n**Названная тень объявленных условий смерти.** "
                 f"Условие (1) судит ЦЕНОВУЮ ногу ({ex_i['mean']:+.1f} "
                 f"против круга {NEUTRAL_COST_BP:.0f}), тогда как деньги "
                 "механики объявлены раздельно — ход цены и начисления, — "
                 f"и с начислениями нетто выходит {ev_net:+.1f}. Порог не "
                 "меняется и вердикт остаётся: правило «не менять пороги "
                 "после результата» существует ровно ради таких моментов. "
                 "Но тень названа здесь числом, а не спрятана, — так же, "
                 "как F1 назвала дефект в выводе своей П1.\n")
    L.append("\nПорог отношения — **1.5**, критерий 8 спеки 06, которым "
             "умерла гипотеза 5 (там вышло 0.51× и 0.07×). Отношение "
             "считается тем же кодом, что в L3 (`run.ratio_cell`): у "
             "отрицательного знаменателя отношение бессмысленно, и число "
             "вида «−4×» печатать нельзя.\n")
    L.append("\nГлавная прочитка требует от контроля ТОЙ ЖЕ стороны: заявка "
             "сказала «того же дециля |ставки|» и знака не назвала, а "
             "лонг имени, которое нам платит, и лонг имени, которому "
             "платим мы, — разные сделки. Вторая прочитка стоит рядом "
             "диагностикой, а не подменяется молча.\n")

    L.append("\n## (г) Ставка события против предела своего ряда\n\n")
    if rank_share is None:
        L.append("Не измерено: ни у одного события не набралось истории "
                 "ставок для ранга. Это отсутствие меры, а не ноль.\n")
    else:
        L.append(f"Доля событий, у которых |ставка| выше 90-го процентиля "
                 f"СОБСТВЕННОГО прошлого ряда: **{rank_share:.2f}**. "
                 "Посылка механики — «интервал укорачивают, когда ставка "
                 "упёрлась в предел»; доля заметно ниже половины означала "
                 "бы, что объявление площадки описывает не то, что лежит "
                 "в данных.\n")

    L.append("\n## Нуль: та же минута, другое имя\n\n")
    if not null["n"]:
        L.append("Не посчитан.\n")
    else:
        L.append(f"Превышение на перемешанных метках: среднее "
                 f"**{null['mean']:+.1f}** б.п., медиана "
                 f"{null['med']:+.1f} по {null['n']} событиям. Нуль "
                 "около нуля — свидетельство, что мера не смещена; нуль, "
                 "уехавший вместе с наблюдением, означал бы сломанную "
                 "загрузку, которая выглядит ровно как «эффекта нет».\n")

    L.append("\n## Окно ДО метки: не поздно ли мы приходим\n\n")
    if not ex_pre["n"]:
        L.append("Не измерено.\n")
    else:
        L.append(f"Превышение в зеркальном окне ТОЙ ЖЕ длины перед меткой: "
                 f"среднее **{ex_pre['mean']:+.1f}**, медиана "
                 f"{ex_pre['med']:+.1f} б.п. по {ex_pre['n']} событиям. "
                 "Если превышение живёт до метки и исчезает после, "
                 "переход есть метка уже случившегося хода, и торговать "
                 "нечем — это четвёртое объявленное условие смерти.\n")
        if pre_own["n"] and own_i["n"]:
            L.append(f"\nСырой ход в сторону позиции: **{pre_own['mean']:+.1f}** "
                     f"б.п. ДО метки (медиана {pre_own['med']:+.1f}) против "
                     f"{own_i['mean']:+.1f} после (медиана "
                     f"{own_i['med']:+.1f}). "
                     + ("Имя приходит к событию уже пройдя ход и отдаёт "
                        "его назад: площадка укорачивает интервал ПОСЛЕ "
                        "движения, а не перед ним."
                        if pre_own["mean"] > 0 > own_i["mean"] else
                        "Знаки до и после согласованы — ход продолжается, "
                        "а не отдаётся.") + "\n")

    lines, dead, doubt = verdict(dens, ex_i, c2, rank_share, null, ex_pre,
                                 meta["measured"])
    L.append("\n## Вердикт\n\n")
    L.append("| условие смерти | замер | срабатывает |\n|---|---|---|\n")
    for a, b, c in lines:
        L.append(f"| {a} | {b} | {c or '—'} |\n")
    if doubt and not dead:
        L.append("\n**Вердикта нет.** " + "; ".join(doubt)
                 + ". Числа выше посчитаны и годятся диагностикой, но "
                   "закрытием механики не являются.\n")
    elif dead:
        L.append("\n**Механика закрыта потолком.** Сработало: "
                 + "; ".join(dead) + ".\n")
        if doubt:
            L.append("\nРядом стоит сомнение в самом замере: "
                     + "; ".join(doubt) + ".\n")
    else:
        L.append("\n**Потолок пройден.** Ни одно объявленное условие "
                 "смерти не сработало — можно строить механику живой "
                 "книги. Это не вердикт о рынке: числа посчитаны с "
                 "недостижимо ранним входом и без проскальзывания.\n")
    if meta.get("partial"):
        L.append(f"\n**Окно ЧАСТИЧНОЕ:** {meta['start']}…{meta['end']} "
                 f"вместо всей истории с {meta['full_start']}. Отчёт "
                 "назван своим именем и полным прогоном не является — "
                 "частичный прогон под именем полного проект уже "
                 "публиковал однажды (трёхсуточный D1). Полная история "
                 "считается заданием очереди, команда в RUNBOOK.\n")

    L.append("\n## Диагностика (вердикта по ней нет)\n\n")
    L.append("| срез | событий | среднее | медиана |\n|---|--:|--:|--:|\n")
    for name, a in diag:
        if not a["n"]:
            L.append(f"| {name} | 0 | — | — |\n")
            continue
        L.append(f"| {name} | {a['n']} | {a['mean']:+.1f} | "
                 f"{a['med']:+.1f} |\n")
    L.append("\nСторона «ставка > 0» (шорт у верхнего предела) в ячейку "
             "вердикта не входит по критерию владельца: хвост сквиза "
             "против шорта не ограничен ничем, и укус почти наверняка "
             "глубже десяти.\n")
    L.append("\n## Чего этот потолок НЕ говорит\n\n")
    L.append("- Он не проверяет книгу: ни забора на имя, ни размера "
             "обратно σ, ни конкуренции за слоты здесь нет.\n")
    L.append("- Связь дневных денег с живыми книгами пула здесь НЕ "
             "считается: её считает потолок фабрики по своим рядам "
             "(`research/factory/ceiling.py`). Ряд «сутки → нетто» лежит "
             "в json рядом с отчётом ровно в той форме, в какой его "
             "судит правило вылета.\n")
    L.append("- Спреда в архиве нет вовсе, и число со спредом "
             "перенесено, а не измерено.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(L))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="потолок механики смены интервала")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2026-07-27")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--tol-min", type=int, default=TOL_MIN)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)          # каталог ДО счёта, не после
    t_start = datetime.now(timezone.utc)

    assets = universe_assets()
    if a.symbols:
        want = set(a.symbols.split(","))
        assets = {k: v for k, v in assets.items()
                  if v["binance_symbol"] in want}
    sym_of = {k: v["binance_symbol"] for k, v in assets.items()}
    log_(f"универсум: активов {len(assets)}, память доступно "
         f"{mem_available_mb():.0f} МиБ")

    fund = FS.load_funding(FUND_DIR, assets, set(assets),
                           symbol_field="bybit_symbol")
    if fund is None:
        raise SystemExit(f"нет каталога рядов funding: {FUND_DIR}")
    if len(fund) < FS.MIN_FUNDING_SYMBOLS and not a.symbols:
        raise SystemExit(f"рядов funding всего {len(fund)} — частичная "
                         "загрузка выдала бы себя за полную")
    log_(f"ряды funding: {len(fund)} активов")

    uni = D.universe()
    share, min_share = D.liquid_days("1m")
    start_ms = FS.ms(a.start)
    end_ms = FS.ms(a.end)
    events, all_ts, dropped = collect_events(
        fund, sym_of, uni, share, min_share, start_ms, end_ms)
    verdict_ev = [e for e in events if e["side"] == SH.side_of_rate(-1.0)]
    diag_ev = [e for e in events if e["side"] != SH.side_of_rate(-1.0)]
    if not events:
        raise SystemExit("ни одного события при непустых рядах — "
                         "это отказ замера, а не отчёт с прочерками")
    log_(f"ячейка вердикта: {len(verdict_ev)}, диагностика: {len(diag_ev)}")

    syms = sorted({e["symbol"] for e in events} | set(sym_of.values()))
    anchors = []
    for e in events:
        anchors += list(anchors_of(e).values())
    book = PriceBook(syms, anchors)
    log_(f"якорей {len(book.anchors):,}, сечение {len(syms)} имён, "
         f"матрица {book.nbytes() / 2**20:.0f} МиБ при доступных "
         f"{mem_available_mb():.0f}".replace(",", " "))
    load_prices(book, a.tol_min)

    rng = np.random.default_rng(SEED)
    rows = measure(verdict_ev, book, all_ts, fund, sym_of, rng)
    drows = measure(diag_ev, book, all_ts, fund, sym_of,
                    np.random.default_rng(SEED + 1))
    meas = [r for r in rows if np.isfinite(r["ideal_exc_bp"])]
    if not meas:
        raise SystemExit("ни одно событие не измерено при непустой "
                         "загрузке цен — отказ, а не пустой отчёт")

    d0 = SH.day_of(start_ms)
    d1 = SH.day_of(min(end_ms, int(max(e["entry_ms"] for e in events))))
    ts_all = [r["ts"] for r in meas]
    auto_ms = FS.ms(AUTO_FROM)
    # Границы срезов пересекаются с окном ПРОГОНА, а не берутся у даты
    # объявления: иначе знаменателем среза «с 2025-11-03» стали бы все
    # сутки от той даты, включая те, которых прогон не считал, и доля
    # вышла бы заниженной в разы — так и случилось на смоуке.
    a_day = SH.day_of(auto_ms)
    dens = SH.active_share(ts_all, d0, d1)
    dens_split = [("ячейка вердикта, всё окно прогона", dens)]
    if d0 < a_day:
        dens_split.append(
            (f"до {AUTO_FROM}",
             SH.active_share([t for t in ts_all if t < auto_ms],
                             d0, min(d1, a_day - 1))))
    if d1 >= a_day:
        dens_split.append(
            (f"с {AUTO_FROM}",
             SH.active_share([t for t in ts_all if t >= auto_ms],
                             max(d0, a_day), d1)))
    dens_split.append(
        ("диагностика: ставка > 0",
         SH.active_share([r["ts"] for r in drows
                          if np.isfinite(r["ideal_exc_bp"])], d0, d1)))
    ex_i = agg([r["ideal_exc_bp"] for r in meas])
    ex_r = agg([r["real_exc_bp"] for r in meas])
    ex_pre = agg([r.get("pre_exc_bp", np.nan) for r in meas])
    own_i = agg([r["ideal_own_bp"] for r in meas])
    fund_a = agg([r["fund_bp"] for r in meas])
    c2 = agg([r.get("c2_bp", np.nan) for r in meas])
    c2any = agg([r.get("c2any_bp", np.nan) for r in meas])
    c2_fund = agg([r.get("c2_fund_bp", np.nan) for r in meas])
    c2any_fund = agg([r.get("c2any_fund_bp", np.nan) for r in meas])
    pre_own = agg([r.get("pre_own_bp", np.nan) for r in meas])
    null = agg([r.get("null_bp", np.nan) for r in meas])
    ranks = [r["rank"] for r in meas if r["rank"] is not None]
    rank_share = (float(np.mean([x >= 0.9 for x in ranks])) if ranks
                  else None)
    diag = [("ставка > 0 (шорт у верхнего предела), идеальный вход",
             agg([r["ideal_exc_bp"] for r in drows])),
            ("ячейка вердикта, выход по возврату интервала",
             agg([r["ideal_exc_bp"] for r in meas
                  if r["exit_why"] == "интервал вернулся"])),
            ("ячейка вердикта, выход по пределу 24 ч",
             agg([r["ideal_exc_bp"] for r in meas
                  if r["exit_why"] == "предел удержания"]))]
    if len(meas) < MIN_MEASURED:
        log_(f"измерено {len(meas)} событий — меньше {MIN_MEASURED}: "
             "ячейка НЕ измерена, а не равна нулю")

    path = os.path.join(OUT, f"FSHIFT-ceiling-{a.tag}.md")
    write_report(path, {
        "when": t_start.strftime("%Y-%m-%d %H:%M UTC"),
        "start": a.start, "end": a.end, "symbols": len(syms),
        "found": len(events), "measured": len(meas),
        "full_start": ap.get_default("start"),
        "partial": (a.start != ap.get_default("start")
                    or a.end != ap.get_default("end")),
        "not_covered": dropped["площадка не охватывает"]},
        dens, ex_i, ex_r, own_i, fund_a, c2, c2any, null, rank_share,
        meas, dens_split, diag, ex_pre, c2_fund, c2any_fund, pre_own)
    lines, dead, doubt = verdict(dens, ex_i, c2, rank_share, null, ex_pre,
                                 len(meas))
    with open(os.path.join(OUT, f"fshift-ceiling-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"start": a.start, "end": a.end,
                   "found": len(events), "measured": len(meas),
                   "dropped": dropped, "density": dens,
                   "excess_ideal": ex_i, "excess_real": ex_r,
                   "excess_pre": ex_pre,
                   "raw_ideal": own_i, "funding": fund_a,
                   "control2": c2, "control2_any_sign": c2any,
                   "control2_funding": c2_fund,
                   "control2_any_sign_funding": c2any_fund,
                   "raw_pre": pre_own,
                   "null": null, "rank_share": rank_share,
                   "daily_net_bp": daily_net(meas),
                   "dead": dead, "doubt": doubt, "seed": SEED},
                  f, ensure_ascii=False)
    log_(f"отчёт: {path}")
    log_("вердикт: " + ("закрыто — " + "; ".join(dead) if dead
                        else ("вердикта нет — " + "; ".join(doubt)
                              if doubt else "потолок пройден")))
    if not a.no_publish:
        Z.publish("потолок механики смены интервала начисления funding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
