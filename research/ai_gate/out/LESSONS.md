# Уроки судьи (спека 19 §11.4)

Посчитано 2026-11-06T07:00:02Z; случаев 560 (с разбором 560); пороги: всего ≥ 20, в половине ≥ 8, случайные того же размера не хуже в ≤ 10% из 400.

## Действующие (читает ветка ai_learn)

| что | правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не лучше правила (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|---|
| не брать | Skip shorts into a pump that is still accelerating: 4h move at least +10% and the last hour still up at least 1%. | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 37 / 26 | -15.6 % vs +3.8 % | 0.0 / 0.055 | — |
| не брать | Skip high-leverage shorts on names where the book already hit the floor in a large share of past positions. | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 32 / 15 | -15.5 % vs +3.2 % | 0.0 / 0.398 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names already up 15% or more in 24h. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 46 / 16 | -11.5 % vs +3.2 % | 0.0 / 0.263 | вторая половина не держит |
| не брать | Skip shorts when the 1h bounce is strong (3% or more) and Bybit longs are below 0.45. | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 23 / 5 | -13.8 % vs +2.4 % | 0.003 / 0.133 | вторая половина не держит |
| не брать | Skip shorts into a pump that is still running hard: last hour up 3% or more and 4h up 5% or more, at any leverage. | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 31 / 19 | -14.3 % vs +3.2 % | 0.0 / 0.16 | вторая половина не держит |
| не брать | Skip 10x+ shorts on names up 20% or more in 24h when the book has already floored on a large share of past entries in that name. | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 26 / 7 | -21.8 % vs +3.1 % | 0.0 / 0.003 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names up 20% or more in 24h unless the last hour is already down at least 2%. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 26 / 8 | -18.8 % vs +2.9 % | 0.0 / 0.482 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names whose last 4h is up 5% or more. | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 36 / 14 | -8.9 % vs +2.6 % | 0.007 / 0.245 | вторая половина не держит |
| не брать | Skip shorts at 10x or more while the 4h move is at least +10% and the last hour is still not falling. | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 18 / 7 | -28.7 % vs +3.0 % | 0.0 / 0.698 | вторая половина не держит |
| не брать | Skip 20x+ shorts while the last hour is still up 2.5% or more, whatever the 4h move. | `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` | 17 / 6 | -36.6 % vs +3.3 % | 0.0 / 0.0 | вторая половина не держит |

## Предложенные, ждут данных

| что | правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не лучше правила (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|---|
| не брать | Skip shorts where the Bybit crowd swung sharply short in 24h while price is still rising over 4h. | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 27 / 5 | +4.3 % vs +1.5 % | 0.762 / 0.292 | первая половина не держит |
| не брать | Skip shorts where the Bybit crowd swung short by at least 10 points in 24h while the last hour is still up at least 1%. | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 33 / 8 | -1.3 % vs +1.8 % | 0.29 / 0.66 | первая половина не держит |
| брать | Take shorts on names up 30% or more in 24h when the 4h move is already flat or negative, so the pump is rolling over. | `book_rules.fav_bp <= 0 и price_moves_to_decision.24h_pct >= 30 и price_moves_to_decision.4h_pct <= 0` | 16 / 5 | +2.4 % vs +1.6 % | 0.5 / 0.278 | первая половина не держит |
| брать | Take shorts at 10x or less when the Bybit crowd swung short by 18 points or more in 24h but the 4h move is below +5%. | `derived.crowd_bybit_shift_24h <= -0.18 и price_moves_to_decision.4h_pct <= 5 и book_rules.lev <= 10` | 22 / 2 | +10.2 % vs +1.2 % | 0.098 / 0.762 | вторая половина не держит |
| не брать | Skip 10x+ shorts when the Bybit crowd is already heavily short (long share 0.36 or below) and the last hour is not falling. | `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` | 10 / 1 | -32.6 % vs +2.3 % | 0.0 / 0.122 | подходящих 11 < 20 |
| не брать | Skip longs on names already up 8% or more in 24h; the book should not chase a pump from the long side. | `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` | 11 / 10 | -14.5 % vs +2.2 % | 0.44 / 0.003 | первая половина не держит |
| не брать | Skip longs at 5x or more when the name is up in the last 24h. | `book_rules.fav_bp >= 0 и book_rules.lev >= 5 и price_moves_to_decision.24h_pct >= 3` | 1 / 4 | -73.8 % vs +2.3 % | 0.01 / 0.0 | подходящих 5 < 20 |
| брать | Take shorts at 10x or less when the Bybit crowd has collapsed to heavily short (long share 0.32 or below) after swinging short by 12 points or more in 24h. | `crowd_positioning.bybit.now <= 0.32 и derived.crowd_bybit_shift_24h <= -0.12 и book_rules.lev <= 10` | 17 / 3 | +13.6 % vs +1.2 % | 0.07 / 0.393 | вторая половина не держит |
| брать | Take shorts at 10x or less when both Bybit and Binance global crowds swung sharply short (Bybit shift of 18 points or more, Binance global long share 0.42 or below). | `derived.crowd_bybit_shift_24h <= -0.18 и crowd_positioning.bn_global.now <= 0.42 и book_rules.lev <= 10` | 16 / 0 | +16.0 % vs +1.2 % | 0.055 / None | подходящих 16 < 20 |

## Отозванные

нет

## Отклонено зря (исход базовой книги у входов, которые судья не взял)

Отклонено 59, из них вышли бы в плюс 32 (54 %); сумма на маржу всех -243.3 %, только плюсовых +646.1 %. Правило take принимается числом (см. выше), не этой таблицей.

| имя | вход UTC | было бы | выход | доводы тогда | разбор |
|---|---|--:|---|---|---|
| JCTUSDT | 2026-10-25 10:00 | +220.9 % | тейк | crowd_positioning: Bybit long ratio fell from 0.52 to 0.30 and Binance global from 0.64 to 0.39, so retail is crowded short; crowd_positioning.bn_top: top trade | wrong |
| JCTUSDT | 2026-10-25 13:00 | +69.2 % | тейк | crowd_positioning: Bybit ratio fell 0.49 to 0.29 and Binance global 0.63 to 0.40, so shorts are piling in; price_moves_to_decision: +41.6% 24h and +266% 7d para | unclear |
| JCTUSDT | 2026-10-25 09:00 | +46.2 % | тейк | crowd_positioning: bybit long ratio fell 0.54 to 0.30 and bn_global to 0.40, crowd heavily short; price_moves_to_decision: +15.5% in 1h and +99% in 24h, squeeze | right |
| JCTUSDT | 2026-10-25 03:00 | +44.6 % | срок | crowd_positioning: Bybit long share fell from 0.56 to 0.26 and Binance global from 0.66 to 0.38, so the crowd is heavily short; price_moves: +143% in 24h and +2 | right |
| PTBUSDT | 2026-10-23 13:00 | +44.6 % | тейк | exchange_events_since_72h: Binance delists PTBUSDT perp today, so forced short covering and thin liquidity; crowd_positioning: shorts dominate (bn_top 0.52, byb | wrong |
| MAGMAUSDT | 2026-10-23 01:00 | +34.2 % | срок | crowd_positioning: bybit long share fell 0.59->0.30, bn_global 0.62->0.32, crowd heavily short; price_moves_to_decision: +49.8% 24h, +118% 7d parabolic run, so  | wrong |
| JCTUSDT | 2026-10-25 04:00 | +33.3 % | срок | crowd_positioning: Bybit long ratio fell from 0.56 to 0.29 and Binance global to 0.39, so shorts are crowded; price_moves_to_decision: +132% in 24h and +215% in | unclear |
| HYPEUSDT | 2026-10-30 08:00 | +23.3 % | срок | Fresh structural bullish catalyst: ICE investing in and launching US Hyperliquid-based perps (theblock ICE/Trade[XYZ] item); Binance hack is driving a CEX-to-DE | unclear |
| HYPEUSDT | 2026-10-29 21:00 | +18.4 % | срок | Fresh coin-specific catalyst: ICE partnering with and investing in Trade[XYZ] to bring Hyperliquid perps to the US; news the price model cannot read; crowd_posi | unclear |
| PTBUSDT | 2026-10-23 12:00 | +17.0 % | тейк | exchange_events_since_72h: Binance delists the PTBUSDT perp today, which moves liquidity and short interest onto thinner venues where post-delisting squeezes ar | wrong |

