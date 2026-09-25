#!/usr/bin/env python3
"""Чтение часа записи из объектного хранилища, когда на диске его нет.

Повод. Закрытые сутки уходят в Hetzner Object Storage (`tools/record_ship.py`,
решение владельца 25.09), местная копия старше N суток снимается. Замеры
по старым часам (реплей, скрины, срезы) обязаны работать как прежде —
читатель часа (`store.read_hour`) при промахе на диске берёт час из
хранилища в местный кэш.

Правила:
- включается ЯВНО (`store.use_remote(...)`): сборщик и страница в
  хранилище не ходят никогда — задержка страницы и трафик на каждом
  запросе;
- скачанный файл сверяется по md5 (ETag хранилища или `md5` из
  метаданных, которые пишет выгрузка) и только потом кладётся в кэш
  `out/cache/<sub>/<SYM>/<час>.jsonl.gz`; несошедшийся — не кладётся и
  считается;
- предел кэша — гигабайты; сверх него снимаются самые старые по
  обращению;
- «в хранилище нет» запоминается на процесс (отрицательный кэш): повтор
  запроса того же часа сети не стоит; промахи, скачивания, отказы —
  числом в `stats()`;
- ключей нет — хранилища нет: читатель говорит это ОДИН раз словами и
  живёт как прежде (`from_env` отдаёт None).
"""
import hashlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))

ROOT_B1 = os.path.join(HERE, "out")
SUBS = ("book", "trades", "raw", "liq", "metrics")
PREFIX = "b1"
CACHE_GB = 2.0


class Remote:
    def __init__(self, s3, bucket, root=ROOT_B1, cache_gb=CACHE_GB,
                 prefix=PREFIX, log=None):
        self.s3, self.bucket, self.prefix = s3, bucket, prefix
        self.root = os.path.abspath(root)
        self.cache = os.path.join(self.root, "cache")
        self.cap = float(cache_gb) * 2**30
        self.log = log or (lambda m: None)
        self.missing = set()
        self.fetched = self.misses = self.bad = self.errors = self.hits = 0
        self.size = self._cache_size()

    # --- дорога до ключа --------------------------------------------------
    def key(self, dirpath, hour):
        """Ключ в бакете по каталогу часа; None — каталог не из записи."""
        rel = os.path.relpath(os.path.abspath(dirpath), self.root)
        parts = rel.split(os.sep)
        if len(parts) != 2 or parts[0] not in SUBS or parts[0] == "cache":
            return None
        return f"{self.prefix}/{parts[0]}/{parts[1]}/{hour}.jsonl.gz"

    def get(self, dirpath, hour):
        """Местный путь скачанного часа или None (нет / не сошёлся / отказ)."""
        key = self.key(dirpath, hour)
        if key is None or key in self.missing:
            return None
        local = os.path.join(self.cache, *key.split("/")[1:])
        if os.path.exists(local):
            self.hits += 1
            try:
                os.utime(local, None)              # обращение — для вытеснения
            except OSError:
                pass
            return local
        try:
            r = self.s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:                                  # noqa: BLE001
            code = str((getattr(e, "response", None) or {})
                       .get("Error", {}).get("Code", ""))
            if code in ("NoSuchKey", "404", "NotFound"):
                self.missing.add(key)
                self.misses += 1
            else:
                self.errors += 1
                if self.errors <= 3:
                    self.log(f"хранилище: отказ на {key}: {str(e)[:160]}")
            return None
        os.makedirs(os.path.dirname(local), exist_ok=True)
        tmp = local + ".tmp"
        h = hashlib.md5()
        n = 0
        with open(tmp, "wb") as f:
            body = r["Body"]
            for chunk in iter(lambda: body.read(1 << 20), b""):
                h.update(chunk)
                f.write(chunk)
                n += len(chunk)
        want = str((r.get("Metadata") or {}).get("md5") or "").lower() \
            or str(r.get("ETag", "")).strip('"').lower()
        if want and want != h.hexdigest():
            os.remove(tmp)
            self.bad += 1
            self.log(f"хранилище: {key} не сошёлся по md5 — не взят")
            return None
        os.replace(tmp, local)
        self.fetched += 1
        self.size += n
        if self.size > self.cap:
            self._evict()
        return local

    # --- кэш ---------------------------------------------------------------
    def _walk(self):
        out = []
        for d, _dirs, files in os.walk(self.cache):
            for fn in files:
                p = os.path.join(d, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append((st.st_mtime, st.st_size, p))
        return out

    def _cache_size(self):
        return sum(sz for _m, sz, _p in self._walk())

    def _evict(self):
        """Снять самые старые по обращению до 90 % предела."""
        files = sorted(self._walk())
        total = sum(sz for _m, sz, _p in files)
        goal = 0.9 * self.cap
        removed = 0
        for _m, sz, p in files:
            if total <= goal:
                break
            try:
                os.remove(p)
                total -= sz
                removed += 1
            except OSError:
                pass
        self.size = total
        if removed:
            self.log(f"кэш хранилища: снято {removed} файлов, осталось "
                     f"{total / 2**30:.2f} ГБ при пределе {self.cap / 2**30:g}")

    def stats(self):
        return {"fetched": self.fetched, "hits": self.hits, "misses": self.misses,
                "bad_md5": self.bad, "errors": self.errors,
                "cache_gb": round(self.size / 2**30, 3)}


def from_env(env_path=None, root=ROOT_B1, cache_gb=CACHE_GB, log=None):
    """Хранилище по ключам сервера; None и одна строка — если ключей нет."""
    import record_ship as RS
    path = env_path or RS.ENV
    log = log or (lambda m: None)
    if not os.path.exists(path):
        log(f"хранилища нет: ключей {path} не существует — читаю только диск")
        return None
    env = RS.load_env(path)
    return Remote(RS.client(env), env["S3_BUCKET"], root=root,
                  cache_gb=cache_gb, prefix=PREFIX, log=log)
