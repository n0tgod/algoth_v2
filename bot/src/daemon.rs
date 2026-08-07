//! Демон: проход тени по кругу, сторож после каждого прохода, статус
//! файлом.
//!
//! Один такт (`tick`) — вся содержательная работа, и он принимает
//! «сейчас» параметром: такт обязан быть разыгрываемым тестом без
//! подмены системных часов. Цикл (`run`) лишь зовёт такт и спит.
//!
//! Статус пишется атомарно (tmp → rename) каждый такт, даже когда
//! делать было нечего: его свежесть — то, чем cron-сторож отличает
//! живой процесс от повисшего (тот же приём, что у сборщика; процесс,
//! бодрый снаружи и мёртвый внутри, уже стоил суток записи).
//!
//! Ошибка такта НЕ роняет демон: она пишется в статус и в лог, и
//! страница показывает её словами. Умерший молча процесс неотличим от
//! спокойного рынка — а живой с красной строкой виден сразу.

use crate::check::{verify, CheckOpts, CheckReport};
use crate::engine::{shadow, Cfg, PassReport};
use crate::journal::read_all;
use crate::paper::{py_round, FeeTable};
use crate::state::derive;
use serde::Serialize;
use std::path::PathBuf;
use std::process::Command;

pub struct SverkaCfg {
    /// Интерпретатор: у sverka.py только стандартная библиотека,
    /// системного python3 достаточно.
    pub python: String,
    pub script: PathBuf,
}

pub struct DaemonCfg {
    pub s8_dir: PathBuf,
    pub journal_dir: PathBuf,
    pub arm: String,
    pub capital_usd: f64,
    /// Путь, а не загруженная таблица: ставки перечитываются каждый
    /// такт — файл обновляется выгрузкой A1, и копия в памяти сутками
    /// молча считала бы по вчерашним ставкам.
    pub fees_path: PathBuf,
    pub interval_sec: u64,
    pub sverka: Option<SverkaCfg>,
}

#[derive(Serialize)]
pub struct SverkaStatus {
    /// `None` — не запускалась либо недоступна (см. `note`).
    pub ok: Option<bool>,
    pub at_ms: Option<i64>,
    pub note: String,
}

#[derive(Serialize)]
pub struct PassSummary {
    pub appended: usize,
    pub opened: usize,
    pub closed: usize,
    pub rejected: usize,
    pub waiting_review: usize,
}

impl From<&PassReport> for PassSummary {
    fn from(r: &PassReport) -> Self {
        PassSummary {
            appended: r.appended,
            opened: r.opened,
            closed: r.closed,
            rejected: r.rejected,
            waiting_review: r.waiting_review,
        }
    }
}

#[derive(Serialize)]
pub struct Status {
    pub at_ms: i64,
    pub arm: String,
    /// Стартовый капитал — знаменатель для доли и начало кривой счёта.
    /// Страница не вправе его выдумывать: у неё нет конфигурации ядра.
    pub capital_usd: f64,
    pub balance_usd: f64,
    pub cash_usd: f64,
    pub busy_usd: f64,
    pub open: usize,
    pub kill: bool,
    pub pass_report: Option<PassSummary>,
    pub check: Option<CheckReport>,
    pub sverka: SverkaStatus,
    /// Ошибка такта словами; `None` — ошибки не было.
    pub error: Option<String>,
}

/// Память демона между тактами — только про сверку: когда бежала и чем
/// кончилась. Всё остальное каждый такт выводится из файлов заново.
#[derive(Default)]
pub struct TickMemory {
    pub sverka_at_ms: Option<i64>,
    pub sverka_ok: Option<bool>,
    pub sverka_note: Option<String>,
}

