# Проверки

Генерируется `tools/project_map.py`; руками не править. Имена проверок в проекте описывают поведение словами — это индекс того, что закреплено тестом. Строка — `L<номер>` в файле теста.


## research/a1_universe/test_funding_refresh.py · 205 строк

Проверки догона рядов funding (`funding_refresh.py`).

- L17 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L22 `TODAY = date(2026, 9, 6)`
- L25 `_iso(d, h=0)`
- L29 `_write(dirp, sym, rows)`
- L38 `class _Fetch`
  - L39 `_Fetch.__init__(self, rows, fail=False)`
  - L42 `_Fetch.__call__(self, sym, a, b)`
- L49 `_in_tmp(fn)`
- L60 `test_merge_dedups_by_time_and_new_wins()`
- L70 `test_tail_is_fetched_from_the_last_day_with_overlap()`
- L93 `test_current_symbol_is_not_fetched_and_failure_leaves_the_file()`
- L112 `test_run_aggregates_and_report_names_failures()`
- L137 `_poison(path, lit, sub, fn, mod)` — --- отрицательные контроли ------------------------------------------------
- L161 `P = os.path.join(HERE, 'funding_refresh.py')`
- L164 `_control_no_overlap()`
- L170 `_control_old_point_wins()`
- L176 `_control_current_symbol_refetched()`
- L181 `TESTS = [test_merge_dedups_by_time_and_new_wins…`
- L188 `CONTROLS = [('хвост без перекрытия', _control_no_o…`
- L195 `main()`

## research/a1_universe/test_options.py · 286 строк

Тесты инвентаря опционов площадки.

- L14 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `test_summarize_only_trading()`
- L33 `test_summarize_counts_contract_once()` — Строки приходят из ДВУХ обходов и пересекаются — контракт считается раз.
- L51 `test_alias_set()`
- L60 `test_api_get_refusal_is_data()`
- L77 `test_run_falls_back_to_probe()` — Общий список не отдан → поимённый опрос, и метод назван в артефакте.
- L103 `test_general_list_narrowing_is_named()` — Общий список без `baseCoin` подставляет умолчание — это НАЗЫВАЕТСЯ.
- L136 `test_report_names_absence()`
- L155 `_control_count_closed()` — Считая снятые контракты, мы объявили бы хедж возможным там, где инструмента нет — проверка свода обязана упас…
- L178 `_control_alias_no_strip()` — Без снятия множителя лота покрытие вышло бы заниженным.
- L192 `_control_api_raises()` — Отказ, поднятый исключением, не даёт перейти ко второму обходу.
- L209 `_control_trusts_general_list()` — Доверяя общему списку (опрос только при его отказе), мы повторили бы живой отказ: «базовый актив ровно один»…
- L239 `_control_no_dedup()` — Без снятия дублей число контрактов удваивается — проверка обязана упасть (живой отказ: BTC 1540 вместо 770).
- L264 `TESTS = [test_summarize_only_trading, test_summ…`
- L269 `CONTROLS = [('снятые контракты считаются живыми', …`
- L276 `main()`

## research/a1_universe/test_persistence.py · 217 строк

Тесты статистики персистентности funding.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L28 `brute_agreement(f, g)` — То же, что `pair_sign_agreement`, но перебором.
- L47 `class Inversions`
  - L48 `Inversions.test_sorted(self)`
  - L51 `Inversions.test_reversed(self)`
  - L54 `Inversions.test_ties_are_not_inversions(self)`
  - L57 `Inversions.test_matches_brute_force(self)`
- L69 `class PairSignAgreement`
  - L70 `PairSignAgreement.test_identical_order_is_one(self)`
  - L77 `PairSignAgreement.test_reversed_order_is_zero(self)`
  - L81 `PairSignAgreement.test_matches_brute_force(self)`
  - L95 `PairSignAgreement.test_ties_excluded_matches_brute_force(self)` — Ряд с обилием точных совпадений — как настоящие ставки funding.
  - L111 `PairSignAgreement.test_all_tied_has_no_sign(self)`
  - L116 `PairSignAgreement.test_independent_series_is_near_half(self)` — Отсутствие связи должно давать 50 %, а не смещённую величину.
- L124 `class Spearman`
  - L125 `Spearman.test_monotone(self)`
  - L128 `Spearman.test_antitone(self)`
  - L131 `Spearman.test_known_value(self)`
- L137 `class DecileSpread`
  - L138 `DecileSpread.test_selection_is_by_past_only(self)` — Отбор по `f`; `g` считается по тем же активам, а не пересортировкой.
  - L152 `DecileSpread.test_promised_is_nonnegative(self)`
- L158 `_series(step_h, n, rate, start_ms=0)` — Ряд из `n` начислений с постоянным шагом и постоянной ставкой.
- L171 `class WindowRate`
  - L172 `WindowRate.test_constant_rate_annualizes(self)` — 8 ч × 0.0001 = 3 начисления в сутки → 0.0003 в сутки → 10.95 % годовых.
  - L179 `WindowRate.test_hourly_regime_gives_eight_times_more(self)` — Тот же размер ставки при часовом режиме стоит в восемь раз дороже.
  - L186 `WindowRate.test_window_outside_series_rejected(self)`
  - L190 `WindowRate.test_window_before_series_rejected(self)`
  - L194 `WindowRate.test_hole_at_window_edge_rejected(self)` — Дыра у края окна занижает сумму — такое окно брать нельзя.
  - L210 `WindowRate.test_short_window_rejected(self)`

## research/a1_universe/test_risk_limit.py · 126 строк

Тесты разбора тиров D0 — без обращения к площадке.

- L11 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `FIXTURE = {'list': [{'id': 2, 'symbol': 'X', 'ris…` — Ответ намеренно НЕ отсортирован по нотионалу: площадка порядок не гарантирует, а D1 ищет тир по размеру позиц…
- L30 `test_tiers_parsed_and_sorted_by_notional()`
- L45 `test_empty_list_is_empty_not_none()`
- L55 `test_report_counts_three_states_by_number()`
- L69 `_control_sort_removed()` — Если убрать сортировку по нотионалу, тест порядка обязан упасть.
- L90 `_control_empty_becomes_none()` — Если пустой ответ вернуть как None, различие «нет тиров» / «не собрано» исчезнет, и тест обязан упасть.
- L109 `TESTS = [test_tiers_parsed_and_sorted_by_notion…`
- L116 `main()`

## research/a1_universe/test_universe.py · 244 строк

Тесты интервальной логики универсума.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L36 `D = date.fromisoformat`
- L39 `class ToIntervals`
  - L40 `ToIntervals.test_empty(self)`
  - L43 `ToIntervals.test_single_day(self)`
  - L47 `ToIntervals.test_contiguous_run_collapses(self)`
  - L51 `ToIntervals.test_gap_splits(self)`
  - L58 `ToIntervals.test_one_day_gap_is_a_gap(self)`
- L65 `class SplitSettlement`
  - L66 `SplitSettlement.test_no_settlement_when_single_interval(self)`
  - L70 `SplitSettlement.test_isolated_trailing_day_is_settlement(self)`
  - L78 `SplitSettlement.test_real_resumption_is_kept(self)`
  - L85 `SplitSettlement.test_short_gap_single_day_is_not_settlement(self)`
- L94 `REC = {'base': 'TEST', 'bybit_symbol': 'TESTU…`
- L107 `class PointInTime`
  - L108 `PointInTime.test_tradable_inside_interval(self)`
  - L111 `PointInTime.test_not_tradable_in_gap(self)`
  - L114 `PointInTime.test_not_tradable_after_delisting(self)`
  - L117 `PointInTime.test_history_counts_only_traded_days(self)`
  - L121 `PointInTime.test_history_excludes_the_gap(self)`
  - L125 `PointInTime.test_binance_history_is_longer_here(self)`
  - L132 `PointInTime.test_estimation_takes_the_longer_series(self)`
- L139 `class UniverseAt`
  - L140 `UniverseAt.setUp(self)`
  - L143 `UniverseAt.test_delisted_asset_is_included_in_past_window(self)`
  - L148 `UniverseAt.test_asset_excluded_after_its_death(self)`
  - L151 `UniverseAt.test_excluded_during_suspension(self)`
  - L154 `UniverseAt.test_history_filter_applies(self)`
  - L157 `UniverseAt.test_requires_binance_series_by_default(self)`
- L161 `class AssetClass` — Разметка классов активов и исключение некрипты из универсума.
  - L164 `AssetClass._manifest(self)`
  - L172 `AssetClass._fees(self)`
  - L181 `AssetClass.test_cheap_tier_marks_non_crypto(self)`
  - L188 `AssetClass.test_exception_list_wins_over_tier(self)`
  - L196 `AssetClass.test_missing_rate_stays_crypto(self)`
  - L205 `AssetClass.test_universe_excludes_non_crypto_by_default(self)`
  - L212 `AssetClass.test_tier_threshold_is_exact(self)`
- L222 `class Normalize` — Регрессии на две ошибки, найденные проверкой покрытия групп.
  - L225 `Normalize.test_prefix_multiplier(self)`
  - L228 `Normalize.test_suffix_multiplier(self)`
  - L234 `Normalize.test_largest_multiplier_wins(self)`
  - L239 `Normalize.test_plain_symbol(self)`

## research/a2_storage/test_refresh.py · 342 строк

Тесты докачки хранилища A2.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `RESEARCH = os.path.dirname(HERE)`
- L33 `FAILED = []`
- L36 `check(name, cond, detail='')`
- L44 `test_days_stop_before_today()` — Сегодня не качается: суточный архив появляется после конца суток.
- L57 `test_max_days_guard()` — Предохранитель: докачка не превращается в повторный прогон A1.
- L63 `test_live_symbols_skips_the_dead()`
- L82 `make_zip(path, rows)` — Суточный/месячный архив в формате Binance.
- L95 `build_store(tmp, interval='1m', extra_day=False, gap_day=False)` — Сырьё месяца и сборка партиции НАСТОЯЩИМ build.py.
- L125 `test_readiness_accounts_for_new_files()` — Дозакачанный день ОБЯЗАН вызвать пересборку партиции.
- L172 `test_storage_edge_reads_a_real_partition()` — Край читается с НАСТОЯЩЕЙ партиции и без сторонних модулей.
- L198 `test_edge_is_the_end_of_CONTINUOUS_coverage()` — Край — конец НЕПРЕРЫВНОГО покрытия, а не максимальная метка.
- L222 `test_days_pilot_takes_the_FIRST_days()` — Пилот берёт дни ОТ КРАЯ, а не с конца: иначе он сам делает дыру.
- L230 `test_watchdog_daily_window()` — Секция сторожа гоняется НАСТОЯЩИМ блоком скрипта с заглушками.
- L310 `test_verdict_says_when_edge_did_not_move()` — Неподвижный край при непустой докачке — отказ, и он называется.
- L319 `main()`

## research/a4_cointegration/test_coint.py · 193 строк

Проверки статистики A4.

- L24 `ou_pair(n=2000, beta=1.5, phi=0.98, seed=0, noise=0.002)` — Пара, у которой спред — авторегрессия первого порядка.
- L40 `two_walks(n=2000, seed=0)`
- L47 `class KnownAnswers`
  - L48 `KnownAnswers.test_cointegrated_pair_is_found(self)`
  - L54 `KnownAnswers.test_independent_walks_are_not(self)` — Две независимые прогулки не должны проходить систематически.
  - L64 `KnownAnswers.test_half_life_recovers_known_value(self)` — Определение — спека 01 §2.4: Δs = λ·s + ε, half_life = −ln2/λ.
  - L85 `KnownAnswers.test_explosive_spread_has_no_half_life(self)` — Расходящийся спред: λ ≥ 0, полураспада не существует.
  - L90 `KnownAnswers.test_random_walk_half_life_is_useless(self)` — У прогулки λ оценивается около нуля, полураспад — порядка длины выборки, то есть заведомо вне горизонта удерж…
  - L98 `KnownAnswers.test_beta_matches_least_squares(self)`
  - L107 `KnownAnswers.test_too_short_series_rejected(self)`
- L112 `class FDR`
  - L113 `FDR.test_step_up_not_naive_threshold(self)` — Ключевое отличие процедуры: отвергается всё до наибольшего k.
  - L129 `FDR.test_nothing_passes(self)`
  - L133 `FDR.test_all_pass(self)`
  - L137 `FDR.test_false_discovery_rate_is_controlled(self)` — На чистом шуме доля отобранных не должна превышать alpha.
  - L147 `FDR.test_matches_brute_force(self)`
  - L162 `FDR.test_empty_input(self)`
- L166 `class Resampling`
  - L167 `Resampling.test_bucket_label_and_last_value(self)`
  - L174 `Resampling.test_gaps_do_not_create_bars(self)` — Пустой интервал не появляется: бара со сделками там не было.
  - L181 `Resampling.test_align_matches_by_timestamp(self)`

## research/a4_cointegration/test_walkforward.py · 245 строк

Проверки сводки walk-forward.

- L19 `window(date, pairs_fdr, pairs_sel=None, candidates=None)` — Окно с заданными наборами прошедших пар.
- L37 `grid(sets, start='2023-01-01', candidates=None)` — Окна, расставленные ровно по шагу сетки.
- L49 `class Overlap`
  - L50 `Overlap.test_denominator_is_the_earlier_window(self)` — Вопрос §8 — сколько из отобранного удержалось.
  - L61 `Overlap.test_empty_earlier_window_is_not_zero(self)` — Окно, не отобравшее ничего, не имеет выживаемости.
  - L70 `Overlap.test_identical_sets(self)`
- L74 `class ConditionalSurvival` — Пара, выпавшая из кандидатов, — не распавшаяся связь.
  - L83 `ConditionalSurvival.test_dropped_candidate_does_not_count_as_broken(self)`
  - L88 `ConditionalSurvival.test_tested_and_failed_counts_as_broken(self)`
  - L92 `ConditionalSurvival.test_nothing_carried_over_is_not_zero(self)`
  - L98 `ConditionalSurvival.test_summary_separates_survival_from_candidate_churn(self)`
  - L111 `ConditionalSurvival.test_candidate_carryover_measured_on_full_list(self)`
  - L117 `ConditionalSurvival.test_criterion_2_reads_conditional_not_unconditional(self)` — Порог §8 сравнивается с условной долей.
- L132 `class NullModel` — Нулевая модель обязана отнимать смысл метки и ничего больше.
  - L140 `NullModel.setUp(self)`
  - L149 `NullModel.test_group_sizes_are_preserved(self)`
  - L154 `NullModel.test_every_asset_keeps_exactly_one_label(self)`
  - L159 `NullModel.test_labels_actually_move(self)`
  - L163 `NullModel.test_same_seed_same_permutation(self)`
  - L168 `NullModel.test_mechanical_pairs_dropped_duplicates_kept_excluded(self)` — Механическая связь задана протоколом, а не меткой.
  - L180 `NullModel.test_original_inputs_not_mutated(self)`
  - L187 `NullModel.test_null_windows_stored_apart(self)` — Окна нуля и окна прогона в одном каталоге испортили бы сводку.
- L193 `class Summary`
  - L194 `Summary.test_survival_pairs_consecutive_windows(self)`
  - L202 `Summary.test_three_step_survival_skips_overlapping_windows(self)`
  - L210 `Summary.test_criteria_read_from_the_thresholds_in_spec(self)`
  - L217 `Summary.test_stop_rule_needs_most_windows_not_some(self)` — Правило остановки — «в большинстве окон», а не «хотя бы в одном».
  - L225 `Summary.test_half_life_filter_narrows_selection(self)`
  - L232 `Summary.test_off_grid_window_is_refused_not_averaged(self)` — Окно не по сетке ломает смысл «соседнего» — и должно падать.

## research/asset_groups/test_pairs.py · 179 строк

Проверки отбора кандидатов A3.

- L17 `series(days, turnover=10000000.0, bars=1440, traded=1440, start…` — Ряд подневной ликвидности: `days` дней подряд от `start`.
- L25 `uni(**kw)`
- L33 `META = {'duplicates': set(), 'mechanical': [],…`
- L36 `class PointInTime`
  - L37 `PointInTime.test_future_days_are_not_used(self)` — День самой даты отбора и всё после неё в оценку не входят.
  - L47 `PointInTime.test_window_is_exactly_form_days(self)`
  - L53 `PointInTime.test_history_requirement(self)`
- L65 `class Liquidity`
  - L66 `Liquidity.test_days_without_trades_excluded_from_turnover(self)` — Замороженный день не наблюдение: в оборот он не входит.
  - L74 `Liquidity.test_days_without_trades_stay_in_share_denominator(self)` — ...но в знаменателе свежести цены остаются.
  - L82 `Liquidity.test_short_series_rejected(self)`
  - L87 `Liquidity.test_illiquid_asset_makes_no_pairs(self)`
- L96 `class SizeRule`
  - L97 `SizeRule.state(self, ta, tb)`
  - L101 `SizeRule.pairs(self, ta, tb, **kw)`
  - L106 `SizeRule.test_ratio_boundary(self)`
  - L111 `SizeRule.test_ratio_is_symmetric(self)`
  - L114 `SizeRule.test_threshold_is_a_parameter_not_a_constant(self)`
- L118 `class Membership`
  - L119 `Membership.st(self, *names)`
  - L123 `Membership.test_pairs_only_inside_a_group(self)`
  - L128 `Membership.test_unlabeled_makes_no_pairs(self)` — Актив без метки сектора не порождает кандидатов вовсе.
  - L134 `Membership.test_duplicate_listing_excluded(self)`
  - L140 `Membership.test_mechanical_pair_ignores_size(self)` — Газовый токен всегда меньше своей сети — размер здесь не судья.
  - L150 `Membership.test_mechanical_pair_not_duplicated(self)`
  - L156 `Membership.test_illiquid_leg_kills_mechanical_pair_too(self)`
- L165 `class RealGroups`
  - L166 `RealGroups.test_groups_file_parses_and_is_disjoint(self)`
  - L173 `RealGroups.test_unlabeled_are_not_in_groups(self)`

## research/b1_book/headless_check.js · 6321 строк

Прогон логики живых страниц без браузера: DOM, canvas и сеть

- L39 `flatBox()`
- L107 `mkEl()`
- L124 `elById()`
- L188 `dcaw()`
- L201 `trade()`
- L215 `candlesTo()` — Полоса цен фикстуры. Узкая (0.06 %) годится живой странице, где окно в минуты, и НЕ годится книге лестницы: е…
- L223 `candles()`
- L224 `state()`
- L283 `recTrade()` — Встречный счёт: те же входы, другая геометрия. Опознаётся по номеру сделки — так видно, подменила ли страница…
- L315 `dcaStub()` — Стаб бумажной месячной книги. Вынесен функцией, потому что её числа нужны и заглушке, и проверке: список чисе…
- L620 `paperStub()`
- L755 `bookDaysStub()`

## research/b1_book/test_book.py · 7755 строк

Тесты стакана. Закрывают место, где ошибка портит все данные молча.

