#!/usr/bin/env python3
"""
S8.2: цикл переобучения модели на стакане (спека 08 §5).

Один цикл: дожать сводку часов → собрать матрицы → оценить ПРЕЖНЮЮ
модель на часах, пришедших после её обучения (живой вневыборочный IC —
то, что смотрит владелец) → обучить свежие модели по всем целям →
атомарно подменить веса. Обучение на всём накопленном: честность
обеспечивается самими целями — у последних h часов форвард не закрыт
и они в обучение не попадают, а признаки смотрят только назад
(тест «будущее не трогает прошлое» в test_s8.py).

Канарейка утечки: при каждом переобучении одна модель учится на целях,
перемешанных внутри сечений. Шум зерна у такой модели ±0.01–0.015
(замер M2), поэтому канарейка кричит только на грубую течь —
|медианный IC| > 0.05. Полный нуль 3 десятью зёрнами — в вердикте §7,
здесь именно канарейка, а не критерий.

Версия модели штампуется в веса и обязана попадать в каждую бумажную
сделку (урок RULES_VERSION): сводка по смеси версий осмысленна на вид
и бессмысленна по сути.

    .venv/bin/python research/s8_loop/train.py --once
    setsid nohup .venv/bin/python research/s8_loop/train.py \
        >> research/s8_loop/out/train.log 2>&1 &
"""

import argparse
import json
import os
import pickle
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "m2_walkforward"))

import bookfeat as FB                                      # noqa: E402
import gbm                                                 # noqa: E402
import nn                                                  # noqa: E402
import summary as SM                                       # noqa: E402
import wf                                                  # noqa: E402

OUT = os.path.join(HERE, "out")
MODEL_DIR = os.path.join(OUT, "model")

MODEL_VERSION = 2
TARGETS = [f"{k}_{h}h" for k in ("fwd", "mfe", "mae") for h in FB.HORIZONS]
# Турнир: две руки на одних данных, объявлены до окна вердикта.
# gbm — деревья (ML), nn — сеть (AI-рука). Прогноз до запуска записан:
# на табличных признаках и неделях данных сеть скорее проиграет.
ARMS = (("gbm", gbm.fit), ("nn", nn.fit))
CYCLE_SEC = 24 * 3600             # спека §5: раз в сутки
MIN_TRAIN_SECTIONS = 48           # меньше двух суток сечений — рано
CANARY_STOP = 0.05                # грубая течь; шум зерна тут ±0.015
# Бумажный счёт руки: старт $1000, 6 позиций равными долями, тейкерский
# круг 11 б.п. с позиции, без проскальзывания (сказано прямо), плечо 1.
# Счёт — наблюдение для владельца, вердикт остаётся за §7.
START_BALANCE = 1000.0
ROUND_COST_BP = 11.0
SEED0 = 20260801


def log(m):
    print(f"[{datetime.now(timezone.utc).strftime('%m-%d %H:%M:%S')}] {m}",
          flush=True)


# --- мысли модели: перевод её состояния в трейдерские слова ------------
# Это НЕ речь модели (бустинг не говорит), а честный пересказ трёх
# измеримых вещей: чему она верит (важности), как сбылись её прошлые
# прогнозы (живой IC) и кого она выбрала бы сейчас (предсказания на
# последнем сечении). Всё, что нельзя вывести из этих чисел, в мыслях
# не появляется.
FEATURE_RU = (
    ("imb_best", "перекос у лучших цен"),
    ("imb_", "перекос глубины стакана"),
    ("depth_b", "глубина бидов"),
    ("depth_a", "глубина асков"),
    ("spread_rel", "спред"),
    ("upd_rel", "суета обновлений книги"),
    ("big_rel", "крупные уровни"),
    ("turn_rel", "оборот против обычного"),
    ("delta", "перевес агрессора в ленте"),
    ("burst", "всплески объёма"),
    ("traded_share", "непрерывность торгов"),
    ("eat_bid", "выедание бидов"),
    ("eat_ask", "выедание асков"),
    ("net_path", "чистота хода (без пилы)"),
    ("ret_", "ход цены к своей волатильности"),
    ("beta", "связь с рынком"),
    ("age_rec", "возраст записи"),
)


def feat_ru(name):
    for pref, ru in FEATURE_RU:
        if name.startswith(pref):
            return ru
    return name


def _ic_words(v):
    if v >= 0.03:
        return "сбывались заметно лучше случайного"
    if v >= 0.01:
        return "сбывались слабо, но в плюс"
    if v > -0.01:
        return "легли около нуля"
    return "шли мимо"


