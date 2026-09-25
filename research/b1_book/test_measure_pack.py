#!/usr/bin/env python3
"""Проверки замера форматов записи: выбор имён, дельты без потерь,
порядок вариантов, «не измерено» без zstd, контроль gzip заново."""
import gzip
import json
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import measure_pack as M                                      # noqa: E402

DAY = "2026-09-22"


def _rows(seed, n=90, depth=8):
    rnd = random.Random(seed)
    bids = {round(0.05 - i * 0.0001, 4): float(rnd.randint(1, 900)) for i in range(depth)}
    asks = {round(0.0501 + i * 0.0001, 4): float(rnd.randint(1, 900)) for i in range(depth)}
    out = []
    for s in range(n):
        if rnd.random() < 0.3:
            p = rnd.choice(list(bids))
            bids[p] = float(rnd.randint(1, 900))
        if rnd.random() < 0.1:                      # уровень уходит и приходит
            p = min(asks)
            asks.pop(p)
            asks[round(p + 0.0001 * depth, 4)] = float(rnd.randint(1, 900))
        b = sorted(bids.items(), key=lambda x: -x[0])
        a = sorted(asks.items())
        out.append({"s": "AAAUSDT", "ts": 1790000000000 + s * 1000, "u": s,
                    "bid": b[0][0], "ask": a[0][0], "bid_sz": b[0][1],
                    "ask_sz": a[0][1], "upd": rnd.randint(0, 9),
                    "b": [[p, q] for p, q in b], "a": [[p, q] for p, q in a],
                    "reach_b": 12.5, "reach_a": 13.0, "bq0.001": 1.0,
                    "t": 1790000000.3 + s})
    return out


def _write(root, sub, sym, hh, lines):
    d = os.path.join(root, sub, sym)
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, f"{DAY}-{hh:02d}.jsonl.gz"), "wt",
                   encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _root():
    root = tempfile.mkdtemp(prefix="measure-")
    for i, sym in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")):
        for hh in (11, 12, 13):
            rows = _rows(i * 10 + hh, n=90 * (i + 1))
            _write(root, "book", sym, hh, [json.dumps(r) for r in rows])
            _write(root, "trades", sym, hh,
                   [json.dumps({"ts": r["ts"], "s": sym, "side": 1, "p": r["bid"],
                                "v": 5.0}) for r in rows[::3]])
    return root


def test_deltas_are_lossless_and_a_broken_stream_is_caught():
    rows = _rows(3, n=200)
    d = M.encode_deltas(rows, keyframe=60)
    assert sum(1 for x in d if x.get("k") == 1) == 4, "ключевых кадров 4 на 200 строк"
    back = M.decode_deltas(d)
    assert M.same_rows(rows, back), "дельты не восстановили снимки"
    assert back[77]["b"] == rows[77]["b"] and back[77]["a"] == rows[77]["a"]
    # контроль: испорченная дельта ловится сверкой, а не проходит молча
    bad = json.loads(json.dumps(d))
    bad[5]["db"] = bad[5].get("db", []) + [[0.0499, 7.0]]
    assert not M.same_rows(rows, M.decode_deltas(bad)), "сверка не увидела порчу"
    print("ok  дельты без потерь на 200 снимках; испорченная дельта ловится сверкой")


def test_measure_on_a_synthetic_day():
    root = _root()
    try:
        book = M.day_files(root, "book", DAY)
        assert len(book) == 12, len(book)
        names = M.pick_names(book, 3)
        assert names == ["DDDUSDT", "BBBUSDT", "AAAUSDT"] or set(names) == {"DDDUSDT", "BBBUSDT", "AAAUSDT"}, names
        said = []
        res = M.measure(root, DAY, names=3, hours=(12, 13), level=3,
                        log=said.append)
        by = {r["key"]: r for r in res["book"]}
        assert by["disk_gz"]["bytes"] > 0 and by["disk_gz"]["ratio"] == 1.0
        # контроль: gzip заново близок к тому, что лежит на диске
        assert 0.9 < by["gzip9"]["ratio"] < 1.1, by["gzip9"]
        # порядок: скаляры < 10 уровней ≤ полный; дельты измерены
        assert by["scalars_zstd"]["bytes"] < by["top10_zstd"]["bytes"] <= by["zstd"]["bytes"] * 1.05, by
        assert by["deltas_zstd"]["bytes"] > 0 and by["zstd_dict"]["bytes"] > 0
        assert all(r["missing_hours"] == 0 for r in res["book"]), res["book"]
        assert 0.3 < res["ladder_share"] < 0.95, res["ladder_share"]
        assert res["day_on_disk"]["files_book"] == 12 and res["rows"] > 0
        assert res["trades"]["ratio"] is not None and res["trades"]["disk_gz"] > 0
        txt = M.report(res)
        assert "| gzip, как на диске |" in txt and "ГБ/сут" in txt
        # пересчёт на сутки: доля × размер суток
        assert abs(by["zstd"]["day_gb"] - res["day_on_disk"]["book_gb"] * by["zstd"]["ratio"]) < 1e-9
        print(f"ok  замер на подставных сутках: {len(names)} имени, доля лесенки "
              f"{100 * res['ladder_share']:.0f} %, zstd {by['zstd']['ratio']:.2f}, "
              f"скаляры {by['scalars_zstd']['ratio']:.2f} от gzip")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_without_zstd_the_variants_are_unmeasured_not_zero():
    root = _root()
    was = M.zstd
    try:
        M.zstd = None
        res = M.measure(root, DAY, names=2, hours=(12,), with_xz=False,
                        log=lambda *a: None)
        by = {r["key"]: r for r in res["book"]}
        assert by["zstd"]["bytes"] is None and by["zstd"]["ratio"] is None
        assert by["zstd"]["missing_hours"] == 2, by["zstd"]
        assert by["gzip9"]["ratio"] is not None
        assert res["trades"]["ratio"] is None and res["trades"]["missing_hours"] == 2
        txt = M.report(res)
        assert "не измерено у 2 часов" in txt and "варианты zstd не измерены" in txt
        print("ok  без zstd варианты помечены «не измерено», gzip посчитан")
    finally:
        M.zstd = was
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    test_deltas_are_lossless_and_a_broken_stream_is_caught()
    test_measure_on_a_synthetic_day()
    test_without_zstd_the_variants_are_unmeasured_not_zero()
    print("\nвсе 3 проверки прошли")
