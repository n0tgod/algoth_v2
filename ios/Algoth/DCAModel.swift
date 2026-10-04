import Foundation
import SwiftUI

/// Позиция в общем списке: закрытая, открытая или оборванная записью.
struct Pos: Identifiable {
    let id: String
    let r: J
    let st: String          // closed | open | cut
    var live: Bool { st != "closed" }
}

/// Состояние экрана DCA. Выбор (режим, депозит, группа, окно списка)
/// живёт здесь, а не в виде: свод перезагружается раз в минуту, и выбор,
/// живущий в виде, сбрасывался бы сам (урок страницы).
@MainActor
final class DCAModel: ObservableObject {
    @Published private(set) var data: J?
    @Published private(set) var failure: FetchError?
    @Published private(set) var loadedAt: Date?
    @Published private(set) var failedAt: Date?
    @Published private(set) var marks: J?
    private var marksBook: String?

    @Published var dep: String?
    @Published var rul: String?
    @Published var grp = "all"          // all | fwd
    @Published var pst = "all"          // all | closed | open | cut
    @Published var page = 0
    @Published var size = 20
    @Published var daysAll = false
    /// Ключ книги, у которой список запрошен ЦЕЛИКОМ: сервер отдаёт
    /// хвост журнала, целиком — ровно одну книгу по нажатию.
    @Published private(set) var full: String?

    static let sizes = [20, 50]
    static let daysHead = 5

    var bookKey: String? {
        guard let rul, let dep else { return nil }
        return rul + ":" + dep
    }
    var book: J { bookKey.map { data?["books"][$0] ?? J(nil) } ?? J(nil) }
    var rulers: [J] { data?["rulers"].array ?? [] }
    var deposits: [Double] { data?["deposits"].array.compactMap(\.double) ?? [] }

    /// Полный свод — раз в минуту, отметка открытых — раз в десять секунд
    /// (тот же ритм, что у страницы).
    func run() async {
        await load()
        var tick = 0
        while !Task.isCancelled {
            await loadMarks()
            try? await Task.sleep(nanoseconds: 10_000_000_000)
            tick += 1
            if tick % 6 == 0 { await load() }
        }
    }

    func load() async {
        do {
            let d = try await fetchJSON("/dca", ["full": full])
            data = d
            failure = nil
            loadedAt = Date()
            pickDefaults()
        } catch let e as FetchError {
            failure = e
            failedAt = Date()
        } catch {
            failure = .network(error.localizedDescription)
            failedAt = Date()
        }
    }

    func loadMarks() async {
        guard let rul, let dep else { return }
        let key = rul + ":" + dep
        guard let d = try? await fetchJSON("/dca_marks",
                                           ["ruler": rul, "dep": dep])
        else { return }
        // Отметка прошлой книги под числами новой — подмена; поэтому
        // отметка привязана к книге, которую спрашивали.
        if d["known"].raw as? Bool == false || !d["error"].isNil { return }
        guard bookKey == key else { return }
        marks = d
        marksBook = key
    }

    /// Живая отметка — только своей книги.
    var liveMarks: J? { marksBook == bookKey ? marks : nil }

    private func pickDefaults() {
        if dep == nil, let first = deposits.first {
            dep = String(Int(first))
        }
        // Умолчание — ПЕРВЫЙ режим порядка (безопасная): книга по
        // умолчанию не должна быть той, что рискует больше.
        if rul == nil { rul = rulers.first?["key"].string }
    }

    func setRuler(_ k: String) { rul = k; picked() }

    // MARK: оси книги — сторона и режим
    //
    // Список книг даёт сервер (`rulers`), сторона — его поле `side`
    // (`long` по умолчанию, `short`, `both` у общего счёта). Режим — ключ
    // без приставки общего счёта и без хвоста короткой книги: `pair_safe`,
    // `safe_h` и `safe` — одна линейка плеча «безопасная» на трёх сторонах.

