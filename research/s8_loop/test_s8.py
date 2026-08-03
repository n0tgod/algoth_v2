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
    t0 = time.time() - 7200
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
    t0 = time.time() - 7200
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
    check("после «рано» ждём час, после обучения — сутки",
          slept == [T.RETRY_SEC, T.CYCLE_SEC], str(slept))
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

def _write_summaries(d, S=36, D=260, seed=5, start="2026-08-01-00"):
    """Синтетические сводки на диск: дельта ленты предсказывает
    следующий час — сигнал, который цикл обязан найти."""
    r = np.random.default_rng(seed)
    t0 = time.mktime(time.strptime(start, "%Y-%m-%d-%H"))
    sig = r.normal(0, 1, (S, D))
    close = np.empty((S, D))
    close[:, 0] = 100.0
    # Сила сигнала выбрана правдоподобной (IC ~0.2, не 0.5): шум
    # проекции канарейки растёт вместе с настоящим сигналом (механизм
    # M2), и на перегретой синтетике канарейка кричала бы без течи.
    for t in range(1, D):
        close[:, t] = close[:, t - 1] * (
            1 + 0.004 * sig[:, t - 1] * 0.22
            + r.normal(0, 0.004, S))
    from datetime import datetime as DT, timezone as TZ
    for si in range(S):
        sym = f"S{si:02d}USDT"
        os.makedirs(os.path.join(d, sym), exist_ok=True)
        fh = {}
        for t in range(D):
            hour = DT.fromtimestamp(t0 + t * 3600, TZ.utc)\
                .strftime("%Y-%m-%d-%H")
            day = hour[:10]
            buy = 1e6 * (1 + 0.4 * np.tanh(sig[si, t]))
            sell = 2e6 - buy
            row = {"hour": hour, "n_snap": 3600,
                   "mid_close": round(close[si, t], 6),
                   "mid_high": round(close[si, t] * 1.002, 6),
                   "mid_low": round(close[si, t] * 0.998, 6),
                   "spread_bp": 5.0, "upd": 100.0, "reach_bp": 60.0,
                   "best_b": 1e4, "best_a": 1e4,
                   "big_med": 1e5, "big_max": 2e5,
                   "n_trades": 500, "buy": round(buy, 2),
                   "sell": round(sell, 2),
                   "vol_max_1s": 1e4, "traded_secs": 1800,
                   "depth_eat_b": 2e5, "depth_eat_a": 2e5}
            for w in BANDS:
                row[f"bq_b{w}"] = 1e5
                row[f"bq_a{w}"] = 1e5
                row[f"cov_b{w}"] = 1.0
                row[f"cov_a{w}"] = 1.0
            f = fh.get(day)
            if f is None:
                f = fh[day] = open(os.path.join(d, sym, day + ".jsonl"),
                                   "a", encoding="utf-8")
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        for f in fh.values():
            f.close()


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
        hist = [json.loads(x) for x in
                open(os.path.join(T.MODEL_DIR, "ic_history.jsonl"))]
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
        for arm in ("gbm", "nn"):
            acc = json.load(open(os.path.join(
                T.MODEL_DIR, f"account_{arm}.json")))
            check(f"счёт {arm} исполнен: старт 1000, издержки учтены",
                  len(acc["history"]) == 1
                  and abs(acc["balance"] - 1000.0
                          - acc["history"][0]["pnl"]) < 0.01
                  and acc["balance"] != 1000.0, str(acc))
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
    check("выбор назван с ожиданием и путём против",
          "HYPE (жду +35 б.п." in text and "до -52" in text, text)
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
    test_probe_never_touches_live_model()
    test_novelty_measure()
    test_nn_learns_and_sees_missing()
    test_think_words()
    test_load_matrices_grid_is_continuous()
    test_train_cycle_end_to_end()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
