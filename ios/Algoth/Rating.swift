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
    @State private var per = Period.all

    /// Окно рейтинга — в КАЛЕНДАРНЫХ сутках UTC до сегодняшних
    /// включительно, а не в числе строк: у книги, стоявшей неделю,
    /// «7 дней» есть неделя тишины, а не семь последних торговых дней.
    enum Period: String, CaseIterable {
        case d7, d30, d365, all
        var title: String {
            switch self {
            case .d7: return "7 дней"
            case .d30: return "месяц"
            case .d365: return "год"
            case .all: return "всё время"
            }
        }
        var days: Int? {
            switch self {
            case .d7: return 7
            case .d30: return 30
            case .d365: return 365
            case .all: return nil
            }
        }
        static let cal: Calendar = {
            var c = Calendar(identifier: .gregorian)
            c.timeZone = TimeZone(identifier: "UTC")!
            return c
        }()
        /// Ключ дня сервера — «ГГГГ-ММ-ДД» в UTC.
        static let day: DateFormatter = {
            let f = DateFormatter()
            f.calendar = cal
            f.timeZone = cal.timeZone
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd"
            return f
        }()
        /// Первый день окна тем же видом, что ключ дня.
        var start: String? {
            guard let n = days,
                  let d0 = Self.cal.date(byAdding: .day, value: -(n - 1),
                                         to: Self.cal.startOfDay(for: Date()))
            else { return nil }
            return Self.day.string(from: d0)
        }
    }

    /// Счёт книги за окно. Доход — сумма дневных $ сервера за окно,
    /// делённая на депозит: та же формула, что у итога книги
    /// (`run_paper`: `final = Σ usd / deposit`), только на части ряда.
    /// Просадку за окно экран не считает — её считает сервер, и только
    /// по всей истории; вторая копия формулы однажды разошлась бы.
    struct Win {
        let usd: Double
        let n: Int
        let final: Double
        /// Сколько суток истории легло в окно, когда она КОРОЧЕ окна;
        /// иначе nil. «Год» по двум месяцам записи — не год.
        let short: Int?
    }

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
        let win: Win?
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
            let st = grp == "fwd" ? b["forward"] : b["all"]
            return Row(id: k, side: side, mode: DCAModel.mode(of: k),
                       title: m.modeTitle(DCAModel.mode(of: k)),
                       st: st, book: b,
                       since: fam.flatMap { d["rules"]["FAMILY_SINCE"][$0].string },
                       win: window(st, dep: b["deposit"].double ?? Double(dk) ?? 0))
        }
        // Книга без сделок мерой не обладает — она внизу, а не «нулём»
        // посреди рейтинга.
        func key(_ r: Row) -> Double? {
            guard r.n > 0 else { return nil }
            if per != .all {
                guard let w = r.win, w.n > 0 else { return nil }
                return w.final
            }
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

    private func window(_ st: J, dep: Double) -> Win? {
        guard let start = per.start, dep > 0 else { return nil }
        let rs = st["days_rows"].array
        var usd = 0.0, n = 0
        for x in rs where (x["d"].string ?? "") >= start {
            usd += x["usd"].double ?? 0
            n += Int(x["n"].double ?? 0)
        }
        // История короче окна: сколько КАЛЕНДАРНЫХ суток от первого дня
        // книги до сегодня, а не сколько дней со сделками.
        var short: Int? = nil
        if let first = rs.first?["d"].string, first > start,
           let d0 = Period.day.date(from: first) {
            let today = Period.cal.startOfDay(for: Date())
            short = (Period.cal.dateComponents([.day], from: d0, to: today).day ?? 0) + 1
        }
        return Win(usd: usd, n: n, final: usd / dep, short: short)
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
            Picker("период", selection: Binding(get: { per },
                                                set: { if per != $0 { Haptic.tap() }; per = $0 })) {
                ForEach(Period.allCases, id: \.self) { x in Text(x.title).tag(x) }
            }
            .pickerStyle(.segmented)
            // Мера с просадкой — только на всей истории: просадку считает
            // сервер, и только по всему ряду.
            if per == .all {
                HStack(spacing: 8) {
                    ForEach(Measure.allCases, id: \.self) { x in
                        Chip(title: x.title, on: x == by, fill: true) { by = x }
                    }
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

    private func placed(_ r: Row) -> Bool {
        guard r.n > 0 else { return false }
        return per == .all || (r.win?.n ?? 0) > 0
    }

    private func list(_ d: J) -> some View {
        let rs = rows(d)
        return Panel {
            Cap(text: "\(rs.count) стратегий · \(F.dollars(Double(curDep ?? "")))"
                + " · " + (per == .all ? "по мере «\(by.title)»" : "доход за \(per.title)"))
            if rs.isEmpty {
                Note(text: "Книг на этом депозите в своде нет.")
            }
            VStack(spacing: 8) {
                ForEach(Array(rs.enumerated()), id: \.element.id) { i, r in
                    Button { Haptic.tap(); open(r.id, curDep ?? "") } label: {
                        RatingRow(place: placed(r) ? i + 1 : nil, r: r, by: by, per: per)
                    }
                    .buttonStyle(.plain)
                }
            }
            if grp == "fwd" && Set(rs.compactMap(\.since)).count > 0 {
                Note(text: "Запись вперёд у семейств начата в разные дни (дата — "
                     + "в строке): у книг с короткой записью меньше дней, и "
                     + "сравнение с ними неравное.")
            }
            if per != .all {
                Note(text: "Доход за окно — сумма дневного счёта книги за последние "
                     + "\(per.days ?? 0) суток UTC, делённая на депозит (так же "
                     + "считается итог). Просадка за окно не показывается: её "
                     + "считает сервер и только по всей истории. Пометка «есть N "
                     + "дн» — истории у книги меньше окна.")
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
    let per: RatingScreen.Period

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
                    if per != .all, let n = r.win?.short { Tag(text: "есть \(n) дн", accent: true) }
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
                Text(per == .all ? by.title : "за " + per.title).font(.system(size: 9)).foregroundStyle(Theme.dim)
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
        if per != .all {
            guard let w = r.win, w.n > 0 else { return ("нет сделок", .plain) }
            return (F.fpct(w.final), Tone(w.final))
        }
        switch by {
        case .final: return (F.fpct(r.final), Tone(r.final))
        case .ratio: return (F.fixed(r.ratio, 2), Tone(r.ratio))
        case .dd: return (F.fpct(r.dd), Tone(r.dd))
        }
    }

    private var detail: String {
        var p: [String] = []
        if per != .all, let w = r.win {
            p.append(F.usd(w.usd))
            p.append("сделок \(w.n)")
            p.append("всё время " + F.fpct(r.final))
            p.append("просадка " + F.fpct(r.dd))
            return p.joined(separator: " · ")
        }
        if by != .final { p.append("доход " + F.fpct(r.final)) }
        p.append(F.usd(r.st["usd"].double))
        if by != .dd { p.append("просадка " + F.fpct(r.dd)) }
        p.append("сделок \(r.n)")
        return p.joined(separator: " · ")
    }
}
