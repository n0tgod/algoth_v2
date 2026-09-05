#!/usr/bin/env python3
"""Проверки бумажных DCA-книг. Прогон: .venv/bin/python …/test_paper.py"""

import json
import os
import subprocess
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
import split_journal as SPL                                    # noqa: E402
import tail as TL                                             # noqa: E402

H = 3600
LAST_RUN = {}          # что видел последний прогон `_cache_run`


def _rec(at, hold_h=1.0, pnl=0.10, lev=4.0, fwd=100.0, sym="AAAUSDT",
         state="closed", exit_="тейк"):
    """Запись позиции, КАК ЕЁ ПИШЕТ живой реплей.

    Поля состояния и входов обязательны: подставная запись без них
    исполняла бы другую дорогу, а такая фикстура в этом проекте уже
    трижды прятала дефект.
    """
    ex = at + hold_h * H
    return {"at": float(at), "exit_ts": float(ex), "pnl": float(pnl),
            "lev": float(lev), "fwd": float(fwd), "sym": sym,
            "exit": exit_, "marks": [(int(at) - int(at) % H, float(pnl))],
            "state": state, "end_ts": float(ex),
            "sched_end": float(at) + 72 * H,
            "entry_px": 100.0, "exit_px": 110.0, "avg": 100.0, "depth": 1,
            "fills": [[float(at), 100.0, 0.25]]}


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
    """Билет зажат полом РЕЖИМА снизу и его же пиком сверху.

    Числа закреплены ЛИТЕРАЛОМ, а не формулой от констант: формула
    повторила бы ошибку правила, а литерал ловит её. Главное свойство —
    мелкий депозит наполнить НЕЛЬЗЯ: у него связывает пол биржи.
    """
    got = {rk: [R.ticket(d, rk) for d in R.DEPOSITS] for rk in R.RULER_ORDER}
    assert got["safe"] == [25.0, 25.0, 145.0], got
    assert got["optimal"] == [25.0, 25.0, 145.0], got
    assert got["aggr"] == [6.25, 28.0, 281.0], got
    assert [R.slots(d, "optimal") for d in R.DEPOSITS] == [40, 400, 689]
    assert [R.slots(d, "aggr") for d in R.DEPOSITS] == [160, 357, 355]
    # у книги без гейта на первых двух депозитах связал ПОЛ
    for d in (1000.0, 10000.0):
        assert d / (R.peak_of("optimal") * R.PEAK_MARGIN) < R.TICKET_MIN, d
        assert R.ticket(d, "optimal") == R.TICKET_MIN, d
    # у третьего связал ПИК, и мест хватает на него с объявленным запасом
    assert R.slots(100000.0, "optimal") >= R.peak_of("optimal") * R.PEAK_MARGIN - 1
    assert R.ticket(100000.0, "optimal") > R.TICKET_MIN
    # доля на позицию — ровно билет этой книги
    for rk in R.RULER_ORDER:
        for d in R.DEPOSITS:
            assert abs(R.share(d, rk) * d - R.ticket(d, rk)) < 1e-9, (rk, d)
    print(f"ok  билет: без гейта {got['optimal']}, с гейтом {got['aggr']} — "
          "пол режима и его же пик")


def test_ticket_rule_is_one_formula_for_every_mode():
    """Билет не является отдельной осью: формула одна, числа свои.

    Это и есть довод, по которому контрольная рука со старым билетом не
    нужна: режимы по-прежнему различаются РОВНО одним объявленным
    правилом (гейтом плеча), а билет у каждого выводится тем же
    выражением из его собственных пола и пика.
    """
    for rk in R.RULER_ORDER:
        for d in R.DEPOSITS:
            want = max(R.floor_of(rk),
                       float(int(d / (R.peak_of(rk) * R.PEAK_MARGIN))))
            assert R.ticket(d, rk) == want, (rk, d)
    # пол ВЫВОДИТСЯ из худшего плеча режима, а не назначен числом
    assert R.floor_of("optimal") == R.MIN_NOTIONAL / R.RUNG_SHARE * R.HEADROOM
    assert (R.floor_of("aggr")
            == R.MIN_NOTIONAL / R.RUNG_SHARE / R.AGGR_MIN_LEV * R.HEADROOM)
    assert R.floor_of("aggr") * R.AGGR_MIN_LEV == R.floor_of("optimal")
    print(f"ok  одна формула: пол ${R.floor_of('optimal'):g} без гейта и "
          f"${R.floor_of('aggr'):g} при гейте {R.AGGR_MIN_LEV:g}×")


def test_gated_mode_is_deployed_at_its_own_peak():
    """Режим с гейтом вложен на СВОЁМ пике, а не на чужом.

    Ради этого правка и делалась: прежде билет считался от пика ПУЛА, и
    режим с гейтом стоял недогруженным — при полном по его меркам
    портфеле часть денег простаивала. Проверяется прямо: на депозитах,
    где связывает пик, мест хватает на собственный пик, а сам он занимает
    заметную долю депозита.
    """
    peak = R.peak_of("aggr")
    assert peak < R.peak_of("optimal"), (peak, R.peak_of("optimal"))
    for d in (10000.0, 100000.0):
        assert R.slots(d, "aggr") >= peak, (d, R.slots(d, "aggr"))
        used = peak * R.ticket(d, "aggr") / d       # доля депозита в пике
        assert 0.6 <= used <= 1.0, (d, used)
        # прежнее правило (пик пула) дало бы вдвое меньше
        was = max(R.TICKET_MIN,
                  float(int(d / (R.peak_of("optimal") * R.PEAK_MARGIN))))
        assert R.ticket(d, "aggr") > was, (d, was)
    # на мелком депозите связывает ПОЛ, и это честная граница: денег
    # хватает не на все места режима
    assert R.ticket(1000.0, "aggr") == R.floor_of("aggr")
    assert R.slots(1000.0, "aggr") < peak
    print(f"ok  свой пик {peak}: в пике занято "
          f"{peak * R.ticket(10000.0, 'aggr') / 10000.0:.0%} депозита $10k "
          f"против {peak * 25.0 / 10000.0:.0%} прежде")


def test_one_per_name_applied_before_cash():
    """Правило биржи не зависит от депозита и применяется ДО раздачи."""
    t0 = 1_700_000_000
    recs = [_rec(t0, hold_h=5.0, sym="AAAUSDT"),
            _rec(t0 + 60, hold_h=5.0, sym="AAAUSDT"),
            _rec(t0 + 120, hold_h=5.0, sym="BBBUSDT")]
    rk = R.DEFAULT_RULER
    rows, cells, one, _live = P.build_rows({rk: recs}, now=t0 + 10 * H,
                                    log=lambda *_: None)
    assert one[rk]["skipped_repeats"] == 1 and one[rk]["kept"] == 2, one
    # у ВСЕХ книг состав один и тот же — повтор снят до кассы
    for dep in R.DEPOSITS:
        got = {r["sym"] for r in rows if r["dep"] == int(dep)}
        assert got == {"AAAUSDT", "BBBUSDT"}, (dep, got)
    print("ok  одна на имя: повтор снят до кассы, состав книг одинаков")


