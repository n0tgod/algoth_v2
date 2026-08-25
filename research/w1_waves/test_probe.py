#!/usr/bin/env python3
"""Проверки прогона волнового зонда.

Главная здесь одна и она калибровочная: **зонд обязан находить волну,
которая в данных действительно есть.** Без неё отрицательный результат
не значит ничего — пустая матрица цен и сломанная загрузка выглядят
ровно как «волн нет», и проект уже дважды печатал нулевой отчёт именно
так.

Поэтому проверок две в обе стороны: на подсаженной волне IC обязан быть
высоким, а нуль — около ноля; на чистых случайных блужданиях обязаны
быть около ноля ОБА. Мера, которая находит волну там, где её нет,
негодна так же, как мера, которая не находит настоящую.

Остальное — дороги. У зонда их несколько (загрузка, соседи, статистика
сечения, зигзаг, сборка отчёта, публикация), и «тесты зелёные» значит
ровно те дороги, которые тесты ИСПОЛНЯЮТ: колонка просадки в турнире
однажды встала прочерками потому, что проверялась величина, а не её
дорога до отчёта.
"""

import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import waves as W                                          # noqa: E402
import probe as P                                          # noqa: E402
from test_waves import check, FAILED                       # noqa: E402

HOUR = 3600
# Три «типа» рынка: у каждого своя форма и своё будущее. Формы взяты
# заведомо различимыми — задача проверки не в тонкости, а в том, что
# дорога от формы до IC вообще проходима.
SHAPES = {
    0: np.linspace(0.0, 1.0, 9),                       # разгон вверх
    1: np.linspace(0.0, -1.0, 9),                      # разгон вниз
    2: np.concatenate([np.linspace(0, 1, 5),
                       np.linspace(1, 0, 5)[1:]]),     # горб
}
FWD = {0: +0.03, 1: -0.03, 2: 0.0}


