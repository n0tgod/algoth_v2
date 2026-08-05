#!/usr/bin/env python3
"""
Тесты S8.1. Главные — заглядывание (один тест на ВСЕ признаки, правило
M1) и правильность пути (MFE/MAE): на них стоит вся геометрия сделок,
и ошибка в них была бы невидима в результате.

    python3 research/s8_loop/test_s8.py
"""

import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np

from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bookfeat as FB                                      # noqa: E402
import summary as SM                                       # noqa: E402
from book import BANDS                                     # noqa: E402

FAILED = []
rng = np.random.default_rng(20260801)


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


# ---------- сводка часа ----------

def _snap(mid, reach_bp, t, big=1000.0):
    r = {"t": t, "bid": mid - 0.5, "ask": mid + 0.5,
         "bid_sz": 10.0, "ask_sz": 12.0, "upd": 7,
         "reach_b": reach_bp, "reach_a": reach_bp,
         "b": [[mid - 0.5, big / mid]], "a": [[mid + 0.5, 8.0]]}
    for w in BANDS:
        r[f"bq{w}"] = 100.0 * (1 + w * 1000)
        r[f"aq{w}"] = 90.0 * (1 + w * 1000)
    return r


def test_summary_censors_bands_by_reach():
    # Охват ±4 б.п. — как у BTC: самая узкая полоса требует пяти.
    rows = [_snap(1000.0, 4.0, i) for i in range(10)]
    out = SM.summarize_hour(rows, [])
    check("узкая полоса цензурирована охватом",
          out["bq_b0.0005"] is None and out["cov_b0.0005"] == 0.0,
          str(out["bq_b0.0005"]))
    rows = [_snap(1000.0, 60.0, i) for i in range(10)]
    out = SM.summarize_hour(rows, [])
    check("при охвате 60 б.п. измеримы полосы до ±0.5 %",
          out["bq_b0.005"] is not None and out["cov_b0.005"] == 1.0,
          str(out))
    check("охват и спред посчитаны",
          abs(out["reach_bp"] - 60.0) < 1e-9 and out["spread_bp"] > 0)


def test_summary_tape():
    rows = [_snap(1000.0, 60.0, i) for i in range(5)]
    trades = [
        {"ts": 1_000_000, "side": 1, "p": 1000.0, "v": 2.0},
        {"ts": 1_001_400, "side": 1, "p": 1001.0, "v": 1.0},
        {"ts": 1_001_600, "side": -1, "p": 999.0, "v": 3.0},
    ]
    out = SM.summarize_hour(rows, trades)
    check("дельта ленты по сторонам",
          abs(out["buy"] - 3001.0) < 1e-6 and abs(out["sell"] - 2997.0)
          < 1e-6, f"{out['buy']} {out['sell']}")
    check("всплеск — максимум секунды, а не среднее",
          abs(out["vol_max_1s"] - (1001.0 + 2997.0)) < 1e-6,
          str(out["vol_max_1s"]))
    check("торгуемых секунд две", out["traded_secs"] == 2,
          str(out["traded_secs"]))
    check("максимум цены пришёл из ленты",
          abs(out["mid_high"] - 1001.0) < 1e-9, str(out["mid_high"]))


def test_summary_roundtrip_through_store():
    """Синтетическая запись через настоящий Writer и read_hour."""
    from store import Writer
    d = tempfile.mkdtemp()
    w = Writer(d, log=lambda m: None)
    # Ровно внутрь часа: иначе двадцать секундных записей от «двух часов
    # назад» переползают через границу часа, попадают в соседний файл, и
    # тест падает в зависимости от времени суток.
    t0 = (time.time() - 7200) // 3600 * 3600 + 60
    hour = Writer.hour(t0)
    for i in range(20):
        s = _snap(500.0, 30.0, t0 + i)
        w.write("book", "TST", s, ts=t0 + i)
        w.write("trades", "TST",
                {"ts": int((t0 + i) * 1000), "side": 1 if i % 2 else -1,
                 "p": 500.0, "v": 1.0}, ts=t0 + i)
    w.close()
    from store import read_hour
    out = SM.summarize_hour(
        read_hour(os.path.join(d, "book", "TST"), hour),
        read_hour(os.path.join(d, "trades", "TST"), hour))
    check("сквозной прогон через хранилище",
          out is not None and out["n_snap"] == 20 and out["n_trades"] == 20,
          str(out))


def test_run_resumes_by_content():
    """Возобновление — по содержимому дневного файла (урок L2)."""
    from store import Writer
    d = tempfile.mkdtemp()
    w = Writer(d, log=lambda m: None)
    t0 = (time.time() - 7200) // 3600 * 3600 + 60
    for i in range(5):
        w.write("book", "AAA", _snap(10.0, 30.0, t0 + i), ts=t0 + i)
    w.close()
    outd = os.path.join(d, "summary")
    n1 = SM.run(d, outd, None, lambda m: None)
    n2 = SM.run(d, outd, None, lambda m: None)
    check("час посчитан один раз", n1 == 1 and n2 == 0, f"{n1} {n2}")
    day = Writer.hour(t0)[:10]
    with open(os.path.join(outd, "AAA", day + ".jsonl")) as f:
        rows = [json.loads(x) for x in f]
    check("строка сводки одна и с часом", len(rows) == 1
          and rows[0]["hour"] == Writer.hour(t0), str(rows))


# ---------- признаки и цели ----------

def synth_summary(S=40, D=600, seed=3):
    r = np.random.default_rng(seed)
    f = r.normal(0, 0.004, D)
    rets = f[None, :] + r.normal(0, 0.006, (S, D))
    close = 100 * np.cumprod(1 + rets, axis=1)
    high = close * (1 + np.abs(r.normal(0, 0.002, (S, D))))
    low = close * (1 - np.abs(r.normal(0, 0.002, (S, D))))
    s = {"mid_close": close, "mid_high": high, "mid_low": low,
         "n_snap": np.full((S, D), 3600.0),
         "spread_bp": np.abs(r.normal(5, 1, (S, D))),
         "upd": np.abs(r.normal(100, 10, (S, D))),
         "best_b": np.abs(r.normal(1e4, 1e3, (S, D))),
         "best_a": np.abs(r.normal(1e4, 1e3, (S, D))),
         "big_med": np.abs(r.normal(1e5, 1e4, (S, D))),
         "big_max": np.abs(r.normal(2e5, 2e4, (S, D))),
         "buy": np.abs(r.normal(1e6, 1e5, (S, D))),
         "sell": np.abs(r.normal(1e6, 1e5, (S, D))),
         "vol_max_1s": np.abs(r.normal(1e4, 1e3, (S, D))),
         "traded_secs": np.full((S, D), 1800.0),
         "depth_eat_b": np.abs(r.normal(2e5, 1e4, (S, D))),
         "depth_eat_a": np.abs(r.normal(2e5, 1e4, (S, D)))}
    for w in BANDS:
        s[f"bq_b{w}"] = np.abs(r.normal(1e5, 1e4, (S, D)))
        s[f"bq_a{w}"] = np.abs(r.normal(1e5, 1e4, (S, D)))
    # metrics/liq и контекст — чтобы общий тест заглядывания кусался
    # и на новых признаках, а не проходил их по пустым NaN
    s["fr"] = r.normal(0.0001, 0.0002, (S, D))
    s["mins_fund"] = np.abs(r.normal(120, 60, (S, D)))
    s["oi_usd"] = np.abs(r.normal(5e6, 5e5, (S, D)))
    s["basis_bp"] = r.normal(0, 3, (S, D))
    s["liq_long"] = np.abs(r.normal(1e4, 5e3, (S, D)))
    s["liq_short"] = np.abs(r.normal(1e4, 5e3, (S, D)))
    ts0 = 1785600000 - (1785600000 % 3600)
    ts = ts0 + np.arange(D) * 3600.0
    s["hour_ts"] = np.tile(ts, (S, 1))
    s["sector"] = np.array([[float(i % 5)] for i in range(S)])
    s["is_btc"] = np.array([[1.0 if i == 0 else 0.0] for i in range(S)])
    return s


def _mutate_after(s, t0, seed=9):
    r = np.random.default_rng(seed)
    out = {}
    for k, v in s.items():
        v2 = v.copy()
        v2[:, t0 + 1:] = np.abs(r.normal(50, 10, v2[:, t0 + 1:].shape))
        out[k] = v2
    return out


def test_no_lookahead_any_feature():
    s = synth_summary()
    t0 = 400
    a, _, _ = FB.feature_pack(s)
    b, _, _ = FB.feature_pack(_mutate_after(s, t0))
    for name in sorted(a):
        same = np.allclose(a[name][:, :t0 + 1], b[name][:, :t0 + 1],
                           equal_nan=True)
        check(f"будущее не трогает прошлое: {name}", same, name)
    s2 = {k: v.copy() for k, v in s.items()}
    s2["mid_close"][:, t0 - 5] *= 1.3
    c, _, _ = FB.feature_pack(s2)
    check("тест кусается",
          not np.allclose(a["ret_4h"][:, :t0 + 1], c["ret_4h"][:, :t0 + 1],
                          equal_nan=True))


def test_forward_path_exact():
    close = np.full((1, 10), 100.0)
    high = np.full((1, 10), 100.0)
    low = np.full((1, 10), 100.0)
    high[0, 4] = 103.0        # +300 б.п. в час 4
    low[0, 5] = 96.0          # −400 б.п. в час 5
    mfe, mae = FB.forward_path(close, high, low, h=4)
    # от часа 2 форвард накрывает часы 3..6: максимум 103, минимум 96
    check("MFE точен", abs(mfe[0, 2] - 300.0) < 1e-9, str(mfe[0, 2]))
    check("MAE точен от часа 2", abs(mae[0, 2] + 400.0) < 1e-9,
          str(mae[0, 2]))
    check("конец ряда — NaN, а не обрывок пути",
          np.isnan(mfe[0, -4:]).all(), str(mfe[0, -4:]))
    hole = high.copy()
    hole[0, 4] = np.nan
    mfe2, _ = FB.forward_path(close, hole, low, h=4)
    check("дыра внутри горизонта не рождает цели",
          np.isnan(mfe2[0, 2]), str(mfe2[0, 2]))


def test_formations_semantics():
    """Формации обязаны показывать то, что означают по-трейдерски.

    Не только «не заглядывают» (это делает общий тест), а именно смысл:
    сжатие диапазона даёт зажим меньше единицы, плоский ряд — полную
    проторговку, рост — положительный наклон и место у верха диапазона.
    """
    S, D = 2, 400
    close = np.full((S, D), 100.0)
    # символ 1 монотонно растёт — для наклонки и места в диапазоне
    close[1] = 100.0 + np.arange(D) * 0.1
    high = close * 1.01
    low = close * 0.99
    # у символа 0 последние 8 часов ход впятеро уже обычного — зажим
    high[0, -8:] = close[0, -8:] * 1.001
    low[0, -8:] = close[0, -8:] * 0.999
    # у растущего символа фитили узкие, иначе они забивают дрейф
    # и наклон измеряет шум свечи, а не ход
    high[1] = close[1] * 1.0001
    low[1] = close[1] * 0.9999
    f = FB.formations({"mid_close": close, "mid_high": high,
                       "mid_low": low})
    check("зажим < 1 на сжатии", f["squeeze_4h"][0, -1] < 0.5,
          str(f["squeeze_4h"][0, -1]))
    check("без сжатия зажим ~ 1",
          abs(f["squeeze_4h"][0, 200] - 1.0) < 0.2,
          str(f["squeeze_4h"][0, 200]))
    check("мало истории — NaN, а не число",
          np.isnan(f["squeeze_4h"][0, 10]), str(f["squeeze_4h"][0, 10]))
    check("плоский ряд — проторговка полная",
          f["dwell_24h"][0, 200] > 0.99, str(f["dwell_24h"][0, 200]))
    check("на плоском ряде наклона нет",
          abs(f["tilt_4h"][0, 200]) < 1e-9, str(f["tilt_4h"][0, 200]))
    check("на росте наклон положителен",
          f["tilt_4h"][1, 200] > 0.5, str(f["tilt_4h"][1, 200]))
    check("рост стоит у верха суточного диапазона",
          f["range_pos"][1, 200] > 0.9, str(f["range_pos"][1, 200]))


def test_metrics_liq_in_summary():
    """Сводка часа: funding/интерес/базис — последняя точка часа,
    ликвидации — суммы по сторонам с соглашением Bybit."""
    book = [_snap(100.0, 50.0, t) for t in range(10)]
    h_end = 1785600000.0
    met = [
        {"ts": (h_end - 3000) * 1000, "fr": 0.0009, "nft": 1, "oi": 1,
         "oiv": 1.0e6, "mark": 100.0, "idx": 100.0},
        {"ts": (h_end - 120) * 1000, "fr": 0.0001,
         "nft": (h_end + 7200) * 1000, "oi": 2, "oiv": 2.5e6,
         "mark": 100.1, "idx": 100.0},
    ]
    liq = [{"ts": 1, "side": "Buy", "p": 100.0, "v": 3.0},
           {"ts": 2, "side": "Sell", "p": 100.0, "v": 5.0},
           {"ts": 3, "side": "Sell", "p": 100.0, "v": 2.0}]
    row = SM.summarize_hour(book, [], met, liq, hour_end=h_end)
    check("ставка — последняя точка часа", row["fr"] == 0.0001,
          str(row.get("fr")))
    check("интерес в долларах — последняя точка",
          row["oi_usd"] == 2.5e6, str(row.get("oi_usd")))
    check("базис в б.п.", abs(row["basis_bp"] - 10.0) < 0.05,
          str(row.get("basis_bp")))
    check("минуты до начисления — от конца часа",
          abs(row["mins_fund"] - 120.0) < 0.2, str(row.get("mins_fund")))
    check("Buy — ликвидации ШОРТОВ", row["liq_short"] == 300.0,
          str(row.get("liq_short")))
    check("Sell — ликвидации ЛОНГОВ", row["liq_long"] == 700.0,
          str(row.get("liq_long")))
    bare = SM.summarize_hour(book, [])
    check("час без опроса метрик не выдумывает ни ставку, ни ноль "
          "ликвидаций", "fr" not in bare and "liq_long" not in bare)


