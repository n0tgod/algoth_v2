#!/usr/bin/env python3
"""Сборщик состояния рынка (спека 19 §3b): кто в лонге, кто в шорте — по именам.

Зачем. Каталог критериев спеки 19 §3a держится на данных, которых в
нашей записи нет: доля аккаунтов в лонге по каждому имени Bybit (A1),
доли толпы и топ-трейдеров Binance (A8, A9), лонг/шорт OKX (A12),
страховой фонд (A13), доминация BTC, страх и жадность, тренды,
стейблкоины (D3–D6), объявления площадок и взломы (E1–E3). Без записи
ни сетка v2, ни судья этих чисел не увидят; запись начинается ДО старта
веток, фон копится.

Отдельный процесс, не внутри сборщика стакана: тяжёлый сосед убивает
цикл, а не себя (урок 10.10), а память сборщика у края. Раз в час из
сторожа (`tools/watchdog_book.sh`), один запуск — одна строка журнала на
имя и источник; первый запуск докачивает историю на глубину, какую
отдаёт площадка (Bybit ≈ 20 сут при 1 ч, Binance 30 сут).

Обязательства по урокам проекта:
* покрытие печатается ЧИСЛОМ до любого вывода: сколько имён из скольких
  получили долю в этот час, по каждому источнику; Binance и OKX — только
  пересечение имён, и «имени нет на площадке» — причина, не ноль;
* отказ источника — строка в `errors` сводки и на странице, не тишина;
* ряд продлевается по ЧАСАМ (последняя метка на имя и источник в
  `hist.json`), не по существованию файла;
* чужие площадки — ВТОРАЯ толпа рядом с нашей, не вместо неё (решение о
  площадке исполнения).

Что НЕ собирается и почему: OI и funding Bybit уже пишет сборщик стакана
(`metrics`, раз в 5 мин); тейкер-агрессия у нас своя из ленты (B4);
тейкер и история OI Binance сняты из-за лимита площадки на эти
эндпоинты (1000 запросов за 5 мин на IP) — две доли на ≈ 450 имён уже
занимают его на 60 %.

Запуск:
    collect.py                 # один час, с публикацией
    collect.py --no-publish
    collect.py --limit 20 --dry   # смоук: 20 имён, без записи и публикации
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "research", "common"))
OUT = os.path.join(HERE, "out")
RECORD = os.path.join(OUT, "record")          # не в git (.gitignore)
HIST = os.path.join(RECORD, "hist.json")
SEEN = os.path.join(RECORD, "seen_events.json")
LATEST = os.path.join(OUT, "latest.json")
REPORT = os.path.join(OUT, "MARKET-state.md")

BYBIT = "https://api.bybit.com"
BINANCE = "https://fapi.binance.com"
BINANCE_CMS = ("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
               "?type=1&pageNo=1&pageSize=20&catalogId=")
OKX = "https://www.okx.com"
BYBIT_BACKFILL = 500      # точек истории на имя при первом запросе (≈ 20 сут при 1 ч)
BINANCE_BACKFILL = 500    # площадка отдаёт не глубже 30 сут
PACE = {"bybit": (2, 0.20), "binance": (1, 0.40), "okx": (1, 0.15)}   # потоки, пауза
TIMEOUT = 15
STALE_S = 2 * 3600        # порог тревоги «запись стоит» на странице
BINANCE_CATALOGS = ("48", "161")   # имя каталога берётся ИЗ ответа, не из памяти


def utc_now():
    return datetime.now(timezone.utc)


def http_json(url, timeout=TIMEOUT, tries=2):
    """GET → JSON. Повтор один, отказ — исключением с кодом и адресом."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "algoth-state/1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (403, 404, 451):
                break
        except Exception as e:                               # noqa: BLE001
            last = f"{type(e).__name__}"
        if i + 1 < tries:
            time.sleep(1.0)
    raise RuntimeError(f"{last}: {url.split('?')[0]}")


# ------------------------------------------------------------ разборы (чистые)

def parse_bybit_names(doc):
    """instruments-info → {symbol: baseCoin} по торгуемым перпам USDT."""
    out = {}
    for it in ((doc.get("result") or {}).get("list") or []):
        s = str(it.get("symbol") or "")
        if s.endswith("USDT") and it.get("status", "Trading") == "Trading":
            out[s] = str(it.get("baseCoin") or s[:-4])
    return out


