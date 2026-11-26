# Книги, которые заводит модель (спека 19 §12)

Посчитано 2026-11-26T08:00:02Z; живых 2 из 10; порог рождения мягкий (≥ 10 случаев, случайные не хуже ≤ 20 %); новых ≤ 2 за 7 суток; отставка — 10 суток в минусе и ниже основной книги (с 10.11) или 30 суток простоя. Только бумага.

| книга | вид | правило | с рождения, сут | позиций | итог $10k | основная на том же окне | нуль книги | статус |
|---|---|---|---|---|---|---|---|---|
| m01 | ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 36.0 | 68 | -0.08 % | +0.53 % | -0.24 % | отставлена: за 10 суток +153.58 $ против основной книги +225.20 $ (ячейка $10000) |
| m02 | ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 36.0 | 78 | +0.04 % | +0.53 % | -3.32 % | отставлена: за 10 суток +181.59 $ против основной книги +225.20 $ (ячейка $10000) |
| m03 | ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 28.96 | 14 | -0.34 % | +5.11 % | -0.38 % | отставлена: за 10 суток -34.40 $ против основной книги +319.38 $ (ячейка $10000) |
| m04 | фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 28.96 | 218 | +2.80 % | +5.11 % | +3.09 % (не хуже 0.65) | отставлена: за 10 суток +271.57 $ против основной книги +319.38 $ (ячейка $10000) |
| m05 | ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 20.96 | 86 | +1.04 % | +1.44 % | -5.15 % | отставлена: за 10 суток -4.06 $ — в минусе и ниже основной книги +532.36 $ (ячейка $10000) |
| m06 | ТВХ | `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 20.96 | 78 | -0.93 % | +1.44 % | -5.78 % | отставлена: за 10 суток -125.98 $ — в минусе и ниже основной книги +532.36 $ (ячейка $10000) |
| m07 | ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч` | 12.96 | 113 | -0.82 % | -0.69 % | -6.84 % | отставлена: за 10 суток -37.89 $ — в минусе и ниже основной книги +157.48 $ (ячейка $10000) |
| m08 | фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 12.96 | 195 | -0.42 % | -0.69 % | +0.06 % (не хуже 0.75) | отставлена: за 10 суток -17.39 $ — в минусе и ниже основной книги +157.48 $ (ячейка $10000) |
| m09 | ТВХ | `px_1h >= 0.004 и crowd_bybit_shift <= -0.03 и buy_share <= 0.5, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` | 5.92 | 38 | -1.95 % | -0.69 % | -2.42 % | живая |
| m10 | ТВХ | `funding >= 5e-05 и px_1h >= 0.005 и oi_1h >= 0.01, окно 4 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 5.92 | 67 | -0.63 % | -0.69 % | +0.17 % | живая |

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
| фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 90 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 65 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 83 | 0.015 | проходит |
| фильтр | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 38 | 0.003 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 70 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 42 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 50 | 0.02 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 72 | 0.138 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 39 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` | 32 | 0.0 | проходит |
| фильтр | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 46 | 0.453 | случайные не хуже в 0.453 > 0.2 |
| фильтр | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 55 | 0.4 | случайные не хуже в 0.4 > 0.2 |
| фильтр | `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` | 17 | 0.107 | проходит |
| фильтр | `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` | 25 | 0.007 | проходит |
| фильтр | `book_rules.fav_bp >= 0 и book_rules.lev >= 5 и price_moves_to_decision.24h_pct >= 3` | 6 | 0.0 | подходящих 6 < 10 |
| фильтр | `price_moves_to_decision.1h_pct >= 10` | 19 | 0.007 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и price_moves_to_decision.168h_pct <= -30 и price_moves_to_decision.4h_pct >= 0` | 42 | 0.463 | случайные не хуже в 0.463 > 0.2 |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.1h_pct >= 1 и price_moves_to_decision.4h_pct >= 1.5` | 41 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` | 276 | 0.0525 | проходит |
| ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 842 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 506 | 0.02 | проходит |
| ТВХ | `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` | 94 | 0.0025 | проходит |
| ТВХ | `funding >= 0.0001 и since_signal >= 0, окно 6 ч` | 372 | 0.1025 | проходит |
| ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 172 | 0.7575 | случайный час не хуже в 0.7575 > 0.2 |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 140 | 0.0 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h >= 0.01 и trades_ratio <= 1, окно 4 ч` | 131 | 0.36 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit >= 0.6 и oi_1h <= -0.02 и px_1h <= 0, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 641 | 0.825 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 684 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 201 | 0.04 | проходит |
| ТВХ | `since_signal >= 0.01 и px_1h <= -0.01, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 539 | 0.0 | проходит |
| ТВХ | `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` | 528 | 0.02 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h <= 0 и crowd_bybit >= 0.55, окно 4 ч` | 155 | 0.5025 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и buy_share <= 0.48, окно 6 ч` | 684 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.01 и px_1h >= 0, окно 4 ч; стоп 3 %, тейк обещание ×2, равный риск` | 352 | 0.85 | в час правила не лучше, чем в час сигнала |
| ТВХ | `burst_ratio <= 0.5 и px_4h >= 0.03, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 302 | 0.0025 | проходит |
| ТВХ | `crowd_bybit_shift >= 0.03 и btc_1h <= 0, окно 5 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 523 | 0.0225 | в час правила не лучше, чем в час сигнала |
| ТВХ | `funding >= 0.0001 и crowd_bybit >= 0.55, окно 6 ч; стоп 5 %, тейк обещание ×2, равный риск` | 227 | 0.0 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.025 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 305 | 0.0 | проходит |
| ТВХ | `px_1h >= 0.01 и oi_1h <= -0.015, окно 6 ч; стоп 3 %, тейк обещание ×3, равный риск` | 177 | 0.0175 | проходит |
| ТВХ | `crowd_bybit >= 0.6 и burst_ratio <= 0.6 и since_signal >= 0, окно 5 ч; стоп 2 %, тейк обещание ×2, равный риск` | 160 | 0.9975 | в час правила не лучше, чем в час сигнала |
| ТВХ | `funding >= 0.0001 и px_4h >= 0.03 и btc_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 206 | 0.9125 | случайный час не хуже в 0.9125 > 0.2 |
| ТВХ | `since_signal >= 0.03 и oi_1h <= -0.02 и buy_share <= 0.5, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` | 121 | 0.3325 | случайный час не хуже в 0.3325 > 0.2 |
| ТВХ | `px_1h >= 0.015 и burst_ratio <= 0.6 и btc_1h <= 0, окно 6 ч` | 457 | 0.9075 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit_shift >= 0.03 и px_1h <= 0, окно 4 ч; стоп 3 %, тейк обещание ×3, равный риск` | 317 | 0.3975 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и funding >= 0.0001 и oi_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 103 | 0.24 | случайный час не хуже в 0.24 > 0.2 |
| ТВХ | `px_4h >= 0.04 и trades_ratio <= 0.8 и btc_4h <= 0.002, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 417 | 0.57 | случайный час не хуже в 0.57 > 0.2 |
| ТВХ | `burst_ratio >= 2 и px_1h >= 0.01 и oi_1h <= -0.005, окно 4 ч` | 80 | 0.9475 | в час правила не лучше, чем в час сигнала |
| ТВХ | `since_signal >= 0.02 и oi_1h <= -0.01 и btc_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 383 | 0.0025 | проходит |
| ТВХ | `funding >= 0.0001 и buy_share >= 0.55 и btc_1h <= 0, окно 5 ч; стоп 3 %, тейк обещание ×3, равный риск` | 70 | 0.9875 | в час правила не лучше, чем в час сигнала |
| ТВХ | `px_1h >= 0.02 и trades_ratio <= 0.9 и crowd_bybit >= 0.55, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` | 423 | 0.05 | проходит |
| ТВХ | `crowd_bybit >= 0.55 и btc_4h <= -0.002 и buy_share >= 0.52, окно 6 ч; стоп 2 %, тейк обещание ×3, равный риск` | 230 | 0.0625 | в час правила не лучше, чем в час сигнала |
| ТВХ | `px_1h >= 0.004 и crowd_bybit_shift <= -0.03 и buy_share <= 0.5, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` | 778 | 0.0 | проходит |
| ТВХ | `px_1h >= 0.004 и oi_1h <= -0.005 и btc_24h >= -0.0196, окно 6 ч` | 567 | 0.2425 | случайный час не хуже в 0.2425 > 0.2 |
| ТВХ | `since_signal >= 0.015 и burst_ratio <= 0.8 и trades_ratio <= 1, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 682 | 0.0 | проходит |
| ТВХ | `funding >= 5e-05 и px_1h >= 0.005 и oi_1h >= 0.01, окно 4 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 740 | 0.0 | проходит |
| выход | `name_floor_share >= 0.282 → стоп 3 %, тейк обещание ×3, равный риск` | 510 | 0.0 | проходит |
| выход | `depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск` | 399 | 0.015 | в ячейке не лучше, чем с выходом книги |
| выход | `spread_bp >= 9 → стоп 8 %, тейк обещание ×3, плечо книги` | 918 | 0.0225 | в ячейке не лучше, чем с выходом книги |
| выход | `btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×2, плечо книги` | 1262 | 0.0 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.282 и spread_bp >= 7 → стоп 3 %, тейк обещание ×3, равный риск` | 184 | 0.0025 | проходит |
| выход | `depth_eat_bid <= 220 и depth_eat_ask <= 221 → стоп 3 %, тейк обещание ×2, равный риск` | 363 | 0.045 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.35 → стоп 2 %, тейк обещание ×3, равный риск` | 217 | 0.01 | проходит |
| выход | `spread_bp >= 9 и btc_24h <= -0.0038 → стоп 8 %, тейк обещание ×3, плечо книги` | 488 | 0.3375 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.282 и depth_eat_bid <= 220 → стоп 3 %, тейк обещание ×2, равный риск` | 78 | 0.0025 | проходит |
| выход | `depth_eat_bid <= 220 и crowd_bybit_shift >= -0.009 → стоп 3 %, тейк обещание ×2, равный риск` | 167 | 0.045 | проходит |
| выход | `name_floor_share >= 0.4 → стоп 2 %, тейк обещание ×3, равный риск` | 170 | 0.0575 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.282 и crowd_bybit >= 0.55 → стоп 3 %, тейк обещание ×3, равный риск` | 183 | 0.065 | в ячейке не лучше, чем с выходом книги |
| выход | `crowd_bn_top >= 0.58 → стоп 2 %, тейк обещание ×3, равный риск` | 247 | 0.01 | проходит |
| выход | `funding >= 5e-05 → стоп 1 %, тейк обещание ×2, равный риск` | 384 | 0.0 | проходит |
| выход | `px_168h >= 0.38 → стоп 3 %, тейк обещание ×3, равный риск` | 326 | 0.9625 | в ячейке не лучше, чем с выходом книги |
| выход | `oi_24h >= 0.25 и oi_24h <= 1 → стоп 5 %, тейк обещание ×1, равный риск` | 757 | 0.0475 | в ячейке не лучше, чем с выходом книги |
| выход | `crowd_bn_top >= 0.58 и funding >= 5e-05 → стоп 1 %, тейк обещание ×3, равный риск` | 151 | 0.015 | проходит |
| выход | `btc_24h <= -0.0059 и spread_bp >= 8.7 → стоп 8 %, тейк обещание ×3, плечо книги` | 463 | 0.1725 | в ячейке не лучше, чем с выходом книги |
| выход | `name_floor_share >= 0.105 и name_floor_share <= 0.256 и crowd_bn_top <= 0.533 → без стопа, тейк обещание ×3, плечо книги` | 300 | 0.0 | проходит |
| выход | `btc_dom <= 59.42 и signal_rr >= 1.05 → без стопа, тейк обещание ×3, плечо книги` | 466 | 0.025 | проходит |
| выход | `mcap_24h <= -3.2 и btc_24h <= -0.0059 → стоп 8 %, тейк обещание ×3, плечо книги` | 953 | 0.0025 | проходит |
| закрытие | `oi_1h >= 0.03 и px_1h >= 0.02 и crowd_bybit_shift <= -0.05` | 794 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `btc_1h >= 0.004 и buy_share >= 0.6` | 242 | 0.9875 | закрыть не лучше, чем держать |
| закрытие | `oi_1h >= 0.04 и btc_1h >= 0.004 и crowd_bybit_shift <= -0.08` | 84 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `since_signal >= 0.06 и oi_1h >= 0.02 и buy_share >= 0.55` | 179 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `crowd_bybit_shift <= -0.08 и btc_4h >= 0.006 и px_1h >= 0.01` | 172 | 0.99 | случайный час не хуже в 0.99 > 0.2 |
| закрытие | `name_floor_share >= 0.25 и px_1h >= 0.02` | 856 | 1.0 | случайный час не хуже в 1.0 > 0.2 |
| закрытие | `oi_1h >= 0.04 и buy_share >= 0.6 и name_floor_share >= 0.25` | 29 | 0.2675 | случайный час не хуже в 0.2675 > 0.2 |
| закрытие | `oi_1h >= 0.04 и buy_share >= 0.6 и px_1h >= 0.02` | 97 | 1.0 | закрыть не лучше, чем держать |
| закрытие | `btc_1h >= 0.006 и px_1h >= 0.02 и oi_1h >= 0.03` | 98 | 0.9975 | случайный час не хуже в 0.9975 > 0.2 |

