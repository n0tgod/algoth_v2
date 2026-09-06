#!/usr/bin/env python3
"""Сглаживают ли короткие DCA-книги длинные — замер, а не имя.

Владелец завёл зеркальные короткие книги с одной названной целью:
«сглаживать лонг стратегии». Это ПРОВЕРЯЕМОЕ утверждение, и проверяется
оно не тем, что книга существует, а тем, как ведут себя деньги ДНЯ, когда
книги стоят рядом. Ровно тот же вопрос D2 задавал варианту «в» (отдельная
шорт-книга) и получил связь +0.066 — стороны шли слегка ВМЕСТЕ, то есть
не сглаживали. Там была другая конструкция (одиночный вход 1×), здесь
DCA, поэтому вопрос ставится заново — и ответ обязан быть числом.

Что считается, по каждой паре «режим × депозит»:
  - дневной ряд денег длинной книги, короткой и ОБЪЕДИНЁННОЙ (обе рядом,
    капитал вдвое: у каждой книги свой депозит, и складывать их проценты
    нельзя — считается доля от суммы депозитов);
  - связь дневных денег сторон (Пирсон по ОБЩИМ суткам). Сглаживание
    требует, чтобы стороны ходили ВРОЗЬ: связь около нуля даёт лишь
    разбавление, положительная не даёт ничего;
  - форма каждой из трёх книг тем же кодом, что считает книги
    (`run_paper._stats`): просадка, укус, медиана дня, доля зелёных.

Вердикт выводится ИЗ ЧИСЕЛ (правило проекта: вердиктовая фраза не стоит
рядом с числом, а следует из него): сглаживанием считается одновременное
улучшение просадки и укуса объединённой книги против длинной при не
ухудшившейся медиане дня. Иначе короткая книга либо разбавляет, либо
мешает — и это тоже говорится словами.

Оговорки, которые снимать нельзя:
  - шортов под гейтом 3.4 % (замер `short_supply.py`), то есть по весу
    короткая книга много легче; её вклад в объединённую кривую мал по
    построению, и «не помогло» может означать «не хватило веса»;
  - хвост сторон НЕ зеркален: у лонга убыток ограничен нулём цены, у
    шорта сверху ничем;
  - деньги обеих книг наполовину пересчёт по прошлому (веса модели
    видели эти часы) — оценка сверху, и группа «вперёд» печатается
    рядом.
"""

import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import rules as R                      # noqa: E402
import run_paper as P                  # noqa: E402

OUT = os.path.join(HERE, "out")


def series(rows):
    """Дневной ряд денег: сутки UTC → доллары."""
    day = {}
    for r in rows:
        d = time.strftime("%Y-%m-%d", time.gmtime(float(r["exit_ts"])))
        day[d] = day.get(d, 0.0) + float(r["usd"])
    return day


def corr(a, b):
    """Связь дневных денег по ОБЩИМ суткам. Меньше трёх — меры нет.

    Ноль здесь означал бы «связи нет», а не «мерить не на чем», поэтому
    короткое пересечение возвращает None.
    """
    ks = sorted(set(a) & set(b))
    if len(ks) < 3:
        return None, len(ks)
    x = np.array([a[k] for k in ks], dtype=float)
    y = np.array([b[k] for k in ks], dtype=float)
    if x.std() == 0 or y.std() == 0:
        return None, len(ks)
    return float(np.corrcoef(x, y)[0, 1]), len(ks)


def pair_rows(rows, mode, dep):
    """Строки длинной и короткой книг одного режима и депозита."""
    def take(rk):
        return [r for r in rows if int(r.get("dep", 0)) == int(dep)
                and R.is_current(r)
                and R.ruler_of(r) == rk]
    return take(mode), take(mode + "_s")


def cell(rows, mode, dep):
    """Три книги рядом: длинная, короткая и обе вместе."""
    lo, sh = pair_rows(rows, mode, dep)
    if not lo or not sh:
        return {"mode": mode, "dep": dep, "n_long": len(lo),
                "n_short": len(sh), "why": "одной из сторон нет вовсе"}
    both = lo + sh
    c, common = corr(series(lo), series(sh))
    s_lo = P._stats(lo, dep)
    s_sh = P._stats(sh, dep)
    # У объединённой книги капитал ВДВОЕ: это две книги рядом, а не одна
    # с удвоенным оборотом. Делить их сумму на один депозит значило бы
    # приписать паре доходность, которой у неё нет.
    s_bo = P._stats(both, 2.0 * dep)
    return {"mode": mode, "dep": dep, "n_long": len(lo), "n_short": len(sh),
            "corr": (None if c is None else round(c, 3)),
            "common_days": common,
            "long": s_lo, "short": s_sh, "both": s_bo,
            # Сглаживание = просадка и укус объединённой книги лучше, чем
            # у длинной, при не ухудшившейся медиане дня. Все три условия
            # разом: одна просадка мельче бывает просто от того, что
            # книга вложила меньше (урок нуля 4 из S1).
            "smoother": bool(
                s_bo and s_lo
                and s_bo["max_dd"] > s_lo["max_dd"]
                and (s_bo.get("bite") is not None and s_lo.get("bite")
                     is not None and s_bo["bite"] < s_lo["bite"])
                and s_bo["day_median"] >= s_lo["day_median"])}


