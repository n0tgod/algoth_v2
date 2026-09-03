#!/usr/bin/env python3
"""
D0 (спека 14) — таблица maintenance margin площадки исполнения.

**Запускается оттуда, где Bybit открыт** (VPS): из песочницы разработки
`api.bybit.com` отвечает 403 CloudFront со страновым блоком — та же
граница, что у сбора funding и комиссий A1.

Зачем. Неравенство безопасности §5 спеки 01 выводит плечо из расстояния
до ликвидации: `liq_distance ≥ SAFETY · worst_leg_move`. Само
`liq_distance` при кросс-марже есть функция средневзвешенной цены входа,
суммарного нотионала и **ставки maintenance margin тира этого нотионала**.
`instruments.json` несёт tick/qty/min-notional и НЕ несёт ни риск-лимитных
тиров, ни MMR — значит без этого сбора §5 считается только по
консервативному плоскому MMR (оценка сверху по забору). Это и есть тот
самый «невоспроизводимый за выходные актив» v1: реальная таблица
maintenance margin.

Что собирает. Для каждого символа универсума — лестницу тиров эндпоинта
`/v5/market/risk-limit` (публичный, ключа не требует): по каждому тиру
верхняя граница нотионала (`riskLimitValue`), ставка maintenance margin
(`maintenanceMargin`), предельное плечо (`maxLeverage`). Из этой лестницы
D1 считает цену ликвидации на любой глубине лестницы доливов.

Оговорка, известная до прогона. Эндпоинт рыночный, но, как и эндпоинт
комиссий A1, по СНЯТЫМ с торгов контрактам может не отдавать ничего —
298 крипто-символов A1 со статусом `Closed` ставок не имели. Значит у
делистнутой ноги MMR, вероятно, не будет, и D1 обязан назначать ей тир
правилом (дорогой тир по обороту), а не брать из данных. Доля символов
без тиров докладывается числом, а не замалчивается.

Запуск:

    python3 bybit_risk_limit.py --symbol BTCUSDT   # смоук на одном
    python3 bybit_risk_limit.py                    # весь универсум

Прогон возобновляемый: символы, уже лежащие в `out/risk_limits.json`,
пропускаются. Только stdlib.
"""

import json
import os
import sys
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
# Кэш ответов — СИБЛИНГ out, а не внутри: публикация коммитит всё под
# `research/*/out`, и полторы тысячи файлов кэша уехали бы в git. Здесь
# они вне этого пути и в историю не попадают.
CACHE = os.path.join(HERE, ".cache_risk")

sys.path.insert(0, RESEARCH)
from common.venue import fetch as _fetch  # noqa: E402

API = "https://api.bybit.com"
CATEGORY = "linear"
WORKERS = 4
PAUSE_S = 0.05
STORE = os.path.join(OUT, "risk_limits.json")


def api_get(path, params, cache_key):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    raw = _fetch(url, CACHE, cache_key=cache_key, user_agent="d0-risklimit/1.0")
    doc = json.loads(raw)
    if doc.get("retCode") != 0:
        raise RuntimeError(
            f"{path}: retCode={doc.get('retCode')} {doc.get('retMsg')}")
    return doc["result"]


def parse_tiers(result):
    """Лестница тиров из ответа эндпоинта, отсортированная по нотионалу.

    Числа приходят строками — переводим в float здесь, чтобы D1 не парсил
    их заново; порядок по верхней границе нотионала, чтобы поиск тира по
    размеру позиции шёл слева направо. Пустой список — законный ответ
    (снятый контракт), и он отличим от дефекта: `rows is None` был бы
    отсутствием ключа, `[]` — известным «тиров нет».
    """
    rows = result.get("list") or []
    tiers = []
    for r in rows:
        tiers.append({
            "id": int(r["id"]),
            "cap": float(r["riskLimitValue"]),      # верх нотионала тира
            "mmr": float(r["maintenanceMargin"]),   # ставка maint. margin
            "imr": float(r.get("initialMargin", 0)),
            "max_leverage": float(r["maxLeverage"]),
        })
    tiers.sort(key=lambda t: t["cap"])
    return tiers


