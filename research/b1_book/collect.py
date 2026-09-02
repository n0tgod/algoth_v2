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
import subprocess
import random
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
# Файлы тени ядра: статус пишет `bot run`, маркер выключения —
# `tools/run_bot.sh --off` (решение владельца 2026-08-22). Констан-
# тами, а не строками в методе: их подменяет тест, и вторая копия
# пути разошлась бы с первой.
SHADOW_STATUS = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                             "bot", "out", "shadow", "status.json")
SHADOW_OFF = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                          "bot", "out", "SHADOW_OFF")
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from book import BANDS, STORE_LADDER, Book, parse_trades                 # noqa: E402
import paper                                              # noqa: E402
import signals                                            # noqa: E402
from signals import RULES_VERSION, Signals                # noqa: E402
from store import Writer, read_hour, read_jsonl            # noqa: E402
from common import universe_filter as UF                   # noqa: E402
# Реестр книг — ОДИН на цикл, страницы и дерево. Импортируется прямо
# (а не лениво, как `trades`), потому что модуль без импортов вовсе:
# он не тянет ни numpy, ни математику признаков.
import books as BK                                        # noqa: E402
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


def _median(xs):
    """Медиана списка. Пустой список сюда не приходит — вызывающий
    обязан проверить: медиана пустоты есть ноль ровно в том смысле, в
    каком «нет данных» есть «рынок стоял», то есть ни в каком."""
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


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
    """Не-крипто символы Bybit: справочник плюс курируемый список.

    Определение одно на проект — `research/common/universe_filter`:
    сборщик решает, что записывать, модель — что торговать, и два
    расходящихся определения означали бы, что модель выбирает то, чего
    сборщик не пишет. Прежняя оговорка «листинги после снимка так не
    распознаются» закрыта курируемым списком и правилом суффикса
    (решение владельца, 2026-08-07): в записи жили UBER, SHOP и ещё
    четыре десятка токенизированных акций, и сеть их выбирала.
    """
    return UF.non_crypto_set(universe_path)


def recent_pick_symbols(hours=6, s8_root=None):
    """Символы из выборов модели за последние часы.

    Их запись обязана дожить до разбора: ряд, оборванный до планового
    закрытия позиции, оставляет её «без исхода», а такие держат кассу
    навсегда (урок RAREUSDT). Шесть часов — горизонт удержания плюс
    запас на опоздание разбора; фильтр выбора новых сделок на такие
    имена не даёт, поэтому множество пустеет само.
    """
    root = s8_root or os.path.join(
        os.path.dirname(HERE), "s8_loop", "out")
    out = set()
    cut = time.time() - hours * 3600
    for name in ("model",):
        try:
            with open(os.path.join(root, name, "picks.jsonl"),
                      encoding="utf-8") as f:
                lines = f.read().split("\n")
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                pk = json.loads(line)
                h0 = datetime.strptime(pk.get("hour") or "",
                                       "%Y-%m-%d-%H")
            except ValueError:
                continue
            if h0.replace(tzinfo=timezone.utc).timestamp() < cut:
                continue
            for side in ("long", "short"):
                for x in pk.get(side) or []:
                    if x.get("sym"):
                        out.add(x["sym"])
    return out


HOUR = 3600.0
PHASE_TOL = 120.0                 # допуск на попадание в ту же фазу часа


