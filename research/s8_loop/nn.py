#!/usr/bin/env python3
"""
Нейросеть на numpy — «AI-рука» турнира моделей (спека 08, объявлена
до окна вердикта; испытаний в вердикте становится два).

Та же честность, что у бустинга: гиперпараметры зафиксированы до
прогона и осями не являются; нормировка — строго по обучающей выборке
(скалер на будущем — та же утечка, что форвардное окно R2); пропуск —
не затирка: значение заменяется медианой обучения, а рядом встаёт флаг
«данных не было» — сеть видит пропуск пропуском, как деревья видят
NaN-корзину.

Важность признаков у сети — сумма |весов| первого слоя по входу
(значение и его флаг складываются). Мера грубее, чем gain деревьев,
и на странице подписана как «вес входа», а не как вклад.
"""

import numpy as np

LAYERS = (64, 32)
LR = 1e-3
EPOCHS = 30
BATCH = 4096
L2 = 1e-5


class NN:
    def __init__(self, ws, bs, mu, sd, med, base):
        self.ws, self.bs = ws, bs
        self.mu, self.sd, self.med = mu, sd, med
        self.base = base
        w = np.abs(self.ws[0])                 # (2F, h)
        f = len(self.med)
        self.importance = w[:f].sum(axis=1) + w[f:].sum(axis=1)

    def _prep(self, x):
        miss = ~np.isfinite(x)
        xi = np.where(miss, self.med[None, :], x)
        z = (xi - self.mu) / self.sd
        return np.hstack([z, miss.astype(np.float64)])

    def predict(self, x):
        a = self._prep(x)
        for w, b in zip(self.ws[:-1], self.bs[:-1]):
            a = np.maximum(a @ w + b, 0.0)
        return (a @ self.ws[-1] + self.bs[-1]).ravel() + self.base


def fit(x, y, seed, epochs=EPOCHS):
    ok = np.isfinite(y)
    x, y = x[ok], y[ok]
    med = np.nanmedian(x, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    miss = ~np.isfinite(x)
    xi = np.where(miss, med[None, :], x)
    mu = xi.mean(axis=0)
    sd = xi.std(axis=0)
    sd[sd == 0] = 1.0
    z = np.hstack([(xi - mu) / sd, miss.astype(np.float64)])
    base = float(y.mean())
    yc = y - base

    rng = np.random.default_rng(seed)
    sizes = [z.shape[1], *LAYERS, 1]
    ws = [rng.normal(0, np.sqrt(2.0 / sizes[i]),
                     (sizes[i], sizes[i + 1])) for i in range(len(sizes) - 1)]
    bs = [np.zeros(s) for s in sizes[1:]]
    mw = [np.zeros_like(w) for w in ws]
    vw = [np.zeros_like(w) for w in ws]
    mb = [np.zeros_like(b) for b in bs]
    vb = [np.zeros_like(b) for b in bs]
    b1, b2, eps, t = 0.9, 0.999, 1e-8, 0

    n = len(yc)
    for _ in range(epochs):
        order = rng.permutation(n)
        for s0 in range(0, n, BATCH):
            idx = order[s0:s0 + BATCH]
            a = z[idx]
            acts = [a]
            for w, b in zip(ws[:-1], bs[:-1]):
                a = np.maximum(a @ w + b, 0.0)
                acts.append(a)
            out = (a @ ws[-1] + bs[-1]).ravel()
            g = (out - yc[idx])[:, None] / len(idx)
            grads_w, grads_b = [], []
            d = g
            for li in range(len(ws) - 1, -1, -1):
                grads_w.insert(0, acts[li].T @ d + L2 * ws[li])
                grads_b.insert(0, d.sum(axis=0))
                if li:
                    d = (d @ ws[li].T) * (acts[li] > 0)
            t += 1
            for li in range(len(ws)):
                for g_, m_, v_, p_ in ((grads_w[li], mw, vw, ws),
                                       (grads_b[li], mb, vb, bs)):
                    m_[li] = b1 * m_[li] + (1 - b1) * g_
                    v_[li] = b2 * v_[li] + (1 - b2) * g_ ** 2
                    mh = m_[li] / (1 - b1 ** t)
                    vh = v_[li] / (1 - b2 ** t)
                    p_[li] -= LR * mh / (np.sqrt(vh) + eps)
    return NN(ws, bs, mu, sd, med, base)
