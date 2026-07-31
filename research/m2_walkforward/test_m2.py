#!/usr/bin/env python3
"""
Тесты M2. Главных два, и оба про то, чего в результате не видно:
модель не смеет видеть будущее (walk-forward честен вплоть до границы
`s + h < T`), а нуль 3 обязан быть воспроизводим (зёрна закреплены
числом — урок R3 про солёный хеш).

    python3 research/m2_walkforward/test_m2.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gbm                                                  # noqa: E402
import wf                                                   # noqa: E402

FAILED = []
rng = np.random.default_rng(7)


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


# ---------- GBM ----------

def test_gbm_learns_signal():
    n = 4000
    x = rng.normal(0, 1, (n, 5))
    y = 2.0 * x[:, 0] - 1.0 * x[:, 3] + rng.normal(0, 0.5, n)
    m = gbm.fit(x[:3000], y[:3000], seed=1, n_trees=60)
    p = m.predict(x[3000:])
    c = np.corrcoef(p, y[3000:])[0, 1]
    check(f"модель учит сигнал (корр. на отложенных {c:.2f})", c > 0.8,
          str(c))
    imp = m.importance
    check("важность сосредоточена на настоящих признаках",
          imp[0] + imp[3] > 0.9 * imp.sum(), str(imp))


def test_gbm_on_noise_is_flat():
    n = 3000
    x = rng.normal(0, 1, (n, 5))
    y = rng.normal(0, 1, n)
    m = gbm.fit(x[:2000], y[:2000], seed=2, n_trees=60)
    p = m.predict(x[2000:])
    c = np.corrcoef(p, y[2000:])[0, 1]
    check(f"на шуме модель бессильна (|корр.| {abs(c):.3f})", abs(c) < 0.1,
          str(c))


def test_gbm_nan_is_information():
    # У строк с пропуском другой уровень цели: модель обязана уметь
    # отделить их разрезом, а не получать подмешанными к малым значениям.
    n = 3000
    x = rng.normal(0, 1, (n, 3))
    miss = rng.random(n) < 0.4
    x[miss, 0] = np.nan
    y = np.where(miss, 3.0, -1.0) + rng.normal(0, 0.3, n)
    m = gbm.fit(x, y, seed=3, n_trees=40)
    p = m.predict(x)
    gap = p[miss].mean() - p[~miss].mean()
    check(f"пропуск отделён разрезом (зазор {gap:.1f})", gap > 3.0,
          str(gap))


def test_gbm_deterministic():
    n = 1000
    x = rng.normal(0, 1, (n, 4))
    y = x[:, 1] + rng.normal(0, 0.5, n)
    p1 = gbm.fit(x, y, seed=5, n_trees=20).predict(x)
    p2 = gbm.fit(x, y, seed=5, n_trees=20).predict(x)
    p3 = gbm.fit(x, y, seed=6, n_trees=20).predict(x)
    check("одно зерно — бит в бит", np.array_equal(p1, p2))
    check("другое зерно — другая модель", not np.array_equal(p1, p3))


def test_binning_edges_from_training_only():
    x = np.array([[0.0], [1.0], [2.0], [3.0]])
    e = gbm.bin_edges(x)
    codes = gbm.bin_apply(np.array([[-100.0], [100.0], [np.nan]]), e)
    check("значения вне обучающего диапазона не ломают корзины",
          codes[0, 0] >= 1 and codes[1, 0] >= 1 and codes[2, 0] == 0,
          str(codes.ravel()))


# ---------- ранги и IC ----------

def test_rankdata_ties():
    r = wf.rankdata(np.array([10.0, 20.0, 20.0, 30.0]))
    check("ничьи получают средний ранг", np.allclose(r, [1, 2.5, 2.5, 4]),
          str(r))


def test_spearman_known():
    a = np.array([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    check("монотонная связь — IC 1", abs(wf.spearman(a, a ** 3) - 1) < 1e-12)
    check("антимонотонная — IC −1", abs(wf.spearman(a, -a) + 1) < 1e-12)
    check("мало пар — NaN", np.isnan(wf.spearman(a[:5], a[:5])))


# ---------- зёрна ----------

def test_seeds_pinned_by_number():
    check("fit_seed(3, 7) = 20560738",
          wf.fit_seed(3, 7) == 20_560_738, str(wf.fit_seed(3, 7)))
    check("null3_seed(5, 2) = 75260733",
          wf.null3_seed(5, 2) == 75_260_733, str(wf.null3_seed(5, 2)))


def test_shuffle_within_sections():
    day_idx = np.array([0, 0, 0, 1, 1, 1, 1])
    y = np.array([1.0, 2, 3, 10, 20, 30, 40])
    slices = wf.day_slices(day_idx)
    s1 = wf.shuffle_within_sections(y, slices, 42)
    s2 = wf.shuffle_within_sections(y, slices, 42)
    s3 = wf.shuffle_within_sections(y, slices, 43)
    check("мультимножество сечения сохранено",
          sorted(s1[:3]) == [1, 2, 3] and sorted(s1[3:]) == [10, 20, 30, 40],
          str(s1))
    check("одно зерно — та же перестановка", np.array_equal(s1, s2))
    check("другое зерно — другая", not np.array_equal(s1, s3))


def test_shuffle_global():
    y = np.array([1.0, 2, np.nan, 4, 5, 6, 7, 8])
    g1 = wf.shuffle_global(y, 42)
    g2 = wf.shuffle_global(y, 42)
    check("глобальная перестановка сохраняет мультимножество и NaN",
          np.isnan(g1[2]) and sorted(g1[np.isfinite(g1)]) ==
          [1, 2, 4, 5, 6, 7, 8], str(g1))
    check("глобальная детерминирована", np.array_equal(g1, g2,
                                                       equal_nan=True))


# ---------- walk-forward ----------

def _tiny_market(n_days=120, n_assets=30, seed=11):
    r = np.random.default_rng(seed)
    day_idx = np.repeat(np.arange(n_days), n_assets)
    day_ord = day_idx + 738000
    x = r.normal(0, 1, (n_days * n_assets, 4))
    # сигнал: признак 2 предсказывает форвард
    y = 0.5 * x[:, 2] + r.normal(0, 1.0, len(day_idx))
    return x, y, day_ord, wf.day_slices(day_ord)


class _Lin:
    """Крохотная детерминированная «модель» для тестов каркаса —
    среднее целей обучения плюс признак. Ровно то, что нужно, чтобы
    утечка была видна: сдвиг целей обучения сдвигает предсказание."""

    def __init__(self, shift):
        self.shift = shift

    def predict(self, x):
        return x[:, 2] + self.shift


def _lin_fit(xt, yt, fit_idx):
    return _Lin(float(yt.mean()))


def test_walkforward_future_cannot_touch_past():
    x, y, day_ord, slices = _tiny_market()
    h = 5
    eval_idx = [i for i, (o, _, _) in enumerate(slices) if o >= 738060]
    pred_a, _ = wf.run_cell(x, y, day_ord, slices, eval_idx, h, 1, _lin_fit)

    # Портим цели РОВНО одного сечения s*. Его форвард кончается в
    # s*+h, значит первое обучение, которому он доступен, стоит на
    # s*+h+1: до этой даты — совпадение бит в бит, после — обязано
    # разойтись. Вторая половина и есть негативный контроль, а первая
    # ловит в том числе ошибку границы на один день (s + h <= T).
    s_star = 738070
    y_b = y.copy()
    y_b[day_ord == s_star] += 1000.0
    pred_b, _ = wf.run_cell(x, y_b, day_ord, slices, eval_idx, h, 1,
                            _lin_fit)
    fin = np.isfinite(pred_a)
    before = fin & (day_ord <= s_star + h)
    after = fin & (day_ord > s_star + h)
    check("цель не видна обучению до конца своего форварда",
          np.array_equal(pred_a[before], pred_b[before]))
    check("тест кусается: после конца форварда модель другая",
          not np.array_equal(pred_a[after], pred_b[after]))

    # Будущие признаки не трогают прошлые предсказания.
    x_c = x.copy()
    x_c[day_ord >= 738090] *= -1.0
    pred_c, _ = wf.run_cell(x_c, y, day_ord, slices, eval_idx, h, 1,
                            _lin_fit)
    past = fin & (day_ord < 738090)
    check("будущие признаки не трогают прошлое",
          np.array_equal(pred_a[past], pred_c[past]))


def test_training_excludes_unfinished_forwards():
    # Модель, обученная в день T, не видела сечений с s + h >= T:
    # цель сечения T−h закончится только в T, и её подмена не смеет
    # менять обучение дня T.
    x, y, day_ord, slices = _tiny_market()
    h = 5
    seen = {}

    def spy_fit(xt, yt, fit_idx):
        seen[fit_idx] = len(yt)
        return _Lin(float(yt.mean()))

    eval_idx = [i for i, (o, _, _) in enumerate(slices) if o >= 738060]
    wf.run_cell(x, y, day_ord, slices, eval_idx, h, None, spy_fit)
    # статическая рука: одна тренировка, строк ровно столько, сколько
    # сечений с ординалом < 738060 − h... то есть 55 дней по 30 строк
    check("обучение статической руки видит ровно завершённые форварды",
          seen == {0: 55 * 30}, str(seen))


def test_fit_schedule():
    ords = [100, 101, 102, 103, 110, 111, 130]
    check("статическая — одно обучение",
          wf.fit_schedule(ords, None) == [0])
    check("ежедневная — каждое сечение",
          wf.fit_schedule(ords, 1) == list(range(7)))
    check("недельная — по календарю, не по номеру",
          wf.fit_schedule(ords, 7) == [0, 4, 6],
          str(wf.fit_schedule(ords, 7)))


def test_single_arm_walkforward():
    # Признак 2 — настоящий сигнал; рука обязана выбрать его по
    # прошлому и дать положительный IC на оценке.
    x, y, day_ord, slices = _tiny_market(n_days=200, n_assets=40)
    ic = wf.ic_by_day(x, y, slices)
    day_ords = [s[0] for s in slices]
    eval_idx = [i for i, o in enumerate(day_ords) if o >= 738100]
    ics, chosen = wf.single_feature_arm(ic, day_ords, eval_idx, 5, 30)
    check("рука выбрала настоящий признак со знаком плюс",
          set(np.unique(chosen)) == {3}, str(np.unique(chosen)))
    check(f"IC руки положителен ({np.nanmedian(ics):.3f})",
          np.nanmedian(ics) > 0.1, str(np.nanmedian(ics)))


def test_nonoverlap():
    check("непересекающиеся сечения — каждое h-е",
          wf.nonoverlap(list(range(20)), 5) == [0, 5, 10, 15])


def main():
    print("модель")
    test_gbm_learns_signal()
    test_gbm_on_noise_is_flat()
    test_gbm_nan_is_information()
    test_gbm_deterministic()
    test_binning_edges_from_training_only()
    print("ранги и IC")
    test_rankdata_ties()
    test_spearman_known()
    print("зёрна")
    test_seeds_pinned_by_number()
    test_shuffle_within_sections()
    test_shuffle_global()
    print("walk-forward")
    test_walkforward_future_cannot_touch_past()
    test_training_excludes_unfinished_forwards()
    test_fit_schedule()
    test_single_arm_walkforward()
    test_nonoverlap()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
