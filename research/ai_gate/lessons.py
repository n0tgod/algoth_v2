#!/usr/bin/env python3
"""Уроки судьи: предложение моделью, приём ЧИСЛОМ (спека 19 §11.4, U2).

Раз в неделю модель читает разборы своих сделок (U1) за неделю, каталог
полей досье с диапазонами и действующие уроки — и предлагает до
`MAX_RULES` правил вида «когда <поля досье с порогами> → skip». Правило
пишется МАШИННО (поле из каталога, знак, число), рядом — словами. Дальше
решает не модель, а этот код:

* случаи — входы ветки `ai_news`, решённые моделью, у которых есть досье
  на момент входа (запись) и закрытый путь (U0): исход берётся у БАЗОВОЙ
  книги, он от решения судьи не зависит;
* половины — по времени входа (медиана);
* в каждой половине: подходящих под правило ≥ `MIN_HALF`, их средний
  результат на маржу ХУЖЕ, чем у остальных, и хуже, чем у случайных
  выборок того же размера из той же половины не меньше чем в
  `1 − P_MAX` долях из `DRAWS` (урок проекта: фильтр, режущий сделки,
  сравнивается со случайной выборкой того же размера, многими зёрнами);
* всего подходящих ≥ `MIN_CASES`.

Прошло обе половины — `accepted`, и учащаяся ветка `ai_learn` читает его
в каждом досье. Не прошло — остаётся `proposed` с числами и ждёт данных.
Принятый урок, у которого на всей выборке подходящие перестали быть хуже
остальных, — `revoked`. Пороги объявлены здесь ДО первого прогона и по
результатам не меняются.

    lessons.py [--dry] [--no-publish]
"""
import argparse
import glob
import hashlib
import json
import os
import random
import statistics as st
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import gate_run as G                                          # noqa: E402
import judge as J                                             # noqa: E402

LESSONS = os.path.join(HERE, "out", "lessons.json")           # в git (публикация out/): действующие уроки — версия
OUT = os.path.join(HERE, "out")
LATEST = os.path.join(OUT, "lessons_latest.json")
REPORT = os.path.join(OUT, "LESSONS.md")
PATHS = os.path.join(OUT, "reviews")

MIN_CASES = 20          # подходящих под правило всего
MIN_HALF = 8            # подходящих в каждой половине
P_MAX = 0.10            # доля случайных выборок того же размера, не лучших правила, ≤
DRAWS = 400             # зёрен на половину
MAX_RULES = 20
REVIEW_DAYS = 7
OPS = ("<", "<=", ">", ">=")
SKIP_KEYS = ("news_on_this_coin_72h", "market_headlines_24h")


# ------------------------------------------------------------ поля досье

