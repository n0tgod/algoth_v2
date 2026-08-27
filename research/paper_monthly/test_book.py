#!/usr/bin/env python3
"""
Тесты бумажной месячной книги.

Главный — на заглядывание: будущее переписывается целиком, и решение
обязано не шелохнуться ни на бит. Рядом негативный контроль, что тест
кусается (изменение ПРОШЛОГО решение меняет), — иначе проверка
проходила бы на коде, который вообще не смотрит на данные.

Второй столп — честное против восстановленного: свод не смешивает их
никогда, и книга без записанных вперёд решений обязана говорить это
словами, а не показывать кривую бэктеста как трек.

    python3 research/paper_monthly/test_book.py
"""

import io
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "d1_seconds"))

import book as B                                          # noqa: E402
import run_d1 as R                                        # noqa: E402

FAILED = []
HOUR_MS = 3_600_000


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


class Fake:
    """Синтетический источник: ряды 1h с общей волной и возвратом.

    `rho < 1` — идиосинкразия возвращается к среднему, значит отставший
    от волны актив обгоняет её в следующем окне: книга обязана это
    находить. `rho = 1` — случайное блуждание, книга обязана давать ноль.
    """

    def __init__(self, t0_day="2026-04-01", days=200, n=40, rho=0.995,
                 seed=5, dead=None):
        rng = np.random.default_rng(seed)
        self.n_bars = days * 24
        self.t0 = int(np.datetime64(t0_day + "T00:00:00", "ms")
                      .astype("int64"))
        wave = np.cumsum(rng.normal(0.0, 0.004, self.n_bars))
        self.syms = [f"S{i:03d}USDT" for i in range(n)]
        self.px = {}
        for j, s in enumerate(self.syms):
            e = rng.normal(0.0, 0.006, self.n_bars)
            idio = np.zeros(self.n_bars)
            for i in range(1, self.n_bars):
                idio[i] = rho * idio[i - 1] + e[i]
            self.px[s] = np.exp(wave + idio)
        self.dead = dead or {}
        self.times = self.t0 + np.arange(self.n_bars) * HOUR_MS

    def load(self, con, symbols, t0, t1, step="1h", interval="1m"):
        a = int(np.datetime64(t0 + "T00:00:00", "ms").astype("int64"))
        b = int(np.datetime64(t1 + "T00:00:00", "ms").astype("int64"))
        m = (self.times >= a) & (self.times < b)
        out = {}
        for s in symbols:
            if s not in self.px:
                continue
            t, c = self.times[m], self.px[s][m]
            cut = self.dead.get(s)
            if cut is not None:
                keep = t < cut
                t, c = t[keep], c[keep]
            if len(t):
                out[s] = (t.copy(), c.copy())
        return out

    def universe(self):
        return {s[:-4]: {"binance_symbol": s, "bybit_symbol": s}
                for s in self.syms}

    def state_at(self, liq, universe, at):
        return {a: {"share_traded": 1.0, "turnover": 1e7}
                for a in universe}


def install(fake, monkey=True):
    """Подменяет загрузку и ликвидность; возвращает восстановитель."""
    old = (B.S.load, B.PR.state_at)
    B.S.load = fake.load
    B.PR.state_at = fake.state_at
    return lambda: (setattr(B.S, "load", old[0]),
                    setattr(B.PR, "state_at", old[1]))


def test_decision_ignores_the_future():
    """Будущее переписано целиком — решение обязано совпасть до бита."""
    f = Fake()
    undo = install(f)
    try:
        at = "2026-06-15"
        uni = f.universe()
        a = B.decide(None, at, None, uni, None)
        check("решение принято", a is not None, "")
        cut = int(np.datetime64(at + "T00:00:00", "ms").astype("int64"))
        after = f.times >= cut
        for s in f.syms:                       # будущее — в мусор
            f.px[s][after] *= np.linspace(1.0, 5.0, int(after.sum()))
        b = B.decide(None, at, None, uni, None)
        same = (a["legs"] == b["legs"])
        check("решение не изменилось после переписи будущего", same,
              f"{a['legs'][:1]} против {b['legs'][:1]}")
    finally:
        undo()