def disk_rate(samples, now, total):
    """Скорость роста занятого места — байт в час, или `None`.

    Замер устроен так, а не «разностью по окну», потому что занятое
    место пилообразно: текущий час лежит простым текстом и растёт, при
    закрытии часа сжимается целиком, и место проседает. Отсюда два
    способа соврать, и оба уже наблюдались на живом сборе.

    Окно короче часа не накрывает ни одного закрытия и меряет рост
    НЕСЖАТЫХ файлов: сразу после перезапуска выходило 4.0 ГБ/ч и «диска
    на 0.8 дня» при свободных восьмидесяти гигабайтах. Тревога, которая
    врёт в первый же час, перестаёт читаться.

    Окно произвольной длины сравнивает разные фазы часа: начало у пика
    пилы, конец у впадины — и рост выходит **отрицательным**, что и
    видно было как «−1736 МБ/ч» через четыре минуты после закрытия.

    Поэтому сравниваются две точки в одной фазе часа: ровно час назад
    плюс-минус две минуты. Простой кусок текущего часа тогда одинаков в
    обеих точках и в разность не входит, а входит только то, что
    прибавилось после сжатия.
    """
    best = None
    for t, b in samples:
        d = abs(now - t - HOUR)
        if d <= PHASE_TOL and (best is None or d < best[0]):
            best = (d, t, b)
    if best is None:
        return None, None
    _, t0, b0 = best
    return (total - b0) / (now - t0) * HOUR, t0


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
    ref = non_crypto_bybit()
    # Решение владельца (2026-08-13): не-крипто ПИШЕТСЯ. Ситуационная
    # книга вправе их торговать (выход у неё по уровню, а не по
    # времени), а торговать можно только записываемое. Из книг со
    # сроком их убирает `tradable_rows` в цикле.
    grace = recent_pick_symbols()
    kept = sorted(s for s in got
                  if UF.is_non_crypto(s, ref) and s in grace)
    syms = list(got)
    log(f"справочник площадки: {len(got)} торгуемых USDT-перпов, "
        f"пишутся все (не-крипто торгует только ситуационная книга)"
        + (f"; дописываются до закрытия позиций: {', '.join(kept)}"
           if kept else ""))
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
                # Крайние цены с прошлого взгляда сторожа. Сторож
                # смотрит раз в пять секунд, а уровень задевается
                # путём: у POWERUSDT 8 августа тейк был пробит внутри
                # одной минуты (низ 0.09119 при уровне 0.09161) и
                # мгновенный снимок его не увидел — сделка осталась
                # открытой. Лента даёт путь целиком, и стоит это двух
                # сравнений на принт.
                #
                # Копить экстремум в самой ленте нельзя: у неё сто
                # двадцать последних принтов, а в обвале их сотни в
                # секунду — окно свернулось бы раньше, чем сторож
                # посмотрит.
                ex = c.px_ext.get(sym)
                if ex is None:
                    c.px_ext[sym] = [t["p"], t["p"]]
                else:
                    if t["p"] > ex[0]:
                        ex[0] = t["p"]
                    if t["p"] < ex[1]:
                        ex[1] = t["p"]
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
        self._model_cache = (0.0, None, object())
        # Цены входа по (символ, час). Закрытый час не меняется, значит
        # прочитанное можно помнить навсегда.
        self._px_cache = {}
        # Кольцевые буферы для страницы наблюдения: она смотрит в память,
        # а не в файлы — между данными и глазом не должно быть выгрузки.
        self.lock = threading.Lock()
        self.mid = {s: deque(maxlen=900) for s in symbols}   # 15 минут
        # По каким символам середина уже дочитана с диска. Подъём идёт
        # по запросу страницы, а не для всех разом: см. `warm_mid`.
        self.mid_warmed = set()
        self.tape = {s: deque(maxlen=120) for s in symbols}
        # Путь цены между взглядами сторожа: [максимум, минимум] по
        # принтам. Читается и сбрасывается сторожем; принт, пришедший
        # ровно между чтением и сбросом, теряется — одна сделка из
        # сотен, и это дешевле, чем блокировка на каждом принте.
        self.px_ext = {}
        # Дневной тормоз (забор владельца 2026-08-29): состояние
        # считает фоновый поток, сканер и страницы только читают.
        # None до первого счёта — тормоз НЕИЗВЕСТЕН и не тормозит,
        # но состояние обязано быть видно (fail-open с криком).
        self._brake = None
        self.brake_skips = 0
        # Живой шум монеты для правила v11 сканера: кеш на минуту,
        # состав целых минут меняется раз в минуту, а сканер
        # спрашивает раз в пять секунд по всем кандидатам.
        self._noise_cache = {}
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

    def candles_files(self, sym, hours=12, end=None):
        """Минутные свечи из записей — история глубже памяти сборщика.

        В памяти живут несколько часов посекундной истории, а сделки
        поднимаются за трое суток: график обрывался там, где кончался
        буфер, и прошлые сделки посмотреть было не на чем.

        `end` — конец окна. Он нужен потому, что сделку открывают из
        таблицы, а таблица помнит недели: у сделки недельной давности
        «последние N часов» не содержат ни одной её свечи, и график
        показал бы пустоту там, где запись есть. Вперёд окно не
        уезжает — будущих свечей не существует, и просьба о них
        означала бы ошибку в вызывающем, а не пустой ответ.

        Закрытый час неизменен, поэтому его свечи считаются один раз и
        кладутся в память. Текущий час пересчитывается каждый запрос —
        он ещё дописывается.
        """
        sym = sym if sym in self.books else self.symbols[0]
        now = time.time()
        try:
            anchor = min(float(end), now) if end else now
        except (TypeError, ValueError):
            anchor = now
        hh = [datetime.fromtimestamp(anchor - i * 3600, timezone.utc)
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
        # `end` возвращается тем, что было применено: страница просит
        # окно и обязана уметь отличить «записи за это время нет» от
        # «сервер про окно не знает и отдал свежее». Первое — правда о
        # данных, второе — дефект, и по пустому списку они неотличимы.
        return {"sym": sym, "candles": out, "hours": len(hh),
                "end": anchor}

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

    # Не чаще раза в это число секунд: сигнал открыт в сеть, и
    # долбёжка им превратилась бы в непрерывный `git fetch` рядом с
    # живым сбором. Отказ по частоте — не ошибка, а состояние.
    POKE_MIN_GAP = 10.0

    def jobs_poke(self):
        """Немедленно посмотреть очередь заданий (`jobs/`).

        Сторож ходит раз в пять минут, и владельцу это долго. Сигнал
        сокращает ожидание до секунд, НЕ расширяя полномочий: он не
        несёт ни команды, ни аргумента, а лишь запускает тот же
        `tools/jobs.sh`, который зовёт сторож. Что позволено —
        решает белый список внутри, задания приходят коммитом.
        """
        now = time.time()
        last = getattr(self, "_poke_at", 0.0)
        if now - last < self.POKE_MIN_GAP:
            return {"ok": False, "why": "слишком часто",
                    "retry_in": round(self.POKE_MIN_GAP - (now - last), 1)}
        self._poke_at = now
        root = os.path.dirname(os.path.dirname(HERE))
        sh = os.path.join(root, "tools", "jobs.sh")
        if not os.path.exists(sh):
            return {"ok": False, "why": "очередь не развёрнута"}
        try:
            # Фоном: `jobs.sh` делает `git fetch`, а ответ странице
            # нужен сразу. Вывод идёт в журнал очереди — сигнал не
            # вправе становиться вторым местом, где живут результаты.
            log = os.path.join(root, "jobs", "poke.log")
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n== сигнал {int(now)} ==\n")
                f.flush()
                subprocess.Popen(["bash", sh], cwd=root, stdout=f,
                                 stderr=subprocess.STDOUT,
                                 start_new_session=True)
        except OSError as e:
            return {"ok": False, "why": f"не запустилось: {e}"}
        return {"ok": True, "at": round(now, 1)}

    def bot_status(self):
        """Статус исполнительного ядра (Rust-тень) — из его файла.

        Ядро пишет `status.json` атомарно каждый такт; страница только
        читает. Отсутствие файла — «не запущено», и это не тревога
        (ядро может быть не развёрнуто), а состояние словами. Возраст
        считается ЗДЕСЬ, по часам сервера: у страницы свои часы, и на
        телефоне они уходят.
        """
        # Выключена решением владельца — это СОСТОЯНИЕ, не поломка и
        # не «не развёрнуто»: маркер пишет tools/run_bot.sh --off, и
        # панель обязана назвать причину словами, иначе остановленная
        # тень неотличима от сломанной.
        try:
            with open(SHADOW_OFF, encoding="utf-8") as f:
                return {"present": False, "off": True,
                        "off_note": f.readline().strip()}
        except OSError:
            pass
        try:
            with open(SHADOW_STATUS, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            return {"present": False}
        st["present"] = True
        try:
            st["age_sec"] = round(
                time.time() - float(st.get("at_ms", 0)) / 1000.0, 1)
        except (TypeError, ValueError):
            st["age_sec"] = None
        return st

    @staticmethod
    def journal_marker(text):
        """Разобрать маркер журнала тени: (каталог книги, версия кассы).

        Маркер пишет `run_bot.sh` строкой «<путь книги> cash=N».
        Разбирать его basename-ом целиком — значит получить
        «model_sit cash=4», не найти такой книги и молча увести панель
        на главную: ровно это и случилось, когда в маркер добавили
        версию правила кассы. Маркер прежнего образца (без версии)
        читается как «версия неизвестна», а не как нулевая.
        """
        parts = str(text or "").strip().split()
        base = os.path.basename(parts[0]) if parts else ""
        cash = None
        for p in parts[1:]:
            if p.startswith("cash="):
                cash = p.split("=", 1)[1]
        return base, cash

    def bot_full(self):
        """Полные данные страницы ядра: статус, журнал, переоценка.

        Журнал читается функциями `bot/sverka.py` — той же реализацией,
        что сверяет сделки. Вторая копия чтения однажды разошлась бы с
        первой (урок загрузчика funding), и страница показывала бы одни
        сделки, а сверка судила бы другие.

        Переоценка открытых позиций — по СВОЕЙ книге сборщика: середина
        лучших цен прямо сейчас. Это брутто до издержек, и страница
        обязана подписать это словами.
        """
        st = self.bot_status()
        if not st.get("present"):
            return st
        root = os.path.join(os.path.dirname(os.path.dirname(HERE)), "bot")
        sys.path.insert(0, root)
        import sverka as SV
        jdir = os.path.join(root, "out", "shadow")
        # Книга тени — из маркера источника журнала (пишет run_bot.sh):
        # странице нужен адрес книги, чтобы открыть сделку на графике
        # именно той книги, которую ведёт ядро.
        # Маркер несёт ДВА поля: каталог книги и версию правила кассы
        # (`<путь> cash=N`). Брать от него basename целиком — значит
        # получить «model_sit cash=4», не найти такой книги и молча
        # увести панель на главную: ровно это и случилось, когда в
        # маркер добавили версию.
        try:
            with open(os.path.join(jdir, "source.txt"),
                      encoding="utf-8") as f:
                base, cash_was = self.journal_marker(f.read())
        except OSError:
            base, cash_was = "", None
        # Ключ книги — обращением КАРТЫ, а не своим списком: третий
        # список каталогов уже разошёлся с картой (он держал `model_z`
        # там, где живая пара давно `model_h24z`), и панель уводила бы
        # на график чужой книги.
        st["book_hz"] = {v: k for k, v in self.BOOK_DIRS.items()
                         if k != "h4"}.get(base, "")
        # Правило кассы, которым писан журнал, против действующего.
        # Журнал дописывается и хранит размеры, посчитанные правилом на
        # момент записи, а Python пересчитывает всё заново — после
        # правки правила сверка краснеет НАВСЕГДА и перестаёт быть
        # сигналом. Архивирует журнал `run_bot.sh` при запуске; пока
        # ядро не перезапущено, страница обязана сказать, что красное
        # объясняется этим, а не расхождением реализаций.
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                            "s8_loop"))
            import trades as TRV
            now_v = str(TRV.CASH_RULES_VERSION)
        except Exception:                                # noqa: BLE001
            now_v = None
        if now_v is not None and cash_was is not None \
                and cash_was != now_v:
            st["cash_stale"] = {"was": cash_was, "now": now_v}
        try:
            recs = SV.read_journal(jdir)
        except SystemExit as e:
            st["journal_error"] = str(e)
            return st
        capital = float(st.get("capital_usd") or 1000.0)
        bal = capital
        opens, closed, curve = {}, [], []
        decisions = rejects = 0
        for r in recs:
            ev = r.get("ev")
            if ev == "decision":
                decisions += 1
            elif ev == "reject":
                rejects += 1
            elif ev == "open":
                opens[r["pos"]] = r
            elif ev == "close":
                o = opens.pop(r["pos"], None)
                if o is None:
                    continue
                bal += r["pnl_usd"]
                closed.append({
                    "pos": r["pos"],
                    "hour": (r["pos"].split(":") + ["", ""])[1],
                    "sym": o.get("sym"), "side": o.get("side"),
                    "size": round(o.get("notional_usd") or 0.0, 2),
                    "entry_px": o.get("entry_px"),
                    "exit_px": r.get("exit_px"),
                    "pnl": round(r["pnl_usd"], 2),
                    "basis": ("книга" if "книга" in (r.get("reason") or "")
                              else "плоский 11"),
                    "closed_at": r["at_ms"] / 1000.0,
                })
                curve.append([r["at_ms"] / 1000.0, round(bal, 2)])
        now = time.time()
        positions = []
        for pos, o in sorted(opens.items()):
            sym = o.get("sym")
            mid = None
            bk = self.books.get(sym)
            if bk is not None:
                try:
                    bid, ask = bk.best()
                    if bid and ask:
                        mid = (bid + ask) / 2.0
                except Exception:                     # noqa: BLE001
                    mid = None
            entry = o.get("entry_px")
            unreal_bp = None
            if mid and entry:
                mv = (mid / entry - 1.0) * 1e4
                unreal_bp = round(mv if o.get("side") == "long" else -mv, 1)
            hour = (pos.split(":") + ["", ""])[1]
            try:
                h0 = datetime.strptime(hour, "%Y-%m-%d-%H").replace(
                    tzinfo=timezone.utc).timestamp()
                closes_at = h0 + 5 * 3600.0
            except ValueError:
                closes_at = None
            size = o.get("notional_usd") or 0.0
            positions.append({
                "pos": pos, "sym": sym, "side": o.get("side"),
                "size": round(size, 2), "entry_px": entry, "cur_mid": mid,
                "unreal_bp": unreal_bp,
                "unreal_usd": (round(size * unreal_bp / 1e4, 2)
                               if unreal_bp is not None else None),
                "opened_at": o["at_ms"] / 1000.0,
                "closes_at": closes_at,
            })
        # Хвост отчёта сверки — числа обязаны быть видны на странице, а
        # не только вердикт (пересказ теряет числа — правило публикации).
        rep = None
        try:
            with open(os.path.join(jdir, "sverka-report.md"),
                      encoding="utf-8") as f:
                rep = "\n".join(f.read().split("\n")[:40])
        except OSError:
            pass
        st.update(
            positions=positions,
            closed=closed[-200:][::-1],
            closed_total=len(closed),
            curve=curve,
            counts={"decisions": decisions, "rejects": rejects,
                    "closed": len(closed), "open": len(positions)},
            sverka_report=rep,
            server_now=now,
        )
        return st

    @staticmethod
    def _median(a):
        """Медиана с честной серединой на чётном числе: sorted[n//2]
        на двух заполнениях выдавал верхнее из двух за медиану —
        первые же живые сделки показали +17.1 вместо +10.1."""
        if not a:
            return None
        a = sorted(a)
        n = len(a)
        m = a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2.0
        return round(m, 1)

    @staticmethod
    def _model_round_bp():
        """Модельный круг издержек — у самого ядра расчёта, не числом
        здесь: две записи одной константы однажды разошлись бы (тот же
        довод, что у версии кассы в run_bot.sh)."""
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                            "s8_loop"))
            import trades as TR
            return float(TR.ROUND_COST_BP)
        except Exception:                             # noqa: BLE001
            return None

    def live_exec(self):
        """Живые сделки исполнителя ПРОТИВ бумажного сигнала книги.

        Предмет страницы playbook (решение владельца 2026-08-21):
        каждая живая сделка X3 — та же сделка, что бумажная запись
        ситуационной книги, посчитанная двумя счетами, и расхождение
        между ними и есть то, что замер живых денег меряет. Вход:
        цена исполнения против цены СИГНАЛА (Decision несёт цену
        события — её видел сканер в секунду решения). Выход: тейк по
        уровню лимиткой (правило v13) — исполнилась или нет. Деньги:
        нетто живой сделки в б.п. её нотионала против бумажного
        `net_bp` той же записи — доллары сравнивать нельзя, у бумажной
        позиции 300 $, у живой 30.

        Журнал читается `sverka.read_journal` — той же реализацией,
        что у панели ядра: вторая копия чтения однажды разошлась бы.
        Бумажная сторона — `_book_view` торгуемой ситуационной книги,
        тем же кодом, что обзор и страница сделок. Сопоставление — по
        ключу позиции (рука:час:имя:сторона): его пишут оба счёта.

        Отсутствие журнала — состояние словами, не ошибка: исполнитель
        может быть не развёрнут. В сухом прогоне страница работает
        тоже: сформированные заявки видны отказами с текстом.
        """
        now = time.time()
        c = getattr(self, "_live_exec_cache", None)
        if c and now - c[0] < 10:
            return c[1]
        root = os.path.join(os.path.dirname(os.path.dirname(HERE)), "bot")
        jdir = os.path.join(root, "out", "live")
        out = {"present": False, "server_now": now}
        try:
            with open(os.path.join(jdir, "live_status.json"),
                      encoding="utf-8") as f:
                st = json.load(f)
            try:
                st["age_sec"] = round(
                    now - float(st.get("at_ms", 0)) / 1000.0, 1)
            except (TypeError, ValueError):
                st["age_sec"] = None
            out["status"] = st
            out["present"] = True
        except (OSError, ValueError):
            out["status"] = None
        try:
            with open(os.path.join(jdir, "mode.txt"),
                      encoding="utf-8") as f:
                out["mode"] = f.read().strip() or None
        except OSError:
            out["mode"] = None

        sys.path.insert(0, root)
        recs = []
        try:
            import sverka as SV
            recs = SV.read_journal(jdir)
        except SystemExit as e:
            out["journal_error"] = str(e)
        except Exception as e:                        # noqa: BLE001
            out["journal_error"] = str(e)[:200]
        if recs:
            out["present"] = True

        decisions, opens, closes, rejects = {}, {}, {}, []
        adjusts = {}
        counts = {"decisions": 0, "opened": 0, "closed": 0,
                  "rejects_dry": 0, "rejects_exec": 0}
        for r in recs:
            ev = r.get("ev")
            if ev == "decision":
                counts["decisions"] += 1
                k = ":".join((r.get("arm") or "", r.get("hour") or "",
                              r.get("sym") or "", r.get("side") or ""))
                decisions[k] = r
            elif ev == "open":
                counts["opened"] += 1
                opens[r.get("pos")] = r
            elif ev == "close":
                counts["closed"] += 1
                closes[r.get("pos")] = r
            elif ev == "adjust":
                # Поправка денег после закрытия: сделка «вне
                # исполнителя» несла ноль, а биржа деньги знала
                # (closed-pnl) — исполнитель дописал их отдельной
                # записью при перезапуске. Переписать строку закрытия
                # нельзя (журнал write-ahead), поэтому знание живёт
                # рядом и складывается при показе.
                adjusts[r.get("pos")] = r
            elif ev == "reject":
                reason = r.get("reason") or ""
                if "сухой прогон" in reason:
                    counts["rejects_dry"] += 1
                else:
                    counts["rejects_exec"] += 1
                rejects.append({"sym": r.get("sym"),
                                "side": r.get("side"),
                                "reason": reason,
                                "at": (r.get("at_ms") or 0) / 1000.0})

        # Бумажная сторона — КНИГА ИЗ МАРКЕРА журнала (book.txt пишет
        # run_live.sh): исполнитель переводится между книгами, и
        # зашитая model_sit после перевода сопоставляла бы живые
        # сделки с чужой бумагой, ничем себя не выдав. Журнал без
        # маркера писан до его появления — с model_sit.
        paper, paper_error = {}, None
        try:
            book_base = self.BOOK_DIRS["sit"]
            try:
                with open(os.path.join(jdir, "book.txt"),
                          encoding="utf-8") as f:
                    book_base = (f.read().strip()
                                 or self.BOOK_DIRS["sit"])
            except OSError:
                pass
            out["book"] = book_base
            # Ключ книги для ссылок страницы (график, разбор сделки):
            # зашитое hz=sit после перевода журнала на другую книгу
            # вело бы в чужую запись — тот же класс дефекта, что
            # список книг в восьми местах. Обратная карта от
            # единственной BOOK_DIRS; неизвестный каталог падает на
            # sit, как все прежние журналы без маркера.
            out["book_hz"] = next(
                (k for k, v2 in self.BOOK_DIRS.items()
                 if v2 == book_base), "sit")
            s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
            mdir = os.path.join(s8, book_base)
            with open(os.path.join(mdir, "manifest.json"),
                      encoding="utf-8") as f:
                mman = json.load(f)
            v = self._book_view(mdir, mman, lite=True)
            for pt in v["trades"]:
                paper[(pt.get("arm"), pt.get("hour"), pt.get("sym"),
                       pt.get("side"))] = pt
        except Exception as e:                        # noqa: BLE001
            paper_error = str(e)[:200]

        rows = []
        slips, fees, deltas = [], [], []
        level_fills = level_misses = 0
        pnl_live = 0.0
        matched = unmatched = 0
        for pos, o in opens.items():
            parts = (str(pos).split(":", 3) + ["", "", "", ""])[:4]
            arm, hour, sym, side = parts
            d = decisions.get(pos)
            cl = closes.get(pos)
            sig = d.get("px") if d else None
            entry = o.get("entry_px")
            notional = float(o.get("notional_usd") or 0.0)
            sgn = 1.0 if side == "long" else -1.0
            # Проскальзывание входа: положительное = хуже для нас, у
            # обеих сторон. Нет цены сигнала — нет измерения, не ноль.
            slip = None
            if sig and entry:
                slip = round((entry / sig - 1.0) * 1e4 * sgn, 1)
                slips.append(slip)
            row = {"pos": pos, "arm": arm, "hour": hour, "sym": sym,
                   "side": side, "size": round(notional, 2),
                   "sig_px": sig, "entry_px": entry, "slip_bp": slip,
                   "opened_at": (o.get("at_ms") or 0) / 1000.0,
                   "state": "открыта"}
            pt = paper.get((arm, hour, sym, side))
            if pt is not None:
                matched += 1
                row["tid"] = pt.get("tid")
                row["paper_net_bp"] = pt.get("net_bp")
                row["paper_pnl"] = pt.get("pnl")
                row["paper_state"] = pt.get("state")
            else:
                unmatched += 1
            if cl is None:
                # Открытая позиция несёт ОТМЕТКУ по текущей середине —
                # тем же способом, что панель ядра. Отметка не исход:
                # своя колонка, своя плитка, с закрытым не складывается;
                # нет цены — прочерк, а не ноль.
                mid = None
                bk = self.books.get(sym)
                if bk is not None:
                    try:
                        bid, ask = bk.best()
                        if bid and ask:
                            mid = (bid + ask) / 2.0
                    except Exception:                 # noqa: BLE001
                        mid = None
                if mid and entry:
                    mv = (mid / entry - 1.0) * 1e4
                    row["cur_px"] = round(mid, 8)
                    row["unreal_bp"] = round(
                        mv if side == "long" else -mv, 1)
                    row["unreal_usd"] = round(
                        notional * row["unreal_bp"] / 1e4, 2)
            if cl is not None:
                row["state"] = "закрыта"
                row["exit_px"] = cl.get("exit_px")
                row["closed_at"] = (cl.get("at_ms") or 0) / 1000.0
                pnl = float(cl.get("pnl_usd") or 0.0)
                adj = adjusts.get(pos)
                if adj is not None:
                    # Деньги, доехавшие с биржи задним числом: у самой
                    # записи закрытия ноль, настоящая сумма — в
                    # поправке. Складывает СЕРВЕР, той же строкой, что
                    # считает нетто, — страница не вправе делать это
                    # сама (вторая касса).
                    pnl += float(adj.get("pnl_usd") or 0.0)
                    row["pnl_exch"] = True
                pnl_live += pnl
                row["pnl"] = round(pnl, 2)
                fee = (float(o.get("fee_usd") or 0.0)
                       + float(cl.get("fee_usd") or 0.0))
                if notional:
                    row["live_net_bp"] = round(pnl / notional * 1e4, 1)
                    row["fee_bp"] = round(fee / notional * 1e4, 1)
                    fees.append(row["fee_bp"])
                reason = cl.get("reason") or ""
                row["reason"] = reason
                # Свежее закрытие «вне исполнителя» берёт деньги с
                # биржи прямо в записи — помечается тем же флагом.
                if "взяты с биржи" in reason:
                    row["pnl_exch"] = True
                # Правило v13 живьём: тейк-лимитка на уровне.
                if "лимитка исполнилась" in reason:
                    row["level_fill"] = True
                    level_fills += 1
                elif "НЕ исполнилась" in reason:
                    row["level_fill"] = False
                    level_misses += 1
                if (row.get("live_net_bp") is not None
                        and isinstance(row.get("paper_net_bp"),
                                       (int, float))):
                    row["delta_bp"] = round(
                        row["live_net_bp"] - row["paper_net_bp"], 1)
                    deltas.append(row["delta_bp"])
            rows.append(row)
        rows.sort(key=lambda r: r.get("opened_at") or 0.0)

        med = self._median
        out.update(
            counts=counts,
            rows=rows[-200:][::-1],
            rejects=rejects[-50:][::-1],
            paper_error=paper_error,
            summary={
                "open": sum(1 for r in rows if r["state"] == "открыта"),
                "open_priced": sum(
                    1 for r in rows if r.get("unreal_usd") is not None),
                "open_marked_usd": (round(sum(
                    r["unreal_usd"] for r in rows
                    if r.get("unreal_usd") is not None), 2)
                    if any(r.get("unreal_usd") is not None
                           for r in rows) else None),
                "closed": counts["closed"],
                "entry_slip_med_bp": med(slips),
                "entry_slip_n": len(slips),
                "fee_med_bp": med(fees),
                "fee_n": len(fees),
                "model_round_bp": self._model_round_bp(),
                "level_fills": level_fills,
                "level_misses": level_misses,
                "pnl_live": round(pnl_live, 2),
                "net_delta_med_bp": med(deltas),
                "net_delta_n": len(deltas),
                "matched": matched,
                "unmatched": unmatched,
            })
        self._live_exec_cache = (now, out)
        return out

    # Ситуационная книга на странице ОДНА, а записей две: торгуемая
    # (свой гейт по отношению, 6 мест, её ведёт тень бота) и
    # наблюдательная (те же правила входа, требование к отношению
    # снято, 24 места). Порог владельца выбирает, какая отвечает:
    # ниже гейта торгуемых сделок не существует вовсе, и ответить
    # может только наблюдательная. Правило живёт ЗДЕСЬ, на сервере, —
    # обзор и страница сделок обязаны решать это одинаково, а две
    # реализации одного правила однажды разойдутся.
    #
    # `None` и ноль здесь РАЗНЫЕ: `None` — «владелец не выбирал», то
    # есть книга как она торгует; ноль — «любое отношение», то есть
    # сознательный переход к наблюдательной записи.
    @staticmethod
    def sit_source(rr_min, traded_gate):
        if rr_min is None or not traded_gate:
            return "traded"
        return "observation" if rr_min < float(traded_gate) else "traded"

    def model_state(self, rr_min=None):
        """Состояние модели S8 для страницы: манифест, мысли, живой IC.

        Пути фиксированы, ключ обязателен на уровне сервера; кеш на
        30 с, потому что источники меняются раз в сутки. Отсутствие
        модели — не ошибка, а именованное состояние: она копит запись.
        """
        now = time.time()
        at, cached, was = self._model_cache
        # Кеш ключуется порогом: тот же ответ на другой порог был бы
        # молчаливой подменой отбора — таблица показывала бы один
        # фильтр, а числа считались по другому.
        if cached is not None and now - at < 30 and was == rr_min:
            return cached
        s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
        # Предпросмотр снят решением владельца (2026-08-07): боевой
        # контур обучен и торгует, строительные леса убраны. Его
        # артефакты остаются на диске, но не отдаются.
        # Порог применяется ТОЛЬКО к книге без срока: у часовых книг
        # обещания пути не служат ни входом, ни выходом, и фильтровать
        # их тем же числом значило бы сравнивать разные вещи.
        # Время сборки — ЧИСЛОМ в ответе, по каждой книге отдельно.
        # «Страницы медленные» невозможно чинить на ощупь: пока не
        # видно, какая книга и какой шаг стоят секунд, оптимизируется
        # наугад. Ответ `/model` в какой-то момент перестал
        # укладываться в минуту, и понять это можно было только
        # таймаутом снаружи.
        took = {}
        t_book = time.time()
        out = self._model_dir_state(os.path.join(s8, self.BOOK_DIRS["h4"]))
        took["h4"] = round((time.time() - t_book) * 1000)
        # Турнир темпов: книги остальных горизонтов — те же веса, свой
        # срок удержания и свой счёт. Отдаются отдельными ключами, а не
        # подмешаны: смесь двух книг в одной таблице выглядела бы
        # осмысленно и не значила бы ничего.
        #
        # Каталог берётся ИЗ КАРТЫ, а не собирается из ключа. Здесь
        # стояло `f"model_{key}"`, и у четырёх книг из пяти соглашение
        # совпадало с картой — а пятая (`z`) молча читала прежний
        # каталог `model_z`: страница показывала книгу 4 ч под именем
        # 24 ч per σ. Карта книг существует ровно для того, чтобы
        # каталог не выводился соглашением.
        books = {}
        for key in (k for k in self.BOOK_DIRS if k != "h4"):
            t_book = time.time()
            st = self._model_dir_state(
                os.path.join(s8, self.BOOK_DIRS[key]),
                rr_min=rr_min if key.startswith("sit") else None)
            took[key] = round((time.time() - t_book) * 1000)
            if st.get("present"):
                books[key] = st
        # Ситуационная секция одна: под ключом `sit` едет та запись,
        # которая отвечает на выбранный порог. Гейт торгуемой книги
        # едет рядом ЧИСЛОМ — без него показ не сможет ни подписать
        # подмену, ни отличить «книга как торгует» от «пересчёт».
        sit = books.get("sit")
        if sit is not None:
            gate = (sit.get("manifest") or {}).get("min_rr")
            src = self.sit_source(rr_min, gate)
            base = books.get("sit_obs") if src == "observation" else sit
            books["sit"] = dict(base or sit, source_book=src,
                                traded_gate=gate)
        if books:
            out["books"] = books
        # Дневной тормоз — состояние на страницу: без строки на экране
        # час без входов при сработавшем тормозе читался бы как отказ,
        # а тормоз, молча умерший, — как работающий (класс «защита,
        # которой молча нет»). None до первого счёта — тоже состояние.
        bs = getattr(self, "_brake", None)
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        out["day_brake"] = dict(
            bs or {}, active=TR.day_brake_active(bs, now),
            stale=(bs is None
                   or now - float(bs.get("at") or 0)
                   > TR.DAY_BRAKE_STALE_SEC))
        out["took_ms"] = took
        out["took_total_ms"] = round((time.time() - now) * 1000)
        self._model_cache = (now, out, rr_min)
        return out

    def live_overlay(self, mdir, tr, reviews):
        """Живые события сборщика поверх истории выборов и разбора.

        Ситуационная книга живёт секундами, а строки выбора и разбора
        пишет часовой цикл. До него позиция существует ТОЛЬКО в файлах
        событий, и показ, молчащий о ней до конца часа, есть отказ
        показа: вход случился в моменте, и владелец видит его на
        графике сразу.

        Функция одна на обзор и на страницу сделок намеренно. Пока
        наложение жило внутри обзора, страница истории читала голые
        `picks.jsonl` — и после смены правил книги обзор показывал
        двенадцать открытых позиций, а история ноль. Расхождение это
        выглядело как поломка выгрузки, а было двумя разными ответами
        на один вопрос.

        Деньги не трогаются ни входом, ни выходом: их считает разбор,
        и касса возвращает их тогда же. Тень бота читает те же два
        файла, и показ, обгоняющий её, развёл бы два счёта.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        conv = {(t.get("sym"), t.get("opened_at")) for t in tr}
        closed = {(rv.get("hour"), r.get("sym"), r.get("side"))
                  for rv in reviews or []
                  for r in rv.get("rows") or []}
        for e in self._jsonl(os.path.join(mdir, "entries_live.jsonl")):
            if (e.get("sym"), e.get("at_ts")) in conv:
                continue
            if (e.get("hour"), e.get("sym"), e.get("side")) in closed:
                continue
            tr.insert(0, {
                "arm": e.get("arm") or "gbm",
                "hour": e.get("hour"), "sym": e.get("sym"),
                "side": e.get("side"), "state": "открыта",
                "opened_at": e.get("at_ts"), "closes_at": None,
                "expected_bp": e.get("fwd"),
                "mae_bp": e.get("mae"),
                # Линия среднего и происхождение стопа — те же поля,
                # что кладёт в сделку разбор. Без них свежая позиция
                # рисовалась бы на графике без второй линии, и это
                # читалось бы как «стоп стоит на прогнозе», то есть
                # как прежнее правило.
                "mae_m_bp": e.get("mae_m"),
                "stop_of": e.get("adverse_of"),
                "mfe_bp": e.get("mfe"),
                "entry_px": e.get("px"),
                "why": e.get("why"),
                "setup": e.get("setup"),
                "train_seq": e.get("train_seq"),
                "fwd0_bp": e.get("fwd0"),
                "noise_bp": e.get("noise_bp"), "eaten": e.get("eaten"),
                "odd": e.get("odd"), "live_wait": True})
            # Id — тем же правилом, что у построенных сделок: поля
            # совпадают с будущей строкой выбора, поэтому имя позиции
            # не меняется, когда цикл перепишет событие в книгу.
            tr[0]["tid"] = TR.tid_of(tr[0])
        # Живые ВЫХОДЫ — зеркально входам. Сторож закрывает позицию
        # секундами, а строку разбора пишет часовой цикл: до него
        # страница показывала позицию открытой, хотя её уже нет.
        # Владелец увидел это на HFTUSDT — цена дошла до цели в 00:35,
        # разбор шёл в 01:06, и сделка висела открытой почти час.
        pend = {}
        for e in self._jsonl(os.path.join(mdir, "exits_live.jsonl")):
            k = (e.get("arm") or "gbm", e.get("hour"),
                 e.get("sym"), e.get("side"))
            pend.setdefault(k, e)          # первое пересечение решает
        for t in tr:
            if t.get("state") != "открыта":
                continue
            e = pend.get((t.get("arm"), t.get("hour"),
                          t.get("sym"), t.get("side")))
            if not e:
                continue
            t["state"] = "вышла, ждёт разбора"
            t["exit_pending"] = True
            t["exit_ts"] = e.get("at_ts")
            t["exit_px"] = e.get("px")
            t["exit_move_bp"] = e.get("move_bp")
            t["exit_reason"] = e.get("reason")
            t["closes_in_sec"] = None
        return tr

    def _book_view(self, mdir, mman, rr_min=None, lite=False):
        """Сделки, деньги и сводки книги — ОДНИМ кодом на обе дороги.

        Обзор и страница сделок читали одну книгу двумя разными
        кусками кода, и куски разошлись ровно так, как расходятся все
        вторые копии в этом проекте. Обзор строил книгу по ПОСЛЕДНИМ
        200 строкам `picks.jsonl` и `review.jsonl`, а страница — по
        файлам целиком; окна двух файлов покрывают разные периоды, и
        у ситуационной книги это давало 141 позицию «вышла, ждёт
        разбора» при том, что их разбор давно записан на диск. Касса
        деньги таких позиций не возвращает (они не «закрыта»), свежие
        входы получали размер 0, и **весь бумажный PnL книги выходил
        ровно нулём** — найдено владельцем.

        Числа расходились у ВСЕХ книг, где файл длиннее окна: у 24 ч
        обзор показывал 765 закрытых и +285 $ против 2170 и +717 $ у
        страницы. Урезание при этом ничего не экономило — ответ
        `/model` весил 17.5 МБ и строился 8.5 с, потому что в него
        уезжали те же 200 строк с лесенками стакана.

        Счёт — величина от ВСЕЙ истории: касса занимает и возвращает
        деньги последовательно с первого дня, и книга, начатая с
        середины, считает другие размеры позиций. Поэтому окна здесь
        нет вовсе, а урезается только то, что отдаётся странице.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
        import trades as TR
        sit = bool(mman.get("situational"))
        hold = self.book_hold(mman, TR.HOLD_H)
        path_h = (int(mman.get("max_age_h") or 24) if hold is None
                  else hold)
        picks = self._jsonl(os.path.join(mdir, "picks.jsonl"))
        revs = self._jsonl(os.path.join(mdir, "review.jsonl"))
        tr = TR.build(picks, revs, hold_h=hold,
                      px_at=self.entry_px(picks),
                      books=TR.load_books(
                          os.path.join(mdir, "books.jsonl")))
        # Живые события — ДО переоценки: строка, наложенная после
        # `TR.mark`, оставалась без отметки. Разборы передаются
        # ЦЕЛИКОМ: наложение по ним и решает, какие выходы уже
        # записаны, и урезанный список воскрешал закрытые позиции.
        if sit:
            self.live_overlay(mdir, tr, revs)
        TR.mark(tr, self.marks(tr))
        # Решение, схлопнувшее встречный лот, СДЕЛКОЙ не является и в
        # списках сделок ему не место (правило владельца): позиции по
        # нему не открывалось, у записи нет ни входа, ни размера, ни
        # денег, и в таблице она выглядела сделкой на ноль долларов.
        # Из записи оно не исчезает — остаётся у закрытого им лота
        # причиной выхода «встречный сигнал закрыл позицию» и
        # достаётся по своему id, — но числом идёт отдельно: молча
        # потерять решение модели нельзя.
        netted = [t for t in tr if t.get("state") == "схлопнула позицию"]
        tr = [t for t in tr if t.get("state") != "схлопнула позицию"]
        tr, rr_cut, rr_unknown = TR.by_rr(tr, rr_min if sit else None)
        cap = {}
        for a in ("gbm", "nn"):
            cap[a] = TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                                slots=mman.get("slots"),
                                sizing=mman.get("sizing"))[1]
        out = {"trades": tr, "cap": cap, "hold": hold, "path_h": path_h,
               "sit": sit, "rr_min": rr_min or 0, "rr_cut": rr_cut,
               "rr_unknown": rr_unknown, "picks": picks, "review": revs,
               "netted": len(netted)}
        if lite:
            return out
        hrows = self.paths(tr, hold_h=path_h)
        TR.dd_money(tr)
        stats = {a: TR.summary(tr, a, capital=cap[a],
                               start=TR.START_BALANCE)
                 for a in ("gbm", "nn")}
        both = sum(v for v in cap.values() if v) or None
        stats["all"] = TR.summary(tr, capital=both,
                                  start=2 * TR.START_BALANCE)
        # Схлопнувшие решения — рядом со счётчиками сделок, но НЕ в
        # них: в `trades` их нет, потому что сделками они не стали.
        for a in ("gbm", "nn"):
            stats[a]["netted"] = sum(1 for t in netted
                                     if t.get("arm") == a)
        stats["all"]["netted"] = len(netted)
        curves = {a: TR.equity(tr, a, hrows, hold_h=path_h)
                  for a in ("gbm", "nn")}
        for a in ("gbm", "nn"):
            stats[a]["dd_book"] = TR.max_dd(curves[a])
            stats[a]["dd_open_book"] = TR.worst_open(curves[a])
        both_c = TR.merge(curves.values())
        stats["all"]["dd_book"] = TR.max_dd(both_c)
        stats["all"]["dd_open_book"] = TR.worst_open(
            both_c, deposit=2 * TR.START_BALANCE)
        out["stats"] = stats
        out["curves"] = curves
        out["both_curve"] = both_c
        return out

    @staticmethod
    def slim_pick(pk):
        """Строка выбора без лесенок стакана — то, что читает обзор.

        Странице нужны сторона, имя, прогноз, обещание пути и новизна;
        лесенка книги в каждой ноге весит на порядок больше и в показе
        не участвует вовсе. Это она делала ответ `/model` в 17.5 МБ.
        """
        if not isinstance(pk, dict):
            return pk
        out = {k: v for k, v in pk.items() if k not in ("long", "short")}
        for side in ("long", "short"):
            out[side] = [{k: v for k, v in (p or {}).items()
                          if k != "cum"} for p in (pk.get(side) or [])]
        return out

    @staticmethod
    def slim_review(rv):
        """Строка разбора без лесенок — обзор берёт из неё «last: got»."""
        if not isinstance(rv, dict):
            return rv
        out = {k: v for k, v in rv.items() if k != "rows"}
        out["rows"] = [{k: v for k, v in (r or {}).items() if k != "cum"}
                       for r in (rv.get("rows") or [])]
        return out

    def _model_dir_state(self, mdir, rr_min=None):
        out = {"present": False}
        try:
            with open(os.path.join(mdir, "manifest.json"),
                      encoding="utf-8") as f:
                out = {"present": True, "manifest": json.load(f)}
        except (OSError, ValueError):
            pass
        # Готовность к обучению: сколько часов уже стали сечениями.
        # Без неё «модели нет» означает и «копим запись», и «запись
        # копится вхолостую, ни один час не годен» — а это разные
        # состояния, и второе стоило суток трижды.
        try:
            with open(os.path.join(mdir, "readiness.json"),
                      encoding="utf-8") as f:
                out["readiness"] = json.load(f)
        except (OSError, ValueError):
            pass
        for arm in ("gbm", "nn"):
            try:
                with open(os.path.join(mdir, f"account_{arm}.json"),
                          encoding="utf-8") as f:
                    out.setdefault("accounts", {})[arm] = json.load(f)
            except (OSError, ValueError):
                pass
        # Выборы и разборы здесь НЕ читаются: их читает `_book_view`
        # целиком, и урезанное окно давало книге чужие числа. Сюда
        # едет только хвост для показа — и уже без лесенок.
        for name, key, keep in (("thoughts.jsonl", "thoughts", 60),
                                ("ic_history.jsonl", "ic", 90)):
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
        out["ic"] = self.ic_summary(out.get("ic") or [])
        try:
            with open(os.path.join(mdir, "last_run.json"),
                      encoding="utf-8") as f:
                out["last_run"] = json.load(f)
        except (OSError, ValueError):
            pass
        # Сделки, деньги и сводки — ТЕМ ЖЕ кодом, что у страницы
        # сделок (`_book_view`). Две реализации здесь уже разошлись
        # однажды: обзор строил книгу по последним 200 строкам файлов
        # и показывал у ситуационной книги ноль денег при +94.84 $ на
        # странице. Одна дорога — расхождению неоткуда взяться.
        try:
            mman = out.get("manifest") or {}
            v = self._book_view(mdir, mman, rr_min=rr_min)
            out["rr_min"] = v["rr_min"]
            out["rr_cut"] = v["rr_cut"]
            out["rr_unknown"] = v["rr_unknown"]
            out["trades"] = v["trades"][:300]
            out["trades_total"] = len(v["trades"])
            out["trade_stats"] = v["stats"]
            out["netted"] = v.get("netted", 0)
            # Странице обзора нужны ПОСЛЕДНИЙ выбор и последний разбор
            # каждой руки — она сама берёт из списка последний. Всё,
            # что раньше ехало сверх этого (200 строк с лесенками на
            # книгу), было чистым весом: 17.5 МБ на опрос.
            last_p, last_r = {}, {}
            for pk in v["picks"]:
                last_p[pk.get("arm") or "gbm"] = pk
            for rv in v["review"]:
                last_r[rv.get("arm") or "gbm"] = rv
            out["picks"] = [self.slim_pick(p)
                            for _, p in sorted(last_p.items())]
            out["review"] = [self.slim_review(r)
                             for _, r in sorted(last_r.items())]
        except Exception as e:                            # noqa: BLE001
            out["trades_error"] = f"{type(e).__name__}: {e}"
            out.setdefault("picks", [])
            out.setdefault("review", [])
        return out

    def model_trades(self, page=0, per=100, arm=None, state=None,
                     sym=None, hz=None, lite=False, rr_min=None):
        """ВСЯ история сделок модели, страницами, со сводкой по всему.

        Отдельно от `model_state`, потому что там история намеренно
        урезана: страница обзора опрашивается раз в минуту, и гонять по
        ней месяцы сделок незачем. Здесь наоборот — читаются файлы
        целиком, а страницами режется только показ.

        Сводка считается по ВСЕЙ выборке, а не по видимой странице:
        статистика, зависящая от того, какую страницу открыли, — не
        статистика.

        `hz` — книга турнира темпов («h1», «h24»); умолчание — главная
        4-часовая. Горизонт берётся из манифеста книги, а не из имени:
        каталог сам говорит, сколько живут его позиции.

        `lite` — режим графика: ему нужны только строки сделок одной
        монеты, а не сводки и кривые. Полный расчёт (просадка каждой
        сделки по почасовым сводкам, кривые счёта, сводки трёх рук)
        занимал секунды и вызывался при каждой смене монеты — владелец
        видел это как «долго грузит». Деньги в строках остаются: их
        проставляет тот же `TR.account`, второй копии счёта нет.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
        import trades as TR
        s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
        name, hz_err = self.book_dir_of(hz)
        if hz_err:
            # Неизвестный ключ книги — отказ СЛОВАМИ. Прежде здесь
            # стоял молчаливый откат на главную книгу, и ссылка на
            # книгу кандидата открывала бы чужие сделки под её именем.
            return {"error": hz_err, "hz": hz}
        # Та же развилка, что у обзора, и тем же правилом: ниже гейта
        # торгуемой книги ответить может только наблюдательная запись.
        # Считается ДО чтения файлов — иначе страница сделок и обзор
        # показывали бы под одним порогом разные книги.
        src_book = "traded"
        if hz == "sit":
            try:
                with open(os.path.join(s8, self.BOOK_DIRS["sit"],
                                       "manifest.json"),
                          encoding="utf-8") as f:
                    gate = (json.load(f) or {}).get("min_rr")
            except (OSError, ValueError):
                gate = None
            src_book = self.sit_source(rr_min, gate)
            if src_book == "observation":
                name = self.BOOK_DIRS["sit_obs"]
        mdir = os.path.join(s8, name)
        try:
            with open(os.path.join(mdir, "manifest.json"),
                      encoding="utf-8") as f:
                mman = json.load(f)
        except (OSError, ValueError):
            mman = {}
        # Сделки и деньги — ОБЩИМ кодом с обзором: у книги одна
        # правда, и вторая дорога к ней однажды разошлась (обзор
        # считал по урезанному окну и показывал ноль там, где здесь
        # +94.84 $). Капитал берётся из ПЕРЕСЧЁТА, а не из файла
        # счёта: файл пишет цикл при разборе, у свежей книги его ещё
        # нет, и экспозиция оставалась без знаменателя.
        v = self._book_view(mdir, mman, rr_min=rr_min, lite=lite)
        tr, cap = v["trades"], v["cap"]
        sit, hold, path_h = v["sit"], v["hold"], v["path_h"]
        rr_cut, rr_unknown = v["rr_cut"], v["rr_unknown"]
        # Согласная книга: руки несут ОДНИ И ТЕ ЖЕ сделки —
        # пересечение выборов симметрично по построению. Показ
        # сводится к канонической руке ЗДЕСЬ, а не на странице: список
        # согласных книг на странице стал бы девятым местом, где живёт
        # одно и то же знание, и однажды разошёлся бы с картой.
        # Тождество проверяется числом: разойдись руки — показ
        # остаётся полным, а страница об этом кричит.
        agree = hz in self.AGREE_BOOKS
        arms_match = self.arms_twins(tr) if agree else None
        keep_arm = None
        if agree and arms_match:
            # Спросили руку явно (ссылка графика, разбора сделки) —
            # отдаём ЕЁ копию: иначе уже разосланные ссылки с arm=nn
            # находили бы пустоту. Не спросили — каноническую.
            keep_arm = arm or self.CANON_ARM
            tr = [t for t in tr if (t.get("arm") or "gbm") == keep_arm]
            arm = None          # выбирать между копиями больше нечего
        accs = {}
        for a in ("gbm", "nn"):
            try:
                with open(os.path.join(mdir, f"account_{a}.json"),
                          encoding="utf-8") as f:
                    accs[a] = json.load(f)
            except (OSError, ValueError):
                pass

        def sliced():
            rows = tr
            if arm:
                rows = [t for t in rows if t["arm"] == arm]
            if state:
                rows = [t for t in rows if t["state"] == state]
            if sym:
                rows = [t for t in rows if t["sym"] == sym.upper()]
            return rows, max(10, min(int(per), 500)), max(0, int(page))

        if lite:
            rows, p, g = sliced()
            return {"source": name, "horizon_h": hold,
                    # Слитые позиции — для графика: долив рисуется
                    # точкой на одной позиции, а не отдельной сделкой
                    # (просьба владельца). Считает ЯДРО, а не страница:
                    # склейку показывают график и таблица, и вторая
                    # реализация разошлась бы с первой.
                    "merged": TR.merge_adds(tr),
                    "situational": sit, "source_book": src_book,
                    "stop_tau": mman.get("stop_tau"),
                    "rules_version": mman.get("rules_version"),
                    # Гейты книги — и в лёгком ответе: график собирает
                    # из них объяснение сделки, и без них страница
                    # печатала фолбэк «22» как действующее правило,
                    # хотя гейт давно 33. Число обязано ехать из
                    # манифеста, как в полном ответе.
                    "min_edge_bp": mman.get("min_edge_bp"),
                    "min_rr": mman.get("min_rr"),
                    "max_rr": mman.get("max_rr"),
                    "min_disc_bp": mman.get("min_disc_bp"),
                    "max_eaten": mman.get("max_eaten"),
                    "exit_policy": mman.get("exit_policy"),
                    "noise_mult": mman.get("noise_mult"),
                    "min_stop_bp": mman.get("min_stop_bp"),
                    "no_timer": bool(mman.get("no_timer")),
                    "basket_take_share": mman.get("basket_take_share"),
                    "basket_floor_share":
                        mman.get("basket_floor_share"),
                    "basket_age_h": mman.get("basket_age_h"),
                    "rr_min": rr_min or 0, "rr_cut": rr_cut,
                    "agree": agree,
                    "arms_match": arms_match,
                    "arm_forced": keep_arm,
                    "lite": True, "start": TR.START_BALANCE,
                    "page": g, "per": p, "total": len(rows),
                    "pages": max(1, (len(rows) + p - 1) // p),
                    "filtered": bool(arm or state or sym),
                    "grand_total": len(tr),
                    "rows": rows[g * p:(g + 1) * p]}
        # Сводки, кривые и просадка посчитаны общим видом — здесь их
        # только раскладывают по ответу. Второй расчёт тех же величин
        # и был источником расхождения обзора со страницей.
        stats, curves, both_c = v["stats"], v["curves"], v["both_curve"]
        rows, per, page = sliced()
        total = len(rows)
        # Кривые счёта — на страницу. Прежде они считались здесь ради
        # просадки и выбрасывались, а владелец видел только итоговое
        # число: где счёт рос, где проседал и чем руки разошлись, из
        # одной цифры не читается вовсе.
        curve_out = {a: TR.thin(curves[a]) for a in ("gbm", "nn")}
        curve_out["all"] = TR.thin(both_c)
        return {"source": name, "horizon_h": hold,
                "merged": TR.merge_adds(tr),
                "situational": sit, "source_book": src_book,
                # Правила книги — в ответ: страница графика строит из
                # них объяснение сделки словами, и брать их из своих
                # констант значило бы описывать текущие исходники, а
                # не тот прогон, который открыл сделку.
                "stop_tau": mman.get("stop_tau"),
                "rules_version": mman.get("rules_version"),
                "min_edge_bp": mman.get("min_edge_bp"),
                "min_rr": mman.get("min_rr"),
                "max_rr": mman.get("max_rr"),
                "min_disc_bp": mman.get("min_disc_bp"),
                "max_eaten": mman.get("max_eaten"),
                "noise_mult": mman.get("noise_mult"),
                "min_stop_bp": mman.get("min_stop_bp"),
                "exit_policy": mman.get("exit_policy"),
                # Корзинные правила — как гейты: страница объясняет
                # книгу по ответу, и поле только в лёгком ответе
                # оставило бы полный без правил (найдено живым
                # ответом h24c: no_timer=None при живом манифесте).
                "no_timer": bool(mman.get("no_timer")),
                "basket_take_share": mman.get("basket_take_share"),
                "basket_floor_share": mman.get("basket_floor_share"),
                "basket_age_h": mman.get("basket_age_h"),
                # Порог владельца и его цена в сделках: без этих чисел
                # отфильтрованный счёт неотличим от счёта книги.
                "rr_min": rr_min or 0, "rr_cut": rr_cut,
                "rr_unknown": rr_unknown,
                # Решения, схлопнувшие встречный лот: сделками не
                # стали и в таблице не показываются, но число обязано
                # быть видно — иначе выбор модели пропадает молча.
                "netted": v.get("netted", 0),
                # Согласная книга показывается ОДНОЙ рукой;
                # `arms_match` — та самая проверка числом.
                "agree": agree, "arms_match": arms_match,
                "arm_forced": keep_arm,
                "curves": curve_out, "start": TR.START_BALANCE,
                "page": page, "per": per, "total": total,
                "pages": max(1, (total + per - 1) // per),
                "filtered": bool(arm or state or sym),
                "grand_total": len(tr),
                "stats": stats, "accounts": accs,
                "symbols": sorted({t["sym"] for t in tr}),
                "rows": rows[page * per:(page + 1) * per]}

    @staticmethod
    def ic_summary(rows):
        """Живой IC — МЕДИАНА по накопленным сечениям, а не последний час.

        Замер по одному сечению шумен: ранговая корреляция четырёх сотен
        имён за один час гуляет на десятые доли. Показать последнюю
        запись значило бы выдать шум за измерение — и хуже того, число
        менялось бы каждый час на глазах, создавая впечатление, что
        модель то «видит», то «слепнет».

        Записи двух видов не смешиваются: `section` — по сохранённому
        вектору сечения (один час на запись), всё прочее — прежние веса
        на окне после обучения, там медиана уже посчитана. Сложить их в
        одну величину значило бы усреднить две разные меры.
        """
        by, out = {}, []
        for r in rows:
            if r.get("kind") == "section":
                by.setdefault((r.get("arm"), r.get("target")), []).append(r)
            else:
                out.append(r)
        for (arm, tgt), rs in by.items():
            v = sorted(x["median_ic"] for x in rs
                       if x.get("median_ic") is not None)
            if not v:
                continue
            out.append({"arm": arm, "target": tgt, "kind": "section",
                        "median_ic": round(v[len(v) // 2], 4),
                        "sections": len(v),
                        "hour": rs[-1].get("hour"),
                        "at": rs[-1].get("at")})
        return out

    def hour_rows(self, pairs):
        """Строки почасовых сводок с кэшом: цена, максимум и минимум часа.

        Один загрузчик и на цену входа, и на путь внутри удержания:
        второй обход тех же файлов был бы вторым определением «цены
        часа».

        Отсутствие кэшируется НЕ всегда. Сводка часа пишется циклом с
        задержкой в несколько минут, и запомнить «нет данных» насовсем
        значило бы навсегда потерять просадку свежих сделок — отказ,
        неотличимый от «просадки не было». Свежий час перечитывается,
        старый признаётся отсутствующим.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
        import trades as TR
        need = {k for k in pairs
                if k[0] and k[1] and k not in self._px_cache}
        if need:
            sd = os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                              "summary")
            self._px_cache.update(TR.hour_rows(sd, need))
            now = time.time()
            for k in need:
                if k in self._px_cache:
                    continue
                end = TR.hour_end(k[1])
                if end is None or now - end > self.SUMMARY_WAIT:
                    self._px_cache[k] = None
        return self._px_cache

    # Сколько ждать сводку закрывшегося часа, прежде чем признать, что
    # её не будет. Цикл сводит час через несколько минут после его
    # конца; три часа — заведомо больше с запасом на перезапуск.
    SUMMARY_WAIT = 3 * 3600

    def model_league(self):
        """Лига: что ведёт себя лучше — руки, книги, ситуации, стороны.

        Просьба владельца: отдельная страница наблюдений за каждой
        стратегией и моделью плюс ТОП сделок по прибыльности за
        сегодня/месяц/год. Агрегаты считаются ЗДЕСЬ, на сервере, и
        один раз: сумма и доля побед — простая арифметика, но два
        места, считающих одно и то же, однажды разойдутся (правило
        одной кассы). Деньги каждой сделки при этом не пересчитываются
        — они уже посчитаны разбором и лежат в записи.

        Наблюдательная книга (`model_sit_obs`) НЕ входит: её входы —
        те же кандидаты, что у торгуемой, и смешение посчитало бы одни
        решения дважды. Сделки без исхода не входят тоже: посчитать
        неизвестный исход нулём значило бы разбавить лигу выдумкой.

        Период сделки — момент, когда деньги стали известны (живой
        выход либо конец часа разбора): «топ за сегодня» — про то, что
        закрылось сегодня, а не про то, что сегодня открыто.
        """
        now = time.time()
        at, cached = getattr(self, "_league_cache", (0.0, None))
        if cached is not None and now - at < 60:
            return cached
        rows, errors, scanned, _ = self.closed_rows()
        # Книги-эхо (равный риск) — те же решения, что у торгуемой:
        # в деньгах лиги они считали бы каждую сделку дважды.
        rows = [r for r in rows if r["hz"] not in self.ECHO_BOOKS]
        return self._league_from(rows, errors, scanned, now)

    # Книги турнира темпов: ключ показа → каталог на диске. Список
    # объявлен ОДИН раз — лига и замер волатильности обязаны считать по
    # одному составу книг, иначе одна страница знала бы о книге, о
    # которой другая молчит.
    # Все книги: ключ показа → каталог на диске. ОДНО определение на
    # сборщик. Список жил в четырёх местах, и книга в единицах σ
    # появилась в трёх из них: страница сделок молча падала на главную
    # книгу, то есть показывала ЧУЖИЕ сделки под именем выбранной —
    # отказ, неотличимый от «у книги пока пусто».
    # Состав книг живёт ОДНИМ реестром (`s8_loop/books.py`): какие
    # книги существуют, где их каталоги, что показывать кнопкой. Пока
    # список стоял литералом здесь, его копии расходились трижды —
    # страница сделок отдавала главную книгу под именем выбранной,
    # сводка собирала каталог соглашением `model_<ключ>`, лига звала
    # книги своими ярлыками. Каталог НЕ выводится из ключа намеренно:
    # у четырёх книг из пяти соглашение совпадало, а пятая молча
    # читала чужой каталог.
    BOOK_DIRS = BK.dirs()
    # Торгуемые: наблюдательная запись повторяет входы торгуемой, и в
    # счётах по книгам её быть не должно.
    BOOKS = BK.traded()

    def book_dir_of(self, hz):
        """Ключ книги → (каталог, причина отказа).

        Карты выше собраны НА ИМПОРТЕ и описывают ядро. Кандидаты
        фабрики появляются каждый час (цикл объявляет книгу и пишет
        `books_extra.json`), значит на импорте их знать невозможно: с
        неподвижной картой книга жила бы на диске, а страница о ней
        молчала — и, что хуже, ключ отбрасывался бы как чужой, а
        `BOOK_DIRS.get(hz) or "model"` МОЛЧА отдавал бы главную книгу
        под именем выбранной. Ровно этот отказ уже трижды случался с
        каталогом книги, и каждый раз выглядел исправной страницей.

        Поэтому: ядро — из карты, кандидаты — с диска с коротким
        кешем, а неизвестный ключ есть ОТКАЗ СЛОВАМИ, а не подмена
        книги. Пустой ключ — главная книга, это умолчание адреса.
        """
        if not hz:
            return self.BOOK_DIRS["h4"], None
        b, why = self.book_rec(hz)
        if b:
            return b["dir"], None
        return None, (f"книги {hz!r} нет"
                      + (f"; кандидаты не читаются: {why}" if why
                         else ""))

    def book_rec(self, hz):
        """Запись книги по ключу — (запись или None, причина отказа).

        Ядро отвечает картой, кандидаты читаются с диска. Кеш короткий
        и общий на всех читателей: два кеша одного состава разошлись
        бы так же, как расходились две карты книг.
        """
        for b in BK.REGISTRY:
            if b["key"] == hz:
                return b, None
        now = time.time()
        at, cached = getattr(self, "_extras_cache", (0.0, None))
        if cached is None or now - at > 60:
            # Состав кандидатов — ДАННЫЕ, и путь к ним строится от
            # `HERE`, как у всех прочих файлов книг: тесты подменяют
            # `HERE`, и резолвер, читающий состав от `__file__`,
            # исполнял бы на проверке живой сервер.
            ex, why = BK.extras(os.path.join(
                os.path.dirname(HERE), "s8_loop", BK.EXTRAS_FILE))
            self._extras_cache = (now, (ex, why))
            cached = (ex, why)
        ex, why = cached
        for b in ex:
            if b["key"] == hz:
                return b, why
        return None, why

    @staticmethod
    def book_hold(mman, default_h):
        """Срок сборки сделок книги; None — у книги нет таймера.

        Без срока живут ситуационные книги (выход по уровню, не по
        времени) и корзинная `h24c` (`no_timer` в манифесте:
        единственный выход — закрытие корзины целиком). Сборка с
        горизонтом переводила бы их позиции в «ждёт разбора» по часам
        и возвращала бы кассе деньги, которые позиция ещё держит.
        Правило жило четырьмя копиями выражения — четвёртая дорога до
        показа однажды разошлась бы с остальными.
        """
        if mman.get("situational") or mman.get("no_timer"):
            return None
        return int(mman.get("horizon_h") or default_h)
    # Эхо и согласные — флаги реестра, а не списки здесь: почему они
    # существуют, записано там же, где сам состав книг.
    ECHO_BOOKS = BK.echo_keys()

    AGREE_BOOKS = BK.agree_keys()

    # Показ согласной книги сводится к ОДНОЙ руке — канонической, той
    # же, что на дереве. Это не украшение, а двойной счёт: фильтр руки
    # по умолчанию «обе», значит каждая её сделка стояла в таблице
    # ДВАЖДЫ, а вкладка «all» считала её дважды.
    CANON_ARM = BK.CANON_ARM

    @staticmethod
    def arms_twins(trades):
        """Тождественны ли руки книги — проверка ЧИСЛОМ, не словом.

        Сводить показ к одной руке законно, только пока пересечение
        симметрично на самом деле. Разойдись руки (дефект эха,
        недописанный час) — половина результата исчезла бы с экрана
        молча, а страница выглядела бы исправной. Сравниваются состав
        и деньги; поля сводятся в строку, потому что `None` рядом с
        числом сортировке не поддаётся.
        """
        def key(a):
            return sorted(
                "|".join(str(t.get(f)) for f in
                         ("hour", "sym", "side", "state", "net_bp",
                          "pnl"))
                for t in trades if (t.get("arm") or "gbm") == a)
        return key("gbm") == key("nn")

    # Дерево моделей: что за логику проверяет каждая ветка, простыми
    # словами и на обоих языках разом (правило справочника: разъехавшись,
    # переводы стали бы двумя разными утверждениями о модели). Ключи
    # ОБЯЗАНЫ совпадать с `BOOK_DIRS` — это закреплено тестом: ветка без
    # текста была бы на странице пустотой, неотличимой от «книги нет».
    ROOT_TREE = {
        "gbm": {
            "title": "ML — decision trees",
            "title_ru": "ML — деревья решений",
            "plain": "Gradient-boosted trees on histograms. Reads "
                     "thresholds and break points — “if this feature "
                     "is past X, the situation is different”. Robust "
                     "to outliers; every forecast decomposes into "
                     "exact feature contributions.",
            "plain_ru": "Градиентный бустинг на гистограммах. Читает "
                        "пороги и изломы — «если признак выше "
                        "такого-то, ситуация другая». Устойчив к "
                        "выбросам; каждый прогноз раскладывается на "
                        "точные вклады признаков."},
        "nn": {
            "title": "AI — neural net",
            "title_ru": "AI — нейросеть",
            "plain": "A small neural network on the same features and "
                     "targets. Blends many features smoothly and can "
                     "catch interactions the trees miss, but overfits "
                     "easier and its explanations are approximate.",
            "plain_ru": "Небольшая нейросеть на тех же признаках и "
                        "целях. Гладко смешивает много признаков сразу "
                        "и ловит взаимодействия, которых деревья не "
                        "видят, но легче переобучается, и её "
                        "объяснения приблизительны."},
        "agree": {
            "title": "ML + AI — agreed",
            "title_ru": "ML + AI — согласие рук",
            "plain": "Books that trade only where BOTH heads picked "
                     "the same name and side in the same hour. The "
                     "intersection is symmetric, so the two arms of "
                     "an agreed book hold identical trades by "
                     "construction — the tree shows each book once, "
                     "with the trees-arm account as the canonical "
                     "one. Echo books: their money never joins the "
                     "ML or AI root sums. Caveat measured before "
                     "they existed: agreement filters the MIDDLE, "
                     "not the tail — the day brake holds the tail.",
            "plain_ru": "Книги, торгующие только там, где ОБЕ руки "
                        "выбрали одно имя и сторону в один час. "
                        "Пересечение симметрично, поэтому руки "
                        "согласной книги несут тождественные сделки "
                        "по построению — дерево показывает каждую "
                        "книгу один раз, каноническим идёт счёт руки "
                        "деревьев. Книги-эхо: их деньги не входят в "
                        "суммы корней ML и AI. Оговорка, измеренная "
                        "до их заведения: согласие фильтрует "
                        "СЕРЕДИНУ, не хвост — хвост держит дневной "
                        "тормоз."},
    }
    BOOK_TREE = {
        "h4": {
            "title": "4-hour book — the main one",
            "title_ru": "Книга 4 часа — главная",
            "plain": "Every hour takes the most extreme forecasts of "
                     "the 4-hour horizon — six names long, six short — "
                     "and holds exactly four hours. Since the owner’s "
                     "decision the extremes are counted in units of "
                     "the coin’s own volatility, not in basis points: "
                     "raw targets made «extreme» mean «volatile», and "
                     "the measured pick was six times wilder than the "
                     "market. The book’s history continues the pair "
                     "that already traded that order — it is the same "
                     "book, not a new one. Entries also pass a floor "
                     "of 30 bp (≈3× the cost round, from the "
                     "extremeness probe): a quiet hour is not traded "
                     "at all. Tests the core question of hypothesis "
                     "6: does ranking the cross-section make money at "
                     "all.",
            "plain_ru": "Каждый час берёт самые крайние прогнозы "
                        "четырёхчасового горизонта — шесть имён в лонг "
                        "и шесть в шорт — и держит ровно четыре часа. "
                        "Решением владельца крайность считается в "
                        "единицах собственной волатильности монеты, а "
                        "не в базисных пунктах: на сырых целях "
                        "«крайний» значило «волатильный», и выбранное "
                        "имя выходило вшестеро размашистее рынка. "
                        "История книги продолжает пару, которая этим "
                        "порядком уже торговала, — это та же книга, а "
                        "не новая. Вход проходит и пол в 30 б.п. "
                        "(≈3× круга, из зонда крайности): тихий час "
                        "не торгуется вовсе. Проверяет главный вопрос "
                        "гипотезы 6: зарабатывает ли само ранжирование "
                        "сечения."},
        "h24": {
            "title": "24-hour book — does the signal live a day",
            "title_ru": "Книга 24 часа — живёт ли сигнал сутки",
            "plain": "The daily pace: fewer trades, less fee, longer "
                     "in risk. Tests the slow end — whether the "
                     "forecast survives a full day of holding. This is "
                     "also the one horizon deliberately LEFT on the "
                     "raw order: it is the control half of the per σ "
                     "pair next to it, and switching it too would "
                     "leave nothing to compare against.",
            "plain_ru": "Суточный темп: сделок меньше, комиссии "
                        "меньше, в риске дольше. Проверяет медленный "
                        "край — доживает ли прогноз до конца суток "
                        "удержания. Это же единственный горизонт, "
                        "намеренно ОСТАВЛЕННЫЙ на сыром порядке: он "
                        "контрольная половина стоящей рядом пары per "
                        "σ, и перевести его значило бы остаться без "
                        "сравнения."},
        "z": {
            "title": "24 h per σ — the control pair",
            "title_ru": "24 ч per σ — контрольная пара",
            "plain": "Books 4 h, 1 h and situational now order the "
                     "section by the forecast divided by the coin’s own "
                     "volatility. This pair keeps the comparison alive "
                     "on the one horizon that was NOT switched: 24 h "
                     "runs both orderings side by side, same section, "
                     "same geometry, one thing different. Without it "
                     "there would be nothing left to answer «does per σ "
                     "help» with.",
            "plain_ru": "Книги 4 ч, 1 ч и ситуационная теперь "
                        "упорядочивают сечение прогнозом, делённым на "
                        "собственную волатильность монеты. Эта пара "
                        "держит сравнение живым на единственном "
                        "горизонте, который НЕ переводили: у 24 ч "
                        "идут оба порядка разом — то же сечение, та же "
                        "геометрия, отличается ровно одно. Без неё "
                        "отвечать на «помогает ли per σ» стало бы "
                        "нечем."},
        "sit": {
            "title": "situational book — price pulls the trigger",
            "title_ru": "Ситуационная книга — курок у цены",
            "plain": "The model draws the map, live price pulls the "
                     "trigger: entry only when price gives a discount "
                     "to the sheet forecast, crossing the gate before "
                     "our eyes. Stop is the learned quantile level "
                     "(~20 % breach), target is the promised "
                     "favourable move, plus an age limit. Tests "
                     "whether picking the moment adds what scheduled "
                     "entries cannot. The Rust core shadows this book. "
                     "Per σ changed only the ORDER in which candidates "
                     "are offered a slot — the gate itself stays in "
                     "basis points, because it is derived from the "
                     "cost round and σ units have no such anchor. The "
                     "book was therefore not archived: it sits full "
                     "under a tenth of the time, so the order decides "
                     "anything only rarely; which order took a trade "
                     "is written into the trade itself.",
            "plain_ru": "Модель рисует карту, курок спускает живая "
                        "цена: вход только когда цена даёт скидку к "
                        "прогнозу листа и пересекает гейт у нас на "
                        "глазах. Стоп — выученный квантильный уровень "
                        "(заход ~20 %), тейк — обещанный ход в пользу, "
                        "плюс предел возраста. Проверяет, даёт ли "
                        "выбор момента то, чего не даёт вход по "
                        "расписанию. Эту книгу ведёт тень Rust-ядра. "
                        "Per σ сменил только ПОРЯДОК, в котором "
                        "кандидатам предлагается слот: гейт остался в "
                        "базисных пунктах, потому что выведен из круга "
                        "издержек, а в единицах σ такого якоря нет. "
                        "Поэтому книга и не отставлена: полной она "
                        "стоит меньше десятой части времени, то есть "
                        "порядок решает что-либо редко, а каким "
                        "порядком взята сделка — записано в самой "
                        "сделке."},
        "sit_obs": {
            "title": "observation record — same setup, no RR gate",
            "title_ru": "Наблюдательная запись — та же ситуация без "
                        "порога RR",
            "plain": "Not traded and not in the league money: records "
                     "the same candidates without the ratio "
                     "requirement, so the RR filter has something to "
                     "show below the traded gate.",
            "plain_ru": "Не торгуется и в деньги лиги не входит: "
                        "записывает те же кандидаты без требования к "
                        "отношению, чтобы фильтр по RR мог показать "
                        "сделки ниже боевого гейта."},
        "sit_lo": {
            "title": "Situational, low RR — the other end",
            "title_ru": "Ситуационная низкого RR — другой конец",
            "plain": "Same situational machinery and the same "
                     "candidates as the traded book, with ONE inverted "
                     "rule: the promised reward/risk must be at most "
                     "1.5 instead of at least 2. Born from a "
                     "measurement over the observation record (2321 "
                     "closed trades in a week): the win share falls "
                     "monotonically as the promised RR grows (54% "
                     "below 1 vs 34% above 2), because a high ratio "
                     "is not a bigger target but a TIGHTER stop — the "
                     "median promised stop shrinks 354 to 57 bp while "
                     "the target stays put, and the share of "
                     "stop-exits climbs 17% to 78%. The 1.5 ceiling "
                     "was declared before any confirming data; the "
                     "single best bucket (0–1) is deliberately not "
                     "cherry-picked. The live executor trades this "
                     "book by the owner’s decision.",
            "plain_ru": "Та же ситуационная механика и те же "
                        "кандидаты, что у торгуемой книги, с ОДНИМ "
                        "перевёрнутым правилом: обещанное отношение "
                        "прибыли к риску не выше 1.5 вместо «не ниже "
                        "2». Родилась из замера по наблюдательной "
                        "записи (2321 закрытая сделка за неделю): "
                        "доля побед падает монотонно с ростом "
                        "обещанного RR (54 % ниже 1 против 34 % выше "
                        "2), потому что высокое отношение — это не "
                        "крупная цель, а УЗКИЙ стоп: медиана "
                        "обещанного стопа сжимается 354 → 57 б.п. при "
                        "почти той же цели, и доля выходов по стопу "
                        "растёт 17 % → 78 %. Потолок 1.5 объявлен до "
                        "проверочных данных; лучшую корзину 0–1 "
                        "нарочно не берём — резать тоньше после "
                        "просмотра поверхности есть ошибка R5. Живой "
                        "исполнитель торгует эту книгу решением "
                        "владельца.",
        },
        "sit_r": {
            "title": "situational · fixed risk — equal dollar risk "
                     "per trade",
            "title_ru": "Ситуационная · равный риск — одинаковый "
                        "доллар риска на сделку",
            "plain": "The SAME trades as the situational book — "
                     "gates and slots match — sized so a stop always "
                     "loses one R and a take at RR 3 always earns "
                     "three: size is inverse to the executable stop. "
                     "The owner saw RR 1:3 takes worth $20 and $5 "
                     "while a stop took $15 — levels differ per "
                     "trade, size did not, so dollar expectancy "
                     "broke. Exits ONLY by its own levels — stop "
                     "or take (owner's rule): a forecast flip "
                     "or the age limit never close its trades, "
                     "so every close is -1R or +RR·R. Its entries "
                     "also demand stop room of at least 1.5× the "
                     "coin's live minute noise where the shared "
                     "gate asks one (owner's rule after a stop one "
                     "wick wide), and a stop no tighter than 1 % — "
                     "an equal dollar of risk must fit under the "
                     "per-name cap, tighter stops silently risked "
                     "less than R. Not in "
                     "league or root sums: same decisions would "
                     "be counted twice.",
            "plain_ru": "ТЕ ЖЕ сделки, что у ситуационной книги — "
                        "гейты и места совпадают, — но размер обратен "
                        "исполняемому стопу: стоп всегда −R, тейк при "
                        "RR 3 всегда +3R. Владелец увидел тейки 1:3 "
                        "по 20 $ и по 5 $ при стопе в 15 $ — уровни у "
                        "сделок разные, размер один, и математика "
                        "ожидания в деньгах ломалась. Выходы — "
                        "ТОЛЬКО по своим уровням, стоп или тейк "
                        "(правило владельца): разворот прогноза и "
                        "предел возраста её сделок не закрывают, "
                        "каждый исход — −1R либо +RR·R. Вход вдобавок "
                        "требует запаса до стопа не тоньше ПОЛУТОРА "
                        "живых минутных шумов там, где общий гейт "
                        "требует один (правило владельца после стопа "
                        "шириной в фитиль), и стопа не тоньше 1 % — "
                        "равный доллар риска обязан помещаться под "
                        "потолок имени, тесный стоп молча рисковал "
                        "меньше R. В лигу и сумму "
                        "корня не входит: те же решения считались бы "
                        "дважды."},
        "h24b": {
            "title": "24 h · basket — close all at +5 % of capital",
            "title_ru": "24 ч · корзина — закрыть всё при +5 % "
                        "капитала",
            "plain": "An echo of the 24 h book: the SAME picks, but "
                     "once an hour the combined unrealised PnL of "
                     "all open positions of an arm is checked, and "
                     "at +5 % of the arm's capital — one daily "
                     "sigma of the book's own curve, declared "
                     "before the run — the whole basket is closed "
                     "at once. Honest theory: stopping at a "
                     "threshold creates no expectation, it reshapes "
                     "the distribution into frequent small takes "
                     "and rare deep losses, so judge it by drawdown "
                     "and tail PAIRED against the source book, not "
                     "by the average. Not in league or root sums: "
                     "an echo of the same decisions.",
            "plain_ru": "Эхо книги 24 ч: ТЕ ЖЕ выборы, но раз в час "
                        "проверяется общий нереализованный результат "
                        "всех открытых позиций руки, и при +5 % "
                        "капитала — один суточный ход собственной "
                        "кривой, порог объявлен до прогона — корзина "
                        "закрывается целиком. Честная теория: "
                        "остановка по порогу ожидания не создаёт, "
                        "она меняет форму распределения на частые "
                        "мелкие фиксации и редкие глубокие минусы, "
                        "поэтому судить книгу надо по просадке и "
                        "хвосту ПАРНО против источника, а не по "
                        "среднему. В лигу и сумму корня не входит: "
                        "эхо тех же решений."},
        "h24bf": {
            "title": "24 h · basket ± floor — take +5 %, cut at "
                     "−5 %",
            "title_ru": "24 ч · корзина с полом — тейк +5 %, стоп "
                        "−5 %",
            "plain": "The same basket echo with a symmetric floor: "
                     "the sum reaching −5 % of capital closes "
                     "everything and fixes the common loss. The "
                     "diagnostic arm of the owner's question — is "
                     "it better to wait a shared drawdown out "
                     "(h24b) or to cut it: the two books differ by "
                     "exactly this one rule, so the difference in "
                     "their curves belongs to the floor. Not in "
                     "league or root sums.",
            "plain_ru": "Та же корзина с симметричным полом: сумма, "
                        "дошедшая до −5 % капитала, закрывает всё и "
                        "фиксирует общий убыток. Диагностическая "
                        "рука вопроса владельца — пересиживать общий "
                        "минус (h24b) или резать его: книги "
                        "различаются ровно этим правилом, и разница "
                        "их кривых принадлежит полу. В лигу и сумму "
                        "корня не входит."},
        "h24c": {
            "title": "24 h · basket only — no per-leg exits",
            "title_ru": "24 ч · только корзина — без отдельных "
                        "выходов",
            "plain": "The owner's construction from the basket "
                     "replay: the SAME picks as the 24 h book, but a "
                     "leg NEVER closes on its own — no timer, no "
                     "individual stop or target. The whole basket "
                     "closes at once on one of three declared "
                     "triggers: +5 % of capital, −5 %, or basket age "
                     "24 h (the signal's own horizon — the only "
                     "threshold with an anchor; 48 h looked better "
                     "in the replay but picking it would be choosing "
                     "by the seen surface). The age limit is what "
                     "keeps the book from the replay's diseases: a "
                     "fully-invested blind book and legs living past "
                     "anything the model claimed. Not in league or "
                     "root sums: an echo of the same decisions; the "
                     "verdict needs calendar, not weeks.",
            "plain_ru": "Конструкция владельца из корзинного реплея: "
                        "ТЕ ЖЕ выборы, что у книги 24 ч, но нога не "
                        "закрывается сама НИКОГДА — ни таймера, ни "
                        "отдельного стопа или цели. Корзина "
                        "закрывается только целиком по одному из "
                        "трёх объявленных поводов: +5 % капитала, "
                        "−5 % либо возраст корзины 24 ч (горизонт "
                        "самого сигнала — единственный порог с "
                        "якорем; 48 ч в реплее выглядел лучше, но "
                        "взять его значило бы выбрать по "
                        "просмотренной поверхности). Именно лимит "
                        "возраста снимает болезни реплея — слепую "
                        "вложенную книгу и ноги, живущие дольше "
                        "того, о чём модель что-то утверждала. В "
                        "лигу и сумму корня не входит: эхо тех же "
                        "решений; вердикт даст календарь, а не "
                        "недели."},
        "h24a": {
            "title": "24 h · agreed — both heads picked it",
            "title_ru": "24 ч · согласные — выбрали обе руки",
            "plain": "The agreement probe (2026-08-30) found the "
                     "first live-positive filter of the project: on "
                     "the 24 h book, decisions taken by BOTH heads "
                     "(trees and net picked the same name, side and "
                     "hour) earned +441/+358 bp per trade over solo "
                     "ones at p = 0.000, surviving the no-best-name "
                     "cut and both halves of history. This book "
                     "keeps exactly that intersection of the 24 h "
                     "book's picks — one declared rule, everything "
                     "else copied verbatim, so the difference in "
                     "curves belongs to agreement. Caveat measured "
                     "before the book existed: agreement is a filter "
                     "of the MIDDLE, not the tail — in the 08-24…27 "
                     "drain agreed trades lost the same as solo "
                     "ones; the tail stays with the day brake. Not "
                     "in league or root sums: an echo of the same "
                     "decisions.",
            "plain_ru": "Зонд согласия (2026-08-30) нашёл первый "
                        "живой положительный фильтр проекта: у книги "
                        "24 ч решения, взятые ОБЕИМИ руками (деревья "
                        "и сеть выбрали одно имя, сторону и час), "
                        "дают +441/+358 б.п. на сделку против "
                        "одиночных при p = 0.000 — переживает «без "
                        "лучшего имени» и обе половины истории. Эта "
                        "книга держит ровно то пересечение выборов "
                        "книги 24 ч: правило одно, всё остальное — "
                        "дословная копия, и разница кривых "
                        "принадлежит согласию. Оговорка, измеренная "
                        "ДО заведения книги: согласие — фильтр "
                        "СЕРЕДИНЫ, не хвоста — в слив 08-24…27 "
                        "согласные теряли наравне с одиночными; "
                        "хвост остаётся дневному тормозу. В лигу и "
                        "сумму корня не входит: эхо тех же решений."},
        "h24za": {
            "title": "24 h · per σ · agreed",
            "title_ru": "24 ч · per σ · согласные",
            "plain": "The same agreement rule applied to the per-σ "
                     "24 h book: only names both heads picked. A "
                     "side observation of the drain split (57 "
                     "trades): the per-σ book's agreed trades "
                     "survived the drain in the black — thin and "
                     "unproven (the σ book's halves flipped sign in "
                     "the main probe), which is exactly why it runs "
                     "as its own book: the calendar will answer, "
                     "not a cell picked off a seen surface. Not in "
                     "league or root sums: an echo of the same "
                     "decisions.",
            "plain_ru": "То же правило согласия на книге 24 ч per σ: "
                        "остаются только имена, выбранные обеими "
                        "руками. Побочное наблюдение разреза слива "
                        "(57 сделок): согласные сделки σ-книги "
                        "пережили слив в плюс — тонко и не доказано "
                        "(в основном зонде у σ-книги половины "
                        "истории меняли знак), и ровно поэтому она "
                        "заведена отдельной книгой: ответит "
                        "календарь, а не ячейка с просмотренной "
                        "поверхности. В лигу и сумму корня не "
                        "входит: эхо тех же решений."},
    }
    # Ночной прогон турнира приходит раз в сутки (сторож, окно 02:xx
    # UTC). Запас на одно пропущенное окно: 36 ч — это «одну ночь
    # можно потерять», а двух подряд уже не бывает без поломки.
    TOUR_STALE = 36 * 3600

    TOURNEY_TREE = {
        "title": "policy tournament (spec 10)",
        "title_ru": "Турнир политик исполнения (спека 10)",
        "plain": "72 rule variants of the situational book — stop "
                 "(quantile / forecast line / none) × target × age "
                 "limit × RR gate × entry edge — replayed over the "
                 "sheet journal; once a week a selector picks which "
                 "variant to live by next. What is judged is not the "
                 "winner but the picking rule itself: the selector "
                 "must beat a RANDOM pick from the same variants — "
                 "otherwise self-tuning is decoration.",
        "plain_ru": "72 варианта правил ситуационной книги — стоп "
                    "(квантиль / линия прогноза / нет) × тейк × "
                    "предел возраста × порог RR × край входа — "
                    "прогоняются по журналу листов, и раз в неделю "
                    "селектор сам выбирает, каким вариантом жить "
                    "дальше. Судится не победитель, а само правило "
                    "выбора: селектор обязан бить СЛУЧАЙНЫЙ выбор из "
                    "тех же вариантов — иначе самоподстройка есть "
                    "украшение."}

    def closed_rows(self, books=None):
        """Закрытые сделки всех торгуемых книг — с деньгами.

        `books` — обойти НЕ ядро, а названный список пар (ключ,
        каталог). Заведено для книг кандидатов фабрики: в лигу, на
        дерево и в разбивку волатильности они не входят намеренно
        (там их решения складывались бы с решениями книг владельца), а
        собственная дневная статистика у них обязана быть — иначе
        страница книги отвечала бы «сделок нет» о книге, у которой они
        есть. Умолчание — ядро, то есть прежнее поведение бит в бит.

        Одно определение «закрытой сделки с деньгами» на все страницы,
        которые по ним считают: лига ранжирует, замер волатильности
        раскладывает по режимам рынка. Второй такой обход однажды
        разошёлся бы с первым — например, забыл бы позвать кассу, и
        одна страница видела бы сотни сделок, а другая ни одной.

        Наблюдательная книга (`model_sit_obs`) НЕ входит: её входы —
        те же кандидаты, что у торгуемой, и смешение посчитало бы одни
        решения дважды.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
        rows, errors, scanned, opens = [], [], [], []
        for hz, name in (books if books is not None else self.BOOKS):
            mdir = os.path.join(s8, name)
            try:
                with open(os.path.join(mdir, "manifest.json"),
                          encoding="utf-8") as f:
                    mman = json.load(f)
            except OSError:
                continue                  # книги нет — это не ошибка
            except ValueError as e:
                errors.append(f"{name}: манифест не читается: {e}")
                continue
            try:
                sit = bool(mman.get("situational"))
                hold = self.book_hold(mman, TR.HOLD_H)
                picks = self._jsonl(os.path.join(mdir, "picks.jsonl"))
                revs = self._jsonl(os.path.join(mdir, "review.jsonl"))
                tr = TR.build(picks, revs, hold_h=hold,
                              px_at=self.entry_px(picks),
                              books=TR.load_books(
                                  os.path.join(mdir, "books.jsonl")))
                # Деньги сделки штампует КАССА, а не разбор: в
                # review.jsonl лежат ход и нетто, а `pnl` появляется у
                # сделки только при пересчёте счёта — размер позиции
                # знает лишь он. Без этого вызова лига видела сотни
                # закрытых сделок и ни одного `pnl`; собственный тест
                # прошёл, потому что положил `pnl` в подставной разбор
                # руками. Форма вызова та же, что у страниц, — деньги
                # лиги обязаны совпадать с деньгами показа.
                for a in ("gbm", "nn"):
                    TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                               slots=mman.get("slots"),
                               sizing=mman.get("sizing"))
            except Exception as e:                    # noqa: BLE001
                # Ошибка обязана быть ВИДНА в ответе, а не глотаться:
                # первый же прогон на сервере вернул пустую лигу при
                # 261 закрытой сделке, и по ответу нельзя было сказать,
                # почему, — ровно тот отказ, неотличимый от тишины,
                # против которого весь проект.
                errors.append(f"{name}: {type(e).__name__}: {e}")
                continue
            # Открытые позиции переоцениваются живой серединой стакана
            # тем же `TR.mark`, а деньги отметки считает тот же
            # `TR.summary`, что у обзора: вторая формула однажды
            # разошлась бы, и дерево показывало бы одни открытые
            # деньги, а обзор другие. Живых книг может не быть (тесты,
            # ранний старт) — тогда позиции честно остаются
            # непереоценёнными: «переоценено 0 из N», а не ноль денег.
            op = [t for t in tr if t.get("state") == "открыта"]
            if op and getattr(self, "books", None):
                try:
                    TR.mark(op, self.marks(op))
                except Exception as e:                # noqa: BLE001
                    errors.append(f"{name}: переоценка: "
                                  f"{type(e).__name__}: {e}")
            for a in ("gbm", "nn"):
                sm = TR.summary(tr, arm=a)
                if sm.get("open"):
                    opens.append({"hz": hz, "arm": a,
                                  "open": sm["open"],
                                  "marked": sm.get("marked", 0),
                                  "unreal_pnl": sm.get("unreal_pnl")})
            n0 = len(rows)
            for t in tr:
                if t.get("state") != "закрыта" or t.get("pnl") is None:
                    continue
                su = (t.get("setup") or [None])
                rows.append({
                    "hz": hz, "arm": t.get("arm") or "gbm",
                    "hour": t.get("hour"), "sym": t.get("sym"),
                    "side": t.get("side"),
                    "opened_at": t.get("opened_at"),
                    "at": (t.get("exit_ts") or t.get("closes_at")
                           or t.get("opened_at")),
                    "net_bp": t.get("net_bp"), "pnl": t.get("pnl"),
                    "setup": su[0][0] if su and su[0] else None,
                    "train_seq": t.get("train_seq"),
                    "reason": t.get("exit_reason")})
            scanned.append({"book": name, "trades": len(tr),
                            "closed_kept": len(rows) - n0})
        return rows, errors, scanned, opens

    # Книги, которые сравнимы ПАРНО: одно сечение, один горизонт,
    # различается ровно порядок. У книг разных горизонтов общих часов
    # нет по построению, и сравнивать их итогами значит сравнивать
    # разные периоды.
    #
    # Пара переехала на 24 ч вместе с самой книгой: главная книга сама
    # перешла на порядок в σ, и сравнение «z против h4» стало бы
    # сравнением книги с её же копией. Пара, оставленная на прежнем
    # горизонте, показывала бы разность двух РАЗНЫХ горизонтов и
    # выглядела бы при этом исправной.
    PAIRS = (("z", "h24"),)
    PAIR_BOOT = 4000
    PAIR_SEED = 20260812

    def _book_pairs(self, rows):
        """Парное сравнение книг по ОБЩИМ часам, с интервалом.

        Владелец прочёл «per σ показывает лучшие результаты» по итогам
        рядом — а итоги считаны на разном числе часов и на разных
        именах. Разность двух книг мерится парно и с интервалом
        (правило проекта: `compare_arms` в R5), иначе разница в
        полпроцента на восьмидесяти часах читается как превосходство.

        Единица — среднее нетто ЧАСА, а не сделки: книга набирает в час
        разное число ног, и сделка тяжёлого часа иначе весила бы
        больше.
        """
        out = []
        for a, b in self.PAIRS:
            ga, gb = {}, {}
            for r in rows:
                k = (r["arm"], r["hour"])
                if r["hz"] == a:
                    ga.setdefault(k, []).append(r)
                elif r["hz"] == b:
                    gb.setdefault(k, []).append(r)
            common = sorted(set(ga) & set(gb))
            if len(common) < 20:
                # Числа сторон едут вместе с отказом: «общих часов 0»
                # выглядит поломкой, а «у второй книги закрытых сделок
                # ещё нет» — состоянием. Пара переехала на 24 ч в день,
                # когда главная книга сама перешла на порядок в σ,
                # поэтому нулю тут взяться откуда.
                out.append({"a": a, "b": b, "hours": len(common),
                            "thin": True,
                            "a_hours": len(ga), "b_hours": len(gb)})
                continue
            d = [sum(t["net_bp"] or 0 for t in ga[k]) / len(ga[k])
                 - sum(t["net_bp"] or 0 for t in gb[k]) / len(gb[k])
                 for k in common]
            n = len(d)
            mean = sum(d) / n
            rnd = random.Random(self.PAIR_SEED)
            boot = sorted(sum(d[rnd.randrange(n)] for _ in range(n)) / n
                          for _ in range(self.PAIR_BOOT))
            lo = boot[int(0.025 * self.PAIR_BOOT)]
            hi = boot[int(0.975 * self.PAIR_BOOT)]
            out.append({
                "a": a, "b": b, "hours": n, "thin": False,
                "mean_bp": round(mean, 1),
                "lo_bp": round(lo, 1), "hi_bp": round(hi, 1),
                # Интервал накрывает ноль — разницу предъявить нельзя,
                # какой бы ни была её величина.
                "covers_zero": bool(lo <= 0 <= hi),
                "a_wins": round(sum(1 for x in d if x > 0) / n, 3)})
        return out

    def _league_from(self, rows, errors, scanned, now):
        """Агрегаты лиги из готовых строк — арифметика без чтения."""

        def agg(sub, key):
            """Итог группы И её итог БЕЗ лучшего имени.

            Вторая величина обязательна, а не украшение: владелец
            прочёл «book imbalance / depth» как лучшую стратегию по
            1301 сделке, а замер показал, что +331 $ это TUT (+247),
            XAN (+119) и THE (+49), без них группа даёт −84 $.
            Крупное число сделок делает такую группу похожей на
            статистику, хотя деньги в ней принадлежат одному разгону.
            Тот же приём проект уже применял в `one_name.py`, где
            колонка «без лучшего имени» переворачивала вывод.
            """
            out = {}
            for r in sub:
                k = key(r)
                if k is None:
                    continue
                g = out.setdefault(k, {"n": 0, "w": 0, "pnl": 0.0,
                                       "net": 0.0, "sym": {}})
                g["n"] += 1
                g["w"] += 1 if (r["pnl"] or 0) > 0 else 0
                g["pnl"] += r["pnl"] or 0.0
                g["net"] += r["net_bp"] or 0.0
                g["sym"][r["sym"]] = (g["sym"].get(r["sym"], 0.0)
                                      + (r["pnl"] or 0.0))
            def row(k, g):
                best, bv = None, 0.0
                for sym, v in g["sym"].items():
                    if best is None or v > bv:
                        best, bv = sym, v
                return {"key": k, "n": g["n"],
                        "win": round(g["w"] / g["n"], 3),
                        "pnl": round(g["pnl"], 2),
                        "net_bp_avg": round(g["net"] / g["n"], 1),
                        # Имя, дающее группе больше всех, и итог без
                        # него. Одно имя вместо доли: владелец должен
                        # видеть, ЧТО именно вытягивает группу.
                        "top_sym": best,
                        "top_pnl": round(bv, 2),
                        "pnl_wo_top": round(g["pnl"] - bv, 2),
                        "syms": len(g["sym"])}
            return sorted([row(k, g) for k, g in out.items()],
                          key=lambda x: -x["pnl"])

        def once(sub):
            """Одно РЕШЕНИЕ — одна строка: имя, час и сторона.

            Вопрос владельца: входят ли в статистику одинаковые сделки
            разных книг. Входят, и много — четыре торгуемые книги
            ранжируют ОДНО сечение одними весами, различаясь горизонтом
            и правилами, обе руки берут его же. Замер на живых данных:
            5098 закрытых сделок лиги — это 3770 различных решений,
            828 из них встречаются по нескольку раз (42 % строк
            таблицы), рекорд — семь копий одного решения (SNTUSDT
            шорт), и 78 % денег лиги сидит на повторяющихся решениях.

            Деньги при этом настоящие: у каждой книги свой капитал и
            своя позиция на бирже. Неверна не бухгалтерия, а СЧЁТ
            НАБЛЮДЕНИЙ: «2610 сделок» читается как 2610 наблюдений, а
            их 1991, и на вопрос «какая ситуация работает» копии
            отвечают хором одним голосом.

            Деньги решения — СРЕДНЕЕ по копиям, а не сумма: сумма и
            есть нынешний счёт, а брать лучшую копию значило бы
            выбирать исход задним числом. Ярлык — большинство копий;
            ничья решается именем семейства, чтобы результат не
            зависел от порядка чтения книг. У половины повторов ярлыки
            копий расходятся (замер: 418 из 828 совпали) — книги
            предсказывают разные горизонты, и вклад признаков у них
            свой.
            """
            by = {}
            for r in sub:
                by.setdefault((r["sym"], r["hour"], r["side"]),
                              []).append(r)
            out = []
            for v in by.values():
                cnt = {}
                for x in v:
                    if x["setup"]:
                        cnt[x["setup"]] = cnt.get(x["setup"], 0) + 1
                lab = (sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
                       [0][0] if cnt else None)
                out.append({
                    "sym": v[0]["sym"], "setup": lab,
                    "copies": len(v),
                    "pnl": sum(x["pnl"] or 0.0 for x in v) / len(v),
                    "net_bp": sum(x["net_bp"] or 0.0 for x in v) / len(v)})
            return out

        # «Сегодня» — календарные сутки UTC, не последние 24 часа:
        # владелец читает это как «что закрылось сегодня».
        day0 = (int(now) // 86400) * 86400
        periods = {}
        for pkey, since in (("today", day0),
                            ("30d", now - 30 * 86400),
                            ("365d", now - 365 * 86400)):
            sub = [r for r in rows if (r["at"] or 0) >= since]
            srt = sorted(sub, key=lambda r: -(r["pnl"] or 0))
            periods[pkey] = {
                "n": len(sub),
                "groups": {
                    "arm": agg(sub, lambda r: r["arm"]),
                    "book": agg(sub, lambda r: r["hz"]),
                    "setup": agg(sub, lambda r: r["setup"]),
                    # Та же разбивка по ситуациям, но одно решение —
                    # один голос. Стоит ПЕРВОЙ на странице (решение
                    # владельца): счёт наблюдений там честный, а
                    # нынешняя разбивка идёт рядом второй, чтобы
                    # разницу было видно, а не пересказано.
                    "setup_once": agg(once(sub), lambda r: r["setup"]),
                    "side": agg(sub, lambda r: r["side"]),
                },
                # Сколько строк лиги стоит за сколькими решениями —
                # числом, а не оценкой: без этой пары «2610 сделок»
                # читается как 2610 наблюдений.
                "decisions": len({(r["sym"], r["hour"], r["side"])
                                  for r in sub}),
                "best": srt[:10],
                "worst": srt[::-1][:5],
                "setup_known": sum(1 for r in sub if r["setup"]),
            }
        out = {"present": bool(rows), "closed_total": len(rows),
               "pairs": self._book_pairs(rows),
               "periods": periods,
               "books": scanned, "errors": errors,
               "generated_at": round(now, 1)}
        out["took_ms"] = round((time.time() - now) * 1000)
        self._league_cache = (now, out)
        return out

    @staticmethod
    def _spearman(xs, ys):
        """Ранговая связь — одна реализация на весь сборщик."""
        n = len(xs)
        if n < 5:
            return None
        rx, ry = [0] * n, [0] * n
        for r, i in enumerate(sorted(range(n), key=lambda i: xs[i])):
            rx[i] = r
        for r, i in enumerate(sorted(range(n), key=lambda i: ys[i])):
            ry[i] = r
        mu = (n - 1) / 2.0
        num = sum((rx[i] - mu) * (ry[i] - mu) for i in range(n))
        den = (sum((rx[i] - mu) ** 2 for i in range(n))
               * sum((ry[i] - mu) ** 2 for i in range(n))) ** 0.5
        return round(num / den, 3) if den else None

    # Порог свежести артефакта бумажной книги. Прогон суточный (сторож
    # в окне 06:xx UTC, догон при 36 ч), поэтому старше 36 часов —
    # состояние, о котором страница обязана КРИЧАТЬ: молчащий ночной
    # прогон неотличим от работающего, и это уже случалось с турниром.
    PAPER_STALE = 36 * 3600

    def paper_book(self, at=None):
        """Бумажная месячная книга: свод из артефакта, транши из журнала.

        Разделение источников здесь принципиально, а не техническое.

        **Свод берётся ИЗ АРТЕФАКТА и не пересчитывается.** Все его
        числа — нетто, t по Ньюи–Уэсту, доля прибыльных, funding —
        считает сама книга; вторая их реализация на странице однажды
        разошлась бы с той, что публикуется отчётом, и владелец видел
        бы на экране одно, а в git другое. По той же причине страница
        не считает деньги ни в одной другой книге.

        **Транши берутся из журнала**, потому что артефакт их не
        содержит вовсе: он свод. Здесь не считается ничего сверх
        календаря — числа исхода переносятся из разбора как есть, а
        деление на честное и восстановленное делает `paper_journal`,
        то есть ровно то правило, которым делит сама книга.

        Журнал живёт ТОЛЬКО на машине, где книга считается: в git идут
        одни отчёты. Значит «траншей нет» и «мы не на той машине» —
        разные состояния, и различает их поле `journal_present`.
        """
        now = time.time()
        key = at or ""
        cat, cached = getattr(self, "_paper_cache", (0.0, {}))
        if now - cat < 120 and key in cached:
            return cached[key]
        if now - cat >= 120:
            cached = {}
        root = os.path.join(os.path.dirname(HERE), "paper_monthly")
        sys.path.insert(0, root)
        try:
            import paper_journal as PJ
        except Exception as e:                              # pragma: no cover
            return {"present": False, "reason": f"модуль журнала: {e}"}
        out = os.path.join(root, "out")
        art_path = os.path.join(out, "PAPER-30d.json")
        dec_path = os.path.join(out, "decisions.jsonl")
        res_path = os.path.join(out, "resolutions.jsonl")
        r = {"present": False, "generated_at": round(now, 1),
             "journal_present": os.path.exists(dec_path),
             "stale_after_sec": self.PAPER_STALE}
        if not os.path.exists(art_path):
            r["reason"] = ("прогона книги на этой машине не было: "
                           "артефакт PAPER-30d.json отсутствует")
            return r
        try:
            with open(art_path, encoding="utf-8") as f:
                art = json.load(f)
        except Exception as e:
            r["reason"] = f"артефакт не читается: {e}"
            return r
        age = now - os.path.getmtime(art_path)
        dec = PJ.read_jsonl(dec_path)
        res = PJ.read_jsonl(res_path)
        r.update({
            "present": True,
            "run_at": art.get("run_at"),
            "run_age_sec": round(age),
            "stale": age > self.PAPER_STALE,
            "verdict": art.get("verdict"),
            "rules": {"rules": art.get("rules"), "k": art.get("k"),
                      "h": art.get("h"), "width": art.get("width"),
                      "cost_bp": art.get("cost_bp"),
                      "ahead_tol_sec": PJ.AHEAD_TOL_SEC},
            # Свод — как посчитан прогоном, породившим файл. Число
            # решений артефакта и число строк журнала печатаются
            # рядом: разойдясь, они говорят, что журнал ушёл вперёд
            # свода, и это состояние, а не поломка.
            "summary": art.get("summary") or {},
            "art_decisions": art.get("decisions"),
            "art_resolutions": art.get("resolutions"),
            "decisions": len(dec), "resolutions": len(res),
            "tranches": PJ.tranches(dec, res, now=now),
        })
        if at:
            d = next((x for x in dec if x.get("at") == at), None)
            if d is None:
                r["legs_reason"] = f"решения на {at} в журнале нет"
            else:
                s = next((x for x in res if x.get("at") == at), None)
                r["legs_at"] = at
                r["legs"] = PJ.leg_rows(d, s)
        cached[key] = r
        self._paper_cache = (now if now - cat >= 120 else cat, cached)
        return r

    def learning(self):
        """Умнеет ли модель и переходит ли это в деньги — по дням.

        Вопрос владельца. Отвечают три ряда, и путать их нельзя:

        1. НАВЫК — живой IC по сечению (`ic_history.jsonl`): ранговая
           связь прогноза с фактом по ВСЕМУ сечению, а не по шести
           выбранным именам. Пишется с первого дня по каждому часу и
           каждой цели; в ответ `/model` уезжают последние 90 строк,
           то есть одиннадцать часов, — поэтому свод считается здесь,
           по файлу целиком.
        2. ДЕНЬГИ — закрытые сделки того же дня, тем же `closed_rows`,
           что у лиги (книги-эхо исключены: те же решения).
        3. РАЗМЕР ЗНАНИЯ — сколько сечений видело обучение и что
           показала канарейка (`train_log.jsonl`, пишет цикл).

        Чего этот замер НЕ докажет, и это сказано на странице: часовое
        переобучение не может сделать модель заметно умнее — M2
        намерил, что сутки против месяца дают +0.000…+0.004 IC, а
        новый час есть 1/40000 выборки. Меняются в этом ряду две
        другие вещи: растёт сама выборка и меняются правила книг.
        Поэтому тренд IC читается как «не деградирует ли», а рост
        ищется в связи IC с деньгами, а не в номере обучения.
        """
        now = time.time()
        at, cached = getattr(self, "_learn_cache", (0.0, None))
        if cached is not None and now - at < 120:
            return cached
        s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
        mdir = os.path.join(s8, self.BOOK_DIRS["h4"])
        out = {"present": False, "generated_at": round(now, 1)}
        ic = self._jsonl(os.path.join(mdir, "ic_history.jsonl"))
        # День берётся из ЧАСА сечения, а не из времени записи: запись
        # идёт позже закрытия форварда, и на границе суток час уехал
        # бы в чужой день.
        days = {}
        for r in ic:
            if r.get("kind") != "section" or r.get("median_ic") is None:
                continue
            h = r.get("hour") or ""
            if len(h) < 10:
                continue
            d = days.setdefault(h[:10], {})
            d.setdefault((r.get("arm"), r.get("target")), []).append(
                float(r["median_ic"]))
        rows, errors, scanned, _ = self.closed_rows()
        rows = [r for r in rows if r["hz"] not in self.ECHO_BOOKS]
        money, ntr = {}, {}
        for r in rows:
            d = datetime.fromtimestamp(r["at"] or 0, timezone.utc)\
                .strftime("%Y-%m-%d")
            money[d] = money.get(d, 0.0) + (r["pnl"] or 0.0)
            ntr[d] = ntr.get(d, 0) + 1
        log = {}
        for r in self._jsonl(os.path.join(mdir, "train_log.jsonl")):
            h = r.get("hour") or ""
            if len(h) >= 10:
                log.setdefault(h[:10], []).append(r)
        series = []
        for d in sorted(set(days) | set(money)):
            per = days.get(d) or {}
            def med(target):
                v = sorted(x for k, vs in per.items() if k[1] == target
                           for x in vs)
                return (round(v[len(v) // 2], 4), len(v)) if v else (None, 0)
            ic4, n4 = med("fwd_4h")
            ic24, n24 = med("fwd_24h")
            lg = log.get(d) or []
            series.append({
                "day": d, "ic_4h": ic4, "sections_4h": n4,
                "ic_24h": ic24, "sections_24h": n24,
                "pnl": round(money.get(d, 0.0), 2),
                "trades": ntr.get(d, 0),
                # Размер знания на конец дня: последняя запись цикла.
                "trainings": len(lg),
                "train_seq": max((x.get("seq") or 0 for x in lg),
                                 default=None),
                "sections": (lg[-1].get("sections") if lg else None),
                "canary_ic": (lg[-1].get("canary_ic") if lg else None)})
        # Связи считаются ЗДЕСЬ: страница не считает статистику, иначе
        # у неё завелась бы вторая её реализация. Дни без IC или без
        # сделок в связь не входят — пропуск не есть ноль.
        pair = [(s["ic_4h"], s["pnl"]) for s in series
                if s["ic_4h"] is not None and s["trades"]]
        trend = [(i, s["ic_4h"]) for i, s in enumerate(series)
                 if s["ic_4h"] is not None]
        out.update({
            "present": bool(series), "days": series,
            "ic_vs_money": self._spearman([x for x, _ in pair],
                                          [y for _, y in pair]),
            "ic_vs_money_n": len(pair),
            "ic_vs_time": self._spearman([x for x, _ in trend],
                                         [y for _, y in trend]),
            "ic_vs_time_n": len(trend),
            "errors": errors})
        self._learn_cache = (now, out)
        return out

    def book_days(self, hz):
        """Дневная статистика ОДНОЙ книги — по просьбе владельца.

        «Кликаем на 4-hour book — открывается страница, где статистика
        по этой книге отдельно по каждому дню». Итог книги на дереве
        отвечает «сколько всего», а на вопрос «когда книга зарабатывала
        и когда сливала» не отвечает вовсе: сумма за две недели стоит
        на нескольких днях, и по ней нельзя отличить ровный ряд от
        одного разгона (это уже находил зонд `probe_turn`).

        Считается ТЕМ ЖЕ `closed_rows`, что лига, разбивка
        волатильности и страница обучения: деньги штампует касса, и
        второй обход однажды разошёлся бы с первым — на лиге это уже
        случилось (она не звала кассу и показывала ноль закрытых при
        сотнях сделок).

        Книги-эхо ЗДЕСЬ не исключаются, в отличие от лиги: там их
        решения складывались бы с решениями книги-источника и считались
        дважды, а тут книга смотрится сама на себя — её деньги
        настоящие и принадлежат ей. Что книга есть эхо, ответ говорит
        полем, чтобы страница могла это назвать.

        День — календарные сутки UTC по моменту, когда деньги стали
        известны (живой выход либо разбор), а не по времени открытия:
        то же правило, что у лиги. Сделка, открытая вчера и закрытая
        сегодня, принадлежит сегодняшнему дню — иначе кривая дня
        менялась бы задним числом.

        Открытые позиции в дневные числа НЕ входят и с закрытыми не
        складываются (правило `summary`): у открытой позиции исхода не
        существует, а «сколько она стоит сегодня» — отметка, которая к
        завтрашнему дню станет другой.
        """
        now = time.time()
        key = str(hz)
        # Кеш ключуется КНИГОЙ: без ключа переход между книгами отдавал
        # бы соседнюю под своим именем две минуты подряд — та же
        # молчаливая подмена, что резолв книги соглашением имени.
        cat, cached, ckey = getattr(self, "_bdays_cache",
                                    (0.0, None, None))
        if cached is not None and ckey == key and now - cat < 120:
            return cached
        # Книга ищется среди ЯДРА И КАНДИДАТОВ: у кандидата фабрики
        # деньги настоящие, и ответ «денег не держит вовсе» по карте
        # ядра был бы прямой ложью о живой книге.
        rec, _why = self.book_rec(key)
        out = {"hz": key, "generated_at": round(now, 1),
               "present": False, "days": [], "errors": [],
               "echo": bool(rec and rec["echo"]),
               "dir": rec["dir"] if rec else None}
        if not (rec and rec["traded"]):
            # Книги нет в карте торгуемых — это НЕ пустая книга.
            # Наблюдательная запись денег не держит вовсе, и молчаливый
            # пустой ряд читался бы как «книга ничего не наторговала».
            out["unknown"] = True
            self._bdays_cache = (now, out, key)
            return out
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        out["cap"] = TR.START_BALANCE
        # Кандидат обходится ПОИМЕННО: ядро его не содержит, и общий
        # обход вернул бы пустой ряд — «книга не торговала» о книге с
        # десятками сделок.
        rows, errors, scanned, opens = self.closed_rows(
            books=None if key in dict(self.BOOKS)
            else [(key, rec["dir"])])
        out["errors"] = errors
        rows = [r for r in rows if r["hz"] == key]
        out["present"] = bool(rows)
        # Открытое стоит ОТДЕЛЬНОЙ строкой ответа: оно есть состояние
        # на сейчас, а не величина какого-то дня.
        out["open"] = {o["arm"]: {"open": o["open"],
                                  "marked": o["marked"],
                                  "unreal_pnl": o["unreal_pnl"]}
                       for o in opens if o["hz"] == key}
        by = {}
        for r in rows:
            d = datetime.fromtimestamp(r["at"] or 0, timezone.utc)\
                .strftime("%Y-%m-%d")
            by.setdefault(d, {}).setdefault(r["arm"] or "gbm",
                                            []).append(r)
        days = []
        cum = {}
        for d in sorted(by):
            per = by[d]
            cell = {}
            for arm in ("gbm", "nn", "all"):
                got = (per.get(arm) if arm != "all"
                       else [x for v in per.values() for x in v])
                if not got:
                    continue
                c = self._day_cell(got)
                cum[arm] = round(cum.get(arm, 0.0) + c["pnl"], 2)
                c["cum"] = cum[arm]
                cell[arm] = c
            days.append({"day": d, "arms": cell})
        out["days"] = days
        out["totals"] = {}
        for arm in ("gbm", "nn", "all"):
            got = [r for r in rows
                   if arm == "all" or (r["arm"] or "gbm") == arm]
            if got:
                out["totals"][arm] = self._day_cell(got)
        self._bdays_cache = (now, out, key)
        return out

    @staticmethod
    def _day_cell(rows):
        """Числа одной клетки «день × рука». Одно определение на день,
        на итог и на обе руки: три реализации одного счёта разошлись бы
        так же, как разошлись два расчёта книги в обзоре и на странице
        сделок.

        Колонка «без лучшей сделки» стоит здесь по той же причине, по
        которой она стоит в лиге: день из десяти сделок с одним
        разгоном выглядит статистикой, хотя все деньги в нём
        принадлежат одному имени.
        """
        pnls = [r["pnl"] or 0.0 for r in rows]
        nets = [r["net_bp"] for r in rows if r.get("net_bp") is not None]
        top = max(rows, key=lambda r: r["pnl"] or 0.0)
        total = sum(pnls)
        exits = {}
        for r in rows:
            exits[r.get("reason") or "?"] = \
                exits.get(r.get("reason") or "?", 0) + 1
        return {
            "trades": len(rows),
            "wins": sum(1 for x in pnls if x > 0),
            "win": round(sum(1 for x in pnls if x > 0) / len(rows), 3),
            "pnl": round(total, 2),
            "net_med": (round(_median(nets), 1) if nets else None),
            "net_avg": (round(sum(nets) / len(nets), 1)
                        if nets else None),
            "top_sym": top["sym"], "top_pnl": round(top["pnl"] or 0.0, 2),
            "pnl_wo_top": round(total - (top["pnl"] or 0.0), 2),
            "worst_pnl": round(min(pnls), 2),
            "exits": exits}

    def market_vol(self):
        """Волатильность рынка по часам — из наших же почасовых сводок.

        Мера — МЕДИАННЫЙ РАЗМАХ середины стакана за час по всем именам,
        `(hi − lo) / close` в б.п. Почему размах, а не доходность часа:
        доходность требует закрытия ПРЕДЫДУЩЕГО часа, то есть ломается
        на дырах записи и на границе суток, и час, в котором рынок
        сходил вниз и вернулся, она считает спокойным — а пережить его
        позиции пришлось целиком. Размах полон в одной строке и такой
        час видит.

        Медиана, а не среднее: одна разогнанная монета не имеет права
        объявлять волатильным весь рынок.

        Считается по тем же сводкам, на которых учится модель, — то
        есть сравнение «режим рынка против результата» идёт по одному
        источнику, а не по чужому индексу.

        Готовые СУТКИ кешируются на диск и больше не перечитываются:
        имён около пятисот, файл на имя в сутки, и полный обход стоил
        бы десятки секунд на каждый запрос страницы. Текущие сутки
        пересчитываются всегда — они ещё дописываются.
        """
        now = time.time()
        at, cached = getattr(self, "_vol_cache", (0.0, None))
        if cached is not None and now - at < 300:
            return cached
        sd = os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                          "summary")
        cpath = os.path.join(HERE, "out", "market_vol.json")
        try:
            with open(cpath, encoding="utf-8") as f:
                done = json.load(f)
        except (OSError, ValueError):
            done = {}
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        try:
            syms = sorted(os.listdir(sd))
        except OSError:
            syms = []
        days = set()
        for s in syms:
            try:
                days.update(f[:-6] for f in os.listdir(os.path.join(sd, s))
                            if f.endswith(".jsonl"))
            except OSError:
                continue
        fresh = 0
        for day in sorted(days):
            if day in done and day != today:
                continue                       # сутки закрыты и посчитаны
            per_hour = {}
            for s in syms:
                path = os.path.join(sd, s, day + ".jsonl")
                try:
                    with open(path, encoding="utf-8") as f:
                        for line in f:
                            try:
                                r = json.loads(line)
                            except ValueError:
                                continue
                            c = r.get("mid_close")
                            hi = r.get("mid_high")
                            lo = r.get("mid_low")
                            h = r.get("hour")
                            if not h or not c or hi is None or lo is None:
                                continue
                            rng = (float(hi) - float(lo)) / float(c) * 1e4
                            if rng >= 0:
                                # Поздняя строка часа побеждает — тот же
                                # порядок, что при сборке матриц.
                                per_hour.setdefault(h, {})[s] = rng
                except OSError:
                    continue
            done[day] = {h: {"bp": round(_median(list(v.values())), 1),
                             "n": len(v)}
                         for h, v in per_hour.items()}
            fresh += 1
        if fresh:
            try:
                os.makedirs(os.path.dirname(cpath), exist_ok=True)
                with open(cpath + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(done, f)
                os.replace(cpath + ".tmp", cpath)
            except OSError:
                pass                       # кеш — ускорение, не истина
        hours = {}
        for day, hh in done.items():
            hours.update(hh)
        out = {"hours": hours, "days": len(done), "recomputed": fresh}
        self._vol_cache = (now, out)
        return out

    def vol_vs_models(self):
        """Влияет ли волатильность рынка на результат книг.

        Просьба владельца: видеть сразу, насколько результат зависит от
        режима рынка. Ответ — не картинка волатильности, а РАЗБИВКА
        наших же закрытых сделок по режиму часа, в котором они открыты.

        Час входа, а не час выхода: волатильность входа известна В
        МОМЕНТ РЕШЕНИЯ, и из неё может выйти правило («в тихие часы не
        торгуем»). Волатильность за время удержания результат объясняет
        лучше, но знать её заранее нельзя — правилом она не станет
        никогда. Обе разные, и путать их значит выдать невозможное за
        вывод.

        Границы корзин — терцили распределения САМОЙ волатильности, а
        не подобранные по результату: пороги, выбранные после того, как
        видны исходы, есть перебор без поправки. Считаются по всем
        записанным часам, то есть «тихий» значит тихий по нашей
        собственной истории.

        Отдельной колонкой идёт число РАЗНЫХ ДАТ в корзине: пятьдесят
        сделок с двух дней — это два дня, а не пятьдесят наблюдений, и
        без этого числа корзина читается как статистика.
        """
        now = time.time()
        at, cached = getattr(self, "_volmod_cache", (0.0, None))
        if cached is not None and now - at < 120:
            return cached
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        sd = os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                          "summary")
        vol = self.market_vol()
        hours = vol["hours"]
        rows, errors, scanned, _ = self.closed_rows()
        # Книги-эхо не входят: те же решения дважды исказили бы
        # разбивку по режимам, как исказили бы лигу.
        rows = [r for r in rows if r["hz"] not in self.ECHO_BOOKS]
        vals = sorted(v["bp"] for v in hours.values())
        cuts = []
        if len(vals) >= 3:
            cuts = [vals[len(vals) // 3], vals[2 * len(vals) // 3]]
        names = ("quiet", "normal", "loud")

        def bucket(bp):
            if not cuts:
                return None
            return names[0] if bp < cuts[0] else (
                names[1] if bp < cuts[1] else names[2])

        # Сделка без часа сводки в корзину НЕ попадает: приписать её
        # «обычному» рынку значило бы придумать наблюдение. Сколько их
        # выпало — числом.
        kept, lost = [], 0
        for r in rows:
            h = hours.get(r.get("hour") or "")
            if not h:
                lost += 1
                continue
            r = dict(r, vol_bp=h["bp"], vol_n=h["n"],
                     bucket=bucket(h["bp"]))
            kept.append(r)

        def agg(sub):
            if not sub:
                return None
            pnl = sum(x["pnl"] or 0.0 for x in sub)
            nets = [x["net_bp"] for x in sub if x["net_bp"] is not None]
            vb = sorted(x["vol_bp"] for x in sub)
            return {"n": len(sub),
                    "days": len({(x["hour"] or "")[:10] for x in sub}),
                    "win": round(sum(1 for x in sub
                                     if (x["pnl"] or 0) > 0) / len(sub), 3),
                    "pnl": round(pnl, 2),
                    "net_bp_avg": round(sum(nets) / len(nets), 1)
                    if nets else None,
                    "vol_med_bp": round(_median(vb), 1)}

        def split(sub):
            return {"all": agg(sub),
                    **{b: agg([x for x in sub if x["bucket"] == b])
                       for b in names}}

        # Отбирает ли модель ВОЛАТИЛЬНЫЕ имена — вопрос владельца о том,
        # не стоит ли учитывать волатильность в обучении. Отвечать на
        # него мнением нельзя, а число берётся дёшево: у каждой сделки
        # есть свой час, и в нём известен и размах САМОЙ монеты, и
        # медиана рынка.
        #
        # Почему это важно именно здесь: признаки модели нормированы
        # собственной волатильностью монеты (`ret_*` делятся на σ), а
        # ЦЕЛИ — нет, они в сырых базисных пунктах. Значит, ранжируя
        # сечение по предсказанному ходу, модель механически ставит
        # выше тех, кто просто больше ходит. Отношение заметно выше
        # единицы и есть подпись этого перекоса; около единицы —
        # перекоса нет, и вопрос закрыт замером, а не рассуждением.
        pairs = {(r["sym"], r["hour"]) for r in kept
                 if r.get("sym") and r.get("hour")}
        #
        # По книгам ОТДЕЛЬНО, и это не украшение: перекос лечится
        # порядком сечения, а порядок теперь разный. Книги 4 ч, 1 ч и
        # ситуационная упорядочены в единицах σ, книга 24 ч намеренно
        # оставлена на сыром порядке — то есть страница показывает
        # обе стороны замера рядом, а не смесь, в которой не видно,
        # что чему принадлежит.
        rel, own_bp, by_book = [], [], {}
        if pairs:
            px = TR.hour_rows(sd, pairs)
            for r in kept:
                row = px.get((r.get("sym"), r.get("hour")))
                med = (hours.get(r.get("hour") or "") or {}).get("bp")
                if not row or not row.get("c") or not med:
                    continue
                o = (row["hi"] - row["lo"]) / row["c"] * 1e4
                own_bp.append(o)
                rel.append(o / med)
                b = by_book.setdefault(r["hz"], {"rel": [], "own": []})
                b["rel"].append(o / med)
                b["own"].append(o)

        def _pick(rr, oo):
            return {"n": len(rr), "rel_med": round(_median(rr), 2),
                    "above": round(sum(1 for x in rr if x > 1.0)
                                   / len(rr), 3),
                    "own_med_bp": round(_median(oo), 1)}

        pick = None
        if rel:
            pick = _pick(rel, own_bp)
            pick["books"] = {hz: _pick(v["rel"], v["own"])
                             for hz, v in sorted(by_book.items())
                             if v["rel"]}

        books = {}
        for hz, _name in self.BOOKS:
            sub = [x for x in kept if x["hz"] == hz]
            if not sub:
                continue
            books[hz] = {"all": split(sub),
                         **{a: split([x for x in sub if x["arm"] == a])
                            for a in ("gbm", "nn")}}
        series = sorted(({"hour": h, "bp": v["bp"], "n": v["n"]}
                         for h, v in hours.items()),
                        key=lambda x: x["hour"])
        out = {"present": bool(kept), "n": len(kept), "no_hour": lost,
               "pick_vol": pick,
               "cuts_bp": cuts, "buckets": names,
               "hours_measured": len(hours), "days": vol["days"],
               "books": books, "series": series[-720:],
               "errors": errors, "scanned": scanned,
               "generated_at": round(now, 1)}
        self._volmod_cache = (now, out)
        return out

    def model_glossary(self):
        """Справочник: какие ситуации модель вообще способна читать.

        Просьба владельца — страница со всеми «стратегиями» модели и
        объяснением каждой простыми словами. Честный ответ записан в
        `families.py` и повторён страницей: дискретных стратегий у
        модели нет, она одна на все ситуации. Что есть — семейства
        признаков, то есть словарь, на котором она думает; имя
        ситуации у сделки получается разложением вкладов в ОДИН
        прогноз.

        Список признаков берётся из ЖИВОГО манифеста обучения, а не из
        исходников: справочник обязан описывать ту модель, которая
        сейчас торгует. Пороги новизны пишутся по каждому признаку,
        поэтому их ключи и есть полный список имён, на которых модель
        училась, — тот же, что берёт тест на полноту карты.

        Вес семейства — сумма важностей его признаков по цели `fwd_4h`
        (главный горизонт). Манифест хранит топ-10 на цель, поэтому
        сумма долей меньше единицы: `weight_covers` говорит, какую
        часть важности мы вообще видим. Печатать долю от неполной
        суммы как «доля семейства» значило бы выдать десять признаков
        за все пятьдесят.
        """
        now = time.time()
        at, cached = getattr(self, "_gloss_cache", (0.0, None))
        if cached is not None and now - at < 300:
            return cached
        s8d = os.path.join(os.path.dirname(HERE), "s8_loop")
        sys.path.insert(0, s8d)
        # Только карта семейств и тексты — без numpy: `bookfeat` тянет
        # математику M1, а справочнику нужны строки.
        import families as FM
        mdir = os.path.join(s8d, "out", "model")
        man, err = {}, None
        try:
            with open(os.path.join(mdir, "manifest.json"),
                      encoding="utf-8") as f:
                man = json.load(f)
        except OSError:
            err = "манифест обучения не найден — модель ещё не училась"
        except ValueError as e:
            err = f"манифест обучения не читается: {e}"
        feats = sorted((man.get("novelty_bounds") or {}))
        imp = ((man.get("importance") or {}).get("gbm")
               or {}).get("fwd_4h") or {}
        seen = 0.0
        by_fam = {}
        for n in feats:
            fam = FM.family(n)
            g = by_fam.setdefault(fam, {"feats": [], "weight": 0.0})
            w = float(imp.get(n) or 0.0)
            seen += w
            g["weight"] += w
            g["feats"].append({"name": n, "weight": round(w, 4)})
        # Сделки, где семейство оказалось главным: справочник должен
        # отвечать не только «что модель умеет читать», но и «чем она
        # на деле торговала». Берётся год лиги — она уже посчитана и
        # закеширована, второй проход по книгам был бы вторым счётом.
        traded = {}
        try:
            lg = self.model_league()
            for g in (((lg.get("periods") or {}).get("365d") or {})
                      .get("groups") or {}).get("setup") or []:
                traded[g["key"]] = {"n": g["n"], "pnl": g["pnl"],
                                    "win": g["win"]}
        except Exception as e:                            # noqa: BLE001
            err = (err or "") + f" лига недоступна: {type(e).__name__}"
        rows = []
        for key, txt in FM.GLOSSARY:
            g = by_fam.get(key) or {"feats": [], "weight": 0.0}
            if key == "other" and not g["feats"]:
                # «Прочее» пусто — так и должно быть; печатать пустую
                # карточку дефекта незачем.
                continue
            # Оба языка едут в ответе разом: переключатель на странице
            # не должен ходить на сервер за переводом — иначе смена
            # языка на потерянной связи давала бы пустую страницу.
            rows.append({
                "key": key,
                **{f: txt[f] for f in ("title", "plain", "reads")},
                **{f + "_ru": txt[f + "_ru"]
                   for f in ("title", "plain", "reads")},
                "caveat": txt.get("caveat"),
                "caveat_ru": txt.get("caveat_ru"),
                "features": sorted(g["feats"],
                                   key=lambda f: (-f["weight"],
                                                  f["name"])),
                "n_features": len(g["feats"]),
                "weight": round(g["weight"], 4),
                "traded": traded.get(key)})
        out = {"present": bool(feats), "error": err,
               "n_features": len(feats),
               "train_seq": man.get("train_seq"),
               "trained_at": man.get("trained_at"),
               "trained_upto": man.get("trained_upto"),
               "symbols": man.get("symbols"), "hours": man.get("hours"),
               # Какую часть важности накрывает топ-10 манифеста: без
               # этого числа веса семейств читались бы как полные доли.
               "weight_covers": round(seen, 4),
               "weight_target": "fwd_4h", "weight_arm": "gbm",
               "families": rows, "generated_at": round(now, 1)}
        self._gloss_cache = (now, out)
        return out

    def model_tournament(self):
        """Полный лист турнира политик: все 72 ветки и селектор.

        Просьба владельца — весь лист веток и подветок отдельной
        страницей. Ответ читает АРТЕФАКТ последнего прогона (его
        обновляет ночной сторож), а не пересчитывает: страница обязана
        описывать тот прогон, который породил файл (урок R1).
        Артефакта нет — честное «ждёт прогона», а не пустая таблица.

        Порог измеримости ячейки и ключ текущих правил берутся у
        САМОГО турнира: вторая запись константы разошлась бы с той,
        по которой считался артефакт.
        """
        now = time.time()
        at, cached = getattr(self, "_tour_cache", (0.0, None))
        if cached is not None and now - at < 60:
            return cached
        # КОД турнира — от настоящего файла, а не от `HERE`: тесты
        # подменяют `HERE`, чтобы подложить артефакты, и код по тому
        # же пути не нашёлся бы. Данные ниже — нарочно по `HERE`.
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "s10_policy"))
        import tournament as TM
        tp = os.path.join(os.path.dirname(HERE), "s10_policy", "out",
                          "V1-tournament.json")
        # Ночной прогон приходит раз в сутки; порог с запасом на одно
        # пропущенное окно. Молчащий сторож обязан быть ВИДЕН: старая
        # таблица со свежим видом — это разовый прогон, притворяющийся
        # наблюдением, тот же класс, что тишина вместо отказа.
        out = {"present": False, "min_cell": TM.MIN_WIN_TRADES,
               "current": TM.CURRENT, "stale_after_sec": self.TOUR_STALE,
               "generated_at": round(now, 1)}
        try:
            with open(tp, encoding="utf-8") as f:
                tj = json.load(f)
            cells = tj.get("cells") or []
            ok = [c for c in cells
                  if (c.get("n") or 0) >= TM.MIN_WIN_TRADES]
            # Ячейка без ожидания в медиану не идёт и НЕ роняет ответ:
            # артефакт прежнего образца (или дописанный наполовину)
            # обрушивал бы обе страницы разом — и лист, и дерево,
            # которое читает тот же метод. Отсутствие величины есть
            # состояние артефакта, а не повод потерять весь показ.
            exps = sorted(c["exp_bp"] for c in ok
                          if c.get("exp_bp") is not None)
            med = exps[len(exps) // 2] if exps else None
            age = now - os.path.getmtime(tp)
            # Несёт ли прогон просадку кривой. Колонка прочерков
            # без объяснения неотличима от сломанного счёта —
            # владелец увидел ровно это и спросил. Признак считается
            # по ячейкам СО СДЕЛКАМИ: у пустой прочерк законен всегда.
            with_n = [c for c in cells if c.get("n")]
            out["has_dd"] = bool(with_n) and any(
                c.get("dd_bp") is not None for c in with_n)
            out.update(present=True, legs=tj.get("legs"),
                       cells=cells, wf=tj.get("wf"),
                       verdict=tj.get("verdict") or {},
                       measured=len(ok), med_exp_bp=med,
                       run_age_sec=round(age, 1),
                       stale=age > self.TOUR_STALE)
        except OSError:
            out["status"] = "ждёт первого прогона на VPS"
        except ValueError as e:
            out["status"] = f"артефакт не читается: {e}"
        self._tour_cache = (now, out)
        return out

    # Порог свежести суточного прогона фабрики: запас на одно
    # пропущенное окно, как у турнира. Молчащая запускалка обязана
    # быть ВИДНА — иначе остановившаяся система выглядит спокойным
    # днём, и это самый дешёвый отказ из всех.
    AGENTS_STALE = 36 * 3600

    @staticmethod
    def _run_row(r, now):
        """Строка прогона для показа: заметка урезается, не выбрасывается."""
        if not r:
            return None
        note = r.get("note") or ""
        out = {"status": r.get("status"), "at": r.get("at"),
               "age_sec": round(now - (r.get("at") or now), 1),
               "dry": bool(r.get("dry")),
               "took_sec": round(max(0.0, (r.get("ended") or 0)
                                     - (r.get("started") or 0)), 1)}
        if note:
            out["note"] = note[:400]
            if len(note) > 400:
                out["note_cut"] = True
        return out

    @staticmethod
    def _produced(root, rel, now):
        """Файл, который роль обязана была оставить.

        Отсутствие файла — состояние, а не ноль: «роль отработала» без
        её продукта есть утверждение, которое нечем проверить.
        """
        p = os.path.join(root, rel)
        out = {"path": rel, "exists": os.path.exists(p)}
        if not out["exists"]:
            return out
        try:
            st = os.stat(p)
            out["bytes"] = st.st_size
            out["age_sec"] = round(now - st.st_mtime, 1)
            with open(p, encoding="utf-8", errors="replace") as f:
                head = f.read(1400)
            out["head"] = head
            out["head_cut"] = st.st_size > len(head.encode("utf-8"))
        except OSError as e:
            out["error"] = str(e)
        return out

    def agents_state(self):
        """Автономная система: конвейер, границы и что уже построено.

        Тексты — из реестра `research/factory/agents.py`, того самого,
        из которого запускалка позже соберёт промпты ролей: страница
        обязана описывать ту систему, которая работает, а не соседнюю.

        Построенность шага решается СУЩЕСТВОВАНИЕМ файла из поля
        `proof`, а не записью в реестре. Иначе страница рассказывала
        бы о системе, которой нет, и выглядела бы исправной — тот же
        класс, что молчаливый ноль на месте пропуска. Пути проверяются
        от настоящего корня репозитория, а не от `HERE`: `HERE` тесты
        подменяют, чтобы подложить артефакты.

        Числа пула — из АРТЕФАКТА суточного прогона (урок R1:
        страница описывает тот прогон, который породил файл), а не
        пересчётом.
        """
        now = time.time()
        at, cached = getattr(self, "_agents_cache", (0.0, None))
        if cached is not None and now - at < 60:
            return cached
        research = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        root = os.path.dirname(research)
        sys.path.insert(0, os.path.join(research, "factory"))
        import agents as AG
        import runlog as RL
        # Прогоны ролей: у РОЛИ существования промпта мало. Промпт
        # есть рецепт, а не работа, и объявить роль построенной по
        # файлу значило бы сказать «работает» про то, что ни разу не
        # звали. Сухой прогон в счёт не идёт — модель в нём не
        # вызывается вовсе.
        runs, broken = RL.read(os.path.join(
            os.path.dirname(HERE), "factory", "out", RL.RUNS))
        last = RL.last_by_role(runs)
        ran = RL.ok_runs(runs)
        # Состояние роли — ДВА разных вопроса: идёт ли прогон сейчас и
        # чем кончился прошлый. Склеив их, страница показывала бы
        # старый отказ во время исправного прогона.
        rstate = RL.state_of(runs)
        steps = []
        for st in AG.pipeline():
            proof = st.get("proof") or ""
            has = bool(proof and os.path.exists(
                os.path.join(root, proof)))
            role = st["kind"] == "role"
            lr = last.get(st["key"])
            rs = rstate.get(st["key"]) or {}
            steps.append(dict(
                st, built=(has and (not role or st["key"] in ran)),
                prompt=has,
                last_run=({"status": lr.get("status"),
                           "at": lr.get("at"),
                           "age_sec": round(now - (lr.get("at") or now), 1),
                           "note": lr.get("note")} if lr else None),
                running=self._run_row(rs.get("running"), now),
                broken_run=self._run_row(rs.get("broken"), now),
                runs=[self._run_row(r, now)
                      for r in RL.history(runs, st["key"], 20)],
                produced=[self._produced(root, rel, now)
                          for rel in (st.get("produces") or [])]))
        built = [s for s in steps if s["built"]]
        # Следующий шаг — ПЕРВЫЙ непостроенный по порядку конвейера,
        # а не назначенный словом: порядок постройки обязан следовать
        # из состояния, иначе он стареет молча.
        nxt = next((s["key"] for s in steps if not s["built"]), None)
        # Расписание считается по ФАКТУ, а не по намерению: сторож
        # зовёт круг (`cycle.py`), а тот будит роли запускалкой.
        # Признак «в стороже есть agents_run.sh» был верен, пока
        # запускалку звали напрямую, и молча устарел бы с появлением
        # круга — расписание работало бы, а страница говорила бы, что
        # его нет.
        try:
            with open(os.path.join(root, "tools", "watchdog_book.sh"),
                      encoding="utf-8", errors="ignore") as f:
                wd = f.read()
        except OSError:
            wd = ""
        sched = ("agents_run.sh" in wd) or ("factory/cycle.py" in wd)
        # Тишина становится тревогой ровно с появлением расписания, и
        # только у шагов КРУГА: остальные зовутся руками, и их
        # молчание есть состояние. Состав круга берётся у самого
        # круга — второй список разошёлся бы с ним молча.
        try:
            import cycle as CY
            circle = [k for k, _kind, _argv, _proof in CY.CIRCLE]
        except Exception:                                 # noqa: BLE001
            circle = []
        okrun = {}
        for r in runs:
            if r.get("status") == "ok" and not r.get("dry"):
                k = r.get("role")
                if k and (r.get("at") or 0) > okrun.get(k, 0):
                    okrun[k] = r.get("at") or 0
        stale = []
        for st in steps:
            k = st["key"]
            st["in_circle"] = k in circle
            st["last_ok_age_sec"] = (round(now - okrun[k], 1)
                                     if k in okrun else None)
            # Ждёт снятия лимита аккаунта — это СОСТОЯНИЕ, и тревога
            # тишины по нему не кричит: роль молчит по делу и
            # поднимется сама по истечении срока. Кричащая на законное
            # ожидание тревога перестаёт быть сигналом.
            w = RL.limit_wait(runs, k, now)
            st["limit_wait_sec"] = round(w, 1) if w > 0 else None
            st["stale"] = bool(
                sched and st["in_circle"] and not w
                and (k not in okrun
                     or now - okrun[k] > self.AGENTS_STALE))
            if st["stale"]:
                stale.append(k)
        # Сводка владельцу — то, ради чего вся система и заводилась,
        # поэтому она стоит НА СТРАНИЦЕ, а не внутри карточки шага:
        # ежедневный отчёт, который надо искать, читают раз.
        sm = os.path.join(os.path.dirname(HERE), "factory", "out",
                          "summary.md")
        summary = None
        if os.path.exists(sm):
            try:
                with open(sm, encoding="utf-8", errors="replace") as f:
                    txt = f.read(9000)
                summary = {"text": txt,
                           "cut": os.path.getsize(sm) > len(
                               txt.encode("utf-8")),
                           "age_sec": round(now - os.path.getmtime(sm), 1)}
            except OSError as e:
                summary = {"error": str(e)}
        out = {"steps": steps, "built_n": len(built), "summary": summary,
               "runs_n": len(runs), "runs_broken": broken,
               "scheduled": bool(sched), "stale_keys": stale,
               "circle": circle,
               "total_n": len(steps),
               "roles_n": sum(1 for s in steps if s["kind"] == "role"),
               "next_key": nxt,
               "boundaries": AG.BOUNDARIES, "risks": AG.RISKS,
               "stale_after_sec": self.AGENTS_STALE,
               "generated_at": round(now, 1), "pool": None}
        fp = os.path.join(os.path.dirname(HERE), "factory", "out",
                          "factory-day-1m.json")
        try:
            with open(fp, encoding="utf-8") as f:
                fj = json.load(f)
            age = now - os.path.getmtime(fp)
            sm = fj.get("summary") or {}
            sp = sm.get("spent") or {}
            # Артефакт ПРЕЖНЕГО образца сводки не несёт. Ноль на её
            # месте читался бы как «пул пуст», поэтому величины
            # остаются пустыми, а причина называется словами.
            out["pool"] = {
                "total": sp.get("total"), "alive": sp.get("active"),
                "retired": sp.get("retired"),
                "selected": sp.get("selected_active"),
                "control": sp.get("control_active"),
                "eff_n": sm.get("eff_n"), "mean_r": sm.get("mean_r"),
                "days": sm.get("days"), "verdict": sm.get("verdict"),
                "at": (fj.get("meta") or {}).get("at"),
                "legs": (fj.get("meta") or {}).get("legs"),
                "has_summary": bool(sm),
                "run_age_sec": round(age, 1),
                "stale": age > self.AGENTS_STALE}
            if not sm:
                out["pool_status"] = ("прогон сделан до появления "
                                      "сводки числами — величины "
                                      "заполнит ближайший суточный")
        except OSError:
            out["pool_status"] = "суточного прогона ещё не было"
        except ValueError as e:
            out["pool_status"] = f"артефакт не читается: {e}"
        self._agents_cache = (now, out)
        return out

    # Корень дерева построенного — ЦЕЛЬ плюс ГЕОМЕТРИЯ: что книга
    # предсказывает и как ведёт сделку. Остальные оси (сечение, пол
    # входа, ширина, отношение, размер, согласие рук) суть дозировка
    # одной и той же механики, и разносить их по корням значило бы
    # называть механикой настройку.
    BUILT_ROOT = ("target", "geom")

    def _cand_live(self, cid):
        """Живая книга кандидата: закрытые сделки и деньги по рукам.

        `None` — каталога нет вовсе (книга ещё не заведена циклом), и
        это НЕ ноль: «книга не торговала» и «книги нет» лечатся
        разным. Открытые деньги здесь не считаются — их знает
        переоценка, и складывать закрытое с открытым нельзя.
        """
        import json as _json
        d = os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                         "model_c_" + str(cid))
        if not os.path.isdir(d):
            return None
        out = {"arms": {}, "closed": 0, "pnl": 0.0, "start": None}
        for arm in ("gbm", "nn"):
            p = os.path.join(d, f"account_{arm}.json")
            try:
                with open(p, encoding="utf-8") as f:
                    a = _json.load(f) or {}
            except (OSError, ValueError):
                continue
            hist = a.get("history") or []
            start = a.get("start")
            bal = a.get("balance")
            pnl = (None if bal is None or start is None
                   else round(bal - start, 2))
            out["arms"][arm] = {"closed": len(hist), "pnl": pnl,
                                "balance": bal, "start": start}
            out["closed"] += len(hist)
            if pnl is not None:
                out["pnl"] = round(out["pnl"] + pnl, 2)
            if start is not None:
                out["start"] = (start if out["start"] is None
                                else out["start"] + start)
        if not out["arms"]:
            # Каталог есть, счетов нет: книга заведена этим часом и
            # ещё не считалась. Состояние, а не пустота.
            return {"arms": {}, "closed": 0, "pnl": None,
                    "start": None, "fresh": True}
        return out

    def factory_built(self):
        """Что автономная система объявила: механика в корне, книги ветками.

        Просьба владельца: страница всего, что система построила и что
        прошло проверки, — с описанием простыми словами и сделками
        бумажной книги.

        Читается ДВА источника, и это не две дороги к одному ответу:
        РЕЕСТР (`ledger.jsonl`) — полный список кандидатов, включая
        вылетевших, то есть знаменатель испытаний; АРТЕФАКТ суточного
        прогона — числа, и только те, которые породил прогон (урок R1).
        Кандидат, объявленный после последнего прогона, стоит в дереве
        с прочерками и названной причиной: «чисел ещё нет» и «ноль»
        снаружи неотличимы, а первое здесь — правда.

        Деньги делятся на ФОРВАРД и РЕПЛЕЙ ПО ПРОШЛОМУ одной функцией
        `pool.split_forward` — той же, которой их делит отчёт. Складывать
        их нельзя: до объявления это пересчёт по прошлому, которое
        ассистент видел, когда предлагал.
        """
        now = time.time()
        at, cached = getattr(self, "_built_cache", (0.0, None))
        if cached is not None and now - at < 60:
            return cached
        # КОД берётся от настоящего файла, ДАННЫЕ — от `HERE`: тесты
        # подменяют `HERE`, чтобы подложить свой реестр и артефакт, и
        # метод, читающий и то и другое от `__file__`, исполнял бы на
        # проверке живые данные сервера — то есть проверял бы не себя.
        research = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        fdir = os.path.join(os.path.dirname(HERE), "factory", "out")
        sys.path.insert(0, os.path.join(research, "factory"))
        import ledger as LG
        import pool as PL
        import space as SP
        rows, broken = LG.read(fdir)
        state = LG.state(rows)
        art, art_err = {}, None
        fp = os.path.join(fdir, "factory-day-1m.json")
        try:
            with open(fp, encoding="utf-8") as f:
                art = json.load(f)
            run_age = now - os.path.getmtime(fp)
        except OSError:
            art_err, run_age = "суточного прогона ещё не было", None
        except ValueError as e:
            art_err, run_age = f"артефакт не читается: {e}", None
        nums = art.get("candidates") or {}
        roots, tot = {}, {"declared": 0, "alive": 0, "retired": 0,
                          "selected": 0, "control": 0, "no_numbers": 0}
        for cid, rec in sorted(state.items()):
            rule = rec.get("rule") or {}
            if SP.validate(rule):
                continue
            tot["declared"] += 1
            alive = rec.get("retired_at") is None
            tot["alive" if alive else "retired"] += 1
            if rec.get("lane") in ("selected", "control"):
                tot[rec["lane"]] += 1
            c = nums.get(cid)
            b = {"key": cid, "lane": rec.get("lane"), "alive": alive,
                 "rule": rule, "plain": SP.describe(rule),
                 "declared_at": rec.get("declared_at"),
                 "retired_at": rec.get("retired_at"),
                 "why": rec.get("why"), "note": rec.get("note"),
                 "trades": None, "fwd": None, "pre": None,
                 "fwd_days": None, "pre_days": None, "last": [],
                 "daily": None, "no_numbers": None, "no_tail": None}
            # ЖИВАЯ книга кандидата — своя касса, а не реплей. Читается
            # счёт, который пишет цикл (`account_<рука>.json`), то есть
            # ровно те деньги, что видят страницы книг: второй расчёт
            # того же числа однажды разошёлся бы с первым.
            b["live"] = self._cand_live(cid)
            if c:
                # Ключ дня в JSON стал строкой — вернуть обратно
                # обязан читатель, иначе ряды не пересекутся ни одним
                # днём (то же правило, что у потолка).
                daily = {int(k): v for k, v in (c.get("daily")
                                                or {}).items()}
                fwd, pre = PL.split_forward(daily, rec.get("declared_at"))
                b.update(trades=c.get("trades"),
                         fwd=round(sum(fwd.values()), 1),
                         pre=round(sum(pre.values()), 1),
                         fwd_days=len(fwd), pre_days=len(pre),
                         daily=sorted((d, round(v, 2))
                                      for d, v in daily.items()),
                         last=list(reversed(c.get("last") or [])))
                if c.get("trades") and not b["last"]:
                    # Пустой хвост при сделках — не «сделок нет», а
                    # прогон прежнего образца. Молчаливая пустота
                    # читалась бы как «книга не торговала».
                    b["no_tail"] = ("прогон сделан до появления хвоста "
                                    "сделок — заполнит ближайший "
                                    "суточный")
            else:
                tot["no_numbers"] += 1
                b["no_numbers"] = ("объявлен после последнего суточного "
                                   "прогона — первые числа придут "
                                   "ближайшим" if alive else
                                   "вылетел: живым кандидатам числа "
                                   "считает прогон, вылетевшим — нет")
            rk = "|".join(str(rule[a]) for a in self.BUILT_ROOT)
            r = roots.setdefault(rk, {"key": rk, "branches": [],
                                      "target": rule["target"],
                                      "geom": rule["geom"]})
            r["branches"].append(b)
        out = []
        for r in roots.values():
            hz = "4 ч" if r["target"] == "fwd_4h" else "24 ч"
            gm = {"timer": "выход по времени",
                  "stop_take": "стоп и тейк по обещаниям пути",
                  "levels": "только уровни, без отмены по времени"}
            r["title"] = f"прогноз {hz} · {gm[r['geom']]}"
            r["alive"] = sum(1 for b in r["branches"] if b["alive"])
            r["n"] = len(r["branches"])
            r["branches"].sort(key=lambda b: (not b["alive"], b["key"]))
            out.append(r)
        out.sort(key=lambda r: (-r["n"], r["key"]))
        sm = art.get("summary") or {}
        res = {"roots": out, "totals": tot, "broken": broken,
               "verdict": sm.get("verdict"), "eff_n": sm.get("eff_n"),
               "record_days": sm.get("record_days"),
               "null_median": sm.get("null_median"),
               "space_total": SP.TOTAL,
               "space_available": SP.available_total(),
               "window_d": PL.WINDOW_D, "cap": PL.CAP,
               "run_at": (art.get("meta") or {}).get("at"),
               "run_age_sec": None if run_age is None else round(run_age, 1),
               "run_stale": (run_age is not None
                             and run_age > self.AGENTS_STALE),
               "art_error": art_err,
               "generated_at": round(now, 1)}
        self._built_cache = (now, res)
        return res

    def model_tree(self):
        """Дерево моделей: две руки и их книги, с логикой каждой ветки.

        Просьба владельца: отдельная страница с разветвлением моделей
        и описанием простыми словами, какую логику проверяет каждая
        под-модель, ветки от основных ML и AI. Честная рамка стоит в
        текстах: под-модель — не отдельная обученная модель, а книга
        на тех же весах, отличающаяся ровно одним объявленным
        правилом, — иначе разницу результатов нельзя было бы приписать
        правилу.

        Состав веток выводится из `BOOK_DIRS` (единственная карта книг
        на сервере), тексты — из `BOOK_TREE`; ветка без текста
        помечается полем `no_text`, а не выпадает: пустота на странице
        была бы неотличима от «книги нет». Совпадение ключей закреплено
        тестом. Правила ветки читаются из ЖИВОГО манифеста книги —
        страница обязана описывать то, что торгует, а не исходники.
        Деньги — те же `closed_rows`, что у лиги и волатильности:
        второй обход однажды разошёлся бы с первым.
        """
        now = time.time()
        at, cached = getattr(self, "_tree_cache", (0.0, None))
        if cached is not None and now - at < 60:
            return cached
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        rows, errors, scanned, opens = self.closed_rows()
        stats = {}
        for r in rows:
            s = stats.setdefault((r["hz"], r["arm"]),
                                 {"closed": 0, "wins": 0, "pnl": 0.0})
            s["closed"] += 1
            s["wins"] += 1 if (r["pnl"] or 0) > 0 else 0
            s["pnl"] += r["pnl"] or 0.0
        # Открытые деньги — ОТДЕЛЬНЫМИ полями и никогда не в одной
        # цифре с закрытыми: у закрытой сделки исход известен, у
        # открытой это отметка (правило `summary`). Ветка может нести
        # только открытые — у живой книги 24 ч так и было: 0 закрытых
        # при 108 открытых, и без этих полей о её деньгах не
        # говорилось ничего вовсе.
        for o in opens:
            s = stats.setdefault((o["hz"], o["arm"]), {})
            s["open"] = o["open"]
            s["marked"] = o["marked"]
            s["open_pnl"] = o["unreal_pnl"]
        s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
        books = []
        for key, name in self.BOOK_DIRS.items():
            meta = self.BOOK_TREE.get(key)
            row = dict(meta) if meta else {
                "title": key, "title_ru": key,
                "plain": "", "plain_ru": "", "no_text": True}
            row.update(key=key, dir=name,
                       echo=key in self.ECHO_BOOKS,
                       # Согласная книга живёт под третьим корнем и
                       # только там: руки тождественны по построению,
                       # под ML и AI она стояла бы дважды.
                       agreed=key in self.AGREE_BOOKS,
                       # Дневная статистика есть только у торгуемых:
                       # наблюдательная запись денег не держит вовсе,
                       # и ссылка на неё вела бы в пустую страницу,
                       # неотличимую от сломанной.
                       traded=any(key == h for h, _ in self.BOOKS))
            man = {}
            try:
                with open(os.path.join(s8, name, "manifest.json"),
                          encoding="utf-8") as f:
                    man = json.load(f)
            except OSError:
                pass
            except ValueError as e:
                errors.append(f"{name}: манифест не читается: {e}")
            row["present"] = bool(man)
            # Правила ветки — короткой строкой из манифеста. Числа
            # языка не имеют, поэтому строка одна на оба языка.
            facts = []
            if man.get("situational"):
                if man.get("min_edge_bp") is not None:
                    facts.append(f"gate {man['min_edge_bp']:g} bp")
                if man.get("min_rr"):
                    facts.append(f"RR ≥ {man['min_rr']:g}")
                if man.get("max_rr") is not None:
                    facts.append(f"RR ≤ {man['max_rr']:g}")
                if man.get("min_disc_bp") is not None:
                    facts.append(f"disc {man['min_disc_bp']:g} bp")
                if man.get("stop_tau") is not None:
                    facts.append(f"stop τ {man['stop_tau']:g}")
                if man.get("max_age_h"):
                    facts.append(f"age ≤ {man['max_age_h']} h")
            elif man.get("no_timer"):
                # Корзина без отдельных выходов: «hold N h» была бы
                # ложью — таймера у ног нет, срок задаёт возраст
                # КОРЗИНЫ. Пороги — из манифеста, как у ситуационных.
                if man.get("basket_take_share") is not None:
                    facts.append(
                        f"take +{man['basket_take_share'] * 100:g} %")
                if man.get("basket_floor_share") is not None:
                    facts.append(
                        f"floor −{man['basket_floor_share'] * 100:g} %")
                if man.get("basket_age_h"):
                    facts.append(f"basket age ≤ {man['basket_age_h']} h")
                facts.append("no per-leg exits")
            elif man:
                # Манифест главной книги старше турнира темпов и
                # `horizon_h` не несёт; срок у неё тот, что берёт
                # касса по умолчанию (`TR.HOLD_H`) — печатать пустую
                # строку правил значило бы показать книгу без срока.
                facts.append(
                    f"hold {man.get('horizon_h') or TR.HOLD_H} h")
                if man.get("entry_floor_bp"):
                    facts.append(
                        f"entry ≥ {man['entry_floor_bp']:g} bp")
            if man.get("stopped"):
                facts.append("STOPPED")
            if man.get("rank_target"):
                facts.append(f"rank by {man['rank_target']}")
            if man.get("slots"):
                facts.append(f"{man['slots']} slots")
            if man.get("rules_version"):
                facts.append(f"rules v{man['rules_version']}")
            row["facts"] = " · ".join(facts)
            per = {}
            for a in ("gbm", "nn"):
                s = stats.get((key, a))
                if not s:
                    continue
                d = {}
                if s.get("closed"):
                    d.update(closed=s["closed"],
                             win=round(s["wins"] / s["closed"], 3),
                             pnl=round(s["pnl"], 2))
                if s.get("open"):
                    d.update(open=s["open"], marked=s["marked"],
                             open_pnl=s["open_pnl"])
                if d:
                    per[a] = d
            row["stats"] = per
            books.append(row)
        # Турнир политик — ветка ситуационной книги. Живые числа из
        # артефакта последнего прогона; артефакта нет — честное «ждёт
        # прогона», а не пустая карточка.
        # Артефакт читает ОДИН метод на обе страницы: своя копия
        # разбора здесь однажды разошлась бы с листом — и порог
        # измеримости в ней уже был зашит числом 30 вместо константы
        # турнира.
        tourney = dict(self.TOURNEY_TREE)
        tj = self.model_tournament()
        if tj.get("present"):
            wf = tj.get("wf") or {}
            picks = (wf.get("points") or []) if wf else []
            tourney.update(
                present=True, legs=tj.get("legs"),
                status=(tj.get("verdict") or {}).get("status")
                or "прогон без вердикта",
                points=len(picks),
                pick=(picks[-1].get("pick") if picks else None),
                cells_measured=tj.get("measured"),
                run_age_sec=tj.get("run_age_sec"),
                stale=tj.get("stale"))
        else:
            tourney.update(present=False,
                           status=tj.get("status")
                           or "ждёт первого прогона на VPS")
        # Третий корень — согласие рук: у его книг руки тождественны
        # по построению, и arm здесь имя корня, а не рука кассы;
        # канонической рукой показа страница берёт gbm.
        out = {"roots": [dict(self.ROOT_TREE["gbm"], arm="gbm"),
                         dict(self.ROOT_TREE["nn"], arm="nn"),
                         dict(self.ROOT_TREE["agree"], arm="agree")],
               "books": books, "tournament": tourney,
               # Депозит книги (на руку): страница печатает рядом с
               # деньгами долю к нему (просьба владельца). Число — из
               # ядра расчёта, не из констант страницы.
               "cap": TR.START_BALANCE,
               "errors": errors, "scanned": scanned,
               "generated_at": round(now, 1)}
        self._tree_cache = (now, out)
        return out

    def entry_px(self, picks):
        """Цены входа для выборов, которые их не несут.

        Цена входа — закрытие часа сигнала, и оно уже лежит в почасовой
        сводке. Значит у старых выборов цена НЕ потеряна: её надо
        прочитать, а не считать недоступной.
        """
        need = set()
        for pk in picks or []:
            hour = pk.get("hour")
            for side in ("long", "short"):
                for p in pk.get(side) or []:
                    if not p.get("px"):
                        need.add((p.get("sym"), hour))
        rows = self.hour_rows(need)
        return {k: (v or {}).get("c") for k, v in rows.items()}

    def paths(self, trades, hold_h=None):
        """Просадка по каждой сделке — из тех же почасовых сводок.

        Итог сделки говорит, чем всё кончилось, и молчит о том, сколько
        позиция была в минусе по дороге. Владелец спрашивал именно про
        второе, и ответ считается по крайним значениям середины за часы
        удержания. `hold_h` — горизонт книги: часы удержания у часовой
        и суточной книги разные.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
        import trades as TR
        hold = hold_h or TR.HOLD_H
        need = set()
        for t in trades:
            for h in TR.live_hours(t, hold):
                need.add((t.get("sym"), h))
        rows = self.hour_rows(need)
        TR.excursion(trades, rows, hold)
        return rows

    @staticmethod
    def dd_money(trades):
        """Просадку в деньги и в доли депозита — ПОСЛЕ расчёта счёта.

        Порядок обязателен: размер позиции проставляет счёт, а без
        размера денежной просадки не существует. Зовётся отдельно, а не
        внутри `paths`, именно поэтому.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
        import trades as TR
        return TR.dd_money(trades)

    def marks(self, trades):
        """Текущая середина по символам открытых сделок.

        Из живых книг, а не из файлов: сборщик держит стакан в памяти,
        и это самая свежая цена, какая вообще есть в системе.
        """
        out = {}
        for t in trades:
            if t.get("state") != "открыта":
                continue
            sym = t.get("sym")
            if sym in out or sym not in self.books:
                continue
            bid, ask = self.books[sym].best()
            if bid and ask:
                out[sym] = (bid + ask) / 2.0
        return out

    def model_marks(self, hz=None):
        """Только переоценка открытых сделок — для частого опроса.

        Отдельно от полной выдачи намеренно: страница обновляет её раз в
        десять секунд, а полный список сделок весит на порядок больше.
        Прежний урок ровно об этом — тяжёлый ответ на частом опросе не
        успевал прийти, и страница писала «нет связи» на исправном
        сборщике.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
        import trades as TR
        s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
        # Опрос обслуживает ТУ книгу, которую смотрят: зашитая главная
        # оставляла прочие без переоценки — владелец видел прочерки в
        # UNREAL у входов ситуационного сканера.
        name, hz_err = self.book_dir_of(hz)
        if hz_err:
            return {"error": hz_err, "hz": hz, "rows": []}
        mdir = os.path.join(s8, name)
        pk = self._jsonl(os.path.join(mdir, "picks.jsonl"))
        revs = self._jsonl(os.path.join(mdir, "review.jsonl"))
        try:
            with open(os.path.join(mdir, "manifest.json"),
                      encoding="utf-8") as f:
                mman = json.load(f) or {}
        except (OSError, ValueError):
            mman = {}
        sit = bool(mman.get("situational"))
        # Горизонт — из манифеста книги, как в полной выдаче: без него
        # позиции 24-часовой книги старше четырёх часов считались бы
        # «ждёт разбора» и выпадали из переоценки.
        hold = self.book_hold(mman, TR.HOLD_H)
        tr = TR.build(pk, revs, hold_h=hold,
                      px_at=self.entry_px(pk),
                      books=TR.load_books(
                          os.path.join(mdir, "books.jsonl")))
        # Живые события — ДО переоценки, той же функцией, что везде.
        if sit:
            self.live_overlay(mdir, tr, revs)
        for a in ("gbm", "nn"):
            TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                       slots=mman.get("slots"),
                       sizing=mman.get("sizing"))
        op = [t for t in tr if t.get("state") == "открыта"]
        if not op:
            return {"source": None, "at": round(time.time(), 1),
                    "rows": []}
        TR.mark(op, self.marks(op))
        return {"source": name, "at": round(time.time(), 1),
                "rows": [{"arm": t["arm"], "hour": t["hour"],
                          "sym": t["sym"], "side": t["side"],
                          "cur_px": t.get("cur_px"),
                          "unreal_bp": t.get("unreal_bp"),
                          "unreal_net_bp": t.get("unreal_net_bp"),
                          "closes_in_sec": t.get("closes_in_sec")}
                         for t in op]}

    def trade_by_id(self, tid):
        """Сделка по короткому id — поиск по всем книгам разом.

        Просьба владельца: у каждой сделки имя, по которому её можно
        назвать, не описывая монету, руку и час. Id выводится из полей
        записи (`trades.tid_of`), поэтому одно решение в торгуемой
        книге и в наблюдательной записи находится дважды — оба
        попадания возвращаются со своим источником, читатель видит,
        какую страницу открывать.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        s8 = os.path.join(os.path.dirname(HERE), "s8_loop", "out")
        tid = str(tid or "").strip().lstrip("#").lower()
        hits = []
        if tid:
            for key, name in self.BOOK_DIRS.items():
                mdir = os.path.join(s8, name)
                pk = self._jsonl(os.path.join(mdir, "picks.jsonl"))
                revs = self._jsonl(os.path.join(mdir, "review.jsonl"))
                try:
                    with open(os.path.join(mdir, "manifest.json"),
                              encoding="utf-8") as f:
                        mman = json.load(f) or {}
                except (OSError, ValueError):
                    mman = {}
                sit = bool(mman.get("situational"))
                if not pk and not revs and not sit:
                    continue
                hold = self.book_hold(mman, TR.HOLD_H)
                tr = TR.build(pk, revs, hold_h=hold,
                              px_at=self.entry_px(pk),
                              books=TR.load_books(
                                  os.path.join(mdir, "books.jsonl")))
                if sit:
                    self.live_overlay(mdir, tr, revs)
                if not any(t.get("tid") == tid for t in tr):
                    continue
                # Деньги — той же кассой, что у страниц: найденная
                # сделка обязана совпадать с тем, что показывают.
                for a in ("gbm", "nn"):
                    TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                               slots=mman.get("slots"),
                               sizing=mman.get("sizing"))
                for t in tr:
                    if t.get("tid") == tid:
                        hits.append({"book": key, "source": name,
                                     "trade": t})
        return {"tid": tid, "hits": hits,
                "at": round(time.time(), 1)}

    # Разобранные строки `.jsonl` — ОДИН кеш на класс.
    #
    # Файлы книг читают девятнадцать мест (обзор, страница сделок,
    # лига, отметки, волатильность, дерево, обучение), и каждое читало
    # их заново. У ситуационной книги строка выбора несёт лесенки
    # стакана — десятки килобайт, — поэтому `/model`, собирающий ВСЕ
    # книги, перестал укладываться в минуту: страница не открывалась
    # вовсе, а лига отвечала 25 с.
    #
    # Числа кеш не меняет и менять не вправе: он отдаёт ровно те
    # строки, что лежат в файле. Признак «файл тот же» — не время
    # правки и не длина (перезапись даёт и то, и другое), а совпадение
    # ПЕРВЫХ байт: архивация книги и пересчёт истории меняют начало
    # файла, и такой файл перечитывается целиком.
    _JSONL_CACHE = {}
    _JSONL_HEAD = 512
    # Рядом пишется стакан, и память здесь дороже секунд: при
    # превышении бюджета выбрасываются самые давние по последнему
    # обращению.
    _JSONL_BUDGET = 192 * 1024 * 1024

    @staticmethod
    def _jsonl(path):
        cache = Collector._JSONL_CACHE
        try:
            st = os.stat(path)
        except OSError:
            cache.pop(path, None)
            return []
        # В подпись входит и номер узла: перезапись через
        # переименование даёт новый файл на том же пути, и
        # совпадение длины со временем правки тогда ничего не
        # значит.
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        hit = cache.get(path)
        if hit is not None and hit["sig"] == sig:
            hit["used"] = time.time()
            return hit["rows"]
        rows, offset, head = [], 0, b""
        if (hit is not None and st.st_size > hit["sig"][1]
                and st.st_ino == hit["sig"][2]):
            try:
                with open(path, "rb") as f:
                    head = f.read(Collector._JSONL_HEAD)
            except OSError:
                head = b""
            if head and head == hit["head"]:
                # Дописан хвост. Список копируется, а не дополняется на
                # месте: страницы держат ссылку на прежний ответ, и
                # дописывать его под ними значило бы менять уже отданное.
                rows, offset = list(hit["rows"]), hit["offset"]
        try:
            with open(path, "rb") as f:
                if offset:
                    f.seek(offset)
                elif not head:
                    head = f.read(Collector._JSONL_HEAD)
                    f.seek(0)
                buf = f.read()
        except OSError:
            return hit["rows"] if hit is not None else []
        # Разбираются только ЦЕЛЫЕ строки: файл дописывается прямо
        # сейчас, и хвост без перевода строки — половина записи, а не
        # порча. Смещение двигается до конца последней целой строки,
        # иначе такая запись потерялась бы навсегда.
        cut = buf.rfind(b"\n") + 1
        for line in buf[:cut].split(b"\n"):
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        cache[path] = {"sig": sig, "head": head, "offset": offset + cut,
                       "rows": rows, "used": time.time()}
        Collector._jsonl_trim()
        return rows

    @staticmethod
    def _jsonl_trim():
        cache = Collector._JSONL_CACHE
        total = sum(v["sig"][1] for v in cache.values())
        if total <= Collector._JSONL_BUDGET:
            return
        for path, _ in sorted(cache.items(), key=lambda kv: kv[1]["used"]):
            total -= cache.pop(path)["sig"][1]
            if total <= Collector._JSONL_BUDGET:
                break

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
                self.samples.append((now, total))
                rate, t0 = disk_rate(self.samples, now, total)
                self.disk = {"bytes": total, "at": now, "by_kind": by,
                             "free": du.free, "total": du.total,
                             "rate_h": rate,
                             "window_s": round(now - t0) if t0 else 0,
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

    def sit_load_positions(self, books):
        """Открытые позиции КАЖДОЙ книги сканера, без исключений.

        Список нужен двум разным делам, и путать их нельзя: по нему
        сторож ведёт уровни, и по нему же считаются ЗАНЯТЫЕ МЕСТА и
        стороны (`held`, `side_n` в `_sit_scan`). Книга «выход по
        времени» уровней не имеет — но места занимает как всякая
        другая, и опустевший список сделал бы её книгой без предела:
        каждый тик она видела бы все слоты свободными и входила бы
        снова. Дефект найден до того, как выстрелил, поэтому правило
        записано ЗДЕСЬ: гасится проверка уровней, а не позиции.
        """
        for d, stt in books.items():
            stt["pos"] = sit_open_levels(
                self._jsonl(os.path.join(d, "picks.jsonl")),
                self._jsonl(os.path.join(d, "review.jsonl")),
                self._jsonl(os.path.join(d, "entries_live.jsonl")))
        return books

    def sit_watch(self):
        """Живой сторож выходов ситуационной книги.

        «Цена прошла обещанный ход против» — единственное правило
        выхода, где решает МОМЕНТ: уровень известен со входа, а живая
        середина лежит у сборщика в памяти. Ждать часового цикла
        значило бы мерить выход по закрытию пробившего бара — урок S1:
        оно уже хуже уровня. Сторож пишет СОБЫТИЕ в свой файл
        (`exits_live.jsonl`), а строку разбора из события делает цикл
        обучения: у каждого файла один писатель — два процесса в одном
        файле уже стоили потерянных данных (gzip-дозапись B1).

        Правила «прогноз развернулся» и «предел возраста» остаются
        часовыми: прогноз обновляется переобучением, ему быстрее не
        стать.
        """
        base = os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                            self.BOOK_DIRS["sit"])
        # Книг может быть больше одной: торгуемая и наблюдательная (та
        # же ситуация без требования к отношению — иначе фильтру
        # владельца нечего показывать ниже боевого порога). Состояние
        # у каждой своё: перезапуск не дублирует события, потому что
        # записанное читается с диска, а не выводится из памяти.
        def fresh_state(mdir):
            return {
                "dir": mdir,
                "signalled": {(e.get("arm"), e.get("hour"),
                               e.get("sym"), e.get("side"))
                              for e in self._jsonl(os.path.join(
                                  mdir, "exits_live.jsonl"))},
                "entered": {(e.get("arm"), e.get("hour"), e.get("sym"))
                            for e in self._jsonl(os.path.join(
                                mdir, "entries_live.jsonl"))},
                "pos": [],
            }

        books = {base: fresh_state(base)}
        pos_at = 0.0
        sheet, sheet_at = None, 0.0
        # Взведённые имена: те, которых мы УЖЕ видели не проходящими
        # гейт. Вход разрешён только им — иначе первый же взгляд после
        # перезапуска (или после долгого чтения листа) выпускает всех,
        # у кого условие успело стать верным без нас, и это выглядит
        # пачкой входов одной секундой.
        armed, armed_hour = set(), None
        last_look = None
        while not self.stop.wait(5.0):
            try:
                now = time.time()
                if now - sheet_at > 60:
                    try:
                        with open(os.path.join(base, "scan_sheet.json"),
                                  encoding="utf-8") as f:
                            sheet = json.load(f)
                    except (OSError, ValueError):
                        sheet = None
                    sheet_at = now
                # Состав книг объявляет ЛИСТ: цикл знает, какие книги
                # ведёт, и сканеру незачем держать второй список — два
                # места, решающих одно, однажды разойдутся. Листа нет
                # или он старого образца — работаем одной торгуемой.
                want = (sheet or {}).get("books") or [
                    {"dir": os.path.basename(base),
                     "min_rr": (sheet or {}).get("min_rr"),
                     "slots": (sheet or {}).get("slots")}]
                root = os.path.dirname(base)
                for b in want:
                    d = os.path.join(root, b.get("dir") or "")
                    if d not in books:
                        os.makedirs(d, exist_ok=True)
                        books[d] = fresh_state(d)
                # Кого сторож ведёт ПО УРОВНЯМ. Список позиций при
                # этом строится ВСЕГДА и для всех: из него же берутся
                # занятые места и стороны, и опустошив его у книги без
                # уровней, я лишил бы её собственного счёта слотов —
                # она входила бы каждый тик без предела. Дефект найден
                # до того, как выстрелил: у книги «выход по времени»
                # входов ещё не было.
                watched = sit_watched(want, root)
                if now - pos_at > 60:
                    self.sit_load_positions(books)
                    pos_at = now
                sh_hour = (sheet or {}).get("hour")
                if sh_hour != armed_hour:
                    # Новый лист — новые обещания: взведение начинается
                    # заново, и первый же тик расставит его сам.
                    armed, armed_hour = set(), sh_hour
                # Взведение общее: пересечение гейта — свойство ЦЕНЫ, а
                # не книги, и книги различаются только требованием к
                # отношению и числом мест.
                self._sit_scan(root, sheet, want, books, now, armed)
                # Путь цены с прошлого взгляда — по каждому имени
                # разом, ОДНИМ снятием на тик: книг несколько, и
                # сбросив экстремум внутри цикла по книгам, вторая
                # книга смотрела бы на пустой путь.
                ext = {}
                for sym in {p["sym"] for stt in books.values()
                            for p in stt["pos"]}:
                    e = self.px_ext.pop(sym, None)
                    if e:
                        ext[sym] = (e[0], e[1])
                # Путь накоплен с ПРОШЛОГО взгляда, а позиция могла
                # открыться внутри этого окна: её уровень тогда задело
                # бы движение, случившееся ДО входа, и сделка вышла бы
                # той же секундой, что открылась. Свежей позиции путь
                # не даётся — ей хватит следующего тика.
                since = last_look
                last_look = now
                for d, stt in books.items():
                    if d not in watched:
                        # Книга «выход по времени»: уровней у неё нет
                        # вовсе, и закрывать её по стопу или цели
                        # значило бы торговать не то правило, которое
                        # судит её реплей. Позиции при этом на месте —
                        # их закроет часовой цикл по возрасту.
                        continue
                    for p in stt["pos"]:
                        key = (p["arm"], p["hour"], p["sym"], p["side"])
                        if key in stt["signalled"]:
                            continue
                        bk = self.books.get(p["sym"])
                        if not bk:
                            continue
                        bid, ask = bk.best()
                        if not (bid and ask):
                            continue
                        eh, el = ext.get(p["sym"], (None, None))
                        at = p.get("at_ts")
                        if at is not None and since is not None \
                                and at > since:
                            eh = el = None
                        ev = sit_exit_event(p, (bid + ask) / 2.0,
                                            eh, el, now)
                        if not ev:
                            continue
                        os.makedirs(d, exist_ok=True)
                        with open(os.path.join(d, "exits_live.jsonl"),
                                  "a", encoding="utf-8") as f:
                            f.write(json.dumps(ev, ensure_ascii=False)
                                    + "\n")
                        stt["signalled"].add(key)
                        if d == base:
                            took = ("дошла до цели"
                                    if ev["reason"]
                                    == "цена дошла до обещанной цели"
                                    else "прошла обещанный ход против")
                            lvl = (" — исполнение по цене уровня, "
                                   "принты прошли сквозь"
                                   if ev.get("fill") == "level" else "")
                            self.log(
                                f"ситуационная: {p['sym']} {took} "
                                f"({ev['move_bp']:+.0f} б.п.){lvl} — "
                                f"выход замечен живьём")
                # Живое поглощение: событие ЭТОГО тика становится
                # строкой книги сейчас, а не ближайшим часом (просьба
                # владельца — pnl сразу после закрытия). Метка —
                # суммарный счёт входов и выходов книги: первый тик
                # после подъёма подбирает и накопленный до перезапуска
                # хвост.
                for d, stt in books.items():
                    mark = len(stt["entered"]) + len(stt["signalled"])
                    if mark != stt.get("absorbed_mark"):
                        self.sit_absorb_now(d)
                        stt["absorbed_mark"] = mark
            except Exception as e:                        # noqa: BLE001
                self.log(f"сторож ситуационной книги: "
                         f"{type(e).__name__}: {e}")

    def sit_noise(self, sym, now):
        """Живой шум монеты: минутный размах середины, б.п. (v12).

        Мера для правила запаса сканера — стоп обязан переживать
        обычный минутный ход самой монеты И ту минуту, которая идёт
        прямо сейчас. Урок T3/T4: стоп внутри шума свечи есть монетка
        минус комиссия. Урок CATSTOCK 2026-08-13, поправивший первую
        версию меры: у тонкого инструмента медиана целых минут — ноль
        (котировка большинство минут не шевелится), а вход случается
        ровно в ту минуту, где цена взорвалась, — то есть мера v11
        видела «шум 0» и пропускала стоп внутри 225-пунктового
        фитиля. Текущая минута из размаха исключалась как заниженная;
        для максимума это неверно — её уже накопленный размах и есть
        нижняя граница того, что стоп обязан пережить.

        Итог — максимум из медианы целых минут (~15 минут кольца) и
        размаха текущей минуты по накопленным точкам. Меньше пяти
        целых минут — меры нет; нулевой итог — тоже её отсутствие:
        котировка, не шевелившаяся 15 минут, есть замороженный ряд,
        а не безопасный, и вход по ней запрещён.

        Кеш на минуту держит только медиану целых минут: размах
        текущей растёт внутри минуты и обязан считаться свежим —
        замороженный кешем, он весь взрыв простоял бы на значении
        первой секунды.
        """
        mstamp = int(now // 60)
        # Снимок кольца один на обе части: сборщик дописывает его из
        # другого потока, и обратный проход по живому deque падал бы
        # на «mutated during iteration».
        pts = list(self.mid.get(sym) or ())
        hit = self._noise_cache.get(sym)
        if hit is not None and hit[0] == mstamp:
            med = hit[1]
        else:
            bins = {}
            for ts, m in pts:
                b = int(ts // 60)
                if b >= mstamp:
                    continue
                lohi = bins.get(b)
                if lohi is None:
                    bins[b] = [m, m]
                else:
                    if m < lohi[0]:
                        lohi[0] = m
                    if m > lohi[1]:
                        lohi[1] = m
            rng = sorted((hi - lo) / ((hi + lo) / 2.0) * 1e4
                         for lo, hi in bins.values() if lo > 0)
            med = rng[len(rng) // 2] if len(rng) >= 5 else None
            self._noise_cache[sym] = (mstamp, med)
        if med is None:
            return None
        lo = hi = None
        for ts, m in reversed(pts):
            if int(ts // 60) < mstamp:
                break
            if lo is None or m < lo:
                lo = m
            if hi is None or m > hi:
                hi = m
        cur = ((hi - lo) / ((hi + lo) / 2.0) * 1e4
               if lo is not None and lo > 0 else 0.0)
        val = max(med, cur)
        return val if val > 0 else None

    def sit_absorb_now(self, mdir):
        """Живое поглощение событий книги: pnl сразу после закрытия.

        Превращение событий в строки выбора и разбора делает общий
        модуль `sit_absorb` — тот же, что у часового цикла (второй
        копии правил нет), одновременную запись двух процессов
        разводит замок каталога. Лесенка выхода — живая книга В ЭТУ
        СЕКУНДУ: ближе к правде исполнения, чем снимок цикла часом
        позже; сжатие то же (`trades.cum_ladder`). Деньги по-прежнему
        штампует касса при чтении — здесь появляются только строки.

        Отказ поглощения не роняет сторожа и не молчит: события
        остаются в файлах, их подберёт следующий тик либо цикл.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import sit_absorb as SA
        import trades as TR

        def ladder_of(syms):
            out = {}
            for sym in syms:
                bk = self.books.get(sym)
                if not bk:
                    continue
                s = bk.sample_view(ladder=0, bands=())
                if not s:
                    continue
                b = TR.cum_ladder(s.get("b"))
                a = TR.cum_ladder(s.get("a"))
                if not b or not a:
                    continue
                out[sym] = {"mid": (s["bid"] + s["ask"]) / 2.0,
                            "b": b, "a": a,
                            "t": round(time.time(), 1)}
            return out

        try:
            return SA.absorb(mdir, ladder_of, self.log)
        except Exception as e:                            # noqa: BLE001
            self.log(f"поглощение событий {os.path.basename(mdir)}: "
                     f"{type(e).__name__}: {e}")
            return (0, 0)

    def _sit_scan(self, root, sheet, want, books, now, armed):
        """Один тик сканера входов: лист сечения против живых цен.

        Карта от модели (лист часа), курок от цены: вход в ту секунду,
        когда остаток обещанного хода проходит гейты. Имя, где
        движение уже пройдено, отсеивается остатком само.

        Кандидат считается ОДИН раз на все книги, а дальше книги
        различаются лишь требованием к отношению и числом мест:
        второй проход считал бы ту же волну заново и мог бы разойтись
        с первым на округлении.
        """
        if not sheet:
            return
        # Протухший лист — не карта: прогнозы стоят на закрытии часа,
        # и старше двух часов им верить нельзя (упавшее переобучение
        # обязано остановить входы, а не торговать прошлым).
        if now - (sheet.get("written_at") or 0) > 2 * 3600:
            return
        # Дневной тормоз (забор): действует ли — решает ОДНО правило
        # ядра (`day_brake_active`), то же, что у файла состояния.
        # Неизвестное или устаревшее состояние не тормозит: fail-open,
        # но состояние видно странице и статусу — защита, которой
        # молча нет, хуже отсутствия защиты (урок ionice).
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        braked = TR.day_brake_active(getattr(self, "_brake", None), now)
        min_edge = float(sheet.get("min_edge_bp") or 22.0)
        # Отсутствие поля — не «правила нет»: лист прежнего образца
        # писался до требования скидки, и молчаливый ноль вернул бы
        # ровно то поведение, ради снятия которого правило заведено.
        md = sheet.get("min_disc_bp")
        min_disc = float(md) if md is not None else 11.0
        # Полоса взведения: насколько ДАЛЬШЕ крючка обязано стоять имя,
        # чтобы его последующий проход считался событием. Отсутствие
        # поля — лист прежнего образца, и тут та же логика, что у
        # скидки: молчаливый ноль вернул бы поведение, ради снятия
        # которого правило и заведено.
        ab = sheet.get("arm_band_bp")
        band = float(ab) if ab is not None else 11.0
        # Потолок на съеденную долю обещания против (правило v11):
        # отсутствие поля — лист прежнего образца, и молчаливая
        # единица вернула бы фейд разгона, ради снятия которого
        # правило заведено. Та же логика, что у скидки и полосы.
        me = sheet.get("max_eaten")
        max_eaten = float(me) if me is not None else 0.5
        hour = sheet.get("hour")
        # Гейт по отношению у сканера снимается: его применяет КНИГА,
        # каждая своим порогом. Само событие входа от этого не
        # меняется — меняется, кто его к себе записывает.
        # Согласие рук считается ПО ЛИСТУ, а не по сделкам — та же
        # конвенция, что у реплея кандидата (`agreed_keys`): у второй
        # руки сделки может не быть из-за мест, и «согласие» тогда
        # означало бы «первой руке хватило места», а не «обе руки
        # увидели одно». Сторона имени берётся из знака прогноза листа.
        by_arm = {}
        for a, rr in (sheet.get("arms") or {}).items():
            by_arm[a] = {q.get("sym"): ("long" if float(
                q.get("fwd") or 0.0) > 0 else "short") for q in rr}

        def agreed(sym, side, arm):
            return any(m.get(sym) == side
                       for a, m in by_arm.items() if a != arm)

        for arm, rows in (sheet.get("arms") or {}).items():
            mids, moves = {}, []
            for r in rows:
                b = self.books.get(r.get("sym"))
                if not b:
                    continue
                bid, ask = b.best()
                if not (bid and ask):
                    continue
                mid = (bid + ask) / 2.0
                mids[r["sym"]] = mid
                if r.get("px"):
                    moves.append((mid / r["px"] - 1.0) * 1e4)
            # Волна — средний живой ход листа: тот же смысл, что фактор
            # в целях. Мерить её не из чего, пока книги дали меньше
            # тридцати имён, — тогда вход молчит, а не считает волной
            # три случайных монеты.
            if len(moves) < 30:
                continue
            wave = sum(moves) / len(moves)
            free = {}
            for b in want:
                d = os.path.join(root, b.get("dir") or "")
                stt = books.get(d)
                if stt is None:
                    continue
                held = {p["sym"] for p in stt["pos"] if p["arm"] == arm}
                # Потолок отношения — правило книги низкого RR; лист
                # без поля означает «потолка нет» (None, не ноль —
                # ноль запретил бы вход всем).
                mx = b.get("max_rr")
                ps = b.get("per_side")
                # Гейт книги — СЛОВАРЬ: правил на книге стало
                # одиннадцать (кандидаты фабрики принесли пол входа,
                # места по сторонам и согласие рук), и кортеж такой
                # длины читается только счётом запятых.
                free[d] = {
                    "free": int(b.get("slots") or 6) - len(held),
                    "held": held,
                    "min_rr": float(b.get("min_rr") or 0.0),
                    "max_rr": None if mx is None else float(mx),
                    # Множитель шума и минимальный стоп —
                    # правила книги, как min_rr; лист без поля
                    # — прежнее поведение (1 шум, порога нет).
                    "noise_mult": float(b.get("noise_mult") or 1.0),
                    "min_stop_bp": float(b.get("min_stop_bp") or 0.0),
                    # Кого тормоз НЕ касается — объявляет лист
                    # (наблюдательная запись: без неё цену
                    # тормоза потом нечем измерить). Отсутствие
                    # поля — книга тормозится: молчаливое
                    # исключение сняло бы забор незаметно.
                    "no_brake": bool(b.get("no_brake")),
                    # Пол входа книги — на прогнозе ЛИСТА: та же
                    # величина, по которой отбирает реплей кандидата.
                    # Нет поля — пола нет (ноль запретил бы всё).
                    "floor_bp": float(b.get("floor_bp") or 0.0),
                    # Места ПО СТОРОНАМ: реплей считает ширину на
                    # сторону, и общий счётчик пустил бы десять лонгов
                    # в книгу шириной пять. Нет поля — прежнее
                    # поведение, счёт по книге целиком.
                    "per_side": None if ps is None else int(ps),
                    "side_n": {"long": 0, "short": 0},
                    # Согласие рук — ось правила кандидата: имя берётся,
                    # только если ОБЕ руки выбрали его и одной стороной.
                    "agree": bool(b.get("agree")),
                    "stt": stt}
                if free[d]["per_side"] is not None:
                    for q in stt["pos"]:
                        if q["arm"] == arm and q["side"] in ("long",
                                                             "short"):
                            free[d]["side_n"][q["side"]] += 1
            # Порядок просмотра кандидатов — в единицах собственной σ
            # монеты (решение владельца о переводе ситуационных сделок
            # на per σ). Мест меньше, чем проходящих гейт, и слот
            # обязан достаться тому, у кого ход крупен ДЛЯ НЕГО, а не
            # тому, кто раньше стоит в списке: прежний порядок был
            # порядком строк листа, то есть случайным.
            #
            # Гейт при этом не тронут: он в базисных пунктах, потому
            # что выведен из круга издержек. Лист старого образца поля
            # не несёт — тогда порядок прежний, и это видно по логу
            # цикла, а не молча.
            #
            # Приоритет едет в КАЖДУЮ запись входа, а не только в
            # манифест: манифест переписывается каждый час и говорит о
            # правиле, действующем СЕЙЧАС, тогда как сделка полугодовой
            # давности была взята другим. Гейт ситуационной книги не
            # менялся, поэтому версия правил не поднималась и книга
            # осталась прежней — а по какой очереди раздавались слоты,
            # без этого поля через месяц сказать было бы нечем.
            scan_rank = (sheet.get("scan_rank")
                         if any(q.get("fwd_z") is not None for q in rows)
                         else None)
            rows = sorted(
                rows,
                key=lambda q: -abs(float(q.get("fwd_z") or 0.0)))
            for r in rows:
                sym = r.get("sym")
                mid = mids.get(sym)
                if not mid:
                    continue
                # Живой шум монеты — часть гейта v11: запас до стопа
                # обязан переживать обычный минутный ход. Первые
                # минуты после запуска меры нет — и входа нет, это
                # калибровка, а не отказ.
                noise = self.sit_noise(sym, now)
                # Гейт без отношения: RR проверяет книга.
                got = sit_scan_entry(r, mid, wave, min_edge, 0.0,
                                     min_disc, noise, max_eaten)
                key = (arm, hour, sym)
                if not got:
                    # Видели имя НЕ проходящим — но взводим не всякий
                    # промах, а только уверенный: имя обязано не
                    # проходить даже ОСЛАБЛЕННЫЙ на полосу гейт. Иначе
                    # взводится тот, кто стоит в миллиметре от крючка,
                    # и пятисекундное дрожание выпускает когорту разом
                    # — пачки входов, которые владелец видел четырежды.
                    #
                    # Ослабленный гейт считается ТОЙ ЖЕ функцией с
                    # меньшей скидкой: второй расчёт того же условия
                    # однажды разошёлся бы с первым, и правило входа
                    # перестало бы совпадать с правилом взведения.
                    if not sit_scan_entry(r, mid, wave, min_edge, 0.0,
                                          min_disc - band, noise,
                                          max_eaten):
                        armed.add(key)
                    continue
                if key not in armed:
                    # Условие было верно уже при первом нашем взгляде:
                    # значит момент прошёл без нас (перезапуск сборщика,
                    # опоздавший лист). Гнаться за пройденным движением
                    # нельзя — ровно это и делало пачку входов одной
                    # секундой, которую владелец видел трижды.
                    continue
                took = False
                braked_hit = False
                for d, gt in list(free.items()):
                    held, stt = gt["held"], gt["stt"]
                    min_rr, max_rr = gt["min_rr"], gt["max_rr"]
                    n_mult, m_stop = gt["noise_mult"], gt["min_stop_bp"]
                    no_brake = gt["no_brake"]
                    if gt["free"] <= 0 or sym in held:
                        continue
                    # Места по сторонам — правило ширины кандидата.
                    side = got.get("side")
                    if gt["per_side"] is not None and (
                            gt["side_n"].get(side, 0) >= gt["per_side"]):
                        continue
                    # Пол входа книги проверяется на прогнозе ЛИСТА
                    # (`fwd0`), а не на остатке: остаток есть то, что
                    # осталось после хода, и порог на нём отбирал бы по
                    # другой величине, чем реплей кандидата.
                    if gt["floor_bp"] and abs(
                            float(got.get("fwd0") or 0.0)) < gt["floor_bp"]:
                        continue
                    # Согласие рук: имя берётся, только если ВТОРАЯ рука
                    # выбрала его тем же направлением. Ось правила
                    # кандидата; лист без поля — прежнее поведение.
                    if gt["agree"] and not agreed(sym, side, arm):
                        continue
                    # Дневной тормоз: вход торгуемой книги не берётся.
                    # Выходов это не касается вовсе — их ведёт сторож
                    # другой дорогой (вход — возможность, выход —
                    # обязанность).
                    if braked and not no_brake:
                        braked_hit = True
                        # Пропуск считается ЧИСЛОМ по каждой книге:
                        # немаркированная тишина неотличима от отказа.
                        self.brake_skips = getattr(
                            self, "brake_skips", 0) + 1
                        continue
                    if key in stt["entered"]:
                        continue
                    if got["rr"] < min_rr:
                        continue
                    # Книга низкого RR берёт ДРУГОЙ конец распределения
                    # отношения: замер по наблюдательной записи показал,
                    # что высокий RR — это узкий стоп, а не крупная цель.
                    if max_rr is not None and got["rr"] > max_rr:
                        continue
                    # Правило книги равного риска (после #ptadyrc:
                    # стоп 39 б.п. при шуме 37.3 — запас в один
                    # фитиль, снятый минутой позже входа). Базовый
                    # гейт v11 уже требует один шум; книга вправе
                    # требовать больше. Порог на книге, а не в
                    # `sit_scan_entry`: кандидат один на все книги,
                    # различаются требования — как с `min_rr`.
                    if abs(got["mae"]) < n_mult * noise - 1e-9:
                        continue
                    # Правило книги равного риска (решение владельца:
                    # «размер тейков и стопов должен быть одинаковый»):
                    # стоп тоньше порога не помещает риск R под потолок
                    # имени, размер срезал бы потолок и риск выходил бы
                    # меньше целевого. Порог выведен из забора
                    # (R/потолок = 1 %) и едет с листом.
                    if abs(got["mae"]) < m_stop - 1e-9:
                        continue
                    ev = {"arm": arm, "hour": hour,
                          "at_ts": round(now, 3),
                          "scan_rank": scan_rank,
                          "reason": "вход по ситуации", **got}
                    if max_rr is not None:
                        # Потолок — числом в запись, как noise_mult:
                        # сработало ли правило книги, проверяется
                        # записью, а не доверием к коду.
                        ev["max_rr"] = max_rr
                    if n_mult != 1.0:
                        # Множитель — числом в запись: сработало ли
                        # правило книги, проверяется записью, а не
                        # доверием к коду (урок v5 с fwd0).
                        ev["noise_mult"] = n_mult
                    if m_stop:
                        ev["min_stop_bp"] = m_stop
                    # Номер обучения — С ЛИСТА, породившего вход: цикл,
                    # который позже перепишет событие в книгу, может
                    # успеть обучиться заново, и сделке достались бы
                    # чужие веса.
                    if sheet.get("train_seq") is not None:
                        ev["train_seq"] = sheet["train_seq"]
                    os.makedirs(d, exist_ok=True)
                    with open(os.path.join(d, "entries_live.jsonl"),
                              "a", encoding="utf-8") as f:
                        f.write(json.dumps(ev, ensure_ascii=False)
                                + "\n")
                    stt["entered"].add(key)
                    held.add(sym)
                    gt["free"] -= 1
                    if gt["per_side"] is not None:
                        gt["side_n"][side] = gt["side_n"].get(side, 0) + 1
                    # Свежий вход сторожится с этой же секунды, не
                    # дожидаясь перечитывания файлов. `at_ts` обязателен:
                    # по нему страж свежести отличает позицию, открытую
                    # внутри окна пути, — без поля путь, накопленный ДО
                    # входа, убивал сделку той же секундой (CATSTOCK
                    # 2026-08-13: фитиль до 838 случился до входа по
                    # 857.25, а стоп 849.33 сняло «путём» мгновенно).
                    stt["pos"].append({
                        "arm": arm, "hour": hour, "sym": sym,
                        "side": got["side"], "px": got["px"],
                        "adv": got["mae"], "fav": got["mfe"],
                        "at_ts": round(now, 3)})
                    took = True
                if took:
                    armed.discard(key)
                elif braked_hit:
                    # Момент прошёл ПРИ тормозе: после полуночи гнаться
                    # за пройденным движением нельзя (правило v5), имя
                    # развзводится.
                    armed.discard(key)
                    self.log(
                        f"ситуационная [{arm}]: живой вход {sym} "
                        f"{got['side']} (остаток {got['fwd']:+.0f} б.п. "
                        f"против {got['fwd0']:+.0f} у листа, скидка "
                        f"{abs(got['fwd']) - abs(got['fwd0']):+.0f}, RR "
                        f"{got['rr']}) — поймано в моменте")


    BRAKE_TTL = 300           # период пересчёта тормоза, секунд

    def brake_watch(self):
        """Дневной тормоз: реализованный день торгуемых книг против
        порога −1 % суммарного капитала (`trades.DAY_BRAKE_SHARE`).

        Один ПИСАТЕЛЬ состояния на весь проект: сумму считает та же
        дорога, что у лиги (`closed_rows` — деньги штампует касса), и
        состояние уходит атомарным файлом `s8_loop/out/day_brake.json`
        — его читают часовой цикл и страницы. Второй расчёт того же
        числа в цикле однажды разошёлся бы с этим.

        Пересчёт раз в BRAKE_TTL, в СВОЁМ потоке: обход книг стоит
        секунды, а 5-секундный тик сторожа делит нить с ВЫХОДАМИ, и
        блокировать его счётом нельзя. Плата — запаздывание тормоза до
        пяти минут; реплей закладывал ноль, значит живой тормоз чуть
        слабее замеренного, и это записано, а не спрятано.
        """
        sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                        "s8_loop"))
        import trades as TR
        path = os.path.join(os.path.dirname(HERE), "s8_loop", "out",
                            TR.DAY_BRAKE_FILE)
        n_books = len([k for k, _ in self.BOOKS
                       if k not in self.ECHO_BOOKS])
        limit = TR.day_brake_limit(n_books)
        said = None
        while not self.stop.wait(self.BRAKE_TTL):
            now = time.time()
            try:
                rows, _err, _sc, _op = self.closed_rows()
                realized = TR.day_realized(
                    ((r["at"], r["pnl"]) for r in rows
                     if r["hz"] not in self.ECHO_BOOKS), now)
                st = {"at": round(now, 1), "limit": limit,
                      "realized": round(realized, 2),
                      "on": realized <= -limit,
                      "skips": self.brake_skips}
            except Exception as e:                    # noqa: BLE001
                # Ошибка счёта — не молчание: состояние несёт причину,
                # тормоз при этом не действует (fail-open), и страница
                # обязана это показать.
                st = {"at": round(now, 1), "limit": limit,
                      "error": f"{type(e).__name__}: {e}"}
            self._brake = st
            try:
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False)
                os.replace(path + ".tmp", path)
            except OSError as e:
                self.log(f"тормоз: состояние не записано: {e}")
            state = (st.get("on"), st.get("error") is not None)
            if state != said:
                # Печать при СМЕНЕ состояния, не каждый тик: тревога,
                # повторяющаяся вечно, перестаёт быть сигналом.
                if st.get("error"):
                    self.log(f"тормоз: счёт не удался — {st['error']}")
                elif st.get("on"):
                    self.log(f"ДНЕВНОЙ ТОРМОЗ: день {st['realized']:+.2f} $ "
                             f"при пороге −{limit:.0f} — новые входы до "
                             f"конца суток закрыты")
                else:
                    self.log(f"тормоз тих: день {st['realized']:+.2f} $ "
                             f"при пороге −{limit:.0f}")
                said = state

    def run(self, hours):
        deadline = self.started + hours * 3600 if hours else None
        threading.Thread(target=self.metrics_poll, daemon=True).start()
        threading.Thread(target=self.sampler, daemon=True).start()
        threading.Thread(target=self.statuser, daemon=True).start()
        threading.Thread(target=self.reporter, daemon=True).start()
        threading.Thread(target=self.diskstat, daemon=True).start()
        threading.Thread(target=self.sit_watch, daemon=True).start()
        threading.Thread(target=self.brake_watch, daemon=True).start()
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


