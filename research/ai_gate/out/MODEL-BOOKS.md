# Книги, которые заводит модель (спека 19 §12)

Посчитано 2026-11-27T07:30:12Z; живых 2 из 10; порог рождения мягкий (≥ 10 случаев, случайные не хуже ≤ 20 %); новых ≤ 2 за 7 суток; отставка — 10 суток в минусе и ниже основной книги (с 10.11) или 30 суток простоя. Только бумага.

| книга | вид | правило | с рождения, сут | позиций | итог $10k | основная на том же окне | нуль книги | статус |
|---|---|---|---|---|---|---|---|---|
| m01 | ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 36.98 | 68 | -0.08 % | -0.68 % | -0.24 % | отставлена: за 10 суток +153.58 $ против основной книги +225.20 $ (ячейка $10000) |
| m02 | ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 36.98 | 78 | +0.04 % | -0.68 % | -3.32 % | отставлена: за 10 суток +181.59 $ против основной книги +225.20 $ (ячейка $10000) |
| m03 | ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 29.94 | 14 | -0.34 % | +3.87 % | -0.38 % | отставлена: за 10 суток -34.40 $ против основной книги +319.38 $ (ячейка $10000) |
| m04 | фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 29.94 | 218 | +2.80 % | +3.87 % | +3.09 % (не хуже 0.65) | отставлена: за 10 суток +271.57 $ против основной книги +319.38 $ (ячейка $10000) |
| m05 | ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 21.94 | 86 | +1.04 % | +0.26 % | -5.15 % | отставлена: за 10 суток -4.06 $ — в минусе и ниже основной книги +532.36 $ (ячейка $10000) |
| m06 | ТВХ | `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 21.94 | 78 | -0.93 % | +0.26 % | -5.78 % | отставлена: за 10 суток -125.98 $ — в минусе и ниже основной книги +532.36 $ (ячейка $10000) |
| m07 | ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч` | 13.94 | 113 | -0.82 % | -1.83 % | -6.84 % | отставлена: за 10 суток -37.89 $ — в минусе и ниже основной книги +157.48 $ (ячейка $10000) |
| m08 | фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 13.94 | 195 | -0.42 % | -1.83 % | +0.06 % (не хуже 0.75) | отставлена: за 10 суток -17.39 $ — в минусе и ниже основной книги +157.48 $ (ячейка $10000) |
| m09 | ТВХ | `px_1h >= 0.004 и crowd_bybit_shift <= -0.03 и buy_share <= 0.5, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` | 6.9 | 43 | -2.40 % | -1.81 % | -3.22 % | живая |
| m10 | ТВХ | `funding >= 5e-05 и px_1h >= 0.005 и oi_1h >= 0.01, окно 4 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 6.9 | 78 | -1.26 % | -1.81 % | +0.04 % | живая |

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
- m07: Price has already squeezed up since the signal, but buying has faded (sellers dominate the tape). Shorting after the exhausted pop gives a better price and less room for a further run against us.
  · выход: `btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×2, плечо книги`
  · выход: `crowd_bn_top >= 0.58 и funding >= 5e-05 → стоп 1 %, тейк обещание ×3, равный риск`
  · выход: `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги`
- m08: If momentum has not rolled over by the entry hour, continuation squeezes tend to come before any fade. Shorts here often went straight to the floor or deep under water (JCT, BIRB, CT, CTR, BMT, XNY, BR).
- m09: Short into a small up-hour where the crowd has shifted short-to-long already (shorts squeezed out) but aggressive buying is not dominant: the bounce is exhausting, entering higher improves the price.
  · выход: `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск`
  · выход: `name_floor_share >= 0.105 и name_floor_share <= 0.256 и crowd_bn_top <= 0.533 → без стопа, тейк обещание ×3, плечо книги`
  · выход: `funding >= 5e-05 → стоп 1 %, тейк обещание ×2, равный риск`
- m10: Funding turned positive with fresh longs piling in on an up-hour: longs are crowded and paying. This is the late-long state that tends to unwind, so the short entered here should see small adverse excursion and allow a 3% stop.
  · выход: `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск`
  · выход: `name_floor_share >= 0.105 и name_floor_share <= 0.256 и crowd_bn_top <= 0.533 → без стопа, тейк обещание ×3, плечо книги`
  · выход: `funding >= 5e-05 → стоп 1 %, тейк обещание ×2, равный риск`

## Наблюдения недели и порог

| вид | правило | случаев | случайные не хуже | вердикт |
|---|---|---|---|---|
| фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 103 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 68 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 97 | 0.0 | проходит |
| фильтр | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 47 | 0.0 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 79 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 46 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 61 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 83 | 0.07 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 44 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` | 37 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.1h_pct >= 1 и price_moves_to_decision.4h_pct >= 1.5` | 48 | 0.0 | проходит |
| фильтр | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 49 | 0.215 | случайные не хуже в 0.215 > 0.2 |
| фильтр | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 64 | 0.037 | проходит |
| фильтр | `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` | 18 | 0.075 | проходит |
| фильтр | `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` | 26 | 0.022 | проходит |
| фильтр | `book_rules.fav_bp >= 0 и book_rules.lev >= 5 и price_moves_to_decision.24h_pct >= 3` | 8 | 0.0 | подходящих 8 < 10 |
| фильтр | `price_moves_to_decision.1h_pct >= 10` | 21 | 0.0 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и price_moves_to_decision.168h_pct <= -30 и price_moves_to_decision.4h_pct >= 0` | 46 | 0.537 | подходящие не хуже остальных |
| фильтр | `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 5` | 29 | 0.02 | проходит |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` | 318 | 0.1425 | проходит |
| ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 742 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 489 | 0.0325 | проходит |
| ТВХ | `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` | 119 | 0.01 | проходит |
| ТВХ | `funding >= 0.0001 и since_signal >= 0, окно 6 ч` | 366 | 0.105 | проходит |
| ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 176 | 0.72 | случайный час не хуже в 0.72 > 0.2 |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 184 | 0.0 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h >= 0.01 и trades_ratio <= 1, окно 4 ч` | 138 | 0.2875 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit >= 0.6 и oi_1h <= -0.02 и px_1h <= 0, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 740 | 0.895 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 750 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 199 | 0.2 | проходит |
| ТВХ | `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 516 | 0.0 | проходит |
| ТВХ | `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` | 605 | 0.0 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h <= 0 и crowd_bybit >= 0.55, окно 4 ч` | 172 | 0.5725 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч` | 750 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.01 и px_1h >= 0, окно 4 ч; стоп 3 %, тейк обещание ×2, равный риск` | 410 | 0.415 | в час правила не лучше, чем в час сигнала |
| ТВХ | `burst_ratio <= 0.5 и px_4h >= 0.03, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 354 | 0.0 | проходит |
| ТВХ | `crowd_bybit_shift >= 0.03 и btc_1h <= 0, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 591 | 0.0 | в час правила не лучше, чем в час сигнала |
| ТВХ | `funding >= 0.0001 и crowd_bybit >= 0.55, окно 6 ч; стоп 5 %, тейк обещание ×2, равный риск` | 265 | 0.0125 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.025 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 355 | 0.0 | проходит |
| ТВХ | `px_1h >= 0.01 и oi_1h <= -0.015, окно 6 ч; стоп 3 %, тейк обещание ×3, равный риск` | 230 | 0.0275 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit >= 0.6 и burst_ratio <= 0.6 и since_signal >= 0, окно 5 ч; стоп 2 %, тейк обещание ×2, равный риск` | 207 | 0.9975 | в час правила не лучше, чем в час сигнала |
| ТВХ | `funding >= 0.0001 и px_4h >= 0.03 и btc_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 191 | 0.55 | случайный час не хуже в 0.55 > 0.2 |
| ТВХ | `since_signal >= 0.03 и oi_1h <= -0.02 и buy_share <= 0.5, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 124 | 0.61 | случайный час не хуже в 0.61 > 0.2 |
| ТВХ | `px_1h >= 0.015 и burst_ratio <= 0.6 и btc_1h <= 0, окно 6 ч` | 507 | 0.905 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit_shift >= 0.03 и px_1h <= 0, окно 4 ч; стоп 3 %, тейк обещание ×3, равный риск` | 405 | 0.11 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и funding >= 0.0001 и oi_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 95 | 0.0225 | проходит |
| ТВХ | `px_4h >= 0.04 и trades_ratio <= 0.8 и btc_4h <= 0.002, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 444 | 0.5275 | в час правила не лучше, чем в час сигнала |
| ТВХ | `burst_ratio >= 2 и px_1h >= 0.01 и oi_1h <= -0.005, окно 4 ч` | 92 | 0.5775 | случайный час не хуже в 0.5775 > 0.2 |
| ТВХ | `since_signal >= 0.02 и oi_1h <= -0.01 и btc_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 366 | 0.0 | проходит |
| ТВХ | `funding >= 0.0001 и buy_share >= 0.55 и btc_1h <= 0, окно 5 ч; стоп 3 %, тейк обещание ×3, равный риск` | 77 | 1.0 | в час правила не лучше, чем в час сигнала |
| ТВХ | `px_1h >= 0.02 и trades_ratio <= 0.9 и crowd_bybit >= 0.55, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` | 535 | 0.0 | проходит |
| ТВХ | `crowd_bybit >= 0.55 и btc_4h <= -0.002 и buy_share >= 0.52, окно 6 ч; стоп 2 %, тейк обещание ×3, равный риск` | 308 | 0.715 | в час правила не лучше, чем в час сигнала |
| ТВХ | `px_1h >= 0.004 и crowd_bybit_shift <= -0.03 и buy_share <= 0.5, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` | 733 | 0.0 | проходит |
| ТВХ | `px_1h >= 0.004 и oi_1h <= -0.005 и btc_24h >= -0.0196, окно 6 ч` | 531 | 0.68 | случайный час не хуже в 0.68 > 0.2 |
| ТВХ | `since_signal >= 0.015 и burst_ratio <= 0.8 и trades_ratio <= 1, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 757 | 0.0 | проходит |
| ТВХ | `funding >= 5e-05 и px_1h >= 0.005 и oi_1h >= 0.01, окно 4 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 746 | 0.0325 | проходит |
| ТВХ | `oi_1h <= -0.02 и px_1h <= 0 и btc_4h >= -0.003, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 1663 | 0.54 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit_shift <= -0.05 и since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 163 | 0.0475 | проходит |
| ТВХ | `burst_ratio >= 2 и px_1h >= 0.015 и buy_share <= 0.5, окно 4 ч; стоп 3 %, тейк обещание ×3, плечо книги` | 270 | 0.1325 | проходит |
| ТВХ | `funding >= 5e-05 и oi_1h >= 0.02 и btc_1h <= 0, окно 6 ч; стоп 2 %, тейк обещание ×3, равный риск` | 146 | 0.315 | случайный час не хуже в 0.315 > 0.2 |
| выход | `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск` | 521 | 0.0075 | в ячейке не лучше, чем с выходом книги |
| выход | `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск` | 433 | 0.0875 | в ячейке не лучше, чем с выходом книги |
| выход | `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги` | 957 | 0.04 | в ячейке не лучше, чем с выходом книги |
| выход | `btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×2, плечо книги` | 1452 | 0.0 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.282 и spread_bp >= 7 → стоп 3 %, тейк обещание ×3, равный риск` | 195 | 0.0 | проходит |
| выход | `depth_eat_bid <= 220 и depth_eat_ask <= 221 → стоп 3 %, тейк обещание ×2, равный риск` | 396 | 0.1175 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.35 → стоп 2 %, тейк обещание ×3, равный риск` | 193 | 0.07 | в ячейке не лучше, чем с выходом книги |
| выход | `spread_bp >= 9 и btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×3, плечо книги` | 546 | 0.3075 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.282 и depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск` | 88 | 0.0 | проходит |
| выход | `depth_eat_bid <= 220 и crowd_bybit_shift >= -0.009 → стоп 3 %, тейк обещание ×2, равный риск` | 194 | 0.1325 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.4 → стоп 2 %, тейк обещание ×3, равный риск` | 148 | 0.14 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.282 и crowd_bybit >= 0.55 → стоп 3 %, тейк обещание ×3, равный риск` | 251 | 0.0 | проходит |
| выход | `crowd_bn_top >= 0.58 → стоп 2 %, тейк обещание ×3, равный риск` | 256 | 0.05 | в ячейке не лучше, чем с выходом книги |
| выход | `funding >= 5e-05 → стоп 1 %, тейк обещание ×2, равный риск` | 508 | 0.18 | в ячейке не лучше, чем с выходом книги |
| выход | `px_168h >= 0.38 → стоп 3 %, тейк обещание ×3, равный риск` | 288 | 1.0 | в ячейке не лучше, чем с выходом книги |
| выход | `oi_24h >= 0.25 и oi_24h <= 1 → стоп 5 %, тейк обещание ×1, равный риск` | 751 | 0.62 | в ячейке не лучше, чем с выходом книги |
| выход | `crowd_bn_top >= 0.58 и funding >= 5e-05 → стоп 1 %, тейк обещание ×3, равный риск` | 207 | 0.3875 | в ячейке не лучше, чем с выходом книги |
| выход | `btc_24h <= -0.0059 и spread_bp >= 8.7 → стоп 8 %, тейк обещание ×3, плечо книги` | 552 | 0.1175 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.105 и name_floor_share <= 0.256 и crowd_bn_top <= 0.533 → без стопа, тейк обещание ×3, плечо книги` | 299 | 0.0 | проходит |
| выход | `btc_dom <= 59.42 и signal_rr >= 1.05 → без стопа, тейк обещание ×3, плечо книги` | 706 | 0.215 | случайные не хуже в 0.215 > 0.2 |
| выход | `mcap_24h <= -3.2 и btc_24h <= -0.0059 → стоп 8 %, тейк обещание ×3, плечо книги` | 1238 | 0.0325 | в ячейке не лучше, чем с выходом книги |
| выход | `fng <= 28 → стоп 2 %, тейк обещание ×1, равный риск` | 541 | 0.0 | в ячейке не лучше, чем с выходом книги |
| выход | `funding >= 8e-06 → стоп 2 %, тейк обещание ×3, равный риск` | 277 | 0.015 | в ячейке не лучше, чем с выходом книги |
| выход | `fng <= 28 и funding >= 0 → стоп 2 %, тейк обещание ×2, равный риск` | 188 | 0.0 | проходит |
| выход | `name_floor_share >= 0.125 и name_floor_share <= 0.28 и depth_eat_ask >= 230 → без стопа, тейк обещание ×3, плечо книги` | 707 | 0.0 | проходит |
| выход | `crowd_bn_top <= 0.5285 и fng >= 28 → без стопа, тейк обещание ×3, плечо книги` | 344 | 0.0725 | проходит |
| закрытие | `oi_1h >= 0.03 и px_1h >= 0.02 и crowd_bybit_shift <= -0.05` | 674 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `btc_1h >= 0.004 и buy_share >= 0.6` | 333 | 0.995 | закрыть не лучше, чем держать |
| закрытие | `oi_1h >= 0.04 и btc_1h >= 0.004 и crowd_bybit_shift <= -0.08` | 67 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `since_signal >= 0.06 и oi_1h >= 0.02 и buy_share >= 0.55` | 167 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `crowd_bybit_shift <= -0.08 и btc_4h >= 0.006 и px_1h >= 0.01` | 160 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `name_floor_share >= 0.25 и px_1h >= 0.02` | 783 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `oi_1h >= 0.04 и buy_share >= 0.6 и name_floor_share >= 0.25` | 31 | 0.8375 | случайный час не хуже в 0.8375 > 0.2 |
| закрытие | `oi_1h >= 0.04 и buy_share >= 0.6 и px_1h >= 0.02` | 100 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `btc_1h >= 0.006 и px_1h >= 0.02 и oi_1h >= 0.03` | 115 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `name_floor_share >= 0.27 и oi_1h >= 0.02` | 592 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `name_floor_share >= 0.27 и btc_1h >= 0.004 и buy_share >= 0.55` | 99 | 0.99 | случайный час не хуже в 0.99 > 0.2 |

Прошли порог, ждут места: `since_signal >= 0.015 и burst_ratio <= 0.8 и trades_ratio <= 1, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `px_1h >= 0.02 и trades_ratio <= 0.9 и crowd_bybit >= 0.55, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.02 и oi_1h <= -0.01 и btc_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.025 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `burst_ratio <= 0.5 и px_4h >= 0.03, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.1h_pct >= 1 и price_moves_to_decision.4h_pct >= 1.5` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 10` — предел 2 новых за 7 суток; `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` — предел 2 новых за 7 суток; `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` — предел 2 новых за 7 суток; `since_signal >= 0.02 и funding >= 0.0001 и oi_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` — предел 2 новых за 7 суток; `crowd_bybit_shift <= -0.05 и since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `funding >= 0.0001 и since_signal >= 0, окно 6 ч` — предел 2 новых за 7 суток; `burst_ratio >= 2 и px_1h >= 0.015 и buy_share <= 0.5, окно 4 ч; стоп 3 %, тейк обещание ×3, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` — предел 2 новых за 7 суток; `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток
