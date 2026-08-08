#!/usr/bin/env python3
"""
M2: градиентный бустинг деревьев на numpy — модель спеки 07 §3.

Своя реализация не из гордости: внешних сервисов у прогона нет, VPS
обязан тянуть обучение сам, и каждая строка, влияющая на числа, должна
быть проверяемой тестом. Чужая библиотека — та же вторая копия
расчётного ядра, только невидимая.

Устройство — гистограммный бустинг:

* Признаки один раз квантуются в корзины, границы берутся по квантилям
  ОБУЧАЮЩЕЙ выборки. Границы, посчитанные по будущему, были бы утечкой
  того же рода, что скалер на будущем (§9 спеки), поэтому `bin_edges`
  зовётся только на обучающих строках, а применение (`bin_apply`)
  разрешено любым.
* Пропуск (NaN) — своя корзина с номером 0. При каждом разрезе пропуск
  пробуется в обе стороны и уходит туда, где выигрыш больше, — модель
  обязана видеть пропуск пропуском (урок A2), а не получать его
  подмешанным к малым значениям. У признаков открытого интереса до
  2024 года пропусков 100 %, и любое другое обращение с ними было бы
  выдумкой.
* Дерево жадное, разрез ищется по гистограммам градиентов; потеря
  квадратичная, значение листа — среднее остатка. Заданный `tau`
  переводит обучение на квантильную потерю (значение листа — квантиль
  остатка): это нужно целям-экстремумам, где условное среднее
  перекрывается в половине случаев и уровнем стопа быть не может.

Гиперпараметры зафиксированы спекой §3 до прогона и осями сетки не
являются: глубина 3, 200 деревьев, шаг 0.05, подвыборка 0.8. Константы
реализации (число корзин, минимум строк в листе) объявлены здесь же и
тоже не крутятся: «захотелось покрутить — это новая итерация».
"""

import numpy as np

DEPTH = 3
N_TREES = 200
LEARNING_RATE = 0.05
SUBSAMPLE = 0.8

N_BINS = 31          # содержательных корзин; код 0 зарезервирован под NaN
MIN_LEAF = 20        # лист мельче этого не создаётся


def bin_edges(x_train, n_bins=N_BINS):
    """Границы корзин по квантилям обучающей выборки, на каждый признак."""
    qs = np.linspace(0.0, 1.0, n_bins + 1)[1:-1]
    edges = []
    for j in range(x_train.shape[1]):
        v = x_train[:, j]
        v = v[np.isfinite(v)]
        edges.append(np.unique(np.quantile(v, qs)) if v.size else
                     np.empty(0))
    return edges


def bin_apply(x, edges):
    """Коды корзин: 0 — пропуск, 1..B — интервалы между границами."""
    n, m = x.shape
    codes = np.zeros((n, m), dtype=np.int16)
    for j in range(m):
        v = x[:, j]
        ok = np.isfinite(v)
        codes[ok, j] = (np.searchsorted(edges[j], v[ok], side="right")
                        .astype(np.int16) + 1)
    return codes


def _histograms(codes_sub, g_sub, n_cats):
    """Суммы градиента и счётчики по корзинам всех признаков разом.

    Один общий bincount вместо цикла по признакам: каждому признаку
    отводится свой диапазон кодов сдвигом j*n_cats. На матрице в сотни
    тысяч строк это и есть почти вся цена обучения.
    """
    n, m = codes_sub.shape
    offs = (np.arange(m, dtype=np.int32) * n_cats)[None, :]
    flat = codes_sub.astype(np.int32) + offs
    flat = flat.ravel()
    w = np.broadcast_to(g_sub[:, None], (n, m)).ravel()
    hg = np.bincount(flat, weights=w, minlength=m * n_cats)
    hn = np.bincount(flat, minlength=m * n_cats)
    return hg.reshape(m, n_cats), hn.reshape(m, n_cats).astype(np.float64)


def _best_split(hg, hn):
    """Лучший разрез по гистограммам: (признак, порог, NaN-влево, gain).

    Порог t означает «корзины 1..t влево, t+1..B вправо»; пропуск (0)
    отдельно пробуется в обе стороны. Критерий — прирост суммы
    G²/n по детям против родителя (квадратичная потеря).
    """
    m, n_cats = hg.shape
    g_nan, n_nan = hg[:, 0], hn[:, 0]
    cg = np.cumsum(hg[:, 1:], axis=1)          # (m, B) — влево без NaN
    cn = np.cumsum(hn[:, 1:], axis=1)
    g_tot, n_tot = cg[:, -1] + g_nan, cn[:, -1] + n_nan

    best = (-1, -1, True, 0.0)
    parent = np.where(n_tot > 0, g_tot ** 2 / np.maximum(n_tot, 1), 0.0)
    for nan_left in (True, False):
        gl = cg[:, :-1] + (g_nan[:, None] if nan_left else 0.0)
        nl = cn[:, :-1] + (n_nan[:, None] if nan_left else 0.0)
        gr = g_tot[:, None] - gl
        nr = n_tot[:, None] - nl
        ok = (nl >= MIN_LEAF) & (nr >= MIN_LEAF)
        with np.errstate(all="ignore"):
            gain = (gl ** 2 / np.maximum(nl, 1) + gr ** 2 / np.maximum(nr, 1)
                    - parent[:, None])
        gain = np.where(ok, gain, -np.inf)
        j, t = np.unravel_index(np.argmax(gain), gain.shape)
        if gain[j, t] > best[3]:
            best = (int(j), int(t) + 1, nan_left, float(gain[j, t]))
    return best


