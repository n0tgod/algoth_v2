#!/usr/bin/env python3
"""Поиск паттернов пути моделью → гипотезы новой ТВХ (спека 19 §11.7, U4b).

Раз в неделю, следом за уроками: модель получает сводку путей цены внутри
закрытых сделок книги (U0: худший ход против и когда, лучший за и когда,
что раньше — цель или пол, форма, выход, результат) по выходам и формам,
выборку путей по сделкам и прошлые результаты проверки сдвига
(`entry_shift`) — и предлагает до `MAX_HYPS` правил входа в машинной форме
того же словаря, что сетка: `pullback` (дождаться отката против позиции
на pct % за within_h ч), `confirm` (хода в пользу), `delay` (времени).
Решает не модель: каждая гипотеза идёт в `entry_shift` теми же порогами,
что объявленная сетка. Модель видит, что уже проверено, — повтор той же
гипотезы отбрасывается по параметрам.
"""
import json
import os
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import entry_shift as E                                       # noqa: E402
import judge as J                                             # noqa: E402

MAX_HYPS = 5
SAMPLE = 200

SYSTEM_PATTERNS = """You are searching for a better entry timing for a paper-trading book of crypto perpetual futures on Bybit (short side, 24-hour holding limit, a stop floor and a target set by the book's rules). You are given the price path inside each closed trade of this book: the worst move against the position and after how many hours, the best move in its favour and when, what was touched first (target or floor), the shape of the path, the exit and the result; aggregated by exit and by shape; and the results of entry-timing rules already tested.

Look for something that REPEATS in the paths and that a different entry moment could exploit: for example, if most trades first move against the position by a few percent in the first hours before going its way, waiting for that move would enter at a better price. Propose at most %d entry rules in the given vocabulary: "pullback" (wait until the price moves AGAINST the position by pct %% within within_h hours, then enter), "confirm" (wait until it moves IN FAVOUR by pct %% within within_h hours), "delay" (enter after_h hours later). If the condition does not happen within the window, there is no trade.

Every rule will be tested by numbers, not by your judgement: replayed by the book's own engine on past signals, compared with the book's own entry and with entering at a random minute of the same window for the same signals, on both halves of the period. A rule that only selects which signals trade, without better timing, will fail. Do not repeat a rule already tested with the same parameters. Returning fewer rules is a valid answer.

Return only the JSON object required by the schema.""" % MAX_HYPS


def schema():
    h = {"type": "object",
         "properties": {"kind": {"type": "string", "enum": list(E.KINDS)}, "pct": {"type": "number"},
                        "within_h": {"type": "number"}, "after_h": {"type": "number"}, "why": {"type": "string"}},
         "required": ["kind", "pct", "within_h", "after_h", "why"], "additionalProperties": False}
    return {"type": "object", "properties": {"hypotheses": {"type": "array", "items": h}, "notes": {"type": "string"}},
            "required": ["hypotheses", "notes"], "additionalProperties": False}


def parse(stop, text):
    if stop == "refusal":
        return None, "отказ модели (refusal) после запасной"
    if stop == "max_tokens":
        return None, "ответ оборван по длине"
    try:
        v = json.loads(text or "")
    except ValueError:
        return None, "ответ не JSON"
    if not isinstance(v, dict) or not isinstance(v.get("hypotheses"), list):
        return None, "нет списка гипотез"
    return {"hypotheses": v["hypotheses"][:MAX_HYPS], "notes": str(v.get("notes") or "")[:1000]}, None


def hyp_id(h):
    if h["kind"] == "delay":
        return f"delay_{float(h['after_h']):g}h"
    return f"{h['kind']}_{float(h['pct']):g}pct_{float(h['within_h']):g}h"


def summary(paths):
    """Сводка путей по выходам и формам — медианы и доли, из чисел U0."""
    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(st.median(xs), 4) if xs else None
    out = {}
    for key, fld in (("by_exit", "exit"), ("by_shape", None)):
        groups = {}
        for p in paths:
            g = p.get("exit") if fld else (p.get("path") or {}).get("shape")
            groups.setdefault(str(g), []).append(p)
        out[key] = {g: {"n": len(xs), "mae_med": med([(x["path"] or {}).get("mae") for x in xs]),
                        "mae_h_med": med([(x["path"] or {}).get("mae_h") for x in xs]),
                        "mfe_med": med([(x["path"] or {}).get("mfe") for x in xs]),
                        "mfe_h_med": med([(x["path"] or {}).get("mfe_h") for x in xs]),
                        "result_med": med([x.get("pnl_frac") for x in xs])} for g, xs in groups.items()}
    return out