def test_backtest_and_live_share_one_curve_and_stay_labelled():
    """Кривая одна (решение владельца), но группы остаются числами.

    Прежнее правило книги запрещало складывать наблюдение с пересчётом.
    Владелец 2026-09-04 решил иначе: бэктест есть предыстория живой
    записи, счёт общий, у сделки бэктеста метка. Проверяется ровно это —
    общий счёт равен сумме групп ПО ПОСТРОЕНИЮ, и обе группы при этом
    видны отдельно: без их объёма общая кривая читалась бы треком.
    """
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
        assert b["all"]["usd"] == 15.0, b["all"]
        assert b["all"]["n"] == 2, b["all"]
        txt = P.report(s)
        assert "бэктест и live" in txt.lower(), txt[:900]
        assert "15.00" in txt, txt          # общий счёт напечатан
        assert "10.00" in txt and "5.00" in txt, txt   # и группы тоже
    print("ok  кривая одна: общий счёт +15.00 при группах +10.00 и +5.00")


def test_open_position_is_not_a_closed_one():
    """Позиция, чей срок ещё идёт, — открытая, а не «закрыта по сроку».

    Дефект, который этим чинится: реплей кончал позицию последним баром
    записи и выдавал это за исход правила. Теперь такая позиция в журнал
    НЕ идёт вовсе (журнал есть запись случившегося), её деньги остаются
    занятыми до планового конца срока, а отметка стоит отдельно и с
    закрытым счётом не складывается.
    """
    t0 = 1_700_000_000
    done = _rec(t0, hold_h=2.0, pnl=0.10, sym="AAAUSDT")
    live = _rec(t0 + H, hold_h=1.0, pnl=-0.05, sym="BBBUSDT",
                state="open", exit_="срок")
    cut = _rec(t0 + 2 * H, hold_h=1.0, pnl=-0.20, sym="CCCUSDT",
               state="cut", exit_="срок")
    rows, cells, _one, lv = P.build_rows({"optimal": [done, live, cut]},
                                         now=t0 + 10 * H, log=lambda *_: None)
    got = [r for r in rows if int(r["dep"]) == 1000]
    assert [r["sym"] for r in got] == ["AAAUSDT"], got
    cell = lv[P._cell("optimal", 1000)]
    assert [x["sym"] for x in cell["positions"]] == ["BBBUSDT"], cell
    assert [x["sym"] for x in cell["cut"]] == ["CCCUSDT"], cell
    assert cell["mark_usd"] < 0, cell          # отметка, а не исход
    c = cells[P._cell("optimal", 1000)]
    assert c["open_n"] == 1 and c["cut_n"] == 1, c
    # деньги живой позиции ЗАНЯТЫ до планового конца: касса не вернула их
    # на последнем баре записи — иначе новый вход получил бы чужую маржу
    assert c["taken"] == 3, c
    txt = P.report({"books": {P._cell("optimal", 1000): {
        "deposit": 1000.0, "ruler": "optimal", "slots": 40, "ticket": 25.0,
        "live_known": True, "open": cell}}, "one_name": {}})
    assert "Открытые позиции" in txt and "оборвана записью" in txt, txt[-900:]
    print("ok  открытая позиция: в журнал не идёт, деньги заняты, "
          "отметка отдельно")


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
        "deposit": 1000, "ruler": R.DEFAULT_RULER, "slots": R.slots(1000, R.DEFAULT_RULER),
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
        "deposit": 1000, "ruler": R.DEFAULT_RULER, "slots": R.slots(1000, R.DEFAULT_RULER),
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
    one_only, _, _, _ = P.build_rows({"optimal": recs}, now=t0 + 10 * H,
                                  log=lambda *_: None)
    both, cells, one, _live = P.build_rows({"optimal": recs, "safe": safe},
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
    rows, cells, one, _live = P.build_rows({"optimal": recs, "aggr": recs},
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
    rows2, _c2, one2, _l2 = P.build_rows({"optimal": pair, "aggr": pair},
                                    now=t0 + 10 * H, log=lambda *_: None)
    opt = [r for r in rows2 if r["ruler"] == "optimal" and r["dep"] == 1000]
    agg = [r for r in rows2 if r["ruler"] == "aggr" and r["dep"] == 1000]
    assert len(opt) == 1 and opt[0]["lev"] == 1.0, opt
    assert len(agg) == 1 and agg[0]["lev"] == 8.0, agg
    assert one2["optimal"]["skipped_repeats"] == 1, one2
    assert one2["aggr"]["skipped_repeats"] == 0, one2
    print(f"ok  гейт: плечо ≥ {R.AGGR_MIN_LEV:g}× (пол биржи при билете "
          "$5), стоит до правила одной на имя")


def test_declared_peak_is_checked_against_the_measured_one():
    """Объявленный пик обязан быть не ниже измеренного, иначе крик.

    Из объявленного пика считается билет. Окажись он ниже настоящего —
    билет велик, и книга берёт не все свои решения, а первые по очереди
    за кассой: отказ меняет и СОСТАВ. Молчать об этом нельзя.
    """
    t0 = 1_700_000_000
    recs = [_rec(t0 + i * 60, hold_h=5.0, sym=f"S{i}USDT", lev=4.0 + i)
            for i in range(6)]
    _rows, _cells, one, _live = P.build_rows({"aggr": recs}, now=t0 + 10 * H,
                                      log=lambda *_: None)
    assert one["aggr"]["peak_names"] == 6, one["aggr"]
    assert one["aggr"]["peak_declared"] == R.peak_of("aggr")
    assert one["aggr"]["peak_over"] is False, one["aggr"]
    assert one["aggr"]["floor"] == R.floor_of("aggr")
    assert one["aggr"]["lev_median"] is not None
    # тот же расклад, но объявленный пик занижен — обязан кричать
    loud = {"aggr": dict(one["aggr"], peak_names=999, peak_over=True)}
    txt = P.report({"books": {}, "one_name": loud})
    # маркер ячейки, а не слова заголовка: заголовок про «не ниже
    # измеренного» стоит в отчёте всегда и проверял бы сам себя
    assert "⚠ ниже измеренного" in txt, txt[-1500:]
    txt = P.report({"books": {}, "one_name": one})
    assert "⚠ ниже измеренного" not in txt, txt[-1500:]
    assert "свой пик позиций" in txt and "| 6 | " in txt, txt[-1200:]
    print(f"ok  пик: измеренный 6 против объявленного "
          f"{R.peak_of('aggr')}, занижение кричит")


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


def _cache_run(cache_seed, legs, td):
    """Настоящий `main` с подставным дорогим проходом.

    Возвращает список решений, которые прогон отправил считать заново.
    Ровно эта дорога и есть предмет: правило можно проверить прямым
    вызовом, а вот доехало ли оно до прогона — только прогоном (урок
    «дорогу до показа проверять отдельно от величины»).
    """
    seen = {}

    def fake_legs(limit=None, log=print):
        return list(legs)

    def fake_collect(rulers=None, legs=None, only=None, **kw):
        # источник баров запоминается: правило хвоста можно проверить
        # прямым вызовом, а доехало ли оно до ядра — только прогоном
        seen["src"] = kw.get("src")
        seen["only"] = [(str(x[0]), round(float(x[1]), 3))
                        for x in (only or [])]
        recs = {tuple(pr): [] for pr in (rulers or [])}
        want = set(seen["only"])
        for g in (legs or []):
            k = (str(g["sym"]), round(float(g["at"]), 3))
            if only is not None and k not in want:
                continue
            for pr in recs:
                recs[pr].append(_rec(g["at"], sym=g["sym"],
                                     state=g.get("state", "closed")))
        return {"recs": recs, "positions": len(want), "skipped": 0,
                "window": D6.window(legs or []), "data_end": 0.0,
                "states": {}}

    gl, cr = D6.gated_legs, D6.collect_recs
    jp, ap, ot = R.JOURNAL, R.ARTIFACT, R.OUT
    try:
        D6.gated_legs, D6.collect_recs = fake_legs, fake_collect
        R.JOURNAL = os.path.join(td, "j.jsonl")
        R.ARTIFACT = os.path.join(td, "a.json")
        R.OUT = P.R.OUT = td
        if cache_seed is not None:
            P.write_cache(cache_seed)
        sys.argv = ["run_paper.py", "--no-publish"]
        P.main()
    finally:
        D6.gated_legs, D6.collect_recs = gl, cr
        R.JOURNAL, R.ARTIFACT, R.OUT = jp, ap, ot
        P.R.OUT = ot
    # То, чем прогон кормил ядро, остаётся видимым отдельно: список
    # пересчитанных решений — ответ на свой вопрос, а источник баров —
    # на другой, и мешать их в одном значении незачем.
    global LAST_RUN
    LAST_RUN = seen
    return seen.get("only", [])


def test_journal_path_is_resolved_at_call_time():
    """Прогон с подменённым журналом не смеет писать в НАСТОЯЩИЙ.

    Журнал книги — единственное здесь невосстановимое: счёт есть чистая
    функция от него, и подставная строка в нём навсегда становится
    частью записи. Путь, замёрзший значением по умолчанию на импорте,
    ровно это и делал — первый прогон проверки кэша положил в живую
    запись девять выдуманных решений.
    """
    real = R.JOURNAL
    with tempfile.TemporaryDirectory() as td:
        mine = os.path.join(td, "j.jsonl")
        t0 = 1_700_000_000
        rows = [{"dep": 1000, "ruler": R.DEFAULT_RULER, "at": t0,
                 "exit_ts": t0 + 3600, "sym": "AAAUSDT", "usd": 1.0,
                 "written_at": t0 + 60, "rules": R.RULES}]
        before = (os.path.getsize(real) if os.path.exists(real) else None)
        try:
            R.JOURNAL = mine
            P.append_journal(rows, log=lambda *a: None)
        finally:
            R.JOURNAL = real
        shard = R.shard_of(mine, t0)
        assert os.path.exists(shard), "запись ушла мимо подменённого журнала"
        got, _bad = R.read_journal(mine)
        assert [r["sym"] for r in got] == ["AAAUSDT"], got
        after = (os.path.getsize(real) if os.path.exists(real) else None)
        assert after == before, "настоящий журнал книги тронут прогоном"
    print("ok  журнал: путь берётся в момент вызова, живая запись цела")


def test_cache_replays_new_and_open_but_not_closed():
    """Кэш реплея законен ровно для ЗАКРЫТЫХ позиций.

    Прошлые бары не меняются, значит исход закрытой окончателен и считать
    его каждый час незачем. Открытая — наоборот: её отметка меняется
    вместе с ценой, и переиспользовать вчерашнюю значило бы показать
    деньги, которых сейчас нет.
    """
    t0 = 1_700_000_000
    pairs = []
    for k in R.RULER_ORDER:
        if P.RULERS[k] not in pairs:
            pairs.append(P.RULERS[k])
    legs = [{"sym": "AAAUSDT", "at": float(t0)},
            {"sym": "BBBUSDT", "at": float(t0 + 3600), "state": "open"}]
    with tempfile.TemporaryDirectory() as td:
        # первый прогон: кэша нет — считается всё
        first = _cache_run(None, legs, td)
        assert sorted(first) == [("AAAUSDT", float(t0)),
                                 ("BBBUSDT", float(t0 + 3600))], first
        # кэш после него уже на диске; добавилось новое решение
        legs2 = legs + [{"sym": "CCCUSDT", "at": float(t0 + 7200)}]
        second = _cache_run(None, legs2, td)
        got = sorted(second)
        assert ("AAAUSDT", float(t0)) not in got, \
            f"закрытая позиция пересчитана заново: {got}"
        assert got == [("BBBUSDT", float(t0 + 3600)),
                       ("CCCUSDT", float(t0 + 7200))], got
        # и прямой вызов правила — на кэше, оставшемся ПОСЛЕ второго
        # прогона: там CCC уже закрыта (её только что посчитали), значит
        # заново нужна одна открытая BBB. Читается тот самый файл, что
        # написал прогон, — роундтрип кэша проверяется вместе с правилом.
        cache, why = P.read_cache(os.path.join(td, "recs.jsonl"))
        assert why is None, why
        assert cache[(tuple(pairs[0]), "CCCUSDT",
                      float(t0 + 7200))]["state"] == "closed"
        need = P.needs_replay(cache, legs2, pairs)
        assert {g["sym"] for g in need} == {"BBBUSDT"}, need
    print("ok  кэш: закрытые не пересчитываются, открытые и новые — да")


def test_cache_of_other_rules_is_refused_out_loud():
    """Кэш чужих правил не чинится молча.

    Смени геометрию — и записи кэша описывают ДРУГУЮ книгу. Подпись
    сверяется, расхождение называется словами и гонит полный пересчёт;
    молчаливое переиспользование выдало бы старую книгу за новую.
    """
    t0 = 1_700_000_000
    legs = [{"sym": "AAAUSDT", "at": float(t0)},
            {"sym": "BBBUSDT", "at": float(t0 + 3600)}]
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "recs.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"sig": {"edge": -1}}) + "\n")
            for g in legs:
                for pr in {P.RULERS[k] for k in R.RULER_ORDER}:
                    r = dict(_rec(g["at"], sym=g["sym"]),
                             pair=list(pr), sym=g["sym"], at=g["at"])
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        cache, why = P.read_cache(path)
        assert cache == {} and why == "правила реплея изменились", (cache, why)
        # без подписи вовсе — тоже отказ, а не «пустой кэш»
        with open(path + ".nosig", "w", encoding="utf-8") as f:
            f.write("\n")
        _c2, why2 = P.read_cache(path + ".nosig")
        assert why2 == "кэш без подписи правил", why2
        # и дорога: прогон считает ВСЁ заново
        only = _cache_run(None, legs, td)
        assert sorted(only) == [("AAAUSDT", float(t0)),
                                ("BBBUSDT", float(t0 + 3600))], only
    print("ok  кэш чужих правил: отказ назван словами, пересчёт полный")


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
            test_backtest_and_live_share_one_curve_and_stay_labelled()
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


def _control_contracts_are_money_not_coins():
    """Контроль: контракты посчитаны ДЕНЬГАМИ рунга, а не монетами.

    Ровно та ошибка единиц, которую эта правка и чинит на графике
    («0.25 $» вместо «6.25 $» в подсказке долива): доля нотионала без
    деления на цену выглядит числом и им не является. Тождество с
    симуляцией обязано упасть.
    """
    orig = R.avg_walk

    def money(fills, entry=None, notional=None):
        out = orig(fills, entry)
        if notional:
            q = 0.0
            for x in out:
                x["dq"] = x["w"] * float(notional)      # деньги, не монеты
                q += x["dq"]
                x["qty"] = q
        return out

    R.avg_walk = money
    try:
        try:
            test_contracts_walk_matches_the_simulation()
        except AssertionError:
            return True
        return False
    finally:
        R.avg_walk = orig


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


def test_shape_counts_positions_not_days():
    """Доля прибыльных СДЕЛОК и среднее время в сделке — свои меры.

    Доля зелёных ДНЕЙ на вопрос «сколько сделок в плюс» не отвечает:
    знаменатели разные, и один день может нести и прибыль, и убыток.
    Числа закреплены ЛИТЕРАЛОМ: посчитанные формулой от тех же строк,
    они прошли бы и на сломанной реализации.
    """
    D = 86400
    t0 = 1_767_225_600
    # три сделки одного дня: две в плюс, одна в минус — день зелёный,
    # а доля прибыльных сделок 2/3
    rows = [{"dep": 1000, "rules": R.RULES, "sym": "AUSDT",
             "at": t0, "exit_ts": t0 + 3600 * 2, "usd": 5.0,
             "written_at": t0 + 3600 * 3, "lev": 1.0, "margin": 25.0,
             "pnl_frac": 0.2, "exit": "тейк"},
            {"dep": 1000, "rules": R.RULES, "sym": "BUSDT",
             "at": t0, "exit_ts": t0 + 3600 * 4, "usd": 3.0,
             "written_at": t0 + 3600 * 5, "lev": 1.0, "margin": 25.0,
             "pnl_frac": 0.12, "exit": "тейк"},
            {"dep": 1000, "rules": R.RULES, "sym": "CUSDT",
             "at": t0, "exit_ts": t0 + 3600 * 6, "usd": -2.0,
             "written_at": t0 + 3600 * 7, "lev": 1.0, "margin": 25.0,
             "pnl_frac": -0.08, "exit": "стоп"},
            # второй день, ДВЕ убыточные сделки по 12 часов: доли
            # нарочно РАЗНЫЕ (0.4 против 0.5) — совпади они, подмена
            # одной меры другой прошла бы мимо проверки
            {"dep": 1000, "rules": R.RULES, "sym": "DUSDT",
             "at": t0 + D, "exit_ts": t0 + D + 3600 * 12, "usd": -1.0,
             "written_at": t0 + D + 3600 * 13, "lev": 1.0, "margin": 25.0,
             "pnl_frac": -0.04, "exit": "стоп"},
            {"dep": 1000, "rules": R.RULES, "sym": "EUSDT",
             "at": t0 + D, "exit_ts": t0 + D + 3600 * 12, "usd": -1.0,
             "written_at": t0 + D + 3600 * 13, "lev": 1.0, "margin": 25.0,
             "pnl_frac": -0.04, "exit": "стоп"}]
    st = P._stats(rows, 1000.0)
    assert st["win"] == 0.4, st["win"]                 # 2 из 5
    assert st["day_green"] == 0.5, st["day_green"]     # 1 день из 2
    # (2 + 4 + 6 + 12 + 12) / 5 = 7.2 ч от первого рунга до выхода
    assert st["hold_h"] == 7.2, st["hold_h"]
    assert st["hold_med_h"] == 6.0, st["hold_med_h"]
    print("ok  форма: прибыльных сделок %.2f при зелёных днях %.2f, "
          "в сделке %.1f ч" % (st["win"], st["day_green"], st["hold_h"]))


def test_worst_open_is_measured_and_missing_is_not_zero():
    """Худшая ОТКРЫТАЯ позиция считается сервером, а пустое — прочерк.

    Отметка открытой позиции не есть исход, поэтому «худшая» здесь
    значит «просевшая глубже всех сейчас». Позиция без отметки в
    сравнение не идёт вовсе: неизмеренное не есть ноль, и вернуть ей
    ноль значило бы объявить её ровной.
    """
    ps = [{"sym": "AUSDT", "mark_frac": -0.02, "mark_usd": -0.5},
          {"sym": "BUSDT", "mark_frac": -0.31, "mark_usd": -7.75},
          {"sym": "CUSDT", "mark_frac": 0.04, "mark_usd": 1.0}]
    st = R.open_stats(ps)
    assert st["worst_sym"] == "BUSDT", st
    assert abs(st["worst_frac"] + 0.31) < 1e-9, st
    assert abs(st["worst_usd"] + 7.75) < 1e-9, st
    # ни числа открытых, ни их отметки здесь НЕ пересчитывается: их
    # считает сам прогон и кладёт в артефакт, а второй счёт разошёлся бы
    assert "mark_usd" not in st and "n" not in st, sorted(st)
    empty = R.open_stats([{"sym": "DUSDT"}])
    assert empty["worst_frac"] is None and empty["worst_sym"] is None, empty
    assert R.open_stats([])["worst_frac"] is None
    print("ok  открытые: глубже всех %s (%.2f %%), без отметки — прочерк"
          % (st["worst_sym"], st["worst_frac"] * 100))


def test_journal_rotates_by_day_and_reader_takes_every_part():
    """Ротация: запись идёт в СУТОЧНЫЙ файл по метке решения, а чтение
    берёт все куски и снимает перекрытие.

    Ротация заведена не ради порядка. Журнал одним файлом вырос до
    11 МБ, упёрся в защиту от опасного коммита (5 МБ) и заморозил ВЕСЬ
    канал публикации на шестнадцать часов: ни логов заданий, ни ночного
    отчёта турнира не доехало. Значит проверять надо три вещи — куда
    легла строка, читается ли старый цельный файл наравне с кусками, и
    не удваивается ли решение, лежащее в обоих.
    """
    td = tempfile.mkdtemp()
    jp = os.path.join(td, "journal.jsonl")
    d1 = 1_788_000_000          # 2026-08-29 UTC
    d2 = d1 + 86400 * 2

    def row(at, sym):
        return {"dep": 1000, "at": at, "exit_ts": at + 3600, "sym": sym,
                "usd": 1.0, "written_at": at + 600, "rules": R.RULES,
                "ruler": "safe", "lev": 2.0, "margin": 25.0,
                "pnl_frac": 0.04, "exit": "тейк", "entry_px": 2.0,
                "exit_px": 2.1, "avg": 2.0, "depth": 1,
                "fills": [[at, 2.0, 0.25]]}

    a1, a2 = row(d1, "AAAUSDT"), row(d2, "BBBUSDT")
    P.append_journal([a1, a2], jp, log=lambda *_: None)
    # Строка легла в файл СВОИХ суток, а не сегодняшних: пересчёт по
    # прошлому обязан лежать своей датой, иначе запись датируется
    # моментом счёта.
    s1, s2 = R.shard_of(jp, d1), R.shard_of(jp, d2)
    assert s1.endswith("journal-2026-08-29.jsonl"), s1
    assert s1 != s2 and os.path.exists(s1) and os.path.exists(s2), (s1, s2)
    assert not os.path.exists(jp), "цельный файл снова растёт записью"

    # Старый цельный файл — ЗАПИСЬ, и читается наравне с кусками.
    old = row(d1 - 86400, "OLDUSDT")
    with open(jp, "w", encoding="utf-8") as f:
        f.write(json.dumps(old, ensure_ascii=False) + "\n")
    st = {}
    rows, bad = R.read_journal(jp, stats=st)
    assert sorted(r["sym"] for r in rows) == ["AAAUSDT", "BBBUSDT",
                                              "OLDUSDT"], rows
    assert not bad and st.get("parts") == 3, (bad, st)

    # Перекрытие: то же решение лежит и в старом файле, и в куске —
    # считать его дважды значило бы удвоить сделку в счёте.
    with open(jp, "a", encoding="utf-8") as f:
        f.write(json.dumps(a1, ensure_ascii=False) + "\n")
    st2 = {}
    rows2, _ = R.read_journal(jp, stats=st2)
    assert len(rows2) == 3, rows2
    assert st2.get("dups") == 1, st2

    # Разрезка цельного файла: числа книги от неё не меняются, а
    # оригинал остаётся на месте — удаление записи есть отдельное
    # решение владельца, а не побочный эффект правки.
    res = SPL.split(jp, log=lambda *_: None)
    rows3, _ = R.read_journal(jp)
    assert len(rows3) == 3, rows3
    assert os.path.exists(jp), "разрезка удалила оригинал"
    assert res["read"] == 2, res
    print("ok  журнал: суточные куски, старый файл читается, "
          f"перекрытие снято ({st2['dups']})")


def test_watchdog_runs_the_book_hourly_and_asks_when_it_last_counted():
    """Сторож ведёт книгу САМ, и вопрос он задаёт правильный.

    Владелец 2026-09-04 велел запустить книги «в live». Показ это делал
    с того же дня, а прогон оставался ручным заданием очереди — то есть
    книга шла только когда её толкали, и открытые позиции не считались
    сутками.

    Проверяется НАСТОЯЩИЙ блок `tools/watchdog_book.sh` с заглушками,
    а не пересказ его логики. Главный случай — последний: `--restat`
    переписывает артефакт, СОХРАНЯЯ `computed_at`, поэтому свежий файл
    со старой меткой обязан читаться как «давно не считали». Возьми
    сторож mtime — и одна диагностическая пересборка глушила бы книгу
    на час, а цепочка их — навсегда.
    """
    wd = os.path.join(HERE, os.pardir, os.pardir, "tools",
                      "watchdog_book.sh")
    src = open(os.path.abspath(wd), encoding="utf-8").read()
    a = src.index("# --- бумажные DCA-книги")
    b = src.index("# --- очередь заданий")
    block = src[a:b]
    return _run_watchdog_cases(block)


def _run_watchdog_cases(block):
    d = tempfile.mkdtemp()
    out = os.path.join(d, "research", "dca_paper", "out")
    os.makedirs(out)
    os.makedirs(os.path.join(d, "stubs"))
    art = os.path.join(out, "DCA-paper.json")

    def stub(name, body):
        p = os.path.join(d, "stubs", name)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)

    stub("pgrep", "#!/bin/sh\nexit ${PGREP_RC:-1}\n")
    stub("setsid", '#!/bin/sh\nshift 2\necho "$@" >> ran.log\n')
    env = dict(os.environ,
               PATH=os.path.join(d, "stubs") + os.pathsep + os.environ["PATH"])
    wrap = "now() { echo T; }\n" + block

    def run(hour, counted_age, busy=False, stamp=True, touch=True):
        """`counted_age` — возраст ПОСЛЕДНЕГО СЧЁТА; None — артефакта нет."""
        try:
            os.remove(os.path.join(d, "ran.log"))
        except OSError:
            pass
        if counted_age is None:
            if os.path.exists(art):
                os.remove(art)
        else:
            at = time.strftime("%Y-%m-%d %H:%M",
                               time.gmtime(time.time() - counted_age))
            body = {"books": {}}
            if stamp:
                body["computed_at"] = at
            with open(art, "w") as f:
                json.dump(body, f)
            if not touch:            # артефакт стар и по файлу тоже
                t = time.time() - counted_age
                os.utime(art, (t, t))
        e = dict(env, PGREP_RC=("0" if busy else "1"))
        stub("date", f'#!/bin/sh\nif [ "$1" = "-u" ] && '
                     f'[ "$2" = "+%H" ]; then echo {hour}; else '
                     f'exec /bin/date "$@"; fi\n')
        subprocess.run(["bash", "-c", wrap], cwd=d, env=e,
                       capture_output=True)
        return os.path.exists(os.path.join(d, "ran.log"))

    cases = [
        ("свежий счёт молчит", ("12", 600), False),
        ("час прошёл — считает", ("12", 7200), True),
        ("час 02 отдан турниру", ("02", 7200), False),
        ("час 06 отдан месячной книге", ("06", 7200), False),
        ("артефакта нет — считает", ("12", None), True),
    ]
    for name, args, want in cases:
        got = run(*args)
        assert got == want, f"{name}: запуск {got}, ожидалось {want}"
    assert run("12", 7200, busy=True) is False, "прогон уже идёт — не второй"
    assert run("12", 600, stamp=False) is True, \
        "метки нет — это НЕ «только что считали»"
    # Тот самый случай: `--restat` минуту назад, а счёт был два часа назад.
    assert run("12", 7200, touch=True) is True, \
        "свежий файл со старой меткой обязан читаться как «давно не считали»"
    print("ok  сторож: книга идёт каждый час, вопрос — когда СЧИТАЛИ, "
          "а не когда трогали файл")
    return True

def test_tail_marks_outcomes_and_refuses_an_entry_from_a_quote():
    """Правило хвоста держит ОБЕ границы, и они про разное.

    Исход, случившийся позже последнего бара ленты, посчитан по
    котировке — он помечается, иначе деньги по котировке потом не
    отделить от денег по принтам. А решение, чей ВХОД пришёлся бы на
    минуту без единого принта, выбрасывается целиком и по ВСЕМ линейкам
    разом: хвост продолжает начатое, а не заводит сделок, которых у книги
    на ленте не было. Выброшенные считаются числом — молча потерять
    решение модели нельзя.
    """
    t0 = 1_700_000_000
    last = float(t0 + 2 * H)            # докуда доходит ЛЕНТА у AAAUSDT
    pairs = [("sigma", 6.0), ("depth", 2.0)]
    recs = {}
    for pr in pairs:
        recs[pr] = [
            # закрылась внутри ленты — по принтам, пометки нет
            _rec(t0, hold_h=1.0, sym="AAAUSDT"),
            # выход позже последнего бара ленты — исход по котировке
            _rec(t0 + H, hold_h=3.0, sym="AAAUSDT"),
            # вход позже последнего бара ленты — такого решения книга
            # не берёт вовсе
            _rec(t0 + 3 * H, hold_h=1.0, sym="AAAUSDT"),
            # имя, у которого ленты не читали: границы нет, и правило
            # молчит — не выдумывать же её
            _rec(t0, hold_h=1.0, sym="BBBUSDT")]
    got = TL.apply(recs, {"AAAUSDT": last})
    assert got["entry_dropped"] == 1, got
    assert got["marked"] == len(pairs), got          # по одной на линейку
    for pr in pairs:
        ats = sorted(float(r["at"]) for r in recs[pr])
        assert float(t0 + 3 * H) not in ats, ats     # выброшено у ОБЕИХ
        assert len(recs[pr]) == 3, recs[pr]
        mk = {(r["sym"], float(r["at"])): r.get("tail") for r in recs[pr]}
        assert mk[("AAAUSDT", float(t0))] is None, mk
        assert mk[("AAAUSDT", float(t0 + H))] == 1, mk
        assert mk[("BBBUSDT", float(t0))] is None, mk
    print(f"ok  хвост: помечено исходов {got['marked']}, вход из котировки "
          f"отклонён у {got['entry_dropped']} решений, у имени без границы "
          f"правило молчит")


def test_tail_reaches_the_core_and_the_replay_signature():
    """Дорога правила до ядра и до кэша — отдельный предмет.

    Само правило проверяется прямым вызовом, а вот подаётся ли хвост в
    дорогой проход и знает ли о нём подпись кэша — только прогоном:
    кэш, посчитанный БЕЗ хвоста, описывает другую книгу и обязан быть
    отвергнут вслух, иначе прежние числа молча выдали бы себя за новые.
    """
    t0 = 1_700_000_000
    legs = [{"sym": "AAAUSDT", "at": float(t0)}]
    with tempfile.TemporaryDirectory() as td:
        _cache_run(None, legs, td)
        src = LAST_RUN.get("src")
        assert isinstance(src, TL.TailBars), \
            f"прогон подал в ядро не хвост, а {src!r}"
        # подпись реплея несёт хвост, и кэш без него не берётся
        assert "tail" in P.cache_sig(), P.cache_sig()
        path = os.path.join(td, "recs.jsonl")
        sig = dict(P.cache_sig())
        sig.pop("tail")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"sig": sig}, ensure_ascii=False) + "\n")
        cache, why = P.read_cache(path)
        assert cache == {} and why == "правила реплея изменились", (cache, why)
        # пометка исхода доезжает до СТРОКИ ЖУРНАЛА, а не живёт в кэше
        rows, _c, _o, _l = P.build_rows(
            {k: [dict(_rec(t0, sym="AAAUSDT"), tail=1)]
             for k in R.RULER_ORDER}, now=t0 + 10 * H, log=lambda m: None)
        assert rows and all(r.get("tail") == 1 for r in rows), rows[:1]
    print(f"ok  хвост доезжает до ядра ({type(src).__name__}), до подписи "
          f"кэша и до строки журнала")


def test_cut_position_gets_a_named_reason():
    """Оборванная позиция получает ПРИЧИНУ, и причин три разных.

    Правило хвоста снимает не всякий обрыв: если запись книги кончается
    там же, где лента (имя перестали писать вовсе), дописывать нечем.
    Тогда «оборванных N» без причины читается как «правило не работает»,
    и лечатся эти случаи разным. Символа, чьих баров прогон не читал
    вовсе (запись пришла из кэша), причина НЕ ИЗМЕРЕНА — выдумывать её
    хуже, чем назвать пропуском.
    """
    t0 = 1_700_000_000
    last = float(t0 + 2 * H)
    pr = ("sigma", 6.0)
    # книга кончилась ровно там, где кончились бары позиции
    a = _rec(t0, hold_h=1.0, sym="AAAUSDT")
    a["end_ts"] = last + 600.0
    b = _rec(t0, hold_h=1.0, sym="BBBUSDT")          # книги нет вовсе
    c = _rec(t0, hold_h=1.0, sym="CCCUSDT")          # баров не читали
    # книга у имени есть и ПОЗЖЕ, а в окне этой позиции её не было:
    # `last_book` держит самую позднюю минуту символа по всему прогону,
    # и приняв её за ответ, мы назвали бы причину, которой не было
    e = _rec(t0, hold_h=1.0, sym="AAAUSDT")
    e["end_ts"] = last - 600.0
    for r in (a, b, c, e):
        r["state"] = "cut"
    recs = {pr: [a, b, c, e]}
    got = TL.apply(recs, {"AAAUSDT": last, "BBBUSDT": last},
                   {"AAAUSDT": last + 600.0})
    assert a["cut_why"] == TL.CUT_BOOK_SHORT, a
    assert a["book_end"] == last + 600.0, a
    assert b["cut_why"] == TL.CUT_NO_BOOK, b
    assert "book_end" not in b, b
    assert c["cut_why"] == TL.CUT_UNKNOWN, c
    assert e["cut_why"] == TL.CUT_BOOK_HOLE, e
    assert got["cut_why"] == {TL.CUT_BOOK_SHORT: 1, TL.CUT_NO_BOOK: 1,
                              TL.CUT_UNKNOWN: 1, TL.CUT_BOOK_HOLE: 1}, got
    # закрытой позиции причина не приписывается: её обрыва не было
    d = _rec(t0, hold_h=1.0, sym="AAAUSDT")
    d["state"] = "closed"
    TL.apply({pr: [d]}, {"AAAUSDT": last}, {"AAAUSDT": last})
    assert "cut_why" not in d, d
    print("ok  причина обрыва названа ПО ПОЗИЦИИ: книга кончилась раньше / "
          "книги нет вовсе / книга не в окне / не измерена; закрытой "
          "причина не приписана")


