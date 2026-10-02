import Foundation
import SwiftUI

/// Данные графика позиции и окно просмотра.
///
/// Свечи — минутные свечи записи (`/candles`), позиция — ответ графику
/// (`/dca_trades`): рунги, ступени ТВХ, цель и ликвидация посчитаны
/// сервером тем же ядром, что книга. Здесь только укрупнение свечей до
/// выбранного таймфрейма (открытие первой минуты, закрытие последней,
/// максимум, минимум и сумма объёма) и окно: какие бары видны и какая
/// шкала цены.
@MainActor
final class TradeChartModel: ObservableObject {
    struct Bar {
        let t: Double
        let o: Double, h: Double, l: Double, c: Double, v: Double
        var up: Bool { c >= o }
    }

    /// Ступень лестницы: значение держится от `t0` до `t1`.
    struct Step {
        let t0: Double, t1: Double, v: Double
    }

    struct Dot {
        let t: Double, px: Double
    }

    static let frames: [(Int, String)] = [(1, "1м"), (5, "5м"), (15, "15м"),
                                          (60, "1ч")]
    static let maxHours = 96.0                  // потолок сервера (`CANDLE_MAX_H`)

    @Published private(set) var raw: [[Double]] = []
    @Published private(set) var bars: [Bar] = []
    @Published private(set) var tf = 5
    @Published private(set) var loading = true
    @Published private(set) var error: String?
    @Published private(set) var notes: [String] = []

    // Позиция
    @Published private(set) var avg: [Step] = []
    @Published private(set) var take: [Step] = []
    @Published private(set) var liq: [Step] = []
    @Published private(set) var entry: Dot?
    @Published private(set) var adds: [Dot] = []
    @Published private(set) var exit: Dot?
    @Published private(set) var exitTone: Tone = .plain
    @Published private(set) var long = true
    @Published private(set) var live = false
    private(set) var tradeStart = 0.0
    private(set) var tradeEnd: Double?
    private(set) var sym = ""

    // Окно просмотра: левый край в барах (дробный) и число видимых баров.
    @Published var start = 0.0
    @Published var count = 100.0
    /// Шкала цены руками (растяжение оси); `nil` — автоподбор по видимому.
    @Published var manual: ClosedRange<Double>?

    private var loadedFor: String?

    func load(p: Pos, book: String?) async {
        let key = p.id
        if loadedFor == key, !raw.isEmpty { return }
        loadedFor = key
        let r = p.r
        guard let s = r["sym"].string, let at = r["at"].double else {
            error = "У позиции нет имени или времени входа."; loading = false; return
        }
        sym = s
        live = p.live
        long = r["side"].string != "short"
        tradeStart = at
        tradeEnd = p.live ? nil : r["exit_ts"].double

        var walk = r["walk"].array
        var addRows: [J] = []
        var trade: J?
        if let book,
           let d = try? await fetchJSON("/dca_trades", ["sym": s, "book": book]) {
            trade = d["rows"].array.first { abs(($0["opened_at"].double ?? -1) - at) < 1 }
        }
        var nts: [String] = []
        if let t = trade {
            if !t["walk"].array.isEmpty { walk = t["walk"].array }
            addRows = t["adds"].array
        } else {
            nts.append("Позиция не нашлась в ответе графику — ступени ТВХ из свода "
                       + "книги, цели и ликвидации на графике нет.")
            addRows = Array(walk.dropFirst())
        }
        buildTrade(r: r, walk: walk, adds: addRows)
        notes = nts
        await fetchCandles(first: true)
        loading = false
    }

    /// Окно записи: позиция и контекст по бокам, не длиннее потолка.
    private func window() -> (hours: Int, end: Double?) {
        let now = Date().timeIntervalSince1970
        let end = tradeEnd ?? now
        let span = max(end - tradeStart, 3600)
        let left = tradeStart - max(2 * 3600, span * 0.6)
        let right = tradeEnd.map { min(now, $0 + max(2 * 3600, span * 0.3)) }
        let hrs = min(Self.maxHours, ((right ?? now) - left) / 3600)
        return (Int(hrs.rounded(.up)), right)
    }

