import Foundation
import SwiftUI

/// Форматы чисел — ТЕ ЖЕ, что у страницы DCA (`usd`, `fpct`/`pct`,
/// `tsq`, `qtyf`, `toPrecision(6)` в `web.py`). Две разные записи одного
/// числа в приложении и в браузере читались бы как два разных числа.
enum F {
    static let dash = "—"

    /// Деньги со знаком: «+12.34 $».
    static func usd(_ v: Double?) -> String {
        guard let v else { return dash }
        return (v > 0 ? "+" : "") + String(format: "%.2f", v) + " $"
    }

    /// Доля (0.0684) процентами со знаком: «+6.84 %»; мелкая — три знака.
    /// Это `pct(v · 1e4)` страницы: порог разрядов считается в б.п.
    static func fpct(_ v: Double?) -> String {
        guard let v else { return dash }
        let bp = v * 1e4
        let d = abs(bp) >= 10 ? 2 : 3
        return (bp > 0 ? "+" : "") + String(format: "%.\(d)f", bp / 100) + " %"
    }

    /// Доля процентами без порога разрядов (сводка коротких книг).
    static func pc(_ v: Double?, _ d: Int = 2) -> String {
        guard let v else { return dash }
        let x = 100 * v
        return (x >= 0 ? "+" : "") + String(format: "%.\(d)f", x) + " %"
    }

    /// Деньги без значка доллара, со знаком (сводка коротких книг).
    static func us(_ v: Double?) -> String {
        guard let v else { return dash }
        return (v >= 0 ? "+" : "") + String(format: "%.2f", v)
    }

    static func fixed(_ v: Double?, _ d: Int, suffix: String = "") -> String {
        guard let v else { return dash }
        return String(format: "%.\(d)f", v) + suffix
    }

    /// Цена: шесть значащих, как `toPrecision(6)`.
    static func px(_ v: Double?) -> String {
        guard let v else { return dash }
        return String(format: "%#.6g", v)
    }

    /// Контракты: масштаб от 0.0003 BTC до миллионов PEPE (`qtyf`).
    static func qty(_ v: Double?) -> String {
        guard let x = v, x.isFinite else { return dash }
        let a = abs(x)
        if a >= 1e6 { return String(format: "%.2f M", x / 1e6) }
        if a >= 1000 {
            let s = String(Int(x.rounded()))
            return groupThousands(s, sep: " ")
        }
        if a >= 1 { return String(format: "%.2f", x) }
        return String(format: "%#.3g", x)
    }

    /// «$10,000» — как `toLocaleString("en-US")` страницы.
    static func dollars(_ v: Double?) -> String {
        guard let v else { return dash }
        let nf = NumberFormatter()
        nf.locale = Locale(identifier: "en_US")
        nf.numberStyle = .decimal
        nf.maximumFractionDigits = 2
        return "$" + (nf.string(from: NSNumber(value: v)) ?? String(v))
    }

    private static func groupThousands(_ s: String, sep: String) -> String {
        var digits = s
        var sign = ""
        if digits.hasPrefix("-") { sign = "-"; digits.removeFirst() }
        var out = ""
        for (i, ch) in digits.reversed().enumerated() {
            if i > 0 && i % 3 == 0 { out.append(sep) }
            out.append(ch)
        }
        return sign + String(out.reversed())
    }

    private static let utc: TimeZone = TimeZone(identifier: "UTC")!

    private static func fmt(_ pattern: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = utc
        f.dateFormat = pattern
        return f
    }
    private static let tsqF = fmt("yyyy-MM-dd HH:mm")
    private static let hhmmF = fmt("HH:mm")
    private static let hourF = fmt("yyyy-MM-dd-HH")
    private static let mdF = fmt("MM-dd")

    /// Полная дата UTC: «08-09» владелец прочёл как 8 сентября.
    static func tsq(_ t: Double?) -> String {
        guard let t else { return dash }
        return tsqF.string(from: Date(timeIntervalSince1970: t))
    }
    static func hhmm(_ t: Double?) -> String {
        guard let t, t > 0 else { return "" }
        return hhmmF.string(from: Date(timeIntervalSince1970: t)) + " UTC"
    }
    static func monthDay(_ t: Double) -> String {
        mdF.string(from: Date(timeIntervalSince1970: t))
    }
    /// Ключ часа графика — тот же формат, что у книг модели.
    static func hourKey(_ t: Double) -> String {
        hourF.string(from: Date(timeIntervalSince1970: t))
    }
}

/// Тон числа — из его знака (`cls` страницы).
enum Tone {
    case good, bad, plain

    init(_ v: Double?) {
        guard let v else { self = .plain; return }
        self = v > 0 ? .good : (v < 0 ? .bad : .plain)
    }

    var color: Color {
        switch self {
        case .good: return Theme.bid
        case .bad: return Theme.ask
        case .plain: return Theme.ink
        }
    }
}
