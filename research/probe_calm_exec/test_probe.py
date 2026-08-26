#!/usr/bin/env python3
"""
Тесты зонда пассивного входа в спокойном рынке.

Главная пара — калибровочная: на синтетике с известным ответом выгода
обязана сойтись ЧИСЛОМ (спред + разница комиссий при исполнении, ровно
ноль при плоской цене без исполнения). Без неё отрицательный результат
не значил бы ничего: сломанная загрузка выглядит как «выгоды нет», и
проект дважды печатал нулевой отчёт именно так.

    python3 research/probe_calm_exec/test_probe.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "d1_seconds"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))

import probe as P                                         # noqa: E402
import detect as D                                        # noqa: E402
import run_d1 as R                                        # noqa: E402
from store import Writer                                  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def grids(n=4000, px=100.0, drift_bp_s=0.0, spread_bp=20.0,
          bsz=10.0, asz=7.0):
    """Синтетические секундные сетки с известной геометрией."""
    t = np.arange(n, dtype=np.float64)
    m = px * (1.0 + drift_bp_s * 1e-4 * t)
    half = m * spread_bp / 2.0 * 1e-4
    bid = (m - half).astype(np.float32)
    ask = (m + half).astype(np.float32)
    mid = np.where(np.isfinite(bid) & np.isfinite(ask),
                   (bid + ask) / 2.0, np.nan)
    _, nxt = D.fill_index(mid)
    return (mid, bid, ask, np.full(n, bsz, np.float32),
            np.full(n, asz, np.float32), nxt)


def tape(rows):
    a = np.array(rows, dtype=np.float64)
    if len(a) == 0:
        return (np.empty(0), np.empty(0), np.empty(0), np.empty(0))
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def test_filled_benefit_is_spread_plus_fee_gap():
    """Плоская цена, лимитка исполнилась: выгода = спред + 3.5 б.п.

    Вход по биду вместо аска экономит ВЕСЬ спред (не половину — обе
    цены сравниваются с одной точкой оценки), плюс разница комиссий.
    """
    mid, bid, ask, bsz, asz, nxt = grids()
    tt, tp, tv, ts = tape([[1.0, 99.0, 50.0, -1]])
    got = P.eval_moment(mid, bid, ask, bsz, asz, nxt, tt, tp, tv, ts,
                        0, 1, 60, 0)
    check("исполнилось", got is not None and got[0], f"{got}")
    want = 20.0 + (P.TAKER_BP - P.MAKER_BP)
    check("выгода равна спреду плюс разнице комиссий",
          got is not None and abs(got[2] - want) < 0.01,
          f"{got and got[2]} против {want}")


def test_unfilled_flat_benefit_is_exactly_zero():
    """Пустая лента, плоская цена: доисполнение тейкером по той же цене
    — выгода РОВНО ноль. Ветка доисполнения обязана существовать: без
    неё событие теряется, и рука мейкера мерилась бы только там, где ей
    повезло."""
    mid, bid, ask, bsz, asz, nxt = grids()
    tt, tp, tv, ts = tape([])
    got = P.eval_moment(mid, bid, ask, bsz, asz, nxt, tt, tp, tv, ts,
                        0, 1, 60, 0)
    check("запись есть и не исполнена",
          got is not None and not got[0], f"{got}")
    check("выгода ровно ноль", got is not None and got[2] == 0.0,
          f"{got and got[2]}")


def test_trend_up_costs_the_unfilled_buy():
    """Цена растёт 1 б.п./с, лента пуста: покупка доисполняется через
    60 с по выросшему аску — выгода около −60 б.п."""
    mid, bid, ask, bsz, asz, nxt = grids(drift_bp_s=1.0)
    tt, tp, tv, ts = tape([])
    got = P.eval_moment(mid, bid, ask, bsz, asz, nxt, tt, tp, tv, ts,
                        0, 1, 60, 0)
    check("рост стоит недоисполненной покупке ~60 б.п.",
          got is not None and -61.0 < got[2] < -55.0,
          f"{got and got[2]}")


def test_sell_side_is_symmetric():
    """Зеркало: падение 1 б.п./с, продажа лимиткой не исполнилась —
    та же цена в другую сторону."""
    mid, bid, ask, bsz, asz, nxt = grids(drift_bp_s=-1.0)
    tt, tp, tv, ts = tape([])
    got = P.eval_moment(mid, bid, ask, bsz, asz, nxt, tt, tp, tv, ts,
                        0, -1, 60, 0)
    check("падение стоит недоисполненной продаже ~60 б.п.",
          got is not None and -61.0 < got[2] < -55.0,
          f"{got and got[2]}")


def test_sell_queue_is_the_ask_size():
    """Очередь продажи — размер АСКА. Покупающая агрессия сквозь наш
    аск (очередь 7 + нога) исполняет; возьми код очередь с бида (10⁹),
    исполнения бы не было."""
    mid, bid, ask, bsz, asz, nxt = grids(bsz=1e9, asz=7.0)
    tt, tp, tv, ts = tape([[1.0, 100.2, 50.0, +1]])
    got = P.eval_moment(mid, bid, ask, bsz, asz, nxt, tt, tp, tv, ts,
                        0, -1, 60, 0)
    check("продажа исполнена очередью аска",
          got is not None and got[0], f"{got}")


def test_missing_eval_point_is_a_skip():
    """Дыра записи в точке оценки — пропуск, а не ноль."""
    mid, bid, ask, bsz, asz, nxt = grids(n=4000)
    mid[100:] = np.nan
    _, nxt2 = D.fill_index(mid)
    tt, tp, tv, ts = tape([])
    got = P.eval_moment(mid, bid, ask, bsz, asz, nxt2, tt, tp, tv, ts,
                        0, 1, 60, 0)
    check("нет точки оценки — нет записи", got is None, f"{got}")


def test_band_edges():
    checks = [(-1.5, 0), (-1.0, 1), (-0.5, 1), (-0.25, 2), (0.0, 2),
              (0.24, 2), (0.25, 3), (0.9, 3), (1.0, 4), (3.0, 4)]
    bad = [(z, P.band_of(z), w) for z, w in checks if P.band_of(z) != w]
    check("границы полос состояния", not bad, f"{bad}")


def test_ep_median_one_hour_one_vote():
    """Час — один голос: три записи одного часа не переголосуют одну
    запись другого."""
    med, n, share = P._ep_median([1.0, 1.0, 1.0, -5.0],
                                 [10, 10, 10, 20])
    check("медиана почасовых медиан", (med, n, share) == (-2.0, 2, 0.5),
          f"{(med, n, share)}")


def test_verdict_phrase_follows_the_number():
    """Фраза выводится из числа — обе ветки (урок Z2: вердиктовая
    фраза литералом противоречила собственному числу отчёта)."""
    pos = P.verdict_phrase({"benefit_ep_bp": 5.0})
    neg = P.verdict_phrase({"benefit_ep_bp": -3.0})
    check("плюс называется ПЛАТИТ", "ПЛАТИТ" in pos and "+5.0" in pos,
          pos)
    check("минус называется НЕ платит",
          "НЕ платит" in neg and "-3.0" in neg, neg)
    check("нет числа — нет фразы",
          "не измерена" in P.verdict_phrase(None), "")


# Почасовые дельты цены, б.п.: большинство часов мелкие (спокойная
# полоса), каждый шестой — крупный (σ невырождена, полосы хвостов
# непусты). Ровно плоская цена дала бы σ = 0, и собственная защита
# зонда от замороженного ряда отсеяла бы ВСЮ фикстуру — подставные
# данные обязаны дрожать, как живые.
HOUR_DELTAS_BP = [10.0 if h % 6 == 5 else (0.5 if h % 2 == 0 else -0.5)
                  for h in range(24)]


def px_of(day_idx, hour):
    """Цена начала часа: кумулятив почасовых дельт."""
    total = day_idx * sum(HOUR_DELTAS_BP) + sum(HOUR_DELTAS_BP[:hour])
    return 100.0 * (1.0 + total * 1e-4)


def write_day(w, sym, day_t0, day_idx, *, sell_tape, step=10):
    """Сутки записи одного имени: снимки раз в `step` секунд, цена
    константна внутри часа и шагает по HOUR_DELTAS_BP между часами;
    при `sell_tape` — постоянная продающая агрессия."""
    for j in range(0, 86400, step):
        px = px_of(day_idx, j // 3600)
        t = day_t0 + j
        w.write("book", sym, {
            "s": sym, "ts": int(t * 1000), "u": 1,
            "bid": px * 0.999, "ask": px * 1.001,
            "bid_sz": 10.0, "ask_sz": 10.0, "upd": 1,
            "b": [[px * 0.999, 10.0]], "a": [[px * 1.001, 10.0]],
            "t": round(float(t), 3)}, ts=t)
        if sell_tape:
            w.write("trades", sym, {
                "ts": int(t * 1000), "s": sym, "side": -1,
                "p": px * 0.998, "v": 200.0}, ts=t)
    w.flush()


def build_store(root, n_days=2):
    """Два имени, `n_days` суток; у S000 лента продаж, у S001 пустая."""
    w = Writer(root)
    t0 = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
    for d in range(n_days):
        for sym, st in (("S000USDT", True), ("S001USDT", False)):
            write_day(w, sym, t0 + d * 86400, d, sell_tape=st)
    w.flush()
    w.close()
    return t0


def test_sigma_is_causal_first_days_are_not_measured():
    """События появляются только когда σ набрана из ПРОШЛЫХ суток.

    min_obs=12 (сутки истории дают ~23 доходности): у первых суток σ
    нет — все их моменты уходят в счётчик, события несут только даты
    вторых суток. Утечка σ из текущих суток дала бы события первых.
    """
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "store")
        t0 = build_store(root, n_days=2)
        counters = {k: 0 for k in (
            "нет якорного снимка", "нет точки состояния",
            "кривые уровни", "нет σ (мало истории)",
            "нет σ (замороженный ряд)", "нет точки оценки")}
        ev = P.measure_symbol(root, "S000USDT",
                              ["2026-08-05", "2026-08-06"],
                              counters, min_obs=12)
        check("события есть", len(ev) > 0, f"{len(ev)}")
        d2 = int(datetime(2026, 8, 6,
                          tzinfo=timezone.utc).timestamp())
        early = [e for e in ev if e[9] < d2]
        check("первые сутки не меряются (σ причинная)",
              not early, f"{len(early)} событий первых суток")
        check("пропуск по σ посчитан",
              counters["нет σ (мало истории)"] > 0,
              f"{counters}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pick_symbols_filters_non_crypto():
    tmp = tempfile.mkdtemp()
    try:
        for kind in ("book", "trades"):
            for s in ("BTCUSDT", "WMTUSDT", "AAAUSDT", "BBBUSDT"):
                os.makedirs(os.path.join(tmp, kind, s))
        got = P.pick_symbols(tmp, 4)
        check("не-крипто отфильтрован", "WMTUSDT" not in got, f"{got}")
        check("BTC входит принудительно", "BTCUSDT" in got, f"{got}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_main(root, out, min_obs=12):
    argv, pub, mo = sys.argv, R.publish, P.MIN_SIGMA_OBS
    R.publish = lambda msg: None
    P.MIN_SIGMA_OBS = min_obs
    sys.argv = ["probe.py", "--root", root, "--out", out,
                "--start", "2026-08-05", "--tag", "t", "--no-publish",
                "--symbols", "S000USDT", "--symbols", "S001USDT"]
    try:
        P.main()
    finally:
        sys.argv, R.publish, P.MIN_SIGMA_OBS = argv, pub, mo
    return json.load(open(os.path.join(out, "CALM-exec-t.json"),
                          encoding="utf-8"))


def test_end_to_end():
    """Сквозной прогон настоящим main(): плоская цена и продающая лента
    у S000 — покупка «на лучшей» исполняется и выгода в её ячейках
    положительна; verdict-строка согласована с числом заголовка."""
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "store")
        build_store(root, n_days=2)
        out = os.path.join(tmp, "out")
        art = run_main(root, out)
        check("события сквозного есть", art["events"] > 0,
              f"{art['events']}")
        cell = art["summary"].get("1|2|60|0")
        check("спокойная ячейка покупки на лучшей есть",
              cell is not None, f"{sorted(art['summary'])[:6]}")
        h = art["headline"]
        check("заголовок посчитан", h is not None, "")
        v = art["verdict"]
        ok = ("ПЛАТИТ" in v) == (h["benefit_ep_bp"] > 0)
        check("фраза вердикта согласована с числом", ok,
              f"{h['benefit_ep_bp']} / {v}")
        md = open(os.path.join(out, "CALM-exec-t.md"),
                  encoding="utf-8").read()
        check("отчёт несёт главную ячейку",
              "Главная ячейка" in md and "спокойно" in md, "")
        check("отчёт несёт оговорку про отмены",
              "отмены заявок не видны" in md, "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("оценка момента (синтетика с известным ответом)")
    test_filled_benefit_is_spread_plus_fee_gap()
    test_unfilled_flat_benefit_is_exactly_zero()
    test_trend_up_costs_the_unfilled_buy()
    test_sell_side_is_symmetric()
    test_sell_queue_is_the_ask_size()
    test_missing_eval_point_is_a_skip()
    print("состояние и свод")
    test_band_edges()
    test_ep_median_one_hour_one_vote()
    test_verdict_phrase_follows_the_number()
    print("причинность и срез")
    test_sigma_is_causal_first_days_are_not_measured()
    test_pick_symbols_filters_non_crypto()
    print("сквозной прогон")
    test_end_to_end()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
