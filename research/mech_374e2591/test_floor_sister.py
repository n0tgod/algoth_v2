#!/usr/bin/env python3
"""Проверки механики 374e2591 — пол капитуляции 0.75 у сестры `safe_h`.

Каждая проверка отвечает за одно правило, и к каждому правилу в
`build.json` приложена подделка, от которой она обязана упасть.
Проверка, которая не кусается, не проверяет ничего.

Что проверяется: уровень пола выводится ФОРМУЛОЙ ЯДРА и зависит от
плеча (тождества на краях оси: доля 0 — ровно ликвидация, доля 1 — ровно
вход); числа правила берутся у объявленных источников (перезагрузка
модуля с подменённым источником, а не сверка значения с самим собой);
час пореза ищется строго ДО фактического выхода; переписанное будущее не
двигает ни часа, ни цены выхода; калибровочная пара обеими ногами
(подсаженный ход до −90 % маржи режется, подсаженный шум не режется);
ноль сработавших при непустом входе — отказ, а не отчёт; величина,
которой нет, — прочерк, а не ноль; вердиктовые фразы выведены из чисел,
а порог убийцы (А) — доля ИЗМЕРЕННОГО худшего дня базовой; форма книги
равна кассе семейства (второй кассы нет) и охрана рынком в ней
применена; окно показа не пересчитывает кассу; кэш сестры свой и пол
входит в его подпись; пол симуляции возвращается даже при падении
реплея; разрыв через пол считается по исходу, а не подразумевается.

Вывод скуп намеренно: приёмка смотрит ПОСЛЕДНИЕ 4000 символов, и строка
«ПРОВАЛ имя», утонувшая в середине, есть контроль, который здесь
пройдёт, а там нет.

    .venv/bin/python research/mech_374e2591/test_floor_sister.py
"""

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import floor_sister as FS                                     # noqa: E402
from floor_sister import AG, D2, G, L, P, R, RP, S, SS, WV     # noqa: E402

TESTS = []
H = FS.HOUR
T0 = 1786176000.0                      # ровная граница часа и суток
NOW = T0 + 80 * H
CTX = {"error": "издержки в проверке не считаются"}
DEP = FS.DEP


def test(fn):
    TESTS.append(fn)
    return fn


def quiet(*_a):
    pass


# ---------------------------------------------------------------- фикстуры

def rec(sym, i_h, cums, lev=3.0, exit="срок", entry=100.0, at=None,
        hold_h=24):
    """Запись кэша с ЯВНЫМ путём: `cums` — накопленный pnl по часам 1..K.

    Путь задаётся накопленным, а отметки ядра — приращения, поэтому
    здесь ровно одно вычитание: подсадка обязана ложиться туда, где её
    ждут, и проверки это утверждают литералом.
    """
    at = float(T0 + i_h * H if at is None else at)
    marks, prev = [], 0.0
    for i, c in enumerate(cums):
        marks.append([at + i * H, float(c) - prev])
        prev = float(c)
    k = len(cums)
    return {"at": at, "exit_ts": at + k * H - 1.0, "sym": sym,
            "side": "short", "lev": float(lev), "pnl": float(cums[-1]),
            "pnl_net": float(cums[-1]) - 0.002, "exit": exit, "marks": marks,
            "end_ts": at + hold_h * H, "sched_end": at + hold_h * H,
            "depth": 1, "n_rungs": 1, "avg": float(entry),
            "entry_px": float(entry), "exit_px": float(entry),
            "filled": float(lev) * 0.25, "fills": [[at, float(entry), 0.25]],
            "state": "closed", "fav_bp": -300.0, "fwd": 300.0, "rr": 0.5,
            "pair": [FS.RULER]}


def cache_of(rows, ruler=None):
    ruler = ruler or FS.RULER
    return {(ruler, r["sym"], round(float(r["at"]), 3)): r for r in rows}


def launch_of(cache, days=400.0):
    return {k[1]: T0 - days * 86400.0 for k in cache}


class StubMkt:
    """Рынок по часам: час срабатывания охраны задаётся по моменту входа."""

    def __init__(self, hour_of=None):
        self.hour_of = hour_of or (lambda _at: None)
        self.wave_none = 0

    def k_star(self, at, _pct, kmax):
        k = self.hour_of(float(at))
        if k is None or k > int(kmax):
            return None, 0
        return int(k), 0


