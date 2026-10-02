import SwiftUI
import UIKit
import WebKit

/// Адрес страницы DCA для приложения.
///
/// `app=1` — уговор со страницей (`DCAPAGE` в `web.py`): по нему она
/// прячет меню соседних страниц и отдаёт логотип настройкам через
/// сообщение `algoth`. Имена проверяет `test_book.py`
/// (`test_dca_page_fits_the_tablet_and_the_app`).
func dcaPageURL(server: String, key: String) -> URL? {
    var s = server.trimmingCharacters(in: .whitespacesAndNewlines)
    if s.isEmpty || key.isEmpty { return nil }
    if !s.contains("://") { s = "http://" + s }
    guard var c = URLComponents(string: s), c.host != nil else { return nil }
    c.path = "/dca-page"
    c.queryItems = [URLQueryItem(name: "k", value: key),
                    URLQueryItem(name: "app", value: "1")]
    return c.url
}

/// Держит WKWebView и его состояние. Вид пересоздаётся SwiftUI сколько
/// угодно раз — страница при этом не перезагружается.
@MainActor
final class PageModel: NSObject, ObservableObject {
    enum Phase: Equatable {
        case loading, ready, failed(String)
    }

    @Published private(set) var phase: Phase = .loading
    var onSettings: (() -> Void)?
    let webView: WKWebView
    private var url: URL?

    override init() {
        let cfg = WKWebViewConfiguration()
        // Сервер видит приложение в строке агента — для логов, не для
        // доступа: доступ даёт только ключ.
        cfg.applicationNameForUserAgent = "AlgothDCA"
        let ucc = WKUserContentController()
        cfg.userContentController = ucc
        webView = WKWebView(frame: .zero, configuration: cfg)
        super.init()
        // Обработчик держится слабо: прямая ссылка замкнула бы модель
        // на саму себя через конфигурацию вида.
        ucc.add(WeakMessageHandler(self), name: "algoth")
        webView.navigationDelegate = self
        webView.allowsBackForwardNavigationGestures = true  // график → назад
        webView.isOpaque = false
        webView.backgroundColor = pageBackgroundUI
        webView.scrollView.backgroundColor = pageBackgroundUI
        // Вырез и полосу «домой» обходит сама страница (`env(safe-area-
        // inset-*)` при `viewport-fit=cover`); двойной отступ дал бы
        // пустую полосу.
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        let rc = UIRefreshControl()
        rc.tintColor = .white
        rc.addTarget(self, action: #selector(pulled), for: .valueChanged)
        webView.scrollView.refreshControl = rc
        if #available(iOS 16.4, *) {
            webView.isInspectable = true  // Safari → Разработка, для починки
        }
    }

    func load(_ url: URL) {
        self.url = url
        phase = .loading
        webView.load(URLRequest(url: url,
                                cachePolicy: .reloadIgnoringLocalCacheData,
                                timeoutInterval: 30))
    }

    func reload() {
        guard let url else { return }
        // После отказа в виде лежит старая страница или ничего — грузим
        // адрес заново; иначе обычная перезагрузка текущей (это может
        // быть и график, открытый со страницы).
        if case .failed = phase { load(url); return }
        if webView.url == nil { load(url); return }
        webView.reload()
    }

    @objc private func pulled() { reload() }

    fileprivate func fail(_ message: String) {
        phase = .failed(message)
        webView.scrollView.refreshControl?.endRefreshing()
    }
}

extension PageModel: WKNavigationDelegate {
    func webView(_ webView: WKWebView,
                 decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // Свой сервер — внутри приложения; чужая ссылка — в Safari, иначе
        // из неё не было бы дороги назад, кроме жеста.
        guard let target = action.request.url else {
            decisionHandler(.allow); return
        }
        if target.scheme == "about" || target.host == url?.host {
            decisionHandler(.allow); return
        }
        UIApplication.shared.open(target)
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView,
                 decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame,
           let http = response.response as? HTTPURLResponse,
           http.statusCode != 200 {
            decisionHandler(.cancel)
            if http.statusCode == 403 {
                fail("Ключ не подошёл: сервер ответил 403.\n"
                     + "Ключ лежит в out/token.txt на сервере.")
            } else {
                fail("Сервер ответил \(http.statusCode).")
            }
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        phase = .ready
        webView.scrollView.refreshControl?.endRefreshing()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!,
                 withError error: Error) {
        failed(error)
    }

    func webView(_ webView: WKWebView,
                 didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        failed(error)
    }

    private func failed(_ error: Error) {
        let e = error as NSError
        // Отменённая загрузка (новый запрос поверх старого) и отказ по
        // нашему же решению выше — не отказ сервера.
        if e.domain == NSURLErrorDomain && e.code == NSURLErrorCancelled {
            return
        }
        if e.domain == "WebKitErrorDomain" && e.code == 102 { return }
        if case .failed = phase { return }  // слова 403 не затирать
        fail("Сервер не отвечает.\n\(e.localizedDescription)")
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        // iOS убивает процесс страницы под нехваткой памяти — без
        // перезагрузки остался бы пустой экран.
        reload()
    }
}

extension PageModel: WKScriptMessageHandler {
    func userContentController(_ ucc: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        if message.name == "algoth", message.body as? String == "settings" {
            onSettings?()
        }
    }
}

private final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ ucc: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        target?.userContentController(ucc, didReceive: message)
    }
}

struct WebContainer: UIViewRepresentable {
    let model: PageModel
    func makeUIView(context: Context) -> WKWebView { model.webView }
    func updateUIView(_ view: WKWebView, context: Context) {}
}
