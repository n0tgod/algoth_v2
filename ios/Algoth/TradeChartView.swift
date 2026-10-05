import SwiftUI
import UIKit

/// График позиции в манере TradingView: свечи, объём, шкалы, перекрестие.
/// Позиция рисуется по правилам страницы `/chart` (`web.py`): зоны
/// прибыли и убытка от ступеней ТВХ, ступени ТВХ, цели и ликвидации,
/// кружок входа, точки доливов, выход с вертикалью от последней ТВХ.
///
/// Жесты: палец — сдвиг; щипок — масштаб по времени; долгое нажатие —
/// перекрестие (ведётся пальцем, снимается касанием); двойное касание —
/// вернуться к сделке; тянуть шкалу цены вверх-вниз — растянуть цену,
/// касание шкалы — снова автоподбор.
struct TradeChartCanvas: View {
    @ObservedObject var cm: TradeChartModel
    var interactive: Bool

    @State private var cross: CGPoint?
    @State private var mode = Mode.idle
    @State private var startView = (0.0, 0.0)
    @State private var startRange: ClosedRange<Double>?
    @State private var press: Task<Void, Never>?
    @State private var lastTap = Date.distantPast
    @State private var pinchBase: Double?

    enum Mode { case idle, pending, pan, cross, axis }

    static let axisW: CGFloat = 66
    static let timeH: CGFloat = 22

    var body: some View {
        GeometryReader { geo in
            let plot = CGRect(x: 0, y: 0,
                              width: max(10, geo.size.width - Self.axisW),
                              height: max(10, geo.size.height - Self.timeH))
            Canvas { ctx, size in
                draw(ctx, size: size, plot: plot)
            }
            .contentShape(Rectangle())
            .gesture(drag(plot), including: interactive ? .all : .none)
            .simultaneousGesture(magnify, including: interactive ? .all : .none)
        }
    }

    // MARK: жесты

    private func drag(_ plot: CGRect) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { v in
                if pinchBase != nil { return }
                if mode == .idle {
                    startView = (cm.start, cm.count)
                    if v.startLocation.x > plot.maxX {
                        mode = .axis
                        startRange = cm.autoRange()
                    } else {
                        mode = .pending
                        let at = v.startLocation
                        press?.cancel()
                        press = Task { @MainActor in
                            try? await Task.sleep(nanoseconds: 320_000_000)
                            if !Task.isCancelled, mode == .pending {
                                mode = .cross
                                cross = at
                                UIImpactFeedbackGenerator(style: .light).impactOccurred()
                            }
                        }
                    }
                }
                let moved = hypot(v.translation.width, v.translation.height)
                switch mode {
                case .pending:
                    if moved > 8 {
                        press?.cancel()
                        mode = .pan
                        cross = nil
                        pan(v.translation.width, plot)
                    }
                case .pan:
                    pan(v.translation.width, plot)
                case .cross:
                    cross = v.location
                case .axis:
                    if let r = startRange {
                        let k = exp(Double(v.translation.height) / 220)
                        let mid = (r.lowerBound + r.upperBound) / 2
                        let half = (r.upperBound - r.lowerBound) / 2 * k
                        cm.manual = (mid - half)...(mid + half)
                    }
                case .idle:
                    break
                }
            }
            .onEnded { v in
                press?.cancel()
                let moved = hypot(v.translation.width, v.translation.height)
                if mode == .pending {
                    // Короткое касание: второе подряд — к сделке; одно —
                    // снять перекрестие.
                    if Date().timeIntervalSince(lastTap) < 0.32 {
                        withAnimation(.easeOut(duration: 0.2)) { cm.fitTrade() }
                        lastTap = .distantPast
                    } else {
                        lastTap = Date()
                    }
                    cross = nil
                } else if mode == .axis, moved < 6 {
                    cm.manual = nil
                }
                mode = .idle
            }
    }

    private func pan(_ dx: CGFloat, _ plot: CGRect) {
        let bw = Double(plot.width) / startView.1
        cm.start = startView.0 - Double(dx) / bw
        cm.clampView()
    }

    private var magnify: some Gesture {
        MagnificationGesture()
            .onChanged { s in
                if pinchBase == nil {
                    pinchBase = cm.count
                    press?.cancel()
                    mode = .idle
                    cross = nil
                }
                guard let base = pinchBase, s > 0 else { return }
                let center = cm.start + cm.count / 2
                cm.count = base / Double(s)
                cm.clampView()
                cm.start = center - cm.count / 2
                cm.clampView()
            }
            .onEnded { _ in pinchBase = nil }
    }

    // MARK: рисование

    private func draw(_ ctx: GraphicsContext, size: CGSize, plot: CGRect) {
        let bars = cm.bars
        guard !bars.isEmpty else { return }
        let range = cm.autoRange()
        let lo = range.lowerBound, hi = range.upperBound
        let bw = Double(plot.width) / cm.count
        let dec = cm.dec
        func x(_ i: Double) -> CGFloat { plot.minX + CGFloat((i - cm.start + 0.5) * bw) }
        func xt(_ t: Double) -> CGFloat { x(cm.index(of: t) - 0.5) }
        func y(_ p: Double) -> CGFloat {
            plot.minY + CGFloat((hi - p) / (hi - lo)) * plot.height
        }
        func price(_ yy: CGFloat) -> Double {
            hi - Double((yy - plot.minY) / plot.height) * (hi - lo)
        }
        let i0 = max(0, Int(cm.start.rounded(.down)) - 1)
        let i1 = min(bars.count, Int((cm.start + cm.count).rounded(.up)) + 1)

        // Сетка и шкала цены
        let ticks = Self.niceTicks(lo: lo, hi: hi, count: max(3, Int(plot.height / 60)))
        var grid = Path()
        for p in ticks {
            grid.move(to: CGPoint(x: plot.minX, y: y(p)))
            grid.addLine(to: CGPoint(x: plot.maxX, y: y(p)))
        }
        let tTicks = timeTicks(plot: plot, bw: bw)
        for (i, _) in tTicks {
            grid.move(to: CGPoint(x: x(i), y: plot.minY))
            grid.addLine(to: CGPoint(x: x(i), y: plot.maxY))
        }
        ctx.stroke(grid, with: .color(Color.white.opacity(0.05)), lineWidth: 1)

        var inner = ctx
        inner.clip(to: Path(plot))

        // Зоны позиции — под свечами
        drawZones(&inner, x: xt, y: y, plot: plot, bars: bars)

        // Объём — полоса внизу
        if i0 < i1 {
            let vmax = bars[i0..<i1].map(\.v).max() ?? 1
            var vu = Path(), vd = Path()
            let vh = plot.height * 0.16
            for i in i0..<i1 {
                let b = bars[i]
                let h = vmax > 0 ? CGFloat(b.v / vmax) * vh : 0
                let r = CGRect(x: x(Double(i)) - CGFloat(bw * 0.35), y: plot.maxY - h,
                               width: max(1, CGFloat(bw * 0.7)), height: h)
                if b.up { vu.addRect(r) } else { vd.addRect(r) }
            }
            inner.fill(vu, with: .color(Theme.bid.opacity(0.22)))
            inner.fill(vd, with: .color(Theme.ask.opacity(0.22)))
        }

        // Свечи
        var wu = Path(), wd = Path(), bu = Path(), bd = Path()
        let body = max(1, CGFloat(bw * 0.7))
        for i in i0..<i1 {
            let b = bars[i]
            let cx = x(Double(i))
            var w = Path()
            w.move(to: CGPoint(x: cx, y: y(b.h)))
            w.addLine(to: CGPoint(x: cx, y: y(b.l)))
            let top = y(max(b.o, b.c)), bot = y(min(b.o, b.c))
            let r = CGRect(x: cx - body / 2, y: top, width: body, height: max(1, bot - top))
            if b.up { wu.addPath(w); bu.addRect(r) } else { wd.addPath(w); bd.addRect(r) }
        }
        inner.stroke(wu, with: .color(Theme.bid), lineWidth: 1)
        inner.stroke(wd, with: .color(Theme.ask), lineWidth: 1)
        inner.fill(bu, with: .color(Theme.bid))
        inner.fill(bd, with: .color(Theme.ask))

        // Позиция поверх свечей
        let lastT = bars[bars.count - 1].t + Double(cm.tf * 60)
        let tags = drawTrade(&inner, x: xt, y: y, lo: lo, hi: hi, plot: plot,
                             lastT: lastT, dec: dec)

        // Последняя цена — пунктир через окно
        let last = bars[bars.count - 1]
        let lcol = last.up ? Theme.bid : Theme.ask
        if last.c >= lo && last.c <= hi {
            var lp = Path()
            lp.move(to: CGPoint(x: plot.minX, y: y(last.c)))
            lp.addLine(to: CGPoint(x: plot.maxX, y: y(last.c)))
            inner.stroke(lp, with: .color(lcol.opacity(0.7)),
                         style: StrokeStyle(lineWidth: 1, dash: [2, 3]))
        }

        // Шкала цены
        for p in ticks where y(p) > plot.minY + 8 && y(p) < plot.maxY - 8 {
            ctx.draw(Text(String(format: "%.\(dec)f", p))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Theme.dim),
                     at: CGPoint(x: plot.maxX + 6, y: y(p)), anchor: .leading)
        }
        // Бирки уровней на шкале — как у TradingView
        for t in tags { axisTag(ctx, t.0, t.1, y: y(t.0), plot: plot, dec: dec) }
        if last.c >= lo && last.c <= hi { axisTag(ctx, last.c, lcol, y: y(last.c), plot: plot, dec: dec) }

        // Шкала времени
        for (i, label) in tTicks where x(i) > plot.minX + 20 && x(i) < plot.maxX - 20 {
            ctx.draw(Text(label).font(.system(size: 10)).foregroundColor(Theme.dim),
                     at: CGPoint(x: x(i), y: plot.maxY + Self.timeH / 2))
        }

        // Перекрестие
        var shown = i1 - 1
        if let c = cross, plot.contains(c) {
            let fi = cm.start + Double(c.x - plot.minX) / bw - 0.5
            let k = min(max(Int(fi.rounded()), 0), bars.count - 1)
            shown = k
            let cx = x(Double(k))
            var cp = Path()
            cp.move(to: CGPoint(x: cx, y: plot.minY)); cp.addLine(to: CGPoint(x: cx, y: plot.maxY))
            cp.move(to: CGPoint(x: plot.minX, y: c.y)); cp.addLine(to: CGPoint(x: plot.maxX, y: c.y))
            ctx.stroke(cp, with: .color(Color.white.opacity(0.45)),
                       style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
            axisTag(ctx, price(c.y), Color(hex: 0x363a45), y: c.y, plot: plot, dec: dec)
            let tl = F.tsq(bars[k].t)
            let tr = CGRect(x: cx - 58, y: plot.maxY + 2, width: 116, height: Self.timeH - 4)
            ctx.fill(Path(roundedRect: tr, cornerRadius: 4), with: .color(Color(hex: 0x363a45)))
            ctx.draw(Text(tl).font(.system(size: 10, design: .monospaced)).foregroundColor(.white),
                     at: CGPoint(x: tr.midX, y: tr.midY))
        }

        // Легенда OHLC — по свече под перекрестием или по последней видимой
        if shown >= 0 && shown < bars.count {
            legend(ctx, bars[max(0, min(shown, bars.count - 1))], dec: dec, plot: plot)
        }
    }

    private func legend(_ ctx: GraphicsContext, _ b: TradeChartModel.Bar, dec: Int,
                        plot: CGRect) {
        let col = b.up ? Theme.bid : Theme.ask
        let chg = b.o != 0 ? (b.c / b.o - 1) * 100 : 0
        let f = "%.\(dec)f"
        var t = Text("\(cm.sym) · \(frameName)  ").foregroundColor(Theme.muted)
        for (k, v) in [("O ", b.o), (" H ", b.h), (" L ", b.l), (" C ", b.c)] {
            t = t + Text(k).foregroundColor(Theme.dim)
            t = t + Text(String(format: f, v)).foregroundColor(col)
        }
        t = t + Text(String(format: "  %+.2f%%", chg)).foregroundColor(col)
        ctx.draw(t.font(.system(size: 10, design: .monospaced)),
                 at: CGPoint(x: plot.minX + 6, y: plot.minY + 10), anchor: .leading)
        var bits: [Text] = []
        if let a = cm.avg.last { bits.append(Text("ТВХ " + String(format: f, a.v)).foregroundColor(Theme.accent)) }
        if let tk = cm.take.last { bits.append(Text("цель " + String(format: f, tk.v)).foregroundColor(Theme.bid)) }
        if let q = cm.liq.last { bits.append(Text("ликв " + String(format: f, q.v)).foregroundColor(Theme.ask)) }
        if !bits.isEmpty {
            let line = bits.dropFirst().reduce(bits[0]) { $0 + Text("  ") + $1 }
            ctx.draw(line.font(.system(size: 10, design: .monospaced)),
                     at: CGPoint(x: plot.minX + 6, y: plot.minY + 25), anchor: .leading)
        }
    }

    private var frameName: String {
        TradeChartModel.frames.first { $0.0 == cm.tf }?.1 ?? "\(cm.tf)м"
    }

    private func axisTag(_ ctx: GraphicsContext, _ p: Double, _ col: Color, y: CGFloat,
                         plot: CGRect, dec: Int) {
        let r = CGRect(x: plot.maxX + 1, y: y - 8, width: Self.axisW - 2, height: 16)
        ctx.fill(Path(roundedRect: r, cornerRadius: 3), with: .color(col))
        ctx.draw(Text(String(format: "%.\(dec)f", p))
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundColor(Color(hex: 0x080a0f)),
                 at: CGPoint(x: r.minX + 5, y: r.midY), anchor: .leading)
    }

    // MARK: позиция

    /// Зоны v1: у лонга прибыль НАД средней (зелёная), убыток под; у шорта
    /// зеркально. Граница — ступени ТВХ; по высоте — свечи удержания.
    private func drawZones(_ ctx: inout GraphicsContext, x xt: (Double) -> CGFloat,
                           y: (Double) -> CGFloat, plot: CGRect,
                           bars: [TradeChartModel.Bar]) {
        guard let e = cm.entry else { return }
        let lastT = bars[bars.count - 1].t + Double(cm.tf * 60)
        let end = min(cm.tradeEnd ?? lastT, lastT)
        var rl = e.px, rh = e.px
        for b in bars where b.t >= cm.tradeStart - 60 && b.t <= end + 60 {
            rl = min(rl, b.l); rh = max(rh, b.h)
        }
        for s in cm.avg { rl = min(rl, s.v); rh = max(rh, s.v) }
        if let x = cm.exit { rl = min(rl, x.px); rh = max(rh, x.px) }
        let yTop = y(rh), yBot = y(rl)
        let above = cm.long ? Theme.bid : Theme.ask
        let below = cm.long ? Theme.ask : Theme.bid
        let steps = cm.avg.isEmpty
            ? [TradeChartModel.Step(t0: cm.tradeStart, t1: end, v: e.px)] : cm.avg
        for s in steps {
            let x0 = xt(max(s.t0, cm.tradeStart)), x1 = xt(min(s.t1, end))
            guard x1 > x0 else { continue }
            let yv = min(max(y(s.v), yTop), yBot)
            ctx.fill(Path(CGRect(x: x0, y: yTop, width: x1 - x0, height: yv - yTop)),
                     with: .color(above.opacity(0.10)))
            ctx.fill(Path(CGRect(x: x0, y: yv, width: x1 - x0, height: yBot - yv)),
                     with: .color(below.opacity(0.10)))
        }
    }

    /// Линии и точки позиции. Возвращает бирки для шкалы цены.
    private func drawTrade(_ ctx: inout GraphicsContext, x xt: (Double) -> CGFloat,
                           y: (Double) -> CGFloat, lo: Double, hi: Double, plot: CGRect,
                           lastT: Double, dec: Int) -> [(Double, Color)] {
        var tags: [(Double, Color)] = []
        let f = "%.\(dec)f"
        func stepPath(_ ss: [TradeChartModel.Step]) -> Path {
            var p = Path()
            for (i, s) in ss.enumerated() {
                let a = CGPoint(x: xt(s.t0), y: y(s.v))
                let b = CGPoint(x: xt(min(s.t1, lastT)), y: y(s.v))
                if i == 0 { p.move(to: a) } else { p.addLine(to: a) }
                p.addLine(to: b)
            }
            return p
        }
        /// Ступени цели и ликвидации: в окне — линией, за краем — меткой
        /// у края со стрелкой (правило страницы: «off scale»).
        func levels(_ ss: [TradeChartModel.Step], _ col: Color, _ dash: [CGFloat],
                    _ name: String, _ row: CGFloat) {
            guard let last = ss.last else { return }
            let vis = ss.filter { $0.v >= lo && $0.v <= hi }
            if !vis.isEmpty {
                ctx.stroke(stepPath(vis), with: .color(col),
                           style: StrokeStyle(lineWidth: 1.4, dash: dash))
                tags.append((vis.last!.v, col))
            } else {
                let up = last.v > hi
                let yy = up ? plot.minY + 44 + row : plot.maxY - plot.height * 0.18 - row
                ctx.draw(Text("\(name) \(String(format: f, last.v)) \(up ? "↑" : "↓") за шкалой")
                            .font(.system(size: 10, design: .monospaced)).foregroundColor(col),
                         at: CGPoint(x: max(plot.minX + 6, xt(cm.tradeStart) + 4), y: yy),
                         anchor: .leading)
            }
        }
        levels(cm.take, Theme.bid, [6, 3], "цель", 0)
        levels(cm.liq, Theme.ask, [2, 4], "ликв", 14)

        if !cm.avg.isEmpty {
            ctx.stroke(stepPath(cm.avg), with: .color(Theme.accent),
                       style: StrokeStyle(lineWidth: 2, dash: [4, 3]))
            if let a = cm.avg.last, a.v >= lo, a.v <= hi { tags.append((a.v, Theme.accent)) }
        }

        let ring = cm.live ? Theme.accent : cm.exitTone.color
        // Выход: вертикаль от последней ступени ТВХ и кольцо по итогу
        if let e = cm.exit {
            let ya = y(cm.avg.last?.v ?? cm.entry?.px ?? e.px)
            var v = Path()
            v.move(to: CGPoint(x: xt(e.t), y: ya))
            v.addLine(to: CGPoint(x: xt(e.t), y: y(e.px)))
            ctx.stroke(v, with: .color(ring.opacity(0.6)),
                       style: StrokeStyle(lineWidth: 1, dash: [2, 3]))
            dot(&ctx, CGPoint(x: xt(e.t), y: y(e.px)), ring)
        }
        for a in cm.adds {
            let c = CGPoint(x: xt(a.t), y: y(a.px))
            ctx.fill(Path(ellipseIn: CGRect(x: c.x - 4, y: c.y - 4, width: 8, height: 8)),
                     with: .color(ring))
        }
        if let e = cm.entry { dot(&ctx, CGPoint(x: xt(e.t), y: y(e.px)), Theme.accent) }
        return tags
    }

    /// Кружок события v1: белая точка с цветным кольцом.
    private func dot(_ ctx: inout GraphicsContext, _ c: CGPoint, _ ring: Color) {
        let r = CGRect(x: c.x - 5, y: c.y - 5, width: 10, height: 10)
        ctx.fill(Path(ellipseIn: r), with: .color(.white))
        ctx.stroke(Path(ellipseIn: r), with: .color(ring), lineWidth: 2.6)
    }

    // MARK: шкалы

    static func niceTicks(lo: Double, hi: Double, count: Int) -> [Double] {
        let span = hi - lo
        guard span > 0, count > 0 else { return [] }
        let raw = span / Double(count)
        let mag = pow(10, (log10(raw)).rounded(.down))
        let step = [1, 2, 2.5, 5, 10].map { $0 * mag }.first { $0 >= raw } ?? raw
        var out: [Double] = []
        var v = (lo / step).rounded(.up) * step
        while v <= hi { out.append(v); v += step }
        return out
    }

    /// Метки времени: шаг, при котором между ними не меньше ~90 pt.
    private func timeTicks(plot: CGRect, bw: Double) -> [(Double, String)] {
        let bars = cm.bars
        guard bars.count > 1 else { return [] }
        let secPerPt = Double(cm.tf * 60) / bw
        let want = secPerPt * 90
        let steps: [Double] = [60, 300, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400]
        let step = steps.first { $0 >= want } ?? 86400
        let t0 = cm.time(at: cm.start), t1 = cm.time(at: cm.start + cm.count)
        var out: [(Double, String)] = []
        var t = (t0 / step).rounded(.up) * step
        while t <= t1 && out.count < 30 {
            let utc = t.truncatingRemainder(dividingBy: 86400) == 0
            out.append((cm.index(of: t), utc ? Self.dayF.string(from: Date(timeIntervalSince1970: t))
                                             : Self.hmF.string(from: Date(timeIntervalSince1970: t))))
            t += step
        }
        return out
    }

    private static func fmt(_ p: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = p
        return f
    }
    private static let hmF = fmt("HH:mm")
    private static let dayF = fmt("dd.MM")
}

