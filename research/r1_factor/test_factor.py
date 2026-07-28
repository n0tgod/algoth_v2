#!/usr/bin/env python3
"""Тесты ядра R1 на известных ответах.

Проверяется не «код не падает», а три конкретные вещи, каждая из которых
уже ломала что-нибудь в этом проекте:

- доходность через дыру в ряду не должна становиться наблюдением;
- актив не должен входить в собственную волну;
- замороженный ряд не должен давать оценку.

Запуск: python3 -m unittest discover -s research/r1_factor
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor as F  # noqa: E402

H = F.STEP_MS["1h"]


def grid(n, t0=0):
    return np.arange(t0, t0 + n * H, H, dtype=np.int64)


class PriceGrid(unittest.TestCase):
    def test_missing_bar_becomes_nan(self):
        t = np.array([0, H, 3 * H], dtype=np.int64)   # бара за 2*H нет
        c = np.array([100.0, 101.0, 103.0])
        g, syms, P = F.price_grid({"A": (t, c)}, "1h", 0, 4 * H)
        self.assertEqual(len(g), 4)
        self.assertTrue(np.isnan(P[2, 0]))
        self.assertEqual(P[3, 0], 103.0)

    def test_grid_starts_on_step_boundary(self):
        g, _, _ = F.price_grid({}, "1h", H + 137, 4 * H)
        self.assertEqual(g[0] % H, 0)


class Gaps(unittest.TestCase):
    def test_return_through_gap_is_not_an_observation(self):
        """Главный дефект, ради которого сетка регулярная.

        Цена идёт 100 → 101 → (дыра) → 103. Наблюдений доходности должно
        быть одно (100→101), а не два: 101→103 разделено пропуском, и
        принять его за часовую доходность значит завысить дисперсию.
        """
        t = np.array([0, H, 3 * H], dtype=np.int64)
        c = np.array([100.0, 101.0, 103.0])
        _, _, P = F.price_grid({"A": (t, c)}, "1h", 0, 4 * H)
        R = F.log_returns(P)
        self.assertEqual(int((~np.isnan(R[:, 0])).sum()), 1)
        self.assertAlmostEqual(R[0, 0], np.log(101 / 100), places=12)

    def test_naive_diff_would_have_given_two(self):
        """Контроль самого теста: без сетки дефект действительно есть."""
        c = np.array([100.0, 101.0, 103.0])
        self.assertEqual(len(np.diff(np.log(c))), 2)


class LeaveOneOut(unittest.TestCase):
    def test_own_return_excluded(self):
        R = np.array([[0.01, 0.02, 0.03, 0.04, 0.05, 0.06]])
        f, floo, n = F.market_factor(R, min_assets=2)
        self.assertAlmostEqual(f[0], np.mean(R[0]), places=12)
        # для первого актива — среднее остальных пяти
        self.assertAlmostEqual(floo[0, 0], np.mean(R[0, 1:]), places=12)
        self.assertEqual(int(n[0]), 6)

    def test_missing_asset_does_not_shift_others(self):
        R = np.array([[0.01, np.nan, 0.03, 0.05, 0.07, 0.09]])
        f, floo, n = F.market_factor(R, min_assets=2)
        self.assertEqual(int(n[0]), 5)
        self.assertAlmostEqual(f[0], np.mean([0.01, 0.03, 0.05, 0.07, 0.09]), 12)
        self.assertAlmostEqual(floo[0, 0], np.mean([0.03, 0.05, 0.07, 0.09]), 12)

    def test_thin_bar_is_dropped(self):
        R = np.array([[0.01, 0.02, np.nan, np.nan, np.nan, np.nan]])
        f, floo, _ = F.market_factor(R, min_assets=5)
        self.assertTrue(np.isnan(f[0]))
        self.assertTrue(np.isnan(floo[0, 0]))

    def test_own_inclusion_inflates_beta(self):
        """Смещение, ради которого версия «все, кроме меня» и заведена.

        Двадцать активов — ровно ранние окна A3. Актив, не связанный с
        рынком вовсе, при включении себя в волну получает заметно
        положительную β; при исключении — ноль.
        """
        rng = np.random.default_rng(0)
        R = rng.normal(0, 0.01, size=(2000, 20))
        f, floo, _ = F.market_factor(R, min_assets=5)
        b_in = F.regress(R[:, 0], f)[0]
        b_out = F.regress(R[:, 0], floo[:, 0])[0]
        self.assertGreater(b_in, 0.5)          # смещение примерно 1/20 → β≈1
        self.assertLess(abs(b_out), 0.15)


class KnownBeta(unittest.TestCase):
    def test_recovers_beta_and_r2(self):
        rng = np.random.default_rng(1)
        n = 5000
        f = rng.normal(0, 0.02, n)
        y = 1.7 * f + rng.normal(0, 0.002, n)
        b, r2, k = F.regress(y, f)
        self.assertAlmostEqual(b, 1.7, places=2)
        self.assertGreater(r2, 0.98)
        self.assertEqual(k, n)

    def test_independent_series_gives_zero_r2(self):
        rng = np.random.default_rng(2)
        b, r2, _ = F.regress(rng.normal(size=5000), rng.normal(size=5000))
        self.assertLess(abs(b), 0.05)
        self.assertLess(r2, 0.01)

    def test_intercept_absorbs_drift(self):
        """Снос актива не должен уезжать в наклон."""
        rng = np.random.default_rng(3)
        f = rng.normal(0, 0.02, 5000)
        y = 0.5 * f + 0.001                     # чистый снос сверху
        b, _, _ = F.regress(y, f)
        self.assertAlmostEqual(b, 0.5, places=6)


class ScaleOfBeta(unittest.TestCase):
    """β меряется относительно НАБЛЮДАЕМОЙ волны, а не скрытого фактора.

    Это не дефект, но выглядит как дефект: на синтетике с известными β
    оценка выходит систематически ниже истины. Причина в том, что
    равновзвешенное среднее доходностей равно `среднее(β) × скрытый
    фактор`, то есть несёт в себе масштаб универсума. Хеджируемся мы об
    наблюдаемое, поэтому определение правильное; тест нужен, чтобы
    следующий читатель не «починил» работающее.
    """

    def setUp(self):
        rng = np.random.default_rng(11)
        self.n, self.k = 2160, 120
        f = rng.normal(0, 0.02, self.n)
        self.true = rng.uniform(0.6, 1.6, self.k)
        R = self.true * f[:, None] + rng.normal(0, 0.015, (self.n, self.k))
        _, floo, _ = F.market_factor(R)
        self.fit = F.betas(R, floo)
        self.est = np.array([b for _, b, _, _ in self.fit])

    def test_estimate_equals_truth_divided_by_mean_beta(self):
        tr = self.true[[j for j, *_ in self.fit]]
        got = float(np.median(self.est / tr))
        want = 1.0 / float(self.true.mean())
        self.assertAlmostEqual(got, want, places=2)

    def test_mean_beta_is_one_by_construction(self):
        """Свободная проверка корректности, годная и на живых данных.

        Каждый актив входит в волну с весом 1/n, поэтому среднее β по
        сечению обязано выходить около единицы независимо от рынка.
        Заметное отклонение означает ошибку в расчёте, а не свойство
        рынка, — на реальном прогоне это первое, что надо смотреть.
        """
        self.assertAlmostEqual(float(self.est.mean()), 1.0, places=2)


class FrozenSeries(unittest.TestCase):
    def test_frozen_asset_yields_no_estimate(self):
        """Замороженный ряд A2: цена не меняется, доходность тождественно
        ноль. Дисперсии нет, оценивать нечего — regress обязан вернуть
        None, а не β = 0 с R² = 0, которое выглядело бы как наблюдение.
        """
        f = np.random.default_rng(4).normal(0, 0.02, 500)
        self.assertIsNone(F.regress(np.zeros(500), f))

    def test_frozen_asset_skipped_by_betas(self):
        rng = np.random.default_rng(5)
        R = rng.normal(0, 0.01, size=(500, 8))
        R[:, 3] = 0.0                            # заморожен
        _, floo, _ = F.market_factor(R, min_assets=5)
        idx = {j for j, *_ in F.betas(R, floo)}
        self.assertNotIn(3, idx)
        self.assertEqual(len(idx), 7)


class Coverage(unittest.TestCase):
    def test_thin_asset_skipped(self):
        rng = np.random.default_rng(6)
        R = rng.normal(0, 0.01, size=(1000, 8))
        R[300:, 2] = np.nan                      # покрытие 30 %
        _, floo, _ = F.market_factor(R, min_assets=5)
        idx = {j for j, *_ in F.betas(R, floo, min_coverage=0.5)}
        self.assertNotIn(2, idx)


class Residuals(unittest.TestCase):
    def test_residual_is_orthogonal_to_factor(self):
        rng = np.random.default_rng(7)
        R = rng.normal(0, 0.01, size=(3000, 12))
        R += 1.3 * rng.normal(0, 0.02, size=(3000, 1))   # общая волна
        _, floo, _ = F.market_factor(R, min_assets=5)
        fit = F.betas(R, floo)
        E = F.residuals(R, floo, fit)
        for j, *_ in fit[:4]:
            m = ~(np.isnan(E[:, j]) | np.isnan(floo[:, j]))
            c = np.corrcoef(E[m, j], floo[m, j])[0, 1]
            self.assertLess(abs(c), 1e-8)

    def test_frozen_leg_residual_is_minus_beta_f(self):
        """Почему §5.1 спеки 03 называет замороженные ряды угрозой
        первого порядка: если такой актив всё же дойдёт до расчёта
        остатка, его остаток равен ровно −β·F, то есть максимальному
        отклонению от волны при любом её движении.
        """
        rng = np.random.default_rng(8)
        R = rng.normal(0, 0.01, size=(500, 8))
        R += rng.normal(0, 0.02, size=(500, 1))
        _, floo, _ = F.market_factor(R, min_assets=5)
        y = np.zeros(500)
        b = 0.9
        a = y.mean() - b * floo[:, 0].mean()
        e = y - a - b * floo[:, 0]
        self.assertAlmostEqual(float(np.corrcoef(e, floo[:, 0])[0, 1]), -1.0, 6)



class SectorFactor(unittest.TestCase):
    def test_small_group_gives_no_factor(self):
        """Среднее по трём именам — шум, а не фактор. Вычитание такого
        «фактора» добавило бы в остаток чужую случайность."""
        R = np.random.default_rng(20).normal(0, 0.01, (100, 10))
        self.assertIsNone(F.sector_factor(R, [0, 1, 2], min_members=5))

    def test_factor_is_group_mean(self):
        R = np.arange(30.0).reshape(3, 10)
        f, _ = F.sector_factor(R, [0, 1, 2, 3, 4], min_members=5)
        self.assertAlmostEqual(f[0], np.mean(R[0, :5]), places=12)

    def test_loo_excludes_own(self):
        R = np.arange(30.0).reshape(3, 10)
        _, loo = F.sector_factor(R, [0, 1, 2, 3, 4], min_members=5)
        self.assertAlmostEqual(loo[0, 0], np.mean(R[0, 1:5]), places=12)


class PairwiseCovariance(unittest.TestCase):
    def test_matches_plain_covariance_without_gaps(self):
        R = np.random.default_rng(21).normal(0, 0.01, (500, 6))
        C = F.pairwise_cov(R, min_overlap=10)
        ref = np.cov(R, rowvar=False)
        self.assertTrue(np.allclose(C, ref, atol=1e-12))

    def test_gaps_do_not_become_zeros(self):
        """Заполнить пропуск нулём значит утверждать «доходность была
        нулевой» — то самое молчание, выданное за данные, которым
        отличались замороженные ряды A2."""
        rng = np.random.default_rng(22)
        R = rng.normal(0, 0.01, (500, 3))
        R[:250, 2] = np.nan
        C = F.pairwise_cov(R, min_overlap=10)
        # дисперсия столбца с пропусками считается по доступной половине
        self.assertAlmostEqual(C[2, 2], np.var(R[250:, 2], ddof=1), places=10)

    def test_short_overlap_is_unknown_not_zero_correlation(self):
        rng = np.random.default_rng(23)
        R = rng.normal(0, 0.01, (500, 2))
        R[50:, 1] = np.nan
        C = F.pairwise_cov(R, min_overlap=100)
        self.assertEqual(C[0, 1], 0.0)


class Components(unittest.TestCase):
    def test_first_component_of_common_factor_is_the_factor(self):
        """Если весь универсум движется одной волной, первая компонента
        обязана быть примерно равновзвешенной."""
        rng = np.random.default_rng(24)
        f = rng.normal(0, 0.02, 2000)
        R = f[:, None] * np.ones(12) + rng.normal(0, 0.002, (2000, 12))
        W, vals = F.top_components(F.pairwise_cov(R, 10), 3)
        w = W[:, 0]
        self.assertGreater(vals[0], 10 * vals[1])       # доминирует одна
        self.assertLess(w.std() / abs(w.mean()), 0.15)  # веса почти равны

    def test_sign_is_fixed_so_beta_does_not_flip(self):
        """Собственный вектор определён с точностью до знака. Без
        фиксации первая компонента произвольно меняла бы направление от
        окна к окну, а вместе с ней знак β."""
        rng = np.random.default_rng(25)
        f = rng.normal(0, 0.02, 800)
        R = f[:, None] * np.ones(8) + rng.normal(0, 0.002, (800, 8))
        for seed in range(4):
            perm = np.random.default_rng(seed).permutation(8)
            W, _ = F.top_components(F.pairwise_cov(R[:, perm], 10), 1)
            self.assertGreater(W[:, 0].sum(), 0)


class WeightedFactor(unittest.TestCase):
    def test_loo_is_exact_subtraction(self):
        rng = np.random.default_rng(26)
        R = rng.normal(0, 0.01, (50, 6))
        W = rng.normal(size=(6, 2))
        Fm, contrib = F.weighted_factor(R, W)
        for i in (0, 3, 5):
            expect = np.delete(R, i, axis=1) @ np.delete(W, i, axis=0)
            self.assertTrue(np.allclose(Fm - contrib[:, i, :], expect))

    def test_market_weights_reproduce_market_factor(self):
        """Рынок — частный случай той же конструкции с весами 1/n."""
        rng = np.random.default_rng(27)
        R = rng.normal(0, 0.01, (200, 10))
        Fm, _ = F.weighted_factor(R, np.full((10, 1), 0.1))
        ref, _, _ = F.market_factor(R, min_assets=5)
        self.assertTrue(np.allclose(Fm[:, 0], ref, atol=1e-12))


class RegressMulti(unittest.TestCase):
    def test_recovers_known_coefficients(self):
        rng = np.random.default_rng(28)
        n = 4000
        X = rng.normal(0, 0.02, (n, 3))
        y = 1.4 * X[:, 0] - 0.7 * X[:, 1] + 0.3 * X[:, 2] + \
            rng.normal(0, 0.001, n) + 0.005
        b, r2, k = F.regress_multi(y, X)
        self.assertAlmostEqual(b[0], 1.4, places=2)
        self.assertAlmostEqual(b[1], -0.7, places=2)
        self.assertAlmostEqual(b[2], 0.3, places=2)
        self.assertGreater(r2, 0.99)
        self.assertEqual(k, n)

    def test_more_factors_explain_more(self):
        """Смысл ступеней 2 и 3: больше факторов — меньше дисперсии
        остаётся в остатке. Это и есть рычаг итерации 1."""
        rng = np.random.default_rng(29)
        n = 3000
        X = rng.normal(0, 0.02, (n, 3))
        y = X @ np.array([1.0, 0.8, 0.6]) + rng.normal(0, 0.005, n)
        r1 = F.regress_multi(y, X[:, :1])[1]
        r3 = F.regress_multi(y, X)[1]
        self.assertGreater(r3, r1 + 0.2)

    def test_degenerate_input_returns_none(self):
        y = np.zeros(50)
        X = np.random.default_rng(30).normal(size=(50, 2))
        self.assertIsNone(F.regress_multi(y, X))

if __name__ == "__main__":
    unittest.main()
