#!/usr/bin/env python3
"""Волна рынка и охрана рынком — ОДНА библиотека для книг и замеров.

Волна — средний ход прокси-имён `side_wave.PROXY` (тот же список, что у
S8) от закрытия одного часа к закрытию другого, по часовым сводкам
стакана (`s8_loop/out/summary`). Меньше `MIN_PROXY` имён с ценой — волна
за этот час НЕ ИЗМЕРЕНА (None), и это считается, а не подменяется нулём.

Охрана рынком (спека 14 §13, правило коротких книг с 2026-09-13):
позиция закрывается по закрытию часа k после входа, когда волна с входа
≥ порога книги. Исход — почасовая отметка ядра симуляции за час k:
доказано (`wave_guard`, 6100 точек), что она равна усечению симуляции в
конец часа бит в бит, поэтому второго реплея не нужно.

Здесь живут: чтение сводок (`Hours`), цены и волна (`Market`), путь
позиции из отметок (`path_of`), закрытие записи на часе (`guard_record`)
и применение охраны к записям книги (`apply_guard`). Замеры
(`tail_screen`, `path_screen`, `wave_guard`) берут это отсюда — вторая
копия волны однажды разошлась бы с первой.
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import side_wave as SWV                                       # noqa: E402

SUMMARY_DIR = os.path.join(ROOT, "research", "s8_loop", "out", "summary")
HOUR = 3600.0
PROXY = SWV.PROXY                            # волна — ТОТ ЖЕ список, что у S8
MIN_PROXY = SWV.MIN_PROXY
GUARD_EXIT = "рынок"


class Hours:
    """Часовые сводки по имени с оглядкой назад — файл дня читается раз."""

    def __init__(self, root=SUMMARY_DIR):
        self.root = root
        self._day = {}
        self.miss = 0
        self.hit = 0

    def _load(self, sym, day):
        key = (sym, day)
        if key in self._day:
            return self._day[key]
        rows = {}
        try:
            with open(os.path.join(self.root, sym, day + ".jsonl"),
                      encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("hour"):
                        rows[r["hour"]] = r
        except OSError:
            rows = {}
        if len(self._day) > 6000:
            self._day.clear()
        self._day[key] = rows
        return rows

    def row(self, sym, ts):
        """Сводка часа, в который попадает момент `ts`."""
        hour = time.strftime("%Y-%m-%d-%H", time.gmtime(float(ts)))
        r = self._load(sym, hour[:10]).get(hour)
        if r is None:
            self.miss += 1
        else:
            self.hit += 1
        return r

    def back(self, sym, ts, n):
        """Сводки n предыдущих часов, старые сначала; пропуски — None."""
        return [self.row(sym, float(ts) - k * HOUR) for k in range(n, 0, -1)]


class Market:
    """Цены из часовых сводок: ход имени, волна прокси-имён, β до входа,
    час срабатывания охраны."""

    def __init__(self, hours=None, proxies=PROXY, min_proxy=MIN_PROXY):
        self.h = hours if hours is not None else Hours()
        self.proxies = tuple(proxies)
        self.min_proxy = int(min_proxy)
        self._px, self._wave, self._kstar = {}, {}, {}
        self.wave_none = 0

    def px(self, sym, ts):
        key = (sym, int(float(ts) // HOUR))
        if key not in self._px:
            r = self.h.row(sym, ts)
            v = r.get("mid_close") if r else None
            self._px[key] = float(v) if v else None
        return self._px[key]

    def move(self, sym, t0, t1):
        a, b = self.px(sym, t0), self.px(sym, t1)
        return (b / a - 1.0) if (a and b) else None

    def wave(self, t0, t1):
        """Средний ход прокси-имён за [t0, t1]; меньше MIN_PROXY цен — нет."""
        key = (int(float(t0) // HOUR), int(float(t1) // HOUR))
        if key not in self._wave:
            ms = [m for m in (self.move(p, t0, t1) for p in self.proxies)
                  if m is not None]
            w = float(np.mean(ms)) if len(ms) >= self.min_proxy else None
            if w is None:
                self.wave_none += 1
            self._wave[key] = w
        return self._wave[key]

    def beta_pre(self, sym, at, n=72, min_n=48):
        """β и ρ имени к волне по часовым доходностям ДО входа."""
        xs, ys = [], []
        t_in = float(at) - 1.0
        for j in range(int(n)):
            t1 = t_in - j * HOUR
            w, o = self.wave(t1 - HOUR, t1), self.move(sym, t1 - HOUR, t1)
            if w is None or o is None:
                continue
            xs.append(w)
            ys.append(o)
        if len(xs) < min_n:
            return None, None, len(xs)
        x, y = np.array(xs), np.array(ys)
        vx = float(x.var())
        if vx <= 0 or float(y.var()) <= 0:
            return None, None, len(xs)
        b = float(((x - x.mean()) * (y - y.mean())).mean() / vx)
        rho = float(np.corrcoef(x, y)[0, 1])
        return b, rho, len(xs)

    def k_star(self, at, pct, kmax):
        """Первый час k ≤ kmax, к концу которого волна с входа ≥ pct %.

        Возвращает (k или None, число часов без волны до срабатывания).
        Час без волны триггером быть не может — он посчитан отдельно.
        """
        key = (int(round(float(at))), float(pct), int(kmax))
        if key not in self._kstar:
            t_in = float(at) - 1.0
            hit, missing = None, 0
            for k in range(1, int(kmax) + 1):
                w = self.wave(t_in, t_in + k * HOUR)
                if w is None:
                    missing += 1
                    continue
                if w >= float(pct) / 100.0:
                    hit = k
                    break
            self._kstar[key] = (hit, missing)
        return self._kstar[key]


def path_of(rec):
    """Путь позиции по часам из отметок ядра: {k: pnl долей маржи}.

    k = 1 — конец первого часа после входа (`at` — конец часа решения,
    отметка часа несёт его начало). Час без бара наследует прошлую отметку;
    до первого бара позиция стоит по цене входа — pnl 0, как у ядра.
    """
    marks = rec.get("marks") or []
    if not marks:
        return None
    at = float(rec["at"])
    cum, raw = 0.0, {}
    for hr, d in marks:
        cum += float(d)
        k = max(1, int(round((float(hr) - at) / HOUR)) + 1)
        raw[k] = cum
    K = max(raw)
    out, last, lead = {}, 0.0, 0
    first = min(raw)
    for k in range(1, K + 1):
        if k in raw:
            last = raw[k]
        elif k < first:
            lead += 1
        out[k] = last
    return {"cum": out, "K": K, "peak": max(out.values()), "final": out[K],
            "lead_gap": lead}


def exit_px_of(rec, pnl, end_ts):
    """Цена, при которой позиция стоит `pnl` долей маржи, — из ЗАПОЛНЕНИЙ.

    Отметка ядра — pnl на всю зарезервированную маржу, а работает в ней
    только заполненный объём: у книги без доливов это одна ступень из
    четырёх, четверть. Прежняя формула «вход × (1 − pnl/плечо)» считала,
    что работает вся маржа, и восстанавливала ход цены вчетверо меньше
    настоящего: RAREUSDT 25.09 — выход «рынок» показан по 0.016103, а
    закрытие часа было 0.01583 (−170 б.п.); на всех 24 отметках ход из
    формулы ровно в 4 раза меньше хода принтов (проба 26.09). Точка
    выхода вставала там, где цены не было.

    Тождество ядра: pnl = d·(qty·px − cash)/capital при capital = 1,
    cash = Σ w·lev, qty = Σ w·lev/цена по ступеням, заполненным к
    `end_ts`; отсюда px = (cash + d·pnl)/qty. Заполнений нет — None:
    цену не выдумываем.
    """
    lev = float(rec.get("lev") or 0)
    fills = [f for f in (rec.get("fills") or ())
             if f and float(f[0]) <= float(end_ts)]
    if not lev or not fills:
        return None
    try:
        cash = sum(float(w) * lev for _t, _p, w in fills)
        qty = sum(float(w) * lev / float(p) for _t, p, w in fills)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if qty <= 0:
        return None
    d = -1.0 if (rec.get("side") or "long") == "short" else 1.0
    return (cash + d * float(pnl)) / qty


def guard_record(rec, k, why=GUARD_EXIT):
    """Та же запись, закрытая на отметке часа k: pnl ядра, срез отметок.

    Издержки те же (круг на заполненный нотионал), funding кассе даст
    короткий срок сам. Цена выхода — из pnl и ЗАПОЛНЕНИЙ (`exit_px_of`),
    для показа; без заполнений поле не пишется.
    """
    p = path_of(rec)
    c = float(p["cum"][k])
    at = float(rec["at"])
    marks = [m for m in rec["marks"]
             if int(round((float(m[0]) - at) / HOUR)) + 1 <= k]
    new = dict(rec, pnl=c, exit_ts=at + k * HOUR - 1.0, exit=why,
               marks=marks, state="closed")
    # цена выхода — из заполнений; неизвестна — None, а не цена ЧУЖОГО
    # выхода записи (срок, пол), которая стояла бы в поле по наследству
    new["exit_px"] = exit_px_of(rec, c, new["exit_ts"])
    if rec.get("pnl_net") is not None:
        new["pnl_net"] = c - (float(rec["pnl"]) - float(rec["pnl_net"]))
    return new


def apply_guard(recs, pct, mkt, kmax, why=GUARD_EXIT):
    """Охрана рынком над записями ОДНОЙ книги.

    Закрытая запись меняется, если триггер пришёл СТРОГО до её выхода;
    открытая — если триггер в уже прожитом часе (сводка часа есть только
    после его закрытия, отметка за него — тоже). Запись без отметок не
    трогается и считается отдельно.
    """
    out = []
    st = {"offered": len(recs), "closed_by_market": 0, "open_closed": 0,
          "no_marks": 0, "hours_no_wave": 0, "checked": 0}
    for r in recs:
        p = path_of(r)
        if not p:
            out.append(r)
            st["no_marks"] += 1
            continue
        closed = (r.get("state") or "closed") == "closed"
        last = min(int(kmax), p["K"] - 1 if closed else p["K"])
        if last < 1:
            out.append(r)
            continue
        k, miss = mkt.k_star(float(r["at"]), pct, last)
        st["hours_no_wave"] += miss
        st["checked"] += 1
        if k is None:
            out.append(r)
            continue
        out.append(guard_record(r, k, why=why))
        st["closed_by_market"] += 1
        if not closed:
            st["open_closed"] += 1
    return out, st
