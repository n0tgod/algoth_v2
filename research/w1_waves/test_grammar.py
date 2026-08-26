#!/usr/bin/env python3
"""Проверки ядра грамматики волн.

Три обязательные стороны, без которых мера выглядела бы исправной,
считая не то:

* **хрестоматийный импульс проходит все правила, и каждая подделка
  ломает ровно своё** — правило, которое ломается чужой подделкой,
  не отделено от соседей;
* **зеркало**: нисходящий импульс обязан давать те же ответы, что
  восходящий, — правило с зашитым знаком ловило бы только бычьи окна
  и молча пропускало медвежьи;
* **подсаженная грамматика находится поиском по структуре, а нуль на
  ней — нет**: без этой пары «грамматики нет» неотличимо от «мера
  сломана».
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import grammar as G                                        # noqa: E402
import waves as W                                          # noqa: E402
from test_waves import check, saw, FAILED                  # noqa: E402

THETA = 0.03


def build(sizes, pre=(0.06, 0.0), tail=0.05, step=0.005):
    """Пила: разгонная пара вершин, затем ноги заданных размеров.

    Разгонная пара нужна, потому что первый подъём ряда ногой не
    является — у него нет предыдущей вершины; хвост подтверждает
    последний разворот.
    """
    peaks = list(pre)
    lvl, sgn = peaks[-1], +1
    for s in sizes:
        lvl += sgn * s
        peaks.append(lvl)
        sgn = -sgn
    peaks.append(lvl - sgn * tail * (-1))
    return saw(peaks, step)


def legs_of(sizes, **kw):
    x = build(sizes, **kw)
    return x, W.legs(x, W.zigzag(x, THETA), max_gap=W.MAX_GAP)


def find_impulse(lg, sizes, tol=0.01):
    """Окно, чьи ноги совпали с заданными размерами.

    Брать «первое окно с восходящей ноги» нельзя: зигзаг подтверждает
    стартовую точку ряда как дно, разгонный подъём тоже становится
    ногой, и первое окно начинается с него — первая версия этих
    проверок мерила не тот отрезок и падала на верном ядре.
    """
    for _, w in G.windows(lg):
        if len(w) == len(sizes) and all(
                abs(w[j]["size"] - sizes[j]) < tol
                for j in range(len(sizes))):
            return w
    return None


def test_textbook_impulse_passes_every_rule():
    """Хрестоматийный импульс: все правила да, растяжения и усечения нет."""
    sizes = [0.10, 0.04, 0.16, 0.05, 0.08]
    _, lg = legs_of(sizes)
    w = find_impulse(lg, sizes)
    check("окно импульса собралось", w is not None, str(len(lg)))
    if w is None:
        return
    st = G.impulse_stats(w)
    check("правило 2 выполнено", st["rule2"])
    check("правило 3 выполнено", st["rule3"])
    check("правило 4 выполнено", st["rule4"])
    check("окно признано импульсом", G.valid_impulse(st))
    check("пятая не усечена", not st["trunc5"])
    check("длиннейшая — третья", st["longest"] == 1, str(st["longest"]))
    check("растяжения нет (0.16 < 1.618×0.10)", not st["extended"])
    check("глубина второй — 0.4", abs(st["depth2"] - 0.4) < 0.05,
          str(st["depth2"]))
    check("отношение 3/1 — 1.6", abs(st["r31"] - 1.6) < 0.1,
          str(st["r31"]))


def test_each_forgery_breaks_exactly_its_rule():
    """Каждая подделка ломает своё правило — и оно названо поимённо."""
    sz = [0.10, 0.12, 0.16, 0.05, 0.08]               # вторая глубже первой
    _, lg = legs_of(sz)
    w = find_impulse(lg, sz)
    check("глубокая вторая ломает правило 2",
          w is not None and not G.impulse_stats(w)["rule2"])

    # Все ноги обязаны быть крупнее порога зигзага: нога мельче θ не
    # существует вовсе, и первая версия фикстуры (0.02, 0.01) молча
    # проверяла другое окно.
    sz = [0.12, 0.035, 0.09, 0.04, 0.10]              # третья короче всех
    _, lg = legs_of(sz)
    w = find_impulse(lg, sz)
    st = G.impulse_stats(w)
    check("короткая третья ломает правило 3", not st["rule3"])
    check("правила 2 и 4 при этом целы", st["rule2"] and st["rule4"],
          str((st["rule2"], st["rule4"])))

    sz = [0.10, 0.08, 0.09, 0.08, 0.07]               # 4-я в зоне 1-й
    _, lg = legs_of(sz)
    w = find_impulse(lg, sz)
    st = G.impulse_stats(w)
    check("перекрытие ломает правило 4", not st["rule4"])
    check("усечённая пятая увидена", st["trunc5"])


def test_mirror_gives_the_same_answers():
    """Нисходящий импульс отвечает так же, как восходящий.

    Правило с зашитым знаком ловило бы только бычьи окна и молча
    пропускало медвежьи — половина рынка осталась бы неизмеренной.
    """
    sz = [0.10, 0.04, 0.16, 0.05, 0.08]
    x, lg = legs_of(sz)
    y = -x
    lg2 = W.legs(y, W.zigzag(y, THETA), max_gap=W.MAX_GAP)
    a = find_impulse(lg, sz)
    b = find_impulse(lg2, sz)
    check("зеркальное окно нашлось и оно нисходящее",
          b is not None and b[0]["dir"] < 0)
    sa, sb = G.impulse_stats(a), G.impulse_stats(b)
    same = all(sa[k] == sb[k] for k in
               ("rule2", "rule3", "rule4", "trunc5", "longest",
                "extended"))
    check("булевы ответы зеркальны", same,
          str({k: (sa[k], sb[k]) for k in sa if sa[k] != sb.get(k)}))
    check("глубины зеркальны", abs(sa["depth2"] - sb["depth2"]) < 1e-9)


def test_window_across_a_seam_does_not_exist():
    """Окно через шов (пропущенную пару ног) не собирается."""
    a = build([0.10, 0.04, 0.16])
    b = build([0.09, 0.05, 0.12]) + 0.4
    x = np.concatenate([a, np.full(W.MAX_GAP + 4, np.nan), b])
    lg = W.legs(x, W.zigzag(x, THETA), max_gap=W.MAX_GAP)
    edge = len(a)
    bad = [(i, w) for i, w in G.windows(lg, k=3)
           if w[0]["i_from"] < edge <= w[-1]["i_to"]]
    check("ни одно окно не пересекает шов", not bad,
          str([(w[0]["i_from"], w[-1]["i_to"]) for _, w in bad]))
    check("окна по обе стороны шва есть",
          len(G.windows(lg, k=3)) >= 2, str(len(G.windows(lg, k=3))))


def test_near_share_band_is_relative():
    """Полоса отношений относительная: у 2.618 она шире, чем у 0.618."""
    s, n = G.near_share([1.60, 1.70, 2.60, 0.62, np.nan], 1.618)
    check("пропуск не в знаменателе", n == 4, str(n))
    check("1.60 внутри ±5 %, 1.70 снаружи", abs(s - 0.25) < 1e-9, str(s))
    s2, _ = G.near_share([2.60], 2.618)
    check("2.60 у 2.618 внутри (полоса относительная)", s2 == 1.0)


def test_contraction_is_found_and_its_aftermath_is_signed_by_pre_leg():
    """Сжатие находится, исход подписан докоррекционной ногой.

    Пред-нога взята МЕНЬШЕ первой сжимающейся намеренно: если бы она
    была крупнее, бегов из четырёх убывающих стало бы два внахлёст —
    первая версия фикстуры была именно такой, и «лишний» второй бег
    нашло ядро, а не проверка.
    """
    sz = [0.10, 0.30, 0.24, 0.18, 0.13, 0.14, 0.20]
    _, lg = legs_of(sz, tail=0.06)
    n_hit, n_win, cont = G.contractions(lg)
    check("сжатие найдено ровно одно", n_hit == 1, str(n_hit))
    check("пригодные окна посчитаны", n_win >= 1, str(n_win))
    check("исход — продолжение в долях пред-ноги (+0.6)",
          len(cont) == 1 and abs(cont[0] - 0.6) < 0.05, str(cont))
    _, lg2 = legs_of([0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22])
    check("растущие ноги сжатием не являются",
          G.contractions(lg2)[0] == 0)


def test_subdivision_counts_inner_pivots_only():
    """Дробление: вершина на границе — граница, а не внутренность."""
    lg = [{"i_from": 10, "i_to": 50}]
    fine = [(10, 11, 1), (20, 21, -1), (30, 31, 1), (50, 51, -1)]
    got = G.subdivision(lg, fine)
    check("две внутренние вершины — три подноги", got == [3], str(got))
    check("пустая внутренность — одна поднога",
          G.subdivision([{"i_from": 10, "i_to": 12}], fine) == [1])


def test_leg_queries_need_a_contiguous_chain():
    """Запрос строится только на цепочке встык, и числа — те самые."""
    def chain(sizes, broken=False):
        lg, pos = [], 0
        for j, s in enumerate(sizes):
            i0 = pos
            pos += 10
            if broken and j == 3:
                i0 += 1                     # шов: начало не равно концу
            lg.append({"i_from": i0, "i_to": pos, "size": s,
                       "px_from": 0.0, "px_to": 0.0, "dir": 1 - 2 * (j % 2),
                       "bars": 10})
        return lg

    F, Y, C = G.leg_queries(chain([1, 2, 4, 8, 16, 32]))
    check("одна цепочка — один запрос", len(F) == 1, str(len(F)))
    check("признаки — лог-отношения (log 2)",
          np.allclose(F[0], np.log(2)), str(F[0]))
    check("цель — отношение следующей ноги",
          abs(Y[0] - np.log(2)) < 1e-12, str(Y))
    check("момент — конец последней ИЗВЕСТНОЙ ноги", C[0] == 50, str(C))
    F2, _, _ = G.leg_queries(chain([1, 2, 4, 8, 16, 32], broken=True))
    check("цепочка со швом запроса не даёт", len(F2) == 0, str(len(F2)))


def test_planted_grammar_is_found_and_null_is_blind_to_it():
    """Подсаженная грамматика находится, нуль на ней слеп.

    Без этой пары «грамматики нет» неотличимо от «мера сломана»: и
    пустая загрузка, и перепутанный знак дают тот же ноль.
    """
    rng = np.random.default_rng(5)
    n = 3000
    F = rng.normal(0, 1, (n, 4))
    Y = F[:, 3] * 2.0 + rng.normal(0, 0.05, n)
    C = np.arange(n) * 1000
    S = np.arange(n) % 7
    ic, ic0, m = G.knn_ic(F, Y, C, S, k=20, guard=720,
                          rng=np.random.default_rng(1))
    check("запросы посчитаны", m > 2000, str(m))
    check("подсаженная грамматика найдена", ic > 0.8, f"{ic:+.3f}")
    check("нуль случайных соседей слеп", abs(ic0) < 0.1, f"{ic0:+.3f}")
    Ysh = Y.copy()
    np.random.default_rng(2).shuffle(Ysh)
    ic_sh, ic0_sh, _ = G.knn_ic(F, Ysh, C, S, k=20, guard=720,
                                rng=np.random.default_rng(1))
    check("на перемешанных целях находка исчезает",
          abs(ic_sh) < 0.1, f"{ic_sh:+.3f}")


def test_knn_guard_excludes_own_symbol_and_own_time():
    """Свой символ и своё время в соседи не идут — проверяется прямо."""
    rng = np.random.default_rng(9)
    n = 400
    F = rng.normal(0, 1, (n, 4))
    Y = rng.normal(0, 1, n)
    C = np.zeros(n, dtype=np.int64)          # все в одну секунду
    S = np.arange(n) % 5
    ic, ic0, m = G.knn_ic(F, Y, C, S, k=10, guard=720,
                          rng=np.random.default_rng(1))
    check("одновременный пул не даёт ни одного запроса", m == 0, str(m))
    C2 = np.arange(n) * 10_000
    S2 = np.zeros(n, dtype=np.int64)          # все один символ
    _, _, m2 = G.knn_ic(F, Y, C2, S2, k=10, guard=720,
                        rng=np.random.default_rng(1))
    check("свой символ не даёт ни одного запроса", m2 == 0, str(m2))


def main():
    tests = (
        test_textbook_impulse_passes_every_rule,
        test_each_forgery_breaks_exactly_its_rule,
        test_mirror_gives_the_same_answers,
        test_window_across_a_seam_does_not_exist,
        test_near_share_band_is_relative,
        test_contraction_is_found_and_its_aftermath_is_signed_by_pre_leg,
        test_subdivision_counts_inner_pivots_only,
        test_leg_queries_need_a_contiguous_chain,
        test_planted_grammar_is_found_and_null_is_blind_to_it,
        test_knn_guard_excludes_own_symbol_and_own_time,
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
