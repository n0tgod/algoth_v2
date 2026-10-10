//! Исполнитель книг Ladder (спека 15 §10a, этапы L2–L3).
//!
//! Решений здесь нет: что делать, говорит строка намерения
//! (`intents.jsonl`, пишет `tools/app_api/intents.py` тем же ядром
//! правил, что считает бумажную книгу). Здесь — только как это сделать
//! на площадке:
//!
//!  * вход — IOC-лимит базовой доли с потолком 30 б.п. от середины;
//!  * рунги — лимитные заявки на уровнях намерения, количество — доля
//!    маржи × плечо / цена рунга;
//!  * цель — reduceOnly-лимит на всё количество по `средняя × (1 ± доля)`
//!    (та же формула, что `rules.avg_walk`), переставляется после
//!    каждого заполненного рунга;
//!  * пол капитуляции (уровень из намерения на текущей глубине) и срок —
//!    каждым тактом по лучшим ценам, закрытие reduceOnly-IOC с потолком
//!    100 б.п.; охрана рынком и прочие выходы книги — намерением `exit`;
//!  * сверка с биржей по своим именам: чужие позиции счёта не трогаются,
//!    но имя, занятое чужой позицией, не входит;
//!  * журнал событий §7.6 (`events.jsonl`) — его читает приложение и
//!    шлёт пуши.
//!
//! Денежных пределов нет (решение владельца 2026-10-10: «в стратегии всё
//! заложено»). Остаются: `KILL` (не делать ничего), `NO_ENTRIES` (входы
//! выключены, позиции ведутся) и пауза входов при расхождении с биржей —
//! это не аппетит к риску, а то, что состояние исполнителя стало
//! неверным.
//!
//! Маржа счёта — какая стоит на счёте (единый счёт, кросс); плечо
//! инструмента выставляется перед входом равным плечу забора, чтобы
//! начальная маржа заявок была той же, что бумага держит под позицию.

use crate::journal::utc_day;
use crate::live::{cap_price, ceil_step, floor_step, fmt_step, Exchange, Instrument};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

/// Потолок входа и выхода, б.п. от середины (спека 15 §10a).
pub const ENTRY_CAP_BP: f64 = 30.0;
pub const EXIT_CAP_BP: f64 = 100.0;
/// Намерение старше этого при первом прочтении не исполняется: цена
/// ушла, и вход описывал бы другую сделку.
pub const INTENT_MAX_AGE_MS: i64 = 20 * 60 * 1000;
/// Индекс хедж-режима нужен, когда площадка отвергла индекс 0.
const IDX_MISMATCH: &str = "position idx not match position mode";

#[derive(Deserialize, Serialize, Clone, Debug, Default)]
pub struct Rung {
    pub px: f64,
    pub share: f64,
    #[serde(default)]
    pub avg: Option<f64>,
    #[serde(default)]
    pub take_px: Option<f64>,
    #[serde(default)]
    pub floor_px: Option<f64>,
    #[serde(default)]
    pub liq_px: Option<f64>,
}

#[derive(Deserialize, Clone, Debug, Default)]
pub struct Intent {
    pub seq: i64,
    pub kind: String,
    #[serde(default)]
    pub sym: Option<String>,
    #[serde(default)]
    pub side: Option<String>,
    #[serde(default)]
    pub book: Option<String>,
    #[serde(default)]
    pub lev: Option<f64>,
    #[serde(default)]
    pub margin_usd: Option<f64>,
    #[serde(default)]
    pub px_ref: Option<f64>,
    #[serde(default)]
    pub rungs: Option<Vec<Rung>>,
    #[serde(default)]
    pub take_frac: Option<f64>,
    #[serde(default)]
    pub take_px: Option<f64>,
    #[serde(default)]
    pub floor_px: Option<f64>,
    #[serde(default)]
    pub liq_px: Option<f64>,
    #[serde(default)]
    pub term_ts: Option<f64>,
    #[serde(default)]
    pub decided_at: Option<f64>,
    #[serde(default)]
    pub computed_at: Option<f64>,
    #[serde(default)]
    pub reason: Option<String>,
}

/// Лежащая заявка: рунг или цель.
#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct Rest {
    pub id: String,
    pub px: f64,
    pub qty: f64,
    /// Уже учтённое исполнение этой заявки и его деньги.
    pub filled: f64,
    pub filled_cost: f64,
    pub fee: f64,
    /// Номер рунга (у цели — 0).
    pub rung: usize,
}

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct LPos {
    pub key: String,
    pub sym: String,
    pub side: String,
    pub book: Option<String>,
    pub decided_at: f64,
    pub lev: f64,
    pub margin_usd: f64,
    pub take_frac: Option<f64>,
    pub term_ms: i64,
    pub rungs: Vec<Rung>,
    /// Заполнено рунгов (вход — первый).
    pub depth: usize,
    pub qty: f64,
    /// Деньги открытого количества по цене входа (средняя = cost / qty).
    pub cost: f64,
    /// Весь вложенный нотионал — знаменатель б.п. итога.
    pub notional_in: f64,
    pub fees: f64,
    /// Реализованное частичными выходами, брутто.
    pub realized: f64,
    pub rung_orders: Vec<Rest>,
    pub take: Option<Rest>,
    pub opened_ms: i64,
    pub tick: f64,
    pub step: f64,
    pub min_qty: f64,
    pub min_notional: f64,
    /// Выход начат и не дошёл (IOC исполнилась частично): причина.
    pub closing: Option<String>,
}

