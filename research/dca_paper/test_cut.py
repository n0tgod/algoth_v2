#!/usr/bin/env python3
"""Проверки досчёта оборванных записью позиций (`cut_check.py`).

Предмет один и он про ГРАНИЦУ: середина стакана дописывается ТОЛЬКО в
хвост, после последнего принта. Всё, что до него, обязано остаться тем
же баром — иначе меняется не конец позиции, а вход, уровни и цены
рунгов, то есть измеряется другая сделка.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_ladder"))
sys.path.insert(0, os.path.join(ROOT, "research", "z2_book"))
import cut_check as C                                         # noqa: E402
import sweep as SW                                            # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "ПРОВАЛ ") + name
          + ("" if cond else f"  · {extra}"))
    if not cond:
        FAILED.append(name)


def _snap(sym, t, mid):
    """Строка снимка ровно того вида, что пишет сборщик."""
    bid, ask = mid * 0.9995, mid * 1.0005
    return json.dumps({"s": sym, "ts": int(t * 1000), "u": 1,
                       "bid": round(bid, 8), "ask": round(ask, 8),
                       "bid_sz": 3.0, "ask_sz": 4.0, "upd": 5,
                       "b": [[bid, 3.0]], "a": [[ask, 4.0]],
                       "reach_b": 50.0, "reach_a": 60.0,
                       "bq0.0005": 10.0, "aq0.0005": 11.0,
                       "bq0.001": 20.0, "aq0.001": 21.0,
                       "bq0.0025": 1000.0, "aq0.0025": 1000.0,
                       "bq0.005": 2000.0, "aq0.005": 2100.0,
                       "t": round(t, 3)}, separators=(",", ":"))


def _trade(sym, t, px):
    return json.dumps({"ts": int(t * 1000), "s": sym, "side": 1,
                       "p": round(px, 8), "v": 1.0},
                      separators=(",", ":"))


def _write(root, kind, sym, t, lines):
    d = os.path.join(root, kind, sym)
    os.makedirs(d, exist_ok=True)
    hour = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d-%H")
    with open(os.path.join(d, f"{hour}.jsonl"), "a", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")


def make_root(sym="AAAUSDT", h0=1756000000 // 3600 * 3600):
    """Запись с ДЫРОЙ в ленте посередине и хвостом только в книге.

    Лента: минуты 0–9 и 20–29 (дыра 10–19), дальше молчит.
    Книга: снимки каждые 15 с все 60 минут часа.
    """
    root = tempfile.mkdtemp(prefix="cutchk-")
    px = 100.0
    for m in range(60):
        for k in range(4):
            t = h0 + m * 60 + k * 15
            _write(root, "book", sym, t, [_snap(sym, t, px + m * 0.01)])
        if m < 10 or 20 <= m < 30:
            _write(root, "trades", sym, h0 + m * 60,
                   [_trade(sym, h0 + m * 60 + 5, px + m * 0.01)])
    return root, sym, h0


def test_book_bars_are_ohlc_and_gaps_are_absent():
    """Минутный бар книги: первая/крайние/последняя середина. Минута без
    снимков ОТСУТСТВУЕТ, а не выходит нулевой (урок A2)."""
    root = tempfile.mkdtemp(prefix="cutchk-")
    h0 = 1756000000 // 3600 * 3600
    sym = "BBBUSDT"
    for t, mid in ((h0 + 5, 100.0), (h0 + 25, 103.0), (h0 + 45, 101.0),
                   (h0 + 125, 99.0)):
        _write(root, "book", sym, t, [_snap(sym, t, mid)])
    bars = C.book_minute_bars(root, sym, h0, h0 + 3599)
    got = {int(b[0]): b for b in bars}
    check("минута без снимков отсутствует, а не нулевая",
          set(got) == {h0, h0 + 120}, f"{sorted(got)}")
    b = got.get(h0)
    ok = (b and abs(b[1] - 100.0) < 1e-6 and abs(b[2] - 103.0) < 1e-6
          and abs(b[3] - 100.0) < 1e-6 and abs(b[4] - 101.0) < 1e-6)
    check("OHLC минуты собран из середин по порядку", bool(ok), f"{b}")
    check("объём бара книги ноль (сделок не было)",
          bool(b) and b[5] == 0.0, f"{b}")


def test_tail_only_prefix_is_untouched():
    """Дописывается ТОЛЬКО хвост: всё до последнего принта — те же бары.

    Дыра в середине ленты НЕ заливается серединой намеренно: по этим
    барам считаются вход, уровни и цены рунгов, а рунг и тейк суть
    лимитки, которые исполняет чужой принт.
    """
    root, sym, h0 = make_root()
    t1 = h0 + 3599
    tape = SW.read_bars(root, sym, h0, t1)
    src = C.TailBars(root=root)
    got = src.bars(sym, h0, t1)
    last = float(tape[-1][0])
    check("лента прочиталась и кончилась раньше окна",
          bool(tape) and last < t1 - 600,
          f"баров {len(tape)}, последний {last - h0:g} с от начала часа")
    head = got[:len(tape)]
    check("префикс совпадает с лентой бит в бит", head == tape,
          f"{head[:2]} против {tape[:2]}")
    add = got[len(tape):]
    check("дописано только ПОСЛЕ последнего принта",
          bool(add) and min(b[0] for b in add) > last,
          f"{[b[0] - last for b in add[:3]]}")
    # Дыра ленты 10–19 минут внутри окна остаётся дырой.
    mins = {int((b[0] - h0) // 60) for b in got}
    check("внутренняя дыра ленты не залита серединой",
          not (mins & set(range(10, 20))),
          f"минуты {sorted(mins & set(range(10, 20)))}")
    check("хвост дописан по всем оставшимся минутам",
          len(add) == 30, f"{len(add)}")
    check("символ отмечен как дописанный",
          src.added.get(sym) == len(add) and not src.dry,
          f"added={src.added}, dry={src.dry}")


def test_no_tape_means_no_position():
    """Ленты нет вовсе — книгой не подменяем: без принтов нет ни входа,
    ни уровней, и позиция была бы другой сделкой, а не дописанной."""
    root = tempfile.mkdtemp(prefix="cutchk-")
    h0 = 1756000000 // 3600 * 3600
    sym = "CCCUSDT"
    for k in range(10):
        t = h0 + k * 60
        _write(root, "book", sym, t, [_snap(sym, t, 100.0 + k)])
    src = C.TailBars(root=root)
    check("без ленты бары пусты", src.bars(sym, h0, h0 + 3599) == [],
          "книга подменила ленту")


def test_dry_tail_stays_cut():
    """Нет книги в хвосте — бары не меняются, символ назван числом."""
    root = tempfile.mkdtemp(prefix="cutchk-")
    h0 = 1756000000 // 3600 * 3600
    sym = "DDDUSDT"
    for m in range(5):
        _write(root, "trades", sym, h0 + m * 60,
               [_trade(sym, h0 + m * 60 + 5, 100.0 + m)])
    src = C.TailBars(root=root)
    tape = SW.read_bars(root, sym, h0, h0 + 3599)
    got = src.bars(sym, h0, h0 + 3599)
    check("пустой хвост оставляет бары как есть", got == tape,
          f"{len(got)} против {len(tape)}")
    check("символ без книги в хвосте назван", src.dry == [sym],
          f"{src.dry}")


def test_data_end_uses_whole_cache():
    """Граница записи берётся по ВСЕМУ кэшу, а не по пересчитанному
    подмножеству: досчитанный хвост двигает `end_ts` вверх, и считай мы
    границу по нему, классификация поехала бы вслед за своей же правкой.
    """
    cache = {
        (("depth", 2.0), "AAA", 1.0): {"end_ts": 1000.0, "state": "closed"},
        (("depth", 2.0), "BBB", 2.0): {"end_ts": 9000.0, "state": "closed"},
        (("depth", 2.0), "CCC", 3.0): {"end_ts": 1500.0, "state": "cut"},
    }
    check("граница записи — максимум по всем решениям",
          C.data_end_of(cache) == 9000.0, f"{C.data_end_of(cache)}")
    check("оборванные найдены по всем линейкам",
          C.cut_keys(cache) == [("CCC", 3.0)], f"{C.cut_keys(cache)}")


def test_state_after_fill_is_closed_by_old_boundary():
    """Досчитанная позиция становится закрытой, недосчитанная — нет.

    Проверяется дорога целиком: правило `position_state` при ПРЕЖНЕЙ
    границе записи. Иначе «досчитали» и «граница уехала» неразличимы.
    """
    import run_d6 as D6
    # Граница отстоит от окон позиций больше чем на `FRESH_TOL`: иначе
    # недосчитанная позиция читается ЖИВОЙ, а не оборванной, и проверка
    # мерила бы не то (первый прогон этого теста дал ровно это).
    end0 = 100000.0
    filled = {"exit": "срок", "end_ts": 5000.0, "sched_end": 5000.0}
    short = {"exit": "срок", "end_ts": 4000.0, "sched_end": 5000.0}
    check("дошедшая до планового конца закрыта",
          D6.position_state(filled, end0) == "closed",
          D6.position_state(filled, end0))
    check("недошедшая остаётся оборванной",
          D6.position_state(short, end0) == "cut",
          D6.position_state(short, end0))


def test_report_builds_and_shows_both_sides():
    """Сборка отчёта исполняется тестом, а не только прогоном.

    У одноразового замера дорог несколько (источник баров, счёт, отчёт,
    публикация), и «тесты зелёные» значит ровно те, которые тест
    исполняет. Падение на ПОСЛЕДНЕМ шаге уже стоило проекту прогонов —
    здесь оно ловится без сервера.
    """
    import rules as R
    import run_paper as P
    st_b = {"n": 10, "days": 5, "usd": 100.0, "final": 0.01,
            "max_dd": -0.02, "day_median": 0.001, "day_worst": -0.01,
            "day_green": 0.6, "win": 0.9, "hold_h": 12.0,
            "hold_med_h": 11.0, "bite": 4.5, "top_sym": "AAAUSDT",
            "usd_wo_top": 80.0, "top_day": "2026-09-01",
            "usd_wo_top3d": 10.0}
    st_a = dict(st_b, n=12, usd=120.0, final=0.012, bite=5.0)
    before, after = {}, {}
    for rk in R.RULER_ORDER:
        for dep in R.DEPOSITS:
            k = P._cell(rk, dep)
            before[k] = {"stats": st_b, "cut_n": 3, "open_n": 2}
            after[k] = {"stats": st_a, "cut_n": 1, "open_n": 2}
    s = {"cut_before": 98, "resolved": 90, "still_cut": 8,
         "dry_symbols": ["ZZZUSDT"], "added_minutes": 1234,
         "added_symbols": 40, "tail_span_h": 0.4,
         "gap": {"n": 98, "med_h": 0.1, "p90_h": 0.9, "max_h": 25.3},
         "exits": {"срок": 80, "тейк": 10}, "deeper": 0, "mixed": 0,
         "dpnl_n": 90, "before": before, "after": after,
         "data_end": 1756000000.0, "secs": 12.3,
         "computed_at": "2026-09-04 10:00"}
    txt = C.report(s)
    rows = [l for l in txt.splitlines() if l.startswith("| ") and "$" in l]
    check("отчёт собирается и несёт строку на каждую книгу",
          len(rows) >= 2 * len(R.RULER_ORDER) * len(R.DEPOSITS),
          f"строк {len(rows)}")
    # Слова «было» и «стало» стоят в ЗАГОЛОВКЕ и остаются там даже у
    # таблицы с одной колонкой — проверять надо числа самой строки
    # (тот же класс, что «блок есть на пустом блоке»).
    both = [l for l in rows if "100.0" in l and "120.0" in l]
    check("каждая денежная строка несёт и «было», и «стало»",
          len(both) >= len(R.RULER_ORDER) * len(R.DEPOSITS),
          f"строк с обеими величинами {len(both)} из {len(rows)}")
    check("оставшиеся оборванными названы отдельно",
          "осталось оборванными | 8" in txt, "")
    check("на пустом прогоне отчёт не падает, а называет причину",
          "Прогон не состоялся" in C.report({"error": "кэша нет"}), "")


def main():
    test_book_bars_are_ohlc_and_gaps_are_absent()
    test_tail_only_prefix_is_untouched()
    test_no_tape_means_no_position()
    test_dry_tail_stays_cut()
    test_data_end_uses_whole_cache()
    test_state_after_fill_is_closed_by_old_boundary()
    test_report_builds_and_shows_both_sides()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО {len(FAILED)}: " + ", ".join(FAILED))
        sys.exit(1)
    print("все проверки прошли")


if __name__ == "__main__":
    main()