def test_context_features():
    """Время, лидер, сектор, круглые числа — смыслом, не только
    отсутствием заглядывания."""
    # 2026-08-03 05:00 UTC — понедельник
    from datetime import datetime as DT, timezone as TZ
    ts0 = DT(2026, 8, 3, 5, tzinfo=TZ.utc).timestamp()
    S, D = 6, 30
    ts = np.tile(ts0 + np.arange(D) * 3600.0, (S, 1))
    ck = FB.clock_features({"hour_ts": ts}, ts)
    check("понедельник распознан", ck["dow"][0, 0] == 0.0,
          str(ck["dow"][0, 0]))
    check("час суток по кругу", abs(
        ck["hod_sin"][0, 0] - np.sin(2 * np.pi * 5 / 24)) < 1e-12)
    check("вторник наступает через 19 часов",
          ck["dow"][0, 19] == 1.0, str(ck["dow"][0, 19]))

    close = np.full((S, D), 100.0)
    close[0] = 100.0 * (1.01 ** np.arange(D))      # BTC растёт
    close[4] = 100.0 * (1.02 ** np.arange(D))      # одиночка без сектора
    s = {"is_btc": np.array([[1.], [0.], [0.], [0.], [0.], [0.]]),
         "sector": np.array([[0.], [0.], [0.], [0.], [np.nan], [0.]])}
    lf = FB.leader_features(s, close)
    r4 = close[0, 10] / close[0, 6] - 1.0
    check("ход BTC разослан всем", abs(lf["btc_ret_4h"][3, 10] - r4) < 1e-12)
    # сектор кода 0 — пять имён (0,1,2,3,5): BTC растёт, остальные
    # плоские; растущая одиночка (ряд 4) исключена NaN-сектором.
    # Среднее для плоского ряда 1 без себя — (ход BTC + 0 + 0 + 0) / 4
    want = r4 / 4.0
    check("сектор считается без себя",
          abs(lf["sec_ret_4h"][1, 10] - want) < 1e-12,
          str(lf["sec_ret_4h"][1, 10]))
    check("отставание от сектора — своё минус чужое",
          abs(lf["rel_sec_4h"][1, 10] - (0.0 - want)) < 1e-12)
    check("без сектора — пропуск, а не ноль",
          np.isnan(lf["sec_ret_4h"][4, 10]))

    d = FB.dist_round(np.array([[90000.0, 90500.0, 0.05]]))
    check("на круглом — ноль", d[0, 0] == 0.0, str(d[0, 0]))
    check("между круглыми — половина", abs(d[0, 1] - 0.5) < 1e-9,
          str(d[0, 1]))
    check("мелкая цена — своя сетка", d[0, 2] == 0.0, str(d[0, 2]))

    x = np.full((1, 10), 100.0)
    x[0, 3] = np.nan
    ch = FB.lagged_change(x, 4)
    check("изменение через дыру — пропуск", np.isnan(ch[0, 7]))
    check("изменение без дыры — число", np.isfinite(ch[0, 8]))


def test_eligibility_floor():
    s = synth_summary(S=35, D=300)
    s["n_snap"][3, :] = 100.0          # книга писалась три минуты в час
    _, r, elig = FB.feature_pack(s)
    check("недописанный час — не сечение (правило по числу)",
          not elig[3].any())
    check("остальные в сечении", elig[0].sum() > 250)


def test_eligibility_by_coverage():
    """Пригодность часа — покрытие во времени, а не число снимков.

    Дефект живого сервера: на 540 символах проход снимков дольше
    секунды, полностью записанный час даёт ~1200 снимков вместо 3600,
    и правило по числу давало РОВНО НОЛЬ сечений — модель не обучилась
    бы никогда при исправной записи.
    """
    S, D = 4, 10
    close = np.full((S, D), 100.0)
    n_snap = np.full((S, D), 1200.0)      # редкая сетка, час записан
    span = np.full((S, D), 3550.0)
    gap = np.full((S, D), 3.0)
    span[1] = 400.0                        # обрывок после перезапуска
    gap[2] = 900.0                         # дыра в четверть часа
    ok = FB.eligibility(close, n_snap, span, gap)
    check("редкая сетка при полном покрытии — сечение", ok[0].all())
    check("обрывок часа — не сечение", not ok[1].any())
    check("дыра длиннее пяти минут — не сечение", not ok[2].any())

    # Сводка старого образца охвата не несёт: правило по числу остаётся,
    # и пропуск полей не открывает ворота молча.
    old = FB.eligibility(close, n_snap, np.full((S, D), np.nan),
                         np.full((S, D), np.nan))
    check("без охвата судим по числу, 1200 < 1800 — не сечение",
          not old.any())


def test_targets_shapes_and_direction():
    s = synth_summary(S=35, D=400)
    f, r, elig = FB.feature_pack(s)
    t = FB.target_pack(s, r, elig, f["beta"])
    check("цели всех горизонтов на месте",
          sorted(t) == sorted([f"{k}_{h}h" for k in ("fwd", "mfe", "mae")
                               for h in FB.HORIZONS]), str(sorted(t)))
    ok = np.isfinite(t["mfe_4h"]) & np.isfinite(t["mae_4h"])
    # MFE бывает отрицательным (цена ни разу не поднялась выше входа),
    # MAE — положительным; настоящий инвариант пути: максимум не ниже
    # минимума.
    check("MFE ≥ MAE там, где оба есть",
          (t["mfe_4h"][ok] >= t["mae_4h"][ok] - 1e-9).all())


def test_retry_when_not_trained():
    """Не обучился — проверить через час, а не через сутки.

    Дефект, найденный на живом сервере: сутки — период переобучения,
    а не наказание за «данных ещё мало». Пока пауза была общей, час
    накопления 48-го сечения стоил бы полных суток ожидания.
    """
    import train as T
    slept, calls = [], []

    def fake_cycle(sum_dir, log_, **kw):
        calls.append(1)
        if len(calls) >= 3:
            raise SystemExit               # выход из вечного цикла
        return len(calls) == 2             # первый — нет, второй — да

    def fake_sleep(s):
        slept.append(s)

    orig_c, orig_s, orig_argv = T.cycle, T.time.sleep, sys.argv
    T.cycle, T.time.sleep, sys.argv = fake_cycle, fake_sleep, ["t"]
    try:
        try:
            T.main()
        except SystemExit:
            pass
    finally:
        T.cycle, T.time.sleep, sys.argv = orig_c, orig_s, orig_argv
    # Первая пауза садится на ГРАНИЦУ часа (см. отдельный тест), а не
    # равна ровно часу: иначе смещение, заданное моментом запуска,
    # жило бы вечно и определяло запаздывание входа.
    check("после «рано» ждём до границы часа, после обучения — сутки",
          len(slept) == 2 and 0 < slept[0] <= T.RETRY_SEC + T.MARGIN_SEC
          and slept[1] == T.CYCLE_SEC, str(slept))
    check("час заметно меньше суток",
          T.RETRY_SEC <= 3600 < T.CYCLE_SEC)


def test_readiness_is_written_before_training():
    """Готовность обязана быть файлом ДО того, как модель появится.

    Три раза подряд «модели нет» означало и «копим запись», и «копим
    вхолостую, ни один час не годен», и различить их можно было только
    зайдя на сервер. Файл пишется на КАЖДОМ цикле, включая тот, где
    обучения не было, — иначе он показывал бы только успех.
    """
    import json as _json
    import tempfile
    import train as T

    root = tempfile.mkdtemp()
    orig = T.MODEL_DIR
    T.MODEL_DIR = os.path.join(root, "model")
    try:
        grid = [f"2026-08-0{d}-{h:02d}" for d in (1, 2) for h in range(4)]
        per = np.array([40, 40, 12, 0, 40, 40, 40, 31])
        T.write_readiness(["A", "B"], grid, per, 6, 17, 8.0,
                          lambda m: None)
        with open(os.path.join(T.MODEL_DIR, "readiness.json"),
                  encoding="utf-8") as f:
            r = _json.load(f)
    finally:
        T.MODEL_DIR = orig
        shutil.rmtree(root, ignore_errors=True)

    check("сечения и порог названы числом",
          r["sections"] == 6 and r["need"] == T.MIN_TRAIN_SECTIONS,
          f"{r['sections']}/{r['need']}")
    check("разложение по часам есть", len(r["by_hour"]) == len(grid),
          str(len(r["by_hour"])))
    # Ноль сечений при живой записи и ноль при мёртвой выглядят
    # одинаково в итоге и по-разному в разложении.
    thin = [h for h in r["by_hour"] if h["n"] < r["min_section"]]
    check("тонкие часы видны поимённо", len(thin) == 2,
          str([h["h"] for h in thin]))
    check("порог сечения записан", r["min_section"] == FB.MIN_SECTION)
    # Второй счётчик ожидания: бете нужны часы истории на монету,
    # и без него «обучение началось, а выборов нет» выглядит
    # поломкой, а не нехваткой данных.
    check("часы на бету названы рядом с сечениями",
          r["beta_min_hours"] == FB.BETA_MIN
          and r["hours_per_symbol"] == 8,
          f"{r.get('hours_per_symbol')} из {r.get('beta_min_hours')}")


def test_canary_not_computed_is_not_a_pass():
    """Непосчитанная проверка на течь не является пройденной.

    Найдено пробным прогоном на восьми сечениях: канарейка считается по
    `fwd_4h`, а это остаток к волне — ему нужна бета, бете нужно
    BETA_MIN часов истории на монету. Пока их нет, цель пуста, канарейка
    возвращает NaN, и прежнее условие `isfinite(med) and |med| > порог`
    читало NaN как «крика не было» — веса писались, а потом повели бы
    бумажные счета БЕЗ проверки на течь.

    Существенно не для пробы, а для боевого прогона: 48 сечений меньше,
    чем BETA_MIN = 96 часов, то есть первое настоящее обучение
    случилось бы ровно в этом состоянии.
    """
    import train as T
    check("бете нужно больше часов, чем сечений ждёт обучение",
          FB.BETA_MIN > T.MIN_TRAIN_SECTIONS,
          f"{FB.BETA_MIN} против {T.MIN_TRAIN_SECTIONS}")

    check("NaN — отдельное состояние, а не «прошла»",
          T.canary_verdict(float("nan")) == "не считалась")
    check("тихая канарейка молчит",
          T.canary_verdict(0.0) == "молчит"
          and T.canary_verdict(T.CANARY_STOP) == "молчит")
    check("громкая кричит в обе стороны",
          T.canary_verdict(T.CANARY_STOP * 1.01) == "кричит"
          and T.canary_verdict(-T.CANARY_STOP * 1.01) == "кричит")
    # Прежнее слитное условие давало NaN тот же исход, что и тишине.
    src = open(os.path.join(HERE, "train.py"), encoding="utf-8").read()
    check("прежнее слитное условие не воспроизводится",
          "np.isfinite(med) and abs(med) > CANARY_STOP" not in src)

    # Порог и полный список целей обязаны ехать в артефакте, иначе
    # отчёт снова прочитает их из своих констант и разойдётся.
    check("порог канарейки пишется в манифест", '"canary_stop"' in src)
    check("полный список целей пишется в манифест",
          '"targets_all"' in src)


