import SwiftUI

/// First-run onboarding — an explanation of what the app is, then a question
/// (have you set up a bullpen before?) that routes the operator to connect their
/// own bullpen, or to a short "how it works" if it's their first time. No demo /
/// example bullpen; an unconnected app shows this.
struct OnboardView: View {
    var onConnect: () -> Void
    @State private var step = 0
    @Environment(\.openURL) private var openURL

    var body: some View {
        ZStack {
            Color.bpBg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                Spacer()
                climb.frame(width: 52, height: 52).padding(.bottom, 22)
                Group {
                    switch step {
                    case 0: explain
                    case 1: question
                    default: firstTime
                    }
                }
                Spacer()
                Text("BULLPENLM")
                    .font(.system(size: 11, weight: .bold, design: .rounded)).tracking(2)
                    .foregroundColor(.bpGold).frame(maxWidth: .infinity)
            }
            .padding(.horizontal, 28)
            .animation(.easeInOut(duration: 0.2), value: step)
        }
    }

    // 0 — explanation
    private var explain: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Track your bullpen.")
                .font(.system(size: 33, weight: .bold, design: .serif)).foregroundColor(.bpText)
            Text("BullpenLM shows you every rep on your sales team — their rank, drills, closes, and what's blocking their next promotion. Your bullpen runs on a host, your reps join with a link, and you track them from here.")
                .font(.system(size: 15.5)).foregroundColor(.bpMuted).lineSpacing(4)
            primary("NEXT") { step = 1 }.padding(.top, 18)
        }
    }

    // 1 — the question
    private var question: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Have you set up a\nbullpen before?")
                .font(.system(size: 29, weight: .bold, design: .serif)).foregroundColor(.bpText).lineSpacing(2)
            Text("If you've already got one running, connect it. If not, it takes a minute to start.")
                .font(.system(size: 15)).foregroundColor(.bpMuted).lineSpacing(4)
            primary("YES — CONNECT MINE") { onConnect() }.padding(.top, 14)
            secondary("No — this is my first") { step = 2 }
        }
    }

    // 2 — first-timer how-it-works
    private var firstTime: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Here's how it works.")
                .font(.system(size: 29, weight: .bold, design: .serif)).foregroundColor(.bpText)
            point("1", "A bullpen runs on a host computer — start one at bullpenlm.com.")
            point("2", "Your reps join with an invite link and start drilling.")
            point("3", "You track them here — ranks, closes, and promotions.")
            primary("OPEN bullpenlm.com") { openURL(URL(string: "https://bullpenlm.com")!) }.padding(.top, 10)
            secondary("I already have one — connect it") { onConnect() }
        }
    }

    private func primary(_ t: String, _ a: @escaping () -> Void) -> some View {
        Button(action: a) {
            Text(t).font(.system(size: 13, weight: .bold, design: .rounded)).tracking(1.4)
                .foregroundColor(.bpBg).frame(maxWidth: .infinity).padding(.vertical, 16)
                .background(Color.bpGold).cornerRadius(13)
        }
    }
    private func secondary(_ t: String, _ a: @escaping () -> Void) -> some View {
        Button(action: a) {
            Text(t).font(.system(size: 14, weight: .semibold)).foregroundColor(.bpMuted)
                .frame(maxWidth: .infinity).padding(.vertical, 8)
        }
    }
    private func point(_ n: String, _ t: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(n).font(.system(size: 13, weight: .bold, design: .rounded)).foregroundColor(.bpBg)
                .frame(width: 26, height: 26).background(Color.bpGold).clipShape(Circle())
            Text(t).font(.system(size: 15)).foregroundColor(.bpText).lineSpacing(3)
        }
    }

    // The Climb mark
    private var climb: some View {
        GeometryReader { g in
            let w = g.size.width, h = g.size.height
            Path { p in
                for (inset, y) in [(0.20, 0.86), (0.30, 0.62), (0.40, 0.40)] as [(CGFloat, CGFloat)] {
                    p.move(to: CGPoint(x: w * inset, y: h * y))
                    p.addLine(to: CGPoint(x: w * (1 - inset), y: h * y))
                }
            }.stroke(Color.bpGold, style: StrokeStyle(lineWidth: 7, lineCap: .round))
            Path { p in
                p.move(to: CGPoint(x: w * 0.46, y: h * 0.18))
                p.addLine(to: CGPoint(x: w * 0.54, y: h * 0.18))
            }.stroke(Color.bpText, style: StrokeStyle(lineWidth: 7, lineCap: .round))
        }
    }
}
