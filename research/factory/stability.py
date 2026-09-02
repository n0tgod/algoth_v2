"""Устойчивость книги: не «сколько принесла», а КАК приносила.

Решение владельца (2026-09-02): «важнее стабильность — стратегии,
которые приносят немного, но стабильно, и не забирают за один день всю
прибыль за неделю или месяц; отталкиваться надо именно от этого».

Проект уже приходил к этой мере с другой стороны, и это не совпадение:
спека 04 объявила критерии 6–8 ПЕРВИЧНЫМИ для carry ровно потому, что
carry даёт ровную мелкую прибыль и редкий крупный убыток, а Sharpe
такую конструкцию систематически льстит. Критерий 8 там записан теми же
словами, что сказал владелец: отношение худшего периода к медианному
терпимо на десяти и означает «год работы отдаётся за неделю» на сорока.

Меры объявлены ЗДЕСЬ и до чтения чисел — иначе порог, подобранный после
результата, есть перебор без поправки:

* `days`      — суток с закрытыми сделками (наблюдений, а не календаря);
* `green`     — доля прибыльных суток;
* `med`       — медиана суток: сколько приносит ОБЫЧНЫЙ день;
* `med_green` — медиана прибыльных суток;
* `worst`     — худшие сутки;
* `bite`      — |худший день| / медиана прибыльного дня, то есть
                СКОЛЬКО ОБЫЧНЫХ ХОРОШИХ ДНЕЙ СЪЕДАЕТ ОДИН ПЛОХОЙ.
                Это и есть вопрос владельца числом;
* `dd`        — глубочайший провал накопленной кривой;
* `under`     — суток ниже прошлого максимума (сколько книга сидит
                под водой): «забрал за день прибыль недели» видно
                именно здесь, а не в глубине провала;
* `red`       — длиннейшая красная серия подряд;
* `tot`       — итог за окно.

Правило тонких данных: меньше `MIN_DAYS` суток — величины считаются, но
книга помечается `thin`, и вердикта по ней не выносится. Десять суток
взяты не с потолка: столько же требует правило вылета (`pool.WINDOW_D`),
и две разные границы у одного пула разошлись бы.

Единица не назначается модулем: у живой книги сутки приходят в
долларах, у реплея — в долях гросса. Отношения (`bite`) безразмерны и
сравнимы всегда, `dd` и `tot` — только внутри своей единицы.
"""

