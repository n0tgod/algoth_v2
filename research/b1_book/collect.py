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
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from book import BANDS, STORE_LADDER, Book, parse_trades                 # noqa: E402
import paper                                              # noqa: E402
import signals                                            # noqa: E402
from signals import RULES_VERSION, Signals                # noqa: E402
from store import Writer, read_hour, read_jsonl            # noqa: E402
from common import universe_filter as UF                   # noqa: E402
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
    # Имена из свежих выборов дописываются до закрытия позиций — обрыв
    # ряда до разбора заморозил бы слот навсегда. Новых выборов на
    # не-крипто нет (фильтр стоит и у модели), так что хвост отпадает
    # сам через горизонт удержания.
    grace = recent_pick_symbols()
    kept = sorted(s for s in got
                  if UF.is_non_crypto(s, ref) and s in grace)
    syms = [s for s in got
            if not UF.is_non_crypto(s, ref) or s in grace]
    log(f"справочник площадки: {len(got)} торгуемых USDT-перпов, "
        f"не-крипто исключено {len(got) - len(syms)}, собираем {len(syms)}"
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

    def bot_status(self):
        """Статус исполнительного ядра (Rust-тень) — из его файла.

        Ядро пишет `status.json` атомарно каждый такт; страница только
        читает. Отсутствие файла — «не запущено», и это не тревога
        (ядро может быть не развёрнуто), а состояние словами. Возраст
        считается ЗДЕСЬ, по часам сервера: у страницы свои часы, и на
        телефоне они уходят.
        """
        p = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                         "bot", "out", "shadow", "status.json")
        try:
            with open(p, encoding="utf-8") as f:
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
        try:
            with open(os.path.join(jdir, "source.txt"),
                      encoding="utf-8") as f:
                base = os.path.basename(f.read().strip())
        except OSError:
            base = ""
        st["book_hz"] = {"model_h1": "h1", "model_h24": "h24",
                         "model_sit": "sit",
                         "model_z": "z"}.get(base, "")
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
        out = self._model_dir_state(os.path.join(s8, "model"))
        # Турнир темпов: книги остальных горизонтов — те же веса, свой
        # срок удержания и свой счёт. Отдаются отдельными ключами, а не
        # подмешаны: смесь двух книг в одной таблице выглядела бы
        # осмысленно и не значила бы ничего.
        books = {}
        for key in (k for k in self.BOOK_DIRS if k != "h4"):
            st = self._model_dir_state(
                os.path.join(s8, f"model_{key}"),
                rr_min=rr_min if key.startswith("sit") else None)
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
                "odd": e.get("odd"), "live_wait": True})
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
        for name, key, keep in (("thoughts.jsonl", "thoughts", 60),
                                ("ic_history.jsonl", "ic", 90),
                                ("picks.jsonl", "picks", 200),
                                ("review.jsonl", "review", 200)):
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
        # Сделки собираются ОДНИМ кодом с отчётами (`s8_loop/trades.py`),
        # а не своим у страницы: выбор и разбор лежат в разных файлах, и
        # соединять их глазами — то же, что не иметь сделок вовсе.
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(HERE),
                                            "s8_loop"))
            import trades as TR
            # Горизонт книги — из её же манифеста: каталог сам говорит,
            # на сколько часов живут его позиции. Иначе часовая книга
            # считалась бы четырёхчасовым сроком — и «открыта» там, где
            # позиция давно закрыта. У ситуационной книги срока нет —
            # закрытия приходят разбором, а путь меряется до предела
            # возраста.
            mman = out.get("manifest") or {}
            sit = bool(mman.get("situational"))
            hold = None if sit else int(mman.get("horizon_h")
                                        or TR.HOLD_H)
            path_h = int(mman.get("max_age_h") or 24) if sit else hold
            # Книги, дописанные пересчётом задним числом. Отдельный
            # файл, потому что историю выборов правит только цикл.
            tr = TR.build(out.get("picks"), out.get("review"),
                          hold_h=hold,
                          px_at=self.entry_px(out.get("picks")),
                          books=TR.load_books(
                              os.path.join(mdir, "books.jsonl")))
            TR.mark(tr, self.marks(tr))
            hrows = self.paths(tr, hold_h=path_h)
            # Живые события сборщика (вход в моменте, выход по
            # уровню) накладываются на историю ОДНОЙ функцией — её же
            # зовёт страница сделок. Два наложения однажды разошлись
            # бы, и обзор показывал бы сделки, которых нет в истории;
            # ровно это владелец и увидел: двенадцать позиций на
            # обзоре против пустой истории.
            if sit:
                self.live_overlay(mdir, tr, out.get("review"))
            # Фильтр владельца по обещанному отношению: показ и СЧЁТ
            # считаются по отобранному подмножеству одним и тем же
            # ядром. Отфильтрованная кривая — это «что было бы, если
            # брать только такие сделки», а не деньги книги, и страница
            # обязана сказать это словами: числа сами по себе выглядят
            # как результат книги.
            tr, cut, unknown = TR.by_rr(tr, rr_min)
            out["rr_min"] = rr_min or 0
            out["rr_cut"] = cut
            out["rr_unknown"] = unknown
            out["trades"] = tr[:300]
            out["trades_total"] = len(tr)
            cap, st, curves = {}, {}, {}
            for a in ("gbm", "nn"):
                # Капитал берётся из ПЕРЕСЧЁТА, а не из файла счёта.
                # Файл пишет цикл при разборе, то есть у свежей книги
                # его ещё нет — и экспозиция оставалась без знаменателя,
                # превращаясь в голое «500 $». Владелец прочитал это как
                # «депозит стал 500». Пересчёт есть всегда и совпадает с
                # тем, что показано в таблице, потому что считается по
                # тем же сделкам.
                cap[a] = TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                                    slots=mman.get("slots"))[1]
                TR.dd_money(tr)
                st[a] = TR.summary(tr, a, capital=cap[a])
                cur = TR.equity(tr, a, hrows, hold_h=path_h)
                st[a]["dd_book"] = TR.max_dd(cur)
                st[a]["dd_open_book"] = TR.worst_open(cur)
                curves[a] = cur
            # Общая сводка по книге: на вкладке «обе» владельцу нужен
            # ИТОГ, а не две колонки, между которыми надо складывать
            # глазами. Капитал складывается — у каждой руки свой счёт
            # по тысяче, и делить прибыль двух счетов на один значило
            # бы завышать доходность вдвое.
            both_cap = sum(v for v in cap.values() if v) or None
            st["all"] = TR.summary(tr, capital=both_cap,
                                   start=2 * TR.START_BALANCE)
            both_curve = TR.merge(curves.values())
            st["all"]["dd_book"] = TR.max_dd(both_curve)
            st["all"]["dd_open_book"] = TR.worst_open(
                both_curve, deposit=2 * TR.START_BALANCE)
            out["trade_stats"] = st
        except Exception as e:                            # noqa: BLE001
            out["trades_error"] = f"{type(e).__name__}: {e}"
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
        name = self.BOOK_DIRS.get(hz) or "model"
        # Та же развилка, что у обзора, и тем же правилом: ниже гейта
        # торгуемой книги ответить может только наблюдательная запись.
        # Считается ДО чтения файлов — иначе страница сделок и обзор
        # показывали бы под одним порогом разные книги.
        src_book = "traded"
        if hz == "sit":
            try:
                with open(os.path.join(s8, "model_sit", "manifest.json"),
                          encoding="utf-8") as f:
                    gate = (json.load(f) or {}).get("min_rr")
            except (OSError, ValueError):
                gate = None
            src_book = self.sit_source(rr_min, gate)
            if src_book == "observation":
                name = "model_sit_obs"
        mdir = os.path.join(s8, name)
        try:
            with open(os.path.join(mdir, "manifest.json"),
                      encoding="utf-8") as f:
                mman = json.load(f)
        except (OSError, ValueError):
            mman = {}
        sit = bool(mman.get("situational"))
        hold = None if sit else int(mman.get("horizon_h") or TR.HOLD_H)
        path_h = int(mman.get("max_age_h") or 24) if sit else hold
        picks = self._jsonl(os.path.join(mdir, "picks.jsonl"))
        revs = self._jsonl(os.path.join(mdir, "review.jsonl"))
        tr = TR.build(picks, revs, hold_h=hold,
                      px_at=self.entry_px(picks),
                      books=TR.load_books(
                          os.path.join(mdir, "books.jsonl")))
        TR.mark(tr, self.marks(tr))
        # Живые события — той же функцией, что у обзора. Без неё
        # история читала голые `picks.jsonl` и молчала о позициях,
        # открытых сканером после последнего цикла: обзор показывал
        # двенадцать сделок, история — ноль.
        if sit:
            self.live_overlay(mdir, tr, revs)
        # Порог обещанного отношения — только у книги без срока: у
        # часовых обещания пути не решают ни входа, ни выхода.
        tr, rr_cut, rr_unknown = TR.by_rr(tr, rr_min if sit else None)
        accs, cap = {}, {}
        for a in ("gbm", "nn"):
            try:
                with open(os.path.join(mdir, f"account_{a}.json"),
                          encoding="utf-8") as f:
                    accs[a] = json.load(f)
            except (OSError, ValueError):
                pass
            # Размеры позиций проставляет счёт — он единственный, кто
            # знает капитал и занятость. Сводка их только складывает.
            #
            # Капитал берётся отсюда же, из пересчёта, а НЕ из файла:
            # файл пишет цикл при разборе, у свежей книги его ещё нет, и
            # экспозиция оставалась без знаменателя — голое «500 $»
            # читается как «депозит стал 500». Пересчёт есть всегда и
            # согласован с показанными сделками по построению.
            cap[a] = TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                                slots=mman.get("slots"))[1]

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
                    "rr_min": rr_min or 0, "rr_cut": rr_cut,
                    "lite": True, "start": TR.START_BALANCE,
                    "page": g, "per": p, "total": len(rows),
                    "pages": max(1, (len(rows) + p - 1) // p),
                    "filtered": bool(arm or state or sym),
                    "grand_total": len(tr),
                    "rows": rows[g * p:(g + 1) * p]}
        hrows = self.paths(tr, hold_h=path_h)
        # Капитал у каждой руки свой — по тысяче. На вкладке «обе»
        # капитал складывается: иначе экспозиция 1504 $ читалась бы как
        # полтора плеча, хотя капитала там две тысячи.
        # Деньги просадки — после счёта: размер позиции знает только он.
        TR.dd_money(tr)
        # `start` — знаменатель для долей по сторонам: депозит на
        # старте, а не нынешний капитал. У «обеих» он двойной, как и у
        # просадки ниже: иначе прибыль двух счетов делилась бы на один.
        stats = {a: TR.summary(tr, a, capital=cap[a],
                               start=TR.START_BALANCE)
                 for a in ("gbm", "nn")}
        both = sum(v for v in cap.values() if v) or None
        stats["all"] = TR.summary(tr, capital=both,
                                  start=2 * TR.START_BALANCE)
        # Просадка счёта считается по кривой с переоценкой открытых, а
        # не по одним закрытиям: позиция, уходившая в минус и
        # вернувшаяся, в кривой закрытий выглядит мелким убытком, и
        # пережитая просадка из неё не видна вовсе.
        curves = {a: TR.equity(tr, a, hrows, hold_h=path_h)
                  for a in ("gbm", "nn")}
        for a in ("gbm", "nn"):
            stats[a]["dd_book"] = TR.max_dd(curves[a])
            stats[a]["dd_open_book"] = TR.worst_open(curves[a])
        both_c = TR.merge(curves.values())
        stats["all"]["dd_book"] = TR.max_dd(both_c)
        # На общей вкладке знаменателем служит сумма депозитов: иначе
        # просадка двух счетов делилась бы на один и выходила вдвое.
        stats["all"]["dd_open_book"] = TR.worst_open(
            both_c, deposit=2 * TR.START_BALANCE)
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
                "min_disc_bp": mman.get("min_disc_bp"),
                # Порог владельца и его цена в сделках: без этих чисел
                # отфильтрованный счёт неотличим от счёта книги.
                "rr_min": rr_min or 0, "rr_cut": rr_cut,
                "rr_unknown": rr_unknown,
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
    BOOK_DIRS = {"h4": "model", "h1": "model_h1", "h24": "model_h24",
                 "sit": "model_sit", "sit_obs": "model_sit_obs",
                 "z": "model_z"}
    # Торгуемые: наблюдательная запись повторяет входы торгуемой, и в
    # счётах по книгам её быть не должно.
    BOOKS = (("h4", "model"), ("h1", "model_h1"),
             ("h24", "model_h24"), ("sit", "model_sit"),
             ("z", "model_z"))

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
    }
    BOOK_TREE = {
        "h4": {
            "title": "4-hour book — the main one",
            "title_ru": "Книга 4 часа — главная",
            "plain": "Every hour takes the most extreme forecasts of "
                     "the 4-hour horizon — six names long, six short — "
                     "and holds exactly four hours. Tests the core "
                     "question of hypothesis 6: does ranking the "
                     "cross-section make money at all.",
            "plain_ru": "Каждый час берёт самые крайние прогнозы "
                        "четырёхчасового горизонта — шесть имён в лонг "
                        "и шесть в шорт — и держит ровно четыре часа. "
                        "Проверяет главный вопрос гипотезы 6: "
                        "зарабатывает ли само ранжирование сечения."},
        "h1": {
            "title": "1-hour book — does speed pay",
            "title_ru": "Книга 1 час — окупается ли скорость",
            "plain": "The same picking at an hourly pace: more trades, "
                     "but every hour pays the full cost round. Tests "
                     "whether speed covers the fee; by R4/R5 the fee "
                     "eats fast books, so tempos are compared fairly "
                     "by IC and hit rate, not by money.",
            "plain_ru": "Тот же выбор на часовом темпе: сделок больше, "
                        "но каждый час платит полный круг издержек. "
                        "Проверяет, окупает ли скорость комиссию; по "
                        "замерам R4/R5 частота съедает деньги, поэтому "
                        "темпы честно сравнивать по IC и точности, а "
                        "не по деньгам."},
        "h24": {
            "title": "24-hour book — does the signal live a day",
            "title_ru": "Книга 24 часа — живёт ли сигнал сутки",
            "plain": "The daily pace: fewer trades, less fee, longer "
                     "in risk. Tests the slow end — whether the "
                     "forecast survives a full day of holding.",
            "plain_ru": "Суточный темп: сделок меньше, комиссии "
                        "меньше, в риске дольше. Проверяет медленный "
                        "край — доживает ли прогноз до конца суток "
                        "удержания."},
        "z": {
            "title": "per-σ book — were we just picking volatility",
            "title_ru": "Книга per σ — не волатильность ли мы отбирали",
            "plain": "Same section, same trade geometry; exactly one "
                     "thing differs — the ordering: the forecast is "
                     "divided by the coin’s own volatility. Tests "
                     "whether the main book’s picking was volatility "
                     "in disguise (measured: the picked coin ranges "
                     "6× the market that same hour).",
            "plain_ru": "То же сечение и та же геометрия сделки; "
                        "отличается ровно одно — порядок: прогноз "
                        "делится на собственную волатильность монеты. "
                        "Проверяет, не был ли отбор главной книги "
                        "переодетым отбором по волатильности (замер: "
                        "выбранная монета вшестеро волатильнее рынка "
                        "в тот же час)."},
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
                     "entries cannot. The Rust core shadows this book.",
            "plain_ru": "Модель рисует карту, курок спускает живая "
                        "цена: вход только когда цена даёт скидку к "
                        "прогнозу листа и пересекает гейт у нас на "
                        "глазах. Стоп — выученный квантильный уровень "
                        "(заход ~20 %), тейк — обещанный ход в пользу, "
                        "плюс предел возраста. Проверяет, даёт ли "
                        "выбор момента то, чего не даёт вход по "
                        "расписанию. Эту книгу ведёт тень Rust-ядра."},
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

    def closed_rows(self):
        """Закрытые сделки всех торгуемых книг — с деньгами.

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
        for hz, name in self.BOOKS:
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
                hold = None if sit else int(mman.get("horizon_h")
                                            or TR.HOLD_H)
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
                               slots=mman.get("slots"))
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

    def _league_from(self, rows, errors, scanned, now):
        """Агрегаты лиги из готовых строк — арифметика без чтения."""

        def agg(sub, key):
            out = {}
            for r in sub:
                k = key(r)
                if k is None:
                    continue
                g = out.setdefault(k, {"n": 0, "w": 0, "pnl": 0.0,
                                       "net": 0.0})
                g["n"] += 1
                g["w"] += 1 if (r["pnl"] or 0) > 0 else 0
                g["pnl"] += r["pnl"] or 0.0
                g["net"] += r["net_bp"] or 0.0
            return sorted(
                [{"key": k, "n": g["n"],
                  "win": round(g["w"] / g["n"], 3),
                  "pnl": round(g["pnl"], 2),
                  "net_bp_avg": round(g["net"] / g["n"], 1)}
                 for k, g in out.items()],
                key=lambda x: -x["pnl"])

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
                    "side": agg(sub, lambda r: r["side"]),
                },
                "best": srt[:10],
                "worst": srt[::-1][:5],
                "setup_known": sum(1 for r in sub if r["setup"]),
            }
        out = {"present": bool(rows), "closed_total": len(rows),
               "periods": periods,
               "books": scanned, "errors": errors,
               "generated_at": round(now, 1)}
        self._league_cache = (now, out)
        return out

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
        rel, own_bp = [], []
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
        pick = None
        if rel:
            pick = {"n": len(rel),
                    "rel_med": round(_median(rel), 2),
                    "above": round(sum(1 for x in rel if x > 1.0)
                                   / len(rel), 3),
                    "own_med_bp": round(_median(own_bp), 1)}

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
            row.update(key=key, dir=name)
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
                if man.get("min_rr") is not None:
                    facts.append(f"RR ≥ {man['min_rr']:g}")
                if man.get("min_disc_bp") is not None:
                    facts.append(f"disc {man['min_disc_bp']:g} bp")
                if man.get("stop_tau") is not None:
                    facts.append(f"stop τ {man['stop_tau']:g}")
                if man.get("max_age_h"):
                    facts.append(f"age ≤ {man['max_age_h']} h")
            elif man:
                # Манифест главной книги старше турнира темпов и
                # `horizon_h` не несёт; срок у неё тот, что берёт
                # касса по умолчанию (`TR.HOLD_H`) — печатать пустую
                # строку правил значило бы показать книгу без срока.
                facts.append(
                    f"hold {man.get('horizon_h') or TR.HOLD_H} h")
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
        out = {"roots": [dict(self.ROOT_TREE["gbm"], arm="gbm"),
                         dict(self.ROOT_TREE["nn"], arm="nn")],
               "books": books, "tournament": tourney,
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

    def model_marks(self):
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
        name = "model"
        mdir = os.path.join(s8, name)
        pk = self._jsonl(os.path.join(mdir, "picks.jsonl"))
        tr = TR.build(pk, self._jsonl(os.path.join(mdir,
                                                   "review.jsonl")),
                      px_at=self.entry_px(pk),
                      books=TR.load_books(
                          os.path.join(mdir, "books.jsonl")))
        for a in ("gbm", "nn"):
            TR.account(tr, a)
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

    @staticmethod
    def _jsonl(path):
        out = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            pass
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
                            "model_sit")
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
                if now - pos_at > 60:
                    for d, stt in books.items():
                        stt["pos"] = sit_open_levels(
                            self._jsonl(os.path.join(d, "picks.jsonl")),
                            self._jsonl(os.path.join(d, "review.jsonl")),
                            self._jsonl(os.path.join(
                                d, "entries_live.jsonl")))
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
                        move, hit = sit_cross(p["side"], p["px"],
                                              p["adv"],
                                              (bid + ask) / 2.0,
                                              p.get("fav"),
                                              hi=eh, lo=el)
                        if not hit:
                            continue
                        ev = {"arm": p["arm"], "hour": p["hour"],
                              "sym": p["sym"], "side": p["side"],
                              "px": round((bid + ask) / 2.0, 8),
                              "move_bp": round(move, 1),
                              "at_ts": round(now, 3),
                              "reason": (
                                  "цена прошла обещанный ход против"
                                  if hit == "против"
                                  else "цена дошла до обещанной цели")}
                        os.makedirs(d, exist_ok=True)
                        with open(os.path.join(d, "exits_live.jsonl"),
                                  "a", encoding="utf-8") as f:
                            f.write(json.dumps(ev, ensure_ascii=False)
                                    + "\n")
                        stt["signalled"].add(key)
                        if d == base:
                            self.log(
                                f"ситуационная: {p['sym']} "
                                f"{'дошла до цели' if hit == 'в пользу' else 'прошла обещанный ход против'}"
                                f" ({move:+.0f} б.п.) — выход замечен "
                                f"живьём")
            except Exception as e:                        # noqa: BLE001
                self.log(f"сторож ситуационной книги: "
                         f"{type(e).__name__}: {e}")

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
        hour = sheet.get("hour")
        # Гейт по отношению у сканера снимается: его применяет КНИГА,
        # каждая своим порогом. Само событие входа от этого не
        # меняется — меняется, кто его к себе записывает.
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
                free[d] = (int(b.get("slots") or 6) - len(held), held,
                           float(b.get("min_rr") or 0.0), stt)
            for r in rows:
                sym = r.get("sym")
                mid = mids.get(sym)
                if not mid:
                    continue
                # Гейт без отношения: RR проверяет книга.
                got = sit_scan_entry(r, mid, wave, min_edge, 0.0,
                                     min_disc)
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
                                          min_disc - band):
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
                for d, (n_free, held, min_rr, stt) in list(free.items()):
                    if n_free <= 0 or sym in held:
                        continue
                    if key in stt["entered"]:
                        continue
                    if got["rr"] < min_rr:
                        continue
                    ev = {"arm": arm, "hour": hour,
                          "at_ts": round(now, 3),
                          "reason": "вход по ситуации", **got}
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
                    free[d] = (n_free - 1, held, min_rr, stt)
                    # Свежий вход сторожится с этой же секунды, не
                    # дожидаясь перечитывания файлов.
                    stt["pos"].append({
                        "arm": arm, "hour": hour, "sym": sym,
                        "side": got["side"], "px": got["px"],
                        "adv": got["mae"], "fav": got["mfe"]})
                    took = True
                if took:
                    armed.discard(key)
                    self.log(
                        f"ситуационная [{arm}]: живой вход {sym} "
                        f"{got['side']} (остаток {got['fwd']:+.0f} б.п. "
                        f"против {got['fwd0']:+.0f} у листа, скидка "
                        f"{abs(got['fwd']) - abs(got['fwd0']):+.0f}, RR "
                        f"{got['rr']}) — поймано в моменте")


    def run(self, hours):
        deadline = self.started + hours * 3600 if hours else None
        threading.Thread(target=self.metrics_poll, daemon=True).start()
        threading.Thread(target=self.sampler, daemon=True).start()
        threading.Thread(target=self.statuser, daemon=True).start()
        threading.Thread(target=self.reporter, daemon=True).start()
        threading.Thread(target=self.diskstat, daemon=True).start()
        threading.Thread(target=self.sit_watch, daemon=True).start()
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


def sit_scan_entry(row, mid, wave_bp, min_edge, min_rr, min_disc):
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
    """
    px0 = row.get("px")
    fwd0 = row.get("fwd")
    if not px0 or not mid or fwd0 is None:
        return None
    move = (mid / px0 - 1.0) * 1e4
    resid = move - (row.get("beta") if row.get("beta") is not None
                    else 1.0) * wave_bp
    rem = fwd0 - resid
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
    d = {"sym": row.get("sym"), "side": side, "px": round(mid, 8),
         "move_bp": round(move, 1), "wave_bp": round(wave_bp, 1),
         "fwd": round(rem, 1), "fwd0": fwd0,
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

    Срабатывание решает ПУТЬ, а цена выхода берётся из `mid` — то
    есть оттуда, где мы можем торговать, когда заметили. Считать
    исполнение по самому уровню значило бы дарить себе цену, которой
    в момент нашего решения уже нет: фитиль вернулся, и продать по
    его дну нельзя. Это тот же принцип, что «не предполагать
    исполнение лимитной заявки по касанию» (ошибка движка v1).
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
