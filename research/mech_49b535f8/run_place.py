#!/usr/bin/env python3
"""
Механика 49b535f8 — ГДЕ усреднять: структурные уровни T4 против
случайных уровней той же глубины (нуль §8.6 спеки 14) и против σ-сетки.

Что сравнивается и почему парно
-------------------------------

Позиции — гейтованные лонги журнала листов (`run_d2.SHEETS`, край ≥ 33
б.п., RR ≥ 2): те же выборы модели, что у D2/D3, и ни один из них
механика не выбирает сама. Общими у всех рук держатся вход (открытие
первого бара после решения), тейк (mfe модели от входа), пол
капитуляции 0.10, срок 72 ч, забор §5 (`SURVIVE_MULT` 2.0, тиры D0) и
равные веса. Меняются ТОЛЬКО цены рунгов — правило размещения:

* **S** — структурные уровни T4 (правило живых бумажных книг);
* **R** — нуль §8.6: ≥ 100 случайных лестниц той же глубины и формы,
  плечо S. Зерно числом, розыгрыши назначены парой (зерно, номер ноги)
  и от порядка обработки не зависят;
* **G** — σ-сетка своей глубины и своего §5-плеча (вопрос о КАРКАСЕ);
* **G′** — тот же каркас на глубине S при плече S (вопрос о МЕСТЕ при
  том же плече). Без G′ разность S − G мешала бы место с рычагом, а D3
  намерил, что рычаг и есть источник и дохода, и хвоста.

Правило вердикта не моё: §9 спеки 14 — «структурные уровни выше 95-го
процентиля случайных по нетто И по укусу». Все три убийцы объявлены
заданием до прогона и собраны в `place.verdict_*` из чисел, а не
написаны рядом с ними.

Что здесь названо честно и не спрятано
--------------------------------------

1. **Розыгрыш вырождается при двух рунгах.** Нижний рунг закреплён на
   глубине структурной лестницы, промежуточных мест при двух рунгах
   нет — значит R ТОЖДЕСТВЕННА S, и такая пара даёт ровно ноль. Это не
   «место не важно», это «выбирать было не из чего». Такие позиции
   считаются числом и в парное сравнение (1) не входят — по тому же
   правилу задания, по которому в него не входят позиции без лестницы
   вовсе. Их включение подарило бы нулю ожидаемый вердикт даром.
   Обе величины печатаются: и по кусающемуся населению (рунгов ≥ 3), и
   по всему, у кого лестница есть.
2. **Структурное правило берёт БЛИЖАЙШИЕ уровни первыми**, а розыгрыш
   равномерен по допустимому множеству — рунги S систематически выше
   равномерных. Часть любой разности S − R есть эта геометрия, а не
   «структурность» уровней; величина сдвига измерена калибровкой на
   чистом блуждании и напечатана.
3. **Предел плеча тира площадки не применяется** — как у D2/D3,
   прогнанных до правки ядра 2026-09-05. Правило одно у всех рук,
   поэтому пара честна; доля позиций сверх предела печатается по каждой
   руке отдельно.
4. **Пол σ берётся из сечения СУТОК** (10-й процентиль, как в
   `run_dca.py`). Внутри суток это лёгкое заглядывание вперёд по
   вспомогательной величине: пол задаёт только каркас G и на руки S, R,
   G′ не влияет ни одним числом.
5. Веса модели видели эти часы (наследство D2 — оценка сверху);
   издержки круга не сняты, всё брутто.

Запуск (VPS — журнал листов и бары только там):

    setsid nohup nice -n 19 .venv/bin/python \\
        research/mech_49b535f8/run_place.py \\
        > research/mech_49b535f8/out/run.log 2>&1 &

Смоук: `--limit 400 --draws 20 --tag smoke` — проверка ДОРОГИ, а не
рынка: население журнала лежит в трёх сутках (83 % ног), и «первые N»
описывают тихую неделю. Представительный, но более дорогой срез —
`--stride` (см. RUNBOOK). Отчёт называет себя смоуком сам. Публикует его
тоже сам прогон; `--no-publish` выключает.
"""

import argparse
import atexit
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time

# СВОЙ КАТАЛОГ БАЙТКОДА НА ПРОГОН, и это не гигиена. Питон считает `.pyc`
# свежим по паре «mtime исходника в целых секундах, размер», а деплой у
# нас — `git pull` и следующий такт: правка, уложившаяся в ту же секунду
# при неизменной длине, оставляет ПРЕЖНИЙ байткод, и прогон считает
# старым кодом, ничем себя не выдавая (`factory/pycguard.py` — как это
# однажды стоило целого захода строителя). Ставится ДО ввоза своих
# модулей: прежде ввезённое от этого не меняется. Чужой выбор
# (`PYTHONPYCACHEPREFIX` машины контролей) уважается.
if not os.environ.get("PYTHONPYCACHEPREFIX"):
    _pyc = tempfile.mkdtemp(prefix="pyc-place-")
    sys.pycache_prefix = _pyc
    atexit.register(shutil.rmtree, _pyc, True)

import numpy as np                                           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
ROOT = os.path.dirname(RESEARCH)
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(HERE, ".cache_sigma")

