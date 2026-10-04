import SwiftUI

/// Экран DCA — родная версия страницы `/dca-page`.
///
/// Порядок блоков — страницы: фильтры, книга, счёт (главные плитки,
/// метрики, кривая), сутки, короткие книги, позиции. iPhone — одна
/// колонка и нижняя панель; iPad — сетки плиток и карточек шире.
struct DCAView: View {
    @StateObject private var m = DCAModel()
    @State private var showIntro = false
    @State private var detail: Pos?
    @Environment(\.horizontalSizeClass) private var hsc
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        content
                    }
                    .padding(.horizontal, hsc == .regular ? 24 : 12)
                    .padding(.vertical, 12)
                    .frame(maxWidth: 1500)
                    .frame(maxWidth: .infinity)
                }
                .refreshable {
                    await m.load()
                    await m.loadMarks()
                }
                .safeAreaInset(edge: .bottom) {
                    if hsc != .regular, m.data?["present"].truthy == true {
                        BottomBar(m: m) {
                            withAnimation { proxy.scrollTo("positions", anchor: .top) }
                        }
                    }
                }
            }
            .background(Theme.bg.ignoresSafeArea())
            .navigationTitle("DCA")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Theme.surface, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { showIntro = true } label: {
                        Image(systemName: "info.circle")
                    }
                    .disabled(m.data?["present"].truthy != true)
                }
            }
        }
        .tint(Theme.accent)
        .task { await m.run() }
        .onChange(of: scenePhase) { phase in
            // В фоне iOS опрос останавливает: по возвращении — свежий свод,
            // а не числа часовой давности под видом текущих.
            if phase == .active { Task { await m.load(); await m.loadMarks() } }
        }
        .sheet(item: $detail) { p in
            PositionDetail(p: p, m: m)
        }
        .sheet(isPresented: $showIntro) {
            IntroView(d: m.data ?? J(nil))
        }
    }

    @ViewBuilder private var content: some View {
        if let w = m.data?["window"], !w.isNil {
            Text("окно решений \(w["from"].text) … \(w["to"].text) UTC")
                .font(.system(size: 11)).foregroundStyle(Theme.dim)
        }
        if let f = m.failure {
            FailureCard(failure: f, hasData: m.data != nil,
                        loadedAt: m.loadedAt) {
                Task { await m.load() }
            }
        }
        if let d = m.data {
            if !d["present"].truthy {
                Panel {
                    Cap(text: "что это", dot: false)
                    Note(text: d["why"].string ?? "нет ответа сборщика")
                }
            } else {
                Filters(m: m)
                BookBody(m: m, d: d, onPick: { detail = $0 })
            }
        } else if m.failure == nil {
            HStack { Spacer(); ProgressView().tint(.white).padding(40); Spacer() }
        }
    }
}

/// Отказ словами. Есть прошлый ответ — он остаётся на экране, но под
/// красной плашкой с временем: молча показывать старое как свежее нельзя.
struct FailureCard: View {
    let failure: FetchError
    let hasData: Bool
    let loadedAt: Date?
    let retry: () -> Void

    var body: some View {
        Panel(alarm: true) {
            Text(failure.words).font(.system(size: 13)).foregroundStyle(Theme.ink)
            if hasData, let t = loadedAt {
                Note(text: "Ниже — числа прошлого ответа, "
                     + F.hhmm(t.timeIntervalSince1970) + ".", tone: .bad)
            }
            Button("Повторить", action: retry).buttonStyle(.borderedProminent)
        }
    }
}

/// Оси книги: режим, депозит, группа счёта.
struct Filters: View {
    @ObservedObject var m: DCAModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // 1. Сторона: общий счёт, только лонги, только шорты.
            Picker("сторона", selection: Binding(get: { m.curSide },
                                                 set: { m.setSide($0) })) {
                ForEach(m.sides, id: \.0) { s in Text(s.1).tag(s.0) }
            }
            .pickerStyle(.segmented)
            // 2. Режим плеча внутри стороны.
            HStack(spacing: 8) {
                ForEach(m.modes, id: \.0) { md in
                    Chip(title: md.1, on: md.0 == m.rul, fill: true) {
                        m.setRuler(md.0)
                    }
                }
            }
            // 3. Депозит и учёт бэктеста.
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(m.deposits, id: \.self) { x in
                        let k = String(Int(x))
                        Chip(title: F.dollars(x), on: k == m.dep) { m.setDep(k) }
                    }
                    Divider().frame(height: 20).overlay(Theme.rule)
                    // Умолчание — «с бэктестом»: это общий счёт книги, одна
                    // кривая; «без бэктеста» снимает пересчёт одним нажатием.
                    Chip(title: "с бэктестом", on: m.grp == "all") {
                        m.grp = "all"; m.page = 0
                    }
                    Chip(title: "без бэктеста", on: m.grp == "fwd") {
                        m.grp = "fwd"; m.page = 0
                    }
                }
            }
        }
        .padding(10)
        .background(Theme.surface)
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }
}

