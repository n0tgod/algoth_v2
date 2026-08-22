//! X1: исполнитель против подставной биржи.
//!
//! Подставная биржа ведёт себя как настоящая на полных исполнениях:
//! IOC либо исполняется целиком по цене заявки, либо не исполняется
//! вовсе; исполнение создаёт позицию, reduceOnly-закрытие её снимает —
//! иначе сверка §4 не упражнялась бы ни одним тестом.

use bot::events::{Event, Side};
use bot::live::{
    cap_price, pos_key, Exchange, ExchPos, Executor, Instrument, LiveCfg,
    OrderStatus, Resting,
};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::rc::Rc;

// --- подставная биржа --------------------------------------------------

#[derive(Clone, Debug)]
struct Placed {
    sym: String,
    side: String,
    qty: f64,
    px: f64,
    tif: String,
    link: String,
    reduce_only: bool,
    id: String,
}

#[derive(Default)]
struct Inner {
    prices: BTreeMap<String, (f64, f64)>,
    instruments: BTreeMap<String, Instrument>,
    ioc_fills: bool,
    placed: Vec<Placed>,
    cancelled: Vec<(String, String)>,
    positions: Vec<ExchPos>,
    order_states: BTreeMap<String, OrderStatus>,
    resting: Vec<Resting>,
    lev_calls: Vec<String>,
    entry_error: Option<String>,
    next_id: u64,
    fee_bp: f64,
    /// Записи closed-pnl биржи: (имя, момент мс, деньги $).
    closed_pnl: Vec<(String, i64, f64)>,
    closed_pnl_calls: u64,
}

#[derive(Clone)]
struct Mock(Rc<RefCell<Inner>>);

impl Mock {
    fn new() -> Mock {
        Mock(Rc::new(RefCell::new(Inner {
            ioc_fills: true,
            fee_bp: 5.5,
            ..Inner::default()
        })))
    }
    fn with_sym(self, sym: &str, bid: f64, ask: f64, tick: f64, step: f64,
                min_qty: f64, min_notional: f64) -> Mock {
        {
            let mut i = self.0.borrow_mut();
            i.prices.insert(sym.into(), (bid, ask));
            i.instruments.insert(sym.into(), Instrument {
                tick, step, min_qty, min_notional,
            });
        }
        self
    }
    fn set_ioc_fills(&self, on: bool) {
        self.0.borrow_mut().ioc_fills = on;
    }
    fn set_entry_error(&self, e: Option<&str>) {
        self.0.borrow_mut().entry_error = e.map(String::from);
    }
    fn placed(&self) -> Vec<Placed> {
        self.0.borrow().placed.clone()
    }
    fn cancelled(&self) -> Vec<(String, String)> {
        self.0.borrow().cancelled.clone()
    }
    fn push_position(&self, sym: &str, side: Side, qty: f64) {
        self.0.borrow_mut().positions.push(ExchPos {
            sym: sym.into(), side, qty,
        });
    }
    fn set_order(&self, id: &str, st: OrderStatus) {
        self.0.borrow_mut().order_states.insert(id.into(), st);
    }
    fn push_closed_pnl(&self, sym: &str, at_ms: i64, pnl: f64) {
        self.0.borrow_mut().closed_pnl.push((sym.into(), at_ms, pnl));
    }
    fn closed_pnl_calls(&self) -> u64 {
        self.0.borrow().closed_pnl_calls
    }
    fn apply_fill(i: &mut Inner, sym: &str, side: &str, qty: f64, reduce: bool) {
        let long = side == "Buy";
        if reduce {
            let want = if long { Side::Short } else { Side::Long };
            for p in i.positions.iter_mut() {
                if p.sym == sym && p.side == want {
                    p.qty -= qty;
                }
            }
            i.positions.retain(|p| p.qty > 1e-12);
        } else {
            i.positions.push(ExchPos {
                sym: sym.into(),
                side: if long { Side::Long } else { Side::Short },
                qty,
            });
        }
    }
}

