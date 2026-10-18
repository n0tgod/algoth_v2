#!/usr/bin/env python3
"""Сухой час судьи (спека 19, этап N2): настоящие кандидаты, настоящая модель, цена числом.

Ничего не торгует и ни в одну книгу не пишет. Берёт у книг Depth
(`optimal` — лонги, `optimal_h` — шорты) свежие входы последних суток и
открытые позиции, собирает досье тем же ядром `judge.py`, что пойдёт в
ветки вперёд, и спрашивает модель:
* вход — дважды с новостями (`ai_news`, второй раз — замер повторяемости,
  §6) и раз без новостей (`ai_plain`);
* открытая позиция — раз сторожем (§5a).
Печатает каждое решение, токены, задержку и цену; переводит цену в сутки
по числу входов книг за последние 7 суток. Покрытие досье печатается
числом ДО решений: сколько кандидатов получили долю толпы, ход цены,
новости — «не измерено» не выдаётся за «ничего не случилось».

Предел вызовов задан до прогона (`--cap`, по умолчанию 6 входов и 4
открытых на книгу ⇒ ≤ 44 вызова).

    run research/ai_gate/dry_hour.py
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
sys.path.insert(0, os.path.join(ROOT, "research", "news"))
import judge as J                                            # noqa: E402
import context as CTX                                        # noqa: E402
from context import load_state, load_news                    # noqa: E402

OUT = os.path.join(HERE, "out")
RECORD = os.path.join(OUT, "record")
OUT_MD = os.path.join(OUT, "AI-dry-hour.md")
OUT_JSON = os.path.join(OUT, "AI-dry-hour.json")
BOOKS = (("optimal", "long"), ("optimal_h", "short"))
H = 3600


def entries_per_day(recs, now, days=7):
    """Входов в сутки: уникальные (имя, час входа). Не по времени одному — в
    одном часе книга открывает десятки имён (18.10: 88 шортов за сутки
    читались как 20.9)."""
    ts = {(r.get("sym"), int(float(r["at"]))) for r in recs if float(r.get("at", 0)) >= now - days * 86400}
    return len(ts) / days


def estimate_only(log=print):
    """Цена в сутки по ценам вызовов последнего сухого часа и счёту входов
    книг за 7 суток — без единого вызова модели."""
    import exit_ceiling as EC                                  # noqa: E402
    try:
        with open(OUT_JSON, encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        return {"error": "нет прошлого сухого часа — цена вызова не измерена"}
    data, why = EC.load(log)
    if why:
        return {"error": f"книги не загружены: {why}"}
    now = data["now"]
    per_day = {b: round(entries_per_day(data["books"].get(b) or [], now), 1) for b, _ in BOOKS}
    open_now = sum(1 for b, _ in BOOKS for r in (data["books"].get(b) or []) if (r.get("state") or "closed") == "open")
    e = prev["by_kind"]["entry"]["mean_usd"]
    h = prev["by_kind"].get("hold", {}).get("mean_usd", e)
    entry_calls = sum(per_day.values()) * 2 * 1.05
    out = {"computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "entries_per_day_7d": per_day,
           "open_now": open_now, "entry_call_usd": e, "hold_call_usd": h,
           "entry_calls_day": round(entry_calls), "usd_entry_day": round(entry_calls * e, 2),
           "heartbeat_calls_day_if_model": open_now * 4, "usd_heartbeat_day_if_model": round(open_now * 4 * h, 2)}
    log(json.dumps(out, ensure_ascii=False))
    return out


def run(cap_entry, cap_open, log=print, client=None):
    import exit_ceiling as EC                                  # noqa: E402
    t0 = time.time()
    key = J.read_key()
    if client is None:
        if not key:
            return {"error": "ключа Anthropic нет или он не той формы — вызовов не было"}
        client = J.make_client(key)
    data, why = EC.load(log)
    if why:
        return {"error": f"книги не загружены: {why}"}
    now = data["now"]
    state, market_rows, events = load_state(days=80)
    news = load_news()
    log(f"фон: имён в записи состояния {len(state)}, срезов рынка {len(market_rows)}, событий {len(events)}, "
        f"новостей {len(news)} (старейшая {time.strftime('%m-%d %H:%M', time.gmtime(min((x['t'] for x in news), default=0) / 1000))})")
    rows, cov, per_day = [], Counter(), {}
    shown_keys = False
    for book, side in BOOKS:
        recs = data["books"].get(book) or []
        per_day[book] = round(entries_per_day(recs, now), 1)
        fresh = sorted((r for r in recs if float(r.get("at", 0)) >= now - 86400), key=lambda r: -float(r["at"]))
        opened = [r for r in recs if (r.get("state") or "closed") == "open"]
        uniq, picked = set(), []
        for r in fresh:
            k = (r.get("sym"), int(float(r["at"])))
            if k not in uniq:
                uniq.add(k); picked.append(r)
        picked = picked[:cap_entry]
        opened = sorted(opened, key=lambda r: -float(r["at"]))[:cap_open]
        log(f"{book}: входов/сутки за 7 сут {per_day[book]}, входов за сутки {len(uniq)} (берём {len(picked)}), "
            f"открытых {len([r for r in recs if (r.get('state') or 'closed') == 'open'])} (берём {len(opened)})")
        if not shown_keys and recs:
            log("поля записи позиции: " + ", ".join(sorted(recs[-1].keys())))
            shown_keys = True
        for kind, sample in (("entry", picked), ("hold", opened)):
            for r in sample:
                at_s = float(r["at"])
                ask_s = now if kind == "hold" else at_s
                kw, nw, c = CTX.build(kind, r, book, side, now, recs, state, market_rows, events, news)
                cov["кандидатов"] += 1
                cov["ход цены есть"] += c["px"]
                cov["толпа Bybit есть"] += c["crowd_bybit"]
                cov["Binance есть"] += c["crowd_binance"]
                cov["новости по имени есть"] += c["news"]
                cov["срез рынка есть"] += c["market"]
                variants = (("ai_news", True), ("ai_news_repeat", True), ("ai_plain", False)) if kind == "entry" \
                    else (("watch", True),)
                for name, with_news in variants:
                    d = J.dossier(kind, r, book, side, ask_s, news=nw if with_news else None, **kw)
                    blob = json.dumps(d, ensure_ascii=False, sort_keys=True)
                    out = J.ask(client, kind, d)
                    out.update({"variant": name, "book": book, "sym": r["sym"], "side": side, "at": at_s,
                                "dossier_sha": hashlib.sha256(blob.encode()).hexdigest()[:12],
                                "dossier_chars": len(blob), "news_n": len(nw) if with_news else None})
                    rows.append(out)
                    os.makedirs(RECORD, exist_ok=True)
                    with open(os.path.join(RECORD, "dry-decisions.jsonl"), "a", encoding="utf-8") as f:
                        f.write(json.dumps(dict(out, dossier=d), ensure_ascii=False) + "\n")
                    log(f"  {name:15} {book:9} {r['sym']:16} {out['decision']:5} "
                        f"conf {out.get('confidence')} {out.get('no_verdict') or ''} "
                        f"tok {out.get('usage', {}).get('input_tokens')}/{out.get('usage', {}).get('output_tokens')} "
                        f"${out.get('cost_usd')} {out.get('latency_s')} с | {'; '.join(out.get('reasons') or [])[:160]}")
    return summarize(rows, cov, per_day, data, t0)


def summarize(rows, cov, per_day, data, t0):
    ok = [r for r in rows if not r.get("no_verdict")]
    by_kind = {}
    for kind in ("entry", "hold"):
        xs = [r for r in ok if r["kind"] == kind and r.get("cost_usd") is not None]
        if xs:
            by_kind[kind] = {"calls": len(xs), "mean_usd": round(sum(r["cost_usd"] for r in xs) / len(xs), 5),
                             "mean_in": round(sum(r["usage"]["input_tokens"] for r in xs) / len(xs)),
                             "mean_out": round(sum(r["usage"]["output_tokens"] for r in xs) / len(xs)),
                             "mean_latency_s": round(sum(r["latency_s"] for r in xs) / len(xs), 1)}
    pairs = {}
    for r in rows:
        if r["kind"] == "entry" and r["variant"] in ("ai_news", "ai_news_repeat") and not r.get("no_verdict"):
            pairs.setdefault((r["book"], r["sym"], r["at"]), {})[r["variant"]] = r["decision"]
    both = [p for p in pairs.values() if len(p) == 2]
    repro = (round(100 * sum(p["ai_news"] == p["ai_news_repeat"] for p in both) / len(both), 1) if both else None)
    ent = [r for r in ok if r["kind"] == "entry" and r["variant"] == "ai_news"]
    skip_share = round(100 * sum(r["decision"] == "skip" for r in ent) / len(ent), 1) if ent else None
    entries_day = sum(per_day.values())
    open_now = sum(1 for b, _ in BOOKS for r in (data["books"].get(b) or []) if (r.get("state") or "closed") == "open")
    e = by_kind.get("entry", {}).get("mean_usd")
    h = by_kind.get("hold", {}).get("mean_usd")
    day = None
    if e is not None:
        calls_entry = entries_day * 2 * 1.05                    # ai_news + ai_plain, повтор 5 %
        calls_hold = open_now * 4                               # минимум раз в 6 ч на открытую; события — сверху
        day = {"entry_calls": round(calls_entry), "hold_calls_min": calls_hold,
               "usd_entry": round(calls_entry * e, 2), "usd_hold_min": round(calls_hold * (h or e), 2)}
        day["usd_total_min"] = round(day["usd_entry"] + day["usd_hold_min"], 2)
        day["usd_month_min"] = round(30 * day["usd_total_min"], 1)
    return {"computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "secs": round(time.time() - t0, 1),
            "model": J.MODEL, "effort": J.EFFORT, "prompt_v": J.PROMPT_V, "prices": J.PRICES_SRC,
            "calls": len(rows), "no_verdict": Counter(r["no_verdict"] for r in rows if r.get("no_verdict")),
            "served_models": Counter(r.get("served_model") for r in ok), "coverage": dict(cov),
            "by_kind": by_kind, "repro_pct": repro, "repro_pairs": len(both), "skip_share_pct": skip_share,
            "entries_per_day": per_day, "open_now": open_now, "per_day": day,
            "total_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
            "rows": [{k: r.get(k) for k in ("variant", "kind", "book", "sym", "side", "at", "decision", "confidence",
                                            "reasons", "news_used", "no_verdict", "served_model", "usage", "cost_usd",
                                            "latency_s", "news_n", "dossier_chars", "dossier_sha")} for r in rows]}


def report(s):
    if s.get("error"):
        return f"# Сухой час судьи\n\nНЕ ПОСЧИТАНО: {s['error']}\n"
    L = ["# Сухой час судьи (спека 19, N2)", "",
         f"{s['computed_at']} UTC, {s['secs']} с. Модель `{s['model']}`, усилие `{s['effort']}`, промпт `{s['prompt_v']}`; "
         f"цены — {s['prices']}.", "",
         f"Вызовов {s['calls']}, потрачено **${s['total_usd']}**; без вердикта: {dict(s['no_verdict']) or 0}; "
         f"ответили модели: {dict(s['served_models'])}.", "",
         "Покрытие досье: " + ", ".join(f"{k} {v}" for k, v in s["coverage"].items()), "",
         "| вызов | число | средняя цена | токенов вход / выход | задержка |", "|---|---|---|---|---|"]
    for k, v in s["by_kind"].items():
        L.append(f"| {'вход' if k == 'entry' else 'сторож'} | {v['calls']} | ${v['mean_usd']} | {v['mean_in']} / {v['mean_out']} | {v['mean_latency_s']} с |")
    L += ["", f"Повторяемость (тот же вход дважды): **{s['repro_pct']} %** на {s['repro_pairs']} парах (порог суда 90 %). "
          f"Доля отказов судьи с новостями: **{s['skip_share_pct']} %** (тревога выше 60 %).", ""]
    if s["per_day"]:
        d = s["per_day"]
        L += [f"**Цена в сутки** (входов книг за 7 сут: {s['entries_per_day']}; открытых сейчас {s['open_now']}): "
              f"вход {d['entry_calls']} вызовов ≈ ${d['usd_entry']}, сторож не меньше {d['hold_calls_min']} ≈ ${d['usd_hold_min']}; "
              f"итого **≥ ${d['usd_total_min']} в сутки, ≥ ${d['usd_month_min']} в месяц** (события сторожа — сверху).", ""]
    L += ["| ветка | книга | имя | решение | уверенность | причины |", "|---|---|---|---|---|---|"]
    for r in s["rows"]:
        L.append(f"| {r['variant']} | {r['book']} | {r['sym']} | {r['decision']}{' (' + r['no_verdict'] + ')' if r.get('no_verdict') else ''} | "
                 f"{r.get('confidence')} | {'; '.join(r.get('reasons') or [])[:200].replace('|', '/')} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=6, help="входов на книгу")
    ap.add_argument("--cap-open", type=int, default=4, help="открытых позиций на книгу")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--estimate", action="store_true", help="только цена в сутки, без вызовов модели")
    a = ap.parse_args(argv)
    if a.estimate:
        import arm_book as AB                                  # noqa: E402
        res = estimate_only(log=AB.guarded(print, limit=3000))
        with open(os.path.join(OUT, "AI-dry-estimate.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        if not a.no_publish and not res.get("error"):
            subprocess.run(["tools/publish.sh", "оценка цены судьи"], cwd=ROOT, check=False)
        return 0 if not res.get("error") else 1
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                      # noqa: E402
    s = run(a.cap, a.cap_open, log=AB.guarded(print, limit=3000))
    os.makedirs(OUT, exist_ok=True)
    txt = report(s)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, default=str)
    print(txt[-3500:])
    if not a.no_publish and not s.get("error"):
        subprocess.run(["tools/publish.sh", "сухой час судьи"], cwd=ROOT, check=False)
    return 0 if not s.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
