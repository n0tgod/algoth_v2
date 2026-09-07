#!/usr/bin/env python3
"""D11 — DCA-лестница на сигнале книги `h24` (24 ч, рука по выбору), шорт.

Вопрос владельца 2026-09-07: «попробуй сделать DCA из этого источника
сигналов» — после разреза книг по стороне (`s8_loop/side_split.py`,
`side_wave.py`): единственный источник, у которого шорты в плюсе и в
кассе (остаток к волне), и сырым — 24-часовой сигнал руки nn.

Что здесь. Та же машинерия, что у D10 (сетка плечо {забор, ≤3×, ≤2×,
≤1×} × доливы {структурные, нет, σ-сетка} × цель {×1, ×2, ×3} = 36
ячеек на книгу, забор, пол капитуляции, нетто круга, половины, парная
Δ к правилу книги, ось гейта), но ноги — выборы книги `h24`
(`s8_loop/out/model_h24/picks.jsonl`, короткая сторона выбранной руки),
обещание `fav` и риск `adv_q` — поля `mfe`/`mae` выбора (они уже в
терминах позиции), момент решения — закрытие часа выбора (`hour_end`). Точка отсчёта — то же правило книги
(`fence:struct:t2`), но гейт отсчёта — «любой» (край ≥ 33 б.п.): у
24-часового сигнала гейт RR книги не правило, а ось.

Срок удержания — `--hold` (по умолчанию 72 ч, как у книги; 24 ч — срок
самого сигнала, отдельный прогон). Ситуационная короткая книга D9/D10
служит контролем: тот же реплей, другой источник ног.

Запуск на VPS:
  run research/dca_ladder/run_d11.py --arm nn
  run research/dca_ladder/run_d11.py --arm nn --hold 24
  run research/dca_ladder/run_d11.py --arm gbm
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(RESEARCH, "s8_loop"))
import run_d2 as D2                                           # noqa: E402
import run_d10 as D10                                         # noqa: E402
import trades as TR                                           # noqa: E402

OUT = os.path.join(HERE, "out")
PICKS = os.path.join(RESEARCH, "s8_loop", "out", "model_h24", "picks.jsonl")
REF_GATE = "any"                     # отсчёт — все решения с краем ≥ 33


def h24_legs(arm="nn", path=None, limit=None, log=print):
    """Короткие ноги из выборов книги h24 (рука `arm`).

    Строка выбора книги со сроком уже несёт `mae`/`mfe` В ТЕРМИНАХ
    ПОЗИЦИИ (`path_fields` применён при записи: `mae` — ход против, у
    шорта > 0; `mfe` — в пользу, у шорта < 0). Применять `_leg` турнира
    (он зовёт `path_fields` ещё раз) нельзя — двойное применение
    переставляет стороны у шорта обратно, и первый прогон пропустил 11
    ног из 1 722 ровно поэтому. Нога собирается прямо: обещание `fav` =
    `mfe`, риск `adv_q` = `mae`, RR = |fav| / риск, сторона — знак `fwd`,
    момент — закрытие часа выбора.
    """
    path = path or PICKS
    out, n_rows, n_hours, bad = [], 0, 0, 0
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        log(f"{path}: выборов нет")
        return []
    with fh:
        for line in fh:
            try:
                p = json.loads(line)
            except ValueError:
                continue
            if (p.get("arm") or "gbm") != arm or not p.get("hour"):
                continue
            at = TR.hour_end(p["hour"])
            if not at:
                continue
            n_hours += 1
            for row in p.get("short") or []:
                n_rows += 1
                try:
                    fwd = float(row["fwd"])
                    fav = float(row["mfe"])
                    adv = float(row["mae"])
                except (KeyError, TypeError, ValueError):
                    bad += 1
                    continue
                if not (fwd < 0 and fav < 0 < adv):
                    bad += 1
                    continue
                g = {"arm": arm, "sym": row.get("sym"), "hour": p["hour"],
                     "at": float(at), "side": "short", "fwd": fwd,
                     "fz": None, "adv_q": adv, "fav": fav, "rr": abs(fav) / adv}
                if D10.gate_of(g):
                    out.append(g)
    out.sort(key=lambda g: (g["at"], g["arm"], g["fwd"], g["sym"]))
    log(f"h24/{arm}: часов {n_hours}, коротких выборов {n_rows}, ног под краем "
        f"{len(out)}, отброшено (нет полей / знак) {bad}")
    return out[:limit] if limit else out


def configure(hold_h=None):
    """Отсчёт по гейту «любой»; срок — по аргументу. Возвращает, что было."""
    was = {"ref_gate": D10.REF_GATE, "cell_defaults": D10.cell.__defaults__,
           "hold": D2.HOLD_H}
    D10.REF_GATE = REF_GATE
    # умолчание аргумента связано при определении функции — меняется явно
    D10.cell.__defaults__ = (REF_GATE, False)
    if hold_h:
        D2.HOLD_H = int(hold_h)
    return was


def restore(was):
    D10.REF_GATE = was["ref_gate"]
    D10.cell.__defaults__ = was["cell_defaults"]
    D2.HOLD_H = was["hold"]


def run(arm="nn", hold_h=None, limit=None, src=None, log=print, legs=None):
    was = configure(hold_h)
    try:
        legs = legs if legs is not None else h24_legs(arm, limit=limit, log=log)
        s = D10.run(src=src, log=log, legs=legs)
        s["signal"] = {"book": "h24", "arm": arm, "picks": PICKS,
                       "hold_h": D2.HOLD_H, "ref_gate": REF_GATE,
                       "legs": len(legs)}
        return s
    finally:
        restore(was)


def report(s):
    sig = s.get("signal") or {}
    head = ["# D11 — DCA-лестница на сигнале h24 (шорт, рука "
            f"{sig.get('arm', '?')}, срок {sig.get('hold_h', '?')} ч)", "",
            "Вопрос владельца 2026-09-07: «попробуй сделать DCA из этого "
            "источника сигналов». Ноги — короткие выборы книги `h24` "
            f"(рука {sig.get('arm')}), {sig.get('legs')} решений под краем ≥ 33 "
            "б.п.; момент решения — закрытие часа выбора; обещание и риск — "
            "из `mae/mfe` выбора тем же `path_fields`, что у книги. Точка "
            f"отсчёта — правило книги `{s.get('ref')}` при гейте «{sig.get('ref_gate')}». "
            "Контроль — ситуационная короткая книга D10 (тот же реплей, другой "
            "источник ног): там плюса не дала ни одна ячейка.", "",
            "Ниже — отчёт той же формы, что D10 (заголовок D10 в нём — "
            "формой, не смыслом: сетка и правила чтения те же).", "", "---", ""]
    return "\n".join(head) + D10.report(s)


def publish(name):
    subprocess.run([os.path.join(ROOT, "tools", "publish.sh"), name],
                   cwd=ROOT, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="D11: DCA на сигнале h24, шорт")
    ap.add_argument("--arm", default="nn", choices=("nn", "gbm"))
    ap.add_argument("--hold", type=int, default=None, help="срок, ч (72)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="1m")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:                                     # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)
    s = run(arm=a.arm, hold_h=a.hold, limit=a.limit)
    tag = a.tag if not a.limit else f"smoke-{a.tag}"
    name = f"D11-h24-{a.arm}-h{s['signal']['hold_h']}-{tag}"
    with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    txt = report(s)
    with open(os.path.join(OUT, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    if not a.no_publish:
        publish(f"D11: DCA на сигнале h24/{a.arm}, срок {s['signal']['hold_h']} ч ({tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
