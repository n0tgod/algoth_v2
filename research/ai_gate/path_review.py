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


def run(log=print, now=None, src=None, mkt=None, books=None):
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
    tot = {"n": len(allp), "no_bars": sum(1 for r in allp if r["path"].get("shape") == "no_bars"),
           "by_shape": {}, "by_touch": {}, "by_exit": {}}
    for r in allp:
        for key, fld in (("by_shape", r["path"].get("shape")), ("by_touch", r["path"].get("first_touch")),
                         ("by_exit", r.get("exit"))):
            tot[key][str(fld)] = tot[key].get(str(fld), 0) + 1
    s = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "secs": round(time.time() - t0, 1),
         "last_pass": stats, "total": tot}
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    log(f"разбор путей: закрытых {stats['closed']}, новых {stats['new']} (без баров {stats['no_bars']}); "
        f"всего {tot['n']}; {s['secs']} с")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    import arm_book as AB                                     # noqa: E402
    s = run(log=AB.guarded(print, limit=2500))
    if not a.no_publish and not s.get("error") and (s.get("last_pass") or {}).get("new"):
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "пути сделок судьи"], cwd=ROOT, check=False)
    return 0 if not s.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
