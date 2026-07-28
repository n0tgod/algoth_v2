#!/usr/bin/env python3
"""Проверки статистики A4.

Здесь проверяется не «код не падает», а что тест отвечает правильно на
случаи с известным ответом: построенная коинтегрированная пара должна
проходить, две независимые случайные прогулки — нет, известный
полураспад должен восстанавливаться.

Отдельно проверяется Бенджамини–Хохберг: наивная реализация «оставить
все p_i ≤ i/m·alpha» даёт другой, меньший набор, и эта ошибка молчалива.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coint as C  # noqa: E402
import series as S  # noqa: E402


def ou_pair(n=2000, beta=1.5, phi=0.98, seed=0, noise=0.002):
    """Пара, у которой спред — авторегрессия первого порядка.

    ln P_A = beta * ln P_B + spread, где ln P_B — случайная прогулка,
    а spread возвращается к нулю с коэффициентом phi. По построению
    такая пара коинтегрирована.
    """
    rng = np.random.default_rng(seed)
    lb = np.cumsum(rng.normal(0, 0.01, n)) + 5.0
    s = np.zeros(n)
    for i in range(1, n):
        s[i] = phi * s[i - 1] + rng.normal(0, noise)
    la = beta * lb + s
    return np.exp(la), np.exp(lb)


def two_walks(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    a = np.cumsum(rng.normal(0, 0.01, n)) + 5.0
    b = np.cumsum(rng.normal(0, 0.01, n)) + 5.0
    return np.exp(a), np.exp(b)


class KnownAnswers(unittest.TestCase):
    def test_cointegrated_pair_is_found(self):
        pa, pb = ou_pair(seed=1)
        r = C.test_pair(pa, pb)
        self.assertLess(r["p"], 0.01)
        self.assertAlmostEqual(r["beta"], 1.5, places=1)

    def test_independent_walks_are_not(self):
        """Две независимые прогулки не должны проходить систематически."""
        rejects = 0
        for seed in range(20):
            pa, pb = two_walks(seed=seed)
            if C.test_pair(pa, pb)["p"] < 0.05:
                rejects += 1
        # При верном тесте ожидается около 5 % ложных срабатываний.
        self.assertLessEqual(rejects, 3, f"ложных срабатываний {rejects}/20")

    def test_half_life_recovers_known_value(self):
        """Определение — спека 01 §2.4: Δs = λ·s + ε, half_life = −ln2/λ.

        То есть λ = phi − 1, а не ln(phi). Для phi близких к единице эти
        два определения совпадают, при phi = 0.9 расходятся на 5 %, и
        источником истины здесь служит спека, а не привычка.
        """
        from scipy.signal import lfilter
        for phi in (0.90, 0.98, 0.995):
            rng = np.random.default_rng(7)
            # Длина выборки берётся под phi: у медленного возврата
            # стандартная ошибка λ относительно самого λ падает как
            # sqrt((1+phi)/((1-phi)·n)), и на общей длине проверка
            # ловила бы шум оценки, а не ошибку в формуле.
            n = int(2000 / (1.0 - phi) ** 2)
            s = lfilter([1.0], [1.0, -phi], rng.normal(0, 0.01, n))
            want = -np.log(2) / (phi - 1.0)
            got = C.half_life(s)
            self.assertLess(abs(got - want) / want, 0.03,
                            f"phi={phi}: {got:.1f} против {want:.1f}")

    def test_explosive_spread_has_no_half_life(self):
        """Расходящийся спред: λ ≥ 0, полураспада не существует."""
        s = 1.01 ** np.arange(500)
        self.assertEqual(C.half_life(s), np.inf)

    def test_random_walk_half_life_is_useless(self):
        """У прогулки λ оценивается около нуля, полураспад — порядка
        длины выборки, то есть заведомо вне горизонта удержания 1–5 дней.
        """
        rng = np.random.default_rng(3)
        s = np.cumsum(rng.normal(0, 1.0, 5000))
        self.assertGreater(C.half_life(s), 100)

    def test_beta_matches_least_squares(self):
        rng = np.random.default_rng(11)
        x = rng.normal(0, 1, 500)
        y = 2.5 * x + 3.0 + rng.normal(0, 0.1, 500)
        beta, alpha = C.ols_beta(y, x)
        want = np.polyfit(x, y, 1)
        self.assertAlmostEqual(beta, want[0], places=8)
        self.assertAlmostEqual(alpha, want[1], places=8)

    def test_too_short_series_rejected(self):
        pa, pb = ou_pair(n=C.MIN_OBS - 1)
        self.assertIsNone(C.test_pair(pa, pb))


class FDR(unittest.TestCase):
    def test_step_up_not_naive_threshold(self):
        """Ключевое отличие процедуры: отвергается всё до наибольшего k.

        При m=4 и alpha=0.10 пороги равны 0.025, 0.05, 0.075, 0.100.
        У p = 0.06 собственный порог (0.05) не проходит, но наибольшее
        проходящее k равно четвёртому, поэтому отвергается всё до него
        включительно. Наивная проверка «каждое p против своего порога»
        потеряла бы именно эту гипотезу.
        """
        p = [0.001, 0.06, 0.07, 0.099]
        got = C.benjamini_hochberg(p, 0.10)
        self.assertEqual(sorted(got.tolist()), [0, 1, 2, 3])
        naive = [i for i, v in enumerate(sorted(p))
                 if v <= (i + 1) / 4 * 0.10]
        self.assertEqual(len(naive), 3)

    def test_nothing_passes(self):
        got = C.benjamini_hochberg([0.5, 0.6, 0.99], 0.10)
        self.assertEqual(len(got), 0)

    def test_all_pass(self):
        got = C.benjamini_hochberg([0.001, 0.002, 0.003], 0.10)
        self.assertEqual(len(got), 3)

    def test_false_discovery_rate_is_controlled(self):
        """На чистом шуме доля отобранных не должна превышать alpha."""
        rng = np.random.default_rng(5)
        picked = 0
        trials = 200
        for _ in range(trials):
            p = rng.uniform(0, 1, 500)
            picked += len(C.benjamini_hochberg(p, 0.10))
        self.assertLess(picked / (trials * 500), 0.01)

    def test_matches_brute_force(self):
        rng = np.random.default_rng(9)
        for _ in range(50):
            m = int(rng.integers(1, 60))
            p = rng.beta(0.4, 3.0, m)
            alpha = 0.10
            s = np.sort(p)
            kmax = 0
            for k in range(1, m + 1):
                if s[k - 1] <= k / m * alpha:
                    kmax = k
            want = set(np.nonzero(p <= s[kmax - 1])[0].tolist()) if kmax else set()
            got = set(C.benjamini_hochberg(p, alpha).tolist())
            self.assertEqual(got, want)

    def test_empty_input(self):
        self.assertEqual(len(C.benjamini_hochberg([], 0.10)), 0)


class Resampling(unittest.TestCase):
    def test_bucket_label_and_last_value(self):
        t = np.array([0, 60_000, 120_000, 3_600_000], dtype=np.int64)
        c = np.array([1.0, 2.0, 3.0, 4.0])
        rt, rc = S.resample(t, c, "1h")
        self.assertEqual(rt.tolist(), [0, 3_600_000])
        self.assertEqual(rc.tolist(), [3.0, 4.0])

    def test_gaps_do_not_create_bars(self):
        """Пустой интервал не появляется: бара со сделками там не было."""
        t = np.array([0, 7_200_000], dtype=np.int64)
        c = np.array([1.0, 2.0])
        rt, _ = S.resample(t, c, "1h")
        self.assertEqual(len(rt), 2)

    def test_align_matches_by_timestamp(self):
        ta = np.array([1, 2, 3, 5], dtype=np.int64)
        tb = np.array([2, 3, 4, 5], dtype=np.int64)
        ca = np.array([10.0, 20.0, 30.0, 50.0])
        cb = np.array([2.0, 3.0, 4.0, 5.0])
        t, a, b = S.align((ta, ca), (tb, cb))
        self.assertEqual(t.tolist(), [2, 3, 5])
        self.assertEqual(a.tolist(), [20.0, 30.0, 50.0])
        self.assertEqual(b.tolist(), [2.0, 3.0, 5.0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