/// График на весь экран: таймфреймы, «к сделке», закрыть.
struct TradeChartScreen: View {
    let p: Pos
    @ObservedObject var cm: TradeChartModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Button { Haptic.tap(); dismiss() } label: {
                    Image(systemName: "xmark").font(.system(size: 15, weight: .semibold))
                        .frame(width: 34, height: 34)
                }
                SideChip(side: p.r["side"].string)
                Text(p.r["sym"].text).font(.system(size: 16, weight: .bold))
                Spacer(minLength: 6)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(TradeChartModel.frames, id: \.0) { fr in
                            Button(fr.1) { Haptic.tap(); cm.setFrame(fr.0) }
                                .font(.system(size: 13, weight: cm.tf == fr.0 ? .bold : .regular))
                                .foregroundStyle(cm.tf == fr.0 ? Color.white : Theme.muted)
                                .padding(.horizontal, 10).padding(.vertical, 6)
                                .background(cm.tf == fr.0 ? Theme.accent.opacity(0.3) : .clear)
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }
                .fixedSize(horizontal: true, vertical: false)
                Button {
                    Haptic.tap()
                    withAnimation(.easeOut(duration: 0.2)) { cm.fitTrade() }
                } label: {
                    Image(systemName: "scope").frame(width: 34, height: 34)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .tint(.white)
            ChartBody(cm: cm, interactive: true)
            if !cm.notes.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(cm.notes, id: \.self) { Note(text: $0) }
                }
                .padding(.horizontal, 12).padding(.bottom, 6)
            }
        }
        .background(Theme.bg.ignoresSafeArea())
        .task { await cm.follow() }
    }
}

/// Холст с состояниями загрузки и отказа.
struct ChartBody: View {
    @ObservedObject var cm: TradeChartModel
    var interactive: Bool

    var body: some View {
        ZStack {
            if let e = cm.error {
                Note(text: e, tone: .bad).padding()
            } else if cm.loading {
                ProgressView().tint(.white)
            } else if cm.bars.isEmpty {
                Note(text: "Свечей записи за окно позиции нет — это пропуск записи, "
                     + "а не «цена стояла».").padding()
            } else {
                TradeChartCanvas(cm: cm, interactive: interactive)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
