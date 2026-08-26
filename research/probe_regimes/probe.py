#!/usr/bin/env python3
"""
Зонд неоднородности навыка модели по режимам рынка.

Вопрос владельца: не завести ли отдельные модели, каждая под свою
стратегию? Прежде чем строить флот специалистов, надо узнать дешёвое:
**неоднороден ли навык НЫНЕШНЕЙ модели по режимам**. Если она
предсказывает одинаково (хорошо или плохо) во всех режимах,
специализировать нечего — направление закрывается за вечер, без
единого нового обучения. Если навык сосредоточен в одном режиме,
дешёвая форма использования — не новая модель, а ФИЛЬТР: торговать
только там. Фильтр есть одно объявленное правило вместо пятнадцати
испытаний, и покупает он то же самое.

Это ЗОНД, а не гипотеза: ни порогов, ни вердикта. Его дело — ответить
на один вопрос и решить, стоит ли писать спеку.

Считается по УЖЕ СОХРАНЁННЫМ векторам M2 (walk-forward, вне выборки) и
матрице признаков M1. Ничего не обучается: режимы задаются признаками,
известными в момент решения (тест на заглядывание у них общий, M1).

Главное в конструкции — НУЛЬ СЛУЧАЙНЫХ ТРЕТЕЙ
--------------------------------------------------

IC внутри трети сечения считается по втрое меньшему числу имён, то
есть шумнее по построению. Любое деление даст разброс между корзинами,
и без сравнения этот разброс прочитался бы как «в таком-то режиме
модель работает лучше». Поэтому рядом с делением по признаку идёт
деление на СЛУЧАЙНЫЕ трети того же размера, тем же кодом, на тех же
днях. Свидетельством неоднородности является только превышение
разброса над случайным.

Зерно случайных третей выводится числом из номера дня — не `hash`
(урок R3: хеш строки солится на процесс, и нуль было бы не повторить).

    .venv/bin/python research/probe_regimes/probe.py
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# Режимы ОБЪЯВЛЕНЫ здесь и до прогона. Каждый — признак, известный в
# момент решения, и каждый отвечает на «в какой обстановке мы сейчас»,
# а не «что модель об этом думает».
REGIMES = [
    ("vol_ratio", "волатильность против своей обычной"),
    ("d_oi_7", "приток/отток открытого интереса за неделю"),
    ("turn_rel", "оборот против своего обычного"),
    ("beta", "связь с рынком"),
    ("age", "возраст листинга"),
    ("f_regime", "режим начисления funding"),
]
BINS = 3                      # трети: меньше — грубо, больше — шумно
MIN_NAMES = 30                # сечение тоньше в замер не идёт
RANDOM_DRAWS = 5              # случайных делений на день
SEED = 20260812


def spearman(a, b):
    """Ранговая корреляция. NaN-пары выброшены вызывающим.

    Постоянный ряд меры НЕ имеет: `argsort` расставил бы ему
    произвольные ранги, и корреляция вышла бы единицей на данных, где
    порядка нет вовсе.
    """
    if a.size < 3:
        return np.nan
    if a.max() == a.min() or b.max() == b.min():
        return np.nan
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    ra -= ra.mean()
    rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else np.nan


def _rng(day):
    """Зерно ЧИСЛОМ из номера дня: нуль обязан быть воспроизводим."""
    return np.random.default_rng(SEED + int(day) * 7919)


def load(matrix, vectors, log=print):
    import pyarrow.parquet as pq
    t = pq.read_table(matrix)
    cols = {n: t.column(n).to_numpy(zero_copy_only=False)
            for n in t.schema.names}
    z = np.load(vectors, allow_pickle=True)
    pred = z["pred"]
    if pred.size != cols["day"].size:
        raise SystemExit(
            f"вектор и матрица не совпали: {pred.size} против "
            f"{cols['day'].size} — это разные прогоны")
    # Горизонт берётся из ИМЕНИ вектора: цель обязана быть той, на
    # которую училась модель, иначе IC меряет чужую величину.
    base = os.path.basename(vectors)
    h = "5" if "_h5_" in base else "1"
    key = f"fwd_{h}"
    log(f"вектор {base}: горизонт {h} д, цель {key}, "
        f"предсказаний {int(np.isfinite(pred).sum())}")
    return cols, pred, key


def _day_index(col):
    """Дни числом. В матрице M1 они лежат СТРОКАМИ («2022-12-06»), и
    приводить их к числу напрямую нельзя. Порядок дат при этом важен
    только для группировки, поэтому годится любая взаимно однозначная
    нумерация — берём номер в отсортированном списке."""
    if col.dtype.kind in "iu":
        return col.astype(np.int64)
    uniq = np.unique(col)
    return np.searchsorted(uniq, col).astype(np.int64)


def run(cols, pred, key, log=print, matched=False):
    """`matched=False` — прежний нуль: случайные РАВНЫЕ трети, один
    набор на день. Для непрерывных признаков это честно — их трети по
    квантилям и есть равные.

    `matched=True` — случайные корзины ТЕХ ЖЕ РАЗМЕРОВ, что корзины
    признака, перестановкой его собственной разметки. Нужен признакам
    ДИСКРЕТНЫМ: у них квантильные трети выходят неравными, меньшая
    корзина шумнее по построению, и разброс против равных третей
    расширяется механикой, а не рынком — волновой зонд W3 поймал ровно
    это (единственное дискретное состояние «обошло» нуль, все
    непрерывные легли на него). Умолчание не тронуто: опубликованные
    отчёты этого зонда считались прежним нулём.
    """
    day = _day_index(cols["day"])
    fwd = cols[key].astype(np.float64)
    good = np.isfinite(pred) & np.isfinite(fwd)
    days = np.unique(day[good])
    out = {}
    for feat, _ in REGIMES:
        if feat not in cols:
            log(f"  признака {feat} в матрице нет — пропуск")
            continue
        out[feat] = {"bins": [[] for _ in range(BINS)],
                     "spread": [], "rspread": [], "argmax": [],
                     "all": []}
    n_days = 0
    for d in days:
        m = good & (day == d)
        if int(m.sum()) < MIN_NAMES:
            continue
        n_days += 1
        p, f = pred[m], fwd[m]
        ic_all = spearman(p, f)
        rng = _rng(d)
        # Случайные деления — те же размеры, тот же код, тот же день.
        # Их несколько: разброс ОДНОГО деления сам шумен, и сравнивать
        # с ним значило бы мерить шум шумом.
        rspreads = []
        if not matched:
            for _ in range(RANDOM_DRAWS):
                order = rng.permutation(p.size)
                rb = np.empty(p.size, dtype=np.int64)
                rb[order] = (np.arange(p.size) * BINS) // p.size
                ics = [spearman(p[rb == i], f[rb == i])
                       for i in range(BINS)]
                ics = [v for v in ics if np.isfinite(v)]
                if len(ics) == BINS:
                    rspreads.append(max(ics) - min(ics))
        for fi, (feat, _) in enumerate(REGIMES):
            if feat not in out:
                continue
            v = cols[feat][m].astype(np.float64)
            ok = np.isfinite(v)
            if ok.sum() < MIN_NAMES:
                continue
            # Границы третей — по САМОМУ сечению этого дня: пороги,
            # общие на всю историю, смешали бы режим рынка с режимом
            # инструмента.
            q = np.quantile(v[ok], [1.0 / BINS, 2.0 / BINS])
            b = np.digitize(v, q)
            ics = []
            for i in range(BINS):
                sel = ok & (b == i)
                ics.append(spearman(p[sel], f[sel])
                           if sel.sum() >= 10 else np.nan)
            if not np.isfinite(ics).all():
                continue
            if matched:
                # Перестановка СОБСТВЕННОЙ разметки признака: размеры
                # корзин в точности его, случайна только привязка имён.
                # Зерно — числом из дня и НОМЕРА признака: имя признака
                # через hash солится на процесс (урок R3).
                rngf = np.random.default_rng(
                    SEED + int(d) * 7919 + 104_729 * (fi + 1))
                rspreads = []
                idx = np.flatnonzero(ok)
                for _ in range(RANDOM_DRAWS):
                    per = b[idx][rngf.permutation(len(idx))]
                    ric = [spearman(p[idx[per == i]], f[idx[per == i]])
                           for i in range(BINS)]
                    ric = [v for v in ric if np.isfinite(v)]
                    if len(ric) == BINS:
                        rspreads.append(max(ric) - min(ric))
            if not rspreads:
                continue
            out[feat]["all"].append(ic_all)
            for i in range(BINS):
                out[feat]["bins"][i].append(ics[i])
            # ПАРНОЕ сравнение в тот же день: разброс по режиму против
            # среднего разброса случайных делений. Доля дней, где
            # первый шире, под нулём равна половине — величина
            # устойчивая, в отличие от отношения двух малых разбросов.
            out[feat]["spread"].append(max(ics) - min(ics))
            out[feat]["rspread"].append(float(np.mean(rspreads)))
            out[feat]["argmax"].append(int(np.argmax(ics)))
    return out, n_days


def summarise(out):
    rows = []
    for feat, name in REGIMES:
        g = out.get(feat)
        if not g or not g["all"]:
            continue
        med = [float(np.median(x)) if x else np.nan for x in g["bins"]]
        sp = np.array(g["spread"], dtype=np.float64)
        rp = np.array(g["rspread"], dtype=np.float64)
        am = np.array(g["argmax"], dtype=np.int64)
        # ДВЕ устойчивые величины вместо отношения малых разбросов.
        # Первая: доля дней, где разброс по режиму шире случайного;
        # под нулём это половина. Вторая: доля дней, где данная
        # корзина оказалась лучшей; под нулём — треть. Обе суть доли,
        # а доля не взрывается, когда обе величины малы.
        wider = float((sp > rp).mean())
        best = [float((am == i).mean()) for i in range(BINS)]
        rows.append({
            "feat": feat, "name": name,
            "ic_all": float(np.median(g["all"])),
            "bins": [round(v, 4) for v in med],
            "spread_med": round(float(np.median(sp)), 4),
            "rand_spread_med": round(float(np.median(rp)), 4),
            "wider": round(wider, 3),
            "best_share": [round(v, 3) for v in best],
            "top_bin": int(np.argmax(best)),
            "top_share": round(max(best), 3),
            "sections": len(g["all"])})
    # Порядок — по силе свидетельства: сперва доля дней с более
    # широким разбросом, при равенстве — по устойчивости лучшей
    # корзины.
    rows.sort(key=lambda r: (-r["wider"], -r["top_share"]))
    return rows


def report(rows, n_days, vectors, path):
    lines = [
        "# Зонд неоднородности навыка по режимам", "",
        f"- вектор предсказаний: `{os.path.basename(vectors)}`, "
        f"сечений в замере: **{n_days}**",
        f"- деление на {BINS} корзины по границам САМОГО сечения; "
        f"сечение тоньше {MIN_NAMES} имён не берётся",
        "- рядом с каждым режимом — СЛУЧАЙНЫЕ трети того же размера "
        "тем же кодом: IC на трети сечения шумнее по построению, и без "
        "этого сравнения любой разброс читался бы как режим",
        "- это ЗОНД: порогов и вердикта нет, его дело — решить, стоит "
        "ли писать спеку про специализацию",
        "",
        "| режим | IC всего | по корзинам (низ→верх) | разброс режима "
        "/ случайного | шире случайного, доля дней (нуль 0.50) | "
        "лучшая корзина, доля дней (нуль 0.33) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        b = " / ".join(f"{v:+.3f}" for v in r["bins"])
        lines.append(
            f"| {r['name']} (`{r['feat']}`) | {r['ic_all']:+.4f} | {b} "
            f"| {r['spread_med']:.4f} / {r['rand_spread_med']:.4f} "
            f"| **{r['wider']:.3f}** "
            f"| №{r['top_bin'] + 1} — {r['top_share']:.3f} |")
    best = rows[0] if rows else None
    lines += ["", "## Чтение", ""]
    if not best:
        lines.append("Ни один режим не набрал сечений — замер пуст.")
    elif best["wider"] < 0.60 and best["top_share"] < 0.45:
        lines += [
            f"Ни у одного режима деление сечения не даёт больше, чем "
            f"деление НАУГАД: лучший признак — {best['name']}, "
            f"разброс шире случайного в {best['wider']:.0%} дней при "
            f"нуле 50 %, а лучшая корзина держится "
            f"{best['top_share']:.0%} дней при нуле 33 %.",
            "",
            "Это значит, что навык модели по режимам ОДНОРОДЕН: "
            "**специализировать нечего**, и отдельные модели под "
            "стратегии покупали бы шум за цену пятнадцати объявленных "
            "испытаний. Направление закрыто дёшево — без единого "
            "нового обучения.",
        ]
    else:
        lines += [
            f"Режим **{best['name']}** делит сечение не как попало: "
            f"разброс шире случайного в {best['wider']:.0%} дней "
            f"(нуль 50 %), лучшая корзина №{best['top_bin'] + 1} "
            f"держится {best['top_share']:.0%} дней (нуль 33 %).",
            "",
            "Это ещё НЕ эдж: превышение надо проверить на второй "
            "половине истории и на устойчивость во времени, прежде "
            "чем объявлять правило. Дешёвая форма использования — "
            "ФИЛЬТР (торговать только в лучшей корзине), а не "
            "отдельная модель: фильтр есть одно объявленное правило, "
            "а флот специалистов — пятнадцать испытаний.",
        ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(HERE)
    ap.add_argument("--matrix", default=os.path.join(
        root, "m1_features", "out", "features_1m.parquet"))
    ap.add_argument("--vectors", default=os.path.join(
        root, "m2_walkforward", "out", "vectors_h5_day.npz"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.out:
        tag = os.path.basename(a.vectors).replace("vectors_", "") \
            .replace(".npz", "")
        a.out = os.path.join(HERE, "out", f"regimes-{tag}.md")
    # Каталог артефактов — ДО счёта, а не в `report()`. Ровно этот
    # дефект уже чинился в турнире (прогон досчитал всё и упал на
    # записи), и здесь он повторился слово в слово: урок был записан,
    # но не перенесён в код нового зонда.
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    cols, pred, key = load(a.matrix, a.vectors)
    out, n_days = run(cols, pred, key)
    rows = summarise(out)
    with open(a.out.replace(".md", ".json"), "w",
              encoding="utf-8") as f:
        json.dump({"rows": rows, "sections": n_days,
                   "vectors": os.path.basename(a.vectors)}, f,
                  ensure_ascii=False, indent=1)
    print("отчёт:", report(rows, n_days, a.vectors, a.out))


if __name__ == "__main__":
    main()