    func fetchCandles(first: Bool = false) async {
        let w = window()
        var q: [String: String?] = ["sym": sym, "hours": String(max(1, w.hours))]
        if let e = w.end { q["end"] = String(Int(e)) }
        do {
            let c = try await fetchJSON("/candles", q)
            // Не знает имени — сервер отдаёт ДРУГОЕ: чужие свечи под этой
            // позицией были бы подменой.
            guard c["sym"].string?.uppercased() == sym.uppercased() else {
                error = "Записи по \(sym) у сборщика нет — чужие свечи не рисую."
                return
            }
            let rows = c["candles"].array.compactMap { row -> [Double]? in
                let v = row.array.compactMap(\.double)
                return v.count >= 6 ? v : (v.count == 5 ? v + [0] : nil)
            }
            raw = rows
            if c["capped"].truthy, !notes.contains(where: { $0.hasPrefix("Окно") }) {
                notes.append("Окно позиции длиннее потолка записи "
                             + "\(c["max_hours"].text) ч — левый край обрезан.")
            }
            if first { tf = Self.autoFrame(span: (tradeEnd ?? Date().timeIntervalSince1970)
                                           - tradeStart) }
            regroup(keepView: !first)
            if first { fitTrade() }
        } catch let e as FetchError {
            if raw.isEmpty { error = e.words }
        } catch {
            if raw.isEmpty { self.error = error.localizedDescription }
        }
    }

