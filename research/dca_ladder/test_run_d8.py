#!/usr/bin/env python3
"""Проверки замера тейка D8.

Главная — ТОЧКА ОТСЧЁТА: ячейка `e:fav` обязана воспроизвести нынешнее
правило книги (`take_px`) бит в бит. Не воспроизведи она его, вся
таблица сравнивала бы варианты с чем-то, чем книга не торгует, и
выглядела бы при этом исправной.

Запуск из `.venv/bin/python` (тянет numpy).
"""
import importlib
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import ladder as L                                            # noqa: E402
import run_d2 as D2                                           # noqa: E402
import test_run_d3 as T3                                      # noqa: E402
import run_d5 as D5                                           # noqa: E402
import run_d6 as D6                                           # noqa: E402
import run_d8 as D8                                           # noqa: E402
import rules as R                                             # noqa: E402

FLAT_MMR = 0.02


def _look(notl):
    return L.mmr_for_notional([], notl, flat=FLAT_MMR)


def _dip_then_rise(t0=1_700_000_000, pre=1440, low=94.0, top=112.0,
                   post=4800):
    """Ровный рынок, потом провал к `low`, рост до `top` и плато.

    Путь выбран так, чтобы сетка РАЗЛИЧАЛАСЬ по существу: провал берёт
    доливы (ТВХ уезжает вниз), а рост проходит обещание и часть его
    множителей. Хвост тянется дольше срока удержания (72 ч) намеренно:
    иначе позиция, не дошедшая до цели, была бы не «закрыта по сроку», а
    ОБОРВАНА записью, и общая выборка выходила бы пустой.
    """
    # Окно ДО входа обязано дрожать, как живое: у ровно постоянного ряда
    # σ равна нулю, а нулевая σ — это «меры нет», и решение выбрасывается
    # целиком (правило проекта: подставные данные обязаны выглядеть
    # живыми). Дрожание детерминированное, зерна не требует.
    bars = []
    for i in range(pre):
        px = 100.0 + 0.1 * ((i * 7919) % 11 - 5) / 5.0
        bars.append((t0 + i * 60, px, px + 0.05, px - 0.05, px, 1000.0))
    at = t0 + pre * 60
    n_down, n_up = 300, 900
    path = [100.0 - (100.0 - low) * j / (n_down - 1) for j in range(n_down)]
    path += [low + (top - low) * j / (n_up - 1) for j in range(n_up)]
    path += [top + 0.1 * ((j * 7919) % 11 - 5) / 5.0
             for j in range(max(0, post - n_down - n_up))]
    for j, px in enumerate(path):
        bars.append((at + j * 60, px, px + 0.05, px - 0.05, px, 1000.0))
    return bars, at


def _legs(at, n=40, sym="AAAUSDT"):
    out = []
    for i in range(n):
        g = dict(T3._leg(at + (i % 5) * 3600))
        g["sym"] = sym
        g["fwd"] = 40.0 + i
        out.append(g)
    return out


def _with_levels(fn):
    orig = D2.build_levels
    D2.build_levels = lambda w, i: T3.LEVELS
    try:
        return fn()
    finally:
        D2.build_levels = orig


def test_reference_cell_reproduces_the_book_rule():
    """`e:fav` == нынешнее правило книги (`D6.one_position`) бит в бит.

    Один и тот же тейк, посчитанный двумя дорогами, обязан дать один
    исход: иначе у замера своя книга, и сравнивать её ячейки с живой
    нельзя ни по одной мере.
    """
    bars, at = _dip_then_rise()
    ts = [b[0] for b in bars]
    g = T3._leg(at)

    def go():
        a = D6.one_position(g, bars, ts, _look, "depth", R.SURVIVE_MULT)
        b = D8.one_position(g, bars, ts, _look, "depth", R.SURVIVE_MULT)
        return a, b
    a, b = _with_levels(go)
    assert a is not None and b, (a, b)
    ref = b[D8.REF]
    for k in ("exit", "exit_ts", "lev", "depth", "avg"):
        assert a[k] == ref[k], (k, a[k], ref[k])
    assert abs(a["pnl"] - ref["pnl"]) < 1e-12, (a["pnl"], ref["pnl"])
    print(f"ok  точка отсчёта `{D8.REF}` == правило книги: {ref['exit']} "
          f"{ref['pnl']*100:+.2f}%, глубина {ref['depth']}, "
          f"плечо {ref['lev']:.2f}×")


