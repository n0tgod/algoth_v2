#!/usr/bin/env python3
"""Судья хвостов: концентрируется ли ЛЕВЫЙ ХВОСТ книги в шортах
против состояния толпы — и общий судья хвоста рядом с машиной суда
навыка.

Девять зондов «обстановки» судили НАВЫК (IC) и дали девять нулей, а
слив 08-24…27 случился при живом IC (+0.079 в худший день): деньги
умерли в хвостах, которых IC не видит. F-серия и разбор слива говорят
одно и то же — хвост приносят ШОРТЫ против состояния толпы, и потолок
по ПРОШЛОМУ ходу его не ловит (BTR входил ДО разгона: сквиз рождается
из состояния, а не из хода). Состояние толпы в момент входа у нас
записано: funding и открытый интерес лежат в почасовых сводках,
на которых учится модель.

Конструкция, объявленная до прогона
-----------------------------------
- Юниверс ячейки — ШОРТЫ одной книги и руки (пять торгуемых книг,
  эхо и наблюдательная запись не входят — правила зонда сетапов).
  Вопрос «плохи ли шорты вообще» не ставится (известно из разбора
  слива); ставится «отличает ли состояние толпы ПЛОХИЕ шорты от
  прочих ШОРТОВ».
- Состояние — на ПОСЛЕДНИЙ ЗАКРЫТЫЙ час перед входом (значение часа
  входа в момент решения ещё не сведено). Два объявленных правила:
  V1 «шорт против переполненного лонга» — funding в верхней трети
  сечения того часа (лонги платят, толпа в лонге); V2 «шорт в свежие
  деньги» — прирост интереса за 24 ч в верхней трети. Терциль — от
  сечения, не константа (режимы ставок меняются, урок A1). Сечение
  тоньше 30 конечных имён — состояния нет, сделка идёт в счётчик
  «не измерено», а не в ноль.
- Мера — не IC и не среднее: доля СУММЫ потерь худших 5 % сделок
  ячейки, принадлежащая помеченным, делённая на долю помеченных среди
  сделок (концентрация; 1.0 — хвост распределён как всё остальное).
- Нуль — перестановка флага ВНУТРИ дня входа с сохранением дневных
  долей (1000 повторов, зерно числом): слив живёт целыми днями, и
  нуль без этой оговорки выдал бы эффект дня за эффект состояния —
  тот же довод, что в зонде согласия рук.
- Зеркало для лонгов (нижняя треть состояния) и конъюнкция V1∧V2 —
  диагностика, в чтение не входят.

Оговорка, которую нельзя терять: левый хвост живой записи почти
целиком есть ОДИН эпизод (слив 08-24…27). Внутридневной нуль
защищает от «в те дни всё было хуже», но переносимость любого ответа
ограничена одним эпизодом — правило из этого зонда не внедряется,
внедрению предшествует слово владельца и накопление календаря.

    cd ~/algoth_v2 && .venv/bin/python research/probe_tailveto/tailveto.py
"""

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, os.path.join(RESEARCH, "probe_turn"))
import turn as PT                                         # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SP = _load("setups_probe",
           os.path.join(RESEARCH, "probe_setups", "setups.py"))
assert hasattr(SP, "book_rows") and hasattr(SP, "BOOKS"), "не тот модуль"

TAIL_Q = 0.05                    # худшие 5 % сделок ячейки по нетто
MIN_SECTION = 30                 # имён с состоянием в сечении часа
MIN_FLAG = 30                    # помеченных сделок на измеримость
MIN_TAIL = 10                    # сделок в хвосте на измеримость
PERMS = 1000
SEED = 20260831


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def col_terciles(M, min_n=MIN_SECTION):
    """Пороги верхней и нижней трети по каждому часу-колонке."""
    cnt = np.isfinite(M).sum(axis=0)
    hi = np.full(M.shape[1], np.nan)
    lo = np.full(M.shape[1], np.nan)
    good = cnt >= min_n
    if good.any():
        with np.errstate(all="ignore"):
            hi[good] = np.nanquantile(M[:, good], 2.0 / 3.0, axis=0)
            lo[good] = np.nanquantile(M[:, good], 1.0 / 3.0, axis=0)
    return hi, lo


