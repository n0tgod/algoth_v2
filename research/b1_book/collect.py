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
import signals                                            # noqa: E402
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
# Символов на одно соединение. Полный список площадки — это больше
# тысячи тем, и одно соединение их не унесёт: буфер сокета переполняется
# на всплеске, площадка рвёт связь, и падают все книги разом. Шардами
# падение стоит своей доли символов, а не всего сбора.
SHARD_SYMBOLS = 40
REST_HOST = "https://api.bybit.com"
UNIVERSE_JSON = os.path.join(os.path.dirname(HERE), "a1_universe", "out",
                             "universe.json")
# Глубина автоматического пересчёта. Живые сделки свежее него
# дописываются как есть — они уже под нынешними правилами.
RECOUNT_HOURS = 24
STATUS_SEC = 5
# Состав сбора живёт ЗДЕСЬ, а не в строке запуска. Пока он был только в
# консоли, перезапуск командой из README тихо срезал сбор до восьми
# монет — процесс при этом исправен, страница исправна, и заметить можно
# лишь глазами через сутки. Менять список — правкой этой строки и
# коммитом, тогда он переживает перезапуск, сервер и сессию.
#
# Состав — решение владельца. 2026-08-01: «расширять на все доступные
# пары Bybit» — по умолчанию `all`: все торгуемые линейные USDT-перпы
# минус не-крипто по справочнику универсума. Список ниже — резерв на
# случай недоступного справочника при пустом диске и состав смоук-тестов.
SYMBOLS_DEFAULT = "all"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
           "ARBUSDT", "LINKUSDT", "AVAXUSDT",
           "1000PEPEUSDT", "ADAUSDT", "BCHUSDT", "BEATUSDT", "BNBUSDT",
           "ENAUSDT", "FILUSDT", "HUSDT", "HYPEUSDT", "LABUSDT",
           "NEARUSDT", "SUIUSDT", "TAOUSDT", "VELVETUSDT", "WLDUSDT",
           "XLMUSDT", "ZECUSDT")
# Сырой поток изменений книги тяжёл, поэтому пишется по одной монете:
# по нему меряется восполнение уровня внутри секунды.
RAW = ("ARBUSDT",)


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


METRICS_POLL_SEC = 300


def metrics_rows(tickers, have):
    """Разбор ответа tickers: funding, интерес, базис по каждому символу.

    Чистая функция под тест: вторая копия разбора колонок в проекте
    уже приводила к тихому нулю (загрузчик funding).
    """
    out = []
    for it in (tickers.get("result") or {}).get("list") or []:
        s = it.get("symbol")
        if s not in have:
            continue
        try:
            out.append((s, {
                "ts": int(time.time() * 1000),
                "fr": float(it["fundingRate"]),
                "nft": int(it["nextFundingTime"]),
                "oi": float(it["openInterest"]),
                "oiv": float(it["openInterestValue"]),
                "mark": float(it["markPrice"]),
                "idx": float(it["indexPrice"]),
            }))
        except (KeyError, TypeError, ValueError):
            continue
    return out


# Виды рядов, у каждого свой файл на символ. Список — источник числа
# дескрипторов; при добавлении вида запрос обязан вырасти сам.
WRITE_KINDS = ("book", "trades", "metrics", "liq", "signals")


def nofile_want(n_syms):
    """Сколько дескрипторов нужно писателю при n символах.

    Считается по списку видов, а не константой «два вида»: именно
    зашитая двойка убила сбор 1–3 августа. Виды выросли с двух (книга,
    лента) до четырёх (добавились метрики и ликвидации), запрос остался
    `2·N + 1024` = 2104 при потребности 4·N = 2160, и писатель упирался
    в предел. Отказ open() приходил в поток снимков — тот падал молча,
    и сбор книги стоял сутками при полностью исправном виде.

    Запас 1024 остаётся: сокеты шардов, сжатие, служебные файлы.
    """
    return (len(WRITE_KINDS) + 1) * n_syms + 1024


def raise_nofile(log, want):
    """Поднять лимит открытых файлов под полный список символов.

    Писатель держит по файлу на символ и вид данных: шестьсот монет —
    это за тысячу дескрипторов при системном лимите 1024 по умолчанию.
    Отказ open() на лимите тих: часть рядов просто перестала бы
    писаться, и заметить это можно было бы лишь дырами через недели.
    """
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < want:
            new = min(want, hard) if hard > 0 else want
            resource.setrlimit(resource.RLIMIT_NOFILE, (new, hard))
            log(f"лимит открытых файлов: {soft} -> {new}")
        if min(want, hard if hard > 0 else want) < want:
            log(f"ВНИМАНИЕ: жёсткий лимит файлов {hard} меньше нужных "
                f"{want} — возможны отказы записи")
    except Exception as e:                                # noqa: BLE001
        log(f"не удалось поднять лимит файлов: {e}")


def fetch_instruments(host=REST_HOST):
    """Справочник линейных контрактов площадки, все страницы."""
    import urllib.request
    out, cursor = [], ""
    while True:
        url = (f"{host}/v5/market/instruments-info?category=linear"
               f"&status=Trading&limit=1000"
               + (f"&cursor={cursor}" if cursor else ""))
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.load(r)
        res = d.get("result") or {}
        out += res.get("list") or []
        cursor = res.get("nextPageCursor") or ""
        if not cursor:
            break
    return out


def usdt_perps(instruments):
    """Из справочника — торгуемые линейные USDT-перпы."""
    return sorted({it["symbol"] for it in instruments
                   if it.get("quoteCoin") == "USDT"
                   and it.get("contractType") == "LinearPerpetual"
                   and it.get("symbol")})


def non_crypto_bybit(universe_path=UNIVERSE_JSON):
    """Символы Bybit не-крипто активов по справочнику универсума.

    Решение владельца: перпы не на криптоактивы в универсум не входят
    (у базового актива календарь биржи, у перпа — круглосуточный).
    Оговорка: не-крипто, листингованные ПОСЛЕ снимка универсума, так не
    распознаются — известная примесь, запись дешёвая.
    """
    try:
        with open(universe_path, encoding="utf-8") as f:
            u = json.load(f)["assets"]
    except OSError:
        return set()
    return {v["bybit_symbol"] for v in u.values()
            if v.get("asset_class") != "crypto" and v.get("bybit_symbol")}


