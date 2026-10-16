"""Охрана рынком у живого читателя: час, который ещё пишется, не судится.

Дефект 2026-10-16 12:03 UTC: сводка часа 11 писалась по именам с
12:02:05 до 12:04:24; к 12:03 строки были у 10 прокси из 19, и их
средняя волна с входа 15.10 19:00 дала +2.18 % ≥ 2 % — три шорта живой
подписки закрыты «рынком». По всем 19 именам волна была +1.46 %.

Кусается: (1) с `require_full` волна часа с неполными строками — None
(не измерено) и в кэш не идёт, а по полному часу считается; (2) без
флага — прежний счёт по тем, кто есть (бумага, бит в бит); (3) имя без
цены на ОБОИХ концах (TON) полноту не ломает; (4) `k_star` при
неполном часе не кэширует отказ — следующий такт увидит полный час.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wave as WV                                             # noqa: E402

# ход 15.10 19:00 → 16.10 11:00 по данным зонда (б.п. → доли)
MOVES = {"BTC": 0.27, "ETH": 1.04, "SOL": 0.56, "XRP": 0.25, "BNB": -0.26, "DOGE": 1.34,
         "ADA": 0.39, "AVAX": 2.90, "LINK": 1.12, "DOT": 3.66, "TRX": 0.99, "SUI": 1.54,
         "LTC": 1.39, "BCH": 1.46, "NEAR": -0.78, "APT": 6.50, "UNI": 0.73, "ARB": 4.49, "OP": 0.14}
EARLY = {"BTC", "ETH", "BNB", "DOGE", "ADA", "AVAX", "DOT", "BCH", "APT", "ARB"}   # записаны до 12:03
T0 = 1792090799.0            # 15.10 18:59:59 UTC (t_in при pos_at 19:00)
T1 = T0 + 17 * 3600          # 16.10 11:59:59 — час 11


class FakeHours:
    def __init__(self, present_at_t1):
        self.present = present_at_t1

    def row(self, sym, ts):
        base = sym[:-4]
        if base not in MOVES:                    # TON — нет на обоих концах
            return None
        if int(ts // 3600) == int(T0 // 3600):
            return {"mid_close": 100.0}
        if int(ts // 3600) == int(T1 // 3600) and base in self.present:
            return {"mid_close": 100.0 * (1 + MOVES[base] / 100.0)}
        return None


def test_partial_hour_is_not_measured_for_live_reader():
    partial = WV.Market(FakeHours(EARLY), require_full=True)
    assert partial.wave(T0, T1) is None, "неполный час у живого читателя обязан быть «не измерен»"
    assert partial.wave_partial == 1 and (int(T0 // 3600), int(T1 // 3600)) not in partial._wave
    k, miss = partial.k_star(T0 + 1, 2.0, 23)
    assert k is None, k
    assert (int(round(T0 + 1)), 2.0, 23) not in partial._kstar, "отказ по неполному часу не кэшируется"
    # контроль: без флага — волна по тем, кто есть, и она ВЫШЕ порога (так и сработало 16.10)
    legacy = WV.Market(FakeHours(EARLY))
    w = legacy.wave(T0, T1)
    assert w is not None and abs(w - 0.0218) < 0.0005, w
    assert legacy.k_star(T0 + 1, 2.0, 23)[0] == 17
    # полный час — считается и у живого читателя, и он НИЖЕ порога
    full = WV.Market(FakeHours(set(MOVES)), require_full=True)
    w2 = full.wave(T0, T1)
    assert w2 is not None and abs(w2 - 0.0146) < 0.0005, w2
    assert full.k_star(T0 + 1, 2.0, 23)[0] is None
    print(f"ok  неполный час (10 из 19): живой читатель — «не измерено»; прежний счёт дал бы "
          f"{w * 100:+.2f} % и выход; полный час {w2 * 100:+.2f} % — ниже порога, выхода нет")


if __name__ == "__main__":
    test_partial_hour_is_not_measured_for_live_reader()
