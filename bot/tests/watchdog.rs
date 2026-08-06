//! Тесты сторожа исполнения: инварианты (`check`) и сверка (`sverka.py`).
//!
//! Сторож, которого нельзя уронить, — не сторож: у каждой проверки есть
//! отрицательный контроль — журнал с нарочно испорченным местом, на
//! котором сторож обязан назвать нарушение, и чистый прогон, на котором
//! обязан молчать нарушениями (но говорить числами).

use bot::check::{verify, CheckOpts};
use bot::engine::{shadow, Cfg};
use bot::events::{Event, Side};
use bot::journal::{read_all, Journal};
use bot::paper::FeeTable;
use bot::picks::hour_ms;
use bot::state::derive;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

const T0: i64 = 1_785_931_200_000; // 2026-08-05 12:00 UTC

fn tmp(name: &str) -> PathBuf {
    let p = std::env::temp_dir()
        .join(format!("bot-wd-{}-{}", std::process::id(), name));
    let _ = fs::remove_dir_all(&p);
    fs::create_dir_all(&p).unwrap();
    p
}

fn opts(now_ms: i64) -> CheckOpts {
    CheckOpts { now_ms, ..Default::default() }
}

fn open_ev(pos: &str, notional: f64, at: i64) -> Event {
    Event::Open {
        pos: pos.into(),
        sym: "AUSDT".into(),
        side: Side::Long,
        notional_usd: notional,
        entry_px: Some(100.0),
        fee_usd: 0.0,
        partial: false,
        ver: Some(3),
        at_ms: at,
    }
}

#[test]
fn чистый_журнал_проходит_и_несёт_числа() {
    let d = tmp("clean");
    let (mut j, _, _) = Journal::open(&d).unwrap();
    j.append(Event::Decision {
        arm: "gbm".into(),
        hour: "2026-08-05-11".into(),
        sym: "AUSDT".into(),
        side: Side::Long,
        px: Some(100.0),
        ver: Some(3),
        at_ms: T0,
    })
    .unwrap();
    j.append(open_ev("p1", 41.66, T0)).unwrap();
    j.append(Event::Close {
        pos: "p1".into(),
        exit_px: Some(101.0),
        fee_usd: 0.0,
        pnl_usd: 1.25,
        reason: "срок (книга)".into(),
        at_ms: T0 + 3_600_000,
    })
    .unwrap();
    let (records, _) = read_all(&d).unwrap();
    let st = derive(1000.0, &records).unwrap();
    let rep = verify(1000.0, &records, &st, &opts(T0 + 2 * 3_600_000));
    assert!(rep.ok, "{:?}", rep.violations);
    assert!(rep.warnings.is_empty(), "{:?}", rep.warnings);
    assert_eq!((rep.events, rep.open_positions), (3, 0));
}

#[test]
fn расхождение_кассы_с_историей_названо() {
    // Состояние подделывается мимо `derive` — ровно тот случай, когда
    // вывод состояния разошёлся бы с историей из-за дефекта.
    let d = tmp("cash");
    let (mut j, _, _) = Journal::open(&d).unwrap();
    j.append(open_ev("p1", 100.0, T0)).unwrap();
    let (records, _) = read_all(&d).unwrap();
    let mut st = derive(1000.0, &records).unwrap();
    st.cash_usd += 3.0; // «потерянные» три доллара
    let rep = verify(1000.0, &records, &st, &opts(T0 + 1_000));
    assert!(!rep.ok);
    assert!(
        rep.violations.iter().any(|v| v.contains("касса разошлась")),
        "{:?}",
        rep.violations
    );
}

#[test]
fn плечо_выше_единицы_это_нарушение() {
    let d = tmp("lev");
    let (mut j, _, _) = Journal::open(&d).unwrap();
    j.append(open_ev("p1", 700.0, T0)).unwrap();
    j.append(open_ev("p2", 700.0, T0 + 1_000)).unwrap();
    let (records, _) = read_all(&d).unwrap();
    let st = derive(1000.0, &records).unwrap();
    let rep = verify(1000.0, &records, &st, &opts(T0 + 2_000));
    assert!(!rep.ok);
    assert!(
        rep.violations.iter().any(|v| v.contains("плечо выше 1×")),
        "{:?}",
        rep.violations
    );
}

