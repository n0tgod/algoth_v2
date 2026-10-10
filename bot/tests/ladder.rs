//! Проверки исполнителя Ladder (спека 15 §10a) на подставной бирже.
//!
//! Подставная биржа исполняет так, как площадка: IOC — сразу по лучшей
//! цене в пределах лимита или отмена; лежащая лимитка — только когда
//! лучшая цена ПРОШЛА её уровень (не касание); reduceOnly не увеличивает
//! позицию; хедж-режим отвергает индекс 0 тем же текстом, что Bybit.

use bot::events::Side;
use bot::ladder::{Ladder, LadderCfg};
use bot::live::{ExchPos, Exchange, Instrument, OrderStatus, Resting};
use serde_json::{json, Value};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::rc::Rc;

#[derive(Clone, Debug)]
struct Ord {
    sym: String,
    buy: bool,
    qty: f64,
    px: f64,
    tif: String,
    reduce: bool,
    filled: f64,
    cost: f64,
    status: String,
    idx: i64,
}

#[derive(Default)]
struct Inner {
    prices: BTreeMap<String, (f64, f64)>,
    pos: BTreeMap<String, f64>, // имя → количество со знаком
    orders: BTreeMap<String, Ord>,
    next: u64,
    hedge: bool,
    lev: Vec<(String, String)>,
    lev_error: Option<String>,
    closed_pnl: Vec<(String, f64)>,
    fee_bp: f64,
    order_calls: u64,
}

#[derive(Clone, Default)]
struct Mock(Rc<RefCell<Inner>>);

impl Mock {
    fn new() -> Mock {
        let m = Mock::default();
        m.0.borrow_mut().fee_bp = 5.5;
        m
    }
    fn set_px(&self, sym: &str, bid: f64, ask: f64) {
        self.0.borrow_mut().prices.insert(sym.into(), (bid, ask));
        self.cross(sym);
    }
    fn fill(i: &mut Inner, id: &str, q: f64, px: f64) {
        let fee_bp = i.fee_bp;
        let o = i.orders.get_mut(id).unwrap();
        let q = q.min(o.qty - o.filled);
        if q <= 0.0 {
            return;
        }
        o.filled += q;
        o.cost += q * px;
        o.status = if o.filled + 1e-12 >= o.qty { "Filled".into() } else { "PartiallyFilled".into() };
        let (sym, buy, reduce) = (o.sym.clone(), o.buy, o.reduce);
        let _ = fee_bp;
        let cur = *i.pos.get(&sym).unwrap_or(&0.0);
        let d = if buy { q } else { -q };
        let mut next = cur + d;
        if reduce && cur.signum() == next.signum() * -1.0 {
            next = 0.0;
        }
        if next.abs() < 1e-12 {
            i.pos.remove(&sym);
        } else {
            i.pos.insert(sym, next);
        }
    }
    /// Лежащие лимитки исполняются, когда лучшая цена ПРОШЛА уровень.
    fn cross(&self, sym: &str) {
        let mut i = self.0.borrow_mut();
        let (bid, ask) = *i.prices.get(sym).unwrap_or(&(0.0, 0.0));
        let ids: Vec<String> = i
            .orders
            .iter()
            .filter(|(_, o)| o.sym == sym && o.tif == "GTC" && (o.status == "New" || o.status == "PartiallyFilled"))
            .filter(|(_, o)| if o.buy { ask > 0.0 && ask < o.px } else { bid > o.px })
            .map(|(k, _)| k.clone())
            .collect();
        for id in ids {
            let (q, px) = {
                let o = &i.orders[&id];
                (o.qty - o.filled, o.px)
            };
            Mock::fill(&mut i, &id, q, px);
        }
    }
    fn partial(&self, id: &str, q: f64) {
        let mut i = self.0.borrow_mut();
        let px = i.orders[id].px;
        Mock::fill(&mut i, id, q, px);
    }
    fn orders_of(&self, sym: &str) -> Vec<Ord> {
        self.0.borrow().orders.values().filter(|o| o.sym == sym).cloned().collect()
    }
    fn resting(&self, sym: &str) -> Vec<(String, Ord)> {
        self.0
            .borrow()
            .orders
            .iter()
            .filter(|(_, o)| o.sym == sym && (o.status == "New" || o.status == "PartiallyFilled"))
            .map(|(k, o)| (k.clone(), o.clone()))
            .collect()
    }
    fn pos(&self, sym: &str) -> f64 {
        *self.0.borrow().pos.get(sym).unwrap_or(&0.0)
    }
}