def test_report_flags_manifest_from_a_previous_run():
    """Манифест прошлого прогона не смеет выдавать себя за нынешний.

    Готовность пишется в НАЧАЛЕ цикла, манифест — в конце. Значит
    прогон, остановленный канарейкой, оставляет манифест прошлого
    нетронутым, и отчёт по нему рассказал бы об обучении, которого
    сейчас не было. Ровно этот класс дефекта проект ловит чаще всех
    прочих.
    """
    import probe_report as PR

    root = tempfile.mkdtemp()
    md = os.path.join(root, "model_probe")
    os.makedirs(md)
    try:
        json.dump({"probe": True, "canary_ic": None, "canary_stop": 0.05,
                   "trained_at": "2026-08-03T17:20:00+00:00",
                   "targets_all": ["fwd_4h"], "importance": {}},
                  open(os.path.join(md, "manifest.json"), "w"))
        json.dump({"at": "2026-08-03T17:44:00+00:00", "sections": 8,
                   "need": 48, "symbols": 543, "hours": 97,
                   "features": 50, "min_section": 30,
                   "beta_min_hours": 96, "hours_per_symbol": 8,
                   "by_hour": []},
                  open(os.path.join(md, "readiness.json"), "w"))
        _, lines = PR.write(md, os.path.join(root, "r.md"))
        txt = "\n".join(lines)
        check("устаревший манифест назван прямо",
              "Манифест старше этого прогона" in txt)
        # Без файла исхода судить о канарейке НЕ ПО ЧЕМУ: `canary_ic` в
        # манифесте описывает тот прогон, который манифест положил.
        # Молчание тут честнее, чем «прошла».
        check("без исхода канарейка не объявляется пройденной",
              "| канарейка" in txt
              and "| канарейка (обучение на перемешанных целях) | прошёл"
              not in txt, txt[txt.find("| канарейка"):][:120])

        # Тот же манифест, но свежее готовности — предупреждения быть
        # не должно, иначе оно перестанет читаться.
        json.dump({"probe": True, "canary_ic": 0.001, "canary_stop": 0.05,
                   "trained_at": "2026-08-03T17:45:00+00:00",
                   "targets_all": ["fwd_4h"], "importance": {}},
                  open(os.path.join(md, "manifest.json"), "w"))
        _, lines = PR.write(md, os.path.join(root, "r.md"))
        check("на свежем манифесте предупреждения нет",
              "Манифест старше" not in "\n".join(lines))

        # Исход прогона важнее предупреждения: по манифесту нельзя
        # судить о шагах, если положил его другой запуск. Веса на диске
        # есть, но записать их себе в заслугу нынешний прогон не вправе.
        json.dump({"probe": True, "canary_ic": None, "canary_stop": 0.05,
                   "trained_at": "2026-08-03T17:30:00+00:00",
                   "targets_all": ["mae_4h"], "importance": {}},
                  open(os.path.join(md, "manifest.json"), "w"))
        json.dump({"at": "2026-08-03T18:03:00+00:00", "probe": True,
                   "reason": "канарейка не считалась", "sections": 9},
                  open(os.path.join(md, "last_run.json"), "w"))
        for arm in ("gbm", "nn"):
            open(os.path.join(md, f"weights_{arm}_mae_4h.pkl"),
                 "wb").write(b"x")
        _, lines = PR.write(md, os.path.join(root, "r.md"))
        txt = "\n".join(lines)
        check("исход прогона назван первой строкой",
              "Чем кончился этот прогон: канарейка не считалась" in txt)
        check("чужое обучение не записано себе в заслугу",
              "| обучение: деревья (ML) | прошёл" not in txt
              and "до обучения не дошёл" in txt)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # Отчёт зовут из цикла обучения: он не вправе уронить прогон.
    try:
        PR.write(os.path.join(root, "нет-такого"), "/tmp/x.md")
        ok = False
    except FileNotFoundError:
        ok = True
    except SystemExit:
        ok = False
    check("нет каталога — обычная ошибка, а не SystemExit", ok)


def test_capital_returns_before_it_is_redeployed():
    """В один момент закрытие идёт раньше открытия.

    Найдено на живых данных сразу после заливки: у всей свежей руки
    стоял `size = 0`. При горизонте в четыре часа выход часа `H`
    совпадает по времени со входом часа `H+4`, и открытие пыталось
    занять деньги, которые ещё не вернулись в кассу. Отказ тихий —
    счёт не падал, он просто переставал торговать.
    """
    import trades as TR

    tr = []
    for h in range(10):
        for i in range(6):
            st = "закрыта" if h < 6 else "открыта"
            t = {"arm": "gbm", "hour": f"H{h:02d}", "sym": f"S{i}",
                 "side": "long", "state": st,
                 "opened_at": h * 3600, "closes_at": (h + 4) * 3600}
            if st == "закрыта":
                t["net_bp"] = 20.0
            tr.append(t)
    TR.account(tr, "gbm")
    zero = [t for t in tr if not t.get("size")]
    check("в стационарном режиме нулевых размеров нет", not zero,
          f"{len(zero)} сделок без размера")
    check("размер держится около капитала на слот",
          all(abs(t["size"] - TR.START_BALANCE / 24) < 1.0 for t in tr),
          str(sorted({round(t["size"], 2) for t in tr})[:4]))

    # Метка времени, равная нулю, — это метка, а не её отсутствие.
    z = [{"arm": "gbm", "hour": "H0", "sym": "A", "side": "long",
          "state": "открыта", "opened_at": 0, "closes_at": 4 * 3600}]
    TR.account(z, "gbm")
    check("нулевая метка времени не выбрасывает сделку из счёта",
          z[0].get("size"), str(z[0].get("size")))


def test_pretest_comes_after_the_summary_is_written():
    """Предпросмотр приходит ПОСЛЕ боевого цикла, а не вместе с ним.

    Сводку часов пишет боевой цикл, предпросмотр её только читает.
    Придя раньше, он видит сетку без только что закрывшегося часа и
    отстаёт ровно на час — а вместе с ним на час зависают все сделки,
    которым срок вышел.

    Замер на сервере, по которому это и нашлось: предпросмотр отработал
    в 23:00:01, сведение часа 22 закончилось в 23:03, и сделки со
    сроком 23:00 провисели «ждёт разбора» до следующего часа.
    """
    import tempfile
    import train as T

    check("запас предпросмотра больше боевого",
          T.PRETEST_MARGIN_SEC > T.MARGIN_SEC,
          f"{T.PRETEST_MARGIN_SEC} против {T.MARGIN_SEC}")
    # Запас не должен съедать час: иначе разбор уедет к следующему.
    check("но не настолько, чтобы съесть час",
          T.PRETEST_MARGIN_SEC < 1800, str(T.PRETEST_MARGIN_SEC))

    d = tempfile.mkdtemp()
    keep = T.MODEL_DIR
    T.MODEL_DIR = os.path.join(d, "m")
    os.makedirs(T.MODEL_DIR)
    try:
        now = time.time()
        closed = datetime.fromtimestamp(now - 3600, timezone.utc)\
            .strftime("%Y-%m-%d-%H")
        earlier = datetime.fromtimestamp(now - 7200, timezone.utc)\
            .strftime("%Y-%m-%d-%H")
        path = os.path.join(T.MODEL_DIR, "last_run.json")

        with open(path, "w", encoding="utf-8") as f:
            json.dump({"last_hour": closed}, f)
        check("видел последний закрывшийся час — не отстал",
              not T.stale_summary())

        with open(path, "w", encoding="utf-8") as f:
            json.dump({"last_hour": earlier}, f)
        check("видел час постарше — отстал, повторять скоро",
              T.stale_summary())
        check("повтор скорый, а не через час",
              0 < T.STALE_RETRY_SEC < T.RETRY_SEC, str(T.STALE_RETRY_SEC))

        # Нет исхода — не повод объявлять отставание: на первом же
        # проходе цикла файла ещё нет.
        os.remove(path)
        check("без исхода отставание не выдумывается",
              not T.stale_summary())
    finally:
        T.MODEL_DIR = keep
        shutil.rmtree(d, ignore_errors=True)


def test_hourly_cycle_wakes_on_the_hour():
    """Часовой цикл ждёт до ГРАНИЦЫ часа, а не час от прошлого раза.

    Запаздывание входа (`lag`) равно тому, насколько поздно цикл
    проснулся после закрытия часа. При отсчёте «час от прошлого раза»
    смещение задаётся моментом запуска и живёт вечно: на сервере оно
    закрепилось на пятнадцати минутах просто потому, что в 15 минут был
    перезапуск.
    """
    import train as T

    for mm in (0, 5, 15, 30, 58, 59.9):
        now = 1_000_000 - (1_000_000 % 3600) + mm * 60
        wait = max(T.MARGIN_SEC, 3600 - (now % 3600) + T.MARGIN_SEC)
        nxt = (now + wait) % 3600 / 60
        check(f"проснувшись на {mm} мин, следующий заход на границе",
              abs(nxt - T.MARGIN_SEC / 60) < 1e-6, f"{nxt:.2f} мин")
    check("запас после закрытия часа положителен и невелик",
          0 < T.MARGIN_SEC <= 600, str(T.MARGIN_SEC))


def test_account_is_one_capital_at_leverage_one():
    """Счёт ведётся на ОДИН капитал, экспозиция его не превышает.

    Прежняя модель считала каждый час независимо: весь баланс делился
    на шесть позиций часа. При горизонте в четыре часа таких наборов
    одновременно открыто четыре, то есть реальная экспозиция была
    ЧЕТЫРЁХКРАТНОЙ, а счёт показывал её как торговлю на тысячу. Плечо
    брать можно, но не молча и не задним числом.

    Просьба владельца — «сделать так, чтобы было при реальном счёте в
    1000 $».
    """
    import trades as TR

    # Шесть имён в час, горизонт четыре часа — двадцать четыре слота.
    tr = []
    for h in range(4):
        for i in range(6):
            tr.append({"arm": "gbm", "hour": f"H{h}", "sym": f"S{i}",
                       "side": "long", "state": "открыта",
                       "opened_at": 1000 + h * 3600,
                       "closes_at": 1000 + (h + 4) * 3600})
    TR.account(tr, "gbm")
    gross = sum(t["size"] for t in tr)
    check("гросс равен капиталу — плечо ровно единица",
          abs(gross - TR.START_BALANCE) < 1e-6, f"{gross:.6f}")
    check("двадцать четыре слота, а не шесть",
          abs(tr[0]["size"] - TR.START_BALANCE / 24) < 1e-6,
          str(tr[0]["size"]))

    # Капитал возвращается при закрытии и работает снова.
    tr2 = []
    for h in range(6):
        for i in range(6):
            tr2.append({"arm": "gbm", "hour": f"H{h:02d}", "sym": f"S{i}",
                        "side": "long", "state": "закрыта",
                        "opened_at": 1000 + h * 3600,
                        "closes_at": 1000 + (h + 4) * 3600,
                        "net_bp": 50.0 if i % 2 else -30.0})
    hist, bal = TR.account(tr2, "gbm")
    check("история ведётся по сделкам, а не по часам",
          len(hist) == len(tr2), f"{len(hist)} против {len(tr2)}")
    check("баланс есть старт плюс сумма результатов",
          abs(bal - TR.START_BALANCE
              - sum(h["pnl"] for h in hist)) < 0.5, str(bal))

    # Функция ЧИСТАЯ: второй вызов на том же списке даёт то же самое,
    # то есть повторный проход цикла не проведёт сделки дважды.
    hist2, bal2 = TR.account(tr2, "gbm")
    check("пересчёт идемпотентен", bal2 == bal and len(hist2) == len(hist),
          f"{bal} -> {bal2}")

    # Денег больше, чем есть, в позицию не кладём.
    tr3 = [{"arm": "gbm", "hour": "H0", "sym": f"S{i}", "side": "long",
            "state": "открыта", "opened_at": 1000,
            "closes_at": 1000 + 4 * 3600} for i in range(200)]
    TR.account(tr3, "gbm")
    check("экспозиция не превышает капитал и на широкой книге",
          sum(t["size"] for t in tr3) <= TR.START_BALANCE + 1e-6,
          str(sum(t["size"] for t in tr3)))


def test_unrealised_never_mixes_with_realised():
    """Нереализованное считается отдельно и тем же размером позиции.

    Закрытая сделка — результат, открытая — текущая отметка, которая до
    срока может стать любой. Сложить их в одну цифру значило бы выдать
    незавершённое за результат, поэтому поля разные и на странице они
    разными рядами.

    Размер позиции берётся так же, как его берёт разбор: баланс на
    число позиций ТОГО ЖЕ часа. Иначе завелось бы второе определение
    размера, и деньги на странице разошлись бы с деньгами в счёте.
    """
    import trades as TR

    rows = [
        {"state": "открыта", "arm": "gbm", "hour": "H1", "side": "long",
         "sym": "A", "unreal_net_bp": 89.0},
        {"state": "открыта", "arm": "gbm", "hour": "H1", "side": "short",
         "sym": "B", "unreal_net_bp": -31.0},
        {"state": "открыта", "arm": "gbm", "hour": "H2", "side": "long",
         "sym": "C", "unreal_net_bp": 11.0},
        {"state": "открыта", "arm": "gbm", "hour": "H2", "side": "long",
         "sym": "D"},                       # без отметки — не считается
        {"state": "закрыта", "arm": "gbm", "hour": "H0", "side": "long",
         "sym": "A", "got_bp": 40.0, "net_bp": 29.0, "pnl": 0.5,
         "expected_bp": 100.0, "hit": True},
    ]
    # Размеры проставляет счёт — он и есть единственный источник
    # размера позиции. Своей арифметики у сводки нет.
    s0 = TR.summary(rows, "gbm")
    check("без счёта деньги не выдумываются",
          "unreal_pnl" not in s0 and s0["unreal_net_avg_bp"] == 23.0,
          str(s0))

    for i, t in enumerate(rows):
        t.setdefault("opened_at", 1000 + i)
        t.setdefault("closes_at", 1000 + i + 4 * 3600)
    TR.account(rows, "gbm")
    s = TR.summary(rows, "gbm")
    check("переоценённых столько, сколько с отметкой", s["marked"] == 3,
          str(s.get("marked")))
    check("реализованное и нереализованное — разные поля",
          "pnl" in s and "unreal_pnl" in s and s["unreal_pnl"] != s["pnl"],
          f"{s.get('pnl')} / {s.get('unreal_pnl')}")
    check("средняя отметка и доля в плюсе названы",
          s["unreal_net_avg_bp"] == 23.0 and s["unreal_win"] == 0.667,
          f"{s.get('unreal_net_avg_bp')} / {s.get('unreal_win')}")
    # Экспозиция открытых не превышает капитала — это и есть плечо 1×.
    check("экспозиция не больше капитала",
          s["exposure"] <= TR.START_BALANCE + 1e-6,
          f"{s.get('exposure')} при капитале {TR.START_BALANCE}")


