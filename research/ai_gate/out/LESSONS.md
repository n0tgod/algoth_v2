# Уроки судьи (спека 19 §11.4)

Посчитано 2026-10-21T07:00:03Z; случаев 145 (с разбором 145); пороги: всего ≥ 20, в половине ≥ 8, случайные того же размера не хуже в ≤ 10% из 400.

## Действующие (читает ветка ai_learn)

нет

## Предложенные, ждут данных

| правило | условие | подходит (1-я / 2-я) | результат: подходящие vs остальные (всего) | случайные не хуже (1-я / 2-я) | почему не принято |
|---|---|---|---|---|---|
| Skip shorts into a pump that is still accelerating: 4h move at least +10% and the last hour still up at least 1%. | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 5 / 12 | -17.0 % vs +3.6 % | 0.395 / 0.0 | подходящих 17 < 20 |
| Skip high-leverage shorts on names where the book already hit the floor in a large share of past positions. | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 4 / 10 | -35.6 % vs +5.2 % | 0.005 / 0.0 | подходящих 14 < 20 |
| Skip shorts where the Bybit crowd swung sharply short in 24h while price is still rising over 4h. | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 1 / 11 | -24.8 % vs +3.6 % | 0.812 / 0.0 | подходящих 12 < 20 |
| Skip 20x+ shorts on names already up 15% or more in 24h. | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 5 / 15 | -21.4 % vs +4.9 % | 0.82 / 0.0 | первая половина не держит |
| Skip 20x+ shorts on names whose last 4h is up 5% or more. | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 5 / 10 | -21.5 % vs +3.8 % | 0.715 / 0.0 | подходящих 15 < 20 |
| Skip shorts when the 1h bounce is strong (3% or more) and Bybit longs are below 0.45. | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 2 / 8 | -10.4 % vs +2.1 % | 0.41 / 0.135 | подходящих 10 < 20 |

## Отозванные

нет

