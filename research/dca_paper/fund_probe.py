#!/usr/bin/env python3
"""Сверка нашего ряда funding с ПЛОЩАДКОЙ по тем же символам и окнам.

Продолжение проверки величины funding. `fund_check.py` показал, что
начислений в наших рядах бывает двадцать четыре за сутки, а не три:
шаг ряда у части перпов час, у большинства четыре. Возражение владельца
(«он же снимает каждые 8 часов») этим ещё не закрыто — ряд мог быть
собран неверно. Поэтому здесь спрашивается САМА ПЛОЩАДКА:

* объявленный интервал начислений символа (`fundingInterval`, минуты) —
  прямо из справочника инструментов;
* история начислений в окне позиции — прямо из `funding/history`;
* и то и другое сравнивается с тем, что лежит у нас: число точек, шаг,
  сумма ставок за окно и наибольшая по модулю.

Расхождение означает дефект НАШИХ данных и лечится их перезакачкой;
совпадение означает, что издержка настоящая. Никаких правок замер не
делает — он только сверяет.

Запуск: `run research/dca_paper/fund_probe.py`.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402

CHECK_ART = os.path.join(HERE, "out", "DCA-fund-check.json")


def _api():
    import bybit_api as B
    return B


def declared_interval(symbol, api=None):
    """Интервал начислений символа по справочнику площадки, минуты."""
    B = api or _api()
    res = B.api_get("/v5/market/instruments-info",
                    {"category": B.CATEGORY, "symbol": symbol},
                    f"instr_one_{symbol}")
    lst = res.get("list") or []
    if not lst:
        return None
    v = lst[0].get("fundingInterval")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def venue_window(symbol, t0, t1, api=None):
    """Начисления площадки в окне [t0, t1) — момент и ставка."""
    B = api or _api()
    d0 = datetime.fromtimestamp(t0, timezone.utc).date() - timedelta(days=1)
    d1 = datetime.fromtimestamp(t1, timezone.utc).date() + timedelta(days=1)
    rows = B.collect_funding_symbol(symbol, d0, d1)
    out = []
    for iso, rate in rows:
        ts = datetime.fromisoformat(iso).timestamp()
        if t0 <= ts < t1:
            out.append((ts, float(rate)))
    return sorted(out)


def ours_window(series, t0, t1):
    """То же окно из НАШЕГО ряда."""
    if series is None:
        return []
    t, r = series
    t = np.asarray(t, dtype=np.int64)
    r = np.asarray(r, dtype=float)
    m = (t >= int(t0 * 1000)) & (t < int(t1 * 1000))
    return sorted(zip((t[m] / 1000.0).tolist(), r[m].tolist()))


def _stat(rows):
    if not rows:
        return {"n": 0, "sum": None, "max_abs": None, "step_h": None}
    ts = [x[0] for x in rows]
    d = np.diff(ts) / 3600.0 if len(ts) > 1 else np.array([])
    return {"n": len(rows),
            "sum": round(float(sum(x[1] for x in rows)), 6),
            "max_abs": round(max(abs(x[1]) for x in rows), 6),
            "step_h": (round(float(np.median(d)), 2) if d.size else None)}


def compare(cases, ctx, api=None, log=print):
    """Сверка по каждому случаю: наш ряд против площадки."""
    out = []
    funding = (ctx or {}).get("funding") or {}
    to_asset = (ctx or {}).get("to_asset") or {}
    for c in cases:
        sym, t0, t1 = c["sym"], float(c["t0"]), float(c["t1"])
        a = to_asset.get(sym)
        ours = ours_window(funding.get(a), t0, t1)
        try:
            theirs = venue_window(sym, t0, t1, api=api)
            why = None
        except Exception as e:                            # noqa: BLE001
            theirs, why = [], f"площадка не ответила: {e}"[:160]
        try:
            iv = declared_interval(sym, api=api)
        except Exception as e:                            # noqa: BLE001
            iv, why = None, why or f"справочник не ответил: {e}"[:160]
        so, st = _stat(ours), _stat(theirs)
        same = (why is None and so["n"] == st["n"]
                and so["sum"] is not None and st["sum"] is not None
                and abs(so["sum"] - st["sum"]) < 1e-9)
        out.append(dict(c, asset=a, ours=so, venue=st, why=why,
                        interval_min=iv, match=same))
        log(f"{sym}: наших {so['n']} точек (сумма {so['sum']}), у площадки "
            f"{st['n']} (сумма {st['sum']}), интервал {iv} мин"
            + (f" — {why}" if why else ""))
        time.sleep(0.2)
    return out


def cases_from_check(path=None, k=3):
    """Окна самых дорогих позиций — из отчёта проверки величины."""
    path = path or CHECK_ART
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    got = []
    for sk, b in (s.get("books") or {}).items():
        for x in (b.get("top") or [])[:k]:
            ev = x.get("events") or []
            if not ev:
                continue
            got.append({"book": sk, "sym": x["sym"],
                        "t0": ev[0]["ts"], "t1": ev[-1]["ts"] + 1.0,
                        "funding_usd": x.get("funding_usd"),
                        "n_events_ours": x.get("n_events")})
    seen, out = set(), []
    for c in got:
        k2 = (c["sym"], int(c["t0"]))
        if k2 in seen:
            continue
        seen.add(k2)
        out.append(c)
    return out


def run(log=print, ctx=None, api=None, cases=None):
    t0 = time.time()
    ctx = ctx if ctx is not None else CO.context()
    if ctx.get("error") and not ctx.get("funding"):
        return {"error": ctx["error"]}
    cases = cases if cases is not None else cases_from_check()
    if not cases:
        return {"error": "нет окон для сверки: сперва прогон fund_check.py"}
    rows = compare(cases, ctx, api=api, log=log)
    ok = sum(1 for r in rows if r["match"])
    return {"cases": rows, "n": len(rows), "match": ok,
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "secs": round(time.time() - t0, 1)}


def report(s):
    L = ["# Сверка нашего ряда funding с площадкой", "",
         "Проверяется возражение владельца «funding снимается каждые 8 "
         "часов»: у площадки спрошены объявленный интервал начислений "
         "символа и история начислений в ОКНЕ самой позиции, и то и "
         "другое сравнено с нашим рядом.", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не сверено:** {s['error']}.", ""])
    L += [f"Сверено окон: {s['n']}, сошлось полностью: **{s['match']}**.", "",
          "| книга | символ | интервал площадки | наших точек | у площадки | "
          "сумма ставок наша | у площадки | наибольшая |ставка| | сошлось |",
          "|---|---|--:|--:|--:|--:|--:|--:|---|"]
    for c in s["cases"]:
        o, v = c["ours"], c["venue"]
        L.append(
            f"| {R.ruler_title(c.get('book') or '')} | {c['sym']} | "
            + ("—" if c.get("interval_min") is None
               else f"{c['interval_min']} мин")
            + f" | {o['n']} | {v['n']} | "
            + ("—" if o["sum"] is None else f"{o['sum']:+.6f}")
            + " | " + ("—" if v["sum"] is None else f"{v['sum']:+.6f}")
            + " | " + ("—" if v["max_abs"] is None else f"{v['max_abs']:.4f}")
            + " | " + ("да" if c["match"] else (c.get("why") or "НЕТ")) + " |")
    L += ["", "## Как читать", "",
          "- Интервал площадки в минутах отвечает на вопрос прямо: 60 "
          "означает начисление каждый час, 240 — каждые четыре, 480 — "
          "каждые восемь. У одного контракта он один, у другого другой; "
          "«всегда восемь часов» — не про Bybit.",
          "- Совпадение числа точек и суммы ставок означает, что наш ряд "
          "равен ряду площадки в этом окне, и величина издержки настоящая.",
          "- Расхождение означает дефект НАШИХ данных: тогда ряд "
          "перекачивается, а числа книг пересчитываются.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="сверка ряда funding с площадкой")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(R.OUT, exist_ok=True)
    s = run()
    art = os.path.join(R.OUT, "DCA-fund-probe.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(R.OUT, "DCA-fund-probe.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish("сверка ряда funding с площадкой")
    return 0


if __name__ == "__main__":
    sys.exit(main())
