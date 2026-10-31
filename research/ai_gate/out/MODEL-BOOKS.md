# Книги, которые заводит модель (спека 19 §12)

Посчитано 2026-10-31T08:00:02Z; живых 4 из 10; порог рождения мягкий (≥ 10 случаев, случайные не хуже ≤ 20 %); новых ≤ 2 за 7 суток; отставка — 10 суток ниже основной книги или 30 суток простоя. Только бумага.

| книга | вид | правило | с рождения, сут | позиций | итог $10k | основная на том же окне | нуль книги | статус |
|---|---|---|---|---|---|---|---|---|
| m01 | ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 10.0 | 47 | -0.79 % | -4.70 % | -1.41 % | живая |
| m02 | ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 10.0 | 55 | +0.75 % | -4.70 % | -2.23 % | живая |
| m03 | ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 2.96 | 5 | -0.20 % | -0.25 % | -0.47 % | живая |
| m04 | фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 2.96 | 49 | +0.54 % | -0.25 % | +0.21 % (не хуже 0.1) | живая |

**Группой:** лучше основной книги 4 из 4 живых с позициями; без эджа ожидается около половины — это не вердикт.

- m01: Shorts on Bybit have been covering (the crowd shifted long) while price rose. This marks a short squeeze that has already happened; the forced buying is done, leaving a better price to short with less squeeze fuel left.
  · выход: `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск`
  · выход: `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск`
  · выход: `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги`
- m02: Open interest is unwinding during a rise after the signal. The rally is driven by liquidations or covering rather than new longs, so it tends to exhaust; entering after the unwind avoids the straight_against paths.
  · выход: `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск`
  · выход: `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск`
  · выход: `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги`
- m03: Pump already happened (4h up >6%), buying burst has faded and OI is unwinding: late longs exiting, so shorting the exhausted top should lower adverse excursion versus entering at the signal hour.
  · выход: `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск`
  · выход: `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск`
  · выход: `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги`
- m04: Names after big 24h runs routinely swing 8-10% within hours. At 20x the floor sits inside that noise, so the floor tends to be hit before the fade arrives.

## Наблюдения недели и порог

| вид | правило | случаев | случайные не хуже | вердикт |
|---|---|---|---|---|
| фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 51 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 42 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 56 | 0.0 | проходит |
| фильтр | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 27 | 0.005 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 42 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 31 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 31 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 47 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 23 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` | 23 | 0.0 | проходит |
| фильтр | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 29 | 0.77 | подходящие не хуже остальных |
| фильтр | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 36 | 0.335 | случайные не хуже в 0.335 > 0.2 |
| фильтр | `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` | 11 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` | 273 | 0.005 | проходит |
| ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 1151 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 517 | 0.0 | проходит |
| ТВХ | `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` | 134 | 0.7425 | случайный час не хуже в 0.7425 > 0.2 |
| ТВХ | `funding >= 0.0001 и since_signal >= 0, окно 6 ч` | 666 | 0.0175 | проходит |
| ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 163 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 101 | 0.0075 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h >= 0.01 и trades_ratio <= 1, окно 4 ч` | 202 | 0.18 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit >= 0.6 и oi_1h <= -0.02 и px_1h <= 0, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 623 | 1.0 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 684 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 223 | 0.01 | проходит |
| ТВХ | `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 553 | 0.0 | проходит |
| ТВХ | `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` | 471 | 0.0 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h <= 0 и crowd_bybit >= 0.55, окно 4 ч` | 241 | 0.2425 | в час правила не лучше, чем в час сигнала |
| выход | `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск` | 533 | 0.0 | проходит |
| выход | `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск` | 477 | 0.0 | проходит |
| выход | `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги` | 941 | 0.0 | проходит |
| выход | `btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×2, плечо книги` | 928 | 0.005 | проходит |
| закрытие | `oi_1h >= 0.03 и px_1h >= 0.02 и crowd_bybit_shift <= -0.05` | 671 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `btc_1h >= 0.004 и buy_share >= 0.6` | 145 | 0.99 | закрыть не лучше, чем держать |

Прошли порог, ждут места: `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` — предел 2 новых за 7 суток; `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `funding >= 0.0001 и since_signal >= 0, окно 6 ч` — предел 2 новых за 7 суток