#[test]
fn застрявшая_позиция_и_тишина_решений_это_предупреждения() {
    let d = tmp("stuck");
    let (mut j, _, _) = Journal::open(&d).unwrap();
    j.append(Event::Decision {
        arm: "gbm".into(),
        hour: "2026-08-05-11".into(),
        sym: "AUSDT".into(),
        side: Side::Long,
        px: None,
        ver: None,
        at_ms: T0,
    })
    .unwrap();
    j.append(open_ev("p1", 41.66, T0)).unwrap();
    let (records, _) = read_all(&d).unwrap();
    let st = derive(1000.0, &records).unwrap();
    // Десять часов спустя: позиция с 4-часовым сроком висит, решений
    // не было — оба предупреждения обязаны быть, нарушений нет.
    let rep = verify(1000.0, &records, &st, &opts(T0 + 10 * 3_600_000));
    assert!(rep.ok, "{:?}", rep.violations);
    assert!(rep.warnings.iter().any(|w| w.contains("застряла p1")));
    assert!(rep.warnings.iter().any(|w| w.contains("решений нет")));
    // А убыток больше размера у ЛОНГА — повод смотреть сделку.
    j.append(Event::Close {
        pos: "p1".into(),
        exit_px: Some(1.0),
        fee_usd: 0.0,
        pnl_usd: -60.0,
        reason: "срок (книга)".into(),
        at_ms: T0 + 11 * 3_600_000,
    })
    .unwrap();
    let (records, _) = read_all(&d).unwrap();
    let st = derive(1000.0, &records).unwrap();
    let rep = verify(1000.0, &records, &st, &opts(T0 + 12 * 3_600_000));
    assert!(rep
        .warnings
        .iter()
        .any(|w| w.contains("больше размера")));
}

/// Сверка на фикстуре чётности: Rust-журнал против Python-счёта.
/// Отрицательный контроль — подделанные деньги одной сделки, которые
/// сверка обязана назвать по имени.
#[test]
fn сверка_чиста_на_фикстуре_и_кусается_на_подделке() {
    let Ok(py) = which_python() else {
        eprintln!("python3 не найден — сверка пропущена");
        return;
    };
    let fixture =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/parity");
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf();
    let jd = tmp("sverka");
    let now = hour_ms("2026-08-05-12").unwrap() + 3_600_000 + 5 * 3_600_000;
    let cfg = Cfg {
        s8_dir: fixture.clone(),
        journal_dir: jd.clone(),
        arm: "gbm".into(),
        capital_usd: 1000.0,
        fees: FeeTable::load(&fixture.join("fees.json")),
        now_ms: now,
    };
    shadow(&cfg).unwrap();

    let run = |jdir: &PathBuf| {
        Command::new(&py)
            .current_dir(&repo)
            .args([
                "bot/sverka.py",
                "--s8",
                fixture.to_str().unwrap(),
                "--journal",
                jdir.to_str().unwrap(),
                "--fees",
                fixture.join("fees.json").to_str().unwrap(),
                "--now",
                &format!("{}", now / 1000),
            ])
            .output()
            .expect("запуск sverka.py")
    };
    let out = run(&jd);
    let text = String::from_utf8_lossy(&out.stdout).into_owned();
    assert!(
        out.status.success() && text.contains("расхождений 0"),
        "чистая сверка не прошла:\n{text}{}",
        String::from_utf8_lossy(&out.stderr)
    );

    // Подделка: +5 $ к деньгам одной закрытой сделки в копии журнала.
    let jd2 = tmp("sverka-bad");
    let mut poisoned = None;
    for e in fs::read_dir(&jd).unwrap() {
        let p = e.unwrap().path();
        let name = p.file_name().unwrap().to_str().unwrap().to_string();
        // Рядом с журналом лежит и отчёт первой сверки — копируется и
        // подделывается только сам журнал.
        if !name.starts_with("journal-") || !name.ends_with(".jsonl") {
            continue;
        }
        let text = fs::read_to_string(&p).unwrap();
        let mut out_lines = Vec::new();
        for line in text.lines() {
            let mut v: serde_json::Value = serde_json::from_str(line).unwrap();
            if poisoned.is_none() && v["ev"] == "close" {
                let pnl = v["pnl_usd"].as_f64().unwrap();
                v["pnl_usd"] = serde_json::json!(pnl + 5.0);
                poisoned = Some(v["pos"].as_str().unwrap().to_string());
            }
            out_lines.push(serde_json::to_string(&v).unwrap());
        }
        fs::write(jd2.join(name), out_lines.join("\n") + "\n").unwrap();
    }
    let pos = poisoned.expect("в журнале есть закрытая сделка");
    let out = run(&jd2);
    let text = String::from_utf8_lossy(&out.stdout).into_owned();
    assert!(!out.status.success(), "подделка прошла сверку:\n{text}");
    assert!(
        text.contains(&pos) && text.contains("деньги"),
        "сделка не названа по имени:\n{text}"
    );
}

fn which_python() -> Result<String, ()> {
    for c in ["python3", "python"] {
        if Command::new(c).arg("--version").output().is_ok() {
            return Ok(c.into());
        }
    }
    Err(())
}