def _go_left(col, thr, nan_left):
    return np.where(col == 0, nan_left, col <= thr)


def _grow(codes, g, idx, depth, importance, leaf=None):
    """Дерево по псевдоостаткам `g`.

    `leaf` — чем считается значение листа. У квадратичной потери это
    среднее самого `g` (умолчание), у квантильной — квантиль ОСТАТКА,
    а не среднее градиента: градиент там равен ±константе и величины
    шага не несёт. Разрез в обоих случаях ищется по гистограммам `g`.
    """
    if leaf is None:
        def leaf(i):
            return float(g[i].mean())
    if depth >= DEPTH or idx.size < 2 * MIN_LEAF:
        return leaf(idx) if idx.size else 0.0
    hg, hn = _histograms(codes[idx], g[idx], N_BINS + 2)
    j, t, nan_left, gain = _best_split(hg, hn)
    if j < 0:
        return leaf(idx)
    importance[j] += gain
    m = _go_left(codes[idx, j], t, nan_left)
    return (j, t, nan_left,
            _grow(codes, g, idx[m], depth + 1, importance, leaf),
            _grow(codes, g, idx[~m], depth + 1, importance, leaf))


def _tree_predict(node, codes, idx, out):
    if not isinstance(node, tuple):
        out[idx] = node
        return
    j, t, nan_left, left, right = node
    m = _go_left(codes[idx, j], t, nan_left)
    _tree_predict(left, codes, idx[m], out)
    _tree_predict(right, codes, idx[~m], out)


class GBM:
    """Обученная модель: границы корзин, деревья, базовый уровень."""

    def __init__(self, edges, trees, base, importance):
        self.edges = edges
        self.trees = trees
        self.base = base
        self.importance = importance          # суммарный gain по признакам

    def predict(self, x):
        return self.predict_codes(bin_apply(x, self.edges))

    def predict_codes(self, codes):
        pred = np.full(codes.shape[0], self.base)
        buf = np.empty(codes.shape[0])
        all_idx = np.arange(codes.shape[0])
        for tr in self.trees:
            _tree_predict(tr, codes, all_idx, buf)
            pred += LEARNING_RATE * buf
        return pred


def fit(x, y, seed, n_trees=N_TREES, tau=None):
    """Обучение. `seed` обязателен и выводится вызывающим из номеров —
    урок R3: зерно, которое нельзя воспроизвести, делает нуль-модель
    непроверяемой.

    `tau` — уровень квантиля. `None` (умолчание) даёт прежнюю
    квадратичную потерю, то есть предсказание УСЛОВНОГО СРЕДНЕГО, и
    числа обязаны совпасть с прежними до бита. Заданный `tau`
    переводит обучение на квантильную (pinball) потерю: модель
    предсказывает уровень, ниже которого цель оказывается в доле
    `tau` случаев.

    Разница существенна там, где цель — экстремум пути. Максимальный
    ход ПРОТИВ позиции есть максимум, и его условное среднее по
    построению перекрывается примерно в половине случаев: стоп,
    поставленный на среднем, срабатывает на медианной сделке. Уровень
    же нужен такой, за который цена заходит РЕДКО, — а это квантиль,
    и получить его из квадратичной потери нельзя ничем.
    """
    ok = np.isfinite(y)
    x, y = x[ok], y[ok]
    edges = bin_edges(x)
    codes = bin_apply(x, edges)
    rng = np.random.default_rng(seed)
    n = len(y)
    base = float(y.mean() if tau is None else np.quantile(y, tau))
    pred = np.full(n, base)
    trees = []
    importance = np.zeros(x.shape[1])
    buf = np.empty(n)
    all_idx = np.arange(n)
    for _ in range(n_trees):
        sub = np.flatnonzero(rng.random(n) < SUBSAMPLE)
        res = y - pred
        if tau is None:
            g, leaf = res, None
        else:
            # Псевдоостаток квантильной потери: +tau там, где цель выше
            # предсказания, −(1−tau) где ниже. Шаг листа берётся
            # отдельной строкой поиска — квантилем остатка внутри листа.
            g = np.where(res > 0, tau, tau - 1.0)

            def leaf(i, _r=res):
                return float(np.quantile(_r[i], tau)) if i.size else 0.0
        tr = _grow(codes, g, sub, 0, importance, leaf)
        trees.append(tr)
        _tree_predict(tr, codes, all_idx, buf)
        pred += LEARNING_RATE * buf
    return GBM(edges, trees, base, importance)
