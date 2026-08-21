//! Живой исполнитель — этапы X1–X3 спеки 12.
//!
//! Замер МЕХАНИКИ, не заработка: правила книги не меняются ни на
//! бит — решения принимает Python-сканер и записывает их событиями,
//! исполнитель лишь превращает уже записанные решения в заявки.
//! Второй копии решающей логики здесь нет намеренно: продублированное
//! в Rust правило стопа однажды разошлось бы со сканером, и сверка
//! ловила бы расхождения, которых никто не совершал (так умер движок
//! v1, и так дважды расходились нули и загрузчики этого проекта).
//!
//! Исполнение по спеке 12 §3:
//! - вход и принудительные выходы — IOC-лимит с потолком цены
//!   (30 б.п. от середины; выход по стопу — 100 б.п.): модель считает
//!   их тейкерскими, потолок не даёт исполниться в разрыве;
//! - цель — лежащая лимитка на уровне обещания С МОМЕНТА ВХОДА:
//!   первая живая проверка правила v13 «сквозной проход исполняет по
//!   уровню»;
//! - не исполнившаяся в потолке IOC — записанный отказ, не молчаливый
//!   повтор; повтор выхода идёт следующим тактом и виден в журнале.
//!
//! Сверка §4: на каждом такте позиции биржи сравниваются с выводом из
//! журнала. ЛЮБОЕ расхождение — остановка: свои заявки снимаются,
//! позиции НЕ трогаются (наше представление о них уже неверно, и
//! автоматика на неверном состоянии могла бы открывать, а не
//! закрывать; reduceOnly страхует, но решает владелец).
//!
//! Остановки §5 (все — до прогона): день хуже −15 $, итог −45 $, три
//! отказа подряд, файл KILL, молчание часового цикла дольше 3 ч,
//! расхождение с биржей. После KILL не совершается НИЧЕГО — даже
//! отмен: аварийный выключатель значит «руки прочь», владелец может
//! разбирать счёт руками. Прочие остановки закрывают позиции
//! reduceOnly-IOC: позиция без работающего сканера не управляется
//! никем, а ограничитель убытка у этой книги — размер, не заявка.
//!
//! Состояние выводится из журнала (write-ahead, тот же формат, что у
//! тени) плюс биржи: точное количество знает только она, и после
//! перезапуска оно берётся у неё — при условии, что стороны и имена
//! сошлись с журналом, иначе остановка.

use crate::engine;
use crate::events::{Event, Side};
use crate::journal::Journal;
use crate::picks;
use serde::Deserialize;
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

// --- биржа как трейт ---------------------------------------------------

/// Справочник инструмента: (шаг цены, шаг объёма, мин. лот,
/// мин. нотионал).
#[derive(Clone, Copy, Debug)]
pub struct Instrument {
    pub tick: f64,
    pub step: f64,
    pub min_qty: f64,
    pub min_notional: f64,
}

/// Статус заявки, как его отдаёт площадка.
#[derive(Clone, Debug)]
pub struct OrderStatus {
    pub status: String,
    pub filled_qty: f64,
    pub avg_px: f64,
    pub fee_usd: f64,
}

/// Позиция на бирже: имя, сторона, количество.
#[derive(Clone, Debug)]
pub struct ExchPos {
    pub sym: String,
    pub side: Side,
    pub qty: f64,
}

/// Всё, что исполнителю нужно от площадки. Трейт — не архитектурная
/// вежливость: без него логику заявок нельзя прогнать тестами, а
/// правка в непроверяемом месте уже давала ложную тревогу панели
/// (урок `verify_journal`).
pub trait Exchange {
    fn best_prices(&self, symbol: &str) -> Result<(f64, f64), String>;
    fn instrument(&self, symbol: &str) -> Result<Instrument, String>;
    #[allow(clippy::too_many_arguments)]
    fn place_limit(
        &self,
        symbol: &str,
        side: &str,
        qty: &str,
        price: &str,
        tif: &str,
        link_id: &str,
        reduce_only: bool,
    ) -> Result<String, String>;
    fn cancel(&self, symbol: &str, order_id: &str) -> Result<(), String>;
    fn order_status(&self, symbol: &str, order_id: &str) -> Result<OrderStatus, String>;
    fn positions(&self) -> Result<Vec<ExchPos>, String>;
    fn wallet_usdt(&self) -> Result<(f64, f64), String>;
}

impl Exchange for crate::venue::Venue {
    fn best_prices(&self, symbol: &str) -> Result<(f64, f64), String> {
        crate::venue::Venue::best_prices(self, symbol)
    }
    fn instrument(&self, symbol: &str) -> Result<Instrument, String> {
        let (tick, step, min_qty, min_notional) =
            crate::venue::Venue::instrument(self, symbol)?;
        Ok(Instrument { tick, step, min_qty, min_notional })
    }
    fn place_limit(
        &self,
        symbol: &str,
        side: &str,
        qty: &str,
        price: &str,
        tif: &str,
        link_id: &str,
        reduce_only: bool,
    ) -> Result<String, String> {
        crate::venue::Venue::place_limit(
            self, symbol, side, qty, price, tif, link_id, reduce_only,
        )
    }
    fn cancel(&self, symbol: &str, order_id: &str) -> Result<(), String> {
        crate::venue::Venue::cancel(self, symbol, order_id)
    }
    fn order_status(&self, symbol: &str, order_id: &str) -> Result<OrderStatus, String> {
        let (status, filled_qty, avg_px, fee_usd) =
            crate::venue::Venue::order_status(self, symbol, order_id)?;
        Ok(OrderStatus { status, filled_qty, avg_px, fee_usd })
    }
    fn positions(&self) -> Result<Vec<ExchPos>, String> {
        Ok(crate::venue::Venue::positions(self)?
            .into_iter()
            .filter(|(_, _, size, _, _)| *size != 0.0)
            .map(|(sym, side, size, _, _)| ExchPos {
                sym,
                side: if side == "Sell" || side == "short" {
                    Side::Short
                } else {
                    Side::Long
                },
                qty: size,
            })
            .collect())
    }
    fn wallet_usdt(&self) -> Result<(f64, f64), String> {
        crate::venue::Venue::wallet_usdt(self)
    }
}

