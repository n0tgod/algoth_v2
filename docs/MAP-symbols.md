# Символы кода

Генерируется `tools/project_map.py`; руками не править. Строка — `L<номер>`; ищите грепом: `grep -n 'account(' docs/MAP-symbols.md`. Методы стоят под своим классом (`Класс.метод`), у Rust — под `impl` (`Тип::метод`). Тесты — в `docs/MAP-tests.md`.


## research/common/fees.py · 64 строк

Тейкерская ставка по символу — одна на весь проект.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `RESEARCH = os.path.dirname(HERE)`
- L27 `FEES_PATH = os.path.join(RESEARCH, 'a1_universe', '…`
- L31 `DEFAULT_TAKER_BP = 5.5` — Модальный тариф A1: 396 символов универсума из 722. Это умолчание, а не оценка — оно применяется только там,…
- L34 `load(path=FEES_PATH)` — `{символ: тейкер в б.п.}` из выгрузки A1.
- L59 `taker_bp(sym, table)` — `(ставка, известна ли)`. Второе — не украшение, а мера покрытия.

## research/common/flat_filter.py · 146 строк

Плоский инструмент: цены нет, а издержки есть.

- L39 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L40 `SUMMARY = os.path.join(os.path.dirname(HERE), 's8…`
- L44 `FLAT_MAX_BP = 50.0` — Порог и окно объявлены до замера (см. шапку). Менять их после результата запрещено правилом проекта.
- L45 `WINDOW_D = 14`
- L46 `MIN_DAYS = 3`
- L49 `day_range_bp(path)` — Суточный размах середины по часам одного дня, б.п. Нет — None.
- L79 `scan(summary=None, days=WINDOW_D, now=None, log=None)` — Медианный суточный размах по каждому имени, б.п.
- L133 `flat_names(summary=None, days=WINDOW_D, now=None, ranges=None)` — Имена, которыми торговать нечем: ход мельче порога.
- L144 `is_flat(sym, flat)` — Плоское ли имя. Пустое множество — правило не связывает никого.

## research/common/funding.py · 156 строк

Измерение частоты начислений funding по самому ряду.

- L32 `MS_PER_DAY = 86400000`
- L33 `DEFAULT_PER_DAY = 3.0`
- L36 `accruals_per_day(first_ms, last_ms, records, intervals_hours=No…` — Начислений в сутки по факту: (записей − 1) / длина периода в сутках.
- L55 `annualized_mean_pct(mean_rate, per_day)` — Годовой ориентир порядка величины, а не оценка доходности.
- L60 `annualized_from_sum(sum_rates, span_days)` — Годовая издержка удержания по фактически начисленному за окно.
- L77 `step_hours(timestamps_ms)` — Промежутки между соседними начислениями, в часах.
- L85 `modal_step_hours(timestamps_ms)` — Самый частый промежуток — режим начисления ряда.
- L93 `gap_report(timestamps_ms, window=25, tolerance=1.5)` — Пропуски начислений, найденные без опоры на объявленный интервал.

## research/common/funding_series.py · 188 строк

Ряды funding площадки исполнения: загрузка, накопление, оценка.

- L44 `MIN_FUNDING_SYMBOLS = 50` — Ниже этого числа символов покрытие считается отсутствующим: частичное даёт заниженную издержку, выдавая её за…
- L47 `parse_time_ms(x)` — Метка времени в миллисекундах из того, что лежит в файле.
- L62 `column_indices(header, where='')` — Позиции колонок времени и ставки — **по имени, а не по номеру**.
- L86 `load_funding(directory, universe, symbols, symbol_field='bybit_…` — `{актив: (времена_мс, ставки)}` по каталогу рядов.
- L126 `ms(day)`
- L130 `accrued(funding, asset, t0_ms, t1_ms)` — Сумма ставок, начисленных в `[t0, t1)`; `None` — ряда нет.
- L148 `accrual_count(funding, asset, t0_ms, t1_ms)` — Число начислений в окне. Нужно ловушке §5.6: смена режима.
- L158 `funding_score(funding, names, at, form_days)` — Оценка отбора: минус средняя **суточная** ставка за окно.

## research/common/oi_metrics.py · 96 строк

Разбор набора `metrics` архива Binance — открытый интерес и потоки.

- L35 `S3 = 'https://s3-ap-northeast-1.amazonaws.co…`
- L37 `STEP_MIN = 5`
- L38 `PUBLISH_LAG_MIN = 5`
- L40 `TIME_COL = 'create_time'`
- L41 `OI_COL = 'sum_open_interest'`
- L42 `OI_USD_COL = 'sum_open_interest_value'`
- L43 `TAKER_RATIO_COL = 'sum_taker_long_short_vol_ratio'`
- L46 `metrics_url(symbol, day)` — `metrics` бывает только суточным — месячной выкладки не существует.
- L52 `days_between(start, end)`
- L61 `read_zip_csv(raw)`
- L67 `parse_metrics(raw, columns=(OI_COL,))` — Строки суточного файла: `[(время_сек, знач1, знач2, …), …]`.

## research/common/pyenv.py · 77 строк

Запуск не тем интерпретатором — отказ, который повторяется вечно.

- L27 `MARK = 'ALGOTH_REEXEC'`
- L30 `repo_root(start=None)` — Корень репозитория — по каталогу `research` рядом с `.venv`.
- L43 `venv_python(root=None)`
- L51 `need(*modules)` — Убедиться, что модули доступны; иначе перезапуститься из .venv.

## research/common/universe_filter.py · 88 строк

Не-крипто перпы: единое определение для сборщика и модели.

- L26 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L27 `UNIVERSE_JSON = os.path.join(os.path.dirname(HERE), 'a1…`
- L33 `NON_CRYPTO_NEW = {'AMCUSDT', 'AMGNUSDT', 'BACUSDT', 'BII…` — Листинги после снимка универсума: токенизированные акции, фонды и pre-IPO компании (волна TradFi-перпов лета…
- L59 `reference_non_crypto(universe_path=UNIVERSE_JSON)` — Не-крипто символы Bybit по справочнику универсума (снимок A1).
- L70 `non_crypto_set(universe_path=UNIVERSE_JSON)` — Полный список известных не-крипто символов.
- L75 `is_non_crypto(sym, ref=None)` — Является ли символ перпом не на криптоактив.

## research/common/venue.py · 154 строк

Общие примитивы работы с площадками: HTTP с дисковым кэшем и нормализация тикеров.

- L22 `TIMEOUT = 45`
- L23 `RETRIES = 3`
- L38 `_MULT = '(10000000|1000000|100000|10000|1000)'` — Множители в тикерах: 1000PEPEUSDT, 10000LADYSUSDT, 1000000MOGUSDT. В логарифмическом спреде постоянный множит…
- L39 `MULTIPLIER_PREFIX_RE = re.compile('^' + _MULT + '(?=[A-Z])')`
- L40 `MULTIPLIER_SUFFIX_RE = re.compile('(?<=[A-Z])' + _MULT + '$')`
- L41 `QUOTE_SUFFIXES = ('USDT', 'USDC', 'PERP', 'USD')`
- L44 `_ctx()`
- L52 `SSL_CTX = _ctx()`
- L55 `fetch(url, cache_dir, method='GET', body=None, cache_key=None, …` — HTTP с дисковым кэшем и повторами. Возвращает текст ответа.
- L86 `fetch_binary(url, cache_dir, cache_key=None, user_agent='algoth…` — То же, что `fetch`, но возвращает байты и кэширует их как есть.
- L135 `normalize(symbol)` — Тикер площадки -> (базовый актив, котируемый актив, множитель).

## research/a0_venue_inventory/inventory.py · 336 строк

A0 — инвентаризация площадок.

- L21 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L22 `CACHE = os.path.join(HERE, 'out', 'cache')`
- L23 `OUT = os.path.join(HERE, 'out')`
- L28 `BYBIT_ARCHIVE = 'https://public.bybit.com/trading/'`
- L29 `BINANCE_S3 = 'https://s3-ap-northeast-1.amazonaws.co…`
- L30 `HYPERLIQUID_API = 'https://api.hyperliquid.xyz/info'`
- L32 `WORKERS = 8`
- L35 `fetch(url, method='GET', body=None, cache_key=None)` — HTTP с дисковым кэшем этапа A0. Реализация — `research/common/venue.py`.
- L49 `collect_hyperliquid()`
- L78 `_bybit_symbols()`
- L83 `_bybit_symbol_range(symbol)` — Первый и последний день, за который есть архив тиков.
- L96 `collect_bybit(symbols)`
- L126 `_s3_list(prefix, delimiter='/')` — Постраничный листинг S3-бакета архива Binance.
- L145 `collect_binance()`
- L182 `binance_datasets()` — Какие типы данных вообще лежат в архиве Binance USD-M.
- L194 `build_summary(hl, bybit, binance, bnc_datasets)`
- L249 `load_datasets_from_summary()` — Список наборов данных архива Binance из предыдущего прогона.
- L258 `renormalize_stored()` — Пересчитать производные поля из уже собранных JSON, без сети.
- L293 `write_all(hl, bybit, binance, summary)`
- L304 `main()`

## research/a0_venue_inventory/report.py · 161 строк

Формирует отчёт A0 в markdown из summary.json.

- L10 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L11 `OUT = os.path.join(HERE, 'out')`
- L14 `load(name)`
- L19 `main()`

## research/a1_universe/binance_funding.py · 256 строк

A1 — история ставок funding с Binance.

- L47 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L48 `OUT = os.path.join(HERE, 'out')`
- L49 `RAW = os.path.join(OUT, 'funding_binance')`
- L51 `BASE = 'https://data.binance.vision/data/futur…`
- L52 `WORKERS = 6`
- L53 `TIMEOUT = 120`
- L54 `RETRIES = 3`
- L62 `http_bytes(url)`
- L78 `read_month(blob, checksum)` — Проверить контрольную сумму и разобрать месячный файл.
- L95 `collect_symbol(symbol, months)`
- L112 `months_without_data(rows, months)` — Запрошенные месяцы, по которым в ряду нет ни одной записи.
- L130 `write_symbol(symbol, rows)`
- L144 `summarize(rows)`
- L169 `main()`

## research/a1_universe/binance_klines.py · 402 строк

A1 — загрузка свечей Binance по универсуму на момент времени.

- L51 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L52 `OUT = os.path.join(HERE, 'out')`
- L53 `RAW = os.path.join(OUT, 'klines')`
- L55 `BASE = 'https://data.binance.vision/data/futur…`
- L56 `DAILY = 'https://data.binance.vision/data/futur…`
- L57 `WORKERS = 6`
- L58 `TIMEOUT = 120`
- L59 `RETRIES = 3`
- L61 `INTERVAL_MINUTES = {'1m': 1, '3m': 3, '5m': 5, '15m': 15, …`
- L67 `http_bytes(url)`
- L83 `months_between(first_ym, last_ym)`
- L95 `verify_and_count(blob, checksum)` — Сверить контрольную сумму, посчитать бары и границы ряда.
- L125 `fetch_month(symbol, interval, ym, keep)` — Скачать, проверить, при необходимости сохранить один символо-месяц.
- L164 `read_symbol_timestamps(symbol, interval)` — Уникальные метки времени по символу и число дублей.
- L195 `missing_days(ts, step_ms)` — Даты UTC, внутри которых не хватает баров.
- L212 `daily_files_present(symbol, interval)` — Дни, закрытые суточными файлами, по состоянию каталога.
- L234 `fetch_day(symbol, interval, day, keep)` — Один суточный файл — им закрываются дыры месячного архива.
- L257 `fill_gaps(symbol, interval, keep, ts)` — Закрыть дыры месячного архива суточными файлами.
- L270 `plan(manifest, interval)` — Какие символо-месяцы нужны: от начала истории Binance до смерти на Bybit.
- L290 `main()`

## research/a1_universe/bybit_api.py · 402 строк

A1 — сбор того, что доступно только через API v5 Bybit.

- L56 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L57 `RESEARCH = os.path.dirname(HERE)`
- L58 `OUT = os.path.join(HERE, 'out')`
- L59 `CACHE = os.path.join(OUT, 'cache_api')`
- L60 `FUNDING_DIR = os.path.join(OUT, 'funding')`
- L68 `API = 'https://api.bybit.com'`
- L69 `CATEGORY = 'linear'`
- L70 `FUNDING_LIMIT = 200`
- L71 `WORKERS = 4`
- L72 `PAUSE_S = 0.05`
- L75 `api_get(path, params, cache_key)`
- L86 `collect_instruments()` — Полный справочник линейных контрактов, включая неторгуемые сейчас.
- L107 `_collect_instruments_status(status)`
- L142 `_ms(d)`
- L146 `collect_funding_symbol(symbol, start_day, end_day)` — Вся история funding по символу. Эндпоинт отдаёт назад во времени.
- L181 `write_funding(symbol, rows)`
- L191 `summarize(symbol, rows)`
- L232 `check_credentials()` — Ключ и секрет на месте и различны. Зовётся до сбора, а не после.
- L258 `collect_fees()` — Ставки комиссий по ключу API. Раздел 5.1: из живого API, не по памяти.
- L287 `preflight()` — Проверить доступ до начала сбора и объяснить отказ по-человечески.
- L307 `main()`

## research/a1_universe/bybit_options.py · 356 строк

Инвентарь опционов площадки исполнения — выпуклый инструмент, есть ли он.

- L61 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L62 `RESEARCH = os.path.dirname(HERE)`
- L63 `OUT = os.path.join(HERE, 'out')`
- L67 `CACHE = os.path.join(HERE, '.cache_opts')` — Кэш ответов — СИБЛИНГ out (публикация коммитит всё под `research/*/out`, и файлы кэша уехали бы в git). Ключ…
- L72 `API = 'https://api.bybit.com'`
- L73 `STORE = os.path.join(OUT, 'options_inventory.js…`
- L74 `UNIVERSE = os.path.join(OUT, 'universe.json')`
- L75 `INSTRUMENTS = os.path.join(OUT, 'instruments.json')`
- L76 `MAJORS = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DO…`
- L77 `WORKERS = 3`
- L80 `api_get(path, params, day=None)` — Публичный GET к площадке. Отказ — ДАННЫЕ, а не исключение.
- L103 `list_options(base_coin=None, pages=20)` — Живые опционные контракты (по базовому активу либо все). Список строк.
- L126 `summarize(rows)` — Свод по базовым активам: контрактов и границы экспираций.
- L170 `universe_bases(inst)` — Базовые активы КРИПТО-части нашего универсума (символ → базовый).
- L196 `load_instruments()`
- L205 `alias_set(base)` — Базовый актив и его вариант без множителя лота (`1000PEPE` → `PEPE`).
- L215 `run(smoke=False, log=print)`
- L275 `report(s)`
- L333 `publish(name)`
- L338 `main()`

## research/a1_universe/bybit_risk_limit.py · 217 строк

D0 (спека 14) — таблица maintenance margin площадки исполнения.

- L49 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `RESEARCH = os.path.dirname(HERE)`
- L51 `OUT = os.path.join(HERE, 'out')`
- L55 `CACHE = os.path.join(HERE, '.cache_risk')` — Кэш ответов — СИБЛИНГ out, а не внутри: публикация коммитит всё под `research/*/out`, и полторы тысячи файлов…
- L60 `API = 'https://api.bybit.com'`
- L61 `CATEGORY = 'linear'`
- L62 `WORKERS = 4`
- L63 `PAUSE_S = 0.05`
- L64 `STORE = os.path.join(OUT, 'risk_limits.json')`
- L67 `api_get(path, params, cache_key)`
- L77 `parse_tiers(result)` — Лестница тиров из ответа эндпоинта, отсортированная по нотионалу.
- L100 `load_store()`
- L107 `universe_symbols()`
- L118 `collect(symbols, store)` — Собрать тиры по символам, которых ещё нет в хранилище.
- L161 `_save(store)`
- L168 `report(store, symbols)` — Покрытие и распределение MMR базового тира — числом, не словом.
- L197 `main()`

## research/a1_universe/data_report.py · 904 строк

A1 — отчёт о загруженных данных.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `OUT = os.path.join(HERE, 'out')`
- L29 `load(name)`
- L37 `pct(x, n)`
- L46 `_plural(n, one, few, many)` — «1 день», «44 дня», «580 дней» — отчёт читает человек, а не парсер.
- L55 `_days(n)`
- L59 `_windows(n)`
- L63 `_assets(n)`
- L67 `quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95))`
- L78 `_fee_stats(universe)` — Ставки комиссий по символам универсума, сгруппированные по тарифу.
- L118 `_fee_of_picked(add, universe, fs, best, bp)` — Комиссия не в среднем по универсуму, а у тех, кого отбирает признак.
- L153 `_fees_section(add, universe, fs)`
- L219 `_bybit_section(add, universe)` — Раздел 3: ставки funding и справочник инструментов Bybit.
- L356 `_venue_diff_section(add, fs)` — Раздел 4: расхождение площадок, выровненное по периодам.
- L471 `_persistence_section(add, universe, fs)` — Раздел 5: доживает ли дифференциал funding до сделки.
- L611 `main()`

## research/a1_universe/funding_persistence.py · 587 строк

A1 — персистентность funding во времени: признак отбора или только издержка.

- L69 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L70 `RESEARCH = os.path.dirname(HERE)`
- L71 `OUT = os.path.join(HERE, 'out')`
- L72 `BYBIT_DIR = os.path.join(OUT, 'funding')`
- L73 `BINANCE_DIR = os.path.join(OUT, 'funding_binance')`
- L78 `MS_DAY = 86400000`
- L83 `GRID = [(7, 5), (30, 5), (90, 5), (30, 30), (9…` — Пары «окно формирования — окно удержания», в сутках. Удержание 1–5 дней задано разделом 3.2 спеки 01; 30 и 90…
- L89 `DECAY_GAPS = [0, 5, 30, 90, 365]`
- L91 `MIN_CROSS_SECTION = 50`
- L92 `STEP_SAMPLE = 64`
- L93 `DECILE = 0.1`
- L94 `VENUE_WINDOW_DAYS = 90`
- L99 `read_series(path, rate_col)` — (отметки времени, ставки, префиксные суммы ставок) — три массива.
- L130 `window_rate(series, t0, t1)` — Годовая ставка по фактически начисленному в окне [t0, t1).
- L170 `_count_inversions(seq)` — Число инверсий сортировкой слиянием. Ties считаются согласованными.
- L198 `_tied_pairs(sorted_keys)` — Число пар с одинаковым ключом в отсортированной последовательности.
- L211 `pair_sign_agreement(f, g)` — Доля пар (i, j), у которых знак `f_i − f_j` совпал со знаком `g_i − g_j`.
- L248 `_ranks(vals)`
- L263 `spearman(f, g)`
- L275 `decile_spread(f, g)` — Спред «шорт верхний дециль / лонг нижний» — обещанный и полученный.
- L290 `quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95))`
- L297 `median(vals)`
- L304 `run_grid(series, t_start, t_end, form_days, hold_days, gap_days…` — Прогон одной конфигурации «формирование → удержание» по всей истории.
- L414 `venue_drift(by_series, bn_series, t_start, t_end, win_days)` — Держится ли знак расхождения Bybit − Binance от окна к окну.
- L468 `load_all(universe, key, directory, rate_col)`
- L483 `main()`

## research/a1_universe/funding_refresh.py · 183 строк

Догон рядов funding площадки исполнения до сегодняшнего дня.

- L36 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L37 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L41 `OUT = B.OUT`
- L42 `OVERLAP_D = 1`
- L45 `read_rows(path)`
- L55 `last_day(rows)`
- L61 `merge(old, new)` — Объединение по ВРЕМЕНИ: новая точка побеждает старую с той же меткой.
- L69 `refresh_symbol(sym, today, fetch=None, read=None)` — Хвост одного символа. Возвращает (было, добавлено, край, ошибка).
- L93 `write_tmp(rows, tmp)`
- L101 `symbols(assets)`
- L109 `run(syms, today, workers=B.WORKERS, log=print, fetch=None)`
- L133 `report(s)`
- L148 `publish(name)`
- L154 `main(argv=None)`

## research/a1_universe/report.py · 295 строк

Формирует отчёт A1 по универсуму в markdown из universe.json.

- L10 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L11 `OUT = os.path.join(HERE, 'out')`
- L26 `PROBE_MONTHS = (1, 7)` — Точки, в которых показывается универсум. Полугодовой шаг выбран под протокол walk-forward раздела 6: окно отб…
- L27 `MIN_HISTORY = 365`
- L30 `_decile_share(assets)` — Доля попаданий в дециль признака funding, приходящаяся на эти активы.
- L51 `main()`

## research/a1_universe/universe.py · 392 строк

A1 — универсум площадки исполнения на момент времени.

- L32 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L33 `RESEARCH = os.path.dirname(HERE)`
- L34 `OUT = os.path.join(HERE, 'out')`
- L35 `CACHE = os.path.join(OUT, 'cache')`
- L36 `A0_OUT = os.path.join(RESEARCH, 'a0_venue_invent…`
- L41 `BYBIT_ARCHIVE = 'https://public.bybit.com/trading/'`
- L42 `WORKERS = 8`
- L47 `DELIST_GAP_DAYS = 7` — Инструмент считаем прекратившим торговаться, если последний день архива старше этого зазора от даты его среза…
- L59 `SETTLEMENT_MAX_LEN_DAYS = 1` — Расчётный день при делистинге. У девяти инструментов последний файл архива отстоит от конца реальной торговли…
- L60 `SETTLEMENT_MIN_GAP_DAYS = 7`
- L82 `NON_CRYPTO_TAKER_BP = 2.75` — Перпы не на криптоактивы. Bybit торгует акции (AAPL, NVDA, TSLA), биржевые фонды (SPY, QQQ, SOXX), фонды с пл…
- L83 `KEEP_AS_CRYPTO = {'PURR'}`
- L87 `DATE_RE = re.compile('(\\d{4}-\\d{2}-\\d{2})\\.cs…`
- L90 `fetch(url, cache_key=None)`
- L94 `trading_days(symbol)` — Множество дней, за которые в архиве Bybit есть сделки по символу.
- L103 `to_intervals(days)` — Отсортированные даты -> непрерывные интервалы [(начало, конец), ...].
- L119 `split_settlement(intervals)` — Отделить расчётные дни делистинга от интервалов реальной торговли.
- L139 `collect(symbols)` — Собрать интервалы торговли по каждому символу.
- L158 `build(days_by_symbol, a0_bybit, a0_binance)` — Свести интервалы и данные A0 в манифест универсума.
- L226 `_parse_intervals(rec)`
- L233 `tradable_on(rec, day)` — Торговался ли инструмент на площадке исполнения в этот день.
- L238 `history_days_by(rec, day)` — Сколько дней с фактическими сделками на площадке исполнения к этому дню.
- L249 `binance_history_days_by(rec, day)` — Длина ряда Binance к этому дню. Гранулярность архива — месяц.
- L257 `estimation_history_days_by(rec, day)` — История, доступная для оценки β, μ, σ и периода полураспада.
- L268 `classify_asset_class(manifest, fees)` — Проставить `asset_class` по ставке комиссии. Сеть не нужна.
- L292 `universe_at(manifest, day, min_history_days=0, require_binance=…` — Универсум на момент времени — реализация требования раздела 2.1.1.
- L314 `_load_fees()`
- L322 `reclassify_stored()` — Разметить классы активов в уже собранном манифесте, без сети.
- L354 `main()`

## research/a1_universe/venue_funding_diff.py · 182 строк

A1 — расхождение ставок funding между площадками, выровненное по периодам.

- L49 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `RESEARCH = os.path.dirname(HERE)`
- L51 `OUT = os.path.join(HERE, 'out')`
- L52 `BYBIT_DIR = os.path.join(OUT, 'funding')`
- L53 `BINANCE_DIR = os.path.join(OUT, 'funding_binance')`
- L58 `MIN_SPAN_DAYS = 90`
- L59 `MIN_ACCRUALS = 30`
- L62 `read_series(path, rate_col)` — (отметка времени UTC, ставка) из gzip-CSV с заголовком.
- L74 `window_stats(series, lo, hi)` — Сумма ставок и число начислений строго внутри окна [lo, hi].
- L80 `quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95))`
- L87 `main()`

## research/a2_storage/build.py · 327 строк

A2 — хранилище: месячные архивы Binance в колоночный формат.

- L51 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L52 `RESEARCH = os.path.dirname(HERE)`
- L53 `A1_OUT = os.path.join(RESEARCH, 'a1_universe', '…`
- L54 `OUT = os.path.join(HERE, 'out')`
- L55 `PARQUET = os.path.join(OUT, 'parquet')`
- L59 `COLUMNS = ['open_time', 'open', 'high', 'low', 'c…` — Колонки месячного файла Binance. Заголовка в файлах до 2025 года нет, в поздних есть — читается и то и другое.
- L69 `KEEP = ['open_time', 'open', 'high', 'low', 'c…` — Хранится не всё. `close_time` выводится из `open_time` и шага, `ignore` всегда ноль. `quote_volume` сверх схе…
- L72 `SCHEMA = pa.schema([('symbol', pa.string()), ('o…`
- L85 `READ_OPTS = pacsv.ReadOptions(column_names=COLUMNS)`
- L86 `CONVERT_OPTS = pacsv.ConvertOptions(column_types={c: p…`
- L90 `PARSE_OPTS = pacsv.ParseOptions(delimiter=',')`
- L92 `MONTH_RE = re.compile('-(\\d{4}-\\d{2})(?:-\\d{2})…`
- L95 `files_by_month(symbol_dir, symbol, interval)` — Файлы символа, сгруппированные по месяцу. Суточные идут туда же.
- L105 `read_zip(path)` — Одна таблица из zip-архива. Заголовок, если он есть, отбрасывается.
- L116 `symbol_month_table(symbol, paths)` — Все файлы символо-месяца в одну таблицу, без дублей, по времени.
- L142 `read_manifest(path)` — Манифест партиции: состав и её собственные числа.
- L160 `write_manifest(path, symbols, rows, dups, files=None)`
- L166 `scan_store(dest)` — Сводка по тому, что лежит на диске, а не по тому, что сделал прогон.
- L198 `main()`

## research/a2_storage/hygiene.py · 429 строк

A2 — отчёт о гигиене данных.

- L37 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L38 `RESEARCH = os.path.dirname(HERE)`
- L39 `OUT = os.path.join(HERE, 'out')`
- L40 `PARQUET = os.path.join(OUT, 'parquet')`
- L41 `A1_OUT = os.path.join(RESEARCH, 'a1_universe', '…`
- L43 `STEP_MINUTES = {'1m': 1, '5m': 5, '15m': 15, '1h': 60}`
- L49 `OUTLIER_MAD = 10.0` — Выброс — движение, во столько раз превышающее медианное абсолютное отклонение доходностей самого символа. Пор…
- L51 `QUARANTINE_DAYS = 30`
- L52 `ENDLIFE_DAYS = 30`
- L53 `PAIR_SYMBOLS = 45`
- L55 `PAIR_WINDOW_DAYS = 365` — (даёт ~990 пар)
- L60 `MEMORY_SHARE = 0.55` — Доля оперативной памяти, отдаваемая движку. Остаток нужен самому Python: замер согласованности ног держит мас…
- L61 `TMP = os.path.join(OUT, '.tmp')`
- L64 `memory_limit_mb()`
- L69 `connect(interval)`
- L92 `per_symbol(con, step_min)` — Покрытие, пропуски, мёртвые бары и выбросы по каждому символу.
- L148 `life_profile(con, side, days)` — Во сколько раз движение у края жизни отличается от обычного.
- L210 `frozen_tails(con, min_days=7)` — Хвост ряда, где бары публикуются, но сделок нет ни одной.
- L254 `pair_alignment(con, universe, n_symbols, window_days=PAIR_WINDO…` — Согласованность двух ног по времени на пересечении их сроков жизни.
- L343 `quantiles(vals, qs=(0.05, 0.25, 0.5, 0.75, 0.95))`
- L350 `main()`

## research/a2_storage/refresh.py · 294 строк

Ежедневная докачка хранилища A2 свежими барами Binance.

- L44 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L45 `RESEARCH = os.path.dirname(HERE)`
- L46 `OUT = os.path.join(HERE, 'out')`
- L47 `PARQUET = os.path.join(OUT, 'parquet')`
- L48 `A1 = os.path.join(RESEARCH, 'a1_universe')`
- L55 `WORKERS = 16`
- L57 `MAX_DAYS = 120` — здесь суточные по десяткам килобайт
- L60 `EDGE_MONTHS = 3`
- L63 `storage_edge(interval='1m', months=EDGE_MONTHS)` — Конец НЕПРЕРЫВНОГО покрытия хранилища. `None` — хранилища нет.
- L105 `limit_days(days, n)` — Пилот берёт дни ОТ КРАЯ, а не с конца.
- L115 `live_symbols(universe_path=None, on_day=None)` — Символы Binance, живые на площадке исполнения в этот день.
- L138 `days_to_fetch(edge, today=None, max_days=MAX_DAYS)` — Дни от края хранилища до вчера включительно.
- L156 `fetch_all(symbols, days, interval, workers=WORKERS, log=print)` — Скачать суточные файлы. Возвращает (скачано, отсутствует).
- L181 `rebuild(months, interval, log=print)` — Пересобрать партиции месяцев ТЕМ ЖЕ `build.py`.
- L202 `report(art, path)`
- L231 `main()`

## research/a2_storage/report.py · 295 строк

Формирует отчёт A2 о гигиене данных в markdown из hygiene_*.json.

- L8 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L9 `OUT = os.path.join(HERE, 'out')`
- L12 `a1_duplicates(interval)` — Сколько дублей насчитала инвентаризация A1 по сырым архивам.
- L23 `q(vals, p)`
- L28 `main()`

## research/a4_cointegration/coint.py · 129 строк

A4 — тест на коинтеграцию и поправка на множественность.

- L38 `MIN_OBS = 200` — Направление регрессии фиксируется, иначе β и p-значение зависели бы от того, в каком порядке пара пришла из A…
- L46 `LAG_CAP = 24` — Потолок числа лагов ADF. Правило Шверта, которым statsmodels выбирает максимум по умолчанию, на 130 тысячах м…
- L49 `log_prices(a, b)`
- L53 `ols_beta(la, lb)` — β и свободный член регрессии ln P_A на ln P_B.
- L71 `half_life(spread)` — Полураспад по модели Орнштейна–Уленбека, спека 01 §2.4.
- L87 `test_pair(pa, pb)` — Энгл–Грейнджер по паре цен. Возвращает словарь или None.
- L109 `benjamini_hochberg(pvalues, alpha=0.1)` — Индексы отвергнутых гипотез при контроле FDR на уровне alpha.

## research/a4_cointegration/compare.py · 150 строк

A4 — сравнение настоящего прогона с нулевой моделью §7.

- L30 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L31 `OUT = os.path.join(HERE, 'out')`
- L37 `subset(rows, since=None, until=None)`
- L44 `rates(rows)` — Доли, не зависящие от того, сколько было тестов.
- L58 `block(rows, where=None)`
- L64 `show(name, real, null)`
- L92 `main()`

## research/a4_cointegration/report.py · 376 строк

A4 — отчёт по этапу.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `OUT = os.path.join(HERE, 'out')`
- L25 `read(name)`
- L33 `pct(x)`
- L37 `num(x, d=1)`
- L41 `main()`

## research/a4_cointegration/series.py · 169 строк

A4 — чтение рядов из хранилища A2 с приведением к нужному шагу.

- L31 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L32 `RESEARCH = os.path.dirname(HERE)`
- L33 `PARQUET = os.path.join(RESEARCH, 'a2_storage', 'o…`
- L34 `OUT = os.path.join(HERE, 'out')`
- L36 `MEMORY_SHARE = 0.55`
- L39 `STEPS = {'1m': None, '5m': "time_bucket(INTERVA…` — Шаг бара -> выражение усечения времени в DuckDB.
- L49 `memory_limit_mb()`
- L54 `connect()`
- L64 `partition_files(interval, t0, t1)` — Партиции, пересекающиеся с окном. Читать всё хранилище незачем.
- L77 `load(con, symbols, t0, t1, step='1h', interval='1m')` — Цены закрытия по шагу `step` за `[t0, t1)`.
- L134 `STEP_MS = {'1m': 60000, '5m': 300000, '15m': 9000…`
- L138 `resample(t, c, step)` — Приведение уже загруженного ряда 1m к более крупному шагу.
- L158 `align(a, b)` — Общие моменты времени двух рядов.

## research/a4_cointegration/sweep.py · 219 строк

A4 — выбор шага бара для теста на коинтеграцию, измерением.

- L35 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L36 `RESEARCH = os.path.dirname(HERE)`
- L37 `OUT = os.path.join(HERE, 'out')`
- L45 `STEPS = ('1d', '4h', '1h', '15m', '1m')`
- L46 `BARS_PER_DAY = {'1d': 1, '4h': 6, '1h': 24, '15m': 96,…`
- L47 `FORM_DAYS = 90`
- L48 `ALPHA = 0.1`
- L51 `window(at)`
- L58 `q(vals, p)`
- L63 `main()`

## research/a4_cointegration/walkforward.py · 469 строк

A4 — прогон теста на коинтеграцию по сетке окон walk-forward.

- L63 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L64 `RESEARCH = os.path.dirname(HERE)`
- L65 `OUT = os.path.join(HERE, 'out')`
- L66 `WINDOWS = os.path.join(OUT, 'windows')`
- L76 `STEP = '1h'`
- L77 `FORM_DAYS = 90`
- L78 `EMBARGO_DAYS = 7`
- L79 `TRADE_DAYS = 30`
- L80 `ALPHA = 0.1`
- L88 `MAX_HALF_LIFE_DAYS = 5.0` — §3.4 в части, не зависящей от издержек. Горизонт удержания 1–5 дней (спека 01 §11). Полураспад — время, за ко…
- L94 `BARS_PER_DAY = {'1m': 1440, '15m': 96, '1h': 24, '4h':…`
- L95 `GRID_START = '2022-07-01'`
- L96 `GRID_END = '2026-06-01'`
- L99 `window_dates(start, end, step_days)`
- L107 `form_window(at)`
- L112 `shuffle_labels(groups, of_group, meta, seed)` — Нулевая модель: метки групп перемешиваются между активами.
- L150 `run_window(con, at, groups, of_group, meta, liq, universe, inte…` — Один срез: кандидаты A3 → Энгл–Грейнджер → BH → полураспад.
- L223 `windows_dir(null_seed=None)` — Результаты нулевой модели живут отдельно от настоящих.
- L234 `load_windows(where=None)`
- L246 `overlap(a, b)` — Доля пар окна `a`, дошедших до окна `b`, от всего набора `a`.
- L260 `survival(sel_a, sel_b, tested_b)` — Выживание среди пар, которые во втором окне вообще проверялись.
- L285 `summarize(rows, where=None)`
- L372 `main()`

## research/asset_groups/check_coverage.py · 180 строк

Проверка группировки активов: покрытие, дубликаты, опечатки, размер групп.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `GROUPS = os.path.join(HERE, 'groups.yaml')`
- L27 `UNIVERSE = os.path.join(HERE, '..', 'a1_universe',…`
- L29 `MIN_HISTORY = 365`
- L30 `BIG_GROUP_PAIRS = 200`
- L33 `parse_groups(path)` — Читает плоский YAML вида `ключ:` + список ` - ЗНАЧЕНИЕ`.
- L59 `eligible()` — Активы, способные попасть хотя бы в одно окно walk-forward.
- L72 `main()`

## research/asset_groups/liquidity.py · 130 строк

A3 — подневная ликвидность каждого актива по хранилищу A2.

- L43 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L44 `RESEARCH = os.path.dirname(HERE)`
- L45 `OUT = os.path.join(HERE, 'out')`
- L46 `PARQUET = os.path.join(RESEARCH, 'a2_storage', 'o…`
- L48 `MEMORY_SHARE = 0.55`
- L51 `memory_limit_mb()`
- L56 `connect()`
- L68 `partitions(interval)`
- L76 `scan(con, path)` — Подневный агрегат одной партиции.
- L97 `main()`

## research/asset_groups/pairs.py · 210 строк

A3 — кандидаты в пары на момент окна.

- L50 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L51 `OUT = os.path.join(HERE, 'out')`
- L52 `UNIVERSE = os.path.join(HERE, '..', 'a1_universe',…`
- L57 `FORM_DAYS = 90`
- L58 `MIN_DAYS_IN_WINDOW = 30`
- L59 `MIN_SHARE_TRADED = 0.9`
- L60 `MAX_TURNOVER_RATIO = 10.0`
- L62 `META_SECTIONS = ('duplicate_listings', 'mechanically_li…`
- L66 `load_groups()`
- L82 `load_liquidity(interval)` — Подневный ряд ликвидности, ключ — базовый актив, не символ.
- L102 `state_at(liq, universe, t)` — Ликвидность каждого актива на дату `t`, только по прошлому.
- L132 `candidates(groups, of_group, meta, st, max_ratio=MAX_TURNOVER_R…`
- L157 `grid(start, end, step_days)`
- L165 `main()`

## research/asset_groups/report.py · 180 строк

Формирует отчёт A3 в markdown из groups.yaml и candidates_*.json.

- L15 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L16 `OUT = os.path.join(HERE, 'out')`
- L22 `SHOW_WINDOWS = ('2022-12-28', '2023-06-26', '2024-06-2…`
- L26 `main()`

## research/b1_book/absorb.py · 365 строк

Поглощение в стакане: крупный стоит, его выедают, он подставляет снова.

- L113 `QBIG = 0.98`
- L114 `BIG = 2.0`
- L115 `HOLD = 10`
- L116 `EAT = 1.0`
- L117 `REFILL = 0.5`
- L118 `MIN_LEVELS = 5`
- L119 `CAL = 900`
- L123 `MIN_CAL = 300` — Квантиль требует больше выборки, чем медиана: при 120 наблюдениях 98-я процентиль есть третье по величине зна…
- L126 `quantile(vals, q)` — Значение, которого не превышает доля `q` выборки.
- L140 `class Side` — Отслеживание одного кандидата на одной стороне.
  - L143 `Side.__init__(self)`
  - L152 `Side.reset(self, price, size, now)`
  - L159 `Side.state(self)`
- L169 `biggest(levels, best, reach, long)` — Самый крупный по нотионалу уровень В ДОСЯГАЕМОСТИ цены.
- L212 `class Tracker` — Поглощение по обеим сторонам одного инструмента.
  - L215 `Tracker.__init__(self, symbol)`
  - L234 `Tracker.reach(self, long)` — Докуда цена доходила за окно удержания, или `None`.
  - L241 `Tracker.chain(self)` — Сводка «докуда дошли» для страницы наблюдения.
  - L249 `Tracker.step(self, bids, asks, sec, now)` — Шаг на новом снимке книги.
  - L311 `Tracker._verdict(self, long, price, notional, med, n, usual, gate, seen)`
  - L359 `Tracker.signal(self)` — Сторона, на которой поглощение подтверждено, или `None`.

## research/b1_book/book.py · 216 строк

Стакан: состояние, применение обновлений, снимок.

- L47 `BANDS = (0.0005, 0.001, 0.0025, 0.005)`
- L48 `LADDER = 10`
- L55 `STORE_LADDER = 0` — В ФАЙЛ пишется книга целиком, а не лесенка для глаз. Причина найдена вопросом владельца «можно ли прогнать пр…
- L58 `class Book` — Одна сторона рынка по одному инструменту.
  - L66 `Book.__init__(self, symbol)`
  - L78 `Book.clear(self)`
  - L84 `Book.ready(self)`
  - L88 `Book.apply(self, msg)` — Применить сообщение темы `orderbook`.
  - L98 `Book._apply(self, msg)`
  - L128 `Book._side(book, rows)`
  - L142 `Book.best(self)`
  - L148 `Book.sample_view(self, ladder=LADDER, bands=BANDS)` — То же, что `sample`, но БЕЗ обнуления счётчика обновлений.
  - L160 `Book.sample(self, ladder=LADDER, bands=BANDS)` — Снимок для записи: лучшие, лесенка и объём в полосах.
  - L169 `Book._sample(self, ladder=LADDER, bands=BANDS)`
- L202 `parse_trades(msg)` — Сделки темы `publicTrade` в компактный вид.

## research/b1_book/collect.py · 7265 строк

Сбор стакана и ленты площадки исполнения живьём.

- L68 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L73 `SHADOW_STATUS = os.path.join(os.path.dirname(os.path.di…` — Файлы тени ядра: статус пишет `bot run`, маркер выключения — `tools/run_bot.sh --off` (решение владельца 2026…
- L75 `SHADOW_OFF = os.path.join(os.path.dirname(os.path.di…`
- L77 `OUT = os.path.join(HERE, 'out')`
- L81 `DCA_TRADES = 200` — Сколько сделок DCA-книги уезжает на страницу. Не «сколько их есть»: счёт закрытых позиций считает свод, а уре…
- L98 `WS_URL = 'wss://stream.bybit.com/v5/public/linea…`
- L117 `DEPTH = 50` — Глубина темы orderbook. Пятьдесят уровней — это НЕ проценты, а полсотни цен подряд, и у плотных инструментов…
- L118 `DEEP_DEPTH = 200`
- L119 `DEEP = ('BTCUSDT', 'ETHUSDT')`
- L122 `DEPTH_LADDER = (500, 200, 50)` — Лестница отступления: площадка может не принять глубину, и тогда берём мельче, а не остаёмся без стакана вовс…
- L123 `PING_SEC = 20`
- L124 `SAMPLE_SEC = 1`
- L129 `SHARD_SYMBOLS = 40` — Символов на одно соединение. Полный список площадки — это больше тысячи тем, и одно соединение их не унесёт:…
- L130 `REST_HOST = 'https://api.bybit.com'`
- L131 `UNIVERSE_JSON = os.path.join(os.path.dirname(HERE), 'a1…`
- L135 `RECOUNT_HOURS = 24` — Глубина автоматического пересчёта. Живые сделки свежее него дописываются как есть — они уже под нынешними пра…
- L136 `STATUS_SEC = 5`
- L147 `SYMBOLS_DEFAULT = 'all'` — Состав сбора живёт ЗДЕСЬ, а не в строке запуска. Пока он был только в консоли, перезапуск командой из README…
- L148 `SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPU…`
- L156 `RAW = ('ARBUSDT',)` — Сырой поток изменений книги тяжёл, поэтому пишется по одной монете: по нему меряется восполнение уровня внутр…
- L159 `_median(xs)` — Медиана списка. Пустой список сюда не приходит — вызывающий обязан проверить: медиана пустоты есть ноль ровно…
- L168 `minute_bars(rows)` — Сделки -> минутные свечи `[t, o, h, l, c, объём]`.
- L193 `signals_version()` — Текущая версия правил — одним местом, чтобы не разъехалась.
- L198 `METRICS_POLL_SEC = 300`
- L201 `metrics_rows(tickers, have)` — Разбор ответа tickers: funding, интерес, базис по каждому символу.
- L229 `WRITE_KINDS = ('book', 'trades', 'metrics', 'liq', 's…` — Виды рядов, у каждого свой файл на символ. Список — источник числа дескрипторов; при добавлении вида запрос о…
- L232 `nofile_want(n_syms)` — Сколько дескрипторов нужно писателю при n символах.
- L247 `raise_nofile(log, want)` — Поднять лимит открытых файлов под полный список символов.
- L269 `fetch_instruments(host=REST_HOST)` — Справочник линейных контрактов площадки, все страницы.
- L287 `usdt_perps(instruments)` — Из справочника — торгуемые линейные USDT-перпы.
- L295 `non_crypto_bybit(universe_path=UNIVERSE_JSON)` — Не-крипто символы Bybit: справочник плюс курируемый список.
- L309 `recent_pick_symbols(hours=6, s8_root=None)` — Символы из выборов модели за последние часы.
- L347 `HOUR = 3600.0`
- L348 `PHASE_TOL = 120.0`
- L351 `disk_rate(samples, now, total)` — Скорость роста занятого места — байт в час, или `None`.
- L384 `disk_symbols(root)` — Символы, по которым на диске уже лежат ряды книги.
- L394 `resolve_symbols(arg, log, root=OUT)` — `--symbols all` — всё, что торгуется, минус не-крипто.
- L426 `shard_split(symbols, size=SHARD_SYMBOLS)` — Разбивка списка на шарды соединений, устойчивая по порядку.
- L432 `GROUPS_YAML = os.path.join(os.path.dirname(HERE), 'as…`
- L436 `parse_groups_yaml(path=GROUPS_YAML)` — Разметка A3 `группа: [активы]` — крошечный разбор под наш формат.
- L462 `symbol_groups(symbols, groups_path=GROUPS_YAML, universe_path=U…` — Символы сбора по группам A3: [{id, symbols}, …] + «прочие».
- L493 `class LogBuf` — Журнал для страницы: кольцо строк плюс сквозной номер.
  - L501 `LogBuf.__init__(self, keep=60)`
  - L505 `LogBuf.add(self, line)`
  - L509 `LogBuf.since(self, k)` — Вернуть `(всего строк, новые для того, у кого есть k)`.
- L517 `class Shard` — Одно соединение с площадкой: свои темы и свой цикл переподключения.
  - L526 `Shard.__init__(self, idx, symbols, coll)`
  - L537 `Shard.topics(self)`
  - L548 `Shard.send_sub(self, ws, topics)` — Подписка по одной теме, с именем темы в `req_id`: одним запросом площадка отвергает ВСЁ из-за одной негодной…
  - L559 `Shard.on_open(self, ws)`
  - L565 `Shard.on_op(self, ws, msg)` — Служебный ответ. Отклонённая подписка неотличима от тишины рынка, молчать о ней нельзя.
  - L578 `Shard.downgrade(self, ws, topic)` — Стакан не принят на этой глубине — пробуем мельче: мельче хуже, но это данные, а отказ — их отсутствие.
  - L597 `Shard.on_message(self, ws, raw)`
  - L666 `Shard.run(self)`
- L697 `class Collector`
  - L698 `Collector.__init__(self, symbols, raw_symbols, root, log, deep=DEEP, pape…`
  - L787 `Collector.n_msg(self)` — --- агрегаты по шардам -------------------------------------------- Сеть живёт в шардах; здесь только суммы д…
  - L791 `Collector.n_trades(self)`
  - L795 `Collector.n_resets(self)`
  - L799 `Collector.last_msg(self)`
  - L802 `Collector.topics_count(self)`
  - L805 `Collector.live_count(self)`
  - L808 `Collector.shard_state(self)`
  - L818 `Collector.sampler(self)` — Снимок стакана раз в секунду по всем символам.
  - L890 `Collector.health(self)` — Здоровье сбора — ОДНО определение на страницу и на файл.
  - L921 `Collector.warm_mid(self, sym)` — Дочитать середину с диска — по одному символу и по запросу.
  - L972 `Collector.snapshot(self, sym=None, since=0.0, logn=None)` — Состояние для страницы наблюдения — прямо из памяти.
  - L1039 `Collector.candles_files(self, sym, hours=12, end=None)` — Минутные свечи из записей — история глубже памяти сборщика.
  - L1100 `Collector.rec_path(self)`
  - L1103 `Collector.load_recount(self)` — Поднять сохранённый пересчёт. Отказ не вправе ронять сбор.
  - L1113 `Collector.save_recount(self)` — Записать пересчёт целиком и атомарно.
  - L1129 `Collector.recount(self, hours=24, start=True, sym=None)` — Все сделки под ТЕКУЩИМИ правилами — единственный вид.
  - L1198 `Collector.merge_live(self, rows, at)` — Пересчитанные сделки плюс живые, сделанные ПОСЛЕ счёта.
  - L1221 `Collector._recount_watch(self)` — Сам пересчитывает, когда это нужно, и не чаще.
  - L1258 `Collector._recount_job(self, hours)`
  - L1313 `Collector.jobs_poke(self)` — Немедленно посмотреть очередь заданий (`jobs/`).
  - L1347 `Collector.bot_status(self)` — Статус исполнительного ядра (Rust-тень) — из его файла.
  - L1380 `Collector.journal_marker(text)` — Разобрать маркер журнала тени: (каталог книги, версия кассы).
  - L1398 `Collector.bot_full(self)` — Полные данные страницы ядра: статус, журнал, переоценка.
  - L1546 `Collector._median(a)` — Медиана с честной серединой на чётном числе: sorted[n//2] на двух заполнениях выдавал верхнее из двух за меди…
  - L1558 `Collector._model_round_bp()` — Модельный круг издержек — у самого ядра расчёта, не числом здесь: две записи одной константы однажды разошлис…
  - L1570 `Collector.live_exec(self)` — Живые сделки исполнителя ПРОТИВ бумажного сигнала книги.
  - L1850 `Collector.sit_source(rr_min, traded_gate)` — Ситуационная книга на странице ОДНА, а записей две: торгуемая (свой гейт по отношению, 6 мест, её ведёт тень…
  - L1855 `Collector.model_state(self, rr_min=None)` — Состояние модели S8 для страницы: манифест, мысли, живой IC.
  - L1937 `Collector.live_overlay(self, mdir, tr, reviews)` — Живые события сборщика поверх истории выборов и разбора.
  - L2021 `Collector._book_view(self, mdir, mman, rr_min=None, lite=False)` — Сделки, деньги и сводки книги — ОДНИМ кодом на обе дороги.
  - L2121 `Collector.slim_pick(pk)` — Строка выбора без лесенок стакана — то, что читает обзор.
  - L2137 `Collector.slim_review(rv)` — Строка разбора без лесенок — обзор берёт из неё «last: got».
  - L2146 `Collector._model_dir_state(self, mdir, rr_min=None)`
  - L2228 `Collector.model_trades(self, page=0, per=100, arm=None, state=None, sym=N…` — ВСЯ история сделок модели, страницами, со сводкой по всему.
  - L2429 `Collector.ic_summary(rows)` — Живой IC — МЕДИАНА по накопленным сечениям, а не последний час.
  - L2461 `Collector.hour_rows(self, pairs)` — Строки почасовых сводок с кэшом: цена, максимум и минимум часа.
  - L2496 `Collector.model_league(self)` — Лига: что ведёт себя лучше — руки, книги, ситуации, стороны.
  - L2548 `Collector.book_dir_of(self, hz)` — Ключ книги → (каталог, причина отказа).
  - L2573 `Collector.book_rec(self, hz)` — Запись книги по ключу — (запись или None, причина отказа).
  - L2601 `Collector.book_hold(mman, default_h)` — Срок сборки сделок книги; None — у книги нет таймера.
  - L2628 `Collector.arms_twins(trades)` — Тождественны ли руки книги — проверка ЧИСЛОМ, не словом.
  - L3081 `Collector.closed_rows(self, books=None)` — Закрытые сделки всех торгуемых книг — с деньгами.
  - L3202 `Collector._book_pairs(self, rows)` — Парное сравнение книг по ОБЩИМ часам, с интервалом.
  - L3255 `Collector._league_from(self, rows, errors, scanned, now)` — Агрегаты лиги из готовых строк — арифметика без чтения.
  - L3390 `Collector._spearman(xs, ys)` — Ранговая связь — одна реализация на весь сборщик.
  - L3413 `Collector._dca_take_frac(rules_mod, row, ruler=None)` — Доля цели у записи позиции. None — правило по ней неизвестно.
  - L3433 `Collector._dca_adds(fills, notional)` — Доливы позиции для графика: деньги и контракты, а не доля.
  - L3461 `Collector.dca_trades(self, sym, book)` — Позиции DCA-книги по одной монете — В ФОРМЕ, ЖДАННОЙ ГРАФИКОМ.
  - L3588 `Collector.dca_marks(self, dep=None, ruler=None)` — Живая переоценка открытых позиций DCA-книги — частый опрос.
  - L3668 `Collector.dca_paper(self, dep=None, ruler=None, full=None)` — Бумажные DCA-книги: свод из артефакта, сделки из журнала.
  - L3863 `Collector.paper_book(self, at=None)` — Бумажная месячная книга: свод из артефакта, транши из журнала.
  - L3950 `Collector.learning(self)` — Умнеет ли модель и переходит ли это в деньги — по дням.
  - L4048 `Collector.book_days(self, hz)` — Дневная статистика ОДНОЙ книги — по просьбе владельца.
  - L4165 `Collector._day_cell(rows)` — Числа одной клетки «день × рука». Одно определение на день, на итог и на обе руки: три реализации одного счёт…
  - L4197 `Collector.market_vol(self)` — Волатильность рынка по часам — из наших же почасовых сводок.
  - L4290 `Collector.vol_vs_models(self)` — Влияет ли волатильность рынка на результат книг.
  - L4445 `Collector.model_glossary(self)` — Справочник: какие ситуации модель вообще способна читать.
  - L4550 `Collector.model_tournament(self)` — Полный лист турнира политик: все 72 ветки и селектор.
  - L4624 `Collector._run_row(r, now)` — Строка прогона для показа: заметка урезается, не выбрасывается.
  - L4641 `Collector._produced(root, rel, now)` — Файл, который роль обязана была оставить.
  - L4663 `Collector.owner_asks(self)` — Чего система ждёт ОТ ВЛАДЕЛЬЦА, и чем это подтверждено.
  - L4705 `Collector.agents_state(self)` — Автономная система: конвейер, границы и что уже построено.
  - L4893 `Collector._cand_live(self, cid)` — Живая книга кандидата: закрытые сделки и деньги по рукам.
  - L4934 `Collector.factory_built(self)` — Что автономная система объявила: механика в корне, книги ветками.
  - L5110 `Collector._cand_decisions(self, cid, rec)` — Множество РЕШЕНИЙ живой книги кандидата.
  - L5131 `Collector.factory_strategy(self, cid)` — Полная карточка ОДНОЙ стратегии автономной системы.
  - L5271 `Collector.model_tree(self)` — Дерево моделей: две руки и их книги, с логикой каждой ветки.
  - L5451 `Collector.entry_px(self, picks)` — Цены входа для выборов, которые их не несут.
  - L5468 `Collector.paths(self, trades, hold_h=None)` — Просадка по каждой сделке — из тех же почасовых сводок.
  - L5489 `Collector.dd_money(trades)` — Просадку в деньги и в доли депозита — ПОСЛЕ расчёта счёта.
  - L5500 `Collector.marks(self, trades)` — Текущая середина по символам открытых сделок.
  - L5518 `Collector.model_marks(self, hz=None)` — Только переоценка открытых сделок — для частого опроса.
  - L5575 `Collector.trade_by_id(self, tid)` — Сделка по короткому id — поиск по всем книгам разом.
  - L5649 `Collector._jsonl(path)`
  - L5706 `Collector._jsonl_trim()`
  - L5716 `Collector.trades(self, sym=None)` — История бумажных сделок и сводка — по требованию, не в опросе.
  - L5744 `Collector.disk_view(self)` — Диск в человеческих единицах, с запасом хода в сутках.
  - L5767 `Collector.diskstat(self)` — Сколько занято, с какой скоростью растёт и надолго ли хватит.
  - L5799 `Collector.statuser(self)`
  - L5819 `Collector.reporter(self)` — Строка в журнал раз в минуту: прогон, который молчит, неотличим от повисшего.
  - L5843 `Collector.metrics_poll(self)` — Funding, открытый интерес и базис — раз в 5 минут, один запрос на все символы. Ставка и интерес доказали ценн…
  - L5867 `Collector.sit_load_positions(self, books)` — Открытые позиции КАЖДОЙ книги сканера, без исключений.
  - L5886 `Collector.sit_watch(self)` — Живой сторож выходов ситуационной книги.
  - L6054 `Collector.sit_noise(self, sym, now)` — Живой шум монеты: минутный размах середины, б.п. (v12).
  - L6121 `Collector.sit_absorb_now(self, mdir)` — Живое поглощение событий книги: pnl сразу после закрытия.
  - L6165 `Collector._sit_scan(self, root, sheet, want, books, now, armed)` — Один тик сканера входов: лист сечения против живых цен.
  - L6489 `Collector.brake_watch(self)` — Дневной тормоз: реализованный день торгуемых книг против порога −1 % суммарного капитала (`trades.DAY_BRAKE_S…
  - L6553 `Collector.run(self, hours)`
- L6589 `sit_scan_entry(row, mid, wave_bp, min_edge, min_rr, min_disc, n…` — Живой вход по ситуации: якорим прогноз листа к живой цене.
- L6734 `sit_cross(side, entry_px, adv, mid, fav=None, hi=None, lo=None)` — Дошёл ли живой ход цены до обещанного уровня.
- L6790 `take_limit_fill(side, entry_px, fav, hi, lo)` — Цена исполнения тейка-лимитки, если принты прошли уровень.
- L6826 `sit_exit_event(pos, mid, hi, lo, now)` — Событие живого выхода по уровню — или None.
- L6859 `sit_watched(want, root)` — Каталоги книг, у которых 5-секундный сторож ведёт УРОВНИ.
- L6877 `sit_open_levels(picks, reviews, entries=None)` — Открытые позиции ситуационной книги с уровнями против.
- L6927 `_unfinished(rows)` — Записи об открытии, у которых нет парного закрытия.
- L6939 `warm_start(root, symbols, collector, log, hours=4, trade_hours=…` — Поднять историю из собственных файлов сборщика.
- L7040 `stable_token(root)` — Ключ доступа, переживающий перезапуск.
- L7068 `selftest(root)` — Прогнать поддельный поток через путь записи и показать итог.
- L7108 `dropped_symbols(root, syms, days=3)` — Символы, по которым на диске есть свежие ряды, а в запуске их нет.
- L7151 `main()`

## research/b1_book/layout_check.py · 148 строк

Замер раскладки плиток страницы DCA настоящим браузером.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L28 `CHROME = '/opt/pw-browsers/chromium-1194/chrome-…`
- L29 `WIDTHS = (1600, 1400, 1200, 1000, 900, 700, 500)`
- L34 `MAIN = [('стратегия заработала', "+95.56 $ <sp…` — Плитки — те же, что строит `statBlock`: длинные подписи («среднее время в сделке») и есть предмет замера, кор…
- L40 `CELLS = [('закрытых позиций', '388'), ('входов …`
- L48 `BOOK = [('режим', 'безопасная'), ('депозит', '…`
- L52 `_tiles(rows)`
- L57 `build(path)` — Страница замера: CSS и раскладка — вырезкой из `web.py`.
- L105 `measure(path, width)`
- L118 `main()`

## research/b1_book/paper.py · 111 строк

Разбор бумажных сделок: история и сводка.

- L28 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L29 `RESEARCH = os.path.dirname(HERE)`
- L36 `FINISHED = ('цель', 'стоп', 'время')`
- L40 `RULES = ('лента', 'стакан')` — Правила идут параллельно: «лента» — то же, что мерили T3 и T4, «стакан» — новое. Первое здесь контрольная рук…
- L43 `current(trades, ver)` — Сделки текущей версии правил.
- L53 `finished(trades)` — Только сделки с наступившим выходом.
- L59 `as_bracket(t)` — Живая сделка в именах замера T3/T4.
- L66 `summary(trades)` — Сводка тем же ядром, что считало отчёты T3 и T4.
- L76 `by_version(trades)` — Сводка по каждой версии правил отдельно, от новой к старой.
- L89 `by_rule(trades)` — Сводка по каждому правилу отдельно.
- L95 `equity(trades)` — Кривая счёта по времени закрытия: `(момент, б.п., R)`.

## research/b1_book/replay.py · 360 строк

Прогон записанного потока через тот же детектор.

- L47 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L48 `OUT = os.path.join(HERE, 'out')`
- L56 `MIN_LEVELS_FOR_BOOK = 20`
- L59 `hours_back(n)`
- L66 `load(root, kind, sym, hours)`
- L74 `book_at(rows)` — Снимки книги по секундам: `{секунда: (биды, аски, уровней)}`.
- L88 `replay_symbol(root, sym, hours, structural, use_book)` — Прогнать один символ. Возвращает `(сделки, сколько секунд)`.
- L120 `stub(rec, sec, why)` — Запись об отвергнутом входе — «сделки нет и вот почему».
- L139 `replay_seeded(root, sym, hours)` — Те же входы, что были, но геометрия новая.
- L217 `compare(seeded, was_close)` — Сопоставить пересчитанные сделки с их записанными исходами.
- L242 `main()`

## research/b1_book/signals.py · 743 строк

Живой детектор: уровни, события поглощения и бумажные сделки.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L47 `RESEARCH = os.path.dirname(HERE)`
- L59 `WINDOW_SEC = 60`
- L60 `VOL_MULT = 5.0`
- L61 `MOVE_MULT = 0.5`
- L62 `IMB = 0.3`
- L63 `TOUCH_NOISE = 0.5`
- L64 `STOP_NOISE = 1.0`
- L65 `MIN_RR = 1.5`
- L66 `MAX_HOLD_SEC = 4 * 3600`
- L70 `GAP_SEC = 5.0` — Промежуток в ленте больше этого считается ДЫРОЙ, а не тишиной рынка: у наших символов сделки идут чаще. Через…
- L75 `TAPE_FRESH_SEC = 300.0` — Насколько лента вправе отставать от «сейчас», чтобы считать её доведённой до конца. Пять минут: перезапуск за…
- L76 `COST_BP = 11.0`
- L77 `KEEP_SEC = 4 * 3600`
- L78 `DEDUP_SEC = 60`
- L83 `DONE_KEEP = 400` — Сколько закрытых сделок держим в памяти для показа. История целиком живёт в файлах: первая версия хранила сор…
- L88 `STRUCTURAL_STOP = True` — Ставить ли стоп за структуру. Выключатель нужен не для настройки, а для честного сравнения: воспроизведение п…
- L101 `RULES_VERSION = 5` — Версия правил. Поднимается ВСЯКИЙ раз, когда меняется то, как принимается решение или строится сделка. Нужна…
- L104 `outcome_at(tr, p, now)` — Что стало со сделкой при цене `p` в момент `now`.
- L127 `finish_from_tape(tr, prints, gap_sec=GAP_SEC, now=None)` — Досчитать оборванную сделку по записанной ленте.
- L220 `absorb_metrics(buy, sell, close, w, vol_mult, move_mult, imb, s…` — Измеренные величины последнего окна и вердикт по ним.
- L279 `class Live` — Кольцевая история одного символа и его бумажные сделки.
  - L282 `Live.__init__(self, symbol)`
  - L302 `Live.on_trade(self, t)` — --- поток --------------------------------------------------------
  - L317 `Live.close_second(self, sec)`
  - L323 `Live.arrays(self)`
  - L334 `Live.minute_frames(self, a)` — Секунды -> минуты, в том же виде, какой ждёт `levels.build`.
  - L350 `Live.stop_frames(self)` — Свечи ДО СЕКУНДЫ РЕШЕНИЯ, а не до последнего пересчёта уровней.
  - L371 `Live.refresh_levels(self, now)` — Уровни пересчитываются раз в минуту: структура медленная.
  - L403 `Live.candles(self, a, minutes=240)` — Минутные свечи из накопленных секунд — для графика страницы.
  - L419 `Live.check(self, now)`
  - L453 `Live.make_trade(self, now, long, lvl, kind, price, noise, px, rule)` — Собрать сделку. Одна реализация геометрии на оба правила.
  - L536 `Live.on_book(self, bids, asks, now)` — Шаг отслеживания поглощения по свежему снимку книги.
  - L548 `Live.check_book(self, now)` — Правило по стакану. Геометрия — общая с правилом по ленте.
  - L565 `Live.update_open(self, now)` — Провести открытые сделки; вернуть закрывшиеся на этом шаге.
  - L593 `Live.restore(self, rows, prints=None)` — Поднять историю сделок с диска.
  - L644 `Live.view(self, since=0.0, done_keep=20)` — Состояние для страницы.
- L690 `class Signals` — Живые детекторы по всем символам.
  - L693 `Signals.__init__(self, symbols)`
  - L696 `Signals.on_trade(self, t)`
  - L701 `Signals.tick(self, now=None, books=None)` — Шаг всех детекторов. Возвращает `(открытые, закрытые)`.
  - L720 `Signals.view(self, sym, since=0.0)`
  - L726 `Signals.history(self, sym)` — Сделки, что держим в памяти, — закрытые И ОТКРЫТЫЕ.

## research/b1_book/store.py · 315 строк

Хранение потока: запись без потерь и чтение через порчу.

- L42 `MAGIC = b'\x1f\x8b\x08'`
- L43 `STEP = 1 << 12`
- L46 `class Writer` — Почасовые файлы по видам данных и символам.
  - L54 `Writer.__init__(self, root, log=None)`
  - L82 `Writer.hour(ts)`
  - L86 `Writer.path(self, kind, symbol, hour, gz=False)`
  - L90 `Writer.write(self, kind, symbol, obj, ts=None)`
  - L109 `Writer._pack(self, path)` — Поставить закрытый час в очередь сжатия.
  - L115 `Writer._pack_worker(self)` — Единственный поток сжатия: файлы по одному, без штурма CPU.
  - L144 `Writer.flush(self)`
  - L149 `Writer.close(self)`
  - L155 `Writer.pack_stale(self, keep_hour=None)` — Сжать простые файлы прошлых часов, оставшиеся от прошлых запусков: иначе они так и лежали бы несжатыми.
- L168 `read_jsonl(path, log=None, parse=json.loads)` — Прочитать файл записей: простой, сжатый или сжатый с порчей.
- L208 `read_hour(dirpath, hour, log=None, parse=json.loads)` — Записи одного часа: простой файл, сжатый или оба сразу.
- L246 `_parse(f, parse=json.loads)` — Разобрать построчно. Возвращает `(записи, дочитано ли до конца)`.
- L265 `_salvage(path, log, parse=json.loads)` — Разобрать сжатый файл по членам, пропуская испорченные.

## research/b1_book/web.py · 11906 строк

Страница наблюдения: стакан, лента, глубина и журнал живьём.

- L50 `PCTJS = <текст, 7 строк>` — Меню страниц — просьба владельца: все страницы в одном месте, чтобы переключаться, не возвращаясь на обзор. С…
- L64 `LVLJS = <текст, 7 строк>` — Величина БЕЗЗНАКОВАЯ: порог, издержка, граница корзины — это настройка, а не движение цены, и «+0.22 %» у неё…
- L77 `QTYJS = <текст, 11 строк>` — Контракты позиции (монеты, а не деньги). Величины разнесены на порядки — 0.0003 BTC против двенадцати миллион…
- L96 `EXITJS = <текст, 10 строк>` — Причины выхода в ячейках таблиц — коротким словом. Длинная фраза («price broke the promised adverse path») пе…
- L116 `BOOKJS = '\nconst BOOK_LIST = ' + json.dumps([li…` — Книги: ключ и подпись, СОБРАНЫ ИЗ РЕЕСТРА (`s8_loop/books.py`), а не записаны здесь. Список жил восемью копия…
- L137 `NAVJS = <текст, 32 строк>` — Состав меню — решение владельца (2026-08-22): пункт playbook ВЕРНУЛСЯ на справочник (перепутал при прошлой пр…
- L172 `NAVCSS = <текст, 8 строк>` — Стили меню — тоже один раз: пять копий CSS разъехались бы так же незаметно, как разъехался бы список.
- L182 `PAGE = '<!doctype html><meta charset="utf-8">\…`
- L1798 `TRADES = '<!doctype html><meta charset="utf-8">\…` — Отдельная страница истории сделок модели. Заведена по просьбе владельца: на обзоре таблица режется до шестиде…
- L2663 `BOTPAGE = '<!doctype html><meta charset="utf-8">\…`
- L3031 `CHART = '<!doctype html><meta charset="utf-8">\…`
- L5305 `FEATJS = <текст, 98 строк>` — Перевод признаков на человеческий — ОДИН на все страницы, которые его показывают (разбор сделки и справочник)…
- L5411 `TRADEINFO = '<!doctype html><meta charset="utf-8">\…` — Страница разбора ОДНОЙ сделки — просьба владельца: у каждой сделки значок «i», по нему страница, где простыми…
- L5760 `LEARNPAGE = '<!doctype html><meta charset="utf-8">\…` — Справочник — просьба владельца: страница со всеми «стратегиями» модели и подробным объяснением каждой простым…
- L5932 `BOOKDAYS = '<!doctype html><meta charset="utf-8">\…` — Дневная статистика ОДНОЙ книги — просьба владельца: «кликаем на 4-hour book, и открывается страница, где стат…
- L6244 `DCAPAGE = '<!doctype html><meta charset="utf-8">\…` — Бумажная месячная книга (`research/paper_monthly`). Своего показа у неё не было вовсе: книга писала отчёт фай…
- L7564 `PAPERPAGE = '<!doctype html><meta charset="utf-8">\…`
- L7895 `LIVEPAGE = '<!doctype html><meta charset="utf-8">\…`
- L8334 `VOLPAGE = '<!doctype html><meta charset="utf-8">\…`
- L8579 `GLOSSARY_PAGE = '<!doctype html><meta charset="utf-8">\…`
- L8833 `TREEPAGE = '<!doctype html><meta charset="utf-8">\…` — Страница дерева моделей — просьба владельца: разветвление от основных ML и AI, и по каждой ветке простыми сло…
- L9330 `TOURPAGE = '<!doctype html><meta charset="utf-8">\…` — Страница турнира политик — просьба владельца: весь лист веток и подветок отдельной страницей. Данные — артефа…
- L9735 `LEAGUE = '<!doctype html><meta charset="utf-8">\…` — Страница лиги — просьба владельца: наблюдение за каждой стратегией и моделью отдельно (что ведёт себя лучше)…
- L10065 `BUILTPAGE = '<!doctype html><meta charset="utf-8">\…` — Страница автономной системы: конвейер ролей и механических шагов, границы и то, что уже построено. Тексты — и…
- L10421 `STRATPAGE = '<!doctype html><meta charset="utf-8">\…`
- L10848 `ASKSPAGE = '<!doctype html><meta charset="utf-8">\…`
- L11016 `AGENTSPAGE = '<!doctype html><meta charset="utf-8">\…`
- L11546 `serve(collector, port, token, log)` — Поднять сервер наблюдения в отдельном потоке.

## research/d1_seconds/detect.py · 367 строк

D1 — общее ядро решения: событие, вход, форвард, одновременный фон.

- L55 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L56 `RESEARCH = os.path.dirname(HERE)`
- L62 `W_SEC = 15 * 60` — --- объявлено спекой 11 §4, после результата не меняется -------------
- L63 `DROPS = (0.03, 0.05)`
- L64 `DELAYS = (1, 5, 15, 30, 60)`
- L65 `HORIZONS_SEC = (5 * 60, 15 * 60, 30 * 60)`
- L66 `VERDICT_CELL = {'drop': 0.03, 'delay_sec': 5, 'horizon…`
- L67 `MIN_CROSS = 50`
- L68 `EPISODE_SEC = 5 * 60`
- L71 `REF_TOL_SEC = 5` — --- служебные допуски: свойства записи, а не гипотезы ----------------
- L72 `FILL_WAIT_SEC = 5`
- L73 `DEDUP_SEC = W_SEC`
- L74 `MIN_DELAY_SEC = 1`
- L77 `place(times, mids, t0, n)` — Сырой ряд `(время, середина)` на секундную сетку длиной `n`.
- L109 `fill_index(row)` — Индексы ближайшего наблюдения слева и справа от каждой секунды.
- L125 `nearest(prev, nxt, k, tol=REF_TOL_SEC)` — Ближайшее к секунде `k` наблюдение в пределах `±tol`, иначе −1.
- L146 `falls(row, prev=None, nxt=None, window_sec=W_SEC, tol=REF_TOL_S…` — Падение середины за `window_sec` к каждой секунде ряда.
- L166 `detect(row, drop, prev=None, nxt=None, window_sec=W_SEC, dedup_…` — Секунды, в которые условие §4 впервые выполнено.
- L190 `first_at_or_after(nxt, k, wait=FILL_WAIT_SEC)` — Первая доступная цена начиная с секунды `k`, иначе −1.
- L207 `trade(row, nxt, j, delay_sec, horizon_sec, wait=FILL_WAIT_SEC)` — Сделка от решения в секунду `j`: вход, выход, доходность.
- L235 `returns_matrix(P, NXT, j, delay_sec, horizon_sec, wait=FILL_WAI…` — Та же сделка от секунды `j`, но по ВСЕМ строкам матрицы разом.
- L267 `guard_sec(delay_sec, horizon_sec, window_sec=W_SEC)` — Ширина защитного окна фона: `max(окно обнаружения, δ + h)`.
- L278 `GUARD_CHUNK = 128`
- L281 `guard_matrix(shape, rows, j_list, guard, chunk=GUARD_CHUNK)` — Кто в какой момент не годится в фон. Обёртка над L3.
- L308 `excess(P, NXT, row, j, delay_sec, horizon_sec, banned, min_cros…` — Контроль 1: своя доходность против одновременной кросс-секции.
- L336 `episodes(times, gap_sec=EPISODE_SEC)` — Номер эпизода: события всех имён, слипшиеся окном `gap_sec`.
- L346 `by_episode(values, ep)` — Медиана внутри эпизода: одно рыночное окно — один голос.
- L356 `live_fall(times, mids, t_now, window_sec=W_SEC, tol=REF_TOL_SEC)` — Падение к моменту `t_now` по сырому ряду живого сборщика.

## research/d1_seconds/passive.py · 420 строк

D1 — исполнимость пассивного входа в первые секунды после падения.

- L59 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L60 `RESEARCH = os.path.dirname(HERE)`
- L61 `OUT = os.path.join(HERE, 'out')`
- L70 `SIZE_USD = 5000.0` — --- объявлено до прогона ---------------------------------------------
- L71 `WAIT_SEC = 60`
- L72 `MAKER_BP = 2.0`
- L73 `TAKER_BP = 5.5`
- L74 `ARMS = ('тейкер', 'мейкер на биде', 'мейкер на…`
- L77 `book_line(line)` — Время, бид, аск и размеры лучших уровней обеих сторон.
- L108 `trade_line(line)` — Время (с), цена, объём, сторона агрессора (+1 покупка, −1 продажа).
- L123 `book_grids(root, sym, hours, t0, n)` — Бид, аск и размеры лучших уровней на секундной сетке.
- L142 `trade_arrays(root, sym, hours, t0)` — Сделки отрезка: время, цена, объём, сторона. Отсортированы.
- L159 `fill_at(tt, tp, tv, tside, t_place, limit, queue, size, wait=WA…` — Когда исполнится пассивная заявка по цене `limit`.
- L195 `measure_day(root, syms, day, jobs, log=print)` — События суток с исходом по каждой руке.
- L256 `summarise(rows)` — По каждой руке: доля исполнения, превышение нетто, эпизоды.
- L292 `report(art, path)`
- L367 `main()`

## research/d1_seconds/run_d1.py · 752 строк

D1 — реплей записи B1 на секундной сетке. Диагностика, вердикта нет.

- L52 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L53 `RESEARCH = os.path.dirname(HERE)`
- L54 `OUT = os.path.join(HERE, 'out')`
- L61 `BOOK_ROOT = os.path.join(RESEARCH, 'b1_book', 'out'…`
- L62 `PAD_SEC = 3600`
- L63 `DAY_SEC = 86400`
- L72 `COMMISSION_BP = 11.0` — Круг издержек для чтения таблицы. Комиссия — тейкерский цикл по крипто-универсуму Bybit; спред берётся ИЗМЕРЕ…
- L73 `COST_ROUND_FALLBACK_BP = 11.7`
- L76 `unbuffer_output()` — Печатать построчно, даже когда вывод уходит в файл.
- L94 `mem_available_mb()` — Сколько памяти реально доступно. Linux; иначе `None`.
- L105 `rss_mb()`
- L114 `mem_need_mb(rows, n)` — Пик памяти на сутки, мегабайты.
- L126 `mid_line(line)` — Время и середина из строки снимка. Быстрый разбор трёх полей.
- L160 `hours_of(t0, n)` — Часы, накрывающие отрезок `[t0, t0 + n)`.
- L172 `symbol_row(root, sym, hours, t0, n)` — Секундная сетка одного символа за отрезок.
- L189 `_job(args)` — Один символ за отрезок. Отказ по одному имени не валит прогон: сутки читаются по пятистам именам, и падение н…
- L202 `available(root)` — Символы и часы, которые есть на диске.
- L217 `day_bounds(day)`
- L222 `load_day(root, syms, day, jobs=1, log=print)` — Матрица «символы × секунды» суток с запасом по краям.
- L254 `cadence(P, lo, hi)` — Как часто на деле стоят наблюдения: медиана промежутка, секунды.
- L273 `next_index(P)` — Матрица «первое наблюдение начиная с этой секунды», int32.
- L286 `events_of_day(P, t0, drop, last_seen, day_lo, day_hi)` — События суток: `(строка, секунда, метка времени)`.
- L310 `measure(P, NXT, rows, cols, t0, cells, log=print)` — Собственная доходность, фон и превышение по всем ячейкам сетки.
- L335 `summarise(rec)` — Сводка ячейки: по эпизодам, а не по событиям.
- L375 `cost_round(out_dir, tag)` — Круг издержек и откуда он взят.
- L401 `report(art, path, out_dir=None)`
- L497 `main()` — Точка входа. Падение здесь обязано САМО СЕБЯ доложить.
- L526 `_LAST = {}`
- L529 `_run()`
- L673 `write_status(out, tag, status)` — Состояние прогона отдельным файлом. Пишется атомарно.
- L688 `publish(msg)` — Опубликовать отчёт сразу же, а не отдельной командой.
- L715 `checks(art)` — Условия немедленной остановки §7, которые видны без издержек.

## research/d1_seconds/tape_check.py · 425 строк

D1 — проверка события по ленте: падала цена или только котировка.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L47 `RESEARCH = os.path.dirname(HERE)`
- L48 `OUT = os.path.join(HERE, 'out')`
- L57 `TRADE_TOL_SEC = 60` — --- объявлено до прогона ---------------------------------------------
- L58 `MIN_TRADES = 10`
- L59 `CONFIRM_SHARE = 0.5`
- L60 `COMMISSION_BP = 11.0`
- L63 `book_line(line)` — Время, бид и аск из строки снимка.
- L96 `trade_line(line)` — Время и цена сделки. Метка в миллисекундах — как её пишет сборщик.
- L116 `book_grids(root, sym, hours, t0, n)` — Середина и спред (б.п.) на секундной сетке.
- L132 `trade_grids(root, sym, hours, t0, n)` — Цена последней сделки секунды и число сделок в секунде.
- L149 `at_time(prev, nxt, k, tol)` — Индекс ближайшего наблюдения к секунде `k`. Обёртка над ядром.
- L154 `check_day(root, syms, day, jobs, log=print)` — События суток с приписанной к ним проверкой по ленте.
- L214 `group_of(e)` — Три группы, и третья обязана быть отдельной.
- L228 `med(v)`
- L233 `summarise(rows)`
- L274 `report(art, path)`
- L331 `reading(g)` — Вывод пишется из чисел, а не из надежды.
- L375 `main()`

## research/dca_ladder/ladder.py · 692 строк

DCA-лестница с забором по §5 — ЯДРО (спека 14).

- L30 `liq_price(p_avg, qty, capital, mmr, side='long')` — Цена ликвидации позиции при кросс-марже; сторона параметром.
- L57 `liq_frac(p_ref, p_liq)` — Насколько ниже опорной цены стоит ликвидация, долей (0..1).
- L65 `mmr_for_notional(tiers, notional, flat=None)` — Ставка maintenance margin тира, чей верх нотионала ≥ позиции.
- L83 `lev_cap_for_notional(tiers, notional, flat=None)` — Предел плеча ТИРА площадки — потолок, который биржа не даст перейти.
- L107 `fully_loaded(rung_prices, weights, capital, leverage)` — Состояние ПОЛНОСТЬЮ набранной лестницы при данном плече.
- L131 `max_leverage(rung_prices, weights, capital, base_px, d_max, mmr…` — Максимальное плечо, при котором забор §5 выполняется.
- L198 `sigma_rungs(base_px, sigma_frac, n_rungs, spacing_sig, side='lo…` — Цены рунгов по σ-сетке: база плюс равные шаги в единицах σ.
- L222 `structural_rungs(entry, level_prices, min_gap, n_rungs, side='l…` — Цены рунгов DCA: вход плюс СТРУКТУРНЫЕ уровни против позиции.
- L257 `open_mark(px, avg, capital, leverage, weights_filled, side='lon…` — Отметка ОТКРЫТОЙ лестницы: доля капитала позиции при цене `px`.
- L285 `_fill_rungs(filled, cash, qty, lo, rung_prices, weights, notion…` — Заполнить рунги долива, до которых дошёл крайний ход бара `lo`.
- L318 `simulate_ladder(closes, lows, rung_prices, weights, capital, le…` — Пройти путь цены лестницей доливов вниз. Чистая функция.
- L360 `simulate_hold(closes, lows, base_px, capital, leverage, mmr)` — Контроль: весь нотионал куплен в базе разом, без лестницы.
- L384 `simulate_single(bars, capital, leverage, mmr, take_px=None, sto…` — Одиночный вход тем же капиталом и плечом, стоп/тейк; сторона параметром.
- L424 `simulate_dca(bars, rung_prices, weights, capital, leverage, mmr…` — DCA на РЕАЛЬНЫХ барах: доливы против хода, тейк по ходу, пол.
- L652 `same_coin_short(bars, trigger_px, exit_ts, exit_px, short_notio…` — Короткий на ТОЙ ЖЕ монете, включаемый в просадке (вариант а).

## research/dca_ladder/run_d10.py · 901 строк

D10 — чем вывести КОРОТКИЕ DCA-книги в плюс: плечо, доливы, цель, гейт.

- L64 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L65 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L80 `OUT = os.path.join(HERE, 'out')`
- L81 `HOUR = 3600`
- L84 `LEVS = [('fence', 'как забор'), ('c3', 'потоло…` — --- сетка объявлена ДО прогона ----------------------------------------
- L86 `LEV_CAP = {'fence': None, 'c3': 3.0, 'c2': 2.0, '…`
- L87 `ADDS = [('struct', 'структурные уровни'), ('no…`
- L89 `TAKES = [('t2', 'обещание ×2', 2.0), ('t1', 'об…`
- L91 `TAKE_MULT = {k: m for k, _t, m in TAKES}`
- L92 `SPACING_SIG = 2.0`
- L94 `GATES = [('rr2', 'RR ≥ 2 (как сейчас)'), ('lo',…` — Гейты входа: подмножества одного прохода. `rr2` — то, чем книга торгует.
- L96 `REF = 'fence:struct:t2'`
- L97 `REF_GATE = 'rr2'`
- L99 `ROUND_COST_BP = float(TR.ROUND_COST_BP)` — Издержки: круг на заполненный нотионал — тейкер на рунге и на выходе.
- L102 `RULERS = {'safe_s': (R.RULERS['safe_s']['rule'],…` — Книги: линейки забора коротких книг. «Агрессивная» — «оптимальная» плюс гейт плеча режима, из тех же позиций…
- L105 `BOOK_RULER = {'optimal_s': 'optimal_s', 'safe_s': 's…`
- L109 `grid()` — Все объявленные ячейки: ключ → (плечо, доливы, цель).
- L119 `CELLS = grid()`
- L120 `KEYS = [c[0] for c in CELLS]`
- L124 `book_cell()` — Ключ ячейки, равной ДЕЙСТВУЮЩЕМУ правилу книги. None — её нет.
- L136 `gate_of(g)` — Какие гейты нога проходит. Край обязателен у всех (как в книге).
- L151 `LEG_KEEP = ('arm', 'sym', 'hour', 'at', 'side', 'f…` — Поля ноги, которые нужны прогону: остальное (px, beta, adv_m, hour…) у 63 тысяч ног — сотни мегабайт словарей…
- L154 `short_legs(limit=None, log=print, path=None)` — Короткие ноги журнала листов под ОБЪЕДИНЕНИЕМ гейтов (край ≥ 33).
- L205 `REC_F = ('at', 'exit_ts', 'end_ts', 'pnl', 'pnl…` — --- записи ячеек колонками ------------------------------------------------ 62 925 ног × 72 ячейки (2 правила…
- L207 `REC_I = ('depth', 'n_rungs')`
- L208 `GATE_BIT = {'any': 1, 'rr2': 2, 'lo': 4}`
- L211 `class Store`
  - L214 `Store.__init__(self)`
  - L219 `Store.__len__(self)`
  - L222 `Store.append(self, r)`
  - L234 `Store.from_rows(cls, rows)`
  - L240 `Store.key(self, j)`
  - L243 `Store.row(self, j)`
  - L253 `Store.rows(self)`
  - L256 `Store.subset(self, keep)` — Новое хранилище из записей, чей ключ (имя, момент) в `keep`.
  - L271 `Store.set_states(self, data_end)`
- L277 `leverage_for(lk, lev_fence)`
- L282 `take_for(g, tk)` — Цель ячейки — та же форма, что `rules.take_rule`, с множителем оси.
- L295 `one_position(g, bars, ts, look, rule, param, lev_look=None)` — Исход одного КОРОТКОГО решения во всех ячейках. None — нечем мерить.
- L368 `collect(limit=None, src=None, log=print, legs=None)` — Дорогой проход: бары символа читаются ОДИН раз на все ячейки.
- L436 `common_sample(recs, log=print)` — Решения, ЗАКРЫТЫЕ при каждой ячейке (правило D8). Потери — числом.
- L461 `_exits(rows)`
- L468 `cell(recs, book, dep, gate=REF_GATE, net=False)` — Ячейка «правило × книга × депозит × гейт»: касса и форма книги.
- L515 `paired(rows_ref, rows_cell)` — Парная разность исходов к точке отсчёта на ОБЩИХ решениях (доли маржи).
- L528 `halves(rows_by_cell)`
- L540 `lev_split(rows)` — Диагностика D9 на этой выборке: без лестницы против лестницы.
- L554 `_rss_mb()`
- L563 `_rss_now_mb()` — Текущий RSS процесса в МБ (Linux); None — не прочитать.
- L581 `MEM_LIMIT_MB = 1200` — Предел памяти прогона. Машина 7.7 ГБ без свопа: сборщик держит 1.5 ГБ, часовой цикл на шаге матрицы 3.3 ГБ; п…
- L584 `mem_guard(where, log=print, limit=None)` — Печатает RSS в точке `where`; выше предела — останавливает прогон.
- L597 `GATE_KEYS = [REF, 'c1:struct:t2', 'c1:none:t2', 'c1…` — Ячейки, по которым читается ось гейта: правило книги и три ячейки 1×.
- L600 `run(limit=None, src=None, log=print, legs=None)`
- L659 `verdict(s)` — Вердикт из ЧИСЕЛ: положительные ячейки (брутто и нетто), устойчивые к половинам, и лучше ли они нынешнего пра…
- L692 `_p(x, d=2, sign=True)`
- L698 `_u(x)`
- L702 `title_of(key)`
- L708 `_row(key, c, cn, p, mark)`
- L724 `report(s)`
- L866 `publish(name)`
- L872 `main(argv=None)`

## research/dca_ladder/run_d2.py · 656 строк

D2 (спека 14) — DCA-стратегия НА ВЫБОРАХ МОДЕЛИ, а не «где попало».

- L62 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L63 `RESEARCH = os.path.dirname(HERE)`
- L64 `OUT = os.path.join(HERE, 'out')`
- L78 `SHEETS = os.path.join(RESEARCH, 's8_loop', 'out'…` — --- объявленная сетка (до прогона) ---------------------------------------
- L79 `ROOT = os.path.join(RESEARCH, 'b1_book', 'out')`
- L80 `MARKET = 'BTCUSDT'`
- L87 `MIN_EDGE_BP = 33.0` — Гейт книги: реплеим ТОЛЬКО выборы, которые ситуационная книга реально открывает (её вход = «сигнал модели», в…
- L88 `MIN_RR = 2.0`
- L89 `BACK_H = 24`
- L90 `HOLD_H = 72`
- L91 `N_RUNGS = 4`
- L92 `MIN_ADD_GAP = 0.015`
- L93 `WEIGHTS = [0.25, 0.25, 0.25, 0.25]`
- L94 `SURVIVE_MULT = 2.0`
- L95 `FLAT_MMR = 0.02`
- L96 `FLOOR_FRAC = 0.1`
- L97 `SS_SHORT_BETA = 1.0`
- L100 `instruments_tiers()`
- L113 `split_window(bars, ts, at, back_h, fwd_h)` — Окно [at−back_h, at+fwd_h] из УЖЕ прочитанного ряда символа.
- L139 `build_levels(bars, now_i)` — Структурные уровни на момент входа по 24-часовому окну до него.
- L154 `px_at(bars, ts, t)` — Цена закрытия рыночной ноги (BTC) на последнем баре с временем ≤ t.
- L169 `run(limit=None, src=None, log=print)`
- L239 `short_book(legs, get, log, long_day)` — Отдельный шорт-контур (§в): ШОРТ-выборы модели, 1× одиночный вход.
- L287 `_short_stats(pnl, day, liq, n, long_day)`
- L324 `_process_leg(g, bars, ts, look, arms, depth_hist, lev_hist, btc…` — Обработать один выбор на прочитанном ряде символа.
- L435 `measures(arms, n, skipped, no_add, depth_hist, lev_hist, secs)`
- L506 `report(s)`
- L630 `publish(name)`
- L635 `main()`

## research/dca_ladder/run_d3.py · 813 строк

D3 (спека 14) — три замера ОДНИМ проходом по тем же выборам, что D2.

- L58 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L59 `RESEARCH = os.path.dirname(HERE)`
- L60 `OUT = os.path.join(HERE, 'out')`
- L73 `GRID_SURVIVE = [2.0, 3.0, 4.0, 6.0, None]` — --- объявленная сетка (до прогона, не менять после чтения результата) ---- Ряды: множитель забора §5. None =…
- L77 `GRID_FLOOR = [None, 0.1, 0.25, 0.5]` — Колонки: пол капитуляции §6 долей расстояния «вход → ликвидация». None = пола нет вовсе (держим до ликвидации…
- L78 `BASE_CELL = (2.0, 0.1)`
- L80 `TAIL_Q = 0.01`
- L81 `NULL_PERM = 200`
- L82 `NULL_SEED = 20260904`
- L83 `AVOID_Q = 0.1`
- L85 `OPTIONS_INV = os.path.join(RESEARCH, 'a1_universe', '…`
- L87 `INSTRUMENTS = os.path.join(RESEARCH, 'a1_universe', '…`
- L88 `ROOT_B1 = os.path.join(RESEARCH, 'b1_book', 'out')`
- L92 `FEATURES = [('fwd_bp', 'обещание модели |fwd|', 'b…` — Человеческие имена признаков и их единица: «bp» — движение цены (в отчёте печатается процентами), «x» — отнош…
- L107 `instruments()` — Справочник площадки: символ → запись (`launch_time`, `base_coin`, …).
- L122 `listed_days(inst)` — Момент листинга на площадке (секунды эпохи) — известен ex ante.
- L139 `window_stats(win, now_i)` — Признаки окна ДО входа: σ, размах, оборот. Только прошлое.
- L167 `leg_cells(g, bars, ts, look, listed)` — Один выбор во ВСЕХ ячейках сетки плюс его ex-ante признаки.
- L254 `cell_stats(pnl, liq, exits, depth, lev, day)`
- L281 `_avg_ranks(x)` — Ранги со СРЕДНИМ на ничьих — иначе признак-константа даёт AUC ≠ 0.5.
- L297 `auc(vals, mask)` — P(значение в группе выше, чем вне) с ничьими по 0.5. NaN не считаются.
- L315 `family_bar(feats, mask, names, perms=NULL_PERM, seed=NULL_SEED)` — Семейственная планка: 95-й процентиль МАКСИМУМА |AUC−0.5| под нулём.
- L339 `avoid_check(pnl, feat, hi_side, q=AVOID_Q)` — Что даст правило «не открывать дециль признака» — польза И цена.
- L376 `d2_crosscheck(base)` — Сверка базовой ячейки с ОПУБЛИКОВАННЫМ D2 (рука S).
- L403 `base_aliases(sym, inst)` — Базовый актив символа и его алиасы без множителя лота.
- L426 `options_cover(tail_syms, inst)` — Доля хвоста в именах, у которых опционы вообще существуют.
- L455 `run(limit=None, src=None, log=print)`
- L542 `finish(out, cellacc, feats, syms, ruins, inst=None)` — Хвост, признаки, планка и покрытие опционами — по базовой ячейке.
- L609 `_pct(x, digits=2)`
- L613 `report(s)`
- L782 `publish(name)`
- L787 `main()`

## research/dca_ladder/run_d4.py · 479 строк

D4 (спека 14) — хедж на уровне КНИГИ, а не позиции.

- L65 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L66 `RESEARCH = os.path.dirname(HERE)`
- L67 `OUT = os.path.join(HERE, 'out')`
- L77 `HOUR = 3600`
- L78 `ROOT_B1 = os.path.join(RESEARCH, 'b1_book', 'out')`
- L83 `GRID_DD = [0.0, 0.03, 0.07, 0.15]` — --- объявленная сетка (до прогона) --------------------------------------- Порог просадки книги, при котором…
- L85 `GRID_MULT = [0.5, 1.0]` — Доля хеджируемой беты: 1.0 — полная нейтрализация рыночной ноги.
- L86 `NULL_SEEDS = 10`
- L87 `NULL_SEED0 = 20260904`
- L88 `MARKET = D2.MARKET`
- L89 `HALF_ROUND = TR.ROUND_COST_BP / 2.0 / 10000.0`
- L92 `book_hours(legs, get, log, limit=None)` — Почасовая книга: экспозиция, изменение денег, бета — из отметок позиций.
- L150 `_one(g, bars, ts, look)` — Базовая ячейка (забор 2.0, пол 0.10) одной позиции — с отметкой.
- L184 `market_returns(hrs, get, log)` — Часовые доходности рыночной ноги на сетке книги. Нет бара — NaN.
- L202 `simulate_hedge(hrs, dP, X, BW, BC, rmkt, dd_on, mult, on_hours=…` — Кривая книги с хеджем. Решение часа `h` — по состоянию конца `h−1`.
- L242 `curve_stats(res, base_day=None)`
- L269 `run(limit=None, src=None, log=print)`
- L342 `_pct(x, d=2)`
- L346 `report(s)`
- L453 `publish(name)`
- L458 `main()`

## research/dca_ladder/run_d5.py · 691 строк

D5 (спека 14) — ЛИНЕЙКА забора: глубины лестницы против движений монеты.

- L92 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L93 `OUT = os.path.join(HERE, 'out')`
- L103 `ROOT_B1 = D4.ROOT_B1`
- L104 `HOUR = 3600`
- L107 `GRID_RULE = [('depth', 2.0), ('depth', 3.0), ('sigm…` — --- объявленная сетка (до прогона) --------------------------------------
- L110 `ANCHOR = ('depth', 2.0)`
- L111 `MIN_PER_DAY = 1440`
- L112 `DECILE = 0.1`
- L122 `ANCHOR_ROBUST = {'median': 0.0191, 'liq_freq': 0.00058,…` — Опубликованные числа якоря (D3 `2.0|0.1`, D4 базовая книга) и длина журнала, при которой они посчитаны. ЖУРНА…
- L127 `ANCHOR_LEN = {'mean': 0.0288, 'final': 0.0732, 'max_…` — ОТ ДЛИНЫ ЗАВИСЯТ — среднее (одна хвостовая позиция его двигает) и всё, что накоплено книгой по часам. Сверяют…
- L128 `ANCHOR_N = {'D3_positions': 8670, 'D4_positions': …`
- L129 `TOL = {'median': 0.0005, 'mean': 0.0005, 'liq…`
- L133 `sigma_day(sigma_bp)` — Суточная σ долей цены из минутной σ в б.п. Нет меры — None.
- L144 `fence_leverage(rule, param, entry, rungs_full, look, sigma_bp, …` — Плечо по объявленной линейке. Возвращает (плечо, рунги, кто связал).
- L194 `leg_cells(g, bars, ts, look)` — Один выбор во всех ячейках сетки, с почасовой отметкой книги.
- L234 `_hold_stats(hold, by_exit)` — Время в позиции: среднее, медиана, край и разбивка по выходу.
- L258 `_exposure(hrs, X, N, sum_pnl, final)` — Чем книга занята: гросс-нотионал и сколько позиций открыто разом.
- L292 `_dec_stats(lev, liq, mask)` — Медианное плечо и доля ликвидаций внутри среза σ.
- L300 `run(limit=None, src=None, log=print)`
- L443 `_pct(x, d=2)`
- L447 `_lvl(x, d=2)`
- L451 `_mins(h)` — Мелкое время читается в минутах: «0.02 ч» ничего не говорит.
- L458 `report(s)`
- L663 `publish(name)`
- L670 `main()`

## research/dca_ladder/run_d6.py · 1102 строк

D6 (спека 14) — НОРМИРОВКА КАССЫ: мало крупных мест или много мелких.

- L77 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L78 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L79 `OUT = os.path.join(HERE, 'out')`
- L101 `ROOT_B1 = D4.ROOT_B1`
- L102 `HOUR = 3600`
- L105 `DEPOSIT = TR.START_BALANCE` — --- объявленная сетка и правила (до прогона) ----------------------------
- L106 `MIN_NOTIONAL = 5.0`
- L107 `RUNG_SHARE = min(D2.WEIGHTS)`
- L108 `GRID_SHARE = [1.0 / 6, 1.0 / 20, 1.0 / 60, 1.0 / 200…`
- L109 `GRID_RULER = [('depth', 2.0), ('sigma', 6.0)]`
- L117 `GRID_TICKET = [7.0, 5.0]` — Ось билета добавлена ПОСЛЕ первого прогона, под вопрос владельца о другом депозите, и потому диагностика, а н…
- L120 `shares_for(deposit)` — Доли сетки плюс доли, задающие объявленные билеты при этом депозите.
- L130 `one_position(g, bars, ts, look, rule, param, hold_h=None, ckpt_…` — Исход одной позиции при заданной линейке забора. Гейты — D2.
- L233 `SCHED_TOL = 120.0` — Допуски классификации. `SCHED_TOL` — тот же, что у D7: бар не встаёт ровно на границу срока, и больше двух ми…
- L234 `FRESH_TOL = 2 * HOUR`
- L237 `position_state(r, data_end)` — Закрыта / открыта / оборвана записью. Правило одно на всех.
- L257 `queue(recs)` — Очередь за деньгами: по секунде решения, внутри секунды — лучшие.
- L268 `ration(recs, share, deposit=DEPOSIT, min_notional=MIN_NOTIONAL,…` — Хронологическая раздача кассы. Возвращает сводку и кривую счёта.
- L385 `window(longs)` — Окно замера ПО РЕШЕНИЯМ, а не по календарю запуска.
- L406 `peak_open(recs)` — Пик одновременности — В ЛОТАХ и В ИМЕНАХ, и это РАЗНЫЕ числа.
- L445 `one_per_name(recs)` — Строгое биржевое правило: второй выбор по открытому имени пропущен.
- L465 `full_cover(recs, min_notional=MIN_NOTIONAL, rung=RUNG_SHARE, lo…` — Депозит, при котором НИ ОДИН сигнал не отвергнут.
- L539 `coverage_curve(recs, peak, deps, ticket=None, min_notional=MIN_…` — Сколько сигналов берётся при депозите меньше полного охвата.
- L559 `gated_legs(limit=None, log=print, side='long')` — Гейтованные ноги журнала листов — БЕЗ реплея по барам.
- L578 `collect_recs(limit=None, src=None, log=print, rulers=None, hold…` — Дорогой проход: исход КАЖДОГО гейтованного лонга при каждой линейке.
- L677 `run(limit=None, src=None, log=print, deposit=DEPOSIT, anchor_de…`
- L730 `anchor_deposit(s)` — Опора по депозиту — встроенная проверка меры, считается В ОДНОМ прогоне на ОДНИХ исходах.
- L770 `_anchor_block(a)`
- L809 `_full_block(s)` — Депозит, при котором берётся каждый сигнал, и что тогда выходит.
- L904 `_shares_of(s)` — Доли берутся из АРТЕФАКТА, а не из констант: отчёт обязан описывать тот прогон, который породил файл (урок R1…
- L911 `_pct(x, d=2)`
- L915 `report(s)`
- L1015 `_restat_window(s, log=print)` — Окно дописывается в готовый артефакт, ЧИСЕЛ не трогая.
- L1035 `_window_line(w)`
- L1050 `publish(name)`
- L1057 `main()`

## research/dca_ladder/run_d7.py · 387 строк

D7 — замер СРОКА удержания DCA-книги (вопрос владельца 2026-09-04).

- L49 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L58 `OUT = os.path.join(HERE, 'out')`
- L59 `HOUR = 3600`
- L65 `HOLDS_H = [24, 48, 72, 120, 168]` — --- сетка объявлена ДО прогона ---------------------------------------- 72 ч — нынешнее правило книги, оно же…
- L66 `REF_H = D2.HOLD_H`
- L70 `TOL_S = 120` — Допуск на границе окна: бары минутные, и последний бар срока стоит не ровно на границе. Больше двух минут раз…
- L71 `RULER = ('depth', D2.SURVIVE_MULT if hasattr(D2…`
- L75 `RULER_KEY = 'optimal'` — Ключ режима бумажной книги, чью кассу мы занимаем: билет считается из пола и пика РЕЖИМА, поэтому имя обязано…
- L82 `truncate(r, hold_h, idx)` — Исход ТОЙ ЖЕ позиции при сроке `hold_h`; None — измерить нечем.
- L120 `common_sample(recs, holds, log=print)` — Решения, годные при КАЖДОМ сроке сетки. Остальные — числом.
- L133 `_exits(rows)` — Раскладка выходов по причинам — она и объясняет механизм срока.
- L141 `cell(recs, hold_h, idx, dep)` — Одна ячейка «срок × депозит»: касса та же, что у бумажной книги.
- L148 `cell_rows(tr, dep, ruler_key=None, hold_h=None)` — Ячейка по УЖЕ решённым исходам — касса и форма книги.
- L180 `halves(base)` — Разрез выборки НАДВОЕ по времени решения — проверка на шум окна.
- L198 `run(limit=None, src=None, log=print)`
- L233 `_pct(x, d=2)`
- L237 `report(s)`
- L359 `publish(name)`
- L365 `main()`

## research/dca_ladder/run_d8.py · 657 строк

D8 — замер ТЕЙКА DCA-книги (вопрос владельца 2026-09-05).

- L62 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L63 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L74 `OUT = os.path.join(HERE, 'out')`
- L75 `HOUR = 3600`
- L83 `TARGETS = [('fav', 'обещание mfe', lambda fav, si…` — --- сетка объявлена ДО прогона ---------------------------------------- Цель задаётся ДОЛЕЙ цены; откуда доля…
- L91 `ANCHORS = [('e', 'entry'), ('a', 'avg')]`
- L95 `TRAILS = [0.5, 1.0]` — Трейлинг: взвод на обещании, дальше шаг трейла долей ОБЕЩАНИЯ. Якорь только `avg` — у трейла цель не уровень…
- L99 `NORM_CELLS = [('e', 'fav'), ('a', 'fav'), ('a', 'fav…` — Диагностическая рука: нормированные веса. Ячейки объявлены, а не выбраны по результату; `fav2` взят затем, чт…
- L100 `REF = 'e:fav'`
- L103 `book_cell()` — Ключ ячейки, равной ДЕЙСТВУЮЩЕМУ правилу книги. None — её нет в сетке.
- L119 `grid()` — Все объявленные ячейки: ключ → (якорь, цель, трейл, нормировка).
- L133 `CELLS = grid()`
- L134 `TARGET_FN = {k: fn for k, _t, fn in TARGETS}`
- L135 `TARGET_TITLE = {k: t for k, t, _fn in TARGETS}`
- L140 `RULERS = {'safe': (R.RULERS['safe']['rule'], R.R…` — Линейки забора: считаются обе, что ведут книги. «Агрессивная» своей линейки не имеет — она есть «оптимальная»…
- L143 `BOOK_RULER = {'safe': 'safe', 'optimal': 'optimal', …`
- L146 `norm_weights(n)` — Веса лестницы, нормированные на единицу: вкладывается ВЕСЬ нотионал.
- L153 `one_position(g, bars, ts, look, rule, param, lev_look=None)` — Исход одного решения во ВСЕХ ячейках сетки. None — измерить нечем.
- L223 `collect(limit=None, src=None, log=print, legs=None)` — Дорогой проход: бары символа читаются ОДИН раз на все ячейки.
- L288 `common_sample(recs, log=print)` — Решения, ЗАКРЫТЫЕ при каждой ячейке. Остальные — числом.
- L314 `_exits(rows)`
- L321 `cell(recs, book, dep)` — Одна ячейка «правило тейка × книга × депозит»: касса книги.
- L369 `diagnosis(recs, book, dep)` — Разложение «двух копеек» у нынешнего правила — не ось, а объяснение.
- L402 `halves(rows_by_cell)` — Разрез выборки надвое по времени решения — проверка на шум окна.
- L415 `_rss_mb()`
- L424 `run(limit=None, src=None, log=print, legs=None)`
- L460 `_p(x, d=2, sign=True)`
- L466 `_u(x)`
- L470 `title_of(key)`
- L483 `report(s)`
- L629 `publish(name)`
- L635 `main()`

## research/dca_ladder/run_d9.py · 684 строк

D9 — варианты ВЫХОДА коротких DCA-книг (вопрос владельца 2026-09-05).

- L61 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L62 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L70 `OUT = os.path.join(HERE, 'out')`
- L71 `HOUR = 3600`
- L76 `HOLDS = list(D7.HOLDS_H)` — --- сетка объявлена ДО прогона ---------------------------------------- Сроки — ТЕ ЖЕ, что у D7: контрольные…
- L77 `REF_H = D2.HOLD_H`
- L78 `PAIRS = [(24, 72), (48, 72), (24, 168), (48, 16…`
- L79 `THETAS = [0.0, 0.02]`
- L80 `MODES = ('A', 'B', 'C')`
- L85 `BOOKS = {'optimal_s': ('depth', D2.SURVIVE_MULT…` — Книги замера: ключ режима бумажной книги → линейка прохода. Совпадение с реестром режимов ДОКАЗЫВАЕТСЯ ниже,…
- L93 `DERIVED = {'aggr_s': 'optimal_s'}` — Режим с гейтом плеча считается НЕ вторым проходом, а фильтром по плечу над проходом своей линейки — ровно так…
- L94 `SHORT_BOOKS = ['optimal_s', 'safe_s', 'aggr_s']`
- L95 `CONTROL_BOOK = 'optimal'`
- L108 `grid()` — Все 20 ячеек в объявленном порядке: (режим, T, H, θ).
- L119 `cell_key(c)`
- L126 `base_key(c)` — Таймерная ячейка, с которой условная ПАРНА: тот же срок H.
- L132 `decide(r, mode, t, h=None, theta=0.0)` — Исход ТОЙ ЖЕ позиции при варианте выхода; None — измерить нечем.
- L172 `book_recs(recs_by_book, key)` — Записи книги: свой проход либо гейт плеча над базовым (aggr_s).
- L181 `_d9_counts(dec)`
- L188 `cell(recs, c, dep, ruler_key)` — Одна ячейка «вариант × депозит»: касса и форма — как у книги.
- L200 `lev_split(recs, h=REF_H)` — Диагностика: исход текущего правила по плечу — 1× против лестницы.
- L231 `run(limit=None, src=None, log=print, with_control=True)`
- L301 `paired(cells_book, dep)` — Δ итога условной ячейки к своему таймеру A:H (те же позиции).
- L317 `vs_ref(cells_book, dep, ref_h)` — Δ итога КАЖДОЙ ячейки к нынешнему правилу книги — таймеру `ref_h`.
- L338 `summarize(s)` — Числа, из которых выводится вердикт; отчёт печатает их, не прозу.
- L390 `_pct(x, d=2)`
- L394 `_n(x, d=2)`
- L398 `_cell_row(ck, c, pd, ref, vr=None)`
- L417 `report(s)`
- L646 `publish(name)`
- L652 `main(argv=None)`

## research/dca_ladder/run_dca.py · 406 строк

D1 (спека 14) — дешёвый потолок DCA-лестницы: реплей по хранилищу A2.

- L50 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L51 `RESEARCH = os.path.dirname(HERE)`
- L52 `OUT = os.path.join(HERE, 'out')`
- L60 `START = '2022-07-01'` — --- объявленная сетка (до прогона) ---------------------------------------
- L61 `STEP = '1h'`
- L62 `EVAL_D = 30`
- L63 `HOLD_D = 20`
- L64 `STRIDE_D = 20`
- L65 `N_RUNGS = 4`
- L66 `SPACING_SIG = 2.0`
- L67 `SURVIVE_MULT = 2.0`
- L68 `WEIGHTS = [0.25, 0.25, 0.25, 0.25]`
- L69 `FLAT_MMR = 0.02`
- L70 `SIG_FLOOR_Q = 0.1`
- L71 `MIN_SECTION = 20`
- L72 `MEM_SHARE = 0.6`
- L75 `instruments_tiers()`
- L81 `universe(smoke)`
- L101 `read_name(con, sym, t0, t1, step, interval)` — Ряд имени: (времена мс, закрытия, низы) по шагу, СО СДЕЛКАМИ.
- L138 `daily_sigma(times_ms, closes)` — σ суточных лог-доходностей ряда (доля цены).
- L157 `mmr_lookup_for(tiers)` — Функция ставки по нотионалу для имени; нет тиров — плоский §10.
- L164 `entry_dates(start, end_hold)`
- L175 `mem_ok()`
- L188 `slice_window(t, c, lo, ts0, ts1)` — Кусок ряда в [ts0, ts1) миллисекунд.
- L195 `run(interval, smoke, days_limit=None)`
- L297 `measures(lad, hold, liq, ruin, depth_sum, n, skipped, per_day, …`
- L335 `report(s)`
- L378 `publish(name)`
- L383 `main()`

## research/dca_live/probe_levels.py · 138 строк

Замер перед постройкой живой DCA-книги: почём лестница и бывает ли она.

- L29 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L30 `RESEARCH = os.path.dirname(HERE)`
- L40 `ROOT = os.path.join(RESEARCH, 'b1_book', 'out')`
- L43 `SHEET = os.path.join(RESEARCH, 's8_loop', 'out'…` — Каталог книги берётся из РЕЕСТРА, а не собирается соглашением: «model_<ключ>» уже однажды увело сводку в чужу…
- L45 `BACK_H = 24`
- L46 `N_RUNGS = 4`
- L47 `MIN_ADD_GAP = 0.015`
- L50 `rungs(entry, level_prices, min_gap=MIN_ADD_GAP, n=N_RUNGS)` — Копия правила реплея (`run_d2.structural_rungs`) на время замера.
- L68 `build_levels(bars)` — Уровни по последнему бару окна; мало истории — уровней нет.
- L81 `main()`

## research/dca_paper/backfill_fav.py · 127 строк

Добор обещания модели (`fav_bp`) в уже записанные строки журнала.

- L33 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L34 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L41 `legs_index(log=print)` — Обещание модели по ключу решения — из ТОГО ЖЕ списка ног.
- L52 `shards()` — Все куски журнала плюс цельный файл прежнего хранения.
- L62 `patch_file(path, idx, write=False)` — Дописать поле в один кусок. Возвращает (строк, тронуто, без ноги).
- L107 `main()`

## research/dca_paper/costs.py · 566 строк

Издержки бумажных DCA-книг: комиссия площадки, funding, гейт по знаку ставки.

- L49 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L59 `OUT = os.path.join(HERE, 'out')`
- L60 `A1 = os.path.join(ROOT, 'research', 'a1_univ…`
- L61 `UNIVERSE = os.path.join(A1, 'universe.json')`
- L62 `FUNDING_DIR = os.path.join(A1, 'funding')`
- L63 `TAKER_FALLBACK_BP = float(TR.ROUND_COST_BP) / 2.0`
- L64 `MIN_FUNDING_COVER = 0.5`
- L70 `RATE_MAX_AGE_S = 24 * 3600` — «Последняя известная ставка» годится гейту, только если она свежая: интервал начисления на площадке не длинне…
- L73 `MIN_ARM_N = 30` — меньше стольких позиций в ЛЮБОЙ из рук гейта — рука не судится: медиана девяти отсечённых есть шум, а не мера
- L76 `universe()`
- L82 `symbol_maps(assets)` — Символ Bybit → актив; символ → тейкер б.п. (None — ставки нет).
- L94 `fills_of(row)` — Рунги записи: (момент, цена, доля нотионала). Пусто — записи нет.
- L107 `commission_usd(row, taker_bp)` — Комиссия позиции в долларах: каждый рунг и выход, тейкером.
- L131 `funding_usd(row, series, side)` — Funding позиции как ВКЛАД в pnl (минус — платим). None — не измерено.
- L164 `rate_at_entry(series, at, max_age_s=RATE_MAX_AGE_S)` — Последняя ИЗВЕСТНАЯ на момент входа ставка; None — ряда нет, рано или последняя точка старше `max_age_s` (ряд…
- L177 `favourable(side, rate)` — Гейт входа по знаку ставки: лонгу ставка ≤ 0, шорту ≥ 0.
- L184 `_day(ts)`
- L188 `enrich(rows, funding, to_asset, taker, log=print)` — Строка журнала → строка с издержками. Пропуски считаются числом.
- L241 `_sum(rows, k)`
- L246 `_bp_median(rows, k)`
- L252 `_stats_net(rows, dep)` — Форма книги нетто: те же `_stats`, деньги = брутто − комиссия + funding.
- L265 `_stats_gross(rows, dep)`
- L272 `book_costs(rows, dep)` — Издержки книги: суммы, медианы на позицию (б.п. маржи), форма нетто.
- L305 `gate_arm(rows, dep)` — Рука «вход только при благоприятной ставке» против всех — парно.
- L330 `run(rows=None, funding=None, assets=None, log=print)`
- L388 `verdict(s)` — Из чисел: у каких книг знак держится после комиссии и funding, и помогает ли гейт по ставке (парно, по медиан…
- L412 `_u(x)`
- L416 `_p(x, d=2)`
- L420 `_b(x)`
- L424 `report(s)`
- L540 `publish(name)`
- L546 `main(argv=None)`

## research/dca_paper/cut_check.py · 402 строк

Позиции «оборвано записью» — досчитать по НАБЛЮДЁННЫМ ценам.

- L82 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L83 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L98 `ROOT_B1 = D6.ROOT_B1`
- L99 `HOUR = 3600.0`
- L100 `MINUTE = 60.0`
- L103 `cut_keys(cache)` — Решения, оборванные записью хотя бы у одной линейки.
- L117 `data_end_of(cache)` — Докуда дошла ЗАПИСЬ по всем решениям кэша.
- L131 `money(cache, keys, now)` — Деньги книг по этому кэшу: тем же кодом, что считает сама книга.
- L151 `gap_profile(recs)` — Профиль недостачи: на сколько окно не дошло до планового конца.
- L163 `run(limit=None, log=print)`
- L257 `_pct(v)`
- L261 `report(s)`
- L382 `main()`

## research/dca_paper/name_check.py · 242 строк

Соответствуют ли режимы DCA своим именам (вопрос владельца 2026-09-04).

- L35 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L36 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L41 `load_share(rows, deposit, window=None)` — Средняя занятая доля депозита: интеграл маржи по времени / окно.
- L73 `mode_stats(rows, deposit, window=None)` — Риск позиции и загрузка книги по строкам одного режима.
- L102 `collect(path=R.JOURNAL, art=R.ARTIFACT)`
- L133 `_pct(x, d=2)`
- L137 `_lvl(x, d=2)`
- L141 `report(s)`
- L217 `publish(name)`
- L223 `main()`

## research/dca_paper/rules.py · 702 строк

Правила бумажных DCA-книг: три депозита, одни правила.

- L23 `RULES = 6`
- L35 `RULES_SINCE = 1788646632.5` — Момент (UTC), с которого действует ЭТА версия правил. Нужен потому, что смена правила гонит полный пересчёт и…
- L38 `is_current(row)` — Строка журнала ТЕКУЩЕЙ версии правил — книга есть она; прежние версии писаны другим правилом и в счёт не вход…
- L49 `DEPOSITS = [1000.0, 10000.0, 100000.0]` — --- депозиты (решение владельца) ---------------------------------------
- L63 `MIN_NOTIONAL = 5.0` — --- размер билета ВЫВЕДЕН из пола биржи, а не назначен ------------------ Минимальный ордер площадки ровно $5…
- L64 `RUNG_SHARE = 0.25`
- L65 `HEADROOM = 1.25`
- L66 `TICKET_MIN = MIN_NOTIONAL / RUNG_SHARE * HEADROOM`
- L94 `PEAK_SEEN = 457` — --- потолок билета: столько, чтобы хватило на ВСЕ места ---------------- Пол задаёт биржа, потолок — сама кни…
- L95 `PEAK_MARGIN = 1.5`
- L96 `PEAKS = {'safe': 457, 'optimal': 457, 'aggr': 2…`
- L97 `TICKET = TICKET_MIN`
- L100 `MIN_EDGE_BP = 33.0` — --- гейты входа: те же, которыми входит живая ситуационная книга -------
- L101 `MIN_RR = 2.0`
- L106 `SIDE = 'long'` — Сторона книги стала осью реестра (`RULERS[...]["side"]`, решение владельца 2026-09-05: зеркальные короткие кн…
- L109 `SURVIVE_MULT = 2.0` — --- ограда и выход: база D3/D4 (забор 2.0, пол капитуляции 0.10) -------
- L110 `FLOOR_FRAC = 0.1`
- L111 `N_RUNGS = 4`
- L112 `HOLD_H = 72`
- L140 `TAKE_ANCHOR = 'avg'` — --- тейк позиции (решение владельца 2026-09-05, замер D8) -------------- Было: `вход · (1 + mfe)` — НЕПОДВИЖН…
- L141 `TAKE_MULT = 2.0`
- L144 `take_rule(fav_bp, side='long')` — Правило тейка позиции: якорь и доля цены. None — цели нет.
- L187 `SIGMA_MULT = 6.0` — --- две линейки плеча (решение владельца 2026-09-04) -------------------- Плечо не настройка агрессивности: о…
- L202 `AGGR_MIN_LEV = MIN_NOTIONAL / RUNG_SHARE / 5.0` — --- порог третьего режима (решение владельца 2026-09-04) -------------- «Агрессивный» режим есть та же линейк…
- L203 `RULERS = {'safe': {'rule': 'sigma', 'param': SIG…`
- L259 `_SHORT_NOTE = 'Зеркало длинной книги той же линейки: …` — --- зеркальные КОРОТКИЕ книги (решение владельца 2026-09-05) ----------- «Такая же логика, только шорт»: те ж…
- L278 `RULER_ORDER = ['safe', 'optimal', 'aggr', 'safe_s', '…`
- L281 `DEFAULT_RULER = 'optimal'` — Запись БЕЗ поля `ruler` писана этой линейкой: до 2026-09-04 книга была одна и считалась глубиной. Умолчание д…
- L284 `ruler_of(row)` — Линейка строки журнала; у строк прежнего образца поля нет.
- L290 `notional_of(row)` — Нотионал позиции = маржа × плечо; None, если чего-то из двух нет.
- L306 `avg_walk(fills, entry=None, notional=None, take_frac=None, side…` — Плавающая ТВХ: средняя цена входа ПОСЛЕ каждого рунга.
- L401 `open_stats(positions)` — ХУДШАЯ из открытых позиций — та, что просела глубже всех СЕЙЧАС.
- L428 `ruler_title(key)`
- L432 `side_of(key)` — Сторона книги. Ключ без поля — длинная: до 2026-09-05 других нет.
- L443 `row_side(row, ruler=None)` — Сторона ЗАПИСИ позиции — одно правило на всех читателей.
- L463 `min_lev_of(key)` — Порог входа по плечу у режима; НЕТ поля — гейта нет вовсе.
- L481 `ONE_PER_NAME = True` — --- биржевое правило, которое реплей D-серии НЕ соблюдал --------------- На одном счёте в одностороннем режим…
- L490 `AHEAD_H = HOLD_H + 48` — --- «записано вперёд» --------------------------------------------------- Решение считается записанным ВПЕРЁД…
- L492 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L493 `OUT = os.path.join(HERE, 'out')`
- L494 `JOURNAL = os.path.join(OUT, 'journal.jsonl')`
- L495 `ARTIFACT = os.path.join(OUT, 'DCA-paper.json')`
- L498 `floor_of(ruler)` — Пол билета РЕЖИМА: биржевой минимум, переведённый в маржу.
- L510 `peak_of(ruler)` — Пик РЕЖИМА, измеренный по журналу. Неизвестный режим — пик пула.
- L520 `ticket(deposit, ruler)` — Билет книги: не меньше пола режима и не больше доли на все места.
- L533 `slots(deposit, ruler)` — Сколько мест помещается в депозит при билете этой книги.
- L538 `share(deposit, ruler)` — Доля счёта на позицию — ровно билет, выраженный долей.
- L543 `ahead(decided_at, written_at, hours=AHEAD_H, since=None)` — Записано ли решение вперёд, а не восстановлено пересчётом.
- L561 `shard_of(path, at=None)` — Файл журнала, в который идёт решение: СУТКИ по метке решения.
- L579 `shard_day(at=None)` — Дата суток решения строкой — ключ ротации, один на всех.
- L594 `SHARD_CAP = 4 * 1024 * 1024` — Порог ЧАСТИ суточного файла. Сутки оказались единицей недостаточной: одно решение живёт во всех книгах разом…
- L597 `shard_parts(path, at=None, day=None)` — Части суток по порядку: `journal-<дата>.jsonl`, затем `.01`, `.02`…
- L611 `shard_place(path, day, lines, cap=SHARD_CAP)` — Разложить строки суток по частям, не переступая порог.
- L636 `journal_parts(path=JOURNAL)` — Все куски журнала: старый цельный файл и суточные, по порядку.
- L648 `journal_key(r)` — Ключ решения: тем же составом, каким дедуплицирует запись.
- L659 `read_journal(path=JOURNAL, stats=None)` — Строки журнала как есть — из ВСЕХ его кусков, БЕЗ повторов.
- L696 `split_rows(rows, hours=AHEAD_H)` — Наблюдение и пересчёт — ДВА списка, и складывать их нельзя.

## research/dca_paper/run_paper.py · 1037 строк

Бумажные DCA-книги: одни правила, три депозита ($1k / $10k / $100k).

- L42 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L43 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L57 `RULERS = {k: (v['rule'], v['param'], R.side_of(k…` — Линейки плеча объявлены В ПРАВИЛАХ, а не здесь: их читает и страница наблюдения, и вторая запись однажды разо…
- L60 `cache_path()` — Путь кэша разрешается В МОМЕНТ ВЫЗОВА, а не на импорте.
- L69 `cache_sig()` — Подпись настроек, ОТ КОТОРЫХ ЗАВИСИТ РЕПЛЕЙ.
- L98 `read_cache(path=None)` — Кэш реплея: (пара, символ, момент) → запись позиции.
- L130 `write_cache(cache, path=None)` — Кэш пишется ЦЕЛИКОМ и атомарно: дозапись оставила бы в файле записи двух подписей разом, а различить их потом…
- L143 `needs_replay(cache, legs, pairs)` — Какие решения обязан пересчитать этот прогон.
- L173 `_key(r)` — Ключ решения: имя плюс секунда входа. Ими и дедуплицируется.
- L178 `_cell(ruler, dep)` — Ключ книги: линейка и депозит. Одно решение живёт в обеих книгах, и склеив их одним ключом, мы потеряли бы вт…
- L184 `build_rows(by_ruler, now=None, log=print)` — Решения, взятые каждой книгой, с деньгами в долларах.
- L313 `append_journal(rows, path=None, log=print)` — Дописывает только НОВЫЕ решения. Запись write-ahead: строка, однажды попавшая в журнал, не переписывается — и…
- L366 `_stats(rows, deposit)` — Итог, просадка и форма по дням — на ЭТОМ подмножестве строк.
- L442 `summarize(path=None, live=None)` — Свод по книгам: ОДНА кривая, и в ней помечено, что бэктест.
- L486 `_pct(x, d=2)`
- L490 `_tail_words(s)` — Числа хвоста словами. Нет чисел — так и сказано, а не ноль.
- L525 `report(s)`
- L850 `publish(name)`
- L856 `main()`

## research/dca_paper/short_supply.py · 123 строк

Сколько ШОРТОВ вообще есть в журнале листов под теми же гейтами.

- L28 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L29 `ROOT = os.path.dirname(HERE)`
- L38 `OUT = os.path.join(HERE, 'out')`
- L41 `day(ts)`
- L45 `collect(log=print)`
- L59 `stats(by, gated)`
- L76 `report(s)`
- L102 `main()`

## research/dca_paper/smoothing.py · 227 строк

Сглаживают ли короткие DCA-книги длинные — замер, а не имя.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L53 `OUT = os.path.join(HERE, 'out')`
- L56 `series(rows)` — Дневной ряд денег: сутки UTC → доллары.
- L65 `corr(a, b)` — Связь дневных денег по ОБЩИМ суткам. Меньше трёх — меры нет.
- L81 `pair_rows(rows, mode, dep)` — Строки длинной и короткой книг одного режима и депозита.
- L90 `cell(rows, mode, dep)` — Три книги рядом: длинная, короткая и обе вместе.
- L120 `collect()`
- L133 `_p(x, d=2)`
- L137 `report(cells)`
- L201 `main()`

## research/dca_paper/split_journal.py · 198 строк

Разрезать цельный журнал книги на суточные куски.

- L37 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L43 `read_one(path)` — Строки ОДНОГО файла: разрезка не должна читать свои же куски.
- L60 `split(path=None, log=print, apply=True)`
- L115 `repack(path=None, cap=None, log=print, apply=True)` — Переложить строки суток по частям, не переступая порог размера.
- L184 `main()`

## research/dca_paper/tail.py · 257 строк

Хвост ленты, продолженный серединой стакана: ПРАВИЛО книги.

- L57 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L58 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L69 `ROOT_B1 = D6.ROOT_B1`
- L70 `HOUR = 3600.0`
- L71 `MINUTE = 60.0`
- L74 `book_minute_bars(root, sym, t0, t1, log=None)` — Минутные бары по СЕРЕДИНЕ стакана в окне `[t0, t1]`.
- L105 `class TailBars` — Бары ленты, продолженные серединой стакана ПОСЛЕ последнего принта.
  - L120 `TailBars.__init__(self, root=ROOT_B1, log=None)`
  - L130 `TailBars.bars(self, sym, t0, t1)`
  - L161 `TailBars.stats(self)` — Числа правила: их печатает отчёт, а не пересказ прогона.
- L171 `apply(recs, last_tape, last_book=None)` — Разметить исходы хвостом и не пустить ВХОД из котировки.
- L229 `CUT_NO_BOOK = 'книги в хвосте нет вовсе'` — Причины, по которым позиция остаётся оборванной ПОСЛЕ правила хвоста. Объявлены строками один раз: два дослов…
- L230 `CUT_BOOK_SHORT = 'книга кончилась раньше планового конца'`
- L231 `CUT_BOOK_HOLE = 'книга есть, но не в окне этой позиции'`
- L232 `CUT_UNKNOWN = 'причина не измерена'`
- L235 `cut_reason(r, last_tape, last_book)` — Почему эта позиция осталась оборванной, когда хвост уже применён.

## research/f1_carry/carry.py · 169 строк

F1 — carry на funding. Ядро расчёта.

- L42 `weights(score, width)` — Веса книги: верхняя доля `width` в лонг, нижняя в шорт.
- L69 `position_return(w, log_ret)` — Доходность позиции из накопленного логарифмического приращения.
- L93 `decompose(w, price_fwd, funding_fwd)` — PnL книги слагаемыми и по ногам.
- L134 `robust(v, how='median')`
- L145 `share_positive(v)`
- L150 `tail_ratio(v)` — Отношение худшего периода к медианному по модулю. Критерий §8.3 п. 8.

## research/f1_carry/report.py · 157 строк

F1 — отчёт по артефакту прогона.

- L16 `OUT = os.path.join(os.path.dirname(os.path.ab…`
- L19 `bp(x, d=1)`
- L23 `f(x, d=2)`
- L27 `main()`

## research/f1_carry/run.py · 405 строк

F1 — книга carry и разложение её PnL. Прогон.

- L53 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L54 `RESEARCH = os.path.dirname(HERE)`
- L55 `OUT = os.path.join(HERE, 'out')`
- L56 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L70 `STEP = '1h'`
- L71 `BARS_PER_DAY = 24`
- L74 `KS = (7, 14)` — Сетка §4 спеки 04. Объявлена до прогона и НЕ РАСШИРЯЕТСЯ.
- L75 `HS = (5, 10)`
- L76 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L78 `GRID_START = '2022-07-01'`
- L79 `GRID_END = '2026-06-01'`
- L80 `REBALANCE_STEP_DAYS = 1`
- L81 `CHUNK_DAYS = 90`
- L83 `MIN_ASSETS = 30`
- L84 `MIN_FORWARD_BARS = 1`
- L85 `MAX_DROPPED_WEIGHT = 0.05`
- L88 `rebalance_dates(start, end, step_days)`
- L95 `forward_price(R, i_t, i_end)` — Сумма побарных доходностей за `[i_t, i_end)` по каждому активу.
- L112 `run_date(at, grid, PX, cols, live, funding)` — Одно сечение: оценки по всем k, форварды по всем h, книга по сетке.
- L174 `process_chunk(con, dates, liq, universe, funding, interval)`
- L206 `summarize(rows, hs)` — Сводка по сетке: медианы слагаемых, доли, посылки §8.1.
- L261 `main()`

## research/f2_traps/concentration.py · 249 строк

Замер к вопросу владельца: спасает ли стоп книгу carry?

- L52 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L53 `RESEARCH = os.path.dirname(HERE)`
- L54 `OUT = os.path.join(HERE, 'out')`
- L55 `F1 = os.path.join(RESEARCH, 'f1_carry', 'out…`
- L63 `KS = (7, 14)`
- L64 `HS = (5, 10)`
- L65 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L67 `WORST_N = 10`
- L68 `STOPS = (0.5, 0.3, 0.2, 0.1)`
- L69 `DD_LIMIT = 0.2`
- L72 `load_vectors(tag)`
- L86 `arr(d, key)`
- L91 `leg_pnl(w, price, fund, stop=None)` — Вклад каждой ноги в результат книги, с обрезанием или без.
- L113 `main()`

## research/f2_traps/extremes.py · 140 строк

Проверка крайних ног: настоящее движение рынка или дефект архива?

- L32 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L33 `RESEARCH = os.path.dirname(HERE)`
- L34 `OUT = os.path.join(HERE, 'out')`
- L35 `F1 = os.path.join(RESEARCH, 'f1_carry', 'out…`
- L40 `KS = (7, 14)`
- L41 `HS = (5, 10)`
- L42 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L43 `TOP = 25`
- L46 `load_vectors(tag)`
- L60 `arr(d, key)`
- L65 `main()`

## research/f2_traps/report.py · 166 строк

F2 — отчёт по артефакту прогона. Зависимостей не имеет намеренно.

- L12 `OUT = os.path.join(os.path.dirname(os.path.ab…`
- L15 `bp(x, d=1)`
- L19 `f(x, d=3)`
- L23 `money(x)`
- L27 `main()`

## research/f2_traps/run.py · 291 строк

F2 — ловушки раздела 5 спеки 04. Прогон.

- L40 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L41 `RESEARCH = os.path.dirname(HERE)`
- L42 `OUT = os.path.join(HERE, 'out')`
- L43 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L44 `F1 = os.path.join(RESEARCH, 'f1_carry', 'out…`
- L56 `KS = (7, 14)`
- L57 `HS = (5, 10)`
- L58 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L60 `BETA_WINDOW = 26`
- L61 `DELIST_HORIZON = 30`
- L62 `CAPITAL = 20000`
- L63 `MAX_TURNOVER_SHARE = 0.05`
- L64 `TOLERANCE = 1e-09`
- L67 `load_vectors(tag)`
- L83 `bybit_delist_days(universe)` — Дата снятия с торгов **на площадке исполнения**, по активу.
- L119 `as_array(d, key)`
- L124 `main()`

## research/f2_traps/traps.py · 180 строк

F2 — ловушки раздела 5 спеки 04. Ядро расчёта.

- L29 `market_return(price_fwd)` — Доходность равновзвешенной волны за период: среднее по сечению.
- L43 `beta(book, market)` — МНК-наклон доходности книги на доходность волны.
- L66 `rolling_beta(book, market, window)` — β на скользящих окнах: одно число скрывает смену режима.
- L81 `near_delisting(names, weights, last_day, at, days=30)` — Доля гросса книги в активах, снимаемых с торгов в ближайшие `days`.
- L108 `regime_change(counts_form, counts_hold, days_form, days_hold, t…` — Доля веса, у которой частота начислений сменилась между окнами.
- L134 `weighted_share(weights, flags)` — Доля гросса книги, приходящаяся на помеченные активы.
- L143 `leg_stat(names, weights, values, side)` — Медиана величины по одной ноге книги. `side`: +1 лонг, −1 шорт.
- L152 `capacity(weights, turnover, names, capital, max_share=0.05)` — Капитал, при котором нога упирается в оборот актива.

## research/f3_nulls/carry_nulls.py · 115 строк

F3 — нулевые модели раздела 7 спеки 04. Ядро расчёта.

- L48 `permuted(score, rng)` — Нуль 1: оценки перемешаны между активами внутри сечения.
- L58 `random_scores(score, rng)` — Нуль 3: случайная книга той же ширины.
- L70 `align_by_name(names_to, names_from, values)` — Значения `values`, разложенные по именам `names_to`.
- L87 `percentile(values, q)`
- L99 `sigmas_from(value, samples)` — Расстояние от среднего распределения зёрен, в его сигмах.

## research/f3_nulls/report.py · 135 строк

F3 — отчёт по артефакту прогона. Зависимостей не имеет намеренно.

- L12 `OUT = os.path.join(os.path.dirname(os.path.ab…`
- L15 `bp(x, d=1)`
- L19 `pct(x, d=1)`
- L23 `f(x, d=1)`
- L27 `main()`

## research/f3_nulls/run.py · 227 строк

F3 — нулевые модели раздела 7 спеки 04. Прогон.

- L28 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L29 `RESEARCH = os.path.dirname(HERE)`
- L30 `OUT = os.path.join(HERE, 'out')`
- L31 `F1 = os.path.join(RESEARCH, 'f1_carry', 'out…`
- L43 `KS = (7, 14)`
- L44 `HS = (5, 10)`
- L45 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L47 `SEEDS = 10`
- L48 `SHIFTS = (180, 270, 365, 450, 545, 640, 730, 200…`
- L49 `TOLERANCE = 1e-09`
- L52 `load_vectors(tag)`
- L66 `arr(d, key)`
- L71 `book_series(vec, days, k, h, width, mode=None, seed=None, shift…` — Ряд брутто книги по непересекающимся датам.
- L107 `main()`

## research/factory/agents.py · 776 строк

Реестр автономной системы: конвейер из шагов, часть которых ведёт модель, а часть — код.

- L34 `BILINGUAL = ('title', 'plain', 'reads', 'writes', '…` — Поля, обязательные на обоих языках. Приписать шаг и забыть перевод — молчаливый отказ: страница показала бы а…
- L44 `PIPELINE = [{'key': 'runner', 'kind': 'mech', 'mod…` — Конвейер в ПОРЯДКЕ исполнения. `kind`: "role" — шаг ведёт модель, "mech" — шаг механический, кода достаточно.…
- L576 `BOUNDARIES = [{'what': 'exchange keys and the live e…` — Чего не касается НИ ОДИН агент. Это не удобство, а граница взрыва: автономную сессию нельзя остановить посред…
- L624 `RISKS = [{'title': 'agents write plausible text…` — Отказы, которые такая схема создаёт САМА. Названы до постройки: то, что названо заранее, ловится дешевле.
- L688 `pipeline()` — Конвейер в порядке исполнения.
- L693 `roles()` — Шаги, которые ведёт модель.
- L698 `mech()` — Шаги механические — кода достаточно.
- L703 `by_key(key)`
- L710 `missing_translations()` — Записи без русской половины — для теста полноты.
- L736 `tools(key)` — Разрешённые роли инструменты. Пусто — значит не объявлены.
- L754 `DEFAULT_MODEL = 'opus'` — Модель и усилие роли — НАСТРОЙКА, а не умолчание среды. До этого запускалка не передавала ни того, ни другого…
- L755 `DEFAULT_EFFORT = 'high'`
- L758 `model_of(key)`
- L763 `effort_of(key)`
- L768 `fallback_of(key)` — Запасная модель роли. Пусто — отката нет.

## research/factory/asks.py · 169 строк

Чего система ждёт ОТ ВЛАДЕЛЬЦА — журнал и его состояние.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L27 `ASKS = 'asks.jsonl'`
- L28 `MIN_WHAT = 20`
- L29 `MIN_WHY = 40`
- L32 `key_of(what)` — Ключ просьбы: одна и та же просьба не задаётся дважды.
- L38 `read(out)` — Строки журнала. Битая строка считается, а не глотается.
- L56 `append(out, rec)`
- L62 `record(out, items, src)` — Записать просьбы роли. Возвращает число НОВЫХ.
- L93 `done(out, ask_id, note='')` — Закрыть просьбу словом владельца. Отдельная запись, не правка.
- L104 `checked(path, root=ROOT)` — Проверка просьбы: (есть ли ответ, чем проверено).
- L117 `state(out, root=ROOT, now=None)` — Просьбы с состоянием, свежие первыми.
- L147 `main(argv=None)`

## research/factory/candidate.py · 229 строк

Реплей одного кандидата: строка параметров → сделки книги.

- L33 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L34 `RESEARCH = os.path.dirname(HERE)`
- L44 `DAY = 86400.0`
- L49 `RR_LO_MAX = 1.5` — Полоса отношения: «низкое» и «высокое» — те же края, которыми живут книги sit_lo и sit (потолок 1.5 против по…
- L50 `RR_HI_MIN = 2.0`
- L53 `passes(lg, rule)` — Проходит ли нога гейты правила (без учёта мест и согласия).
- L68 `agreed_keys(legs)` — Ключи (час, имя, сторона), которые выбрали ОБЕ руки.
- L82 `order_value(lg, rule)` — Чем меряется место в очереди за слотом.
- L96 `weight(lg, rule)` — Вес ноги в дневном итоге по правилу размера.
- L128 `simulate(legs, outs, rule)` — Сделки книги кандидата.
- L187 `geometry(rule)` — Ось геометрии → тройка (стоп, тейк, предел возраста) турнира.
- L199 `with_geometry(rule)` — Правило плюс поля геометрии, которых ждёт `simulate`.
- L207 `daily_net(trades)` — День выхода → взвешенный нетто книги в б.п. гросса.
- L224 `trade_counts(trades)`

## research/factory/ceiling.py · 735 строк

Потолок заявки: стоит ли её вообще объявлять.

- L128 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L129 `RESEARCH = os.path.dirname(HERE)`
- L130 `ROOT = os.path.dirname(RESEARCH)`
- L139 `OUT = os.path.join(HERE, 'out')`
- L140 `JOURNAL = 'ceilings.jsonl'`
- L142 `PASS = 'pass'`
- L143 `CLOSED = 'closed'`
- L144 `UNDET = 'undetermined'`
- L155 `MIN_TRADES_IN_WINDOW = 10` — --- пороги. Объявлены ДО расчёта и после него не смягчаются ---------- Минимум сделок задан СКОРОСТЬЮ, а не а…
- L156 `MIN_TRADES_PER_DAY = MIN_TRADES_IN_WINDOW / float(PL.WINDOW_…`
- L163 `MAX_CORR = 0.95` — Предел связи. При связи 0.95 пара книг несёт эффективное `N = 2 / (1 + 0.95) = 1.03`: второй кандидат добавля…
- L167 `MIN_PAIR_DAYS = 3` — Столько же общих суток, сколько требует `ledger.effective_n`: пара, которую пул не берёт в свой знаменатель,…
- L190 `MIN_ACTIVE_SHARE = SB.MIN_DAYS / float(PL.IDLE_D)` — --- измеримость ФОРМЫ (решение владельца 2026-09-02) ----------------- Главный критерий владельца — устойчиво…
- L195 `read_run(path)` — Артефакт суточного прогона или причина, по которой его нет.
- L214 `_days(obj)` — Дневной ряд из артефакта: ключ дня — ЧИСЛО, а не строка.
- L241 `record_days(run)` — Длина ЗАПИСИ в сутках из артефакта — знаменатель измеримости.
- L263 `pair_corr(a, b, min_days=MIN_PAIR_DAYS)` — Связь дневных денег двух книг по ОБЩИМ суткам.
- L282 `pair_eff_n(a, b)` — Эффективное `N` пары книг — тем же `effective_n`, что у отчёта.
- L288 `counted_by_pool(daily)` — Считает ли пул этот дневной ряд вовсе.
- L300 `pool_eff_n(live, pending=None, key='pending')` — Эффективное `N` ПУЛА — с заявкой или без неё.
- L317 `_res(verdict, why, **kw)`
- L323 `judge(run, min_tpd=MIN_TRADES_PER_DAY, max_corr=MAX_CORR, min_p…` — Вердикт потолка по артефакту суточного прогона.
- L514 `journal_path(base=None)`
- L518 `read_journal(base=None)` — События потолка и число НЕразобранных строк — как у реестра.
- L541 `record(res, at=None, base=None)` — Дописать вердикт в журнал потолка. Причина отказа или None.
- L576 `_num(x, fmt='{:+.3f}')` — Величина, которой НЕТ, — прочерк, а не ноль: ноль означает «измерено и равно нулю».
- L582 `write_report(path, res, log=print)`
- L693 `publish(log=print)` — Публикация — часть прогона, а не отдельный шаг: шаг, который можно забыть, рано или поздно забывают (урок D1).
- L704 `main(argv=None)`

## research/factory/cycle.py · 309 строк

Суточный круг фабрики: один шаг за вызов.

- L36 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L37 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L38 `OUT = os.path.join(HERE, 'out')`
- L42 `STOP = os.path.join(OUT, 'STOP')`
- L46 `MAX_ROLE_RUNS_PER_DAY = 12` — Предел прогонов РОЛЕЙ за сутки. Ролей в круге стало четыре (разведчик, брифер, предлагающий, строитель); запа…
- L52 `MAX_MECH_RUNS_PER_DAY = 3` — Предел попыток МЕХАНИЧЕСКОГО шага за сутки. Модель он не зовёт, но судья читает бары часами: падающий шаг без…
- L59 `MAX_TRIES_PER_STEP = 3` — Предел попыток ОДНОГО шага за сутки — общий для ролей и механики. Исчерпав его, шаг ПРОПУСКАЕТСЯ, а не остана…
- L61 `START_HOUR = 2` — Час UTC, раньше которого круг не начинается.
- L82 `CIRCLE = [('scout', 'role', None, None), ('brief…` — Круг в порядке исполнения: ключ, вид, чем запускается, чем доказано. ПОРЯДОК ВЫВЕДЕН ИЗ ДАННЫХ, а не из красо…
- L108 `GATES = {'build': lambda out: _build_ready(out)}` — Шаг, у которого есть условие: без него шаг пропускается молча, но строкой в выводе, а не тишиной.
- L111 `_build_ready(out)`
- L122 `AFTER = {'ceiling': 'factory-day-1m.json', 'dec…` — Шаг → артефакт, который он читает. Пусто — входа нет (шаг читает журналы и хранилище, а не продукт соседа).
- L134 `day_of(ts)`
- L138 `done_today(key, kind, proof, rows, now)` — Шаг сделан сегодня? Роль судится журналом, механика — артефактом.
- L167 `launch(key, kind, argv, log=print)` — Запустить шаг ОТЦЕПЛЕННО и вернуть номер процесса.
- L202 `main(argv=None)`

## research/factory/declare.py · 158 строк

Шаг объявления: заявка, прошедшая потолок, попадает в реестр.

- L32 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L38 `OUT = os.path.join(HERE, 'out')`
- L39 `DAY = 86400.0`
- L42 `_day(ts)`
- L46 `read_json(path)`
- L56 `gate(ceil, prop, run_at, now, state, ceil_at=None)` — Можно ли объявлять. Возвращает (правило, причина отказа).
- L106 `main(argv=None)`

## research/factory/ledger.py · 204 строк

Реестр испытаний фабрики — журнал событий, а не таблица состояний.

- L30 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L31 `LEDGER = 'ledger.jsonl'`
- L33 `DECLARE = 'declare'`
- L34 `RETIRE = 'retire'`
- L35 `LANES = ('selected', 'control')`
- L38 `path(base=None)`
- L42 `read(base=None)` — События реестра и число НЕразобранных строк.
- L71 `state(rows)` — Состояние кандидатов по журналу: id → запись.
- L97 `active(st)`
- L101 `retired(st)`
- L105 `_append(row, base=None)`
- L112 `declare(cid, rule, lane, seed=None, at=None, base=None, source=…` — Объявить кандидата. Возвращает причину отказа или None.
- L134 `retire(cid, why, at=None, base=None)`
- L144 `_now()`
- L148 `spent(st)` — Сколько испытаний потрачено — по полосам и всего.
- L163 `effective_n(series)` — Эффективное число испытаний по попарной связи дневных денег.
- L196 `_corr(xs, ys)`

## research/factory/live_books.py · 259 строк

Правило кандидата → ЖИВАЯ бумажная книга.

- L54 `DIR_MARK = '_c_'` — Каталог книги кандидата: `model_c_<ключ>`. Префикс `model_` обязателен (правило `books.MAIN_DIR`) — в демо-пр…
- L55 `DIR_PREFIX = 'model' + DIR_MARK`
- L59 `SLOTS_PER_WIDTH = 2` — Ситуационная книга держит места ПО СТОРОНАМ (реплей `simulate` считает `width` на сторону), поэтому мест у кн…
- L62 `SIZING = {'equal': None, 'risk': 'fixed_risk', '…` — Ось «размер» реестра → имя правила кассы (`trades.account`).
- L65 `RR_BAND = {'none': (0.0, None), 'lo': (0.0, 1.5),…` — Ось «полоса отношения» → пара (пол, потолок) для гейта сканера.
- L82 `LIVE_LANES = ('selected',)` — Кому заводится ЖИВАЯ книга (решение владельца 2026-09-02): «не для всех кандидатов, а только для тех, кто про…
- L85 `rule_gap(rule)` — Чем живая машинерия сегодня не умеет это правило, или None.
- L107 `gap(rec)` — Почему кандидату НЕ заводится живая книга, или None.
- L124 `book_of(cid, rec, describe=None)` — Запись книги для `books_extra.json` или (None, причина).
- L187 `build(state, describe=None)` — Реестр испытаний → (книги, пропущенные с причинами).
- L204 `write(path, books, log=None)` — Атомарно записать `books_extra.json`.
- L223 `KEY_CHARS = set('abcdefghijklmnopqrstuvwxyz01234567…` — Ключ кандидата: только эти знаки (см. `book_of`). Набор служит и отличителем архива от живого каталога в `dro…
- L226 `dropped_dirs(root, main, keys)` — Каталоги книг кандидатов на диске, которых НЕТ в составе.

## research/factory/mech_queue.py · 341 строк

Очередь МЕХАНИК: заявки, которых движок ещё не умеет.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L27 `QUEUE = 'mechanisms.jsonl'`
- L28 `TASK = 'build_task.md'`
- L29 `TASK_PREV = 'build_task-prev.md'`
- L30 `MARK = '<!-- механика: %s -->'`
- L33 `key_of(title)`
- L38 `DIR_PREFIX = 'research/mech_'`
- L41 `dir_of(mid)` — Каталог механики. Выводится МАШИНОЙ из ключа, и это не вкус.
- L59 `read(out)`
- L76 `append(out, rec)`
- L82 `queue(out, prop, src='propose')` — Поставить механику из заявки. Возвращает ключ либо None.
- L110 `mark(out, ev, mid, note='')` — Отметить механику: `given` (отдана), `built`, `blocked`.
- L116 `state(out)` — Механики со состоянием, старые первыми (очередь, а не стопка).
- L145 `pending(out)` — Механики, которых строитель ещё не брал и которые не закрыты.
- L151 `task_id(path)` — Чья механика лежит в задании. Нет метки — задание рукописное.
- L164 `task_text(rec)` — Задание строителю из заявки. Слова заявки, а не мой пересказ.
- L210 `write_task(out, rec)` — Положить задание строителю. Прежнее не теряется, а отходит.
- L221 `STATE = 'mech_task.json'`
- L224 `write_state(out, decided, mid=None, note='')` — След шага круга: что решено СЕГОДНЯ.
- L242 `build_ready(out)` — Есть ли ЧТО строить: задание машины, ещё не закрытое.
- L255 `main(argv=None)`

## research/factory/mech_run.py · 76 строк

Обёртка механического шага круга: прогон и ТЕРМИНАЛЬНАЯ строка журнала.

- L26 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L31 `out_dir()` — Каталог журнала. Подменяется переменной среды — как у роли.
- L36 `main(argv=None)`

## research/factory/pool.py · 254 строк

Пул кандидатов: сколько объявлять и кого отставлять.

- L46 `CAP = 100`
- L47 `CONTROL_SHARE = 0.25`
- L48 `PER_DAY = 5`
- L49 `WINDOW_D = 10`
- L50 `IDLE_D = 30`
- L51 `DAY = 86400.0`
- L60 `MIN_MED_DAY = 0.0` — --- пороги формы ----------------------------------------------------- Обычный день не вправе быть отрицатель…
- L68 `MAX_BITE = 10.0` — Худший день не глубже десяти обычных прибыльных. Число не выдумано и не подобрано: критерий 8 спеки 04 объяви…
- L72 `MAX_DAY_NO = 100000` — Ключ дневного ряда — номер суток от эпохи. Больше этого — секунды, а не сутки (сто тысяч суток от эпохи это 2…
- L75 `plan_batch(n_active, n_control_active, want, cap=CAP, share=CON…` — Сколько отобранных и сколько случайных объявить сейчас.
- L96 `day_no(t, day=DAY)` — Момент в СЕКУНДАХ → номер суток, то есть ключ дневного ряда.
- L101 `days_of(daily)` — Ключи дневного ряда — и громкий отказ, если это не сутки.
- L125 `window_net(daily, now, window_d=WINDOW_D, day=DAY)` — Сумма нетто за последние `window_d` СУТОК и число дней с записью.
- L141 `split_forward(daily, declared_at, day=DAY)` — Дневной ряд книги → (форвард, реплей по прошлому).
- L164 `shape_why(daily, declared_at, min_med=MIN_MED_DAY, max_bite=MAX…` — Причина вылета ПО ФОРМЕ или None.
- L203 `should_retire(daily, now, null_median, declared_at, window_d=WI…` — Причина вылета кандидата или None.
- L237 `sweep(state, daily_by_id, now, null_median, **kw)` — Кого отставить сейчас — по всем живым кандидатам разом.

## research/factory/probe_env.py · 105 строк

Что нужно запускалке ролей, и чего на этой машине нет.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L27 `line(name, ok, note='')`
- L32 `main()`

## research/factory/publish_build.py · 156 строк

Опубликовать то, что построила роль строителя.

- L27 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L28 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L29 `REPORT = os.path.join(HERE, 'out', 'build.json')`
- L40 `ALLOWED_PREFIX = 'research/factory/'` — Публиковать можно только СВОЙ каталог: путь наружу означает не опечатку, а попытку, и белый список публикации…
- L43 `roots(out=None)` — Свои каталоги: фабрика плюс каталог механики из задания.
- L57 `paths_of(report, log=print, allowed=None)` — Пути, объявленные отчётом постройки. Чужое отсеивается.
- L106 `main(argv=None)`

## research/factory/pycguard.py · 264 строк

Байткод, заслоняющий исходник: как он появляется и как его найти.

- L53 `HEADER = 16`
- L54 `FLAG_HASH = 1`
- L55 `FLAG_CHECKED = 2`
- L57 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L60 `cache_file(src)` — Путь к кешу, который питон СЧЁЛ БЫ кешем этого исходника.
- L78 `header(pyc)` — (магия, флаги, поле1, поле2) заголовка кеша либо None.
- L90 `looks_fresh(src, pyc)` — Счёл бы питон этот кеш свежим — его же правилом, не нашим.
- L117 `_defs(code)` — Код каждого объявления верхнего уровня: {имя: код}.
- L128 `source_code(src)` — Код, скомпилированный из ИСХОДНИКА на диске.
- L135 `cached_code(pyc)` — Код, лежащий в кеше, либо None, если кеш не разбирается.
- L145 `shadow(src)` — Заслоняет ли кеш исходник. Находка С ЧИСЛАМИ либо None.
- L177 `find_shadows(sources)` — Находки по списку исходников, в порядке имён.
- L187 `loaded_here(base=HERE, mods=None)` — Исходники модулей этого каталога, УЖЕ загруженных в процесс.
- L203 `clear(finds)` — Убрать заслоняющие кеши. Возвращает список убранных путей.
- L226 `describe(f)` — Находка словами и числами.
- L235 `main(argv=None)`

## research/factory/run_day.py · 695 строк

Суточный прогон фабрики: объявить, прогнать, отсеять, доложить.

- L34 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L35 `RESEARCH = os.path.dirname(HERE)`
- L36 `ROOT = os.path.dirname(RESEARCH)`
- L49 `OUT = os.path.join(HERE, 'out')`
- L50 `PROPOSALS = os.path.join(HERE, 'proposals.jsonl')`
- L57 `PROPOSAL_NAME = 'proposal.json'` — Заявка предлагающего — та самая, которую судит ПОТОЛОК, и она ещё не объявлена: между ней и реестром стоит ша…
- L58 `NULL_SEEDS = 10`
- L59 `DAY = 86400.0`
- L64 `read_proposals(path=None)` — Предложения ассистента: правило и, необязательно, довод.
- L98 `pending_rule(state, path)` — Заявка, которую судит потолок: (правило, причина отсутствия).
- L135 `run_pending(rule, legs, outs)` — Числа заявки тем же реплеем, что у живых кандидатов.
- L148 `declare_today(base, now, seed, log=print, per_day=None)` — Объявить предложенных и добрать контрольную руку жребием.
- L176 `declare_rules(base, now, seed, fresh, log=print, per_day=None, …` — Объявить названные правила и добрать контрольную руку жребием.
- L215 `needed_legs(legs, rules, log=print)` — Ноги, которые возьмёт ХОТЯ БЫ ОДИН живой кандидат.
- L231 `record_days(legs)` — Длина ЗАПИСИ в сутках — сколько календарных суток вообще есть в журнале листов сечения.
- L261 `load_legs(sheets, log=print)`
- L269 `outcomes_for(legs, root, geoms, log=print)` — Исходы всех ног при всех нужных геометриях.
- L301 `_adv(lg, stop)`
- L307 `_fav(lg, take)`
- L311 `geometries()` — Все тройки геометрии, какие может попросить пространство.
- L325 `LAST_TRADES = 40` — Сколько последних сделок кандидата кладётся в артефакт. Полный список — десятки тысяч строк на кандидата: арт…
- L328 `run_candidates(state, legs, outs, log=print)` — Сделки и дневной нетто по каждому живому кандидату.
- L356 `null_daily(legs, outs, rule, seeds=NULL_SEEDS)` — Дневной нетто книги на ПЕРЕМЕШАННЫХ внутри часа исходах.
- L393 `null_median(nulls, now, window_d=PL.WINDOW_D)` — Медиана нуля за окно вылета — то число, с которым сравнивается кандидат. Одно на группу, а не на книгу.
- L410 `_med(xs)`
- L418 `verdict(sel, ctl, n_days)` — Фраза вердикта ВЫВОДИТСЯ из чисел, а не стоит рядом с ними.
- L444 `write_report(path, meta, cands, st, nulls_med, log=print, pendi…`
- L565 `publish(path, log=print, msg='фабрика: суточный прогон')` — Публикация — часть прогона, а не отдельный шаг: шаг, который можно забыть, рано или поздно забывают (урок D1).
- L581 `main(argv=None)`

## research/factory/runlog.py · 1155 строк

Журнал прогонов ролей и механическая проверка того, что роль произвела.

- L31 `RUNS = 'agents-runs.jsonl'`
- L38 `BRIEF_BUDGET_CHARS = 33000` — Потолок брифа. Роль предлагающего читает ТОЛЬКО бриф, и весь смысл сторожа — не платить 216 тысячами токенов…
- L43 `BRIEF_MIN_CITES = 3` — Бриф без указателей брифом не является: утверждение без ссылки на файл и число нечем оспорить. Три — не «дост…
- L58 `CITE_RE = re.compile('[A-Za-z0-9_][A-Za-z0-9_./-]…` — Что считается указателем. Расширения — те, в которых у нас живут данные и код; голое слово путём не является.…
- L69 `LIMIT = 'limit'` — Отказ по лимиту аккаунта — ОЖИДАНИЕ, а не поломка, и статус у него свой. Разница не косметическая: попытка, у…
- L74 `LIMIT_BACKOFF_SEC = 1800` — Запас, когда ответ не назвал момента снятия. Не угадываем время по тексту: лучше подождать объявленное и сказ…
- L77 `limit_retry_at(text, now=None)` — Когда пробовать снова после отказа по лимиту: (момент, откуда).
- L132 `limit_wait(rows, role, now=None)` — Сколько секунд роли ещё ждать снятия лимита (0 — не ждёт).
- L160 `append(path, role, status, started, ended=None, note=None, dry=…` — Дозаписать строку прогона. Возвращает записанную строку.
- L194 `read(path)` — Прочитать журнал. Возвращает (строки, число битых).
- L217 `last_by_role(rows)` — Последний прогон каждой роли — по времени, а не по порядку строк.
- L239 `ok_runs(rows)` — Роли, у которых был хотя бы один НЕсухой успешный прогон.
- L250 `fails_since_ok(rows, role)` — Сколько попыток роли ПОДРЯД кончились отказом и чем — с последнего успеха.
- L289 `cites(text)` — Пути, названные в тексте.
- L316 `BRIEF_OPEN_MARK = 'Что открыто'` — Заголовок раздела, который бриф обязан нести. Строкой, а не структурой: бриф пишет модель человеческим тексто…
- L319 `check_brief(text, root, budget=BRIEF_BUDGET_CHARS, min_cites=BR…` — Механическая проверка брифа. Возвращает (годен, список бед, пути).
- L357 `alive(pid)` — Жив ли процесс. Мёртвый номер значит «прогон оборван».
- L366 `state_of(rows)` — По каждой роли: идёт ли прогон сейчас и чем кончился прошлый.
- L406 `history(rows, role, limit=20)` — Последние строки роли, новые сверху.
- L430 `PROPOSAL_MIN = {'hypothesis': 80, 'kills_it': 60, 'cei…` — Поле `shape` заведено решением владельца (2026-09-02): главный критерий — устойчивость, «приносит немного, но…
- L438 `PROPOSAL_ORIGIN = ('own', 'scout', 'space')` — Откуда заявка взялась. Поле обязательное и с закрытым набором значений: «придумал сам» и «пересказал чужое ме…
- L439 `PROPOSAL_MIN_SEED = 120`
- L440 `FACTORY_PREFIX = 'research/factory/'`
- L441 `PROPOSAL_MIN_CITES = 3`
- L442 `BRIEF_PATH = 'research/factory/out/brief.md'`
- L446 `PROPOSAL_MIN_WHY = 120` — Пустой день — законный ответ, но он обязан быть ОБОСНОВАН: иначе «сегодня нечего предложить» станет способом…
- L449 `check_proposal(text, root, ledger_ids=(), space=None, closed_id…` — Предложение проверяемо? Возвращает (годно, список бед).
- L571 `SCOUT_MIN = {'title': 8, 'claim': 40, 'mechanism': …`
- L573 `SCOUT_MAX_IDEAS = 5`
- L574 `SCOUT_MIN_WHY = 120`
- L575 `SCOUT_SEEN = 'scout.jsonl'`
- L578 `scout_seen(base, before=None)` — Заголовки уже принесённых идей. Журнал ведёт машина.
- L617 `scout_record(text, base)` — Дописать принесённое в журнал. Возвращает число записанных.
- L662 `check_scout(text, seen=())` — Меню разведчика проверяемо? Возвращает (годно, список бед).
- L721 `check_needs_owner(d)` — Форма просьб к владельцу в отчёте роли. Возвращает список бед.
- L752 `_owner_asks(out, d, src)` — Записать просьбы к владельцу. Молча не теряем ни одной.
- L761 `_close_mechanism(out, d)` — Отметить механику построенной либо упершейся в владельца.
- L781 `OUT_REL = 'research/factory/out'`
- L784 `check_role(role, root, since=None, out=None, record=False)` — Контракт роли: выполнен ли. Возвращает (годно, список бед).
- L916 `BUILD_MIN_WHY = 120`
- L926 `BUILD_MAX_CONTROLS = 24` — Предел числа подделок и общий бюджет времени на их проверку. Первая версия ставила предел 8 и ОТВЕРГЛА починк…
- L927 `BUILD_CONTROLS_BUDGET = 1800`
- L929 `BUILD_TEST_TIMEOUT = 900` — Сколько ждать прогон тестов кандидата.
- L932 `_run_tests(root, tests)` — Прогнать тесты кандидата. Возвращает (прошли, вывод).
- L965 `_own_path(rel, roots)` — Путь принадлежит одному из своих каталогов и не вылезает наружу.
- L972 `mech_dir(out)` — Каталог механики, лежащей СЕЙЧАС в задании строителя.
- L987 `check_build(text, root, out_dir=None)` — Постройка годна? Возвращает (годно, список бед).
- L1101 `ADV_MIN_TRIES = 3`
- L1102 `ADV_MIN_HOW = 40`
- L1103 `ADV_MIN_WHY = 100`
- L1104 `ADV_VERDICTS = ('veto', 'pass', 'undetermined')`
- L1107 `check_adversary(text, root)` — Разбор адверсария годен? Возвращает (годно, список бед).

## research/factory/scout_backfill.py · 197 строк

Дописать журналу разведчика текст идей, записанных заголовком.

- L29 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L30 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L35 `MENU = 'research/factory/out/scout.json'`
- L36 `FIELDS = ('claim', 'mechanism', 'kills_it', 'nov…`
- L39 `read_journal(path)` — Строки журнала как есть. Битая строка считается, а не глотается.
- L56 `incomplete(rows)` — Заголовки, у которых НИ ОДНА запись не несёт текста идеи.
- L75 `first_at(rows, title)` — Момент ПЕРВОЙ записи заголовка: восстановление не сдвигает порядок.
- L83 `restore(rows, menus)` — Записи-поправки для заголовков без текста.
- L116 `git_menus(root, limit=40)` — Версии меню из истории git, свежие первыми.
- L141 `main(argv=None)`

## research/factory/space.py · 257 строк

Пространство кандидатов фабрики — объявлено ДО первого прогона.

- L23 `AXES = (('target', ('fwd_4h', 'fwd_24h')), ('r…` — Порядок осей = порядок полей в ключе кандидата. Менять порядок значит менять ключи всех уже объявленных канди…
- L62 `GEOMETRY = {'timer': ('no', False, 24), 'stop_take…` — Геометрия сделки одной таблицей: (стоп, тейк, предел возраста). Живёт ЗДЕСЬ, в модуле пространства, а не рядо…
- L69 `AXIS_NAMES = tuple((a for a, _ in AXES))`
- L70 `VALUES = dict(AXES)`
- L75 `TOTAL = 1` — Полный перебор. Число закреплено ЛИТЕРАЛОМ в проверке: оно и есть знаменатель испытаний фабрики, и молчаливое…
- L81 `_SHORT = {'target': {'fwd_4h': 'h4', 'fwd_24h': …` — Короткие ярлыки для ключа кандидата: ключ уезжает в имя каталога и в адрес страницы, поэтому только латиница,…
- L93 `validate(rule)` — Строка параметров годна? Возвращает причину отказа или None.
- L114 `key(rule)` — Ключ кандидата — из САМОГО правила, а не из счётчика.
- L136 `describe(rule, lang='ru')` — Объяснение книги ИЗ ПАРАМЕТРОВ — страница обязана его печатать.
- L172 `_rand(seed, i)` — Зерно выводится ЧИСЛОМ, а не `hash()`: хеш строки в Python солится на каждый процесс, и нуль, который нельзя…
- L181 `index_to_rule(idx)` — Номер сочетания → правило. Порядок осей объявлен, значит номер и правило переводятся друг в друга однозначно.
- L191 `draw(seed, n, exclude=(), available_only=True)` — `n` РАЗЛИЧНЫХ правил равномерно случайно из пространства.
- L224 `SHEET_TARGETS = ('fwd_4h',)` — --- что из пространства сегодня исполнимо --------------------------- Пространство объявлено целиком и не сжи…
- L227 `unavailable(rule)` — Причина, по которой правило сегодня не исполнимо, или None.
- L250 `available_total()` — Сколько сочетаний исполнимо сегодня — знаменатель, который печатается рядом с числом потраченных испытаний.

## research/factory/stability.py · 325 строк

Устойчивость книги: не «сколько принесла», а КАК приносила.

- L48 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L49 `RESEARCH = os.path.dirname(HERE)`
- L68 `MIN_DAYS = PL.WINDOW_D` — Граница тонких данных — та же, что окно правила вылета, и берётся она У ПРАВИЛА, а не повторяется числом: пре…
- L71 `stats(daily)` — Устойчивость по ряду «сутки → нетто за эти сутки».
- L127 `OUT = os.path.join(HERE, 'out')`
- L128 `TOKEN = os.path.join(RESEARCH, 'b1_book', 'out'…`
- L131 `_get(base, path, key, timeout=120)`
- L137 `live_rows(base, key, keys)` — Устойчивость ЖИВЫХ книг: сутки в долларах, как их считает касса.
- L159 `cand_rows(base, key)` — Устойчивость РЕПЛЕЯ кандидатов: доли гросса, до и после объявления.
- L177 `_cell(s, field)`
- L184 `_money(v, cap)` — Деньги и доля к депозиту рядом — единица показа всего проекта.
- L197 `_pct(v)` — Доля гросса реплея: базисные пункты хранения — проценты показа.
- L202 `_table(rows, get, title, unit)`
- L249 `report(live, cands, base, at)`
- L292 `main()`

## research/l0_liquidation_inventory/inventory.py · 265 строк

L0 — инвентаризация данных о ликвидациях.

- L57 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L58 `OUT = os.path.join(HERE, 'out')`
- L59 `CACHE = os.path.join(OUT, 'cache')`
- L64 `BINANCE_S3 = 'https://s3-ap-northeast-1.amazonaws.co…`
- L65 `BYBIT_ARCHIVE = 'https://public.bybit.com/trading/'`
- L69 `SAMPLE = ('BTCUSDT', 'SOLUSDT', 'ARBUSDT')` — Представители: крупный, средний и мелкий по обороту — объём ленты зависит от активности, и средним по одному…
- L70 `SAMPLE_MONTH = '2025-03'`
- L73 `UA = 'l0-liquidation-inventory/1.0'`
- L76 `fetch(url, cache_key=None, binary=False)`
- L82 `s3_list(prefix, delimiter='/')`
- L101 `s3_sizes(prefix)` — Ключи с размерами — нужно для оценки объёма.
- L121 `binance_datasets()` — Какие типы данных лежат в архиве USD-M, помесячно и посуточно.
- L131 `binance_tape_volume()` — Вес ленты сделок против свечей — на представителях.
- L161 `bybit_tick_format()` — Есть ли в тиковом архиве Bybit признак ликвидации.
- L181 `binance_agg_format()` — Колонки ленты Binance: есть ли признак принудительного закрытия.
- L201 `main()`

## research/l1_cascades/execution.py · 281 строк

L1 — сколько стоит войти в момент каскада.

- L60 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L61 `RESEARCH = os.path.dirname(HERE)`
- L62 `OUT = os.path.join(HERE, 'out')`
- L63 `CACHE = os.path.join(OUT, 'cache')`
- L70 `S3 = PR.S3`
- L71 `UA = 'l1-execution/1.0'`
- L72 `WORKERS = 8`
- L76 `CELLS = {'1x3': (0.01, 0.03), '2x3': (0.02, 0.0…` — Ячейки, между которыми идёт выбор: мягкая мертва по величине, строгая бедна наблюдениями, середина — единстве…
- L77 `SIZES = (10000, 50000, 200000)`
- L78 `EXIT_MIN = 15`
- L79 `TOL_SEC = 60`
- L80 `BAND = 0.01`
- L83 `day_of(ts)`
- L87 `load_depth(sym, day)` — Снимки глубины за сутки: `(время, нотионал спроса, предложения)`.
- L130 `at_moment(depth, when)` — Последний снимок, сделанный не позже момента. Иначе — пусто.
- L139 `slip_bp(size, notional)` — Проскальзывание в б.п. при равномерном стакане внутри полосы.
- L153 `collect_events(cells, start, end, symbols)` — События по правилам `probe.py`, без второй копии обнаружения.
- L170 `measure(events, sizes)` — Глубина в момент входа и выхода против обычной для того же дня.
- L225 `main()`

## research/l1_cascades/lag.py · 323 строк

L1 — известно ли в момент `t` то, что мы взяли на метке `t`.

- L51 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L52 `RESEARCH = os.path.dirname(HERE)`
- L53 `OUT = os.path.join(HERE, 'out')`
- L54 `CACHE = os.path.join(OUT, 'cache')`
- L62 `S3 = 'https://s3-ap-northeast-1.amazonaws.co…`
- L63 `UA = 'l1-cascade-probe/1.0'`
- L64 `WORKERS = 8`
- L65 `STEP = 300.0`
- L69 `SAMPLE = ('BTCUSDT', 'SOLUSDT', 'ARBUSDT')` — Символы разного размера: соглашение о метке от инструмента зависеть не должно, и если зависит — это само по с…
- L70 `MONTHS = ('2024-07', '2025-03')`
- L76 `days_of(mon)`
- L85 `load_metrics(sym, mon)` — `(время, интерес, отношение объёмов)` по суточным файлам месяца.
- L103 `load_klines(sym, mon)` — `(время открытия, объём, объём агрессивных покупок)`, минутные.
- L122 `ratio_over(kt, vol, buy, t0, t1)` — Отношение агрессивных покупок к продажам за `[t0, t1)`.
- L134 `compare(sym, mon)`
- L163 `spearman(a, b)` — Ранговая корреляция без scipy — связь заведомо не линейна.
- L178 `oi_snapshot_side(sym, mon)` — Снимок интереса — на начале интервала строки или на конце.
- L212 `price_shift(sym, mon)` — Насколько цена «последнего открытого бара» отличается от закрытого.
- L246 `main()`

## research/l1_cascades/probe.py · 463 строк

L1 — как каскад ликвидаций выглядит в данных, и есть ли после него отскок.

- L72 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L73 `RESEARCH = os.path.dirname(HERE)`
- L74 `OUT = os.path.join(HERE, 'out')`
- L75 `CACHE = os.path.join(OUT, 'cache')`
- L83 `S3 = 'https://s3-ap-northeast-1.amazonaws.co…`
- L84 `UA = 'l1-cascade-probe/1.0'`
- L85 `WORKERS = 8`
- L89 `SAMPLE = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPU…` — Выборка: мажоры, средние и мелкие. Каскады у них разной силы, и средним по BTC судить обо всех нельзя.
- L92 `START = '2024-01-01'`
- L93 `END = '2026-06-30'`
- L95 `STEP_MIN = 5`
- L96 `LAG_MIN = 5`
- L97 `WINDOW_MIN = 15`
- L98 `TOL_SEC = 60`
- L99 `OI_DROPS = (0.01, 0.02, 0.03)`
- L100 `MOVES = (0.01, 0.02, 0.03)`
- L101 `FORWARD_MIN = (5, 15, 60, 240, 1440)`
- L104 `months(start, end)`
- L114 `days(start, end)`
- L123 `load_metrics(sym, start, end)` — Открытый интерес по 5-минутной сетке. `metrics` бывает только суточным.
- L147 `load_price(sym, start, end)` — Минутные открытия и закрытия из месячных архивов.
- L186 `align(mt, pt, close, open_, lag_min=LAG_MIN, rule='closed')` — Цена в момент решения. Момент = метка строки + `lag_min`.
- L215 `at_time(t, want, tol=TOL_SEC)` — Индекс точки сетки, стоящей в нужный момент. Иначе −1.
- L235 `scan(sym, oi_t, oi_v, price, oi_drop, move)` — События: интерес упал И цена сдвинулась за одно окно.
- L270 `episodes(events, gap_sec=4 * 3600)` — События, слипшиеся в эпизоды по всем символам сразу.
- L293 `by_episode(events, f)` — Медиана внутри эпизода, потом по эпизодам. Одно окно — один голос.
- L303 `baseline(series, rng_seed=7)` — Безусловная доходность на тех же активах и том же периоде.
- L335 `main()`

## research/l2_data/oi_binance.py · 352 строк

L2 — открытый интерес по всему крипто-универсуму, архив Binance.

- L69 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L70 `RESEARCH = os.path.dirname(HERE)`
- L71 `A1_OUT = os.path.join(RESEARCH, 'a1_universe', '…`
- L72 `OUT = os.path.join(HERE, 'out')`
- L73 `SERIES = os.path.join(OUT, 'oi_binance')`
- L81 `UA = 'l2-oi-binance/1.0'`
- L82 `START = '2024-01-01'`
- L83 `END = '2026-06-30'`
- L84 `WORKERS = 16`
- L87 `universe_symbols()` — Крипто-активы с историей Binance и их интервалы жизни.
- L104 `days_of(intervals, start, end)` — Дни жизни инструмента внутри окна, без дублей и по порядку.
- L116 `collect_symbol(symbol, days, workers)` — Ряд интереса по символу. Возвращает `(массивы, сводка)`.
- L163 `write_json(path, doc)` — Атомарная запись: обрыв не оставляет обрезанного файла.
- L171 `scan_series()` — Состояние — с диска, а не из манифеста.
- L200 `is_done(info, sym, days, start, end)` — Собран ли символ **за нужное окно**, а не просто «файл есть».
- L239 `load_manifest(path)` — Манифест плюс то, что найдено на диске. Диск главнее.
- L256 `main()`

## research/l2_data/oi_bybit.py · 503 строк

L2 — открытый интерес площадки исполнения и проверка её соглашения о метке.

- L49 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `RESEARCH = os.path.dirname(HERE)`
- L51 `A1 = os.path.join(RESEARCH, 'a1_universe')`
- L52 `OUT = os.path.join(HERE, 'out')`
- L53 `SERIES = os.path.join(OUT, 'oi_bybit')`
- L59 `INTERVAL = '5min'`
- L60 `LIMIT = 200`
- L61 `PAUSE_S = 0.05`
- L62 `PROBE_SYMBOLS = ('BTCUSDT', 'SOLUSDT', 'ARBUSDT')`
- L63 `PROBE_DAYS = 20`
- L66 `WINDOW_DAYS = 940` — Окно сбора L2 по Binance: сравнивать площадки можно только на общем периоде, и глубже собирать незачем.
- L67 `STEP_SEC = 300`
- L70 `oi_page(symbol, end_ms, interval=INTERVAL, start_ms=None)` — Страница интереса, назад во времени от `end_ms`.
- L89 `has_data_at(symbol, days_ago, interval=INTERVAL, now_ms=None)` — Есть ли данные примерно `days_ago` суток назад. Один запрос.
- L96 `retention_days(symbol, interval=INTERVAL, now_ms=None)` — Глубина истории — лестницей и уточнением, а не обходом назад.
- L127 `oi_history(symbol, pages_max, interval=INTERVAL, since_days=Non…` — История назад во времени. `since_days` ограничивает глубину.
- L153 `klines(symbol, start_ms, end_ms)` — Пятиминутные бары Bybit: `(время_начала_мс, объём)`.
- L178 `spearman(a, b)`
- L192 `label_profile(symbol, oi_rows)` — Профиль связи изменения интереса с объёмом по сдвигам −2…+2.
- L220 `probe(args)` — Обе проверки площадки. Пишет отчёт в `out/`, а не только в консоль.
- L304 `venue_map()` — Тикер Binance -> тикер Bybit и статус контракта.
- L327 `sample_symbols(n)` — Выборка по размеру инструмента, а не первые по алфавиту.
- L355 `collect(args)` — Ряды интереса по выборке символов.
- L480 `main()`

## research/l2_data/report.py · 192 строк

L2 — отчёт о сборе: что собралось и годится ли это для L3.

- L36 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L37 `RESEARCH = os.path.dirname(HERE)`
- L38 `OUT = os.path.join(HERE, 'out')`
- L39 `SERIES = os.path.join(OUT, 'oi_binance')`
- L44 `EXPLORATORY = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPU…` — Разведочная часть §4 спеки 06. Вердикт по ней не выносится никогда.
- L47 `MIN_OI_USD = 5000000`
- L48 `STEP_MIN = 5`
- L51 `stamp(sec)`
- L55 `load()`
- L64 `pct(v, q)`
- L68 `main()`

## research/l3_events/data.py · 279 строк

L3 — слой данных: цены, открытый интерес и фильтры на общей сетке.

- L53 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L54 `RESEARCH = os.path.dirname(HERE)`
- L55 `A1_OUT = os.path.join(RESEARCH, 'a1_universe', '…`
- L56 `A3_OUT = os.path.join(RESEARCH, 'asset_groups', …`
- L57 `L2_OUT = os.path.join(RESEARCH, 'l2_data', 'out')`
- L58 `OI_SERIES = os.path.join(L2_OUT, 'oi_binance')`
- L59 `OUT = os.path.join(HERE, 'out')`
- L63 `START = '2024-01-01'`
- L64 `END = '2026-06-30'`
- L65 `STEP_SEC = 300`
- L66 `STEP_MIN = 5`
- L67 `LAG_STEPS = 1`
- L70 `EXPLORATORY = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPU…` — Разведочная часть §4 спеки: вердикт по ней не выносится никогда.
- L75 `grid(start=START, end=END)` — Сетка моментов времени в секундах эпохи UTC.
- L84 `months(start=START, end=END)`
- L93 `universe()` — Крипто-активы с историей Binance: тикер -> сведения.
- L109 `price_matrix(symbols, times, interval='1m', log=None, columns=(…` — Первая доступная цена в каждый момент сетки: `(символы × моменты)`.
- L180 `oi_series(symbol, times)` — Открытый интерес символа на сетке: контракты и доллары.
- L208 `liquid_days(interval='1m', min_share=0.9)` — Дни, в которые актив достаточно ликвиден по мере A3.
- L228 `liquidity_mask(symbol, times, share, min_share, window_days=90)` — Маска моментов, где актив прошёл фильтр ликвидности §7.3.
- L266 `delist_mask(symbol, times, uni, guard_days=30)` — Маска моментов вне окна делистинга §7.1.

## research/l3_events/events.py · 231 строк

L3 — отбор событий, эпизоды, нули и контроли. Чистые функции.

- L29 `STEP_MIN = 5`
- L30 `WINDOW_MIN = 15`
- L31 `DEDUP_MIN = 60`
- L32 `EPISODE_SEC = 4 * 3600`
- L33 `CROSS_GUARD_MIN = 60`
- L34 `SHIFT_DAYS = 365`
- L37 `steps(minutes, step_min=STEP_MIN)` — Число шагов сетки в `minutes`. Шаг — параметр, а не константа.
- L48 `detect(oi_c, price, ok, oi_drop, move, require_oi=True, step_mi…` — Индексы моментов, где сработало условие §5.1.
- L91 `forward(price, j, horizon_min, step_min=STEP_MIN)` — Доходность от входа в `j` до выхода через `horizon_min` минут.
- L104 `episodes(times, gap_sec=EPISODE_SEC)` — Номер эпизода для каждого события. События идут по времени.
- L125 `by_episode(values, ep)` — Медиана внутри эпизода, потом по эпизодам: одно окно — один голос.
- L135 `ban_matrix(shape, rows, j_list, guard_min=CROSS_GUARD_MIN, step…` — Кто в какой момент считается «каскадящим» и не входит в фон.
- L178 `cross_section(P, j_list, rows, horizon_min, guard_min=CROSS_GUA…` — Контроль 1: медианный форвард тех, кто в этот момент не каскадил.
- L203 `null_matched_times(valid, j_list, hours, seed, guard_steps)` — Нуль 1: случайные моменты того же актива и того же часа суток.
- L222 `null_shift(j_list, n, shift_days=SHIFT_DAYS)` — Нуль 2: тот же актив, момент сдвинут на год.

## research/l3_events/run.py · 362 строк

L3 — события, эпизоды, нули и контроли. Единственный дорогой проход.

- L32 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L33 `RESEARCH = os.path.dirname(HERE)`
- L34 `OUT = os.path.join(HERE, 'out')`
- L41 `OI_DROP = 0.01` — Объявлено спекой §5.1 и §6, перебору не подлежит.
- L42 `MOVE = 0.03`
- L43 `HORIZONS = (15, 60, 240)`
- L44 `DIAGNOSTIC = (5, 1440)`
- L45 `MIN_OI_USD = 5000000`
- L46 `NULL_SEEDS = 10`
- L49 `stamp(sec)`
- L53 `scan_symbols(symbols, times, P, uni, share, min_share, log, dir…` — Отбор событий по всем символам. Возвращает векторы.
- L96 `measure(rec, arm, times, P, valid_by_row, hours, log)` — Форварды, эпизоды, контроль 1 и оба нуля для одной руки.
- L160 `block(name, res)` — Строки отчёта по одной руке.
- L186 `ratio_cell(a, b)` — Отношение «событие / контроль 2» с честным разбором знаков.
- L201 `verdict(ev, c2)` — Критерий немедленной остановки §9.1 — числом, а не на глаз.
- L256 `main()`

## research/m1_features/build.py · 395 строк

M1: сборка матрицы признаков — этап 1 гипотезы 6 (спека 07).

- L47 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L48 `RESEARCH = os.path.dirname(HERE)`
- L49 `OUT = os.path.join(HERE, 'out')`
- L57 `PARQUET = os.path.join(RESEARCH, 'a2_storage', 'o…`
- L58 `UNIVERSE = os.path.join(RESEARCH, 'a1_universe', '…`
- L59 `FUNDING_DIR = os.path.join(RESEARCH, 'a1_universe', '…`
- L60 `OI_DIR = os.path.join(RESEARCH, 'l2_data', 'out'…`
- L62 `START_DEFAULT = '2022-07-01'`
- L64 `MIN_HISTORY_DAYS = 365` — на площадке исполнения не из чего
- L65 `BARS_PER_DAY = {'1m': 1440, '15m': 96}`
- L68 `connect()` — duckdb с теми же прагмами, что у liquidity.py, — и по той же причине: без явной зоны граница суток зависела б…
- L82 `aggregate_partition(con, path)` — Дневная сводка одной месячной партиции, arrow-таблицей.
- L102 `stage1(interval, log)` — Дневная сводка по всем партициям, с возобновлением по месяцам.
- L157 `load_daily(dst, day0, n_days, symbols)` — Дневная сводка -> матрицы (символ × день).
- L188 `eligibility(universe, assets, day0, n_days)` — Маска «актив в универсуме в этот день»: класс, возраст, интервал.
- L205 `main()`

## research/m1_features/features.py · 287 строк

M1: математика признаков — чистые функции над дневными рядами.

- L33 `DAY_MS = 86400000`
- L34 `DAY_SEC = 86400`
- L37 `RET_WINDOWS = (1, 3, 7, 14, 30)` — Окна, объявленные спекой §4. Менять после просмотра результатов нельзя.
- L38 `PATH_WINDOWS = (7, 14)`
- L41 `TURN_MED_WIN = 30`
- L44 `MIN_SECTION = 10`
- L45 `HORIZONS = (1, 5)`
- L48 `daily_returns(close)` — Дневные доходности; NaN, если нет любого из двух закрытий.
- L55 `_trailing(x, win, min_n, fn)` — Скользящее окно, кончающееся текущим днём. Только назад.
- L74 `trailing_std(x, win, min_n)`
- L78 `trailing_mean(x, win, min_n)`
- L82 `trailing_median(x, win, min_n)`
- L86 `trailing_sum_abs(x, win, min_n)`
- L91 `ret_k(close, k)` — Доходность за k дней; NaN без любого из закрытий-концов.
- L98 `ret_norm(close, k, sigma_long)` — Доходность за k дней в единицах собственной σ, растянутой на k.
- L109 `net_over_path(close, r, k, min_frac=0.8)` — «Чистое/путь» за k дней — та же величина, что в `path_norm`.
- L124 `wave_excl_self(r, elig)` — Рыночная волна для каждого актива — среднее ПО ОСТАЛЬНЫМ.
- L143 `rolling_beta(r, w, win=BETA_WIN, min_n=BETA_MIN)` — β актива к волне по скользящему окну, только назад.
- L171 `funding_daily(t_ms, rates, day0_ms, n_days)` — Начисления funding по календарным дням: (сумма б.п., число).
- L190 `sign_stability(x, win, min_n)` — Доля положительных среди последних `win` наблюдений.
- L196 `oi_daily(t_sec, oi_usd, day0_sec, n_days, lag_sec=300)` — Открытый интерес на конец дня — по моменту, когда он ИЗВЕСТЕН.
- L216 `rel_change(x, k)` — Относительное изменение за k дней; NaN без любого из концов.
- L225 `forward_residual(close, r, elig, beta, h)` — Цель обучения: форвард за h дней СВЕРХ рыночной волны, в б.п.
- L241 `feature_pack(close, turnover, traded_share, elig, fund_bp=None,…` — Все признаки спеки §4 разом: `{имя: матрица (символы, дни)}`.

## research/m1_features/report.py · 78 строк

Отчёт M1 из готовой сводки. Стандартная библиотека намеренно: отчёт обязан собираться на любой машине из само…

- L15 `render(s)`
- L72 `main()`

## research/m2_walkforward/gbm.py · 285 строк

M2: градиентный бустинг деревьев на numpy — модель спеки 07 §3.

- L37 `DEPTH = 3`
- L38 `N_TREES = 200`
- L39 `LEARNING_RATE = 0.05`
- L40 `SUBSAMPLE = 0.8`
- L42 `N_BINS = 31`
- L43 `MIN_LEAF = 20`
- L46 `bin_edges(x_train, n_bins=N_BINS)` — Границы корзин по квантилям обучающей выборки, на каждый признак.
- L58 `bin_apply(x, edges)` — Коды корзин: 0 — пропуск, 1..B — интервалы между границами.
- L70 `_histograms(codes_sub, g_sub, n_cats)` — Суммы градиента и счётчики по корзинам всех признаков разом.
- L87 `_best_split(hg, hn)` — Лучший разрез по гистограммам: (признак, порог, NaN-влево, gain).
- L118 `_go_left(col, thr, nan_left)`
- L122 `_grow(codes, g, idx, depth, importance, leaf=None)` — Дерево по псевдоостаткам `g`.
- L153 `_tree_predict(node, codes, idx, out)`
- L170 `class GBM` — Обученная модель: границы корзин, деревья, базовый уровень.
  - L173 `GBM.__init__(self, edges, trees, base, importance)`
  - L179 `GBM.predict(self, x)`
  - L182 `GBM.predict_codes(self, codes)`
  - L191 `GBM.contrib(self, x)` — Вклад каждого признака в предсказание КАЖДОЙ строки.
- L237 `fit(x, y, seed, n_trees=N_TREES, tau=None)` — Обучение. `seed` обязателен и выводится вызывающим из номеров — урок R3: зерно, которое нельзя воспроизвести,…

## research/m2_walkforward/report.py · 123 строк

Отчёт M2 из готовой сводки. Стандартная библиотека намеренно (урок R1): отчёт собирается на любой машине из с…

- L13 `_f(v, d=4)`
- L17 `render(s)`
- L117 `main()`

## research/m2_walkforward/run.py · 331 строк

M2 — пилот-гейт гипотезы 6 (спека 07 §10): walk-forward по сетке из 8 ячеек, модель против одиночного признак…

- L36 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L42 `RESEARCH = os.path.dirname(HERE)`
- L43 `MATRIX = os.path.join(RESEARCH, 'm1_features', '…`
- L44 `OUT = os.path.join(HERE, 'out')`
- L46 `META = ('day', 'asset')`
- L47 `NOT_FEATURES = ('target_1', 'target_5', 'fwd_1', 'fwd_…`
- L48 `NULL3_STOP = 0.01`
- L49 `FIXED_BASELINE = 'ret_7'`
- L52 `log(m)`
- L56 `load_matrix(path)`
- L73 `main()`
- L277 `est_total_fits(n_eval, null_seeds)`
- L283 `verdict(s)`
- L309 `finish(summary, tag, t_all, fit_times)`

## research/m2_walkforward/wf.py · 230 строк

M2: каркас walk-forward — чистая математика без чтения с диска.

- L36 `EVAL_START = '2024-07-01'`
- L37 `MIN_IC_PAIRS = 10`
- L38 `SEED0 = 20260731`
- L40 `FREQ_DAYS = {'day': 1, 'week': 7, 'month': 30, 'sta…`
- L41 `CELLS = [(h, f) for h in (1, 5) for f in ('stat…`
- L44 `cell_name(h, freq)`
- L48 `fit_seed(cell_idx, fit_idx)` — Зерно обучения из номеров — урок R3: зерно, которое нельзя воспроизвести, делает нулевую модель непроверяемой.
- L54 `null3_seed(h, seed_idx)`
- L58 `rankdata(v)` — Ранги 1..n со средними на ничьих. Ничьи здесь не экзотика: funding-признаки совпадают побитово у многих актив…
- L76 `spearman(a, b)`
- L89 `day_slices(day_idx)` — Границы сечений в отсортированной по дню таблице: (день, lo, hi).
- L97 `ic_by_day(x, y, slices)` — IC каждого признака в каждом сечении: (дни, признаки).
- L107 `shuffle_within_sections(y, slices, seed)` — Нуль 3: цели перемешиваются ВНУТРИ сечения. Мультимножество дня сохраняется — рвётся только связь «какой акти…
- L118 `shuffle_global(y, seed)` — Различитель для нуля 3: перестановка целей по ВСЕЙ истории.
- L134 `train_rows(day_ord, fit_ord, h)` — Строки, чей форвард целиком известен до дня обучения.
- L139 `fit_schedule(eval_ords, freq_days)` — Номера оценочных дней, перед которыми модель переобучается. Статическая рука обучается один раз, перед первым…
- L152 `run_cell(x, y, day_ord, slices, eval_idx, h, freq_days, fit_fn,…` — Walk-forward одной ячейки.
- L178 `single_feature_arm(ic_mat, day_ords, eval_idx, h, freq_days)` — Рука одиночного признака тем же walk-forward.
- L207 `stats(ic_list)` — Сводка по ряду IC непересекающихся сечений.
- L223 `nonoverlap(eval_idx, h)` — Каждое h-е оценочное сечение — статистика без перекрытия форвардов (урок R2).
- L229 `parse_day(s)`

## research/mech_994fc54f/bid_survives.py · 929 строк

Механика 994fc54f — поглощение после падения со ЗНАМЕНАТЕЛЕМ.

- L69 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L70 `RESEARCH = os.path.dirname(HERE)`
- L71 `OUT = os.path.join(HERE, 'out')`
- L85 `DROP = 0.03` — --- объявлено ДО прогона, после результата не меняется ----------------
- L86 `HORIZON_SEC = 30 * 60`
- L87 `MARK_DELAY_SEC = 5`
- L88 `T_SEC = 60`
- L89 `DECLARED_ENTRY_SEC = 60`
- L90 `NEED_BP = 52.2`
- L91 `SHARE_POS_MIN = 0.6`
- L92 `MIN_EPISODES = 300`
- L93 `NULL_PERMS = 200`
- L94 `NULL_SEED = 20260905`
- L95 `MAX_BITE = SB.PL.MAX_BITE`
- L96 `MIN_TRADE_DAY_SHARE = 0.33`
- L97 `MAX_LIVE_CORR = CE.MAX_CORR`
- L98 `EXPECTED_LIVE_CORR = 0.3`
- L99 `SLOTS = 6`
- L100 `NAME_CAP = 0.1`
- L101 `DIAG_T_SEC = (15, 30)`
- L102 `DIAG_HORIZONS = (5 * 60, 15 * 60)`
- L103 `DIAG_DROP = 0.05`
- L104 `BTC = 'BTCUSDT'`
- L106 `LABELS = ('пережил', 'выеден')`
- L107 `DAY_SEC = 86400`
- L110 `entry_wait(mark_delay=MARK_DELAY_SEC, t_sec=T_SEC, declared=DEC…` — Через сколько секунд после решения возможен вход.
- L123 `ENTRY_SEC = entry_wait()`
- L126 `flow_through(tt, tp, tv, tside, t_place, limit, t_sec=T_SEC)` — Продающая агрессия сквозь уровень `limit` за `t_sec` секунд.
- L146 `mark_event(tt, tp, tv, tside, j, limit, queue, size, t_sec=T_SE…` — Метка события: `пережил` либо `выеден`, и когда именно выеден.
- L160 `level_pulled(flow, limit, bid_after)` — Уровень ушёл, не приняв ни одного принта.
- L177 `bg_mean(P, NXT, row, j, delay, hor, banned, min_cross=D.MIN_CRO…` — Фон РАВНОВЗВЕШЕННЫМ средним, рядом с медианой D1.
- L200 `_episode_values(rows, key)` — Значения ключа по эпизодам: одно рыночное окно — один голос.
- L211 `group_stats(rows, key='exc_med')` — Сводка подмножества: медиана и среднее ПО ЭПИЗОДАМ.
- L236 `by_label(rows, field='label', key='exc_med')` — Сводка по обеим меткам разом.
- L242 `ceiling_bp(split)` — Верхняя граница: лучшее подмножество ПРИ ИДЕАЛЬНОМ ЗНАНИИ.
- L257 `null_permutation(rows, key='exc_med', perms=NULL_PERMS, seed=NU…` — Нуль: метка переставляется между событиями ТЕХ ЖЕ суток.
- L294 `_by_day(rows)`
- L301 `replay_days(rows, key='own', cost_bp=None, slots=SLOTS, name_ca…` — Книга по дням: `{номер суток: нетто в % капитала}`.
- L331 `form_stats(daily)` — Форма книги по суткам — ОБЩЕЙ мерой проекта.
- L345 `trade_day_share(daily, days_total)` — Доля суток записи, в которые книга хоть раз закрывала сделку.
- L357 `live_corr(daily, path)` — Связь дневных денег реплея с живыми книгами пула.
- L392 `measure_day(root, syms, day, jobs, last_seen, log=print)` — События суток с меткой поглощения и превышением по ячейкам.
- L497 `summarise(rows, days_total, live_path)` — Все числа отчёта. Порядок — от самого дешёвого убийцы к прочим.
- L550 `diagnostics(rows)` — Ячейки, которые считаются рядом и предъявлять которые запрещено.
- L572 `killers(art)` — Пять убийц заявки. Каждый выводится из числа, а не из надежды.
- L632 `reading(art)` — Вывод одной фразой. Выводится из числа, а не стоит рядом с ним.
- L669 `_num(v, fmt='+.1f')` — Величины, которой нет, — прочерк. Ноль означает «измерено».
- L674 `_split_table(L, split, title)`
- L689 `report(art, path)`
- L789 `write_status(out, tag, status)` — Состояние прогона отдельным файлом, атомарно, после каждых суток.
- L798 `_LAST = {}`
- L801 `main()` — Точка входа. Падение обязано САМО СЕБЯ доложить.
- L822 `_run()`

## research/mech_994fc54f/controls_check.py · 93 строк

Машина негативных контролей механики 994fc54f.

- L28 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L30 `SUITE = 'research/mech_994fc54f/test_bid_surviv…`
- L33 `sha(p)`
- L37 `run()` — Код возврата и ИМЕНА упавших проверок, а не только код.
- L52 `main(report)`

## research/mech_fcbd3542/run_halves.py · 1311 строк

Механика `fcbd3542` — отскок первых секунд по половинам универсума.

- L92 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L93 `RESEARCH = os.path.dirname(HERE)`
- L94 `OUT = os.path.join(HERE, 'out')`
- L113 `NULL_PERMS = 200` — --- объявлено ДО прогона --------------------------------------------
- L114 `NULL_SEED = 20260904`
- L116 `SLOTS = 6` — проверяемым не является (урок R3)
- L117 `HEDGE_SYMBOL = 'BTCUSDT'`
- L118 `CACHE = os.path.join(HERE, '.cache_ann')`
- L127 `excess_both(P, NXT, row, j, delay_sec, horizon_sec, banned, hed…` — Превышение над сечением ОБЕИМИ статистиками фона.
- L162 `measure_halves(P, NXT, rows, cols, t0, cells, hedge_row=None, l…` — Замер всех ячеек. Порядок ячеек — по ширине защитного окна.
- L190 `_MONTH_CACHE = {}`
- L193 `month_of(ts)` — Месяц события в UTC — то, чем метка привязана к имени.
- L211 `episode_stats(rec, col)` — Статистика столбца по ЭПИЗОДАМ, а не по событиям.
- L236 `half_of(labels, month, sym)` — Половина имени НА МЕСЯЦ события.
- L247 `split_records(rec, syms, labels)` — Разложить записи по половинам месяца события.
- L262 `half_stats(rec, syms, labels)` — Полная сводка по половинам для одной ячейки сетки.
- L282 `index_records(rec, syms, col=I_EXCM)` — Разложить записи один раз, чтобы нуль не делал это двести.
- L307 `_median_of(idx, want)` — Медиана по эпизодам среди записей, чей ключ в `want`.
- L320 `_half_median(rec, syms, want, col=I_EXCM)` — То же одним вызовом — для мест, где перестановок нет.
- L325 `permutation_null(rec, syms, labels, perms=NULL_PERMS, seed=NULL…` — Нуль: метка `ticksig` переставлена МЕЖДУ ИМЕНАМИ внутри месяца.
- L382 `turnover_control(rec, syms, labels)` — Разрез по `ticksig` ВНУТРИ половин по обороту.
- L421 `book_trades(rec, syms, want, delay_sec, horizon_sec, ring_bp, s…` — Сделки книги: шесть мест, одна позиция на имя, вход по времени.
- L458 `book_days(trades, cap_share=None)` — Дневной ряд книги в ПРОЦЕНТАХ капитала и его устойчивость.
- L476 `require_events(rec, days, symbols)` — Ноль наблюдений при непустом входе — ОТКАЗ, а не отчёт.
- L493 `active_share(pct, record_days)` — Доля суток записи хотя бы с одной закрытой сделкой.
- L507 `synthetic(n_event=40, n_quiet=90, n_sec=20000, rebound=0.02, pl…` — Подставной день: половина имён отскакивает, половина нет.
- L554 `calibrate(planted=True, seed=7, **kw)` — Прогнать пару на подставном дне. Возвращает разность половин.
- L587 `TICK_CHANGE_HINT = 'tick size'`
- L590 `announcements(cache=CACHE)` — Объявления площадки. Отдельной функцией, чтобы её подменяли.
- L608 `tick_change_symbols(known, path=None, cache=CACHE, fetch=None)` — Имена, у которых площадка меняла шаг цены 11.08.2026.
- L638 `tick_change_at()` — Момент смены шага цены, объявленный заявкой: 11.08.2026 08:30 UTC.
- L643 `_median_mask(t, v, mask)` — Медиана по эпизодам под маской. Пусто — «не измерено».
- L653 `tick_change_experiment(rec, syms, changed, at_ts=None, col=I_EX…` — Естественный эксперимент: имена со сменой шага против соседей.
- L682 `killers(art)` — Условия, каждое из которых закрывает заявку. Фразы ИЗ ЧИСЕЛ.
- L764 `FACTORY_DAY = os.path.join(RESEARCH, 'factory', 'out'…`
- L767 `link_to_pool(pct, path=FACTORY_DAY)` — Связь дневных денег реплея с кандидатами пула.
- L808 `fmt(x, plus=True)`
- L814 `report(art, path)`
- L1051 `_LAST = {}`
- L1054 `write_status(out, tag, status)` — Состояние прогона отдельным файлом, атомарно и ПОСЛЕ КАЖДЫХ суток.
- L1067 `build_labels(months, syms, con=None, min_obs=TS.MIN_OBS)` — Метки по месяцам записи. Возвращает `{месяц: {...}}`.
- L1100 `main()`
- L1120 `_run()`

## research/mech_fcbd3542/ticksig.py · 346 строк

tick/σ — шаг цены в единицах волатильности, метка на имя-месяц.

- L65 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L66 `RESEARCH = os.path.dirname(HERE)`
- L72 `UNIVERSE = os.path.join(RESEARCH, 'a1_universe', '…`
- L73 `INSTRUMENTS = os.path.join(RESEARCH, 'a1_universe', '…`
- L74 `PARQUET = os.path.join(RESEARCH, 'a2_storage', 'o…`
- L77 `LOOKBACK_D = 30` — --- объявлено ДО прогона --------------------------------------------
- L78 `MIN_OBS = 20`
- L82 `DDOF = 1` — Две трети окна. Ниже этого σ по горсти дней описывает не имя, а несколько его дней; выше — окно теряло бы све…
- L90 `MEMORY_SHARE = 0.15` — Доля физической памяти под DuckDB. У соседей 0.55; здесь меньше намеренно и заметно: рядом идёт запись стакан…
- L92 `_LEAD = re.compile('^(\\d+)')`
- L93 `_TRAIL = re.compile('(\\d+)(?:USDT|USD|USDC|PERP…`
- L96 `name_multiplier(symbol)` — Множитель контракта, вытащенный из ИМЕНИ.
- L114 `price_scale(bybit_symbol, binance_symbol)` — Во сколько раз цена на Bybit больше цены на Binance.
- L128 `load_universe(path=UNIVERSE)` — Отображение символов Bybit в символы Binance.
- L140 `load_ticks(path=INSTRUMENTS)` — Шаг цены по справочнику площадки исполнения.
- L155 `window(month, days=LOOKBACK_D)` — Окно метки для месяца `YYYY-MM`: `[начало − days, начало)`.
- L167 `connect(share=MEMORY_SHARE, tmp=None)` — Своё подключение к DuckDB со своим временным каталогом.
- L189 `closes_loader(con, interval='1m')` — Загрузчик суточных закрытий из хранилища A2.
- L209 `turnover_loader(con, interval='1m')` — Загрузчик подневного оборота из хранилища A2.
- L241 `sigma_of(closes, ddof=DDOF)` — σ суточных доходностей ряда закрытий. `None` — меры нет.
- L257 `label_one(tick, closes, scale, turnover=None, min_obs=MIN_OBS)` — Метка одного имени. Всегда возвращает словарь с полем `why`.
- L302 `build(month, symbols, load_closes, load_turnover=None, ticks=No…` — Метки всех имён на месяц. Возвращает `(метки, окно)`.
- L331 `halves(labels, key='ticksig')` — Деление имён пополам по медиане `key`. Только размеченные.

## research/ops/book_days_probe.py · 62 строк

Дневная разбивка книг — числами, прямо с диска сервера.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L23 `main()`

## research/ops/diag.py · 117 строк

Снимок состояния сервера: почему что-то не работает.

- L20 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L21 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L25 `LOGS = (('цикл обучения', 'research/s8_loop/ou…` — Что смотреть. Список объявлен, а не собирается по маске: иначе однажды сюда попадёт файл с ключами.
- L32 `PROCS = ('b1_book/collect.py', 's8_loop/train.p…`
- L34 `STAMPS = (('манифест модели', 'research/s8_loop/…`
- L42 `tail(path, n)`
- L53 `age(path)`
- L61 `run(cmd)`
- L70 `main()`

## research/ops/live_report.py · 103 строк

Что происходило у живого исполнителя: журнал сделок с временем.

- L18 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L19 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L20 `JOURNAL = os.path.join(ROOT, 'bot', 'out', 'live')`
- L23 `rows()` — Записи журнала по всем суточным файлам, по возрастанию времени.
- L42 `when(ms)`
- L48 `main()`

## research/paper_monthly/book.py · 658 строк

Бумажная месячная книга: запись решений вперёд, разбор через 30 дней.

- L63 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L64 `RESEARCH = os.path.dirname(HERE)`
- L65 `OUT = os.path.join(HERE, 'out')`
- L66 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L98 `RULES = PJ.RULES` — --- конструкция, объявлена до первого прогона ------------------------ Живёт в `paper_journal.py` — стандартн…
- L99 `K_DAYS = PJ.K_DAYS`
- L100 `H_DAYS = PJ.H_DAYS`
- L101 `FORM_DAYS = PJ.FORM_DAYS`
- L102 `WIDTH = PJ.WIDTH`
- L103 `STEP = '1h'`
- L104 `BARS_PER_DAY = 24`
- L105 `TAKER_BP = PJ.TAKER_BP`
- L106 `TURNOVER = PJ.TURNOVER`
- L107 `COST_BP = PJ.COST_BP`
- L108 `MIN_ASSETS = 30`
- L109 `MODEL = 'market'`
- L110 `START = '2026-08-01'`
- L111 `AHEAD_TOL_SEC = PJ.AHEAD_TOL_SEC`
- L113 `DEC = os.path.join(OUT, 'decisions.jsonl')`
- L114 `RES = os.path.join(OUT, 'resolutions.jsonl')`
- L126 `append_jsonl(path, rec)`
- L134 `archive_journal(reason, out=None)` — Отставить журнал целиком, назвав причину.
- L159 `note(why, reason)` — Счётчик причины отказа. Пустой прогон обязан объяснять себя.
- L170 `storage_span(interval='1m')` — Первая и последняя партиция хранилища A2 — как есть на диске.
- L188 `build(con, at, liq, universe, of_group, forward, why=None)` — Сечение даты `at`: β, сигнал и — при `forward` — исход.
- L284 `pick(names, beta, sig, width=WIDTH)` — Дециль по сигналу: веса, Σ|w| = 1, ноги равновзвешены внутри.
- L306 `decide(con, at, liq, universe, of_group, why=None)` — Решение даты `at`. Данных после `at` не касается вовсе.
- L324 `resolve(con, rec, liq, universe, of_group, funding=None)` — Разбор транша `rec`: исход по ногам, издержки, funding, нетто.
- L388 `catchup(con, liq, universe, of_group, funding, start=START, end…` — Досчитать всё, чего нет в журнале: решения и созревшие разборы.
- L440 `newey_west_t(vals, lag)` — t с поправкой Ньюи–Уэста. Общая с `probe_monthly/robust.py`.
- L447 `summarise(decisions, resolutions)` — Свод: честное и восстановленное — ОТДЕЛЬНО, всегда.
- L503 `verdict_phrase(sm)` — Фраза выводится ИЗ чисел, и честная группа названа первой.
- L523 `report(art, path)`
- L605 `main()`

## research/paper_monthly/paper_journal.py · 161 строк

Журнал бумажной месячной книги: чтение и правила — на стандартной библиотеке, без numpy и duckdb.

- L25 `RULES = 1` — --- конструкция (объявлена до первого прогона книги) ------------------
- L26 `K_DAYS = 14`
- L27 `H_DAYS = 30`
- L28 `FORM_DAYS = 90`
- L29 `WIDTH = 0.1`
- L30 `TAKER_BP = 5.5`
- L31 `TURNOVER = 2.0`
- L32 `COST_BP = TURNOVER * TAKER_BP`
- L41 `AHEAD_TOL_SEC = 2 * 86400` — Решение считается записанным ВПЕРЁД, если попало в журнал не позже чем через двое суток после даты сечения. Д…
- L44 `ms(day)` — Полночь UTC даты в миллисекундах.
- L55 `shift(day, n)`
- L59 `today()`
- L63 `read_jsonl(path)`
- L75 `ahead(rec)` — Записано ли решение ВПЕРЁД, до начала форвардного окна.
- L87 `tranches(decisions, resolutions, now=None, h_days=H_DAYS)` — Сопоставить решения с разборами — по одной строке на транш.
- L132 `leg_rows(dec, res=None)` — Ноги транша: состав решения плюс исход, когда он есть.

## research/probe_agree/agree.py · 284 строк

Зонд согласия рук: решение, взятое ОБЕИМИ руками, против взятого одной.

- L43 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L44 `RESEARCH = os.path.dirname(HERE)`
- L45 `OUT = os.path.join(HERE, 'out')`
- L54 `MIN_CELL = 30`
- L55 `PERMS = 1000`
- L56 `SEED = 20260831`
- L59 `log_(m)`
- L63 `pick_keys(mdir)` — Множество (час, имя, сторона) по КАЖДОЙ руке — из выборов.
- L81 `flag_rows(rows, keys)` — Флаг согласия на закрытой строке: ДРУГАЯ рука тоже выбирала.
- L90 `day_of(ts)`
- L94 `_delta(nets_a, nets_s)`
- L100 `perm_p(trades, delta_obs, perms=PERMS, seed=SEED)` — Односторонний перестановочный p: согласие лучше случайного разбиения тех же дней. Флаги тасуются ВНУТРИ дня,…
- L123 `cell_stats(trades)` — Числа одной ячейки (книга × рука). Меньше MIN_CELL в любой группе — ячейка не измерена, а не нулевая.
- L170 `reading(cells_out)`
- L190 `write_report(path, cells_out, obs_out, meta)`
- L239 `main(argv=None)`

## research/probe_agree/basket_agree.py · 422 строк

Вопрос владельца (2026-08-31): как повели бы себя КОРЗИННЫЕ книги 24 ч на согласных ногах?

- L63 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L64 `RESEARCH = os.path.dirname(HERE)`
- L65 `OUT = os.path.join(HERE, 'out')`
- L78 `CELL = {'take': 0.05, 'floor': 0.05, 'age_h': …` — Правило живой книги h24c: цель, предел (доли капитала), возраст.
- L79 `SEEDS = tuple(range(1, 11))`
- L80 `OTHER = {'gbm': 'nn', 'nn': 'gbm'}`
- L83 `log_(m)`
- L87 `hour_str(ts)`
- L92 `agreed_picks(picks, keys)` — Пересечение голов: нога остаётся, если ту же (имя, сторону) в тот же час выбрала и другая голова. Ключи — `ag…
- L108 `null_picks(picks, agreed, seed)` — Случайное подмножество ТОЙ ЖЕ ширины по каждому часу.
- L133 `leg_rule(invest)` — Размер ноги: живой `LEG_USD` либо полный капитал по часам.
- L150 `name_stats(by)` — Сколько РАЗНЫХ имён в ногах и как они сгущены.
- L171 `run_arm(by, mids, leg_usd=BB.LEG_USD)`
- L176 `verdict(agr, nulls)` — Вердиктовая фраза выводится из числа, а не стоит рядом.
- L195 `fmt(v, spec='+.2f', dash='—')`
- L199 `null_summary(nulls)`
- L213 `write_report(path, res, meta)`
- L324 `main(argv=None)`

## research/probe_agree/basket_width.py · 452 строк

Вопрос владельца (2026-08-31): «а если корзину только из согласных, но шире — по 12 ног?»

- L72 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L73 `RESEARCH = os.path.dirname(HERE)`
- L74 `OUT = os.path.join(HERE, 'out')`
- L85 `WIDTHS = (6, 12, 20, 30)`
- L86 `CELL = BA.CELL`
- L87 `SEEDS = BA.SEEDS`
- L88 `HOLD_H = 24`
- L89 `BRIDGE_MIN = 0.9`
- L96 `MIN_HOURS = 3 * HOLD_H` — Часов сечения на руку, ниже которых мерить нечего: корзина живёт до 24 ч, и на истории короче трёх её жизней…
- L99 `log_(m)`
- L103 `load_sections(mdir_model, target)` — Полное сечение часа из `preds.jsonl`: {рука: {ts: [(имя, прогноз)]}}.
- L123 `pick_n(row, n, floor_bp)` — Топ-n/2 с каждого конца сечения — правило книги дословно.
- L148 `priced(legs, mids, ts, last)` — Цена входа — середина часа решения (конвенция книг со сроком).
- L163 `build(sections, n, floor_bp, mids)` — Состав всех часов заданной ширины, по рукам.
- L174 `bridge(built6, recorded)` — Доля часов, где состав из сечения совпал с записанным выбором.
- L193 `leg_usd(n, capital=BB.CAPITAL)` — Нога ширины: капитал делится на объявленные слоты N × 24.
- L198 `run_arm(by, mids, n)`
- L203 `legs_per_hour(by)`
- L209 `fmt(v, spec='+.2f', dash='—')`
- L213 `cell_row(name, c, extra='')` — Строка ячейки.
- L232 `write_report(path, res, meta)`
- L308 `write_short(path, per_arm, hours, target)` — Отчёт-диагноз: почему замер не состоялся.
- L342 `main(argv=None)`

## research/probe_agree/drain.py · 212 строк

Вопрос владельца (2026-08-31): пережили ли СОГЛАСНЫЕ сделки слив 08-24…27 так же, как книги целиком?

- L31 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L32 `RESEARCH = os.path.dirname(HERE)`
- L33 `OUT = os.path.join(HERE, 'out')`
- L43 `DRAIN = ('2026-08-24', '2026-08-27')`
- L44 `MIN_GRP = 10`
- L47 `log_(m)`
- L51 `date_of(ts)`
- L56 `in_drain(ts)`
- L61 `grp_stats(rows)` — Числа одной группы: сделок, средний б.п., сумма $, худшее имя.
- L76 `split_cell(rows)` — Ячейка → окно слива и остальное, каждая часть по группам.
- L101 `by_day_table(rows, days)`
- L111 `fmt_bp(v)`
- L115 `fmt_p(v)`
- L119 `write_report(path, cells, day_rows, meta)`
- L162 `main(argv=None)`

## research/probe_basket/basket.py · 542 строк

Реплей корзины БЕЗ отдельных выходов: одна цель, один предел, всё закрывается только разом.

- L63 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L64 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L75 `CAPITAL = 3000.0`
- L76 `LEG_USD = CAPITAL / 144.0`
- L77 `TAKES = (0.025, 0.05, 0.1, 0.2)`
- L78 `FLOORS = (0.025, 0.05, 0.1, 0.2, None)`
- L79 `NAME_CAP = TR.NAME_CAP_SHARE * CAPITAL`
- L80 `COST = TR.ROUND_COST_BP / 10000.0`
- L81 `HOUR = 3600`
- L91 `AGES = (None, 24, 48)` — Вторая серия (вопрос владельца): лимит ВОЗРАСТА корзины и правило «один минус в день». Оси объявлены до прого…
- L92 `ONE_LOSS = (False, True)`
- L95 `log_(m)`
- L99 `hour_ts(hour)`
- L104 `load_picks(mdir)` — Ноги выборов по (руке, часу): sym, side, px.
- L122 `mid_at(mids, sym, ts, last)` — Середина часа с переносом последней известной.
- L139 `replay(picks, mids, take, floor, capital=CAPITAL, leg_usd=LEG_U…` — Одна ячейка: корзина закрывается ТОЛЬКО целиком.
- L280 `baseline(s8, t0, t1)` — Факт живой h24 (свои выходы по сроку) за то же окно.
- L292 `fmt(v, spec='+.2f', dash='—')`
- L298 `write_report(path, cells, base, meta)`
- L357 `VARIANTS = [(a, o) for o in ONE_LOSS for a in AGES]`
- L360 `vlabel(age, ol)`
- L365 `total_of(c)`
- L369 `med(vals)`
- L377 `write_rules_report(path, arms, base_fact, meta)` — arms: {arm: {(age, ol): {(take, floor): cell}}}.
- L455 `main(argv=None)`

## research/probe_calm_exec/probe.py · 489 строк

Зонд пассивного входа в СПОКОЙНОМ рынке.

- L54 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L55 `RESEARCH = os.path.dirname(HERE)`
- L56 `OUT = os.path.join(HERE, 'out')`
- L67 `SIZE_USD = 300.0` — --- объявлено до прогона ---------------------------------------------
- L69 `WAITS = (60, 300, 900)` — живых книг, а не про спеку 11 (там было $5000)
- L70 `HORIZON_SEC = 3600`
- L71 `STATE_SEC = 3600`
- L72 `Z_EDGES = (-1.0, -0.25, 0.25, 1.0)`
- L73 `BAND_NAMES = ('падал ≥1σ', 'падал', 'спокойно', 'рос…`
- L74 `CALM_BAND = 2`
- L75 `MIN_SIGMA_OBS = 48`
- L76 `SNAP_TOL = 5`
- L77 `REF_TOL = 60`
- L78 `ARMS = ('на лучшей', 'на середине')`
- L79 `SIDES = (1, -1)`
- L80 `DEFAULT_START = '2026-08-04'`
- L81 `DEFAULT_TAKE = 38`
- L83 `MAKER_BP = PV.MAKER_BP`
- L84 `TAKER_BP = PV.TAKER_BP`
- L87 `day_hours(day)` — 27 ключей часов: последний час прошлых суток + 24 + 2 следующих.
- L100 `band_of(z)` — Полоса состояния по z; границы — Z_EDGES.
- L109 `pick_symbols(root, take)` — Срез имён: пересечение книги и ленты, минус не-крипто.
- L135 `eval_moment(mid, bid, ask, bsz, asz, nxt, tt, tp, tv, tside, i0…` — Выгода пассивной руки против тейкера в одном моменте.
- L172 `measure_symbol(root, sym, days, counters, min_obs=None, size_us…` — События одного имени за все сутки. σ копится причинно.
- L248 `_ep_median(vals, hours)` — Медиана И среднее почасовых медиан: час — один голос.
- L263 `summarise(events)` — Свод по ячейкам (сторона, полоса, T, рука).
- L295 `headline(events)` — Главная ячейка сводки, объявлена до прогона: полоса «спокойно», T = 60 с, рука «на лучшей», обе стороны вмест…
- L319 `verdict_phrase(h)` — Фраза выводится ИЗ числа, а не стоит рядом с ним (урок Z2).
- L338 `report(art, path)`
- L415 `main()`

## research/probe_corr/corr_probe.py · 320 строк

Зонд корреляции: навык модели у «скоррелированных» и «своей жизнью».

- L56 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L57 `RESEARCH = os.path.dirname(HERE)`
- L58 `OUT = os.path.join(HERE, 'out')`
- L67 `R = importlib.util.module_from_spec(_spec)`
- L73 `CORR_W = 90`
- L74 `CORR_MIN = 60`
- L75 `MIN_WAVE = 30`
- L76 `CORR_REGIMES = [('mkt_corr', 'корреляция с волной рынк…`
- L79 `VECTORS = ('vectors_h5_day.npz', 'vectors_h1_day.…`
- L82 `log_(m)`
- L86 `load_daily(dir_)` — Дневные закрытия из сводки M1: (дни, символы, матрица закрытий).
- L114 `log_returns(close)` — Дневные лог-доходности: только между соседними днями сетки.
- L123 `corr_series(r_i, wave_sum, wave_cnt, q_ix)` — Корреляция актива с волной БЕЗ СЕБЯ в заданные дни.
- L153 `build_corr_column(cols, daily_dir, log=log_, uni=None)` — Колонка `mkt_corr`, выровненная со строками матрицы M1.
- L197 `judge(cols, pred, key, log=log_)` — Суд машиной зонда режимов. Признак непрерывный — нуль прежний (равные случайные трети; matched нужен только д…
- L210 `reading(rows)` — Фраза вывода — из чисел (правило: вердикт выводится, а не стоит рядом).
- L231 `write_report(path, blocks, meta)`
- L272 `main(argv=None)`

## research/probe_dow/dow.py · 309 строк

Зонд дней недели: есть ли смысл торговать только в определённые дни.

- L50 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L51 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L62 `SEED = 20260829`
- L63 `PERMS = 2000`
- L64 `CELLS = ((7, 1), (14, 1))`
- L65 `WIDTH = 0.1`
- L66 `DAYS_RU = ('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'в…`
- L67 `WEEKEND = (5, 6)`
- L70 `log_(m)`
- L74 `dow_of(date_str)` — День недели UTC-даты ребаланса, 0=понедельник … 6=воскресенье.
- L80 `per_date(vec, k, h)` — IC и спред дециля по каждой дате ребаланса — ядром R2.
- L102 `by_dow(rows, field)`
- L109 `family_null(rows, field, perms=PERMS, seed=SEED)` — Планка семейственная: максимум отклонения дня под нулём.
- L146 `live_books(s8)` — Живой разрез по дням недели — анекдот, и это сказано числом дат.
- L169 `write_report(path, cells, live, meta)`
- L233 `main(argv=None)`

## research/probe_drain/brake.py · 305 строк

Реплей двух правил против слива 08-24…27: тормоз дня и потолок шорта.

- L48 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L49 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L58 `DAY = 86400`
- L59 `BRAKE_X = (30.0, 60.0, 90.0, 150.0)`
- L60 `BRAKE_X_GLOBAL = (300.0, 600.0, 900.0, 1500.0)`
- L61 `RUNUP_R = (2, 3, 5)`
- L62 `RUNUP_T = (0.2, 0.5, 1.0)`
- L63 `SUMMARY = os.path.join(ROOT, 'research', 's8_loop…`
- L66 `log_(m)`
- L70 `load_trades(s8)` — Закрытые сделки не-эхо книг с моментами входа и денег.
- L91 `replay_brake(trades, x, group_of)` — Тормоз дня: вход при реализованном дне группы ≤ −X не берётся.
- L121 `brake_table(trades, xs, group_of, label)`
- L137 `load_mids(symbols, log=log_)` — Почасовые середины по сводкам B1: {sym: {hour_ts: mid}}.
- L167 `runup(mids, sym, t_in, r_days)` — Ход за R суток к последнему ЗАКРЫТОМУ часу перед входом.
- L185 `runup_table(trades, mids)`
- L209 `write_report(path, brk, brk_g, ru, meta)`
- L264 `main(argv=None)`

## research/probe_drain/drain.py · 443 строк

Разбор слива 2026-08-24…27: что случилось со сделками всех книг.

- L53 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L54 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L63 `DAY = 86400`
- L66 `DRAIN = ('2026-08-24', '2026-08-27')` — Окно слива названо владельцем; база — дни ТОЙ ЖЕ кассы (капитал 3000 с 2026-08-13). Сравнивать доллары через…
- L67 `BASE = ('2026-08-13', '2026-08-23')`
- L68 `TOP_TRADES = 15`
- L71 `log_(m)`
- L75 `day_int(iso)`
- L80 `dstr(d)`
- L84 `in_win(day, win)`
- L88 `slice_stats(trades)` — Состав среза сделок: победы, причины, стороны, концентрация.
- L122 `crypto_symbols()` — Крипто-универсум по справочнику: не-крипто в контекст не идёт — его календарная компонента (биржа закрыта ноч…
- L135 `market_ctx(d0, d1, log=log_)` — Дневная доходность сечения по A2: медиана, BTC/ETH, доля вниз.
- L191 `ic_by_day(model_dir)` — Медианный живой IC (fwd_4h, обе руки) по дням.
- L208 `cycle_by_day(model_dir)` — Длительность цикла по дням: не влезающий в час цикл старит лист сканера и задерживает выходы — внутренний под…
- L225 `rule_archives(s8, d0, d1)` — Архивы книг, датированные окном: смена правил — событие разбора.
- L247 `collect(s8, log=log_)`
- L262 `top_losers(books, k=TOP_TRADES)`
- L274 `fmt(v, spec='+.2f', dash='—')`
- L285 `write_report(path, books, ctx, ic, cyc, arch, meta)`
- L395 `main(argv=None)`

## research/probe_extreme/probe.py · 378 строк

Зонд: платит ли ЗАШКАЛ прогноза — профиль исхода по крайности.

- L41 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L42 `RESEARCH = os.path.dirname(HERE)`
- L46 `HORIZONS_H = (1, 4)`
- L47 `N_BUCKETS = 5`
- L48 `MIN_SYM_LEGS = 20`
- L49 `ENTRY_TOL_SEC = 600`
- L50 `EXIT_TOL = 0.2`
- L51 `ROUND_COST_BP = 11.0`
- L54 `unbuffer_output()` — Печатать построчно, даже когда вывод уходит в файл.
- L69 `load_legs(paths, log=print)` — Ноги из журнала листов: (время, час, рука, монета, прогноз, цена).
- L104 `moves_for_symbol(bars, legs)` — Ход цены по горизонтам для ног ОДНОЙ монеты.
- L130 `excess_by_section(legs)` — Превышение над медианой СВОЕГО сечения, со знаком стороны.
- L152 `extremeness(legs, log=print)` — Оси крайности: rel — в разах от обычного прогноза монеты, raw — б.п.
- L172 `bucket_edges(vals, n=N_BUCKETS)` — Границы корзин — квантили распределения самой величины.
- L180 `profile(legs, axis, h)` — Профиль исхода по корзинам крайности, с «без лучшего имени».
- L226 `reading(art)` — Чтение профиля — по объявленным исходам, а не по лучшей клетке.
- L255 `report(art, path)`
- L299 `run(sheets, root, src=None, log=print)`
- L341 `main()`

## research/probe_fshift/controls_check.py · 98 строк

Машина негативных контролей этой механики: подделка → сюита падает.

- L32 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L34 `SUITE = 'research/probe_fshift/test_fshift.py'`
- L35 `REPORT = 'research/factory/out/build.json'`
- L38 `sha(p)`
- L43 `run()` — Код возврата и ИМЕНА провалившихся проверок, а не только код.
- L55 `main(report=None)`

## research/probe_fshift/run_ceiling.py · 1099 строк

Потолок механики «смена интервала начисления funding».

- L56 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L57 `RESEARCH = os.path.dirname(HERE)`
- L74 `OUT = os.path.join(HERE, 'out')`
- L75 `A1_OUT = os.path.join(RESEARCH, 'a1_universe', '…`
- L76 `FUND_DIR = os.path.join(A1_OUT, 'funding')`
- L80 `AUTO_FROM = '2025-11-03'` — Границы применимости — из объявления площадки, чужое утверждение, а не наш замер. Обе обязаны стоять в отчёте…
- L81 `NOT_COVERED = ('BTCUSDT', 'ETHUSDT')`
- L83 `TOL_MIN = 5`
- L84 `MIN_CROSS = Z.MIN_CROSS`
- L85 `NEUTRAL_COST_BP = Z.NEUTRAL_COST_BP`
- L86 `SOLO_COST_BP = Z.ROUND_COST_BP`
- L91 `SOLO_COST_SPREAD_BP = 17.4` — Круг голой ноги СО СПРЕДОМ в стрессе — перенесённое число собственной записи стакана (`research/d1_seconds/ou…
- L92 `SEED = 20260903`
- L93 `NULL_DRAWS = 20`
- L94 `MIN_MEASURED = 30`
- L95 `DECILES = 10`
- L98 `log_(m)`
- L102 `mem_available_mb()`
- L115 `universe_assets()` — Крипто-активы с обоими символами: площадка исполнения и архив.
- L129 `collect_events(fund, sym_of, uni, share, min_share, start_ms, e…` — События смены интервала по всему универсуму, с охранами.
- L182 `minute(ts_ms)`
- L186 `anchors_of(e)` — Четыре момента цены на событие. Одно место на весь замер.
- L200 `class PriceBook` — Сечение цен на каждом якоре. Якорь — момент, цена — первая доступная в `[якорь, якорь + допуск)`.
  - L209 `PriceBook.__init__(self, symbols, anchors)`
  - L218 `PriceBook.nbytes(self)`
  - L221 `PriceBook.vec(self, anchor)`
  - L225 `PriceBook.price(self, anchor, symbol)`
- L233 `needed_minutes(anchors, tol_min=TOL_MIN)` — Минуты, которые надо прочитать: якорь плюс окно допуска.
- L240 `fill_book(book, by_minute, tol_min=TOL_MIN)` — Раскладывает прочитанные минуты по якорям.
- L269 `load_prices(book, tol_min=TOL_MIN, log=log_, con_factory=None)` — Заполняет `book` из хранилища A2, месяц за месяцем.
- L338 `cross_mean(book, a_in, a_out, banned_rows)` — Равновзвешенная корзина сечения за окно `(a_in, a_out)`.
- L361 `banned(all_ts, book, t0_ms, t1_ms)` — Строки, у которых в окне своё событие смены интервала.
- L382 `own_ret(book, a_in, a_out, symbol)`
- L390 `current_rates(fund, sym_of, at_ms, max_age_ms=24 * SH.MS_H)` — Действующая ставка каждого имени в момент `at_ms`.
- L411 `decile_peers(rates, symbol, same_sign=True, deciles=DECILES)` — Имена того же дециля |ставки|, что и `symbol`.
- L439 `measure(events, book, all_ts, fund, sym_of, rng, log=log_, asse…` — Числа (б) и (в) по каждому событию. Чистая функция от цен.
- L536 `null_excess(book, a_in, a_out, ban, side, rng, draws=NULL_DRAWS)` — Нуль: та же минута, ДРУГОЕ имя.
- L565 `agg(vals)`
- L573 `daily_net(rows, key='ideal_exc_bp')` — Ряд «сутки → сумма нетто за эти сутки», в б.п. гросса.
- L592 `verdict(dens, ex, c2, rank_share, null, pre=None, measured=None)` — Вердикт ЧИСЛОМ, а не литералом рядом с числом.
- L691 `write_report(path, meta, dens, ex_i, ex_r, own_i, fund_a, c2, c…`
- L947 `main(argv=None)`

## research/probe_fshift/shift.py · 303 строк

Смена интервала начисления funding как датированное событие.

- L65 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L66 `RESEARCH = os.path.dirname(HERE)`
- L73 `MS_H = 3600000`
- L74 `MS_D = 86400000`
- L76 `WINDOW = 25`
- L77 `RATIO = 2.0`
- L78 `MIN_BEFORE_STEPS = 5`
- L79 `MAX_HOLD_MS = 24 * MS_H`
- L85 `VERDICT_SIGN = -1` — Ячейка вердикта: ставка < 0 (платят шорты) — позиция ЛОНГ. Сторона выбрана до всякого счёта по критерию владе…
- L88 `side_of_rate(rate)` — Сторона позиции по знаку ставки. Плюс — лонг, минус — шорт.
- L101 `regime_before(t_ms, i, window=WINDOW, min_steps=MIN_BEFORE_STEP…` — Режим ряда по шагам, кончающимся на `t[i-1]`. Строго прошлое.
- L120 `shift_events(t_ms, rates, window=WINDOW, ratio=RATIO, min_steps…` — Первые начисления по УКОРОЧЕННОМУ интервалу.
- L165 `reverse_ts(t_ms, i, short_h, ratio=RATIO)` — Метка первого начисления по ВОЗВРАЩЁННОМУ длинному интервалу.
- L184 `holding(t_ms, ev, max_hold_ms=MAX_HOLD_MS)` — Окно удержания `(вход_мс, выход_мс, причина)`.
- L198 `dedup_by_name(events, min_gap_ms=MAX_HOLD_MS)` — Одна позиция на имя: событие внутри чужого удержания пропускается.
- L215 `rate_extremity(t_ms, rates, i, min_hist=20)` — Насколько ставка события крайняя в СОБСТВЕННОМ прошлом ряда.
- L239 `day_of(ts_ms)`
- L243 `active_share(event_ts, first_day=None, last_day=None, window_d=…` — Доля суток хотя бы с одним событием, по скользящим окнам.
- L282 `excess_bp(own_ret, cross_ret, side)` — Превышение над одновременной кросс-секцией, в базисных пунктах.
- L294 `funding_bp(sum_rates, side)` — Начисления, ПОЛУЧЕННЫЕ позицией за удержание, в базисных пунктах.

## research/probe_intraday/probe.py · 208 строк

Зонд: какой знак у связи «прошлое отклонение → будущее» внутри дня?

- L42 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L43 `RESEARCH = os.path.dirname(HERE)`
- L44 `OUT = os.path.join(HERE, 'out')`
- L56 `STEPS = ('1m', '5m', '15m')`
- L57 `STEP_MIN = {'1m': 1, '5m': 5, '15m': 15}`
- L61 `KS_MIN = (60, 240)` — Горизонты в МИНУТАХ: величина должна быть свойством времени, а не числа баров, иначе сравнение шагов бессмысл…
- L62 `HS_MIN = (60, 240, 1440)`
- L63 `MIN_BARS = 4`
- L65 `FORM_DAYS = 20`
- L66 `TEST_DAYS = 10`
- L67 `WINDOWS = ('2022-09-01', '2023-03-01', '2023-09-0…`
- L70 `MIN_ASSETS = 30`
- L71 `WIDTH = 0.1`
- L72 `ROUND_TRIP_BP = 11.0`
- L75 `ms(day)`
- L79 `one_window(con, start, step, liq, universe, interval)` — Один срез: β на окне формирования, IC на окне замера.
- L145 `main()`

## research/probe_liqsplit/liqsplit.py · 347 строк

Живые принты ликвидаций как условие отскока: падения D1 С принудительными закрытиями против падений БЕЗ них.

- L50 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L51 `RESEARCH = os.path.dirname(HERE)`
- L52 `OUT = os.path.join(HERE, 'out')`
- L65 `GROUPS = ('с ликвидациями', 'без ликвидаций')` — --- объявлено до прогона ---------------------------------------------
- L66 `COST_ROUND_BP = 17.4`
- L67 `NEED_GROSS_BP = 2 * COST_ROUND_BP`
- L70 `log_(m)`
- L74 `liq_line(line)` — Принт ликвидации: (секунда, нотионал $, сторона Buy=1).
- L88 `liq_of_day(root, sym, hours)` — Все принты `liq` имени за сутки, отсортированные по времени.
- L103 `liq_day_alive(root, day)` — Есть ли за сутки хоть один liq-файл хоть у одного имени.
- L120 `check_day(root, syms, day, jobs, log=print)` — События суток ячейки вердикта с принтами ликвидаций окна.
- L161 `group_of(e)`
- L165 `_med(v)`
- L170 `_agg(sub)`
- L193 `summarise(rows)`
- L217 `reading(g)`
- L239 `_row(name, r)`
- L255 `report(art, path)`
- L293 `main()`

## research/probe_listings/probe.py · 564 строк

Зонд первых дней жизни инструмента (листинги).

- L63 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L64 `RESEARCH = os.path.dirname(HERE)`
- L65 `OUT = os.path.join(HERE, 'out')`
- L66 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L76 `DELAYS = (1, 3, 7)` — --- объявлено до прогона ---------------------------------------------
- L77 `HORIZONS = (7, 30, 90)`
- L78 `MAIN_CELL = 'd1_h30'`
- L80 `MATURE_AGE = 365` — горизонт — объявлено до прогона
- L81 `MIN_MATURE = 30`
- L82 `MAIN_FROM = '2022-01-01'`
- L84 `SEEDS = (1, 2, 3, 4, 5)` — раньше пуста; ранние годы — диагностика
- L85 `FUND_WINS = ((0, 7), (7, 30))`
- L89 `load_universe(path=None)`
- L95 `crypto_assets(universe)` — Активы-крипто с символом Binance и датой листинга.
- L108 `day_index(d0, day)`
- L112 `build_matrix(con, symbols, t0=T_START, t1=T_END)` — Матрица дневных закрытий `[день × символ]` из хранилища A2.
- L132 `measure_events(M, col_of, ages, events, d, h, counters, end_idx)` — Записи ячейки (d, h): превышение новичка над зрелой кросс-секцией.
- L180 `events_entry_index(M, j, listed, d)` — Индекс дня входа: закрытие дня `listed + d`, без подглядывания.
- L191 `summarise(records)` — Свод по событиям и по когортам (месяц листинга — один голос).
- L214 `by_year(records)`
- L224 `null_events(M, col_of, ages, syms, n_events, seed, end_idx, d, …` — Псевдо-события: случайные (зрелое имя, дата), той же численности.
- L249 `funding_newborns(funding, events)` — Средняя суточная ставка новичка в окнах от ПЕРВОГО начисления.
- L282 `verdict_phrase(cell)` — Фраза выводится ИЗ чисел главной ячейки (урок Z2).
- L297 `report(art, path)`
- L395 `born_index(M)` — День рождения каждого ряда — ПО ДАННЫМ: первый конечный день.
- L412 `run(M, syms, universe, events_all, counters)` — Вся сетка + нуль + по-годам. Вынесено ради тестов на синтетике.
- L499 `main()`

## research/probe_monthly/funding_cost.py · 317 строк

Funding месячной книги — вторая половина зонда месячного горизонта.

- L45 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L46 `RESEARCH = os.path.dirname(HERE)`
- L47 `OUT = os.path.join(HERE, 'out')`
- L48 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L60 `UNCOVERED_MAX = 0.1`
- L61 `NET_TOL = 0.06`
- L64 `load_universe(path=None)`
- L70 `book_of(vec, t, sig, fwd)` — Книга сечения: {актив: вес}, Σ|w| = 1 — тот же дециль, что зонд.
- L84 `funding_of_book(funding, w, t, h)` — Издержка funding книги за `[t, t+h)`, б.п. гросса, по ногам.
- L107 `measure_cell_funding(vec, pairs, funding, h, counters)` — Funding и нетто-с-funding по сечениям ячейки; рядом пересчёт нетто БЕЗ funding — для сверки с артефактом зонд…
- L150 `crosscheck(cells_f, probe_art)` — Нетто без funding обязано совпасть с артефактом зонда.
- L169 `verdict_phrase(cell)` — Фраза выводится ИЗ чисел главной ячейки (урок Z2).
- L189 `report(art, path)`
- L242 `main()`

## research/probe_monthly/probe.py · 411 строк

Зонд месячного горизонта кросс-секции.

- L63 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L64 `RESEARCH = os.path.dirname(HERE)`
- L65 `OUT = os.path.join(HERE, 'out')`
- L74 `BRICK = 10` — --- объявлено до прогона ---------------------------------------------
- L75 `KS = (14, 30, 60, 90)`
- L76 `HS = (10, 30)`
- L77 `WIDTH = 0.1`
- L78 `TAKER_BP = 5.5`
- L79 `SEEDS = (1, 2, 3, 4, 5)`
- L80 `MAIN_CELL = 'k14_h30'`
- L86 `shift(day, days)`
- L90 `name_index(vec, day, cache)`
- L96 `aligned(vec, cache, base_names, day, kind, key)` — Вектор `kind[key]` даты `day`, выровненный по `base_names`.
- L113 `chain(vec, cache, base_names, days)` — Сумма fwd10 по датам `days`, выровненная по `base_names`.
- L127 `build_signal(vec, cache, t, k)` — Сигнал формации k на дату t, в нумерации names(t).
- L141 `build_forward(vec, cache, t, h)` — Форвард h дней на дату t, в нумерации names(t).
- L149 `book_weights(sig, fwd, width=WIDTH)` — Веса книги даты: Σ|w| = 1, дециль равновзвешенный внутри ноги.
- L157 `turnover(prev_w, cur_w)` — Σ|Δw| двух книг (имя → вес); полная замена = 2.
- L164 `build_pairs(vec, cache, dates, k, h, counters)` — Пары (дата, сигнал, форвард) ячейки. Строятся ОДИН раз: нуль отличается от прогона ровно тем, как сопоставлен…
- L183 `measure_pairs(vec, pairs, counters, seed=None)` — Мера ячейки по готовым парам. `seed` — нуль 1: перестановка сигнала внутри сечения, зерно на ДАТУ (`RS.seed_f…
- L236 `run_grid(vec, dates_all, counters)` — Все ячейки k×h по непересекающимся сечениям (шаг h по списку дат — конвенция R3: перекрытие окон обесценило A…
- L253 `run_nulls(vec, all_pairs, counters)` — Нуль 1 для каждой ячейки по ТЕМ ЖЕ парам, что прогон.
- L270 `verdict_phrase(cell)` — Фраза выводится ИЗ чисел главной ячейки (урок Z2).
- L291 `report(art, path)`
- L361 `main()`

## research/probe_monthly/robust.py · 512 строк

Три оговорки месячного зонда, закрытые замерами.

- L63 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L64 `RESEARCH = os.path.dirname(HERE)`
- L65 `OUT = os.path.join(HERE, 'out')`
- L76 `NW_MIN_T = 2.5` — --- объявлено до прогона ---------------------------------------------
- L77 `NW_DEAD_T = 2.0`
- L78 `NULL_T_MAX = 1.5`
- L79 `SEEDS = (1, 2, 3, 4, 5)`
- L82 `chain_alive(vec, cache, base_names, days)` — Сумма кирпичей ПРЕФИКСОМ до первого разрыва.
- L117 `build_forward_alive(vec, cache, t, h)` — Месячный форвард руки `alive`: частичный при делистинге.
- L127 `book_stats(vec, t, sig, fwd, prev_w, status=None)` — Одно сечение: нетто книги и состав ног. `None` — дециль вырожден.
- L151 `survivorship(vec, cache, dates, k, h, counters)` — Замер 1: базовая рука против руки `alive` на ОДНИХ датах.
- L204 `newey_west_t(vals, lag)` — t-статистика среднего с поправкой Ньюи–Уэста на автокорреляцию.
- L231 `overlapping(vec, cache, dates, k, h, counters, seed=None)` — Нетто по ВСЕМ датам (перекрывающиеся окна) + t наивный и NW.
- L279 `halves(vec, cache, dates, k, h, counters)` — Замер 3: те же ячейки на первой и второй половине дат.
- L307 `verdict_phrase(art)` — Фраза выводится ИЗ чисел трёх замеров (урок Z2).
- L347 `report(art, path)`
- L432 `main()`

## research/probe_regimes/probe.py · 348 строк

Зонд неоднородности навыка модели по режимам рынка.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L51 `REGIMES = [('vol_ratio', 'волатильность против св…` — Режимы ОБЪЯВЛЕНЫ здесь и до прогона. Каждый — признак, известный в момент решения, и каждый отвечает на «в ка…
- L59 `BINS = 3`
- L60 `MIN_NAMES = 30`
- L61 `RANDOM_DRAWS = 5`
- L62 `SEED = 20260812`
- L65 `spearman(a, b)` — Ранговая корреляция. NaN-пары выброшены вызывающим.
- L84 `_rng(day)` — Зерно ЧИСЛОМ из номера дня: нуль обязан быть воспроизводим.
- L89 `load(matrix, vectors, log=print)`
- L110 `_day_index(col)` — Дни числом. В матрице M1 они лежат СТРОКАМИ («2022-12-06»), и приводить их к числу напрямую нельзя. Порядок д…
- L121 `run(cols, pred, key, log=print, matched=False)` — `matched=False` — прежний нуль: случайные РАВНЫЕ трети, один набор на день. Для непрерывных признаков это чес…
- L220 `summarise(out)`
- L255 `report(rows, n_days, vectors, path)`
- L318 `main()`

## research/probe_reversal/probe.py · 356 строк

Зонд: работает ли краткосрочный возврат на минутных горизонтах.

- L55 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L56 `RESEARCH = os.path.dirname(HERE)`
- L57 `OUT = os.path.join(HERE, 'out')`
- L64 `STEP_MIN = 1`
- L65 `STEP_SEC = 60`
- L66 `WINDOW_MIN = 15`
- L67 `MOVES = (0.02, 0.03, 0.05)`
- L68 `DELAYS = (0, 1, 2, 5)`
- L69 `HORIZONS = (1, 2, 3, 5, 10, 15, 30, 60)`
- L70 `MIN_CROSS = 20`
- L73 `grid(start, end)`
- L81 `month_bounds(mon)`
- L88 `taker_bp(symbols)` — Посимвольная тейкерская ставка из A1. Ставка не одно число.
- L117 `run_month(mon, nxt, symbols, uni, share, min_share, interval, l…` — События месяца и всё, что по ним меряется. Возвращает записи.
- L152 `excursions(M, er, ec, horizons)` — Насколько далеко цена ушла ПРОТИВ позиции и в её пользу.
- L181 `measure(rec, M, times, log)` — Превышение над одновременной кросс-секцией по эпизодам.
- L223 `merge(dst, src)`
- L232 `main()`

## research/probe_setups/setups.py · 887 строк

Зонд сетапов: есть ли ярлык ситуации, устойчивый по ВСЕМ книгам и рукам.

- L96 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L101 `BOOKS = (('h4', 'model'), ('h24', 'model_h24'),…` — Торгуемые книги, входящие в меру. Карта та же, что у сервера; эхо-книги исключены намеренно (см. шапку).
- L103 `ECHO = (('sit_r', 'model_sit_r'), ('h24b', 'mo…`
- L105 `OBS = ('sit_obs', 'model_sit_obs')`
- L106 `ARMS = ('gbm', 'nn')`
- L108 `MIN_CELL = 30`
- L109 `MIN_SIDE = 10`
- L110 `MIN_DEC = 100`
- L111 `MIN_CELLS = 4`
- L112 `STABLE_SHARE = 2.0 / 3`
- L113 `PERMS = 1000`
- L114 `SEED = 20260824`
- L117 `read_jsonl(path)`
- L131 `median(xs)` — Медиана с усреднением двух середин.
- L145 `book_rows(mdir, hz)` — Закрытые сделки книги — ядром `trades.py`, второй копии нет.
- L204 `account_check(mdir, real, closed_after=None)` — Встроенная сверка: мои деньги против счёта, писанного циклом.
- L248 `decision_labels(rows)` — Ярлык НА РЕШЕНИЕ: большинство копий, ничья — по имени семейства.
- L271 `apply_labels(rows, lab)`
- L278 `decisions(rows)` — Решения: нетто — СРЕДНЕЕ по копиям, не сумма.
- L304 `cells(rows)` — Ячейки (книга × рука) с базой: медиана и среднее ВСЕХ сделок.
- L314 `family_cells(cs, labels)` — Превышение семейства над своей ячейкой, по каждой ячейке.
- L369 `stability(fc, key='exc_med')` — S1 — доля ячеек с положительным превышением; S2 — его величина.
- L389 `qualified(fc, decs)` — Семейства, для которых мера вообще построена.
- L399 `null_decisions(rows, decs, qual, perms=PERMS, seed=SEED)` — НУЛЬ 2: перемешать ярлыки между решениями, сохранив повторы.
- L443 `null_incell(rows, qual, perms=200, seed=SEED + 1)` — НУЛЬ 1 (диагностика): перемешивание внутри ячейки.
- L472 `without_top(decs, fam)` — Среднее нетто семейства без ЛУЧШЕГО имени.
- L488 `halves(rows, qual)` — Знак взвешенного превышения в обеих половинах истории.
- L508 `fam_title(f)`
- L517 `analyse(rows)` — Весь замер над уже загруженными строками — чистая функция.
- L560 `verdict(res, n2, hv, key='')` — Шесть объявленных условий, каждое — отдельным флагом.
- L595 `load(root, books)`
- L609 `fmt(x, nd=1)`
- L613 `write_report(path, data, meta)`
- L795 `obs_block(root)` — Наблюдательная запись отдельным блоком — по копиям, без ячеек.
- L808 `publish(msg)`
- L817 `main(argv=None)`

## research/probe_spike/long_history.py · 320 строк

То же условие всплеска — на годах истории, а не на трёх неделях.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L47 `ROOT = os.path.dirname(HERE)`
- L57 `OUT = os.path.join(HERE, 'out')`
- L58 `HORIZONS = S.HORIZONS`
- L59 `JUMP = S.JUMP`
- L60 `DEDUP_MIN = 5`
- L66 `SPREAD_OWN = (8.5, 6.5)` — Спред взят из СОБСТВЕННОЙ записи стакана (21 сутки, 725 имён, зонд `spike.py`): в архиве Binance спреда нет в…
- L67 `SPREAD_HEDGE = (5.7, 5.7)`
- L70 `log_(m)`
- L74 `primitives(P)` — Единственный примитив: ход за минуту по открытиям соседних баров.
- L88 `build_conditions()`
- L99 `CONDITIONS = build_conditions()`
- L100 `CONDS_BY_NAME = {}`
- L105 `collect_events(P, prim, own, log=log_)` — События месяца. `own` отсекает хвост следующего месяца.
- L125 `trips()` — Оба круга ОДНОЙ формулой зонда — второй копии издержек нет.
- L138 `run(start, end, symbols=None, log=log_)`
- L178 `KEY = ('всплеск вверх 2 % за минуту', -1, 60)`
- L181 `write_report(path, cells, null, years, meta)`
- L268 `main(argv=None)`

## research/probe_spike/spike.py · 401 строк

Зонд минутного всплеска: цена это была или котировка, и что после круга.

- L55 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L56 `ROOT = os.path.dirname(HERE)`
- L65 `OUT = os.path.join(HERE, 'out')`
- L66 `HORIZONS = (15, 60, 240)`
- L67 `JUMP = 0.02`
- L68 `MIN_TRADES = 10`
- L69 `QUIET_OK = 0.5`
- L70 `QUIET_BAD = 0.8`
- L71 `FEE_BP = 11.0`
- L72 `LEGS = 2`
- L75 `log_(m)`
- L79 `moves(mid)`
- L86 `primitives(M)`
- L98 `build_conditions()`
- L119 `CONDITIONS = build_conditions()`
- L120 `CONDS_BY_NAME = {}`
- L125 `collect_events(P, prim, log=log_)`
- L143 `diag(ev, M, syms, acc, h=60)` — Спред, концентрация по именам и сырой ход — по каждому условию.
- L202 `_q(v, q=50)`
- L206 `round_trip(a)` — Круг книги из двух ног: комиссия обеих плюс по половине спреда.
- L219 `solo_trip(a)` — Круг ОДНОЙ ноги: голая направленная сделка без хеджа.
- L233 `write_report(path, cells, null, dg, meta)`
- L329 `main(argv=None)`

## research/probe_stables/probe.py · 142 строк

Стейбл-против-стейбла: у инструмента цены нет, а издержки есть.

- L40 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L44 `SUMMARY = FF.SUMMARY`
- L45 `OUT = os.path.join(HERE, 'out')`
- L51 `ROUND_COST_BP = 11.0` — Правило живёт ОДНИМ модулем (`common/flat_filter`): его читают и этот замер, и цикл, решающий, чем торговать.…
- L52 `STABLE_MAX_BP = FF.FLAT_MAX_BP`
- L55 `scan(days, log=print)` — Медианный суточный размах по каждому имени, б.п. — общей мерой.
- L63 `report(res, days, path)`
- L122 `main()`

## research/probe_tailveto/tailveto.py · 335 строк

Судья хвостов: концентрируется ли ЛЕВЫЙ ХВОСТ книги в шортах против состояния толпы — и общий судья хвоста ря…

- L58 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L59 `RESEARCH = os.path.dirname(HERE)`
- L60 `OUT = os.path.join(HERE, 'out')`
- L66 `_load(name, path)`
- L73 `SP = _load('setups_probe', os.path.join(RESE…`
- L77 `TAIL_Q = 0.05`
- L78 `MIN_SECTION = 30`
- L79 `MIN_FLAG = 30`
- L80 `MIN_TAIL = 10`
- L81 `PERMS = 1000`
- L82 `SEED = 20260831`
- L85 `log_(m)`
- L89 `col_terciles(M, min_n=MIN_SECTION)` — Пороги верхней и нижней трети по каждому часу-колонке.
- L102 `entry_state(M, hi, lo, sym_ix, grid_ix, sym, opened_at)` — Флаг состояния на последний ЗАКРЫТЫЙ час перед входом.
- L123 `tail_judge(entries, perms=PERMS, seed=SEED)` — Судья хвостов: концентрация худших 5 % в помеченной группе.
- L183 `fmt(v, spec='+.2f')`
- L188 `cell_line(name, c)`
- L199 `reading(cells)`
- L214 `write_report(path, blocks, diag, meta)`
- L250 `main(argv=None)`

## research/probe_turn/turn.py · 461 строк

Зонд перелома: почему книги сначала зарабатывают, а потом сливают.

- L49 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L52 `DAY = 86400`
- L53 `PERMS = 2000`
- L57 `MIN_DAYS = 10` — Сколько дней истории нужно книге, чтобы участвовать в мере синхронности: у книги, заведённой вчера, общих дне…
- L58 `SEED = 20260824`
- L64 `BOOKS = (('h4', 'model', False), ('h24', 'model…` — Торгуемые книги: та же карта, что у сервера. Эхо-книги (тот же набор решений под другим правилом) помечаются,…
- L70 `read_jsonl(path)`
- L84 `book_trades(mdir)` — Закрытые сделки книги с деньгами — ядром `trades.py`.
- L144 `daily(trades)`
- L151 `curve(days)` — Кумулятивная кривая по календарю, без пропусков дней.
- L164 `peak_stats(days)` — Пик кривой и что было по обе стороны от него.
- L184 `perm_test(days, perms=PERMS, seed=SEED)` — Те же дни в случайном порядке: как выглядит «перелом» у шума.
- L219 `sync_stats(books, seed=SEED)` — Синхронны ли просадки книг — против того же на перемешанных днях.
- L277 `split_by_peak(trades, days)` — Что изменилось в сделках до и после пика кривой.
- L321 `main()`
- L369 `day_str(d)`
- L373 `write_report(art, path)`
- L451 `publish()`

## research/probe_upcascade/up.py · 250 строк

Зонд продолжения сквиза: ЛОНГ после каскада ликвидаций ВВЕРХ.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L47 `RESEARCH = os.path.dirname(HERE)`
- L48 `OUT = os.path.join(HERE, 'out')`
- L68 `L3 = importlib.util.module_from_spec(_spec)`
- L73 `DIRECTION = +1`
- L76 `log_(m)`
- L80 `mem_avail_mb()` — Свободная память машины: реплей живёт рядом со сборщиком, чья запись невосполнима, и первый прогон зонда убил…
- L93 `fmt_bp(v)`
- L97 `med(a)`
- L103 `rows_for(res)` — Строки таблицы одной руки: по горизонтам — сырой ход, сверх кросс-секции (по событиям и по эпизодам), доля по…
- L135 `write_report(path, blocks, meta)`
- L180 `main(argv=None)`

## research/r1_factor/compare.py · 124 строк

R1 — сверка двух прогонов, посчитанных на разном разрешении хранилища.

- L34 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L35 `OUT = os.path.join(HERE, 'out')`
- L38 `load(interval)`
- L46 `median(v)`
- L53 `main()`

## research/r1_factor/factor.py · 298 строк

R1 — рыночная волна и остаток. Ядро расчёта.

- L39 `STEP_MS = {'1m': 60000, '5m': 300000, '15m': 9000…`
- L42 `MIN_ASSETS_IN_BAR = 5`
- L43 `MIN_COVERAGE = 0.5`
- L46 `price_grid(series, step, t0_ms, t1_ms)` — Цены на регулярной сетке шага `step`; пропуск — NaN.
- L71 `log_returns(P)` — Логарифмические доходности по сетке.
- L82 `market_factor(R, min_assets=MIN_ASSETS_IN_BAR)` — Равновзвешенная волна и версия «все, кроме меня».
- L107 `regress(y, x)` — МНК `y = a + b·x` по общим наблюдениям. Возвращает b, R², n.
- L131 `betas(R, F_loo, min_coverage=MIN_COVERAGE)` — β и R² каждого актива против собственной волны «все, кроме меня».
- L148 `residuals(R, F_loo, fitted)` — Остатки `r − a − β·F` по оценкам окна формирования.
- L165 `quantiles(vals, ps=(0.05, 0.25, 0.5, 0.75, 0.95))`
- L183 `sector_factor(R, members, min_members=5)` — Секторный фактор группы и его версия «все, кроме меня».
- L209 `pairwise_cov(R, min_overlap=100)` — Ковариация по попарно доступным наблюдениям.
- L236 `top_components(C, m)` — Веса первых `m` главных компонент, столбцами.
- L258 `weighted_factor(R, W)` — Факторы `R·W` и их версии «все, кроме меня».
- L276 `regress_multi(y, X)` — МНК `y = a + Σ b_j x_j` по общим наблюдениям.

## research/r1_factor/premise.py · 357 строк

R1 — прогон: рыночная волна по сетке окон и проверка посылки §8.1.

- L53 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L54 `RESEARCH = os.path.dirname(HERE)`
- L55 `OUT = os.path.join(HERE, 'out')`
- L56 `WINDOWS = os.path.join(OUT, 'windows')`
- L66 `STEP = '1h'`
- L67 `COARSER = ('4h', '1d')`
- L68 `FORM_DAYS = 90`
- L69 `TRADE_DAYS = 30`
- L70 `GRID_START = '2022-07-01'`
- L71 `GRID_END = '2026-06-01'`
- L73 `MIN_ASSETS = 10`
- L77 `P1_MIN_EXPLAINED = 0.4` — Пороги §8.1. Здесь они только докладываются: решение принимает сводка, а не отдельное окно.
- L78 `P2_MAX_SPREAD = 0.15`
- L81 `windows_dir(interval)` — Окна тоже раскладываются по разрешению.
- L91 `window_dates(start, end, step_days)`
- L98 `form_window(at)`
- L103 `fit_at_step(series, step, t0_ms, t1_ms)` — β, R² и доля объяснённой дисперсии на одном шаге бара.
- L151 `run_window(con, at, liq, universe, of_group, interval)`
- L238 `load_windows(interval)` — Состояние с диска, а не из дельты прогона (урок A2, правка a51c133).
- L251 `summarize(rows)`
- L303 `main()`

## research/r1_factor/report.py · 182 строк

R1 — отчёт по проверке посылки §8.1 спеки 03.

- L22 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L23 `OUT = os.path.join(HERE, 'out')`
- L26 `pct(x, d=1)`
- L30 `median(v)`
- L38 `main()`

## research/r2_residual/compare.py · 106 строк

R2 — сверка прогонов: между разрешениями хранилища или с нулевой моделью.

- L25 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L26 `OUT = os.path.join(HERE, 'out')`
- L29 `load(name)`
- L37 `median(v)`
- L44 `main()`

## research/r2_residual/crosssection.py · 582 строк

R2 — возврат остатка вне выборки, кросс-секционный прогон.

- L66 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L67 `RESEARCH = os.path.dirname(HERE)`
- L68 `OUT = os.path.join(HERE, 'out')`
- L69 `CHUNKS = os.path.join(OUT, 'chunks')`
- L70 `VECTORS = os.path.join(OUT, 'vectors')`
- L82 `STEP = '1h'`
- L83 `BARS_PER_DAY = 24`
- L84 `FORM_DAYS = 90`
- L85 `MODELS = ('market', 'market_sector', 'pca3')`
- L86 `MIN_GROUP = 5`
- L87 `PCA_COMPONENTS = 3`
- L90 `KS = (1, 3, 7, 14)` — Сетка §2 спеки 03. Объявлена до прогона и не меняется.
- L91 `HS = (1, 3, 5, 10)`
- L92 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L94 `GRID_START = '2022-07-01'`
- L95 `GRID_END = '2026-06-01'`
- L96 `REBALANCE_STEP_DAYS = 1`
- L97 `CHUNK_DAYS = 90`
- L99 `MIN_ASSETS = 30`
- L100 `MIN_FORWARD_BARS = 1`
- L103 `rebalance_dates(start, end, step_days)`
- L110 `ms(day)`
- L114 `build_factors(R, names, of_group, model)` — Матрица факторов на каждый актив: (T, N, m), уже «все, кроме меня».
- L159 `fit_window(R, FACT, need)` — β каждого актива на окне формирования. NaN там, где не оценивается.
- L170 `run_date(at, grid, PX, cols, live, state, universe, of_group, m…` — Одно сечение: сигналы по всем k, форварды по всем h, IC и корзины.
- L289 `composition(b, names, state, universe, at)` — Чем дециль отличается от универсума. §5.2 и §5.3 спеки 03.
- L312 `process_chunk(con, dates, liq, universe, of_group, model, inter…` — Одна загрузка данных на группу дат: память под контролем.
- L357 `tag(interval, null_seed, model='market')` — Имя артефакта несёт и разрешение, и ступень лестницы.
- L369 `chunk_path(interval, first_date, null_seed=None, model='market')` — Имя чанка несёт ПЕРВУЮ ДАТУ, а не порядковый номер.
- L381 `load_chunks(interval, null_seed=None, model='market')` — Состояние с диска, а не из дельты прогона (урок A2).
- L398 `summarize(rows)`
- L497 `robust(v, how)` — Медиана и усечённое на 5 % с каждого хвоста среднее.
- L509 `share_positive(v)`
- L514 `main()`

## research/r2_residual/nulls.py · 315 строк

R3 — две нулевые модели по десять зёрен. Спека 03, раздел 7.

- L66 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L67 `OUT = os.path.join(HERE, 'out')`
- L68 `VECTORS = os.path.join(OUT, 'vectors')`
- L73 `SEEDS = tuple(range(1, 11))`
- L76 `SHIFTS = (180, 240, 300, 365, 430, 490, 550, 610…` — Сдвиги нуля 2, дни. 365 — величина из спеки; остальные дают распределение, без которого «превышает 95-й проце…
- L77 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L80 `NULL_PERCENTILE = 95` — Порог §8.2: реальный IC обязан превышать 95-й процентиль зёрен нуля.
- L83 `load_vectors(interval)`
- L105 `measure(pairs, k, h)` — IC и спред корзины по списку пар (сигнал, форвард).
- L127 `share_pos(v)`
- L132 `grid_of(dates, vec, build)` — Мера по всей сетке k×h. `build` даёт пары (сигнал, форвард).
- L152 `real_builder(vec)`
- L158 `null1_builder(vec, seed)`
- L171 `null2_builder(vec, dates_all, shift)` — Сигнал даты t против форварда даты t+shift, сопоставление по активу.
- L202 `verify_against_run(real, interval)` — Пересчёт из векторов обязан воспроизвести прогон R2 в точности.
- L227 `verdict(real, nulls, key='ic_median')` — Сравнение прогона с распределением зёрен нуля.
- L259 `main()`

## research/r2_residual/nulls_report.py · 185 строк

R3 — отчёт по нулевым моделям.

- L14 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L15 `OUT = os.path.join(HERE, 'out')`
- L18 `STOP_IC = 0.005` — §8.2: критерий немедленной остановки.
- L19 `STOP_COST_RATIO = 2.0`
- L20 `COST_CYCLE_BP = 26.0`
- L23 `med(v)`
- L30 `p95(v)`
- L35 `f(x, d=4)`
- L39 `main()`

## research/r2_residual/path_norm.py · 260 строк

Замер к идее владельца: нормировать сигнал длиной пути (эквивалент RSI).

- L56 `OUT = os.path.join(os.path.dirname(os.path.ab…`
- L57 `VECTORS = os.path.join(OUT, 'vectors')`
- L59 `DAY = '1'`
- L60 `MIN_AGREE = 0.98`
- L63 `window_files(interval, model)`
- L73 `daily_pieces(win, dates, i, k, names)` — Подённые сигналы за k дней, выровненные по именам текущей даты.
- L98 `gross_sharpe(spreads, h)` — Годовой Sharpe по непересекающимся периодам, брутто.
- L127 `collect(interval, model, ks, hs, width=0.1)`
- L190 `median(v)`
- L194 `main()`

## research/r2_residual/report.py · 238 строк

R2 — отчёт: возврат остатка вне выборки.

- L15 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L16 `OUT = os.path.join(HERE, 'out')`
- L19 `IC_MIN = 0.02` — Пороги §8.3 спеки 03. Утверждены до прогона, здесь только сверка.
- L20 `T_MIN = 3.0`
- L21 `POSITIVE_SHARE_MIN = 0.6`
- L22 `SECTIONS_MIN = 100`
- L24 `STOP_IC = 0.005` — Критерий немедленной остановки §8.2.
- L25 `STOP_COST_RATIO = 2.0`
- L28 `COST_CYCLE_BP = 26.0` — Цикл издержек по отобранным именам, замер A1. Здесь используется только для сверки с §8.2 — сам расчёт издерж…
- L31 `fmt(x, d=4)`
- L35 `bp(x)`
- L39 `main()`

## research/r2_residual/residual.py · 245 строк

R2 — возврат остатка. Ядро расчёта.

- L45 `accumulate(R, F, beta, i0, i1)` — Сумма остатков по барам `[i0, i1)` для каждого актива.
- L63 `ranks(x)` — Средние ранги с корректной обработкой связок.
- L88 `spearman(a, b)` — Ранговая корреляция сечения по общим наблюдениям.
- L103 `basket_spread(score, fwd, width)` — Спред длинно-короткой корзины: верхняя доля минус нижняя.
- L131 `tstat(vals)` — t-статистика среднего. Возвращает (среднее, t, n).
- L145 `quantiles(vals, ps=(0.05, 0.25, 0.5, 0.75, 0.95))`
- L152 `window_bounds(i_form, i_t, n_returns, k, h, bars_per_day)` — Границы трёх окон в индексах ряда доходностей.
- L172 `seed_for(seed, day)` — Детерминированное зерно из номера зерна и даты.
- L190 `residual_matrix(R, FACT, B)` — Остатки `r − Σ β_j · F_j` для всех активов и баров сразу.
- L211 `accumulate_resid(E, i0, i1)` — Сумма готовых остатков по барам `[i0, i1)`.
- L225 `blend_ranks(a, b, weight=0.5)` — Комбинация двух сигналов средним нормированных рангов, §12.3.

## research/r4_costs/costs.py · 180 строк

R4 — издержки на фактическом обороте книги. Ядро расчёта.

- L60 `weights(score, fwd, width)` — Веса книги на одну дату. Сумма модулей равна единице.
- L82 `align(names_a, w_a, names_b, w_b)` — Два вектора весов на общем множестве имён, в одном порядке.
- L95 `turnover(names_prev, w_prev, names_now, w_now)` — Оборот ребаланса: `(имена, |Δw| по именам, сумма)`.
- L109 `commission(names, delta, rate_of)` — Комиссия за ребаланс, доля гросс-нотионала.
- L123 `funding_cost(names, w, accrued_of)` — Funding за период удержания, доля гросс-нотионала.
- L147 `quintile_expected_rate(turnovers, table, cheap, expensive, fall…` — Ожидаемая ставка по квинтилю оборота — правило раздела 6.
- L174 `net_spread(gross_spread, cost)` — Прибыль за период нетто, доля гросс-нотионала.

## research/r4_costs/report.py · 323 строк

R4 — отчёт: издержки на фактическом обороте книги.

- L15 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L16 `OUT = os.path.join(HERE, 'out')`
- L19 `MEDIAN_CELL_POSITIVE = True` — Пороги §8.3 спеки 03, утверждены до прогона.
- L20 `POSITIVE_CELLS_MIN = 0.6`
- L21 `SHARPE_MIN = 0.8`
- L22 `STRESSED_MIN_SHARE = 0.4`
- L25 `bp(x, d=1)`
- L29 `f(x, d=2)`
- L33 `median(v)`
- L40 `sharpe(cell, h)`
- L47 `split_arms(cells)` — Ячейки по рукам прогона: чистый остаток, он же на суженном универсуме, комбинация с funding.
- L67 `main()`

## research/r4_costs/run.py · 383 строк

R4 — издержки на фактическом обороте книги.

- L68 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L69 `RESEARCH = os.path.dirname(HERE)`
- L70 `OUT = os.path.join(HERE, 'out')`
- L71 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L72 `VECTORS = os.path.join(RESEARCH, 'r2_residual', '…`
- L88 `BP = 0.0001`
- L91 `EXPENSIVE_SHARE = [0.432, 0.326, 0.137, 0.147, 0.052]` — Доля дорогого тарифа по квинтилям оборота, замер A1 (раздел 6 спеки).
- L93 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L94 `COST_MULTIPLIER = 1.5`
- L95 `FORM_DAYS = 90`
- L96 `BLEND_WEIGHT = 0.5`
- L99 `load_vectors(interval)`
- L118 `load_fees(universe)` — Ставка тейкера по базовому активу. None там, где её нет.
- L129 `load_funding(universe, symbols)` — Ряды площадки исполнения из каталога A1. Обёртка над общим модулем.
- L134 `funding_score(funding, names, at, form_days=FORM_DAYS)`
- L138 `blended(sig, fs, arm)` — Сигнал руки прогона. §12.3, вес 0.5, комбинация рангов.
- L155 `rate_table(names, fees, state, rule)` — Ставка каждого имени по выбранному правилу назначения.
- L171 `run_cell(dates, vec, k, h, width, fees, states, funding, rule, …` — Проход по непересекающимся датам с переносом книги между ними.
- L237 `main()`

## research/r5_backtest/compare_arms.py · 135 строк

Сравнение рук прогона: чистый остаток против комбинации с funding.

- L39 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L40 `R4 = os.path.join(os.path.dirname(HERE), 'r4…`
- L41 `BOOTSTRAP = 4000`
- L42 `SEED = 20260728`
- L46 `sharpe(v, ppy)`
- L52 `paired_bootstrap(a, b, ppy, rng, n_boot=BOOTSTRAP)` — Распределение разности Sharpe при пересэмплировании ПАР периодов.
- L66 `main()`

## research/r5_backtest/report.py · 151 строк

R5 — отчёт: статистическая валидация и сверка со всеми критериями §8.3.

- L12 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L13 `OUT = os.path.join(HERE, 'out')`
- L16 `f(x, d=2)`
- L20 `pct(x, d=1)`
- L24 `main()`

## research/r5_backtest/run.py · 166 строк

R5 — статистическая валидация по рядам доходностей из R4.

- L32 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L33 `RESEARCH = os.path.dirname(HERE)`
- L34 `OUT = os.path.join(HERE, 'out')`
- L35 `R4 = os.path.join(RESEARCH, 'r4_costs', 'out…`
- L40 `DECLARED_TRIALS = 96`
- L45 `BLEND_TRIALS = 192` — §12.4: комбинация с funding есть новое СЕМЕЙСТВО испытаний, а не новая ячейка внутри старого. Число удваивает…
- L46 `SHARPE_MIN = 0.8`
- L47 `WORST_SUBPERIOD_MIN = 0.3`
- L48 `MAX_DRAWDOWN = 0.2`
- L51 `main()`

## research/r5_backtest/stats.py · 182 строк

R5 — статистическая валидация. Ядро расчёта.

- L40 `EULER = 0.5772156649015329`
- L43 `norm_cdf(x)`
- L47 `norm_ppf(p)` — Обратная функция нормального распределения, метод Акклама.
- L84 `moments(v)`
- L102 `sharpe(v, periods_per_year)` — Годовой Sharpe по ряду доходностей за период.
- L110 `expected_max_sharpe(n_trials, sr_std)` — Sharpe, который лучшая из `n_trials` пустышек даст случайностью.
- L119 `deflated_sharpe(v, periods_per_year, n_trials, sr_std)` — Обе версии поправки. Возвращает словарь, ничего не выбирая.
- L147 `max_drawdown(v)` — Максимальная просадка кривой эквити, построенной сложением.
- L166 `split_by_year(dates, v)` — Ряд, разложенный по календарным годам.
- L174 `split_equal(v, parts)` — Ряд, разрезанный на равные куски — подпериоды без привязки к дате.

## research/s10_policy/tournament.py · 680 строк

Турнир политик исполнения ситуационной книги (спека 10, этапы V1–V2).

- L40 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `EDGES = [22.0, 33.0]` — --------------------------------------------------------------------- Пространство политик. ОБЪЯВЛЕНО спекой…
- L51 `RRS = [1.5, 2.0, 3.0]`
- L52 `STOPS = ['q', 'm', 'none']`
- L53 `TAKES = [True, False]`
- L54 `AGES = [24, 72]`
- L59 `CURRENT = 'e33_rr2.0_sq_t1_a24'` — Вариант текущих правил живой книги — референс селектора. Правила книги сменились (гейт 22 → 33, зонд крайност…
- L61 `SLOTS = 6`
- L62 `SEL_STEP_D = 7`
- L63 `SEL_WIN_D = 28`
- L64 `MIN_WIN_TRADES = 30`
- L65 `N_SEEDS = 10`
- L66 `MIN_POINTS = 8`
- L67 `MIN_WF_TRADES = 300`
- L73 `KILL_D = 10` — Рука kill-10 (§7.1, правка владельца 2026-08-10 до первого прогона): вариант с отрицательной суммой за послед…
- L74 `KILL_MIN_TRADES = 10`
- L75 `DAY = 86400`
- L78 `variants()` — Все 72 объявленных варианта; ключ — имя ячейки в артефактах.
- L97 `legs_from_sheets(paths, log=print)` — Каждая строка каждого листа — кандидат в сделку.
- L147 `_leg(row, arm, hour, at)`
- L179 `outcome(bars, t0, side, adv, fav, age_h)` — Чем кончилась сделка: стоп, цель или срок.
- L214 `leg_outcomes(lg, bars)` — Исходы ноги по всем сочетаниям осей выхода — один раз на ногу.
- L238 `simulate(legs, outs, var)`
- L266 `daily(trades)` — День ВЫХОДА -> (сумма нетто б.п., число сделок).
- L285 `_win(series, d0, d1)` — Сумма и число сделок по дням `[d0, d1)`.
- L295 `_elig(series_by_key, keys, D)` — Годные варианты на день `D`: окно 28 суток, не тоньше 30 сделок.
- L305 `_bleeding(series, D)` — Сливает ли вариант по правилу kill-10 на день `D`.
- L315 `_rnd_pick(seed, point_idx, n)` — Зерно выводится ЧИСЛОМ из номера зерна и номера точки.
- L324 `walk_forward(series_by_key, keys, log=print)` — Кривые селектора, оракула, случайных и референса.
- L386 `_kill_arm(series_by_key, keys, points, last)` — Рука kill-10: базовый селектор плюс правило свежести (§7.1).
- L431 `_add(acc, series, d0, d1)`
- L439 `curve_dd(day_sums)` — Глубочайший провал накопленной кривой и её итог.
- L461 `_tot(acc)`
- L468 `verdict(wf)` — Вердикт по §8 спеки 10 — либо честное «диагностика, не вердикт».
- L513 `run(sheets, root, src=None, log=print)`
- L556 `report(legs, cells, wf, path)`
- L636 `main()`

## research/s10_policy/width.py · 368 строк

Профиль ожидания по МЕСТУ в сечении: сколько ног стоит открывать.

- L53 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L54 `RESEARCH = os.path.dirname(HERE)`
- L66 `AGE_H = 4` — Объявлено здесь: голое удержание на горизонте книги, места и ширины, по которым печатается профиль. Это не се…
- L67 `RANKS = (1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 4…`
- L68 `WIDTHS = (1, 2, 3, 5, 10, 20, 30, 50)`
- L71 `rank_legs(legs)` — Место ноги в своём сечении: 1 — самый крайний прогноз стороны.
- L89 `measure(sheets, root, src=None, log=print)`
- L122 `by_rank(rows)` — Ожидание по каждому месту отдельно.
- L137 `by_width(rows)` — Ожидание книги, берущей места 1..N, и её концентрация.
- L170 `step(ranks, edge=5)` — Средние по верхним местам и по хвосту — ДОБАВЛЕНО после прогона.
- L192 `bands(widths)` — Вклад полосы мест: сколько приносят места от прошлой ширины до этой. Из накопительных итогов это не читается,…
- L216 `reading(ranks, widths)` — Вывод пишется из чисел: убывает ли ожидание с местом.
- L243 `report(art, path)`
- L316 `main()`

## research/s11_horizon/horizon_probe.py · 348 строк

Зонд горизонта сигнала ситуационных книг: 4 ч против 5/6/8/12/24.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L54 `PROBE_HORIZONS = (4, 5, 6, 8, 12, 24)` — Сетка объявлена до прогона. 4 — контроль (живой сигнал книги), 24 — прямой вопрос владельца, остальные — «и т…
- L55 `SPLIT_FRAC = 0.6`
- L56 `EDGE_BP = 33.0`
- L57 `GATES = (('sit', 2.0, None), ('lo', 0.0, 1.5))`
- L59 `AGE_H = 24`
- L60 `SLOTS_NOTE = 'слоты и одна позиция на имя — моделью …`
- L63 `edge_pass(fwd)` — Нога слабее гейта входа не торгуется НИ в одной ячейке (край один на всю сетку), поэтому и не хранится. Первы…
- L73 `train_cols(n_hours, split_j, h)` — Колонки обучения горизонта `h` при разрезе `split_j`.
- L83 `gate_pool(legs, rr_max)` — Кандидаты книги: потолок отношения — правило книги lo.
- L96 `hour_epoch(hour_key)`
- L101 `cell_stats(trades)`
- L124 `fit_predict(h, arm, fit_fn, x, targets, elig, el_tr)` — Обучение трёх целей горизонта и предсказание на всей сетке.
- L152 `main()`
- L297 `write_report(art, path)`
- L336 `publish()` — Отчёт публикует сам прогон: шаг, который можно забыть, забывают (уроки D1 и width).

## research/s1_managed/ceilings.py · 257 строк

Потолок трёх рычагов против сквиза — до того, как строить хоть один.

- L45 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L46 `RESEARCH = os.path.dirname(HERE)`
- L47 `OUT = os.path.join(HERE, 'out')`
- L48 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L60 `KS = (7, 14)`
- L61 `HS = (5, 10)`
- L62 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L63 `DECLARED_STOP = {5: 0.35, 10: 0.45}`
- L65 `SHORT_SHARE = 0.35`
- L66 `DELIST_HORIZON = 30`
- L67 `REQUIRED_SHARPE = 1.53`
- L68 `DD_LIMIT = 0.2`
- L71 `load_vectors(tag)`
- L84 `delist_days(universe)`
- L99 `beta(book, mkt)` — Наклон доходности книги на доходность равновзвешенной волны.
- L117 `arr(v, key, sub)`
- L121 `main()`

## research/s1_managed/managed.py · 163 строк

S1 — книга carry с управлением риском. Ядро расчёта.

- L24 `VOL_FLOOR_PCT = 10`
- L27 `floored_vol(vol, ok, pct=VOL_FLOOR_PCT)` — Волатильность с полом по процентилю сечения.
- L49 `inverse_vol_weights(score, vol, width, min_vol=1e-06)` — Веса книги: ноги по рангу оценки, доли внутри ноги ∝ 1/σ.
- L80 `equal_weights(score, vol, width, min_vol=1e-06)` — Равные веса на том же универсуме — контрольная рука.
- L102 `apply_exits(w, pos_ret, exit_ret, exit_frac, fund)` — Доходность каждой ноги с учётом выхода по уровню.
- L126 `book_pnl(w, leg_ret)` — PnL книги и по ногам из доходностей позиций.
- L140 `unpaired_share(w, hit)` — Доля гросса, оставшаяся без пары после выходов. §5.3 спеки.
- L155 `turnover_from_exits(w, hit)` — Дополнительный оборот от сработавших выходов, в долях гросса.

## research/s1_managed/report.py · 149 строк

S1 — отчёт по артефакту прогона. Зависимостей не имеет намеренно.

- L12 `OUT = os.path.join(os.path.dirname(os.path.ab…`
- L13 `ARMS = (('base', 'равные веса, без выходов'), …`
- L18 `bp(x, d=1)`
- L22 `pct(x, d=1)`
- L26 `f(x, d=2)`
- L30 `main()`

## research/s1_managed/run.py · 417 строк

S1 — книга carry с управлением риском. Прогон.

- L46 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L47 `RESEARCH = os.path.dirname(HERE)`
- L48 `OUT = os.path.join(HERE, 'out')`
- L49 `A1 = os.path.join(RESEARCH, 'a1_universe', '…`
- L65 `STEP = '1h'`
- L66 `BARS_PER_DAY = 24`
- L69 `KS = (7, 14)` — Сетка §4 спеки 05 — та же, что в 04, и НЕ расширяется.
- L70 `HS = (5, 10)`
- L71 `WIDTHS = {'decile': 0.1, 'quintile': 0.2}`
- L77 `DECLARED_STOP = {5: 0.35, 10: 0.45}` — §3.3: уровень выхода объявлен ДО прогона и выведен из распределения доходности ноги (1-й процентиль, округлён…
- L78 `ROBUSTNESS_STOP = 0.25`
- L79 `LEVELS = sorted({*DECLARED_STOP.values(), ROBUST…`
- L81 `GRID_START = '2022-07-01'`
- L82 `GRID_END = '2026-06-01'`
- L83 `CHUNK_DAYS = 90`
- L84 `MIN_ASSETS = 30`
- L85 `MIN_FORWARD_BARS = 1`
- L86 `MIN_VOL = 1e-06`
- L89 `rebalance_dates(start, end)`
- L96 `volatility(R, i0, i1)` — Разброс часовых доходностей на окне оценки. NaN, если баров мало.
- L105 `exits(R, i_t, i_end, levels)` — Точки выхода по каждому уровню и каждой стороне.
- L139 `run_date(at, grid, PX, cols, live, funding)`
- L183 `process_chunk(con, dates, liq, universe, funding, interval)`
- L212 `arr(d, key)`
- L217 `build(vec, dates)` — Три руки на каждую ячейку, §3.3 и контроль.
- L301 `summarize(cells)`
- L329 `main()`

## research/s8_loop/adopt_book.py · 208 строк

Перенести историю одной книги в другую — когда это ТА ЖЕ книга.

- L50 `read_jsonl(path)` — Строки jsonl; битая строка пропускается, нет файла — пусто.
- L68 `key_of(rec)` — Ключ записи книги — (рука, час), как у `write_pick`.
- L73 `stamp(rec, rank)` — Проставить порядок сечения записи, сделанной до появления поля.
- L87 `conflicting(recs, rank)` — Записи, ЯВНО упорядоченные иначе, — перенос на них останавливается.
- L93 `merge(src, dst, rank)` — Слить записи источника в цель: дубли цели побеждают, порядок — по часу.
- L109 `write_rows(path, rows)` — Записать книгу целиком, оставив прежнюю версию рядом.
- L122 `carry_seq(seq_from, into, log=print)` — Продолжить нумерацию обучений, а не начать её заново.
- L156 `main(argv=None)`

## research/s8_loop/backfill.py · 380 строк

Дописать старым сделкам книгу входа и выхода из записи стакана.

- L55 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L56 `RESEARCH = os.path.dirname(HERE)`
- L71 `OUT = os.path.join(HERE, 'out')` — Каталоги те же, что у цикла, но `train` не импортируется: он тянет numpy, а пересчёту нужны только стандартна…
- L72 `MODEL_DIRS = {False: os.path.join(OUT, 'model'), Tru…`
- L76 `BOOKS = 'books.jsonl'`
- L79 `read_rows(path)`
- L95 `class Books` — Книга на заданные моменты — потоком, без подъёма часа в память.
  - L112 `Books.__init__(self, root, log=None)`
  - L117 `Books._stream(self, path)`
  - L135 `Books._hour(ts)`
  - L139 `Books.collect(self, want, tol=120.0)` — `{(символ, час): [моменты]}` → `{(символ, момент): книга}`.
- L190 `plan(picks, reviews, have, log, hold_h=TR.HOLD_H)` — Что именно надо прочитать: `{(символ, час): {моменты}}` и заявки.
- L233 `stamp(jobs, got, log)` — Заявки + прочитанные книги → записи приписного файла.
- L247 `compare(picks, reviews, log, books=None)` — Счёт до и после — по каждой руке, деньгами.
- L271 `report(before, after, n1, n2, reads, mdir)` — Отчёт о пересчёте: что было, что стало, чего не хватило.
- L300 `main()`

## research/s8_loop/bookfeat.py · 440 строк

S8.1, этап 2: признаки и цели из почасовых сводок — чистая математика.

- L28 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L29 `RESEARCH = os.path.dirname(HERE)`
- L41 `F = _ilu.module_from_spec(_spec)`
- L47 `HORIZONS = (1, 4, 24)`
- L50 `SIGNAL_H = 4` — Горизонт сигнала: на нём книга торгует, и только на нём заведены производные цели (квантильный стоп, единицы…
- L68 `MIN_SNAPS = 1800`
- L69 `MIN_SPAN_SEC = 1800`
- L70 `MAX_GAP_SEC = 300`
- L71 `MIN_SECTION = 30`
- L74 `rel_to_past(x, win=NORM_WIN, min_n=NORM_MIN)` — x к своей скользящей медиане. Текущий час входит в окно — он известен в момент расчёта; будущее не входит (за…
- L84 `imbalance(b, a)`
- L91 `eligibility(close, n_snap, span=None, gap=None)` — Час участвует в сечении, если книга писалась почти весь час.
- L118 `forward_path(close, high, low, h)` — Максимальный ход в пользу/против за следующие h часов, в б.п.
- L153 `rolling_extreme(x, win, fn)` — Скользящий максимум/минимум за последние win часов, только назад.
- L167 `formations(s)` — Формации владельца (зажимка, наклонка, проторговка) — числами.
- L214 `_opt(s, key, like)` — Матрица сводки, которой может не быть (поле добавлено позже начала записи): нет — весь ряд NaN, признак честн…
- L221 `lagged_change(x, k)` — x[t]/x[t−k] − 1; дыра в любом конце — NaN, а не склейка.
- L230 `clock_features(s, like)` — Час суток и день недели из начала часа — сезонность.
- L249 `leader_features(s, close)` — Ход BTC и своего сектора за 4 часа — запаздывание за лидером.
- L288 `dist_round(close)` — Близость к круглому числу в долях шага круглой сетки, 0…0.5.
- L303 `feature_pack(s)` — Все признаки спеки 08 §3 разом из словаря матриц сводки.
- L389 `target_pack(s, r, elig, beta, horizons=None)` — Цели: остаток к волне + путь, по каждому горизонту.

## research/s8_loop/books.py · 315 строк

Реестр книг: ОДНО место, где записано, какие книги существуют.

- L49 `REGISTRY = ({'key': 'h4', 'dir': 'model', 'label':…` — Порядок записей = порядок кнопок на странице. Менять его — менять показ, поэтому он объявлен здесь, а не соби…
- L107 `REMOVED_HORIZONS = (1,)` — Горизонты турнира темпов, снятые решением владельца. Держим ЧИСЛАМИ, а не ключами: цикл заводит книги обходом…
- L112 `CANON_ARM = 'gbm'` — Каноническая рука согласной книги. Её руки тождественны по построению, и показ сводится к одной; та же рука к…
- L115 `all_keys(books=None)`
- L119 `by_key(key, books=None)`
- L126 `dirs(books=None)` — Ключ → каталог. Карта существует затем, чтобы каталог НЕ выводился соглашением `model_<ключ>`: у четырёх книг…
- L133 `traded(books=None)` — Книги, держащие деньги, в порядке реестра.
- L139 `echo_keys(books=None)`
- L143 `agree_keys(books=None)`
- L157 `menu(books=None)` — Кнопки страницы: ключ и подпись, в объявленном порядке.
- L170 `MAIN_DIR = 'model'` — Каталог книги строится циклом как `MODEL_DIR + суффикс`, а не как «out/<каталог>»: в демо- и песочном прогоне…
- L173 `suffix(key, books=None)`
- L183 `family(name, books=None)`
- L204 `EXTRAS_FILE = 'books_extra.json'` — --- Книги фабрики --------------------------------------------------- Реестр выше — ЯДРО: книги, заведённые р…
- L206 `FAMILIES = ('timer', 'sigma', 'basket', 'agree', '…`
- L211 `_SAFE = set('abcdefghijklmnopqrstuvwxyz01234567…` — Ключ уезжает в адрес страницы, каталог — в путь на диске. Файл пишет автомат, поэтому оба проверяются набором…
- L214 `_safe_name(s)`
- L218 `_extras_path(path=None)`
- L226 `extras(path=None)` — Книги фабрики с диска: (список, причина отказа или None).
- L307 `load(path=None)` — Все книги: ядро плюс кандидаты фабрики, и причина отказа.

## research/s8_loop/cycle_health.py · 324 строк

Бюджет часового цикла: укладывается ли он в час и куда уходит время.

- L41 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L42 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L43 `OUT = os.path.join(HERE, 'out')`
- L44 `HOUR = 3600.0`
- L47 `DAYS_SHOWN = 14` — В таблицу идут последние сутки: вся история — это сотни строк, и отчёт, который не читается, ничем не лучше о…
- L50 `log_(m)`
- L54 `median(vals)` — Медиана, а не «средний по счёту элемент».
- L68 `pct(vals, q)`
- L76 `spearman(xs, ys)` — Ранговая связь — своя, потому что модуль обязан быть stdlib.
- L114 `read_log(path)`
- L131 `day_of(row)` — Сутки строки — по ЧАСУ СЕЧЕНИЯ (`hour`, вида ГГГГ-ММ-ДД-ЧЧ).
- L154 `by_day(rows)`
- L163 `summarize(rows, man)`
- L203 `verdict(s)` — Вердиктовая фраза выводится ИЗ ЧИСЕЛ, а не стоит рядом с ними.
- L228 `fmt(v, spec='.1f', dash='—')`
- L232 `write_report(path, s, meta)`
- L277 `publish(msg)`
- L282 `main(argv=None)`

## research/s8_loop/diag_books.py · 68 строк

Диагностика шага книг: каталоги model_h24*, хвост журнала цикла.

- L12 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L13 `OUT = os.path.join(HERE, 'out')`
- L16 `main()`

## research/s8_loop/families.py · 525 строк

Семейства признаков — вид СИТУАЦИИ словами трейдера, и объяснение каждого простыми словами на двух языках.

- L26 `FAMILY_EXACT = {'imb_best': 'book', 'spread_rel': 'boo…`
- L44 `FAMILY_PREFIX = (('imb_', 'book'), ('depth_b', 'book'),…`
- L51 `family(name)` — Семейство признака; незнакомое имя — «other», и тест на живом списке признаков обязан держать «other» пустым.
- L70 `GLOSSARY = (('absorption', {'title': 'Absorption —…` — Порядок — как читает трейдер: сперва то, что видно в стакане и ленте, потом производные рынка, потом контекст…
- L519 `GLOSSARY_BY_KEY = dict(GLOSSARY)`
- L525 `BILINGUAL = ('title', 'plain', 'reads')` — Поля, которые обязаны быть на обоих языках. Список объявлен здесь и проверяется тестом: приписать семейство и…

## research/s8_loop/negdur_restat.py · 200 строк

Переоценка сделок с отрицательной длительностью — седьмой дефект кассы.

- L32 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L39 `TOL_SEC = 600` — Допуск поиска цены: свеча решения может отсутствовать (дыра записи), берём последнюю не старше десяти минут д…
- L42 `_get(url)`
- L47 `affected(rows)` — Закрытые сделки, чей выход датирован РАНЬШЕ входа.
- L62 `reprice(t, base, key)` — Цена середины на момент решения (review_at) из записи сборщика.
- L90 `main()`

## research/s8_loop/nn.py · 141 строк

Нейросеть на numpy — «AI-рука» турнира моделей (спека 08, объявлена до окна вердикта; испытаний в вердикте ст…

- L22 `LAYERS = (64, 32)`
- L23 `LR = 0.001`
- L24 `EPOCHS = 30`
- L25 `BATCH = 4096`
- L26 `L2 = 1e-05`
- L29 `class NN`
  - L30 `NN.__init__(self, ws, bs, mu, sd, med, base)`
  - L38 `NN._prep(self, x)`
  - L44 `NN.predict(self, x)`
  - L50 `NN.contrib(self, x)` — Вклад признака: прогноз минус прогноз «будь признак обычным».
- L71 `fit(x, y, seed, epochs=EPOCHS, tau=None)` — `tau` — уровень квантиля; `None` оставляет прежнюю квадратичную потерю бит в бит. Смысл тот же, что у бустинг…

## research/s8_loop/one_name.py · 199 строк

Цена правила «одно имя — одна позиция»: пересчёт по записанным сделкам.

- L43 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L47 `RULES = ('hedge', 'netting', 'one', 'netting_pl…`
- L50 `_end(t)`
- L54 `apply_rule(rows, rule)` — Список сделок под выбранным правилом; исходный не трогается.
- L120 `stats(rows, arm, slots=None, hold_h=TR.HOLD_H)`
- L150 `main()`

## research/s8_loop/probe_report.py · 316 строк

Отчёт о пробном прогоне конвейера — файлом, а не пересказом консоли.

- L39 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L40 `OUT = os.path.join(HERE, 'out')`
- L41 `ARMS = ('gbm', 'nn')`
- L42 `RU_ARM = {'gbm': 'деревья (ML)', 'nn': 'сеть (AI…`
- L52 `jload(path)`
- L60 `jlines(path)`
- L74 `step(ok, name, detail='')` — Строка таблицы шагов. Состояний ТРИ, а не два.
- L88 `write(d, out_path)` — Собрать отчёт по каталогу артефактов. Возвращает путь.
- L299 `main()`

## research/s8_loop/sit_absorb.py · 245 строк

Живые события ситуационной книги → строки выбора и разбора.

- L34 `read_jsonl(path)` — Строки jsonl; битая строка пропускается, нет файла — пусто.
- L50 `book_lock(mdir)` — Замок книги: выборы и разбор пишут два процесса по очереди.
- L68 `sit_open_positions(picks, reviews, arm)` — Открытые позиции ситуационной книги — перечитыванием файлов.
- L99 `fresh_picks(mdir, arm, picks_all=None)` — Живые входы сканера, ещё не ставшие строками выбора.
- L141 `write_picks(mdir, recs, log_=None)`
- L152 `live_exit_rows(mdir, arm, picks_all=None, reviews_all=None)` — Строки разбора для позиций, закрытых ЖИВЫМ сторожем.
- L203 `write_reviews(mdir, arm, by_hour, ladders, log_=None)` — Дозапись строк разбора; лесенка выхода — из переданной книги.
- L221 `absorb(mdir, ladder_of, log_=None, arms=('gbm', 'nn'))` — Полное поглощение живых событий книги, под замком.

## research/s8_loop/summary.py · 341 строк

S8.1, этап 1: запись стакана → почасовая сводка (спека 08 §3, §9).

- L34 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L35 `RESEARCH = os.path.dirname(HERE)`
- L40 `BOOK_ROOT = os.path.join(RESEARCH, 'b1_book', 'out')`
- L41 `OUT = os.path.join(HERE, 'out', 'summary')`
- L45 `EAT_BAND = 0.001` — Самая узкая полоса, в которой меряется «выедено против показанного»: знаменатель — показанная глубина у цены,…
- L48 `_med(v)`
- L57 `summarize_hour(book_rows, trade_rows, metrics_rows=None, liq_ro…` — Один (символ, час) → одна строка сводки.
- L234 `hours_closed(now=None, back=None)` — Часы, уже закрытые записью (текущий не берётся — он пишется).
- L244 `done_hours(day_path)`
- L258 `run(root, out_dir, hours_back, log, redo=0)` — redo — пересвести последние N часов, даже если они уже готовы.
- L322 `main()`

## research/s8_loop/synth.py · 83 строк

Синтетические сводки часов: заложенный сигнал, который цикл обязан найти.

- L34 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L40 `write_summaries(d, S=36, D=260, seed=5, start='2026-08-01-00')` — Разложить синтетические сводки по каталогу `d`.

## research/s8_loop/trades.py · 1844 строк

Сделки модели: выбор + разбор фактом = одна сущность с состоянием.

- L42 `HOLD_H = 4`
- L48 `LADDER_CAP_USD = 5000.0` — Максимальный нотионал, до которого лесенка стамповывается в запись. Фазы C–D — капитал $1–20 тыс., то есть по…
- L54 `ROUND_COST_BP = 11.0` — Круг издержек живёт ЗДЕСЬ, а не в цикле обучения: его читают и цикл (при разборе), и сборщик (при переоценке…
- L69 `LEVEL_EXITS = ('цена прошла обещанный ход против', 'ц…` — Выходы, которые ставили МЫ САМИ: стоп и цель. Причины выхода живут строками в разборе, и список обязан быть о…
- L73 `by_level(t)` — Сделка закрыта нашим же уровнем (стоп или цель).
- L78 `_ts(hour)` — `2026-08-03-17` → epoch-секунды начала часа.
- L87 `_hour_of(ts)`
- L92 `hour_end(hour)` — Когда час кончился. Нужно тем, кто решает, ждать ли сводку.
- L98 `position_path(side, mae_v, mfe_v, h=4)` — Ход ПРОТИВ и В ПОЛЬЗУ позиции из целей, считанных по цене.
- L116 `rr_of(t)` — Отношение обещанной прибыли к обещанному риску у ЭТОЙ сделки.
- L140 `by_rr(trades, rr_min)` — Сделки, чьё обещанное отношение не ниже порога.
- L165 `wider_stop(mean_adv, q_adv)` — Дальний из двух уровней стопа — квантильный либо средний.
- L186 `path_fields(side, mae_v, mfe_v, h=4, mae_q=None, mfe_q=None)` — Оба конца пути готовыми полями записи выбора.
- L222 `_FEES = None`
- L225 `fee_table()` — Таблица ставок, читаемая один раз на процесс.
- L239 `cum_ladder(levels, cap_usd=LADDER_CAP_USD)` — Лесенка → `[[цена, накопленный нотионал], …]` до потолка.
- L263 `walk(cum, notional)` — Средняя цена рыночной заявки на `notional` долларов.
- L289 `exec_cost(t, size, table=None)` — Полный круг издержек ЭТОЙ сделки: комиссия + проскальзывание.
- L335 `_gift(px, px_live, side)` — Насколько вход по цене сигнала выгоднее доступного в решении.
- L348 `load_books(path)` — Дописанные задним числом книги: `{(рука, час, символ): {in, out}}`.
- L373 `pct(bp)` — Базисные пункты → процент движения цены, строкой.
- L395 `lvl(bp)` — Базисные пункты → процент БЕЗЗНАКОВОЙ величиной.
- L409 `tid_of(t)` — Короткий постоянный идентификатор сделки (просьба владельца).
- L429 `build(picks, reviews, now=None, hold_h=HOLD_H, px_at=None, book…` — Сделки из выборов и разборов, свежие сверху.
- L668 `net_positions(trades)` — Одно имя — одна позиция: долив своей стороны, схлопывание чужой.
- L755 `START_BALANCE = 3000.0` — Решение владельца 2026-08-13: капитал каждой руки каждой книги — 3000 $. Счёт — чистая функция от файлов, поэ…
- L761 `CAND_START_BALANCE = 1000.0` — Депозит СТРАТЕГИИ автономной системы (решение владельца 2026-09-02): каждой книге-кандидату по умолчанию 1000…
- L764 `start_of(man)` — Депозит книги: из её МАНИФЕСТА, а не из константы читателя.
- L785 `FIXED_RISK_SHARE = 0.001` — Риск на сделку книги равного риска (доля капитала): стоп всегда стоит −R, тейк при RR r — +r·R, и математика…
- L809 `CASH_RULES_VERSION = 5` — Версия ПРАВИЛА КАССЫ. Счёт Python — чистая функция от файлов и лечится пересчётом сам; журнал тени на Rust до…
- L818 `NAME_CAP_SHARE = 0.1` — Потолок суммарной экспозиции на ОДНО имя, в долях текущего капитала книги (cash + busy — тот же знаменатель,…
- L835 `DAY_BRAKE_SHARE = 0.01` — Дневной тормоз — второй ЗАБОР (решение владельца 2026-08-29 по реплею `probe_drain/DRAIN-brake-0824.md`): ког…
- L836 `DAY_BRAKE_STALE_SEC = 900`
- L837 `DAY_BRAKE_FILE = 'day_brake.json'`
- L840 `money_ts(t)` — Момент, когда деньги сделки стали известны.
- L850 `day_realized(pairs, now_ts)` — Реализованный результат текущих суток UTC: Σ pnl по моментам денег. Пара без момента не входит — неизвестное…
- L864 `day_brake_limit(n_books, arms=2)` — Порог тормоза в долларах: доля от суммарного капитала торгуемых не-эхо книг. Выводится, а не повторяется числ…
- L872 `read_day_brake(path, now_ts, stale_sec=DAY_BRAKE_STALE_SEC)` — Состояние тормоза из файла единственного писателя (сборщик).
- L890 `day_brake_active(st, now_ts, stale_sec=DAY_BRAKE_STALE_SEC)` — Действует ли тормоз СЕЙЧАС. Одно правило на файл и на память сборщика — две реализации однажды разошлись бы.…
- L904 `account(trades, arm, start=START_BALANCE, hold_h=HOLD_H, table=…` — Счёт ОДНОГО капитала: экспозиция не превышает его.
- L1139 `dd_money(trades, deposit=START_BALANCE)` — Просадку — в деньгах и в долях ДЕПОЗИТА, а не позиции.
- L1169 `merge_adds(trades)` — Слитая позиция для ПОКАЗА: долив — не отдельная сделка.
- L1295 `summary(trades, arm=None, capital=None, start=None)` — Сводка: закрытые — фактом, открытые — переоценкой.
- L1423 `_dd(rows, out)` — Просадка по сделкам: худшая, медианная и сколько их измерено.
- L1464 `_unreal(rows, out, capital)` — Переоценка открытых — отдельными полями, не смешивая с фактом.
- L1505 `hour_rows(sum_dir, pairs)` — Цена часа из почасовых сводок: `{(символ, час): {c, hi, lo}}`.
- L1548 `entry_prices(sum_dir, pairs)` — Цены входа: `{(символ, час): цена}` — закрытие часа сигнала.
- L1558 `live_hours(t, hold_h=HOLD_H, now=None)` — Часы, которые позиция прожила: от `час+1` до часа закрытия.
- L1586 `excursion(trades, rows, hold_h=HOLD_H, now=None)` — Худший ход ПРОТИВ позиции за время удержания, в б.п.
- L1632 `equity(trades, arm, rows, start=START_BALANCE, hold_h=HOLD_H, c…` — Почасовая кривая счёта С УЧЁТОМ открытых позиций.
- L1691 `worst_open(curve, deposit=START_BALANCE)` — Худший момент по КНИГЕ: все открытые позиции разом.
- L1717 `thin(curve, cap=600)` — Кривая для показа: не длиннее `cap` точек, без потери провалов.
- L1743 `merge(curves)` — Общая кривая нескольких счетов: сумма по часам.
- L1782 `max_dd(curve)` — Максимальная просадка кривой: доля от достигнутого максимума.
- L1814 `mark(trades, prices, cost_bp=ROUND_COST_BP)` — Проставить открытым сделкам нереализованный результат.
- L1842 `by_symbol(trades, sym)` — Сделки одной монеты — для меток на её графике.

## research/s8_loop/train.py · 3865 строк

S8.2: цикл переобучения модели на стакане (спека 08 §5).

- L37 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L38 `RESEARCH = os.path.dirname(HERE)`
- L63 `OUT = os.path.join(HERE, 'out')`
- L64 `MODEL_DIR = os.path.join(OUT, 'model')`
- L71 `LIVE_MODEL_DIR = MODEL_DIR` — Боевой каталог, запомненный НА ИМПОРТЕ. Демо-прогон, песочный контур и тесты подменяют `MODEL_DIR`, а состав…
- L75 `FACTORY_OUT = os.path.join(RESEARCH, 'factory', 'out')` — Откуда берутся кандидаты и куда пишется состав их книг. Константами, а не выражением на месте: тест обязан по…
- L76 `EXTRAS_PATH = os.path.join(HERE, BK.EXTRAS_FILE)`
- L78 `MODEL_VERSION = 2`
- L86 `STOP_H = 4` — Горизонт, на котором ставятся заявки (он же `SIT_SIGNAL_H` ниже: сигнал ситуационной книги). Квантильные цели…
- L97 `STOP_TAU = 0.2` — Доля случаев, в которых цена ВПРАВЕ зайти за стоп. Число объявлено до прогона и выведено из замера `s9_sweep/…
- L103 `QUANT_TARGETS = {f'maeq_{STOP_H}h': (f'mae_{STOP_H}h', …` — Цель квантильной модели — та же КОЛОНКА, что у средней; отличается только потеря обучения. Отдельная колонка…
- L111 `RANK_Z = f'fwd_{FB.SIGNAL_H}h_z'` — Ранжирующая цель книги в единицах собственной σ монеты. Заведена по замеру отбора: размах выбранной моделью м…
- L114 `rank_z(h)` — Ключ порядка сечения в единицах σ для своего горизонта.
- L124 `TARGETS = [f'{k}_{h}h' for k in ('fwd', 'mfe', 'm…`
- L129 `target_col(tgt)` — Колонка целей, по которой обучается и оценивается цель `tgt`.
- L143 `ARMS = (('gbm', gbm.fit), ('nn', nn.fit))` — Турнир: две руки на одних данных, объявлены до окна вердикта. gbm — деревья (ML), nn — сеть (AI-рука). Прогно…
- L151 `RETRY_SEC = 3600` — Цикл ЕЖЕЧАСНЫЙ, а не суточный (спека §5 писала «раз в сутки» про переобучение). Причина не в качестве весов —…
- L165 `TRAIN_EVERY_H = 24` — Каденция переобучения. Час — темп КНИГ, а не весов: замер `cycle_health` 2026-08-31 показал, что цикл перевал…
- L168 `MARGIN_SEC = 120` — Запас после закрытия часа: сначала его надо свести по всем монетам, и только потом обучаться. Он же есть нижн…
- L175 `PRETEST_MARGIN_SEC = 360` — Предпросмотр сводку не пишет — он читает готовую, а пишет её боевой цикл. Значит приходить он обязан ПОСЛЕ не…
- L177 `STALE_RETRY_SEC = 300` — Пришёл, а сводка ещё не дописана — ждать час незачем: пробуем скоро.
- L178 `MIN_TRAIN_SECTIONS = 48`
- L181 `PROBE_MIN_SECTIONS = 4` — Пробный прогон: тот же конвейер на том, что уже накоплено, но в свой каталог и со своей пометкой. Порог 48 не…
- L182 `PROBE = False`
- L186 `PRETEST = False` — Предпросмотр: та же модель на том, что уже накоплено, своим циклом и в свой каталог. Задача — показать владел…
- L187 `PRETEST_MIN_SECTIONS = 4`
- L191 `HEDGE_PRETEST = 'грубый: бета = 1 (посимвольная не оцен…` — Режим хеджа — строкой, а не флагом: она едет в манифест, на страницу и в проверку смены режима. Смена этой ст…
- L192 `HEDGE_LIVE = 'включён'`
- L193 `CANARY_STOP = 0.05`
- L197 `MIN_TARGET_ROWS = 1000` — Меньше тысячи строк цель не обучается: гейт главной цели, пропуск цели в обучении и объяснение «книга ждёт» н…
- L201 `START_BALANCE = 1000.0` — Бумажный счёт руки: старт $1000, 6 позиций равными долями, тейкерский круг 11 б.п. с позиции, без проскальзыв…
- L204 `ROUND_COST_BP = TR_COST` — Круг издержек — из `trades`: его читает и сборщик, переоценивая открытые сделки. Одно определение на двоих.
- L205 `SEED0 = 20260801`
- L208 `log(m)`
- L219 `FEATURE_RU = (('imb_best', 'перекос у лучших цен'), …` — --- мысли модели: перевод её состояния в трейдерские слова ------------ Это НЕ речь модели (бустинг не говори…
- L264 `feat_ru(name)`
- L271 `_ic_words(v)`
- L281 `think(prev_man, man, ic_rows, picks)` — Мысли одного цикла. Чистая функция — закреплена тестами.
- L356 `load_matrices(sum_dir)` — Сводки всех символов → словарь матриц (символы, часы).
- L421 `context_mats(syms, grid)` — Контекст, который несут не сводки, а сами оси: время и сектор.
- L451 `assemble(mats, horizons=None)` — Матрицы сводки → (X, имена признаков, цели, elig, r).
- L492 `flatten(x, y, elig)` — (S, H) → строки обучения: только сечения, только закрытые цели.
- L498 `novelty_bounds(x, elig)` — Диапазон обучения по каждому признаку: 0.5–99.5 процентили по строкам сечений. Это ЗАМЕР, а не правило (идея…
- L516 `novelty(xrow, lo, hi)` — Доля признаков монеты вне диапазона обучения, 0…1.
- L531 `section_ic(pred_mat, y_mat, elig, cols)`
- L542 `predict_matrix(model, x, elig)`
- L551 `PREDS_KEEP_H = 48`
- L552 `WHY_TOP = 3`
- L553 `WHY_FLOOR_BP = 1.0`
- L556 `explain_rows(model, xj, names)` — «Почему прогноз такой»: главные признаки КАЖДОЙ строки, в б.п.
- L605 `save_preds(arm, hour, syms, rows_m, pred, target='fwd_4h')` — Сохранить ВЕСЬ вектор предсказаний сечения, а не только выбор.
- L633 `score_preds(targets, elig, grid, syms, log_)` — Оценить сохранённые векторы, у которых форвард уже закрылся.
- L720 `_hours_apart(a, b)` — Сколько часов между двумя ключами часа. Не смогли — считаем много.
- L730 `eval_previous(x, targets, elig, grid, log_)` — Живой вневыборочный IC: прежние веса на часах после их обучения.
- L777 `CANARY_SEEDS = 5`
- L780 `canary_many(x, targets, elig, grid, seed, log_, name, seeds)` — Канарейка несколькими зёрнами: среднее — оценка, разброс — шум.
- L816 `canary_verdict(med)` — Три состояния канарейки, а не два.
- L836 `canary_target(targets, elig, want='fwd_4h', need=MIN_TARGET_ROW…` — На какой цели считать канарейку.
- L862 `canary(x, y, elig, grid, seed, log_, name='fwd_4h')` — Обучение на перемешанных целях: кричит только на грубую течь.
- L882 `write_readiness(syms, grid, per_hour, n_sections, n_feat, hist_…` — Готовность к обучению — файлом, а не строкой в журнале.
- L923 `fresh_on_mode_change(mode, log_=None)` — Сменился режим хеджа — прежние выборы и счёт отставляются в архив.
- L968 `tradable_rows(rows_m, syms, ref=None, flat=None)` — Строки сечения, которыми МОЖНО торговать: не-крипто и плоское прочь.
- L992 `write_outcome(reason, **nums)` — Чем кончился ЭТОТ цикл — отдельным файлом, всегда.
- L1020 `_read_jsonl(path)` — Строки jsonl; битая строка пропускается, нет файла — пусто.
- L1058 `RANK_BY_HORIZON = {1: True, 4: True, 24: False}` — Решение владельца (2026-08-11): книги 4 ч, 1 ч и ситуационная упорядочиваются в единицах СОБСТВЕННОЙ волатиль…
- L1061 `rank_key_for(h, sigma=None)` — Ключ порядка сечения книги горизонта `h`.
- L1071 `book_key(h, sigma=False)` — Ключ книги по горизонту и порядку сечения.
- L1084 `book_dir(h, sigma=False)` — Каталог книги горизонта `h` часов рядом с главным каталогом.
- L1093 `review_arm(mdir, arm, hold_h, targets, si, grid, book_root, log…` — Разобрать все неразобранные выборы одной руки одной книги.
- L1189 `SIT_SLOTS = 6` — --- ситуационная книга ----------------------------------------------- Решение владельца (2026-08-07): книга,…
- L1190 `SIT_MIN_EDGE_BP = 3 * ROUND_COST_BP`
- L1191 `SIT_MIN_RR = 2.0`
- L1203 `SIT_LO_MAX_RR = 1.5` — Книга НИЗКОГО RR (решение владельца 2026-08-22). Замер по наблюдательной записи (2321 закрытая сделка, неделя…
- L1204 `SIT_LO_SLOTS = 6`
- L1215 `SIT_MIN_DISC_BP = ROUND_COST_BP` — Цена обязана ПРИЙТИ К НАМ, а не лист — объявить. Остаток хода обязан превышать то, что обещал сам лист, на кр…
- L1233 `SIT_ARM_BAND_BP = ROUND_COST_BP` — Полоса нечувствительности взведения. Требование «имя было замечено НЕ проходящим гейт» отличает пересечение п…
- L1245 `SIT_MAX_EATEN = 0.5` — Потолок на съеденную долю обещания против (правило v11, часть 2). Ход цены против прогноза до входа считался…
- L1246 `SIT_MAX_AGE_H = 24`
- L1253 `SIT_R_EXIT_POLICY = 'levels_only'` — Книга равного риска (решение владельца 2026-08-13): сделка закрывается ТОЛЬКО уровнем — стопом или тейком. Ра…
- L1258 `SIT_LEVELS_AGE = 'levels_age'` — Политика кандидата фабрики: уровни и предел возраста, без разворота прогноза. Ровно то, чем закрывает сделку…
- L1264 `SIT_AGE_ONLY = 'age_only'` — Только предел возраста: ни стопа, ни цели, ни разворота прогноза. Так устроена ось `geom: timer` фабрики — «в…
- L1272 `SIT_R_NOISE_MULT = 1.5` — Второе правило той же книги (решение владельца после #ptadyrc): запас до стопа обязан быть не тоньше ПОЛУТОРА…
- L1282 `SIT_R_MIN_STOP_BP = TR.FIXED_RISK_SHARE / TR.NAME_CAP_SHARE…` — Третье правило той же книги (решение владельца: «размер тейков и стопов должен быть одинаковый»): вход только…
- L1294 `SIT_OBS_SLOTS = 24` — Наблюдательная книга: те же гейты, КРОМЕ отношения. Нужна затем, чтобы фильтру владельца было что показывать…
- L1295 `SIT_OBS_MIN_RR = 0.0`
- L1296 `SIT_SIGNAL_H = 4`
- L1357 `SIT_RULES_VERSION = 13` — Версия ПРАВИЛ книги — часть её определения (урок RULES_VERSION). v1 — часовые входы, и в выходах жил дефект п…
- L1375 `BOOK_FILES = ('picks.jsonl', 'review.jsonl', 'entrie…` — Файлы, которые принадлежат КНИГЕ, а не модели. Всё остальное в каталоге — веса, манифест модели, сохранённые…
- L1379 `archive_book(mdir, dst, log_=None)` — Перенести КНИГУ каталога `mdir` в каталог `dst`.
- L1416 `fresh_book_on_rank_change(mdir, want, log_=None, floor=None)` — Сменился ПОРЯДОК сечения — старая книга уходит в архив.
- L1487 `fresh_sit_on_rules_change(mdir, log_=None, rules=None, version=…` — Сменились правила ситуационной книги — старая уходит в архив.
- L1539 `situational_arm(mdir, arm, models, x, mats, syms, rows_m, j_las…` — Один проход ситуационной книги: сначала выходы, потом входы.
- L1779 `H4_FLOOR_BP = 30.0` — Пол на вход книги 4 ч — из зонда крайности (probe_extreme, 2026-08-12): исход растёт монотонно с величиной пр…
- L1782 `REMOVED_BOOKS = set(BK.REMOVED_HORIZONS)` — Снятые горизонты турнира темпов — из реестра книг, а не числом здесь: почему часовая удалена, записано там же…
- L1802 `BASKET_H = 24` — Корзинные книги-эхо 24 ч (решение владельца 2026-08-14): под-модель, которая смотрит не на сделку, а на ОБЩИЙ…
- L1803 `BASKET_TAKE_SHARE = 0.05`
- L1804 `BASKET_FLOOR_SHARE = 0.05`
- L1805 `BASKET_TAKE_REASON = 'корзина дошла до цели'`
- L1806 `BASKET_FLOOR_REASON = 'корзина дошла до предела убытка'`
- L1817 `BASKET_AGE_H = 24` — Третья корзинная книга `model_h24c` (решение владельца 2026-08-30, по реплею probe_basket серии 1–2): у ног Н…
- L1818 `BASKET_AGE_REASON = 'корзина дошла до предела возраста'`
- L1819 `BASKET_SLOTS = 6 * BASKET_H`
- L1822 `make_pick(arm, hold_h, models, x, mats, syms, rows_m, j_last, g…` — Выбор монет одной книги: цели fwd/mae/mfe СВОЕГО горизонта.
- L1939 `write_pick(mdir, picks)` — Один выбор на (руку, час) — и не больше.
- L1956 `rebuild_accounts(mdir, hold_h, slots=None)` — Счета книги — пересборкой ЦЕЛИКОМ из выборов и разборов.
- L1995 `echo_picks(mdir, src_dir, cur_hour)` — Скопировать в книгу-эхо выборы источника за текущий час.
- L2014 `echo_reviews(mdir, src_dir)` — Скопировать разборы источника для выборов, живущих в эхе.
- L2040 `agree_keys(src_dir, hour)` — Что выбрала КАЖДАЯ рука источника за час: {(имя, сторона)}.
- L2062 `agree_echo_cycle(mdir, src_dir, cur_hour, hold_h, log_)` — Один проход согласной книги-эха: пересечение рук источника.
- L2135 `basket_state(trades, arm)` — Деньги корзины руки: сумма нереализованного нетто открытых.
- L2158 `basket_close_records(op, arm, reason, now, books=None)` — Записи разбора закрытия корзины — по одной на час выбора.
- L2196 `basket_echo_cycle(mdir, src_dir, cur_hour, take_share, floor_sh…` — Один проход корзинной книги-эха: копия, переоценка, решение.
- L2272 `live_px(syms, book_root, now=None, log_=None)` — Цена, доступная В МОМЕНТ РЕШЕНИЯ, а не в момент сигнала.
- L2306 `book_at(sym, ts, book_root, tol=120.0)` — Снимок книги, ближайший к моменту `ts` и не позже него.
- L2340 `stamp_book(syms, ts, book_root, log_=None, what='')` — `{символ: {mid, b, a, t}}` — книга для расчёта исполнения.
- L2366 `log_cycle(row, log_)` — Строка журнала циклов. Один писатель на оба пути.
- L2383 `train_due(prev_man, now_ts, every_h=None)` — Пора ли переобучать: (да/нет, причина словами).
- L2420 `load_prev_models(names)` — Веса ПРОШЛОГО цикла с диска — для шага книг до обучения.
- L2457 `cand_sheet_entry(b)` — Запись кандидата в списке книг листа сечения.
- L2492 `cand_book(b, sm, models_b, x, mats, syms, rows_sit, j_last, gri…` — Свести одну книгу кандидата: манифест, выборы, счёт.
- L2549 `retire_dropped_books(books, log_)` — Каталог книги кандидата вне состава — в архив.
- L2607 `candidate_books(log_)` — Кандидаты фабрики → живые книги. Возвращает список записей.
- L2666 `run_books(models_b, seq_b, man_b, *, x, mats, syms, targets, el…` — Шаг книг: разбор, выборы, лист сканера и счета всех книг.
- L3221 `cycle(sum_dir, log_, book_root=SM.BOOK_ROOT)`
- L3677 `stale_summary()` — Отстал ли последний прогон от закрывшегося часа.
- L3697 `demo()` — Полный вывод цикла на синтетике — ответ на «что я буду видеть».
- L3743 `main()`

## research/s8_loop/why.py · 141 строк

Почему час не становится сечением — по числам, а не по догадке.

- L23 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L24 `SUM = os.path.join(HERE, 'out', 'summary')`
- L39 `med(v)`
- L47 `main()`

## research/s9_sweep/stops.py · 235 строк

Где ставить стоп: замер пробоя обещанной линии и возврата за ней.

- L48 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L54 `BUFFERS = [0.0, 0.1, 0.25, 0.5, 1.0]` — Буферы, по которым считается цена решения. Объявлены здесь и до прогона: доли от |mae|, потому что сама линия…
- L57 `walk(bars, entry_ts, entry_px, side, adv, fav, max_h=S.MAX_AGE_…` — Путь ноги относительно обещанных линий.
- L97 `measure_buffer(legs, buf)` — Что даёт буфер `buf` (в долях `|mae|`) на этой выборке.
- L125 `run(legs)`
- L135 `report(rows, legs, path)`
- L204 `main()`

## research/s9_sweep/sweep.py · 553 строк

Перебор правил ситуационной книги по УЖЕ ЗАПИСАННЫМ решениям модели.

- L61 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L67 `EDGES = [22.0, 33.0, 44.0, 66.0]` — Объявленная сетка. Меняется только правкой этого файла ДО прогона.
- L68 `RRS = [1.5, 2.0, 3.0, 4.0]`
- L69 `TAKE = [True, False]`
- L70 `MAX_AGE_H = 24`
- L71 `NULL_SHIFT_H = 6`
- L72 `MIN_CELL = 30`
- L75 `hour_ts(hour)`
- L79 `class HttpBars` — Бары через страницу наблюдения, когда записи нет под рукой.
  - L94 `HttpBars.__init__(self, base, key, log=print, disk=None)`
  - L105 `HttpBars.bars(self, sym, t0, t1)`
- L160 `read_bars(root, sym, t0, t1)` — Минутные бары собственной записи сборщика в окне `[t0, t1]`.
- L180 `bracket(bars, entry_ts, entry_px, side, adv, fav, max_h=MAX_AGE…` — Чем кончилась сделка: стоп, цель или срок.
- L218 `net_bp(side, move, adv)` — Нетто ноги и её риск в тех же единицах.
- L229 `legs_of(book_dir)` — Ноги всех выборов книги: цена входа, прогноз, обещания пути.
- L245 `legs_of_records(recs, book)` — Разбор записей выбора — ОДИН на оба источника (файл и HTTP).
- L279 `rr_of(leg)`
- L283 `run(root, books, log=print, src=None, legs=None)` — `src` — источник баров (`None` — записи на диске).
- L325 `measure(sel, take, null=False, mirror=False)` — `null` — сдвиг момента, `mirror` — та же сделка в другую сторону.
- L381 `drift(legs)` — Куда ехал рынок в окне и как перекошены стороны.
- L409 `report(legs, cells, path, root, books)`
- L487 `legs_from_http(base, key, books, log=print)` — Выборы через страницу наблюдения: те же записи, другой путь.
- L511 `main()`

## research/t0_orderflow_inventory/inventory.py · 313 строк

T0 — инвентаризация данных потока заявок: лента, кластеры, стакан.

- L57 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L58 `OUT = os.path.join(HERE, 'out')`
- L59 `CACHE = os.path.join(OUT, 'cache')`
- L64 `BYBIT = 'https://public.bybit.com/'`
- L65 `BINANCE_S3 = 'https://s3-ap-northeast-1.amazonaws.co…`
- L66 `UA = 't0-orderflow-inventory/1.0'`
- L70 `SAMPLE = ('BTCUSDT', 'SOLUSDT', 'ARBUSDT')` — Крупный, средний и мелкий: вес ленты зависит от активности, и средним по одному символу судить обо всех нельз…
- L71 `SAMPLE_DAY = '2025-03-10'`
- L74 `fetch(url, cache_key=None, binary=False)`
- L80 `listing(url, key)`
- L87 `bybit_sections()` — Какие разделы вообще есть в публичном архиве Bybit.
- L96 `bybit_trade_format()` — Состав ленты Bybit: колонки, агрессор, разрешение метки.
- L138 `bybit_symbol_days(symbol)` — Сколько суточных файлов и какого веса у символа.
- L149 `bybit_day_weight(symbol, day)` — Вес одного дня ленты и число принтов в нём.
- L165 `binance_book_sets()` — Есть ли у Binance наборы про стакан и какого разрешения.
- L180 `binance_agg_day(symbol, day)` — Вес суточной ленты Binance и состав колонок.
- L204 `main()`

## research/t1_tape/probe.py · 470 строк

Зонд: зарабатывает ли поглощение в ленте.

- L55 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L56 `RESEARCH = os.path.dirname(HERE)`
- L57 `OUT = os.path.join(HERE, 'out')`
- L66 `SYMBOLS = ('BTCUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGE…` — Ликвидные перпы Bybit разного размера. Кросс-секция должна быть шире одного имени, иначе контроля 1 не сущест…
- L68 `START = '2025-03-06'`
- L69 `END = '2025-03-10'`
- L71 `STEP_SEC = 1`
- L72 `WINDOWS = (10, 30)`
- L73 `VOL_MULTS = (5.0, 10.0)`
- L74 `MOVE_MULT = 0.5`
- L78 `IMBALANCES = (0.0, 0.3)` — Требуемый перевес давящей стороны. Ноль — как считал первый прогон: объём большой, а односторонний он или нет…
- L84 `HORIZONS = (30, 60, 300, 900, 1800)` — Горизонты удержания, секунды. Пять и десять убраны по потолку из первого прогона: лучший возможный выход внут…
- L89 `EPISODE_SEC = 300` — Слипание событий разных символов. На непрерывном сигнале длинное окно вырождается: события суток схлопываются…
- L97 `MIN_CROSS = 3` — Защитное окно кросс-секции: сосед, у которого событие рядом по времени, в фон не входит. Величина НЕ констант…
- L104 `MIN_CROSS_SHARE = 0.2` — Доля символов, требуемая в фоне. Держится НИЗКОЙ намеренно. Строгое требование (половина) выбрасывает ровно т…
- L106 `TAKER_ROUND_BP = 11.0`
- L107 `MAKER_ROUND_BP = 4.0`
- L110 `cross(P, cols, rows, horizon_sec, banned, guard_sec, min_cross,…` — Контроль 1 через общую функцию L3.
- L124 `day_matrix(symbols, day, step_sec, log)` — Ленты всех символов за сутки на общей сетке.
- L167 `forward_fill(M)` — Перенос последней известной цены вперёд по каждой строке.
- L182 `episodes_of(times, cols)`
- L186 `main()`
- L427 `cross_width(C, banned, cols, steps_h)` — Сколько символов оказалось в фоне на каждом событии.
- L441 `excursions(C, H, L, rows, cols, steps_list, side)` — Ход против и в пользу для НЕСКОЛЬКИХ горизонтов одним проходом.

## research/t1_tape/tape.py · 388 строк

T1 — лента принтов площадки исполнения: загрузка, кластеры, поглощение.

- L49 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `RESEARCH = os.path.dirname(HERE)`
- L51 `OUT = os.path.join(HERE, 'out')`
- L52 `CACHE = os.path.join(OUT, 'cache')`
- L57 `ARCHIVE = 'https://public.bybit.com/trading/'`
- L58 `UA = 't1-tape/1.0'`
- L62 `COL_TIME = 'timestamp'` — Колонки ленты Bybit. Ищутся по имени: разбор по номеру уже однажды стоил проекту тихого нуля в загрузчике fun…
- L63 `COL_SIDE = 'side'`
- L64 `COL_SIZE = 'size'`
- L65 `COL_PRICE = 'price'`
- L66 `COL_TICK = 'tickDirection'`
- L69 `day_url(symbol, day)`
- L73 `days_between(start, end)`
- L82 `load_day(symbol, day, cache=True)` — Лента за сутки: `(время, знак, размер, цена)`.
- L129 `to_grid(tape, step_sec, t0=None, t1=None)` — Лента на регулярную сетку шагом `step_sec`.
- L195 `footprint(tape, t_from, t_to, tick)` — Кластер: объём по ценовым уровням и сторонам за окно.
- L217 `rolling_sum(v, w)` — Сумма по `w` ячейкам, выровненная по правому краю окна.
- L227 `absorption(grid, window_sec, vol_mult, move_mult, side, imb=0.0)` — Моменты поглощения: много агрессии в одну сторону, цена не идёт.
- L313 `level_filter(tape, grid, idx, window_sec, side, bands=10)` — Из моментов поглощения оставить те, где набирали НА ЦЕНЕ.
- L387 `stamp(sec)`

## research/t2_levels/probe.py · 430 строк

Зонд: зарабатывает ли набор НА ЦЕНЕ — уровневое поглощение.

- L69 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L70 `RESEARCH = os.path.dirname(HERE)`
- L71 `OUT = os.path.join(HERE, 'out')`
- L81 `A1_OUT = os.path.join(RESEARCH, 'a1_universe', '…`
- L83 `SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPU…`
- L87 `START = '2025-03-03'`
- L88 `END = '2025-03-09'`
- L90 `STEP_SEC = 1`
- L91 `WINDOWS = (60, 300)`
- L92 `VOL_MULTS = (5.0, 10.0)`
- L93 `MOVE_MULT = 0.5`
- L94 `IMB = 0.3`
- L95 `CONCS = (0.4, 0.6)`
- L96 `BANDS = 10`
- L99 `HORIZONS_MIN = (5, 15, 30)` — Горизонты в минутах: короче пяти нет смысла — потолок T1 показал, что лучший возможный выход внутри минуты ме…
- L100 `EPISODE_SEC = 900`
- L101 `MIN_CROSS = 20`
- L102 `MIN_CROSS_SHARE = 0.1`
- L104 `TAKER_ROUND_BP = 11.0`
- L105 `MAKER_ROUND_BP = 4.0`
- L108 `tape_to_store()` — Карта: символ ленты Bybit -> символ хранилища Binance.
- L126 `bg_grid(start, end, step_sec)` — Сетка фона: от начала первых суток до конца последних.
- L135 `detect_day(sym, day, win, mult, conc_min, side, log)` — События уровневого набора у одного символа за сутки.
- L156 `main()`
- L318 `cross_width(P, banned, cols, steps_h)`
- L326 `excursion(P, HI, LO, rows, cols, steps_h, side)` — Ход против позиции и в её пользу за горизонт, по краям баров.
- L342 `report(cfg, rows_out, thin)`

## research/t3_brackets/brackets.py · 644 строк

Замер сделки: стоп по уровню, цель по структуре, ожидание как критерий.

- L78 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L79 `RESEARCH = os.path.dirname(HERE)`
- L80 `OUT = os.path.join(HERE, 'out')`
- L85 `SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPU…`
- L89 `START = '2025-03-03'`
- L90 `END = '2025-03-09'`
- L92 `STEP_SEC = 1`
- L93 `WINDOWS = (60, 300)`
- L94 `VOL_MULTS = (5.0, 10.0)`
- L95 `MOVE_MULT = 0.5`
- L96 `IMB = 0.3`
- L97 `CONCS = (0.4, 0.6)`
- L98 `BANDS = 10`
- L99 `MIN_RRS = (1.5, 2.0, 3.0)`
- L100 `LOOKBACK_SEC = 3600`
- L101 `MAX_HOLD_SEC = 3600`
- L102 `SHELF_Q = 0.8`
- L103 `STOP_MIN_BP = 3.0`
- L104 `NULLS_PER_EVENT = 1`
- L106 `TAKER_BP = 5.5`
- L107 `MAKER_BP = 2.0`
- L110 `bracket(g, i0, side, stop_px, target_px, max_hold_sec)` — Пройти по секундам вперёд: что задето первым, стоп или цель.
- L152 `profile(tape, t_from, t_to, width)` — Профиль объёма за окно: полосы шириной `width` и их объём.
- L171 `shelf_ahead(centers, vol, entry, long, q=SHELF_Q)` — Ближайшая полка объёма впереди — цель.
- L191 `evaluate(g, tape, i, side, level, width, min_rr, cost_bp, lookb…` — Собрать сделку по событию: стоп, цель, отношение, исход.
- L232 `rng_for(day_idx, cell_idx, seed)` — Зерно из чисел, а не из хеша строки.
- L243 `stats(trades, cost_bp)` — Сводка по сделкам: ожидание, безубыточная доля побед и R.
- L279 `main()`
- L426 `minute_bars(g, t_day)` — Секундную сетку суток — в минутные свечи для графика.
- L452 `write_bundle(out_dir, tag, want, acc, candles, cost, a, log)` — Бэктест одной ячейки для графика: свечи, сделки, кривая счёта.
- L514 `tick_of(vals)` — Шаг цены — наименьшее ненулевое различие цен, а не догадка.
- L522 `pack(g, tape, r, key, sym, day)` — Событие с картинкой: кластер, дельта, путь цены, уровни сделки.
- L565 `report(cfg, rows)`

## research/t3_brackets/chart.py · 644 строк

График бэктеста: свечи, сделки на них, кривая счёта снизу.

- L37 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L38 `OUT = os.path.join(HERE, 'out')`
- L40 `HTML = <текст, 568 строк>`
- L610 `main()`

## research/t3_brackets/render.py · 315 строк

Страница просмотра событий: кластер, уровень, сделка, путь цены.

- L34 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L35 `OUT = os.path.join(HERE, 'out')`
- L38 `sparse(rows)` — Плотную матрицу в разреженную: нулей в кластере большинство.
- L48 `prepare(ev)` — Событие в вид, удобный для отрисовки, без лишних чисел.
- L69 `HTML = <текст, 220 строк>`
- L291 `main()`

## research/t4_structure/ceiling.py · 224 строк

Потолок отсева: чего добьётся фильтр с идеальным знанием будущего.

- L52 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L53 `OUT = os.path.join(HERE, 'out')`
- L54 `MIN_KEEP = 0.3`
- L55 `SEED = 20260731`
- L58 `load(path)`
- L94 `exp_se(rows, key='net')`
- L104 `best_cut(rows, feat, key='net')` — Лучший порог по признаку — выбранный ПО ИСХОДАМ, то есть нечестно.
- L146 `random_null(rows, share, tries=2000, key='net')` — Распределение ожидания при СЛУЧАЙНОМ отсеве той же доли.
- L171 `main()`

## research/t4_structure/exits.py · 330 строк

Потолок геометрии: сколько вообще способны дать стоп и цель.

- L59 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L60 `OUT = os.path.join(HERE, 'out')`
- L61 `CACHE = os.path.join(OUT, 'bars')`
- L62 `MAX_HOLD_SEC = 4 * 3600`
- L63 `COST_BP = 11.0`
- L66 `day_ohlc(symbol, day)` — Минутные бары суток: `{метка: (open, high, low, close)}`.
- L91 `load_bars(syms, days)`
- L101 `load(path)`
- L120 `walk(bars, r)` — Пройти окно удержания и снять всё, что нужно всем потолкам.
- L172 `bracket(path, dn, up, last)` — Что задето первым при данной геометрии: стоп, цель или время.
- L186 `stat(vals)`
- L195 `grid_cell(walks, s_mult, t_mult)` — Исход при стопе и цели, умноженных на заданные множители.
- L205 `main()`

## research/t4_structure/levels.py · 307 строк

Уровни из структуры: полки объёма, экстремумы суток, круглые числа.

- L46 `LOOKBACK_MIN = 24 * 60`
- L47 `MIN_HISTORY_MIN = 6 * 60`
- L55 `RECENT_MIN = 30` — Шум меряется по НЕДАВНЕМУ окну, а не по суткам. Волатильность внутри суток не постоянна: у ARBUSDT 4 марта ме…
- L56 `MIN_RECENT_MIN = 10`
- L57 `SHELF_Q = 0.85`
- L58 `ROUND_SPAN = 3.0`
- L61 `minute_series(g)` — Секундная сетка суток -> минутные `(t, high, low, vwap, объём)`.
- L85 `noise_px(H, L, P)` — Обычный ход минутной свечи в ценах — мера шума.
- L99 `burst_px(H, L, lookback=RECENT_MIN)` — Крупнейшая минутная свеча окна — в ценах.
- L126 `shelves(P, V, noise, q=SHELF_Q)` — Полки объёма: цены, где оборот заметно выше окрестного.
- L150 `round_levels(price, noise, span=ROUND_SPAN)` — Круглые числа вокруг цены; шаг — от масштаба самой цены.
- L165 `build(t, H, L, P, V, now_i, prev_day_hl=None, recent_min=RECENT…` — Уровни на момент `now_i`: полки, экстремумы суток, круглые числа.
- L216 `structural_stop(H, L, levels, entry, long, noise, lookback=RECE…` — Стоп за ближайшим экстремумом и за накоплением, а не в долях шума.
- L262 `nearest(levels, kinds, price, tol)` — Ближайший уровень к цене, если он в пределах `tol`.
- L272 `ahead(levels, price, long, min_gap)` — Ближайший уровень впереди — цель. Слишком близкие пропускаются.
- L283 `ahead_worth(levels, price, long, min_gap, ok)` — Ближайший уровень впереди, который **оправдывает риск**.

## research/t4_structure/reentry.py · 239 строк

Замер: отличается ли исход входа, случившегося сразу после стопа?

- L56 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L57 `OUT = os.path.join(HERE, 'out')`
- L60 `load(path)`
- L85 `label(rows, within_min, quiet_min=60)` — Пометить каждую сделку обстоятельствами ЕЁ ВХОДА.
- L112 `wilson(k, n, z=1.96)` — Интервал доли: на малых корзинах обычная ошибка врёт.
- L123 `summarize(rows, name)`
- L143 `main()`

## research/t4_structure/run.py · 474 строк

Замер сделки на структурных уровнях: лента даёт момент, структура — цену.

- L44 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L45 `RESEARCH = os.path.dirname(HERE)`
- L46 `OUT = os.path.join(HERE, 'out')`
- L55 `SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPU…`
- L59 `START = '2025-03-03'`
- L60 `END = '2025-03-09'`
- L62 `STEP_SEC = 1`
- L63 `WINDOW = 60`
- L64 `VOL_MULTS = (5.0, 10.0)`
- L65 `MOVE_MULT = 0.5`
- L66 `IMB = 0.3`
- L67 `MIN_RRS = (1.5, 2.0, 3.0)`
- L68 `TOUCH_NOISE = 0.5`
- L74 `STOP_NOISES = (1.0, 2.0, 4.0)` — Ширина стопа в долях шума — ось сетки, а не константа. Смоук показал, почему: обычный ход минутной свечи ликв…
- L75 `MAX_HOLD_SEC = 4 * 3600`
- L76 `NULLS_PER_EVENT = 1`
- L77 `TAKER_BP = 5.5`
- L78 `MAKER_BP = 2.0`
- L81 `evaluate(g, i, side, level, stop_px, target_px, min_rr, cost_bp…` — Собрать сделку у структурного уровня.
- L119 `main()`
- L330 `bundle(out_dir, tag, want, trades, candles, cost, a, log)` — Выгрузка для графика — тем же форматом, что читает `chart.py`.
- L376 `report(cfg, rows)`

## research/t4_structure/trend.py · 277 строк

Замер: зависит ли исход сделки от локального тренда в момент входа.

- L55 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L56 `OUT = os.path.join(HERE, 'out')`
- L57 `CACHE = os.path.join(HERE, 'out', 'bars')`
- L58 `DAILY = 'https://data.binance.vision/data/futur…`
- L59 `WINDOWS = (15, 60, 240)`
- L60 `SEED = 20260731`
- L63 `day_bars(symbol, day)` — Минутные бары символа за сутки: `{метка: (открытие, закрытие)}`.
- L95 `load_bars(syms, days)`
- L106 `load_trades(path)`
- L122 `typical_move(bars, win)` — Обычное |изменение| за окно у этого символа — медиана по неделе.
- L141 `trend_at(bars, t, win, typ)` — Знак и величина тренда ДО момента `t`. Только назад.
- L156 `exp_se(rows, key)`
- L166 `median(rows, key)`
- L171 `bucket_of(bars, r, win, typ)` — Корзина сделки: по тренду, против, либо тренда нет.
- L186 `main()`

## research/w1_waves/filter_probe.py · 332 строк

W3 — волновое состояние как фильтр сделок наших моделей.

- L59 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L60 `RESEARCH = os.path.dirname(HERE)`
- L61 `OUT = os.path.join(HERE, 'out')`
- L83 `R = importlib.util.module_from_spec(_spec)`
- L89 `THETA_MULT = 2.0`
- L91 `VECTORS = ('vectors_h5_day.npz', 'vectors_h1_day.…`
- L92 `WAVE_REGIMES = [('wv_leg_age', 'зрелость текущей ноги …`
- L99 `SEED = 20260827`
- L102 `log_(m)`
- L106 `day_hour(day, grid0_ts)` — Час решения дня: ОТКРЫТИЕ его последнего часа, индексом сетки.
- L118 `wave_states(x, theta, queries)` — Пять волновых состояний в заданные часы. Пропуск — NaN.
- L165 `build_wave_columns(cols, log=log_, uni=None)` — Волновые колонки, выровненные со строками матрицы M1.
- L214 `judge(cols, pred, key, log=log_)` — Суд машиной зонда режимов над волновыми состояниями.
- L236 `reading(rows)` — Фраза вывода — из чисел, а не рядом с ними.
- L255 `write_report(path, blocks, meta)`
- L289 `main(argv=None)`

## research/w1_waves/grammar.py · 248 строк

W2 — грамматика волн: ядро мер. Ни загрузки, ни отчёта — их держит `grammar_probe.py`.

- L45 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L50 `GOLDEN = 1.618`
- L51 `IMPULSE_K = 5`
- L52 `CONTRACT_K = 4`
- L55 `contiguous(w)` — Ноги идут встык: конец каждой — начало следующей.
- L66 `windows(lg, k=IMPULSE_K)` — Скользящие окна из k подряд идущих ног: (индекс первой, окно).
- L76 `impulse_stats(w)` — Правила импульса и родственные величины окна из пяти ног.
- L111 `valid_impulse(st)`
- L115 `near_share(vals, target, half=0.05)` — Доля значений в ОТНОСИТЕЛЬНОЙ полосе ±half вокруг цели.
- L128 `contractions(lg, k=CONTRACT_K)` — Сжатия: k подряд строго убывающих ног, с окружением для исхода.
- L155 `subdivision(coarse_lg, fine_piv)` — Дробление: сколько мелких ног внутри каждой крупной.
- L171 `leg_queries(lg, need=IMPULSE_K)` — Сырьё для поиска по структуре: признаки, цель, момент.
- L194 `knn_ic(F, Y, C, S, k=50, guard=720, rng=None, block=128, max_q=…` — Предсказывает ли структура последних ног следующую ногу.

## research/w1_waves/grammar_probe.py · 532 строк

W2 — зонд грамматики волн: прогон, суррогаты, свод, отчёт.

- L39 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L40 `RESEARCH = os.path.dirname(HERE)`
- L41 `OUT = os.path.join(HERE, 'out')`
- L56 `THETAS = (1.0, 2.0, 3.0)`
- L57 `WARM_DIFFS = 1440`
- L58 `MIN_MEAS_H = 24 * 90`
- L59 `BOOT = 5`
- L61 `KNN_THETAS = (1.0, 2.0)`
- L62 `KNN_MAX_Q = 30000`
- L63 `FIB31 = (1.0, G.GOLDEN, 2.618)`
- L64 `FIB51 = (0.618, 1.0, G.GOLDEN)`
- L68 `M_SHARE = 0.02` — Запасы сравнения с суррогатом. Объявлены до прогона: разница мельче запаса не читается ни в чью пользу.
- L69 `M_RHO = 0.02`
- L70 `M_FIB = 0.005`
- L71 `M_SUB = 0.2`
- L72 `M_CONT = 0.02`
- L73 `M_KNN = 0.01`
- L75 `SEED = 20260826`
- L78 `log_(m)`
- L82 `own_theta(x, warm=WARM_DIFFS)` — σ символа по его первым 60 суткам и индекс начала замера.
- L100 `make_surr(x, rng)` — Суррогатный ряд: те же приращения, порядок разбит сутками.
- L112 `new_acc()`
- L119 `collect(d, lg)` — Все оконные меры одного ряда ног — в накопитель.
- L143 `share(v)`
- L147 `rho_pairs(pairs)`
- L156 `summarize(d)` — Свод накопителя одной (θ, сторона)-ячейки в числа отчёта.
- L187 `CLAIMS = (('импульсных окон больше', lambda r, s…`
- L213 `fmt(v, digits=3)`
- L218 `sh(v)`
- L222 `write_report(path, res, sub, knn, meta)`
- L405 `main(argv=None)`

## research/w1_waves/probe.py · 816 строк

W1 — зонд волнового анализа: повторяются ли волны и платит ли это.

- L82 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L83 `RESEARCH = os.path.dirname(HERE)`
- L84 `OUT = os.path.join(HERE, 'out')`
- L97 `STEP_SEC = 3600`
- L98 `STEP_H = 1`
- L99 `WINDOWS = (12, 24, 48, 168)`
- L100 `HORIZONS = (1, 4, 12, 24)`
- L101 `K = 50`
- L102 `MIN_NB_SHARE = 0.2`
- L104 `POOL = 20000` — иначе предсказания нет вовсе
- L105 `POOL_DAYS = 365`
- L106 `QUERY_EVERY_H = 12`
- L107 `MIN_CROSS = 50`
- L108 `SIM_BANDS = ((0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0…`
- L111 `THETAS = (1.0, 2.0, 3.0)` — Зигзаг: порог разворота в суточных сигмах САМОГО символа.
- L112 `BOOT = 20`
- L113 `BLOCK_H = 24`
- L114 `MIN_HOURS_ZZ = 24 * 90`
- L116 `ROUND_COST_BP = 11.0`
- L118 `START = '2023-01-01'`
- L119 `END = '2026-06-01'`
- L120 `MIN_SHARE = 0.9`
- L121 `SEED = 20260825`
- L122 `BLOCK_Q = 1024`
- L123 `MEM_SHARE = 0.5`
- L126 `log_(m)`
- L130 `free_mb()` — Доступная память машины. Ноль — значит не спросили, а не «нет».
- L142 `memory_plan(n_sym, n_h, log=log_)` — Сколько нужно и сколько есть — ДО счёта, а не после падения.
- L165 `grid(start, end)`
- L173 `quarters(start, end)` — Границы кварталов тестовой эры: пул строится заново на каждый.
- L187 `load_prices(symbols, times, interval, log=log_)` — Логарифмические цены и маски годности. Пустая матрица — отказ.
- L215 `excess_forward(L, h, min_cross=MIN_CROSS)` — Избыточная доходность вперёд: сверх РАВНОВЗВЕШЕННОЙ кросс-секции.
- L237 `paths(L, rows, cols, W)` — Сырые пути `W+1` баров, кончающиеся в своей колонке.
- L255 `sample_pool(L, ok_cols, t_lo, t_hi, W, rng, want=POOL)` — Пул форм из ПРОШЛОГО: строки-символы, колонки-времена.
- L279 `_median_of(nb, n, g)` — Медиана будущего соседей — только там, где соседей достаточно.
- L297 `cell_key(w, h)`
- L301 `section_stats(pred, actual, rev, sim, acc, w, h)` — Одно сечение: IC, спред дециля, нуль и контроль возврата.
- L351 `run_knn(L, times, symbols, rng, log=log_)` — Прочитка 1: повторяется ли форма со смыслом.
- L416 `sigma_hour(L, lo, hi)` — Часовая σ приращений по окну ПЕРЕД замером — по символу.
- L427 `run_zigzag(L, times, symbols, rng, log=log_)` — Прочитка 2: похожа ли структура ног на случайное блуждание.
- L504 `med(v)`
- L513 `DECILE_K = 3.51` — Удвоенное среднее нормальной величины в хвосте 10 % — множитель, по которому спред длинно-короткого дециля вы…
- L516 `ic_break_even(sigma, cost_bp=None)` — Какой IC вообще способен окупить круг издержек в этой ячейке.
- L535 `cells_table(acc, acc0)`
- L561 `write_report(path, rows, zz, meta)`
- L749 `main(argv=None)`

## research/w1_waves/waves.py · 328 строк

W1 — ядро волнового зонда: форма и зигзаг.

- L52 `MAX_GAP = 6` — Пропусков подряд больше — зигзаг начинается заново. Число объявлено до прогона: на часовой сетке шесть часов…
- L56 `MIN_PATH_SD_BP = 5.0` — Путь, весь размах которого меньше этого, формой не считается. Пять базисных пунктов на сутки часовых баров —…
- L61 `FIB_LEVELS = (0.382, 0.5, 0.618, 0.786, 1.0, 1.618)` — Уровни Фибоначчи и полуширина полосы, в которой считается попадание. Объявлены ДО прогона: подобрать ширину п…
- L62 `FIB_BAND = 0.02`
- L65 `zigzag(x, theta, max_gap=MAX_GAP)` — Причинный зигзаг: подтверждённые развороты по порогу `theta`.
- L127 `_gap_inside(x, i0, i1, max_gap)` — Есть ли внутри отрезка разрыв записи длиннее `max_gap` баров.
- L140 `legs(x, piv, max_gap=None)` — Ноги и коэффициенты отката по подтверждённым разворотам.
- L182 `fib_shares(ratios, levels=FIB_LEVELS, band=FIB_BAND)` — Доля откатов, попавших в полосу вокруг каждого уровня.
- L198 `block_bootstrap(d, block, rng)` — Суррогат приращений: те же значения, порядок разбит блоками.
- L227 `znorm(X, min_sd_bp=MIN_PATH_SD_BP)` — Формы: уровень снят, масштаб снят, строки единичной длины.
- L256 `top_neighbours(Q, POOL, k, block=2048, forbid=None)` — `k` ближайших по форме из прошлого: индексы и сходство.
- L298 `spearman(a, b)` — Ранговая корреляция по конечным парам. NaN, если пар меньше трёх.
- L314 `_rank(v)` — Ранги со средним для совпадений: ничья не вправе давать порядок.

## research/z1_screen/screen.py · 1241 строк

Z1 — скрин закономерностей: машина, которая сама перебирает УСЛОВИЯ по записанным данным и меряет, предсказыв…

- L79 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L80 `RESEARCH = os.path.dirname(HERE)`
- L81 `OUT = os.path.join(HERE, 'out')`
- L88 `STEP_MIN = 1`
- L89 `STEP_SEC = 60`
- L90 `HORIZONS = (5, 15, 60, 240)`
- L91 `GUARD_MIN = 60`
- L92 `MIN_CROSS = 50`
- L93 `DEDUP_MIN = 60`
- L102 `PERMS = 100` — Единица наблюдения — временнáя КОРЗИНА длиной в горизонт, а не событие и не «эпизод по разрыву». Причина ариф…
- L103 `SEED = 20260824`
- L104 `ROUND_COST_BP = 11.0`
- L111 `NEUTRAL_COST_BP = 2 * ROUND_COST_BP` — Превышение над кросс-секцией есть PnL рыночно-нейтральной книги: наша нога плюс хедж об остальное сечение. Зн…
- L112 `WARM_DAYS = 2`
- L113 `MIN_EVENTS = 30`
- L114 `MIN_BUCKETS = 50`
- L121 `CHUNK = 200` — Планка считается по Z, а не по базисным пунктам. Пилот показал, почему: ячейка на 34 событиях и 16 корзинах д…
- L124 `log_(msg)`
- L128 `month_span(mon)`
- L135 `grid(a, b)`
- L140 `daily_units(symbols, mon, log=log_)` — Собственные единицы символа по КАЖДЫМ суткам: шум и медианы.
- L184 `unit_rows(symbols, times, units)` — Единицы ПРОШЛЫХ суток, разложенные по минутам сетки.
- L212 `back_ret(P, w)` — Доходность за `w` минут НАЗАД: известна в момент `t`.
- L221 `fwd_ret(P, h)` — Ход ВПЕРЁД от входа: вход по открытию следующего бара.
- L237 `cross_stat(F, cols, rows, how='median')` — Одновременная кросс-секция с исключением своих событий.
- L281 `roll_sum(X, w)` — Сумма за `w` минут, кончающаяся на ПРОШЛОМ баре.
- L298 `since_shock(z, thr=2.0, cap=1440)` — Минут с последнего собственного шока |z_15| >= thr, с потолком.
- L309 `primitives(P, QV, TR, TB, U, hi_prev, lo_prev, btc_row)` — Все примитивы разом. Возвращает словарь матриц символ × минута.
- L347 `build_conditions()`
- L443 `CONDITIONS = build_conditions()`
- L446 `dedup_rows(hit, dedup_min=DEDUP_MIN)` — Одно срабатывание на серию: обвал длится десятки минут.
- L467 `NULL_CAP = 3000`
- L468 `BUCKET_QUOTA = 100`
- L477 `month_units(symbols, mon, times, log=log_)` — Матрицы собственных единиц символа плюс вчерашний диапазон.
- L558 `age_matrix(symbols, times, uni)` — Возраст листинга в сутках — из справочника универсума.
- L572 `OI_PUBLISH_SEC = 300`
- L575 `oi_matrices(symbols, times)` — Изменение открытого интереса за 15 и 60 минут (ряд с 2024).
- L607 `run_length_gap(fin)` — Сколько минут подряд не было сделок ПЕРЕД текущей минутой.
- L623 `since_resume(fin)` — Минут с возобновления торгов после перерыва (потолок — сутки).
- L637 `base_prims(P, U, uni, symbols, times)` — Примитивы, нужные почти всем группам, — держатся в памяти.
- L675 `group_prims(group, P, U, prim, symbols, times, uni, log=log_)` — Примитивы конкретной группы: материализуются и освобождаются.
- L699 `volume_prims(P, U, prim, rows_slice, symbols, times, log=log_)` — Объём, размер сделки и доля агрессивных покупок — по куску имён.
- L725 `collect_events(P, U, prim, symbols, times, uni, own, log=log_)` — События по всем условиям: словарь имя-условия → (строки, колонки).
- L772 `CONDS_BY_NAME = {}`
- L777 `measure(events, P, times, acc, rng, log=log_, conds_by_name=Non…` — Превышение по ячейкам, свёрнутое ДО корзин прямо в месяце.
- L894 `bucket_groups(ep)` — Порядок и границы корзин — считаются ОДИН раз на ячейку.
- L908 `med_by_groups(V, order, edges)` — Медиана по корзинам, затем медиана по корзинам-медианам.
- L927 `class warnings_ignored` — Пустая медиана по корзине даёт предупреждение, а не ошибку.
  - L930 `warnings_ignored.__enter__(self)`
  - L938 `warnings_ignored.__exit__(self, *a)`
- L943 `med_by_groups_all(V, order, edges)` — Медианы по КАЖДОЙ корзине, без свёртки в одно число.
- L954 `med_by_episode(v, ep)`
- L962 `summarize(acc)` — Сводка по ячейкам и семейственная планка нуля.
- L1034 `verdict_of(c, null)` — Вердикт ячейки. Четыре условия, и все объявлены до прогона.
- L1056 `write_report(path, cells, null, meta)`
- L1142 `publish(msg)`
- L1150 `months_between(start, end)`
- L1160 `run(start, end, symbols=None, log=log_)`
- L1194 `main(argv=None)`

## research/z2_book/bench_ladder.py · 283 строк

Z2: цена разбора ЛЕСЕНКИ — замер на живых строках записи.

- L40 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L41 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L50 `N_SYM = 12`
- L51 `N_LINES = 4000`
- L52 `WINDOW_S = 60`
- L58 `OVERHEAD = 2.5` — Наблюдённое отставание живого прохода от чистой арифметики разбора. Взято не с потолка: D1 прочитал 12 суток…
- L60 `_LAD = re.compile('"b":\\[(.*?)\\],"a":\\[(.*?…`
- L63 `log_(m)`
- L67 `ladder(line)` — Разбор ЛЕСЕНКИ: обе стороны как массивы «цена, размер».
- L87 `sample_lines(day, book=None, n_sym=N_SYM, n_lines=N_LINES, log=…` — Сырые строки живой записи: по одному часу у нескольких символов.
- L118 `bench(fn, lines, cap=2000)` — Микросекунды на строку. Возвращает None, если разбор не прошёл.
- L134 `snaps_of_day(day, store=None)` — Снимки за сутки: сколько всего и сколько в минуте НА ИМЯ.
- L153 `measure(day, book=None, store=None, n_sym=N_SYM, n_lines=N_LINE…`
- L175 `_med(v)`
- L179 `write_report(res, path=None, log=log_)`
- L252 `publish(msg)`
- L257 `main(argv=None)`

## research/z2_book/bookfeat2.py · 271 строк

Z2 — признаки СОБСТВЕННОЙ записи стакана, сведённые по минутам.

- L57 `BAND = '0.0025'` — Полоса глубины, по которой считается выедание. Узкая (±0.05 %) у плотных имён вырождается — у BTCUSDT все пол…
- L63 `FOLD_FIELDS = ('mid_open', 'mid_close', 'mid_hi', 'mi…` — Состав свёртки и его ПОРЯДОК. Одно определение на всех: минутный склад хранит поля этим порядком, скрин берёт…
- L69 `_num(line, key, start=0)` — Число по ключу в кавычках. Быстрее json.loads в разы.
- L94 `_NUM = '(-?[\\d.eE+-]+)'` — Скаляры снимка лежат по КРАЯМ строки: `bid/ask/upd` в первой сотне байт, `reach/bq/aq/t` — в последних двухст…
- L95 `_HEAD = re.compile('"ts":' + _NUM + '.*?"bid":'…`
- L98 `_TAIL = re.compile('"reach_b":' + _NUM + ',"rea…`
- L102 `HEAD_SPAN = 300`
- L103 `TAIL_SPAN = 400`
- L106 `snap_line(line)` — Снимок: момент наблюдения и скаляры книги, разбор по краям.
- L123 `snap_line_slow(line)` — Снимок: момент наблюдения и скаляры книги.
- L151 `trade_line_px(line)` — Принт: момент, сторона агрессора, ЦЕНА, размер.
- L166 `trade_line(line)` — Принт: момент, сторона агрессора, нотионал.
- L172 `minute_of(t, t0)`
- L176 `fold(snaps, trades, t0, n_min)` — Свести символо-час к минутам. Обе последовательности — по времени.
- L265 `_med(v)`

## research/z2_book/fold.py · 912 строк

Z2 — минутный склад записи стакана.

- L66 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L67 `RESEARCH = os.path.dirname(HERE)`
- L74 `BOOK = os.path.join(RESEARCH, 'b1_book', 'out'…`
- L75 `TRADES = os.path.join(RESEARCH, 'b1_book', 'out'…`
- L76 `STORE = os.path.join(HERE, 'out', 'store')`
- L77 `MIN_PER_DAY = 1440`
- L83 `FOLD_VERSION = 1` — Версия арифметики свёртки. Меняется вместе с `bookfeat2.fold`, с полосой глубины или с составом полей. Склад…
- L90 `FOLDERS = {}` — Реестр сворачивателей. Машинерия склада — обход суток, состояние с диска, параллельность, отчёт, публикация —…
- L93 `register_folder(name, module, day_fn, fields, store, version=1,…` — Объявить сворачиватель. `mins_field` — поле, по которому считаются годные символо-минуты: у книги это `mid_op…
- L105 `folder(kind=None)` — Сворачиватель по имени; без имени — книжный, как было.
- L110 `folder_store(spec)` — Каталог склада разрешается В МОМЕНТ ВЫЗОВА, а не на импорте.
- L129 `log_(m)`
- L133 `symbols(root=None)`
- L141 `day_bounds(day)`
- L146 `hours_of_day(day)`
- L152 `day_is_closed(day, now=None)` — Сутки годны к свёртке, только когда их конец уже в прошлом.
- L158 `symbol_day(sym, day, book=None, trades=None)` — Минутные признаки одного символа за сутки. Пропуск — это None.
- L180 `_row(got, fields=None)` — Словарь списков -> матрица (поле × минута) float32.
- L192 `_JOB = {}`
- L195 `_init(book, trades, kind=None)`
- L199 `_one(arg)`
- L213 `fold_day(day, syms=None, jobs=1, book=None, trades=None, store=…` — Свернуть сутки на склад. Возвращает 'ok' / 'есть' / причину отказа.
- L289 `_progress(day, done, n, have, t_start, log, every=50)`
- L297 `_head(path, names=False)` — Заголовок суток со СКЛАДА: версия, имена, объём — с диска.
- L317 `has_record(sym, day, book=None)` — Есть ли у имени сырьё за эти сутки — хоть один часовой файл.
- L333 `day_gap(day, store_names, syms=None, book=None)` — Имена, у которых за эти сутки ЕСТЬ сырьё и НЕТ свёртки.
- L346 `partial_days(st, syms=None, book=None, store=None)` — Сутки на складе, свёрнутые УЖЕ запрошенного: день -> сколько имён.
- L366 `scan(store=None)` — Состояние склада, прочитанное С ДИСКА, а не из дельты прогона.
- L384 `read_day(day, syms, fields=None, store=None, log=log_, version=…` — Матрицы «символ × минута» со склада, или None — читайте сырьё.
- L429 `days_with_records(book=None, syms=None)` — Какие сутки вообще есть в СЫРЬЕ — по именам часовых файлов.
- L445 `write_manifest(store=None, log=log_)` — Сводка склада ВЫВОДИТСЯ из обхода файлов, а не из прогона.
- L472 `FULL_DAY = 0.95` — Полные сутки и годный состав. Числа объявлены здесь, а не в тексте отчёта: порог, живущий словом в прозе, одн…
- L473 `THIN_ROWS = 100`
- L476 `coverage(head)` — Доля заполненных символо-минут: полные ли это сутки.
- L487 `calendar_gaps(days)` — Календарные сутки внутри окна записи, которых в СЫРЬЕ нет вовсе.
- L503 `density(path, log=log_)` — Медиана снимков в минуте за сутки — ПРЯМАЯ мера прорежения записи.
- L526 `HOURS_BACK = 7`
- L527 `HOUR_DEV = 0.2`
- L530 `_med(v)` — Медиана без дефекта `sorted(x)[n // 2]`.
- L547 `hour_series(path, field='snaps', agg='med_sym', log=log_)` — Медиана поля ПО ЧАСАМ суток.
- L588 `hour_density(path, log=log_)` — Снимков в минуте по часам — частный случай `hour_series`.
- L593 `hour_spread(rows)` — Размах ОДНОГО И ТОГО ЖЕ часа по суткам, в долях его медианы.
- L611 `hour_table(store, days, back=HOURS_BACK, log=log_)` — Сетка «сутки × час» за последние `back` суток плюс отклонения.
- L651 `full_days(st)` — Сутки, годные к замеру: полные по времени И широкие по составу.
- L664 `write_report(path=None, store=None, book=None, syms=None, log=l…` — Отчёт о состоянии склада — ФАЙЛОМ, который уезжает в git.
- L847 `publish(msg)` — Публикация — ЧАСТЬ прогона, а не отдельный шаг (урок `width.py`).
- L867 `main(argv=None)`

## research/z2_book/probe.py · 546 строк

Z2 — скрин закономерностей по СОБСТВЕННОЙ записи стакана.

- L52 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L53 `RESEARCH = os.path.dirname(HERE)`
- L54 `OUT = os.path.join(HERE, 'out')`
- L66 `BOOK = F.BOOK` — Пути, склад и свёртка живут в `fold`, здесь только имена для вызова: тесты подменяют их, поэтому они передают…
- L67 `TRADES = F.TRADES`
- L68 `STORE = F.STORE`
- L69 `MIN_PER_DAY = F.MIN_PER_DAY`
- L70 `HORIZONS = (1, 5, 15, 60)`
- L71 `MIN_SNAPS = 30`
- L72 `NORM_MIN_MIN = 600`
- L75 `log_(m)`
- L79 `symbols(root=BOOK)`
- L87 `symbol_day(sym, day, log=log_)` — Минутные признаки одного символа за сутки. Пропуск — это None.
- L95 `FIELDS = ('mid_open', 'spread', 'depth_b', 'dept…` — Из восемнадцати полей свёртки скрину нужны пятнадцать. Список — подмножество `B.FOLD_FIELDS` и проверяется те…
- L100 `PROGRESS_EVERY = 50`
- L103 `day_matrices(syms, day, log=log_, use_store=True)` — Матрицы «символ × минута» за сутки плюс ширина записи числом.
- L132 `_raw_matrices(syms, day, log=log_)` — Тот же день, собранный чтением СЫРЬЯ. Запасной путь склада.
- L154 `norms(prev)` — Собственные нормы символа по ВЧЕРАШНИМ суткам.
- L176 `primitives(M, N)` — Признаки в собственных единицах символа. Нормы — вчерашние.
- L206 `build_conditions()` — Пространство объявляется ЦЕЛИКОМ здесь и после прогона не растёт.
- L260 `CONDITIONS = build_conditions()`
- L261 `CONDS_BY_NAME = {}`
- L266 `collect_events(P, prim, times, log=log_)` — События по всем условиям: имя триггера → (строки, колонки).
- L285 `side_drift(cells)` — Снос по стороне: при контроле СРЕДНИМ он обязан быть около нуля.
- L305 `write_report(path, cells, null, drift, meta)`
- L410 `days_between(start, end)`
- L420 `store_note(days, args)` — Откуда читались сутки — со склада или из сырья.
- L434 `start_day(asked, have_days, use_store=True, log=log_)` — С каких суток начинать замер.
- L465 `main(argv=None)`

## research/z3_ladder/fold_ladder.py · 359 строк

Z3: катящийся склад лесенки — проход по сырью, свёртка к минуте.

- L35 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L36 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L47 `STORE = os.path.join(HERE, 'out', 'store')`
- L48 `VERSION = 1`
- L51 `log_(m)`
- L55 `peak_rss_mb()` — Пик собственной памяти, МБ — по факту, а не по оценке.
- L61 `mem_line()` — Сколько памяти доступно машине прямо сейчас, словами.
- L78 `snap_full(line)` — Снимок целиком, вместе с лесенкой.
- L94 `_read(dirpath, hour, parse)`
- L101 `symbol_day(sym, day, book=None, trades=None)` — Минутные потоки по уровням одного символа за сутки.
- L150 `trades_between(trs, j, lo, hi)` — Принты интервала `(lo, hi]` и новое положение указателя.
- L168 `fold_chunk(acc, snaps, trs, t0, prev=None, n_min=None)` — Досчитать пары снимков в накопители минут; вернуть хвост.
- L193 `close_day(acc, n_min=None)` — Накопители минут -> словарь списков по полям.
- L206 `fold_symbol(snaps, trs, t0, n_min=None)` — Свернуть снимки и ленту одного символа к минутам — сутки целиком.
- L225 `write_report(path=None, store=None, log=log_)` — Состояние ладдерного склада — файлом, который уезжает в git.
- L296 `publish(msg)`
- L301 `main(argv=None)`

## research/z3_ladder/ladder.py · 236 строк

Z3: потоки по ЦЕНОВЫМ УРОВНЯМ — ядро меры.

- L58 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L59 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L65 `MAX_DT = 3.0`
- L66 `MIN_PAIRS = 20`
- L68 `FIELDS = ('vis_b', 'vis_a', 'eat_b', 'eat_a', 'c…`
- L73 `side_flows_slow(prev, cur, traded)` — Потоки одной стороны через словари — образцовая реализация.
- L110 `_monotone(levels)` — Направление лесенки: 1 — по возрастанию, −1 — по убыванию, 0 — не монотонна.
- L125 `side_flows(prev, cur, traded)` — Потоки одной стороны между двумя снимками.
- L178 `pair_flows(prev, cur, trades)` — Потоки обеих сторон плюс ход середины между двумя снимками.
- L201 `minute_accum()` — Пустой накопитель минуты. Ноль пар означает ПРОПУСК.
- L206 `add_pair(acc, fl)` — Добавить пару снимков в накопитель минуты.
- L224 `close_minute(acc)` — Итог минуты: пропуск, если пар меньше `MIN_PAIRS`.

## research/z3_ladder/screen3.py · 653 строк

Z3 — скрин по лесенке: снятие, смерть и восполнение КОНКРЕТНЫХ цен.

- L54 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L55 `ROOT = os.path.dirname(os.path.dirname(HERE))`
- L68 `OUT = os.path.join(HERE, 'out')`
- L69 `STORE = os.path.join(HERE, 'out', 'store')`
- L73 `HORIZONS = P2.HORIZONS` — Горизонты те же, что у Z2: лесенка обязана быть ЧИСТОЙ версией той же меры, и сравнивать их можно только на о…
- L78 `MIN_PAIRS = 30` — Порог ЗАМЕРА, а не склада: минута с малым числом пар снимков — пропуск, а не наблюдение. Склад хранит `pairs`…
- L83 `NORM_MIN_MIN = 120` — Норма символа считается по ВЧЕРАШНИМ суткам и только там, где вчера было хотя бы столько минут: норма по тем…
- L86 `log_(m)`
- L90 `day_ladder(syms, day, log=log_)` — Матрицы лесенки за сутки со своего склада. Нет склада — None.
- L104 `norms(prev)` — Собственные нормы символа по вчерашней лесенке.
- L124 `price_moves(mid)` — Ход самой цены за минуту — БЕЗ единого взгляда в лесенку.
- L139 `primitives(L, N, mid=None)` — Признаки лесенки в долях показанного — и в разах от своей нормы.
- L181 `build_conditions()` — Пространство объявляется ЦЕЛИКОМ здесь и после прогона не растёт.
- L290 `twin_of(name)` — Имя условия для ДРУГОЙ стороны книги, или None.
- L308 `CONDITIONS = build_conditions()`
- L309 `CONDS_BY_NAME = {}`
- L314 `collect_events(P, prim, log=log_)` — События по всем условиям: имя триггера → (условие, строки, колонки).
- L333 `store_days(store=None)` — Сутки, которые ЕСТЬ на складе лесенки, по диску.
- L338 `stats(syms, days, log=log_)` — Распределение самих величин — БЕЗ единого взгляда на исходы.
- L393 `write_report(path, cells, null, drift, meta)`
- L508 `main(argv=None)`

## bot/sverka.py · 272 строк

Сверка: каждая сделка бота против Python-счёта, до цента.

- L30 `HERE = os.path.dirname(os.path.abspath(__file_…`
- L31 `REPO = os.path.dirname(HERE)`
- L36 `CENT = 0.005`
- L37 `EXACT = 1e-09`
- L40 `read_jsonl(path)` — Строки файла; оборванный хвост пропускается — его допишут.
- L62 `read_journal(jdir)` — Журнал бота: сутки по возрастанию, дубли по номеру сняты.
- L86 `bot_trades(recs)` — Сделки и отказы из журнала.
- L116 `book_mode(s8)` — Режим книги — из её манифеста, как у Rust-ядра.
- L135 `py_trades(s8, arm, capital, table, now)` — Правда Python-стороны — тем же конвейером, что страница.
- L155 `main()`

## bot/src/check.rs · 200 строк

Сторож исполнения: инварианты, которые обязаны держаться всегда.

- L31 `verify_journal` — Сколько часов позиция живёт ЗАКОННО — по книге, которую ведёт этот журнал. Путь к книге лежит в маркере источ…
- L50 `hold_from_journal`
- L62 `struct CheckOpts`
- L71 `impl Default for CheckOpts`
  - L72 `CheckOpts::default`
- L78 `struct CheckReport`
- L89 `verify` — Проверить состояние против журнала. `st` обязан быть выведен из этих же `records` — сторож пересчитывает касс…

## bot/src/daemon.rs · 316 строк

Демон: проход тени по кругу, сторож после каждого прохода, статус

- L26 `struct SverkaCfg`
- L33 `struct DaemonCfg`
- L47 `struct SverkaStatus`
- L55 `struct PassSummary`
- L63 `impl From`
  - L64 `From::from`
- L76 `struct Status`
- L97 `struct TickMemory`
- L104 `tick` — Один такт: тень → сторож → сверка (по расписанию) → статус на диск.
- L217 `run_sverka`
- L272 `write_status` — Статус — атомарно: обрыв записи не оставляет странице огрызка, который разобрался бы как «бот молчит» при жив…
- L285 `run` — Вечный цикл: такт, лог-строка, сон. Убивается сигналом; журнал write-ahead, поэтому обрыв в любом месте стоит…

## bot/src/engine.rs · 640 строк

Движок тени: те же сделки, что у Python-счёта, своим счётом.

- L28 `struct BookMode`
- L43 `book_rules_version` — Версия правил книги из её манифеста; `None`, если книга правил не объявляет (книги горизонтов) или манифеста…
- L63 `fresh_journal_on_rules_change` — Журнал — запись ОДНОЙ книги. Сменились правила книги (цикл отставил её в архив и начал заново) — журнал обяза…
- L113 `book_mode`
- L143 `struct Cfg`
- L156 `struct PassReport`
- L166 `enum EngineError`
- L171 `impl From`
  - L172 `From::from`
- L176 `impl From`
  - L177 `From::from`
- L181 `impl Display for EngineError`
  - L182 `EngineError::fmt`
- L190 `side_str`
- L198 `shadow` — Один проход тени. Возвращает отчёт и состояние ПОСЛЕ прохода.
- L638 `default_fees_path` — Умолчание для пути к таблице ставок — та же выгрузка A1, что читает Python-счёт. Не копия таблицы, а тот же ф…

## bot/src/events.rs · 140 строк

События журнала — единственное, что ядро запоминает.

- L19 `enum Side`
- L31 `enum Event`
- L115 `impl Event`
  - L117 `Event::at_ms` — Момент события — по нему журнал режется на сутки.
- L136 `struct Record`

## bot/src/journal.rs · 310 строк

Журнал: append-only файл событий, суточная ротация, честное чтение.

- L27 `struct ReadReport`
- L38 `enum JournalError`
- L54 `impl From`
  - L55 `From::from`
- L60 `impl Display for JournalError`
  - L61 `JournalError::fmt`
- L87 `struct Journal` — Пишущая сторона. Читателей может быть сколько угодно, писатель один.
- L97 `impl Journal`
  - L100 `Journal::open` — Открыть журнал в каталоге; номер продолжается с найденного, а не с нуля — иначе рестарт раздвоил бы нумерацию.
  - L113 `Journal::append` — Записать событие: сначала строка с fsync, потом действие у вызывающего (write-ahead). Возвращает присвоенный…
- L147 `read_all` — Прочитать весь журнал каталога: сутки по возрастанию, внутри — по номеру; дубли сняты, противоречия и порча н…
- L242 `plain_days` — Простые (несжатые) сутки каталога.
- L259 `compress_day` — Сжать сутки целиком и атомарно: tmp → fsync → rename → удалить исходник. Обрыв на любом шаге не теряет данных…
- L274 `read_gz`
- L283 `utc_day` — Сутки UTC по метке в миллисекундах: `YYYY-MM-DD`. Календарь — алгоритм civil_from_days, чтобы не тянуть chron…
- L298 `mod tests`
  - L302 `calendar_matches_known_dates`

## bot/src/lib.rs · 11 строк

Исполнительное ядро (спека 09). Этап E1: журнал и состояние.


## bot/src/live.rs · 1843 строк

Живой исполнитель — этапы X1–X3 спеки 12.

- L63 `struct Instrument`
- L72 `struct OrderStatus`
- L81 `struct ExchPos`
- L94 `struct Resting`
- L102 `trait Exchange`
  - L103 `best_prices`
  - L104 `open_orders`
  - L106 `set_leverage` — Плечо 1× — спека 12 §2; отказ не блокирует вход, но пишется.
  - L107 `instrument`
  - L109 `place_limit`
  - L119 `cancel`
  - L120 `order_status`
  - L121 `positions`
  - L122 `wallet_usdt`
  - L126 `closed_pnl` — Реализованный результат закрытых позиций имени за окно: (момент мс, деньги $). Деньги сделки, закрытой мимо и…
- L134 `impl Exchange for Venue`
  - L135 `Venue::best_prices`
  - L138 `Venue::open_orders`
  - L146 `Venue::set_leverage`
  - L149 `Venue::instrument`
  - L154 `Venue::place_limit`
  - L168 `Venue::cancel`
  - L171 `Venue::order_status`
  - L176 `Venue::positions`
  - L191 `Venue::wallet_usdt`
  - L194 `Venue::closed_pnl`
- L209 `floor_step` — Вниз к кратному шага. Вверх округлять размер нельзя: нога 30 $ — это потолок забора (10 % капитала), и переша…
- L216 `ceil_step`
- L226 `step_decimals` — Число знаков после запятой у шага: печать заявки обязана нести ровно ту точность, которой шаг требует, — площ…
- L236 `fmt_step`
- L251 `lvl_bp` — Потолок цены входа/выхода: покупка — не дороже середины плюс `cap_bp`, продажа — не дешевле середины минус `c…
- L256 `cap_price`
- L269 `struct EntryEv`
- L284 `struct ExitEv`
- L293 `side_of`
- L301 `side_str`
- L309 `pos_key` — Ключ позиции — тот же, что у Python-счёта и тени: рука:час:имя:сторона.
- L315 `struct LiveCfg`
- L354 `impl LiveCfg`
  - L355 `LiveCfg::leg_usd`
  - L358 `LiveCfg::kill_file`
  - L367 `LiveCfg::limits_off_file` — Файл LIMITS_OFF в каталоге журнала — снятые ДЕНЕЖНЫЕ пределы §5 (день и итог), решение владельца о риске. Мар…
- L376 `struct LivePos`
- L398 `struct TickReport`
- L405 `struct Executor`
- L464 `journal_rules_guard` — Версия правил книги и журнал ЖИВЫХ денег: никакого само-архива. Инцидент 2026-08-23: при переводе на новую кн…
- L507 `impl Executor`
  - L512 `Executor::open` — Поднять исполнителя: журнал перечитывается, позиции сверяются с биржей (точное количество знает она), решения…
  - L787 `Executor::is_halted`
  - L791 `Executor::append`
  - L799 `Executor::halt`
  - L831 `Executor::tick` — Один такт. Порядок существенен: KILL раньше всего (после него не совершается ничего); ОБНАРУЖЕНИЕ исполнивших…
  - L903 `Executor::reconcile`
  - L939 `Executor::limits_breached`
  - L981 `Executor::flatten`
  - L999 `Executor::ensure_targets` — Цель ставится с входа и переставляется, пока не встанет: позиция без лежащей цели проверяет не то правило, ко…
  - L1068 `Executor::discover_target_fills` — Лимитка цели могла исполниться раньше, чем сторож записал событие, — биржа узнаёт первой. Обнаруженное исполн…
  - L1129 `Executor::process_exits`
  - L1209 `Executor::close_via_target` — Книга записала «дошла до цели». Если наша лимитка исполнилась — закрытие уже по её цене; если НЕТ — правило v…
  - L1261 `Executor::close_pos` — Принудительное закрытие reduceOnly-IOC с потолком цены. Не исполнилось — записанный отказ и повтор следующим…
  - L1354 `Executor::reject_exit`
  - L1374 `Executor::record_close`
  - L1413 `Executor::process_entries`
  - L1469 `Executor::reject_entry`
  - L1482 `Executor::try_enter`
  - L1716 `Executor::status_json` — Статус — атомарным файлом: полусписанный JSON у читателя был бы отказом, неотличимым от «исполнитель не работ…
  - L1758 `Executor::write_status`
- L1771 `now_ms_wall`
- L1780 `run_loop` — Цикл демона: такт раз в `interval_sec`, часы пересинхронизируются снаружи (в `main`) — здесь только логика.
- L1797 `mod tests`
  - L1801 `округления_вниз_и_вверх_по_шагу`
  - L1814 `печать_несёт_точность_шага`
  - L1822 `потолок_цены_округляется_внутрь`
  - L1837 `ключ_позиции_как_у_питона`

## bot/src/main.rs · 461 строк

`bot state <каталог> [капитал]` — вывести состояние из журнала.

- L10 `main`

## bot/src/paper.rs · 192 строк

Бумажное исполнение: лесенка, комиссия, деньги сделки.

- L23 `py_round` — Округление как в Python: `round(x, n)` округляет ДЕСЯТИЧНУЮ запись double к ближайшей, при равенстве — к чётн…
- L28 `struct FeeTable` — Таблица тейкерских ставок из выгрузки A1 (`fees.json`).
- L30 `impl FeeTable`
  - L33 `FeeTable::load` — Формат выгрузки — список записей площадки, ставка долями единицы в строке. Ключи ищутся по имени поля (урок з…
  - L55 `FeeTable::empty`
  - L61 `FeeTable::taker_bp` — `(ставка б.п., известна ли)`. Второе — мера покрытия, не украшение: молчаливое умолчание неотличимо от измере…
  - L68 `FeeTable::len`
  - L71 `FeeTable::is_empty`
- L80 `struct Book`
- L92 `walk` — Средняя цена рыночной заявки на `notional` долларов по лесенке. Возвращает `(цена, влезло ли целиком)` — част…
- L119 `struct Exec`
- L135 `exec_cost` — Исполнение по записанным книгам входа и выхода. Зеркало `trades.exec_cost` в части, которая делает деньги: дв…
- L164 `mod tests`
  - L168 `округление_как_у_питона`
  - L179 `лесенка_частичное_исполнение_честное`

## bot/src/picks.rs · 208 строк

Чтение решений модели и разборов — входных документов ядра.

- L23 `struct Leg`
- L35 `struct Pick`
- L53 `struct ReviewRow`
- L78 `struct Review`
- L87 `read_lines`
- L123 `load_picks` — Выборы руки. Дубли снимаются НА СТРОКЕ, как у Python-сборки: перезапуск пишет тот же час целиком — его строки…
- L147 `load_reviews` — Разборы руки: `(час, имя, сторона) → строка`.
- L173 `hour_ms` — `2026-08-05-11` → миллисекунды НАЧАЛА часа UTC. Обратная пара к `journal::utc_day`; проверена теми же закрепл…
- L196 `mod tests`
  - L201 `час_и_календарь_обратны_друг_другу`

## bot/src/state.rs · 150 строк

Состояние счёта — чистая функция от журнала.

- L16 `struct Position`
- L34 `struct State`
- L49 `enum StateError`
- L58 `impl Display for StateError`
  - L59 `StateError::fmt`
- L73 `derive` — Вывести состояние из записей. Записи обязаны идти в порядке журнала (это гарантирует читатель `journal::read_…

## bot/src/venue.rs · 635 строк

Площадка: подпись и запросы Bybit V5 (спека 12, этап X1).

- L22 `struct Keys` — Ключ и секрет. Debug и Display нарочно не выводят содержимое.
- L27 `impl Debug for Keys`
  - L28 `Keys::fmt`
- L41 `impl Keys`
  - L48 `Keys::load` — Читает env-файл вида `BYBIT_KEY=…` / `BYBIT_SECRET=…`. Файл кладёт владелец руками, поэтому разбор терпим к т…
  - L80 `Keys::sign` — Подпись V5: hex(HMAC-SHA256(secret, ts + key + recv + payload)).
- L94 `unwrap_ret` — Ответ площадки: `retCode == 0` — успех, иначе отказ с текстом. Разность имён (`retCode`/`ret_code`) площадка…
- L104 `struct Venue`
- L116 `impl Venue`
  - L117 `Venue::new`
  - L129 `Venue::now_ms`
  - L138 `Venue::server_time_ms` — Время площадки — публичный вызов без подписи.
  - L156 `Venue::sync_clock` — Меряет сдвиг часов и запоминает его для подписи.
  - L173 `Venue::get` — Подписанный GET: query уже собран строкой `k=v&k2=v2`.
  - L198 `Venue::post` — Подписанный POST: тело подписывается ДОСЛОВНО той же строкой, которая уходит на провод, — сериализуем один ра…
  - L221 `Venue::wallet_usdt` — Баланс единого счёта в USDT: (equity, доступно).
  - L257 `Venue::positions` — Открытые позиции по всем линейным USDT-перпам: (symbol, side, size, avgPrice, unrealisedPnl).
  - L291 `Venue::open_orders` — Открытые заявки: (symbol, orderId, side, qty, price).
  - L330 `Venue::closed_pnl` — Реализованный результат ЗАКРЫТЫХ позиций по имени за окно: (createdTime мс, closedPnl $). Единственный источн…
  - L370 `Venue::best_prices` — Лучшие цены: (bid, ask).
  - L397 `Venue::place_limit` — Лимитная заявка. `tif` — "IOC" или "PostOnly"; количество и цена приходят СТРОКАМИ: шаг цены и объёма у каждо…
  - L426 `Venue::set_leverage` — Плечо 1× — спека 12 §2. «Не изменилось» (110043) — не отказ.
  - L440 `Venue::cancel`
  - L455 `Venue::order_status` — Статус заявки: (status, cumExecQty, avgPrice, cumExecFee). Сначала `realtime` (открытые и свежезакрытые), зат…
  - L493 `Venue::instrument` — Живой справочник инструмента: (tick_size, qty_step, min_order_qty, min_notional_value). Снимок A1 на диске го…
  - L527 `Venue::executions` — Исполнения по символу за последние `hours` часов: (orderLinkId, side, qty, price, fee).
- L563 `mod tests`
  - L566 `tmp`
  - L576 `подпись_совпадает_с_независимой_реализацией`
  - L589 `ключ_читается_как_вставил_владелец`
  - L601 `ключ_без_секрета_это_отказ_словами`
  - L612 `секрет_не_печатается`
  - L623 `отказ_площадки_несёт_код_и_текст`

## tools/agents_run.sh · 383 строк

Запускалка ролей автономной системы.

- L79 `log_run()` — Строка прогона пишется ЯДРОМ журнала, а не echo в файл: формат один на запускалку, страницу и проверки, и вто…
- L91 `die()`
- L212 `call_model()`
- L247 `limit_hit()` — Откат на запасную модель — на ДВЕ причины и ровно один раз. Молчаливый перебор моделей превратил бы «роль отр…
- L260 `model_unsupported()` — Отказ ИМЕННО модели, а не задания: CLI её не знает или не берёт. Условие узкое намеренно — «unsupported» вооб…

## tools/diag_cycle.py · 302 строк

Почему молчит цикл обучения: хвост журнала и состояние манифеста.

- L22 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L30 `OUT = os.path.join(ROOT, 'research', 's8_loop…`
- L33 `_rows(p)` — Строки журнала книги. Файла нет — пусто, но это НЕ ошибка: книга, заведённая в этот час, разбора ещё не имеет.
- L52 `age(p)`
- L59 `main(argv=None)`

## tools/diag_dca.py · 49 строк

Идёт ли прогон бумажных DCA-книг и докуда дошёл.

- L15 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L16 `LOG = os.path.join(ROOT, 'research/dca_paper/…`
- L17 `ART = os.path.join(ROOT, 'research/dca_paper/…`
- L20 `main()`

## tools/diag_disk.py · 66 строк

Диски и куда на самом деле пишется запись стакана — одним заданием.

- L20 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L21 `PATHS = ['research/b1_book/out', 'out', 'resear…`
- L25 `sh(cmd)`
- L34 `main()`

## tools/diag_queue.py · 65 строк

Состояние канала заданий и идущих прогонов — одним заданием.

- L17 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L20 `run(*cmd)`
- L29 `tail(path, n=12)`
- L41 `main()`

## tools/diag_spill.py · 67 строк

Проверка перелива записи: читаются ли перелитые часы ПО ПРЕЖНЕМУ пути.

- L17 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L21 `OUT = os.path.join(ROOT, 'research', 'b1_book…`
- L22 `SPILL = os.path.join(os.path.dirname(ROOT), 'b1…`
- L25 `sh(cmd)`
- L34 `main()`

## tools/jobs.sh · 284 строк

Очередь заданий: сессия кладёт задание в git, сервер его выполняет.

- L42 `now()`
- L71 `role_busy()` — --- подтянуть задания ------------------------------------------------ Только перемотка вперёд: расхождение о…
- L87 `note()`

## tools/probe_cli_models.py · 56 строк

Какие модели принимает CLI НА ЭТОЙ машине.

- L26 `IDS = ['claude-fable-5-1', 'claude-opus-5', '…`
- L27 `ASK = 'Ответь ровно одним словом: ок'`
- L30 `run(argv, stdin=None, timeout=180)`
- L41 `main()`

## tools/project_map.py · 546 строк

Карта кода проекта — из самих файлов, не руками.

- L47 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L48 `DOCS = os.path.join(ROOT, 'docs')`
- L49 `OUT_MAP = os.path.join(DOCS, 'MAP.md')`
- L50 `OUT_SYM = os.path.join(DOCS, 'MAP-symbols.md')`
- L51 `OUT_TST = os.path.join(DOCS, 'MAP-tests.md')`
- L53 `CODE_EXT = ('.py', '.rs', '.sh', '.js')`
- L54 `DOC_LINE = 110`
- L55 `SIG_LEN = 64`
- L56 `VAL_LEN = 40`
- L60 `STAGES = {'common': 'общие модули (площадка, fun…` — Заголовки этапов — единственное рукописное знание в генераторе. Этап без строки печатается без названия, и эт…
- L125 `git_files()`
- L131 `read(path)`
- L136 `one_line(text, limit=DOC_LINE)`
- L141 `first_doc_line(doc)` — Первый абзац докстринга одной строкой (обрезанной до DOC_LINE).
- L160 `comment_block_above(lines, idx, marks=('#',))` — Блок комментариев, стоящий прямо над строкой idx (0-based), одной строкой. Шебанг и пустой блок не считаются.
- L184 `py_sig(node)` — ---------------------------------------------------------------- Python
- L193 `py_module(path)`
- L243 `RS_FN = re.compile('^(\\s*)(?:pub(?:\\([^)]*\\)…` — ------------------------------------------------------------------ Rust
- L244 `RS_TYPE = re.compile('^(?:pub(?:\\([^)]*\\))?\\s+…`
- L247 `RS_IMPL = re.compile('^impl(?:<[^>]*>)?\\s+(?:([\…` — Пути вида `crate::venue::Venue` допустимы: в карте остаётся последний сегмент — `impl Exchange for Venue`, ме…
- L248 `RS_MOD = re.compile('^(?:pub\\s+)?mod\\s+(\\w+)\…`
- L251 `rs_module(path)`
- L297 `SH_FN = re.compile('^(\\w+)\\s*\\(\\)\\s*\\{')` — ------------------------------------------------------------------ shell
- L300 `sh_module(path)`
- L320 `JS_FN = re.compile('^(?:async\\s+)?function\\s+…` — --------------------------------------------------------------------- JS
- L321 `JS_CONST = re.compile('^const\\s+(\\w+)\\s*=\\s*(?…`
- L324 `js_module(path)`
- L343 `md_title(path)`
- L350 `PARSERS = {'.py': py_module, '.rs': rs_module, '.…`
- L354 `is_test(path)`
- L361 `ROOT_GROUP = 'корень'` — ------------------------------------------------------------- сборка
- L364 `SELF = ('docs/MAP.md', 'docs/MAP-symbols.md', …` — Сами файлы карты в карту не входят: иначе первый коммит с ними менял бы карту на втором, и она никогда не был…
- L367 `group_of(path)`
- L378 `shown_name(group, path)` — Имя файла в карте: относительно каталога группы, чтобы `docs/journal/2026-08.md` не выглядел как файл в корне…
- L387 `build()`
- L511 `main(argv)`

## tools/publish.sh · 159 строк

Опубликовать артефакты прогона: отчёты и сводки — в git.

- L47 `finish_rebase()` — Конфликт на артефакте разрешается в пользу того, что лежит на диске ЗДЕСЬ, то есть в пользу прогона. Так уже…

## tools/publish_mech_code.py · 88 строк

Опубликовать КОД механики, отчёт которой уже уехал в git.

- L23 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L24 `FACTORY = os.path.join(ROOT, 'research', 'factory…`
- L25 `KEEP = ('.py', '.md', '.json', '.txt')`
- L28 `code_files(rel_dir)` — Код каталога: без `out/` (его публикует общая публикация).
- L43 `main(argv=None)`

## tools/repair_model_dir.sh · 78 строк

Вернуть МОДЕЛЬ из архива книги — разовая починка после дефекта,


## tools/restart_book.sh · 107 строк

Перезапуск сборщика стакана — одной командой и без тихих отказов.


## tools/retire_overfilled_book.py · 86 строк

Отставить запись книги, набранной СВЕРХ объявленной ширины.

- L29 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L35 `held_by_arm(mdir)` — Занятые ИМЕНА по рукам — счётом сканера, а не своим.
- L48 `main(argv)`

## tools/run.sh · 75 строк

Прогнать этап и опубликовать результат одной командой.


## tools/run_bot.sh · 151 строк

Запуск/перезапуск исполнительного ядра (Rust-тень, спека 09).


## tools/run_live.sh · 247 строк

Запуск/перезапуск ЖИВОГО исполнителя (спека 12, этапы X2–X3).


## tools/safety_check.sh · 107 строк

Проверка перед коммитом: то, что нельзя записать в историю случайно.

- L22 `say()`
- L24 `staged()`

## tools/spill_book.py · 214 строк

Перелив старых часов записи стакана с полного тома на корень — с символьной ссылкой на месте каждого файла.

- L48 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L49 `SRC = os.path.join(ROOT, 'research', 'b1_book…`
- L50 `DEST = os.path.join(os.path.dirname(ROOT), 'b1…`
- L51 `SUBS = ('book', 'trades')`
- L52 `NAME = re.compile('^(\\d{4}-\\d{2}-\\d{2})-\\d…`
- L53 `REQUIRE_OTHER_DEV = True`
- L54 `TAIL_CHECK = 65536`
- L57 `log(msg)`
- L61 `free_bytes(path)`
- L66 `df_line(path)`
- L74 `candidates(src, upto, subs=SUBS)` — (путь, размер, день) сжатых часов не позже `upto`, старые первыми.
- L97 `_same_bytes_at_ends(a, b, size)`
- L110 `copy_verified(src_path, dest_path)` — Копия под временным именем, проверенная размером и концами файла; неполная или отличная копия — исключение, о…
- L131 `spill_one(src_path, dest_path)` — Перенести один файл; вернуть размер. Оригинал уступает место ссылке только после проверенной копии.
- L143 `run(src=SRC, dest=DEST, upto=None, max_gb=50.0, min_root_free_g…`
- L194 `main(argv=None)`

## tools/stop_run.py · 125 строк

Остановить ИДУЩИЙ прогон очереди по пути скрипта — и ничего кроме него.

- L26 `PROTECTED = ('b1_book/collect.py', 's8_loop/train.p…`
- L29 `WAIT_S = 30`
- L32 `allowed(script)` — Путь, который вообще можно останавливать: research/… или tools/…, оканчивается на .py, без «..», не из защищё…
- L44 `match(ps_lines, script)` — Строки `ps -eo pid,args` → pid процессов `python <script> …`.
- L59 `ps_lines()`
- L65 `alive(pid)`
- L75 `stop(pids, log=print)`
- L96 `main(argv=None)`

## tools/unstick_publish.py · 77 строк

Разморозить публикацию: вернуть разрезанный журнал к версии git.

- L25 `ROOT = os.path.dirname(os.path.dirname(os.path…`
- L31 `REL = 'research/dca_paper/out/journal.jsonl'`
- L34 `main()`

## tools/watchdog_book.sh · 275 строк

Сторож сбора: поднимает умершее и перезапускает зависшее.

- L34 `now()`