impl LPos {
    pub fn long(&self) -> bool {
        self.side == "long"
    }
    pub fn avg(&self) -> f64 {
        if self.qty > 0.0 {
            self.cost / self.qty
        } else {
            0.0
        }
    }
    pub fn n(&self) -> usize {
        self.rungs.len().max(1)
    }
    /// Пол на текущей глубине — уровень намерения для этой глубины.
    pub fn floor_px(&self) -> Option<f64> {
        let k = self.depth.max(1).min(self.rungs.len().max(1)) - 1;
        self.rungs.get(k).and_then(|r| r.floor_px)
    }
    pub fn liq_px(&self) -> Option<f64> {
        let k = self.depth.max(1).min(self.rungs.len().max(1)) - 1;
        self.rungs.get(k).and_then(|r| r.liq_px)
    }
    /// Цель от ТЕКУЩЕЙ средней: `avg × (1 ± доля)`, округление внутрь.
    pub fn take_px(&self) -> Option<f64> {
        let f = self.take_frac?;
        if !(f > 0.0) || self.qty <= 0.0 {
            return None;
        }
        let raw = if self.long() {
            self.avg() * (1.0 + f)
        } else {
            self.avg() * (1.0 - f)
        };
        Some(if self.long() {
            ceil_step(raw, self.tick)
        } else {
            floor_step(raw, self.tick)
        })
    }
}

#[derive(Deserialize, Serialize, Clone, Debug, Default)]
#[serde(default)]
pub struct LState {
    pub seq_done: i64,
    pub positions: BTreeMap<String, LPos>,
    pub realized_usd: f64,
    pub realized_by_day: BTreeMap<String, f64>,
    /// Пауза входов по расхождению с биржей; снимает файл `RESUME`.
    pub paused: Option<String>,
    /// 0 — односторонний режим счёта, 1 — хедж (узнаётся отказом).
    pub hedge: bool,
    pub closed_n: u64,
    pub entries_n: u64,
    pub rejects_n: u64,
}

pub struct LadderCfg {
    pub dir: PathBuf,
    pub dry: bool,
}

impl LadderCfg {
    pub fn intents(&self) -> PathBuf {
        self.dir.join("intents.jsonl")
    }
    pub fn events(&self) -> PathBuf {
        self.dir.join("events.jsonl")
    }
    pub fn state(&self) -> PathBuf {
        self.dir.join("ladder_state.json")
    }
    pub fn status(&self) -> PathBuf {
        self.dir.join("ladder_status.json")
    }
    pub fn kill(&self) -> PathBuf {
        self.dir.join("KILL")
    }
    pub fn no_entries(&self) -> PathBuf {
        self.dir.join("NO_ENTRIES")
    }
    pub fn resume(&self) -> PathBuf {
        self.dir.join("RESUME")
    }
    /// Мягкая остановка: процесс выходит МЕЖДУ тактами, состояние
    /// сохранено (деплой и перевод подписки в сухой режим). Сигнал
    /// убил бы процесс посреди такта — заявка ушла, запись нет.
    pub fn stop(&self) -> PathBuf {
        self.dir.join("STOP")
    }
    pub fn pid(&self) -> PathBuf {
        self.dir.join("ladder.pid")
    }
}

/// Второй исполнитель на ту же подписку делил бы одни позиции и
/// удваивал заявки: живой pid в файле с процессом `bot ladder` — отказ.
pub fn claim_pid(cfg: &LadderCfg) -> Result<(), String> {
    if let Ok(t) = std::fs::read_to_string(cfg.pid()) {
        if let Ok(pid) = t.trim().parse::<u32>() {
            if pid != std::process::id() {
                let cmd = std::fs::read(format!("/proc/{pid}/cmdline")).unwrap_or_default();
                let cmd = String::from_utf8_lossy(&cmd).replace('\0', " ");
                if cmd.contains("ladder") && cmd.contains(&cfg.dir.display().to_string()) {
                    return Err(format!("исполнитель этой подписки уже работает (pid {pid})"));
                }
            }
        }
    }
    std::fs::write(cfg.pid(), std::process::id().to_string())
        .map_err(|e| format!("pid-файл не пишется: {e}"))
}

#[derive(Default, Debug)]
pub struct LTick {
    pub opened: usize,
    pub closed: usize,
    pub rejected: usize,
    pub rungs: usize,
    pub note: Option<String>,
}

pub struct Ladder<E: Exchange> {
    pub cfg: LadderCfg,
    pub ex: E,
    pub st: LState,
    ev_seq: i64,
    ins: BTreeMap<String, Instrument>,
    lev_set: BTreeMap<String, String>,
    pub last_error: Option<String>,
}

fn mode(dry: bool) -> &'static str {
    if dry {
        "dry"
    } else {
        "live"
    }
}

fn read_jsonl(path: &Path) -> Vec<Value> {
    let Ok(text) = std::fs::read_to_string(path) else {
        return Vec::new();
    };
    text.lines()
        .filter_map(|l| serde_json::from_str::<Value>(l.trim()).ok())
        .collect()
}

impl<E: Exchange> Ladder<E> {
    pub fn open(cfg: LadderCfg, ex: E) -> Result<Ladder<E>, String> {
        std::fs::create_dir_all(&cfg.dir)
            .map_err(|e| format!("каталог подписки {} не создаётся: {e}", cfg.dir.display()))?;
        let st = match std::fs::read_to_string(cfg.state()) {
            Ok(t) => serde_json::from_str::<LState>(&t)
                .map_err(|e| format!("состояние исполнителя битое: {e}"))?,
            Err(_) => LState::default(),
        };
        let ev_seq = read_jsonl(&cfg.events())
            .iter()
            .filter_map(|v| v.get("seq").and_then(Value::as_i64))
            .max()
            .unwrap_or(0);
        Ok(Ladder {
            cfg,
            ex,
            st,
            ev_seq,
            ins: BTreeMap::new(),
            lev_set: BTreeMap::new(),
            last_error: None,
        })
    }

    // --- журнал и состояние ------------------------------------------

