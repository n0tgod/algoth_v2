#!/usr/bin/env python3
"""
Механика d71203f0 — неспровоцированный принт ликвидации.

Что утверждается
----------------

Принудительное закрытие в имени B, перед которым НЕ двигались ни само B,
ни рынок, — это IOC-заявка площадки, у которой нет информации о B:
позицию снесло из-за уценки залога либо соседней позиции того же
единого счёта (у Bybit ликвидация срабатывает при MMR 100 % ПО СЧЁТУ).
Воздействие без информации временно, значит должно откатываться, и
откат обязан принадлежать ИМЕНИ, а не рынку.

Популяция, а не мера
--------------------

От L3, D1, LIQSPLIT, fcbd3542 и 994fc54f эта заявка отличается
ПОПУЛЯЦИЕЙ. Там событие — имя УЖЕ упало (3 % за 15 минут), то есть
ликвидация по определению спровоцирована: цену двигали продавцы имени.
Здесь берётся дополнение той выборки — принт есть, падения нет. Вердикт
L3 «отскок принадлежит рынку» вынесен по СВОЕЙ популяции и на её
дополнение не распространяется; спровоцированные принты считаются тем же
кодом группой сравнения, и если разницы нет, тот же прогон подтверждает
L3 ещё раз.

Тишина шести окон
-----------------

Событие: принт ликвидации лонга в имени B, перед которым спокойны шесть
окон — собственный ход середины B за 1, 5 и 60 минут в пределах 1σ
своего окна И медианный ход кросс-секции за те же три окна в пределах
своей 1σ. Пороги (1σ) и окна (1/5/60 мин) объявлены заданием ДО прогона
и после просмотра чисел не двигаются; 2σ печатается диагностикой.

**σ берётся у ПРОШЛЫХ суток, а не у текущих.** Иначе мера тишины знала
бы, чем кончится день, в который она решает: это ровно тот класс
дефекта, который проект ловил около десяти раз, и каждый раз его находил
человек, читавший число. У автономной сессии читателя нет, поэтому
правило закреплено тестом на заглядывание и негативным контролем к нему.

Пол у σ не назначен числом, а потребован строго положительным:
замороженный ряд даёт ход ровно ноль при σ ровно ноль, «0 ≤ 0» читается
как тишина, и вся выборка заполнилась бы именами без цены. Имя, у
которого σ за прошлые сутки равна нулю либо считана меньше чем по
`MIN_SIGMA_PTS` секундам, — **не измерено**, событие уходит в
именованный счётчик, а не в группу.

Метка стороны — по данным
-------------------------

`side` потока `allLiquidation` в проекте уже читался обратно: LIQSPLIT
намерил в падениях на 3 % долю `Sell` всего 0.34 и заключил, что на этом
потоке ликвидацию ЛОНГА маркирует `Buy`. Калибровка повторяется здесь на
нынешней записи и печатается; доля вблизи половины — отказ, а не
молчаливый выбор: перевёрнутый знак сделки неотличим от «эффекта нет».

Чего здесь НЕ живёт
-------------------

Второй копии ядра нет. Чтение принтов — `probe_liqsplit.liq_line`,
`liq_of_day`, `liq_day_alive`; окна, вход, форвард, фон и эпизоды —
`d1_seconds/detect.py`; загрузка суток, матрица и круг издержек —
`run_d1.py`; форма по дням — `factory/stability.py`; связь с пулом —
`ceiling.pair_corr`; предел памяти — `run_d10.mem_guard`. Здесь живут
ровно тишина, склейка принтов, разрез на две группы и вердикт из числа.

Файлов и сети этот модуль не касается: всё I/O — в `run_unprovoked.py`.
"""

