#!/usr/bin/env python3
"""Запись вперёд судьи (спека 19, этап N3): решения в реальном времени.

Раз в 15 мин из сторожа. Ничего не торгует и ни в одну книгу не пишет:
пишет ЖУРНАЛ РЕШЕНИЙ, из которого ветки считаются кассой тем же ядром, что
книги (`gate_books.py`). Журнал — запись класса A: задним числом её не
досчитать (решение обязано быть принято до того, как стал известен исход).

Что делает за проход:
1. **Вход.** Кандидаты книг Depth (`optimal` — лонги, `optimal_h` —
   шорты; шорты после возраста и охраны, как книга живёт) с часом входа не
   раньше `GATE_SINCE` и не старше `LATE_H`, ещё без решения. Досье — на
   момент входа (ничего позже него), спрашиваются `ai_news` и `ai_plain`;
   5 % входов (по отпечатку ключа, не жребием прогона) спрашиваются второй
   раз — повторяемость (§6).
2. **Сторож** (§5a). Позиции, которые `ai_news` впустил и которые открыты:
   событие по имени после прошлой проверки — новость с привязкой, событие
   площадки или взлом, сдвиг доли лонгов Bybit на ≥ 10 п.п. от опорной —
   и модель спрашивается «держать или закрыть». Без события раз в 6 ч —
   строка `heartbeat` без модели, с возрастом обоих сборщиков фона.
3. **Забор цены.** Потрачено за сутки UTC ≥ `BUDGET_DAY_USD` — вызовов
   больше нет, строки идут с `no_verdict: бюджет суток` (вход — «открыть»,
   сторож — «держать»); на странице это видно.

Журнал: `out/decisions/decisions-ГГГГ-ММ-ДД.jsonl` (в git, без досье) и
`out/record/` (досье целиком, вне git). Сводка — `out/latest.json`.

    gate_run.py [--no-publish] [--dry]
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import context as CTX                                        # noqa: E402
import judge as J                                            # noqa: E402

OUT = os.path.join(HERE, "out")
DECISIONS = os.path.join(OUT, "decisions")
RECORD = os.path.join(OUT, "record")
WATCH = os.path.join(RECORD, "watch.json")
LATEST = os.path.join(OUT, "latest.json")
PUBLISHED = os.path.join(RECORD, "published_hour.txt")
NEWS_LATEST = os.path.join(ROOT, "research", "news", "out", "latest.json")
MS_LATEST = os.path.join(ROOT, "research", "market_state", "out", "latest.json")
TRAIN_WAIT = os.path.join(ROOT, "research", "s8_loop", "out", "train_wait.flag")

GATE_SINCE = 1792346400            # 2026-10-18 18:00 UTC — день рождения веток (§9 N3)
BOOKS = (("optimal", "long"), ("optimal_h", "short"))
LATE_H = 6                         # кандидат старше — не судится (досье на момент входа уже бы не собрать честно)
REPEAT_MOD = 20                    # 1 из 20 входов спрашивается повторно (5 %)
BUDGET_DAY_USD = 8.0               # забор: ≈ 2.7 × ожидаемой цены суток (§8)
CROWD_SHIFT = 0.10                 # сдвиг доли лонгов Bybit для события сторожа
HEARTBEAT_S = 6 * 3600
TRAIN_WAIT_STALE_S = 3600        # флаг старше часа — застрял: судья не встаёт молча навсегда
NEWS_STALE_S = 45 * 60
MS_STALE_S = 2 * 3600
H = 3600


def _peak_mb():
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    except Exception:                                        # noqa: BLE001
        return None


def key_of(book, r):
    return f"{book}|{r['sym']}|{int(float(r['at']))}"


def holder_of(recs, book, dec, closes, r):
    """Ключ позиции ВЕТКИ, которая держит имя `r` в час его входа, или None.

    Владелец 20.10: «судья рассудил десятки входов, хотя по факту мы
    использовали несколько». 85 % вызовов (89 из 105, 19–20.10) были
    повторными часовыми сигналами по имени, которое ветка уже держала, —
    книга выбрасывает их правилом «одно имя — одна позиция» ДО кассы, в
    любом депозите одинаково, и решение по ним ничего не меняло.

    Здесь то же правило, что у книги (`run_d6.one_per_name` после гейта
    плеча, `run_paper.build_rows`), над записями ветки: отклонённые
    судьёй убраны, ещё не рассуженные стоят (книга открывает их по
    умолчанию), закрытия сторожа укорачивают позицию (`dec`/`closes` —
    решения этой ветки). Порядок — как у книги: час, затем |прогноз|.
    """
    import gate_books as GB                                    # noqa: E402
    sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
    import rules as R                                          # noqa: E402
    t = int(float(r["at"]))
    kr = key_of(book, r)
    same = [x for x in recs if x.get("sym") == r.get("sym") and int(float(x["at"])) <= t]
    ml = R.min_lev_of(book)
    if ml is not None:
        same = [x for x in same if float(x["lev"]) >= ml]
    kept, _cut, _unj = GB.filt(same, book, dec)
    if closes:
        kept, _n, _h = GB.apply_closes(kept, book, closes, R.JUDGE_EXIT)
    until, who = None, None
    for x in sorted(kept, key=lambda x: (int(float(x["at"])), -float(x.get("fwd") or 0))):
        kx = key_of(book, x)
        if kx == kr:
            return who if (until is not None and until > t) else None
        if until is not None and until > int(float(x["at"])):
            continue                                           # повтор — выброшен книгой
        until, who = int(float(x["exit_ts"])), kx
    return None


def is_repeat(key):
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % REPEAT_MOD == 0


def day_of(t):
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def read_decisions(days=None):
    rows = []
    paths = sorted(glob.glob(os.path.join(DECISIONS, "decisions-*.jsonl")))
    for p in (paths[-days:] if days else paths):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


def spent_today(rows, now):
    d = day_of(now)
    return round(sum(r.get("cost_usd") or 0 for r in rows if day_of(r.get("t", 0)) == d), 4)


def file_age(path, now):
    try:
        return now - os.path.getmtime(path)
    except OSError:
        return None


def pick_new(cands, judged, now):
    """Кандидаты без решения, не раньше дня рождения и не старше LATE_H."""
    out = []
    for book, side, r in cands:
        at = float(r["at"])
        k = key_of(book, r)
        if at >= GATE_SINCE and now - at <= LATE_H * H and k not in judged:
            out.append((book, side, r, k))
    return sorted(out, key=lambda x: float(x[2]["at"]))


def watch_triggers(w, sym, now_ms, news, events, crowd_now):
    """Событие для сторожа с прошлой проверки → список причин (пусто — нет события)."""
    last = int(w.get("last_check_ms", 0))
    why = []
    n = [x for x in news if last < x["t"] <= now_ms and sym in (x.get("tags") or {})]
    if n:
        why.append(f"news:{len(n)}")
    e = CTX.events_for(events, sym, now_ms, since_ms=last)
    if e:
        why.append(f"event:{len(e)}")
    ref = w.get("crowd_ref")
    if ref is not None and crowd_now is not None and abs(crowd_now - ref) >= CROWD_SHIFT:
        why.append(f"crowd:{ref:.3f}->{crowd_now:.3f}")
    return why


def write_rows(rows, full=None):
    os.makedirs(DECISIONS, exist_ok=True)
    for r in rows:
        with open(os.path.join(DECISIONS, f"decisions-{day_of(r['t'])}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    if full:
        os.makedirs(RECORD, exist_ok=True)
        with open(os.path.join(RECORD, f"dossiers-{day_of(time.time())}.jsonl"), "a", encoding="utf-8") as f:
            for x in full:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")


def candidates(log):
    """Позиции книг Depth так, как они живут (шорты — после возраста и охраны)."""
    import run_pair as RPair                                   # noqa: E402
    import run_paper as RP                                     # noqa: E402
    import instruments_refresh as IR                           # noqa: E402
    longs, why_l = RPair.long_recs(log=log)
    shorts, why_s = RPair.short_recs(log=log)
    if why_l or why_s:
        return None, why_l or why_s
    quiet = lambda *a: None                                    # noqa: E731
    now = time.time()
    books = {"optimal": longs.get("optimal") or []}
    kept, _ = RP.age_shorts(shorts.get("optimal_h") or [], "optimal_h", launch=IR.launches(), log=quiet, now=now)
    kept, _ = RP.guard_shorts(kept, "optimal_h", log=quiet, now=now)
    books["optimal_h"] = kept
    return books, None


def run(log=print, client=None, dry=False, now=None):
    t0 = time.time()
    now = now or time.time()
    wait_age = file_age(TRAIN_WAIT, now)
    if wait_age is not None and wait_age < TRAIN_WAIT_STALE_S:
        return {"skipped": "обучение S8 ждёт памяти (train_wait.flag) — проход уступает"}
    if wait_age is not None:
        log(f"флаг ожидания обучения висит {wait_age / 60:.0f} мин — считаю застрявшим и не уступаю")
    prev = read_decisions(days=3)
    judged = {r["key"] for r in prev if r.get("kind") == "entry" and r.get("branch") in ("ai_news", "ai_plain")}
    entry_ok = {r["key"]: r for r in prev if r.get("kind") == "entry" and r.get("branch") == "ai_news"}
    spent = spent_today(prev, now)
    key = J.read_key()
    if client is None and key and not dry:
        client = J.make_client(key)
    books, why = candidates(log)
    if why:
        return {"error": f"книги не загружены: {why}"}
    state, market_rows, events = CTX.load_state(days=4)
    news = CTX.load_news()
    out_rows, full = [], []
    stats = {"entry_new": 0, "calls": 0, "cost": 0.0, "watched": 0, "watch_calls": 0, "closes": 0, "heartbeats": 0}

    def call(kind, d):
        nonlocal spent
        if client is None:
            return {"decision": "open" if kind == "entry" else "hold",
                    "no_verdict": "ключа нет" if not key else "сухой прогон", "model": J.MODEL}
        if spent >= BUDGET_DAY_USD:
            return {"decision": "open" if kind == "entry" else "hold", "no_verdict": "бюджет суток", "model": J.MODEL}
        row = J.ask(client, kind, d)
        spent += row.get("cost_usd") or 0
        stats["calls"] += 1
        stats["cost"] += row.get("cost_usd") or 0
        return row

    cands = [(b, s, r) for b, s in BOOKS for r in books.get(b) or []]
    # решения веток к этому проходу — обновляются по ходу: отклонённый
    # ранний вход освобождает имя для позднего в том же проходе
    import gate_books as GB                                    # noqa: E402
    dec_by = {b: dict(v) for b, v in GB.entry_index(prev).items()}
    closes_news = GB.close_index(prev)
    stats["held"] = 0
    for book, side, r, k in pick_new(cands, judged, now):
        recs = books[book]
        held = {br: holder_of(recs, book, dec_by.setdefault(br, {}),
                              closes_news if br == "ai_news" else {}, r)
                for br in ("ai_news", "ai_plain")}
        variants = [(br, w) for br, w in (("ai_news", True), ("ai_plain", False)) if held[br] is None]
        for br in ("ai_news", "ai_plain"):
            if held[br] is not None:
                # имя держит ранний вход ветки — книга выбросит и этот;
                # модель не спрашивается, строка честно говорит почему
                row = {"t": now, "kind": "entry", "branch": br, "key": k, "book": book, "sym": r["sym"],
                       "side": side, "at": float(r["at"]), "late_min": round((now - float(r["at"])) / 60, 1),
                       "decision": "held", "held_by": held[br], "cost_usd": 0.0}
                out_rows.append(row)
                full.append(row)
                dec_by[br][k] = "held"
                stats["held"] += 1
        if not variants:
            log(f"вход {k}: имя держат обе ветки ({held['ai_news']}) — не судится")
            continue
        kw, nw, cov = CTX.build("entry", r, book, side, now, recs, state, market_rows, events, news)
        variants = [(br, nw if w else None) for br, w in variants]
        if held["ai_news"] is None and is_repeat(k):
            variants.append(("ai_news_repeat", nw))
        for branch, with_news in variants:
            d = J.dossier("entry", r, book, side, float(r["at"]), news=with_news, **kw)
            res = call("entry", d)
            row = {"t": now, "kind": "entry", "branch": branch, "key": k, "book": book, "sym": r["sym"],
                   "side": side, "at": float(r["at"]), "late_min": round((now - float(r["at"])) / 60, 1),
                   "news_n": len(with_news) if with_news is not None else None, "cov": cov,
                   **{f: res.get(f) for f in ("decision", "confidence", "reasons", "news_used", "no_verdict",
                                              "served_model", "usage", "cost_usd", "latency_s", "request_id",
                                              "prompt_v", "model", "effort")}}
            out_rows.append(row)
            full.append(dict(row, dossier=d))
            if branch in dec_by:
                dec_by[branch][k] = row.get("decision")
            if branch == "ai_news":
                entry_ok[k] = row
        stats["entry_new"] += 1
        log(f"вход {k}: " + ", ".join(f"{x['branch']}={x['decision']}{'(' + x['no_verdict'] + ')' if x.get('no_verdict') else ''}"
                                       for x in out_rows if x["key"] == k))

    # --- сторож ------------------------------------------------------------
    watch = {}
    try:
        with open(WATCH, encoding="utf-8") as f:
            watch = json.load(f)
    except (OSError, ValueError):
        pass
    now_ms = int(now * 1000)
    news_age, ms_age = file_age(NEWS_LATEST, now), file_age(MS_LATEST, now)
    fresh = (news_age is not None and news_age <= NEWS_STALE_S) and (ms_age is not None and ms_age <= MS_STALE_S)
    for book, side in BOOKS:
        recs = books.get(book) or []
        for r in recs:
            if (r.get("state") or "closed") != "open" or float(r["at"]) < GATE_SINCE:
                continue
            k = key_of(book, r)
            e = entry_ok.get(k)
            if not e or e.get("decision") != "open":
                continue                                  # ветка ai_news эту позицию не открывала
            if holder_of(recs, book, dec_by.get("ai_news", {}), closes_news, r) is not None:
                continue                                  # повтор по держимому имени: книга его выбросила
            w = watch.setdefault(k, {"last_check_ms": int(float(r["at"]) * 1000), "last_hb": float(r["at"])})
            if w.get("closed"):
                continue
            stats["watched"] += 1
            c = CTX.crowd_of(state, r["sym"], now_ms) or {}
            crowd_now = (c.get("bybit") or {}).get("now")
            if w.get("crowd_ref") is None:
                ec = CTX.crowd_of(state, r["sym"], int(float(r["at"]) * 1000)) or {}
                w["crowd_ref"] = (ec.get("bybit") or {}).get("now")
            trig = watch_triggers(w, r["sym"], now_ms, news, events, crowd_now) if fresh else []
            if trig:
                kw, nw, cov = CTX.build("hold", r, book, side, now, recs, state, market_rows, events, news)
                d = J.dossier("hold", r, book, side, now, news=nw, **kw)
                d["trigger"] = trig
                res = call("hold", d)
                row = {"t": now, "kind": "hold", "branch": "ai_news_x", "key": k, "book": book, "sym": r["sym"],
                       "side": side, "at": float(r["at"]), "trigger": trig, "news_n": len(nw), "cov": cov,
                       **{f: res.get(f) for f in ("decision", "confidence", "reasons", "news_used", "no_verdict",
                                                  "served_model", "usage", "cost_usd", "latency_s", "request_id",
                                                  "prompt_v", "model", "effort")}}
                out_rows.append(row)
                full.append(dict(row, dossier=d))
                stats["watch_calls"] += 1
                if crowd_now is not None:
                    w["crowd_ref"] = crowd_now
                if row["decision"] == "close" and not row.get("no_verdict"):
                    w["closed"] = now
                    stats["closes"] += 1
                log(f"сторож {k}: {trig} → {row['decision']} {row.get('no_verdict') or ''}")
            elif now - float(w.get("last_hb", 0)) >= HEARTBEAT_S:
                out_rows.append({"t": now, "kind": "heartbeat", "branch": "ai_news_x", "key": k, "book": book,
                                 "sym": r["sym"], "side": side, "at": float(r["at"]), "decision": "hold",
                                 "no_verdict": None if fresh else "фон не свеж",
                                 "news_age_s": None if news_age is None else round(news_age),
                                 "state_age_s": None if ms_age is None else round(ms_age)})
                w["last_hb"] = now
                stats["heartbeats"] += 1
            if fresh:
                w["last_check_ms"] = now_ms
    if not dry:
        write_rows(out_rows, full)
        os.makedirs(RECORD, exist_ok=True)
        tmp = WATCH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(watch, f)
        os.replace(tmp, WATCH)
    s = summary(read_decisions(days=2) if not dry else prev + out_rows, now, stats, t0, fresh, news_age, ms_age)
    if not dry:
        with open(LATEST, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
    log(f"проход: новых входов {stats['entry_new']}, вызовов {stats['calls']} (${stats['cost']:.4f}), "
        f"под сторожем {stats['watched']}, вызовов сторожа {stats['watch_calls']}, закрытий {stats['closes']}, "
        f"heartbeat {stats['heartbeats']}; за сутки потрачено ${s['today']['usd']}; {time.time() - t0:.1f} с; "
        f"пик памяти {_peak_mb()} МБ")
    return s


def summary(rows, now, stats, t0, fresh, news_age, ms_age):
    d = day_of(now)
    today = [r for r in rows if day_of(r.get("t", 0)) == d]
    allent = [r for r in today if r.get("kind") == "entry" and r.get("branch") == "ai_news"]
    # «held» — повтор по держимому имени, модели не показан (20.10): в доле
    # отказов его нет, он считается отдельно
    ent = [r for r in allent if r.get("decision") != "held"]
    ok = [r for r in ent if not r.get("no_verdict")]
    skip = sum(1 for r in ok if r.get("decision") == "skip")
    pairs = {}
    for r in today:
        if r.get("kind") == "entry" and r.get("branch") in ("ai_news", "ai_news_repeat") and not r.get("no_verdict"):
            pairs.setdefault(r["key"], {})[r["branch"]] = r["decision"]
    both = [p for p in pairs.values() if len(p) == 2]
    skip_pct = round(100 * skip / len(ok), 1) if ok else None
    return {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "since": GATE_SINCE,
            "secs": round(time.time() - t0, 1), "last_pass": stats, "background_fresh": fresh,
            "news_age_s": None if news_age is None else round(news_age),
            "state_age_s": None if ms_age is None else round(ms_age),
            "today": {"usd": round(sum(r.get("cost_usd") or 0 for r in today), 4), "budget_usd": BUDGET_DAY_USD,
                      "entries": len(ent), "held": len(allent) - len(ent), "skips": skip, "skip_pct": skip_pct,
                      "skip_alarm": bool(skip_pct is not None and skip_pct > 60),
                      "no_verdict": sum(1 for r in ent if r.get("no_verdict")),
                      "plain_skips": sum(1 for r in today if r.get("branch") == "ai_plain" and r.get("decision") == "skip"
                                         and not r.get("no_verdict")),
                      "repeat_pairs": len(both), "repeat_same": sum(1 for p in both if p["ai_news"] == p["ai_news_repeat"]),
                      "watch_calls": sum(1 for r in today if r.get("kind") == "hold"),
                      "closes": sum(1 for r in today if r.get("kind") == "hold" and r.get("decision") == "close"
                                    and not r.get("no_verdict")),
                      "heartbeats": sum(1 for r in today if r.get("kind") == "heartbeat")},
            "recent": [{k: r.get(k) for k in ("t", "kind", "branch", "book", "sym", "side", "decision", "confidence",
                                              "reasons", "no_verdict", "trigger", "cost_usd")}
                       for r in sorted(rows, key=lambda r: -r.get("t", 0))
                       if r.get("kind") in ("entry", "hold") and r.get("branch") != "ai_news_repeat"][:40]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--dry", action="store_true", help="без вызовов модели и без записи")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
    import arm_book as AB                                      # noqa: E402
    s = run(log=AB.guarded(print, limit=2500), dry=a.dry)
    if s.get("error") or s.get("skipped"):
        print(s.get("error") or s.get("skipped"))
        return 1 if s.get("error") else 0
    hour = time.strftime("%Y-%m-%dT%H", time.gmtime())
    try:
        last = open(PUBLISHED, encoding="utf-8").read().strip()
    except OSError:
        last = ""
    if not a.dry and not a.no_publish and last != hour:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "ai-gate " + hour], cwd=ROOT, check=False)
        with open(PUBLISHED, "w", encoding="utf-8") as f:
            f.write(hour)
    return 0


if __name__ == "__main__":
    sys.exit(main())
