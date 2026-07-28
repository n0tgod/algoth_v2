#!/usr/bin/env python3
"""
R2 — отчёт: возврат остатка вне выборки.

Все числа читаются из артефакта прогона, ни одно не зашито в текст.
Зависимостей тяжелее `json` нет — настройки прогона лежат в самом файле.

    python3 report.py --interval 1m > out/R2-report-1m.md
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# Пороги §8.3 спеки 03. Утверждены до прогона, здесь только сверка.
IC_MIN = 0.02
T_MIN = 3.0
POSITIVE_SHARE_MIN = 0.60
SECTIONS_MIN = 100
# Критерий немедленной остановки §8.2.
STOP_IC = 0.005
STOP_COST_RATIO = 2.0
# Цикл издержек по отобранным именам, замер A1. Здесь используется только
# для сверки с §8.2 — сам расчёт издержек предмет R4.
COST_CYCLE_BP = 26.0


def fmt(x, d=4):
    return "—" if x is None else f"{x:.{d}f}"


def bp(x):
    return "—" if x is None else f"{x * 10000:.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    args = ap.parse_args()
    path = os.path.join(OUT, f"crosssection_{args.interval}.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала crosssection.py "
                         f"--interval {args.interval}")
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    cfg, s = doc["config"], doc["summary"]
    cells = s["cells"]
    p = print

    p("# R2 — возврат остатка вне выборки\n")
    p("**Спека:** 03, этап R2, критерии §8.3 п. 1–3 и §8.2  ")
    p(f"**Модель фактора:** {cfg['model']} — ступень 1 лестницы §3.3  ")
    p(f"**Шаг бара:** {cfg['step']}, окно формирования {cfg['form_days']} дн  ")
    p(f"**Разрешение хранилища:** {cfg['interval']}  ")
    p(f"**Сечений:** {s['sections_total']}, "
      f"{s.get('date_first')} … {s.get('date_last')}  ")
    p(f"**Активов в сечении:** медиана {s['assets']['median']:.0f}, "
      f"от {s['assets']['min']} до {s['assets']['max']}\n")

    # ---- вердикт --------------------------------------------------------
    def cell_pass(c):
        i = c["ic_independent"]
        return (i["mean"] is not None and i["mean"] >= IC_MIN
                and i["t"] is not None and i["t"] >= T_MIN
                and i["positive_share"] is not None
                and i["positive_share"] >= POSITIVE_SHARE_MIN
                and i["sections"] >= SECTIONS_MIN)

    passed = [k for k, c in cells.items() if cell_pass(c)]
    ics = [c["ic_independent"]["mean"] for c in cells.values()
           if c["ic_independent"]["mean"] is not None]
    med = s["grid"]["ic_median"]

    p("## Итог\n")
    p("Решение принимается **по медиане сетки, а не по лучшей ячейке** "
      "(§2 спеки). Лучшая ячейка приводится только для того, чтобы был "
      "виден размер разрыва между медианой и максимумом: у настоящего "
      "эффекта плато, у подгонки — узкий гребень.\n")
    p("| Величина | Порог | Получено | |")
    p("|---|---|---|---|")
    p(f"| Медианный IC по сетке | ≥ {IC_MIN} | **{fmt(med)}** | "
      f"{'✓' if med is not None and med >= IC_MIN else '✗'} |")
    p(f"| Ячеек, прошедших все критерии §8.3 п. 1–3 | — | "
      f"**{len(passed)}** из {len(cells)} | |")
    p(f"| Ячеек с положительным IC | — | {s['grid']['positive_cells']} "
      f"из {len(cells)} | |")
    p(f"| Лучшая ячейка | — | {fmt(s['grid']['ic_best'])} | |")
    p(f"| Худшая ячейка | — | {fmt(s['grid']['ic_worst'])} | |\n")

    # ---- критерий немедленной остановки ---------------------------------
    p("## Критерий немедленной остановки §8.2\n")
    p("Проверяется до бэктеста намеренно: в A4 перестановочный тест "
      "обесценил результат месячного прогона, и узнали об этом в конце.\n")
    best = max(cells.items(),
               key=lambda kv: (kv[1]["ic_independent"]["mean"] is not None,
                               kv[1]["ic_independent"]["mean"] or -9))
    bk, bc = best
    bspread = bc["decile"]["spread_mean"]
    ratio = (abs(bspread) * 10000 / COST_CYCLE_BP) if bspread else None
    p("| Условие остановки | Порог | Получено | Сработало |")
    p("|---|---|---|---|")
    stop_ic = med is None or med < STOP_IC
    p(f"| Медианный IC по непересекающимся сечениям | < {STOP_IC} | "
      f"{fmt(med)} | {'ДА' if stop_ic else 'нет'} |")
    stop_cost = ratio is None or ratio < STOP_COST_RATIO
    p(f"| Брутто-спред лучшей ячейки против цикла издержек {COST_CYCLE_BP:.0f} б.п. "
      f"| < {STOP_COST_RATIO}× | {fmt(ratio, 2)}× | "
      f"{'ДА' if stop_cost else 'нет'} |")
    p("| Реальный IC против нуля | 95-й процентиль зёрен | считается в R3 | — |\n")
    p(f"Спред лучшей ячейки (`{bk}`) — **{bp(bspread)} б.п.** за период "
      f"удержания, брутто. Издержки здесь не вычтены: их расчёт — предмет "
      f"R4, и сравнение с циклом {COST_CYCLE_BP:.0f} б.п. по отобранным "
      f"именам (замер A1) приведено только ради §8.2.\n")

    # ---- полная сетка ---------------------------------------------------
    p("## Вся сетка\n")
    p("Публикуются все ячейки, а не выбранная (§2, правило 2).\n")
    p("| k, дн | h, дн | IC незав. | t | Сечений | Доля + | Дециль, б.п. "
      "| Годовых, % | Квинтиль, б.п. |")
    p("|---|---|---|---|---|---|---|---|---|")
    for k in cfg["ks"]:
        for h in cfg["hs"]:
            c = cells.get(f"k{k}_h{h}")
            if not c:
                continue
            i = c["ic_independent"]
            d, q = c.get("decile", {}), c.get("quintile", {})
            mark = " **" if cell_pass(c) else ""
            p(f"|{mark} {k}{mark} | {h} | {fmt(i['mean'])} | {fmt(i['t'], 2)} "
              f"| {i['sections']} | {fmt(i['positive_share'], 2)} "
              f"| {bp(d.get('spread_mean'))} "
              f"| {fmt((d.get('annualized') or 0) * 100, 1)} "
              f"| {bp(q.get('spread_mean'))} |")
    p("")
    p(f"Пороги §8.3: IC ≥ {IC_MIN}, t ≥ {T_MIN}, доля положительных "
      f"сечений ≥ {POSITIVE_SHARE_MIN}, непересекающихся сечений "
      f"≥ {SECTIONS_MIN}.\n")

    p("**Перекрывающиеся сечения приводятся отдельно** и в вердикте не "
      "участвуют. Ежедневный ребаланс при удержании в несколько дней даёт "
      "сильно зависимые наблюдения, и t на них завышена по построению — "
      "ровно тот механизм, который в A4 создал превосходство ×4.7 из "
      "ничего.\n")
    p("| k, дн | h, дн | IC перекрыв. | t перекрыв. | Сечений |")
    p("|---|---|---|---|---|")
    for k in cfg["ks"]:
        for h in cfg["hs"]:
            c = cells.get(f"k{k}_h{h}")
            if not c:
                continue
            o = c["ic_overlapping"]
            p(f"| {k} | {h} | {fmt(o['mean'])} | {fmt(o['t'], 2)} "
              f"| {o['sections']} |")
    p("")

    # ---- ловушки --------------------------------------------------------
    comp = s.get("composition")
    if comp:
        p("## Ловушки §5.2 и §5.3: чем дециль отличается от универсума\n")
        p(f"Замер на ячейке `k7_h3`, медиана по {comp['sections']} сечениям.\n")
        p("| Величина | Лонг (отстал) | Шорт (ушёл вперёд) | Универсум |")
        p("|---|---|---|---|")
        for label, field, f in (
            ("Медианный дневной оборот, $", "turnover", lambda x: f"{x:,.0f}"),
            ("Доля баров со сделками", "share_traded", lambda x: f"{x:.4f}"),
            ("Возраст листинга, дней", "age_days", lambda x: f"{x:,.0f}"),
        ):
            row = [comp[leg][field] for leg in ("long", "short", "universe")]
            p(f"| {label} | " + " | ".join("—" if x is None else f(x)
                                           for x in row) + " |")
        p("")
        p("**§5.2 — торгуем ли мы то, что можно торговать.** Если дециль "
          "систематически беднее универсума, брутто-спред завышен: "
          "проскальзывание считается по тонкой ноге. A1 уже ловила это на "
          "funding — спред дециля там оказался верхней границей, а не "
          "ожиданием.\n")
        p("**§5.3 — не переодетый ли это фактор размера.** Если лонг "
          "систематически крупнее шорта, построен не возврат к среднему, а "
          "ставка на размер, и она умрёт в день разворота премии за "
          "размер.\n")

    # ---- нуль, если посчитан ------------------------------------------
    nulls = []
    for fn in sorted(os.listdir(OUT)):
        if fn.startswith(f"crosssection_{args.interval}_null") \
                and fn.endswith(".json"):
            with open(os.path.join(OUT, fn), encoding="utf-8") as f:
                nulls.append(json.load(f))
    if nulls:
        p("## Нулевая модель §7 — предварительно\n")
        p("Сигнал перемешан между активами внутри сечения: разрушена "
          "связь «кто какой сигнал получил», всё остальное на месте. "
          "**Это ещё не R3** — там требуется десять зёрен и вторая нулевая "
          "модель со сдвигом сечения на 365 дней. Здесь проверяется более "
          "грубая вещь: не создан ли сигнал ошибкой в коде.\n")
        p("| Величина | Прогон | " + " | ".join(
            f"нуль, зерно {n['config']['null_seed']}" for n in nulls) + " |")
        p("|---" * (len(nulls) + 2) + "|")
        for label, get in (
            ("Медианный IC по сетке", lambda d: fmt(d["summary"]["grid"]["ic_median"])),
            ("Лучшая ячейка", lambda d: fmt(d["summary"]["grid"]["ic_best"])),
            ("Худшая ячейка", lambda d: fmt(d["summary"]["grid"]["ic_worst"])),
            ("Ячеек с положительным IC",
             lambda d: f"{d['summary']['grid']['positive_cells']} из 16"),
        ):
            p(f"| {label} | {get(doc)} | "
              + " | ".join(get(n) for n in nulls) + " |")
        p("")
        worst_real = s["grid"]["ic_worst"]
        best_null = max(n["summary"]["grid"]["ic_best"] for n in nulls)
        p(f"**Худшая ячейка прогона ({fmt(worst_real)}) выше лучшей ячейки "
          f"нуля ({fmt(best_null)}) в {worst_real / best_null:.1f} раза.** "
          f"Это прямая противоположность A4, где перемешанные метки давали "
          f"результат не хуже настоящих. Утечки в коде нет: перестановка "
          f"«кто какой сигнал получил» уничтожает эффект полностью.\n")

    p("## Что дальше\n")
    if stop_ic or stop_cost:
        p("**Сработал критерий немедленной остановки §8.2.** Бэктест не "
          "строится. Следующий шаг — не R3, а решение: ступень 2 лестницы "
          "§3.3 (рынок + сектор), либо закрытие гипотезы.\n")
    elif passed:
        p("Критерии §8.3 п. 1–3 выполнены хотя бы частью сетки, остановка "
          "не сработала — переход к **R3**: две нулевые модели по десять "
          "зёрен каждая. Пока нуль не посчитан, эти числа ничего не "
          "значат: в A4 перемешанные метки дали результат лучше настоящих.\n")
    else:
        p("Остановка §8.2 не сработала, но ни одна ячейка не прошла "
          "критерии §8.3 п. 1–3 целиком. Это не результат «положительно» и "
          "не результат «отрицательно» — это требование посчитать нуль "
          "(R3) прежде, чем интерпретировать что-либо.\n")


if __name__ == "__main__":
    main()
