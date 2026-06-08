import SwiftUI

/// Renders any org's rank ladder + the next-rank double gate straight from the
/// contract. Backend-agnostic: hand it any PromotionSource. With
/// MockPromotionSource it shows Kumquat's Agent->Director; with HTTPPromotionSource
/// it shows BullpenLM's Rookie->Legend. Same view, different config.
struct RankLadderView: View {
    let source: PromotionSource
    let agent: String
    @State private var ladder: Ladder?
    @State private var failed = false

    var body: some View {
        ZStack {
            Color.bpBg.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("RANK LADDER").font(.system(size: 11, weight: .bold, design: .monospaced))
                        .tracking(2).foregroundColor(.bpMuted)

                    if let l = ladder {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) { ForEach(l.ranks) { chip($0, current: l.current_order) } }
                        }
                        if let nx = l.next_check { gate(nx) }
                        else { Text("Top of the ladder.").font(.system(.callout, design: .serif)).foregroundColor(.bpMint) }
                    } else if failed {
                        Text("Couldn't load the ladder.").foregroundColor(.bpMuted)
                    } else {
                        ProgressView().tint(.bpGold).padding(.top, 40)
                    }
                }
                .padding(20)
            }
        }
        .task { await load() }
    }

    private func load() async {
        do { ladder = try await source.ladder(agent: agent) } catch { failed = true }
    }

    // A rank chip — cleared (mint) / current (gold) / locked (dim).
    @ViewBuilder private func chip(_ r: Rank, current: Int) -> some View {
        let state = r.order < current ? 0 : (r.order == current ? 1 : 2)   // 0 done,1 cur,2 lock
        VStack(alignment: .leading, spacing: 3) {
            Text(r.name.uppercased()).font(.system(size: 13, weight: .heavy))
                .foregroundColor(state == 1 ? .bpGold : (state == 0 ? .bpMint : .bpMuted))
            Text(r.comp_label).font(.system(size: 9.5, weight: .medium, design: .monospaced))
                .foregroundColor(.bpMuted)
        }
        .padding(.vertical, 9).padding(.horizontal, 12)
        .frame(minWidth: 96, alignment: .leading)
        .background(state == 1 ? Color.bpGold.opacity(0.10) : (state == 0 ? Color.bpMint.opacity(0.08) : Color.clear))
        .overlay(RoundedRectangle(cornerRadius: 11)
            .stroke(state == 1 ? Color.bpGold : (state == 0 ? Color.bpMint.opacity(0.5) : Color.white.opacity(0.12))))
        .cornerRadius(11)
        .opacity(state == 2 ? 0.55 : 1)
    }

    // The next-rank double gate — knowledge + production, from the contract.
    @ViewBuilder private func gate(_ nx: PromotionCheck) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text("Promote to \(nx.rank.name)").font(.system(size: 17, weight: .heavy))
                    .foregroundColor(.bpText)
                Text(nx.eligible ? "ELIGIBLE" : "IN PROGRESS")
                    .font(.system(size: 9.5, weight: .bold, design: .monospaced)).tracking(1)
                    .padding(.vertical, 3).padding(.horizontal, 9)
                    .background((nx.eligible ? Color.bpMint : Color.bpGold).opacity(0.16))
                    .foregroundColor(nx.eligible ? .bpMint : .bpGold).cornerRadius(20)
            }
            Text(nx.rank.comp_label).font(.system(.subheadline, design: .serif)).italic().foregroundColor(.bpMuted)

            gateRow("Knowledge — studied \(nx.knowledge.sources_studied)/\(nx.knowledge.sources_total)\(nx.knowledge.quiz_passed ? " · quiz passed" : " · quiz pending")",
                    ok: nx.knowledge.complete,
                    val: "\(nx.knowledge.sources_studied)/\(nx.knowledge.sources_total)")
            gateRow("Production — sales this month (personal)",
                    ok: nx.production.met,
                    val: "\(nx.production.sales_this_month)/\(nx.production.threshold)")
        }
        .padding(16)
        .background(Color.bpPanel.opacity(0.6))
        .overlay(RoundedRectangle(cornerRadius: 13).stroke(Color.bpGold.opacity(0.35)))
        .cornerRadius(13)
        .padding(.top, 6)
    }

    @ViewBuilder private func gateRow(_ label: String, ok: Bool, val: String) -> some View {
        HStack {
            Text(label).font(.system(size: 13.5)).foregroundColor(.bpText)
            Spacer()
            Text(ok ? "DONE" : val)
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .padding(.vertical, 3).padding(.horizontal, 8)
                .background((ok ? Color.bpMint : Color.bpGold).opacity(0.15))
                .foregroundColor(ok ? .bpMint : .bpGold).cornerRadius(6)
        }
        .padding(.vertical, 8)
        .overlay(Divider().background(Color.white.opacity(0.06)), alignment: .bottom)
    }
}