def sit_scan_entry(row, mid, wave_bp, min_edge, min_rr, min_disc,
                   noise_bp, max_eaten):
    """Живой вход по ситуации: якорим прогноз листа к живой цене.

    `row` — строка листа сечения (прогноз `fwd` — остаток к волне,
    СЫРЫЕ обещания пути `mae`/`mfe`, бета, цена закрытия `px`). К
    моменту тика цена ушла: остаток прогноза = прогноз минус уже
    пройденный ОСТАТОЧНЫЙ ход (сырой ход минус бета×волна — единицы
    обязаны совпадать, fwd захеджирован волной). Обещания пути
    переякориваются вычитанием сырого хода. Вход, когда остаток
    проходит те же гейты, что часовой вход: край и RR.

    Имя, где движение уже пройдено, отсеивается само — остаток мал.
    Перелёт за прогноз (остаток сменил знак) — другая ситуация, не
    заявка модели: пропуск. Возвращает поля события либо `None`;
    чистая функция — правило денег живёт под тестом, а не в потоке.

    Стоп берётся из квантильных концов листа (`mae_q`/`mfe_q`), а не
    из линии прогноза: линия прогноза есть уровень, куда модель ЖДЁТ
    цену, и заявка на нём срабатывает примерно у половины сделок.
    Отношение RR считается по этому же стопу — иначе гейт мерил бы
    одно, а сделка несла другое.

    `min_disc` — насколько остаток обязан ПРЕВЫШАТЬ обещание листа.
    Без него курок спускала не цена, а лист: пока цена не двинулась,
    остаток равен полному прогнозу, и все выбранные моделью имена
    проходили гейт в первый же такт после записи листа — книга
    набивалась пачкой в минуту цикла. Требование скидки означает
    ровно «цена пришла к нам»: вход дешевле того, на что рассчитывала
    модель, и на величину, которой хватает окупить круг издержек.

    Правило v11 — два гейта против фейда разгона. Ход цены против
    прогноза до входа считался ДВАЖДЫ в плюс (скидка растёт, RR
    растёт: переякоренный риск сжимается, награда растёт) и ни разу в
    минус — хотя тот же ход съедает обещанный моделью запас до стопа.
    `noise_bp` — живой минутный шум монеты: запас до стопа обязан его
    переживать, стоп внутри шума свечи есть монетка минус комиссия
    (урок T3/T4; TWT 2026-08-13 — запас 16 б.п., пробит баром самого
    входа). Нет меры (`None`) — нет входа: пропуск не есть ноль.
    `max_eaten` — потолок съеденной доли обещания против, якорь —
    ЛИСТ: у пяти стопнутых сделок v10 цена съела 44–86 % обещания до
    входа. Оба аргумента обязательны: правило, исчезающее при забытом
    параметре, есть отказ, неотличимый от тишины.
    """
    px0 = row.get("px")
    fwd0 = row.get("fwd")
    if not px0 or not mid or fwd0 is None:
        return None
    move = (mid / px0 - 1.0) * 1e4
    resid = move - (row.get("beta") if row.get("beta") is not None
                    else 1.0) * wave_bp
    rem = fwd0 - resid
    # Правило v10: ЛИСТ сам обязан видеть ситуацию. Остаток раздувается
    # любым крупным внутричасовым ходом (rem = fwd0 − ход), и при
    # прогнозе −0.011 % книга шортила разгон +2.17 % как «ситуацию» —
    # скрытый фейд любого разгона под именем модели. Прогноз мельче
    # гейта — кандидата не существует, каким бы ни был ход цены.
    if abs(fwd0) < min_edge:
        return None
    if abs(rem) < min_edge or (fwd0 > 0) != (rem > 0):
        return None
    # Скидка считается по МОДУЛЮ и после проверки знака: остаток той
    # же стороны, что прогноз, и больше него — значит остаточный ход
    # шёл ПРОТИВ прогноза, то есть цена пришла к нам. Допуск в
    # миллионную б.п. — потому что остаток выведен делением цен, и
    # ровное равенство выходит как 29.9999999999989: правило не имеет
    # права переворачиваться на шуме последнего разряда.
    if abs(rem) - abs(fwd0) < min_disc - 1e-6:
        return None
    side = "long" if rem > 0 else "short"
    if row.get("mae") is None or row.get("mfe") is None:
        return None
    rem_mae = row["mae"] - move
    rem_mfe = row["mfe"] - move
    # Квантильные концы пути переякориваются тем же ходом: это уровни
    # той же цены, а не другая величина. Листа без них хватает (цель
    # не набрала строк, лист прежнего образца) — тогда стоп остаётся
    # на средней линии, и `path_fields` скажет это полем `adverse_of`.
    rem_maeq = (row["mae_q"] - move if row.get("mae_q") is not None
                else None)
    rem_mfeq = (row["mfe_q"] - move if row.get("mfe_q") is not None
                else None)
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "s8_loop"))
    import trades as TR
    pf = TR.path_fields(side, round(rem_mae, 1), round(rem_mfe, 1),
                        mae_q=(None if rem_maeq is None
                               else round(rem_maeq, 1)),
                        mfe_q=(None if rem_mfeq is None
                               else round(rem_mfeq, 1)))
    # Отношение считается по ИСПОЛНЯЕМОЙ геометрии: риск сделки — это
    # тот стоп, который реально стоит, а не линия прогноза. Иначе гейт
    # обещал бы RR ≥ 2, а сделка бралась бы с фактическим 1.2 — та же
    # ошибка единиц, что уже дважды ловилась в этом проекте.
    adv, fav = pf["mae"], pf["mfe"]
    if side == "long" and not (fav > 0 and adv < 0):
        return None
    if side == "short" and not (fav < 0 and adv > 0):
        return None
    rr = abs(fav) / abs(adv)
    if rr < min_rr:
        return None
    # Правило v11, запас: стоп обязан переживать обычный минутный ход
    # самой монеты. Нет меры — нет входа.
    if noise_bp is None or abs(adv) < noise_bp - 1e-9:
        return None
    # Правило v11, съеденное обещание: та же геометрия стопа на ЯКОРЕ
    # ЛИСТА даёт, сколько хода против модель обещала изначально;
    # доля, уже пройденная ценой, не выше потолка. Обещание против не
    # той стороны — та же причина отказа: цена изначально за пределом
    # карты (случай «предсказанный максимум ниже входа» из замера
    # бракета, который обязан становиться пропуском).
    pf0 = TR.path_fields(side, round(row["mae"], 1),
                         round(row["mfe"], 1),
                         mae_q=(None if row.get("mae_q") is None
                                else round(row["mae_q"], 1)),
                         mfe_q=(None if row.get("mfe_q") is None
                                else round(row["mfe_q"], 1)))
    adv0 = pf0["mae"]
    if adv0 is None or (side == "long" and adv0 >= 0) \
            or (side == "short" and adv0 <= 0):
        return None
    eaten = 1.0 - abs(adv) / abs(adv0)
    if eaten > max_eaten + 1e-9:
        return None
    d = {"sym": row.get("sym"), "side": side, "px": round(mid, 8),
         "move_bp": round(move, 1), "wave_bp": round(wave_bp, 1),
         "fwd": round(rem, 1), "fwd0": fwd0,
         # Числа обоих правил v11 — в запись: сработало ли правило,
         # проверяется числом, а не доверием к коду (урок v5 с fwd0).
         "noise_bp": round(noise_bp, 1), "eaten": round(eaten, 3),
         "rr": round(rr, 2), **pf}
    # Объяснение прогноза приходит С ЛИСТА готовым: у сканера нет ни
    # модели, ни имён признаков, и пересчитать его тут нечем. Сделка
    # обязана нести, почему модель выбрала это имя (просьба владельца),
    # и единственный честный путь — довезти ответ цикла до записи.
    if row.get("why") is not None:
        d["why"] = row["why"]
    # Вид ситуации (доминирующие семейства признаков) — тем же путём.
    if row.get("setup") is not None:
        d["setup"] = row["setup"]
    if row.get("odd") is not None:
        d["odd"] = row["odd"]
    return d