def think(prev_man, man, ic_rows, picks):
    """Мысли одного цикла. Чистая функция — закреплена тестами."""
    out = []
    ic = next((r for r in ic_rows or [] if r["target"] == "fwd_4h"), None)
    if ic:
        out.append(f"проверил вчерашние прогнозы на {ic['sections']} новых "
                   f"сечениях: направления {_ic_words(ic['median_ic'])} "
                   f"(IC {ic['median_ic']:+.3f}).")
    imp = (man.get("importance") or {}).get("fwd_4h") or {}
    top = list(imp)[:3]
    if top:
        out.append("сильнее всего сейчас смотрю на: "
                   + ", ".join(feat_ru(t) for t in top) + ".")
    prev_imp = ((prev_man or {}).get("importance") or {}).get("fwd_4h")
    if prev_imp and imp:
        diff = [(k, imp.get(k, 0.0) - prev_imp.get(k, 0.0))
                for k in set(imp) | set(prev_imp)]
        up = max(diff, key=lambda x: x[1])
        dn = min(diff, key=lambda x: x[1])
        if up[1] > 0.02:
            out.append(f"после переобучения стал больше доверять: "
                       f"{feat_ru(up[0])} (+{up[1]:.2f} веса), меньше — "
                       f"{feat_ru(dn[0])} ({dn[1]:+.2f}).")
    if picks:
        long_s = ", ".join(
            f"{p['sym'].replace('USDT','')} (жду {p['fwd']:+.0f} б.п. за "
            f"4 ч, путь против до {p['mae']:.0f})" for p in picks["long"])
        short_s = ", ".join(
            f"{p['sym'].replace('USDT','')} ({p['fwd']:+.0f} б.п.)"
            for p in picks["short"])
        out.append(f"если бы торговал сейчас: лонг — {long_s}; "
                   f"шорт — {short_s}. Это ожидание в среднем, не "
                   f"обещание пути.")
    can = man.get("canary_ic")
    if can is not None:
        out.append(f"проверка на шум {'чиста' if abs(can) <= CANARY_STOP else 'ПОДНЯТА'} "
                   f"({can:+.3f}): на перемешанных данных я бы ничего "
                   f"не «увидел» — значит то, что вижу, не выдумка "
                   f"конвейера.")
    if not prev_man:
        out.insert(0, f"первое обучение: {man.get('sections')} сечений по "
                      f"{man.get('symbols')} монетам. Пока выборка "
                      f"короткая — выводы будут гулять, это нормально.")
    return out


