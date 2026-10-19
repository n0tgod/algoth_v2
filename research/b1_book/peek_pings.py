#!/usr/bin/env python3
"""Разрывы соединений сборщика по журналу `out/collect.log` (19.10).

Владелец: «иногда подвисает и не грузит открытый PnL». В состоянии
сборщика видно, что шарды массово рвутся по `ping/pong timed out` и в
моменте готово 358 книг из 798. Здесь — давно ли так: по каждому запуску
сборщика (счётчик секунд в начале строки обнуляется на перезапуске)
число таймаутов, закрытий и переподключений в час, и доля готовых книг
по минутной строке «книг готово N/M» — медиана и минимум. Последний
запуск — ещё и по часам. Только читает.
"""
import os
import re
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "out", "collect.log")
TS = re.compile(r"^\[\s*(\d+) с\]")
READY = re.compile(r"книг готово (\d+)/(\d+)")


def main():
    if not os.path.exists(LOG):
        print("журнала сборщика нет:", LOG)
        return 1
    end = os.path.getmtime(LOG)
    print(f"журнал {LOG}: {os.path.getsize(LOG) / 1e6:.0f} МБ, изменён "
          f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(end))} UTC")
    segs, cur, prev = [], None, -1
    with open(LOG, encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = TS.match(ln)
            if not m:
                continue
            t = int(m.group(1))
            # Потоки пишут вперемешку, и счётчик идёт назад на секунды;
            # перезапуск — откат больше чем на десять минут.
            if cur is None or t < prev - 600:
                cur = {"ping": 0, "close": 0, "reconn": 0, "ready": [], "t_end": 0,
                       "hours": {}}
                segs.append(cur)
            prev = max(prev, t) if cur["t_end"] else t
            cur["t_end"] = max(cur["t_end"], t)
            h = t // 3600
            hb = cur["hours"].setdefault(h, {"ping": 0, "close": 0, "ready": []})
            if "ping/pong timed out" in ln:
                cur["ping"] += 1
                hb["ping"] += 1
            elif "соединение закрыто" in ln:
                cur["close"] += 1
                hb["close"] += 1
            elif "переподключение через" in ln:
                cur["reconn"] += 1
            r = READY.search(ln)
            if r and int(r.group(2)):
                x = int(r.group(1)) / int(r.group(2))
                cur["ready"].append(x)
                hb["ready"].append(x)
    print(f"запусков в журнале: {len(segs)}; ниже последние 15, старые сверху")
    print("№  длит,ч  таймаут/ч  закрыт/ч  готово: медиана  минимум  доля минут <90%")
    for i, s in enumerate(segs[-15:]):
        hrs = max(s["t_end"] / 3600, 1e-9)
        rd = s["ready"]
        low = (sum(1 for x in rd if x < 0.9) / len(rd)) if rd else None
        print(f"{len(segs) - 15 + i if len(segs) > 15 else i:>3} {hrs:6.1f} {s['ping'] / hrs:10.1f} "
              f"{s['close'] / hrs:9.1f} "
              f"{(st.median(rd) if rd else float('nan')):15.2f} "
              f"{(min(rd) if rd else float('nan')):8.2f} "
              f"{(low if low is not None else float('nan')):12.2f}")
    if segs:
        s = segs[-1]
        start = end - s["t_end"]
        print("\nпоследний запуск по часам (UTC; начало по времени файла):")
        for h in sorted(s["hours"]):
            hb = s["hours"][h]
            rd = hb["ready"]
            print(f"  {time.strftime('%m-%d %H:%M', time.gmtime(start + h * 3600))}  "
                  f"таймаутов {hb['ping']:4d}  закрытий {hb['close']:4d}  "
                  f"готово медиана {st.median(rd) if rd else float('nan'):.2f} "
                  f"мин {min(rd) if rd else float('nan'):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