def flat_cache(n=12, step_h=8):
    """Кэш на несколько суток, где пол не срабатывает НИ РАЗУ."""
    rows = []
    for i in range(n):
        rows.append(rec(f"S{i % 4}USDT", i * step_h,
                        [0.02, -0.03, 0.05, 0.01 * (1 if i % 2 else -1)]))
    return cache_of(rows)


def deep_cache(n=12, step_h=8):
    """Кэш, где часть позиций уходит глубоко под воду."""
    rows = []
    for i in range(n):
        if i % 3 == 0:
            rows.append(rec(f"S{i % 4}USDT", i * step_h,
                            [-0.05, -0.12, -0.30, -0.55, -0.80],
                            exit="пол"))
        else:
            rows.append(rec(f"S{i % 4}USDT", i * step_h,
                            [0.03, 0.06, 0.02, 0.09, 0.12], exit="тейк"))
    return cache_of(rows)


def views_of(cache):
    return FS.views_of(cache)[0]


# ------------------------------------------------------- уровень пола

@test
def уровень_пола_формулой_ядра():
    """Края оси доли — тождества: 0 есть ликвидация, 1 есть вход."""
    r = rec("AUSDT", 0, [-0.1])
    lo = FS.floor_level(r, 0.0)
    hi = FS.floor_level(r, 1.0)
    mid = FS.floor_level(r, 0.75)
    assert abs(lo["px"] - lo["p_liq"]) < 1e-9, lo
    assert abs(hi["px"] - float(r["entry_px"])) < 1e-9, hi
    assert abs(hi["pnl"]) < 1e-12, hi                  # на входе pnl ноль
    # На самой ликвидации переоценка обязана совпасть с ядром
    ws = [f[2] for f in r["fills"]]
    want = L.open_mark(lo["p_liq"], r["avg"], 1.0, r["lev"], ws, "short")
    assert abs(lo["pnl"] - want) < 1e-12, (lo, want)
    assert lo["pnl"] < mid["pnl"] < hi["pnl"], (lo, mid, hi)
    # доля 0.75 режет примерно при четверти маржи, но не ровно −0.25
    assert -0.26 < mid["pnl"] < -0.20, mid


@test
def уровень_зависит_от_плеча():
    """У крупного плеча ликвидация ближе, и четверть пути до неё дешевле."""
    a = FS.floor_level(rec("AUSDT", 0, [-0.1], lev=3.0))
    b = FS.floor_level(rec("BUSDT", 0, [-0.1], lev=25.0))
    assert a["pnl"] < b["pnl"] - 0.01, (a, b)
    assert abs(b["pnl"] + 0.25) > 0.02, ("плоские −25 % — другое правило", b)


@test
def запись_без_рунгов_не_считается():
    """Нотионал, не сходящийся с рунгами, — отказ с причиной, а не пол."""
    bad = dict(rec("AUSDT", 0, [-0.1]), filled=99.0)
    assert FS.floor_level(bad).get("why"), FS.floor_level(bad)
    assert FS.floor_level(dict(rec("AUSDT", 0, [-0.1]), fills=[])).get("why")
    lv, diag = FS.levels_of({("r", "AUSDT", 1.0): {"rec": bad}})
    assert not lv and diag["n"] == 0 and diag["why"], diag


@test
def уровень_не_отрицателен_выбывает():
    """Пол стоит ПРОТИВ позиции: неотрицательный уровень правилом не станет."""
    r = rec("AUSDT", 0, [-0.1])
    v = {("r", "AUSDT", 1.0): {"rec": r}}
    lv, diag = FS.levels_of(v, frac=1.0)          # доля 1 — уровень ровно 0
    assert not lv, lv
    assert "уровень пола не отрицателен" in (diag["why"] or {}), diag


