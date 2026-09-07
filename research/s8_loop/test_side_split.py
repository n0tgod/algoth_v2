#!/usr/bin/env python3
"""Проверки `side_split.py`: сделки собираются ядром кассы, стороны не
смешиваются, вердикт держит порог и половины, семьи не складывают эхо."""
import importlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import side_split as SS                                       # noqa: E402
import trades as TR                                           # noqa: E402

H0 = "2026-08-10-00"
T0 = 1_786_320_000            # ≈ 2026-08-10 00:00 UTC


def _hour(i):
    from datetime import datetime, timedelta, timezone
    d = datetime(2026, 8, 10, tzinfo=timezone.utc) + timedelta(hours=i)
    return d.strftime("%Y-%m-%d-%H")


def _book(root, dirname, n_hours, short_got, long_got, situational=False):
    """Книга: каждый час один лонг и один шорт; исходы — функциями часа."""
    d = os.path.join(root, dirname)
    os.makedirs(d, exist_ok=True)
    man = {"situational": situational, "horizon_h": 4, "slots": 6,
           "trained_at": "2026-08-10T00:00:00+00:00"}
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f)
    with open(os.path.join(d, "picks.jsonl"), "w", encoding="utf-8") as fp, \
            open(os.path.join(d, "review.jsonl"), "w", encoding="utf-8") as fr:
        for i in range(n_hours):
            h = _hour(i)
            fp.write(json.dumps({"arm": "gbm", "hour": h,
                                 "long": [{"sym": "LUSDT", "fwd": 200.0, "px": 100.0}],
                                 "short": [{"sym": "SUSDT", "fwd": -200.0, "px": 100.0}]})
                     + "\n")
            sg, lg = short_got(i), long_got(i)
            fr.write(json.dumps({"arm": "gbm", "hour": h, "cost_bp": 11.0, "rows": [
                {"sym": "LUSDT", "side": "long", "expected": 200.0,
                 "got": lg, "net": lg - 11.0},
                {"sym": "SUSDT", "side": "short", "expected": -200.0,
                 "got": -sg, "net": sg - 11.0}]}) + "\n")
    return d


def _registry():
    return [
        {"key": "a", "dir": "model_a", "label": "A", "family": "timer",
         "horizon_h": 4, "traded": True, "echo": False, "agree": False},
        {"key": "b", "dir": "model_b", "label": "B", "family": "timer",
         "horizon_h": 4, "traded": True, "echo": False, "agree": False},
        {"key": "b_echo", "dir": "model_b_echo", "label": "B echo",
         "family": "timer", "horizon_h": 4, "traded": True, "echo": True,
         "agree": False},
        {"key": "c", "dir": "model_c", "label": "C", "family": "situational",
         "horizon_h": None, "traded": True, "echo": False, "agree": False},
        {"key": "gone", "dir": "model_gone", "label": "нет", "family": "timer",
         "horizon_h": 4, "traded": True, "echo": False, "agree": False},
    ]


def test_sides_are_split_by_the_ledger_and_judged_by_numbers():
    root = tempfile.mkdtemp(prefix="side-")
    try:
        # A: шорты стабильно в плюсе, лонги в минусе → «только шорты»
        _book(root, "model_a", 80, lambda i: 60.0, lambda i: -40.0)
        # B: шорты в плюсе по сумме, но вторая половина в минусе
        _book(root, "model_b", 80, lambda i: 200.0 if i < 40 else -60.0,
              lambda i: 30.0)
        _book(root, "model_b_echo", 80, lambda i: 200.0 if i < 40 else -60.0,
              lambda i: 30.0)
        # C: мало сделок — не судится
        _book(root, "model_c", 10, lambda i: 100.0, lambda i: 100.0)
        s = SS.run(books=_registry(), root=root, log=lambda *a: None)
        assert s["missing"] == ["gone"], s["missing"]
        by = {(r["key"], r["arm"]): r for r in s["rows"]}
        a = by[("a", "gbm")]
        assert a["short"]["n"] == 80 and a["long"]["n"] == 80, a["short"]
        assert a["short"]["pnl_usd"] > 0 > a["long"]["pnl_usd"], (a["short"], a["long"])
        assert a["short"]["net_bp_median"] == 49.0 and a["long"]["net_bp_median"] == -51.0
        assert a["short"]["half_a"] > 0 and a["short"]["half_b"] > 0
        assert a["verdict"]["shorts_positive"] and a["verdict"]["shorts_only"], a["verdict"]
        b = by[("b", "gbm")]
        assert b["short"]["pnl_usd"] > 0 and b["short"]["half_b"] < 0, b["short"]
        assert b["verdict"]["shorts_positive_unstable"] and not b["verdict"]["shorts_positive"]
        c = by[("c", "gbm")]
        assert c["verdict"]["judged"] is False and "меньше" in c["verdict"]["why"]
        assert s["shorts_only"] == ["a/gbm"] and s["shorts_positive"] == ["a/gbm"]
        assert s["shorts_positive_unstable"] == ["b/gbm", "b_echo/gbm"], s["shorts_positive_unstable"]
        # семьи: эхо не складывается, ситуационная — своя строка
        fam = s["families"]
        assert fam["timer"]["books"] == ["a", "b"], fam["timer"]
        assert abs(fam["timer"]["short_pnl"] - (a["short"]["pnl_usd"] + b["short"]["pnl_usd"])) < 0.011
        assert fam["situational"]["books"] == ["c"]
        txt = SS.report(s)
        for need in ("`a` | timer | gbm", "только шорты", "`b_echo` (эхо)",
                     "плюс, но не на обеих половинах", "шортов меньше 30", "gone"):
            assert need in txt, need
        print(f"ok  стороны разрезаны кассой: A шорты {a['short']['pnl_usd']:+.2f} $ / "
              f"лонги {a['long']['pnl_usd']:+.2f} $ → «только шорты»; B — неустойчиво; "
              "C — не судится; эхо в семье не сложено")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# --- отрицательные контроли ------------------------------------------------
def _poison(path, lit, sub, fn, mod):
    src = open(path, encoding="utf-8").read()
    assert src.count(lit) == 1, f"подделка НЕ легла: {lit}"
    keep = os.path.join(tempfile.mkdtemp(prefix="side-ctl-"), os.path.basename(path))
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


P = os.path.join(HERE, "side_split.py")


def _control_side_ignored():
    return _poison(P, 's = [t for t in closed if t.get("side") == side]',
                   "s = list(closed)",
                   test_sides_are_split_by_the_ledger_and_judged_by_numbers, SS)


def _control_halves_not_required():
    return _poison(P, '"shorts_positive": bool(pos and stable),',
                   '"shorts_positive": bool(pos),',
                   test_sides_are_split_by_the_ledger_and_judged_by_numbers, SS)


def _control_echo_summed_into_family():
    return _poison(P, 'if r["echo"] or r["agree"]:\n            continue',
                   "if False:\n            continue",
                   test_sides_are_split_by_the_ledger_and_judged_by_numbers, SS)


TESTS = [test_sides_are_split_by_the_ledger_and_judged_by_numbers]
CONTROLS = [("сторона не различается", _control_side_ignored),
            ("половины не требуются", _control_halves_not_required),
            ("эхо сложено в семью", _control_echo_summed_into_family)]


def main():
    for t in TESTS:
        t()
    bad = [nm for nm, fn in CONTROLS if not fn()]
    assert not bad, f"контроли не кусаются: {bad}"
    print(f"\nвсе {len(TESTS)} проверки прошли; {len(CONTROLS)} отрицательных "
          f"контролей кусаются")


if __name__ == "__main__":
    main()
