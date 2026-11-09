# Книги, которые заводит модель (спека 19 §12)

Посчитано 2026-11-09T08:25:04Z; живых 2 из 10; порог рождения мягкий (≥ 10 случаев, случайные не хуже ≤ 20 %); новых ≤ 2 за 7 суток; отставка — 10 суток ниже основной книги или 30 суток простоя. Только бумага.

| книга | вид | правило | с рождения, сут | позиций | итог $10k | основная на том же окне | нуль книги | статус |
|---|---|---|---|---|---|---|---|---|
| m01 | ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 19.02 | 68 | -0.08 % | -2.41 % | -0.24 % | отставлена: за 10 суток +153.58 $ против основной книги +225.20 $ (ячейка $10000) |
| m02 | ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 19.02 | 78 | +0.04 % | -2.41 % | -3.32 % | отставлена: за 10 суток +181.59 $ против основной книги +225.20 $ (ячейка $10000) |
| m03 | ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 11.98 | 14 | -0.34 % | +2.09 % | -0.38 % | отставлена: за 10 суток -34.40 $ против основной книги +319.38 $ (ячейка $10000) |
| m04 | фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 11.98 | 216 | +2.79 % | +2.09 % | +2.97 % (не хуже 0.65) | отставлена: за 10 суток +271.57 $ против основной книги +319.38 $ (ячейка $10000) |
| m05 | ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 3.98 | 29 | -1.18 % | -1.44 % | -1.66 % | живая |
| m06 | ТВХ | `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 3.98 | 20 | -1.48 % | -1.44 % | -1.78 % | живая |

**Группой:** лучше основной книги 1 из 2 живых с позициями; без эджа ожидается около половины — это не вердикт.

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
- m05: Price has already squeezed at least 2% against the short since the signal, and aggressive buying has dropped below half of trades. Entering here means the adverse leg is behind us, which should shrink the further adverse excursion so a 5% stop can survive.
  · выход: `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск`
  · выход: `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск`
  · выход: `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги`
- m06: Price rose after the signal and then printed the first down hour of at least 1%. Entering on that rollover sells near a local high, after the 'against then for' move has started, which should lower the adverse excursion.
  · выход: `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск`
  · выход: `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск`
  · выход: `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги`

## Наблюдения недели и порог

| вид | правило | случаев | случайные не хуже | вердикт |
|---|---|---|---|---|
| фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 63 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 47 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 62 | 0.0 | проходит |
| фильтр | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 28 | 0.007 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 50 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 33 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 34 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 50 | 0.013 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 25 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` | 23 | 0.0 | проходит |
| фильтр | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 32 | 0.728 | подходящие не хуже остальных |
| фильтр | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 41 | 0.352 | случайные не хуже в 0.352 > 0.2 |
| фильтр | `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` | 11 | 0.0 | проходит |
| фильтр | `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` | 21 | 0.003 | проходит |
| фильтр | `book_rules.fav_bp >= 0 и book_rules.lev >= 5 и price_moves_to_decision.24h_pct >= 3` | 5 | 0.0 | подходящих 5 < 10 |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` | 334 | 0.03 | проходит |
| ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 1079 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 509 | 0.0 | проходит |
| ТВХ | `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` | 140 | 0.1325 | проходит |
| ТВХ | `funding >= 0.0001 и since_signal >= 0, окно 6 ч` | 534 | 0.0575 | проходит |
| ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 184 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 129 | 0.0025 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h >= 0.01 и trades_ratio <= 1, окно 4 ч` | 186 | 0.005 | проходит |
| ТВХ | `crowd_bybit >= 0.6 и oi_1h <= -0.02 и px_1h <= 0, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 629 | 0.7675 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 747 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 207 | 0.01 | проходит |
| ТВХ | `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 580 | 0.0 | проходит |
| ТВХ | `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` | 546 | 0.0025 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h <= 0 и crowd_bybit >= 0.55, окно 4 ч` | 127 | 0.8225 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч` | 747 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.01 и px_1h >= 0, окно 4 ч; стоп 3 %, тейк обещание ×2, равный риск` | 365 | 0.5675 | в час правила не лучше, чем в час сигнала |
| ТВХ | `burst_ratio <= 0.5 и px_4h >= 0.03, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 292 | 0.2275 | случайный час не хуже в 0.2275 > 0.2 |
| ТВХ | `crowd_bybit_shift >= 0.03 и btc_1h <= 0, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 609 | 0.0225 | в час правила не лучше, чем в час сигнала |
| ТВХ | `funding >= 0.0001 и crowd_bybit >= 0.55, окно 6 ч; стоп 5 %, тейк обещание ×2, равный риск` | 166 | 0.28 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.025 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 299 | 0.0 | проходит |
| ТВХ | `px_1h >= 0.01 и oi_1h <= -0.015, окно 6 ч; стоп 3 %, тейк обещание ×3, равный риск` | 174 | 0.0025 | проходит |
| ТВХ | `crowd_bybit >= 0.6 и burst_ratio <= 0.6 и since_signal >= 0, окно 5 ч; стоп 2 %, тейк обещание ×2, равный риск` | 125 | 0.22 | в час правила не лучше, чем в час сигнала |
| ТВХ | `funding >= 0.0001 и px_4h >= 0.03 и btc_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 281 | 1.0 | случайный час не хуже в 1.0 > 0.2 |
| ТВХ | `since_signal >= 0.03 и oi_1h <= -0.02 и buy_share <= 0.5, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 152 | 0.055 | проходит |
| ТВХ | `px_1h >= 0.015 и burst_ratio <= 0.6 и btc_1h <= 0, окно 6 ч` | 496 | 0.0 | проходит |
| ТВХ | `crowd_bybit_shift >= 0.03 и px_1h <= 0, окно 4 ч; стоп 3 %, тейк обещание ×3, равный риск` | 328 | 0.0 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и funding >= 0.0001 и oi_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 108 | 0.255 | случайный час не хуже в 0.255 > 0.2 |
| ТВХ | `px_4h >= 0.04 и trades_ratio <= 0.8 и btc_4h <= 0.002, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 378 | 0.0075 | проходит |
| выход | `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск` | 482 | 0.0 | проходит |
| выход | `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск` | 440 | 0.0125 | в ячейке не лучше, чем с выходом книги |
| выход | `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги` | 827 | 0.0 | проходит |
| выход | `btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×2, плечо книги` | 1104 | 0.0 | проходит |
| выход | `name_floor_share >= 0.282 и spread_bp >= 7 → стоп 3 %, тейк обещание ×3, равный риск` | 189 | 0.0 | проходит |
| выход | `depth_eat_bid <= 220 и depth_eat_ask <= 221 → стоп 3 %, тейк обещание ×2, равный риск` | 398 | 0.0025 | проходит |
| выход | `name_floor_share >= 0.35 → стоп 2 %, тейк обещание ×3, равный риск` | 249 | 0.0025 | проходит |
| выход | `spread_bp >= 9 и btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×3, плечо книги` | 351 | 0.315 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.282 и depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск` | 125 | 0.0 | проходит |
| выход | `depth_eat_bid <= 220 и crowd_bybit_shift >= -0.009 → стоп 3 %, тейк обещание ×2, равный риск` | 160 | 0.0725 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.4 → стоп 2 %, тейк обещание ×3, равный риск` | 193 | 0.0 | проходит |
| выход | `name_floor_share >= 0.282 и crowd_bybit >= 0.55 → стоп 3 %, тейк обещание ×3, равный риск` | 147 | 0.1875 | в ячейке не лучше, чем с выходом книги |
| закрытие | `oi_1h >= 0.03 и px_1h >= 0.02 и crowd_bybit_shift <= -0.05` | 791 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `btc_1h >= 0.004 и buy_share >= 0.6` | 167 | 0.9875 | закрыть не лучше, чем держать |
| закрытие | `oi_1h >= 0.04 и btc_1h >= 0.004 и crowd_bybit_shift <= -0.08` | 85 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `since_signal >= 0.06 и oi_1h >= 0.02 и buy_share >= 0.55` | 163 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `crowd_bybit_shift <= -0.08 и btc_4h >= 0.006 и px_1h >= 0.01` | 156 | 0.9975 | закрыть не лучше, чем держать |

Прошли порог, ждут места: `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч` — предел 2 новых за 7 суток; `px_1h >= 0.015 и burst_ratio <= 0.6 и btc_1h <= 0, окно 6 ч` — предел 2 новых за 7 суток; `since_signal >= 0.025 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` — предел 2 новых за 7 суток; `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `px_1h >= 0.01 и oi_1h <= -0.015, окно 6 ч; стоп 3 %, тейк обещание ×3, равный риск` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` — предел 2 новых за 7 суток; `funding >= 0.0001 и px_1h >= 0.01 и trades_ratio <= 1, окно 4 ч` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` — предел 2 новых за 7 суток; `px_4h >= 0.04 и trades_ratio <= 0.8 и btc_4h <= 0.002, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` — предел 2 новых за 7 суток; `since_signal >= 0.03 и oi_1h <= -0.02 и buy_share <= 0.5, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `funding >= 0.0001 и since_signal >= 0, окно 6 ч` — предел 2 новых за 7 суток; `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` — предел 2 новых за 7 суток
