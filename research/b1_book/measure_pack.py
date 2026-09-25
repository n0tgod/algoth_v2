#!/usr/bin/env python3
"""Замер: сколько весит запись стакана в разных форматах — на ЖИВЫХ часах.

Зачем. Запись растёт на 3.7 ГБ в сутки уже в gzip (128 ГБ за 35 дней),
том заполнился 24.09, сборщик умер на 12 часов. Решение владельца 25.09:
закрытые сутки уходят в Hetzner Object Storage. Прежде чем выбирать
формат для хранилища и для диска, он МЕРЯЕТСЯ, а не гадается:
синтетический час той же формы дал zstd-19 0.57 от gzip, дельты 0.73,
скаляры без лесенки 0.16 — но синтетика сжимается втрое хуже живой
записи (средний файл книги на диске ≈ 100 КБ против 357 у синтетики),
и живые числа могут отличаться в любую сторону.

Что меряется на N именах за одни сутки (умолчание — трое суток назад:
сутки закрыты и сжаты):
  книга — gzip как на диске; gzip-9 заново (контроль: ± несколько %);
  xz-6; zstd-19; zstd-19 со словарём, обученным на ДРУГОМ часе тех же
  имён; дельты уровней между секундами (ключевой кадр раз в минуту) +
  zstd-19; скаляры без лесенки + zstd-19; 10 уровней + zstd-19;
  доля байт лесенки в строке;
  лента — gzip как на диске; zstd-19.
Имена — по размеру файла книги в час 12: треть самых тяжёлых, треть из
середины, треть самых лёгких (имён 725, а байты у десятка — средний по
имени размер иначе врал бы). Часы — шесть по суткам (0, 4, …, 20),
иначе zstd-19 на всех 24 стоил бы часы счёта.

Дельты БЕЗ ПОТЕРЬ: восстановление сверяется со снимками на каждом часе,
и расхождение роняет прогон — иначе «дельты меньше» ничего не значило
бы. zstd — модуль `zstandard`; его нет — вариант помечен «не измерено»
(не нулём), прогон идёт дальше.

Итог — таблица долей от gzip на диске и пересчёт на ВСЕ имена суток:
размер суток на диске считается по всем файлам этого дня, доля —
по выборке; так «ГБ/сут» у варианта есть оценка, и это сказано.

    run research/b1_book/measure_pack.py --day 2026-09-22 --names 30
"""
import argparse
import gzip
import json
import lzma
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from store import read_jsonl                                  # noqa: E402

try:
    import zstandard as zstd
except ImportError:                                           # noqa: BLE001
    zstd = None

ROOT_B1 = os.path.join(HERE, "out")
OUT_JSON = os.path.join(HERE, "out", "measure-pack.json")
OUT_MD = os.path.join(HERE, "out", "measure-pack.md")
HOURS = (0, 4, 8, 12, 16, 20)
ZLEVEL = 19
TOP_LEVELS = 10
KEYFRAME = 60


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


# ---------------------------------------------------------------- выбор имён
def day_files(root, sub, day):
    """Файлы одних суток: (имя, час, путь, размер) — по всем именам."""
    out = []
    base = os.path.join(root, sub)
    if not os.path.isdir(base):
        return out
    for sym in sorted(os.listdir(base)):
        d = os.path.join(base, sym)
        if not os.path.isdir(d):
            continue
        for hh in range(24):
            p = os.path.join(d, f"{day}-{hh:02d}.jsonl.gz")
            try:
                out.append((sym, hh, p, os.path.getsize(p)))
            except OSError:
                continue
    return out


