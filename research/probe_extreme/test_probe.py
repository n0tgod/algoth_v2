#!/usr/bin/env python3
"""Проверки зонда крайности: мера, а не намерение.

Синтетика построена так, что ответ известен заранее: платит только
зашкал. Реализация, которая мешает корзины, теряет знак у шортов или
считает дыру записи нулевым ходом, обязана падать.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import probe as P                                          # noqa: E402

FAIL = []


def check(name, ok, note=""):
    print(("  ok   " if ok else "  ПАДЕНИЕ ") + name
          + ("" if ok else f": {note}"))
    if not ok:
        FAIL.append(name)


T0 = 1_786_000_000


class Bars:
    """Подставные бары: цена идёт за прогнозом ТОЛЬКО в час зашкала.

    Первая версия двигала зашкалившую монету всегда — и середина
    профиля подкрашивалась её обычными часами: тест проверял не
    ступеньку, а снос монеты. Дрейф включён в окно [час, час+66 мин]:
    нога зашкала забирает его целиком, соседний час цепляет минуты.
    """

    def __init__(self, drift_bp):
        self.drift = drift_bp        # sym -> (б.п./час, set(час))

    def bars(self, sym, t0, t1):
        out, px = [], 100.0
        t = int(t0 // 60) * 60
        rate, hours = self.drift.get(sym, (0.0, set()))
        while t <= t1:
            i = int((t - T0) // 3600)
            on = i in hours and (t - T0) - i * 3600 < 3960
            nxt = px * (1 + (rate / 66.0 if on else 0.0) / 1e4)
            out.append([t, px, max(px, nxt), min(px, nxt), nxt])
            px = nxt
            t += 60
        return out


def synth_sheets(path, hours=30, syms=12):
    """Журнал листов: у каждой монеты свой обычный прогноз, у двух —
    зашкал в части часов."""
    with open(path, "w", encoding="utf-8") as f:
        for i in range(hours):
            at = T0 + i * 3600
            rows = []
            for j in range(syms):
                sym = f"S{j}USDT"
                base = 10.0 + j            # у монет разный масштаб
                # Обычный прогноз дрожит вокруг базы: распределению
                # крайности нужно тело, а не точка — иначе квинтили
                # вырождаются в одну границу.
                fwd = base * (0.6 + ((i * 7 + j * 3) % 9) / 10.0)
                if j == 0 and i % 3 == 0:
                    fwd = base * 6         # зашкал лонга
                elif j == 1 and i % 3 == 1:
                    fwd = -base * 6        # зашкал шорта
                elif j % 2:
                    fwd = -fwd
                rows.append({"sym": sym, "fwd": fwd, "px": 100.0})
            f.write(json.dumps({
                "hour": f"2026-08-08-{i % 24:02d}",
                "written_at": at,
                "arms": {"gbm": rows}}) + "\n")


def drift_for(hours=30):
    """Дрейф ровно в часы зашкала той же схемы, что synth_sheets."""
    return {"S0USDT": (60.0, {i for i in range(hours) if i % 3 == 0}),
            "S1USDT": (-60.0, {i for i in range(hours) if i % 3 == 1})}


def run_synth():
    d = tempfile.mkdtemp()
    sp = os.path.join(d, "sheets.jsonl")
    synth_sheets(sp)
    return P.run([sp], root="", src=Bars(drift_for()),
                 log=lambda *a: None)


def main():
    art = run_synth()
    check("все ноги измерены",
          art["legs_measured"] == art["legs_total"],
          f"{art['legs_measured']} из {art['legs_total']}")

    pf = art["profiles"]["rel_1h"]["rows"]
    top, mid = pf[-1], pf[2]
    # У зашкала цена шла за прогнозом у обеих сторон: превышение
    # положительно; середина — ноль. Шорт, потерявший знак, дал бы
    # хвост около нуля (плюс лонга съелся бы минусом шорта).
    # Хвостовая корзина разбавлена обычными ногами у границы квинтиля
    # (зашкалов ~20 из 83) — среднее ждём не «60», а заметно выше
    # середины: проверяется ступенька, а не чистота корзины.
    check("зашкал платит на оси rel",
          top["n"] > 0 and top["mean_bp"] > 10
          and top["mean_bp"] - mid["mean_bp"] > 8, str((top, mid)))
    check("середина оси rel около нуля",
          mid["n"] > 0 and abs(mid["mean_bp"]) < 10, str(mid))
    check("в хвосте обе зашкаливавшие монеты",
          top["syms"] >= 2, str(top))
    check("колонка без лучшего имени посчитана",
          top.get("wo_top_mean_bp") is not None and top["wo_top_mean_bp"] > 0,
          str(top))
    check("чтение называет ступеньку",
          any("фильтр настоящий" in x and x.startswith("rel/1h")
              for x in art["reading"]),
          str(art["reading"]))
    # 4h-строки на этой синтетике не проверяются нарочно: окно в
    # четыре часа у соседних ног накрывает час зашкала, и их
    # «загрязнение» — свойство синтетики, а не зонда.

    # Ось raw на этой синтетике НЕ обязана видеть ступеньку так же
    # чисто: зашкал задан в разах от собственной шкалы монеты, и в сырых
    # б.п. монеты с крупной базой засоряют хвост. Требуется лишь, что
    # ось посчитана.
    check("контрольная ось raw посчитана",
          all(r.get("n") for r in art["profiles"]["raw_1h"]["rows"]),
          str(art["profiles"]["raw_1h"]["rows"]))

    # Дыра записи — пропуск, а не ноль: монета без баров теряет ноги
    # числом, корзины не разбавляются нулевыми ходами.
    class Holey(Bars):
        def bars(self, sym, t0, t1):
            if sym == "S0USDT":
                return []
            return super().bars(sym, t0, t1)

    d = tempfile.mkdtemp()
    sp = os.path.join(d, "sheets.jsonl")
    synth_sheets(sp)
    art2 = P.run([sp], root="", src=Holey(drift_for()),
                 log=lambda *a: None)
    check("дыра записи — пропуск, а не наблюдение",
          art2["legs_measured"] < art2["legs_total"],
          f"{art2['legs_measured']} из {art2['legs_total']}")

    # Обрыв записи ПОСРЕДИ горизонта: вход есть, выхода нет. Нога
    # обязана выпасть, а не получить нулевой ход — нулевой ход у
    # трети корзины выровнял бы профиль в ноль.
    class Cut(Bars):
        def bars(self, sym, t0, t1):
            return [b for b in super().bars(sym, t0, t1)
                    if b[0] <= T0 + int(4.5 * 3600)]

    d4 = tempfile.mkdtemp()
    sp4 = os.path.join(d4, "sheets.jsonl")
    synth_sheets(sp4, hours=6)
    art3 = P.run([sp4], root="", src=Cut(drift_for(6)),
                 log=lambda *a: None)
    check("обрыв посреди горизонта — нога выпала",
          art3["legs_measured"] == 4 * 12,
          f"{art3['legs_measured']} вместо 48")

    # Сечение из трёх измеренных ног — не фон: медиана трёх точек
    # назвала бы превышением что угодно (ловушка тонкого фона T1).
    d5 = tempfile.mkdtemp()
    sp5 = os.path.join(d5, "sheets.jsonl")
    synth_sheets(sp5, hours=6)
    with open(sp5, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "hour": "2026-08-09-10",
            "written_at": T0 + 40 * 3600,
            "arms": {"gbm": [
                {"sym": f"S{j}USDT", "fwd": 10.0, "px": 100.0}
                for j in range(3)]}}) + "\n")
    art4 = P.run([sp5], root="", src=Bars(drift_for(6)),
                 log=lambda *a: None)
    check("тонкое сечение фоном не служит",
          art4["legs_measured"] == art3["legs_total"],
          f"{art4['legs_measured']} при {art4['legs_total']} ногах")

    # Публикация — часть прогона, в обе стороны (урок width.py):
    # с флагом её нет, без флага она обязана случиться. Сам publish
    # подменяется — тест не вправе коммитить.
    import unittest.mock as um
    calls = []
    art_pre = run_synth()
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "d1_seconds"))
    import run_d1 as RD
    d3 = tempfile.mkdtemp()
    sp3 = os.path.join(d3, "sheets.jsonl")
    synth_sheets(sp3, hours=12)
    with um.patch.object(RD, "publish", lambda m: calls.append(m)), \
         um.patch.object(P, "run", lambda *a, **k: art_pre), \
         um.patch.object(P, "HERE", d3), \
         um.patch.object(sys, "argv",
                         ["probe.py", "--sheets", sp3, "--tag", "smoke",
                          "--no-publish"]):
        P.main()
    check("с --no-publish публикации нет", not calls, str(calls))
    with um.patch.object(RD, "publish", lambda m: calls.append(m)), \
         um.patch.object(P, "run", lambda *a, **k: art_pre), \
         um.patch.object(P, "HERE", d3), \
         um.patch.object(sys, "argv",
                         ["probe.py", "--sheets", sp3, "--tag", "smoke"]):
        P.main()
    check("без флага публикация случается",
          len(calls) == 1 and "smoke" in calls[0], str(calls))

    if FAIL:
        print(f"\nПАДЕНИЙ: {len(FAIL)} — " + ", ".join(FAIL))
        sys.exit(1)
    print("\nвсе проверки прошли")


if __name__ == "__main__":
    main()
