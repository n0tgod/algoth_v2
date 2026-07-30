#!/usr/bin/env python3
"""
Живой детектор: уровни, события поглощения и бумажные сделки.

Что это и чем не является
-------------------------

Это **наблюдение, а не торговля**. Замеры T1–T4 показали, что у
поглощения, определённого по принтам, направленного содержания нет:
ожидание отрицательное и по агрессии, и против неё, а исходы ложатся на
случайность. Сделки здесь рисуются не потому, что они прибыльны, а
чтобы владелец видел, **туда ли** детектор показывает — совпадают ли его
метки с тем, что видно в стакане.

Правила те же, что в замерах, и это важно
-----------------------------------------

Уровни, шум и геометрия сделки берутся из `t4_structure/levels.py` —
того же кода, что считал отчёты. Второй копии не заводится: расхождение
между тем, что показано, и тем, что померено, обесценило бы и то и
другое.

Отличается только способ подачи данных: там массив за сутки, здесь
кольцевой буфер, который дополняется каждую секунду. Согласие двух
реализаций детектора поглощения проверяется тестом на одних и тех же
данных.

Правило входа
-------------

Событие: за окно в 60 секунд агрессивный объём одной стороны выше
обычного в N раз, перевес стороны не меньше 0.3, цена ушла против
поглощающего не больше половины обычного хода **и** стоит у
структурного уровня. Вход — по следующей сделке (лимитное исполнение не
предполагается), стоп за уровнем на один шум, цель на ближайшем уровне
впереди.
"""

import os
import sys
import time
from collections import deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(RESEARCH, "t4_structure"))
import levels as LV                                       # noqa: E402

WINDOW_SEC = 60
VOL_MULT = 5.0
MOVE_MULT = 0.5
IMB = 0.3
TOUCH_NOISE = 0.5
STOP_NOISE = 1.0
MIN_RR = 1.5
MAX_HOLD_SEC = 4 * 3600
COST_BP = 11.0
KEEP_SEC = 4 * 3600               # сколько секунд истории держим
DEDUP_SEC = 60                    # не чаще одного события в минуту на символ


def absorb_metrics(buy, sell, close, w, vol_mult, move_mult, imb, side):
    """Измеренные величины последнего окна и вердикт по ним.

    Возвращает словарь, а не «да/нет», намеренно: без чисел «событий
    нет» неотличимо от «детектор сломан», и смотреть не на что. Правило
    то же, что в `tape.absorption`, пороги относительные — объём в разах
    от обычного для этого символа, допуск на движение в долях обычного
    хода за то же окно.
    """
    out = {"vol_x": None, "imb": None, "move_x": None, "ok": False,
           "why": "мало истории"}
    n = len(close)
    if n < w * 3:
        return out
    press = sell if side < 0 else buy
    other = buy if side < 0 else sell
    win_press = float(np.sum(press[-w:]))
    win_other = float(np.sum(other[-w:]))
    tot = win_press + win_other
    if tot <= 0:
        out["why"] = "нет объёма"
        return out
    out["imb"] = round((win_press - win_other) / tot, 3)
    # Обычный объём окна — медиана скользящих сумм по всей истории.
    c = np.concatenate([[0.0], np.cumsum(press)])
    sums = c[w:] - c[:-w]
    sums = sums[sums > 0]
    if len(sums) < 5:
        return out
    med = float(np.median(sums))
    if med <= 0:
        out["why"] = "нет обычного объёма"
        return out
    out["vol_x"] = round(win_press / med, 2)
    # Ход окна и обычный ход окна.
    # Смещение окна ровно такое же, как в `tape.absorption`: конец окна
    # против его начала, то есть w−1 шагов назад. Разница в один шаг
    # рассогласовала бы живой детектор с тем, чем считаны отчёты.
    move = close[-1] / close[-w] - 1.0 if close[-w] > 0 else np.nan
    moves = (close[w - 1:] / np.maximum(close[:len(close) - w + 1], 1e-12)
             - 1.0)
    moves = moves[np.isfinite(moves)]
    if not np.isfinite(move) or len(moves) < 5:
        return out
    typ = float(np.median(np.abs(moves)))
    allow = max(move_mult * typ, 1e-9)
    out["move_x"] = round((move if side < 0 else -move) / allow, 2)
    held = move >= -allow if side < 0 else move <= allow
    if out["vol_x"] < vol_mult:
        out["why"] = "объём ниже порога"
    elif out["imb"] < imb:
        out["why"] = "давление двустороннее"
    elif not held:
        out["why"] = "цена ушла"
    else:
        out["ok"], out["why"] = True, "условия выполнены"
    return out


