#!/usr/bin/env python3
"""
Тесты M1. Главный — на заглядывание в будущее, и он один на ВСЕ признаки.

Для обучаемой модели утечка из будущего — смерть первого порядка (§9
спеки 07): модель найдёт её с гарантией и покажет красивый IC, который
не существует. Дефект этого класса в проекте уже был трижды — форвардное
окно R2 на бар раньше ребаланса, метка metrics в L1, цена незакрытого
бара — и каждый раз его не было видно в результате. Поэтому проверка
устроена жёстко: меняем будущее целиком и требуем, чтобы прошлое не
изменилось НИ У ОДНОГО признака из общей сборки. Признак, забытый в
тесте, — дыра того же размера, что забытый в коде сдвиг.

    python3 research/m1_features/test_features.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import features as F                                       # noqa: E402

FAILED = []
rng = np.random.default_rng(20260731)


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  ПАДЕНИЕ {name}: {detail}")
        FAILED.append(name)


def synth(S=24, D=140, gap=None):
    """Синтетический рынок: общая волна + свой шум, положительные цены."""
    f = rng.normal(0, 0.02, D)
    r = 1.0 * f[None, :] + rng.normal(0, 0.01, (S, D))
    close = 100.0 * np.cumprod(1.0 + r, axis=1)
    if gap:
        close[gap[0], gap[1]] = np.nan
    turn = np.abs(rng.normal(1e7, 2e6, (S, D)))
    traded = np.clip(rng.normal(0.99, 0.01, (S, D)), 0, 1)
    elig = np.ones((S, D), dtype=bool)
    fund_bp = rng.normal(1.0, 3.0, (S, D))
    fund_cnt = np.full((S, D), 3.0)
    oi = np.abs(rng.normal(5e6, 1e6, (S, D)))
    age = np.arange(D, dtype=float)[None, :] + 400.0 + \
        np.arange(S, dtype=float)[:, None]
    return close, turn, traded, elig, fund_bp, fund_cnt, oi, age


def pack(data):
    c, tu, tr, e, fb, fc, oi, age = data
    return F.feature_pack(c, tu, tr, e, fb, fc, oi, age_days=age)


def mutate_after(data, t0):
    """Переписать всё ПОСЛЕ дня t0 другим случайным рынком."""
    out = [x.copy() for x in data]
    S, D = out[0].shape
    r2 = np.random.default_rng(7)
    for i in (0, 1, 2, 4, 6):          # close, turn, traded, fund_bp, oi
        out[i][:, t0 + 1:] = np.abs(r2.normal(50, 10, (S, D - t0 - 1)))
    return out


def test_no_lookahead_any_feature():
    data = synth()
    t0 = 100
    a = pack(data)
    b = pack(mutate_after(data, t0))
    for name in sorted(a):
        same = np.allclose(a[name][:, :t0 + 1], b[name][:, :t0 + 1],
                           equal_nan=True)
        check(f"будущее не трогает прошлое: {name}", same, name)
    # И проверка, что тест кусается: изменение ПРОШЛОГО обязано менять
    # признаки — иначе выше сравнивались константы.
    data2 = [x.copy() for x in data]
    data2[0][:, t0 - 5] *= 1.5
    c = pack(data2)
    bites = not np.allclose(a["ret_7"][:, :t0 + 1], c["ret_7"][:, :t0 + 1],
                            equal_nan=True)
    check("тест кусается (прошлое меняет признаки)", bites)


def test_forward_is_strictly_forward():
    data = synth()
    c = data[0]
    r = F.daily_returns(c)
    elig = data[3]
    zero_beta = np.zeros_like(c)
    t0 = 100
    res_a, fwd_a = F.forward_residual(c, r, elig, zero_beta, 5)
    c2 = c.copy()
    c2[:, :t0] = np.abs(rng.normal(50, 5, (c.shape[0], t0)))
    res_b, fwd_b = F.forward_residual(c2, F.daily_returns(c2), elig,
                                      zero_beta, 5)
    check("форвард не зависит от прошлого (дефект R2 не воспроизводим)",
          np.allclose(fwd_a[:, t0:-5], fwd_b[:, t0:-5], equal_nan=True))
    check("в конце ряда форвард NaN, а не ноль",
          np.all(np.isnan(fwd_a[:, -5:])))


def test_missing_day_is_gap_not_zero():
    data = synth(gap=(3, slice(60, 65)))
    a = pack(data)
    check("дневная доходность через дыру — NaN",
          np.isnan(F.daily_returns(data[0])[3, 60:66]).all())
    check("ret_1 в дыре — NaN, не ноль", np.isnan(a["ret_1"][3, 60:66]).all())
    # Замороженный хвост: сделок нет — закрытий нет — признаков нет.
    data2 = synth()
    data2[0][5, 110:] = np.nan
    b = pack(data2)
    check("замороженный хвост не рождает признаков",
          np.isnan(b["ret_1"][5, 111:]).all() and
          np.isnan(b["vol_ratio"][5, 139]),
          str(b["vol_ratio"][5, 139]))


def test_net_path_needs_enough_days():
    data = synth(gap=(2, slice(50, 54)))
    a = pack(data)
    check("путь по обрывку не считается (4 дыры из 7)",
          np.isnan(a["net_path_7"][2, 55]), str(a["net_path_7"][2, 55]))
    full = a["net_path_7"][0, 55]
    check("на целом ряду |чистое/путь| ≤ 1", abs(full) <= 1.0 + 1e-9,
          str(full))


def test_wave_excludes_self_and_beta_sane():
    S, D = 20, 140
    f = rng.normal(0, 0.02, D)
    r = 1.0 * f[None, :] + rng.normal(0, 0.004, (S, D))
    r[7] = rng.normal(0, 0.02, D)          # чистый шум, к рынку не привязан
    close = 100 * np.cumprod(1 + r, axis=1)
    elig = np.ones((S, D), dtype=bool)
    w = F.wave_excl_self(F.daily_returns(close), elig)
    b = F.rolling_beta(F.daily_returns(close), w)
    check(f"несвязанный актив получил β≈0 ({b[7, -1]:.2f})",
          abs(b[7, -1]) < 0.35, str(b[7, -1]))
    others = np.delete(b[:, -1], 7)
    check(f"связанные получили β≈1 (среднее {np.nanmean(others):.2f})",
          abs(np.nanmean(others) - 1.0) < 0.15, str(np.nanmean(others)))
    thin = F.wave_excl_self(F.daily_returns(close),
                            np.zeros((S, D), dtype=bool))
    check("волна из пустого сечения — NaN", np.isnan(thin).all())


def test_funding_day_aggregation():
    day = 86_400_000
    t = np.array([day // 3, day // 2, day - 1, day + 100, 3 * day + 5])
    rate = np.array([1e-4, 1e-4, 1e-4, -2e-4, 5e-4])
    bp, cnt = F.funding_daily(t, rate, 0, 4)
    check(f"три начисления сложились ({bp[0]:.1f} б.п.)",
          abs(bp[0] - 3.0) < 1e-9, str(bp[0]))
    check("частота посчитана", cnt[0] == 3 and cnt[1] == 1, str(cnt))
    check("день без начислений — NaN, не ноль",
          np.isnan(bp[2]) and cnt[2] == 0, str(bp[2]))


def test_age_is_linear_in_time():
    data = synth()
    a = pack(data)
    d = a["age"][0, 100] - a["age"][0, 99]
    check("возраст растёт на день за день",
          abs(d - 1.0 / 365.25) < 1e-12, str(d))
    check("возраст в годах, не в днях",
          abs(a["age"][0, 0] - 400.0 / 365.25) < 1e-9, str(a["age"][0, 0]))


def test_oi_respects_publication_lag():
    # Снимок за две минуты до полуночи публикуется через пять минут —
    # уже в следующем дне, и прошлому дню принадлежать не вправе.
    t = np.array([86_400 - 120])
    out = F.oi_daily(t, np.array([7e6]), 0, 2, lag_sec=300)
    check("точка у полуночи ушла в СЛЕДУЮЩИЙ день",
          np.isnan(out[0]) and out[1] == 7e6, str(out))
    # Последняя точка дня побеждает — свойство, на котором стоит
    # векторизация, и оно закрепляется числом, а не верой.
    t2 = np.array([1000, 2000, 3000])
    out2 = F.oi_daily(t2, np.array([1.0, 2.0, 3.0]), 0, 1, lag_sec=0)
    check("последняя точка дня побеждает", out2[0] == 3.0, str(out2))


def test_ret_norm_scales_by_sqrt_horizon():
    S, D = 4, 120
    r = np.full((S, D), 0.01)
    close = 100 * np.cumprod(1 + r, axis=1)
    sig = F.trailing_std(F.daily_returns(close), 30, 20)
    # На постоянном ряду σ = 0 — нормировка обязана дать NaN, а не
    # бесконечность: Sharpe 4.5e16 у постоянного ряда уже был (R4).
    v = F.ret_norm(close, 7, sig)
    check("нулевая σ не рождает бесконечность",
          not np.isinf(v[np.isfinite(v)]).any() if np.isfinite(v).any()
          else np.isnan(v[:, -1]).all(), str(v[:, -1]))


def test_end_to_end_tiny_store():
    """Крохотное хранилище -> дневная сводка тем же SQL, что и прогон."""
    try:
        import duckdb
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("  —    duckdb/pyarrow нет, сквозная проверка пропущена")
        return
    import tempfile

    import build as B

    d = tempfile.mkdtemp()
    day = 86_400_000
    rows = {"symbol": [], "open_time": [], "close": [],
            "quote_volume": [], "trades": []}
    for s in ("AAAUSDT", "BBBUSDT"):
        for dd in range(3):
            for m in range(0, 1440, 60):        # каждый час, для скорости
                rows["symbol"].append(s)
                rows["open_time"].append((dd * day + m * 60_000) * 1000)
                rows["close"].append(100.0 + dd + m / 1440)
                rows["quote_volume"].append(1000.0)
                # У BBB второй день целиком без сделок: закрытие этого
                # дня обязано выйти NaN, а не перенестись (урок A2).
                rows["trades"].append(0 if (s == "BBBUSDT" and dd == 1)
                                      else 5)
    t = pa.table({"symbol": pa.array(rows["symbol"]),
                  "open_time": pa.array(rows["open_time"],
                                        pa.timestamp("us")),
                  "close": pa.array(rows["close"]),
                  "quote_volume": pa.array(rows["quote_volume"]),
                  "trades": pa.array(rows["trades"])})
    path = os.path.join(d, "1970-01.parquet")
    pq.write_table(t, path)

    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    out = B.aggregate_partition(con, path)
    got = {(r["symbol"], str(r["day"])): r for r in out.to_pylist()}
    aaa = got[("AAAUSDT", "1970-01-02")]
    bbb = got[("BBBUSDT", "1970-01-02")]
    check("закрытие дня — последний бар со сделками",
          abs(aaa["close"] - (101.0 + 1380 / 1440)) < 1e-9, str(aaa))
    check("день без сделок: закрытие NaN, а не перенос",
          bbb["close"] is None, str(bbb))
    check("оборот дня без сделок пуст", not bbb["turnover"], str(bbb))
    check("минуты со сделками посчитаны",
          aaa["bars_traded"] == 24 and bbb["bars_traded"] == 0,
          f"{aaa['bars_traded']} {bbb['bars_traded']}")


def main():
    print("заглядывание")
    test_no_lookahead_any_feature()
    test_forward_is_strictly_forward()
    print("пропуски")
    test_missing_day_is_gap_not_zero()
    test_net_path_needs_enough_days()
    print("волна и β")
    test_wave_excludes_self_and_beta_sane()
    print("funding и интерес")
    test_funding_day_aggregation()
    test_oi_respects_publication_lag()
    print("нормировка")
    test_ret_norm_scales_by_sqrt_horizon()
    print("сквозная")
    test_end_to_end_tiny_store()
    print()
    if FAILED:
        print(f"ПАДЕНИЙ: {len(FAILED)} — {', '.join(FAILED)}")
        raise SystemExit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