def leaves(d, pre=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from leaves(v, f"{pre}.{k}" if pre else k)
    elif isinstance(d, (int, float)) and not isinstance(d, bool):
        yield pre, float(d)


def fields_of(dossier):
    """Числовые поля досье плоско + два производных (объявлены здесь)."""
    d = {k: v for k, v in (dossier or {}).items() if k not in SKIP_KEYS}
    out = dict(leaves(d))
    b = out.get("crowd_positioning.bybit.now"), out.get("crowd_positioning.bybit.24h_ago")
    if None not in b:
        out["derived.crowd_bybit_shift_24h"] = round(b[0] - b[1], 6)
    h = out.get("name_history_in_book.hit_floor"), out.get("name_history_in_book.positions_before")
    if None not in h and h[1] > 0:
        out["derived.name_floor_share"] = round(h[0] / h[1], 6)
    return out


def catalog(cases):
    stat = {}
    for c in cases:
        for k, v in c["f"].items():
            s = stat.setdefault(k, [0, v, v, []])
            s[0] += 1; s[1] = min(s[1], v); s[2] = max(s[2], v); s[3].append(v)
    return {k: {"n": s[0], "min": s[1], "max": s[2], "median": st.median(s[3])} for k, s in sorted(stat.items())}


# ------------------------------------------------------------ случаи

def load_dossiers():
    out = {}
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
                    if r.get("branch") == "ai_news" and r.get("kind") == "entry" and r.get("dossier"):
                        out[r["key"]] = r["dossier"]
        except OSError:
            continue
    return out


def load_paths():
    rows = []
    for p in sorted(glob.glob(os.path.join(PATHS, "paths-*.jsonl"))):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return {r["key"]: r for r in rows if r.get("key")}


def cases(decisions=None, dossiers=None, paths=None):
    """Входы ai_news, решённые моделью, с досье и закрытым путём."""
    decisions = decisions if decisions is not None else G.read_decisions()
    dossiers = dossiers if dossiers is not None else load_dossiers()
    paths = paths if paths is not None else load_paths()
    reviews = {r["key"]: r for r in decisions if r.get("kind") == "review"}
    out = []
    for r in decisions:
        if r.get("kind") != "entry" or r.get("branch") != "ai_news":
            continue
        if r.get("decision") not in ("open", "skip") or r.get("no_verdict"):
            continue
        k = r["key"]
        p, d = paths.get(k), dossiers.get(k)
        if not p or d is None or p.get("pnl_frac") is None:
            continue
        rv = reviews.get(k) or {}
        out.append({"key": k, "sym": r.get("sym"), "side": r.get("side"), "at": float(r["at"]),
                    "decision": r["decision"], "pnl": float(p["pnl_frac"]), "exit": p.get("exit"),
                    "exit_ts": float(p["exit_ts"]), "path_words": p.get("words_en"), "f": fields_of(d),
                    "review": {k2: rv.get(k2) for k2 in ("verdict", "failed", "saved", "notes", "lesson")} if rv else None})
    return sorted(out, key=lambda c: c["at"])


# ------------------------------------------------------------ правило и проверка

def rule_id(rule):
    sig = json.dumps(sorted((c["field"], c["op"], round(float(c["value"]), 6)) for c in rule["when"]))
    return hashlib.sha256(sig.encode()).hexdigest()[:10]


def valid(rule, cat):
    """→ причина отказа или None. Поле — из каталога, знак — из словаря, число — число."""
    if rule.get("do") != "skip":
        return "проверяемы только правила skip"
    w = rule.get("when")
    if not isinstance(w, list) or not (1 <= len(w) <= 3):
        return "условий должно быть 1–3"
    for c in w:
        if c.get("field") not in cat:
            return f"поля {c.get('field')!r} нет в каталоге"
        if c.get("op") not in OPS:
            return f"знак {c.get('op')!r} вне словаря"
        try:
            float(c.get("value"))
        except (TypeError, ValueError):
            return "порог не число"
    return None


def matches(rule, f):
    for c in rule["when"]:
        v = f.get(c["field"])
        if v is None:
            return False
        x = float(c["value"])
        if not {"<": v < x, "<=": v <= x, ">": v > x, ">=": v >= x}[c["op"]]:
            return False
    return True


def _half(xs, rule, rng):
    m = [c["pnl"] for c in xs if matches(rule, c["f"])]
    rest = [c["pnl"] for c in xs if not matches(rule, c["f"])]
    out = {"n": len(xs), "matched": len(m), "mean_matched": round(st.mean(m), 4) if m else None,
           "mean_rest": round(st.mean(rest), 4) if rest else None, "p_random": None, "floors_matched": None}
    if m and rest:
        mm = st.mean(m)
        allp = [c["pnl"] for c in xs]
        as_bad = sum(1 for _ in range(DRAWS) if st.mean(rng.sample(allp, len(m))) <= mm)
        out["p_random"] = round(as_bad / DRAWS, 3)
    out["floors_matched"] = sum(1 for c in xs if matches(rule, c["f"]) and c["exit"] == "пол")
    return out


def test_rule(rule, cs, seed=0):
    """Обе половины по времени; всего; вердикт по объявленным порогам."""
    rng = random.Random(seed)
    mid = len(cs) // 2
    a, b = cs[:mid], cs[mid:]
    ha, hb, hall = _half(a, rule, rng), _half(b, rule, rng), _half(cs, rule, rng)

    def ok(h):
        return (h["matched"] >= MIN_HALF and h["mean_matched"] is not None and h["mean_rest"] is not None
                and h["mean_matched"] < h["mean_rest"] and h["p_random"] is not None and h["p_random"] <= P_MAX)
    passed = ok(ha) and ok(hb) and hall["matched"] >= MIN_CASES
    why = None
    if not passed:
        if hall["matched"] < MIN_CASES:
            why = f"подходящих {hall['matched']} < {MIN_CASES}"
        elif not ok(ha):
            why = "первая половина не держит"
        else:
            why = "вторая половина не держит"
    return {"first": ha, "second": hb, "all": hall, "passed": passed, "why": why,
            "split_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime(b[0]["at"])) if b else None}


# ------------------------------------------------------------ модель

SYSTEM_LESSONS = """You are improving the entry judge of a paper-trading book of crypto perpetual futures on Bybit. You are given a week of the judge's own post-trade reviews (each with the decision, the outcome, the price path inside the trade, and the judge's verdict on its decision), the catalog of numeric dossier fields with their ranges, and the current lessons with their test results.

Propose at most %d rules that would make the judge SKIP entries that tend to go badly. Each rule is a conjunction of 1 to 3 conditions on catalog fields ("field", "op" one of < <= > >=, numeric "value"), plus a short "text" in plain words and the mechanism in "why". Use only fields from the catalog, with thresholds inside their observed range.

Every rule will be tested by numbers, not by your judgement: on both halves of past entries split by time, the matched entries must do worse than the rest and worse than random samples of the same size. So prefer rules with a mechanism that should hold out of sample, and do not tune a threshold to one or two trades. Repeating a current rule unchanged is useless; refine or drop it. Returning fewer rules, or none, is a valid answer.

Return only the JSON object required by the schema.""" % MAX_RULES


def schema_lessons():
    cond = {"type": "object", "properties": {"field": {"type": "string"}, "op": {"type": "string", "enum": list(OPS)},
                                             "value": {"type": "number"}},
            "required": ["field", "op", "value"], "additionalProperties": False}
    rule = {"type": "object", "properties": {"text": {"type": "string"}, "when": {"type": "array", "items": cond},
                                             "do": {"type": "string", "enum": ["skip"]}, "why": {"type": "string"}},
            "required": ["text", "when", "do", "why"], "additionalProperties": False}
    return {"type": "object", "properties": {"rules": {"type": "array", "items": rule}, "notes": {"type": "string"}},
            "required": ["rules", "notes"], "additionalProperties": False}


def parse_lessons(stop, text):
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
    return {"rules": v["rules"][:MAX_RULES], "notes": str(v.get("notes") or "")[:1000]}, None


def propose(client, cs, cat, state, now):
    week = [c for c in cs if c["exit_ts"] >= now - REVIEW_DAYS * 86400 and c.get("review")]
    payload = {"kind": "lessons",
               "reviews_last_week": [{"symbol": c["sym"], "side": c["side"], "decision": c["decision"],
                                      "exit": c["exit"], "result_on_margin": round(c["pnl"], 4),
                                      "path": c["path_words"], "review": c["review"],
                                      "dossier_fields": {k: round(v, 4) for k, v in c["f"].items()}} for c in week],
               "field_catalog": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                                 for k, v in cat.items()},
               "current_lessons": [{"text": r["text"], "when": r["when"], "status": r["status"],
                                    "test_all": (r.get("test") or {}).get("all")} for r in
                                   (state.get("accepted") or []) + (state.get("proposed") or [])]}
    row = J._call(client, "lessons", SYSTEM_LESSONS, schema_lessons(), payload, parse_lessons, {"rules": []})
    return row, len(week)


# ------------------------------------------------------------ похожие случаи

SIMILAR_K = 5
SIMILAR_SAME = 3


def similar(cs, sym, side, crowd_now, at_s, k=SIMILAR_K):
    """Похожие закрытые случаи ДО момента решения: то же имя (свежие, до
    `SIMILAR_SAME`), затем та же сторона с ближайшей долей лонгов Bybit.
    Будущего нет: берутся только вышедшие раньше `at_s`."""
    past = [c for c in cs if c["exit_ts"] < at_s]
    same = sorted([c for c in past if c["sym"] == sym], key=lambda c: -c["at"])[:SIMILAR_SAME]
    rest = [c for c in past if c["sym"] != sym and c["side"] == side
            and c["f"].get("crowd_positioning.bybit.now") is not None]
    if crowd_now is not None:
        rest.sort(key=lambda c: abs(c["f"]["crowd_positioning.bybit.now"] - crowd_now))
    else:
        rest.sort(key=lambda c: -c["at"])
    pick = same + rest[:max(0, k - len(same))]
    return [{"symbol": c["sym"], "entered_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(c["at"])),
             "crowd_bybit_at_entry": c["f"].get("crowd_positioning.bybit.now"), "exit": c["exit"],
             "result_on_margin": round(c["pnl"], 4), "price_path": c["path_words"], "decision_then": c["decision"],
             "own_review": ({kk: c["review"].get(kk) for kk in ("verdict", "failed", "saved")} if c.get("review") else None)}
            for c in pick]


# ------------------------------------------------------------ состояние и прогон

def load_state(path=None):
    path = path or LESSONS
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"version": 0, "accepted": [], "proposed": [], "rejected": [], "revoked": []}


