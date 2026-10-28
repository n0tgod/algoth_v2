#!/usr/bin/env python3
"""Поиск паттернов моделью → правила новой ТВХ по состоянию рынка (спека 19 §11.7–11.8, U4b).

С 21.10 (владелец: «не просто ход цены — комплексный поиск по всем
параметрам рынка») модель предлагает правила словаря поиска
`entry_search`: 1–3 условия на параметрах состояния на каждом часе после
сигнала и окно W; проверяет их поиск теми же порогами, что ячейки.
Ниже — прежнее описание (словарь хода цены), оставлено как история.

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
import judge as J                                             # noqa: E402

MAX_HYPS = 5
SAMPLE = 200

SYSTEM_PATTERNS = """You are searching for a better entry moment for a paper-trading book of crypto perpetual futures on Bybit (short side, 24-hour holding limit, a stop floor and a target set by the book's rules). An entry rule here says: after the model's signal, wait and enter at the FIRST hour k = 0..W when the market state satisfies all conditions; if that never happens within W hours, there is no trade.

You are given: the catalog of market-state fields computed at every hour after a signal (crowd positioning, order-book microstructure from our own recording, funding, basis, open interest, the coin's and BTC's moves, the move since the signal, market regime, the signal's own promise and reward/risk, the coin's history in the book) with their observed ranges; a summary of the price path inside past trades (worst move against and when, best move in favour and when, what was touched first, the shape, the exit); and the results of the last systematic search over single and paired conditions.

Look for a COMBINATION of conditions with a mechanism: for example, a crowded short squeeze that has already happened, a burst of buying exhausting itself, funding flipping, open interest unwinding. Propose at most %d rules, each with 1 to 3 conditions ("field" from the catalog, "op" <= or >=, numeric "value" inside the observed range) and a window W of 1 to 6 hours, plus the mechanism in "why".

Each rule also chooses its EXIT ("exit"): one cell of the declared exit grid — a price stop from the average entry (none, 1, 2, 3, 5 or 8 %%), a take of the model's promised move ×1, ×2 (the book) or ×3, and leverage "book" (the book's own) or "eq" (equal risk: the loss at the stop equals the book's loss at its floor). The owner's long-term goal is a SHORT stop: look for entry states after which the price rarely goes far against the position (small adverse excursion of the winners), so that a short stop does not cut them; the path summary and the last search's best rule per stop show where that stands today. Use "s0:t2:book" for the book's own exit.

Every rule is tested by numbers, not by your judgement: chosen on one half of the period and checked on the other half, against the book's own entry and against entering at a random hour of the same window for the same signals. Rules that only skip signals without improving the entry moment fail. Do not repeat a rule already in the search results. Returning fewer rules is a valid answer.

Also study the EXIT. You are given "exit_by_state": for each market-state field at the signal hour, by terciles, which exit cell of the grid gave the best net result per signal versus the book's exit, and whether that gain held in both halves of the period. Propose at most %d EXIT rules ("exit_rules"): 1-3 conditions on fields at the SIGNAL hour, and the exit cell to use when they hold (the book's own exit otherwise). The owner's goal is a SHORT stop: prefer rules that let a short stop (1-3 %%) survive where the state says the adverse excursion is small, and say the mechanism. These rules are tested by numbers too: matched signals vs the same signals with the book's exit, against random subsets of the same size with the same cell.
Return only the JSON object required by the schema.""" % (MAX_HYPS, MAX_HYPS)
OPS = ("<=", ">=")


def schema():
    cond = {"type": "object", "properties": {"field": {"type": "string"}, "op": {"type": "string", "enum": list(OPS)},
                                             "value": {"type": "number"}},
            "required": ["field", "op", "value"], "additionalProperties": False}
    import entry_search as ES                                  # noqa: E402
    r = {"type": "object", "properties": {"when": {"type": "array", "items": cond}, "W": {"type": "integer"},
                                          "exit": {"type": "string", "enum": [e["name"] for e in ES.EXITS]},
                                          "why": {"type": "string"}},
         "required": ["when", "W", "exit", "why"], "additionalProperties": False}
    xr = {"type": "object", "properties": {"when": {"type": "array", "items": cond},
                                           "exit": {"type": "string", "enum": [e["name"] for e in ES.EXITS]},
                                           "why": {"type": "string"}},
          "required": ["when", "exit", "why"], "additionalProperties": False}
    return {"type": "object", "properties": {"rules": {"type": "array", "items": r},
                                             "exit_rules": {"type": "array", "items": xr},
                                             "notes": {"type": "string"}},
            "required": ["rules", "exit_rules", "notes"], "additionalProperties": False}


def parse(stop, text):
    if stop == "refusal":
        return None, "отказ модели (refusal) после запасной"
    if stop == "max_tokens":
        return None, "ответ оборван по длине"
    try:
        v = json.loads(text or "")
    except ValueError:
        return None, "ответ не JSON"
    if not isinstance(v, dict) or not isinstance(v.get("rules"), list):
        return None, "нет списка правил"
    xr = v.get("exit_rules") if isinstance(v.get("exit_rules"), list) else []
    return {"rules": v["rules"][:MAX_HYPS], "exit_rules": xr[:MAX_HYPS], "notes": str(v.get("notes") or "")[:1000]}, None


def valid(rule, catalog):
    w = rule.get("when")
    if not isinstance(w, list) or not (1 <= len(w) <= 3):
        return "условий должно быть 1–3"
    try:
        W = int(rule.get("W"))
    except (TypeError, ValueError):
        return "окно не число"
    if not (1 <= W <= 6):
        return "окно вне 1–6 ч"
    for c in w:
        if c.get("field") not in catalog:
            return f"поля {c.get('field')!r} нет в каталоге"
        if c.get("op") not in OPS:
            return f"знак {c.get('op')!r} вне словаря"
        try:
            float(c.get("value"))
        except (TypeError, ValueError):
            return "порог не число"
    import entry_search as ES                                  # noqa: E402
    if rule.get("exit") is not None and rule.get("exit") not in ES.EXIT_BY:
        return f"выхода {rule.get('exit')!r} нет в сетке"
    return None


def valid_exit(rule, catalog):
    """Правило выхода (§11.10): 1–3 условия из каталога, ячейка из сетки и не выход книги."""
    w = rule.get("when")
    if not isinstance(w, list) or not (1 <= len(w) <= 3):
        return "условий должно быть 1–3"
    for c in w:
        if c.get("field") not in catalog:
            return f"поля {c.get('field')!r} нет в каталоге"
        if c.get("op") not in OPS:
            return f"знак {c.get('op')!r} вне словаря"
        try:
            float(c.get("value"))
        except (TypeError, ValueError):
            return "порог не число"
    import entry_search as ES                                  # noqa: E402
    if rule.get("exit") not in ES.EXIT_BY:
        return f"выхода {rule.get('exit')!r} нет в сетке"
    if rule.get("exit") == ES.BOOK_EXIT:
        return "выход книги — не правило"
    return None


def sig_exit(rule):
    return json.dumps([sorted((c["field"], c["op"], round(float(c["value"]), 6)) for c in rule["when"]), rule["exit"]])


def sig(rule):
    """Подпись правила: условия, окно и выход (выход книги — без поля, как до §11.9)."""
    base = [sorted((c["field"], c["op"], round(float(c["value"]), 6)) for c in rule["when"]), int(rule["W"])]
    ex = rule.get("exit")
    return json.dumps(base + ([ex] if ex and ex != "s0:t2:book" else []))


def summary(paths):
    """Сводка путей по выходам и формам — медианы, из чисел U0."""
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
    # §11.9: какую долю плюсовых и минусовых сделок задел бы стоп s — цель
    # владельца (короткий стоп) упирается именно в это число у плюсовых
    win = [p for p in paths if (p.get("pnl_frac") or 0) > 0 and (p.get("path") or {}).get("mae") is not None]
    los = [p for p in paths if (p.get("pnl_frac") or 0) <= 0 and (p.get("path") or {}).get("mae") is not None]
    out["stop_would_cut"] = {
        f"{round(s_ * 100)}%": {"winners": round(sum(1 for p in win if p["path"]["mae"] >= s_) / len(win), 3) if win else None,
                                "losers": round(sum(1 for p in los if p["path"]["mae"] >= s_) / len(los), 3) if los else None}
        for s_ in (0.01, 0.02, 0.03, 0.05, 0.08)}
    out["stop_would_cut"]["n"] = {"winners": len(win), "losers": len(los)}
    return out


def catalog_from_table(path=None):
    """Каталог полей с диапазонами — из таблицы поиска (`entry_search`)."""
    import numpy as np
    import entry_search as ES                                  # noqa: E402
    z = np.load(path or ES.TABLE, allow_pickle=False)
    F, names = z["F"], [str(x) for x in z["names"]]
    out = {}
    for j, nm in enumerate(names):
        x = F[:, :, j].ravel()
        x = x[~np.isnan(x)]
        if len(x) == 0:
            continue
        out[nm] = {"cover": round(float(len(x)) / F[:, :, j].size, 3), "q10": round(float(np.quantile(x, 0.1)), 6),
                   "q50": round(float(np.quantile(x, 0.5)), 6), "q90": round(float(np.quantile(x, 0.9)), 6)}
    return out


def run(log=print, client=None, paths=None, rules_file=None, catalog=None, last_search=None, exit_state=None):
    """Предложить правила входа по состоянию и дописать их в файл правил поиска."""
    import entry_search as ES                                  # noqa: E402
    rules_file = rules_file or ES.RULES_FILE
    if paths is None:
        import path_review as PR                              # noqa: E402
        paths = PR.read_paths()
    if catalog is None:
        try:
            catalog = catalog_from_table()
        except Exception as e:                                # noqa: BLE001
            return {"error": f"таблицы поиска нет — каталог полей не построить: {type(e).__name__}"}
    if last_search is None:
        try:
            with open(ES.LATEST, encoding="utf-8") as f:
                ls = json.load(f)
            last_search = {k: {kk: ls[k].get(kk) for kk in ("rule", "train_gain", "test_mean", "test_book", "held",
                                                              "top5_train", "by_stop")}
                           for k in ("fold_1to2", "fold_2to1") if isinstance(ls.get(k), dict)}
            last_search["shortest_stop_holding"] = ls.get("shortest_stop")
        except (OSError, ValueError):
            last_search = None
    if client is None:
        key = J.read_key()
        client = J.make_client(key) if key else None
    if client is None:
        return {"error": "ключа нет"}
    if len(paths) < 50:
        return {"error": f"путей {len(paths)} < 50"}
    shorts = [p for p in paths if p.get("side") == "short" and (p.get("path") or {}).get("shape") != "no_bars"]
    if exit_state is None:
        try:
            with open(ES.LATEST, encoding="utf-8") as f:
                ls = json.load(f)
            exit_state = {"by_state": (ls.get("exit_state") or [])[:40], "last_exit_rules": ls.get("exit_model") or [],
                          "book_exits": ls.get("book_exits")}
        except (OSError, ValueError):
            exit_state = None
    payload = {"kind": "entry_rules", "field_catalog": catalog, "path_summary": summary(shorts),
               "last_search": last_search, "exit_by_state": exit_state}
    row = J._call(client, "patterns", SYSTEM_PATTERNS, schema(), payload, parse, {"rules": []})
    try:
        with open(rules_file, encoding="utf-8") as f:
            st_ = json.load(f)
    except (OSError, ValueError):
        st_ = {"rules": []}
    seen = {sig(r) for r in st_.get("rules") or []}
    new, invalid = [], []
    for r in row.get("rules") or []:
        why = valid(r, catalog)
        if why:
            invalid.append({"rule": r, "why": why})
            continue
        r = {"when": [{"field": c["field"], "op": c["op"], "value": float(c["value"])} for c in r["when"]],
             "W": int(r["W"]), "why": str(r.get("why") or "")[:300],
             **({"exit": r["exit"]} if r.get("exit") and r["exit"] != "s0:t2:book" else {}),
             "proposed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if sig(r) in seen:
            continue
        seen.add(sig(r))
        new.append(r)
    st_.setdefault("rules", []).extend(new)
    # правила выхода (§11.10): своя подпись, свой список; повтор не пишется
    seen_x = {sig_exit(r) for r in st_.get("exit_rules") or []}
    new_x, invalid_x = [], []
    for r in row.get("exit_rules") or []:
        why = valid_exit(r, catalog)
        if why:
            invalid_x.append({"rule": r, "why": why})
            continue
        r = {"when": [{"field": c["field"], "op": c["op"], "value": float(c["value"])} for c in r["when"]],
             "exit": r["exit"], "why": str(r.get("why") or "")[:300],
             "proposed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if sig_exit(r) in seen_x:
            continue
        seen_x.add(sig_exit(r))
        new_x.append(r)
    st_.setdefault("exit_rules", []).extend(new_x)
    st_["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(rules_file), exist_ok=True)
    with open(rules_file + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st_, f, ensure_ascii=False, indent=1)
    os.replace(rules_file + ".tmp", rules_file)
    log(f"правила входа от модели: новых {len(new)}, отвергнуто формой {len(invalid)}; "
        f"правила выхода: новых {len(new_x)}, отвергнуто {len(invalid_x)}"
        + (f" ({row.get('no_verdict')})" if row.get("no_verdict") else ""))
    return {"new": new, "invalid": invalid, "new_exit": new_x, "invalid_exit": invalid_x, "notes": row.get("notes"),
            "no_verdict": row.get("no_verdict"), "cost_usd": row.get("cost_usd")}


def main():
    """Отдельный проход (по заданию): недельный идёт из `lessons.py`."""
    import subprocess
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    r = run(log=print)
    if r.get("error"):
        print(f"правила модели НЕ предложены: {r['error']}")
        return 1
    for x in r.get("new") or []:
        print(" и ".join(f"{c['field']} {c['op']} {c['value']:g}" for c in x["when"]) + f", окно {x['W']} ч — {x['why']}")
    for x in r.get("invalid") or []:
        print(f"отвергнуто формой: {x['why']}")
    for x in r.get("new_exit") or []:
        print("выход: " + " и ".join(f"{c['field']} {c['op']} {c['value']:g}" for c in x["when"]) + f" → {x['exit']} — {x['why']}")
    for x in r.get("invalid_exit") or []:
        print(f"выход отвергнут формой: {x['why']}")
    if r.get("notes"):
        print(f"модель: {r['notes']}")
    print(f"стоимость: {r.get('cost_usd')} $")
    root = os.path.dirname(os.path.dirname(HERE))
    subprocess.run([os.path.join(root, "tools", "publish.sh"), "правила входа от модели"], cwd=root, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
