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
                .map(|s| s.parse().unwrap_or(3000.0))
                .unwrap_or(3000.0);
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
        Some("run") => {
            // bot run --s8 DIR --journal DIR [--arm gbm] [--capital N]
            //         [--fees PATH] [--interval-sec 60]
            //         [--sverka bot/sverka.py] [--python python3]
            let mut s8 = None;
            let mut jr = None;
            let mut arm = "gbm".to_string();
            // Умолчание для РУЧНОГО запуска; живой контур передаёт
            // --capital из ядра расчёта (tools/run_bot.sh спрашивает
            // trades.START_BALANCE). 3000 — решение владельца
            // 2026-08-13; та же цифра во всех ветках разбора аргументов.
            let mut capital = 3000.0_f64;
            let mut fees_path = "research/a1_universe/out/fees.json".to_string();
            let mut interval = 60u64;
            let mut sverka_script: Option<String> = None;
            let mut python = "python3".to_string();
            let mut it = args[2..].iter();
            while let Some(a) = it.next() {
                let mut val = || it.next().cloned().unwrap_or_default();
                match a.as_str() {
                    "--s8" => s8 = Some(val()),
                    "--journal" => jr = Some(val()),
                    "--arm" => arm = val(),
                    "--capital" => capital = val().parse().unwrap_or(3000.0),
                    "--fees" => fees_path = val(),
                    "--interval-sec" => interval = val().parse().unwrap_or(60),
                    "--sverka" => sverka_script = Some(val()),
                    "--python" => python = val(),
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
            let cfg = bot::daemon::DaemonCfg {
                s8_dir: s8.into(),
                journal_dir: jr.into(),
                arm,
                capital_usd: capital,
                fees_path: fees_path.into(),
                interval_sec: interval.max(5),
                sverka: sverka_script.map(|sc| bot::daemon::SverkaCfg {
                    python,
                    script: sc.into(),
                }),
            };
            eprintln!(
                "демон тени: рука {}, интервал {} с, сверка {}",
                cfg.arm,
                cfg.interval_sec,
                if cfg.sverka.is_some() { "включена" } else { "НЕ настроена" }
            );
            bot::daemon::run(&cfg);
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
                .unwrap_or(3000.0);
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
            // Срок жизни позиции берётся у КНИГИ, которую ведёт
            // журнал: путь к ней лежит в маркере источника, режим — в
            // её манифесте. Зашитая четвёрка кричала «застряла» на
            // законных позициях книги без срока (предел возраста 24 ч),
            // и панель выглядела отказом на исправном ядре.
            let rep = bot::check::verify_journal(
                Path::new(&dir),
                capital,
                &records,
                &st,
                now_ms,
            );
            println!("{}", serde_json::to_string_pretty(&rep).expect("json"));
            if !rep.ok {
                exit(1);
            }
        }
        Some("probe") => {
            // X1: проверка связи с площадкой — подпись, часы, чтение.
            // `--order` дополнительно ставит и отменяет заведомо
            // неисполнимую PostOnly-заявку: это единственный способ
            // проверить ПРАВО торговать, не совершив сделки. Без
            // флага команда только читает.
            //
            //   bot probe --keys ~/.bybit/live.env             //             --base https://api-testnet.bybit.com [--order]
            let mut keys_path = String::new();
            let mut base = String::from("https://api-testnet.bybit.com");
            let mut with_order = false;
            let mut it = args[2..].iter();
            while let Some(a) = it.next() {
                match a.as_str() {
                    "--keys" => keys_path = it.next().cloned().unwrap_or_default(),
                    "--base" => base = it.next().cloned().unwrap_or_default(),
                    "--order" => with_order = true,
                    _ => {}
                }
            }
            if keys_path.is_empty() {
                eprintln!("нужен --keys <файл>");
                exit(2);
            }
            let keys = match bot::venue::Keys::load(Path::new(&keys_path)) {
                Ok(k) => k,
                Err(e) => {
                    eprintln!("{e}");
                    exit(2);
                }
            };
            println!("ключ: {keys:?}");
            let mut v = bot::venue::Venue::new(&base, keys);
            match v.sync_clock() {
                Ok(skew) => println!("часы: сдвиг {skew} мс (наши против площадки)"),
                Err(e) => {
                    eprintln!("площадка недоступна: {e}");
                    exit(1);
                }
            }
            match v.wallet_usdt() {
                Ok((eq, bal)) => println!("кошелёк USDT: equity {eq:.2}, balance {bal:.2}"),
                Err(e) => {
                    eprintln!("кошелёк не читается: {e}");
                    exit(1);
                }
            }
            match v.positions() {
                Ok(p) => {
                    println!("открытых позиций: {}", p.len());
                    for (sym, side, size, px, upnl) in &p {
                        println!("  {sym} {side} {size} @ {px} (unreal {upnl:+.2})");
                    }
                }
                Err(e) => {
                    eprintln!("позиции не читаются: {e}");
                    exit(1);
                }
            }
            match v.open_orders() {
                Ok(o) => println!("открытых заявок: {}", o.len()),
                Err(e) => {
                    eprintln!("заявки не читаются: {e}");
                    exit(1);
                }
            }
            if with_order {
                // BTCUSDT: бид минус 20 % — PostOnly туда не
                // исполнится никогда; количество минимальное (0.001).
                let (bid, _ask) = match v.best_prices("BTCUSDT") {
                    Ok(x) => x,
                    Err(e) => {
                        eprintln!("цены не читаются: {e}");
                        exit(1);
                    }
                };
                let far = (bid * 0.8 / 100.0).round() * 100.0;
                let px = format!("{far:.1}");
                let link = format!("probe-{}", std::process::id());
                println!("ставлю PostOnly BTCUSDT Buy 0.001 @ {px} (бид {bid})");
                match v.place_limit("BTCUSDT", "Buy", "0.001", &px, "PostOnly", &link, false) {
                    Ok(id) => {
                        println!("заявка принята: {id}");
                        std::thread::sleep(std::time::Duration::from_secs(1));
                        match v.cancel("BTCUSDT", &id) {
                            Ok(()) => println!("заявка отменена — круг пройден"),
                            Err(e) => {
                                eprintln!("ОТМЕНА НЕ ПРОШЛА: {e}");
                                eprintln!("снимите заявку {id} руками");
                                exit(1);
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("заявка не принята: {e}");
                        exit(1);
                    }
                }
            }
            println!("probe: всё прошло");
        }
        Some("live") => {
            // bot live --s8 DIR --journal DIR --keys FILE --base URL
            //          [--arm gbm] [--capital 300] [--interval-sec 5]
            //          [--dry] [--once] [--clear-halt]
            //
            // Живой исполнитель X1–X3 (спека 12). Вся логика в
            // bot::live — двоичный файл тестами не покрывается, и
            // правка здесь однажды уже дала ложную тревогу панели.
            let mut s8 = None;
            let mut jr = None;
            let mut keys_path = None;
            let mut base: Option<String> = None;
            let mut arm = "gbm".to_string();
            // 300 $ — капитал ЗАМЕРА (спека 12 §2), не бумажные 3000.
            let mut capital = 300.0_f64;
            let mut interval = 5u64;
            let mut dry = false;
            let mut once = false;
            let mut clear_halt = false;
            let mut it = args[2..].iter();
            while let Some(a) = it.next() {
                let mut val = || it.next().cloned().unwrap_or_default();
                match a.as_str() {
                    "--s8" => s8 = Some(val()),
                    "--journal" => jr = Some(val()),
                    "--keys" => keys_path = Some(val()),
                    "--base" => base = Some(val()),
                    "--arm" => arm = val(),
                    "--capital" => capital = val().parse().unwrap_or(300.0),
                    "--interval-sec" => interval = val().parse().unwrap_or(5),
                    "--dry" => dry = true,
                    "--once" => once = true,
                    "--clear-halt" => clear_halt = true,
                    other => {
                        eprintln!("неизвестный ключ {other}");
                        exit(2);
                    }
                }
            }
            let (Some(s8), Some(jr), Some(kp)) = (s8, jr, keys_path) else {
                eprintln!("нужны --s8, --journal и --keys");
                exit(2);
            };
            // База обязательна СЛОВОМ: живой счёт не должен зависеть
            // от того, какое умолчание кто-то однажды поменял.
            let Some(base) = base else {
                eprintln!("нужна --base (https://api.bybit.com)");
                exit(2);
            };
            let keys = match bot::venue::Keys::load(Path::new(&kp)) {
                Ok(k) => k,
                Err(e) => {
                    eprintln!("ключ не читается: {e}");
                    exit(2);
                }
            };
            let mut v = bot::venue::Venue::new(&base, keys);
            match v.sync_clock() {
                Ok(skew) => eprintln!("часы: сдвиг {skew} мс"),
                Err(e) => {
                    eprintln!("часы не синхронизируются: {e}");
                    exit(1);
                }
            }
            let cfg = bot::live::LiveCfg {
                s8_dir: s8.into(),
                journal_dir: jr.into(),
                arm,
                capital_usd: capital,
                name_cap_share: 0.10,
                entry_cap_bp: 30.0,
                stop_cap_bp: 100.0,
                day_stop_usd: 15.0,
                total_stop_usd: 45.0,
                max_rejects: 3,
                stale_cycle_h: 3.0,
                stale_entry_sec: 120,
                dry,
            };
            eprintln!(
                "исполнитель: капитал {capital} $, нога {:.0} $, {} — {}",
                cfg.leg_usd(),
                if dry { "СУХОЙ прогон (заявки не отправляются)" } else { "ЖИВЫЕ заявки" },
                base
            );
            let ex = match bot::live::Executor::open(cfg, v, clear_halt) {
                Ok(x) => x,
                Err(e) => {
                    eprintln!("исполнитель не поднялся: {e}");
                    exit(2);
                }
            };
            if once {
                let mut ex = ex;
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|d| d.as_millis() as i64)
                    .unwrap_or(0);
                let rep = ex.tick(now);
                eprintln!(
                    "такт: входов {}, выходов {}, отказов {}, остановка: {}",
                    rep.opened,
                    rep.closed,
                    rep.rejected,
                    rep.halted.as_deref().unwrap_or("нет")
                );
                if rep.halted.is_some() {
                    exit(1);
                }
            } else {
                bot::live::run_loop(ex, interval);
            }
        }
        Some("shadow") => {
            // bot shadow --s8 DIR --journal DIR [--arm gbm]
            //            [--capital 1000] [--fees PATH] [--now-ms N]
            let mut s8 = None;
            let mut jr = None;
            let mut arm = "gbm".to_string();
            // Умолчание для РУЧНОГО запуска; живой контур передаёт
            // --capital из ядра расчёта (tools/run_bot.sh спрашивает
            // trades.START_BALANCE). 3000 — решение владельца
            // 2026-08-13; та же цифра во всех ветках разбора аргументов.
            let mut capital = 3000.0_f64;
            let mut fees_path = None;
            let mut now_ms: Option<i64> = None;
            let mut it = args[2..].iter();
            while let Some(a) = it.next() {
                let mut val = || it.next().cloned().unwrap_or_default();
                match a.as_str() {
                    "--s8" => s8 = Some(val()),
                    "--journal" => jr = Some(val()),
                    "--arm" => arm = val(),
                    "--capital" => capital = val().parse().unwrap_or(3000.0),
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
                eprintln!("ставки не прочитаны — весь счёт на умолчании 0.055 %");
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