def sit_cross(side, entry_px, adv, mid, fav=None, hi=None, lo=None):
    """Дошёл ли живой ход цены до обещанного уровня.

    `adv` — обещание из самого выбора (поле `mae` записи: ход ПРОТИВ
    этой позиции, у лонга отрицательный, у шорта положительный),
    `fav` — обещание В ПОЛЬЗУ (поле `mfe`). Возвращает
    `(ход в б.п., что задето)`, где второе — `None`, `"против"` или
    `"в пользу"`. Чистая функция — правило денег обязано жить под
    тестом, а не внутри потока.

    Цель проверяется вместе со стопом, потому что до неё книга не
    выходила вовсе: стоп стоял, тейка не было, и позиция, дошедшая до
    обещанного уровня, продолжала висеть до разворота прогноза или
    суток возраста. Владелец увидел это на XNYUSDT — цена прошла
    обещание почти сразу, сделка осталась открытой. Отношение
    прибыли к риску, которым гейт пускает вход (RR ≥ 2), при этом
    было наполовину выдумкой: рисковали по правилу, брали по случаю.

    Одновременное касание обоих уровней внутри одного тика решается
    ПРОТИВ нас — ровно как ничья в замерах T3/T4: цену между двумя
    уровнями секунда не разрешает, и приписывать себе лучший исход
    значило бы завышать результат систематически.

    `hi`/`lo` — крайние цены ПУТИ с прошлого взгляда (по ленте).
    Уровень задевается путём, а не снимком: сторож смотрит раз в пять
    секунд, и у POWERUSDT 8 августа тейк был пробит внутри одной
    минуты (низ 0.09119 при уровне 0.09161), а мгновенная середина
    этого не увидела — сделка осталась открытой при сработавшем
    правиле. Без пути правило проверялось на выборке из каждой
    пятой секунды.

    Эта функция решает только СРАБАТЫВАНИЕ; цену исполнения решает
    вызывающий (`sit_exit_event`): тейк, сквозь который прошли
    принты, — по цене уровня (`take_limit_fill`), всё остальное — по
    `mid`, то есть оттуда, где мы можем торговать, когда заметили.
    Касание уровня исполнения не гарантирует — на уровне чужая
    очередь, и это тот же принцип, что «не предполагать исполнение
    лимитной заявки по касанию» (ошибка движка v1). Стоп цену уровня
    не получает никогда: он не лимитка, в разрыве его исполнение
    хуже уровня.
    """
    move = (mid / entry_px - 1.0) * 1e4
    hi = mid if hi is None else max(hi, mid)
    lo = mid if lo is None else min(lo, mid)
    ext_adv = lo if side == "long" else hi
    ext_fav = hi if side == "long" else lo
    m_adv = (ext_adv / entry_px - 1.0) * 1e4
    m_fav = (ext_fav / entry_px - 1.0) * 1e4
    if (m_adv <= adv) if side == "long" else (m_adv >= adv):
        return move, "против"
    if fav is not None and (
            (m_fav >= fav) if side == "long" else (m_fav <= fav)):
        return move, "в пользу"
    return move, None


