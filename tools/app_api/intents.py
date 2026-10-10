"""Намерения живого исполнителя Ladder (спека 15 §10a, этап L1).

Что делает. Для каждой активной подписки берёт НОВЫЕ выборы источника
её ячейки — короткие из `picks.jsonl` книги h24 (обе руки), длинные из
листов ситуационной книги под гейтами края и отношения — и считает по
ним ТО ЖЕ, что считает бумага, теми же функциями: окно по записи
сборщика, вход открытием первого бара от решения, структурные уровни и
рунги, σ окна, плечо забора с пределом тира (`run_d6.plan_position`,
общий пролог с `one_position`), цель правилом книги, ликвидацию и пол
(`rules.levels_of`), срок (`rules.hold_of`). Гейты книги — те же:
плечо не ниже порога режима (`rules.min_lev_of`), одна позиция на имя
у источника, возраст имени у коротких (`run_paper.age_shorts`), гейт
по ставке там, где он объявлен (`run_pair.gate_shorts`). Размер — долей
кассы ПОДПИСКИ (`rules.share_in`): при сложном проценте от депозита плюс
своего реализованного, при фиксированном билете — от депозита (§2);
отказы кассы — те же два, что у раздачи бумаги: «нет кассы» и «мельче
минимума биржи».

Намерение пишется строкой `kind: "entry"` в
`<корень исполнителя>/<subscription_id>/intents.jsonl` рядом с журналом
событий (`events.jsonl`): sym, side, lev, margin_usd, notional_usd,
px_ref (открытие минуты решения), rungs [{px, share}], take_px,
floor_px, liq_px, term_ts, decided_at. Отказ — строкой в `skips.jsonl` с
причиной словами: отказ обязан быть неотличим от тишины НЕ.

Чего НЕ делает. Денег с биржи не трогает и ключей не видит; заявок не
строит — это `bot ladder` (L2). Выходы книги (охрана рынком, команда)
намерением `exit` — следующий шаг: здесь только входы. Позиции до
подписки не ведутся (§2: вход со следующего входа).

Сверка с бумагой. Бумажная строка того же решения появляется часовым
прогоном книг позже намерения; `parity` находит её в своде `/dca` по
имени и секунде решения и печатает расхождение ЧИСЛОМ: вход в б.п.,
плечо, маржа, цель и пол в б.п. Решение, которое взяла бумага, а
намерение отвергло, — названо причиной из `skips.jsonl`; обратное —
«бумага не взяла». Это и есть то, что видно по L1.

Источники читаются ХВОСТОМ: смещение по файлу хранится в
`_intents_sources.json` корня; при первом чтении берётся последние
`FIRST_TAIL` байт — история не перечитывается (её уже считает бумага),
а решение, пришедшее до подъёма, в намерения не идёт и печатается как
пропуск источника.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RESEARCH = os.path.join(ROOT, "research")

HOUR = 3600.0
MINUTE = 60.0
FIRST_TAIL = 8 * 1024 * 1024        # первое чтение источника: хвост, не история
SEEN_KEEP_S = 7 * 86400             # ключи виденных решений живут неделю
PENDING_MAX_S = 20 * MINUTE         # сколько ждать бар входа, прежде чем отказать
PARITY_TAIL = 300                   # сколько последних намерений сверять

_CORE = None
_TIERS = {"mtime": None, "data": {}}


def core():
    """Модули правил и ядра — лениво: API без подписок их не грузит."""
    global _CORE
    if _CORE is not None:
        return _CORE
    for d in ("dca_paper", "dca_ladder", "s8_loop", "a1_universe",
              "s10_policy", "b1_book"):
        p = os.path.join(RESEARCH, d)
        if p not in sys.path:
            sys.path.insert(0, p)
    import rules as R                                        # noqa: E402
    import run_d2 as D2                                      # noqa: E402
    import run_d6 as D6                                      # noqa: E402
    import run_d10 as D10                                    # noqa: E402
    import run_d11 as D11                                    # noqa: E402
    import ladder as L                                       # noqa: E402
    import tournament as TNT                                 # noqa: E402
    import trades as TR                                      # noqa: E402
    import run_paper as RP                                   # noqa: E402
    import run_pair as PR                                    # noqa: E402
    import run_short as S                                    # noqa: E402
    import instruments_refresh as IR                         # noqa: E402
    _CORE = {"R": R, "D2": D2, "D6": D6, "D10": D10, "D11": D11, "L": L,
             "TNT": TNT, "TR": TR, "RP": RP, "PR": PR, "S": S, "IR": IR}
    return _CORE


def bars_source(log=None):
    """Бары записи сборщика с хвостом книги (`tail.TailBars`) — только
    диск: окно намерения не старше суток, хранилище не нужно."""
    c = core()
    sys.path.insert(0, os.path.join(RESEARCH, "dca_paper"))
    import tail as TL                                        # noqa: E402
    src = TL.TailBars(log=log)
    TL.store.use_remote(None)
    c["TL"] = TL
    return src


def tiers():
    """Тиры площадки — один разбор на изменение файла."""
    c = core()
    p = os.path.join(RESEARCH, "a1_universe", "out", "risk_limits.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    if _TIERS["mtime"] != mt:
        try:
            _TIERS["data"] = c["D2"].instruments_tiers()
        except (OSError, ValueError):
            _TIERS["data"] = {}
        _TIERS["mtime"] = mt
    return _TIERS["data"]


# ------------------------------------------------------------ источники

def source_files(files=None):
    """Файл источника по семейству книги: `sit` — листы ситуационной,
    `h24` — выборы книги со сроком. Подмена — для проверок."""
    c = core()
    out = {"sit": c["D2"].SHEETS, "h24": c["D11"].PICKS}
    out.update(files or {})
    return out


def read_tail(path, st, first_tail=FIRST_TAIL):
    """Новые ПОЛНЫЕ строки файла от сохранённого смещения.

    Возвращает (строки, новое состояние, почему-пусто). Первое чтение
    начинается с хвоста в `first_tail` байт (не с начала истории), и
    первая неполная строка хвоста выбрасывается. Файл стал короче —
    смещение с нуля (переписан). Последняя строка без перевода —
    незаконченная запись, остаётся на следующий раз.
    """
    st = dict(st or {})
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], st, "файла нет"
    off = st.get("offset")
    fresh = off is None
    # момент ПРОШЛОГО чтения: строки, прочитанные сейчас, не старше
    # него — это и есть мера свежести решения (см. `decide`)
    st["prev_at"] = st.get("at")
    if fresh:
        off = max(0, size - int(first_tail))
    elif off > size:
        off = 0
    out = []
    with open(path, "rb") as f:
        f.seek(off)
        chunk = f.read(size - off)
    if fresh and off > 0:
        nl = chunk.find(b"\n")
        chunk = chunk[nl + 1:] if nl >= 0 else b""
        off += (nl + 1) if nl >= 0 else len(chunk)
    end = chunk.rfind(b"\n")
    if end < 0:
        st.update({"offset": off, "size": size, "at": time.time()})
        return [], st, ("первое чтение: хвост без полной строки" if fresh else None)
    body = chunk[:end]
    for ln in body.split(b"\n"):
        ln = ln.strip()
        if ln:
            out.append(ln.decode("utf-8", "replace"))
    st.update({"offset": off + end + 1, "size": size, "at": time.time(),
               "read": int(st.get("read") or 0) + len(out)})
    return out, st, None


def legs_from_lines(family, lines, log=print):
    """Строки источника → ноги ТЕМ ЖЕ правилом, что реплей: лист — через
    `tournament._leg`, выборы h24 — через `run_d11.h24_leg`. Гейт книги
    применяется здесь (`run_d6.leg_gated` / `run_d10.gate_of`)."""
    c = core()
    out, bad = [], 0
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            bad += 1
            continue
        if family == "sit":
            at = rec.get("written_at") or ((c["TR"]._ts(rec.get("hour")) or 0) + 3600)
            if not at:
                bad += 1
                continue
            for arm, rows in (rec.get("arms") or {}).items():
                for row in rows or []:
                    g = c["TNT"]._leg(row, arm, rec.get("hour"), float(at))
                    if g is not None and c["D6"].leg_gated(g, None):
                        out.append(g)
        elif family == "h24":
            arm = rec.get("arm") or "gbm"
            if arm not in c["S"].ARMS or not rec.get("hour"):
                continue
            for row in rec.get("short") or []:
                g = c["D11"].h24_leg(rec, row, arm)
                # гейт отсчёта книг h24 — «любой» с краем ≥ 33 (run_d11)
                if g is not None and c["D11"].REF_GATE in c["D10"].gate_of(g):
                    out.append(g)
        else:
            bad += 1
    if bad:
        log(f"источник {family}: битых строк {bad}")
    out.sort(key=lambda g: (g["at"], g.get("arm") or "", -abs(float(g.get("fwd") or 0)), g["sym"]))
    return out


def sources_state_path(root):
    return os.path.join(root, "_intents_sources.json")


def load_sources_state(root):
    try:
        with open(sources_state_path(root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_sources_state(root, st):
    os.makedirs(root, exist_ok=True)
    tmp = sources_state_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, sources_state_path(root))


# ------------------------------------------------------------ решение

def leg_key(book, g):
    return f"{book}:{g['sym']}:{int(float(g['at']))}"


def cell_sources(rk):
    """Книги-источники ячейки: у общего счёта две, у обычной — она сама."""
    R = core()["R"]
    return list(R.parts_of(rk) or [rk])


def sub_cash(sub, st):
    """Касса подписки — депозит плюс своё реализованное (§2). Одно правило
    с `server.App.sub_cash`; здесь — чтобы модуль читался без сервера."""
    return float(sub["deposit"]) + float((st or {}).get("realized_usd") or 0.0)


def size_for(rk, sk, deposit, sizing, cash):
    """Маржа позиции источника `sk` в ячейке `rk`: доля счёта по правилу
    книги (`rules.share_in`) от кассы подписки (сложный процент) либо от
    депозита (фиксированный билет). Возвращает (маржа, доля, база)."""
    R = core()["R"]
    share = float(R.share_in(rk, sk, float(deposit)))
    base = float(cash) if (sizing or R.DEFAULT_SIZING) == R.SIZING_COMPOUND else float(deposit)
    return base * share, share, base


def plan_entry(g, sk, bars, src_tiers, now, why):
    """Геометрия входа ТЕМИ ЖЕ функциями, что бумага. None — причина в `why`."""
    c = core()
    R, D6, L, D2 = c["R"], c["D6"], c["L"], c["D2"]
    if not bars:
        why.append("баров записи нет")
        return None
    ts = [b[0] for b in bars]
    t = src_tiers.get(g["sym"]) or []
    look = lambda notl, _t=t: L.mmr_for_notional(_t, notl, flat=D2.FLAT_MMR)   # noqa: E731
    lev_look = lambda notl, _t=t: L.lev_cap_for_notional(_t, notl)           # noqa: E731
    cfg = R.RULERS.get(sk) or {}
    pl = D6.plan_position(g, bars, ts, look, cfg["rule"], cfg["param"],
                          hold_h=R.hold_of(sk), lev_look=lev_look,
                          adds=cfg.get("adds"), why=why)
    if pl is None:
        return None
    # бар входа обязан быть ЗАКРЫТ: уровни строятся по окну ВКЛЮЧИТЕЛЬНО
    # с баром входа (`build_levels`), и по незакрытому бару они другие
    if pl["entry_ts"] + MINUTE > float(now):
        why.append("бар входа ещё не закрыт")
        return "wait"
    pl["look"] = look
    return pl


def intent_row(sub, st, rk, sk, g, pl, margin, share, base, now):
    """Строка намерения входа — числа ядра, не копия."""
    c = core()
    R, D2 = c["R"], c["D2"]
    side = pl["side"]
    rungs = pl["rungs"]
    weights = list(D2.WEIGHTS[:len(rungs)])
    hold_h = float(pl["hold_h"])
    term_ts = float(g["at"]) + hold_h * HOUR
    row = {"sym": g["sym"], "side": side, "entry_px": pl["entry"], "margin": margin,
           "lev": pl["lev"], "fav_bp": g.get("fav"), "sched_end": term_ts,
           "fills": [[pl["entry_ts"], pl["entry"], weights[0]]]}
    lv = R.levels_of(row, sk, look=pl["look"]) or {}
    return {"kind": "entry", "mode": "dry", "sub": sub["id"], "cell": rk, "book": sk,
            "sizing": (st.get("sizing") or R.DEFAULT_SIZING),
            "sym": g["sym"], "side": side, "arm": g.get("arm"), "hour": g.get("hour"),
            "decided_at": float(g["at"]), "entry_ts": pl["entry_ts"],
            "computed_at": float(now), "lag_s": round(float(now) - float(g["at"]), 1),
            "px_ref": pl["entry"],
            "lev": pl["lev"], "binder": pl.get("binder"),
            "margin_usd": round(float(margin), 4), "notional_usd": round(float(margin) * pl["lev"], 4),
            "share": share, "cash_usd": round(float(base), 4),
            "rungs": [{"px": float(px), "share": float(w)} for px, w in zip(rungs, weights)],
            "rungs_full": pl["rungs_full"],
            "take_frac": abs(float(pl["take"]["frac"])) if pl.get("take") else None,
            "take_px": lv.get("take_px"), "floor_px": lv.get("floor_px"),
            "liq_px": lv.get("liq_px"), "floor_frac": lv.get("floor_frac"),
            "avg": lv.get("avg"), "term_ts": term_ts, "hold_h": hold_h,
            "fav_bp": g.get("fav"), "adv_bp": g.get("adv_q"), "fwd_bp": g.get("fwd"),
            "rr": g.get("rr"), "sigma_bp": pl.get("sigma_bp"), "stop_px": pl.get("stop_px")}


def skip_row(sub, rk, sk, g, why, now):
    return {"kind": "skip", "sub": sub["id"], "cell": rk, "book": sk, "sym": g.get("sym"),
            "side": g.get("side"), "decided_at": float(g["at"]), "computed_at": float(now),
            "arm": g.get("arm"), "fwd_bp": g.get("fwd"), "why": why}


def _append(path, rows):
    """Дозапись с растущим `seq`; возвращает число строк."""
    if not rows:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seq = 0
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    seq = max(seq, int(json.loads(ln)["seq"]))
                except (ValueError, KeyError, TypeError):
                    pass
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            seq += 1
            f.write(json.dumps(dict(r, seq=seq, written_at=time.time()), ensure_ascii=False) + "\n")
    return len(rows)


def intents_path(root, sub_id):
    return os.path.join(root, sub_id, "intents.jsonl")


def skips_path(root, sub_id):
    return os.path.join(root, sub_id, "skips.jsonl")


def read_rows(path, limit=None):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-limit:] if limit else out


def busy_names(st, book_cell, rk, sk, now):
    """Имена, занятые у источника: живые намерения подписки по той же
    книге-источнику и открытые позиции той же книги в бумажной ячейке
    (правило одной на имя — свойство ИСТОЧНИКА, `run_paper.build_rows`).
    Возвращает {имя: кто держит}."""
    out = {}
    for q in ((book_cell or {}).get("open") or {}).get("positions") or []:
        if (q.get("book") or rk) == sk and q.get("sym"):
            out[q["sym"]] = "бумага держит"
    live = ((st.get("intents") or {}).get("live") or {})
    for k, v in live.items():
        if v.get("book") == sk and float(v.get("term_ts") or 0) > now:
            out[v["sym"]] = "намерение держит"
    return out


def decide(sub, st, legs_by_family, book_cell, env, log=print):
    """Решения одной подписки по новым ногам. Возвращает (намерения,
    отказы, новое состояние `intents`)."""
    c = core()
    R, RP, PR, IR = c["R"], c["RP"], c["PR"], c["IR"]
    now = float(env.get("now") or time.time())
    rk = sub["book"]
    dep = float(sub["deposit"])
    sizing = st.get("sizing") or R.DEFAULT_SIZING
    cash = sub_cash(sub, st)
    since = float((st.get("follow") or {}).get("since") or sub["created"])
    it = dict(st.get("intents") or {})
    seen = dict(it.get("seen") or {})
    live = dict(it.get("live") or {})
    pending = list(it.get("pending") or [])
    # живые намерения: срок вышел — деньги и имя свободны
    live = {k: v for k, v in live.items() if float(v.get("term_ts") or 0) > now}
    seen = {k: v for k, v in seen.items() if float(v) > now - SEEN_KEEP_S}
    out, skips = [], []
    launch = env.get("launch")
    src_tiers = env.get("tiers") if env.get("tiers") is not None else tiers()
    bars_of = env["bars"]                          # (sym, t0, t1) -> бары
    # очередь на решение: отложенные с прошлых тактов плюс новые
    todo = [(p["book"], p["leg"], p["since_ts"]) for p in pending]
    pending = []
    for sk in cell_sources(rk):
        fam = R.family_of(sk)
        for g in legs_by_family.get(fam) or []:
            if g.get("side") != R.side_of(sk):
                continue
            if float(g["at"]) < since:
                continue
            k = leg_key(sk, g)
            if k in seen:
                continue
            # Свежесть решения — по тому, сколько оно ДОСТУПНО нам, а не по
            # метке часа: цикл пишет выборы часа xx:00 в xx:02, а после
            # перезапуска или под памятью — и в xx:31 (16:08 10.10: шесть
            # решений 15:00 отвергнуты «поздно», хотя появились минуту
            # назад). Строка, прочитанная в этот такт, не старше прошлого
            # чтения источника (`avail_age`); при первом чтении меры нет —
            # судится возраст самой метки. Отставание от метки часа едет в
            # намерение числом (`lag_s`): исполнитель решит по цене
            # (потолок от `px_ref`), а не по календарю.
            age = now - float(g["at"])
            avail = (env.get("avail_age") or {}).get(fam)
            fresh = (avail is not None and avail <= PENDING_MAX_S) or age <= PENDING_MAX_S
            if not fresh:
                seen[k] = float(g["at"])
                skips.append(skip_row(sub, rk, sk, g,
                                      f"решение пришло поздно: возраст {int(age // 60)} мин "
                                      f"(подъём после решения или источник отстал)", now))
                continue
            todo.append((sk, g, now))
    # фильтры стороны — ОДНОЙ функцией с бумагой: возраст имени у
    # коротких, гейт по ставке где объявлен
    rows_by_book = {}
    for sk, g, t0 in todo:
        rows_by_book.setdefault(sk, []).append((g, t0))
    for sk, items in rows_by_book.items():
        legs = [g for g, _ in items]
        if R.side_of(sk) == "short":
            kept, _age = RP.age_shorts(legs, rk, launch=launch, log=log, now=now)
            kept_keys = {leg_key(sk, g) for g in kept}
            for g, t0 in items:
                if leg_key(sk, g) not in kept_keys:
                    seen[leg_key(sk, g)] = float(g["at"])
                    skips.append(skip_row(sub, rk, sk, g, "возраст имени ниже порога или неизвестен", now))
            items = [(g, t0) for g, t0 in items if leg_key(sk, g) in kept_keys]
            if R.short_gate_on(rk):
                kept, _gt = PR.gate_shorts([g for g, _ in items], rk, env.get("costs_ctx"), log=log)
                kept_keys = {leg_key(sk, g) for g in kept}
                for g, t0 in items:
                    if leg_key(sk, g) not in kept_keys:
                        seen[leg_key(sk, g)] = float(g["at"])
                        skips.append(skip_row(sub, rk, sk, g, "гейт по ставке funding", now))
                items = [(g, t0) for g, t0 in items if leg_key(sk, g) in kept_keys]
        # внутри секунды — лучшие по |прогноз| первыми (правило кассы D6)
        items.sort(key=lambda x: (int(float(x[0]["at"])), -abs(float(x[0].get("fwd") or 0))))
        busy = busy_names(st, book_cell, rk, sk, now)
        for g, t0 in items:
            k = leg_key(sk, g)
            why = []
            if g["sym"] in busy:
                seen[k] = float(g["at"])
                skips.append(skip_row(sub, rk, sk, g, f"одна позиция на имя: {busy[g['sym']]}", now))
                continue
            try:
                bars = bars_of(g["sym"], float(g["at"]) - c["D2"].BACK_H * HOUR, now)
            except Exception as e:                           # noqa: BLE001
                bars = None
                why.append(f"бары не прочитаны: {e}"[:160])
            pl = plan_entry(g, sk, bars or [], src_tiers, now, why) if bars is not None else None
            # бара входа (или бара после него) ещё нет либо он не закрыт —
            # ждём до `PENDING_MAX_S` после решения, не отказываем: запись
            # сборщика догоняет решение минутами
            no_bar = pl is None and (not bars or (why and why[-1].startswith("нет бара")))
            if pl == "wait" or (no_bar and float(g["at"]) + PENDING_MAX_S > now):
                pending.append({"book": sk, "leg": g, "since_ts": t0,
                                "why": (why[-1] if why else "ждём бар входа")})
                continue
            if pl is None:
                seen[k] = float(g["at"])
                msg = "; ".join(why) or "геометрии нет"
                if no_bar:
                    msg = f"бар входа не пришёл за {int(PENDING_MAX_S // 60)} мин: {msg}"
                skips.append(skip_row(sub, rk, sk, g, msg, now))
                continue
            ml = R.min_lev_of(sk)
            if ml is not None and pl["lev"] < ml:
                seen[k] = float(g["at"])
                skips.append(skip_row(sub, rk, sk, g, f"гейт плеча: {pl['lev']:.2f} < {ml:g}", now))
                continue
            margin, share, base = size_for(rk, sk, dep, sizing, cash)
            if margin * pl["lev"] * R.RUNG_SHARE < R.MIN_NOTIONAL:
                seen[k] = float(g["at"])
                skips.append(skip_row(sub, rk, sk, g,
                                      f"мельче минимума биржи: рунг {margin * pl['lev'] * R.RUNG_SHARE:.2f} $ "
                                      f"< {R.MIN_NOTIONAL:g}", now))
                continue
            used = sum(float(v.get("margin_usd") or 0) for v in live.values())
            free = base - used
            if margin > free + 1e-9 * base:
                seen[k] = float(g["at"])
                skips.append(skip_row(sub, rk, sk, g, f"нет кассы: нужно {margin:.2f} $, свободно {free:.2f} $", now))
                continue
            row = intent_row(sub, st, rk, sk, g, pl, margin, share, base, now)
            out.append(row)
            seen[k] = float(g["at"])
            live[k] = {"sym": g["sym"], "book": sk, "margin_usd": row["margin_usd"],
                       "term_ts": row["term_ts"], "at": float(g["at"]), "side": row["side"]}
            busy[g["sym"]] = "намерение держит"
    # отложенные, которым бар так и не пришёл, — отказ с причиной
    keep = []
    for p in pending:
        if float(p["leg"]["at"]) + PENDING_MAX_S <= now:
            k = leg_key(p["book"], p["leg"])
            seen[k] = float(p["leg"]["at"])
            skips.append(skip_row(sub, rk, p["book"], p["leg"],
                                  f"бар входа не пришёл за {int(PENDING_MAX_S // 60)} мин: {p.get('why')}", now))
        else:
            keep.append(p)
    it.update({"seen": seen, "live": live, "pending": keep, "at": now,
               "last_lag_s": (max(r["lag_s"] for r in out) if out else it.get("last_lag_s")),
               "n": int(it.get("n") or 0) + len(out), "n_skips": int(it.get("n_skips") or 0) + len(skips),
               "last_decided_at": (max([r["decided_at"] for r in out]) if out else it.get("last_decided_at")),
               "cash_usd": cash, "sizing": sizing})
    return out, skips, it


# ------------------------------------------------------------ сверка с бумагой

def _bp(a, b):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    return None if b == 0 else round((a / b - 1.0) * 1e4, 2)


def paper_rows(book_cell, rk):
    """Позиции бумажной ячейки — открытые и хвост закрытых — с книгой-источником."""
    out = []
    for q in ((book_cell or {}).get("open") or {}).get("positions") or []:
        out.append(dict(q, _src=(q.get("book") or rk), _closed=False))
    for t in (book_cell or {}).get("trades") or []:
        out.append(dict(t, _src=(t.get("book") or rk), _closed=True))
    return out


def match_paper(intent, rows):
    """Строка бумаги того же решения: имя, источник, секунда решения."""
    for q in rows:
        if q.get("sym") != intent.get("sym") or q.get("_src") != intent.get("book"):
            continue
        try:
            if abs(float(q.get("at")) - float(intent["decided_at"])) <= 1.0:
                return q
        except (TypeError, ValueError):
            continue
    return None


def parity_one(intent, q):
    """Расхождение намерения с бумажной строкой — числом по полю."""
    lv = q.get("levels") or {}
    walk = q.get("walk") or []
    take_paper = lv.get("take_px") if lv.get("take_px") is not None else (walk[0].get("take") if walk else None)
    out = {"sym": intent["sym"], "decided_at": intent["decided_at"],
           "entry_bp": _bp(intent.get("px_ref"), q.get("entry_px")),
           "lev_d": (round(float(intent["lev"]) - float(q["lev"]), 4)
                     if intent.get("lev") is not None and q.get("lev") is not None else None),
           "margin_d": (round(float(intent["margin_usd"]) - float(q["margin"]), 4)
                        if q.get("margin") is not None else None),
           "take_bp": _bp(intent.get("take_px"), take_paper),
           "floor_bp": _bp(intent.get("floor_px"), lv.get("floor_px")),
           "paper_closed": bool(q.get("_closed"))}
    return out


def parity(root, sub, st, book_cell, since=None, tail=PARITY_TAIL):
    """Сверка намерений подписки с бумажной ячейкой: совпавшие — с
    расхождениями по полю (медиана и максимум |Δ|), намерения без
    строки бумаги, строки бумаги без намерения (с причиной из отказов)."""
    rk = sub["book"]
    since = float(since if since is not None else ((st.get("follow") or {}).get("since") or sub["created"]))
    ints = [r for r in read_rows(intents_path(root, sub["id"]), tail) if r.get("kind") == "entry"]
    skips = read_rows(skips_path(root, sub["id"]), tail * 4)
    rows = paper_rows(book_cell, rk)
    matched, intent_only = [], []
    taken = set()
    for r in ints:
        q = match_paper(r, rows)
        if q is None:
            intent_only.append({"sym": r["sym"], "decided_at": r["decided_at"], "book": r["book"]})
        else:
            taken.add(id(q))
            matched.append(parity_one(r, q))
    skip_why = {f"{s.get('book')}:{s.get('sym')}:{int(float(s.get('decided_at') or 0))}": s.get("why")
                for s in skips if s.get("decided_at") is not None}
    paper_only = []
    for q in rows:
        try:
            at = float(q.get("at"))
        except (TypeError, ValueError):
            continue
        if at < since or id(q) in taken:
            continue
        key = f"{q.get('_src')}:{q.get('sym')}:{int(at)}"
        paper_only.append({"sym": q.get("sym"), "decided_at": at, "book": q.get("_src"),
                           "why": skip_why.get(key, "намерения не было (решение до подъёма или источник не прочитан)")})

    def _agg(field):
        vals = sorted(abs(float(m[field])) for m in matched if m.get(field) is not None)
        if not vals:
            return None
        return {"n": len(vals), "median": vals[len(vals) // 2], "max": vals[-1]}
    return {"since": since, "intents": len(ints), "matched": len(matched),
            "intent_only": len(intent_only), "paper_only": len(paper_only),
            "paper_rows_since": sum(1 for q in rows if (q.get("at") or 0) >= since),
            "fields": {f: _agg(f) for f in ("entry_bp", "lev_d", "margin_d", "take_bp", "floor_bp")},
            "last": matched[-5:], "intent_only_tail": intent_only[-5:], "paper_only_tail": paper_only[-5:],
            "at": time.time()}


def summary(st):
    """Что отдаёт состояние подписки приложению (§10a L1: «намерения за час»)."""
    it = (st or {}).get("intents") or {}
    return {"at": it.get("at"), "n": it.get("n"), "n_skips": it.get("n_skips"),
            "live": len(it.get("live") or {}), "pending": len(it.get("pending") or []),
            "last_decided_at": it.get("last_decided_at"), "cash_usd": it.get("cash_usd"),
            "source_age_s": it.get("source_age_s"), "last_lag_s": it.get("last_lag_s"),
            "parity": it.get("parity"), "error": it.get("error")}


# ------------------------------------------------------------ такт

def cell_key(book, deposit, sizing):
    k = f"{book}:{int(float(deposit))}"
    return k if (sizing or "compound") == "compound" else f"{k}:{sizing}"


def tick(db, dca, root, log=print, env=None):
    """Один такт по всем активным подпискам. Возвращает число намерений.

    `env` — подмены для проверок: `files` (источники по семейству),
    `bars` (функция баров), `launch` (справочник листингов), `tiers`,
    `now`. Без них — настоящие источники, запись сборщика, справочники.
    """
    subs = db.c.execute("SELECT * FROM subscriptions WHERE status='active'").fetchall()
    if not subs:
        return 0
    env = dict(env or {})
    now = float(env.get("now") or time.time())
    env["now"] = now
    c = core()
    R = c["R"]
    # какие семейства нужны подпискам — только их источники и читаются
    fams = set()
    for s in subs:
        for sk in cell_sources(s["book"]):
            fams.add(R.family_of(sk))
    files = source_files(env.get("files"))
    sst = load_sources_state(root)
    legs_by_family = {}
    for fam in sorted(fams):
        path = files.get(fam)
        if not path:
            log(f"намерения: у семейства {fam} нет источника")
            continue
        lines, st2, why = read_tail(path, sst.get(path) or {})
        sst[path] = st2
        if why:
            log(f"намерения: {os.path.basename(path)} — {why}")
        legs_by_family[fam] = legs_from_lines(fam, lines, log=log) if lines else []
        prev = st2.get("prev_at")
        env.setdefault("avail_age", {})
        if fam not in env["avail_age"]:
            env["avail_age"][fam] = (now - float(prev)) if prev else None
    save_sources_state(root, sst)
    # возраст источников — в состояние каждой подписки: «0 намерений» при
    # стоящем источнике и при тихом часе выглядят одинаково, различает их
    # только это число (часовой шаг цикла молчит на время обучения)
    src_age = {}
    for fam in sorted(fams):
        path = files.get(fam)
        try:
            src_age[fam] = round(now - os.path.getmtime(path), 1) if path else None
        except OSError:
            src_age[fam] = None
    if "bars" not in env:
        src = env.get("src") or bars_source(log=None)
        env["bars"] = src.bars
    if "launch" not in env:
        try:
            env["launch"] = c["IR"].launches()
        except Exception:                                    # noqa: BLE001
            env["launch"] = {}
    n = 0
    books = (dca or {}).get("books") or {}
    for s in subs:
        st = json.loads(s["state_json"] or "{}")
        book_cell = books.get(cell_key(s["book"], s["deposit"], st.get("sizing")))
        try:
            ints, skips, it = decide(s, st, legs_by_family, book_cell, env, log=log)
            if ints:
                n += _append(intents_path(root, s["id"]), ints)
                log(f"намерения {s['book']} {float(s['deposit']):g} $: входов {len(ints)}"
                    + (f", отказов {len(skips)}" if skips else ""))
            if skips:
                _append(skips_path(root, s["id"]), skips)
            it.pop("error", None)
            if ints or skips or book_cell:
                try:
                    it["parity"] = parity(root, s, st, book_cell)
                except Exception as e:                       # noqa: BLE001
                    it["parity"] = {"error": str(e)[:200]}
        except Exception as e:                               # noqa: BLE001
            it = dict(st.get("intents") or {})
            it["error"] = f"{type(e).__name__}: {e}"[:200]
            log(f"намерения {s['book']}: {it['error']}")
        it["source_age_s"] = {fam: src_age.get(fam) for fam in
                              {R.family_of(sk) for sk in cell_sources(s["book"])}}
        st["intents"] = it
        db.set_sub_state(s["id"], st)
    return n


def reset_sub(db, root, sub_id, now=None):
    """Сброс намерений подписки: файлы НЕ удаляются — переименовываются в
    `*-stale-<момент>.jsonl` (запись остаётся), состояние `intents`
    очищается, смещения источников не трогаются. Нужен, когда состояние
    набрано не теми правилами (первый подъём 10.10 записал намерения по
    решениям задним числом). Возвращает, что сделано, словами."""
    now = float(now or time.time())
    tag = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    moved = []
    for path in (intents_path(root, sub_id), skips_path(root, sub_id)):
        if os.path.exists(path):
            dst = path[:-len(".jsonl")] + f"-stale-{tag}.jsonl"
            os.replace(path, dst)
            moved.append(os.path.basename(dst))
    row = db.c.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    if row is None:
        return {"error": f"подписки {sub_id} нет", "moved": moved}
    st = json.loads(row["state_json"] or "{}")
    had = st.pop("intents", None)
    db.set_sub_state(sub_id, st)
    return {"sub": sub_id, "moved": moved, "had_intents": (had or {}).get("n"),
            "had_live": len((had or {}).get("live") or {})}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="сверка намерений исполнителя с бумажными книгами")
    ap.add_argument("--db", default=os.path.join(HERE, "out", "app.sqlite"))
    ap.add_argument("--root", default=None, help="корень журналов исполнителя (умолчание — сервера)")
    ap.add_argument("--check", action="store_true", help="напечатать сверку по подпискам")
    ap.add_argument("--tail", type=int, default=20, help="сколько последних намерений и отказов показать")
    ap.add_argument("--reset-sub", default=None, help="сбросить намерения подписки (файлы переименовываются, не удаляются)")
    a = ap.parse_args(argv)
    sys.path.insert(0, HERE)
    import server as SV                                      # noqa: E402
    import db as DBM                                         # noqa: E402
    root = a.root or SV.EXEC_ROOT
    db = DBM.DB(a.db)
    if a.reset_sub:
        print("сброс:", json.dumps(reset_sub(db, root, a.reset_sub), ensure_ascii=False))
    dca = None
    try:
        dca = SV.fetch_dca()
    except Exception as e:                                   # noqa: BLE001
        print(f"свод книг не прочитан: {e}")
    books = (dca or {}).get("books") or {}
    subs = db.c.execute("SELECT * FROM subscriptions WHERE status='active'").fetchall()
    print(f"подписок активных {len(subs)}; корень {root}")
    for path, st in (load_sources_state(root) or {}).items():
        print(f"источник {os.path.relpath(path, ROOT)}: смещение {st.get('offset')} из {st.get('size')}, "
              f"прочитано строк {st.get('read', 0)}, "
              f"последнее чтение {time.strftime('%Y-%m-%d %H:%M', time.gmtime(st.get('at') or 0))} UTC")
    for s in subs:
        st = json.loads(s["state_json"] or "{}")
        sizing = st.get("sizing") or "compound"
        print(f"\n== {s['book']} {float(s['deposit']):g} $ {sizing} ({s['id']}), касса {sub_cash(s, st):.2f} $")
        it = st.get("intents") or {}
        ages = ", ".join(f"{k} {int(v // 60)} мин" if v is not None else f"{k} —"
                         for k, v in (it.get("source_age_s") or {}).items())
        print(f"такт {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(it.get('at') or 0))} UTC; "
              f"возраст источников: {ages or '—'}; "
              f"намерений {it.get('n', 0)}, отказов {it.get('n_skips', 0)}, живых {len(it.get('live') or {})}, "
              f"ждут бар {len(it.get('pending') or [])}"
              + (f"; ошибка: {it['error']}" if it.get("error") else ""))
        for r in read_rows(intents_path(root, s["id"]), a.tail):
            print(f"  вход {time.strftime('%m-%d %H:%M', time.gmtime(r['decided_at']))} (+{int((r.get('lag_s') or 0) // 60)} мин) {r['sym']} {r['side']} "
                  f"x{r['lev']:.2f} маржа {r['margin_usd']:.2f} $ вход {r['px_ref']} цель {r.get('take_px')} "
                  f"пол {r.get('floor_px')} рунгов {len(r.get('rungs') or [])} срок {r['hold_h']:g} ч")
        for r in read_rows(skips_path(root, s["id"]), a.tail):
            print(f"  отказ {time.strftime('%m-%d %H:%M', time.gmtime(r['decided_at']))} {r['sym']} — {r['why']}")
        if a.check:
            p = parity(root, s, st, books.get(cell_key(s["book"], s["deposit"], sizing)))
            print(f"  сверка с бумагой: намерений {p['intents']}, совпало {p['matched']}, "
                  f"без бумаги {p['intent_only']}, бумага без намерения {p['paper_only']} "
                  f"(строк бумаги с подписки {p['paper_rows_since']})")
            for f, v in p["fields"].items():
                print(f"    {f}: " + ("—" if not v else f"n {v['n']}, медиана |Δ| {v['median']}, макс {v['max']}"))
            for q in p["paper_only_tail"]:
                print(f"    бумага без намерения: {q['sym']} {time.strftime('%m-%d %H:%M', time.gmtime(q['decided_at']))} — {q['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
