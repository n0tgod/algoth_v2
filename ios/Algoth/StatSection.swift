import Charts
import SwiftUI
import UIKit

/// Счёт книги: главные плитки, издержки, метрики, кривая (`statBlock`).
struct StatSection: View {
    @ObservedObject var m: DCAModel
    let st: J
    let b: J
    let meta: J

    private var fwd: Bool { m.grp == "fwd" }
    private var title: String {
        fwd ? "счёт без бэктеста: записанное вперёд" : "счёт с бэктестом: одна кривая"
    }

    /// Открытые: `nil` — поля нет вовсе (плиток нет), `known == false` —
    /// «не считали» (прочерк с причиной), иначе — отметка.
    private var opPresent: Bool { b["live_known"].raw as? Bool == false || !b["open"].isNil }
    private var opKnown: Bool { b["live_known"].raw as? Bool != false && !b["open"].isNil }

    var body: some View {
        if st.isNil {
            Panel {
                Cap(text: title)
                Note(text: "Строк ещё нет. У книги это не пустота показа: решение "
                     + "попадает в журнал только после того, как его позиция "
                     + "закрылась.")
            }
        } else {
            Panel {
                header
                mainTiles
                CostsWarn(ct: b["costs"], meta: meta)
                metrics
                curve
                notes
            }
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Cap(text: title)
            Spacer(minLength: 4)
            Tag(text: fwd ? "наблюдение" : "общий счёт", accent: fwd)
            if let f = st["final"].double {
                Text(F.fpct(f))
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Tone(f).color)
                    .padding(.horizontal, 8).padding(.vertical, 2)
                    .overlay(Capsule().stroke(Tone(f).color.opacity(0.35)))
            }
        }
    }

    private var openPnl: (String, Tone, String) {
        guard opKnown else { return (F.dash, .plain, "") }
        let op = b["open"]
        if let mk = m.liveMarks {
            let note = mk["n"].isNil ? ""
                : "переоценено \(mk["priced"].text) из \(mk["n"].text) · "
                  + F.hhmm(mk["at"].double)
            if let v = mk["mark_usd"].double { return (F.usd(v), Tone(v), note) }
            if mk["priced"].double == 0 { return (F.dash, .plain, note) }
        }
        let v = op["mark_usd"].double
        return (F.usd(v), Tone(v), "")
    }

    private var mainTiles: some View {
        let usd = st["usd"].double
        let earned = F.usd(usd) + (st["final"].isNil ? ""
                                   : " (" + F.fpct(st["final"].double) + ")")
        let since = st["open_dd_since"].double
        let ddLabel = "просадка открытых"
            + (fwd && since != nil ? " с " + F.monthDay(since!) : "")
        let ddVal = st["open_dd_share"].isNil ? F.dash
            : F.usd(st["open_dd"].double) + " (" + F.fpct(st["open_dd_share"].double) + ")"
        let pnl = openPnl
        return TileGrid(min: 200) {
            Tile(label: "стратегия заработала", value: earned, tone: Tone(usd),
                 big: true, tinted: true)
            if opPresent {
                Tile(label: "открытый pnl", value: pnl.0, tone: pnl.1, big: true,
                     note: pnl.2, tinted: true)
                Tile(label: "открытых позиций",
                     value: opKnown ? String(b["open"]["positions"].array.count)
                                    : F.dash,
                     big: true)
            }
            Tile(label: "просадка депозита", value: F.fpct(st["max_dd"].double),
                 tone: Tone(st["max_dd"].double), big: true, tinted: true)
            Tile(label: ddLabel, value: ddVal, tone: Tone(st["open_dd_share"].double),
                 big: true, tinted: true)
        }
    }

    private var cells: [(String, String, Tone)] {
        func n(_ k: String) -> String { st[k].text }
        var c: [(String, String, Tone)] = [
            ("закрытых позиций", n("n"), .plain),
            ("входов (с доливами)", n("fills"), .plain),
            ("из них бэктест", n("n_bt"), .plain),
            ("из них по котировке", n("n_tail"), .plain),
            ("имён", n("names"), .plain),
            ("дней", n("days"), .plain),
            ("прибыльных сделок", st["win"].double.map {
                String(format: "%.1f %%", $0 * 100) } ?? F.dash, .plain),
            ("среднее время в сделке", F.fixed(st["hold_h"].double, 1, suffix: " ч"),
             .plain),
            ("медиана дня", F.fpct(st["day_median"].double),
             Tone(st["day_median"].double)),
            ("худший день", F.fpct(st["day_worst"].double),
             Tone(st["day_worst"].double)),
            ("зелёных дней", F.fixed(st["day_green"].double, 2), .plain),
            ("укус", n("bite"), .plain),
            ("$ без лучшего имени", F.usd(st["usd_wo_top"].double),
             Tone(st["usd_wo_top"].double)),
            ("$ без 3 лучших дней", F.usd(st["usd_wo_top3d"].double),
             Tone(st["usd_wo_top3d"].double)),
        ]
        if opPresent {
            let w = opKnown ? b["open"]["worst_frac"].double : nil
            c.append(("худшая открытая", F.fpct(w), Tone(w)))
            let cut = b["open"]["cut"].array.count
            if opKnown && cut > 0 { c.append(("оборвано записью", String(cut), .plain)) }
        }
        return c
    }

    private var metrics: some View {
        let c = cells
        return VStack(alignment: .leading, spacing: 8) {
            Cap(text: "метрики и статистика книги (\(c.count))")
            TileGrid(min: 140) {
                ForEach(c.indices, id: \.self) { i in
                    Tile(label: c[i].0, value: c[i].1, tone: c[i].2)
                }
            }
        }
        .padding(.top, 4)
    }

    private var curve: some View {
        let dep = b["deposit"].double ?? Double(m.dep ?? "") ?? 0
        let usd = st["usd"].double
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Cap(text: "динамика счёта (USDT)", tone: Tone(usd))
                Spacer()
                Text(F.usd(usd) + " итогом")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Tone(usd).color)
            }
            EquityCurve(rows: st["days_rows"].array, dep: dep)
        }
        .padding(12)
        .background(Theme.chip)
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    @ViewBuilder private var notes: some View {
        Note(text: "Кривая — накопленный счёт по ЗАКРЫТЫМ позициям от депозита; "
             + "открытые в неё не входят. Группа: "
             + (fwd ? "записанное вперёд" : "бэктест и записанное вперёд")
             + ". Просадка открытых — другая величина: сколько книга держала под "
             + "водой одновременно открытыми позициями в худший час; по группам "
             + "она не делится, поэтому в группе «без бэктеста» там прочерк.")
        if opPresent && !opKnown {
            Note(text: "Открытых не считали: свод пересобран из журнала, а "
                 + "открытые позиции в журнал не идут вовсе. Прочерк здесь значит "
                 + "«не смотрели», а не «открытых нет».")
        } else if opKnown {
            let op = b["open"]
            Note(text: "Открытый pnl — ОТМЕТКА по последней цене, а не исход: с "
                 + "закрытым счётом он не складывается нигде"
                 + (op["at"].isNil ? "" : " (снята " + F.tsq(op["at"].double) + " UTC)")
                 + (op["worst_sym"].string.map {
                     ". Глубже всех сейчас \($0) (" + F.fpct(op["worst_frac"].double)
                     + " · " + F.usd(op["worst_usd"].double) + ")" } ?? "")
                 + ".")
        }
        if let top = st["top_sym"].string {
            Note(text: "Лучшее имя \(top) — плитка «без лучшего имени» показывает "
                 + "итог без него: деньги из одного разгона статистикой не являются. "
                 + "«Без 3 лучших дней» вычитает три лучших ДНЯ: один рыночный "
                 + "эпизод раздаёт деньги десяткам имён разом."
                 + (st["usd_wo_top3d"].isNil
                    ? " У книги моложе четырёх дней вычитать нечего — там прочерк, "
                      + "а не ноль." : ""))
        }
    }
}

