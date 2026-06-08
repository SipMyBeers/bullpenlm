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
    static let seenWelcomeKey = "bp_seen_welcome"

    static var seenWelcome: Bool { d.bool(forKey: seenWelcomeKey) }
    static func markWelcomeSeen() { d.set(true, forKey: seenWelcomeKey) }

    static let demoBullpen = "demo"

    static var base: String { d.string(forKey: baseKey) ?? "https://app.bullpenlm.com" }
    /// The operator's own bullpen, if they've connected one.
    static var realBullpen: String { d.string(forKey: bullpenKey) ?? "" }
    /// What the app actually shows — the real bullpen, or the demo floor so a
    /// cold open ALWAYS lands on a working app (App Store Guideline 4.2).
    static var bullpen: String { realBullpen.isEmpty ? demoBullpen : realBullpen }
    static var op: String { let v = d.string(forKey: opKey) ?? ""; return v.isEmpty ? "self" : v }
    static var isDemo: Bool { realBullpen.isEmpty }
    static var isConfigured: Bool { !realBullpen.isEmpty }   // gates push, not the floor

    static func save(bullpen: String, op: String, base: String) {
        d.set(bullpen.trimmingCharacters(in: .whitespaces).lowercased(), forKey: bullpenKey)
        d.set(op.trimmingCharacters(in: .whitespaces), forKey: opKey)
        let b = base.trimmingCharacters(in: .whitespaces)
        d.set(b.isEmpty ? "https://app.bullpenlm.com" : b, forKey: baseKey)
    }

    /// Always resolvable now — falls back to the demo floor.
    static var teamURL: URL? {
        guard var c = URLComponents(string: base + "/app/team.html") else { return nil }
        c.queryItems = [URLQueryItem(name: "b", value: bullpen),
                        URLQueryItem(name: "rep", value: op)]
        return c.url
    }
}

// Brand palette — Clubhouse scheme: near-black + warm cream + one gold,
// refined sage green for "done/online" semantics.
extension Color {
    static let bpBg    = Color(red: 0.063, green: 0.059, blue: 0.051)  // #100f0d
    static let bpPanel = Color(red: 0.106, green: 0.098, blue: 0.086)  // #1b1916
    static let bpGold  = Color(red: 0.847, green: 0.631, blue: 0.227)  // #d8a13a
    static let bpMint  = Color(red: 0.435, green: 0.702, blue: 0.541)  // sage #6fb38a
    static let bpText  = Color(red: 0.937, green: 0.914, blue: 0.867)  // #efe9dd
    static let bpMuted = Color(red: 0.647, green: 0.612, blue: 0.549)  // #a59c8c
}
