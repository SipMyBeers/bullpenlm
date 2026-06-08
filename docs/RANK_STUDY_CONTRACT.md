# Rank & Study Contract — v1

The single shape that **both** Kumquat Command (web) and **BullpenLM** (iOS + floor)
read to render rank ladders and promotion gates. Neither surface owns it; both render
it. It is **location-agnostic** — served by whichever spine wins later (BullpenLM's
Python server, Kumquat's D1, or a shared service) behind a thin adapter. Consumers
code against this contract, never against a specific backend.

Status: **stable v1**. Additive changes only (new optional fields). Breaking changes
bump the version and both surfaces pin it.

---

## 1. `rank` — a config row (NOTHING is hardcoded)

A rank ladder is a list of config rows, one ladder per org. BullpenLM's
Rookie→Legend and Kumquat's Agent→Director are the *same engine, different rows*.

```
rank {
  id:         string   // stable slug, e.g. "senior-producer" | "all-star"
  org_id:     string   // which org/bullpen this ladder belongs to
  name:       string   // display, e.g. "Senior Producer"
  order:      int      // 0-based ladder position (0 = entry rank)
  comp_label: string   // human comp tier, e.g. "90% contract" | "Lvl 5"
  gate_rule:  GateRule // what it takes to PROMOTE INTO this rank
}
```

## 2. `GateRule` — the Koscot firewall lives here

```
gate_rule {
  knowledge: {
    source_kind:   "notebook" | "gauntlet"  // where "studied" is measured
    sources_total: int                        // sources/tiers to study for this rank
    quiz_required: bool                        // must pass rank quiz / Tier-3 cert
  }
  production: {
    metric:    "sales"     // ALWAYS personal sales. NEVER recruiting.
    threshold: int          // personal sales required in the window
    window:    "month"      // calendar month
  }
}
```

**INVARIANT (do not violate): `production.metric` is always personal sales.**
Recruiting NEVER gates a comp rank. Recruiting may drive *separate* recognition
titles (Field Trainer, Director-as-honor), but those are not `rank` rows whose
`gate_rule` upgrades commission. This is the Koscot-clean firewall — keep it inside
`gate_rule` so neither surface can accidentally gate comp on downline.

## 3. `promotion_check(agent, rank)` → the payload both scorecards render

```
{
  rank:       { id, name, order, comp_label },
  knowledge:  { sources_studied: int, sources_total: int, quiz_passed: bool },
  production: { sales_this_month: int, threshold: int },
  eligible:   bool
}
```

```
eligible = knowledge.sources_studied >= knowledge.sources_total
           && knowledge.quiz_passed
           && production.sales_this_month >= production.threshold
```

## 4. The two reads a scorecard makes

```
ranks(org_id)                  -> [rank, ...]      // the ladder, ordered by `order`
promotion_check(agent, rank_id)-> payload          // one rank's gate progress
```

A scorecard renders: the **ladder** (rank rows) + the agent's **current rank**
(highest `order` they are already eligible for) + `promotion_check` for the
**next** rank (the active gate, both halves shown).

## 5. How each surface FILLS the contract (adapters)

The payload is identical; only the adapter that fills it differs. The surface never
knows which one ran.

| contract field                 | BullpenLM adapter                         | Kumquat adapter                  |
|--------------------------------|-------------------------------------------|----------------------------------|
| knowledge.sources_studied/total| Gauntlet tiers cleared / required (toppack)| notebook sources studied / total |
| knowledge.quiz_passed          | Tier-3 drill cert cleared                  | rank quiz ≥ 80%                  |
| production.sales_this_month    | `deal_closed_won` events this month        | sales logged this month          |
| production.threshold           | rank's `gate_rule.production.threshold`     | same                             |
| eligible                       | knowledge + production (+ gate cleared)     | knowledge + production           |

## 6. Adapter interface (location-agnostic)

Both surfaces depend on this interface, not a backend:

```
interface PromotionSource {
  ranks(org_id)                    -> [rank]
  promotionCheck(agent, rank_id)   -> payload
}
```

- BullpenLM ships a concrete adapter that reads its own server (toppack / gate /
  audit) — see `server/ranks.py`.
- A **mock** adapter returning this exact shape is the build/test target for any
  consumer before a spine home is chosen.
- When the spine home is decided, only a new adapter is written; no consumer changes.

## 7. Defining a ladder without code (operator path)

An org defines its own ladder by dropping a `ranks.json` at
`bullpens/<slug>/ranks.json` — an array of `rank` rows (§1). No code, no rebuild;
`GET /api/b/<slug>/ranks` serves it immediately and `/promotion/<agent>` evaluates
against it. Absent the file, the BullpenLM default ladder (Rookie→Legend) is used.

Reference example: `docs/examples/ranks.kumquat.json` — Kumquat's Agent → Producer
→ Senior Producer → Field Trainer → Agency Director ladder with contract-% comp
labels. Every `gate_rule` is production-gated on personal sales (Koscot firewall);
notebook study fills `knowledge` via Kumquat's adapter.
