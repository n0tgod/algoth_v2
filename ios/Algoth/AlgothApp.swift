import SwiftUI

// Приложение Algoth для iPhone и iPad.
//
// Экраны РОДНЫЕ (SwiftUI), а не страница в браузере: данные берутся из
// тех же ответов сервера наблюдения, что кормят страницы
// (`research/b1_book/web.py`: `/dca`, `/dca_marks`). Деньги считает
// сервер — экран только печатает пришедшее, своей арифметики денег у
// него нет (правило роли «дизайн»: вторая формула однажды разойдётся с
// кассой). Начинаем с DCA; следующий экран встанет вкладкой рядом.
@main
struct AlgothApp: App {
    var body: some Scene {
        WindowGroup {
            RootTabs()
                .preferredColorScheme(.dark)
        }
    }
}

/// Вкладки приложения. Модель одна на все: один опрос сервера, и рейтинг
/// описывает тот же ответ, что экран DCA.
struct RootTabs: View {
    @StateObject private var m = DCAModel()
    @State private var tab = "dca"

    var body: some View {
        TabView(selection: $tab) {
            DCAView(m: m)
                .tabItem { Label("DCA", systemImage: "chart.line.uptrend.xyaxis") }
                .tag("dca")
            RatingScreen(m: m) { rul, dep in
                // Строка рейтинга открывает свою книгу на экране DCA.
                m.dep = dep
                m.setRuler(rul)
                tab = "dca"
            }
            .tabItem { Label("Рейтинг", systemImage: "list.number") }
            .tag("rating")
        }
        .tint(Theme.accent)
        .task { await m.run() }
    }
}