def test_contracts_walk_matches_the_simulation():
    """Контракты позиции = то, что купила симуляция, а не второй счёт.

    Просьба владельца 2026-09-05: у сделки видеть размер в КОНТРАКТАХ и
    общее количество в позиции. Считать их страница не вправе — деньги
    рунга и его цена уже лежат в записи, и второе такое умножение
    разошлось бы с симуляцией. Проверяется тождество: сумма `dq` по
    рунгам равна `qty` симуляции (деньги / средняя цена), и последний
    шаг `qty` равен ей же.

    Рядом — два инварианта показа: без нотионала полей нет вовсе
    (неизмеримое не есть ноль), и с нотионалом прежние поля не
    шелохнулись (правка не вправе двигать ТВХ).
    """
    import ladder as L
    # путь: вход 100, низ до 90 (долив), дальше вверх
    bars = [(0.0, 100.0, 101.0, 100.0, 100.5, 5.0),
            (60.0, 100.5, 101.0, 89.0, 95.0, 5.0),
            (120.0, 95.0, 96.0, 94.0, 95.5, 5.0)]
    cap, lev = 25.0, 4.0
    r = L.simulate_dca(bars, [100.0, 90.0], [0.5, 0.5], cap, lev, 0.02)
    nt = cap * lev
    w = R.avg_walk(r["fills"], r.get("entry_px"), nt)
    qty_sim = r["filled_notional"] / r["avg"]          # деньги / средняя
    assert len(w) == 2, w
    assert abs(sum(x["dq"] for x in w) - qty_sim) < 1e-9, (w, qty_sim)
    assert abs(w[-1]["qty"] - qty_sim) < 1e-9, (w[-1], qty_sim)
    # без нотионала — полей нет, и прежние числа бит в бит
    w0 = R.avg_walk(r["fills"], r.get("entry_px"))
    assert all("dq" not in x and "qty" not in x for x in w0), w0
    assert [x["avg"] for x in w0] == [x["avg"] for x in w], (w0, w)
    # нотионал берётся из записи одной функцией, и запись без плеча
    # (или без маржи) контрактов не получает
    assert abs(R.notional_of({"margin": 25.0, "lev": 4.0}) - 100.0) < 1e-12
    assert R.notional_of({"margin": 25.0}) is None
    assert R.notional_of({"lev": 4.0}) is None
    assert R.notional_of({"margin": 0.0, "lev": 4.0}) is None