def propose(client, paths, tested):
    shorts = [p for p in paths if p.get("side") == "short" and (p.get("path") or {}).get("shape") != "no_bars"]
    sample = sorted(shorts, key=lambda p: -float(p.get("exit_ts") or 0))[:SAMPLE]
    payload = {"kind": "entry_patterns", "summary": summary(shorts),
               "paths": [{"exit": p.get("exit"), "result_on_margin": p.get("pnl_frac"),
                          **{k: (p.get("path") or {}).get(k) for k in ("mae", "mae_h", "mfe", "mfe_h", "first_touch",
                                                                         "shape", "life_h", "market_move")}}
                         for p in sample],
               "already_tested": tested}
    row = J._call(client, "patterns", SYSTEM_PATTERNS, schema(), payload, parse, {"hypotheses": []})
    hyps, invalid = [], []
    seen = {t.get("id") for t in tested}
    for h in row.get("hypotheses") or []:
        h = {k: h.get(k) for k in ("kind", "pct", "within_h", "after_h", "why")}
        why = E.valid(h)
        if why:
            invalid.append({"rule": h, "why": why})
            continue
        h["id"] = hyp_id(h)
        if h["id"] in seen:
            continue
        seen.add(h["id"])
        h["proposed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        h["by"] = "model"
        hyps.append(h)
    return row, hyps, invalid


def run(log=print, client=None, paths=None, hyps_file=None, shift_file=None):
    """Предложить гипотезы и дописать их в файл гипотез `entry_shift`."""
    hyps_file = hyps_file or E.HYPS_FILE
    shift_file = shift_file or E.LATEST
    if paths is None:
        import path_review as PR                              # noqa: E402
        paths = PR.read_paths()
    tested = []
    try:
        with open(shift_file, encoding="utf-8") as f:
            last = json.load(f)
        for h in last.get("hypotheses") or []:
            ps = (h.get("per_signal") or {}).get("all") or {}
            tested.append({"id": h["id"], "rule": h.get("rule"), "candidate": h.get("candidate"), "why_not": h.get("why"),
                           "triggered": ps.get("triggered"), "mean_signal": ps.get("mean_signal"),
                           "mean_triggered": ps.get("mean_triggered"),
                           "random_minute": (h.get("null_median_triggered") or {}).get("all")})
        b = ((last.get("base") or {}).get("per_signal") or {}).get("all") or {}
        tested.append({"id": "book_entry", "mean_signal": b.get("mean_signal")})
    except (OSError, ValueError):
        pass
    try:
        with open(hyps_file, encoding="utf-8") as f:
            st_ = json.load(f)
    except (OSError, ValueError):
        st_ = {"hypotheses": []}
    tested += [{"id": h["id"], "rule": h} for h in st_.get("hypotheses") or [] if h["id"] not in {t["id"] for t in tested}]
    tested += [{"id": g["id"], "rule": g} for g in E.GRID if g["id"] not in {t["id"] for t in tested}]
    if client is None:
        key = J.read_key()
        client = J.make_client(key) if key else None
    if client is None:
        return {"error": "ключа нет"}
    if len(paths) < 50:
        return {"error": f"путей {len(paths)} < 50"}
    row, hyps, invalid = propose(client, paths, tested)
    st_.setdefault("hypotheses", []).extend(hyps)
    st_["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(hyps_file), exist_ok=True)
    with open(hyps_file + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st_, f, ensure_ascii=False, indent=1)
    os.replace(hyps_file + ".tmp", hyps_file)
    log(f"паттерны пути: предложено {len(hyps)} новых гипотез ТВХ, отвергнуто формой {len(invalid)}"
        + (f" ({row.get('no_verdict')})" if row.get("no_verdict") else ""))
    return {"new": hyps, "invalid": invalid, "notes": row.get("notes"), "no_verdict": row.get("no_verdict"),
            "cost_usd": row.get("cost_usd")}
