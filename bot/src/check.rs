//! Сторож исполнения: инварианты, которые обязаны держаться всегда.
//!
//! Смысл — превратить «кажется, работает» в список утверждений с
//! числами. Каждое нарушение называет сделку и величину; молчаливый
//! сторож неотличим от отсутствующего, поэтому и чистый вердикт несёт
//! числа: сколько событий проверено, сколько позиций открыто.
//!
//! Нарушение (violation) — счёт вести нельзя, надо чинить.
//! Предупреждение (warning) — работать можно, но смотреть надо:
//! застрявшая позиция и тишина решений бывают и у исправного бота
//! (разбор запаздывает, цикл модели упал) — это ожидание, но ожидание
//! обязано быть видимым.

use crate::events::{Event, Record};
use crate::state::State;
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;

/// Сколько часов позиция живёт ЗАКОННО — по книге, которую ведёт этот
/// журнал. Путь к книге лежит в маркере источника (`source.txt`,
/// пишет `run_bot.sh`), режим и срок — в её манифесте.
///
/// Маркер несёт два поля: путь и версию правила кассы (`… cash=N`), и
/// разбирать его надо ПЕРВЫМ полем — целиком он однажды уже сломал
/// показ, когда версию добавили. Нет маркера или нет манифеста —
/// остаётся умолчание, то есть прежнее поведение.
/// Проверка журнала со сроком, взятым у ЕГО книги. Связка живёт
/// здесь, а не в `main`: правку в двоичном файле не проверить тестом,
/// и отрицательный контроль на неё не кусается — проверено.
pub fn verify_journal(
    journal_dir: &Path,
    capital: f64,
    records: &[Record],
    st: &State,
    now_ms: i64,
) -> CheckReport {
    verify(
        capital,
        records,
        st,
        &CheckOpts {
            now_ms,
            hold_h: hold_from_journal(journal_dir),
            ..Default::default()
        },
    )
}

pub fn hold_from_journal(journal_dir: &Path) -> i64 {
    let def = CheckOpts::default().hold_h;
    let Ok(text) = std::fs::read_to_string(journal_dir.join("source.txt"))
    else {
        return def;
    };
    let Some(first) = text.split_whitespace().next() else {
        return def;
    };
    crate::engine::book_mode(Path::new(first)).hold_h.unwrap_or(def)
}

pub struct CheckOpts {
    pub hold_h: i64,
    /// Сколько часов сверх срока терпим, прежде чем звать позицию
    /// застрявшей, и сколько часов тишины решений считаем нормальными
    /// (цикл модели часовой; двойной пропуск — уже событие).
    pub stale_h: i64,
    pub now_ms: i64,
}

impl Default for CheckOpts {
    fn default() -> Self {
        CheckOpts { hold_h: 4, stale_h: 3, now_ms: 0 }
    }
}

#[derive(Serialize, Debug)]
pub struct CheckReport {
    pub ok: bool,
    pub violations: Vec<String>,
    pub warnings: Vec<String>,
    pub events: usize,
    pub open_positions: usize,
}

/// Проверить состояние против журнала. `st` обязан быть выведен из
/// этих же `records` — сторож пересчитывает кассу НЕЗАВИСИМЫМ проходом
/// и ловит расхождение вывода состояния с историей.
pub fn verify(
    capital: f64,
    records: &[Record],
    st: &State,
    o: &CheckOpts,
) -> CheckReport {
    let mut v: Vec<String> = Vec::new();
    let mut w: Vec<String> = Vec::new();

    // Независимый пересчёт кассы: суммы прямо по событиям, без логики
    // `derive`. Совпадение — проверка самого вывода состояния.
    let mut realized = 0.0_f64;
    let mut open: BTreeMap<&str, (f64, i64, &str)> = BTreeMap::new();
    let mut last_decision: Option<i64> = None;
    for r in records {
        match &r.event {
            Event::Decision { at_ms, .. } => last_decision = Some(*at_ms),
            Event::Open { pos, notional_usd, at_ms, sym, .. } => {
                open.insert(pos, (*notional_usd, *at_ms, sym));
            }
            Event::Close { pos, pnl_usd, .. } => {
                if let Some((size, _, _)) = open.remove(pos.as_str()) {
                    realized += pnl_usd;
                    // Лонг не может потерять больше позиции; у шорта
                    // убыток сверху не ограничен (урок арифметики
                    // хвоста F1–F3) — потому предупреждение, а не
                    // нарушение, и оно зовёт смотреть сделку.
                    if *pnl_usd < -size {
                        w.push(format!(
                            "{pos}: убыток {pnl_usd:.2} больше размера \
                             {size:.2} — проверить сделку"
                        ));
                    }
                }
            }
            Event::Adjust { pnl_usd, .. } => {
                // Деньги, доехавшие после закрытия («вне исполнителя»,
                // биржевой closed-pnl): пересчёт обязан считать их тем
                // же движением, что `derive`, иначе касса «разойдётся»
                // на собственной поправке.
                realized += pnl_usd;
            }
            _ => {}
        }
    }
    let busy: f64 = open.values().map(|(n, _, _)| n).sum();
    let cash2 = capital + realized - busy;

    if (st.cash_usd - cash2).abs() > 1e-6 {
        v.push(format!(
            "касса разошлась с историей: состояние {:.6}, пересчёт {cash2:.6}",
            st.cash_usd
        ));
    }
    if (st.realized_pnl_usd - realized).abs() > 1e-6 {
        v.push(format!(
            "реализованное разошлось: состояние {:.6}, пересчёт {realized:.6}",
            st.realized_pnl_usd
        ));
    }
    if st.positions.len() != open.len() {
        v.push(format!(
            "открытых позиций {} в состоянии против {} по событиям",
            st.positions.len(),
            open.len()
        ));
    }

    // Плечо 1×: занятое не превышает капитала с учётом результата.
    let cap_now = capital + realized;
    if busy > cap_now + 1e-6 {
        v.push(format!(
            "плечо выше 1×: занято {busy:.2} при капитале {cap_now:.2}"
        ));
    }

    // Застрявшие позиции: срок вышел, разбора всё нет.
    let deadline = (o.hold_h + o.stale_h) * 3_600_000;
    for (pos, (_, opened, _)) in &open {
        if o.now_ms - opened > deadline {
            let h = (o.now_ms - opened) as f64 / 3_600_000.0;
            w.push(format!(
                "застряла {pos}: открыта {h:.1} ч при сроке {} ч — \
                 разбор запаздывает",
                o.hold_h
            ));
        }
    }

    // Тишина решений: умерший цикл модели выглядит как спокойный
    // рынок, и различает их только возраст последнего решения.
    match last_decision {
        Some(t) if o.now_ms - t > o.stale_h * 3_600_000 => {
            w.push(format!(
                "решений нет {:.1} ч — цикл модели молчит",
                (o.now_ms - t) as f64 / 3_600_000.0
            ));
        }
        None if !records.is_empty() => {
            w.push("в журнале нет ни одного решения".into());
        }
        _ => {}
    }

    CheckReport {
        ok: v.is_empty(),
        violations: v,
        warnings: w,
        events: records.len(),
        open_positions: open.len(),
    }
}
