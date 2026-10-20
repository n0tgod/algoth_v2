#!/usr/bin/env python3
"""Ветки судьи спеки 19 кассой (этап N3): из журнала решений и позиций книг.

Шесть веток у каждой книги Depth (`optimal` — лонги, `optimal_h` — шорты),
все с дня рождения `GATE_SINCE`, все НЕТТО тем же путём, что сами книги
(`run_paper.build_rows` → `costs.apply_to_rows` → `run_paper._stats`):

| ветка | вход | выход |
|---|---|---|
| книга | лист как есть | правила книги |
| `ai_news` | без входов, где судья с новостями сказал skip | правила книги |
| `ai_plain` | без входов, где судья без новостей сказал skip | правила книги |
| `rand` | в каждом часе убрано столько же входов, сколько у `ai_news`, жребием | правила книги |
| `ai_news_x` | как `ai_news` | + закрытие по слову сторожа (причина «судья») |
| `rand_x` | как `ai_news` | + столько же случайных закрытий тех же часов держания |
| `delist` | лист как есть | + закрытие при объявлении Bybit о делистинге имени |

Вход без решения (поздний, проход уступил обучению) остаётся во всех ветках
и считается числом — «не судили» не выдаётся за «впустили». Решение
`no_verdict` — «открыть», как и записано. Закрытие сторожем ложится на
отметку часа ПОСЛЕ решения (`wave.guard_record`), цена выхода — путь ядра
на этой отметке, издержки — рыночного выхода. Жребий — 20 зёрен; печатается
медиана и доля зёрен не хуже ветки модели.

**До суда (не раньше 2026-11-10) это не вердикт**, а состояние записи; дни
записи печатаются числом.

    run research/ai_gate/gate_books.py
"""
import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import context as CTX                                        # noqa: E402
import gate_run as G                                         # noqa: E402

OUT_MD = os.path.join(HERE, "out", "AI-gate-books.md")
OUT_JSON = os.path.join(HERE, "out", "AI-gate-books.json")
SEEDS = 20
JUDGE_DAY = "2026-11-10"
H = 3600
PERP_RE = re.compile(r"\b([0-9A-Z]{2,25}USDT)\b")


# ------------------------------------------------------------ ветки (чистые функции)

def entry_index(rows):
    """{ветка: {ключ: решение}} по строкам входа; повтор — не ветка."""
    out = {}
    for r in rows:
        if r.get("kind") == "entry" and r.get("branch") in ("ai_news", "ai_plain", "ai_learn"):
            out.setdefault(r["branch"], {})[r["key"]] = r.get("decision")
    return out


def close_index(rows):
    """{ключ: момент закрытия} — первое «close» сторожа с вердиктом."""
    out = {}
    for r in sorted(rows, key=lambda r: r.get("t", 0)):
        if r.get("kind") == "hold" and r.get("decision") == "close" and not r.get("no_verdict"):
            out.setdefault(r["key"], float(r["t"]))
    return out


def filt(recs, book, dec):
    """→ (оставленные, убрано, без решения)."""
    kept, cut, unj = [], 0, 0
    for r in recs:
        d = dec.get(G.key_of(book, r))
        if d is None:
            unj += 1
            kept.append(r)
        elif d == "skip":
            cut += 1
        else:
            kept.append(r)
    return kept, cut, unj


def cut_by_hour(recs, book, dec):
    """{час входа: сколько убрал судья} — для жребия той же формы."""
    n = {}
    for r in recs:
        if dec.get(G.key_of(book, r)) == "skip":
            h = int(float(r["at"]))
            n[h] = n.get(h, 0) + 1
    return n


