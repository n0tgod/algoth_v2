"""Замороженная модель: лист теми же строками, живой лист не тронут.

Кусается: (1) `sheet_rows` даёт ровно тот лист, что `situational_arm`
(бит в бит — иначе вынос блока есть другая мера); (2) без полной сетки
весов заморозка отказывает словами, а не считает часть рук; (3) с
полной сеткой `frozen_sheets` пишет строку часа с номером
замороженного обучения и номером живого; (4) архив весов обучения
кладёт все файлы сетки в `archive/seq<N>/`.
"""
import json
import os
import pickle
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import train as T                                             # noqa: E402


class Stub:
    def __init__(self, by_row):
        self.by_row = np.asarray(by_row, dtype=float)
        self.importance = np.array([1.0, 0.0])

    def predict(self, xs):
        idx = np.asarray(xs)[:, 0].astype(int)
        return self.by_row[idx]


def _world():
    syms = ["AUSDT", "BUSDT", "CUSDT", "DUSDT"]
    grid = ["2026-10-15-10", "2026-10-15-11"]
    n, feat = len(syms), 2
    x = np.zeros((n, len(grid), feat))
    for i in range(n):
        x[i, :, 0] = i
    mats = {"mid_close": np.full((n, len(grid)), 100.0)}
    lo, hi = np.full(feat, -1e9), np.full(feat, 1e9)
    k = T.SIT_SIGNAL_H
    models = {("gbm", f"fwd_{k}h"): Stub([30.0, 10.0, -40.0, 25.0]),
              ("gbm", f"mae_{k}h"): Stub([-10.0, -5.0, -50.0, -20.0]),
              ("gbm", f"mfe_{k}h"): Stub([25.0, 30.0, 20.0, 30.0])}
    return syms, grid, x, mats, np.arange(n), lo, hi, models


def test_sheet_rows_is_the_live_sheet():
    syms, grid, x, mats, rows, lo, hi, models = _world()
    d = tempfile.mkdtemp()
    try:
        live = T.situational_arm(d, "gbm", models, x, mats, syms, rows, 1,
                                 grid, lo, hi, None, lambda m: None)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    mine = T.sheet_rows(models, "gbm", x, mats, syms, rows, 1, lo, hi, lambda m: None)
    assert live and json.dumps(live, sort_keys=True) == json.dumps(mine, sort_keys=True), (live, mine)
    print(f"ok  sheet_rows == лист situational_arm бит в бит ({len(mine)} строк)")


def _grid_models():
    out = {}
    for arm, _ in T.ARMS:
        for tgt in T.TARGETS:
            out[(arm, tgt)] = Stub([30.0, 10.0, -40.0, 25.0])
    return out


def _write_weights(d, models, seq, skip=None):
    os.makedirs(d, exist_ok=True)
    for (arm, tgt), m in models.items():
        if skip and (arm, tgt) == skip:
            continue
        with open(os.path.join(d, f"weights_{arm}_{tgt}.pkl"), "wb") as f:
            pickle.dump({"model": m, "version": T.MODEL_VERSION, "features": ["f0", "f1"],
                         "train_seq": seq, "arm": arm, "target": tgt}, f)


def test_frozen_refuses_partial_grid_and_writes_full():
    syms, grid, x, mats, rows, lo, hi, _ = _world()
    saved = T.MODEL_DIR
    td = tempfile.mkdtemp()
    T.MODEL_DIR = os.path.join(td, "model")
    T._FROZEN_CACHE.update(sig=None, models=None, seq=None, why=None)
    logs = []
    try:
        mdir = os.path.join(td, "model_sit")
        os.makedirs(mdir)
        # нет каталога заморозки — тишина и ноль
        assert T.frozen_sheets(mdir, x, mats, syms, rows, 1, grid, lo, hi, logs.append,
                               names=["f0", "f1"], live_seq=40) == 0
        assert not os.path.exists(os.path.join(mdir, "sheets_frozen.jsonl"))
        # неполная сетка — отказ словами, файла нет
        full = _grid_models()
        first = next(iter(full))
        _write_weights(T.frozen_dir(), full, 7, skip=first)
        assert T.frozen_sheets(mdir, x, mats, syms, rows, 1, grid, lo, hi, logs.append,
                               names=["f0", "f1"], live_seq=40) == 0
        assert logs and "нет весов" in logs[-1], logs
        assert not os.path.exists(os.path.join(mdir, "sheets_frozen.jsonl"))
        # полная сетка — строка часа с обоими номерами
        _write_weights(T.frozen_dir(), full, 7)
        n = T.frozen_sheets(mdir, x, mats, syms, rows, 1, grid, lo, hi, logs.append,
                            names=["f0", "f1"], live_seq=40)
        assert n == len(T.ARMS), (n, logs)
        with open(os.path.join(mdir, "sheets_frozen.jsonl"), encoding="utf-8") as f:
            rec = json.loads(f.readline())
        assert rec["train_seq"] == 7 and rec["live_seq"] == 40 and rec["frozen"] is True, rec
        assert rec["hour"] == grid[1] and set(rec["arms"]) == {a for a, _ in T.ARMS}
        assert {r["sym"] for r in rec["arms"]["gbm"]} == set(syms)
        # другой список признаков — отказ (модель смотрела бы не на те колонки)
        T._FROZEN_CACHE.update(sig=None, models=None, seq=None, why=None)
        assert T.frozen_sheets(mdir, x, mats, syms, rows, 1, grid, lo, hi, logs.append,
                               names=["f0", "zzz"], live_seq=40) == 0
        assert "признаков" in logs[-1], logs[-1]
        # архив обучения
        _write_weights(T.MODEL_DIR, full, 41)
        with open(os.path.join(T.MODEL_DIR, "manifest.json"), "w") as f:
            json.dump({"train_seq": 41}, f)
        dst = T.archive_weights(41, logs.append)
        assert dst and dst.endswith("seq41")
        files = sorted(os.listdir(dst))
        assert len(files) == len(full) + 1 and "manifest.json" in files, files
    finally:
        T.MODEL_DIR = saved
        T._FROZEN_CACHE.update(sig=None, models=None, seq=None, why=None)
        shutil.rmtree(td, ignore_errors=True)
    print("ok  заморозка: нет каталога — тишина; неполная сетка и чужие признаки — отказ словами; "
          "полная — строка часа с №7 (заморозка) и №40 (живое); архив обучения — вся сетка")


if __name__ == "__main__":
    test_sheet_rows_is_the_live_sheet()
    test_frozen_refuses_partial_grid_and_writes_full()
