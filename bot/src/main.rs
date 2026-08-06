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
        _ => {
            eprintln!("использование: bot state <каталог-журнала> [капитал]");
            exit(2);
        }
    }
}
