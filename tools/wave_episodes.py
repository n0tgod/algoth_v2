"""Зонд: как часто рынок даёт волну, на которую смотрит охрана.

Для каждого часа записи — наибольшая волна прокси-имён (`wave.PROXY`) от
любого входа за предыдущие 24 ч (срок короткой позиции) к концу этого
часа. По порогам 1 / 1.5 / 2 / 3 / 4 / 6 % печатает: сколько часов и
сколько ЭПИЗОДОВ (часы ближе суток друг к другу — один эпизод) на всей
записи и вперёд с 13.09, с датами и пиком каждого эпизода; отдельно —
ход сквиза 09–10.08 по часам от входа с наибольшей волной. Ничего не
меняет; отчёт — `research/dca_paper/out/WAVE-episodes.md`.

    run tools/wave_episodes.py
"""
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "research", "dca_paper"))
import wave as WV                                             # noqa: E402

HOUR = 3600
START = "2026-08-04-00"
FWD = "2026-09-13-00"
THR = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
OUT = os.path.join(ROOT, "research", "dca_paper", "out", "WAVE-episodes.md")


def ts(h):
    return int(datetime.strptime(h, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc).timestamp())


def hh(t):
    return time.strftime("%Y-%m-%d-%H", time.gmtime(t))


def episodes(hours, gap=24 * HOUR):
    """Часы → эпизоды (начало, конец, пик, час пика)."""
    out = []
    for t, w in sorted(hours):
        if out and t - out[-1][1] <= gap:
            s, e, pk, pt = out[-1]
            out[-1] = (s, t, max(pk, w), pt if pk >= w else t)
        else:
            out.append((t, t, w, t))
    return out


def main():
    mkt = WV.Market(WV.Hours())
    t0, t_end = ts(START), int(time.time()) // HOUR * HOUR
    best = {}                                   # час → (наибольшая волна, её вход)
    hours_n = 0
    for t in range(t0 + 24 * HOUR, t_end + 1, HOUR):
        hours_n += 1
        mx, ms = None, None
        for k in range(1, 25):
            w = mkt.wave(t - k * HOUR, t)
            if w is not None and (mx is None or w > mx):
                mx, ms = w, t - k * HOUR
        if mx is not None:
            best[t] = (mx * 100.0, ms)
        if hours_n % 400 == 0:
            print(f"  … {hours_n} часов, {hh(t)}", flush=True)
    lines = [f"# Волны рынка по часам: как часто срабатывала бы охрана",
             "",
             f"Прокси {len(WV.PROXY)} имён (минимум {WV.MIN_PROXY}); часов с мерой "
             f"{len(best)} из {hours_n} ({hh(t0)} … {hh(t_end)}); волна — наибольшая от любого "
             f"входа за предыдущие 24 ч к концу часа. Эпизод — часы ближе суток друг к другу.",
             ""]
    print("\n".join(lines))
    for label, lo in (("Вся запись", t0), ("Вперёд с 13.09", ts(FWD))):
        lines += [f"## {label}", "", "| порог | часов ≥ порога | эпизодов | эпизоды (начало → конец, пик) |",
                  "|---|--:|--:|---|"]
        for thr in THR:
            hs = [(t, w) for t, (w, _s) in best.items() if t >= lo and w >= thr]
            eps = episodes(hs)
            desc = "; ".join(f"{hh(s)[5:]}→{hh(e)[5:]} {pk:+.1f} %" for s, e, pk, _ in eps[:12])
            if len(eps) > 12:
                desc += f"; … ещё {len(eps) - 12}"
            lines.append(f"| ≥ {thr:g} % | {len(hs)} | {len(eps)} | {desc or '—'} |")
        lines.append("")
    top = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:12]
    lines += ["## Самые большие волны (час конца, волна, вход)", ""]
    lines += [f"- {hh(t)}: {w:+.2f} % от входа {hh(s)}" for t, (w, s) in top]
    lines.append("")
    # сквиз 09–10.08: ход по часам от входа с наибольшей волной в эти дни
    sq = [(t, w, s) for t, (w, s) in best.items() if "2026-08-09" <= hh(t)[:10] <= "2026-08-11"]
    if sq:
        t_pk, w_pk, s_pk = max(sq, key=lambda x: x[1])
        lines += [f"## Сквиз 09–11.08: ход от входа {hh(s_pk)} (пик {w_pk:+.2f} % к {hh(t_pk)})", "",
                  "| часов от входа | волна |", "|--:|--:|"]
        for k in range(1, 25):
            w = mkt.wave(s_pk, s_pk + k * HOUR)
            lines.append(f"| {k} | {('—' if w is None else f'{w * 100:+.2f} %')} |")
        lines.append("")
    lines.append(f"Прогон {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}; часов без меры {mkt.wave_none}.")
    txt = "\n".join(lines)
    print(txt)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print("отчёт:", OUT)


if __name__ == "__main__":
    main()
