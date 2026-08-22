//! Движок тени: те же сделки, что у Python-счёта, своим счётом.
//!
//! Каждый проход (`shadow`) читает выборы и разборы модели, сравнивает
//! с журналом и дописывает НЕДОСТАЮЩИЕ события: решения, входы, выходы,
//! отказы. Проход идемпотентен — второй запуск на тех же файлах не
//! дописывает ничего: что считать сделанным, решает журнал, а не
//! память процесса (урок `build.py`).
//!
//! Порядок событий — как у Python-`account`: по времени, при равенстве
//! момента закрытие раньше открытия (деньги возвращаются в кассу до
//! того, как их снова размещают; обратный порядок там уже давал
//! `size = 0` у всей руки).

use crate::events::{Event, Side};
use crate::journal::{Journal, JournalError};
use crate::paper::{exec_cost, py_round, walk, FeeTable};
use crate::picks::{hour_ms, load_picks, load_reviews, Leg};
use crate::state::{derive, State, StateError};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

pub const HOLD_H: i64 = 4;

/// Режим книги — из её же манифеста: каталог сам говорит, как живут
/// его позиции. Флаг в командной строке однажды разошёлся бы с тем,
/// что лежит на диске, — а манифест едет вместе с книгой.
#[derive(Debug, Clone, Copy, Default)]
pub struct BookMode {
    /// Ситуационная книга: без срока, закрытие задаёт разбор.
    pub sit: bool,
    /// Фиксированные слоты кассы (у ситуационной книги их 6).
    pub slots: Option<f64>,
    /// Сколько часов позиция живёт ЗАКОННО: горизонт у книги со
    /// сроком, предел возраста у ситуационной. Проверка «застряла»
    /// считала это число зашитой четвёркой и кричала на позиции
    /// книги без срока, прожившие законные 15 часов, — тревога,
    /// которая кричит ложно, перестаёт быть сигналом.
    pub hold_h: Option<i64>,
}

/// Версия правил книги из её манифеста; `None`, если книга правил не
/// объявляет (книги горизонтов) или манифеста нет.
pub fn book_rules_version(s8_dir: &Path) -> Option<i64> {
    #[derive(serde::Deserialize)]
    struct Man {
        #[serde(default)]
        rules_version: Option<i64>,
    }
    let text = std::fs::read_to_string(s8_dir.join("manifest.json")).ok()?;
    serde_json::from_str::<Man>(&text).ok()?.rules_version
}

