// Прогон логики живых страниц без браузера: DOM, canvas и сеть
// подменены заглушками, всё остальное — настоящий код страницы.
//
// Зачем отдельно от питоновских тестов: ошибка в разборе ответа или
// в склейке разностных кусков не роняет ничего видимого. Страница
// просто перестаёт обновляться, и это выглядит как «сборщик молчит», а
// не как дефект страницы. Владелец уже сообщал ровно такой симптом.
//
// Ответ подсовывается дважды: сначала полный, потом разностный — иначе
// проверялся бы только первый кадр, а склейка, ради которой всё и
// затевалось, не выполнялась бы ни разу.
//
//     node research/b1_book/headless_check.js <файл-со-страницей> [?строка]
//
// Второй аргумент — строка запроса страницы. Она нужна не для полноты:
// график открывают ССЫЛКОЙ на конкретную сделку, и весь этот путь —
// выбор руки, окно свечей в прошлом, подгонка вида — исполняется
// только когда параметры есть. Без аргумента проверялся бы живой режим,
// а открытая по ссылке страница падала бы у владельца.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const SEARCH = process.argv[3] || "?k=xxx&sym=BTCUSDT";
const js = src.match(/<script>\n([\s\S]*)<\/script>/)[1];
const isChart = /id="px"/.test(src);
const isTrades = /id="tb"/.test(src);
const isBot = /id="botlike-page"|Исполнительное ядро — тень/.test(src);
// Страницу открыли ссылкой на конкретную сделку модели.
const FOCUS = /hour=/.test(SEARCH);

const ctx = new Proxy({}, { get: (t, k) => {
  if (k === "canvas") return { clientWidth: 900 };
  if (k === "measureText") return () => ({ width: 40 });
  return () => undefined;
}, set: () => true });
const mkEl = () => new Proxy({
  style: {}, dataset: {}, clientWidth: 900, clientHeight: 380,
  textContent: "", innerHTML: "", getContext: () => ctx,
  getBoundingClientRect: () => ({ left: 0, top: 0 }),
  setAttribute: () => {}, addEventListener: () => {},
  querySelector: () => mkEl(), querySelectorAll: () => [],
}, { get: (t, k) => (k in t ? t[k] : () => undefined),
     set: (t, k, v) => ((t[k] = v), true) });
// Элементы кешируются ПО ИДЕНТИФИКАТОРУ. Прежде каждый вызов возвращал
// новый объект, поэтому написанное страницей в `innerHTML` тут же
// терялось, и любая проверка отрисованной разметки проходила вхолостую —
// отрицательный контроль это и показал: удаление таблицы сделок тест не
// уронило.
const ELS = new Map();
const elById = id => {
  if (!ELS.has(id)) ELS.set(id, mkEl());
  return ELS.get(id);
};
global.__el = elById;
global.document = {
  documentElement: mkEl(), getElementById: elById,
  querySelector: () => mkEl(), querySelectorAll: () => [],
  createElement: () => mkEl(), addEventListener: () => {},
};
global.location = { search: SEARCH };
global.history = { replaceState: () => {} };
global.window = { devicePixelRatio: 2, addEventListener: () => {},
                  history: global.history, location: global.location };
global.getComputedStyle = () => ({ getPropertyValue: () => "#000000" });
// Память страницы: в ней живёт состояние переключателя встречного счёта,
// чтобы перезагрузка его не гасила. Заводится включённым — тогда
// проверка заодно требует, чтобы страница САМА подтянула готовый счёт.
const LS = new Map([["rec", "1"]]);
global.localStorage = { getItem: k => (LS.has(k) ? LS.get(k) : null),
                        setItem: (k, v) => LS.set(k, String(v)),
                        removeItem: k => LS.delete(k) };
global.devicePixelRatio = 2;
global.setInterval = () => 0;          // такт даём сами, вручную
global.requestAnimationFrame = f => f();

// Свечи и сделки модели обязаны лежать в одном времени: иначе слой
// сделок не рисуется вовсе по фильтру окна, и проверка «сделка видна на
// графике» проходит вхолостую. Час подставных сделок — 2026-08-03,
// поэтому и край свечей там же.
const T0 = Date.UTC(2026, 7, 3, 23, 30) / 1000;
const trade = (i, closed) => ({
  id: "BTCUSDT-" + i, t: T0 - 600 + i, sym: "BTCUSDT", side: -1, long: true,
  entry: 64700, stop: 64600, target: 64900, level: 64700, kind: "полка",
  stop_bp: 15.5, rr: 2.0, held: 120, stop_by: "экстремум",
  state: closed ? "цель" : "открыта",
  pnl_bp: closed ? 20.5 : 0.0, r: closed ? 1.3 : 0.0,
  exit: closed ? 64900 : null, closed_at: closed ? T0 - 400 + i : null,
});
const candlesTo = (end, n) => Array.from({length: n}, (_, i) =>
  [end - (n - i) * 60, 64700, 64720, 64680, 64710, 1234.5]);
const candles = n => candlesTo(T0, n);
const state = (full, n) => ({
  sym: "BTCUSDT", symbols: ["BTCUSDT", "ETHUSDT"], now: T0 + (full ? 0 : 1),
  book: {s: "BTCUSDT", bid: 64700, ask: 64700.1, upd: 5,
         b: [[64700, 1.5]], a: [[64700.1, 2.5]]},
  bands: [{w: 0.05, bid: 100, ask: 120}],
  mid: full ? Array.from({length: 300}, (_, i) => [T0 - 300 + i, 64700 + i % 5])
            : [[T0 + 1, 64705]],
  mid_full: full,
  tape: full ? [{ts: T0 * 1000, p: 64700, v: 0.5, side: 1}]
             : [{ts: (T0 + 1) * 1000, p: 64701, v: 0.2, side: -1}],
  tape_full: full,
  log: full ? ["строка"] : [], log_n: 1,
  sig: {history_min: 40, near_x: 0.3, touch_x: 0.5, vol_mult: 5, imb: 0.3,
        diag: {long: {vol_x: 1.2, imb: 0.1, move_x: 0.5, why: "мало"},
               short: {}},
        candles: full ? candles(n) : candles(2).slice(-2),
        candles_full: full, done_total: 3, noise_bp: 12.0,
        levels: [{p: 64700, kind: "полка"}],
        open: [trade(9, false)],
        done: [trade(1, true), Object.assign(trade(2, true),
               {state: "оборвана перезапуском", pnl_bp: null, r: null})]},
  status: {uptime_sec: 3600, messages: 1e6, trades: 1e5, resets: 0,
           signals: 3, closed: 2, msg_per_sec: 150, ready: 2,
           last_msg_age_sec: 0.1, topics_live: 4, topics: 4,
           disk: {used_gb: 1.2, free_gb: 80.4, total_gb: 150.0,
                  rate_mb_h: 42.5, per_sym_mb_h: 5.3, days_left: 78.9,
                  by_kind: {book: 0.7, trades: 0.4, raw: 0.1}}},
});
const hist = {sym: "BTCUSDT", symbols: ["BTCUSDT"], count: 2,
              by_rule: {"лента": null, "стакан": null},
              trades: [trade(1, true), trade(2, true)],
              equity: [[T0 - 300, 20.5, 1.3], [T0 - 200, 41.0, 2.6]],
              by_ver: [{ver: 3, n: 1, stats: null},
                       {ver: 2, n: 6, stats: {trades: 6, win_rate: 0.17,
                        break_even: 0.4, expectancy_bp: -12.0,
                        expectancy_r: -0.5, median_bp: -14.0, median_r: -0.6,
                        stop_bp_median: 18.0, rr_median: 2.0,
                        held_median_sec: 200, share_target: 0.17,
                        share_stop: 0.83, share_time: 0.0,
                        cut_by_restart: 0}}],
              ver: 3,
              stats: {trades: 2, win_rate: 1.0, break_even: 0.31,
                      expectancy_bp: 20.5, expectancy_r: 1.3, median_bp: 20.5,
                      median_r: 1.3, stop_bp_median: 15.5, rr_median: 2.0,
                      held_median_sec: 120, share_target: 1.0, share_stop: 0.0,
                      share_time: 0.0, cut_by_restart: 1},
             };

// Встречный счёт: те же входы, другая геометрия. Опознаётся по номеру
// сделки — так видно, подменила ли страница показанное, а не только
// напечатала ли отчёт.
// Поле `was.id` связывает пересчитанную сделку с настоящей: без него
// новую геометрию не наложить на тот же вход, а отдельным графиком две
// картинки глазами не совместить.
const recTrade = i => Object.assign(trade(i, true),
  {id: "rec-" + i, stop: 64500, target: 65100, stop_bp: 31.0, rr: 4.0,
   was: {id: "BTCUSDT-" + i, stop_bp: 15.5}});
// Отвергнутый вход: сделки нет, но событие было. Он обязан доехать до
// графика — иначе «правило этот вход не берёт» выглядит как пропажа
// данных, и владелец так это и прочитал.
const noTrade = {id: "rec-нет", t: T0 - 300, sym: "BTCUSDT", long: true,
                 side: -1, entry: 64700, stop: null, target: null,
                 level: 64700, kind: "полка", state: "не открыта",
                 why: "стоп 31.0 б.п., ни один уровень впереди не даёт 1:1.5",
                 stop_bp: null, rr: null, held: null, pnl_bp: null, r: null,
                 exit: null, closed_at: null};
// `at` намеренно СТАРЫЙ (три часа назад), а живые сделки в `hist`
// свежее: так проверяется, что страница говорит о возрасте пересчёта.
// Снимок трёхчасовой давности на исправном сборщике выглядит точно как
// «новых сделок нет», и молчание тут — отказ, а не пустота.
const recount = {busy: false, done: 2, total: 2, hours: 24,
                 at: T0 - 3 * 3600, ver: 3,
                 made: 5, refused: 1, took_sec: 2.0, no_outcome: 1,
                 trades: [recTrade(1), recTrade(2), noTrade],
                 stats: hist.stats,
                 by_rule: hist.by_rule, equity: hist.equity};

let full = true, calls = 0;
const seen = [];
global.fetch = async (url) => {
  calls++; seen.push(url);
  const body = url.startsWith("/model_marks")
             ? {source: "model_pretest", at: Date.UTC(2026,7,3,19,30)/1000,
                rows: [{arm: "gbm", hour: "2026-08-03-18",
                        sym: "BTCUSDT", side: "long", cur_px: 101.0,
                        unreal_bp: 100.0, unreal_net_bp: 89.0,
                        closes_in_sec: 13800}]}
             : url.startsWith("/model_trades")
             ? {source: "model_pretest", pretest: true, page: 0, per: 100,
                total: 3, pages: 1, filtered: false, grand_total: 3,
                // Кривая счёта: четыре числа на точку — метка,
                // эквити и границы корзины. Полоса между ними и
                // есть провал, который иначе исчез бы при
                // прореживании.
                start: 1000,
                curves: {gbm: [[T0-7200, 1000, 1000, 1000],
                               [T0-3600, 960, 940, 1000],
                               [T0, 1012.5, 960, 1012.5]],
                         nn: [[T0-7200, 1000, 1000, 1000],
                              [T0-3600, 1004, 1000, 1006],
                              [T0, 981.2, 978, 1004]],
                         all: [[T0-7200, 2000, 2000, 2000],
                               [T0, 1993.7, 1940, 2006]]},
                symbols: ["BTCUSDT"],
                accounts: {gbm: {balance: 998.3, history: []}},
                stats: {all: {closed: 1, open: 1, no_outcome: 0,
                              // Итог по ногам: длинная зарабатывает,
                              // короткая теряет — ровно тот случай,
                              // ради которого разбивка и заведена.
                              n_long: 1, pnl_long: 24.55,
                              pnl_long_pct: 1.23, net_bp_long: 300.0,
                              n_short: 1, pnl_short: -8.07,
                              pnl_short_pct: -0.40, net_bp_short: -51.0,
                              hit_rate: 0.0, net_bp_avg: -51,
                              pnl: -0.85, expected_over_got: 18.1,
                              marked: 1, unreal_net_avg_bp: 89.0,
                              unreal_win: 1.0, unreal_pnl: 14.83,
                              exposure: 500.0, capital: 2000.0,
                              leverage: 0.25, fill_hours: 1,
                              fill_of: 4,
                              dd_measured: 2, dd_worst_bp: -412.0,
                              dd_med_bp: -155.0, dd_sized: 2,
                              dd_worst_cap_bp: -17.2, dd_worst_usd: -17.2,
                              dd_med_cap_bp: -6.5,
                              dd_open_worst_cap_bp: -6.5,
                              dd_open_book: {usd: -84.3, cap_bp: -843.0,
                                             hour: "2026-08-03-20",
                                             open: 12, full: true},
                              dd_book: {pct: -6.31, at: "2026-08-03-19",
                                        from: "2026-08-03-14",
                                        hours: 9, gaps: 0},
                              gift_n: 2, gift_med_bp: 12.4,
                              gift_avg_bp: 9.1, gift_lag_med: 393,
                              exec_n: 2, exec_med_bp: 18.4,
                              exec_avg_bp: 19.1, fee_med_bp: 11.0,
                              slip_med_bp: 7.4, fee_known: 1,
                              exec_partial: 0, cost_flat: 3},
                        gbm: {closed: 1, open: 1, no_outcome: 0,
                              hit_rate: 0.0, net_bp_avg: -51, pnl: -0.85,
                              marked: 1, unreal_net_avg_bp: 89.0,
                              unreal_win: 1.0, unreal_pnl: 14.83},
                        nn: {closed: 0, open: 0, no_outcome: 0,
                             marked: 0}},
                rows: [
                  {arm: "gbm", hour: "2026-08-03-18", sym: "BTCUSDT",
                   side: "long",
                   opened_at: Date.UTC(2026,7,3,19)/1000,
                   closes_at: Date.UTC(2026,7,3,23)/1000,
                   state: "открыта", expected_bp: 373, mae_bp: -50,
                   closes_in_sec: 13800, lag_sec: 313, odd: 0.03,
                   entry_px: 64700, cur_px: 64710,
                   unreal_bp: 100.0, unreal_net_bp: 89.0,
                   dd_bp: -155.0, dd_hours: 1, dd_usd: -6.5, dd_cap_bp: -6.5},
                  // Закрытая сделка со СВОЕЙ ценой входа и ходом цены:
                  // из этой пары график и строит выход. Без них слой
                  // рисовал бы только вход, и потеря выхода прошла бы
                  // незамеченной.
                  {arm: "gbm", hour: "2026-08-03-14", sym: "BTCUSDT",
                   side: "short",
                   opened_at: Date.UTC(2026,7,3,15)/1000,
                   closes_at: Date.UTC(2026,7,3,19)/1000,
                   state: "закрыта", expected_bp: -725, mae_bp: 90,
                   entry_px: 64700, got_bp: 40, net_bp: -51, pnl: -0.85,
                   dd_bp: -412.0, dd_hours: 4, dd_usd: -17.2,
                   dd_cap_bp: -17.2},
                  // Вторая рука в ТОТ ЖЕ час: ровно тот случай, ради
                  // которого заведён переключатель — нарисованные
                  // вместе, эти две сделки легли бы друг на друга.
                  {arm: "nn", hour: "2026-08-03-14", sym: "BTCUSDT",
                   side: "long",
                   opened_at: Date.UTC(2026,7,3,15)/1000,
                   closes_at: Date.UTC(2026,7,3,19)/1000,
                   state: "закрыта", expected_bp: 210, mae_bp: -40,
                   entry_px: 64700, got_bp: 40, net_bp: 29, pnl: 0.48}]}
             : url.startsWith("/trades") ? hist
             : url.startsWith("/recount") ? recount
             : url.startsWith("/groups")
               ? {groups: [{id: "memes",
                            symbols: ["DOGEUSDT", "1000PEPEUSDT"]},
                           {id: "other", symbols: ["BTCUSDT"]}]}
             : url.startsWith("/model")
               ? {present: true,
                  manifest: {version: 1, sections: 96, symbols: 540,
                             canary_ic: 0.003, importance: {},
                             trained_at: "2026-08-01T10:00:00+00:00"},
                  thoughts: [{at: "08-01 10:00", text: "проверка"}],
                  ic: [{target: "fwd_4h", median_ic: 0.021, sections: 24}],
                  // Предпросмотр со сделками ОБЯЗАН быть в подставном
                  // ответе: без него слой сделок модели не рисуется
                  // ни разу, и ошибка в нём прошла бы незамеченной —
                  // ровно тот отказ, который проект ловит везде.
                  pretest: {
                    present: true,
                    manifest: {version: 2, sections: 9, symbols: 543,
                               hedge: "выключен (бета не оценима)",
                               canary_ic: 0.004, canary_spread: 0.216,
                               canary_seeds: 5, importance: {},
                               trained_at: "2026-08-03T19:30:00+00:00"},
                    readiness: {sections: 9, need: 48, symbols: 543,
                                hours_per_symbol: 9, beta_min_hours: 96,
                                min_section: 30, features: 50,
                                by_hour: []},
                    last_run: {reason: "обучилась",
                               at: "2026-08-03T19:30:13+00:00"},
                    accounts: {gbm: {balance: 998.3,
                                     history: [{hour: "2026-08-03-17",
                                                pnl: -1.7, balance: 998.3},
                                               {hour: "2026-08-03-18",
                                                pnl: 0.9, balance: 999.2}]}},
                    trade_stats: {gbm: {closed: 2, open: 1, no_outcome: 0,
                                        hit_rate: 0.5, net_bp_avg: -0.5,
                                        pnl: -0.02, expected_avg: -95.5,
                                        got_avg: 50.5,
                                        expected_over_got: 12.5},
                                  nn: {closed: 0, open: 3,
                                       no_outcome: 0}},
                    trades: [
                      {arm: "gbm", hour: "2026-08-03-19", sym: "BTCUSDT",
                       side: "long", opened_at: Math.floor(Date.now()/1000)-600,
                       closes_at: Math.floor(Date.now()/1000)+13800,
                       state: "открыта", expected_bp: 373, mae_bp: -50,
                       closes_in_sec: 13800},
                      {arm: "gbm", hour: "2026-08-03-17", sym: "BTCUSDT",
                       side: "short", opened_at: Math.floor(Date.now()/1000)-7800,
                       closes_at: Math.floor(Date.now()/1000)-1400,
                       state: "закрыта", expected_bp: -725, mae_bp: -90,
                       got_bp: 40, net_bp: -51, pnl: -0.85, pos: 166.67}],
                    thoughts: [{at: "08-03 19:30", text: "предпросмотр"}],
                    ic: []}}
             : url.startsWith("/bot-full")
               ? {present: true, age_sec: 42.0, arm: "gbm",
                  capital_usd: 1000.0, balance_usd: 1125.01,
                  cash_usd: 0.0, busy_usd: 1125.01, open: 1, kill: false,
                  check: {ok: true, violations: [], warnings: [],
                          events: 32, open_positions: 1},
                  sverka: {ok: true, at_ms: 1785952800000,
                           note: "расхождений нет"},
                  error: null, server_now: 1785952860,
                  counts: {decisions: 12, rejects: 1, closed: 8, open: 1},
                  closed_total: 8,
                  positions: [{pos: "gbm:2026-08-05-10:AAAUSDT:long",
                               sym: "AAAUSDT", side: "long", size: 62.5,
                               entry_px: 50.02, cur_mid: 50.33,
                               unreal_bp: 62.0, unreal_usd: 0.39,
                               opened_at: 1785949200, closes_at: 1785963600}],
                  closed: [{pos: "gbm:2026-08-05-10:CCCUSDT:short",
                            hour: "2026-08-05-10", sym: "CCCUSDT",
                            side: "short", size: 62.5, entry_px: 1199.52,
                            exit_px: 1225.71, pnl: -1.5, basis: "книга",
                            closed_at: 1785949200}],
                  curve: [[1785949200, 998.5], [1785952800, 1125.01]],
                  sverka_report: "# Сверка бота с Python-счётом"}
             : url.startsWith("/bot")
               // Статус исполнительного ядра: живой, с чистыми
               // вердиктами и числами — панель обязана их ПОКАЗАТЬ.
               ? {present: true, age_sec: 42.0, arm: "gbm",
                  balance_usd: 990.08, cash_usd: 490.08, busy_usd: 500.0,
                  open: 12, kill: false,
                  pass_report: {appended: 0, opened: 0, closed: 0,
                                rejected: 0, waiting_review: 4},
                  check: {ok: true, violations: [], warnings:
                          ["застряла gbm:x: открыта 9.0 ч при сроке 4 ч"],
                          events: 32, open_positions: 12},
                  sverka: {ok: true, at_ms: 1785952800000,
                           note: "расхождений нет"},
                  error: null}
             : url.startsWith("/candles")
               // Окно уважается: сервер умеет отдавать прошлое, и
               // подставной ответ обязан вести себя так же. Отдавай он
               // всегда свежее — проверка «сделка недельной давности
               // видна» проходила бы вхолостую на сломанном сервере.
               ? (() => {
                   const m = /[?&]end=(\d+)/.exec(url);
                   const e = m ? Math.min(+m[1], T0) : T0;
                   return {sym: "BTCUSDT", candles: candlesTo(e, 1440),
                           hours: 24, end: e};
                 })()
               : state(full, 60);
  return {ok: true, json: async () => body};
};

process.on("unhandledRejection", e => {
  console.error("ПАДЕНИЕ в обработчике ответа:", e);
  process.exit(1);
});

// Точка такта живёт внутри области видимости страницы, поэтому её надо
// вынести наружу явно — иначе проверялся бы только запуск.
new Function(js + "\nglobal.__step = typeof tick !== 'undefined' "
                + "? tick : (typeof pull !== 'undefined' ? pull "
                + ": (typeof load !== 'undefined' ? load : null));"
                + "\nglobal.__st = typeof ST !== 'undefined' ? ST : null;"
                + "\nglobal.__cands = typeof cands === 'function' "
                + "? cands : null;"
                + "\nglobal.__rec = typeof pullRec === 'function' "
                + "? pullRec : null;"
                + "\nglobal.__REC = typeof REC !== 'undefined' ? REC : null;"
                + "\nglobal.__shown = typeof shown === 'function' "
                + "? shown : null;"
                // Строку про возраст пересчёта проверяем вызовом самой
                // функции, а не чтением `innerHTML`: DOM здесь заглушен,
                // и проверка по разметке проходила ВХОЛОСТУЮ — сломанный
                // `ageLine` её не ронял. Отрицательный контроль это и
                // показал.
                + "\nglobal.__age = typeof ageLine === 'function' "
                + "? ageLine : null;"
                // Что график ДЕЙСТВИТЕЛЬНО нарисовал: `draw` складывает
                // сюда по записи на каждую отрисованную сделку. Без
                // этого проверка смотрела на функцию-источник и не
                // замечала, что рисуется из другой, — тот самый отказ
                // «определено и не вызывается».
                + "\nglobal.__hit = typeof HIT !== 'undefined' "
                + "? () => HIT : null;"
                + "\nglobal.__barAt = typeof barAt === 'function' "
                + "? barAt : null;"
                // Слой сделок МОДЕЛИ: рука, найденная сделка и то,
                // отпущено ли слежение за краем. Проверять его по
                // разметке нельзя — он рисуется на canvas, а тот
                // заглушен; единственное свидетельство отрисовки —
                // записи в HIT и состояние самой страницы.
                + "\nglobal.__mdl = typeof MDL !== 'undefined' ? MDL : null;"
                + "\nglobal.__focused = typeof focused === 'function' "
                + "? focused : null;"
                + "\nglobal.__follow = () => typeof follow !== 'undefined' "
                + "? follow : null;"
                + "\nglobal.__table = typeof shownTrades === 'function' "
                + "? shownTrades : (typeof shown === 'function' "
                + "? () => shown().trades : null);"
                // Вкладка предпросмотра: её надо ОТКРЫТЬ в проверке,
                // иначе весь её код ни разу не исполняется, и падение
                // в нём достанется владельцу, а не тесту.
                + "\nglobal.__pretest = typeof renderModel === 'function' "
                + "&& typeof MDL !== 'undefined' && 'mode' in MDL "
                + "? () => { MDL.mode = 'pretest'; renderModel(); "
                + "          return document.getElementById('modelbox')"
                + "                 .innerHTML || ''; } : null;")();
(async () => {
  const step = global.__step;
  // Первый кадр отдан самой страницей при загрузке; ждём его, затем
  // подсовываем разностный ответ и проверяем склейку.
  await new Promise(r => setTimeout(r, 30));
  full = false;
  for (let i = 0; i < 3; i++) { await (step ? step() : null);
                                await new Promise(r => setTimeout(r, 10)); }
  if (!calls) { console.error("ПАДЕНИЕ: страница не сходила за данными");
                process.exit(1); }
  // Разностный кусок обязан ДОПОЛНИТЬ накопленное, а не заменить его.
  // Замена выглядит как исправная страница с графиком в две точки —
  // ровно тот отказ, который не отличить от «данных ещё нет».
  const st = global.__st, bad = [];
  // Обе страницы обязаны сходить и за состоянием, и за историей сделок.
  // Функция, которая определена и не вызывается ни откуда, — отказ,
  // неотличимый от «сделок пока нет»: панель просто пустая.
  //
  // Какая это страница, решает РАЗМЕТКА, а не список запросов. Прежде
  // признаком служил запрос `/model_trades`, и стоило графику пойти за
  // сделками модели — он тут же был принят за страницу сделок, и на
  // него посыпались чужие требования. Признак, выводимый из поведения,
  // ломается от изменения поведения; разметка страницы — это она сама.
  if (!isTrades && !isBot && !seen.some(u => u.startsWith("/state")))
    bad.push("страница не запросила состояние");
  if (global.__pretest) {
    let html = "";
    try { html = global.__pretest(); }
    catch (e) { bad.push("вкладка pre-testing упала: " + e.message); }
    // Мало не упасть — она обязана НАРИСОВАТЬ сделки. Пустая вкладка
    // неотличима от «сделок пока нет».
    if (!html) bad.push("вкладка pre-testing ничего не нарисовала");
    else {
      if (!/model trades|no model trades/.test(html))
        bad.push("вкладка pre-testing не показала сделок");
      // Режим хеджа обязан быть назван, и рядом — чего он НЕ снимает.
      // «Грубый хедж» без второй половины читается как «захеджировано»,
      // а разница бет между ногами остаётся неснятой.
      if (!/beta is taken as <b>1<\/b>/.test(html))
        bad.push("вкладка pre-testing не называет режим хеджа");
      if (!/difference(<\/b>)? between coins/.test(html))
        bad.push("не сказано, чего грубый хедж НЕ снимает");
      // Единица показа — ПРОЦЕНТ движения цены (решение владельца).
      // Проверяется по числу: +373 б.п. обязаны показаться как +3.73 %,
      // а не как «373». Проверка на наличие знака «%» прошла бы и на
      // проценте выигрышных сделок, то есть ни о чём.
      if (!/\+3\.73 %/.test(html))
        bad.push("сделки показаны не в процентах движения цены");
      if (/\bbp\b/.test(html))
        bad.push("в сделках остались базисные пункты");
    }
  }
  if (!isTrades && !isBot && !seen.some(u => u.startsWith("/trades")))
    bad.push("страница не запросила историю сделок (/trades)");
  // Страница сделок: кривая счёта, группы величин, сравнение рук.
  // Проверяется ЧИСЛАМИ из подставного ответа — «блок есть» прошло бы
  // и на пустом блоке, а пустой блок неотличим от «данных ещё нет».
  if (isTrades) {
    const st = global.__el ? String(
      global.__el("stats").innerHTML || "") : "";
    const lab = global.__el ? String(
      global.__el("eqlab").innerHTML || "") : "";
    // Кривая: подпись обязана назвать обе руки и их итог в процентах
    // от старта. 1012.5 при старте 1000 — это +1.25 %.
    if (!/\+1\.25 %/.test(lab) || !/-1\.88 %/.test(lab))
      bad.push("кривая счёта не подписала итог обеих рук");
    if (!/3 hours/.test(lab))
      bad.push("кривая счёта не сказала, на скольких часах построена");
    // Группы: без заголовков блоки налипают друг на друга.
    for (const g of ["result", "risk", "execution", "arms side by side"])
      if (!new RegExp(">" + g + "<").test(st))
        bad.push("нет группы величин: " + g);
    // Сравнение рук: обе колонки с числами, а не одна.
    if (!/998\.3 \$/.test(st))
      bad.push("в сравнении рук нет баланса");
    // Итог по ногам: деньги и доля старта. Проверяется числами —
    // «блок есть» прошло бы и на пустых значениях. Книга нейтральна по
    // числу позиций и не нейтральна по бете, и если весь доход даёт
    // одна сторона, это ставка на рынок, а не кросс-секция.
    if (!/\+24\.55 \$/.test(st) || !/\(\+1\.23 %\)/.test(st))
      bad.push("итог длинной ноги не показан в деньгах и в долях старта");
    if (!/-8\.07 \$/.test(st) || !/\(-0\.4 %\)/.test(st))
      bad.push("итог короткой ноги не показан");
    if (!/measurement error/.test(st))
      bad.push("не сказано, что разрыв между руками — ошибка измерения");
    // Пояснения свёрнуты, но обязаны ОСТАТЬСЯ: в них записано, почему
    // величина считается именно так. Свернуть и потерять — разные
    // вещи, и по виду страницы они неотличимы.
    if ((st.match(/<details/g) || []).length < 5)
      bad.push("пояснения групп пропали, а не свернулись");
    if (!/recorded order book/.test(st) || !/lower<\/b> bound/.test(st))
      bad.push("текст пояснений потерян при сворачивании");
  }
  // Страница ядра: числа из подставного ответа обязаны дойти до
  // разметки — баланс, доля, позиция с переоценкой, закрытая сделка,
  // вердикт сверки.
  if (isBot) {
    const acct = String(global.__el("acct").innerHTML || "");
    if (!/1125\.01/.test(acct)) bad.push("ядро: баланс не показан");
    if (!/\+12\.50 %/.test(acct)) bad.push("ядро: доля от старта не показана");
    if (!/расхождений 0/.test(acct)) bad.push("ядро: вердикт сверки не показан");
    const pos = String(global.__el("pos").innerHTML || "");
    if (!/AAA/.test(pos) || !/0\.62 %/.test(pos))
      bad.push("ядро: открытая позиция без переоценки");
    const cl = String(global.__el("cl").innerHTML || "");
    if (!/CCC/.test(cl) || !/-1\.5/.test(cl))
      bad.push("ядро: закрытая сделка не показана");
    const svp = String(global.__el("sv").textContent || "");
    if (!/Сверка бота/.test(svp))
      bad.push("ядро: отчёт сверки не показан");
  }

  // Панель исполнительного ядра — только на обзоре. Проверяется
  // ЧИСЛАМИ подставного ответа: «блок есть» прошло бы и на пустом
  // блоке, а пустой блок неотличим от «ядро не запущено».
  if (!isTrades && !isChart && !isBot) {
    const bb = global.__el ? String(
      global.__el("botbox").innerHTML || "") : "";
    if (!/990\.08/.test(bb))
      bad.push("панель ядра не показала баланс тени");
    if (!/расхождений 0/.test(bb))
      bad.push("вердикт сверки не показан");
    if (!/застряла/.test(bb))
      bad.push("предупреждения сторожа не показаны");
    if (/СТАТУС МОЛЧИТ/.test(bb))
      bad.push("свежий статус назван молчащим");
    const cap = global.__el ? String(
      global.__el("cap-bot").textContent || "") : "";
    if (!/42 с/.test(cap))
      bad.push("возраст статуса ядра не показан");
  }

  // График обязан достроить историю свечей с диска: без неё он
  // обрывается там, где кончается память сборщика, и прошлые сделки
  // смотреть не на чем.
  if (isChart && !seen.some(u => u.startsWith("/candles")))
    bad.push("график не запросил историю свечей (/candles)");
  // Сделки модели на графике. Это не украшение: страницу открывают
  // ссылкой из таблицы ради ответа «а что было с ценой», и слой,
  // который молча не рисуется, неотличим от «сделок по этой монете нет».
  if (isChart) {
    if (!seen.some(u => u.startsWith("/model_trades")))
      bad.push("график не запросил сделок модели");
    const M = global.__mdl, drawn = (global.__hit ? global.__hit() : [])
      .filter(h => h.mdl);
    if (!M) bad.push("график не держит слоя сделок модели");
    else {
      if (!drawn.length)
        bad.push("сделки модели не нарисованы ни одной");
      // Рука ОДНА. Две модели выбирают в один час по одной монете, и
      // нарисованные вместе они ложатся друг на друга — вход одной
      // закрывает вход другой, и чья это сделка, по картинке не сказать.
      else if (!drawn.every(h => h.mdl.arm === M.arm))
        bad.push("на графике сделки обеих рук: "
                 + drawn.map(h => h.mdl.arm).join(", "));
      // И выход обязан быть нарисован, а не только вход: иначе видно,
      // что сделка была, и не видно, чем кончилась.
      const cl = drawn.find(h => h.mdl.state === "закрыта");
      if (cl && cl.exit == null)
        bad.push("у закрытой сделки не нарисован выход");
      // Открытая по ссылке страница: рука из ссылки, сделка найдена,
      // окно свечей взято ЗА ПРОШЛОЕ и слежение за краем отпущено.
      if (FOCUS) {
        const want = /arm=nn/.test(SEARCH) ? "nn" : "gbm";
        if (M.arm !== want)
          bad.push(`рука из ссылки не выбрана: ${M.arm} вместо ${want}`);
        if (!global.__focused || !global.__focused())
          bad.push("сделка из ссылки не найдена среди загруженных");
        if (!seen.some(u => /\/candles.*[?&]end=\d+/.test(u)))
          bad.push("окно свечей под сделку не запрошено (нет end=)");
        if (global.__follow() !== false)
          bad.push("страница осталась следить за краем вместо сделки");
        if (!drawn.some(h => h.mdl.hour === M.hour))
          bad.push("сделка из ссылки не попала на график");
      }
    }
  }
  if (isChart && global.__cands) {
    const all = global.__cands();
    if (all.length <= (st.cand || []).length)
      bad.push(`история свечей не подмешалась: ${all.length} против живых `
               + `${(st.cand || []).length}`);
  }
  // Метка сделки обязана ложиться на СВОЮ свечу. Раньше положение
  // считалось долей окна по времени, а ряд свечей дырявый — минута без
  // сделок отсутствует, — и метки разъезжались при масштабировании.
  if (isChart && global.__barAt) {
    const gap = [[100, 1, 1, 1, 1, 0], [160, 1, 1, 1, 1, 0],
                 [1000, 1, 1, 1, 1, 0], [1060, 1, 1, 1, 1, 0]];
    const cases = [[90, 0], [100, 0], [159, 0], [160, 1], [999, 1],
                   [1000, 2], [1059, 2], [1060, 3], [9999, 3]];
    for (const [t, want] of cases) {
      const got = global.__barAt(gap, t);
      if (got !== want) {
        bad.push(`момент ${t} лёг на свечу ${got}, а должен на ${want}`);
        break;
      }
    }
    if (global.__barAt([], 5) !== 0)
      bad.push("пустой ряд свечей роняет привязку меток");
  }
  // Склейка разностных кусков проверяется у страниц, которые её
  // делают. У истории сделок разностного опроса нет вовсе: она
  // тянет страницу целиком, и требовать от неё накопленного буфера
  // значит проверять не то.
  if (st) {
    const buf = st.mid && st.mid.length ? st.mid : st.cand;
    if (!buf || buf.length < 50)
      bad.push(`склейка потеряла историю: осталось ${
        buf ? buf.length : "—"}`);
    if (st.cand && st.cand.length && st.cand.length < 50)
      bad.push(`свечи склеились неверно: ${st.cand.length}`);
  }
  // Вид ОДИН: всё под нынешними правилами, тумблера нет. Решение
  // владельца, и оно снимает целый класс путаницы — застывший снимок
  // часами подменял таблицу, а страница молчала об этом.
  // Проверять надо ВЕСЬ файл (`src`), а не только скрипт: кнопка живёт
  // в разметке, и первая версия этой проверки искала её в `js` —
  // то есть проходила вхолостую. Отрицательный контроль это показал.
  if (/id="rec"/.test(src))
    bad.push("на странице осталась кнопка пересчёта");
  if (/localStorage\.getItem\("rec"\)/.test(src))
    bad.push("состояние тумблера всё ещё поднимается из памяти страницы");
  if (isTrades) {
    // У истории сделок пересчёта нет вовсе — она про модель, а не про
    // детектор ленты. Проверяется здесь другое: что страница
    // действительно нарисовала строки, а не молча осталась пустой.
    const tb = global.__el ? global.__el("tb") : null;
    const html = tb ? String(tb.innerHTML || "") : "";
    if (!html) bad.push("страница сделок ничего не нарисовала");
    else if (!/\+3\.73 %|no trades yet/.test(html))
      bad.push("строки сделок не в процентах движения цены");
    const stats = global.__el ? String(
      global.__el("stats").innerHTML || "") : "";
    if (!/trades/.test(stats))
      bad.push("общая статистика не показана");
    // Разбиение по рукам турнира: без него не видно, какая из двух
    // моделей даёт результат, а он у них общий на вид.
    if (!/data-sa="gbm"/.test(stats) || !/data-sa="nn"/.test(stats)
        || !/data-sa="all"/.test(stats))
      bad.push("статистика не делится на all / ml / ai");
    // Нереализованное в сводке: 89 б.п. = +0.89 %, и деньги отдельно.
    if (!/\+0\.89 %/.test(stats))
      bad.push("нереализованное не попало в общую статистику");
    if (!/14\.83/.test(stats))
      bad.push("нереализованные деньги не показаны");
    // Экспозиция без знаменателя читается как «депозит стал 500».
    // Требуем капитал рядом и плечо числом.
    if (!/500 \$ \/ 2000/.test(stats))
      bad.push("экспозиция показана без капитала");
    if (!/0\.25×/.test(stats))
      bad.push("плечо не показано");
    // И почему оно ниже единицы: книга набирается 4 часа.
    if (!/filling 1\/4 h/.test(stats))
      bad.push("не сказано, что книга ещё набирается");
    // И оно обязано стоять ОТДЕЛЬНО от факта, а не в одной строке.
    if (!/not a result yet/.test(stats))
      bad.push("нереализованное не отделено от результата");
    // Просадка. Худшая сделка −412 б.п. = −4.12 %, просадка счёта
    // −6.31 %. Проверяется числом: наличие слова «drawdown» прошло бы
    // и на пустом блоке, а пустой блок неотличим от «просадки не было».
    // Ведущее число — вся живая книга в один момент, а не худшая
    // сделка: −843 б.п. депозита = −8.43 %. Проверяется числом, потому
    // что «есть блок просадки» прошло бы и на одной сделке.
    if (!/-8\.43 %/.test(stats))
      bad.push("общая просадка книги не показана");
    if (!/-84\.3 \$/.test(stats))
      bad.push("общая просадка книги не показана в деньгах");
    if (!/12 pos/.test(stats))
      bad.push("не сказано, сколько позиций стояло в худший момент");
    if (!/-0\.17 %/.test(stats))
      bad.push("худшая просадка сделки не показана в долях депозита");
    if (!/-17\.2 \$/.test(stats))
      bad.push("худшая просадка сделки не показана в деньгах");
    if (!/deposit/.test(stats))
      bad.push("единица просадки не названа — от позиции или от депозита");
    if (!/-6\.31 %/.test(stats))
      bad.push("просадка счёта не показана");
    if (!/lower<\/b> bound|lower bound/.test(stats))
      bad.push("просадка выдана за точную, без оговорки о нижней оценке");
    // Подарок входа: книга записана по цене закрытия часа, а решение
    // пришло 393 с спустя. Число обязано быть на виду — иначе условность
    // живёт в JSON и читается как «её нет».
    // Издержки: круг обязан быть виден разложением, а не одной
    // цифрой, и покрытие ставок — числом. Умолчание, не отличимое от
    // измерения, есть ровно тот класс дефекта, который проект ловит
    // с A2: пустота выдаёт себя за результат.
    if (!/18\.4 bp/.test(stats))
      bad.push("круг издержек не показан");
    if (!/11 bp/.test(stats) || !/7\.4 bp/.test(stats))
      bad.push("круг не разложен на комиссию и спред");
    if (!/1\/2/.test(stats))
      bad.push("покрытие настоящей ставкой не показано");
    if (!/recorded order book/.test(stats))
      bad.push("не сказано, что издержки считаны по записанной книге");
    if (!/12\.4 bp/.test(stats))
      bad.push("подарок входа не показан числом");
    if (!/393 s/.test(stats))
      bad.push("задержка решения не показана рядом с подарком");
    if (!/not yet applied/.test(stats))
      bad.push("не сказано, что подарок пока только измеряется");
    const pg = global.__el ? String(
      global.__el("pg").textContent || "") : "";
    if (!/page \d+ of/.test(pg))
      bad.push("нумерация страниц не показана");
    // Время показывается в поясе владельца, а НЕ в UTC. Подставная
    // сделка входит в 19:00 UTC, значит в Вене это 21:00 — проверка
    // по числу, а не по наличию двоеточия.
    if (!/21:00/.test(html))
      bad.push("время показано не в поясе владельца");
    // Ключ часа обязан остаться доступным: сдвинутый ключ ничему в
    // файлах и журналах не соответствует.
    if (!/UTC key/.test(html))
      bad.push("ключ часа в UTC потерян");
    // «Состояние» — это состояние, а не время закрытия. Само время
    // закрытия обязано быть отдельной колонкой: выход 23:00 UTC — это
    // 01:00 в Вене, и именно это число обязано появиться.
    if (!/01:00/.test(html))
      bad.push("время выхода не показано отдельно");
    if (!/>open\b/.test(html))
      bad.push("состояние показано не словом");
    // Нереализованный результат открытой сделки: 89 б.п. = +0.89 %.
    if (!/\+0\.89 %/.test(html))
      bad.push("нереализованный результат открытой сделки не показан");
    // И он обязан обновляться ОТДЕЛЬНЫМ частым запросом, иначе весь
    // список пришлось бы тянуть каждые десять секунд.
    if (!seen.some(u => u.startsWith("/model_marks")))
      bad.push("переоценка не запрашивается отдельно");
    // Просадка по КАЖДОЙ сделке, а не только в сводке: закрытая сделка
    // тут дала −412 б.п. = −4.12 % по дороге при итоге −0.51 %, и
    // увидеть это можно только в строке.
    if (!/-0\.17 %/.test(html))
      bad.push("просадка сделки в строке не в долях депозита");
    if (/>-4\.12 %</.test(html))
      bad.push("в строке ведущим числом остался процент от позиции");
  } else if (isBot) {
    // У страницы ядра нет ни пересчёта, ни детекторных сделок — её
    // проверки выше, числами из /bot-full.
  } else if (!global.__rec || !global.__table) {
    bad.push("страница не забирает пересчёт");
  } else {
    // Пересчёт обязан быть запрошен САМ, при загрузке, и обязательно
    // словом «не начинай новый»: счёт запускает сборщик при смене
    // версии правил, а страница только забирает готовое. Иначе каждое
    // открытие вкладки гоняло бы трёхминутный прогон заново.
    const self = seen.filter(u => u.startsWith("/recount"));
    if (!self.length)
      bad.push("пересчёт не запрошен при загрузке");
    else if (!self.every(u => /go=0/.test(u)))
      bad.push("страница запускает новый пересчёт: " + self[0]);
    // И показана обязана быть именно пересчитанная геометрия, БЕЗ
    // единого нажатия: владелец просил, чтобы старой на графике не было
    // вовсе, а нажимать ничего не требовалось.
    const tr = global.__table();
    if (!tr.length || !tr.every(m => String(m.id || "").startsWith("rec-")))
      bad.push(`показаны не пересчитанные сделки: ${tr.length} строк, `
               + `первая ${tr.length ? tr[0].id : "—"}`);
    // Открытая по ссылке страница стоит окном на сделке модели, и
    // сделок детектора в этом окне может не быть вовсе — требовать их
    // там значит требовать, чтобы окно НЕ переехало.
    if (isChart && !FOCUS) {
      // Только сделки ДЕТЕКТОРА: в том же списке лежат теперь и сделки
      // модели, а у них ни `id`, ни геометрии пересчёта нет вовсе.
      const drawn = global.__hit ? global.__hit().filter(h => h.m) : null;
      if (!drawn || !drawn.length)
        bad.push("график не нарисовал ни одной сделки");
      else if (!drawn.every(h => String(h.m.id || "").startsWith("rec-")))
        bad.push("на графике осталась старая геометрия: "
                 + drawn.map(h => h.m.id).join(", "));
      // Вход, который правило не взяло, обязан быть НАРИСОВАН, а не
      // пропущен: молчание тут неотличимо от потери данных.
      else if (!drawn.some(h => h.m.state === "не открыта"))
        bad.push("отвергнутый вход не показан на графике");
    }
    // Возраст пересчёта обязан быть назван, и назван числом: иначе
    // застывший снимок читается как «сделок больше не находится».
    if (!global.__age) {
      bad.push("страница не говорит о возрасте пересчёта (нет ageLine)");
    } else {
      const note = global.__age(recount, hist.trades) || "";
      if (!/computed at/.test(note))
        bad.push("возраст пересчёта не показан: " + JSON.stringify(note));
      if (!/\b\d+ min ago/.test(note))
        bad.push("возраст не назван числом минут: " + JSON.stringify(note));
      if (!/Live trades after that moment/.test(note))
        bad.push("новые живые сделки после пересчёта не названы: "
                 + JSON.stringify(note));
    }
  }
  if (bad.length) { console.error("ПАДЕНИЕ: " + bad.join("; "));
                    process.exit(1); }
  console.log(`логика страницы отработала без ошибок, запросов ${calls}, `
    + `середина ${st && st.mid ? st.mid.length : "—"}, свечей ${
        st && st.cand ? st.cand.length : "—"}`);
})();
