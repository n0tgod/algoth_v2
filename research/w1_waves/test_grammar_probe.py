#!/usr/bin/env python3
"""Проверки прогона грамматики.

Две обязательные стороны. Порог зигзага фиксируется ДО измеряемого
куска — порог, знающий будущее, раздал бы разогнавшимся символам
широкие пороги задним числом. И вердиктная фраза выводится ИЗ ЧИСЕЛ
свода: проза, написанная под ожидаемый результат, однажды уже
противоречила собственной таблице отчёта.
"""

import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import grammar as G                                        # noqa: E402
import grammar_probe as GP                                 # noqa: E402
from test_waves import check, FAILED                       # noqa: E402


class Cfg:
    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(GP, k)
            setattr(GP, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(GP, k, v)


def test_theta_is_fixed_before_the_measured_region():
    """Порог — из первых 60 суток; будущее его не трогает."""
    rng = np.random.default_rng(3)
    x = np.cumsum(rng.normal(0, 0.01, 6000))
    th1, start1 = GP.own_theta(x)
    check("порог посчитан", th1 is not None and th1 > 0, str(th1))
    y = x.copy()
    y[3000:] = y[3000:] * 40.0            # будущее взбесилось
    th2, start2 = GP.own_theta(y)
    check("будущее порога не меняет", th1 == th2 and start1 == start2,
          f"{th1} → {th2}")
    z = x.copy()
    z[:1000] = z[:1000] * 40.0            # разогревные сутки другие
    th3, _ = GP.own_theta(z)
    check("разогрев порог меняет", th3 != th1, f"{th1} → {th3}")
    check("короткому ряду порога нет",
          GP.own_theta(x[:2000])[0] is None)


def mk(**over):
    """Свод-фикстура. Умолчание — «факт неотличим от суррогата»."""
    d = {"windows": 5000, "rule2": 0.9, "rule3": 0.8, "rule4": 0.5,
         "all3": 0.4, "trunc5": 0.3, "extended": 0.2,
         "long_w1": 0.33, "long_w3": 0.34, "long_w5": 0.33,
         "r31@1.0": 0.05, f"r31@{G.GOLDEN}": 0.04, "r31@2.618": 0.02,
         "r51@0.618": 0.05, "r51@1.0": 0.05, f"r51@{G.GOLDEN}": 0.03,
         "alt_depth": 0.05, "alt_time": 0.05, "alt_n": 5000,
         "c_freq": 0.02, "cont_med": 0.0, "cont_n": 300,
         "follow_valid": 0.4, "follow_not": 0.5, "n_follow_valid": 900,
         "n_r31": 5000, "n_r51": 5000}
    d.update(over)
    return d


def elliott(base):
    """Свод, отличающийся от базы в предсказанную Эллиоттом сторону."""
    return mk(all3=base["all3"] + 0.1, trunc5=base["trunc5"] - 0.1,
              extended=base["extended"] + 0.1,
              long_w3=base["long_w3"] + 0.1,
              alt_depth=base["alt_depth"] - 0.1,
              alt_time=base["alt_time"] - 0.1,
              **{f"r31@{G.GOLDEN}": base[f"r31@{G.GOLDEN}"] + 0.02,
                 "r51@0.618": base["r51@0.618"] + 0.02},
              c_freq=base["c_freq"] + 0.05,
              cont_med=base["cont_med"] + 0.1)


def _report(res, sub, knn):
    d = tempfile.mkdtemp()
    try:
        p = GP.write_report(os.path.join(d, "w2.md"), res, sub, knn,
                            {"when": "т", "start": "a", "end": "b",
                             "symbols": 9, "used": 9})
        return open(p, encoding="utf-8").read()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_verdict_counts_come_from_the_numbers():
    """Подтверждённые закономерности считаются, а не пишутся прозой."""
    base = mk()
    flat_sub = {"real": {"motive": [3] * 100, "corr": [3] * 100},
                "surr": {"motive": [3] * 100, "corr": [3] * 100}}
    flat_knn = {(m, k): (0.0, 0.0, 9000) for m in GP.KNN_THETAS
                for k in ("real", "surr")}
    res0 = {(m, k): mk() for m in GP.THETAS for k in ("real", "surr")}
    t0 = _report(res0, flat_sub, flat_knn)
    check("рынок без структуры — 0 из 12",
          "подтверждается 0 из 12" in t0, t0[-500:])
    check("нулевой итог назван словами",
          "не найдено" in t0)
    check("ни одна строка свода не подтверждена",
          t0.count("| подтверждается |") == 0,
          str(t0.count("| подтверждается |")))

    res1 = {(m, "real"): elliott(base) for m in GP.THETAS}
    res1.update({(m, "surr"): mk() for m in GP.THETAS})
    good_sub = {"real": {"motive": [5] * 100, "corr": [3] * 100},
                "surr": {"motive": [4] * 100, "corr": [4] * 100}}
    good_knn = {(m, "real"): (0.10, 0.00, 9000) for m in GP.KNN_THETAS}
    good_knn.update({(m, "surr"): (0.00, 0.00, 9000)
                     for m in GP.KNN_THETAS})
    t1 = _report(res1, good_sub, good_knn)
    check("эллиоттовский рынок — 12 из 12",
          "подтверждается 12 из 12" in t1, t1[-500:])
    # Вердикты в СТРОКАХ обязаны сходиться с итогом: колонка, ставшая
    # литералом, лгала бы при честном счётчике — первый отрицательный
    # контроль прошёл мимо именно так.
    check("каждая строка свода подтверждена (12 ячеек)",
          t1.count("| подтверждается |") == 12,
          str(t1.count("| подтверждается |")))
    check("положительный итог не называет теорию доказанной",
          "спека с порогами, а не вывод" in t1)
    check("оговорка про геометрию зигзага стоит на странице",
          "собственная геометрия" in t1)
    check("оговорка про счёт стоит на странице",
          "неопровержимой" in t1)


def test_probe_runs_end_to_end_on_random_walks():
    """Сквозная дорога: случайные блуждания, отчёт написан, публикация
    обеих сторон."""
    rng = np.random.default_rng(11)
    n_sym, n_h = 6, 4200
    L = np.cumsum(rng.normal(0, 0.01, (n_sym, n_h)),
                  axis=1).astype(np.float32)
    said = []
    old_load, old_pub, old_out = GP.P.load_prices, GP.Z.publish, GP.OUT
    d = tempfile.mkdtemp()
    try:
        GP.P.load_prices = lambda *a, **k: L
        GP.Z.publish = lambda m: said.append(m)
        GP.OUT = os.path.join(d, "out")
        with Cfg(WARM_DIFFS=600, MIN_MEAS_H=1200, BOOT=2):
            GP.main(["--symbols", ",".join(f"S{i}USDT"
                                           for i in range(n_sym)),
                     "--start", "2025-01-01", "--end", "2025-06-25",
                     "--tag", "t", "--skip-knn", "--no-publish"])
            check("отчёт написан в созданный прогоном каталог",
                  os.path.exists(os.path.join(GP.OUT, "W2-grammar-t.md")))
            check("с ключом публикации нет", not said, str(said))
            GP.main(["--symbols", ",".join(f"S{i}USDT"
                                           for i in range(n_sym)),
                     "--start", "2025-01-01", "--end", "2025-06-25",
                     "--tag", "t", "--skip-knn"])
            check("без ключа публикация случилась", len(said) == 1)
        t = open(os.path.join(GP.OUT, "W2-grammar-t.md"),
                 encoding="utf-8").read()
        check("свод в отчёте есть", "Свод" in t and "итог" in t)
        check("пропущенный поиск назван не мерившимся, а не «нет»",
              "не мерилось" in t and "из 11" in t, t[-700:])
        check("причина пропуска названа словами",
              "ключом пропуска" in t)
        check("таблицы порогов написаны",
              t.count("## Порог") == len(GP.THETAS),
              str(t.count("## Порог")))
    finally:
        GP.P.load_prices, GP.Z.publish, GP.OUT = old_load, old_pub, old_out
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = (
        test_theta_is_fixed_before_the_measured_region,
        test_verdict_counts_come_from_the_numbers,
        test_probe_runs_end_to_end_on_random_walks,
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