/// Всё, что ниже фильтров: книга, счёт, сутки, короткие, позиции.
struct BookBody: View {
    @ObservedObject var m: DCAModel
    let d: J
    let onPick: (Pos) -> Void

    var body: some View {
        let b = m.book
        let st = m.grp == "fwd" ? b["forward"] : b["all"]
        let rmeta = m.rulers.first { $0["key"].string == m.rul } ?? J(nil)

        if d["stale"].truthy {
            Panel(alarm: true) {
                Note(text: "Суточный прогон не пришёл, артефакту "
                     + d["age_h"].text + " ч. Числа ниже описывают ТОТ "
                     + "прогон, а не сегодняшний день.", tone: .bad)
            }
        }
        BookTiles(b: b, title: rmeta["title"].string ?? m.rul ?? F.dash,
                  dep: m.dep)
        PairNotes(b: b)
        StatSection(m: m, st: st, b: b, meta: d["costs"])
        if m.grp == "fwd",
           let fam = rmeta["family"].string,
           let since = d["rules"]["FAMILY_SINCE"][fam].string {
            Panel {
                Note(text: "Запись вперёд у этой книги идёт с \(since): в этот "
                     + "день сменились правила её семейства, и решения, писанные "
                     + "прежними правилами, в счёт нынешних не идут. Это не "
                     + "остановка книги — сделки в группе «с бэктестом» "
                     + "считаются как прежде.")
            }
        }
        DupNote(dd: b["dups"])
        DaysSection(m: m, st: st, dep: b["deposit"].double
                    ?? Double(m.dep ?? "") ?? 0)
        ShortBooks(sh: d["short"])
        if d["journal_present"].raw as? Bool == false {
            Panel {
                Note(text: "Журнала на этой машине нет вовсе — он живёт там, "
                     + "где книги считаются. Это не то же самое, что «сделок нет».")
            }
        }
        PositionsSection(m: m, onPick: onPick).id("positions")
    }
}

/// Сетка плиток: колонок столько, сколько влезает по ширине.
struct TileGrid<Content: View>: View {
    var min: CGFloat = 150
    @ViewBuilder var content: Content

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: min), spacing: 10)],
                  spacing: 10) {
            content
        }
    }
}

struct BookTiles: View {
    let b: J
    let title: String
    let dep: String?

    var body: some View {
        Panel {
            Cap(text: "книга", dot: false)
            TileGrid {
                ForEach(sideTiles, id: \.0) { t in
                    Tile(label: t.0, value: t.1)
                }
                Tile(label: "строк в журнале", value: b["n_journal"].text)
            }
        }
    }

    /// Билет и места — свойства СТОРОНЫ: у общего счёта по плитке на
    /// сторону, у обычной книги — две.
    private var sideTiles: [(String, String)] {
        let pr = b["parts"]
        let ks = orderedParts(pr)
        if ks.isEmpty {
            return [("мест", b["slots"].text),
                    ("билет", b["ticket"].double.map { "$" + J($0).text } ?? F.dash)]
        }
        let nm: (J) -> String = { $0["side"].string == "short" ? "короткой" : "длинной" }
        var out: [(String, String)] = []
        for k in ks { out.append(("мест " + nm(pr[k]), pr[k]["slots"].text)) }
        for k in ks {
            out.append(("билет " + nm(pr[k]),
                        pr[k]["ticket"].double.map { "$" + J($0).text } ?? F.dash))
        }
        return out
    }
}

/// Стороны общего счёта: длинная первой.
func orderedParts(_ pr: J) -> [String] {
    pr.keys.sorted { a, b in
        let sa = pr[a]["side"].string == "short" ? 1 : 0
        let sb = pr[b]["side"].string == "short" ? 1 : 0
        return sa == sb ? a < b : sa < sb
    }
}

