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
from book import BANDS, Book, parse_trades                 # noqa: E402
from signals import Signals                               # noqa: E402
from store import Writer, read_hour, read_jsonl            # noqa: E402
import web                                                # noqa: E402

WS_URL = "wss://stream.bybit.com/v5/public/linear"
DEPTH = 50                        # глубина темы orderbook
PING_SEC = 20
SAMPLE_SEC = 1
STATUS_SEC = 5
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "ARBUSDT", "LINKUSDT", "AVAXUSDT")


class Collector:
    def __init__(self, symbols, raw_symbols, root, log):
        self.symbols = list(symbols)
        self.raw = set(raw_symbols)
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
        # Кольцевые буферы для страницы наблюдения: она смотрит в память,
        # а не в файлы — между данными и глазом не должно быть выгрузки.
        self.lock = threading.Lock()
        self.mid = {s: deque(maxlen=900) for s in symbols}   # 15 минут
        self.tape = {s: deque(maxlen=120) for s in symbols}
        self.lines = deque(maxlen=60)
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
            out.append(f"orderbook.{DEPTH}.{s}")
            out.append(f"publicTrade.{s}")
        return out

    def on_open(self, ws):
        self.log(f"подключено, тем {len(self.topics())}")
        ws.send(json.dumps({"op": "subscribe", "args": self.topics()}))

    def on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        self.last_msg = time.time()
        topic = msg.get("topic") or ""
        if not topic:
            return
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
                try:
                    ws.send(json.dumps({"op": "unsubscribe",
                                        "args": [topic]}))
                    ws.send(json.dumps({"op": "subscribe",
                                        "args": [topic]}))
                except Exception:                         # noqa: BLE001
                    pass
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
                s = b.sample()
                if s is not None:
                    s["t"] = round(now, 3)
                    self.w.write("book", sym, s, ts=now)
                    self.mid[sym].append(
                        (round(now, 1), (s["bid"] + s["ask"]) / 2.0))
            opened, closed = self.sig.tick(now)
            for ev in opened:
                self.n_signals += 1
                self.log(f"{ev['sym']}: сигнал "
                         f"{'лонг' if ev['long'] else 'шорт'} у уровня "
                         f"{ev['level']:.6g} ({ev['kind']}), стоп "
                         f"{ev['stop_bp']:.0f} б.п., отношение 1:{ev['rr']}")
                self.w.write("signals", ev["sym"], dict(ev, ev="open"), ts=now)
            for tr in closed:
                self.n_closed += 1
                self.log(f"{tr['sym']}: {tr['state']} — "
                         f"{tr['pnl_bp']:+.1f} б.п. ({tr['r']:+.2f} R), "
                         f"держали {tr['held']} с")
                self.w.write("signals", tr["sym"], dict(tr, ev="close"), ts=now)

    def snapshot(self, sym=None):
        """Состояние для страницы наблюдения — прямо из памяти."""
        sym = sym if sym in self.books else self.symbols[0]
        b = self.books[sym]
        s = b.sample_view()
        bands = []
        if s:
            for w in BANDS:
                bands.append({"w": round(w * 100, 3),
                              "bid": s.get(f"bq{w}", 0.0),
                              "ask": s.get(f"aq{w}", 0.0)})
        with self.lock:
            mid = list(self.mid[sym])
            tape = list(self.tape[sym])
            lines = list(self.lines)
        return {"sym": sym, "symbols": self.symbols, "book": s,
                "bands": bands, "mid": mid, "tape": tape, "log": lines,
                "sig": self.sig.view(sym),
                "status": {"uptime_sec": round(time.time() - self.started, 1),
                           "messages": self.n_msg, "trades": self.n_trades,
                           "resets": self.n_resets,
                           "signals": self.n_signals,
                           "closed": self.n_closed,
                           "msg_per_sec": round(self.msg_rate, 1),
                           "ready": sum(1 for x in self.books.values()
                                        if x.ready),
                           "last_msg_age_sec": (
                               round(time.time() - self.last_msg, 1)
                               if self.last_msg else None)}}

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
                     f"сбросов {self.n_resets}")
            last = (self.n_msg, self.n_trades)

    def run(self, hours):
        import websocket                                   # noqa: E402

        deadline = self.started + hours * 3600 if hours else None
        threading.Thread(target=self.sampler, daemon=True).start()
        threading.Thread(target=self.statuser, daemon=True).start()
        threading.Thread(target=self.reporter, daemon=True).start()
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

    lines = deque(maxlen=60)

    def log(m):
        line = f"[{time.time() - t0:8.0f} с] {m}"
        lines.append(line)
        print(line, flush=True)

    log(f"символов {len(syms)}: {', '.join(syms)}")
    if raw:
        log(f"сырой поток пишется для: {', '.join(raw)}")
    log(f"каталог {a.out}")
    c = Collector(syms, raw, a.out, log)
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