def parse_bybit_ratio(doc):
    """account-ratio → [{t, long, short}] по возрастанию времени."""
    rows = []
    for it in ((doc.get("result") or {}).get("list") or []):
        try:
            rows.append({"t": int(it["timestamp"]), "long": float(it["buyRatio"]),
                         "short": float(it["sellRatio"])})
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["t"])
    return rows


def parse_binance_names(doc):
    """exchangeInfo → множество бессрочных USDT-контрактов в торговле."""
    out = set()
    for it in doc.get("symbols") or []:
        if (it.get("contractType") == "PERPETUAL" and it.get("status") == "TRADING"
                and it.get("quoteAsset") == "USDT"):
            out.add(str(it.get("symbol")))
    return out


def parse_binance_ratio(lst):
    """global/top long-short → [{t, long}] (доля лонгов)."""
    rows = []
    for it in lst or []:
        try:
            rows.append({"t": int(it["timestamp"]), "long": float(it["longAccount"])})
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["t"])
    return rows


def parse_okx_ccys(doc):
    """public/instruments SWAP → множество базовых монет USDT-свопов."""
    out = set()
    for it in doc.get("data") or []:
        inst = str(it.get("instId") or "")
        parts = inst.split("-")
        if len(parts) == 3 and parts[1] == "USDT" and parts[2] == "SWAP" \
                and it.get("state", "live") == "live":
            out.add(parts[0])
    return out


def parse_okx_ratio(doc):
    """long-short-account-ratio → [{t, ls}] (лонгов на одного шортиста)."""
    rows = []
    for it in doc.get("data") or []:
        try:
            rows.append({"t": int(it[0]), "ls": float(it[1])})
        except (IndexError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["t"])
    return rows


def parse_market(fng=None, cg=None, ins=None, stables=None):
    """Четыре ответа уровня рынка → плоский словарь; чего нет — нет."""
    m = {}
    try:
        d = (fng or {}).get("data") or []
        m["fng"] = int(d[0]["value"]); m["fng_label"] = str(d[0].get("value_classification") or "")
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    try:
        g = (cg or {}).get("data") or {}
        m["btc_dom"] = round(float(g["market_cap_percentage"]["btc"]), 2)
        m["mcap_usd"] = round(float(g["total_market_cap"]["usd"]))
        m["mcap_24h_pct"] = round(float(g["market_cap_change_percentage_24h_usd"]), 2)
    except (KeyError, TypeError, ValueError):
        pass
    try:
        lst = ((ins or {}).get("result") or {}).get("list") or []
        bal = sum(float(x["balance"]) for x in lst if x.get("coin") == "USDT")
        if lst:
            m["insurance_usdt"] = round(bal)
    except (KeyError, TypeError, ValueError):
        pass
    try:
        tot = 0.0; px = {}
        for a in (stables or {}).get("peggedAssets") or []:
            circ = float(((a.get("circulating") or {}).get("peggedUSD")) or 0)
            tot += circ
            if a.get("symbol") in ("USDT", "USDC") and a.get("price") is not None:
                px[a["symbol"]] = round(float(a["price"]), 4)
        if tot:
            m["stables_usd"] = round(tot)
            m["stable_px"] = px
    except (KeyError, TypeError, ValueError):
        pass
    return m


def parse_bybit_events(doc):
    """announcements → [{id, src, t, title, kind}]; id — ссылка."""
    out = []
    for it in ((doc.get("result") or {}).get("list") or []):
        url = str(it.get("url") or it.get("title") or "")
        try:
            t = int(it.get("dateTimestamp") or it.get("publishTime") or 0)
        except (TypeError, ValueError):
            t = 0
        kind = ((it.get("type") or {}).get("key") if isinstance(it.get("type"), dict)
                else it.get("type")) or ""
        out.append({"id": "bybit:" + url, "src": "bybit", "t": t,
                    "title": str(it.get("title") or "")[:200], "kind": str(kind),
                    "tags": [str(x) for x in (it.get("tags") or [])][:8]})
    return out


def parse_binance_events(doc):
    """CMS article list → события с именем каталога ИЗ ответа."""
    out = []
    data = (doc or {}).get("data") or {}
    for cat in data.get("catalogs") or []:
        cname = str(cat.get("catalogName") or cat.get("catalogId") or "")
        for a in cat.get("articles") or []:
            code = str(a.get("code") or a.get("id") or "")
            try:
                t = int(a.get("releaseDate") or 0)
            except (TypeError, ValueError):
                t = 0
            out.append({"id": "binance:" + code, "src": "binance", "t": t,
                        "title": str(a.get("title") or "")[:200], "kind": cname})
    return out


