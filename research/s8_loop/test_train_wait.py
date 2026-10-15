#!/usr/bin/env python3
"""Ожидание памяти под обучение (`train.wait_train_mem`, 15.10): памяти
хватает сразу — идти, флаг поднят; не хватает — флаг поднят, проверки
каждые `step_s`, память освободилась — идти с причиной «дождался»; не
освободилась за `max_wait_s` — отказ, флаг снят. Флаг несёт pid процесса.

    .venv/bin/python research/s8_loop/test_train_wait.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import train as T                                             # noqa: E402


def main():
    d = tempfile.mkdtemp()
    flag = os.path.join(d, "train_wait.flag")
    logs = []
    slept = []
    # 1. хватает сразу
    ok, why = T.wait_train_mem(min_mb=3072, max_wait_s=60, step_s=15, log_=logs.append,
                               avail=lambda: 3600, sleep=slept.append, flag=flag)
    assert ok and not slept and os.path.exists(flag), (ok, why, slept)
    assert open(flag).read().split()[0] == str(os.getpid())
    T.clear_train_flag(flag)
    assert not os.path.exists(flag)
    # 2. не хватает, освободилась на третьей проверке
    seq = iter([2790, 2800, 2900, 3500, 3600])
    logs.clear(); slept.clear()
    clock = [1000.0]
    real_time = T.time.time
    T.time.time = lambda: clock[0]

    def sleep(s):
        slept.append(s)
        clock[0] += s
    try:
        ok, why = T.wait_train_mem(min_mb=3072, max_wait_s=600, step_s=15, log_=logs.append,
                                   avail=lambda: next(seq), sleep=sleep, flag=flag)
        assert ok and slept == [15, 15, 15] and "дождался за 45 с" in why, (ok, why, slept)
        assert os.path.exists(flag), "флаг при успехе остаётся до конца цикла"
        assert any("жду до 600 с" in m for m in logs), logs
        T.clear_train_flag(flag)
        # 3. не освободилась — отказ после max_wait_s, флаг снят
        logs.clear(); slept.clear()
        ok, why = T.wait_train_mem(min_mb=3072, max_wait_s=60, step_s=15, log_=logs.append,
                                   avail=lambda: 2500, sleep=sleep, flag=flag)
        assert not ok and len(slept) == 4 and "ждал 60 с" in why, (ok, why, slept)
        assert not os.path.exists(flag)
    finally:
        T.time.time = real_time
    # 4. контроль: без ожидания та же последовательность отказывает сразу
    ok0, _ = T.train_mem_ok(2790, 3072)
    assert not ok0
    print("ok  ожидание памяти: сразу/дождался за 45 с/отказ за 60 с; флаг с pid поднят при "
          "ожидании и успехе, снят при отказе")
    return 0


if __name__ == "__main__":
    sys.exit(main())
