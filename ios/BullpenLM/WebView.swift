import SwiftUI
import WebKit

/// The team dashboard, full-screen, with a floating gear for settings and
/// pull-to-refresh. The web page (team.html) does the rendering; the shell
/// gives it a native home, refresh, and (later) push + mic for voice drills.
struct TeamWebScreen: View {
    let url: URL
    var onSettings: () -> Void
    @State private var reloadToken = 0

    var body: some View {
        ZStack(alignment: .topTrailing) {
            WebView(url: url, reloadToken: reloadToken)
                .ignoresSafeArea(edges: .bottom)
            Button(action: onSettings) {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(.bpMuted)
                    .padding(10)
                    .background(Color.bpPanel.opacity(0.85))
                    .clipShape(Circle())
                    .overlay(Circle().stroke(Color.bpText.opacity(0.12)))
            }
            .padding(.top, 6)
            .padding(.trailing, 14)
        }
    }
}

struct WebView: UIViewRepresentable {
    let url: URL
    var reloadToken: Int

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.allowsInlineMediaPlayback = true
        cfg.mediaTypesRequiringUserActionForPlayback = []   // voice drills can start audio
        let web = WKWebView(frame: .zero, configuration: cfg)
        web.isOpaque = false
        web.backgroundColor = UIColor(red: 0.039, green: 0.027, blue: 0.012, alpha: 1)
        web.scrollView.backgroundColor = .clear
        web.scrollView.contentInsetAdjustmentBehavior = .never

        let rc = UIRefreshControl()
        rc.tintColor = UIColor(red: 0.984, green: 0.749, blue: 0.141, alpha: 1)
        rc.addTarget(context.coordinator, action: #selector(Coordinator.refresh(_:)), for: .valueChanged)
        context.coordinator.web = web
        web.scrollView.refreshControl = rc

        web.load(URLRequest(url: url))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        if context.coordinator.lastToken != reloadToken {
            context.coordinator.lastToken = reloadToken
            web.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject {
        weak var web: WKWebView?
        var lastToken = 0
        @objc func refresh(_ sender: UIRefreshControl) {
            web?.reload()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { sender.endRefreshing() }
        }
    }
}