impl Exchange for Mock {
    fn best_prices(&self, symbol: &str) -> Result<(f64, f64), String> {
        self.0
            .borrow()
            .prices
            .get(symbol)
            .copied()
            .ok_or_else(|| format!("нет цен {symbol}"))
    }
    fn instrument(&self, symbol: &str) -> Result<Instrument, String> {
        self.0
            .borrow()
            .instruments
            .get(symbol)
            .copied()
            .ok_or_else(|| format!("нет справочника {symbol}"))
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
        let mut i = self.0.borrow_mut();
        if !reduce_only {
            if let Some(e) = i.entry_error.clone() {
                return Err(e);
            }
        }
        i.next_id += 1;
        let id = format!("o{}", i.next_id);
        let q: f64 = qty.parse().map_err(|_| "qty не число")?;
        let px: f64 = price.parse().map_err(|_| "px не число")?;
        i.placed.push(Placed {
            sym: symbol.into(),
            side: side.into(),
            qty: q,
            px,
            tif: tif.into(),
            link: link_id.into(),
            reduce_only,
            id: id.clone(),
        });
        if tif == "IOC" {
            if i.ioc_fills {
                let fee = q * px * i.fee_bp / 1e4;
                i.order_states.insert(id.clone(), OrderStatus {
                    status: "Filled".into(),
                    filled_qty: q,
                    avg_px: px,
                    fee_usd: fee,
                });
                Mock::apply_fill(&mut i, symbol, side, q, reduce_only);
            } else {
                i.order_states.insert(id.clone(), OrderStatus {
                    status: "Cancelled".into(),
                    filled_qty: 0.0,
                    avg_px: 0.0,
                    fee_usd: 0.0,
                });
            }
        } else {
            // Лежащая заявка: стоит, пока тест не решит её судьбу.
            i.order_states.insert(id.clone(), OrderStatus {
                status: "New".into(),
                filled_qty: 0.0,
                avg_px: 0.0,
                fee_usd: 0.0,
            });
        }
        Ok(id)
    }
    fn cancel(&self, symbol: &str, order_id: &str) -> Result<(), String> {
        let mut i = self.0.borrow_mut();
        i.cancelled.push((symbol.into(), order_id.into()));
        if let Some(st) = i.order_states.get_mut(order_id) {
            if st.status == "New" {
                st.status = "Cancelled".into();
            }
        }
        Ok(())
    }
    fn order_status(&self, _symbol: &str, order_id: &str) -> Result<OrderStatus, String> {
        self.0
            .borrow()
            .order_states
            .get(order_id)
            .cloned()
            .ok_or_else(|| format!("нет заявки {order_id}"))
    }
    fn positions(&self) -> Result<Vec<ExchPos>, String> {
        Ok(self.0.borrow().positions.clone())
    }
    fn open_orders(&self) -> Result<Vec<Resting>, String> {
        Ok(self.0.borrow().resting.clone())
    }
    fn set_leverage(&self, symbol: &str, _lev: &str) -> Result<(), String> {
        self.0.borrow_mut().lev_calls.push(symbol.into());
        Ok(())
    }
    fn wallet_usdt(&self) -> Result<(f64, f64), String> {
        Ok((300.0, 300.0))
    }
    fn closed_pnl(
        &self,
        symbol: &str,
        start_ms: i64,
        end_ms: i64,
    ) -> Result<Vec<(i64, f64)>, String> {
        let mut i = self.0.borrow_mut();
        i.closed_pnl_calls += 1;
        Ok(i
            .closed_pnl
            .iter()
            .filter(|(s, t, _)| s == symbol && *t >= start_ms && *t <= end_ms)
            .map(|(_, t, p)| (*t, *p))
            .collect())
    }
}

// --- обвязка -----------------------------------------------------------

struct Fx {
    root: PathBuf,
    s8: PathBuf,
    jr: PathBuf,
}