// --- округления --------------------------------------------------------

/// Вниз к кратному шага. Вверх округлять размер нельзя: нога 30 $ —
/// это потолок забора (10 % капитала), и перешагнувший его размер
/// нарушил бы правило, которое не учится.
pub fn floor_step(v: f64, step: f64) -> f64 {
    if step <= 0.0 {
        return v;
    }
    (v / step + 1e-9).floor() * step
}

pub fn ceil_step(v: f64, step: f64) -> f64 {
    if step <= 0.0 {
        return v;
    }
    (v / step - 1e-9).ceil() * step
}

/// Число знаков после запятой у шага: печать заявки обязана нести
/// ровно ту точность, которой шаг требует, — площадка отвергает и
/// лишние знаки, и неровное число.
pub fn step_decimals(step: f64) -> usize {
    let mut s = step;
    let mut d = 0usize;
    while d < 10 && (s - s.round()).abs() > 1e-9 {
        s *= 10.0;
        d += 1;
    }
    d
}

pub fn fmt_step(v: f64, step: f64) -> String {
    format!("{:.*}", step_decimals(step), v)
}

/// Потолок цены входа/выхода: покупка — не дороже середины плюс
/// `cap_bp`, продажа — не дешевле середины минус `cap_bp`. Округление
/// ВНУТРЬ потолка: заявка, вышедшая за него округлением, платила бы
/// больше объявленного.
pub fn cap_price(mid: f64, buy: bool, cap_bp: f64, tick: f64) -> f64 {
    if buy {
        floor_step(mid * (1.0 + cap_bp / 1e4), tick)
    } else {
        ceil_step(mid * (1.0 - cap_bp / 1e4), tick)
    }
}

// --- события книги -----------------------------------------------------

/// Живой вход сканера (`entries_live.jsonl`). Ожидания пути — б.п. от
/// цены события: из них строится уровень цели для лежащей лимитки.
#[derive(Deserialize, Clone, Debug)]
pub struct EntryEv {
    pub arm: Option<String>,
    pub hour: String,
    pub sym: String,
    pub side: String,
    pub px: f64,
    #[serde(default)]
    pub mae: Option<f64>,
    #[serde(default)]
    pub mfe: Option<f64>,
    pub at_ts: f64,
}

/// Живой выход сторожа (`exits_live.jsonl`).
#[derive(Deserialize, Clone, Debug)]
pub struct ExitEv {
    pub arm: Option<String>,
    pub hour: String,
    pub sym: String,
    pub side: String,
    pub at_ts: f64,
    pub reason: String,
}

fn side_of(s: &str) -> Option<Side> {
    match s {
        "long" => Some(Side::Long),
        "short" => Some(Side::Short),
        _ => None,
    }
}

fn side_str(s: Side) -> &'static str {
    match s {
        Side::Long => "long",
        Side::Short => "short",
    }
}

/// Ключ позиции — тот же, что у Python-счёта и тени: рука:час:имя:сторона.
pub fn pos_key(arm: &str, hour: &str, sym: &str, side: Side) -> String {
    format!("{arm}:{hour}:{sym}:{}", side_str(side))
}

// --- конфигурация ------------------------------------------------------

pub struct LiveCfg {
    /// Каталог книги (`…/model_sit`).
    pub s8_dir: PathBuf,
    /// Журнал исполнителя — СВОЙ каталог, не журнал тени: тень ведёт
    /// бумажные 3000 $, здесь живые 300, и смесь двух счетов в одном
    /// журнале сделала бы сверку бессмысленной.
    pub journal_dir: PathBuf,
    pub arm: String,
    /// Капитал замера. 300 $ — спека 12 §2; НЕ `trades.START_BALANCE`
    /// (бумажные 3000).
    pub capital_usd: f64,
    /// Потолок на имя — доля капитала (забор, спека 12 §2).
    pub name_cap_share: f64,
    /// Потолок цены IOC от середины, б.п. (§3).
    pub entry_cap_bp: f64,
    /// Потолок цены выхода по стопу (§3): в стрессе середина едет, и
    /// узкий потолок оставил бы позицию незакрытой.
    pub stop_cap_bp: f64,
    /// Остановки §5.
    pub day_stop_usd: f64,
    pub total_stop_usd: f64,
    pub max_rejects: u32,
    pub stale_cycle_h: f64,
    /// Сухой прогон X2: заявки формируются и проверяются по живому
    /// справочнику, но НЕ отправляются; выдуманных исполнений нет —
    /// позиции в сухом прогоне не открываются вовсе.
    pub dry: bool,
}

impl LiveCfg {
    pub fn leg_usd(&self) -> f64 {
        self.capital_usd * self.name_cap_share
    }
    pub fn kill_file(&self) -> PathBuf {
        self.journal_dir.join("KILL")
    }
}

// --- исполнитель -------------------------------------------------------

/// Открытая живая позиция.
#[derive(Clone, Debug)]
pub struct LivePos {
    pub key: String,
    pub sym: String,
    pub side: Side,
    pub qty: f64,
    pub entry_px: f64,
    pub notional_usd: f64,
    pub fee_usd: f64,
    /// Уровень цели — от цены СОБЫТИЯ, не от нашего исполнения:
    /// правило v13 обещает уровень книги, его и проверяем.
    pub target_px: Option<f64>,
    pub target_id: Option<String>,
    pub step: f64,
    pub tick: f64,
    pub opened_at_ms: i64,
}

#[derive(Debug, Default)]
pub struct TickReport {
    pub opened: u32,
    pub closed: u32,
    pub rejected: u32,
    pub halted: Option<String>,
}

