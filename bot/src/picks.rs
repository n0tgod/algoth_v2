//! Чтение решений модели и разборов — входных документов ядра.
//!
//! `picks.jsonl` — кого выбрал часовой цикл, `review.jsonl` — чем
//! кончилось и какой была книга на выходе. Ядро читает их как ЗАКАЗ и
//! ВЫПИСКУ: цена и книга в них — входные данные (иначе сверка с
//! Python-счётом сравнивала бы разные снимки, а не разные формулы),
//! всё остальное — размер, исполнение, деньги — ядро считает само.
//!
//! Оборванная последняя строка (цикл пишет в тот же файл прямо сейчас)
//! пропускается молча ЗДЕСЬ и будет дочитана следующим проходом; порча
//! в середине — ошибка, файл дописывается только в хвост.

use crate::events::Side;
use crate::paper::Book;
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

/// Одна нога выбора: имя, цена закрытия часа сигнала, книга в момент
/// решения. Ожидания (`fwd`/`mae`/`mfe`) ядру не нужны — оно исполняет,
/// а не судит; они остаются в файле для страницы и замеров.
#[derive(Deserialize, Clone, Debug)]
pub struct Leg {
    pub sym: String,
    pub px: Option<f64>,
    #[serde(default)]
    pub cum: Option<Book>,
    /// Секунда живого входа сканера: сделка ситуационной книги
    /// открывается моментом события, а не закрытием часа.
    #[serde(default)]
    pub at_ts: Option<f64>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Pick {
    pub arm: Option<String>,
    pub hour: String,
    /// Момент решения цикла: денежное событие входа стоит на нём, а
    /// не на номинальной границе часа — симметрично разбору.
    #[serde(default)]
    pub at_ts: Option<f64>,
    #[serde(default)]
    pub ver: Option<u32>,
    #[serde(default)]
    pub long: Vec<Leg>,
    #[serde(default)]
    pub short: Vec<Leg>,
}

/// Исход ноги из разбора: книга на выходе и нетто по прежней основе —
/// запасной путь для сделок, у которых книги не записаны.
#[derive(Deserialize, Clone, Debug)]
pub struct ReviewRow {
    pub sym: String,
    pub side: String,
    #[serde(default)]
    pub net: Option<f64>,
    #[serde(default)]
    pub cum: Option<Book>,
    /// Час выхода ситуационной книги: срок закрытия задаёт разбор,
    /// а не горизонт.
    #[serde(default)]
    pub exit_hour: Option<String>,
    /// Причина выхода — едет в журнал закрытия дословно.
    #[serde(default)]
    pub reason: Option<String>,
    /// Секунда живого выхода: сторож записал факт событием тогда, а
    /// цикл лишь переписал его позже. Деньги возвращаются в неё.
    #[serde(default)]
    pub exit_ts: Option<f64>,
    /// Момент записи разбора (штампуется из записи при чтении):
    /// касса не вправе узнать исход раньше него.
    #[serde(skip)]
    pub rec_at_ts: Option<f64>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Review {
    pub arm: Option<String>,
    pub hour: String,
    #[serde(default)]
    pub at_ts: Option<f64>,
    #[serde(default)]
    pub rows: Vec<ReviewRow>,
}

fn read_lines<T: for<'de> Deserialize<'de>>(path: &Path) -> Vec<T> {
    let Ok(text) = std::fs::read_to_string(path) else {
        return Vec::new();
    };
    let lines: Vec<&str> = text.split('\n').collect();
    let mut out = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        match serde_json::from_str::<T>(line) {
            Ok(v) => out.push(v),
            Err(e) => {
                let is_tail = lines[i + 1..].iter().all(|l| l.trim().is_empty());
                if is_tail {
                    // Пишущая сторона ещё не довела строку — дочитаем
                    // следующим проходом.
                    continue;
                }
                // Середина не бывает оборвана у append-only файла:
                // остановиться честнее, чем перешагнуть сделку.
                panic!(
                    "{}: строка {} не разбирается не в хвосте: {e}",
                    path.display(),
                    i + 1
                );
            }
        }
    }
    out
}

/// Выборы руки. Дубли снимаются НА СТРОКЕ, как у Python-сборки:
/// перезапуск пишет тот же час целиком — его строки совпадут и
/// уйдут; живой вход сканера дописывает к часу ВТОРУЮ запись с
/// новыми именами — они остаются.
pub fn load_picks(dir: &Path, arm: &str) -> Vec<Pick> {
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut out = Vec::new();
    for mut p in read_lines::<Pick>(&dir.join("picks.jsonl")) {
        let a = p.arm.clone().unwrap_or_else(|| "gbm".into());
        if a != arm {
            continue;
        }
        let hour = p.hour.clone();
        p.long.retain(|l| {
            seen.insert(format!("{hour}:{}:long", l.sym))
        });
        p.short.retain(|l| {
            seen.insert(format!("{hour}:{}:short", l.sym))
        });
        if p.long.is_empty() && p.short.is_empty() {
            continue;
        }
        out.push(p);
    }
    out
}

/// Разборы руки: `(час, имя, сторона) → строка`.
pub fn load_reviews(
    dir: &Path,
    arm: &str,
) -> BTreeMap<(String, String, Side), ReviewRow> {
    let mut out = BTreeMap::new();
    for rv in read_lines::<Review>(&dir.join("review.jsonl")) {
        let a = rv.arm.clone().unwrap_or_else(|| "gbm".into());
        if a != arm {
            continue;
        }
        for mut row in rv.rows {
            let side = match row.side.as_str() {
                "long" => Side::Long,
                "short" => Side::Short,
                _ => continue,
            };
            row.rec_at_ts = rv.at_ts;
            out.entry((rv.hour.clone(), row.sym.clone(), side))
                .or_insert(row);
        }
    }
    out
}

/// `2026-08-05-11` → миллисекунды НАЧАЛА часа UTC. Обратная пара к
/// `journal::utc_day`; проверена теми же закреплёнными датами.
pub fn hour_ms(hour: &str) -> Option<i64> {
    let p: Vec<&str> = hour.split('-').collect();
    if p.len() != 4 {
        return None;
    }
    let (y, m, d, h): (i64, i64, i64, i64) = (
        p[0].parse().ok()?,
        p[1].parse().ok()?,
        p[2].parse().ok()?,
        p[3].parse().ok()?,
    );
    // days_from_civil (Howard Hinnant) — зеркало civil_from_days.
    let y2 = if m <= 2 { y - 1 } else { y };
    let era = y2.div_euclid(400);
    let yoe = y2 - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some((days * 24 + h) * 3_600_000)
}

#[cfg(test)]
mod tests {
    use super::hour_ms;
    use crate::journal::utc_day;

    #[test]
    fn час_и_календарь_обратны_друг_другу() {
        assert_eq!(hour_ms("2026-08-05-11"), Some(1_785_927_600_000));
        assert_eq!(utc_day(hour_ms("2026-08-05-11").unwrap()), "2026-08-05");
        assert_eq!(hour_ms("1970-01-01-00"), Some(0));
        assert_eq!(hour_ms("2000-02-29-23"), Some(951_865_200_000));
        assert_eq!(hour_ms("кривой час"), None);
    }
}