impl Fx {
    fn new(name: &str) -> Fx {
        let root = std::env::temp_dir()
            .join(format!("live-x1-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let s8 = root.join("model_sit");
        let jr = root.join("bot_live");
        std::fs::create_dir_all(&s8).unwrap();
        std::fs::create_dir_all(&jr).unwrap();
        std::fs::write(
            s8.join("manifest.json"),
            r#"{"situational": true, "slots": 6, "rules_version": 13}"#,
        )
        .unwrap();
        Fx { root, s8, jr }
    }
    fn entry(&self, arm: &str, hour: &str, sym: &str, side: &str, px: f64,
             mae: f64, mfe: f64, at_ts: f64) {
        let line = format!(
            r#"{{"arm":"{arm}","hour":"{hour}","sym":"{sym}","side":"{side}","px":{px},"mae":{mae},"mfe":{mfe},"at_ts":{at_ts},"reason":"вход по ситуации"}}"#
        );
        append(&self.s8.join("entries_live.jsonl"), &line);
    }
    fn exit(&self, arm: &str, hour: &str, sym: &str, side: &str, reason: &str,
            at_ts: f64) {
        let line = format!(
            r#"{{"arm":"{arm}","hour":"{hour}","sym":"{sym}","side":"{side}","px":1.0,"move_bp":-50.0,"at_ts":{at_ts},"reason":"{reason}"}}"#
        );
        append(&self.s8.join("exits_live.jsonl"), &line);
    }
    fn cfg(&self, dry: bool) -> LiveCfg {
        LiveCfg {
            s8_dir: self.s8.clone(),
            journal_dir: self.jr.clone(),
            arm: "gbm".into(),
            capital_usd: 300.0,
            name_cap_share: 0.10,
            entry_cap_bp: 30.0,
            stop_cap_bp: 100.0,
            day_stop_usd: 15.0,
            total_stop_usd: 45.0,
            max_rejects: 3,
            stale_cycle_h: 1e9, // свежесть манифеста в тестах не предмет
            stale_entry_sec: 120,
            dry,
        }
    }
    fn records(&self) -> Vec<bot::events::Record> {
        bot::journal::read_all(&self.jr).unwrap().0
    }
}

impl Drop for Fx {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn append(path: &std::path::Path, line: &str) {
    use std::io::Write;
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .unwrap();
    writeln!(f, "{line}").unwrap();
}

const NOW: i64 = 1_755_700_000_000;

// --- тесты -------------------------------------------------------------

/// Вход: IOC в потолке 30 б.п., размер — нога 30 $ вниз к шагу; после
/// исполнения на уровне обещания ЛЕЖИТ reduceOnly-лимитка (правило
/// v13). Дважды одно событие не исполняется.
#[test]
fn вход_ставит_ioc_и_цель_на_уровне() {
    let fx = Fx::new("entry");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let rep = ex.tick(NOW);
    assert_eq!(rep.opened, 1, "вход не открылся");

    let placed = m.placed();
    assert_eq!(placed.len(), 2, "ожидались IOC входа и лежащая цель: {placed:?}");
    let entry = &placed[0];
    assert_eq!(entry.tif, "IOC");
    assert_eq!(entry.side, "Buy");
    assert!(!entry.reduce_only);
    // Нога 30 $ при mid 1.0 и шаге 0.1 — ровно 30.0.
    assert!((entry.qty - 30.0).abs() < 1e-9, "{}", entry.qty);
    // Потолок: не дороже mid + 30 б.п.
    assert!(entry.px <= 1.0 * 1.0030 + 1e-9, "{}", entry.px);

    let target = &placed[1];
    assert_eq!(target.tif, "GTC");
    assert_eq!(target.side, "Sell");
    assert!(target.reduce_only, "цель обязана быть reduceOnly");
    // Уровень — от цены СОБЫТИЯ (1.0 + 120 б.п.), не от нашего
    // исполнения по 1.003.
    assert!((target.px - 1.012).abs() < 1e-9, "{}", target.px);
    assert!(target.link.starts_with("tp-ARBUSDT-"), "{}", target.link);

    // Повторный такт: то же событие не исполняется второй раз.
    let rep2 = ex.tick(NOW + 5_000);
    assert_eq!(rep2.opened, 0, "событие исполнилось дважды");
    assert_eq!(m.placed().len(), 2);

    // Журнал: Decision -> Open, write-ahead.
    let recs = fx.records();
    assert!(matches!(recs[0].event, Event::Decision { .. }));
    assert!(matches!(recs[1].event, Event::Open { .. }));
}

/// Не исполнившаяся IOC — записанный отказ и НИКАКОЙ позиции; три
/// подряд — остановка §5 (счёт живой, вслепую не стучимся).
#[test]
fn ioc_без_исполнения_отказ_и_три_подряд_остановка() {
    let fx = Fx::new("reject3");
    let m = Mock::new()
        .with_sym("AUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0)
        .with_sym("BUSDT", 1.9999, 2.0001, 0.0001, 0.1, 0.1, 5.0)
        .with_sym("CUSDT", 2.9999, 3.0001, 0.0001, 0.1, 0.1, 5.0);
    m.set_ioc_fills(false);
    fx.entry("gbm", "2026-08-20-15", "AUSDT", "long", 1.0, -50.0, 100.0, 1755699951.0);
    fx.entry("gbm", "2026-08-20-15", "BUSDT", "long", 2.0, -50.0, 100.0, 1755699952.0);
    fx.entry("gbm", "2026-08-20-15", "CUSDT", "long", 3.0, -50.0, 100.0, 1755699953.0);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let rep = ex.tick(NOW);
    assert_eq!(rep.opened, 0);
    assert_eq!(rep.rejected, 3);
    assert!(rep.halted.is_some(), "три отказа подряд обязаны остановить");
    assert!(ex.pos.is_empty());
    let recs = fx.records();
    let rejects = recs.iter().filter(|r| matches!(r.event, Event::Reject { .. })).count();
    assert_eq!(rejects, 3);
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Kill { on: true, reason, .. } if reason.contains("отказ"))));
}

/// Выход по стопу: цель снимается, позиция закрывается reduceOnly-IOC,
/// деньги в журнале — от фактических цен и комиссий.
#[test]
fn выход_по_стопу_снимает_цель_и_закрывает() {
    let fx = Fx::new("stop");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    assert_eq!(ex.pos.len(), 1);

    // Цена уехала вниз, сторож записал выход.
    m.0.borrow_mut().prices.insert("ARBUSDT".into(), (0.9949, 0.9951));
    fx.exit("gbm", "2026-08-20-15", "ARBUSDT", "long",
            "цена прошла обещанный ход против", 1755699100.0);
    let rep = ex.tick(NOW + 10_000);
    assert_eq!(rep.closed, 1, "стоп не закрыл позицию");
    assert!(ex.pos.is_empty());

    // Цель снята ДО закрытия.
    let cancelled = m.cancelled();
    assert_eq!(cancelled.len(), 1, "цель не снималась: {cancelled:?}");
    let placed = m.placed();
    let close = placed.last().unwrap();
    assert_eq!(close.tif, "IOC");
    assert_eq!(close.side, "Sell");
    assert!(close.reduce_only, "закрытие обязано быть reduceOnly");
    // Потолок стопа 100 б.п. от середины 0.995.
    assert!(close.px >= 0.995 * (1.0 - 100.0 / 1e4) - 1e-9, "{}", close.px);

    let recs = fx.records();
    let Some(Event::Close { pnl_usd, reason, .. }) = recs
        .iter()
        .rev()
        .find(|r| matches!(r.event, Event::Close { .. }))
        .map(|r| r.event.clone())
    else {
        panic!("нет Close в журнале");
    };
    assert!(reason.contains("ход против"), "{reason}");
    // Лонг с 1.003 в 0.9851: минус около 54 центов на 30 $ плюс два
    // круга комиссии — деньги отрицательные и правдоподобные.
    assert!(pnl_usd < -0.3 && pnl_usd > -1.5, "{pnl_usd}");
}

/// Книга дошла до цели и наша лимитка исполнилась: закрытие ПО ЦЕНЕ
/// УРОВНЯ — то, ради чего правило v13 и проверяется живьём.
#[test]
fn цель_исполнилась_закрытие_по_уровню() {
    let fx = Fx::new("target-fill");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    let target_id = m.placed().last().unwrap().id.clone();

    // Биржа исполнила лежащую цель по уровню.
    m.set_order(&target_id, OrderStatus {
        status: "Filled".into(),
        filled_qty: 30.0,
        avg_px: 1.012,
        fee_usd: 0.006,
    });
    {
        // Биржа сняла позицию исполнением цели.
        let mut i = m.0.borrow_mut();
        i.positions.clear();
    }
    let rep = ex.tick(NOW + 10_000);
    assert_eq!(rep.closed, 1, "исполненная цель не закрыла позицию");
    let recs = fx.records();
    let Some(Event::Close { exit_px, pnl_usd, reason, .. }) = recs
        .iter()
        .rev()
        .find(|r| matches!(r.event, Event::Close { .. }))
        .map(|r| r.event.clone())
    else {
        panic!("нет Close");
    };
    assert_eq!(exit_px, Some(1.012), "выход обязан быть по цене уровня");
    assert!(reason.contains("лимитка исполнилась"), "{reason}");
    assert!(pnl_usd > 0.2, "{pnl_usd}");
}

/// Книга записала «дошла до цели», а лимитка на бирже НЕ исполнилась:
/// расхождение правила v13 уезжает в причину словами, позиция
/// закрывается IOC — главный замер X3 не теряется молча.
#[test]
fn цель_книги_без_исполнения_лимитки_это_расхождение_v13() {
    let fx = Fx::new("target-miss");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);