import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
for _p in (os.path.join(RESEARCH, "s10_policy"),
           os.path.join(RESEARCH, "s8_loop"), os.path.join(RESEARCH, "s9_sweep")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Просадка накопленной кривой — ТОЙ ЖЕ функцией, что у турнира политик:
# вторая реализация однажды разошлась бы, и отчёт говорил бы одно, а
# таблица другое.
import tournament as TN                                     # noqa: E402

MIN_DAYS = 10


def stats(daily):
    """Устойчивость по ряду «сутки → нетто за эти сутки».

    Ключ суток — что угодно сортируемое (дата строкой либо номер дня):
    порядок задаёт только накопленную кривую, и смешивать два вида
    ключей в одном ряду нельзя — сортировка молча перепутала бы дни.
    """
    if not daily:
        return None
    vals = [daily[d] for d in sorted(daily)]
    green = [v for v in vals if v > 0]
    tot, dd = TN.curve_dd(dict(enumerate(vals)))
    # Под водой: сутки, когда накопленное ниже прошлого максимума.
    run = peak = 0.0
    under = 0
    for v in vals:
        run += v
        if run < peak - 1e-12:
            under += 1
        peak = max(peak, run)
    red = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        red = max(red, cur)
    med_green = st.median(green) if green else None
    worst = min(vals)
    # Укус: сколько обычных хороших дней съедает худший день. Без
    # прибыльных суток мера не существует — ноль тут читался бы как
    # «не кусает», а на деле кусать просто нечего.
    bite = (None if not med_green or med_green <= 0
            else round(abs(worst) / med_green, 1))
    return {"days": len(vals),
            "green": round(len(green) / len(vals), 3),
            "med": round(st.median(vals), 2),
            "med_green": None if med_green is None else round(med_green, 2),
            "worst": round(worst, 2),
            "bite": bite,
            "dd": dd, "under": under, "red": red, "tot": tot,
            "thin": len(vals) < MIN_DAYS}


# --- прогон: числа берутся у САМОГО сервера ------------------------
#
# Ряды суток строит сборщик (`/book_days`) и суточный прогон фабрики
# (`/factory_built`) — те же числа, что видит владелец на страницах.
# Второй обход файлов дал бы вторую реализацию кассы, и отчёт однажды
# разошёлся бы со страницей; здесь он читает ровно то, что показано.

import argparse                                             # noqa: E402
import json                                                 # noqa: E402
import subprocess                                           # noqa: E402
import time                                                 # noqa: E402
import urllib.request                                       # noqa: E402

import books as BK                                          # noqa: E402
import pool as PL                                           # noqa: E402

OUT = os.path.join(HERE, "out")
TOKEN = os.path.join(RESEARCH, "b1_book", "out", "token.txt")


def _get(base, path, key, timeout=120):
    url = f"{base}{path}{'&' if '?' in path else '?'}k={key}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def live_rows(base, key, keys):
    """Устойчивость ЖИВЫХ книг: сутки в долларах, как их считает касса."""
    out = []
    for k in keys:
        try:
            d = _get(base, f"/book_days?hz={k}", key)
        except Exception as e:                             # noqa: BLE001
            out.append({"key": k, "error": f"{type(e).__name__}: {e}"})
            continue
        if d.get("unknown"):
            # Книга не из торгуемых: денег не держит вовсе. Это НЕ
            # пустая книга, и молчаливый пропуск читался бы как «нет
            # чисел».
            out.append({"key": k, "skip": "денег не держит"})
            continue
        daily = {r["day"]: ((r.get("arms") or {}).get("all") or {}).get("pnl")
                 for r in (d.get("days") or [])}
        daily = {k2: v for k2, v in daily.items() if v is not None}
        out.append({"key": k, "cap": d.get("cap"), "st": stats(daily)})
    return out


def cand_rows(base, key):
    """Устойчивость РЕПЛЕЯ кандидатов: доли гросса, до и после объявления.

    Две половины считаются РАЗДЕЛЬНО и не складываются: до объявления
    это пересчёт по прошлому, которое ассистент видел, когда предлагал.
    """
    d = _get(base, "/factory_built", key)
    out = []
    for r in d.get("roots") or []:
        for b in r.get("branches") or []:
            daily = {int(x[0]): x[1] for x in (b.get("daily") or [])}
            fwd, pre = PL.split_forward(daily, b.get("declared_at"))
            out.append({"key": b["key"], "lane": b.get("lane"),
                        "alive": b.get("alive"),
                        "fwd": stats(fwd), "pre": stats(pre)})
    return out


def _cell(s, field):
    if not s:
        return "—"
    v = s.get(field)
    return "—" if v is None else f"{v}"


def _money(v, cap):
    """Деньги и доля к депозиту рядом — единица показа всего проекта.

    Депозита нет — печатаем только то, что есть: выдуманный процент
    хуже пропуска.
    """
    if v is None:
        return "—"
    if not cap:
        return f"{v:+.2f} $"
    return f"{v:+.2f} $ ({v / cap * 100:+.2f} %)"


def _pct(v):
    """Доля гросса реплея: базисные пункты хранения — проценты показа."""
    return "—" if v is None else f"{v / 100:+.2f} %"


def _table(rows, get, title, unit):
    lines = [f"### {title}", "",
             "Единица суток — "
             + ("деньги счёта, в скобках доля к депозиту книги."
                if unit == "money"
                else "доля гросса реплея в процентах: своей кассы у "
                     "него нет, и доллары здесь не выдумываются."), "",
             "| книга | суток | зелёных | медиана | худший | "
             "укус | просадка | под водой | красных подряд | итог |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    # Порядок — по ОБЫЧНОМУ ДНЮ, а не по укусу, и это исправление
    # найдено чтением первого же прогона. Укус («сколько хороших дней
    # съедает плохой») осмыслен у конструкции «часто по копейке, редко
    # по многу»; у книги, чей типичный день отрицателен, он мал просто
    # потому, что делить не на что — и такая книга вставала бы наверх
    # таблицы устойчивой. Сперва медиана дня, потом доля зелёных.
    def order(r):
        s = get(r)
        if not s:
            return (2, 0.0, 0.0)
        return (1 if s["thin"] else 0, -(s["med"] or 0.0),
                -(s["green"] or 0.0))
    for r in sorted(rows, key=order):
        s = get(r)
        name = r["key"]
        if r.get("error") or r.get("skip"):
            lines.append(f"| `{name}` | {r.get('error') or r.get('skip')} "
                         "| | | | | | | | |")
            continue
        if not s:
            lines.append(f"| `{name}` | закрытых суток нет "
                         "| | | | | | | | |")
            continue
        mark = " ⚠" if s["thin"] else ""
        fm = ((lambda v: _money(v, r.get("cap"))) if unit == "money"
              else _pct)
        lines.append(
            f"| `{name}`{mark} | {s['days']} | {s['green']:.2f} | "
            f"{fm(s['med'])} | {fm(s['worst'])} | {_cell(s, 'bite')} | "
            f"{fm(s['dd'])} | {s['under']} | {s['red']} | "
            f"{fm(s['tot'])} |")
    lines.append("")
    lines.append(f"⚠ — суток меньше {MIN_DAYS}: величины посчитаны, но "
                 "вердикта по ним нет.")
    return "\n".join(lines)


def report(live, cands, base, at):
    parts = [
        "# Устойчивость книг: не сколько, а КАК",
        "",
        f"Прогон {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(at))}, "
        f"числа взяты у сервера {base} — те же, что на страницах.",
        "",
        "Мера отвечает на вопрос владельца: интересны книги, которые "
        "приносят немного, но стабильно, и не забирают за один день "
        "прибыль недели. Главная колонка — **укус**: сколько обычных "
        "прибыльных дней съедает худший день. Отношение 10 проект уже "
        "называл терпимым (критерий 8 спеки 04), 40 — «год работы "
        "отдаётся за неделю».",
        "",
        "«Под водой» — сколько суток книга просидела ниже прошлого "
        "максимума: именно там видно, забрал ли один день прибыль "
        "недели, а не в глубине провала.",
        "",
        "**Укус читать только у книги с положительным обычным днём.** "
        "Он мерит форму «часто по копейке, редко по многу»; у книги, "
        "чья медиана дня отрицательна, он мал просто потому, что "
        "делить не на что — такая книга теряет не редким срывом, а "
        "каждый день. Поэтому таблица упорядочена по медиане дня, а "
        "не по укусу.",
        "",
        _table(live, lambda r: r.get("st"), "Живые книги", "money"),
        "",
        _table([c for c in cands if c.get("fwd")], lambda r: r["fwd"],
               "Кандидаты фабрики — форвард (со дня объявления)",
               "gross"),
        "",
        _table([c for c in cands if c.get("pre")], lambda r: r["pre"],
               "Кандидаты фабрики — бэктест (до объявления, пересчёт "
               "по уже виденному прошлому)", "gross"),
        "",
        "Бэктест и форвард НЕ складываются и стоят разными таблицами: "
        "до объявления это пересчёт по прошлому, которое ассистент "
        "видел, когда предлагал.",
        "",
    ]
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--key", default=None)
    ap.add_argument("--tag", default="live")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    key = a.key
    if not key:
        with open(TOKEN, encoding="utf-8") as f:
            key = f.read().strip()
    os.makedirs(OUT, exist_ok=True)
    core = [b["key"] for b in BK.REGISTRY]
    cands = cand_rows(a.base, key)
    live = live_rows(a.base, key, core + [c["key"] for c in cands])
    at = time.time()
    path = os.path.join(OUT, f"STABILITY-{a.tag}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report(live, cands, a.base, at))
    with open(os.path.join(OUT, f"stability-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"at": at, "live": live, "cands": cands}, f,
                  ensure_ascii=False, indent=1)
    print(f"отчёт: {path}")
    if not a.no_publish:
        # Публикация — часть прогона: шаг, который можно забыть,
        # рано или поздно забывают (урок D1 и `width.py`).
        subprocess.run([os.path.join(RESEARCH, "..", "tools",
                                     "publish.sh"),
                        path, "устойчивость книг"], check=False)


if __name__ == "__main__":
    main()