class Live:
    """Кольцевая история одного символа и его бумажные сделки."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.sec = deque(maxlen=KEEP_SEC)      # (t, buy, sell, hi, lo, close)
        self.cur = None                        # накапливаемая секунда
        self.levels = ([], [], float("nan"), float("nan"))
        self.levels_at = 0.0
        self.open = []                         # незакрытые бумажные сделки
        self.done = deque(maxlen=40)
        self.last_event = 0.0
        self.last_px = None
        self.diag = {-1: {}, 1: {}}

    # --- поток --------------------------------------------------------
    def on_trade(self, t):
        p, v, side = t["p"], t["v"], t["side"]
        self.last_px = p
        sec = int(t["ts"] // 1000)
        if self.cur is None or self.cur[0] != sec:
            self.close_second(sec)
        c = self.cur
        if side > 0:
            c[1] += p * v
        else:
            c[2] += p * v
        c[3] = max(c[3], p)
        c[4] = min(c[4], p)
        c[5] = p

    def close_second(self, sec):
        if self.cur is not None:
            self.sec.append(tuple(self.cur))
        self.cur = [sec, 0.0, 0.0, -np.inf, np.inf,
                    self.last_px if self.last_px else np.nan]

    def arrays(self):
        if len(self.sec) < 10:
            return None
        a = np.array(self.sec, dtype=np.float64)
        close = a[:, 5]
        ok = np.isfinite(close) & (close > 0)
        if ok.sum() < 10:
            return None
        return a[ok]

    # --- уровни -------------------------------------------------------
    def minute_frames(self, a):
        """Секунды -> минуты, в том же виде, какой ждёт `levels.build`."""
        t = (a[:, 0] // 60).astype(np.int64)
        keys, idx = np.unique(t, return_inverse=True)
        n = len(keys)
        H = np.full(n, -np.inf)
        L = np.full(n, np.inf)
        V = np.zeros(n)
        S = np.zeros(n)
        np.maximum.at(H, idx, a[:, 3])
        np.minimum.at(L, idx, a[:, 4])
        np.add.at(V, idx, a[:, 1] + a[:, 2])
        np.add.at(S, idx, (a[:, 1] + a[:, 2]) * a[:, 5])
        P = np.where(V > 0, S / np.maximum(V, 1e-12), (H + L) / 2)
        return keys * 60.0, H, L, P, V

    def refresh_levels(self, now):
        """Уровни пересчитываются раз в минуту: структура медленная."""
        if now - self.levels_at < 60:
            return
        a = self.arrays()
        if a is None:
            return
        t, H, L, P, V = self.minute_frames(a)
        n = len(t)
        # На живом потоке истории меньше суток, поэтому окно построения
        # равно тому, что накопилось; требование к минимуму — тоже.
        px, kinds, noise, slow = LV.build(
            t, H, L, P, V, now_i=n, prev_day_hl=None, min_history=20)
        if len(px) == 0 and n >= 20:
            # Истории мало для полок — но круглые числа и экстремумы
            # накопленного окна доступны сразу, и это лучше пустоты.
            noise = LV.noise_px(H, L, P)
            if np.isfinite(noise) and noise > 0:
                px = list(LV.round_levels(P[-1], noise))
                kinds = ["круглое"] * len(px)
                px.append(float(np.nanmax(H)))
                kinds.append("максимум окна")
                px.append(float(np.nanmin(L)))
                kinds.append("минимум окна")
                order = np.argsort(px)
                px = np.asarray(px)[order]
                kinds = [kinds[i] for i in order]
        self.levels = (px, kinds, noise, slow)
        self.levels_at = now

    # --- события и бумажные сделки ------------------------------------
    def candles(self, a, minutes=120):
        """Минутные свечи из накопленных секунд — для графика страницы."""
        if a is None or len(a) < 60:
            return []
        t, H, L, P, V = self.minute_frames(a)
        # Открытие и закрытие минуты берём по краям её секунд.
        keys = (a[:, 0] // 60).astype(np.int64)
        uniq = np.unique(keys)
        out = []
        for k in uniq[-minutes:]:
            m = a[keys == k]
            out.append([float(k * 60), float(m[0, 5]),
                        float(np.max(m[:, 3])), float(np.min(m[:, 4])),
                        float(m[-1, 5]), float(np.sum(m[:, 1] + m[:, 2]))])
        return out

    def check(self, now):
        self.refresh_levels(now)
        self.update_open(now)
        px, kinds, noise, _ = self.levels
        if len(px) == 0 or not np.isfinite(noise) or noise <= 0:
            return None
        if now - self.last_event < DEDUP_SEC or self.open:
            return None
        a = self.arrays()
        if a is None:
            return None
        w = WINDOW_SEC
        buy, sell = a[:, 1], a[:, 2]
        close, hi, lo = a[:, 5], a[:, 3], a[:, 4]
        price = float(close[-1])
        for side in (-1, 1):
            m = absorb_metrics(buy, sell, close, w, VOL_MULT, MOVE_MULT,
                               IMB, side)
            self.diag[side] = m
            if not m["ok"]:
                continue
            near = LV.nearest(px, kinds, price, TOUCH_NOISE * noise)
            if near is None:
                continue
            lvl, kind = near
            long = side < 0
            stop = lvl - STOP_NOISE * noise if long else lvl + STOP_NOISE * noise
            tgt = LV.ahead(px, price, long, STOP_NOISE * noise)
            if tgt is None:
                continue
            entry = price
            if (long and (stop >= entry or tgt <= entry)) or \
               (not long and (stop <= entry or tgt >= entry)):
                continue
            stop_bp = abs(entry - stop) / entry * 1e4
            tgt_bp = abs(tgt - entry) / entry * 1e4
            rr = (tgt_bp - COST_BP) / max(stop_bp, 1e-9)
            if rr < MIN_RR:
                continue
            tr = {"t": now, "sym": self.symbol, "side": side,
                  "long": long, "entry": entry, "stop": stop,
                  "target": tgt, "level": lvl, "kind": kind,
                  "stop_bp": round(stop_bp, 1), "rr": round(rr, 2),
                  "state": "открыта", "pnl_bp": 0.0, "r": 0.0,
                  "held": 0}
            self.open.append(tr)
            self.last_event = now
            return tr
        return None

    def update_open(self, now):
        if not self.open or self.last_px is None:
            return
        p = self.last_px
        still = []
        for tr in self.open:
            tr["held"] = int(now - tr["t"])
            sign = 1.0 if tr["long"] else -1.0
            hit_stop = p <= tr["stop"] if tr["long"] else p >= tr["stop"]
            hit_tgt = p >= tr["target"] if tr["long"] else p <= tr["target"]
            if hit_stop:
                tr["state"], exit_px = "стоп", tr["stop"]
            elif hit_tgt:
                tr["state"], exit_px = "цель", tr["target"]
            elif tr["held"] >= MAX_HOLD_SEC:
                tr["state"], exit_px = "время", p
            else:
                tr["pnl_bp"] = round(
                    sign * (p / tr["entry"] - 1.0) * 1e4 - COST_BP, 1)
                tr["r"] = round(tr["pnl_bp"] / max(tr["stop_bp"], 1e-9), 2)
                still.append(tr)
                continue
            tr["pnl_bp"] = round(
                sign * (exit_px / tr["entry"] - 1.0) * 1e4 - COST_BP, 1)
            tr["r"] = round(tr["pnl_bp"] / max(tr["stop_bp"], 1e-9), 2)
            self.done.appendleft(tr)
        self.open = still

    def view(self):
        px, kinds, noise, _ = self.levels
        a = self.arrays()
        near = None
        if len(px) and self.last_px and np.isfinite(noise) and noise > 0:
            d = min(abs(np.asarray(px) - self.last_px))
            near = round(float(d) / noise, 2)      # в единицах шума
        return {
            "history_min": round(len(self.sec) / 60.0, 1),
            "near_x": near,
            "diag": {"long": self.diag.get(-1, {}),
                     "short": self.diag.get(1, {})},
            "touch_x": TOUCH_NOISE, "vol_mult": VOL_MULT, "imb": IMB,
            "candles": self.candles(a),
            "levels": [{"p": float(p), "kind": k}
                       for p, k in zip(list(px), list(kinds))],
            "noise_bp": (round(noise / self.last_px * 1e4, 1)
                         if noise and self.last_px and np.isfinite(noise)
                         else None),
            "open": list(self.open),
            "done": list(self.done),
        }


class Signals:
    """Живые детекторы по всем символам."""

    def __init__(self, symbols):
        self.by = {s: Live(s) for s in symbols}

    def on_trade(self, t):
        live = self.by.get(t["s"])
        if live is not None:
            live.on_trade(t)

    def tick(self, now=None):
        now = now if now is not None else time.time()
        out = []
        for live in self.by.values():
            live.close_second(int(now))
            ev = live.check(now)
            if ev is not None:
                out.append(ev)
        return out

    def view(self, sym):
        live = self.by.get(sym)
        return live.view() if live else {"levels": [], "open": [], "done": []}
