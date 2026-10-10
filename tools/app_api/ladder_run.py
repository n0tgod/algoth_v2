#!/usr/bin/env python3
"""Супервизор живых исполнителей Ladder (спека 15 §7a.3, §10a).

Зовётся сторожем каждые 5 минут:

    .venv/bin/python tools/app_api/ladder_run.py --ensure

Что делает. Для каждой активной подписки в режиме `live` (перевела её
кнопка владельца в приложении — §7a.4; сам супервизор режим не меняет
никогда) держит запущенным ровно один процесс `bot ladder`: нет процесса
— запускает; подписка вышла из `live` — мягко останавливает (файл
`STOP`, выход между тактами). Новый код бота (исходники новее бинарника)
— пересобирает и мягко перезапускает работающие процессы: состояние
сохраняется каждым тактом, позиции и заявки продолжаются.

Ключ подписки открывается здесь (`keys_local.open_sub_key`, приватная
половина конвертов на сервере) и уходит процессу ТОЛЬКО трубой stdin —
не в аргументы, не в окружение, не на диск. Печатается только имя
подписки и что сделано.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import db as DBM                                             # noqa: E402

OUT = os.path.join(HERE, "out")
BIN = os.path.join(ROOT, "bot", "target", "release", "bot")
BASE = "https://api.bybit.com"
EXEC_ROOT = os.environ.get("ALGOTH_EXEC_ROOT") or os.path.join(ROOT, "bot", "out", "dca")
STOP_WAIT_S = 30
# Такт исполнителя: отметка позиции в статусе обновляется каждым тактом
# (владелец 10.10: «пнл как можно чаще, как на бирже»). Три запроса к
# площадке за такт — далеко от её пределов.
INTERVAL_S = 2


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), *a, flush=True)


def live_subs(db):
    return db.c.execute("SELECT * FROM subscriptions WHERE status='active' AND mode='live'").fetchall()


def running(pgrep=None):
    """{подписка: [pid]} по процессам `bot ladder --dir <корень>/<подписка>`."""
    out = {}
    try:
        txt = (pgrep or (lambda: subprocess.run(["pgrep", "-af", "bot ladder --dir"],
                                                capture_output=True, text=True).stdout))()
    except OSError:
        return out
    for ln in txt.splitlines():
        parts = ln.split()
        if len(parts) < 2 or "ladder" not in parts:
            continue
        try:
            d = parts[parts.index("--dir") + 1]
        except (ValueError, IndexError):
            continue
        out.setdefault(os.path.basename(d.rstrip("/")), []).append(int(parts[0]))
    return out


def sources_newer(bin_path=BIN):
    """Исходники бота новее бинарника — нужна сборка."""
    try:
        bt = os.path.getmtime(bin_path)
    except OSError:
        return True
    src = glob.glob(os.path.join(ROOT, "bot", "src", "*.rs")) + [os.path.join(ROOT, "bot", "Cargo.toml")]
    return any(os.path.getmtime(p) > bt for p in src if os.path.exists(p))


def build():
    env = dict(os.environ)
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
    r = subprocess.run(["cargo", "build", "--release", "--manifest-path", os.path.join(ROOT, "bot", "Cargo.toml"), "-q"],
                       capture_output=True, text=True, env=env, timeout=1800)
    if r.returncode != 0:
        log("СБОРКА НЕ ПРОШЛА — работающие процессы не трогаю:", (r.stderr or r.stdout)[-1500:])
        return False
    return True


def stale_exe(pids):
    """Процесс работает на старом бинарнике: файл заменён сборкой, у
    процесса ссылка на удалённый."""
    for p in pids:
        try:
            if os.readlink(f"/proc/{p}/exe").endswith(" (deleted)"):
                return True
        except OSError:
            continue
    return False


def stop(sub_id, pids, root=EXEC_ROOT, wait_s=STOP_WAIT_S):
    """Мягкая остановка: файл STOP, ждать выхода между тактами."""
    d = os.path.join(root, sub_id)
    with open(os.path.join(d, "STOP"), "w") as f:
        f.write(str(time.time()))
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if not any(os.path.exists(f"/proc/{p}") for p in pids):
            return True
        time.sleep(1)
    log(f"{sub_id}: процесс не вышел за {wait_s} с по STOP — оставлен работать, повтор следующим тактом")
    return False


def start(db, sub_id, root=EXEC_ROOT, bin_path=BIN, opener=None, popen=subprocess.Popen):
    """Запуск исполнителя подписки с ключом трубой."""
    import keys_local as KL                                  # noqa: E402
    d = os.path.join(root, sub_id)
    os.makedirs(d, exist_ok=True)
    try:
        os.remove(os.path.join(d, "STOP"))
    except OSError:
        pass
    try:
        key, secret = (opener or KL.open_sub_key)(db, sub_id)
    except Exception as e:                                   # noqa: BLE001
        log(f"{sub_id}: ключ не открылся — исполнитель не запущен: {e}")
        return False
    logf = open(os.path.join(d, "ladder.log"), "ab")
    p = popen([bin_path, "ladder", "--dir", d, "--base", BASE, "--keys-stdin", "--interval-sec", str(INTERVAL_S)],
              stdin=subprocess.PIPE, stdout=logf, stderr=subprocess.STDOUT,
              cwd=ROOT, start_new_session=True)
    try:
        p.stdin.write(f"BYBIT_KEY={key}\nBYBIT_SECRET={secret}\n".encode())
        p.stdin.close()
    finally:
        key = secret = None                                  # noqa: F841
    log(f"{sub_id}: исполнитель запущен, pid {p.pid}")
    return True


def first_seq(root, sub_id):
    """Исполнитель, впервые поднятый у подписки, не читает намерения,
    записанные ДО перевода в live: они сухие и старые (отказ «устарело»
    на каждое — лавина пушей). Состояние создаётся с прочитанным seq."""
    d = os.path.join(root, sub_id)
    st = os.path.join(d, "ladder_state.json")
    if os.path.exists(st):
        return None
    seq = 0
    try:
        with open(os.path.join(d, "intents.jsonl"), encoding="utf-8") as f:
            for ln in f:
                try:
                    seq = max(seq, int(json.loads(ln)["seq"]))
                except (ValueError, KeyError, TypeError):
                    pass
    except OSError:
        pass
    os.makedirs(d, exist_ok=True)
    with open(st, "w", encoding="utf-8") as f:
        json.dump({"seq_done": seq}, f)
    return seq


def ensure(db, root=EXEC_ROOT, bin_path=BIN, run=None, builder=build, starter=start, stopper=stop):
    live = {s["id"]: s for s in live_subs(db)}
    run = running() if run is None else run
    # подписки, вышедшие из live, — мягко остановить
    for sid, pids in run.items():
        if sid not in live:
            log(f"{sid}: подписка не в живом режиме — мягкая остановка")
            stopper(sid, pids, root=root)
    if not live:
        return {"live": 0, "started": 0}
    rebuilt = False
    if sources_newer(bin_path):
        log("исходники бота новее бинарника — собираю")
        rebuilt = builder()
        if not rebuilt and not os.path.exists(bin_path):
            log("бинарника нет и сборка не прошла — запускать нечего")
            return {"live": len(live), "started": 0, "error": "сборка"}
    started = 0
    for sid in live:
        pids = run.get(sid) or []
        if pids and (rebuilt or stale_exe(pids)):
            log(f"{sid}: новый бинарник — мягкий перезапуск")
            if not stopper(sid, pids, root=root):
                continue
            pids = []
        if pids:
            continue
        seq = first_seq(root, sid)
        if seq is not None:
            log(f"{sid}: первый подъём — намерения до seq {seq} (сухие) не исполняются")
        if starter(db, sid, root=root, bin_path=bin_path):
            started += 1
    return {"live": len(live), "started": started, "rebuilt": rebuilt}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.path.join(OUT, "app.sqlite"))
    ap.add_argument("--ensure", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        return 0
    db = DBM.DB(a.db)
    if a.ensure:
        r = ensure(db)
        if r.get("live") or r.get("started"):
            log(f"живых подписок {r['live']}, запущено {r['started']}" + (", пересобран бинарник" if r.get("rebuilt") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