/// Журнал — запись ОДНОЙ книги. Сменились правила книги (цикл отставил
/// её в архив и начал заново) — журнал обязан переначаться тоже:
/// прежних сделок в новых файлах не существует, и сверка кричала бы о
/// расхождениях, которых никто не совершал. Прежний журнал
/// отставляется рядом, не удаляется; файл KILL переносится в свежий
/// каталог — аварийный выключатель не снимается сменой книги.
///
/// Журнал без маркера версии при объявленных правилах тоже
/// отставляется: журнал, не умеющий доказать свою версию, не
/// принадлежит ни одной из известных.
pub fn fresh_journal_on_rules_change(
    s8_dir: &Path,
    journal_dir: &Path,
) -> std::io::Result<Option<PathBuf>> {
    let Some(ver) = book_rules_version(s8_dir) else {
        return Ok(None);
    };
    let marker = journal_dir.join("rules_version.txt");
    let was: Option<i64> = std::fs::read_to_string(&marker)
        .ok()
        .and_then(|t| t.trim().parse().ok());
    if was == Some(ver) {
        return Ok(None);
    }
    let has_journal = std::fs::read_dir(journal_dir)
        .map(|it| {
            it.flatten().any(|e| {
                e.file_name().to_string_lossy().starts_with("journal-")
            })
        })
        .unwrap_or(false);
    if !has_journal {
        std::fs::create_dir_all(journal_dir)?;
        std::fs::write(&marker, format!("{ver}
"))?;
        return Ok(None);
    }
    let tag = was.map(|v| v.to_string()).unwrap_or_else(|| "0".into());
    let mut dst = journal_dir.with_file_name(format!(
        "{}.rules-v{tag}",
        journal_dir.file_name().unwrap_or_default().to_string_lossy()
    ));
    let mut n = 0;
    while dst.exists() {
        n += 1;
        dst = journal_dir.with_file_name(format!(
            "{}.rules-v{tag}-{n}",
            journal_dir.file_name().unwrap_or_default().to_string_lossy()
        ));
    }
    std::fs::rename(journal_dir, &dst)?;
    std::fs::create_dir_all(journal_dir)?;
    if dst.join("KILL").exists() {
        std::fs::write(journal_dir.join("KILL"), b"")?;
    }
    std::fs::write(&marker, format!("{ver}
"))?;
    Ok(Some(dst))
}

pub fn book_mode(s8_dir: &Path) -> BookMode {
    #[derive(serde::Deserialize)]
    struct Man {
        #[serde(default)]
        situational: bool,
        #[serde(default)]
        slots: Option<f64>,
        #[serde(default)]
        max_age_h: Option<i64>,
        #[serde(default)]
        horizon_h: Option<i64>,
    }
    let Ok(text) = std::fs::read_to_string(s8_dir.join("manifest.json"))
    else {
        return BookMode::default();
    };
    match serde_json::from_str::<Man>(&text) {
        Ok(m) if m.situational => BookMode {
            sit: true,
            slots: Some(m.slots.unwrap_or(6.0)),
            hold_h: Some(m.max_age_h.unwrap_or(24)),
        },
        Ok(m) => BookMode {
            hold_h: m.horizon_h,
            ..BookMode::default()
        },
        _ => BookMode::default(),
    }
}

pub struct Cfg {
    /// Каталог руки: `…/s8_loop/out/model_pretest` или `…/model`.
    pub s8_dir: PathBuf,
    pub journal_dir: PathBuf,
    pub arm: String,
    pub capital_usd: f64,
    pub fees: FeeTable,
    /// «Сейчас» передаётся снаружи: движок обязан быть разыгрываемым
    /// тестом без подмены системных часов.
    pub now_ms: i64,
}

#[derive(Debug, Default)]
pub struct PassReport {
    pub appended: usize,
    pub opened: usize,
    pub closed: usize,
    pub rejected: usize,
    /// Сделки, чей срок вышел, а разбора ещё нет: ожидание, не потеря.
    pub waiting_review: usize,
}

#[derive(Debug)]
pub enum EngineError {
    Journal(JournalError),
    State(StateError),
}

impl From<JournalError> for EngineError {
    fn from(e: JournalError) -> Self {
        EngineError::Journal(e)
    }
}
impl From<StateError> for EngineError {
    fn from(e: StateError) -> Self {
        EngineError::State(e)
    }
}
impl std::fmt::Display for EngineError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EngineError::Journal(e) => write!(f, "журнал: {e}"),
            EngineError::State(e) => write!(f, "состояние: {e}"),
        }
    }
}

fn side_str(s: Side) -> &'static str {
    match s {
        Side::Long => "long",
        Side::Short => "short",
    }
}

