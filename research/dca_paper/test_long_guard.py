"""Охрана вниз для длинных книг: ядро `wave.k_star/apply_guard(down=True)`
и нуль замера `long_guard` (те же часы, случайные открытые позиции)."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wave as WV                                             # noqa: E402
import long_guard as LG                                       # noqa: E402

H = 3600.0
AT = 1_790_000_000.0


class FakeMarket(WV.Market):
    """Волна задана рядом по часам от входа: {k: доля}."""

    def __init__(self, path):
        super().__init__(hours=object())
        self.path = path

    def wave(self, t0, t1):
        return self.path.get(int(round((t1 - t0) / H)))


def _rec(at, n=10, d=0.01, state="closed"):
    marks = [(at + (k - 1) * H, d) for k in range(1, n + 1)]
    return {"sym": "AUSDT", "at": at, "exit_ts": at + n * H, "pnl": d * n,
            "marks": marks, "state": state, "side": "long", "lev": 2.0,
            "fills": [(at, 1.0, 0.25)], "exit": "срок"}


def test_down_trigger_mirrors_up_and_default_is_unchanged():
    m = FakeMarket({1: 0.0, 2: -0.01, 3: -0.025, 4: 0.03})
    k, miss = m.k_star(AT, 2.0, 9, down=True)
    assert (k, miss) == (3, 0), (k, miss)
    k_up, _ = m.k_star(AT, 2.0, 9)                    # прежний счёт: вверх, k=4
    assert k_up == 4, k_up
    out, st = WV.apply_guard([_rec(AT)], 2.0, m, kmax=9, down=True)
    assert st["closed_by_market"] == 1 and out[0]["exit"] == WV.GUARD_EXIT
    assert abs(out[0]["pnl"] - 0.03) < 1e-12 and out[0]["exit_ts"] == AT + 3 * H - 1
    out2, st2 = WV.apply_guard([_rec(AT)], 4.0, m, kmax=9, down=True)
    assert st2["closed_by_market"] == 0 and out2[0]["exit"] == "срок"
    print("ok  охрана вниз: срабатывает на −2.5 % в час 3, вверх — прежний час 4; ниже порога — молчит")


def test_null_uses_the_same_hours_and_other_positions():
    recs = [_rec(AT + i * H) for i in range(6)]
    hits = [(recs[0], WV.guard_record(recs[0], 3))]
    idx = LG.open_index(recs, "safe")
    rng = random.Random(1)
    out, miss = LG.null_book(recs, hits, idx, rng)
    changed = [(i, r) for i, r in enumerate(out) if r is not recs[i]]
    assert miss == 0 and len(changed) == 1, (miss, changed)
    i, r = changed[0]
    assert r["exit"] == "случайный" and int((r["exit_ts"] + 1) // H) == int((AT + 3 * H) // H)
    print(f"ok  нуль: тот же час закрытия ({int((r['exit_ts'] + 1 - AT) // H)} ч от первой), "
          f"случайная открытая позиция №{i}")


def test_inverse_variants_and_direction():
    import inverse_guard as IG
    names = [n for n, _d, _i in IG.variants("short")]
    assert names[:2] == ["off", "direct4"] and "inv2" in names and "direct4+inv6" in names, names
    assert [n for n, _d, _i in IG.variants("long")][:2] == ["off", "inv1"]
    m = FakeMarket({1: -0.03, 2: 0.05})
    out, hits = IG.guard([_rec(AT)], 2.0, m, "safe_h", down=True, why=IG.WHY_INV)
    assert len(hits) == 1 and out[0]["exit"] == IG.WHY_INV and out[0]["exit_ts"] == AT + H - 1
    out2, hits2 = IG.guard([_rec(AT)], 2.0, m, "safe", down=False, why=IG.WHY_INV)
    assert len(hits2) == 1 and out2[0]["exit_ts"] == AT + 2 * H - 1
    print("ok  обратная охрана: варианты объявлены, шорт — по падению рынка, лонг — по росту")


if __name__ == "__main__":
    test_down_trigger_mirrors_up_and_default_is_unchanged()
    test_null_uses_the_same_hours_and_other_positions()
    test_inverse_variants_and_direction()
    print("\nвсе 3 проверки прошли")