def take_limit_fill(side, entry_px, fav, hi, lo):
    """Цена исполнения тейка-лимитки, если принты прошли уровень.

    Уровень тейка известен со входа, то есть заявка стоит в книге
    заранее. Сделка СТРОГО за уровнем означает, что агрессор снял
    уровни глубже нашего, — по приоритету цена-время нашу заявку он
    обязан был снять раньше. Ровно касание исполнения не гарантирует
    (впереди чужая очередь) — тогда None, и выход идёт по доступной
    середине, как прежде. Правило v1 «не считать лимитку исполненной
    по касанию» остаётся в силе: здесь засчитывается не касание, а
    проход насквозь.

    `hi`/`lo` — крайние цены СДЕЛОК с прошлого взгляда (`px_ext`
    копится по ленте); середина сюда не подмешивается намеренно —
    середина умеет нырять на снятых бидах без единого принта, и
    лимитку такой нырок не исполняет. Нет пути (свежая позиция) —
    нет и исполнения по уровню.

    Замер, из которого правило (решение владельца, #6wa5abp): тейк
    0.027347, принты минуты выхода до 0.02700 — 124 б.п. сквозь, —
    а выход записан по отскочившей середине, 63.5 б.п. отдано; по
    11 тейкам книги отдано +164 б.п. суммой, 5 из 6 проверяемых —
    сквозные. Возвращает `(цена уровня, крайний принт)` либо None.
    """
    if fav is None:
        return None
    level = entry_px * (1.0 + fav / 1e4)
    if side == "long":
        if hi is None or hi <= level * (1.0 + 1e-9):
            return None
        return level, hi
    if lo is None or lo >= level * (1.0 - 1e-9):
        return None
    return level, lo


