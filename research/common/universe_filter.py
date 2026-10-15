"""Не-крипто перпы: единое определение для сборщика и модели.

Решение владельца (A1; подтверждено 2026-08-07): перпы не на
криптоактивы в универсум не входят — у базового актива календарь
биржи, у перпа круглосуточный, и спред несёт календарную компоненту,
которая выглядит сигналом, не будучи им.

Источника четыре, и все нужны:

1. Справочник универсума (`asset_class` в `universe.json`) — снимок A1.
2. Курируемый список листингов ПОСЛЕ снимка: справочник их не знает по
   построению. Список правится руками — как `KEEP_AS_CRYPTO` в A1;
   ошибка в нём стоит одной монеты, а не класса.
3. Правило суффикса `*STOCKUSDT` — площадка сама помечает так часть
   токенизированных акций, и будущие листинги с этой пометкой не должны
   ждать правки списка.
4. Разметка площадки `symbolType` (stock/ETF/commodity/forex) в
   справочнике `instruments.json` — с 15.10 главный источник: список
   отстал от волны листингов на ~60 имён.

Фильтр живёт одним модулем намеренно: сборщик решает, что записывать,
модель — что торговать, и два расходящихся определения «не-крипто»
означали бы, что модель выбирает то, чего сборщик не пишет.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_JSON = os.path.join(os.path.dirname(HERE), "a1_universe",
                             "out", "universe.json")

# Листинги после снимка универсума: токенизированные акции, фонды и
# pre-IPO компании (волна TradFi-перпов лета 2026). Криптоимена той же
# волны (CASHCAT, GRVT, 1000BTT) в список НЕ входят.
NON_CRYPTO_NEW = {
    "AMCUSDT", "AMGNUSDT", "BACUSDT", "BIIBUSDT", "BITOUSDT",
    # Волна августа 2026, найдена владельцем по пропавшему unreal pnl:
    # книга со сроком торговала акциями (Meituan, Xiaomi, Kuaishou,
    # SMIC, Riot, Ouster, KLA, Western Digital, Circle, Samsung), их
    # котировка стоит вне часов биржи, форвард не считался, и сделки
    # «без исхода» запирали кассу. NESA/NCLD/DOS/AEON НЕ добавлены:
    # тождество не установлено, а 12-часовое окно /candles календарную
    # подпись не разрешает — проверить по полной записи на сервере.
    "MEITUANUSDT", "XIAOMIUSDT", "KUAISHOUUSDT", "SMICUSDT",
    "RIOTUSDT", "OUSTUSDT", "KLACUSDT", "WDCUSDT", "CRCLUSDT",
    "SAMSUNGUSDT", "TSMUSDT", "AEHRUSDT",
    # Найден зондом спокойного рынка: ISRG = Intuitive Surgical,
    # тождество тикера точное; 1224 записи за 23 суток против ~5500
    # у крипты — календарная подпись стоящей вне биржи котировки.
    "ISRGUSDT",
    "BRKBUSDT", "CIFRUSDT", "CLSKUSDT", "CXMTUSDT", "EBAYUSDT",
    "GDXUSDT", "GEUSDT", "GIGADEVICEUSDT", "GILDUSDT", "GMESTOCKUSDT",
    "JNJUSDT", "JPMUSDT", "KOUSDT", "MAUSDT", "MINIMAXUSDT", "MOUSDT",
    "NETUSDT", "NVOUSDT", "PEPUSDT", "POPMARTUSDT", "PYPLUSDT",
    "RDDTUSDT", "REGNUSDT", "SHOPUSDT", "SPOTUSDT", "SSPCUSDT",
    "TBTUSDT", "TENCENTUSDT", "TMFUSDT", "UBERUSDT", "UNHUSDT",
    "VRTXSTOCKUSDT", "VUSDT", "WMTUSDT", "XOMUSDT", "ZHIPUUSDT",
}


def reference_non_crypto(universe_path=UNIVERSE_JSON):
    """Не-крипто символы Bybit по справочнику универсума (снимок A1)."""
    try:
        with open(universe_path, encoding="utf-8") as f:
            u = json.load(f)["assets"]
    except (OSError, ValueError, KeyError):
        return set()
    return {v["bybit_symbol"] for v in u.values()
            if v.get("asset_class") != "crypto" and v.get("bybit_symbol")}


INSTRUMENTS_JSON = os.path.join(os.path.dirname(HERE), "a1_universe",
                                "out", "instruments.json")
# Разметка площадки (`symbolType` справочника Bybit), измерено 15.10:
# '' — 501, innovation — 128 (крипта), stock — 213, ETF — 57,
# commodity — 4, forex — 3. Курируемый список отстал на ~60 имён волны
# после 13.08 (AMZU, NAVER, DDOG, MCD, EURUSD …) — правило теперь
# читается с биржи, список остаётся для снятых имён без разметки.
EXCHANGE_NON_CRYPTO_TYPES = frozenset({"stock", "ETF", "commodity", "forex"})


def exchange_non_crypto(instruments_path=INSTRUMENTS_JSON):
    """Не-крипто по разметке площадки (поле `symbol_type` справочника).

    Справочник догоняется суточно (`a1_universe/instruments_refresh.py`);
    у записей до 15.10 поля нет — они ловятся списком и снимком A1.
    """
    try:
        with open(instruments_path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return set()
    return {k for k, v in (d or {}).items()
            if isinstance(v, dict)
            and v.get("symbol_type") in EXCHANGE_NON_CRYPTO_TYPES}


def non_crypto_set(universe_path=UNIVERSE_JSON,
                   instruments_path=INSTRUMENTS_JSON):
    """Полный список известных не-крипто символов."""
    return (reference_non_crypto(universe_path) | set(NON_CRYPTO_NEW)
            | exchange_non_crypto(instruments_path))


def is_non_crypto(sym, ref=None):
    """Является ли символ перпом не на криптоактив.

    `ref` — заранее собранный `non_crypto_set()`: в цикле по сотням
    имён перечитывать справочник на каждый вызов незачем.
    """
    if sym.endswith("STOCKUSDT"):
        return True
    # CSOP — эмитент биржевых фондов (Samsung 2x, SK Hynix 2x, ...):
    # свежие листинги волной, поимённый список отставал бы от каждого
    # нового. Найдено владельцем: CSOPSAMSUNG2L вошёл в книгу.
    if sym.startswith("CSOP"):
        return True
    return sym in (non_crypto_set() if ref is None else ref)