/// Один проход тени. Возвращает отчёт и состояние ПОСЛЕ прохода.
pub fn shadow(cfg: &Cfg) -> Result<(PassReport, State), EngineError> {
    let (mut journal, records, _) = Journal::open(&cfg.journal_dir)?;
    let mut st = derive(cfg.capital_usd, &records)?;

    // Что уже сделано — по журналу, не по памяти. Отказ терминален:
    // отвергнутый вход не переигрывается после снятия выключателя,
    // потому что его момент прошёл, а вход задним числом — выдумка.
    let mut seen_decision: BTreeSet<String> = BTreeSet::new();
    let mut touched: BTreeSet<String> = BTreeSet::new(); // open/close/reject
    let mut closed_keys: BTreeSet<String> = BTreeSet::new();
    for r in &records {
        match &r.event {
            Event::Decision { arm, hour, sym, side, .. } => {
                seen_decision
                    .insert(format!("{arm}:{hour}:{sym}:{}", side_str(*side)));
            }
            Event::Open { pos, .. } => {
                touched.insert(pos.clone());
            }
            Event::Close { pos, .. } => {
                closed_keys.insert(pos.clone());
            }
            Event::Reject { sym, side, reason, .. } => {
                // Ключ отказа записан в причине после «|» — см. ниже.
                if let Some(k) = reason.split('|').nth(1) {
                    touched.insert(k.to_string());
                }
                let _ = (sym, side);
            }
            // Поправку денег пишет только живой исполнитель; тени она
            // не встречается и на дедуп решений не влияет.
            Event::Adjust { .. } => {}
            Event::Kill { .. } => {}
        }
    }

    // Аварийный выключатель — файл-флаг; переходы журналируются.
    let kill_now = cfg.journal_dir.join("KILL").exists();
    let mut appended = 0usize;
    let mut rep = PassReport::default();
    if kill_now != st.kill {
        journal.append(Event::Kill {
            on: kill_now,
            reason: if kill_now {
                "файл KILL появился".into()
            } else {
                "файл KILL снят".into()
            },
            at_ms: cfg.now_ms,
        })?;
        appended += 1;
        st.kill = kill_now;
    }

    // План: все ноги всех часов руки, время входа — КОНЕЦ часа сигнала
    // (признаки считаются по всему часу, раньше входа не существует).
    struct Planned {
        key: String,
        hour: String,
        sym: String,
        side: Side,
        legs_in_hour: usize,
        opened_at: i64,
        closes_at: i64,
        px: Option<f64>,
        cum_in: Option<crate::paper::Book>,
        ver: Option<u32>,
        // Схлопывание: сигнал встречной стороны позиции НЕ открывает,
        // а закрывает старший лот. Зеркало `trades.net_positions` —
        // площадка не даёт двух отдельных лонгов по одной паре.
        netted: bool,
        // Плоский нетто и момент закрытия; книга встречного входа —
        // ЛЕСЕНКА ВЫХОДА схлопнутого лота (тот же выбор, что в Python:
        // выход происходит в книгу того момента, а не прежнего разбора).
        net_close: Option<(f64, i64)>,
        net_book: Option<crate::paper::Book>,
    }
    // Круг издержек схлопнутого лота без лесенки — плоский, ровно как
    // у Python в этом же месте.
    const NET_ROUND_BP: f64 = 11.0;
    let mode = book_mode(&cfg.s8_dir);
    let picks = load_picks(&cfg.s8_dir, &cfg.arm);
    let reviews = load_reviews(&cfg.s8_dir, &cfg.arm);
    let mut plan: Vec<Planned> = Vec::new();
    for p in &picks {
        let Some(h0) = hour_ms(&p.hour) else { continue };
        let hour_close = h0 + 3_600_000;
        let legs = p.long.len() + p.short.len();
        // Денежное событие входа — момент РЕШЕНИЯ цикла, не граница
        // часа: разбор пишется раньше выбора, и касса успевает
        // вернуться. Оставить вход на границе значило бы просить
        // деньги за минуты до их возврата — размер 0 у всей руки
        // (владелец видел это на часовой книге как pnl 0.00).
        let decided = p
            .at_ts
            .map(|t| (t * 1000.0) as i64)
            .unwrap_or(hour_close)
            .max(hour_close);
        let mut add = |leg: &Leg, side: Side| {
            // Живой вход сканера открыт секундой события; строка без
            // метки — часовой вход, открытый моментом решения.
            let opened_at = leg
                .at_ts
                .map(|t| (t * 1000.0) as i64)
                .unwrap_or(decided);
            plan.push(Planned {
                key: format!(
                    "{}:{}:{}:{}",
                    cfg.arm, p.hour, leg.sym, side_str(side)
                ),
                hour: p.hour.clone(),
                sym: leg.sym.clone(),
                side,
                legs_in_hour: legs,
                opened_at,
                // У ситуационной книги СРОКА НЕТ: закрытие задаёт
                // разбор, и его время достаётся ниже из самой строки
                // разбора. 0 — «не назначено», а не «в эпоху».
                closes_at: if mode.sit {
                    0
                } else {
                    hour_close + HOLD_H * 3_600_000
                },
                px: leg.px,
                cum_in: leg.cum.clone(),
                ver: p.ver,
                netted: false,
                net_close: None,
                net_book: None,
            });
        };
        for leg in &p.long {
            add(leg, Side::Long);
        }
        for leg in &p.short {
            add(leg, Side::Short);
        }
    }
    // Срок ситуационной сделки — из разбора: час выхода плюс момент
    // записи, как у Python-кассы (`max(closes_at, review_at)` — деньги
    // не возвращаются раньше, чем исход стал известен).
    if mode.sit {
        for t in plan.iter_mut() {
            if let Some(row) =
                reviews.get(&(t.hour.clone(), t.sym.clone(), t.side))
            {
                let ex = row
                    .exit_hour
                    .as_deref()
                    .and_then(hour_ms)
                    .map(|m| m + 3_600_000)
                    .unwrap_or(0);
                let ra = row
                    .rec_at_ts
                    .map(|v| (v * 1000.0) as i64)
                    .unwrap_or(0);
                // Живой выход закрыт секундой пересечения — её и
                // берём: конец часа держал бы деньги в позиции,
                // которой уже нет, и расходился бы с Python-кассой.
                t.closes_at = row
                    .exit_ts
                    .map(|v| (v * 1000.0) as i64)
                    .unwrap_or_else(|| ex.max(ra));
            }
        }
    }

    // Схлопывание встречной стороны: одно имя — одна позиция.
    // Закрывается самый старый лот (FIFO), по цене входа схлопнувшего
    // сигнала и в его же книгу.
    {
        let mut order: Vec<usize> = (0..plan.len()).collect();
        order.sort_by(|&a, &b| {
            plan[a].opened_at.cmp(&plan[b].opened_at)
                .then(plan[a].sym.cmp(&plan[b].sym))
        });
        let mut live: std::collections::BTreeMap<String, Vec<usize>> =
            std::collections::BTreeMap::new();
        for i in order {
            let (sym, side, now, px) = (
                plan[i].sym.clone(), plan[i].side,
                plan[i].opened_at, plan[i].px,
            );
            let keep = live.entry(sym).or_default();
            keep.retain(|&j| plan[j].closes_at == 0
                        || plan[j].closes_at > now);
            let victim = keep.iter().copied()
                .filter(|&j| plan[j].side != side)
                .min_by_key(|&j| plan[j].opened_at);
            match victim {
                None => keep.push(i),
                Some(v) => {
                    keep.retain(|&j| j != v);
                    if let (Some(px0), Some(px1)) = (plan[v].px, px) {
                        let sign = if plan[v].side == Side::Long {
                            1.0
                        } else {
                            -1.0
                        };
                        let mv = sign * (px1 / px0 - 1.0) * 1e4;
                        plan[v].net_close = Some((mv - NET_ROUND_BP, now));
                        plan[v].net_book = plan[i].cum_in.clone();
                        plan[v].closes_at = now;
                    }
                    plan[i].netted = true;
                }
            }
        }
    }

    // События этого прохода: (момент, 0 выход | 1 вход, номер в плане).
    // Стабильная сортировка держит ноги одного часа в порядке файла —
    // как у Python, где сборка и счёт сохраняют исходный порядок.
    let mut ev: Vec<(i64, u8, usize)> = Vec::new();
    for (i, t) in plan.iter().enumerate() {
        if t.netted {
            continue;                  // позиции нет: ни входа, ни выхода
        }
        if t.opened_at <= cfg.now_ms && !touched.contains(&t.key) {
            ev.push((t.opened_at, 1, i));
        }
        if t.closes_at > 0
            && t.closes_at <= cfg.now_ms
            && (touched.contains(&t.key) || t.opened_at <= cfg.now_ms)
            && !closed_keys.contains(&t.key)
        {
            // Правило «выход раньше входа» — про ЧУЖИЕ сделки: деньги
            // возвращаются в кассу до того, как их снова размещают.
            // Своя сделка закрыться раньше, чем открылась, не может, а
            // сканер закрывает позицию по пути цены и попадает в ту же
            // СЕКУНДУ, что вход (живой случай: CATIUSDT 18:08:35). При
            // общем правиле её выход шёл первым — позиции ещё нет, и
            // ядро теряло закрытие целиком (2 из 3 на фикстуре).
            // Зеркало той же правки в `trades.account`.
            let own = t.opened_at.div_euclid(1000);
            let kind = if t.closes_at.div_euclid(1000) <= own { 2 } else { 0 };
            ev.push((t.closes_at, kind, i));
        }
    }
    // Порядок — по ЦЕЛОЙ секунде, выход в ней раньше входа. Зеркало
    // `trades.account`: разбор пишется с миллисекундами, выбор — целой
    // секундой, и ниже секунды сравнивались бы округления писателей, а
    // не моменты. Секунда одна и та же в обоих счётах.
    ev.sort_by_key(|e| (e.0.div_euclid(1000), e.1));

    for (at, kind, i) in ev {
        let t = &plan[i];
        if kind == 1 {
            // Решение журналируется один раз — до всякого риска.
            if seen_decision.insert(t.key.clone()) {
                journal.append(Event::Decision {
                    src_ts: None,
                    arm: cfg.arm.clone(),
                    hour: t.hour.clone(),
                    sym: t.sym.clone(),
                    side: t.side,
                    px: t.px,
                    ver: t.ver,
                    at_ms: t.opened_at,
                })?;
                appended += 1;
            }
            if st.kill {
                journal.append(Event::Reject {
                    sym: t.sym.clone(),
                    side: t.side,
                    reason: format!("выключатель повёрнут|{}", t.key),
                    at_ms: at,
                })?;
                appended += 1;
                rep.rejected += 1;
                touched.insert(t.key.clone());
                st.rejected += 1;
                continue;
            }
            // Размер — как у Python: доля ПОЛНОГО капитала (касса +
            // занятое) на число слотов часа, но не больше свободного.
            let busy: f64 =
                st.positions.values().map(|p| p.notional_usd).sum();
            let slots = mode.slots.unwrap_or(
                (t.legs_in_hour as f64 * HOLD_H as f64).max(1.0),
            );
            let want = (st.cash_usd + busy) / slots;
            // Забор v4, зеркало NAME_CAP_SHARE из trades.py: суммарная
            // позиция по одному имени не выше 10 % капитала книги.
            // Занятое имени считается по открытым позициям — тот же
            // источник, что busy, второго учёта не заводится.
            let name_busy: f64 = st
                .positions
                .values()
                .filter(|p| p.sym == t.sym)
                .map(|p| p.notional_usd)
                .sum();
            let room = (0.10 * (st.cash_usd + busy) - name_busy).max(0.0);
            let size = want.min(room).min(st.cash_usd).max(0.0);
            if size <= 0.0 {
                journal.append(Event::Reject {
                    sym: t.sym.clone(),
                    side: t.side,
                    reason: format!("касса пуста, вход не размещён|{}", t.key),
                    at_ms: at,
                })?;
                appended += 1;
                rep.rejected += 1;
                touched.insert(t.key.clone());
                st.rejected += 1;
                continue;
            }
            // Цена входа — исполнение с лесенки решения; без книги
            // остаётся цена закрытия часа, и это видно по полю.
            let entry_px = t
                .cum_in
                .as_ref()
                .and_then(|b| {
                    walk(
                        if t.side == Side::Long { &b.a } else { &b.b },
                        size,
                    )
                })
                .map(|(px, _)| px)
                .or(t.px);
            journal.append(Event::Open {
                pos: t.key.clone(),
                sym: t.sym.clone(),
                side: t.side,
                notional_usd: size,
                entry_px,
                fee_usd: 0.0,
                partial: false,
                qty: None,
                target_px: None,
                ver: t.ver,
                at_ms: at,
            })?;
            appended += 1;
            rep.opened += 1;
            st.cash_usd -= size;
            st.positions.insert(
                t.key.clone(),
                crate::state::Position {
                    sym: t.sym.clone(),
                    side: t.side,
                    notional_usd: size,
                    entry_px,
                    fee_usd: 0.0,
                    partial: false,
                    ver: t.ver,
                    opened_at_ms: at,
                },
            );
            touched.insert(t.key.clone());
        } else {
            let Some(pos) = st.positions.get(&t.key) else {
                // Вход отвергнут или ещё не случился — закрывать нечего.
                continue;
            };
            let size = pos.notional_usd;
            let netted = t.net_close;
            let row_opt =
                reviews.get(&(t.hour.clone(), t.sym.clone(), t.side));
            if row_opt.is_none() && netted.is_none() {
                rep.waiting_review += 1;
                continue;
            }
            // Деньги — по записанным книгам, как у Python-счёта; без
            // книг — по нетто разбора прежней основы. Ни то ни другое
            // недоступно — сделка остаётся открытой: посчитать
            // неизвестный исход нулём значит разбавить счёт выдумкой.
            let long = t.side == Side::Long;
            // Схлопнутый лот выходит в книгу встречного входа; нет её —
            // плоский круг. Прежний разбор к нему отношения не имеет.
            let done = if let Some((flat, _)) = netted {
                match (&t.cum_in, &t.net_book) {
                    (Some(cin), Some(cout)) => exec_cost(
                        long, cin, cout, size, &cfg.fees, &t.sym,
                    )
                    .map(|e| {
                        (e.net_bp, Some(e.fill_out), e.fee_bp, "книга")
                    }),
                    _ => None,
                }
                .or(Some((flat, None, NET_ROUND_BP, "плоский 11")))
            } else {
                let row = row_opt.unwrap();
                match (&t.cum_in, &row.cum) {
                    (Some(cin), Some(cout)) => exec_cost(
                        long, cin, cout, size, &cfg.fees, &t.sym,
                    )
                    .map(|e| {
                        (e.net_bp, Some(e.fill_out), e.fee_bp, "книга")
                    }),
                    _ => None,
                }
                .or_else(|| row.net.map(|n| (n, None, 0.0, "плоский 11")))
            };
            let Some((net_bp, fill_out, fee_bp, basis)) = done else {
                rep.waiting_review += 1;
                continue;
            };
            // Полная точность, как в кассе Python: он добавляет к
            // балансу НЕокруглённый pnl, а округляет только запись
            // сделки. Округлив здесь, мы накопили бы расхождение с его
            // балансом по центу на сделку — сверка это и поймала.
            let pnl = size * net_bp / 1e4;
            // Причина закрытия — из разбора (ситуационная книга
            // называет её словами), иначе прежний «срок».
            let why = if netted.is_some() {
                "встречный сигнал закрыл позицию".to_string()
            } else {
                row_opt.and_then(|r| r.reason.clone())
                    .unwrap_or_else(|| "срок".into())
            };
            journal.append(Event::Close {
                pos: t.key.clone(),
                exit_px: fill_out,
                fee_usd: py_round(size * fee_bp / 1e4, 4),
                pnl_usd: pnl,
                reason: format!("{why} ({basis})"),
                at_ms: at,
            })?;
            appended += 1;
            rep.closed += 1;
            st.cash_usd += size + pnl;
            st.realized_pnl_usd += pnl;
            st.closed += 1;
            st.positions.remove(&t.key);
            closed_keys.insert(t.key.clone());
        }
    }
    rep.appended = appended;
    // Итоговое состояние — перечитыванием журнала, а не локальной
    // копией: если копия разошлась с журналом, это дефект, и пусть он
    // упадёт здесь, а не в сверке.
    let (records, _) = crate::journal::read_all(&cfg.journal_dir)?;
    let fresh = derive(cfg.capital_usd, &records)?;
    Ok((rep, fresh))
}

/// Умолчание для пути к таблице ставок — та же выгрузка A1, что читает
/// Python-счёт. Не копия таблицы, а тот же файл.
pub fn default_fees_path(repo_root: &Path) -> PathBuf {
    repo_root.join("research/a1_universe/out/fees.json")
}