def test_avg_anchor_exits_earlier_and_pays_the_filled_notional():
    """Тейк от ТВХ выходит раньше и платит `нотионал × доля` тождественно."""
    bars, at = _dip_then_rise()
    ts = [b[0] for b in bars]
    o = _with_levels(lambda: D8.one_position(
        T3._leg(at), bars, ts, _look, "depth", R.SURVIVE_MULT))
    e, a = o["e:fav"], o["a:fav"]
    assert a["depth"] > 1, a                 # доливы сработали
    assert a["exit"] == "тейк" and e["exit"] == "тейк", (a, e)
    assert a["exit_ts"] <= e["exit_ts"], (a["exit_ts"], e["exit_ts"])
    want = a["filled"] * a["frac"]
    assert abs(a["pnl"] - want) < 1e-12, (a["pnl"], want)
    print(f"ok  якорь ТВХ выходит раньше ({int((e['exit_ts']-a['exit_ts'])/60)} "
          f"мин) и платит нотионал {a['filled']:.2f}× × {a['frac']*100:.2f} % "
          f"= {a['pnl']*100:+.2f} % (якорь входа {e['pnl']*100:+.2f} %)")


def test_normalised_weights_deploy_the_whole_notional():
    """Диагностическая рука: при одном рунге работает ВЕСЬ нотионал.

    Веса `[0.25]×4` не нормируются, поэтому позиция без лестницы
    вкладывает четверть объявленного нотионала. Рука `n|…` отвечает на
    вопрос, копейки ли это цели или простаивающего капитала.
    """
    bars, at = _dip_then_rise()
    ts = [b[0] for b in bars]
    # уровней нет вовсе → лестница из одной базы
    orig = D2.build_levels
    D2.build_levels = lambda w, i: np.array([])
    try:
        o = D8.one_position(T3._leg(at), bars, ts, _look, "depth",
                            R.SURVIVE_MULT)
    finally:
        D2.build_levels = orig
    base, norm = o["e:fav"], o["n|e:fav"]
    assert base["depth"] == 1 and norm["depth"] == 1, (base, norm)
    assert abs(base["filled"] - 0.25) < 1e-9, base["filled"]
    assert abs(norm["filled"] - 1.0) < 1e-9, norm["filled"]
    assert abs(norm["pnl"] - 4.0 * base["pnl"]) < 1e-9, (norm, base)
    print(f"ok  без лестницы работает {base['filled']:.2f} нотионала против "
          f"{norm['filled']:.2f} у нормированной руки — "
          f"{base['pnl']*100:+.3f} % против {norm['pnl']*100:+.3f} %")


def test_sigma_missing_drops_the_decision_everywhere():
    """σ не измерена — решение не считается НИ ОДНОЙ ячейкой.

    Половина сетки задана в σ имени. Подставив ноль, мы дали бы такому
    имени цель в ноль процентов, то есть мгновенный тейк на входе, — и
    ячейка выглядела бы лучшей в таблице.
    """
    flat = [(1_700_000_000 + i * 60, 50.0, 50.0, 50.0, 50.0, 1000.0)
            for i in range(2000)]          # замороженная котировка: σ = 0
    at = flat[1440][0]
    ts = [b[0] for b in flat]
    o = _with_levels(lambda: D8.one_position(
        T3._leg(at), flat, ts, _look, "depth", R.SURVIVE_MULT))
    assert o is None, o
    print("ok  замороженный ряд (σ = 0) выброшен целиком, а не с нулевой целью")


def test_common_sample_is_one_for_all_cells():
    """Решение, не закрытое хотя бы в одной ячейке, уходит из ВСЕХ."""
    recs = {k: [{"sym": "AAAUSDT", "at": 1.0, "state": "closed"},
                {"sym": "BBBUSDT", "at": 2.0, "state": "closed"}]
            for k in (c[0] for c in D8.CELLS)}
    bad = D8.CELLS[3][0]
    recs[bad] = [dict(recs[bad][0]), dict(recs[bad][1], state="cut")]
    out, n, lost = D8.common_sample(recs, log=lambda *a: None)
    assert n == 1 and lost == 1, (n, lost)
    for k, v in out.items():
        assert [r["sym"] for r in v] == ["AAAUSDT"], (k, v)
    print(f"ok  общая выборка: {n} решение осталось у всех "
          f"{len(out)} ячеек, выброшено {lost}")