/// Издержки уже вычтены; молчать нельзя только про «не измерено».
struct CostsWarn: View {
    let ct: J
    let meta: J

    var body: some View {
        if ct.isNil {
            Note(text: "Издержки в этих деньгах НЕ учтены: свод прежнего образца "
                 + "их не считал. Числа выше — БРУТТО.", tone: .bad)
        } else if !ct["applied"].truthy {
            Note(text: "Издержки не вычтены"
                 + (meta["error"].string.map { ": " + $0 } ?? "")
                 + ". Числа выше — БРУТТО.", tone: .bad)
        } else {
            let parts = warnParts
            if !parts.isEmpty { Note(text: parts.joined(separator: "; ") + ".") }
        }
    }

    private var warnParts: [String] {
        var w: [String] = []
        if ct["not_measured"].truthy {
            w.append("у \(ct["not_measured"].text) сделок из \(ct["n"].text) нет "
                     + "записи рунгов — издержки им не вычтены вовсе")
        }
        if ct["no_funding"].truthy {
            w.append("у \(ct["no_funding"].text) сделок ряд funding не покрывает "
                     + "позицию — funding им не начислен (прочерк, не ноль)")
        }
        return w
    }
}

/// Накопленный счёт по суткам от депозита (`curveSvg`). Точки — сумма
/// дневных денег сервера; итог в шапке берётся из `st.usd`, а не отсюда.
struct EquityCurve: View {
    let rows: [J]
    let dep: Double

    /// Видимое окно по суткам (номера, дробные). `nil` — вся история:
    /// так график и открывается, целиком в своих границах.
    @State private var window: ClosedRange<Double>?
    @State private var pinchBase: ClosedRange<Double>?
    @State private var panBase: ClosedRange<Double>?
    @State private var sel: Int?

    private struct Pt: Identifiable {
        let id: Int
        let eq: Double
        let r: J
        var usd: Double { r["usd"].double ?? 0 }
    }

    var body: some View {
        if rows.count < 2 {
            Note(text: "Кривой ещё нет: суток в этой группе \(rows.count). Из одной "
                 + "точки линии не бывает — это не «книга стоит на месте».")
        } else {
            content
        }
    }

    private var full: ClosedRange<Double> { -0.5...(Double(rows.count) - 0.5) }

    private var content: some View {
        let pts = points
        let dom = window ?? full
        let vis = pts.filter { Double($0.id) >= dom.lowerBound - 1
                               && Double($0.id) <= dom.upperBound + 1 }
        let last = pts.last?.eq ?? dep
        let col = last >= dep ? Theme.bid : Theme.ask
        // Шкала — по видимым суткам: приблизили — кривая на всю высоту.
        var lo = vis.map(\.eq).min() ?? dep, hi = vis.map(\.eq).max() ?? dep
        if window == nil { lo = min(lo, dep); hi = max(hi, dep) }
        let pad = max((hi - lo) * 0.08, 0.01)
        let ydom = (lo - pad)...(hi + pad)
        let base = min(max(dep, ydom.lowerBound), ydom.upperBound)
        let bmax = max(vis.map { abs($0.usd) }.max() ?? 1, 0.01)
        let shown = sel.flatMap { i in pts.indices.contains(i) ? pts[i] : nil } ?? pts.last
        return VStack(alignment: .leading, spacing: 6) {
            if let p = shown { header(p, picked: sel != nil) }
            Chart {
                ForEach(vis) { p in
                    AreaMark(x: .value("сутки", Double(p.id)),
                             yStart: .value("база", base),
                             yEnd: .value("счёт", p.eq))
                        .foregroundStyle(LinearGradient(
                            colors: [col.opacity(0.34), col.opacity(0.02)],
                            startPoint: .top, endPoint: .bottom))
                    LineMark(x: .value("сутки", Double(p.id)), y: .value("счёт", p.eq))
                        .foregroundStyle(col)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                }
                if ydom.contains(dep) {
                    RuleMark(y: .value("депозит", dep))
                        .foregroundStyle(Theme.rule)
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                }
                if let i = sel, pts.indices.contains(i) {
                    RuleMark(x: .value("сутки", Double(i)))
                        .foregroundStyle(Color.white.opacity(0.5))
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    PointMark(x: .value("сутки", Double(i)), y: .value("счёт", pts[i].eq))
                        .symbolSize(80)
                        .foregroundStyle(col)
                }
            }
            .chartXScale(domain: dom)
            .chartYScale(domain: ydom)
            .chartXAxis(.hidden)
            .chartYAxis {
                AxisMarks(position: .trailing) { _ in
                    AxisGridLine().foregroundStyle(Theme.rule)
                    AxisValueLabel().foregroundStyle(Theme.dim)
                }
            }
            .chartPlotStyle { $0.clipped() }
            .chartOverlay { proxy in gestures(proxy) }
            .frame(height: 220)
            // Вибрация: толчок при захвате и щелчок на каждом новом дне
            // (`ChartTouchLayer`). На iPad вибромотора нет.
            .sensoryFeedback(.selection, trigger: sel) { old, new in
                old != nil && new != nil && old != new }
            // Результат каждого дня столбиком — та же ось суток.
            Chart {
                ForEach(vis) { p in
                    BarMark(x: .value("сутки", Double(p.id)), y: .value("день", p.usd),
                            width: .ratio(0.7))
                        .foregroundStyle((p.usd >= 0 ? Theme.bid : Theme.ask)
                            .opacity(sel == nil || sel == p.id ? 0.85 : 0.35))
                }
                RuleMark(y: .value("ноль", 0)).foregroundStyle(Theme.rule)
            }
            .chartXScale(domain: dom)
            .chartYScale(domain: -bmax...bmax)
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 5)) { v in
                    AxisValueLabel {
                        if let d = v.as(Double.self), pts.indices.contains(Int(d.rounded())) {
                            Text(String(pts[Int(d.rounded())].r["d"].text.dropFirst(5)))
                                .foregroundStyle(Theme.dim)
                        }
                    }
                }
            }
            .chartYAxis {
                AxisMarks(position: .trailing, values: [-bmax, 0, bmax]) { _ in
                    AxisValueLabel().foregroundStyle(Theme.dim)
                }
            }
            .chartPlotStyle { $0.clipped() }
            .chartOverlay { proxy in gestures(proxy) }
            .frame(height: 90)
            HStack {
                Text((rows.first?["d"].text ?? "") + " · " + F.dollars(dep))
                Spacer()
                Text(window == nil ? "зажмите — итог дня · щипок — масштаб"
                                   : "сдвиг пальцем · разведите до конца — вся история")
                    .foregroundStyle(Theme.dim)
                Spacer()
                Text((rows.last?["d"].text ?? "") + " · $" + String(format: "%.2f", last))
            }
            .font(.system(size: 11)).foregroundStyle(Theme.muted)
        }
    }

    /// Строка над графиком: итог выбранного дня крупно (по умолчанию —
    /// последнего). Числа — поля той же строки `days_rows`, что в таблице.
    private func header(_ p: Pt, picked: Bool) -> some View {
        let r = p.r
        let usd: Double? = r["usd"].double
        let tone: Color = Tone(usd).color
        let day: String = r["d"].text
        let money: String = F.usd(usd)
        let share: String = dep > 0 ? F.fpct((usd ?? 0) / dep) : ""
        let bal: String = "счёт $" + String(format: "%.2f", p.eq)
        var pos: String = "позиций " + r["n"].text
        if let l = r["long"].double { pos += " · L " + F.us(l) }
        if let s = r["short"].double { pos += " · S " + F.us(s) }
        return HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(day)
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                .foregroundStyle(picked ? Theme.ink : Theme.muted)
            Text(money)
                .font(.system(size: 20, weight: .heavy, design: .monospaced))
                .foregroundStyle(tone)
            Text(share)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(tone)
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 1) {
                Text(bal)
                Text(pos)
            }
            .font(.system(size: 11, design: .monospaced))
            .foregroundStyle(Theme.muted)
        }
    }

    /// Жесты: зажатие — выбор дня с вибрацией на каждом новом дне; щипок —
    /// масштаб; сдвиг пальцем — только в приближении (иначе мешал бы
    /// листать страницу).
    private func gestures(_ proxy: ChartProxy) -> some View {
        GeometryReader { g in
            let plot = proxy.plotFrame.map { g[$0] } ?? CGRect(origin: .zero, size: g.size)
            ChartTouchLayer(
                panEnabled: window != nil,
                onPick: { x in pick(proxy, x: x - plot.minX) },
                onPickEnd: { sel = nil },
                onPinch: { scale, ax, ended in
                    if ended { pinchBase = nil; return }
                    let b = pinchBase ?? (window ?? full)
                    if pinchBase == nil { pinchBase = b }
                    let frac = Double((ax * g.size.width - plot.minX) / max(plot.width, 1))
                    let anchor = b.lowerBound + (b.upperBound - b.lowerBound)
                        * min(max(frac, 0), 1)
                    zoom(b, around: anchor, by: Double(scale))
                },
                onPan: { dx, ended in
                    if ended { panBase = nil; return }
                    guard sel == nil, let w = window else { return }
                    if panBase == nil { panBase = w }
                    let b = panBase ?? w
                    let per = (b.upperBound - b.lowerBound) / max(Double(plot.width), 1)
                    shift(b, by: -Double(dx) * per)
                })
        }
    }

    private func pick(_ proxy: ChartProxy, x: CGFloat) {
        guard let v: Double = proxy.value(atX: x) else { return }
        let i = min(max(Int(v.rounded()), 0), rows.count - 1)
        if i != sel {
            sel = i
        }
    }

    private func zoom(_ b: ClosedRange<Double>, around ax: Double, by k: Double) {
        let f = full
        let span = min(max((b.upperBound - b.lowerBound) / max(k, 0.01), 5),
                       f.upperBound - f.lowerBound)
        if span >= f.upperBound - f.lowerBound - 0.01 { window = nil; return }
        let t = (ax - b.lowerBound) / (b.upperBound - b.lowerBound)
        var lo = ax - span * t
        lo = min(max(lo, f.lowerBound), f.upperBound - span)
        window = lo...(lo + span)
    }

    private func shift(_ b: ClosedRange<Double>, by d: Double) {
        let f = full
        let span = b.upperBound - b.lowerBound
        let lo = min(max(b.lowerBound + d, f.lowerBound), f.upperBound - span)
        window = lo...(lo + span)
    }

    private var points: [Pt] {
        var acc = 0.0
        return rows.enumerated().map { i, r in
            acc += r["usd"].double ?? 0
            return Pt(id: i, eq: dep + acc, r: r)
        }
    }
}