    fx.exit("gbm", "2026-08-20-15", "ARBUSDT", "long",
            "цена дошла до обещанной цели", 1755699100.0);
    let rep = ex.tick(NOW + 10_000);
    assert_eq!(rep.closed, 1);
    let recs = fx.records();
    let Some(Event::Close { reason, .. }) = recs
        .iter()
        .rev()
        .find(|r| matches!(r.event, Event::Close { .. }))
        .map(|r| r.event.clone())
    else {
        panic!("нет Close");
    };
    assert!(reason.contains("НЕ исполнилась"), "{reason}");
    assert!(reason.contains("v13"), "{reason}");
}

/// Сверка §4: биржа держит позицию, которой журнал не знает, —
/// остановка БЕЗ закрытий (состоянию верить нельзя), свои цели сняты.
#[test]
fn расхождение_с_биржей_останавливает_без_закрытий() {
    let fx = Fx::new("mismatch");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    let placed_before = m.placed().len();

    // Чужая позиция появилась на счёте мимо журнала.
    m.push_position("GHOSTUSDT", Side::Long, 5.0);
    let rep = ex.tick(NOW + 10_000);
    assert!(rep.halted.is_some(), "расхождение обязано остановить");
    assert!(rep.halted.as_ref().unwrap().contains("сверка"), "{rep:?}");
    // Ни одной НОВОЙ заявки — ни входов, ни закрытий.
    assert_eq!(m.placed().len(), placed_before, "остановка не смеет торговать");
    // Своя цель снята: лимитка при молчащем исполнителе углубила бы
    // расхождение.
    assert_eq!(m.cancelled().len(), 1);
    // Позиция осталась: закрывать по неверному состоянию нельзя.
    assert_eq!(ex.pos.len(), 1);
}

/// Файл KILL: не совершается НИЧЕГО — ни заявок, ни отмен.
#[test]
fn kill_означает_руки_прочь() {
    let fx = Fx::new("kill");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    let before = (m.placed().len(), m.cancelled().len());

    std::fs::write(fx.jr.join("KILL"), b"").unwrap();
    fx.exit("gbm", "2026-08-20-15", "ARBUSDT", "long",
            "цена прошла обещанный ход против", 1755699100.0);
    let rep = ex.tick(NOW + 10_000);
    assert_eq!(rep.halted.as_deref(), Some("KILL"));
    assert_eq!((m.placed().len(), m.cancelled().len()), before,
               "после KILL не совершается ничего");
}

/// Предел дня §5: минус глубже 15 $ закрывает всё и останавливает.
#[test]
fn предел_дня_закрывает_всё() {
    let fx = Fx::new("daystop");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);

    // Сегодняшний реализованный минус вносится журналом второй копии
    // исполнителя не имеет: пишем Close руками через журнал теста.
    {
        let (mut jr, _, _) = bot::journal::Journal::open(&fx.jr).unwrap();
        jr.append(Event::Close {
            pos: "gbm:x:YUSDT:long".into(),
            exit_px: None,
            fee_usd: 0.0,
            pnl_usd: -20.0,
            reason: "тестовый минус".into(),
            at_ms: NOW,
        })
        .unwrap();
    }
    // Перечитанный исполнитель обязан увидеть минус дня и закрыть всё.
    let m2 = m.clone();
    let mut ex2 = Executor::open(fx.cfg(false), m2, false).unwrap();
    let rep = ex2.tick(NOW + 10_000);
    assert!(rep.halted.is_some());
    assert!(rep.halted.as_ref().unwrap().contains("день"), "{rep:?}");
    assert_eq!(rep.closed, 1, "позиция обязана закрыться при остановке дня");
    let last = m.placed();
    let close = last.last().unwrap();
    assert!(close.reduce_only && close.tif == "IOC");
}

/// Сухой прогон X2: заявка сформирована и проверена по справочнику,
/// но НЕ отправлена; позиций не существует, выдуманных исполнений нет.
#[test]
fn сухой_прогон_не_отправляет_ничего() {
    let fx = Fx::new("dry");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(true), m.clone(), false).unwrap();
    let rep = ex.tick(NOW);
    assert_eq!(rep.opened, 0);
    assert_eq!(m.placed().len(), 0, "сухой прогон отправил заявку");
    assert!(ex.pos.is_empty());
    let recs = fx.records();
    let Some(Event::Reject { reason, .. }) = recs
        .iter()
        .rev()
        .find(|r| matches!(r.event, Event::Reject { .. }))
        .map(|r| r.event.clone())
    else {
        panic!("нет Reject");
    };
    assert!(reason.contains("сухой прогон"), "{reason}");
    // Сформированная заявка видна словами: сторона, размер, потолок.
    assert!(reason.contains("Buy ARBUSDT 30.0 @ 1.003"), "{reason}");
}

