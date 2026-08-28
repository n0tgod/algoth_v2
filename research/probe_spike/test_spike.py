#!/usr/bin/env python3
"""Проверки зонда всплеска: каждая дорога исполняется на подставном складе.

Склад пишется НАПРЯМУЮ теми же ключами, что кладёт свёртка: зонд читает
склад, и фикстура обязана выглядеть как живой артефакт (правило,
которое в этом проекте уже стоило ложно зелёного теста лиги).
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
Z2 = os.path.join(os.path.dirname(HERE), "z2_book")
for p in (HERE, Z2):
    if p not in sys.path:
        sys.path.insert(0, p)

import bookfeat2 as B                                     # noqa: E402
import fold as F                                          # noqa: E402
import probe as P2                                        # noqa: E402
import spike as S                                         # noqa: E402
from test_probe import check, FAILED                      # noqa: E402

DAYS = ["2026-08-18", "2026-08-19", "2026-08-20"]
NARROW_DAY = "2026-08-17"          # сутки узкого состава: замером не служат
SYMS = [f"S{i:02d}USDT" for i in range(8)]
MINS = 1440


def write_store_day(store, day, syms, seed=1, quiet_only=False):
    """Сутки склада: спокойный ряд плюс всплески двух родов.

    Половина всплесков подтверждена лентой (сделки есть, тихая доля
    мала), половина котировочная (сделок нет, ход сделан без единой
    сделки). Разделять их зонд и обязан.
    """
    rng = np.random.default_rng(seed)
    n = len(syms)
    M = {f: np.full((n, MINS), np.nan, dtype=np.float32)
         for f in B.FOLD_FIELDS}
    for r in range(n):
        px = 100.0 * float(np.exp(rng.normal(0, 0.01)))
        row = np.empty(MINS, dtype=np.float64)
        for m in range(MINS):
            px *= float(np.exp(rng.normal(0, 0.0004)))
            row[m] = px
        # Всплески: каждые 120 минут, со сдвигом по имени, чтобы фон
        # существовал (синхронный сигнал не оставляет кросс-секции).
        for k, m in enumerate(range(60 + r * 7, MINS - 300, 120)):
            row[m:] *= 1.03
            conf = (k % 2 == 0) and not quiet_only
            M["trades"][r, m] = 50.0 if conf else 0.0
            M["path"][r, m] = 0.03
            M["path_quiet"][r, m] = 0.003 if conf else 0.029
            if conf:                      # подтверждённые откатывают
                row[m + 1:m + 61] /= np.linspace(1.0, 1.01, 60)
        M["mid_open"][r] = row
        M["spread"][r] = 5.0 + rng.random(MINS)
        for f in ("trades", "path", "path_quiet"):
            v = M[f][r]
            v[~np.isfinite(v)] = (3.0 if f == "trades" else
                                  (0.002 if f == "path" else 0.0002))
        M["snaps"][r] = 60.0
    os.makedirs(store, exist_ok=True)
    payload = {f: M[f] for f in B.FOLD_FIELDS}
    payload["symbols"] = np.array(syms)
    payload["version"] = np.array([B.FOLD_VERSION if hasattr(B, "FOLD_VERSION")
                                   else 1], dtype=np.int32)
    payload["rows"] = np.array([n], dtype=np.int32)
    payload["minutes"] = np.array([n * MINS], dtype=np.int64)
    np.savez_compressed(os.path.join(store, day + ".npz"), **payload)


def _setup(quiet_only=False, narrow_first=False):
    root = tempfile.mkdtemp()
    old = (P2.BOOK, P2.STORE, S.OUT, P2.MIN_SNAPS, F.STORE, F.THIN_ROWS)
    # Порог «широких суток» абсолютный (100 имён), а фикстура держит
    # восемь: без сдвига порога ВСЕ сутки числились бы узкими, страж
    # молча падал бы на первые сутки записи, и проверка проверяла бы
    # не то. Двигается порог, а не правило — как у судьи выше.
    F.THIN_ROWS = 4
    P2.BOOK = os.path.join(root, "book")
    P2.STORE = os.path.join(root, "store")
    # Страж начала читает склад ЧЕРЕЗ модуль свёртки, а не через зонд:
    # не подменив и его, проверка шла бы мимо той дороги, которую
    # проверяет (урок «дорога до показа» — величина верна, а до места
    # не доезжает).
    F.STORE = P2.STORE
    S.OUT = os.path.join(root, "out")
    P2.MIN_SNAPS = 1
    if narrow_first:
        write_store_day(P2.STORE, NARROW_DAY, SYMS[:2], seed=1,
                        quiet_only=quiet_only)
    for i, d in enumerate(DAYS):
        write_store_day(P2.STORE, d, SYMS, seed=5 + i, quiet_only=quiet_only)
    return root, old


def _restore(old):
    (P2.BOOK, P2.STORE, S.OUT, P2.MIN_SNAPS, F.STORE, F.THIN_ROWS) = old


def _thin_judge():
    keep = (Z_MOD.MIN_CROSS, Z_MOD.MIN_BUCKETS, Z_MOD.DEDUP_MIN)
    Z_MOD.MIN_CROSS, Z_MOD.MIN_BUCKETS, Z_MOD.DEDUP_MIN = 3, 1, 5
    return keep


def _fat_judge(keep):
    Z_MOD.MIN_CROSS, Z_MOD.MIN_BUCKETS, Z_MOD.DEDUP_MIN = keep


import screen as Z_MOD                                    # noqa: E402


def test_probe_runs_and_separates_quote_from_price():
    """Прогон целиком, и котировочные события отделены от подтверждённых."""
    root, old = _setup()
    keep = _thin_judge()
    try:
        rc = S.main(["--no-publish", "--tag", "t",
                     "--symbols", ",".join(SYMS)])
        check("прогон дошёл до конца", rc == 0, f"код {rc}")
        rep = os.path.join(S.OUT, "SPIKE-report-t.md")
        check("отчёт написан", os.path.exists(rep), rep)
        txt = open(rep, encoding="utf-8").read()
        check("обе группы в таблице цены сделки",
              "подтверждён лентой" in txt and "котировочный" in txt,
              txt[-800:])
        # Проверяется та часть фразы, которая несёт ПРАВИЛО, а не её
        # начало: «нижняя граница» без причины прошло бы и на тексте,
        # где причина потеряна (урок двух холостых контролей Z2).
        check("сказано, ПОЧЕМУ оценка нижняя",
              "без обхода лесенки" in txt, txt[:1400])
        got = json.load(open(os.path.join(S.OUT, "spike-t.json"),
                             encoding="utf-8"))
        conf = [k for k in got["cells"] if "подтверждён" in k]
        quote = [k for k in got["cells"] if "котировочный" in k]
        check("подтверждённые ячейки есть", bool(conf), str(list(got["cells"])[:3]))
        check("котировочные ячейки есть", bool(quote), str(list(got["cells"])[:3]))
        ec = got["cells"][conf[0]]["events"]
        eq = got["cells"][quote[0]]["events"]
        check("группы не совпали по числу событий", ec != eq,
              f"{ec} против {eq}")
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_quote_only_day_gives_no_confirmed_events():
    """Сутки, где всплески идут БЕЗ сделок, подтверждённых не дают.

    Это проверка самого различения: если гейт по ленте молчит, зонд
    объявит котировочный скачок ценой — ровно та ошибка, ради которой
    он и написан.
    """
    root, old = _setup(quiet_only=True)
    keep = _thin_judge()
    try:
        S.main(["--no-publish", "--tag", "q", "--symbols", ",".join(SYMS)])
        got = json.load(open(os.path.join(S.OUT, "spike-q.json"),
                             encoding="utf-8"))
        conf = [k for k in got["cells"] if "подтверждён" in k]
        check("подтверждённых событий нет вовсе", not conf,
              str(conf[:3]))
        quote = [k for k in got["cells"] if "котировочный" in k]
        check("а котировочные посчитаны", bool(quote), "их тоже нет")
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_round_trip_charges_both_legs_by_half_spread():
    """Круг: комиссия ДВУХ ног плюс по половине спреда каждой.

    Числа закреплены прямо, а не свойством: конвенция D1 (6.8 и 6.1
    б.п. спреда при комиссии 11 дали круг 17.4) держится только на
    половинах, и подстановка полного спреда завышала бы издержки почти
    вдвое — вердикт «не окупается» вышел бы бесплатно.
    """
    a = {"spread_in": [6.0, 8.0], "spread_out": [4.0, 6.0],
         "hedge_in": [2.0, 4.0], "hedge_out": [1.0, 3.0]}
    rnd, si, so, hi, ho = S.round_trip(a)
    check("медианы спредов взяты верно",
          (si, so, hi, ho) == (7.0, 5.0, 3.0, 2.0), f"{si}/{so}/{hi}/{ho}")
    # 2 × 11 + (7 + 5)/2 + (3 + 2)/2 = 22 + 6 + 2.5 = 30.5
    check("круг двух ног = 30.5", abs(rnd - 30.5) < 1e-9, f"{rnd}")
    check("спред НЕ взят целиком", abs(rnd - 39.0) > 1e-6,
          "круг посчитан полными спредами, а не половинами")
    # Конвенция D1 воспроизводится: одна нога, спреды 6.8 и 6.1 → 17.4
    solo = S.LEGS / 2 * S.FEE_BP + (6.8 + 6.1) / 2
    check("конвенция D1 воспроизведена", abs(solo - 17.45) < 0.01,
          f"{solo}")


def test_report_names_hedge_spread():
    """Отчёт обязан говорить, что вторую ногу тоже посчитали.

    Без этой строки колонка «круг двух ног» читается как круг одной, и
    величина выглядит завышенной вдвое без причины.
    """
    root, old = _setup()
    keep = _thin_judge()
    try:
        S.main(["--no-publish", "--tag", "h", "--symbols", ",".join(SYMS)])
        txt = open(os.path.join(S.OUT, "SPIKE-report-h.md"),
                   encoding="utf-8").read()
        check("сказано про половину спреда", "половине спреда" in txt,
              txt[:1200])
        check("сказано про спред хедж-ноги",
              "спред\nхедж-ноги" in txt or "спред хедж-ноги" in txt,
              txt[:1200])
        check("колонка хеджа в таблице", "спред хеджа" in txt, txt[-900:])
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_narrow_early_day_is_not_measured():
    """Узкие по составу сутки в замер не входят.

    Состав сборщика рос ступенями 25 → 30 → 540 → 725 имён, и на
    ранних сутках кросс-секции, которой меряется превышение, нет вовсе
    (урок T1: при четырёх символах медианный фон 0–2 имени, а величины
    печатались и выглядели результатом).
    """
    root, old = _setup(narrow_first=True)
    keep = _thin_judge()
    try:
        S.main(["--no-publish", "--tag", "n", "--symbols", ",".join(SYMS)])
        txt = open(os.path.join(S.OUT, "SPIKE-report-n.md"),
                   encoding="utf-8").read()
        check("замер начат с широких суток", DAYS[0] in txt.split("\n")[2],
              txt.split("\n")[2])
        check("узкие сутки не стали началом",
              NARROW_DAY not in txt.split("\n")[2], txt.split("\n")[2])
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def test_diag_counts_in_basis_points():
    """Таблица цены сделки считает в БАЗИСНЫХ ПУНКТАХ, а не в долях.

    `fwd_ret` отдаёт долю, судья домножает на 1e4 у себя, и первый
    живой прогон напечатал «−0.0» превышения при +38.5 б.п. в главной
    таблице: одна таблица отчёта противоречила другой, и меньшая
    читалась как «эффекта нет». Числа закреплены прямо.
    """
    n, mins, h = 3, 300, 60
    M = {f: np.full((n, mins), np.nan, dtype=np.float32)
         for f in B.FOLD_FIELDS}
    for r in range(n):
        M["mid_open"][r] = 100.0
        M["spread"][r] = 4.0
    # Вход по открытию 11-й минуты, выход по 71-й (h = 60): у символа 0
    # цена там на 1 % выше, у остальных та же. Значит его сырой ход
    # +100 б.п., среднее сечения +33.3, превышение +66.7.
    M["mid_open"][0, 71:] = 101.0
    syms = [f"S{i}USDT" for i in range(n)]
    cond = {"name": "проба", "side": +1, "fn": None, "group": "проба"}
    ev = {"проба": (cond, np.array([0]), np.array([10]))}
    acc = {}
    S.diag(ev, M, syms, acc, h=h)
    a = acc["проба"]
    exc = float(np.mean(a["exc"]))
    check("превышение в б.п., а не в долях", abs(exc - 66.7) < 0.5,
          f"{exc:.4f} — доля вместо б.п. дала бы 0.0067")
    check("спред взят из записи", abs(_median(a["spread_in"]) - 4.0) < 1e-6,
          str(a["spread_in"][:3]))
    check("спред хеджа посчитан", abs(_median(a["hedge_in"]) - 4.0) < 1e-6,
          str(a["hedge_in"][:3]))


def _median(v):
    return float(np.percentile(v, 50)) if len(v) else float("nan")


def test_cost_table_agrees_in_sign_with_verdict_table():
    """Две таблицы отчёта не вправе противоречить друг другу по знаку.

    Главная таблица считается судьёй по корзинам, таблица цены сделки —
    прямым проходом; совпадать дословно они не обязаны, а расходиться
    в знаке — не вправе: расхождение и было подписью ошибки единиц.
    """
    root, old = _setup()
    keep = _thin_judge()
    try:
        S.main(["--no-publish", "--tag", "s", "--symbols", ",".join(SYMS)])
        txt = open(os.path.join(S.OUT, "SPIKE-report-s.md"),
                   encoding="utf-8").read()
        cost = txt.split("### Цена сделки")[1]
        vals, by_name = [], {}
        for line in cost.split("\n"):
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 9 and cells[1].startswith("всплеск"):
                v = float(cells[7].replace("+", ""))
                vals.append(v)
                by_name.setdefault(cells[1], {})[cells[2]] = v
        check("строки таблицы цены есть", len(vals) >= 2, str(vals))
        check("превышение не тождественный ноль",
              any(abs(v) > 1.0 for v in vals), str(vals))
        # Сторона обязана переворачивать знак: у лонга и шорта одного
        # условия ход цены один, а исход противоположен. Строка без
        # стороны печатала бы длинную сторону под обеими метками.
        pairs = [(n, d) for n, d in by_name.items() if len(d) == 2]
        check("обе стороны в таблице", bool(pairs), str(list(by_name)[:2]))
        bad = [(n, d) for n, d in pairs
               if abs(d["L"]) > 1.0 and d["L"] * d["S"] >= 0]
        check("знак стороны перевёрнут", not bad, str(bad[:2]))
    finally:
        _fat_judge(keep)
        _restore(old)
        shutil.rmtree(root, ignore_errors=True)


def main():
    tests = (test_probe_runs_and_separates_quote_from_price,
             test_quote_only_day_gives_no_confirmed_events,
             test_round_trip_charges_both_legs_by_half_spread,
             test_report_names_hedge_spread,
             test_narrow_early_day_is_not_measured,
             test_diag_counts_in_basis_points,
             test_cost_table_agrees_in_sign_with_verdict_table)
    for t in tests:
        t()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print(f"все проверки прошли ({len(tests)} блоков)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
