#!/usr/bin/env python3
"""Проверки механики a47008e1 — охрана рынком как правило выхода.

Каждая проверка отвечает за одно правило, и к каждому правилу в
`build.json` приложена подделка, от которой она обязана упасть. Проверка,
которая не кусается, не проверяет ничего.

Что проверяется: касса не заводится второй копией (форма равна ячейке
семейства); прочерк вместо ноля у дня, которого нет; калибровочная пара
обеими ногами (подсаженный ход волны находится с точностью до минуты,
шум молчит); заглядывание в будущее (переписать будущее — прошлое не
шелохнулось); порог «меньше пяти прокси — волны нет»; минутный срез
записи равен часовому срезу оси; розыгрыш контроля тот же, что у оси;
охрана срабатывает строго до фактического выхода; задержка исполнения
считается, а не подразумевается нулём; пустая охрана — отказ, а не
отчёт с прочерками; вердиктовые фразы выведены из чисел; порядок шагов
(реплей не считается, пока потолок не пройден); сетка порогов берётся у
`path_screen`, а не назначается здесь.

Вывод скуп намеренно: приёмка смотрит ПОСЛЕДНИЕ 4000 символов, и строка
«ПРОВАЛ имя», утонувшая в середине, есть контроль, который здесь
пройдёт, а там нет.

    .venv/bin/python research/mech_a47008e1/test_guard_sister.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard_sister as GS                                     # noqa: E402
from guard_sister import AG, P, WG                            # noqa: E402

TESTS = []
H = GS.HOUR
M = GS.MINUTE
T0 = 1786176000.0                      # ровная граница часа и суток
NOW = T0 + 60 * H
CTX = {"error": "издержки в проверке не считаются"}


def test(fn):
    TESTS.append(fn)
    return fn


def quiet(*_a):
    pass


# ---------------------------------------------------------------- фикстуры

def marks_of(at, pnl, n_h):
    """Почасовые приращения, сумма которых РАВНА исходу.

    Дрожание намеренное: ровные приращения спрятали бы разницу между
    «где стоит позиция к часу k» и её итогом, а срез по минуте как раз
    об этом.
    """
    rng = np.random.default_rng(int(at) % 9973 + n_h)
    d = list(rng.normal(0.0, 0.05, max(1, n_h - 1)))
    d.append(float(pnl) - sum(d))
    return [[at + i * H, round(float(x), 6)] for i, x in enumerate(d)]


def rec(sym, i_h, pnl, hold_h=24, lev=3.0, fwd=100.0, at=None):
    at = float(T0 + i_h * H if at is None else at)
    out_ts = at + hold_h * H - 1.0
    mk = marks_of(at, pnl, hold_h)
    return {"at": at, "exit_ts": out_ts, "pnl": float(pnl),
            "pnl_net": float(pnl) - 0.002, "lev": float(lev),
            "fwd": float(fwd), "sym": sym, "side": "short",
            "exit": "срок", "marks": mk, "end_ts": out_ts,
            "sched_end": at + hold_h * H, "depth": 1, "avg": 100.0,
            "entry_px": 100.0, "exit_px": 100.0,
            "fills": [[at, 100.0, 0.25]], "state": "closed",
            "fav_bp": 300.0, "rr": 0.5}


def cache_of(rows, ruler=None):
    """Кэш реплея в живой форме: ключ — (линейка, имя, момент)."""
    ruler = ruler or GS.RULER
    return {(ruler, r["sym"], round(float(r["at"]), 3)): r for r in rows}


def small_cache(n=12, step_h=8):
    """Кэш на НЕСКОЛЬКО суток: колонки концентрации без четырёх дней не
    существуют, и фикстура на одних сутках прятала бы их прочерком."""
    rows = []
    for i in range(n):
        rows.append(rec(f"S{i % 4}USDT", i * step_h, (0.3 if i % 3 else -0.9),
                        fwd=100.0 + i))
    return cache_of(rows)


def launch_of(cache, days=400.0):
    return {k[1]: T0 - days * 86400.0 for k in cache}


class StubMkt:
    """Рынок по часам: волна задаётся функцией от часа с входа И от момента.

    Момент нужен нулю сдвига: волна, зависящая ТОЛЬКО от длины окна, на
    сдвинутом рынке дала бы те же числа, и нуль выглядел бы работающим,
    ничего не меняя.
    """

    def __init__(self, wave_of=None):
        self.wave_of = wave_of or (lambda k, t0: None)
        self.wave_none = 0

    def wave(self, t0, t1):
        k = int(round((float(t1) - float(t0)) / H))
        w = self.wave_of(k, float(t0))
        if w is None:
            self.wave_none += 1
        return w

    def move(self, _sym, _t0, _t1):
        return None

    def beta_pre(self, _sym, _at, **_kw):
        return None, None, 0


def views_of(cache, wave_of=None):
    mkt = StubMkt(wave_of)
    return {k: P.view_of(r, mkt) for k, r in cache.items()}, mkt


def window_wave(cache, hi=0.03, k_min=4):
    """Волна ≥ `hi` после часа `k_min`, но ТОЛЬКО внутри окна фикстуры.

    Вне окна (там, где окажется сдвинутая волна) рынок стоит: нуль
    сдвига обязан получить другой ряд, иначе он ничего не проверяет.
    """
    last = max(float(k[2]) for k in cache) + 48 * H

    def of(k, t0=None):
        if t0 is not None and (t0 < T0 - H or t0 > last):
            return 0.0
        return hi if k >= k_min else 0.0
    return of


def bars_of(t0, t1, px_of, step=M):
    """Минутные бары по функции цены: [t, o, h, l, c, объём]."""
    out = []
    t = float(int(t0 // step) * step)
    while t <= t1:
        p = float(px_of(t))
        out.append([t, p, p, p, p, 1.0])
        t += step
    return out


def planted_px(at, jumps):
    """Цена прокси: ступеньки, объявленные парами (минута с входа, цена)."""
    def px(t):
        m = (float(t) - at) / M + 1.0        # минута 1 — бар в момент `at`
        p = 100.0
        for m0, v in jumps:
            if m >= m0:
                p = v
        return p
    return px


def planted_wave(at, jumps, hours=26, proxies=None, min_have=None, until=None):
    """Волна на подсаженных барах — тем же кодом, что живая.

    `min_have` — сколько прокси-имён получат бары вовсе; остальные
    останутся без цены, и это ровно тот случай, который волна обязана
    считать несобравшейся. `until` — пара (сколько имён пишут до конца,
    до какой минуты пишут остальные): так проверяется порог на МИНУТЕ, а
    не только на входе.
    """
    proxies = proxies or GS.PROXY
    have = len(proxies) if min_have is None else int(min_have)
    keep, until_m = until or (len(proxies), None)
    px = planted_px(at, jumps)
    t0, t1 = at - H, at + hours * H

    def read(sym, a, b):
        i = proxies.index(sym)
        if i >= have:
            return []
        end = min(b, t1)
        if i >= keep and until_m is not None:
            end = min(end, at + (until_m - 1) * M)
        return bars_of(max(a, t0 - 2 * M), end, px)

    return GS.MinuteWave(t0, t1, read=read, proxies=proxies, log=quiet).build()


def flat_paths(cache, n=GS.HOLD_MIN, pnl_of=None):
    """Минутные пути: pnl минуты i = i/1000, время бара = at + i·минута."""
    pnl_of = pnl_of or (lambda i: i / 1000.0)
    out = {}
    for key, r in cache.items():
        at, out_ts = float(r["at"]), float(r["exit_ts"])
        pnl = np.full(n, np.nan)
        ts = np.full(n, np.nan)
        for i in range(n):
            t = at + i * M
            if t >= out_ts:
                break
            ts[i] = t
            pnl[i] = pnl_of(i)
        out[key] = (pnl, ts)
    return out


# ------------------------------------------------------------- касса и колонки

@test
def форма_равна_кассе():
    """Форма книги обязана совпадать с ячейкой семейства бит в бит.

    Иначе в проекте появилась бы вторая касса, и обе выглядели бы
    исправными.
    """
    cache = small_cache()
    launch = launch_of(cache)
    st = GS.book_form(cache, CTX, launch, now=NOW, log=quiet)
    cell = AG.stats_of(AG.packed_short(cache), CTX, launch,
                       [GS.BOOK], deps=[GS.DEP], now=NOW)[
        f"{GS.BOOK}:{int(GS.DEP)}"]
    assert st, "форма книги пуста"
    for f in ("n", "usd", "final", "max_dd", "day_median", "win", "taken"):
        assert st.get(f) == cell.get(f), (f, st.get(f), cell.get(f))
    assert st.get("usd_wo_top3d") is not None, st
    assert st.get("usd_wo_top") is not None, st


@test
def фильтр_возраста_применён():
    """Молодое имя книга не берёт — и ровно это делает касса.

    Без вызова фильтра форма считала бы по большему составу, чем
    торгует книга.
    """
    cache = small_cache()
    launch = launch_of(cache)
    young = sorted(launch)[0]
    launch[young] = T0 - 1.0 * 86400.0          # имя моложе порога
    st = GS.book_form(cache, CTX, launch, now=NOW, log=quiet)
    cell = AG.stats_of(AG.packed_short(cache), CTX, launch,
                       [GS.BOOK], deps=[GS.DEP], now=NOW)[
        f"{GS.BOOK}:{int(GS.DEP)}"]
    full = GS.book_form(cache, CTX, launch_of(cache), now=NOW, log=quiet)
    assert st["n"] == cell["n"], (st["n"], cell["n"])
    assert st["n"] < full["n"], (st["n"], full["n"])


@test
def колонка_дня_прочерк_а_не_ноль():
    """Дня нет в своде — прочерк с причиной; есть — число."""
    cache = small_cache()
    st = GS.book_form(cache, CTX, launch_of(cache), now=NOW, log=quiet)
    c = GS.columns(st, named_day="1999-01-01")
    assert c["named_usd"] is None, c["named_usd"]
    assert c["named_why"], "причина прочерка не названа"
    have = (st.get("days_rows") or [])[0]["d"]
    c2 = GS.columns(st, named_day=have)
    assert c2["named_usd"] is not None and c2["named_why"] is None, c2


# --------------------------------------------------------- волна по минутам

@test
def калибровка_подсаженная_волна():
    """Подсаженный ход +2.5 % находится с точностью до минуты.

    Литерал в утверждении намеренный: «нашлось что-то» — не находка.
    """
    at = T0 + 3 * H
    w = planted_wave(at, [(100, 102.5), (150, 100.5), (300, 103.0)])
    m, val = w.cross(at, GS.HOLD_MIN, 2.0)
    assert m == 100, m
    assert abs(val - 0.025) < 1e-9, val
    # ровно на пороге — срабатывает (нестрогое неравенство)
    w2 = planted_wave(at, [(77, 102.0)])
    assert w2.cross(at, GS.HOLD_MIN, 2.0)[0] == 77, w2.cross(at, GS.HOLD_MIN, 2.0)


@test
def калибровка_шум_молчит():
    """На шуме без хода волна порога не пересекает — ни одной минуты."""
    at = T0 + 3 * H
    rng = np.random.default_rng(11)
    steps = {}

    def px(t):
        k = int((float(t) - (at - H)) // M)
        if k not in steps:
            steps[k] = 100.0 * (1.0 + 0.0004 * float(rng.normal()))
        return steps[k]

    w = GS.MinuteWave(at - H, at + 26 * H,
                      read=lambda _s, a, b: bars_of(a, b, px),
                      proxies=GS.PROXY, log=quiet).build()
    m, top = w.cross(at, GS.HOLD_MIN, 2.0)
    assert m is None, (m, top)
    assert top is not None and abs(top) < 0.02, top


@test
def будущее_не_меняет_прошлого():
    """Переписать будущее — минута пересечения не шелохнётся.

    Ход подсаживается ОДИН (100-я минута, дальше волна ниже порога), а в
    будущее дописывается ход, которого не было: правило, глядящее вперёд
    (последнее пересечение, максимум, лучший выход), от этого сдвинется,
    правило первой минуты — нет.

    И обратное: переписанное ДО пересечения ответ меняет — иначе
    проверка не умела бы ловить вовсе.
    """
    at = T0 + 3 * H
    jumps = [(100, 102.5), (150, 100.5)]
    w = planted_wave(at, jumps)
    m0 = w.cross(at, GS.HOLD_MIN, 2.0)[0]
    assert m0 == 100, m0
    w.c[:, w.j(at) + 400:] = 1e6                # ход, которого не было
    assert w.cross(at, GS.HOLD_MIN, 2.0)[0] == m0, (m0, "будущее сдвинуло")
    w2 = planted_wave(at, jumps)
    w2.c[:, w2.j(at) + 99:] = 100.0             # убрали сам ход
    assert w2.cross(at, GS.HOLD_MIN, 2.0)[0] != m0, "проверка ничего не ловит"


@test
def меньше_пяти_прокси_нет_волны():
    """Имён с ценой меньше порога — волны нет, а не среднее по двум.

    Порог проверяется на КАЖДОЙ минуте, а не только на входе: имена
    перестают писаться по одному, и минута, где цену держат четверо,
    волны не имеет, даже если на входе их было двадцать.
    """
    at = T0 + 3 * H
    few = planted_wave(at, [(100, 102.5)], min_have=GS.MIN_PROXY - 1)
    assert few.cross(at, GS.HOLD_MIN, 2.0)[0] is None, "волна собралась из мала"
    assert few.thin > 0, few.thin
    part = planted_wave(at, [(300, 104.0)], until=(GS.MIN_PROXY - 1, 200))
    assert part.cross(at, GS.HOLD_MIN, 2.0)[0] is None, \
        "к 300-й минуте цену держат четверо, а волна нашлась"
    enough = planted_wave(at, [(100, 102.5)], min_have=GS.MIN_PROXY)
    assert enough.cross(at, GS.HOLD_MIN, 2.0)[0] == 100, "порога хватило, а волны нет"


@test
def база_волны_до_входа():
    """Ход считается от закрытия ПЕРЕД входом, а не от первой минуты сделки.

    Прыжок ровно в минуту входа обязан быть виден: взяв базой саму
    минуту входа, охрана пропустила бы ход, случившийся на входе.
    """
    at = T0 + 3 * H
    w = planted_wave(at, [(1, 102.5)])
    assert w.cross(at, GS.HOLD_MIN, 2.0)[0] == 1, w.cross(at, GS.HOLD_MIN, 2.0)


# --------------------------------------------------------------- срез записи

@test
def минутный_срез_равен_часовому():
    """На границе часа минутный срез обязан совпасть со срезом оси.

    Разойдись они — реплей внутри часа считал бы деньги другой меркой,
    чем потолок, и сравнение двух шагов ничего не значило бы.
    """
    r = rec("S0USDT", 2, -0.4)
    k = 5
    cum = P.path_of(r)["cum"][k]
    mine = GS.cut_at(r, float(r["at"]) + k * H - 1.0, cum, why="правило выхода")
    theirs = P.exit_at(r, k)
    for f in ("pnl", "exit_ts", "exit", "state", "exit_px", "pnl_net"):
        assert mine.get(f) == theirs.get(f), (f, mine.get(f), theirs.get(f))
    a = [[float(m[0]), round(float(m[1]), 9)] for m in mine["marks"]]
    b = [[float(m[0]), round(float(m[1]), 9)] for m in theirs["marks"]]
    assert a == b, (a[-2:], b[-2:])


@test
def срез_держит_сумму_отметок():
    """Сумма приращений отметок среза равна исходу среза."""
    r = rec("S1USDT", 4, 0.7)
    ts = float(r["at"]) + 3 * H + 17 * M
    cut = GS.cut_at(r, ts, -0.123456)
    assert abs(sum(float(m[1]) for m in cut["marks"]) + 0.123456) < 1e-9, \
        cut["marks"]
    assert float(cut["exit_ts"]) == ts, cut["exit_ts"]


# ------------------------------------------------------------------ контроль

@test
def розыгрыш_как_у_оси():
    """Розыгрыш контроля обязан быть ТОТ ЖЕ, что у оси в path_screen.

    Иначе контроль мерил бы другой случай, чем правило, и «не хуже в
    N % зёрен» отвечало бы не на тот вопрос.
    """
    cache = small_cache(10)
    views, _m = views_of(cache)
    keys = sorted(cache)
    changed = {keys[0]: 3, keys[1]: 5, keys[2]: 7}
    idx = P.open_index(views)
    theirs = P.control_exits(cache, views, changed, CTX, launch_of(cache),
                             seeds=4, dep=GS.DEP, now=NOW, log=quiet, idx=idx)
    mine = []
    for i in range(4):
        mod, _nc = GS.draw(cache, lambda rk, k: (idx.get(rk) or {}).get(k) or [],
                           changed, i, lambda key, k: P.exit_at(cache[key], k))
        s = 0.0
        for key, r in mod.items():
            if r is not cache[key]:
                s += float(r["pnl"]) - float(cache[key]["pnl"])
        mine.append(round(s, 9))
    assert [round(x, 9) for x in theirs["sum"]] == mine, (theirs["sum"], mine)


@test
def контроль_по_колонке_спора():
    """Контроль считается по ВСЕМ объявленным колонкам, а не по итогу.

    Убийца 1 спорит о «$ без 3 лучших дней»; доля зёрен, посчитанная по
    другой величине, к этому спору отношения не имеет.
    """
    cache = small_cache(14)
    views, _m = views_of(cache, wave_of=lambda k, _t=None: 0.03 if k >= 4 else 0.0)
    base = GS.columns(GS.book_form(cache, CTX, launch_of(cache), now=NOW,
                                   log=quiet))
    cells = GS.cells_axis(cache, views, CTX, launch_of(cache), base, seeds=3,
                          now=NOW, log=quiet, say=quiet)
    vc = [c for c in cells if c.get("verdict_cell")]
    assert len(vc) == 1, [c["val"] for c in cells]
    vc = vc[0]
    assert vc["delta"]["n"] > 0, vc["delta"]
    assert set(vc["beat"]) == {f for f, _t in GS.COLS}, sorted(vc["beat"])
    assert vc["control"]["n"] == 3, vc["control"]
    assert GS.VERDICT_COL in vc["beat"], vc["beat"]


# -------------------------------------------------------------- охрана и срок

@test
def охрана_строго_до_выхода():
    """Пересечение после фактического выхода сделку не трогает.

    И причина называется своя: «волна есть, порог не пересечён» — не то
    же, что «волны нет вовсе», лечатся они разным.
    """
    at = T0 + 3 * H
    cache = cache_of([rec("S0USDT", 3, 0.2, hold_h=2)])       # выход через 2 ч
    w = planted_wave(at, [(200, 103.0)])                      # ход на 200-й минуте
    got, why = GS.guard_minutes(cache, w, flat_paths(cache))
    assert not got, got
    assert why["no_cross"] == 1 and why["no_wave"] == 0, why
    thin = planted_wave(at, [(30, 103.0)], min_have=GS.MIN_PROXY - 1)
    _g, why2 = GS.guard_minutes(cache, thin, flat_paths(cache))
    assert why2["no_wave"] == 1 and why2["no_cross"] == 0, why2
    w2 = planted_wave(at, [(30, 103.0)])                      # ход внутри срока
    got2, _why2 = GS.guard_minutes(cache, w2, flat_paths(cache))
    assert len(got2) == 1, (got2, "внутри срока охрана обязана сработать")


@test
def задержка_минуты_считается():
    """Выход берётся минутой позже пересечения — и это видно числом."""
    at = T0 + 3 * H
    cache = cache_of([rec("S0USDT", 3, 0.2, hold_h=24)])
    w = planted_wave(at, [(100, 103.0)])
    paths = flat_paths(cache)          # pnl минуты i = i/1000
    lagged, _a = GS.guard_minutes(cache, w, paths, lag=1)
    zero, _b = GS.guard_minutes(cache, w, paths, lag=0)
    key = sorted(cache)[0]
    assert zero[key][0] == 100 and lagged[key][0] == 100, (zero, lagged)
    assert abs(zero[key][2] - 0.099) < 1e-9, zero[key]
    assert abs(lagged[key][2] - 0.100) < 1e-9, lagged[key]
    assert lagged[key][3] - zero[key][3] == M, (lagged[key], zero[key])


@test
def пустая_охрана_отказ():
    """Охрана не сработала — отказ с причиной, а не колонки прочерками."""
    at = T0 + 3 * H
    cache = small_cache(6)
    w = planted_wave(at, [], hours=30)                # ходу неоткуда взяться
    out = GS.replay_cell(cache, w, flat_paths(cache), CTX, launch_of(cache),
                         seeds=0, now=NOW, log=quiet, say=quiet)
    assert out["n"] == 0, out["n"]
    assert out.get("empty"), out
    assert out["cols"] is None, "пустота выдала себя за результат"


@test
def реплей_считает_колонки_и_контроль():
    """Сработавшая охрана даёт колонки и контроль по тем же колонкам."""
    cache = small_cache(8)
    at = float(sorted(cache)[0][2])
    w = planted_wave(at, [(60, 104.0)], hours=60)
    out = GS.replay_cell(cache, w, flat_paths(cache), CTX, launch_of(cache),
                         seeds=3, now=NOW, log=quiet, say=quiet)
    assert out["n"] > 0, out["why"]
    assert out["cols"] and out["cols"]["n"] is not None, out["cols"]
    assert set(out["beat"]) == {f for f, _t in GS.COLS}, sorted(out["beat"])
    assert out["control"]["n"] == 3, out["control"]


@test
def пути_собираются_по_пачкам():
    """Пути копятся по всем пачкам, чужая линейка не идёт, отказы — числом.

    Реплей вызывается подставным: здесь проверяется РАЗБОР его ответа, а
    не сам реплей (тот считает ядро и стоит часы).
    """
    # Пачки НЕ равны size: символ не рвётся. У фикстуры имена `S{i%4}`, и
    # на 9 ногах это S0 — три ноги, S1/S2/S3 — по две; при size=3 выходит
    # 3+2+2+2, четыре пачки. Числа посчитаны по фикстуре руками, а не
    # спрошены у `by_symbol`: ожидание, взятое у проверяемого кода, сходится
    # с ним всегда. Ровное деление 9/3 здесь и было бы признаком поломки —
    # оно означало бы, что пачка разрезала имя надвое.
    cache = small_cache(9, step_h=24)
    legs = [{"sym": k[1], "at": k[2]} for k in sorted(cache)]
    seen, sizes = [], []

    def fake_replay(pack, log=None, ckpt_hours=None):
        seen.append(len(ckpt_hours or []))
        sizes.append(len(pack))
        assert len({g["sym"] for g in pack}) == 1, pack
        out = {}
        for i, g in enumerate(pack):
            key = (GS.RULER, g["sym"], round(float(g["at"]), 3))
            ck = [(0.0, float(g["at"]) + j * M, j / 100.0)
                  for j in range(GS.HOLD_MIN)]
            r = dict(cache[key], ckpt=ck)
            out[key] = r
            # чужая линейка — в пути не идёт
            out[("optimal_s", g["sym"], round(float(g["at"]), 3))] = r
            if i == 0:                        # запись без меток — своё число
                out[key] = dict(r, ckpt=None)
        return out, {}

    paths, diag = GS.replay_paths(legs, size=3, log=quiet, say=quiet,
                                  replay=fake_replay)
    assert sizes == [3, 2, 2, 2], sizes
    assert diag["batches"] == 4, diag
    assert seen and set(seen) == {GS.HOLD_MIN}, seen
    # подставной роняет метки у ПЕРВОЙ ноги каждой пачки — значит отказов
    # ровно столько, сколько пачек, а записей — остаток
    assert diag["no_ckpt"] == 4, diag
    assert diag["records"] == len(legs) - 4 == 5, diag
    assert all(k[0] == GS.RULER for k in paths), sorted(paths)[:3]
    key = sorted(paths)[0]
    pnl, ts = paths[key]
    assert abs(pnl[5] - 0.05) < 1e-9, pnl[:6]


@test
def пачки_не_рвут_символ():
    """Символ не делится между пачками: бары имени читаются раз на пачку."""
    legs = [{"sym": f"S{i % 3}USDT", "at": T0 + i * H} for i in range(30)]
    packs = GS.by_symbol(legs, size=4)
    seen = {}
    for i, pack in enumerate(packs):
        for g in pack:
            assert seen.setdefault(g["sym"], i) == i, (g["sym"], i)
    assert sum(len(p) for p in packs) == len(legs), packs


@test
def метки_ядра_на_середине_минуты():
    """Метка ядра попадает в свою минуту, а не в предыдущую.

    `k/60 · 3600` в двоичной дроби бывает меньше целой секунды, и
    метка на границе брала бы прошлый бар.
    """
    offs = GS.ckpt_offsets(GS.HOLD_MIN)
    assert len(offs) == GS.HOLD_MIN, len(offs)
    for m in (1, 2, 59, 60, 61, 1439, 1440):
        abs_t = 1786176000.0 + offs[m - 1] * H
        assert int((abs_t - 1786176000.0) // M) == m - 1, (m, abs_t)
        assert abs_t > 1786176000.0 + (m - 1) * M, (m, abs_t)


# ------------------------------------------------------------------- вердикт

@test
def убийца_один_из_числа():
    """Фраза убийцы 1 выведена из чисел, а не стоит рядом литералом."""
    base = {"usd_wo_top3d": -676.69}
    good = {"cols": {"usd_wo_top3d": 2289.0},
            "beat": {GS.VERDICT_COL: {"share": 0.0}}}
    ok, why, nums = GS.killer_one(base, good)
    assert ok is True, (ok, why)
    assert "2289" in why and "676" in why, why
    worse = {"cols": {"usd_wo_top3d": -700.0},
             "beat": {GS.VERDICT_COL: {"share": 0.0}}}
    ok2, why2, _n2 = GS.killer_one(base, worse)
    assert ok2 is False and "-700" in why2.replace("−", "-"), (ok2, why2)
    loud = {"cols": {"usd_wo_top3d": 2289.0},
            "beat": {GS.VERDICT_COL: {"share": 0.30}}}
    ok3, why3, _n3 = GS.killer_one(base, loud)
    assert ok3 is False and "30 %" in why3, (ok3, why3)
    none_, why4, _n4 = GS.killer_one(base, {"cols": {}, "beat": {}})
    assert none_ is None and "не измерено" in why4, (none_, why4)


@test
def убийца_два_сравнивает_с_базой():
    """Убийца 2 судит сестру против базы на ТЕХ ЖЕ сутках и числами."""
    base = {"final": 0.106, "ratio": 1.0}
    cell = {"cols": {"final": 0.377, "ratio": 3.0}, "beat": {"usd": {"share": 0.0}}}
    ok, why, _n = GS.killer_two(base, cell)
    assert ok is True and "37.7" in why, (ok, why)
    low = {"cols": {"final": 0.05, "ratio": 3.0}, "beat": {"usd": {"share": 0.0}}}
    assert GS.killer_two(base, low)[0] is False, GS.killer_two(base, low)
    flat = {"cols": {"final": 0.377, "ratio": 0.9},
            "beat": {"usd": {"share": 0.0}}}
    assert GS.killer_two(base, flat)[0] is False, GS.killer_two(base, flat)
    assert GS.killer_two(base, None)[0] is None, "нет реплея — не измерено"


@test
def порядок_шагов_соблюдён():
    """Реплей не считается, пока потолок не пройден; --force снимает.

    Порядок объявлен заданием: шаг, посчитанный вперёд своего условия,
    тратит часы прогона и предъявляет число, которое ничего не значит.
    """
    cache = small_cache(6)
    launch = launch_of(cache)
    w = planted_wave(float(sorted(cache)[0][2]), [], hours=30)
    s = GS.run(seeds=0, do_replay=True, cache=dict(cache), legs_=[], wave=w,
               ctx=CTX, launch=launch, now=NOW, log=quiet,
               summary_dir=os.path.join(HERE, "нет-такого-каталога"))
    assert not s.get("error"), s.get("error")
    assert s["killers"]["1"]["pass"] is not True, s["killers"]["1"]
    assert (s.get("replay") or {}).get("skipped"), s.get("replay")
    s2 = GS.run(seeds=0, do_replay=True, force=True, cache=dict(cache),
                legs_=[], wave=w, ctx=CTX, launch=launch, now=NOW, log=quiet,
                summary_dir=os.path.join(HERE, "нет-такого-каталога"))
    assert not (s2.get("replay") or {}).get("skipped"), s2.get("replay")


@test
def отказ_вместо_пустоты():
    """Закрытых позиций линейки нет — отказ, а не отчёт с прочерками."""
    s = GS.run(seeds=0, cache=cache_of([], ruler=GS.RULER), ctx=CTX,
               launch={}, now=NOW, log=quiet,
               summary_dir=os.path.join(HERE, "нет-такого-каталога"))
    assert s.get("error"), s
    assert "закрытых позиций" in s["error"], s["error"]


@test
def нуль_сдвига_волны():
    """Нуль сдвига обязан быть ДРУГИМ рядом и гасить прибавку.

    Сдвиг ноль дал бы ту же меру под другим именем: «нуль», равный самой
    мере, — это подтверждение, а не проверка.
    """
    cache = small_cache(14)
    views, mkt = views_of(cache, wave_of=window_wave(cache))
    nviews = shifted = GS.shifted_views(views, mkt)
    key = sorted(views)[0]
    assert views[key]["wave"] != shifted[key]["wave"], "нуль равен мере"
    # на своём рынке ось срабатывает, на сдвинутом — нет
    _mod, ch = P.apply_axis(cache, views, "wave", GS.THRESH)
    _mod2, ch2 = P.apply_axis(cache, nviews, "wave", GS.THRESH)
    assert len(ch) > 0, "ось не сработала и на своём рынке"
    assert len(ch2) == 0, (len(ch), len(ch2))
    zero = GS.shifted_views(views, mkt, days=0)
    assert zero[key]["wave"] == views[key]["wave"], "сдвиг 0 изменил ряд"


@test
def форвард_не_выдаёт_себя_за_пересчёт():
    """Без дня объявления форвардных суток НОЛЬ, как бы pool ни считал.

    `pool.shape_why(ряд, None)` берёт день объявления нулём и считает
    форвардом ВЕСЬ ряд: вердикт выглядел бы форвардным, будучи
    пересчётом по прошлому, которое модель видела. Число форвардных
    суток и есть то, чем это различается.
    """
    st = {"daily_no": dict((20690 + i, (10.0 if i % 3 else -4.0))
                           for i in range(12))}
    got = GS.forward_why(st)
    assert got["days"] == 12, got
    assert got["forward_days"] == 0, got
    assert "ПЕРЕСЧЁТ" in (got.get("note") or ""), got
    later = GS.forward_why(st, declared_at=20695 * 86400.0)
    assert later["forward_days"] == 7, later
    assert "форвард" in (later.get("note") or ""), later


@test
def связь_берётся_у_фабрики():
    """Модулей `ceiling.py` в проекте два, и связь считает ФАБРИЧНЫЙ.

    Чужой (`t4_structure`) стоит на пути раньше и `pair_corr` не несёт:
    простой ввоз по имени отдавал его молча.
    """
    got = GS.CE.__file__.replace("\\", "/")
    assert got.endswith("research/factory/ceiling.py"), got
    assert hasattr(GS.CE, "pair_corr"), sorted(dir(GS.CE))[:12]
    a = dict((i, float(i % 3 - 1)) for i in range(1, 13))
    rho, days = GS.CE.pair_corr(a, a)
    assert days == 12 and rho is not None and abs(rho - 1.0) < 1e-6, (rho, days)


@test
def сетка_берётся_у_оси():
    """Порог и сетка не назначаются здесь: они у path_screen.AXES."""
    declared = {k: v for k, _t, v in P.AXES}["wave"]
    assert tuple(GS.GRID) == tuple(declared), (GS.GRID, declared)
    assert GS.THRESH == WG.middle(declared), (GS.THRESH, declared)
    assert GS.THRESH in tuple(declared), (GS.THRESH, declared)


@test
def отчёт_говорит_числами():
    """Отчёт печатает вердикт, колонки и причины — без падений на прочерках."""
    cache = small_cache(10)
    views, _m = views_of(cache, wave_of=lambda k, _t=None: 0.03 if k >= 6 else 0.0)
    base = GS.columns(GS.book_form(cache, CTX, launch_of(cache), now=NOW,
                                   log=quiet))
    cells = GS.cells_axis(cache, views, CTX, launch_of(cache), base, seeds=2,
                          now=NOW, log=quiet, say=quiet)
    k1, why1, _n1 = GS.killer_one(base, [c for c in cells
                                         if c.get("verdict_cell")][0])
    s = {"mech": GS.MECH, "book": GS.BOOK, "ruler": GS.RULER, "dep": GS.DEP,
         "grid": list(GS.GRID), "thresh": GS.THRESH, "base": base,
         "cells": cells, "replay": None, "wave": None,
         "killers": {"1": {"pass": k1, "why": why1, "nums": {}},
                     "2": {"pass": None, "why": "не измерено", "nums": {}}},
         "forward": {"why": "суточного ряда нет"}, "live_link": {"why": "нет"},
         "diag": {"n": len(views), "no_marks": 0, "mismatch": 0,
                  "wave_none_h": 0, "hours": {"есть": 1, "нет": 0}},
         "computed_at": "2026-09-13 00:00", "secs": 1.0}
    txt = GS.report(s)
    assert "$ без 3 лучших дней" in txt, txt[:400]
    assert "ячейка вердикта" in txt, txt[:400]
    assert why1 in txt, why1
    # Показ обязан выдержать ВСЕ три состояния шага 2: не запускался,
    # пропущен по порядку, посчитан. Падение показа после двухчасового
    # реплея есть отказ, неотличимый от тишины.
    rep = GS.replay_cell(cache, planted_wave(float(sorted(cache)[0][2]),
                                             [(60, 104.0)], hours=60),
                         flat_paths(cache), CTX, launch_of(cache), seeds=2,
                         now=NOW, log=quiet, say=quiet)
    rep["diag"] = {"legs": 1, "records": 1, "no_ckpt": 0, "batches": 1,
                   "secs": 1.0, "misaligned": 0}
    rep["sample"] = len(cache)
    rep["base"] = base
    rep["zero_lag"] = {"cols": rep.get("cols")}
    for r in (None, {"skipped": "шаг 2 не считается"},
              {"error": "реплей не дал путей"}, rep):
        t = GS.report(dict(s, replay=r,
                           wave={"proxies": 20, "have": 19, "minutes": 100,
                                 "thin": 0, "min_proxy": 5}))
        assert "Шаг 2" in t, t[-300:]
    # и блок нуля — с числом и без него
    null = GS.cells_axis(cache, GS.shifted_views(views, _m), CTX,
                         launch_of(cache), base, grid=(GS.THRESH,), seeds=0,
                         verdict=GS.THRESH, now=NOW, log=quiet, say=quiet)[0]
    null.update(shift_d=GS.NULL_SHIFT_D, changed_same=0, positions=len(views))
    t2 = GS.report(dict(s, null=null))
    assert "Нуль: волна, сдвинутая во времени" in t2, t2[-300:]
    assert "Нуль не посчитан" in GS.report(dict(s, null=None)), "нуля нет"


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
