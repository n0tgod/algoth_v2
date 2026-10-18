#!/usr/bin/env python3
"""Бывает ли случай «держим имя, а площадка объявила делистинг» (спека 19 §5a, N2a).

Прежде чем включать правило «делистинг → закрыть по рынку», замер: сколько
раз оно сработало бы на записи книг и что оно изменило бы (урок 06.10 —
правило без случая ничего не решает).

Два источника делистинга, оба с площадки исполнения:
1. **Объявления Bybit** типа `delistings` (`/v5/announcements/index`,
   постранично до начала записи книг) — момент публикации `publishTime`.
   Имена — перпы `…USDT` из заголовка и описания; спот (`ABC/USDT`)
   печатается отдельно: перп он не закрывает, но сигнал тот же.
2. **Справочник инструментов** — контракты со `status != Trading` и
   `delivery_time` в окне записи: когда площадка контракт фактически сняла.

Для каждого объявления о перпе — позиции книг по этому имени:
* **держали в момент публикации** (вход ≤ публикация < выход): что дал бы
  выход на часе публикации против фактического, в % маржи
  (`итог − путь[час публикации]` — сколько позиция заработала или потеряла
  ПОСЛЕ объявления);
* **открыли после публикации** (до снятия контракта): правило заодно
  запретило бы вход — печатается их итог.
Позиция в одной книге и её сестрах — одна сделка: счёт по уникальным
(имя, сторона, час входа), книги — списком.

Только чтение; отчёт `out/DCA-delist-cases.md`, публикует сам.

    run research/dca_paper/delist_cases.py
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
OUT_MD = os.path.join(HERE, "out", "DCA-delist-cases.md")
OUT_JSON = os.path.join(HERE, "out", "DCA-delist-cases.json")
INSTRUMENTS = os.path.join(ROOT, "research", "a1_universe", "out", "instruments.json")
API = "https://api.bybit.com/v5/announcements/index?locale=en-US&type=delistings&limit=50&page={p}"
SINCE_MS = int(datetime(2026, 8, 4, tzinfo=timezone.utc).timestamp() * 1000)   # начало записи стакана
HOUR = 3600.0
MEM_LIMIT_MB = 3000
PERP_RE = re.compile(r"\b([0-9A-Z]{2,25}USDT)\b")
SPOT_RE = re.compile(r"\b([0-9A-Z]{2,25})/USDT\b")


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------ разборы (чистые)

def parse_ann(it):
    """Объявление → {t, title, perps, spots}; t — момент публикации."""
    text = f"{it.get('title') or ''} \n {it.get('description') or ''}"
    try:
        t = int(it.get("publishTime") or it.get("dateTimestamp") or 0)
    except (TypeError, ValueError):
        t = 0
    perps = sorted(set(PERP_RE.findall(text)) - {"USDT"})
    spots = sorted(set(SPOT_RE.findall(text)))
    return {"t": t, "title": str(it.get("title") or "")[:200], "url": it.get("url"),
            "perps": perps, "spots": spots}


def closed_contracts(instruments, since_ms):
    """Справочник → [(символ, момент снятия мс)] за окно."""
    out = []
    for s, it in (instruments or {}).items():
        try:
            d = int(it.get("delivery_time") or 0)
        except (TypeError, ValueError):
            d = 0
        if s.endswith("USDT") and it.get("status") != "Trading" and d >= since_ms:
            out.append((s, d))
    return sorted(out, key=lambda x: x[1])


def span_of(r):
    """Позиция → (вход с, выход с) или None; выход — exit_ts, иначе по часам пути."""
    try:
        at = float(r["at"])
    except (KeyError, TypeError, ValueError):
        return None
    ex = r.get("exit_ts")
    if ex is None:
        marks = r.get("marks") or []
        if not marks:
            return None
        ex = float(marks[-1][0]) + HOUR
    return at, float(ex)


def after_announcement(cum, at, t_s):
    """Сколько позиция сделала ПОСЛЕ часа публикации: итог − путь[k]."""
    if not cum:
        return None
    K = max(cum)
    k = max(1, min(K, int((t_s - at) // HOUR) + 1))
    return cum[K] - cum.get(k, 0.0)


def match(anns, positions, closed_at):
    """Объявления о перпах × позиции → случаи «держали» и «вошли после»."""
    held, after = {}, {}
    for a in anns:
        if not a["perps"]:
            continue
        t_s = a["t"] / 1000.0
        for p in positions:
            if p["sym"] not in a["perps"]:
                continue
            at, ex = p["span"]
            end = closed_at.get(p["sym"], float("inf"))
            key = (p["sym"], p["side"], int(at))
            if at <= t_s < ex:
                c = held.setdefault(key, {"sym": p["sym"], "side": p["side"], "at": at, "ann": a["title"],
                                          "ann_t": a["t"], "books": [], "after": p.get("after"),
                                          "final": p.get("final")})
                c["books"].append(p["book"])
            elif t_s < at < end:
                c = after.setdefault(key, {"sym": p["sym"], "side": p["side"], "at": at, "ann": a["title"],
                                           "ann_t": a["t"], "books": [], "final": p.get("final")})
                c["books"].append(p["book"])
    return list(held.values()), list(after.values())


# ------------------------------------------------------------ прогон

def fetch_anns(log, get=None, pages=20):
    get = get or (lambda u: json.loads(urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "algoth-delist/1"}), timeout=20).read()))
    out, err = [], None
    for p in range(1, pages + 1):
        try:
            doc = get(API.format(p=p))
        except Exception as e:                               # noqa: BLE001
            err = f"страница {p}: {type(e).__name__}: {e}"[:200]
            break
        if doc.get("retCode") not in (0, None):
            err = f"страница {p}: retCode {doc.get('retCode')} {doc.get('retMsg')}"
            break
        lst = (doc.get("result") or {}).get("list") or []
        out += [parse_ann(x) for x in lst]
        if not lst or min((parse_ann(x)["t"] for x in lst), default=0) < SINCE_MS:
            break
        time.sleep(0.3)
    log(f"объявлений о делистинге получено {len(out)} ({p} стр.); старейшее "
        f"{fmt(min(a['t'] for a in out)) if out else '—'}" + (f"; ОТКАЗ: {err}" if err else ""))
    return out, err


def positions_of(log):
    import exit_ceiling as EC                                  # noqa: E402
    import rules as R                                          # noqa: E402
    import wave as WV                                          # noqa: E402
    data, why = EC.load(log)
    if why:
        return None, why
    shorts = set(R.order_of("h24"))                            # сторона — по реестру книг, не по имени
    out, keys = [], set()
    for book, recs in data["books"].items():
        side = "short" if book in shorts else "long"
        for r in recs:
            sp = span_of(r)
            if not sp or not r.get("sym"):
                continue
            pth = WV.path_of(r)
            out.append({"book": book, "sym": r["sym"], "side": r.get("side") or side, "span": sp,
                        "final": (pth or {}).get("final"), "cum": (pth or {}).get("cum")})
            keys.add((r["sym"], int(sp[0])))
    log(f"позиций в книгах {len(out)} (уникальных входов {len(keys)}) в {len(data['books'])} книгах")
    return out, None


def run(log=print):
    t0 = time.time()
    anns, err = fetch_anns(log)
    anns_in = [a for a in anns if a["t"] >= SINCE_MS]
    try:
        with open(INSTRUMENTS, encoding="utf-8") as f:
            closed = closed_contracts(json.load(f), SINCE_MS)
    except (OSError, ValueError) as e:
        closed, err = [], (err or "") + f"; справочник не прочитан: {e}"
    closed_at = {s: d / 1000.0 for s, d in closed}
    pos, why = positions_of(log)
    if why:
        return {"error": f"позиции книг не загружены: {why}", "anns": len(anns_in), "fetch_error": err}
    for p in pos:
        p["after"] = None
    held, after = match(anns_in, pos, closed_at)
    # «после объявления» считается на позиции первой книги случая (путь одинаков у сестёр одного входа)
    by_key = {}
    for p in pos:
        by_key.setdefault((p["sym"], p["side"], int(p["span"][0])), p)
    for c in held:
        p = by_key.get((c["sym"], c["side"], int(c["at"])))
        c["after"] = after_announcement(p.get("cum") if p else None, c["at"], c["ann_t"] / 1000.0)
    held_syms = {c["sym"] for c in held} | {c["sym"] for c in after}
    book_syms = {p["sym"] for p in pos}
    perp_anns = [a for a in anns_in if a["perps"]]
    res = {
        "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "secs": round(time.time() - t0, 1),
        "window_from": fmt(SINCE_MS), "fetch_error": err,
        "anns": len(anns_in), "anns_perp": len(perp_anns), "anns_spot_only": sum(1 for a in anns_in if a["spots"] and not a["perps"]),
        "perps_named": len({s for a in perp_anns for s in a["perps"]}),
        "perps_named_ever_in_books": len({s for a in perp_anns for s in a["perps"]} & book_syms),
        "closed_contracts": len(closed), "closed_ever_in_books": len({s for s, _ in closed} & book_syms),
        "held": sorted(held, key=lambda c: c["ann_t"]), "entered_after": sorted(after, key=lambda c: c["ann_t"]),
        "names_hit": sorted(held_syms), "positions": len(pos),
    }
    return res


def pct(x):
    return "—" if x is None else f"{100 * x:+.1f} %"


def report(r):
    if r.get("error"):
        return f"# Делистинг против позиций книг\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    L = ["# Делистинг против позиций книг (спека 19 §5a, N2a)", "",
         f"Окно с {r['window_from']} UTC, посчитано {r['computed_at']} UTC за {r['secs']} с."
         + (f" **Отказ загрузки объявлений:** {r['fetch_error']}" if r.get("fetch_error") else ""), "",
         "| что | число |", "|---|---|",
         f"| объявлений Bybit о делистинге в окне | {r['anns']} |",
         f"| из них про перпы | {r['anns_perp']} |",
         f"| только спот | {r['anns_spot_only']} |",
         f"| перпов названо | {r['perps_named']} |",
         f"| из них когда-либо в книгах | {r['perps_named_ever_in_books']} |",
         f"| контрактов снято площадкой в окне (справочник) | {r['closed_contracts']} |",
         f"| из них когда-либо в книгах | {r['closed_ever_in_books']} |",
         f"| позиций книг просмотрено | {r['positions']} |",
         f"| **держали в момент объявления** (уникальных входов) | **{len(r['held'])}** |",
         f"| **вошли после объявления, до снятия** | **{len(r['entered_after'])}** |", ""]
    if r["held"]:
        L += ["## Держали в момент объявления", "",
              "| имя | сторона | вход UTC | объявление UTC | после объявления | итог позиции | книг |", "|---|---|---|---|---|---|---|"]
        for c in r["held"]:
            L.append(f"| {c['sym']} | {c['side']} | {fmt(c['at'] * 1000)} | {fmt(c['ann_t'])} | {pct(c['after'])} | "
                     f"{pct(c['final'])} | {len(c['books'])} |")
        L += ["", "«После объявления» — что позиция сделала от часа публикации до своего выхода, в % маржи: "
              "минус значит, что правило «закрыть при объявлении» сберегло бы столько."]
    if r["entered_after"]:
        L += ["", "## Вошли после объявления", "", "| имя | сторона | вход UTC | объявление UTC | итог | книг |", "|---|---|---|---|---|---|"]
        for c in r["entered_after"]:
            L.append(f"| {c['sym']} | {c['side']} | {fmt(c['at'] * 1000)} | {fmt(c['ann_t'])} | {pct(c['final'])} | {len(c['books'])} |")
    if not r["held"] and not r["entered_after"]:
        L += ["**Случаев ноль:** ни одна позиция книг не держала и не открывала имя, объявленное к делистингу. "
              "Правило в окне записи ничего бы не изменило; включать его можно как страховку, но эффекта на числах не будет."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                      # noqa: E402
    res = run(AB.guarded(print, limit=MEM_LIMIT_MB))
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, default=str)
    print(txt[-3500:])
    if not a.no_publish and not res.get("error"):
        subprocess.run(["tools/publish.sh", "замер: делистинг против позиций"], cwd=ROOT, check=False)
    return 0 if not res.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
