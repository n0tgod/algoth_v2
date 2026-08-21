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

    // Нулевой размер у Python-кассы (потолок имени, пустая касса) пар
    // ОТКАЗУ ядра — конвенция сверки: «отказ по пустой кассе — законная
    // пара нулевому размеру». Позиция нулевого размера не открывается.
    let sized: Vec<_> =
        exp.trades.iter().filter(|t| t.size > 0.0).collect();
    let n_zero = exp.trades.len() - sized.len();
    let n_closed = sized.iter().filter(|t| t.state == "закрыта").count();
    let n_open = sized.len() - n_closed;
    assert_eq!(rep.opened, sized.len(), "входов столько же");
    assert_eq!(rep.closed, n_closed, "выходов столько же");
    assert_eq!(rep.waiting_review as usize, n_open, "остальные ждут разбора");
    assert_eq!(rep.rejected, n_zero, "нулевые размеры — отказы ядра");

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
        if t.size <= 0.0 {
            assert!(!opens.contains_key(&t.pos),
                    "нулевой размер открыт ядром: {}", t.pos);
            continue;
        }
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
fn журнал_переначинается_со_сменой_правил_книги() {
    use bot::engine::fresh_journal_on_rules_change;
    let sit = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/parity_sit"); // манифест с rules_version
    let jd = tmp("rules-journal");
    // Журнал без маркера при объявленных правилах — отставляется:
    // доказать свою версию он не умеет (живая миграция v2 → v3).
    fs::write(jd.join("journal-2026-08-07.jsonl"), b"").unwrap();
    fs::write(jd.join("KILL"), b"").unwrap();
    let dst = fresh_journal_on_rules_change(&sit, &jd).unwrap();
    let dst = dst.expect("журнал обязан отставиться");
    assert!(dst.join("journal-2026-08-07.jsonl").exists());
    assert!(!jd.join("journal-2026-08-07.jsonl").exists());
    assert!(
        jd.join("KILL").exists(),
        "выключатель не снимается сменой книги"
    );
    assert!(jd.join("rules_version.txt").exists());
    // Повторный вызов — пустой: версия совпала.
    assert!(fresh_journal_on_rules_change(&sit, &jd).unwrap().is_none());
    // Книга без объявленных правил журнал не трогает.
    let plain = fixture(); // главная книга: rules_version в манифесте нет
    assert!(
        fresh_journal_on_rules_change(&plain, &jd).unwrap().is_none()
    );
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

/// Срок жизни позиции берётся у КНИГИ журнала, а не зашит четвёркой.
///
/// Живой случай: тень ведёт ситуационную книгу (без срока, предел
/// возраста 24 ч), а проверка считала сроком 4 ч и объявляла
/// «застряла» позиции, прожившие законные 15 часов. Панель ядра
/// выглядела отказом на исправном ядре — тревога, которая кричит
/// ложно, перестаёт быть сигналом.
#[test]
fn срок_позиции_читается_у_книги_журнала() {
    use std::io::Write;
    let d = tmp("hold-from-book");
    let s8 = d.join("model_sit");
    std::fs::create_dir_all(&s8).unwrap();
    std::fs::write(
        s8.join("manifest.json"),
        br#"{"situational": true, "slots": 6, "max_age_h": 24}"#,
    )
    .unwrap();
    let jr = d.join("journal");
    std::fs::create_dir_all(&jr).unwrap();
    // Маркер несёт ДВА поля: путь и версию правила кассы. Разбирать
    // надо первым полем — целиком он однажды уже ломал показ.
    let mut f = std::fs::File::create(jr.join("source.txt")).unwrap();
    write!(f, "{} cash=5\n", s8.display()).unwrap();
    assert_eq!(bot::check::hold_from_journal(&jr), 24);

    // Книга со сроком отдаёт свой горизонт, а не умолчание.
    let s24 = d.join("model_h24");
    std::fs::create_dir_all(&s24).unwrap();
    std::fs::write(s24.join("manifest.json"), br#"{"horizon_h": 24}"#)
        .unwrap();
    let jr2 = d.join("journal24");
    std::fs::create_dir_all(&jr2).unwrap();
    std::fs::write(jr2.join("source.txt"), format!("{}\n", s24.display()))
        .unwrap();
    assert_eq!(bot::check::hold_from_journal(&jr2), 24);

    // Нет маркера — прежнее умолчание, а не паника.
    let jr3 = d.join("journal-bare");
    std::fs::create_dir_all(&jr3).unwrap();
    assert_eq!(bot::check::hold_from_journal(&jr3), 4);

    // И главное — ДОРОГА до проверки: позиция книги без срока,
    // прожившая 15 часов, законна, и «застряла» о ней говорить
    // нельзя. Отрицательный контроль на зашитую четвёрку кусается
    // только через эту связку.
    let now = 1_787_318_000_000i64;
    let recs = vec![bot::events::Record {
        seq: 1,
        event: Event::Open {
            pos: "gbm:2026-08-20-20:SUNUSDT:long".into(),
            sym: "SUNUSDT".into(),
            side: bot::events::Side::Long,
            notional_usd: 300.0,
            entry_px: Some(1.0),
            fee_usd: 0.02,
            partial: false,
            ver: Some(3),
            at_ms: now - 15 * 3_600_000,
        },
    }];
    let st = bot::state::derive(3000.0, &recs).unwrap();
    let rep = bot::check::verify_journal(&jr, 3000.0, &recs, &st, now);
    assert!(
        !rep.warnings.iter().any(|w| w.contains("застряла")),
        "законная позиция книги без срока объявлена застрявшей: {:?}",
        rep.warnings
    );
    // Встречная сторона: у книги 4 ч та же позиция застряла, и
    // проверка обязана это сказать — иначе, починив ложную тревогу,
    // мы потеряли бы настоящую. У книги 24 ч она законна (срок плюс
    // запас в 3 ч), и это тоже проверяется числом.
    let s4 = d.join("model_h4");
    std::fs::create_dir_all(&s4).unwrap();
    std::fs::write(s4.join("manifest.json"), br#"{"horizon_h": 4}"#)
        .unwrap();
    let jr4 = d.join("journal4");
    std::fs::create_dir_all(&jr4).unwrap();
    std::fs::write(jr4.join("source.txt"), format!("{}\n", s4.display()))
        .unwrap();
    let rep4 = bot::check::verify_journal(&jr4, 3000.0, &recs, &st, now);
    assert!(
        rep4.warnings.iter().any(|w| w.contains("застряла")),
        "у книги 4 ч позиция 15 ч обязана считаться застрявшей: {:?}",
        rep4.warnings
    );
    let rep2 = bot::check::verify_journal(&jr2, 3000.0, &recs, &st, now);
    assert!(
        !rep2.warnings.iter().any(|w| w.contains("застряла")),
        "у книги 24 ч позиция 15 ч застрявшей не является"
    );
}