/// Встречный сигнал на удерживаемом имени закрывает позицию и сам не
/// открывается — правило кассы v3 на живом счёте.
#[test]
fn встречный_сигнал_закрывает_и_не_открывается() {
    let fx = Fx::new("netted");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    assert_eq!(ex.pos.len(), 1);

    fx.entry("gbm", "2026-08-20-16", "ARBUSDT", "short", 1.001, 60.0, -140.0, 1755702600.0);
    let rep = ex.tick(NOW + 10_000);
    assert_eq!(rep.closed, 1, "встречный сигнал обязан закрыть позицию");
    assert_eq!(rep.opened, 0, "встречный сигнал не открывается");
    assert!(ex.pos.is_empty());
    let recs = fx.records();
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Close { reason, .. } if reason.contains("встречный сигнал"))));
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Reject { reason, .. } if reason.contains("вход не открывался"))));
}

/// Нога 30 $ меньше минимального лота (случай BTC): честный отказ без
/// заявки, и он НЕ считается отказом биржи — серию §5 не двигает.
#[test]
fn мелкая_нога_отвергается_без_заявки() {
    let fx = Fx::new("minlot");
    let m = Mock::new().with_sym("BTCUSDT", 114999.0, 115001.0, 0.1, 0.001, 0.001, 5.0);
    fx.entry("gbm", "2026-08-20-15", "BTCUSDT", "long", 115000.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let rep = ex.tick(NOW);
    assert_eq!(rep.opened, 0);
    assert_eq!(m.placed().len(), 0);
    assert!(rep.halted.is_none(), "мелкий лот — не отказ биржи");
    let recs = fx.records();
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Reject { reason, .. } if reason.contains("меньше минимального лота"))));
}

/// Перезапуск: позиция из журнала принимает КОЛИЧЕСТВО от биржи, а
/// решение без исхода закрывается отказом — вход привязан к секунде.
#[test]
fn перезапуск_берёт_количество_у_биржи() {
    let fx = Fx::new("restart");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    {
        let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
        ex.tick(NOW);
    }
    // Оборванное решение: Decision без Open/Reject.
    {
        let (mut jr, _, _) = bot::journal::Journal::open(&fx.jr).unwrap();
        jr.append(Event::Decision {
            src_ts: None,
            arm: "gbm".into(),
            hour: "2026-08-20-16".into(),
            sym: "ZUSDT".into(),
            side: Side::Long,
            px: Some(2.0),
            ver: None,
            at_ms: NOW + 1000,
        })
        .unwrap();
    }
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let key = pos_key("gbm", "2026-08-20-15", "ARBUSDT", Side::Long);
    let p = ex.pos.get(&key).expect("позиция не поднялась из журнала");
    assert!((p.qty - 30.0).abs() < 1e-9, "количество не от биржи: {}", p.qty);
    let recs = fx.records();
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Reject { sym, reason, .. }
            if sym == "ZUSDT" && reason.contains("оборвано перезапуском"))),
        "оборванное решение не закрыто отказом");
    // И живой такт после перезапуска проходит сверку.
    let rep = ex.tick(NOW + 20_000);
    assert!(rep.halted.is_none(), "{rep:?}");
}

/// Дедуп события входа обязан переживать ЗАКРЫТИЕ позиции: файл
/// событий перечитывается каждый такт целиком, и без дедупа старое
/// событие открывало бы сделку заново сразу после выхода. Пока имя
/// в позиции, повтор маскирует проверка «имя уже в позиции» — потому
/// проверять надо именно после закрытия.
#[test]
fn старое_событие_не_входит_после_закрытия() {
    let fx = Fx::new("dedup-after-close");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    fx.exit("gbm", "2026-08-20-15", "ARBUSDT", "long",
            "цена прошла обещанный ход против", 1755699100.0);
    let rep = ex.tick(NOW + 10_000);
    assert_eq!(rep.closed, 1);
    assert!(ex.pos.is_empty());

    // Третий такт: файл событий всё ещё несёт старый вход.
    let rep3 = ex.tick(NOW + 20_000);
    assert_eq!(rep3.opened, 0, "старое событие вошло второй раз");
    assert!(ex.pos.is_empty());
    // И журнал не пухнет повторными Decision.
    let recs = fx.records();
    let decisions = recs.iter().filter(|r| matches!(r.event, Event::Decision { .. })).count();
    assert_eq!(decisions, 1, "решение записано больше одного раза");
}

