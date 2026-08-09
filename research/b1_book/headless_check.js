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
const isInfo = /id="whybox"/.test(src);
const isLeague = /league — what works best/.test(src);
const isGloss = /playbook — what the model can read/.test(src);
const isVol = /does the market regime move our results/.test(src);
const isTree = /model tree — which logic each branch tests/.test(src);
const isTrades = /id="tb"/.test(src);
const isBot = /id="botlike-page"|Исполнительное ядро — тень/.test(src);
// Страницу открыли ссылкой на конкретную сделку модели.
const FOCUS = /hour=/.test(SEARCH);

// Нарисованное надо чем-то наблюдать: холст здесь заглушка, и
// единственный видимый снаружи след отрисовки — подписи. По ним
// проверяется вертикаль цены: сдвинулась ли шкала.
global.__texts = [];
const ctx = new Proxy({}, { get: (t, k) => {
  if (k === "canvas") return { clientWidth: 900 };
  if (k === "measureText") return () => ({ width: 40 });
  if (k === "fillText") return (s) => { global.__texts.push(String(s)); };
  return () => undefined;
}, set: () => true });
const mkEl = () => new Proxy({
  style: {}, dataset: {}, clientWidth: 900, clientHeight: 380,
  textContent: "", innerHTML: "", getContext: () => ctx,
  getBoundingClientRect: () => ({ left: 0, top: 0 }),
  setAttribute: () => {}, _ev: {},
  addEventListener: function (t, f) {
    (this._ev[t] = this._ev[t] || []).push(f);
  },
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
        // Выключенный детектор ничего не ведёт: ни открытых, ни
        // закрытых. Подставной ответ обязан вести себя так же, иначе
        // проверка «пустая история названа выключенной» шла бы на
        // непустой истории и не проверяла ничего.
        open: /paperoff=1/.test(SEARCH) ? [] : [trade(9, false)],
        done: /paperoff=1/.test(SEARCH) ? []
              : [trade(1, true), Object.assign(trade(2, true),
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
             ? {source: "model", at: Date.UTC(2026,7,3,19,30)/1000,
                rows: [{arm: "gbm", hour: "2026-08-03-18",
                        sym: "BTCUSDT", side: "long", cur_px: 101.0,
                        unreal_bp: 100.0, unreal_net_bp: 89.0,
                        closes_in_sec: 13800}]}
             : url.startsWith("/volatility") && /voldown=1/.test(SEARCH)
             ? (() => { throw new Error("сборщик молчит"); })()
             : url.startsWith("/volatility")
             ? {present: true, n: 40, no_hour: 3, days: 12,
                hours_measured: 300, cuts_bp: [22.0, 61.0],
                buckets: ["quiet", "normal", "loud"], errors: [],
                // Отбор волатильных имён: 1.42× — перекос, который
                // страница обязана НАЗВАТЬ, а не просто напечатать.
                pick_vol: {n: 37, rel_med: 1.42, above: 0.73,
                           own_med_bp: 68.0},
                series: [{hour: "2026-08-01-10", bp: 14.0, n: 500},
                         {hour: "2026-08-01-11", bp: 55.0, n: 500},
                         {hour: "2026-08-02-12", bp: 180.0, n: 498}],
                books: {h4: {
                  all: {all: {n: 40, days: 12, win: 0.45, pnl: -3.5,
                              net_bp_avg: -4.0, vol_med_bp: 48.0},
                        quiet: {n: 25, days: 9, win: 0.3, pnl: -9.4,
                                net_bp_avg: -21.0, vol_med_bp: 16.0},
                        normal: {n: 12, days: 6, win: 0.6, pnl: 4.1,
                                 net_bp_avg: 12.0, vol_med_bp: 44.0},
                        // Тонкая корзина: три сделки с двух дней —
                        // страница обязана пометить её как анекдот.
                        loud: {n: 3, days: 2, win: 1.0, pnl: 1.8,
                               net_bp_avg: 55.0, vol_med_bp: 150.0}},
                  gbm: {all: {n: 20, days: 10, win: 0.5, pnl: 1.0,
                              net_bp_avg: 2.0, vol_med_bp: 47.0},
                        quiet: null, normal: null, loud: null}}}}
             : url.startsWith("/model_tree")
             ? {roots: [
                  {arm: "gbm", title: "ML — decision trees",
                   title_ru: "ML — деревья решений",
                   plain: "Reads thresholds and break points.",
                   plain_ru: "Читает пороги и изломы."},
                  {arm: "nn", title: "AI — neural net",
                   title_ru: "AI — нейросеть",
                   plain: "Blends many features smoothly.",
                   plain_ru: "Гладко смешивает много признаков."}],
                books: [
                  {key: "h4", dir: "model", present: true,
                   title: "4-hour book — the main one",
                   title_ru: "Книга 4 часа — главная",
                   plain: "Does ranking the cross-section make money.",
                   plain_ru: "Зарабатывает ли само ранжирование "
                             + "сечения.",
                   facts: "hold 4 h · 24 slots",
                   stats: {gbm: {closed: 5, win: 0.6, pnl: 12.34},
                           nn: {closed: 4, win: 0.25, pnl: -3.21}}},
                  {key: "sit", dir: "model_sit", present: true,
                   title: "situational book — price pulls the trigger",
                   title_ru: "Ситуационная книга — курок у цены",
                   plain: "Does picking the moment add anything.",
                   plain_ru: "Даёт ли выбор момента что-то сверх "
                             + "расписания.",
                   facts: "gate 22 bp · RR ≥ 2 · stop τ 0.2",
                   stats: {gbm: {closed: 3, win: 0.667, pnl: 4.10}}},
                  // Книга без манифеста на сервере: ветка обязана
                  // сказать «не заведена», а не выглядеть пустой.
                  {key: "h24", dir: "model_h24", present: false,
                   title: "24-hour book", title_ru: "Книга 24 часа",
                   plain: "Slow end.", plain_ru: "Медленный край.",
                   facts: "", stats: {}}],
                tournament: {
                  title: "policy tournament (spec 10)",
                  title_ru: "Турнир политик исполнения (спека 10)",
                  plain: "The picking rule is judged, not the winner.",
                  plain_ru: "Судится правило выбора, а не победитель.",
                  present: true, legs: 3840, points: 3,
                  pick: "e22_rr1.5_sm_t1_a24", cells_measured: 12,
                  status: "диагностика, не вердикт: точек 3 из 8"},
                errors: [], generated_at: 0}
             : url.startsWith("/glossary")
             ? {present: true, n_features: 3, train_seq: 77,
                weight_covers: 0.2, weight_arm: "gbm",
                weight_target: "fwd_4h", error: null,
                families: [
                  {key: "absorption",
                   title: "Absorption — the book being eaten",
                   plain: "Someone keeps putting size back at the same "
                          + "price while the market keeps hitting it.",
                   reads: "aggressive volume against displayed depth",
                   caveat: "Measured on prints alone this carried no "
                           + "direction at all.",
                   title_ru: "Выедение стакана — поглощение",
                   plain_ru: "Кто-то доставляет объём на ту же цену, "
                             + "пока по нему бьют.",
                   reads_ru: "агрессивный объём против показанной "
                             + "глубины",
                   caveat_ru: "По одним принтам направления нет вовсе.",
                   features: [{name: "eat_bid", weight: 0.12}],
                   n_features: 1, weight: 0.12,
                   traded: {n: 5, pnl: 8.0, win: 0.6}},
                  {key: "oi", title: "Open interest",
                   plain: "How much money is standing in this contract "
                          + "right now against its usual level.",
                   reads: "open interest vs its own past week",
                   caveat: null,
                   title_ru: "Открытый интерес",
                   plain_ru: "Сколько денег стоит в контракте сейчас "
                             + "против обычного уровня.",
                   reads_ru: "интерес против собственной недели",
                   caveat_ru: null,
                   features: [{name: "oi_rel", weight: 0.08},
                              {name: "oi_chg_4h", weight: 0}],
                   n_features: 2, weight: 0.08, traded: null}]}
             : url.startsWith("/league")
             ? {present: true, closed_total: 3,
                errors: ["model_h24: ValueError: boom"],
                books: [{book: "model_sit", trades: 3,
                         closed_kept: 2}],
                periods: {
                 today: {n: 0, groups: {}, best: [], worst: [],
                         setup_known: 0},
                 "30d": {n: 3, setup_known: 2, groups: {
                     arm: [{key: "nn", n: 2, win: 0.5, pnl: 4.1,
                            net_bp_avg: 12.0},
                           {key: "gbm", n: 1, win: 0, pnl: -3.0,
                            net_bp_avg: -51.0}],
                     book: [{key: "sit", n: 2, win: 0.5, pnl: 4.1,
                             net_bp_avg: 12.0},
                            {key: "h1", n: 1, win: 0, pnl: -3.0,
                             net_bp_avg: -51.0}],
                     setup: [{key: "liq", n: 1, win: 1, pnl: 8.0,
                              net_bp_avg: 49.0}],
                     side: [{key: "long", n: 3, win: 0.33, pnl: 1.1,
                             net_bp_avg: -5.0}]},
                   best: [{hz: "sit", arm: "nn", hour: "2026-08-03-14",
                           sym: "AAAUSDT", side: "long",
                           at: 1786190000, net_bp: 49.0, pnl: 8.0,
                           setup: "liq"}],
                   worst: [{hz: "h1", arm: "gbm",
                            hour: "2026-08-03-15", sym: "CCCUSDT",
                            side: "long", at: 1786190100,
                            net_bp: -51.0, pnl: -3.0, setup: null}]},
                 "365d": {n: 3, groups: {}, best: [], worst: [],
                          setup_known: 2}}}
             : url.startsWith("/model_trades")
             ? {source: "model", page: 0, per: 100,
                // Слитая позиция: два лота одного имени. График обязан
                // нарисовать ОДНУ позицию, точку долива и засечку
                // разгрузки — четыре наложенных прямоугольника были
                // именно тем, что владелец не мог прочесть.
                merged: [{arm: "gbm", hour: "2026-08-03-12",
                          sym: "BTCUSDT", side: "long",
                          entry_px: 64700, avg_px: 64750,
                          size_total: 150, lots: 2,
                          opened_at: T0 - 600, closes_at: T0 - 200,
                          state: "закрыта", net_bp: 20.0, pnl: 0.3,
                          exit_px: 64900,
                          mae_bp: -50, mfe_bp: 120,
                          adds: [{at: T0 - 400, px: 64800, size: 50,
                                  hour: "2026-08-03-13"}],
                          exits: [{at: T0 - 200, px: 64900, size: 150,
                                   net_bp: 20.0, pnl: 0.3,
                                   state: "закрыта"}]}],
                // Правила книги — в ответе: из них страница графика
                // собирает объяснение сделки словами.
                stop_tau: 0.2, min_edge_bp: 22, min_rr: 2,
                min_disc_bp: 11, rules_version: 8,
                // Книга без срока: страница обязана переставить
                // столбцы — час здесь ключ листа, а не время сделки.
                ...(/hz=sit/.test(url)
                    ? {situational: true, horizon_h: null} : {}),
                total: 4, pages: 1, filtered: false, grand_total: 4,
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
                   // Просьба владельца: сделка несёт номер обучения и
                   // вклад признаков; страница обязана собрать из них
                   // объяснение словами.
                   train_seq: 124, mae_m_bp: -12,
                   stop_of: "maeq_4h", fwd0_bp: 180,
                   why: [["ret_7", 45.2], ["eat_bid", -12.1]],
                   setup: [["liq", 0.42], ["absorption", 0.25]],
                   entry_px: 64700, got_bp: 40, net_bp: 29, pnl: 0.48},
                  // Сделка БЕЗ СРОКА, как у ситуационной книги: конца
                  // нет вовсе. Она и показала дефект — спан схлопывался
                  // в точку, и от живой позиции оставалась одна метка
                  // входа, без зон и обещаний.
                  {arm: "gbm", hour: "2026-08-03-20", sym: "BTCUSDT",
                   side: "long",
                   opened_at: Date.UTC(2026,7,3,21)/1000,
                   closes_at: null,
                   state: "открыта", expected_bp: 150, mae_bp: -60,
                   mfe_bp: 210, entry_px: 64700,
                   unreal_bp: 30, unreal_net_bp: 19}]}
             // Выключенный детектор — это ОТВЕТ сервера, а не пустая
             // история: страница обязана назвать причину, иначе
             // выключенное наблюдение читается как поломка записи.
             : url.startsWith("/trades")
             ? (/paperoff=1/.test(SEARCH)
                ? {off: true, sym: "BTCUSDT", symbols: ["BTCUSDT"],
                   trades: [], stats: null, by_rule: {}, equity: [],
                   count: 0, by_ver: [], ver: 3, older: 0}
                : hist)
             // Выключённый детектор — и пересчитывать нечего: сервер
             // отвечает `off` на оба запроса, подставной обязан тоже.
             : (url.startsWith("/recount") && /paperoff=1/.test(SEARCH))
             ? {off: true, sym: "BTCUSDT", trades: [], stats: null,
                by_rule: {}, equity: [], ver: 3, busy: false}
             : url.startsWith("/recount") ? recount
             : url.startsWith("/groups")
               ? {groups: [{id: "memes",
                            symbols: ["DOGEUSDT", "1000PEPEUSDT"]},
                           {id: "other", symbols: ["BTCUSDT"]}]}
             : url.startsWith("/model")
               // Боевой контур со сделками: панель сделок теперь живёт
               // здесь (предпросмотр снят), и без сделок в подставном
               // ответе её код не исполнялся бы ни разу.
               ? {present: true,
                  manifest: {version: 1, sections: 96, symbols: 540,
                             canary_ic: 0.003, importance: {},
                             trained_at: "2026-08-01T10:00:00+00:00"},
                  thoughts: [{at: "08-01 10:00", text: "проверка"}],
                  ic: [{target: "fwd_4h", median_ic: 0.021, sections: 24}],
                  accounts: {gbm: {balance: 998.3,
                                   history: [{hour: "2026-08-03-17",
                                              pnl: -1.7, balance: 998.3},
                                             {hour: "2026-08-03-18",
                                              pnl: 0.9, balance: 999.2}]}},
                  // Итог по книге сервер отдаёт ключом `all`, и
                  // на вкладке «обе» показывается ТОЛЬКО он: разбивка
                  // по рукам живёт за соседними кнопками.
                  // Открытые деньги: у `gbm` переоценены не все
                  // позиции (2 из 3) — знаменатель обязан быть виден,
                  // у `nn` закрытых нет вовсе, и отметка там всё, что
                  // о книге известно.
                  trade_stats: {gbm: {closed: 2, open: 3, no_outcome: 0,
                                      hit_rate: 0.5, net_bp_avg: -0.5,
                                      pnl: -0.02, expected_avg: -95.5,
                                      got_avg: 50.5, marked: 2,
                                      unreal_pnl: 4.25,
                                      unreal_net_avg_bp: 31.0,
                                      unreal_win: 0.5,
                                      expected_over_got: 12.5},
                                nn: {closed: 0, open: 3, marked: 3,
                                     unreal_pnl: -1.75,
                                     unreal_net_avg_bp: -12.0,
                                     no_outcome: 0},
                                all: {closed: 2, open: 6, trades: 8,
                                      no_outcome: 0, hit_rate: 0.5,
                                      hit_basis: "all", hit_n: 2,
                                      net_bp_avg: -0.5, pnl: -0.02,
                                      marked: 5, unreal_pnl: 2.50,
                                      unreal_net_avg_bp: 9.5,
                                      expected_avg: -95.5,
                                      got_avg: 50.5,
                                      expected_over_got: 12.5}},
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
                  // Книга турнира темпов: та же форма, свой горизонт и
                  // свои числа — по ним и проверяется, что переключение
                  // показывает ИМЕННО её, а не главную.
                  books: {
                    // Ситуационная книга: открытая позиция БЕЗ срока
                    // (closes_in_sec нет) и закрытая с причиной выхода.
                    sit: {present: true,
                          // Настройка владельца: порог обещанного
                          // отношения. Отбор и счёт делает сервер, и
                          // ответ обязан нести цену отбора числом.
                          rr_min: 3, rr_cut: 7, rr_unknown: 1,
                          trades_total: 2,
                          // Ситуационная секция одна, а записей две.
                          // Какая отвечает на порог — решает СЕРВЕР, и
                          // говорит это полем; гейт торгуемой книги
                          // едет рядом, потому что у наблюдательной
                          // записи своего гейта нет по построению.
                          source_book: "observation", traded_gate: 4,
                          manifest: {version: 1, situational: true,
                                     horizon_h: null, slots: 6,
                                     sections: 96, symbols: 540,
                                     canary_ic: 0.003,
                                     min_edge_bp: 22, min_rr: 4,
                                     min_disc_bp: 11, arm_band_bp: 11,
                                     max_age_h: 24,
                                     woke_after_hour_sec: 120,
                                     cycle_sec: 261,
                                     steps_sec: {"сведение часа": 180,
                                                 "матрица": 20,
                                                 "обучение": 40,
                                                 "книги": 21},
                                     target: "fwd_4h",
                                     target_rows: 5200,
                                     target_need: 1000,
                                     trained_at:
                                       "2026-08-01T10:00:00+00:00"},
                          accounts: {gbm: {balance: 1001.1,
                                           history: [
                             {hour: "2026-08-03-17", pnl: 0.6,
                              balance: 1000.5},
                             {hour: "2026-08-03-18", pnl: 0.6,
                              balance: 1001.1}]}},
                          // Сводка «обе» приходит с сервера тем же
                          // ядром: страница её показывает, а не
                          // складывает сама — второй счёт разошёлся
                          // бы с первым.
                          trade_stats: {gbm: {closed: 1, open: 1,
                                              no_outcome: 0,
                                              hit_rate: 1.0,
                                              net_bp_avg: 31.0,
                                              pnl: 1.1, trades: 2,
                                              expected_over_got: 1.4},
                                        all: {closed: 2, open: 2,
                                              no_outcome: 0, trades: 4,
                                              hit_rate: 0.5,
                                              net_bp_avg: 12.0,
                                              pnl: 0.7,
                                              expected_over_got: 2.1}},
                          trades: [
                            {arm: "gbm", hour: "2026-08-03-18",
                             sym: "BTCUSDT", side: "long",
                             opened_at: Math.floor(Date.now()/1000)-600,
                             closes_at: null, state: "открыта",
                             expected_bp: 61, mae_bp: -25},
                            {arm: "gbm", hour: "2026-08-03-15",
                             sym: "ETHUSDT", side: "short",
                             opened_at: Math.floor(Date.now()/1000)-9600,
                             state: "закрыта", expected_bp: -80,
                             mae_bp: 30, got_bp: -42, net_bp: 31,
                             pnl: 0.52,
                             exit_reason: "прогноз развернулся"}]},
                    // Книга, ждущая свою цель: выборов нет, и причина
                    // обязана дойти до разметки числом.
                    h24: {present: true,
                          manifest: {version: 1, horizon_h: 24,
                                     sections: 96, symbols: 540,
                                     canary_ic: 0.003,
                                     target: "fwd_24h",
                                     target_rows: 412,
                                     target_need: 1000,
                                     trained_at:
                                       "2026-08-01T10:00:00+00:00"}},
                    h1: {present: true,
                               manifest: {version: 1, horizon_h: 1,
                                          sections: 96, symbols: 540,
                                          canary_ic: 0.003,
                                          target: "fwd_1h",
                                          target_rows: 5200,
                                          target_need: 1000,
                                          trained_at:
                                            "2026-08-01T10:00:00+00:00"},
                               accounts: {gbm: {balance: 1003.57,
                                                history: [
                                  {hour: "2026-08-03-17", pnl: 1.2,
                                   balance: 1002.1},
                                  {hour: "2026-08-03-18", pnl: 1.5,
                                   balance: 1003.57}]}},
                               trade_stats: {gbm: {closed: 4, open: 1,
                                                   no_outcome: 0,
                                                   hit_rate: 0.75,
                                                   net_bp_avg: 12.5,
                                                   pnl: 3.57,
                                                   expected_over_got: 2.1}},
                               trades: [
                                 {arm: "gbm", hour: "2026-08-03-19",
                                  sym: "BTCUSDT", side: "long",
                                  opened_at: Math.floor(Date.now()/1000)-600,
                                  closes_at: Math.floor(Date.now()/1000)+3000,
                                  state: "открыта", expected_bp: 244,
                                  mae_bp: -30, closes_in_sec: 3000}]}}}
             : url.startsWith("/bot-full")
               ? {present: true, age_sec: 42.0, arm: "gbm",
                  capital_usd: 1000.0, balance_usd: 1125.01,
                  cash_usd: 0.0, busy_usd: 1125.01, open: 1, kill: false,
                  check: {ok: true, violations: [], warnings: [],
                          events: 32, open_positions: 1},
                  sverka: {ok: true, at_ms: 1785952800000,
                           note: "расхождений нет"},
                  error: null, server_now: 1785952860,
                  book_hz: "sit",
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
                // Переключатель языка справочника. Дёргается САМА
                // функция страницы, а не подставная кнопка: DOM здесь
                // заглушен, `querySelectorAll` пуст, и проверка «клик
                // по кнопке» шла бы вхолостую — обработчик до неё не
                // доезжает вовсе.
                + "\nglobal.__lang = typeof setLang === 'function' "
                + "? setLang : null;"
                + "\nglobal.__info = typeof showInfo === 'function' "
                + "? showInfo : null;"
                + "\nglobal.__infoClose = typeof closeInfo === "
                + "'function' ? closeInfo : null;"
                + "\nglobal.__mdl = typeof MDL !== 'undefined' ? MDL : null;"
                // Сколько отметок ДОЛИВА попало в карту наведения:
                // слой рисуется на canvas, и единственное свидетельство
                // отрисовки — записи в HIT.
                + "\nglobal.__hitAdds = typeof HIT !== 'undefined' "
                + "? () => HIT.filter(h => h && h.add).length : null;"
                + "\nglobal.__focused = typeof focused === 'function' "
                + "? focused : null;"
                + "\nglobal.__follow = () => typeof follow !== 'undefined' "
                + "? follow : null;"
                + "\nglobal.__table = typeof shownTrades === 'function' "
                + "? shownTrades : (typeof shown === 'function' "
                + "? () => shown().trades : null);"
                // Клик по сделке ядра открывает её на графике: без
                // вызова этот код не исполняется ни разу.
                + "\nglobal.__showTrade = typeof showTrade === 'function' "
                + "? showTrade : null;"
                // Книгу турнира темпов надо ОТКРЫТЬ в проверке, иначе
                // её код ни разу не исполняется — тот же урок, что
                // с вкладкой предпросмотра.
                + "\nglobal.__book = typeof renderModel === 'function' "
                + "&& typeof MDL !== 'undefined' && 'book' in MDL "
                + "? (b) => { MDL.book = b; renderModel(); "
                + "           return document.getElementById('modelbox')"
                + "                  .innerHTML || ''; } : null;"
                // То же для руки: на вкладке «обе» печатается только
                // итог по книге, поэтому ветки отдельных рук (частично
                // переоценённая книга, книга без единого закрытия) без
                // переключения не исполняются ни разу.
                + "\nglobal.__arm = typeof renderModel === 'function' "
                + "&& typeof MDL !== 'undefined' && 'arm' in MDL "
                + "? (a) => { MDL.arm = a; renderModel(); "
                + "           return document.getElementById('modelbox')"
                + "                  .innerHTML || ''; } : null;"
                )();
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
  if (!isTrades && !isBot && !isInfo && !isLeague && !isGloss && !isVol && !isTree
      && !seen.some(u => u.startsWith("/state")))
    bad.push("страница не запросила состояние");
  // Панель сделок боевой модели — на обзоре, под переключателем рук.
  // Проверяется ЧИСЛАМИ подставного ответа: «блок есть» прошло бы и на
  // пустом блоке, а пустой блок неотличим от «сделок пока нет».
  if (!isTrades && !isChart && !isBot && !isInfo && !isLeague
      && !isGloss && !isVol && !isTree) {
    const mb = global.__el ? String(
      global.__el("modelbox").innerHTML || "") : "";
    if (!/model trades|no model trades/.test(mb))
      bad.push("обзор: панель сделок модели не нарисована");
    // Единица показа — ПРОЦЕНТ движения цены (решение владельца).
    // Проверяется по числу: +373 б.п. обязаны показаться как +3.73 %,
    // а не как «373». Проверка на наличие знака «%» прошла бы и на
    // проценте выигрышных сделок, то есть ни о чём.
    if (!/\+3\.73 %/.test(mb))
      bad.push("обзор: сделки показаны не в процентах движения цены");
    // Сводка и кривая счёта: числа из подставного ответа.
    if (!/paper P&amp;L, \$|paper P&L, \$/.test(mb))
      bad.push("обзор: сводка по сделкам не нарисована");
    // На вкладке «обе» — ТОЛЬКО итог по книге. Три одинаковых блока
    // подряд (итог, деревья, сеть) показывали одно и то же двумя
    // способами; разбивка по рукам живёт за соседними кнопками.
    if (!/both arms together/.test(mb))
      bad.push("обзор: итога по книге нет");
    if (/>trees</.test(mb) || /neural<\/b>/.test(mb))
      bad.push("обзор: на вкладке «обе» снова печатается разбивка "
               + "по рукам");
    // Открытые деньги — по ЧИСЛАМ фикстуры: «ячейка есть» прошло бы и
    // на прочерке, а прочерк неотличим от «позиций нет».
    if (!/open P&amp;L, \$ \(mark\)|open P&L, \$ \(mark\)/.test(mb))
      bad.push("обзор: открытых денег нет в сводке");
    if (!/\+2\.5/.test(mb))
      bad.push("обзор: сумма открытых денег не показана числом");
    // И она обязана стоять ОТДЕЛЬНО от факта: сложенные вместе
    // −0.02 и +2.50 дали бы +2.48 — незавершённое, выданное за
    // результат. Обе величины стоят рядом каждая своей ячейкой.
    if (/2\.48/.test(mb))
      bad.push("обзор: открытые деньги сложены с реализованными");
    if (!/-0\.02/.test(mb))
      bad.push("обзор: реализованный итог пропал");
    // Отдельные руки: у деревьев переоценены не все позиции, у сети
    // нет ни одного закрытия. Обе ветки на вкладке «обе» не
    // исполняются вовсе, а владелец смотрит именно по рукам.
    if (global.__arm) {
      const gb = global.__arm("gbm");
      if (!/\+4\.25/.test(gb))
        bad.push("рука: открытых денег нет");
      if (!/2\/3 priced/.test(gb))
        bad.push("рука: непереоценённые позиции молча выпали из суммы");
      const nb = global.__arm("nn");
      if (!/none closed yet/.test(nb))
        bad.push("рука без закрытий: строка состояния пропала");
      if (!/-1\.75/.test(nb))
        bad.push("рука без закрытий: открытых денег не видно, хотя "
                 + "кроме них о книге ничего не известно");
      global.__arm("all");
    }
    if (!/paper equity/.test(mb) || !/<svg/.test(mb))
      bad.push("обзор: кривая бумажного счёта не нарисована");
    if (!/trades-page/.test(mb))
      bad.push("обзор: нет ссылки на полную историю сделок");
    // Турнир темпов: переключатель книг есть, и книга 1 ч показывает
    // СВОИ числа, а не числа главной. Проверяется числами фикстуры:
    // «кнопка есть» прошло бы и на кнопке, которая ничего не меняет.
    if (!/data-book="h1"/.test(mb))
      bad.push("обзор: нет переключателя книг горизонтов");
    if (global.__book) {
      let hb = "";
      try { hb = global.__book("h1"); }
      catch (e) { bad.push("обзор: книга 1 ч упала: " + e.message); }
      // Баланс книги живёт в ПОДПИСИ секции, горизонт — там же.
      const hcap = global.__el
        ? String(global.__el("cap-model").textContent || "") : "";
      if (!/1003\.57/.test(hcap) || !/hold 1 h/.test(hcap))
        bad.push("обзор: книга 1 ч не показывает свой счёт и горизонт");
      if (!/\+2\.44 %/.test(hb))
        bad.push("обзор: сделка книги 1 ч не показана в процентах");
      if (!/hz=h1/.test(hb))
        bad.push("обзор: ссылка на историю книги 1 ч потеряла книгу");
      // Сделка главной книги (+3.73 %) в часовой книге видна быть не
      // может: смесь двух книг и есть отказ, ради которого проверка.
      if (/\+3\.73 %/.test(hb))
        bad.push("обзор: в книге 1 ч видны сделки главной книги");
      // Книга 1 ч свою цель НАБРАЛА — строка ожидания у неё была бы
      // ложной тревогой.
      if (/waiting for its target/.test(hb))
        bad.push("обзор: книга 1 ч ждёт цель, которую уже набрала");
      // Книга, ждущая свою цель, обязана назвать причину ЧИСЛОМ:
      // пустая книга без неё неотличима от сломанной.
      let wb = "";
      try { wb = global.__book("h24"); }
      catch (e) { bad.push("обзор: книга 24 ч упала: " + e.message); }
      if (!/412<\/b> of 1000/.test(wb) || !/fwd_24h/.test(wb))
        bad.push("обзор: ждущая книга не называет причину числом");
      // Ситуационная книга: позиция без срока не рисует NaN, причина
      // выхода закрытой доходит до разметки переводом.
      let sb = "";
      try { sb = global.__book("sit"); }
      catch (e) { bad.push("обзор: ситуационная книга упала: " + e.message); }
      if (/NaN/.test(sb))
        bad.push("обзор: у бессрочной позиции нарисован NaN");
      if (!/forecast flipped/.test(sb))
        bad.push("обзор: причина выхода ситуационной сделки не показана");
      const scap = global.__el
        ? String(global.__el("cap-model").textContent || "") : "";
      if (!/by situation/.test(scap))
        bad.push("обзор: подпись ситуационной книги не называет режим");
      // Книга без срока входит редко ПО ЗАМЫСЛУ, и правило обязано
      // стоять рядом числом: иначе пустая книга неотличима от
      // сломанной. Требуем именно скидку — без неё сканер входил бы
      // в первый же такт после листа, то есть по часам цикла.
      if (!/11 bp/.test(sb) || !/22 bp/.test(sb))
        bad.push("обзор: правило входа ситуационной книги не названо числом");
      // Полоса взведения — часть правила входа, и без неё пачки
      // возвращались четвёртый раз. Читателю страницы её надо видеть
      // числом, а не выводить из отсутствия сделок.
      if (!/in front of us/.test(sb))
        bad.push("обзор: полоса взведения не названа на странице");
      // Переключатель порога и его цена: без подписи «это подмножество»
      // отфильтрованный счёт читается как деньги книги.
      if (!/id="rrf"/.test(sb) || !/≥ 1 : 3\.0/.test(sb))
        bad.push("обзор: переключателя порога RR нет");
      // Порог означает «и выше»: без этого слова его читают как
      // выбор одной полки — вопрос владельца до первого запуска.
      if (!/3 or higher/.test(sb) || !/<b>2<\/b> of 9/.test(sb)
          || !/across both arms/.test(sb) || !/NOT the book/.test(sb))
        bad.push("обзор: цена фильтра и оговорка не показаны");
      // Гейт книги обязан быть назван в самом дилере: без него порог
      // «1 к 3» невозможно соотнести с тем, чем книга торгует.
      if (!/as the book trades/.test(sb))
        bad.push("обзор: дилер не называет порог, которым книга торгует");
      // Столбики руки обязаны складываться в число её сделок: иначе
      // «закрыто 32» читается как вся книга (владелец так и прочёл).
      if (!/>trades</.test(sb))
        bad.push("обзор: у руки не показано число сделок всего");
      // Порог ниже собственного гейта книги показывает ДРУГУЮ запись:
      // торгуемых сделок с таким отношением не существует вовсе. Это
      // обязано быть подписано — молчаливая подмена книги под тем же
      // именем по кривой неотличима.
      if (!/observation record/.test(sb)
          || !/does not trade it/.test(sb.replace(/\s+/g, " ")))
        bad.push("обзор: подмена записи под порогом не подписана");
      // И вкладки «situational · any RR» больше нет: секция одна, а
      // выбор делает дилер. Две вкладки предлагали выбирать книгу
      // вместо вопроса, который на самом деле задают.
      if (/any RR/.test(sb))
        bad.push("обзор: ситуационная книга снова разбита на вкладки");
      // Вкладка «обе» обязана давать ИТОГ, а не две колонки.
      if (!/both arms together/.test(sb))
        bad.push("обзор: общей сводки по книге нет");
      // Запаздывание входа — с разбором по шагам: без него шесть
      // минут выглядят как лень движка, а лечится каждый шаг иначе.
      if (!/120 s/.test(sb) || !/261 s/.test(sb)
          || !/сведение часа 180 s/.test(sb))
        bad.push("обзор: запаздывание входа не разложено по шагам");
      // Возврат на главную: проверки ниже смотрят на её разметку.
      try { global.__book("h4"); }
      catch (e) { bad.push("обзор: возврат на книгу 4 ч упал: " + e.message); }
    }
  }
  // Порог из ссылки обязан доехать до запроса сделок: он выбирает не
  // подмножество, а ЗАПИСЬ, и без него график ищет сделку в книге,
  // где её нет по построению.
  if (/[?&]rr=1\.5/.test(SEARCH || "")) {
    const q = seen.filter(u => u.startsWith("/model_trades"));
    if (!q.some(u => /rr_min=1\.5/.test(u)))
      bad.push("график: порог из ссылки не доехал до запроса: "
               + q.join(" "));
  }
  if (!isTrades && !isBot && !isInfo && !isLeague && !isGloss && !isVol && !isTree
      && !seen.some(u => u.startsWith("/trades")))
    bad.push("страница не запросила историю сделок (/trades)");
  // Страница сделок: кривая счёта, группы величин, сравнение рук.
  // Проверяется ЧИСЛАМИ из подставного ответа — «блок есть» прошло бы
  // и на пустом блоке, а пустой блок неотличим от «данных ещё нет».
  if (isTrades) {
    // Странице сделок нужна сводка — облегчённый ответ её не несёт.
    if (seen.some(u => u.startsWith("/model_trades") && /lite=/.test(u)))
      bad.push("страница сделок ушла на облегчённый ответ без сводки");
    // Переход между страницами статистики книг: ссылки на все три,
    // активная помечена. «Кнопки есть» мало — без `hz` в ссылке все
    // три вели бы на главную книгу, ничем себя не выдав.
    const bb = global.__el ? String(
      global.__el("books").innerHTML || "") : "";
    if (!/hz=h1/.test(bb) || !/hz=h24/.test(bb))
      bad.push("страница сделок: нет ссылок на книги горизонтов");
    // Кнопок столько же, сколько книг в ОБЩЕМ списке. «Ссылки есть»
    // прошло бы и на четырёх из пяти — ровно это владелец и увидел:
    // страница книги в единицах σ открывалась, а вкладки у неё не
    // было, потому что перечень кнопок жил здесь пятым местом.
    const nb = (bb.match(/data-hz="/g) || []).length;
    if (nb !== 5)
      bad.push(`страница сделок: кнопок книг ${nb}, а книг пять`);
    if (!/hz=z/.test(bb))
      bad.push("страница сделок: нет вкладки книги в единицах σ");
    const act = /hz=sit/.test(SEARCH) ? "sit" : "h4";
    if (!new RegExp(`data-hz="${act}" aria-pressed="true"`).test(bb))
      bad.push("страница сделок: активная книга не помечена");
    // Горизонт книги обязан дойти до подписи: страницы двух книг
    // иначе неотличимы. В подставном ответе его нет — подпись обязана
    // честно показать умолчание главной книги.
    const srcp = global.__el ? String(
      global.__el("src").textContent || "") : "";
    if (!/hold 4 h/.test(srcp))
      bad.push("страница сделок: горизонт книги не назван в подписи");
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
    // Баланс в шапке — отдельный элемент, и сломаться ему нечем
    // помешать: сетка счёта его не дублирует кодом, только числом.
    const tb = String(global.__el("topbal").textContent || "");
    if (!/1125\.01/.test(tb)) bad.push("ядро: баланс в шапке не показан");
    if (!/\+12\.50 %/.test(acct)) bad.push("ядро: доля от старта не показана");
    if (!/0 mismatches/.test(acct)) bad.push("ядро: вердикт сверки не показан");
    // Возраст вердикта — рядом с ним. Сверка идёт раз в час, и
    // вердикт прошлого часа обязан выдавать свой возраст, иначе
    // читается как «сейчас»: подставной ответ считан минуту назад.
    if (!/60 s ago/.test(acct))
      bad.push("ядро: возраст вердикта сверки не показан");
    const pos = String(global.__el("pos").innerHTML || "");
    if (!/AAA/.test(pos) || !/0\.62 %/.test(pos))
      bad.push("ядро: открытая позиция без переоценки");
    const cl = String(global.__el("cl").innerHTML || "");
    if (!/CCC/.test(cl) || !/-1\.5/.test(cl))
      bad.push("ядро: закрытая сделка не показана");
    const svp = String(global.__el("sv").textContent || "");
    if (!/Сверка бота/.test(svp))
      bad.push("ядро: отчёт сверки не показан");
    // Клик по сделке открывает её на графике над equity. Проверяется
    // числами: адрес встроенного графика обязан нести монету, руку,
    // час, КНИГУ и embed — без книги график молча показал бы не ту.
    const posHtml = String(global.__el("pos").innerHTML || "");
    if (!/data-pos="gbm:2026-08-05-10:AAAUSDT:long"/.test(posHtml))
      bad.push("ядро: строка позиции не несёт ключ сделки");
    if (global.__showTrade) {
      global.__showTrade("gbm:2026-08-05-10:AAAUSDT:long");
      const src = String(global.__el("tchart").src || "");
      for (const part of ["sym=AAAUSDT", "arm=gbm",
                          "hour=2026-08-05-10", "hz=sit", "embed=1"])
        if (!src.includes(part))
          bad.push("ядро: в адресе графика сделки нет " + part);
      const lab = String(global.__el("tlab").textContent || "");
      if (!/AAA/.test(lab))
        bad.push("ядро: подпись графика не называет сделку");
    } else bad.push("ядро: showTrade не определён");
  }
  // Встроенный режим графика: с embed=1 шапка и сводка спрятаны, без
  // него — на месте. Ошибка в любую сторону — молчаливый отказ показа.
  if (isChart) {
    // Живая позиция обязана быть нарисована СПАНОМ, а не точкой: у
    // ситуационной книги срока нет вовсе, и `closes_at` там пуст.
    // Проверяется отрисованная геометрия (зона наведения сделки), а
    // не входные данные: у схлопнутой в точку сделки она шириной в
    // четырнадцать пикселей и никаких зон нет.
    // Подставная бессрочная сделка — у руки `gbm`; на прогоне с
    // выбранной сетью её и не должно быть видно.
    const mh = /arm=nn/.test(SEARCH) ? null
      : (global.__hit ? global.__hit().filter(h => h.mdl) : []);
    const liveT = mh && mh.find(h => h.mdl && h.mdl.state === "открыта"
                                 && !h.mdl.closes_at);
    if (mh && !liveT)
      bad.push("график: открытая бессрочная сделка не нарисована вовсе");
    else if (liveT && liveT.x1 - liveT.x0 < 40)
      bad.push("график: у открытой сделки только точка входа, спана нет: "
               + Math.round(liveT.x1 - liveT.x0) + " px");
    // Ради чего график и открывают: сделки МОДЕЛИ по этой паре —
    // теми же числами, что в книге. Подставной ответ несёт закрытую
    // сделку руки `gbm` (+0.40 % ход, −0.51 % нетто, −0.85 $) и
    // открытую; обе обязаны стоять в таблице своей строкой.
    const mr = global.__el ? String(global.__el("mrows").innerHTML || "") : "";
    // Ход закрытой сделки одинаков у обеих рук (+0.40 %), а деньги
    // свои: у деревьев −0.85 $, у сети +0.48. Проверяется показанная
    // рука — иначе таблица могла бы печатать чужую и пройти.
    const money = /arm=nn/.test(SEARCH) ? /\+0\.48/ : /-0\.85/;
    if (!/\+0\.40 %/.test(mr) || !money.test(mr))
      bad.push("график: сделки модели по паре не выписаны строками");
    if (!/data-h="2026-08-03-14"/.test(mr))
      bad.push("график: строка сделки не несёт часа для наведения");
    const c4 = global.__el
      ? String(global.__el("cap4").textContent || "") : "";
    if (!/BTC/.test(c4) || !/book|situational/.test(c4))
      bad.push("график: заголовок сделок модели не называет пару и книгу");
    // Объяснение сделки в фокусе — просьба владельца: каким обучением
    // открыта, что двигало прогноз, как поставлены уровни. Проверяются
    // ЧИСЛА из подставной сделки, а не наличие блока: пустой блок
    // неотличим от «данных ещё нет». Ссылка открывает сделку руки nn
    // (`arm=nn`), у неё в фикстуре и лежат why/train_seq.
    if (/arm=nn/.test(SEARCH)) {
      const mn = global.__el
        ? String(global.__el("mnote").innerHTML || "") : "";
      if (!/training #124/.test(mn))
        bad.push("график: объяснение не называет номер обучения");
      if (!/ret_7 \+0\.45 %/.test(mn))
        bad.push("график: вклад признаков не показан числом");
      // Вид ситуации — просьба владельца: выедение стакана,
      // ликвидации, зажим… Проверяются подпись семейства с долей И
      // оговорка, что это чтение вкладов: без неё семейство читалось
      // бы как выбранная стратегия, которой у модели нет.
      if (!/liquidations 42 %/.test(mn)
          || !/absorption\) 25 %/.test(mn))
        bad.push("график: вид ситуации не назван с долями");
      if (!/not a\s+hand-picked\s+strategy/
            .test(mn.replace(/\s+/g, " ")))
        bad.push("график: подпись не говорит, что это чтение вкладов");
      if (!/20 % of cases/.test(mn))
        bad.push("график: правило стопа не названо в объяснении");
      if (!/sheet promised/.test(mn) || !/in\s+front of us/
            .test(mn.replace(/\s+/g, " ")))
        bad.push("график: стратегия входа не названа в объяснении");
    }

    // Вертикаль цены: тянуть вверх-вниз, а не только в сторону. Жест
    // воспроизводится настоящими обработчиками страницы, а результат
    // читается по ПОДПИСЯМ шкалы — «функция вызвалась» прошло бы и на
    // графике, который не сдвинулся.
    const cv = global.__el ? global.__el("px") : null;
    const ev = cv && cv._ev;
    const fire = (t, e) => (ev[t] || []).forEach(f => f(e));
    if (!ev || !ev.pointerdown || !ev.pointermove) {
      bad.push("график: жесты не привязаны к холсту");
    } else {
      // Снимок шкалы ДО жеста: перерисовываем сдвигом на ноль, чтобы
      // сравнивать одно и то же — подписи одной и той же отрисовки.
      global.__texts = [];
      fire("pointerdown", {clientX: 400, clientY: 200, pointerId: 1,
                           pointerType: "mouse"});
      fire("pointermove", {clientX: 400, clientY: 200, pointerId: 1});
      const before = global.__texts.join("|");
      global.__texts = [];
      fire("pointermove", {clientX: 400, clientY: 320, pointerId: 1});
      const after = global.__texts.join("|");
      fire("pointerup", {clientX: 400, clientY: 320, pointerId: 1});
      if (!before || before === after)
        bad.push("график: вертикальный сдвиг не меняет шкалу цены");
      global.__texts = [];
      if (ev.dblclick) fire("dblclick", {});
      const reset = global.__texts.join("|");
      if (!reset)
        bad.push("график: двойной щелчок ничего не перерисовывает");
      else if (reset !== before)
        bad.push("график: двойной щелчок не вернул автоматический "
                 + "масштаб цены");
    }
  }

  if (isLeague) {
    const bx = global.__el
      ? String(global.__el("box").innerHTML || "") : "";
    // Числа стаба: лидер группы помечен, деньги и счётчики на месте,
    // топ несёт ссылку на разбор сделки.
    if (!/&#9733;|\u2605/.test(bx) && bx.indexOf("\u2605") < 0
        && bx.indexOf("★") < 0)
      bad.push("лига: лидер группы не помечен");
    if (!/\+4\.1/.test(bx) || !/-3/.test(bx))
      bad.push("лига: деньги групп не показаны");
    if (!/liquidations/.test(bx))
      bad.push("лига: ситуация не названа человеческим именем");
    if (!/AAA/.test(bx) || !/\+8\.00/.test(bx))
      bad.push("лига: топ сделок не показан");
    if (!/trade-info/.test(bx))
      bad.push("лига: из топа нет ссылки на разбор сделки");
    const nt = global.__el
      ? String(global.__el("note").innerHTML || "") : "";
    if (!/observation record is excluded/.test(nt)
        || !/noise/.test(nt))
      bad.push("лига: оговорки честности потеряны");
    if (!seen.some(u => u.startsWith("/league")))
      bad.push("лига: данные не запрошены");
    // Сломанная книга видна на странице, и сказано, что итоги неполны.
    if (!/model_h24: ValueError: boom/.test(bx)
        || !/NOT the whole story/.test(bx))
      bad.push("лига: ошибка сборки книги не показана");
    // Каждая таблица — в прокрутке: панель узкая, и без обёртки
    // правые колонки СРЕЗАЛИСЬ (владелец видел «avg net» без
    // процента и не видел денег вовсе). Четыре панели групп плюс два
    // топа — шесть обёрток на подставных данных, где все группы полны.
    const nScroll = (bx.match(/class="scroll"/g) || []).length;
    if (nScroll < 6)
      bad.push("лига: таблицы групп не в прокрутке, колонки срезаются"
               + ` (обёрток ${nScroll} из 6)`);
  }

  // Дерево моделей — родовое дерево: по умолчанию узел несёт ТОЛЬКО
  // имя и главную статистику, проза открывается кнопкой «i» (просьба
  // владельца). Проверяется числами и в обе стороны: статистика видна
  // без нажатия, описание БЕЗ нажатия не видно.
  if (isTree) {
    if (!seen.some(u => u.startsWith("/model_tree")))
      bad.push("дерево: страница не запросила /model_tree");
    const flat = s => String(s || "").replace(/\s+/g, " ");
    const bx = flat(global.__el ? global.__el("box").innerHTML : "");
    const roots = (bx.match(/data-root="/g) || []).length;
    if (roots !== 2)
      bad.push(`дерево: корней ${roots}, а рук две`);
    // Узлов на руку: корень + три книги + лист турнира = 5.
    const nodes = (bx.match(/data-key="/g) || []).length;
    if (nodes !== 10)
      bad.push(`дерево: узлов ${nodes}, а должно быть 10`);
    const ibtns = (bx.match(/class="ibtn"/g) || []).length;
    if (ibtns !== 10)
      bad.push(`дерево: кнопок «i» ${ibtns} на 10 узлов`);
    // Статистика — видна по умолчанию, это и есть лицо узла.
    if (!/\+12\.34 \$/.test(bx) || !/-3\.21 \$/.test(bx))
      bad.push("дерево: деньги веток не из ответа");
    if (!/e22_rr1\.5_sm_t1_a24/.test(bx))
      bad.push("дерево: действующий вариант турнира не в узле");
    if (!/not started/.test(bx))
      bad.push("дерево: отсутствующая на сервере книга не помечена");
    // Проза по умолчанию СПРЯТАНА: если описание видно без «i», вся
    // просьба владельца не выполнена.
    if (/Reads thresholds and break points/.test(bx)
        || /Does picking the moment/.test(bx)
        || /The picking rule is judged/.test(bx))
      bad.push("дерево: описание видно без нажатия «i»");
    const md0 = flat(global.__el ? global.__el("modal").innerHTML : "");
    if (md0 !== "")
      bad.push("дерево: карточка «i» открыта без нажатия");
    if (!global.__info || !global.__infoClose) {
      bad.push("дерево: функции карточки «i» не существуют");
    } else {
      // Карточка книги: проза, правила из манифеста, деньги руки и
      // ссылка на историю С КНИГОЙ в адресе.
      global.__info("sit:gbm");
      let md = flat(global.__el("modal").innerHTML);
      if (!/Does picking the moment add anything/.test(md))
        bad.push("дерево: проза ветки не открылась по «i»");
      if (!/gate 22 bp/.test(md))
        bad.push("дерево: правила ветки не в карточке");
      if (!/closed <b>3<\/b>/.test(md) || !/\+4\.10 \$/.test(md))
        bad.push("дерево: деньги руки не в карточке");
      if (!/href="\/trades-page\?k=xxx&hz=sit"/.test(md))
        bad.push("дерево: ссылка истории без книги или ключа");
      // Карточка турнира: статус целиком.
      global.__info("tourney:gbm");
      md = flat(global.__el("modal").innerHTML);
      if (!/The picking rule is judged/.test(md))
        bad.push("дерево: проза турнира не открылась");
      if (!/диагностика, не вердикт/.test(md))
        bad.push("дерево: статус турнира не в карточке");
      // Язык переключается НАСТОЯЩЕЙ функцией страницы, и открытая
      // карточка обязана перерисоваться на новом языке.
      if (global.__lang) {
        global.__lang("ru");
        md = flat(global.__el("modal").innerHTML);
        if (!/Судится правило выбора/.test(md))
          bad.push("дерево: карточка не перешла на русский");
        global.__info("root:gbm");
        md = flat(global.__el("modal").innerHTML);
        if (!/Читает пороги и изломы/.test(md))
          bad.push("дерево: русская проза корня не показана");
        global.__lang("en");
      } else {
        bad.push("дерево: переключателя языка нет");
      }
      // Крестик закрывает: карточка пустеет, дерево остаётся.
      global.__infoClose();
      if (flat(global.__el("modal").innerHTML) !== "")
        bad.push("дерево: карточка «i» не закрывается");
    }
  }

  // Меню страниц — на каждой самостоятельной странице, и проверяется
  // ЧИСЛАМИ: пять пунктов, ключ в каждой ссылке, текущая помечена.
  // «Блок есть» прошло бы и на пустом меню, а пустое меню неотличимо
  // от «страницы кончились».
  if (!isChart && !isInfo) {
    const nv = global.__el ? global.__el("nav") : null;
    const nh = nv ? String(nv.innerHTML || "") : "";
    const links = (nh.match(/class="navlink/g) || []).length;
    if (links !== 7)
      bad.push(`меню: пунктов ${links}, а страниц семь`);
    if (!/href="\/league-page\?k=xxx"/.test(nh)
        || !/href="\/glossary-page\?k=xxx"/.test(nh)
        || !/href="\/tree-page\?k=xxx"/.test(nh))
      bad.push("меню: ссылка без ключа или страница потеряна");
    if (!/aria-current="page"/.test(nh))
      bad.push("меню: текущая страница не помечена");
  }

  if (isVol && /voldown=1/.test(SEARCH)) {
    // Медленный счёт не есть отсутствие данных. Первый обход суток
    // отваливается по времени, и страница писала «делить нечего» —
    // владелец прочёл это как пустую страницу.
    const intro = String(global.__el
      ? global.__el("intro").innerHTML : "").replace(/\s+/g, " ");
    if (!/No answer from the collector/.test(intro))
      bad.push("волатильность: молчание сборщика не названо");
    if (/Nothing to split yet/.test(intro))
      bad.push("волатильность: медленный счёт выдан за отсутствие "
               + "данных");
    if (!/takes about a minute/.test(intro))
      bad.push("волатильность: не сказано, сколько ждать");
  } else if (isVol) {
    const flat = s => String(s || "").replace(/\s+/g, " ");
    const bx = flat(global.__el ? global.__el("box").innerHTML : "");
    const intro = flat(global.__el
      ? global.__el("intro").innerHTML : "");
    const cur = flat(global.__el ? global.__el("curve").innerHTML : "");
    // Меряемая величина названа, и названа честно: почему размах, а не
    // доходность часа. Без этого абзаца число не читается вовсе.
    if (!/median hourly range/.test(intro))
      bad.push("волатильность: мера не названа");
    if (!/fell and came back is calm by return/.test(intro))
      bad.push("волатильность: не сказано, почему размах, а не "
               + "доходность");
    // Час ВХОДА против часа удержания — разница, из которой только
    // первая может стать правилом.
    if (!/opened<\/b> in/.test(intro) || !/never become a rule/.test(intro))
      bad.push("волатильность: не разделены час входа и час удержания");
    // Границы корзин объявлены до результата, и это сказано числом.
    if (!/22 \/ 61 bp/.test(intro))
      bad.push("волатильность: границы корзин не названы числом");
    if (!/thresholds picked after seeing results/.test(intro))
      bad.push("волатильность: не сказано, что пороги не подбирались "
               + "под результат");
    // Сделки без сводки часа не растворяются молча.
    if (!/3 closed trades had no summary/.test(intro))
      bad.push("волатильность: выпавшие сделки не посчитаны");
    // Разбивка: числа фикстуры по корзинам, обе руки, дни рядом.
    if (!/quiet/.test(bx) || !/loud/.test(bx))
      bad.push("волатильность: разбивки по режиму нет");
    if (!/-9\.4/.test(bx) || !/\+4\.1/.test(bx))
      bad.push("волатильность: деньги корзин не показаны");
    if (!/trees \(ML\)/.test(bx))
      bad.push("волатильность: разбивки по рукам нет");
    // Число разных ДАТ обязано стоять рядом с числом сделок: три
    // сделки с двух дней — это два дня.
    if (!/<th>days<\/th>/.test(bx))
      bad.push("волатильность: числа разных дат нет в таблице");
    if (!/class="thin"/.test(bx))
      bad.push("волатильность: тонкая корзина не помечена анекдотом");
    if (!/read them as anecdotes/.test(bx))
      bad.push("волатильность: не сказано, как читать тонкие строки");
    if (!/<svg/.test(cur) || !/bucket edges/.test(cur))
      bad.push("волатильность: кривой режима рынка нет");
    if (!seen.some(u => u.startsWith("/volatility")))
      bad.push("волатильность: данные не запрошены");
    // Отбирает ли модель волатильные имена — числами фикстуры.
    if (!/does the model pick the movers/.test(bx))
      bad.push("волатильность: замера отбора нет");
    if (!/1\.42/.test(bx) || !/73 %/.test(bx))
      bad.push("волатильность: перекос отбора не показан числом");
    if (!/targets are raw basis points/.test(bx))
      bad.push("волатильность: перекос напечатан, но не назван");
    if (!/not a proof of cause/.test(bx))
      bad.push("волатильность: отпечаток выдан за причину");
  }

  if (isGloss) {
    // Пробелы схлопываются: текст страницы переносится по строкам
    // исходника, и фраза «reading of the forecast» физически стоит на
    // двух — проверка на дословное совпадение падала бы на вёрстке, а
    // не на смысле.
    const flat = s => String(s || "").replace(/\s+/g, " ");
    const bx = flat(global.__el
      ? global.__el("box").innerHTML : "");
    const intro = flat(global.__el
      ? global.__el("intro").innerHTML : "");
    // Главная честность страницы обязана стоять на ней, а не в моей
    // голове: без неё список семейств читается как набор правил.
    if (!/no separate strategies/.test(intro))
      bad.push("справочник: не сказано, что стратегий у модели нет");
    if (!/reading of the forecast, not a rule/.test(intro))
      bad.push("справочник: имя ситуации выдано за правило");
    if (!/top ten per target/.test(intro) || !/20 %/.test(intro))
      bad.push("справочник: неполнота весов не названа числом");
    // Числа стаба, а не «блок есть»: пустая карточка неотличима от
    // «данных ещё нет».
    if (!/Absorption — the book being eaten/.test(bx))
      bad.push("справочник: семейство не названо");
    if (!/putting size back at the same price/.test(bx))
      bad.push("справочник: объяснение простыми словами потеряно");
    if (!/aggressive volume against displayed depth/.test(bx))
      bad.push("справочник: не сказано, что именно мерится");
    if (!/carried no direction at all/.test(bx))
      bad.push("справочник: оговорка честности потеряна");
    // Признак переведён ОБЩИМ словарём — тем же, что у разбора сделки.
    if (!/sellers eating through the shown bids/.test(bx))
      bad.push("справочник: признак не переведён на человеческий");
    if (!/12\.0 %/.test(bx))
      bad.push("справочник: вес признака не показан");
    // Вес неизвестен — прочерк, а НЕ ноль: ноль читался бы как
    // «модель им не пользуется».
    if (/0\.0 %/.test(bx))
      bad.push("справочник: неизвестный вес показан нулём");
    if (!/named in 5 closed trades/.test(bx))
      bad.push("справочник: сделки по семейству не посчитаны");
    if (!seen.some(u => u.startsWith("/glossary")))
      bad.push("справочник: данные не запрошены");
    // Переключатель языка. Проверяется не «кнопка есть», а то, что
    // страница ПЕРЕСОБРАЛАСЬ по-русски: текст семейства, подписи самой
    // страницы, перевод признака и — главное — та же оговорка про
    // отсутствие стратегий. Потерять её в переводе значило бы соврать
    // одному из двух читателей.
    const before = bx;
    const nq = calls;
    if (!/data-l="ru"/.test(String(global.__el
          ? global.__el("lang").innerHTML : "")))
      bad.push("справочник: кнопки языка нет на странице");
    if (!global.__lang) {
      bad.push("справочник: переключателя языка нет");
    } else {
      global.__lang("ru");
      const rbx = flat(global.__el ? global.__el("box").innerHTML : "");
      const rin = flat(global.__el
        ? global.__el("intro").innerHTML : "");
      if (rbx === before)
        bad.push("справочник: переключение языка ничего не изменило");
      if (!/Отдельных стратегий у модели нет/.test(rin))
        bad.push("справочник по-русски: оговорка про стратегии "
                 + "потеряна в переводе");
      if (!/чтение прогноза, а не правило/.test(rin))
        bad.push("справочник по-русски: имя ситуации выдано за правило");
      if (!/топ-10 на цель/.test(rin) || !/20 %/.test(rin))
        bad.push("справочник по-русски: неполнота весов не названа");
      if (!/Выедение стакана/.test(rbx))
        bad.push("справочник по-русски: семейство не переведено");
      if (!/доставляет объём на ту же цену/.test(rbx))
        bad.push("справочник по-русски: объяснение не переведено");
      if (!/Что именно мерится/.test(rbx))
        bad.push("справочник по-русски: подписи страницы остались "
                 + "английскими");
      if (!/продавцы выедают показанные биды/.test(rbx))
        bad.push("справочник по-русски: признак не переведён");
      if (!/признаков: 1/.test(rbx))
        bad.push("справочник по-русски: счётчики не переведены");
      // Оба языка приходят одним ответом: смена языка не имеет права
      // ходить на сервер — на потерянной связи страница погасла бы.
      if (calls !== nq)
        bad.push("справочник: смена языка полезла на сервер");
      // Меню переезжает на русский вместе со страницей.
      const nh2 = global.__el
        ? String(global.__el("nav").innerHTML || "") : "";
      if (!/справочник/.test(nh2))
        bad.push("справочник: меню осталось на другом языке");
    }
  }

  if (isInfo) {
    const wb = global.__el
      ? String(global.__el("whybox").innerHTML || "") : "";
    const sub = global.__el
      ? String(global.__el("sub").textContent || "") : "";
    // Числа фикстуры, а не «блок есть»: пустой разбор неотличим от
    // «данных ещё нет».
    if (!/training #124/.test(sub))
      bad.push("разбор: номер обучения не назван");
    if (!/liquidations \(42 %\)/.test(wb))
      bad.push("разбор: вид ситуации не назван долей");
    if (!/eating through the shown bids/.test(wb))
      bad.push("разбор: признак не переведён на человеческий");
    if (!/in only\s+<b>20 %<\/b> of cases/.test(wb.replace(/\s+/g, " ")))
      bad.push("разбор: правило стопа не объяснено");
    if (!/does <b>not<\/b> guarantee/.test(wb))
      bad.push("разбор: честность про разрывы потеряна");
    if (!/walked\s+<b>\+0\.30 %<\/b> against/.test(
          wb.replace(/\s+/g, " ")))
      bad.push("разбор: скидка входа не посчитана из чисел");
    if (!seen.some(u => u.startsWith("/model_trades")))
      bad.push("разбор: сделки не запрошены у сервера");
  }

  if (isChart && /paperoff=1/.test(SEARCH)) {
    // Выключенный детектор обязан называть себя выключенным. «Ждёт
    // условий» на выключенном наблюдении — ложь, и владелец прочёл её
    // как «сделки не записываются».
    const pp = global.__el ? global.__el("ppanel") : null;
    const dsp = pp && pp.style ? String(pp.style.display || "") : "";
    if (dsp !== "none")
      bad.push("график: пустая таблица чужого детектора осталась на виду");
    const mn = global.__el ? String(global.__el("mnote").innerHTML || "") : "";
    if (!/--paper/.test(mn) || !/is off/.test(mn))
      bad.push("график: причина спрятанной таблицы не названа");
  }

  if (isChart && !/paperoff=1/.test(SEARCH)) {
    // Слитая позиция: график рисует ОДНУ сделку модели вместо лотов,
    // и точка долива попадает в карту наведения. «Слой нарисовался»
    // прошло бы и на четырёх наложенных прямоугольниках — проверяем
    // ЧИСЛОМ: одна позиция и одна отметка долива.
    // Долив проверяем там, где рука совпадает со слитой позицией
    // фикстуры (gbm). На странице по ссылке рука другая, и доливов у
    // неё нет ПО СОСТАВУ — требовать их там значило бы проверять
    // фикстуру, а не страницу.
    const mdl = global.__mdl;
    if (mdl && mdl.arm === "gbm") {
      const hits = (global.__hitAdds ? global.__hitAdds() : null);
      if (hits !== null && hits < 1)
        bad.push("график: долив не нарисован точкой на позиции");
      // Таблица под графиком обязана говорить о позиции то же, что
      // картинка: линия входа стоит на СРЕДНЕЙ цене (64750), а не на
      // цене первого лота (64700). Разойдись они — владелец увидел бы
      // на графике одно, а в строке другое, и оба выглядели бы верно.
      const mr = global.__el ? String(
        global.__el("mrows").innerHTML || "") : "";
      if (mr && !/64750/.test(mr))
        bad.push("график: в таблице не средняя цена слитой позиции");
      if (mr && !/avg &times;2|avg ×2/.test(mr))
        bad.push("график: слитая позиция не названа слитой");
    }
  }

  if (isChart) {
    const emb = /embed=1/.test(SEARCH);
    const nav = global.__el ? global.__el("topnav") : null;
    const disp = nav && nav.style ? String(nav.style.display || "") : "";
    if (emb && disp !== "none")
      bad.push("график: embed не спрятал шапку");
    if (!emb && disp === "none")
      bad.push("график: шапка спрятана без embed");
  }

  // Панель исполнительного ядра — только на обзоре. Проверяется
  // ЧИСЛАМИ подставного ответа: «блок есть» прошло бы и на пустом
  // блоке, а пустой блок неотличим от «ядро не запущено».
  if (!isTrades && !isChart && !isBot && !isInfo && !isLeague
      && !isGloss && !isVol && !isTree) {
    const bb = global.__el ? String(
      global.__el("botbox").innerHTML || "") : "";
    if (!/990\.08/.test(bb))
      bad.push("панель ядра не показала баланс тени");
    if (!/0 mismatches/.test(bb))
      bad.push("вердикт сверки не показан");
    if (!/застряла/.test(bb))
      bad.push("предупреждения сторожа не показаны");
    if (/STATUS SILENT/.test(bb))
      bad.push("свежий статус назван молчащим");
    const cap = global.__el ? String(
      global.__el("cap-bot").textContent || "") : "";
    if (!/42 s/.test(cap))
      bad.push("возраст статуса ядра не показан");
  }

  // График обязан достроить историю свечей с диска: без неё он
  // обрывается там, где кончается память сборщика, и прошлые сделки
  // смотреть не на чем.
  if (isChart && !seen.some(u => u.startsWith("/candles")))
    bad.push("график не запросил историю свечей (/candles)");
  // Выбор монеты — группами по секторам, а не стеной из пятисот
  // кнопок. Проверяется содержимым подставного ответа: имя группы и
  // монета внутри неё обязаны дойти до разметки.
  if (isChart) {
    if (!seen.some(u => u.startsWith("/groups")))
      bad.push("график: группы монет не запрошены");
    const gp = String(global.__el("groups").innerHTML || "");
    if (!/Memes/.test(gp) || !/DOGE/.test(gp))
      bad.push("график: группы монет не построены");
  }
  // Сделки модели на графике. Это не украшение: страницу открывают
  // ссылкой из таблицы ради ответа «а что было с ценой», и слой,
  // который молча не рисуется, неотличим от «сделок по этой монете нет».
  if (isChart) {
    if (!seen.some(u => u.startsWith("/model_trades")))
      bad.push("график не запросил сделок модели");
    // Графику нужны строки, а не сводки: полный расчёт занимал секунды
    // на каждую смену монеты. Страница сделок, наоборот, обязана
    // остаться на полном ответе — её проверки по числам сводки это
    // и держат.
    if (seen.some(u => u.startsWith("/model_trades") && !/lite=1/.test(u)))
      bad.push("график тянет сделки модели полным ответом");
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
      // Точки долива несут ту же сделку (`mdl`), но выхода у них нет
      // по построению — это отметки внутри позиции. Спрашивать выход
      // надо у записи ПОЗИЦИИ, иначе проверка падала бы на слитой
      // сделке, у которой всё нарисовано верно.
      const cl = drawn.find(h => !h.add && h.mdl.state === "закрыта");
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
    // Книга без срока: первым столбцом идёт ВХОД, час листа уезжает
    // вторым. Вход 19:00 UTC — это 21:00 в Вене, час листа 18 — 20:00,
    // так что перестановка видна числами. Без неё сделка сканера,
    // открытая в 18:16, стоит под «17:00» и на телефоне (второй
    // столбец скрыт) читается как старая часовая.
    if (/hz=sit/.test(SEARCH)) {
      const h1 = String((global.__el("thw") || {}).textContent || "");
      const h2 = String((global.__el("thw2") || {}).textContent || "");
      if (h1 !== "entered" || h2 !== "sheet hour")
        bad.push(`книга без срока: заголовки не переставлены (${h1}/${h2})`);
      const cells = html.split("<td").slice(1, 3).join("|");
      if (!/21:00/.test(cells) || !/20:00/.test(cells))
        bad.push("вход и час листа не различимы в строке: " + cells);
    }
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
  } else if (isBot || isInfo || isLeague || isGloss || isVol
             || isTree) {
    // У страницы ядра и у разбора сделки нет ни пересчёта, ни
    // детекторных сделок — их проверки выше, своими числами.
  } else if (/paperoff=1/.test(SEARCH)) {
    // Пересчитывать нечего: бумажных сделок не ведут. Проверки
    // пересчёта здесь неприменимы — их место занимает проверка, что
    // страница НАЗЫВАЕТ выключенное выключенным (выше).
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
  // Выход ЯВНЫЙ: страница вправе назначить повтор по таймеру (так
  // делает волатильность, когда сборщик молчит), и незавершённый
  // таймер держал бы node живым вечно. Проверка, висящая на исправной
  // странице, неотличима от проверки, поймавшей зависание.
  process.exit(0);
})();