def sit_exit_event(pos, mid, hi, lo, now):
    """Событие живого выхода по уровню — или None.

    Срабатывание решает путь (`sit_cross`, ничья тика — против нас:
    стоп первым, и цена уровня ему не достаётся). Цена исполнения:
    тейк со сквозными принтами — по уровню, ход события тогда равен
    ровно обещанию (для книги равного риска это точное +r·R, ради
    которого она заведена); касание без прохода и всякий стоп — по
    доступной середине. Числа правила едут в событие (`fill`,
    `thru_px`): сработало ли оно, проверяется записью, а не доверием
    к коду.
    """
    move, hit = sit_cross(pos["side"], pos["px"], pos["adv"], mid,
                          pos.get("fav"), hi=hi, lo=lo)
    if not hit:
        return None
    ev = {"arm": pos["arm"], "hour": pos["hour"], "sym": pos["sym"],
          "side": pos["side"], "px": round(mid, 8),
          "move_bp": round(move, 1), "at_ts": round(now, 3),
          "reason": ("цена прошла обещанный ход против"
                     if hit == "против"
                     else "цена дошла до обещанной цели")}
    if hit == "в пользу":
        fill = take_limit_fill(pos["side"], pos["px"], pos.get("fav"),
                               hi, lo)
        if fill is not None:
            ev["px"] = round(fill[0], 8)
            ev["move_bp"] = round(pos["fav"], 1)
            ev["fill"] = "level"
            ev["thru_px"] = fill[1]
    return ev


