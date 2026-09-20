"""Негативные контроли механики bb7c3581 — СУДИТ САМА ПРИЁМКА.

Своей копии проверяющей машины здесь нет намеренно. Строитель d71203f0
написал такую копию, она объявила 24 контроля из 24 кусающимися, а
приёмка фабрики отвергла два: копия читала весь вывод сюиты, приёмка —
последние 4000 символов. Копия, поддатливее проверяемой машины, врёт
ровно в ту сторону, ради которой её и заводят.

Поэтому здесь вызывается `runlog.check_build` — тот самый код, которым
фабрика примет или отвергнет постройку: он сам применяет каждую подделку
к копии файла, сам прогоняет сюиту (в своём каталоге байткода — иначе
`.pyc` предыдущей подделки исполняется вместо новой), сам требует
падения ИМЕННО названной проверки и сам возвращает файл на место.

    .venv/bin/python research/mech_bb7c3581/controls_check.py \
            research/factory/out/build.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "research", "factory"))
import runlog as RL                                           # noqa: E402

DEFAULT = os.path.join("research", "factory", "out", "build.json")


def main(report=None):
    report = report or DEFAULT
    with open(os.path.join(ROOT, report), encoding="utf-8") as f:
        text = f.read()
    d = json.loads(text)
    print(f"контролей объявлено: {len(d.get('controls') or [])}; "
          f"сюита {d.get('tests')}")
    ok, bad = RL.check_build(text, ROOT,
                             out_dir=os.path.join(ROOT, "research", "factory",
                                                  "out"))
    for b in bad:
        print(f"  БЕДА: {b}")
    print("ПРИЁМКА: " + ("годно" if ok else "ОТВЕРГНУТО"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
