// Прогон логики страницы без браузера: canvas и DOM подменены
// заглушками, всё остальное — настоящий код страницы.
//
// Страница, которая молча ничего не нарисовала, выглядит как «эффекта
// нет», а не как ошибка. Проверка синтаксиса этого не ловит: падает всё
// на первом же вызове во время работы. Требует node; питоновские тесты
// остаются главными и без него.
//
//     node research/t3_brackets/headless_check.js out/T3-chart.html
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const js = src.match(/<script>\n([\s\S]*)<\/script>/)[1];
const data = src.match(/<script id="data"[^>]*>([\s\S]*?)<\/script>/)[1];
const ctx = new Proxy({}, { get: (t, k) => {
  if (k === "canvas") return { clientWidth: 900 };
  if (k === "measureText") return () => ({ width: 40 });
  return () => undefined;
}, set: () => true });
const mkEl = () => new Proxy({
  style: {}, dataset: {}, clientWidth: 900, clientHeight: 380,
  offsetWidth: 200, offsetHeight: 120, textContent: "", innerHTML: "",
  getContext: () => ctx, getBoundingClientRect: () => ({ left: 0, top: 0 }),
  setPointerCapture: () => {}, addEventListener: () => {},
  appendChild: () => {}, querySelector: () => mkEl(), querySelectorAll: () => [],
  scrollIntoView: () => {},
}, { get: (t, k) => (k in t ? t[k] : () => undefined),
     set: (t, k, v) => ((t[k] = v), true) });
global.document = {
  documentElement: mkEl(), getElementById: () => mkEl(),
  querySelector: () => mkEl(), querySelectorAll: () => [],
  createElement: () => mkEl(), addEventListener: () => {},
};
global.window = { devicePixelRatio: 2, addEventListener: () => {} };
global.getComputedStyle = () => ({ getPropertyValue: () => "#000000" });
global.MutationObserver = class { observe() {} };
global.requestAnimationFrame = f => f();
new Function(js.replace(
  'JSON.parse(document.getElementById("data").textContent)', data))();
console.log("логика страницы отработала без ошибок");
