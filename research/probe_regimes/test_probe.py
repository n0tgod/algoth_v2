#!/usr/bin/env python3
"""Проверки зонда режимов: мера, нуль и то, что зонд НЕ выдумывает.

Три места, где ошибка была бы невидимой, и на каждое стоит проверка,
дающая при неверной реализации ДРУГОЕ число, а не падение: ранговая
корреляция должна быть настоящей; случайные трети — воспроизводимыми;
и главное — на данных БЕЗ неоднородности зонд обязан показать
превышение около единицы, а на данных С неоднородностью — заметно
больше. Без второй половины он был бы прибором, всегда говорящим «да».

    python3 research/probe_regimes/test_probe.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import probe as P                                            # noqa: E402

FAIL = []


def check(name, ok, extra=""):
    print(("  ok   " if ok else "  ПАДЕНИЕ ") + name
          + ("" if ok else f": {extra}"))
    if not ok:
        FAIL.append(name)


def test_spearman():
    a = np.array([1.0, 2, 3, 4, 5])
    check("совпадающий порядок даёт +1",
          abs(P.spearman(a, a * 3) - 1.0) < 1e-9, str(P.spearman(a, a * 3)))
    check("обратный порядок даёт −1",
          abs(P.spearman(a, -a) + 1.0) < 1e-9, str(P.spearman(a, -a)))
    # Ранговая, а не линейная: монотонное преобразование не меняет.
    check("монотонное преобразование меру не двигает",
          abs(P.spearman(a, np.exp(a)) - 1.0) < 1e-9,
          str(P.spearman(a, np.exp(a))))
    check("постоянный ряд меры не имеет",
          np.isnan(P.spearman(a, np.ones(5))),
          str(P.spearman(a, np.ones(5))))


def test_seed_is_a_number():
    """Зерно выводится ЧИСЛОМ: нуль обязан повторяться между процессами.

    Урок R3: хеш строки солится на процесс, и два прогона одного кода
    на одних данных давали разные нули при комментарии «результат
    воспроизводим».
    """
    a = P._rng(739100).permutation(10)
    b = P._rng(739100).permutation(10)
    c = P._rng(739101).permutation(10)
    check("одно зерно — та же перестановка", (a == b).all(), str(a))
    check("другой день — другая перестановка", not (a == c).all(),
          str(c))


def _matrix(n_days, n_names, hetero):
    """Синтетика. `hetero` — есть ли зависимость навыка от режима.

    Режим кладётся в `vol_ratio`. При `hetero` предсказание совпадает
    с будущим только в ВЕРХНЕЙ трети режима, в остальных это шум; без
    `hetero` навык ровный по всему сечению.
    """
    rng = np.random.default_rng(7)
    day, pred, fwd, vol = [], [], [], []
    for d in range(n_days):
        v = rng.random(n_names)
        f = rng.normal(size=n_names)
        p = rng.normal(size=n_names)
        if hetero:
            top = v > 2.0 / 3.0
            p[top] = f[top] + rng.normal(scale=0.15, size=int(top.sum()))
        else:
            p = f + rng.normal(scale=0.9, size=n_names)
        day.append(np.full(n_names, 739000 + d))
        pred.append(p)
        fwd.append(f)
        vol.append(v)
    cols = {"day": np.concatenate(day),
            "fwd_5": np.concatenate(fwd),
            "vol_ratio": np.concatenate(vol)}
    return cols, np.concatenate(pred)


def test_probe_finds_and_does_not_invent():
    # Без неоднородности зонд обязан показать НУЛЕВЫЕ величины: доля
    # дней с более широким разбросом около половины, лучшая корзина
    # около трети. Это и есть проверка, что прибор не выдумывает.
    cols, pred = _matrix(120, 90, hetero=False)
    rows = P.summarise(P.run(cols, pred, "fwd_5", log=lambda *a: None)[0])
    flat = next(r for r in rows if r["feat"] == "vol_ratio")
    check("на ровном навыке разброс не шире случайного",
          0.35 < flat["wider"] < 0.65,
          f"доля {flat['wider']}, корзины {flat['bins']}")
    check("на ровном навыке лучшая корзина не залипает",
          flat["top_share"] < 0.45, str(flat["best_share"]))

    # С неоднородностью: обе величины уходят от нуля, и указывают на
    # ТУ корзину, где навык заложен, — иначе зонд нашёл бы разброс,
    # но не место.
    cols, pred = _matrix(120, 90, hetero=True)
    rows = P.summarise(P.run(cols, pred, "fwd_5", log=lambda *a: None)[0])
    het = next(r for r in rows if r["feat"] == "vol_ratio")
    check("на неоднородном навыке разброс шире случайного",
          het["wider"] > 0.85, f"доля {het['wider']}")
    check("зонд указывает НА ТУ корзину, где навык заложен",
          het["top_bin"] == 2 and het["top_share"] > 0.85,
          f"корзина {het['top_bin']}, доля {het['top_share']}, "
          f"{het['bins']}")
    # Разброс режима обязан превышать случайный по величине тоже —
    # иначе доля могла бы набраться из ничтожных превышений.
    check("разброс режима крупнее случайного и по величине",
          het["spread_med"] > 2 * het["rand_spread_med"],
          f"{het['spread_med']} против {het['rand_spread_med']}")


def test_thin_sections_are_skipped():
    cols, pred = _matrix(40, 12, hetero=False)   # 12 имён < MIN_NAMES
    out, n = P.run(cols, pred, "fwd_5", log=lambda *a: None)
    check("тонкое сечение в замер не идёт", n == 0, str(n))


if __name__ == "__main__":
    test_spearman()
    test_seed_is_a_number()
    test_probe_finds_and_does_not_invent()
    test_thin_sections_are_skipped()
    if FAIL:
        print(f"\nПАДЕНИЙ: {len(FAIL)} — " + "; ".join(FAIL))
        sys.exit(1)
    print("\nвсе проверки прошли")