pub struct Executor<E: Exchange> {
    pub cfg: LiveCfg,
    ex: E,
    jr: Journal,
    /// Решения, уже принятые к рассмотрению (ключ + секунда события):
    /// выводится из журнала, дважды одно событие не исполняется.
    seen: BTreeSet<String>,
    pub pos: BTreeMap<String, LivePos>,
    rejects_row: u32,
    halted: Option<String>,
    /// Остановка с закрытием позиций (лимиты §5) — или без него
    /// (расхождение с биржей: состоянию верить нельзя).
    halt_flatten: bool,
    realized_total: f64,
    realized_by_day: BTreeMap<String, f64>,
    /// Позиции, чей выход уже записан книгой, но IOC не исполнился:
    /// повтор следующим тактом, каждый — строкой журнала.
    exit_pending: BTreeMap<String, String>,
}

impl<E: Exchange> Executor<E> {
    /// Поднять исполнителя: журнал перечитывается, позиции сверяются с
    /// биржей (точное количество знает она), решения без исхода
    /// закрываются отказом — вход привязан к секунде, и исполнять его
    /// после перезапуска значило бы торговать прошлое.
    pub fn open(cfg: LiveCfg, ex: E, clear_halt: bool) -> Result<Executor<E>, String> {
        engine::fresh_journal_on_rules_change(&cfg.s8_dir, &cfg.journal_dir)
            .map_err(|e| format!("смена правил книги: {e}"))?;
        std::fs::create_dir_all(&cfg.journal_dir)
            .map_err(|e| format!("каталог журнала: {e}"))?;
        let (mut jr, records, _) =
            Journal::open(&cfg.journal_dir).map_err(|e| format!("журнал: {e}"))?;

        let mut seen = BTreeSet::new();
        let mut open_ev: BTreeMap<String, (String, Side, f64, Option<f64>, f64, i64)> =
            BTreeMap::new();
        let mut pending: BTreeMap<String, (String, Side, i64)> = BTreeMap::new();
        let mut halted = None;
        let mut realized_total = 0.0;
        let mut realized_by_day: BTreeMap<String, f64> = BTreeMap::new();
        for r in &records {
            match &r.event {
                Event::Decision { arm, hour, sym, side, at_ms, .. } => {
                    let k = pos_key(arm, hour, sym, *side);
                    seen.insert(format!("{k}@{at_ms}"));
                    pending.insert(k, (sym.clone(), *side, *at_ms));
                }
                Event::Reject { sym, side, at_ms, .. } => {
                    // Отказ закрывает висящее решение этого имени.
                    let gone: Vec<String> = pending
                        .iter()
                        .filter(|(_, (s, sd, at))| {
                            s == sym && sd == side && *at <= *at_ms
                        })
                        .map(|(k, _)| k.clone())
                        .collect();
                    for k in gone {
                        pending.remove(&k);
                    }
                }
                Event::Open { pos, sym, side, notional_usd, entry_px, fee_usd, at_ms, .. } => {
                    pending.remove(pos);
                    open_ev.insert(
                        pos.clone(),
                        (sym.clone(), *side, *notional_usd, *entry_px, *fee_usd, *at_ms),
                    );
                }
                Event::Close { pos, pnl_usd, at_ms, .. } => {
                    open_ev.remove(pos);
                    realized_total += pnl_usd;
                    *realized_by_day
                        .entry(crate::journal::utc_day(*at_ms))
                        .or_insert(0.0) += pnl_usd;
                }
                Event::Kill { on, reason, .. } => {
                    halted = if *on { Some(reason.clone()) } else { None };
                }
            }
        }

        if clear_halt {
            if let Some(r) = &halted {
                jr.append(Event::Kill {
                    on: false,
                    reason: format!("остановка снята владельцем (была: {r})"),
                    at_ms: now_ms_wall(),
                })
                .map_err(|e| format!("журнал: {e}"))?;
                halted = None;
            }
        }

        // Решение без исхода — оборванный перезапуском вход. Заявка
        // могла и уйти: если биржа держит позицию, которой нет в
        // журнале, это поймает первая же сверка. Сам вход пропускается:
        // он привязан к секунде события.
        for (k, (sym, side, _)) in pending {
            jr.append(Event::Reject {
                sym,
                side,
                reason: format!(
                    "{k}: решение оборвано перезапуском — вход пропущен"
                ),
                at_ms: now_ms_wall(),
            })
            .map_err(|e| format!("журнал: {e}"))?;
        }

        // Количество и цену держит биржа; журнал держит состав. Пока
        // стороны и имена сходятся — берём её числа, иначе первая
        // сверка остановит.
        let exch = ex.positions()?;
        let mut pos = BTreeMap::new();
        for (key, (sym, side, notional, entry_px, fee, at)) in &open_ev {
            let found = exch
                .iter()
                .find(|p| p.sym == *sym && p.side == *side);
            let (qty, tick, step) = match found {
                Some(p) => {
                    let ins = ex.instrument(sym)?;
                    (p.qty, ins.tick, ins.step)
                }
                // Биржа позиции не знает — количество нулевое; сверка
                // первого такта объявит расхождение и остановит.
                None => (0.0, 0.0, 0.0),
            };
            let entry = entry_px.unwrap_or(0.0);
            pos.insert(
                key.clone(),
                LivePos {
                    key: key.clone(),
                    sym: sym.clone(),
                    side: *side,
                    qty,
                    entry_px: entry,
                    notional_usd: *notional,
                    fee_usd: *fee,
                    target_px: None,
                    target_id: None,
                    step,
                    tick,
                    opened_at_ms: *at,
                },
            );
        }

        Ok(Executor {
            cfg,
            ex,
            jr,
            seen,
            pos,
            rejects_row: 0,
            halted,
            halt_flatten: false,
            realized_total,
            realized_by_day,
            exit_pending: BTreeMap::new(),
        })
    }

    pub fn is_halted(&self) -> Option<&String> {
        self.halted.as_ref()
    }

