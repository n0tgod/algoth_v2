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

sys.path.insert(0, HERE)
import absorb as AB                                       # noqa: E402

WINDOW_SEC = 60
VOL_MULT = 5.0
MOVE_MULT = 0.5
IMB = 0.3
TOUCH_NOISE = 0.5
STOP_NOISE = 1.0
MIN_RR = 1.5
MAX_HOLD_SEC = 4 * 3600
# Промежуток в ленте больше этого считается ДЫРОЙ, а не тишиной
# рынка: у наших символов сделки идут чаще. Через дыру исход
# досчитывается консервативно — см. `finish_from_tape`.
GAP_SEC = 5.0
COST_BP = 11.0
KEEP_SEC = 4 * 3600               # сколько секунд истории держим
DEDUP_SEC = 60                    # не чаще одного события в минуту на символ
# Сколько закрытых сделок держим в памяти для показа. История целиком
# живёт в файлах: первая версия хранила сорок штук ТОЛЬКО в памяти, и
# сделки, открывавшиеся при владельце, исчезали и по переполнению, и по
# перезапуску. Память — витрина, источник истины — диск.
DONE_KEEP = 400
# Ставить ли стоп за структуру. Выключатель нужен не для настройки, а
# для честного сравнения: воспроизведение прогоняет одни и те же
# записанные данные дважды — прежней геометрией и новой, — и разницу
# тогда можно отнести к геометрии, а не к другому куску рынка.
STRUCTURAL_STOP = True
# Версия правил. Поднимается ВСЯКИЙ раз, когда меняется то, как
# принимается решение или строится сделка. Нужна не для порядка:
# подъём истории поднимает трое суток сделок, и после правки правила в
# сводке смешиваются две геометрии — числа становятся бессмысленными, а
# на вид остаются осмысленными. Сделки прежних версий не удаляются, они
# просто не идут в статистику текущей.
#   1 — стоп долей шума (до 2026-07-31)
#   2 — стоп за экстремумом и накоплением
#   3 — цель на ближайшем уровне, ОПРАВДЫВАЮЩЕМ риск
#   4 — пол стопа по крупнейшей свече окна, а не по медианной
#   5 — стоп считается по свечам ДО СЕКУНДЫ ВХОДА, а не до последнего
#       пересчёта уровней: свечи прокола в данных могло не быть вовсе
RULES_VERSION = 5


def outcome_at(tr, p, now):
    """Что стало со сделкой при цене `p` в момент `now`.

    Возвращает `(состояние, цена выхода)` либо `None`, если ещё жива.

    Вынесено отдельно намеренно: тем же правилом закрывает сделки живой
    детектор и досчитывает оборванные `finish_from_tape`. Две копии
    одного правила однажды разошлись бы, и тогда досчитанная сделка
    отличалась бы от живой, а обе выглядели бы правдоподобно.

    Ничья решается ПРОТИВ нас — стоп проверяется первым. То же правило
    в T3/T4, и менять его здесь нельзя: досчёт стал бы мягче живого
    счёта, то есть льстил бы результату.
    """
    if (p <= tr["stop"]) if tr["long"] else (p >= tr["stop"]):
        return "стоп", tr["stop"]
    if (p >= tr["target"]) if tr["long"] else (p <= tr["target"]):
        return "цель", tr["target"]
    if int(now - tr["t"]) >= MAX_HOLD_SEC:
        return "время", p
    return None