/// «Мест» у общего счёта — суммой сторон, а не прочерком.
func slotsText(_ b: J) -> String {
    let ks = orderedParts(b["parts"])
    if ks.isEmpty { return b["slots"].text }
    let v = ks.map { b["parts"][$0]["slots"] }
    if v.contains(where: { $0.isNil }) { return F.dash }
    return v.map(\.text).joined(separator: " + ")
}

struct PairNotes: View {
    let b: J

    var body: some View {
        let pr = b["parts"]
        if pr.isObject, !pr.keys.isEmpty {
            let sh = pr.keys.map { pr[$0] }
                .first { $0["side"].string == "short" } ?? J(nil)
            let share: String = {
                guard let s = sh["share_mult"].double else { return "свою долю" }
                return s >= 1 ? "свой билет целиком"
                    : J(s).text + "× от собственного билета"
            }()
            Panel {
                Note(text: "Общего билета у счёта НЕ СУЩЕСТВУЕТ: размер позиции "
                     + "считает каждая сторона своим правилом — длинная от своего "
                     + "пика одновременных позиций, короткая берёт \(share). "
                     + "Деньги при этом одни: занятая одной стороной маржа "
                     + "недоступна другой, и часть сделок поэтому не случается.")
            }
            let one = b["one_sided"].array.compactMap(\.string)
            if !one.isEmpty {
                Panel(alarm: true) {
                    Note(text: "В общем счёте нет одной стороны ("
                         + one.joined(separator: ", ") + "): числа этой книги "
                         + "описывают половину замысла, а выглядят как целая "
                         + "книга. Читать их нельзя, пока сторона не появится.",
                         tone: .bad)
                }
            }
        }
    }
}

struct DupNote: View {
    let dd: J

    var body: some View {
        Panel {
            if dd.isNil {
                Note(text: "Правило «одно имя — одна позиция» на этой книге НЕ "
                     + "ПРОВЕРЯЛОСЬ: свод прежнего образца поля не несёт. Это не "
                     + "то же самое, что «дублей нет».")
            } else {
                let bad = (dd["overlaps"].double ?? 0) > 0
                if bad {
                    Note(text: "Дубли: \(dd["overlaps"].text). Две позиции книги "
                         + "по одному имени пересекаются во времени — это дефект "
                         + "правила «одна на имя», а не свойство рынка.", tone: .bad)
                } else {
                    Text("Дублей нет. ").bold().foregroundColor(Theme.ink)
                        + Text("Ни одна пара позиций по одному имени не "
                               + "пересекается во времени: "
                               + "\(dd["positions"].text) позиций, "
                               + "\(dd["names"].text) имён.")
                        .foregroundColor(Theme.muted)
                }
                Note(text: "Повторных входов после закрытия \(dd["repeats"].text), "
                     + "медиана паузы "
                     + (dd["pause_median_h"].isNil ? F.dash
                        : dd["pause_median_h"].text + " ч")
                     + ", больше всего входов в одно имя "
                     + "\(dd["max_per_name"].text).")
            }
        }
        .font(.system(size: 12))
    }
}

/// Нижняя панель iPhone: накопленный счёт, открытые из мест, к журналу.
/// Числа — те же поля, что в плитках; своей арифметики у неё нет.
struct BottomBar: View {
    @ObservedObject var m: DCAModel
    let jump: () -> Void

    var body: some View {
        let b = m.book
        let st = m.grp == "fwd" ? b["forward"] : b["all"]
        let known = b["live_known"].raw as? Bool != false && !b["open"].isNil
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 2) {
                Text("НАКОПЛ. СЧЁТ").font(.system(size: 9)).tracking(1)
                    .foregroundStyle(Theme.muted)
                Text(F.usd(st["usd"].double)
                     + (st["final"].isNil ? "" : " (" + F.fpct(st["final"].double) + ")"))
                    .font(.system(size: 14, weight: .bold, design: .monospaced))
                    .foregroundStyle(Tone(st["usd"].double).color)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("ОТКРЫТО / МЕСТ").font(.system(size: 9)).tracking(1)
                    .foregroundStyle(Theme.muted)
                Text((known ? String(b["open"]["positions"].array.count) : F.dash)
                     + " / " + slotsText(b))
                    .font(.system(size: 14, weight: .bold, design: .monospaced))
                    .foregroundStyle(Theme.ink)
            }
            Spacer()
            Button("журнал", action: jump).buttonStyle(.bordered).controlSize(.small)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.ultraThinMaterial)
        .overlay(Rectangle().frame(height: 1).foregroundStyle(Theme.rule),
                 alignment: .top)
    }
}