    fn append(&mut self, ev: Event) {
        if let Err(e) = self.jr.append(ev) {
            // Журнал — write-ahead: не записали, значит не действуем.
            eprintln!("журнал не пишется: {e}");
            self.halted = Some(format!("журнал не пишется: {e}"));
        }
    }

    fn halt(&mut self, reason: String, flatten: bool, now_ms: i64) {
        eprintln!("ОСТАНОВКА: {reason}");
        self.append(Event::Kill { on: true, reason: reason.clone(), at_ms: now_ms });
        self.halted = Some(reason);
        self.halt_flatten = flatten;
        // Свои лежащие цели снимаются при любой остановке, кроме KILL
        // (KILL проверяется раньше и сюда не доходит): лимитка,
        // исполнившаяся при молчащем исполнителе, углубила бы
        // расхождение.
        let ids: Vec<(String, String)> = self
            .pos
            .values()
            .filter_map(|p| p.target_id.clone().map(|id| (p.sym.clone(), id)))
            .collect();
        for (sym, id) in ids {
            if let Err(e) = self.ex.cancel(&sym, &id) {
                eprintln!("не снялась цель {sym} {id}: {e}");
            }
        }
        for p in self.pos.values_mut() {
            p.target_id = None;
        }
    }

    /// Один такт. Порядок существенен: KILL раньше всего (после него
    /// не совершается ничего); ОБНАРУЖЕНИЕ исполнившихся целей раньше
    /// сверки — лежащая лимитка законно исполняется между тактами, и
    /// сверка, идущая первой, кричала бы «расхождение» на каждом
    /// тейке (поймано тестом до первого живого прогона); сверка
    /// раньше действий (действия на разъехавшемся состоянии множат
    /// расхождение); выходы раньше входов (освобождают места и
    /// деньги).
    pub fn tick(&mut self, now_ms: i64) -> TickReport {
        let mut rep = TickReport::default();
        if self.cfg.kill_file().exists() {
            rep.halted = Some("KILL".into());
            self.write_status(now_ms, Some("файл KILL — не совершается ничего"));
            return rep;
        }
        if self.halted.is_some() {
            if self.halt_flatten && !self.pos.is_empty() {
                self.flatten(now_ms, &mut rep);
            }
            rep.halted = self.halted.clone();
            self.write_status(now_ms, None);
            return rep;
        }

        // Только чтение статусов своих заявок и записи закрытий —
        // безопасно и на разъехавшемся состоянии.
        self.discover_target_fills(now_ms, &mut rep);

        if let Err(e) = self.reconcile(now_ms) {
            self.halt(e, false, now_ms);
            rep.halted = self.halted.clone();
            self.write_status(now_ms, None);
            return rep;
        }

        if let Some(r) = self.limits_breached(now_ms) {
            self.halt(r, true, now_ms);
            self.flatten(now_ms, &mut rep);
            rep.halted = self.halted.clone();
            self.write_status(now_ms, None);
            return rep;
        }

        self.process_exits(now_ms, &mut rep);
        self.process_entries(now_ms, &mut rep);
        self.ensure_targets(now_ms);

        if self.rejects_row >= self.cfg.max_rejects {
            self.halt(
                format!("{} отказов подряд (§5)", self.rejects_row),
                true,
                now_ms,
            );
            self.flatten(now_ms, &mut rep);
        }
        rep.halted = self.halted.clone();
        self.write_status(now_ms, None);
        rep
    }

    // --- сверка §4 ------------------------------------------------------

    fn reconcile(&mut self, _now_ms: i64) -> Result<(), String> {
        let exch = self.ex.positions().map_err(|e| format!("сверка: позиции не читаются: {e}"))?;
        let mut ours: BTreeMap<(String, String), f64> = BTreeMap::new();
        for p in self.pos.values() {
            *ours
                .entry((p.sym.clone(), side_str(p.side).into()))
                .or_insert(0.0) += p.qty;
        }
        let mut theirs: BTreeMap<(String, String), f64> = BTreeMap::new();
        for p in &exch {
            *theirs
                .entry((p.sym.clone(), side_str(p.side).into()))
                .or_insert(0.0) += p.qty;
        }
        for (k, q) in &ours {
            let t = theirs.get(k).copied().unwrap_or(0.0);
            if (t - q).abs() > 1e-9 {
                return Err(format!(
                    "сверка: {} {}: у нас {q}, у биржи {t}",
                    k.0, k.1
                ));
            }
        }
        for (k, t) in &theirs {
            if !ours.contains_key(k) {
                return Err(format!(
                    "сверка: биржа держит {} {} ({t}), журнал о ней не знает",
                    k.0, k.1
                ));
            }
        }
        Ok(())
    }

    // --- остановки §5 ---------------------------------------------------

    fn limits_breached(&self, now_ms: i64) -> Option<String> {
        let today = crate::journal::utc_day(now_ms);
        let day = self.realized_by_day.get(&today).copied().unwrap_or(0.0);
        if day <= -self.cfg.day_stop_usd {
            return Some(format!(
                "день {today}: {day:+.2} $ хуже предела −{:.0} $ (§5)",
                self.cfg.day_stop_usd
            ));
        }
        if self.realized_total <= -self.cfg.total_stop_usd {
            return Some(format!(
                "итог {:+.2} $ хуже предела −{:.0} $ (§5)",
                self.realized_total, self.cfg.total_stop_usd
            ));
        }
        let man = self.cfg.s8_dir.join("manifest.json");
        if let Ok(md) = std::fs::metadata(&man) {
            if let Ok(mt) = md.modified() {
                let age_h = std::time::SystemTime::now()
                    .duration_since(mt)
                    .map(|d| d.as_secs_f64() / 3600.0)
                    .unwrap_or(0.0);
                if age_h > self.cfg.stale_cycle_h {
                    return Some(format!(
                        "часовой цикл молчит {age_h:.1} ч при пределе {} ч (§5) — позиции без сканера не управляет никто",
                        self.cfg.stale_cycle_h
                    ));
                }
            }
        }
        None
    }