@test
def сверка_ликвидации_кусается():
    """Выведенная ликвидация против записи: подделка цены обязана всплыть."""
    ok = rec("AUSDT", 0, [-1.0], exit="ликвидация")
    lvl = FS.floor_level(ok)
    ok["exit_px"] = lvl["p_liq"]
    bad = dict(rec("BUSDT", 1, [-1.0], exit="ликвидация"),
               exit_px=lvl["p_liq"] * 1.10)
    vs = {("r", "AUSDT", 1.0): {"rec": ok}, ("r", "BUSDT", 2.0): {"rec": bad}}
    liq = {("r", "AUSDT", 1.0): lvl["p_liq"],
           ("r", "BUSDT", 2.0): FS.floor_level(bad)["p_liq"]}
    got = FS.liq_check(vs, liq)
    assert got["n"] == 2 and got["bad"] == 1, got
    assert got["worst_bp"] > 100.0, got
    # ликвидаций нет вовсе — прочерк с причиной, а не «расхождений ноль»
    none = FS.liq_check({("r", "AUSDT", 1.0): {"rec": rec("AUSDT", 0, [0.1])}},
                        liq)
    assert none["n"] == 0 and none["why"], none


# ------------------------------------------------- откуда берутся правила

@test
def правила_берутся_у_книги():
    """Числа правила читаются у источников, а не назначены здесь.

    Проверяется ПОДМЕНОЙ источника и перезагрузкой модуля: сверка
    значения с самим собой прошла бы и на литерале.
    """
    was_floors, was_guard = SS.FLOORS, dict(R.WAVE_GUARD_PCT)
    try:
        SS.FLOORS = (("f10", 0.10), ("f75", 0.41))
        R.WAVE_GUARD_PCT[FS.BOOK] = 7.5
        importlib.reload(FS)
        assert abs(FS.FLOOR - 0.41) < 1e-12, FS.FLOOR
        assert abs(FS.GUARD - 7.5) < 1e-12, FS.GUARD
    finally:
        SS.FLOORS = was_floors
        R.WAVE_GUARD_PCT.clear()
        R.WAVE_GUARD_PCT.update(was_guard)
        importlib.reload(FS)
    assert abs(FS.FLOOR - 0.75) < 1e-12, FS.FLOOR
    assert abs(FS.GUARD - 2.0) < 1e-12, FS.GUARD
    assert abs(FS.BASE_FLOOR - R.floor_frac_of(FS.BOOK, D2.FLOOR_FRAC)) < 1e-12
    assert FS.AGE_D == R.min_age_days(FS.BOOK), FS.AGE_D
    assert FS.SEEDS == P.SEEDS and FS.TAIL_EXITS == FS.T.TAIL_EXITS


# ------------------------------------------------------ час пореза и будущее

@test
def час_среза_строго_до_выхода():
    """Час выхода в счёт не идёт: правило не узнаёт исхода заранее."""
    early = rec("AUSDT", 0, [-0.05, -0.10, -0.30, -0.40])
    late = rec("BUSDT", 1, [-0.05, -0.10, -0.15, -0.90])
    vs = views_of(cache_of([early, late]))
    lv, _d = FS.levels_of(vs)
    got = FS.hits(vs, lv)
    ka = got.get((FS.RULER, "AUSDT", round(early["at"], 3)))
    kb = got.get((FS.RULER, "BUSDT", round(late["at"], 3)))
    assert ka == 3, ka
    assert kb is None, ("крест на часе выхода порезом не является", kb)


@test
def будущее_не_меняет_прошлого():
    """Переписать будущее — час и цена выхода не шелохнутся."""
    base = rec("AUSDT", 0, [-0.05, -0.12, -0.30, -0.35, -0.42, -0.50])
    fut = rec("AUSDT", 0, [-0.05, -0.12, -0.30, +5.00, -9.00, +7.00])
    out = []
    for r in (base, fut):
        vs = views_of(cache_of([r]))
        lv, _d = FS.levels_of(vs)
        key = (FS.RULER, "AUSDT", round(r["at"], 3))
        k = FS.hits(vs, lv)[key]
        mark = FS.cut_record(r, k)
        lvlr = FS.cut_record(r, k, lv[key])
        out.append((k, round(float(mark["pnl"]), 9),
                    round(float(lvlr["pnl"]), 9), lv[key]))
        assert max(int(round((m[0] - r["at"]) / H)) + 1
                   for m in lvlr["marks"]) <= k, lvlr["marks"]
    assert out[0][:3] == out[1][:3], out
    assert out[0][0] == 3, out
    assert abs(out[0][2] - out[0][3]) < 1e-9, ("порез по уровню", out[0])