    static let sideOrder: [(String, String)] = [("both", "Both"), ("long", "Long"),
                                                ("short", "Short")]
    static let modeOrder = ["safe", "optimal", "aggr"]

    static func side(of r: J) -> String {
        if let s = r["side"].string, !s.isEmpty { return s }
        let k = r["key"].string ?? ""
        if k.hasPrefix("pair_") { return "both" }
        if k.hasSuffix("_h") { return "short" }
        return "long"
    }

    static func mode(of key: String) -> String {
        var k = key
        if k.hasPrefix("pair_") { k.removeFirst(5) }
        if k.hasSuffix("_h") { k.removeLast(2) }
        return k
    }

    var curSide: String {
        rulers.first { $0["key"].string == rul }.map(Self.side) ?? "long"
    }

    /// Стороны, у которых есть книги, — в порядке Both / Long / Short.
    var sides: [(String, String)] {
        let have = Set(rulers.map(Self.side))
        return Self.sideOrder.filter { have.contains($0.0) }
    }

    /// Режимы выбранной стороны: (ключ книги, название режима).
    var modes: [(String, String)] {
        let mine = rulers.filter { Self.side(of: $0) == curSide }
        let named: [(String, String)] = mine.compactMap { r in
            guard let k = r["key"].string else { return nil }
            return (k, modeTitle(Self.mode(of: k)))
        }
        return named.sorted {
            (Self.modeOrder.firstIndex(of: Self.mode(of: $0.0)) ?? 9)
                < (Self.modeOrder.firstIndex(of: Self.mode(of: $1.0)) ?? 9)
        }
    }

    /// Название режима — у длинной книги того же ключа; её нет — ключ.
    func modeTitle(_ mode: String) -> String {
        rulers.first { $0["key"].string == mode }?["title"].string ?? mode
    }

    /// Смена стороны держит режим: была «оптимальная» — останется она.
    func setSide(_ side: String) {
        let want = Self.mode(of: rul ?? "")
        let cand = rulers.filter { Self.side(of: $0) == side }
        let same = cand.first { Self.mode(of: $0["key"].string ?? "") == want }
        if let k = (same ?? cand.first)?["key"].string { setRuler(k) }
    }
    func setDep(_ k: String) { dep = k; picked() }

    private func picked() {
        page = 0
        marks = nil
        Task {
            if full != nil { full = nil; await load() }
            await loadMarks()
        }
    }

    func requestFull() {
        full = bookKey
        page = 0
        Task { await load() }
    }

    /// Один список на все состояния, свежие сверху (`unifiedRows`).
    func positions() -> [Pos] {
        let b = book
        var out: [Pos] = []
        for r in b["trades"].array {
            out.append(Pos(id: "x" + rowKey(r), r: r, st: "closed"))
        }
        for r in b["open"]["positions"].array {
            out.append(Pos(id: "o" + rowKey(r), r: r, st: "open"))
        }
        for r in b["open"]["cut"].array {
            out.append(Pos(id: "c" + rowKey(r), r: r, st: "cut"))
        }
        out.sort { ($0.r["at"].double ?? 0) > ($1.r["at"].double ?? 0) }
        // Ключ строки обязан быть уникальным для списка: две руки модели
        // могут дать одно имя в один час, и одинаковый ключ молча
        // склеил бы две позиции в одну карточку.
        out = out.enumerated().map { i, p in
            Pos(id: p.id + "#" + String(i), r: p.r, st: p.st)
        }
        // Группа «без бэктеста» режет ЗАКРЫТЫЕ строки пересчёта; у
        // открытой пометки пересчёта не бывает.
        if grp == "fwd" {
            out = out.filter { $0.st != "closed" || !$0.r["bt"].truthy }
        }
        return out
    }

    private func rowKey(_ r: J) -> String {
        String(Int(r["at"].double ?? 0)) + ":" + (r["sym"].string ?? "")
    }
}