def collect():
    # `read_journal` отдаёт ПАРУ (строки, битых): взяв её целиком, замер
    # получал бы список и число вместо строк и падал на первой же
    # `r.get`. Дорога до чтения журнала не исполнялась ни одним тестом —
    # проверки звали `cell` с готовыми словарями.
    rows, bad = R.read_journal()
    out = []
    for mode in [k for k in R.RULER_ORDER if R.side_of(k) == "long"]:
        for dep in R.DEPOSITS:
            out.append(cell(rows, mode, dep))
    return out, bad


def _p(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} %"


def report(cells):
    L = ["# Сглаживают ли короткие DCA-книги длинные\n"]
    L.append("Замер названной владельцем цели. Сглаживание есть "
             "утверждение о СВЯЗИ дневных денег сторон, и само по себе "
             "зеркало его не даёт: книга рядом может разбавлять, мешать "
             "или помогать — различают эти случаи числа.\n")
    L.append("Считается по каждой паре «режим × депозит»: связь дневных "
             "денег сторон (Пирсон, общие сутки) и форма трёх книг — "
             "длинной, короткой и ОБЕИХ РЯДОМ. У объединённой капитал "
             "вдвое: это две книги, а не одна.\n")
    ok = [c for c in cells if c.get("why") is None]
    if not ok:
        L.append("**Мерить нечего:** у книг нет обеих сторон. "
                 + "; ".join(f"{c['mode']}/{c['dep']:.0f}: {c['why']} "
                             f"(лонг {c['n_long']}, шорт {c['n_short']})"
                             for c in cells) + "\n")
        return "\n".join(L) + "\n"
    L.append("| режим | депозит | сделок Л/Ш | связь дней | итог Л | "
             "итог Ш | итог обе | просадка Л | просадка обе | укус Л | "
             "укус обе | медиана дня Л | медиана дня обе | сглаживает |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|")
    for c in ok:
        lo, sh, bo = c["long"], c["short"], c["both"]
        L.append(
            f"| {R.ruler_title(c['mode'])} | ${c['dep']:,.0f} | "
            f"{c['n_long']}/{c['n_short']} | "
            f"{'—' if c['corr'] is None else format(c['corr'], '+.3f')} | "
            f"{_p(lo['final'])} | {_p(sh['final'])} | {_p(bo['final'])} | "
            f"{_p(lo['max_dd'])} | {_p(bo['max_dd'])} | "
            f"{lo['bite'] if lo['bite'] is not None else '—'} | "
            f"{bo['bite'] if bo['bite'] is not None else '—'} | "
            f"{_p(lo['day_median'], 3)} | {_p(bo['day_median'], 3)} | "
            f"{'да' if c['smoother'] else 'нет'} |")
    n_sm = sum(1 for c in ok if c["smoother"])
    cs = [c["corr"] for c in ok if c["corr"] is not None]
    med_c = (round(float(np.median(cs)), 3) if cs else None)
    L.append("")
    # Вердикт ВЫВОДИТСЯ из чисел, а не стоит рядом с ними.
    L.append(f"Сглаживает в **{n_sm} ячейках из {len(ok)}**; медианная "
             f"связь дневных денег сторон "
             f"**{'—' if med_c is None else format(med_c, '+.3f')}**.\n")
    if med_c is not None and med_c > 0.2:
        L.append("Связь ПОЛОЖИТЕЛЬНА: стороны ходят вместе, и книга рядом "
                 "сглаживать не может по построению — она добавляет тот "
                 "же риск помельче.\n")
    elif med_c is not None and med_c < -0.2:
        L.append("Связь ОТРИЦАТЕЛЬНА: стороны ходят врозь — это и есть "
                 "механизм, которого требует сглаживание. Величину его "
                 "пользы читать по колонкам просадки и укуса, а не по "
                 "самой связи.\n")
    else:
        L.append("Связь около нуля: стороны почти независимы. Это даёт "
                 "РАЗБАВЛЕНИЕ (риск делится между двумя книгами), а не "
                 "сглаживание; заметным оно станет только если веса "
                 "сторон сопоставимы, а шортов под гейтом 3.4 %.\n")
    L.append("Чего эти числа не описывают: шортов под гейтом втрое "
             "меньше процента от длинных, то есть по весу короткая книга "
             "легче — «не помогло» может означать «не хватило веса». "
             "Хвост сторон не зеркален: у лонга убыток ограничен нулём "
             "цены, у шорта сверху ничем. И деньги обеих книг наполовину "
             "пересчёт по прошлому — оценка сверху.\n")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    cells, bad = collect()
    if bad:
        print(f"битых строк журнала: {bad}")
    for c in cells:
        if c.get("why"):
            print(f"{c['mode']}/{c['dep']:.0f}: {c['why']} "
                  f"(лонг {c['n_long']}, шорт {c['n_short']})")
        else:
            print(f"{c['mode']}/{c['dep']:.0f}: связь {c['corr']}, "
                  f"сглаживает {c['smoother']}")
    path = os.path.join(OUT, f"DCA-smoothing-{a.tag}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report(cells))
    print("отчёт:", path)
    if not a.no_publish:
        os.system(f"bash {os.path.join(HERE, '..', '..', 'tools', 'publish.sh')}"
                  f" 'DCA: сглаживают ли короткие книги длинные'")


if __name__ == "__main__":
    main()
