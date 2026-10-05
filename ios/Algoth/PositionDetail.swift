import SwiftUI

/// Раскрытая позиция: КАЖДЫЙ вход своей строкой, ТВХ после него и выход
/// (`fillRows`). Контракты и ТВХ приходят с сервера (`rules.avg_walk`).
struct PositionDetail: View {
    let p: Pos
    @ObservedObject var m: DCAModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var cm = TradeChartModel()
    @State private var full = false

    var body: some View {
        let r = p.r
        let short = r["side"].string == "short"
        let walk = r["walk"].array
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    PosCard(p: p, mark: nil)
                    preview
                    Cap(text: "лестница позиции")
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), spacing: 10)],
                              spacing: 10) {
                        ForEach(walk.indices, id: \.self) { i in
                            leg(walk[i], i, short)
                        }
                        finalLeg(r, walk.last?["qty"].double, short)
                    }
                }
                .padding(16)
            }
            .background(Theme.bg.ignoresSafeArea())
            .task { await cm.load(p: p, book: m.bookKey) }
            .fullScreenCover(isPresented: $full) { TradeChartScreen(p: p, cm: cm) }
            .navigationTitle(r["sym"].text)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") { Haptic.tap(); dismiss() }
                }
            }
        }
    }

    /// Превью графика в карточке; касание — на весь экран.
    private var preview: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Cap(text: "график позиции")
                Spacer()
                Button { Haptic.tap(); full = true } label: {
                    Label("на весь экран", systemImage: "arrow.up.left.and.arrow.down.right")
                        .font(.system(size: 12))
                }
            }
            ChartBody(cm: cm, interactive: false)
                .frame(height: 300)
                .contentShape(Rectangle())
                .onTapGesture { Haptic.tap(); full = true }
        }
        .padding(12)
        .background(Theme.chip)
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func leg(_ f: J, _ i: Int, _ short: Bool) -> some View {
        legCard(title: i == 0 ? "вход" : "долив \(i)",
                rows: [("когда", F.tsq(f["at"].double), .plain),
                       ("цена", F.px(f["px"].double), .plain),
                       ("доля", f["w"].double.map {
                           String(format: "%.0f %%", $0 * 100) } ?? F.dash, .plain),
                       (short ? "продано" : "куплено", F.qty(f["dq"].double), .plain),
                       ("стало", F.qty(f["qty"].double), .plain),
                       ("ТВХ после", F.px(f["avg"].double), .plain)],
                note: i > 0 ? "цена дошла до структурного уровня"
                    : (short ? "первый рунг (шорт) по сигналу модели"
                             : "первый рунг по сигналу модели"))
    }

    /// У открытой выхода НЕ СУЩЕСТВУЕТ: последняя строка — отметка.
    private func finalLeg(_ r: J, _ qt: Double?, _ short: Bool) -> some View {
        let depth = r["depth"].isNil ? F.dash : "рунгов " + r["depth"].text
        if p.live {
            let money = r["mark_usd"].double
            return legCard(title: "ещё открыта",
                           rows: [("когда", F.tsq(r["last_ts"].double), .plain),
                                  ("глубина", depth, .plain),
                                  ("держим", F.qty(qt), .plain),
                                  ("отметка", F.fpct(r["mark_frac"].double) + " · "
                                   + F.usd(money), (money ?? 0) > 0 ? .good : .bad)],
                           note: "отметка, а не исход")
        }
        let money = r["usd"].double
        return legCard(title: "выход",
                       rows: [("когда", F.tsq(r["exit_ts"].double), .plain),
                              ("цена", F.px(r["exit_px"].double), .plain),
                              ("глубина", depth, .plain),
                              (short ? "откуплено" : "продано", F.qty(qt), .plain),
                              ("стало", "0", .plain),
                              ("итог", F.fpct(r["pnl_frac"].double) + " · "
                               + F.usd(money), (money ?? 0) > 0 ? .good : .bad)],
                       note: (r["exit"].string ?? "") + (short ? " · откуплено" : ""))
    }

    private func legCard(title: String, rows: [(String, String, Tone)],
                         note: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.system(size: 14, weight: .bold))
            Divider().overlay(Theme.rule)
            ForEach(rows.indices, id: \.self) { i in
                KV(label: rows[i].0, value: rows[i].1, tone: rows[i].2)
            }
            if !note.isEmpty {
                Text(note).font(.system(size: 11)).foregroundStyle(Theme.dim)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.chip)
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.rule))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

/// «Что это»: режимы и числа правил — с сервера, не литералами.
struct IntroView: View {
    let d: J
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let r = d["rules"]
        let deps = r["DEPOSITS"].array.compactMap(\.double)
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Note(text: "Бумажные DCA-книги: три режима × три депозита, "
                         + "реплей по барам записи стакана. Деньги — НЕТТО, издержки "
                         + "в каждой сделке. Режим — не настройка агрессивности: "
                         + "плечо выводится из неравенства безопасности, и режим "
                         + "задаёт, ИЗ ЧЕГО.")
                    ForEach(d["rulers"].array.indices, id: \.self) { i in
                        let x = d["rulers"].array[i]
                        let k = x["key"].string ?? ""
                        Panel {
                            Text(x["title"].string ?? k).font(.system(size: 15, weight: .bold))
                            Note(text: x["plain"].string ?? "")
                            KV(label: "пол", value: r["FLOORS"][k].isNil ? F.dash
                               : "$" + r["FLOORS"][k].text)
                            KV(label: "пик", value: r["PEAKS"][k].isNil
                               ? r["PEAK_SEEN"].text : r["PEAKS"][k].text)
                            KV(label: "билет", value: deps.map {
                                ticket(r, k, $0) }.joined(separator: " / "))
                        }
                    }
                    Panel {
                        Cap(text: "правила", dot: false)
                        KV(label: "версия правил", value: r["RULES"].text)
                        KV(label: "срок позиции", value: r["HOLD_H"].text + " ч")
                        KV(label: "гейт края", value: r["MIN_EDGE_BP"].text + " б.п.")
                        KV(label: "RR не ниже", value: r["MIN_RR"].text)
                        KV(label: "цель", value: "×" + r["TAKE_MULT"].text)
                        KV(label: "одна позиция на имя",
                           value: r["ONE_PER_NAME"].truthy ? "да" : "нет")
                    }
                }
                .padding(16)
            }
            .background(Theme.bg.ignoresSafeArea())
            .navigationTitle("Что это")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") { Haptic.tap(); dismiss() }
                }
            }
        }
    }

    /// Билет считается ПО РЕЖИМУ; артефакт прежнего образца нёс один набор.
    private func ticket(_ r: J, _ k: String, _ dep: Double) -> String {
        let t = r["TICKETS"]
        let key = String(Int(dep))
        let v = t[k].isObject ? t[k][key] : t[key]
        return v.isNil ? F.dash : "$" + v.text
    }
}
