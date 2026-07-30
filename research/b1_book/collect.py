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
import ssl
import sys
import threading
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
from book import Book, parse_trades                       # noqa: E402

WS_URL = "wss://stream.bybit.com/v5/public/linear"
DEPTH = 50                        # глубина темы orderbook
PING_SEC = 20
SAMPLE_SEC = 1
STATUS_SEC = 5
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "ARBUSDT", "LINKUSDT", "AVAXUSDT")


class Writer:
    """Пишет строки JSON в почасовые сжатые файлы, по файлу на символ."""

    def __init__(self, root):
        self.root = root
        self.files = {}
        self.lock = threading.Lock()

    def hour(self, ts):
        return datetime.fromtimestamp(ts, timezone.utc).strftime(
            "%Y-%m-%d-%H")

    def write(self, kind, symbol, obj, ts=None):
        ts = ts if ts is not None else time.time()
        key = (kind, symbol, self.hour(ts))
        with self.lock:
            f = self.files.get(key)
            if f is None:
                for k in [k for k in self.files if k[:2] == (kind, symbol)]:
                    self.files.pop(k).close()      # час сменился
                d = os.path.join(self.root, kind, symbol)
                os.makedirs(d, exist_ok=True)
                f = gzip.open(os.path.join(d, f"{key[2]}.jsonl.gz"), "at",
                              encoding="utf-8")
                self.files[key] = f
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")

    def flush(self):
        with self.lock:
            for f in self.files.values():
                f.flush()

    def close(self):
        with self.lock:
            for f in self.files.values():
                f.close()
            self.files.clear()


class Collector:
    def __init__(self, symbols, raw_symbols, root, log):
        self.symbols = list(symbols)
        self.raw = set(raw_symbols)
        self.books = {s: Book(s) for s in symbols}
        self.w = Writer(root)
        self.log = log
        self.n_msg = 0
        self.n_trades = 0
        self.n_resets = 0
        self.last_msg = 0.0
        self.started = time.time()
        self.stop = threading.Event()
        self.ws = None
        self.pending_resub = set()

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

    def statuser(self):
        while not self.stop.wait(STATUS_SEC):
            self.w.flush()
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
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                rows = sum(1 for _ in fh)
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
    a = ap.parse_args()
    if a.selftest:
        selftest(a.out)
        return
    os.makedirs(a.out, exist_ok=True)
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    raw = [s.strip() for s in a.raw.split(",") if s.strip()]
    t0 = time.time()

    def log(m):
        print(f"[{time.time() - t0:8.0f} с] {m}", flush=True)

    log(f"символов {len(syms)}: {', '.join(syms)}")
    if raw:
        log(f"сырой поток пишется для: {', '.join(raw)}")
    log(f"каталог {a.out}")
    c = Collector(syms, raw, a.out, log)
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
