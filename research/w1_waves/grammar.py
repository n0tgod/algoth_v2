#!/usr/bin/env python3
"""W2 — грамматика волн: ядро мер. Ни загрузки, ни отчёта — их держит
`grammar_probe.py`.

Зачем это после W1. W1 ответил про ОДИНОЧНЫЕ ноги: откаты не садятся
на уровни Фибоначчи, пара соседних ног связи сверх геометрии зигзага
не несёт. Владелец справедливо заметил, что волновая теория утверждает
больше: ноги собираются в СТРУКТУРЫ. Вот её структурные утверждения,
и каждое проверяемо без разметки счёта — скользящим окном из пяти
подряд идущих ног правило либо выполнено, либо нет, и выбора между
допустимыми счётами не существует:

1. **Импульс из пяти волн с тремя жёсткими правилами**: волна 2 не
   перекрывает волну 1 целиком; волна 3 не короче обеих движущих;
   волна 4 не заходит на ценовую территорию волны 1. Если рынок
   «предпочитает» импульсную грамматику, доля окон, где выполнены все
   три, обязана быть выше, чем у суррогата с той же геометрией зигзага.
2. **Растяжение**: одна из движущих волн заметно длиннее остальных,
   чаще всего третья.
3. **Усечённая пятая — редкость**: волна 5 обычно обновляет экстремум
   третьей.
4. **Чередование**: глубокая вторая — плоская четвёртая, и наоборот
   (глубина здесь — измеримая замена «формы» коррекции; это прокси,
   и это сказано, а не спрятано).
5. **Отношения между волнами**: 3-я к 1-й и 5-я к 1-й садятся на
   1.0 / 1.618 / 2.618 и 0.618 / 1.0 / 1.618.
6. **Дробление (фрактальность)**: движущие волны делятся на пять
   подволн, коррекционные — на три. Это сердце теории.
7. **Сжатие (треугольник)**: серия убывающих ног, после которой ход
   продолжает докоррекционное направление.
8. **Структура ног предсказывает следующую** — обобщение всего сразу:
   если у последовательности ног есть грамматика, соседи по структуре
   последних пяти ног обязаны предсказывать следующую лучше случайных.

Каждая мера сравнивается с блочным суррогатом: у самого зигзага есть
собственная геометрия (W1 намерил у суррогата связь соседних ног
+0.11 из ничего), и без сравнения она читалась бы как структура.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import waves as W                                          # noqa: E402

GOLDEN = 1.618
IMPULSE_K = 5                     # ног в окне импульса
CONTRACT_K = 4                    # подряд убывающих ног — «сжатие»


def contiguous(w):
    """Ноги идут встык: конец каждой — начало следующей.

    Плоский список ног не говорит, где зигзаг начинался заново после
    дыры; окно, собранное через такой шов, было бы склейкой двух
    кусков — тот же класс дефекта, что нога через дыру.
    """
    return all(w[j + 1]["i_from"] == w[j]["i_to"]
               for j in range(len(w) - 1))


def windows(lg, k=IMPULSE_K):
    """Скользящие окна из k подряд идущих ног: (индекс первой, окно)."""
    out = []
    for i in range(len(lg) - k + 1):
        w = lg[i:i + k]
        if contiguous(w):
            out.append((i, w))
    return out


def impulse_stats(w):
    """Правила импульса и родственные величины окна из пяти ног.

    Ориентацию задаёт первая нога: окно, начинающееся с восходящей,
    проверяется как восходящий импульс, с нисходящей — зеркально. Все
    сравнения симметричны: размеры беззнаковы, ценовые разности
    умножаются на направление.
    """
    s = w[0]["dir"]
    u1, d2, u3, d4, u5 = (leg["size"] for leg in w)
    p1, p3, p4, p5 = (w[j]["px_to"] for j in (0, 2, 3, 4))
    mx = max(u1, u3, u5)
    second = sorted((u1, u3, u5))[1]
    return {
        # Правило 2: коррекция не перекрывает волну 1 целиком.
        "rule2": bool(d2 <= u1),
        # Правило 3: волна 3 не короче ОБЕИХ движущих.
        "rule3": not (u3 < u1 and u3 < u5),
        # Правило 4: конец волны 4 не заходит на территорию волны 1.
        "rule4": bool(s * (p4 - p1) > 0),
        # Усечённая пятая: не обновила экстремум третьей.
        "trunc5": not (s * (p5 - p3) > 0),
        "longest": int(0 if mx == u1 else (1 if mx == u3 else 2)),
        "extended": bool(second > 0 and mx >= GOLDEN * second),
        "depth2": (d2 / u1) if u1 > 0 else float("nan"),
        "depth4": (d4 / u3) if u3 > 0 else float("nan"),
        "t2": (w[1]["bars"] / w[0]["bars"]) if w[0]["bars"]
        else float("nan"),
        "t4": (w[3]["bars"] / w[2]["bars"]) if w[2]["bars"]
        else float("nan"),
        "r31": (u3 / u1) if u1 > 0 else float("nan"),
        "r51": (u5 / u1) if u1 > 0 else float("nan"),
    }


def valid_impulse(st):
    return bool(st["rule2"] and st["rule3"] and st["rule4"])


def near_share(vals, target, half=0.05):
    """Доля значений в ОТНОСИТЕЛЬНОЙ полосе ±half вокруг цели.

    Полоса относительная, а не абсолютная: у цели 2.618 абсолютные
    ±0.02 несравнимо теснее, чем у 0.618, и таблица сравнивала бы
    разные вопросы под одним именем.
    """
    v = np.asarray([x for x in vals if np.isfinite(x) and x > 0])
    if len(v) == 0:
        return float("nan"), 0
    return float(np.mean(np.abs(v / target - 1.0) <= half)), int(len(v))


def contractions(lg, k=CONTRACT_K):
    """Сжатия: k подряд строго убывающих ног, с окружением для исхода.

    Возвращает (сжатий, пригодных окон, исходы). Исход — ход двух ног
    ПОСЛЕ сжатия в направлении ноги ПЕРЕД ним, в долях её размера:
    утверждение треугольника — после сжатия движение продолжает
    докоррекционное направление, то есть исход положителен. Направление
    следующей ноги мерить нельзя вовсе: ноги зигзага чередуются по
    построению, и «направление пробоя» задано последней ногой сжатия.
    """
    n_hit, n_win, cont = 0, 0, []
    for i in range(1, len(lg) - k - 1):
        seg = lg[i - 1:i + k + 2]
        if len(seg) < k + 3 or not contiguous(seg):
            continue
        n_win += 1
        sz = [v["size"] for v in seg[1:1 + k]]
        if not all(sz[j] > sz[j + 1] for j in range(k - 1)):
            continue
        n_hit += 1
        pre, a, b = seg[0], seg[k + 1], seg[k + 2]
        if pre["size"] > 0:
            cont.append(pre["dir"] * (b["px_to"] - a["px_from"])
                        / pre["size"])
    return n_hit, n_win, cont


def subdivision(coarse_lg, fine_piv):
    """Дробление: сколько мелких ног внутри каждой крупной.

    Счёт — число мелких вершин СТРОГО внутри крупной ноги плюс один.
    Вершина на границе принадлежит границе: крупная и мелкая вершины в
    одной точке — одна и та же вершина, и считать её внутренней значило
    бы дарить каждой ноге лишнюю подволну.
    """
    fp = np.asarray([p[0] for p in fine_piv], dtype=np.int64)
    out = []
    for leg in coarse_lg:
        n = int(((fp > leg["i_from"]) & (fp < leg["i_to"])).sum())
        out.append(n + 1)
    return out


def leg_queries(lg, need=IMPULSE_K):
    """Сырьё для поиска по структуре: признаки, цель, момент.

    Признаки — четыре лог-отношения подряд идущих ног (масштаб символа
    сокращается сам: отношение безразмерно). Цель — лог-отношение
    СЛЕДУЮЩЕЙ ноги к последней известной. Момент — конец последней
    ИЗВЕСТНОЙ ноги: цель реализуется после него.
    """
    F, Y, C = [], [], []
    for i in range(need - 1, len(lg) - 1):
        w = lg[i - need + 1:i + 2]
        if not contiguous(w):
            continue
        sz = [v["size"] for v in w]
        if any(s <= 0 for s in sz):
            continue
        F.append([float(np.log(sz[j + 1] / sz[j]))
                  for j in range(need - 1)])
        Y.append(float(np.log(sz[-1] / sz[-2])))
        C.append(int(w[-2]["i_to"]))
    return F, Y, C


def knn_ic(F, Y, C, S, k=50, guard=720, rng=None, block=128,
           max_q=None):
    """Предсказывает ли структура последних ног следующую ногу.

    Соседи — ЧУЖИЕ символы и время дальше `guard` часов В ОБЕ стороны:
    одновременные ноги делят один рынок, и совпадение их будущего было
    бы подсматриванием, а не грамматикой. Пул двусторонний по времени —
    мера отвечает «есть ли грамматика», а не «торгуема ли она», и это
    ограничение называется в отчёте словами.

    Возвращает (IC прогона, IC случайных соседей, число запросов).
    Нуль — те же запросы, k СЛУЧАЙНЫХ разрешённых соседей: если похожие
    по структуре не лучше случайных, грамматики нет.
    """
    F = np.asarray(F, dtype=np.float32)
    Y = np.asarray(Y, dtype=np.float64)
    C = np.asarray(C, dtype=np.int64)
    S = np.asarray(S, dtype=np.int64)
    n = len(F)
    if n < k * 4:
        return float("nan"), float("nan"), 0
    rng = rng or np.random.default_rng(0)
    q_idx = np.arange(n)
    if max_q is not None and n > max_q:
        q_idx = np.sort(rng.choice(n, size=max_q, replace=False))
    pn = (F.astype(np.float64) ** 2).sum(axis=1).astype(np.float32)
    pred = np.full(len(q_idx), np.nan)
    pred0 = np.full(len(q_idx), np.nan)
    for a in range(0, len(q_idx), block):
        rows = q_idx[a:a + block]
        q = F[rows]
        d2 = ((q.astype(np.float64) ** 2).sum(axis=1)
              .astype(np.float32)[:, None]
              + pn[None, :] - 2.0 * (q @ F.T))
        bad = (S[rows, None] == S[None, :]) \
            | (np.abs(C[rows, None] - C[None, :]) <= guard)
        d2[bad] = np.inf
        ok = (~bad).sum(axis=1) >= k
        if not ok.any():
            continue
        part = np.argpartition(d2, kth=k - 1, axis=1)[:, :k]
        pv = np.take(Y, part)
        pv[~np.isfinite(np.take_along_axis(d2, part, axis=1))] = np.nan
        sel = np.flatnonzero(ok)
        pred[a + sel] = np.nanmedian(pv[ok], axis=1)
        # Нуль: k случайных из разрешённых — случайный ключ с запретом.
        keys = rng.random(d2.shape, dtype=np.float32)
        keys[bad] = np.inf
        rpart = np.argpartition(keys, kth=k - 1, axis=1)[:, :k]
        rv = np.take(Y, rpart)
        rv[~np.isfinite(np.take_along_axis(keys, rpart, axis=1))] = np.nan
        pred0[a + sel] = np.nanmedian(rv[ok], axis=1)
    yq = Y[q_idx]
    return (W.spearman(pred, yq), W.spearman(pred0, yq),
            int(np.isfinite(pred).sum()))
