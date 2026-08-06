//! Тесты E1: журнал и состояние.
//!
//! Каждый тест закрывает место, где ошибка была бы НЕВИДИМОЙ: рестарт,
//! оборванный хвост, сутки в двух видах, противоречивые записи. Числа
//! закреплены числами, а не свойствами; отрицательные контроли — то,
//! что порча обязана давать ошибку, а не «как получится».

use bot::events::{Event, Record, Side};
use bot::journal::{read_all, Journal, JournalError};
use bot::state::{derive, StateError};
use std::fs;
use std::path::PathBuf;

/// Свой каталог на тест: имя из номера процесса и имени теста, прежний
/// сносится — прогон не зависит от мусора прошлого прогона.
fn dir(name: &str) -> PathBuf {
    let p = std::env::temp_dir().join(format!("bot-e1-{}-{}", std::process::id(), name));
    let _ = fs::remove_dir_all(&p);
    fs::create_dir_all(&p).unwrap();
    p
}

/// 2026-08-05 12:00:00 UTC — все события кладутся днём, чтобы ротация
/// случалась только там, где тест её просит.
const T0: i64 = 1_785_931_200_000;

fn open_ev(pos: &str, notional: f64, at: i64) -> Event {
    Event::Open {
        pos: pos.into(),
        sym: "AUSDT".into(),
        side: Side::Long,
        notional_usd: notional,
        entry_px: Some(100.0),
        fee_usd: 0.02,
        partial: false,
        ver: Some(3),
        at_ms: at,
    }
}

fn close_ev(pos: &str, pnl: f64, at: i64) -> Event {
    Event::Close {
        pos: pos.into(),
        exit_px: Some(101.0),
        fee_usd: 0.02,
        pnl_usd: pnl,
        reason: "срок".into(),
        at_ms: at,
    }
}

/// Шесть событий обычного часа: решение, отказ, два входа, выход,
/// выключатель. По ним считаются почти все проверки ниже.
fn six_events() -> Vec<Event> {
    vec![
        Event::Decision {
            arm: "gbm".into(),
            hour: "2026-08-05-11".into(),
            sym: "AUSDT".into(),
            side: Side::Long,
            px: Some(100.0),
            ver: Some(3),
            at_ms: T0,
        },
        Event::Reject {
            sym: "BUSDT".into(),
            side: Side::Short,
            reason: "плечо: гросс превысил бы капитал".into(),
            at_ms: T0 + 1_000,
        },
        open_ev("gbm:2026-08-05-11:AUSDT:long", 41.66, T0 + 2_000),
        open_ev("gbm:2026-08-05-11:CUSDT:short", 41.66, T0 + 3_000),
        close_ev("gbm:2026-08-05-11:AUSDT:long", 1.25, T0 + 4_000),
        Event::Kill { on: true, reason: "проверка".into(), at_ms: T0 + 5_000 },
    ]
}

fn write_all(dirp: &PathBuf, events: &[Event]) {
    let (mut j, rec, rep) = Journal::open(dirp).unwrap();
    assert!(rec.is_empty() && rep.dropped_tail == 0);
    for e in events {
        j.append(e.clone()).unwrap();
    }
}

fn state_json(dirp: &PathBuf) -> String {
    let (records, _) = read_all(dirp).unwrap();
    serde_json::to_string(&derive(1000.0, &records).unwrap()).unwrap()
}

#[test]
fn roundtrip_числа_кассы_точны() {
    let d = dir("roundtrip");
    write_all(&d, &six_events());
    let (records, rep) = read_all(&d).unwrap();
    assert_eq!(records.len(), 6);
    assert_eq!(rep.dropped_tail, 0);
    let st = derive(1000.0, &records).unwrap();
    // Касса: 1000 − 41.66 − 41.66 (входы) + 41.66 + 1.25 (выход).
    assert!((st.cash_usd - 959.59).abs() < 1e-9, "cash {}", st.cash_usd);
    assert!((st.realized_pnl_usd - 1.25).abs() < 1e-9);
    assert_eq!(st.positions.len(), 1);
    assert!(st.positions.contains_key("gbm:2026-08-05-11:CUSDT:short"));
    assert_eq!((st.decisions, st.rejected, st.closed), (1, 1, 1));
    assert!(st.kill);
    assert_eq!(st.last_seq, 6);
}

#[test]
fn рестарт_на_каждой_границе_восстанавливает_бит_в_бит() {
    // Журнал режется после каждой строки — как будто процесс умер там.
    // Состояние из куска обязано совпасть с состоянием из тех же
    // событий, записанных заново, дословно по JSON.
    let d = dir("cut");
    write_all(&d, &six_events());
    let full = fs::read_to_string(d.join("journal-2026-08-05.jsonl")).unwrap();
    let lines: Vec<&str> = full.trim_end().split('\n').collect();
    assert_eq!(lines.len(), 6);
    for k in 0..=6 {
        let dk = dir(&format!("cut-{k}"));
        let mut cut: String = lines[..k].join("\n");
        if k > 0 {
            cut.push('\n');
        }
        fs::write(dk.join("journal-2026-08-05.jsonl"), &cut).unwrap();
        let de = dir(&format!("cut-ref-{k}"));
        write_all(&de, &six_events()[..k]);
        assert_eq!(state_json(&dk), state_json(&de), "рез после {k} строк");
    }
}

