/* BullpenLM — Gauntlet config. Maps the 7 phase tiers to named boss-buyers
 * + taunts + goals for the spawn-floor ladder. Served as .js because the
 * floor static handler serves .html/.js/.css (not .json). Exposes
 * window.BP_GAUNTLET. A sibling gauntlet.json holds the same data for any
 * tooling that wants raw JSON. */
window.BP_GAUNTLET = {
  "tiers": [
    {
      "tier": 1,
      "boss": "The Gatekeeper",
      "taunt": "You've got ten seconds before I hang up. Most people don't make it five.",
      "goal": "Survive the open. Earn the next thirty seconds."
    },
    {
      "tier": 2,
      "boss": "The Brush-Off",
      "taunt": "Not interested. Send me an email. I'm slammed — you know how it is.",
      "goal": "Turn the reflex no into a real conversation."
    },
    {
      "tier": 3,
      "boss": "The Skeptic",
      "taunt": "Fine, you've got my attention. But I doubt you understand what runs my core.",
      "goal": "Find the pain, the champion, and the cost of doing nothing."
    },
    {
      "tier": 4,
      "boss": "The Wall",
      "taunt": "No budget. Too risky. We already have a team. Pick your poison.",
      "goal": "Take every objection head-on without flinching."
    },
    {
      "tier": 5,
      "boss": "The Committee",
      "taunt": "Impress the whole room — and don't you dare just list features at us.",
      "goal": "Demo to value and thread every stakeholder in the building."
    },
    {
      "tier": 6,
      "boss": "The CFO",
      "taunt": "A pilot, you say. Then justify every dollar before I sign anything.",
      "goal": "Structure a paid pilot the numbers can't argue with."
    },
    {
      "tier": 7,
      "boss": "The Closer's Mirror",
      "taunt": "Last stall. Last signature. Beat me and you ARE the closer.",
      "goal": "Kill the stall, get the signature, close the pilot."
    }
  ]
};