@test
def порез_по_уровню_равен_полу():
    """Порез по уровню кладёт исход РОВНО на пол, а по отметке — на отметку."""
    r = rec("AUSDT", 0, [-0.05, -0.12, -0.31, -0.40])
    vs = views_of(cache_of([r]))
    lv, _d = FS.levels_of(vs)
    key = (FS.RULER, "AUSDT", round(r["at"], 3))
    k = FS.hits(vs, lv)[key]
    mark, lvlr = FS.cut_record(r, k), FS.cut_record(r, k, lv[key])
    assert abs(float(mark["pnl"]) + 0.31) < 1e-9, mark["pnl"]
    assert abs(float(lvlr["pnl"]) - lv[key]) < 1e-9, (lvlr["pnl"], lv[key])
    assert float(lvlr["pnl"]) > float(mark["pnl"]), "уровень выше отметки"
    assert WV.path_of(lvlr)["final"] == lvlr["pnl"], lvlr
    assert mark["exit"] == FS.EXIT and lvlr["exit"] == FS.EXIT


@test
def калибровочная_пара():
    """Подсаженный ход находится, подсаженный шум молчит."""
    deep = [0.01, -0.05, -0.30, -0.60, -0.90]
    noise = [0.01, -0.02, 0.03, -0.04, 0.02]
    assert min(deep) == -0.90 and deep[2] == -0.30, deep   # подсадка легла
    assert max(abs(x) for x in noise) < 0.05, noise        # шум и есть шум
    vs = views_of(cache_of([rec("DUSDT", 0, deep), rec("NUSDT", 1, noise)]))
    lv, _d = FS.levels_of(vs)
    got = FS.hits(vs, lv)
    kd = got.get((FS.RULER, "DUSDT", round(T0, 3)))
    kn = got.get((FS.RULER, "NUSDT", round(T0 + H, 3)))
    assert kd == 3, ("подсадка не найдена", kd)
    assert kn is None, ("шум порезан — правило режет что попало", kn)
    cut = FS.cut_record(vs[(FS.RULER, "DUSDT", round(T0, 3))]["rec"], kd,
                        lv[(FS.RULER, "DUSDT", round(T0, 3))])
    assert -0.26 < float(cut["pnl"]) < -0.20, cut["pnl"]


# --------------------------------------------------------- касса и окно

@test
def форма_равна_кассе():
    """Своей кассы нет: форма совпадает с ячейкой семейства, охрана в ней."""
    cache = deep_cache()
    mkt = StubMkt(lambda at: 2 if int((at - T0) / H) % 24 == 0 else None)
    was = RP._MARKET
    try:
        RP._MARKET = mkt
        mine = FS.book_form(cache, CTX, launch_of(cache), now=NOW, log=quiet)
        cell = G.cell_stats(AG.packed_short(cache), CTX, launch_of(cache),
                            now=NOW, log=quiet, keys=[FS.BOOK], deps=[DEP])
    finally:
        RP._MARKET = was
    c = cell.get(f"{FS.BOOK}:{int(DEP)}") or {}
    for f in ("n", "usd", "final", "max_dd", "win", "day_median", "taken"):
        assert mine.get(f) == c.get(f), (f, mine.get(f), c.get(f))
    assert mine["exits"] == c["exits"], (mine["exits"], c["exits"])
    assert mine["guard"]["closed_by_market"] > 0, mine["guard"]
    assert FS.EXIT in mine["exits"] or "рынок" in mine["exits"], mine["exits"]


@test
def порядок_пола_и_охраны():
    """Раньше — тот, кто раньше; ничья остаётся за полом."""
    cuts = [-0.05, -0.12, -0.30, -0.35, -0.42, -0.50]     # пол на часе 3
    rows = [rec("AUSDT", 0, cuts), rec("BUSDT", 8, cuts), rec("CUSDT", 16, cuts)]
    plan = {rows[0]["at"]: 5, rows[1]["at"]: 2, rows[2]["at"]: 3}
    cache = cache_of(rows)
    vs = views_of(cache)
    lv, _d = FS.levels_of(vs)
    mod = FS.apply_floor(cache, FS.hits(vs, lv), lv)
    mkt = StubMkt(lambda at: plan.get(at))
    st = FS.book_form(mod, CTX, launch_of(cache), now=NOW, log=quiet, mkt=mkt)
    ex = st["exits"]
    assert (ex.get(FS.EXIT) or {}).get("n") == 2, ex     # A и C — полом
    assert (ex.get("рынок") or {}).get("n") == 1, ex     # B — охраной раньше


