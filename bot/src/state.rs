//! Состояние счёта — чистая функция от журнала.
//!
//! Никакого накопления между вызовами: повторный прогон того же
//! журнала даёт то же состояние бит в бит, и провести сделку дважды
//! невозможно по построению. Тот же принцип, что у Python-счёта
//! (`trades.account`), и тот же урок `build.py` из A2 — состояние
//! читается из истории, а не утверждается.

use crate::events::{Event, Record, Side};
use serde::Serialize;
use std::collections::BTreeMap;

/// Открытая позиция. Всё, что нужно, чтобы закрыть её и посчитать
/// сверку с Python-счётом; ничего сверх.
#[derive(Serialize, Clone, PartialEq, Debug)]
pub struct Position {
    pub sym: String,
    pub side: Side,
    pub notional_usd: f64,
    pub entry_px: Option<f64>,
    pub fee_usd: f64,
    pub partial: bool,
    pub ver: Option<u32>,
    pub opened_at_ms: i64,
}

/// Счёт одного капитала: экспозиция не превышает его (плечо 1× держит
/// риск-слой E2; здесь — только честная арифметика кассы).
///
/// `BTreeMap`, а не `HashMap`: сериализация обязана быть
/// детерминированной, иначе «состояние совпало бит в бит» нельзя
/// проверить сравнением строк.
#[derive(Serialize, PartialEq, Debug)]
pub struct State {
    pub capital_usd: f64,
    /// Свободные деньги по КАССЕ: занятое возвращается при закрытии.
    pub cash_usd: f64,
    pub realized_pnl_usd: f64,
    pub positions: BTreeMap<String, Position>,
    pub kill: bool,
    pub decisions: u64,
    pub rejected: u64,
    pub closed: u64,
    pub last_seq: u64,
    pub last_at_ms: i64,
}

#[derive(Debug, PartialEq)]
pub enum StateError {
    /// Открытие поверх открытой позиции — противоречие журнала, а не
    /// ситуация: риск-слой не выпускает второй вход по тому же ключу.
    DoubleOpen { pos: String, seq: u64 },
    /// Закрытие несуществующей позиции. При write-ahead такое означает
    /// порчу журнала, и выводить состояние из него нельзя.
    CloseWithoutOpen { pos: String, seq: u64 },
}

impl std::fmt::Display for StateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StateError::DoubleOpen { pos, seq } => {
                write!(f, "событие {seq}: открытие поверх открытой {pos}")
            }
            StateError::CloseWithoutOpen { pos, seq } => {
                write!(f, "событие {seq}: закрытие несуществующей {pos}")
            }
        }
    }
}

/// Вывести состояние из записей. Записи обязаны идти в порядке журнала
/// (это гарантирует читатель `journal::read_all`).
pub fn derive(capital_usd: f64, records: &[Record]) -> Result<State, StateError> {
    let mut st = State {
        capital_usd,
        cash_usd: capital_usd,
        realized_pnl_usd: 0.0,
        positions: BTreeMap::new(),
        kill: false,
        decisions: 0,
        rejected: 0,
        closed: 0,
        last_seq: 0,
        last_at_ms: 0,
    };
    for r in records {
        st.last_seq = r.seq;
        st.last_at_ms = r.event.at_ms();
        match &r.event {
            Event::Decision { .. } => st.decisions += 1,
            Event::Reject { .. } => st.rejected += 1,
            Event::Open {
                pos,
                sym,
                side,
                notional_usd,
                qty: _,
                target_px: _,
                entry_px,
                fee_usd,
                partial,
                ver,
                at_ms,
            } => {
                if st.positions.contains_key(pos) {
                    return Err(StateError::DoubleOpen {
                        pos: pos.clone(),
                        seq: r.seq,
                    });
                }
                st.cash_usd -= notional_usd;
                st.positions.insert(
                    pos.clone(),
                    Position {
                        sym: sym.clone(),
                        side: *side,
                        notional_usd: *notional_usd,
                        entry_px: *entry_px,
                        fee_usd: *fee_usd,
                        partial: *partial,
                        ver: *ver,
                        opened_at_ms: *at_ms,
                    },
                );
            }
            Event::Close { pos, pnl_usd, .. } => {
                let p = st.positions.remove(pos).ok_or_else(|| {
                    StateError::CloseWithoutOpen { pos: pos.clone(), seq: r.seq }
                })?;
                // Касса: занятое возвращается, нетто-результат сверху.
                // `pnl_usd` уже за вычетом издержек — считает его
                // исполнение, а не состояние, чтобы формула жила в
                // одном месте.
                st.cash_usd += p.notional_usd + pnl_usd;
                st.realized_pnl_usd += pnl_usd;
                st.closed += 1;
            }
            Event::Kill { on, .. } => st.kill = *on,
        }
    }
    Ok(st)
}
