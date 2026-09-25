#!/usr/bin/env python3
"""Выгрузка закрытых суток записи стакана в объектное хранилище (S3).

Повод. Запись растёт на 3.7 ГБ в сутки, 24.09 том заполнился и сборщик
умер на 12 часов; копии записи (класс A) не существовало. Решение
владельца 25.09: закрытые сутки уходят в Hetzner Object Storage —
в десять раз дешевле тома и в другом датацентре.

Что уходит. Сжатые часы `<sub>/<SYM>/ГГГГ-ММ-ДД-ЧЧ.jsonl.gz` за дни не
позже `--upto` (умолчание — позавчера, как у перелива: текущий и
вчерашний день — зона сборщика и его сжатия). Несжатый `.jsonl` не
уходит никогда. Ключ в бакете — `b1/<sub>/<SYM>/<день>-<ЧЧ>.jsonl.gz`,
тот же путь, что на диске.

Проверка КАЖДОГО файла. md5 считается местно и уходит заголовком
`Content-MD5` — хранилище отвергает несовпадение; после — HEAD: размер
обязан совпасть, ETag сверяется с md5 (расхождение ETag при совпавшем
размере считается отдельным числом, а не молчит). День помечается
выгруженным (`out/ship/<день>.ok`) только когда сверены ВСЕ его файлы;
частичный ход дня лежит в `out/ship/<день>.part.json`, и повтор
продолжает с него. Манифест дня (файлы, размеры, md5) кладётся в бакет
рядом: `b1/manifest/<день>.json` — по нему запись можно проверить и
восстановить без этого сервера.

Удаление местной копии — ОТДЕЛЬНЫЙ шаг `--prune-days N`: только дни
старше N суток и только с отметкой `.ok`. Перелитый файл (ссылка на
корень, `spill_book`) удаляется вместе с целью — иначе корень не
освободился бы, а ссылка осталась бы сиротой.

Ключи — файл `~/.hetzner/s3.env` (строки `S3_ENDPOINT=…`, `S3_REGION=…`,
`S3_BUCKET=…`, `S3_KEY=…`, `S3_SECRET=…`), в git не идёт, рядом с ключами
биржи. Нет файла — отказ с названным путём, не тишина.

    run tools/record_ship.py --dry-run
    run tools/record_ship.py --max-gb 20
    run tools/record_ship.py --prune-days 21
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "research", "b1_book", "out")
SUBS = ("book", "trades", "raw", "liq", "metrics")
ENV = os.path.expanduser("~/.hetzner/s3.env")
PREFIX = "b1"
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{2})\.jsonl\.gz$")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


# ------------------------------------------------------------------ ключи
def load_env(path=ENV):
    """Ключи хранилища; отсутствие — отказ словами, с путём."""
    if not os.path.exists(path):
        raise SystemExit(f"ключей хранилища нет: {path} (строки S3_ENDPOINT, "
                         "S3_REGION, S3_BUCKET, S3_KEY, S3_SECRET)")
    env = {}
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    miss = [k for k in ("S3_ENDPOINT", "S3_BUCKET", "S3_KEY", "S3_SECRET")
            if not env.get(k)]
    if miss:
        raise SystemExit(f"в {path} нет полей: {miss}")
    env.setdefault("S3_REGION", env["S3_ENDPOINT"].split("//")[-1].split(".")[0])
    return env


def client(env):
    """Клиент S3 под Hetzner: virtual-hosted, подпись v4, без новых
    контрольных сумм boto3 (хранилище их не принимает)."""
    import boto3
    from botocore.config import Config
    cfg = Config(signature_version="s3v4",
                 s3={"addressing_style": "virtual"},
                 request_checksum_calculation="when_required",
                 response_checksum_validation="when_required",
                 retries={"max_attempts": 5, "mode": "standard"})
    return boto3.client("s3", endpoint_url=env["S3_ENDPOINT"],
                        region_name=env["S3_REGION"],
                        aws_access_key_id=env["S3_KEY"],
                        aws_secret_access_key=env["S3_SECRET"], config=cfg)


# ------------------------------------------------------------------ файлы
def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def df_line(path):
    try:
        return f"{path}: свободно {free_bytes(path) / 2**30:.1f} ГБ"
    except OSError as e:
        return f"{path}: df не читается ({e})"


def day_files(root, day, subs=SUBS):
    """Файлы одних суток: (ключ, путь, размер) по всем подкаталогам."""
    out = []
    for sub in subs:
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for sym in sorted(os.listdir(base)):
            d = os.path.join(base, sym)
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                m = NAME.match(name)
                if not m or m.group(1) != day:
                    continue
                p = os.path.join(d, name)
                try:
                    sz = os.path.getsize(p)          # по ссылке — цель
                except OSError:
                    continue
                out.append((f"{PREFIX}/{sub}/{sym}/{name}", p, sz))
    return out


def closed_days(root, upto, subs=SUBS):
    """Дни записи не позже `upto` (ГГГГ-ММ-ДД), у которых есть сжатые часы."""
    days = set()
    for sub in subs:
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for sym in os.listdir(base):
            d = os.path.join(base, sym)
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                m = NAME.match(name)
                if m and m.group(1) <= upto:
                    days.add(m.group(1))
    return sorted(days)


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ship_dir(root):
    d = os.path.join(root, "ship")
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- выгрузка
def put_verified(s3, bucket, key, path):
    """Положить файл и сверить: md5 заголовком, HEAD по размеру и ETag.

    Возвращает (размер, md5, etag_совпал).
    """
    size = os.path.getsize(path)
    hexd = md5_of(path)
    b64 = base64.b64encode(bytes.fromhex(hexd)).decode("ascii")
    with open(path, "rb") as f:
        s3.put_object(Bucket=bucket, Key=key, Body=f, ContentMD5=b64,
                      ContentLength=size, Metadata={"md5": hexd})
    h = s3.head_object(Bucket=bucket, Key=key)
    got = int(h.get("ContentLength", -1))
    if got != size:
        raise RuntimeError(f"{key}: в хранилище {got} байт, местно {size}")
    etag = str(h.get("ETag", "")).strip('"')
    return size, hexd, (etag == hexd)


def ship_day(s3, bucket, root, day, dry_run=False, budget=None, log=log,
             progress_s=30.0):
    """Выгрузить один день. Возвращает сводку дня; `budget` — остаток байт."""
    files = day_files(root, day)
    sd = ship_dir(root)
    ok_path = os.path.join(sd, f"{day}.ok")
    part_path = os.path.join(sd, f"{day}.part.json")
    done = {}
    if os.path.exists(part_path):
        with open(part_path, encoding="utf-8") as f:
            done = json.load(f).get("files") or {}
    todo = [(k, p, sz) for k, p, sz in files if k not in done]
    st = {"day": day, "files": len(files), "bytes": sum(sz for *_, sz in files),
          "already": len(done), "sent": 0, "sent_bytes": 0,
          "etag_mismatch": 0, "errors": 0, "complete": False,
          "stopped": None}
    if dry_run:
        st["stopped"] = "сухой прогон"
        return st
    t0, last = time.time(), time.time()
    for key, path, sz in todo:
        if budget is not None and budget[0] - sz < 0:
            st["stopped"] = "предел за прогон"
            break
        try:
            size, hexd, etag_ok = put_verified(s3, bucket, key, path)
        except Exception as e:                                # noqa: BLE001
            st["errors"] += 1
            log(f"  ОТКАЗ {key}: {str(e)[:200]}")
            if st["errors"] >= 20:
                st["stopped"] = "20 отказов подряд — прогон остановлен"
                break
            continue
        done[key] = {"size": size, "md5": hexd, "etag_ok": etag_ok}
        if not etag_ok:
            st["etag_mismatch"] += 1
        st["sent"] += 1
        st["sent_bytes"] += size
        if budget is not None:
            budget[0] -= size
        if time.time() - last > progress_s:
            last = time.time()
            _save_part(part_path, day, done)
            el = time.time() - t0
            log(f"  {day}: {st['sent']}/{len(todo)} файлов, "
                f"{st['sent_bytes'] / 2**30:.2f} ГБ, {el:.0f} с")
    _save_part(part_path, day, done)
    # день закрыт, только когда сверен КАЖДЫЙ файл дня
    if files and all(k in done for k, *_ in files) and not st["errors"]:
        manifest = {"day": day, "files": {k: done[k] for k, *_ in files},
                    "bytes": st["bytes"], "n": len(files),
                    "shipped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        body = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        s3.put_object(Bucket=bucket, Key=f"{PREFIX}/manifest/{day}.json",
                      Body=body, ContentLength=len(body),
                      ContentMD5=base64.b64encode(hashlib.md5(body).digest()).decode())
        with open(ok_path, "w", encoding="utf-8") as f:
            json.dump({"day": day, "n": len(files), "bytes": st["bytes"],
                       "etag_mismatch": sum(1 for v in done.values()
                                            if not v.get("etag_ok")),
                       "at": manifest["shipped_at"]}, f, ensure_ascii=False)
        st["complete"] = True
    return st


def _save_part(path, day, done):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"day": day, "files": done}, f, ensure_ascii=False)
    os.replace(tmp, path)


def shipped_days(root):
    sd = ship_dir(root)
    return sorted(n[:-3] for n in os.listdir(sd) if n.endswith(".ok"))


# ---------------------------------------------------------------- удаление
def prune(root, keep_days, today=None, dry_run=False, log=log):
    """Снять местные копии дней старше `keep_days` — только выгруженных.

    Ссылка перелива удаляется ВМЕСТЕ с целью на корне.
    """
    today = today or datetime.now(timezone.utc).date()
    edge = (today - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    out = {"edge": edge, "days": [], "files": 0, "bytes": 0, "targets": 0,
           "refused": []}
    for day in closed_days(root, edge):
        if day not in shipped_days(root):
            out["refused"].append(day)
            continue
        n = b = t = 0
        for _key, path, sz in day_files(root, day):
            n += 1
            b += sz
            if dry_run:
                continue
            if os.path.islink(path):
                target = os.path.realpath(path)
                os.remove(path)
                try:
                    os.remove(target)
                    t += 1
                except OSError:
                    pass
            else:
                os.remove(path)
        out["days"].append(day)
        out["files"] += n
        out["bytes"] += b
        out["targets"] += t
        log(f"  {day}: {'снял бы' if dry_run else 'снято'} {n} файлов, "
            f"{b / 2**30:.2f} ГБ, из них перелитых {t}")
    if out["refused"]:
        log(f"  НЕ сняты (нет отметки выгрузки): {out['refused']}")
    return out


# --------------------------------------------------------------------- main
def run(root=SRC, upto=None, max_gb=20.0, dry_run=False, prune_days=None,
        env_path=ENV, s3=None, bucket=None, log=log, today=None):
    t0 = time.time()
    today = today or datetime.now(timezone.utc).date()
    upto = upto or (today - timedelta(days=2)).strftime("%Y-%m-%d")
    log(f"до: {df_line(root)}; {df_line(os.path.dirname(ROOT))}")
    if s3 is None:
        env = load_env(env_path)
        s3, bucket = client(env), env["S3_BUCKET"]
    days = [d for d in closed_days(root, upto) if d not in shipped_days(root)]
    log(f"дней к выгрузке (не позже {upto}, без отметки): {len(days)}"
        + (f" — {days[0]} … {days[-1]}" if days else "")
        + f"; предел за прогон {max_gb:g} ГБ" + ("; СУХОЙ прогон" if dry_run else ""))
    budget = [max_gb * 2**30]
    summary = []
    for day in days:
        st = ship_day(s3, bucket, root, day, dry_run=dry_run, budget=budget, log=log)
        summary.append(st)
        log(f"{day}: файлов {st['files']}, {st['bytes'] / 2**30:.2f} ГБ, "
            f"отправлено {st['sent']} (было {st['already']}), отказов {st['errors']}, "
            f"ETag не совпал у {st['etag_mismatch']}, "
            f"{'ЗАКРЫТ' if st['complete'] else 'не закрыт'}"
            + (f" — {st['stopped']}" if st["stopped"] else ""))
        if st["stopped"] and st["stopped"] != "сухой прогон":
            break
    pr = None
    if prune_days is not None:
        log(f"снятие местных копий старше {prune_days} сут:")
        pr = prune(root, prune_days, today=today, dry_run=dry_run, log=log)
    log(f"после: {df_line(root)}; {df_line(os.path.dirname(ROOT))}; "
        f"{time.time() - t0:.0f} с")
    sent = sum(s["sent_bytes"] for s in summary)
    log(f"итого отправлено {sent / 2**30:.2f} ГБ, дней закрыто "
        f"{sum(1 for s in summary if s['complete'])} из {len(summary)}")
    return {"days": summary, "prune": pr, "sent_bytes": sent}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", default=None, help="день ГГГГ-ММ-ДД включительно")
    ap.add_argument("--max-gb", type=float, default=20.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune-days", type=int, default=None)
    ap.add_argument("--root", default=SRC)
    a = ap.parse_args(argv)
    run(root=a.root, upto=a.upto, max_gb=a.max_gb, dry_run=a.dry_run,
        prune_days=a.prune_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
