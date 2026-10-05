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

/// Вкладки приложения. Модель одна на все: один опрос сервера, и сводка
/// коротких книг описывает тот же ответ, что экран DCA.
struct RootTabs: View {
    @StateObject private var m = DCAModel()

    var body: some View {
        TabView {
            DCAView(m: m)
                .tabItem { Label("DCA", systemImage: "chart.line.uptrend.xyaxis") }
            ShortBooksScreen(m: m)
                .tabItem { Label("Шорты h24", systemImage: "arrow.down.right.circle") }
        }
        .tint(Theme.accent)
        .task { await m.run() }
    }
}

/// Сводка коротких книг h24 — все режимы и депозиты разом.
struct ShortBooksScreen: View {
    @ObservedObject var m: DCAModel
    @Environment(\.horizontalSizeClass) private var hsc

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let f = m.failure {
                        FailureCard(failure: f, hasData: m.data != nil,
                                    loadedAt: m.loadedAt) { Task { await m.load() } }
                    }
                    if let d = m.data {
                        ShortBooks(sh: d["short"])
                    } else if m.failure == nil {
                        HStack { Spacer(); ProgressView().tint(.white).padding(40); Spacer() }
                    }
                }
                .padding(.horizontal, hsc == .regular ? 24 : 12)
                .padding(.vertical, 12)
                .frame(maxWidth: 1500)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await m.load() }
            .background(Theme.bg.ignoresSafeArea())
            .navigationTitle("Шорты h24")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Theme.surface, for: .navigationBar)
        }
    }
}
