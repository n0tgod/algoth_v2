#!/usr/bin/env python3
"""Проверки механики 193cbb87 — пауза по имени после хвостового выхода.

Каждая проверка отвечает за одно правило, и к каждому правилу в
`build.json` приложена подделка, от которой она обязана упасть.
Проверка, которая не кусается, не проверяет ничего.

Что проверяется: пауза запрещает вход после СВОЕГО хвостового выхода и
только после него (обычный исход паузы не даёт); граница окна ровно на
P часах; будущее не читается — переписали исход, который на момент
решения ещё не случился, и прошлое не шелохнулось; триггер — только
ВЗЯТАЯ кассой позиция, а не любое решение имени; записи снимаются по
порядку времени (снятая поздняя запись судила бы состав, которого не
будет); переполнение — отказ вслух, а не молчание; размер контроля
равен числу ВЗЯТЫХ базой вычеркнутых позиций; спор идёт о названной
величине; вердиктовая фраза выводится из числа; убийца шага 0 стоит на
двух числах сразу; величины, которой нет, — прочерк, а не ноль;
перестановка меток кусается; пустота не выдаёт себя за результат; кэш
реплея не переписывается (механизмом, а не обещанием); издержки
вычитаются в каждой сделке; сверка с ячейкой семейства кусается;
ускорение сверяется бит в бит; ось и ячейка вердикта объявлены
заданием; калибровочная пара обеими ногами — подсадка находится, шум
молчит.

Вывод скуп намеренно: приёмка смотрит ПОСЛЕДНИЕ 4000 символов, и строка
«ПРОВАЛ имя», утонувшая в середине, есть контроль, который здесь
пройдёт, а там нет.

    .venv/bin/python research/mech_193cbb87/test_name_pause.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import name_pause as NP                                       # noqa: E402
from name_pause import R, RP, AG, TS                          # noqa: E402

TESTS = []
H = NP.HOUR
DAY = 86400.0
T0 = 1786147200.0                      # ровная граница часа И суток
NOW = T0 + 60 * DAY
CTX = {"error": "издержки в проверке не считаются"}
BOOK = "safe_h"
RULER = "safe_s"                       # линейка книги вердикта
DEP = 10000.0


def test(fn):
    TESTS.append(fn)
    return fn


def quiet(*_a):
    pass


class NoMarket:
    """Рынка в проверке нет: охрана не срабатывает ни разу.

    Подставной рынок НАЗВАН, а не подразумевается: правило выхода,
    сработавшее посреди фикстуры, сдвинуло бы исходы и сроки, и
    литеральные равенства стали бы недостижимы по чужой причине.
    """

    def __init__(self):
        self.wave_none = 0

    def k_star(self, _at, _pct, _last):
        self.wave_none += 1
        return None, 1


# Рынок подменяется и ГЛОБАЛЬНО: `short_grid.cell_stats` берёт его сам
# (`run_paper.market`), а моменты фикстуры попадают в окно живой записи
# стакана — и сверка с ячейкой семейства разошлась бы не по своей
# причине, а потому, что одна её половина прочитала диск, а другая нет.
RP._MARKET = NoMarket()


# ---------------------------------------------------------------- фикстуры

def rec(sym, at, pnl=0.25, exit="срок", exit_ts=None, hold_h=24, lev=3.0,
        fwd=100.0, state="closed"):
    """Запись реплея в ЖИВОЙ форме: поля те же, что пишет прогон.

    Отметки дрожат и суммируются ровно в исход: запись с ровными
    приращениями прятала бы разницу между «где позиция к часу k» и её
    итогом, а запись, где сумма отметок не равна исходу, живой не
    бывает — касса и правило охраны читают такую иначе.
    """
    out_ts = float(at + hold_h * H - 1.0 if exit_ts is None else exit_ts)
    n = max(1, int((out_ts - float(at)) // H) + 1)
    d = [((i * 37 % 11) - 5) / 100.0 for i in range(n - 1)]
    d.append(float(pnl) - sum(d))
    return {"at": float(at), "exit_ts": out_ts, "pnl": float(pnl),
            "pnl_net": float(pnl) - 0.002, "lev": float(lev),
            "lev_fence": float(lev), "fwd": float(fwd), "sym": sym,
            "side": "short", "rr": 0.55, "gates": ["any"], "exit": exit,
            "marks": [[float(at) + i * H, round(float(x), 6)]
                      for i, x in enumerate(d)],
            "end_ts": out_ts, "sched_end": float(at) + hold_h * H,
            "depth": 1, "n_rungs": 1, "avg": 100.0, "entry_px": 100.0,
            "exit_px": 100.7, "fills": [[float(at) + 60.0, 100.0, 0.25]],
            "state": state, "fav_bp": 300.0}


def cache_of(rows, ruler=RULER):
    return {(ruler, r["sym"], round(float(r["at"]), 3)): r for r in rows}


def launch_of(rows, days=400.0):
    return {r["sym"]: T0 - days * DAY for r in rows}


def packed_of(rows):
    return {BOOK: list(rows)}


def spread(days=14, per_day=3, pnl=None, exit_of=None):
    """Книга на несколько суток: колонок концентрации без четырёх суток нет."""
    pnl = pnl or (lambda i: 0.25 if i % 4 else -0.6)
    rows = []
    for d in range(days):
        for j in range(per_day):
            i = d * per_day + j
            rows.append(rec(f"S{i:03d}USDT", T0 + d * DAY + j * 2 * H,
                            pnl(i), fwd=150.0 - j,
                            exit=(exit_of(i) if exit_of else "срок")))
    return rows


def with_repeats(rows=None):
    """Живая книга плюс имя, где книга вошла СРАЗУ ПОСЛЕ своего пола.

    Первая позиция кончается полом, вторая открывается через два часа —
    ровно то, о чём заявка (GPSUSDT: шесть ликвидаций за десять часов).
    """
    rows = list(rows if rows is not None else spread())
    t = T0 + 5 * DAY
    rows += [rec("REPUSDT", t, -0.8, exit="пол", exit_ts=t + 5 * H),
             rec("REPUSDT", t + 7 * H, -0.7, exit="пол",
                 exit_ts=t + 12 * H),
             rec("REPUSDT", t + 14 * H, 0.3, exit_ts=t + 20 * H)]
    return rows


def rows_of(recs, book=BOOK, dep=DEP, now=NOW):
    """Строки кассы книги на этих записях — тем же ядром, что прогон."""
    with NP.only(dep):
        rows, cells, _o, _l = RP.build_rows({book: list(recs)}, now=now,
                                            keys=[book], log=quiet)
    return rows, cells


# ------------------------------------------------------------- само правило

@test
def пауза_не_берёт_имя_после_своего_хвостового_выхода():
    """Вход в имя запрещён, пока не прошло P часов после пола или ликвидации."""
    a = rec("AUSDT", T0, -0.8, exit="пол", exit_ts=T0 + 5 * H)
    b = rec("AUSDT", T0 + 8 * H)
    c = rec("BUSDT", T0 + 8 * H)
    got = NP.blocked_of([a, b, c], [a], 12.0)
    assert [x["sym"] for x in got] == ["AUSDT"], got
    assert got[0]["key"] == RP._key(b), got
    assert abs(got[0]["gap_h"] - 3.0) < 1e-9, got
    assert got[0]["trigger_exit"] == "пол", got
    # чужое имя паузы не получает ни при каком P
    assert not [x for x in NP.blocked_of([a, c], [a], 24.0)], "чужое имя"


@test
def срок_и_тейк_паузы_не_дают():
    """Триггер — только исходы хвоста; обычный исход книгу не останавливает."""
    for ex in ("срок", "тейк", "трейл", "рынок"):
        a = rec("AUSDT", T0, 0.2, exit=ex, exit_ts=T0 + 5 * H)
        b = rec("AUSDT", T0 + 8 * H)
        assert not NP.blocked_of([a, b], [a], 24.0), ex
    for ex in NP.TRIGGER_EXITS:
        a = rec("AUSDT", T0, -0.8, exit=ex, exit_ts=T0 + 5 * H)
        b = rec("AUSDT", T0 + 8 * H)
        assert len(NP.blocked_of([a, b], [a], 24.0)) == 1, ex


@test
def пауза_кончается_ровно_через_P_часов():
    """Граница окна объявлена: вход ровно через P часов уже разрешён."""
    a = rec("AUSDT", T0, -0.8, exit="пол", exit_ts=T0 + 5 * H)
    on = rec("AUSDT", T0 + 5 * H + 12 * H)          # ровно 12 ч после выхода
    before = rec("AUSDT", T0 + 5 * H + 12 * H - 1)  # на секунду раньше
    assert not NP.blocked_of([a, on], [a], 12.0), "граница обязана быть <"
    assert len(NP.blocked_of([a, before], [a], 12.0)) == 1, "12 ч − 1 с"


@test
def не_заглядывает_в_будущее():
    """Переписали будущее — прошлое не шелохнулось.

    Исход позиции, которая на момент решения ещё НЕ ЗАКРЫТА, лежит в
    будущем этого решения. Правило, читающее его, «работало» бы тем же,
    чем скрин без нуля.
    """
    c1 = rec("CUSDT", T0, -0.9, exit="ликвидация", exit_ts=T0 + 6 * H)
    c2 = rec("CUSDT", T0 + 8 * H)                    # повтор, запрещён
    c3 = rec("DUSDT", T0 + 40 * H, 0.2, exit="срок", exit_ts=T0 + 70 * H)
    c4 = rec("DUSDT", T0 + 50 * H)                   # решение ВНУТРИ c3
    recs = [c1, c2, c3, c4]
    before = [x["key"] for x in NP.blocked_of(recs, recs, 12.0)]
    assert before == [RP._key(c2)], before
    # переписываем БУДУЩЕЕ решения c4: исход c3 становится хвостовым
    c3b = dict(c3, exit="ликвидация", pnl=-0.9)
    recs2 = [c1, c2, c3b, c4]
    after = [x["key"] for x in NP.blocked_of(recs2, recs2, 12.0)]
    assert after == before, f"прошлое шелохнулось: {before} → {after}"


@test
def две_трактовки_триггера_различаются():
    """Правило смотрит ПРЕДЫДУЩУЮ позицию, шаг 0 — последний хвостовой выход."""
    d1 = rec("EUSDT", T0, -0.8, exit="пол", exit_ts=T0 + 5 * H)
    d2 = rec("EUSDT", T0 + 6 * H, 0.2, exit="срок", exit_ts=T0 + 7 * H)
    d3 = rec("EUSDT", T0 + 8 * H)
    recs = [d1, d2, d3]
    prev = [x["key"] for x in NP.blocked_of(recs, recs, 12.0, mode="prev")]
    tail = [x["key"] for x in NP.blocked_of(recs, recs, 12.0, mode="tail")]
    assert prev == [RP._key(d2)], prev
    assert tail == [RP._key(d2), RP._key(d3)], tail


@test
def триггер_только_взятая_позиция():
    """Решение, которого книга НЕ взяла, паузы не даёт.

    Триггер есть состояние книги, которое знает про себя живой
    исполнитель: позиция, отвергнутая правилом «одна на имя» или
    кассой, на бирже не открывалась и остановить книгу не может.
    """
    a1 = rec("FUSDT", T0, 0.2, exit="срок", exit_ts=T0 + 24 * H - 1)
    a2 = rec("FUSDT", T0 + 2 * H, -0.9, exit="ликвидация",
             exit_ts=T0 + 25 * H)                 # снимет «одна на имя»
    a3 = rec("FUSDT", T0 + 30 * H)
    recs = spread(days=6) + [a1, a2, a3]
    got = NP.sister(packed_of(recs), DEP, 12.0, books=(BOOK,), now=NOW)
    assert not got["cut"][BOOK], got["cut"][BOOK]
    # а по кэшу реплея (диагностика) та же книга запрет получает
    var = NP.sister(packed_of(recs), DEP, 12.0, books=(BOOK,), now=NOW,
                    trigger="cache")
    assert [x["key"] for x in var["cut"][BOOK]] == [RP._key(a3)], var["cut"]


@test
def повторы_снимаются_по_порядку_времени():
    """Снимается САМАЯ РАННЯЯ запрещённая запись, и состав считается дальше.

    Снять позднюю значило бы судить её по составу, которого у книги с
    паузой не будет: её триггер — позиция, которую эта же пауза
    запрещает.
    """
    b1 = rec("GUSDT", T0, -0.9, exit="ликвидация", exit_ts=T0 + 10 * H)
    b2 = rec("GUSDT", T0 + 13 * H, -0.9, exit="ликвидация",
             exit_ts=T0 + 20 * H)
    b3 = rec("GUSDT", T0 + 26 * H)
    recs = spread(days=6) + [b1, b2, b3]
    got = NP.sister(packed_of(recs), DEP, 12.0, books=(BOOK,), now=NOW)
    keys = [x["key"] for x in got["cut"][BOOK]]
    assert keys == [RP._key(b2)], keys
    assert got["steps"][BOOK] == 1, got["steps"]


@test
def отказ_вместо_тишины_при_переполнении():
    """Правило, снявшее больше предела записей, роняет прогон вслух."""
    t = T0 + 2 * DAY
    recs = spread(days=6) + [
        rec("HUSDT", t, -0.9, exit="ликвидация", exit_ts=t + 1 * H),
        rec("HUSDT", t + 2 * H), rec("HUSDT", t + 3 * H)]
    fell = ""
    try:
        NP.sister(packed_of(recs), DEP, 12.0, books=(BOOK,), now=NOW,
                  max_steps=1)
    except RuntimeError as e:
        fell = str(e)
    assert "max" not in fell and "другая книга" in fell, f"молчание: {fell!r}"


# --------------------------------------------------------------- контроль

@test
def размер_контроля_равен_вычеркнутым_взятым():
    """Спорить можно только о ВЗЯТЫХ позициях: снятое решение, которого
    касса и так не брала, денег книги не меняет."""
    t = T0 + 3 * DAY
    e1 = rec("IUSDT", t, -0.8, exit="пол", exit_ts=t + 2 * H)
    e2 = rec("IUSDT", t + 3 * H, -0.5, exit="срок", exit_ts=t + 9 * H)
    e3 = rec("IUSDT", t + 5 * H)                    # снимет «одна на имя»
    recs = spread(days=8) + [e1, e2, e3]
    prep = packed_of(recs)
    base = NP.base_of(prep, DEP, CTX, books=(BOOK,), now=NOW)
    got, _sis = NP.branch(prep, base, DEP, CTX, 12.0, books=(BOOK,), now=NOW,
                          seeds=0)
    assert got["cut_n"][BOOK] == 2, got["cut_n"]
    assert got["cut_taken_n"][BOOK] == 1, got["cut_taken_n"]


@test
def спор_идёт_о_названной_величине():
    """Доля зёрен считается по той величине, о которой спор, а не по числу
    сделок: сделок у правила и у случайного урезания поровну всегда."""
    draws = [{"usd_wo_top3d": 100.0, "ratio": 1.0, "day_worst": -0.1,
              "n": 50} for _ in range(4)]
    form = {"usd_wo_top3d": 500.0, "ratio": 2.0, "day_worst": -0.05, "n": 50}
    got = NP.beats(draws, form)
    assert got["usd_wo_top3d"]["share"] == 0.0, got
    assert got["usd_wo_top3d"]["value"] == 500.0, got
    assert got["ratio"]["share"] == 0.0 and got["day_worst"]["share"] == 0.0
    assert got["usd_wo_top3d"]["median"] == 100.0, got
    # то же правило, но хуже выборки — доля обязана стать единицей
    worse = NP.beats(draws, dict(form, usd_wo_top3d=10.0))
    assert worse["usd_wo_top3d"]["share"] == 1.0, worse


@test
def вердикт_выводится_из_числа():
    """Фраза вердикта считается из доли зёрен, а не стоит рядом литералом."""
    a, b = NP.verdict_of(0.0), NP.verdict_of(0.9)
    assert a != b, (a, b)
    assert "бьёт" in a and "неотличимо" in b, (a, b)
    assert NP.verdict_of(NP.BEAT_MAX) == b, "порог включён в «не хуже»"
    assert "не измерено" in NP.verdict_of(None)


@test
def шаг_0_закрывает_инертное_правило():
    """Убийца шага 0 стоит на ДВУХ числах сразу: и счёте, и доле сделок."""
    def rep(n, share, p=NP.KILL_P_H, mode=NP.KILL_MODE):
        return {"cells": {p: {mode: {"n": n, "share": share}}}}

    assert NP.KILL_P_H == 24.0 and NP.KILL_MODE == "tail", NP.KILL_P_H
    assert NP.step0_killer(rep(25, 0.01))["fired"] is True, "доля мала"
    assert NP.step0_killer(rep(10, 0.50))["fired"] is True, "счёт мал"
    assert NP.step0_killer(rep(25, 0.05))["fired"] is False, "есть что резать"
    assert NP.step0_killer(rep(None, None))["fired"] is None, "не посчитано"
    assert "2.1 %" in NP.step0_killer(rep(16, 0.0209))["why"]
    # ячейка убийцы — НЕ ячейка вердикта: числа берутся с оси 24 ч
    assert NP.step0_killer(rep(25, 0.05, p=NP.VERDICT_P_H,
                               mode="prev"))["fired"] is None, "чужая ячейка"


# -------------------------------------------------------------- шаг 1г

@test
def непосчитанное_идёт_прочерком():
    """Полоса без обеих групп — прочерк с причиной, а не ноль."""
    band = [rec(f"J{i}USDT", T0 + i * H, -0.9, exit="пол", lev=20.0)
            for i in range(5)]
    got = NP.lev_perm(band, set(), perms=10)
    assert got["gap"] is None and got["perm"] is None, got
    assert got["why"], got
    assert NP.lev_killer(got)["fired"] is None, NP.lev_killer(got)


@test
def перестановка_меток_кусается():
    """Нуль перестановкой: разрыв, которого нет, обязан быть обычным."""
    band, keys = [], set()
    for i in range(8):
        r = rec(f"K{i}USDT", T0 + i * H, -0.9,
                exit=("пол" if i % 2 else "срок"), lev=20.0)
        band.append(r)
        if i < 4:
            keys.add(RP._key(r))
    null = NP.lev_perm(band, keys, perms=200)
    assert null["gap"] == 0.0, null
    assert null["perm"] >= 0.2, f"перестановки не кусаются: {null}"
    # а подсаженный разрыв обязан находиться
    band2, keys2 = [], set()
    for i in range(10):
        r = rec(f"L{i}USDT", T0 + i * H, -0.9,
                exit=("пол" if i < 2 else "срок"), lev=20.0)
        band2.append(r)
        if i < 2:
            keys2.add(RP._key(r))
    hit = NP.lev_perm(band2, keys2, perms=200)
    assert hit["gap"] == 1.0 and hit["perm"] <= 0.1, hit


# ------------------------------------------------------- касса и издержки

@test
def издержки_вычитаются_в_каждой_сделке():
    """Деньги книги — НЕТТО: издержки накладывает общая функция проекта."""
    seen = {"n": 0}
    real = NP.CO.apply_to_rows

    def spy(rows, ctx, **kw):
        seen["n"] += 1
        return [dict(r, usd=round(float(r["usd"]) - 1.0, 4)) for r in rows], \
            {"applied": len(rows), "cost_usd": float(len(rows))}

    recs = spread(days=6)
    rows, cells = rows_of(recs)
    NP.CO.apply_to_rows = spy
    try:
        got = NP.form_of(rows, DEP, {"taker": {}}, BOOK, cells)
        gross = NP.form_of(rows, DEP, CTX, BOOK, cells)
    finally:
        NP.CO.apply_to_rows = real
    assert seen["n"] == 1, "издержки не вычитались вовсе"
    assert got["n"] == gross["n"] and got["n"] > 0, (got["n"], gross["n"])
    assert abs(got["usd"] - (gross["usd"] - got["n"])) < 1e-6, (got, gross)
    assert (gross.get("costs") or {}).get("error"), gross.get("costs")


@test
def сверка_с_ячейкой_семейства_кусается():
    """Расхождение с ячейкой семейства обязано быть видно числом."""
    recs = spread(days=6)
    cache = cache_of(recs)
    lau = launch_of(recs)
    ok = NP.agrees_with_cell(AG.packed_short(cache), CTX, lau, dep=DEP,
                             book=BOOK, now=NOW, mkt=NoMarket())
    assert ok["все_равны"] is True, ok
    assert ok["n"]["здесь"] == ok["n"]["ячейка"] > 0, ok["n"]
    real = NP.G.cell_stats

    def wrong(*a, **kw):
        got = real(*a, **kw)
        for k in got:
            got[k] = dict(got[k], n=int(got[k]["n"] or 0) + 1)
        return got

    NP.G.cell_stats = wrong
    try:
        bad = NP.agrees_with_cell(AG.packed_short(cache), CTX, lau, dep=DEP,
                                  book=BOOK, now=NOW, mkt=NoMarket())
    finally:
        NP.G.cell_stats = real
    assert bad["все_равны"] is False, bad
    assert bad["n"]["равно"] is False, bad["n"]


@test
def ускорение_сверяется_бит_в_бит():
    """Узкий проход по одному депозиту равен полному — числами, а не верой."""
    recs = spread(days=6)
    was = list(R.DEPOSITS)
    full, _c, _o, _l = RP.build_rows({BOOK: recs}, now=NOW, keys=[BOOK],
                                     log=quiet)
    mine = sorted((r["sym"], r["at"], r["usd"]) for r in full
                  if int(r["dep"]) == int(DEP))
    base = NP.base_of({BOOK: recs}, DEP, CTX, books=(BOOK,), now=NOW)
    narrow = sorted((r["sym"], r["at"], r["usd"]) for r in base["rows"]
                    if int(r["dep"]) == int(DEP))
    assert mine and narrow == mine, (len(mine), len(narrow))
    assert R.DEPOSITS == was, "список депозитов не возвращён на место"
    try:
        with NP.only(DEP):
            raise ValueError("падение внутри узкого прохода")
    except ValueError:
        pass
    assert R.DEPOSITS == was, "после падения список не возвращён"


@test
def кэш_реплея_не_переписывается():
    """Запрет — механизм, а не обещание в комментарии."""
    real = NP.S.write_cache
    fell = ""
    with NP.cache_locked():
        assert NP.S.write_cache is not real, "писатель не подменён"
        try:
            NP.S.write_cache({}, path=os.path.join(HERE, "out", "_нет.jsonl"))
        except RuntimeError as e:
            fell = str(e)
    assert "не вправе переписывать" in fell, f"кэш переписан молча: {fell!r}"
    assert NP.S.write_cache is real, "писатель не возвращён на место"


# ------------------------------------------------------------ калибровка

@test
def калибровка_находит_подсадку():
    """Подсаженный эффект обязан находиться: иначе «эффекта нет» неотличимо
    от сломанной загрузки."""
    recs = with_repeats()
    prep = packed_of(recs)
    base = NP.base_of(prep, DEP, CTX, books=(BOOK,), now=NOW)
    taken = base["taken"][BOOK]
    keys = {BOOK: set(x["key"] for x in NP.blocked_of(taken, taken,
                                                      NP.VERDICT_P_H))}
    assert keys[BOOK], "фикстура без повторов: калибровать нечего"
    pl = NP.planted(prep, keys, books=(BOOK,))
    # исход переписан, а отметки сходятся с ним — запись осталась живой
    hit = [r for r in pl[BOOK] if RP._key(r) in keys[BOOK]]
    assert hit and all(abs(r["pnl"] - NP.PLANT_PNL) < 1e-9 for r in hit), hit
    assert all(abs(sum(float(m[1]) for m in r["marks"]) - NP.PLANT_PNL)
               < 1e-6 for r in hit), "отметки не сходятся с исходом"
    pb = NP.base_of(pl, DEP, CTX, books=(BOOK,), now=NOW)
    got, _s = NP.branch(pl, pb, DEP, CTX, NP.VERDICT_P_H, books=(BOOK,),
                        now=NOW, seeds=8, seed0=4000)
    share = got["control"][BOOK][NP.MAIN_FIELD]["share"]
    assert share is not None and share <= NP.BEAT_MAX, \
        f"подсадка не находится: доля {share}"


@test
def калибровка_молчит_на_шуме():
    """Там, где урезать НЕЧЕГО, правило обязано быть неотличимо от случайной
    выборки того же размера: иначе «работает» сам размер.

    Книга построена вырожденной намеренно: каждая позиция кончается в
    ноль, поэтому любое урезание даёт одну и ту же книгу, и доля зёрен
    обязана быть единицей ТОЧНО. Живой такая книга не бывает и не
    притворяется: это нуль по построению, а не подставная запись.
    """
    rows = []
    for d in range(14):
        for j in range(2):
            i = d * 2 + j
            rows.append(rec(f"M{i:03d}USDT", T0 + d * DAY + j * 3 * H, 0.0))
    t = T0 + 4 * DAY
    rows += [rec("NUSDT", t, 0.0, exit="пол", exit_ts=t + 2 * H),
             rec("NUSDT", t + 4 * H, 0.0)]
    prep = packed_of(rows)
    base = NP.base_of(prep, DEP, CTX, books=(BOOK,), now=NOW)
    got, _s = NP.branch(prep, base, DEP, CTX, NP.VERDICT_P_H, books=(BOOK,),
                        now=NOW, seeds=8, seed0=3000)
    assert got["cut_taken_n"][BOOK] == 1, got["cut_taken_n"]
    share = got["control"][BOOK][NP.MAIN_FIELD]["share"]
    assert share is not None and share >= NP.BEAT_MAX, \
        f"на шуме правило «работает»: доля {share}"
    assert "неотличимо" in NP.verdict_of(share)


# ------------------------------------------------------------- весь прогон

@test
def пустота_не_выдаёт_себя_за_результат():
    """Ноль записей при непустом входе — отказ с причиной, а не отчёт."""
    s = NP.run(cache={}, ctx=CTX, launch={}, mkt=NoMarket(), books=(BOOK,),
               deps=(DEP,), seeds=0, perms=4, log=quiet, now=NOW)
    assert "нет записей" in (s.get("error") or ""), s.get("error")
    assert "Не посчитано" in NP.report(s), "отчёт печатает числа вместо отказа"


@test
def книга_вердикта_без_позиций_есть_отказ():
    """Записи есть, а книга вердикта пуста — тоже отказ, а не прочерки."""
    recs = spread(days=6)
    s = NP.run(cache=cache_of(recs, ruler="optimal_s"), ctx=CTX,
               launch=launch_of(recs), mkt=NoMarket(),
               books=(BOOK, "optimal_h"), deps=(DEP,), seeds=0, perms=4,
               log=quiet, now=NOW)
    assert "ни одной позиции" in (s.get("error") or ""), s.get("error")


@test
def метка_тейка_проверяется_на_данных():
    """Исхода, которого в книге нет вовсе, плацебо не бывает — и молчать об
    этом нельзя: пустое плацебо читалось бы как «плацебо эффекта не дало»."""
    recs = with_repeats()
    assert not any(r["exit"] == NP.TAKE_EXIT for r in recs), "фикстура"
    s = NP.run(cache=cache_of(recs), ctx=CTX, launch=launch_of(recs),
               mkt=NoMarket(), books=(BOOK,), deps=(DEP,), seeds=4, perms=8,
               log=quiet, now=NOW, full=False)
    assert not s.get("error"), s.get("error")
    assert s["placebo_why"] and NP.TAKE_EXIT in s["placebo_why"], s
    assert s["killers"]["1в"]["fired"] is None, s["killers"]["1в"]
    assert "Не посчитано" in NP.report(s) or "не посчитано" in NP.report(s)


@test
def прогон_целиком_и_отчёт():
    """Механика целиком на живой по форме фикстуре: числа, убийцы, отчёт."""
    recs = with_repeats(spread(days=14, exit_of=lambda i: (
        "тейк" if i % 7 == 3 else "срок")))
    s = NP.run(cache=cache_of(recs), ctx=CTX, launch=launch_of(recs),
               mkt=NoMarket(), books=(BOOK,), deps=(DEP,), seeds=6, perms=20,
               log=quiet, now=NOW)
    assert not s.get("error"), s.get("error")
    assert s["calib"]["ok"] is True, s["calib"]["why"]
    assert s["agree"]["все_равны"] is True, s["agree"]
    assert s["base"][BOOK]["n"] > 10, s["base"][BOOK]
    assert s["rule"][NP.VERDICT_P_H]["cut_taken_n"][BOOK] >= 1, s["rule"]
    assert s["step0"][BOOK]["cells"][NP.VERDICT_P_H]["prev"]["n"] >= 1
    assert s["placebo_why"] is None, s["placebo_why"]
    assert s["verdict"]["why"], s["verdict"]
    txt = NP.report(s)
    for want in ("Шаг 0. Повторы", "Калибровочная пара",
                 "Шаг 1а. Потолок", "Шаг 1б. Правило", "Шаг 1в. Плацебо",
                 "Шаг 1г. Переодетое плечо", "Шаг 2. Форма",
                 "Шаг 3. Вперёд", s["verdict"]["why"][:40]):
        assert want in txt, want
    # обязательные колонки формы — все до одной, и они объявлены заявкой
    for col in ("взято кассой", "медиана дня", "среднее дня", "зелёных",
                "укус", "худший день", "$ без 3 лучших дней",
                "$ без лучшего имени", "просадка без худшего дня",
                NP.NAMED_DAY):
        assert col in txt, col
    # ячейка убийцы шага 0 названа на самой странице, а не подразумевается
    assert f"{NP.KILL_P_H:g} ч, трактовка" in txt, "ячейка убийцы"
    assert "форвардных суток 0" in txt, "шаг 3 обязан назвать причину"


@test
def ось_и_ячейка_объявлены_заданием():
    """Ось, ячейка вердикта, исходы и пороги — из задания, а не отсюда."""
    assert NP.PAUSE_GRID_H == (6.0, 12.0, 24.0), NP.PAUSE_GRID_H
    assert NP.VERDICT_P_H == NP.PAUSE_GRID_H[len(NP.PAUSE_GRID_H) // 2]
    assert NP.VERDICT_P_H == 12.0, NP.VERDICT_P_H
    assert NP.TRIGGER_EXITS == tuple(TS.TAIL_EXITS), NP.TRIGGER_EXITS
    assert "срок" not in NP.TRIGGER_EXITS, NP.TRIGGER_EXITS
    assert NP.PLACEBO_EXITS == (NP.TAKE_EXIT,), NP.PLACEBO_EXITS
    assert not set(NP.PLACEBO_EXITS) & set(NP.TRIGGER_EXITS), "плацебо"
    assert NP.BOOK == "safe_h" and NP.DEP == 10000.0, (NP.BOOK, NP.DEP)
    assert NP.SEEDS == AG.SEEDS and NP.PERMS == TS.PERMS, NP.SEEDS
    assert NP.HIGH_LEV == TS.HIGH_LEV, NP.HIGH_LEV
    assert (NP.MIN_REPEATS, NP.MIN_SHARE) == (20, 0.03), NP.MIN_SHARE
    assert (NP.BEAT_MAX, NP.PERM_MAX) == (0.05, 0.05), NP.BEAT_MAX
    assert NP.NAMED_DAY == "2026-09-12" and NP.PLANT_PNL == -0.9


def main():
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as e:                                # noqa: BLE001
            failed.append((fn.__name__, f"{type(e).__name__}: {e}"[:110]))
    print(f"проверок {len(TESTS)}, прошло {len(TESTS) - len(failed)}, "
          f"провалов {len(failed)}")
    for name, err in failed:
        print(f"ПРОВАЛ {name}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