def rand_cut(recs, n_by_hour, rng, pool=None):
    """Жребий той же формы, что судья: столько же отказов в тот же час.

    `pool` — ключи входов, которые судья РЕШАЛ моделью (open/skip). С 20.10
    повторы по имени, которое ветка держит, модели не показываются
    (`gate_run.holder_of`, решение «held»): книга выбрасывает их сама, и
    отказ жребия по такому повтору ничего не менял бы — контроль был бы
    слабее судьи. Записи вне пула жребий не трогает. `None` — прежний
    пул (все записи часа)."""
    by = {}
    keep = []
    for r in recs:
        if pool is not None and r.get("_key") not in pool:
            keep.append(r)
            continue
        by.setdefault(int(float(r["at"])), []).append(r)
    out = list(keep)
    for h, xs in by.items():
        drop = set(id(x) for x in rng.sample(xs, min(len(xs), n_by_hour.get(h, 0))))
        out += [x for x in xs if id(x) not in drop]
    if pool is not None:                 # служебный ключ в кассу не едет
        out = [{k: v for k, v in x.items() if k != "_key"} for x in out]
    return out


def k_of(rec, t):
    """Отметка часа после момента t (≥ 1); None — позиция уже вышла раньше."""
    import wave as WV                                          # noqa: E402
    p = WV.path_of(rec)
    if not p:
        return None
    k = max(1, math.ceil((t - float(rec["at"])) / H))
    closed = (rec.get("state") or "closed") == "closed"
    if closed and k >= p["K"]:
        return None
    return min(k, p["K"])


def close_at(rec, k, why):
    import wave as WV                                          # noqa: E402
    return WV.guard_record(rec, k, why=why)


def apply_closes(recs, book, closes, why):
    """Закрыть позиции по {ключ: момент}; → (записи, число закрытых, [(i, k)])."""
    out, n, hits = [], 0, []
    for i, r in enumerate(recs):
        t = closes.get(G.key_of(book, r))
        k = k_of(r, t) if t is not None else None
        if k is not None:
            out.append(close_at(r, k, why)); n += 1; hits.append(k)
        else:
            out.append(r)
    return out, n, hits


def rand_closes(recs, ks, rng, why):
    """Столько же закрытий тех же часов держания у случайных живых позиций."""
    import wave as WV                                          # noqa: E402
    paths = [WV.path_of(r) for r in recs]
    taken, out = set(), list(recs)
    for k in ks:
        alive = [i for i, p in enumerate(paths) if p and i not in taken
                 and (p["K"] > k or (recs[i].get("state") or "closed") == "open" and p["K"] >= k)]
        if not alive:
            continue
        i = rng.choice(alive)
        taken.add(i)
        out[i] = close_at(recs[i], k, why)
    return out


def delist_closes(recs, book, events):
    """{ключ: момент объявления} — позиции, открытые в момент объявления Bybit о делистинге имени."""
    anns = []
    for e in events:
        if e.get("venue") == "bybit" and "delist" in f"{e.get('kind')} {e.get('title')}".lower():
            anns.append((e["t"] / 1000.0, set(PERP_RE.findall(str(e.get("title") or "")))))
    out = {}
    for r in recs:
        at = float(r["at"])
        for t, syms in anns:
            if r["sym"] in syms and t >= at:
                out.setdefault(G.key_of(book, r), t)
    return out


# ------------------------------------------------------------ касса нетто

def cash_net(book, recs, now, ctx):
    """Касса книги НЕТТО: тот же путь, что у книг — строки, издержки, свод."""
    import run_paper as RP                                     # noqa: E402
    import costs as CO                                         # noqa: E402
    import long_guard as LG                                    # noqa: E402
    rows, _c, _o, _l = RP.build_rows({book: recs}, now=now, keys=[book], log=lambda *a: None)
    rows, cs = CO.apply_to_rows(rows, ctx)
    out = {}
    for d in LG.DEPS:
        sub = [r for r in rows if r.get("ruler") == book and int(r.get("dep", 0)) == int(d)
               and not r.get("sizing") and r.get("usd") is not None]
        st = RP._stats(sub, d) or {}
        out[int(d)] = {m: st.get(m) for m in ("final", "max_dd", "n", "win", "usd")}
    return out, cs.get("error")