def entry_state(M, hi, lo, sym_ix, grid_ix, sym, opened_at):
    """Флаг состояния на последний ЗАКРЫТЫЙ час перед входом.

    Возвращает (top, bottom) как True/False либо (None, None) —
    состояния нет (имя вне сводки, час вне сетки, NaN, тонкое
    сечение). Не измеряется ≠ нет.
    """
    si = sym_ix.get(sym)
    if si is None or opened_at is None:
        return None, None
    h = datetime.fromtimestamp(float(opened_at), timezone.utc) \
        .strftime("%Y-%m-%d-%H")
    j = grid_ix.get(h)
    if j is None or j < 1:
        return None, None
    v = M[si, j - 1]
    if not np.isfinite(v) or not np.isfinite(hi[j - 1]):
        return None, None
    return bool(v >= hi[j - 1]), bool(v <= lo[j - 1])


def tail_judge(entries, perms=PERMS, seed=SEED):
    """Судья хвостов: концентрация худших 5 % в помеченной группе.

    `entries` — список {net, day, flag}; flag True/False (None сюда
    не входят). Нуль — перестановка флагов внутри дня с сохранением
    дневных долей. Возвращает словарь; `measured=False` — ячейка не
    измерена, а не нулевая.
    """
    n = len(entries)
    nets = np.array([e["net"] for e in entries])
    flags = np.array([bool(e["flag"]) for e in entries])
    days = np.array([e["day"] for e in entries])
    n_flag = int(flags.sum())
    out = {"n": n, "n_flag": n_flag,
           "share": (n_flag / n if n else None), "measured": False}
    if n < 3 * MIN_FLAG or n_flag < MIN_FLAG or n - n_flag < MIN_FLAG:
        return out
    thr = float(np.quantile(nets, TAIL_Q))
    tail = nets <= thr
    n_tail = int(tail.sum())
    loss = np.where(tail, np.maximum(0.0, -nets), 0.0)
    total = float(loss.sum())
    out.update({"tail_n": n_tail, "tail_thr": thr})
    if n_tail < MIN_TAIL or total <= 0:
        return out

    def conc(fl):
        share = fl.mean()
        if share <= 0:
            return 0.0
        return float(loss[fl].sum() / total / share)

    obs = conc(flags)
    rng = np.random.default_rng(seed)
    null = np.empty(perms)
    for p in range(perms):
        perm = flags.copy()
        for d in np.unique(days):
            m = days == d
            perm[m] = rng.permutation(perm[m])
        null[p] = conc(perm)
    p_val = float((1 + (null >= obs).sum()) / (1 + perms))
    v_net = nets[flags]
    v_sym = [e["sym"] for e, f in zip(entries, flags) if f]
    by = {}
    for s, x in zip(v_sym, v_net):
        by[s] = by.get(s, 0.0) + float(x)
    top = min(by, key=by.get) if by else None
    out.update({
        "measured": True,
        "tail_flag": int((tail & flags).sum()),
        "loss_share": float(loss[flags].sum() / total),
        "ratio": obs, "p": p_val,
        "null_med": float(np.median(null)),
        "veto_sum": float(v_net.sum()),
        "veto_top_sym": top,
        "veto_wo_top": float(v_net.sum() - by[top]) if top else None})
    return out


def fmt(v, spec="+.2f"):
    return "—" if v is None or (isinstance(v, float)
                                and not np.isfinite(v)) else f"{v:{spec}}"


def cell_line(name, c):
    if not c.get("measured"):
        return (f"| {name} | {c['n']}/{c['n_flag']} | — | — | — | — |"
                " — | не измерена |")
    return (f"| {name} | {c['n']}/{c['n_flag']} | {c['share']:.2f} | "
            f"{c['tail_flag']}/{c['tail_n']} | {c['loss_share']:.2f} | "
            f"{fmt(c['ratio'], '.2f')} | {fmt(c['p'], '.3f')} | "
            f"{fmt(c['veto_sum'], '+.0f')}"
            f" / {fmt(c['veto_wo_top'], '+.0f')} |")


def reading(cells):
    m = [c for _, c in cells if c.get("measured")]
    hits = [c for c in m if c["ratio"] > 1.5 and c["p"] < 0.05]
    if not m:
        return ("Ни одна ячейка не измерена — записи мало, судья "
                "ответа не даёт.")
    if not hits:
        return ("Хвост распределён по состоянию толпы так же, как и "
                "всё остальное: вето по состоянию резало бы сделки, а "
                "не хвост.")
    return (f"Хвост концентрируется в помеченных у {len(hits)} из "
            f"{len(m)} измеренных ячеек — повод считать спеку вето, "
            "не вывод: эпизод в записи один.")


