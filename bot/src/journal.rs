//! Журнал: append-only файл событий, суточная ротация, честное чтение.
//!
//! Устройство повторяет выстраданное хранилище B1, а не изобретает
//! своё:
//!
//! - текущие сутки пишутся ПРОСТЫМ текстом — обрыв записи стоит одной
//!   строки, и только последней;
//! - закрытые сутки сжимаются целиком и атомарно (tmp → rename →
//!   удаление исходника). Дозаписи в gzip не бывает: каждый запуск
//!   добавлял бы новый член архива, а обрыв посреди записи терял ВЕСЬ
//!   хвост файла — этот дефект уже терял данные сборщика;
//! - обрыв между rename и удалением оставляет сутки в двух видах —
//!   читатель берёт оба и снимает дубли по номеру строки, потому что
//!   удвоить сделку хуже, чем прочитать файл дважды.

use crate::events::{Event, Record};
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

/// Что чтение нашло, помимо самих записей. Пустота обязана отличаться
/// от потери, поэтому потери называются числами.
#[derive(Debug, Default, PartialEq)]
pub struct ReadReport {
    /// Оборванных строк в хвосте последнего простого файла (0 или 1 —
    /// при write-ahead с fsync больше одной не бывает).
    pub dropped_tail: usize,
    /// Суток, у которых сжатый файл оказался битым и спасли простой
    /// близнец.
    pub gz_salvaged: usize,
    pub files: usize,
}

#[derive(Debug)]
pub enum JournalError {
    Io(std::io::Error),
    /// Порча НЕ в хвосте. Отброшенная середина значила бы тихо потерять
    /// сделку — на этом чтение обязано остановиться, а не «продолжить
    /// как получится».
    CorruptLine { file: String, line: usize, why: String },
    /// Два разных события под одним номером — журнал противоречив.
    Contradiction { seq: u64 },
    /// Номер вне очереди: номера идут подряд с единицы, и разрыв
    /// означает потерянный кусок журнала — по дырявой истории позиции
    /// не восстановить, открытая в потерянном куске просто исчезла бы.
    SeqRegression { file: String, seq: u64 },
    /// Сжатые сутки битые, а простого близнеца нет.
    LostDay { day: String },
}

impl From<std::io::Error> for JournalError {
    fn from(e: std::io::Error) -> Self {
        JournalError::Io(e)
    }
}

impl std::fmt::Display for JournalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            JournalError::Io(e) => write!(f, "ввод-вывод: {e}"),
            JournalError::CorruptLine { file, line, why } => write!(
                f,
                "порча не в хвосте: {file}, строка {line}: {why} — \
                 состояние по такому журналу не выводится"
            ),
            JournalError::Contradiction { seq } => write!(
                f,
                "противоречие: два разных события под номером {seq}"
            ),
            JournalError::SeqRegression { file, seq } => write!(
                f,
                "номер {seq} вне очереди ({file}) — журнал дырявый \
                 или куски перепутаны"
            ),
            JournalError::LostDay { day } => write!(
                f,
                "сутки {day}: сжатый файл битый, простого близнеца нет"
            ),
        }
    }
}

/// Пишущая сторона. Читателей может быть сколько угодно, писатель один.
pub struct Journal {
    dir: PathBuf,
    seq: u64,
    /// Сутки открытого файла (`YYYY-MM-DD`). Ротация — по дате события,
    /// а не по настенным часам: так поведение детерминировано и
    /// разыгрывается тестом без подмены времени.
    day: String,
    file: Option<File>,
}

impl Journal {
    /// Открыть журнал в каталоге; номер продолжается с найденного, а не
    /// с нуля — иначе рестарт раздвоил бы нумерацию.
    pub fn open(dir: &Path) -> Result<(Journal, Vec<Record>, ReadReport), JournalError> {
        fs::create_dir_all(dir)?;
        let (records, report) = read_all(dir)?;
        let seq = records.last().map(|r| r.seq).unwrap_or(0);
        Ok((
            Journal { dir: dir.to_path_buf(), seq, day: String::new(), file: None },
            records,
            report,
        ))
    }

