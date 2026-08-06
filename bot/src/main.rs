//! `bot state <каталог> [капитал]` — вывести состояние из журнала.
//!
//! Единственная команда E1: посмотреть глазами то, что выводят тесты.
//! Причины отказов печатаются словами и кодом 2 — молчаливый отказ
//! неотличим от пустого журнала.

use std::path::Path;
use std::process::exit;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("state") => {
            let dir = match args.get(2) {
                Some(d) => d,
                None => {
                    eprintln!("нужен каталог журнала: bot state <dir> [капитал]");
                    exit(2);
                }
            };
            let capital: f64 = args
                .get(3)
                .map(|s| s.parse().unwrap_or(1000.0))
                .unwrap_or(1000.0);
            let (_, records, report) = match bot::journal::Journal::open(Path::new(dir)) {
                Ok(x) => x,
                Err(e) => {
                    eprintln!("журнал не читается: {e}");
                    exit(2);
                }
            };
            let st = match bot::state::derive(capital, &records) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("состояние не выводится: {e}");
                    exit(2);
                }
            };
            println!("{}", serde_json::to_string_pretty(&st).expect("json"));
            if report.dropped_tail > 0 || report.gz_salvaged > 0 {
                eprintln!(
                    "замечания чтения: оборванных строк в хвосте {}, спасённых суток {}",
                    report.dropped_tail, report.gz_salvaged
                );
            }
        }
        Some("check") => {
            // bot check <журнал> [капитал] [--now-ms N] — сторож:
            // инварианты счёта; выход 1 при нарушении.
            let dir = match args.get(2) {
                Some(d) => d.clone(),
                None => {
                    eprintln!("нужен каталог журнала: bot check <dir>");
                    exit(2);
                }
            };
            let capital: f64 = args
                .get(3)
                .and_then(|s| s.parse().ok())
                .unwrap_or(1000.0);
            let mut now_ms: Option<i64> = None;
            let mut it = args[3..].iter();
            while let Some(a) = it.next() {
                if a == "--now-ms" {
                    now_ms = it.next().and_then(|v| v.parse().ok());
                }
            }
            let now_ms = now_ms.unwrap_or_else(|| {
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|d| d.as_millis() as i64)
                    .unwrap_or(0)
            });
            let (_, records, _) = match bot::journal::Journal::open(Path::new(&dir)) {
                Ok(x) => x,
                Err(e) => {
                    eprintln!("журнал не читается: {e}");
                    exit(2);
                }
            };
            let st = match bot::state::derive(capital, &records) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("состояние не выводится: {e}");
                    exit(2);
                }
            };
            let rep = bot::check::verify(
                capital,
                &records,
                &st,
                &bot::check::CheckOpts { now_ms, ..Default::default() },
            );
            println!("{}", serde_json::to_string_pretty(&rep).expect("json"));
            if !rep.ok {
                exit(1);
            }
        }
        Some("shadow") => {
            // bot shadow --s8 DIR --journal DIR [--arm gbm]
            //            [--capital 1000] [--fees PATH] [--now-ms N]
            let mut s8 = None;
            let mut jr = None;
            let mut arm = "gbm".to_string();
            let mut capital = 1000.0_f64;
            let mut fees_path = None;
            let mut now_ms: Option<i64> = None;
            let mut it = args[2..].iter();
            while let Some(a) = it.next() {
                let mut val = || it.next().cloned().unwrap_or_default();
                match a.as_str() {
                    "--s8" => s8 = Some(val()),
                    "--journal" => jr = Some(val()),
                    "--arm" => arm = val(),
                    "--capital" => capital = val().parse().unwrap_or(1000.0),
                    "--fees" => fees_path = Some(val()),
                    "--now-ms" => now_ms = val().parse().ok(),
                    other => {
                        eprintln!("неизвестный ключ {other}");
                        exit(2);
                    }
                }
            }
            let (Some(s8), Some(jr)) = (s8, jr) else {
                eprintln!("нужны --s8 и --journal");
                exit(2);
            };
            let fees = match &fees_path {
                Some(p) => bot::paper::FeeTable::load(Path::new(p)),
                None => bot::paper::FeeTable::load(
                    &bot::engine::default_fees_path(Path::new(".")),
                ),
            };
            if fees.is_empty() {
                // Пустая таблица — работаем на умолчании, но говорим об
                // этом: молчаливое умолчание неотличимо от измерения.
                eprintln!("ставки не прочитаны — весь счёт на умолчании 5.5 б.п.");
            }
            let now_ms = now_ms.unwrap_or_else(|| {
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|d| d.as_millis() as i64)
                    .unwrap_or(0)
            });
            let cfg = bot::engine::Cfg {
                s8_dir: s8.into(),
                journal_dir: jr.into(),
                arm,
                capital_usd: capital,
                fees,
                now_ms,
            };
            match bot::engine::shadow(&cfg) {
                Ok((rep, st)) => {
                    eprintln!(
                        "проход: событий {}, входов {}, выходов {}, \
                         отказов {}, ждут разбора {}",
                        rep.appended, rep.opened, rep.closed,
                        rep.rejected, rep.waiting_review
                    );
                    println!(
                        "{}",
                        serde_json::to_string_pretty(&st).expect("json")
                    );
                }
                Err(e) => {
                    eprintln!("тень не прошла: {e}");
                    exit(2);
                }
            }
        }
        _ => {
            eprintln!(
                "использование: bot state <каталог> [капитал] | bot shadow …"
            );
            exit(2);
        }
    }
}
