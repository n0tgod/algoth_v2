import Charts
import SwiftUI

/// График позиции — родной вместо страницы `/chart`.
///
/// Те же данные, что у страницы: минутные свечи записи (`/candles`, окно
/// под саму позицию) и позиция книги (`/dca_trades`): рунги, ступени ТВХ,
/// цель и цена ликвидации, посчитанные сервером тем же ядром, что книга
/// (`rules.avg_walk`, `rules.liq_walk`). Своего счёта у графика нет; свечи
/// только укрупняются для показа — открытие первой минуты, закрытие
/// последней, максимум и минимум группы.
struct PositionChart: View {
    let p: Pos
    let book: String?
    @StateObject private var cm = ChartModel()
    @State private var sel: Date?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Cap(text: "график позиции")
                Spacer()
                if let s = readout {
                    Text(s).font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(Theme.muted)
                }
            }
            if let e = cm.error {
                Note(text: e, tone: .bad)
            } else if cm.loading {
                HStack { Spacer(); ProgressView().tint(.white); Spacer() }
                    .frame(height: 300)
            } else if cm.candles.isEmpty {
                Note(text: "Свечей записи за окно позиции нет — это пропуск записи, "
                     + "а не «цена стояла».")
            } else {
                chart
                legend
                ForEach(cm.notes, id: \.self) { Note(text: $0) }
            }
        }
        .padding(12)
        .background(Theme.chip)
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .task { await cm.load(p: p, book: book) }
    }

    private var chart: some View {
        let bars = cm.candles
        let dom = cm.yDomain
        return GeometryReader { geo in
            let w = max(1, geo.size.width / CGFloat(max(bars.count, 1)) * 0.7)
            Chart {
                ForEach(bars) { c in
                    RuleMark(x: .value("время", c.t),
                             yStart: .value("мин", c.l), yEnd: .value("макс", c.h))
                        .foregroundStyle(c.up ? Theme.bid.opacity(0.7) : Theme.ask.opacity(0.7))
                        .lineStyle(StrokeStyle(lineWidth: 1))
                    RectangleMark(x: .value("время", c.t),
                                  yStart: .value("откр", min(c.o, c.c)),
                                  yEnd: .value("закр", max(c.o, c.c) + cm.minBody),
                                  width: .fixed(w))
                        .foregroundStyle(c.up ? Theme.bid : Theme.ask)
                }
                ForEach(cm.lines) { s in
                    ForEach(s.pts) { pt in
                        LineMark(x: .value("время", pt.t), y: .value("цена", pt.v),
                                 series: .value("ряд", s.name))
                            .foregroundStyle(s.color)
                            .lineStyle(StrokeStyle(lineWidth: s.width, dash: s.dash))
                    }
                }
                ForEach(cm.legs) { f in
                    PointMark(x: .value("время", f.t), y: .value("цена", f.v))
                        .symbol(.triangle)
                        .symbolSize(70)
                        .foregroundStyle(Theme.accent)
                }
                if let x = cm.exitPt {
                    PointMark(x: .value("время", x.t), y: .value("цена", x.v))
                        .symbol(.square)
                        .symbolSize(70)
                        .foregroundStyle(cm.exitTone.color)
                }
                if let s = sel {
                    RuleMark(x: .value("время", s))
                        .foregroundStyle(Color.white.opacity(0.35))
                }
            }
            .chartYScale(domain: dom)
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 5)) { _ in
                    AxisGridLine().foregroundStyle(Theme.rule)
                    AxisValueLabel(format: .dateTime.day().hour().minute())
                        .foregroundStyle(Theme.dim)
                }
            }
            .chartYAxis {
                AxisMarks(position: .trailing) { _ in
                    AxisGridLine().foregroundStyle(Theme.rule)
                    AxisValueLabel().foregroundStyle(Theme.dim)
                }
            }
            .chartOverlay { proxy in
                GeometryReader { g in
                    Rectangle().fill(Color.clear).contentShape(Rectangle())
                        .gesture(DragGesture(minimumDistance: 0)
                            .onChanged { v in
                                let x = v.location.x - g[proxy.plotAreaFrame].origin.x
                                if let d: Date = proxy.value(atX: x) { sel = d }
                            }
                            .onEnded { _ in sel = nil })
                }
            }
        }
        .frame(height: 320)
        .environment(\.timeZone, TimeZone(identifier: "UTC")!)
    }

    /// Под пальцем: свеча и ТВХ на это время.
    private var readout: String? {
        guard let s = sel, let c = cm.candle(near: s) else { return nil }
        var t = F.hhmm(c.t.timeIntervalSince1970) + "  O " + F.px(c.o)
            + " H " + F.px(c.h) + " L " + F.px(c.l) + " C " + F.px(c.c)
        if let a = cm.value(of: "ТВХ", at: s) { t += "  ТВХ " + F.px(a) }
        return t
    }

    private var legend: some View {
        HStack(spacing: 12) {
            ForEach(cm.lines) { s in
                HStack(spacing: 4) {
                    Rectangle().fill(s.color).frame(width: 14, height: 2)
                    Text(s.name)
                }
            }
            HStack(spacing: 4) {
                Image(systemName: "triangle.fill").foregroundStyle(Theme.accent)
                Text("рунги")
            }
            if cm.exitPt != nil {
                HStack(spacing: 4) {
                    Image(systemName: "square.fill").foregroundStyle(cm.exitTone.color)
                    Text("выход")
                }
            }
        }
        .font(.system(size: 11))
        .foregroundStyle(Theme.muted)
    }
}

/// Данные графика. Свечи и позиция — с сервера; здесь только окно,
/// укрупнение свечей для показа и разбор ступеней в точки линий.
@MainActor
final class ChartModel: ObservableObject {
    struct Bar: Identifiable {
        let id: Int
        let t: Date
        let o: Double, h: Double, l: Double, c: Double
        var up: Bool { c >= o }
    }
    struct Pt: Identifiable {
        let id: Int
        let t: Date
        let v: Double
    }
    struct Line: Identifiable {
        var id: String { name }
        let name: String
        let color: Color
        var width: CGFloat = 2
        var dash: [CGFloat] = []
        let pts: [Pt]
    }

    @Published private(set) var candles: [Bar] = []
    @Published private(set) var lines: [Line] = []
    @Published private(set) var legs: [Pt] = []
    @Published private(set) var exitPt: Pt?
    @Published private(set) var exitTone: Tone = .plain
    @Published private(set) var notes: [String] = []
    @Published private(set) var error: String?
    @Published private(set) var loading = true
    @Published private(set) var yDomain: ClosedRange<Double> = 0...1
    private(set) var minBody = 0.0

    /// Сколько свечей показывать: глаз больше не различит, а тысячи
    /// минутных баров тормозят прокрутку на телефоне.
    static let maxBars = 240
    static let pad: Double = 1800              // запас окна, как у страницы
    static let maxHours = 96                   // потолок сервера (`CANDLE_MAX_H`)

    func load(p: Pos, book: String?) async {
        let r = p.r
        guard let sym = r["sym"].string, let at = r["at"].double else {
            error = "У позиции нет имени или времени входа."; loading = false; return
        }
        let exitTs = p.live ? nil : r["exit_ts"].double
        let end = (exitTs ?? Date().timeIntervalSince1970) + Self.pad
        let wantH = Int(((end - (at - Self.pad)) / 3600).rounded(.up))
        let hours = max(1, wantH)

        // Позиция — из ответа графику (там цель и ликвидация); нет её
        // там — из свода книги, без цели и ликвидации, и это сказано.
        var walk = r["walk"].array
        var trade: J?
        if let book {
            if let d = try? await fetchJSON("/dca_trades", ["sym": sym, "book": book]) {
                trade = d["rows"].array.first {
                    abs(($0["opened_at"].double ?? -1) - at) < 1
                }
            }
        }
        if let t = trade, !t["walk"].array.isEmpty { walk = t["walk"].array }
        var nts: [String] = []
        if trade == nil {
            nts.append("Позиция не нашлась в ответе графику — ступени ТВХ взяты из "
                       + "свода книги, цели и ликвидации на графике нет.")
        }

        let c: J
        do {
            var q: [String: String?] = ["sym": sym, "hours": String(hours)]
            if let exitTs { q["end"] = String(Int(exitTs + Self.pad)) }
            c = try await fetchJSON("/candles", q)
        } catch let e as FetchError {
            error = e.words; loading = false; return
        } catch {
            self.error = error.localizedDescription; loading = false; return
        }
        // Сервер отдаёт свечи ДРУГОГО имени, если этого не знает: свечи
        // чужой монеты под этой позицией были бы подменой.
        if c["sym"].string?.uppercased() != sym.uppercased() {
            error = "Записи по \(sym) у сборщика нет — свечи не показываю, "
                + "чтобы не нарисовать чужую монету."
            loading = false; return
        }
        if c["capped"].truthy {
            nts.append("Окно позиции \(wantH) ч длиннее потолка записи "
                       + "\(c["max_hours"].text) ч — левый край обрезан.")
        }
        let raw = c["candles"].array.compactMap { row -> [Double]? in
            let v = row.array.compactMap(\.double)
            return v.count >= 5 ? v : nil
        }.filter { $0[0] >= at - Self.pad && $0[0] <= end }
        candles = Self.group(raw)

        let lastT = exitTs ?? (raw.last?[0] ?? Date().timeIntervalSince1970)
        buildLines(walk: walk, until: lastT)
        legs = walk.enumerated().compactMap { i, f in
            guard let t = f["at"].double, let v = f["px"].double else { return nil }
            return Pt(id: i, t: Date(timeIntervalSince1970: t), v: v)
        }
        if let exitTs, let px = r["exit_px"].double {
            exitPt = Pt(id: 0, t: Date(timeIntervalSince1970: exitTs), v: px)
            exitTone = Tone(r["usd"].double)
        }
        yDomain = domain(&nts)
        notes = nts
        loading = false
    }