impl Exchange for Mock {
    fn best_prices(&self, symbol: &str) -> Result<(f64, f64), String> {
        self.0.borrow().prices.get(symbol).copied().ok_or_else(|| format!("нет цен {symbol}"))
    }
    fn open_orders(&self) -> Result<Vec<Resting>, String> {
        Ok(self
            .0
            .borrow()
            .orders
            .iter()
            .filter(|(_, o)| o.status == "New" || o.status == "PartiallyFilled")
            .map(|(k, o)| Resting { sym: o.sym.clone(), id: k.clone(), link: String::new(), qty: o.qty, px: o.px })
            .collect())
    }
    fn set_leverage(&self, symbol: &str, lev: &str) -> Result<(), String> {
        let mut i = self.0.borrow_mut();
        if let Some(e) = i.lev_error.clone() {
            return Err(e);
        }
        i.lev.push((symbol.into(), lev.into()));
        Ok(())
    }
    fn instrument(&self, _symbol: &str) -> Result<Instrument, String> {
        Ok(Instrument { tick: 0.01, step: 0.01, min_qty: 0.01, min_notional: 5.0 })
    }
    fn place_limit(&self, s: &str, side: &str, q: &str, p: &str, tif: &str, l: &str, r: bool) -> Result<String, String> {
        self.place_limit_idx(s, side, q, p, tif, l, r, 0)
    }
    fn place_limit_idx(
        &self,
        symbol: &str,
        side: &str,
        qty: &str,
        price: &str,
        tif: &str,
        _link: &str,
        reduce: bool,
        idx: i64,
    ) -> Result<String, String> {
        let mut i = self.0.borrow_mut();
        i.order_calls += 1;
        if i.hedge != (idx != 0) {
            return Err("order/create: retCode 10001 position idx not match position mode".into());
        }
        i.next += 1;
        let id = format!("o{}", i.next);
        let q: f64 = qty.parse().unwrap();
        let px: f64 = price.parse().unwrap();
        let buy = side == "Buy";
        i.orders.insert(
            id.clone(),
            Ord { sym: symbol.into(), buy, qty: q, px, tif: tif.into(), reduce, filled: 0.0, cost: 0.0, status: "New".into(), idx },
        );
        if tif == "IOC" {
            let (bid, ask) = *i.prices.get(symbol).unwrap_or(&(0.0, 0.0));
            let ok = if buy { ask > 0.0 && ask <= px } else { bid >= px };
            let cur = *i.pos.get(symbol).unwrap_or(&0.0);
            let q = if reduce { q.min(cur.abs()) } else { q };
            if ok && q > 0.0 {
                Mock::fill(&mut i, &id, q, if buy { ask } else { bid });
            }
            let o = i.orders.get_mut(&id).unwrap();
            if o.status != "Filled" {
                o.status = if o.filled > 0.0 { "PartiallyFilledCanceled".into() } else { "Cancelled".into() };
            }
        }
        Ok(id)
    }
    fn cancel(&self, _symbol: &str, id: &str) -> Result<(), String> {
        let mut i = self.0.borrow_mut();
        if let Some(o) = i.orders.get_mut(id) {
            if o.status == "New" {
                o.status = "Cancelled".into();
            } else if o.status == "PartiallyFilled" {
                o.status = "PartiallyFilledCanceled".into();
            }
        }
        Ok(())
    }
    fn order_status(&self, _symbol: &str, id: &str) -> Result<OrderStatus, String> {
        let i = self.0.borrow();
        let o = i.orders.get(id).ok_or("нет заявки")?;
        Ok(OrderStatus {
            status: o.status.clone(),
            filled_qty: o.filled,
            avg_px: if o.filled > 0.0 { o.cost / o.filled } else { 0.0 },
            fee_usd: o.cost * i.fee_bp / 1e4,
        })
    }
    fn positions(&self) -> Result<Vec<ExchPos>, String> {
        Ok(self
            .0
            .borrow()
            .pos
            .iter()
            .map(|(s, q)| ExchPos { sym: s.clone(), side: if *q > 0.0 { Side::Long } else { Side::Short }, qty: q.abs() })
            .collect())
    }
    fn wallet_usdt(&self) -> Result<(f64, f64), String> {
        Ok((300.0, 300.0))
    }
    fn closed_pnl(&self, symbol: &str, _a: i64, _b: i64) -> Result<Vec<(i64, f64)>, String> {
        Ok(self.0.borrow().closed_pnl.iter().filter(|(s, _)| s == symbol).map(|(_, p)| (0, *p)).collect())
    }
}

