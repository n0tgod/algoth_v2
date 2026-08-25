#!/usr/bin/env python3
"""Проверки ядра волнового зонда.

Три из них стоят отдельно, потому что без них зонд считал бы не то и
выглядел бы исправным:

* **зигзаг причинный** — вершина подтверждается позже, чем случается, и
  разметка, берущая вершину в момент вершины, заглядывает в будущее;
* **замороженный путь формой не является** — иначе z-нормировка делит
  дрожание последнего знака на само себя и получает форму, которая
  «повторяется» по всему универсуму (ловушка S1 в новом костюме);
* **размер блока не меняет ответа** — ускорение, меняющее числа, есть
  другая мера.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import waves as W                                          # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "ПРОВАЛ ") + name
          + ("" if cond else f"  · {extra}"))
    if not cond:
        FAILED.append(name)


def saw(peaks, step=1.0):
    """Пила из логарифмических цен по заданным вершинам."""
    x = [0.0]
    for p in peaks:
        a = x[-1]
        n = max(int(abs(p - a) / step), 1)
        x.extend(list(np.linspace(a, p, n + 1))[1:])
    return np.array(x, dtype=np.float64)


def test_zigzag_is_causal():
    """Вершина подтверждается ПОЗЖЕ, чем случается, и обе метки видны."""
    x = saw([0.10, 0.02, 0.12, 0.04], step=0.005)
    piv = W.zigzag(x, theta=0.03)
    check("развороты найдены", len(piv) >= 3, str(len(piv)))
    check("подтверждение строго позже вершины",
          all(ic > ip for ip, ic, _ in piv),
          str([(ip, ic) for ip, ic, _ in piv]))
    # Вершина обязана быть настоящим экстремумом своей окрестности.
    ok = True
    for ip, ic, d in piv:
        seg = x[ip:ic + 1]
        ok &= (x[ip] == seg.max()) if d > 0 else (x[ip] == seg.min())
    check("вершина есть экстремум своего отрезка", ok)
    # Знаки чередуются: две вершины подряд означали бы, что ногу
    # потеряли.
    dirs = [d for _, _, d in piv]
    check("направления чередуются",
          all(a != b for a, b in zip(dirs, dirs[1:])), str(dirs))


def test_zigzag_costs_confirmation_lag_and_it_grows_with_theta():
    """Задержка подтверждения — не мелочь: она растёт с порогом.

    Это и есть плата за уверенность в развороте, и правило входа
    обязано платить её, а не брать вершину задним числом.
    """
    x = saw([0.20, 0.02, 0.22, 0.01], step=0.002)
    lag = {}
    for th in (0.02, 0.06):
        piv = W.zigzag(x, theta=th)
        lag[th] = np.median([ic - ip for ip, ic, _ in piv]) if piv else np.nan
    check("задержка растёт с порогом", lag[0.06] > lag[0.02], str(lag))


def test_gap_breaks_the_wave():
    """Через разрыв записи волна не продолжается."""
    a = saw([0.10, 0.02], step=0.005)
    b = saw([0.10, 0.02], step=0.005) + 0.50
    x = np.concatenate([a, np.full(W.MAX_GAP + 3, np.nan), b])
    piv = W.zigzag(x, theta=0.03)
    edge = len(a) + W.MAX_GAP + 3
    span = [(ip, ic) for ip, ic, _ in piv if ip < len(a) <= ic]
    check("ни одна нога не перешагивает дыру", not span, str(span))
    check("после дыры волны считаются заново",
          any(ip >= edge for ip, _, _ in piv), str(piv))


def test_leg_ratio_is_what_a_trader_would_measure():
    """Коэффициент отката — отношение ноги к предыдущей, карандашом."""
    x = saw([0.10, 0.04, 0.14], step=0.005)     # ноги 0.10, 0.06, 0.10
    piv = W.zigzag(x, theta=0.03)
    lg = W.legs(x, piv)
    check("ног не меньше двух", len(lg) >= 2, str(len(lg)))
    r = lg[1]["ratio"]
    check("откат 0.06/0.10 ≈ 0.6", abs(r - 0.6) < 0.06, f"{r:.3f}")
    check("у первой ноги отношения нет",
          not np.isfinite(lg[0]["ratio"]))


def test_fib_shares_count_what_they_say():
    """Доли Фибоначчи считаются по объявленной полосе, а не на глаз."""
    r = [0.382, 0.39, 0.5, 0.62, 0.9, np.nan]
    s = W.fib_shares(r, band=0.02)
    check("пропуски не идут в знаменатель", s["n"] == 5, str(s["n"]))
    check("0.382 ловит два значения из пяти",
          abs(s[0.382] - 0.4) < 1e-9, str(s[0.382]))
    check("0.618 ловит одно", abs(s[0.618] - 0.2) < 1e-9, str(s[0.618]))
    check("0.786 не ловит ничего", s[0.786] == 0.0, str(s[0.786]))


def test_surrogate_keeps_the_values_and_the_gaps():
    """Суррогат — те же приращения и та же дырявость, другой порядок."""
    rng = np.random.default_rng(7)
    d = rng.normal(size=500)
    d[[10, 11, 300]] = np.nan
    s = W.block_bootstrap(d, block=24, rng=np.random.default_rng(1))
    check("пропуски на тех же местах",
          np.array_equal(np.isfinite(d), np.isfinite(s)))
    check("значения взяты из оригинала",
          set(np.round(s[np.isfinite(s)], 12))
          <= set(np.round(d[np.isfinite(d)], 12)))
    check("порядок изменён",
          not np.allclose(d[np.isfinite(d)], s[np.isfinite(s)]))


def test_frozen_path_is_not_a_shape():
    """Замороженный ряд не даёт формы — пропуск, а не единичный вектор.

    Ловушка S1 в новом костюме: у мёртвого инструмента σ пути равна
    дрожанию последнего знака, и деление на неё раздуло бы округление в
    форму, идеально повторяющуюся по всему универсуму.
    """
    live = np.log(100 + np.cumsum(np.random.default_rng(3)
                                  .normal(0, 0.5, 49)))
    dead = np.log(np.full(49, 100.0))
    # Дрожание берётся в один базисный пункт, а не в микродолю: путь
    # мельче точности float32 схлопывается в ТОЧНО постоянный, и его
    # ловит проверка на нулевую длину, а не пол. Первая версия этой
    # фикстуры была именно такой — отрицательный контроль на снятый пол
    # её не уронил, потому что она не исполняла ту дорогу.
    tick = np.log(100 * (1 + np.array([0, 1e-4] * 24 + [0],
                                      dtype=np.float64)))
    # А путь чуть ЖИРНЕЕ пола обязан формой быть: пол, отвергающий всё
    # мелкое, был бы не полом, а фильтром волатильности.
    thin = np.log(100 * (1 + np.array([0, 2e-3] * 24 + [0],
                                      dtype=np.float64)))
    Z, ok = W.znorm(np.vstack([live, dead, tick, thin]))
    check("живой путь — форма", bool(ok[0]))
    check("мёртвый ряд формой не является", not bool(ok[1]))
    check("дрожание в базисный пункт формой не является", not bool(ok[2]))
    check("путь чуть выше пола формой является", bool(ok[3]))
    check("у не-формы строка пропусков",
          bool(np.isnan(Z[1]).all() and np.isnan(Z[2]).all()))


def test_shape_ignores_level_and_scale():
    """Одна форма на другом уровне и в другом масштабе — та же форма."""
    base = np.cumsum(np.random.default_rng(5).normal(0, 0.01, 49))
    Z, ok = W.znorm(np.vstack([base, base * 3.0 + 7.0, -base]))
    check("все три — формы", bool(ok.all()))
    check("масштаб и уровень сняты",
          abs(float(Z[0] @ Z[1]) - 1.0) < 1e-5, str(float(Z[0] @ Z[1])))
    check("зеркальная форма — не та же",
          abs(float(Z[0] @ Z[2]) + 1.0) < 1e-5, str(float(Z[0] @ Z[2])))


def test_planted_motif_is_found_first():
    """Подсаженная форма находится первым соседом со сходством около 1."""
    rng = np.random.default_rng(11)
    pool_raw = rng.normal(0, 0.01, (500, 25)).cumsum(axis=1)
    q_raw = pool_raw[123] * 2.5 + 4.0            # та же форма, иной масштаб
    P, _ = W.znorm(pool_raw)
    Q, _ = W.znorm(q_raw[None, :])
    idx, sim = W.top_neighbours(Q, P, k=5)
    check("подсаженная форма — первый сосед", int(idx[0, 0]) == 123,
          str(idx[0, :3]))
    check("сходство около единицы", sim[0, 0] > 0.999, str(sim[0, 0]))
    check("соседи упорядочены по убыванию сходства",
          bool(np.all(np.diff(sim[0]) <= 1e-6)), str(sim[0]))


def test_block_size_does_not_change_the_answer():
    """Ускорение, меняющее числа, есть другая мера."""
    rng = np.random.default_rng(13)
    P, _ = W.znorm(rng.normal(0, 0.01, (400, 20)).cumsum(axis=1))
    Q, _ = W.znorm(rng.normal(0, 0.01, (97, 20)).cumsum(axis=1))
    a = W.top_neighbours(Q, P, k=7, block=3)
    b = W.top_neighbours(Q, P, k=7, block=4096)
    check("индексы соседей совпадают", np.array_equal(a[0], b[0]))
    check("сходства совпадают бит в бит", np.array_equal(a[1], b[1]))


def test_forbidden_pool_never_shows_up():
    """Запрещённый сосед не берётся — на нём и держится причинность.

    Через `forbid` зонд убирает соседей из того же времени: у них
    будущее одно и то же (рынок), и предсказание выродилось бы в
    подсматривание.
    """
    rng = np.random.default_rng(17)
    P, _ = W.znorm(rng.normal(0, 0.01, (200, 16)).cumsum(axis=1))
    Q = P[:20].copy()                       # каждый запрос лежит в пуле
    ban = np.zeros((20, 200), dtype=bool)
    ban[np.arange(20), np.arange(20)] = True
    idx, sim = W.top_neighbours(Q, P, k=3, forbid=lambda rows: ban[rows])
    check("сам себя соседом не берёт",
          not any(int(idx[i, 0]) == i for i in range(20)),
          str(idx[:5, 0]))
    check("сходство при этом ниже единицы",
          bool(np.nanmax(sim[:, 0]) < 0.999), str(float(np.nanmax(sim[:, 0]))))


def test_spearman_handles_ties_and_short_rows():
    """Ранговая связь: ничья не даёт порядка, короткая строка — не мера."""
    check("монотонная связь даёт единицу",
          abs(W.spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-12)
    check("обратная связь даёт минус единицу",
          abs(W.spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-12)
    check("сплошная ничья меры не даёт",
          not np.isfinite(W.spearman([1, 1, 1, 1], [1, 2, 3, 4])))
    check("двух пар мало", not np.isfinite(W.spearman([1, 2], [2, 1])))
    check("пропуски выброшены, а не занулены",
          abs(W.spearman([1, 2, np.nan, 4], [1, 2, 99, 4]) - 1.0) < 1e-12)


def main():
    tests = (
        test_zigzag_is_causal,
        test_zigzag_costs_confirmation_lag_and_it_grows_with_theta,
        test_gap_breaks_the_wave,
        test_leg_ratio_is_what_a_trader_would_measure,
        test_fib_shares_count_what_they_say,
        test_surrogate_keeps_the_values_and_the_gaps,
        test_frozen_path_is_not_a_shape,
        test_shape_ignores_level_and_scale,
        test_planted_motif_is_found_first,
        test_block_size_does_not_change_the_answer,
        test_forbidden_pool_never_shows_up,
        test_spearman_handles_ties_and_short_rows,
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
