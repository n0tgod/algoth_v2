#!/usr/bin/env python3
"""
Сбор стакана и ленты площадки исполнения живьём.

Зачем
-----

Четыре замера направления ленты дали ноль: объём (T1), односторонность и
уровень (T2), сделка с микроуровнем (T3), сделка со структурным уровнем
и её зеркало (T4). Все считались по **принтам** — по уже состоявшимся
сделкам. А поглощение по определению происходит **в очереди заявок**:
крупный стоит, его выедают, он подставляет снова. По принтам «его
выкупают» и «продавцы кончились сами» выглядят одинаково.

Стакана в архивах нет ни у Bybit, ни у Binance (у второго только снимок
глубины раз в минуту по полосам). Значит единственный способ ответить —
собрать самому. Это и есть то, что читает команда, о которой говорил
владелец, и первое, чего стенд никогда не видел.

Что пишется
-----------

**Всегда, по всем символам** — снимок стакана раз в секунду (лучшие
цены и размеры, лесенка ближних уровней, накопленный объём в полосах
±0.05…0.5 %) и все сделки. Этого хватает, чтобы измерить главное:
стоит ли объём на цене и восполняется ли он после каждого удара.

**По выбранным символам** — сырой поток изменений целиком. Нужен, чтобы
проверить саму секундную свёртку: если восполнение происходит быстрее
секунды, свёртка его сгладит, и знать об этом надо из данных, а не из
предположения.

Устройство
----------

Файлы по часам, отдельно на символ, сжатые: `book/`, `trades/`, `raw/`.
Формат — по строке JSON на запись, как в архивах площадки; читается чем
угодно и дописывается без перезаписи.

Разрыв нумерации обновлений означает потерю части потока. Книга в этом
случае выбрасывается и подписка обновляется — молча продолжать нельзя,
книга разойдётся с биржей, оставаясь правдоподобной на вид.

Состояние пишется в `status.json` каждые пять секунд: сколько сообщений,
сколько сбросов, когда последнее сообщение. По нему же будет жить
страница наблюдения.

    .venv/bin/python research/b1_book/collect.py --symbols BTCUSDT,ARBUSDT
    .venv/bin/python research/b1_book/collect.py --hours 24 --raw ARBUSDT
"""

import argparse
import gzip
import json
import os
import secrets
import shutil
import signal
import ssl
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
from book import BANDS, STORE_LADDER, Book, parse_trades                 # noqa: E402
import paper                                              # noqa: E402
from signals import RULES_VERSION, Signals                # noqa: E402
from store import Writer, read_hour, read_jsonl            # noqa: E402
import web                                                # noqa: E402

WS_URL = "wss://stream.bybit.com/v5/public/linear"
# Глубина темы orderbook. Пятьдесят уровней — это НЕ проценты, а
# полсотни цен подряд, и у плотных инструментов они умещаются в точку:
# замер на живом сборщике дал охват ±1.2 б.п. у BTCUSDT и ±2.6 у
# ETHUSDT против 45–77 б.п. у остальных шести. Уровень в пяти пунктах от
# цены там не виден вовсе, то есть главный вопрос B1 — стоит ли объём на
# цене — на этих двух проверить было нечем.
#
# Плата за глубокую тему — шаг 100 мс вместо 20. Для записи она никакая:
# снимок пишется раз в секунду. Быстрый шаг важен только сырому потоку,
# по которому меряется восполнение внутри секунды, и он остаётся на
# мелкой теме.
#
# Глубина 500 у линейных контрактов НЕ существует, проверено ответом
# площадки: `error:handler not found,topic:orderbook.500.BTCUSDT`.
# Предел — 200, и он даёт ±4.2 б.п. у BTCUSDT (было 1.2) и ±11.0 у
# ETHUSDT (было 2.6). У BTC даже этого мало: самая узкая полоса требует
# пяти базисных пунктов, то есть глубина полос на нём непроверяема
# публичным потоком в принципе.
DEPTH = 50
DEEP_DEPTH = 200
DEEP = ("BTCUSDT", "ETHUSDT")
# Лестница отступления: площадка может не принять глубину, и
# тогда берём мельче, а не остаёмся без стакана вовсе.
DEPTH_LADDER = (500, 200, 50)
PING_SEC = 20
SAMPLE_SEC = 1
STATUS_SEC = 5
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "ARBUSDT", "LINKUSDT", "AVAXUSDT")


