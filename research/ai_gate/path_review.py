#!/usr/bin/env python3
"""Разбор пути закрытых сделок судимых книг (спека 19 §11.2, этап U0).

Раз в час: закрытые позиции книг судьи (`gate_run.candidates`) с дня
рождения веток, которых ещё нет в разборе, получают меры пути
(`trade_path.metrics`) по минутным барам записи (`tail.TailBars` — тот
же источник, что у книг) и уровням книги (`rules.levels_of`). Строки —
`out/reviews/paths-ГГГГ-ММ-ДД.jsonl` (день выхода, в git), ключ — тот же,
что у решений (`gate_run.key_of`). Открытые не разбираются: путь у них не
кончился. Модель здесь не нужна, цена ноль.

Позиция без баров в окне — строка с `shape: no_bars`: «не измерено»
записано, а не пропущено молча. Нет сводки часа у `wave.Market` — ход
рынка None.

**Разбор судьёй (§11.3, U1).** Сделка, по которой ветка `ai_news`
выносила решение моделью (open/skip с вердиктом), после разбора пути
отдаётся модели ещё раз: досье на момент входа как было (запись
`out/record/dossiers-*.jsonl`), решение с причинами, исход и путь — и
модель пишет, было ли решение верным по тогдашним данным, какой критерий
подвёл или спас, и один проверяемый урок либо пустой («одного случая
мало»). Строка `kind: review` ложится в журнал решений того дня, когда
разбор сделан, — тем же забором суточной цены, что входы
(`gate_run.BUDGET_DAY_USD`): разбор не вправе съесть деньги судьи. За
проход — не больше `REVIEW_CAP` разборов, старые первыми; сделка без
досье в записи разбирается без него, и это записано (`dossier_found`).
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import gate_run as G                                          # noqa: E402
import trade_path as TP                                       # noqa: E402

OUT = os.path.join(HERE, "out")
REVIEWS = os.path.join(OUT, "reviews")
LATEST = os.path.join(OUT, "paths_latest.json")
NOMINAL_MARGIN = 25.0          # уровни книги при номинальной марже: тиры ставки на малых нотионалах одни
REVIEW_CAP = 40                # разборов за проход: первый проход не съедает сутки судьи разом


def load_dossiers(keys):
    """ключ → досье ветки ai_news на момент входа из записи (нет записи — нет ключа)."""
    want, out = set(keys), {}
    for p in sorted(glob.glob(os.path.join(G.RECORD, "dossiers-*.jsonl"))):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if '"ai_news"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("branch") == "ai_news" and r.get("key") in want and r.get("dossier"):
                        out[r["key"]] = r["dossier"]
        except OSError:
            continue
    return out


def reviews(paths, client, log, now, dry=False, cap=REVIEW_CAP):
    """Разбор судьёй закрытых сделок с решением ai_news, ещё не разобранных."""
    prev = G.read_decisions()
    done = {r["key"] for r in prev if r.get("kind") == "review"}
    dec = {r["key"]: r for r in prev if r.get("kind") == "entry" and r.get("branch") == "ai_news"}
    todo = [p for p in sorted(paths, key=lambda x: float(x["exit_ts"]))
            if p["key"] not in done and p["key"] in dec
            and dec[p["key"]].get("decision") in ("open", "skip") and not dec[p["key"]].get("no_verdict")]
    todo = todo[:cap]
    spent = G.spent_today(prev, now)
    doss = load_dossiers([p["key"] for p in todo])
    rows, st = [], {"todo": len(todo), "done": 0, "no_dossier": 0, "budget_stop": 0, "cost": 0.0}
    for p in todo:
        e = dec[p["key"]]
        outcome = {"exit": p.get("exit"), "pnl_on_margin": p.get("pnl_frac"),
                   "lived_hours": (p.get("path") or {}).get("life_h"),
                   "closed_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(float(p["exit_ts"])))}
        d = G.J.review_dossier(doss.get(p["key"]) or {"missing": "dossier not recorded"}, e, outcome,
                               dict(p.get("path") or {}, words=p.get("words_en")))
        if p["key"] not in doss:
            st["no_dossier"] += 1
        if client is None or dry:
            res = {"verdict": "unclear", "no_verdict": "сухой прогон" if dry else "ключа нет", "model": G.J.MODEL}
        elif spent >= G.BUDGET_DAY_USD:
            res = {"verdict": "unclear", "no_verdict": "бюджет суток", "model": G.J.MODEL}
            st["budget_stop"] += 1
        else:
            res = G.J.ask_review(client, d)
            spent += res.get("cost_usd") or 0
            st["cost"] += res.get("cost_usd") or 0
        row = {"t": now, "kind": "review", "branch": "ai_news", "key": p["key"], "book": p["book"], "sym": p["sym"],
               "side": p.get("side"), "at": p["at"], "exit_ts": p["exit_ts"], "exit": p.get("exit"),
               "pnl_frac": p.get("pnl_frac"), "decision": e.get("decision"), "dossier_found": p["key"] in doss,
               **{f: res.get(f) for f in ("verdict", "confidence", "failed", "saved", "lesson", "notes", "no_verdict",
                                          "served_model", "usage", "cost_usd", "latency_s", "request_id",
                                          "prompt_v", "model", "effort")}}
        rows.append(row)
        st["done"] += 1
        log(f"разбор {p['key']}: решение {e.get('decision')} → {row['verdict']}"
            + (f" ({row['no_verdict']})" if row.get("no_verdict") else "")
            + (f"; урок: {row['lesson']['when']} → {row['lesson']['do']}" if row.get("lesson") else ""))
    if rows:
        G.write_rows(rows)
    return st


def read_paths(days=None):
    rows = []
    paths = sorted(glob.glob(os.path.join(REVIEWS, "paths-*.jsonl")))
    if days:
        paths = paths[-int(days):]
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


def write_paths(rows):
    os.makedirs(REVIEWS, exist_ok=True)
    by = {}
    for r in rows:
        by.setdefault(G.day_of(float(r["exit_ts"])), []).append(r)
    for d, xs in by.items():
        with open(os.path.join(REVIEWS, f"paths-{d}.jsonl"), "a", encoding="utf-8") as f:
            for x in xs:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")


def review(rec, book, src, mkt, R):
    at, end = float(rec["at"]), float(rec["exit_ts"])
    bars = src.bars(rec["sym"], at, end) or []
    lv = None
    try:
        lv = R.levels_of(dict(rec, margin=rec.get("margin") or NOMINAL_MARGIN), book)
    except Exception:                                        # noqa: BLE001
        lv = None
    name_move = mkt.move(rec["sym"], at, end) if mkt else None
    mkt_move = mkt.wave(at, end) if mkt else None
    m = TP.metrics(bars, rec.get("side") or R.side_of(book), rec["entry_px"], at, end,
                   take_px=(lv or {}).get("take_px"), floor_px=(lv or {}).get("floor_px"),
                   lev=rec.get("lev"), hold_h=R.hold_of(book), name_move=name_move, market_move=mkt_move)
    return {"t": time.time(), "kind": "path", "key": G.key_of(book, rec), "book": book, "sym": rec["sym"],
            "side": rec.get("side") or R.side_of(book), "at": at, "exit_ts": end, "exit": rec.get("exit"),
            "pnl_frac": rec.get("pnl"), "take_px": (lv or {}).get("take_px"), "floor_px": (lv or {}).get("floor_px"),
            "path": m, "words": TP.words(m), "words_en": TP.words(m, "en")}


def run(log=print, now=None, src=None, mkt=None, books=None, client=None, dry=False, do_review=True):
    t0 = time.time()
    now = now or time.time()
    import rules as R                                         # noqa: E402
    if books is None:
        books, why = G.candidates(log)
        if why:
            return {"error": f"книги не загружены: {why}"}
    if src is None:
        import tail as TL                                     # noqa: E402
        src = TL.TailBars(log=lambda *a: None, cache=TL.BARS_CACHE)
    if mkt is None:
        try:
            import wave as WV                                 # noqa: E402
            mkt = WV.Market()
        except Exception as e:                                # noqa: BLE001
            log(f"ход рынка недоступен: {e}")
            mkt = None
    done = {r["key"] for r in read_paths()}
    new, stats = [], {"closed": 0, "new": 0, "no_bars": 0, "by_shape": {}, "by_touch": {}}
    for book, _side in G.BOOKS:
        for r in books.get(book) or []:
            if (r.get("state") or "closed") != "closed" or float(r["at"]) < G.GATE_SINCE or not r.get("exit_ts"):
                continue
            stats["closed"] += 1
            k = G.key_of(book, r)
            if k in done:
                continue
            try:
                row = review(r, book, src, mkt, R)
            except Exception as e:                            # noqa: BLE001
                log(f"{k}: разбор не удался: {type(e).__name__}: {e}")
                continue
            new.append(row)
            m = row["path"]
            stats["new"] += 1
            if m.get("shape") == "no_bars":
                stats["no_bars"] += 1
            stats["by_shape"][m.get("shape")] = stats["by_shape"].get(m.get("shape"), 0) + 1
            stats["by_touch"][m.get("first_touch")] = stats["by_touch"].get(m.get("first_touch"), 0) + 1
            log(f"путь {k}: {row['words']}")
    if new:
        write_paths(new)
    allp = read_paths()
    rv = None
    if do_review:
        key = G.J.read_key()
        if client is None and key and not dry:
            client = G.J.make_client(key)
        try:
            rv = reviews(allp, client, log, now, dry=dry)
        except Exception as e:                                # noqa: BLE001
            rv = {"error": f"{type(e).__name__}: {e}"[:200]}
            log(f"разбор судьёй не прошёл: {rv['error']}")
    tot = {"n": len(allp), "no_bars": sum(1 for r in allp if r["path"].get("shape") == "no_bars"),
           "by_shape": {}, "by_touch": {}, "by_exit": {}}
    for r in allp:
        for key, fld in (("by_shape", r["path"].get("shape")), ("by_touch", r["path"].get("first_touch")),
                         ("by_exit", r.get("exit"))):
            tot[key][str(fld)] = tot[key].get(str(fld), 0) + 1
    s = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "secs": round(time.time() - t0, 1),
         "last_pass": stats, "total": tot, "reviews": rv}
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    log(f"разбор путей: закрытых {stats['closed']}, новых {stats['new']} (без баров {stats['no_bars']}); "
        f"всего {tot['n']}; разборов судьёй {(rv or {}).get('done')} (${(rv or {}).get('cost', 0):.3f}); {s['secs']} с")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--dry", action="store_true", help="без вызовов модели")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                     # noqa: E402
    s = run(log=AB.guarded(print, limit=2500), dry=a.dry)
    if not a.no_publish and not s.get("error") and ((s.get("last_pass") or {}).get("new") or (s.get("reviews") or {}).get("done")):
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "пути сделок судьи"], cwd=ROOT, check=False)
    return 0 if not s.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