    /// Открытая позиция живёт: свечи подтягиваются, пока график открыт.
    func follow() async {
        guard live else { return }
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 30_000_000_000)
            await fetchCandles()
        }
    }

    /// Таймфрейм, при котором позиция занимает ~120 баров.
    static func autoFrame(span: Double) -> Int {
        let m = span / 60 / 120
        return frames.map(\.0).min { abs(Double($0) - m) < abs(Double($1) - m) } ?? 5
    }

    func setFrame(_ m: Int) {
        guard m != tf else { return }
        // Окно держится по времени: тот же отрезок в новых барах.
        let t0 = time(at: start), t1 = time(at: start + count)
        tf = m
        regroup(keepView: false)
        start = index(of: t0)
        count = max(10, index(of: t1) - start)
        clampView()
    }

    private func regroup(keepView: Bool) {
        let step = Double(tf * 60)
        var out: [Bar] = []
        var cur: [Double]?
        var bucket = -1.0
        for r in raw {
            let b = (r[0] / step).rounded(.down) * step
            if b != bucket {
                if let c = cur {
                    out.append(Bar(t: c[0], o: c[1], h: c[2], l: c[3], c: c[4], v: c[5]))
                }
                bucket = b
                cur = [b, r[1], r[2], r[3], r[4], r[5]]
            } else if var c = cur {
                c[2] = max(c[2], r[2]); c[3] = min(c[3], r[3]); c[4] = r[4]; c[5] += r[5]
                cur = c
            }
        }
        if let c = cur { out.append(Bar(t: c[0], o: c[1], h: c[2], l: c[3], c: c[4], v: c[5])) }
        let wasAtEnd = start + count >= Double(bars.count) - 0.5
        let oldN = bars.count
        bars = out
        if keepView, wasAtEnd, oldN > 0 { start += Double(out.count - oldN) }
        clampView()
    }

    private func buildTrade(r: J, walk: [J], adds addRows: [J]) {
        let end = tradeEnd
        func steps(_ key: String, positive: Bool = false) -> [Step] {
            var out: [Step] = []
            for (i, f) in walk.enumerated() {
                guard let t0 = f["at"].double, let v = f[key].double else { continue }
                if positive && v <= 0 { continue }
                let t1 = (i + 1 < walk.count ? walk[i + 1]["at"].double : nil) ?? end
                out.append(Step(t0: t0, t1: t1 ?? .infinity, v: v))
            }
            return out
        }
        avg = steps("avg")
        take = steps("take")
        liq = steps("liq", positive: true)
        if let px = r["entry_px"].double ?? walk.first?["px"].double {
            entry = Dot(t: tradeStart, px: px)
        }
        adds = addRows.compactMap { a in
            guard let t = a["at"].double, let px = a["px"].double else { return nil }
            return Dot(t: t, px: px)
        }
        if let t = tradeEnd, let px = r["exit_px"].double {
            exit = Dot(t: t, px: px)
            exitTone = Tone(r["usd"].double)
        }
    }

    // MARK: окно

    func fitTrade() {
        guard !bars.isEmpty else { return }
        let a = index(of: tradeStart)
        let b = tradeEnd.map { index(of: $0) } ?? Double(bars.count)
        let span = max(b - a, 20)
        start = a - span * 0.25
        count = span * 1.55
        manual = nil
        clampView()
    }

    func clampView() {
        let n = Double(max(bars.count, 1))
        count = min(max(count, 12), max(n * 1.5, 12))
        start = min(max(start, -count * 0.8), n - count * 0.2)
    }

    /// Время → дробный номер бара (бары с пропусками: поиск по времени).
    func index(of t: Double) -> Double {
        guard !bars.isEmpty else { return 0 }
        let step = Double(tf * 60)
        if t <= bars[0].t { return (t - bars[0].t) / step }
        if t >= bars[bars.count - 1].t {
            return Double(bars.count - 1) + (t - bars[bars.count - 1].t) / step
        }
        var lo = 0, hi = bars.count - 1
        while hi - lo > 1 {
            let mid = (lo + hi) / 2
            if bars[mid].t <= t { lo = mid } else { hi = mid }
        }
        let frac = min(1, (t - bars[lo].t) / max(bars[hi].t - bars[lo].t, 1))
        return Double(lo) + frac
    }

    func time(at i: Double) -> Double {
        guard !bars.isEmpty else { return 0 }
        let step = Double(tf * 60)
        let k = Int(i.rounded(.down))
        if k < 0 { return bars[0].t + i * step }
        if k >= bars.count - 1 { return bars[bars.count - 1].t + (i - Double(bars.count - 1)) * step }
        return bars[k].t + (i - Double(k)) * (bars[k + 1].t - bars[k].t)
    }

    /// Шкала цены по видимому: свечи, ступени ТВХ и выход. Цель и
    /// ликвидацию в шкалу не втягиваем — ради них свечи сжались бы в
    /// нитку (правило страницы); за краем они подписаны у края.
    func autoRange() -> ClosedRange<Double> {
        if let m = manual { return m }
        let i0 = max(0, Int(start.rounded(.down)))
        let i1 = min(bars.count, Int((start + count).rounded(.up)))
        var lo = Double.infinity, hi = -Double.infinity
        if i0 < i1 {
            for b in bars[i0..<i1] { lo = min(lo, b.l); hi = max(hi, b.h) }
        }
        let t0 = time(at: start), t1 = time(at: start + count)
        for s in avg where s.t0 <= t1 && s.t1 >= t0 { lo = min(lo, s.v); hi = max(hi, s.v) }
        if let e = exit, e.t >= t0, e.t <= t1 { lo = min(lo, e.px); hi = max(hi, e.px) }
        if !lo.isFinite || !hi.isFinite {
            lo = bars.map(\.l).min() ?? 0; hi = bars.map(\.h).max() ?? 1
        }
        let span = max(hi - lo, abs(hi) * 1e-4)
        // Снизу — место под объём (как у страницы: полоса 16 %).
        return (lo - span * 0.24)...(hi + span * 0.07)
    }

    var dec: Int {
        let p = bars.last?.c ?? entry?.px ?? 1
        guard p > 0 else { return 2 }
        let mag = Int(log10(p).rounded(.down))
        return max(2, min(8, 4 - mag))
    }
}
