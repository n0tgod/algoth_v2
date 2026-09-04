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


def test_slots_grow_with_deposit():
    """Три книги отличаются РОВНО числом мест: 40 / 400 / 4000."""
    got = [R.slots(d) for d in R.DEPOSITS]
    assert got == [40, 400, 4000], got
    # доля на позицию при этом падает — билет один
    for d in R.DEPOSITS:
        assert abs(R.share(d) * d - R.TICKET) < 1e-9, d
    print(f"ok  места: {got} при одном билете ${R.TICKET:g}")


def test_one_per_name_applied_before_cash():
    """Правило биржи не зависит от депозита и применяется ДО раздачи."""
    t0 = 1_700_000_000
    recs = [_rec(t0, hold_h=5.0, sym="AAAUSDT"),
            _rec(t0 + 60, hold_h=5.0, sym="AAAUSDT"),
            _rec(t0 + 120, hold_h=5.0, sym="BBBUSDT")]
    rows, cells, one = P.build_rows(recs, now=t0 + 10 * H, log=lambda *_: None)
    assert one["skipped_repeats"] == 1 and one["kept"] == 2, one
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
        b = s["books"]["1000"]
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


TESTS = [test_ticket_clears_the_exchange_floor, test_slots_grow_with_deposit,
         test_one_per_name_applied_before_cash,
         test_forward_and_restored_never_mix, test_journal_appends_only_new,
         test_report_names_what_is_not_modelled]

CONTROLS = [("свод складывает вперёд и пересчёт", _control_no_split),
            ("билет ниже пола биржи", _control_ticket_below_floor),
            ("правило одной позиции снято", _control_one_per_name_off),
            ("журнал переписывает строку", _control_journal_overwrites)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; "
          f"{len(CONTROLS)} отрицательных контролей кусаются")


if __name__ == "__main__":
    main()