/// Первый запуск на живой книге: файл событий несёт ИСТОРИЮ, и без
/// порога свежести первые шесть старых входов открыли бы живые
/// позиции по прошлым сигналам (найдено сухим прогоном X2). Старое
/// событие не торгуется, не трогает биржу и не порождает ни строки
/// журнала; свежее рядом с ним работает как обычно.
#[test]
fn историческое_событие_не_торгуется_и_не_шумит() {
    let fx = Fx::new("stale");
    let m = Mock::new()
        .with_sym("OLDUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0)
        .with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    // Событие часовой давности — история книги до нашего запуска.
    fx.entry("gbm", "2026-08-20-14", "OLDUSDT", "long", 1.0, -50.0, 120.0, 1755696400.0);
    // Свежее событие — 50 секунд до NOW.
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let rep = ex.tick(NOW);
    assert_eq!(rep.opened, 1, "свежее событие обязано войти");
    assert!(ex.pos.keys().all(|k| k.contains("ARBUSDT")), "{:?}", ex.pos.keys());
    // Историческое не оставило следа: ни заявки, ни строки журнала.
    let placed = m.placed();
    assert!(placed.iter().all(|p| p.sym != "OLDUSDT"), "{placed:?}");
    let recs = fx.records();
    assert!(recs.iter().all(|r| !matches!(&r.event,
        Event::Decision { sym, .. } | Event::Reject { sym, .. } if sym == "OLDUSDT")),
        "историческое событие попало в журнал");
    // И на следующем такте оно так же старо.
    let rep2 = ex.tick(NOW + 5_000);
    assert_eq!(rep2.opened, 0);
}

/// Журнал режется на сутки по метке записи, и свежее событие,
/// случившееся ЗА СЕКУНДЫ до полуночи, не вправе класть строку во
/// вчерашний файл: первый сухой прогон X2 именно так перемешал
/// номера строк между суточными файлами, и исполнитель отказался
/// подниматься («номер вне очереди»). Все строки обязаны лечь в
/// сегодняшний файл, и журнал обязан перечитываться.
#[test]
fn событие_у_полуночи_не_рвёт_журнал() {
    let fx = Fx::new("midnight");
    let m = Mock::new()
        .with_sym("AUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0)
        .with_sym("BUSDT", 1.9999, 2.0001, 0.0001, 0.1, 0.1, 5.0);
    // Полночь суток NOW и момент «30 секунд после неё».
    let day = bot::journal::utc_day(NOW);
    let midnight_ms = bot::picks::hour_ms(&format!("{day}-00")).unwrap();
    let now2 = midnight_ms + 30_000;
    // Сначала сегодняшнее событие, затем вчерашнее — но свежее
    // (90 секунд назад): порядок, на котором старая метка ломала
    // журнал (поздний номер уезжал в РАННИЙ суточный файл).
    fx.entry("gbm", "2026-08-20-00", "AUSDT", "long", 1.0, -50.0, 120.0,
             (now2 as f64) / 1000.0 - 10.0);
    fx.entry("gbm", "2026-08-19-23", "BUSDT", "long", 2.0, -50.0, 120.0,
             (midnight_ms as f64) / 1000.0 - 60.0);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let rep = ex.tick(now2);
    assert_eq!(rep.opened, 2, "оба свежих события обязаны войти");
    // Все строки — в одном, сегодняшнем файле.
    let files: Vec<String> = std::fs::read_dir(&fx.jr)
        .unwrap()
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.starts_with("journal-"))
        .collect();
    assert_eq!(files.len(), 1, "строки разъехались по суткам: {files:?}");
    assert!(files[0].contains(&day), "{files:?} против {day}");
    // И журнал перечитывается — на этом падал живой сервер.
    let (recs, _) = bot::journal::read_all(&fx.jr).expect("журнал не перечитался");
    assert!(recs.len() >= 4);
}

/// Инцидент IMXUSDT: цель исполнилась ЧАСТИЧНО, биржа уменьшила
/// позицию, а обнаружение понимало только «Filled» целиком — сверка
/// видела расхождение и останавливала исполнитель; MONUSDT после
/// этого висела без управления, пока владелец не закрыл руками.
/// Теперь частичное исполнение уменьшает позицию, копит реализованную
/// часть и переставляет лимитку на остаток тем же уровнем.
#[test]
fn частичная_цель_не_останавливает_а_переставляется() {
    let fx = Fx::new("partial");
    let m = Mock::new().with_sym("IMXUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-21-21", "IMXUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    let target_id = m.placed().last().unwrap().id.clone();

    // Биржа исполнила 10 из 30 по уровню и держит остаток 20.
    m.set_order(&target_id, OrderStatus {
        status: "PartiallyFilled".into(),
        filled_qty: 10.0,
        avg_px: 1.012,
        fee_usd: 0.002,
    });
    {
        let mut i = m.0.borrow_mut();
        i.positions.clear();
        i.positions.push(ExchPos {
            sym: "IMXUSDT".into(), side: Side::Long, qty: 20.0,
        });
    }
    let rep = ex.tick(NOW + 10_000);
    assert!(rep.halted.is_none(),
            "частичное исполнение цели прочитано как расхождение: {rep:?}");
    let key = pos_key("gbm", "2026-08-21-21", "IMXUSDT", Side::Long);
    let p = ex.pos.get(&key).expect("позиция пропала").clone();
    assert!((p.qty - 20.0).abs() < 1e-9, "{}", p.qty);
    assert!((p.notional_usd - 20.0 * p.entry_px).abs() < 1e-6);
    // Реализованная часть: (1.012 − 1.003) × 10 = 0.09.
    assert!((p.part_pnl - 0.09).abs() < 1e-9, "{}", p.part_pnl);
    // Лимитка переставлена на остаток тем же уровнем.
    let last = m.placed();
    let re = last.last().unwrap().clone();
    assert_eq!(re.tif, "GTC");
    assert!((re.qty - 20.0).abs() < 1e-9, "{}", re.qty);
    assert!((re.px - 1.012).abs() < 1e-9, "{}", re.px);

    // Остаток дошёл до цели целиком: закрытие несёт И часть.
    m.set_order(&re.id, OrderStatus {
        status: "Filled".into(),
        filled_qty: 20.0,
        avg_px: 1.012,
        fee_usd: 0.004,
    });
    {
        m.0.borrow_mut().positions.clear();
    }
    let rep = ex.tick(NOW + 20_000);
    assert_eq!(rep.closed, 1);
    let recs = fx.records();
    let Some(Event::Close { pnl_usd, .. }) = recs
        .iter()
        .rev()
        .find(|r| matches!(r.event, Event::Close { .. }))
        .map(|r| r.event.clone())
    else { panic!("нет Close") };
    // Остаток: (1.012−1.003)/1.003 × 20.06 ≈ 0.18; часть 0.09; минус
    // комиссии входа и частей.
    assert!(pnl_usd > 0.22 && pnl_usd < 0.28, "{pnl_usd}");
}

/// Перезапуск возвращает ЛЕЖАЩУЮ цель по метке заявки, а не оставляет
/// позицию без неё (инцидент MONUSDT: перезапуск терял цели). И
/// количество берётся с биржи: цель могла исполниться частично, пока
/// исполнитель не работал, — нотионал пересчитывается.
#[test]
fn перезапуск_возвращает_цель_и_считает_частичное() {
    let fx = Fx::new("restart-target");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let (open_at, target_px) = {
        let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
        ex.tick(NOW);
        let key = pos_key("gbm", "2026-08-20-15", "ARBUSDT", Side::Long);
        let p = ex.pos.get(&key).unwrap();
        (p.opened_at_ms, p.target_px.unwrap())
    };
    // Пока исполнитель лежал: цель исполнилась на 12 из 30, остаток
    // заявки стоит в книге со СВОЕЙ меткой.
    {
        let mut i = m.0.borrow_mut();
        i.positions.clear();
        i.positions.push(ExchPos {
            sym: "ARBUSDT".into(), side: Side::Long, qty: 18.0,
        });
        i.resting.push(Resting {
            sym: "ARBUSDT".into(), id: "rest1".into(),
            link: format!("tp-ARBUSDT-{open_at}"),
            qty: 18.0, px: target_px,
        });
    }
    let placed_before = m.placed().len();
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let key = pos_key("gbm", "2026-08-20-15", "ARBUSDT", Side::Long);
    {
        let p = ex.pos.get(&key).expect("позиция не поднялась");
        assert!((p.qty - 18.0).abs() < 1e-9, "{}", p.qty);
        assert!((p.notional_usd - 18.0 * p.entry_px).abs() < 1e-6,
                "нотионал не пересчитан: {}", p.notional_usd);
        assert_eq!(p.target_id.as_deref(), Some("rest1"),
                   "лежащая цель не возвращена");
    }
    // И такт НЕ ставит вторую цель поверх возвращённой.
    let rep = ex.tick(NOW + 30_000);
    assert!(rep.halted.is_none(), "{rep:?}");
    assert_eq!(m.placed().len(), placed_before,
               "перезапуск поставил дубль цели");
}

/// Позиция, закрытая вне исполнителя (владелец закрыл руками), при
/// перезапуске закрывается записью с причиной — а не висит нулевым
/// количеством и не выдумывает денег.
#[test]
fn закрытое_руками_закрывается_записью_вне_исполнителя() {
    let fx = Fx::new("manual-close");
    let m = Mock::new().with_sym("MONUSDT", 0.0299, 0.0301, 0.00001, 1.0, 1.0, 5.0);
    fx.entry("gbm", "2026-08-21-21", "MONUSDT", "short", 0.03, 60.0, -140.0, 1755699950.5);
    {
        let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
        ex.tick(NOW);
        assert_eq!(ex.pos.len(), 1);
    }
    // Владелец закрыл позицию в приложении.
    m.0.borrow_mut().positions.clear();
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    assert!(ex.pos.is_empty(), "позиция-призрак после ручного закрытия");
    let recs = fx.records();
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Close { reason, pnl_usd, .. }
            if reason.contains("вне исполнителя")
               && *pnl_usd == 0.0)),
        "нет записи о закрытии вне исполнителя");
    let rep = ex.tick(NOW + 10_000);
    assert!(rep.halted.is_none(), "{rep:?}");
}