    // --- закрытие всего -------------------------------------------------

    fn flatten(&mut self, now_ms: i64, rep: &mut TickReport) {
        let keys: Vec<String> = self.pos.keys().cloned().collect();
        for k in keys {
            self.close_pos(
                &k,
                "остановка §5 — принудительное закрытие",
                self.cfg.stop_cap_bp,
                now_ms,
                rep,
                None,
            );
        }
    }

    // --- цель: лежащая лимитка (правило v13) ----------------------------

    /// Цель ставится с входа и переставляется, пока не встанет: позиция
    /// без лежащей цели проверяет не то правило, которым живёт книга.
    fn ensure_targets(&mut self, _now_ms: i64) {
        if self.cfg.dry {
            return;
        }
        let need: Vec<String> = self
            .pos
            .values()
            .filter(|p| p.target_id.is_none() && p.target_px.is_some() && p.qty > 0.0)
            .map(|p| p.key.clone())
            .collect();
        for k in need {
            let p = self.pos.get(&k).cloned().expect("pos");
            let level = p.target_px.expect("target_px");
            let side = match p.side {
                Side::Long => "Sell",
                Side::Short => "Buy",
            };
            let link = format!("tp-{}-{}", p.sym, p.opened_at_ms);
            match self.ex.place_limit(
                &p.sym,
                side,
                &fmt_step(p.qty, p.step),
                &fmt_step(level, p.tick),
                "GTC",
                &link,
                true,
            ) {
                Ok(id) => {
                    if let Some(q) = self.pos.get_mut(&k) {
                        q.target_id = Some(id);
                    }
                }
                Err(e) => eprintln!(
                    "цель {} @ {level} не встала (повтор следующим тактом): {e}",
                    p.sym
                ),
            }
        }
    }

    /// Лимитка цели могла исполниться раньше, чем сторож записал
    /// событие, — биржа узнаёт первой. Обнаруженное исполнение
    /// закрывает позицию по фактической цене заявки.
    fn discover_target_fills(&mut self, now_ms: i64, rep: &mut TickReport) {
        let with_target: Vec<(String, String, String)> = self
            .pos
            .values()
            .filter_map(|p| {
                p.target_id
                    .clone()
                    .map(|id| (p.key.clone(), p.sym.clone(), id))
            })
            .collect();
        for (key, sym, id) in with_target {
            match self.ex.order_status(&sym, &id) {
                Ok(st) if st.status == "Filled" => {
                    self.record_close(
                        &key,
                        st.avg_px,
                        st.fee_usd,
                        "цена дошла до обещанной цели — лимитка исполнилась",
                        now_ms,
                        rep,
                    );
                }
                Ok(_) => {}
                Err(e) => eprintln!("статус цели {sym} {id}: {e}"),
            }
        }
    }

    // --- выходы ---------------------------------------------------------

    fn process_exits(&mut self, now_ms: i64, rep: &mut TickReport) {
        // Повторы прошлых тактов — первыми: их выход уже записан книгой.
        let retry: Vec<(String, String)> = self
            .exit_pending
            .iter()
            .map(|(k, r)| (k.clone(), r.clone()))
            .collect();
        for (k, reason) in retry {
            if self.pos.contains_key(&k) {
                self.close_pos(&k, &reason, self.cfg.stop_cap_bp, now_ms, rep, None);
            } else {
                self.exit_pending.remove(&k);
            }
        }

        let events: Vec<ExitEv> =
            picks::read_lines(&self.cfg.s8_dir.join("exits_live.jsonl"));
        for ev in events {
            let arm = ev.arm.clone().unwrap_or_else(|| "gbm".into());
            if arm != self.cfg.arm {
                continue;
            }
            let Some(side) = side_of(&ev.side) else { continue };
            let key = pos_key(&arm, &ev.hour, &ev.sym, side);
            if !self.pos.contains_key(&key) {
                continue; // закрыта раньше либо вход был отвергнут
            }
            let is_target = ev.reason.contains("дошла до обещанной цели");
            if is_target {
                self.close_via_target(&key, now_ms, rep);
            } else {
                self.close_pos(
                    &key,
                    &ev.reason,
                    self.cfg.stop_cap_bp,
                    now_ms,
                    rep,
                    None,
                );
            }
        }

        // Часовые причины (разворот прогноза, предел возраста,
        // страховка уровней) приходят строками разбора, а не
        // событиями сторожа.
        let reviews = picks::load_reviews(&self.cfg.s8_dir, &self.cfg.arm);
        let open_keys: Vec<String> = self.pos.keys().cloned().collect();
        for key in open_keys {
            let p = match self.pos.get(&key) {
                Some(p) => p.clone(),
                None => continue,
            };
            let parts: Vec<&str> = key.splitn(4, ':').collect();
            if parts.len() != 4 {
                continue;
            }
            let hour = parts[1].to_string();
            if let Some(row) = reviews.get(&(hour, p.sym.clone(), p.side)) {
                let reason = row
                    .reason
                    .clone()
                    .unwrap_or_else(|| "разбор закрыл позицию".into());
                if reason.contains("дошла до обещанной цели") {
                    self.close_via_target(&key, now_ms, rep);
                } else {
                    let cap = if reason.contains("против") {
                        self.cfg.stop_cap_bp
                    } else {
                        self.cfg.entry_cap_bp
                    };
                    self.close_pos(&key, &reason, cap, now_ms, rep, None);
                }
            }
        }
    }

