import SwiftUI

@main
struct BullpenLMApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    var body: some Scene {
        WindowGroup {
            RootView(onConfigured: { appDelegate.requestAuthorization() })
                .preferredColorScheme(.dark)
        }
    }
}

/// Where the operator's bullpen lives. v1 wraps the mobile team dashboard
/// (floor/app/team.html) served off the floor; the native shell just stores
/// which bullpen + identity to point at and renders it in a WKWebView.
enum Config {
    private static let d = UserDefaults.standard
    static let baseKey = "bp_base", bullpenKey = "bp_bullpen", opKey = "bp_operator"

    static var base: String { d.string(forKey: baseKey) ?? "https://app.bullpenlm.com" }
    static var bullpen: String { d.string(forKey: bullpenKey) ?? "" }
    static var op: String { let v = d.string(forKey: opKey) ?? ""; return v.isEmpty ? "self" : v }
    static var isConfigured: Bool { !bullpen.isEmpty }

    static func save(bullpen: String, op: String, base: String) {
        d.set(bullpen.trimmingCharacters(in: .whitespaces).lowercased(), forKey: bullpenKey)
        d.set(op.trimmingCharacters(in: .whitespaces), forKey: opKey)
        let b = base.trimmingCharacters(in: .whitespaces)
        d.set(b.isEmpty ? "https://app.bullpenlm.com" : b, forKey: baseKey)
    }

    static var teamURL: URL? {
        guard !bullpen.isEmpty, var c = URLComponents(string: base + "/app/team.html") else { return nil }
        c.queryItems = [URLQueryItem(name: "b", value: bullpen),
                        URLQueryItem(name: "rep", value: op)]
        return c.url
    }
}

// Brand palette (matches the floor: dark + gold + mint).
extension Color {
    static let bpBg    = Color(red: 0.039, green: 0.027, blue: 0.012)
    static let bpPanel = Color(red: 0.102, green: 0.071, blue: 0.031)
    static let bpGold  = Color(red: 0.984, green: 0.749, blue: 0.141)
    static let bpMint  = Color(red: 0.204, green: 0.827, blue: 0.600)
    static let bpText  = Color(red: 0.961, green: 0.910, blue: 0.847)
    static let bpMuted = Color(red: 0.659, green: 0.604, blue: 0.529)
}
