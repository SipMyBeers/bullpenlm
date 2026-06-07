import UIKit
import UserNotifications

/// Handles remote-notification registration and routes the APNs device
/// token to the operator's floor (`POST /api/b/<bullpen>/push/register`).
/// Real delivery needs an APNs .p8 key on the host + the Push capability
/// on the App ID — see ios/TESTFLIGHT_RUNBOOK.md. Until then the server
/// stores the token and no-ops the send.
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    /// Ask once, then register for remote notifications. Safe to call on
    /// every appear — the system only prompts the first time.
    func requestAuthorization() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
            guard granted else { return }
            DispatchQueue.main.async { UIApplication.shared.registerForRemoteNotifications() }
        }
    }

    func application(_ application: UIApplication,
                     didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        PushManager.send(token: token)
    }

    func application(_ application: UIApplication,
                     didFailToRegisterForRemoteNotificationsWithError error: Error) {
        print("push: registration failed — \(error.localizedDescription)")
    }

    // Show banners while the app is foregrounded too.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}

enum PushManager {
    static func send(token: String) {
        let bullpen = Config.bullpen
        guard !bullpen.isEmpty,
              let url = URL(string: Config.base + "/api/b/\(bullpen)/push/register") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        #if DEBUG
        let env = "sandbox"
        #else
        let env = "prod"
        #endif
        let body: [String: String] = ["operator": Config.op, "token": token, "platform": "ios", "env": env]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req).resume()
    }
}