def minute_bars(rows):
    """Сделки -> минутные свечи `[t, o, h, l, c, объём]`.

    Минута без сделок отсутствует, а не выходит нулевой: пустой бар —
    пропуск, а не наблюдение с нулевым объёмом (урок A2).
    """
    by = {}
    for r in rows:
        try:
            t = int(r["ts"] // 60000) * 60
            p = float(r["p"])
            v = float(r["v"])
        except (KeyError, TypeError, ValueError):
            continue
        c = by.get(t)
        if c is None:
            by[t] = [t, p, p, p, p, p * v]
        else:
            c[2] = max(c[2], p)
            c[3] = min(c[3], p)
            c[4] = p
            c[5] += p * v
    return [by[k] for k in sorted(by)]


def signals_version():
    """Текущая версия правил — одним местом, чтобы не разъехалась."""
    return RULES_VERSION


class LogBuf:
    """Журнал для страницы: кольцо строк плюс сквозной номер.

    Номер нужен не для порядка, а чтобы страница просила только новое.
    Пересылать все шестьдесят строк каждую секунду — 4.6 КиБ в секунду
    на пустом месте, и это при том, что новых строк обычно ноль.
    """

    def __init__(self, keep=60):
        self.lines = deque(maxlen=keep)
        self.n = 0

    def add(self, line):
        self.lines.append(line)
        self.n += 1

    def since(self, k):
        """Вернуть `(всего строк, новые для того, у кого есть k)`."""
        first = self.n - len(self.lines)
        if k is None or k < first:
            return self.n, list(self.lines)
        return self.n, list(self.lines)[max(0, int(k) - first):]


class Collector:
    def __init__(self, symbols, raw_symbols, root, log, deep=DEEP):
        self.symbols = list(symbols)
        self.raw = set(raw_symbols)
        self.depth = {s: (DEEP_DEPTH if s in set(deep or ()) else DEPTH)
                      for s in symbols}
        self.books = {s: Book(s) for s in symbols}
        self.w = Writer(root, log)
        self.log = log
        self.n_msg = 0
        self.n_trades = 0
        self.n_resets = 0
        self.last_msg = 0.0
        self.started = time.time()
        self.stop = threading.Event()
        self.ws = None
        self.pending_resub = set()
        self.live = set()
        self.disk = {}
        self.samples = deque(maxlen=90)   # (момент, байт)
        self.ccache = {}                  # свечи закрытых часов
        # Кольцевые буферы для страницы наблюдения: она смотрит в память,
        # а не в файлы — между данными и глазом не должно быть выгрузки.
        self.lock = threading.Lock()
        self.mid = {s: deque(maxlen=900) for s in symbols}   # 15 минут
        self.tape = {s: deque(maxlen=120) for s in symbols}
        self.lines = LogBuf()
        self.msg_mark = (time.time(), 0)
        self.msg_rate = 0.0
        # Живой детектор: те же правила, что в замерах. Сделки бумажные,
        # это наблюдение, а не торговля — замеры T1–T4 показали, что
        # направленного содержания у события нет. Страница нужна, чтобы
        # видеть, ТУДА ли детектор показывает.
        self.sig = Signals(symbols)
        self.n_signals = 0
        self.n_closed = 0

    # --- сеть ---------------------------------------------------------
    def topics(self):
        out = []
        for s in self.symbols:
            out.append(f"orderbook.{self.depth[s]}.{s}")
            out.append(f"publicTrade.{s}")
        return out

    def send_sub(self, ws, topics):
        """Подписка по одной теме, с именем темы в `req_id`.

        Одним запросом на все шестнадцать площадка отвергает **весь**
        запрос из-за одной негодной темы: так глубокая тема стакана
        погасила сбор целиком, и в журнале это выглядело как
        «подключено, тем 16» и дальше тишина. По одной — отказ стоит
        своей темы и называет её.
        """
        for t in topics:
            try:
                ws.send(json.dumps({"op": "subscribe", "args": [t],
                                    "req_id": t}))
            except Exception as e:                        # noqa: BLE001
                self.log(f"не отправилась подписка {t}: {e}")

    def on_open(self, ws):
        self.live = set()
        self.log(f"подключено, подписываюсь на {len(self.topics())} тем")
        self.send_sub(ws, self.topics())

    def on_op(self, ws, msg):
        """Ответ на служебную команду. Молчать о нём нельзя.

        Отклонённая подписка неотличима от тишины рынка: данных нет в
        обоих случаях. Раньше такие сообщения выбрасывались, потому что
        у них нет поля `topic`.
        """
        if msg.get("op") == "pong" or msg.get("ret_msg") == "pong":
            return
        ok, req = msg.get("success"), msg.get("req_id") or ""
        if ok is False:
            self.log(f"подписка отклонена: {req or '?'} — "
                     f"{msg.get('ret_msg') or msg}")
            self.downgrade(ws, req)
        elif ok is True and req:
            self.live.add(req)

    def downgrade(self, ws, topic):
        """Стакан не принят на этой глубине — пробуем мельче.

        Список глубин у площадки свой, и он может отличаться от того,
        что написано в документации. Сбор не вправе от этого умирать:
        мельче — хуже, но это данные, а отказ — их отсутствие.
        """
        if not topic.startswith("orderbook."):
            return
        try:
            _, d, sym = topic.split(".", 2)
            d = int(d)
        except ValueError:
            return
        nxt = next((x for x in DEPTH_LADDER if x < d), None)
        if nxt is None or sym not in self.books:
            self.log(f"{sym}: глубины кончились, стакан собираться не будет")
            return
        self.depth[sym] = nxt
        self.log(f"{sym}: глубина {d} не принята, пробую {nxt}")
        self.send_sub(ws, [f"orderbook.{nxt}.{sym}"])

    def on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        topic = msg.get("topic") or ""
        if not topic:
            self.on_op(ws, msg)
            return
        self.last_msg = time.time()
        self.n_msg += 1
        if topic.startswith("orderbook."):
            sym = topic.rsplit(".", 1)[-1]
            b = self.books.get(sym)
            if b is None:
                return
            if sym in self.raw:
                self.w.write("raw", sym, msg)
            if not b.apply(msg):
                self.n_resets += 1
                self.log(f"{sym}: разрыв нумерации, переподписка")
                self.pending_resub.add(sym)
                self.live.discard(topic)
                try:
                    ws.send(json.dumps({"op": "unsubscribe",
                                        "args": [topic]}))
                except Exception:                         # noqa: BLE001
                    pass
                self.send_sub(ws, [topic])
        elif topic.startswith("publicTrade."):
            sym = topic.rsplit(".", 1)[-1]
            for t in parse_trades(msg):
                self.n_trades += 1
                self.w.write("trades", sym, t, ts=t["ts"] / 1000.0)
                d = self.tape.get(sym)
                if d is not None:
                    d.append(t)
                self.sig.on_trade(t)

    def on_error(self, ws, err):
        self.log(f"ошибка соединения: {err}")

    def on_close(self, ws, code, reason):
        self.log(f"соединение закрыто: {code} {reason}")

    # --- фоновые задачи ------------------------------------------------
    def sampler(self):
        """Снимок стакана раз в секунду по всем символам."""
        nxt = time.time() + SAMPLE_SEC
        while not self.stop.wait(max(0.0, nxt - time.time())):
            nxt += SAMPLE_SEC
            now = time.time()
            for sym, b in self.books.items():
                s = b.sample(ladder=STORE_LADDER)
                if s is not None:
                    s["t"] = round(now, 3)
                    self.w.write("book", sym, s, ts=now)
                    self.mid[sym].append(
                        (round(now, 1), (s["bid"] + s["ask"]) / 2.0))
            opened, closed = self.sig.tick(now, self.books)
            for ev in opened:
                self.n_signals += 1
                self.log(f"{ev['sym']}: сигнал [{ev['rule']}] "
                         f"{'лонг' if ev['long'] else 'шорт'} у уровня "
                         f"{ev['level']:.6g} ({ev['kind']}), стоп "
                         f"{ev['stop_bp']:.0f} б.п., отношение 1:{ev['rr']}")
                self.w.write("signals", ev["sym"], dict(ev, ev="open"), ts=now)
            for tr in closed:
                self.n_closed += 1
                self.log(f"{tr['sym']}: [{tr['rule']}] "
                         f"{tr['state']} — "
                         f"{tr['pnl_bp']:+.1f} б.п. ({tr['r']:+.2f} R), "
                         f"держали {tr['held']} с")
                self.w.write("signals", tr["sym"], dict(tr, ev="close"), ts=now)

    def snapshot(self, sym=None, since=0.0, logn=None):
        """Состояние для страницы наблюдения — прямо из памяти.

        Выдача **разностная**: страница сообщает, до какого момента у неё
        уже всё есть, и получает только новое. Полная выдача весила 58
        КиБ, из них 29 — девятьсот точек середины, пересылавшихся
        целиком каждую секунду ради одной новой. На мобильной связи
        ответ не успевал прийти до следующего опроса, и страница
        показывала «нет связи со сборщиком» на исправном сборщике.

        Если `since` старше того, что мы держим в памяти, шлём всё и
        говорим об этом флагом: догадываться на стороне страницы, полон
        ли кусок, значит однажды склеить ряд с дырой.
        """
        sym = sym if sym in self.books else self.symbols[0]
        b = self.books[sym]
        s = b.sample_view()
        bands = []
        if s:
            for w in BANDS:
                # Полоса шире того, докуда достаёт подписка, — это не
                # измерение глубины, а весь видимый стакан целиком.
                reach = min(s.get("reach_b", 0.0), s.get("reach_a", 0.0))
                bands.append({"w": round(w * 100, 3),
                              "bid": s.get(f"bq{w}", 0.0),
                              "ask": s.get(f"aq{w}", 0.0),
                              "beyond": w * 1e4 > reach})
        with self.lock:
            mid = list(self.mid[sym])
            tape = list(self.tape[sym])
            log_n, lines = self.lines.since(logn)
        mid_full = tape_full = True
        if since > 0:
            if mid and mid[0][0] <= since:
                mid = [p for p in mid if p[0] > since]
                mid_full = False
            if tape and tape[0]["ts"] / 1000.0 <= since:
                tape = [t for t in tape if t["ts"] / 1000.0 > since]
                tape_full = False
        if s:
            s["depth"] = self.depth.get(sym, DEPTH)
        return {"sym": sym, "symbols": self.symbols, "book": s,
                "bands": bands, "mid": mid, "tape": tape, "log": lines,
                "mid_full": mid_full, "tape_full": tape_full,
                "log_n": log_n, "now": round(time.time(), 3),
                "sig": self.sig.view(sym, since),
                "status": {"uptime_sec": round(time.time() - self.started, 1),
                           "messages": self.n_msg, "trades": self.n_trades,
                           "resets": self.n_resets,
                           "signals": self.n_signals,
                           "closed": self.n_closed,
                           "topics_live": len(self.live),
                           "topics": len(self.topics()),
                           "msg_per_sec": round(self.msg_rate, 1),
                           "ready": sum(1 for x in self.books.values()
                                        if x.ready),
                           "last_msg_age_sec": (
                               round(time.time() - self.last_msg, 1)
                               if self.last_msg else None),
                           "disk": self.disk_view()}}

    def candles_files(self, sym, hours=12):
        """Минутные свечи из записей — история глубже памяти сборщика.

        В памяти живут несколько часов посекундной истории, а сделки
        поднимаются за трое суток: график обрывался там, где кончался
        буфер, и прошлые сделки посмотреть было не на чем.

        Закрытый час неизменен, поэтому его свечи считаются один раз и
        кладутся в память. Текущий час пересчитывается каждый запрос —
        он ещё дописывается.
        """
        sym = sym if sym in self.books else self.symbols[0]
        now = time.time()
        hh = [datetime.fromtimestamp(now - i * 3600, timezone.utc)
              .strftime("%Y-%m-%d-%H")
              for i in range(int(max(1, min(hours, 72))), -1, -1)]
        cur = self.w.hour(now)
        out = []
        for h in hh:
            key = (sym, h)
            got = self.ccache.get(key)
            if got is None or h == cur:
                rows = read_hour(os.path.join(self.w.root, "trades", sym), h)
                got = minute_bars(rows)
                if h != cur:
                    self.ccache[key] = got
                    # Кэш ограничен: символов много, а часов копится.
                    if len(self.ccache) > 4000:
                        for k in list(self.ccache)[:1000]:
                            self.ccache.pop(k, None)
            out += got
        out.sort(key=lambda c: c[0])
        return {"sym": sym, "candles": out, "hours": len(hh)}

    def trades(self, sym=None):
        """История бумажных сделок и сводка — по требованию, не в опросе.

        Отдельным запросом именно потому, что это не поток: история
        меняется раз в несколько минут, а опрос идёт раз в секунду.
        """
        sym = sym if sym in self.books else None
        rows = (self.sig.history(sym) if sym
                else [t for s in self.symbols for t in self.sig.history(s)])
        rows = sorted(rows, key=lambda t: -(t.get("closed_at")
                                            or t.get("t") or 0))
        # Статистика — только по текущей версии правил. Подъём истории
        # поднимает трое суток, и после правки геометрии в сводке
        # смешались бы две: числа стали бы бессмысленными, оставшись на
        # вид осмысленными. Старые сделки не удаляются, они видны в
        # таблице и посчитаны отдельным числом.
        cur = paper.current(rows, signals_version())
        return {"sym": sym, "symbols": self.symbols, "trades": rows,
                "stats": paper.summary(cur), "by_rule": paper.by_rule(cur),
                "equity": paper.equity(cur), "count": len(cur),
                "ver": signals_version(), "older": len(rows) - len(cur)}

    def disk_view(self):
        """Диск в человеческих единицах, с запасом хода в сутках."""
        d = self.disk
        if not d:
            return None
        gb = 1 << 30
        rate = d.get("rate_h")
        # Проверка на `is not None`, а не на истинность: честный ноль —
        # это измерение («не растёт»), а не отсутствие измерения.
        days = (d["free"] / rate / 24.0) if rate and rate > 0 else None
        n = max(1, d.get("symbols") or 1)
        return {"used_gb": round(d["bytes"] / gb, 2),
                "free_gb": round(d["free"] / gb, 1),
                "total_gb": round(d["total"] / gb, 1),
                "window_min": round((d.get("window_s") or 0) / 60),
                "rate_mb_h": (round(rate / (1 << 20), 1)
                              if rate is not None else None),
                "per_sym_mb_h": (round(rate / n / (1 << 20), 2)
                                 if rate is not None else None),
                "days_left": round(days, 1) if days else None,
                "by_kind": {k: round(v / gb, 2)
                            for k, v in (d.get("by_kind") or {}).items()}}

    def diskstat(self):
        """Сколько занято, с какой скоростью растёт и надолго ли хватит.

        Считается раз в минуту обходом каталога, а не оценкой: расширять
        универсум надо по измеренной скорости на символ, иначе получится
        та же ошибка, что с порогами — число из головы. Обход отдельным
        потоком, чтобы не задерживать приём.
        """
        while not self.stop.wait(60):
            try:
                total, by = 0, {}
                for base, _, files in os.walk(self.w.root):
                    kind = os.path.relpath(base, self.w.root).split(os.sep)[0]
                    for f in files:
                        try:
                            n = os.path.getsize(os.path.join(base, f))
                        except OSError:
                            continue
                        total += n
                        by[kind] = by.get(kind, 0) + n
                du = shutil.disk_usage(self.w.root)
                now = time.time()
                # Скорость считается по ОКНУ, а не по соседним замерам:
                # при закрытии часа файл сжимается, и занятое место
                # проседает. Разность соседних минут тогда отрицательна,
                # и «рост» выходит то нулём, то выбросом.
                self.samples.append((now, total))
                rate = None
                t0, b0 = self.samples[0]
                if now - t0 >= 300:
                    rate = (total - b0) / (now - t0) * 3600
                self.disk = {"bytes": total, "at": now, "by_kind": by,
                             "free": du.free, "total": du.total,
                             "rate_h": rate, "window_s": round(now - t0),
                             "symbols": len(self.symbols)}
            except Exception as e:                        # noqa: BLE001
                self.log(f"замер диска не вышел: {e}")

    def statuser(self):
        while not self.stop.wait(STATUS_SEC):
            self.w.flush()
            t0, n0 = self.msg_mark
            dt = max(time.time() - t0, 1e-9)
            self.msg_rate = (self.n_msg - n0) / dt
            self.msg_mark = (time.time(), self.n_msg)
            st = {
                "t": round(time.time(), 1),
                "uptime_sec": round(time.time() - self.started, 1),
                "messages": self.n_msg, "trades": self.n_trades,
                "resets": self.n_resets,
                "last_msg_age_sec": (round(time.time() - self.last_msg, 1)
                                     if self.last_msg else None),
                "symbols": {s: {"ready": b.ready,
                                "bid": b.best()[0], "ask": b.best()[1],
                                "resets": b.resets}
                            for s, b in self.books.items()},
            }
            tmp = os.path.join(OUT, "status.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(OUT, "status.json"))

    def reporter(self):
        """Строка в журнал раз в минуту: прогон, который молчит, неотличим
        от повисшего."""
        last = (0, 0)
        while not self.stop.wait(60):
            ready = sum(1 for b in self.books.values() if b.ready)
            self.log(f"сообщений {self.n_msg:,} (+{self.n_msg - last[0]:,}), "
                     f"сделок {self.n_trades:,} "
                     f"(+{self.n_trades - last[1]:,}), "
                     f"книг готово {ready}/{len(self.books)}, "
                     f"тем принято {len(self.live)}/{len(self.topics())}, "
                     f"сбросов {self.n_resets}")
            last = (self.n_msg, self.n_trades)

    def run(self, hours):
        import websocket                                   # noqa: E402

        deadline = self.started + hours * 3600 if hours else None
        threading.Thread(target=self.sampler, daemon=True).start()
        threading.Thread(target=self.statuser, daemon=True).start()
        threading.Thread(target=self.reporter, daemon=True).start()
        threading.Thread(target=self.diskstat, daemon=True).start()
        delay = 1
        while not self.stop.is_set():
            if deadline and time.time() >= deadline:
                self.log("время сбора вышло")
                break
            self.ws = websocket.WebSocketApp(
                WS_URL, on_open=self.on_open, on_message=self.on_message,
                on_error=self.on_error, on_close=self.on_close)
            try:
                self.ws.run_forever(
                    ping_interval=PING_SEC, ping_timeout=PING_SEC // 2,
                    sslopt={"cert_reqs": ssl.CERT_REQUIRED})
            except Exception as e:                        # noqa: BLE001
                self.log(f"разрыв: {e}")
            if self.stop.is_set() or (deadline and time.time() >= deadline):
                break
            # Книги после разрыва недействительны: биржа пришлёт новый
            # снимок, но до него старое состояние — вымысел.
            for b in self.books.values():
                b.clear()
            self.log(f"переподключение через {delay} с")
            time.sleep(delay)
            delay = min(delay * 2, 30)
        self.stop.set()
        self.w.close()


def warm_start(root, symbols, collector, log, hours=4, trade_hours=72):
    """Поднять историю из собственных файлов сборщика.

    Перезапуск не должен стоить двадцати минут накопления: сделки и
    снимки уже лежат на диске, и по ним восстанавливается и посекундный
    буфер детектора, и середина для графика. Без этого каждая правка
    кода обнуляла наблюдение, а уровни появлялись заново только через
    треть часа.

    Бумажные сделки поднимаются за более длинное окно (`trade_hours`),
    чем поток: поток нужен детектору «сейчас», а сделки — это результат,
    и он не имеет права исчезать по перезапуску.
    """
    def rows_of(kind, sym, hour, cutoff_ts, pick):
        out = []
        d = os.path.join(root, kind, sym)
        for r in read_hour(d, hour, log=lambda m: log("  " + m)):
            v = pick(r, cutoff_ts)
            if v is not None:
                out.append(v)
        return out

    cutoff = time.time() - hours * 3600
    hh = [datetime.fromtimestamp(cutoff + i * 3600, timezone.utc)
          .strftime("%Y-%m-%d-%H") for i in range(hours + 2)]
    n_tr = n_bk = 0
    for sym in symbols:
        rows = []
        for h in hh:
            rows += rows_of("trades", sym, h, cutoff, lambda r, c:
                            r if r.get("ts", 0) / 1000.0 >= c else None)
        rows.sort(key=lambda x: x.get("ts", 0))
        for t in rows:
            collector.sig.on_trade(t)
        n_tr += len(rows)
        # Середина для линии обзора — из посекундных снимков стакана.
        mids = []
        recent = time.time() - 900
        for h in hh:
            mids += rows_of(
                "book", sym, h, recent,
                lambda r, c: ((round(r["t"], 1),
                               (r["bid"] + r["ask"]) / 2.0)
                              if r.get("t", 0) >= c and r.get("bid")
                              and r.get("ask") else None))
        mids.sort()
        collector.mid[sym].extend(mids[-900:])
        n_bk += len(mids)
    n_paper = 0
    ph = [datetime.fromtimestamp(time.time() - i * 3600, timezone.utc)
          .strftime("%Y-%m-%d-%H") for i in range(trade_hours, -1, -1)]
    for sym in symbols:
        rows = []
        for h in ph:
            rows += rows_of("signals", sym, h, 0.0, lambda r, c: r)
        live = collector.sig.by.get(sym)
        if live is not None and rows:
            n_paper += live.restore(rows)
    if n_tr or n_bk:
        log(f"поднято из своих файлов: сделок {n_tr:,}, снимков {n_bk:,}, "
            f"бумажных сделок {n_paper}")
    else:
        log("своих файлов нет — история копится с нуля")


def stable_token(root):
    """Ключ доступа, переживающий перезапуск.

    Первая версия генерировала его заново при каждом старте, и ссылка на
    страницу менялась после каждого перезапуска сборщика — открытая
    вкладка переставала работать без всякой причины. Ключ хранится
    рядом с рядами и в git не идёт.
    """
    path = os.path.join(root, "token.txt")
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    except OSError:
        pass
    # Алфавит без похожих знаков: ключ читают с экрана глазами, а `l`,
    # `I`, `1`, `O` и `0` в такой ссылке путаются и дают отказ доступа,
    # выглядящий как поломка сервера.
    alpha = "abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789"
    tok = "".join(secrets.choice(alpha) for _ in range(12))
    os.makedirs(root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tok + "\n")
    os.chmod(path, 0o600)
    return tok


def selftest(root):
    """Прогнать поддельный поток через путь записи и показать итог."""
    root = os.path.join(root, "selftest")
    c = Collector(["TEST"], ["TEST"], root, lambda m: print("  " + m))
    snap = {"topic": "orderbook.50.TEST", "type": "snapshot",
            "ts": 1_700_000_000_000,
            "data": {"s": "TEST", "u": 1,
                     "b": [["100.0", "5"], ["99.9", "3"]],
                     "a": [["100.1", "4"], ["100.2", "6"]]}}
    c.on_message(None, json.dumps(snap))
    c.on_message(None, json.dumps(
        {"topic": "orderbook.50.TEST", "type": "delta",
         "ts": 1_700_000_000_100,
         "data": {"s": "TEST", "u": 2, "b": [["100.0", "0"]], "a": []}}))
    c.on_message(None, json.dumps(
        {"topic": "publicTrade.TEST", "data": [
            {"T": 1_700_000_000_050, "s": "TEST", "S": "Buy",
             "p": "100.1", "v": "2"}]}))
    smp = c.books["TEST"].sample()
    if smp is not None:
        smp["t"] = time.time()
        c.w.write("book", "TEST", smp)
    c.w.close()
    n = 0
    for base, _, files in os.walk(root):
        for f in files:
            path = os.path.join(base, f)
            size = os.path.getsize(path)
            rows = len(read_jsonl(path))
            print(f"  {os.path.relpath(path, root)}: {rows} записей, "
                  f"{size} байт")
            n += rows
    print(f"итого записей {n}; книга: лучшая покупка "
          f"{smp['bid'] if smp else '—'}, продажа "
          f"{smp['ask'] if smp else '—'}")
    if n < 3:
        raise SystemExit("сборщик ничего не записал — путь записи сломан")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--raw", default="",
                    help="символы, для которых писать сырой поток целиком")
    ap.add_argument("--deep", default=",".join(DEEP),
                    help="символы с глубокой темой стакана (500 уровней); "
                         "нужны там, где полсотни уровней стоят в точке")
    ap.add_argument("--hours", type=float, default=0,
                    help="сколько собирать; 0 — до остановки")
    ap.add_argument("--out", default=OUT)
    # Проверка без сети: сборщик, который подключился и молча ничего не
    # пишет, выглядит работающим. Прогоняет поддельные сообщения через
    # тот же путь, что и живые, и показывает, что легло на диск.
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--http", type=int, default=0,
                    help="порт страницы наблюдения; 0 — не поднимать")
    ap.add_argument("--token", default="",
                    help="ключ доступа; пустой — берётся из out/token.txt")
    a = ap.parse_args()
    if a.selftest:
        selftest(a.out)
        return
    os.makedirs(a.out, exist_ok=True)
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    raw = [s.strip() for s in a.raw.split(",") if s.strip()]
    t0 = time.time()

    lines = LogBuf()

    def log(m):
        line = f"[{time.time() - t0:8.0f} с] {m}"
        lines.add(line)
        print(line, flush=True)

    log(f"символов {len(syms)}: {', '.join(syms)}")
    if raw:
        log(f"сырой поток пишется для: {', '.join(raw)}")
    log(f"каталог {a.out}")
    deep = [x.strip() for x in a.deep.split(",") if x.strip()]
    c = Collector(syms, raw, a.out, log, deep=deep)
    log("глубина стакана: " + ", ".join(
        f"{s_}={c.depth[s_]}" for s_ in syms))
    c.lines = lines

    # `pkill` шлёт TERM, и без обработчика процесс умирал, не закрыв
    # файлы: последняя запись терялась, а раньше — портила весь архив.
    def bye(signum, frame):
        log(f"сигнал {signum}: закрываю файлы")
        c.stop.set()
        c.w.close()
        if c.ws is not None:
            try:
                c.ws.close()
            except Exception:                             # noqa: BLE001
                pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    if a.http:
        token = a.token or stable_token(a.out)
        web.serve(c, a.http, token, log)
    # Подъём истории — удобство, а не условие работы. Его падение не
    # вправе уносить ни сбор, ни страницу: именно страница и нужна,
    # чтобы увидеть, что случилось.
    n = c.w.pack_stale()
    if n:
        log(f"сжато незакрытых часов от прошлых запусков: {n}")
    try:
        warm_start(a.out, syms, c, log)
    except Exception as e:                                # noqa: BLE001
        log(f"поднять историю не вышло ({type(e).__name__}: {e}); "
            f"сбор продолжается с нуля")
    try:
        c.run(a.hours)
    except KeyboardInterrupt:
        log("остановлено вручную")
        c.stop.set()
        c.w.close()
    log(f"итого сообщений {c.n_msg:,}, сделок {c.n_trades:,}, "
        f"сбросов {c.n_resets}")


if __name__ == "__main__":
    main()