for _p in (HERE, os.path.join(RESEARCH, "dca_ladder"),
           os.path.join(RESEARCH, "dca_paper"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "s10_policy"),
           os.path.join(RESEARCH, "s8_loop"),
           os.path.join(RESEARCH, "s9_sweep"),
           os.path.join(RESEARCH, "t4_structure")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ladder as L                                           # noqa: E402
import place as P                                            # noqa: E402
import run_d2 as D2                                          # noqa: E402
import run_d3 as D3                                          # noqa: E402
import run_d6 as D6                                          # noqa: E402
import rules as RB                                           # noqa: E402
import stability as ST                                       # noqa: E402
import sweep as SW                                           # noqa: E402
import tournament as TNT                                     # noqa: E402

# --- касса дневной формы: ЧУЖИЕ величины у своих хозяев -------------------
BOOK_CAP = RB.DEPOSITS[1]                  # $10 000 — средний депозит книг
BOOK_RULER = "optimal"                     # режим, чей билет берём
ARMS = ("S", "G", "GP", "R")
ARM_NAMES = {"S": "S структурные уровни", "G": "G σ-сетка (своя глубина)",
             "GP": "G′ σ-каркас на глубине S", "R": "R медианный розыгрыш"}

CLUSTER_H = 24                             # окно склейки чтений в σ-проходе
SIG_CACHE_V = 1                            # версия меры σ (ключ кэша)
MEM_NEED_MB = 1300                         # состав: журнал листов ~880 МБ
MEM_SHARE = 0.85
PROGRESS_S = 30                            # молчать дольше нельзя


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
    """Отказаться ГРОМКО, если прогон не влезает рядом со сбором.

    Запись стакана — единственное невосстановимое в проекте, и прогон,
    уронивший сборщик по памяти, стоит суток записи, которых неоткуда
    взять (2026-09-06: D10 в 2.1 ГБ убил часовой цикл ядром). Нужное
    считается СОСТАВОМ и печатается числом рядом с доступным, а не
    выясняется после падения.
    """
    have = mem_available_mb()
    if have is None:
        log("память машины не прочиталась — иду, но осторожно")
        return True
    log(f"память: нужно ~{need_mb} МБ, доступно {have} МБ "
        f"(порог {share:.0%})")
    if need_mb > have * share:
        log("ОТКАЗ: прогон не влезает рядом со сбором. Дождаться "
            "свободной памяти либо сузить население ключом --limit.")
        return False
    return True


def state(tag, **kw):
    """Состояние прогона файлом: молчащий прогон неотличим от повисшего."""
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, f"state-{tag}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(dict(kw, at=round(time.time(), 1),
                           rss_mb=peak_rss_mb()), f, ensure_ascii=False)
    except OSError:
        pass


# ------------------------------------------------------------ население

def load_legs(limit=None, log=log_, stride=1):
    """Гейтованные ЛОНГИ журнала листов — тем же гейтом, что D2/D3.

    Состав обязан совпадать с опубликованным D2 бит в бит: разойдись он,
    и таблицы сравнивались бы с числами другой книги, обе выглядя
    исправными.

    `stride` — прореживание для СМОУКА, и оно не роскошь: население
    журнала лежит в трёх сутках (20–22 августа — 83 % ног), поэтому
    «первые N» описывают неделю тишины, а не то, что считает боевой
    прогон. Умолчание 1 — полное население, ничего не прорежено.
    """
    legs = TNT.legs_from_sheets([D2.SHEETS], log=log)
    longs = [g for g in legs if g["side"] == "long"
             and abs(g["fwd"]) >= D2.MIN_EDGE_BP
             and (g["rr"] or 0) >= D2.MIN_RR]
    del legs
    log(f"лонгов под гейтом книги (край ≥ {D2.MIN_EDGE_BP}, "
        f"RR ≥ {D2.MIN_RR}) {len(longs)}")
    if stride and stride > 1:
        longs = longs[::int(stride)]
        log(f"прорежено шагом {stride}: осталось {len(longs)}")
    if limit:
        longs = longs[:limit]
        log(f"лимит: взято {len(longs)}")
    return longs


def by_symbol(longs):
    out = {}
    for i, g in enumerate(longs):
        out.setdefault(g["sym"], []).append(i)
    return out


# ------------------------------------------------------- σ: проход первый

def _cache_path(sym):
    return os.path.join(CACHE, f"{sym}.json")


