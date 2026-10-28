# Уроки судьи (спека 19 §11.4)

Посчитано 2026-10-28T07:00:03Z; случаев 308 (с разбором 308); пороги: всего ≥ 20, в половине ≥ 8, случайные того же размера не хуже в ≤ 10% из 400.

## Действующие (читает ветка ai_learn)

| правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не хуже (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|
| Skip shorts into a pump that is still accelerating: 4h move at least +10% and the last hour still up at least 1%. | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 17 / 24 | -20.7 % vs +4.3 % | 0.0 / 0.0 | — |
| Skip high-leverage shorts on names where the book already hit the floor in a large share of past positions. | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 14 / 23 | -21.4 % vs +4.1 % | 0.0 / 0.05 | — |
| Skip 20x+ shorts on names already up 15% or more in 24h. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 19 / 31 | -15.4 % vs +4.2 % | 0.0 / 0.02 | — |
| Skip shorts when the 1h bounce is strong (3% or more) and Bybit longs are below 0.45. | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 11 / 14 | -14.8 % vs +2.4 % | 0.077 / 0.015 | — |
| Skip shorts into a pump that is still running hard: last hour up 3% or more and 4h up 5% or more, at any leverage. | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 15 / 20 | -18.5 % vs +3.5 % | 0.02 / 0.0 | — |
| Skip 10x+ shorts on names up 20% or more in 24h when the book has already floored on a large share of past entries in that name. | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 9 / 19 | -22.1 % vs +3.3 % | 0.0 / 0.028 | — |
| Skip 20x+ shorts on names up 20% or more in 24h unless the last hour is already down at least 2%. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 10 / 17 | -25.6 % vs +3.6 % | 0.0 / 0.003 | — |

## Предложенные, ждут данных

| правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не хуже (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|
| Skip shorts where the Bybit crowd swung sharply short in 24h while price is still rising over 4h. | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 13 / 14 | +6.0 % vs +0.5 % | 0.0 / 0.99 | вторая половина не держит |
| Skip 20x+ shorts on names whose last 4h is up 5% or more. | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 14 / 28 | -12.1 % vs +3.1 % | 0.0 / 0.11 | вторая половина не держит |
| Skip shorts at 10x or more while the 4h move is at least +10% and the last hour is still not falling. | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 7 / 12 | -42.4 % vs +3.9 % | 0.0 / 0.0 | подходящих 19 < 20 |
| Skip shorts where the Bybit crowd swung short by at least 10 points in 24h while the last hour is still up at least 1%. | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 19 / 15 | -2.5 % vs +1.5 % | 0.23 / 0.425 | первая половина не держит |

## Отозванные

нет

