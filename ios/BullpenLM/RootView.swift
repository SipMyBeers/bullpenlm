import SwiftUI

struct RootView: View {
    @State private var configured = Config.isConfigured
    @State private var isDemo = Config.isDemo
    @State private var showSettings = false
    // First launch (no real bullpen yet) gets an orientation screen so the
    // operator isn't dropped cold into a wall of sample reps.
    @State private var showWelcome = !Config.seenWelcome && Config.isDemo
    /// Called once the operator has a bullpen set, to request push.
    var onConfigured: () -> Void = {}

    var body: some View {
        ZStack(alignment: .bottom) {
            Color.bpBg.ignoresSafeArea()
            // Always a working floor on cold open — real bullpen or the demo.
            if let url = Config.teamURL {
                TeamWebScreen(url: url) { showSettings = true }
            }
            if isDemo { demoBar }
        }
        .onAppear { if configured { onConfigured() } }
        .fullScreenCover(isPresented: $showWelcome) {
            WelcomeView(
                onConnect: { Config.markWelcomeSeen(); showWelcome = false
                             DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { showSettings = true } },
                onExplore: { Config.markWelcomeSeen(); showWelcome = false })
        }
        .sheet(isPresented: $showSettings) {
            SetupView {
                showSettings = false
                configured = Config.isConfigured
                isDemo = Config.isDemo
                if configured { onConfigured() }
            }
        }
    }

    // Slim bottom bar shown over the demo floor — never blocks the gear.
    private var demoBar: some View {
        Button { showSettings = true } label: {
            HStack(spacing: 10) {
                Text("DEMO DATA").font(.system(size: 10, weight: .bold, design: .monospaced))
                    .tracking(1.5).foregroundColor(.bpGold)
                Text("Sample team — tap to connect your bullpen")
                    .font(.system(size: 12.5)).foregroundColor(.bpText)
                Spacer()
                Image(systemName: "arrow.right").font(.system(size: 11, weight: .bold)).foregroundColor(.bpMuted)
            }
            .padding(.horizontal, 16).padding(.vertical, 11)
            .background(.ultraThinMaterial)
            .overlay(Rectangle().frame(height: 1).foregroundColor(.bpGold.opacity(0.3)), alignment: .top)
        }
        .buttonStyle(.plain)
    }
}

/// First-launch (and settings) form: which bullpen, and who you are.
struct SetupView: View {
    @Environment(\.dismiss) private var dismiss
    // Pre-fill the canonical floor so the operator isn't guessing a slug.
    @State private var bullpen = Config.realBullpen.isEmpty ? "default" : Config.realBullpen
    @State private var op = UserDefaults.standard.string(forKey: Config.opKey) ?? ""
    @State private var base = Config.base
    @State private var showAdvanced = false
    var onSave: () -> Void

    var body: some View {
        ZStack {
            Color.bpBg.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("BULLPEN").font(.system(size: 30, weight: .heavy)).foregroundColor(.bpGold)
                            + Text("LM").font(.system(size: 30, weight: .heavy)).foregroundColor(.bpMint)
                        Text("Connect your bullpen").font(.system(.title3, design: .serif)).italic().foregroundColor(.bpMuted)
                    }.padding(.top, 28)

                    field("BULLPEN", "your bullpen slug (e.g. default)", text: $bullpen)
                    field("YOUR NAME", "operator handle (e.g. self)", text: $op)

                    DisclosureGroup(isExpanded: $showAdvanced) {
                        field("FLOOR URL", "https://app.bullpenlm.com", text: $base)
                            .padding(.top, 8)
                    } label: {
                        Text("Advanced").font(.system(size: 11, weight: .bold, design: .monospaced))
                            .tracking(2).foregroundColor(.bpMuted)
                    }.tint(.bpMuted)

                    Button(action: saveAndGo) {
                        Text("CONNECT")
                            .font(.system(size: 13, weight: .bold, design: .monospaced)).tracking(2)
                            .foregroundColor(.bpBg).frame(maxWidth: .infinity).padding(.vertical, 15)
                            .background(canSave ? Color.bpGold : Color.bpMuted.opacity(0.4))
                            .cornerRadius(11)
                    }.disabled(!canSave)

                    Button { dismiss() } label: {
                        Text("Explore the demo instead")
                            .font(.system(size: 12.5, weight: .semibold, design: .monospaced))
                            .foregroundColor(.bpMuted).frame(maxWidth: .infinity)
                    }

                    Text("Points at the team scorecards for your bullpen. Until you connect one, the app shows a sample demo team. Change it anytime from the gear.")
                        .font(.system(size: 12, design: .serif)).foregroundColor(.bpMuted).lineSpacing(3)
                }
                .padding(22)
            }
        }
    }

    private var canSave: Bool { !bullpen.trimmingCharacters(in: .whitespaces).isEmpty }

    private func saveAndGo() {
        Config.save(bullpen: bullpen, op: op, base: base)
        onSave()
        dismiss()
    }

    private func field(_ label: String, _ placeholder: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(label).font(.system(size: 10, weight: .semibold, design: .monospaced)).tracking(2).foregroundColor(.bpMuted)
            TextField("", text: text, prompt: Text(placeholder).foregroundColor(.bpMuted.opacity(0.6)))
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .font(.system(.body, design: .serif)).foregroundColor(.bpText)
                .padding(13)
                .background(Color.black.opacity(0.3))
                .overlay(RoundedRectangle(cornerRadius: 9).stroke(Color.bpText.opacity(0.15)))
                .cornerRadius(9)
        }
    }
}
