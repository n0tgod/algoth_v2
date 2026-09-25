#!/usr/bin/env python3
"""Проверки выгрузки записи: md5 и HEAD на каждый файл, день закрывается
только целиком, несжатое и свежее не уходит, снятие только выгруженного,
ссылка перелива снимается с целью, без ключей — отказ с путём."""
import base64
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import record_ship as RS                                     # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name
          + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


class FakeS3:
    """Подставное хранилище: проверяет Content-MD5, как настоящее."""

    def __init__(self, lie_size=False):
        self.objs = {}
        self.lie_size = lie_size
        self.puts = 0

    def put_object(self, Bucket, Key, Body, ContentMD5=None, ContentLength=None,
                   Metadata=None):
        data = Body.read() if hasattr(Body, "read") else Body
        if ContentMD5 is not None:
            want = base64.b64encode(hashlib.md5(data).digest()).decode()
            if want != ContentMD5:
                raise RuntimeError("BadDigest")
        self.objs[Key] = data
        self.puts += 1

    def head_object(self, Bucket, Key):
        data = self.objs[Key]
        n = len(data) + (1 if self.lie_size else 0)
        return {"ContentLength": n, "ETag": f'"{hashlib.md5(data).hexdigest()}"'}


def _root(days, syms=("AAAUSDT", "BBBUSDT"), spill=None):
    root = tempfile.mkdtemp(prefix="ship-")
    for day in days:
        for sub in ("book", "trades"):
            for sym in syms:
                d = os.path.join(root, sub, sym)
                os.makedirs(d, exist_ok=True)
                for hh in (0, 1):
                    p = os.path.join(d, f"{day}-{hh:02d}.jsonl.gz")
                    with gzip.open(p, "wt") as f:
                        f.write(json.dumps({"day": day, "sub": sub, "sym": sym,
                                            "h": hh}) + "\n")
                    if spill and day in spill:
                        t = os.path.join(spill_dir(spill), sub, sym, os.path.basename(p))
                        os.makedirs(os.path.dirname(t), exist_ok=True)
                        os.replace(p, t)
                        os.symlink(t, p)
                # несжатый час — зона сборщика, не уходит
                with open(os.path.join(d, f"{day}-02.jsonl"), "w") as f:
                    f.write("{}\n")
    return root


_SPILL = {}


def spill_dir(spill):
    return _SPILL.setdefault("d", tempfile.mkdtemp(prefix="ship-spill-"))


def main():
    today = date(2026, 9, 25)
    days = ["2026-09-20", "2026-09-21", "2026-09-23", "2026-09-24"]
    root = _root(days, spill={"2026-09-20"})
    s3 = FakeS3()
    said = []
    try:
        # без ключей — отказ с путём
        try:
            RS.run(root=root, env_path=os.path.join(root, "nope.env"), log=said.append,
                   today=today)
            check("без ключей — отказ", False)
        except SystemExit as e:
            check("без ключей — отказ с путём", "nope.env" in str(e), str(e))
        # выгрузка: позавчера и старше, несжатое не уходит
        res = RS.run(root=root, s3=s3, bucket="b", log=said.append, today=today)
        shipped = sorted({k.split("/")[3][:10] for k in s3.objs if "/manifest/" not in k})
        check("уходят дни не позже позавчера", shipped == ["2026-09-20", "2026-09-21", "2026-09-23"], shipped)
        check("несжатый час не уходит", not any(k.endswith(".jsonl") for k in s3.objs))
        check("день закрыт целиком, манифест в бакете",
              all(s["complete"] for s in res["days"])
              and "b1/manifest/2026-09-21.json" in s3.objs, res["days"])
        man = json.loads(s3.objs["b1/manifest/2026-09-21.json"])
        check("манифест несёт md5 каждого файла",
              man["n"] == 8 and all(len(v["md5"]) == 32 for v in man["files"].values()), man)
        check("перелитый файл ушёл по ссылке", "b1/book/AAAUSDT/2026-09-20-00.jsonl.gz" in s3.objs)
        check("отметки дней", RS.shipped_days(root) == ["2026-09-20", "2026-09-21", "2026-09-23"])
        # повтор ничего не шлёт
        n = s3.puts
        RS.run(root=root, s3=s3, bucket="b", log=said.append, today=today)
        check("повтор не шлёт ничего", s3.puts == n, (n, s3.puts))
        # контроль: хранилище врёт размером — день НЕ закрывается, отметки нет
        root2 = _root(["2026-09-10"])
        liar = FakeS3(lie_size=True)
        r2 = RS.run(root=root2, s3=liar, bucket="b", log=said.append, today=today)
        check("расхождение размера — день не закрыт", not r2["days"][0]["complete"]
              and r2["days"][0]["errors"] > 0 and RS.shipped_days(root2) == [], r2["days"])
        pr = RS.prune(root2, keep_days=1, today=today, log=said.append)
        check("незакрытый день не снимается", pr["refused"] == ["2026-09-10"]
              and os.path.exists(os.path.join(root2, "book", "AAAUSDT", "2026-09-10-00.jsonl.gz")), pr)
        # снятие: только старше N суток и только выгруженных; ссылка — с целью
        pr = RS.prune(root, keep_days=3, today=today, log=said.append)
        check("сняты дни старше 3 суток", pr["days"] == ["2026-09-20", "2026-09-21"], pr)
        link = os.path.join(root, "book", "AAAUSDT", "2026-09-20-00.jsonl.gz")
        target = os.path.join(spill_dir(None), "book", "AAAUSDT", "2026-09-20-00.jsonl.gz")
        check("ссылка перелива снята вместе с целью",
              not os.path.lexists(link) and not os.path.exists(target) and pr["targets"] == 8, pr)
        check("свежий день на месте",
              os.path.exists(os.path.join(root, "book", "AAAUSDT", "2026-09-23-00.jsonl.gz")))
        check("несжатый час не тронут",
              os.path.exists(os.path.join(root, "book", "AAAUSDT", "2026-09-20-02.jsonl")))
        # сухой прогон ничего не шлёт и не снимает
        root3 = _root(["2026-09-11"])
        dry = FakeS3()
        RS.run(root=root3, s3=dry, bucket="b", dry_run=True, prune_days=0, log=said.append, today=today)
        check("сухой прогон: ничего не отправлено и не снято", dry.puts == 0
              and os.path.exists(os.path.join(root3, "book", "AAAUSDT", "2026-09-11-00.jsonl.gz")))
    finally:
        for d in (root, ):
            shutil.rmtree(d, ignore_errors=True)
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