def parse_hacks(lst, since_s):
    out = []
    for h in lst or []:
        try:
            t = int(h.get("date") or 0)
        except (TypeError, ValueError):
            continue
        if t >= since_s:
            out.append({"id": f"hack:{h.get('name')}:{t}", "src": "defillama", "t": t * 1000,
                        "title": f"{h.get('name')}: {h.get('classification') or ''} "
                                 f"{h.get('amount') or 0}$"[:200], "kind": "hack"})
    return out


# ------------------------------------------------------------ состав записи

def new_rows(rows, last_t):
    """Оставить точки новее последней записанной: ряд продлевается по часам."""
    return [r for r in rows if r["t"] > (last_t or 0)]


def day_of(t_ms):
    return datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc).date().isoformat()


def coverage(got, of):
    return {"got": int(got), "of": int(of),
            "pct": (round(100.0 * got / of, 1) if of else None)}


def skew(long_share):
    """Перекос толпы в п.п. от 50: +13 — толпа в лонге на 63 %."""
    return None if long_share is None else round((long_share - 0.5) * 100, 1)


def summarize(names, latest, cov, market, events, errors, t0, n_rows, n_bf):
    """Сводка часа для страницы и приложения; имена — только с данными."""
    tab = {}
    for s in names:
        v = latest.get(s)
        if not v:
            continue
        tab[s] = {k: v[k] for k in ("bb_long", "bn_long", "bn_top", "okx_ls", "nc", "t") if k in v}
    ranked = sorted((s for s in tab if tab[s].get("bb_long") is not None),
                    key=lambda s: tab[s]["bb_long"])
    return {
        "computed_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "secs": round(time.time() - t0, 1),
        "coverage": cov, "market": market,
        "events_24h": [e for e in events if e["t"] >= (time.time() - 86400) * 1000][:50],
        "errors": errors, "rows": n_rows, "backfill": n_bf,
        "most_short": ranked[:10], "most_long": ranked[-10:][::-1],
        "names": tab,
    }


def report_md(s):
    cov = s["coverage"]
    L = ["# Состояние рынка (спека 19 §3b)", "",
         f"Срез {s['computed_at']}, прогон {s['secs']} с, строк записано {s['rows']} "
         f"(из них докачка {s['backfill']}).", "",
         "| источник | имён получено | из | % |", "|---|---|---|---|"]
    for k in ("bybit", "binance", "okx"):
        c = cov.get(k) or {}
        L.append(f"| {k} | {c.get('got', '—')} | {c.get('of', '—')} | {c.get('pct', '—')} |")
    m = s.get("market") or {}
    L += ["", "Рынок: " + ", ".join(f"{k} {v}" for k, v in m.items() if k != "stable_px") or "Рынок: —"]
    if s["errors"]:
        L += ["", "Отказы: " + "; ".join(s["errors"][:10])]
    if s["most_long"]:
        L += ["", "Толпа в лонге сильнее всего: " + ", ".join(
            f"{n} {s['names'][n]['bb_long']:.2f}" for n in s["most_long"]),
              "Толпа в шорте сильнее всего: " + ", ".join(
            f"{n} {s['names'][n]['bb_long']:.2f}" for n in s["most_short"])]
    L += ["", f"Событий за сутки: {len(s['events_24h'])}."]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------ прогон

class Writer:
    """Строки записи — по суткам ИХ времени, чтобы сетка читала по дням."""

    def __init__(self, root=RECORD, dry=False):
        self.root, self.dry, self.n, self.lock = root, dry, 0, threading.Lock()
        self.fh = {}

    def write(self, row):
        with self.lock:
            self.n += 1
            if self.dry:
                return
            d = day_of(row["t"])
            fh = self.fh.get(d)
            if fh is None:
                os.makedirs(self.root, exist_ok=True)
                fh = self.fh[d] = open(os.path.join(self.root, f"state-{d}.jsonl"), "a", encoding="utf-8")
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def close(self):
        for fh in self.fh.values():
            fh.close()


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def _pool(src, items, fn, log):
    """Вежливый обход: потоки и пауза по площадке; отказ имени — счётчик, не падение."""
    workers, pause = PACE[src]
    errs = []

    def one(x):
        try:
            r = fn(x)
        except Exception as e:                               # noqa: BLE001
            errs.append(f"{x}: {e}")
            r = None
        time.sleep(pause)
        return r
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, items))
    if errs:
        log(f"  {src}: отказов по именам {len(errs)}, первый — {errs[0]}")
    return res, errs


