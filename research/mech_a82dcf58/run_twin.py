#!/usr/bin/env python3
"""Механика a82dcf58 — прогон: DCA-лестница на СЛУЧАЙНОМ ИМЕНИ того же
часа как одновременная кросс-секция.

Вопрос один: **чьи это деньги — выбора модели или часа рынка.** Память
проекта называет DCA «единственным направлением с положительным
механизмом» и стоит на числе S − B = +1.69 % медианы НА ВЫБОРАХ МОДЕЛИ.
Слова «на выборах модели» ни разу не проверялись: шесть нулей спеки 14 §8
меняют лестницу, срок, выход — но не ИМЯ.

Здесь каждому гейтованному лонгу журнала листов ставится двойник:
случайное имя из строки ТОГО ЖЕ ЧАСА (всё сечение, ~700 имён), только
крипто, не гейтованный выбор, из того же дециля суточной σ. Двойнику
ПЕРЕСАЖИВАЕТСЯ геометрия выбора — смещения рунгов в долях цены входа,
доля тейка, веса, плечо, — и меняется только имя с его ценовым путём.
Это перестановка меток A4 на лестнице при неизменной форме и неизменном
плече.

Руки:

* **S** — выбор модели: базовая ячейка D2/D3 (гейт края 33 б.п. и RR ≥ 2,
  структурные уровни T4, забор §5, пол капитуляции 0.10, срок 72 ч, тейк
  по mfe модели от входа);
* **T1σ** — двойник, подобранный по децилю σ; ЯЧЕЙКА ВЕРДИКТА;
* **T1** — двойник без подбора σ; диагностика (T1σ − T1 = цена выбора
  волатильности);
* **T2** — тот же двойник СО СВОЕЙ геометрией (свои уровни по своим 24 ч,
  своё §5-плечо, свой тейк по своему mfe той же строки листа); диагностика
  «что книга заработала бы на случайных именах».

Честное ожидание, названное ДО прогона (заявка): S от T1σ не отличится, и
тогда деньги DCA-книг есть плечо × рынок часа, а лестница — форма.

Два прохода по записи, и это не роскошь. Проход 1 меряет σ у КАЖДОГО
кандидата каждого часа (децили считаются по сечению часа целиком) и
заодно, пока бары символа в памяти, собирает геометрию и руку S его
выборов. Проход 2 идёт снова ПО СИМВОЛУ и считает всех его двойников
всех розыгрышей: розыгрыши назначены ЗАРАНЕЕ (зерно числом, номер
розыгрыша в ключе), поэтому бары каждого имени читаются один раз, а не
на каждый розыгрыш. σ кладётся в кэш на символ — повторный прогон её не
пересчитывает.

Запуск (VPS; журнал листов и запись баров только там):

    setsid nohup nice -n 19 .venv/bin/python \\
        research/mech_a82dcf58/run_twin.py \\
        > research/mech_a82dcf58/out/run_twin.log 2>&1 &

Смоук: `--limit N --draws K`. Калибровка: `--calibrate` (синтетика, той
же дорогой). Публикует отчёт сам; `--no-publish` выключает.
"""

import argparse
import json
import os
import resource
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(HERE, ".cache_sigma")

sys.path.insert(0, HERE)
import twin as T                                            # noqa: E402
from twin import D2, D3, L, P, UF                           # noqa: E402,F401

sys.path.insert(0, os.path.join(RESEARCH, "s10_policy"))
sys.path.insert(0, os.path.join(RESEARCH, "s9_sweep"))
sys.path.insert(0, os.path.join(RESEARCH, "mech_49b535f8"))
import tournament as TNT                                    # noqa: E402
import sweep as SW                                          # noqa: E402
import run_place as RP                                      # noqa: E402

SIG_CACHE_V = 1                        # версия меры σ (ключ кэша)
MEM_NEED_MB = 1300                     # состав: журнал листов ~880 МБ
MEM_SHARE = 0.6                        # задание: не больше 0.6 доступной
PROGRESS_S = 30                        # молчать дольше нельзя


def log_(m):
    print(m, flush=True)


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