TESTS = [test_shape_counts_positions_not_days,
    test_contracts_walk_matches_the_simulation,
         test_journal_rotates_by_day_and_reader_takes_every_part,
         test_worst_open_is_measured_and_missing_is_not_zero,
         test_ticket_clears_the_exchange_floor,
         test_ticket_is_squeezed_between_the_floor_and_the_peak,
    test_ticket_rule_is_one_formula_for_every_mode,
    test_gated_mode_is_deployed_at_its_own_peak,
         test_cut_position_gets_a_named_reason,
         test_one_per_name_applied_before_cash,
         test_backtest_and_live_share_one_curve_and_stay_labelled,
    test_open_position_is_not_a_closed_one, test_journal_appends_only_new,
         test_report_names_what_is_not_modelled,
         test_day_concentration_is_measured_and_not_faked,
         test_short_record_says_not_measured_not_zero,
         test_two_rulers_are_two_books_and_optimal_is_untouched,
         test_aggressive_gate_takes_only_levered_entries,
         test_declared_peak_is_checked_against_the_measured_one,
         test_legacy_row_reads_as_the_ruler_it_was_written_with,
         test_cash_refusals_reach_the_report_and_survive_restat,
         test_rules_change_starts_a_fresh_record,
         test_journal_path_is_resolved_at_call_time,
         test_cache_replays_new_and_open_but_not_closed,
         test_cache_of_other_rules_is_refused_out_loud,
         test_watchdog_runs_the_book_hourly_and_asks_when_it_last_counted,
         test_tail_marks_outcomes_and_refuses_an_entry_from_a_quote,
         test_tail_reaches_the_core_and_the_replay_signature]