def load_matrices(sum_dir):
    """Сводки всех символов → словарь матриц (символы, часы).

    Сетка часов общая и непрерывная от первого до последнего часа:
    дыра записи — колонка NaN, а не выпавшая колонка. Склей мы только
    имеющиеся часы, форвард через дыру склеил бы вечер с утром — тот же
    дефект, что `diff` по дырявым барам, закрытый в R1.
    """
    rows_by_sym = {}
    hours = set()
    try:
        symbols = sorted(os.listdir(sum_dir))
    except OSError:
        return None, [], []
    for sym in symbols:
        rr = []
        sdir = os.path.join(sum_dir, sym)
        for fn in sorted(os.listdir(sdir)):
            if not fn.endswith(".jsonl"):
                continue
            with open(os.path.join(sdir, fn), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        rr.append(r)
                        hours.add(r["hour"])
                    except (ValueError, KeyError):
                        continue
        if rr:
            rows_by_sym[sym] = rr
    if not rows_by_sym:
        return None, [], []
    h0 = min(hours)
    h1 = max(hours)
    grid = []
    t = datetime.strptime(h0, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    end = datetime.strptime(h1, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    while t <= end:
        grid.append(t.strftime("%Y-%m-%d-%H"))
        t = datetime.fromtimestamp(t.timestamp() + 3600, timezone.utc)
    idx = {h: i for i, h in enumerate(grid)}
    syms = sorted(rows_by_sym)
    fields = set()
    for rr in rows_by_sym.values():
        fields.update(rr[0])
    fields.discard("hour")
    mats = {f: np.full((len(syms), len(grid)), np.nan) for f in fields}
    for si, sym in enumerate(syms):
        for r in rows_by_sym[sym]:
            j = idx.get(r["hour"])
            if j is None:
                continue
            for f in fields:
                v = r.get(f)
                if isinstance(v, (int, float)):
                    mats[f][si, j] = v
    return mats, syms, grid


def assemble(mats):
    """Матрицы сводки → (X, имена признаков, цели, elig, r)."""
    feats, r, elig = FB.feature_pack(mats)
    targets = FB.target_pack(mats, r, elig, feats["beta"])
    names = sorted(feats)
    S, H = mats["mid_close"].shape
    x = np.stack([feats[n] for n in names], axis=-1)    # (S, H, F)
    return x, names, targets, elig


def flatten(x, y, elig):
    """(S, H) → строки обучения: только сечения, только закрытые цели."""
    m = elig & np.isfinite(y)
    return x[m], y[m], m


def section_ic(pred_mat, y_mat, elig, cols):
    out = []
    for j in cols:
        m = elig[:, j] & np.isfinite(y_mat[:, j]) & np.isfinite(
            pred_mat[:, j])
        if m.sum() < FB.MIN_SECTION:
            continue
        out.append(wf.spearman(pred_mat[m, j], y_mat[m, j]))
    return [v for v in out if np.isfinite(v)]


def predict_matrix(model, x, elig):
    S, H, Fn = x.shape
    pred = np.full((S, H), np.nan)
    m = elig.copy()
    if m.any():
        pred[m] = model.predict(x[m])
    return pred


def eval_previous(x, targets, elig, grid, log_):
    """Живой вневыборочный IC: прежние веса на часах после их обучения."""
    man_path = os.path.join(MODEL_DIR, "manifest.json")
    try:
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)
        upto = man["trained_upto"]
    except (OSError, ValueError, KeyError):
        return []
    cols = [j for j, h in enumerate(grid) if h > upto]
    if not cols:
        return []
    rows = []
    for arm, _ in ARMS:
        for tgt in TARGETS:
            wpath = os.path.join(MODEL_DIR, f"weights_{arm}_{tgt}.pkl")
            try:
                with open(wpath, "rb") as f:
                    saved = pickle.load(f)
            except OSError:
                continue
            pred = predict_matrix(saved["model"], x, elig)
            ics = section_ic(pred, targets[tgt], elig, cols)
            if not ics:
                continue
            rows.append({"arm": arm, "target": tgt,
                         "version": saved.get("version"),
                         "trained_upto": upto,
                         "median_ic": round(float(np.median(ics)), 4),
                         "sections": len(ics)})
    if not rows:
        return []
    with open(os.path.join(MODEL_DIR, "ic_history.jsonl"), "a",
              encoding="utf-8") as f:
        at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        for r in rows:
            r["at"] = at
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    for arm, _ in ARMS:
        ml = next((r for r in rows if r["target"] == "fwd_4h"
                   and r.get("arm") == arm), None)
        if ml:
            log_(f"живой IC [{arm}]: fwd_4h {ml['median_ic']:+.4f} на "
                 f"{ml['sections']} новых сечениях")
    return rows


def canary(x, y, elig, grid, seed, log_):
    """Обучение на перемешанных целях: кричит только на грубую течь."""
    day_idx = np.broadcast_to(np.arange(len(grid)), elig.shape)
    m = elig & np.isfinite(y)
    xs, ys = x[m], y[m].copy()
    secs = day_idx[m]
    rng = np.random.default_rng(seed)
    for j in np.unique(secs):
        sel = np.flatnonzero(secs == j)
        ys[sel] = ys[sel][rng.permutation(len(sel))]
    model = gbm.fit(xs, ys, seed=seed + 1)
    pred = np.full(elig.shape, np.nan)
    pred[m] = model.predict(xs)
    ics = section_ic(pred, y, elig, list(range(len(grid))))
    med = float(np.median(ics)) if ics else float("nan")
    log_(f"канарейка (перемешанные цели): медианный IC {med:+.4f}")
    return med


def cycle(sum_dir, log_, book_root=SM.BOOK_ROOT):
    t0 = time.time()
    if book_root and os.path.isdir(os.path.join(book_root, "book")):
        n_new = SM.run(book_root, sum_dir, None, log_)
    else:
        n_new = 0
        log_("сырой записи здесь нет — работаю по готовым сводкам")
    mats, syms, grid = load_matrices(sum_dir)
    if mats is None:
        log_("сводок ещё нет — цикл пропущен")
        return False
    x, names, targets, elig = assemble(mats)
    n_sections = int((elig.sum(axis=0) >= FB.MIN_SECTION).sum())
    log_(f"матрица: {len(syms)} символов × {len(grid)} часов, "
         f"сечений с ≥{FB.MIN_SECTION} именами: {n_sections}, "
         f"признаков {len(names)}")
    if n_sections < MIN_TRAIN_SECTIONS:
        log_(f"сечений меньше {MIN_TRAIN_SECTIONS} — учиться рано, "
             f"запись копится")
        return False

    ic_rows = eval_previous(x, targets, elig, grid, log_)

    med = canary(x, targets["fwd_4h"], elig, grid,
                 SEED0 + len(grid), log_)
    if np.isfinite(med) and abs(med) > CANARY_STOP:
        log_(f"КАНАРЕЙКА КРИЧИТ: |IC| {abs(med):.3f} > {CANARY_STOP} — "
             f"похоже на течь конвейера, веса НЕ обновляются")
        return False

    os.makedirs(MODEL_DIR, exist_ok=True)
    imp_all = {}
    models = {}
    for ai, (arm, fit_fn) in enumerate(ARMS):
        for ti, tgt in enumerate(TARGETS):
            xs, ys, _ = flatten(x, targets[tgt], elig)
            if len(ys) < 1000:
                log_(f"{arm}/{tgt}: строк {len(ys)} — пропуск")
                continue
            t1 = time.time()
            model = fit_fn(xs, ys,
                           seed=SEED0 + 10_000 * ai + 100 * ti + len(grid))
            models[(arm, tgt)] = model
            tot = model.importance.sum() or 1.0
            imp = {names[j]: round(float(model.importance[j] / tot), 4)
                   for j in np.argsort(model.importance)[::-1][:10]}
            imp_all.setdefault(arm, {})[tgt] = imp
            blob = {"model": model, "features": names, "target": tgt,
                    "arm": arm, "version": MODEL_VERSION,
                    "trained_upto": grid[-1], "rows": len(ys)}
            p = os.path.join(MODEL_DIR, f"weights_{arm}_{tgt}.pkl")
            with open(p + ".tmp", "wb") as f:
                pickle.dump(blob, f)
            os.replace(p + ".tmp", p)
            log_(f"{arm}/{tgt}: обучена на {len(ys):,} строках за "
                 f"{time.time() - t1:.0f} с; топ: "
                 + ", ".join(f"{k} {v}" for k, v in list(imp.items())[:3]))

    mp = os.path.join(MODEL_DIR, "manifest.json")
    prev_man = None
    try:
        with open(mp, encoding="utf-8") as f:
            prev_man = json.load(f)
    except (OSError, ValueError):
        pass

    man = {"version": MODEL_VERSION, "trained_upto": grid[-1],
           "trained_at": datetime.now(timezone.utc).isoformat(
               timespec="seconds"),
           "symbols": len(syms), "hours": len(grid),
           "sections": n_sections, "targets": sorted(imp_all),
           "canary_ic": round(med, 4) if np.isfinite(med) else None,
           "new_summary_hours": n_new,
           "importance": imp_all,
           "cycle_sec": round(time.time() - t0, 1)}
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    os.replace(mp + ".tmp", mp)

    # Выбор -> ожидание -> факт, по каждой руке турнира отдельно:
    # сводка по смеси рук осмысленна на вид и бессмысленна по сути.
    ppath = os.path.join(MODEL_DIR, "picks.jsonl")
    prev_picks = {}
    try:
        with open(ppath, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    prev_picks[row.get("arm") or "gbm"] = row
                except ValueError:
                    continue
    except OSError:
        pass

    at = datetime.now(timezone.utc).strftime("%m-%d %H:%M")
    all_lines = []
    si = {s: i for i, s in enumerate(syms)}
    j_last = max((jj for jj in range(len(grid))
                  if elig[:, jj].sum() >= FB.MIN_SECTION), default=None)
    for arm, _ in ARMS:
        review = None
        lp = prev_picks.get(arm)
        if lp and lp.get("hour") in grid:
            j = grid.index(lp["hour"])
            review = []
            for side in ("long", "short"):
                for pk in lp.get(side) or []:
                    i = si.get(pk["sym"])
                    if i is None:
                        continue
                    got = targets["fwd_4h"][i, j]
                    if np.isfinite(got):
                        review.append({"sym": pk["sym"], "side": side,
                                       "expected": round(pk["fwd"], 1),
                                       "got": round(float(got), 1)})
            if review:
                with open(os.path.join(MODEL_DIR, "review.jsonl"), "a",
                          encoding="utf-8") as f:
                    f.write(json.dumps(
                        {"arm": arm, "hour": lp["hour"], "rows": review},
                        ensure_ascii=False) + "\n")
                # Бумажный счёт: исполняем прошлый выбор по факту.
                apath = os.path.join(MODEL_DIR, f"account_{arm}.json")
                try:
                    with open(apath, encoding="utf-8") as f:
                        acc = json.load(f)
                except (OSError, ValueError):
                    acc = {"balance": START_BALANCE, "history": []}
                pos = acc["balance"] / max(len(review), 1)
                pnl = sum(pos * ((1 if r["side"] == "long" else -1)
                                 * r["got"] - ROUND_COST_BP) / 1e4
                          for r in review)
                acc["balance"] = round(acc["balance"] + pnl, 2)
                acc["history"].append(
                    {"hour": lp["hour"], "pnl": round(pnl, 2),
                     "balance": acc["balance"]})
                acc["history"] = acc["history"][-500:]
                with open(apath + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(acc, f, ensure_ascii=False)
                os.replace(apath + ".tmp", apath)
        picks = None
        if (arm, "fwd_4h") in models and (arm, "mae_4h") in models \
                and j_last is not None:
            rows_m = np.flatnonzero(elig[:, j_last])
            xj = x[rows_m, j_last]
            fwd = models[(arm, "fwd_4h")].predict(xj)
            mae = models[(arm, "mae_4h")].predict(xj)
            o = np.argsort(fwd)
            mk = lambda i: {"sym": syms[rows_m[i]],          # noqa: E731
                            "fwd": float(fwd[i]),
                            "mae": float(mae[i])}
            picks = {"arm": arm, "hour": grid[-1],
                     "long": [mk(i) for i in o[::-1][:3]],
                     "short": [mk(i) for i in o[:3]]}
            with open(ppath, "a", encoding="utf-8") as f:
                f.write(json.dumps(picks, ensure_ascii=False) + "\n")

        man_arm = dict(man, importance=imp_all.get(arm) or {})
        prev_arm = None
        if prev_man:
            pi = prev_man.get("importance") or {}
            prev_arm = dict(prev_man,
                            importance=pi.get(arm) if arm in pi else pi)
        ic_arm = [r for r in ic_rows or [] if r.get("arm") == arm]
        lines = think(prev_arm, man_arm, ic_arm, picks)
        if review:
            hits = sum(1 for r in review
                       if (r["got"] > 0) == (r["side"] == "long"))
            lines.insert(0, f"счёт: {acc['balance'] - pnl:+.2f} -> "
                            f"{acc['balance']:+.2f} $ "
                            f"({pnl / max(acc['balance'] - pnl, 1) * 1e4:+.0f}"
                            f" б.п. за круг, издержки учтены).")
            lines.insert(0, f"разбор прошлых выборов ({len(review)} имён, "
                            f"угадан знак у {hits}): " + "; ".join(
                                f"{r['sym'].replace('USDT','')} "
                                f"{'лонг' if r['side'] == 'long' else 'шорт'}: "
                                f"ждал {r['expected']:+.0f}, вышло "
                                f"{r['got']:+.0f} б.п." for r in review))
        all_lines += [f"[{'деревья' if arm == 'gbm' else 'сеть'}] {t}"
                      for t in lines]
    lines = all_lines
    with open(os.path.join(MODEL_DIR, "thoughts.jsonl"), "a",
              encoding="utf-8") as f:
        for t in lines:
            f.write(json.dumps({"at": at, "text": t},
                               ensure_ascii=False) + "\n")
    for t in lines:
        log_(f"мысль: {t}")
    log_(f"цикл закончен за {man['cycle_sec']:.0f} с, веса v{MODEL_VERSION} "
         f"до часа {grid[-1]}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--summary-dir", default=SM.OUT)
    a = ap.parse_args()
    try:
        os.nice(10)               # приём данных важнее счёта
    except OSError:
        pass
    while True:
        try:
            cycle(a.summary_dir, log)
        except Exception as e:                            # noqa: BLE001
            # Цикл живёт сутками; одна упавшая итерация не вправе
            # убить процесс — но обязана быть видна.
            import traceback
            log(f"цикл упал: {type(e).__name__}: {e}")
            traceback.print_exc()
        if a.once:
            break
        time.sleep(CYCLE_SEC)


if __name__ == "__main__":
    main()
