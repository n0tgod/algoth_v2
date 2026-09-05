"""Машина негативных контролей механики 994fc54f.

Каждая подделка из `build.json` применяется к КОПИИ файла, сюита
прогоняется заново, файл восстанавливается и сверяется по sha256.
Требуется не просто падение, а падение ИМЕННО названной проверки:
контроль, роняющий что-то другое, ничего не доказывает о том правиле,
ради которого написан.

Байткод при этом НЕ кешируется, и это не гигиена. Питон считает `.pyc`
свежим по паре (mtime источника в целых секундах, размер), а машина
подделок пишет в один и тот же файл подряд — замена одной строки сплошь
и рядом даёт файл того же размера в ту же секунду, и прогон исполняет
байткод ПРЕДЫДУЩЕЙ подделки. Врёт это в обе стороны: холостой контроль
объявляется кусающимся и наоборот. Дефект найден ролью строителя на
своей копии этой машины и уже исправлен в `runlog._run_tests`; здесь он
исправлен так же, чтобы проверку можно было ПОВТОРИТЬ, а не пересказать.

    .venv/bin/python research/mech_994fc54f/controls_check.py \
            research/factory/out/build.json
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SUITE = "research/mech_994fc54f/test_bid_survives.py"


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run():
    """Код возврата и ИМЕНА упавших проверок, а не только код."""
    for d in (os.path.join(ROOT, "research", "mech_994fc54f"),):
        shutil.rmtree(os.path.join(d, "__pycache__"), ignore_errors=True)
    py = os.path.join(ROOT, ".venv", "bin", "python")
    if not os.path.exists(py):
        py = sys.executable
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([py, "-B", os.path.join(ROOT, SUITE)], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    fails = [ln.split("ПАДЕНИЕ", 1)[1].split(":")[0].strip()
             for ln in r.stdout.splitlines() if "ПАДЕНИЕ " in ln]
    return r.returncode, fails


def main(report):
    controls = json.load(open(report, encoding="utf-8"))["controls"]
    rc, fails = run()
    print(f"=== база: rc={rc}, падений={len(fails)} ===")
    base_ok = rc == 0 and not fails
    print("база зелёная" if base_ok else f"БАЗА КРАСНАЯ: {fails}")

    bad = []
    for i, c in enumerate(controls, 1):
        p = os.path.join(ROOT, c["file"])
        before, orig = sha(p), open(p, encoding="utf-8").read()
        # Подделка обязана быть ОДНОЗНАЧНОЙ: строка, встречающаяся
        # дважды, подменила бы заодно и то место, о котором контроль
        # ничего не утверждает.
        if orig.count(c["old"]) != 1:
            print(f"  #{i} НЕПРИМЕНИМ: строка встречается "
                  f"{orig.count(c['old'])} раз")
            bad.append(i)
            continue
        open(p, "w", encoding="utf-8").write(
            orig.replace(c["old"], c["new"], 1))
        try:
            rc, fails = run()
        finally:
            open(p, "w", encoding="utf-8").write(orig)
        assert sha(p) == before, f"#{i}: файл не восстановлен"
        hit = [f for f in fails if c["expect"] in f]
        ok = rc != 0 and hit
        print(f"  #{i} {'кусается' if ok else 'ХОЛОСТОЙ'}: rc={rc}, "
              f"падений={len(fails)}, названная="
              f"{'да' if hit else 'НЕТ'}  [{c['expect'][:52]}]")
        if not ok:
            print(f"      упали: {fails}")
            bad.append(i)

    print(f"\nитог: {len(controls) - len(bad)} из {len(controls)} кусаются"
          + ("" if not bad else f"; ХОЛОСТЫЕ: {bad}"))
    return 1 if bad or not base_ok else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
