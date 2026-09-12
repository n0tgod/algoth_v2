"""Машина негативных контролей механики d71203f0.

Каждая подделка из `build.json` применяется к КОПИИ файла, сюита
прогоняется заново, файл восстанавливается и сверяется по sha256.
Требуется не просто падение, а падение ИМЕННО названной проверки:
контроль, роняющий что-то другое, ничего не доказывает о том правиле,
ради которого написан.

**Судит здесь не своя копия правила, а сама приёмка.** Первая редакция
этого файла читала ВЕСЬ вывод сюиты и объявила 24 контроля из 24
кусающимися; приёмка фабрики (`runlog._run_tests`) смотрит ПОСЛЕДНИЕ
4000 символов — и отвергла два, чьё падение до хвоста не дошло, потому
что сюиту обрывало исключение. Копия, поддатливее проверяемой машины,
врёт ровно в ту сторону, ради которой её и заводят: «у меня всё
зелёное» при красной приёмке. Поэтому сюиту прогоняет `runlog._run_tests`
— тот же код, тем же чтением хвоста.

Байткод та же функция кладёт в свой каталог на каждый прогон, и это не
гигиена. Питон считает `.pyc` свежим по паре (mtime источника в целых
секундах, размер), а машина подделок пишет в один и тот же файл подряд —
замена одной строки сплошь и рядом даёт файл того же размера в ту же
секунду, и прогон исполняет байткод ПРЕДЫДУЩЕЙ подделки. Врёт это в обе
стороны: холостой контроль объявляется кусающимся и наоборот.

    .venv/bin/python research/mech_d71203f0/controls_check.py \
            research/factory/out/build.json
"""
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SUITE = "research/mech_d71203f0/test_unprovoked.py"

sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import runlog as RL                                          # noqa: E402


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run():
    """(прошла, хвост вывода) — ровно так, как это делает приёмка."""
    return RL._run_tests(ROOT, SUITE)


def main(report):
    with open(report, encoding="utf-8") as f:
        controls = json.load(f)["controls"]
    ok, out = run()
    print(f"=== база: {'зелёная' if ok else 'КРАСНАЯ'} ===")
    if not ok:
        print(out[-2000:])
        return 1

    bad = []
    for i, c in enumerate(controls, 1):
        p = os.path.join(ROOT, c["file"])
        before = sha(p)
        with open(p, encoding="utf-8") as f:
            orig = f.read()
        # Подделка обязана быть ОДНОЗНАЧНОЙ: строка, встречающаяся
        # дважды, подменила бы заодно и то место, о котором контроль
        # ничего не утверждает.
        if orig.count(c["old"]) != 1:
            print(f"  #{i} НЕПРИМЕНИМ: строка встречается "
                  f"{orig.count(c['old'])} раз")
            bad.append(i)
            continue
        t0 = time.time()
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(orig.replace(c["old"], c["new"], 1))
            passed, txt = run()
        finally:
            with open(p, "w", encoding="utf-8") as f:
                f.write(orig)
        assert sha(p) == before, f"#{i}: файл не восстановлен"
        want = c.get("expect") or ""
        if passed:
            print(f"  #{i} ХОЛОСТОЙ: подделка прошла мимо сюиты  "
                  f"[{want[:52]}]")
            bad.append(i)
        elif want and want not in txt:
            # Сюита упала, но названной проверки в ХВОСТЕ нет — значит
            # её оборвало что-то постороннее либо падение не дожило до
            # сводки. Для приёмки это неотличимо от холостого контроля,
            # и здесь тоже.
            print(f"  #{i} УПАЛО НЕ ТО: обещано {want[:52]!r}; в хвосте "
                  "его нет")
            print("      " + " / ".join(
                ln.strip() for ln in txt.splitlines()
                if ln.startswith("ПАДЕНИЙ:"))[:300])
            bad.append(i)
        else:
            print(f"  #{i} кусается ({round(time.time() - t0, 1)} с): "
                  f"{want[:60]}")

    print(f"\nитог: {len(controls) - len(bad)} из {len(controls)} кусаются"
          + ("" if not bad else f"; НЕГОДНЫЕ: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "research", "factory", "out", "build.json")))
