import SwiftUI

// Приложение Algoth для iPhone и iPad.
//
// Разделы — страницы сервера наблюдения (сборщик B1, `research/b1_book/
// web.py`), открытые в `WKWebView`. Страницы в приложение НЕ копируются:
// их код один, и правка страницы видна в приложении после деплоя, без
// новой сборки. Вторая копия показа однажды разошлась бы с кассой —
// урок «одно ядро». Приложение добавляет то, чего у вкладки браузера
// нет: ключ в связке ключей, потяни-обнови, отказ словами вместо белого
// экрана, безопасные зоны iPhone и сетку iPad (последние — правилами
// самой страницы под `app=1`).
@main
struct AlgothApp: App {
    @StateObject private var settings = AppSettings()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(settings)
                .preferredColorScheme(.dark)
        }
    }
}

/// Раздел приложения — страница сервера.
///
/// Новый раздел — одна строка в `AppSection.all`. Странице, чтобы жить в
/// приложении удобно, нужно то же, что сделано у DCA: правила под `app=1`
/// (без меню соседних страниц, логотип зовёт `algoth` → настройки),
/// безопасные зоны и раскладка под сенсорный экран.
struct AppSection: Identifiable, Hashable {
    let id: String
    let title: String
    let symbol: String   // SF Symbol для вкладки
    let path: String     // путь страницы на сервере

    static let all: [AppSection] = [
        AppSection(id: "dca", title: "DCA", symbol: "chart.bar.xaxis",
                   path: "/dca-page"),
    ]
}

/// Фон страниц (`--bg` в DCAPAGE): тот же цвет под вырезом, при загрузке
/// и за краем прокрутки, — иначе мелькает белое.
let pageBackground = Color(red: 8 / 255, green: 10 / 255, blue: 15 / 255)
let pageBackgroundUI = UIColor(red: 8 / 255, green: 10 / 255, blue: 15 / 255,
                               alpha: 1)

struct RootView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var showSettings = false

    var body: some View {
        ZStack {
            pageBackground.ignoresSafeArea()
            if settings.isConfigured {
                sections
            } else {
                // Первый запуск: без ключа сервер отвечает 403, и
                // открывать страницы незачем — сразу форма.
                NavigationStack { SettingsView(firstRun: true) }
            }
        }
        .sheet(isPresented: $showSettings) {
            NavigationStack { SettingsView(firstRun: false) }
        }
    }

    // Один раздел — без панели вкладок: панель из одной кнопки только
    // съедает экран. Со вторым разделом появляется сама.
    @ViewBuilder private var sections: some View {
        let all = AppSection.all
        if all.count == 1, let only = all.first {
            SectionView(section: only, openSettings: { showSettings = true })
        } else {
            TabView {
                ForEach(all) { s in
                    SectionView(section: s,
                                openSettings: { showSettings = true })
                        .tabItem { Label(s.title, systemImage: s.symbol) }
                }
            }
        }
    }
}

/// Одна страница со своим `WKWebView`: у каждого раздела своя прокрутка
/// и своя история «назад», переключение вкладок их не сбрасывает.
struct SectionView: View {
    let section: AppSection
    var openSettings: () -> Void
    @EnvironmentObject private var settings: AppSettings
    @StateObject private var page = PageModel()
    @State private var wentAway: Date?
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let url = settings.url(for: section.path)
        ZStack {
            WebContainer(model: page)
                .ignoresSafeArea()
            PhaseOverlay(model: page, openSettings: openSettings)
        }
        .onAppear {
            page.onSettings = openSettings
            if let url, page.loadedURL != url { page.load(url) }
        }
        .onChange(of: url) { new in
            if let new { page.load(new) }
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
