import Foundation

/// Сервер и ключ страницы — из сборки, а не из настроек на устройстве.
///
/// Ключ подставляет сборка (секрет `ALGOTH_PAGE_KEY` → настройка сборки
/// → `Info.plist`); в git он не идёт никогда. Нет ключа в сборке — экран
/// говорит это словами, а не показывает пустую книгу.
enum Server {
    static var host: String {
        (Bundle.main.object(forInfoDictionaryKey: "AlgothServer") as? String)
            .flatMap { $0.isEmpty ? nil : $0 } ?? "116.203.146.99"
    }
    static var key: String {
        (Bundle.main.object(forInfoDictionaryKey: "AlgothPageKey") as? String)
            ?? ""
    }

    static func url(_ path: String, _ query: [String: String?] = [:]) -> URL? {
        var c = URLComponents()
        c.scheme = "http"
        c.host = host
        c.path = path
        var items = [URLQueryItem(name: "k", value: key)]
        for (k, v) in query.sorted(by: { $0.key < $1.key }) {
            if let v { items.append(URLQueryItem(name: k, value: v)) }
        }
        c.queryItems = items
        return c.url
    }
}

enum FetchError: Error {
    case noKey, denied, status(Int), network(String), badJSON

    var words: String {
        switch self {
        case .noKey:
            return "В сборке нет ключа страницы (секрет ALGOTH_PAGE_KEY). "
                + "Без ключа сервер отвечает 403."
        case .denied:
            return "Ключ не подошёл: сервер ответил 403. "
                + "Ключ сборки разошёлся с out/token.txt на сервере."
        case .status(let c):
            return "Сервер ответил \(c)."
        case .network(let s):
            return "Сборщик не отвечает — это не «книг нет».\n\(s)"
        case .badJSON:
            return "Сервер ответил не JSON — показывать нечего."
        }
    }
}

func fetchJSON(_ path: String, _ query: [String: String?] = [:]) async throws -> J {
    if Server.key.isEmpty { throw FetchError.noKey }
    guard let url = Server.url(path, query) else { throw FetchError.badJSON }
    var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData,
                         timeoutInterval: 30)
    req.setValue("Algoth-iOS", forHTTPHeaderField: "User-Agent")
    let data: Data
    let resp: URLResponse
    do {
        (data, resp) = try await URLSession.shared.data(for: req)
    } catch {
        throw FetchError.network(error.localizedDescription)
    }
    if let http = resp as? HTTPURLResponse, http.statusCode != 200 {
        throw http.statusCode == 403 ? FetchError.denied
            : FetchError.status(http.statusCode)
    }
    guard let obj = try? JSONSerialization.jsonObject(with: data) else {
        throw FetchError.badJSON
    }
    return J(obj)
}

/// Ответ сервера как есть, с терпимостью страницы: нет поля — `nil`, и
/// экран печатает прочерк, а не падает. Жёсткая схема (Codable) роняла
/// бы весь экран на первом поле, которого сервер прежнего образца не
/// пишет, — а таких в своде много, и страница их переживает.
struct J {
    let raw: Any?

    init(_ raw: Any?) { self.raw = (raw is NSNull) ? nil : raw }

    subscript(_ key: String) -> J { J((raw as? [String: Any])?[key]) }

    var isNil: Bool { raw == nil }

    private var isBool: Bool {
        guard let n = raw as? NSNumber else { return false }
        return CFGetTypeID(n) == CFBooleanGetTypeID()
    }

    var double: Double? {
        guard let n = raw as? NSNumber, !isBool else { return nil }
        return n.doubleValue
    }
    var int: Int? { double.map { Int($0) } }
    var string: String? { raw as? String }
    var array: [J] { (raw as? [Any])?.map(J.init) ?? [] }
    var keys: [String] { ((raw as? [String: Any])?.keys).map(Array.init) ?? [] }
    var isObject: Bool { raw is [String: Any] }

    /// Истинность по правилам JS: так страница читает флаги (`r.bt`).
    var truthy: Bool {
        guard let raw else { return false }
        if isBool { return (raw as? NSNumber)?.boolValue ?? false }
        if let n = raw as? NSNumber { return n.doubleValue != 0 }
        if let s = raw as? String { return !s.isEmpty }
        return true
    }

    /// Значение текстом, как его печатает страница: целое — без «.0».
    var text: String {
        if let s = string { return s }
        if let d = double {
            if d == d.rounded(), abs(d) < 1e15 { return String(Int(d)) }
            return String(d)
        }
        if isBool { return truthy ? "true" : "false" }
        return F.dash
    }
}