/// Деньги сделки, закрытой мимо исполнителя, знает биржа — и запись
/// закрытия обязана нести ИХ, а не ноль: closed-pnl отдаёт
/// реализованный результат ручных закрытий (инцидент MONUSDT — на
/// странице стоял pnl 0 при настоящих деньгах в кошельке).
#[test]
fn закрытое_руками_берёт_деньги_с_биржи() {
    let fx = Fx::new("manual-close-pnl");
    let m = Mock::new().with_sym("MONUSDT", 0.0299, 0.0301, 0.00001, 1.0, 1.0, 5.0);
    fx.entry("gbm", "2026-08-21-21", "MONUSDT", "short", 0.03, 60.0, -140.0, 1755699950.5);
    {
        let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
        ex.tick(NOW);
        assert_eq!(ex.pos.len(), 1);
    }
    // Владелец закрыл руками; биржа помнит деньги этого закрытия.
    m.0.borrow_mut().positions.clear();
    m.push_closed_pnl("MONUSDT", NOW + 60_000, 2.64);
    let ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    assert!(ex.pos.is_empty());
    let recs = fx.records();
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Close { reason, pnl_usd, .. }
            if reason.contains("взяты с биржи")
               && (*pnl_usd - 2.64).abs() < 1e-9)),
        "закрытие вне исполнителя не взяло деньги с биржи: {recs:?}");
}