def write_report(path, blocks, diag, meta):
    L = ["# Судья хвостов — шорты против состояния толпы\n"]
    L.append(f"Прогон {meta['when']} · состояние на последний закрытый "
             f"час перед входом · хвост — худшие {TAIL_Q:.0%} сделок "
             f"ячейки · нуль — перестановка флага внутри дня "
             f"({PERMS} повторов, зерно числом)\n")
    L.append("**Это зонд: порогов вердикта нет, правило не "
             "внедряется.** Мера — концентрация: доля суммы потерь "
             "хвоста у помеченных ÷ доля помеченных; 1.0 — хвост "
             "распределён как всё. Оговорка первого порядка: левый "
             "хвост записи почти целиком один эпизод (слив "
             "08-24…27) — внутридневной нуль защищает от эффекта дня, "
             "но переносимость ограничена одним эпизодом.\n")
    for title, cells in blocks:
        L.append(f"\n## {title}\n")
        L.append("| ячейка | сделок/помечено | доля | хвост "
                 "(пом./всего) | доля потерь | концентрация | p | "
                 "вето Σ б.п. / без лучшего |")
        L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for name, c in cells:
            L.append(cell_line(name, c))
        L.append("\n" + reading(cells) + "\n")
    L.append("\n## Диагностика (в чтение не входит)\n")
    L.append("| ячейка | сделок/помечено | доля | хвост | доля потерь"
             " | концентрация | p | вето Σ / без лучшего |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for name, c in diag:
        L.append(cell_line(name, c))
    L.append(f"\nСделок без состояния (нет сводки часа, тонкое "
             f"сечение): {meta['unknown']} из {meta['total']} — "
             "счётчик, не ноль.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="судья хвостов")
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()

    TN = _load("s8_train", os.path.join(RESEARCH, "s8_loop", "train.py"))
    log_("сводки → матрицы")
    mats, syms, grid = TN.load_matrices(TN.SM.OUT)
    if mats is None:
        log_("сводок нет — не та машина, отчёт не пишется")
        return 1
    sym_ix = {s: i for i, s in enumerate(syms)}
    grid_ix = {h: i for i, h in enumerate(grid)}
    states = {
        "V1 funding (толпа в лонге)": mats["fr"] * 1e4,
        "V2 прирост интереса 24 ч": TN.FB.lagged_change(
            mats["oi_usd"], 24)}
    tercs = {k: col_terciles(M) for k, M in states.items()}
    log_(f"матрицы {len(syms)} имён × {len(grid)} часов")

    total = unknown = 0
    blocks, diag = [], []
    cells_by_rule = {k: [] for k in states}
    diag_rows = []
    for hz, mdir_name in SP.BOOKS:
        # Книги живут в s8_loop/out (корень зонда сетапов, а не
        # сборщика); ранний возврат book_rows несёт ТРИ значения
        # против четырёх у полного — распаковка по счёту падала ровно
        # на пустой книге. Первый живой прогон упал на обоих разом.
        mdir = os.path.join(RESEARCH, "s8_loop", "out", mdir_name)
        rows = SP.book_rows(mdir, hz)[0]
        if not rows:
            log_(f"{hz}: книги нет либо пуста — пропуск")
            continue
        for arm in SP.ARMS:
            arm_rows = [r for r in rows if r["arm"] == arm
                        and r.get("opened_at")]
            for rule, M in states.items():
                hi, lo = tercs[rule]
                shorts, longs, conj = [], [], []
                for r in arm_rows:
                    top, bot = entry_state(M, hi, lo, sym_ix, grid_ix,
                                           r["sym"], r["opened_at"])
                    total += 1
                    if top is None:
                        unknown += 1
                        continue
                    day = datetime.fromtimestamp(
                        r["opened_at"], timezone.utc).date().isoformat()
                    e = {"net": r["net"], "day": day, "sym": r["sym"]}
                    if r["side"] == "short":
                        shorts.append(dict(e, flag=top))
                    else:
                        longs.append(dict(e, flag=bot))
                name = f"{hz} · {arm}"
                cells_by_rule[rule].append(
                    (name, tail_judge(shorts)))
                diag_rows.append((f"{name} · лонги-зеркало ({rule})",
                                  tail_judge(longs)))
                log_(f"{rule}: {name} — шортов {len(shorts)}")
    for rule in states:
        blocks.append((f"Шорты · {rule}", cells_by_rule[rule]))
    # total считает каждую сделку по числу правил — доля неизвестного
    # от этого не искажается (оба правила бьют по одной сетке).
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"),
            "unknown": unknown, "total": total}
    path = write_report(os.path.join(OUT, f"TAILVETO-{a.tag}.md"),
                        blocks, diag_rows, meta)
    art = {"meta": meta, "blocks": [
        (t, [(n, c) for n, c in cells]) for t, cells in blocks]}
    with open(os.path.join(OUT, f"tailveto-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False)
    log_(f"отчёт: {path} · {time.time() - t0:.0f} с")
    if not a.no_publish:
        PT.publish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
