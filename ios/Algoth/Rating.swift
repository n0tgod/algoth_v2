import SwiftUI

/// Рейтинг стратегий: все книги всех сторон (общий счёт, лонги, шорты
/// h24) на одном депозите, упорядоченные по выбранной мере. Числа — те
/// же, что у экрана книги (`books["ключ:депозит"].all / .forward`);
/// сервер их считает, экран только сортирует и печатает.
struct RatingScreen: View {
    @ObservedObject var m: DCAModel
    /// Открыть книгу на экране DCA: ключ линейки и депозит.
    let open: (String, String) -> Void
    @Environment(\.horizontalSizeClass) private var hsc
    @State private var dep: String?
    @State private var grp = "all"
    @State private var by = Measure.final

    enum Measure: String, CaseIterable {
        case final, ratio, dd
        var title: String {
            switch self {
            case .final: return "доход"
            case .ratio: return "доход / просадка"
            case .dd: return "просадка"
            }
        }
    }

    struct Row: Identifiable {
        let id: String          // ключ линейки
        let side: String
        let mode: String
        let title: String
        let st: J
        let book: J
        let since: String?
        var final: Double? { st["final"].double }
        var dd: Double? { st["max_dd"].double }
        var n: Int { Int(st["n"].double ?? 0) }
        /// Доход на единицу просадки; просадки нет — меры нет (не ∞).
        var ratio: Double? {
            guard let f = final, let d = dd, abs(d) > 1e-9 else { return nil }
            return f / abs(d)
        }
    }

    private var curDep: String? {
        dep ?? m.deposits.first.map { String(Int($0)) }
    }

    private func rows(_ d: J) -> [Row] {
        guard let dk = curDep else { return [] }
        let all: [Row] = m.rulers.compactMap { r in
            guard let k = r["key"].string else { return nil }
            let b = d["books"][k + ":" + dk]
            if b.isNil { return nil }
            let side = DCAModel.side(of: r)
            let fam = r["family"].string
            return Row(id: k, side: side, mode: DCAModel.mode(of: k),
                       title: m.modeTitle(DCAModel.mode(of: k)),
                       st: grp == "fwd" ? b["forward"] : b["all"], book: b,
                       since: fam.flatMap { d["rules"]["FAMILY_SINCE"][$0].string })
        }
        // Книга без сделок мерой не обладает — она внизу, а не «нулём»
        // посреди рейтинга.
        func key(_ r: Row) -> Double? {
            guard r.n > 0 else { return nil }
            switch by {
            case .final: return r.final
            case .ratio: return r.ratio
            case .dd: return r.dd
            }
        }
        return all.sorted { a, b in
            switch (key(a), key(b)) {
            case let (x?, y?): return x > y
            case (_?, nil): return true
            default: return false
            }
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let f = m.failure {
                        FailureCard(failure: f, hasData: m.data != nil,
                                    loadedAt: m.loadedAt) { Task { await m.load() } }
                    }
                    if let d = m.data {
                        controls
                        stale(d)
                        list(d)
                    } else if m.failure == nil {
                        HStack { Spacer(); ProgressView().tint(.white).padding(40); Spacer() }
                    }
                }
                .padding(.horizontal, hsc == .regular ? 24 : 12)
                .padding(.vertical, 12)
                .frame(maxWidth: 1100)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await m.load() }
            .background(Theme.bg.ignoresSafeArea())
            .navigationTitle("Рейтинг стратегий")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Theme.surface, for: .navigationBar)
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                ForEach(m.deposits, id: \.self) { x in
                    let k = String(Int(x))
                    Chip(title: F.dollars(x), on: k == curDep, fill: true) { dep = k }
                }
            }
            Picker("учёт", selection: Binding(get: { grp },
                                              set: { if grp != $0 { Haptic.tap() }; grp = $0 })) {
                Text("с бэктестом").tag("all")
                Text("без бэктеста").tag("fwd")
            }
            .pickerStyle(.segmented)
            HStack(spacing: 8) {
                ForEach(Measure.allCases, id: \.self) { x in
                    Chip(title: x.title, on: x == by, fill: true) { by = x }
                }
            }
        }
        .padding(10)
        .background(Theme.surface)
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    @ViewBuilder
    private func stale(_ d: J) -> some View {
        let late = [("длинных книг", d), ("коротких книг", d["short"]),
                    ("общего счёта", d["pair"])].filter { $0.1["stale"].truthy }
        if !late.isEmpty {
            Panel(alarm: true) {
                Note(text: "Свод " + late.map { $0.0 }.joined(separator: ", ")
                     + " устарел: прогон не пришёл, их числа описывают прошлый "
                     + "прогон.", tone: .bad)
            }
        }
    }

    private func list(_ d: J) -> some View {
        let rs = rows(d)
        return Panel {
            Cap(text: "\(rs.count) стратегий · \(F.dollars(Double(curDep ?? "")))"
                + " · по мере «\(by.title)»")
            if rs.isEmpty {
                Note(text: "Книг на этом депозите в своде нет.")
            }
            VStack(spacing: 8) {
                ForEach(Array(rs.enumerated()), id: \.element.id) { i, r in
                    Button { Haptic.tap(); open(r.id, curDep ?? "") } label: {
                        RatingRow(place: r.n > 0 ? i + 1 : nil, r: r, by: by)
                    }
                    .buttonStyle(.plain)
                }
            }
            if grp == "fwd" && Set(rs.compactMap(\.since)).count > 0 {
                Note(text: "Запись вперёд у семейств начата в разные дни (дата — "
                     + "в строке): у книг с короткой записью меньше дней, и "
                     + "сравнение с ними неравное.")
            }
            Note(text: "Рейтинг — витрина прошлого счёта, а не выбор книги: "
                 + "лучшая строка таблицы после просмотра есть лучшая ячейка "
                 + "сетки. Нажатие открывает книгу на вкладке DCA.")
        }
    }
}

