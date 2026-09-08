#!/usr/bin/env python3
"""Догон справочника инструментов площадки: моменты листинга.

Зачем. `instruments.json` собран однажды и стареет так же, как ряды
funding: на 2026-09-08 в нём не было 109 символов, которые площадка
торгует сейчас, — а именно новые листинги оказались тем, что решало
исход замера гейта. Возраст имени на момент решения без даты листинга
не посчитать вовсе.

Что делает. Спрашивает справочник по всем статусам (тем же кодом, что
сборщик A1 — второй копии пагинации нет), объединяет со старым файлом и
пишет ЦЕЛИКОМ через временный файл с атомарной заменой (класс B,
`docs/DATA-SAFETY.md`). Старую запись не удаляет: делистнутый символ
остаётся с его последним известным состоянием, иначе история потеряет
имена, которыми книги торговали.

Отчёт: `out/instruments-refresh.md` (+ `.json`), публикует сам.
Запуск: `run research/a1_universe/instruments_refresh.py`.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import bybit_api as B                                         # noqa: E402

OUT = B.OUT
PATH = os.path.join(OUT, "instruments.json")


def read_old(path=None):
    path = path or PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def merge(old, fresh):
    """Свежая запись побеждает, старая не исчезает.

    Возвращает (объединение, сколько новых, сколько обновлённых).
    """
    out = dict(old)
    new = upd = 0
    for k, v in (fresh or {}).items():
        if k not in out:
            new += 1
        elif out[k] != v:
            upd += 1
        out[k] = v
    return out, new, upd


def write(data, path=None):
    """Класс B: сперва временный файл, потом атомарная замена."""
    path = path or PATH
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def launch_days(data, at=None):
    """Символ → возраст в сутках на момент `at`. Нет даты — символа нет."""
    at = float(at if at is not None else time.time())
    out = {}
    for sym, v in (data or {}).items():
        try:
            lt = float(v.get("launch_time")) / 1000.0
        except (TypeError, ValueError):
            continue
        if lt > 0:
            out[sym] = (at - lt) / 86400.0
    return out


def run(log=print, collect=None, path=None):
    t0 = time.time()
    old = read_old(path)
    # Метка дня в ключе кэша: без неё ответ площадки берётся из кэша
    # прошлого прогона, и догон объявляет «новых 0», ничего не спросив.
    tag = "_" + datetime.now(timezone.utc).date().isoformat()
    try:
        fresh = (collect(tag) if collect else B.collect_instruments(tag))
    except Exception as e:                                    # noqa: BLE001
        log(f"справочник не получен: {e}")
        return {"error": f"справочник не получен: {e}"[:200],
                "had": len(old)}
    data, new, upd = merge(old, fresh)
    write(data, path)
    ages = launch_days(data)
    log(f"справочник: было {len(old)}, пришло {len(fresh)}, новых {new}, "
        f"обновлённых {upd}, всего {len(data)}; с датой листинга {len(ages)}")
    return {"had": len(old), "fetched": len(fresh), "new": new,
            "updated": upd, "total": len(data), "with_launch": len(ages),
            "young_30d": sum(1 for d in ages.values() if d < 30),
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
            "secs": round(time.time() - t0, 1)}


def report(s):
    L = ["# Догон справочника инструментов", ""]
    if s.get("error"):
        return "\n".join(L + [f"**Не обновлён:** {s['error']}. Прежний файл "
                              f"({s.get('had')} символов) не тронут.", ""])
    L += [f"Прогон {s['computed_at']}: было {s['had']} символов, пришло "
          f"{s['fetched']}, новых **{s['new']}**, обновлённых {s['updated']}, "
          f"всего {s['total']}; с моментом листинга {s['with_launch']}, из "
          f"них моложе 30 суток {s['young_30d']}. Прогон {s['secs']} с.", "",
          "Старые записи не удаляются: делистнутый символ остаётся с "
          "последним известным состоянием, иначе история потеряет имена, "
          "которыми книги торговали.", ""]
    return "\n".join(L)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="догон справочника инструментов")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                        # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)
    s = run()
    with open(os.path.join(OUT, "instruments-refresh.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, "instruments-refresh.md"), "w",
              encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"A1: догон справочника инструментов (+{s.get('new', 0)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