Прошли порог, ждут места: `since_signal >= 0.015 и burst_ratio <= 0.8 и trades_ratio <= 1, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.025 и buy_share <= 0.48, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.1h_pct >= 1 и price_moves_to_decision.4h_pct >= 1.5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` — предел 2 новых за 7 суток; `since_signal >= 0.02 и oi_1h <= -0.01 и btc_1h <= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `burst_ratio <= 0.5 и px_4h >= 0.03, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` — предел 2 новых за 7 суток; `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 10` — предел 2 новых за 7 суток; `px_1h >= 0.01 и oi_1h <= -0.015, окно 6 ч; стоп 3 %, тейк обещание ×3, равный риск` — предел 2 новых за 7 суток; `burst_ratio <= 0.5 и since_signal >= 0.015, окно 6 ч; стоп 8 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` — предел 2 новых за 7 суток; `since_signal >= 0.03 и oi_1h <= -0.02, окно 6 ч; стоп 3 %, тейк обещание ×2, равный риск` — предел 2 новых за 7 суток; `px_1h >= 0.02 и trades_ratio <= 0.9 и crowd_bybit >= 0.55, окно 6 ч; без стопа, тейк обещание ×3, плечо книги` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` — предел 2 новых за 7 суток; `funding >= 0.0001 и since_signal >= 0, окно 6 ч` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток
