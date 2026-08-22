//! Площадка: подпись и запросы Bybit V5 (спека 12, этап X1).
//!
//! Один клиент на чтение и на заявки. База URL — параметр, а не
//! константа: X1 гоняется против тестовой сети, X3 против боевой, и
//! код обязан быть одним — различие двух сред, зашитое в код, стало
//! бы различием двух программ.
//!
//! Правила обращения с ключом:
//!  - ключ живёт файлом вне репозитория (`~/.bybit/live.env`), права
//!    600, читается при старте;
//!  - секрет не печатается НИКОГДА: ни в журнал, ни в ошибку, ни в
//!    Debug — вывод ключа отдаёт длину, не содержимое;
//!  - подпись — HMAC-SHA256(timestamp + api_key + recv_window +
//!    payload), как требует V5.

use hmac::{Hmac, Mac};
use serde_json::Value;
use sha2::Sha256;
use std::path::Path;

/// Ключ и секрет. Debug и Display нарочно не выводят содержимое.
pub struct Keys {
    pub key: String,
    secret: String,
}

impl std::fmt::Debug for Keys {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Длина — достаточно, чтобы отличить пустой ключ от живого;
        // содержимое не попадает ни в какой вывод.
        write!(
            f,
            "Keys{{key: {}…({}), secret: ({} байт)}}",
            &self.key.chars().take(4).collect::<String>(),
            self.key.len(),
            self.secret.len()
        )
    }
}

impl Keys {
    /// Читает env-файл вида `BYBIT_KEY=…` / `BYBIT_SECRET=…`.
    ///
    /// Файл кладёт владелец руками, поэтому разбор терпим к тому,
    /// как его вставили: CRLF, пробелы вокруг `=`, пустые строки и
    /// строки-комментарии. Нетерпим он к отсутствию полей: ключ без
    /// секрета — отказ словами, а не пустая строка в подпись.
    pub fn load(path: &Path) -> Result<Keys, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| format!("файл ключа {} не читается: {e}", path.display()))?;
        let mut key = None;
        let mut secret = None;
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let Some((name, val)) = line.split_once('=') else {
                continue;
            };
            let val = val.trim().to_string();
            match name.trim() {
                "BYBIT_KEY" => key = Some(val),
                "BYBIT_SECRET" => secret = Some(val),
                _ => {}
            }
        }
        match (key, secret) {
            (Some(k), Some(s)) if !k.is_empty() && !s.is_empty() => {
                Ok(Keys { key: k, secret: s })
            }
            _ => Err(format!(
                "в {} нет BYBIT_KEY и BYBIT_SECRET",
                path.display()
            )),
        }
    }

    /// Подпись V5: hex(HMAC-SHA256(secret, ts + key + recv + payload)).
    pub fn sign(&self, ts_ms: i64, recv_window_ms: i64, payload: &str) -> String {
        let mut mac = Hmac::<Sha256>::new_from_slice(self.secret.as_bytes())
            .expect("hmac принимает ключ любой длины");
        mac.update(ts_ms.to_string().as_bytes());
        mac.update(self.key.as_bytes());
        mac.update(recv_window_ms.to_string().as_bytes());
        mac.update(payload.as_bytes());
        hex::encode(mac.finalize().into_bytes())
    }
}

/// Ответ площадки: `retCode == 0` — успех, иначе отказ с текстом.
/// Разность имён (`retCode`/`ret_code`) площадка не использует в V5,
/// но `retMsg` бывает пустым — тогда в ошибке остаётся код.
fn unwrap_ret(v: Value, what: &str) -> Result<Value, String> {
    let code = v.get("retCode").and_then(Value::as_i64).unwrap_or(-1);
    if code == 0 {
        Ok(v.get("result").cloned().unwrap_or(Value::Null))
    } else {
        let msg = v.get("retMsg").and_then(Value::as_str).unwrap_or("");
        Err(format!("{what}: retCode {code} {msg}"))
    }
}

pub struct Venue {
    pub base: String,
    keys: Keys,
    agent: ureq::Agent,
    /// Насколько наши часы отстают от часов площадки (их минус наши).
    /// Подпись живёт `recv_window` миллисекунд от МЕТКИ, и метка со
    /// сдвинутых часов протухает до отправки — измеряется при старте,
    /// а не предполагается нулевым.
    pub skew_ms: i64,
    pub recv_window_ms: i64,
}

