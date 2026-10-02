import SwiftUI

// Приложение-оболочка страницы DCA (`/dca-page` сборщика B1).
//
// Страница НЕ копируется в приложение: её код один и живёт в
// `research/b1_book/web.py`, приложение открывает её с сервера. Вторая
// копия показа однажды разошлась бы с кассой — урок «одно ядро».
// Приложение добавляет то, чего у вкладки браузера нет: ключ в связке
// ключей вместо адресной строки, потяни-обнови, отказ словами вместо
// белого экрана, безопасные зоны iPhone и сетку карточек iPad
// (последние две — правилами самой страницы под `app=1`).
@main
struct AlgothDCAApp: App {
    @StateObject private var settings = AppSettings()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(settings)
                .preferredColorScheme(.dark)
        }
    }
}

/// Фон страницы (`--bg` в DCAPAGE): тот же цвет под вырезом, при
/// загрузке и за краем прокрутки, — иначе мелькает белое.
let pageBackground = Color(red: 8 / 255, green: 10 / 255, blue: 15 / 255)
let pageBackgroundUI = UIColor(red: 8 / 255, green: 10 / 255, blue: 15 / 255,
                               alpha: 1)

struct RootView: View {
    @EnvironmentObject private var settings: AppSettings
    @StateObject private var page = PageModel()
    @State private var showSettings = false
    @State private var wentAway: Date?
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            pageBackground.ignoresSafeArea()
            if let url = settings.pageURL {
                WebContainer(model: page)
                    .ignoresSafeArea()
                    .onAppear {
                        page.onSettings = { showSettings = true }
                        page.load(url)
                    }
                    .onChange(of: url) { page.load($0) }
                PhaseOverlay(model: page,
                             openSettings: { showSettings = true })
            } else {
                // Первый запуск: без ключа сервер отвечает 403, и
                // открывать страницу незачем — сразу форма.
                NavigationStack { SettingsView(firstRun: true) }
            }
        }
        .sheet(isPresented: $showSettings) {
            NavigationStack { SettingsView(firstRun: false) }
        }
        // Страница опрашивает сервер сама, но в фоне iOS её таймеры
        // останавливает. После долгого отсутствия — полная перезагрузка,
        // чтобы не показывать числа часовой давности как свежие.
        .onChange(of: scenePhase) { phase in
            switch phase {
            case .background:
                wentAway = Date()
            case .active:
                if let t = wentAway, Date().timeIntervalSince(t) > 300 {
                    page.reload()
                }
                wentAway = nil
            default:
                break
            }
        }
    }
}

/// Загрузка и отказ поверх страницы. Отказ обязан быть виден словами:
/// белый или пустой экран неотличим от «сервер молчит».
struct PhaseOverlay: View {
    @ObservedObject var model: PageModel
    var openSettings: () -> Void

    var body: some View {
        switch model.phase {
        case .ready:
            EmptyView()
        case .loading:
            ProgressView().tint(.white).controlSize(.large)
        case .failed(let message):
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 40))
                    .foregroundStyle(Color(red: 1, green: 0.286, blue: 0.412))
                Text(message)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 24)
                HStack(spacing: 12) {
                    Button("Повторить") { model.reload() }
                        .buttonStyle(.borderedProminent)
                    Button("Настройки", action: openSettings)
                        .buttonStyle(.bordered)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(pageBackground.ignoresSafeArea())
        }
    }
}
