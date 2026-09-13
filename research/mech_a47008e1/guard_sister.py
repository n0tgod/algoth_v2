#!/usr/bin/env python3
"""Механика a47008e1 — охрана рынком как правило ВЫХОДА короткой книги h24.

Заявка предлагающего 2026-09-13 (`research/factory/out/proposal.md`):
сестра безопасной короткой книги `safe_h` с ОДНИМ добавленным правилом —
закрыть шорт в первую минуту, когда волна рынка выросла на порог от
момента входа. Порог и сетка объявлены НЕ здесь: сетка берётся у
`path_screen.AXES` (ось `wave`, 1 / 2 / 3 %), ячейка вердикта — середина
этой сетки (`wave_guard.middle`), то есть 2 %. Ни одно число правила в
этом файле не назначается заново: назначенный тем же, кто его проверяет,
порог слабее назначенного независимо.

Что здесь считается — и чего здесь НЕТ.

1. **Потолок** (шаг 1, все позиции). Ось волны по ПОЧАСОВЫМ отметкам
   ядра — тот же счёт, что у `path_screen` / `wave_guard`: выход на
   границе часа есть усечение симуляции в эту секунду, и равенство уже
   проверено (`wave_guard.faithfulness`, 0 расхождений на 6100 точках).
   Новое здесь — КОЛОНКИ, которых у оси не было: «$ без трёх лучших
   дней», «$ без лучшего имени», «просадка без худшего дня», ЧИСЛО
   ВЗЯТЫХ СДЕЛОК (касса семейства берёт больше позиций на освобождённые
   деньги, и без этого числа прибавка неотличима от оборота капитала) и
   деньги сестры за названный заданием день `WORST_DAY`. Контроль —
   случайные выходы того же числа в те же часы, `SEEDS` зёрен, ПО ТЕМ ЖЕ
   КОЛОНКАМ: спор идёт о «без трёх лучших дней», значит и контроль
   считается по ней, а не по итогу.

2. **Реплей ядра внутри часа** (шаг 2). Волна пересчитывается по
   МИНУТНЫМ барам записи (`side_wave.PROXY`, `side_wave.closes_at` —
   определение волны берётся у S8, второй копии нет), минута пересечения
   находится до реплея (волна внешняя к позиции), а исход этой минуты
   отдаёт САМО ядро: `simulate_dca(checkpoints=…)` — «ровно то, чем
   кончилась бы симуляция со сроком до этой метки». Лестница, правила и
   пол капитуляции — `run_short.replay`, не копия. Считаются ДВА
   варианта: без задержки (потолок: узнали и вышли в ту же минуту) и с
   задержкой на минуту (`LAG_MIN`) — исполнение бывает только позже, и
   разница печатается числом, а не подразумевается нулём.

3. **Форвард** (шаги 3 и 4) здесь НЕ считается и считаться не может:
   форвардных суток у сестры ноль, пока она не объявлена. Правило вылета
   пула (`pool.shape_why`) применяется к ПЕРЕСЧЁТУ и помечено пересчётом:
   вердикта по нему нет. Дорога вперёд — решение владельца (`needs_owner`
   отчёта постройки).

Убийцы объявлены заданием и проверяются ПО ПОРЯДКУ: шаг 2 не считается,
если шаг 1 не прошёл (`--force` снимает порядок и помечает прогон).

Чего механика НЕ утверждает: хвост своего имени охрана не ловит (разгон
одной монеты без хода рынка волна не видит; его держит пол капитуляции),
и худший день ПО ИМЕНИ у сестры тот же, что у базы. Спор идёт о режиме
удержания, а не о хвосте.

Запуск (VPS, очередь заданий):

    run research/mech_a47008e1/guard_sister.py                # потолок
    run research/mech_a47008e1/guard_sister.py --replay --sample 400
    run research/mech_a47008e1/guard_sister.py --replay       # реплей целиком

Смоук без реплея: `--seeds 8 --limit 400 --no-publish`.
"""
import argparse
import calendar
import json
import os
import random
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
for _rel in ("research/dca_paper", "research", "research/a1_universe",
             "research/dca_ladder", "research/s8_loop", "research/s9_sweep",
             "research/factory"):
    _p = os.path.join(ROOT, _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import short_grid as G                                        # noqa: E402
import agree_book as AG                                       # noqa: E402
import arm_book as AB                                         # noqa: E402
import path_screen as P                                       # noqa: E402
import wave_guard as WG                                       # noqa: E402
import tail_screen as T                                       # noqa: E402
import instruments_refresh as IR                              # noqa: E402
import side_wave as SWV                                       # noqa: E402
import sweep as SW                                            # noqa: E402
import run_d6 as D6                                           # noqa: E402
import pool as PL                                             # noqa: E402
import stability as ST                                        # noqa: E402


def load_from(rel, name):
    """Модуль ИМЕННО из этого файла, а не первый одноимённый на пути.

    `ceiling.py` в проекте два — потолок заявки у фабрики и потолок
    уровня в `t4_structure`, — и второй стоит на пути раньше (его
    вставляет `run_d2`). Простой `import ceiling` молча отдавал ЧУЖОЙ
    модуль: связь дневных денег считалась бы не тем кодом, которым
    фабрика считает эффективное N, а вернее — не считалась бы вовсе.
    Поэтому путь называется явно, а проверка `связь_берётся_у_фабрики`
    держит это правило.
    """
    import importlib.util
    p = os.path.join(ROOT, rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CE = load_from("research/factory/ceiling.py", "factory_ceiling")

ART = "GUARD-sister"
MECH = "a47008e1"
# --- объявлено ЗАДАНИЕМ, а не этим файлом ---------------------------------
BOOK = "safe_h"                     # ячейка вердикта: безопасная короткая
RULER = S.BOOKS[BOOK]               # линейка, на которой считается позиция
DEP = 10000.0                       # депозит вердикта
GRID = WG.wave_axis()               # сетка порогов — у path_screen.AXES
THRESH = WG.middle(GRID)            # середина сетки, а не лучшая ячейка
WORST_DAY = "2026-09-12"            # худший день базовой книги, назван заданием
SEEDS = P.SEEDS                     # 200 зёрен контроля
HOUR = 3600.0
MINUTE = 60.0
HOLD_MIN = int(R.H24_HOLD_H * 60)   # минут удержания книги
LAG_MIN = 1                         # задержка исполнения, минут (честный вариант)
EXIT_LABEL = WG.EXIT_LABEL          # метка исхода — одна на охрану
PROXY = SWV.PROXY                   # волна — ТОТ ЖЕ список, что у S8
MIN_PROXY = SWV.MIN_PROXY           # меньше имён с ценой — волны нет
# Ног в пачке реплея. Число ИЗМЕРЕНО, а не назначено: при 300 выборка в
# 400 позиций дошла до 1.19 ГБ против предела 1200 МБ (`MEM_LIMIT_MB`) —
# на одну ногу приходится две линейки по 1440 меток ядра. Пачки не рвут
# символ, поэтому уменьшение пачки НЕ добавляет чтений баров: платится
# только постоянная цена лишних вызовов `run_short.replay`.
BATCH = 100
CTL_TRIES = 20                      # попыток подобрать свободного кандидата
SEED_BASE = 1000                    # начало потока зёрен — как в path_screen
# Колонки, о которых спорит заявка. Порядок — порядок показа.
COLS = (("usd", "$ всего"),
        ("usd_wo_top3d", "$ без 3 лучших дней"),
        ("usd_wo_top", "$ без лучшего имени"),
        ("max_dd_wo_worst", "просадка без худшего дня"),
        ("n", "сделок взято"),
        ("named_usd", f"$ за {WORST_DAY}"))
# Колонка, по которой судится убийца 1. Одна, названа здесь.
VERDICT_COL = "usd_wo_top3d"
# Сдвиг волны для НУЛЯ, суток. Объявлен до прогона и не подбирается.
NULL_SHIFT_D = 7
# Доля зёрен, при которой контроль убивает ячейку (объявлено заданием).
BEAT_MAX = 0.05


def _quiet(*_a):
    pass


def log_line(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


# --- касса: те же функции и тот же порядок, что у семейства ---------------

def book_form(cache, ctx, launch, dep=DEP, book=BOOK, now=None, log=_quiet):
    """Форма книги на этих записях — ТЕМИ ЖЕ функциями, что касса.

    Зачем не сама касса (`short_grid.cell_stats`): её ячейка не отдаёт
    колонок концентрации. Они считаются в `run_paper._stats` — одной
    формулой на весь проект, — но до ячейки не доезжают, а спор заявки
    идёт ровно о них. Дописать поля в `short_grid.py` нельзя: публикация
    постройки несёт только свой каталог (`publish_build`), и правка
    чужого файла осталась бы на сервере — прогон был, а в ветке пусто.

    Поэтому здесь ВЫЗОВ тех же функций в том же порядке, а равенство
    кассе на общих полях закреплено проверкой `форма_равна_кассе`:
    разойдись они, сюита падает, и вторая касса не заведётся молча.
    """
    packed = AG.packed_short(cache)
    recs, _ages = RP.age_shorts(packed.get(book) or [], book, launch=launch,
                                log=log, now=now)
    rows, cells, _one, _live = RP.build_rows({book: recs}, now=now,
                                             keys=[book], log=log)
    mine = [r for r in rows if R.ruler_of(r) == book
            and int(r.get("dep", 0)) == int(dep)]
    if ctx is not None and not ctx.get("error"):
        mine, _c = CO.apply_to_rows(mine, ctx)
    st = RP._stats(mine, dep)
    if st is None:
        return None
    c = cells.get(RP._cell(book, dep)) or {}
    fin, dd = st.get("final"), st.get("max_dd")
    daily_no = {}
    for r in mine:
        d = PL.day_no(float(r["exit_ts"]))
        daily_no[d] = daily_no.get(d, 0.0) + float(r["usd"])
    st = dict(st, taken=c.get("taken"), no_cash=c.get("no_cash"),
              offered=c.get("offered"),
              ratio=(None if not fin or not dd
                     else round(float(fin) / abs(float(dd)), 2)),
              daily_no={int(k): round(v, 4) for k, v in daily_no.items()})
    return st


def columns(st, named_day=WORST_DAY):
    """Колонки спора из формы книги. Чего нет — прочерк, а не ноль.

    Все величины берутся у `run_paper._stats`, то есть посчитаны там же,
    где деньги книги. Своего счёта здесь нет вовсе — только выбор полей
    и деньги названного дня из той же суточной разбивки.
    """
    if not st:
        return None
    days = {str(r["d"]): float(r.get("usd") or 0.0)
            for r in (st.get("days_rows") or [])}
    ns = {str(r["d"]): int(r.get("n") or 0)
          for r in (st.get("days_rows") or [])}
    out = {k: st.get(k) for k in ("usd", "final", "max_dd", "ratio", "n",
                                  "taken", "no_cash", "day_median", "win",
                                  "usd_wo_top", "usd_wo_top3d",
                                  "max_dd_wo_worst", "top_sym", "top_day",
                                  "worst_day", "days", "n_tail",
                                  # суточный ряд номерами суток нужен
                                  # правилу вылета пула и связи с живой
                                  # книгой: они судят ряд, а не итог
                                  "daily_no")}
    # Деньги названного дня: дня в своде нет — прочерк с причиной, а не
    # ноль. Ноль означал бы «книга в этот день торговала и вышла в нуль».
    out["named_day"] = named_day
    out["named_usd"] = days.get(named_day)
    out["named_n"] = ns.get(named_day)
    out["named_why"] = (None if named_day in days
                        else "дня нет в суточном своде книги")
    out["shape"] = ST.stats(days) or None
    return out


# --- ось волны по часам: потолок ------------------------------------------

def hours_of(changed):
    """{линейка: [часы]} правила — в том же порядке, что у path_screen."""
    hours = {}
    for key, k in changed.items():
        hours.setdefault(key[0], []).append(k)
    return hours


def draw(cache, cand, changed, seed, cut, tries=CTL_TRIES):
    """Случайные выходы ТОГО ЖЕ числа в ТЕ ЖЕ моменты среди открытых.

    Отбор, зёрна и «не дважды одну сделку» — как в
    `path_screen.control_exits`; равенство его розыгрышу закреплено
    проверкой `розыгрыш_как_у_оси` (иначе контроль мерил бы другой
    случай, чем ось, и сравнение было бы не с чем).

    `cand` — (линейка, момент) → список ключей, открытых в этот момент;
    `cut` — как закрыть запись в этот момент. Возвращает (кэш, сколько
    моментов остались без кандидата).
    """
    rnd = random.Random(SEED_BASE + int(seed))
    mod, used, no_cand = dict(cache), set(), 0
    for rk, ks in hours_of(changed).items():
        for k in ks:
            pool = cand(rk, k)
            pick = None
            for _try in range(tries):
                if not pool:
                    break
                c = rnd.choice(pool)
                if c not in used:
                    pick = c
                    break
            if pick is None:
                no_cand += 1
                continue
            used.add(pick)
            mod[pick] = cut(pick, k)
    return mod, no_cand


def control(cache, cand, changed, cut, ctx, launch, seeds=SEEDS, dep=DEP,
            now=None, log=_quiet, progress=None):
    """Колонки книги на случайных выходах: по зерну — своя строка."""
    out, no_cand, t0 = [], 0, time.time()
    for i in range(int(seeds)):
        mod, nc = draw(cache, cand, changed, i, cut)
        no_cand += nc
        out.append(columns(book_form(mod, ctx, launch, dep=dep, now=now,
                                     log=log)))
        if progress and i and i % 25 == 0:
            progress(f"    контроль: {i} зёрен из {seeds}, "
                     f"{time.time() - t0:.0f} с")
    return {"draws": out, "no_cand": no_cand,
            "secs": round(time.time() - t0, 1)}


def beat(draws, value, field):
    """Доля зёрен, где случайные выходы НЕ ХУЖЕ величины — одной мерой.

    Мера чужая (`agree_book.beat_share`) намеренно: доля зёрен считается
    в проекте одним местом, и вторая её копия однажды считала бы «не
    хуже» строгим неравенством.
    """
    return AG.beat_share([d for d in (draws or []) if d], value, field)


def _med(xs):
    xs = [float(x) for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def cells_axis(cache, views, ctx, launch, base, grid=GRID, seeds=SEEDS,
               dep=DEP, verdict=THRESH, now=None, log=_quiet, say=log_line):
    """Ячейки оси волны по часам: колонки правила и контроль по ним.

    Контроль на `seeds` зёрнах считается у ЯЧЕЙКИ ВЕРДИКТА — она
    объявлена заданием одна. Соседние пороги сетки печатаются
    диагностикой: у них колонки есть, контроля нет, и это сказано
    словами, а не пропуском.
    """
    idx = P.open_index(views)
    cells = []
    for y in grid:
        mod, changed = P.apply_axis(cache, views, "wave", y)
        for key in changed:
            mod[key] = dict(mod[key], exit=EXIT_LABEL)
        d = P.deltas(cache, views, changed)
        say(f"ось волны ≥ {y:g} %: изменено {d['n']} сделок "
            f"(хвостовых {d['tails']}), Σ долей маржи {d['sum']:+.2f}")
        cell = {"val": float(y), "delta": d, "cols": None, "control": None,
                "beat": {}, "verdict_cell": bool(abs(y - verdict) < 1e-9)}
        if not d["n"]:
            cell["why"] = "порог не пересечён ни разу: правило не меняет сделок"
            cells.append(cell)
            continue
        cell["cols"] = columns(book_form(mod, ctx, launch, dep=dep, now=now,
                                         log=log))
        if cell["verdict_cell"] and seeds:
            ctl = control(cache,
                          lambda rk, k: (idx.get(rk) or {}).get(k) or [],
                          changed, lambda key, k: P.exit_at(cache[key], k),
                          ctx, launch, seeds=seeds, dep=dep, now=now,
                          log=log, progress=say)
            cell["control"] = {"no_cand": ctl["no_cand"], "secs": ctl["secs"],
                               "n": len(ctl["draws"]),
                               "med": {f: _med([(x or {}).get(f)
                                                for x in ctl["draws"]])
                                       for f, _t in COLS}}
            for f, _t in COLS:
                sh, n = beat(ctl["draws"], (cell["cols"] or {}).get(f), f)
                cell["beat"][f] = {"share": sh, "n": n}
        cells.append(cell)
    return cells


def shifted_views(views, mkt, days=NULL_SHIFT_D):
    """Те же позиции, но волна взята на `days` суток в сторону — НУЛЬ.

    Честная форма нуля «сдвиг во времени»: путь позиции, её отметки,
    моменты и сроки остаются СВОИМИ, а рынок подставляется чужой.
    Прибавка, которая держится и на чужом рынке, есть свойство СРОКА
    (сделки просто короче), а не выравнивания с волной, — и тогда
    правилом ось не является.

    Нуль обязан быть ДРУГИМ рядом: сдвиг ноль дал бы ту же меру под
    другим именем, и проверка `нуль_сдвига_волны` держит именно это.
    """
    d = float(days) * 86400.0
    out = {}
    for key, v in views.items():
        if not v["path"]:
            out[key] = v
            continue
        t_in = float(v["rec"]["at"]) - 1.0
        w = {k: mkt.wave(t_in + d, t_in + d + k * HOUR)
             for k in range(1, v["path"]["K"] + 1)}
        out[key] = dict(v, wave=w)
    return out


# --- волна по МИНУТАМ: то, чего у оси по часам нет -----------------------

class MinuteWave:
    """Волна рынка на минутной сетке: средний ход прокси-имён записи.

    Определение волны НЕ своё: имена (`side_wave.PROXY`), правило «меньше
    `MIN_PROXY` цен — волны нет» и правило закрытия («последний бар не
    старше `CLOSE_TOL` до границы», `side_wave.closes_at`) взяты у S8.
    Своё здесь только сетка: минуты вместо часов.

    Бары читает тот же загрузчик, которым живёт реплей книг
    (`sweep.read_bars` по записи `run_d6.ROOT_B1`), сутками: полное окно
    одного имени — 57 тысяч баров, и держать двадцать таких разом
    незачем. В памяти остаётся только матрица закрытий (имена × минуты).
    """

    def __init__(self, t0, t1, read=None, proxies=PROXY, min_proxy=MIN_PROXY,
                 tol=SWV.CLOSE_TOL, chunk_h=24, log=_quiet):
        self.proxies = tuple(proxies)
        self.min_proxy = int(min_proxy)
        self.tol = float(tol)
        self.chunk = float(chunk_h) * HOUR
        self.log = log
        self.read = read or (lambda s, a, b: SW.read_bars(D6.ROOT_B1, s, a, b))
        self.t0 = float(int(float(t0) // MINUTE) * MINUTE)
        self.t1 = float(int(float(t1) // MINUTE) * MINUTE)
        self.n = int((self.t1 - self.t0) // MINUTE) + 1
        if self.n <= 0:
            raise ValueError("окно волны пусто")
        self.c = np.full((len(self.proxies), self.n), np.nan)
        self.have = 0
        self.thin = 0                 # минут, где имён с ценой меньше порога

    def j(self, ts):
        """Номер минуты в сетке; вне сетки — None, а не край."""
        k = int((float(ts) - self.t0) // MINUTE)
        return k if 0 <= k < self.n else None

    def build(self):
        # Прогресс — по имени: чтение ленты двадцати имён за сорок суток
        # идёт минутами, а прогон, молчащий десять минут, неотличим от
        # застрявшего.
        grid = self.t0 + MINUTE * np.arange(self.n)
        t_start = time.time()
        for i, sym in enumerate(self.proxies):
            got, h = 0, self.t0
            while h <= self.t1:
                end = min(h + self.chunk, self.t1 + MINUTE)
                bars = self.read(sym, h - self.tol, end)
                if bars:
                    a, b = self.j(h), self.j(min(end, self.t1))
                    if a is not None and b is not None and b >= a:
                        cl = SWV.closes_at(bars, list(grid[a:b + 1]))
                        self.c[i, a:b + 1] = cl
                        got += int(np.isfinite(cl).sum())
                h = end
            if got:
                self.have += 1
            else:
                self.log(f"  волна: {sym} без баров в окне")
            self.log(f"  волна: {i + 1}/{len(self.proxies)} имён, {sym} дал "
                     f"{got} минут, {time.time() - t_start:.0f} с")
        ok = np.isfinite(self.c).sum(axis=0)
        self.thin = int((ok < self.min_proxy).sum())
        self.log(f"волна: прокси с барами {self.have}/{len(self.proxies)}, "
                 f"минут {self.n}, из них без волны {self.thin}")
        return self

    def path(self, at, n):
        """Ход волны с входа по минутам 1…n. Минута без волны — NaN.

        База — закрытие ПЕРЕД входом (`at − 1`, та же секунда, от которой
        считает волну ось по часам в `path_screen.view_of`): сравнивать
        ход с ценой, которой на момент решения ещё не было, значило бы
        мерить заодно первую минуту сделки.
        """
        jb, j1 = self.j(float(at) - 1.0), self.j(float(at))
        if jb is None or j1 is None:
            return None
        n = int(min(n, self.n - j1))
        if n <= 0:
            return None
        # Порог «имён с ценой» проверяется ОДИН раз — по числу имён, у
        # которых есть и база, и цена этой минуты (`cnt` ниже). Отдельная
        # проверка базы была бы мёртвым кодом: минута с пятью ценами
        # требует пяти баз по построению, и подделать её было бы нечем.
        base = self.c[:, jb]
        seg = self.c[:, j1:j1 + n]
        with np.errstate(all="ignore"):
            rel = seg / base[:, None] - 1.0
        ok = np.isfinite(rel)
        cnt = ok.sum(axis=0)
        num = np.where(ok, rel, 0.0).sum(axis=0)
        with np.errstate(all="ignore"):
            w = np.where(cnt >= self.min_proxy, num / np.maximum(cnt, 1), np.nan)
        return w

    def cross(self, at, n, thresh):
        """Первая минута (1…n), где волна ≥ порога, иначе None.

        ПЕРВАЯ, а не лучшая и не последняя: правило обязано решаться
        данными, которые к этой минуте уже были. Проверка на
        заглядывание в будущее (`будущее_не_меняет_прошлого`) держит
        именно это.
        """
        w = self.path(at, n)
        if w is None:
            return None, None
        hit = np.isfinite(w) & (w >= float(thresh) / 100.0)
        if not hit.any():
            return None, (float(np.nanmax(w)) if np.isfinite(w).any() else None)
        m = int(np.argmax(hit)) + 1
        return m, float(w[m - 1])


def cut_at(rec, ts, pnl, why=EXIT_LABEL):
    """Запись, закрытая в момент `ts` с исходом `pnl` (доля маржи).

    Отметки режутся так же, как их режет `path_screen.exit_at` на границе
    часа: часы ДО часа выхода остаются своими приращениями, час выхода
    получает остаток до `pnl`. Равенство обеим дорогам на границе часа
    закреплено проверкой `минутный_срез_равен_часовому` — иначе реплей
    внутри часа считал бы деньги не той же меркой, что потолок.
    """
    at = float(rec["at"])
    ts = float(ts)
    k = int((ts - at) // HOUR) + 1
    keep, cum = [], 0.0
    for m in rec.get("marks") or []:
        ki = int(round((float(m[0]) - at) / HOUR)) + 1
        if ki < k:
            keep.append(m)
            cum += float(m[1])
    keep.append([at + (k - 1) * HOUR, float(pnl) - cum])
    new = dict(rec, pnl=float(pnl), exit_ts=ts, exit=why, marks=keep,
               state="closed")
    lev, e = float(rec.get("lev") or 0), rec.get("entry_px")
    if e and lev:
        new["exit_px"] = float(e) * (1.0 - float(pnl) / lev)      # шорт
    if rec.get("pnl_net") is not None and rec.get("pnl") is not None:
        new["pnl_net"] = float(pnl) - (float(rec["pnl"]) - float(rec["pnl_net"]))
    return new


# --- реплей ядра внутри часа --------------------------------------------

def ckpt_offsets(n=HOLD_MIN):
    """Метки ядра: середина каждой минуты удержания, в часах от входа.

    Середина, а не граница: метка `simulate_dca` отдаёт последний бар с
    `t ≤ метка`, а `k/60 · 3600` в двоичной дроби бывает на 10⁻¹⁴ меньше
    целой секунды — и метка брала бы ПРЕДЫДУЩУЮ минуту. Полминуты — та
    же минута при любой такой ошибке.
    """
    return tuple((m - 0.5) / 60.0 for m in range(1, int(n) + 1))


def minute_path(rec, n=HOLD_MIN):
    """Исходы ядра по минутам из `ckpt`: (pnl, время бара) или NaN.

    NaN значит «этой минутой сделка уже закрыта либо бара ещё не было» —
    пустота названа, а не подменена нулём.

    Отдельно про ПОСЛЕДНИЕ минуты позиции: метку ядро закрывает СЛЕДУЮЩИМ
    баром (`while cps[ck_i] < bt`), поэтому у минуты самого последнего
    бара метки нет. Для охраны это в нашу сторону строгости — такая
    позиция остаётся нетронутой, — и считается числом (`no_mark`), а не
    подменяется отметкой часа.
    """
    ck = rec.get("ckpt") or []
    pnl = np.full(int(n), np.nan)
    ts = np.full(int(n), np.nan)
    for i, c in enumerate(ck[:int(n)]):
        if c is None:
            continue
        ts[i] = float(c[1])
        pnl[i] = float(c[2])
    return pnl, ts


def by_symbol(legs, size=BATCH):
    """Пачки ног, не рвущие символ: бары имени читаются один раз на пачку.

    Рвать символ между пачками значило бы читать его сорокадневное окно
    дважды — реплей и так самая дорогая часть прогона.
    """
    by = {}
    for g in legs:
        by.setdefault(g["sym"], []).append(g)
    out, cur = [], []
    for sym in sorted(by):
        if cur and len(cur) + len(by[sym]) > int(size):
            out.append(cur)
            cur = []
        cur += by[sym]
    if cur:
        out.append(cur)
    return out


def replay_paths(legs, keys=None, size=BATCH, n=HOLD_MIN, log=_quiet,
                 say=log_line, replay=None):
    """Минутные пути позиций: ядро с метками на каждой минуте удержания.

    Возвращает ({(линейка, имя, момент): (pnl[], ts[])}, диагностика).
    Второго счёта здесь нет: числа отдаёт `simulate_dca` через
    `run_short.replay`, а эта функция только раскладывает их по минутам.
    """
    replay = replay or S.replay
    want = set(keys) if keys is not None else None
    need = [g for g in legs
            if want is None or (g["sym"], round(float(g["at"]), 3)) in want]
    offs = ckpt_offsets(n)
    paths, diag = {}, {"legs": len(need), "records": 0, "no_ckpt": 0,
                       "batches": 0, "misaligned": 0}
    packs = by_symbol(need, size=size)
    t0 = time.time()
    for i, pack in enumerate(packs, 1):
        fresh, _tail = replay(pack, log=log, ckpt_hours=offs)
        diag["batches"] += 1
        for key, r in fresh.items():
            if key[0] != RULER:
                continue
            if abs(float(r["at"]) % HOUR) > 1e-6:
                diag["misaligned"] += 1
                continue
            if not r.get("ckpt"):
                diag["no_ckpt"] += 1
                continue
            diag["records"] += 1
            paths[key] = minute_path(r, n=n)
        say(f"  реплей: пачка {i}/{len(packs)}, записей {diag['records']}, "
            f"{time.time() - t0:.0f} с")
    diag["secs"] = round(time.time() - t0, 1)
    return paths, diag


def guard_minutes(cache, wave, paths, thresh=THRESH, lag=LAG_MIN, n=HOLD_MIN):
    """Минута выхода по охране у каждой позиции и почему её нет.

    Охрана срабатывает СТРОГО до фактического выхода: позиция, закрытая
    раньше пересечения, правилом не тронута — считается числом, а не
    записывается в «изменённые».
    """
    # «Волны нет» и «волна есть, порог не пересечён» — РАЗНЫЕ причины, и
    # лечатся они разным: первая есть пробел записи, вторая — ответ
    # правила. Смешать их значило бы назвать пропуск результатом.
    got, why = {}, {"no_path": 0, "no_wave": 0, "no_cross": 0,
                    "closed_before": 0, "no_mark": 0, "late": 0}
    for key, r in sorted(cache.items()):
        if key[0] != RULER or r.get("state", "closed") != "closed":
            continue
        pl = paths.get(key)
        if pl is None:
            why["no_path"] += 1
            continue
        at, out_ts = float(r["at"]), float(r["exit_ts"])
        lim = int(min(n, max(0, (out_ts - at) // MINUTE)))
        if lim <= 0:
            why["closed_before"] += 1
            continue
        m, top = wave.cross(at, lim, thresh)
        if m is None:
            why["no_cross" if top is not None else "no_wave"] += 1
            continue
        i = m - 1 + int(lag)
        if i >= n:
            why["late"] += 1
            continue
        pnl, ts = pl
        if not np.isfinite(pnl[i]) or not np.isfinite(ts[i]):
            why["no_mark"] += 1
            continue
        if float(ts[i]) >= out_ts:
            why["closed_before"] += 1
            continue
        got[key] = (m, i, float(pnl[i]), float(ts[i]))
    return got, why


def open_minutes(cache, paths, n=HOLD_MIN):
    """(линейка, минута) → ключи позиций, ОТКРЫТЫХ в эту минуту.

    Открыта значит: у минуты есть отметка ядра и фактический выход позже.
    Тот же смысл, что у `path_screen.open_index` по часам.
    """
    idx = {}
    for key, r in cache.items():
        pl = paths.get(key)
        if pl is None or r.get("state", "closed") != "closed":
            continue
        pnl, ts = pl
        out_ts = float(r["exit_ts"])
        ok = np.isfinite(pnl) & np.isfinite(ts) & (ts < out_ts)
        for i in np.nonzero(ok)[0]:
            idx.setdefault(key[0], {}).setdefault(int(i), []).append(key)
    return idx


def sister_cache(cache, got):
    """Кэш сестры: те же записи, у изменённых — выход по охране."""
    mod = dict(cache)
    for key, (_m, _i, pnl, ts) in got.items():
        mod[key] = cut_at(cache[key], ts, pnl)
    return mod


def replay_cell(cache, wave, paths, ctx, launch, thresh=THRESH, lag=LAG_MIN,
                seeds=SEEDS, dep=DEP, now=None, log=_quiet, say=log_line):
    """Сестра на минутных выходах и её контроль — те же колонки."""
    got, why = guard_minutes(cache, wave, paths, thresh=thresh, lag=lag)
    mod = sister_cache(cache, got)
    out = {"lag": int(lag), "n": len(got), "why": why,
           "sum": round(sum(v[2] - float(cache[k]["pnl"])
                            for k, v in got.items()), 4),
           "cols": None, "control": None, "beat": {}}
    if not got:
        out["empty"] = ("охрана не сработала ни на одной позиции: "
                        "пересечения порога внутри срока нет")
        return out
    out["cols"] = columns(book_form(mod, ctx, launch, dep=dep, now=now,
                                    log=log))
    if seeds:
        idx = open_minutes(cache, paths)
        changed = {k: v[1] for k, v in got.items()}

        def cut(key, i):
            pnl, ts = paths[key]
            return cut_at(cache[key], float(ts[i]), float(pnl[i]),
                          why="случайный выход")

        ctl = control(cache, lambda rk, i: (idx.get(rk) or {}).get(i) or [],
                      changed, cut, ctx, launch, seeds=seeds, dep=dep,
                      now=now, log=log, progress=say)
        out["control"] = {"no_cand": ctl["no_cand"], "secs": ctl["secs"],
                          "n": len(ctl["draws"]),
                          "med": {f: _med([(x or {}).get(f)
                                           for x in ctl["draws"]])
                                  for f, _t in COLS}}
        for f, _t in COLS:
            sh, n_ = beat(ctl["draws"], (out["cols"] or {}).get(f), f)
            out["beat"][f] = {"share": sh, "n": n_}
    return out


# --- вердикт: фраза выводится из числа -----------------------------------

def killer_one(base, cell, col=VERDICT_COL, beat_max=BEAT_MAX):
    """Убийца 1: потолок на записи по объявленной колонке.

    Мёртво, если колонка сестры не выше той же колонки базы, либо
    случайные выходы не хуже сестры по ЭТОЙ колонке в ≥ `beat_max` зёрен.
    Фраза собирается из чисел — рядом с числом её положить нельзя, она
    стареет молча.
    """
    b = (base or {}).get(col)
    c = ((cell or {}).get("cols") or {}).get(col)
    sh = ((cell or {}).get("beat") or {}).get(col, {}).get("share")
    if cell and cell.get("why"):
        return False, cell["why"], {"base": b, "sister": c, "beat": sh}
    if b is None or c is None:
        return None, ("не измерено: колонка "
                      f"«{dict(COLS)[col]}» есть не у обеих книг "
                      f"(база {b}, сестра {c})"), {"base": b, "sister": c,
                                                   "beat": sh}
    if float(c) <= float(b):
        return False, (f"колонка «{dict(COLS)[col]}» у сестры {c:+.2f} $ "
                       f"не выше базы {b:+.2f} $ — прибавка пришла теми же "
                       "днями"), {"base": b, "sister": c, "beat": sh}
    if sh is None:
        return None, ("не измерено: контроль по колонке не посчитан "
                      "(зёрен нет)"), {"base": b, "sister": c, "beat": sh}
    if float(sh) >= beat_max:
        return False, (f"случайные выходы не хуже сестры по колонке в "
                       f"{100 * float(sh):.0f} % зёрен при пределе "
                       f"{100 * beat_max:.0f} %"), {"base": b, "sister": c,
                                                    "beat": sh}
    return True, (f"колонка «{dict(COLS)[col]}» {b:+.2f} → {c:+.2f} $, "
                  f"случайные не хуже в {100 * float(sh):.0f} % зёрен "
                  f"(предел {100 * beat_max:.0f} %)"), {"base": b,
                                                        "sister": c,
                                                        "beat": sh}


def killer_two(base, cell, beat_max=BEAT_MAX):
    """Убийца 2: реплей внутри часа против базы на тех же сутках."""
    if not cell:
        return None, "не измерено: реплей не запускался", {}
    if cell.get("empty"):
        return False, cell["empty"], {}
    c = cell.get("cols") or {}
    bf, cf = (base or {}).get("final"), c.get("final")
    br, cr = (base or {}).get("ratio"), c.get("ratio")
    sh = (cell.get("beat") or {}).get("usd", {}).get("share")
    got = {"base_final": bf, "final": cf, "base_ratio": br, "ratio": cr,
           "beat": sh}
    if cf is None or bf is None:
        return None, "не измерено: итог посчитан не у обеих книг", got
    if float(cf) <= float(bf):
        return False, (f"итог сестры {100 * cf:+.1f} % не выше базы "
                       f"{100 * bf:+.1f} % на тех же сутках"), got
    if br is not None and cr is not None and float(cr) <= float(br):
        return False, (f"доход на просадку сестры {cr:.2f} не выше базового "
                       f"{br:.2f}"), got
    if sh is None:
        return None, "не измерено: контроль реплея не посчитан", got
    if float(sh) >= beat_max:
        return False, (f"случайные выходы, реплеенные тем же ядром, не хуже "
                       f"в {100 * float(sh):.0f} % зёрен"), got
    return True, (f"итог {100 * bf:+.1f} → {100 * cf:+.1f} %, доход на "
                  f"просадку {br} → {cr}, случайные не хуже в "
                  f"{100 * float(sh):.0f} % зёрен"), got


def forward_why(st, declared_at=None):
    """Правило вылета пула на ряду книги — с пометкой, чем судится.

    ВНИМАНИЕ на ловушку: `pool.shape_why(ряд, None)` считает форвардом
    ВЕСЬ ряд (день объявления берётся нулём), и вердикт выглядел бы
    форвардным, будучи пересчётом по прошлому, которое модель видела.
    Поэтому здесь печатается число форвардных суток — ноль, пока сестра
    не объявлена, — и оно стоит ПЕРЕД причиной. `declared_at` оставлен
    входом для дороги вперёд: с ним те же функции посчитают настоящий
    форвард, не меняя этой.
    """
    daily = {int(k): float(v) for k, v in (st or {}).get("daily_no",
                                                          {}).items()}
    if not daily:
        return {"why": "суточного ряда нет", "days": 0, "forward_days": 0}
    s = ST.stats(daily) or {}
    fwd, _pre = PL.split_forward(daily, declared_at)
    return {"days": s.get("days"), "med": s.get("med"), "bite": s.get("bite"),
            "green": s.get("green"), "thin": s.get("thin"),
            "shape_why": PL.shape_why(daily, declared_at),
            "declared_at": declared_at,
            "forward_days": (len(fwd) if declared_at else 0),
            "note": ("судится ПЕРЕСЧЁТ: форвардных суток у необъявленной "
                     "сестры нет, вердиктом это не является"
                     if not declared_at else
                     "судится форвард со дня объявления")}


def live_link(st, book=BOOK, dep=DEP):
    """Связь дневных денег сестры с живой книгой того же семейства.

    Число даёт `ceiling.pair_corr` — тем же кодом, которым фабрика
    считает эффективное N. Прочерк значит «общих суток мало», а не
    «книги независимы».
    """
    a = {int(k): float(v) for k, v in (st or {}).get("daily_no", {}).items()}
    if not a:
        return {"why": "суточного ряда сестры нет"}
    try:
        with open(R.artifact_of(book), encoding="utf-8") as f:
            art = json.load(f)
    except (OSError, ValueError) as e:                        # noqa: BLE001
        return {"why": f"свод живой книги не прочитан: {str(e)[:80]}"}
    cell = ((art.get("books") or {}).get(f"{book}:{int(dep)}") or {})
    rows = (cell.get("all") or {}).get("days_rows") or []
    # Дата свода — строка UTC, а номер суток у сестры считан из секунд
    # UTC: перевод идёт `timegm`, а не `mktime`. `mktime` читает дату как
    # МЕСТНОЕ время, и на машине не в UTC оба ряда разъехались бы на
    # сутки — связь считалась бы по сдвинутым парам, молча.
    b = {}
    for r in rows:
        try:
            ts = calendar.timegm(time.strptime(str(r["d"]), "%Y-%m-%d"))
            b[PL.day_no(float(ts))] = float(r.get("usd") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
    if not b:
        return {"why": "суточного ряда живой книги в своде нет"}
    rho, days = CE.pair_corr(a, b)
    return {"rho": rho, "days": days, "book": book}


# --- прогон --------------------------------------------------------------

def window_of(ats):
    """Окно записи, нужное волне: час до первого входа и срок после последнего.

    Считается по ТЕМ входам, которые в реплей попали: окно всего кэша при
    выборке в сотню позиций читало бы сорок суток баров двадцати имён
    впустую.
    """
    ats = [float(x) for x in ats]
    if not ats:
        return None
    return min(ats) - HOUR, max(ats) + R.H24_HOLD_H * HOUR


def run(seeds=SEEDS, limit=None, do_replay=False, sample=None, force=False,
        now=None, launch=None, ctx=None, log=log_line, mem_limit=None,
        summary_dir=None, wave=None, thresh=THRESH, lag=LAG_MIN,
        cache=None, legs_=None):
    t0 = time.time()
    say = AB.guarded(log, limit=(G.MEM_LIMIT_MB if mem_limit is None
                                 else mem_limit))
    if cache is None:
        cache, why = S.read_cache(log=say)
        if why:
            say(f"механика не считается: {why}")
            return {"error": f"кэш реплея непригоден: {why}", "mech": MECH}
    closed = {key: r for key, r in cache.items()
              if key[0] == RULER and r.get("state", "closed") == "closed"}
    if limit:
        keep = sorted(closed, key=lambda k: k[2])[:int(limit)]
        closed = {k: closed[k] for k in keep}
        cache = {k: v for k, v in cache.items() if k[0] != RULER or k in closed}
    if not closed:
        return {"error": f"закрытых позиций линейки {RULER} нет: считать "
                         "нечего, и пустота не выдаёт себя за результат",
                "mech": MECH}
    ctx = ctx if ctx is not None else CO.context()
    launch = IR.launches() if launch is None else launch
    hours = T.Hours(root=summary_dir or T.SUMMARY_DIR)
    mkt = P.Market(hours)
    views = {key: P.view_of(r, mkt) for key, r in closed.items()}
    no_marks = sum(1 for v in views.values() if v["path"] is None)
    mismatch = sum(1 for k, v in views.items()
                   if v["path"] is not None
                   and abs(v["path"]["final"] - float(closed[k]["pnl"])) > 1e-6)
    say(f"позиций {len(views)}, без отметок ядра {no_marks}, отметка ≠ исходу "
        f"{mismatch}; волна по часам не собралась {mkt.wave_none} раз; "
        f"сводок есть/нет {hours.hit}/{hours.miss}; {time.time() - t0:.0f} с")
    if no_marks >= len(views):
        return {"error": "ни у одной позиции нет отметок ядра: ось волны "
                         "считать нечем", "mech": MECH}
    base = book_form(cache, ctx, launch, now=now, log=_quiet)
    base_cols = columns(base) or {}
    say(f"база {BOOK} ${int(DEP)}: итог {_pp(base_cols.get('final'))}, "
        f"$ {_u(base_cols.get('usd'))}, без 3 лучших дней "
        f"{_u(base_cols.get('usd_wo_top3d'))}, сделок "
        f"{_n(base_cols.get('n'))}")
    cells = cells_axis(cache, views, ctx, launch, base_cols, seeds=seeds,
                       verdict=thresh, now=now, log=_quiet, say=say)
    verdict = next((c for c in cells if c.get("verdict_cell")), None)
    k1, k1_why, k1_num = killer_one(base_cols, verdict)
    say(f"убийца 1 ({'прошёл' if k1 else 'НЕ прошёл' if k1 is False else 'не измерен'}): {k1_why}")
    # НУЛЬ: та же ось на волне, сдвинутой на неделю. Считается ВСЕГДА, а
    # не только когда убийца пройден: нуль, который смотрят лишь на
    # удачном прогоне, есть подтверждение, а не проверка.
    # Счётчик несобравшейся волны снимается ДО нуля: нуль спрашивает
    # рынок в чужом окне и добавил бы своих промахов в число позиций.
    wave_none_h = mkt.wave_none
    nviews = shifted_views(views, mkt)
    null = cells_axis(cache, nviews, ctx, launch, base_cols, grid=(thresh,),
                      seeds=seeds, verdict=thresh, now=now, log=_quiet,
                      say=say)
    null = (null or [None])[0]
    if null:
        null["shift_d"] = NULL_SHIFT_D
        null["changed_same"] = sum(
            1 for key, v in nviews.items()
            if P.trigger(v, "wave", thresh) == P.trigger(views[key], "wave",
                                                         thresh))
        null["positions"] = len(views)
        null["wave_none"] = mkt.wave_none - wave_none_h
    say("нуль сдвига волны на "
        f"{NULL_SHIFT_D} сут: колонка спора "
        f"{_u(((null or {}).get('cols') or {}).get(VERDICT_COL))} против "
        f"{_u(((verdict or {}).get('cols') or {}).get(VERDICT_COL))} у сестры")
    rep, wmeta = None, None
    if do_replay and (k1 or force):
        keys = sorted({(k[1], k[2]) for k in closed}, key=lambda x: (x[1], x[0]))
        if sample:
            step = max(1, len(keys) // int(sample))
            keys = keys[::step][:int(sample)]
        if wave is None:
            win = window_of(a for _s, a in keys)
            wave = MinuteWave(win[0], win[1], log=say).build()
        wmeta = {"proxies": len(wave.proxies), "have": wave.have,
                 "minutes": wave.n, "thin": wave.thin,
                 "min_proxy": wave.min_proxy}
        legs_ = S.legs(log=say) if legs_ is None else legs_
        paths, diag = replay_paths(legs_, keys=set(keys), log=_quiet, say=say)
        if not paths:
            rep = {"error": "реплей не дал ни одного минутного пути: "
                            "метки ядра пусты"}
        else:
            sub = {k: v for k, v in cache.items()
                   if k[0] != RULER or (k[1], k[2]) in set(keys)}
            rep = replay_cell(sub, wave, paths, ctx, launch, thresh=thresh,
                              lag=lag, seeds=seeds, now=now, log=_quiet,
                              say=say)
            rep["diag"] = diag
            rep["sample"] = len(keys)
            rep["of"] = len(closed)
            rep["base"] = columns(book_form(sub, ctx, launch, now=now,
                                            log=_quiet))
            rep["zero_lag"] = replay_cell(sub, wave, paths, ctx, launch,
                                          thresh=thresh, lag=0, seeds=0,
                                          now=now, log=_quiet, say=say)
    elif do_replay:
        rep = {"skipped": "шаг 2 не считается: убийца 1 не пройден "
                          "(порядок шагов объявлен заданием; --force снимает)"}
    k2, k2_why, k2_num = killer_two((rep or {}).get("base") or base_cols,
                                    rep if rep and not rep.get("skipped")
                                    and not rep.get("error") else None)
    sis = (rep or {}).get("cols") or (verdict or {}).get("cols")
    return {"mech": MECH, "book": BOOK, "ruler": RULER, "dep": DEP,
            "grid": [float(x) for x in GRID], "thresh": float(thresh),
            "seeds": int(seeds), "lag_min": int(lag),
            "base": base_cols, "cells": cells, "null": null,
            "replay": rep, "wave": wmeta,
            "killers": {"1": {"pass": k1, "why": k1_why, "nums": k1_num},
                        "2": {"pass": k2, "why": k2_why, "nums": k2_num}},
            "forward": forward_why(base) if sis is None else None,
            "forward_sister": (None if sis is None else forward_why(
                {"daily_no": (sis or {}).get("daily_no", {})})),
            "live_link": live_link(sis and {"daily_no": sis.get("daily_no",
                                                                {})}),
            "diag": {"n": len(views), "no_marks": no_marks,
                     "mismatch": mismatch, "wave_none_h": wave_none_h,
                     "hours": {"есть": hours.hit, "нет": hours.miss},
                     "forced": bool(force)},
            "costs_error": (ctx or {}).get("error"),
            "computed_at": G.stamp(), "secs": round(time.time() - t0, 1)}


# --- показ ---------------------------------------------------------------

def _u(x):
    return "—" if x is None else f"{float(x):+,.2f} $"


def _pp(x, d=1):
    return "—" if x is None else f"{100.0 * float(x):+.{d}f} %"


def _p(x, d=0):
    return "—" if x is None else f"{100.0 * float(x):.{d}f} %"


def _n(x):
    return "—" if x is None else f"{int(x)}"


def _col(f, v):
    if v is None:
        return "—"
    if f == "max_dd_wo_worst":
        return _pp(v)
    if f == "n":
        return _n(v)
    return _u(v)


def _cols_table(rows):
    """Колонки спора: строка на книгу. Прочерк значит «не измерено»."""
    L = ["| книга | " + " | ".join(t for _f, t in COLS) + " |",
         "|---|" + "--:|" * len(COLS)]
    for name, c in rows:
        if not c:
            L.append(f"| {name} | " + " | ".join("—" for _ in COLS) + " |")
            continue
        L.append(f"| {name} | "
                 + " | ".join(_col(f, c.get(f)) for f, _t in COLS) + " |")
    return L


def _control_table(cell):
    ctl = (cell or {}).get("control")
    if not ctl:
        return ["Контроля у этой ячейки нет: она не ячейка вердикта "
                "(зёрна тратятся на объявленную одну).", ""]
    L = [f"Случайные выходы того же числа в те же моменты, {ctl['n']} зёрен "
         f"({ctl['secs']} с; моментов без кандидата {ctl['no_cand']}).", "",
         "| колонка | сестра | случайные (медиана) | зёрен, где случайные "
         "не хуже |", "|---|--:|--:|--:|"]
    for f, t in COLS:
        b = (cell.get("beat") or {}).get(f) or {}
        L.append(f"| {t} | {_col(f, (cell.get('cols') or {}).get(f))} | "
                 f"{_col(f, (ctl.get('med') or {}).get(f))} | "
                 + ("—" if b.get("share") is None
                    else f"{100 * b['share']:.0f} % из {b.get('n')}") + " |")
    return L + [""]


def report(s):
    L = ["# Охрана рынком как правило выхода короткой книги: сестра "
         f"`{s.get('book')}` (механика {s.get('mech')})", "",
         "Заявка предлагающего 2026-09-13: закрыть шорт в первую минуту, "
         "когда волна рынка выросла на объявленный порог от момента входа. "
         "Порог не назначен здесь: сетка взята у `path_screen.AXES`, ячейка "
         "вердикта — СЕРЕДИНА сетки (`wave_guard.middle`), соседние пороги "
         "печатаются диагностикой. Деньги — касса семейства, нетто; "
         "концентрация считается теми же полями, что у страницы книг "
         "(`run_paper._stats`).", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не посчитано:** {s['error']}.", ""])
    dg = s.get("diag") or {}
    L += [f"Позиций линейки `{s.get('ruler')}` {dg.get('n')}, без отметок ядра "
          f"{dg.get('no_marks')}, последняя отметка ≠ исходу у "
          f"{dg.get('mismatch')} (обязано быть 0); волна по часам не "
          f"собралась {dg.get('wave_none_h')} раз; сводок стакана есть/нет "
          f"{(dg.get('hours') or {}).get('есть')}/"
          f"{(dg.get('hours') or {}).get('нет')}. Порог вердикта "
          f"{s.get('thresh'):g} % из сетки "
          + " / ".join(f"{x:g}" for x in s.get("grid") or []) + " %.", ""]
    if s.get("costs_error"):
        L += [f"**Издержки:** {s['costs_error']} — деньги ниже без этой "
              "части.", ""]
    kk = s.get("killers") or {}
    L += ["## Вердикт по объявленным убийцам", "",
          "| убийца | итог | чем сказано |", "|---|---|---|"]
    for k, ttl in (("1", "потолок на записи, колонка «без 3 лучших дней»"),
                   ("2", "реплей ядра внутри часа")):
        got = kk.get(k) or {}
        mark = ("прошёл" if got.get("pass") is True else
                "**МЁРТВО**" if got.get("pass") is False else "не измерен")
        L.append(f"| {k}. {ttl} | {mark} | {got.get('why')} |")
    L += ["", "Убийцы 3 и 4 — форвардные, и здесь их нет по построению: "
          "форвардных суток у необъявленной сестры ноль. Правило вылета "
          "пула ниже применено к ПЕРЕСЧЁТУ и вердиктом не является.", ""]
    L += ["## Шаг 1. Потолок: ось волны по отметкам часа", "",
          "Выход на границе часа есть усечение симуляции в эту секунду "
          "(проверено `wave_guard`, 0 расхождений). Колонки — те, о которых "
          "спорит заявка; «сделок взято» стоит рядом с деньгами не для "
          "красоты: касса берёт больше позиций на освобождённые деньги, и "
          "без этого числа прибавка неотличима от оборота капитала.", ""]
    rows = [(f"база `{s.get('book')}`", s.get("base"))]
    for c in s.get("cells") or []:
        ttl = (f"охрана {c['val']:g} %"
               + (" — **ячейка вердикта**" if c.get("verdict_cell") else ""))
        rows.append((ttl, c.get("cols")))
    L += _cols_table(rows) + [""]
    for c in s.get("cells") or []:
        d = c.get("delta") or {}
        L.append(f"- охрана {c['val']:g} %: изменено {d.get('n', 0)} сделок "
                 f"(хвостовых {d.get('tails', 0)}, срезано в минус "
                 f"{d.get('cut_worse', 0)}), Σ долей маржи "
                 + ("—" if d.get("sum") is None else f"{d['sum']:+.2f}")
                 + (f"; {c['why']}" if c.get("why") else ""))
    L += [""]
    vc = next((c for c in (s.get("cells") or []) if c.get("verdict_cell")),
              None)
    L += ["### Контроль ячейки вердикта по тем же колонкам", ""]
    L += _control_table(vc)
    L += ["### Нуль: волна, сдвинутая во времени", ""]
    nl = s.get("null")
    if not nl:
        L += ["Нуль не посчитан.", ""]
    else:
        nc = (nl.get("cols") or {}).get(VERDICT_COL)
        sc = ((vc or {}).get("cols") or {}).get(VERDICT_COL)
        ttl = dict(COLS)[VERDICT_COL]
        L += [f"Та же ось на волне, взятой на {nl.get('shift_d')} суток в "
              "сторону: путь позиции, её моменты и срок СВОИ, рынок чужой. "
              "Прибавка, которая держится и на чужом рынке, есть свойство "
              "срока (сделки просто короче), а не выравнивания с волной.", "",
              f"Изменённых сделок {nl.get('delta', {}).get('n')} (у сестры "
              f"{(vc or {}).get('delta', {}).get('n')}); час выхода совпал с "
              f"настоящим у {nl.get('changed_same')} позиций из "
              f"{nl.get('positions')} — нуль обязан быть ДРУГИМ рядом, и это "
              "число тому мера. Волна в сдвинутом окне не собралась "
              f"{nl.get('wave_none')} раз (у позиций — "
              f"{(s.get('diag') or {}).get('wave_none_h')}).", ""]
        L += _cols_table([(f"нуль: сдвиг {nl.get('shift_d')} сут",
                           nl.get("cols"))]) + [""]
        if nc is not None and sc is not None:
            L += [("**Нуль молчит**: колонка «{0}» на сдвинутой волне "
                   "{1} против {2} у сестры."
                   if float(nc) < float(sc) else
                   "**Нуль ГОВОРИТ ТО ЖЕ**: колонка «{0}» на сдвинутой волне "
                   "{1} против {2} у сестры — прибавку делает срок, а не "
                   "волна.").format(ttl, _u(nc), _u(sc)), ""]
        else:
            L += ["Сравнить нуль с сестрой нечем: колонка есть не у обоих.",
                  ""]
    rep = s.get("replay")
    L += ["## Шаг 2. Реплей ядра внутри часа", ""]
    if not rep:
        L += ["Не запускался (`--replay` выключен).", ""]
    elif rep.get("skipped"):
        L += [f"{rep['skipped']}.", ""]
    elif rep.get("error"):
        L += [f"**Не посчитано:** {rep['error']}.", ""]
    else:
        w = s.get("wave") or {}
        dgr = rep.get("diag") or {}
        why = rep.get("why") or {}
        L += [f"Волна по минутам: прокси с барами {w.get('have')}/"
              f"{w.get('proxies')}, минут сетки {w.get('minutes')}, из них "
              f"без волны (имён с ценой меньше {w.get('min_proxy')}) "
              f"{w.get('thin')}. Позиций в выборке {rep.get('sample')}, "
              f"минутных путей {dgr.get('records')} (пачек "
              f"{dgr.get('batches')}, без меток {dgr.get('no_ckpt')}, вход не "
              f"на границе часа {dgr.get('misaligned')}, {dgr.get('secs')} с).",
              "",
              f"Охрана сработала у {rep.get('n')} позиций; не сработала: "
              f"пути нет {why.get('no_path')}, волны нет вовсе "
              f"{why.get('no_wave')}, волна есть и порог не пересечён "
              f"{why.get('no_cross')}, закрылась раньше "
              f"{why.get('closed_before')}, отметки минуты нет "
              f"{why.get('no_mark')}, пересечение позже срока "
              f"{why.get('late')}. Σ приращений долей маржи "
              + ("—" if rep.get("sum") is None else f"{rep['sum']:+.2f}")
              + f"; задержка исполнения {rep.get('lag')} мин.", ""]
        zl = rep.get("zero_lag") or {}
        rows = [("база на тех же позициях", rep.get("base")),
                (f"сестра, задержка {rep.get('lag')} мин", rep.get("cols")),
                ("сестра без задержки (потолок)", zl.get("cols"))]
        L += _cols_table(rows) + [""]
        L += ["Строка «без задержки» — верхняя оценка: узнать о пересечении "
              "и выйти в ту же минуту нельзя. Разница двух строк и есть цена "
              "минуты, и она напечатана, а не подразумевается нулём.", ""]
        if rep.get("of") and rep.get("sample") and rep["sample"] < rep["of"]:
            L += [f"**Это ВЫБОРКА: {rep['sample']} позиций из "
                  f"{rep['of']}**, ровно по времени. База в таблице "
                  "посчитана на тех же позициях, поэтому сравнение честное, "
                  "но колонки концентрации на выборке шумят, и вердикт "
                  "убийцы 2 по ней предварителен — полный реплей стоит "
                  "часов и запускается отдельным заданием.", ""]
        L += ["### Контроль реплея", ""] + _control_table(rep)
    fs = s.get("forward_sister") or s.get("forward") or {}
    L += ["## Правило вылета пула — по пересчёту, не вердикт", ""]
    if fs.get("why"):
        L += [f"Не посчитано: {fs['why']}.", ""]
    else:
        L += [f"**Форвардных суток {fs.get('forward_days')}** — "
              f"{fs.get('note', '')}. Суток в ряду {fs.get('days')}, медиана "
              "дня "
              + ("—" if fs.get("med") is None else f"{fs['med']:+.2f} $")
              + f", зелёных {fs.get('green')}, укус {fs.get('bite')}; "
              + ("правило вылета не отставило бы книгу"
                 if not fs.get("shape_why")
                 else f"правило вылета сказало бы: {fs['shape_why']}")
              + ".", ""]
    ll = s.get("live_link") or {}
    L += ["## Связь с живой книгой того же семейства", ""]
    if ll.get("why"):
        L += [f"Не измерено: {ll['why']}.", ""]
    else:
        L += [f"Связь дневных денег сестры с живой `{ll.get('book')}` "
              + ("—" if ll.get("rho") is None
                 else f"{float(ll['rho']):+.2f}")
              + f" по {ll.get('days')} общим суткам (`ceiling.pair_corr`). "
              "Прочерк значит «общих суток мало», а не «книги "
              "независимы».", ""]
    L += ["## Как читать", "",
          "- Колонка «без 3 лучших дней» и есть спор: если сестра не выше "
          "базы по ней, прибавка пришла эпизодом.",
          "- «Сделок взято» рядом с деньгами: больше сделок при том же "
          "депозите значит, что часть прибавки есть оборот капитала, а не "
          "выход.",
          "- Хвост своего имени охрана не ловит по построению: разгон одной "
          "монеты без хода рынка волна не видит.",
          f"- Расчёт: {s.get('computed_at')}, {s.get('secs')} с.", ""]
    return "\n".join(L)


def write(s, name=ART, out=None):
    out = out or OUT
    os.makedirs(out, exist_ok=True)
    art = os.path.join(out, f"{name}.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report(s)
    with open(os.path.join(out, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    return txt


def publish(name):
    sh = os.path.join(ROOT, "tools", "publish.sh")
    if os.path.exists(sh):
        subprocess.run(["bash", sh, name], cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--limit", type=int, default=None,
                    help="первых N позиций линейки — смоук")
    ap.add_argument("--replay", action="store_true",
                    help="шаг 2: реплей ядра внутри часа")
    ap.add_argument("--sample", type=int, default=None,
                    help="позиций в реплее (ровно по времени); 0 — все")
    ap.add_argument("--force", action="store_true",
                    help="считать шаг 2 даже если убийца 1 не пройден")
    ap.add_argument("--art", default=ART)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    try:
        os.nice(10)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)
    s = run(seeds=a.seeds, limit=a.limit, do_replay=a.replay,
            sample=a.sample, force=a.force)
    txt = write(s, name=a.art)
    print(txt)
    if s.get("error"):
        print(s["error"])
    if not a.no_publish:
        publish(f"механика {MECH}: охрана рынком как правило выхода "
                f"короткой книги ({a.art})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