def _control_journal_path_frozen():
    """Путь журнала снова берётся значением по умолчанию: прогон с
    подменённым журналом пишет в настоящую запись книги."""
    orig = P.append_journal
    # Замерзает на ЧУЖОМ пути, а не на настоящем журнале: контроль
    # воспроизводит дефект, а не совершает его — записи книги он
    # трогать не вправе ни при какой подделке.
    stuck = os.path.join(tempfile.mkdtemp(), "frozen.jsonl")

    def frozen(rows, path=stuck, log=print):
        return orig(rows, path=path, log=log)

    P.append_journal = frozen
    try:
        try:
            test_journal_path_is_resolved_at_call_time()
        except AssertionError:
            return True
        return False
    finally:
        P.append_journal = orig


def _control_cache_reuses_open():
    """Состояние в кэше не читается: открытая позиция берётся вчерашней.

    Ровно тот дефект, которого правило и не допускает — отметка живой
    позиции меняется с ценой, и переиспользовать её значит показать
    деньги, которых сейчас нет.
    """
    orig = P.needs_replay

    def loose(cache, legs, pairs):
        need = []
        for g in legs:
            sym, at = str(g["sym"]), round(float(g["at"]), 3)
            if any(cache.get((tuple(pr), sym, at)) is None for pr in pairs):
                need.append(g)
        return need

    P.needs_replay = loose
    try:
        try:
            test_cache_replays_new_and_open_but_not_closed()
        except AssertionError:
            return True
        return False
    finally:
        P.needs_replay = orig


