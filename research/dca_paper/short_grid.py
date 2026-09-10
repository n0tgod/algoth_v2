#!/usr/bin/env python3
"""Общая машинерия замеров ОСИ на коротком листе `h24`.

Замеров оси у нас уже два (множитель тейка, пол капитуляции), и оба
делают одно и то же вокруг своей оси: гоняют реплей по барам, кладут
записи по книгам семейства, применяют ПРАВИЛА КНИГИ и считают деньги
нетто с составом исходов, а артефакт сливают, потому что ось считается
частями (память). Второй копии этой дороги быть не должно: она решает,
чем книга торгует, и разойдясь однажды, дала бы двум замерам разные
книги под одним именем.

Ось живёт в самом замере — здесь только общее.
"""
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "research", "a1_universe"))
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "s8_loop"))
import rules as R                                             # noqa: E402
import costs as CO                                            # noqa: E402
import run_paper as RP                                        # noqa: E402
import run_short as S                                         # noqa: E402
import run_d10 as D10                                         # noqa: E402
import run_d11 as D11                                         # noqa: E402
import tail as TL                                             # noqa: E402

MEM_LIMIT_MB = 1200


def replay(legs_, cells, src=None, log=print):
    """Проход по барам на эти ячейки: бары символа читаются один раз.

    Срок и гейт отсчёта ставятся на время прогона тем же способом, что у
    книги (`run_d11.configure`), и возвращаются обратно: оставленный
    глобально срок сделал бы соседний замер другим замером молча.
    """
    was = D11.configure(R.H24_HOLD_H)
    try:
        src = src or TL.TailBars(log=log)
        return D10.collect(legs=legs_, cells=cells, rich=True, raw=True,
                           src=src, log=log)
    finally:
        D11.restore(was)


def pack(recs, key):
    """Записи ячейки по книгам семейства — той же картой, что у прогона."""
    return {bk: list((recs.get(rk) or {}).get(key) or [])
            for bk, rk in S.BOOKS.items()}


def cell_stats(packed, ctx, launch, now=None, log=lambda *a: None):
    """Книги семейства на этих записях: деньги НЕТТО, состав исходов.

    Правила книги применяются ТЕ ЖЕ и в том же порядке, что в прогоне
    (`run_paper.age_shorts` → `build_rows`): замер, торгующий другими
    правилами, отвечал бы на другой вопрос.
    """
    packed = dict(packed)
    for bk in list(packed):
        packed[bk], _why = RP.age_shorts(packed[bk], bk, launch=launch,
                                         log=log, now=now)
    rows, cells_, _one, _live = RP.build_rows(packed, now=now,
                                              keys=R.H24_ORDER, log=log)
    out = {}
    for bk in R.H24_ORDER:
        for dep in R.DEPOSITS:
            mine = [r for r in rows if R.ruler_of(r) == bk
                    and int(r.get("dep", 0)) == int(dep)]
            if ctx is not None and not ctx.get("error"):
                mine, _c = CO.apply_to_rows(mine, ctx)
            st = RP._stats(mine, dep) or {}
            fin, dd = st.get("final"), st.get("max_dd")
            by = collections.Counter(r.get("exit") or "—" for r in mine)
            usd = collections.defaultdict(float)
            for r in mine:
                usd[r.get("exit") or "—"] += float(r.get("usd") or 0.0)
            c = cells_.get(RP._cell(bk, dep)) or {}
            out[f"{bk}:{int(dep)}"] = {
                "book": bk, "dep": int(dep), "n": st.get("n"),
                "usd": st.get("usd"), "final": fin, "max_dd": dd,
                "win": st.get("win"), "day_median": st.get("day_median"),
                "ratio": (None if not fin or not dd
                          else round(float(fin) / abs(float(dd)), 2)),
                "exits": {k: {"n": v, "usd": round(usd[k], 2)}
                          for k, v in by.items()},
                "no_cash": c.get("no_cash"), "taken": c.get("taken")}
    return out


def merge_artifact(s, path, axis):
    """Слить ячейки этого прогона с уже посчитанными.

    Ось объявлена целиком, а считаться может частями (память): ячейка
    прежнего прогона остаётся со СВОЕЙ датой, и отчёт не выдаёт разные
    прогоны за один. Ячейка, посчитанная заново, перекрывает старую.

    `axis` — вся объявленная ось парами (ключ, значение); в артефакт
    едут и посчитанная её часть (`axis`), и вся (`axis_all`), чтобы
    отчёт мог назвать недостающие ячейки, а не молчать о них.
    """
    now = s.get("computed_at")
    s["cell_at"] = {k: now for k in (s.get("cells") or {})}
    s["axis_all"] = [{"key": k, "value": v} for k, v in axis]
    if s.get("error"):
        return s
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = {}
    cells_ = dict(old.get("cells") or {})
    at = dict(old.get("cell_at") or {})
    cells_.update(s.get("cells") or {})
    at.update(s["cell_at"])
    s["cells"], s["cell_at"] = cells_, at
    s["axis"] = [{"key": k, "value": v} for k, v in axis if k in cells_]
    return s


def write(s, name, report_fn, title, log=print):
    """Артефакт и отчёт замера — одним местом, с публикацией прогоном."""
    os.makedirs(R.OUT, exist_ok=True)
    art = os.path.join(R.OUT, f"{name}.json")
    with open(art + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(art + ".tmp", art)
    txt = report_fn(s)
    with open(os.path.join(R.OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    log(txt)
    return txt


def stamp():
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime())