    fn event(&mut self, now_ms: i64, ev: &str, mut v: Value) {
        self.ev_seq += 1;
        if let Some(o) = v.as_object_mut() {
            o.insert("seq".into(), json!(self.ev_seq));
            o.insert("ts".into(), json!(now_ms as f64 / 1000.0));
            o.insert("ev".into(), json!(ev));
            o.insert("mode".into(), json!(mode(self.cfg.dry)));
            o.insert("written_at".into(), json!(now_ms as f64 / 1000.0));
        }
        let line = serde_json::to_string(&v).unwrap_or_default();
        use std::io::Write;
        let ok = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.cfg.events())
            .and_then(|mut f| writeln!(f, "{line}"));
        if let Err(e) = ok {
            eprintln!("журнал событий не пишется: {e}");
        }
    }

    fn pos_fields(p: &LPos) -> Value {
        json!({
            "sym": p.sym, "side": p.side, "book": p.book,
            "pos_at": p.decided_at, "lev": p.lev,
            "margin_usd": p.margin_usd, "avg": p.avg(),
            "depth": format!("{}/{}", p.depth, p.n()),
            "floor_px": p.floor_px(), "liq_px": p.liq_px(),
            "term_ts": p.term_ms as f64 / 1000.0,
        })
    }

    pub fn save(&self) {
        let tmp = self.cfg.dir.join("ladder_state.json.tmp");
        let ok = std::fs::write(&tmp, serde_json::to_vec_pretty(&self.st).unwrap_or_default())
            .and_then(|_| std::fs::rename(&tmp, self.cfg.state()));
        if let Err(e) = ok {
            eprintln!("состояние исполнителя не пишется: {e}");
        }
    }

    pub fn status_json(&self, now_ms: i64, note: Option<&str>) -> Value {
        let today = utc_day(now_ms);
        let ps: Vec<Value> = self
            .st
            .positions
            .values()
            .map(|p| {
                let mut v = Self::pos_fields(p);
                if let Some(o) = v.as_object_mut() {
                    o.insert("key".into(), json!(p.key));
                    o.insert("qty".into(), json!(p.qty));
                    o.insert("take_px".into(), json!(p.take.as_ref().map(|t| t.px)));
                    o.insert("rungs_resting".into(), json!(p.rung_orders.len()));
                    o.insert("closing".into(), json!(p.closing));
                    o.insert("opened_ms".into(), json!(p.opened_ms));
                }
                v
            })
            .collect();
        json!({
            "at_ms": now_ms,
            "mode": mode(self.cfg.dry),
            "kill": self.cfg.kill().exists(),
            "no_entries": self.cfg.no_entries().exists(),
            "paused": self.st.paused,
            "hedge": self.st.hedge,
            "seq_done": self.st.seq_done,
            "positions": ps,
            "margin_open_usd": self.st.positions.values().map(|p| p.margin_usd).sum::<f64>(),
            "realized_usd": self.st.realized_usd,
            "realized_today_usd": self.st.realized_by_day.get(&today).copied().unwrap_or(0.0),
            "entries_n": self.st.entries_n,
            "closed_n": self.st.closed_n,
            "rejects_n": self.st.rejects_n,
            "last_error": self.last_error,
            "note": note,
        })
    }

    fn write_status(&self, now_ms: i64, note: Option<&str>) {
        let st = self.status_json(now_ms, note);
        let tmp = self.cfg.dir.join("ladder_status.json.tmp");
        let ok = std::fs::write(&tmp, serde_json::to_vec_pretty(&st).unwrap_or_default())
            .and_then(|_| std::fs::rename(&tmp, self.cfg.status()));
        if let Err(e) = ok {
            eprintln!("статус не пишется: {e}");
        }
    }

    // --- площадка ------------------------------------------------------

    fn instrument(&mut self, sym: &str) -> Result<Instrument, String> {
        if let Some(i) = self.ins.get(sym) {
            return Ok(*i);
        }
        let i = self.ex.instrument(sym)?;
        self.ins.insert(sym.to_string(), i);
        Ok(i)
    }

    /// Заявка с индексом позиции по режиму счёта; отказ «не тот индекс»
    /// переключает режим один раз и повторяет.
    #[allow(clippy::too_many_arguments)]
    fn place(
        &mut self,
        sym: &str,
        long_pos: bool,
        buy: bool,
        qty: &str,
        px: &str,
        tif: &str,
        link: &str,
        reduce: bool,
    ) -> Result<String, String> {
        let side = if buy { "Buy" } else { "Sell" };
        let idx = |hedge: bool| -> i64 {
            if !hedge {
                0
            } else if long_pos {
                1
            } else {
                2
            }
        };
        match self
            .ex
            .place_limit_idx(sym, side, qty, px, tif, link, reduce, idx(self.st.hedge))
        {
            Err(e) if e.contains(IDX_MISMATCH) => {
                self.st.hedge = !self.st.hedge;
                eprintln!(
                    "режим позиций счёта: {}",
                    if self.st.hedge { "хедж" } else { "односторонний" }
                );
                self.ex
                    .place_limit_idx(sym, side, qty, px, tif, link, reduce, idx(self.st.hedge))
            }
            r => r,
        }
    }

    // --- такт ------------------------------------------------------------

    pub fn tick(&mut self, now_ms: i64) -> LTick {
        let mut rep = LTick::default();
        if self.cfg.kill().exists() {
            // KILL — не делать НИЧЕГО: ни заявок, ни отмен.
            rep.note = Some("KILL".into());
            self.write_status(now_ms, Some("KILL — исполнитель ничего не делает"));
            return rep;
        }
        if self.cfg.resume().exists() {
            if let Some(r) = self.st.paused.take() {
                self.event(now_ms, "resume", json!({"reason": format!("пауза снята файлом RESUME (была: {r})")}));
            }
            let _ = std::fs::remove_file(self.cfg.resume());
        }
        self.last_error = None;
        if !self.cfg.dry {
            if let Err(e) = self.discover_fills(now_ms, &mut rep) {
                self.last_error = Some(e);
            }
            if let Err(e) = self.reconcile(now_ms, &mut rep) {
                self.last_error = Some(e);
            }
            self.check_exits(now_ms, &mut rep);
        }
        let intents = self.new_intents();
        for it in intents {
            match it.kind.as_str() {
                "entry" => self.enter(&it, now_ms, &mut rep),
                "exit" => self.exit_intent(&it, now_ms, &mut rep),
                _ => {}
            }
            self.st.seq_done = self.st.seq_done.max(it.seq);
        }
        if !self.cfg.dry {
            self.ensure_takes(now_ms);
        }
        self.save();
        self.write_status(now_ms, rep.note.as_deref());
        rep
    }

    fn new_intents(&self) -> Vec<Intent> {
        let mut out: Vec<Intent> = read_jsonl(&self.cfg.intents())
            .into_iter()
            .filter_map(|v| serde_json::from_value::<Intent>(v).ok())
            .filter(|i| i.seq > self.st.seq_done)
            .collect();
        out.sort_by_key(|i| i.seq);
        out
    }

    // --- вход -----------------------------------------------------------

    fn reject(&mut self, it: &Intent, reason: String, now_ms: i64, rep: &mut LTick) {
        rep.rejected += 1;
        self.st.rejects_n += 1;
        self.event(
            now_ms,
            "reject",
            json!({"sym": it.sym, "side": it.side, "book": it.book,
                   "pos_at": it.decided_at, "reason": reason}),
        );
    }

    fn enter(&mut self, it: &Intent, now_ms: i64, rep: &mut LTick) {
        let (Some(sym), Some(side), Some(lev), Some(margin), Some(rungs)) = (
            it.sym.clone(),
            it.side.clone(),
            it.lev,
            it.margin_usd,
            it.rungs.clone(),
        ) else {
            self.reject(it, "намерение без имени, стороны, плеча, маржи или рунгов".into(), now_ms, rep);
            return;
        };
        if rungs.is_empty() || !(lev > 0.0) || !(margin > 0.0) {
            self.reject(it, "намерение с пустыми рунгами или нулевой маржой".into(), now_ms, rep);
            return;
        }
        let long = side == "long";
        let made = it.computed_at.or(it.decided_at).unwrap_or(0.0);
        if now_ms - (made * 1000.0) as i64 > INTENT_MAX_AGE_MS {
            self.reject(
                it,
                format!(
                    "намерение устарело: {} мин после расчёта — цена ушла",
                    (now_ms - (made * 1000.0) as i64) / 60_000
                ),
                now_ms,
                rep,
            );
            return;
        }
        if self.cfg.no_entries().exists() {
            self.reject(it, "входы выключены (NO_ENTRIES)".into(), now_ms, rep);
            return;
        }
        if let Some(p) = &self.st.paused {
            let r = format!("входы на паузе: {p}");
            self.reject(it, r, now_ms, rep);
            return;
        }
        if self.st.positions.contains_key(&sym) {
            self.reject(it, "имя уже в позиции этого исполнителя".into(), now_ms, rep);
            return;
        }
        let ins = match self.instrument(&sym) {
            Ok(i) => i,
            Err(e) => {
                self.reject(it, format!("справочник не читается: {e}"), now_ms, rep);
                return;
            }
        };
        let (bid, ask) = match self.ex.best_prices(&sym) {
            Ok(x) => x,
            Err(e) => {
                self.reject(it, format!("цены не читаются: {e}"), now_ms, rep);
                return;
            }
        };
        let mid = (bid + ask) / 2.0;
        if !(mid > 0.0) {
            self.reject(it, "середины нет".into(), now_ms, rep);
            return;
        }
        let q0 = floor_step(rungs[0].share * margin * lev / mid, ins.step);
        if q0 < ins.min_qty - 1e-12 || q0 * mid < ins.min_notional - 1e-9 {
            self.reject(
                it,
                format!(
                    "база мельче минимума биржи: {} × {mid} при мин. лоте {} и мин. нотионале {} $",
                    fmt_step(q0, ins.step),
                    ins.min_qty,
                    ins.min_notional
                ),
                now_ms,
                rep,
            );
            return;
        }
        let buy = long;
        let px = cap_price(mid, buy, ENTRY_CAP_BP, ins.tick);
        let term_ms = (it.term_ts.unwrap_or(0.0) * 1000.0) as i64;
        if self.cfg.dry {
            rep.opened += 1;
            self.event(
                now_ms,
                "entry",
                json!({"sym": sym, "side": side, "book": it.book, "pos_at": it.decided_at,
                       "qty": q0, "px": px, "lev": lev, "margin_usd": margin,
                       "depth": format!("1/{}", rungs.len()), "take_px": it.take_px,
                       "floor_px": rungs[0].floor_px.or(it.floor_px), "term_ts": it.term_ts,
                       "reason": "сухой режим: заявка сформирована, на биржу не отправлена"}),
            );
            return;
        }
        // чужая позиция на счёте по этому имени — вход запрещён
        match self.ex.positions() {
            Ok(ps) => {
                if ps.iter().any(|p| p.sym == sym && p.qty > 0.0) {
                    self.reject(it, "на счёте уже есть чужая позиция по этому имени".into(), now_ms, rep);
                    return;
                }
            }
            Err(e) => {
                self.reject(it, format!("позиции счёта не читаются: {e}"), now_ms, rep);
                return;
            }
        }
        // Плечо инструмента = плечо забора, до входа: начальная маржа
        // заявок та же, что бумага держит. Отказ площадки — отказ входа.
        let lev_s = format!("{:.2}", (lev * 100.0).floor() / 100.0);
        if self.lev_set.get(&sym) != Some(&lev_s) {
            if let Err(e) = self.ex.set_leverage(&sym, &lev_s) {
                self.reject(it, format!("плечо {lev_s}× не выставилось: {e}"), now_ms, rep);
                return;
            }
            self.lev_set.insert(sym.clone(), lev_s.clone());
        }
        let link = format!("ld-in-{}-{}", sym, now_ms);
        let oid = match self.place(
            &sym,
            long,
            buy,
            &fmt_step(q0, ins.step),
            &fmt_step(px, ins.tick),
            "IOC",
            &link,
            false,
        ) {
            Ok(id) => id,
            Err(e) => {
                self.reject(it, format!("заявка входа отвергнута: {e}"), now_ms, rep);
                return;
            }
        };
        let st = match self.ex.order_status(&sym, &oid) {
            Ok(s) => s,
            Err(e) => {
                // Заявка ушла, статус неизвестен — сверка следующего
                // такта увидит позицию без записи и поставит паузу.
                self.reject(it, format!("статус входа не читается: {e}"), now_ms, rep);
                return;
            }
        };
        if st.filled_qty <= 0.0 {
            self.reject(
                it,
                format!("IOC не исполнилась в потолке {} б.п. от середины", ENTRY_CAP_BP),
                now_ms,
                rep,
            );
            return;
        }
        let p = LPos {
            key: format!("{}:{}", sym, it.decided_at.unwrap_or(0.0) as i64),
            sym: sym.clone(),
            side: side.clone(),
            book: it.book.clone(),
            decided_at: it.decided_at.unwrap_or(0.0),
            lev,
            margin_usd: margin,
            take_frac: it.take_frac,
            term_ms,
            rungs: rungs.clone(),
            depth: 1,
            qty: st.filled_qty,
            cost: st.filled_qty * st.avg_px,
            notional_in: st.filled_qty * st.avg_px,
            fees: st.fee_usd,
            realized: 0.0,
            rung_orders: Vec::new(),
            take: None,
            opened_ms: now_ms,
            tick: ins.tick,
            step: ins.step,
            min_qty: ins.min_qty,
            min_notional: ins.min_notional,
            closing: None,
        };
        self.st.entries_n += 1;
        rep.opened += 1;
        let mut f = Self::pos_fields(&p);
        if let Some(o) = f.as_object_mut() {
            o.insert("qty".into(), json!(st.filled_qty));
            o.insert("px".into(), json!(st.avg_px));
            o.insert("px_ref".into(), json!(it.px_ref));
            o.insert("slip_bp".into(), json!(it.px_ref.map(|r| {
                let d = (st.avg_px / r - 1.0) * 1e4;
                if long { d } else { -d }
            })));
            o.insert("take_px".into(), json!(p.take_px()));
            o.insert("fee_usd".into(), json!(st.fee_usd));
            if st.filled_qty + 1e-12 < q0 {
                o.insert("reason".into(), json!(format!("исполнено частично: {} из {}", st.filled_qty, q0)));
            }
        }
        self.event(now_ms, "entry", f);
        self.st.positions.insert(sym.clone(), p);
        // позиция на бирже уже есть — запись о ней на диск немедленно
        self.save();
        self.place_rungs(&sym, now_ms, rep);
        self.place_take(&sym, now_ms);
    }

    fn place_rungs(&mut self, sym: &str, now_ms: i64, rep: &mut LTick) {
        let Some(p) = self.st.positions.get(sym).cloned() else { return };
        let mut placed = Vec::new();
        for (i, r) in p.rungs.iter().enumerate().skip(1) {
            let px = if p.long() { floor_step(r.px, p.tick) } else { ceil_step(r.px, p.tick) };
            if !(px > 0.0) {
                continue;
            }
            let q = floor_step(r.share * p.margin_usd * p.lev / px, p.step);
            if q < p.min_qty - 1e-12 || q * px < p.min_notional - 1e-9 {
                self.event(
                    now_ms,
                    "reject",
                    json!({"sym": p.sym, "side": p.side, "pos_at": p.decided_at,
                           "reason": format!("рунг {} мельче минимума биржи — не ставится", i + 1)}),
                );
                continue;
            }
            let link = format!("ld-r{}-{}-{}", i + 1, p.sym, now_ms);
            match self.place(
                &p.sym,
                p.long(),
                p.long(),
                &fmt_step(q, p.step),
                &fmt_step(px, p.tick),
                "GTC",
                &link,
                false,
            ) {
                Ok(id) => {
                    rep.rungs += 1;
                    placed.push(Rest { id, px, qty: q, filled: 0.0, filled_cost: 0.0, fee: 0.0, rung: i });
                }
                Err(e) => self.event(
                    now_ms,
                    "reject",
                    json!({"sym": p.sym, "side": p.side, "pos_at": p.decided_at,
                           "reason": format!("рунг {} не поставлен: {e}", i + 1)}),
                ),
            }
        }
        if let Some(q) = self.st.positions.get_mut(sym) {
            q.rung_orders = placed;
        }
    }

    /// Цель reduceOnly на всё открытое количество от текущей средней.
    fn place_take(&mut self, sym: &str, now_ms: i64) {
        let Some(p) = self.st.positions.get(sym).cloned() else { return };
        if p.closing.is_some() || p.take.is_some() {
            return;
        }
        let Some(tp) = p.take_px() else { return };
        let q = floor_step(p.qty, p.step);
        if q <= 0.0 {
            return;
        }
        let link = format!("ld-tp-{}-{}", p.sym, now_ms);
        match self.place(
            &p.sym,
            p.long(),
            !p.long(),
            &fmt_step(q, p.step),
            &fmt_step(tp, p.tick),
            "GTC",
            &link,
            true,
        ) {
            Ok(id) => {
                if let Some(x) = self.st.positions.get_mut(sym) {
                    x.take = Some(Rest { id, px: tp, qty: q, filled: 0.0, filled_cost: 0.0, fee: 0.0, rung: 0 });
                }
                let mut f = Self::pos_fields(&p);
                if let Some(o) = f.as_object_mut() {
                    o.insert("px".into(), json!(tp));
                    o.insert("qty".into(), json!(q));
                }
                self.event(now_ms, "take_set", f);
            }
            Err(e) => {
                self.last_error = Some(format!("цель {} не встала: {e}", p.sym));
            }
        }
    }

    fn ensure_takes(&mut self, now_ms: i64) {
        let syms: Vec<String> = self
            .st
            .positions
            .values()
            .filter(|p| p.take.is_none() && p.closing.is_none())
            .map(|p| p.sym.clone())
            .collect();
        for s in syms {
            self.place_take(&s, now_ms);
        }
    }

    // --- исполнения ------------------------------------------------------

    /// Учитывает приращение исполнения лежащей заявки по её статусу.
    /// Возвращает (приращение кол-ва, цена приращения, комиссия, конечна ли).
    fn delta(&self, sym: &str, r: &Rest) -> Result<(f64, f64, f64, bool), String> {
        let s = self.ex.order_status(sym, &r.id)?;
        let d = s.filled_qty - r.filled;
        let fin = matches!(
            s.status.as_str(),
            "Filled" | "Cancelled" | "Rejected" | "Deactivated" | "PartiallyFilledCanceled"
        );
        if d <= 1e-12 {
            return Ok((0.0, 0.0, 0.0, fin));
        }
        let cost_all = s.filled_qty * s.avg_px;
        let px = (cost_all - r.filled_cost) / d;
        Ok((d, px, (s.fee_usd - r.fee).max(0.0), fin))
    }

    fn apply_rung_fill(&mut self, sym: &str, ri: usize, d: f64, px: f64, fee: f64, now_ms: i64, rep: &mut LTick) {
        let Some(p) = self.st.positions.get_mut(sym) else { return };
        p.qty += d;
        p.cost += d * px;
        p.notional_in += d * px;
        p.fees += fee;
        if let Some(r) = p.rung_orders.iter_mut().find(|r| r.rung == ri) {
            r.filled += d;
            r.filled_cost += d * px;
            r.fee += fee;
        }
        p.depth = p.depth.max(ri + 1);
        let snap = p.clone();
        rep.rungs += 1;
        let mut f = Self::pos_fields(&snap);
        if let Some(o) = f.as_object_mut() {
            o.insert("qty".into(), json!(d));
            o.insert("px".into(), json!(px));
            o.insert("fee_usd".into(), json!(fee));
            o.insert("take_px".into(), json!(snap.take_px()));
        }
        self.event(now_ms, "rung", f);
    }

    /// Частичный или полный выход: деньги и количество.
    fn apply_exit_fill(&mut self, sym: &str, d: f64, px: f64, fee: f64) {
        let Some(p) = self.st.positions.get_mut(sym) else { return };
        let avg = p.avg();
        let sgn = if p.long() { 1.0 } else { -1.0 };
        let d = d.min(p.qty);
        p.realized += sgn * (px - avg) * d;
        p.cost -= avg * d;
        p.qty -= d;
        p.fees += fee;
        if p.qty < p.step * 0.5 {
            p.qty = 0.0;
            p.cost = 0.0;
        }
    }

    /// Позиция закрыта: событие исхода, реализованное, снятие рунгов.
    fn finish(&mut self, sym: &str, ev: &str, exit_px: Option<f64>, reason: Option<String>, now_ms: i64, rep: &mut LTick) {
        let Some(p) = self.st.positions.remove(sym) else { return };
        for r in &p.rung_orders {
            let _ = self.ex.cancel(&p.sym, &r.id);
        }
        if let Some(t) = &p.take {
            if ev != "take" {
                let _ = self.ex.cancel(&p.sym, &t.id);
            }
        }
        let pnl = p.realized - p.fees;
        self.st.realized_usd += pnl;
        *self.st.realized_by_day.entry(utc_day(now_ms)).or_insert(0.0) += pnl;
        self.st.closed_n += 1;
        rep.closed += 1;
        let mut f = Self::pos_fields(&p);
        if let Some(o) = f.as_object_mut() {
            o.insert("px".into(), json!(exit_px));
            o.insert("pnl_usd".into(), json!(pnl));
            o.insert(
                "pnl_bp".into(),
                json!(if p.notional_in > 0.0 { Some(pnl / p.notional_in * 1e4) } else { None }),
            );
            o.insert("fee_usd".into(), json!(p.fees));
            o.insert("exit_ts_pos".into(), json!(now_ms as f64 / 1000.0));
            o.insert("depth".into(), json!(format!("{}/{}", p.depth, p.n())));
            if let Some(r) = reason {
                o.insert("reason".into(), json!(r));
            }
        }
        self.event(now_ms, ev, f);
        self.save();
    }

    /// Исполнения лежащих заявок, ушедших из списка открытых.
    fn discover_fills(&mut self, now_ms: i64, rep: &mut LTick) -> Result<(), String> {
        if self.st.positions.is_empty() {
            return Ok(());
        }
        let open: BTreeSet<String> = self
            .ex
            .open_orders()
            .map_err(|e| format!("открытые заявки не читаются: {e}"))?
            .into_iter()
            .map(|r| r.id)
            .collect();
        let syms: Vec<String> = self.st.positions.keys().cloned().collect();
        for sym in syms {
            self.poll_sym(&sym, Some(&open), now_ms, rep);
        }
        Ok(())
    }

    /// Опрос заявок одного имени: `open` — список открытых (опрашиваются
    /// только ушедшие из него); None — опрашиваются все (сверка).
    fn poll_sym(&mut self, sym: &str, open: Option<&BTreeSet<String>>, now_ms: i64, rep: &mut LTick) {
        let Some(p) = self.st.positions.get(sym).cloned() else { return };
        let mut rung_filled = false;
        for r in &p.rung_orders {
            if open.map(|o| o.contains(&r.id)).unwrap_or(false) {
                continue;
            }
            match self.delta(sym, r) {
                Ok((d, px, fee, fin)) => {
                    if d > 0.0 {
                        self.apply_rung_fill(sym, r.rung, d, px, fee, now_ms, rep);
                        rung_filled = true;
                    }
                    if fin {
                        if let Some(q) = self.st.positions.get_mut(sym) {
                            q.rung_orders.retain(|x| x.id != r.id);
                        }
                    }
                }
                Err(e) => self.last_error = Some(format!("рунг {sym}: {e}")),
            }
        }
        if let Some(t) = p.take.clone() {
            if !open.map(|o| o.contains(&t.id)).unwrap_or(false) {
                match self.delta(sym, &t) {
                    Ok((d, px, fee, fin)) => {
                        if d > 0.0 {
                            self.apply_exit_fill(sym, d, px, fee);
                            if let Some(q) = self.st.positions.get_mut(sym) {
                                if let Some(tt) = q.take.as_mut() {
                                    tt.filled += d;
                                    tt.filled_cost += d * px;
                                    tt.fee += fee;
                                }
                            }
                        }
                        let left = self.st.positions.get(sym).map(|q| q.qty).unwrap_or(0.0);
                        if left <= 0.0 {
                            let tpx = if t.filled + d > 0.0 { Some((t.filled_cost + d * px) / (t.filled + d)) } else { None };
                            self.finish(sym, "take", tpx, None, now_ms, rep);
                            return;
                        }
                        if fin {
                            // цель снята площадкой или исполнена частично
                            // и закрыта — поставится заново от средней
                            if let Some(q) = self.st.positions.get_mut(sym) {
                                q.take = None;
                            }
                        }
                    }
                    Err(e) => self.last_error = Some(format!("цель {sym}: {e}")),
                }
            }
        }
        if rung_filled {
            self.replace_take(sym, now_ms);
        }
    }

    /// После рунга цель переезжает: старая снимается (с учётом того,
    /// что успела исполниться), новая ставится от новой средней.
    fn replace_take(&mut self, sym: &str, now_ms: i64) {
        let Some(t) = self.st.positions.get(sym).and_then(|p| p.take.clone()) else {
            self.place_take(sym, now_ms);
            return;
        };
        let _ = self.ex.cancel(sym, &t.id);
        if let Ok((d, px, fee, _)) = self.delta(sym, &t) {
            if d > 0.0 {
                self.apply_exit_fill(sym, d, px, fee);
            }
        }
        if let Some(p) = self.st.positions.get_mut(sym) {
            p.take = None;
        }
        self.place_take(sym, now_ms);
    }

    // --- сверка ----------------------------------------------------------

    fn reconcile(&mut self, now_ms: i64, rep: &mut LTick) -> Result<(), String> {
        if self.st.positions.is_empty() {
            return Ok(());
        }
        let exch = self
            .ex
            .positions()
            .map_err(|e| format!("сверка: позиции не читаются: {e}"))?;
        let syms: Vec<String> = self.st.positions.keys().cloned().collect();
        for sym in syms {
            let Some(p) = self.st.positions.get(&sym).cloned() else { continue };
            let want_long = p.long();
            let theirs: f64 = exch
                .iter()
                .filter(|e| e.sym == sym && (e.side == crate::events::Side::Long) == want_long)
                .map(|e| e.qty)
                .sum();
            if (theirs - p.qty).abs() < p.step * 0.5 {
                continue;
            }
            // Расхождение — сперва все заявки имени: частичное исполнение
            // лежащей заявки законно и видно только по её статусу.
            self.poll_sym(&sym, None, now_ms, rep);
            let Some(p) = self.st.positions.get(&sym).cloned() else { continue };
            if (theirs - p.qty).abs() < p.step * 0.5 {
                continue;
            }
            if theirs <= 0.0 {
                // Позиции на бирже нет — закрыта мимо исполнителя
                // (ликвидация, вручную). Деньги знает только биржа.
                let money = self
                    .ex
                    .closed_pnl(&sym, p.opened_ms, now_ms)
                    .ok()
                    .filter(|l| !l.is_empty())
                    .map(|l| l.iter().map(|(_, x)| x).sum::<f64>());
                if let Some(q) = self.st.positions.get_mut(&sym) {
                    // деньги — с биржи (уже нетто): реализованное и
                    // комиссии позиции заменяются её числом
                    if let Some(m) = money {
                        q.realized = m;
                        q.fees = 0.0;
                    } else {
                        q.realized = 0.0;
                        q.fees = 0.0;
                    }
                    q.qty = 0.0;
                    q.cost = 0.0;
                }
                let why = if money.is_some() {
                    "позиция закрыта вне исполнителя (биржей или вручную); деньги — closed-pnl биржи".to_string()
                } else {
                    "позиция закрыта вне исполнителя; денег биржа не отдала — записан ноль с этой оговоркой".to_string()
                };
                self.finish(&sym, "mismatch", None, Some(why), now_ms, rep);
                continue;
            }
            let why = format!("сверка {sym}: у исполнителя {}, у биржи {theirs}", p.qty);
            self.event(
                now_ms,
                "mismatch",
                json!({"sym": sym, "side": p.side, "pos_at": p.decided_at, "reason": why}),
            );
            self.st.paused = Some(why);
            // ведём то, что держит биржа: закрытие reduceOnly по её числу
            if let Some(q) = self.st.positions.get_mut(&sym) {
                let avg = q.avg();
                q.qty = theirs;
                q.cost = avg * theirs;
            }
        }
        Ok(())
    }

    // --- выходы -----------------------------------------------------------

    fn check_exits(&mut self, now_ms: i64, rep: &mut LTick) {
        if self.st.positions.is_empty() {
            return;
        }
        let syms: Vec<String> = self.st.positions.keys().cloned().collect();
        let quotes = match self.ex.tickers(&syms) {
            Ok(q) => q,
            Err(e) => {
                self.last_error = Some(format!("котировки не читаются: {e}"));
                return;
            }
        };
        for sym in syms {
            let Some(p) = self.st.positions.get(&sym).cloned() else { continue };
            if let Some(r) = p.closing.clone() {
                self.close(&sym, &r, now_ms, rep);
                continue;
            }
            if now_ms >= p.term_ms && p.term_ms > 0 {
                self.close(&sym, "term", now_ms, rep);
                continue;
            }
            let Some(&(bid, ask)) = quotes.get(&sym) else { continue };
            if let Some(fl) = p.floor_px() {
                let hit = if p.long() { bid > 0.0 && bid <= fl } else { ask > 0.0 && ask >= fl };
                if hit {
                    self.close(&sym, "floor", now_ms, rep);
                }
            }
        }
    }

    fn exit_intent(&mut self, it: &Intent, now_ms: i64, rep: &mut LTick) {
        let Some(sym) = it.sym.clone() else { return };
        let Some(p) = self.st.positions.get(&sym) else { return };
        if let Some(at) = it.decided_at {
            if (p.decided_at - at).abs() > 1.0 {
                return; // выход другой позиции того же имени
            }
        }
        if self.cfg.dry {
            return;
        }
        let kind = match it.reason.as_deref() {
            Some("market") | None => "market",
            Some("term") => "term",
            Some(_) => "cmd_close",
        };
        self.close(&sym, kind, now_ms, rep);
    }

    /// Закрытие: снять рунги и цель (учтя успевшее исполниться), затем
    /// reduceOnly-IOC с потолком 100 б.п. Недоисполненное — повтор
    /// следующим тактом с той же причиной.
    fn close(&mut self, sym: &str, kind: &str, now_ms: i64, rep: &mut LTick) {
        let Some(p) = self.st.positions.get(sym).cloned() else { return };
        for r in &p.rung_orders {
            let _ = self.ex.cancel(sym, &r.id);
            if let Ok((d, px, fee, _)) = self.delta(sym, r) {
                if d > 0.0 {
                    self.apply_rung_fill(sym, r.rung, d, px, fee, now_ms, rep);
                }
            }
        }
        if let Some(t) = &p.take {
            let _ = self.ex.cancel(sym, &t.id);
            if let Ok((d, px, fee, _)) = self.delta(sym, t) {
                if d > 0.0 {
                    self.apply_exit_fill(sym, d, px, fee);
                }
            }
        }
        if let Some(q) = self.st.positions.get_mut(sym) {
            q.rung_orders.clear();
            q.take = None;
            q.closing = Some(kind.to_string());
        }
        let Some(p) = self.st.positions.get(sym).cloned() else { return };
        if p.qty <= 0.0 {
            self.finish(sym, kind, None, None, now_ms, rep);
            return;
        }
        let (bid, ask) = match self.ex.best_prices(sym) {
            Ok(x) => x,
            Err(e) => {
                self.last_error = Some(format!("выход {sym}: цены не читаются, повтор: {e}"));
                return;
            }
        };
        let mid = (bid + ask) / 2.0;
        let buy = !p.long();
        let px = cap_price(mid, buy, EXIT_CAP_BP, p.tick);
        let q = ceil_step(p.qty, p.step);
        let link = format!("ld-x-{}-{}", sym, now_ms);
        let oid = match self.place(
            sym,
            p.long(),
            buy,
            &fmt_step(q, p.step),
            &fmt_step(px, p.tick),
            "IOC",
            &link,
            true,
        ) {
            Ok(id) => id,
            Err(e) => {
                self.event(
                    now_ms,
                    "reject",
                    json!({"sym": sym, "side": p.side, "pos_at": p.decided_at,
                           "reason": format!("выход ({kind}) отвергнут: {e} — повтор следующим тактом")}),
                );
                return;
            }
        };
        match self.ex.order_status(sym, &oid) {
            Ok(s) if s.filled_qty > 0.0 => {
                self.apply_exit_fill(sym, s.filled_qty, s.avg_px, s.fee_usd);
                let left = self.st.positions.get(sym).map(|q| q.qty).unwrap_or(0.0);
                if left <= 0.0 {
                    self.finish(sym, kind, Some(s.avg_px), None, now_ms, rep);
                }
            }
            Ok(_) => self.last_error = Some(format!("выход {sym} ({kind}): IOC не исполнилась в потолке, повтор")),
            Err(e) => self.last_error = Some(format!("выход {sym}: статус не читается: {e}")),
        }
    }
}

fn wall_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

/// Цикл демона: такт раз в `interval_sec`.
pub fn run_loop<E: Exchange>(mut lx: Ladder<E>, interval_sec: u64) -> ! {
    let mut said: Option<String> = None;
    loop {
        if lx.cfg.stop().exists() {
            let _ = std::fs::remove_file(lx.cfg.stop());
            lx.save();
            eprintln!("исполнитель Ladder: мягкая остановка по файлу STOP");
            let _ = std::fs::remove_file(lx.cfg.pid());
            std::process::exit(0);
        }
        let rep = lx.tick(wall_ms());
        let now = lx.last_error.clone();
        if now != said {
            if let Some(e) = &now {
                eprintln!("исполнитель Ladder: {e}");
            }
            said = now;
        }
        if rep.opened + rep.closed + rep.rejected > 0 {
            eprintln!(
                "такт: входов {}, закрытий {}, отказов {}, рунгов {}",
                rep.opened, rep.closed, rep.rejected, rep.rungs
            );
        }
        std::thread::sleep(std::time::Duration::from_secs(interval_sec.max(1)));
    }
}
