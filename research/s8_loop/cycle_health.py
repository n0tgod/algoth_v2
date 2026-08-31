#!/usr/bin/env python3
"""Бюджет часового цикла: укладывается ли он в час и куда уходит время.

Повод (2026-08-31): живой манифест показал цикл 5304 с при часовом
такте — обучение 4137 с, оценка и канарейка 1067, — и пробуждение через
3301 с после закрытия часа. Неделю назад обучение занимало 1014 с. Один
манифест это СНИМОК: он говорит про последний час и молчит о том, когда
цикл перестал укладываться и растёт ли он с данными. Ряд есть только в
`train_log.jsonl` (строка на обучение), и этот замер читает его.

Почему это важно за пределами удобства: пока цикл длиннее часа, лист
сечения у сканера стареет, а цикловые выходы записываются позже своего
часа — и исполняет их живой X3 настоящими деньгами. Тот же зазор уже
стоил SCRTUSDT −3.2 % живьём при −0.11 % бумаги.

Что печатается и почему именно это:
- медиана и 90-й процентиль `cycle_sec` ПО СУТКАМ — один час ничего не
  говорит, а рост виден только рядом;
- доля циклов, не уложившихся в час, по суткам — это и есть мера
  «сколько времени лист был несвежим»;
- связь `cycle_sec` с числом сечений и имён: растёт с данными (лечится
  каденцией обучения) или скакнуло разом (лечится поиском причины);
- разбивка по шагам ИЗ МАНИФЕСТА последнего прогона — с оговоркой, что
  ряда по шагам не существует: журнал их не писал.

Замер, а не вердикт проекта: порогов гипотезы здесь нет, вывод
выводится из чисел и решает владелец.

Запуск на VPS:
  cd ~/algoth_v2 && .venv/bin/python research/s8_loop/cycle_health.py
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
HOUR = 3600.0
# В таблицу идут последние сутки: вся история — это сотни строк,
# и отчёт, который не читается, ничем не лучше отсутствующего.
DAYS_SHOWN = 14


def log_(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def median(vals):
    """Медиана, а не «средний по счёту элемент».

    `sorted(v)[n // 2]` на чётной длине берёт ВЕРХНЕЕ из двух средних.
    Этот дефект уже дважды ловился в проекте (страница исполнения и
    сетка часов склада), и оба раза он смещал числа в одну сторону.
    """
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def pct(vals, q):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[i]


def spearman(xs, ys):
    """Ранговая связь — своя, потому что модуль обязан быть stdlib.

    Замер зовут и с сервера, и из песочницы; тянуть numpy ради одной
    корреляции значило бы привязать диагностику цикла к окружению,
    которое у неё может отсутствовать."""
    pairs = [(a, b) for a, b in zip(xs, ys)
             if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            share = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = share
            i = j + 1
        return r

    ra = ranks([p[0] for p in pairs])
    rb = ranks([p[1] for p in pairs])
    ma = sum(ra) / n
    mb = sum(rb) / n
    num = sum((a - ma) * (b - mb) for a, b in zip(ra, rb))
    da = sum((a - ma) ** 2 for a in ra) ** 0.5
    db = sum((b - mb) ** 2 for b in rb) ** 0.5
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def read_log(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def day_of(row):
    """Сутки строки — по ЧАСУ СЕЧЕНИЯ (`hour`, вида ГГГГ-ММ-ДД-ЧЧ).

    Метка записи `at` в живом журнале идёт форматом `%m-%d %H:%M`, то
    есть БЕЗ ГОДА, и ключом календарного ряда быть не может: первый
    прогон на живом журнале дал 216 «суток» на 216 строк, потому что
    `at[:10]` резал минуты. Час сечения год несёт всегда.

    Расхождение между часом сечения и моментом записи равно длине
    цикла — ровно той величине, которую здесь и меряют, — поэтому у
    полуночных прогонов сутки могут отличаться на один. Это названо, а
    не спрятано: на суточной медиане один прогон не меняет ничего.
    """
    h = row.get("hour")
    if isinstance(h, str) and len(h) >= 10 and h[4] == "-":
        return h[:10]
    at = row.get("at")
    # ISO-метка (`ГГГГ-ММ-ДДTчч:мм`) годится; без года — нет.
    if isinstance(at, str) and len(at) >= 10 and at[4] == "-":
        return at[:10]
    return None


def by_day(rows):
    out = {}
    for r in rows:
        d = day_of(r)
        if d:
            out.setdefault(d, []).append(r)
    return out


def summarize(rows, man):
    days = by_day(rows)
    per_day = []
    for d in sorted(days):
        cs = [r.get("cycle_sec") for r in days[d]]
        cs = [c for c in cs if isinstance(c, (int, float))]
        if not cs:
            continue
        over = sum(1 for c in cs if c > HOUR)
        per_day.append({
            "day": d, "n": len(cs),
            "med": round(median(cs) or 0.0, 1),
            "p90": round(pct(cs, 0.9) or 0.0, 1),
            "over_hour": over,
            "over_share": round(over / len(cs), 3),
            "sections": median([r.get("sections") for r in days[d]]),
            "symbols": median([r.get("symbols") for r in days[d]])})
    cs = [r.get("cycle_sec") for r in rows]
    secs = [r.get("sections") for r in rows]
    first_over = next((p["day"] for p in per_day
                       if p["over_share"] >= 0.5), None)
    return {
        "cycles": len(rows),
        "per_day": per_day,
        "rho_sections": spearman(secs, cs),
        "rho_seq": spearman([r.get("seq") for r in rows], cs),
        "first_over_day": first_over,
        "steps_last": (man or {}).get("steps_sec"),
        "woke_last": (man or {}).get("woke_after_hour_sec"),
        "cycle_last": (man or {}).get("cycle_sec"),
        "sections_last": (man or {}).get("sections"),
    }


def verdict(s):
    """Вердиктовая фраза выводится ИЗ ЧИСЕЛ, а не стоит рядом с ними.

    Правило записано после того, как в отчёте склада фраза стояла
    литералом и противоречила собственному числу того же отчёта."""
    pd = s["per_day"]
    if not pd:
        return ("не измерено: журнал обучений пуст — здесь его нет "
                "или цикл ещё не писал строк")
    last = pd[-1]
    if last["over_share"] >= 0.5:
        w = (f"цикл НЕ укладывается в час: за {last['day']} "
             f"{last['over_hour']} из {last['n']} прогонов длиннее "
             f"часа, медиана {last['med']:.0f} с")
        if s["first_over_day"] and s["first_over_day"] != last["day"]:
            w += f"; так с {s['first_over_day']}"
        return w
    if last["over_hour"]:
        return (f"цикл укладывается в час не всегда: за {last['day']} "
                f"{last['over_hour']} из {last['n']} прогонов длиннее "
                f"часа")
    return (f"цикл укладывается в час: за {last['day']} медиана "
            f"{last['med']:.0f} с, ни одного прогона длиннее часа")


def fmt(v, spec=".1f", dash="—"):
    return dash if v is None else format(v, spec)


def write_report(path, s, meta):
    L = ["# Бюджет часового цикла\n"]
    L.append(f"Прогон {meta['when']} · строк журнала {s['cycles']} · "
             f"суток {len(s['per_day'])}\n")
    L.append(f"**Вывод (выведен из чисел): {verdict(s)}.**\n")
    L.append("Час — это 3600 с. Пока цикл длиннее, лист сечения у "
             "сканера стареет, а цикловые выходы записываются позже "
             "своего часа; исполняет их живой исполнитель настоящими "
             "деньгами (тот же зазор стоил SCRTUSDT −3.2 % живьём при "
             "−0.11 % бумаги).\n")
    L.append("| сутки | прогонов | медиана с | 90-й проц. | длиннее "
             "часа | доля | сечений | имён |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    shown = s["per_day"][-DAYS_SHOWN:]
    if len(s["per_day"]) > len(shown):
        L.append(f"| … | | | | | | | ранее {len(s['per_day']) - len(shown)} "
                 f"суток |")
    for p in shown:
        L.append(f"| {p['day']} | {p['n']} | {p['med']:.0f} | "
                 f"{p['p90']:.0f} | {p['over_hour']} | "
                 f"{p['over_share']:.2f} | {fmt(p['sections'], '.0f')} "
                 f"| {fmt(p['symbols'], '.0f')} |")
    L.append("\nРастёт ли цикл вместе с данными — ранговая связь "
             f"`cycle_sec` с числом сечений **{fmt(s['rho_sections'], '+.3f')}**, "
             f"с номером обучения **{fmt(s['rho_seq'], '+.3f')}**. Связь "
             "близкая к единице означает, что лечится каденцией "
             "обучения, а не поиском одного виноватого часа.\n")
    st = s["steps_last"] or {}
    if st:
        L.append("Разбивка последнего прогона по шагам (из манифеста; "
                 "**ряда по шагам не существует** — журнал обучений их "
                 "не писал, это снимок одного часа):\n")
        L.append("| шаг | секунд |")
        L.append("|---|--:|")
        for k, v in st.items():
            L.append(f"| {k} | {v:.0f} |")
        L.append(f"\nВесь цикл {fmt(s['cycle_last'], '.0f')} с, проснулся "
                 f"через {fmt(s['woke_last'], '.0f')} с после закрытия "
                 f"часа, сечений {fmt(s['sections_last'], '.0f')}.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def publish(msg):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), msg],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="бюджет часового цикла")
    ap.add_argument("--model-dir", default=os.path.join(
        HERE, "out", "model"))
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out or OUT, exist_ok=True)
    rows = read_log(os.path.join(a.model_dir, "train_log.jsonl"))
    man = None
    try:
        with open(os.path.join(a.model_dir, "manifest.json"),
                  encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        man = None
    # Ни журнала, ни манифеста — значит мы не на той машине, а не «цикл
    # пуст». Отчёт в этом случае НЕ пишется и не публикуется: прогон из
    # песочницы однажды уже затёр серверный отчёт пустым.
    if not rows and man is None:
        log_(f"ни журнала обучений, ни манифеста в {a.model_dir} — "
             f"это не та машина; отчёт не пишется")
        return 1
    s = summarize(rows, man)
    log_(f"строк {s['cycles']}, суток {len(s['per_day'])}: {verdict(s)}")
    meta = {"when": datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC")}
    base = a.out or OUT
    with open(os.path.join(base, f"cycle-health-{a.tag}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": s}, f, ensure_ascii=False,
                  indent=1)
    p = write_report(os.path.join(base, f"CYCLE-health-{a.tag}.md"),
                     s, meta)
    log_(f"отчёт: {p}")
    if not a.no_publish:
        publish("бюджет часового цикла")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