    /// Записать событие: сначала строка с fsync, потом действие у
    /// вызывающего (write-ahead). Возвращает присвоенный номер.
    pub fn append(&mut self, ev: Event) -> Result<u64, JournalError> {
        let day = utc_day(ev.at_ms());
        if self.file.is_none() || day != self.day {
            // Перед первой строкой новых суток закрываются и сжимаются
            // ВСЕ простые файлы старших дат — в том числе оставшиеся от
            // прежнего запуска, до которых прошлая ротация не дошла.
            self.file = None;
            for old in plain_days(&self.dir)? {
                if old < day {
                    compress_day(&self.dir, &old)?;
                }
            }
            let f = OpenOptions::new()
                .create(true)
                .append(true)
                .open(self.dir.join(format!("journal-{day}.jsonl")))?;
            self.day = day;
            self.file = Some(f);
        }
        self.seq += 1;
        let rec = Record { seq: self.seq, event: ev };
        let mut line = serde_json::to_string(&rec).expect("сериализация события");
        line.push('\n');
        let f = self.file.as_mut().expect("файл открыт строкой выше");
        f.write_all(line.as_bytes())?;
        // fsync на каждое событие: журнал денег, событий десятки в час —
        // цена нулевая, а «записано» обязано означать «на диске».
        f.sync_data()?;
        Ok(self.seq)
    }
}

/// Прочитать весь журнал каталога: сутки по возрастанию, внутри — по
/// номеру; дубли сняты, противоречия и порча не в хвосте — ошибка.
pub fn read_all(dir: &Path) -> Result<(Vec<Record>, ReadReport), JournalError> {
    let mut days: BTreeMap<String, (bool, bool)> = BTreeMap::new(); // (plain, gz)
    if dir.is_dir() {
        for e in fs::read_dir(dir)? {
            let name = e?.file_name().to_string_lossy().into_owned();
            if let Some(d) = name.strip_prefix("journal-") {
                if let Some(d) = d.strip_suffix(".jsonl") {
                    days.entry(d.to_string()).or_default().0 = true;
                } else if let Some(d) = d.strip_suffix(".jsonl.gz") {
                    days.entry(d.to_string()).or_default().1 = true;
                }
            }
        }
    }
    let mut report = ReadReport::default();
    let mut out: Vec<Record> = Vec::new();
    let mut seen: BTreeMap<u64, String> = BTreeMap::new();
    let last_day = days.keys().next_back().cloned();
    for (day, (plain, gz)) in &days {
        let plain_path = dir.join(format!("journal-{day}.jsonl"));
        let gz_path = dir.join(format!("journal-{day}.jsonl.gz"));
        // Хвост вправе быть оборванным только у ПОСЛЕДНИХ суток и
        // только в простом файле: всё остальное закрыто целиком.
        let tail_ok = *plain && Some(day) == last_day.as_ref();
        let mut texts: Vec<(String, String)> = Vec::new();
        if *gz {
            match read_gz(&gz_path) {
                Ok(t) => texts.push((gz_path.display().to_string(), t)),
                Err(_) if *plain => report.gz_salvaged += 1, // близнец ниже
                Err(_) => return Err(JournalError::LostDay { day: day.clone() }),
            }
        }
        if *plain {
            texts.push((
                plain_path.display().to_string(),
                fs::read_to_string(&plain_path)?,
            ));
        }
        report.files += texts.len();
        for (fname, text) in texts {
            let lines: Vec<&str> = text.split('\n').collect();
            let n = lines.len();
            for (i, line) in lines.iter().enumerate() {
                if line.is_empty() {
                    continue;
                }
                let rec: Record = match serde_json::from_str(line) {
                    Ok(r) => r,
                    Err(e) => {
                        // Последняя непустая строка последних суток —
                        // оборванная запись write-ahead: действия не
                        // было, строка отбрасывается со счётом.
                        let is_tail = tail_ok
                            && fname.ends_with(".jsonl")
                            && lines[i + 1..].iter().all(|l| l.is_empty());
                        if is_tail {
                            report.dropped_tail += 1;
                            continue;
                        }
                        let _ = n;
                        return Err(JournalError::CorruptLine {
                            file: fname.clone(),
                            line: i + 1,
                            why: e.to_string(),
                        });
                    }
                };
                match seen.get(&rec.seq) {
                    // Дубль суток «и простые, и сжатые»: строки обязаны
                    // совпадать дословно, иначе это не дубль, а подмена.
                    Some(prev) if prev == line => continue,
                    Some(_) => {
                        return Err(JournalError::Contradiction { seq: rec.seq })
                    }
                    None => {}
                }
                // Подряд и с единицы, а не просто по возрастанию:
                // разрыв — это потерянная строка, то есть тихо
                // исчезнувшая сделка, и state по такому не выводится.
                let expect = out.last().map(|r| r.seq + 1).unwrap_or(1);
                if rec.seq != expect {
                    return Err(JournalError::SeqRegression {
                        file: fname.clone(),
                        seq: rec.seq,
                    });
                }
                seen.insert(rec.seq, line.to_string());
                out.push(rec);
            }
        }
    }
    Ok((out, report))
}

