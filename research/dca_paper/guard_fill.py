#!/usr/bin/env python3
"""Замер: цена выхода охраны рынком — закрытие часа против первой цены
после границы.

Повод (26.09, RAREUSDT). Охрана рынком (спека 14 §13) закрывает шорт по
закрытию часа, в котором средний ход прокси-имён с входа дошёл до
порога; цена выхода — из отметки ядра за последний бар часа. Живьём
решение по закрытию часа исполняется в следующие секунды — по цене
первой минуты нового часа, а на границе часа цена прыгает. Вопрос
владельца: на сколько это меняет исход, системно ли и в какую сторону.

Что меряется на ВСЕХ выходах «рынок» журнала `h24` (нынешние правила;
общий счёт берёт те же решения): по каждому уникальному выходу
(имя, момент, граница) читаются бары принтов ±15 минут вокруг границы
часа, и сравниваются:
  - `close_before` — закрытие последнего бара ДО границы: то, что по
    правилу и есть цена выхода (контроль: расхождение с записанной
    ценой печатается числом — оно обязано быть около нуля);
  - `first_after` — открытие первого бара с началом НА границе или
    позже, не дальше 15 минут: первая цена, по которой шорт можно было
    закрыть после решения; нет принта 15 минут — прочерк, а не ноль.
Разница — в б.п. цены СО ЗНАКОМ пользы шорта (положительно = живьём
вышли бы лучше) и в деньгах книги: доля маржи = разница × плечо, деньги
= доля × маржа строки. Итог по каждой книге и депозиту: сколько выходов,
у скольких есть цена после, медиана/среднее/p10/p90 разницы, доля с
|разницей| > 50 б.п., сумма денег и её отношение к итогу этих сделок.

Бары старых дней, уже снятых с диска, читаются из хранилища
(`store.use_remote`). Отчёт — `out/DCA-guard-fill.md`.

    run research/dca_paper/guard_fill.py
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s9_sweep"))
sys.path.insert(0, os.path.join(ROOT, "research", "b1_book"))
import rules as R                                             # noqa: E402
import store                                                  # noqa: E402
import remote as RM                                           # noqa: E402
from sweep import read_bars                                   # noqa: E402

ROOT_B1 = RM.ROOT_B1
OUT_JSON = os.path.join(HERE, "out", "DCA-guard-fill.json")
OUT_MD = os.path.join(HERE, "out", "DCA-guard-fill.md")
WINDOW_S = 15 * 60.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def candidates(bars, boundary, window=WINDOW_S):
    """(закрытие до границы, открытие первого бара на/после границы)."""
    before = [b for b in bars if b[0] < boundary]
    after = [b for b in bars if boundary <= b[0] <= boundary + window]
    return ((float(before[-1][4]) if before else None),
            (float(after[0][1]) if after else None))


def side_sign(side):
    return -1.0 if side == "short" else 1.0


def measure(rows, bars_of=None, log=log, root=ROOT_B1, remote=None):
    """rows — строки журнала; bars_of(sym, t0, t1) — бары принтов."""
    bars_of = bars_of or (lambda s, a, b: read_bars(root, s, a, b))
    guard = [r for r in rows if r.get("exit") == R.GUARD_EXIT and R.is_current(r)
             and r.get("exit_px") and r.get("lev") and r.get("margin")]
    uniq = {}
    for r in guard:
        uniq.setdefault((r["sym"], round(float(r["at"]), 3),
                         round(float(r["exit_ts"]), 3)), []).append(r)
    log(f"выходов «{R.GUARD_EXIT}» {len(guard)} строк, уникальных {len(uniq)}")
    per = {}
    t0, last, done = time.time(), time.time(), 0
    checked = {"n": 0, "abs_bp": []}
    for (sym, at, ets), rs in sorted(uniq.items()):
        boundary = float(int(ets + 1.0))
        bars = bars_of(sym, boundary - WINDOW_S, boundary + WINDOW_S)
        close_before, first_after = candidates(bars, boundary)
        px = float(rs[0]["exit_px"])
        if close_before:
            checked["n"] += 1
            checked["abs_bp"].append(abs(close_before - px) / px * 1e4)
        for r in rs:
            key = (R.ruler_of(r), int(r.get("dep") or 0))
            p = per.setdefault(key, {"n": 0, "with_after": 0, "deltas": [],
                                     "usd": 0.0, "usd_trades": 0.0, "big": 0})
            p["n"] += 1
            p["usd_trades"] += float(r.get("usd") or 0.0)
            if first_after is None:
                continue
            side = R.row_side(r)
            d_bp = side_sign(side) * (first_after - px) / px * 1e4
            frac = d_bp / 1e4 * float(r["lev"])
            p["with_after"] += 1
            p["deltas"].append(d_bp)
            p["usd"] += frac * float(r["margin"])
            if abs(d_bp) > 50:
                p["big"] += 1
        done += 1
        if time.time() - last > 30:
            last = time.time()
            log(f"  {done}/{len(uniq)} выходов, {time.time() - t0:.0f} с")
    out = {}
    for (rk, dep), p in sorted(per.items()):
        ds = sorted(p["deltas"])
        n = len(ds)
        out[f"{rk}:{dep}"] = {
            "ruler": rk, "dep": dep, "n": p["n"], "with_after": p["with_after"],
            "no_print": p["n"] - p["with_after"],
            "median_bp": (ds[n // 2] if n else None),
            "mean_bp": (sum(ds) / n if n else None),
            "p10_bp": (ds[int(0.1 * (n - 1))] if n else None),
            "p90_bp": (ds[int(0.9 * (n - 1))] if n else None),
            "big_share": (p["big"] / n if n else None),
            "usd": round(p["usd"], 2), "usd_trades": round(p["usd_trades"], 2)}
    chk = sorted(checked["abs_bp"])
    return {"books": out, "unique_exits": len(uniq), "rows": len(guard),
            "check": {"n": checked["n"],
                      "median_abs_bp": (chk[len(chk) // 2] if chk else None),
                      "p90_abs_bp": (chk[int(0.9 * (len(chk) - 1))] if chk else None)},
            "remote": (remote.stats() if remote else None),
            "secs": round(time.time() - t0, 1),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


def _p(x, d=1):
    return "—" if x is None else f"{x:+.{d}f}"


def report(res):
    c = res["check"]
    med = "—" if c["median_abs_bp"] is None else f"{c['median_abs_bp']:.1f}"
    p90 = "—" if c["p90_abs_bp"] is None else f"{c['p90_abs_bp']:.1f}"
    L = ["# Цена выхода охраны рынком: закрытие часа против первой цены после границы", "",
         f"Выходов «{R.GUARD_EXIT}» в журнале `h24` {res['rows']} строк, уникальных "
         f"{res['unique_exits']}; счёт {res['secs']:.0f} с; посчитано {res['computed_at']} UTC.", "",
         f"**Контроль правила:** записанная цена выхода против закрытия последнего бара до "
         f"границы — медиана |разницы| {med} б.п., p90 {p90} б.п. на {c['n']} выходах "
         "(около нуля — цена выхода и есть закрытие часа; больше — источники расходятся).", "",
         "Разница — б.п. цены со знаком пользы шорта: **плюс = живьём вышли бы лучше**, "
         "чем по записи.", "",
         "| книга | депозит | выходов | с ценой после | без принта 15 мин | медиана | среднее "
         "| p10 | p90 | доля |Δ|>50 б.п. | Σ $ разницы | Σ $ этих сделок |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for b in res["books"].values():
        big = "—" if b["big_share"] is None else f"{100 * b['big_share']:.0f} %"
        L.append(f"| {b['ruler']} | ${b['dep']:,} | {b['n']} | {b['with_after']} | "
                 f"{b['no_print']} | {_p(b['median_bp'])} | {_p(b['mean_bp'])} | "
                 f"{_p(b['p10_bp'])} | {_p(b['p90_bp'])} | {big} | {b['usd']:+.2f} | "
                 f"{b['usd_trades']:+.2f} |")
    if res.get("remote"):
        L += ["", f"Бары из хранилища: {json.dumps(res['remote'], ensure_ascii=False)}."]
    L += ["", "## Чего замер НЕ говорит", "",
          "Первая цена после границы — открытие первой минуты с принтом; живой выход мог быть "
          "и хуже (очередь, объём), и лучше (лимитка). Разница считается только там, где принт "
          "после границы есть в 15 минут; выходы без принта — числом в колонке. Правило этим "
          "замером не меняется — решение владельца; смена цены выхода есть смена исхода и "
          "версии правил."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", default=R.H24_JOURNAL)
    a = ap.parse_args(argv)
    remote = RM.from_env(log=log)
    if remote is not None:
        store.use_remote(remote)
    rows, bad = R.read_journal(a.journal)
    log(f"журнал {a.journal}: строк {len(rows)}, битых {bad}")
    res = measure(rows, log=log, remote=remote)
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
