#!/usr/bin/env python3
"""
A1 — универсум площадки исполнения на момент времени.

Спецификация 02, разделы 2.1 и 2.1.1. Отвечает на один вопрос:
**какие инструменты торговались на Bybit в заданный день и какая история у них
была к тому моменту** — независимо от того, существуют ли они сегодня.

Зачем отдельно от A0. A0 сохранил по каждому символу только первую дату,
последнюю и число доступных дней. Этого мало: у 11 символов внутри срока
жизни есть разрывы, и это не мелочь — LUNA, UST, ANC (крах Terra),
FTT (крах FTX), BTT, KEEP, GST. То есть «торговался с X по Y» неверно:
инструмент останавливали, возобновляли и хоронили. Универсум, построенный
по паре (первая дата, последняя дата), молча включит в торговое окно дни,
когда инструмента не существовало.

Источник — листинг директорий публичного архива Bybit: файл за день лежит
там тогда и только тогда, когда в этот день были сделки. Справочник
инструментов API v5 для этого не годится даже при наличии доступа: он
описывает сегодняшнее состояние и о делистнутых инструментах молчит.

Только stdlib. Сетевые ответы кэшируются — повторный запуск дешёвый.
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")
A0_OUT = os.path.join(RESEARCH, "a0_venue_inventory", "out")

sys.path.insert(0, RESEARCH)
from common.venue import fetch as _fetch  # noqa: E402

BYBIT_ARCHIVE = "https://public.bybit.com/trading/"
WORKERS = 8

# Инструмент считаем прекратившим торговаться, если последний день архива
# старше этого зазора от даты его среза. Зазор нужен, потому что архив
# выкладывается с задержкой и «вчера ещё нет файла» не означает делистинг.
DELIST_GAP_DAYS = 7

# Расчётный день при делистинге. У девяти инструментов последний файл архива
# отстоит от конца реальной торговли на 26–348 дней и содержит ровно один день:
# биржа закрывает позиции по расчётной цене уже после остановки торгов.
# Взять его за дату делистинга — значит считать инструмент торгуемым всё это
# время: у BTT торговля кончилась 2021-12-28, а последний файл датирован
# 2022-12-12, почти годом позже.
#
# Пороги разделяют данные без произвола: у всех девяти артефактов длина
# хвоста ровно 1 день, а ближайший настоящий хвост — 12 дней. Настоящие
# возобновления торгов (FHE — 201 день после паузы в 77) остаются на месте.
SETTLEMENT_MAX_LEN_DAYS = 1
SETTLEMENT_MIN_GAP_DAYS = 7

# Перпы не на криптоактивы. Bybit торгует акции (AAPL, NVDA, TSLA), биржевые
# фонды (SPY, QQQ, SOXX), фонды с плечом и обратные (TQQQ, SQQQ, SOXL, TZA),
# металлы (XAU, XAG) и сырьё (CL, BZ). Из универсума они исключены решением
# владельца, и причина не в том, что «это не крипта»:
#
#   - базовый актив стоит в выходные, а перп торгуется круглосуточно, поэтому
#     цена держится ожиданием. У спреда появляется календарная компонента,
#     которая проходит тест на коинтеграцию, не будучи возвратом к среднему;
#   - у фондов с плечом сверх того собственный распад — структурный дрейф,
#     а не стационарность.
#
# То есть такие пары попадут в отбор по причинам, не имеющим отношения к
# гипотезе, и съедят квоту ложных открытий раздела 3.3 спеки 02.
#
# Признак — ставка комиссии: у этого класса тейкер 2.75 б.п. против 5.5 у
# основной массы. Признак точный, но это **признак, а не определение**,
# поэтому исключения ведутся явным списком.
#
# Инструменты не удаляются, а помечаются: решение обратимо, а перпы на акции
# и металлы остаются законной, просто **другой** гипотезой (см. `IDEAS.md`).
NON_CRYPTO_TAKER_BP = 2.75
KEEP_AS_CRYPTO = {
    "PURR",   # мемкоин экосистемы Hyperliquid, на дешёвом тарифе по иной причине
}

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.csv\.gz")


def fetch(url, cache_key=None):
    return _fetch(url, CACHE, cache_key=cache_key, user_agent="a1-universe/1.0")


def trading_days(symbol):
    """Множество дней, за которые в архиве Bybit есть сделки по символу."""
    try:
        html = fetch(BYBIT_ARCHIVE + symbol + "/", cache_key="bybit_sym_" + symbol)
    except Exception:
        return []
    return sorted({date.fromisoformat(d) for d in DATE_RE.findall(html)})


def to_intervals(days):
    """Отсортированные даты -> непрерывные интервалы [(начало, конец), ...]."""
    if not days:
        return []
    out = []
    start = prev = days[0]
    for d in days[1:]:
        if (d - prev).days == 1:
            prev = d
            continue
        out.append((start, prev))
        start = prev = d
    out.append((start, prev))
    return out


def split_settlement(intervals):
    """Отделить расчётные дни делистинга от интервалов реальной торговли.

    Возвращает (интервалы торговли, расчётные дни). Отрезается только хвост:
    изолированный короткий интервал в конце, отстоящий от торговли разрывом.
    """
    iv = list(intervals)
    settlement = []
    while len(iv) >= 2:
        start, end = iv[-1]
        prev_end = iv[-2][1]
        length = (end - start).days + 1
        gap = (start - prev_end).days - 1
        if length <= SETTLEMENT_MAX_LEN_DAYS and gap >= SETTLEMENT_MIN_GAP_DAYS:
            settlement.insert(0, iv.pop())
        else:
            break
    return iv, [d for d, _ in settlement]


def collect(symbols):
    """Собрать интервалы торговли по каждому символу."""
    result = {}
    done = [0]

    def work(sym):
        days = trading_days(sym)
        done[0] += 1
        if done[0] % 100 == 0:
            print(f"  bybit {done[0]}/{len(symbols)}", file=sys.stderr, flush=True)
        return sym, days

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for sym, days in ex.map(work, symbols):
            if days:
                result[sym] = days
    return result


def build(days_by_symbol, a0_bybit, a0_binance):
    """Свести интервалы и данные A0 в манифест универсума."""
    archive_as_of = max(d[-1] for d in days_by_symbol.values())
    delist_before = archive_as_of - timedelta(days=DELIST_GAP_DAYS)

    # Binance: базовый актив -> символ с самой длинной историей.
    # Один актив иногда представлен несколькими символами (смена множителя),
    # длинная история важнее совпадения тикера.
    bn_by_base = {}
    for rec in a0_binance.values():
        if rec.get("quote") != "USDT":
            continue
        cur = bn_by_base.get(rec["base"])
        if cur is None or rec["first_month"] < cur["first_month"]:
            bn_by_base[rec["base"]] = rec

    entries = {}
    for sym, days in sorted(days_by_symbol.items()):
        meta = a0_bybit.get(sym, {})
        if meta.get("quote") != "USDT":
            continue
        base = meta["base"]
        iv, settlement = split_settlement(to_intervals(days))
        listed = iv[0][0]
        last = iv[-1][1]
        traded = sum((b - a).days + 1 for a, b in iv)
        span = (last - listed).days + 1
        bn = bn_by_base.get(base)

        rec = {
            "base": base,
            "bybit_symbol": sym,
            "multiplier": meta.get("multiplier", 1),
            "listed": listed.isoformat(),
            "last_trading_day": last.isoformat(),
            "settlement_days": [d.isoformat() for d in settlement],
            "trading_days": traded,
            "calendar_span_days": span,
            "gap_days": span - traded,
            "intervals": [[a.isoformat(), b.isoformat()] for a, b in iv],
            "delisted": last < delist_before,
            "binance_symbol": bn["symbol"] if bn else None,
            "binance_first_month": bn["first_month"] if bn else None,
            "binance_last_month": bn["last_month"] if bn else None,
        }

        # Один базовый актив может иметь несколько символов Bybit
        # (например смена множителя). Берём с самой ранней историей;
        # остальные сохраняем, чтобы ничего не потерялось молча.
        prev = entries.get(base)
        if prev is None:
            entries[base] = rec
        elif rec["listed"] < prev["listed"]:
            rec["also_symbols"] = sorted(prev.get("also_symbols", []) + [prev["bybit_symbol"]])
            entries[base] = rec
        else:
            prev.setdefault("also_symbols", [])
            prev["also_symbols"] = sorted(set(prev["also_symbols"] + [sym]))

    return {
        "archive_as_of": archive_as_of.isoformat(),
        "delist_gap_days": DELIST_GAP_DAYS,
        "assets": entries,
    }


# ------------------------------------------------------- запрос на момент времени

def _parse_intervals(rec):
    return [
        (date.fromisoformat(a), date.fromisoformat(b))
        for a, b in rec["intervals"]
    ]


def tradable_on(rec, day):
    """Торговался ли инструмент на площадке исполнения в этот день."""
    return any(a <= day <= b for a, b in _parse_intervals(rec))


def history_days_by(rec, day):
    """Сколько дней с фактическими сделками на площадке исполнения к этому дню."""
    total = 0
    for a, b in _parse_intervals(rec):
        if b < day:
            total += (b - a).days + 1
        elif a <= day:
            total += (day - a).days + 1
    return total


def binance_history_days_by(rec, day):
    """Длина ряда Binance к этому дню. Гранулярность архива — месяц."""
    fm = rec.get("binance_first_month")
    if not fm:
        return 0
    return max(0, (day - date(int(fm[:4]), int(fm[5:7]), 1)).days)


def estimation_history_days_by(rec, day):
    """История, доступная для оценки β, μ, σ и периода полураспада.

    Спецификация 02, раздел 2.2: где история площадки исполнения короче,
    отношение оценивается по ряду Binance. Обратное тоже встречается —
    часть активов Bybit листинговал раньше Binance, — поэтому ни один
    источник по отдельности не годится, берётся более длинный.
    """
    return max(history_days_by(rec, day), binance_history_days_by(rec, day))


def classify_asset_class(manifest, fees):
    """Проставить `asset_class` по ставке комиссии. Сеть не нужна.

    Возвращает число размеченных как некриптоактивы. Символы, для которых
    площадка ставку не отдала (делистнутые — эндпоинт отвечает по текущему
    состоянию счёта), остаются `crypto`: у них нет признака, а исключать
    по умолчанию нельзя, иначе из универсума молча выпадет ровно та часть,
    ради которой он строится на момент времени.
    """
    rate = {f["symbol"]: float(f["takerFeeRate"]) * 1e4 for f in fees}
    n = 0
    for base, rec in manifest["assets"].items():
        taker = rate.get(rec["bybit_symbol"])
        non_crypto = (
            taker is not None
            and abs(taker - NON_CRYPTO_TAKER_BP) < 1e-9
            and base not in KEEP_AS_CRYPTO
        )
        rec["asset_class"] = "non_crypto" if non_crypto else "crypto"
        rec["taker_fee_bp"] = taker
        n += non_crypto
    return n


def universe_at(manifest, day, min_history_days=0, require_binance=True,
                include_non_crypto=False):
    """Универсум на момент времени — реализация требования раздела 2.1.1.

    Существует ли инструмент сегодня, на отбор не влияет. Условия ровно два:
    торговался на площадке исполнения в этот день и накопил к тому моменту
    достаточную для оценки историю.
    """
    out = []
    for base, rec in manifest["assets"].items():
        if require_binance and not rec["binance_symbol"]:
            continue
        if not include_non_crypto and rec.get("asset_class") == "non_crypto":
            continue
        if not tradable_on(rec, day):
            continue
        if estimation_history_days_by(rec, day) < min_history_days:
            continue
        out.append(base)
    return sorted(out)


def _load_fees():
    path = os.path.join(OUT, "fees.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def reclassify_stored():
    """Разметить классы активов в уже собранном манифесте, без сети.

    Полный пересбор ходил бы в архив Bybit заново и сдвинул бы дату среза,
    а с ней все числа отчётов. Разметка от даты среза не зависит, поэтому
    делается отдельным проходом — как `--renormalize` на этапе A0.
    """
    path = os.path.join(OUT, "universe.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала обычный прогон")
    fees = _load_fees()
    if fees is None:
        raise SystemExit("нет out/fees.json — соберите bybit_api.py --with-fees")

    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    n = classify_asset_class(manifest, fees)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)

    assets = manifest["assets"]
    with_bnc = [r for r in assets.values() if r["binance_symbol"]]
    dropped = [r for r in with_bnc if r["asset_class"] == "non_crypto"]
    print(json.dumps({
        "assets": len(assets),
        "non_crypto": n,
        "kept_by_exception": sorted(KEEP_AS_CRYPTO),
        "with_binance_before": len(with_bnc),
        "with_binance_after": len(with_bnc) - len(dropped),
    }, ensure_ascii=False, indent=2))


def main():
    if "--classify" in sys.argv:
        reclassify_stored()
        return

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    with open(os.path.join(A0_OUT, "bybit.json"), encoding="utf-8") as f:
        a0_bybit = json.load(f)
    with open(os.path.join(A0_OUT, "binance.json"), encoding="utf-8") as f:
        a0_binance = json.load(f)

    symbols = sorted(s for s, v in a0_bybit.items() if v.get("quote") == "USDT")
    print(f"USDT-перпов Bybit по данным A0: {len(symbols)}", file=sys.stderr, flush=True)

    days_by_symbol = collect(symbols)
    print(f"с непустым архивом: {len(days_by_symbol)}", file=sys.stderr, flush=True)

    manifest = build(days_by_symbol, a0_bybit, a0_binance)
    fees = _load_fees()
    if fees:
        classify_asset_class(manifest, fees)
    path = os.path.join(OUT, "universe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)

    assets = manifest["assets"]
    print(json.dumps({
        "archive_as_of": manifest["archive_as_of"],
        "assets": len(assets),
        "delisted": sum(1 for r in assets.values() if r["delisted"]),
        "with_binance": sum(1 for r in assets.values() if r["binance_symbol"]),
        "with_gaps": sum(1 for r in assets.values() if r["gap_days"] > 0),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