    /// Книга записала «дошла до цели». Если наша лимитка исполнилась —
    /// закрытие уже по её цене; если НЕТ — правило v13 разошлось с
    /// биржей, и это главный замер X3: расхождение уезжает в причину
    /// закрытия словами, позиция закрывается IOC.
    fn close_via_target(&mut self, key: &str, now_ms: i64, rep: &mut TickReport) {
        let p = match self.pos.get(key) {
            Some(p) => p.clone(),
            None => return,
        };
        if let Some(id) = &p.target_id {
            match self.ex.order_status(&p.sym, id) {
                Ok(st) if st.status == "Filled" => {
                    self.record_close(
                        key,
                        st.avg_px,
                        st.fee_usd,
                        "цена дошла до обещанной цели — лимитка исполнилась",
                        now_ms,
                        rep,
                    );
                    return;
                }
                Ok(st) => {
                    if let Err(e) = self.ex.cancel(&p.sym, id) {
                        eprintln!("цель {} не снялась: {e}", p.sym);
                    }
                    if let Some(q) = self.pos.get_mut(key) {
                        q.target_id = None;
                        q.qty -= st.filled_qty;
                        // Частично исполненная цель уже вернула часть.
                    }
                    self.close_pos(
                        key,
                        "книга дошла до цели, лимитка на уровне НЕ исполнилась — правило v13 разошлось",
                        self.cfg.entry_cap_bp,
                        now_ms,
                        rep,
                        None,
                    );
                    return;
                }
                Err(e) => eprintln!("статус цели {}: {e}", p.sym),
            }
        }
        self.close_pos(
            key,
            "книга дошла до цели, лежащей лимитки не было — правило v13 не проверено этой сделкой",
            self.cfg.entry_cap_bp,
            now_ms,
            rep,
            None,
        );
    }

    /// Принудительное закрытие reduceOnly-IOC с потолком цены. Не
    /// исполнилось — записанный отказ и повтор следующим тактом.
    fn close_pos(
        &mut self,
        key: &str,
        reason: &str,
        cap_bp: f64,
        now_ms: i64,
        rep: &mut TickReport,
        qty_override: Option<f64>,
    ) {
        let p = match self.pos.get(key) {
            Some(p) => p.clone(),
            None => return,
        };
        if let Some(id) = &p.target_id {
            if let Err(e) = self.ex.cancel(&p.sym, id) {
                eprintln!("цель {} перед закрытием не снялась: {e}", p.sym);
            }
            if let Some(q) = self.pos.get_mut(key) {
                q.target_id = None;
            }
        }
        let qty = qty_override.unwrap_or(p.qty);
        if qty <= 0.0 {
            // Нечего закрывать (нулевое количество после перезапуска
            // ловит сверка) — позиция снимается без заявки.
            self.record_close(key, p.entry_px, 0.0, reason, now_ms, rep);
            return;
        }
        let (bid, ask) = match self.ex.best_prices(&p.sym) {
            Ok(x) => x,
            Err(e) => {
                eprintln!("цены {} не читаются, выход повторится: {e}", p.sym);
                self.exit_pending.insert(key.into(), reason.into());
                return;
            }
        };
        let mid = (bid + ask) / 2.0;
        let buy = p.side == Side::Short;
        let px = cap_price(mid, buy, cap_bp, p.tick);
        let link = format!("cl-{}-{}", p.sym, now_ms);
        let res = self.ex.place_limit(
            &p.sym,
            if buy { "Buy" } else { "Sell" },
            &fmt_step(qty, p.step),
            &fmt_step(px, p.tick),
            "IOC",
            &link,
            true,
        );
        let oid = match res {
            Ok(id) => id,
            Err(e) => {
                self.reject_exit(key, &p, &format!("{reason} — заявка выхода отвергнута: {e}"), now_ms, rep);
                return;
            }
        };
        match self.ex.order_status(&p.sym, &oid) {
            Ok(st) if st.filled_qty + 1e-12 >= qty => {
                self.rejects_row = 0;
                self.record_close(key, st.avg_px, st.fee_usd, reason, now_ms, rep);
            }
            Ok(st) if st.filled_qty > 0.0 => {
                // Часть закрылась: количество уменьшается, остаток
                // повторяется следующим тактом. Отказом не считается —
                // биржа исполнила, сколько было в потолке.
                self.rejects_row = 0;
                if let Some(q) = self.pos.get_mut(key) {
                    q.qty -= st.filled_qty;
                    q.fee_usd += st.fee_usd;
                }
                self.exit_pending.insert(key.into(), reason.into());
            }
            Ok(_) => {
                self.reject_exit(
                    key,
                    &p,
                    &format!("{reason} — IOC не исполнилась в потолке {cap_bp} б.п."),
                    now_ms,
                    rep,
                );
            }
            Err(e) => {
                self.reject_exit(
                    key,
                    &p,
                    &format!("{reason} — статус заявки не читается: {e}"),
                    now_ms,
                    rep,
                );
            }
        }
    }

    fn reject_exit(
        &mut self,
        key: &str,
        p: &LivePos,
        reason: &str,
        now_ms: i64,
        rep: &mut TickReport,
    ) {
        self.rejects_row += 1;
        rep.rejected += 1;
        self.append(Event::Reject {
            sym: p.sym.clone(),
            side: p.side,
            reason: reason.into(),
            at_ms: now_ms,
        });
        self.exit_pending
            .insert(key.into(), reason.split(" — ").next().unwrap_or(reason).to_string());
    }

    fn record_close(
        &mut self,
        key: &str,
        exit_px: f64,
        exit_fee: f64,
        reason: &str,
        now_ms: i64,
        rep: &mut TickReport,
    ) {
        let Some(p) = self.pos.remove(key) else { return };
        self.exit_pending.remove(key);
        let sign = match p.side {
            Side::Long => 1.0,
            Side::Short => -1.0,
        };
        let gross = if p.entry_px > 0.0 && exit_px > 0.0 {
            sign * (exit_px - p.entry_px) / p.entry_px * p.notional_usd
        } else {
            0.0
        };
        let pnl = gross - p.fee_usd - exit_fee;
        self.append(Event::Close {
            pos: key.into(),
            exit_px: if exit_px > 0.0 { Some(exit_px) } else { None },
            fee_usd: exit_fee,
            pnl_usd: pnl,
            reason: reason.into(),
            at_ms: now_ms,
        });
        self.realized_total += pnl;
        *self
            .realized_by_day
            .entry(crate::journal::utc_day(now_ms))
            .or_insert(0.0) += pnl;
        rep.closed += 1;
    }

