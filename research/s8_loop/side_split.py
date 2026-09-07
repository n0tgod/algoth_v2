#!/usr/bin/env python3
"""Разрез ВСЕХ книг моделей по стороне: где шорты в плюсе и есть ли
сигнал, который в плюсе только по шортам.

Вопрос владельца 2026-09-07: «смотреть не в сторону DCA, а на источник
сигнала: какая из стратегий в models даёт плюс по шорт-сделкам, или
какой тип сигналов даёт плюс только по шортам».

Что считается. Для каждой книги реестра (ядро плюс кандидаты фабрики —
`books.load()`) сделки собираются ТЕМ ЖЕ ядром, что страница и касса:
`trades.build` по `picks/review/books.jsonl`, срок из манифеста тем же
правилом, что у сборщика (`situational`/`no_timer` → без срока, иначе
`horizon_h`), деньги — `trades.account` с размером и депозитом из
манифеста. Закрытые сделки делятся по стороне и по руке. По стороне:
n, Σ pnl $ (касса книги), средний и медианный net_bp (нетто круга
11 б.п., доли нотионала), доля прибыльных, медиана дня по дате выхода,
наивная t-статистика среднего net_bp (сделки одного часа не независимы,
поэтому рядом медиана дня), половины окна по времени входа.

Вердикт из чисел, не по лучшей книге. «Шорты в плюсе»: n ≥ N_MIN,
Σ pnl шортов > 0, медиана net_bp шортов > 0, медиана дня ≥ 0, сумма
шортов ≥ 0 на ОБЕИХ половинах. «Плюс только по шортам»: то же при
Σ pnl лонгов ≤ 0. Контроль — лонги той же книги: та же модель, та же
механика, другая сторона; если плюс у обеих сторон — это сигнал, если
только у одной — ставка на направление рынка окна.

Семья (тип сигнала) — из реестра: timer (срок 4/24 ч, порядок per σ),
sigma, basket (корзина), agree (согласие рук), situational (уровни);
кандидаты фабрики — своим ключом. Эхо-книги (те же решения под другим
правилом размера/выхода) в суммах семьи не складываются — по флагу
реестра, не по имени.

Запуск на VPS: run research/s8_loop/side_split.py
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import books as BK                                            # noqa: E402
import trades as TR                                           # noqa: E402

OUT = os.path.join(HERE, "out")
ARMS = ("gbm", "nn")
N_MIN = 30            # меньше сделок на стороне — не судится


def jlines(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        return None
    return out


def book_hold(mman, default_h=TR.HOLD_H):
    """То же правило, что у сборщика (`collect.book_hold`)."""
    if mman.get("situational") or mman.get("no_timer"):
        return None
    return int(mman.get("horizon_h") or default_h)


def load_trades(mdir, log=print):
    """Сделки книги тем же ядром, что страница; None — книги нет."""
    mp = os.path.join(mdir, "manifest.json")
    try:
        with open(mp, encoding="utf-8") as f:
            mman = json.load(f)
    except (OSError, ValueError) as e:
        log(f"{os.path.basename(mdir)}: манифест не читается — {e}")
        return None, None
    picks = jlines(os.path.join(mdir, "picks.jsonl"))
    revs = jlines(os.path.join(mdir, "review.jsonl"))
    if picks is None or revs is None:
        log(f"{os.path.basename(mdir)}: нет picks/review")
        return None, mman
    hold = book_hold(mman)
    tr = TR.build(picks, revs, hold_h=hold,
                  books=TR.load_books(os.path.join(mdir, "books.jsonl")))
    start = TR.start_of(mman)
    for a in ARMS:
        try:
            TR.account(tr, a, hold_h=hold or TR.HOLD_H,
                       slots=mman.get("slots"), sizing=mman.get("sizing"),
                       start=start)
        except Exception as e:                            # noqa: BLE001
            log(f"{os.path.basename(mdir)} [{a}]: касса не сошлась — {e}")
    return tr, mman


def _day(t):
    ts = t.get("exit_ts") or t.get("closes_at") or t.get("opened_at")
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts))) if ts else None


def side_stats(closed, side):
    """Статистика одной стороны по закрытым сделкам."""
    s = [t for t in closed if t.get("side") == side]
    nets = np.array([float(t["net_bp"]) for t in s
                     if t.get("net_bp") is not None], dtype=float)
    pnls = [float(t["pnl"]) for t in s if t.get("pnl") is not None]
    out = {"n": len(s), "pnl_usd": round(sum(pnls), 2) if pnls else None,
           "net_bp_mean": round(float(nets.mean()), 1) if len(nets) else None,
           "net_bp_median": round(float(np.median(nets)), 1) if len(nets) else None,
           "win": round(float(np.mean(nets > 0)), 3) if len(nets) else None,
           "t": (round(float(nets.mean() / (nets.std(ddof=1) / np.sqrt(len(nets)))), 2)
                 if len(nets) > 2 and nets.std(ddof=1) > 0 else None)}
    days = {}
    for t in s:
        d = _day(t)
        if d and t.get("pnl") is not None:
            days[d] = days.get(d, 0.0) + float(t["pnl"])
    out["days"] = len(days)
    out["day_median"] = (round(float(np.median(list(days.values()))), 2)
                         if days else None)
    ts = sorted(float(t["opened_at"]) for t in s if t.get("opened_at"))
    if len(ts) >= 4:
        mid = ts[len(ts) // 2]
        a = [float(t["pnl"]) for t in s if t.get("opened_at")
             and float(t["opened_at"]) < mid and t.get("pnl") is not None]
        b = [float(t["pnl"]) for t in s if t.get("opened_at")
             and float(t["opened_at"]) >= mid and t.get("pnl") is not None]
        out["half_a"] = round(sum(a), 2)
        out["half_b"] = round(sum(b), 2)
        out["half_mid"] = time.strftime("%Y-%m-%d", time.gmtime(mid))
    else:
        out["half_a"] = out["half_b"] = out["half_mid"] = None
    ex = {}
    for t in s:
        r = t.get("exit_reason") or "срок"
        ex[r] = ex.get(r, 0) + 1
    out["exits"] = ex
    return out


def judge(short, long_):
    """Вердикт стороны из чисел; None — не судится (мало сделок)."""
    if not short or short["n"] < N_MIN or short["pnl_usd"] is None:
        return {"judged": False, "why": f"шортов меньше {N_MIN}"}
    pos = (short["pnl_usd"] > 0 and (short["net_bp_median"] or 0) > 0
           and (short["day_median"] or 0) >= 0)
    stable = (short["half_a"] is not None and short["half_a"] >= 0
              and short["half_b"] >= 0)
    long_neg = bool(long_ and long_["n"] >= N_MIN
                    and (long_["pnl_usd"] or 0) <= 0)
    return {"judged": True, "shorts_positive": bool(pos and stable),
            "shorts_positive_unstable": bool(pos and not stable),
            "shorts_only": bool(pos and stable and long_neg),
            "long_negative": long_neg}


def run(books=None, root=None, log=print):
    t0 = time.time()
    root = root or OUT
    if books is None:
        books, why = BK.load()
        if why:
            log(f"кандидаты фабрики: {why}")
    rows, missing = [], []
    for b in books:
        if b.get("removed"):
            continue
        mdir = os.path.join(root, b["dir"])
        if not os.path.isdir(mdir):
            missing.append(b["key"])
            continue
        tr, mman = load_trades(mdir, log=log)
        if tr is None:
            missing.append(b["key"])
            continue
        for a in ARMS:
            closed = [t for t in tr if t.get("arm") == a
                      and t.get("state") == "закрыта"]
            if not closed:
                continue
            sh, lg = side_stats(closed, "short"), side_stats(closed, "long")
            rows.append({"key": b["key"], "label": b.get("label") or b["key"],
                         "family": b.get("family"), "echo": bool(b.get("echo")),
                         "agree": bool(b.get("agree")),
                         "traded": bool(b.get("traded", True)),
                         "arm": a, "closed": len(closed),
                         "start": TR.start_of(mman),
                         "short": sh, "long": lg, "verdict": judge(sh, lg)})
        log(f"{b['key']}: закрытых {sum(r['closed'] for r in rows if r['key'] == b['key'])}")
    # семьи — без эхо и согласных (одни решения дважды)
    fam = {}
    for r in rows:
        if r["echo"] or r["agree"]:
            continue
        f = fam.setdefault(r["family"] or "?", {"short_pnl": 0.0, "long_pnl": 0.0,
                                                 "short_n": 0, "long_n": 0,
                                                 "short_nets": [], "books": set()})
        f["short_pnl"] += r["short"]["pnl_usd"] or 0.0
        f["long_pnl"] += r["long"]["pnl_usd"] or 0.0
        f["short_n"] += r["short"]["n"]
        f["long_n"] += r["long"]["n"]
        f["books"].add(r["key"])
    for f in fam.values():
        f["books"] = sorted(f["books"])
        f["short_pnl"] = round(f["short_pnl"], 2)
        f["long_pnl"] = round(f["long_pnl"], 2)
        f.pop("short_nets", None)
    pos = [f"{r['key']}/{r['arm']}" for r in rows if r["verdict"].get("shorts_positive")]
    only = [f"{r['key']}/{r['arm']}" for r in rows if r["verdict"].get("shorts_only")]
    unst = [f"{r['key']}/{r['arm']}" for r in rows
            if r["verdict"].get("shorts_positive_unstable")]
    judged = sum(1 for r in rows if r["verdict"].get("judged"))
    return {"rows": rows, "families": fam, "missing": missing,
            "shorts_positive": pos, "shorts_only": only,
            "shorts_positive_unstable": unst, "judged": judged,
            "n_min": N_MIN, "round_cost_bp": TR.ROUND_COST_BP,
            "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


def _u(x):
    return "—" if x is None else f"{x:+,.2f}"


def _b(x):
    return "—" if x is None else f"{x:+.1f}"


def _pc(x):
    return "—" if x is None else f"{x * 100:.0f} %"


def report(s):
    P = ["# Книги моделей по стороне: где шорты в плюсе", "",
         "Вопрос владельца 2026-09-07: не DCA, а источник сигнала — какая книга "
         "даёт плюс по шорт-сделкам, и есть ли тип сигнала с плюсом только по "
         "шортам. Сделки собраны тем же ядром, что страница и касса "
         "(`trades.build`/`account`, срок и размер из манифеста книги); "
         f"net_bp — нетто круга {s['round_cost_bp']:g} б.п. в долях нотионала, "
         "$ — касса книги. Медиана дня — по дате выхода; половины — по времени "
         "входа. t — наивная (сделки одного часа не независимы).", "",
         f"Прогон {s['computed_at']} UTC · строк книга×рука {len(s['rows'])} · "
         f"судимых (шортов ≥ {s['n_min']}) {s['judged']} · книг без записи "
         f"{len(s['missing'])}"
         + (" (" + ", ".join(s["missing"]) + ")" if s["missing"] else "") + ".", "",
         "## По книгам и рукам", "",
         "| книга | семья | рука | закрыто | шорт n | шорт $ | шорт net б.п. ср/мед | "
         "шорт win | t | дней | медиана дня $ | половины $ A/B | лонг n | лонг $ | "
         "лонг net мед | вердикт |",
         "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in s["rows"]:
        sh, lg, v = r["short"], r["long"], r["verdict"]
        vt = ("**шорты в плюсе, только шорты**" if v.get("shorts_only")
              else "**шорты в плюсе**" if v.get("shorts_positive")
              else "плюс, но не на обеих половинах" if v.get("shorts_positive_unstable")
              else ("минус" if v.get("judged") else v.get("why", "—")))
        tag = " (эхо)" if r["echo"] else (" (согласие)" if r["agree"] else "")
        P.append(f"| `{r['key']}`{tag} | {r['family']} | {r['arm']} | {r['closed']} | "
                 f"{sh['n']} | {_u(sh['pnl_usd'])} | {_b(sh['net_bp_mean'])} / "
                 f"{_b(sh['net_bp_median'])} | "
                 f"{_pc(sh['win'])} | "
                 f"{'—' if sh['t'] is None else sh['t']} | {sh['days']} | "
                 f"{_u(sh['day_median'])} | {_u(sh['half_a'])} / {_u(sh['half_b'])} | "
                 f"{lg['n']} | {_u(lg['pnl_usd'])} | {_b(lg['net_bp_median'])} | {vt} |")
    P += ["", "## По семьям сигнала (без эхо и согласных книг)", "",
          "| семья | книги | шорт n | шорт $ | лонг n | лонг $ |", "|---|---|---:|---:|---:|---:|"]
    for k, f in sorted(s["families"].items()):
        P.append(f"| {k} | {', '.join(f['books'])} | {f['short_n']} | {_u(f['short_pnl'])} | "
                 f"{f['long_n']} | {_u(f['long_pnl'])} |")
    P += ["", "## Вердикт (из чисел)", "",
          f"Судимых строк {s['judged']}. Шорты в плюсе устойчиво (Σ $ > 0, медиана "
          f"net_bp > 0, медиана дня ≥ 0, обе половины ≥ 0): **{len(s['shorts_positive'])}**"
          + (" — " + ", ".join(f"`{k}`" for k in s["shorts_positive"]) if s["shorts_positive"] else "")
          + f". Из них плюс ТОЛЬКО по шортам (лонги той же книги ≤ 0): "
          f"**{len(s['shorts_only'])}**"
          + (" — " + ", ".join(f"`{k}`" for k in s["shorts_only"]) if s["shorts_only"] else "")
          + ". Плюс по сумме, но не на обеих половинах: "
          f"{len(s['shorts_positive_unstable'])}"
          + (" — " + ", ".join(f"`{k}`" for k in s["shorts_positive_unstable"])
             if s["shorts_positive_unstable"] else "") + ".", "",
          "Чего замер НЕ говорит: окно записи одно и режим рынка один — плюс одной "
          "стороны при минусе другой у той же модели есть подпись направления окна, "
          "а не сигнала; эхо-книги повторяют решения книги-источника; проскальзывание "
          "и funding в net_bp не входят (круг — только комиссия)."]
    return "\n".join(P) + "\n"


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="книги моделей по стороне")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    s = run()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"SIDE-split-{a.tag}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"SIDE-split-{a.tag}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"S8: книги по стороне — шорты в плюсе у {len(s['shorts_positive'])} "
                f"из {s['judged']} ({a.tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