/// Простые (несжатые) сутки каталога.
fn plain_days(dir: &Path) -> Result<Vec<String>, JournalError> {
    let mut out = Vec::new();
    for e in fs::read_dir(dir)? {
        let name = e?.file_name().to_string_lossy().into_owned();
        if let Some(d) = name.strip_prefix("journal-") {
            if let Some(d) = d.strip_suffix(".jsonl") {
                out.push(d.to_string());
            }
        }
    }
    out.sort();
    Ok(out)
}

/// Сжать сутки целиком и атомарно: tmp → fsync → rename → удалить
/// исходник. Обрыв на любом шаге не теряет данных: до rename жив
/// простой файл, после — оба, и читатель снимет дубли.
fn compress_day(dir: &Path, day: &str) -> Result<(), JournalError> {
    let plain = dir.join(format!("journal-{day}.jsonl"));
    let gz = dir.join(format!("journal-{day}.jsonl.gz"));
    let tmp = dir.join(format!("journal-{day}.jsonl.gz.tmp"));
    let bytes = fs::read(&plain)?;
    let f = File::create(&tmp)?;
    let mut enc = GzEncoder::new(f, flate2::Compression::default());
    enc.write_all(&bytes)?;
    let f = enc.finish()?;
    f.sync_data()?;
    fs::rename(&tmp, &gz)?;
    fs::remove_file(&plain)?;
    Ok(())
}

fn read_gz(path: &Path) -> std::io::Result<String> {
    let mut s = String::new();
    GzDecoder::new(File::open(path)?).read_to_string(&mut s)?;
    Ok(s)
}

/// Сутки UTC по метке в миллисекундах: `YYYY-MM-DD`.
/// Календарь — алгоритм civil_from_days, чтобы не тянуть chrono ради
/// одной даты.
pub fn utc_day(at_ms: i64) -> String {
    let days = at_ms.div_euclid(86_400_000);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    format!("{y:04}-{m:02}-{d:02}")
}

#[cfg(test)]
mod tests {
    use super::utc_day;

    #[test]
    fn calendar_matches_known_dates() {
        // Значения закреплены ЧИСЛОМ, не свойством (урок зерна R3).
        assert_eq!(utc_day(0), "1970-01-01");
        assert_eq!(utc_day(1_785_968_400_000), "2026-08-05");
        assert_eq!(utc_day(1_785_974_400_000), "2026-08-06"); // полночь
        assert_eq!(utc_day(1_785_974_399_999), "2026-08-05"); // за 1 мс до
        assert_eq!(utc_day(951_782_400_000), "2000-02-29"); // високосный
    }
}