    /// Минутные свечи → не больше `maxBars` баров.
    private static func group(_ raw: [[Double]]) -> [Bar] {
        guard !raw.isEmpty else { return [] }
        let k = max(1, Int((Double(raw.count) / Double(maxBars)).rounded(.up)))
        var out: [Bar] = []
        var i = 0
        while i < raw.count {
            let g = raw[i..<min(i + k, raw.count)]
            out.append(Bar(id: out.count,
                           t: Date(timeIntervalSince1970: g.first![0]),
                           o: g.first![1], h: g.map { $0[2] }.max()!,
                           l: g.map { $0[3] }.min()!, c: g.last![4]))
            i += k
        }
        return out
    }

    /// Ступени: значение рунга держится до следующего рунга или конца.
    private func buildLines(walk: [J], until: Double) {
        func steps(_ key: String) -> [Pt] {
            var pts: [Pt] = []
            for (i, f) in walk.enumerated() {
                guard let t0 = f["at"].double, let v = f[key].double else { continue }
                let t1 = (i + 1 < walk.count ? walk[i + 1]["at"].double : nil) ?? until
                pts.append(Pt(id: pts.count, t: Date(timeIntervalSince1970: t0), v: v))
                pts.append(Pt(id: pts.count, t: Date(timeIntervalSince1970: max(t0, t1)),
                              v: v))
            }
            return pts
        }
        var ls: [Line] = []
        let avg = steps("avg")
        if !avg.isEmpty { ls.append(Line(name: "ТВХ", color: Theme.accent, pts: avg)) }
        let take = steps("take")
        if !take.isEmpty {
            ls.append(Line(name: "цель", color: Theme.bid, width: 1.5, dash: [5, 4],
                           pts: take))
        }
        let liq = steps("liq")
        if !liq.isEmpty {
            ls.append(Line(name: "ликвидация", color: Theme.ask, width: 1.5,
                           dash: [2, 3], pts: liq))
        }
        lines = ls
    }

    /// Ось цены — по свечам и линиям позиции. Ликвидация, лежащая далеко
    /// от свечей, сжала бы их в нитку: её уровень тогда называется
    /// словами, а не рисуется за краем молча.
    private func domain(_ nts: inout [String]) -> ClosedRange<Double> {
        var lo = candles.map(\.l).min() ?? 0
        var hi = candles.map(\.h).max() ?? 1
        for l in lines where l.name != "ликвидация" {
            for p in l.pts { lo = min(lo, p.v); hi = max(hi, p.v) }
        }
        for p in legs { lo = min(lo, p.v); hi = max(hi, p.v) }
        let span = max(hi - lo, abs(hi) * 1e-4)
        if let liq = lines.first(where: { $0.name == "ликвидация" }) {
            let vals = liq.pts.map(\.v)
            if let near = vals.min(by: { abs($0 - lo) < abs($1 - lo) }) {
                if near >= lo - span && near <= hi + span {
                    lo = min(lo, vals.min()!); hi = max(hi, vals.max()!)
                } else {
                    lines.removeAll { $0.name == "ликвидация" }
                    nts.append("Ликвидация \(F.px(near)) — далеко за окном цены, "
                               + "на графике не помещается.")
                }
            }
        }
        let s2 = max(hi - lo, abs(hi) * 1e-4)
        minBody = s2 * 0.002
        return (lo - s2 * 0.04)...(hi + s2 * 0.04)
    }

    func candle(near d: Date) -> Bar? {
        candles.min { abs($0.t.timeIntervalSince(d)) < abs($1.t.timeIntervalSince(d)) }
    }

    func value(of name: String, at d: Date) -> Double? {
        guard let l = lines.first(where: { $0.name == name }) else { return nil }
        var v: Double?
        for p in l.pts where p.t <= d { v = p.v }
        return v
    }
}
