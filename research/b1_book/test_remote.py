#!/usr/bin/env python3
"""Проверки чтения часа из хранилища: промах на диске → архив дня скачан,
сверен по md5 и распакован в кэш; соседний час — из кэша; «нет в
хранилище» — раз; несошедшийся md5 не берётся; предел кэша вытесняет
старое; чужой каталог — без запроса; без ключей — только диск; источник
реплея включает хранилище; обрыв потока повторяется с отступом, вечный
обрыв падает вслух без битого файла в кэше; архивы дней качаются
параллельно и ставятся в кэш по одному; предвыборка пропускает часы,
которые есть на диске."""
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


class BrokenBody:
    """Поток, который рвётся на первом чтении — как `IncompleteRead`."""

    def read(self, n=-1):
        raise OSError("Connection broken: IncompleteRead")


class FlakyS3(FakeS3):
    """Первые `break_first` запросов отдают рвущийся поток, дальше — целый."""

    def __init__(self, objs, break_first=2):
        super().__init__(objs)
        self.break_first = break_first

    def get_object(self, Bucket, Key):
        r = super().get_object(Bucket, Key)
        if self.gets <= self.break_first:
            r["Body"] = BrokenBody()
        return r


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
        # --- сеть икает: повтор с отступом, вечный обрыв — вслух и без битого файла ---
        was_backoff = RM.BACKOFF_S
        RM.BACKOFF_S = (0.0, 0.0, 0.0)
        try:
            flaky = FlakyS3(dict(objs), break_first=2)
            rm4 = RM.Remote(flaky, "b", root=root, log=lambda m: None)
            store.use_remote(rm4)
            dc = os.path.join(root, "trades", "CCCUSDT")
            os.makedirs(dc, exist_ok=True)
            objs_c = {"b1/trades/CCCUSDT/2026-09-03.tar": tar_of({"2026-09-03-01.jsonl.gz": gz([{"c": 1}])})}
            flaky.objs.update(objs_c)
            rows = store.read_hour(dc, "2026-09-03-01")
            st4 = rm4.stats()
            check("обрыв потока дважды — третья попытка читает час",
                  rows == [{"c": 1}] and flaky.gets == 3 and st4["retries"] == 2 and st4["errors"] == 2, (rows, flaky.gets, st4))
            dead = FlakyS3(dict(objs_c), break_first=10 ** 6)
            rm5 = RM.Remote(dead, "b", root=root, log=lambda m: None)
            store.use_remote(rm5)
            dd_ = os.path.join(root, "trades", "DDDUSDT")
            os.makedirs(dd_, exist_ok=True)
            dead.objs = {"b1/trades/DDDUSDT/2026-09-03.tar": tar_of({"2026-09-03-01.jsonl.gz": gz([{"d": 1}])})}
            raised = None
            try:
                store.read_hour(dd_, "2026-09-03-01")
            except RM.RemoteFetchError as e:
                raised = str(e)
            cdir = os.path.join(root, "cache", "trades", "DDDUSDT")
            leftovers = sorted(os.listdir(cdir)) if os.path.exists(cdir) else []
            check("вечный обрыв — отказ вслух после всех попыток, кэш без битого файла",
                  raised is not None and "не скачан за 4 попытки" in raised and dead.gets == RM.ATTEMPTS
                  and leftovers == [], (raised, dead.gets, leftovers))
            # --- предвыборка: архивы дней параллельно, установка по одному, часы с диска не тянутся ---
            days = {f"b1/trades/EEEUSDT/2026-09-1{dd}.tar": tar_of({f"2026-09-1{dd}-00.jsonl.gz": gz([{"e": dd}]),
                                                                    f"2026-09-1{dd}-01.jsonl.gz": gz([{"e": dd, "h": 1}])})
                    for dd in range(0, 5)}
            s3e = FakeS3(days)
            rm6 = RM.Remote(s3e, "b", root=root, log=lambda m: None)
            store.use_remote(rm6)
            de = os.path.join(root, "trades", "EEEUSDT")
            os.makedirs(de, exist_ok=True)
            for hh in ("00", "01"):                                       # день 14 целиком есть на диске
                with gzip.open(os.path.join(de, f"2026-09-14-{hh}.jsonl.gz"), "wt") as f:
                    f.write(json.dumps({"local": 14}) + "\n")
            hours = [f"2026-09-1{dd}-{hh:02d}" for dd in range(0, 6) for hh in (0, 1)]   # день 15 в хранилище отсутствует
            got = store.prefetch(de, hours)
            st6 = rm6.stats()
            check("предвыборка качает дни разом и ставит по одному; местный день не тянется; нет дня — запомнено",
                  got == 4 and st6["prefetched"] == 4 and s3e.gets == 5 and st6["misses"] == 1
                  and "b1/trades/EEEUSDT/2026-09-15.tar" in rm6.missing
                  and "b1/trades/EEEUSDT/2026-09-14.tar" not in rm6.missing, (got, st6, s3e.gets))
            n6 = s3e.gets
            rows = [store.read_hour(de, f"2026-09-1{dd}-01") for dd in range(0, 4)]
            check("часы после предвыборки — из кэша, без запросов",
                  rows == [[{"e": dd, "h": 1}] for dd in range(0, 4)] and s3e.gets == n6
                  and store.read_hour(de, "2026-09-14-00") == [{"local": 14}] and s3e.gets == n6, (rows, s3e.gets))
            check("повторная предвыборка — ноль запросов", store.prefetch(de, hours) == 0 and s3e.gets == n6)
            # предвыборка, у которой один архив рвётся вечно, — вслух
            dead2 = FlakyS3({"b1/trades/FFFUSDT/2026-09-20.tar": tar_of({"2026-09-20-00.jsonl.gz": gz([{"f": 1}])})},
                            break_first=10 ** 6)
            rm7 = RM.Remote(dead2, "b", root=root, log=lambda m: None)
            store.use_remote(rm7)
            df = os.path.join(root, "trades", "FFFUSDT")
            os.makedirs(df, exist_ok=True)
            raised = None
            try:
                store.prefetch(df, ["2026-09-20-00"])
            except RM.RemoteFetchError as e:
                raised = str(e)
            check("предвыборка с вечным обрывом — отказ вслух", raised is not None and "FFFUSDT" in raised, raised)
            # источник реплея зовёт предвыборку на оба каталога окна
            import tail as TL
            called = []
            was_pf = store.prefetch
            store.prefetch = lambda d, hs: called.append((os.path.basename(os.path.dirname(d)), os.path.basename(d), len(hs))) or 0
            try:
                tb = TL.TailBars(root=root, log=lambda m: None, remote=rm6)
                tb.bars("GGGUSDT", 1_757_000_000.0, 1_757_000_000.0 + 5 * 3600)
            finally:
                store.prefetch = was_pf
            check("TailBars зовёт предвыборку ленты и книги на часы окна",
                  called == [("trades", "GGGUSDT", 6), ("book", "GGGUSDT", 6)], called)
            check("статистика источника несёт числа хранилища",
                  isinstance(tb.stats().get("remote"), dict) and "retries" in tb.stats()["remote"], tb.stats())
        finally:
            RM.BACKOFF_S = was_backoff
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
