#!/usr/bin/env python3
"""Перелив старых часов записи стакана с полного тома на корень — с
символьной ссылкой на месте каждого файла.

Повод (2026-09-06). Докупленный том 150 ГБ (`HC_Volume_106683528`,
bind mount на `research/b1_book/out`) заполнен на 95 % за 33 дня записи
(≈ 4 ГБ/сут), а на корне свободно 76 ГБ. Решение владельца: занять
корень. Перенос сделан ссылками, а не переносом каталога и не сменой
монтирования: сборщик продолжает писать в тот же путь, читатели
(`store.read_hour` через `os.path.exists`/`open`) видят файлы по тем же
именам, ничего не перезапускается, и всё обратимо файл за файлом.

Что переносится: ТОЛЬКО сжатые часы `<sub>/<SYM>/ГГГГ-ММ-ДД-ЧЧ.jsonl.gz`
за дни не позже `--upto` (по умолчанию позавчера: текущий и вчерашний
день — зона сборщика и его сжатия). Несжатый `.jsonl` не трогается
никогда — его ещё может сжать сборщик (`pack_stale`), и ссылка под ним
стала бы сиротой. Файлы, уже ставшие ссылками, пропускаются: прогон
идемпотентен.

Как переносится один файл — порядок, при котором оригинал не исчезает
раньше проверенной копии: копия во временное имя → сверка размера и
концов файла → `os.replace` во «взрослое» имя → `copystat` (mtime
сохраняется: по нему считают свежесть) → снятие оригинала → ссылка на
его место. Обрыв между двумя последними шагами лечится повтором: копия
найдена целой — ставится ссылка.

Предохранители: источник и приёмник обязаны лежать на РАЗНЫХ дисках
(если bind mount отвалился, источник уже на корне, и «перелив» стал
бы перекладыванием на том же диске — прогон отказывает); на корне
остаётся не меньше `--min-root-free-gb`; за прогон переносится не
больше `--max-gb`; `--dry-run` только считает. Прогон печатает ход
каждые 30 с, `df` обеих сторон до и после, и пишет строку в
`<приёмник>/spill.log`.

Запуск заданием очереди:
  run tools/spill_book.py --dry-run
  run tools/spill_book.py --max-gb 50
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "research", "b1_book", "out")
DEST = os.path.join(os.path.dirname(ROOT), "b1_spill")
SUBS = ("book", "trades")
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-\d{2}\.jsonl\.gz$")
REQUIRE_OTHER_DEV = True          # проверки на одном диске снимают флаг
TAIL_CHECK = 65536


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def df_line(path):
    try:
        r = subprocess.run(["df", "-h", path], capture_output=True, text=True)
        return r.stdout.strip().splitlines()[-1]
    except Exception:                                     # noqa: BLE001
        return f"{path}: df недоступен"


def candidates(src, upto, subs=SUBS):
    """(путь, размер, день) сжатых часов не позже `upto`, старые первыми."""
    out = []
    for sub in subs:
        d = os.path.join(src, sub)
        if not os.path.isdir(d):
            continue
        for sym in sorted(os.listdir(d)):
            sd = os.path.join(d, sym)
            if not os.path.isdir(sd):
                continue
            for fn in os.listdir(sd):
                m = NAME.match(fn)
                if not m or m.group(1) > upto:
                    continue
                p = os.path.join(sd, fn)
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                out.append((p, os.path.getsize(p), m.group(1)))
    out.sort(key=lambda t: (t[2], t[0]))
    return out


def _same_bytes_at_ends(a, b, size):
    n = min(TAIL_CHECK, size)
    with open(a, "rb") as fa, open(b, "rb") as fb:
        if fa.read(n) != fb.read(n):
            return False
        if size > n:
            fa.seek(size - n)
            fb.seek(size - n)
            if fa.read(n) != fb.read(n):
                return False
    return True


def copy_verified(src_path, dest_path):
    """Копия под временным именем, проверенная размером и концами файла;
    неполная или отличная копия — исключение, оригинал не тронут."""
    size = os.path.getsize(src_path)
    if (os.path.exists(dest_path) and os.path.getsize(dest_path) == size
            and _same_bytes_at_ends(src_path, dest_path, size)):
        return size                       # прошлый прогон оборвался после копии
    tmp = dest_path + ".tmp"
    shutil.copyfile(src_path, tmp)
    got = os.path.getsize(tmp)
    if got != size:
        os.remove(tmp)
        raise IOError(f"копия неполна: {src_path} ({got} из {size} байт)")
    if not _same_bytes_at_ends(src_path, tmp, size):
        os.remove(tmp)
        raise IOError(f"копия отличается: {src_path}")
    os.replace(tmp, dest_path)
    shutil.copystat(src_path, dest_path)
    return size


def spill_one(src_path, dest_path):
    """Перенести один файл; вернуть размер. Оригинал уступает место
    ссылке только после проверенной копии."""
    if os.path.islink(src_path):
        return 0
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    size = copy_verified(src_path, dest_path)
    os.remove(src_path)
    os.symlink(dest_path, src_path)
    return size


def run(src=SRC, dest=DEST, upto=None, max_gb=50.0, min_root_free_gb=20.0,
        dry_run=False, subs=SUBS, log=log):
    today = datetime.now(timezone.utc).date()
    lim_day = (today - timedelta(days=2)).isoformat()
    upto = upto or lim_day
    if upto > lim_day:
        raise SystemExit(f"ОТКАЗ: --upto {upto} позже позавчера {lim_day} — "
                         "текущий и вчерашний день принадлежат сборщику")
    os.makedirs(dest, exist_ok=True)
    if REQUIRE_OTHER_DEV and os.stat(src).st_dev == os.stat(dest).st_dev:
        raise SystemExit(f"ОТКАЗ: {src} и {dest} на одном диске — bind mount "
                         "записи не на месте? переливать некуда")
    log(f"до: {df_line(src)}")
    log(f"до: {df_line(dest)}")
    cands = candidates(src, upto, subs)
    total = sum(s for _, s, _ in cands)
    log(f"кандидатов {len(cands)} файлов, {total / 2**30:.1f} ГБ, дни "
        f"{cands[0][2] if cands else '—'} … {cands[-1][2] if cands else '—'}; "
        f"предел за прогон {max_gb:g} ГБ, запас корня {min_root_free_gb:g} ГБ")
    moved, n, stop = 0, 0, None
    t0, said = time.time(), time.time()
    if not dry_run:
        for p, size, day in cands:
            if moved + size > max_gb * 2**30:
                stop = f"предел {max_gb:g} ГБ за прогон"
                break
            if free_bytes(dest) - size < min_root_free_gb * 2**30:
                stop = (f"на приёмнике осталось бы меньше {min_root_free_gb:g} ГБ "
                        f"({free_bytes(dest) / 2**30:.1f})")
                break
            rel = os.path.relpath(p, src)
            moved += spill_one(p, os.path.join(dest, rel))
            n += 1
            if time.time() - said > 30:
                log(f"  перенесено {n}/{len(cands)}, {moved / 2**30:.1f} ГБ, "
                    f"день {day}")
                said = time.time()
    secs = round(time.time() - t0, 1)
    log(f"{'считал бы' if dry_run else 'перенесено'} {n} файлов, "
        f"{moved / 2**30:.2f} ГБ за {secs} с"
        + (f"; остановлен: {stop}" if stop else ""))
    log(f"после: {df_line(src)}")
    log(f"после: {df_line(dest)}")
    if not dry_run:
        with open(os.path.join(dest, "spill.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                    f"файлов {n} байт {moved} до {upto} стоп {stop}\n")
    return {"files": n, "bytes": moved, "candidates": len(cands),
            "cand_bytes": total, "stop": stop, "upto": upto, "secs": secs}


def main(argv=None):
    ap = argparse.ArgumentParser(description="перелив старых часов записи на корень")
    ap.add_argument("--upto", default=None,
                    help="последний день (ГГГГ-ММ-ДД), по умолчанию позавчера")
    ap.add_argument("--max-gb", type=float, default=50.0)
    ap.add_argument("--min-root-free-gb", type=float, default=20.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        os.nice(15)
        subprocess.run(["ionice", "-c", "3", "-p", str(os.getpid())],
                       capture_output=True)
    except Exception:                                     # noqa: BLE001
        pass
    run(upto=a.upto, max_gb=a.max_gb, min_root_free_gb=a.min_root_free_gb,
        dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