/// Запись прежнего образца («денег журнал не знает», pnl 0)
/// доправляется с биржи задним числом ОТДЕЛЬНОЙ записью при
/// перезапуске — и ровно один раз: повторный подъём не спрашивает
/// биржу заново и второй поправки не пишет.
#[test]
fn нулевое_вне_исполнителя_доправляется_поправкой() {
    let fx = Fx::new("adjust-pnl");
    let m = Mock::new().with_sym("MONUSDT", 0.0299, 0.0301, 0.00001, 1.0, 1.0, 5.0);
    fx.entry("gbm", "2026-08-21-21", "MONUSDT", "short", 0.03, 60.0, -140.0, 1755699950.5);
    {
        let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
        ex.tick(NOW);
    }
    // Ручное закрытие при бирже, ещё НЕ отдающей записей, — рождается
    // запись прежнего образца с нулём и оговоркой.
    m.0.borrow_mut().positions.clear();
    drop(Executor::open(fx.cfg(false), m.clone(), false).unwrap());
    assert!(fx.records().iter().any(|r| matches!(&r.event,
        Event::Close { reason, pnl_usd, .. }
            if reason.contains("не знает") && *pnl_usd == 0.0)));
    // Биржа знает деньги — следующий подъём доправляет их поправкой.
    m.push_closed_pnl("MONUSDT", NOW + 60_000, 2.64);
    drop(Executor::open(fx.cfg(false), m.clone(), false).unwrap());
    let adj: Vec<f64> = fx.records().iter().filter_map(|r| match &r.event {
        Event::Adjust { pnl_usd, .. } => Some(*pnl_usd),
        _ => None,
    }).collect();
    assert_eq!(adj, vec![2.64], "поправка не записана либо не одна");
    // Четвёртый подъём: поправка уже есть — биржу не спрашиваем,
    // второй не пишем.
    let calls = m.closed_pnl_calls();
    drop(Executor::open(fx.cfg(false), m.clone(), false).unwrap());
    assert_eq!(m.closed_pnl_calls(), calls,
               "повторный подъём снова спрашивает биржу");
    let n = fx.records().iter().filter(|r| matches!(&r.event,
        Event::Adjust { .. })).count();
    assert_eq!(n, 1, "поправка задвоилась");
}

/// Отказ 110126 «подпишите соглашение» — ограничение счёта по
/// конкретному имени, детерминированное и не про исполнение: серию
/// «три отказа подряд» он двигать не должен (на живом счёте два таких
/// уже стояли в шаге от остановки всего замера).
#[test]
fn отказ_по_соглашению_не_входит_в_серию() {
    let fx = Fx::new("agreement");
    let m = Mock::new()
        .with_sym("GEUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0)
        .with_sym("WMTUSDT", 1.9999, 2.0001, 0.0001, 0.1, 0.1, 5.0)
        .with_sym("XUSDT", 2.9999, 3.0001, 0.0001, 0.1, 0.1, 5.0);
    m.set_entry_error(Some(
        "/v5/order/create: retCode 110126 You must sign the required \
         agreement before trading"));
    fx.entry("gbm", "2026-08-21-21", "GEUSDT", "long", 1.0, -50.0, 100.0, 1755699951.0);
    fx.entry("gbm", "2026-08-21-21", "WMTUSDT", "long", 2.0, -50.0, 100.0, 1755699952.0);
    fx.entry("gbm", "2026-08-21-21", "XUSDT", "long", 3.0, -50.0, 100.0, 1755699953.0);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    let rep = ex.tick(NOW);
    assert_eq!(rep.rejected, 3);
    assert!(rep.halted.is_none(),
            "отказы по соглашению остановили замер: {rep:?}");
    let recs = fx.records();
    assert!(recs.iter().any(|r| matches!(&r.event,
        Event::Reject { reason, .. }
            if reason.contains("подписать соглашение"))));
}

/// Плечо 1× (спека 12 §2) выставляется раз на имя перед первым входом.
#[test]
fn плечо_выставляется_раз_на_имя() {
    let fx = Fx::new("lev");
    let m = Mock::new().with_sym("ARBUSDT", 0.9999, 1.0001, 0.0001, 0.1, 0.1, 5.0);
    fx.entry("gbm", "2026-08-20-15", "ARBUSDT", "long", 1.0, -50.0, 120.0, 1755699950.5);
    let mut ex = Executor::open(fx.cfg(false), m.clone(), false).unwrap();
    ex.tick(NOW);
    ex.tick(NOW + 5_000);
    let calls = m.0.borrow().lev_calls.clone();
    assert_eq!(calls, vec!["ARBUSDT".to_string()],
               "плечо не выставлено либо выставлялось повторно: {calls:?}");
}

/// Потолок цены — служебная арифметика уровня заявки.
#[test]
fn потолок_является_потолком() {
    // Покупка никогда не дороже объявленного потолка…
    for mid in [0.01234_f64, 1.0, 77593.9] {
        let px = cap_price(mid, true, 30.0, 0.0001);
        assert!(px <= mid * 1.0030 + 1e-9, "{mid} {px}");
        // …и продажа никогда не дешевле.
        let px = cap_price(mid, false, 30.0, 0.0001);
        assert!(px >= mid * 0.9970 - 1e-9, "{mid} {px}");
    }
}
