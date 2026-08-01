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
const isChart = /id="px"/.test(src);

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

const T0 = 1785440000;
const trade = (i, closed) => ({
  id: "BTCUSDT-" + i, t: T0 - 600 + i, sym: "BTCUSDT", side: -1, long: true,
  entry: 64700, stop: 64600, target: 64900, level: 64700, kind: "полка",
  stop_bp: 15.5, rr: 2.0, held: 120, stop_by: "экстремум",
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
  const body = url.startsWith("/trades") ? hist
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
                  ic: [{target: "fwd_4h", median_ic: 0.021, sections: 24}]}
             : url.startsWith("/candles")
               ? {sym: "BTCUSDT", candles: candles(1440), hours: 24}
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
                + "? tick : pull;\nglobal.__st = ST;"
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
                + "\nglobal.__table = typeof shownTrades === 'function' "
                + "? shownTrades : (typeof shown === 'function' "
                + "? () => shown().trades : null);")();
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
  if (!seen.some(u => u.startsWith("/state")))
    bad.push("страница не запросила состояние");
  if (!seen.some(u => u.startsWith("/trades")))
    bad.push("страница не запросила историю сделок (/trades)");
  // График обязан достроить историю свечей с диска: без неё он
  // обрывается там, где кончается память сборщика, и прошлые сделки
  // смотреть не на чем.
  if (isChart && !seen.some(u => u.startsWith("/candles")))
    bad.push("график не запросил историю свечей (/candles)");
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
  const buf = st.mid && st.mid.length ? st.mid : st.cand;
  if (!buf || buf.length < 50)
    bad.push(`склейка потеряла историю: осталось ${buf ? buf.length : "—"}`);
  if (st.cand && st.cand.length && st.cand.length < 50)
    bad.push(`свечи склеились неверно: ${st.cand.length}`);
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
  if (!global.__rec || !global.__table) {
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
    if (isChart) {
      const drawn = global.__hit ? global.__hit() : null;
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
      if (!/посчитан в/.test(note))
        bad.push("возраст пересчёта не показан: " + JSON.stringify(note));
      if (!/\b\d+ мин назад/.test(note))
        bad.push("возраст не назван числом минут: " + JSON.stringify(note));
      if (!/Живых сделок после этого момента/.test(note))
        bad.push("новые живые сделки после пересчёта не названы: "
                 + JSON.stringify(note));
    }
  }
  if (bad.length) { console.error("ПАДЕНИЕ: " + bad.join("; "));
                    process.exit(1); }
  console.log(`логика страницы отработала без ошибок, запросов ${calls}, `
    + `середина ${st.mid ? st.mid.length : "—"}, свечей ${
        st.cand ? st.cand.length : "—"}`);
})();
