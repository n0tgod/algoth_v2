import SwiftUI

/// По суткам: новые сверху, накопленный итог — по ВРЕМЕНИ (`dayTable`).
struct DaysSection: View {
    @ObservedObject var m: DCAModel
    let st: J
    let dep: Double

    private struct Day: Identifiable {
        let id: Int
        let r: J
        let acc: Double
    }

    var body: some View {
        let rs = st["days_rows"].array
        if !rs.isEmpty {
            let all = days(rs)
            let cut = m.daysAll ? all.count : min(DCAModel.daysHead, all.count)
            Panel {
                HStack {
                    Cap(text: "по суткам — \(rs.count) суток")
                    Spacer()
                    if all.count > DCAModel.daysHead {
                        Button(m.daysAll ? "свернуть до \(DCAModel.daysHead)"
                                         : "все \(all.count)") {
                            withAnimation { m.daysAll.toggle() }
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                    }
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 10)],
                          spacing: 10) {
                    ForEach(all.prefix(cut)) { x in dayCard(x) }
                }
                Note(text: "Новые сверху; накопленный итог идёт по ВРЕМЕНИ, то есть "
                     + "сверху вниз убывает. Он считается по общей кривой: бэктест и "
                     + "записанное вперёд ведутся одним счётом."
                     + (cut < all.count ? " Показаны последние \(cut) из \(all.count) суток." : ""))
            }
        }
    }

    /// Итог копится по времени и только потом порядок переворачивается:
    /// пересчёт сверху вниз на перевёрнутом ряде был бы другой величиной.
    private func days(_ rs: [J]) -> [Day] {
        var acc = 0.0
        var out: [Day] = []
        for (i, r) in rs.enumerated() {
            acc += r["usd"].double ?? 0
            out.append(Day(id: i, r: r, acc: acc))
        }
        return Array(out.reversed())
    }

    private func dayCard(_ x: Day) -> some View {
        let r = x.r
        let usd = r["usd"].double
        return VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Circle().fill(Tone(usd) == .plain ? Theme.dim : Tone(usd).color)
                    .frame(width: 7, height: 7)
                Text(r["d"].text).font(.system(size: 15, weight: .bold,
                                               design: .monospaced))
                Spacer()
                Text(F.usd(usd)).font(.system(size: 15, weight: .bold,
                                              design: .monospaced))
                    .foregroundStyle(Tone(usd).color)
            }
            Divider().overlay(Theme.rule)
            KV(label: "позиций", value: r["n"].text)
            KV(label: "из них бэктест", value: r["bt"].text)
            KV(label: "лонг", value: side(r["long"], r["n_long"]),
               tone: Tone(r["long"].double))
            KV(label: "шорт", value: side(r["short"], r["n_short"]),
               tone: Tone(r["short"].double))
            KV(label: "к депозиту",
               value: dep > 0 ? F.fpct((usd ?? 0) / dep) : F.dash, tone: Tone(usd))
            KV(label: "накопленным итогом", value: F.usd(x.acc),
               tone: x.acc > 0 ? .good : .bad)
        }
        .padding(12)
        .background(Theme.chip)
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        // Тонкий день приглушён, но НЕ спрятан.
        .opacity((r["n"].double ?? 0) < 5 ? 0.6 : 1)
    }

    /// Деньги дня по стороне; сделок стороны не было — прочерк, не ноль.
    private func side(_ v: J, _ n: J) -> String {
        guard let x = v.double else { return F.dash }
        return F.usd(x) + (n.truthy ? " (\(n.text))" : "")
    }
}

/// Позиции книги: один список на все состояния, окном 20/50 (`posBlock`).
struct PositionsSection: View {
    @ObservedObject var m: DCAModel
    let onPick: (Pos) -> Void

    static let states = [("all", "все"), ("closed", "закрытые"),
                         ("open", "открытые"), ("cut", "оборванные")]

