# Книги, которые заводит модель (спека 19 §12)

Посчитано 2026-10-28T08:35:05Z; живых 4 из 10; порог рождения мягкий (≥ 10 случаев, случайные не хуже ≤ 20 %); новых ≤ 2 за 7 суток; отставка — 10 суток ниже основной книги или 30 суток простоя. Только бумага.

**Родились в этом проходе:** m03 (entry) — `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч`; m04 (skip) — `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15`

| книга | вид | правило | с рождения, сут | позиций | итог $10k | основная на том же окне | нуль книги | статус |
|---|---|---|---|---|---|---|---|---|
| m01 | ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 7.02 | 31 | -1.74 % | -4.08 % | -1.56 % | живая |
| m02 | ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 7.02 | 25 | +0.00 % | -4.08 % | -1.96 % | живая |

**Группой:** лучше основной книги 2 из 2 живых с позициями; без эджа ожидается около половины — это не вердикт.

- m01: Shorts on Bybit have been covering (the crowd shifted long) while price rose. This marks a short squeeze that has already happened; the forced buying is done, leaving a better price to short with less squeeze fuel left.
- m02: Open interest is unwinding during a rise after the signal. The rally is driven by liquidations or covering rather than new longs, so it tends to exhaust; entering after the unwind avoids the straight_against paths.

## Наблюдения недели и порог

| вид | правило | случаев | случайные не хуже | вердикт |
|---|---|---|---|---|
| фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 41 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 37 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 50 | 0.0 | проходит |
| фильтр | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 25 | 0.007 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` | 35 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` | 28 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` | 27 | 0.0 | проходит |
| фильтр | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 27 | 0.795 | подходящие не хуже остальных |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 42 | 0.003 | проходит |
| фильтр | `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` | 19 | 0.0 | проходит |
| фильтр | `book_rules.fav_bp <= 0 и derived.crowd_bybit_shift_24h <= -0.1 и price_moves_to_decision.1h_pct >= 1` | 34 | 0.292 | случайные не хуже в 0.292 > 0.2 |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` | 273 | 0.005 | проходит |
| ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 1151 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 517 | 0.0 | проходит |
| ТВХ | `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` | 134 | 0.7425 | случайный час не хуже в 0.7425 > 0.2 |
| ТВХ | `funding >= 0.0001 и since_signal >= 0, окно 6 ч` | 666 | 0.0175 | проходит |
| ТВХ | `px_4h >= 0.06 и burst_ratio <= 0.8 и oi_1h <= -0.01, окно 6 ч` | 163 | 0.0 | проходит |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` | 101 | 0.0075 | проходит |
| ТВХ | `funding >= 0.0001 и px_1h >= 0.01 и trades_ratio <= 1, окно 4 ч` | 202 | 0.18 | в час правила не лучше, чем в час сигнала |
| ТВХ | `crowd_bybit >= 0.6 и oi_1h <= -0.02 и px_1h <= 0, окно 6 ч; стоп 3 %, тейк обещание ×2, плечо книги` | 623 | 1.0 | в час правила не лучше, чем в час сигнала |

Прошли порог, ждут места: `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` — предел 2 новых за 7 суток; `book_rules.fav_bp <= 0 и price_moves_to_decision.1h_pct >= 3 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.24h_pct >= 20 и derived.name_floor_share >= 0.3` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 20 и price_moves_to_decision.1h_pct >= -2` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 0` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` — предел 2 новых за 7 суток; `since_signal >= 0.03 и buy_share <= 0.47 и crowd_bybit_shift >= 0, окно 6 ч; стоп 5 %, тейк обещание ×2, плечо книги` — предел 2 новых за 7 суток; `funding >= 0.0001 и since_signal >= 0, окно 6 ч` — предел 2 новых за 7 суток
