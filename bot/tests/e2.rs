//! Тесты E2: тень обязана сходиться с Python-счётом до цента.
//!
//! Фикстура порождена НАСТОЯЩИМИ `trades.build` + `trades.account`
//! (`gen_parity.py`) и лежит в git: здесь Rust-движок читает те же
//! `picks.jsonl`/`review.jsonl` и обязан выдать те же размеры, те же
//! нетто и те же деньги. Это сверка E2 в миниатюре — расхождение
//! формул любой из сторон называет конкретную сделку.

use bot::engine::{shadow, Cfg};
use bot::events::Event;
use bot::journal::read_all;
use bot::paper::{py_round, FeeTable};
use bot::picks::hour_ms;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/parity")
}

fn tmp(name: &str) -> PathBuf {
    let p = std::env::temp_dir()
        .join(format!("bot-e2-{}-{}", std::process::id(), name));
    let _ = fs::remove_dir_all(&p);
    fs::create_dir_all(&p).unwrap();
    p
}

fn cfg(journal: &PathBuf) -> Cfg {
    // «Сейчас» — час спустя срока закрытия последнего часа фикстуры.
    let now = hour_ms("2026-08-05-12").unwrap() + 3_600_000 + 5 * 3_600_000;
    Cfg {
        s8_dir: fixture(),
        journal_dir: journal.clone(),
        arm: "gbm".into(),
        capital_usd: 1000.0,
        fees: FeeTable::load(&fixture().join("fees.json")),
        now_ms: now,
    }
}

#[derive(serde::Deserialize)]
struct Expected {
    balance: f64,
    trades: Vec<ExpTrade>,
}
#[derive(serde::Deserialize)]
struct ExpTrade {
    pos: String,
    size: f64,
    state: String,
    #[serde(default)]
    pnl: Option<f64>,
    #[serde(default)]
    fill_in: Option<f64>,
    #[serde(default)]
    fill_out: Option<f64>,
    #[serde(default)]
    basis: Option<String>,
    #[serde(default)]
    reason: Option<String>,
}

#[test]
fn тень_сходится_с_питон_счётом_до_цента() {
    let jd = tmp("parity");
    let (rep, st) = shadow(&cfg(&jd)).unwrap();
    let exp: Expected = serde_json::from_str(
        &fs::read_to_string(fixture().join("expected.json")).unwrap(),
    )
    .unwrap();

    let n_closed = exp.trades.iter().filter(|t| t.state == "закрыта").count();
    let n_open = exp.trades.len() - n_closed;
    assert_eq!(rep.opened, exp.trades.len(), "входов столько же");
    assert_eq!(rep.closed, n_closed, "выходов столько же");
    assert_eq!(rep.waiting_review as usize, n_open, "остальные ждут разбора");
    assert_eq!(rep.rejected, 0);

    // Журнал → карты фактов по ключу позиции.
    let (records, _) = read_all(&jd).unwrap();
    let mut opens: BTreeMap<String, (f64, Option<f64>)> = BTreeMap::new();
    let mut closes: BTreeMap<String, (f64, Option<f64>, String)> =
        BTreeMap::new();
    for r in &records {
        match &r.event {
            Event::Open { pos, notional_usd, entry_px, .. } => {
                opens.insert(pos.clone(), (*notional_usd, *entry_px));
            }
            Event::Close { pos, pnl_usd, exit_px, reason, .. } => {
                closes.insert(
                    pos.clone(),
                    (*pnl_usd, *exit_px, reason.clone()),
                );
            }
            _ => {}
        }
    }

    for t in &exp.trades {
        let (size, entry_px) = opens
            .get(&t.pos)
            .unwrap_or_else(|| panic!("нет входа {}", t.pos));
        assert_eq!(*size, t.size, "размер {}", t.pos);
        if t.state == "закрыта" {
            let (pnl, exit_px, reason) = closes
                .get(&t.pos)
                .unwrap_or_else(|| panic!("нет выхода {}", t.pos));
            // Журнал несёт полную точность; запись Python округлена
            // до цента — сравнение через то же округление.
            assert_eq!(py_round(*pnl, 2), t.pnl.unwrap(), "деньги {}", t.pos);
            // У сделки по книге цены исполнения обязаны совпасть
            // ДОСЛОВНО: одна лесенка, одна арифметика обхода.
            if t.basis.as_deref() == Some("книга") {
                assert_eq!(*entry_px, t.fill_in, "вход {}", t.pos);
                assert_eq!(*exit_px, t.fill_out, "выход {}", t.pos);
                assert!(reason.contains("книга"), "{reason}");
            } else {
                assert!(reason.contains("плоский"), "{reason}");
            }
        } else {
            assert!(!closes.contains_key(&t.pos), "{} закрыт лишним", t.pos);
        }
    }

    // Баланс: свободная касса плюс занятое — и ровно то число, что
    // вернул Python-счёт.
    let busy: f64 = st.positions.values().map(|p| p.notional_usd).sum();
    assert_eq!(py_round(st.cash_usd + busy, 2), exp.balance, "баланс");

    // Идемпотентность: второй проход не дописывает ничего.
    let (rep2, _) = shadow(&cfg(&jd)).unwrap();
    assert_eq!(rep2.appended, 0, "повторный проход обязан быть пустым");
}

