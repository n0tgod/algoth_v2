#!/usr/bin/env python3
"""
Отчёт M2 из готовой сводки. Стандартная библиотека намеренно (урок R1):
отчёт собирается на любой машине из самого артефакта.

    python3 research/m2_walkforward/report.py out/m2_summary_1m.json
"""

import json
import sys


def _f(v, d=4):
    return "—" if v is None else f"{v:+.{d}f}"


def render(s):
    v = s.get("verdict", {})
    n3 = s.get("null3", {})
    tag = f", {s['tag']}" if s.get("tag") else ""

    lines = [f"# M2 — walk-forward, модель против одиночного признака "
             f"(1m{tag})", "",
             f"Гипотеза 6, спека 07, этап M2. Окно оценки с "
             f"{s['eval_start']}, деревьев {s['trees']}.", ""]

    lines += ["## Нуль 3 — обучение на перемешанных форвардах "
              "(считается ПЕРВЫМ)", "",
              "Модель, обученная на шуме, — одна случайная функция "
              "признаков; её проекция на настоящий сигнал даёт ±0.01 на "
              "зерно (замерено смоуком двумя видами перестановки). "
              "Подпись утечки — не большое зерно, а согласованный сдвиг "
              "всех зёрен: t сдвига.", "",
              "| h | медиана по зёрнам | среднее ± SE | t сдвига | "
              "худшее зерно | зёрен |", "|---|---|---|---|---|---|"]
    for h, r in sorted(n3.items()):
        lines.append(f"| {h} | {_f(r['median'])} | {_f(r.get('mean'))} ± "
                     f"{r.get('se', 0):.4f} | {r.get('t_shift', 0):+.1f} | "
                     f"{r['worst_abs']:.4f} | {len(r['medians'])} |")
    if v.get("null3_leak"):
        lines += ["", "**КОНВЕЙЕР ТЕЧЁТ — зёрна согласованно сдвинуты, "
                  "сетка не считалась, числа ниже отсутствуют.**"]

    cells = s.get("cells", {})
    if cells:
        lines += ["", "## Сетка 8 ячеек", "",
                  "IC — Спирмен по непересекающимся сечениям. «Признак» — "
                  "лучший одиночный признак, отобранный тем же "
                  "walk-forward; «−ret_7» — возврат R2 в лоб, диагностика.",
                  "",
                  "| ячейка | IC модели | t | доля+ | сечений | IC признака "
                  "| разность | −ret_7 | обучений | с |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for name, c in cells.items():
            m, sg = c["model"], c["single"]
            lines.append(
                f"| {name} | {_f(m['median'])} | {m['t']:.1f} | "
                f"{m['share_pos']:.2f} | {m['n']} | {_f(sg['median'])} | "
                f"**{_f(c['delta_median'])}** | "
                f"{_f(c['fixed_ret7']['median'])} | {c['n_fits']} | "
                f"{c['sec']:.0f} |")

        lines += ["", "### Что выбирала рука одиночного признака", ""]
        for name, c in cells.items():
            top = sorted(c["picked"].items(), key=lambda kv: -kv[1])[:3]
            lines.append(f"- {name}: " + ", ".join(
                f"`{k}` ({n} дней)" for k, n in top))

    imp = s.get("importance", {})
    if imp:
        lines += ["", "## Важность признаков (обучение на окне до оценки)",
                  "",
                  "Суммарный вклад разрезов, доли единицы. Модель, чей "
                  "результат нельзя разложить по признакам, нельзя и "
                  "оспорить (§9 спеки).", ""]
        for h, d in sorted(imp.items()):
            top = list(d.items())[:8]
            lines.append(f"- h={h}: " + ", ".join(
                f"`{k}` {val:.3f}" for k, val in top))

    if "c1_median_ic" in v:
        rows = [
            ("1. медианный IC по ячейкам ≥ 0.02",
             f"{v['c1_median_ic']:+.4f}", v["c1_pass"]),
            ("2. медианное превышение над признаком ≥ +0.005",
             f"{v['c2_median_delta']:+.4f}", v["c2_pass"]),
            (f"3. t медианной ячейки ({v['c3_cell']}) ≥ 3",
             f"{v['c3_t']:.1f}", v["c3_pass"]),
            ("4. доля положительных сечений ≥ 0.60",
             f"{v['c4_share_pos']:.2f}", v["c4_pass"]),
            ("5. непересекающихся сечений ≥ 100",
             str(v["c5_min_sections"]), v["c5_pass"]),
            ("7. нуль 3: без согласованного сдвига зёрен (|t| ≤ 3)",
             "да" if v.get("null3_pass") else "нет", v.get("null3_pass")),
        ]
        lines += ["", "## Критерии §8 (измеримые на M2)", "",
                  "| критерий | значение | вердикт |", "|---|---|---|"]
        for name, val, ok in rows:
            lines.append(f"| {name} | {val} | "
                         f"{'выполнен' if ok else 'НЕ выполнен'} |")
        lines += ["", "Критерии 6 (нуль 1), 8–9 (Sharpe, экономика) — "
                  "этапы M3–M4."]
        if v.get("stop_no_cell_beats_single"):
            lines += ["", "**НЕМЕДЛЕННАЯ ОСТАНОВКА §8: модель не "
                      "превосходит одиночный признак ни в одной ячейке — "
                      "гипотеза умирает дёшево, M3–M4 не считаются.**"]

    b = s.get("budget", {})
    if b:
        lines += ["", "## Бюджет", "",
                  f"Обучений {b['fits']}, среднее "
                  f"{b['fit_sec_mean']} с, максимум {b['fit_sec_max']} с, "
                  f"весь прогон {b['total_sec'] / 3600:.1f} ч."]
    return "\n".join(lines) + "\n"


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        print(render(json.load(f)))


if __name__ == "__main__":
    main()
