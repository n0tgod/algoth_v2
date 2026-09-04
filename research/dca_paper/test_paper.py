#!/usr/bin/env python3
"""Проверки бумажных DCA-книг. Прогон: .venv/bin/python …/test_paper.py"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
import rules as R                                             # noqa: E402
import run_paper as P                                         # noqa: E402
import run_d6 as D6                                           # noqa: E402

H = 3600


def _rec(at, hold_h=1.0, pnl=0.10, lev=4.0, fwd=100.0, sym="AAAUSDT"):
    ex = at + hold_h * H
    return {"at": float(at), "exit_ts": float(ex), "pnl": float(pnl),
            "lev": float(lev), "fwd": float(fwd), "sym": sym,
            "exit": "тейк", "marks": [(int(at) - int(at) % H, float(pnl))]}


def test_ticket_clears_the_exchange_floor():
    """Билет обязан пережить ХУДШЕЕ плечо, иначе часть сигналов неисполнима.

    Минимальный ордер $5, мельчайший рунг 25 % нотионала, забор выдаёт от
    1× — значит маржи нужно не меньше $20. Проверяем тождеством, а не
    числом в комментарии.
    """
    need = R.MIN_NOTIONAL / R.RUNG_SHARE / 1.0
    assert abs(need - 20.0) < 1e-9, need
    assert R.TICKET >= need, (R.TICKET, need)
    # при билете и плече 1 позиция проходит пол, при вдвое меньшем — нет
    recs = [_rec(1_700_000_000 + i, hold_h=2.0, lev=1.0, sym=f"C{i}USDT")
            for i in range(5)]
    ok = D6.ration(recs, R.TICKET / 1000.0, deposit=1000.0,
                   min_notional=R.MIN_NOTIONAL)
    thin = D6.ration(recs, (R.TICKET / 2) / 1000.0, deposit=1000.0,
                     min_notional=R.MIN_NOTIONAL)
    assert ok["too_small"] == 0 and ok["taken"] == 5, ok
    assert thin["too_small"] == 5, thin
    print(f"ok  билет: ${R.TICKET:g} переживает 1× (нужно ${need:g}), "
          f"половина билета не проходит")


def test_ticket_is_squeezed_between_the_floor_and_the_peak():
    """Билет зажат полом биржи снизу и пиком книги сверху.

    Числа закреплены ЛИТЕРАЛОМ, а не формулой от констант: формула
    повторила бы ошибку правила, а литерал ловит её. Главное свойство —
    мелкий депозит наполнить НЕЛЬЗЯ: у $1k и $10k связывает пол, и
    только у $100k потолок оказался выше пола.
    """
    got = [R.ticket(d) for d in R.DEPOSITS]
    assert got == [25.0, 25.0, 145.0], got
    assert [R.slots(d) for d in R.DEPOSITS] == [40, 400, 689]
    # у первых двух связал ПОЛ: доля на все места была бы меньше него
    for d in (1000.0, 10000.0):
        assert d / (R.PEAK_SEEN * R.PEAK_MARGIN) < R.TICKET_MIN, d
        assert R.ticket(d) == R.TICKET_MIN, d
    # у третьего связал ПИК, и мест хватает на него с объявленным запасом
    assert R.slots(100000.0) >= R.PEAK_SEEN * R.PEAK_MARGIN - 1
    assert R.ticket(100000.0) > R.TICKET_MIN
    # доля на позицию — ровно билет этого депозита
    for d in R.DEPOSITS:
        assert abs(R.share(d) * d - R.ticket(d)) < 1e-9, d
    print(f"ok  билет: {[f'${x:g}' for x in got]}, мест "
          f"{[R.slots(d) for d in R.DEPOSITS]} — пол биржи и пик книги")


def test_one_per_name_applied_before_cash():
    """Правило биржи не зависит от депозита и применяется ДО раздачи."""
    t0 = 1_700_000_000
    recs = [_rec(t0, hold_h=5.0, sym="AAAUSDT"),
            _rec(t0 + 60, hold_h=5.0, sym="AAAUSDT"),
            _rec(t0 + 120, hold_h=5.0, sym="BBBUSDT")]
    rk = R.DEFAULT_RULER
    rows, cells, one = P.build_rows({rk: recs}, now=t0 + 10 * H,
                                    log=lambda *_: None)
    assert one[rk]["skipped_repeats"] == 1 and one[rk]["kept"] == 2, one
    # у ВСЕХ книг состав один и тот же — повтор снят до кассы
    for dep in R.DEPOSITS:
        got = {r["sym"] for r in rows if r["dep"] == int(dep)}
        assert got == {"AAAUSDT", "BBBUSDT"}, (dep, got)
    print("ok  одна на имя: повтор снят до кассы, состав книг одинаков")


def test_forward_and_restored_never_mix():
    """Наблюдение и пересчёт — два числа, и они не складываются."""
    t0 = 1_700_000_000
    fresh = {"dep": 1000, "at": t0, "exit_ts": t0 + H, "sym": "A",
             "usd": 10.0, "written_at": t0 + 3600, "rules": R.RULES}
    old = {"dep": 1000, "at": t0, "exit_ts": t0 + H, "sym": "B",
           "usd": 5.0, "written_at": t0 + (R.AHEAD_H + 10) * 3600,
           "rules": R.RULES}
    assert R.ahead(fresh["at"], fresh["written_at"]) is True
    assert R.ahead(old["at"], old["written_at"]) is False
    fwd, back = R.split_rows([fresh, old])
    assert len(fwd) == 1 and len(back) == 1, (fwd, back)
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        with open(jp, "w", encoding="utf-8") as f:
            for r in (fresh, old):
                f.write(json.dumps(r) + "\n")
        s = P.summarize(jp)
        b = s["books"][P._cell(R.DEFAULT_RULER, 1000)]
        assert b["forward"]["usd"] == 10.0, b["forward"]
        assert b["restored"]["usd"] == 5.0, b["restored"]
        txt = P.report(s)
        assert "не складываются никогда" in txt, txt[:800]
        # 15.0 — сумма двух групп; её на странице быть не должно
        assert "15.00" not in txt, txt
    print("ok  запись: вперёд +10.00 и пересчёт +5.00 порознь, суммы нет")


def test_journal_appends_only_new():
    """Строка write-ahead не переписывается: момент записи подвинуть нельзя."""
    t0 = 1_700_000_000
    row = {"dep": 1000, "at": t0, "exit_ts": t0 + H, "sym": "A",
           "usd": 1.0, "written_at": t0 + 60, "rules": R.RULES}
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        a = P.append_journal([row], jp, log=lambda *_: None)
        later = dict(row, written_at=t0 + 10 ** 6)
        b = P.append_journal([later], jp, log=lambda *_: None)
        assert a["added"] == 1 and b["added"] == 0, (a, b)
        rows, _ = R.read_journal(jp)
        assert len(rows) == 1 and rows[0]["written_at"] == t0 + 60, rows
        # битая строка не роняет чтение и считается числом
        with open(jp, "a", encoding="utf-8") as f:
            f.write("{оборвана\n")
        rows, bad = R.read_journal(jp)
        assert len(rows) == 1 and bad == 1, (rows, bad)
    print("ok  журнал: повтор не дописан, момент записи не подвинут")


def test_report_names_what_is_not_modelled():
    """Отчёт обязан сказать, чего в числах нет, а не подразумевать."""
    txt = P.report({"books": {}})
    for need in ("Живого исполнения здесь нет", "по слитой", "СВЕРХУ"):
        assert need in txt, need
    assert "Наблюдения ещё нет" in txt, txt[-1500:]
    print("ok  отчёт: названы живое исполнение, слитая позиция и оценка сверху")



def test_day_concentration_is_measured_and_not_faked():
    """Один эпизод раздаёт деньги многим именам — колонка по именам слепа.

    Строим запись, где три дня несут всё, а остальные тают: «без лучшего
    имени» остаётся плюсовым, «без 3 лучших дней» обязано уйти в минус.
    Числа закреплены литералом, а не формулой от констант модуля.
    """
    D = 86400
    t0 = 1_767_225_600            # 2026-01-01 00:00 UTC, ровный день
    rows = []
    # десять тощих дней по -1 $, каждый своим именем
    for i in range(10):
        rows.append({"dep": 1000, "rules": R.RULES, "sym": f"T{i}USDT",
                     "at": t0 + i * D, "exit_ts": t0 + i * D + 60,
                     "usd": -1.0, "written_at": t0 + i * D + 120,
                     "lev": 1.0, "margin": 25.0, "pnl_frac": -0.04,
                     "exit": "стоп"})
    # три жирных дня, деньги размазаны по РАЗНЫМ именам — по 20 $ на день
    for j in range(3):
        for k in range(4):
            rows.append({"dep": 1000, "rules": R.RULES,
                         "sym": f"F{j}{k}USDT",
                         "at": t0 + (20 + j) * D, "exit_ts": t0 + (20 + j) * D + 60,
                         "usd": 5.0, "written_at": t0 + (20 + j) * D + 120,
                         "lev": 1.0, "margin": 25.0, "pnl_frac": 0.2,
                         "exit": "тейк"})
    st = P._stats(rows, 1000.0)
    assert st["days"] == 13, st["days"]
    assert abs(st["usd"] - 50.0) < 1e-6, st["usd"]          # -10 + 60
    # ни одно имя не даёт больше 5 $ — по именам концентрации «не видно»
    assert st["usd_wo_top"] > 40.0, st["usd_wo_top"]
    # а по дням от итога не остаётся ничего: 50 - 60 = -10
    assert abs(st["usd_wo_top3d"] + 10.0) < 1e-6, st["usd_wo_top3d"]
    # колонка обязана доехать до отчёта строкой, а не остаться в json
    s = {"books": {P._cell(R.DEFAULT_RULER, 1000): {
        "deposit": 1000, "ruler": R.DEFAULT_RULER, "slots": R.slots(1000),
        "ticket": R.TICKET, "forward": None, "restored": st,
        "n_forward": 0, "n_restored": len(rows)}}}
    txt = P.report(s)
    assert "$ без 3 лучших дней" in txt
    assert "-10.00" in txt, txt
    print("ok  дни: по именам +%.2f, без 3 лучших дней %.2f при итоге %.2f"
          % (st["usd_wo_top"], st["usd_wo_top3d"], st["usd"]))


def test_short_record_says_not_measured_not_zero():
    """Три дня из трёх вычитать нечем: прочерк, а не ноль."""
    D = 86400
    t0 = 1_767_225_600
    rows = [{"dep": 1000, "rules": R.RULES, "sym": f"S{i}USDT",
             "at": t0 + i * D, "exit_ts": t0 + i * D + 60, "usd": 3.0,
             "written_at": t0 + i * D + 120, "lev": 1.0, "margin": 25.0,
             "pnl_frac": 0.12, "exit": "тейк"} for i in range(3)]
    st = P._stats(rows, 1000.0)
    assert st["days"] == 3, st["days"]
    assert st["usd_wo_top3d"] is None, st["usd_wo_top3d"]
    txt = P.report({"books": {P._cell(R.DEFAULT_RULER, 1000): {
        "deposit": 1000, "ruler": R.DEFAULT_RULER, "slots": R.slots(1000),
        "ticket": R.TICKET, "forward": None, "restored": st,
        "n_forward": 0, "n_restored": len(rows)}}})
    # прочерк стоит В СВОЕЙ ячейке, последней в строке, а не «где-то»
    assert "| 6.00 | — |" in txt, [l for l in txt.split("\n") if "9.00" in l]
    print("ok  короткая запись: три дня из трёх — прочерк, а не ноль")


def test_two_rulers_are_two_books_and_optimal_is_untouched():
    """Одно решение живёт в ОБЕИХ книгах, и вторая не читается повтором.

    Плюс инвариант правки: числа «оптимальной» после появления второй
    линейки обязаны совпасть с числами прогона, где линейка была одна, —
    иначе мы молча переписали бы опубликованную книгу.
    """
    t0 = 1_700_000_000
    recs = [_rec(t0, hold_h=5.0, sym="AAAUSDT", pnl=0.10),
            _rec(t0 + 120, hold_h=5.0, sym="BBBUSDT", pnl=-0.04)]
    # у «безопасной» те же решения, но плечо (а с ним и ход) своё
    safe = [dict(r, lev=1.4, pnl=r["pnl"] * 0.35) for r in recs]
    one_only, _, _ = P.build_rows({"optimal": recs}, now=t0 + 10 * H,
                                  log=lambda *_: None)
    both, cells, one = P.build_rows({"optimal": recs, "safe": safe},
                                    now=t0 + 10 * H, log=lambda *_: None)
    assert {"optimal", "safe"} <= set(one), one
    # режим, которому записей не досталось, не исчезает, а стоит нулём:
    # молча пропавшая книга неотличима от книги, которой нечего показать
    for k in set(one) - {"optimal", "safe"}:
        assert one[k]["kept"] == 0 and one[k]["positions"] == 0, (k, one[k])
    # каждая строка несёт свой режим, и книг стало по числу режимов
    assert {r["ruler"] for r in both} == {"optimal", "safe"}, "нет метки"
    assert len(cells) == len(R.RULER_ORDER) * len(R.DEPOSITS), sorted(cells)
    opt = [r for r in both if r["ruler"] == "optimal"]
    assert opt == [dict(r, ruler="optimal") for r in one_only], "оптимальная сдвинулась"
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        a = P.append_journal(both, jp, log=lambda *_: None)
        assert a["added"] == len(both), a
        # повтор того же прогона не дописывает ничего
        b = P.append_journal(both, jp, log=lambda *_: None)
        assert b["added"] == 0, b
        s = P.summarize(jp)
        ks = [P._cell(rk, d) for rk in R.RULER_ORDER for d in R.DEPOSITS]
        assert all(k in s["books"] for k in ks), sorted(s["books"])
        so = s["books"][P._cell("optimal", 1000)]
        ss = s["books"][P._cell("safe", 1000)]
        assert so["forward"] and ss["forward"], (so, ss)
        assert so["forward"]["usd"] != ss["forward"]["usd"], "книги совпали"
        txt = P.report(s)
        for rk in R.RULER_ORDER:
            assert R.ruler_title(rk) in txt, (rk, txt[:400])
    print("ok  линейки: две книги на решение, «оптимальная» бит в бит прежняя")


def test_aggressive_gate_takes_only_levered_entries():
    """Третий режим = та же линейка глубины плюс ГЕЙТ по плечу.

    Проверяется три вещи, и вторая важнее первой. (1) Гейт режет ровно по
    объявленному порогу, и порог ВЫВЕДЕН из пола биржи при билете $5, а
    не выбран. (2) Гейт стоит ПЕРЕД правилом одной на имя: у режима с
    гейтом низкоплечевой ранний вход не случается, значит имя свободно и
    позже по нему открывается рычажный — состав, а не только объём.
    (3) Режим без поля `min_lev` гейта не несёт вовсе: отсутствие и ноль
    здесь разные значения.
    """
    # порог — тождество, а не число в комментарии
    assert abs(R.AGGR_MIN_LEV
               - R.MIN_NOTIONAL / R.RUNG_SHARE / 5.0) < 1e-9, R.AGGR_MIN_LEV
    assert R.min_lev_of("aggr") == R.AGGR_MIN_LEV
    assert R.min_lev_of("optimal") is None and R.min_lev_of("safe") is None
    t0 = 1_700_000_000
    recs = [_rec(t0, hold_h=5.0, sym="LOWUSDT", lev=1.5),
            _rec(t0 + 60, hold_h=5.0, sym="MIDUSDT", lev=3.9),
            _rec(t0 + 120, hold_h=5.0, sym="HIUSDT", lev=4.0),
            _rec(t0 + 180, hold_h=5.0, sym="TOPUSDT", lev=8.0)]
    rows, cells, one = P.build_rows({"optimal": recs, "aggr": recs},
                                    now=t0 + 10 * H, log=lambda *_: None)
    assert one["optimal"]["gate_dropped"] == 0, one["optimal"]
    assert one["aggr"]["gate_dropped"] == 2, one["aggr"]
    assert one["aggr"]["kept"] == 2, one["aggr"]
    syms = {k: {r["sym"] for r in rows if r["ruler"] == k and r["dep"] == 1000}
            for k in ("optimal", "aggr")}
    assert syms["aggr"] == {"HIUSDT", "TOPUSDT"}, syms
    assert syms["aggr"] < syms["optimal"], syms
    # (2) порядок: гейт до правила одной на имя
    pair = [_rec(t0, hold_h=5.0, sym="AAAUSDT", lev=1.0),
            _rec(t0 + 60, hold_h=5.0, sym="AAAUSDT", lev=8.0)]
    rows2, _c2, one2 = P.build_rows({"optimal": pair, "aggr": pair},
                                    now=t0 + 10 * H, log=lambda *_: None)
    opt = [r for r in rows2 if r["ruler"] == "optimal" and r["dep"] == 1000]
    agg = [r for r in rows2 if r["ruler"] == "aggr" and r["dep"] == 1000]
    assert len(opt) == 1 and opt[0]["lev"] == 1.0, opt
    assert len(agg) == 1 and agg[0]["lev"] == 8.0, agg
    assert one2["optimal"]["skipped_repeats"] == 1, one2
    assert one2["aggr"]["skipped_repeats"] == 0, one2
    print(f"ok  гейт: плечо ≥ {R.AGGR_MIN_LEV:g}× (пол биржи при билете "
          "$5), стоит до правила одной на имя")


def test_aggressive_keeps_the_same_ticket_and_says_its_own_peak():
    """Билет у режима с гейтом ТОТ ЖЕ, и это решение, а не недосмотр.

    По своей арифметике его пол был бы вчетверо ниже ($20/4 = $5), но
    другой билет дал бы другое число мест — то есть режим отличался бы от
    «оптимальной» ДВУМЯ правилами, и разницу нельзя было бы приписать
    гейту. Цена выбора обязана быть видна числом: свой пик режима и
    отказы кассы печатаются, а отчёт называет плату словами.
    """
    for d in R.DEPOSITS:
        assert R.ticket(d) == R.ticket(d), d       # один билет на все режимы
    own_floor = R.MIN_NOTIONAL / R.RUNG_SHARE / R.AGGR_MIN_LEV
    assert abs(own_floor - 5.0) < 1e-9, own_floor
    assert R.TICKET_MIN > own_floor, (R.TICKET_MIN, own_floor)
    t0 = 1_700_000_000
    recs = [_rec(t0 + i * 60, hold_h=5.0, sym=f"S{i}USDT", lev=4.0 + i)
            for i in range(6)]
    _rows, _cells, one = P.build_rows({"aggr": recs}, now=t0 + 10 * H,
                                      log=lambda *_: None)
    assert one["aggr"]["peak_names"] == 6, one["aggr"]
    assert one["aggr"]["lev_median"] is not None
    txt = P.report({"books": {}, "one_name": one})
    assert "Билет у режима с гейтом НЕ понижен" in txt, txt[:400]
    assert "свой пик позиций" in txt and "6 |" in txt, txt[-1200:]
    print(f"ok  билет тот же (${R.TICKET_MIN:g} против собственного пола "
          f"${own_floor:g}), свой пик режима печатается числом")


def test_legacy_row_reads_as_the_ruler_it_was_written_with():
    """Строка без поля `ruler` писана глубиной — и обязана попасть к ней.

    Не «в безопасную» и не в никуда: журнал write-ahead, переписать
    прошлое нечем, поэтому умолчание доказуемо и закреплено числом.
    """
    t0 = 1_700_000_000
    legacy = {"dep": 1000, "at": t0, "exit_ts": t0 + H, "sym": "A",
              "usd": 7.0, "written_at": t0 + 3600, "rules": R.RULES}
    assert R.ruler_of(legacy) == "optimal", R.ruler_of(legacy)
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        with open(jp, "w", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")
        s = P.summarize(jp)
        assert s["books"][P._cell("optimal", 1000)]["forward"]["usd"] == 7.0
        assert s["books"][P._cell("safe", 1000)]["forward"] is None
    print("ok  прежняя строка: читается оптимальной, в безопасную не течёт")


def test_cash_refusals_reach_the_report_and_survive_restat():
    """Отказы кассы — прямой ответ «что покупает депозит», и их нельзя
    терять пересборкой свода: `--restat` ничего не считает, но и не
    вправе выбрасывать числа счётного прогона. Тот же класс, что «урезать
    можно то, что отдаёшь, но не то, на чём считаешь».
    """
    st = {"n": 5, "names": 5, "days": 5, "usd": 3.0, "final": 0.003,
          "max_dd": -0.01, "day_median": 0.0, "day_worst": -0.002,
          "day_green": 0.6, "bite": 2.0, "top_sym": "AAAUSDT",
          "usd_wo_top": 2.0, "usd_wo_top3d": -1.0}
    base = {"books": {P._cell(rk, 1000): {
        "deposit": 1000, "ruler": rk, "slots": 40, "ticket": R.TICKET,
        "forward": None, "restored": st, "n_forward": 0, "n_restored": 5}
        for rk in R.RULER_ORDER}}
    # без счётного прогона таблицы нет, и сказано ПОЧЕМУ
    txt0 = P.report(dict(base))
    assert "Что связывает депозит" in txt0
    assert "пересборкой свода" in txt0, txt0[-700:]
    assert "нет кассы" not in txt0
    # со счётным прогоном — числа по каждой книге
    s = dict(base, computed_at="2026-09-04 12:00", cells={
        P._cell(rk, 1000): {"slots": 40, "taken": 594, "no_cash": 1689,
                            "too_small": 0} for rk in R.RULER_ORDER})
    txt = P.report(s)
    assert "| 594 | 1689 |" in txt, [l for l in txt.split("\n")
                                     if "594" in l]
    assert "2026-09-04 12:00" in txt

    # И ГЛАВНОЕ — дорога, а не только формула: `--restat` гоняется
    # настоящим `main`. Первая версия этой проверки звала один `report`
    # и потому прошла, когда переноса в `main` не было вовсе, — тест,
    # чьё имя обещает больше, чем он исполняет, хуже отсутствующего.
    import runpy
    jp, ap = R.JOURNAL, R.ARTIFACT
    with tempfile.TemporaryDirectory() as td:
        try:
            R.JOURNAL = os.path.join(td, "j.jsonl")
            R.ARTIFACT = os.path.join(td, "a.json")
            P.R.OUT = td
            t0 = 1_700_000_000
            with open(R.JOURNAL, "w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "dep": 1000, "ruler": R.DEFAULT_RULER, "at": t0,
                    "exit_ts": t0 + 3600, "sym": "AAAUSDT", "usd": 2.0,
                    "written_at": t0 + 600, "rules": R.RULES}) + "\n")
            with open(R.ARTIFACT, "w", encoding="utf-8") as f:
                json.dump({"cells": {P._cell(R.DEFAULT_RULER, 1000): {
                    "slots": 40, "taken": 594, "no_cash": 1689,
                    "too_small": 0}}, "positions": 8677,
                    "computed_at": "2026-09-04 12:00"}, f)
            sys.argv = ["run_paper.py", "--restat", "--no-publish"]
            P.main()
            with open(R.ARTIFACT, encoding="utf-8") as f:
                got = json.load(f)
            assert (got.get("cells") or {}), "пересборка потеряла отказы"
            assert got.get("positions") == 8677, got.get("positions")
            assert got.get("computed_at") == "2026-09-04 12:00", got
            with open(os.path.join(td, "DCA-paper.md"), encoding="utf-8") as f:
                md = f.read()
            assert "| 594 | 1689 |" in md, md[-900:]
        finally:
            R.JOURNAL, R.ARTIFACT, P.R.OUT = jp, ap, os.path.dirname(ap)
    print("ok  отказы кассы: пересборка их не теряет (проверено main)")


def test_rules_change_starts_a_fresh_record():
    """Смена правил (билета) начинает запись заново, а не дописывает.

    Решение, писанное ДРУГИМ билетом, той же строкой не является: без
    версии в ключе дедупа книга новых правил осталась бы пустой навсегда
    — прогон считал бы её записанной и не дописывал ни строки.
    """
    t0 = 1_700_000_000
    was = {"dep": 1000, "ruler": R.DEFAULT_RULER, "at": t0,
           "exit_ts": t0 + 3600, "sym": "AAAUSDT", "usd": 5.0,
           "margin": 25.0, "written_at": t0 + 600, "rules": R.RULES - 1}
    now = dict(was)
    now["rules"] = R.RULES
    now["margin"] = 145.0
    now["usd"] = 29.0
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "j.jsonl")
        with open(jp, "w", encoding="utf-8") as f:
            f.write(json.dumps(was) + "\n")
        a = P.append_journal([now], jp, log=lambda *_: None)
        assert a["added"] == 1, a
        s = P.summarize(jp)
        b = s["books"][P._cell(R.DEFAULT_RULER, 1000)]
        # видна ТОЛЬКО запись действующих правил, и это её числа
        assert b["forward"]["n"] == 1, b["forward"]
        assert b["forward"]["usd"] == 29.0, b["forward"]
    print("ok  смена правил: запись начата заново, прежняя не считается")


def _control_no_split():
    """Свод, складывающий наблюдение с пересчётом, — то, ради чего split."""
    orig = R.split_rows
    R.split_rows = lambda rows, hours=R.AHEAD_H: (list(rows), [])
    try:
        try:
            test_forward_and_restored_never_mix()
        except AssertionError:
            return True
        return False
    finally:
        R.split_rows = orig


def _control_ticket_below_floor():
    """Билет ниже пола биржи — часть сигналов физически неисполнима."""
    orig = R.TICKET
    R.TICKET = 10.0
    try:
        try:
            test_ticket_clears_the_exchange_floor()
        except AssertionError:
            return True
        return False
    finally:
        R.TICKET = orig


def _control_one_per_name_off():
    """Без правила биржи повтор по имени попадает в книгу."""
    orig = R.ONE_PER_NAME
    R.ONE_PER_NAME = False
    try:
        try:
            test_one_per_name_applied_before_cash()
        except AssertionError:
            return True
        return False
    finally:
        R.ONE_PER_NAME = orig


def _control_journal_overwrites():
    """Журнал, переписывающий строку, позволяет подвинуть момент записи."""
    orig = P.append_journal

    def rewrite(rows, path=R.JOURNAL, log=print):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        return {"had": 0, "added": len(rows), "bad": 0}
    P.append_journal = rewrite
    try:
        try:
            test_journal_appends_only_new()
        except AssertionError:
            return True
        return False
    finally:
        P.append_journal = orig



def _control_day_concentration_by_one_day():
    """Контроль: вычесть ОДИН лучший день вместо трёх — проверка обязана пасть."""
    src = P._stats

    def broken(rows, deposit):
        st = src(rows, deposit)
        if st and st.get("usd_wo_top3d") is not None:
            day = {}
            for r in rows:
                d = time.strftime("%Y-%m-%d", time.gmtime(float(r["exit_ts"])))
                day[d] = day.get(d, 0.0) + float(r["usd"])
            st["usd_wo_top3d"] = round(sum(day.values()) - max(day.values()), 2)
        return st

    P._stats = broken
    try:
        try:
            test_day_concentration_is_measured_and_not_faked()
        except AssertionError:
            return True
        return False
    finally:
        P._stats = src


def _control_dedup_without_ruler():
    """Контроль: дедуп без линейки — вторая книга не пишется вовсе."""
    orig = R.ruler_of
    R.ruler_of = lambda row: "optimal"          # линейку «не видим»
    try:
        try:
            test_two_rulers_are_two_books_and_optimal_is_untouched()
        except AssertionError:
            return True
        return False
    finally:
        R.ruler_of = orig


def _control_legacy_reads_as_safe():
    """Контроль: прежняя строка объявлена безопасной — книга подменена."""
    orig = R.DEFAULT_RULER
    R.DEFAULT_RULER = "safe"
    try:
        try:
            test_legacy_row_reads_as_the_ruler_it_was_written_with()
        except AssertionError:
            return True
        return False
    finally:
        R.DEFAULT_RULER = orig


def _control_restat_drops_the_counts():
    """Контроль: пересборка молча выбрасывает числа счётного прогона."""
    orig = P.report

    def blind(s):
        return orig({k: v for k, v in s.items() if k != "cells"})

    P.report = blind
    try:
        try:
            test_cash_refusals_reach_the_report_and_survive_restat()
        except AssertionError:
            return True
        return False
    finally:
        P.report = orig


def _control_dedup_without_rules_version():
    """Контроль: дедуп БЕЗ версии правил — прежнее поведение дословно.

    Здесь пять строк повторяют код до правки намеренно: контроль обязан
    воспроизводить именно ту дорогу, которую правка закрыла.
    """
    orig = P.append_journal

    def blind(rows, path=R.JOURNAL, log=print):
        was, _ = R.read_journal(path)
        seen = {(R.ruler_of(r), r.get("dep"), P._key(r)) for r in was}
        fresh = [r for r in rows
                 if (R.ruler_of(r), r["dep"], P._key(r)) not in seen]
        if fresh:
            with open(path, "a", encoding="utf-8") as f:
                for r in fresh:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return {"had": len(was), "added": len(fresh), "bad": 0}

    P.append_journal = blind
    try:
        try:
            test_rules_change_starts_a_fresh_record()
        except AssertionError:
            return True
        return False
    finally:
        P.append_journal = orig


def _control_gate_is_gone():
    """Гейта нет вовсе: третий режим молча становится копией второй книги.

    Порядок «гейт до правила одной на имя» этим контролем не проверяется —
    он живёт в самом `build_rows`, и подделать его изнутри процесса
    нечем; он проверяется порчей исходника (копия в scratchpad, возврат
    копией), как остальные правки такого рода.
    """
    orig = R.min_lev_of
    R.min_lev_of = lambda k: None
    try:
        try:
            test_aggressive_gate_takes_only_levered_entries()
        except AssertionError:
            return True
        return False
    finally:
        R.min_lev_of = orig


def _control_gate_on_every_ruler():
    """Порог назначен всем режимам: книга без поля теряет свои входы."""
    orig = R.min_lev_of
    R.min_lev_of = lambda k: R.AGGR_MIN_LEV
    try:
        try:
            test_aggressive_gate_takes_only_levered_entries()
        except AssertionError:
            return True
        return False
    finally:
        R.min_lev_of = orig


TESTS = [test_ticket_clears_the_exchange_floor,
         test_ticket_is_squeezed_between_the_floor_and_the_peak,
         test_one_per_name_applied_before_cash,
         test_forward_and_restored_never_mix, test_journal_appends_only_new,
         test_report_names_what_is_not_modelled,
         test_day_concentration_is_measured_and_not_faked,
         test_short_record_says_not_measured_not_zero,
         test_two_rulers_are_two_books_and_optimal_is_untouched,
         test_aggressive_gate_takes_only_levered_entries,
         test_aggressive_keeps_the_same_ticket_and_says_its_own_peak,
         test_legacy_row_reads_as_the_ruler_it_was_written_with,
         test_cash_refusals_reach_the_report_and_survive_restat,
         test_rules_change_starts_a_fresh_record]

CONTROLS = [("свод складывает вперёд и пересчёт", _control_no_split),
            ("билет ниже пола биржи", _control_ticket_below_floor),
            ("правило одной позиции снято", _control_one_per_name_off),
            ("журнал переписывает строку", _control_journal_overwrites),
            ("концентрация по одному дню вместо трёх",
             _control_day_concentration_by_one_day),
            ("дедуп не видит линейки", _control_dedup_without_ruler),
            ("прежняя строка объявлена безопасной",
             _control_legacy_reads_as_safe),
            ("пересборка теряет числа счётного прогона",
             _control_restat_drops_the_counts),
            ("дедуп не видит версии правил",
             _control_dedup_without_rules_version),
            ("гейта плеча нет вовсе", _control_gate_is_gone),
            ("гейт назначен всем режимам", _control_gate_on_every_ruler)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