def sit_watched(want, root):
    """Каталоги книг, у которых 5-секундный сторож ведёт УРОВНИ.

    Книга «выход по времени» (ось `geom: timer` фабрики) уровней не
    имеет вовсе: ни стопа, ни цели правилу не объявляли, и сторож,
    закрывающий её по уровню, торговал бы не то правило, которое
    судит её реплей. Флаг приходит ЛИСТОМ сечения: состав книг
    объявляет цикл, и второго списка у сканера нет — два места,
    решающих одно, однажды разойдутся.

    Флага нет (книга ядра, лист прежнего образца) — уровни В СИЛЕ:
    умолчание обязано быть прежним поведением, иначе правка молча
    сняла бы сторожа с книг владельца.
    """
    return {os.path.join(root, b.get("dir") or "") for b in want
            if not b.get("no_levels")}


def sit_open_levels(picks, reviews, entries=None):
    """Открытые позиции ситуационной книги с уровнями против.

    Открыта = выбор записан, разбора с её ключом нет. Живой вход,
    ещё не превращённый циклом в строку выбора (`entries`), — тоже
    позиция: сторожить её надо с момента события, а не с ближайшего
    часа. Позиции без цены входа или без обещания хода против
    сторожить нечем — они ждут часового цикла.
    """
    done = set()
    for rv in reviews:
        for r in rv.get("rows") or []:
            done.add((rv.get("arm") or "gbm", rv.get("hour"),
                      r.get("sym"), r.get("side")))
    out = []
    converted = set()
    for pk in picks:
        arm = pk.get("arm") or "gbm"
        for side in ("long", "short"):
            for p in pk.get(side) or []:
                if p.get("at_ts") is not None:
                    converted.add((arm, p.get("sym"), p.get("at_ts")))
                if (arm, pk.get("hour"), p.get("sym"), side) in done:
                    continue
                if not (p.get("px") and p.get("mae") is not None):
                    continue
                out.append({"arm": arm, "hour": pk.get("hour"),
                            "sym": p.get("sym"), "side": side,
                            "px": p["px"], "adv": p["mae"],
                            "fav": p.get("mfe"),
                            # Момент открытия: сторож по нему решает,
                            # годится ли накопленный путь. Путь до
                            # входа — чужой, и уровень им задевать
                            # нельзя.
                            "at_ts": p.get("at_ts")})
    for e in entries or []:
        arm = e.get("arm") or "gbm"
        if (arm, e.get("sym"), e.get("at_ts")) in converted:
            continue
        if (arm, e.get("hour"), e.get("sym"), e.get("side")) in done:
            continue
        if not (e.get("px") and e.get("mae") is not None):
            continue
        out.append({"arm": arm, "hour": e.get("hour"),
                    "sym": e.get("sym"), "side": e.get("side"),
                    "px": e["px"], "adv": e["mae"],
                    "fav": e.get("mfe"), "at_ts": e.get("at_ts")})
    return out


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
    # Проверка ЗДЕСЬ, а не при импорте модуля: `websocket` нужен только
    # запуску сбора, а тесты и разбор записей импортируют этот файл как
    # библиотеку и обязаны работать без него. Но и молчать нельзя:
    # `websocket` импортируется внутри потока шарда, то есть его
    # нехватка проявилась бы тишиной в журнале, а не отказом старта.
    from research.common import pyenv
    pyenv.need("websocket")

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