def run(get=http_json, limit=0, dry=False, log=print, hist_path=HIST, seen_path=SEEN,
        record_dir=RECORD):
    t0 = time.time()
    hist = _load(hist_path, {})
    seen = set(_load(seen_path, []))
    errors = []
    latest = {}
    w = Writer(record_dir, dry=dry)
    n_bf = [0]

    def take(src, sym, rows, key, backfill_wanted):
        """Записать новые точки и запомнить последнюю; вернуть, пришло ли что-то."""
        h = hist.setdefault(sym, {})
        fresh = new_rows(rows, h.get(src))
        if backfill_wanted and len(fresh) > 1:
            n_bf[0] += len(fresh) - 1
        for r in fresh:
            row = {"t": r["t"], "sym": sym, "src": src}
            row.update({k: v for k, v in r.items() if k != "t"})
            w.write(row)
        if fresh:
            h[src] = fresh[-1]["t"]
        if rows:
            latest.setdefault(sym, {})[key] = rows[-1][next(k for k in rows[-1] if k != "t")]
            latest[sym]["t"] = max(latest[sym].get("t", 0), rows[-1]["t"])
        return bool(rows)

    # --- имена Bybit (своя площадка) --------------------------------------
    try:
        names = parse_bybit_names(get(f"{BYBIT}/v5/market/instruments-info?category=linear&status=Trading&limit=1000"))
    except Exception as e:                                   # noqa: BLE001
        errors.append(f"bybit instruments: {e}")
        names = {}
    syms = sorted(names)
    if limit:
        syms = syms[:limit]
    try:
        import universe_filter as UF                          # noqa: E402
        nc = UF.non_crypto_set()
    except Exception:                                        # noqa: BLE001
        nc = set()
    log(f"имена Bybit в торговле: {len(names)}; в прогоне {len(syms)}; не-крипто среди них "
        f"{sum(1 for s in syms if s in nc)}")
    cov = {}

    def bb(sym):
        lim = 1 if hist.get(sym, {}).get("bybit") else BYBIT_BACKFILL
        rows = parse_bybit_ratio(get(f"{BYBIT}/v5/market/account-ratio?category=linear&symbol={sym}&period=1h&limit={lim}"))
        return take("bybit", sym, rows, "bb_long", lim > 1)
    res, errs = _pool("bybit", syms, bb, log)
    cov["bybit"] = coverage(sum(1 for r in res if r), len(syms))
    errors += [f"bybit {e}" for e in errs[:3]]
    for s in syms:
        if s in nc and s in latest:
            latest[s]["nc"] = True

    # --- Binance: пересечение имён, толпа и топы --------------------------
    try:
        bn_all = parse_binance_names(get(f"{BINANCE}/fapi/v1/exchangeInfo"))
    except Exception as e:                                   # noqa: BLE001
        errors.append(f"binance exchangeInfo: {e}"); bn_all = set()
    bn = [s for s in syms if s in bn_all]
    log(f"Binance торгует {len(bn_all)} перпов USDT; пересечение с нашими {len(bn)} "
        f"(нет на Binance: {len(syms) - len(bn)})")

    def bnf(sym):
        ok = False
        for kind, path, key in (("bn_global", "globalLongShortAccountRatio", "bn_long"),
                                ("bn_top", "topLongShortPositionRatio", "bn_top")):
            lim = 1 if hist.get(sym, {}).get(kind) else BINANCE_BACKFILL
            rows = parse_binance_ratio(get(f"{BINANCE}/futures/data/{path}?symbol={sym}&period=1h&limit={lim}"))
            ok = take(kind, sym, rows, key, lim > 1) or ok
        return ok
    if bn_all:
        res, errs = _pool("binance", bn, bnf, log)
        cov["binance"] = coverage(sum(1 for r in res if r), len(bn))
        cov["binance"]["absent"] = len(syms) - len(bn)
        errors += [f"binance {e}" for e in errs[:3]]
    else:
        cov["binance"] = coverage(0, len(bn)); cov["binance"]["why"] = "справочник не получен"

    # --- OKX: по базовой монете -------------------------------------------
    try:
        ok_ccys = parse_okx_ccys(get(f"{OKX}/api/v5/public/instruments?instType=SWAP"))
    except Exception as e:                                   # noqa: BLE001
        errors.append(f"okx instruments: {e}"); ok_ccys = set()
    by_ccy = {}
    for s in syms:
        by_ccy.setdefault(names.get(s, s[:-4]), []).append(s)
    ccys = sorted(c for c in by_ccy if c in ok_ccys)
    log(f"OKX: свопов USDT {len(ok_ccys)}; наших базовых монет там {len(ccys)} из {len(by_ccy)}")

    def okf(ccy):
        rows = parse_okx_ratio(get(f"{OKX}/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=1H"))
        got = False
        for s in by_ccy[ccy]:
            got = take("okx", s, rows, "okx_ls", False) or got
        return got
    if ok_ccys:
        res, errs = _pool("okx", ccys, okf, log)
        cov["okx"] = coverage(sum(1 for r in res if r), len(ccys))
        cov["okx"]["absent"] = len(by_ccy) - len(ccys)
        errors += [f"okx {e}" for e in errs[:3]]
    else:
        cov["okx"] = coverage(0, len(ccys)); cov["okx"]["why"] = "справочник не получен"

    # --- уровень рынка -----------------------------------------------------
    srcs = {"fng": "https://api.alternative.me/fng/?limit=1",
            "cg": "https://api.coingecko.com/api/v3/global",
            "ins": f"{BYBIT}/v5/market/insurance?coin=USDT",
            "stables": "https://stablecoins.llama.fi/stablecoins?includePrices=true"}
    got = {}
    for k, u in srcs.items():
        try:
            got[k] = get(u)
        except Exception as e:                               # noqa: BLE001
            errors.append(f"{k}: {e}")
    market = parse_market(**got)
    if market:
        row = {"t": int(time.time() * 1000), "sym": "*", "src": "market"}
        row.update({k: v for k, v in market.items() if k != "stable_px"})
        w.write(row)
    try:
        tr = get("https://api.coingecko.com/api/v3/search/trending")
        market["trending"] = [str((c.get("item") or {}).get("symbol") or "").upper()
                              for c in (tr.get("coins") or [])][:15]
    except Exception as e:                                   # noqa: BLE001
        errors.append(f"trending: {e}")

    # --- события -----------------------------------------------------------
    events = []
    try:
        events += parse_bybit_events(get(f"{BYBIT}/v5/announcements/index?locale=en-US&limit=50"))
    except Exception as e:                                   # noqa: BLE001
        errors.append(f"bybit announcements: {e}")
    for cat in BINANCE_CATALOGS:
        try:
            events += parse_binance_events(get(BINANCE_CMS + cat))
        except Exception as e:                               # noqa: BLE001
            errors.append(f"binance cms {cat}: {e}")
    try:
        events += parse_hacks(get("https://api.llama.fi/hacks"), time.time() - 7 * 86400)
    except Exception as e:                                   # noqa: BLE001
        errors.append(f"hacks: {e}")
    new_ev = [e for e in events if e["id"] not in seen]
    for e in new_ev:
        row = {"t": e["t"] or int(time.time() * 1000), "sym": "*", "src": "event", "venue": e["src"]}
        row.update({k: e[k] for k in e if k not in ("t", "src")})
        w.write(row)
        seen.add(e["id"])
    w.close()
    log(f"событий известно {len(events)}, новых {len(new_ev)}")

    s = summarize(syms, latest, cov, market, events, errors, t0, w.n, n_bf[0])
    if not dry:
        _save(hist_path, hist)
        _save(seen_path, sorted(seen)[-5000:])
        _save(LATEST, s)
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write(report_md(s))
    log(f"покрытие: bybit {cov['bybit']['got']}/{cov['bybit']['of']}, "
        f"binance {cov['binance']['got']}/{cov['binance']['of']}, "
        f"okx {cov['okx']['got']}/{cov['okx']['of']}; строк {w.n} (докачка {n_bf[0]}); "
        f"отказов {len(errors)}; {s['secs']} с")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description="состояние рынка: доли лонгов по именам и фон")
    ap.add_argument("--limit", type=int, default=0, help="только первые N имён (смоук)")
    ap.add_argument("--dry", action="store_true", help="ничего не писать и не публиковать")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run(limit=a.limit, dry=a.dry)
    if not a.dry and not a.no_publish:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"),
                        "market-state " + s["computed_at"][:13]], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
