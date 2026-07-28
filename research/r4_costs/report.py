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


def split_arms(cells):
    """Ячейки по рукам прогона: чистый остаток, он же на суженном
    универсуме, комбинация с funding.

    Разделять обязательно: без этого «медиана нетто по сетке» считалась
    бы по смеси трёх книг, и любое улучшение одной руки размывалось бы
    двумя остальными. Базовые таблицы отчёта строятся по руке `resid`,
    то есть остаются тем же, чем были до итерации 1.
    """
    out = {"resid": {}, "resid_r": {}, "blend": {}}
    for k, v in cells.items():
        if k.endswith("_blend"):
            out["blend"][k[:-len("_blend")]] = v
        elif k.endswith("_resid_r"):
            out["resid_r"][k[:-len("_resid_r")]] = v
        else:
            out["resid"][k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--blend-funding", action="store_true",
                    help="читать артефакт рычага 2 §12.3")
    args = ap.parse_args()
    tag = "_blend" if args.blend_funding else ""
    path = os.path.join(OUT, f"costs_{args.interval}{tag}.json")
    if not os.path.exists(path):
        raise SystemExit(f"нет {path} — сначала run.py --interval "
                         f"{args.interval}")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    cfg, rules = doc["config"], doc["rules"]
    blend_run = bool(cfg.get("blend_funding"))
    arms = {r: split_arms(c) for r, c in rules.items()}
    if blend_run:
        # Дальше по отчёту `rules[rule]` означает базовую руку: все
        # прежние таблицы обязаны остаться сравнимыми с прогоном до
        # итерации 1, иначе сравнивать будет не с чем.
        rules = {r: a["resid"] for r, a in arms.items()}
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


    # --- рычаг 2 итерации 1 ---------------------------------------------
    if blend_run:
        a = arms["expected"]
        res, resr, bl = a["resid"], a["resid_r"], a["blend"]
        keys = sorted(set(resr) & set(bl))
        p("## 4а. Рычаг 2 итерации 1 — funding вторым сигналом (§12.3)\n")
        cv = cfg.get("score_coverage") or {}
        p(f"**Оценка:** минус средняя суточная ставка за окно формирования "
          f"({cfg.get('form_days')} дней), комбинация — среднее рангов с "
          f"весом {cfg.get('blend_weight')}. Вес объявлен один и не "
          f"перебирается: перебор был бы новым измерением сетки.\n")
        p(f"**Покрытие оценки:** медиана {cv.get('median', float('nan')):.3f}, "
          f"минимум {cv.get('min', float('nan')):.3f} по "
          f"{cv.get('dates', 0)} датам. Согласие двух прочиток «средней "
          f"ставки» (за сутки против за начисление): "
          f"{cfg.get('score_reading_agreement'):.4f}.\n")
        p("Сравнивать комбинацию с ПОЛНОЙ чистой книгой нельзя: "
          "`blend_ranks` выбрасывает актив без одного из двух сигналов, "
          "поэтому у комбинированной книги универсум уже. Разница тогда "
          "включала бы эффект сужения. Колонка «остаток, суженный» — тот "
          "же чистый остаток на том же универсуме, и честное сравнение "
          "идёт против неё.\n")
        p("| Ячейка | IC остаток | IC суж. | IC комб. | Funding суж., б.п. "
          "| Funding комб., б.п. | Нетто суж., б.п. | Нетто комб., б.п. |")
        p("|---|---|---|---|---|---|---|---|")
        for k in keys:
            c0, c1, c2 = res.get(k), resr[k], bl[k]
            p(f"| {k} | {f(c0['ic_median'], 4) if c0 else '—'} "
              f"| {f(c1['ic_median'], 4)} | {f(c2['ic_median'], 4)} "
              f"| {bp(c1['funding']['mean'])} | {bp(c2['funding']['mean'])} "
              f"| {bp(c1['net']['mean'])} | {bp(c2['net']['mean'])} |")
        p("")
        fr = median([c["funding"]["mean"] for c in resr.values()])
        fb = median([c["funding"]["mean"] for c in bl.values()])
        ir = median([c["ic_median"] for c in resr.values()
                     if c["ic_median"] is not None])
        ib = median([c["ic_median"] for c in bl.values()
                     if c["ic_median"] is not None])
        nr = median([c["net"]["mean"] for c in resr.values()])
        nb = median([c["net"]["mean"] for c in bl.values()])
        p(f"Медианы по сетке: **funding {bp(fr)} → {bp(fb)} б.п.**, "
          f"**IC {f(ir, 4)} → {f(ib, 4)}**, **нетто {bp(nr)} → {bp(nb)} б.п.**\n")
        p("### Критерий немедленной остановки §12.6, условие 3\n")
        p("> Funding-издержка книги при комбинированном сигнале против "
          "чистого остатка: **не ниже** — работа прекращается.\n")
        drop = fb < fr
        p(f"Получено: **{bp(fr)} → {bp(fb)} б.п.** — "
          f"{'издержка упала, условие НЕ сработало' if drop else 'издержка НЕ упала, условие СРАБОТАЛО'}.\n")
        p("Это прямая проверка механизма, а не косвенный признак. R4 "
          "намерил, что книга систематически платит funding: длинная нога "
          "— активы, отставшие от волны, — имеет ставку выше короткой. "
          "Сигнал по funding тянет отбор в противоположную сторону и "
          "обязан этот перекос уменьшать. Если издержка не упала, "
          "механизм понят неверно, и улучшение любых других чисел было бы "
          "совпадением.\n")
        p("**Цена рычага, объявленная §12.4 до прогона:** испытаний "
          "становится 192 вместо 96, поправка растёт с 1.195 до 1.307, то "
          "есть планка поднимается на **0.112 Sharpe**. Комбинация, "
          "давшая меньше, вредна — даже когда её собственные числа "
          "выглядят лучше.\n")

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