class Cfg:
    """Малая объявленная сетка на время проверки: дороги те же."""

    def __init__(self, **kw):
        self.kw = kw
        self.old = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(P, k)
            setattr(P, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(P, k, v)


def synth(planted, n_sym=60, pool_days=60, test_days=40, w=8,
          query_every=24, seed=3):
    """Универсум случайных блужданий; при `planted` в него сажают волну.

    Волна сажается ОДНОЙ И ТОЙ ЖЕ формой в пуле и в тестовой эре, иначе
    соседей не из чего брать. Будущее пишется последним, чтобы его не
    затёрла следующая посадка.
    """
    rng = np.random.default_rng(seed)
    n_h = (pool_days + test_days) * 24
    t0 = 1_700_000_000 - (1_700_000_000 % HOUR)
    times = np.arange(t0, t0 + n_h * HOUR, HOUR, dtype=np.int64)
    L = np.log(100.0 + np.cumsum(
        rng.normal(0, 0.05, (n_sym, n_h)), axis=1)).astype(np.float32)
    # Колонки посадки обязаны совпасть с теми, которые зонд СПРАШИВАЕТ:
    # он идёт от начала тестовой эры шагом `query_every`, и посадка со
    # сдвигом фазы просто не попадалась бы ему на глаза. Первая версия
    # фикстуры сажала волну с шага `w+1` — проверка честно показала
    # «волны нет» на данных, где волна была.
    cols = np.arange(query_every, n_h - 3, query_every, dtype=np.int64)
    if planted:
        for r in range(n_sym):
            t = r % 3
            for j in cols:
                L[r, j - w:j + 1] = (L[r, j - w] + SHAPES[t] * 0.05
                                     + rng.normal(0, 0.0005, w + 1))
        for r in range(n_sym):
            t = r % 3
            for j in cols:
                L[r, j + 1] = L[r, j] + FWD[t] / 2.0
                L[r, j + 2] = L[r, j] + FWD[t]
    pool_end = pool_days * 24
    return L, times, [f"S{i:03d}USDT" for i in range(n_sym)], t0, pool_end


def _run(planted, seed=3):
    L, times, syms, t0, pool_end = synth(planted, seed=seed)
    from datetime import datetime, timezone
    iso = (lambda ts: datetime.fromtimestamp(int(ts), timezone.utc)
           .replace(tzinfo=None).isoformat())
    with Cfg(WINDOWS=(8,), HORIZONS=(2,), K=5, POOL=4000, POOL_DAYS=60,
             QUERY_EVERY_H=24, MIN_CROSS=20, BLOCK_Q=64,
             SIM_BANDS=((0.0, 0.9), (0.9, 1.01)),
             START=iso(times[pool_end]), END=iso(times[-1] - 4 * HOUR)):
        acc, acc0 = P.run_knn(L, times, syms, np.random.default_rng(11),
                              log=lambda m: None)
        return P.cells_table(acc, acc0)


def test_probe_finds_a_wave_that_is_really_there():
    """Подсаженная волна обязана находиться — иначе ноль ничего не значит."""
    rows = _run(planted=True)
    check("ячейка измерена", len(rows) == 1, str(len(rows)))
    if not rows:
        return
    r = rows[0]
    check("сечений набралось", r["sections"] >= 10, str(r["sections"]))
    check("IC на подсаженной волне высок", r["ic"] > 0.5, f"{r['ic']:+.4f}")
    check("нуль на той же волне около ноля", abs(r["ic_null"]) < 0.25,
          f"{r['ic_null']:+.4f}")
    check("прогон перебивает свой нуль", r["ic"] > r["ic_null"] + 0.3,
          f"{r['ic']:+.4f} против {r['ic_null']:+.4f}")
    check("спред дециля положителен", r["spread_bp"] > 0,
          f"{r['spread_bp']:+.1f}")
    check("книга есть половина спреда",
          abs(r["book_bp"] - r["spread_bp"] / 2) < 1e-6)


def test_pure_random_walks_give_nothing():
    """На случайных блужданиях около ноля обязаны быть ОБА числа.

    Мера, находящая волну там, где её нет, негодна так же, как мера,
    не находящая настоящую.
    """
    rows = _run(planted=False)
    check("ячейка измерена и без посадки", len(rows) == 1, str(len(rows)))
    if not rows:
        return
    r = rows[0]
    check("IC на шуме около ноля", abs(r["ic"]) < 0.15, f"{r['ic']:+.4f}")
    check("нуль на шуме около ноля", abs(r["ic_null"]) < 0.15,
          f"{r['ic_null']:+.4f}")


def test_break_even_ic_is_computed_from_the_measured_spread():
    """Порог окупаемости считается из σ ячейки, а не назначается.

    Он и решает, какие ячейки мертвы по построению: при разбросе
    исходов за час окупить круг издержек требуется IC, которого не
    бывает, а за сутки — вполне обычный. Печатать один IC без этого
    числа значит сравнивать несравнимое.
    """
    with Cfg(ROUND_COST_BP=11.0):
        hour = P.ic_break_even(0.01)          # σ 100 б.п. — часовой масштаб
        day = P.ic_break_even(0.05)           # σ 500 б.п. — суточный
    check("порог обратен разбросу", hour > day, f"{hour:.4f} / {day:.4f}")
    check("часовой порог заведомо высок", hour > 0.05, f"{hour:.4f}")
    check("суточный порог достижим", day < 0.02, f"{day:.4f}")
    # Арифметика проверяется числом, а не свойством: прибыль книги есть
    # половина спреда, спред есть IC·σ·3.51.
    ic = P.ic_break_even(0.05)
    book_bp = ic * 0.05 * P.DECILE_K / 2 * 1e4
    check("на пороге книга ровно окупает круг",
          abs(book_bp - 11.0) < 1e-6, f"{book_bp:.4f}")
    check("нулевой разброс порога не даёт",
          not np.isfinite(P.ic_break_even(0.0)))


def test_pool_is_strictly_in_the_past():
    """Соседи берутся только из прошлого — проверяется САМА граница.

    Первая версия этой проверки ловила не границу, а её следствие: она
    сажала пул в тестовую эру и ждала, что IC взлетит от самосовпадений.
    Не взлетел — совпадений вышло около трёх процентов запросов, и
    медиана по сечениям их не заметила. То есть заглядывание прошло бы
    мимо проверки, а проверка выглядела бы исправной. Граница
    проверяется там, где о ней принимают решение.
    """
    L, times, syms, _, pool_end = synth(planted=True)
    from datetime import datetime, timezone
    iso = (lambda ts: datetime.fromtimestamp(int(ts), timezone.utc)
           .replace(tzinfo=None).isoformat())
    calls, real = [], P.sample_pool

    def spy(*a, **kw):
        calls.append((a[2], a[3]))          # (t_lo, t_hi)
        return real(*a, **kw)

    with Cfg(WINDOWS=(8,), HORIZONS=(2,), K=5, POOL=4000, POOL_DAYS=60,
             QUERY_EVERY_H=24, MIN_CROSS=20, BLOCK_Q=64,
             SIM_BANDS=((0.0, 1.01),),
             START=iso(times[pool_end]), END=iso(times[-1] - 4 * HOUR)):
        P.sample_pool = spy
        try:
            P.run_knn(L, times, syms, np.random.default_rng(11),
                      log=lambda m: None)
        finally:
            P.sample_pool = real
    check("пул вообще строился", len(calls) > 0, str(len(calls)))
    check("верхняя граница пула не заходит в тестовую эру",
          all(hi <= pool_end for _, hi in calls), str(calls[:3]))
    check("нижняя граница пула не уходит за начало записи",
          all(lo >= 0 for lo, _ in calls), str(calls[:3]))


def test_sample_pool_respects_its_bounds():
    """Пул не отдаёт ни одной колонки вне запрошенного окна."""
    rng = np.random.default_rng(1)
    L = rng.normal(size=(10, 200)).astype(np.float32)
    ok = np.ones(200, dtype=bool)
    got = P.sample_pool(L, ok, 40, 120, 8, rng, want=500)
    check("пул набран", got is not None and len(got[1]) > 0)
    if got:
        c = got[1]
        check("колонки строго внутри окна",
              bool(c.min() >= 40 and c.max() < 120),
              f"{int(c.min())}…{int(c.max())}")
    check("окно нулевой ширины пула не даёт",
          P.sample_pool(L, ok, 100, 100, 8, rng) is None)


def test_excess_is_over_the_equal_weight_section():
    """Избыток считается сверх РАВНОВЗВЕШЕННОЙ кросс-секции.

    Контроль средним, а не медианой: медиана робастна, но она не
    портфель, и Z1 намерил, что превышение над ней несёт снос, не
    зависящий от условия.
    """
    L = np.zeros((4, 5), dtype=np.float32)
    L[:, 2] = [0.0, 0.0, 0.0, 0.0]
    L[:, 3] = [0.01, 0.02, 0.03, 0.10]          # сильно скошено вправо
    with Cfg(MIN_CROSS=2):
        F = P.excess_forward(L, 1, min_cross=2)
    got = F[:, 2]
    check("сумма избытков по сечению равна нулю",
          abs(float(np.nansum(got))) < 1e-6, str(got))
    check("скошенность не даёт медианного сноса",
          float(got[3]) > 0 and float(got[0]) < 0, str(got))
    with Cfg(MIN_CROSS=99):
        F2 = P.excess_forward(L, 1, min_cross=99)
    check("тонкое сечение — пропуск целиком",
          bool(np.isnan(F2[:, 2]).all()))


def test_prediction_needs_enough_neighbours():
    """Мало соседей с известным будущим — ПРОПУСК, а не значение по тем.

    Дорога проверяется напрямую: в синтетике у всех соседей будущее
    известно, порог не связывает никогда, и отрицательный контроль на
    него оказался холостым — правило существовало бы только на вид.
    """
    nb = np.full((3, 10), np.nan)
    nb[0] = np.arange(10.0)                 # десять из десяти
    nb[1, :1] = 5.0                         # один — ниже порога
    nb[2, :2] = [4.0, 6.0]                  # ровно порог 0.2 × 10
    with Cfg(MIN_NB_SHARE=0.2):
        out = P._median_of(nb, 3, np.ones(3, dtype=bool))
    check("полный набор соседей даёт предсказание",
          np.isfinite(out[0]) and abs(out[0] - 4.5) < 1e-9, str(out[0]))
    check("одного соседа мало — пропуск", not np.isfinite(out[1]),
          str(out[1]))
    check("ровно порог принимается",
          np.isfinite(out[2]) and abs(out[2] - 5.0) < 1e-9, str(out[2]))


def test_path_ends_in_its_own_column():
    """Путь кончается СВОЕЙ колонкой и не заглядывает вперёд."""
    L = np.arange(40, dtype=np.float32).reshape(2, 20)
    got = P.paths(L, np.array([0, 1]), np.array([10, 12]), 4)
    check("длина пути W+1", got.shape == (2, 5), str(got.shape))
    check("последний элемент — своя колонка",
          float(got[0, -1]) == float(L[0, 10])
          and float(got[1, -1]) == float(L[1, 12]))
    check("первый элемент отстоит на W",
          float(got[0, 0]) == float(L[0, 6]))
    # Отрицательный индекс в numpy — не ошибка, а отсчёт с конца: путь,
    # начинающийся раньше начала матрицы, склеился бы из ХВОСТА записи,
    # то есть из будущего, и форма вышла бы настоящая, просто чужая.
    try:
        P.paths(L, np.array([0]), np.array([2]), 4)
        check("путь за начало записи отвергается", False, "не упало")
    except ValueError as e:
        check("путь за начало записи отвергается", True)
        check("отказ называет колонку и длину",
              "2" in str(e) and "4" in str(e), str(e))


def test_report_is_written_and_its_verdict_comes_from_the_numbers():
    """Отчёт собирается настоящим вызовом, а фраза выводится из числа.

    Проза, написанная под ожидаемый результат, однажды уже
    противоречила собственной таблице отчёта.
    """
    d = tempfile.mkdtemp()
    try:
        base = {"W": 24, "h": 4, "sections": 500, "rev_ic": 0.05,
                "spread_bp": 4.0, "book_bp": 2.0, "bands": {},
                "sigma_bp": 500.0, "ic_need": 0.0125}
        weak = [dict(base, ic=0.010, ic_null=0.020, resid_ic=0.001)]
        pathw = P.write_report(os.path.join(d, "w.md"), weak, {},
                               {"when": "т", "start": "a", "end": "b",
                                "symbols": 3})
        tw = open(pathw, encoding="utf-8").read()
        check("отчёт написан файлом", os.path.exists(pathw))
        check("нуль не перебит — так и сказано",
              "НЕ лучше случайных" in tw, tw[-400:])
        dress = [dict(base, ic=0.060, ic_null=0.005, resid_ic=0.004)]
        td = open(P.write_report(os.path.join(d, "d.md"), dress, {},
                                 {"when": "т", "start": "a", "end": "b",
                                  "symbols": 3}), encoding="utf-8").read()
        check("возврат в костюме назван возвратом",
              "в новом костюме" in td, td[-400:])
        rich = [dict(base, ic=0.060, ic_null=0.005, resid_ic=0.050,
                     spread_bp=60.0, book_bp=30.0)]
        tr = open(P.write_report(os.path.join(d, "r.md"), rich, {},
                                 {"when": "т", "start": "a", "end": "b",
                                  "symbols": 3}), encoding="utf-8").read()
        check("перебитый круг издержек назван поводом писать спеку",
              "повод писать спеку" in tr, tr[-400:])
        check("оговорка про ошибку R5 стоит на самой странице",
              "R5" in tr)
        check("все объявленные ячейки в таблице",
              tr.count("| 24 | 4 |") >= 2, str(tr.count("| 24 | 4 |")))
        # Пустая таблица обязана объяснять СЕБЯ, и по-разному: пропуск
        # по ключу и «не набралось» — разные состояния, а выглядят
        # одинаково. Колонка просадки турнира встала прочерками именно
        # так, и владелец справедливо спросил, что сломалось.
        sk = open(P.write_report(os.path.join(d, "s.md"), [], {},
                                 {"when": "т", "start": "a", "end": "b",
                                  "symbols": 3,
                                  "skipped": ("knn", "zigzag")}),
                  encoding="utf-8").read()
        check("пропуск по ключу назван пропуском по ключу",
              sk.count("ключом пропуска") == 2, str(sk.count("ключом")))
        no = open(P.write_report(os.path.join(d, "n.md"), [], {},
                                 {"when": "т", "start": "a", "end": "b",
                                  "symbols": 3, "skipped": ()}),
                  encoding="utf-8").read()
        check("несобравшаяся выборка названа несобравшейся",
              "не набралось" in no and "ключом пропуска" not in no,
              no[:200])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_zigzag_report_road_runs_and_compares_to_surrogate():
    """Дорога прочитки 2 исполняется целиком и кладёт обе стороны."""
    # Тестовая эра берётся длиннее объявленного минимума истории, а не
    # подгоняется под него подменой константы: порог — часть меры.
    L, times, syms, _, _ = synth(planted=False, n_sym=6, pool_days=30,
                                 test_days=120, seed=5)
    from datetime import datetime, timezone
    iso = (datetime.fromtimestamp(int(times[30 * 24]), timezone.utc)
           .replace(tzinfo=None).isoformat())
    with Cfg(THETAS=(1.0,), BOOT=2, START=iso):
        zz = P.run_zigzag(L, times, syms, np.random.default_rng(2),
                          log=lambda m: None)
    check("порог посчитан", 1.0 in zz, str(list(zz)))
    d = zz.get(1.0, {})
    check("ноги найдены", d.get("legs", 0) > 0, str(d.get("legs")))
    check("суррогат посчитан рядом", d.get("surrogate", {}).get("n", 0) > 0,
          str(d.get("surrogate", {}).get("n")))
    check("задержка подтверждения положительна",
          d.get("lag_median_h", 0) > 0, str(d.get("lag_median_h")))
    check("связь соседних ног посчитана и у факта, и у суррогата",
          np.isfinite(d.get("next_leg", np.nan))
          and np.isfinite(d.get("next_leg_sur", np.nan)),
          f"{d.get('next_leg')} / {d.get('next_leg_sur')}")
    dd = tempfile.mkdtemp()
    try:
        t = open(P.write_report(os.path.join(dd, "z.md"), [], zz,
                                {"when": "т", "start": "a", "end": "b",
                                 "symbols": 6}), encoding="utf-8").read()
        check("в отчёте обе строки — факт и суррогат",
              "факт" in t and "суррогат" in t)
        check("связь соседних ног доехала до отчёта",
              "Говорит ли нога о следующей" in t and "разница" in t,
              t[-600:])
        check("задержка подтверждения названа платой за честность",
              "цена честности" in t)
    finally:
        shutil.rmtree(dd, ignore_errors=True)


def test_memory_is_counted_before_the_run_not_after_the_kill():
    """Не влезаем — отказ со словами; влезаем — молчание. Обе стороны.

    Рядом идёт живой сбор стакана, и записи, которую он потеряет, не
    докачать ниоткуда. Прогон D1 был убит ядром по памяти именно так.
    """
    with Cfg(MEM_SHARE=1e-9):
        try:
            P.memory_plan(700, 40_000, log=lambda m: None)
            check("непомещающийся прогон отказывается", False, "не упало")
        except SystemExit as e:
            check("непомещающийся прогон отказывается", True)
            check("отказ называет, что уменьшать",
                  "BLOCK_Q" in str(e) and "POOL" in str(e), str(e))
    with Cfg(MEM_SHARE=0.5):
        said = []
        P.memory_plan(10, 100, log=said.append)
        check("помещающийся прогон не поднимает тревоги", True)
        check("нужное и доступное названы числом",
              said and "МБ" in said[0], str(said))


def test_empty_matrix_is_a_refusal_not_an_absence_of_waves():
    """Пустая загрузка обязана падать со словами, а не печатать ноль."""
    old = P.D.price_matrix
    P.D.price_matrix = lambda *a, **k: np.full((3, 10), np.nan,
                                               dtype=np.float32)
    try:
        try:
            P.load_prices(["AUSDT"], np.arange(10) * HOUR, "1m",
                          log=lambda m: None)
            check("пустая матрица остановила прогон", False, "не упало")
        except SystemExit as e:
            check("пустая матрица остановила прогон", True)
            check("отказ назван словами", "заполнена" in str(e), str(e))
    finally:
        P.D.price_matrix = old


def test_publication_is_part_of_the_run():
    """С ключом публикации нет, без ключа — есть. Обе стороны."""
    said = []
    old_pub, old_out = P.Z.publish, P.OUT
    old_load, old_knn, old_zz = P.load_prices, P.run_knn, P.run_zigzag
    d = tempfile.mkdtemp()
    try:
        P.Z.publish = lambda m: said.append(m)
        P.OUT = os.path.join(d, "out")            # каталога ещё НЕТ
        P.load_prices = lambda *a, **k: np.zeros((2, 5), dtype=np.float32)
        P.run_knn = lambda *a, **k: ({}, {})
        P.run_zigzag = lambda *a, **k: {}
        P.main(["--symbols", "AUSDT,BUSDT", "--tag", "t", "--no-publish"])
        check("каталог артефактов создаётся прогоном",
              os.path.exists(os.path.join(P.OUT, "W1-waves-t.md")))
        check("с ключом публикации нет", not said, str(said))
        P.main(["--symbols", "AUSDT,BUSDT", "--tag", "t"])
        check("без ключа публикация случилась", len(said) == 1, str(said))
    finally:
        P.Z.publish, P.OUT = old_pub, old_out
        P.load_prices, P.run_knn, P.run_zigzag = old_load, old_knn, old_zz
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = (
        test_probe_finds_a_wave_that_is_really_there,
        test_pure_random_walks_give_nothing,
        test_break_even_ic_is_computed_from_the_measured_spread,
        test_pool_is_strictly_in_the_past,
        test_sample_pool_respects_its_bounds,
        test_excess_is_over_the_equal_weight_section,
        test_prediction_needs_enough_neighbours,
        test_path_ends_in_its_own_column,
        test_report_is_written_and_its_verdict_comes_from_the_numbers,
        test_zigzag_report_road_runs_and_compares_to_surrogate,
        test_memory_is_counted_before_the_run_not_after_the_kill,
        test_empty_matrix_is_a_refusal_not_an_absence_of_waves,
        test_publication_is_part_of_the_run,
    )
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
