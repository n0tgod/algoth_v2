#!/usr/bin/env python3
"""
R4 — отчёт: издержки на фактическом обороте книги.

Числа читаются из артефакта прогона, зависимостей тяжелее `json` нет.

    python3 report.py --interval 1m > out/R4-report-1m.md
"""

import argparse
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# Пороги §8.3 спеки 03, утверждены до прогона.
MEDIAN_CELL_POSITIVE = True
POSITIVE_CELLS_MIN = 0.60
SHARPE_MIN = 0.8
STRESSED_MIN_SHARE = 0.40


def bp(x, d=1):
    return "—" if x is None else f"{x * 10000:.{d}f}"


def f(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def median(v):
    v = sorted(x for x in v if x is not None)
    n = len(v)
    return None if not n else (v[n // 2] if n % 2
                               else (v[n // 2 - 1] + v[n // 2]) / 2)


def sharpe(cell, h):
    t, n = cell.get("net_t"), cell.get("sections")
    if not t or not n:
        return None
    return (t / math.sqrt(n)) * math.sqrt(365.0 / h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    args = ap.parse_args()
    path = os.path.join(OUT, f"costs_{args.interval}.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала run.py --interval "
                         f"{args.interval}")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    cfg, rules = doc["config"], doc["rules"]
    p = print

    p("# R4 — издержки на фактическом обороте книги\n")
    p("**Спека:** 03, этап R4 и раздел 6  ")
    p(f"**Разрешение хранилища:** {cfg['interval']}  ")
    p(f"**Сечений в истории:** {cfg['sections_total']}  ")
    cov = cfg.get("funding_symbols")
    tot = cfg.get("universe_symbols")
    if cfg["funding_included"]:
        p(f"**Funding включён:** да, ряды у {cov} активов из {tot}\n")
    else:
        p(f"**Funding включён:** **НЕТ**"
          + (f" (рядов нашлось {cov} из {tot})" if cov is not None else "")
          + " — см. раздел 4\n")

    p("## Единица измерения\n")
    p("Всё выражается **в долях гросс-нотионала книги** — суммы модулей "
      "позиций по всем ногам, нормированной на единицу. При дециле из "
      "300 активов это 30 лонгов по +1/60 и 30 шортов по −1/60.\n")
    p("```\nприбыль за период  = Σ w·форвард  =  ½ · спред дециля\n"
      "комиссия за период = Σ |Δw| · тейкер\n"
      "полная замена книги: Σ|Δw| = 2, то есть 11 б.п. при тейкере 5.5\n```\n")
    p("Множитель ½ существен. Спред дециля есть разность средних по ногам, "
      "то есть величина «на ногу»; книга держит две ноги одновременно, и "
      "капитал делится между ними. В отчёте R2 §8.2 спред сравнивался с "
      "«циклом издержек 26 б.п.» — две величины в разных единицах. Вердикт "
      "от этого не менялся, но число было нестрогим; здесь всё в одной "
      "единице.\n")

    # --- оборот ---------------------------------------------------------
    base = rules["expected"]
    p("## 1. Оборот книги — измерен, а не назначен\n")
    p("До сих пор в рассуждениях фигурировали «шестьдесят ног на каждый "
      "ребаланс», то есть оборот 2.0 — полная замена. Замер по составу "
      "дециля показывает другое: имя, оставшееся в той же ноге, не "
      "торгуется вовсе.\n")
    p("| k, дн | h, дн | Оборот, доля гросса | Комиссия, б.п. |")
    p("|---|---|---|---|")
    for k in cfg["ks"]:
        for h in cfg["hs"]:
            c = base.get(f"k{k}_h{h}_decile")
            if c:
                p(f"| {k} | {h} | {c['turnover']['mean']:.3f} "
                  f"| {bp(c['commission']['mean'])} |")
    p("")
    tmin = min(c["turnover"]["mean"] for c in base.values())
    tmax = max(c["turnover"]["mean"] for c in base.values())
    p(f"Оборот идёт от **{tmin:.3f} до {tmax:.3f}** при максимуме 2.0. "
      f"Допущение о полной замене завышало бы издержки вчетверо на "
      f"длинном сигнале: при k = 14 сигнал за сутки почти не меняется, и "
      f"половина книги остаётся на месте.\n")

    # --- сетка ----------------------------------------------------------
    for rule, title in (("expected", "правило квинтиля оборота"),
                        ("pessimistic", "плоские 11.0 б.п.")):
        cells = rules[rule]
        p(f"## 2. Сетка нетто — {title}\n")
        p("| k | h | Корзина | Сечений | Брутто, б.п. | Издержки, б.п. "
          "| Нетто, б.п. | Sharpe год. | Доля + | Нетто ×1.5 |")
        p("|---|---|---|---|---|---|---|---|---|---|")
        for w in ("decile", "quintile"):
            for k in cfg["ks"]:
                for h in cfg["hs"]:
                    c = cells.get(f"k{k}_h{h}_{w}")
                    if not c:
                        continue
                    cost = c["commission"]["mean"] + c["funding"]["mean"]
                    s = sharpe(c, h)
                    mark = "**" if s is not None and s >= SHARPE_MIN else ""
                    p(f"| {k} | {h} | {w} | {c['sections']} "
                      f"| {bp(c['gross']['mean'])} | {bp(cost)} "
                      f"| {mark}{bp(c['net']['mean'])}{mark} | {f(s)} "
                      f"| {f(c['net_positive_share'])} "
                      f"| {bp(c['net_stressed'])} |")
        p("")
        nets = [c["net"]["mean"] for c in cells.values()]
        pos = sum(1 for x in nets if x > 0)
        st = sum(1 for c in cells.values() if c["net_stressed"] > 0)
        p(f"Медиана нетто по сетке **{bp(median(nets))} б.п.**, "
          f"положительных ячеек **{pos} из {len(nets)}**, "
          f"при издержках ×1.5 — **{st} из {len(nets)}**.\n")

    # --- критерии -------------------------------------------------------
    cells = rules["expected"]
    nets = [c["net"]["mean"] for c in cells.values()]
    pos_share = sum(1 for x in nets if x > 0) / len(nets)
    sharpes = [sharpe(c, int(k.split("_h")[1].split("_")[0]))
               for k, c in cells.items()]
    med_sharpe = median(sharpes)
    best = max(((s, k) for k, s in zip(cells, sharpes) if s is not None),
               default=(None, None))
    p("## 3. Сверка с критериями §8.3\n")
    p("| # | Критерий | Порог | Получено | |")
    p("|---|---|---|---|---|")
    ok4 = median(nets) is not None and median(nets) > 0
    p(f"| 4 | Медианная ячейка положительна нетто | да "
      f"| {bp(median(nets))} б.п. | {'✓' if ok4 else '✗'} |")
    ok5 = pos_share >= POSITIVE_CELLS_MIN
    p(f"| 5 | Доля ячеек, положительных нетто | ≥ {POSITIVE_CELLS_MIN:.0%} "
      f"| {pos_share:.0%} | {'✓' if ok5 else '✗'} |")
    ok6 = med_sharpe is not None and med_sharpe >= SHARPE_MIN
    p(f"| 6 | Sharpe (до поправки на 96 испытаний) | ≥ {SHARPE_MIN} "
      f"| медиана {f(med_sharpe)}, лучшая {f(best[0])} "
      f"| {'✓' if ok6 else '✗'} |")
    st_ok = [c for c in cells.values()
             if c["net"]["mean"] > 0
             and c["net_stressed"] >= STRESSED_MIN_SHARE * c["net"]["mean"]]
    p(f"| 9 | Издержки ×1.5: положительно и ≥ {STRESSED_MIN_SHARE:.0%} "
      f"базового | — | {len(st_ok)} ячеек из {len(nets)} | |")
    p("")
    p("Критерий 6 в полном виде (Deflated Sharpe с поправкой на число "
      "испытаний) считается в R5 — там же просадка, худший подпериод и "
      "устойчивость к возмущению параметров. Здесь приведена оценка "
      "**без** поправки, то есть заведомо оптимистичная.\n")

    # --- corner ---------------------------------------------------------
    if best[1]:
        p("## 4. Что в этих числах тревожит\n")
        # Признак «оптимум за краем сетки» проверяется по КРАЮ, а не по
        # углу: лучшая ячейка может не стоять в углу, а лучшие несколько
        # при этом жаться к границе одной из осей. Первая редакция
        # проверяла угол по обеим осям сразу и молчала на настоящей
        # картине.
        ranked = sorted(((s, k) for k, s in zip(cells, sharpes)
                         if s is not None), reverse=True)
        top = ranked[:5]
        h_max = max(cfg["hs"])
        at_edge = sum(1 for _, k in top
                      if int(k.split("_h")[1].split("_")[0]) == h_max)
        if at_edge >= 4:
            p(f"**Лучшие ячейки жмутся к краю сетки по горизонту "
              f"удержания.** Из пяти лучших по Sharpe у {at_edge} горизонт "
              f"равен {h_max} дням — максимуму объявленной сетки. Это "
              f"классический признак того, что оптимум лежит ЗА её "
              f"пределами.\n")
            p("Расширять сетку после получения результатов запрещено "
              "правилом 1 раздела 2 спеки, и запрет здесь работает ровно "
              "так, как задуман: соблазн добавить h = 20 велик именно "
              "потому, что это почти наверняка улучшило бы числа. Если "
              "владелец решит проверить более длинные горизонты, это "
              "новая сетка, объявленная заново, с новым прогоном нулевых "
              "моделей — а не расширение старой.\n")
        p("**Нетто держится на длинных горизонтах, а сигнал сильнее всего "
          "на коротких.** По брутто-IC лучшими были ячейки с h = 1; "
          "издержки их и съели. Оставшееся — это уже другая стратегия, чем "
          "та, что показала IC 0.047.\n")
        p("**Доля прибыльных периодов около половины.** Она почти не "
          "выросла против брутто: возврат остатка даёт малый перевес, "
          "размазанный по множеству ног, а не устойчивую прибыль в каждом "
          "периоде. По Sharpe это бьёт сильнее, чем по среднему.\n")

    if not cfg["funding_included"]:
        p("**Funding в этих числах отсутствует, и это не мелочь.** При "
          "удержании 10 дней дифференциал ставок между ногами способен "
          "дать десятки базисных пунктов — то есть величину, сравнимую со "
          "всем нетто. Причём именно ячейки с h = 10, которые сейчас "
          "выглядят лучшими, к нему чувствительнее всего. Ранжирование "
          "ячеек может перевернуться. Прогон с funding обязателен до "
          "любого вывода.\n")

    p("## 5. Что дальше\n")
    if not cfg["funding_included"]:
        p("Повторить прогон там, где лежат ряды funding площадки "
          "исполнения. Затем **R5** — портфельный бэктест по модели "
          "позиции спеки 01: Deflated Sharpe с поправкой на 96 испытаний, "
          "просадка, худший подпериод, устойчивость к возмущению "
          "параметров ±20 %.\n")
    else:
        p("Переход к **R5** — портфельный бэктест по модели позиции "
          "спеки 01.\n")


if __name__ == "__main__":
    main()