#[test]
fn оборванный_хвост_отбрасывается_и_считается() {
    let d = dir("tail");
    write_all(&d, &six_events());
    let p = d.join("journal-2026-08-05.jsonl");
    let mut txt = fs::read_to_string(&p).unwrap();
    txt.push_str("{\"seq\":7,\"ev\":\"kill\",\"on\":fa"); // обрыв на полуслове
    fs::write(&p, &txt).unwrap();
    let (records, rep) = read_all(&d).unwrap();
    assert_eq!(records.len(), 6, "хвост не должен ничего утащить за собой");
    assert_eq!(rep.dropped_tail, 1, "потеря обязана быть названа числом");
    // Продолжение после такого рестарта не дырявит нумерацию.
    let (mut j, rec, _) = Journal::open(&d).unwrap();
    assert_eq!(rec.len(), 6);
    let seq = j.append(close_ev("gbm:2026-08-05-11:CUSDT:short", -0.5, T0 + 6_000)).unwrap();
    assert_eq!(seq, 7);
}

#[test]
fn порча_в_середине_это_ошибка_а_не_пропуск() {
    // Отброшенная середина тихо теряла бы сделку — чтение обязано
    // остановиться. Это отрицательный контроль мягкости хвоста.
    let d = dir("mid");
    write_all(&d, &six_events());
    let p = d.join("journal-2026-08-05.jsonl");
    let txt = fs::read_to_string(&p).unwrap();
    let broken: Vec<String> = txt
        .trim_end()
        .split('\n')
        .enumerate()
        .map(|(i, l)| if i == 2 { "мусор".to_string() } else { l.to_string() })
        .collect();
    fs::write(&p, broken.join("\n") + "\n").unwrap();
    match read_all(&d) {
        Err(JournalError::CorruptLine { line, .. }) => assert_eq!(line, 3),
        other => panic!("ожидалась CorruptLine, получено {other:?}"),
    }
}

#[test]
fn ротация_сжимает_старые_сутки_и_читает_оба() {
    let d = dir("rotate");
    let day2 = T0 + 86_400_000;
    let mut evs = six_events();
    evs.push(open_ev("gbm:2026-08-06-11:DUSDT:long", 10.0, day2));
    write_all(&d, &evs);
    assert!(
        d.join("journal-2026-08-05.jsonl.gz").exists()
            && !d.join("journal-2026-08-05.jsonl").exists(),
        "старые сутки обязаны сжаться и исчезнуть простым файлом"
    );
    assert!(d.join("journal-2026-08-06.jsonl").exists());
    let (records, _) = read_all(&d).unwrap();
    assert_eq!(records.len(), 7);
    let st = derive(1000.0, &records).unwrap();
    assert_eq!(st.positions.len(), 2);
}

#[test]
fn сутки_в_двух_видах_не_читаются_дважды() {
    // Обрыв между rename и удалением оставляет и простой, и сжатый
    // файл. Удвоенный час уже был дефектом B1 — здесь дубли снимаются
    // по номеру строки.
    let d = dir("twins");
    let day2 = T0 + 86_400_000;
    let mut evs = six_events();
    evs.push(open_ev("gbm:2026-08-06-11:DUSDT:long", 10.0, day2));
    write_all(&d, &evs);
    // Воссоздаём простой файл рядом со сжатым — дословно тот же.
    let gz = d.join("journal-2026-08-05.jsonl.gz");
    let mut text = String::new();
    use std::io::Read;
    flate2::read::GzDecoder::new(fs::File::open(&gz).unwrap())
        .read_to_string(&mut text)
        .unwrap();
    fs::write(d.join("journal-2026-08-05.jsonl"), &text).unwrap();
    let (records, _) = read_all(&d).unwrap();
    assert_eq!(records.len(), 7, "дубль суток не вправе удвоить события");
}