def disk_symbols(root):
    """Символы, по которым на диске уже лежат ряды книги."""
    d = os.path.join(root, "book")
    try:
        return sorted(s for s in os.listdir(d)
                      if os.path.isdir(os.path.join(d, s)))
    except OSError:
        return []


def resolve_symbols(arg, log, root=OUT):
    """`--symbols all` — всё, что торгуется, минус не-крипто.

    Если справочник площадки недоступен (сеть, гео), сбор не умирает,
    а продолжает то, что уже записывается: пропущенный час всего списка
    хуже, чем час без новых имён. Отказ называется в журнале громко.
    """
    if arg.strip().lower() != "all":
        return [s.strip() for s in arg.split(",") if s.strip()]
    try:
        got = usdt_perps(fetch_instruments())
    except Exception as e:                                # noqa: BLE001
        ondisk = disk_symbols(root) or list(SYMBOLS)
        log(f"ВНИМАНИЕ: справочник площадки недоступен ({e}); "
            f"продолжаю по уже записываемым {len(ondisk)} символам")
        return ondisk
    drop = non_crypto_bybit()
    syms = [s for s in got if s not in drop]
    log(f"справочник площадки: {len(got)} торгуемых USDT-перпов, "
        f"не-крипто исключено {len(got) - len(syms)}, собираем {len(syms)}")
    return syms


def shard_split(symbols, size=SHARD_SYMBOLS):
    """Разбивка списка на шарды соединений, устойчивая по порядку."""
    return [list(symbols[i:i + size])
            for i in range(0, len(symbols), size)]


GROUPS_YAML = os.path.join(os.path.dirname(HERE), "asset_groups",
                           "groups.yaml")


def parse_groups_yaml(path=GROUPS_YAML):
    """Разметка A3 `группа: [активы]` — крошечный разбор под наш формат.

    Полного YAML здесь нет намеренно: файл наш собственный, формат
    один (двухуровневые списки), а зависимость ради него — лишняя.
    Незнакомая строка пропускается молча — это отображение для глаз,
    а не расчёт.
    """
    out, cur = {}, None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                s = line.rstrip()
                if s.startswith("    - "):
                    if cur is not None:
                        out[cur].append(s[6:].strip())
                elif s.startswith("  ") and s.endswith(":"):
                    cur = s.strip()[:-1]
                    out[cur] = []
    except OSError:
        return {}
    return out


def symbol_groups(symbols, groups_path=GROUPS_YAML,
                  universe_path=UNIVERSE_JSON):
    """Символы сбора по группам A3: [{id, symbols}, …] + «прочие».

    Группировка — для глаз владельца на странице: 540 плоских кнопок
    нечитаемы. Новые листинги, которых нет в разметке, честно лежат в
    «прочих», а не рассованы по догадке.
    """
    by_asset = parse_groups_yaml(groups_path)
    sym_of = {}
    try:
        with open(universe_path, encoding="utf-8") as f:
            u = json.load(f)["assets"]
        sym_of = {k: v.get("bybit_symbol") for k, v in u.items()}
    except (OSError, ValueError, KeyError):
        pass
    have = set(symbols)
    used = set()
    out = []
    for gid, assets in by_asset.items():
        ss = sorted(s for s in (sym_of.get(a) for a in assets)
                    if s in have)
        if ss:
            out.append({"id": gid, "symbols": ss})
            used.update(ss)
    rest = sorted(have - used)
    if rest:
        out.append({"id": "other", "symbols": rest})
    return out


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


class Shard:
    """Одно соединение с площадкой: свои темы и свой цикл переподключения.

    Книги, писатель и детектор — общие (живут в коллекторе); шарду
    принадлежат сокет, множество живых тем и счётчики. Падение шарда
    стоит своей доли символов, а не всего сбора, и переподключение
    очищает только свои книги.
    """

    def __init__(self, idx, symbols, coll):
        self.idx = idx
        self.symbols = list(symbols)
        self.c = coll
        self.ws = None
        self.live = set()
        self.n_msg = 0
        self.n_trades = 0
        self.n_resets = 0
        self.last_msg = 0.0

    def topics(self):
        out = []
        for s in self.symbols:
            out.append(f"orderbook.{self.c.depth[s]}.{s}")
            out.append(f"publicTrade.{s}")
            # Ликвидации: единственный источник — живой поток, в архивах
            # их нет ни у кого (замер L0). Каждый день без записи —
            # минус день будущей обучающей выборки.
            out.append(f"allLiquidation.{s}")
        return out

    def send_sub(self, ws, topics):
        """Подписка по одной теме, с именем темы в `req_id`: одним
        запросом площадка отвергает ВСЁ из-за одной негодной темы."""
        for t in topics:
            try:
                ws.send(json.dumps({"op": "subscribe", "args": [t],
                                    "req_id": t}))
            except Exception as e:                        # noqa: BLE001
                self.c.log(f"шард {self.idx}: не отправилась подписка "
                           f"{t}: {e}")

    def on_open(self, ws):
        self.live = set()
        self.c.log(f"шард {self.idx}: подключён, подписываюсь на "
                   f"{len(self.topics())} тем")
        self.send_sub(ws, self.topics())

    def on_op(self, ws, msg):
        """Служебный ответ. Отклонённая подписка неотличима от тишины
        рынка, молчать о ней нельзя."""
        if msg.get("op") == "pong" or msg.get("ret_msg") == "pong":
            return
        ok, req = msg.get("success"), msg.get("req_id") or ""
        if ok is False:
            self.c.log(f"шард {self.idx}: подписка отклонена: "
                       f"{req or '?'} — {msg.get('ret_msg') or msg}")
            self.downgrade(ws, req)
        elif ok is True and req:
            self.live.add(req)

    def downgrade(self, ws, topic):
        """Стакан не принят на этой глубине — пробуем мельче: мельче
        хуже, но это данные, а отказ — их отсутствие."""
        if not topic.startswith("orderbook."):
            return
        try:
            _, d, sym = topic.split(".", 2)
            d = int(d)
        except ValueError:
            return
        nxt = next((x for x in DEPTH_LADDER if x < d), None)
        if nxt is None or sym not in self.c.books:
            self.c.log(f"{sym}: глубины кончились, стакан собираться "
                       f"не будет")
            return
        self.c.depth[sym] = nxt
        self.c.log(f"{sym}: глубина {d} не принята, пробую {nxt}")
        self.send_sub(ws, [f"orderbook.{nxt}.{sym}"])

    def on_message(self, ws, raw):
        c = self.c
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
            b = c.books.get(sym)
            if b is None:
                return
            if sym in c.raw:
                c.w.write("raw", sym, msg)
            if not b.apply(msg):
                self.n_resets += 1
                c.log(f"{sym}: разрыв нумерации, переподписка")
                self.live.discard(topic)
                try:
                    ws.send(json.dumps({"op": "unsubscribe",
                                        "args": [topic]}))
                except Exception:                         # noqa: BLE001
                    pass
                self.send_sub(ws, [topic])
        elif topic.startswith("allLiquidation."):
            sym = topic.rsplit(".", 1)[-1]
            for q in msg.get("data") or []:
                try:
                    row = {"ts": int(q["T"]), "side": q["S"],
                           "p": float(q["p"]), "v": float(q["v"])}
                except (KeyError, TypeError, ValueError):
                    continue
                c.w.write("liq", sym, row, ts=row["ts"] / 1000.0)
        elif topic.startswith("publicTrade."):
            sym = topic.rsplit(".", 1)[-1]
            for t in parse_trades(msg):
                self.n_trades += 1
                c.w.write("trades", sym, t, ts=t["ts"] / 1000.0)
                d = c.tape.get(sym)
                if d is not None:
                    d.append(t)
                if c.paper:
                    c.sig.on_trade(t)

    def run(self):
        import websocket                                   # noqa: E402
        delay = 1
        while not self.c.stop.is_set():
            self.ws = websocket.WebSocketApp(
                WS_URL, on_open=self.on_open,
                on_message=self.on_message,
                on_error=lambda ws, e:
                    self.c.log(f"шард {self.idx}: ошибка соединения: {e}"),
                on_close=lambda ws, code, reason:
                    self.c.log(f"шард {self.idx}: соединение закрыто: "
                               f"{code} {reason}"))
            try:
                self.ws.run_forever(
                    ping_interval=PING_SEC, ping_timeout=PING_SEC // 2,
                    sslopt={"cert_reqs": ssl.CERT_REQUIRED})
            except Exception as e:                        # noqa: BLE001
                self.c.log(f"шард {self.idx}: разрыв: {e}")
            if self.c.stop.is_set():
                break
            # Книги шарда после разрыва недействительны: до нового
            # снимка площадки их состояние — вымысел.
            for s in self.symbols:
                b = self.c.books.get(s)
                if b is not None:
                    b.clear()
            self.c.log(f"шард {self.idx}: переподключение через {delay} с")
            time.sleep(delay)
            delay = min(delay * 2, 30)


