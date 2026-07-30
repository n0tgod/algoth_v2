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
//     node research/b1_book/headless_check.js <файл-со-страницей>
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const js = src.match(/<script>\n([\s\S]*)<\/script>/)[1];

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
global.document = {
  documentElement: mkEl(), getElementById: () => mkEl(),
  querySelector: () => mkEl(), querySelectorAll: () => [],
  createElement: () => mkEl(), addEventListener: () => {},
};
global.location = { search: "?k=xxx&sym=BTCUSDT" };
global.history = { replaceState: () => {} };
global.window = { devicePixelRatio: 2, addEventListener: () => {},
                  history: global.history, location: global.location };
global.getComputedStyle = () => ({ getPropertyValue: () => "#000000" });
global.devicePixelRatio = 2;
global.setInterval = () => 0;          // такт даём сами, вручную
global.requestAnimationFrame = f => f();

const T0 = 1785440000;
const trade = (i, closed) => ({
  id: "BTCUSDT-" + i, t: T0 - 600 + i, sym: "BTCUSDT", side: -1, long: true,
  entry: 64700, stop: 64600, target: 64900, level: 64700, kind: "полка",
  stop_bp: 15.5, rr: 2.0, held: 120,
  state: closed ? "цель" : "открыта",
  pnl_bp: closed ? 20.5 : 0.0, r: closed ? 1.3 : 0.0,
  exit: closed ? 64900 : null, closed_at: closed ? T0 - 400 + i : null,
});
const candles = n => Array.from({length: n}, (_, i) =>
  [T0 - (n - i) * 60, 64700, 64720, 64680, 64710, 1234.5]);
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
const hist = {sym: "BTCUSDT", symbols: ["BTCUSDT"],
              trades: [trade(1, true), trade(2, true)],
              equity: [[T0 - 300, 20.5, 1.3], [T0 - 200, 41.0, 2.6]],
              stats: {trades: 2, win_rate: 1.0, break_even: 0.31,
                      expectancy_bp: 20.5, expectancy_r: 1.3, median_bp: 20.5,
                      median_r: 1.3, stop_bp_median: 15.5, rr_median: 2.0,
                      held_median_sec: 120, share_target: 1.0, share_stop: 0.0,
                      share_time: 0.0, cut_by_restart: 1},
              all_stats: null, all_equity: [], all_trades: 2};

let full = true, calls = 0;
global.fetch = async (url) => {
  calls++;
  const body = url.startsWith("/trades") ? hist : state(full, 60);
  return {ok: true, json: async () => body};
};

process.on("unhandledRejection", e => {
  console.error("ПАДЕНИЕ в обработчике ответа:", e);
  process.exit(1);
});

// Точка такта живёт внутри области видимости страницы, поэтому её надо
// вынести наружу явно — иначе проверялся бы только запуск.
new Function(js + "\nglobal.__step = typeof tick !== 'undefined' "
                + "? tick : pull;\nglobal.__st = ST;")();
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
  const buf = st.mid && st.mid.length ? st.mid : st.cand;
  if (!buf || buf.length < 50)
    bad.push(`склейка потеряла историю: осталось ${buf ? buf.length : "—"}`);
  if (st.cand && st.cand.length && st.cand.length < 50)
    bad.push(`свечи склеились неверно: ${st.cand.length}`);
  if (bad.length) { console.error("ПАДЕНИЕ: " + bad.join("; "));
                    process.exit(1); }
  console.log(`логика страницы отработала без ошибок, запросов ${calls}, `
    + `середина ${st.mid ? st.mid.length : "—"}, свечей ${
        st.cand ? st.cand.length : "—"}`);
})();
