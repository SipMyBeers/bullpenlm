import Foundation

/// The shared rank/study contract — see docs/RANK_STUDY_CONTRACT.md.
/// These types decode the canonical payload BOTH surfaces render. The iOS app
/// never knows which backend filled it; it only knows this shape.

struct Rank: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let order: Int
    let comp_label: String
    var xp_hint: Int?          // display-only, optional (BullpenLM ladders only)
}

struct Knowledge: Codable, Hashable {
    let sources_studied: Int
    let sources_total: Int
    let quiz_passed: Bool
    var complete: Bool { sources_studied >= sources_total && quiz_passed }
}

struct Production: Codable, Hashable {
    let sales_this_month: Int
    let threshold: Int
    var met: Bool { sales_this_month >= threshold }
}

/// promotion_check(agent, rank) — contract §3.
struct PromotionCheck: Codable, Hashable {
    let rank: Rank
    let knowledge: Knowledge
    let production: Production
    let eligible: Bool
}

/// The ladder read — rows + the agent's current rank + the active next gate.
struct Ladder: Codable {
    let org_id: String
    let ranks: [Rank]
    let current_order: Int
    let next_check: PromotionCheck?
}
