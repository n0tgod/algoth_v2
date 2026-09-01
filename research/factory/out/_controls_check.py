"""Машина негативных контролей: подделка -> сюита обязана упасть.

Каждая подделка из `build.json` применяется к КОПИИ файла, прогоняется
`test_ceiling.py`, файл восстанавливается и сверяется по sha256.
Требуется не просто падение, а падение ИМЕННО названной проверки:
контроль, роняющий что-то другое, ничего не доказывает о том правиле,
ради которого написан.

    python3 research/factory/out/_controls_check.py \
            research/factory/out/build.json

Файл лежит в `out/` потому, что роль строителя пишет только туда и в
названный заданием каталог; удалить его после прогона нельзя —
`research/*/out` защищён от удаления правилами сохранности данных
(`docs/DATA-SAFETY.md`), поэтому он объявлен в `touched`, а не оставлен
молча. Предыдущие заходы адверсарий писал такую машину заново каждый
раз; здесь она лежит рядом с отчётом, чтобы проверку можно было
ПОВТОРИТЬ, а не пересказать.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = "/root/algoth_v2"
SUITES = ["research/factory/test_ceiling.py",
          "research/factory/test_run_day.py",
          "research/factory/test_factory.py",
          "research/factory/test_candidate.py"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def drop_pyc(d):
    """Снести кеш байткода каталога. Артефактов не трогает: `__pycache__`
    порождается питоном и восстанавливается сам."""
    p = os.path.join(d, "__pycache__")
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)


def run(suite):
    """Код возврата и ИМЕНА провалившихся проверок, а не только код.

    Одного кода мало: контроль, роняющий сюиту чем-то посторонним,
    выглядел бы кусающимся, ничего не проверив о своём правиле.

    Байткод НЕ кешируется, и это не гигиена, а дефект, найденный
    измерением. Питон считает `.pyc` свежим по паре (mtime источника в
    целых секундах, размер), а машина подделок пишет в один и тот же
    файл подряд, и замены одной строки сплошь и рядом дают файл ТОГО ЖЕ
    размера. Тогда прогон исполняет байткод ПРЕДЫДУЩЕЙ подделки, и
    результат врёт в обе стороны: холостой контроль показывает «кусается»
    (чужой подделкой), кусающийся — «холостой».

    Показано на последовательности A,B,B,A,B,B, где A = `r·days**0.05`
    (роняет сюиту), B = `r·days**0.01` (не роняет) и файлы равны по
    длине: с кешем вышло 1,0,0,**0**,0,0 — четвёртый прогон объявил
    падающую подделку прошедшей. Со стёртым кешем и с
    `PYTHONDONTWRITEBYTECODE` — 1,0,0,1,0,0 оба раза.

    Цена дефекта не в этой машине: через неё проходили ВСЕ контроли
    фабрики, включая двенадцать прошлого захода, которые адверсарий
    воспроизводил ею же.
    """
    # Одного `-B` мало: он запрещает ПИСАТЬ байткод, а читать уже
    # лежащий — нет. Проверено было сочетание «стереть кеш и не писать
    # новый», им и чиним.
    drop_pyc(os.path.dirname(os.path.join(ROOT, suite)))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-B", os.path.join(ROOT, suite)],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    fails = [l.split("ПРОВАЛ", 1)[1].split(" — ")[0].strip()
             for l in r.stdout.splitlines() if "ПРОВАЛ " in l]
    return r.returncode, fails


def main(report):
    controls = json.load(open(report, encoding="utf-8"))["controls"]
    print("=== база ===")
    base_ok = True
    for s in SUITES:
        rc, f = run(s)
        print(f"  {s}: rc={rc} провалов={len(f)}")
        base_ok = base_ok and rc == 0 and not f
    print("база зелёная" if base_ok else "БАЗА КРАСНАЯ")

    print("\n=== контроли ===")
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
        open(p, "w", encoding="utf-8").write(orig.replace(c["old"], c["new"]))
        try:
            rc, fails = run("research/factory/test_ceiling.py")
        finally:
            open(p, "w", encoding="utf-8").write(orig)
        assert sha(p) == before, f"#{i}: файл не восстановлен"
        hit = [f for f in fails if c["expect"] in f]
        ok = rc != 0 and hit
        print(f"  #{i} {'кусается' if ok else 'ХОЛОСТОЙ'}: rc={rc}, "
              f"провалов={len(fails)}, названная={'да' if hit else 'НЕТ'}"
              f"  [{c['expect'][:52]}]")
        if not ok:
            print(f"      провалились: {fails}")
            bad.append(i)

    print(f"\nитог: {len(controls) - len(bad)} из {len(controls)} кусаются"
          + ("" if not bad else f"; ХОЛОСТЫЕ: {bad}"))
    return 1 if bad or not base_ok else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