    var body: some View {
        let b = m.book
        let inGrp = m.positions()
        let rows = m.pst == "all" ? inGrp : inGrp.filter { $0.st == m.pst }
        let total = rows.count
        let pages = max(1, (total + m.size - 1) / m.size)
        let pg = min(m.page, pages - 1)
        let from = pg * m.size
        let win = Array(rows.dropFirst(from).prefix(m.size))
        let shown = b["trades"].array.count
        let tot = b["trades_total"].int
        let cut = tot != nil && shown < tot!
        Panel {
            HStack {
                Cap(text: "позиции книги — \(total)" + (cut ? " (хвост журнала)" : ""))
                Spacer()
                if cut {
                    Button("все \(tot!)") { m.requestFull() }
                        .buttonStyle(.bordered).controlSize(.small)
                }
            }
            if cut {
                Note(text: "Список — ХВОСТ журнала: сервер отдал последние \(shown) "
                     + "закрытых из \(tot!), а плитка «закрытых позиций» считает по "
                     + "всему журналу. Это разные множества.")
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Self.states, id: \.0) { s in
                        let n = s.0 == "all" ? inGrp.count
                            : inGrp.filter { $0.st == s.0 }.count
                        Chip(title: s.1, count: String(n), on: m.pst == s.0) {
                            m.pst = s.0; m.page = 0
                        }
                    }
                }
            }
            if inGrp.contains(where: { $0.st == "cut" }) {
                Note(text: "Оборванные записью — НЕ открытые на бирже: у них кончился "
                     + "ряд цен своего символа раньше, чем у остальных. Закрытыми «по "
                     + "сроку» они не считаются и в счёт книги не входят.")
            }
            if b["live_known"].raw as? Bool == false {
                Note(text: "Открытых в этом прогоне не считали (свод пересобран из "
                     + "журнала) — это не «открытых нет».")
            }
            pager(total: total, pages: pages, pg: pg, from: from)
            if total == 0 {
                Note(text: "В выбранном состоянии позиций нет. Это измерено, а не "
                     + "пропуск показа: счётчик в переключателе говорит, где они есть.")
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 320), spacing: 10)],
                          spacing: 10) {
                    ForEach(win) { p in
                        PosCard(p: p, mark: mark(for: p))
                            .onTapGesture { onPick(p) }
                    }
                }
                if pages > 1 { pager(total: total, pages: pages, pg: pg, from: from) }
            }
        }
    }

    private func pager(total: Int, pages: Int, pg: Int, from: Int) -> some View {
        HStack(spacing: 8) {
            Text("в окне").font(.system(size: 11)).foregroundStyle(Theme.muted)
            ForEach(DCAModel.sizes, id: \.self) { n in
                Chip(title: String(n), on: m.size == n) { m.size = n; m.page = 0 }
            }
            Spacer()
            Button { m.page = max(0, pg - 1) } label: { Image(systemName: "chevron.left") }
                .disabled(pg <= 0)
            Text("\(total == 0 ? 0 : from + 1)–\(min(total, from + m.size)) из \(total)")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(Theme.muted)
            Button { m.page = pg + 1 } label: { Image(systemName: "chevron.right") }
                .disabled(pg >= pages - 1)
        }
    }

    /// Живая отметка открытой — из `/dca_marks` по имени (одна на имя).
    /// Оборванная записью её не получает: ряд её цен кончился.
    private func mark(for p: Pos) -> J? {
        guard p.st == "open", let mk = m.liveMarks else { return nil }
        let sym = p.r["sym"].string
        return mk["rows"].array.first { $0["sym"].string == sym }
    }
}

/// Карточка позиции. Деньги закрытой — ИСХОД, у остальных — ОТМЕТКА.
struct PosCard: View {
    let p: Pos
    let mark: J?

    var body: some View {
        let r = p.r
        let frac = p.live ? (mark?["mark_frac"] ?? r["mark_frac"]).double
                          : r["pnl_frac"].double
        let money = p.live ? (mark?["mark_usd"] ?? r["mark_usd"]).double
                           : r["usd"].double
        let tone: Tone = money == nil ? .plain : (money! > 0 ? .good : .bad)
        let qty = r["walk"].array.last?["qty"].double
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                SideChip(side: r["side"].string)
                Text(r["sym"].text).font(.system(size: 16, weight: .bold))
                if r["bt"].truthy { Tag(text: "бэктест") }
                if r["tail"].truthy { Tag(text: "по котировке") }
                Spacer(minLength: 4)
                Text(F.usd(money)).font(.system(size: 15, weight: .bold,
                                                design: .monospaced))
                    .foregroundStyle(tone.color)
            }
            Divider().overlay(Theme.rule)
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 4) {
                GridRow {
                    KV(label: "вход", value: F.tsq(r["at"].double))
                    KV(label: "выход", value: p.live ? F.dash : F.tsq(r["exit_ts"].double))
                }
                GridRow {
                    KV(label: "плечо", value: r["lev"].double.map {
                        String(format: "%.2f×", $0) } ?? F.dash)
                    KV(label: "маржа", value: F.fixed(r["margin"].double, 2, suffix: " $"))
                }
                GridRow {
                    KV(label: "цена входа", value: F.px(r["entry_px"].double))
                    KV(label: "ТВХ", value: F.px(r["avg"].double))
                }
                GridRow {
                    KV(label: "выход по", value: p.live ? F.dash : F.px(r["exit_px"].double))
                    KV(label: "контрактов", value: F.qty(qty))
                }
                GridRow {
                    KV(label: "ход", value: F.fpct(frac), tone: frac == nil ? .plain : tone)
                    KV(label: "рунгов", value: String(r["fills"].array.count))
                }
            }
            HStack(spacing: 6) {
                stateChip
                if p.live { Tag(text: "отметка") }
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 11))
                    .foregroundStyle(Theme.dim)
            }
        }
        .padding(12)
        .background(Theme.chip)
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .contentShape(Rectangle())
    }

    @ViewBuilder private var stateChip: some View {
        switch p.st {
        case "cut":
            Pill(text: "оборвана записью")
            if let why = p.r["cut_why"].string {
                Text(why).font(.system(size: 11)).foregroundStyle(Theme.dim)
                    .lineLimit(2)
            }
        case "open":
            Pill(text: "открыта", accent: true)
        default:
            let u = p.r["usd"].double
            Pill(text: p.r["exit"].string ?? "", tone: u == nil ? .plain
                 : (u! > 0 ? .good : .bad))
        }
    }
}
