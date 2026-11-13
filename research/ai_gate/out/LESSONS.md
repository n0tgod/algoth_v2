# Уроки судьи (спека 19 §11.4)

Посчитано 2026-11-13T07:00:02Z; случаев 726 (с разбором 726); пороги: всего ≥ 20, в половине ≥ 8, случайные того же размера не хуже в ≤ 10% из 400.

## Действующие (читает ветка ai_learn)

| что | правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не лучше правила (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|---|
| не брать | Skip shorts into a pump that is still accelerating: 4h move at least +10% and the last hour still up at least 1%. | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 48 / 28 | -15.6 % vs +4.5 % | 0.0 / 0.0 | — |
| не брать | Skip high-leverage shorts on names where the book already hit the floor in a large share of past positions. | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 38 / 22 | -10.9 % vs +3.6 % | 0.0 / 0.608 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names already up 15% or more in 24h. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 53 / 25 | -6.2 % vs +3.5 % | 0.0 / 0.905 | вторая половина не держит |
| не брать | Skip shorts when the 1h bounce is strong (3% or more) and Bybit longs are below 0.45. | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 27 / 4 | -14.6 % vs +3.2 % | 0.018 / 0.06 | вторая половина не держит |
| не брать | Skip shorts into a pump that is still running hard: last hour up 3% or more and 4h up 5% or more, at any leverage. | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 40 / 18 | -14.5 % vs +3.9 % | 0.0 / 0.0 | — |
| не брать | Skip 10x+ shorts on names up 20% or more in 24h when the book has already floored on a large share of past entries in that name. | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 28 / 12 | -18.1 % vs +3.6 % | 0.0 / 0.05 | — |
| не брать | Skip 20x+ shorts on names up 20% or more in 24h unless the last hour is already down at least 2%. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 28 / 17 | -8.3 % vs +3.1 % | 0.0 / 0.978 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names whose last 4h is up 5% or more. | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 45 / 20 | -3.7 % vs +3.0 % | 0.007 / 0.828 | вторая половина не держит |
| не брать | Skip shorts at 10x or more while the 4h move is at least +10% and the last hour is still not falling. | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 21 / 15 | -22.6 % vs +3.7 % | 0.0 / 0.01 | — |
| не брать | Skip 20x+ shorts while the last hour is still up 2.5% or more, whatever the 4h move. | `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` | 19 / 9 | -38.9 % vs +4.1 % | 0.0 / 0.0 | — |

## Предложенные, ждут данных

| что | правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не лучше правила (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|---|
| не брать | Skip shorts where the Bybit crowd swung sharply short in 24h while price is still rising over 4h. | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 29 / 11 | +0.1 % vs +2.6 % | 0.76 / 0.013 | первая половина не держит |
| не брать | Skip shorts where the Bybit crowd swung short by at least 10 points in 24h while the last hour is still up at least 1%. | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 36 / 11 | -0.1 % vs +2.6 % | 0.287 / 0.75 | первая половина не держит |
| брать | Take shorts on names up 30% or more in 24h when the 4h move is already flat or negative, so the pump is rolling over. | `book_rules.fav_bp <= 0 и price_moves_to_decision.24h_pct >= 30 и price_moves_to_decision.4h_pct <= 0` | 18 / 7 | +6.2 % vs +2.3 % | 0.45 / 0.07 | первая половина не держит |
| брать | Take shorts at 10x or less when the Bybit crowd swung short by 18 points or more in 24h but the 4h move is below +5%. | `derived.crowd_bybit_shift_24h <= -0.18 и price_moves_to_decision.4h_pct <= 5 и book_rules.lev <= 10` | 22 / 5 | +9.7 % vs +2.1 % | 0.085 / 0.552 | вторая половина не держит |
| не брать | Skip 10x+ shorts when the Bybit crowd is already heavily short (long share 0.36 or below) and the last hour is not falling. | `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` | 11 / 6 | -7.5 % vs +2.7 % | 0.0 / 0.983 | подходящих 17 < 20 |
| не брать | Skip longs on names already up 8% or more in 24h; the book should not chase a pump from the long side. | `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` | 18 / 4 | -15.0 % vs +3.0 % | 0.138 / 0.0 | первая половина не держит |
| не брать | Skip longs at 5x or more when the name is up in the last 24h. | `book_rules.fav_bp >= 0 и book_rules.lev >= 5 и price_moves_to_decision.24h_pct >= 3` | 3 / 2 | -73.8 % vs +2.9 % | 0.0 / 0.0 | подходящих 5 < 20 |
| брать | Take shorts at 10x or less when the Bybit crowd has collapsed to heavily short (long share 0.32 or below) after swinging short by 12 points or more in 24h. | `crowd_positioning.bybit.now <= 0.32 и derived.crowd_bybit_shift_24h <= -0.12 и book_rules.lev <= 10` | 20 / 2 | +12.3 % vs +2.1 % | 0.033 / 0.647 | вторая половина не держит |
| брать | Take shorts at 10x or less when both Bybit and Binance global crowds swung sharply short (Bybit shift of 18 points or more, Binance global long share 0.42 or below). | `derived.crowd_bybit_shift_24h <= -0.18 и crowd_positioning.bn_global.now <= 0.42 и book_rules.lev <= 10` | 16 / 3 | +14.7 % vs +2.1 % | 0.035 / 0.34 | подходящих 19 < 20 |
| брать | Take shorts on names up 20% or more in 24h when Binance global retail has already swung heavily short (long share 0.40 or below) and the last 4h is no longer racing (4h move at most +8%). | `crowd_positioning.bn_global.now <= 0.4 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.4h_pct <= 8` | 22 / 16 | +10.6 % vs +2.0 % | 0.873 / 0.003 | первая половина не держит |
| брать | Take shorts when both Bybit and Binance global retail are heavily short (Bybit long share 0.34 or below, Binance global 0.40 or below) and the last hour is not spiking (1h move at most +3%). | `crowd_positioning.bybit.now <= 0.34 и crowd_positioning.bn_global.now <= 0.4 и price_moves_to_decision.1h_pct <= 3` | 42 / 14 | +11.1 % vs +1.7 % | 0.4 / 0.0 | первая половина не держит |
| брать | Take shorts when the Bybit crowd swung short by 7 points or more in 24h to a long share of 0.34 or below, while the 4h move is at most +8%. | `crowd_positioning.bybit.now <= 0.34 и derived.crowd_bybit_shift_24h <= -0.07 и price_moves_to_decision.4h_pct <= 8` | 30 / 16 | +6.5 % vs +2.1 % | 0.855 / 0.003 | первая половина не держит |
| не брать | Skip shorts while the last hour is still up 10% or more. | `price_moves_to_decision.1h_pct >= 10` | 6 / 7 | -21.4 % vs +2.9 % | 0.007 / 0.013 | подходящих 13 < 20 |

## Отозванные

нет

## Отклонено зря (исход базовой книги у входов, которые судья не взял)

Отклонено 84, из них вышли бы в плюс 53 (63 %); сумма на маржу всех +357.3 %, только плюсовых +1287.9 %. Правило take принимается числом (см. выше), не этой таблицей.

| имя | вход UTC | было бы | выход | доводы тогда | разбор |
|---|---|--:|---|---|---|
| JCTUSDT | 2026-10-25 10:00 | +220.9 % | тейк | crowd_positioning: Bybit long ratio fell from 0.52 to 0.30 and Binance global from 0.64 to 0.39, so retail is crowded short; crowd_positioning.bn_top: top trade | wrong |
| PIEVERSEUSDT | 2026-11-10 08:00 | +89.7 % | срок | crowd_positioning: long/short ratios 0.33-0.35 on Bybit/Binance, shorts heavily crowded and growing; price_moves_to_decision: +28% 24h, +81% 7d, still rising (1 | wrong |
| PIEVERSEUSDT | 2026-11-10 07:00 | +80.2 % | срок | crowd_positioning: Bybit L/S 0.32 and Binance global 0.36, so accounts are heavily short; crowd_positioning: ratios fell sharply in 24h while price rose 28.7%,  | unclear |
| PIEVERSEUSDT | 2026-11-10 06:00 | +72.8 % | срок | crowd_positioning: long/short ratios very short-heavy (bybit 0.32, bn_global 0.35) and falling; price_moves_to_decision: +28.8% 24h, +72% 7d while shorts pile i | wrong |
| PIEVERSEUSDT | 2026-11-09 20:00 | +72.6 % | срок | crowd_positioning: Bybit L/S 0.32 and Binance global 0.36, falling fast, so shorts are crowded; price_moves_to_decision: +32% in 24h and +86% in 7d; crowded sho | wrong |
| JCTUSDT | 2026-10-25 13:00 | +69.2 % | тейк | crowd_positioning: Bybit ratio fell 0.49 to 0.29 and Binance global 0.63 to 0.40, so shorts are piling in; price_moves_to_decision: +41.6% 24h and +266% 7d para | unclear |
| PIEVERSEUSDT | 2026-11-10 01:00 | +55.8 % | срок | crowd_positioning: Bybit L/S 0.31 and BN global 0.36, heavily short-crowded and getting more so; price_moves_to_decision: +40% 24h and +84% 7d into crowded shor | wrong |
| PIEVERSEUSDT | 2026-11-10 04:00 | +55.4 % | срок | crowd_positioning: bybit L/S 0.30, bn_global 0.35, shorts crowded and rising; price_moves_to_decision: +25% 24h, +72% 7d momentum against short, squeeze risk; n | unclear |
| PIEVERSEUSDT | 2026-11-10 03:00 | +52.7 % | срок | crowd_positioning: long/short ratios very low (bybit 0.30, bn_global 0.34), crowd heavily short; price_moves_to_decision: +39% 24h and still rising +1.7% 1h aga | unclear |
| JCTUSDT | 2026-10-25 09:00 | +46.2 % | тейк | crowd_positioning: bybit long ratio fell 0.54 to 0.30 and bn_global to 0.40, crowd heavily short; price_moves_to_decision: +15.5% in 1h and +99% in 24h, squeeze | right |