@test
def окно_показа_не_пересчитывает_кассу():
    """Окно режет ПОКАЗ, а не счёт: раздача денег остаётся на всей истории."""
    cache = deep_cache(n=15, step_h=12)
    lp = launch_of(cache)
    whole = FS.book_form(cache, CTX, lp, now=NOW, log=quiet,
                         mkt=StubMkt())
    since = T0 + 60 * H
    part = FS.book_form(cache, CTX, lp, now=NOW, log=quiet, mkt=StubMkt(),
                        since=since)
    assert part["n"] < whole["n"], (part["n"], whole["n"])
    assert part["taken"] == whole["taken"], (part["taken"], whole["taken"])
    assert part["offered"] == whole["offered"], part["offered"]


# ------------------------------------------------------------- вердикты

@test
def порог_убийцы_А_доля_измеренного():
    """Порог (А) — доля ИЗМЕРЕННОГО худшего дня базовой, не литерал."""
    a = FS.verdict_worst({"day_worst_usd": -900.0, "worst_day": "д1"},
                         {"day_worst_usd": -500.0, "worst_day": "д2"})
    b = FS.verdict_worst({"day_worst_usd": -300.0, "worst_day": "д1"},
                         {"day_worst_usd": -700.0, "worst_day": "д2"})
    assert abs(a["thr"] + 600.0) < 0.01, a
    assert abs(b["thr"] + 200.0) < 0.01, b
    assert a["dead"] is False and b["dead"] is True, (a, b)


@test
def вердикт_выводится_из_числа():
    """Фраза следует за числом, а не стоит рядом с ним литералом."""
    alive = FS.verdict_worst({"day_worst_usd": -900.0, "worst_day": "д1"},
                             {"day_worst_usd": -100.0, "worst_day": "д2"})
    dead = FS.verdict_worst({"day_worst_usd": -900.0, "worst_day": "д1"},
                            {"day_worst_usd": -800.0, "worst_day": "д2"})
    assert alive["dead"] is False and "жива" in alive["why"], alive
    assert dead["dead"] is True and "МЕРТВА" in dead["why"], dead
    assert "-800" in dead["why"].replace("−", "-"), dead["why"]
    none = FS.verdict_worst({"day_worst_usd": None}, {"day_worst_usd": -1.0})
    assert none["dead"] is None and none["why"], none


@test
def убийца_Б_из_доли_зёрен():
    """Контроль судит долей зёрен, и порог объявлен заданием."""
    assert FS.verdict_control(0.04, 200, 10)["dead"] is False
    assert FS.verdict_control(FS.BEAT_MAX, 200, 10)["dead"] is True
    assert FS.verdict_control(0.5, 200, 10)["dead"] is True
    nm = FS.verdict_control(None, 200, 0)
    assert nm["dead"] is None and "не посчитан" in nm["why"], nm


@test
def убийца_В_обе_половины():
    """Медиана дня И «без 3 лучших дней» — убивает любая из двух."""
    ok = {"day_median_usd": 100.0, "usd_wo_top3d": 500.0}
    m = {"day_median_usd": -1.0, "usd_wo_top3d": 500.0}
    w = {"day_median_usd": 100.0, "usd_wo_top3d": -1.0}
    assert FS.verdict_shape(ok)["dead"] is False, FS.verdict_shape(ok)
    assert FS.verdict_shape(m)["dead"] is True, FS.verdict_shape(m)
    assert FS.verdict_shape(w)["dead"] is True, FS.verdict_shape(w)
    thin = FS.verdict_shape({"day_median_usd": 100.0, "usd_wo_top3d": None})
    assert thin["dead"] is False and "не измерено" in thin["why"], thin


@test
def убийца_Г_прочерк_без_форварда():
    """Форварда у необъявленной сестры нет: прочерк с причиной, не «жива»."""
    g = FS.verdict_forward(0)
    assert g["dead"] is None, g
    assert "форвардных суток у сестры ноль" in g["why"], g
    few = FS.verdict_forward(3)
    assert few["dead"] is None and "не измерено" in few["why"], few
    assert FS.verdict_forward(FS.MIN_FWD_DAYS)["dead"] is None


@test
def итог_собирается_из_вердиктов():
    vs = [{"key": "А", "dead": True}, {"key": "Б", "dead": False},
          {"key": "Г", "dead": None}]
    s = FS.summary_of(vs, "шаг")
    assert "МЕРТВА по убийце А" in s and "не измерено: Г" in s, s
    s2 = FS.summary_of([{"key": "Б", "dead": False}], "шаг")
    assert "МЕРТВА" not in s2 and "жива по Б" in s2, s2


# ------------------------------------------------------- отказ и прочерк

@test
def ноль_не_выдаёт_себя_за_результат():
    """Ни одного пореза при непустом входе — отказ, а не отчёт."""
    cache = flat_cache()
    got = FS.run_marks(seeds=0, cache=cache, ctx=CTX, launch=launch_of(cache),
                       now=NOW, log=quiet, mkt=StubMkt())
    assert got.get("error") and "не сработал" in got["error"], got
    empty = FS.run_marks(seeds=0, cache={}, ctx=CTX, launch={}, now=NOW,
                         log=quiet, mkt=StubMkt())
    assert empty.get("error") and "пуст" in empty["error"], empty
    no_marks = cache_of([dict(rec("AUSDT", 0, [-0.5]), marks=[])])
    nm = FS.run_marks(seeds=0, cache=no_marks, ctx=CTX,
                      launch=launch_of(no_marks), now=NOW, log=quiet,
                      mkt=StubMkt())
    assert nm.get("error") and "закрытых записей" in nm["error"], nm


@test
def величина_которой_нет_прочерк():
    """Ноль означает «измерено и равно нулю»; неизмеренное — прочерк."""
    c = FS.columns({"n": 3})
    assert c["day_worst_usd"] is None and c["day_median_usd"] is None, c
    assert c["usd_wo_top3d"] is None and c["tails"] == 0, c
    assert FS.columns(None) is None
    assert FS._u(None) == "—" and FS._sh(None) == "—" and FS._n(None) == "—"
    q = FS._quant([])
    assert q["med"] is None and q["n"] == 0, q


# ------------------------------------------------------- шаг 1 целиком

@test
def потолок_считается_целиком():
    """Шаг 1 отдаёт колонки спора, контроль и вердикты по всем убийцам."""
    cache = deep_cache(n=18, step_h=6)
    got = FS.run_marks(seeds=2, cache=cache, ctx=CTX, launch=launch_of(cache),
                       now=NOW, log=quiet, mkt=StubMkt())
    assert not got.get("error"), got
    assert got["changed"]["n"] > 0 and got["delta"]["n"] == got["changed"]["n"]
    for name in ("base", "sister_mark", "sister_level"):
        assert got[name] and got[name]["usd"] is not None, name
    assert got["sister_level"]["usd"] > got["sister_mark"]["usd"], got
    assert [v["key"] for v in got["verdicts"]] == ["А", "Б", "В", "Г"]
    assert got["beat"] is not None and got["seeds"] == 2, got["beat"]
    assert got["liq_check"]["n"] >= 0 and got["summary"]
    txt = FS.report({"marks": got})
    assert "Шаг 1" in txt and "Объявленные убийцы" in txt, txt[-300:]
    assert "Шаг 2 (реплей ядром) не считался" in txt, txt[-300:]


@test
def отчёт_не_падает_на_пустом():
    """Каждая дорога до показа проверяется отдельно, включая пустую."""
    for s in ({}, {"marks": {"error": "нечего"}},
              {"replay": {"error": "нечего"}},
              {"marks": None, "replay": None}):
        t = FS.report(s)
        assert "Вердикт" in t, t[-200:]
    # смоук обязан кричать, что он смоук
    t = FS.report({"marks": {"limit": 5, "error": "мало"}})
    assert "ОГРАНИЧЕННОЙ выборке" in t, t[:400]
    assert "ОГРАНИЧЕННОЙ" not in FS.report({"marks": {"error": "мало"}})


# --------------------------------------------------- кэш сестры и реплей

@test
def кэш_сестры_свой_и_с_полом():
    """Записи сестры не трогают кэш книги, а пол входит в подпись."""
    p = FS.cache_path()
    assert os.path.abspath(p).startswith(HERE + os.sep), p
    assert os.path.abspath(p) != os.path.abspath(S.CACHE), p
    sig, base = FS.sister_sig(), S.cache_sig()
    assert sig["floor"][FS.BOOK] == FS.FLOOR, sig
    assert base["floor"][FS.BOOK] != FS.FLOOR, base
    assert sig != base, "подпись сестры обязана отличаться от подписи книги"
    assert FS.cache_path(0.5) != p, FS.cache_path(0.5)


@test
def пол_возвращается_после_реплея():
    """Пол симуляции — на время прогона, и возвращается даже при падении."""
    seen, was = {}, D2.FLOOR_FRAC
    real = G.replay

    def boom(*_a, **_k):
        seen["floor"] = D2.FLOOR_FRAC
        raise RuntimeError("реплей упал")
    try:
        G.replay = boom
        try:
            FS.replay_floor([{"sym": "AUSDT", "at": T0}], log=quiet)
        except RuntimeError:
            pass
    finally:
        G.replay = real
    assert abs(seen.get("floor", -1) - FS.FLOOR) < 1e-12, seen
    assert D2.FLOOR_FRAC == was, (D2.FLOOR_FRAC, was)


@test
def изменённые_позиции_по_реплею():
    """Пол умеет только укорачивать: изменённая позиция вышла РАНЬШЕ."""
    cums = [-0.05, -0.12, -0.30, -0.35, -0.42, -0.50]
    base = rec("AUSDT", 0, cums)
    same = rec("BUSDT", 8, cums)
    short_marks = dict(rec("CUSDT", 16, [-0.30, -0.40]),
                       exit_ts=T0 + 16 * H + 6 * H - 1.0)
    bcache = cache_of([base, same, short_marks])
    bviews = views_of(bcache)
    lv, _d = FS.levels_of(bviews)
    kb = (FS.RULER, "AUSDT", round(base["at"], 3))
    kc = (FS.RULER, "CUSDT", round(short_marks["at"], 3))
    sister = {kb: FS.cut_record(base, 3, lv[kb]),
              (FS.RULER, "BUSDT", round(same["at"], 3)): same,
              # вышла раньше базовой, но отметки базовой до этого часа
              # не доходят: разыгрывать случайный выход не среди кого
              kc: dict(short_marks, exit_ts=short_marks["at"] + 3 * H - 1.0,
                       exit=FS.EXIT, pnl=lv[kc]),
              (FS.RULER, "ZUSDT", 1.0): rec("ZUSDT", 24, cums)}
    ch, why = FS.replay_changed(bcache, sister, bviews)
    assert list(ch) == [kb] and ch[kb] == 3, (ch, why)
    assert why.get("решения нет в кэше базовой книги") == 1, why
    assert why.get("час пореза вне записи базовой") == 1, why
    d = FS.replay_delta(bcache, sister, ch)
    want = float(sister[kb]["pnl"]) - float(base["pnl"])
    assert d["n"] == 1 and abs(d["sum"] - want) < 1e-12, (d, want)
    assert d["sum"] > 0, d                          # порез спас часть маржи
    # «хвостовых» считается по БАЗОВОЙ записи: у сестры порез всегда
    # кончается полом, и счёт по ней равнялся бы числу порезов всегда
    assert d["tails"] == 0, d                       # база вышла по сроку
    b2 = dict(bcache)
    b2[kb] = dict(base, exit="пол")
    d2 = FS.replay_delta(b2, sister, ch)
    assert d2["tails"] == 1, d2


@test
def разрыв_через_пол_считается():
    """Исход ниже уровня — разрыв; ликвидация считается отдельно."""
    at_level = rec("AUSDT", 0, [-0.24], exit="пол")
    lv = FS.floor_level(at_level)["pnl"]
    at_level = rec("AUSDT", 0, [lv], exit="пол")
    below = rec("BUSDT", 1, [lv - 0.30], exit="пол")
    liq = rec("CUSDT", 2, [-1.0], exit="ликвидация")
    win = rec("DUSDT", 3, [0.2], exit="тейк")
    cache = cache_of([at_level, below, liq, win])
    vs = views_of(cache)
    lvls, _d = FS.levels_of(vs)
    g = FS.gap_of(vs, lvls)
    assert g["n"] == 3 and g["below"] == 2 and g["liq"] == 1, g
    assert g["gap"]["med"] is not None and g["share"] == round(2 / 3, 3), g
    none = FS.gap_of({k: v for k, v in vs.items() if k[1] == "DUSDT"}, lvls)
    assert none["n"] == 0 and none["why"], none


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