def test_signal_identical_with_and_without_future_loaded():
    """β и сигнал обязаны СОВПАСТЬ при загруженном будущем и без него.

    Проверка на заглядывание, которая действительно кусается. Тест
    выше (порча будущего при `decide`) сам по себе слаб: при решении
    будущее вообще не грузится, и он проходит даже на сдвинутой
    границе окна — то есть доказывает работу защиты №2, ничего не
    говоря о защите №1. Здесь будущее в матрице ЕСТЬ (как при
    разборе), и любой сдвиг `i_t` немедленно уводит и β, и сигнал."""
    f = Fake()
    undo = install(f)
    try:
        uni = f.universe()
        a = B.build(None, "2026-06-15", None, uni, None, forward=False)
        b = B.build(None, "2026-06-15", None, uni, None, forward=True)
        check("оба построения удались", a is not None and b is not None,
              "")
        na, ba, sa = a[0], a[1], a[2]
        nb, bb, sb = b[0], b[1], b[2]
        check("состав совпал", list(na) == list(nb), "")
        check("β не зависит от наличия будущего",
              np.allclose(ba, bb, equal_nan=True, atol=1e-12),
              f"{np.nanmax(np.abs(np.asarray(ba) - np.asarray(bb)))}")
        check("сигнал не зависит от наличия будущего",
              np.allclose(sa, sb, equal_nan=True, atol=1e-12),
              f"{np.nanmax(np.abs(np.asarray(sa) - np.asarray(sb)))}")
    finally:
        undo()


def test_changing_the_past_does_change_the_decision():
    """Негативный контроль самого теста: правка ПРОШЛОГО обязана
    решение поменять — иначе проверка выше проходила бы и на коде,
    который данных не читает вовсе."""
    f = Fake()
    undo = install(f)
    try:
        at = "2026-06-15"
        uni = f.universe()
        a = B.decide(None, at, None, uni, None)
        cut = int(np.datetime64(at + "T00:00:00", "ms").astype("int64"))
        before = f.times < cut
        f.px[f.syms[0]][before] *= np.linspace(
            1.0, 3.0, int(before.sum()))
        b = B.decide(None, at, None, uni, None)
        check("правка прошлого меняет решение",
              a["legs"] != b["legs"], "не изменилось")
    finally:
        undo()


def test_book_weights():
    f = Fake()
    undo = install(f)
    try:
        rec = B.decide(None, "2026-06-15", None, f.universe(), None)
        w = [l["w"] for l in rec["legs"]]
        check("Σ|w| = 1", abs(sum(abs(x) for x in w) - 1.0) < 1e-9,
              f"{sum(abs(x) for x in w)}")
        check("ноги симметричны",
              abs(sum(w)) < 1e-9, f"{sum(w)}")
        longs = [l for l in rec["legs"] if l["w"] > 0]
        shorts = [l for l in rec["legs"] if l["w"] < 0]
        check("лонг набран по верхним сигналам",
              min(l["sig"] for l in longs)
              >= max(l["sig"] for l in shorts),
              f"{min(l['sig'] for l in longs)} против "
              f"{max(l['sig'] for l in shorts)}")
    finally:
        undo()


def test_reversion_is_found_and_random_walk_is_not():
    """Калибровка: подсаженный возврат книга находит, на случайном
    блуждании даёт около ноля. Без этой пары отрицательный результат
    неотличим от сломанной загрузки."""
    for rho, want_pos, nm in ((0.99, True, "возврат"),
                              (1.0, False, "блуждание")):
        f = Fake(rho=rho, seed=9)
        undo = install(f)
        try:
            uni = f.universe()
            nets = []
            for d in range(0, 60, 10):
                at = (date.fromisoformat("2026-05-20")
                      + timedelta(days=d)).isoformat()
                rec = B.decide(None, at, None, uni, None)
                if rec is None:
                    continue
                got = B.resolve(None, rec, None, uni, None)
                if got:
                    nets.append(got["gross_bp"])
            if want_pos:
                check(f"{nm}: брутто положительно",
                      nets and float(np.mean(nets)) > 50,
                      f"{nets}")
            else:
                check(f"{nm}: брутто около ноля",
                      nets and abs(float(np.mean(nets))) < 120,
                      f"{nets}")
        finally:
            undo()


