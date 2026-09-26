#!/usr/bin/env python3
"""Проверки чтения часа из хранилища: промах на диске → архив дня скачан,
сверен по md5 и распакован в кэш; соседний час — из кэша; «нет в
хранилище» — раз; несошедшийся md5 не берётся; предел кэша вытесняет
старое; чужой каталог — без запроса; без ключей — только диск; источник
реплея включает хранилище."""
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools"))
import remote as RM                                           # noqa: E402
import store                                                  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  ПАДЕНИЕ ") + name
          + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


class NoKey(Exception):
    def __init__(self):
        super().__init__("nokey")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self, objs, lie=False):
        self.objs, self.lie, self.gets = objs, lie, 0

    def get_object(self, Bucket, Key):
        self.gets += 1
        if Key not in self.objs:
            raise NoKey()
        data = self.objs[Key]
        md5 = hashlib.md5(data).hexdigest()
        return {"Body": io.BytesIO(data), "ETag": f'"{"0" * 32 if self.lie else md5}"',
                "Metadata": {}}


def gz(rows):
    b = io.BytesIO()
    with gzip.open(b, "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return b.getvalue()


def tar_of(members):
    """Архив дня, как его пишет выгрузка: {имя члена: байты}."""
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for name, data in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return b.getvalue()


def main():
    root = tempfile.mkdtemp(prefix="remote-")
    try:
        objs = {"b1/book/AAAUSDT/2026-09-01.tar": tar_of({
                    "2026-09-01-12.jsonl.gz": gz([{"h": 12}, {"h": 12}]),
                    "2026-09-01-15.jsonl.gz": gz([{"h": 15}])}),
                "b1/trades/AAAUSDT/2026-09-01.tar": tar_of({
                    "2026-09-01-12.jsonl.gz": gz([{"t": 1}])})}
        s3 = FakeS3(objs)
        rm = RM.Remote(s3, "b", root=root, cache_gb=0.001, log=lambda m: None)
        d = os.path.join(root, "book", "AAAUSDT")
        os.makedirs(d, exist_ok=True)
        # без хранилища — промах есть промах
        store.use_remote(None)
        check("без хранилища — пусто", store.read_hour(d, "2026-09-01-12") == [])
        store.use_remote(rm)
        rows = store.read_hour(d, "2026-09-01-12")
        check("промах на диске — час из архива дня", rows == [{"h": 12}, {"h": 12}], rows)
        cached = os.path.join(root, "cache", "book", "AAAUSDT", "2026-09-01-12.jsonl.gz")
        check("архив распакован в кэш целиком", os.path.exists(cached)
              and os.path.exists(cached.replace("-12.", "-15.")))
        n = s3.gets
        check("соседний час дня — из кэша, без запроса",
              store.read_hour(d, "2026-09-01-15") == [{"h": 15}] and s3.gets == n
              and rm.stats()["hits"] == 1)
        check("часа нет в архиве — пусто без нового запроса",
              store.read_hour(d, "2026-09-01-13") == [] and s3.gets == n
              and store.read_hour(d, "2026-09-01-13") == [] and s3.gets == n)
        check("дня нет в хранилище — пусто и запомнено",
              store.read_hour(d, "2026-09-02-13") == [] and s3.gets == n + 1
              and store.read_hour(d, "2026-09-02-14") == [] and s3.gets == n + 1)
        # местный файл важнее хранилища
        with gzip.open(os.path.join(d, "2026-09-01-14.jsonl.gz"), "wt") as f:
            f.write(json.dumps({"local": 1}) + "\n")
        n = s3.gets
        check("местный файл читается без запроса",
              store.read_hour(d, "2026-09-01-14") == [{"local": 1}] and s3.gets == n)
        # чужой каталог — не ключ записи, запроса нет
        check("каталог вне записи — без запроса",
              rm.key(os.path.join(root, "other", "X"), "2026-09-01-12") is None
              and rm.key(os.path.join(root, "cache", "X"), "2026-09-01-12") is None)
        # md5 не сошёлся — не берётся, считается
        liar = FakeS3(objs, lie=True)
        rm2 = RM.Remote(liar, "b", root=root, log=lambda m: None)
        store.use_remote(rm2)
        dt = os.path.join(root, "trades", "AAAUSDT")
        os.makedirs(dt, exist_ok=True)
        got = store.read_hour(dt, "2026-09-01-12")
        check("несошедшийся md5 не берётся", got == [] and rm2.stats()["bad_md5"] == 1
              and not os.path.exists(os.path.join(root, "cache", "trades", "AAAUSDT",
                                                  "2026-09-01-12.jsonl.gz")), got)
        # предел кэша: самое старое по обращению снимается
        one = gz([{"x": "y" * 200}] * 200)
        big = {f"b1/book/BBBUSDT/2026-09-0{dd}.tar": tar_of({f"2026-09-0{dd}-00.jsonl.gz": one})
               for dd in range(1, 7)}
        s3b = FakeS3(big)
        rm3 = RM.Remote(s3b, "b", root=root, cache_gb=len(one) * 3.5 / 2**30,
                        log=lambda m: None)
        store.use_remote(rm3)
        db = os.path.join(root, "book", "BBBUSDT")
        os.makedirs(db, exist_ok=True)
        for dd in range(1, 7):
            store.read_hour(db, f"2026-09-0{dd}-00")
            time.sleep(0.01)
        left = sorted(os.listdir(os.path.join(root, "cache", "book", "BBBUSDT")))
        check("предел кэша вытесняет старое", 0 < len(left) < 6 and "2026-09-06-00.jsonl.gz" in left
              and "2026-09-01-00.jsonl.gz" not in left, left)
        # без ключей — None и слова
        said = []
        check("без ключей — только диск", RM.from_env(env_path=os.path.join(root, "no.env"),
                                                      root=root, log=said.append) is None
              and any("хранилища нет" in x for x in said), said)
        # источник реплея включает хранилище сам
        store.use_remote(None)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "research", "dca_paper"))
        import tail as TL
        TL.TailBars(root=root, log=lambda m: None, remote=rm)
        check("источник реплея включает хранилище", store.REMOTE is rm)
        store.use_remote(None)
    finally:
        store.use_remote(None)
        shutil.rmtree(root, ignore_errors=True)
    if FAILED:
        print(f"\nпадений: {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
