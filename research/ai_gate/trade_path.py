#!/usr/bin/env python3
"""Путь цены ВНУТРИ сделки числами (спека 19 §11.2, этап U0).

Владелец 20.10: судья должен «анализировать поведение цены внутри каждой
сделки, не только её результат». Здесь — меры этого поведения по минутным
барам записи, одним ядром для журнала, досье учащейся ветки и приложения.
Модели здесь нет; пороги формы объявлены константами ДО первого прогона и
не меняются по результатам.

Меры (все ходы — в долях цены входа; у шорта «против» = вверх):
* `mae` — худший ход против позиции, `mae_h` — через сколько часов он был,
  `mae_margin` — тот же ход на маржу (× плечо входа);
* `mfe` — лучший ход за позицию, `mfe_h`, `mfe_margin`;
* `first_touch` — что цена коснулась раньше: `take` (цель), `floor` (пол),
  `none` — ни того, ни другого до выхода; уровни — ТЕ ЖЕ, что у книги
  (`rules.levels_of`), вызывающий передаёт их числами;
* `shape` — форма пути по порогам `SHAPE_*`;
* `life_h`, `life_share` — часы до выхода и доля срока книги;
* `name_move`, `market_move` — ход имени и волна прокси-имён за время
  сделки (`wave.Market`), чтобы отличить свою дорогу от общего хода;
* `bars`, `gap_min` — сколько минут записи было и сколько минут без бара:
  путь по дырявой записи обязан это говорить, а не выглядеть гладким.
"""
HOUR = 3600.0
# Форма пути. «Сразу за»: ход против не больше трети хода за; «сразу
# против» — зеркально; иначе порядок крайностей решает, что было раньше.
SHAPE_STRAIGHT = 1.0 / 3.0
# Спайк: худший ход против достигнут не позже SPIKE_MIN минут от входа и
# он не меньше SPIKE_MULT × |итогового хода| — цена метнулась и вернулась.
SPIKE_MIN = 15
SPIKE_MULT = 2.0


def _dir(side):
    return -1.0 if str(side) == "short" else 1.0


