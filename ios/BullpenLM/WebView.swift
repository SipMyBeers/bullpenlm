import SwiftUI
import WebKit

/// The team dashboard, full-screen, with a floating gear for settings and
/// pull-to-refresh. The web page (team.html) does the rendering; the shell
/// gives it a native home, refresh, and (later) push + mic for voice drills.
struct TeamWebScreen: View {
    let url: URL
    var onSettings: () -> Void
    @State private var reloadToken = 0
    // Defaults false in normal use; a debug hook can auto-open the ladder.
    @State private var showLadder = UserDefaults.standard.bool(forKey: "demo_open_ladder")

    var body: some View {
        ZStack(alignment: .topTrailing) {
            WebView(url: url, reloadToken: reloadToken)
                .ignoresSafeArea(edges: .bottom)
            HStack(spacing: 10) {
                circleButton("chart.bar.fill") { showLadder = true }
                circleButton("gearshape.fill", action: onSettings)
            }
            .padding(.top, 6)
            .padding(.trailing, 14)
        }
        // The native rank ladder, rendered from the shared contract — reads the
        // CONNECTED bullpen's live ladder (/promotion/<agent>), not a mock.
        .sheet(isPresented: $showLadder) {
            RankLadderView(source: HTTPPromotionSource(), agent: Config.op)
        }
    }

    @ViewBuilder private func circleButton(_ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(.bpMuted)
                .padding(10)
                .background(Color.bpPanel.opacity(0.85))
                .clipShape(Circle())
                .overlay(Circle().stroke(Color.bpText.opacity(0.12)))
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