def lessons_text(state):
    """Принятые уроки словами — для досье и промпта учащейся ветки."""
    acc = state.get("accepted") or []
    if not acc:
        return []
    return [{"rule": r["text"], "when": " and ".join(f"{c['field']} {c['op']} {c['value']}" for c in r["when"]),
             "why": r.get("why"), "evidence": {"matched": (r.get("test") or {}).get("all", {}).get("matched"),
                                               "mean_matched": (r.get("test") or {}).get("all", {}).get("mean_matched"),
                                               "mean_rest": (r.get("test") or {}).get("all", {}).get("mean_rest")}}
            for r in acc]


def run(log=print, now=None, client=None, dry=False, cs=None, path=None):
    path = path or LESSONS
    t0 = time.time()
    now = now or time.time()
    cs = cs if cs is not None else cases()
    cat = catalog(cs)
    state = load_state(path)
    out = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "cases": len(cs),
           "cases_with_review": sum(1 for c in cs if c.get("review")), "fields": len(cat), "model": None,
           "new_rules": 0, "accepted_now": [], "revoked_now": [], "invalid": []}
    if len(cs) < 2 * MIN_HALF:
        out["error"] = f"случаев {len(cs)} < {2 * MIN_HALF}: проверять нечем"
        return out
    # 1. предложения модели
    if client is None and not dry:
        key = J.read_key()
        client = J.make_client(key) if key else None
    known = {r["id"] for k in ("accepted", "proposed", "rejected", "revoked") for r in (state.get(k) or [])}
    if client is not None and not dry:
        row, n_week = propose(client, cs, cat, state, now)
        out["model"] = {k: row.get(k) for k in ("no_verdict", "served_model", "cost_usd", "notes", "usage")}
        out["model"]["reviews_shown"] = n_week
        for r in row.get("rules") or []:
            why = valid(r, cat)
            if why:
                out["invalid"].append({"text": r.get("text"), "why": why})
                continue
            r = {"text": str(r["text"])[:300], "when": [{"field": c["field"], "op": c["op"], "value": float(c["value"])}
                                                       for c in r["when"]],
                 "do": "skip", "why": str(r.get("why") or "")[:300], "proposed_at": out["computed_at"], "status": "proposed"}
            r["id"] = rule_id(r)
            if r["id"] in known:
                continue
            known.add(r["id"])
            state.setdefault("proposed", []).append(r)
            out["new_rules"] += 1
    else:
        out["model"] = {"no_verdict": "сухой прогон" if dry else "ключа нет"}
    # 2. проверка числом — всех предложенных и принятых
    keep_p = []
    for r in state.get("proposed") or []:
        r["test"] = test_rule(r, cs)
        r["tested_at"] = out["computed_at"]
        if r["test"]["passed"]:
            r["status"] = "accepted"; r["accepted_at"] = out["computed_at"]
            state.setdefault("accepted", []).append(r)
            out["accepted_now"].append(r["text"])
        else:
            keep_p.append(r)
    state["proposed"] = keep_p
    keep_a = []
    for r in state.get("accepted") or []:
        if r.get("tested_at") != out["computed_at"]:
            r["test"] = test_rule(r, cs); r["tested_at"] = out["computed_at"]
        a = r["test"]["all"]
        if a["mean_matched"] is not None and a["mean_rest"] is not None and a["mean_matched"] >= a["mean_rest"]:
            r["status"] = "revoked"; r["revoked_at"] = out["computed_at"]
            state.setdefault("revoked", []).append(r)
            out["revoked_now"].append(r["text"])
        else:
            keep_a.append(r)
    state["accepted"] = keep_a
    state["version"] = int(state.get("version") or 0) + (1 if (out["accepted_now"] or out["revoked_now"]) else 0)
    state["updated"] = out["computed_at"]
    if not dry:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)
    out["state"] = {k: len(state.get(k) or []) for k in ("accepted", "proposed", "rejected", "revoked")}
    out["version"] = state["version"]
    out["secs"] = round(time.time() - t0, 1)
    out["report"] = report(state, out)
    log(f"уроки: случаев {len(cs)}, новых правил {out['new_rules']}, принято сейчас {len(out['accepted_now'])}, "
        f"отозвано {len(out['revoked_now'])}; действующих {out['state']['accepted']}, ждут {out['state']['proposed']}")
    return out