- L22 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `FAILED = []`
- L30 `check(name, cond, detail='')`
- L38 `snap(u=100)`
- L45 `delta(u, b=None, a=None)`
- L50 `test_snapshot_then_delta()`
- L60 `test_concurrent_apply_and_sample()` — Снимок и правка книги идут из разных потоков — гонки быть не должно.
- L115 `test_zero_size_removes_level()` — Ноль — снятие уровня, а не нулевой объём.
- L124 `test_gap_resets_book()` — Разрыв нумерации: книгу выбрасываем, а не продолжаем молча.
- L136 `test_delta_before_snapshot_ignored()`
- L142 `test_sample_bands_and_ladder()`
- L159 `test_sample_none_when_one_side_empty()`
- L166 `test_trades_side_is_aggressor()`
- L180 `test_view_does_not_reset_counter()` — Показ не вправе портить запись.
- L198 `test_page_has_no_external_loads()` — Страницы обязаны быть самодостаточными: сервер стоит в интернете.
- L230 `test_pages_do_not_shadow_platform_globals()` — Скрипт страницы не смеет объявлять имена платформы браузера.
- L263 `_tag_attrs(src, tag)` — Атрибуты каждого тега `tag` в шаблоне страницы.
- L297 `_columns(src, head_re, body_re)` — (колонок в шапке, в строке, скрытые в шапке, скрытые в строке).
- L312 `TABLES = (('сделки', 'TRADES', '<thead><tr>(.*?)…` — Таблиц сделок на сервере две — полная на своей странице и короткая на обзоре, — и правка по тексту однажды уж…
- L330 `_trades_columns(src)`
- L334 `test_trades_table_columns_line_up()` — Шапка и строка обязаны совпадать колонка в колонку.
- L375 `test_owner_asks_road_reaches_the_journal()` — Дорога сервера до журнала просьб: путь тот же, что у записи.
- L399 `test_pages_run_headless()` — Логика страниц обязана отработать на подставном ответе.
- L697 `test_live_exec_paper_side_follows_the_book_marker()` — Бумажная сторона страницы live — книга из МАРКЕРА журнала.
- L816 `test_live_exec_measures_slippage_against_signal()` — Живое исполнение против бумажного сигнала — арифметика чисел.
- L1024 `test_agreed_book_is_shown_once_not_twice()` — Согласная книга показывается ОДНОЙ рукой — и это не украшение.
- L1130 `test_netted_signal_is_not_shown_as_a_trade()` — Решение, схлопнувшее встречный лот, — не сделка (правило владельца).
- L1217 `test_jsonl_cache_matches_plain_read()` — Кеш чтения `.jsonl` обязан отдавать РОВНО то, что в файле.
- L1311 `test_book_built_twice_gives_same_numbers()` — Две сборки книги подряд обязаны дать одинаковые числа.
- L1367 `test_overview_and_trades_page_agree()` — Обзор и страница сделок считают книгу ОДНИМ кодом.
- L1469 `test_model_trades_lite_matches_full()` — Лёгкий ответ /model_trades несёт те же строки, что полный.
- L1555 `test_sit_absorb_now_makes_pnl_immediate()` — Сборщик поглощает события сам: pnl сразу после закрытия.
- L1615 `test_trade_by_id_finds_across_books()` — Поиск сделки по короткому id обходит все книги разом.
- L1660 `test_live_detector_agrees_with_batch()` — Живой детектор обязан решать так же, как тот, чем считаны отчёты.
- L1698 `test_metrics_explain_refusal()` — Отказ обязан быть объяснён числом, а не молчанием.
- L1716 `test_warm_start_restores_history()` — Перезапуск не должен обнулять наблюдение.
- L1762 `test_candles_window_can_end_in_the_past()` — Свечи под сделку берутся из ЕЁ времени, а не из последних часов.
- L1834 `test_recount_survives_restart()` — Встречный счёт переживает перезапуск сборщика.
- L1881 `test_nofile_covers_every_kind()` — Дескрипторов запрашивается по числу ВИДОВ рядов, не по двойке.
- L1901 `test_health_is_one_definition()` — Здоровье сбора — одно определение на страницу и на файл.
- L1943 `test_collected_symbols_are_not_lost()` — Состав сбора не теряет монет, по которым уже собраны ряды.
- L1967 `test_warm_start_is_cheap_and_safe()` — Подъём не читает лишнего и не портит живой ряд.
- L2016 `test_disk_rate_compares_same_phase_of_hour()` — Скорость роста диска меряется в одной фазе часа.
- L2074 `test_warm_mid_is_lazy_and_ordered()` — Середина читается по запросу и не ломает порядок времени.
- L2133 `test_shrunken_run_announces_dropped_symbols()` — Урезанный состав сбора обязан назвать пропавших поимённо.
- L2187 `test_warm_start_survives_truncated_file()` — Обрубленный хвост файла не вправе уносить запуск.
- L2228 `QUIET = (0.0, 1.0, 1.0, 100.0, 99.9, 99.95)`
- L2231 `book_with(level_px=None, level_sz=0.0, side='b', n=20, step=0.1…` — Стакан из обычных уровней; при желании — с крупным на одной цене.
- L2243 `calibrate(tr, secs=None)` — Накопить «обычное» — без этого крупный не с чем сравнивать.
- L2256 `test_interrupted_trade_is_finished_from_tape()` — Оборванная сделка досчитывается по ленте — и честно про дыру.
- L2357 `test_recount_runs_itself_and_merges_live()` — Пересчёт запускается сам, а живые сделки дописываются как есть.
- L2423 `test_open_trade_is_visible_but_not_counted()` — Открытая позиция обязана быть видна и обязана не считаться.
- L2464 `test_book_absorption_needs_all_five()` — Поглощение — пять условий сразу, и каждое обязано уметь отказать.
- L2507 `test_gate_fires_equally_on_smooth_and_lumpy_books()` — Гейт «крупный» обязан срабатывать одинаково часто у всех.
- L2556 `test_level_out_of_reach_is_never_a_candidate()` — Недосягаемый уровень не должен выдавать себя за измерение.
- L2589 `test_reach_window_counts_seconds_not_snapshots()` — Ход копится по НОВЫМ секундам, а не по снимкам книги.
- L2611 `test_quantile_threshold_belongs_to_the_sample()` — Порог обязан быть значением из выборки, а не выдуманным.
- L2631 `test_level_is_not_judged_against_itself()` — Текущий замер не входит в выборку, по которой его судят.
- L2649 `test_book_absorption_rejects_pulled_and_broken()` — Снятый уровень и пробитый уровень — не поглощение.
- L2681 `test_two_rules_run_side_by_side()` — Правила не должны запирать друг друга.
- L2701 `test_stop_sees_the_candle_it_entered_on()` — Стоп считается по свечам ДО СЕКУНДЫ ВХОДА, а не до пересчёта.
- L2738 `test_stop_clears_the_biggest_candle_not_the_median()` — Стоп не вправе стоять внутри крупнейшей свечи окна.
- L2773 `test_stop_goes_behind_structure_not_inside_noise()` — Стоп обязан стоять за экстремумом и накоплением, а не в шуме.
- L2817 `test_replay_drives_detector_from_files()` — Прогон записи обязан кормить тот же детектор, что работает живьём.
- L2874 `test_seeded_replay_keeps_entry_changes_stop()` — Те же входы, новая геометрия — вход обязан остаться прежним.
- L2939 `test_target_skips_levels_that_do_not_pay_for_risk()` — Цель — ближайший уровень, ОПРАВДЫВАЮЩИЙ риск, а не просто ближайший.
- L2971 `test_compare_pairs_old_and_recomputed()` — Сопоставление «было / стало» обязано считать по парам, а не в среднем.
- L3008 `test_rejected_subscription_is_not_silence()` — Отклонённая подписка обязана назваться и не гасить остальные.
- L3059 `test_paper_off_is_silent_but_named()` — Выключенные бумажные сделки: ни одной новой, лента детектору не подаётся — и это НАЗВАНО, а не выглядит полом…
- L3108 `test_symbol_groups_for_page()` — Группы монет для страницы: разметка A3 + справочник, новые листинги честно в «прочих», а не рассованы по дога…
- L3141 `test_liq_and_metrics_recorded()` — Ликвидации и тикеры пишутся: живой поток не восстановим задним числом, и тихая потеря этих рядов была бы видн…
- L3179 `test_sit_scan_anchors_forecast_to_live_price()` — Живой вход: карта от модели, курок от цены.
- L3257 `test_sit_scan_v11_room_and_eaten()` — Правило v11: запас переживает шум, обещание съедено не больше потолка.
- L3318 `test_sit_noise_is_median_minute_range()` — Мера шума v12: максимум медианы целых минут и текущей минуты.
- L3376 `test_sit_scan_stop_is_the_quantile_level()` — Стоп берётся из квантильных концов листа, а не из линии прогноза.
- L3433 `test_sit_scan_max_rr_takes_the_other_end()` — Потолок отношения — правило книги низкого RR (владелец, 2026-08-22).
- L3514 `test_sit_scan_day_brake_blocks_traded_not_observation()` — Дневной тормоз в сканере: торгуемая книга не входит, наблюдательная запись пишет (контрольная рука — без неё…
- L3632 `test_sit_scan_enters_only_on_a_crossing_it_saw()` — Вход — событие, а не состояние, в котором имя застали.
- L3806 `test_sit_scan_candidate_gates_floor_side_and_agree()` — Гейты книги кандидата: пол входа, места по сторонам, согласие рук.
- L3905 `test_sit_scan_book_noise_multiplier()` — Правило книги равного риска: запас до стопа не тоньше 1.5 шума.
- L3993 `test_sit_scan_min_stop_book_rule()` — Правило книги равного риска: стоп не тоньше порога (1 %).
- L4068 `test_take_limit_fill_and_exit_event()` — Тейк — лимитка: принты сквозь уровень исполняют по уровню.
- L4131 `test_collector_keeps_its_public_methods()` — Сборщик цел: у него на месте всё, чем его запускают.
- L4154 `test_pending_live_exit_is_shown_before_the_review()` — Живой выход виден сразу, а не через час.
- L4220 `test_learning_day_by_day()` — Сводка обучения: навык по сечению, деньги дня и связь между ними.
- L4325 `test_paper_book_summary_comes_from_the_artefact()` — Месячная книга: свод из артефакта, транши из журнала.
- L4473 `test_book_days_splits_one_book_by_day()` — Дневная статистика книги: разбивка по календарным суткам UTC.
- L4630 `test_league_counts_a_decision_once()` — Разбивка ситуаций «одно решение — один голос».
- L4707 `test_league_ranks_by_realised_money()` — Лига: агрегаты по рукам/книгам/ситуациям и топ по деньгам.
- L4850 `test_model_tree_names_every_book()` — Дерево моделей: у каждой книги из карты есть текст, оба языка.
- L5001 `test_tournament_page_reads_artifact()` — Лист турнира: ответ — из артефакта прогона, пороги — из турнира.
- L5092 `test_tree_page_fits_the_phone()` — Дерево на телефоне — вертикальное; правила закреплены источником.
- L5115 `test_dca_tiles_line_up_and_fill_the_row()` — Плитки сводки DCA: значения на одной линии, ряд без хвоста.
- L5165 `test_dca_palette_comes_from_the_mockups()` — Цвета страницы DCA взяты из макетов, а не подобраны на глаз.
- L5218 `test_dca_page_fits_the_phone()` — Страница DCA на телефоне: таблицы ложатся карточками.
- L5257 `test_tree_scrolls_to_its_left_edge()` — Первая карточка дерева обязана быть достижима прокруткой.
- L5291 `test_volatility_splits_results_by_regime()` — Волатильность рынка против результата книг.
- L5396 `test_marks_poll_serves_the_book_in_view()` — Опрос переоценки обслуживает ТУ книгу, которую смотрят.
- L5450 `test_journal_marker_is_parsed_not_basenamed()` — Маркер журнала тени несёт ДВА поля, и разбирать надо оба.
- L5476 `test_book_registry_is_one_list()` — Книги объявлены один раз, и запрос каждой идёт в СВОЙ каталог.
- L5549 `test_glossary_describes_the_live_model()` — Справочник: каждое семейство названо, каждый признак расписан.
- L5668 `test_live_entries_reach_both_pages()` — Обзор и история сделок обязаны показывать ОДНИ сделки.
- L5741 `test_sit_watch_levels_and_crossing()` — Живой сторож ситуационной книги: уровни и пересечение.
- L5875 `test_all_symbols_filter()` — `--symbols all`: USDT-перпы минус не-крипто, ничего лишнего.
- L5948 `test_shard_split_covers_everything()`
- L5960 `test_pack_queue_single_worker()` — Смена часа закрывает сотни файлов разом; сжатие обязано идти очередью, а не потоком на файл — иначе раз в час…
- L5993 `test_closed_trade_is_returned_for_writing()` — Закрытие обязано выйти наружу, иначе его некому записать.
- L6029 `test_restore_marks_trade_cut_by_restart()` — Открытие без закрытия — не «ничего не было», а оборванная сделка.
- L6054 `test_store_writes_plain_and_packs_on_hour()` — Текущий час лежит простым текстом, прошлый — сжатым.
- L6091 `test_store_hour_not_counted_twice()` — Час, лежащий и простым, и сжатым, не удваивается.
- L6125 `test_store_salvages_corrupted_archive()` — Порча В СЕРЕДИНЕ архива не вправе уносить то, что записано после.
- L6167 `test_scanner_prefers_the_biggest_move_for_its_own_coin()` — Слот достаётся тому, у кого ход крупен ДЛЯ НЕГО.
- L6204 `test_switcher_says_how_the_book_is_ordered()` — Подпись обязана говорить, ЧТО за книга.
- L6235 `test_shadow_off_marker_is_a_state_not_an_alarm()` — Маркер выключения тени — состояние, не поломка.
- L6273 `test_jobs_poke_runs_queue_and_holds_rate()` — Сигнал очереди: запускает `tools/jobs.sh` и не даёт долбить.
- L6323 `test_run_live_refuses_to_archive_open_positions()` — Журнал с открытыми позициями не отставляется молча — блоком скрипта.
- L6382 `test_watchdog_respects_shadow_off_marker()` — Сторож не воскрешает выключенную тень — настоящим блоком скрипта.
- L6437 `test_factory_built_splits_forward_from_replay()` — Построенное системой: дерево читает РЕЕСТР и АРТЕФАКТ, и делит деньги на форвард и реплей прошлого.
- L6605 `test_strategy_card_shows_applied_beside_declared_and_twins()` — Карточка стратегии: применённое рядом с объявленным и близнецы.
- L6745 `test_candidate_book_is_addressable_and_unknown_key_is_refused()` — Книга кандидата открывается своим ключом; чужой ключ — отказ.
- L6849 `test_agents_limit_wait_is_a_state_not_a_silence_alarm()` — Роль, ждущая снятия лимита, тревогой тишины НЕ помечается.
- L6931 `test_agents_state_reads_the_registry_and_the_disk()` — Автономная система: тексты из реестра, построенность — с диска.
- L7041 `test_dca_serves_ruler_and_deposit_as_one_book()` — Дорога сборщика до книги DCA: линейка и депозит вместе, не порознь.
- L7267 `test_dca_open_pnl_is_marked_live_not_hourly()` — Открытый pnl DCA-книги переоценивается ЖИВОЙ серединой.
- L7360 `test_dca_cut_position_carries_its_reason()` — Оборванная позиция едет странице С ПРИЧИНОЙ, и текст ОДИН.
- L7425 `test_dca_trades_speak_the_language_of_the_chart()` — Позиции DCA-книги едут графику В ЕГО ФОРМЕ, и ТВХ приходит готовой.
- L7618 `main()`

## research/d1_seconds/test_detect.py · 803 строк

Тесты ядра решения D1. Каждая проверка закрывает место, где ошибка была бы невидимой в результате: числа печа…

- L15 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L20 `FAILED = []`
- L23 `check(name, cond, detail='')`
- L31 `ramp(n, start=100.0)` — Ровный ряд без движения: событий в нём быть не должно.
- L38 `test_place_takes_the_last_price_of_the_second()` — Решение принимается концом секунды, значит и цена — последняя.
- L52 `test_place_ignores_order_of_input()` — Порядок строк в записи не обязан быть отсортированным.
- L58 `test_gap_is_a_gap_not_a_carried_price()` — Дыра остаётся дырой: перенесённая цена дала бы нулевую доходность.
- L71 `test_window_is_time_not_cells()` — Главная проверка модуля.
- L96 `test_reference_is_the_nearest_not_the_older_one()` — Ближайшая опора, а не «последняя до».
- L119 `test_missing_reference_is_not_zero()` — Нет опоры — `nan`, а не «падения не было».
- L136 `test_detect_finds_the_declared_fall()`
- L149 `test_dedup_counts_one_event_per_window()` — Падение остаётся верным сотни секунд подряд.
- L168 `test_entry_at_the_decision_second_is_refused()` — Вход по цене, определившей сигнал, — подарок, которого нет.
- L184 `test_entry_is_the_first_price_strictly_after_the_delay()`
- L196 `test_entry_refuses_a_stale_price()` — Цена, найденная сильно позже намеченного момента, — другая сделка.
- L213 `test_horizon_runs_from_the_actual_entry()` — Задержка заполнения не должна укорачивать удержание.
- L229 `build_matrix(rows, n, mover=None, drop=0.04, j_ev=1800)` — Матрица ровных рядов; строке `mover` рисуется падение и отскок.
- L238 `matrix_index(P)`
- L245 `test_cross_section_floor_is_not_zero()` — Фон тоньше пола — «не измеряется», а не «превышение равно нулю».
- L262 `test_cross_section_excludes_neighbours_with_own_event()` — Сосед со своим падением не годится в фон — и не только сосед в ту же секунду.
- L296 `test_background_uses_the_same_execution_rule()` — Фон считается той же функцией, что событие.
- L316 `test_single_row_and_matrix_paths_agree()` — Внутри самого ядра путей исполнения два, и они обязаны совпасть.
- L348 `test_delay_axis_decays_as_the_rebound_is_given_away()` — Сквозная проверка: чем позже вход, тем меньше остаётся.
- L375 `test_live_and_replay_agree_bit_for_bit()` — То, ради чего ядро одно.
- L406 `test_declared_grid_matches_the_spec()` — Сетка объявлена спекой и после результата не меняется.
- L424 `test_episodes_glue_the_market_wide_drop()` — Сотня событий в одну минуту — одно наблюдение, а не сто.
- L433 `snapshot_line(sym, t, bid, ask, levels=50)` — Строка снимка ровно того вида, что пишет сборщик.
- L448 `test_fast_parse_matches_json_loads()` — Ускорение, меняющее числа, есть другая мера.
- L477 `test_fast_parse_refuses_a_snapshot_without_time()` — Снимок прежнего образца — пропуск, а не цена без времени.
- L494 `test_replay_end_to_end_into_a_fresh_checkout()` — Сквозной прогон настоящего `main()` по настоящим файлам записи.
- L624 `test_guard_matrix_chunks_change_nothing()` — Пачки строк экономят память и обязаны дать ТОТ ЖЕ ответ.
- L647 `test_float32_prices_do_not_move_the_measure()` — Цены хранятся в одинарной точности ради памяти.
- L672 `test_output_is_line_buffered_when_redirected()` — Отцепленный прогон обязан печатать построчно.
- L700 `test_a_crash_reports_itself()` — Упавший прогон обязан оставить файл, а не тишину.
- L758 `main()`

## research/d1_seconds/test_passive.py · 276 строк

Тесты модели очереди и замера пассивного входа.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L31 `FAILED = []`
- L34 `check(name, cond, detail='')`
- L42 `tape(rows)` — `(время, цена, объём, сторона)` массивами.
- L48 `test_touching_the_price_is_not_a_fill()` — Главная проверка модуля.
- L62 `test_fill_when_the_queue_is_eaten()`
- L70 `test_only_selling_aggression_fills_a_buy()` — Покупателя-агрессора наша покупка не исполняет.
- L83 `test_price_above_our_limit_does_not_fill()`
- L92 `test_wait_window_is_respected()` — Заявка снимается: сделка после окна ожидания нас не исполняет.
- L103 `test_trades_before_placement_do_not_count()` — Объём, прошедший ДО постановки, очередь нам не съедает.
- L111 `test_own_size_must_also_pass()` — Нужно съесть очередь И наш объём: иначе заявка задета частично.
- L126 `test_sell_side_is_a_mirror()` — Продажа лимиткой: исполняет ПОКУПАЮЩАЯ агрессия не ниже цены.
- L147 `test_default_side_is_bitwise_the_old_buy()` — Умолчание `side` — прежняя покупка, счёт D1 не шевелится.
- L158 `test_book_line_carries_ask_sz()` — Разбор снимка отдаёт размер очереди на аске.
- L174 `build_day(root, *, fill_side)` — Сутки из 60 имён; у одного падение 4 % и отскок.
- L207 `run_day(fill_side)`
- L227 `test_end_to_end_fills_and_misses()`
- L253 `main()`

## research/d1_seconds/test_tape_check.py · 267 строк

Тесты проверки события по ленте.

- L22 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L31 `FAILED = []`
- L34 `check(name, cond, detail='')`
- L42 `snap(sym, t, bid, ask)`
- L48 `test_both_parsers_agree()` — Разбор проверки и разбор прогона обязаны дать одну середину.
- L65 `test_trade_line_reads_milliseconds()` — Сборщик пишет метку сделки в миллисекундах, а сетка — в секундах.
- L79 `build(root, kind_rows)`
- L87 `scenario(with_trades)` — Сутки из 60 имён; у одного падение на 4 % и отскок.
- L119 `run_scenario(with_trades)`
- L137 `test_real_move_is_confirmed()`
- L153 `test_quote_only_move_is_caught()` — Главная проверка: пустая книга обязана быть названа пустой.
- L168 `test_no_trades_is_a_third_group()` — Отсутствие сделок — не опровержение, а отсутствие свидетельства.
- L186 `test_no_evidence_is_not_a_refutation()` — Все события в третьей группе — судить нечем, а не «закрыто».
- L207 `test_missing_median_is_not_printed_as_zero()` — У группы без сделок падения по сделкам НЕ СУЩЕСТВУЕТ.
- L231 `test_reading_is_written_from_numbers()` — Вывод собирается из чисел, а не из надежды.
- L247 `main()`

## research/dca_ladder/test_ladder.py · 1340 строк

Тесты ядра забора — цена ликвидации закреплена таблицей §5 спеки 01.

- L6 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L10 `MMR = 0.005`
- L13 `_single_liq_frac(leverage, mmr=MMR, base=100.0)` — Ликвидация одиночной (без лестницы) длинной позиции, долей от входа.
- L22 `test_liq_price_matches_spec5_table()`
- L36 `test_one_x_long_cannot_liquidate()`
- L43 `test_mmr_tier_lookup()`
- L62 `test_fully_loaded_avg_and_notional()`
- L74 `test_max_leverage_derived_from_fence()`
- L95 `test_venue_leverage_cap_binds()` — Предел плеча ТИРА площадки связывает раньше неравенства безопасности.
- L126 `test_fence_refuses_leverage_dead_at_open()` — Ликвидация обязана стоять ПРОТИВ позиции, иначе она мертва на входе.
- L155 `test_max_leverage_refuses_impossible_depth()`
- L168 `_control_no_mmr_term()` — Убрать (1−mmr) из знаменателя — таблица §5 обязана разойтись.
- L183 `_patch_ladder_source(lit, repl, test)` — Подделка ИСХОДНИКА ядра: правило живёт строкой, подменить функцию нечем. Копия кладётся в scratchpad и возвра…
- L218 `_control_venue_cap_ignored()` — Забор, не читающий предел тира — проверка обязана упасть.
- L237 `_control_dead_at_open_allowed()` — Снять проверку стороны ликвидации — плечо уедет за 1/mmr, и позиция окажется ликвидированной в момент открыти…
- L246 `_control_leverage_unbounded()` — Плечо, не считающее забор (всегда потолок) — тест вывода обязан упасть (не будет ни 3.02, ни монотонности).
- L261 `test_sigma_rungs_descend()`
- L270 `test_ladder_beats_hold_on_recovery()`
- L293 `test_ladder_partial_fill()`
- L307 `test_liquidation_on_gap()`
- L324 `_bars(closes, lows, highs=None, entry=None, vols=None)` — Собрать OHLC-бары из closes/lows для тестов D2; open первого = entry.
- L344 `test_dca_matches_ladder_bit_for_bit()`
- L363 `test_dca_take_on_recovery()`
- L382 `test_dca_capit_floor_in_the_red()`
- L399 `test_dca_liquidation_gap()`
- L412 `test_single_stop_and_take()`
- L428 `test_same_coin_short_no_trigger()`
- L435 `test_same_coin_short_recovers_to_zero()`
- L449 `test_same_coin_short_crash_gains()`
- L465 `test_liq_price_short_is_above()`
- L477 `test_single_short_take_stop_liq()`
- L501 `_control_short_side_ignored()` — Если сторону игнорировать (считать лонгом), шорт-геометрия ломается — тест тейка/стопа/ликвидации шорта обяза…
- L523 `_control_short_recovers_on_entry_bar()` — Если восстановление проверять НА баре входа (у него верх ≥ триггера почти всегда), крах закрылся бы в ноль —…
- L553 `_control_dca_no_floor()` — Пол игнорируется — сделка идёт до ликвидации/срока, не 'пол'.
- L572 `_control_dca_take_ignored()` — Тейк игнорируется — возврат не закрывается по уровню, не 'тейк'.
- L593 `_control_no_liquidation_check()` — Убрать проверку ликвидации в simulate_hold — разрыв обязан перестать ловиться, тест разрыва падает.
- L615 `_control_rungs_never_fill()` — Если рунги ниже базы не заполняются, лестница вырождается в базу и на возврате не бьёт удержание — тест возвр…
- L643 `_track_bars(t0=1699999200, hours=5)` — Бары трёх часов: ровно, затем провал до рунга, затем возврат.
- L657 `test_track_does_not_change_numbers()` — Отметка — наблюдение, а не правило: числа обязаны совпасть бит в бит.
- L672 `test_track_last_equals_outcome()` — Последняя запись отметки — сам исход сделки, а не переоценка.
- L689 `test_track_marks_hour_close()` — Переоценка часа — по ПОСЛЕДНЕМУ бару часа, а не по первому.
- L706 `_control_track_marks_hour_open()` — Отметка по ПЕРВОМУ бару часа (запись не перезаписывается) — экспозиция и переоценка книги отставали бы на час.
- L735 `test_fills_describe_the_position_and_its_floating_entry()` — Входы позиции записаны, и средняя из них равна средней симуляции.
- L774 `_control_fills_not_logged()` — Доливы не записываются: позиция не разворачивается во входы.
- L788 `test_open_mark_equals_the_simulation_pnl()` — Живая отметка открытой позиции — та же величина, что pnl симуляции.
- L825 `_control_open_mark_forgets_leverage()` — Отметка считается без плеча: страница показала бы не те деньги.
- L839 `test_limit_needs_a_print_market_exit_does_not()` — Лимитка на баре БЕЗ принтов не заполняется, рыночный выход — да.
- L881 `_control_limit_fills_without_a_print()` — Правило снято: лимитка заполняется и на минуте без единой сделки.
- L889 `TAKE_RUNGS = [100.0, 90.0]`
- L890 `TAKE_W = [0.5, 0.5]`
- L893 `_dca_take(bars, rule=None, take_px=None, rungs=None, w=None, le…`
- L899 `test_entry_anchored_rule_equals_take_px()` — Якорь `entry` обязан совпасть со старым `take_px` БИТ В БИТ.
- L917 `test_avg_anchor_follows_the_ladder_and_pays_filled_leverage()` — Тейк от ТВХ едет вниз вместе со средней, и его pnl — тождество.
- L938 `test_take_level_uses_the_average_at_the_bar_start()` — Долив ЭТОЙ минуты уровень опускает, но заявку переставит следующая.
- L953 `test_trailing_arms_then_exits_below_the_peak()` — Трейл: взвод не закрывает, выход не получает цену уровня.
- L988 `test_take_px_and_take_rule_together_are_refused()` — Два уровня разом неоднозначны — отказ, а не молчаливый выбор.
- L1006 `test_short_take_fills_below_entry()` — Тейк шорта стоит НИЖЕ входа и исполняется низом бара по уровню.
- L1030 `test_short_rungs_need_the_price_to_rise()` — Лестница шорта не набирается, пока цена НЕ ВЫРОСЛА до рунгов.
- L1054 `test_short_liquidation_is_above_entry()` — Шорт ликвидируется ростом цены; у лонга тот же путь безобиден.
- L1071 `test_short_floor_cuts_above_entry()` — Пол капитуляции у шорта срабатывает СВЕРХУ и режет не в −100 %.
- L1087 `test_short_take_rule_walks_with_the_average()` — Динамический тейк шорта едет ВВЕРХ вместе с ТВХ и стоит ниже неё.
- L1109 `test_short_rungs_and_fence_mirror()` — Уровни, σ-сетка и забор зеркальны; лонг тем же вызовом не тронут.
- L1139 `test_short_open_mark_mirrors_the_sign()` — Отметка открытого шорта тождественна симуляции и зеркальна знаком.
- L1149 `_poison_ladder(lit, sub, fn)` — Подделка строки ядра и прогон проверки. True — контроль кусается.
- L1177 `_control_take_anchor_ignored()` — Якорь не читается — тейк всегда от входа.
- L1185 `_control_take_level_uses_this_bar_average()` — Уровень считается по ТВХ ПОСЛЕ долива этого же бара.
- L1193 `_control_trail_gets_the_level_price()` — Трейл исполняется по уровню, а не по доступной цене.
- L1199 `_control_trail_arms_and_exits_in_one_bar()` — Взвод переставлен ПЕРЕД выходом — трейл срабатывает в баре взвода.
- L1211 `_control_trail_peak_grows_on_a_quote_bar()` — Максимум трейла растёт и на минуте без единого принта.
- L1223 `_control_short_rungs_fill_by_long_rule()` — Доливы шорта ищут НИЗ бара — лестница вверх не набирается.
- L1232 `_control_short_take_level_not_mirrored()` — Уровень цели считается вверх у обеих сторон.
- L1240 `_control_short_pnl_sign_not_mirrored()` — Знак исхода не зеркалится — падение цены у шорта в минус.
- L1248 `_control_short_fence_compares_downwards()` — Забор шорта требует ликвидации СНИЗУ — плечо выходит любым.
- L1256 `TESTS = [test_open_mark_equals_the_simulation_p…`
- L1300 `CONTROLS = [('доливы шорта по правилу лонга', _con…`
- L1330 `main()`

## research/dca_ladder/test_run_d10.py · 497 строк

Проверки замера D10 — короткие DCA-книги: плечо, доливы, цель, гейт.

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L33 `H = 3600`
- L34 `LEVELS = np.array([98.0, 95.0, 90.0, 102.0, 105.…`
- L38 `_short_leg(at, sym='SSSUSDT', fwd=60.0, rr=2.0, fav=-500.0)`
- L45 `_with_levels(fn)`
- L54 `_cells(bars, at, g=None)` — Все ячейки одного короткого решения на подставных барах.
- L62 `test_grid_is_declared_before_the_run()`
- L76 `test_gate_of_splits_legs_by_ratio_and_edge()`
- L89 `test_ref_cell_reproduces_the_book_short_leg_bit_for_bit()` — Ячейка правила книги — та же позиция, что считает бумажная книга.
- L109 `test_leverage_cap_binds_and_fence_is_kept()`
- L126 `test_none_arm_keeps_the_fence_leverage_of_the_ladder()` — Без доливов — то же плечо, что забор выдал ЛЕСТНИЦЕ, не 1×.
- L142 `test_sigma_rungs_sit_above_entry_for_a_short()`
- L160 `test_take_axis_orders_the_targets()` — ×1 ближе ×2 ближе ×3: тейк раньше, а дальняя цель на этом пути не достигается вовсе.
- L178 `test_wrong_side_promise_drops_the_decision()` — Обещание шорта НЕ вниз — цели нет, решения нет (не ноль).
- L190 `test_net_column_subtracts_the_round_on_filled_notional()`
- L205 `_rec(sym, at, state='closed')`
- L211 `test_common_sample_is_one_for_all_cells()`
- L221 `_legs(at, sym, n=10, rr_cycle=(2.0, 1.2, 1.7))`
- L232 `test_short_legs_stream_equals_the_reference_loader()` — Потоковый читатель листов даёт ТЕ ЖЕ короткие ноги под гейтом и в том же порядке, что `legs_from_sheets` с по…
- L275 `test_memory_guard_stops_the_run_above_the_limit()` — Прогон, переросший предел памяти, останавливает себя сам — с числом и причиной, до того как ядро убьёт часово…
- L302 `test_run_end_to_end_synthetic()` — run → verdict → report на подставных барах: шорт-неудачник и шорт-победитель; гейты делят ноги на три группы.
- L353 `test_main_writes_smoke_artifacts_and_publishes_by_default()`
- L383 `_poison(path, lit, sub, fn, mod)` — --- отрицательные контроли ------------------------------------------------
- L408 `P = os.path.join(HERE, 'run_d10.py')`
- L411 `_control_cap_ignored()`
- L417 `_control_none_arm_forced_to_1x()`
- L423 `_control_sigma_side_flipped()`
- L429 `_control_net_without_cost()`
- L435 `_control_gate_ignores_ratio()`
- L441 `_control_sample_is_per_cell()`
- L447 `_control_wrong_side_promise_accepted()`
- L453 `TESTS = [test_grid_is_declared_before_the_run, …`
- L470 `_control_memory_guard_never_stops()`
- L475 `CONTROLS = [('сторож памяти не останавливает', _co…`
- L487 `main()`

## research/dca_ladder/test_run_d2.py · 207 строк

Тест чистой логики D2 — построение структурных рунгов.

- L11 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L16 `test_rungs_below_with_reserve()`
- L24 `test_rungs_skip_too_close()`
- L31 `test_rungs_ignore_above()`
- L38 `test_rungs_cap_at_n()`
- L45 `test_split_window()`
- L57 `test_split_window_no_future()`
- L65 `test_px_at()`
- L76 `_hedge_case()` — Синтетика для бета-хеджа: build_levels пусто → один рунг, плечо 1×; BTC ПАДАЕТ за окно → короткий BTC даёт пл…
- L96 `test_hedge_arm_arithmetic()`
- L129 `test_short_stats_diversify_measure()`
- L149 `_control_flat_btc()` — Если BTC не движется (be == bx), хедж = 0 и SH == S — проверка «SH выше S при падении BTC» обязана упасть. До…
- L165 `_control_no_gap_check()` — Без проверки запаса слишком близкие уровни попали бы в рунги — тест «слишком близкий пропущен» обязан упасть.
- L185 `TESTS = [test_rungs_below_with_reserve, test_ru…`
- L198 `main()`

## research/dca_ladder/test_run_d3.py · 427 строк

Тесты D3 — граница забора, портрет хвоста, покрытие опционами.

- L20 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `LEVELS = np.array([98.0, 95.0, 90.0])`
- L27 `FLAT_MMR = 0.02`
- L30 `_bars(t0=1700000000, pre=1440, drop_to=40.0, steps=120)` — 1440 минут ровного рынка у 100, затем плавный сход до `drop_to`.
- L46 `_leg(at)`
- L54 `_cells(bars=None, at=None)`
- L67 `test_hard_1x_cannot_liquidate()`
- L89 `test_floor_cuts_before_liquidation()`
- L103 `test_features_are_ex_ante()`
- L117 `test_auc_ties_and_separation()`
- L134 `_calib(n=500, k=50, noise_feats=20, seed=7)`
- L145 `test_family_bar_calibration()`
- L165 `test_avoid_keeps_unmeasured()`
- L185 `test_crosscheck_reports_mismatch()`
- L209 `test_options_cover_aliases()`
- L233 `class _Src` — Подставной источник баров: тот же контракт, что `sweep.read_bars`.
  - L236 `_Src.__init__(self, by_sym)`
  - L239 `_Src.bars(self, sym, a, b)`
- L243 `test_run_end_to_end_synthetic()`
- L290 `test_window_stats_needs_history()`
- L305 `_control_hard_1x_from_fence()` — Если строка «1×» начнёт брать плечо у забора, гарантии не станет — проверка «1× не ликвидируется» обязана упа…
- L320 `_control_ranks_without_ties()` — Ранги без усреднения ничьих: признак-константа получит AUC ≠ 0.5 и «разделит» — проверка AUC обязана упасть.
- L336 `_control_bar_without_null()` — Планка без нуля (ноль вместо процентиля перестановок): шум пройдёт — калибровочная пара обязана упасть.
- L352 `_control_avoid_drops_unmeasured()` — Если правило выбрасывает позиции с неизмеримым признаком, ему приписывается чужая польза — проверка обязана у…
- L380 `_control_floor_ignored()` — Пол, не доезжающий до симулятора, оставил бы колонку украшением — проверка пола обязана упасть.
- L395 `TESTS = [test_hard_1x_cannot_liquidate, test_fl…`
- L408 `CONTROLS = [('жёсткий 1× берёт плечо у забора', _c…`
- L417 `main()`

## research/dca_ladder/test_run_d4.py · 266 строк

Тесты D4 — книжный хедж.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `H = D4.HOUR`
- L27 `_flat_book(n=6, crash_at=3, hit=-0.1)` — Книга из постоянной экспозиции: обвал ровно в один час, рынок с ней.
- L41 `test_hedge_cannot_see_the_crash()` — Хедж не может быть включён в час, просадкой которого он и вызван.
- L64 `test_switching_costs_are_charged()` — Издержки берутся с ИЗМЕНЕНИЯ нотионала: включил и выключил — круг.
- L79 `test_null_uses_same_duty()` — Нуль включает хедж на столько же часов — иначе сравнивают разное.
- L95 `test_end_to_end_and_crosscheck()` — Сквозной прогон: свод обязан сойтись с суммой исходов позиций.
- L139 `test_beats_null_needs_both()` — «Бьёт нуль» — это И итог выше 95-го процентиля, И просадка мельче.
- L173 `_control_hedge_sees_current_hour()` — Размер по ТЕКУЩЕМУ часу (заглядывание) — проверка обязана упасть.
- L212 `_control_costs_ignored()` — Бесплатное переключение — проверка издержек обязана упасть.
- L226 `_control_crosscheck_blind()` — Свод без сверки (остаток объявлен нулём) — сквозной тест обязан упасть, потому что расхождение перестало бы б…
- L247 `TESTS = [test_hedge_cannot_see_the_crash, test_…`
- L251 `CONTROLS = [('хедж видит текущий час', _control_he…`
- L256 `main()`

## research/dca_ladder/test_run_d5.py · 486 строк

Тесты D5 — линейка забора (глубины лестницы против движений монеты).

- L44 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L53 `LOOK = lambda notl: L.mmr_for_notional([], not…`
- L54 `ENTRY = 100.0`
- L55 `RUNGS = [100.0, 98.0, 95.0, 90.0]`
- L58 `test_sigma_ruler_gives_wild_less_leverage()` — Главное утверждение: та же лестница, разная монета — разное плечо.
- L78 `test_no_sigma_no_leverage()` — Нет меры и ноль — оба 1×, а не потолок.
- L95 `test_buffer_never_shallower_than_ladder()` — Ликвидация не встаёт выше последнего планового долива.
- L120 `test_anchor_matches_live_path()` — Ячейка ("depth", 2.0) обязана дать плечо живого пути D2/D4.
- L140 `test_hold_time_from_entry_not_window()` — Время в позиции: от входа, ноль законен, потолок — предел удержания.
- L174 `_anchor(cell, n, hours)` — Прогон сверки якоря на подставленной ячейке.
- L196 `test_anchor_separates_growth_from_defect()` — Живой случай 2026-09-04: журнал вырос, счёт не разошёлся.
- L225 `test_exposure_and_deposit_math()` — Две нормировки дохода не смешиваются и обе названы.
- L257 `test_run_end_to_end_synthetic()` — Сквозной прогон: run → report, обе единицы и сверка якоря.
- L319 `_control_sigma_zero_allowed()` — Без защиты от нулевой σ замороженный ряд получает потолок плеча.
- L334 `_control_buffer_may_be_shallower()` — Без `max(N·σ, d_max)` ликвидация встаёт внутрь лестницы.
- L360 `_control_sigma_ruler_is_depth()` — Если σ-линейка втайне считает запас по лестнице, различия нет.
- L377 `_control_hold_from_window_start()` — Отсчёт от начала окна признаков добавил бы сутки каждой позиции.
- L404 `_control_anchor_blames_growth()` — Прежняя сверка: любое поле строго, рост журнала = «читать нельзя».
- L419 `_control_one_normalisation_only()` — Одна строка вместо двух: доход на депозит теряется молча.
- L444 `_control_anchor_never_complains()` — Молчаливая сверка якоря: расхождение обязано попадать в отчёт.
- L458 `TESTS = [test_sigma_ruler_gives_wild_less_lever…`
- L467 `CONTROLS = [('нулевая σ пропускается', _control_si…`
- L476 `main()`

## research/dca_ladder/test_run_d6.py · 663 строк

Тесты D6 — нормировка кассы.

- L28 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L34 `H = D6.HOUR`
- L37 `_rec(at, hold_h=1.0, pnl=0.1, lev=4.0, fwd=100.0, sym='AAAUSDT')` — Позиция с готовым исходом: раздаче больше ничего не нужно.
- L45 `test_budget_is_respected()` — Шесть мест — не больше шести позиций разом, сколько ни предлагай.
- L59 `test_money_returns_before_it_is_spent()` — Закрытие в ту же секунду освобождает кассу до нового входа.
- L78 `test_min_notional_rejects_not_rounds()` — Мелкий ордер отвергается, и причина считается отдельной колонкой.
- L92 `test_leverage_sets_the_ticket()` — Меньше плечо — крупнее минимальный кусок депозита, у́же книга.
- L109 `test_best_first_within_a_second()` — Внутри секунды деньги достаются лучшим по |прогноз|, не первым.
- L121 `test_deposit_units_and_curve()` — Доход и просадка считаются в долях ДЕПОЗИТА, а не позиции.
- L134 `test_report_names_both_refusals()`
- L148 `test_concentration_names_one_coin()` — Итог, принадлежащий одному имени, обязан быть виден числом.
- L172 `_pc(x)`
- L176 `test_report_carries_concentration()` — Число, не доехавшее до отчёта, владельцу не существует.
- L197 `_control_no_concentration()` — Итог без лучшего имени, равный итогу, — колонка ничего не считает.
- L216 `test_window_is_measured_and_reported()` — Доход в процентах без окна не читается — окно обязано быть в отчёте.
- L238 `test_restat_says_the_journal_grew()` — Окно, дописанное позже прогона, обязано назвать хвост числом.
- L255 `test_percent_of_deposit_is_invariant_to_deposit()` — Пока пол биржи не связывает, процент к депозиту от депозита не зависит.
- L282 `test_scale_invariance_holds_on_the_cash_boundary()` — Тот же набор сделок — тот же процент, на любом депозите.
- L305 `test_deposit_anchor_catches_a_broken_measure()` — Расхождение при СОВПАВШЕМ наборе — сломанная мера, не находка.
- L340 `test_peak_open_separates_lots_from_names()` — Пик в ЛОТАХ и пик в ИМЕНАХ — разные числа, и оба обязаны быть.
- L363 `test_one_per_name_skips_repeats()` — Строгое правило биржи: повтор по открытому имени не берётся.
- L379 `test_full_cover_takes_every_signal()` — Депозит полного охвата берёт ВСЕ и выводится из слабейшего плеча.
- L412 `test_report_carries_full_cover()` — Число, не доехавшее до отчёта, владельцу не существует.
- L432 `_control_lots_as_names()` — Пик лотов, выданный за пик имён, — ровно то, что нашёл владелец.
- L452 `_control_no_full_cover()` — Билет от МЕДИАННОГО плеча вместо слабейшего — охват неполон.
- L474 `_control_no_window()` — Отчёт без окна — доход в процентах непонятно за что.
- L488 `_control_blind_anchor()` — Опора, объявляющая совпадением всё подряд, не проверяет ничего.
- L508 `_control_no_budget()` — Без вычета маржи любая доля берёт всё — ширина побеждает даром.
- L528 `_control_no_min_notional()` — Без минимума биржи мелкий ордер проходит, и книга шире, чем можно.
- L544 `_control_arrival_order()` — Раздача по порядку прихода: узкая книга берёт случайные сигналы.
- L559 `test_open_drawdown_is_not_the_equity_drawdown()` — Просадка ОДНОВРЕМЕННО ОТКРЫТЫХ — своя величина (вопрос владельца).
- L589 `_control_open_dd_counts_the_closing_hour()` — Час закрытия попал в открытые — реализованное выдано за отметку.
- L596 `_poison_d6(lit, sub, fn)` — Подделка строки `run_d6` и прогон проверки.
- L624 `TESTS = [test_budget_is_respected, test_money_r…`
- L640 `CONTROLS = [('бюджет не вычитается', _control_no_b…`
- L653 `main()`

## research/dca_ladder/test_run_d7.py · 283 строк

Проверки замера срока D7. Главная — усечение равно прямой симуляции.

- L7 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L8 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L15 `M = 60`
- L16 `H = 3600`
- L17 `T0 = 1700000000`
- L20 `_bars(path, t0=T0)` — Минутные бары из ряда цен: (t, o, h, l, c, v).
- L29 `_walk(n, f)`
- L33 `_rec(bars, holds, at=T0, take=None, rungs=None, lev=3.0)` — Запись, как её строит `one_position`: исход, трек и контрольные точки. Фикстура повторяет сборку записи, а не…
- L51 `test_truncation_equals_direct_simulation()` — Усечение обязано дать ТО ЖЕ, что прямая симуляция с этим сроком.
- L82 `test_marks_sum_to_the_truncated_outcome()` — Сумма почасовых приращений обязана равняться исходу сделки.
- L100 `test_sample_is_common_to_all_holds()` — Запись, не дожившая до самого длинного срока, выбрасывается ЦЕЛИКОМ.
- L121 `test_shorter_hold_frees_the_name_and_the_slot()` — Срок меняет не только исход, но и ОБОРОТ: имя и место освобождаются.
- L142 `test_grid_is_declared_and_holds_the_reference()` — Сетка объявлена до прогона и содержит нынешнее правило книги.
- L155 `test_halves_split_by_time_and_never_overlap()` — Половины окна режутся ПО ВРЕМЕНИ решения и не пересекаются.
- L188 `_control_truncate_ignores_checkpoint()` — Усечение берёт исход полной сделки вместо переоценки на границе.
- L202 `_control_marks_not_fixed()` — Приращения обрезаны, но не поправлены: сумма разойдётся с исходом.
- L229 `_control_sample_not_common()` — Выборка не общая: короткая запись остаётся на коротких сроках.
- L243 `_control_halves_split_by_index()` — Половины режутся по порядку списка, а не по времени решения.
- L258 `TESTS = [test_truncation_equals_direct_simulati…`
- L265 `CONTROLS = [('усечение игнорирует контрольную точк…`
- L273 `main()`

## research/dca_ladder/test_run_d8.py · 365 строк

Проверки замера тейка D8.

- L19 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L20 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L31 `FLAT_MMR = 0.02`
- L34 `_look(notl)`
- L38 `_dip_then_rise(t0=1700000000, pre=1440, low=94.0, top=112.0, po…` — Ровный рынок, потом провал к `low`, рост до `top` и плато.
- L67 `_legs(at, n=40, sym='AAAUSDT')`
- L77 `_with_levels(fn)`
- L86 `test_book_cell_reproduces_the_book_rule()` — Ячейка правила книги == сама книга (`D6.one_position`) бит в бит.
- L125 `test_take_rule_is_read_from_the_book_not_hardcoded()` — Доля цели равна `обещание × TAKE_MULT` — числом, а не на словах.
- L141 `test_decisions_before_the_rules_change_are_backtest()` — Решение старше границы версии правил — бэктест по построению.
- L160 `test_avg_anchor_exits_earlier_and_pays_the_filled_notional()` — Тейк от ТВХ выходит раньше и платит `нотионал × доля` тождественно.
- L177 `test_normalised_weights_deploy_the_whole_notional()` — Диагностическая рука: при одном рунге работает ВЕСЬ нотионал.
- L204 `test_sigma_missing_drops_the_decision_everywhere()` — σ не измерена — решение не считается НИ ОДНОЙ ячейкой.
- L221 `test_common_sample_is_one_for_all_cells()` — Решение, не закрытое хотя бы в одной ячейке, уходит из ВСЕХ.
- L236 `test_run_end_to_end_synthetic()` — Сквозной прогон: run → отчёт. Дороги отчёта `py_compile` не видит.
- L261 `_poison(path, lit, sub, fn, mod)`
- L286 `_control_weights_not_normalised()` — Нормировка снята — диагностическая рука повторяет базовую.
- L294 `_control_missing_sigma_becomes_zero()` — σ без меры подменена нулём — цель в ноль процентов.
- L302 `_control_sample_is_per_cell()` — Выборка считается по каждой ячейке отдельно.
- L310 `_control_grid_ignores_the_anchor()` — Сетка строится одним якорем — ячейка книги её не воспроизводит.
- L318 `_control_take_multiplier_dropped()` — Множитель цели снят — книга торгует не тем, чем её судят.
- L326 `_control_rules_boundary_ignored()` — Граница версии правил снята — пересчёт красится во «вперёд».
- L334 `TESTS = [test_book_cell_reproduces_the_book_rul…`
- L345 `CONTROLS = [('веса не нормируются', _control_weigh…`
- L355 `main()`

## research/dca_ladder/test_run_d9.py · 518 строк

Проверки замера D9 — варианты выхода коротких DCA-книг.

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `H = 3600`
- L28 `T0 = T7.T0`
- L29 `N = 170 * 60`
- L30 `TAKE = 100.5`
- L33 `_path_loser_recovers()` — Минус к 24 ч, плоско до 48 ч, к 70 ч доходит до тейка.
- L46 `_path_winner_flat()` — Плюс к 24 ч и плоско дальше: до тейка не доходит никогда.
- L51 `_path_level_early()` — Тейк задет к пятому часу — раньше любого T сетки.
- L56 `_rec(path, sym)`
- L62 `_same(a, b)`
- L67 `test_grid_is_declared_before_the_run()`
- L83 `test_timer_equals_d7_truncation()` — Ячейка A — ровно усечение D7, бит в бит; своего счёта у неё нет.
- L95 `test_cut_losers_at_T_and_hold_the_rest_to_H()` — B: минус глубже θ режется на T, остальное живёт до H.
- L120 `test_lock_winners_is_the_mirror()` — C: плюс фиксируется на T, минус держится до H — зеркало B.
- L134 `test_level_exit_before_T_is_untouched_by_every_variant()` — Тейк к пятому часу: ни один вариант не вправе его переписать.
- L147 `test_aggr_is_the_base_pass_under_its_leverage_gate()` — `aggr_s` — записи `optimal_s` при плече не ниже гейта режима.
- L160 `test_cell_goes_through_the_book_cash()` — Ячейка — касса и форма книги: взято обеих, раскладка d9 честная.
- L172 `_rise_then_fall(t0=1700000000, pre=1440, top=106.0, low=90.0, p…` — Путь ШОРТА-неудачника: рост к 24 ч (доливы вверх), плоско, потом падение до цели к ~65 ч и плато до 170 ч — в…
- L192 `_drift_down(t0=1700000000, pre=1440, post=10500)` — Путь шорта-победителя: −0.5 % к 24 ч и плоско — цели не достигает.
- L206 `_legs(at, side, sym, n=10)`
- L217 `test_run_end_to_end_synthetic()` — Сквозной прогон run → report на подставных барах обеих сторон.
- L268 `_stub_summary(flip_c=False, neg=False)` — Свод по образцу живого: одна короткая книга, депозит один.
- L315 `test_verdict_is_derived_from_paired_numbers_on_both_halves()` — Вердикт — из парной разности и её знака на половинах, не из прозы.
- L361 `test_main_publishes_by_default_and_not_with_the_flag()`
- L389 `_with_decide(bad, test)` — --- отрицательные контроли ---------------------------------------------
- L402 `_control_theta_ignored()` — B режет любой минус, порог θ не читается.
- L410 `_control_cut_regardless_of_mark()` — B закрывает на T всё открытое, отметку не смотрит.
- L420 `_control_level_exit_overridden()` — Вариант судит и позицию, вышедшую по уровню раньше T.
- L437 `_control_gate_not_applied()`
- L450 `_control_verdict_ignores_the_sign()` — Фраза «в плюс не выводит» стоит литералом, а не выводится из чисел.
- L469 `_control_stability_ignores_halves()` — «Устойчива» = «лучше на целом», половины не спрашиваются.
- L489 `TESTS = [test_grid_is_declared_before_the_run, …`
- L500 `CONTROLS = [('θ не читается', _control_theta_ignor…`
- L508 `main()`

## research/dca_ladder/test_run_dca.py · 141 строк

Тесты чистых помощников реплея D1 — без хранилища A2.

- L13 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `test_daily_sigma_known()`
- L31 `test_daily_sigma_takes_last_of_day()`
- L42 `test_slice_window()`
- L52 `test_entry_dates_stride()`
- L60 `test_measures_numbers()`
- L81 `test_measures_empty_is_none_not_zero()`
- L90 `test_measures_no_winners_bite_none()`
- L102 `_control_bite_against_all()` — Укус, посчитанный по медиане ВСЕХ (а не прибыльных), даёт другое число — значит выбор знаменателя нагружен, и…
- L110 `_control_empty_returns_zero()` — Если бы measures на n=0 возвращал 0 вместо None, edge-тест упал.
- L116 `TESTS = [test_daily_sigma_known, test_daily_sig…`
- L127 `main()`

## research/dca_paper/test_costs.py · 456 строк

Проверки замера издержек DCA-книг (`costs.py`).

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `H = 3600`
- L27 `T0 = 1790000000.0`
- L28 `FILLS4 = [(T0 + 60, 100.0, 0.25), (T0 + 5 * H, 1…`
- L32 `_row(sym='SSSUSDT', side='short', at=T0, fills=None, exit_ts=No…`
- L47 `_series(start, hours, rate_fn)` — Ряд начислений раз в час: (времена мс, ставки), как у загрузчика.
- L55 `test_commission_charges_every_rung_and_the_exit()`
- L72 `test_funding_sign_follows_the_side()`
- L82 `test_funding_follows_the_open_notional_over_time()` — До долива платит четверть, после — половина: нотионал по времени.
- L97 `test_funding_uncovered_is_not_measured()`
- L109 `test_rate_at_entry_is_the_last_known_and_the_gate_is_by_side()`
- L130 `_fixture()`
- L163 `test_slippage_on_base_entry_and_market_exits_only()` — Проскальзывание X3 берётся с базового входа (первый рунг — рыночный) и с рыночного выхода (пол/срок/трейл/сто…
- L190 `test_run_end_to_end_synthetic()`
- L253 `test_gate_is_judged_only_with_both_arms_of_size()` — Медиана девяти отсечённых — шум: рука судится при ≥ MIN_ARM_N позиций в ОБЕИХ руках, иначе книга не попадает…
- L271 `test_main_writes_the_artifact_and_publishes_by_default()`
- L303 `_poison(path, lit, sub, fn, mod)` — --- отрицательные контроли ------------------------------------------------
- L328 `P = os.path.join(HERE, 'costs.py')`
- L331 `_control_exit_fee_dropped()`
- L336 `_control_funding_sign_flipped()`
- L342 `_control_open_notional_ignores_time()`
- L348 `_control_uncovered_counted_as_zero()`
- L354 `_control_gate_ignores_side()`
- L360 `_control_rate_at_entry_looks_ahead()`
- L365 `_control_stale_rate_counts_as_known()`
- L371 `_control_gate_medians_in_dollars()`
- L377 `_control_missing_series_reads_as_present()`
- L383 `_control_old_rules_rows_counted()`
- L388 `_control_no_fills_in_cover_denominator()`
- L393 `_control_thin_rest_arm_judged()`
- L398 `_control_slip_on_take_exit()`
- L403 `_control_slip_on_every_rung()`
- L409 `_control_net_ignores_slippage()`
- L415 `TESTS = [test_commission_charges_every_rung_and…`
- L427 `CONTROLS = [('комиссия выхода снята', _control_exi…`
- L446 `main()`

## research/dca_paper/test_cut.py · 297 строк

Проверки досчёта оборванных записью позиций (`cut_check.py`).

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L17 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L24 `FAILED = []`
- L27 `check(name, cond, extra='')`
- L34 `_snap(sym, t, mid)` — Строка снимка ровно того вида, что пишет сборщик.
- L49 `_trade(sym, t, px)`
- L55 `_write(root, kind, sym, t, lines)`
- L64 `make_root(sym='AAAUSDT', h0=1756000000 // 3600 * 3600)` — Запись с ДЫРОЙ в ленте посередине и хвостом только в книге.
- L82 `test_book_bars_are_ohlc_and_gaps_are_absent()` — Минутный бар книги: первая/крайние/последняя середина. Минута без снимков ОТСУТСТВУЕТ, а не выходит нулевой (…
- L103 `test_tail_only_prefix_is_untouched()` — Дописывается ТОЛЬКО хвост: всё до последнего принта — те же бары.
- L138 `test_no_tape_means_no_position()` — Ленты нет вовсе — книгой не подменяем: без принтов нет ни входа, ни уровней, и позиция была бы другой сделкой…
- L152 `test_dry_tail_stays_cut()` — Нет книги в хвосте — бары не меняются, символ назван числом.
- L169 `test_data_end_uses_whole_cache()` — Граница записи берётся по ВСЕМУ кэшу, а не по пересчитанному подмножеству: досчитанный хвост двигает `end_ts`…
- L185 `test_state_after_fill_is_closed_by_old_boundary()` — Досчитанная позиция становится закрытой, недосчитанная — нет.
- L206 `test_report_builds_and_shows_both_sides()` — Сборка отчёта исполняется тестом, а не только прогоном.
- L255 `test_run_refuses_when_the_rule_is_already_in_the_book()` — Правило внедрено — замер обязан отказать СЛОВАМИ, а не дать ноль.
- L280 `main()`

## research/dca_paper/test_names.py · 227 строк

Проверки замера соответствия имён режимов.

- L9 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L10 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L16 `H = 3600`
- L17 `T0 = 1700000000`
- L20 `_row(at, hold_h, margin, dep=10000, ruler='optimal', pnl=0.01, …`
- L28 `test_load_is_money_weighted_by_time()` — Загрузка — деньги, взвешенные ВРЕМЕНЕМ, а не доля сделок.
- L52 `test_verdict_follows_the_numbers_both_ways()` — Вердикт выводится ИЗ загрузки, а не стоит рядом с ней.
- L81 `test_window_is_common_to_all_modes()` — Окно загрузки — ОДНО на все режимы депозита.
- L104 `test_book_numbers_come_from_the_artifact()` — Свод книги берётся ИЗ АРТЕФАКТА и здесь не пересчитывается.
- L125 `_control_load_by_trade_share()` — Загрузка считается долей сделок, а не деньгами во времени.
- L139 `_control_verdict_always_printed()` — Фраза про недогруз печатается всегда — то есть не сообщает ничего.
- L157 `_control_book_recomputed_here()` — Свод книги считается на месте вместо чтения артефакта.
- L178 `_control_window_per_mode()` — Каждый режим мерится СВОИМ окном — недогруз становится невидим.
- L206 `TESTS = [test_load_is_money_weighted_by_time, t…`
- L211 `CONTROLS = [('загрузка по доле сделок', _control_l…`
- L217 `main()`

## research/dca_paper/test_paper.py · 2390 строк

Проверки бумажных DCA-книг. Прогон: .venv/bin/python …/test_paper.py

- L11 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L12 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L21 `H = 3600`
- L22 `LAST_RUN = {}`
- L31 `T0 = (int(R.RULES_SINCE) // H + 1) * H` — Момент фикстур стоит ПОСЛЕ границы версии правил (`R.RULES_SINCE`): решение старше неё есть бэктест по постро…
- L34 `_rec(at, hold_h=1.0, pnl=0.1, lev=4.0, fwd=100.0, sym='AAAUSDT'…` — Запись позиции, КАК ЕЁ ПИШЕТ живой реплей.
- L52 `test_ticket_clears_the_exchange_floor()` — Билет обязан пережить ХУДШЕЕ плечо, иначе часть сигналов неисполнима.
- L75 `test_ticket_is_squeezed_between_the_floor_and_the_peak()` — Билет зажат полом РЕЖИМА снизу и его же пиком сверху.
- L103 `test_ticket_rule_is_one_formula_for_every_mode()` — Билет не является отдельной осью: формула одна, числа свои.
- L125 `test_gated_mode_is_deployed_at_its_own_peak()` — Режим с гейтом вложен на СВОЁМ пике, а не на чужом.
- L153 `test_one_per_name_applied_before_cash()` — Правило биржи не зависит от депозита и применяется ДО раздачи.
- L170 `test_backtest_and_live_share_one_curve_and_stay_labelled()` — Кривая одна (решение владельца), но группы остаются числами.
- L207 `test_take_steps_follow_the_floating_average()` — Цель ступенчата: якорь — плавающая ТВХ, и долив опускает обе.
- L249 `test_row_side_is_the_record_then_the_book()` — Сторона записи: поле строки, а без него — линейка книги.
- L271 `test_take_frac_comes_from_the_rule_not_from_the_record()` — Доля цели ВЫВОДИТСЯ из обещания правилом, а не хранится числом.
- L290 `test_fav_backfill_adds_a_field_and_nothing_else()` — Добор обещания дописывает ОДНО поле и не трогает ничего больше.
- L339 `test_open_position_is_not_a_closed_one()` — Позиция, чей срок ещё идёт, — открытая, а не «закрыта по сроку».
- L375 `test_journal_appends_only_new()` — Строка write-ahead не переписывается: момент записи подвинуть нельзя.
- L396 `test_report_names_what_is_not_modelled()` — Отчёт обязан сказать, чего в числах нет, а не подразумевать.
- L406 `test_day_concentration_is_measured_and_not_faked()` — Один эпизод раздаёт деньги многим именам — колонка по именам слепа.
- L451 `test_short_record_says_not_measured_not_zero()` — Три дня из трёх вычитать нечем: прочерк, а не ноль.
- L471 `test_two_rulers_are_two_books_and_optimal_is_untouched()` — Одно решение живёт в ОБЕИХ книгах, и вторая не читается повтором.
- L517 `test_aggressive_gate_takes_only_levered_entries()` — Третий режим = та же линейка глубины плюс ГЕЙТ по плечу.
- L562 `test_declared_peak_is_checked_against_the_measured_one()` — Объявленный пик обязан быть не ниже измеренного, иначе крик.
- L592 `test_legacy_row_reads_as_the_ruler_it_was_written_with()` — Строка без поля `ruler` писана глубиной — и обязана попасть к ней.
- L612 `test_cash_refusals_reach_the_report_and_survive_restat()` — Отказы кассы — прямой ответ «что покупает депозит», и их нельзя терять пересборкой свода: `--restat` ничего н…
- L677 `_cache_run(cache_seed, legs, td)` — Настоящий `main` с подставным дорогим проходом.
- L733 `test_journal_path_is_resolved_at_call_time()` — Прогон с подменённым журналом не смеет писать в НАСТОЯЩИЙ.
- L764 `test_cache_replays_new_and_open_but_not_closed()` — Кэш реплея законен ровно для ЗАКРЫТЫХ позиций.
- L805 `test_cache_of_other_rules_is_refused_out_loud()` — Кэш чужих правил не чинится молча.
- L838 `test_rules_change_starts_a_fresh_record()` — Смена правил (билета) начинает запись заново, а не дописывает.
- L867 `_control_no_split()` — Свод, складывающий наблюдение с пересчётом, — то, ради чего split.
- L881 `_control_ticket_below_floor()` — Билет ниже пола биржи — часть сигналов физически неисполнима.
- L895 `_control_one_per_name_off()` — Без правила биржи повтор по имени попадает в книгу.
- L909 `_control_journal_overwrites()` — Журнал, переписывающий строку, позволяет подвинуть момент записи.
- L930 `_control_day_concentration_by_one_day()` — Контроль: вычесть ОДИН лучший день вместо трёх — проверка обязана пасть.
- L955 `_control_dedup_without_ruler()` — Контроль: дедуп без линейки — вторая книга не пишется вовсе.
- L969 `_control_legacy_reads_as_safe()` — Контроль: прежняя строка объявлена безопасной — книга подменена.
- L983 `_control_restat_drops_the_counts()` — Контроль: пересборка молча выбрасывает числа счётного прогона.
- L1001 `_control_dedup_without_rules_version()` — Контроль: дедуп БЕЗ версии правил — прежнее поведение дословно.
- L1031 `_control_contracts_are_money_not_coins()` — Контроль: контракты посчитаны ДЕНЬГАМИ рунга, а не монетами.
- L1062 `_control_walk_ignores_side()` — Контроль: ступени цели считаются без стороны (длинная геометрия).
- L1085 `_control_row_side_ignores_book()` — Контроль: сторона артефактной записи берётся умолчанием `ruler_of`, а не переданной книгой — короткая книга ч…
- L1104 `_control_gate_is_gone()` — Гейта нет вовсе: третий режим молча становится копией второй книги.
- L1124 `_control_gate_on_every_ruler()` — Порог назначен всем режимам: книга без поля теряет свои входы.
- L1138 `test_shape_counts_positions_not_days()` — Доля прибыльных СДЕЛОК и среднее время в сделке — свои меры.
- L1183 `test_worst_open_is_measured_and_missing_is_not_zero()` — Худшая ОТКРЫТАЯ позиция считается сервером, а пустое — прочерк.
- L1208 `test_journal_rotates_by_day_and_reader_takes_every_part()` — Ротация: запись идёт в СУТОЧНЫЙ файл по метке решения, а чтение берёт все куски и снимает перекрытие.
- L1273 `test_watchdog_runs_the_book_hourly_and_asks_when_it_last_counte…` — Сторож ведёт книгу САМ, и вопрос он задаёт правильный.
- L1297 `_run_watchdog_cases(block)`
- L1364 `test_tail_marks_outcomes_and_refuses_an_entry_from_a_quote()` — Правило хвоста держит ОБЕ границы, и они про разное.
- L1407 `test_tail_reaches_the_core_and_the_replay_signature()` — Дорога правила до ядра и до кэша — отдельный предмет.
- L1440 `test_cut_position_gets_a_named_reason()` — Оборванная позиция получает ПРИЧИНУ, и причин три разных.
- L1486 `test_contracts_walk_matches_the_simulation()` — Контракты позиции = то, что купила симуляция, а не второй счёт.
- L1528 `test_short_books_are_declared_as_a_mirror()` — Реестр несёт шесть книг, и у коротких сторона объявлена полем.
- L1547 `test_take_rule_mirrors_the_promise_side()` — Цель шорта берётся у обещания ВНИЗ; лонг считается прежним числом.
- L1562 `test_short_legs_go_only_into_short_books()` — Нога идёт в книгу СВОЕЙ стороны, и обе стороны считаются одним проходом.
- L1602 `test_venue_cap_is_in_the_replay_signature()` — Предел плеча площадки входит в ПОДПИСЬ реплея.
- L1614 `test_venue_leverage_cap_reaches_the_fence()` — Предел плеча ПЛОЩАДКИ доезжает до забора, а не остаётся правилом.
- L1663 `test_replay_cache_asks_only_for_its_own_side()` — Кэш спрашивают парой СВОЕЙ стороны — иначе пересчёт вечен.
- L1684 `_smooth_rows(pairs, mode='optimal', dep=10000.0)` — Журнал из пар «(деньги лонга, деньги шорта)» по суткам.
- L1698 `test_smoothing_finds_it_and_stays_silent_without_it()` — Калибровка меры: находит сглаживание и молчит на его отсутствии.
- L1726 `test_journal_shard_rolls_over_by_size()` — Часть суточного файла ограничена по РАЗМЕРУ, и читатель видит все.
- L1762 `test_repack_splits_an_oversized_day()` — Перепаковка режет переросшие сутки и не теряет ни одного решения.
- L1801 `test_smoothing_reads_the_journal_pair()` — Дорога замера до журнала, а не только его формула.
- L1827 `test_smoothing_splits_the_capital_of_two_books()` — У пары книг капитал ВДВОЕ: их проценты не складываются в один.
- L1845 `TESTS = [test_smoothing_finds_it_and_stays_sile…`
- L1888 `_control_journal_path_frozen()` — Путь журнала снова берётся значением по умолчанию: прогон с подменённым журналом пишет в настоящую запись кни…
- L1911 `_control_cache_reuses_open()` — Состояние в кэше не читается: открытая позиция берётся вчерашней.
- L1939 `_control_cache_sig_ignored()` — Подпись правил не сверяется: кэш чужой геометрии молча идёт в дело, и книга новых правил считалась бы наполов…
- L1971 `_control_floor_one_for_everyone()` — Пол назначен один на всех: режим с гейтом не может взять мелкий билет, и на $1k у него остаётся вчетверо мень…
- L1987 `_control_peak_from_the_pool()` — Пик берётся общий (прежнее поведение): режим с гейтом снова стоит недогруженным — ровно тот дефект, ради кото…
- L2002 `_control_state_ignored()` — Состояние позиции не читается: живая попадает в журнал закрытой — ровно тот дефект, ради которого состояние и…
- L2027 `_control_win_counts_days()` — Доля прибыльных считается по ДНЯМ, а не по сделкам: день с двумя плюсами и одним минусом объявляется целиком…
- L2048 `_control_missing_mark_reads_as_zero()` — Позиция без отметки читается ровной: «не измерено» подменяется нулём — ровно тот класс, от которого защищает…
- L2069 `_control_watchdog_asks_mtime()` — Сторож снова смотрит на mtime файла вместо метки счёта.
- L2094 `_poison_run_paper(lit, repl, probe)` — Прогнать `probe` на ИСПОРЧЕННОМ `run_paper.py` и вернуть файл.
- L2129 `_control_shard_ignores_size()` — Ротация только суточная — часть перерастает порог.
- L2147 `_control_repack_drops_the_tail()` — Перепаковка пишет только первую часть — решения теряются.
- L2170 `_control_smoothing_takes_the_pair_as_rows()` — Пара взята целиком за строки — дорога обязана упасть.
- L2195 `_control_tail_never_reaches_the_core()` — Хвост построен, но в дорогой проход не подан.
- L2207 `_control_tail_out_of_the_replay_signature()` — Подпись реплея не знает хвоста: кэш прежних правил взялся бы молча.
- L2214 `_control_venue_cap_out_of_the_replay_signature()` — Подпись реплея не знает предела площадки: кэш, посчитанный забором без предела, взялся бы молча — и книга ост…
- L2223 `_control_tail_entry_from_a_quote_allowed()` — Граница входа снята: хвост заводит сделки, которых у книги не было.
- L2247 `_control_cut_reason_is_one_for_all()` — Причина обрыва одна на всех: «книги нет вовсе» приписывается и тому имени, у которого книга дотянулась дальше…
- L2263 `_control_cut_reason_by_symbol_not_position()` — Причина берётся ПО ИМЕНИ: книга, дотянувшаяся у соседнего окна, объявляется дотянувшейся и здесь. Тогда «книг…
- L2285 `_control_venue_cap_not_passed()` — Забор зовут без предела площадки — дорога обязана упасть.
- L2329 `CONTROLS = [('хвост не доезжает до ядра', _control…`
- L2380 `main()`

## research/dca_paper/test_slip_x3.py · 76 строк

Проверки `slip_x3.py`: решение ↔ открытие по ключу позиции, знак по стороне, отсутствие цены сигнала — пропус…

- L10 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L15 `_journal(rows)`
- L24 `_dec(arm, hour, sym, side, px)`
- L29 `_open(arm, hour, sym, side, entry_px, notl=100.0)`
- L34 `test_pairs_and_signs_by_side()`
- L66 `test_missing_journal_is_named()`

## research/f1_carry/test_carry.py · 216 строк

Тесты ядра F1 на известных ответах.

- L21 `BP = 0.0001`
- L24 `class TestWeights`
  - L26 `TestWeights.test_gross_is_one_and_legs_equal(self)`
  - L34 `TestWeights.test_top_score_goes_long(self)` — Соглашение проекта: положительная оценка = «покупаем».
  - L46 `TestWeights.test_nan_score_gets_no_weight(self)`
  - L53 `TestWeights.test_too_thin_section_gives_no_book(self)`
- L59 `class TestDecompose`
  - L61 `TestDecompose.test_long_pays_positive_rate(self)` — Положительная ставка: лонг ПЛАТИТ, шорт получает.
  - L70 `TestDecompose.test_short_earns_positive_rate(self)`
  - L77 `TestDecompose.test_parts_sum_to_gross(self)`
  - L90 `TestDecompose.test_missing_observation_is_dropped_not_zeroed(self)` — Ноль означал бы «цена не двигалась» — наблюдение, которого не было. Вес такого актива обязан попасть в `dropp…
- L104 `class TestPositionReturn` — Перевод накопленного логарифма в доходность позиции.
  - L112 `TestPositionReturn.test_long_cannot_lose_more_than_everything(self)`
  - L118 `TestPositionReturn.test_short_loss_is_unbounded(self)` — У шорта убыток сверху не ограничен ничем: актив, выросший в 13 раз, стоит позиции 1194 %, а не 256 %.
  - L125 `TestPositionReturn.test_small_moves_are_almost_unchanged(self)` — На величинах, которыми живёт медиана книги, поправка пренебрежима — поэтому дефект и не был виден в средних.
  - L131 `TestPositionReturn.test_short_side_sign(self)` — Актив упал — шорт заработал.
  - L137 `TestPositionReturn.test_book_tail_is_worse_than_the_log_approximation(self)` — Проверка направления ошибки на книге из двух ног.
  - L151 `TestPositionReturn.test_the_case_the_spec_predicts(self)` — §5.1: нам платят за покупку падающего.
- L167 `class TestTailRatio`
  - L169 `TestTailRatio.test_known_value(self)`
  - L173 `TestTailRatio.test_denominator_is_median_of_absolute(self)` — У книги с медианой около нуля модуль медианы взорвал бы отношение в бесконечность, сообщив о хвосте то, чего…
  - L180 `TestTailRatio.test_short_series_gives_nothing(self)`
- L185 `class TestFundingLoader` — Разбор рядов. Колонки ищутся по имени, а не по номеру.
  - L188 `TestFundingLoader.setUp(self)`
  - L194 `TestFundingLoader.test_two_column_bybit_layout(self)`
  - L198 `TestFundingLoader.test_three_column_binance_layout(self)` — Ровно тот случай, который смоук-прогон поймал разложением по ногам: `row[1]` у архива Binance есть число часо…
  - L206 `TestFundingLoader.test_unknown_header_raises(self)`
  - L210 `TestFundingLoader.test_empty_file_raises(self)`

## research/f2_traps/test_traps.py · 140 строк

Тесты ядра F2 на известных ответах.

- L17 `class TestBeta`
  - L19 `TestBeta.test_exact_slope(self)`
  - L27 `TestBeta.test_market_neutral_book_gives_zero(self)`
  - L34 `TestBeta.test_short_market_bet_is_detected(self)` — Ловушка §5.2: книга, оказавшаяся ставкой против рынка.
  - L46 `TestBeta.test_flat_market_gives_nothing(self)`
  - L49 `TestBeta.test_short_series_gives_nothing(self)`
  - L52 `TestBeta.test_rolling_beta_sees_regime_change(self)` — Одно число скрывает смену знака: β +0.5 полгода и −0.5 полгода в среднем даст ноль, и книга покажется нейтрал…
- L65 `class TestMarketReturn`
  - L67 `TestMarketReturn.test_equal_weighted_mean(self)`
  - L71 `TestMarketReturn.test_missing_is_excluded_not_zeroed(self)` — Ноль означал бы «актив не двигался» — наблюдение, которого не было; он занизил бы волну и завысил β книги.
  - L77 `TestMarketReturn.test_all_missing(self)`
- L81 `class TestDelisting`
  - L83 `TestDelisting.test_counts_only_weighted_names_inside_horizon(self)`
  - L91 `TestDelisting.test_already_delisted_does_not_count(self)` — Отрицательный зазор — актив снят в прошлом; в книге его быть не должно вовсе, и записывать это в ловушку буду…
- L101 `class TestRegimeChange`
  - L103 `TestRegimeChange.test_same_rate_per_day_is_not_a_change(self)` — Окна разной длины дают разное ЧИСЛО начислений при неизменном режиме — сравнивать надо начисления в сутки.
  - L109 `TestRegimeChange.test_four_hourly_to_hourly_is_a_change(self)`
  - L113 `TestRegimeChange.test_missing_counts_as_no_change(self)`
  - L117 `TestRegimeChange.test_weighted_share(self)`
- L123 `class TestCapacity`
  - L125 `TestCapacity.test_known_limit(self)` — Позиция 0.5 · $20 000 = $10 000 против оборота $1 млн есть 1 % оборота; предел при 5 % — $100 000.
  - L134 `TestCapacity.test_asset_without_turnover_is_skipped(self)`

## research/f3_nulls/test_nulls.py · 120 строк

Тесты ядра F3. Запуск: python3 -m unittest discover -s research/f3_nulls

- L17 `class TestPermutation`
  - L19 `TestPermutation.test_multiset_is_preserved(self)`
  - L26 `TestPermutation.test_nan_travels_with_values(self)` — Если бы NaN оставались на месте, число участников сечения менялось бы, и нуль отличался бы от прогона не толь…
  - L38 `TestPermutation.test_deterministic_for_same_seed(self)`
- L45 `class TestRandomBook`
  - L47 `TestRandomBook.test_eligibility_is_preserved(self)`
  - L52 `TestRandomBook.test_null1_and_null3_pick_the_same_kind_of_book(self)` — Ключевая проверка: объявленные нуль 1 и нуль 3 совпадают по построению.
- L82 `class TestAlignByName`
  - L84 `TestAlignByName.test_matches_by_name_not_position(self)`
  - L90 `TestAlignByName.test_same_length_does_not_imply_same_assets(self)` — Сечения даты t и t+сдвиг бывают одной длины и разного состава — сопоставление по позиции молча дало бы чужие…
- L97 `class TestStats`
  - L99 `TestStats.test_percentile_known_values(self)`
  - L104 `TestStats.test_percentile_of_ten_is_near_max(self)` — При десяти зёрнах 95-й процентиль почти совпадает с максимумом — поэтому вердикт по нему шумен, и рядом счита…
  - L111 `TestStats.test_sigmas(self)`
  - L115 `TestStats.test_sigmas_need_spread(self)`

## research/factory/test_candidate.py · 199 строк

Проверки реплея кандидата.

- L12 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L18 `FAILED = []`
- L19 `H = 3600.0`
- L22 `check(name, ok, got='')`
- L29 `leg(i, sym, side, fwd, at, arm='gbm', fz=None, adv=30.0, rr=3.0…`
- L38 `rule(**kw)`
- L46 `outs_for(legs, move=100.0, exit_at=None)` — Исход у всех ног одинаковый — тогда разница между книгами принадлежит ПРАВИЛУ, а не исходам.
- L55 `test_width_is_per_side()`
- L69 `test_one_position_per_name_per_arm()`
- L79 `test_order_decides_who_gets_the_slot()`
- L99 `test_agreement_is_read_from_the_sheet()`
- L112 `test_sizing_changes_weight_not_the_trade()`
- L132 `test_unmeasurable_weight_skips_the_leg()`
- L141 `test_gates_are_the_books_gates()`
- L160 `test_daily_net_is_weighted()`
- L178 `main()`

## research/factory/test_ceiling.py · 1789 строк

Проверки потолка заявки.

- L32 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `_PYC = tempfile.mkdtemp(prefix='pyc-suite-')` — Байткод — В СВОЙ каталог, и это не гигиена, а исправление дефекта, стоившего целого захода. Питон считает леж…
- L61 `FAILED = []`
- L62 `H = 3600.0`
- L63 `DAY0 = 20600`
- L66 `check(name, ok, got='')`
- L75 `series(vals, start=DAY0)` — Дневной ряд, каким его кладёт в артефакт `json.dump`: ключ дня строкой. Ряд с числовыми ключами не пересёкся…
- L82 `noise(seed, n=40, scale=30.0)` — Случайное блуждание дневных денег. Зерно закреплено ЧИСЛОМ: нуль, который нельзя повторить, не является прове…
- L89 `daymap(vals, start=DAY0, step=1)` — Дневной ряд ЯВНЫМИ номерами суток: {день: деньги}.
- L103 `artifact_days(pend_daily, pend_trades, live, pend_rule=None, re…` — Артефакт суточного прогона по ЯВНЫМ номерам суток.
- L143 `artifact(pend_daily, pend_trades, live, pend_rule=None, record_…` — Тот же артефакт по СПИСКАМ: сутки подряд от `DAY0`.
- L157 `three_book_pool()` — Пул из ТРЁХ живых книг, где теснейшая связь не первая и не самая длинная.
- L176 `key_sensitive_pool()` — Пул, на котором ЧЕТЫРЕ естественных ключа выбирают РАЗНЫЕ книги.
- L216 `growth_live_pool(seed=531)` — Пул, на котором условие роста `N` ЖИВОЕ, и обе его стороны видны.
- L273 `POOLS = 400`
- L274 `POOL_SEED = 90210`
- L276 `MIN_USABLE = 300` — не является проверяемым (урок R3)
- L277 `MIN_WITNESSES = 10`
- L290 `JUDGE_RESOLUTION = 0.0001` — Разрешение, на котором потолок ВООБЩЕ различает книги: в `links` связь кладётся округлённой (`round(r, 4)`),…
- L291 `MIN_TOP_GAP = 5 * JUDGE_RESOLUTION`
- L294 `random_pool(rnd, span=60)` — Случайный пул: число книг, длины рядов, знаки связи, сутки.
- L332 `oracle_links(pend, live, min_days=CL.MIN_PAIR_DAYS)` — Правило потолка, записанное здесь СВОЕЙ строкой.
- L361 `ALT_KEYS = (('r·days**0.25', lambda lk: lk['r'] * …` — Названные переписи ключа — только ради ЧИСЛА чувствительности: сверка с оракулом ловит и те, которых в списке…
- L370 `flip(run)` — Знак ВСЕХ дневных денег наоборот — и заявки, и живых книг.
- L375 `_scale(run, k)`
- L387 `test_profit_never_decides()` — Переворот знака денег не меняет вердикта НИ В ОДНОЙ ветке.
- L438 `test_calibration_finds_a_planted_link_and_is_silent_on_noise()` — Подсаженную связь потолок обязан найти, на шуме — промолчать.
- L463 `test_the_pool_measure_is_not_reimplemented()` — Связь и эффективное `N` считает `ledger`, а не вторая копия.
- L510 `test_the_whole_pool_is_read_and_the_closest_link_decides()` — Теснейшая связь выбирается ПО ВЕЛИЧИНЕ, и читается весь пул.
- L543 `test_the_closest_link_is_chosen_by_the_signed_correlation_itsel…` — Теснейшая — по ЗНАКОВОЙ связи: не по модулю и не со взвешиванием.
- L610 `test_the_key_is_fixed_by_an_oracle_on_random_pools()` — Ключ закреплён СВОЙСТВОМ, а не перечнем подделок.
- L735 `test_the_pair_numbers_belong_to_the_closest_book()` — `N` пары и общие сутки описывают ТУ ЖЕ книгу, что названа теснейшей.
- L782 `test_the_pools_effective_n_must_grow()` — Заявка, от которой эффективное `N` пула не растёт, закрывается.
- L834 `test_the_key_error_is_not_rescued_by_the_growth_condition()` — Ошибку ключа второе условие НЕ ловит — и это показано там, где второе условие ЖИВОЕ.
- L901 `test_the_growth_condition_is_not_rendered_on_a_degenerate_pool()` — На пустом и единичном пуле `N_eff` вырожден — и это СЛОВАМИ.
- L944 `test_pending_days_are_counted_not_zeroed()` — «Суток со сделками у заявки» — посчитанное число, а не ноль.
- L976 `test_the_fixture_is_possible_for_a_live_writer()` — Инвариант живого писателя: суток в ряду не больше, чем сделок.
- L1003 `test_the_denominator_is_the_record_not_the_books()` — Знаменатель измеримости — ДЛИНА ЗАПИСИ, а не активность книг.
- L1036 `test_an_old_artifact_has_no_denominator_and_waits()` — Длины записи в артефакте нет — кандидат ЖДЁТ.
- L1058 `test_the_measurability_threshold_cannot_be_softened()` — Порог измеримости закреплён ЗНАЧЕНИЕМ, а не комментарием.
- L1080 `test_a_mirror_book_is_not_closed()` — Связь ЗНАКОВАЯ: зеркало потолком не закрывается.
- L1103 `test_day_keys_are_numbers_not_text()` — День — номер суток, и читатель обязан вернуть ему тип.
- L1118 `test_thin_book_is_closed_by_the_rate()` — Книга, дающая единицы сделок, мертва по построению.
- L1136 `test_shape_must_be_measurable_at_all()` — Залп в редкие сутки — по ФОРМЕ неизмерим, сколько бы сделок ни был.
- L1185 `test_required_trades_grow_with_the_record()` — Требуется СКОРОСТЬ, а не абсолютное число: порог, стоящий литералом, означал бы разное на записи в неделю и в…
- L1200 `test_empty_is_undetermined_and_never_pass()` — Посчитать нечем — кандидат ЖДЁТ, а не проходит по умолчанию.
- L1219 `test_zero_trades_everywhere_is_a_broken_replay()` — Ноль сделок У ВСЕХ книг — сломанный реплей, а не мёртвая заявка.
- L1238 `test_unmeasured_link_is_a_dash_not_a_zero()` — Связь, которой нет, — прочерк. Ноль читался бы как «измерено и книги независимы», то есть как разрешение объя…
- L1257 `test_no_live_books_is_a_pass_with_a_dash()` — Пустой пул: повторять нечего, связь — прочерк, но не отказ.
- L1268 `test_the_phrase_is_derived_from_the_numbers()` — Вердиктовая фраза собирается из посчитанных величин.
- L1298 `test_the_report_prints_the_threshold_that_decided()` — Отчёт печатает то число, которым решено, а не константу модуля.
- L1323 `test_journal_records_changes_not_the_schedule()` — Строка на КАЖДЫЙ вызов сделала бы журнал записью расписания.
- L1353 `test_main_writes_both_forms_and_publishes()`
- L1385 `test_missing_run_is_a_named_refusal_not_zeros()`
- L1407 `write_sheets(path, hours=24, syms=8)` — Лист сечения, где ПОЛ ВХОДА действительно связывает: два имени крупных, шесть мелких. На листе, где все прогн…
- L1427 `write_span_sheets(path, days=3, hours=3, syms=6)` — Листы на несколько СУТОК, где гейт пропускает только последние.
- L1450 `test_the_record_window_is_measured_before_the_gates()` — Длину записи кладёт прогон, и меряет её ДО гейтов кандидата.
- L1504 `test_pending_is_replayed_but_not_declared()` — Заявка прогоняется теми же ногами — и объявлением не становится.
- L1580 `test_declared_proposal_is_not_pending_anymore()` — Заявка, уже стоящая в реестре, потолком не судится: испытание потрачено, и судить её поздно.
- L1611 `_child(tmp, code)` — Прогон в ЧИСТОМ питоне из каталога `tmp`; вывод строкой.
- L1628 `_poison(tmp, name='victim')` — Собрать кеш, который питон СЧИТАЕТ свежим, а код в нём другой.
- L1665 `test_stale_bytecode_shadow_is_found_and_named()` — Кеш, заслоняющий исходник, обязан быть найден и НАЗВАН.
- L1719 `test_the_tree_under_test_is_not_shadowed_by_stale_bytecode()` — Дерево, в котором лежит проверяемый код, обязано быть чистым.
- L1742 `main()`

## research/factory/test_factory.py · 3187 строк

Проверки реестра и пространства фабрики.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `FAILED = []`
- L30 `check(name, ok, got='')`
- L39 `AXES_SNAPSHOT = (('target', ('fwd_4h', 'fwd_24h')), ('r…` — Снимок пространства на день объявления. Числа ЛИТЕРАЛАМИ: формула от самих осей была бы тавтологией и не заме…
- L52 `test_space_is_declared_and_frozen()`
- L64 `test_validate_bites_on_both_sides()`
- L78 `test_draw_is_reproducible_and_random()`
- L94 `test_unavailable_is_named_by_number()`
- L115 `test_describe_names_every_axis()`
- L125 `test_ledger_is_a_journal_not_a_table()`
- L157 `test_broken_line_is_counted_not_swallowed()`
- L169 `test_effective_n_is_measured()`
- L183 `test_agents_registry_is_one_source_and_complete()` — Реестр автономной системы: один источник и полон на двух языках.
- L248 `test_run_log_counts_every_wake_up()` — Журнал прогонов: тишина запрещена, сухой прогон не работа.
- L284 `test_running_now_is_a_separate_question()` — «Работает сейчас» и «последний прогон» — разные вопросы.
- L348 `test_brief_contract_is_mechanical()` — Контракт брифа проверяет машина, и проверяет ровно проверяемое.
- L404 `test_scout_brings_mechanisms_not_verdicts()` — Разведка проверяется по форме, и повтор ловит МАШИНА.
- L535 `test_proposal_must_be_checkable_not_persuasive()` — Заявка на испытание проверяется машиной по форме, не по красоте.
- L640 `test_scout_is_not_rejected_by_its_own_ideas()` — Живой отказ 2026-09-02: разведчик отвергнут собственным меню.
- L701 `test_scout_backlog_survives_the_next_menu()` — Запрет на повтор без текста идеи есть потеря идеи.
- L766 `test_owner_ask_is_measured_not_assumed()` — Просьба к владельцу: записана один раз, состояние — проверкой.
- L836 `test_mechanic_waits_in_a_queue_not_in_a_file()` — Механика переживает следующий прогон предлагающего.
- L904 `test_the_conveyor_records_asks_and_the_mechanic()` — Дорога: контракт роли САМ ставит механику и записывает просьбы.
- L989 `test_circle_calls_the_builder_only_with_a_task()` — Круг зовёт строителя ТОЛЬКО когда задание есть.
- L1075 `test_contract_check_gets_the_start_moment()` — Дорога до правила: момент начала прогона обязан ДОЙТИ до проверки.
- L1147 `test_closed_by_ceiling_is_not_proposed_again()` — Закрытое дешёвым расчётом не возвращается на следующий круг.
- L1233 `test_rights_reach_the_model_whole()` — Право с пробелом внутри доезжает до модели ЦЕЛИКОМ.
- L1293 `test_prompt_actually_reaches_the_model()` — Промпт обязан ДОЙТИ до модели, а не потеряться в аргументах.
- L1357 `test_the_control_machine_is_not_fooled_by_stale_bytecode()` — Машина контролей обязана исполнять ТОТ код, который написала.
- L1400 `test_build_contract_makes_the_controls_bite()` — Главное в постройке — не «тесты зелёные», а кусаются ли контроли.
- L1489 `test_adversary_must_show_what_it_tried()` — «Не смог сломать» обязано отличаться от «не пробовал».
- L1541 `test_a_broken_character_does_not_swallow_the_journal_row()` — Порченый знак в пояснении НЕ теряет строку журнала.
- L1570 `test_fallback_happens_on_a_limit_or_an_unknown_model()` — Откат на запасную модель — по двум причинам, ровно раз, и в журнал.
- L1717 `test_a_hanging_role_is_killed_by_the_clock_and_named()` — Повисшая роль убивается по времени, и это НАЗЫВАЕТСЯ словом.
- L1785 `test_a_usage_limit_is_a_wait_and_the_role_resumes_itself()` — Лимит аккаунта — ОЖИДАНИЕ: бюджета не тратит, снимется — сам.
- L1857 `test_the_contract_judges_the_run_not_the_live_artifacts()` — Проверка контракта смотрит В КАТАЛОГ ПРОГОНА, а не в боевой.
- L1923 `test_the_mechanic_builds_in_a_directory_the_machine_named()` — Каталог механики назначает МАШИНА, и приёмка знает про него.
- L2042 `test_the_judge_does_not_write_the_journals()` — Проверку зовёт и судимая роль — писать обязан только судья.
- L2117 `test_the_proposer_says_where_the_idea_came_from()` — Заявка называет ПРОИСХОЖДЕНИЕ, и «сам придумал» подтверждается.
- L2191 `test_the_brief_carries_the_open_corners()` — Бриф обязан нести раздел открытых углов — сырьё для своих заявок.
- L2210 `test_limit_reset_time_is_read_not_guessed()` — Момент снятия берётся из ответа, а выдумка называется запасом.
- L2262 `test_cycle_advances_one_step_and_obeys_the_safeties()` — Суточный круг: один шаг за вызов, и три предохранителя держат.
- L2446 `test_mech_step_leaves_its_end_line()` — У механического шага есть писатель КОНЦА, и круг им пользуется.
- L2565 `test_runner_leaves_a_line_on_every_refusal()` — Запускалка: отказ называется и всё равно оставляет строку.
- L2642 `test_candidate_diagnostic_counts_trades_not_journal_lines()` — Диагностика кандидатов считает СДЕЛКИ ядром, а не строки.
- L2716 `test_overfilled_book_record_is_retired_not_kept()` — Запись сверх объявленной ширины отставляется, а не остаётся.
- L2789 `main()`
- L2859 `test_control_share_is_of_the_pool_not_the_batch()`
- L2874 `test_control_share_converges()` — Доля контроля обязана сходиться к четверти, а не совпадать с ней в каждой партии: при пуле из двух четверть р…
- L2889 `test_batch_respects_the_owners_limits()`
- L2905 `NOW_S = 20698 * P.DAY` — Фикстура правила вылета обязана выглядеть как ЖИВОЙ артефакт: ключ дневного ряда — номер суток (`candidate.da…
- L2906 `D0 = P.day_no(NOW_S)`
- L2909 `test_window_is_calendar_not_last_entries()`
- L2918 `test_the_window_speaks_day_numbers_not_seconds()` — Единица ключа дневного ряда — НОМЕР СУТОК, и это было дефектом.
- L2951 `test_retire_rule_follows_the_owner_by_sum()`
- L2970 `test_shape_is_the_owners_main_criterion()` — Вылет судит ФОРМУ, а не только сумму (решение владельца 2026-09-02).
- L3030 `test_young_candidate_is_not_judged()`
- L3038 `test_silence_frees_the_slot()`
- L3045 `test_dropped_book_dir_is_found_and_the_archive_is_not()` — Каталог книги вне состава обязан быть НАЗВАН, архив — нет.
- L3079 `test_sweep_judges_control_by_the_same_rule()`
- L3102 `test_stability_asks_how_not_how_much()` — Устойчивость: сколько хороших дней съедает один плохой.

## research/factory/test_run_day.py · 426 строк

Сквозной прогон фабрики на синтетике.

- L20 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `FAILED = []`
- L28 `H = 3600.0`
- L31 `check(name, ok, got='')`
- L38 `sheet_row(sym, fwd, fz)`
- L46 `write_sheets(path, hours=6, syms=8)`
- L61 `fake_bars(t0)` — Бары, на которых исход существует у любой геометрии.
- L77 `setup(tmp)`
- L98 `test_end_to_end()`
- L154 `test_null_keeps_the_book_and_shuffles_the_future()` — Нуль обязан менять ИСХОДЫ, а не состав книги.
- L179 `test_only_needed_legs_are_priced()` — Бары читаются только за ногами, которые кто-то возьмёт.
- L197 `test_zero_outcomes_is_a_failure_not_a_quiet_day()` — Ноль исходов при непустых ногах — поломка чтения баров.
- L222 `test_candidate_trades_reach_the_artifact()` — У кандидата в артефакте есть не только сумма, но и СДЕЛКИ.
- L279 `test_declaration_passes_only_the_ceiling_gate()` — Объявляется ТОЛЬКО то, что потолок пропустил, и только сегодня.
- L408 `main()`

## research/l1_cascades/test_probe.py · 136 строк

Тесты отбора событий. Покрывают дефект, найденный на широком универсуме.

- L20 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L25 `FAILED = []`
- L26 `STEP = PR.STEP_MIN * 60`
- L29 `check(name, cond, detail='')`
- L37 `grid(n, start=1700000000)`
- L41 `test_at_time_exact()`
- L50 `test_at_time_gap()` — Дыра: точки есть, но не те. Обязан вернуть −1, а не соседа.
- L60 `test_at_time_tolerance()`
- L70 `test_scan_ignores_gap()` — Обвал «через дыру» событием не является.
- L85 `test_scan_finds_real_event()` — Настоящий каскад внутри сплошного куска обязан находиться.
- L105 `test_forward_across_gap_dropped()` — Форвард, попадающий в дыру, не берётся ближайшим соседом.
- L119 `main()`

## research/l2_data/test_l2.py · 255 строк

Тесты сбора L2. Покрываются места, где ошибка уже случалась в проекте.

- L26 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `RESEARCH = os.path.dirname(HERE)`
- L37 `FAILED = []`
- L40 `check(name, cond, detail='')`
- L48 `zipped(header, rows)`
- L56 `HEAD_A = ['create_time', 'symbol', 'sum_open_int…`
- L60 `ROW_A = ['2025-03-10 00:05:00', 'BTCUSDT', '698…`
- L65 `ORDER_B = [0, 2, 7, 3, 1, 4, 5, 6]` — Тот же день теми же числами, но колонки переставлены: если разбор идёт по номеру, значения разъедутся молча.
- L66 `HEAD_B = [HEAD_A[i] for i in ORDER_B]`
- L67 `ROW_B = [ROW_A[i] for i in ORDER_B]`
- L70 `test_columns_by_name()`
- L81 `test_missing_column_raises()`
- L91 `test_utc_regardless_of_local_zone()` — Метка обязана дать одно и то же время в любом часовом поясе.
- L111 `test_bad_rows_skipped_not_fatal()`
- L117 `test_days_of_intervals()`
- L141 `test_is_done_checks_window()` — Готовность — это «собрано за нужное окно», а не «файл есть».
- L193 `test_url_and_days()`
- L202 `test_retention_ladder()` — Глубину истории нащупывают, а не обходят.
- L234 `main()`

## research/l3_events/test_l3.py · 237 строк

Тесты L3. Закрывают места, где ошибка была бы невидимой в результате.

- L13 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L18 `FAILED = []`
- L19 `W = E.steps(E.WINDOW_MIN)`
- L22 `check(name, cond, detail='')`
- L30 `flat(n, v=100.0)`
- L34 `test_detect_basic()`
- L45 `test_detect_direction()` — Рост цены событием не является: конструкция — лонг после падения.
- L55 `test_detect_needs_oi_drop()`
- L65 `test_detect_gap_is_nan()` — Дыра в ряде интереса не порождает события — она NaN на сетке.
- L76 `test_detect_mask()`
- L87 `test_dedup()` — Серия соседних баров одного обвала — одно событие.
- L103 `test_forward()`
- L114 `test_episodes()`
- L130 `test_by_episode()`
- L138 `test_ban_matrix_matches_direct_fill()` — Разностный массив обязан дать в точности то же, что прямая запись.
- L173 `test_cross_section_excludes_neighbours()` — Каскадящие соседи не должны попадать в собственный фон.
- L189 `test_null_shift()`
- L198 `test_null_matched_hour()`
- L212 `main()`

## research/m1_features/test_features.py · 280 строк

Тесты M1. Главный — на заглядывание в будущее, и он один на ВСЕ признаки.

- L22 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `FAILED = []`
- L31 `check(name, cond, detail='')`
- L39 `synth(S=24, D=140, gap=None)` — Синтетический рынок: общая волна + свой шум, положительные цены.
- L57 `pack(data)`
- L62 `mutate_after(data, t0)` — Переписать всё ПОСЛЕ дня t0 другим случайным рынком.
- L72 `test_no_lookahead_any_feature()`
- L91 `test_forward_is_strictly_forward()`
- L109 `test_missing_day_is_gap_not_zero()`
- L125 `test_net_path_needs_enough_days()`
- L135 `test_wave_excludes_self_and_beta_sane()`
- L154 `test_funding_day_aggregation()`
- L166 `test_age_is_linear_in_time()`
- L176 `test_oi_respects_publication_lag()`
- L190 `test_ret_norm_scales_by_sqrt_horizon()`
- L203 `test_end_to_end_tiny_store()` — Крохотное хранилище -> дневная сводка тем же SQL, что и прогон.
- L256 `main()`

## research/m2_walkforward/test_m2.py · 389 строк

Тесты M2. Главных два, и оба про то, чего в результате не видно: модель не смеет видеть будущее (walk-forward…

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L22 `FAILED = []`
- L26 `check(name, cond, detail='')`
- L36 `test_gbm_learns_signal()`
- L50 `test_gbm_on_noise_is_flat()`
- L61 `test_gbm_nan_is_information()`
- L76 `test_gbm_deterministic()`
- L87 `test_gbm_quantile_holds_declared_share()`
- L113 `test_gbm_squared_loss_bit_for_bit()`
- L129 `test_gbm_quantile_monotone_in_tau()`
- L140 `test_gbm_contrib_identity()`
- L164 `test_gbm_old_trees_still_predict()`
- L186 `test_binning_edges_from_training_only()`
- L197 `test_rankdata_ties()`
- L203 `test_spearman_known()`
- L212 `test_seeds_pinned_by_number()`
- L219 `test_shuffle_within_sections()`
- L233 `test_shuffle_global()`
- L246 `_tiny_market(n_days=120, n_assets=30, seed=11)`
- L256 `class _Lin` — Крохотная детерминированная «модель» для тестов каркаса — среднее целей обучения плюс признак. Ровно то, что…
  - L261 `_Lin.__init__(self, shift)`
  - L264 `_Lin.predict(self, x)`
- L268 `_lin_fit(xt, yt, fit_idx)`
- L272 `test_walkforward_future_cannot_touch_past()`
- L306 `test_training_excludes_unfinished_forwards()`
- L326 `test_fit_schedule()`
- L337 `test_single_arm_walkforward()`
- L351 `test_nonoverlap()`
- L356 `main()`

## research/mech_994fc54f/test_bid_survives.py · 530 строк

Тесты механики 994fc54f — поглощение после падения.

- L31 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L32 `RESEARCH = os.path.dirname(HERE)`
- L46 `FAILED = []`
- L49 `check(name, cond, detail='')`
- L57 `tape(rows)` — `(время, цена, объём, сторона)` массивами, как их даёт запись.
- L68 `test_entry_never_earlier_than_the_label()` — Вход не раньше, чем метка становится известна.
- L84 `test_label_does_not_look_beyond_T()` — Поток ПОСЛЕ окна метку не решает.
- L94 `test_future_beyond_the_window_does_not_move_the_mark()` — Переписали будущее за окном — метка, поток и снятие не дрогнули.
- L113 `test_shown_queue_decides_the_label()` — Знаменатель поглощения — ПОКАЗАННЫЙ размер уровня.
- L129 `test_flow_agrees_with_the_fill_model()` — Диагностика и метка считают одно и то же.
- L153 `test_pulled_level_is_told_apart()` — Уровень, ушедший без единого принта, считается отдельно.
- L164 `_matrix(nrows, own_ret, bg_ret, n=400)` — Матрица «символы × секунды»: строка 0 своя, остальные фон.
- L175 `test_thin_background_is_not_measured()` — Фон тоньше пола — не ноль, а отсутствие измерения.
- L185 `_rows(vals, labels, t0=1700000000.0, gap=1.0, day='2026-08-10')`
- L191 `test_group_counts_episodes_not_events()` — Шесть событий одной минуты — одно наблюдение, а не шесть.
- L203 `test_ceiling_is_the_best_subset()` — Верхняя граница — лучшее подмножество при идеальном знании.
- L215 `_two_days(n=15)` — Сутки с одной меткой и сутки с другой. Значения различаются.
- L229 `test_null_permutes_inside_the_day()` — Перестановка идёт ВНУТРИ суток, а не по всей выборке.
- L247 `test_null_is_reproducible()` — Зерно — число: нуль, который нельзя повторить, не проверяем.
- L256 `test_calibration_pair()` — Подсаженный разрез мера обязана найти, на шуме — промолчать.
- L291 `_book_rows(n, t=1700000000.0, own=0.01, same_name=False)`
- L296 `test_slots_are_respected()` — Мест шесть, и седьмой сигнал в книгу не входит.
- L305 `test_one_position_per_name()` — Одна позиция на имя: три сигнала по одной монете — одна нога.
- L313 `test_form_uses_the_project_measure()` — Форма считается ОБЩЕЙ мерой проекта, а не своей.
- L323 `test_trade_day_share_is_measurability()`
- L333 `test_absent_value_is_a_dash_not_zero()` — Величины, которой нет, — прочерк. Ноль означает «измерено».
- L339 `_art(ceil, surv=None, eat=None, n95=None)`
- L350 `test_reading_is_derived_from_the_number()` — Вердиктовая фраза выводится из числа, а не стоит рядом с ним.
- L361 `test_killers_are_named_by_number()`
- L373 `J_EV = 3600`
- L374 `STEP = 5`
- L375 `SPAN = 7800`
- L376 `NSYM = 55`
- L379 `build_day(root, with_event=True)` — Сутки записи: два события с разным ответом книги и ровный фон.
- L411 `run_main(with_event=True)`
- L434 `test_end_to_end_splits_the_two_subsets()`
- L455 `test_end_to_end_refuses_when_there_are_no_events()` — Ноль наблюдений при непустом входе — отказ, а не пустой отчёт.
- L494 `main()`

## research/mech_fcbd3542/test_halves.py · 721 строк

Проверки механики `fcbd3542`: метка tick/σ и замер по половинам.

- L20 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L21 `RESEARCH = os.path.dirname(HERE)`
- L32 `same(a, b)` — Равны как числа, считая nan равным nan.
- L46 `test_window_ends_at_month_start_and_never_looks_into_it()`
- L58 `test_future_rewrite_does_not_move_the_label()` — Заглядывание: переписать месяц события — метка не шелохнётся.
- L89 `test_frozen_row_gives_a_gap_not_infinity()` — Замороженный ряд A2: σ = 0 — пропуск, а не бесконечный tick/σ.
- L100 `test_price_scale_comes_from_the_names()`
- L114 `test_short_history_is_a_gap_with_a_named_reason()`
- L124 `test_halves_split_at_median_and_tie_goes_coarse()`
- L138 `test_turnover_is_recorded_as_median_daily()`
- L149 `_matrix(rows=80, n=4000, seed=3)`
- L158 `test_excess_both_matches_detect_excess_exactly()` — Медианная ветка обязана совпадать с `detect.excess` дословно.
- L184 `test_mean_background_is_a_second_statistic_not_a_copy()`
- L196 `test_measure_halves_matches_run_d1_measure()` — Первые шесть столбцов обязаны совпасть с чужим замером.
- L214 `test_rewriting_the_future_beyond_exit_moves_nothing()` — Заглядывание в замере: за выходом сделки цены не влияют.
- L250 `_labels(syms, thin, month='1970-01', turn=None)`
- L258 `_rec(t, row, exc, own=None)`
- L263 `test_unlabelled_is_a_third_group()`
- L280 `test_half_is_asked_per_month()` — Метка помесячная: имя бывает тонким в июле и крупным в августе.
- L295 `test_episode_stats_says_nothing_instead_of_zero()`
- L305 `test_median_and_mean_are_printed_side_by_side()` — Форма фейда видна только парой: медиана плюс, среднее минус.
- L317 `test_indexing_does_not_change_the_number()` — Ускорение, меняющее числа, есть другая мера.
- L339 `test_null_is_reproducible_by_number_and_centred_on_zero()`
- L358 `test_null_permutes_the_label_not_the_events()` — Подсаженная связь метки с исходом обязана перебивать нуль.
- L380 `test_book_keeps_six_slots_and_one_position_per_name()`
- L396 `test_book_pays_the_round_and_the_hedge_pays_its_own()`
- L408 `test_book_day_is_the_day_of_exit()` — Сделка принадлежит суткам, когда деньги стали известны.
- L421 `test_book_size_is_the_project_name_cap()`
- L432 `test_active_share_and_shape_rule_come_from_the_ceiling()`
- L444 `test_require_events_refuses_instead_of_printing_dashes()`
- L458 `test_calibration_finds_the_planted_rebound_and_is_silent_on_noi…` — Без этой пары сломанная загрузка выглядит как «эффекта нет».
- L469 `test_tick_change_never_invents_a_list()` — Сеть в проверку не входит: обе ветки отказа подставные.
- L505 `_art(best, span=50.0)`
- L561 `_art_full(best, span=50.0)`
- L567 `test_killer_phrases_follow_the_numbers()` — Вердикт по каждому условию выводится из числа, а не рядом с ним.
- L606 `test_tick_change_experiment_is_built_or_absent_not_empty()`
- L625 `test_link_reads_the_daily_series_not_a_summary()` — Связь считается по РЯДУ суток, а не по сводке о нём.
- L657 `test_report_verdict_phrase_follows_the_number()`
- L672 `test_report_span_phrase_follows_the_number()`
- L687 `test_report_says_not_measured_instead_of_zero()`
- L703 `main()`

## research/paper_monthly/test_book.py · 605 строк

Тесты бумажной месячной книги.

- L29 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L30 `RESEARCH = os.path.dirname(HERE)`
- L37 `FAILED = []`
- L38 `HOUR_MS = 3600000`
- L41 `check(name, cond, detail='')`
- L49 `class Fake` — Синтетический источник: ряды 1h с общей волной и возвратом.
  - L57 `Fake.__init__(self, t0_day='2026-04-01', days=200, n=40, rho=0.995, …`
  - L75 `Fake.load(self, con, symbols, t0, t1, step='1h', interval='1m')`
  - L92 `Fake.universe(self)`
  - L96 `Fake.state_at(self, liq, universe, at)`
- L101 `install(fake, monkey=True)` — Подменяет загрузку и ликвидность; возвращает восстановитель.
- L110 `test_decision_ignores_the_future()` — Будущее переписано целиком — решение обязано совпасть до бита.
- L131 `test_signal_identical_with_and_without_future_loaded()` — β и сигнал обязаны СОВПАСТЬ при загруженном будущем и без него.
- L161 `test_changing_the_past_does_change_the_decision()` — Негативный контроль самого теста: правка ПРОШЛОГО обязана решение поменять — иначе проверка выше проходила бы…
- L182 `test_no_bar_on_the_decision_day_is_a_refusal()` — Нет наблюдений в день решения — решения НЕТ.
- L213 `test_book_weights()`
- L234 `test_reversion_is_found_and_random_walk_is_not()` — Калибровка: подсаженный возврат книга находит, на случайном блуждании даёт около ноля. Без этой пары отрицате…
- L266 `test_delisted_leg_is_held_to_the_last_bar()` — Нога, чей ряд оборвался внутри месяца, СЧИТАЕТСЯ и помечается — это исправление robust.py, стоившее зонду 44…
- L310 `test_net_arithmetic_with_funding()` — Нетто = брутто − издержки − funding, числом.
- L340 `test_ahead_flag()`
- L353 `test_structural_delay_is_ahead_and_measured()` — Решение, записанное через сутки, — ВПЕРЁД, и доля форварда названа числом.
- L386 `test_summary_never_mixes_groups()`
- L404 `test_verdict_says_when_there_is_no_track()`
- L424 `test_catchup_is_idempotent()` — Повторный прогон не задваивает журнал и не переписывает его.
- L460 `test_empty_run_explains_itself()` — Пустой прогон обязан назвать причины и край хранилища.
- L490 `test_partial_failure_is_named_too()` — ЧАСТИЧНЫЙ отказ так же неотличим от тишины, как полный.
- L522 `test_archive_journal_moves_and_names_the_reason()` — Отставка журнала: файлы уезжают, причина записана, запись начинается с чистого листа. Строку из append-only ж…
- L549 `test_report_writes_and_marks_backfill()`
- L575 `main()`

## research/probe_agree/test_agree.py · 215 строк

Проверки зонда согласия: флаг из выборов, нуль внутри дня, находит подсаженное и молчит на ровном.

- L9 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L14 `FAILED = []`
- L17 `check(name, cond, note='')`
- L24 `test_flag_from_picks_not_rows()` — Флаг — из выборов ДРУГОЙ руки, даже когда её сделка не дожила до закрытия (схлопнулась, без исхода): фильтр о…
- L47 `test_pick_keys_reads_both_sides(tmp=None)`
- L73 `synth_trades(n_days=40, per_day=20, planted=0.0, seed=9)` — Сделки одной ячейки: половина согласных; `planted` — сдвиг нетто согласных в б.п.
- L91 `test_null_finds_planted_and_stays_silent()`
- L107 `test_null_preserves_day_counts()` — Нуль тасует флаги ВНУТРИ дня: перестановка не смешивает дни — иначе эффект дня (слив) выдал бы себя за эффект…
- L131 `test_report_and_reading()`
- L160 `test_drain_split_boundaries()` — Разрез окна слива: границы ВКЛЮЧИТЕЛЬНО, день — UTC по моменту денег, худшее имя — по сумме $ группы.
- L197 `main()`

## research/probe_agree/test_basket_agree.py · 313 строк

Проверки замера «согласие голов на корзине h24c».

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `FAILED = []`
- L30 `check(name, cond, detail='')`
- L38 `hour_key(ts)`
- L43 `T0 = int(datetime(2026, 8, 5, tzinfo=timezon…`
- L44 `H = 3600`
- L47 `write_fixture(mdir)` — Выборы живого образца: две головы, час с частичным согласием и час, где вторая голова не выбирала вовсе.
- L71 `load_all(mdir)`
- L75 `test_agreed_intersection()`
- L104 `test_null_width_and_determinism()`
- L131 `test_verdict_from_numbers()`
- L144 `synth_mids(syms, n=60)` — Середины дрожат, как живые (урок calm-зонда: ровная фикстура вырождает меры).
- L156 `wide_picks(hours=8, per_hour=6)`
- L169 `test_invest_full()` — Ветвь `full` обязана ОБОБЩАТЬ живой размер, а не заменять его.
- L230 `test_e2e_report()`
- L295 `main()`

## research/probe_agree/test_basket_width.py · 326 строк

Проверки замера «ширина согласной корзины».

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `BB = BW.BB`
- L27 `FAILED = []`
- L30 `check(name, cond, detail='')`
- L38 `T0 = int(datetime(2026, 8, 5, tzinfo=timezon…`
- L39 `H = 3600`
- L40 `SYMS = [f'S{i:02d}USDT' for i in range(10)]`
- L43 `hour_key(ts)`
- L48 `section(shift)` — Сечение часа: прогнозы от −45 до +45 б.п., сдвиг меняет порядок.
- L54 `write_fixture(s8, hours=100, arms=('gbm', 'nn'))` — Живой образец: `preds.jsonl` в каталоге МОДЕЛИ, `picks.jsonl` в каталоге книги; выборы согласованы с сечением…
- L91 `mids_fixture(hours=140)` — Середины дрожат, как живые: ровный ряд вырождает любую меру.
- L102 `test_pick_rule()`
- L144 `test_leg_scales()`
- L156 `test_bridge()`
- L180 `test_e2e_report()`
- L229 `test_bridge_refuses()` — Плохой мост обязан остановить прогон — с настоящим main().
- L261 `test_short_history_refuses()` — Короткая история — диагноз отчётом, а не таблица нулей.
- L293 `test_unclosed_is_mark_not_zero()` — Корзина без единого закрытия — отметка, а не реализованный ноль.
- L310 `main()`

## research/probe_basket/test_basket.py · 313 строк

Проверки реплея корзины: правило «только все разом» закреплено числами, оба порога живые, хвост не выдаётся з…

- L11 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L22 `FAILED = []`
- L23 `H = 3600`
- L24 `T0 = BS.hour_ts('2026-08-20-00')`
- L27 `check(name, cond, note='')`
- L34 `flat_mids(path)` — {sym: {ts: mid}} по заданным траекториям (часовые точки).
- L42 `test_take_closes_all_at_once()` — Цель корзины закрывает ВСЕ ноги одним часом, и реализованное сходится числом: ход минус круг на каждую ногу.
- L66 `test_floor_and_no_individual_exits()` — Предел закрывает всё; нога с чудовищным собственным минусом НЕ закрывается, пока корзина в допуске, — отдельн…
- L89 `test_cash_and_name_caps_count()` — Касса и потолок имени: сверх — размер 0, посчитан числом.
- L120 `test_age_limit_closes_basket()` — Лимит возраста закрывает корзину целиком по отметке; пороги старше возраста — задетая цель называется целью,…
- L147 `test_one_loss_day_blocks_entries()` — После минусового закрытия новые входы того же дня UTC не берутся и считаются числом; следующий день входит.
- L172 `test_unpriced_leg_blocks_decision()` — Нога без единой цены блокирует решение корзины (правило живой книги), и часы блокировки считаются.
- L185 `test_whole_run_writes_report()`
- L294 `main()`

## research/probe_calm_exec/test_probe.py · 374 строк

Тесты зонда пассивного входа в спокойном рынке.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L33 `FAILED = []`
- L36 `check(name, cond, detail='')`
- L44 `grids(n=4000, px=100.0, drift_bp_s=0.0, spread_bp=20.0, bsz=10.…` — Синтетические секундные сетки с известной геометрией.
- L59 `tape(rows)`
- L66 `test_filled_benefit_is_spread_plus_fee_gap()` — Плоская цена, лимитка исполнилась: выгода = спред + 3.5 б.п.
- L83 `test_unfilled_flat_benefit_is_exactly_zero()` — Пустая лента, плоская цена: доисполнение тейкером по той же цене — выгода РОВНО ноль. Ветка доисполнения обяз…
- L98 `test_trend_up_costs_the_unfilled_buy()` — Цена растёт 1 б.п./с, лента пуста: покупка доисполняется через 60 с по выросшему аску — выгода около −60 б.п.
- L110 `test_sell_side_is_symmetric()` — Зеркало: падение 1 б.п./с, продажа лимиткой не исполнилась — та же цена в другую сторону.
- L122 `test_sell_queue_is_the_ask_size()` — Очередь продажи — размер АСКА. Покупающая агрессия сквозь наш аск (очередь 7 + нога) исполняет; возьми код оч…
- L134 `test_missing_eval_point_is_a_skip()` — Дыра записи в точке оценки — пропуск, а не ноль.
- L145 `test_band_edges()`
- L152 `test_ep_median_one_hour_one_vote()` — Час — один голос, и медиана со средним считаются ОБЕ.
- L166 `test_verdict_phrase_follows_the_number()` — Фраза выводится из числа — обе ветки (урок Z2: вердиктовая фраза литералом противоречила собственному числу о…
- L187 `HOUR_DELTAS_BP = [10.0 if h % 6 == 5 else 0.5 if h % 2 =…` — Почасовые дельты цены, б.п.: большинство часов мелкие (спокойная полоса), каждый шестой — крупный (σ невырожд…
- L191 `px_of(day_idx, hour)` — Цена начала часа: кумулятив почасовых дельт.
- L197 `write_day(w, sym, day_t0, day_idx, *, sell_tape, step=10)` — Сутки записи одного имени: снимки раз в `step` секунд, цена константна внутри часа и шагает по HOUR_DELTAS_BP…
- L217 `build_store(root, n_days=2)` — Два имени, `n_days` суток; у S000 лента продаж, у S001 пустая.
- L229 `test_sigma_is_causal_first_days_are_not_measured()` — События появляются только когда σ набрана из ПРОШЛЫХ суток.
- L260 `test_pick_symbols_filters_non_crypto()`
- L273 `run_main(root, out, min_obs=12)`
- L288 `test_empty_run_names_its_reasons()` — Пустой прогон печатает счётчики пропусков В ЛОГ.
- L317 `test_end_to_end()` — Сквозной прогон настоящим main(): плоская цена и продающая лента у S000 — покупка «на лучшей» исполняется и в…
- L348 `main()`

## research/probe_corr/test_corr_probe.py · 225 строк

Проверки зонда корреляции: мера, исключение себя, причинность, сквозная дорога до машины суда с подсаженным н…

- L12 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L17 `FAILED = []`
- L20 `check(name, cond, note='')`
- L27 `synth_returns(n_names=40, n_days=260, seed=11)` — Доходности: имя 0 — клон рынка, имя 1 — независимое, имя 2 — зеркало рынка. Рынок — общий фактор остальных им…
- L41 `test_corr_math_and_self_exclusion()`
- L73 `test_causality_and_min_window()`
- L110 `_daily_dir(root, syms, days, close)` — Дневная сводка на диске — той же формы, что пишет M1.
- L127 `test_judge_road_finds_planted_and_stays_silent()` — Сквозная дорога: файлы → колонка → машина суда.
- L210 `main()`

## research/probe_dow/test_dow.py · 165 строк

Проверки зонда дней недели.

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `FAILED = []`
- L30 `check(name, cond, note='')`
- L37 `test_dow_labels_pinned()` — Метка дня закреплена ЧИСЛОМ по известным датам.
- L44 `_rows(days=700, sat_bump=0.0, seed=3)` — Синтетика: сечение в день, спред — шум, суббота +sat_bump б.п.
- L58 `test_planted_day_is_found_and_noise_is_quiet()` — Калибровочная пара: подсаженная суббота переживает планку, чистый шум — нет.
- L77 `test_null_is_reproducible()` — Зерно числом: два прогона нуля дают ОДНИ числа (урок R3).
- L86 `test_whole_run_writes_report()` — Сквозной прогон на подставных векторах: отчёт, обе ячейки, публикация по флагу. Подставной артефакт выглядит…
- L149 `main()`

## research/probe_drain/test_brake.py · 183 строк

Проверки реплея: хронология тормоза, отсутствие заглядывания у хода.

- L15 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L25 `FAILED = []`
- L28 `check(name, cond, note='')`
- L35 `_t(h, pnl, dh=4, sym='AAAUSDT', side='long', book='h4', arm='gb…`
- L43 `test_brake_chronology()` — Тормоз видит только деньги, известные ДО входа, и только от принятых сделок.
- L78 `test_runup_uses_closed_hour()` — Ход берётся с последнего ЗАКРЫТОГО часа перед входом.
- L94 `test_runup_table_counts()`
- L124 `test_whole_run_writes_report()`
- L169 `main()`

## research/probe_drain/test_drain.py · 173 строк

Проверки разбора слива: каждая дорога исполняется, не только формулы.

- L15 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `FAILED = []`
- L27 `check(name, cond, note='')`
- L34 `test_window_bounds_are_inclusive()` — Границы окна включительны с обеих сторон.
- L53 `test_slice_stats_pins_numbers()` — Срез считает стороны, причины и концентрацию числом.
- L81 `_fixture(root)` — Книга с прибыльной базой и убыточным окном — как живая.
- L118 `test_whole_run_writes_report()`
- L158 `main()`

## research/probe_extreme/test_probe.py · 224 строк

Проверки зонда крайности: мера, а не намерение.

- L13 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L17 `FAIL = []`
- L20 `check(name, ok, note='')`
- L27 `T0 = 1786000000`
- L30 `class Bars` — Подставные бары: цена идёт за прогнозом ТОЛЬКО в час зашкала.
  - L39 `Bars.__init__(self, drift_bp)`
  - L42 `Bars.bars(self, sym, t0, t1)`
- L56 `synth_sheets(path, hours=30, syms=12)` — Журнал листов: у каждой монеты свой обычный прогноз, у двух — зашкал в части часов.
- L83 `drift_for(hours=30)` — Дрейф ровно в часы зашкала той же схемы, что synth_sheets.
- L89 `run_synth()`
- L97 `main()`

## research/probe_fshift/test_fshift.py · 574 строк

Проверки механики «смена интервала начисления funding».

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L25 `H = SH.MS_H`
- L26 `T0 = 1700000000000 // H * H`
- L29 `eq(a, b, tol=1e-09, what='')`
- L35 `test_side_sign_by_number()` — Знак закреплён ЧИСЛОМ, а не словом.
- L50 `test_funding_and_excess_signs()` — Начисления и превышение — числами, обе стороны.
- L63 `series_8h_then_1h(n_long=40, n_short=12, rate=-0.01)` — 8 часов, затем переход на 1 час. Метка события — первый час.
- L70 `test_shift_events_finds_shortening()`
- L81 `test_no_lookahead_in_events()` — Переписать будущее — прошлое не должно шелохнуться.
- L117 `test_lookahead_probe_bites()` — Негативный контроль самой проверки: она обязана кусаться.
- L146 `test_min_before_steps()` — Режим, оценённый по паре шагов, режимом не является.
- L155 `test_only_first_short_accrual_is_event()` — Событие — ПЕРВОЕ начисление по короткому интервалу.
- L176 `test_ratio_ignores_jitter()` — Дрожание метки на минуты сменой интервала не является.
- L183 `test_reverse_and_holding()`
- L201 `test_dedup_by_name()`
- L208 `test_rate_extremity()`
- L220 `test_active_share_arithmetic()`
- L229 `test_active_share_empty_is_none()`
- L237 `test_needed_minutes_never_before_anchor()` — Окно допуска смотрит только ВПЕРЁД от якоря.
- L250 `test_fill_book_takes_first_price()` — У якоря побеждает ПЕРВАЯ доступная цена окна допуска.
- L265 `test_fill_book_is_order_independent()` — Порядок, в котором хранилище вернуло строки, чисел не меняет.
- L279 `make_book(n=120, ret=None, seed=7)` — Сечение из `n` имён на трёх якорях: метка, метка+1, выход.
- L293 `test_cross_mean_needs_min_cross()`
- L300 `test_cross_mean_excludes_banned()`
- L310 `test_decile_peers_same_sign()`
- L324 `synth_case(plant, n=120, seed=11, rate=-0.01)` — Сечение с подсаженным ходом у имени события (или без него).
- L350 `test_calibration_finds_planted_move()` — Подсаженное событие обязано находиться.
- L368 `test_calibration_silent_on_random_walk()` — На случайном блуждании превышение обязано быть около нуля.
- L380 `test_funding_excludes_entry_accrual()` — Начисление в момент метки — не наше, и это закреплено ЧИСЛОМ.
- L395 `test_peer_funding_is_measured_from_peer_series()` — Начисления соседа считаются по ЕГО ряду и тем же окном.
- L415 `test_anchors_pre_window_mirrors_holding()` — Окно ДО метки — зеркало удержания, и оно строго перед меткой.
- L425 `test_pre_window_is_measured()` — Четвёртое условие смерти обязано опираться на посчитанное число.
- L438 `test_measure_reports_missing_price_as_gap()` — Цены нет — величины нет; ноль тут читался бы как «не двигалась».
- L451 `DENS = {'share': 0.9}`
- L452 `GOOD = {'n': 100, 'mean': 80.0, 'med': 60.0}`
- L453 `C2 = {'n': 100, 'mean': 10.0, 'med': 8.0}`
- L454 `NUL = {'n': 100, 'mean': 0.2, 'med': 0.1}`
- L455 `PRE = {'n': 100, 'mean': 3.0, 'med': 2.0}`
- L456 `BIG = 100`
- L459 `vd(dens=None, ex=None, c2=None, rank=0.8, null=None, pre=None, …`
- L465 `test_verdict_derived_from_numbers()` — Фраза вердикта выводится из числа, а не стоит рядом литералом.
- L491 `test_verdict_threshold_comes_from_factory()` — Порог измеримости формы взят у потолка фабрики, а не назначен.
- L501 `test_verdict_says_not_measured_not_dead()` — «Не измерено» — не то же, что «условие сработало».
- L510 `test_verdict_withholds_on_thin_sample()` — На горстке событий вердикт не выносится вовсе.
- L524 `test_null_is_calibration_not_a_kill()` — Нуль калибрует меру, а не судит механику.
- L536 `test_daily_net_matches_exit_rule_shape()` — Ряд суток отдаётся в той форме, в какой его судит правило вылета.
- L550 `ALL = [v for k, v in sorted(globals().items()…`
- L553 `main()`

## research/probe_liqsplit/test_liqsplit.py · 209 строк

Проверки зонда деления падений по принтам ликвидаций.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L31 `R = LS.R`
- L32 `FAILED = []`
- L35 `check(name, cond, detail='')`
- L43 `snap(sym, t, bid, ask)`
- L50 `liq(sym, t, side='Buy', p=96.0, v=10.0)`
- L54 `scenario()` — Сутки из 60 имён. S000 падает в 3600 с ликвидациями в окне; S001 падает в 7000 — принты только ВНЕ окна (до и…
- L85 `run_scenario()`
- L105 `test_liq_line_reads_milliseconds()`
- L114 `test_split_and_window()`
- L146 `test_dead_day_detection()`
- L169 `test_reading_branches()`
- L192 `main()`

## research/probe_listings/test_probe.py · 414 строк

Тесты зонда первых дней жизни инструмента.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L29 `FAILED = []`
- L32 `check(name, cond, detail='')`
- L40 `iso(day_idx)`
- L45 `synth(n_days=900, n_old=40, n_new=20, drift_bp_day=0.0, list_da…` — Матрица дневных закрытий: зрелые с дня 0, новички листингами в `list_days`, дрейф новичка — первые 30 дней св…
- L84 `counters()`
- L92 `test_planted_drift_is_found()` — Подсаженный дрейф −30 б.п./день найден; нуль около ноля.
- L105 `test_no_drift_is_zero()`
- L114 `test_delay_skips_the_listing_day()` — Цена дня листинга задрана в полтора раза — вход по закрытию следующего дня её не видит, и «распад пампа» не в…
- L125 `test_base_is_mature_and_computed_by_hand()` — База события — среднее зрелых, сверено с ручным счётом числом.
- L143 `test_young_dirty_neighbor_stays_out_of_base()` — Молодой сосед с диким дрейфом НЕ входит в контрольную базу.
- L169 `test_delisted_counts_to_last_bar()` — Делистинг внутри горизонта: считается до последнего бара с пометкой, а не выбрасывается (вырезать его — вырез…
- L184 `test_edge_of_data_is_a_skip()` — Форвард за краем данных — пропуск, а не укороченное окно.
- L195 `test_hole_at_entry_is_a_skip()` — Дыра в день входа — пропуск, а не сдвиг на следующий день.
- L209 `test_thin_base_is_a_skip()`
- L218 `test_event_comes_from_data_not_listed_field()` — Событие A — рождение ряда ПО ДАННЫМ, а не поле `listed`.
- L241 `test_short_history_name_stays_out_of_base()` — Имя с давним `listed`, но коротким РЯДОМ — не зрелое.
- L267 `test_short_history_out_of_base_through_run()` — Тот же зуб, но через ДОРОГУ run(): прямой тест строил ages сам и подделку внутри run не исполнял — контроль н…
- L288 `test_bybit_listing_is_a_separate_event()` — Листинг Bybit у зрелого на Binance имени — событие B, отдельной секцией; свежерождённое имя в B не входит (во…
- L307 `test_cohort_is_one_vote()` — Месяц листинга — один голос: толпа событий одного месяца не переголосует одиночек других.
- L324 `test_funding_newborns()`
- L342 `test_verdict_phrase()`
- L357 `test_report_writes()` — Дорога до показа исполняется: отчёт из настоящего run().
- L385 `main()`

## research/probe_monthly/test_funding_cost.py · 266 строк

Тесты funding-замера месячной книги.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `RESEARCH = os.path.dirname(HERE)`
- L37 `FAILED = []`
- L40 `check(name, cond, detail='')`
- L48 `ms_of(iso)`
- L53 `series(day_from, n_accruals, rate, step_h=8)` — Ряд funding: начисления каждые step_h часов от полуночи.
- L62 `test_sign_by_number()` — Лонг с положительной ставкой ПЛАТИТ, шорт ПОЛУЧАЕТ — числом.
- L77 `test_missing_leg_is_not_zero()` — Нога без ряда — недоучтённый гросс, а не нулевая издержка.
- L87 `test_accrual_count_comes_from_the_series()` — Та же ставка вдвое чаще — вдвое дороже (правило A1: число начислений по ряду, не по объявленному интервалу).
- L99 `test_window_bounds()` — Начисление до окна и ровно на его правой границе не входит.
- L109 `test_crosscheck_bites()`
- L120 `test_verdict_phrase()`
- L139 `write_funding_dir(fdir, names, rate=1e-06, day_from='2024-01-01…`
- L151 `write_universe(path, names)`
- L157 `run_funding_main(out, fdir, upath, vdir)`
- L172 `test_end_to_end()` — Сквозной: артефакт зонда настоящим probe.main, затем funding поверх него; сверка обязана пройти, фраза — след…
- L213 `test_tampered_probe_artifact_stops_the_run()` — Подделанный артефакт зонда останавливает замер: funding, посчитанный другим книгам, недействителен.
- L246 `main()`

## research/probe_monthly/test_probe.py · 315 строк

Тесты зонда месячного горизонта.

- L29 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L30 `RESEARCH = os.path.dirname(HERE)`
- L39 `FAILED = []`
- L42 `check(name, cond, detail='')`
- L50 `synth_vec(n_days=400, n_names=60, mode='revert', seed=7, shuffl…` — Векторы формата R2 на ежедневных датах.
- L83 `test_signal_chain_identity()` — Сигнал k=30 равен минус сумме трёх прошлых кирпичей — числом.
- L97 `test_forward_chain_identity()`
- L110 `test_alignment_is_by_name()` — Перетасовка имён между датами НЕ меняет меру ячейки.
- L133 `test_missing_day_breaks_the_chain()` — Дата вне сетки → None, а не сцепление через дыру (класс L2).
- L142 `test_nan_name_stays_nan()` — NaN в одном кирпиче заражает имя целиком — пропуск, не ноль.
- L153 `test_turnover()`
- L161 `test_calibration_finds_planted_reversion()` — Зонд обязан НАХОДИТЬ месячный возврат, который в данных есть, и не находить его на случайном блуждании; нуль…
- L189 `test_verdict_phrase_follows_numbers()`
- L209 `write_vectors(vec, vdir, interval='1m')`
- L223 `run_main(vdir, out)`
- L237 `test_end_to_end()` — Сквозной прогон настоящим main() на подсаженном возврате.
- L269 `test_empty_run_names_reasons()` — Пустой прогон печатает причины (урок первого смоука calm).
- L292 `main()`

## research/probe_monthly/test_robust.py · 297 строк

Тесты трёх замеров устойчивости месячного зонда.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `RESEARCH = os.path.dirname(HERE)`
- L35 `FAILED = []`
- L38 `check(name, cond, detail='')`
- L46 `counters()`
- L52 `test_newey_west_exact_number()` — Точное значение, посчитанное независимо (ряд 1,2,3,4; лаг 1).
- L65 `test_newey_west_bites_on_autocorrelation()` — На положительно автокоррелированном ряде NW ОБЯЗАН быть меньше наивного; на белом шуме — близок к нему.
- L87 `make_vec(n_days=400, seed=7)`
- L91 `test_chain_alive_tells_delisting_from_hole()` — Три статуса числом: целое, оборванный хвост, дыра в середине.
- L117 `test_missing_first_brick_is_not_alive()`
- L127 `test_alive_arm_keeps_what_base_drops()` — Базовая рука выбрасывает делистнутое имя, живая — держит.
- L166 `test_halves_split_covers_both()`
- L176 `test_overlap_null_calibration()` — Ключевая калибровка: на подсаженном возврате t по NW большой, на перемешанном сигнале — около ноля. Без неё п…
- L198 `test_verdict_phrase_follows_numbers()`
- L233 `run_main(vdir, out)`
- L247 `test_end_to_end()`
- L275 `main()`

## research/probe_regimes/test_probe.py · 137 строк

Проверки зонда режимов: мера, нуль и то, что зонд НЕ выдумывает.

- L19 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L23 `FAIL = []`
- L26 `check(name, ok, extra='')`
- L33 `test_spearman()`
- L48 `test_seed_is_a_number()` — Зерно выводится ЧИСЛОМ: нуль обязан повторяться между процессами.
- L63 `_matrix(n_days, n_names, hetero)` — Синтетика. `hetero` — есть ли зависимость навыка от режима.
- L91 `test_probe_finds_and_does_not_invent()`
- L123 `test_thin_sections_are_skipped()`

## research/probe_setups/test_setups.py · 354 строк

Тесты зонда сетапов. Каждая дорога исполняется, а не подразумевается.

- L17 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L23 `FAILED = []`
- L26 `check(name, cond, extra='')`
- L33 `row(hz, arm, sym, hour, side, net, fam, ts=None)`
- L40 `test_label_is_taken_per_decision()` — Одно решение — один ярлык: большинство копий, ничья по имени.
- L71 `test_excess_is_measured_over_own_cell()` — Семейство большинства в плюсовой книге НЕ получает превышения.
- L90 `test_thin_cell_is_a_gap_not_a_zero()` — Ячейка тоньше порога — пропуск, а не наблюдение с нулём.
- L102 `synth(seed=1, edge_fam='tape', edge=40.0, books=None, hours=140)` — Синтетика: у одного семейства настоящее превышение во всех ячейках.
- L123 `test_finds_a_real_setup_and_rejects_noise()`
- L139 `test_pure_noise_names_nobody()` — На чистом шуме устойчивых сетапов быть не должно ни одного.
- L150 `test_duplicate_null_is_harder_than_incell_null()` — Нуль 2 обязан быть СТРОЖЕ нуля 1 — в этом цена повторов.
- L165 `mkbook(root, name, hz, hours=40, syms=6, sit=False)` — Каталог книги, как его пишет цикл: манифест, выборы, разборы.
- L206 `test_smoke_runs_every_road_to_the_report()` — Сквозной прогон: настоящие каталоги книг → отчёт на диске.
- L251 `test_side_excess_removes_the_direction_confound()` — Семейство из одних лонгов в растущей книге НЕ получает превышения.
- L283 `test_account_check_counts_only_what_the_file_could_know()` — Закрытое ПОСЛЕ записи файла счёта — не расхождение реализаций.
- L331 `TESTS = [test_label_is_taken_per_decision, test…`
- L342 `main()`

## research/probe_spike/test_long_history.py · 201 строк

Проверки прогона на годах: каждая дорога исполняется, не только формула.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `Z1 = os.path.join(os.path.dirname(HERE), 'z1…`
- L20 `Z2 = os.path.join(os.path.dirname(HERE), 'z2…`
- L21 `L3 = os.path.join(os.path.dirname(HERE), 'l3…`
- L32 `SYMS = [f'S{i:02d}USDT' for i in range(12)]`
- L35 `synth_matrix(syms, times, interval='1m', log=None, columns=('op…` — Подставной загрузчик цен: спокойный ряд плюс всплески на 3 %.
- L58 `_setup()`
- L68 `_restore(old)`
- L72 `test_trips_reuse_probe_formula()` — Издержки считает формула ЗОНДА, а не своя арифметика.
- L90 `test_gap_gives_no_event()` — Дыра в сетке не рождает всплеск.
- L109 `test_own_mask_keeps_events_in_their_month()` — Хвост следующего месяца событий не даёт.
- L135 `test_run_writes_report_and_year_profile()` — Сквозной прогон: отчёт, профиль по годам, публикация по флагу.
- L185 `main()`

## research/probe_spike/test_spike.py · 359 строк

Проверки зонда всплеска: каждая дорога исполняется на подставном складе.

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L17 `Z2 = os.path.join(os.path.dirname(HERE), 'z2…`
- L28 `DAYS = ['2026-08-18', '2026-08-19', '2026-08-2…`
- L29 `NARROW_DAY = '2026-08-17'`
- L30 `SYMS = [f'S{i:02d}USDT' for i in range(8)]`
- L31 `MINS = 1440`
- L34 `write_store_day(store, day, syms, seed=1, quiet_only=False)` — Сутки склада: спокойный ряд плюс всплески двух родов.
- L78 `_setup(quiet_only=False, narrow_first=False)`
- L103 `_restore(old)`
- L107 `_thin_judge()`
- L113 `_fat_judge(keep)`
- L120 `test_probe_runs_and_separates_quote_from_price()` — Прогон целиком, и котировочные события отделены от подтверждённых.
- L155 `test_quote_only_day_gives_no_confirmed_events()` — Сутки, где всплески идут БЕЗ сделок, подтверждённых не дают.
- L179 `test_round_trip_charges_both_legs_by_half_spread()` — Круг: комиссия ДВУХ ног плюс по половине спреда каждой.
- L209 `test_report_names_hedge_spread()` — Отчёт обязан говорить, что вторую ногу тоже посчитали.
- L233 `test_narrow_early_day_is_not_measured()` — Узкие по составу сутки в замер не входят.
- L257 `test_diag_counts_in_basis_points()` — Таблица цены сделки считает в БАЗИСНЫХ ПУНКТАХ, а не в долях.
- L290 `_median(v)`
- L294 `test_cost_table_agrees_in_sign_with_verdict_table()` — Две таблицы отчёта не вправе противоречить друг другу по знаку.
- L340 `main()`

## research/probe_tailveto/test_tailveto.py · 179 строк

Проверки судьи хвостов.

- L22 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `FAILED = []`
- L30 `check(name, cond, detail='')`
- L38 `synth(n_days=30, per_day=30, planted=False, seed=3)`
- L52 `test_judge_finds_planted_and_stays_silent()`
- L66 `test_day_effect_not_mistaken_for_state()` — В плохие дни и флагов больше, и нетто хуже — но ВНУТРИ дня флаг с исходом не связан. Концентрация выходит выш…
- L85 `test_terciles_and_entry_state()`
- L122 `test_missing_book_unpack()` — Ранний возврат book_rows несёт ТРИ значения, полный — четыре: распаковка по счёту уронила первый живой прогон…
- L133 `test_report_smoke()`
- L161 `main()`

## research/probe_turn/test_turn.py · 264 строк

Тесты зонда перелома.

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L21 `OK = []`
- L24 `check(name, cond, note='')`
- L30 `days_from(vals, start=20000)`
- L34 `test_peak_stats_reads_the_curve()`
- L47 `test_noise_gives_no_turning_point()`
- L57 `test_real_break_is_caught()`
- L71 `test_sync_separates_common_from_independent()`
- L92 `test_sync_survives_a_young_book()` — Одна молодая книга не вправе обнулять меру для всех.
- L128 `test_split_by_peak_reports_both_sides()`
- L159 `test_whole_run_executes_to_report()` — Прогон целиком: книга на диске → артефакт и отчёт.
- L238 `_run_main(s8)`
- L248 `main()`

## research/probe_upcascade/test_up.py · 244 строк

Проверки зонда продолжения сквиза.

- L22 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `E = U.E`
- L28 `L3 = U.L3`
- L30 `FAILED = []`
- L33 `check(name, cond, detail='')`
- L41 `two_sided_series(n=200)` — Ряд с ОБОИМИ событиями: падение на 30-м шаге, рост на 120-м; интерес падает в обоих случаях (каскад — исчезно…
- L53 `test_default_is_down_bit_for_bit()` — Умолчание — прежний L3: находит падение, игнорирует рост, и равно явному direction=-1 поэлементно.
- L66 `test_direction_up_mirrors()`
- L87 `test_reference_formula_random()` — Независимая переформулировка условия на случайных данных: d_px ≥ move при direction=+1, d_oi ≤ −drop, тот же…
- L119 `test_scan_symbols_passes_direction()` — Дорога зонда — L3.scan_symbols(direction=+1), а не прямой вызов detect: зашитый в run.py −1 не поймал бы ни о…
- L155 `synth_measure(direction=+1)` — НАСТОЯЩИЙ L3.measure на синтетике: 30 символов (кросс-секции нужен фон не тоньше min_cross=20 — урок T1), 600…
- L181 `test_rows_and_report()`
- L226 `main()`

## research/r1_factor/test_factor.py · 346 строк

Тесты ядра R1 на известных ответах.

- L23 `H = F.STEP_MS['1h']`
- L26 `grid(n, t0=0)`
- L30 `class PriceGrid`
  - L31 `PriceGrid.test_missing_bar_becomes_nan(self)`
  - L39 `PriceGrid.test_grid_starts_on_step_boundary(self)`
- L44 `class Gaps`
  - L45 `Gaps.test_return_through_gap_is_not_an_observation(self)` — Главный дефект, ради которого сетка регулярная.
  - L59 `Gaps.test_naive_diff_would_have_given_two(self)` — Контроль самого теста: без сетки дефект действительно есть.
- L65 `class LeaveOneOut`
  - L66 `LeaveOneOut.test_own_return_excluded(self)`
  - L74 `LeaveOneOut.test_missing_asset_does_not_shift_others(self)`
  - L81 `LeaveOneOut.test_thin_bar_is_dropped(self)`
  - L87 `LeaveOneOut.test_own_inclusion_inflates_beta(self)` — Смещение, ради которого версия «все, кроме меня» и заведена.
- L103 `class KnownBeta`
  - L104 `KnownBeta.test_recovers_beta_and_r2(self)`
  - L114 `KnownBeta.test_independent_series_gives_zero_r2(self)`
  - L120 `KnownBeta.test_intercept_absorbs_drift(self)` — Снос актива не должен уезжать в наклон.
- L129 `class ScaleOfBeta` — β меряется относительно НАБЛЮДАЕМОЙ волны, а не скрытого фактора.
  - L140 `ScaleOfBeta.setUp(self)`
  - L150 `ScaleOfBeta.test_estimate_equals_truth_divided_by_mean_beta(self)`
  - L156 `ScaleOfBeta.test_mean_beta_is_one_by_construction(self)` — Свободная проверка корректности, годная и на живых данных.
- L167 `class FrozenSeries`
  - L168 `FrozenSeries.test_frozen_asset_yields_no_estimate(self)` — Замороженный ряд A2: цена не меняется, доходность тождественно ноль. Дисперсии нет, оценивать нечего — regres…
  - L176 `FrozenSeries.test_frozen_asset_skipped_by_betas(self)`
- L186 `class Coverage`
  - L187 `Coverage.test_thin_asset_skipped(self)`
- L196 `class Residuals`
  - L197 `Residuals.test_residual_is_orthogonal_to_factor(self)`
  - L209 `Residuals.test_frozen_leg_residual_is_minus_beta_f(self)` — Почему §5.1 спеки 03 называет замороженные ряды угрозой первого порядка: если такой актив всё же дойдёт до ра…
- L227 `class SectorFactor`
  - L228 `SectorFactor.test_small_group_gives_no_factor(self)` — Среднее по трём именам — шум, а не фактор. Вычитание такого «фактора» добавило бы в остаток чужую случайность.
  - L234 `SectorFactor.test_factor_is_group_mean(self)`
  - L239 `SectorFactor.test_loo_excludes_own(self)`
- L245 `class PairwiseCovariance`
  - L246 `PairwiseCovariance.test_matches_plain_covariance_without_gaps(self)`
  - L252 `PairwiseCovariance.test_gaps_do_not_become_zeros(self)` — Заполнить пропуск нулём значит утверждать «доходность была нулевой» — то самое молчание, выданное за данные,…
  - L263 `PairwiseCovariance.test_short_overlap_is_unknown_not_zero_correlation(self)`
- L271 `class Components`
  - L272 `Components.test_first_component_of_common_factor_is_the_factor(self)` — Если весь универсум движется одной волной, первая компонента обязана быть примерно равновзвешенной.
  - L283 `Components.test_sign_is_fixed_so_beta_does_not_flip(self)` — Собственный вектор определён с точностью до знака. Без фиксации первая компонента произвольно меняла бы напра…
- L296 `class WeightedFactor`
  - L297 `WeightedFactor.test_loo_is_exact_subtraction(self)`
  - L306 `WeightedFactor.test_market_weights_reproduce_market_factor(self)` — Рынок — частный случай той же конструкции с весами 1/n.
- L315 `class RegressMulti`
  - L316 `RegressMulti.test_recovers_known_coefficients(self)`
  - L329 `RegressMulti.test_more_factors_explain_more(self)` — Смысл ступеней 2 и 3: больше факторов — меньше дисперсии остаётся в остатке. Это и есть рычаг итерации 1.
  - L340 `RegressMulti.test_degenerate_input_returns_none(self)`

## research/r2_residual/test_residual.py · 354 строк

Тесты ядра R2 на известных ответах.

- L21 `class Accumulate`
  - L22 `Accumulate.test_sums_residual_over_bars(self)`
  - L33 `Accumulate.test_missing_bars_are_skipped_not_zeroed(self)` — Актив, торговавшийся половину окна, не должен получать волну за ту половину, которой не было.
  - L43 `Accumulate.test_asset_with_no_bars_is_nan_not_zero(self)`
- L51 `class Ranks`
  - L52 `Ranks.test_average_rank_for_ties(self)`
  - L59 `Ranks.test_all_ties_give_no_correlation(self)` — Урок A1: связки нельзя засчитывать как согласие.
- L65 `class Spearman`
  - L66 `Spearman.test_perfect_monotone(self)`
  - L72 `Spearman.test_perfect_inverse(self)`
  - L77 `Spearman.test_independent_is_near_zero(self)`
- L84 `class BasketSpread`
  - L85 `BasketSpread.test_picks_extremes_and_signs_correctly(self)`
  - L94 `BasketSpread.test_no_signal_gives_zero_spread_on_average(self)` — Порог задан стандартной ошибкой, а не выбран на глаз.
- L111 `class DetectsRealReversal` — Стенд обязан увидеть возврат, если он в данных есть.
  - L114 `DetectsRealReversal.test_finds_planted_mean_reversion(self)`
  - L127 `DetectsRealReversal.test_finds_nothing_when_nothing_planted(self)` — И, что важнее, НЕ находит, когда возврата нет.
  - L136 `DetectsRealReversal.test_momentum_gives_negative_ic(self)` — Продолжение движения вместо возврата обязано дать минус, а не ноль: знак должен быть содержательным, а не абс…
- L148 `class TStat`
  - L149 `TStat.test_known_value(self)`
  - L155 `TStat.test_scales_with_sample_size(self)`
  - L161 `TStat.test_ignores_missing_sections(self)`
- L168 `class WindowBounds` — Ошибка на один бар здесь невидима — поэтому тест явный.
  - L171 `WindowBounds.setUp(self)`
  - L175 `WindowBounds.test_forward_starts_exactly_at_rebalance(self)` — Бар i_t−1 закончился В МОМЕНТ ребаланса и уже известен.
  - L183 `WindowBounds.test_signal_ends_exactly_at_rebalance(self)`
  - L186 `WindowBounds.test_signal_and_forward_share_no_bar(self)`
  - L189 `WindowBounds.test_lengths(self)`
  - L194 `WindowBounds.test_signal_clipped_by_formation_start(self)`
  - L198 `WindowBounds.test_forward_clipped_by_end_of_series(self)`
- L203 `class DeterministicSeed` — Нулевая модель, которую нельзя повторить, не является проверяемой.
  - L212 `DeterministicSeed.test_known_values(self)`
  - L217 `DeterministicSeed.test_same_input_same_permutation(self)`
  - L222 `DeterministicSeed.test_different_date_different_permutation(self)`
- L228 `class ResidualMatrix`
  - L229 `ResidualMatrix.test_single_factor_matches_old_path(self)` — Многофакторная формула на одном факторе обязана совпасть с одномерной: иначе у остатка две разные формулы.
  - L239 `ResidualMatrix.test_unfitted_asset_has_no_residual(self)`
  - L247 `ResidualMatrix.test_more_factors_remove_more_variance(self)` — Рычаг итерации 1: лучший хедж оставляет меньше дисперсии.
- L260 `class BlendRanks`
  - L261 `BlendRanks.test_equal_signals_give_same_order(self)`
  - L266 `BlendRanks.test_opposite_signals_cancel(self)`
  - L271 `BlendRanks.test_scale_of_inputs_does_not_matter(self)` — Ранги, а не значения: иначе комбинацию определял бы тот сигнал, у кого шире распределение.
  - L281 `BlendRanks.test_asset_with_one_signal_is_dropped(self)`
  - L288 `BlendRanks.test_weight_zero_is_pure_first_signal(self)`
- L294 `class TestPathNorm` — Замер нормировки пути (эквивалент RSI на остатке).
  - L297 `TestPathNorm.test_rsi_identity(self)` — RSI Уайлдера есть в точности 50·(1 + чистое / путь).
  - L311 `TestPathNorm.test_rsi_is_monotone_in_net_over_path(self)` — Сечение ранжируется, поэтому важна только монотонность.
  - L320 `TestPathNorm.test_sharpe_se_depends_on_span_not_frequency(self)` — Стандартная ошибка годового Sharpe равна 1/√(лет истории).
  - L338 `TestPathNorm.test_sharpe_matches_hand_computation(self)`
  - L347 `TestPathNorm.test_short_series_gives_nothing(self)` — Девять периодов — не ряд. Лучше пусто, чем Sharpe из воздуха.

## research/r4_costs/test_costs.py · 324 строк

Тесты ядра R4 на известных ответах.

- L24 `BP = 0.0001` — Базисный пункт равен 0.0001. Тейкер 5.5 б.п. — это 0.00055, а не 0.000055: первая редакция этих тестов ошибла…
- L28 `class Weights`
  - L29 `Weights.test_gross_is_one_and_book_is_neutral(self)`
  - L36 `Weights.test_long_is_top_of_score(self)`
  - L44 `Weights.test_assets_without_forward_get_no_weight(self)`
- L52 `class Turnover`
  - L53 `Turnover.test_unchanged_book_trades_nothing(self)`
  - L59 `Turnover.test_full_replacement_trades_two(self)` — Полная замена книги — оборот 2, а не 1: старое закрывается, новое открывается.
  - L66 `Turnover.test_flip_trades_double(self)` — Имя, перевернувшееся из лонга в шорт, торгуется двойным объёмом — именно поэтому оборот считается по разности…
  - L72 `Turnover.test_persisting_leg_is_free(self)` — Смысл замера: допущение «шестьдесят ног каждый ребаланс» завышало бы издержки тем сильнее, чем длиннее окно с…
- L83 `class Commission`
  - L84 `Commission.test_full_replacement_at_modal_rate(self)` — Полная замена при тейкере 5.5 б.п. стоит 11 б.п. гросса.
  - L92 `Commission.test_per_symbol_rate_is_used(self)` — Разброс ставок вчетверо — средняя по универсуму запрещена.
- L101 `class Funding`
  - L102 `Funding.test_long_pays_short_receives(self)` — Положительная ставка: лонг платит, шорт получает.
  - L108 `Funding.test_book_funding_is_the_differential(self)` — У книги, равной по деньгам, funding есть ДИФФЕРЕНЦИАЛ ног, а не сумма. Знак заранее неизвестен и подлежит зам…
  - L116 `Funding.test_missing_series_is_skipped_not_zeroed(self)`
- L122 `class DelistedRate`
  - L125 `DelistedRate.test_thin_asset_gets_expensive_rate(self)`
  - L134 `DelistedRate.test_uniform_population_gives_670(self)` — При равномерном распределении по квинтилям — 6.70 б.п.
  - L140 `DelistedRate.test_measured_population_gives_676(self)` — Число 6.76 б.п. из раздела 6 спеки — это средневзвешенное по ФАКТИЧЕСКОМУ распределению безставочных активов…
  - L152 `DelistedRate.test_flat_expensive_would_overcharge(self)` — Замер, опровергнувший черновик: плоские 11.0 б.п. завышают издержку почти вдвое против правила.
  - L160 `DelistedRate.test_no_turnover_gets_fallback(self)`
- L166 `class NetSpread`
  - L167 `NetSpread.test_half_factor(self)` — Спред дециля — величина «на ногу», книга держит две ноги.
  - L171 `NetSpread.test_costs_subtract_directly(self)`
  - L174 `NetSpread.test_known_case_end_to_end(self)` — Сквозной пример в числах, которые можно проверить руками.
- L191 `class ParseTime` — Формат метки времени угадывался дважды и дважды неверно.
  - L200 `ParseTime.setUp(self)`
  - L208 `ParseTime.test_iso_with_timezone(self)`
  - L212 `ParseTime.test_milliseconds_as_string(self)`
  - L216 `ParseTime.test_both_forms_agree(self)`
  - L221 `ParseTime.test_unknown_form_raises(self)`
- L226 `class TestFundingSignal` — Рычаг 2 итерации 1, §12.3: funding вторым сигналом.
  - L229 `TestFundingSignal.setUp(self)`
  - L237 `TestFundingSignal.series(self, rates, step_h, end='2024-01-31')` — Ряд начислений, заканчивающийся до `end`, с шагом `step_h` часов.
  - L245 `TestFundingSignal.test_sign_convention(self)` — Высокая ставка обязана давать ОТРИЦАТЕЛЬНУЮ оценку.
  - L258 `TestFundingSignal.test_hourly_costs_more_than_four_hourly_at_equal_rate(self)` — Главное место, где прочитка «за сутки» отличается от «за начисление»: та же ставка при часовых начислениях до…
  - L273 `TestFundingSignal.test_missing_series_is_nan_not_zero(self)` — Ноль означал бы «ставка была нулевой» — наблюдение, которого не было. Тот же класс ошибки, что замороженные р…
  - L282 `TestFundingSignal.test_window_excludes_future_accruals(self)` — Начисления, случившиеся в дату отбора и позже, в оценку не входят: иначе сигнал знал бы будущее.
  - L292 `TestFundingSignal.test_restricted_arm_keeps_signal_and_drops_uncovered(self)` — `resid_r` — тот же остаток на суженном универсуме.
  - L305 `TestFundingSignal.test_blend_moves_ranking_toward_funding(self)` — Комбинация обязана двигать порядок в сторону второго сигнала.
  - L316 `TestFundingSignal.test_exactly_opposite_signals_give_no_portfolio(self)` — Крайний случай, найденный при написании предыдущего теста: если funding ранжирует сечение ровно наоборот, ком…

## research/r5_backtest/test_stats.py · 154 строк

Тесты ядра R5 на известных ответах.

- L22 `class NormPpf`
  - L23 `NormPpf.test_known_quantiles(self)`
  - L29 `NormPpf.test_round_trip(self)`
- L34 `class Sharpe`
  - L35 `Sharpe.test_known_value(self)` — Ряд со средним 0.001 и разбросом 0.01 при 252 периодах в год.
  - L49 `Sharpe.test_constant_series_has_no_sharpe(self)`
- L53 `class ExpectedMaxSharpe`
  - L54 `ExpectedMaxSharpe.test_grows_with_number_of_trials(self)`
  - L61 `ExpectedMaxSharpe.test_scales_with_spread_of_trials(self)`
  - L66 `ExpectedMaxSharpe.test_no_correction_for_single_trial(self)`
- L70 `class CorrectionKillsPureSearch` — Проверка смысла поправки, а не её формулы.
  - L78 `CorrectionKillsPureSearch.test_best_of_pure_noise_does_not_survive(self)`
  - L92 `CorrectionKillsPureSearch.test_real_edge_survives_the_same_correction(self)` — Обратная проверка: поправка не должна убивать всё подряд.
- L106 `class HeavyTails`
  - L107 `HeavyTails.test_dsr_falls_on_fat_tails_when_sharpe_does_not(self)` — Смысл второй версии поправки: у ряда с тяжёлыми хвостами обычный Sharpe этого не показывает, а DSR показывает.
- L123 `class Drawdown`
  - L124 `Drawdown.test_known_case(self)` — +10 %, затем −50 % даёт просадку ровно 50 %.
  - L130 `Drawdown.test_monotone_growth_has_no_drawdown(self)`
  - L134 `Drawdown.test_compounding_not_summing(self)` — Просадка считается сложением, а не суммой: счёт считает так.
- L141 `class Splits`
  - L142 `Splits.test_by_year(self)`
  - L148 `Splits.test_equal_parts_cover_everything(self)`

## research/s10_policy/test_tournament.py · 412 строк

Проверки турнира политик: геометрия, слоты, селектор без заглядывания.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L22 `FAIL = []`
- L25 `check(name, ok, extra='')`
- L32 `bar(t, o, h, l, c)`
- L36 `test_variants()`
- L45 `test_legs()`
- L121 `test_outcome()`
- L152 `_leg(i, sym, at, fwd=30.0, arm='gbm')`
- L161 `_outs(legs, why='цель', move=60.0, hold=3600)`
- L173 `test_slots()`
- L194 `test_cell_drawdown_is_not_the_worst_trade()` — Просадка кривой и худшая сделка — РАЗНЫЕ величины.
- L265 `test_selector()`
- L303 `test_kill_arm()` — Рука kill-10: сливающий вариант снимается немедленно.
- L344 `test_artifacts_survive_fresh_checkout()` — Прогон целиком, в каталог, которого ещё нет, — оба артефакта.
- L378 `test_verdict()`

## research/s10_policy/test_width.py · 265 строк

Тесты профиля по месту в сечении.

- L17 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L25 `FAILED = []`
- L28 `check(name, cond, detail='')`
- L36 `leg(sym, fwd, hour='2026-08-05-10', arm='gbm', at=1.0)` — Нога листа: сторона задаётся знаком прогноза, как у сканера.
- L45 `test_rank_is_within_hour_arm_and_side()` — Место считается внутри часа, руки и СТОРОНЫ.
- L64 `test_short_side_sign()` — У шорта место задаёт МОДУЛЬ прогноза, а не его величина.
- L72 `rows_with(profile)` — Ноги с заданным ожиданием по месту: `profile[место] = нетто`.
- L83 `test_decaying_profile_is_named_decaying()`
- L91 `test_flat_profile_is_named_flat()` — Плоский профиль — довод ПРОТИВ оси, и это надо сказать прямо.
- L100 `test_thin_profile_is_not_judged()` — Мест с наблюдениями мало — судить нечем, а не «профиля нет».
- L108 `test_width_reports_concentration()` — Итог без лучшего имени — обязательная колонка.
- L126 `test_net_matches_the_tournament_formula()` — Нетто считается той же формулой, что `simulate` турнира.
- L146 `test_report_names_the_fence()` — Отчёт обязан назвать потолок на имя.
- L164 `test_bands_show_what_the_added_places_bring()` — Полоса мест считается разностью, а не долей накопленного.
- L182 `test_step_separates_rich_head_from_flat_tail()` — Ступень: верхние места богаты, дальше ноль.
- L199 `test_run_publishes_itself()` — Прогон обязан публиковать отчёт сам.
- L242 `main()`

## research/s11_horizon/test_horizon.py · 192 строк

Тесты зонда горизонта сигнала.

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L23 `OK = []`
- L26 `check(name, cond, note='')`
- L32 `_synth(S=40, H=80, seed=7)`
- L45 `test_default_targets_unchanged()`
- L61 `test_split_boundary_is_m2_rule()`
- L75 `test_gate_pool_rr_ceiling()`
- L86 `test_edge_prefilter_matches_simulate_gate()`
- L111 `test_fit_predict_executes_end_to_end()`
- L138 `test_cell_stats_and_report_execute()`
- L177 `main()`

## research/s1_managed/test_managed.py · 183 строк

Тесты ядра S1. Запуск: python3 -m unittest discover -s research/s1_managed

- L14 `class TestInverseVolWeights`
  - L16 `TestInverseVolWeights.test_gross_is_one_and_legs_equal_in_money(self)`
  - L25 `TestInverseVolWeights.test_volatile_name_gets_smaller_share(self)` — Суть правила 1: актив, который ходит в разы, получает меньшую долю ноги ещё до того, как что-либо произошло.
  - L37 `TestInverseVolWeights.test_floor_binds_when_a_name_is_far_below_the_section(self)` — Тот же расчёт, но одно имя вдесятеро спокойнее сечения: пол обязан связать, и отношение весов выходит мягче г…
  - L46 `TestInverseVolWeights.test_equal_vol_reproduces_equal_weights(self)` — Проверка на вырождение: при одинаковой волатильности правило обязано совпасть с равными весами до последнего…
  - L56 `TestInverseVolWeights.test_frozen_series_is_excluded(self)` — У замороженного ряда (A2) волатильность равна нулю, и обратная величина дала бы ему бесконечный вес — дефект…
  - L67 `TestInverseVolWeights.test_same_universe_as_control_arm(self)`
- L76 `class TestExits`
  - L78 `TestExits.test_untouched_leg_keeps_full_period(self)`
  - L88 `TestExits.test_exit_replaces_period_return(self)`
  - L95 `TestExits.test_funding_is_prorated_not_kept_whole(self)` — Выбитая нога перестаёт получать начисления. Оставить их целиком значило бы дарить книге доход, которого не бы…
  - L105 `TestExits.test_long_pays_funding_with_correct_sign(self)`
- L112 `class TestBookStats`
  - L114 `TestBookStats.test_pnl_splits_by_leg(self)`
  - L123 `TestBookStats.test_unpaired_share_zero_when_nothing_fires(self)`
  - L128 `TestBookStats.test_unpaired_share_after_one_side_exits(self)` — Выбило одну короткую ногу из двух: осталось 0.5 лонга против 0.25 шорта, перекос — треть оставшегося гросса.
  - L136 `TestBookStats.test_turnover_counts_only_fired_legs(self)`
- L143 `class TestVolFloor` — Пол волатильности. Без него правило 1 — ловушка замороженных рядов.
  - L146 `TestVolFloor.test_near_frozen_name_cannot_take_the_leg(self)` — Замер, поймавший дефект: σ медианы 0.008 против 0.000057 у 0.1-го процентиля, и такой актив забирал до 92.7 %…
  - L158 `TestVolFloor.test_floor_is_taken_from_the_section_not_a_constant(self)` — Волатильность универсума меняется с режимом рынка: пол, заданный числом, связывал бы то слишком сильно, то ни…
  - L167 `TestVolFloor.test_high_vol_tail_is_not_trimmed(self)` — Подавлять волатильные имена и есть смысл правила — верхний хвост подрезать нельзя.
  - L175 `TestVolFloor.test_still_downweights_the_volatile_name(self)`

## research/s8_loop/test_books.py · 263 строк

Проверки реестра книг.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L29 `FAILED = []`
- L32 `check(name, ok, got='')`
- L40 `SNAPSHOT = (('h4', 'model', '4 h · per σ', 'timer'…` — Снимок на день заведения реестра: ключ, каталог, подпись, семья, горизонт, торгуемая, эхо, согласная, кнопка.
- L64 `FIELDS = ('key', 'dir', 'label', 'family', 'hori…`
- L68 `test_registry_matches_the_snapshot()`
- L84 `test_registry_is_self_consistent()`
- L103 `_web_book_list()` — BOOK_LIST со страницы — разбором ТОГО ЖЕ куска JS, что уезжает в браузер. Копию списка на стороне питона здес…
- L120 `_web_hz_keys()` — Список законных ключей на СТРАНИЦЕ — его там быть не должно.
- L128 `test_readers_agree_with_the_registry()`
- L165 `_extras(rows)`
- L173 `test_factory_books_come_from_a_file()`
- L198 `test_a_bad_file_drops_candidates_and_names_the_reason()`
- L245 `main()`

## research/s8_loop/test_cycle_health.py · 234 строк

Проверки замера бюджета цикла.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L23 `FAILED = []`
- L26 `check(name, cond, detail='')`
- L34 `write_log(mdir, rows)`
- L42 `row(day, h, sec, seq, sections)` — Строка ЖИВОГО образца: метка `at` идёт форматом `%m-%d %H:%M`, то есть без года — ровно так её пишет цикл. Пе…
- L53 `test_median_is_a_median()` — Медиана на чётной длине — среднее двух средних, а не верхнее.
- L65 `test_verdict_comes_from_numbers()` — Вердикт выводится из чисел четырьмя ветками.
- L107 `test_day_key_survives_a_live_record()` — Ключ суток обязан пережить живую метку без года.
- L131 `test_kinds_are_counted_apart()` — Часовой цикл и цикл с обучением считаются раздельно.
- L153 `test_growth_is_measured_not_assumed()` — Растёт ли цикл с данными — ранговой связью, а не на глаз.
- L169 `test_e2e_report()`
- L215 `main()`

## research/s8_loop/test_s8.py · 5730 строк

Тесты S8.1. Главные — заглядывание (один тест на ВСЕ признаки, правило M1) и правильность пути (MFE/MAE): на…

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L36 `FAILED = []`
- L40 `check(name, cond, detail='')`
- L50 `_snap(mid, reach_bp, t, big=1000.0)`
- L61 `test_summary_censors_bands_by_reach()`
- L77 `test_summary_tape()`
- L97 `test_summary_roundtrip_through_store()` — Синтетическая запись через настоящий Writer и read_hour.
- L123 `test_run_resumes_by_content()` — Возобновление — по содержимому дневного файла (урок L2).
- L145 `synth_summary(S=40, D=600, seed=3)`
- L185 `_mutate_after(s, t0, seed=9)`
- L195 `test_no_lookahead_any_feature()`
- L212 `test_forward_path_exact()`
- L232 `test_formations_semantics()` — Формации обязаны показывать то, что означают по-трейдерски.
- L271 `test_metrics_liq_in_summary()` — Сводка часа: funding/интерес/базис — последняя точка часа, ликвидации — суммы по сторонам с соглашением Bybit.
- L304 `test_context_features()` — Время, лидер, сектор, круглые числа — смыслом, не только отсутствием заглядывания.
- L353 `test_eligibility_floor()`
- L362 `test_eligibility_by_coverage()` — Пригодность часа — покрытие во времени, а не число снимков.
- L390 `test_targets_shapes_and_direction()`
- L431 `test_one_name_one_position()` — Одно имя — одна позиция: долив своей стороны, схлопывание чужой.
- L490 `test_merge_adds_shows_one_position()` — Долив — точка на одной позиции, а не отдельная сделка.
- L585 `test_name_cap_and_inv_risk_sizing()` — Забор 10 % на имя и рука 1/σ² — числами, с отрицательным смыслом.
- L645 `test_zero_length_trade_returns_its_money()` — Сделка, закрытая в секунду своего же входа, не течёт кассой.
- L682 `test_rank_key_reorders_the_section()` — Книга в σ обязана ранжировать ДРУГОЙ величиной.
- L748 `test_retry_when_not_trained()` — Цикл ежечасный ВСЕГДА — удался он или нет.
- L788 `test_readiness_is_written_before_training()` — Готовность обязана быть файлом ДО того, как модель появится.
- L835 `test_canary_not_computed_is_not_a_pass()` — Непосчитанная проверка на течь не является пройденной.
- L874 `test_report_flags_manifest_from_a_previous_run()` — Манифест прошлого прогона не смеет выдавать себя за нынешний.
- L955 `test_capital_returns_before_it_is_redeployed()` — В один момент закрытие идёт раньше открытия.
- L998 `test_cash_returns_when_the_review_is_written()` — Касса узнаёт исход не раньше записи разбора.
- L1095 `test_rr_filter_is_one_definition_and_recounts_money()` — Фильтр по обещанному отношению: одна формула и честный счёт.
- L1139 `test_sverka_pairs_cash_reject_with_zero_size()` — Сверка: отказ ядра по пустой кассе — пара нулевому размеру.
- L1194 `test_picks_never_take_non_crypto()` — Выбор монет не берёт не-крипто — ни по списку, ни по суффиксу.
- L1217 `test_flat_names_are_measured_not_listed()` — Плоское имя мерится по записи, а не ведётся списком.
- L1278 `test_horizon_books_review_with_their_own_target()` — Книга каждого горизонта разбирается СВОЕЙ целью и в СВОЙ каталог.
- L1345 `test_situational_book_enters_and_exits_by_situation()` — Ситуационная книга: вход только от сканера, выход по причинам.
- L1854 `test_pretest_comes_after_the_summary_is_written()` — Предпросмотр приходит ПОСЛЕ боевого цикла, а не вместе с ним.
- L1910 `test_hourly_cycle_wakes_on_the_hour()` — Часовой цикл ждёт до ГРАНИЦЫ часа, а не час от прошлого раза.
- L1931 `test_account_is_one_capital_at_leverage_one()` — Счёт ведётся на ОДИН капитал, экспозиция его не превышает.
- L2007 `test_unrealised_never_mixes_with_realised()` — Нереализованное считается отдельно и тем же размером позиции.
- L2060 `test_both_ends_of_the_path_are_recorded_and_mirrored()` — Ход против и ход в пользу — зеркальны по стороне и оба в записи.
- L2160 `test_drawdown_is_measured_not_inferred_from_the_outcome()` — Просадка сделки — ход ПРОТИВ по дороге, а не её итог.
- L2221 `test_drawdown_is_reported_against_the_deposit()` — Просадка сделки считается от ДЕПОЗИТА, а не от позиции.
- L2277 `test_pretest_hedges_with_beta_one_and_keeps_books_apart()` — Предпросмотр хеджит бетой = 1, а смена режима начинает книгу заново.
- L2342 `test_worst_open_book_is_not_the_worst_trade()` — Общая просадка книги — все живые позиции разом, а не худшая из них.
- L2406 `test_sign_counts_only_trades_that_reached_a_level()` — «Знак угадан» — про геометрию сделки, а не про то, где её застали.
- L2470 `test_summary_splits_pnl_by_side()` — Итог по ногам считается раздельно, доля — от СТАРТОВОГО депозита.
- L2521 `test_account_drawdown_counts_open_positions()` — Просадка счёта считается с переоценкой открытых, а не по закрытиям.
- L2589 `test_execution_is_walked_through_the_recorded_book()` — Издержки — по записанной книге, а не константой.
- L2681 `test_backfill_recovers_the_book_for_old_trades()` — Старым сделкам книга дописывается из записи, а не выдумывается.
- L2804 `test_entry_gift_is_measured_before_it_is_removed()` — Вход по цене сигнала — подарок, и его сперва меряют.
- L2847 `test_exposure_covers_all_open_and_leverage_is_named()` — Экспозиция — по всем открытым; в долларах её читать нельзя.
- L2906 `test_entry_price_is_recovered_from_summaries()` — Цена входа у старых выборов не потеряна — она в сводке.
- L2954 `test_unrealised_marks_open_positions_only()` — Нереализованный результат — по живой цене и только у открытых.
- L2994 `test_awaiting_review_is_not_a_lost_outcome()` — Ожидание разбора и потерянный исход — разные состояния.
- L3039 `test_entry_is_the_close_of_the_signal_hour()` — Вход — на ЗАКРЫТИИ часа решения, а не на его начале.
- L3080 `test_one_pick_per_arm_and_hour()` — Выбор пишется один раз на (руку, час), сколько бы ни было проходов.
- L3131 `test_trades_close_on_an_hourly_cycle()` — Сделки обязаны закрываться при часовом цикле и цели в 4 часа.
- L3197 `test_adverse_path_matches_the_side()` — Ход ПРОТИВ позиции у лонга и шорта — разные цели.
- L3246 `test_percent_is_the_display_unit()` — Сделки показываются в ПРОЦЕНТАХ движения цены, не в б.п.
- L3283 `test_pretest_runs_where_live_refuses_and_stays_apart()` — Предпросмотр показывает работу там, где боевой обязан молчать.
- L3374 `test_probe_never_touches_live_model()` — Пробный прогон пишет в свой каталог и метит себя в артефакте.
- L3422 `test_novelty_measure()` — Новизна: доля признаков вне диапазона обучения, NaN не судится.
- L3448 `test_live_ic_survives_hourly_retraining()` — Живой IC обязан считаться и при переобучении каждый час.
- L3534 `test_live_ic_shown_as_median_not_last_hour()` — Страница показывает медиану сечений, а не последний час.
- L3569 `test_declared_candidate_gets_a_live_book()` — Объявленный кандидат получает ЖИВУЮ книгу, а не только реплей.
- L3684 `test_a_book_dropped_from_the_composition_is_retired()` — Книга, выпавшая из состава, отставляется, а не висит открытой.
- L3774 `test_a_strategy_keeps_its_own_deposit()` — Депозит стратегии — 1000 $ на руку, и счёт строится на нём.
- L3847 `test_candidate_books_are_not_written_by_a_sandbox_run()` — Песочный прогон боевой состав книг НЕ переписывает.
- L3871 `test_train_cycle_end_to_end()`
- L4103 `test_flat_name_never_reaches_the_scanner_sheet()` — Плоское имя не доезжает до ЛИСТА сканера, а не только до rows_m.
- L4168 `test_low_rr_book_is_declared_with_a_ceiling()` — Книга низкого RR объявлена листом и манифестом (владелец, 2026-08-22).
- L4222 `test_books_run_before_training_on_prev_weights()` — Книги идут ДО обучения, на весах прошлого часа (правка SCRTUSDT).
- L4309 `test_nn_learns_and_sees_missing()` — Сеть учится и видит пропуск флагом, а не затиркой.
- L4362 `test_think_words()` — Мысли — чистая функция от чисел; слова обязаны следовать за числами, а не украшать их.
- L4391 `test_load_matrices_grid_is_continuous()`
- L4409 `test_sigma_targets_exist_on_every_horizon()` — Порядок сечения нельзя задать целью, которой не существует.
- L4439 `test_book_archives_when_the_order_changes()` — Книга, упорядоченная иначе, — ДРУГАЯ книга.
- L4524 `test_repair_returns_the_model_and_leaves_the_book()` — Разбор последствий: модель возвращается, книга остаётся в архиве.
- L4590 `test_adopting_the_same_book_keeps_its_history()` — Книга, которой главная СТАЛА, уже существовала — её и продолжаем.
- L4684 `test_non_crypto_split_by_book_kind()` — Не-крипто: часовые книги не видят, ситуационная вправе.
- L4720 `test_entry_floor_gates_the_main_book()` — Пол входа: тихий час не торгуется, смена пола отставляет книгу.
- L4782 `test_books_order_by_their_own_sigma()` — Порядок сечения — свойство книги, и он один на весь цикл.
- L4804 `test_fixed_risk_sizing_equalises_dollar_risk()` — Рука равного риска: стоп всегда −R, тейк при RR r — +r·R.
- L4851 `test_no_outcome_returns_principal()` — Деньги сделки «без исхода» возвращаются принципалом.
- L4901 `test_basket_echo_books()` — Корзинные книги-эхо: копия выборов, порог суммы, закрытие разом.
- L5027 `test_basket_only_book()` — h24c: ни одного отдельного выхода — таймерные разборы источника не копируются вовсе, закрывает только корзина…
- L5138 `test_fresh_sit_version_for_echo_books()` — `version=1` у эха: решает словарь правил, а не версия v13.
- L5180 `test_sit_absorb_lives_in_one_module()` — Поглощение живых событий: и сборщик, и цикл зовут один код.
- L5252 `test_trade_ids_are_stable()` — Id сделки: выводится из полей записи и переживает пересборку.
- L5288 `test_day_brake_math_and_activation()` — Арифметика дневного тормоза и правило «действует сейчас».
- L5323 `test_training_runs_on_a_cadence_not_every_hour()` — Обучение ушло из ЧАСОВОГО пути на объявленную каденцию.
- L5432 `test_day_brake_blocks_entries_not_reviews()` — Сквозной цикл: тормоз закрывает ВХОДЫ часовых книг, не разбор.
- L5499 `test_agree_echo_book()` — Согласное эхо: у источника остаётся ровно пересечение рук.
- L5626 `main()`

## research/s9_sweep/test_sweep.py · 179 строк

Проверки перебора правил: геометрия сделки и отбор ног.

- L15 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `FAIL = []`
- L22 `check(name, ok, extra='')`
- L29 `bar(t, o, h, l, c)`
- L33 `test_bracket()`
- L83 `test_net_and_rr()`
- L104 `test_stop_walk()` — Пробой обещанной линии и возврат к цели — арифметика руками.
- L167 `main()`

## research/t1_tape/test_tape.py · 384 строк

Тесты модуля ленты. Синтетика плюс одна проверка на живом файле.

- L19 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `FAILED = []`
- L27 `check(name, cond, detail='')`
- L35 `synth()` — Пять принтов в двух секундах, знаки и цены известны.
- L44 `test_grid_volumes()`
- L57 `test_grid_prices()`
- L72 `test_grid_empty_cell_is_nan()` — Пустая ячейка — пропуск, а не наблюдение с нулевой доходностью.
- L85 `test_footprint()`
- L97 `test_rolling_sum()`
- L105 `test_absorption_finds_held_price()` — Льют объём, цена стоит — это поглощение.
- L137 `test_absorption_ignores_move()` — Тот же объём, но цена провалилась — это не поглощение.
- L163 `test_side_is_aggressor_on_real_file()` — Живая проверка: агрессивная покупка обязана двигать цену вверх.
- L186 `two_sided_spike(one_sided)` — Всплеск объёма при стоящей цене: односторонний или двусторонний.
- L208 `test_imbalance_separates_accumulation()` — Перевес: льют в одну сторону — накопление; обе бьются — нет.
- L226 `level_tape(spread)` — Всплеск продаж: весь на одной цене либо размазанный по ходу.
- L254 `test_level_filter_measures_concentration()` — Набор на цене против объёма, размазанного по ходу окна.
- L282 `test_level_filter_flat_window()` — Цена не двигалась вовсе — предельный набор, а не деление на ноль.
- L295 `load_probe()`
- L301 `test_excursions_match_per_horizon()` — Один проход на все горизонты обязан дать то же, что проход на каждый.
- L341 `test_cross_width_counts_only_clean()` — Ширина фона: сам актив в него не входит, запрещённые тоже.
- L356 `main()`

## research/t3_brackets/headless_check.js · 39 строк

Прогон логики страницы без браузера: canvas и DOM подменены

- L19 `mkEl()`

## research/t3_brackets/test_brackets.py · 157 строк

Тесты замера сделки. Закрывают места, где ошибка была бы невидимой.

- L19 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L28 `FAILED = []`
- L31 `check(name, cond, detail='')`
- L39 `grid_from(prices, step=1.0)` — Сетка из последовательности `(open, high, low, close)` по секундам.
- L50 `flat(v)`
- L54 `test_target_hit()`
- L63 `test_stop_hit()`
- L71 `test_tie_goes_against_us()` — В одну секунду задеты оба уровня — считается стоп.
- L83 `test_timeout()`
- L91 `test_entry_skips_empty_seconds()` — Секунда без сделок — не наблюдение, вход берётся со следующей.
- L100 `test_shelf_is_nearest_ahead()` — Цель — ближайшая полка впереди, а не самая крупная.
- L111 `test_shelf_none_when_nothing_ahead()`
- L118 `test_break_even_arithmetic()` — Безубыточная доля побед: при 1 к 3 и издержках она около трети.
- L128 `test_seed_is_reproducible_by_number()`
- L136 `main()`

## research/t3_brackets/test_render.py · 185 строк

Тесты выгрузки и страниц. Ловят молчаливую пустоту.

- L22 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L28 `FAILED = []`
- L29 `OUT = os.path.join(HERE, 'out')`
- L32 `check(name, cond, detail='')`
- L40 `test_minute_bars()` — Минутные свечи из секундной сетки: края берутся по сделкам.
- L67 `test_tick_is_measured()`
- L75 `encode_decode(bars)` — То же преобразование, что в выгрузке, и обратно.
- L102 `test_encoding_round_trip()` — Сжатие, меняющее числа, есть другой график, а не тот же поменьше.
- L131 `render_if_possible(script, tag)`
- L146 `test_pages_have_data()`
- L169 `main()`

## research/t4_structure/test_exits.py · 124 строк

Тесты потолка геометрии.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L28 `FAILED = []`
- L31 `check(name, cond, detail='')`
- L39 `bars(seq, t0=60)` — Свечи из списка (high, low) на минутной сетке.
- L44 `row(pos=1, entry=100.0, stop=99.0, target=102.0)`
- L49 `test_tie_inside_bar_goes_against_us()`
- L57 `test_target_and_stop_read_in_order()`
- L64 `test_short_flips_the_sign()`
- L71 `test_drawdown_measured_before_target_not_after()`
- L82 `test_wider_stop_lets_losers_run()`
- L101 `test_no_bars_is_not_a_zero_trade()`
- L106 `main()`

## research/t4_structure/test_levels.py · 167 строк

Тесты структурных уровней.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `FAILED = []`
- L27 `check(name, cond, detail='')`
- L35 `test_noise_is_median_range()`
- L46 `test_shelf_found_where_volume_sits()` — Полка обязана появиться там, где прошёл объём, и только там.
- L60 `test_round_levels_scale_with_price()` — Шаг круглых чисел берётся от масштаба цены, а не назначается.
- L72 `test_nearest_and_ahead()`
- L91 `test_stop_is_outside_noise()` — Стоп, поставленный по правилу, обязан быть больше шума.
- L113 `test_build_needs_history()`
- L125 `test_noise_follows_recent_regime()` — Шум обязан следовать текущему режиму, а не суточному среднему.
- L148 `main()`

## research/w1_waves/test_filter_probe.py · 334 строк

Проверки волнового фильтра.

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L29 `THETA = 0.03`
- L32 `test_state_is_causal_and_confirmation_gated()` — Будущее состояния не меняет; неподтверждённая вершина не видна.
- L61 `test_state_numbers_by_hand()` — Числа состояния сходятся с карандашом, знак — с направлением.
- L84 `test_stale_price_gives_no_state()` — Протухшая цена — не состояние: дыра длиннее MAX_GAP даёт NaN.
- L107 `test_day_hour_maps_to_the_last_hour_of_the_day()` — День решения — открытие его ПОСЛЕДНЕГО часа, числом.
- L115 `synth_judge(hetero, n_days=120, n_names=90, seed=5)` — Матрица-фикстура для машины суда: навык либо ровный, либо сосредоточен в верхней трети волнового состояния.
- L142 `test_planted_heterogeneity_is_found_and_flat_skill_is_flat()` — Суд находит подсаженную неоднородность и молчит на ровной.
- L165 `test_discrete_state_needs_a_matched_null()` — Дискретное состояние без неоднородности: честный нуль молчит, нуль равных третей кричит.
- L224 `test_reading_comes_from_the_numbers()` — Фраза вывода — из чисел: три ветки, и каждая по своему числу.
- L238 `test_wave_columns_map_assets_to_symbols_and_rows()` — Актив матрицы → символ Binance → своя строка, не чужая.
- L277 `test_main_road_and_publish_gating()` — Сквозная дорога main: отчёт написан, публикация обеих сторон.
- L311 `main()`

## research/w1_waves/test_grammar.py · 289 строк

Проверки ядра грамматики волн.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L30 `THETA = 0.03`
- L33 `build(sizes, pre=(0.06, 0.0), tail=0.05, step=0.005)` — Пила: разгонная пара вершин, затем ноги заданных размеров.
- L50 `legs_of(sizes, **kw)`
- L55 `find_impulse(lg, sizes, tol=0.01)` — Окно, чьи ноги совпали с заданными размерами.
- L71 `test_textbook_impulse_passes_every_rule()` — Хрестоматийный импульс: все правила да, растяжения и усечения нет.
- L93 `test_each_forgery_breaks_exactly_its_rule()` — Каждая подделка ломает своё правило — и оно названо поимённо.
- L120 `test_mirror_gives_the_same_answers()` — Нисходящий импульс отвечает так же, как восходящий.
- L143 `test_window_across_a_seam_does_not_exist()` — Окно через шов (пропущенную пару ног) не собирается.
- L158 `test_near_share_band_is_relative()` — Полоса отношений относительная: у 2.618 она шире, чем у 0.618.
- L167 `test_contraction_is_found_and_its_aftermath_is_signed_by_pre_le…` — Сжатие находится, исход подписан докоррекционной ногой.
- L187 `test_subdivision_counts_inner_pivots_only()` — Дробление: вершина на границе — граница, а не внутренность.
- L197 `test_leg_queries_need_a_contiguous_chain()` — Запрос строится только на цепочке встык, и числа — те самые.
- L222 `test_planted_grammar_is_found_and_null_is_blind_to_it()` — Подсаженная грамматика находится, нуль на ней слеп.
- L247 `test_knn_guard_excludes_own_symbol_and_own_time()` — Свой символ и своё время в соседи не идут — проверяется прямо.
- L265 `main()`

## research/w1_waves/test_grammar_probe.py · 199 строк

Проверки прогона грамматики.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `class Cfg`
  - L27 `Cfg.__init__(self, **kw)`
  - L30 `Cfg.__enter__(self)`
  - L36 `Cfg.__exit__(self, *a)`
- L41 `test_theta_is_fixed_before_the_measured_region()` — Порог — из первых 60 суток; будущее его не трогает.
- L60 `mk(**over)` — Свод-фикстура. Умолчание — «факт неотличим от суррогата».
- L75 `elliott(base)` — Свод, отличающийся от базы в предсказанную Эллиоттом сторону.
- L88 `_report(res, sub, knn)`
- L99 `test_verdict_counts_come_from_the_numbers()` — Подтверждённые закономерности считаются, а не пишутся прозой.
- L140 `test_probe_runs_end_to_end_on_random_walks()` — Сквозная дорога: случайные блуждания, отчёт написан, публикация обеих сторон.
- L182 `main()`

## research/w1_waves/test_probe.py · 481 строк

Проверки прогона волнового зонда.

- L29 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L36 `HOUR = 3600`
- L40 `SHAPES = {0: np.linspace(0.0, 1.0, 9), 1: np.lin…` — Три «типа» рынка: у каждого своя форма и своё будущее. Формы взяты заведомо различимыми — задача проверки не…
- L46 `FWD = {0: +0.03, 1: -0.03, 2: 0.0}`
- L49 `class Cfg` — Малая объявленная сетка на время проверки: дороги те же.
  - L52 `Cfg.__init__(self, **kw)`
  - L56 `Cfg.__enter__(self)`
  - L62 `Cfg.__exit__(self, *a)`
- L67 `synth(planted, n_sym=60, pool_days=60, test_days=40, w=8, query…` — Универсум случайных блужданий; при `planted` в него сажают волну.
- L102 `_run(planted, seed=3)`
- L116 `test_probe_finds_a_wave_that_is_really_there()` — Подсаженная волна обязана находиться — иначе ноль ничего не значит.
- L135 `test_pure_random_walks_give_nothing()` — На случайных блужданиях около ноля обязаны быть ОБА числа.
- L151 `test_break_even_ic_is_computed_from_the_measured_spread()` — Порог окупаемости считается из σ ячейки, а не назначается.
- L175 `test_pool_is_strictly_in_the_past()` — Соседи берутся только из прошлого — проверяется САМА граница.
- L212 `test_sample_pool_respects_its_bounds()` — Пул не отдаёт ни одной колонки вне запрошенного окна.
- L228 `test_excess_is_over_the_equal_weight_section()` — Избыток считается сверх РАВНОВЗВЕШЕННОЙ кросс-секции.
- L251 `test_prediction_needs_enough_neighbours()` — Мало соседей с известным будущим — ПРОПУСК, а не значение по тем.
- L272 `test_path_ends_in_its_own_column()` — Путь кончается СВОЕЙ колонкой и не заглядывает вперёд.
- L294 `test_report_is_written_and_its_verdict_comes_from_the_numbers()` — Отчёт собирается настоящим вызовом, а фраза выводится из числа.
- L352 `test_zigzag_report_road_runs_and_compares_to_surrogate()` — Дорога прочитки 2 исполняется целиком и кладёт обе стороны.
- L391 `test_memory_is_counted_before_the_run_not_after_the_kill()` — Не влезаем — отказ со словами; влезаем — молчание. Обе стороны.
- L413 `test_empty_matrix_is_a_refusal_not_an_absence_of_waves()` — Пустая загрузка обязана падать со словами, а не печатать ноль.
- L430 `test_publication_is_part_of_the_run()` — С ключом публикации нет, без ключа — есть. Обе стороны.
- L454 `main()`

## research/w1_waves/test_waves.py · 300 строк

Проверки ядра волнового зонда.

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `FAILED = []`
- L29 `check(name, cond, extra='')`
- L36 `saw(peaks, step=1.0)` — Пила из логарифмических цен по заданным вершинам.
- L46 `test_zigzag_is_causal()` — Вершина подтверждается ПОЗЖЕ, чем случается, и обе метки видны.
- L67 `test_zigzag_costs_confirmation_lag_and_it_grows_with_theta()` — Задержка подтверждения — не мелочь: она растёт с порогом.
- L81 `test_gap_breaks_the_wave()` — Через разрыв записи волна не продолжается.
- L94 `test_leg_over_a_gap_is_a_splice_not_a_leg()` — Нога через дыру записи — склейка, и с `max_gap` её не существует.
- L135 `test_leg_ratio_is_what_a_trader_would_measure()` — Коэффициент отката — отношение ноги к предыдущей, карандашом.
- L147 `test_fib_shares_count_what_they_say()` — Доли Фибоначчи считаются по объявленной полосе, а не на глаз.
- L158 `test_surrogate_keeps_the_values_and_the_gaps()` — Суррогат — те же приращения и та же дырявость, другой порядок.
- L173 `test_frozen_path_is_not_a_shape()` — Замороженный ряд не даёт формы — пропуск, а не единичный вектор.
- L203 `test_shape_ignores_level_and_scale()` — Одна форма на другом уровне и в другом масштабе — та же форма.
- L214 `test_planted_motif_is_found_first()` — Подсаженная форма находится первым соседом со сходством около 1.
- L229 `test_block_size_does_not_change_the_answer()` — Ускорение, меняющее числа, есть другая мера.
- L240 `test_forbidden_pool_never_shows_up()` — Запрещённый сосед не берётся — на нём и держится причинность.
- L260 `test_spearman_handles_ties_and_short_rows()` — Ранговая связь: ничья не даёт порядка, короткая строка — не мера.
- L273 `main()`

## research/z1_screen/test_screen.py · 425 строк

Тесты скрина Z1. Каждая дорога исполняется, а не подразумевается.

- L16 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L21 `FAILED = []`
- L24 `check(name, cond, extra='')`
- L31 `test_forward_never_touches_the_signal_bar()` — Вход по открытию СЛЕДУЮЩЕГО бара, а не того, что дал сигнал.
- L57 `test_dedup_keeps_one_event_per_series()`
- L68 `test_cross_section_excludes_own_events_and_thins_out()`
- L82 `synth(n_sym=120, n_min=3000, edge=0.004, seed=3)` — Синтетика: у половины «событий» есть настоящее превышение.
- L101 `run_cells(P, rows, cols, side=1, perms=40)`
- L118 `test_real_effect_beats_the_family_bar()`
- L129 `test_pure_noise_stays_under_the_bar()`
- L138 `test_buckets_do_not_degenerate_on_a_frequent_signal()` — Единица наблюдения обязана оставаться множественной.
- L153 `test_side_flips_the_sign()`
- L163 `test_matrix_medians_equal_the_naive_count()` — Матричный счёт нулей обязан совпасть с поэлементным.
- L192 `test_accumulator_does_not_grow_with_months()` — Накопитель не хранит сырых событий — иначе ядро убьёт прогон.
- L237 `test_short_vol_shape_is_named_not_reported_as_a_find()` — Медиана выше круга при отрицательном среднем — не находка.
- L268 `test_thin_cell_does_not_set_the_bar_for_everyone()` — Планка считается без тонких ячеек — иначе её назначает шум.
- L304 `test_open_interest_lag_is_time_not_steps()` — Строка интереса с меткой t известна только в t+5 минут.
- L338 `test_report_names_the_degenerate_control()` — Доля универсума в событии обязана доезжать до отчёта.
- L366 `test_units_are_yesterdays_and_zero_noise_is_a_gap()` — Нулевой шум — пропуск, а не «бесконечно сильный сигнал».
- L382 `test_since_shock_and_rolling_sum()`
- L396 `TESTS = [test_forward_never_touches_the_signal_…`
- L413 `main()`

## research/z2_book/test_bench.py · 174 строк

Проверки замера цены разбора лесенки.

- L14 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L23 `_setup(days, syms)`
- L36 `test_ladder_parse_matches_json_and_is_measured_on_live_lines()` — Разбор лесенки обязан совпасть с `json.loads` дословно.
- L76 `test_report_names_the_price_of_both_passes()` — Отчёт обязан назвать и сплошной проход, и точечный.
- L120 `test_heavy_pair_is_sampled_explicitly()` — BTC и ETH пишутся темой в 200 уровней — строка вчетверо тяжелее.
- L138 `test_publish_is_part_of_the_run()` — С ключом публикации нет, без ключа она ОБЯЗАНА случиться.
- L156 `main()`

## research/z2_book/test_bookfeat2.py · 199 строк

Тесты разбора и сведения записи стакана.

- L13 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L18 `FAILED = []`
- L21 `check(name, cond, extra='')`
- L28 `snap(t, ts_ms, bid, ask, bq=1000.0, aq=1200.0, upd=7, bsz=3.0, …` — Строка снимка ровно того вида, что пишет сборщик.
- L45 `test_light_parse_matches_json()` — Быстрый разбор обязан совпасть с `json.loads` дословно.
- L60 `test_fast_and_slow_parsers_agree()` — Быстрый разбор обязан совпасть с медленным и с `json.loads`.
- L92 `test_observation_moment_is_the_later_of_two_stamps()` — Метка `t` ставится ОДИН РАЗ на весь проход по символам.
- L109 `test_empty_minute_is_a_gap_not_zeros()`
- L120 `test_quiet_path_counts_moves_without_trades()` — Ход середины БЕЗ единой сделки — величина, которой нет в ленте.
- L138 `test_pull_separates_cancels_from_trades()` — Снятие заявок — то, что НЕ объяснено сделками.
- L168 `test_path_is_not_stitched_across_minutes()` — Путь минуты не сшивается с прошлой: это её собственная величина.
- L178 `TESTS = [test_light_parse_matches_json, test_fa…`
- L187 `main()`

## research/z2_book/test_fold.py · 741 строк

Тесты минутного склада записи стакана.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L35 `_setup(days, syms, hours=(10, 11), per_min=4, seed=7)`
- L47 `_restore(old)`
- L52 `_same(a, b)`
- L57 `test_store_reproduces_raw_bit_for_bit()` — Матрицы со склада и из сырья равны точно, включая пропуски.
- L91 `test_unfinished_day_is_not_folded()` — Текущие сутки не сворачиваются: половина дня выглядела бы целой.
- L113 `test_state_is_read_from_disk_not_from_the_run()` — Обход склада знает о сутках, которых этот процесс не сворачивал.
- L143 `test_foreign_version_falls_back_loudly()` — Склад чужой версии не берётся молча — падает на сырьё со словами.
- L176 `test_store_version_is_asked_not_taken_from_the_book_constant()` — Версию склада сверяет ПАРАМЕТР, а не константа книжного склада.
- L213 `test_symbol_absent_that_day_is_a_gap_and_order_is_the_asked_one…` — Состав записи растёт по дням: чужое имя — строка пропусков.
- L237 `test_fields_of_the_screen_are_a_subset_of_the_fold()` — Поле замера, которого нет в свёртке, дало бы матрицу пропусков.
- L245 `test_parallel_fold_equals_single_threaded()` — Три потока обязаны дать тот же склад, что один.
- L265 `test_cli_runs_the_whole_road()` — Настоящий `main()`: находит сутки в сырье, сворачивает, пишет сводку.
- L311 `test_report_names_the_days_the_store_is_missing()` — Главное число отчёта — сутки записи, которых на складе нет.
- L330 `test_report_separates_full_days_from_stumps_and_names_recording…` — Покрытие и дыры записи — числами, а не арифметикой в уме.
- L391 `test_density_catches_thinning_that_coverage_cannot()` — Прорежение видно плотностью и НЕ видно покрытием.
- L432 `test_hour_grid_is_the_control_that_same_day_hours_are_not()` — Просевший ЧАС последних суток ловится сравнением с теми же часами.
- L483 `test_even_base_uses_a_true_median_not_the_upper_middle()` — `sorted(x)[n // 2]` на чётной длине берёт ВЕРХНЕЕ из двух средних.
- L527 `test_flow_tells_market_from_our_load_one_way()` — Выросшая лента при упавших снимках означает рынок.
- L587 `test_screen_starts_at_the_first_full_and_wide_day()` — Замер начинается с полных и ШИРОКИХ суток, а не с первых суток.
- L630 `test_publish_is_part_of_the_run()` — С ключом публикации нет, без ключа она ОБЯЗАНА случиться.
- L651 `test_partial_day_is_not_taken_for_folded()` — Сутки, свёрнутые по одному имени из трёх, свёрнутыми не считаются.
- L706 `main()`

## research/z2_book/test_probe.py · 406 строк

Сквозные тесты скрина по записи стакана.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `FAILED = []`
- L29 `check(name, cond, extra='')`
- L36 `write_rec(root, syms, days, hours=(10, 11), per_min=4, seed=1, …` — Записать поддельную запись ровно в том виде, что пишет сборщик.
- L112 `run(root, syms, days, tag='test')`
- L129 `test_end_to_end_over_real_files()`
- L179 `test_drift_is_zero_with_the_mean_control()` — Снос по стороне обязан быть около нуля — встроенная проверка меры.
- L218 `test_declared_horizons_are_the_measured_ones()` — Горизонты замера обязаны совпасть с объявленными в Z2.
- L250 `test_norms_wiring_uses_the_previous_day()` — Нормы обязаны ДОЕХАТЬ до замера от вчерашних суток.
- L294 `test_thin_minute_and_missing_norms_are_gaps()`
- L317 `test_norms_come_from_yesterday_only()` — Норма, посчитанная по тем же суткам, знала бы будущее внутри дня.
- L332 `test_cell_row_carries_the_drift_of_its_own_horizon()` — Снос своего горизонта обязан стоять В СТРОКЕ ячейки.
- L385 `TESTS = [test_end_to_end_over_real_files, test_…`
- L394 `main()`

## research/z3_ladder/test_fold_ladder.py · 476 строк

Проверки прохода лесенки: свой склад, чужой не трогается.

- L9 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L10 `Z2 = os.path.join(os.path.dirname(HERE), 'z2…`
- L20 `TICK = 0.01`
- L21 `LEVELS = 12`
- L24 `write_ladder_rec(root, syms, days, hour=10, per_min=30, seed=3,…` — Запись с НАСТОЯЩЕЙ лесенкой: уровни на сетке шага цены.
- L132 `_setup(days, syms, per_min=4)`
- L143 `_restore(old)`
- L147 `test_ladder_folds_into_its_own_store_and_leaves_the_book_alone()` — У лесенки свой склад, и книжный она не трогает.
- L184 `test_flows_reach_the_minute_grid_with_real_numbers()` — Числа обязаны доехать от пары снимков до минутной сетки.
- L229 `test_trades_are_matched_to_their_own_interval()` — Сделка объясняет убыль ТОГО интервала, в котором случилась.
- L254 `test_interval_boundary_is_strict_on_the_left()` — Принт ровно в момент предыдущего снимка принадлежит ПРОШЛОМУ интервалу.
- L276 `test_symbols_can_be_given_by_a_repeated_key()` — Имена можно давать повторным ключом, а не только через запятую.
- L310 `test_observation_moment_is_the_later_of_two_times()` — Момент наблюдения — позднее из метки сборщика и метки биржи.
- L335 `test_report_counts_a_smoke_day_as_not_folded()` — Сутки, свёрнутые смоуком, отчёт называет частичными, а не готовыми.
- L376 `test_hourly_reading_equals_the_whole_day_bit_for_bit()` — Почасовое чтение обязано совпасть с посуточным ТОЧНО.
- L454 `main()`

## research/z3_ladder/test_ladder.py · 254 строк

Проверки ядра потоков по ценовым уровням.

- L10 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L16 `FAILED = []`
- L19 `check(name, ok, extra='')`
- L26 `snap(t, bid, ask, b, a)`
- L30 `test_price_leaving_the_visible_ladder_is_not_a_cancel()` — Цена, ушедшая за край лесенки, снятием НЕ является.
- L47 `test_decrease_explained_by_a_trade_is_not_a_cancel()` — Убыль, объяснённая сделкой на этой же цене, — не снятие.
- L63 `test_level_death_without_a_print()` — Уровень, ушедший в ноль без единой сделки, — смерть без принта.
- L76 `test_refill_is_counted_where_a_trade_happened()` — Подставленное на цене, где была сделка, — это восполнение.
- L85 `test_gap_gives_no_observation()` — Разрыв в записи не даёт наблюдения, а не даёт ноль.
- L102 `test_aggressor_side_eats_the_right_book()` — Покупающий агрессор ест АСКИ, продающий — биды.
- L119 `test_minute_is_a_gap_when_pairs_are_few()` — Минута из трёх снимков — пропуск, а не наблюдение.
- L142 `test_sweep_is_notional_per_basis_point()` — `sweep` — съеденный нотионал на базисный пункт хода середины.
- L170 `test_fast_merge_equals_the_reference_bit_for_bit()` — Быстрый путь обязан совпасть с образцовым БИТ В БИТ.
- L208 `test_unsorted_ladder_falls_back_instead_of_zeroing()` — Перемешанная лесенка считается ОБРАЗЦОВЫМ путём, а не обнуляется.
- L230 `main()`

## research/z3_ladder/test_screen3.py · 297 строк

Проверки скрина по лесенке: каждая дорога ИСПОЛНЯЕТСЯ.

- L17 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L18 `Z2 = os.path.join(os.path.dirname(HERE), 'z2…`
- L30 `DAYS = ['2026-08-18', '2026-08-19', '2026-08-2…`
- L34 `SYMS = [f'S{i:02d}USDT' for i in range(6)]` — Имён шесть, а не четыре: фон обязан существовать после запрета соседей, иначе контроль не строится ни для одн…
- L37 `_thin_judge()` — Понизить пороги СУДЬИ на время проверки дороги.
- L51 `_fat_judge(keep)`
- L55 `_setup(sparse_last=True)` — Три дня записи, у последнего минуты нарочно тонкие.
- L84 `_restore(old)`
- L89 `test_screen_runs_the_whole_road_and_says_it_is_diagnostics()` — Прогон целиком: два склада, судья, отчёт, числа в JSON.
- L117 `test_thin_minutes_are_a_gap_not_an_observation()` — Минута с малым числом пар не доезжает до замера вовсе.
- L150 `test_one_day_is_refused_because_norms_come_from_yesterday()` — Одни сутки — отказ словами, а не пустая таблица.
- L170 `test_horizons_must_match_the_book_screen()` — Разошлись горизонты с Z2 — прогон отказывается, а не считает.
- L191 `test_stats_mode_looks_at_features_and_never_at_outcomes()` — Режим распределения не читает ни цен, ни форвардов.
- L215 `test_narrow_days_and_stale_norms_are_kept_out()` — Узкие сутки не считаются, а норма — только с КАЛЕНДАРНО вчера.
- L277 `main()`

## bot/tests/e1.rs · 333 строк

Тесты E1: журнал и состояние.

- L16 `dir` — Свой каталог на тест: имя из номера процесса и имени теста, прежний сносится — прогон не зависит от мусора пр…
- L27 `open_ev`
- L43 `close_ev`
- L56 `six_events` — Шесть событий обычного часа: решение, отказ, два входа, выход, выключатель. По ним считаются почти все провер…
- L81 `write_all`
- L89 `state_json`
- L95 `roundtrip_числа_кассы_точны`
- L113 `рестарт_на_каждой_границе_восстанавливает_бит_в_бит`
- L136 `оборванный_хвост_отбрасывается_и_считается`
- L154 `порча_в_середине_это_ошибка_а_не_пропуск`
- L175 `ротация_сжимает_старые_сутки_и_читает_оба`
- L194 `сутки_в_двух_видах_не_читаются_дважды`
- L216 `битый_гзип_спасается_простым_близнецом_или_ошибка`
- L244 `противоречие_и_регресс_номеров_это_ошибки`
- L290 `двойное_открытие_и_чужое_закрытие_это_ошибки_состояния`
- L313 `повторное_открытие_продолжает_нумерацию_без_дублей`

## bot/tests/e2.rs · 357 строк

Тесты E2: тень обязана сходиться с Python-счётом до цента.

- L18 `fixture`
- L22 `tmp`
- L30 `cfg`
- L44 `struct Expected`
- L49 `struct ExpTrade`
- L66 `тень_сходится_с_питон_счётом_до_цента`
- L149 `ситуационная_тень_сходится_с_питон_счётом`
- L219 `журнал_переначинается_со_сменой_правил_книги`
- L247 `выключатель_отвергает_входы_и_отказ_терминален`
- L272 `срок_позиции_читается_у_книги_журнала`

## bot/tests/gen_parity.py · 256 строк

Фикстура чётности: Python-счёт порождает ожидаемые числа для Rust.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `REPO = os.path.dirname(os.path.dirname(HERE))`
- L28 `OUT = os.path.join(HERE, 'fixtures', 'parity')`
- L31 `FEES = [{'symbol': 'AAAUSDT', 'takerFeeRate': …`
- L39 `ladder(mid, side, thin=False)` — Накопленная лесенка вокруг середины, как штампует stamp_book.
- L54 `book(mid, thin=False)`
- L59 `leg(sym, px, drift_bp, thin=False, with_book=True)` — Нога выбора и её же исход: выход сдвинут на drift_bp от входа.
- L72 `main()`
- L131 `SIT_OUT = os.path.join(HERE, 'fixtures', 'parity_…`
- L134 `sit()` — Фикстура ситуационной книги: без срока, живые входы и выходы.

## bot/tests/live_x1.rs · 1429 строк

X1: исполнитель против подставной биржи.

- L21 `struct Placed`
- L33 `struct Inner`
- L59 `struct Mock`
- L61 `impl Mock`
  - L62 `Mock::new`
  - L69 `Mock::with_sym`
  - L80 `Mock::set_ioc_fills`
  - L83 `Mock::set_entry_error`
  - L86 `Mock::set_target_error`
  - L89 `Mock::placed`
  - L92 `Mock::cancelled`
  - L95 `Mock::push_position`
  - L100 `Mock::set_order`
  - L103 `Mock::set_order_later`
  - L106 `Mock::set_lev_error`
  - L109 `Mock::push_closed_pnl`
  - L112 `Mock::closed_pnl_calls`
  - L115 `Mock::apply_fill`
- L135 `impl Exchange for Mock`
  - L136 `Mock::best_prices`
  - L144 `Mock::instrument`
  - L152 `Mock::place_limit`
  - L213 `Mock::cancel`
  - L223 `Mock::order_status`
  - L240 `Mock::positions`
  - L243 `Mock::open_orders`
  - L246 `Mock::set_leverage`
  - L254 `Mock::wallet_usdt`
  - L257 `Mock::closed_pnl`
- L276 `struct Fx`
- L282 `impl Fx`
  - L283 `Fx::new`
  - L298 `Fx::entry`
  - L305 `Fx::exit`
  - L312 `Fx::cfg`
  - L329 `Fx::records`
- L334 `impl Drop for Fx`
  - L335 `Fx::drop`
- L340 `append`
- L358 `вход_ставит_ioc_и_цель_на_уровне`
- L400 `ioc_без_исполнения_отказ_и_три_подряд_остановка`
- L426 `выход_по_стопу_снимает_цель_и_закрывает`
- L471 `цель_исполнилась_закрытие_по_уровню`
- L513 `без_манифеста_книги_исполнитель_не_стартует`
- L528 `журнал_без_маркера_не_отставляется_а_останавливает`
- L567 `тейк_внутри_такта_не_останавливает_а_закрывает`
- L616 `цель_книги_без_исполнения_лимитки_это_расхождение_v13`
- L643 `расхождение_с_биржей_останавливает_без_закрытий`
- L667 `kill_означает_руки_прочь`
- L686 `предел_дня_закрывает_всё`
- L729 `маркер_снимает_денежные_пределы_и_только_их`
- L789 `сухой_прогон_не_отправляет_ничего`
- L815 `встречный_сигнал_закрывает_и_не_открывается`
- L838 `мелкая_нога_отвергается_без_заявки`
- L855 `перезапуск_берёт_количество_у_биржи`
- L898 `старое_событие_не_входит_после_закрытия`
- L926 `историческое_событие_не_торгуется_и_не_шумит`
- L958 `пауза_входов_файлом_не_трогает_выходы`
- L1007 `событие_у_полуночи_не_рвёт_журнал`
- L1047 `частичная_цель_не_останавливает_а_переставляется`
- L1114 `перезапуск_возвращает_цель_и_считает_частичное`
- L1161 `закрытое_руками_закрывается_записью_вне_исполнителя`
- L1189 `закрытое_руками_берёт_деньги_с_биржи`
- L1216 `нулевое_вне_исполнителя_доправляется_поправкой`
- L1255 `отказ_по_соглашению_не_входит_в_серию`
- L1280 `плечо_выставляется_раз_на_имя`
- L1298 `отказ_плеча_виден_в_статусе_и_снимается_успехом`
- L1331 `отказ_постановки_цели_виден_в_статусе_и_снимается_успехом`
- L1365 `повторная_постановка_цели_не_дублирует_метку`
- L1392 `перезапуск_находит_цель_по_метке_нового_образца`
- L1420 `потолок_является_потолком`

## bot/tests/watchdog.rs · 382 строк

Тесты сторожа исполнения: инварианты (`check`) и сверка (`sverka.py`).

- L21 `tmp`
- L29 `opts`
- L33 `open_ev`
- L50 `чистый_журнал_проходит_и_несёт_числа`
- L87 `поправка_денег_сходится_в_обеих_кассах`
- L119 `расхождение_кассы_с_историей_названо`
- L138 `плечо_выше_единицы_это_нарушение`
- L155 `застрявшая_позиция_и_тишина_решений_это_предупреждения`
- L201 `сверка_чиста_на_фикстуре_и_кусается_на_подделке`
- L291 `такт_демона_пишет_статус_и_не_молчит_об_ошибке`
- L375 `which_python`

## tools/test_jobs.sh · 236 строк

Проверка очереди заданий: она выполняет объявленное и отвергает всё

- L8 `say()`
- L9 `check()`
- L13 `has()`
- L35 `run()`

## tools/test_project_map.py · 246 строк

Проверка генератора карты кода и хука, который её перестраивает.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `REAL_ROOT = os.path.dirname(HERE)`
- L23 `FAILED = []`
- L26 `check(name, cond, detail='')`
- L32 `git(root, *args, **kw)`
- L37 `temp_repo(files)`
- L52 `with_root(root, fn)`
- L66 `test_real_repo()` — ------------------------------------------------------------ живой репо
- L89 `PY_FIX = <текст, 28 строк>` — ---------------------------------------------------------- разборщики
- L118 `RS_FIX = <текст, 16 строк>`
- L135 `RS_TEST_FIX = <текст, 3 строк>`
- L140 `test_parsers()`
- L169 `test_check_mode()` — ------------------------------------------------------ --check и хук
- L186 `test_hook_end_to_end()` — Дорога до вызова: не функция, а сам хук в настоящем коммите.
- L234 `main()`

## tools/test_safety.sh · 110 строк

Проверка проверки: safety_check обязан кусаться на каждом случае,

- L13 `say()`
- L14 `check()`

## tools/test_spill_book.py · 226 строк

Проверки `spill_book.py` на подставном дереве записи: переносятся только старые сжатые часы, оригинал уступае…

- L13 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L17 `TODAY = datetime.now(timezone.utc).date()`
- L20 `_day(n)`
- L24 `_tree()` — Источник: два символа, дни −10…−1, сжатые часы; плюс несжатый старый час и текущий день. Приёмник — отдельный…
- L50 `_files(src)`
- L59 `test_moves_only_old_compressed_hours_and_links_them()`
- L92 `test_dry_run_and_caps_do_not_move()`
- L122 `test_same_device_is_refused()`
- L136 `test_truncated_copy_leaves_the_original()`
- L166 `_poison(path, lit, sub, fn)` — --- отрицательные контроли ------------------------------------------------
- L189 `P = os.path.join(HERE, 'spill_book.py')`
- L192 `_control_copy_not_verified()`
- L197 `_control_same_device_allowed()`
- L202 `_control_plain_jsonl_moved_too()`
- L208 `TESTS = [test_moves_only_old_compressed_hours_a…`
- L211 `CONTROLS = [('копия не проверяется', _control_copy…`
- L216 `main()`

## tools/test_stop_run.py · 49 строк

Проверки `stop_run.py`: границы имени и совпадение по пути.

- L9 `PS = ['1572752 .venv/bin/python research/b1_…`
- L19 `test_protected_names_are_refused()`
- L30 `test_match_is_by_exact_script_path_of_a_python_process()`
- L38 `test_main_refuses_and_reports_absence()`

## tools/test_unstick.py · 87 строк

Проверка размораживателя публикации на ПОДСТАВНОМ репозитории.

- L18 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L25 `main()`
