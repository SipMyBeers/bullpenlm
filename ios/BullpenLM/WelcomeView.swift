import SwiftUI

/// First-launch orientation so a new operator isn't dropped cold into a wall of
/// sample reps. Explains what the app is and routes them to THEIR bullpen (or a
/// clearly-labeled sample). Shown once.
struct WelcomeView: View {
    var onConnect: () -> Void
    var onExplore: () -> Void

    var body: some View {
        ZStack {
            Color.bpBg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                Spacer()

                // The Climb mark
                climb.frame(width: 56, height: 56).padding(.bottom, 22)

                Text("Your sales floor,\nin your pocket.")
                    .font(.system(size: 34, weight: .bold, design: .serif))
                    .foregroundColor(.bpText).lineSpacing(2)
                    .padding(.bottom, 14)

                Text("Track every rep on your bullpen — rank, drills, closes, and what's blocking their next promotion — at a glance, with a buzz when someone closes.")
                    .font(.system(size: 15.5)).foregroundColor(.bpMuted).lineSpacing(4)
                    .padding(.bottom, 34)

                Button(action: onConnect) {
                    Text("CONNECT YOUR BULLPEN")
                        .font(.system(size: 13, weight: .bold, design: .rounded)).tracking(1.5)
                        .foregroundColor(Color.bpBg).frame(maxWidth: .infinity).padding(.vertical, 16)
                        .background(Color.bpGold).cornerRadius(13)
                }
                .padding(.bottom, 12)

                Button(action: onExplore) {
                    Text("Explore a sample team first")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.bpMuted).frame(maxWidth: .infinity).padding(.vertical, 6)
                }

                Spacer()
                Text("BULLPENLM")
                    .font(.system(size: 11, weight: .bold, design: .rounded)).tracking(2)
                    .foregroundColor(.bpGold).frame(maxWidth: .infinity)
            }
            .padding(.horizontal, 28)
        }
    }

    // ascending gold rungs (The Climb)
    private var climb: some View {
        GeometryReader { g in
            let w = g.size.width, h = g.size.height
            Path { p in
                let rungs: [(CGFloat, CGFloat)] = [(0.20, 0.86), (0.30, 0.62), (0.40, 0.40)]
                for (inset, y) in rungs {
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
