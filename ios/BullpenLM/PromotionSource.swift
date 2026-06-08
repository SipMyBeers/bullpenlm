import Foundation

/// Location-agnostic adapter (contract §6). Consumers depend on this protocol,
/// never on a backend. When the spine home is chosen, only a new conformer is
/// written — no view changes.
protocol PromotionSource {
    func ladder(agent: String) async throws -> Ladder
}

/// MOCK adapter — returns Kumquat's Agent->Director ladder in the exact contract
/// shape. Proves the scorecard renders an ARBITRARY org's ladder without any
/// backend. This is the build/test target until the spine home is decided.
struct MockPromotionSource: PromotionSource {
    func ladder(agent: String) async throws -> Ladder {
        let ranks = [
            Rank(id: "agent",           name: "Agent",           order: 0, comp_label: "80% contract"),
            Rank(id: "producer",        name: "Producer",        order: 1, comp_label: "80% contract"),
            Rank(id: "senior-producer", name: "Senior Producer", order: 2, comp_label: "90% contract"),
            Rank(id: "field-trainer",   name: "Field Trainer",   order: 3, comp_label: "100% contract"),
            Rank(id: "agency-director", name: "Agency Director",  order: 4, comp_label: "110% override"),
        ]
        // Mirrors the Academy mockup: knowledge 4/5 + quiz pending, production 7/10.
        let next = PromotionCheck(
            rank: ranks[2],
            knowledge: Knowledge(sources_studied: 4, sources_total: 5, quiz_passed: false),
            production: Production(sales_this_month: 7, threshold: 10),
            eligible: false)
        return Ladder(org_id: "kumquat", ranks: ranks, current_order: 1, next_check: next)
    }
}

/// Real BullpenLM adapter — reads GET /api/b/<bullpen>/promotion/<agent>.
/// One concrete conformer of the same protocol; swap-in when wiring to a spine.
struct HTTPPromotionSource: PromotionSource {
    func ladder(agent: String) async throws -> Ladder {
        guard !Config.bullpen.isEmpty,
              let url = URL(string: Config.base + "/api/b/\(Config.bullpen)/promotion/\(agent)")
        else { throw URLError(.badURL) }
        let (data, _) = try await URLSession.shared.data(from: url)
        return try JSONDecoder().decode(Ladder.self, from: data)
    }
}
