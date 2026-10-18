# Сухой час судьи (спека 19, N2)

2026-10-18 16:54 UTC, 162.4 с. Модель `claude-opus-5-5`, усилие `medium`, промпт `v1-2026-10-18`; цены — https://platform.claude.com/docs/en/about-claude/pricing (2026-10-18).

Вызовов 44, потрачено **$0.5341**; без вердикта: 0; ответили модели: {'claude-opus-5-5': 44}.

Покрытие досье: кандидатов 20, ход цены есть 20, толпа Bybit есть 20, Binance есть 15, новости по имени есть 0, срез рынка есть 20

| вызов | число | средняя цена | токенов вход / выход | задержка |
|---|---|---|---|---|
| вход | 36 | $0.01184 | 2202 / 152 | 3.3 с |
| сторож | 8 | $0.01347 | 2787 / 116 | 3.1 с |

Повторяемость (тот же вход дважды): **100.0 %** на 12 парах (порог суда 90 %). Доля отказов судьи с новостями: **8.3 %** (тревога выше 60 %).

**Цена в сутки** (входов книг за 7 сут: {'optimal': 2.4, 'optimal_h': 20.9}; открытых сейчас 83): вход 49 вызовов ≈ $0.58, сторож не меньше 332 ≈ $4.47; итого **≥ $5.05 в сутки, ≥ $151.5 в месяц** (события сторожа — сверху).