#[test]
fn битый_гзип_спасается_простым_близнецом_или_ошибка() {
    let d = dir("gzbad");
    let day2 = T0 + 86_400_000;
    let mut evs = six_events();
    evs.push(open_ev("gbm:2026-08-06-11:DUSDT:long", 10.0, day2));
    write_all(&d, &evs);
    let gz = d.join("journal-2026-08-05.jsonl.gz");
    let plain = d.join("journal-2026-08-05.jsonl");
    // Близнеца нет, gz испорчен — потеря обязана быть названа.
    let good = fs::read(&gz).unwrap();
    fs::write(&gz, &good[..good.len() / 2]).unwrap();
    match read_all(&d) {
        Err(JournalError::LostDay { day }) => assert_eq!(day, "2026-08-05"),
        other => panic!("ожидалась LostDay, получено {other:?}"),
    }
    // Появился близнец — сутки спасены, и спасение посчитано.
    let mut text = String::new();
    use std::io::Read;
    flate2::read::GzDecoder::new(std::io::Cursor::new(good.clone()))
        .read_to_string(&mut text)
        .unwrap();
    fs::write(&plain, &text).unwrap();
    let (records, rep) = read_all(&d).unwrap();
    assert_eq!(records.len(), 7);
    assert_eq!(rep.gz_salvaged, 1);
}

#[test]
fn противоречие_и_регресс_номеров_это_ошибки() {
    let d = dir("contra");
    write_all(&d, &six_events()[..3].to_vec());
    let p = d.join("journal-2026-08-05.jsonl");
    // Тот же номер, другое событие.
    let mut txt = fs::read_to_string(&p).unwrap();
    let fake = Record { seq: 3, event: close_ev("x", 9.9, T0 + 9_000) };
    txt.push_str(&(serde_json::to_string(&fake).unwrap() + "\n"));
    fs::write(&p, &txt).unwrap();
    assert!(matches!(
        read_all(&d),
        Err(JournalError::Contradiction { seq: 3 })
    ));
    // Дыра в нумерации: выброшенная середина — потерянная сделка,
    // и читатель обязан остановиться, а не перешагнуть.
    let d2 = dir("gap");
    write_all(&d2, &six_events()[..3].to_vec());
    let p2 = d2.join("journal-2026-08-05.jsonl");
    let txt2 = fs::read_to_string(&p2).unwrap();
    let kept: Vec<&str> = txt2
        .trim_end()
        .split('\n')
        .enumerate()
        .filter(|(i, _)| *i != 1)
        .map(|(_, l)| l)
        .collect();
    fs::write(&p2, kept.join("\n") + "\n").unwrap();
    assert!(matches!(
        read_all(&d2),
        Err(JournalError::SeqRegression { seq: 3, .. })
    ));
    // И журнал, начатый не с единицы (удалённые ранние сутки), — тоже
    // ошибка: открытая в потерянном куске позиция исчезла бы молча.
    let d3 = dir("headless");
    write_all(&d3, &six_events()[..3].to_vec());
    let p3 = d3.join("journal-2026-08-05.jsonl");
    let txt3 = fs::read_to_string(&p3).unwrap();
    let tail: Vec<&str> = txt3.trim_end().split('\n').skip(1).collect();
    fs::write(&p3, tail.join("\n") + "\n").unwrap();
    assert!(matches!(
        read_all(&d3),
        Err(JournalError::SeqRegression { seq: 2, .. })
    ));
}

#[test]
fn двойное_открытие_и_чужое_закрытие_это_ошибки_состояния() {
    let recs = |evs: Vec<Event>| -> Vec<Record> {
        evs.into_iter()
            .enumerate()
            .map(|(i, e)| Record { seq: i as u64 + 1, event: e })
            .collect()
    };
    let двойное = recs(vec![
        open_ev("p1", 10.0, T0),
        open_ev("p1", 10.0, T0 + 1_000),
    ]);
    assert_eq!(
        derive(1000.0, &двойное),
        Err(StateError::DoubleOpen { pos: "p1".into(), seq: 2 })
    );
    let чужое = recs(vec![close_ev("нет-такой", 1.0, T0)]);
    assert_eq!(
        derive(1000.0, &чужое),
        Err(StateError::CloseWithoutOpen { pos: "нет-такой".into(), seq: 1 })
    );
}

#[test]
fn повторное_открытие_продолжает_нумерацию_без_дублей() {
    let d = dir("reopen");
    write_all(&d, &six_events());
    // Второй запуск того же журнала — как рестарт процесса.
    let (mut j, records, _) = Journal::open(&d).unwrap();
    assert_eq!(records.len(), 6);
    let seq = j.append(close_ev("gbm:2026-08-05-11:CUSDT:short", 0.5, T0 + 10_000)).unwrap();
    assert_eq!(seq, 7, "нумерация продолжается, а не начинается заново");
    let (records, _) = read_all(&d).unwrap();
    assert_eq!(records.len(), 7);
    let st = derive(1000.0, &records).unwrap();
    assert_eq!(st.positions.len(), 0);
    assert_eq!(st.closed, 2);
    // Пустой каталог для сравнения: те же семь событий одним заходом
    // дают то же состояние дословно.
    let d2 = dir("reopen-ref");
    let mut evs = six_events();
    evs.push(close_ev("gbm:2026-08-05-11:CUSDT:short", 0.5, T0 + 10_000));
    write_all(&d2, &evs);
    assert_eq!(state_json(&d), state_json(&d2));
}