class Collector:
    def __init__(self, symbols, raw_symbols, root, log, deep=DEEP,
                 paper=False):
        # `paper` — бумажные сделки детектора. По умолчанию выключены
        # решением владельца 2026-08-01: направление ленты закрыто
        # четырьмя замерами (T1–T4), а правило поглощения в стакане
        # входит в модель гипотезы 6 признаками (eat_bid/eat_ask,
        # big_rel, дисбалансы) — выученными, а не зашитыми порогами.
        # Держать ручную версию рядом с моделью значит смешивать две
        # статистики на одной странице; сама запись стакана и ленты от
        # этого не меняется ни байтом.
        self.paper = paper
        self.symbols = list(symbols)
        self.raw = set(raw_symbols)
        self.depth = {s: (DEEP_DEPTH if s in set(deep or ()) else DEPTH)
                      for s in symbols}
        self.books = {s: Book(s) for s in symbols}
        self.w = Writer(root, log)
        self.log = log
        self.started = time.time()
        self.stop = threading.Event()
        self.shards = [Shard(i, chunk, self)
                       for i, chunk in enumerate(shard_split(self.symbols))]
        self.disk = {}
        self.samples = deque(maxlen=90)   # (момент, байт)
        self.ccache = {}                  # свечи закрытых часов
        # Встречный пересчёт живёт на ДИСКЕ, а не только в памяти.
        # Держали в памяти — и он пропадал при каждом перезапуске
        # сборщика, а на странице гас при каждой перезагрузке: владельцу
        # приходилось гонять трёхминутный счёт заново, чтобы увидеть то
        # же самое. Считаем один раз, дальше читаем.
        self.rec = self.load_recount()
        # Группы монет для страницы — статика, считается один раз.
        try:
            self.groups = symbol_groups(self.symbols)
        except Exception:                                 # noqa: BLE001
            self.groups = [{"id": "other",
                            "symbols": sorted(self.symbols)}]
        # Состояние модели S8 читается с диска по фиксированным путям и
        # кешируется: страница опрашивает раз в минуту, файлы меняются
        # раз в сутки.
        self._model_cache = (0.0, None)
        # Кольцевые буферы для страницы наблюдения: она смотрит в память,
        # а не в файлы — между данными и глазом не должно быть выгрузки.
        self.lock = threading.Lock()
        self.mid = {s: deque(maxlen=900) for s in symbols}   # 15 минут
        # По каким символам середина уже дочитана с диска. Подъём идёт
        # по запросу страницы, а не для всех разом: см. `warm_mid`.
        self.mid_warmed = set()
        self.tape = {s: deque(maxlen=120) for s in symbols}
        self.lines = LogBuf()
        self.msg_mark = (time.time(), 0)
        self.msg_rate = 0.0
        # Здоровье ЗАПИСИ книги, а не процесса: сообщения могут литься
        # при мёртвом сборщике снимков, и именно так это выглядело.
        self.n_snap = 0
        self.n_snap_err = 0
        self.last_snap = 0.0
        self.snap_pass_sec = 0.0
        self.snap_slow_said = 0.0
        # Живой детектор: те же правила, что в замерах. Сделки бумажные,
        # это наблюдение, а не торговля — замеры T1–T4 показали, что
        # направленного содержания у события нет. Страница нужна, чтобы
        # видеть, ТУДА ли детектор показывает.
        self.sig = Signals(symbols)
        self.n_signals = 0
        self.n_live_merged = 0
        self.n_closed = 0

    # --- агрегаты по шардам --------------------------------------------
    # Сеть живёт в шардах; здесь только суммы для страницы и журнала.
    @property
    def n_msg(self):
        return sum(s.n_msg for s in self.shards)

    @property
    def n_trades(self):
        return sum(s.n_trades for s in self.shards)

    @property
    def n_resets(self):
        return sum(s.n_resets for s in self.shards)

    @property
    def last_msg(self):
        return max((s.last_msg for s in self.shards), default=0.0)

    def topics_count(self):
        return sum(len(s.topics()) for s in self.shards)

    def live_count(self):
        return sum(len(s.live) for s in self.shards)

    def shard_state(self):
        now = time.time()
        return [{"i": s.idx, "symbols": len(s.symbols),
                 "live": len(s.live), "topics": len(s.topics()),
                 "age_sec": (round(now - s.last_msg, 1)
                             if s.last_msg else None)}
                for s in self.shards]


    # --- фоновые задачи ------------------------------------------------
    def sampler(self):
        """Снимок стакана раз в секунду по всем символам.

        Тело обёрнуто намеренно: это поток-демон, и одна исключительная
        ситуация (кончились дескрипторы, кончился диск, битый снимок)
        убивала его молча — вебсокеты продолжали лить, `status.json`
        писал другой поток, страница выглядела исправной, а запись
        книги прекращалась. Ровно так на сервере встал сбор 2 августа.
        Теперь отказ считается, называется и НЕ прекращает запись
        остальных символов.
        """
        nxt = time.time() + SAMPLE_SEC
        while not self.stop.wait(max(0.0, nxt - time.time())):
            # Долг НЕ отрабатывается: если проход занял дольше шага,
            # прибавление шага к прошлому сроку заставляет цикл гнать
            # проходы подряд, пока не догонит. На живом сборе это дало
            # 4091 снимок на монету в час вместо 3600 — лишняя запись
            # вспышками вместо ровной сетки. Отстали — берём следующий
            # срок от текущего момента.
            nxt = max(nxt + SAMPLE_SEC, time.time())
            now = time.time()
            t_pass = time.time()
            for sym, b in self.books.items():
                try:
                    s = b.sample(ladder=STORE_LADDER)
                    if s is not None:
                        s["t"] = round(now, 3)
                        self.w.write("book", sym, s, ts=now)
                        self.n_snap += 1
                        self.last_snap = now
                        self.mid[sym].append(
                            (round(now, 1), (s["bid"] + s["ask"]) / 2.0))
                except Exception as e:                    # noqa: BLE001
                    self.n_snap_err += 1
                    if self.n_snap_err in (1, 10) \
                            or self.n_snap_err % 1000 == 0:
                        self.log(f"снимок {sym} не записан "
                                 f"({self.n_snap_err} отказов подряд по "
                                 f"счёту): {type(e).__name__}: {e}")
            self.snap_pass_sec = time.time() - t_pass
            # Предупреждение перевзводится раз в час: сборщик работает
            # неделями, состав растёт, и однократная строка о медленном
            # проходе потерялась бы в журнале навсегда.
            if now - self.snap_slow_said > 3600 \
                    and self.snap_pass_sec > SAMPLE_SEC:
                # Проход дольше секунды означает, что снимков в часе
                # меньше 3600, и это меняет пригодность часа к сечению.
                # Сказать об этом надо один раз и числом.
                self.snap_slow_said = now
                self.log(f"ВНИМАНИЕ: полный проход снимков занял "
                         f"{self.snap_pass_sec:.2f} с при шаге "
                         f"{SAMPLE_SEC} с — снимков в часе будет около "
                         f"{int(3600 / max(self.snap_pass_sec, 1e-9))}, "
                         f"не 3600")
            if not self.paper:
                continue
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

    def health(self):
        """Здоровье сбора — ОДНО определение на страницу и на файл.

        Копий было две (`snapshot` для страницы, `statuser` для
        `status.json`), и они немедленно разошлись: поля о записи
        снимков добавились только в файл, а страница продолжала
        показывать прежний набор. Тот же класс, что вторая копия
        расчётного ядра, и ловится он тем же — единственным местом.
        """
        return {
            "uptime_sec": round(time.time() - self.started, 1),
            "messages": self.n_msg, "trades": self.n_trades,
            "resets": self.n_resets,
            "last_msg_age_sec": (round(time.time() - self.last_msg, 1)
                                 if self.last_msg else None),
            # Главная мера: пишутся ли снимки книги. Всё остальное
            # остаётся бодрым и при мёртвом сборщике снимков.
            "snapshots": self.n_snap,
            "snapshot_errors": self.n_snap_err,
            "last_snap_age_sec": (round(time.time() - self.last_snap, 1)
                                  if self.last_snap else None),
            "snap_pass_sec": round(self.snap_pass_sec, 3),
            # По каждому виду: сколько записей и сколько секунд назад
            # была последняя. Вид, переставший писаться, обязан быть
            # виден числом, а не выводиться из размера каталога на
            # диске (тот округляется до сотых гигабайта и молчит).
            "writes": dict(self.w.n_by_kind),
            "write_age_sec": {k: round(time.time() - v, 1)
                              for k, v in self.w.last_by_kind.items()},
        }

    def warm_mid(self, sym):
        """Дочитать середину с диска — по одному символу и по запросу.

        Раньше это делалось для ВСЕХ символов при старте, и на живом
        сборе замер показал цену: подъём читал 480 795 снимков, полный
        проход сборщика снимков занял из-за этого 63.8 с вместо 0.3, а
        все четырнадцать соединений получили `ping/pong timed out` и
        переподключились — то есть запись портилась ради линии на
        странице. Строка «около 56 снимков в час вместо 3600» в журнале
        и есть след этой платы.

        Страница смотрит на один символ за раз, значит и читать надо
        один. Два часовых файла одного имени — доли секунды, и платит за
        них тот, кто смотрит, а не запись.
        """
        with self.lock:
            if sym in self.mid_warmed:
                return
            self.mid_warmed.add(sym)
        m_from = time.time() - 900
        hours = sorted({datetime.fromtimestamp(m_from + i * 900,
                                               timezone.utc)
                        .strftime("%Y-%m-%d-%H") for i in range(0, 5)})
        mids = []
        d = os.path.join(self.w.root, "book", sym)
        try:
            for h in hours:
                for r in read_hour(d, h):
                    if r.get("t", 0) >= m_from and r.get("bid") \
                            and r.get("ask"):
                        mids.append((round(r["t"], 1),
                                     (r["bid"] + r["ask"]) / 2.0))
        except Exception as e:                            # noqa: BLE001
            self.log(f"середину {sym} поднять не вышло: {e}")
            return
        if not mids:
            return
        mids.sort()
        with self.lock:
            live = list(self.mid[sym])
            # Живая запись идёт параллельно, поэтому дописывать в конец
            # нельзя: старые точки легли бы ПОСЛЕ новых, и график
            # показал бы ряд, идущий назад во времени. Берём с диска
            # только то, что старше самой ранней живой точки.
            edge = live[0][0] if live else None
            old = [p for p in mids if edge is None or p[0] < edge]
            if not old:
                return
            self.mid[sym].clear()
            self.mid[sym].extend((old + live)[-900:])

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
        self.warm_mid(sym)
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
                "status": {**self.health(),
                           "signals": self.n_signals,
                           "paper": self.paper,
                           "closed": self.n_closed,
                           "topics_live": self.live_count(),
                           "topics": self.topics_count(),
                           "shards": self.shard_state(),
                           "msg_per_sec": round(self.msg_rate, 1),
                           "ready": sum(1 for x in self.books.values()
                                        if x.ready),
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

    def rec_path(self):
        return os.path.join(self.w.root, "recount.json")

    def load_recount(self):
        """Поднять сохранённый пересчёт. Отказ не вправе ронять сбор."""
        try:
            with open(self.rec_path(), encoding="utf-8") as f:
                st = json.load(f)
        except Exception:                                 # noqa: BLE001
            return {}
        st["busy"] = False        # процесс, считавший его, давно умер
        return st

    def save_recount(self):
        """Записать пересчёт целиком и атомарно.

        Через временный файл: обрыв посреди записи оставил бы огрызок,
        который при следующем запуске разобрался бы как «пересчёта нет»
        либо, хуже, как неполный, — а по нему не отличить одно от
        другого. Тот же приём, что при сжатии часа.
        """
        tmp = self.rec_path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.rec, f, ensure_ascii=False)
            os.replace(tmp, self.rec_path())
        except Exception as e:                            # noqa: BLE001
            self.log(f"пересчёт не сохранён: {type(e).__name__}: {e}")

    def recount(self, hours=24, start=True, sym=None):
        """Все сделки под ТЕКУЩИМИ правилами — единственный вид.

        Решение владельца: кнопки пересчёта не нужно, сравнивать «как
        было и как стало» он не хочет, всё должно считаться под новые
        условия само. Поэтому счёт запускается автоматически (см.
        `_recount_watch`), а страница показывает только его.

        Живые сделки, записанные ПОСЛЕ момента счёта, пересчитывать не
        надо и нельзя: их сделал живой детектор, то есть уже нынешними
        правилами. Они просто дописываются к результату. Отсюда и
        устройство перезапуска счёта — он нужен ровно тогда, когда
        меняется версия правил, а не по часам.

        Оговорка, которую нельзя терять: это **встречный** счёт для
        старых входов — цена шла та же, но сделка была бы другой.
        Пересчитывается геометрия (стоп и цель), а сами входы берутся из
        записи. Значит правка УСЛОВИЙ ВХОДА в этих числах не отражается,
        отражается только правка геометрии. Для условий входа нужен
        полный прогон (`replay.replay_symbol`), он дороже и читает книгу.
        """
        if not self.paper:
            # Детектор выключен — показывать нечего, и это не пустота,
            # а состояние. Гасится ЗДЕСЬ, у источника: панель кормится
            # кешем на диске, и полагаться на то, что файлы кто-то
            # удалил, значит зависеть от постороннего действия.
            return {"off": True, "trades": [], "extra": [], "stats": None,
                    "by_rule": {}, "equity": [], "busy": False, "at": 0,
                    "ver": signals_version()}
        st = self.rec
        rows = self.merge_live(st.get("trades") or [], st.get("at", 0))
        # Отвергнутые и незакрытые идут ОТДЕЛЬНЫМ списком и в статистику
        # не попадают: у них нет исхода. Показываются вместе с
        # остальными, потому что «правило этот вход не берёт» — ответ, а
        # молчание ответом не является.
        extra = st.get("extra") or []
        one = (st.get("by_sym") or {}).get(sym) if sym else None
        if sym:
            # По одной монете: странице графика нужны её сделки, а не все.
            rows = [t for t in rows if t.get("sym") == sym]
            extra = [t for t in extra if t.get("sym") == sym]
        # Версия отдаётся ТА, ПОД КОТОРУЮ СЧИТАЛИ, а не текущая: иначе
        # поднятый с диска пересчёт после правки геометрии подписывался
        # бы нынешними правилами, не будучи ими. `stale` говорит об этом
        # прямо, чтобы страница не молчала о расхождении.
        made_ver = st.get("ver") or signals_version()
        out = {"busy": st.get("busy", False), "done": st.get("done", 0),
               "total": st.get("total", 0), "hours": st.get("hours"),
               "at": st.get("at", 0), "ver": made_ver,
               "now_ver": signals_version(),
               "live": self.n_live_merged,
               "stale": made_ver != signals_version(),
               "made": (one or st).get("made", 0),
               "refused": (one or st).get("refused", 0),
               "took_sec": st.get("took_sec"),
               "trades": sorted(rows + extra,
                                key=lambda t: -(t.get("closed_at")
                                                or t.get("t") or 0)),
               "no_outcome": len(extra)}
        # Сводка считается ИЗ ТЕХ ЖЕ строк, что показаны, а не берётся из
        # сохранённой: после склейки с живыми сделками сохранённая
        # описывала бы другой набор — таблица одно, числа другое, и обе
        # стороны выглядели бы правдоподобно. Открытые и отвергнутые
        # отсеет `paper.finished` сам: исхода у них нет.
        out["stats"] = paper.summary(rows)
        out["by_rule"] = paper.by_rule(rows)
        out["equity"] = paper.equity(rows)
        return out

    def merge_live(self, rows, at):
        """Пересчитанные сделки плюс живые, сделанные ПОСЛЕ счёта.

        Живую сделку пересчитывать незачем: её сделал живой детектор
        нынешними правилами, то есть она уже «под новыми условиями».
        Пересчёт нужен только тем, что записаны под прежней версией.

        Ключ склейки — момент входа: пересчитанная запись несёт тот же
        `t`, что и живая, из которой она выведена. Без ключа сделка
        показалась бы дважды, и обе выглядели бы настоящими.
        """
        seen = {(r.get("sym"), int(r.get("t") or 0)) for r in rows}
        add = []
        for s in self.symbols:
            for t in self.sig.history(s):
                if float(t.get("t") or 0) <= at:
                    continue
                if (t.get("sym"), int(t.get("t") or 0)) in seen:
                    continue
                add.append(t)
        self.n_live_merged = len(add)
        return list(rows) + add

    def _recount_watch(self):
        """Сам пересчитывает, когда это нужно, и не чаще.

        Нужно в трёх случаях: пересчёта нет вовсе; он считан под ДРУГУЮ
        версию правил; он старше запуска этого процесса.

        Третье условие добавлено после первого же прогона, и без него
        конструкция не работала. Сторож смотрел только на номер версии
        геометрии — а правки детектора (гейт «крупный», досягаемость
        уровня) её не меняют, и четырёхчасовой пересчёт остался лежать
        как «свежий». Между тем **перезапуск и есть деплой** в нашем
        рабочем цикле: владелец перезапускает сервер именно затем, чтобы
        подхватить правки. Значит после запуска считать надо заново, и
        цена этому — один трёхминутный счёт на перезапуск.

        По часам не перезапускаем: живые сделки и так под нынешними
        правилами, их дописывает `merge_live`, а периодический счёт
        занимал бы процессор у приёма сообщений — приём важнее.
        """
        while not self.stop.wait(30.0):
            st = self.rec
            if st.get("busy"):
                continue
            at = st.get("at") or 0
            why = ("прежнего нет" if not at
                   else f"прежний считан под v{st.get('ver')}"
                   if st.get("ver") != signals_version()
                   else "прежний старше этого запуска" if at < self.started
                   else None)
            if why is None:
                continue
            self.log(f"пересчёт под правила v{signals_version()} "
                     f"запускается сам: {why}")
            st.update({"busy": True, "hours": RECOUNT_HOURS, "done": 0,
                       "total": len(self.symbols), "at": 0})
            self._recount_job(RECOUNT_HOURS)

    def _recount_job(self, hours):
        import replay as R
        t0 = time.time()
        keep = signals.STRUCTURAL_STOP
        hh = R.hours_back(hours)
        allt, extra, made, refused = [], [], 0, 0
        # По каждой монете отдельно: на странице монеты сравнивать общее
        # число входов с её таблицей нельзя — покрытие вышло бы то
        # больше единицы, то меньше, и ни о чём бы не говорило.
        bysym = {}
        try:
            for i, s in enumerate(self.symbols, 1):
                try:
                    d, cr, rf = R.replay_seeded(self.w.root, s, hh)
                except Exception as e:                    # noqa: BLE001
                    self.log(f"пересчёт {s}: {type(e).__name__}: {e}")
                    d, cr, rf = [], [], []
                allt += d
                made += len(cr)
                refused += len(rf)
                # Отвергнутые входы и не успевшие закрыться — тоже
                # результат правила, а не пустота. В статистику они не
                # идут (исхода нет), но на графике обязаны быть видны:
                # иначе сделка, которую новая геометрия не берёт, просто
                # исчезает, и это неотличимо от потери данных.
                done_ids = {t.get("id") for t in d}
                extra += list(rf) + [t for t in cr
                                     if t.get("id") not in done_ids]
                bysym[s] = {"made": len(cr), "refused": len(rf),
                            "closed": len(d)}
                self.rec["done"] = i
            self.rec.update({"trades": allt, "extra": extra, "by_sym": bysym,
                             "stats": paper.summary(allt),
                             "by_rule": paper.by_rule(allt),
                             "equity": paper.equity(allt),
                             "made": made, "refused": refused,
                             "took_sec": round(time.time() - t0, 1),
                             # Версия правил, под которую считали. Без неё
                             # поднятый с диска пересчёт выдавал бы себя
                             # за нынешний после любой правки геометрии.
                             "ver": signals_version(),
                             "at": time.time()})
            self.log(f"пересчёт под правила v{signals_version()}: "
                     f"входов {made}, отвергнуто {refused}, "
                     f"закрытых {len(allt)}, за {time.time() - t0:.0f} с")
        finally:
            signals.STRUCTURAL_STOP = keep
            self.rec["busy"] = False
            self.save_recount()

    def model_state(self):
        """Состояние модели S8 для страницы: манифест, мысли, живой IC.

        Пути фиксированы, ключ обязателен на уровне сервера; кеш на
        30 с, потому что источники меняются раз в сутки. Отсутствие
        модели — не ошибка, а именованное состояние: она копит запись.
        """
        now = time.time()
        at, cached = self._model_cache
        if cached is not None and now - at < 30:
            return cached
        mdir = os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                            "model")
        out = {"present": False}
        try:
            with open(os.path.join(mdir, "manifest.json"),
                      encoding="utf-8") as f:
                out = {"present": True, "manifest": json.load(f)}
        except (OSError, ValueError):
            pass
        for arm in ("gbm", "nn"):
            try:
                with open(os.path.join(mdir, f"account_{arm}.json"),
                          encoding="utf-8") as f:
                    out.setdefault("accounts", {})[arm] = json.load(f)
            except (OSError, ValueError):
                pass
        for name, key, keep in (("thoughts.jsonl", "thoughts", 60),
                                ("ic_history.jsonl", "ic", 90),
                                ("picks.jsonl", "picks", 6),
                                ("review.jsonl", "review", 6)):
            rows = []
            try:
                with open(os.path.join(mdir, name), encoding="utf-8") as f:
                    for line in f:
                        try:
                            rows.append(json.loads(line))
                        except ValueError:
                            continue
            except OSError:
                pass
            out[key] = rows[-keep:]
        self._model_cache = (now, out)
        return out

    def trades(self, sym=None):
        """История бумажных сделок и сводка — по требованию, не в опросе.

        Отдельным запросом именно потому, что это не поток: история
        меняется раз в несколько минут, а опрос идёт раз в секунду.
        """
        sym = sym if sym in self.books else None
        if not self.paper:
            return {"off": True, "sym": sym, "symbols": self.symbols,
                    "trades": [], "stats": None, "by_rule": {},
                    "equity": [], "count": 0, "by_ver": [],
                    "ver": signals_version(), "older": 0}
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
                "by_ver": paper.by_version(rows),
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
                **self.health(),
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
            ages = [(s.idx, time.time() - s.last_msg)
                    for s in self.shards if s.last_msg]
            worst = max(ages, key=lambda x: x[1]) if ages else None
            extra = (f", худший шард {worst[0]} ({worst[1]:.0f} с тишины)"
                     if worst and worst[1] > 30 else "")
            d = self.disk or {}
            if d.get("rate_h") and d["rate_h"] > 0 and d.get("free"):
                extra += (f", диска на ~"
                          f"{d['free'] / d['rate_h'] / 24:.0f} дн.")
            self.log(f"сообщений {self.n_msg:,} (+{self.n_msg - last[0]:,}), "
                     f"сделок {self.n_trades:,} "
                     f"(+{self.n_trades - last[1]:,}), "
                     f"книг готово {ready}/{len(self.books)}, "
                     f"тем принято {self.live_count()}/"
                     f"{self.topics_count()}, "
                     f"сбросов {self.n_resets}{extra}")
            last = (self.n_msg, self.n_trades)

    def metrics_poll(self):
        """Funding, открытый интерес и базис — раз в 5 минут, один
        запрос на все символы. Ставка и интерес доказали ценность
        замерами (персистентность A1; d_oi_7 — второй по важности
        признак M2), и живой ряд не восстановим задним числом."""
        import urllib.request
        fails = 0
        while not self.stop.wait(METRICS_POLL_SEC):
            try:
                url = (f"{REST_HOST}/v5/market/tickers?category=linear")
                with urllib.request.urlopen(url, timeout=30) as r:
                    rows = metrics_rows(json.load(r), set(self.books))
                now = time.time()
                for s, row in rows:
                    self.w.write("metrics", s, row, ts=now)
                if fails:
                    self.log(f"опрос тикеров ожил, строк {len(rows)}")
                fails = 0
            except Exception as e:                        # noqa: BLE001
                fails += 1
                if fails in (1, 10) or fails % 100 == 0:
                    self.log(f"опрос тикеров не прошёл ({fails} подряд): "
                             f"{type(e).__name__}: {e}")

    def run(self, hours):
        deadline = self.started + hours * 3600 if hours else None
        threading.Thread(target=self.metrics_poll, daemon=True).start()
        threading.Thread(target=self.sampler, daemon=True).start()
        threading.Thread(target=self.statuser, daemon=True).start()
        threading.Thread(target=self.reporter, daemon=True).start()
        threading.Thread(target=self.diskstat, daemon=True).start()
        if self.paper:
            threading.Thread(target=self._recount_watch,
                             daemon=True).start()
        else:
            self.log("бумажные сделки выключены: направление ленты "
                     "закрыто замерами, поглощение входит в модель "
                     "признаками; запись стакана и ленты идёт как шла")
        # Шарды вводятся ступенями: тысяча подписок разом — это шторм
        # и для площадки, и для собственного разбора сообщений.
        for sh in self.shards:
            threading.Thread(target=sh.run, daemon=True).start()
            time.sleep(1.0)
        self.log(f"шардов запущено: {len(self.shards)}")
        while not self.stop.wait(1.0):
            if deadline and time.time() >= deadline:
                self.log("время сбора вышло")
                break
        self.stop.set()
        for sh in self.shards:
            if sh.ws is not None:
                try:
                    sh.ws.close()
                except Exception:                         # noqa: BLE001
                    pass
        self.w.close()