def pick_names(files, n, hour=12):
    """Треть тяжёлых, треть из середины, треть лёгких — по книге часа `hour`."""
    at = sorted(((sz, sym) for sym, hh, _p, sz in files if hh == hour),
                reverse=True)
    if not at:
        return []
    k = max(1, n // 3)
    heavy = [s for _, s in at[:k]]
    mid0 = max(0, len(at) // 2 - k // 2)
    middle = [s for _, s in at[mid0:mid0 + k]]
    light = [s for _, s in at[-k:]]
    seen, out = set(), []
    for s in heavy + middle + light:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:n]


# ------------------------------------------------------------------ форматы
def lines_of(path):
    return read_jsonl(path, parse=lambda ln: ln.rstrip("\n"))


def strip_ladder(r):
    return {k: v for k, v in r.items() if k not in ("b", "a")}


def dumps(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def encode_deltas(rows, keyframe=KEYFRAME):
    """Ключевой кадр раз в `keyframe` строк, дальше — изменившиеся уровни.

    Уровень с объёмом 0 в дельте означает «уровень ушёл». Порядок уровней
    в кадре — как в снимке; при восстановлении лесенка сортируется по
    цене, как её и пишет сборщик.
    """
    out, prev = [], None
    for i, r in enumerate(rows):
        if prev is None or i % keyframe == 0:
            out.append(dict(r, k=1))
            prev = r
            continue
        d = strip_ladder(r)
        for side in ("b", "a"):
            old = {p: q for p, q in prev[side]}
            new = {p: q for p, q in r[side]}
            d["d" + side] = ([[p, q] for p, q in r[side] if old.get(p) != q]
                             + [[p, 0] for p in old if p not in new])
        out.append(d)
        prev = r
    return out


def decode_deltas(items):
    rows, prev = [], None
    for d in items:
        if d.get("k") == 1:
            r = {k: v for k, v in d.items() if k != "k"}
            rows.append(r)
            prev = r
            continue
        if prev is None:
            raise ValueError("дельта без ключевого кадра")
        r = {k: v for k, v in d.items() if k not in ("db", "da")}
        for side in ("b", "a"):
            book = {p: q for p, q in prev[side]}
            for p, q in d.get("d" + side, ()):
                if q == 0:
                    book.pop(p, None)
                else:
                    book[p] = q
            rev = side == "b"
            r[side] = [[p, book[p]] for p in sorted(book, reverse=rev)]
        rows.append(r)
        prev = r
    return rows


def same_rows(a, b):
    """Снимки равны: скаляры и лесенка (лесенка — как множество уровней)."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if strip_ladder(x) != strip_ladder(y):
            return False
        for side in ("b", "a"):
            if sorted(map(tuple, x[side])) != sorted(map(tuple, y[side])):
                return False
    return True


def zc(level=ZLEVEL, dict_data=None):
    if zstd is None:
        return None
    if dict_data is not None:
        return zstd.ZstdCompressor(level=level, dict_data=dict_data)
    return zstd.ZstdCompressor(level=level)


def zsize(comp, data):
    return None if comp is None else len(comp.compress(data))


def measure_book_hour(lines, on_disk, dict_data=None, level=ZLEVEL,
                      with_xz=True):
    """Размеры одного часа книги по вариантам; None — не измерено."""
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    rows = [json.loads(ln) for ln in lines if ln.strip()]
    ladder_bytes = sum(len(ln) - len(dumps(strip_ladder(r)))
                       for ln, r in zip((x for x in lines if x.strip()), rows))
    c = zc(level)
    out = {"disk_gz": on_disk, "raw": len(raw),
           "gzip9": len(gzip.compress(raw, 9)),
           "xz6": (len(lzma.compress(raw, preset=6)) if with_xz else None),
           "zstd": zsize(c, raw),
           "zstd_dict": zsize(zc(level, dict_data), raw) if dict_data else None,
           "ladder_share": (ladder_bytes / max(1, len(raw))),
           "rows": len(rows)}
    if rows and "b" in rows[0]:
        d = encode_deltas(rows)
        back = decode_deltas(d)
        if not same_rows(rows, back):
            raise SystemExit("дельты не восстанавливают снимки — формат "
                             "с потерями, замер недействителен")
        out["deltas_zstd"] = zsize(c, ("\n".join(dumps(x) for x in d) + "\n")
                                   .encode("utf-8"))
        sc = "\n".join(dumps(strip_ladder(r)) for r in rows) + "\n"
        out["scalars_zstd"] = zsize(c, sc.encode("utf-8"))
        top = "\n".join(dumps(dict(r, b=r["b"][:TOP_LEVELS],
                                   a=r["a"][:TOP_LEVELS])) for r in rows) + "\n"
        out["top10_zstd"] = zsize(c, top.encode("utf-8"))
    else:
        out["deltas_zstd"] = out["scalars_zstd"] = out["top10_zstd"] = None
    return out


def train_dict(samples, size=112 * 1024):
    if zstd is None or not samples:
        return None
    try:
        return zstd.train_dictionary(size, samples)
    except Exception as e:                                    # noqa: BLE001
        log(f"словарь не обучился: {e}")
        return None


VARIANTS = (("disk_gz", "gzip, как на диске"), ("gzip9", "gzip-9 заново (контроль)"),
            ("xz6", "xz-6"), ("zstd", f"zstd-{ZLEVEL}"),
            ("zstd_dict", f"zstd-{ZLEVEL} + словарь"),
            ("deltas_zstd", f"дельты уровней + zstd-{ZLEVEL}"),
            ("top10_zstd", f"{TOP_LEVELS} уровней + zstd-{ZLEVEL}"),
            ("scalars_zstd", f"скаляры без лесенки + zstd-{ZLEVEL}"))


def measure(root, day, names=30, hours=HOURS, level=ZLEVEL, with_xz=True,
            log=log, state=None):
    book = day_files(root, "book", day)
    trades = day_files(root, "trades", day)
    if not book:
        raise SystemExit(f"за {day} нет файлов книги в {root}/book")
    syms = pick_names(book, names)
    log(f"сутки {day}: файлов книги {len(book)} ({sum(s for *_, s in book) / 2**30:.2f} ГБ), "
        f"ленты {len(trades)} ({sum(s for *_, s in trades) / 2**30:.2f} ГБ); "
        f"имён в выборке {len(syms)} из {len({s for s, *_ in book})}, часов {list(hours)}; "
        f"zstd {'есть' if zstd else 'НЕТ — не измеряется'}")
    by_book = {(s, h): (p, sz) for s, h, p, sz in book}
    by_tr = {(s, h): (p, sz) for s, h, p, sz in trades}
    tot = {k: 0 for k, _ in VARIANTS}
    miss = {k: 0 for k, _ in VARIANTS}
    ladder, rows_n = 0.0, 0
    tr_tot = {"disk_gz": 0, "zstd": 0, "zstd_miss": 0}
    t0, last = time.time(), time.time()
    done = 0
    for si, sym in enumerate(syms):
        # словарь — на часе, которого НЕТ в замере (иначе он видел бы образец)
        dict_data = None
        other = [h for h in range(24) if h not in hours and (sym, h) in by_book]
        if other and zstd is not None:
            p, _ = by_book[(sym, other[len(other) // 2])]
            sample = [ln.encode("utf-8") for ln in lines_of(p)[::4]]
            dict_data = train_dict(sample)
        for h in hours:
            if (sym, h) in by_book:
                p, sz = by_book[(sym, h)]
                r = measure_book_hour(lines_of(p), sz, dict_data=dict_data,
                                      level=level, with_xz=with_xz)
                for k, _ in VARIANTS:
                    if r.get(k) is None:
                        miss[k] += 1
                    else:
                        tot[k] += r[k]
                ladder += r["ladder_share"] * r["raw"]
                rows_n += r["rows"]
                tot.setdefault("raw", 0)
                tot["raw"] += r["raw"]
            if (sym, h) in by_tr:
                p, sz = by_tr[(sym, h)]
                raw = ("\n".join(lines_of(p)) + "\n").encode("utf-8")
                tr_tot["disk_gz"] += sz
                z = zsize(zc(level), raw)
                if z is None:
                    tr_tot["zstd_miss"] += 1
                else:
                    tr_tot["zstd"] += z
            done += 1
            if time.time() - last > 30:
                last = time.time()
                el = time.time() - t0
                log(f"  {sym} {h:02d}: часов {done}/{len(syms) * len(hours)}, "
                    f"{el:.0f} с, осталось ≈ {el / done * (len(syms) * len(hours) - done):.0f} с")
        if state:
            _write_state(state, day, syms[:si + 1], tot, miss, tr_tot,
                         ladder, rows_n, partial=True)
    res = _result(day, syms, hours, level, tot, miss, tr_tot, ladder, rows_n,
                  book, trades, time.time() - t0)
    return res


def _result(day, syms, hours, level, tot, miss, tr_tot, ladder, rows_n,
            book, trades, secs):
    day_book = sum(s for *_, s in book)
    day_tr = sum(s for *_, s in trades)
    base = tot.get("disk_gz") or 0
    rows = []
    for k, title in VARIANTS:
        v = tot.get(k)
        measured = miss.get(k, 0) == 0 and v
        ratio = (v / base) if (measured and base) else None
        rows.append({"key": k, "title": title, "bytes": (v if measured else None),
                     "ratio": ratio,
                     "day_gb": (day_book * ratio / 2**30 if ratio else None),
                     "missing_hours": miss.get(k, 0)})
    tr_ratio = ((tr_tot["zstd"] / tr_tot["disk_gz"])
                if tr_tot["disk_gz"] and not tr_tot["zstd_miss"] else None)
    return {"day": day, "names": syms, "hours": list(hours), "level": level,
            "zstd": zstd is not None, "secs": round(secs, 1),
            "rows": rows_n, "raw_bytes": tot.get("raw", 0),
            "ladder_share": (ladder / tot["raw"]) if tot.get("raw") else None,
            "book": rows,
            "trades": {"disk_gz": tr_tot["disk_gz"], "zstd": tr_tot["zstd"],
                       "ratio": tr_ratio, "missing_hours": tr_tot["zstd_miss"]},
            "day_on_disk": {"book_gb": day_book / 2**30, "trades_gb": day_tr / 2**30,
                            "files_book": len(book), "files_trades": len(trades)},
            "computed_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}


def _write_state(path, day, syms, tot, miss, tr_tot, ladder, rows_n, partial):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"day": day, "partial": partial, "names_done": syms,
                   "tot": tot, "miss": miss, "trades": tr_tot,
                   "ladder": ladder, "rows": rows_n}, f, ensure_ascii=False)


def _p(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def report(res):
    L = [f"# Замер форматов записи стакана — сутки {res['day']}", "",
         f"Имён в выборке {len(res['names'])}, часов {res['hours']}, строк книги "
         f"{res['rows']:,}, сырой JSON {res['raw_bytes'] / 2**20:.0f} МБ; счёт "
         f"{res['secs']:.0f} с; zstd {'есть' if res['zstd'] else 'НЕТ — варианты zstd не измерены'}.",
         "", f"**Доля байт лесенки в строке снимка: {_p(res['ladder_share'] * 100 if res['ladder_share'] is not None else None, 1)} %.**",
         "", "На диске за сутки по ВСЕМ именам: книга "
         f"{res['day_on_disk']['book_gb']:.2f} ГБ ({res['day_on_disk']['files_book']} файлов), лента "
         f"{res['day_on_disk']['trades_gb']:.2f} ГБ ({res['day_on_disk']['files_trades']} файлов).", "",
         "## Книга: варианты хранения", "",
         "| вариант | МБ в выборке | доля от gzip на диске | ГБ/сут на все имена (оценка) | ТБ/год |",
         "|---|---|---|---|---|"]
    for r in res["book"]:
        mb = _p(r["bytes"] / 2**20 if r["bytes"] is not None else None, 1)
        L.append(f"| {r['title']} | {mb} | {_p(r['ratio'])} | {_p(r['day_gb'])} | "
                 f"{_p(r['day_gb'] * 365 / 1024 if r['day_gb'] else None)} |"
                 + (f" не измерено у {r['missing_hours']} часов" if r["missing_hours"] else ""))
    t = res["trades"]
    L += ["", "## Лента", "",
          f"gzip на диске {t['disk_gz'] / 2**20:.1f} МБ в выборке; zstd-{res['level']} — доля "
          f"{_p(t['ratio'])}" + (f" (не измерено у {t['missing_hours']} часов)" if t["missing_hours"] else "") + ".",
          "", "## Что это значит и чего НЕ значит", "",
          "«ГБ/сут» у варианта — размер суток на диске, умноженный на долю ПО ВЫБОРКЕ; "
          "выборка — треть тяжёлых, треть средних, треть лёгких имён по часу 12, и доля у "
          "полного состава может отличаться. Дельты и скаляры восстанавливают снимок без "
          "потерь только у дельт; «скаляры» и «10 уровней» теряют лесенку — это варианты для "
          "ДИСКА при полной записи в хранилище, и решение о них — владельца. "
          "Контроль «gzip-9 заново» обязан быть близок к «как на диске»: иначе выборка читалась не тем файлом.",
          f"", f"Посчитано {res['computed_at']} UTC."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=(datetime.now(timezone.utc) - timedelta(days=3))
                    .strftime("%Y-%m-%d"))
    ap.add_argument("--names", type=int, default=30)
    ap.add_argument("--hours", default=",".join(str(h) for h in HOURS))
    ap.add_argument("--level", type=int, default=ZLEVEL)
    ap.add_argument("--no-xz", action="store_true")
    ap.add_argument("--root", default=ROOT_B1)
    a = ap.parse_args(argv)
    hours = tuple(int(x) for x in a.hours.split(",") if x.strip())
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    res = measure(a.root, a.day, names=a.names, hours=hours, level=a.level,
                  with_xz=not a.no_xz, state=OUT_JSON + ".state")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    txt = report(res)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