    // --- входы ----------------------------------------------------------

    fn process_entries(&mut self, now_ms: i64, rep: &mut TickReport) {
        let events: Vec<EntryEv> =
            picks::read_lines(&self.cfg.s8_dir.join("entries_live.jsonl"));
        for ev in events {
            let arm = ev.arm.clone().unwrap_or_else(|| "gbm".into());
            if arm != self.cfg.arm {
                continue;
            }
            let Some(side) = side_of(&ev.side) else { continue };
            let key = pos_key(&arm, &ev.hour, &ev.sym, side);
            let at_ms = (ev.at_ts * 1000.0) as i64;
            let seen_key = format!("{key}@{at_ms}");
            if self.seen.contains(&seen_key) {
                continue;
            }
            // Write-ahead: решение записано ДО каких-либо действий.
            self.append(Event::Decision {
                arm: arm.clone(),
                hour: ev.hour.clone(),
                sym: ev.sym.clone(),
                side,
                px: Some(ev.px),
                ver: None,
                at_ms,
            });
            self.seen.insert(seen_key);
            self.try_enter(&key, &ev, side, now_ms, rep);
            if self.halted.is_some() {
                return;
            }
        }
    }

    fn reject_entry(&mut self, ev: &EntryEv, side: Side, reason: String, now_ms: i64, rep: &mut TickReport, counts: bool) {
        if counts {
            self.rejects_row += 1;
        }
        rep.rejected += 1;
        self.append(Event::Reject {
            sym: ev.sym.clone(),
            side,
            reason,
            at_ms: now_ms,
        });
    }

    fn try_enter(
        &mut self,
        key: &str,
        ev: &EntryEv,
        side: Side,
        now_ms: i64,
        rep: &mut TickReport,
    ) {
        // Встречный сигнал на удерживаемом имени закрывает позицию и
        // сам не открывается — правило кассы v3 (нетто на бирже).
        let opposite: Option<String> = self
            .pos
            .values()
            .find(|p| p.sym == ev.sym && p.side != side)
            .map(|p| p.key.clone());
        if let Some(vk) = opposite {
            self.close_pos(
                &vk,
                "встречный сигнал закрыл позицию",
                self.cfg.entry_cap_bp,
                now_ms,
                rep,
                None,
            );
            self.reject_entry(
                ev,
                side,
                "встречный сигнал: закрыл позицию, вход не открывался".into(),
                now_ms,
                rep,
                false,
            );
            return;
        }
        if self.pos.values().any(|p| p.sym == ev.sym) {
            self.reject_entry(ev, side, "имя уже в позиции".into(), now_ms, rep, false);
            return;
        }
        let slots = engine::book_mode(&self.cfg.s8_dir)
            .slots
            .unwrap_or(6.0) as usize;
        if self.pos.len() >= slots {
            self.reject_entry(ev, side, format!("все {slots} мест заняты"), now_ms, rep, false);
            return;
        }

        let ins = match self.ex.instrument(&ev.sym) {
            Ok(i) => i,
            Err(e) => {
                self.reject_entry(ev, side, format!("справочник не читается: {e}"), now_ms, rep, true);
                return;
            }
        };
        let (bid, ask) = match self.ex.best_prices(&ev.sym) {
            Ok(x) => x,
            Err(e) => {
                self.reject_entry(ev, side, format!("цены не читаются: {e}"), now_ms, rep, true);
                return;
            }
        };
        let mid = (bid + ask) / 2.0;
        if mid <= 0.0 {
            self.reject_entry(ev, side, "середины нет".into(), now_ms, rep, true);
            return;
        }
        let leg = self.cfg.leg_usd();
        let qty = floor_step(leg / mid, ins.step);
        if qty < ins.min_qty - 1e-12 || qty * mid < ins.min_notional - 1e-9 {
            self.reject_entry(
                ev,
                side,
                format!(
                    "нога {leg:.0} $ меньше минимального лота ({} × {mid} ≥ {} $, мин. лот {})",
                    fmt_step(qty, ins.step), ins.min_notional, ins.min_qty
                ),
                now_ms,
                rep,
                false,
            );
            return;
        }
        let buy = side == Side::Long;
        let px = cap_price(mid, buy, self.cfg.entry_cap_bp, ins.tick);

        // Уровень цели — от цены события (обещание книги, правило v13).
        let target_px = ev.mfe.map(|bp| {
            let raw = ev.px * (1.0 + bp / 1e4);
            if buy {
                // Лонг продаёт выше: округление к потолку внутрь уровня.
                ceil_step(raw, ins.tick)
            } else {
                floor_step(raw, ins.tick)
            }
        });

        if self.cfg.dry {
            self.reject_entry(
                ev,
                side,
                format!(
                    "сухой прогон X2 — заявка сформирована, не отправлена: {} {} {} @ {} IOC (цель {})",
                    if buy { "Buy" } else { "Sell" },
                    ev.sym,
                    fmt_step(qty, ins.step),
                    fmt_step(px, ins.tick),
                    target_px
                        .map(|t| fmt_step(t, ins.tick))
                        .unwrap_or_else(|| "—".into()),
                ),
                now_ms,
                rep,
                false,
            );
            return;
        }

        let link = format!("in-{}-{at}", ev.sym, at = (ev.at_ts * 1000.0) as i64);
        let oid = match self.ex.place_limit(
            &ev.sym,
            if buy { "Buy" } else { "Sell" },
            &fmt_step(qty, ins.step),
            &fmt_step(px, ins.tick),
            "IOC",
            &link,
            false,
        ) {
            Ok(id) => id,
            Err(e) => {
                self.reject_entry(ev, side, format!("заявка входа отвергнута: {e}"), now_ms, rep, true);
                return;
            }
        };
        let st = match self.ex.order_status(&ev.sym, &oid) {
            Ok(s) => s,
            Err(e) => {
                // Заявка ушла, статус неизвестен: исполнение узнает
                // сверка следующего такта — она и остановит, если
                // биржа держит позицию, которой нет в журнале.
                self.reject_entry(ev, side, format!("статус входа не читается: {e}"), now_ms, rep, true);
                return;
            }
        };
        if st.filled_qty <= 0.0 {
            self.reject_entry(
                ev,
                side,
                format!(
                    "IOC не исполнилась в потолке {} б.п. (запрошено {})",
                    self.cfg.entry_cap_bp,
                    fmt_step(qty, ins.step)
                ),
                now_ms,
                rep,
                true,
            );
            return;
        }
        self.rejects_row = 0;
        let notional = st.filled_qty * st.avg_px;
        self.append(Event::Open {
            pos: key.into(),
            sym: ev.sym.clone(),
            side,
            notional_usd: notional,
            entry_px: Some(st.avg_px),
            fee_usd: st.fee_usd,
            partial: st.filled_qty + 1e-12 < qty,
            ver: None,
            at_ms: now_ms,
        });
        self.pos.insert(
            key.into(),
            LivePos {
                key: key.into(),
                sym: ev.sym.clone(),
                side,
                qty: st.filled_qty,
                entry_px: st.avg_px,
                notional_usd: notional,
                fee_usd: st.fee_usd,
                target_px,
                target_id: None,
                step: ins.step,
                tick: ins.tick,
                opened_at_ms: now_ms,
            },
        );
        rep.opened += 1;
    }

