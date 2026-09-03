#!/usr/bin/env python3
"""
Инвентарь опционов площадки исполнения — выпуклый инструмент, есть ли он.

**Запускается оттуда, где Bybit открыт** (VPS): из песочницы разработки
`api.bybit.com` отвечает 403 CloudFront со страновым блоком — та же
граница, что у сбора funding, комиссий A1 и тиров D0.

Зачем. Три хеджа лонг-DCA закрыты замерами D2 (шорт той же монеты,
бета-хедж рынком, отдельная шорт-книга), и арифметика объяснила их разом:
у книги ликвидаций 0.06 % — около пяти позиций из 8670, весь хвост стоит
≈520 п.п., а бета-хедж стоил ≈24 970 п.п. **Линейный хедж облагает все
сделки ради страховки от нескольких.** Инструмент, у которого такой
арифметики нет, ровно один — ВЫПУКЛЫЙ: премия мала в обычное время и
платит только в хвосте. На перпах это опцион (пут под лонг).

Что собирает. Список базовых активов, на которые площадка вообще
котирует опционы, число живых контрактов и границы экспираций. Это не
модель хеджа и не цена премии — это ответ на предшествующий им вопрос:
существует ли инструмент на тех именах, где сидит наш хвост. Если хвост
живёт в альтах, а опционы только на мажоры, направление закрыто до
всякой калибровки — тем же приёмом «сначала самая дешёвая оценка,
способная убить направление», что потолок рычагов S1.

Порядок обхода — и почему он такой. Первый прогон (2026-09-03) сделал
один запрос без `baseCoin`, получил 770 строк и объявил: базовый актив с
опционами РОВНО ОДИН, BTC. Ответ выглядел исправным и был неверен:
эндпоинт без `baseCoin` подставляет умолчание, то есть отвечает на другой
вопрос, чем задан. Тот же класс, что «справочник собирался только по
торгуемым сейчас» (A1) и «покрытие меряет присутствие, а не плотность»
(Z2) — сужение молчит, а число печатается.

Поэтому поимённый опрос базовых активов НАШЕГО универсума идёт ВСЕГДА, а
общий список служит лишь дополнением; если общий отдал строго меньше
активов, чем опрос, это НАЗЫВАЕТСЯ в отчёте, а не сглаживается. Покрытие
и так надо считать по тем именам, которыми мы торгуем, а не по рекламному
списку площадки.

Оговорка, названная до прогона: наличие контракта не есть исполнимость.
Опцион на тонкий альт может существовать и не иметь ни спроса, ни
предложения; ёмкость и премию этот прогон не меряет и мерить не должен —
он отвечает «есть ли инструмент», а не «во что он обойдётся».

Запуск:

    python3 bybit_options.py            # опрос по всему нашему универсуму
    python3 bybit_options.py --smoke    # опрос только по мажорам

Публикует отчёт сам; `--no-publish` выключает. Только stdlib.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
# Кэш ответов — СИБЛИНГ out (публикация коммитит всё под `research/*/out`,
# и файлы кэша уехали бы в git). Ключ несёт дату: повтор в те же сутки
# дёшев, назавтра ответ берётся заново — инвентарь живой, а не снимок.
CACHE = os.path.join(HERE, ".cache_opts")

sys.path.insert(0, RESEARCH)
from common.venue import fetch as _fetch                       # noqa: E402

API = "https://api.bybit.com"
STORE = os.path.join(OUT, "options_inventory.json")
UNIVERSE = os.path.join(OUT, "universe.json")
INSTRUMENTS = os.path.join(OUT, "instruments.json")
MAJORS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE"]
WORKERS = 3


def api_get(path, params, day=None):
    """Публичный GET к площадке. Отказ — ДАННЫЕ, а не исключение.

    Возвращает (ok, result, msg). Эндпоинт, требующий `baseCoin`, отвечает
    ненулевым `retCode` — это законный ответ, по которому мы выбираем
    второй способ обхода, а не падение прогона.
    """
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    key = f"{day or time.strftime('%Y-%m-%d', time.gmtime())}-" \
          f"{urllib.parse.urlencode(params)}".replace("/", "_")
    try:
        raw = _fetch(url, CACHE, cache_key=key, user_agent="opts-inv/1.0")
    except Exception as e:                       # noqa: BLE001 — сеть
        return False, {}, f"сеть: {e}"
    try:
        doc = json.loads(raw)
    except ValueError as e:
        return False, {}, f"ответ не JSON: {e}"
    if doc.get("retCode") != 0:
        return False, {}, f"retCode={doc.get('retCode')} {doc.get('retMsg')}"
    return True, doc.get("result") or {}, ""


def list_options(base_coin=None, pages=20):
    """Живые опционные контракты (по базовому активу либо все). Список строк.

    Пагинация курсором; предел страниц — страховка от бесконечного цикла,
    а не оценка объёма. Возвращает (ok, rows, msg).
    """
    rows, cursor = [], None
    for _ in range(pages):
        p = {"category": "option", "limit": 1000}
        if base_coin:
            p["baseCoin"] = base_coin
        if cursor:
            p["cursor"] = cursor
        ok, res, msg = api_get("/v5/market/instruments-info", p)
        if not ok:
            return False, rows, msg
        rows.extend(res.get("list") or [])
        cursor = res.get("nextPageCursor")
        if not cursor:
            break
    return True, rows, ""


def summarize(rows):
    """Свод по базовым активам: контрактов и границы экспираций.

    Считаются только торгуемые контракты: снятый опцион инструментом уже не
    является, и записав его, мы объявили бы хедж возможным там, где его нет.

    Контракт считается ОДИН раз по имени. Строки приходят из двух обходов
    (общий список плюс поимённый опрос), и они пересекаются: первый прогон
    правки дал у BTC 1540 контрактов вместо 770 — ровно вдвое, потому что
    те же строки сложились дважды. Набор базовых активов от этого не
    менялся, а число в таблице врало вдвое.
    """
    by, seen = {}, set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        st = str(r.get("status") or "")
        if st and st != "Trading":
            continue
        name = str(r.get("symbol") or "")
        if name:
            if name in seen:
                continue
            seen.add(name)
        b = str(r.get("baseCoin") or "").upper()
        if not b:
            continue
        d = by.setdefault(b, {"contracts": 0, "first_ms": None,
                              "last_ms": None})
        d["contracts"] += 1
        try:
            dt = int(r.get("deliveryTime") or 0)
        except (TypeError, ValueError):
            dt = 0
        if dt > 0:
            d["first_ms"] = dt if d["first_ms"] is None else min(d["first_ms"], dt)
            d["last_ms"] = dt if d["last_ms"] is None else max(d["last_ms"], dt)
    for b, d in by.items():
        for k in ("first_ms", "last_ms"):
            d[k[:-3]] = (time.strftime("%Y-%m-%d", time.gmtime(d[k] / 1000))
                         if d[k] else None)
    return by


def universe_bases(inst):
    """Базовые активы КРИПТО-части нашего универсума (символ → базовый).

    Не-крипто исключены решением владельца по составу универсума; считать
    покрытие по ним значило бы мерить не тот универсум, которым торгуем.
    """
    try:
        with open(UNIVERSE, encoding="utf-8") as f:
            u = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for _asset, rec in (u.get("assets") or {}).items():
        if not isinstance(rec, dict):
            continue
        if rec.get("asset_class") != "crypto":
            continue
        sym = rec.get("bybit_symbol")
        if not sym:
            continue
        b = (inst.get(sym) or {}).get("base_coin") or rec.get("base") or ""
        if b:
            out[sym] = str(b).upper()
    return out


def load_instruments():
    try:
        with open(INSTRUMENTS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def alias_set(base):
    """Базовый актив и его вариант без множителя лота (`1000PEPE` → `PEPE`)."""
    b = str(base).upper()
    alts = {b}
    for pre in ("1000000", "100000", "10000", "1000"):
        if b.startswith(pre) and len(b) > len(pre):
            alts.add(b[len(pre):])
    return alts


def run(smoke=False, log=print):
    t0 = time.time()
    inst = load_instruments()
    uni = universe_bases(inst)
    log(f"крипто-символов универсума {len(uni)}")

    # 1) общий список без базового актива — ДОПОЛНЕНИЕ, а не источник
    ok, rows, msg = list_options(None)
    if ok and rows:
        log(f"общий список принят: строк {len(rows)}")
    else:
        log(f"общий список не отдан ({msg or 'пусто'})")
        rows = []
    list_coins = sorted(summarize(rows))

    # 2) поимённый опрос НАШИХ базовых активов — он и отвечает на вопрос
    probed, probe_errors = 0, []
    cands = list(dict.fromkeys(
        MAJORS if smoke
        else MAJORS + sorted({a for b in uni.values() for a in alias_set(b)})))
    log(f"опрашиваю базовые активы поимённо: кандидатов {len(cands)}")
    said, done = time.time(), 0

    def one(b):
        o, rr, m = list_options(b, pages=5)
        return b, o, rr, m

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for b, o, rr, m in ex.map(one, cands):
            done += 1
            probed += 1
            if o:
                rows.extend(rr)
            elif m and "retCode" not in m:
                probe_errors.append({"base": b, "msg": m})
            if time.time() - said > 30:
                log(f"  опрошено {done}/{len(cands)}, строк {len(rows)}")
                said = time.time()

    by = summarize(rows)
    # общий список, отдавший СТРОГО меньше активов, чем опрос, — это
    # подставленное умолчание, а не пустая площадка; называем числом
    narrowed = sorted(set(by) - set(list_coins)) if list_coins else []
    method = "list+probe" if list_coins else "probe"
    coins = sorted(by)
    cover = sorted({s for s, b in uni.items() if alias_set(b) & set(coins)})
    out = {
        "asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "bybit /v5/market/instruments-info category=option",
        "method": method, "probed": probed, "rows": len(rows),
        "list_coins": list_coins, "narrowed": narrowed,
        "base_coins": coins, "by_coin": by,
        "universe_crypto": len(uni),
        "universe_covered": cover,
        "probe_errors": probe_errors[:20],
        "secs": round(time.time() - t0, 1),
    }
    return out


def report(s):
    P = []
    P.append("# Инвентарь опционов площадки исполнения\n")
    P.append("Вопрос один: **существует ли выпуклый инструмент на тех "
             "именах, которыми мы торгуем.** Линейный хедж закрыт "
             "арифметикой (D2: страховка стоила в 48 раз дороже всего "
             "хвоста, который страховала), выпуклый — единственный, у "
             "которого такой арифметики нет. Наличие контракта не есть "
             "исполнимость: ёмкость и премию этот прогон не меряет.\n")
    P.append(f"Снято {s['asof']}, поимённый опрос базовых активов нашего "
             f"универсума ({s['probed']} штук), строк {s['rows']}, прогон "
             f"{s['secs']} с.\n")
    if s.get("narrowed"):
        P.append(f"> **Общий список эндпоинта сузил ответ молча.** Запрос без "
                 f"`baseCoin` вернул активы {s.get('list_coins')}, а "
                 f"поимённый опрос нашёл ещё {len(s['narrowed'])}: "
                 f"{', '.join(s['narrowed'])}. То есть эндпоинт без базового "
                 f"актива подставляет умолчание и отвечает на другой вопрос, "
                 f"чем задан, — первый прогон на этом объявил «базовый актив "
                 f"ровно один». Поэтому опрос идёт всегда, а общий список "
                 f"служит дополнением.\n")
    coins = s["base_coins"]
    if not coins:
        P.append("**Опционов не найдено ни на один базовый актив.** Если "
                 "способ обхода — поимённый опрос, это утверждение о наших "
                 "именах, а не о площадке целиком.\n")
    else:
        P.append(f"## Базовые активы с опционами: {len(coins)}\n")
        P.append("| базовый актив | контрактов | ближняя экспирация | "
                 "дальняя |")
        P.append("|---|--:|--:|--:|")
        for b in coins:
            d = s["by_coin"][b]
            P.append(f"| {b} | {d['contracts']} | {d.get('first') or '—'} | "
                     f"{d.get('last') or '—'} |")
        P.append("")
    cov, tot = len(s["universe_covered"]), s["universe_crypto"]
    share = (cov / tot * 100.0) if tot else 0.0
    P.append(f"## Покрытие нашего универсума\n")
    P.append(f"Крипто-символов в универсуме **{tot}**, из них опцион на "
             f"базовый актив существует у **{cov} ({share:.1f} %)**"
             + (f": {', '.join(s['universe_covered'])}"
                if 0 < cov <= 30 else "") + ".\n")
    if share < 5:
        P.append("То есть **пут под нашу книгу купить не на что**: опционы "
                 "живут на мажорах, а книга торгует альтами. Пут на мажор "
                 "есть снова РЫНОЧНЫЙ хедж, а замер (б) уже показал, что "
                 "рынок нашему хвосту не отвечает — хвост идиосинкратический, "
                 "альт валится сам, рынок при этом часто растёт. Значит "
                 "выпуклый путь закрыт не ценой премии, а отсутствием "
                 "инструмента.\n")
    if s.get("probe_errors"):
        P.append(f"\nОпрос: сетевых отказов {len(s['probe_errors'])} "
                 f"(первые: {s['probe_errors'][:3]}) — эти базовые активы "
                 "остались НЕизмеренными, а не пустыми.\n")
    return "\n".join(P) + "\n"


def publish(name):
    subprocess.run(["tools/publish.sh", f"job: {name}"],
                   cwd=os.path.dirname(RESEARCH), check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    s = run(smoke=a.smoke)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    rep = report(s)
    with open(os.path.join(OUT, "D3-options.md"), "w", encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)
    if not a.no_publish:
        publish("bybit-options")


if __name__ == "__main__":
    main()