def run(log=print):
    import costs as CO                                         # noqa: E402
    import rules as R                                          # noqa: E402
    import long_guard as LG                                    # noqa: E402
    t0 = time.time()
    R.DEPOSITS[:] = list(LG.DEPS)
    R.SIZINGS = (R.SIZING_COMPOUND,)
    books, why = G.candidates(log)
    if why:
        return {"error": f"книги не загружены: {why}"}
    now = time.time()
    rows = G.read_decisions()
    eidx = entry_index(rows)
    closes = close_index(rows)
    _s, _m, events = CTX.load_state(days=40)
    ctx = CO.context()
    days = round((now - G.GATE_SINCE) / 86400, 2)
    res = {"computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), "since": G.GATE_SINCE,
           "days": days, "judge_day": JUDGE_DAY, "seeds": SEEDS, "books": {}, "cost_error": None,
           "spent_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4)}
    for book, side in G.BOOKS:
        recs = [r for r in books.get(book) or [] if float(r["at"]) >= G.GATE_SINCE]
        b = {"side": side, "positions": len(recs), "branches": {}, "counts": {}}
        if not recs:
            b["why"] = "позиций с дня рождения ещё нет"
            res["books"][book] = b
            continue
        news_dec, plain_dec = eidx.get("ai_news", {}), eidx.get("ai_plain", {})
        learn_dec = eidx.get("ai_learn", {})
        kept_n, cut_n, unj_n = filt(recs, book, news_dec)
        kept_p, cut_p, unj_p = filt(recs, book, plain_dec)
        kept_l, cut_l, _unj_l = filt(recs, book, learn_dec)
        x_recs, n_close, ks = apply_closes(kept_n, book, closes, R.JUDGE_EXIT)
        dl = delist_closes(recs, book, events)
        d_recs, n_dl, _ = apply_closes(recs, book, dl, R.DELIST_EXIT)
        b["counts"] = {"ai_news_cut": cut_n, "ai_plain_cut": cut_p, "ai_learn_cut": cut_l, "unjudged": unj_n,
                       "judge_closes": n_close, "delist_closes": n_dl}
        for name, rr in (("book", recs), ("ai_news", kept_n), ("ai_plain", kept_p),
                         ("ai_news_x", x_recs), ("delist", d_recs)):
            c, err = cash_net(book, rr, now, ctx)
            b["branches"][name] = c
            res["cost_error"] = res["cost_error"] or err
        nbh = cut_by_hour(recs, book, news_dec)
        pool = {k for k, v in news_dec.items() if v in ("open", "skip")}
        keyed = [dict(r, _key=G.key_of(book, r)) for r in recs]
        b["counts"]["held"] = sum(1 for v in news_dec.values() if v == "held")
        for name, make, ref in (("rand", lambda rng: rand_cut(keyed, nbh, rng, pool), "ai_news"),
                                ("rand_x", lambda rng: rand_closes(kept_n, ks, rng, R.JUDGE_EXIT), "ai_news_x")):
            draws = []
            for s in range(SEEDS):
                c, _ = cash_net(book, make(random.Random(1000 + s)), now, ctx)
                draws.append(c)
            agg = {}
            for d in (1000, 10000):
                fs = sorted(x[d]["final"] for x in draws if x[d]["final"] is not None)
                mine = (b["branches"][ref].get(d) or {}).get("final")
                agg[d] = {"median_final": fs[len(fs) // 2] if fs else None,
                          "not_worse_share": (round(sum(1 for f in fs if mine is not None and f >= mine) / len(fs), 2)
                                              if fs and mine is not None else None)}
            b["branches"][name] = agg
        # Учащаяся ветка (§11.4) судится СВОИМ окном — с её дня рождения: до
        # него она по построению равна книге, и общее окно разбавило бы
        # разность. На том же окне — книга и ai_news.
        lw = [r for r in recs if float(r["at"]) >= G.LEARN_SINCE]
        if lw:
            sl = {}
            for name, rr in (("book", lw), ("ai_news", filt(lw, book, news_dec)[0]),
                             ("ai_learn", filt(lw, book, learn_dec)[0])):
                c, err = cash_net(book, rr, now, ctx)
                sl[name] = c
                res["cost_error"] = res["cost_error"] or err
            b["since_learn"] = {"since": G.LEARN_SINCE, "positions": len(lw), "branches": sl,
                                "learn_cut": sum(1 for r in lw if learn_dec.get(G.key_of(book, r)) == "skip")}
        else:
            b["since_learn"] = {"since": G.LEARN_SINCE, "positions": 0, "why": "позиций с дня рождения ai_learn ещё нет"}
        res["books"][book] = b
        log(f"{book}: позиций {len(recs)}, судья убрал {cut_n}, без новостей {cut_p}, без решения {unj_n}, "
            f"закрыл сторож {n_close}, делистинг {n_dl} ({time.time() - t0:.0f} с)")
    res["secs"] = round(time.time() - t0, 1)
    return res


def pp(x):
    return "—" if x is None else f"{100 * x:+.2f} %"


def report(r):
    if r.get("error"):
        return f"# Ветки судьи\n\nНЕ ПОСЧИТАНО: {r['error']}\n"
    L = ["# Ветки судьи спеки 19 — запись вперёд", "",
         f"Посчитано {r['computed_at']} UTC за {r['secs']} с. Запись с 2026-10-18 18:00 UTC, **{r['days']} сут**; "
         f"суд не раньше {r['judge_day']} — **до него это не вердикт**. Потрачено на модель всего ${r['spent_usd']}."
         + (f" **Издержки не посчитаны:** {r['cost_error']}" if r.get("cost_error") else ""), ""]
    for book, b in r["books"].items():
        L += [f"## {book} ({'Depth · Long' if b['side'] == 'long' else 'Depth · Short'})", ""]
        if b.get("why"):
            L += [b["why"], ""]
            continue
        c = b["counts"]
        L += [f"Позиций {b['positions']}; судья с новостями убрал {c['ai_news_cut']}, без новостей {c['ai_plain_cut']}, "
              f"без решения {c['unjudged']}; сторож закрыл {c['judge_closes']}, делистинг {c['delist_closes']}.", "",
              "| ветка | $1k итог | $1k просадка | $10k итог | $10k просадка | позиций $10k |", "|---|---|---|---|---|---|"]
        for name in ("book", "ai_news", "ai_plain", "ai_news_x", "delist"):
            x = b["branches"][name]
            L.append(f"| {name} | {pp(x[1000]['final'])} | {pp(x[1000]['max_dd'])} | {pp(x[10000]['final'])} | "
                     f"{pp(x[10000]['max_dd'])} | {x[10000]['n']} |")
        for name in ("rand", "rand_x"):
            x = b["branches"][name]
            L.append(f"| {name} (медиана {r['seeds']} зёрен) | {pp(x[1000]['median_final'])} | — | "
                     f"{pp(x[10000]['median_final'])} | — | не хуже модели: {x[10000]['not_worse_share']} |")
        L.append("")
        sl = b.get("since_learn") or {}
        L += [f"**Учащаяся ветка ai_learn — своё окно с {time.strftime('%Y-%m-%d %H:%M', time.gmtime(sl.get('since') or 0))} UTC**"
              f" (позиций {sl.get('positions', 0)}; ai_learn убрала {sl.get('learn_cut', 0)}):", ""]
        if sl.get("why"):
            L += [sl["why"], ""]
        else:
            L += ["| ветка | $1k итог | $10k итог | позиций $10k |", "|---|---|---|---|"]
            for name in ("book", "ai_news", "ai_learn"):
                x = sl["branches"][name]
                L.append(f"| {name} | {pp(x[1000]['final'])} | {pp(x[10000]['final'])} | {x[10000]['n']} |")
            L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
    import arm_book as AB                                      # noqa: E402
    res = run(log=AB.guarded(print, limit=2500))
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(report(res))
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    print(report(res)[-3000:])
    if not a.no_publish and not res.get("error"):
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "ветки судьи"], cwd=ROOT, check=False)
    return 0 if not res.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