private struct RatingRow: View {
    let place: Int?
    let r: RatingScreen.Row
    let by: RatingScreen.Measure

    private var sideTitle: String {
        DCAModel.sideOrder.first { $0.0 == r.side }?.1 ?? r.side
    }
    private var sideColor: Color {
        switch r.side {
        case "short": return Theme.ask
        case "long": return Theme.bid
        default: return Theme.accent
        }
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(place.map { "#\($0)" } ?? "–")
                .font(.system(size: 15, weight: .heavy, design: .monospaced))
                .foregroundStyle(place.map { $0 <= 3 } == true ? Theme.accent : Theme.dim)
                .frame(width: 38, alignment: .leading)
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text(sideTitle)
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(sideColor)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(sideColor.opacity(0.13))
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                    Text(r.title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Theme.ink)
                        .lineLimit(1)
                    if let s = r.since { Tag(text: "с " + s) }
                }
                Text(detail)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Theme.muted)
                    .lineLimit(2)
            }
            Spacer(minLength: 6)
            VStack(alignment: .trailing, spacing: 3) {
                Text(main.0)
                    .font(.system(size: 17, weight: .bold, design: .monospaced))
                    .foregroundStyle(main.1.color)
                    .minimumScaleFactor(0.7).lineLimit(1)
                Text(by.title).font(.system(size: 9)).foregroundStyle(Theme.dim)
            }
            Image(systemName: "chevron.right")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Theme.dim)
        }
        .padding(12)
        .background(Theme.chip)
        .overlay(RoundedRectangle(cornerRadius: 14)
            .stroke(place == 1 ? Theme.accent.opacity(0.5) : Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .contentShape(Rectangle())
    }

    private var main: (String, Tone) {
        guard r.n > 0 else { return ("нет сделок", .plain) }
        switch by {
        case .final: return (F.fpct(r.final), Tone(r.final))
        case .ratio: return (F.fixed(r.ratio, 2), Tone(r.ratio))
        case .dd: return (F.fpct(r.dd), Tone(r.dd))
        }
    }

    private var detail: String {
        var p: [String] = []
        if by != .final { p.append("доход " + F.fpct(r.final)) }
        p.append(F.usd(r.st["usd"].double))
        if by != .dd { p.append("просадка " + F.fpct(r.dd)) }
        p.append("сделок \(r.n)")
        return p.joined(separator: " · ")
    }
}
