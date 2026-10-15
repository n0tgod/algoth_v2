// Кабинет Algoth (спека 16 L4). Все числа и слова — ответы API; страница
// ничего не считает, только печатает и шлёт команды. Токен сессии —
// в localStorage (срок держит сервер, 30 суток).
const Site = (() => {
  const API = "/api/v1/";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const tok = () => localStorage.getItem("algoth.session") || "";
  const money = (v) => v == null ? "—" : (v >= 0 ? "+" : "−") + "$" + Math.abs(v).toFixed(2);
  const amt = (v) => v == null ? "—" : "$" + Number(v).toLocaleString("en-US", {maximumFractionDigits: 2});
  const when = (t) => t ? new Date(t * 1000).toLocaleString() : "—";

  async function api(method, path, body) {
    const h = {"Content-Type": "application/json"};
    if (tok()) h.Authorization = "Bearer " + tok();
    const r = await fetch(API + path, {method, headers: h, body: body ? JSON.stringify(body) : (method === "GET" ? undefined : "{}")});
    let j = {};
    try { j = await r.json(); } catch (e) { j = {error: "the server did not answer with JSON"}; }
    if (!r.ok) { const e = new Error(j.error || ("the server answered " + r.status)); e.status = r.status; e.body = j; throw e; }
    return j;
  }
  function msg(text, ok) { const m = $("msg"); if (!m) return; m.innerHTML = text ? `<div class="msg ${ok ? "ok" : ""}">${esc(text)}</div>` : ""; }
  function show(id, on) { const e = $(id); if (e) e.classList.toggle("hide", !on); }

  // --- markdown документов: заголовки, абзацы, списки, таблицы ---------
  function md(text) {
    const out = []; let list = false, table = false;
    const inl = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>');
    for (const raw of text.split("\n")) {
      const t = raw.trim();
      if (!t) { if (list) { out.push("</ul>"); list = false; } if (table) { out.push("</table>"); table = false; } continue; }
      if (t.startsWith("|")) {
        if (t.includes("---")) continue;
        if (!table) { out.push("<table>"); table = true; }
        out.push("<tr>" + t.split("|").slice(1, -1).map((c) => "<td>" + inl(c.trim()) + "</td>").join("") + "</tr>"); continue;
      }
      if (t.startsWith("- ")) { if (!list) { out.push("<ul>"); list = true; } out.push("<li>" + inl(t.slice(2)) + "</li>"); continue; }
      if (t.startsWith("# ")) out.push("<h1>" + inl(t.slice(2)) + "</h1>");
      else if (t.startsWith("## ")) out.push("<h2>" + inl(t.slice(3)) + "</h2>");
      else out.push("<p>" + inl(t) + "</p>");
    }
    if (list) out.push("</ul>"); if (table) out.push("</table>");
    return out.join("\n");
  }

  // --- главная -----------------------------------------------------------
  const pct = (v, d = 1) => v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(d) + " %";
  const day = (t) => t ? new Date(t * 1000).toISOString().slice(0, 10) : null;

  // Депозит — переключателем (владелец 14.10): тот же ответ сервера с
  // другим депозитом; выбор запоминается на устройстве.
  // Деньги — всегда «$ (%)» (владелец 15.10): нет долларов — одна доля.
  // в строку — процент первым, без скобок (владелец 15.10)
  function both(u, f, d) {
    if (u == null && f == null) return "—";
    if (u == null) return pct(f, d);
    const s = (u >= 0 ? "+" : "−") + "$" + Math.abs(u).toLocaleString("en-US", {maximumFractionDigits: 2, minimumFractionDigits: 2});
    return f == null ? s : pct(f, d) + " · " + s;
  }

  async function featured(dep) {
    let r; try { r = await api("GET", "pub/top" + (dep ? "?deposit=" + encodeURIComponent(dep) : "")); }
    catch (e) { $("f-title").textContent = "The strategy server is not responding."; return; }
    const t = r.top;
    const depLabel = "$" + Number(r.deposit).toLocaleString("en-US");
    $("deps").innerHTML = (r.deposits || []).map((d) => `<button role="tab" aria-selected="${d === r.deposit}" data-dep="${d}">$${d >= 1000 ? (d / 1000) + "k" : d}</button>`).join("");
    for (const b of document.querySelectorAll("#deps button")) b.onclick = () => { try { localStorage.setItem("algoth.dep", b.dataset.dep); } catch (e) {} featured(b.dataset.dep); };
    $("rank-title").textContent = "All strategies at " + depLabel;
    // плитки шапки — только числа сервера: число стратегий, окно записи,
    // сделки лучшей, момент пересчёта; нет числа — прочерк, не ноль
    const stat = (id, v) => { const e = $(id); if (e) e.textContent = v; };
    const n = (r.ranking || []).length; stat("s-n", n ? String(n) : "—");
    const w = r.window || {}; stat("s-days", w.span_d != null ? String(Math.round(w.span_d)) : "—");
    if (w.from) stat("s-since", "days of paper trading since " + String(w.from).slice(0, 10));
    stat("s-at", r.computed_at ? String(r.computed_at).slice(11, 16) : "—");
    if (n) stat("s-badge", `paper books · ${n} strategies · recomputed every 5 minutes`);
    $("f-rule").textContent = r.rule + (r.stale ? " The hourly run has not arrived; numbers describe the previous run." : "");
    if (!t) { $("f-title").textContent = "No strategy with trades yet."; return; }
    const side = {long: "Long", short: "Short", both: "Both sides"}[t.side] || t.side;
    $("f-title").textContent = `Ladder · ${t.title_en} · ${side}`;
    $("f-plain").textContent = t.plain || "";
    const ret = $("f-return"); ret.textContent = pct(t.final); ret.className = t.final >= 0 ? "good" : "bad";
    $("f-return-usd").textContent = both(t.usd, null) + " · return over the whole record";
    stat("s-trades", t.n != null ? String(t.n) : "—");
    stat("s-win", t.win == null ? "closed trades" : `closed trades · ${Math.round(t.win * 100)} % won`);
    $("f-tiles").innerHTML = [
      ["max drawdown", pct(t.max_dd), "closed trades, from the account peak", both(t.max_dd_usd, null)],
      ["worst open loss", t.open_dd_share == null ? "—" : pct(t.open_dd_share), t.open_dd_at ? "of the account then, " + new Date(t.open_dd_at * 1000).toISOString().slice(0, 10) : "of the account then", t.open_dd == null ? null : both(t.open_dd, null)],
      ["trades", t.n ?? "—", `${t.days_n} days of record`],
      ["win rate", t.win == null ? "—" : Math.round(t.win * 100) + " %", "closed trades"],
      ["open now", t.open_n ?? "—", "positions"],
      ["record since", t.days && t.days.length ? t.days[0][0] : "—", "paper book"],
    ].map(([k, v, s, u]) => `<div class="tile"><small>${esc(k)}</small><b>${esc(v)}</b>${u ? `<span class="usd">${esc(u)}</span>` : ""}<small>${esc(s)}</small></div>`).join("");
    drawLine._meta = {at: t.open_dd_at, share: t.open_dd_share, usd: t.open_dd};
    drawLine($("f-chart"), $("f-tip"), t.days, t.final >= 0 ? "var(--bid)" : "var(--ask)", t.open_dips);
    $("f-legend").innerHTML = t.open_dips ? `<span><i class="lg-line"></i>closed trades</span><span><i class="lg-dip"></i>with open positions at their worst hour of the day</span>` : "";
    const tb = document.querySelector("#rank tbody");
    tb.innerHTML = (r.ranking || []).map((x, i) => `<tr class="${i === 0 ? "top" : ""}"><td>${i + 1}</td><td>Ladder · ${esc(x.title_en)}</td><td>${esc(side === x.side ? side : ({long: "Long", short: "Short", both: "Both"}[x.side] || x.side))}</td>
      <td class="num ${x.final >= 0 ? "good" : "bad"}">${pct(x.final)}<small class="usd">${both(x.usd, null)}</small></td><td class="num">${pct(x.max_dd)}<small class="usd">${both(x.max_dd_usd, null)}</small></td><td class="num">${x.n ?? "—"}</td><td class="num">${x.win == null ? "—" : Math.round(x.win * 100) + " %"}</td></tr>`).join("");
  }

  // Линия одной серии: накопленный % депозита по дням (значения с
  // сервера). Сетка по трём уровням, подписи первого и последнего дня,
  // перекрестие с подсказкой. Цвет — знак итога, одна серия без легенды.
  function drawLine(svg, tip, days, color, dips) {
    // ширина — по контейнеру, не растяжением: иначе на телефоне подписи
    // сжимаются; при смене ширины — перерисовка
    const W = Math.max(320, Math.round(svg.clientWidth || 720)), H = 240, L = 44, R = 10, T = 12, B = 24;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.removeAttribute("preserveAspectRatio");
    drawLine._last = [svg, tip, days, color, dips];
    if (!drawLine._bound) { drawLine._bound = true; let tm; window.addEventListener("resize", () => { clearTimeout(tm); tm = setTimeout(() => drawLine(...drawLine._last), 150); }); }
    const ns = "http://www.w3.org/2000/svg";
    const el = (n, a) => { const e = document.createElementNS(ns, n); for (const k in a) e.setAttribute(k, a[k]); return e; };
    svg.innerHTML = "";
    if (!days || days.length < 2) { svg.appendChild(Object.assign(el("text", {x: W / 2, y: H / 2, class: "axis-text", "text-anchor": "middle"}), {textContent: "not enough days to draw"})); return; }
    const dv = (dips || []).filter((v) => v != null);
    const ys = days.map((d) => d[1]); const lo = Math.min(0, ...ys, ...dv), hi = Math.max(0, ...ys); const span = (hi - lo) || 1;
    const x = (i) => L + (i / (days.length - 1)) * (W - L - R), y = (v) => T + (1 - (v - lo) / span) * (H - T - B);
    for (const v of [lo, lo + span / 2, hi]) {
      svg.appendChild(el("line", {x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid-line"}));
      svg.appendChild(Object.assign(el("text", {x: L - 6, y: y(v) + 4, class: "axis-text", "text-anchor": "end"}), {textContent: pct(v, 0)}));
    }
    if (lo < 0 && hi > 0) svg.appendChild(el("line", {x1: L, x2: W - R, y1: y(0), y2: y(0), class: "grid-line", style: "stroke:var(--muted)"}));
    const pts = days.map((d, i) => `${x(i).toFixed(1)},${y(d[1]).toFixed(1)}`);
    svg.appendChild(el("path", {d: `M${pts[0]} L${pts.slice(1).join(" ")} L${x(days.length - 1).toFixed(1)},${y(lo)} L${x(0)},${y(lo)} Z`, class: "area", fill: color}));
    // Просадка открытых — ЛИНИЕЙ (владелец 15.10): вторая кривая «счёт с
    // открытыми в худший час дня»; где открытые не были в минусе, она
    // совпадает с линией закрытых; промежуток между линиями — впадина
    // своим цветом. Худшая точка всей записи подписана.
    if (dips && dips.length === days.length) {
      const low = days.map((d, i) => (dips[i] != null && dips[i] < d[1]) ? dips[i] : d[1]);
      const lowPts = low.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
      svg.appendChild(el("path", {d: "M" + lowPts.join(" L") + " L" + pts.slice().reverse().join(" L") + " Z", class: "dip-area"}));
      svg.appendChild(el("path", {d: "M" + lowPts.join(" L"), class: "dip-line"}));
      // Худшая точка — момент худшей ДОЛИ счёта (сервер, `open_dd_at`),
      // подпись — та же доля сервера (15.10: от счёта на тот час, не от
      // стартового депозита); нет момента — точки нет.
      const wd = (drawLine._meta || {}).at ? new Date(drawLine._meta.at * 1000).toISOString().slice(0, 10) : null;
      const worst = wd ? days.findIndex((d) => d[0] === wd) : -1;
      if (worst >= 0) {
        svg.appendChild(el("circle", {cx: x(worst), cy: y(low[worst]), r: 4, class: "dip-dot"}));
        const right = x(worst) > W * 0.6;
        svg.appendChild(Object.assign(el("text", {x: x(worst) + (right ? -8 : 8), y: Math.min(H - B - 4, y(low[worst]) + 14), class: "dip-text", "text-anchor": right ? "end" : "start"}),
          {textContent: `worst open loss ${both(drawLine._meta.usd, drawLine._meta.share, 1)} of the account · ${wd}`}));
      }
    }
    svg.appendChild(el("path", {d: "M" + pts.join(" L"), class: "line", stroke: color}));
    for (const [i, anchor] of [[0, "start"], [days.length - 1, "end"]])
      svg.appendChild(Object.assign(el("text", {x: x(i), y: H - 6, class: "axis-text", "text-anchor": anchor}), {textContent: days[i][0]}));
    const cross = el("line", {y1: T, y2: H - B, class: "cross", visibility: "hidden"}), dot = el("circle", {r: 4.5, fill: color, class: "dot", visibility: "hidden"});
    svg.appendChild(cross); svg.appendChild(dot);
    const hit = el("rect", {x: L, y: 0, width: W - L - R, height: H, fill: "transparent"});
    svg.appendChild(hit);
    const move = (ev) => {
      const box = svg.getBoundingClientRect(); const px = (ev.clientX - box.left) / box.width * W;
      const i = Math.max(0, Math.min(days.length - 1, Math.round((px - L) / (W - L - R) * (days.length - 1))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(days[i][1])); dot.setAttribute("visibility", "visible");
      tip.textContent = `${days[i][0]}  closed ${pct(days[i][1], 2)}` + (dips && dips[i] != null ? `  ·  with open at worst ${pct(dips[i], 2)}` : ""); tip.classList.remove("hide");
      tip.style.left = (x(i) / W * box.width) + "px"; tip.style.top = (y(days[i][1]) / H * box.height) + "px";
    };
    hit.addEventListener("mousemove", move); hit.addEventListener("touchmove", (e) => { move(e.touches[0]); }, {passive: true});
    hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.classList.add("hide"); });
  }

  async function home() {
    $("year").textContent = new Date().getFullYear();
    let dep = null; try { dep = localStorage.getItem("algoth.dep"); } catch (e) {}
    featured(dep);
    try {
      const s = await api("GET", "site");
      if (s.company) $("company").textContent = s.company;
      const set = (id, url, sub) => { const a = $(id); if (url) { a.href = url; a.classList.remove("soon"); $(id + "-sub").textContent = sub; } };
      set("ios", s.ios_url, "App Store"); set("mac", s.mac_url, "Mac App Store");
      if (s.testflight_url) $("testflight").innerHTML = `Early access: <a href="${esc(s.testflight_url)}">join the TestFlight beta</a>.`;
      if (tok()) $("nav-account").textContent = "Account";
    } catch (e) { /* главная живёт и без настроек */ }
  }

  // --- документы ---------------------------------------------------------
  async function legal() {
    try {
      const l = await api("GET", "legal");
      $("version").textContent = "Version " + l.version;
      $("docs").innerHTML = l.docs.map((d) => md(d.text)).join("<hr>");
    } catch (e) { $("docs").innerHTML = `<div class="msg">${esc(e.message)}</div>`; }
  }

  // --- кабинет -----------------------------------------------------------
  let me = null, site = {}, cells = [];

  async function account() {
    try { site = await api("GET", "site"); } catch (e) { site = {}; }
    $("server-ip").textContent = site.server_ip || "";
    $("signout").onclick = async (ev) => { ev.preventDefault(); try { await api("POST", "auth/logout"); } catch (e) {} localStorage.removeItem("algoth.session"); location.reload(); };
    $("op-btn").onclick = async () => {
      try { const r = await api("POST", "auth/operator", {token: $("op-token").value.trim(), device: "web"}); localStorage.setItem("algoth.session", r.session); location.reload(); }
      catch (e) { msg(e.message); }
    };
    $("apple-btn").onclick = appleSignIn;
    if (!site.apple_client_id) $("apple-note").textContent = "Sign in with Apple is being set up on the server (Services ID). Meanwhile sign in from the app.";
    if (!tok()) { show("login", true); return; }
    try { me = await api("GET", "me"); }
    catch (e) { if (e.status === 401) { localStorage.removeItem("algoth.session"); show("login", true); return; } msg(e.message); return; }
    show("signout", true);
    if (me.consent && me.consent.ok === false && me.role !== "operator") { await consent(); return; }
    await render();
  }

  async function appleSignIn() {
    if (!site.apple_client_id) { msg("Sign in with Apple is not configured on the server yet."); return; }
    if (!window.AppleID) {
      await new Promise((ok, bad) => { const s = document.createElement("script"); s.src = "https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js"; s.onload = ok; s.onerror = () => bad(new Error("Apple sign-in script did not load")); document.head.appendChild(s); }).catch((e) => msg(e.message));
      if (!window.AppleID) return;
    }
    try {
      AppleID.auth.init({clientId: site.apple_client_id, scope: "email", redirectURI: location.origin + "/account", usePopup: true});
      const r = await AppleID.auth.signIn();
      const s = await api("POST", "auth/apple", {identity_token: r.authorization.id_token, device: "web"});
      localStorage.setItem("algoth.session", s.session); location.reload();
    } catch (e) { msg(e.message || (e.error ? "Apple: " + e.error : "sign-in cancelled")); }
  }

  async function consent() {
    show("consent", true);
    const l = await api("GET", "legal");
    $("consent-version").textContent = l.version;
    $("consent-docs").innerHTML = l.docs.map((d) => md(d.text)).join("<hr>");
    $("agree").onchange = () => { $("accept").disabled = !$("agree").checked; };
    $("accept").onclick = async () => {
      try { await api("POST", "consent", {version: l.version, device: "web"}); location.reload(); } catch (e) { msg(e.message); }
    };
  }

  async function render() {
    show("home", true);
    const [keys, subs, st] = await Promise.all([api("GET", "keys"), api("GET", "subscriptions"), api("GET", "state")]);
    try { cells = (await api("GET", "strategies")).cells; } catch (e) { cells = []; }
    $("me").innerHTML = `<div class="kv"><b>role</b><span>${esc(me.role)}</span></div><div class="kv"><b>e-mail</b><span>${esc(me.email || "—")}</span></div>
      <div class="kv"><b>live trading on the server</b><span class="${st.live_enabled ? "good" : ""}">${st.live_enabled ? "enabled by the operator" : "disabled"}</span></div>
      ${me.consent && me.consent.accepted ? `<div class="kv"><b>documents accepted</b><span>version ${esc(me.consent.accepted)} on ${when(me.consent.accepted_at)}</span></div>` : ""}`;
    renderKeys(keys.keys || []); renderSubs(subs.subscriptions || [], st); renderPositions(); renderEvents(st);
    if (me.role === "operator") renderOperator(st);
    $("add-key").onclick = async () => {
      msg("Checking the key with the exchange…", true);
      try { await api("POST", "keys", {venue: "bybit", key: $("key").value.trim(), secret: $("secret").value.trim()}); msg("Key added.", true); $("key").value = ""; $("secret").value = ""; await render(); }
      catch (e) { msg(e.message); }
    };
    fillSubForm(keys.keys || []);
  }

  function renderKeys(keys) {
    $("keys").innerHTML = keys.length ? keys.map((k) => `<div class="card"><div class="row"><span class="mono">${esc(k.venue)} · ${esc(k.prefix)}…</span>
      <span class="pill ${k.trade_ok ? "ok" : ""}">${k.trade_ok ? "trading" : "no trading"}</span><span class="pill ${k.ip_ok ? "ok" : ""}">${k.ip_restricted ? (k.ip_ok ? "IP ✓" : "wrong IP") : "no IP restriction"}</span>
      ${k.equity_usd != null ? `<span class="note">equity when added ${amt(k.equity_usd)}</span>` : ""}</div>
      ${(k.warnings || []).map((w) => `<div class="note bad">${esc(w)}</div>`).join("")}
      <div class="row"><button class="danger" data-revoke="${esc(k.key_id)}">Revoke key</button></div></div>`).join("")
      : `<p class="note">No keys yet.</p>`;
    for (const b of document.querySelectorAll("[data-revoke]")) b.onclick = async () => {
      if (!confirm("Revoke this key? Its subscriptions will be closed.")) return;
      try { await api("DELETE", "keys/" + b.dataset.revoke); await render(); } catch (e) { msg(e.message); }
    };
  }

  function subState(st, id) { return ((st.subscriptions || []).find((s) => s.subscription_id === id)) || {}; }

  function renderSubs(subs, st) {
    const bookName = (c) => (c.title_en || c.book) + " · " + (c.side || "");
    $("subs").innerHTML = subs.length ? subs.map((s) => {
      const x = subState(st, s.subscription_id); const ex = x.executor || {}; const es = ex.status || {};
      const live = s.mode === "live"; const want = `${s.book}:${Math.round(s.deposit)}`;
      const cell = cells.find((c) => c.book === s.book && Math.abs(c.deposit - s.deposit) < 1e-9) || {book: s.book, side: s.side};
      return `<div class="card"><div class="row"><b>${esc(bookName(cell))}</b><span class="pill ${live ? "live" : ""}">${live ? "LIVE" : "dry run"}</span><span class="pill">${esc(s.sizing || "compound")}</span></div>
        <div class="kv"><b>deposit</b><span>${amt(s.deposit)}</span></div>
        ${x.cash_usd != null ? `<div class="kv"><b>subscription cash</b><span>${amt(x.cash_usd)}</span></div>` : ""}
        ${x.equity_usd != null ? `<div class="kv"><b>account equity</b><span class="${x.equity_ok ? "good" : "bad"}">${amt(x.equity_usd)}</span></div>` : ""}
        ${live && es.at_ms ? `<div class="kv"><b>executor</b><span class="${ex.age_s < 60 ? "good" : "bad"}">${ex.age_s < 60 ? "running" : "silent " + Math.round(ex.age_s / 60) + " min"}</span></div>
          <div class="kv"><b>realized live</b><span>${money(es.realized_usd)}</span></div><div class="kv"><b>entries / closed</b><span>${es.entries_n || 0} / ${es.closed_n || 0}</span></div>` : ""}
        ${live && ex.why_none ? `<div class="note">${esc(ex.why_none)}</div>` : ""}
        ${es.paused ? `<div class="note bad">entries paused: ${esc(es.paused)}</div>` : ""}${es.last_error ? `<div class="note bad">${esc(es.last_error)}</div>` : ""}
        ${ex.kill ? `<div class="note bad">KILL — the executor does nothing</div>` : ""}${ex.no_entries ? `<div class="note">new entries stopped; open positions are managed</div>` : ""}
        ${(x.warnings || []).map((w) => `<div class="note bad">${esc(w)}</div>`).join("")}
        <div class="row">
          ${live ? (ex.no_entries ? `<button data-act="arm" data-id="${esc(s.subscription_id)}" data-want="${esc(want)}">Resume entries</button>` : `<button data-act="disarm" data-id="${esc(s.subscription_id)}">Stop trading</button>`)
                 + `<button data-act="dry" data-id="${esc(s.subscription_id)}">Back to dry run</button>`
                 + (me.role === "operator" ? `<button class="danger" data-act="kill" data-id="${esc(s.subscription_id)}" data-on="${ex.kill ? 0 : 1}">${ex.kill ? "Lift KILL" : "KILL"}</button>` : "")
                 : `<button data-act="check" data-id="${esc(s.subscription_id)}">Check account</button><button class="primary" data-act="golive" data-id="${esc(s.subscription_id)}" data-want="${esc(want)}">Go live…</button>`}
          <button class="danger" data-act="close-sub" data-id="${esc(s.subscription_id)}">Close subscription</button></div>
        <pre class="note mono hide" id="check-${esc(s.subscription_id)}"></pre></div>`;
    }).join("") : `<p class="note">No subscriptions yet.</p>`;
    for (const b of document.querySelectorAll("[data-act]")) b.onclick = () => action(b.dataset);
  }

  async function action(d) {
    const id = d.id;
    try {
      if (d.act === "check") { const r = await api("POST", `subscriptions/${id}/check`); const p = $("check-" + id); p.textContent = r.text; p.classList.remove("hide"); return; }
      if (d.act === "golive") {
        const w = prompt(`The executor will place REAL orders on Bybit with this key. No money stops. Type ${d.want} to confirm.`);
        if (w == null) return; await api("POST", `subscriptions/${id}/arm`, {confirm: w}); msg("Live. The executor starts within 5 minutes.", true);
      } else if (d.act === "arm") { await api("POST", `subscriptions/${id}/arm`, {confirm: d.want}); }
      else if (d.act === "disarm") { await api("POST", `subscriptions/${id}/disarm`); }
      else if (d.act === "dry") { if (!confirm("Back to dry run? Only possible without open positions.")) return; await api("POST", `subscriptions/${id}/dry`); }
      else if (d.act === "kill") { if (!confirm(d.on === "1" ? "KILL: the executor stops doing anything — no orders, no cancels." : "Lift KILL?")) return; await api("POST", `subscriptions/${id}/kill`, {on: d.on === "1"}); }
      else if (d.act === "close-sub") { if (!confirm("Close this subscription?")) return; const r = await api("DELETE", "subscriptions/" + id); if (r.note) msg(r.note, true); }
      else if (d.act === "close-pos") { if (!confirm(`Close ${d.sym} now?`)) return; const r = await api("POST", `subscriptions/${id}/close`, {sym: d.sym, pos_at: Number(d.at)}); if (r.note) msg(r.note, true); }
      await render();
    } catch (e) { msg(e.message); }
  }

  async function renderPositions() {
    let p; try { p = await api("GET", "positions"); } catch (e) { $("positions").innerHTML = `<p class="note bad">${esc(e.message)}</p>`; return; }
    const rows = (p.positions || []).filter((r) => r.state === "open");
    const pnl = p.pnl || {};
    $("positions").innerHTML = (pnl.open_usd != null ? `<div class="kv"><b>open P&amp;L</b><span class="${pnl.open_usd >= 0 ? "good" : "bad"}">${money(pnl.open_usd)}</span></div><div class="kv"><b>closed</b><span>${money(pnl.realized_usd)}</span></div>` : "")
      + (rows.length ? rows.map((r) => `<div class="card"><div class="row"><b class="mono">${esc(r.sym)}</b><span class="pill">${esc(r.side)}</span>${r.depth ? `<span class="note">rung ${esc(r.depth)}</span>` : ""}<span class="${(r.mark_usd || 0) >= 0 ? "good" : "bad"}">${money(r.mark_usd)}</span></div>
          <div class="note">avg ${esc(r.avg ?? "—")} · take ${esc(r.take_px ?? "—")} · floor ${esc(r.floor_px ?? "—")} · margin ${amt(r.margin)}</div>
          ${r.closing ? `<div class="note">closing: ${esc(r.closing)}</div>` : `<div class="row"><button class="danger" data-act="close-pos" data-id="${esc(r.subscription_id)}" data-sym="${esc(r.sym)}" data-at="${esc(r.pos_at)}">Close</button></div>`}</div>`).join("")
        : `<p class="note">No open live positions.</p>`);
    for (const b of document.querySelectorAll("[data-act=close-pos]")) b.onclick = () => action(b.dataset);
  }

  function renderEvents(st) {
    const ev = (st.events_tail || []).slice(-12).reverse();
    $("events").innerHTML = ev.length ? ev.map((e) => `<div>${esc(when(e.ts))} · ${esc(e.text)}</div>`).join("") : `<span class="note">no events</span>`;
  }

  function fillSubForm(keys) {
    const sel = $("sub-key"); sel.innerHTML = keys.map((k) => `<option value="${esc(k.key_id)}">${esc(k.prefix)}…</option>`).join("");
    const deps = [...new Set(cells.map((c) => c.deposit))].sort((a, b) => a - b);
    $("sub-dep").innerHTML = deps.map((d) => `<option value="${d}">${amt(d)}</option>`).join("");
    const upd = () => {
      const side = $("sub-side").value, mode = $("sub-mode").value;
      const book = side === "both" ? "pair_" + mode : side === "short" ? mode + "_h" : mode;
      const c = cells.find((x) => x.book === book && Math.abs(x.deposit - Number($("sub-dep").value)) < 1e-9 && (x.sizing || "compound") === $("sub-sizing").value);
      $("sub-cell").textContent = c ? `${c.title_en || c.book} · ${c.side} · deposit ${amt(c.deposit)}` + (c.ticket_usd ? ` · per position ${amt(c.ticket_usd)}` : "") + (c.n != null ? ` · paper trades ${c.n}` : "") : "The server has no such strategy cell.";
      $("add-sub").disabled = !c || !keys.length; $("add-sub").dataset.book = book;
    };
    for (const id of ["sub-side", "sub-mode", "sub-dep", "sub-sizing"]) $(id).onchange = upd;
    upd();
    $("add-sub").onclick = async () => {
      try { await api("POST", "subscriptions", {key_id: sel.value, book: $("add-sub").dataset.book, deposit: Number($("sub-dep").value), sizing: $("sub-sizing").value}); msg("Subscribed as a dry run.", true); await render(); }
      catch (e) { msg(e.message); }
    };
  }

  async function renderOperator(st) {
    show("operator", true);
    let lim = {}, ov = {}; try { lim = await api("GET", "operator/limits"); ov = await api("GET", "operator/overview"); } catch (e) { msg(e.message); }
    $("op").innerHTML = `<div class="kv"><b>live trading switch</b><span class="${st.live_enabled ? "good" : ""}">${st.live_enabled ? "enabled" : "disabled"}</span></div>
      <div class="row"><button id="op-live">${st.live_enabled ? "Disable live trading switch" : "Enable live trading switch"}</button></div>
      <div class="kv"><b>accounts</b><span>${lim.accounts ?? "—"} of ${lim.max_accounts ?? "—"} allowed</span></div>
      <div class="row"><input id="op-max" type="number" min="1" value="${lim.max_accounts ?? 1}" style="max-width:120px"><button id="op-max-btn">Set account limit</button></div>
      <h3 style="margin-top:14px">Site settings</h3>
      <label>Apple Services ID (web sign-in client id)</label><input id="s-apple" value="${esc(site.apple_client_id || "")}" placeholder="trade.algoth.web">
      <label>Company name (footer)</label><input id="s-company" value="${esc(site.company || "")}">
      <label>App Store link (iPhone &amp; iPad)</label><input id="s-ios" value="${esc(site.ios_url || "")}" placeholder="https://apps.apple.com/…">
      <label>Mac App Store link</label><input id="s-mac" value="${esc(site.mac_url || "")}">
      <label>TestFlight link (early access)</label><input id="s-tf" value="${esc(site.testflight_url || "")}" placeholder="https://testflight.apple.com/join/…">
      <div class="row"><button class="primary" id="s-save">Save site settings</button></div>
      <h3 style="margin-top:14px">Accounts and subscriptions</h3>
      ${(ov.accounts || []).map((a) => `<div class="card"><div class="row"><span class="mono">${esc(a.account_id)}</span><span class="pill">${esc(a.role)}</span><span class="note">${esc(a.email || "")}</span><span class="note">created ${when(a.created)}</span>
        <span class="note">keys ${a.keys} · subs ${a.subs} · live ${a.live}</span>${a.consent ? `<span class="pill ok">consent ${esc(a.consent)}</span>` : `<span class="pill">no consent</span>`}</div></div>`).join("")}
      <h3 style="margin-top:14px">Capacity by cell</h3>
      ${(ov.cells || []).length ? `<table class="doc">${(ov.cells || []).map((c) => `<tr><td class="mono">${esc(c.book)}</td><td>${amt(c.deposit)}</td><td>${c.live} live</td><td>${c.dry} dry</td></tr>`).join("")}</table>` : `<p class="note">no subscriptions</p>`}`;
    $("op-live").onclick = async () => { try { await api("POST", "operator/live", {on: !st.live_enabled}); await render(); } catch (e) { msg(e.message); } };
    $("op-max-btn").onclick = async () => { try { await api("POST", "operator/limits", {max_accounts: Number($("op-max").value)}); await render(); } catch (e) { msg(e.message); } };
    $("s-save").onclick = async () => {
      try { await api("POST", "operator/site", {apple_client_id: $("s-apple").value.trim(), company: $("s-company").value.trim(), ios_url: $("s-ios").value.trim(), mac_url: $("s-mac").value.trim(), testflight_url: $("s-tf").value.trim()}); msg("Saved.", true); site = await api("GET", "site"); }
      catch (e) { msg(e.message); }
    };
  }

  return {home, legal, account};
})();