def _control_cache_sig_ignored():
    """Подпись правил не сверяется: кэш чужой геометрии молча идёт в дело,
    и книга новых правил считалась бы наполовину по старым."""
    orig = P.read_cache

    def blind(path=None):
        path = path or P.cache_path()
        out = {}
        try:
            with open(path, encoding="utf-8") as f:
                for i, ln in enumerate(f):
                    ln = ln.strip()
                    if not ln or i == 0:
                        continue
                    r = json.loads(ln)
                    out[(tuple(r["pair"]), r["sym"],
                         round(float(r["at"]), 3))] = r
        except (OSError, ValueError):
            return {}, "кэш не читается"
        return out, None

    P.read_cache = blind
    try:
        try:
            test_cache_of_other_rules_is_refused_out_loud()
        except AssertionError:
            return True
        return False
    finally:
        P.read_cache = orig


def _control_floor_one_for_everyone():
    """Пол назначен один на всех: режим с гейтом не может взять мелкий
    билет, и на $1k у него остаётся вчетверо меньше мест, чем позволяет
    его собственная арифметика."""
    orig = R.floor_of
    R.floor_of = lambda k: R.TICKET_MIN
    try:
        try:
            test_ticket_is_squeezed_between_the_floor_and_the_peak()
        except AssertionError:
            return True
        return False
    finally:
        R.floor_of = orig


def _control_peak_from_the_pool():
    """Пик берётся общий (прежнее поведение): режим с гейтом снова стоит
    недогруженным — ровно тот дефект, ради которого правка и делалась."""
    orig = R.peak_of
    R.peak_of = lambda k: R.PEAK_SEEN
    try:
        try:
            test_gated_mode_is_deployed_at_its_own_peak()
        except AssertionError:
            return True
        return False
    finally:
        R.peak_of = orig


def _control_state_ignored():
    """Состояние позиции не читается: живая попадает в журнал закрытой —
    ровно тот дефект, ради которого состояние и заведено."""
    orig = D6.position_state
    D6.position_state = lambda r, data_end: "closed"
    # состояние приходит в записи, поэтому подделываем сам разбор строк
    import run_paper as PP
    was = PP.build_rows

    def patched(by_ruler, now=None, log=print):
        clean = {k: [dict(r, state="closed") for r in v]
                 for k, v in by_ruler.items()}
        return was(clean, now=now, log=log)
    PP.build_rows = patched
    try:
        try:
            test_open_position_is_not_a_closed_one()
        except AssertionError:
            return True
        return False
    finally:
        PP.build_rows = was
        D6.position_state = orig


def _control_win_counts_days():
    """Доля прибыльных считается по ДНЯМ, а не по сделкам: день с двумя
    плюсами и одним минусом объявляется целиком выигранным."""
    src = P._stats

    def broken(rows, deposit):
        st = src(rows, deposit)
        if st:
            st["win"] = st["day_green"]
        return st
    P._stats = broken
    try:
        try:
            test_shape_counts_positions_not_days()
        except AssertionError:
            return True
        return False
    finally:
        P._stats = src