def report(state, out):
    pct = lambda v: "—" if v is None else f"{100 * v:+.1f} %"     # noqa: E731
    L = ["# Уроки судьи (спека 19 §11.4)", "",
         f"Посчитано {out['computed_at']}; случаев {out['cases']} (с разбором {out['cases_with_review']}); "
         f"пороги: всего ≥ {MIN_CASES}, в половине ≥ {MIN_HALF}, случайные того же размера не хуже в ≤ {P_MAX:.0%} из {DRAWS}.", ""]
    for name, key in (("Действующие (читает ветка ai_learn)", "accepted"), ("Предложенные, ждут данных", "proposed"),
                      ("Отозванные", "revoked")):
        L += [f"## {name}", ""]
        rs = state.get(key) or []
        if not rs:
            L += ["нет", ""]
            continue
        L += ["| правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не хуже (1-я / 2-я) | почему не принято |",
              "|---|---|---|---|---|---|"]
        for r in rs:
            t = r.get("test") or {}
            f, s, a = t.get("first") or {}, t.get("second") or {}, t.get("all") or {}
            cond = " и ".join(f"{c['field']} {c['op']} {c['value']:g}" for c in r["when"])
            L.append(f"| {r['text']} | `{cond}` | {f.get('matched')} / {s.get('matched')} | "
                     f"{pct(a.get('mean_matched'))} vs {pct(a.get('mean_rest'))} | {f.get('p_random')} / {s.get('p_random')} | "
                     f"{t.get('why') or '—'} |")
        L.append("")
    if out.get("invalid"):
        L += ["## Отвергнуто формой", ""] + [f"- {x['text']}: {x['why']}" for x in out["invalid"]] + [""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="без модели и без записи состояния")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
    import arm_book as AB                                     # noqa: E402
    s = run(log=AB.guarded(print, limit=2500), dry=a.dry)
    os.makedirs(OUT, exist_ok=True)
    # Сухой прогон ничего не пишет: по свежести файлов сторож судит, была ли
    # недельная сводка (20.10 сухой прогон отложил бы первую настоящую).
    if not a.dry:
        with open(LATEST, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in s.items() if k != "report"}, f, ensure_ascii=False)
        if s.get("report"):
            with open(REPORT, "w", encoding="utf-8") as f:
                f.write(s["report"])
    if s.get("report"):
        print(s["report"])
    if s.get("error"):
        print(s["error"])
    # Паттерны пути → гипотезы новой ТВХ (§11.7, U4b) — тем же недельным
    # проходом; проверяет их `entry_shift` следующим шагом сторожа.
    if not a.dry:
        try:
            import patterns as PT                               # noqa: E402
            pr = PT.run(log=print)
            s["patterns"] = {k: pr.get(k) for k in ("new", "invalid", "notes", "no_verdict", "cost_usd", "error")}
            with open(LATEST, "w", encoding="utf-8") as f:
                json.dump({k: v for k, v in s.items() if k != "report"}, f, ensure_ascii=False)
        except Exception as e:                                # noqa: BLE001
            print(f"паттерны пути не прошли: {type(e).__name__}: {e}")
    if not a.no_publish and not a.dry:
        subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), "уроки судьи"], cwd=ROOT, check=False)
    return 0 if not s.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
