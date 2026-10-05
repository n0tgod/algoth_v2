import SwiftUI
import UIKit

/// Лёгкий отклик на нажатие кнопки или переключателя — один на всё
/// приложение. На iPad без вибромотора молчит сам.
@MainActor
enum Haptic {
    private static let gen = UIImpactFeedbackGenerator(style: .light)
    static func tap() {
        gen.impactOccurred(intensity: 0.7)
        gen.prepare()
    }
}

/// Палитра страницы DCA (макеты владельца): тот же фон, карточки, неон.
enum Theme {
    static let bg = Color(hex: 0x080a0f)
    static let surface = Color(hex: 0x0d1117)
    static let panel = Color(hex: 0x121721)
    static let chip = Color(hex: 0x161c27)
    static let ink = Color(hex: 0xe1e7f5)
    static let muted = Color(hex: 0x9aa5be)
    static let dim = Color(hex: 0x7a8599)
    static let bid = Color(hex: 0x00f59b)
    static let ask = Color(hex: 0xff4969)
    static let accent = Color(hex: 0x6366f1)
    static let rule = Color.white.opacity(0.08)

    static let mono = Font.system(.body, design: .monospaced)
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xff) / 255,
                  green: Double((hex >> 8) & 0xff) / 255,
                  blue: Double(hex & 0xff) / 255)
    }
}

/// Панель раздела.
struct Panel<Content: View>: View {
    var alarm = false
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(alarm ? Color(hex: 0x1a1318) : Theme.panel)
            .overlay(RoundedRectangle(cornerRadius: 16)
                .stroke(alarm ? Theme.ask.opacity(0.35) : Theme.rule))
            .clipShape(RoundedRectangle(cornerRadius: 16))
    }
}

/// Заголовок раздела: точка + название заглавными.
struct Cap: View {
    let text: String
    var tone: Tone = .plain
    var dot = true

    var body: some View {
        HStack(spacing: 8) {
            if dot {
                Circle()
                    .fill(tone == .plain ? Theme.accent : tone.color)
                    .frame(width: 8, height: 8)
                    .shadow(color: tone == .plain ? Theme.accent : tone.color,
                            radius: 4)
            }
            Text(text.uppercased())
                .font(.system(size: 11, weight: .medium))
                .tracking(1.2)
                .foregroundStyle(Theme.muted)
        }
    }
}

/// Плитка «подпись — значение». Тон плитки — из знака её же числа.
struct Tile: View {
    let label: String
    let value: String
    var tone: Tone = .plain
    var big = false
    var note: String? = nil
    var tinted = false

    var body: some View {
        VStack(alignment: big ? .center : .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(Theme.muted)
                .lineLimit(2)
                .multilineTextAlignment(big ? .center : .leading)
            Text(value)
                .font(.system(size: big ? 24 : 16, weight: big ? .heavy : .bold,
                              design: .monospaced))
                .foregroundStyle(tone.color)
                .shadow(color: big && tone != .plain ? tone.color.opacity(0.45)
                        : .clear, radius: 8)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
            if let note, !note.isEmpty {
                Text(note).font(.system(size: 10)).foregroundStyle(Theme.dim)
                    .lineLimit(2)
            }
        }
        .padding(big ? 14 : 10)
        .frame(maxWidth: .infinity, minHeight: big ? 92 : 64,
               alignment: big ? .center : .leading)
        .background(background)
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(border))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private var background: some ShapeStyle {
        guard tinted else { return AnyShapeStyle(Theme.chip) }
        switch tone {
        case .good:
            return AnyShapeStyle(LinearGradient(
                colors: [Color(hex: 0x15231e), Color(hex: 0x101917)],
                startPoint: .top, endPoint: .bottom))
        case .bad: return AnyShapeStyle(Color(hex: 0x1a1318))
        case .plain: return AnyShapeStyle(Theme.chip)
        }
    }

    private var border: Color {
        guard tinted else { return Theme.rule }
        switch tone {
        case .good: return Color(hex: 0x10b981).opacity(0.30)
        case .bad: return Theme.ask.opacity(0.20)
        case .plain: return Theme.rule
        }
    }
}

/// Чип выбора (режим, депозит, группа, состояние).
struct Chip: View {
    let title: String
    var count: String? = nil
    let on: Bool
    /// Растянуть чип на ширину своей доли ряда (режимы — тремя равными).
    var fill = false
    let action: () -> Void

    var body: some View {
        Button { Haptic.tap(); action() } label: {
            HStack(spacing: 6) {
                Text(title).lineLimit(1).minimumScaleFactor(0.75)
                if let count {
                    Text(count).foregroundStyle(on ? Color.white.opacity(0.7)
                                                   : Theme.dim)
                }
            }
            .font(.system(size: 13, weight: on ? .semibold : .regular))
            .foregroundStyle(on ? Color.white : Theme.muted)
            .frame(maxWidth: fill ? .infinity : nil)
            .padding(.horizontal, fill ? 8 : 14)
            .padding(.vertical, 8)
            .background(on ? Color(hex: 0x4f46e5).opacity(0.25)
                        : Color.white.opacity(0.03))
            .overlay(RoundedRectangle(cornerRadius: 12)
                .stroke(on ? Theme.accent.opacity(0.6) : Theme.rule))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
    }
}

/// Пометка (бэктест, по котировке, отметка).
struct Tag: View {
    let text: String
    var accent = false

    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 9, weight: .semibold))
            .tracking(0.8)
            .foregroundStyle(accent ? Color(hex: 0xa5b4fc) : Theme.muted)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .overlay(RoundedRectangle(cornerRadius: 6)
                .stroke(accent ? Theme.accent.opacity(0.45) : Theme.rule))
    }
}

/// Фишка состояния позиции.
struct Pill: View {
    let text: String
    var tone: Tone = .plain
    var accent = false

    var body: some View {
        Text(text)
            .font(.system(size: 11))
            .foregroundStyle(accent ? Color(hex: 0xa5b4fc)
                             : (tone == .plain ? Theme.ink : tone.color))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(accent ? Theme.accent.opacity(0.12)
                        : (tone == .plain ? Color.white.opacity(0.03)
                           : tone.color.opacity(0.08)))
            .overlay(RoundedRectangle(cornerRadius: 8)
                .stroke(accent ? Theme.accent.opacity(0.45)
                        : (tone == .plain ? Theme.rule
                           : tone.color.opacity(0.30))))
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

/// Сторона позиции фишкой у монеты. Нет поля — нет фишки.
struct SideChip: View {
    let side: String?

    var body: some View {
        if side == "long" || side == "short" {
            let short = side == "short"
            Text(short ? "S" : "L")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(short ? Theme.ask : Theme.bid)
                .padding(.horizontal, 5)
                .padding(.vertical, 3)
                .background((short ? Theme.ask : Theme.bid).opacity(0.13))
                .clipShape(RoundedRectangle(cornerRadius: 4))
        }
    }
}

/// Строка «подпись — значение» внутри карточки.
struct KV: View {
    let label: String
    let value: String
    var tone: Tone = .plain

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label).font(.system(size: 11)).foregroundStyle(Theme.dim)
            Spacer(minLength: 4)
            Text(value).font(.system(size: 13, design: .monospaced))
                .foregroundStyle(tone.color)
                .multilineTextAlignment(.trailing)
        }
    }
}

/// Пояснение мелким текстом.
struct Note: View {
    let text: String
    var tone: Tone = .plain

    var body: some View {
        Text(text)
            .font(.system(size: 12))
            .foregroundStyle(tone == .plain ? Theme.muted : tone.color)
            .fixedSize(horizontal: false, vertical: true)
    }
}