def _unfinished(rows):
    """Записи об открытии, у которых нет парного закрытия."""
    opened, closed = {}, set()
    for r in rows:
        key = r.get("id") or f"{r.get('sym')}-{r.get('t')}"
        if r.get("ev") == "close":
            closed.add(key)
        else:
            opened[key] = r
    return [r for k, r in opened.items() if k not in closed]


def warm_start(root, symbols, collector, log, hours=4, trade_hours=72):
    """Поднять историю из собственных файлов сборщика.

    Перезапуск не должен стоить двадцати минут накопления: сделки уже
    лежат на диске, и по ним восстанавливается посекундный буфер
    детектора. Без этого каждая правка кода обнуляла наблюдение, а
    уровни появлялись заново только через треть часа.

    Бумажные сделки поднимаются за более длинное окно (`trade_hours`),
    чем поток: поток нужен детектору «сейчас», а сделки — это результат,
    и он не имеет права исчезать по перезапуску.

    Середина для графика здесь НЕ поднимается — она читается по запросу
    страницы, символ за символом (`Collector.warm_mid`). Массовый подъём
    стоил записи: 480 795 снимков на старте, проход сборщика 63.8 с
    вместо 0.3 и `ping/pong timed out` на всех четырнадцати соединениях.
    Запись — цель машины, линия на странице — удобство; платить первым
    за второе нельзя.
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
    n_tr = 0
    # Лента нужна только детектору бумажных сделок. При выключенных
    # сделках это чтение миллионов строк ради счётчика в журнале:
    # прошлый подъём поднял 5.3 млн сделок и не использовал ни одной.
    for si, sym in enumerate(symbols if collector.paper else ()):
        if si and si % 100 == 0:
            # На полном списке подъём читает сотни файлов; молчание
            # дольше минуты неотличимо от зависания.
            log(f"  подъём истории: {si}/{len(symbols)} символов")
        rows = []
        for h in hh:
            rows += rows_of("trades", sym, h, cutoff, lambda r, c:
                            r if r.get("ts", 0) / 1000.0 >= c else None)
        rows.sort(key=lambda x: x.get("ts", 0))
        for t in rows:
            collector.sig.on_trade(t)
        n_tr += len(rows)
    n_paper = 0
    ph = [datetime.fromtimestamp(time.time() - i * 3600, timezone.utc)
          .strftime("%Y-%m-%d-%H") for i in range(trade_hours, -1, -1)]
    n_fixed = n_left = n_alive = 0
    # При выключенных бумажных сделках поднимать нечего: прошлые сделки
    # лежат на диске и никуда не денутся, а досчитывать оборванные —
    # значит читать ленту двух суток на 540 символов ради истории
    # закрытого направления.
    for sym in (symbols if collector.paper else ()):
        rows = []
        for h in ph:
            rows += rows_of("signals", sym, h, 0.0, lambda r, c: r)
        live = collector.sig.by.get(sym)
        if live is None or not rows:
            continue
        # Оборванные сделки досчитываются по записанной ленте, и для
        # этого её надо ДОЧИТАТЬ: в память поднимаются последние четыре
        # часа, а оборваться сделка могла двое суток назад. Читаем
        # прицельно — только часы от входа до предела удержания и только
        # у символов, где есть что досчитывать. Иначе пришлось бы поднять
        # трое суток ленты по всем двадцати пяти именам ради нескольких
        # сделок.
        need = _unfinished(rows)
        tape = []
        if need:
            want = set()
            for r in need:
                t0 = float(r.get("t") or 0)
                for k in range(0, signals.MAX_HOLD_SEC + 3600, 3600):
                    want.add(datetime.fromtimestamp(t0 + k, timezone.utc)
                             .strftime("%Y-%m-%d-%H"))
            for h in sorted(want):
                tape += rows_of("trades", sym, h, 0.0, lambda r, c: r)
            tape.sort(key=lambda x: x.get("ts", 0))
        before = len(need)
        n_paper += live.restore(rows, tape)
        after = sum(1 for t in live.done
                    if t.get("state") == "оборвана перезапуском")
        n_alive += len(live.open)
        n_fixed += before - after - len(live.open)
        n_left += after
    if n_fixed or n_left or n_alive:
        log(f"незакрытых сделок поднято: досчитано по ленте {n_fixed}"
            + (f", возвращено в работу {n_alive}" if n_alive else "")
            + (f", без исхода {n_left} (лента не дотянулась)"
               if n_left else ""))
    if n_tr or n_paper:
        log(f"поднято из своих файлов: сделок {n_tr:,}, "
            f"бумажных сделок {n_paper}")
    else:
        log("подъём истории не требуется — середина читается по запросу")


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
    sh = c.shards[0]
    sh.on_message(None, json.dumps(snap))
    sh.on_message(None, json.dumps(
        {"topic": "orderbook.50.TEST", "type": "delta",
         "ts": 1_700_000_000_100,
         "data": {"s": "TEST", "u": 2, "b": [["100.0", "0"]], "a": []}}))
    sh.on_message(None, json.dumps(
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


def dropped_symbols(root, syms, days=3):
    """Символы, по которым на диске есть свежие ряды, а в запуске их нет.

    Список монет задаётся строкой запуска, то есть живёт в чужой
    консоли, а не в репозитории. Достаточно один раз запустить сборщик
    командой из README — и половина монет молча пропадает: процесс
    поднимается исправным, страница показывает исправные восемь, и
    заметить это можно только глазами через сутки. Ровно так и вышло.

    Свежесть обязательна: инструмент, который сняли месяц назад,
    ругался бы вечно, и предупреждение перестали бы читать.
    """
    d = os.path.join(root, "trades")
    if not os.path.isdir(d):
        return []
    edge = time.time() - days * 86400
    gone = []
    for s in sorted(os.listdir(d)):
        if s in syms or not os.path.isdir(os.path.join(d, s)):
            continue
        try:
            files = os.listdir(os.path.join(d, s))
            fresh = max((os.path.getmtime(os.path.join(d, s, f))
                         for f in files), default=0)
        except OSError:
            continue
        if fresh >= edge:
            # Глубина, а не только свежесть: файл — час, поэтому их число
            # и есть накопленное. Без этого ошибочный запуск на три
            # минуты оставляет след, на который сторож потом ругается
            # вечно наравне с монетой, собиравшейся неделю, — и
            # предупреждение перестают читать.
            gone.append((s, len(files)))
    if not gone:
        return []
    gone.sort(key=lambda x: -x[1])
    names = ", ".join(f"{s} ({n} ч)" for s, n in gone)
    return [f"ВНИМАНИЕ: на диске есть свежие ряды ещё по {len(gone)} "
            f"символам, а в этом запуске их нет: {names}",
            "сбор по ним прекращён — при составе `all` так выглядит "
            "делистинг; если это не нарочно, проверьте строку запуска"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=SYMBOLS_DEFAULT,
                    help="`all` — все торгуемые линейные USDT-перпы минус "
                         "не-крипто (решение владельца, 2026-08-01) — "
                         "либо список через запятую")
    ap.add_argument("--raw", default=",".join(RAW),
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
    ap.add_argument("--paper", action="store_true",
                    help="вести бумажные сделки детектора; по умолчанию "
                         "выключены — направление ленты закрыто "
                         "замерами T1–T4, поглощение входит в модель "
                         "гипотезы 6 признаками")
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
    t0 = time.time()

    lines = LogBuf()

    def log(m):
        line = f"[{time.time() - t0:8.0f} с] {m}"
        lines.add(line)
        print(line, flush=True)

    syms = resolve_symbols(a.symbols, log)
    raw = [s.strip() for s in a.raw.split(",") if s.strip()]
    raise_nofile(log, want=nofile_want(len(syms)))
    shown = (", ".join(syms) if len(syms) <= 40
             else ", ".join(syms[:30]) + f", … ещё {len(syms) - 30} "
             f"(полный список в status.json)")
    log(f"символов {len(syms)}: {shown}")
    for m in dropped_symbols(a.out, syms):
        log(m)
    if raw:
        log(f"сырой поток пишется для: {', '.join(raw)}")
    log(f"каталог {a.out}")
    deep = [x.strip() for x in a.deep.split(",") if x.strip()]
    c = Collector(syms, raw, a.out, log, deep=deep, paper=a.paper)
    log("глубина стакана: " + ", ".join(
        f"{s_}={c.depth[s_]}" for s_ in syms))
    c.lines = lines

    # `pkill` шлёт TERM, и без обработчика процесс умирал, не закрыв
    # файлы: последняя запись терялась, а раньше — портила весь архив.
    def bye(signum, frame):
        log(f"сигнал {signum}: закрываю файлы")
        c.stop.set()
        c.w.close()
        for sh in c.shards:
            if sh.ws is not None:
                try:
                    sh.ws.close()
                except Exception:                         # noqa: BLE001
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
    # Подъём идёт ФОНОМ: сбор обязан начать писать сразу. Раньше он
    # стоял перед подпиской, и на полной записи каждый перезапуск
    # обходился в двенадцать минут тишины — а перезапусков при отладке
    # много. История — удобство страницы, запись — смысл всего.
    def _warm():
        try:
            warm_start(a.out, syms, c, log)
        except Exception as e:                            # noqa: BLE001
            log(f"поднять историю не вышло ({type(e).__name__}: {e}); "
                f"сбор продолжается с нуля")
    threading.Thread(target=_warm, daemon=True).start()
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