    // --- статус ---------------------------------------------------------

    /// Статус — атомарным файлом: полусписанный JSON у читателя был бы
    /// отказом, неотличимым от «исполнитель не работает».
    fn write_status(&mut self, now_ms: i64, note: Option<&str>) {
        let today = crate::journal::utc_day(now_ms);
        let wallet = self.ex.wallet_usdt().ok();
        let positions: Vec<serde_json::Value> = self
            .pos
            .values()
            .map(|p| {
                json!({
                    "key": p.key,
                    "sym": p.sym,
                    "side": side_str(p.side),
                    "qty": p.qty,
                    "entry_px": p.entry_px,
                    "notional_usd": p.notional_usd,
                    "target_px": p.target_px,
                    "target_resting": p.target_id.is_some(),
                })
            })
            .collect();
        let st = json!({
            "at_ms": now_ms,
            "dry": self.cfg.dry,
            "capital_usd": self.cfg.capital_usd,
            "halted": self.halted,
            "note": note,
            "positions": positions,
            "realized_today_usd": self.realized_by_day.get(&today).copied().unwrap_or(0.0),
            "realized_total_usd": self.realized_total,
            "rejects_row": self.rejects_row,
            "wallet": wallet.map(|(eq, bal)| json!({"equity": eq, "balance": bal})),
        });
        let path = self.cfg.journal_dir.join("live_status.json");
        let tmp = self.cfg.journal_dir.join("live_status.json.tmp");
        if std::fs::write(&tmp, serde_json::to_vec_pretty(&st).unwrap_or_default())
            .and_then(|_| std::fs::rename(&tmp, &path))
            .is_err()
        {
            eprintln!("статус не пишется в {}", path.display());
        }
    }
}

fn now_ms_wall() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

/// Цикл демона: такт раз в `interval_sec`, часы пересинхронизируются
/// снаружи (в `main`) — здесь только логика.
pub fn run_loop<E: Exchange>(mut ex: Executor<E>, interval_sec: u64) -> ! {
    loop {
        let now = now_ms_wall();
        let rep = ex.tick(now);
        if let Some(r) = &rep.halted {
            eprintln!("исполнитель остановлен: {r}");
        }
        std::thread::sleep(std::time::Duration::from_secs(interval_sec.max(1)));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn округления_вниз_и_вверх_по_шагу() {
        // Сравнение с допуском: 26 × 0.001 в IEEE754 несёт хвост
        // 2e-18, а на провод число уходит через fmt_step с точностью
        // шага — хвост не доезжает до площадки.
        assert!((floor_step(0.02599, 0.001) - 0.025).abs() < 1e-12);
        assert!((ceil_step(0.02501, 0.001) - 0.026).abs() < 1e-12);
        assert_eq!(fmt_step(ceil_step(0.02501, 0.001), 0.001), "0.026");
        // Ровное число не двигается ни туда, ни сюда.
        assert!((floor_step(0.025, 0.001) - 0.025).abs() < 1e-12);
        assert!((ceil_step(0.025, 0.001) - 0.025).abs() < 1e-12);
    }

    #[test]
    fn печать_несёт_точность_шага() {
        assert_eq!(fmt_step(0.025, 0.001), "0.025");
        assert_eq!(fmt_step(62100.0, 0.1), "62100.0");
        assert_eq!(fmt_step(3.0, 1.0), "3");
        assert_eq!(step_decimals(0.00001), 5);
    }

    #[test]
    fn потолок_цены_округляется_внутрь() {
        // Покупка: mid 1.0000, потолок 30 б.п. = 1.0030 — вниз к тику.
        let px = cap_price(1.0, true, 30.0, 0.0001);
        assert!(px <= 1.0030 + 1e-12, "{px}");
        assert!((px - 1.0030).abs() < 1e-9, "{px}");
        // Продажа: не дешевле 0.9970 — вверх к тику.
        let px = cap_price(1.0, false, 30.0, 0.0001);
        assert!(px >= 0.9970 - 1e-12, "{px}");
        // Грубый тик: покупка НЕ выше потолка даже ценой отступа.
        let px = cap_price(100.0, true, 30.0, 0.5);
        assert!(px <= 100.30, "{px}");
        assert_eq!(px, 100.0);
    }

    #[test]
    fn ключ_позиции_как_у_питона() {
        assert_eq!(
            pos_key("gbm", "2026-08-20-15", "ARBUSDT", Side::Short),
            "gbm:2026-08-20-15:ARBUSDT:short"
        );
    }
}
