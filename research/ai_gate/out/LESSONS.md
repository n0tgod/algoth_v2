# Уроки судьи (спека 19 §11.4)

Посчитано 2026-11-20T07:00:02Z; случаев 877 (с разбором 877); пороги: всего ≥ 20, в половине ≥ 8, случайные того же размера не хуже в ≤ 10% из 400.

## Действующие (читает ветка ai_learn)

| что | правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не лучше правила (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|---|
| не брать | Skip shorts into a pump that is still accelerating: 4h move at least +10% and the last hour still up at least 1%. | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 55 / 35 | -11.0 % vs +3.9 % | 0.0 / 0.163 | вторая половина не держит |
| не брать | Skip high-leverage shorts on names where the book already hit the floor in a large share of past positions. | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 42 / 23 | -9.2 % vs +3.3 % | 0.0 / 0.917 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names already up 15% or more in 24h. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 58 / 25 | -5.4 % vs +3.2 % | 0.0 / 0.958 | вторая половина не держит |
| не брать | Skip shorts when the 1h bounce is strong (3% or more) and Bybit longs are below 0.45. | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 27 / 11 | -11.5 % vs +3.0 % | 0.005 / 0.172 | вторая половина не держит |
| не брать | Skip shorts into a pump that is still running hard: last hour up 3% or more and 4h up 5% or more, at any leverage. | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 46 / 24 | -9.4 % vs +3.4 % | 0.0 / 0.292 | вторая половина не держит |
| не брать | Skip 10x+ shorts on names up 20% or more in 24h when the book has already floored on a large share of past entries in that name. | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 31 / 11 | -19.3 % vs +3.5 % | 0.0 / 0.142 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names up 20% or more in 24h unless the last hour is already down at least 2%. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 31 / 19 | -6.7 % vs +2.9 % | 0.0 / 0.998 | вторая половина не держит |
| не брать | Skip 20x+ shorts on names whose last 4h is up 5% or more. | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 48 / 24 | -1.7 % vs +2.7 % | 0.003 / 0.973 | вторая половина не держит |
| не брать | Skip shorts at 10x or more while the 4h move is at least +10% and the last hour is still not falling. | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 24 / 15 | -17.6 % vs +3.3 % | 0.0 / 0.618 | вторая половина не держит |
| не брать | Skip 20x+ shorts while the last hour is still up 2.5% or more, whatever the 4h move. | `book_rules.lev >= 20 и book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 2.5` | 23 / 9 | -27.8 % vs +3.5 % | 0.0 / 0.177 | вторая половина не держит |
| брать | Take shorts on names up 20% or more in 24h when Binance global retail is heavily short (0.40 or below) but Binance top traders still lean long (0.55 or above). | `price_moves_to_decision.24h_pct >= 20 и crowd_positioning.bn_global.now <= 0.4 и crowd_positioning.bn_top.now >= 0.55` | 9 / 21 | +27.5 % vs +1.5 % | 0.003 / 0.025 | — |

## Предложенные, ждут данных

| что | правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не лучше правила (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|---|
| не брать | Skip shorts where the Bybit crowd swung sharply short in 24h while price is still rising over 4h. | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 29 / 17 | +1.3 % vs +2.4 % | 0.795 / 0.1 | первая половина не держит |
| не брать | Skip shorts where the Bybit crowd swung short by at least 10 points in 24h while the last hour is still up at least 1%. | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 37 / 18 | +0.6 % vs +2.5 % | 0.34 / 0.69 | первая половина не держит |
| брать | Take shorts on names up 30% or more in 24h when the 4h move is already flat or negative, so the pump is rolling over. | `book_rules.fav_bp <= 0 и price_moves_to_decision.24h_pct >= 30 и price_moves_to_decision.4h_pct <= 0` | 18 / 15 | +6.5 % vs +2.2 % | 0.405 / 0.165 | первая половина не держит |
| брать | Take shorts at 10x or less when the Bybit crowd swung short by 18 points or more in 24h but the 4h move is below +5%. | `derived.crowd_bybit_shift_24h <= -0.18 и price_moves_to_decision.4h_pct <= 5 и book_rules.lev <= 10` | 22 / 14 | +9.4 % vs +2.1 % | 0.04 / 0.35 | вторая половина не держит |
| не брать | Skip 10x+ shorts when the Bybit crowd is already heavily short (long share 0.36 or below) and the last hour is not falling. | `book_rules.lev >= 10 и crowd_positioning.bybit.now <= 0.36 и price_moves_to_decision.1h_pct >= 0` | 11 / 6 | -7.5 % vs +2.6 % | 0.0 / 0.978 | подходящих 17 < 20 |
| не брать | Skip longs on names already up 8% or more in 24h; the book should not chase a pump from the long side. | `book_rules.fav_bp >= 0 и price_moves_to_decision.24h_pct >= 8` | 19 / 6 | -9.9 % vs +2.7 % | 0.11 / 0.022 | первая половина не держит |
| не брать | Skip longs at 5x or more when the name is up in the last 24h. | `book_rules.fav_bp >= 0 и book_rules.lev >= 5 и price_moves_to_decision.24h_pct >= 3` | 3 / 3 | -60.7 % vs +2.8 % | 0.0 / 0.003 | подходящих 6 < 20 |
| брать | Take shorts at 10x or less when the Bybit crowd has collapsed to heavily short (long share 0.32 or below) after swinging short by 12 points or more in 24h. | `crowd_positioning.bybit.now <= 0.32 и derived.crowd_bybit_shift_24h <= -0.12 и book_rules.lev <= 10` | 20 / 4 | +12.7 % vs +2.1 % | 0.04 / 0.32 | вторая половина не держит |
| брать | Take shorts at 10x or less when both Bybit and Binance global crowds swung sharply short (Bybit shift of 18 points or more, Binance global long share 0.42 or below). | `derived.crowd_bybit_shift_24h <= -0.18 и crowd_positioning.bn_global.now <= 0.42 и book_rules.lev <= 10` | 16 / 4 | +14.7 % vs +2.1 % | 0.033 / 0.32 | вторая половина не держит |
| брать | Take shorts on names up 20% or more in 24h when Binance global retail has already swung heavily short (long share 0.40 or below) and the last 4h is no longer racing (4h move at most +8%). | `crowd_positioning.bn_global.now <= 0.4 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.4h_pct <= 8` | 22 / 17 | +10.7 % vs +2.0 % | 0.905 / 0.003 | первая половина не держит |
| брать | Take shorts when both Bybit and Binance global retail are heavily short (Bybit long share 0.34 or below, Binance global 0.40 or below) and the last hour is not spiking (1h move at most +3%). | `crowd_positioning.bybit.now <= 0.34 и crowd_positioning.bn_global.now <= 0.4 и price_moves_to_decision.1h_pct <= 3` | 42 / 16 | +9.6 % vs +1.8 % | 0.39 / 0.01 | первая половина не держит |
| брать | Take shorts when the Bybit crowd swung short by 7 points or more in 24h to a long share of 0.34 or below, while the 4h move is at most +8%. | `crowd_positioning.bybit.now <= 0.34 и derived.crowd_bybit_shift_24h <= -0.07 и price_moves_to_decision.4h_pct <= 8` | 30 / 19 | +6.0 % vs +2.1 % | 0.855 / 0.005 | первая половина не держит |
| не брать | Skip shorts while the last hour is still up 10% or more. | `price_moves_to_decision.1h_pct >= 10` | 7 / 12 | -15.6 % vs +2.8 % | 0.018 / 0.028 | подходящих 19 < 20 |
| брать | Take shorts when both Bybit and Binance global retail are heavily short (Bybit long share 0.34 or below, Binance global 0.40 or below) and the 4h move is at most +8%, so the pump is not still running. | `crowd_positioning.bybit.now <= 0.34 и crowd_positioning.bn_global.now <= 0.4 и price_moves_to_decision.4h_pct <= 8` | 34 / 18 | +8.2 % vs +2.0 % | 0.645 / 0.007 | первая половина не держит |
| не брать | Skip shorts on names already down 30% or more over 7 days when the last 4h is bouncing (flat or up). | `book_rules.fav_bp <= 0 и price_moves_to_decision.168h_pct <= -30 и price_moves_to_decision.4h_pct >= 0` | 20 / 22 | +1.7 % vs +2.4 % | 0.78 / 0.182 | первая половина не держит |
| не брать | Skip 20x+ shorts while both the last hour (+1% or more) and the last 4h (+1.5% or more) are still rising. | `book_rules.lev >= 20 и price_moves_to_decision.1h_pct >= 1 и price_moves_to_decision.4h_pct >= 1.5` | 25 / 16 | -19.6 % vs +3.4 % | 0.0 / 0.282 | вторая половина не держит |

## Отозванные

нет

## Отклонено зря (исход базовой книги у входов, которые судья не взял)

Отклонено 92, из них вышли бы в плюс 59 (64 %); сумма на маржу всех +398.4 %, только плюсовых +1368.6 %. Правило take принимается числом (см. выше), не этой таблицей.

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

## Учится ли ветка ai_learn у правил take

- «Take shorts on names up 20% or more in 24h when Binance global retail is heavily short (0.40 or below) but Binance top traders still lean long (0.55 or above).» (с 2026-11-20): подходящих входов судила 0, отклонила всё же 0