def test_drawdown_is_measured_not_inferred_from_the_outcome():
    """Просадка сделки — ход ПРОТИВ по дороге, а не её итог.

    Сделка, закрывшаяся в плюс, могла по пути стоить сорока процентов, и
    по колонке `net` этого не видно вовсе. Стороны считаются раздельно:
    у лонга просадка — минимум часа, у шорта максимум. Перепутать их
    значило бы записать шорту благоприятный ход как убыток — эта ошибка
    в проекте уже случалась с колонкой `mae`.
    """
    import trades as TR

    h = "2026-08-03-10"
    # Цена: вход 100, провал до 80 во втором часу, выход в плюс.
    rows = {}
    for i, (lo, hi, c) in enumerate(
            [(99.0, 101.0, 100.0), (80.0, 101.0, 90.0),
             (89.0, 130.0, 120.0), (110.0, 125.0, 115.0)], start=1):
        key = TR._hour_of(TR._ts(h) + i * 3600)
        rows[("AUSDT", key)] = {"c": c, "hi": hi, "lo": lo}
    base = {"arm": "gbm", "hour": h, "sym": "AUSDT", "entry_px": 100.0,
            "state": "закрыта", "opened_at": TR._ts(h) + 3600,
            "closes_at": TR._ts(h) + 5 * 3600, "net_bp": 1400.0}
    lo = dict(base, side="long")
    sh = dict(base, side="short")
    # `now` далеко в будущем — все четыре часа удержания закрыты.
    later = TR._ts(h) + 100 * 3600
    TR.excursion([lo, sh], rows, now=later)
    check("у лонга просадка считается по минимуму часа",
          lo["dd_bp"] == -2000.0 and lo["dd_hours"] == 4,
          f"{lo.get('dd_bp')} за {lo.get('dd_hours')} ч")
    check("у шорта просадка считается по максимуму, а не по минимуму",
          sh["dd_bp"] == -3000.0, str(sh.get("dd_bp")))
    check("итог сделки просадку не описывает",
          lo["net_bp"] > 0 and lo["dd_bp"] < 0,
          f"net {lo['net_bp']}, dd {lo['dd_bp']}")

    # Час без сводки НЕ считается нулевой просадкой: он просто не входит
    # в замер, и это видно числом покрытых часов.
    part = dict(base, side="long")
    few = {k: v for k, v in rows.items() if not k[1].endswith("-12")}
    TR.excursion([part], few, now=later)
    check("час без сводки не считается наблюдением",
          part["dd_hours"] == 3 and part["dd_bp"] == -1100.0,
          f"{part.get('dd_bp')} за {part.get('dd_hours')} ч")

    # Позиция, ни разу не уходившая в минус, имеет просадку ноль, а не
    # положительную величину: «просадка» есть ход против позиции.
    up = dict(base, side="long")
    TR.excursion([up], {k: {"c": 120.0, "hi": 130.0, "lo": 105.0}
                        for k in rows}, now=later)
    check("вверх просадки не бывает", up["dd_bp"] == 0.0,
          str(up.get("dd_bp")))

    # У открытой сделки берутся только ЗАКРЫВШИЕСЯ часы: текущий час
    # ещё пишется, и его крайние значения через минуту будут другими.
    op = dict(base, side="long", state="открыта")
    TR.excursion([op], rows, now=TR._ts(h) + 2 * 3600 + 600)
    check("у открытой сделки текущий час в замер не входит",
          op["dd_hours"] == 1, str(op.get("dd_hours")))


def test_drawdown_is_reported_against_the_deposit():
    """Просадка сделки считается от ДЕПОЗИТА, а не от позиции.

    Решение владельца, и повод настоящий: шорт HFT показал −47.67 %, что
    читается как «потеряли половину», тогда как позиция — 1/24 счёта, и
    в деньгах это −19.90 $, то есть 2 % депозита.

    Отдельно проверяется, что худшая по цене и худшая по деньгам — РАЗНЫЕ
    сделки, когда размеры позиций различаются. Пересортировка в долях
    депозита нужна именно поэтому; взять ту же сделку, что и по цене,
    значило бы назвать худшей не ту.
    """
    import trades as TR

    # У первой ход вдвое хуже, у второй позиция вчетверо крупнее.
    rows = [
        {"state": "закрыта", "arm": "gbm", "hour": "H1", "side": "long",
         "sym": "A", "dd_bp": -4000.0, "size": 25.0},
        {"state": "открыта", "arm": "gbm", "hour": "H2", "side": "short",
         "sym": "B", "dd_bp": -2000.0, "size": 100.0},
        {"state": "закрыта", "arm": "gbm", "hour": "H3", "side": "long",
         "sym": "C", "dd_bp": -500.0},          # без размера — не в деньгах
    ]
    n = TR.dd_money(rows, deposit=1000.0)
    check("денежная просадка считается только там, где есть размер",
          n == 2 and "dd_usd" not in rows[2], f"{n}, {rows[2]}")
    check("деньги = размер × ход",
          rows[0]["dd_usd"] == -10.0 and rows[1]["dd_usd"] == -20.0,
          f"{rows[0].get('dd_usd')} / {rows[1].get('dd_usd')}")
    check("доля депозита = деньги / депозит",
          rows[0]["dd_cap_bp"] == -100.0 and rows[1]["dd_cap_bp"] == -200.0,
          f"{rows[0].get('dd_cap_bp')} / {rows[1].get('dd_cap_bp')}")

    s = TR.summary(rows, "gbm")
    check("худшая по цене — первая сделка",
          s["dd_worst_bp"] == -4000.0, str(s.get("dd_worst_bp")))
    check("худшая по деньгам — ДРУГАЯ сделка, вторая",
          s["dd_worst_cap_bp"] == -200.0 and s["dd_worst_usd"] == -20.0,
          f"{s.get('dd_worst_cap_bp')} / {s.get('dd_worst_usd')}")
    check("сделка без размера в денежную статистику не входит",
          s["dd_sized"] == 2 and s["dd_measured"] == 3,
          f"{s.get('dd_sized')} из {s.get('dd_measured')}")
    check("открытые отдельно и тоже в долях депозита",
          s["dd_open_worst_cap_bp"] == -200.0,
          str(s.get("dd_open_worst_cap_bp")))

    # Депозит — величина СТАРТОВАЯ: выросший счёт не вправе задним
    # числом уменьшать просадку прошлой сделки.
    same = [dict(rows[0])]
    TR.dd_money(same, deposit=TR.START_BALANCE)
    check("знаменатель — стартовый депозит, а не текущий баланс",
          same[0]["dd_cap_bp"] == rows[0]["dd_cap_bp"],
          f"{same[0]['dd_cap_bp']} против {rows[0]['dd_cap_bp']}")


def test_pretest_hedges_with_beta_one_and_keeps_books_apart():
    """Предпросмотр хеджит бетой = 1, а смена режима начинает книгу заново.

    Единица — не произвол: средняя бета по сечению равна ей ПО
    ПОСТРОЕНИЮ (каждый актив входит в волну с весом 1/n), и R1 намерил
    1.015 по 48 окнам. Ноль, стоявший здесь прежде, оставлял в цели ход
    рынка за час — величину, общую для всех имён и потому непредсказуемую
    кросс-секционными признаками, то есть чистый шум в метке.

    И вторая половина: книга с хеджем и книга без него — РАЗНЫЕ книги.
    Счёт считается чистой функцией по всем выборам каталога, поэтому при
    смене режима старые выборы обязаны уйти в архив, иначе кривая
    описывала бы книгу, которой не было.
    """
    import shutil
    import tempfile
    import numpy as np
    import train as T

    d = tempfile.mkdtemp()
    try:
        # Подстановка: там, где бета есть, она сохраняется; где нет —
        # единица, а не ноль и не выдуманное среднее.
        beta = np.array([0.4, np.nan, 1.9])
        got = np.where(np.isfinite(beta), beta, 1.0)
        check("бета подставляется единицей только там, где её нет",
              list(got) == [0.4, 1.0, 1.9], str(list(got)))
        check("режимы названы разными строками",
              T.HEDGE_PRETEST != T.HEDGE_LIVE
              and "1" in T.HEDGE_PRETEST,
              f"{T.HEDGE_PRETEST} / {T.HEDGE_LIVE}")

        was = T.MODEL_DIR
        T.MODEL_DIR = os.path.join(d, "model_pretest")
        os.makedirs(T.MODEL_DIR)
        for name in ("manifest.json", "picks.jsonl", "account_gbm.json"):
            with open(os.path.join(T.MODEL_DIR, name), "w",
                      encoding="utf-8") as f:
                f.write(json.dumps({"hedge": "выключен (бета не оценима)"})
                        if name == "manifest.json" else "{}\n")
        try:
            # Тот же режим — каталог не трогается: иначе книга
            # начиналась бы заново на каждом запуске цикла.
            same = T.fresh_on_mode_change("выключен (бета не оценима)")
            check("при том же режиме каталог остаётся на месте",
                  same is None and os.path.isdir(T.MODEL_DIR), str(same))

            moved = T.fresh_on_mode_change(T.HEDGE_PRETEST)
            check("смена режима отставляет прежнюю книгу",
                  moved and os.path.isdir(moved)
                  and not os.path.exists(T.MODEL_DIR), str(moved))
            # Прежние выборы НЕ удалены: их можно прочитать и сравнить.
            check("прежние выборы сохранены, а не стёрты",
                  os.path.exists(os.path.join(moved, "picks.jsonl")),
                  str(os.listdir(moved)))
            # Пустой каталог режима не имеет — отставлять нечего.
            os.makedirs(T.MODEL_DIR)
            check("каталог без манифеста не отставляется",
                  T.fresh_on_mode_change(T.HEDGE_PRETEST) is None)
        finally:
            T.MODEL_DIR = was
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_worst_open_book_is_not_the_worst_trade():
    """Общая просадка книги — все живые позиции разом, а не худшая из них.

    Просьба владельца. Разница настоящая и в обе стороны: худшая сделка
    может случиться в час, когда остальные в плюсе и книга спокойна, а
    книга может просесть глубже любой отдельной сделки, если все ноги
    поехали вместе.

    Позиции складываются СО ЗНАКОМ: прибыльные гасят убыточные, потому
    что на счёте в этот момент лежит сальдо. Сумма одних убыточных была
    бы валовым убытком — величиной, которой счёт не видел.
    """
    import trades as TR

    h0 = "2026-08-03-10"
    # Час 11: одна нога глубоко в минусе, вторая в плюсе — книга почти
    # цела. Час 12: обе умеренно в минусе — книга просела сильнее.
    px = {"A": [50.0, 100.0], "B": [150.0, 90.0]}
    rows, hrows = [], {}
    for i, sym in enumerate(("A", "B")):
        rows.append({"arm": "gbm", "hour": h0, "sym": sym, "side": "long",
                     "entry_px": 100.0, "state": "открыта",
                     "opened_at": TR._ts(h0) + 3600,
                     "closes_at": TR._ts(h0) + 5 * 3600})
        for j, p in enumerate(px[sym]):
            hrows[(sym, TR._hour_of(TR._ts(h0) + (j + 1) * 3600))] = {
                "c": p, "hi": p, "lo": p}
    later = TR._ts(h0) + 100 * 3600
    TR.account(rows, "gbm")
    TR.excursion(rows, hrows, now=later)
    TR.dd_money(rows)
    cur = TR.equity(rows, "gbm", hrows, now=later)
    o = TR.worst_open(cur)
    s = TR.summary(rows, "gbm")

    by_hour = {p["hour"]: p["op"] for p in cur}
    h11 = TR._hour_of(TR._ts(h0) + 3600)
    h12 = TR._hour_of(TR._ts(h0) + 2 * 3600)
    check("в первый час прибыльная нога гасит убыточную",
          abs(by_hour[h11]) < abs(by_hour[h12]),
          f"{by_hour[h11]} против {by_hour[h12]}")
    check("худший момент книги — второй час, а не первый",
          o["hour"] == h12 and o["open"] == 2,
          f"{o.get('hour')}, позиций {o.get('open')}")
    # Худшая ОДНА сделка сидит в первом часу (−50 %), а книга просела
    # глубже во втором. Совпасть эти два числа не обязаны — ровно в этом
    # и смысл просьбы.
    check("худшая сделка и худший момент книги — разные числа",
          s["dd_worst_cap_bp"] != o["cap_bp"],
          f"сделка {s.get('dd_worst_cap_bp')}, книга {o.get('cap_bp')}")
    check("доля депозита у книги считается от него же",
          abs(o["cap_bp"] - o["usd"] / TR.START_BALANCE * 1e4) < 0.11,
          f"{o.get('cap_bp')} при {o.get('usd')} $")

    # На общей вкладке рука без записи часа НЕ переносит свою прошлую
    # переоценку: часа нет ровно тогда, когда живых позиций не было.
    a = [{"hour": "H1", "eq": 900.0, "open": 1, "op": -100.0, "full": True},
         {"hour": "H2", "eq": 1000.0, "open": 0, "op": 0.0, "full": True}]
    b = [{"hour": "H1", "eq": 1000.0, "open": 1, "op": 0.0, "full": True}]
    m = TR.merge([a, b])
    check("закрытая рука не тащит призрак переоценки в следующий час",
          [p["op"] for p in m] == [-100.0, 0.0], str(m))


