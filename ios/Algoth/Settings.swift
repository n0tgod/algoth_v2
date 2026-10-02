import Foundation
import Security
import SwiftUI

/// Адрес сервера и ключ страницы.
///
/// Ключ — в связке ключей устройства, а не в настройках и не в коде:
/// в git он не идёт никогда (`CLAUDE.md`), и в сборку тоже.
final class AppSettings: ObservableObject {
    static let defaultServer = "http://116.203.146.99"

    @Published private(set) var server: String
    @Published private(set) var key: String

    init() {
        server = UserDefaults.standard.string(forKey: "server")
            ?? Self.defaultServer
        key = Keychain.read("page-key") ?? ""
    }

    /// Есть ли с чем идти на сервер: адрес разбирается и ключ не пуст.
    var isConfigured: Bool { url(for: "/") != nil }

    func url(for path: String) -> URL? {
        pageURL(server: server, key: key, path: path)
    }

    func save(server: String, key: String) {
        let s = server.trimmingCharacters(in: .whitespacesAndNewlines)
        let k = key.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(s, forKey: "server")
        Keychain.write(k, for: "page-key")
        self.server = s
        self.key = k
    }
}

enum Keychain {
    private static let service = "algoth"

    private static func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    static func read(_ account: String) -> String? {
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func write(_ value: String, for account: String) {
        SecItemDelete(query(account) as CFDictionary)
        guard !value.isEmpty else { return }
        var q = query(account)
        q[kSecValueData as String] = Data(value.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(q as CFDictionary, nil)
    }
}

struct SettingsView: View {
    let firstRun: Bool
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    @State private var server = ""
    @State private var key = ""

    var body: some View {
        Form {
            Section {
                TextField("http://адрес", text: $server)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } header: {
                Text("Сервер")
            }
            Section {
                SecureField("ключ страницы", text: $key)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } header: {
                Text("Ключ")
            } footer: {
                Text("Тот же ключ, что в адресе страниц после ?k=. "
                     + "Хранится в связке ключей этого устройства.")
            }
            Section {
                Button("Сохранить и открыть") {
                    settings.save(server: server, key: key)
                    if !firstRun { dismiss() }
                }
                .disabled(pageURL(server: server, key: key, path: "/") == nil)
            }
        }
        .navigationTitle(firstRun ? "Algoth" : "Настройки")
        .toolbar {
            if !firstRun {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Закрыть") { dismiss() }
                }
            }
        }
        .onAppear {
            server = settings.server
            key = settings.key
        }
    }
}