def _control_missing_mark_reads_as_zero():
    """Позиция без отметки читается ровной: «не измерено» подменяется
    нулём — ровно тот класс, от которого защищает прочерк."""
    src = R.open_stats

    def broken(positions):
        ps = [dict(p, mark_frac=(p.get("mark_frac") or 0.0),
                   mark_usd=(p.get("mark_usd") or 0.0))
              for p in (positions or [])]
        return src(ps)
    R.open_stats = broken
    try:
        try:
            test_worst_open_is_measured_and_missing_is_not_zero()
        except AssertionError:
            return True
        return False
    finally:
        R.open_stats = src


def _control_watchdog_asks_mtime():
    """Сторож снова смотрит на mtime файла вместо метки счёта.

    Ровно дефект, ради которого триггер и переписан: `--restat` трогает
    файл, не считая, и по mtime книга выглядела бы посчитанной.
    """
    wd = os.path.join(HERE, os.pardir, os.pardir, "tools",
                      "watchdog_book.sh")
    src = open(os.path.abspath(wd), encoding="utf-8").read()
    a = src.index("# --- бумажные DCA-книги")
    b = src.index("# --- очередь заданий")
    block = src[a:b]
    lit = 'dca_at=$(grep -o'
    assert lit in block, "подделка НЕ легла: литерала нет"
    broken = block.replace(
        lit,
        'dca_at=$(date -u -d "@$(stat -c %Y \"$DCAP\")" '
        '+"%Y-%m-%d %H:%M"); : $(grep -o', 1)
    try:
        _run_watchdog_cases(broken)
    except AssertionError:
        return True
    return False


def _poison_run_paper(lit, repl, probe):
    """Прогнать `probe` на ИСПОРЧЕННОМ `run_paper.py` и вернуть файл.

    Правило живёт строкой внутри прогона, подменить функцию нечем.
    Копия кладётся рядом во временный каталог и возвращается
    копированием: `git checkout` для этого не инструмент — он однажды
    снёс всю несохранённую работу файла. Кэш байткода снимается руками:
    питон считает `.pyc` свежим по паре «mtime в целых секундах,
    размер», и подделка успевала исполниться прежним кодом.
    """
    import importlib
    import shutil
    path = os.path.join(HERE, "run_paper.py")
    src = open(path, encoding="utf-8").read()
    assert lit in src, f"подделка НЕ легла: литерала нет ({lit!r})"
    keep = os.path.join(tempfile.mkdtemp(prefix="run-paper-"), "run_paper.py")
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, repl, 1))
        pyc = os.path.join(HERE, "__pycache__")
        if os.path.isdir(pyc):
            for f in os.listdir(pyc):
                if f.startswith("run_paper."):
                    os.remove(os.path.join(pyc, f))
        importlib.reload(P)
        try:
            probe()
        except AssertionError:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(P)


def _control_tail_never_reaches_the_core():
    """Хвост построен, но в дорогой проход не подан.

    Ровно тот класс, что уже дважды ловился: правило есть, дороги до
    него нет, и снаружи книга выглядит считающей по хвосту.
    """
    return _poison_run_paper(
        "rulers=pairs, legs=legs, src=src,",
        "rulers=pairs, legs=legs,",
        test_tail_reaches_the_core_and_the_replay_signature)


def _control_tail_out_of_the_replay_signature():
    """Подпись реплея не знает хвоста: кэш прежних правил взялся бы молча."""
    return _poison_run_paper(
        '            "tail": 1}', "            }",
        test_tail_reaches_the_core_and_the_replay_signature)


def _control_tail_entry_from_a_quote_allowed():
    """Граница входа снята: хвост заводит сделки, которых у книги не было."""
    orig = TL.apply

    def loose(recs, last_tape):
        marked = 0
        for lst in recs.values():
            for r in lst:
                lt = last_tape.get(r["sym"])
                if lt is not None and float(r.get("exit_ts") or 0.0) > lt:
                    r["tail"] = 1
                    marked += 1
        return {"entry_dropped": 0, "marked": marked}

    TL.apply = loose
    try:
        try:
            test_tail_marks_outcomes_and_refuses_an_entry_from_a_quote()
        except AssertionError:
            return True
        return False
    finally:
        TL.apply = orig

def _control_cut_reason_is_one_for_all():
    """Причина обрыва одна на всех: «книги нет вовсе» приписывается и
    тому имени, у которого книга дотянулась дальше ленты. Различить два
    случая тогда нечем, а лечатся они разным."""
    was = TL.cut_reason
    TL.cut_reason = lambda r, last_tape, last_book: TL.CUT_NO_BOOK
    try:
        try:
            test_cut_position_gets_a_named_reason()
        except AssertionError:
            return True
        return False
    finally:
        TL.cut_reason = was


def _control_cut_reason_by_symbol_not_position():
    """Причина берётся ПО ИМЕНИ: книга, дотянувшаяся у соседнего окна,
    объявляется дотянувшейся и здесь. Тогда «книга кончилась раньше
    планового конца» стоит там, где её в окне не было вовсе."""
    was = TL.cut_reason

    def broken(r, last_tape, last_book):
        sym = r["sym"]
        if sym not in last_tape:
            return TL.CUT_UNKNOWN
        return (TL.CUT_BOOK_SHORT if sym in last_book else TL.CUT_NO_BOOK)
    TL.cut_reason = broken
    try:
        try:
            test_cut_position_gets_a_named_reason()
        except AssertionError:
            return True
        return False
    finally:
        TL.cut_reason = was


CONTROLS = [("хвост не доезжает до ядра", _control_tail_never_reaches_the_core),
            ("подпись реплея не знает хвоста",
             _control_tail_out_of_the_replay_signature),
            ("вход из котировки разрешён",
             _control_tail_entry_from_a_quote_allowed),
            ("сторож смотрит mtime вместо метки счёта",
             _control_watchdog_asks_mtime),
            ("доля прибыльных считается по дням", _control_win_counts_days),
            ("отметки нет — читается нулём",
             _control_missing_mark_reads_as_zero),
            ("путь журнала замёрз на импорте", _control_journal_path_frozen),
            ("кэш переиспользует открытую", _control_cache_reuses_open),
            ("подпись правил кэша не сверяется", _control_cache_sig_ignored),
            ("свод складывает вперёд и пересчёт", _control_no_split),
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
            ("контракты посчитаны деньгами, а не монетами",
             _control_contracts_are_money_not_coins),
            ("гейта плеча нет вовсе", _control_gate_is_gone),
            ("гейт назначен всем режимам", _control_gate_on_every_ruler),
            ("пол билета один на все режимы", _control_floor_one_for_everyone),
            ("пик билета взят у пула", _control_peak_from_the_pool),
            ("состояние позиции не читается", _control_state_ignored),
            ("причина обрыва одна на всех",
             _control_cut_reason_is_one_for_all),
            ("причина обрыва берётся по имени, а не по позиции",
             _control_cut_reason_by_symbol_not_position)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