| ветка | книга | имя | решение | уверенность | причины |
|---|---|---|---|---|---|
| ai_news | optimal | SUSHIUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning ratios moderate, not extreme; price_moves_to_decision are ordinary drawdown, not a veto reason |
| ai_news_repeat | optimal | SUSHIUSDT | open | 0.8 | news_on_this_coin_72h empty; no coin-specific event; crowd_positioning ratios moderate, no extreme one-sided crowding; exchange_events_since_72h and calendar_next_48h empty |
| ai_plain | optimal | SUSHIUSDT | open | 0.8 | No coin-specific events: exchange_events_since_72h and calendar_next_48h empty; crowd_positioning: long/short ratios below 1 on Bybit/Binance, longs not crowded; price_moves_to_decision show ordinary  |
| ai_news | optimal | KSMUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning not extreme for long; ratios below 1 on Binance/Bybit; exchange_events_since_72h and calendar_next_48h empty |
| ai_news_repeat | optimal | KSMUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning ratios modest and easing, no squeeze risk against long; exchange_events_since_72h and calendar empty |
| ai_plain | optimal | KSMUSDT | open | 0.8 | no coin-specific events or news in the dossier; crowd_positioning ratios show no one-sided crowding against the long; price_moves_to_decision show an ordinary drawdown, not a veto reason |
| ai_news | optimal | LRCUSDT | open | 0.8 | news_on_this_coin_72h empty: no coin-specific event; crowd_positioning bybit 0.65 long-leaning but not extreme; exchange_events_since_72h and calendar empty |
| ai_news_repeat | optimal | LRCUSDT | open | 0.85 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning bybit 0.65 long-leaning but not extreme; exchange_events_since_72h and calendar empty |
| ai_plain | optimal | LRCUSDT | open | 0.8 | No coin-specific news or exchange events in the dossier; crowd_positioning bybit 0.65 long ratio is moderate, not an extreme squeeze setup; name_history_in_book: 8 prior positions, 0 hit_floor |
| ai_news | optimal | SUSHIUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning not extreme; long/short ratios moderate; price_moves_to_decision ordinary drawdown, market noise only |
| ai_news_repeat | optimal | SUSHIUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning not extremely one-sided against a long; exchange_events_since_72h empty, calendar clear |
| ai_plain | optimal | SUSHIUSDT | open | 0.8 | no coin-specific events in calendar_next_48h or exchange_events_since_72h; crowd_positioning ratios stable, not extreme enough to signal a squeeze against the long; price_moves_to_decision show an ord |
| ai_news | optimal | AEVOUSDT | open | 0.8 | news_on_this_coin_72h empty; no coin-specific event; exchange_events_since_72h empty, calendar clear; crowd_positioning long-leaning but stable, not extreme for squeeze |
| ai_news_repeat | optimal | AEVOUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; exchange_events_since_72h and calendar_next_48h empty; crowd_positioning ratios stable, no extreme one-sidedness |
| ai_plain | optimal | AEVOUSDT | open | 0.8 | no coin-specific news or exchange events in dossier; crowd_positioning ratios moderate, not squeeze-prone against long; name_history_in_book: 23 positions, 0 hit_floor |
| ai_news | optimal | 1000TURBOUSDT | open | 0.8 | news_on_this_coin_72h is empty, so there is no coin-specific event; crowd_positioning is long-leaning but easing (0.664 to 0.654), not extreme; the price drop in price_moves_to_decision is ordinary mo |
| ai_news_repeat | optimal | 1000TURBOUSDT | open | 0.8 | news_on_this_coin_72h empty: no coin-specific event; crowd_positioning ~0.65 long, stable, not extreme enough for squeeze; exchange_events_since_72h empty; drop is ordinary price move |
| ai_plain | optimal | 1000TURBOUSDT | open | 0.8 | no coin-specific events or news in dossier; crowd_positioning long ratio ~0.65, moderate and slightly easing; price drop is an ordinary move, not a veto reason |
| watch | optimal | SUSHIUSDT | hold | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning roughly unchanged vs entry_crowd; small loss (-0.65%) handled by stop floor/time limit |
| watch | optimal | KSMUSDT | hold | 0.85 | news_on_this_coin_72h empty; no coin-specific event; crowd_positioning little changed since entry_crowd; pnl_pct_of_margin -0.64 is a small loss handled by stop floor |
| watch | optimal | LRCUSDT | hold | 0.8 | news_on_this_coin_72h empty, no coin-specific event; exchange_events_since_72h empty; crowd_positioning shift small (0.65 to 0.666), loss of -0.7% within normal range |
| watch | optimal | SUSHIUSDT | hold | 0.8 | news_on_this_coin_72h is empty and there are no exchange events; crowd_positioning has barely moved since entry_crowd; pnl_pct_of_margin -0.82 is a small loss that the stop floor covers |
| ai_news | optimal_h | DGAIUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning not one-sided enough to signal a squeeze (bybit 0.45, okx 0.51); calendar_next_48h and exchange_events_since_72h empty |
| ai_news_repeat | optimal_h | DGAIUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning not one-sided enough to signal a squeeze (bybit 0.45, okx 0.51); calendar_next_48h and exchange_events_since_72h empty |
| ai_plain | optimal_h | DGAIUSDT | open | 0.72 | no coin-specific events or news in dossier; crowd_positioning not extreme (bybit 0.45, okx 0.51); name_history_in_book: 0 floor hits in 12 positions |
| ai_news | optimal_h | QUSDT | skip | 0.55 | crowd_positioning: ~75% of accounts short (Bybit 0.31, Binance global 0.33), top traders adding shorts too; price_moves_to_decision: +6.9% in 1h and +331% in 7d against a crowded short, an active sque |
| ai_news_repeat | optimal_h | QUSDT | skip | 0.6 | crowd_positioning: Bybit long/short ratio about 0.31 and Binance global about 0.33, so shorts heavily crowded; price_moves_to_decision: +6.9% 1h, +19% 24h, +331% 7d; a squeeze against shorts is underw |
| ai_plain | optimal_h | QUSDT | skip | 0.6 | crowd_positioning: Bybit 0.31 and BN global 0.33 long/short ratios show accounts heavily short, so the short side is crowded; price_moves_to_decision: +331% over 7d and +6.9% in the last hour, suggest |
| ai_news | optimal_h | RLCUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning balanced (bybit 0.518), no squeeze setup; calendar_next_48h and exchange_events_since_72h empty |
| ai_news_repeat | optimal_h | RLCUSDT | open | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning balanced, no squeeze setup against short; calendar_next_48h and exchange_events_since_72h empty |
| ai_plain | optimal_h | RLCUSDT | open | 0.72 | exchange_events_since_72h empty; no coin-specific news; crowd_positioning not one-sided enough for a squeeze (bn_global 0.41, bybit 0.52); price_moves_to_decision show ordinary downtrend, no event |
| ai_news | optimal_h | SANDUSDT | open | 0.72 | news_on_this_coin_72h empty; no coin-specific event; crowd_positioning not extreme (bybit 0.64, bn_global 0.59); calendar_next_48h and exchange_events_since_72h empty |
| ai_news_repeat | optimal_h | SANDUSDT | open | 0.72 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning: Bybit/Binance ratios near balanced, no extreme squeeze setup; calendar_next_48h and exchange_events_since_72h empty |
| ai_plain | optimal_h | SANDUSDT | open | 0.74 | No coin-specific events: calendar_next_48h and exchange_events_since_72h are empty; crowd_positioning is long-leaning (bybit 0.64, okx rising to 1.82), so a short squeeze is unlikely; price_moves_to_d |
| ai_news | optimal_h | GWEIUSDT | open | 0.72 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning moderately long-leaning (bybit 0.649), not a squeeze risk for a short; exchange_events_since_72h and calendar empty |
| ai_news_repeat | optimal_h | GWEIUSDT | open | 0.72 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning long-leaning (bybit 0.649), no short squeeze setup; exchange_events_since_72h and calendar_next_48h empty |
| ai_plain | optimal_h | GWEIUSDT | open | 0.72 | exchange_events_since_72h and calendar_next_48h are empty; crowd_positioning is long-leaning (bybit 0.649, bn_global 0.69), not a crowded short; price_moves_to_decision show ordinary volatility, no co |
| ai_news | optimal_h | ARIAUSDT | open | 0.7 | news_on_this_coin_72h empty: no coin-specific event; crowd_positioning: long/short ratios falling, no one-sided short crowd; price_moves_to_decision pump is ordinary price action the model sees |
| ai_news_repeat | optimal_h | ARIAUSDT | open | 0.7 | news_on_this_coin_72h empty: no coin-specific event; crowd_positioning bybit 0.596 falling: longs not crowded against short; price_moves_to_decision show strong rally, ordinary price risk only |
| ai_plain | optimal_h | ARIAUSDT | open | 0.6 | No coin-specific event: exchange_events_since_72h and calendar_next_48h are empty, and there is no news; crowd_positioning leans short (bybit 0.596, bn_global 0.678) and is drifting further short; not |
| watch | optimal_h | DGAIUSDT | hold | 0.8 | news_on_this_coin_72h empty, exchange_events_since_72h empty: no coin-specific event since entry; crowd_positioning shifted only slightly vs entry_crowd (bybit 0.454->0.482, okx 0.51->0.55), not a sha |
| watch | optimal_h | QUSDT | hold | 0.72 | news_on_this_coin_72h empty, no coin-specific event since entry; crowd_positioning roughly unchanged vs entry_crowd (bybit 0.312->0.318, bn_top 0.494->0.487); loss of -7.65% margin is handled by stop  |
| watch | optimal_h | RLCUSDT | hold | 0.85 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning shifted little since entry_crowd; pnl_pct_of_margin -0.4 is minor; stop and time limit handle losses |
| watch | optimal_h | SANDUSDT | hold | 0.8 | news_on_this_coin_72h empty, no coin-specific event; crowd_positioning barely changed vs entry_crowd (still long-leaning, supports short); position_now pnl positive at 1.9h of 24h hold |