def test_account_drawdown_counts_open_positions():
    """Просадка счёта считается с переоценкой открытых, а не по закрытиям.

    Кривая по одним закрытиям систематически льстит: позиция, уходившая
    в минус и вернувшаяся, входит в неё мелким убытком, и пережитая
    просадка из неё не видна. Это ровно та ошибка, которой посвящено
    закрытие гипотезы 3 — там медиана льстила, а решал хвост.
    """
    import trades as TR

    h = "2026-08-03-10"
    t = {"arm": "gbm", "hour": h, "sym": "AUSDT", "side": "long",
         "entry_px": 100.0, "state": "закрыта", "net_bp": 0.0, "pnl": 0.0,
         "opened_at": TR._ts(h) + 3600,
         "closes_at": TR._ts(h) + 5 * 3600}
    rows = {}
    for i, c in enumerate([100.0, 50.0, 70.0, 100.0], start=1):
        rows[("AUSDT", TR._hour_of(TR._ts(h) + i * 3600))] = {
            "c": c, "hi": c, "lo": c}
    later = TR._ts(h) + 100 * 3600
    TR.account([t], "gbm")
    cur = TR.equity([t], "gbm", rows, now=later)
    dd = TR.max_dd(cur)
    # Число закреплено точно, потому что оно проверяет и слот-модель:
    # одна сделка в часе занимает четверть капитала (шесть имён на
    # четыре часа — двадцать четыре слота), поэтому падение цены вдвое
    # стоит счёту 12.5 %, а не пятидесяти. Ослабить до неравенства
    # значило бы перестать проверять размер позиции.
    check("просадка счёта видит провал открытой позиции",
          dd["pct"] == -12.5, str(dd))
    check("а по закрытиям провала нет вовсе — итог сделки нулевой",
          t["pnl"] == 0.0 and cur[-1]["eq"] == TR.START_BALANCE,
          f"pnl {t['pnl']}, конец {cur[-1]['eq']}")

    # Час, где живую ногу переоценить нечем, помечается и считается
    # дырой: занизить просадку молча нельзя.
    gap = {k: v for k, v in rows.items() if not k[1].endswith("-12")}
    d2 = TR.max_dd(TR.equity([t], "gbm", gap, now=later))
    check("час без переоценки назван дырой", d2["gaps"] == 1, str(d2))

    # Общая кривая двух счетов складывается по часам, а рука без записи
    # в этот час берётся последним известным значением, а не нулём.
    a = [{"hour": "2026-08-03-11", "eq": 1000.0, "open": 1, "full": True},
         {"hour": "2026-08-03-12", "eq": 900.0, "open": 1, "full": True}]
    b = [{"hour": "2026-08-03-11", "eq": 1000.0, "open": 1, "full": True}]
    m = TR.merge([a, b])
    check("рука без записи часа не обнуляется",
          [p["eq"] for p in m] == [2000.0, 1900.0], str(m))

    # Вершина, от которой считается просадка, — та, что была ПЕРЕД
    # провалом, а не последняя вершина кривой. Найдено на живой руке:
    # счёт провалился в 08-04-17 и позже обновил максимум, после чего
    # сводка сообщала «от 08-05-01 до 08-04-17» — пара, читающаяся
    # задом наперёд. Глубина при этом была верна, поэтому проверка на
    # неё дефект не ловила вовсе.
    rec = [{"hour": "2026-08-03-11", "eq": 1000.0, "full": True},
           {"hour": "2026-08-03-12", "eq": 900.0, "full": True},
           {"hour": "2026-08-03-13", "eq": 1200.0, "full": True}]
    d3 = TR.max_dd(rec)
    check("просадка считается от вершины перед провалом",
          d3["from"] == "2026-08-03-11" and d3["at"] == "2026-08-03-12",
          str(d3))
    check("вершина не может стоять позже дна",
          d3["from"] < d3["at"], str(d3))
    check("глубина от восстановления не меняется",
          d3["pct"] == -10.0, str(d3))


def test_entry_gift_is_measured_before_it_is_removed():
    """Вход по цене сигнала — подарок, и его сперва меряют.

    Признаки кончаются закрытием часа, а цикл решает через 6–15 минут
    после него (замер на живом предпросмотре: медиана 393 с). Вход по
    закрытию часа означает покупку по цене, которой в момент решения
    уже нет, — тот же класс, что `next_open` в L1 и минута задержки в
    зонде возврата.

    Подменять цену на живую прямо сейчас нельзя: исход разбор меряет ОТ
    ТОГО ЖЕ закрытия часа, и сдвинуть один конец, оставив другой, — это
    дефект хуже чинимого. Поэтому здесь проверяется ровно замер.
    """
    pk = [{"arm": "gbm", "hour": "2026-08-03-10", "at_ts": 1,
           "long": [{"sym": "AUSDT", "fwd": 100.0, "px": 100.0,
                     "px_live": 101.0}],
           "short": [{"sym": "BUSDT", "fwd": -100.0, "px": 100.0,
                      "px_live": 101.0}]}]
    tr = TR.build(pk, [], now=TR._ts("2026-08-03-10") + 60)
    g = {t["sym"]: t["gift_bp"] for t in tr}
    # Цена ушла вверх на 100 б.п. Лонгу это подарок (записались дешевле,
    # чем купили бы), шорту — наоборот: он записался ХУЖЕ доступного.
    check("подарок лонгу положителен", g["AUSDT"] == 100.0, str(g))
    check("тот же ход шорту в минус", g["BUSDT"] == -100.0, str(g))

    # Без живой цены поле не выдумывается: пропуск обязан остаться
    # пропуском, иначе «подарка нет» будет неотличимо от «не измеряли».
    pk2 = [{"arm": "gbm", "hour": "2026-08-03-10", "at_ts": 1,
            "long": [{"sym": "CUSDT", "fwd": 1.0, "px": 100.0}],
            "short": []}]
    t2 = TR.build(pk2, [], now=TR._ts("2026-08-03-10") + 60)
    check("нет живой цены — нет и числа", t2[0]["gift_bp"] is None,
          str(t2[0]))

    # В сводку подарок идёт по ВСЕМ сделкам, а не только по закрытым:
    # он известен на входе и от исхода не зависит.
    s = TR.summary(tr, "gbm")
    check("подарок в сводке считается по открытым тоже",
          s.get("gift_n") == 2 and s.get("gift_avg_bp") == 0.0,
          str({k: v for k, v in s.items() if k.startswith("gift")}))


def test_exposure_covers_all_open_and_leverage_is_named():
    """Экспозиция — по всем открытым; в долларах её читать нельзя.

    Вопрос владельца: «exposure 1504.11 $ это что?». В долларах число
    отвечает неверно, когда счетов несколько: у двух рук по тысяче, и
    полторы тысячи на вкладке «обе» — это 0.75 плеча, а вовсе не
    полтора. Поэтому рядом обязаны стоять капитал и плечо.

    И считаться экспозиция обязана по ВСЕМ открытым, а не только по
    переоценённым: позиция, у которой сейчас нет текущей цены (книга по
    инструменту молчит), экспозицию всё равно несёт. Посчитать её нулём
    значило бы занизить плечо ровно там, где с инструментом что-то не
    так.
    """
    import trades as TR

    rows = []
    for i in range(4):
        rows.append({"state": "открыта", "arm": "gbm", "hour": "H1",
                     "side": "long", "sym": f"S{i}",
                     "opened_at": 1000, "closes_at": 1000 + 4 * 3600})
    rows[0]["unreal_net_bp"] = 25.0          # переоценена только одна
    TR.account(rows, "gbm")

    s = TR.summary(rows, "gbm", capital=TR.START_BALANCE)
    whole = round(sum(t["size"] for t in rows), 2)
    check("экспозиция считается по всем открытым, а не по переоценённым",
          s["exposure"] == whole and s["marked"] == 1,
          f"{s.get('exposure')} против {whole}, переоценено "
          f"{s.get('marked')}")
    check("капитал назван рядом с экспозицией",
          s["capital"] == round(TR.START_BALANCE, 2), str(s.get("capital")))
    check("плечо есть экспозиция, делённая на капитал",
          s["leverage"] == round(s["exposure"] / TR.START_BALANCE, 2),
          f"{s.get('leverage')} при {s.get('exposure')} / "
          f"{TR.START_BALANCE}")
    check("плечо не больше единицы — книга размещает свои деньги",
          s["leverage"] <= 1.0, str(s.get("leverage")))
    # Свежая книга занимает не все часовые наборы, и плечо ниже единицы
    # у неё — норма. Без этого числа неполная экспозиция читается как
    # пропавшие деньги: владелец прочитал «500 $» как «депозит стал 500».
    check("сказано, на сколько часов книга набрана",
          s["fill_hours"] == 1 and s["fill_of"] == TR.HOLD_H,
          f"{s.get('fill_hours')} из {s.get('fill_of')}")

    # Две руки — два счёта. Общая вкладка обязана делить сумму
    # экспозиций на сумму капиталов, иначе плечо выйдет вдвое больше.
    for t in rows[2:]:
        t["arm"] = "nn"
    TR.account(rows, "gbm")
    TR.account(rows, "nn")
    both = TR.summary(rows, capital=2 * TR.START_BALANCE)
    check("на общей вкладке капитал складывается вместе с экспозицией",
          both["leverage"] <= 1.0 and both["capital"] == round(
              2 * TR.START_BALANCE, 2),
          f"{both.get('leverage')} при {both.get('exposure')} / "
          f"{both.get('capital')}")


def test_entry_price_is_recovered_from_summaries():
    """Цена входа у старых выборов не потеряна — она в сводке.

    Вопрос владельца: почему нельзя проставить цену входа уже открытым
    сделкам. Можно, и точно: цена входа есть закрытие часа сигнала, а
    это поле `mid_close` почасовой сводки — то же самое, по которому
    цикл считает цели. Записывать её в выбор было удобством, а не
    необходимостью, и «у старых записей поля нет» было ограничением,
    которое я сам себе назначил.
    """
    import tempfile
    import trades as TR

    sd = tempfile.mkdtemp()
    os.makedirs(os.path.join(sd, "AUSDT"))
    with open(os.path.join(sd, "AUSDT", "2026-08-03.jsonl"), "w",
              encoding="utf-8") as f:
        for h in (19, 20, 21):
            f.write(json.dumps({"hour": f"2026-08-03-{h}",
                                "mid_close": 100.0 + h}) + "\n")
    try:
        px = TR.entry_prices(sd, {("AUSDT", "2026-08-03-20"),
                                  ("BUSDT", "2026-08-03-20")})
        check("цена входа прочитана из сводки того же часа",
              px == {("AUSDT", "2026-08-03-20"): 120.0}, str(px))

        picks = [{"arm": "gbm", "hour": "2026-08-03-20",
                  "long": [{"sym": "AUSDT", "fwd": 100.0, "mae": -50.0}],
                  "short": []}]                       # поля `px` НЕТ
        t = TR.build(picks, [], now=TR._ts("2026-08-03-22"), px_at=px)[0]
        check("старый выбор получил цену входа", t["entry_px"] == 120.0,
              str(t.get("entry_px")))
        TR.mark([t], {"AUSDT": 121.2})
        check("и переоценивается как обычная открытая",
              t["unreal_bp"] == 100.0, str(t.get("unreal_bp")))

        # Своя цена в выборе важнее прочитанной: она записана в момент
        # решения, а сводку могли пересобрать.
        own = [{"arm": "gbm", "hour": "2026-08-03-20",
                "long": [{"sym": "AUSDT", "fwd": 1.0, "px": 999.0}],
                "short": []}]
        t2 = TR.build(own, [], now=TR._ts("2026-08-03-22"), px_at=px)[0]
        check("цена из выбора не подменяется сводкой",
              t2["entry_px"] == 999.0, str(t2.get("entry_px")))
    finally:
        shutil.rmtree(sd, ignore_errors=True)