def load_store():
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def universe_symbols():
    with open(os.path.join(OUT, "universe.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    syms = []
    for rec in manifest["assets"].values():
        s = rec.get("bybit_symbol")
        if s:
            syms.append(s)
    return sorted(set(syms))


def collect(symbols, store):
    """Собрать тиры по символам, которых ещё нет в хранилище."""
    todo = [s for s in symbols if s not in store]
    print(f"собрано {len(store)}, осталось {len(todo)} из {len(symbols)}",
          file=sys.stderr, flush=True)
    done = [0]

    def work(sym):
        try:
            res = api_get("/v5/market/risk-limit",
                          {"category": CATEGORY, "symbol": sym},
                          cache_key=f"rl_{sym}")
            tiers = parse_tiers(res)
        except RuntimeError as e:
            # retCode 10001 «symbol is closed or invalid» — снятый контракт:
            # это ОПРЕДЕЛЁННОЕ состояние «тиров нет», записываем как [], а
            # не как сбой. Иначе каждый повтор бьёт все закрытые снова, а
            # покрытие путает «закрыт» с «не собрано». Тот же класс, что
            # закрытые символы у эндпоинта комиссий A1.
            if "10001" in str(e):
                return sym, [], None
            return sym, None, str(e)
        except Exception as e:               # noqa: BLE001
            return sym, None, str(e)
        time.sleep(PAUSE_S)
        return sym, tiers, None

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for sym, tiers, err in ex.map(work, todo):
            done[0] += 1
            if err is not None:
                # Ошибка сети/подписи — не «нет тиров», а сбой; в хранилище
                # не пишем, чтобы возобновление попробовало снова.
                print(f"  ! {sym}: {err}", file=sys.stderr, flush=True)
                continue
            store[sym] = tiers
            if done[0] % 100 == 0:
                print(f"  {done[0]}/{len(todo)}", file=sys.stderr, flush=True)
                _save(store)
    _save(store)
    return store


def _save(store):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, STORE)


def report(store, symbols):
    """Покрытие и распределение MMR базового тира — числом, не словом."""
    have = [s for s in symbols if store.get(s)]
    empty = [s for s in symbols if s in store and not store[s]]
    missing = [s for s in symbols if s not in store]
    base_mmr = Counter()
    for s in have:
        base = store[s][0]["mmr"]          # тир с наименьшим нотионалом
        base_mmr[round(base, 6)] += 1
    lines = []
    lines.append("# D0 — таблица maintenance margin Bybit\n")
    lines.append(f"Символов универсума: {len(symbols)}")
    lines.append(f"С тирами: {len(have)}  ·  пустой ответ (снят с торгов?): "
                 f"{len(empty)}  ·  не собрано: {len(missing)}\n")
    lines.append("## MMR базового тира — сколько символов на ставке\n")
    lines.append("| MMR базового тира | символов |")
    lines.append("|---|--:|")
    for mmr, n in sorted(base_mmr.items()):
        lines.append(f"| {mmr:.4f} | {n} |")
    if empty:
        lines.append(f"\n**Без тиров ({len(empty)}):** "
                     + ", ".join(empty[:40])
                     + (" …" if len(empty) > 40 else ""))
        lines.append("\nЭто ожидаемо для снятых контрактов и означает: D1 "
                     "обязан назначать делистнутой ноге MMR правилом "
                     "(дорогой тир по обороту), а не брать из данных.")
    return "\n".join(lines) + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    symbols = universe_symbols()
    only = None
    for i, a in enumerate(sys.argv):
        if a == "--symbol" and i + 1 < len(sys.argv):
            only = sys.argv[i + 1].upper()
    if only:
        symbols = [only]
    store = load_store()
    store = collect(symbols, store)
    rep = report(store, symbols)
    with open(os.path.join(OUT, "D0-risk-limits.md"), "w",
              encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)


if __name__ == "__main__":
    main()
