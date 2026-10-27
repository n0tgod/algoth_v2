# Книги, которые заводит модель (спека 19 §12)

Посчитано 2026-10-27T08:00:03Z; живых 2 из 10; порог рождения мягкий (≥ 10 случаев, случайные не хуже ≤ 20 %); новых ≤ 2 за 7 суток; отставка — 10 суток ниже основной книги или 30 суток простоя. Только бумага.

| книга | вид | правило | с рождения, сут | позиций | итог $10k | основная на том же окне | нуль книги | статус |
|---|---|---|---|---|---|---|---|---|
| m01 | ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 6.0 | 27 | -1.34 % | -3.55 % | -1.05 % | живая |
| m02 | ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 6.0 | 18 | -1.04 % | -3.55 % | -2.04 % | живая |

**Группой:** лучше основной книги 2 из 2 живых с позициями; без эджа ожидается около половины — это не вердикт.

- m01: Shorts on Bybit have been covering (the crowd shifted long) while price rose. This marks a short squeeze that has already happened; the forced buying is done, leaving a better price to short with less squeeze fuel left.
- m02: Open interest is unwinding during a rise after the signal. The rally is driven by liquidations or covering rather than new longs, so it tends to exhaust; entering after the unwind avoids the straight_against paths.

## Наблюдения недели и порог

| вид | правило | случаев | случайные не хуже | вердикт |
|---|---|---|---|---|
| фильтр | `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` | 17 | 0.003 | проходит |
| фильтр | `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` | 14 | 0.0 | проходит |
| фильтр | `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` | 12 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` | 20 | 0.0 | проходит |
| фильтр | `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` | 15 | 0.0 | проходит |
| фильтр | `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` | 10 | 0.072 | проходит |
| ТВХ | `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` | 270 | 0.0 | проходит |
| ТВХ | `crowd_bybit_shift <= -0.06 и px_1h >= 0.005, окно 4 ч` | 1048 | 0.0 | проходит |
| ТВХ | `oi_1h <= -0.02 и since_signal >= 0.01, окно 5 ч` | 486 | 0.0 | проходит |
| ТВХ | `burst_ratio >= 2 и depth_eat_ask >= 1000 и px_1h >= 0.01, окно 3 ч` | 131 | 0.5875 | случайный час не хуже в 0.5875 > 0.2 |
| ТВХ | `funding >= 0.0001 и since_signal >= 0, окно 6 ч` | 688 | 0.025 | проходит |

Прошли порог, ждут места: `since_signal >= 0.03 и buy_share <= 0.47, окно 4 ч` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.24h_pct >= 15` — предел 2 новых за 7 суток; `book_rules.lev >= 20 и price_moves_to_decision.4h_pct >= 5` — предел 2 новых за 7 суток; `book_rules.lev >= 10 и derived.name_floor_share >= 0.35` — предел 2 новых за 7 суток; `derived.crowd_bybit_shift_24h <= -0.15 и price_moves_to_decision.4h_pct >= 3` — предел 2 новых за 7 суток; `price_moves_to_decision.4h_pct >= 10 и price_moves_to_decision.1h_pct >= 1` — предел 2 новых за 7 суток; `funding >= 0.0001 и since_signal >= 0, окно 6 ч` — предел 2 новых за 7 суток; `price_moves_to_decision.1h_pct >= 3 и crowd_positioning.bybit.now < 0.45` — предел 2 новых за 7 суток
