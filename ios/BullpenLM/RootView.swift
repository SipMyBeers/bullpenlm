import SwiftUI

struct RootView: View {
    @State private var configured = Config.isConfigured
    @State private var showSettings = false
    /// Called once the operator has a bullpen set, to request push.
    var onConfigured: () -> Void = {}

    var body: some View {
        ZStack {
            Color.bpBg.ignoresSafeArea()
            if configured, let url = Config.teamURL {
                TeamWebScreen(url: url) { showSettings = true }
            } else {
                SetupView { configured = Config.isConfigured; if configured { onConfigured() } }
            }
        }
        .onAppear { if configured { onConfigured() } }
        .sheet(isPresented: $showSettings) {
            SetupView {
                showSettings = false
                configured = Config.isConfigured
                if configured { onConfigured() }
            }
        }
    }
}

/// First-launch (and settings) form: which bullpen, and who you are.
struct SetupView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var bullpen = Config.bullpen
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
                        Text("Track your team").font(.system(.title3, design: .serif)).italic().foregroundColor(.bpMuted)
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
                        Text("OPEN THE FLOOR")
                            .font(.system(size: 13, weight: .bold, design: .monospaced)).tracking(2)
                            .foregroundColor(.bpBg).frame(maxWidth: .infinity).padding(.vertical, 15)
                            .background(canSave ? Color.bpGold : Color.bpMuted.opacity(0.4))
                            .cornerRadius(11)
                    }.disabled(!canSave)

                    Text("Points at the team scorecards for your bullpen. Change it anytime from the gear.")
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