def finish_from_tape(tr, prints, gap_sec=GAP_SEC):
    """Досчитать оборванную сделку по записанной ленте.

    Владелец: «оборванных сделок быть не должно, история цены есть,
    их можно досчитать». Верно, и вот с какой оговоркой.

    **Лента имеет дыру ровно там, где она нужнее всего.** Сделка
    оборвалась потому, что процесс остановили, а записывает ленту тот
    же процесс: секунды простоя в записи отсутствуют. Пройти по ленте
    насквозь, будто в дыре ничего не происходило, — это ровно то
    молчание, которое стенд ловит у себя третий день подряд.

    Поэтому дыра не игнорируется, а учитывается двумя способами:

    * если сделка разрешилась ДО первой дыры, исход настоящий;
    * если разрешение пришлось на цену ПОСЛЕ дыры, выход берётся по
      **худшей** из двух — уровня и первой цены после дыры. Цена могла
      пройти уровень разрывом, и заполнение по уровню было бы подарком.
      Тот же довод, по которому S1 не верил стопу на разрывах.

    Размер слепого места пишется в сделку числом (`blind_sec`): его
    надо видеть, а не выводить из молчания.

    Возвращает закрытую сделку либо `None`, если лента до разрешения не
    дотянулась — тогда честнее пометка, чем выдуманный исход.
    """
    if not prints:
        return None
    t0 = float(tr.get("t") or 0)
    if not (tr.get("stop") and tr.get("target")) or not t0:
        return None
    prev, blind = t0, 0.0
    for r in prints:
        try:
            ts = float(r["ts"]) / 1000.0
            p = float(r["p"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts <= t0:
            continue
        if ts - prev > gap_sec:
            blind = max(blind, ts - prev)
        prev = ts
        got = outcome_at(tr, p, ts)
        if got is None:
            continue
        state, exit_px = got
        if blind > 0 and state in ("стоп", "цель"):
            # Через дыру уровень мог быть пройден разрывом: берём
            # худшее из уровня и первой доступной после неё цены.
            exit_px = min(exit_px, p) if tr["long"] else max(exit_px, p)
        sign = 1.0 if tr["long"] else -1.0
        out = dict(tr)
        out["state"], out["exit"] = state, exit_px
        out["closed_at"] = ts
        out["held"] = int(ts - t0)
        out["pnl_bp"] = round(
            sign * (exit_px / tr["entry"] - 1.0) * 1e4 - COST_BP, 1)
        out["r"] = round(out["pnl_bp"] / max(tr.get("stop_bp") or 1e-9, 1e-9), 2)
        out["blind_sec"] = round(blind, 1)
        return out
    return None


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
        self.frames = (None, None, None, None, None)
        self.levels_at = 0.0
        self.open = []                         # незакрытые бумажные сделки
        self.done = deque(maxlen=DONE_KEEP)
        self.seq = 0                           # номер сделки внутри символа
        # Поглощение в стакане — второе правило, идущее рядом с первым.
        # Своя защёлка и свой слот на каждое правило: если бы они делили
        # один, сработавшее первым запрещало бы второе, и контрольная
        # рука перестала бы быть контрольной.
        self.bk = AB.Tracker(symbol)
        self.last_event = {"лента": 0.0, "стакан": 0.0}
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

    def stop_frames(self):
        """Свечи ДО СЕКУНДЫ РЕШЕНИЯ, а не до последнего пересчёта уровней.

        Уровни (полки, круглые числа) пересчитываются раз в минуту — они
        медленные, и это правильно. Но стоп считается по экстремуму и по
        крупнейшей свече окна, а вход случается ровно на резком движении,
        то есть на той самой свече, которой в `self.frames` может ещё не
        быть: между пересчётами проходит до шестидесяти секунд.

        Владелец увидел это на ARBUSDT: вход 10:05:42 после прокола до
        0.07578, стоп встал в 18.4 б.п. при проколе на 26 — то есть НАД
        лоем, хотя правило требует за него. Числа подтвердили: стоп задан
        «крупнейшей свечой», а не экстремумом, потому что экстремума в
        данных не было.

        Заглядывания вперёд здесь нет: буфер секунд содержит только то,
        что уже случилось к моменту решения.
        """
        a = self.arrays()
        return None if a is None else self.minute_frames(a)

    def refresh_levels(self, now):
        """Уровни пересчитываются раз в минуту: структура медленная."""
        if now - self.levels_at < 60:
            return
        a = self.arrays()
        if a is None:
            return
        t, H, L, P, V = self.minute_frames(a)
        self.frames = (t, H, L, P, V)
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
    def candles(self, a, minutes=240):
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
        # Ведение открытых сделок вынесено в `Signals.tick`: закрытие
        # обязано попасть на диск, а для этого его должен увидеть тот,
        # кто умеет писать. Порядок вызовов прежний.
        self.refresh_levels(now)
        px, kinds, noise, _ = self.levels
        if len(px) == 0 or not np.isfinite(noise) or noise <= 0:
            return None
        if now - self.last_event["лента"] < DEDUP_SEC or \
                any(t["rule"] == "лента" for t in self.open):
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
            tr = self.make_trade(now, side < 0, lvl, kind, price, noise, px,
                                 "лента")
            if tr is not None:
                return tr
        return None

    def make_trade(self, now, long, lvl, kind, price, noise, px, rule):
        """Собрать сделку. Одна реализация геометрии на оба правила.

        Меняется ровно повод для входа; стоп за уровнем на один шум,
        цель на ближайшем структурном уровне впереди и вход по следующей
        сделке остаются теми же, что в замерах T3 и T4. Тогда разницу
        между правилами можно отнести к поводу, а не к другой сделке.

        Отказ называет причину в `last_refusal`: сделка, которую правило
        не берёт, — это результат, а не пустота, и на графике она обязана
        быть видна.
        """
        self.last_refusal = ""
        # Стоп за структурой, а не в долях шума. Прежний «уровень минус
        # один шум» давал 5 б.п. при круге издержек 11 — стоп сидел
        # внутри обычной минутной свечи. Долевой остаётся полом: он
        # ставит стоп не ближе, чем раньше, но не ограничивает сверху.
        base = lvl - STOP_NOISE * noise if long else lvl + STOP_NOISE * noise
        why = "шум"
        # Свечи берутся свежие, до секунды решения: в `self.frames` той
        # свечи, на которой мы входим, может ещё не быть — уровни
        # пересчитываются раз в минуту.
        fr = self.stop_frames() or self.frames
        got = (LV.structural_stop(fr[1], fr[2], px, price, long, noise)
               if STRUCTURAL_STOP else None)
        stop = base
        if got is not None:
            cand, why = got
            if (long and cand < base) or (not long and cand > base):
                stop = cand
            else:
                why = "шум"
        entry = price
        # Пол по КРУПНЕЙШЕЙ свече окна, а не по медианной. Структура
        # сама по себе близости не запрещает: если вход стоит у только
        # что сделанного экстремума, «за экстремум» отстоит на единицы
        # пунктов. На FILUSDT это дало стоп 8.3 б.п. против 7.6 у
        # прежнего правила — то есть правило не сработало вовсе, и
        # сделку сняла обычная для того получаса свеча.
        burst = LV.burst_px(fr[1], fr[2])
        if np.isfinite(burst) and burst > 0 and abs(entry - stop) < burst:
            stop = entry - burst if long else entry + burst
            why = "крупнейшая свеча"
        if (long and stop >= entry) or (not long and stop <= entry):
            self.last_refusal = "стоп оказался по ту сторону входа"
            return None
        stop_bp = abs(entry - stop) / entry * 1e4
        # Цель — не ближайший уровень, а ближайший ИЗ ОПРАВДЫВАЮЩИХ риск.
        # Уровень в двух шагах от входа отношения не даёт; целиться в
        # него значит отдавать движение, ради которого и входили.
        def worth(v):
            bp = abs(v - entry) / entry * 1e4
            return (bp - COST_BP) / max(stop_bp, 1e-9) >= MIN_RR
        tgt = LV.ahead_worth(px, price, long, STOP_NOISE * noise, worth)
        if tgt is None:
            # Самый частый отказ, и его надо называть вслух: стоп в
            # столько-то пунктов требует цели впятеро дальше, а ближайший
            # уровень впереди столько не даёт. Молча пропав, такой вход
            # выглядит на графике как исчезнувшая сделка — владелец
            # именно это и увидел.
            self.last_refusal = (f"стоп {stop_bp:.1f} б.п., "
                                 f"ни один уровень впереди не даёт 1:{MIN_RR}")
            return None
        if (long and tgt <= entry) or (not long and tgt >= entry):
            self.last_refusal = "цель оказалась по ту сторону входа"
            return None
        tgt_bp = abs(tgt - entry) / entry * 1e4
        rr = (tgt_bp - COST_BP) / max(stop_bp, 1e-9)
        self.seq += 1
        tr = {"id": f"{self.symbol}-{int(now)}-{self.seq}",
              "ver": RULES_VERSION,
              "t": now, "sym": self.symbol, "side": 1 if not long else -1,
              "long": long, "entry": entry, "stop": stop,
              "target": tgt, "level": lvl, "kind": kind, "rule": rule,
              "stop_bp": round(stop_bp, 1),
              "tgt_bp": round(tgt_bp, 1), "rr": round(rr, 2),
              "stop_by": why,
              "state": "открыта", "pnl_bp": 0.0, "r": 0.0,
              "held": 0, "exit": None, "closed_at": None}
        self.open.append(tr)
        self.last_event[rule] = now
        return tr

    def on_book(self, bids, asks, now):
        """Шаг отслеживания поглощения по свежему снимку книги.

        Шум минутной свечи сюда больше не передаётся: полоса поиска
        уровня строится из хода самой ленты за окно удержания. Замер
        показал, что величины расходятся на порядок — уровень в полосе
        «два шума» стоял в 5–18 б.п. от цены при спуске за десять
        секунд в 2–7 б.п., то есть был недосягаем по построению.
        """
        sec = self.sec[-1] if self.sec else None
        self.bk.step(bids, asks, sec, now)

    def check_book(self, now):
        """Правило по стакану. Геометрия — общая с правилом по ленте."""
        if now - self.last_event["стакан"] < DEDUP_SEC or \
                any(t["rule"] == "стакан" for t in self.open):
            return None
        got = self.bk.signal()
        if got is None:
            return None
        long, lvl, _ = got
        px, kinds, noise, _ = self.levels
        if len(px) == 0 or not np.isfinite(noise) or noise <= 0:
            return None
        if self.last_px is None:
            return None
        return self.make_trade(now, long, lvl, "стакан", self.last_px,
                               noise, px, "стакан")

    def update_open(self, now):
        """Провести открытые сделки; вернуть закрывшиеся на этом шаге."""
        if not self.open or self.last_px is None:
            return []
        p = self.last_px
        still, closed = [], []
        for tr in self.open:
            tr["held"] = int(now - tr["t"])
            sign = 1.0 if tr["long"] else -1.0
            got = outcome_at(tr, p, now)
            if got is not None:
                tr["state"], exit_px = got
            else:
                tr["pnl_bp"] = round(
                    sign * (p / tr["entry"] - 1.0) * 1e4 - COST_BP, 1)
                tr["r"] = round(tr["pnl_bp"] / max(tr["stop_bp"], 1e-9), 2)
                still.append(tr)
                continue
            tr["exit"] = exit_px
            tr["closed_at"] = now
            tr["pnl_bp"] = round(
                sign * (exit_px / tr["entry"] - 1.0) * 1e4 - COST_BP, 1)
            tr["r"] = round(tr["pnl_bp"] / max(tr["stop_bp"], 1e-9), 2)
            self.done.appendleft(tr)
            closed.append(tr)
        self.open = still
        return closed

    def restore(self, rows, prints=None):
        """Поднять историю сделок с диска.

        Открытие и закрытие лежат отдельными записями. Открытие без
        закрытия означает, что процесс остановили с живой сделкой.

        Такая сделка **досчитывается по записанной ленте** — владелец
        прав, что данные для этого есть: цена лежит на диске, и пройти
        по ней вперёд от точки входа тем же правилом закрытия можно.
        Досчитать удаётся не всегда, и когда не удаётся, сделка
        по-прежнему помечается прямо, а не выбрасывается.
        """
        opened, closed = {}, {}
        for r in rows:
            key = r.get("id") or f"{r.get('sym')}-{r.get('t')}"
            (closed if r.get("ev") == "close" else opened)[key] = r
        out = []
        for key, r in opened.items():
            done = closed.get(key)
            if done is None:
                r = dict(r)
                r.pop("ev", None)
                got = finish_from_tape(r, prints) if prints else None
                if got is None:
                    r["state"] = "оборвана перезапуском"
                    r["pnl_bp"] = r["r"] = None
                    out.append(r)
                else:
                    out.append(got)
            else:
                out.append(done)
        out += [r for k, r in closed.items() if k not in opened]
        out.sort(key=lambda x: x.get("closed_at") or x.get("t") or 0)
        for r in out:
            r.pop("ev", None)
            self.done.appendleft(r)
            self.seq = max(self.seq, int(str(r.get("id", "")).rsplit("-", 1)[-1])
                           if str(r.get("id", "")).rsplit("-", 1)[-1].isdigit()
                           else 0)
        return len(out)

    def view(self, since=0.0, done_keep=20):
        """Состояние для страницы.

        `done` намеренно урезан: в памяти держатся сотни закрытых
        сделок, но пересылать их каждую секунду незачем — историю
        целиком отдаёт отдельный запрос, который делают по требованию.
        """
        px, kinds, noise, _ = self.levels
        a = self.arrays()
        near = None
        if len(px) and self.last_px and np.isfinite(noise) and noise > 0:
            d = min(abs(np.asarray(px) - self.last_px))
            near = round(float(d) / noise, 2)      # в единицах шума
        cd = self.candles(a)
        cd_full = True
        if since > 0 and cd and cd[0][0] <= since:
            # Последняя свеча ещё копится, поэтому шлётся всегда: иначе
            # страница держала бы её недостроенной до следующей минуты.
            cd = [c for c in cd if c[0] >= since - 60]
            cd_full = False
        return {
            "history_min": round(len(self.sec) / 60.0, 1),
            "near_x": near,
            "diag": {"long": self.diag.get(-1, {}),
                     "short": self.diag.get(1, {})},
            "touch_x": TOUCH_NOISE, "vol_mult": VOL_MULT, "imb": IMB,
            "book": {"лонг": self.bk.diag.get(True) or {},
                     "шорт": self.bk.diag.get(False) or {},
                     "qbig": AB.QBIG, "big": AB.BIG, "hold": AB.HOLD,
                     "eat": AB.EAT, "refill": AB.REFILL,
                     # Докуда дошла цепочка условий за жизнь процесса.
                     # «Правило молчит» и «правило молчит на третьем
                     # условии» — разные сообщения, и чинится второе.
                     "chain": self.bk.chain()},
            "candles": cd, "candles_full": cd_full,
            "done_total": len(self.done),
            "levels": [{"p": float(p), "kind": k}
                       for p, k in zip(list(px), list(kinds))],
            "noise_bp": (round(noise / self.last_px * 1e4, 1)
                         if noise and self.last_px and np.isfinite(noise)
                         else None),
            "open": list(self.open),
            "done": list(self.done)[:done_keep],
        }


class Signals:
    """Живые детекторы по всем символам."""

    def __init__(self, symbols):
        self.by = {s: Live(s) for s in symbols}

    def on_trade(self, t):
        live = self.by.get(t["s"])
        if live is not None:
            live.on_trade(t)

    def tick(self, now=None, books=None):
        """Шаг всех детекторов. Возвращает `(открытые, закрытые)`.

        `books` — текущие книги по символам; без них правило по стакану
        просто не срабатывает, а правило по ленте работает как прежде.
        """
        now = now if now is not None else time.time()
        opened, closed = [], []
        for sym, live in self.by.items():
            live.close_second(int(now))
            b = (books or {}).get(sym)
            if b is not None and b.ready:
                live.on_book(b.bids, b.asks, now)
            closed += live.update_open(now)
            for ev in (live.check(now), live.check_book(now)):
                if ev is not None:
                    opened.append(ev)
        return opened, closed

    def view(self, sym, since=0.0):
        live = self.by.get(sym)
        return live.view(since) if live else {
            "levels": [], "open": [], "done": [], "candles": [],
            "candles_full": True, "done_total": 0}

    def history(self, sym):
        """Сделки, что держим в памяти, — закрытые И ОТКРЫТЫЕ.

        Открытые обязаны быть здесь, и это исправление дефекта, а не
        удобство. Прежняя версия отдавала только `done`, поэтому
        позиция, которую детектор держит прямо сейчас, не попадала ни в
        таблицу, ни на график: в журнале «сигнал», в счётчике единица, на
        диске запись — а на странице пусто. Со стороны владельца это
        неотличимо от «сделок не находится», и ровно так он это и
        прочитал.

        В статистику они не идут сами собой: `paper.finished` берёт
        только состояния с наступившим выходом. Посчитать открытую
        нулём значило бы разбавить ожидание выдумкой — та же причина,
        по которой не считаются оборванные перезапуском.
        """
        live = self.by.get(sym)
        return (list(live.done) + list(live.open)) if live else []