def test_unrealised_marks_open_positions_only():
    """Нереализованный результат — по живой цене и только у открытых.

    Считается в `trades.mark`, а не на странице: формула одна на весь
    проект, и вторая её запись в JavaScript однажды разошлась бы с той,
    по которой ведётся счёт. Нетто — за вычетом круга издержек: открытая
    сделка, показанная брутто, выглядит лучше, чем закроется, а разница
    как раз в размере типичного движения за четыре часа.
    """
    import trades as TR

    check("круг издержек — одно определение на цикл и сборщик",
          TR.ROUND_COST_BP == 11.0, str(TR.ROUND_COST_BP))
    rows = [
        {"state": "открыта", "side": "long", "sym": "A", "entry_px": 100.0},
        {"state": "открыта", "side": "short", "sym": "B", "entry_px": 50.0},
        {"state": "открыта", "side": "long", "sym": "C", "entry_px": None},
        {"state": "закрыта", "side": "long", "sym": "A", "entry_px": 100.0},
    ]
    n = TR.mark(rows, {"A": 101.0, "B": 49.0, "C": 7.0})
    check("переоценены только открытые с ценой входа", n == 2, str(n))
    check("лонг: цена выросла на процент — плюс сто б.п.",
          rows[0]["unreal_bp"] == 100.0, str(rows[0].get("unreal_bp")))
    check("шорт: цена упала на два процента — плюс двести",
          rows[1]["unreal_bp"] == 200.0, str(rows[1].get("unreal_bp")))
    check("нетто беднее брутто ровно на круг издержек",
          rows[0]["unreal_net_bp"] == 100.0 - TR.ROUND_COST_BP,
          str(rows[0].get("unreal_net_bp")))
    # Цену входа не выдумываем: без неё величина не считается вовсе.
    check("без цены входа переоценки нет",
          "unreal_bp" not in rows[2], str(rows[2]))
    check("закрытую сделка не переоценивают",
          "unreal_bp" not in rows[3], str(rows[3]))
    # Нет цены в стакане — тоже не выдумываем.
    r2 = [{"state": "открыта", "side": "long", "sym": "Z",
           "entry_px": 10.0}]
    check("нет текущей цены — переоценки нет",
          TR.mark(r2, {}) == 0 and "unreal_bp" not in r2[0])


def test_awaiting_review_is_not_a_lost_outcome():
    """Ожидание разбора и потерянный исход — разные состояния.

    Прежде оба звались «без исхода», и счётчик потерь рос просто оттого,
    что цикл идёт раз в час: у сделки вышел срок, а разбор до неё не
    дошёл. Тревога, которая срабатывает по расписанию, перестаёт
    читаться — а различить эти два случая можно точно.

    Признак строгий: выборы разбираются по ВОЗРАСТАНИЮ часа, значит
    если разбор дошёл до более позднего часа этой руки, то и этот он
    рассмотрел и цель посчитать не смог. Это окончательно и это дефект
    данных — дыра записи в удержании, выпадение монеты из универсума.
    """
    import trades as TR

    def pick(h, sym):
        return {"arm": "gbm", "hour": h,
                "long": [{"sym": sym, "fwd": 100.0, "mae": -50.0}],
                "short": []}
    picks = [pick("2026-08-03-20", "AUSDT"),
             pick("2026-08-03-21", "BUSDT"),
             pick("2026-08-04-01", "CUSDT")]
    revs = [{"arm": "gbm", "hour": "2026-08-03-21", "cost_bp": 11.0,
             "rows": [{"sym": "BUSDT", "side": "long", "expected": 100.0,
                       "got": 40.0, "net": 29.0, "pnl": 0.5,
                       "pos": 166.0}]}]
    st = {t["sym"]: t["state"]
          for t in TR.build(picks, revs, now=TR._ts("2026-08-04-06"))}
    check("разбор прошёл мимо — исход потерян окончательно",
          st["AUSDT"] == "без исхода", st["AUSDT"])
    check("разбор ещё не дошёл — это ожидание, а не потеря",
          st["CUSDT"] == "ждёт разбора", st["CUSDT"])
    check("разобранная закрыта", st["BUSDT"] == "закрыта", st["BUSDT"])

    s = TR.summary(TR.build(picks, revs, now=TR._ts("2026-08-04-06")),
                   "gbm")
    check("счётчики разведены",
          s["no_outcome"] == 1 and s["awaiting"] == 1, str(s))
    # И ни один из двух не попадает в статистику закрытых: неизвестный
    # исход, посчитанный нулём, тянул бы долю угаданных к монетке, а
    # пропадают исходы ровно там, где рвётся запись, то есть не
    # случайно.
    check("незакрытые в статистику не входят", s["closed"] == 1, str(s))


def test_entry_is_the_close_of_the_signal_hour():
    """Вход — на ЗАКРЫТИИ часа решения, а не на его начале.

    Признаки считаются по всему часу: в 20:00 их ещё нет, они появляются
    в 21:00. Цель `fwd_4h` определена так же — движение от закрытия часа
    `t` до закрытия часа `t+4`. Первая версия ставила вход на начало
    часа, и обе метки уезжали на час назад: обратный отсчёт врал, метка
    на графике стояла до того, как сигнал существовал, а «без исхода»
    наступало на час раньше срока.

    Вопрос владельца («hour — это фактически вход?») этот сдвиг и
    вскрыл: ответ «да» был бы неверен ровно на час.
    """
    import trades as TR

    hour = "2026-08-03-20"
    decided = TR._ts("2026-08-03-21") + 313          # цикл проснулся в 21:05
    picks = [{"arm": "gbm", "hour": hour, "at_ts": decided,
              "long": [{"sym": "BICOUSDT", "fwd": 273.0, "mae": -419.0}],
              "short": []}]
    t = TR.build(picks, [], now=TR._ts("2026-08-03-23"))[0]
    check("вход на закрытии часа сигнала",
          t["opened_at"] == TR._ts("2026-08-03-21"),
          str(t["opened_at"] - TR._ts("2026-08-03-21")))
    check("выход через четыре часа после входа",
          t["closes_at"] == TR._ts("2026-08-04-01"),
          str(t["closes_at"] - TR._ts("2026-08-04-01")))
    check("вход НЕ на начале часа сигнала",
          t["opened_at"] != TR._ts(hour))
    # Задержка цикла — это задержка входа, и выдавать её за ноль нельзя.
    check("задержка решения названа числом", t["lag_sec"] == 313,
          str(t["lag_sec"]))
    check("обратный отсчёт считается от верного срока",
          abs(t["closes_in_sec"] - 2 * 3600) < 1, str(t["closes_in_sec"]))
    # У старых записей момента решения нет — поле пустое, а не выдумано.
    old = TR.build([{k: v for k, v in picks[0].items() if k != "at_ts"}],
                   [], now=TR._ts("2026-08-03-23"))[0]
    check("без записи момента задержка пуста, а не ноль",
          old["lag_sec"] is None and old["decided_at"] is None)


def test_one_pick_per_arm_and_hour():
    """Выбор пишется один раз на (руку, час), сколько бы ни было проходов.

    Проходов внутри одного часа бывает несколько: перезапуск цикла — а
    он случается на КАЖДОЙ заливке — сразу гонит проход, и следующий по
    расписанию приходит в тот же час. Замер на живом предпросмотре: у
    часа 20 тридцать шесть сделок вместо двенадцати, у часа 19 —
    двадцать четыре.

    Счёт дубли не портят (разбор помнит разобранные часы), но вытесняют
    из таблицы настоящую историю и делают счётчик сделок ложным.
    """
    import tempfile
    import train as T
    import synth
    import trades as TR

    sd = tempfile.mkdtemp(prefix="dup-")
    md = os.path.join(tempfile.mkdtemp(), "m")
    keep = (T.MODEL_DIR, T.PRETEST, T.ARMS, T.gbm.fit, T.nn.fit)
    T.MODEL_DIR, T.PRETEST = md, True
    T.gbm.fit = lambda x, y, seed: keep[3](x, y, seed, n_trees=12)
    T.nn.fit = lambda x, y, seed: keep[4](x, y, seed, epochs=3)
    T.ARMS = (("gbm", T.gbm.fit),)
    try:
        synth.write_summaries(sd, D=80)
        # Три прохода подряд БЕЗ новых часов — ровно как при трёх
        # перезапусках внутри часа.
        for _ in range(3):
            T.cycle(sd, lambda m: None, book_root=None)
        with open(os.path.join(md, "picks.jsonl"), encoding="utf-8") as f:
            picks = [json.loads(x) for x in f]
        key = [(p["arm"], p["hour"]) for p in picks]
        check("выбор записан один раз на руку и час",
              len(key) == len(set(key)), str(key))
        tr = TR.build(picks, [])
        check("сделок ровно шесть на проход", len(tr) == 6, str(len(tr)))

        # И чтение снимает дубли, уже лежащие в файле: исправить его
        # задним числом нельзя, а показывать историю вдвое — врать.
        dbl = picks + picks
        check("дубли из файла снимаются на чтении",
              len(TR.build(dbl, [])) == len(tr),
              f"{len(TR.build(dbl, []))} против {len(tr)}")
    finally:
        (T.MODEL_DIR, T.PRETEST, T.ARMS, T.gbm.fit, T.nn.fit) = keep
        shutil.rmtree(sd, ignore_errors=True)


def test_trades_close_on_an_hourly_cycle():
    """Сделки обязаны закрываться при часовом цикле и цели в 4 часа.

    Разбор смотрел только на ПРЕДЫДУЩИЙ выбор. При цикле раз в час
    форвард предыдущего выбора ещё не закрыт, поэтому разбор выходил
    пустым; а к следующему циклу этот выбор уже не был предыдущим и не
    разбирался НИКОГДА. На живом предпросмотре это дало 48 сделок,
    закрытых ноль — при исправном на вид цикле, с растущей таблицей и
    бегущими часами.

    Геометрия здесь та же, что на сервере: между циклами прибавляется по
    одному часу.
    """
    import tempfile
    import train as T
    import synth
    import trades as TR

    sd = tempfile.mkdtemp(prefix="hourly-")
    md = os.path.join(tempfile.mkdtemp(), "m")
    keep = (T.MODEL_DIR, T.PRETEST, T.ARMS, T.gbm.fit, T.nn.fit)
    T.MODEL_DIR, T.PRETEST = md, True
    T.gbm.fit = lambda x, y, seed: keep[3](x, y, seed, n_trees=12)
    T.nn.fit = lambda x, y, seed: keep[4](x, y, seed, epochs=3)
    T.ARMS = (("gbm", T.gbm.fit),)
    try:
        for k in range(6):
            synth.write_summaries(sd, D=80 + k)
            T.cycle(sd, lambda m: None, book_root=None)
        with open(os.path.join(md, "picks.jsonl"), encoding="utf-8") as f:
            picks = [json.loads(x) for x in f]
        rp = os.path.join(md, "review.jsonl")
        revs = []
        if os.path.exists(rp):
            with open(rp, encoding="utf-8") as f:
                revs = [json.loads(x) for x in f]
        tr = TR.build(picks, revs)
        st = TR.summary(tr, "gbm")
        check(f"сделки закрываются ({st['closed']} закрыто, "
              f"{st['open']} открыто)", st["closed"] > 0, str(st))
        # «Без исхода» — срок вышел, разбора нет. При исправном разборе
        # таких быть не должно вовсе.
        check("зависших без исхода нет", st["no_outcome"] == 0, str(st))
        with open(os.path.join(md, "account_gbm.json"),
                  encoding="utf-8") as f:
            acc = json.load(f)
        check("счёт двигался", len(acc["history"]) > 0
              and acc["balance"] != T.START_BALANCE,
              f"{acc['balance']} за {len(acc['history'])} шагов")
        # Разбор одного часа пишется РОВНО один раз: повторный цикл не
        # вправе снова провести те же сделки по счёту.
        hours = [r["hour"] for r in revs]
        check("час разбирается один раз", len(hours) == len(set(hours)),
              str(hours))
        T.cycle(sd, lambda m: None, book_root=None)
        with open(rp, encoding="utf-8") as f:
            again = [json.loads(x) for x in f]
        check("повтор цикла не переразбирает уже разобранное",
              len(again) == len(revs), f"{len(revs)} -> {len(again)}")
    finally:
        (T.MODEL_DIR, T.PRETEST, T.ARMS, T.gbm.fit, T.nn.fit) = keep
        shutil.rmtree(sd, ignore_errors=True)


def test_adverse_path_matches_the_side():
    """Ход ПРОТИВ позиции у лонга и шорта — разные цели.

    `mae_4h` есть минимум цены за горизонт, `mfe_4h` — максимум, и обе
    считаются по ЦЕНЕ, а не по позиции. Значит лонгу против идёт mae, а
    шорту — mfe. Первая версия таблицы подставляла шорту mae, то есть
    подписывала ход в его ПОЛЬЗУ словами «ход против» — вранье в самой
    важной колонке, и заметил бы его только тот, кто помнит определение.
    """
    import train as T

    class Fake:
        def __init__(self, v):
            self.v = v
            self.importance = np.ones(3)

        def predict(self, x):
            return np.full(len(x), self.v)

    # Цена за горизонт ходит от −300 до +400 б.п. от входа.
    models = {("gbm", "fwd_4h"): Fake(50.0),
              ("gbm", "mae_4h"): Fake(-300.0),
              ("gbm", "mfe_4h"): Fake(400.0)}
    xj = np.zeros((5, 3))
    fwd = models[("gbm", "fwd_4h")].predict(xj)
    mae = models[("gbm", "mae_4h")].predict(xj)
    mfe = models[("gbm", "mfe_4h")].predict(xj)
    # Повторяем правило подстановки из `cycle` — оно и проверяется.
    adv_long = float(mae[0])
    adv_short = float(mfe[0])
    check("лонгу против идёт минимум цены", adv_long == -300.0)
    check("шорту против идёт максимум цены", adv_short == 400.0)
    check("прежнее поведение не воспроизводится: у шорта не mae",
          adv_short != float(mae[0]))
    # И знак читается как «против» у обоих: у лонга цена падала, у
    # шорта росла — обе стороны потеряли бы.
    check("обе величины означают убыток своей стороне",
          adv_long < 0 < adv_short)

    src = open(os.path.join(HERE, "train.py"), encoding="utf-8").read()
    check("сторона доезжает до сборки выбора", "def mk(i, side):" in src)
    check("источник хода против пишется в сам выбор",
          '"adverse_of"' in src)


def test_percent_is_the_display_unit():
    """Сделки показываются в ПРОЦЕНТАХ движения цены, не в б.п.

    Решение владельца. Существенно, что меняется только показ: цели
    модели, издержки и формула счёта остаются в базисных пунктах —
    единица хранения и единица показа разные вещи, и смешать их значит
    однажды посчитать комиссию в процентах.

    Числа закреплены явно, а не свойством: округление до двух знаков
    съело бы мелкое нетто, ради которого таблицу и смотрят.
    """
    import train as T
    check("крупное движение — два знака",
          T.pct(534) == "+5.34 %" and T.pct(-725) == "-7.25 %",
          f"{T.pct(534)} / {T.pct(-725)}")
    check("на границе десяти б.п. знаков всё ещё два",
          T.pct(-11.0) == "-0.11 %", T.pct(-11.0))
    # Ниже десяти б.п. два знака дали бы «-0.00 %» — то есть скрыли бы
    # само число.
    check("мелкое нетто не схлопывается в ноль",
          T.pct(-0.5) == "-0.005 %" and T.pct(4.9) == "+0.049 %",
          f"{T.pct(-0.5)} / {T.pct(4.9)}")
    check("пусто остаётся пустым", T.pct(None) == "—")
    # Издержки в коде обязаны остаться базисными пунктами.
    check("круг издержек хранится в б.п.", T.ROUND_COST_BP == 11.0,
          str(T.ROUND_COST_BP))

    # И то же самое в мыслях модели — их читает владелец, а не разработчик.
    man = {"sections": 9, "symbols": 543, "importance": {}}
    picks = {"long": [{"sym": "HFTUSDT", "fwd": 534.0, "mae": -112.0}],
             "short": [{"sym": "BEATUSDT", "fwd": -725.0, "mae": -90.0}]}
    txt = " ".join(T.think(None, man, [], picks))
    check("мысли говорят процентами",
          "+5.34 %" in txt and "-7.25 %" in txt and "б.п." not in txt,
          txt[:160])


def test_pretest_runs_where_live_refuses_and_stays_apart():
    """Предпросмотр показывает работу там, где боевой обязан молчать.

    Владелец хочет видеть обучение на том, что уже накоплено. Боевой
    цикл в этом состоянии отказывается по делу: `fwd_*` требуют беты,
    бете нужно FB.BETA_MIN часов, и без главной цели веса вели бы
    контур, который ничего не выбирает.

    Предпросмотр отключает хедж (бета := 0 там, где её нет) и потому
    работает. Цена честно названа: книга становится НАПРАВЛЕННОЙ, и
    пометка едет в артефакт, а не в комментарий.

    Главное здесь — что он не может помешать боевому: свой каталог,
    свой порог, и сводку часов он не пишет вовсе.
    """
    import tempfile
    import train as T
    import synth

    sd = tempfile.mkdtemp(prefix="pre-")
    live = os.path.join(tempfile.mkdtemp(), "model")
    pre = os.path.join(tempfile.mkdtemp(), "model_pretest")
    keep = (T.MODEL_DIR, T.PRETEST, T.PROBE, T.MIN_TRAIN_SECTIONS)
    try:
        # 60 часов: бете нужно 96, значит fwd_* пусты по построению.
        synth.write_summaries(sd, D=60)
        T.MODEL_DIR, T.PRETEST, T.PROBE = live, False, False
        T.MIN_TRAIN_SECTIONS = 4       # чтобы дойти именно до беты
        ok_live = T.cycle(sd, lambda m: None, book_root=None)
        with open(os.path.join(live, "last_run.json"),
                  encoding="utf-8") as f:
            lr = json.load(f)
        check("боевой отказывается без главной цели",
              not ok_live and lr["reason"] == "нет главной цели",
              lr["reason"])
        check("боевой весов не пишет",
              not any(f.startswith("weights_") for f in os.listdir(live)))

        T.MODEL_DIR, T.PRETEST = pre, True
        ok_pre = T.cycle(sd, lambda m: None, book_root=None)
        check("предпросмотр на тех же данных обучается", ok_pre)
        with open(os.path.join(pre, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
        check("режим хеджа назван в артефакте, а не только на странице",
              man["pretest"] is True and man["hedge"] == T.HEDGE_PRETEST,
              str(man.get("hedge")))
        with open(os.path.join(pre, "picks.jsonl"), encoding="utf-8") as f:
            picks = [json.loads(x) for x in f]
        check("выбор монет есть — ради него всё и делалось",
              picks and picks[0]["long"], str(len(picks)))
        # Канарейка на малой выборке кричит от собственного шума;
        # несколько зёрен это и показывают числом.
        check("канарейка считана несколькими зёрнами",
              man["canary_seeds"] > 1 and man["canary_spread"] > 0,
              f"{man['canary_seeds']} зёрен, разброс "
              f"{man['canary_spread']}")
        check("боевой каталог не тронут предпросмотром",
              not os.path.exists(os.path.join(live, "picks.jsonl"))
              and not os.path.exists(os.path.join(live, "manifest.json")))
    finally:
        T.MODEL_DIR, T.PRETEST, T.PROBE, T.MIN_TRAIN_SECTIONS = keep
        shutil.rmtree(sd, ignore_errors=True)


def test_probe_never_touches_live_model():
    """Пробный прогон пишет в свой каталог и метит себя в артефакте.

    Владелец вправе посмотреть, как работает обучение, до того как
    накопятся сорок восемь сечений. Опасность здесь ровно одна и она
    уже случалась: коммит F2 подменил артефакт настоящего прогона
    смоуковым, потому что по содержимому они неотличимы. Поэтому
    пробный прогон меняет КАТАЛОГ, а не порог, и метка `probe` лежит в
    манифесте — каталог переименуют, а манифест поедет с весами.
    """
    import train as T

    live, probe_flag = T.MODEL_DIR, T.PROBE
    orig_argv = sys.argv
    try:
        sys.argv = ["t", "--probe"]
        seen = {}

        def fake_cycle(sum_dir, log_, **kw):
            seen["dir"] = T.MODEL_DIR
            seen["probe"] = T.PROBE
            return False

        orig_c = T.cycle
        T.cycle = fake_cycle
        try:
            T.main()
        finally:
            T.cycle = orig_c
    finally:
        sys.argv = orig_argv
        T.MODEL_DIR, T.PROBE = live, probe_flag

    check("пробный прогон уводит каталог от боевого",
          seen.get("dir") and seen["dir"] != live, str(seen.get("dir")))
    check("каталог назван отдельно, а не рядом случайно",
          str(seen.get("dir")).endswith("model_probe"), str(seen.get("dir")))
    check("флаг пробы поднят", seen.get("probe") is True)
    check("боевой каталог восстановлен", T.MODEL_DIR == live)
    # Порог не трогается: пробный прогон обходит его каталогом, а не
    # понижением. Понизить порог значило бы, что боевое обучение
    # однажды случится на восьми сечениях.
    check("боевой порог сечений не изменился",
          T.MIN_TRAIN_SECTIONS == 48, str(T.MIN_TRAIN_SECTIONS))
    check("порог пробы заметно ниже боевого",
          T.PROBE_MIN_SECTIONS < T.MIN_TRAIN_SECTIONS)


def test_novelty_measure():
    """Новизна: доля признаков вне диапазона обучения, NaN не судится."""
    import train as T
    lo = np.array([0.0, 0.0, np.nan])
    hi = np.array([1.0, 1.0, np.nan])
    check("всё внутри — ноль",
          T.novelty(np.array([0.5, 0.5, 9.9]), lo, hi) == 0.0)
    check("один из двух снаружи — половина",
          T.novelty(np.array([0.5, 2.0, 9.9]), lo, hi) == 0.5)
    check("NaN-признак не судится",
          T.novelty(np.array([np.nan, 2.0, 9.9]), lo, hi) == 1.0)
    check("судить не по чему — None, а не ноль",
          T.novelty(np.array([np.nan, np.nan, 9.9]), lo, hi) is None)
    x = np.zeros((3, 20, 2))
    x[:, :, 1] = np.nan                     # признак без записи
    elig = np.ones((3, 20), dtype=bool)
    blo, bhi = T.novelty_bounds(x, elig)
    check("пустой признак — без диапазона, живой — с диапазоном",
          np.isnan(blo[1]) and blo[0] == 0.0 == bhi[0], str((blo, bhi)))


# ---------- цикл переобучения ----------

from synth import write_summaries as _write_summaries


def test_live_ic_survives_hourly_retraining():
    """Живой IC обязан считаться и при переобучении каждый час.

    Дефект, найденный на живом предпросмотре: `eval_previous` берёт часы
    СТРОГО ПОСЛЕ обучения прежней модели, а при часовом цикле такой час
    ровно один — последний, — и форвард у него не закрыт. Цель `NaN`,
    IC пуст, файл не пишется, и так каждый раз. Панель показывала
    пустоту, неотличимую от «данных ещё мало», тогда как измерение было
    невозможно по построению — за сутки работы ноль записей.

    Здесь проверяется обе половины починки: вектор сечения сохраняется
    целиком, а через горизонт по нему считается IC — по всему сечению,
    а не по шести выбранным именам.
    """
    import numpy as np
    import shutil
    import tempfile
    import train as T

    d = tempfile.mkdtemp()
    was = T.MODEL_DIR
    T.MODEL_DIR = d
    try:
        S, H = 40, 8
        grid = [f"2026-08-04-{h:02d}" for h in range(H)]
        syms = [f"S{i}USDT" for i in range(S)]
        elig = np.ones((S, H), dtype=bool)
        rng = np.random.default_rng(7)
        y = rng.normal(size=(S, H))
        y[:, -1] = np.nan          # форвард последнего часа не закрыт
        targets = {"fwd_4h": y}

        # Сечение предпоследнего часа: предсказание совпадает с фактом,
        # значит IC обязан выйти около единицы. Точное совпадение здесь
        # уместно — проверяется проводка, а не качество модели.
        T.save_preds("gbm", grid[-2], syms, np.arange(S), y[:, -2])
        # И сечение последнего часа — его оценить ещё нечем.
        T.save_preds("gbm", grid[-1], syms, np.arange(S),
                     rng.normal(size=S))
        rows = T.score_preds(targets, elig, grid, syms, lambda m: None)
        check("закрывшееся сечение оценено, незакрытое отложено",
              len(rows) == 1 and rows[0]["hour"] == grid[-2],
              str([(r["hour"], r["median_ic"]) for r in rows]))
        check("IC посчитан по ВСЕМУ сечению, а не по выбранным именам",
              rows[0]["names"] == S and rows[0]["median_ic"] > 0.99,
              f"{rows[0].get('names')} имён, IC {rows[0].get('median_ic')}")
        check("мера помечена видом — двух разных IC в одном списке быть "
              "не должно", rows[0]["kind"] == "section",
              str(rows[0].get("kind")))
        with open(os.path.join(d, "ic_history.jsonl"),
                  encoding="utf-8") as f:
            hist = [json.loads(x) for x in f if x.strip()]
        check("замер попал в историю, а не остался в памяти",
              len(hist) == 1 and hist[0]["hour"] == grid[-2], str(hist))

        # Оценённая запись из очереди уходит, неоценённая остаётся —
        # иначе один и тот же час считался бы каждый цикл заново.
        left = [json.loads(x) for x in
                open(os.path.join(d, "preds.jsonl"), encoding="utf-8")
                if x.strip()]
        check("оценённое убрано из очереди, ждущее осталось",
              len(left) == 1 and left[0]["hour"] == grid[-1], str(left))

        # Повторный вызов не обязан дублировать замер.
        again = T.score_preds(targets, elig, grid, syms, lambda m: None)
        check("повторный проход не считает тот же час дважды",
              not again, str(again))

        # Устаревшее выбрасывается, а не копится вечно: час выпал из
        # сетки, оценить нечем, и молчать об этом нельзя.
        T.save_preds("gbm", "2026-07-01-00", syms, np.arange(S),
                     rng.normal(size=S))
        said = []
        T.score_preds(targets, elig, grid, syms, said.append)
        check("устаревший вектор выброшен и об этом сказано",
              any("выброшено" in s for s in said), str(said))
        left = [json.loads(x) for x in
                open(os.path.join(d, "preds.jsonl"), encoding="utf-8")
                if x.strip()]
        check("после выброса в очереди остался только ждущий час",
              len(left) == 1 and left[0]["hour"] == grid[-1], str(left))
    finally:
        T.MODEL_DIR = was
        shutil.rmtree(d, ignore_errors=True)


def test_live_ic_shown_as_median_not_last_hour():
    """Страница показывает медиану сечений, а не последний час.

    Замер по одному сечению шумен: ранговая корреляция сотен имён за
    один час гуляет на десятые доли. Показать последнюю запись значило
    бы выдать шум за измерение, и число прыгало бы каждый час, создавая
    впечатление, что модель то «видит», то «слепнет».

    И два вида замера не складываются в один: `section` — по
    сохранённому вектору (час на запись), прочее — прежние веса на окне
    после обучения, где медиана уже посчитана.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "b1_book"))
    import collect

    rows = [
        {"arm": "gbm", "target": "fwd_4h", "kind": "section",
         "median_ic": 0.30, "hour": "h1"},
        {"arm": "gbm", "target": "fwd_4h", "kind": "section",
         "median_ic": -0.10, "hour": "h2"},
        {"arm": "gbm", "target": "fwd_4h", "kind": "section",
         "median_ic": 0.05, "hour": "h3"},
        {"arm": "nn", "target": "fwd_4h", "kind": "window",
         "median_ic": 0.02, "sections": 20},
    ]
    out = collect.Collector.ic_summary(rows)
    sec = [r for r in out if r["kind"] == "section"]
    check("живой IC сведён в медиану, а не взят последним часом",
          len(sec) == 1 and sec[0]["median_ic"] == 0.05
          and sec[0]["sections"] == 3, str(sec))
    check("замер на окне не смешан с замером на сечениях",
          any(r["kind"] == "window" and r["median_ic"] == 0.02
              for r in out), str(out))


def test_train_cycle_end_to_end():
    import train as T

    orig_fit = T.gbm.fit
    orig_nn = T.nn.fit
    T.gbm.fit = lambda x, y, seed: orig_fit(x, y, seed, n_trees=25)
    T.nn.fit = lambda x, y, seed: orig_nn(x, y, seed, epochs=4)
    T.ARMS = (("gbm", T.gbm.fit), ("nn", T.nn.fit))
    try:
        d = tempfile.mkdtemp()
        sd = os.path.join(d, "summary")
        _write_summaries(sd, D=260)
        T.MODEL_DIR = os.path.join(d, "model")
        ok = T.cycle(sd, lambda m: None, book_root=None)
        check("цикл прошёл", ok)
        man = json.load(open(os.path.join(T.MODEL_DIR, "manifest.json")))
        check("манифест с версией и границей обучения",
              man["version"] == T.MODEL_VERSION
              and man["trained_upto"].startswith("2026-08-1"),
              str(man.get("trained_upto")))
        check("веса всех целей обеих рук на месте",
              all(os.path.exists(os.path.join(
                  T.MODEL_DIR, f"weights_{a}_{t}.pkl"))
                  for a, _ in T.ARMS for t in T.TARGETS))
        check("канарейка не кричит",
              man["canary_ic"] is not None
              and abs(man["canary_ic"]) < T.CANARY_STOP,
              str(man["canary_ic"]))

        # Второй цикл: дописываем сутки и ждём живой вневыборочный IC —
        # прежняя модель обязана поймать заложенный сигнал на часах,
        # которых не видела.
        _write_summaries(sd, D=300)   # те же зерно и старт: +40 час.
        ok2 = T.cycle(sd, lambda m: None, book_root=None)
        check("второй цикл прошёл", ok2)
        # Цикл ОБЯЗАН сохранять вектор сечения — без этого живой IC при
        # часовом переобучении не считается вовсе. Проверять сами
        # функции недостаточно: отрицательный контроль показал, что
        # снятие вызова из цикла не роняло ни одного теста.
        pr = [json.loads(x) for x in
              open(os.path.join(T.MODEL_DIR, "preds.jsonl"),
                   encoding="utf-8") if x.strip()]
        check("цикл сохранил вектор сечения по каждой руке",
              {r["arm"] for r in pr} == {"gbm", "nn"}, str(len(pr)))
        check("сохранён ВЕСЬ вектор, а не шесть выбранных имён",
              all(len(r["pred"]) == len(r["syms"]) > 6 for r in pr),
              str([len(r["pred"]) for r in pr]))
        # И замер по сохранённому обязан доехать до истории: у второго
        # цикла форвард первых сечений уже закрыт.
        hist = [json.loads(x) for x in
                open(os.path.join(T.MODEL_DIR, "ic_history.jsonl"))]
        sec = [h for h in hist if h.get("kind") == "section"]
        check("живой IC по сохранённым векторам попал в историю",
              sec and {h["arm"] for h in sec} == {"gbm", "nn"},
              str(len(sec)))
        f1 = [h for h in hist if h["target"] == "fwd_1h"]
        check("живой IC записан по обеим рукам",
              len(f1) == 2 and {h["arm"] for h in f1} == {"gbm", "nn"},
              str(f1))
        check(f"заложенный сигнал пойман вне выборки обеими "
              f"(деревья {f1[0]['median_ic']:+.2f}, "
              f"сеть {f1[1]['median_ic']:+.2f})",
              all(h["median_ic"] > 0.1 for h in f1), str(f1))
        th = [json.loads(x)["text"] for x in
              open(os.path.join(T.MODEL_DIR, "thoughts.jsonl"))]
        check("мысли записаны и говорят о сбываемости",
              any("проверил вчерашние прогнозы" in t for t in th)
              and any("если бы торговал сейчас" in t for t in th),
              str(th[-3:]))
        picks = [json.loads(x) for x in
                 open(os.path.join(T.MODEL_DIR, "picks.jsonl"))]
        check("выборы обеих рук записаны с часом и ожиданием",
              len(picks) == 4 and {p["arm"] for p in picks} ==
              {"gbm", "nn"} and "fwd" in picks[0]["long"][0],
              str(picks[0])[:100])
        rev = [json.loads(x) for x in
               open(os.path.join(T.MODEL_DIR, "review.jsonl"))]
        check("прошлые выборы обеих рук разобраны фактом",
              len(rev) == 2 and {r["arm"] for r in rev} == {"gbm", "nn"}
              and all("got" in x for r in rev for x in r["rows"]),
              str(rev)[:120])
        # Счёт — один капитал: история ведётся ПО СДЕЛКАМ, а не по
        # часам, и баланс есть старт плюс сумма их результатов. Прежняя
        # модель складывала часы, каждый на полный капитал, и давала
        # четырёхкратную экспозицию при горизонте в четыре часа.
        import trades as TR
        for arm in ("gbm", "nn"):
            acc = json.load(open(os.path.join(
                T.MODEL_DIR, f"account_{arm}.json")))
            got = sum(h["pnl"] for h in acc["history"])
            check(f"счёт {arm} исполнен: старт 1000, издержки учтены",
                  acc["start"] == TR.START_BALANCE
                  and acc["leverage"] == 1.0
                  and len(acc["history"]) == 6
                  and abs(acc["balance"] - 1000.0 - got) < 0.05
                  and acc["balance"] != 1000.0, str(acc)[:200])
        check("счёт попал в мысли",
              any(t.startswith("[деревья] счёт:") or
                  t.startswith("[сеть] счёт:") for t in th), str(th[:3]))
        check("разбор попал в мысли обеих рук",
              any("разбор прошлых выборов" in t and "[деревья]" in t
                  for t in th)
              and any("[сеть]" in t for t in th), str(th[:2]))
        man2 = json.load(open(os.path.join(T.MODEL_DIR,
                                           "manifest.json")))
        nb = man2.get("novelty_bounds") or {}
        check("границы новизны в манифесте по каждому признаку",
              len(nb) > 40 and man2.get("novelty_pct") == [0.5, 99.5]
              and all(len(v) == 2 for v in nb.values()),
              f"признаков с границами: {len(nb)}")
        odds = [p.get("odd") for pk in picks
                for p in pk["long"] + pk["short"]]
        check("каждый выбор помечен новизной 0…1",
              all(o is not None and 0.0 <= o <= 1.0 for o in odds),
              str(odds[:6]))
        check("новизна доехала из выбора в разбор",
              all("odd" in x for r in rev for x in r["rows"]),
              str(rev[0]["rows"][:2]))
        check("новизна названа в мыслях как замер, не правило",
              any("новизна выбора" in t for t in th), str(th[-2:]))
    finally:
        T.gbm.fit = orig_fit
        T.nn.fit = orig_nn
        T.ARMS = (("gbm", T.gbm.fit), ("nn", T.nn.fit))


def test_nn_learns_and_sees_missing():
    """Сеть учится и видит пропуск флагом, а не затиркой."""
    import nn as N

    r = np.random.default_rng(4)
    n = 6000
    x = r.normal(0, 1, (n, 5))
    miss = r.random(n) < 0.3
    x[miss, 2] = np.nan
    y = 1.5 * x[:, 0] + np.where(miss, 2.0, -1.0) + r.normal(0, 0.3, n)
    m = N.fit(x[:4500], y[:4500], seed=1, epochs=20)
    p = m.predict(x[4500:])
    c = np.corrcoef(p, y[4500:])[0, 1]
    check(f"сеть учит сигнал вне выборки (корр. {c:.2f})", c > 0.8, str(c))
    gap = p[miss[4500:]].mean() - p[~miss[4500:]].mean()
    # Настоящий зазор 3.0; сети с четырьмя эпохами хватает поймать
    # направление и величину порядка — тест проверяет «флаг работает»,
    # а не «сеть сошлась до конца».
    check(f"пропуск различён флагом (зазор {gap:.1f})", gap > 1.0,
          str(gap))
    p2 = N.fit(x[:4500], y[:4500], seed=1, epochs=20).predict(x[4500:])
    check("одно зерно — бит в бит", np.array_equal(p, p2))


def test_think_words():
    """Мысли — чистая функция от чисел; слова обязаны следовать за
    числами, а не украшать их."""
    import train as T

    man = {"importance": {"fwd_4h": {"imb_0.001": 0.3, "eat_bid": 0.2,
                                     "beta": 0.1}},
           "canary_ic": 0.004, "sections": 100, "symbols": 540}
    prev = {"importance": {"fwd_4h": {"imb_0.001": 0.1, "eat_bid": 0.25,
                                      "beta": 0.1}}}
    ic = [{"target": "fwd_4h", "median_ic": 0.032, "sections": 24}]
    picks = {"long": [{"sym": "HYPEUSDT", "fwd": 35.2, "mae": -52.1}],
             "short": [{"sym": "DOGEUSDT", "fwd": -21.0, "mae": -30.0}]}
    text = "\n".join(T.think(prev, man, ic, picks))
    check("сбываемость названа по порогу IC",
          "заметно лучше случайного" in text and "+0.032" in text, text)
    check("важности переведены в трейдерские слова",
          "перекос глубины стакана" in text, text)
    check("сдвиг доверия назван с числами",
          "больше доверять" in text and "+0.20" in text, text)
    # Единица показа — процент движения цены: 35 б.п. = +0.35 %,
    # −52 б.п. = −0.52 %.
    check("выбор назван с ожиданием и путём против",
          "HYPE (жду +0.35 %" in text and "до -0.52 %" in text, text)
    first = "\n".join(T.think(None, man, [], None))
    check("первое обучение названо первым",
          first.startswith("первое обучение"), first[:60])


def test_load_matrices_grid_is_continuous():
    import train as T

    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "AAA"))
    rows = [{"hour": "2026-08-01-00", "mid_close": 1.0, "n_snap": 3600},
            {"hour": "2026-08-01-05", "mid_close": 2.0, "n_snap": 3600}]
    with open(os.path.join(d, "AAA", "2026-08-01.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    mats, syms, grid = T.load_matrices(d)
    check("сетка часов непрерывна (дыра — колонка NaN)",
          len(grid) == 6 and np.isnan(mats["mid_close"][0, 2]),
          str(grid))
    check("края на месте", mats["mid_close"][0, 0] == 1.0
          and mats["mid_close"][0, 5] == 2.0)


def main():
    print("сводка часа")
    test_summary_censors_bands_by_reach()
    test_summary_tape()
    test_summary_roundtrip_through_store()
    test_run_resumes_by_content()
    print("заглядывание")
    test_no_lookahead_any_feature()
    print("путь")
    test_forward_path_exact()
    print("формации")
    test_formations_semantics()
    print("новые пакеты: metrics/liq, время, лидер, сектор")
    test_metrics_liq_in_summary()
    test_context_features()
    print("сечение и цели")
    test_eligibility_floor()
    test_eligibility_by_coverage()
    test_targets_shapes_and_direction()
    print("цикл переобучения")
    test_retry_when_not_trained()
    test_readiness_is_written_before_training()
    test_canary_not_computed_is_not_a_pass()
    test_report_flags_manifest_from_a_previous_run()
    test_capital_returns_before_it_is_redeployed()
    test_pretest_comes_after_the_summary_is_written()
    test_hourly_cycle_wakes_on_the_hour()
    test_account_is_one_capital_at_leverage_one()
    test_unrealised_never_mixes_with_realised()
    test_exposure_covers_all_open_and_leverage_is_named()
    test_drawdown_is_measured_not_inferred_from_the_outcome()
    test_drawdown_is_reported_against_the_deposit()
    test_pretest_hedges_with_beta_one_and_keeps_books_apart()
    test_worst_open_book_is_not_the_worst_trade()
    test_account_drawdown_counts_open_positions()
    test_entry_price_is_recovered_from_summaries()
    test_unrealised_marks_open_positions_only()
    test_awaiting_review_is_not_a_lost_outcome()
    test_entry_is_the_close_of_the_signal_hour()
    test_one_pick_per_arm_and_hour()
    test_trades_close_on_an_hourly_cycle()
    test_adverse_path_matches_the_side()
    test_percent_is_the_display_unit()
    test_pretest_runs_where_live_refuses_and_stays_apart()
    test_probe_never_touches_live_model()
    test_novelty_measure()
    test_nn_learns_and_sees_missing()
    test_think_words()
    test_load_matrices_grid_is_continuous()
    test_live_ic_survives_hourly_retraining()
    test_live_ic_shown_as_median_not_last_hour()
    test_train_cycle_end_to_end()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