const T0: i64 = 1_791_000_000_000;

fn dir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("ladder-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write_intents(d: &PathBuf, rows: &[Value]) {
    let text: String = rows.iter().map(|r| format!("{r}\n")).collect();
    std::fs::write(d.join("intents.jsonl"), text).unwrap();
}

fn events(d: &PathBuf) -> Vec<Value> {
    std::fs::read_to_string(d.join("events.jsonl"))
        .unwrap_or_default()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

fn kinds(d: &PathBuf) -> Vec<String> {
    events(d).iter().map(|e| e["ev"].as_str().unwrap().to_string()).collect()
}

fn short_intent(seq: i64) -> Value {
    json!({"seq": seq, "kind": "entry", "sym": "SSSUSDT", "side": "short", "book": "aggr_h",
           "lev": 25.0, "margin_usd": 6.25, "px_ref": 100.0, "take_frac": 0.05,
           "rungs": [{"px": 100.0, "share": 0.25, "floor_px": 107.0, "liq_px": 115.0}],
           "term_ts": (T0 / 1000 + 24 * 3600) as f64, "decided_at": (T0 / 1000) as f64,
           "computed_at": (T0 / 1000) as f64 + 60.0})
}

fn long_intent(seq: i64) -> Value {
    json!({"seq": seq, "kind": "entry", "sym": "LLLUSDT", "side": "long", "book": "aggr",
           "lev": 8.0, "margin_usd": 25.0, "px_ref": 100.0, "take_frac": 0.04,
           "rungs": [{"px": 100.0, "share": 0.25, "floor_px": 80.0, "liq_px": 78.0},
                     {"px": 97.0, "share": 0.25, "floor_px": 85.0, "liq_px": 83.0},
                     {"px": 94.0, "share": 0.25, "floor_px": 87.0, "liq_px": 86.0},
                     {"px": 91.0, "share": 0.25, "floor_px": 88.0, "liq_px": 87.0}],
           "term_ts": (T0 / 1000 + 72 * 3600) as f64, "decided_at": (T0 / 1000) as f64,
           "computed_at": (T0 / 1000) as f64 + 60.0})
}

fn ladder(d: &PathBuf, m: &Mock, dry: bool) -> Ladder<Mock> {
    Ladder::open(LadderCfg { dir: d.clone(), dry }, m.clone()).unwrap()
}

#[test]
fn шорт_с_одним_рунгом_входит_ставит_цель_и_выходит_по_ней() {
    let d = dir("short");
    let m = Mock::new();
    m.set_px("SSSUSDT", 99.99, 100.01);
    write_intents(&d, &[short_intent(1)]);
    let mut lx = ladder(&d, &m, false);
    let rep = lx.tick(T0 + 120_000);
    assert_eq!(rep.opened, 1, "{:?}", lx.last_error);
    // база: 0.25 × 6.25 × 25 / 100 = 0.39 по шагу 0.01; продажа по bid
    assert!((m.pos("SSSUSDT") + 0.39).abs() < 1e-9, "позиция {}", m.pos("SSSUSDT"));
    assert_eq!(m.0.borrow().lev, vec![("SSSUSDT".to_string(), "25.00".to_string())]);
    let rest = m.resting("SSSUSDT");
    assert_eq!(rest.len(), 1, "у книги без доливов лежит только цель");
    let tp = &rest[0].1;
    assert!(tp.buy && tp.reduce && (tp.qty - 0.39).abs() < 1e-9);
    assert!((tp.px - (99.99 * 0.95_f64 * 100.0).floor() / 100.0).abs() < 1e-9, "цель {}", tp.px);
    assert_eq!(kinds(&d), vec!["entry", "take_set"]);
    let e0 = &events(&d)[0];
    assert_eq!(e0["mode"], "live");
    assert_eq!(e0["depth"], "1/1");
    assert!((e0["slip_bp"].as_f64().unwrap() - (-(99.99_f64 / 100.0 - 1.0) * 1e4)).abs() < 1e-6);
    // повтор такта — ничего нового; статус несёт отметку позиции
    let rep = lx.tick(T0 + 125_000);
    assert_eq!(rep.opened + rep.closed, 0);
    let st = lx.status_json(T0 + 125_000, None);
    let p0 = &st["positions"][0];
    assert_eq!(p0["mark_px"], 100.0);
    assert!((p0["upnl_usd"].as_f64().unwrap() - (-(100.0 - 99.99) * 0.39)).abs() < 1e-9, "{p0}");
    assert!(p0["fee_usd"].as_f64().unwrap() > 0.0);
    // цена прошла цель — цель исполнена, позиция закрыта с прибылью
    m.set_px("SSSUSDT", 94.0, 94.02);
    let rep = lx.tick(T0 + 130_000);
    assert_eq!(rep.closed, 1, "{:?}", lx.last_error);
    assert_eq!(m.pos("SSSUSDT"), 0.0);
    let ev = events(&d);
    let last = ev.last().unwrap();
    assert_eq!(last["ev"], "take");
    let gross = (99.99 - tp.px) * 0.39;
    let fees = (99.99 * 0.39 + tp.px * 0.39) * 5.5 / 1e4;
    assert!((last["pnl_usd"].as_f64().unwrap() - (gross - fees)).abs() < 1e-9, "{last}");
    assert!((lx.st.realized_usd - (gross - fees)).abs() < 1e-9);
    assert!(lx.st.positions.is_empty());
    // seq растёт на 1
    let seqs: Vec<i64> = ev.iter().map(|e| e["seq"].as_i64().unwrap()).collect();
    assert_eq!(seqs, (1..=seqs.len() as i64).collect::<Vec<_>>());
}

#[test]
fn лонг_лестница_доливает_переставляет_цель_и_выходит_по_полу() {
    let d = dir("long");
    let m = Mock::new();
    m.set_px("LLLUSDT", 99.99, 100.01);
    write_intents(&d, &[long_intent(1)]);
    let mut lx = ladder(&d, &m, false);
    lx.tick(T0 + 120_000);
    // база: 0.25 × 25 × 8 / середина 100 = 0.50 (покупка по ask 100.01); рунги на 97 / 94 / 91
    let p = lx.st.positions.get("LLLUSDT").cloned().unwrap();
    assert!((p.qty - 0.5).abs() < 1e-9 && p.depth == 1, "{}", p.qty);
    let rungs: Vec<f64> = p.rung_orders.iter().map(|r| r.px).collect();
    assert_eq!(rungs, vec![97.0, 94.0, 91.0]);
    let q2 = (0.25_f64 * 25.0 * 8.0 / 97.0 * 100.0).floor() / 100.0;
    assert!((p.rung_orders[0].qty - q2).abs() < 1e-9);
    let tp0 = p.take.clone().unwrap().px;
    assert!((tp0 - (100.01_f64 * 1.04 * 100.0).ceil() / 100.0).abs() < 1e-9, "цель от средней {tp0}");
    // касание уровня рунга — не исполнение
    m.set_px("LLLUSDT", 96.99, 97.0);
    lx.tick(T0 + 130_000);
    assert_eq!(lx.st.positions["LLLUSDT"].depth, 1, "касание не наливает");
    // проход — наливает, цель переезжает от новой средней
    m.set_px("LLLUSDT", 96.9, 96.95);
    let rep = lx.tick(T0 + 140_000);
    assert_eq!(rep.rungs, 1, "{:?}", lx.last_error);
    let p = lx.st.positions.get("LLLUSDT").cloned().unwrap();
    assert_eq!(p.depth, 2);
    let avg = (0.5 * 100.01 + q2 * 97.0) / (0.5 + q2);
    assert!((p.avg() - avg).abs() < 1e-9);
    let tp1 = p.take.clone().unwrap();
    assert!((tp1.px - (avg * 1.04 * 100.0).ceil() / 100.0).abs() < 1e-9 && (tp1.qty - (0.5 + q2)).abs() < 1e-9);
    assert_eq!(p.floor_px(), Some(85.0), "пол — уровень глубины 2");
    let old_tp = m.orders_of("LLLUSDT").into_iter().filter(|o| o.reduce && o.tif == "GTC").count();
    assert_eq!(old_tp, 2, "старая цель снята, новая стоит");
    assert_eq!(m.resting("LLLUSDT").iter().filter(|(_, o)| o.reduce).count(), 1);
    // цена ниже пола глубины 2 (85), но выше рунга 94? нет — рунг 94 исполнится первым
    m.set_px("LLLUSDT", 93.9, 93.95);
    lx.tick(T0 + 150_000);
    assert_eq!(lx.st.positions["LLLUSDT"].depth, 3);
    // цена 86.9 проходит и последний рунг (91) — он наливается раньше
    // выхода, как на площадке; пол глубины 4 — 88: bid 86.9 → выход
    m.set_px("LLLUSDT", 86.9, 86.95);
    let rep = lx.tick(T0 + 160_000);
    assert_eq!(rep.closed, 1, "{:?} {:?}", lx.last_error, kinds(&d));
    assert_eq!(m.pos("LLLUSDT"), 0.0);
    assert!(m.resting("LLLUSDT").is_empty(), "рунги и цель сняты");
    let last = events(&d).last().cloned().unwrap();
    assert_eq!(last["ev"], "floor");
    assert!(last["pnl_usd"].as_f64().unwrap() < 0.0);
    assert_eq!(last["depth"], "4/4");
    assert_eq!(last["floor_px"], 88.0);
    let k = kinds(&d);
    assert_eq!(k.iter().filter(|x| *x == "rung").count(), 3);
    assert_eq!(k.iter().filter(|x| *x == "take_set").count(), 4);
}

#[test]
fn срок_и_выход_по_намерению_закрывают_позицию() {
    let d = dir("term");
    let m = Mock::new();
    m.set_px("SSSUSDT", 99.99, 100.01);
    write_intents(&d, &[short_intent(1)]);
    let mut lx = ladder(&d, &m, false);
    lx.tick(T0 + 120_000);
    let rep = lx.tick(T0 + 24 * 3600 * 1000 + 1);
    assert_eq!(rep.closed, 1);
    assert_eq!(kinds(&d).last().unwrap(), "term");
    // выход по намерению охраны рынком
    let d2 = dir("exit");
    let m2 = Mock::new();
    m2.set_px("SSSUSDT", 99.99, 100.01);
    write_intents(&d2, &[short_intent(1)]);
    let mut lx2 = ladder(&d2, &m2, false);
    lx2.tick(T0 + 120_000);
    let mut ex = short_intent(2);
    ex["kind"] = json!("exit");
    ex["reason"] = json!("market");
    // чужая позиция того же имени (другая секунда решения) — не трогается
    let mut other = ex.clone();
    other["seq"] = json!(3);
    other["decided_at"] = json!((T0 / 1000 - 3600) as f64);
    write_intents(&d2, &[short_intent(1), ex, other]);
    m2.set_px("SSSUSDT", 101.0, 101.02);
    let rep = lx2.tick(T0 + 3_600_000);
    assert_eq!(rep.closed, 1);
    let last = events(&d2).last().cloned().unwrap();
    assert_eq!(last["ev"], "market");
    assert!(last["pnl_usd"].as_f64().unwrap() < 0.0);
}

#[test]
fn ликвидация_мимо_исполнителя_и_расхождение_ставят_паузу_входов() {
    let d = dir("recon");
    let m = Mock::new();
    m.set_px("SSSUSDT", 99.99, 100.01);
    m.set_px("LLLUSDT", 99.99, 100.01);
    write_intents(&d, &[short_intent(1), long_intent(2)]);
    let mut lx = ladder(&d, &m, false);
    lx.tick(T0 + 120_000);
    assert_eq!(lx.st.positions.len(), 2);
    // биржа закрыла шорт сама (ликвидация) — деньги из closed-pnl
    m.0.borrow_mut().pos.remove("SSSUSDT");
    m.0.borrow_mut().closed_pnl.push(("SSSUSDT".into(), -6.1));
    lx.tick(T0 + 130_000);
    assert!(!lx.st.positions.contains_key("SSSUSDT"));
    let mm: Vec<Value> = events(&d).into_iter().filter(|e| e["ev"] == "mismatch").collect();
    assert_eq!(mm.len(), 1);
    assert!((mm[0]["pnl_usd"].as_f64().unwrap() + 6.1).abs() < 1e-9);
    assert!(lx.st.paused.is_none(), "закрытие мимо — не пауза");
    // количество разъехалось без исполнений — пауза входов, ведём биржевое
    m.0.borrow_mut().pos.insert("LLLUSDT".into(), 0.3);
    lx.tick(T0 + 140_000);
    assert!(lx.st.paused.is_some());
    assert!((lx.st.positions["LLLUSDT"].qty - 0.3).abs() < 1e-9);
    let mut nx = short_intent(3);
    nx["computed_at"] = json!((T0 / 1000) as f64 + 140.0);
    write_intents(&d, &[short_intent(1), long_intent(2), nx]);
    lx.tick(T0 + 150_000);
    let last = events(&d).last().cloned().unwrap();
    assert_eq!(last["ev"], "reject");
    assert!(last["reason"].as_str().unwrap().starts_with("входы на паузе"), "{last}");
    std::fs::write(d.join("RESUME"), "").unwrap();
    lx.tick(T0 + 160_000);
    assert!(lx.st.paused.is_none() && !d.join("RESUME").exists());
    assert!(kinds(&d).contains(&"resume".to_string()));
}

#[test]
fn частичное_исполнение_рунга_видно_сверке_а_не_паузе() {
    let d = dir("partial");
    let m = Mock::new();
    m.set_px("LLLUSDT", 99.99, 100.01);
    write_intents(&d, &[long_intent(1)]);
    let mut lx = ladder(&d, &m, false);
    lx.tick(T0 + 120_000);
    let rid = m.resting("LLLUSDT").into_iter().find(|(_, o)| !o.reduce && (o.px - 97.0).abs() < 1e-9).unwrap().0;
    m.partial(&rid, 0.2);
    lx.tick(T0 + 130_000);
    assert!(lx.st.paused.is_none(), "{:?}", lx.st.paused);
    let p = &lx.st.positions["LLLUSDT"];
    assert!((p.qty - 0.7).abs() < 1e-9 && p.depth == 2, "{} {}", p.qty, p.depth);
    assert!((p.take.as_ref().unwrap().qty - 0.7).abs() < 1e-9, "цель на всё количество");
}

#[test]
fn хедж_режим_счёта_узнаётся_отказом_и_дальше_индекс_по_стороне() {
    let d = dir("hedge");
    let m = Mock::new();
    m.0.borrow_mut().hedge = true;
    m.set_px("SSSUSDT", 99.99, 100.01);
    write_intents(&d, &[short_intent(1)]);
    let mut lx = ladder(&d, &m, false);
    let rep = lx.tick(T0 + 120_000);
    assert_eq!(rep.opened, 1, "{:?} {:?}", lx.last_error, kinds(&d));
    assert!(lx.st.hedge);
    let idx: Vec<i64> = m.orders_of("SSSUSDT").iter().map(|o| o.idx).collect();
    assert!(idx.iter().all(|i| *i == 2), "шорт в хедже — индекс 2: {idx:?}");
}

#[test]
fn отказы_входа_названы_причиной_и_ничего_не_ставят() {
    let m = Mock::new();
    m.set_px("SSSUSDT", 99.99, 100.01);
    // устаревшее намерение
    let d = dir("stale");
    write_intents(&d, &[short_intent(1)]);
    let mut lx = ladder(&d, &m, false);
    lx.tick(T0 + 60_000 + 21 * 60_000);
    assert!(events(&d)[0]["reason"].as_str().unwrap().starts_with("намерение устарело"));
    assert_eq!(m.0.borrow().order_calls, 0);
    // NO_ENTRIES
    let d = dir("noent");
    std::fs::write(d.join("NO_ENTRIES"), "").unwrap();
    write_intents(&d, &[short_intent(1)]);
    ladder(&d, &m, false).tick(T0 + 120_000);
    assert!(events(&d)[0]["reason"].as_str().unwrap().contains("NO_ENTRIES"));
    // чужая позиция на счёте
    let d = dir("foreign");
    m.0.borrow_mut().pos.insert("SSSUSDT".into(), 1.0);
    write_intents(&d, &[short_intent(1)]);
    ladder(&d, &m, false).tick(T0 + 120_000);
    assert!(events(&d)[0]["reason"].as_str().unwrap().contains("чужая позиция"));
    m.0.borrow_mut().pos.clear();
    // мельче минимума биржи
    let d = dir("small");
    let mut s = short_intent(1);
    s["margin_usd"] = json!(0.5);
    write_intents(&d, &[s]);
    ladder(&d, &m, false).tick(T0 + 120_000);
    assert!(events(&d)[0]["reason"].as_str().unwrap().starts_with("база мельче минимума"));
    // плечо не выставилось — отказ входа
    let d = dir("lev");
    m.0.borrow_mut().lev_error = Some("retCode 110013 cannot set leverage".into());
    write_intents(&d, &[short_intent(1)]);
    ladder(&d, &m, false).tick(T0 + 120_000);
    assert!(events(&d)[0]["reason"].as_str().unwrap().starts_with("плечо 25.00× не выставилось"));
    m.0.borrow_mut().lev_error = None;
    assert_eq!(m.0.borrow().order_calls, 0, "ни одна заявка не ушла");
    // KILL — ничего, даже намерения не читаются
    let d = dir("kill");
    std::fs::write(d.join("KILL"), "").unwrap();
    write_intents(&d, &[short_intent(1)]);
    let mut lx = ladder(&d, &m, false);
    lx.tick(T0 + 120_000);
    assert!(events(&d).is_empty() && lx.st.seq_done == 0);
}

#[test]
fn сухой_режим_пишет_вход_и_ничего_не_отправляет() {
    let d = dir("dry");
    let m = Mock::new();
    m.set_px("SSSUSDT", 99.99, 100.01);
    write_intents(&d, &[short_intent(1)]);
    let mut lx = ladder(&d, &m, true);
    let rep = lx.tick(T0 + 120_000);
    assert_eq!(rep.opened, 1);
    assert_eq!(m.0.borrow().order_calls, 0);
    let e = &events(&d)[0];
    assert_eq!(e["mode"], "dry");
    assert_eq!(e["ev"], "entry");
    assert!(lx.st.positions.is_empty());
}

#[test]
fn перезапуск_продолжает_позиции_и_нумерацию_журнала() {
    let d = dir("restart");
    let m = Mock::new();
    m.set_px("SSSUSDT", 99.99, 100.01);
    write_intents(&d, &[short_intent(1)]);
    {
        let mut lx = ladder(&d, &m, false);
        lx.tick(T0 + 120_000);
    }
    let mut lx = ladder(&d, &m, false);
    assert_eq!(lx.st.positions.len(), 1);
    assert_eq!(lx.st.seq_done, 1);
    let rep = lx.tick(T0 + 125_000);
    assert_eq!(rep.opened, 0, "намерение не исполняется второй раз");
    m.set_px("SSSUSDT", 94.0, 94.02);
    lx.tick(T0 + 130_000);
    let seqs: Vec<i64> = events(&d).iter().map(|e| e["seq"].as_i64().unwrap()).collect();
    assert_eq!(seqs, vec![1, 2, 3]);
    let st: Value = serde_json::from_str(&std::fs::read_to_string(d.join("ladder_status.json")).unwrap()).unwrap();
    assert_eq!(st["positions"].as_array().unwrap().len(), 0);
    assert!(st["realized_usd"].as_f64().unwrap() > 0.0);
}
