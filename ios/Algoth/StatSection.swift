import Charts
import SwiftUI

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

    private struct Pt: Identifiable {
        let id: Int
        let eq: Double
    }

    var body: some View {
        if rows.count < 2 {
            Note(text: "Кривой ещё нет: суток в этой группе \(rows.count). Из одной "
                 + "точки линии не бывает — это не «книга стоит на месте».")
        } else {
            let pts = points
            let last = pts.last?.eq ?? dep
            let col = last >= dep ? Theme.bid : Theme.ask
            let lo = min(dep, pts.map(\.eq).min() ?? dep)
            let hi = max(dep, pts.map(\.eq).max() ?? dep)
            let pad = max((hi - lo) * 0.05, 0.01)
            VStack(spacing: 4) {
                Chart {
                    ForEach(pts) { p in
                        AreaMark(x: .value("сутки", p.id),
                                 yStart: .value("депозит", dep),
                                 yEnd: .value("счёт", p.eq))
                            .foregroundStyle(LinearGradient(
                                colors: [col.opacity(0.34), col.opacity(0.02)],
                                startPoint: .top, endPoint: .bottom))
                        LineMark(x: .value("сутки", p.id), y: .value("счёт", p.eq))
                            .foregroundStyle(col)
                            .lineStyle(StrokeStyle(lineWidth: 2))
                    }
                    RuleMark(y: .value("депозит", dep))
                        .foregroundStyle(Theme.rule)
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                }
                .chartXAxis(.hidden)
                .chartYAxis {
                    AxisMarks(position: .trailing) { _ in
                        AxisGridLine().foregroundStyle(Theme.rule)
                        AxisValueLabel().foregroundStyle(Theme.dim)
                    }
                }
                .chartYScale(domain: (lo - pad)...(hi + pad))
                .frame(height: 210)
                HStack {
                    Text((rows.first?["d"].text ?? "") + " · " + F.dollars(dep))
                    Spacer()
                    Text((rows.last?["d"].text ?? "") + " · $"
                         + String(format: "%.2f", last))
                }
                .font(.system(size: 11)).foregroundStyle(Theme.muted)
            }
        }
    }

    private var points: [Pt] {
        var acc = 0.0
        return rows.enumerated().map { i, r in
            acc += r["usd"].double ?? 0
            return Pt(id: i, eq: dep + acc)
        }
    }
}