def metrics(bars, side, entry_px, at, exit_ts, take_px=None, floor_px=None,
            lev=None, hold_h=None, name_move=None, market_move=None):
    """Меры пути по барам `[t, o, h, l, c, v]` в окне [at, exit_ts]."""
    e = float(entry_px)
    d = _dir(side)
    at, end = float(at), float(exit_ts)
    rows = [b for b in bars if at <= float(b[0]) <= end and float(b[2]) > 0 and float(b[3]) > 0]
    out = {"bars": len(rows), "gap_min": None, "mae": None, "mae_h": None, "mfe": None, "mfe_h": None,
           "mae_margin": None, "mfe_margin": None, "first_touch": None, "shape": None,
           "life_h": round((end - at) / HOUR, 2),
           "life_share": (round((end - at) / HOUR / float(hold_h), 3) if hold_h else None),
           "name_move": name_move, "market_move": market_move}
    if not rows or e <= 0:
        out["shape"] = "no_bars"
        return out
    span_min = int((end - at) // 60) + 1
    out["gap_min"] = max(0, span_min - len(rows))
    mae, mae_t, mfe, mfe_t = 0.0, None, 0.0, None
    touch_take, touch_floor = None, None
    for b in rows:
        t, hi, lo = float(b[0]), float(b[2]), float(b[3])
        # ход за позицию: у лонга — вверх (high), у шорта — вниз (low)
        fav = (hi / e - 1.0) if d > 0 else (1.0 - lo / e)
        adv = (1.0 - lo / e) if d > 0 else (hi / e - 1.0)
        if adv > mae:
            mae, mae_t = adv, t
        if fav > mfe:
            mfe, mfe_t = fav, t
        if take_px is not None and touch_take is None:
            if (d > 0 and hi >= float(take_px)) or (d < 0 and lo <= float(take_px)):
                touch_take = t
        if floor_px is not None and touch_floor is None:
            if (d > 0 and lo <= float(floor_px)) or (d < 0 and hi >= float(floor_px)):
                touch_floor = t
    out["mae"] = round(mae, 5)
    out["mfe"] = round(mfe, 5)
    out["mae_h"] = round((mae_t - at) / HOUR, 2) if mae_t is not None else None
    out["mfe_h"] = round((mfe_t - at) / HOUR, 2) if mfe_t is not None else None
    if lev:
        out["mae_margin"] = round(mae * float(lev), 4)
        out["mfe_margin"] = round(mfe * float(lev), 4)
    if touch_take is not None and (touch_floor is None or touch_take <= touch_floor):
        out["first_touch"] = "take"
    elif touch_floor is not None:
        out["first_touch"] = "floor"
    else:
        out["first_touch"] = "none"
    final = (float(rows[-1][4]) / e - 1.0) * d
    if mae_t is not None and (mae_t - at) <= SPIKE_MIN * 60 and mae > 0 and mae >= SPIKE_MULT * abs(final):
        out["shape"] = "spike_against"
    elif mae <= SHAPE_STRAIGHT * mfe and mfe > 0:
        out["shape"] = "straight_for"
    elif mfe <= SHAPE_STRAIGHT * mae and mae > 0:
        out["shape"] = "straight_against"
    elif mae_t is not None and mfe_t is not None and mae_t < mfe_t:
        out["shape"] = "against_then_for"
    elif mae_t is not None and mfe_t is not None:
        out["shape"] = "for_then_against"
    else:
        out["shape"] = "flat"
    out["final_move"] = round(final, 5)
    return out


SHAPE_RU = {"straight_for": "сразу за", "straight_against": "сразу против",
            "against_then_for": "сначала против, потом за", "for_then_against": "сначала за, потом против",
            "spike_against": "спайк против в первые минуты", "flat": "без хода", "no_bars": "баров нет"}
SHAPE_EN = {"straight_for": "straight in favour", "straight_against": "straight against",
            "against_then_for": "against, then in favour", "for_then_against": "in favour, then against",
            "spike_against": "spike against in the first minutes", "flat": "flat", "no_bars": "no bars"}


def words(m, lang="ru"):
    """Одной строкой для досье и приложения — из чисел, не рядом с ними."""
    if not m or m.get("shape") == "no_bars":
        return "путь не измерен: баров записи нет" if lang == "ru" else "path not measured: no recorded bars"
    sh = (SHAPE_RU if lang == "ru" else SHAPE_EN).get(m.get("shape"), str(m.get("shape")))
    pct = lambda v: f"{100 * v:.1f} %" if v is not None else ("—")                     # noqa: E731
    if lang == "ru":
        s = (f"{sh}; против до {pct(m.get('mae'))} через {m.get('mae_h')} ч, за до {pct(m.get('mfe'))} "
             f"через {m.get('mfe_h')} ч; раньше коснулась: "
             + {"take": "цели", "floor": "пола", "none": "ни цели, ни пола"}.get(m.get("first_touch"), "—")
             + f"; жила {m.get('life_h')} ч")
    else:
        s = (f"{sh}; against up to {pct(m.get('mae'))} after {m.get('mae_h')} h, in favour up to {pct(m.get('mfe'))} "
             f"after {m.get('mfe_h')} h; touched first: "
             + {"take": "target", "floor": "floor", "none": "neither"}.get(m.get("first_touch"), "—")
             + f"; lived {m.get('life_h')} h")
    if m.get("market_move") is not None:
        s += (f"; рынок за это время {pct(m['market_move'])}" if lang == "ru"
              else f"; market over the same hours {pct(m['market_move'])}")
    if m.get("gap_min"):
        s += (f"; без бара {m['gap_min']} мин" if lang == "ru" else f"; {m['gap_min']} min without a bar")
    return s