#[test]
fn ситуационная_тень_сходится_с_питон_счётом() {
    // Книга без срока: вход секундой события, закрытие задаёт разбор,
    // слоты кассы фиксированы манифестом. Ожидание порождено
    // НАСТОЯЩИМИ trades.build + account на тех же файлах.
    let sit = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/parity_sit");
    let jd = tmp("parity-sit");
    let now = hour_ms("2026-08-05-11").unwrap() + 2 * 3_600_000;
    let cfg = Cfg {
        s8_dir: sit.clone(),
        journal_dir: jd.clone(),
        arm: "gbm".into(),
        capital_usd: 1000.0,
        fees: FeeTable::load(&sit.join("fees.json")),
        now_ms: now,
    };
    let (rep, st) = shadow(&cfg).unwrap();
    let exp: Expected = serde_json::from_str(
        &fs::read_to_string(sit.join("expected.json")).unwrap(),
    )
    .unwrap();
    let n_closed =
        exp.trades.iter().filter(|t| t.state == "закрыта").count();
    assert_eq!(rep.opened, exp.trades.len(), "входов столько же");
    assert_eq!(rep.closed, n_closed, "выходов столько же");
    assert_eq!(
        rep.waiting_review, 0,
        "у открытой ситуационной сделки срок не выходит — ждать нечего"
    );

    let (records, _) = read_all(&jd).unwrap();
    let mut opens: BTreeMap<String, f64> = BTreeMap::new();
    let mut closes: BTreeMap<String, (f64, String)> = BTreeMap::new();
    for r in &records {
        match &r.event {
            Event::Open { pos, notional_usd, .. } => {
                opens.insert(pos.clone(), *notional_usd);
            }
            Event::Close { pos, pnl_usd, reason, .. } => {
                closes.insert(pos.clone(), (*pnl_usd, reason.clone()));
            }
            _ => {}
        }
    }
    for t in &exp.trades {
        let size = opens
            .get(&t.pos)
            .unwrap_or_else(|| panic!("нет входа {}", t.pos));
        assert_eq!(*size, t.size, "размер {}", t.pos);
        if t.state == "закрыта" {
            let (pnl, reason) = closes
                .get(&t.pos)
                .unwrap_or_else(|| panic!("нет выхода {}", t.pos));
            assert_eq!(py_round(*pnl, 2), t.pnl.unwrap(), "деньги {}", t.pos);
            // Причина выхода — дословно из разбора.
            let want = t.reason.as_deref().unwrap_or("срок");
            assert!(reason.contains(want), "{reason} vs {want}");
        } else {
            assert!(!closes.contains_key(&t.pos), "{} закрыт лишним", t.pos);
        }
    }
    let busy: f64 = st.positions.values().map(|p| p.notional_usd).sum();
    assert_eq!(py_round(st.cash_usd + busy, 2), exp.balance, "баланс");

    // Идемпотентность: второй проход не дописывает ничего.
    let (rep2, _) = shadow(&cfg).unwrap();
    assert_eq!(rep2.appended, 0, "повторный проход обязан быть пустым");
}

#[test]
fn выключатель_отвергает_входы_и_отказ_терминален() {
    let jd = tmp("kill");
    fs::write(jd.join("KILL"), b"").unwrap();
    let (rep, st) = shadow(&cfg(&jd)).unwrap();
    assert_eq!(rep.opened, 0, "при выключателе входов нет");
    assert_eq!(rep.rejected, 12, "каждое намерение отвергнуто и записано");
    assert!(st.kill);
    assert_eq!(st.cash_usd, 1000.0, "деньги не тронуты");
    // Выключатель снят: прошлые отказы НЕ переигрываются — их момент
    // прошёл, вход задним числом был бы выдумкой.
    fs::remove_file(jd.join("KILL")).unwrap();
    let (rep2, st2) = shadow(&cfg(&jd)).unwrap();
    assert!(!st2.kill);
    assert_eq!(rep2.opened, 0, "отказ терминален");
    assert_eq!(rep2.appended, 1, "дописан только поворот выключателя");
}