impl Venue {
    pub fn new(base: &str, keys: Keys) -> Venue {
        Venue {
            base: base.trim_end_matches('/').to_string(),
            keys,
            agent: ureq::AgentBuilder::new()
                .timeout(std::time::Duration::from_secs(10))
                .build(),
            skew_ms: 0,
            recv_window_ms: 5_000,
        }
    }

    fn now_ms(&self) -> i64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("время после эпохи")
            .as_millis() as i64
            + self.skew_ms
    }

    /// Время площадки — публичный вызов без подписи.
    pub fn server_time_ms(&self) -> Result<i64, String> {
        let url = format!("{}/v5/market/time", self.base);
        let v: Value = self
            .agent
            .get(&url)
            .call()
            .map_err(|e| format!("time: {e}"))?
            .into_json()
            .map_err(|e| format!("time: json: {e}"))?;
        let r = unwrap_ret(v, "time")?;
        r.get("timeNano")
            .and_then(Value::as_str)
            .and_then(|s| s.parse::<i128>().ok())
            .map(|n| (n / 1_000_000) as i64)
            .ok_or_else(|| "time: нет timeNano".into())
    }

    /// Меряет сдвиг часов и запоминает его для подписи.
    pub fn sync_clock(&mut self) -> Result<i64, String> {
        let t0 = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("время после эпохи")
            .as_millis() as i64;
        let srv = self.server_time_ms()?;
        let t1 = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("время после эпохи")
            .as_millis() as i64;
        // Серверную метку сравниваем с серединой запроса: сетевой
        // путь входит в замер поровну в обе стороны.
        self.skew_ms = srv - (t0 + t1) / 2;
        Ok(self.skew_ms)
    }

    /// Подписанный GET: query уже собран строкой `k=v&k2=v2`.
    pub fn get(&self, path: &str, query: &str) -> Result<Value, String> {
        let ts = self.now_ms();
        let sign = self.keys.sign(ts, self.recv_window_ms, query);
        let url = if query.is_empty() {
            format!("{}{}", self.base, path)
        } else {
            format!("{}{}?{}", self.base, path, query)
        };
        let v: Value = self
            .agent
            .get(&url)
            .set("X-BAPI-API-KEY", &self.keys.key)
            .set("X-BAPI-TIMESTAMP", &ts.to_string())
            .set("X-BAPI-RECV-WINDOW", &self.recv_window_ms.to_string())
            .set("X-BAPI-SIGN", &sign)
            .call()
            .map_err(|e| format!("GET {path}: {e}"))?
            .into_json()
            .map_err(|e| format!("GET {path}: json: {e}"))?;
        unwrap_ret(v, path)
    }

    /// Подписанный POST: тело подписывается ДОСЛОВНО той же строкой,
    /// которая уходит на провод, — сериализуем один раз и подписываем
    /// именно её, а не «такой же» объект.
    pub fn post(&self, path: &str, body: &Value) -> Result<Value, String> {
        let raw = serde_json::to_string(body).expect("json");
        let ts = self.now_ms();
        let sign = self.keys.sign(ts, self.recv_window_ms, &raw);
        let url = format!("{}{}", self.base, path);
        let v: Value = self
            .agent
            .post(&url)
            .set("X-BAPI-API-KEY", &self.keys.key)
            .set("X-BAPI-TIMESTAMP", &ts.to_string())
            .set("X-BAPI-RECV-WINDOW", &self.recv_window_ms.to_string())
            .set("X-BAPI-SIGN", &sign)
            .set("Content-Type", "application/json")
            .send_string(&raw)
            .map_err(|e| format!("POST {path}: {e}"))?
            .into_json()
            .map_err(|e| format!("POST {path}: json: {e}"))?;
        unwrap_ret(v, path)
    }

    // --- чтение ------------------------------------------------------

    /// Баланс единого счёта в USDT: (equity, доступно).
    pub fn wallet_usdt(&self) -> Result<(f64, f64), String> {
        let r = self.get(
            "/v5/account/wallet-balance",
            "accountType=UNIFIED&coin=USDT",
        )?;
        let list = r
            .get("list")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        for acc in &list {
            for c in acc
                .get("coin")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
            {
                if c.get("coin").and_then(Value::as_str) == Some("USDT") {
                    let f = |k: &str| {
                        c.get(k)
                            .and_then(Value::as_str)
                            .and_then(|s| s.parse::<f64>().ok())
                            .unwrap_or(0.0)
                    };
                    // У единого счёта доступное поле называется
                    // availableToWithdraw либо пусто — берём equity
                    // и walletBalance, они есть всегда.
                    return Ok((f("equity"), f("walletBalance")));
                }
            }
        }
        Err("wallet: в ответе нет USDT".into())
    }

    /// Открытые позиции по всем линейным USDT-перпам:
    /// (symbol, side, size, avgPrice, unrealisedPnl).
    pub fn positions(&self) -> Result<Vec<(String, String, f64, f64, f64)>, String> {
        let r = self.get(
            "/v5/position/list",
            "category=linear&settleCoin=USDT&limit=200",
        )?;
        let mut out = Vec::new();
        for p in r
            .get("list")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
        {
            let f = |k: &str| {
                p.get(k)
                    .and_then(Value::as_str)
                    .and_then(|s| s.parse::<f64>().ok())
                    .unwrap_or(0.0)
            };
            let size = f("size");
            if size == 0.0 {
                continue;
            }
            out.push((
                p.get("symbol").and_then(Value::as_str).unwrap_or("").into(),
                p.get("side").and_then(Value::as_str).unwrap_or("").into(),
                size,
                f("avgPrice"),
                f("unrealisedPnl"),
            ));
        }
        Ok(out)
    }

    /// Открытые заявки: (symbol, orderId, side, qty, price).
    pub fn open_orders(&self) -> Result<Vec<(String, String, String, f64, f64)>, String> {
        let r = self.get(
            "/v5/order/realtime",
            "category=linear&settleCoin=USDT&limit=50",
        )?;
        let mut out = Vec::new();
        for o in r
            .get("list")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
        {
            let f = |k: &str| {
                o.get(k)
                    .and_then(Value::as_str)
                    .and_then(|s| s.parse::<f64>().ok())
                    .unwrap_or(0.0)
            };
            out.push((
                o.get("symbol").and_then(Value::as_str).unwrap_or("").into(),
                o.get("orderId").and_then(Value::as_str).unwrap_or("").into(),
                // Метка заявки — по ней восстановление после
                // перезапуска находит СВОЮ лежащую цель.
                o.get("orderLinkId").and_then(Value::as_str).unwrap_or("").into(),
                f("qty"),
                f("price"),
            ));
        }
        Ok(out)
    }

    /// Реализованный результат ЗАКРЫТЫХ позиций по имени за окно:
    /// (createdTime мс, closedPnl $). Единственный источник денег
    /// сделки, закрытой мимо исполнителя (вручную либо биржей), —
    /// журнал их не знает, а площадка знает: `closedPnl` уже нетто,
    /// комиссии обеих ног вычтены ею самой. Окно у площадки не шире
    /// семи суток — позиции книги живут меньше, для нашего случая
    /// этого хватает; более широкий запрос она отвергнет сама, и
    /// отказ виден, а не проглочен.
    pub fn closed_pnl(
        &self,
        symbol: &str,
        start_ms: i64,
        end_ms: i64,
    ) -> Result<Vec<(i64, f64)>, String> {
        let r = self.get(
            "/v5/position/closed-pnl",
            &format!(
                "category=linear&symbol={symbol}\
                 &startTime={start_ms}&endTime={end_ms}&limit=100"
            ),
        )?;
        let mut out = Vec::new();
        for p in r
            .get("list")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
        {
            let f = |k: &str| {
                p.get(k)
                    .and_then(Value::as_str)
                    .and_then(|s| s.parse::<f64>().ok())
            };
            let ts = p
                .get("createdTime")
                .and_then(Value::as_str)
                .and_then(|s| s.parse::<i64>().ok())
                .unwrap_or(0);
            // Запись без числа — пропуск, а не ноль: ноль был бы
            // утверждением «денег не было».
            if let Some(pnl) = f("closedPnl") {
                out.push((ts, pnl));
            }
        }
        Ok(out)
    }

    /// Лучшие цены: (bid, ask).
    pub fn best_prices(&self, symbol: &str) -> Result<(f64, f64), String> {
        // Публичный маршрут, но подписанный GET не мешает.
        let r = self.get(
            "/v5/market/tickers",
            &format!("category=linear&symbol={symbol}"),
        )?;
        let list = r
            .get("list")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let t = list.first().ok_or("tickers: пусто")?;
        let f = |k: &str| {
            t.get(k)
                .and_then(Value::as_str)
                .and_then(|s| s.parse::<f64>().ok())
                .unwrap_or(0.0)
        };
        Ok((f("bid1Price"), f("ask1Price")))
    }

    // --- заявки ------------------------------------------------------

    /// Лимитная заявка. `tif` — "IOC" или "PostOnly"; количество и
    /// цена приходят СТРОКАМИ: шаг цены и объёма у каждого символа
    /// свой, и округлять обязан вызывающий по справочнику — площадка
    /// отвергает неровное число, и это правильный отказ, а не помеха.
    pub fn place_limit(
        &self,
        symbol: &str,
        side: &str,
        qty: &str,
        price: &str,
        tif: &str,
        link_id: &str,
        reduce_only: bool,
    ) -> Result<String, String> {
        let body = serde_json::json!({
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Limit",
            "qty": qty,
            "price": price,
            "timeInForce": tif,
            "orderLinkId": link_id,
            "reduceOnly": reduce_only,
        });
        let r = self.post("/v5/order/create", &body)?;
        r.get("orderId")
            .and_then(Value::as_str)
            .map(String::from)
            .ok_or_else(|| "order/create: нет orderId".into())
    }

    /// Плечо 1× — спека 12 §2. «Не изменилось» (110043) — не отказ.
    pub fn set_leverage(&self, symbol: &str, lev: &str) -> Result<(), String> {
        let body = serde_json::json!({
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": lev,
            "sellLeverage": lev,
        });
        match self.post("/v5/position/set-leverage", &body) {
            Ok(_) => Ok(()),
            Err(e) if e.contains("110043") => Ok(()),
            Err(e) => Err(e),
        }
    }

    pub fn cancel(&self, symbol: &str, order_id: &str) -> Result<(), String> {
        let body = serde_json::json!({
            "category": "linear",
            "symbol": symbol,
            "orderId": order_id,
        });
        self.post("/v5/order/cancel", &body).map(|_| ())
    }

    /// Статус заявки: (status, cumExecQty, avgPrice, cumExecFee).
    ///
    /// Сначала `realtime` (открытые и свежезакрытые), затем `history`:
    /// IOC живёт мгновение, и у нерасторопного опроса она уже в
    /// истории. Не нашлась нигде — отказ словами, а не выдуманный
    /// статус: заявка, о которой площадка молчит, не «не исполнилась».
    pub fn order_status(
        &self,
        symbol: &str,
        order_id: &str,
    ) -> Result<(String, f64, f64, f64), String> {
        for path in ["/v5/order/realtime", "/v5/order/history"] {
            let r = self.get(
                path,
                &format!("category=linear&symbol={symbol}&orderId={order_id}"),
            )?;
            let list = r
                .get("list")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if let Some(o) = list.first() {
                let f = |k: &str| {
                    o.get(k)
                        .and_then(Value::as_str)
                        .and_then(|s| s.parse::<f64>().ok())
                        .unwrap_or(0.0)
                };
                let status = o
                    .get("orderStatus")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                return Ok((status, f("cumExecQty"), f("avgPrice"), f("cumExecFee")));
            }
        }
        Err(format!("order_status: заявка {order_id} не найдена ни в realtime, ни в history"))
    }

    /// Живой справочник инструмента: (tick_size, qty_step,
    /// min_order_qty, min_notional_value). Снимок A1 на диске годится
    /// исследованиям; живая заявка округляется по живому справочнику —
    /// шаги цены площадка меняет, и устаревший файл дал бы отказ
    /// «invalid price» на каждой заявке.
    pub fn instrument(&self, symbol: &str) -> Result<(f64, f64, f64, f64), String> {
        let r = self.get(
            "/v5/market/instruments-info",
            &format!("category=linear&symbol={symbol}"),
        )?;
        let list = r
            .get("list")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let i = list
            .first()
            .ok_or_else(|| format!("instruments-info: {symbol} не найден"))?;
        let s = |v: Option<&Value>| {
            v.and_then(Value::as_str)
                .and_then(|s| s.parse::<f64>().ok())
                .unwrap_or(0.0)
        };
        let pf = i.get("priceFilter");
        let lf = i.get("lotSizeFilter");
        let tick = s(pf.and_then(|x| x.get("tickSize")));
        let step = s(lf.and_then(|x| x.get("qtyStep")));
        let min_qty = s(lf.and_then(|x| x.get("minOrderQty")));
        let min_notional = s(lf.and_then(|x| x.get("minNotionalValue")));
        if tick <= 0.0 || step <= 0.0 {
            return Err(format!(
                "instruments-info: {symbol} без шага цены или объёма (tick {tick}, step {step})"
            ));
        }
        Ok((tick, step, min_qty, min_notional))
    }

    /// Исполнения по символу за последние `hours` часов:
    /// (orderLinkId, side, qty, price, fee).
    pub fn executions(
        &self,
        symbol: &str,
        hours: i64,
    ) -> Result<Vec<(String, String, f64, f64, f64)>, String> {
        let start = self.now_ms() - hours * 3_600_000;
        let r = self.get(
            "/v5/execution/list",
            &format!("category=linear&symbol={symbol}&startTime={start}&limit=100"),
        )?;
        let mut out = Vec::new();
        for e in r
            .get("list")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
        {
            let f = |k: &str| {
                e.get(k)
                    .and_then(Value::as_str)
                    .and_then(|s| s.parse::<f64>().ok())
                    .unwrap_or(0.0)
            };
            out.push((
                e.get("orderLinkId").and_then(Value::as_str).unwrap_or("").into(),
                e.get("side").and_then(Value::as_str).unwrap_or("").into(),
                f("execQty"),
                f("execPrice"),
                f("execFee"),
            ));
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!("venue-{name}-{}", std::process::id()));
        let _ = std::fs::remove_file(&p);
        p
    }

    /// Вектор подписи закреплён ЧИСЛОМ, посчитанным независимой
    /// реализацией (python hmac по тем же байтам): свойство «подпись
    /// стабильна» прошло бы и на неверной формуле.
    #[test]
    fn подпись_совпадает_с_независимой_реализацией() {
        let k = Keys {
            key: "testkey".into(),
            secret: "testsecret".into(),
        };
        let got = k.sign(1_700_000_000_000, 5_000, "category=linear");
        assert_eq!(
            got,
            "bb83e8488b138c2b23221db49ca6198f560509321d4b611ae6a530efe7070a7d"
        );
    }

    #[test]
    fn ключ_читается_как_вставил_владелец() {
        // CRLF, пробелы вокруг `=`, комментарий и пустая строка —
        // всё это законные следы ручной вставки.
        let p = tmp("crlf");
        std::fs::write(&p, "# ключ\r\n BBYBIT=x\r\nBYBIT_KEY = abc \r\n\r\nBYBIT_SECRET= def\r\n").unwrap();
        let k = Keys::load(&p).unwrap();
        assert_eq!(k.key, "abc");
        assert_eq!(k.secret, "def");
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn ключ_без_секрета_это_отказ_словами() {
        let p = tmp("nosecret");
        std::fs::write(&p, "BYBIT_KEY=abc\n").unwrap();
        let e = Keys::load(&p).unwrap_err();
        assert!(e.contains("BYBIT_SECRET"), "{e}");
        let _ = std::fs::remove_file(&p);
    }

    /// Секрет не попадает в отладочный вывод — единственное место,
    /// откуда он мог бы утечь в журнал или в текст ошибки.
    #[test]
    fn секрет_не_печатается() {
        let k = Keys {
            key: "PUBLICPART".into(),
            secret: "VERYSECRET".into(),
        };
        let dbg = format!("{k:?}");
        assert!(!dbg.contains("VERYSECRET"), "{dbg}");
        assert!(dbg.contains("PUBL"), "{dbg}");
    }

    #[test]
    fn отказ_площадки_несёт_код_и_текст() {
        let v: Value = serde_json::json!({
            "retCode": 10004, "retMsg": "error sign",
        });
        let e = unwrap_ret(v, "order/create").unwrap_err();
        assert!(e.contains("10004") && e.contains("error sign"), "{e}");
        let ok: Value = serde_json::json!({
            "retCode": 0, "result": {"orderId": "42"},
        });
        let r = unwrap_ret(ok, "x").unwrap();
        assert_eq!(r.get("orderId").and_then(Value::as_str), Some("42"));
    }
}