def test_delisted_leg_is_held_to_the_last_bar():
    """Нога, чей ряд оборвался внутри месяца, СЧИТАЕТСЯ и помечается —
    это исправление robust.py, стоившее зонду 44 б.п./мес."""
    f = Fake()
    undo = install(f)
    try:
        at = "2026-06-15"
        uni = f.universe()
        rec = B.decide(None, at, None, uni, None)
        victim = rec["legs"][0]["sym"]
        cut = int(np.datetime64("2026-06-25T00:00:00", "ms")
                  .astype("int64"))
        f.dead[victim] = cut
        got = B.resolve(None, rec, None, uni, None)
        leg = next(l for l in got["legs"] if l["sym"] == victim)
        check("оборванная нога посчитана",
              leg["resid_bp"] is not None, f"{leg}")
        check("оборванная нога помечена", leg["truncated"] is True,
              f"{leg}")
        check("баров меньше полного месяца",
              0 < leg["bars"] < B.H_DAYS * 24, f"{leg['bars']}")
        check("вес не потерян", got["missing_weight"] == 0.0,
              f"{got['missing_weight']}")
    finally:
        undo()


def test_net_arithmetic_with_funding():
    """Нетто = брутто − издержки − funding, числом."""
    f = Fake()
    undo = install(f)
    try:
        at = "2026-06-15"
        uni = f.universe()
        rec = B.decide(None, at, None, uni, None)
        day = 86_400_000
        t0 = B.FS.ms(at)
        funding = {}
        for lg in rec["legs"]:
            t = np.array([t0 + i * 8 * 3_600_000 for i in range(90)],
                         dtype=np.int64)
            funding[lg["sym"]] = (t, np.full(90, 1e-4))
        got = B.resolve(None, rec, None, uni, None, funding)
        check("funding посчитан", got["funding_bp"] is not None, "")
        check("нетто = брутто − издержки − funding",
              abs(got["net_bp"] - (got["gross_bp"] - B.COST_BP
                                   - got["funding_bp"])) < 0.02,
              f"{got['net_bp']} против {got['gross_bp']} − "
              f"{B.COST_BP} − {got['funding_bp']}")
        check("равные ставки на симметричных ногах гасятся",
              abs(got["funding_bp"]) < 1e-6, f"{got['funding_bp']}")
        check("недоучёта нет", got["funding_uncovered"] == 0.0,
              f"{got['funding_uncovered']}")
    finally:
        undo()


def test_ahead_flag():
    at = "2026-06-15"
    t = B.ms(at) / 1000.0
    check("записано в день сечения — вперёд",
          B.ahead({"at": at, "written_at": t + 3600}), "")
    check("записано через сутки — ещё вперёд",
          B.ahead({"at": at, "written_at": t + 86000}), "")
    check("записано через неделю — восстановлено",
          not B.ahead({"at": at, "written_at": t + 7 * 86400}), "")
    check("без метки — восстановлено", not B.ahead({"at": at}), "")


def test_summary_never_mixes_groups():
    at1, at2 = "2026-06-15", "2026-06-16"
    dec = [{"at": at1, "written_at": B.ms(at1) / 1000.0 + 60},
           {"at": at2, "written_at": B.ms(at2) / 1000.0 + 9e5}]
    res = [{"at": at1, "net_bp": 100.0, "gross_bp": 111.0,
            "truncated_legs": 0, "funding_bp": None},
           {"at": at2, "net_bp": -500.0, "gross_bp": -489.0,
            "truncated_legs": 2, "funding_bp": None}]
    sm = B.summarise(dec, res)
    check("честная группа — один транш",
          sm["ahead"]["tranches"] == 1
          and sm["ahead"]["net_mean_bp"] == 100.0, f"{sm['ahead']}")
    check("восстановленная — другой",
          sm["backfilled"]["tranches"] == 1
          and sm["backfilled"]["net_mean_bp"] == -500.0,
          f"{sm['backfilled']}")


def test_verdict_says_when_there_is_no_track():
    empty = B.summarise([{"at": "2026-06-15",
                          "written_at": B.ms("2026-06-15") / 1000.0
                          + 9e5}],
                        [{"at": "2026-06-15", "net_bp": 900.0,
                          "gross_bp": 911.0, "truncated_legs": 0,
                          "funding_bp": None}])
    v = B.verdict_phrase(empty)
    check("книга без честных наблюдений говорит это словами",
          "настоящих наблюдений пока НЕТ" in v, v)
    check("и называет восстановленное бэктестом", "бэктест" in v, v)
    live = B.summarise(
        [{"at": "2026-06-15", "written_at": B.ms("2026-06-15") / 1000.0}],
        [{"at": "2026-06-15", "net_bp": 50.0, "gross_bp": 61.0,
          "truncated_legs": 0, "funding_bp": None}])
    check("с честными наблюдениями фраза другая",
          "записано вперёд 1" in B.verdict_phrase(live),
          B.verdict_phrase(live))


