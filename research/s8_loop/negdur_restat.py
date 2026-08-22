#!/usr/bin/env python3
"""Переоценка сделок с отрицательной длительностью — седьмой дефект кассы.

Цикловые выходы ситуационных книг оценивались ценой закрытия
разбираемого часа, и позиция, открытая ПОЗЖЕ этого закрытия, получала
выход по цене из ПРОШЛОГО (ENSUSDT: бумага записала +363 б.п., которых
у сделки не было ни секунды). Правка цикла такие случаи впредь
исключает; этот замер отвечает на вопрос владельца «насколько поменяется
статистика»: каждый задетый выход переоценивается по реальной минутной
середине МОМЕНТА РЕШЕНИЯ (review_at) — той же цене, по которой закрывал
бы живой исполнитель.

Файлы книги НЕ переписываются: история — история, это замер, не правка.
Деньги пересчитываются по записанному размеру сделки; эффект второго
порядка (изменившийся pnl менял бы размер поздних входов через кассу)
не реплеится и назван в отчёте.

Запуск из песочницы (данные — по HTTP со страницы наблюдения, как
S9-sweep-remote; ключ в git не идёт):

    python3 research/s8_loop/negdur_restat.py --key <ключ> \
        [--base http://116.203.146.99] [--hz sit]
"""

import argparse
import json
import os
import statistics
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trades as TR  # noqa: E402

# Допуск поиска цены: свеча решения может отсутствовать (дыра записи),
# берём последнюю не старше десяти минут до решения — но НИКОГДА не
# старше входа: цена старше входа и есть дефект, который меряем.
TOL_SEC = 600


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def affected(rows):
    """Закрытые сделки, чей выход датирован РАНЬШЕ входа."""
    out = []
    for t in rows:
        if t.get("state") != "закрыта":
            continue
        op = t.get("opened_at")
        ex = None
        for e in t.get("exits") or []:
            ex = e.get("at")
        if op and ex and float(ex) < float(op):
            out.append(t)
    return out