import os
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in (os.path.join(RESEARCH, "d1_seconds"),
           os.path.join(RESEARCH, "b1_book"),
           os.path.join(RESEARCH, "factory"),
           os.path.join(RESEARCH, "probe_liqsplit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import detect as D                                          # noqa: E402
import stability as SB                                      # noqa: E402


def module_origin(mod):
    """Каталог, из которого модуль пришёл НА САМОМ ДЕЛЕ."""
    return os.path.basename(os.path.dirname(os.path.abspath(mod.__file__)))


def check_origin(mod, want):
    """Модуль из нужного каталога? Чужой тёзка — отказ, а не работа.

    Чужой модуль под знакомым именем уже импортировался в F3, и совпади
    имена функций, подмену нельзя было бы заметить вовсе. Проверка не
    украшение: живой смоук этой механики поймал ровно это — `ceiling`
    разрешался в `t4_structure`, а не в `factory`, и падение пришло на
    ПОСЛЕДНЕМ шаге прогона, после всего счёта.
    """
    got = module_origin(mod)
    if got != want:
        raise ImportError(f"чужой модуль {mod.__name__}: пришёл из "
                          f"{got}, а нужен из {want}")
    return True


def _from_file(name, *parts):
    """Модуль по ТОЧНОМУ пути, а не по имени из `sys.path`.

    На пути импорта у этого прогона семь каталогов, и имена в них
    повторяются: `ceiling.py` есть и у фабрики, и у `t4_structure`. Кто
    выиграет, решает порядок чужих импортов — то есть случайность,
    которая меняется от соседнего `import`. Путь не зависит ни от чего.
    """
    import importlib.util
    path = os.path.join(RESEARCH, *parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


CE = _from_file("factory_ceiling", "factory", "ceiling.py")

check_origin(D, "d1_seconds")
check_origin(SB, "factory")
check_origin(CE, "factory")

# --- объявлено заданием ДО прогона, после результата не меняется -------
WINDOWS_SEC = (60, 300, 3600)     # три окна тишины: 1, 5 и 60 минут
K_SIGMA = 1.0                     # порог тишины — одна сигма
K_SIGMA_DIAG = 2.0                # вторая сигма: диагностика, не ячейка
GLUE_SEC = 60                     # принты одного имени за 60 с — одно
ENTRY_SEC = 5                     # вход тейкером через 5 с после принта
HORIZON_SEC = 15 * 60             # удержание ячейки вердикта
DIAG_HORIZONS = (5 * 60, 30 * 60)   # кривая распада, предъявлять нельзя
NEED_MEAN_BP = 17.4               # убийца 2: круг тейкера по записи
NEED_GROSS_BP = 34.8              # планка D1 §7: двойной круг
MIN_EVENTS_PER_DAY = 10           # убийца 1: медианные сутки
NULL_SEEDS = 10                   # убийца 4: зёрен нуля
NULL_SEED0 = 20260912             # зерно ЧИСЛОМ: hash строки солится
BEST_DAYS = 3                     # колонка «без трёх лучших суток»
DROP = D.VERDICT_CELL["drop"]     # 0.03 — падение, на котором калибруют

# --- служебные допуски: свойства записи, а не гипотезы ------------------
CROSS_STEP_SEC = 10               # шаг сетки кросс-секционного хода
CROSS_CHUNK = 1024                # столбцов за раз при медиане сечения
MIN_SIGMA_PTS = 500               # секунд с ценой, иначе σ не измерена
SIDE_MARGIN = 0.05                # полоса неразличимости доли Sell
MIN_CALIB_PRINTS = 30             # принтов в окнах падений на калибровку
DAY_SEC = 86400

GROUPS = ("неспровоцированные", "спровоцированные")
SIDE_TITLE = {"long": "ликвидация лонга", "short": "ликвидация шорта"}


# ======================================================================
# 1. Принты: склейка в события
# ======================================================================

def glue_prints(ts, usd, gap=GLUE_SEC):
    """Принты одного имени в пределах `gap` — ОДНО событие.

    Возвращает список `(время первого принта, сумма нотионала, сколько
    принтов)`. Время события — первый принт кластера: он и есть момент
    решения, а последний известен только задним числом.

    Правило слипания — то же, что у `detect.detect`: новый кластер
    начинается, когда принт отстоит от НАЧАЛА текущего не меньше чем на
    `gap`. Иначе очередь принтов, идущая через 59 секунд, склеилась бы в
    один бесконечный «эпизод», и число событий зависело бы от плотности
    ленты, а не от рынка.
    """
    out, cur = [], None
    for t, u in zip(np.asarray(ts, dtype=np.float64),
                    np.asarray(usd, dtype=np.float64)):
        if cur is None or float(t) - cur[0] >= float(gap):
            cur = [float(t), float(u), 1]
            out.append(cur)
        else:
            cur[1] += float(u)
            cur[2] += 1
    return [(a, b, int(c)) for a, b, c in out]


def long_mark(n_sell, n_buy, margin=SIDE_MARGIN, min_prints=MIN_CALIB_PRINTS):
    """Какая метка `side` означает «ликвидация лонга». Решают ДАННЫЕ.

    Возвращает `(метка либо None, словами почему)`. В падениях на 3 %
    ликвидируют ЛОНГОВ — значит доминирующая там метка и есть наша.
    LIQSPLIT намерил долю `Sell` 0.34, то есть доминировал `Buy`; число
    пересчитывается на нынешней записи, а не переносится.

    Доля вблизи половины — `None`, то есть ОТКАЗ. Выбрать метку молча
    значило бы с вероятностью в половину перевернуть знак каждой сделки,
    и перевёрнутый знак выглядит ровно как «эффекта нет». Принтов меньше
    пола — тоже `None`: «не измерено» не есть «поровну».
    """
    n_sell, n_buy = int(n_sell), int(n_buy)
    tot = n_sell + n_buy
    if tot < int(min_prints):
        return None, (f"принтов в окнах падений {tot} при минимуме "
                      f"{int(min_prints)} — метка НЕ ИЗМЕРЕНА")
    share = n_sell / tot
    if share < 0.5 - float(margin):
        return "Buy", (f"доля Sell {share:.3f} из {tot} принтов: в "
                       f"падениях доминирует Buy — он и маркирует "
                       f"ликвидацию лонга")
    if share > 0.5 + float(margin):
        return "Sell", (f"доля Sell {share:.3f} из {tot} принтов: в "
                        f"падениях доминирует Sell — он и маркирует "
                        f"ликвидацию лонга")
    return None, (f"доля Sell {share:.3f} из {tot} принтов внутри полосы "
                  f"неразличимости ±{float(margin):.2f} — сторону выбрать "
                  f"НЕЧЕМ, знак сделки был бы угадан")


def other_side(mark):
    """Метка второй стороны. Диагностика «ликвидации шортов»."""
    if mark == "Buy":
        return "Sell"
    if mark == "Sell":
        return "Buy"
    return None


# ======================================================================
# 2. Тишина шести окон
# ======================================================================

def sigma_of(x, min_pts=MIN_SIGMA_PTS):
    """σ ряда ходов за сутки. `None` — НЕ ИЗМЕРЕНА, а не ноль.

    Два отказа, и оба не украшение. Секунд с ценой меньше пола —
    замороженный ряд, и σ по нему описывает не имя, а дыру в записи.
    σ ровно ноль — ряд, стоящий на месте: ход тоже ровно ноль, «0 ≤ 0»
    прошло бы как тишина, и вся неспровоцированная группа набилась бы
    именами без цены. Порога по величине здесь нет намеренно — он был бы
    назначен тем же, кто его проверяет.
    """
    v = np.asarray(x, dtype=np.float64)
    v = v[np.isfinite(v)]
    if len(v) < int(min_pts):
        return None
    s = float(np.std(v))
    if not (s > 0.0):
        return None
    return s


def quiet_of(own, cross, sig_own, sig_cross, k=K_SIGMA, windows=WINDOWS_SEC):
    """Спокойны ли ШЕСТЬ окон. `True` / `False` / `None` — не измерено.

    Шесть, а не три: собственный ход имени за 1, 5 и 60 минут И
    медианный ход кросс-секции за те же окна. Без второй половины
    «неспровоцированный» означал бы «имя стояло, пока рынок валился», а
    это ровно популяция L3, уже закрытая.

    `None` возвращается, когда хоть одной величины или хоть одной σ нет.
    Пропуск — прочерк с причиной, а не «не тихо»: иначе имя без записи
    молча пополняло бы группу сравнения.
    """
    own = own or {}
    cross = cross or {}
    sig_own = sig_own or {}
    sig_cross = sig_cross or {}
    for w in windows:
        a, b = own.get(w), cross.get(w)
        sa, sb = sig_own.get(w), sig_cross.get(w)
        if a is None or b is None or sa is None or sb is None:
            return None
        if not (np.isfinite(a) and np.isfinite(b)):
            return None
    for w in windows:
        if abs(float(own[w])) > float(k) * float(sig_own[w]):
            return False
        if abs(float(cross[w])) > float(k) * float(sig_cross[w]):
            return False
    return True


def scan_day(P, lo, hi, ev_by_row, windows=WINDOWS_SEC, step=CROSS_STEP_SEC,
             min_cross=D.MIN_CROSS, log=None):
    """Один проход по строкам суток: σ, кросс-сечение и ходы в событиях.

    Отдаёт четыре вещи:

    * `sigma_own[r][w]` — σ хода имени за окно `w` по ЭТИМ суткам. Она
      понадобится СЛЕДУЮЩИМ суткам, а не этим;
    * `sigma_cross[w]` — то же для медианного хода кросс-секции;
    * `cross_med[w]` — сам медианный ход на сетке шагом `step`;
    * `moves[r][j][w]` — собственный ход имени `r` в секунду события `j`.

    Кросс-секция считается на СЕТКЕ, а не посекундно, и это цена памяти:
    медиана по 767 именам на 93 600 секунд — это матрица в четверть
    гигабайта рядом со сборщиком, которому память отдавать нельзя. Шаг
    объявлен `CROSS_STEP_SEC` и одинаков у величины и у её σ; событие
    берёт значение с сетки НЕ ПОЗЖЕ своей секунды, то есть смотрит
    строго в прошлое.

    Ширина сечения тоньше пола — `nan`, не ноль: тот же порог, что у
    ядра (`detect.MIN_CROSS`), и берётся он у ядра.
    """
    log = log or (lambda m: None)
    rows_n, n = P.shape
    grid = np.arange(0, n, int(step), dtype=np.int64)
    gmat = {w: np.full((rows_n, len(grid)), np.nan, dtype=np.float32)
            for w in windows}
    sigma_own, moves = {}, {}
    for r in range(rows_n):
        row = np.asarray(P[r], dtype=np.float64)
        prev, nxt = D.fill_index(row)
        so, mv = {}, {}
        for w in windows:
            f = D.falls(row, prev, nxt, window_sec=int(w))
            gmat[w][r] = f[grid]
            so[int(w)] = sigma_of(f[int(lo):int(hi)])
            for j in ev_by_row.get(r, ()):
                mv.setdefault(int(j), {})[int(w)] = float(f[int(j)])
        sigma_own[r] = so
        if mv:
            moves[r] = mv
        if (r + 1) % 200 == 0:
            log(f"    тишина: просмотрено {r + 1}/{rows_n} имён")
    cross_med, sigma_cross = {}, {}
    in_day = (grid >= int(lo)) & (grid < int(hi))
    for w in windows:
        m = np.full(len(grid), np.nan)
        for a in range(0, len(grid), int(CROSS_CHUNK)):
            b = min(a + int(CROSS_CHUNK), len(grid))
            sub = gmat[w][:, a:b]
            width = np.isfinite(sub).sum(axis=0)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                med = np.nanmedian(sub, axis=0)
            m[a:b] = np.where(width >= int(min_cross), med, np.nan)
        cross_med[int(w)] = m
        sigma_cross[int(w)] = sigma_of(m[in_day])
        gmat[w] = None
    return {"sigma_own": sigma_own, "sigma_cross": sigma_cross,
            "cross_med": cross_med, "moves": moves, "grid_step": int(step)}


def cross_at(cross_med, j, step=CROSS_STEP_SEC, windows=WINDOWS_SEC):
    """Медианный ход сечения на сетке НЕ ПОЗЖЕ секунды `j`.

    Пол, а не округление: значение с сетки после `j` описывало бы рынок,
    которого в момент решения ещё не было. Отставание ограничено шагом
    сетки и работает против находки — тишина проверяется по чуть более
    старому рынку.
    """
    g = int(j) // int(step)
    out = {}
    for w in windows:
        arr = cross_med.get(int(w))
        if arr is None or g < 0 or g >= len(arr):
            out[int(w)] = None
        else:
            v = float(arr[g])
            out[int(w)] = v if np.isfinite(v) else None
    return out


# ======================================================================
# 3. Агрегат: эпизоды, группы, колонки концентрации
# ======================================================================

def _empty(names=0, events=0):
    return {"events": int(events), "episodes": 0, "mean_bp": None,
            "median_bp": None, "share_pos": None, "names": int(names)}


def group_stats(rows, key="exc"):
    """Сводка подмножества: среднее и медиана ПО ЭПИЗОДАМ.

    Обвал накрывает рынок целиком, и сотня событий одной минуты — одно
    наблюдение, а не сто. Считать событиями значило бы подделать бюджет
    доказательства втрое (перекрытие уже раздувало t в этом проекте).
    Эпизоды склеивает `detect.episodes` — та же функция, что у L3 и D1.
    """
    if not rows:
        return _empty()
    x = np.array([r.get(key, np.nan) for r in rows], dtype=np.float64)
    t = np.array([r["t"] for r in rows], dtype=np.float64)
    ok = np.isfinite(x)
    names = len({r["sym"] for r in rows})
    if not ok.any():
        return _empty(names=names, events=len(rows))
    v = D.by_episode(x[ok], D.episodes(t[ok]))
    if len(v) == 0:
        return _empty(names=names, events=len(rows))
    return {"events": len(rows), "episodes": int(len(v)),
            "mean_bp": round(float(np.mean(v)) * 1e4, 2),
            "median_bp": round(float(np.median(v)) * 1e4, 2),
            "share_pos": round(float(np.mean(v > 0)), 3),
            "names": names}


def split_by_quiet(rows, key="exc", flag="quiet"):
    """Две группы заявки: неспровоцированные и спровоцированные."""
    return {GROUPS[0]: group_stats([r for r in rows if r.get(flag) is True],
                                   key),
            GROUPS[1]: group_stats([r for r in rows if r.get(flag) is False],
                                   key)}


def _by(rows, field):
    out = {}
    for r in rows:
        out.setdefault(r.get(field), []).append(r)
    return out


def drop_best_name(rows, key="exc"):
    """То же число без ОДНОГО имени, давшего больше всех.

    Колонка обязательная: концентрация в этом проекте уже переворачивала
    знак. Лучшее имя — по СУММЕ вклада, а не по среднему: вопрос в том,
    живёт ли плюс в одном имени, а имя с одной удачной сделкой суммой не
    выделится.
    """
    if not rows:
        return _empty(), None
    tot = {}
    for sym, sub in _by(rows, "sym").items():
        v = [r.get(key) for r in sub
             if r.get(key) is not None and np.isfinite(r.get(key))]
        if v:
            tot[sym] = float(np.sum(v))
    if not tot:
        return _empty(), None
    best = max(tot, key=lambda s: tot[s])
    return group_stats([r for r in rows if r["sym"] != best], key), best


def drop_best_days(rows, key="exc", k=BEST_DAYS):
    """То же число без `k` лучших СУТОК записи.

    Книги живут эпизодами: у коротких книг без трёх лучших дней
    оставалось 28–48 % денег. Темпом такое читать нельзя, поэтому
    колонка стоит рядом с главным числом, а не в приложении.
    """
    if not rows:
        return _empty(), []
    tot = {}
    for day, sub in _by(rows, "day").items():
        v = [r.get(key) for r in sub
             if r.get(key) is not None and np.isfinite(r.get(key))]
        if v:
            tot[day] = float(np.sum(v))
    if not tot:
        return _empty(), []
    best = sorted(tot, key=lambda d: tot[d], reverse=True)[:int(k)]
    return group_stats([r for r in rows if r["day"] not in set(best)],
                       key), best


def terciles(rows, key="exc", size="usd"):
    """Трети по нотионалу принта. Довода за концентрацию в крупных нет.

    У LIQSPLIT градиент по нотионалу немонотонен (+28.6 / +17.9 / +23.1),
    поэтому трети — диагностика формы, а не вторая ячейка. Если плюс
    живёт только в верхней трети, кандидат вылетит по укусу, и объявлять
    его книгой нельзя.
    """
    v = [r for r in rows
         if r.get(size) is not None and np.isfinite(r.get(size))]
    if len(v) < 30:
        return []
    u = np.array([r[size] for r in v], dtype=np.float64)
    q1, q2 = np.quantile(u, [1 / 3, 2 / 3])
    out = []
    for name, sel in (("нижняя треть $", u <= q1),
                      ("середина", (u > q1) & (u < q2)),
                      ("верхняя треть $", u >= q2)):
        out.append((name, group_stats([r for r, s in zip(v, sel) if s], key)))
    return out


def ceiling_bp(rows, keys):
    """Потолок: лучший горизонт ПРИ ИДЕАЛЬНОМ ЗНАНИИ будущего.

    Считается первым и закрывает направление один: если даже всеведущий
    выбор между 5, 15 и 30 минутами не достаёт до круга тейкера, книге
    взяться неоткуда. Приём S1 — потолок рычагов; там он закрыл три
    направления за вечер.
    """
    got = [group_stats(rows, k)["mean_bp"] for k in keys]
    got = [g for g in got if g is not None]
    if not got:
        return None
    return max(got)


def null_stats(rows, seeds=NULL_SEEDS, key="null"):
    """Нуль: та же мера в СЛУЧАЙНУЮ секунду того же имени и того же часа.

    Зерно — число (`NULL_SEED0`), а не `hash` строки: хеш солится на
    каждый процесс, и нуль, который нельзя повторить, проверяемым не
    является (дефект R3). Планка — 95-й процентиль по зёрнам: одно
    зерно есть сам шум, а разрешение доли равно 1/зёрна.
    """
    if not rows:
        return {"seeds": 0, "pct95_bp": None, "mean_bp": None, "sd_bp": None}
    got = []
    for s in range(int(seeds)):
        sub = [dict(r, _null=(r.get(key) or [None] * int(seeds))[s])
               for r in rows]
        g = group_stats(sub, "_null")
        if g["mean_bp"] is not None:
            got.append(g["mean_bp"])
    if not got:
        return {"seeds": 0, "pct95_bp": None, "mean_bp": None, "sd_bp": None}
    a = np.array(got, dtype=np.float64)
    return {"seeds": int(len(a)),
            "pct95_bp": round(float(np.percentile(a, 95)), 2),
            "mean_bp": round(float(np.mean(a)), 2),
            "sd_bp": round(float(np.std(a)), 2)}


# ======================================================================
# 4. Форма по суткам и связь с живым пулом
# ======================================================================

def daily_series(rows, cost_bp, key="own", hold=HORIZON_SEC,
                 entry=ENTRY_SEC):
    """Сутки реплея: `{номер суток от эпохи: средняя нетто-позиция, %}`.

    Единица — средняя нетто-доходность ПОЗИЦИИ, закрытой в эти сутки.
    Своей кассы у реплея нет, и доллары здесь не выдумываются: депозит,
    число мест и потолок на имя заданием не объявлены, а назначить их
    самому значило бы подобрать величину, о которой потом спорят.

    Правила ячейки вердикта, которые тут действуют: равный размер, одна
    позиция на имя (пока открыта прежняя, новый принт того же имени не
    берётся), выход по времени. Ключ суток — номер суток по МОМЕНТУ
    ВЫХОДА, ровно как его кладёт касса кандидатов: иначе ряд нельзя ни
    сравнить с живыми книгами, ни отдать правилу вылета.
    """
    acc, busy = {}, {}
    for r in sorted(rows, key=lambda e: e["t"]):
        v = r.get(key)
        if v is None or not np.isfinite(v):
            continue
        t_in = float(r["t"]) + float(entry)
        if busy.get(r["sym"], -1e30) > t_in:
            continue
        t_out = t_in + float(hold)
        busy[r["sym"]] = t_out
        acc.setdefault(int(t_out // DAY_SEC), []).append(
            float(v) - float(cost_bp) / 1e4)
    return {d: round(float(np.mean(vs)) * 100.0, 6)
            for d, vs in sorted(acc.items())}


def form_stats(daily):
    """Форма книги по суткам — ОБЩЕЙ мерой проекта, а не своей.

    `stability.stats` считает медиану дня, худший день, укус и просадку
    и живым книгам пула, и реплеям кандидатов. Вторая реализация здесь
    разошлась бы с правилом вылета молча: отчёт говорил бы одно, а
    судили бы по другому.
    """
    s = SB.stats(daily)
    if not s:
        return None
    return dict(s)


def live_corr(daily, live):
    """Связь дневных денег реплея с живыми книгами пула.

    Считает `ceiling.pair_corr` — тем же кодом, которым потолок судит
    независимость заявки. `None` означает «не измерено» и печатается
    прочерком: ноль читался бы как «измерено, книги независимы», то есть
    как разрешение объявлять.
    """
    if not live:
        return None, None, 0
    mine = {int(d): float(v) for d, v in (daily or {}).items()}
    best, who, n = None, None, 0
    for cid, other in live.items():
        o = {int(d): float(v) for d, v in (other or {}).items()}
        r, k = CE.pair_corr(mine, o)
        if r is None:
            continue
        if best is None or abs(r) > abs(best):
            best, who, n = r, cid, k
    return best, who, n


# ======================================================================
# 5. Вердикт: четыре убийцы по порядку
# ======================================================================

def _num(v, fmt="+.1f"):
    """Величины, которой нет, — прочерк. Ноль означает «измерено»."""
    return "—" if v is None else format(v, fmt)


def killers(art):
    """Четыре убийцы заявки и планка D1. Каждый выводится ИЗ ЧИСЛА.

    Порядок объявлен заданием и не переставляется: объём, экономика,
    механизм, нуль. Первым идёт самый дешёвый — счётчик событий, который
    печатается ДО всякой доходности.
    """
    out = {}
    unp = art["split"][GROUPS[0]]
    prov = art["split"][GROUPS[1]]
    med = art.get("events_per_day_median")
    out["1. объём"] = (
        "не измерен: живых суток нет" if med is None else
        f"неспровоцированных событий в медианные сутки {med:.1f} при "
        f"минимуме {MIN_EVENTS_PER_DAY} (живых суток {art['days_live']}, "
        f"молчала лента {art['dead_days']}) — "
        + ("СРАБОТАЛ: класса нет либо поток его не видит"
           if med < MIN_EVENTS_PER_DAY else "не сработал"))
    out["2. экономика"] = (
        "не измерена: превышения нет" if unp["mean_bp"] is None else
        f"среднее превышение {unp['mean_bp']:+.1f} б.п. при круге тейкера "
        f"{NEED_MEAN_BP:.1f} — "
        + ("СРАБОТАЛ: вход не окупается даже валово"
           if unp["mean_bp"] <= NEED_MEAN_BP else "не сработал"))
    out["3. механизм"] = (
        "не измерен: одна из групп пуста"
        if unp["mean_bp"] is None or prov["mean_bp"] is None else
        f"неспровоцированные {unp['mean_bp']:+.1f} против "
        f"{prov['mean_bp']:+.1f} б.п. у спровоцированных — "
        + ("СРАБОТАЛ: тот же отскок после падения, что у L3 и LIQSPLIT"
           if unp["mean_bp"] <= prov["mean_bp"] else "не сработал"))
    n95 = (art.get("null") or {}).get("pct95_bp")
    out["4. нуль"] = (
        "не измерен" if n95 is None or unp["mean_bp"] is None else
        f"неспровоцированные {unp['mean_bp']:+.1f} против 95-го процентиля "
        f"нуля {n95:+.1f} б.п. по {art['null']['seeds']} зёрнам — "
        + ("СРАБОТАЛ: случайная секунда того же часа даёт не меньше"
           if unp["mean_bp"] <= n95 else "не сработал"))
    out["планка D1 §7 (не убийца)"] = (
        "не измерена" if unp["mean_bp"] is None else
        f"валовые {unp['mean_bp']:+.1f} при требуемых "
        f"{NEED_GROSS_BP:.1f} — "
        + ("НЕ ВЗЯТА: направление открыто, книги нет"
           if unp["mean_bp"] < NEED_GROSS_BP else "взята"))
    nb = art.get("no_best_name") or {}
    out["без лучшего имени"] = (
        "не измерено" if nb.get("mean_bp") is None else
        f"{nb['mean_bp']:+.1f} б.п. без имени {art.get('best_name')} "
        f"(было {_num(unp['mean_bp'])}) — "
        + ("плюс жил в одном имени" if nb["mean_bp"] <= 0
           else "знак держится"))
    nd = art.get("no_best_days") or {}
    out[f"без {BEST_DAYS} лучших суток"] = (
        "не измерено" if nd.get("mean_bp") is None else
        f"{nd['mean_bp']:+.1f} б.п. без суток "
        f"{', '.join(art.get('best_days') or []) or '—'} "
        f"(было {_num(unp['mean_bp'])}) — "
        + ("плюс жил в трёх сутках" if nd["mean_bp"] <= 0
           else "знак держится"))
    return out


def reading(art):
    """Вывод одной фразой. Выводится ИЗ ЧИСЛА, а не стоит рядом с ним.

    Фраза, положенная рядом с числом литералом, стареет молча и однажды
    противоречит своему же числу — в этом проекте так уже бывало.
    """
    unp = art["split"][GROUPS[0]]
    prov = art["split"][GROUPS[1]]
    med = art.get("events_per_day_median")
    if med is not None and med < MIN_EVENTS_PER_DAY:
        return (f"**Закрыто объёмом.** Неспровоцированных принтов "
                f"ликвидации лонга в медианные сутки {med:.1f} при "
                f"минимуме {MIN_EVENTS_PER_DAY}: класса нет либо поток "
                f"его не видит. Доходность считать не на чем, и остальные "
                f"числа отчёта — диагностика записи, а не рынка.")
    c = art.get("ceiling_bp")
    if unp["mean_bp"] is None:
        return ("Судить нечем: превышение неспровоцированных не измерено. "
                "Проверять надо ширину фона и запись, а не гипотезу — "
                "сломанная загрузка выглядит ровно как «эффекта нет».")
    if c is not None and c <= NEED_MEAN_BP:
        return (f"**Закрыто потолком.** Лучший горизонт при идеальном "
                f"знании будущего даёт {c:+.1f} б.п. при круге тейкера "
                f"{NEED_MEAN_BP:.1f}: ни 5, ни 15, ни 30 минут вход не "
                f"окупают, и разрез популяции этого поднять не может.")
    if unp["mean_bp"] <= NEED_MEAN_BP:
        return (f"**Закрыто экономикой.** Ячейка вердикта даёт "
                f"{unp['mean_bp']:+.1f} б.п. валовых при круге тейкера "
                f"{NEED_MEAN_BP:.1f} — направление не окупает своего "
                f"входа. Потолок по горизонтам {_num(c)} б.п. остаётся "
                f"диагностикой распада, предъявлять его нельзя (урок R5).")
    if prov["mean_bp"] is not None and unp["mean_bp"] <= prov["mean_bp"]:
        return (f"**Закрыто механизмом.** Неспровоцированные "
                f"{unp['mean_bp']:+.1f} против {prov['mean_bp']:+.1f} б.п. "
                f"у спровоцированных: это тот же отскок после падения, что "
                f"у L3 и LIQSPLIT, и слово «без информации» к нему ничего "
                f"не добавило. Вердикт L3 подтверждён на дополнении своей "
                f"популяции.")
    n95 = (art.get("null") or {}).get("pct95_bp")
    if n95 is not None and unp["mean_bp"] <= n95:
        return (f"**Закрыто нулём.** Неспровоцированные "
                f"{unp['mean_bp']:+.1f} б.п. против {n95:+.1f} у случайной "
                f"секунды того же имени и того же часа: мера ловит не "
                f"принт, а само имя в этот час.")
    nb = (art.get("no_best_name") or {}).get("mean_bp")
    nd = (art.get("no_best_days") or {}).get("mean_bp")
    if (nb is not None and nb <= 0) or (nd is not None and nd <= 0):
        return (f"Четыре убийцы пройдены ({unp['mean_bp']:+.1f} б.п.), но "
                f"плюс концентрирован: без лучшего имени {_num(nb)}, без "
                f"{BEST_DAYS} лучших суток {_num(nd)} б.п. По критерию "
                f"владельца это не книга, а замер направления.")
    if unp["mean_bp"] < NEED_GROSS_BP:
        return (f"Четыре убийцы пройдены: {unp['mean_bp']:+.1f} б.п. против "
                f"{prov['mean_bp']:+.1f} у спровоцированных и {_num(n95)} у "
                f"нуля. Планка D1 §7 ({NEED_GROSS_BP:.1f} б.п., двойной "
                f"круг) НЕ взята — направление открыто, книги нет.")
    return (f"Все четыре убийцы пройдены, планка D1 §7 взята: "
            f"{unp['mean_bp']:+.1f} б.п. валовых против "
            f"{NEED_GROSS_BP:.1f}, нуль {_num(n95)}, спровоцированные "
            f"{_num(prov['mean_bp'])}, эпизодов {unp['episodes']}. Дальше "
            f"— форма книги и решение пула, а не этого прогона.")


# ======================================================================
# 6. Отчёт
# ======================================================================

def _grp_table(L, split, title):
    L.append(f"\n### {title}\n")
    L.append("| группа | событий | эпизодов | среднее | медиана | "
             "доля > 0 | имён |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for name in split:
        g = split[name] or {}
        L.append(f"| {name} | {g.get('events', 0)} | "
                 f"{g.get('episodes', 0)} | {_num(g.get('mean_bp'))} | "
                 f"{_num(g.get('median_bp'))} | "
                 f"{_num(g.get('share_pos'), '.3f')} | "
                 f"{g.get('names', 0)} |")


def report(art, path):
    a = art
    L = ["# Механика d71203f0 — неспровоцированный принт ликвидации\n",
         f"Прогон {a['run_at']} · суток записи {a['days']} "
         f"({a['day_from']} … {a['day_to']}), из них живых лентой "
         f"ликвидаций **{a['days_live']}**, молчавших **{a['dead_days']}**, "
         f"отданных только под σ **{a.get('days_sigma_only', 0)}** "
         f"· имён {a['symbols']} · прогон занял {a['took_min']} мин\n",
         "**Это потолок заявки, а не вердикт этапа.** Событие — принт "
         "принудительного закрытия ЛОНГА в имени, перед которым спокойны "
         "шесть окон: собственный ход за 1, 5 и 60 минут в пределах 1σ и "
         "медианный ход кросс-секции за те же окна в пределах своей 1σ. "
         "σ берётся у ПРОШЛЫХ суток. Вход тейкером через "
         f"{ENTRY_SEC} с, удержание {HORIZON_SEC // 60} минут, выход по "
         "времени, равный размер, одна позиция на имя. Мера — превышение "
         "над одновременной кросс-секцией (`detect.excess`), среднее и "
         "медиана по эпизодам.\n",
         "## 1. Объём: считается ДО всякой доходности\n",
         f"- принтов ликвидации в СУЖДЁННЫХ сутках: **{a['prints']}** "
         f"(первые сутки записи в счёт не идут — они отданы под σ), "
         f"событий после склейки {GLUE_SEC} с: **{a['events_glued']}**",
         f"- метка стороны: **{a['long_mark'] or '—'}** — "
         f"{a['long_mark_why']}",
         f"- событий ячейки (сторона «{a['long_mark'] or '—'}»): "
         f"**{a['events_side']}**, из них неспровоцированных "
         f"**{a['events_unprovoked']}**, спровоцированных "
         f"**{a['events_provoked']}**, не классифицировано "
         f"**{a['events_unclassified']}** (σ прошлых суток нет либо ход не "
         f"измерен)",
         f"- неспровоцированных событий в сутки: медиана "
         f"**{_num(a.get('events_per_day_median'), '.1f')}** при минимуме "
         f"{MIN_EVENTS_PER_DAY} (убийца 1)\n",
         "Сутки, в которые лента ликвидаций молчала ЦЕЛИКОМ, событий не "
         "дают и считаются отдельным числом: молчащая подписка снаружи "
         "неотличима от спокойного рынка. Цены таких суток при этом "
         "прочитаны — σ следующим суткам они дают.\n",
         "## 2. Ячейка вердикта\n",
         f"Круг тейкера по нашей записи — **{a['cost_round_bp']:.1f} б.п.** "
         f"({a['cost_src']}); порог убийцы 2 объявлен заданием как "
         f"{NEED_MEAN_BP:.1f}.\n"]
    _grp_table(L, a["split"], "Превышение над одновременной кросс-секцией, "
                              f"удержание {HORIZON_SEC // 60} мин")
    L.append("\n### Концентрация — колонки обязательные\n")
    L.append("| срез | событий | эпизодов | среднее | медиана | доля > 0 |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for name, g in (("неспровоцированные, все",
                     a["split"][GROUPS[0]]),
                    (f"без лучшего имени ({a.get('best_name') or '—'})",
                     a.get("no_best_name") or {}),
                    (f"без {BEST_DAYS} лучших суток "
                     f"({', '.join(a.get('best_days') or []) or '—'})",
                     a.get("no_best_days") or {})):
        L.append(f"| {name} | {g.get('events', 0)} | {g.get('episodes', 0)} "
                 f"| {_num(g.get('mean_bp'))} | {_num(g.get('median_bp'))} "
                 f"| {_num(g.get('share_pos'), '.3f')} |")
    L.append("\n## 3. Потолок и нуль\n")
    L.append(f"- потолок по горизонтам "
             f"{', '.join(str(h // 60) for h in sorted(a['horizons']))} "
             f"мин при идеальном знании будущего: "
             f"**{_num(a.get('ceiling_bp'))} б.п.**")
    n = a.get("null") or {}
    L.append(f"- нуль «случайная секунда того же имени и того же часа», "
             f"зёрен {n.get('seeds', 0)} (зерно {NULL_SEED0} числом): "
             f"среднее {_num(n.get('mean_bp'))}, разброс "
             f"{_num(n.get('sd_bp'), '.2f')}, 95-й процентиль "
             f"**{_num(n.get('pct95_bp'))} б.п.**\n")
    L.append("## 4. Четыре убийцы по порядку\n")
    for k, s in a["killers"].items():
        L.append(f"- **{k}**: {s}")
    L.append("\n## 5. Форма по суткам\n")
    f = a.get("form") or {}
    L.append("Единица суток — средняя нетто-доходность позиции, закрытой в "
             "эти сутки, в процентах. Своей кассы у реплея нет: депозит, "
             "число мест и потолок на имя заданием не объявлены, и "
             "выдумывать их значило бы назначить величину, о которой потом "
             "спорят. Мера формы — общая `factory/stability.py`.\n")
    if not f:
        L.append("Форма не измерена: закрытых суток нет.\n")
    else:
        L.append("| суток | зелёных | медиана дня | худший день | укус | "
                 "просадка | под водой |")
        L.append("|--:|--:|--:|--:|--:|--:|--:|")
        L.append(f"| {f.get('days')} | {_num(f.get('green'), '.2f')} | "
                 f"{_num(f.get('med'), '+.3f')} % | "
                 f"{_num(f.get('worst'), '+.3f')} % | "
                 f"{_num(f.get('bite'), '.1f')} | "
                 f"{_num(f.get('dd'), '+.3f')} % | {f.get('under')} |")
        if f.get("thin"):
            L.append(f"\n⚠ суток меньше {SB.MIN_DAYS}: величины посчитаны, "
                     f"но вердикта по форме нет.")
    L.append(f"\nСвязь дневных денег с живыми книгами пула: "
             f"**{_num(a.get('live_corr'), '+.3f')}** "
             f"({a.get('live_corr_with') or 'сравнивать не с чем'}, "
             f"{a.get('live_corr_days', 0)} общих суток). Предел, по "
             f"которому судит пул, — {CE.MAX_CORR:.2f}.\n")
    L.append("## 6. Диагностика — предъявлять запрещено\n")
    L.append("Ячейки ниже просмотрены ПОСЛЕ данных. Выбрать лучшую и "
             "объявить её и есть ошибка R5; ячейка вердикта одна и "
             "объявлена заданием до прогона.\n")
    for name, sp in (a.get("diagnostics") or {}).items():
        _grp_table(L, sp, name)
    tr = a.get("terciles") or []
    if tr:
        L.append("\n### Трети по нотионалу принта\n")
        L.append("| треть | событий | эпизодов | среднее | медиана | "
                 "доля > 0 |")
        L.append("|---|--:|--:|--:|--:|--:|")
        for name, g in tr:
            L.append(f"| {name} | {g['events']} | {g['episodes']} | "
                     f"{_num(g.get('mean_bp'))} | "
                     f"{_num(g.get('median_bp'))} | "
                     f"{_num(g.get('share_pos'), '.3f')} |")
    L.append("\n## 7. Как читать\n")
    L.append(a["reading"])
    L.append("\n## 8. Оговорки, этим прогоном не снимаемые\n")
    L.append("- метка стороны калибрована по ВСЕЙ записи, то есть знает "
             "её целиком. Это вопрос семантики поля площадки, а не "
             "сигнал; устойчивость метки по половинам записи напечатана "
             "в диагностике, и разойдись половины — верить нельзя ни "
             "одной;")
    L.append("- кросс-секционный ход берётся с сетки шагом "
             f"{CROSS_STEP_SEC} с и НЕ ПОЗЖЕ секунды события: отставание "
             "работает против находки, но сглаживает резкие минуты;")
    L.append("- превышение над кросс-секцией есть мера ЗАХЕДЖИРОВАННОЙ "
             "ноги, а живая книга голая и в каскадный день несёт рынок;")
    L.append("- проскальзывания обходом лесенки в числах нет, оно может "
             "только ухудшить; спред входит в круг издержек измеренным "
             "по нашей же записи;")
    L.append("- отмены заявок в записи не видны, поэтому «принт без "
             "движения» опирается на середину книги, а не на намерения "
             "счёта, чью позицию снесли.")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return path