def test_run_end_to_end_synthetic():
    """Сквозной прогон: run → отчёт. Дороги отчёта `py_compile` не видит."""
    bars, at = _dip_then_rise()
    up, _ = _dip_then_rise(low=98.0, top=140.0)
    src = T3._Src({"AAAUSDT": bars, "BBBUSDT": up})
    legs = _legs(at, n=30) + _legs(at, n=30, sym="BBBUSDT")
    s = _with_levels(lambda: D8.run(src=src, legs=legs, log=lambda *a: None))
    assert s["positions"] == 60, s["positions"]
    want = len(D8.CELLS) * len(D8.BOOK_RULER) * len(R.DEPOSITS)
    assert len(s["cells"]) == want, (len(s["cells"]), want)
    dep = int(R.DEPOSITS[1])
    ref = s["cells"][f"{D8.REF}|optimal|{dep}"]
    assert ref["taken"] > 0 and ref["pnl_median"] is not None, ref
    assert s["diag"].get("optimal"), s["diag"]
    txt = D8.report(s)
    assert "две копейки" in txt and f"`{D8.REF}`" in txt, txt[:400]
    for k in s["keys"]:
        assert f"`{k}`" in txt, k
    assert "ошибкой R5" in txt, "оговорка про выбор лучшей ячейки потеряна"
    print(f"ok  сквозной прогон: {s['positions']} решений, "
          f"{len(s['cells'])} ячеек, отчёт {len(txt)} знаков; "
          f"точка отсчёта взяла {ref['taken']} сделок, "
          f"медиана {ref['pnl_median']*100:+.2f} %")


def _poison(path, lit, sub, fn, mod):
    src = open(path, encoding="utf-8").read()
    assert lit in src, f"подделка НЕ легла: литерала нет — {lit}"
    keep = os.path.join(tempfile.mkdtemp(prefix="d8-"),
                        os.path.basename(path))
    shutil.copy(path, keep)
    try:
        open(path, "w", encoding="utf-8").write(src.replace(lit, sub, 1))
        cache = os.path.join(os.path.dirname(path), "__pycache__")
        base = os.path.basename(path).split(".")[0]
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith(base + "."):
                    os.remove(os.path.join(cache, f))
        importlib.reload(mod)
        try:
            fn()
        except Exception:
            return True
        return False
    finally:
        shutil.copy(keep, path)
        importlib.reload(mod)


def _control_weights_not_normalised():
    """Нормировка снята — диагностическая рука повторяет базовую."""
    return _poison(os.path.join(HERE, "run_d8.py"),
                   "return [x / s for x in w] if s > 0 else w",
                   "return w",
                   test_normalised_weights_deploy_the_whole_notional, D8)


def _control_missing_sigma_becomes_zero():
    """σ без меры подменена нулём — цель в ноль процентов."""
    return _poison(os.path.join(HERE, "run_d8.py"),
                   "if sig is None or not sig > 0:",
                   "if False:",
                   test_sigma_missing_drops_the_decision_everywhere, D8)


def _control_sample_is_per_cell():
    """Выборка считается по каждой ячейке отдельно."""
    return _poison(os.path.join(HERE, "run_d8.py"),
                   "ok = s if ok is None else (ok & s)",
                   "ok = s if ok is None else (ok | s)",
                   test_common_sample_is_one_for_all_cells, D8)


def _control_reference_anchors_on_the_average():
    """Точка отсчёта считается по ТВХ — то есть книгу не воспроизводит."""
    return _poison(os.path.join(HERE, "run_d8.py"),
                   'out.append((f"{ak}:{tk}", anchor, tk, None, False))',
                   'out.append((f"{ak}:{tk}", "avg", tk, None, False))',
                   test_reference_cell_reproduces_the_book_rule, D8)


TESTS = [
    test_reference_cell_reproduces_the_book_rule,
    test_avg_anchor_exits_earlier_and_pays_the_filled_notional,
    test_normalised_weights_deploy_the_whole_notional,
    test_sigma_missing_drops_the_decision_everywhere,
    test_common_sample_is_one_for_all_cells,
    test_run_end_to_end_synthetic,
]

CONTROLS = [
    ("веса не нормируются", _control_weights_not_normalised),
    ("σ без меры считается нулём", _control_missing_sigma_becomes_zero),
    ("выборка своя у каждой ячейки", _control_sample_is_per_cell),
    ("точка отсчёта не воспроизводит книгу",
     _control_reference_anchors_on_the_average),
]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; {len(CONTROLS)} отрицательных "
          f"контролей кусаются")


if __name__ == "__main__":
    main()