def reprice(t, base, key):
    """Цена середины на момент решения (review_at) из записи сборщика.

    Нет цены в допуске — сделка не переоценивается и считается
    отдельным числом: выдумывать нечем (нет цены — нет измерения).
    """
    dec = t.get("review_at")
    if not dec:
        return None, "нет момента решения"
    dec = float(dec)
    url = (f"{base}/candles?k={key}&sym={t['sym']}"
           f"&hours=2&end={dec + 120:.0f}")
    try:
        cs = (_get(url) or {}).get("candles") or []
    except Exception as e:  # noqa: BLE001
        return None, f"свечи не пришли: {e}"[:60]
    best = None
    for c in cs:
        ts = float(c[0])
        if ts <= dec and (best is None or ts > best[0]):
            best = (ts, float(c[4]))
    if best is None or dec - best[0] > TOL_SEC:
        return None, "нет свечи в допуске"
    if best[0] < float(t["opened_at"]) - 60:
        return None, "свеча старше входа"
    return best[1], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://116.203.146.99")
    ap.add_argument("--key", required=True)
    ap.add_argument("--hz", default="sit")
    ap.add_argument("--out", default=os.path.join(
        HERE, "out", "negdur-restat-remote.md"))
    a = ap.parse_args()

    d = _get(f"{a.base}/model_trades?k={a.key}&hz={a.hz}")
    # Времена выходов несёт merged-представление (плоские rows отдают
    # exit_ts пустым) — статистика «было/стало» считается по нему же,
    # чтобы обе стороны сравнения стояли на одном основании.
    rows = d.get("merged") or d.get("rows") or []
    closed = [t for t in rows if t.get("state") == "закрыта"]
    bad = affected(rows)

    lines, sum_dpnl, flips = [], 0.0, 0
    old_nets = {id(t): t.get("net_bp") for t in closed}
    new_nets = dict(old_nets)
    repriced, skipped = 0, []
    for t in sorted(bad, key=lambda r: r.get("opened_at") or 0):
        px, why = reprice(t, a.base, a.key)
        entry = float(t.get("entry_px") or 0.0)
        if px is None or entry <= 0:
            skipped.append((t["sym"], t.get("tid"), why or "нет входа"))
            continue
        repriced += 1
        sgn = 1.0 if t["side"] == "long" else -1.0
        got_new = (px / entry - 1.0) * 1e4
        cost = float(t.get("cost_bp") or TR.ROUND_COST_BP)
        net_new = sgn * got_new - cost
        net_old = float(t.get("net_bp") or 0.0)
        size = float(t.get("size") or 0.0)
        dpnl = size * (net_new - net_old) / 1e4
        sum_dpnl += dpnl
        new_nets[id(t)] = net_new
        if (net_old > 0) != (net_new > 0):
            flips += 1
        gap = (float(t["opened_at"])
               - float((t["exits"] or [{}])[-1].get("at") or 0)) / 60
        lines.append(
            f"| {t['sym']} | {t.get('tid')} | {t.get('arm')} "
            f"| {gap:.0f} мин | {t.get('exit_reason')} "
            f"| {net_old:+.1f} | {net_new:+.1f} "
            f"| {net_new - net_old:+.1f} | {dpnl:+.2f} $ |")

    def stats(nets):
        vals = [v for v in nets.values() if v is not None]
        win = sum(1 for v in vals if v > 0) / len(vals) if vals else 0
        return (sum(vals), win, statistics.median(vals) if vals else 0)

    s_old, w_old, m_old = stats(old_nets)
    s_new, w_new, m_new = stats(new_nets)
    pnl_old = sum(float(t.get("pnl") or 0.0) for t in closed)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join([
            "# Переоценка выходов с отрицательной длительностью "
            "(седьмой дефект кассы) — удалённый замер",
            "",
            f"Книга `{a.hz}`, закрытых сделок {len(closed)}, из них "
            f"выход датирован раньше входа у **{len(bad)}** "
            f"({len(bad) / max(len(closed), 1) * 100:.1f} %). "
            f"Переоценено {repriced}, не переоценено {len(skipped)} "
            "(нет цены — нет измерения, не ноль).",
            "",
            "Каждый задетый выход переоценён по минутной середине "
            "МОМЕНТА РЕШЕНИЯ (`review_at`) из записи сборщика — той "
            "же цене, по которой закрывал бы живой исполнитель. "
            "Файлы книги не переписаны: это замер «что было бы при "
            "честных ценах», правка цикла такие случаи впредь "
            "исключает. Деньги — по записанному размеру сделки; "
            "эффект второго порядка (изменившийся pnl менял бы "
            "размеры поздних входов через кассу) не реплеится.",
            "",
            "## Итог по книге (все закрытые сделки)",
            "",
            "| мера | как записано | по честным ценам | Δ |",
            "|---|---|---|---|",
            f"| Σ нетто, б.п. | {s_old:+.0f} | {s_new:+.0f} "
            f"| {s_new - s_old:+.0f} |",
            f"| доля побед | {w_old * 100:.1f} % | {w_new * 100:.1f} % "
            f"| {(w_new - w_old) * 100:+.1f} п.п. |",
            f"| медиана нетто, б.п. | {m_old:+.1f} | {m_new:+.1f} "
            f"| {m_new - m_old:+.1f} |",
            f"| бумажный pnl, $ (≈) | {pnl_old:+.2f} "
            f"| {pnl_old + sum_dpnl:+.2f} | {sum_dpnl:+.2f} |",
            "",
            f"Перевернулся знак у {flips} сделок из {repriced} "
            "переоценённых.",
            "",
            "## Переоценённые сделки",
            "",
            "| имя | id | рука | выход раньше входа на | причина "
            "| нетто было | нетто честно | Δ, б.п. | Δ денег |",
            "|---|---|---|---|---|---|---|---|---|",
        ] + lines + ([
            "",
            "## Не переоценены",
            "",
        ] + [f"- {s} {t}: {w}" for s, t, w in skipped]
            if skipped else []) + [""]))
    print(f"отчёт: {a.out}")
    print(f"задето {len(bad)}, переоценено {repriced}, "
          f"Δ денег {sum_dpnl:+.2f} $, знак перевернулся у {flips}")


if __name__ == "__main__":
    main()