def cache_read(sym):
    try:
        with open(_cache_path(sym), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if d.get("v") != SIG_CACHE_V or d.get("back_h") != D2.BACK_H:
        return {}                       # мера другая — кэш не годится
    return d.get("sig") or {}


def cache_write(sym, sig):
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(_cache_path(sym), "w", encoding="utf-8") as f:
            json.dump({"v": SIG_CACHE_V, "back_h": D2.BACK_H, "sig": sig},
                      f)
    except OSError:
        pass


def clusters(ats, span_h=CLUSTER_H):
    """Разбить моменты решений на группы под ОДНО чтение окна назад.

    Окно σ — 24 ч до решения, и читать его на каждую ногу отдельно
    значит перечитывать одни и те же часы у имени, по которому книга
    приняла двадцать решений подряд. Группа читается одним куском.
    """
    out, cur = [], []
    for t in sorted(ats):
        if cur and t - cur[0] > span_h * 3600:
            out.append(cur)
            cur = []
        cur.append(t)
    if cur:
        out.append(cur)
    return out


def sigma_pass(longs, src=None, log=log_, tag="1m"):
    """σ каждой позиции ДО входа. Нужна одному — полу сечения.

    Проход отдельный и узкий: пол §S1 берётся из сечения СУТОК, то есть
    известен только после того, как σ измерена у всех позиций дня, а
    боевой проход идёт по символам. Читается ровно окно назад, чтения
    склеиваются группами, результат кладётся в кэш на символ — повторный
    прогон σ не пересчитывает.

    Возвращает список, ВЫРОВНЕННЫЙ по `longs` (nan — не измерена).
    """
    get = src.bars if src else (lambda s, x, y: SW.read_bars(D2.ROOT, s, x, y))
    sig = [float("nan")] * len(longs)
    bysym = by_symbol(longs)
    said = time.time()
    done = hits = reads = 0
    for sym, idxs in bysym.items():
        done += 1
        cached = cache_read(sym)
        need = [i for i in idxs if str(int(longs[i]["at"])) not in cached]
        fresh = {}
        if need:
            ats = sorted({float(longs[i]["at"]) for i in need})
            for grp in clusters(ats):
                a0 = grp[0] - D2.BACK_H * 3600
                b1 = grp[-1] + 3600
                bars = get(sym, a0, b1)
                reads += 1
                if not bars:
                    continue
                ts = [b[0] for b in bars]
                for i in need:
                    at = float(longs[i]["at"])
                    if not (grp[0] <= at <= grp[-1]):
                        continue
                    rs = D2.split_window(bars, ts, at, D2.BACK_H, 1)
                    if rs is None:
                        continue
                    win, now_i = rs
                    s_bp, _rng, _turn = D3.window_stats(win, now_i)
                    if s_bp == s_bp:
                        fresh[str(int(at))] = float(s_bp)
            if fresh:
                cached = dict(cached, **fresh)
                cache_write(sym, cached)
        for i in idxs:
            v = cached.get(str(int(longs[i]["at"])))
            if v is not None:
                sig[i] = float(v)
                hits += 1
        if time.time() - said > PROGRESS_S:
            log(f"  σ: символ {done}/{len(bysym)}, измерено {hits}, "
                f"чтений {reads}, RSS {peak_rss_mb()} МБ")
            state(tag, step="sigma", sym_done=done, sym_all=len(bysym),
                  measured=hits)
            said = time.time()
    log(f"σ измерена у {hits} из {len(longs)} ног ({reads} чтений)")
    return sig


def day_of(at):
    return time.strftime("%Y-%m-%d", time.gmtime(float(at)))


def floors_by_day(longs, sig_bp):
    """Пол σ на каждые сутки — из сечения ЭТИХ суток (урок S1).

    То же правило, что в `run_dca.py`: `SIG_FLOOR_Q`-квантиль сечения, но
    не ниже абсолютного пола. Суток с тонким сечением пол абсолютный —
    и это «сечения не набралось», а не «пола нет».
    """
    per = {}
    for g, s in zip(longs, sig_bp):
        if s == s:
            per.setdefault(day_of(g["at"]), []).append(P.sigma_day_of(s))
    return {d: P.sigma_floor(v) for d, v in per.items()}


# ------------------------------------------------------- боевой проход

def setup(g, bars, ts):
    """Разбор ноги до забора: окно, вход, тейк, уровни, структурные рунги.

    Гейты и функции — те же, что у D2 (`split_window`, `build_levels`,
    `structural_rungs`), и зовутся у него: состав позиций обязан
    совпадать с опубликованным. Возвращает словарь либо None.
    """
    rs = D2.split_window(bars, ts, g["at"], D2.BACK_H, D2.HOLD_H)
    if rs is None:
        return None
    win, now_i = rs
    hold = win[now_i:]
    entry = float(hold[0][1])
    if entry <= 0:
        return None
    take_px = entry * (1 + g["fav"] / 1e4)
    stop_px = entry * (1 + g["adv_q"] / 1e4)
    if not (take_px > entry and 0 < stop_px < entry):
        return None
    lv = D2.build_levels(win, now_i)
    rungs = D2.structural_rungs(entry, list(lv), D2.MIN_ADD_GAP, D2.N_RUNGS)
    s_bp, _rng, _turn = D3.window_stats(win, now_i)
    return {"hold": hold, "entry": entry, "take_px": take_px,
            "rungs": rungs, "sigma_bp": s_bp, "n_levels": int(len(lv))}


def run(limit=None, draws=P.DRAWS, seed=P.SEED, src=None, log=log_,
        tag="1m", legs=None, stride=1):
    """Полный проход. `legs`/`src` подставляются ТОЛЬКО проверками.

    Шов ради проверок, а не ради удобства: журнал листов весит 260 МБ и
    читается одиннадцать секунд, и сюита, читающая его, не запускалась бы
    вовсе — то есть дорога от ног до вердикта осталась бы непроверенной.
    Умолчание — живые данные.
    """
    t_run = time.time()
    longs = (list(legs) if legs is not None
             else load_legs(limit, log, stride=stride))
    if legs is not None and limit:
        longs = longs[:limit]
    if not longs:
        return {"refused": "ног под гейтом ноль — журнал листов пуст либо "
                           "гейт не пропускает никого"}
    tiers_all = D2.instruments_tiers()
    log("проход 1 из 2: σ до входа (для пола сечения)")
    sig_bp = sigma_pass(longs, src=src, log=log, tag=tag)
    floors = floors_by_day(longs, sig_bp)
    log(f"суток с сечением σ {len(floors)}")

    get = src.bars if src else (lambda s, x, y: SW.read_bars(D2.ROOT, s, x, y))
    bysym = by_symbol(longs)
    log(f"проход 2 из 2: реплей рук, символов {len(bysym)}, "
        f"розыгрышей {draws}, зерно {seed}")

    acc = {a: {"pnl": [], "liq": 0, "exits": {}, "lev": [], "over": [],
               "recs": []} for a in ("S", "G", "GP")}
    r_pnl, r_exit, r_liq = [], [], []   # (позиций × розыгрышей)
    keep = []                         # ноги, ставшие позициями
    k_hist, no_ladder, degen, thin_gap, draw_failed = [], 0, 0, 0, 0
    g_why, sig_day_hist = {}, []
    sig_mismatch = sig_missing = 0
    skipped = 0
    said = time.time()
    done = 0
    for sym, idxs in bysym.items():
        done += 1
        if time.time() - said > PROGRESS_S:
            log(f"  символ {done}/{len(bysym)}, позиций {len(keep)}, "
                f"RSS {peak_rss_mb()} МБ")
            state(tag, step="replay", sym_done=done, sym_all=len(bysym),
                  positions=len(keep))
            said = time.time()
        a0 = min(float(longs[i]["at"]) for i in idxs) - D2.BACK_H * 3600
        b1 = max(float(longs[i]["at"]) for i in idxs) + D2.HOLD_H * 3600
        bars = get(sym, a0, b1)
        if not bars:
            skipped += len(idxs)
            continue
        ts = [b[0] for b in bars]
        tiers = tiers_all.get(sym) or []

        def look(notl, _t=tiers):
            return L.mmr_for_notional(_t, notl, flat=D2.FLAT_MMR)

        for i in idxs:
            g = longs[i]
            s = setup(g, bars, ts)
            if s is None:
                skipped += 1
                continue
            # σ узкого прохода и σ широкого окна обязаны совпасть БИТ В
            # БИТ: узкое окно есть префикс широкого, и расхождение
            # означало бы, что пол сечения посчитан не по той мере,
            # которой считается сама сетка. Считается числом, а не верой.
            if sig_bp[i] == sig_bp[i] and s["sigma_bp"] == s["sigma_bp"]:
                if float(sig_bp[i]) != float(s["sigma_bp"]):
                    sig_mismatch += 1
            elif s["sigma_bp"] != s["sigma_bp"]:
                sig_missing += 1
            floor = floors.get(day_of(g["at"]), P.ABS_SIG_FLOOR)
            sd = P.sigma_day_of(s["sigma_bp"])
            sig_day = None if sd is None else max(sd, floor)
            arms = P.position_arms(s["hold"], s["entry"], s["rungs"],
                                   s["take_px"], look, sig_day,
                                   n_draws=draws, leg_id=int(g["id"]),
                                   seed=seed, tiers=tiers)
            keep.append(i)
            if arms.get("g_why"):
                g_why[arms["g_why"]] = g_why.get(arms["g_why"], 0) + 1
            sig_day_hist.append(sig_day)
            k_hist.append(arms["k"])
            no_ladder += int(arms["no_ladder"])
            degen += int(arms["degenerate"] and not arms["no_ladder"])
            thin_gap += int(bool(arms.get("gp_thin_gap")))
            draw_failed += int(arms.get("draw_failed") or 0)
            for a in ("S", "G", "GP"):
                res = arms[a]
                if res is None:                  # σ не измерена — прочерк
                    acc[a]["pnl"].append(float("nan"))
                    acc[a]["lev"].append(float("nan"))
                    acc[a]["over"].append(None)
                    continue
                acc[a]["pnl"].append(res["pnl_frac"])
                acc[a]["liq"] += int(res.get("exit") == "ликвидация")
                acc[a]["exits"][res.get("exit")] = \
                    acc[a]["exits"].get(res.get("exit"), 0) + 1
                acc[a]["lev"].append(arms["lev_s"] if a != "G"
                                     else arms.get("lev_g"))
                acc[a]["over"].append(arms["over_S"] if a != "G"
                                      else arms.get("over_G"))
                acc[a]["recs"].append({
                    "at": float(g["at"]), "sym": g["sym"],
                    "exit_ts": float(res["exit_ts"]), "fwd": float(g["fwd"]),
                    "pnl": float(res["pnl_frac"])})
            r_pnl.append([x["pnl_frac"] for x in arms["R"]])
            r_exit.append([float(x["exit_ts"]) for x in arms["R"]])
            r_liq.append([int(x.get("exit") == "ликвидация")
                          for x in arms["R"]])

    n = len(keep)
    if not n:
        return {"refused": f"позиций ноль при {len(longs)} ногах под гейтом "
                           f"(пропущено {skipped}) — баров нет либо геометрия "
                           f"не сложилась; пустота результатом не является"}
    log(f"позиций {n}, пропущено {skipped}, прогон "
        f"{round(time.time() - t_run, 1)} с")
    return measures(longs, keep, acc, r_pnl, r_exit, r_liq, k_hist,
                    no_ladder, degen, thin_gap, skipped, sig_mismatch,
                    sig_missing, draws, seed, time.time() - t_run,
                    g_why=g_why, sig_day=sig_day_hist,
                    draw_failed=draw_failed, log=log)


# ------------------------------------------------------------ сводки

def concentration(recs, ticket):
    """Колонки концентрации: без трёх лучших суток и без лучшего имени.

    Обязательна по уроку проекта: концентрация переворачивает знак (у
    книг DCA 92.7 % итога легло в трое суток). Считается на том же
    составе, что и дневной ряд руки.
    """
    if not recs:
        return None
    by_day, by_name = {}, {}
    for r in recs:
        d = day_of(r["exit_ts"])
        by_day[d] = by_day.get(d, 0.0) + r["pnl"] * ticket
        by_name[r["sym"]] = by_name.get(r["sym"], 0.0) + r["pnl"] * ticket
    tot = sum(by_day.values())
    top3 = sorted(by_day.values(), reverse=True)[:3]
    best = max(by_name.values()) if by_name else 0.0
    return {"tot": round(tot, 2),
            "no_top3_days": round(tot - sum(top3), 2),
            "no_best_name": round(tot - best, 2),
            "best_name": (max(by_name, key=by_name.get) if by_name
                          else None)}


def day_form(recs, cap=BOOK_CAP, ruler=BOOK_RULER):
    """Дневная форма руки: касса бумажных книг, форма — `stability.stats`.

    Правила ЧУЖИЕ и зовутся у хозяев: билет — `dca_paper/rules.ticket`
    (депозит $10 000, режим «оптимальная» → $25), одна позиция на имя —
    `run_d6.one_per_name`, день ВЫХОДА — `tournament.daily` (деньги стали
    известны), форма — `factory/stability.stats`. Своё здесь только
    сцепление: вторая касса разошлась бы со страницей книг.

    Мест книга не связывает намеренно: при билете $25 из $10 000 их 400,
    а одновременных позиций у гейта единицы — предел, который не
    связывает, лучше не изображать связывающим.
    """
    if not recs:
        return None, None
    tk = RB.ticket(cap, ruler)
    keep, skip = D6.one_per_name(recs)
    trades = [{"exit": float(r["exit_ts"]), "net": float(r["pnl"]) * tk}
              for r in keep]
    daily = {d: v[0] for d, v in TNT.daily(trades).items()}
    st = ST.stats(daily)
    if st is not None:
        st.update({"taken": len(keep), "offered": len(recs),
                   "skipped_same_name": skip, "ticket": tk,
                   "capital": cap})
        # Среднее суток рядом с медианой: `stability.stats` печатает
        # медиану (так судят книги), но расхождение медианы и среднего
        # ЗНАКОМ и есть подпись короткой волатильности, а DCA — ровно
        # такая форма. Считается здесь, из того же ряда, и второй кассой
        # не является.
        st["mean_day"] = round(sum(daily.values()) / len(daily), 2)
        st.update(concentration(keep, tk) or {})
    return st, daily


def measures(longs, keep, acc, r_pnl, r_exit, r_liq, k_hist, no_ladder,
             degen, thin_gap, skipped, sig_mismatch, sig_missing, draws,
             seed, secs, g_why=None, sig_day=None, draw_failed=0,
             log=log_):
    n = len(keep)
    day_hist = {}
    for i in keep:
        d = day_of(longs[i]["at"])
        day_hist[d] = day_hist.get(d, 0) + 1
    R = np.asarray(r_pnl, dtype=float)
    S = np.asarray(acc["S"]["pnl"], dtype=float)
    G = np.asarray(acc["G"]["pnl"], dtype=float)
    GP = np.asarray(acc["GP"]["pnl"], dtype=float)
    k_arr = np.asarray(k_hist, dtype=int)

    out = {
        "positions": n, "legs": len(longs), "skipped": skipped,
        "secs": round(secs, 1), "rss_mb": peak_rss_mb(),
        "draws": int(draws), "seed": int(seed),
        "no_ladder": int(no_ladder), "degenerate_2": int(degen),
        "gp_thin_gap": int(thin_gap),
        "draw_failed": int(draw_failed),
        "sigma_mismatch": int(sig_mismatch),
        "sigma_missing": int(sig_missing),
        "no_grid_why": dict(g_why or {}),
        "sigma_day_median": (round(float(np.median(
            [x for x in (sig_day or []) if x])), 4)
            if any(sig_day or []) else None),
        "k_hist": {int(k): int((k_arr == k).sum())
                   for k in sorted(set(k_hist))},
        # Концентрация САМОГО НАСЕЛЕНИЯ во времени — не денег, а решений.
        # У этого журнала она крайняя (83 % ног в трёх сутках), и без
        # числа рядом любая дневная форма читалась бы как «месяц», хотя
        # описывает эпизод. Считается по дню ВХОДА: это состав, а не
        # деньги.
        "day_hist": day_hist,
        "top3_day_share": (round(sum(sorted(day_hist.values(),
                                            reverse=True)[:3]) / n, 3)
                           if n and day_hist else None),
        "params": {"BACK_H": D2.BACK_H, "HOLD_H": D2.HOLD_H,
                   "N_RUNGS": P.N_RUNGS, "MIN_GAP": P.MIN_GAP,
                   "SURVIVE_MULT": P.SURVIVE_MULT,
                   "FLOOR_FRAC": P.FLOOR_FRAC,
                   "SPACING_SIG": P.SPACING_SIG,
                   "SIG_FLOOR_Q": P.SIG_FLOOR_Q,
                   "NULL_Q": P.NULL_Q, "GRID_BAND": P.GRID_BAND},
        "arms": {},
    }
    # --- руки по позициям
    for a in ("S", "G", "GP"):
        out["arms"][a] = P.cell_stats(acc[a]["pnl"], liq=acc[a]["liq"],
                                      lev=acc[a]["lev"], over=acc[a]["over"],
                                      exits=acc[a]["exits"])
    # Рука R в таблицах — МЕДИАННЫЙ РОЗЫГРЫШ, то есть одна целая книга, а
    # не медиана по позициям поперёк розыгрышей: последняя есть
    # статистика, а не портфель, и торговать её нельзя (урок «медиана —
    # не портфель»). Тот же розыгрыш идёт и в дневную форму.
    med_draw = None
    if R.size:
        meds = [float(np.median(R[:, j])) for j in range(R.shape[1])]
        med_draw = int(np.argsort(meds)[len(meds) // 2])
        out["median_draw"] = med_draw
        RL = np.asarray(r_liq, dtype=int)
        # Плечо у R — плечо S по построению (рука отвечает за место, а не
        # за рычаг), поэтому колонка плеча берётся у S, а не оставляется
        # прочерком: прочерк здесь читался бы как «не измерено».
        out["arms"]["R"] = P.cell_stats(
            R[:, med_draw], liq=int(RL[:, med_draw].sum()),
            lev=acc["S"]["lev"], over=acc["S"]["over"])
    else:
        out["arms"]["R"] = {"n": 0}

    # --- нуль §8.6: кусающееся население (рунгов ≥ 3) и всё с лестницей
    bite_mask = k_arr >= 3
    lad_mask = k_arr >= 2
    out["null_bite_n"] = int(bite_mask.sum())
    out["null_ladder_n"] = int(lad_mask.sum())
    pools = {}
    for nm, m in (("bite", bite_mask), ("ladder", lad_mask)):
        if m.sum() >= 5:
            pools[nm] = P.draw_pool(list(S[m]), R[m].tolist())
        else:
            pools[nm] = None
    out["null"] = pools
    out["verdict_null"] = (P.verdict_null(pools["bite"]["nulls"])
                           if pools.get("bite") else
                           P.verdict_null(None))

    # --- убийца 2: σ-сетка (полное население, у кого G измерима)
    m = np.isfinite(S) & np.isfinite(G)
    out["grid_n"] = int(m.sum())
    if m.any():
        d = S[m] - G[m]
        out["grid"] = {
            "median": round(float(np.median(d)), 5),
            "mean": round(float(np.mean(d)), 5),
            "frac_S_above": round(float(np.mean(S[m] > G[m])), 3),
            "median_lev_S": out["arms"]["S"].get("median_lev"),
            "median_lev_G": out["arms"]["G"].get("median_lev"),
        }
        out["verdict_grid"] = P.verdict_grid(out["grid"]["median"],
                                             out["grid"]["frac_S_above"],
                                             int(m.sum()))
    else:
        out["grid"] = None
        out["verdict_grid"] = P.verdict_grid(None, None, 0)

    # --- G′: место при ТОМ ЖЕ плече
    m2 = np.isfinite(S) & np.isfinite(GP) & lad_mask
    if m2.any():
        d2 = S[m2] - GP[m2]
        out["even"] = {"n": int(m2.sum()),
                       "median": round(float(np.median(d2)), 5),
                       "mean": round(float(np.mean(d2)), 5),
                       "frac_S_above": round(float(np.mean(S[m2] > GP[m2])),
                                             3)}
    else:
        out["even"] = None

    # --- дневная форма: одна касса на все руки
    form, days = {}, {}
    for a in ("S", "G", "GP"):
        form[a], days[a] = day_form(acc[a]["recs"])
    if med_draw is not None:
        recs_r = [{"at": float(longs[i]["at"]), "sym": longs[i]["sym"],
                   "exit_ts": float(r_exit[p][med_draw]),
                   "fwd": float(longs[i]["fwd"]),
                   "pnl": float(R[p, med_draw])}
                  for p, i in enumerate(keep)]
        form["R"], days["R"] = day_form(recs_r)
    out["form"] = form
    out["verdict_form"] = P.verdict_form(
        form.get("S"), {"G": form.get("G"), "R": form.get("R")})
    out["boot"] = {
        "S_minus_G": (P.paired_day_boot(days.get("S") or {},
                                        days.get("G") or {})
                      if days.get("S") and days.get("G") else None),
        "S_minus_R": (P.paired_day_boot(days.get("S") or {},
                                        days.get("R") or {})
                      if days.get("S") and days.get("R") else None),
    }
    log("калибровочная пара…")
    out["calibration"] = P.calibrate(n_draws=min(int(draws), P.DRAWS),
                                     seed=seed)
    return out


# ------------------------------------------------------------ отчёт

def _pct(v, nd=2):
    return "—" if v is None or v != v else f"{v * 100:+.{nd}f} %"


def _num(v, nd=1):
    return "—" if v is None or v != v else f"{v:.{nd}f}"


def _money(v):
    return "—" if v is None or v != v else f"{v:+.2f} $"


def _freq(v, nd=2):
    """Частота — доля без знака: «+0.00 %» у частоты читается неверно."""
    return "—" if v is None or v != v else f"{v * 100:.{nd}f} %"


def report(s, tag="1m"):
    P_ = []
    A = P_.append
    A("# Где усреднять: структурные уровни против случайных и σ-сетки "
      "(механика 49b535f8)\n")
    if s.get("refused"):
        A("**Прогон отказался считать.** " + s["refused"] + "\n")
        A("Пустота результатом не является: ноль наблюдений при непустом "
          "входе есть отказ с названной причиной, а не отчёт с прочерками.")
        return "\n".join(P_) + "\n"
    A("Нуль §8.6 спеки 14 на выборах модели: место доливов меняется, всё "
      "остальное — вход, тейк (mfe), пол капитуляции, срок 72 ч, забор §5 "
      "и веса — держится общим. Вердикт по правилу §9 спеки, порог не "
      "мой.\n")
    if tag != "1m":
        # Смоук обязан НАЗЫВАТЬ СЕБЯ в тексте, а не только в имени файла:
        # отчёт, неотличимый от боевого, однажды будет прочитан как
        # боевой (у проекта это уже случалось с артефактами прогонов).
        A(f"⚠ **Это СМОУК (`--tag {tag}`), а не боевой прогон:** население "
          f"урезано ключом `--limit` до {s['positions']} позиций, "
          f"розыгрышей {s['draws']} вместо {P.DRAWS}. Вердикты ниже "
          "проверяют, что дорога считается и печатается, — судить по ним "
          "рынок нельзя.\n")
    A(f"Позиций {s['positions']} из {s['legs']} ног под гейтом, пропущено "
      f"{s['skipped']} (нет баров или геометрии); розыгрышей "
      f"{s['draws']}, зерно {s['seed']}; прогон {s['secs']} с, пик памяти "
      f"{s['rss_mb']} МБ.\n")
    kh = s.get("k_hist") or {}
    A("**Из чего состоит население.** Рунгов в структурной лестнице: "
      + ", ".join(f"{k} — {v}" for k, v in sorted(kh.items()))
      + f". Без лестницы вовсе (одиночный вход, плечо 1×) {s['no_ladder']}; "
      f"с двумя рунгами {s['degenerate_2']} — у них розыгрыш ТОЖДЕСТВЕН "
      "структурной лестнице (нижний рунг закреплён на её глубине, "
      "промежуточных мест нет), и парная разность равна нулю по "
      "построению, а не по существу. Поэтому нуль §8.6 судится на "
      f"кусающемся населении: рунгов ≥ 3, {s['null_bite_n']} позиций; "
      f"рядом напечатано то же по всем, у кого лестница есть "
      f"({s['null_ladder_n']}).\n")
    t3 = s.get("top3_day_share")
    if t3 is not None:
        top = sorted((s.get("day_hist") or {}).items(),
                     key=lambda x: -x[1])[:3]
        A(f"**Насколько население само лежит в эпизоде.** Трое самых "
          f"густых суток дают {t3 * 100:.0f} % позиций ("
          + ", ".join(f"{d} — {c}" for d, c in top)
          + "). Это состав решений, а не деньги: дневная форма ниже "
            "описывает прежде всего эти сутки, и колонка «без 3 лучших "
            "дней» здесь не украшение, а единственный способ увидеть "
            "правило отдельно от эпизода.\n")
    gw = s.get("no_grid_why") or {}
    if gw:
        A("**У кого σ-каркаса нет и почему.** "
          + ", ".join(f"{k}: {v}" for k, v in sorted(gw.items()))
          + " (медианная суточная σ имени "
          + _pct(s.get("sigma_day_median"), 1)
          + " — при шаге 2 σ и четырёх рунгах сетка глубже 100 % цены "
          "перестаёт существовать, и это граница КАРКАСА, а не пропуск "
          "данных). Такие позиции получают прочерк в руке G, а не ноль.\n")
    if s.get("sigma_mismatch"):
        A(f"⚠ σ узкого и широкого окна разошлись у {s['sigma_mismatch']} "
          "позиций — это дефект меры, а не шум: узкое окно обязано быть "
          "префиксом широкого.\n")
    if s.get("draw_failed"):
        A(f"⚠ розыгрышей, не сложившихся по форме, {s['draw_failed']} — они "
          "заменены рукой S, то есть тянут пару к нулю; число печатается "
          "потому, что молчаливая замена была бы подарком нулю.\n")

    A("## Руки по позициям (доля капитала позиции)\n")
    A("| рука | позиций | ликвид. | медиана | среднее | зелёных | худшая | "
      "укус | плечо | 1× | сверх тира |")
    A("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for a in ARMS:
        st = (s["arms"] or {}).get(a) or {}
        if not st.get("n"):
            A(f"| {ARM_NAMES[a]} | — | — | — | — | — | — | — | — | — | — |")
            continue
        A(f"| {ARM_NAMES[a]} | {st['n']} | {_freq(st.get('liq_freq'))} | "
          f"{_pct(st['median'])} | {_pct(st['mean'])} | "
          f"{st['green'] * 100:.1f} % | {_pct(st['worst'], 1)} | "
          f"{_num(st.get('bite'))} | {_num(st.get('median_lev'), 2)}× | "
          f"{_num(st.get('frac_1x'), 2)} | {_num(st.get('over_tier'), 3)} |")
    A("")
    A("Медиана и среднее стоят рядом намеренно: расхождение их ЗНАКА есть "
      "подпись короткой волатильности, и по одной медиане её от эджа не "
      "отличить. «Сверх тира» — доля позиций, чьё плечо выше предела тира "
      "площадки: обе руки считаются без него (как D2/D3 до правки "
      "2026-09-05), пара от этого честна, а неточность названа.\n")

    # --- убийца 1
    A("## Убийца 1 — нуль §8.6: случайные уровни той же глубины\n")
    nb = (s.get("null") or {}).get("bite")
    if not nb:
        A("Нуль не посчитан: кусающегося населения не набралось — это «не "
          "измерено», а не «не бьёт».\n")
    else:
        A(f"Розыгрышей {nb['draws']} на {nb['n']} позициях. Каждый "
          "розыгрыш — ЦЕЛАЯ книга: медиана, среднее и укус считаются "
          "внутри розыгрыша по всем позициям, и только потом сравниваются "
          "с S.\n")
        A("| величина | S | граница 95 % | среднее розыгрышей | размах | "
          "σ от среднего | выше границы |")
        A("|---|--:|--:|--:|--:|--:|--:|")
        for key, nm in (("median", "медиана"), ("mean", "среднее"),
                        ("bite", "укус (меньше — лучше)")):
            v = nb["nulls"].get(key)
            if not v:
                A(f"| {nm} | — | — | — | — | — | — |")
                continue
            f = (_num if key == "bite" else _pct)
            A(f"| {nm} | {f(v['real'])} | {f(v['edge'])} | {f(v['mean'])} | "
              f"{f(v['min'])} … {f(v['max'])} | {_num(v['sigmas'], 2)} | "
              f"{'да' if v['beats'] else 'НЕТ'} |")
        A("")
    for line in (s.get("verdict_null") or {}).get("why") or []:
        A(f"**{line}.**\n")
    for line in (s.get("verdict_null") or {}).get("parts") or []:
        A(f"- {line}")
    A("")
    nl = (s.get("null") or {}).get("ladder")
    if nl:
        v1 = nl["nulls"].get("median") or {}
        v2 = nl["nulls"].get("mean") or {}
        A(f"То же по ВСЕМ позициям с лестницей ({nl['n']}, вместе с "
          f"двухрунговыми, где розыгрыш тождествен S): медиана "
          f"{_pct(v1.get('real'))} против границы {_pct(v1.get('edge'))} "
          f"({'выше' if v1.get('beats') else 'не выше'}), среднее "
          f"{_pct(v2.get('real'))} против {_pct(v2.get('edge'))} "
          f"({'выше' if v2.get('beats') else 'не выше'}). Разбавление "
          "тождественными парами тянет любую разность к нулю — то есть "
          "работает В ПОЛЬЗУ вердикта «украшение», и потому вердикт "
          "выносится не по этой строке.\n")

    # --- убийца 2
    A("## Убийца 2 — какой каркас: структура против σ-сетки\n")
    gr = s.get("grid")
    if not gr:
        A("Сравнение не посчитано: σ не измерена ни у одной позиции.\n")
    else:
        A(f"На {s['grid_n']} позициях, где σ измерима. Медиана S − G "
          f"{_pct(gr['median'], 3)}, среднее {_pct(gr['mean'], 3)}, S выше "
          f"G у {gr['frac_S_above'] * 100:.1f} % выборов; медианное плечо "
          f"S {_num(gr.get('median_lev_S'), 2)}× против "
          f"{_num(gr.get('median_lev_G'), 2)}× у G.\n")
    for line in (s.get("verdict_grid") or {}).get("why") or []:
        A(f"**{line}.**\n")
    ev = s.get("even")
    if ev:
        A(f"**Место при ТОМ ЖЕ плече (S против G′).** На {ev['n']} "
          f"позициях с лестницей: медиана {_pct(ev['median'], 3)}, среднее "
          f"{_pct(ev['mean'], 3)}, S выше G′ у "
          f"{ev['frac_S_above'] * 100:.1f} %. G′ — тот же каркас на глубине "
          "S и с плечом S, поэтому эта строка отделяет МЕСТО от РЫЧАГА: "
          "разность S − G их смешивает, разность S − G′ — нет.\n")

    # --- убийца 3
    A("## Убийца 3 — дневная форма книги\n")
    A(f"Реплей считает позиции независимо, и «сумма долей капитала» книгой "
      f"не является. Здесь касса бумажных книг: депозит ${BOOK_CAP:,.0f}, "
      f"билет ${RB.ticket(BOOK_CAP, BOOK_RULER):,.0f} "
      f"(`dca_paper/rules.ticket`, режим «{BOOK_RULER}»), одна позиция на "
      "имя, сутки — день ВЫХОДА (деньги стали известны).\n")
    A("| рука | суток | зелёных | медиана дня | среднее дня | худший день | "
      "укус | просадка | под водой | итог | без 3 лучших дней | "
      "без лучшего имени | сделок |")
    A("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for a in ARMS:
        st = (s.get("form") or {}).get(a)
        if not st:
            A(f"| {ARM_NAMES[a]} | — | — | — | — | — | — | — | — | — | — | "
              "— | — |")
            continue
        A(f"| {ARM_NAMES[a]} | {st['days']} | {st['green'] * 100:.0f} % | "
          f"{_money(st['med'])} | {_money(st.get('mean_day'))} | "
          f"{_money(st['worst'])} | "
          f"{_num(st.get('bite'))} | {_money(st['dd'])} | {st['under']} | "
          f"{_money(st['tot'])} | {_money(st.get('no_top3_days'))} | "
          f"{_money(st.get('no_best_name'))} | {st['taken']} |")
    A("")
    A("Колонки концентрации обязательны по уроку проекта: у бумажных книг "
      "92.7 % итога легло в трое суток, и без них «итог» описывает эпизод, "
      "а не правило.\n")
    for line in (s.get("verdict_form") or {}).get("why") or []:
        A(f"**{line}.**\n")
    for line in (s.get("verdict_form") or {}).get("parts") or []:
        A(f"- {line}")
    A("")
    for nm, key in (("S − G", "S_minus_G"), ("S − R (медианный розыгрыш)",
                                             "S_minus_R")):
        b = (s.get("boot") or {}).get(key)
        if b:
            A(f"Парный бутстрап по суткам, {nm}: медиана дня "
              f"{_money(b['median'])}, интервал {_money(b['lo'])} … "
              f"{_money(b['hi'])} на {b['days']} общих сутках — "
              + ("ноль НАКРЫТ" if b["covers_zero"] else "ноль не накрыт")
              + ".")
    A("")

    # --- калибровка
    A("## Калибровочная пара: находит подсаженное, молчит на шуме\n")
    c = s.get("calibration") or {}
    pl, nz, gm = c.get("planted"), c.get("noise"), c.get("geom")
    if pl:
        v1, v2 = pl["nulls"]["median"], pl["nulls"]["mean"]
        A(f"**Подсажено** ({c.get('planted_n')} позиций, путь "
          f"разворачивается ровно на уровне, где стоит рунг S): медиана "
          f"{_pct(v1['real'])} против границы {_pct(v1['edge'])} "
          f"({_num(v1['sigmas'], 2)} σ), среднее {_pct(v2['real'])} против "
          f"{_pct(v2['edge'])} ({_num(v2['sigmas'], 2)} σ) — "
          + ("подсаженный эффект НАЙДЕН" if c.get("found")
             else "подсаженный эффект НЕ НАЙДЕН, и тогда отрицательный "
                  "результат прогона ничего не значит") + ".\n")
    if nz:
        v1, v2 = nz["nulls"]["median"], nz["nulls"]["mean"]
        A(f"**Обмениваемость** ({c.get('noise_n')} случайных блужданий; "
          "лестница «S» нарисована ТЕМ ЖЕ законом, что розыгрыши, — по "
          f"построению она один из них): ранг S {v1['rank']:.2f} по "
          f"медиане и {v2['rank']:.2f} по среднему — "
          + ("машинерия молчит, как обязана" if c.get("quiet")
             else "машинерия систематически хвалит S на данных, где хвалить "
                  "нечего, и это дефект самой механики") + ".\n")
    if gm:
        v1 = gm["nulls"]["median"]
        A(f"**Геометрия правила** (диагностика, {c.get('geom_n')} блужданий "
          "со СЛУЧАЙНЫМИ уровнями): структурное правило берёт ближайшие "
          "уровни первыми, розыгрыш равномерен по допустимому множеству — "
          "рунги S систематически выше. На чистом блуждании это ставит S "
          f"на ранг {v1['rank']:.2f} ({_num(v1['sigmas'], 2)} σ) без всякой "
          "«структурности»: столько из разности S − R принадлежит форме "
          "правила, а не содержанию уровней.\n")
    if not pl:
        A("Калибровка не посчиталась — прогон судить нельзя.\n")

    A("\n**Оговорки, объявленные до прогона.** Веса модели видели эти часы "
      "(наследство D2 — оценка сверху); издержки круга в pnl не сняты, всё "
      "брутто; предел плеча тира площадки не применяется ни к одной руке "
      "(как D2/D3 до правки 2026-09-05) — доля позиций сверх предела "
      "напечатана; пол σ берётся из сечения суток (как в `run_dca.py`), и "
      "внутри суток это лёгкое заглядывание вперёд по вспомогательной "
      "величине — на руки S, R и G′ она не влияет ни одним числом; у "
      f"σ-каркаса G′ зазор §R1 не спрашивается (у {s.get('gp_thin_gap')} "
      "лестниц он мельче 1.5 % — правило зазора принадлежит структурному "
      "правилу, и навязывать его сетке значило бы сравнивать не каркасы); "
      "дневная форма каждой руки считается на СВОЁМ составе (правило одной "
      "позиции на имя смотрит на её собственные выходы) — числа сделок "
      "напечатаны рядом.")
    return "\n".join(P_) + "\n"


def publish(name):
    subprocess.run(["tools/publish.sh", f"job: {name}"], cwd=ROOT,
                   check=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--draws", type=int, default=P.DRAWS)
    ap.add_argument("--seed", type=int, default=P.SEED)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--no-mem-guard", action="store_true")
    a = ap.parse_args(argv)
    # Каталог артефактов создаётся ДО счёта: прогон, падающий на записи
    # последнего шага, теряет всю работу (так уже было у турнира).
    os.makedirs(OUT, exist_ok=True)
    tag = a.tag or ("smoke" if a.limit else "1m")
    if not a.no_mem_guard and not mem_guard():
        return 2
    s = run(limit=a.limit, draws=a.draws, seed=a.seed, tag=tag,
            stride=a.stride)
    with open(os.path.join(OUT, f"PLACE-levels-{tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    rep = report(s, tag)
    with open(os.path.join(OUT, f"PLACE-levels-{tag}.md"), "w",
              encoding="utf-8") as f:
        f.write(rep)
    sys.stderr.write("\n" + rep)
    # Публикует САМ прогон: шаг, который можно забыть, забывают.
    if not a.no_publish:
        publish(f"place-levels-{tag}")
    return 0 if not s.get("refused") else 3


if __name__ == "__main__":
    sys.exit(main())
