#!/usr/bin/env python3
"""Волна окна и сырой исход стороны: что шорты книг сделали бы САМИ ПО СЕБЕ.

Разрез по стороне (`side_split.py`) считает деньги кассы книги, а касса
меряет исход целью книги — форвардным ОСТАТКОМ к рыночной волне
(`bookfeat.target_pack` → `features.forward_residual`: ход имени минус
β × средний ход остальных). То есть «шорты h24 в плюсе» значит: имена,
которые модель шортит, отстают от рынка на медианные +503 б.п. за 24 ч —
кросс-секционный сигнал, а не ставка на падение рынка, по построению.
Но одиночный шорт несёт и волну: сырой исход = остаток + β × волна, и
в растущем рынке шорт-нога, обыгравшая рынок, всё равно может быть в
минусе деньгами. Здесь считается второе число — рядом с первым.

Волна — прокси: равновзвешенный средний ход `PROXY` имён (крупнейшие по
обороту) за горизонт книги от закрытия часа входа, по закрытиям минутных
баров ленты собственной записи (`sweep.read_bars`); волна цикла берёт
среднее по ВСЕМ именам универсума, и это расхождение названо. β — из
выбора книги (`picks.jsonl`, поле `beta` на час решения); без поля —
1.0, и таких считается число. Сырой нетто сделки = нетто кассы + s·β·волна
(s = +1 лонг, −1 шорт), сырые деньги — тем же размером, что у кассы.

Печатается по книге/руке/стороне: n, нетто кассы (остаток) ср/мед и Σ $,
сырое нетто ср/мед и Σ $, средняя волна в часы сделок, доля часов с
падающей волной; и рынок окна целиком: медиана волны по часам, доля
падающих часов. Прочерки с причиной там, где волны нет.

Запуск на VPS: run research/s8_loop/side_wave.py
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
sys.path.insert(0, os.path.join(ROOT, "research", "s9_sweep"))
sys.path.insert(0, os.path.join(ROOT, "research", "b1_book"))
import side_split as SS                                       # noqa: E402
import sweep as SW                                            # noqa: E402
import trades as TR                                           # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT_B1 = os.path.join(ROOT, "research", "b1_book", "out")
BOOKS = ("h24", "z", "h4")
PROXY = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
         "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "TRXUSDT", "TONUSDT",
         "SUIUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "APTUSDT", "UNIUSDT",
         "ARBUSDT", "OPUSDT")
MIN_PROXY = 5              # меньше имён с ценой на границе — волны нет
CLOSE_TOL = 1800           # последний бар не старше получаса от границы


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def closes_at(bars, bounds):
    """Закрытие последнего бара не старше `CLOSE_TOL` до каждой границы."""
    out = np.full(len(bounds), np.nan)
    if not bars:
        return out
    ts = np.array([b[0] for b in bars], dtype=float)
    cl = np.array([b[4] for b in bars], dtype=float)
    idx = np.searchsorted(ts, np.array(bounds, dtype=float), "right") - 1
    for k, i in enumerate(idx):
        if i >= 0 and bounds[k] - ts[i] <= CLOSE_TOL and cl[i] > 0:
            out[k] = cl[i]
    return out


def wave_table(bounds, horizons, read=None, proxies=PROXY, log=log):
    """{H: волна б.п. по границам} — средний ход прокси-имён за H часов."""
    read = read or (lambda s, a, b: SW.read_bars(ROOT_B1, s, a, b))
    hmax = max(horizons)
    t0, t1 = min(bounds) - 3600, max(bounds) + hmax * 3600 + 3600
    ends = {H: [b + H * 3600 for b in bounds] for H in horizons}
    moves = {H: [] for H in horizons}
    have = 0
    for sym in proxies:
        bars = read(sym, t0, t1)
        c0 = closes_at(bars, bounds)
        if not np.isfinite(c0).any():
            log(f"  волна: {sym} без баров в окне")
            continue
        have += 1
        for H in horizons:
            c1 = closes_at(bars, ends[H])
            moves[H].append((c1 / c0 - 1.0) * 1e4)
    out, cover = {}, {}
    for H in horizons:
        if not moves[H]:
            out[H] = np.full(len(bounds), np.nan)
            cover[H] = 0
            continue
        m = np.array(moves[H])
        n_ok = np.isfinite(m).sum(axis=0)
        with np.errstate(all="ignore"):
            w = np.nanmean(m, axis=0)
        w[n_ok < MIN_PROXY] = np.nan
        out[H] = w
        cover[H] = int(np.isfinite(w).sum())
    log(f"волна: прокси с барами {have}/{len(proxies)}, границ {len(bounds)}, "
        + ", ".join(f"{H} ч: {cover[H]} с волной" for H in horizons))
    return out, {"proxies": have, "bounds": len(bounds), "cover": cover}


def betas_of(mdir):
    """β на час решения из выборов книги: (рука, час, имя, сторона) → β."""
    out = {}
    for p in SS.jlines(os.path.join(mdir, "picks.jsonl")) or []:
        arm = p.get("arm") or "gbm"
        for side in ("long", "short"):
            for r in p.get(side) or []:
                if r.get("beta") is not None:
                    out[(arm, p.get("hour"), r.get("sym"), side)] = float(r["beta"])
    return out


def side_rows(trades, betas, wave, H, arm, side):
    """Сырой исход по сделкам стороны; сделка без волны — пропуск со счётом."""
    rows, no_wave, no_beta = [], 0, 0
    s = 1.0 if side == "long" else -1.0
    for t in trades:
        if t.get("arm") != arm or t.get("side") != side or t.get("state") != "закрыта":
            continue
        if t.get("net_bp") is None:
            continue
        w = wave.get(t.get("hour"))
        if w is None or not np.isfinite(w):
            no_wave += 1
            continue
        b = betas.get((arm, t.get("hour"), t.get("sym"), side))
        if b is None:
            no_beta += 1
            b = 1.0
        net = float(t["net_bp"])
        raw = net + s * b * float(w)
        pnl = t.get("pnl")
        size = (float(pnl) / net * 1e4 if pnl is not None and abs(net) > 1e-9
                else None)
        rows.append({"net": net, "raw": raw, "wave": float(w), "beta": b,
                     "pnl": float(pnl) if pnl is not None else None,
                     "pnl_raw": (size * raw / 1e4 if size is not None else None)})
    return rows, no_wave, no_beta


def _stat(rows):
    if not rows:
        return {"n": 0}
    net = np.array([r["net"] for r in rows])
    raw = np.array([r["raw"] for r in rows])
    wv = np.array([r["wave"] for r in rows])
    p = [r["pnl"] for r in rows if r["pnl"] is not None]
    pr = [r["pnl_raw"] for r in rows if r["pnl_raw"] is not None]
    return {"n": len(rows),
            "net_mean": round(float(net.mean()), 1), "net_median": round(float(np.median(net)), 1),
            "raw_mean": round(float(raw.mean()), 1), "raw_median": round(float(np.median(raw)), 1),
            "pnl_usd": round(sum(p), 2) if p else None,
            "pnl_raw_usd": round(sum(pr), 2) if pr else None,
            "wave_mean": round(float(wv.mean()), 1),
            "wave_neg_share": round(float(np.mean(wv < 0)), 3),
            "raw_win": round(float(np.mean(raw > 0)), 3),
            "beta_mean": round(float(np.mean([r["beta"] for r in rows])), 3)}


def run(root=None, read=None, log=log, books=BOOKS, trades_of=None):
    t0 = time.time()
    root = root or SS.OUT
    reg, _why = SS.BK.load()
    by_key = {b["key"]: b for b in reg}
    loaded = {}
    for k in books:
        b = by_key.get(k)
        if not b:
            log(f"{k}: нет в реестре")
            continue
        mdir = os.path.join(root, b["dir"])
        tr, mman = (trades_of(k) if trades_of else SS.load_trades(mdir, log=log))
        if tr is None:
            log(f"{k}: книги нет")
            continue
        closed_h = sorted(t.get("hour") for t in tr if t.get("hour")
                          and t.get("state") == "закрыта")
        loaded[k] = {"trades": tr, "H": SS.book_hold(mman or {}) or TR.HOLD_H,
                     "betas": betas_of(mdir) if not trades_of else {},
                     "window": [closed_h[0], closed_h[-1]] if closed_h else None,
                     "names": len({t.get("sym") for t in tr if t.get("state") == "закрыта"})}
    hours = sorted({t.get("hour") for v in loaded.values() for t in v["trades"]
                    if t.get("hour") and t.get("state") == "закрыта"})
    if not hours:
        return {"present": False, "why": "закрытых сделок нет", "books": {}}
    bounds = [TR.hour_end(h) for h in hours]
    horizons = sorted({v["H"] for v in loaded.values()})
    wt, wmeta = wave_table(bounds, horizons, read=read, log=log)
    out = {"present": True, "books": {}, "wave_meta": wmeta, "proxies": list(PROXY),
           "hours": len(hours), "window": [hours[0], hours[-1]], "market": {}}
    for H in horizons:
        w = wt[H]
        ok = w[np.isfinite(w)]
        out["market"][str(H)] = {"hours_with_wave": int(len(ok)),
                                 "median_bp": round(float(np.median(ok)), 1) if len(ok) else None,
                                 "mean_bp": round(float(ok.mean()), 1) if len(ok) else None,
                                 "neg_share": round(float(np.mean(ok < 0)), 3) if len(ok) else None}
    for k, v in loaded.items():
        wave = {h: float(wt[v["H"]][i]) for i, h in enumerate(hours)}
        bk = {"H": v["H"], "arms": {}, "window": v.get("window"), "names": v.get("names")}
        for arm in SS.ARMS:
            bk["arms"][arm] = {}
            for side in ("long", "short"):
                rows, nw, nb = side_rows(v["trades"], v["betas"], wave, v["H"], arm, side)
                st = _stat(rows)
                st.update(no_wave=nw, no_beta=nb)
                bk["arms"][arm][side] = st
        out["books"][k] = bk
    out["secs"] = round(time.time() - t0, 1)
    out["computed_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return out


def _u(x):
    return "—" if x is None else f"{x:+,.2f}"


def _b(x):
    return "—" if x is None else f"{x:+.1f}"


def _pc(x):
    return "—" if x is None else f"{x * 100:.0f} %"


def report(s):
    P = ["# Волна окна и сырой исход стороны", ""]
    if not s.get("present"):
        P.append(f"Не измерено: {s.get('why')}.")
        return "\n".join(P) + "\n"
    P += ["Касса книг меряет исход ОСТАТКОМ к волне (цель `fwd_Hh` = ход − β·волна), "
          "поэтому плюс стороны в кассе — кросс-секционный по построению. Одиночная "
          "нога несёт ещё и волну: сырой нетто = нетто кассы + s·β·волна. Волна — "
          f"прокси: средний ход {len(s['proxies'])} крупнейших имён по ленте записи "
          "(волна цикла — среднее по всем именам универсума); β — из выбора книги, "
          "без поля 1.0.", "",
          f"Прогон {s['computed_at']} UTC · часов входа {s['hours']} "
          f"({s['window'][0]} … {s['window'][1]}) · прокси с барами "
          f"{s['wave_meta']['proxies']}/{len(s['proxies'])}.", "",
          "## Рынок окна (волна по всем часам входа)", "",
          "| горизонт | часов с волной | медиана волны, б.п. | среднее | доля падающих часов |",
          "|---|---:|---:|---:|---:|"]
    for H, m in sorted(s["market"].items(), key=lambda kv: int(kv[0])):
        P.append(f"| {H} ч | {m['hours_with_wave']} | {_b(m['median_bp'])} | {_b(m['mean_bp'])} | "
                 f"{_pc(m['neg_share'])} |")
    P += ["", "## По книгам: нетто кассы (остаток) против сырого", "",
          "| книга | H | рука | сторона | n | нетто кассы ср/мед б.п. | Σ $ кассы | "
          "сырое ср/мед б.п. | Σ $ сырое | сырой win | волна в часы сделок ср | "
          "доля падающих | β ср | без волны | без β |",
          "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, bk in s["books"].items():
        w = bk.get("window") or ["—", "—"]
        P.append(f"| `{k}` окно {w[0]} … {w[1]}, имён {bk.get('names')} | | | | | | | | | | | | | | |")
        for arm, sides in bk["arms"].items():
            for side, st in sides.items():
                if not st.get("n"):
                    P.append(f"| `{k}` | {bk['H']} | {arm} | {side} | 0 | — | — | — | — | — | — | — | — | "
                             f"{st.get('no_wave', 0)} | {st.get('no_beta', 0)} |")
                    continue
                P.append(f"| `{k}` | {bk['H']} | {arm} | {side} | {st['n']} | "
                         f"{_b(st['net_mean'])} / {_b(st['net_median'])} | {_u(st['pnl_usd'])} | "
                         f"{_b(st['raw_mean'])} / {_b(st['raw_median'])} | {_u(st['pnl_raw_usd'])} | "
                         f"{st['raw_win'] * 100:.0f} % | {_b(st['wave_mean'])} | "
                         f"{st['wave_neg_share'] * 100:.0f} % | {st['beta_mean']:.2f} | "
                         f"{st['no_wave']} | {st['no_beta']} |")
    P += ["", "Читать так: если у стороны плюс в кассе и минус сырым — сигнал "
          "кросс-секционный, а нога сама по себе проигрывает волне; торговать её "
          "имеет смысл только внутри нейтральной книги или с хеджем волны. Плюс "
          "обоими числами — нога заработала бы и одна на этом окне (и это окно одно).",
          "", "Чего замер НЕ говорит: волна прокси ≠ волна цикла (среднее по всем "
          "именам); β — оценка модели на час решения, не реализованная; издержки "
          "хеджа волны не считаны; проскальзывание и funding — нет."]
    return "\n".join(P) + "\n"


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="волна окна и сырой исход стороны")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--books", action="append", default=None,
                    help="ключ книги; повторяемый (по умолчанию h24, z, h4)")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        os.nice(10)
    except Exception:                                     # noqa: BLE001
        pass
    s = run(books=tuple(a.books) if a.books else BOOKS)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"SIDE-wave-{a.tag}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"SIDE-wave-{a.tag}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"S8: волна окна и сырой исход стороны ({a.tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