/// Один такт: тень → сторож → сверка (по расписанию) → статус на диск.
pub fn tick(cfg: &DaemonCfg, mem: &mut TickMemory, now_ms: i64) -> Status {
    let mut status = Status {
        at_ms: now_ms,
        arm: cfg.arm.clone(),
        capital_usd: cfg.capital_usd,
        balance_usd: 0.0,
        cash_usd: 0.0,
        busy_usd: 0.0,
        open: 0,
        kill: false,
        pass_report: None,
        check: None,
        sverka: SverkaStatus {
            ok: mem.sverka_ok,
            at_ms: mem.sverka_at_ms,
            note: mem.sverka_note.clone().unwrap_or_default(),
        },
        error: None,
    };
    // Правила книги сменились (цикл отставил её в архив) — журнал
    // переначинается ДО прохода: тень старой книги в новых файлах
    // выглядела бы расхождениями, которых никто не совершал.
    match crate::engine::fresh_journal_on_rules_change(
        &cfg.s8_dir,
        &cfg.journal_dir,
    ) {
        Ok(Some(dst)) => {
            eprintln!(
                "правила книги сменились — журнал отставлен в {}",
                dst.display()
            );
            // Прежний вердикт сверки описывает журнал, которого
            // больше нет. Держать его на панели — показывать красное
            // о несуществующем состоянии: владелец увидел ровно это
            // после перехода книги на v4, при пустых журнале и книге.
            // Сброс делает сверку «пора» в этом же такте.
            mem.sverka_at_ms = None;
            mem.sverka_ok = None;
            mem.sverka_note = None;
        }
        Ok(None) => {}
        Err(e) => {
            status.error = Some(format!("смена правил книги: {e}"));
            write_status(&cfg.journal_dir, &status);
            return status;
        }
    }
    let ecfg = Cfg {
        s8_dir: cfg.s8_dir.clone(),
        journal_dir: cfg.journal_dir.clone(),
        arm: cfg.arm.clone(),
        capital_usd: cfg.capital_usd,
        fees: FeeTable::load(&cfg.fees_path),
        now_ms,
    };
    let pass = match shadow(&ecfg) {
        Ok((rep, st)) => {
            status.busy_usd =
                st.positions.values().map(|p| p.notional_usd).sum();
            status.cash_usd = st.cash_usd;
            status.balance_usd = py_round(st.cash_usd + status.busy_usd, 2);
            status.open = st.positions.len();
            status.kill = st.kill;
            status.pass_report = Some(PassSummary::from(&rep));
            Some(rep)
        }
        Err(e) => {
            status.error = Some(format!("проход тени: {e}"));
            None
        }
    };

    // Сторож инвариантов — на каждом такте, по свежему журналу.
    match read_all(&cfg.journal_dir) {
        Ok((records, _)) => match derive(cfg.capital_usd, &records) {
            Ok(st) => {
                status.check = Some(verify(
                    cfg.capital_usd,
                    &records,
                    &st,
                    &CheckOpts { now_ms, ..Default::default() },
                ));
            }
            Err(e) => {
                status.error = Some(format!("состояние не выводится: {e}"));
            }
        },
        Err(e) => {
            status.error = Some(format!("журнал не читается: {e}"));
        }
    }

    // Сверка — раз в час либо сразу после новых закрытий: чаще
    // сравнивать нечего, входные файлы меняются часовым циклом.
    let due = match mem.sverka_at_ms {
        None => true,
        Some(t) => {
            now_ms - t >= 3_600_000
                || pass.as_ref().map(|p| p.closed > 0).unwrap_or(false)
        }
    };
    if let Some(sv) = &cfg.sverka {
        if due {
            status.sverka = run_sverka(cfg, sv, now_ms, mem);
        }
    } else {
        status.sverka.note = "сверка не настроена".into();
    }

    write_status(&cfg.journal_dir, &status);
    status
}

fn run_sverka(
    cfg: &DaemonCfg,
    sv: &SverkaCfg,
    now_ms: i64,
    mem: &mut TickMemory,
) -> SverkaStatus {
    let out = Command::new(&sv.python)
        .arg(&sv.script)
        .arg("--s8")
        .arg(&cfg.s8_dir)
        .arg("--journal")
        .arg(&cfg.journal_dir)
        .args(["--arm", &cfg.arm])
        .args(["--capital", &format!("{}", cfg.capital_usd)])
        .arg("--fees")
        .arg(&cfg.fees_path)
        .args(["--now", &format!("{}", now_ms / 1000)])
        .output();
    let st = match out {
        Ok(o) => {
            let note = if o.status.success() {
                "расхождений нет".to_string()
            } else {
                // Строки расхождений — в статус: страница обязана
                // показать, ЧТО разошлось, а не только флаг.
                let text = String::from_utf8_lossy(&o.stdout);
                let tail: Vec<&str> = text
                    .lines()
                    .filter(|l| l.starts_with("- "))
                    .take(5)
                    .collect();
                format!("РАСХОЖДЕНИЯ: {}", tail.join("; "))
            };
            mem.sverka_ok = Some(o.status.success());
            mem.sverka_at_ms = Some(now_ms);
            mem.sverka_note = Some(note.clone());
            SverkaStatus {
                ok: mem.sverka_ok,
                at_ms: mem.sverka_at_ms,
                note,
            }
        }
        // Недоступная сверка — не тишина: причина словами. Прошлый
        // вердикт при этом не выдаётся за свежий.
        Err(e) => SverkaStatus {
            ok: None,
            at_ms: mem.sverka_at_ms,
            note: format!("сверка недоступна: {e}"),
        },
    };
    st
}

/// Статус — атомарно: обрыв записи не оставляет странице огрызка,
/// который разобрался бы как «бот молчит» при живом боте.
fn write_status(dir: &std::path::Path, st: &Status) {
    let tmp = dir.join("status.json.tmp");
    let dst = dir.join("status.json");
    if let Ok(body) = serde_json::to_vec_pretty(st) {
        if std::fs::write(&tmp, body).is_ok() {
            let _ = std::fs::rename(&tmp, &dst);
        }
    }
}

/// Вечный цикл: такт, лог-строка, сон. Убивается сигналом; журнал
/// write-ahead, поэтому обрыв в любом месте стоит не больше одной
/// недописанной строки, которую подъём отбросит со счётом.
pub fn run(cfg: &DaemonCfg) -> ! {
    let mut mem = TickMemory::default();
    loop {
        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0);
        let st = tick(cfg, &mut mem, now_ms);
        println!(
            "[{} {:02}:{:02}Z] баланс {} $, открыто {}, инварианты {}, сверка {}{}",
            crate::journal::utc_day(now_ms),
            now_ms / 1000 % 86_400 / 3_600,
            now_ms / 1000 % 3_600 / 60,
            st.balance_usd,
            st.open,
            st.check
                .as_ref()
                .map(|c| if c.ok { "целы" } else { "НАРУШЕНЫ" })
                .unwrap_or("—"),
            match st.sverka.ok {
                Some(true) => "чиста",
                Some(false) => "РАСХОЖДЕНИЯ",
                None => "—",
            },
            st.error
                .as_ref()
                .map(|e| format!("; ОШИБКА: {e}"))
                .unwrap_or_default()
        );
        std::thread::sleep(std::time::Duration::from_secs(cfg.interval_sec));
    }
}
