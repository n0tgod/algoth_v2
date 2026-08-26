#!/usr/bin/env python3
"""W2 — зонд грамматики волн: прогон, суррогаты, свод, отчёт.

Владелец справедливо не принял W1 как полный ответ: там мерились
одиночные ноги, а волновая теория утверждает, что ноги собираются в
СТРУКТУРЫ — импульс 1–5 с жёсткими правилами, растяжения, чередование
второй и четвёртой, дробление волн на подволны, треугольники. Здесь
проверяется каждое из этих утверждений, и все — без разметки счёта:
скользящим окном из пяти подряд идущих ног правило либо выполнено,
либо нет, и неопровержимость разметки сюда не проникает.

Устройство честности — три решения, объявленные до прогона:

1. **Всё сравнивается с блочным суррогатом** (те же приращения, порядок
   разбит сутками): у зигзага есть собственная геометрия, и она сама
   по себе даёт «структуру» из ничего — W1 намерил у суррогата связь
   соседних ног +0.11.
2. **Порог зигзага — σ САМОГО символа по его ПЕРВЫМ 60 суткам**, замер
   начинается после них: порог из будущего был бы заглядыванием.
3. **Запасы сравнения — константами здесь же** (M_*): «отличие» — это
   разница с суррогатом больше объявленного запаса, в предсказанную
   Эллиоттом сторону, на большинстве порогов зигзага. Читается СЧЁТ
   подтверждённых закономерностей, а не лучшая строка.

Это зонд: вердикта нет, право на итерацию не тратится.

    .venv/bin/python research/w1_waves/grammar_probe.py
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "l3_events"))
sys.path.insert(0, os.path.join(RESEARCH, "a4_cointegration"))
sys.path.insert(0, os.path.join(RESEARCH, "z1_screen"))

import grammar as G                                       # noqa: E402
import probe as P                                         # noqa: E402
import screen as Z                                        # noqa: E402
import waves as W                                         # noqa: E402

# --- пространство, объявленное до прогона -------------------------------

START, END = "2022-07-01", "2026-06-01"
THETAS = (1.0, 2.0, 3.0)          # порог зигзага в суточных σ символа
WARM_DIFFS = 1440                 # 60 суток часовых приращений на σ
MIN_MEAS_H = 24 * 90              # короче — символ не участвует
BOOT = 5                          # суррогатов на символ для грамматики
SUB_COARSE, SUB_FINE = 2.0, 1.0   # пара порогов для дробления
KNN_THETAS = (1.0, 2.0)
KNN_MAX_Q = 30_000
FIB31 = (1.0, G.GOLDEN, 2.618)    # цели для волны 3 к волне 1
FIB51 = (0.618, 1.0, G.GOLDEN)    # цели для волны 5 к волне 1

# Запасы сравнения с суррогатом. Объявлены до прогона: разница мельче
# запаса не читается ни в чью пользу.
M_SHARE = 0.02                    # доли (правила, усечение, растяжение)
M_RHO = 0.02                      # ранговые связи (чередование)
M_FIB = 0.005                     # доли у целей Фибоначчи
M_SUB = 0.2                       # разность средних чисел подволн
M_CONT = 0.02                     # медиана исхода сжатия
M_KNN = 0.01                      # IC поиска по структуре

SEED = 20260826


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def own_theta(x, warm=WARM_DIFFS):
    """σ символа по его первым 60 суткам и индекс начала замера.

    Порог, посчитанный по всей истории, знал бы будущее: разогнавшийся
    в 2025 символ получил бы широкий порог уже в 2023. Здесь порог
    фиксируется по данным СТРОГО ДО измеряемого куска.
    """
    d = np.diff(x)
    fin = np.flatnonzero(np.isfinite(d))
    if len(fin) < warm + MIN_MEAS_H:
        return None, None
    cut = int(fin[warm - 1])
    sig = float(np.nanstd(d[:cut + 1]))
    if not np.isfinite(sig) or sig <= 0:
        return None, None
    return sig * float(np.sqrt(24.0)), cut + 1


def make_surr(x, rng):
    """Суррогатный ряд: те же приращения, порядок разбит сутками."""
    d = np.diff(x)
    s = W.block_bootstrap(d, 24, rng)
    fin = np.isfinite(s)
    y = np.empty(len(x))
    y[0] = x[0]
    y[1:] = x[0] + np.cumsum(np.where(fin, s, 0.0))
    y[1:][~fin] = np.nan
    return y


def new_acc():
    return {k: [] for k in
            ("rule2", "rule3", "rule4", "all3", "trunc5", "extended",
             "longest", "depth", "tdep", "r31", "r51",
             "follow_valid", "follow_not", "c_hits", "c_wins", "cont")}


def collect(d, lg):
    """Все оконные меры одного ряда ног — в накопитель."""
    for i, w in G.windows(lg):
        st = G.impulse_stats(w)
        for k in ("rule2", "rule3", "rule4", "trunc5", "extended"):
            d[k].append(st[k])
        d["all3"].append(G.valid_impulse(st))
        d["longest"].append(st["longest"])
        d["depth"].append((st["depth2"], st["depth4"]))
        d["tdep"].append((st["t2"], st["t4"]))
        d["r31"].append(st["r31"])
        d["r51"].append(st["r51"])
        j = i + G.IMPULSE_K
        if j < len(lg) and lg[j]["i_from"] == w[-1]["i_to"]:
            net = abs(w[-1]["px_to"] - w[0]["px_from"])
            if net > 0:
                key = "follow_valid" if G.valid_impulse(st) else "follow_not"
                d[key].append(lg[j]["size"] / net)
    nh, nw, cont = G.contractions(lg)
    d["c_hits"].append(nh)
    d["c_wins"].append(nw)
    d["cont"].extend(cont)


def share(v):
    return float(np.mean(v)) if len(v) else float("nan")


def rho_pairs(pairs):
    if not pairs:
        return float("nan"), 0
    a = np.array([p[0] for p in pairs])
    b = np.array([p[1] for p in pairs])
    ok = np.isfinite(a) & np.isfinite(b)
    return W.spearman(a[ok], b[ok]), int(ok.sum())


def summarize(d):
    """Свод накопителя одной (θ, сторона)-ячейки в числа отчёта."""
    lon = np.array(d["longest"]) if d["longest"] else np.array([])
    out = {
        "windows": len(d["all3"]),
        "rule2": share(d["rule2"]), "rule3": share(d["rule3"]),
        "rule4": share(d["rule4"]), "all3": share(d["all3"]),
        "trunc5": share(d["trunc5"]), "extended": share(d["extended"]),
        "long_w1": float((lon == 0).mean()) if len(lon) else float("nan"),
        "long_w3": float((lon == 1).mean()) if len(lon) else float("nan"),
        "long_w5": float((lon == 2).mean()) if len(lon) else float("nan"),
        "c_freq": (float(np.sum(d["c_hits"]) / max(np.sum(d["c_wins"]), 1))
                   if d["c_wins"] else float("nan")),
        "cont_med": (float(np.median(d["cont"])) if d["cont"]
                     else float("nan")),
        "cont_n": len(d["cont"]),
        "follow_valid": (float(np.median(d["follow_valid"]))
                         if d["follow_valid"] else float("nan")),
        "follow_not": (float(np.median(d["follow_not"]))
                       if d["follow_not"] else float("nan")),
        "n_follow_valid": len(d["follow_valid"]),
    }
    out["alt_depth"], out["alt_n"] = rho_pairs(d["depth"])
    out["alt_time"], _ = rho_pairs(d["tdep"])
    for t in FIB31:
        out[f"r31@{t}"], out["n_r31"] = G.near_share(d["r31"], t)
    for t in FIB51:
        out[f"r51@{t}"], out["n_r51"] = G.near_share(d["r51"], t)
    return out


CLAIMS = (
    # (имя, предсказание Эллиотта, функция(real, surr) -> bool)
    ("импульсных окон больше",
     lambda r, s: r["all3"] - s["all3"] > M_SHARE),
    ("усечённая пятая реже",
     lambda r, s: s["trunc5"] - r["trunc5"] > M_SHARE),
    ("растяжение чаще",
     lambda r, s: r["extended"] - s["extended"] > M_SHARE),
    ("длиннейшая чаще третья",
     lambda r, s: r["long_w3"] - s["long_w3"] > M_SHARE),
    ("чередование глубин 2 и 4",
     lambda r, s: s["alt_depth"] - r["alt_depth"] > M_RHO),
    ("чередование длительностей",
     lambda r, s: s["alt_time"] - r["alt_time"] > M_RHO),
    ("волна 3 у 1.618 от первой",
     lambda r, s: r[f"r31@{G.GOLDEN}"] - s[f"r31@{G.GOLDEN}"] > M_FIB),
    ("волна 5 у 0.618/1.0 от первой",
     lambda r, s: (r["r51@0.618"] + r["r51@1.0"])
     - (s["r51@0.618"] + s["r51@1.0"]) > M_FIB),
    ("сжатий больше",
     lambda r, s: r["c_freq"] - s["c_freq"] > M_SHARE),
    ("после сжатия — продолжение",
     lambda r, s: r["cont_med"] - s["cont_med"] > M_CONT),
)


def fmt(v, digits=3):
    return ("—" if not np.isfinite(v) else f"{v:+.{digits}f}"
            if v < 0 or digits else f"{v:.{digits}f}")


def sh(v):
    return "—" if not np.isfinite(v) else f"{v:.3f}"


def write_report(path, res, sub, knn, meta):
    L = []
    L.append("# W2 — грамматика волн: структура против суррогата\n")
    L.append(f"Прогон {meta['when']} · {meta['start']}…{meta['end']} · "
             f"символов {meta['used']} из {meta['symbols']} · шаг 1 ч · "
             f"суррогатов на символ {BOOT}\n")
    L.append("**Зонд, а не гипотеза.** Проверяются СТРУКТУРНЫЕ "
             "утверждения волновой теории — правила импульса 1–5, "
             "растяжение, чередование, отношения волн, дробление на "
             "подволны, треугольники — скользящим окном из пяти подряд "
             "идущих ног, без разметки счёта: правило либо выполнено, "
             "либо нет, и выбора между допустимыми счётами не "
             "существует. Каждая мера сравнивается с блочным "
             "суррогатом: у зигзага есть собственная геометрия, и без "
             "сравнения она читалась бы как структура. Запасы сравнения "
             "объявлены до прогона; читать надо счёт подтверждённых "
             "закономерностей, а не лучшую строку.\n")

    for m in THETAS:
        r, s = res.get((m, "real")), res.get((m, "surr"))
        if not r or not s:
            continue
        L.append(f"\n## Порог {m:.0f}σ — окон {r['windows']:,} "
                 f"(суррогат {s['windows']:,})\n")
        L.append("| мера | факт | суррогат | Δ |")
        L.append("|---|--:|--:|--:|")
        rows = (
            ("правило 2 (вторая не перекрывает первую)", "rule2"),
            ("правило 3 (третья не короче обеих)", "rule3"),
            ("правило 4 (четвёртая вне зоны первой)", "rule4"),
            ("**все три разом — импульс**", "all3"),
            ("усечённая пятая", "trunc5"),
            ("растяжение (макс ≥ 1.618×второй)", "extended"),
            ("длиннейшая — первая", "long_w1"),
            ("длиннейшая — третья", "long_w3"),
            ("длиннейшая — пятая", "long_w5"),
            (f"волна 3 у 1.0 от первой", "r31@1.0"),
            (f"волна 3 у 1.618", f"r31@{G.GOLDEN}"),
            (f"волна 3 у 2.618", "r31@2.618"),
            (f"волна 5 у 0.618", "r51@0.618"),
            (f"волна 5 у 1.0", "r51@1.0"),
            ("частота сжатий (4 убывающих ноги)", "c_freq"),
        )
        for name, k in rows:
            dv = r[k] - s[k] if (np.isfinite(r[k]) and np.isfinite(s[k])) \
                else float("nan")
            L.append(f"| {name} | {sh(r[k])} | {sh(s[k])} | "
                     f"{fmt(dv)} |")
        L.append(f"| чередование глубин 2/4 (ранговая связь, "
                 f"n={r['alt_n']:,}) | {fmt(r['alt_depth'])} | "
                 f"{fmt(s['alt_depth'])} | "
                 f"{fmt(r['alt_depth'] - s['alt_depth'])} |")
        L.append(f"| чередование длительностей | {fmt(r['alt_time'])} | "
                 f"{fmt(s['alt_time'])} | "
                 f"{fmt(r['alt_time'] - s['alt_time'])} |")
        L.append(f"| исход после сжатия, медиана (n={r['cont_n']:,}) | "
                 f"{fmt(r['cont_med'])} | {fmt(s['cont_med'])} | "
                 f"{fmt(r['cont_med'] - s['cont_med'])} |")
        L.append(f"| откат после импульса / после не-импульса "
                 f"(n={r['n_follow_valid']:,}) | "
                 f"{sh(r['follow_valid'])} / {sh(r['follow_not'])} | "
                 f"{sh(s['follow_valid'])} / {sh(s['follow_not'])} | |")

    L.append("\n## Дробление: движущие на 5, коррекционные на 3\n")
    L.append("Сердце теории: волна делится на подволны, и у движущих их "
             f"пять, у коррекционных три. Крупный зигзаг {SUB_COARSE:.0f}σ, "
             f"мелкий {SUB_FINE:.0f}σ; роли — по позиции в окне, прошедшем "
             "все три правила. Смотреть надо на РАЗНОСТЬ движущих и "
             "коррекционных против той же разности у суррогата: сами "
             "числа задаёт отношение порогов, а не рынок.\n")
    L.append("| сторона | подволн у движущих (среднее) | у коррекционных "
             "| разность | ног |")
    L.append("|---|--:|--:|--:|--:|")
    for kind, name in (("real", "факт"), ("surr", "суррогат")):
        mo, co = sub[kind]["motive"], sub[kind]["corr"]
        if not mo or not co:
            L.append(f"| {name} | — | — | — | 0 |")
            continue
        dm, dc = float(np.mean(mo)), float(np.mean(co))
        L.append(f"| {name} | {dm:.2f} | {dc:.2f} | {dm - dc:+.2f} | "
                 f"{len(mo) + len(co):,} |")

    L.append("\n## Предсказывает ли структура последних пяти ног "
             "следующую\n")
    L.append("Обобщение всей грамматики разом: соседи по структуре "
             "(четыре отношения подряд идущих ног) из ЧУЖИХ символов и "
             "чужого времени, их следующая нога — предсказание. Нуль — "
             "случайные соседи; суррогат — та же машина на рядах без "
             "структуры. Пул двусторонний по времени с защитой ±30 "
             "суток: мера отвечает «есть ли грамматика», а не «торгуема "
             "ли она».\n")
    L.append("| порог | IC факт | IC нуля | IC суррогата | запросов |")
    L.append("|--:|--:|--:|--:|--:|")
    for m in KNN_THETAS:
        kr = knn.get((m, "real"))
        ks = knn.get((m, "surr"))
        if not kr:
            continue
        L.append(f"| {m:.0f}σ | {fmt(kr[0], 4)} | {fmt(kr[1], 4)} | "
                 f"{fmt(ks[0], 4) if ks else '—'} | {kr[2]:,} |")
    if meta.get("knn_note"):
        L.append(f"\n**Поиск не считался** — {meta['knn_note']}.\n")

    # --- свод по объявленным закономерностям ---------------------------
    L.append("\n## Свод: сколько закономерностей Эллиотта подтверждается\n")
    L.append("«Подтверждается» — отличие от суррогата в предсказанную "
             "сторону с запасом, объявленным до прогона, на большинстве "
             "порогов зигзага. Выбрать лучшую строку задним числом — "
             "ошибка R5.\n")
    L.append("| закономерность | " +
             " | ".join(f"{m:.0f}σ" for m in THETAS) + " | итог |")
    L.append("|---|" + "--:|" * len(THETAS) + "---|")
    confirmed = 0
    for name, f in CLAIMS:
        marks, yes = [], 0
        for m in THETAS:
            r, s = res.get((m, "real")), res.get((m, "surr"))
            ok = bool(r and s and f(r, s))
            yes += ok
            marks.append("да" if ok else "нет")
        verdict = "подтверждается" if yes >= 2 else \
            ("неустойчиво" if yes == 1 else "нет")
        confirmed += yes >= 2
        L.append(f"| {name} | " + " | ".join(marks) + f" | {verdict} |")
    # дробление и kNN — по своим полям
    mo_r, co_r = sub["real"]["motive"], sub["real"]["corr"]
    mo_s, co_s = sub["surr"]["motive"], sub["surr"]["corr"]
    sub_ok = bool(mo_r and co_r and mo_s and co_s and
                  (np.mean(mo_r) - np.mean(co_r))
                  - (np.mean(mo_s) - np.mean(co_s)) > M_SUB)
    confirmed += sub_ok
    L.append("| дробление: движущие на 5, коррекционные на 3 | " +
             " | ".join(["·"] * len(THETAS)) +
             f" | {'подтверждается' if sub_ok else 'нет'} |")
    # «Не измерено» и «нет» — разные вещи: пропущенный по ключу или по
    # памяти поиск не вправе читаться как опровержение.
    knn_measured = any(np.isfinite(knn.get((m, "real"), (np.nan,))[0])
                       for m in KNN_THETAS)
    knn_yes = 0
    for m in KNN_THETAS:
        kr, ks = knn.get((m, "real")), knn.get((m, "surr"))
        knn_yes += bool(kr and ks and np.isfinite(kr[0])
                        and kr[0] > kr[1] + M_KNN
                        and (not np.isfinite(ks[0])
                             or kr[0] > ks[0] + M_KNN))
    knn_ok = knn_measured and knn_yes == len(KNN_THETAS)
    confirmed += knn_ok
    L.append("| структура ног предсказывает следующую | " +
             " | ".join(["·"] * len(THETAS)) +
             f" | {'подтверждается' if knn_ok else ('нет' if knn_measured else 'не мерилось')} |")
    total = len(CLAIMS) + 1 + (1 if knn_measured else 0)
    L.append(f"\n**Итог: подтверждается {confirmed} из {total} "
             "объявленных закономерностей.**\n")
    if confirmed == 0:
        L.append("\n**Читается так:** структурных закономерностей "
                 "волновой теории, отличающих рынок от суррогата с той "
                 "же геометрией зигзага, в этих данных не найдено — "
                 "включая правила импульса, растяжение, чередование, "
                 "дробление и предсказуемость следующей ноги.\n")
    elif confirmed <= 2:
        L.append("\n**Читается так:** почти вся видимая «структура» "
                 "принадлежит геометрии зигзага; выжившие пункты "
                 "перечислены выше и читать их надо по своим строкам, а "
                 "не как подтверждение теории целиком.\n")
    else:
        L.append("\n**Читается так:** часть структурных закономерностей "
                 "отличает рынок от суррогата — по строкам выше видно, "
                 "какие; следующий шаг — спека с порогами, а не вывод "
                 "отсюда.\n")

    L.append("\n## Чего зонд не мерил\n")
    L.append("- Разметку счёта (какая волна первая, где кончается "
             "коррекция): она требует выбора между допустимыми счётами, "
             "и выбор задним числом делает теорию неопровержимой. Здесь "
             "меряется то, что от счёта не зависит.\n")
    L.append("- Торговое правило и деньги: вопрос владельца — «работает "
             "ли теория», и он отвечается сравнением с суррогатом, а не "
             "книгой.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="зонд грамматики волн")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--tag", default="1h")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--skip-knn", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)

    import data as D                                      # noqa: E402
    uni = D.universe()
    symbols = ([s for s in a.symbols.split(",") if s]
               or sorted(uni.keys()))
    times = P.grid(a.start, a.end)
    log_(f"символов {len(symbols)}, часов {len(times):,}")
    L = P.load_prices(symbols, times, a.interval)

    res = {(m, k): new_acc() for m in THETAS for k in ("real", "surr")}
    sub = {k: {"motive": [], "corr": []} for k in ("real", "surr")}
    knn_raw = {(m, k): {"F": [], "Y": [], "C": [], "S": []}
               for m in KNN_THETAS for k in ("real", "surr")}
    used = 0
    t0 = time.time()
    for r, sym in enumerate(symbols):
        if r and r % 50 == 0:
            el = time.time() - t0
            log_(f"  {r}/{len(symbols)} символов, {el:.0f} с, "
                 f"в деле {used}")
        x_full = L[r].astype(np.float64)
        theta_base, start = own_theta(x_full)
        if theta_base is None:
            continue
        x = x_full[start:]
        if int(np.isfinite(x).sum()) < MIN_MEAS_H:
            continue
        used += 1
        rng = np.random.default_rng((SEED, r))
        surrs = [make_surr(x, rng) for _ in range(BOOT)]
        piv_by = {}
        for m in THETAS:
            th = m * theta_base
            piv = W.zigzag(x, th)
            lg = W.legs(x, piv, max_gap=W.MAX_GAP)
            piv_by[("real", m)] = (piv, lg)
            collect(res[(m, "real")], lg)
            for b, y in enumerate(surrs):
                pv = W.zigzag(y, th)
                lgs = W.legs(y, pv, max_gap=W.MAX_GAP)
                collect(res[(m, "surr")], lgs)
                if b == 0:
                    piv_by[("surr", m)] = (pv, lgs)
        # Дробление: роли по окнам крупного зигзага, прошедшим правила.
        for kind in ("real", "surr"):
            pc, lc = piv_by[(kind, SUB_COARSE)]
            pf, _ = piv_by[(kind, SUB_FINE)]
            cnt = G.subdivision(lc, pf)
            for i, w in G.windows(lc):
                if G.valid_impulse(G.impulse_stats(w)):
                    for j in (0, 2, 4):
                        sub[kind]["motive"].append(cnt[i + j])
                    for j in (1, 3):
                        sub[kind]["corr"].append(cnt[i + j])
        # Сырьё поиска по структуре.
        if not a.skip_knn:
            for m in KNN_THETAS:
                for kind in ("real", "surr"):
                    _, lg = piv_by[(kind, m)]
                    F, Y, C = G.leg_queries(lg)
                    kd = knn_raw[(m, kind)]
                    kd["F"] += F
                    kd["Y"] += Y
                    kd["C"] += [c + start for c in C]
                    kd["S"] += [r] * len(F)

    log_(f"символов в деле {used}; считаю поиск по структуре…")
    knn, knn_note = {}, ""
    if a.skip_knn:
        knn_note = "прогон запущен с ключом пропуска"
    if not a.skip_knn:
        pool_max = max((len(kd["F"]) for kd in knn_raw.values()),
                       default=0)
        need = 3 * 128 * pool_max * 4 / 1e6 + 200
        have = P.free_mb()
        log_(f"память поиска: нужно ~{need:.0f} МБ, доступно {have:.0f}")
        if have and need > 0.5 * have:
            # Рядом живой сбор стакана; отказ громкий, а не тихий ноль.
            knn_note = (f"пропущен по памяти: нужно ~{need:.0f} МБ "
                        f"при доступных {have:.0f}")
            log_("поиск по структуре " + knn_note)
            a.skip_knn = True
    if not a.skip_knn:
        for (m, kind), kd in knn_raw.items():
            rng = np.random.default_rng((SEED, 777, int(m * 10),
                                         kind == "surr"))
            ic, ic0, n = G.knn_ic(kd["F"], kd["Y"], kd["C"], kd["S"],
                                  k=50, guard=30 * 24, rng=rng,
                                  max_q=KNN_MAX_Q)
            knn[(m, kind)] = (ic, ic0, n)
            log_(f"  {m:.0f}σ {kind}: IC {ic:+.4f}, нуль {ic0:+.4f}, "
                 f"запросов {n:,} из {len(kd['F']):,}")

    summ = {k: summarize(d) for k, d in res.items()}
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"),
            "start": a.start, "end": a.end,
            "symbols": len(symbols), "used": used,
            "knn_note": knn_note}
    path = os.path.join(OUT, f"W2-grammar-{a.tag}.md")
    write_report(path, summ, sub, knn, meta)
    with open(os.path.join(OUT, f"w2-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"cells": {f"{m}|{k}": v for (m, k), v in summ.items()},
                   "sub": {k: {kk: [int(v) for v in vv]
                               for kk, vv in d.items()}
                           for k, d in sub.items()},
                   "knn": {f"{m}|{k}": v for (m, k), v in knn.items()},
                   "meta": meta}, f, ensure_ascii=False)
    log_(f"отчёт: {path}")
    if not a.no_publish:
        Z.publish("W2: грамматика волн против суррогата")
    return 0


if __name__ == "__main__":
    sys.exit(main())
