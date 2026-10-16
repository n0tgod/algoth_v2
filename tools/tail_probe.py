"""Зонд: хвосты логов прогонов книг на сервере (ничего не меняет).

    run tools/tail_probe.py --n=60
"""
import argparse
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGS = ["research/dca_paper/out/daily.log", "research/dca_paper/out/short.log",
        "research/dca_paper/out/pair.log"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()
    for rel in LOGS:
        p = os.path.join(ROOT, rel)
        print(f"===== {rel}", "(нет файла)" if not os.path.exists(p) else
              f"{os.path.getsize(p)} байт")
        if os.path.exists(p):
            with open(p, "rb") as f:
                f.seek(max(0, os.path.getsize(p) - 400_000))
                lines = f.read().decode("utf-8", "replace").splitlines()
            print("\n".join(lines[-a.n:]))


if __name__ == "__main__":
    main()