def test_catchup_is_idempotent():
    """Повторный прогон не задваивает журнал и не переписывает его."""
    tmp = tempfile.mkdtemp()
    f = Fake()
    undo = install(f)
    old = (B.DEC, B.RES)
    B.DEC = os.path.join(tmp, "d.jsonl")
    B.RES = os.path.join(tmp, "r.jsonl")
    try:
        uni = f.universe()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            a1, b1 = B.catchup(None, None, uni, None, {},
                               start="2026-06-15", end="2026-06-18",
                               log=lambda *x: None)
            a2, b2 = B.catchup(None, None, uni, None, {},
                               start="2026-06-15", end="2026-06-18",
                               log=lambda *x: None)
        check("первый прогон записал решения", a1 == 4, f"{a1}")
        check("второй не добавил ничего", a2 == 0 and b2 == 0,
              f"{a2} {b2}")
        check("журнал не задвоился",
              len(B.read_jsonl(B.DEC)) == 4,
              f"{len(B.read_jsonl(B.DEC))}")
        check("незрелые транши не разбираются", b1 == 0, f"{b1}")
        with contextlib.redirect_stdout(buf):
            _, b3 = B.catchup(None, None, uni, None, {},
                              start="2026-06-15", end="2026-07-20",
                              log=lambda *x: None)
        check("созревшие транши разобраны", b3 >= 4, f"{b3}")
    finally:
        undo()
        B.DEC, B.RES = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_empty_run_explains_itself():
    """Пустой прогон обязан назвать причины и край хранилища.

    Первый живой прогон дал «новых решений 0» и ни слова о том,
    почему: тот же класс отказа, что чинился в зонде спокойного рынка.
    Здесь сечение пустое (ни одного живого имени), и прогон обязан
    сказать это счётчиком, а не промолчать."""
    tmp = tempfile.mkdtemp()
    f = Fake()
    undo = install(f)
    old = (B.DEC, B.RES, B.PR.state_at)
    B.DEC = os.path.join(tmp, "d.jsonl")
    B.RES = os.path.join(tmp, "r.jsonl")
    B.PR.state_at = lambda liq, uni, at: {}
    lines = []
    try:
        a, b = B.catchup(None, None, f.universe(), None, {},
                         start="2026-06-15", end="2026-06-17",
                         log=lines.append)
        check("ничего не посчитано", a == 0 and b == 0, f"{a} {b}")
        txt = "\n".join(lines)
        check("причина названа",
              "живых и ликвидных имён меньше пола" in txt, txt)
        check("край хранилища напечатан", "Хранилище A2" in txt, txt)
    finally:
        undo()
        B.DEC, B.RES, B.PR.state_at = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_report_writes_and_marks_backfill():
    tmp = tempfile.mkdtemp()
    try:
        dec = [{"at": "2026-06-15",
                "written_at": B.ms("2026-06-15") / 1000.0 + 9e5}]
        res = [{"at": "2026-06-15", "net_bp": 120.0, "gross_bp": 131.0,
                "truncated_legs": 1, "funding_bp": -3.0}]
        sm = B.summarise(dec, res)
        art = {"run_at": "t", "rules": B.RULES, "k": B.K_DAYS,
               "h": B.H_DAYS, "width": B.WIDTH, "cost_bp": B.COST_BP,
               "decisions": 1, "resolutions": 1, "summary": sm,
               "verdict": B.verdict_phrase(sm)}
        p = os.path.join(tmp, "r.md")
        B.report(art, p)
        md = open(p, encoding="utf-8").read()
        check("отчёт разделяет группы",
              "записано вперёд | 0" in md and "восстановлено | 1" in md,
              md[md.find("| группа"):][:400])
        check("отчёт называет отличие от зонда по β",
              "ОДНОЙ β" in md, "")
        check("отчёт говорит, чего книга не доказывает",
              "не проверяет исполнение" in md, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("заглядывание")
    test_decision_ignores_the_future()
    test_signal_identical_with_and_without_future_loaded()
    test_changing_the_past_does_change_the_decision()
    print("книга и исход")
    test_book_weights()
    test_reversion_is_found_and_random_walk_is_not()
    test_delisted_leg_is_held_to_the_last_bar()
    test_net_arithmetic_with_funding()
    print("честное против восстановленного")
    test_ahead_flag()
    test_summary_never_mixes_groups()
    test_verdict_says_when_there_is_no_track()
    print("журнал и отчёт")
    test_catchup_is_idempotent()
    test_empty_run_explains_itself()
    test_report_writes_and_marks_backfill()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
