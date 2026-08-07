"""Не-крипто перпы: единое определение для сборщика и модели.

Решение владельца (A1; подтверждено 2026-08-07): перпы не на
криптоактивы в универсум не входят — у базового актива календарь
биржи, у перпа круглосуточный, и спред несёт календарную компоненту,
которая выглядит сигналом, не будучи им.

Источника три, и все три нужны:

1. Справочник универсума (`asset_class` в `universe.json`) — снимок A1.
2. Курируемый список листингов ПОСЛЕ снимка: справочник их не знает по
   построению. Список правится руками — как `KEEP_AS_CRYPTO` в A1;
   ошибка в нём стоит одной монеты, а не класса.
3. Правило суффикса `*STOCKUSDT` — площадка сама помечает так часть
   токенизированных акций, и будущие листинги с этой пометкой не должны
   ждать правки списка.

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


def non_crypto_set(universe_path=UNIVERSE_JSON):
    """Полный список известных не-крипто символов."""
    return reference_non_crypto(universe_path) | set(NON_CRYPTO_NEW)


def is_non_crypto(sym, ref=None):
    """Является ли символ перпом не на криптоактив.

    `ref` — заранее собранный `non_crypto_set()`: в цикле по сотням
    имён перечитывать справочник на каждый вызов незачем.
    """
    if sym.endswith("STOCKUSDT"):
        return True
    return sym in (non_crypto_set() if ref is None else ref)