def mem_available_mb():
    """Свободная память машины, МБ. Не прочитали — None, а не ноль."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def mem_guard(need_mb=MEM_NEED_MB, share=MEM_SHARE, log=log_):
    """Отказаться ГРОМКО, если прогон не влезает рядом со сборщиком.

    Запись стакана — единственное невосстановимое в проекте: прогон,
    уронивший сборщик по памяти, стоит суток записи, которых неоткуда
    взять (2026-09-06: D10 в 2.1 ГБ убил часовой цикл ядром). Нужное
    считается СОСТАВОМ и печатается числом рядом с доступным.
    """
    have = mem_available_mb()
    if have is None:
        log("память машины не прочиталась — иду, но осторожно")
        return True
    log(f"память: нужно ~{need_mb} МБ, доступно {have} МБ "
        f"(порог {share:.0%})")
    if need_mb > have * share:
        log("ОТКАЗ: прогон не влезает рядом со сбором. Дождаться свободной "
            "памяти либо сузить население ключом --limit.")
        return False
    return True


def mem_limit_mb(share=MEM_SHARE, log=log_):
    """Предел РАБОЧЕЙ памяти прогона: доля доступной, взятая на старте.

    Не прочиталась — предела нет (None), и это «не измерено», а не
    «сколько угодно»: прогон тогда идёт, но говорит об этом вслух.
    """
    have = mem_available_mb()
    if have is None:
        log("предел памяти не выведен — доступная не прочиталась")
        return None
    lim = int(have * float(share))
    log(f"предел памяти прогона {lim} МБ ({share:.0%} от доступных {have})")
    return lim


def mem_stop(limit, where, log=log_):
    """Выше предела — прогон снимает СЕБЯ, с числом и словами.

    Тяжёлый прогон рядом с часовым циклом убивает не себя, а ЦИКЛ: ядро
    выбирает жертву по-своему, трассировки не оставляет, буфер stdout
    гибнет с SIGKILL (2026-09-06, D10 в 2.1 ГБ). Самоостанов дешевле
    убитого цикла и неотличимой от тишины смерти.
    """
    if not limit:
        return None
    rss = peak_rss_mb()
    if rss > limit:
        raise SystemExit(f"ОСТАНОВ: память {rss} МБ выше предела {limit} МБ "
                         f"({where}) — рядом сборщик и часовой цикл, прогон "
                         "снял себя сам, чтобы не убили цикл")
    return rss


def state(tag, **kw):
    """Состояние файлом: молчащий прогон неотличим от повисшего."""
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, f"state-{tag}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(dict(kw, at=round(time.time(), 1),
                           rss_mb=peak_rss_mb()), f, ensure_ascii=False)
    except OSError:
        pass


# ------------------------------------------------------------- население

def load(limit=None, stride=1, log=log_, legs=None):
    """Выборы книги и СЕЧЕНИЯ их часов из журнала листов.

    Выборы — гейтованные лонги, тем же гейтом, что D2/D3: состав обязан
    совпадать с опубликованным бит в бит, разойдись он — и таблицы
    сравнивались бы с числами другой книги, обе выглядя исправными.

    Сечение часа берётся ИЗ ТОЙ ЖЕ строки журнала (`legs_from_sheets`
    отдаёт все строки листа, а не только гейтованные) — второго читателя
    журнала не заводится.

    Запреты пула применяются здесь: не-крипто и ВСЕ гейтованные выборы
    часа (в них лежит и сам выбор). `stride` — прорежение для смоука:
    население журнала лежит в трёх сутках (20–22 августа), и «первые N»
    описывают неделю тишины, а не то, что считает боевой прогон.
    """
    legs = list(legs) if legs is not None else TNT.legs_from_sheets(
        [D2.SHEETS], log=log)
    gate = [g for g in legs if g["side"] == "long"
            and abs(g["fwd"]) >= T.MIN_EDGE_BP and (g["rr"] or 0) >= T.MIN_RR]
    log(f"ног всего {len(legs)}, лонгов под гейтом книги "
        f"(край ≥ {T.MIN_EDGE_BP}, RR ≥ {T.MIN_RR}) {len(gate)}")
    # Запрет «не другой гейтованный выбор этого часа» считается по ПОЛНОМУ
    # гейту, а не по прореженному: прорежение есть свойство смоука, и
    # менять из-за него состав запретов значило бы мерить другую книгу.
    gated_by_at = {}
    for g in gate:
        gated_by_at.setdefault(float(g["at"]), set()).add(g["sym"])

    picks = gate
    if stride and int(stride) > 1:
        picks = picks[::int(stride)]
        log(f"прорежено шагом {stride}: осталось {len(picks)}")
    if limit:
        picks = picks[:int(limit)]
        log(f"лимит: взято {len(picks)}")
    want_at = {float(g["at"]) for g in picks}

    non_crypto = UF.non_crypto_set()
    pools = {}
    for g in legs:
        at = float(g["at"])
        if at not in want_at:
            continue                    # сечения часов без выборов не нужны
        key = (at, g["arm"])
        p = pools.get(key)
        if p is None:
            p = pools[key] = {"syms": [], "fav": []}
        p["syms"].append(sys.intern(str(g["sym"])))
        p["fav"].append(float(g["fav"]))
    del legs
    kept = 0
    for (at, _arm), p in pools.items():
        m = T.pool_mask(p["syms"], gated_by_at.get(at, ()), non_crypto)
        p["syms"] = [s for s, ok in zip(p["syms"], m) if ok]
        p["fav"] = [v for v, ok in zip(p["fav"], m) if ok]
        kept += len(p["syms"])
    log(f"сечений часов {len(pools)}, кандидатов после запретов {kept} "
        f"(не-крипто в справочнике {len(non_crypto)})")
    return picks, pools


# --------------------------------------------------------------- кэш σ

def _cache_path(sym):
    return os.path.join(CACHE, f"{sym}.json")


def cache_read(sym):
    try:
        with open(_cache_path(sym), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if d.get("v") != SIG_CACHE_V or d.get("back_h") != T.BACK_H:
        return {}                       # мера другая — кэш не годится
    return d.get("sig") or {}


def cache_write(sym, sig):
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(_cache_path(sym), "w", encoding="utf-8") as f:
            json.dump({"v": SIG_CACHE_V, "back_h": T.BACK_H, "sig": sig}, f)
    except OSError:
        pass


# ------------------------------------------------------- проход 1 из 2

def needs(picks, pools):
    """Что у кого нужно: символ → моменты решений (σ) и его выборы."""
    sig_need, pick_by = {}, {}
    for i, g in enumerate(picks):
        pick_by.setdefault(g["sym"], []).append(i)
        sig_need.setdefault(g["sym"], set()).add(float(g["at"]))
    for (at, _arm), p in pools.items():
        for s in p["syms"]:
            sig_need.setdefault(s, set()).add(at)
    return sig_need, pick_by


def pass_one(picks, sig_need, pick_by, get, tiers_all, log=log_, tag="1m",
             use_cache=True, mem_lim=None):
    """σ каждого кандидата каждого часа и рука S каждого выбора.

    Один проход по символам: бары имени читаются РАЗ, на них считается и
    σ (для децилей часа), и геометрия его собственных выборов. Второй
    проход на то же чтение стоил бы часа записи впустую.

    Возвращает `(sig, setups, skipped, reads)`, где `sig[sym][at]` — σ в
    б.п. (NaN не кладётся вовсе: «не измерено» есть отсутствие ключа, а
    не ноль), `setups[i]` — геометрия и рука S выбора `i` либо None.
    """
    sig = {}
    setups = [None] * len(picks)
    said = time.time()
    done = reads = skipped = 0
    syms = sorted(sig_need)
    for sym in syms:
        done += 1
        ats = sorted(sig_need[sym])
        mine = pick_by.get(sym) or []
        cached = cache_read(sym) if use_cache else {}
        need = [a for a in ats if str(int(a)) not in cached]
        bars = ts = None
        if need or mine:
            a0 = min(ats) - T.BACK_H * 3600
            b1 = (max(ats) + T.HOLD_H * 3600) if mine else (max(ats) + 3600)
            bars = get(sym, a0, b1)
            reads += 1
            ts = [b[0] for b in bars] if bars else []
        fresh = {}
        if bars:
            for a in need:
                s_bp = T.sigma_at(bars, ts, a)
                if s_bp == s_bp:
                    fresh[str(int(a))] = float(s_bp)
        if fresh and use_cache:
            cached = dict(cached, **fresh)
            cache_write(sym, cached)
        elif fresh:
            cached = dict(cached, **fresh)
        got = {}
        for a in ats:
            v = cached.get(str(int(a)))
            if v is not None:
                got[a] = float(v)
        if got:
            sig[sym] = got
        # выборы этого имени: геометрия и рука S, пока бары в памяти
        tiers = tiers_all.get(sym) or []

        def look(notl, _t=tiers):
            return L.mmr_for_notional(_t, notl, flat=T.FLAT_MMR)

        for i in mine:
            g = picks[i]
            if not bars:
                skipped += 1
                continue
            st = RP.setup(g, bars, ts)
            if st is None:
                skipped += 1
                continue
            entry, rungs = st["entry"], st["rungs"]
            lev, rungs = P.fence_lev(rungs, entry, P.depth_of(entry, rungs),
                                     look)
            res = T.sim(st["hold"], rungs, lev, look(1.0 * lev),
                        st["take_px"])
            setups[i] = {
                "geo": T.geometry(entry, rungs, st["take_px"], lev),
                "mmr": float(look(1.0 * lev)), "lev": float(lev),
                "k": int(len(rungs)), "entry": float(entry),
                "sigma": float(st["sigma_bp"]),
                "pnl": float(res["pnl_frac"]),
                "exit": res.get("exit"),
                "exit_ts": float(res["exit_ts"])}
        if time.time() - said > PROGRESS_S:
            log(f"  проход 1: символ {done}/{len(syms)}, чтений {reads}, "
                f"σ у {len(sig)} имён, RSS {peak_rss_mb()} МБ")
            said = time.time()
        mem_stop(mem_lim, f"проход 1, символ {done}/{len(syms)}", log)
        state(tag, step="sigma", sym_done=done, sym_all=len(syms),
              reads=reads, skipped=skipped)
    log(f"проход 1: символов {len(syms)}, чтений {reads}, "
        f"выборов с геометрией {sum(1 for s in setups if s)}, "
        f"пропущено {skipped}")
    return sig, setups, skipped, reads


# --------------------------------------------------------- назначение

def assign(picks, pools, sig, setups, draws=T.DRAWS, seed=T.SEED, log=log_):
    """Двойники всех розыгрышей, назначенные ЗАРАНЕЕ. Чистый шаг.

    Дециль σ считается ВНУТРИ ЧАСА по сечению целиком: волатильность
    гуляет по дням, и дециль, посчитанный по всей записи, подбирал бы
    двойника из другого режима. Возвращает `(MT, PT, diag)`: матрицы
    `позиции × розыгрыши` с индексами имён (−1 — двойника нет) и
    диагностику подбора.
    """
    n = len(picks)
    MT = np.full((n, int(draws)), -1, dtype=np.int32)
    PT = np.full((n, int(draws)), -1, dtype=np.int32)
    names = []                          # индекс → (sym, fav)
    idx_of = {}
    no_dec = no_pool = 0
    edges_cache = {}
    for i, g in enumerate(picks):
        st = setups[i]
        if st is None:
            continue
        key = (float(g["at"]), g["arm"])
        pool = pools.get(key)
        if not pool or not pool["syms"]:
            no_pool += 1
            continue
        at = float(g["at"])
        if key not in edges_cache:
            vals = [sig.get(s, {}).get(at, float("nan"))
                    for s in pool["syms"]]
            edges_cache[key] = (T.decile_edges(vals), vals)
        edges, vals = edges_cache[key]
        pick_dec = T.decile_of(st["sigma"], edges)
        if pick_dec is None:
            no_dec += 1
        loc = []
        for j, s in enumerate(pool["syms"]):
            if (s, at) not in idx_of:
                idx_of[(s, at)] = len(names)
                names.append((s, float(pool["fav"][j]), at))
            loc.append(idx_of[(s, at)])
        dec = [T.decile_of(v, edges) for v in vals]
        m, p = T.assign_twins(loc, dec, pick_dec, draws, int(g["id"]), seed)
        for j in range(int(draws)):
            if m[j] is not None:
                MT[i, j] = m[j]
            if p[j] is not None:
                PT[i, j] = p[j]
    log(f"назначено: подобранных по σ "
        f"{int((MT >= 0).sum())}, без подбора {int((PT >= 0).sum())} "
        f"из {n * int(draws)} пар; часов без дециля {no_dec}, "
        f"часов без сечения {no_pool}")
    return MT, PT, names, {"no_decile": no_dec, "no_pool": no_pool}


# ------------------------------------------------------- проход 2 из 2

def _one_twin(k, lo, hi, rows, cols, kind, names, setups, bars, ts, look,
              mmr_from, mats, acc):
    """Все задания ОДНОГО двойника (имя × час): окно нарезается один раз.

    Задания `[lo, hi)` отсортированы так, что делят одно `k` — то есть
    одно имя и один момент решения. Окно и своя геометрия у них общие, и
    считать их на каждый розыгрыш значило бы платить сотню раз за одно и
    то же. Отличается только ВЫБОР, чья геометрия пересаживается, поэтому
    память ключуется номером выбора — ровно тем, от чего исход зависит.
    """
    R_M, X_M, R_P, X_P, R_2, X_2 = mats
    _sym, fav, at = names[k]
    rs = T.twin_window(bars, ts, at)
    if rs is None:
        acc["no_window"] += hi - lo
        return
    win, now_i = rs
    hold = win[now_i:]
    e_t = float(hold[0][1])
    if not (e_t > 0):
        acc["no_window"] += hi - lo
        return
    memo, own = {}, 0
    for q in range(lo, hi):
        r, c = int(rows[q]), int(cols[q])
        st = setups[r]
        res = memo.get(r)
        if res is None:
            rungs, take = T.transplant(st["geo"], e_t)
            # MMR пересаживается от ВЫБОРА (ячейка вердикта): у двойника
            # меняется имя с его ценовым путём, а ставка тира путём не
            # является. Ключ `--mmr own` считает тем же кодом по тиру
            # двойника, и расхождение ставок печатается числом.
            mmr = st["mmr"] if mmr_from == "pick" else float(
                look(1.0 * st["lev"]))
            res = memo[r] = T.sim(hold, rungs, st["lev"], mmr, take)
            acc["mmr_seen"] += 1
            acc["mmr_diff"] += int(
                abs(float(look(1.0 * st["lev"])) - st["mmr"]) > 1e-12)
        if int(kind[q]) == 0:
            R_M[r, c] = res["pnl_frac"]
            X_M[r, c] = int(res["exit_ts"])
            acc["liq_m"] += int(res.get("exit") == "ликвидация")
            # T2 — своя геометрия ЭТОГО имени: от выбора она не зависит
            # вовсе, поэтому считается один раз на (имя × час).
            if own == 0:
                g2, why = T.own_geometry(win, now_i, fav, look)
                if g2 is None:
                    own = None
                    acc["t2_why"][why] = acc["t2_why"].get(why, 0) + 1
                else:
                    own = T.sim(g2["hold"], g2["rungs"], g2["lev"],
                                look(1.0 * g2["lev"]), g2["take_px"])
            if own is not None:
                R_2[r, c] = own["pnl_frac"]
                X_2[r, c] = int(own["exit_ts"])
        else:
            R_P[r, c] = res["pnl_frac"]
            X_P[r, c] = int(res["exit_ts"])
            acc["liq_p"] += int(res.get("exit") == "ликвидация")


def pass_two(setups, MT, PT, names, get, tiers_all, log=log_,
             tag="1m", mmr_from=T.MMR_FROM, mem_lim=None):
    """Двойники: бары каждого имени читаются ОДИН раз на все розыгрыши.

    Внешний цикл идёт ПО СИМВОЛУ — иначе сто розыгрышей означали бы сто
    чтений одного и того же имени, а чтение записи и есть цена прогона.
    Задания раскладываются массивами, а не списком питоновых кортежей:
    пар «позиция × розыгрыш» под миллион, и список из них весит вчетверо
    больше самих матриц.

    Двойника нет либо баров у него нет — NaN (прочерк), а не ноль: ноль
    означал бы «двойник сработал ровно в ноль» там, где двойника не было.
    """
    n, d = MT.shape
    R_M = np.full((n, d), np.nan, dtype=np.float64)
    X_M = np.zeros((n, d), dtype=np.int64)
    R_P = np.full((n, d), np.nan, dtype=np.float64)
    X_P = np.zeros((n, d), dtype=np.int64)
    R_2 = np.full((n, d), np.nan, dtype=np.float64)
    X_2 = np.zeros((n, d), dtype=np.int64)
    acc = {"liq_m": 0, "liq_p": 0, "mmr_seen": 0, "mmr_diff": 0,
           "no_window": 0, "no_bars": 0, "t2_why": {}}
    syms = sorted({nm[0] for nm in names})
    s_of = {s: i for i, s in enumerate(syms)}
    ksym = np.array([s_of[nm[0]] for nm in names], dtype=np.int32)
    rm, cm = np.nonzero(MT >= 0)
    rp, cp = np.nonzero(PT >= 0)
    rows = np.concatenate([rm, rp]).astype(np.int32)
    cols = np.concatenate([cm, cp]).astype(np.int32)
    kk = np.concatenate([MT[rm, cm], PT[rp, cp]]).astype(np.int32)
    kind = np.concatenate([np.zeros(len(rm), np.int8),
                           np.ones(len(rp), np.int8)])
    del rm, cm, rp, cp
    # Сортировка по (символ, имя-час): символы идут группами, внутри
    # символа — группами по часу, и оба чтения (баров и окна) случаются
    # ровно по разу.
    order = np.lexsort((kk, ksym[kk]))
    rows, cols, kk, kind = rows[order], cols[order], kk[order], kind[order]
    grp = ksym[kk]
    said = time.time()
    pos, done, total = 0, 0, len(rows)
    while pos < total:
        s_i = int(grp[pos])
        end = int(np.searchsorted(grp, s_i, side="right"))
        sym = syms[s_i]
        done += 1
        ats = [names[int(k)][2] for k in kk[pos:end]]
        bars = get(sym, min(ats) - T.BACK_H * 3600,
                   max(ats) + T.HOLD_H * 3600)
        ts = [b[0] for b in bars] if bars else []
        tiers = tiers_all.get(sym) or []

        def look(notl, _t=tiers):
            return L.mmr_for_notional(_t, notl, flat=T.FLAT_MMR)

        if not bars:
            acc["no_bars"] += end - pos
        else:
            q = pos
            while q < end:
                k = int(kk[q])
                qe = q
                while qe < end and int(kk[qe]) == k:
                    qe += 1
                _one_twin(k, q, qe, rows, cols, kind, names, setups, bars,
                          ts, look, mmr_from,
                          (R_M, X_M, R_P, X_P, R_2, X_2), acc)
                q = qe
        if time.time() - said > PROGRESS_S:
            log(f"  проход 2: символ {done}/{len(syms)}, измерено пар "
                f"{int(np.isfinite(R_M).sum())}, RSS {peak_rss_mb()} МБ")
            said = time.time()
        mem_stop(mem_lim, f"проход 2, символ {done}/{len(syms)}", log)
        state(tag, step="twins", sym_done=done, sym_all=len(syms),
              pairs=int(np.isfinite(R_M).sum()))
        pos = end
    log(f"проход 2: символов {len(syms)}, измеримых пар T1σ "
        f"{int(np.isfinite(R_M).sum())} из {n * d}; без баров "
        f"{acc['no_bars']}, без окна {acc['no_window']}")
    return dict(acc, R_M=R_M, X_M=X_M, R_P=R_P, X_P=X_P, R_2=R_2, X_2=X_2)


# ------------------------------------------------------------- сводки

CONC_KEYS = ("tot", "no_top3_days", "no_best_name")


def book_pick(picks, setups, ok):
    """Дневная форма руки S при ОДНОЙ кассе.

    Касса чужая и зовётся у хозяев (`run_place.day_form` → билет
    `dca_paper/rules.ticket` при $10 000 «оптимальной», одна позиция на
    имя `run_d6.one_per_name`, день ВЫХОДА `tournament.daily`, форма
    `factory/stability.stats`, колонки концентрации
    `run_place.concentration`). Своё здесь только то, что ВСЕ руки идут
    ОДНОЙ дорогой: вторая касса разошлась бы со страницей книг, и обе
    выглядели бы исправными.
    """
    recs = [{"at": float(picks[i]["at"]), "sym": picks[i]["sym"],
             "exit_ts": setups[i]["exit_ts"], "fwd": float(picks[i]["fwd"]),
             "pnl": setups[i]["pnl"]}
            for i in ok]
    return RP.day_form(recs)


def book_draws(picks, names, IDX, R, X, ok):
    """Дневная форма КАЖДОГО розыгрыша — той же кассой, что рука S.

    Имя книги двойника — имя ДВОЙНИКА (правило «одна позиция на имя»
    свойство того, чем торгуют), а момент решения и порядок раздачи —
    выбора: слот книга раздаёт по своему прогнозу, и менять порядок вместе
    с именем значило бы мерить заодно другую очередь.
    """
    st_d, day_d = [], []
    for j in range(IDX.shape[1]):
        recs = []
        for i in ok:
            k = int(IDX[i, j])
            if k < 0 or not np.isfinite(R[i, j]):
                continue
            recs.append({"at": float(picks[i]["at"]), "sym": names[k][0],
                         "exit_ts": float(X[i, j]),
                         "fwd": float(picks[i]["fwd"]),
                         "pnl": float(R[i, j])})
        s, dd = RP.day_form(recs)
        st_d.append(s)
        day_d.append(dd)
    return st_d, day_d


def conc_of(st):
    """Колонки концентрации книги: итог, без 3 лучших суток, без лучшего
    имени. Нет книги — прочерки, а не нули."""
    return {k: (st or {}).get(k) for k in CONC_KEYS}


def paired_days(day_a, day_b):
    """Парная разность по СУТКАМ: медиана и среднее рядом."""
    if not day_a or not day_b:
        return None
    keys = sorted(set(day_a) & set(day_b))
    if not keys:
        return None
    a = np.array([day_a[k] for k in keys], dtype=float)
    b = np.array([day_b[k] for k in keys], dtype=float)
    return T.paired(a, b)


def median_draw(R):
    """Номер МЕДИАННОГО розыгрыша по медиане исхода позиции.

    Пара считается с ним, а не со средним по ста книгам: среднего из ста
    книг не равен ни один розыгрыш, и разброс у него вдесятеро уже
    (тот же довод, что в `place.draw_pool`).
    """
    med = []
    for j in range(R.shape[1]):
        col = R[:, j]
        col = col[np.isfinite(col)]
        med.append(float(np.median(col)) if len(col) else np.nan)
    med = np.asarray(med)
    good = np.nonzero(np.isfinite(med))[0]
    if not len(good):
        return None
    target = float(np.median(med[good]))
    return int(good[int(np.argmin(np.abs(med[good] - target)))])


def measures(picks, setups, MT, PT, names, res, draws, seed, secs,
             skipped, diag, log=log_):
    ok = [i for i, s in enumerate(setups) if s is not None]
    n = len(ok)
    out = {"positions": n, "legs": len(picks), "skipped": skipped,
           "draws": int(draws), "seed": int(seed), "secs": round(secs, 1),
           "peak_rss_mb": peak_rss_mb(), "assign": diag,
           "mmr_from": T.MMR_FROM,
           "params": {"MIN_EDGE_BP": T.MIN_EDGE_BP, "MIN_RR": T.MIN_RR,
                      "BACK_H": T.BACK_H, "HOLD_H": T.HOLD_H,
                      "N_RUNGS": T.N_RUNGS, "MIN_ADD_GAP": T.MIN_ADD_GAP,
                      "SURVIVE_MULT": T.SURVIVE_MULT,
                      "FLOOR_FRAC": T.FLOOR_FRAC, "N_DEC": T.N_DEC,
                      "COVER_MIN": T.COVER_MIN, "NULL_Q": T.NULL_Q}}
    if not n:
        out["refused"] = (
            f"позиций ноль при {len(picks)} ногах под гейтом "
            f"(пропущено {skipped}) — баров либо геометрии нет; пустота "
            "результатом не является")
        return out
    if int(draws) < T.MIN_DRAWS:
        out["refused"] = (
            f"розыгрышей {draws}, а нуль не строится меньше чем на "
            f"{T.MIN_DRAWS}: полоса из горстки книг есть шум, а не нуль")
        return out

    S = np.array([setups[i]["pnl"] for i in ok], dtype=float)
    R_M = res["R_M"][ok, :]
    R_P = res["R_P"][ok, :]
    R_2 = res["R_2"][ok, :]

    pairs = int(R_M.shape[0] * R_M.shape[1])
    measured = int(np.isfinite(R_M).sum())
    cover = measured / pairs if pairs else 0.0
    out["cover"] = round(cover, 4)
    out["cover_pairs"] = pairs
    out["cover_measured"] = measured
    out["verdict_cover"] = T.verdict_cover(cover, pairs)
    if not measured:
        out["refused"] = ("измеримых пар «позиция × розыгрыш» ноль — "
                          "двойников не нашлось либо баров у них нет; "
                          "пустота результатом не является")
        return out

    # `draw_pool` — сводка сестринской механики, и берёт она список
    # списков: розыгрыш есть ЦЕЛАЯ книга, и считать его надо внутри
    # себя. Матрица разворачивается в списки на её входе, а не
    # переписывается вторая копия правила «выше 95-го процентиля».
    out["null_t1s"] = P.draw_pool(S, R_M.tolist())
    out["null_t1"] = P.draw_pool(S, R_P.tolist())
    out["null_t2"] = P.draw_pool(S, R_2.tolist())
    out["arm_S"] = P.cell_stats(S, lev=[setups[i]["lev"] for i in ok])
    out["exits_S"] = {}
    for i in ok:
        e = setups[i]["exit"]
        out["exits_S"][e] = out["exits_S"].get(e, 0) + 1
    out["liq_twin_m"] = res["liq_m"]
    out["liq_twin_p"] = res["liq_p"]
    out["t2_why"] = res["t2_why"]
    out["mmr_diff_share"] = (round(res["mmr_diff"] / res["mmr_seen"], 4)
                             if res["mmr_seen"] else None)

    # цена подбора волатильности: T1σ против T1 — диагностика, не вердикт
    a, b = out["null_t1s"], out["null_t1"]
    if a and b:
        out["sigma_price"] = round(a["draw_median_of_medians"]
                                   - b["draw_median_of_medians"], 5)

    # отдельный счёт выборов БЕЗ структурной лестницы: у них плечо 1× и
    # один рунг, и двойник получает ровно то же
    kk = np.array([setups[i]["k"] for i in ok], dtype=int)
    for name, m in (("ladder", kk >= 2), ("no_ladder", kk < 2)):
        if int(m.sum()):
            out[f"null_{name}"] = P.draw_pool(S[m], R_M[m, :].tolist())
            out[f"n_{name}"] = int(m.sum())
        else:
            out[f"n_{name}"] = 0

    st_s, day_s = book_pick(picks, setups, ok)
    st_d, day_d = book_draws(picks, names, MT, res["R_M"], res["X_M"], ok)
    out["book_S"] = st_s
    out["book_draws"] = int(sum(1 for s in st_d if s))
    out["form_nulls"] = T.form_nulls(st_s, st_d)
    c_s = conc_of(st_s)
    out["conc_S"] = c_s
    out["conc_nulls"] = T.conc_nulls(c_s, [conc_of(x) for x in st_d if x])
    # Колонки концентрации обязаны стоять у КАЖДОЙ руки, а не только у
    # ячейки вердикта: концентрация переворачивает знак (92.7 % итога
    # бумажных книг легло в трое суток), и рука без этой колонки
    # предъявляла бы эпизод как правило.
    for key, IDX, RR, XX in (("t1", PT, res["R_P"], res["X_P"]),
                             ("t2", MT, res["R_2"], res["X_2"])):
        sd, _dd = book_draws(picks, names, IDX, RR, XX, ok)
        out[f"conc_nulls_{key}"] = T.conc_nulls(
            c_s, [conc_of(x) for x in sd if x])
        out[f"book_draws_{key}"] = int(sum(1 for x in sd if x))

    jm = median_draw(R_M)
    out["median_draw"] = jm
    if jm is not None:
        out["pair_pos"] = T.paired(S, R_M[:, jm])
        out["pair_day"] = paired_days(day_s, day_d[jm])
        out["boot"] = (P.paired_day_boot(day_s, day_d[jm])
                       if day_s and day_d[jm] else None)
    else:
        out["pair_pos"] = out["pair_day"] = out["boot"] = None

    k1 = T.verdict_choice((out["null_t1s"] or {}).get("nulls"))
    k2 = T.verdict_pair(out["pair_pos"], out["pair_day"], out["boot"])
    k3 = T.verdict_form(out["form_nulls"])
    k4 = T.verdict_conc(out["conc_nulls"])
    out["killers"] = {"choice": k1, "pair": k2, "form": k3, "conc": k4}
    out["verdict"] = T.verdict(out["verdict_cover"], [k1, k2, k3, k4])
    return out


# ------------------------------------------------------------- прогон

def core(picks, pools, get, tiers_all, draws=T.DRAWS, seed=T.SEED,
         log=log_, tag="1m", use_cache=True, mmr_from=T.MMR_FROM,
         mem_lim=None):
    """Вся дорога от населения до вердикта. Калибровка идёт ЕЮ ЖЕ.

    Калибровка, идущая мимо проверяемого пути, проверяет не его — поэтому
    синтетика подставляется швами `picks`/`pools`/`get`/`tiers_all`, а
    считает её тот же код, что живые данные.
    """
    t0 = time.time()
    sig_need, pick_by = needs(picks, pools)
    log(f"проход 1 из 2: σ у {len(sig_need)} имён, выборов {len(picks)}")
    sig, setups, skipped, _reads = pass_one(picks, sig_need, pick_by, get,
                                            tiers_all, log=log, tag=tag,
                                            use_cache=use_cache,
                                            mem_lim=mem_lim)
    MT, PT, names, diag = assign(picks, pools, sig, setups, draws=draws,
                                 seed=seed, log=log)
    log(f"проход 2 из 2: двойники, розыгрышей {draws}, зерно {seed}")
    res = pass_two(setups, MT, PT, names, get, tiers_all, log=log,
                   tag=tag, mmr_from=mmr_from, mem_lim=mem_lim)
    return measures(picks, setups, MT, PT, names, res, draws, seed,
                    time.time() - t0, skipped, diag, log=log)


def run(limit=None, stride=1, draws=T.DRAWS, seed=T.SEED, src=None,
        log=log_, tag="1m", legs=None, use_cache=True,
        mmr_from=T.MMR_FROM):
    picks, pools = load(limit=limit, stride=stride, log=log, legs=legs)
    if not picks:
        return {"refused": "ног под гейтом ноль — журнал листов пуст либо "
                           "гейт не пропускает никого"}
    get = src.bars if src else (lambda s, x, y: SW.read_bars(D2.ROOT, s, x, y))
    tiers_all = (src.tiers if src is not None and hasattr(src, "tiers")
                 else D2.instruments_tiers())
    return core(picks, pools, get, tiers_all, draws=draws, seed=seed,
                log=log, tag=tag, use_cache=use_cache, mmr_from=mmr_from,
                mem_lim=mem_limit_mb(log=log))


# ------------------------------------------------------------ калибровка

class FakeSource:
    """Синтетический источник баров и тиров для калибровки и проверок."""

    def __init__(self, series, tiers=None):
        self.series = series
        self.tiers = tiers or {}

    def bars(self, sym, t0, t1):
        b = self.series.get(sym) or []
        return [x for x in b if t0 <= x[0] <= t1]


def synth(n_pool=28, n_hours=8, hold_n=6000, step_h=6, seed=T.SEED,
          planted=False, up=0.20):
    """Синтетический час: сечение имён, выборы книги и их бары.

    Подставной артефакт обязан выглядеть как живой: имена разной цены,
    дрожание, живые метки времени и живой масштаб — иначе фикстура прячет
    ошибку (восемь таких случаев в проекте).

    Имена выборов и имена сечения РАЗДЕЛЕНЫ: в живом прогоне пул часа не
    берёт гейтованных выборов, и если бы подсаженное имя попадало в
    кандидаты соседних часов, подделка протекала бы в двойников и
    калибровка занижала бы собственную чувствительность.

    `planted=True` — подсаженный ход: бары ВЫБОРА идут вверх до тейка в
    первый час, у кандидатов путь прежний; тогда рука S обязана бить
    двойников с большим запасом. `planted=False` — ОБМЕНИВАЕМОСТЬ: выбор
    нарисован тем же законом, что кандидаты, то есть он есть один из
    розыгрышей по построению, и превосходство здесь означало бы дефект
    машинерии, а не свойство рынка.
    """
    rng = np.random.default_rng(int(seed))
    t0 = 1_786_000_000
    t0 -= t0 % 3600
    # Решения разнесены по СУТКАМ, а не сложены в один час: дневная форма
    # и парный бутстрап по суткам — часть проверяемой дороги, и калибровка
    # на одном дне их бы не тронула вовсе.
    ats = [float(t0 + T.BACK_H * 3600 + h * int(step_h) * 3600)
           for h in range(n_hours)]
    pool_names = [f"SYN{i:03d}USDT" for i in range(n_pool)]
    pick_names = [f"PIK{h:03d}USDT" for h in range(n_hours)]
    series, planted_max = {}, {}
    # Шаг блуждания заведомо меньше расстояния до тейка (за всё окно
    # накапливается около 1 %, тейк стоит в 1.5–4 %): иначе кандидаты
    # доходят до тейка сами, обе руки упираются в один и тот же потолок
    # `take × плечо`, и подсаженный ход становится НЕВИДИМ — калибровка
    # «не нашла» бы его при исправном коде. Потолок исхода у лестницы с
    # тейком есть свойство конструкции, и его надо было увидеть заранее.
    for i, s in enumerate(pool_names + pick_names):
        px = T.walk(rng, hold_n, sigma=0.0004,
                    start=float(10.0 * (1.0 + 0.3 * i)))
        series[s] = T.bars_of(px, t0)
    picks, pools = [], {}
    for h, at in enumerate(ats):
        pools[(at, "syn")] = {
            "syms": list(pool_names),
            "fav": [float(rng.uniform(60.0, 300.0)) for _ in pool_names]}
        psym = pick_names[h]
        picks.append({"id": h, "arm": "syn", "sym": psym, "at": at,
                      "side": "long", "fwd": 60.0,
                      "fav": float(rng.uniform(150.0, 400.0)),
                      "adv_q": -80.0, "rr": 3.0, "beta": 1.0,
                      "px": float(series[psym][0][4])})
        if planted:
            b = series[psym]
            i_at = next((k for k, x in enumerate(b) if x[0] >= at), None)
            if i_at is not None:
                px = T.lift_to_take([x[4] for x in b], i_at, up=up)
                series[psym] = T.bars_of(px, t0)
                planted_max[psym] = max(px[i_at:]) / px[i_at] - 1.0
    return picks, pools, FakeSource(series), planted_max


def calibrate(draws=30, seed=T.SEED, log=log_, up=0.20):
    """Калибровочная пара: найти подсаженное и промолчать на шуме.

    Половина 1 — подсаженный ход у ВЫБОРА: рука S обязана бить двойников
    и по медиане, и по среднему. Половина 2 — обмениваемость: выбор
    нарисован тем же законом, что кандидаты, значит он есть один из
    розыгрышей, и превосходство здесь означало бы дефект самой машинерии
    (сбитая пара, чужое плечо, выравнивание не по той позиции), а не
    свойство рынка. Без второй половины сломанное чтение баров двойника
    (пустое окно → прочерк → книга из двух позиций) неотличимо от
    «выбор работает».
    """
    out = {}
    for half, pl in (("planted", True), ("noise", False)):
        picks, pools, src, pmax = synth(planted=pl, seed=seed, up=up)
        if pl:
            # Легла ли подделка — ЧИСЛО, а не вера: без этой проверки
            # калибровка «нашла подсаженное» на неподсаженных барах.
            out["planted_move"] = (round(float(min(pmax.values())), 4)
                                   if pmax else None)
            if not pmax or min(pmax.values()) < up * 0.5:
                out["planted_laid"] = False
            else:
                out["planted_laid"] = True
        s = core(picks, pools, src.bars, src.tiers, draws=draws, seed=seed,
                 log=log, tag="cal", use_cache=False)
        out[half] = s
    a = ((out.get("planted") or {}).get("null_t1s") or {}).get("nulls")
    b = ((out.get("noise") or {}).get("null_t1s") or {}).get("nulls")
    out["found"] = bool(a and T.beats_both(a))
    out["quiet"] = bool(b is not None and not T.beats_both(b))
    out["ok"] = bool(out["found"] and out["quiet"]
                     and out.get("planted_laid"))
    return out


# --------------------------------------------------------------- отчёт

def _pct(v, nd=2):
    return "—" if v is None or v != v else f"{float(v) * 100:+.{nd}f} %"


def _num(v, nd=2):
    return "—" if v is None or v != v else f"{float(v):.{nd}f}"


def _money(v):
    return "—" if v is None or v != v else f"{float(v):+,.2f} $"


def _null_row(name, nl):
    if not nl:
        return f"| {name} | — | — | — | — | — |"
    return (f"| {name} | {_pct(nl['real'], 3)} | {_pct(nl['edge'], 3)} | "
            f"{_pct(nl['mean'], 3)} | {_num(nl['sigmas'], 1)} | "
            f"{'да' if nl['beats'] else 'нет'} |")


def report(s, tag="1m"):
    P_ = []
    P_.append("# Механика a82dcf58 — чьи это деньги: выбор модели или час "
              "рынка\n")
    P_.append("DCA-лестница на СЛУЧАЙНОМ ИМЕНИ того же часа как "
              "одновременная кросс-секция. Переставляется ИМЯ; уровни, "
              "тейк, веса и плечо у двойника те же (перестановка меток A4 "
              "на лестнице). Ячейка вердикта — двойник, подобранный по "
              "децилю суточной σ (T1σ).\n")
    if s.get("refused"):
        P_.append(f"**ОТКАЗ.** {s['refused']}\n")
        return "\n".join(P_) + "\n"
    p = s["params"]
    P_.append(f"Позиций {s['positions']} из {s['legs']} ног под гейтом "
              f"(край ≥ {p['MIN_EDGE_BP']} б.п., RR ≥ {p['MIN_RR']}), "
              f"пропущено {s['skipped']}; розыгрышей {s['draws']}, зерно "
              f"{s['seed']}; прогон {s['secs']} с, пик памяти "
              f"{s['peak_rss_mb']} МБ.\n")
    vc = s["verdict_cover"]
    P_.append(f"**Измеримость.** {vc['why'][0]}\n")
    P_.append(f"\n## Вердикт\n\n**{s['verdict']['head']}**\n")
    for w in s["verdict"]["why"]:
        P_.append(f"- {w}")
    P_.append("")

    P_.append("\n## Рука S против книг-двойников (доля капитала позиции)\n")
    P_.append(f"Каждый розыгрыш — ЦЕЛАЯ книга: медиана и среднее считаются "
              f"внутри розыгрыша по всем позициям, и только потом "
              f"сравниваются с S. Край — {p['NULL_Q']:.0f}-й процентиль "
              f"розыгрышей.\n")
    P_.append("| величина | рука S | край розыгрышей | среднее розыгрышей | "
              "σ от среднего | S выше края |")
    P_.append("|---|--:|--:|--:|--:|:--:|")
    nl = (s.get("null_t1s") or {}).get("nulls") or {}
    P_.append(_null_row("медиана позиции", nl.get("median")))
    P_.append(_null_row("среднее позиции", nl.get("mean")))
    bt = nl.get("bite")
    P_.append(f"| укус (меньше — лучше) | {_num((bt or {}).get('real'), 1)} | "
              f"{_num((bt or {}).get('edge'), 1)} | "
              f"{_num((bt or {}).get('mean'), 1)} | "
              f"{_num((bt or {}).get('sigmas'), 1)} | "
              f"{'да' if bt and bt['beats'] else 'нет'} |")
    a = s["arm_S"]
    P_.append(f"\nРука S: позиций {a['n']}, медиана {_pct(a['median'])}, "
              f"среднее {_pct(a['mean'])}, зелёных "
              f"{a['green'] * 100:.1f} %, худшая {_pct(a['worst'], 1)}, "
              f"укус {_num(a['bite'], 1)}, медианное плечо "
              f"{_num(a.get('median_lev'), 2)}×, доля 1× "
              f"{_num(a.get('frac_1x'), 3)}.")
    P_.append(f"Исходы S: {s['exits_S']}. Ликвидаций у двойников T1σ "
              f"{s['liq_twin_m']}, у T1 {s['liq_twin_p']}.\n")

    P_.append("\n## Четыре убийцы, в порядке дешевизны\n")
    for key, ttl in (("choice", "1. Имя выбора против имён того же часа"),
                     ("pair", "2. Парная разность S − T"),
                     ("form", "3. Дневная форма при одной кассе"),
                     ("conc", "4. Без трёх лучших суток")):
        k = s["killers"][key]
        mark = {True: "СРАБОТАЛ", False: "не сработал",
                None: "НЕ ПОСЧИТАН"}[k.get("killed")]
        P_.append(f"\n### {ttl} — {mark}\n")
        for x in k.get("parts") or []:
            P_.append(f"- {x}")
        for w in k.get("why") or []:
            P_.append(f"\n{w}")

    bk = s.get("book_S") or {}
    P_.append(f"\n\n## Дневная форма (одна касса: депозит "
              f"{_num(bk.get('capital'), 0)} $, билет "
              f"{_num(bk.get('ticket'), 0)} $, одна позиция на имя)\n")
    b = s.get("book_S") or {}
    if b:
        P_.append(f"Рука S: суток {b.get('days')}, зелёных "
                  f"{_num((b.get('green') or 0) * 100, 1)} %, медиана дня "
                  f"{_money(b.get('med'))}, среднее дня "
                  f"{_money(b.get('mean_day'))}, худший день "
                  f"{_money(b.get('worst'))}, укус {_num(b.get('bite'), 1)}, "
                  f"просадка {_money(b.get('dd'))}, итог "
                  f"{_money(b.get('tot'))}; взято {b.get('taken')} из "
                  f"{b.get('offered')} (одно имя разом: пропущено "
                  f"{b.get('skipped_same_name')}). Книг-двойников с формой "
                  f"{s.get('book_draws')}.")
    c = s.get("conc_S") or {}
    P_.append(f"\nКонцентрация руки S: итог {_money(c.get('tot'))}, без 3 "
              f"лучших суток {_money(c.get('no_top3_days'))}, без лучшего "
              f"имени {_money(c.get('no_best_name'))}.\n")

    P_.append("\n## Диагностика (вердикта не выносит)\n")
    for key, ttl in (("null_t1", "T1 — двойник БЕЗ подбора σ"),
                     ("null_t2", "T2 — тот же двойник со СВОЕЙ геометрией")):
        d = s.get(key) or {}
        nn = (d.get("nulls") or {}).get("median")
        mm = (d.get("nulls") or {}).get("mean")
        P_.append(f"- **{ttl}:** медиана розыгрышей "
                  f"{_pct(d.get('draw_median_of_medians'), 3)}, среднее "
                  f"{_pct(d.get('draw_median_of_means'), 3)}; S выше края "
                  f"по медиане "
                  f"{'да' if nn and nn['beats'] else 'нет'}, по среднему "
                  f"{'да' if mm and mm['beats'] else 'нет'}")
    # Колонки концентрации — у КАЖДОЙ руки, не только у ячейки вердикта
    for key, ttl in (("conc_nulls", "T1σ (вердикт)"), ("conc_nulls_t1", "T1"),
                     ("conc_nulls_t2", "T2")):
        nl = (s.get(key) or {}).get("no_top3_days")
        nb = (s.get(key) or {}).get("no_best_name")
        if not nl:
            P_.append(f"- концентрация против книг {ttl}: не посчитана")
            continue
        P_.append(f"- **концентрация против книг {ttl}:** S без 3 лучших "
                  f"суток {_money(nl['real'])} против края "
                  f"{_money(nl['edge'])} "
                  f"({'выше' if nl['beats'] else 'не выше'}); без лучшего "
                  f"имени {_money((nb or {}).get('real'))} против "
                  f"{_money((nb or {}).get('edge'))} "
                  f"({'выше' if nb and nb['beats'] else 'не выше'})")
    if s.get("sigma_price") is not None:
        P_.append(f"- **Цена подбора волатильности (T1σ − T1):** "
                  f"{_pct(s['sigma_price'], 3)} по медиане книг-двойников")
    if s.get("t2_why"):
        P_.append(f"- T2 не построилась у: {s['t2_why']} (прочерк с "
                  f"причиной, не ноль)")
    P_.append(f"- Выборов со структурной лестницей {s.get('n_ladder')}, без "
              f"неё {s.get('n_no_ladder')} (у последних плечо 1× и один "
              f"рунг, двойник получает ровно то же)")
    for key, ttl in (("null_ladder", "со структурной лестницей"),
                     ("null_no_ladder", "без структурной лестницы")):
        d = s.get(key)
        if not d:
            continue
        nn = (d.get("nulls") or {}).get("median")
        mm = (d.get("nulls") or {}).get("mean")
        P_.append(f"  - {ttl} ({d['n']}): S по медиане "
                  f"{_pct((nn or {}).get('real'), 3)} против края "
                  f"{_pct((nn or {}).get('edge'), 3)} "
                  f"({'выше' if nn and nn['beats'] else 'не выше'}); по "
                  f"среднему {_pct((mm or {}).get('real'), 3)} против "
                  f"{_pct((mm or {}).get('edge'), 3)} "
                  f"({'выше' if mm and mm['beats'] else 'не выше'})")
    P_.append(f"- Тир двойника: MMR пересаживается от ВЫБОРА "
              f"(`MMR_FROM={s['mmr_from']}`); своя ставка тира отличалась бы "
              f"у {_num((s.get('mmr_diff_share') or 0) * 100, 1)} % пар — "
              f"ключ `--mmr own` считает тем же кодом")
    P_.append(f"- Подбор: часов без дециля σ {s['assign'].get('no_decile')}, "
              f"часов без сечения {s['assign'].get('no_pool')}; "
              f"медианный розыгрыш № {s.get('median_draw')}")

    P_.append("\n\n**Оговорки, названные до прогона.** Веса модели видели "
              "эти часы — оценка сверху для руки S во всех D-прогонах; если "
              "S не бьёт двойников даже на виденной записи, вывод только "
              "крепче. Издержки круга на ногу здесь не сняты (как в D2): "
              "они одинаковы у S и у двойника по построению и пару не "
              "двигают. Двойник входит в ТОТ ЖЕ момент и держится тот же "
              "срок. Убийца 2 требует согласия знаков И по позициям, И по "
              "суткам — это строже, чем одна строка заявки, и названо "
              "здесь, а не спрятано. T2 считается только у имён с длинным "
              "обещанием той же строки листа; доля непостроенных названа "
              "выше числом.\n")
    P_.append("\n**Что меняет исход.** Убита — бумажный трек DCA-книг с "
              "8 августа есть «лонг альтов при 2–3× в месяц роста», и "
              "решение о фазе C для них не имеет основания, пока двойник "
              "не побит. Жива — первое число проекта, где выбор модели "
              "бьёт свою кросс-секцию ПОСЛЕ лестницы.\n")
    return "\n".join(P_) + "\n"


def cal_report(c):
    P_ = ["# Механика a82dcf58 — калибровочная пара\n",
          "Подсаженный ход у выбора обязан найтись; на обмениваемой "
          "синтетике (выбор нарисован тем же законом, что кандидаты) "
          "механика обязана промолчать. Обе половины считаются ТОЙ ЖЕ "
          "дорогой, что боевой прогон (`core`).\n"]
    P_.append(f"- подделка легла (ход выбора после входа): "
              f"{_pct(c.get('planted_move'), 1)} — "
              f"{'да' if c.get('planted_laid') else 'НЕТ'}")
    for half, ttl in (("planted", "подсаженное"), ("noise", "шум")):
        s = c.get(half) or {}
        nl = (s.get("null_t1s") or {}).get("nulls") or {}
        md, mn = nl.get("median"), nl.get("mean")
        P_.append(f"- **{ttl}:** позиций {s.get('positions')}, покрытие "
                  f"{_num((s.get('cover') or 0) * 100, 1)} %; S по медиане "
                  f"{_pct((md or {}).get('real'), 3)} против края "
                  f"{_pct((md or {}).get('edge'), 3)} "
                  f"({'выше' if md and md['beats'] else 'не выше'}), по "
                  f"среднему {_pct((mn or {}).get('real'), 3)} против "
                  f"{_pct((mn or {}).get('edge'), 3)} "
                  f"({'выше' if mn and mn['beats'] else 'не выше'})")
    P_.append(f"\n**Итог калибровки:** нашла подсаженное — "
              f"{'да' if c.get('found') else 'НЕТ'}; промолчала на шуме — "
              f"{'да' if c.get('quiet') else 'НЕТ'}; годна — "
              f"{'да' if c.get('ok') else 'НЕТ'}.\n")
    return "\n".join(P_) + "\n"


def publish(name):
    subprocess.run(["tools/publish.sh", f"job: {name}"], cwd=ROOT,
                   check=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--draws", type=int, default=T.DRAWS)
    ap.add_argument("--seed", type=int, default=T.SEED)
    ap.add_argument("--mmr", choices=("pick", "own"), default=T.MMR_FROM)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-mem-guard", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)     # каталог артефактов — ДО счёта
    tag = "cal" if a.calibrate else ("smoke" if (a.limit or a.stride > 1)
                                     else "1m")
    if a.calibrate:
        c = calibrate(draws=max(a.draws, T.MIN_DRAWS), seed=a.seed)
        with open(os.path.join(OUT, "TWIN-calibration.json"), "w",
                  encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1, default=str)
        rep = cal_report(c)
        with open(os.path.join(OUT, "TWIN-calibration.md"), "w",
                  encoding="utf-8") as f:
            f.write(rep)
        sys.stderr.write("\n" + rep)
        if not a.no_publish:
            publish("twin-calibration")
        return 0 if c.get("ok") else 2
    if not a.no_mem_guard and not mem_guard():
        return 3
    s = run(limit=a.limit, stride=a.stride, draws=a.draws, seed=a.seed,
            tag=tag, use_cache=not a.no_cache, mmr_from=a.mmr)
    with open(os.path.join(OUT, f"TWIN-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, default=str)
    rep = report(s, tag)
    with open(os.path.join(OUT, f"TWIN-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)
    if not a.no_publish:
        publish(f"twin-{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
