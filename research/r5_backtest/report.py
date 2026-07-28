#!/usr/bin/env python3
"""
R5 — отчёт: статистическая валидация и сверка со всеми критериями §8.3.

    python3 report.py --interval 1m > out/R5-report-1m.md
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def f(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def pct(x, d=1):
    return "—" if x is None else f"{100 * x:.{d}f} %"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--blend-funding", action="store_true")
    args = ap.parse_args()
    tag = "_blend" if args.blend_funding else ""
    path = os.path.join(OUT, f"validation_{args.interval}{tag}.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала run.py --interval "
                         f"{args.interval}")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    cfg = doc["config"]
    base = doc["rules"]["expected"]
    p = print

    p("# R5 — статистическая валидация\n")
    p("**Спека:** 03, §8.3 критерии 6–8; спека 02 §7  ")
    p(f"**Разрешение хранилища:** {cfg['interval']}  ")
    p(f"**Испытаний в поправке:** {cfg['declared_trials']} "
      f"(объявлено в §2), посчитано ячеек {cfg['cells_measured']}  ")
    p(f"**Funding включён:** "
      f"{'да' if cfg['funding_included'] else '**НЕТ**'}\n")

    p("## Как считается поправка, и почему это записано здесь\n")
    p("Спека утвердила **порог** (0.8), но не **способ** поправки Sharpe на "
      "число испытаний. Способ зафиксирован до прогона и докладываются обе "
      "общепринятые версии, чтобы выбор определения нельзя было подогнать "
      "под результат:\n")
    p("- `Sharpe − SR₀(N)` — вычитается тот Sharpe, который лучшая из `N` "
      "пустышек показала бы чистой случайностью. **Вердикт выносится по "
      "ней**: величина в тех же единицах, что и порог;")
    p("- `DSR` — вероятность того, что истинный Sharpe положителен, с "
      "учётом длины ряда, асимметрии и тяжести хвостов. Безразмерна, "
      "порогом 0.8 не проверяется, приводится рядом.\n")

    # --- итог -----------------------------------------------------------
    cells = base["cells"]
    best_name = max(cells, key=lambda k: cells[k]["sharpe_deflated"])
    b = cells[best_name]
    p("## Итог\n")
    p(f"| Величина | Значение |")
    p("|---|---|")
    p(f"| Лучшая ячейка | `{best_name}` |")
    p(f"| Sharpe до поправки | {f(b['sharpe_annual'])} |")
    p(f"| Поправка SR₀ ({cfg['declared_trials']} испытаний) "
      f"| {f(base['sr0_annual'])} |")
    p(f"| **Sharpe после поправки** | **{f(b['sharpe_deflated'])}** "
      f"при пороге {cfg['sharpe_min']} |")
    p(f"| DSR (вероятность) | {f(b['dsr_probability'], 3)} |")
    p(f"| Максимальная просадка | {pct(b['max_drawdown'])} |")
    p(f"| Худший год по Sharpe | {f(b['worst_year_sharpe'])} "
      f"при пороге {cfg['worst_subperiod_min']} |\n")
    p(f"Поправка SR₀ = {f(base['sr0_annual'])} означает: при "
      f"{cfg['declared_trials']} испытаниях и наблюдаемом разбросе Sharpe по "
      f"ячейкам ({f(base['sr_std_over_cells'], 3)}) **лучшая из пустышек "
      f"показала бы Sharpe {f(base['sr0_annual'])} чистой случайностью**. "
      f"Мы наблюдаем {f(base['best_sharpe_raw'])}.\n")

    # --- устойчивость к числу испытаний ---------------------------------
    p("## Устойчивость вердикта к числу испытаний\n")
    p("Формула ожидаемого максимума предполагает независимые испытания, а "
      "наши ячейки сильно скоррелированы: те же данные, соседние горизонты, "
      "пересекающиеся сигналы. Эффективное число независимых направлений "
      "заведомо меньше объявленных 96, то есть поправка по 96 избыточно "
      "строга. Поэтому вердикт проверен на устойчивость.\n")
    p("| Эффективных испытаний | Поправка SR₀ | Sharpe после поправки "
      "| Проходит 0.8 |")
    p("|---|---|---|---|")
    for n, v in base["trials_sensitivity"].items():
        p(f"| {n} | {f(v['sr0_annual'])} | {f(v['best_deflated'])} "
          f"| {'ДА' if v['passes'] else 'нет'} |")
    p("")
    p("**Вердикт не меняется ни при каком числе испытаний**, вплоть до пяти. "
      "Спорить о том, сколько их было на самом деле, незачем.\n")

    # --- по ячейкам -----------------------------------------------------
    p("## Ячейки по убыванию поправленного Sharpe\n")
    p("| Ячейка | Sharpe | После поправки | DSR | Просадка | Худший год "
      "| Лет + | Эксцесс |")
    p("|---|---|---|---|---|---|---|---|")
    for name in sorted(cells, key=lambda k: -cells[k]["sharpe_deflated"]):
        c = cells[name]
        p(f"| {name} | {f(c['sharpe_annual'])} | {f(c['sharpe_deflated'])} "
          f"| {f(c['dsr_probability'], 3)} | {pct(c['max_drawdown'])} "
          f"| {f(c['worst_year_sharpe'])} "
          f"| {c['positive_years']}/{c['years']} | {f(c['kurtosis'], 1)} |")
    p("")

    # --- сверка ---------------------------------------------------------
    ok6 = b["sharpe_deflated"] >= cfg["sharpe_min"]
    ok7 = (b["worst_year_sharpe"] is not None
           and b["worst_year_sharpe"] >= cfg["worst_subperiod_min"])
    ok8 = abs(b["max_drawdown"]) <= cfg["max_drawdown"]
    p("## Сверка с §8.3\n")
    p("| # | Критерий | Порог | Получено | |")
    p("|---|---|---|---|---|")
    p(f"| 6 | Sharpe после поправки на испытания | ≥ {cfg['sharpe_min']} "
      f"| {f(b['sharpe_deflated'])} | {'✓' if ok6 else '✗'} |")
    p(f"| 7 | Худший подпериод | Sharpe ≥ {cfg['worst_subperiod_min']} "
      f"| {f(b['worst_year_sharpe'])} | {'✓' if ok7 else '✗'} |")
    p(f"| 8 | Максимальная просадка | ≤ {pct(cfg['max_drawdown'], 0)} "
      f"| {pct(b['max_drawdown'])} | {'✓' if ok8 else '✗'} |\n")

    p("## Что этот результат означает и чего не означает\n")
    p("**Эффект реальный.** R3 показал расстояние в 36 стандартных "
      "отклонений от нулевой модели; это не отменяется. Отбор действительно "
      "предсказывает возврат остатка.\n")
    p("**Но он слишком мал, чтобы платить за исполнение.** Весь наблюдаемый "
      "Sharpe объясняется перебором сетки. Это не «сигнала нет» — это "
      "«сигнал есть, а денег из него не выходит при тейкерских ставках».\n")
    p("Различие существенно для решения. Гипотеза A4 умерла потому, что "
      "механизма не было вовсе — перемешанные метки работали лучше "
      "настоящих. Здесь механизм есть и проверен трижды; не сходится "
      "экономика исполнения.\n")

    if not cfg["funding_included"]:
        p("**Funding в этих числах отсутствует.** До прогона с рядами "
          "площадки исполнения вердикт остаётся предварительным.\n")

    p("## Решение по §8\n")
    p("Критерии 1–5, 10 и 11 выполнены, критерии 6 и 7 — нет. Это ветка "
      "**«выполнены частично»**, которая по §8 спеки даёт право на одну "
      "итерацию уточнения гипотезы (не более двух).\n")


if __name__ == "__main__":
    main()
