//! Бумажное исполнение: лесенка, комиссия, деньги сделки.
//!
//! Каждая формула — зеркало Python-счёта (`s8_loop/trades.py`), и это
//! не копия ради копии: сверка E2 сравнивает две НЕЗАВИСИМЫЕ записи
//! одних формул на одних данных, и расхождение означает ошибку одной
//! из сторон. Порядок операций сохранён дословно — сумма в другом
//! порядке даёт другой последний бит, и сверка «до цента» утонула бы
//! в ложных срабатываниях.

use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::Path;

/// Модальный тариф A1 — умолчание там, где ставки нет вовсе.
pub const DEFAULT_TAKER_BP: f64 = 5.5;

/// Округление как в Python: `round(x, n)` округляет ДЕСЯТИЧНУЮ запись
/// double к ближайшей, при равенстве — к чётной. Rust-форматирование
/// делает то же самое, поэтому канонический путь — через строку.
/// Деньги и б.п. проходят через это при каждом сравнении с Python;
/// «своё» округление половин от нуля дало бы редкие расхождения в цент,
/// неотличимые от настоящих ошибок формул.
pub fn py_round(x: f64, digits: usize) -> f64 {
    format!("{x:.digits$}").parse().expect("число из числа")
}

/// Таблица тейкерских ставок из выгрузки A1 (`fees.json`).
pub struct FeeTable(BTreeMap<String, f64>);

impl FeeTable {
    /// Формат выгрузки — список записей площадки, ставка долями единицы
    /// в строке. Ключи ищутся по имени поля (урок загрузчика funding).
    pub fn load(path: &Path) -> FeeTable {
        #[derive(Deserialize)]
        struct Row {
            symbol: Option<String>,
            #[serde(rename = "takerFeeRate")]
            taker: Option<String>,
        }
        let mut out = BTreeMap::new();
        if let Ok(text) = std::fs::read_to_string(path) {
            if let Ok(rows) = serde_json::from_str::<Vec<Row>>(&text) {
                for r in rows {
                    if let (Some(s), Some(t)) = (r.symbol, r.taker) {
                        if let Ok(v) = t.parse::<f64>() {
                            out.insert(s, py_round(v * 1e4, 4));
                        }
                    }
                }
            }
        }
        FeeTable(out)
    }

    pub fn empty() -> FeeTable {
        FeeTable(BTreeMap::new())
    }

    /// `(ставка б.п., известна ли)`. Второе — мера покрытия, не
    /// украшение: молчаливое умолчание неотличимо от измерения.
    pub fn taker_bp(&self, sym: &str) -> (f64, bool) {
        match self.0.get(sym) {
            Some(v) => (*v, true),
            None => (DEFAULT_TAKER_BP, false),
        }
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

/// Книга в момент исполнения: середина и накопленные лесенки
/// (`[[цена, накопленный нотионал], …]`) — ровно то, что штампует в
/// запись Python (`stamp_book`).
#[derive(Deserialize, Clone, PartialEq, Debug)]
pub struct Book {
    pub mid: f64,
    pub b: Vec<[f64; 2]>,
    pub a: Vec<[f64; 2]>,
    #[serde(default)]
    pub t: Option<f64>,
}

/// Средняя цена рыночной заявки на `notional` долларов по лесенке.
/// Возвращает `(цена, влезло ли целиком)` — частичное исполнение
/// помечается честно, а не досчитывается по последнему уровню.
/// Дословное зеркало `trades.walk`.
pub fn walk(cum: &[[f64; 2]], notional: f64) -> Option<(f64, bool)> {
    if cum.is_empty() || notional <= 0.0 {
        return None;
    }
    let (mut prev, mut qty, mut left) = (0.0_f64, 0.0_f64, notional);
    for lvl in cum {
        let (p, c) = (lvl[0], lvl[1]);
        let take = left.min(c - prev);
        if take <= 0.0 {
            prev = c;
            continue;
        }
        qty += take / p;
        left -= take;
        prev = c;
        if left <= 1e-9 {
            break;
        }
    }
    if qty <= 0.0 {
        return None;
    }
    Some(((notional - left) / qty, left <= 1e-9))
}

/// Итог исполнения одной сделки по двум книгам.
#[derive(Debug, PartialEq)]
pub struct Exec {
    pub fill_in: f64,
    pub fill_out: f64,
    /// Круг комиссии, б.п. (обе ноги), округлён как у Python.
    pub fee_bp: f64,
    pub fee_known: bool,
    /// Нетто-ход в б.п. с вычетом комиссии, округлён до одной десятой.
    pub net_bp: f64,
    pub filled: bool,
}

/// Исполнение по записанным книгам входа и выхода. Зеркало
/// `trades.exec_cost` в части, которая делает деньги: движение цены —
/// по ФАКТИЧЕСКИМ ценам исполнения с лесенок, обе ноги по СВОЕЙ
/// стороне книги (лонг входит в аск и выходит в бид).
/// `None` — когда какой-то книги нет: неизвестная издержка не ноль.
pub fn exec_cost(
    long: bool,
    cin: &Book,
    cout: &Book,
    size: f64,
    fees: &FeeTable,
    sym: &str,
) -> Option<Exec> {
    if size <= 0.0 {
        return None;
    }
    let (px_in, ok_in) = walk(if long { &cin.a } else { &cin.b }, size)?;
    let (px_out, ok_out) = walk(if long { &cout.b } else { &cout.a }, size)?;
    if px_in <= 0.0 || px_out <= 0.0 || cin.mid <= 0.0 || cout.mid <= 0.0 {
        return None;
    }
    let (fee, known) = fees.taker_bp(sym);
    let mv = (px_out / px_in - 1.0) * if long { 1e4 } else { -1e4 };
    Some(Exec {
        fill_in: px_in,
        fill_out: px_out,
        fee_bp: py_round(fee * 2.0, 2),
        fee_known: known,
        net_bp: py_round(mv - fee * 2.0, 1),
        filled: ok_in && ok_out,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn округление_как_у_питона() {
        // Значения закреплены числом; половины уходят к чётной цифре
        // ДЕСЯТИЧНОЙ записи — как делает Python round().
        assert_eq!(py_round(0.125, 2), 0.12);
        assert_eq!(py_round(0.135, 2), 0.14); // 0.135 в double чуть больше
        assert_eq!(py_round(2.675, 2), 2.67); // а 2.675 — чуть меньше
        assert_eq!(py_round(-0.125, 2), -0.12);
        assert_eq!(py_round(41.664999999, 2), 41.66);
    }

    #[test]
    fn лесенка_частичное_исполнение_честное() {
        let cum = vec![[100.0, 50.0], [101.0, 90.0]];
        let (px, full) = walk(&cum, 40.0).unwrap();
        assert_eq!(px, 100.0);
        assert!(full);
        // Просим больше, чем показано: цена по виденному, флаг честный.
        let (px, full) = walk(&cum, 120.0).unwrap();
        assert!(!full);
        let qty = 50.0 / 100.0 + 40.0 / 101.0;
        assert!((px - 90.0 / qty).abs() < 1e-12);
        assert!(walk(&[], 10.0).is_none());
        assert!(walk(&cum, 0.0).is_none());
    }
}
